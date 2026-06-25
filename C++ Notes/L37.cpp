// ============================================================
// L37: std::atomic and Memory Ordering
// ============================================================
// WHAT: std::atomic<T> provides lock-free, thread-safe read and
//       write operations on a single value. Memory ordering
//       controls how atomic operations interact with surrounding
//       non-atomic reads and writes across CPU cores.
// WHY (TRADING): Atomics are the foundation of low-latency
//   concurrency. An atomic position counter, an atomic sequence
//   number, or an atomic kill-switch flag all update in < 5ns
//   with no lock contention. Memory ordering lets you choose
//   exactly how much synchronization you pay for:
//   - relaxed: cheapest (~1ns) — just atomicity, no ordering
//   - acquire/release: directional fence (~3ns) — most HFT use
//   - seq_cst: sequential consistency (~5-10ns) — safe default
//   In the hot path (tick → signal → order), every nanosecond
//   counts. Understand memory ordering to make the right choice.
// PHASE: Concurrency
// ============================================================

/*
  CONCEPT OVERVIEW:

  WHAT IS AN ATOMIC?
    A single variable that any number of threads can read or write
    simultaneously WITHOUT a mutex, with guaranteed no torn reads/writes.
    A torn read: thread reads half of a 64-bit value while another thread
    is writing the other half → garbage. Atomics prevent this.

  KEY OPERATIONS:
    atomic<T> a{initial};
    a.store(val, order)          — write val
    a.load(order)                — read val
    a.exchange(val, order)       — write val, return old val
    a.compare_exchange_strong(expected, desired, order) — CAS
    a.fetch_add(n, order)        — add n, return old value (like i++)
    a.fetch_sub(n, order)        — subtract n
    a.fetch_and/or/xor(n, order) — bitwise ops

  IS_LOCK_FREE:
    a.is_lock_free()             — true if hardware-native (no hidden mutex)
    On x86_64: bool, int, int64_t are all lock-free.

  MEMORY ORDERING (from weakest to strongest):
    memory_order_relaxed:
      Just atomicity. No ordering constraints at all.
      Use for: independent counters, statistics, kill-switch WRITE.
      Example: seq_num.fetch_add(1, relaxed) — just increment atomically.

    memory_order_acquire:
      This LOAD must happen before all subsequent reads/writes in this thread.
      Pairs with release on the other thread.
      Use for: "reader" side of a flag — load the flag, then read the data.

    memory_order_release:
      All prior reads/writes in this thread happen before this STORE.
      Pairs with acquire on the other thread.
      Use for: "writer" side of a flag — write the data, then set the flag.

    memory_order_acq_rel:
      Both acquire and release on a single atomic RMW operation.
      Use for: exchange, compare_exchange in a lock-free queue.

    memory_order_seq_cst:
      Total global ordering — all threads see all seq_cst operations
      in the same order. Safest but slowest.
      This is the DEFAULT if you don't specify.

  ACQUIRE-RELEASE PATTERN (the most important HFT pattern):
    Thread A (producer):
        data = 42;                              // 1. write data
        flag.store(true, release);              // 2. set flag (release)

    Thread B (consumer):
        while (!flag.load(acquire)) {}          // 3. wait for flag (acquire)
        use(data);                              // 4. now data is visible

    Guarantee: step 1 is visible before step 4. No race condition.

  COMPARE-AND-SWAP (CAS):
    bool compare_exchange_strong(T& expected, T desired, order):
      - If atomic == expected: atomically set to desired, return true
      - If atomic != expected: load current value into expected, return false
    Use for: lock-free data structures, optimistic updates.

  TRADING USE CASE:
    std::atomic<bool>    kill_switch_{false};   // any thread can kill
    std::atomic<int64_t> seq_num_{0};           // unique order IDs
    std::atomic<int64_t> position_{0};          // net position (hot read)
    std::atomic<bool>    data_ready_{false};    // producer-consumer flag

    // Hot path: atomic position update (no mutex)
    position_.fetch_add(delta, std::memory_order_relaxed);

  COMMON MISTAKES:
    - Assuming default (seq_cst) is free — it adds a full memory fence on x86
    - Using relaxed on the flag in a producer-consumer pattern → data not visible
    - compare_exchange in a loop forgetting to update expected after failure
    - Treating atomic<struct> as lock-free when struct > 8 bytes (it's not)
    - Using atomic<double> for prices — use atomic<int64_t> (ticks)
*/

#include <iostream>
#include <atomic>
#include <thread>
#include <vector>
#include <chrono>
#include <cstdint>
#include <cassert>

using namespace std::chrono_literals;

// ============================================================
// ATOMIC POSITION TRACKER
// ============================================================

class AtomicPosition {
public:
    // Hot read: strategy needs current position every tick
    int64_t get() const {
        return pos_.load(std::memory_order_relaxed);  // no ordering needed
    }

    // Hot write: fill handler updates on every fill
    void on_fill(int64_t delta) {
        pos_.fetch_add(delta, std::memory_order_relaxed);
    }

    // Risk check: load with relaxed (just a snapshot, ordering doesn't matter)
    bool is_flat() const {
        return pos_.load(std::memory_order_relaxed) == 0;
    }

private:
    std::atomic<int64_t> pos_{0};
};

// ============================================================
// KILL SWITCH — any thread can activate, all threads check
// ============================================================

class KillSwitch {
public:
    // Activate from any thread (risk, operator console, timer)
    void activate(const std::string& reason) {
        // Release: all prior writes visible before this store
        killed_.store(true, std::memory_order_release);
        std::cout << "  [KillSwitch] ACTIVATED: " << reason << "\n";
    }

    // Check from any thread — hot path
    bool is_active() const {
        // Acquire: after this load, subsequent reads see the kill state
        return killed_.load(std::memory_order_acquire);
    }

    void reset() {
        killed_.store(false, std::memory_order_release);
    }

private:
    std::atomic<bool> killed_{false};
};

// ============================================================
// ORDER ID GENERATOR — atomic sequence number
// ============================================================

class OrderIdGenerator {
public:
    // Thread-safe, returns a globally unique, monotonically increasing ID
    uint64_t next() {
        // relaxed: just need atomicity, not ordering
        // (the ID itself doesn't synchronize any other data)
        return seq_.fetch_add(1, std::memory_order_relaxed);
    }

    uint64_t current() const {
        return seq_.load(std::memory_order_relaxed);
    }

private:
    std::atomic<uint64_t> seq_{1000000};   // start at 1M to distinguish from test IDs
};

// ============================================================
// PRODUCER-CONSUMER — acquire/release flag
// ============================================================

struct MarketData {
    int64_t bid = 0, ask = 0;
    int32_t bid_qty = 0, ask_qty = 0;
};

class DataChannel {
public:
    // PRODUCER (feed thread): write data, then signal ready
    void publish(const MarketData& d) {
        data_ = d;                                          // 1. write data (non-atomic)
        ready_.store(true, std::memory_order_release);      // 2. signal (release fence)
        // release fence: guarantees step 1 is visible before step 2 to any thread
        // that reads ready_ with acquire
    }

    // CONSUMER (strategy thread): wait for signal, then read data
    bool try_consume(MarketData& out) {
        if (!ready_.load(std::memory_order_acquire)) {     // 3. check signal (acquire fence)
            return false;
        }
        // acquire fence: guarantees data_ writes from producer are now visible here
        out = data_;                                        // 4. read data
        ready_.store(false, std::memory_order_release);    // 5. reset for next publish
        return true;
    }

private:
    MarketData            data_{};
    std::atomic<bool>     ready_{false};
};

// ============================================================
// COMPARE-AND-SWAP — optimistic update example
// ============================================================

// A lock-free "best bid" tracker using CAS
// Only updates if the new bid is higher (optimistic, no mutex)
class LockFreeBestBid {
public:
    int64_t get() const {
        return best_bid_.load(std::memory_order_relaxed);
    }

    // Update best bid only if new_bid > current best
    bool update_if_better(int64_t new_bid) {
        int64_t current = best_bid_.load(std::memory_order_relaxed);
        while (new_bid > current) {
            // CAS: if best_bid_ still == current, set to new_bid (returns true)
            //      if another thread changed it, current is updated, retry
            if (best_bid_.compare_exchange_weak(
                    current,      // expected (updated on failure)
                    new_bid,      // desired
                    std::memory_order_release,   // success ordering
                    std::memory_order_relaxed))  // failure ordering
            {
                return true;   // we successfully set the new best bid
            }
            // current was updated to the latest value — loop checks again
        }
        return false;   // new_bid was not better than current best
    }

private:
    std::atomic<int64_t> best_bid_{0};
};

// ============================================================
// BENCHMARK: relaxed vs seq_cst
// ============================================================

void bench_atomic(const std::string& label,
                  std::memory_order store_order,
                  std::memory_order load_order,
                  int iters)
{
    std::atomic<int64_t> counter{0};
    auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < iters; ++i) {
        counter.store(i, store_order);
        int64_t v = counter.load(load_order);
        (void)v;
    }
    auto t1 = std::chrono::steady_clock::now();
    auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count();
    std::cout << "  " << label << ": " << iters << " ops in "
              << ns << "ns = " << ns / iters << "ns/op\n";
}

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // IS_LOCK_FREE
    // -------------------------------------------------------

    std::cout << "=== atomic lock-free status ===\n";

    std::atomic<bool>    ab{};
    std::atomic<int32_t> ai32{};
    std::atomic<int64_t> ai64{};
    std::atomic<double>  adbl{};  // typically lock-free on x86

    std::cout << "  atomic<bool>:    is_lock_free=" << ab.is_lock_free() << "\n";
    std::cout << "  atomic<int32_t>: is_lock_free=" << ai32.is_lock_free() << "\n";
    std::cout << "  atomic<int64_t>: is_lock_free=" << ai64.is_lock_free() << "\n";
    std::cout << "  atomic<double>:  is_lock_free=" << adbl.is_lock_free() << "\n";

    // -------------------------------------------------------
    // POSITION + ORDER ID
    // -------------------------------------------------------

    std::cout << "\n=== atomic position and order ID ===\n";

    {
        AtomicPosition pos;
        OrderIdGenerator gen;

        // Multiple threads updating position concurrently
        std::vector<std::thread> threads;
        for (int i = 0; i < 4; ++i) {
            threads.emplace_back([i, &pos, &gen]() {
                int64_t delta = (i % 2 == 0) ? 100 : -50;
                pos.on_fill(delta);
                uint64_t id = gen.next();
                std::cout << "  [Thread " << i << "] fill delta=" << delta
                          << " order_id=" << id << "\n";
            });
        }
        for (auto& t : threads) t.join();

        std::cout << "  Final position: " << pos.get() << "\n";
        std::cout << "  Orders issued:  " << gen.current() - 1000000 << "\n";
    }

    // -------------------------------------------------------
    // KILL SWITCH
    // -------------------------------------------------------

    std::cout << "\n=== kill switch ===\n";

    {
        KillSwitch ks;
        std::atomic<bool> running{true};
        int ticks = 0;

        // Strategy thread: checks kill switch on every tick
        std::thread strat([&ks, &running, &ticks]() {
            while (!ks.is_active() && running) {
                ++ticks;
                std::this_thread::sleep_for(1ms);
            }
            std::cout << "  [Strategy] stopped after " << ticks << " ticks\n";
        });

        // Risk thread: activates kill switch after 5ms
        std::thread risk([&ks, &running]() {
            std::this_thread::sleep_for(5ms);
            ks.activate("Max daily loss exceeded");
            running.store(false, std::memory_order_relaxed);
        });

        strat.join();
        risk.join();
    }

    // -------------------------------------------------------
    // PRODUCER-CONSUMER — acquire/release
    // -------------------------------------------------------

    std::cout << "\n=== acquire/release producer-consumer ===\n";

    {
        DataChannel channel;
        std::atomic<int> consumed{0};
        std::atomic<bool> done{false};

        // Feed thread publishes ticks
        std::thread producer([&channel, &done]() {
            MarketData ticks[] = {
                {1825000, 1825100, 100, 200},
                {1825100, 1825200, 150, 100},
                {1825200, 1825300, 200,  50},
            };
            for (const auto& d : ticks) {
                channel.publish(d);
                std::this_thread::sleep_for(1ms);
            }
            done.store(true, std::memory_order_release);
        });

        // Strategy thread consumes ticks
        std::thread consumer([&channel, &consumed, &done]() {
            MarketData d;
            while (!done.load(std::memory_order_acquire) || channel.try_consume(d)) {
                if (channel.try_consume(d)) {
                    ++consumed;
                    std::cout << "  [Consumer] bid=$" << d.bid / 10000.0
                              << " ask=$" << d.ask / 10000.0 << "\n";
                }
            }
        });

        producer.join();
        consumer.join();
        std::cout << "  Consumed " << consumed.load() << " updates\n";
    }

    // -------------------------------------------------------
    // COMPARE-AND-SWAP
    // -------------------------------------------------------

    std::cout << "\n=== CAS — lock-free best bid ===\n";

    {
        LockFreeBestBid best;
        std::vector<std::thread> threads;

        int64_t bids[] = {1825000, 1825500, 1824500, 1825200, 1826000, 1825900};

        for (int i = 0; i < 6; ++i) {
            threads.emplace_back([i, &best, &bids]() {
                bool updated = best.update_if_better(bids[i]);
                std::cout << "  Thread " << i << ": bid=" << bids[i]
                          << (updated ? " ACCEPTED" : " rejected") << "\n";
            });
        }
        for (auto& t : threads) t.join();
        std::cout << "  Best bid: " << best.get() << " ($"
                  << best.get() / 10000.0 << ")\n";
    }

    // -------------------------------------------------------
    // BENCHMARK: relaxed vs seq_cst
    // -------------------------------------------------------

    std::cout << "\n=== Memory order benchmark ===\n";

    const int BENCH_ITERS = 1000000;
    bench_atomic("relaxed",  std::memory_order_relaxed, std::memory_order_relaxed, BENCH_ITERS);
    bench_atomic("seq_cst",  std::memory_order_seq_cst, std::memory_order_seq_cst, BENCH_ITERS);

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Full atomic state for a trading engine — zero mutex in hot path:

        class TradingEngine {
            std::atomic<int64_t>  net_position_{0};  // shares of current symbol
            std::atomic<int64_t>  seq_num_{1};       // next order sequence number
            std::atomic<bool>     kill_switch_{false};
            std::atomic<bool>     market_open_{false};
            std::atomic<int64_t>  realized_pnl_{0};  // in ticks
            std::atomic<int>      open_orders_{0};

        public:
            // Called from fill handler thread (NOT the strategy thread):
            void on_fill(int64_t delta_qty, int64_t fill_price) noexcept {
                if (kill_switch_.load(memory_order_acquire)) return;
                net_position_.fetch_add(delta_qty, memory_order_relaxed);
                realized_pnl_.fetch_add(delta_qty * fill_price, memory_order_relaxed);
                open_orders_.fetch_sub(1, memory_order_relaxed);
            }

            // Called from strategy thread on every tick:
            int64_t position() const noexcept {
                return net_position_.load(memory_order_relaxed);
            }

            // Called from risk thread:
            void kill(const char* reason) noexcept {
                kill_switch_.store(true, memory_order_release);
            }
        };
    */
}
