// ============================================================
// L33: std::chrono and Time
// ============================================================
// WHAT: The <chrono> library provides type-safe, unit-safe
//       durations, time points, and clocks. Also covers the
//       CPU timestamp counter (rdtsc) for sub-nanosecond timing.
// WHY (TRADING): Time is everything in HFT.
//   - Order timestamps: regulatory requirement (nanosecond precision)
//   - Latency measurement: tick arrival to order send ("wire-to-order")
//   - Timer events: cancel stale quotes after N µs
//   - Rate limiting: max N orders per second (burst control)
//   - Benchmarking: measure hot-path code in CPU cycles
//   The wrong clock (wall clock vs steady clock) or wrong precision
//   (milliseconds when you need nanoseconds) can break your system.
// PHASE: Modern C++
// ============================================================

/*
  CONCEPT OVERVIEW:

  THREE CLOCKS:
    std::chrono::system_clock:
      - Represents wall-clock time (calendar time, can jump backward on NTP sync)
      - Use for: timestamps that need to represent absolute time of day
      - Resolution: typically microseconds on modern systems
      - Can convert to std::time_t for printing

    std::chrono::steady_clock:
      - NEVER goes backward. Monotonic — only increases.
      - Use for: measuring durations, rate limiting, timeouts
      - Resolution: typically nanoseconds on modern hardware
      - Cannot convert to calendar time (arbitrary epoch)
      *** USE THIS FOR LATENCY MEASUREMENT ***

    std::chrono::high_resolution_clock:
      - May alias steady_clock or system_clock depending on platform
      - Prefer steady_clock explicitly — it's unambiguous

  DURATION TYPES (all in <chrono>):
    std::chrono::nanoseconds     (ns)
    std::chrono::microseconds    (µs)
    std::chrono::milliseconds    (ms)
    std::chrono::seconds         (s)
    std::chrono::minutes
    std::chrono::hours
    std::chrono::duration<Rep, Period>  — generic

  TIME LITERAL SUFFIXES (C++14, namespace std::chrono_literals):
    using namespace std::chrono_literals;
    1ns, 100us, 5ms, 2s, 1h

  DURATION_CAST:
    Must explicitly cast between incompatible durations (truncates):
    auto us = std::chrono::duration_cast<microseconds>(some_nanoseconds);

  TIME POINT:
    auto t = Clock::now();  — current time as a time_point
    Arithmetic: t2 - t1 = duration; t + duration = new time_point

  RDTSC (CPU Timestamp Counter):
    __rdtsc() — reads the CPU's cycle counter register (x86/x86_64)
    Returns: 64-bit count of CPU cycles since last reset
    Nanoseconds = cycles / (cpu_freq_GHz)
    Pros: < 1ns overhead, no syscall, true cycle-level resolution
    Cons: unstable across CPU migrations, frequency scaling, multiple sockets
    Use: microbenchmarks, measuring individual function latency
    Read with CPUID fence for accurate measurement:
      _mm_lfence(); uint64_t t = __rdtsc(); _mm_lfence();

  TRADING USE CASE:
    // Timestamp an order at nanosecond precision
    auto now = std::chrono::steady_clock::now();
    uint64_t timestamp_ns = now.time_since_epoch().count();

    // Measure wire-to-order latency
    auto t0 = std::chrono::steady_clock::now();
    process_tick(tick);
    send_order(order);
    auto t1 = std::chrono::steady_clock::now();
    auto latency_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count();

    // Cancel stale quote after 100µs
    if (t1 - quote_sent_time > 100us) cancel(quote_id);

  COMMON MISTAKES:
    - Using system_clock for latency measurement (NTP can make it go backward)
    - Comparing time_points from different clocks (compiler error)
    - Printing a steady_clock time_point as calendar time (has no meaningful epoch)
    - Using sleep_for in the hot path — the OS wakes you up when it feels like it (~50µs late)
    - Integer overflow: rdtsc runs at ~3 billion ticks/sec; wrap in uint64_t (not int)
*/

#include <iostream>
#include <chrono>
#include <thread>       // std::this_thread::sleep_for
#include <vector>
#include <algorithm>    // std::sort for percentiles
#include <cstdint>
#include <numeric>      // std::accumulate
#include <cmath>        // std::sqrt for stddev

// rdtsc is x86/x86_64 specific
#if defined(__x86_64__) || defined(_M_X64) || defined(__i386__) || defined(_M_IX86)
#  include <intrin.h>    // MSVC: __rdtsc()
#  define HAS_RDTSC 1
#else
#  define HAS_RDTSC 0
#endif

using namespace std::chrono_literals;

// ============================================================
// HELPERS
// ============================================================

// Get current time as nanoseconds since epoch (steady_clock)
uint64_t now_ns() {
    using namespace std::chrono;
    return static_cast<uint64_t>(
        duration_cast<nanoseconds>(
            steady_clock::now().time_since_epoch()
        ).count()
    );
}

// Get wall-clock time as nanoseconds since Unix epoch (for exchange timestamps)
uint64_t wall_ns() {
    using namespace std::chrono;
    return static_cast<uint64_t>(
        duration_cast<nanoseconds>(
            system_clock::now().time_since_epoch()
        ).count()
    );
}

// ============================================================
// LATENCY SAMPLER
// ============================================================

// Collects latency samples and prints percentile statistics
// Used to measure wire-to-order latency distribution
class LatencyStats {
public:
    void record(uint64_t ns) { samples_.push_back(ns); }

    void print(const std::string& label) const {
        if (samples_.empty()) return;

        std::vector<uint64_t> sorted = samples_;
        std::sort(sorted.begin(), sorted.end());

        auto n    = sorted.size();
        double avg = std::accumulate(sorted.begin(), sorted.end(), 0.0) / n;
        double p50 = sorted[n * 50 / 100];
        double p99 = sorted[n * 99 / 100];
        double p999 = sorted[n * 999 / 1000 < n ? n * 999 / 1000 : n - 1];
        double max = sorted.back();

        std::cout << "[" << label << "] n=" << n
                  << " avg=" << avg << "ns"
                  << " p50=" << p50 << "ns"
                  << " p99=" << p99 << "ns"
                  << " p99.9=" << p999 << "ns"
                  << " max=" << max << "ns\n";
    }

private:
    std::vector<uint64_t> samples_;
};

// ============================================================
// RATE LIMITER
// ============================================================

// Limits orders to max_per_second using steady_clock
// Token bucket approach: refill at fixed rate, reject when empty
class RateLimiter {
public:
    explicit RateLimiter(int max_per_second)
        : max_tokens_(max_per_second)
        , tokens_(max_per_second)
        , refill_interval_ns_(1'000'000'000LL / max_per_second)
        , last_refill_(std::chrono::steady_clock::now())
    {}

    bool try_consume() {
        // Refill tokens based on elapsed time
        auto now = std::chrono::steady_clock::now();
        auto elapsed_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
            now - last_refill_).count();

        if (elapsed_ns >= refill_interval_ns_) {
            int64_t new_tokens = elapsed_ns / refill_interval_ns_;
            tokens_ = std::min(tokens_ + static_cast<int>(new_tokens), max_tokens_);
            last_refill_ = now;
        }

        if (tokens_ > 0) {
            --tokens_;
            return true;   // OK to send
        }
        return false;      // rate limit exceeded
    }

private:
    int         max_tokens_;
    int         tokens_;
    int64_t     refill_interval_ns_;
    std::chrono::steady_clock::time_point last_refill_;
};

// ============================================================
// SCOPED TIMER — RAII latency measurement
// ============================================================

class ScopedTimer {
public:
    explicit ScopedTimer(const std::string& label, LatencyStats* stats = nullptr)
        : label_(label), stats_(stats), start_(std::chrono::steady_clock::now()) {}

    ~ScopedTimer() {
        auto end = std::chrono::steady_clock::now();
        auto ns  = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start_).count();
        if (stats_) {
            stats_->record(static_cast<uint64_t>(ns));
        } else {
            std::cout << "[" << label_ << "] " << ns << "ns\n";
        }
    }

private:
    std::string                            label_;
    LatencyStats*                          stats_;
    std::chrono::steady_clock::time_point  start_;
};

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // CLOCK TYPES AND RESOLUTION
    // -------------------------------------------------------

    std::cout << "=== Clock properties ===\n";

    {
        // Is steady_clock actually steady (monotonic)?
        std::cout << "  steady_clock::is_steady: "
                  << std::chrono::steady_clock::is_steady << "\n";
        std::cout << "  system_clock::is_steady: "
                  << std::chrono::system_clock::is_steady << "\n";

        // Get current time from each clock
        auto t_steady = std::chrono::steady_clock::now();
        auto t_system = std::chrono::system_clock::now();

        // Convert system_clock to time_t for calendar display
        std::time_t t_c = std::chrono::system_clock::to_time_t(t_system);
        std::cout << "  Wall time: " << std::ctime(&t_c);

        // Steady clock: nanoseconds since some arbitrary epoch
        uint64_t steady_ns = static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(
                t_steady.time_since_epoch()).count());
        std::cout << "  Steady ns since epoch: " << steady_ns << "\n";
    }

    // -------------------------------------------------------
    // DURATION TYPES AND LITERALS
    // -------------------------------------------------------

    std::cout << "\n=== Duration types ===\n";

    {
        using namespace std::chrono;

        // Duration literals (C++14)
        auto one_sec     = 1s;
        auto half_ms     = 500us;
        auto hundred_ns  = 100ns;

        std::cout << "  1s    = " << duration_cast<nanoseconds>(one_sec).count() << "ns\n";
        std::cout << "  500µs = " << duration_cast<nanoseconds>(half_ms).count() << "ns\n";
        std::cout << "  100ns = " << duration_cast<nanoseconds>(hundred_ns).count() << "ns\n";

        // Arithmetic between durations
        auto total = 1ms + 500us + 200ns;
        std::cout << "  1ms + 500µs + 200ns = "
                  << duration_cast<nanoseconds>(total).count() << "ns\n";

        // duration_cast: truncates (floors) when converting to coarser unit
        nanoseconds precise_ns = 1500ns;
        microseconds truncated = duration_cast<microseconds>(precise_ns);
        std::cout << "  1500ns → " << truncated.count() << "µs (truncated)\n";
    }

    // -------------------------------------------------------
    // MEASURING LATENCY
    // -------------------------------------------------------

    std::cout << "\n=== Measuring latency ===\n";

    {
        // Measure a simulated "tick processing + order send" path
        auto t0 = std::chrono::steady_clock::now();

        // Simulate some work (in reality: parse tick, evaluate signal, prepare order)
        volatile double sum = 0.0;  // volatile: prevent compiler from eliminating the loop
        for (int i = 0; i < 1000; ++i) sum += i * 0.001;

        auto t1 = std::chrono::steady_clock::now();

        auto elapsed_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count();
        auto elapsed_us = std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0).count();

        std::cout << "  Simulated tick processing: " << elapsed_ns << "ns ("
                  << elapsed_us << "µs)\n";
    }

    // -------------------------------------------------------
    // SCOPED TIMER
    // -------------------------------------------------------

    std::cout << "\n=== ScopedTimer ===\n";

    {
        {
            ScopedTimer t("risk_check");
            // Simulate risk check work
            volatile int x = 0;
            for (int i = 0; i < 100; ++i) x += i;
        }

        LatencyStats stats;
        for (int i = 0; i < 10; ++i) {
            ScopedTimer t("iteration", &stats);
            volatile double d = 0.0;
            for (int j = 0; j < 500; ++j) d += j * 0.01;
        }
        stats.print("iteration");
    }

    // -------------------------------------------------------
    // RATE LIMITER
    // -------------------------------------------------------

    std::cout << "\n=== Rate limiter (100/sec) ===\n";

    {
        RateLimiter limiter(5);  // 5 orders/sec for demo (would be 100 in real use)

        int accepted = 0, rejected = 0;
        for (int i = 0; i < 20; ++i) {
            if (limiter.try_consume()) {
                ++accepted;
            } else {
                ++rejected;
            }
        }
        std::cout << "  20 attempts: " << accepted << " accepted, "
                  << rejected << " rate-limited\n";
    }

    // -------------------------------------------------------
    // STALE QUOTE DETECTION
    // -------------------------------------------------------

    std::cout << "\n=== Stale quote detection ===\n";

    {
        auto quote_time = std::chrono::steady_clock::now();

        // Simulate some processing time
        std::this_thread::sleep_for(2ms);

        auto now = std::chrono::steady_clock::now();
        auto age = std::chrono::duration_cast<std::chrono::microseconds>(now - quote_time);

        constexpr auto STALE_THRESHOLD = 1000us;  // cancel if older than 1ms
        if (age > STALE_THRESHOLD) {
            std::cout << "  Quote is stale: age=" << age.count() << "µs — cancel\n";
        } else {
            std::cout << "  Quote is fresh: age=" << age.count() << "µs\n";
        }
    }

    // -------------------------------------------------------
    // RDTSC — CPU cycle counter
    // -------------------------------------------------------

    std::cout << "\n=== rdtsc CPU cycle counter ===\n";

#if HAS_RDTSC
    {
        // Measure how many cycles a simple function takes
        // _mm_lfence ensures instructions before rdtsc complete first
        // (prevents CPU reordering from contaminating the measurement)

        uint64_t t0 = __rdtsc();

        // Work to measure
        volatile double sum = 0.0;
        for (int i = 0; i < 100; ++i) sum += i;

        uint64_t t1 = __rdtsc();
        uint64_t cycles = t1 - t0;

        // At 3GHz: 1 cycle ≈ 0.33ns; at 4GHz: 1 cycle ≈ 0.25ns
        // Estimate ns: cycles / GHz (rough — accurate if you know CPU freq)
        std::cout << "  100 iterations: ~" << cycles << " CPU cycles\n";
        std::cout << "  Approx ns at 3GHz: " << cycles / 3 << "ns\n";

        // Measure overhead of rdtsc itself
        uint64_t r0 = __rdtsc();
        uint64_t r1 = __rdtsc();
        std::cout << "  rdtsc overhead: " << (r1 - r0) << " cycles\n";
    }
#else
    std::cout << "  rdtsc not available on this architecture\n";
#endif

    // -------------------------------------------------------
    // TIMESTAMP AN ORDER (wall clock for exchange)
    // -------------------------------------------------------

    std::cout << "\n=== Order timestamps ===\n";

    {
        // Regulatory timestamps: use system_clock (wall time, UTC)
        uint64_t order_ts_ns = wall_ns();
        std::cout << "  Order timestamp (system_clock ns): " << order_ts_ns << "\n";

        // Internal latency: use steady_clock
        uint64_t internal_ts = now_ns();
        std::cout << "  Internal timestamp (steady_clock ns): " << internal_ts << "\n";

        // The difference: how far the steady_clock epoch is from Unix epoch
        // (This varies per process start — not meaningful for calendar time)
        int64_t diff_ms = static_cast<int64_t>((order_ts_ns - internal_ts) / 1'000'000LL);
        std::cout << "  Epoch difference: ~" << diff_ms / 1000 << " seconds\n";
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Full latency measurement pipeline for a feed handler:

        // Event: packet arrives from exchange
        uint64_t t_packet_arrival = __rdtsc();

        // Parse ITCH message from raw bytes
        auto msg = itch_parser_.parse(recv_buf, bytes);
        uint64_t t_parsed = __rdtsc();

        // Update local order book
        order_book_.apply(msg);
        uint64_t t_book_updated = __rdtsc();

        // Evaluate strategy signal
        auto signal = strategy_.evaluate(order_book_.bbo());
        uint64_t t_signal = __rdtsc();

        // Submit order if signal exists
        if (signal) {
            gateway_.send(make_order(*signal));
        }
        uint64_t t_order_sent = __rdtsc();

        // Record per-tick latency breakdown in ring buffer (async logging later)
        latency_log_.record({
            t_parsed        - t_packet_arrival,   // parse time
            t_book_updated  - t_parsed,            // book update
            t_signal        - t_book_updated,      // signal eval
            t_order_sent    - t_signal,            // order routing
            t_order_sent    - t_packet_arrival,    // total wire-to-order
        });

        // After market close: print percentiles for each component
        latency_log_.print_percentiles();
    */
}
