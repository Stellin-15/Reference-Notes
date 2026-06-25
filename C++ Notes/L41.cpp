// ============================================================
// L41: Busy Waiting and Spin Loops
// ============================================================
// WHAT: A spin loop (busy wait) repeatedly checks a condition
//       without yielding the CPU, as opposed to sleeping and
//       being woken up by the OS. The CPU instruction _mm_pause()
//       (PAUSE on x86) hints the CPU to avoid speculative
//       execution hazards and reduce power during spinning.
// WHY (TRADING): The OS scheduler has 50–200µs wakeup latency.
//   If a tick arrives and your thread is sleeping, you're 50µs
//   late before you even look at the tick. In HFT, that means
//   a competitor fills the order before you.
//   A spin loop on a dedicated pinned core checks every ~1ns.
//   Total latency: recv → spin → detect → process ≈ 100ns.
//   The cost: one CPU core burning 100% CPU doing nothing
//   useful while waiting. On dedicated trading hardware with
//   isolated cores, this is completely acceptable.
// PHASE: Concurrency
// ============================================================

/*
  CONCEPT OVERVIEW:

  SPINNING vs SLEEPING:
    Sleeping (condition_variable / sleep_for):
      - Thread gives up the CPU, OS wakes it later
      - Wakeup latency: 50–200µs (SCHED_OTHER) or ~5–50µs (SCHED_FIFO)
      - CPU usage: 0% while sleeping
      - Use for: slow paths (logging, EOD, UI, operator console)

    Spinning (busy wait):
      - Thread loops checking a flag, never gives up the CPU
      - Response latency: < 1µs (limited by memory ordering)
      - CPU usage: 100% on that core
      - Use for: hot paths on dedicated isolated pinned cores

  _MM_PAUSE() / PAUSE instruction:
    Tells the CPU: "I'm spinning — optimize accordingly."
    Benefits:
    1. Reduces pipeline mis-speculation: CPU knows the next iteration
       depends on memory state, so it won't speculate as aggressively.
    2. Improves hyperthreading: surrenders execution slots to sibling
       hyperthread during the pause (~30-70 cycles).
    3. Reduces power consumption slightly.
    4. Makes the memory bus available sooner for the writing thread.
    Cost: ~5–15 ns per pause (vs 1–2 ns per empty loop iteration).
    ALWAYS use _mm_pause() in spin loops — never spin with a bare loop.

  SPIN WITH BACKOFF:
    After N failed spins, sleep briefly (std::this_thread::yield or sleep).
    Reduces power and cache pressure when wait is long.
    Adaptive backoff: start with pause, then yield, then sleep.
    Not used in pure HFT hot paths — only in hybrid approaches.

  WHEN TO STOP SPINNING (decide at design time):
    Pure spin: isolated core, dedicated thread, low-latency requirement
    Spin-then-sleep: shared core, latency can tolerate occasional ms delay
    Pure sleep: background thread, latency doesn't matter

  POWER vs LATENCY TRADEOFF:
    Pure spin: minimum latency, maximum CPU usage (one core)
    Sleep:     near-zero CPU usage, high latency variance
    Yield:     moderate CPU (shares core), moderate latency

  MEMORY ORDER IN SPIN LOOPS:
    while (!flag.load(memory_order_acquire)) { _mm_pause(); }
    acquire: ensures data written before flag.store(release) is visible here.
    relaxed: wrong — you may spin forever seeing a stale flag value.

  TRADING USE CASE:
    // Feed thread: spin on the receive buffer until a packet arrives
    while (running_) {
        int bytes = recv(sock_, buf_, sizeof(buf_), MSG_DONTWAIT);
        if (bytes > 0) {
            process_packet(buf_, bytes);
        } else {
            _mm_pause();   // no packet — hint CPU and try again
        }
    }

    // Strategy thread: spin on SPSC queue waiting for ticks
    Tick t;
    while (running_) {
        if (tick_queue_.pop(t)) {
            strategy_.on_tick(t);
        } else {
            _mm_pause();
        }
    }

  COMMON MISTAKES:
    - Spinning on a shared core (hurts the other thread on the same core)
    - Spinning without _mm_pause() — wastes execution slots on sibling hyperthread
    - Not using memory_order_acquire on the flag load — may never see the update
    - Long compute in the spin loop — should be nearly empty (check, pause, loop)
    - No runnable check — the spin loop must have a way to exit cleanly on shutdown
*/

#include <iostream>
#include <atomic>
#include <thread>
#include <chrono>
#include <vector>
#include <cstdint>
#include <cassert>

// PAUSE instruction (x86/x86_64)
#if defined(__x86_64__) || defined(_M_X64) || defined(__i386__) || defined(_M_IX86)
#  include <immintrin.h>
#  define CPU_PAUSE() _mm_pause()
#  define HAS_PAUSE 1
#else
#  define CPU_PAUSE() std::this_thread::yield()
#  define HAS_PAUSE 0
#endif

using namespace std::chrono_literals;

// ============================================================
// SPIN LOCK — demonstrate the spin primitive
// ============================================================

// A spinlock: busily spins until the lock is acquired.
// Useful for very short critical sections (< 50ns of work).
// For longer critical sections: use std::mutex instead.
class SpinLock {
public:
    void lock() noexcept {
        // Exchange: if locked_ was false, set to true (acquired).
        // If it was already true, keep trying.
        while (locked_.exchange(true, std::memory_order_acquire)) {
            // Spin with pause: hint CPU while waiting
            while (locked_.load(std::memory_order_relaxed)) {
                CPU_PAUSE();   // inner loop: don't exchange every iteration
            }
        }
    }

    void unlock() noexcept {
        locked_.store(false, std::memory_order_release);
    }

    bool try_lock() noexcept {
        return !locked_.load(std::memory_order_relaxed)
            && !locked_.exchange(true, std::memory_order_acquire);
    }

private:
    std::atomic<bool> locked_{false};
};

// RAII guard for SpinLock (same interface as lock_guard)
class SpinLockGuard {
public:
    explicit SpinLockGuard(SpinLock& sl) : sl_(sl) { sl_.lock(); }
    ~SpinLockGuard() { sl_.unlock(); }
    SpinLockGuard(const SpinLockGuard&)            = delete;
    SpinLockGuard& operator=(const SpinLockGuard&) = delete;
private:
    SpinLock& sl_;
};

// ============================================================
// SPIN WAIT — wait for a flag with pause
// ============================================================

// Wait until flag becomes true (producer set it with release)
// Returns the number of pause iterations needed
uint64_t spin_wait_for(std::atomic<bool>& flag) {
    uint64_t iters = 0;
    while (!flag.load(std::memory_order_acquire)) {
        CPU_PAUSE();
        ++iters;
    }
    return iters;
}

// Adaptive wait: spin briefly, then yield, then sleep
// Better for shared cores or when latency tolerance is moderate
void adaptive_wait(std::atomic<bool>& flag) {
    const int SPIN_ITERS  = 1000;   // try this many times before yielding
    const int YIELD_ITERS = 100;    // then yield this many times before sleeping

    for (int i = 0; i < SPIN_ITERS; ++i) {
        if (flag.load(std::memory_order_acquire)) return;
        CPU_PAUSE();
    }
    for (int i = 0; i < YIELD_ITERS; ++i) {
        if (flag.load(std::memory_order_acquire)) return;
        std::this_thread::yield();
    }
    while (!flag.load(std::memory_order_acquire)) {
        std::this_thread::sleep_for(100us);
    }
}

// ============================================================
// SIMULATED MARKET DATA RECEIVER
// ============================================================

struct Tick {
    uint64_t seq;
    int64_t  price;
    int32_t  qty;
};

// Simulates a feed handler that spins waiting for the next tick
class SpinFeedHandler {
public:
    SpinFeedHandler() : running_(false), ticks_received_(0) {}

    void start() {
        running_.store(true, std::memory_order_release);
        thread_ = std::thread([this]() { run(); });
    }

    void stop() {
        running_.store(false, std::memory_order_release);
        if (thread_.joinable()) thread_.join();
    }

    void inject_tick(const Tick& t) {
        // Simulate a tick arriving from the network buffer
        pending_tick_   = t;
        tick_available_.store(true, std::memory_order_release);  // signal
    }

    int ticks_received() const {
        return ticks_received_.load(std::memory_order_relaxed);
    }

private:
    void run() {
        // This is the hot-path spin loop — stays here 100% of the time
        while (running_.load(std::memory_order_relaxed)) {
            // Check if a tick is available (spin with pause)
            if (tick_available_.load(std::memory_order_acquire)) {
                process_tick(pending_tick_);
                tick_available_.store(false, std::memory_order_release);
                ticks_received_.fetch_add(1, std::memory_order_relaxed);
            } else {
                CPU_PAUSE();   // no tick — pause and try again
            }
        }
    }

    void process_tick(const Tick& t) {
        // Simulate very fast tick processing (no I/O, no allocation)
        volatile int64_t mid = (t.price * 2);   // dummy work
        (void)mid;
    }

    std::atomic<bool>     running_;
    std::atomic<bool>     tick_available_{false};
    std::atomic<int>      ticks_received_{0};
    Tick                  pending_tick_{};
    std::thread           thread_;
};

// ============================================================
// BENCHMARK: spin vs sleep latency
// ============================================================

struct LatencyResult {
    double min_ns, max_ns, avg_ns;
};

LatencyResult measure_response_latency(bool use_spin, int samples) {
    std::atomic<bool> signal{false};
    std::atomic<uint64_t> response_time_sum{0};
    uint64_t min_ns = UINT64_MAX, max_ns = 0;
    std::vector<uint64_t> latencies(samples);

    // Responder thread: waits for signal, records latency
    std::thread responder([&signal, &latencies, use_spin, samples]() {
        for (int i = 0; i < samples; ++i) {
            // Wait for signal
            if (use_spin) {
                while (!signal.load(std::memory_order_acquire)) CPU_PAUSE();
            } else {
                // Sleep-based: poll every 10µs
                while (!signal.load(std::memory_order_acquire)) {
                    std::this_thread::sleep_for(10us);
                }
            }
            latencies[i] = 1;   // just mark that we received it
            signal.store(false, std::memory_order_release);
        }
    });

    std::vector<uint64_t> delays(samples);

    // Signaler thread: fires signal and measures round-trip
    for (int i = 0; i < samples; ++i) {
        auto t0 = std::chrono::steady_clock::now();
        signal.store(true, std::memory_order_release);
        // Wait for responder to clear the signal
        while (signal.load(std::memory_order_acquire)) CPU_PAUSE();
        auto t1 = std::chrono::steady_clock::now();
        uint64_t ns = static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());
        delays[i] = ns;
        if (ns < min_ns) min_ns = ns;
        if (ns > max_ns) max_ns = ns;
        std::this_thread::sleep_for(50us);  // space out signals
    }

    responder.join();

    double sum = 0.0;
    for (uint64_t d : delays) sum += d;
    return {static_cast<double>(min_ns), static_cast<double>(max_ns), sum / samples};
}

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // SPIN LOCK BASIC TEST
    // -------------------------------------------------------

    std::cout << "=== SpinLock ===\n";

    {
        SpinLock sl;
        int counter = 0;
        std::vector<std::thread> threads;

        for (int i = 0; i < 4; ++i) {
            threads.emplace_back([&sl, &counter]() {
                for (int j = 0; j < 1000; ++j) {
                    SpinLockGuard guard(sl);
                    ++counter;
                }
            });
        }
        for (auto& t : threads) t.join();
        std::cout << "  Final counter (4 threads × 1000): " << counter
                  << " (expected 4000)\n";
    }

    // -------------------------------------------------------
    // SPIN WAIT FOR FLAG
    // -------------------------------------------------------

    std::cout << "\n=== Spin wait for flag ===\n";

    {
        std::atomic<bool> flag{false};
        uint64_t spin_count = 0;

        auto t0 = std::chrono::steady_clock::now();

        std::thread setter([&flag]() {
            std::this_thread::sleep_for(1ms);   // delay 1ms
            flag.store(true, std::memory_order_release);
        });

        spin_count = spin_wait_for(flag);

        auto t1 = std::chrono::steady_clock::now();
        auto wait_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count();

        setter.join();
        std::cout << "  Waited " << wait_ns << "ns, " << spin_count << " spin iterations\n";
    }

    // -------------------------------------------------------
    // FEED HANDLER SPIN LOOP
    // -------------------------------------------------------

    std::cout << "\n=== Spin feed handler ===\n";

    {
        SpinFeedHandler feed;
        feed.start();

        // Inject 5 ticks from another thread
        auto t0 = std::chrono::steady_clock::now();
        for (int i = 0; i < 5; ++i) {
            feed.inject_tick({uint64_t(i), int64_t(1825000 + i * 100), 100});
            std::this_thread::sleep_for(1ms);
        }
        std::this_thread::sleep_for(5ms);
        feed.stop();
        auto t1 = std::chrono::steady_clock::now();

        std::cout << "  Ticks injected: 5\n";
        std::cout << "  Ticks received: " << feed.ticks_received() << "\n";
        std::cout << "  Total time: "
                  << std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count()
                  << "ms\n";
    }

    // -------------------------------------------------------
    // LATENCY: SPIN vs SLEEP
    // -------------------------------------------------------

    std::cout << "\n=== Response latency: spin vs sleep ===\n";

    {
        const int SAMPLES = 100;

        auto spin_result  = measure_response_latency(true,  SAMPLES);
        auto sleep_result = measure_response_latency(false, SAMPLES);

        auto print = [](const std::string& label, const LatencyResult& r) {
            std::cout << "  [" << label << "] "
                      << "min=" << r.min_ns << "ns "
                      << "avg=" << r.avg_ns << "ns "
                      << "max=" << r.max_ns << "ns\n";
        };
        print("spin ", spin_result);
        print("sleep", sleep_result);
    }

    // -------------------------------------------------------
    // PAUSE INSTRUCTION INFO
    // -------------------------------------------------------

    std::cout << "\n=== _mm_pause() info ===\n";

#if HAS_PAUSE
    std::cout << "  _mm_pause() available (x86/x86_64)\n";
    // Measure cost of one pause instruction
    const int N = 1000000;
    auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < N; ++i) _mm_pause();
    auto t1 = std::chrono::steady_clock::now();
    auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count();
    std::cout << "  " << N << " _mm_pause() calls: " << ns << "ns total\n";
    std::cout << "  Per pause: " << ns / N << "ns (~5-15ns typical)\n";
#else
    std::cout << "  _mm_pause() not available — using yield() instead\n";
#endif

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      The production hot-path loop for a market data feed thread:

        void FeedThread::run() {
            // Thread is pinned to isolated core, SCHED_FIFO priority 99
            // Never sleeps. Never calls malloc. Never takes a mutex.

            while (running_.load(std::memory_order_relaxed)) {

                // Try to receive a UDP packet (non-blocking)
                int bytes = recv(udp_sock_, recv_buf_, sizeof(recv_buf_), MSG_DONTWAIT);

                if (bytes > 0) {
                    // Packet arrived — process immediately
                    uint32_t seq = parse_sequence(recv_buf_);

                    if (seq != expected_seq_) {
                        gap_detected_ = true;   // request retransmission
                    }
                    expected_seq_ = seq + 1;

                    // Parse ITCH message and push to book thread's SPSC queue
                    auto msg = itch_parser_.parse(recv_buf_, bytes);
                    while (!feed_to_book_.push(msg)) {
                        CPU_PAUSE();   // book thread is slow — wait
                    }
                } else {
                    // No packet — spin with pause (back off to reduce bus traffic)
                    _mm_pause();
                    _mm_pause();
                    _mm_pause();
                }
            }
        }

        // Total latency from packet arrival to SPSC push: ~50-200ns
        // This thread never sleeps — it's always checking for the next packet.
    */
}
