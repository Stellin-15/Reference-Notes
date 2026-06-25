// ============================================================
// L42: Thread-Local Storage and Cache Partitioning
// ============================================================
// WHAT: thread_local gives each thread its own private copy of
//       a variable. False sharing occurs when two threads write
//       to different variables that happen to share the same
//       64-byte CPU cache line — causing expensive cache
//       coherency traffic even though they're not actually
//       sharing data.
// WHY (TRADING): Two bugs that are nearly invisible but
//   catastrophic for latency:
//   1. False sharing: two trading threads writing adjacent
//      struct fields destroy each other's cache lines.
//      Fix: pad structs to cache line boundaries.
//   2. Shared global state: per-thread statistics accumulate
//      into a global with a mutex. Fix: thread_local accumulators
//      — each thread has its own counter, no synchronization.
//   In both cases, the code "works correctly" but is 5-10x
//   slower than it should be. These bugs only appear under
//   multi-core profiling, not in unit tests.
// PHASE: Concurrency
// ============================================================

/*
  CONCEPT OVERVIEW:

  THREAD_LOCAL:
    thread_local T var = init;
    Each thread gets its OWN copy of var, initialized the first time
    that thread accesses it.
    The copy is destroyed when the thread exits (destructor is called).
    Works on: built-in types, classes with constructors/destructors.

    Use cases:
    - Per-thread statistics: each thread accumulates, merge at end
    - Per-thread random state: each thread has its own RNG seed
    - Per-thread temporary buffers: no dynamic allocation, no sharing
    - Per-thread error state: like errno (which IS thread_local)

    HFT use case:
    - Per-thread order ID range: thread 0 gets IDs 0..999999,
      thread 1 gets 1000000..1999999 — no atomic needed
    - Per-thread tick counter: no mutex, no atomic

  CACHE LINE (64 bytes on x86):
    The CPU loads/stores memory in 64-byte chunks called cache lines.
    If two variables are in the same cache line, they always move together.

  FALSE SHARING:
    Thread A writes to field a.
    Thread B writes to field b.
    If a and b are in the same 64-byte cache line:
    - Thread A's write invalidates thread B's cache (MESI protocol)
    - Thread B must reload the cache line from RAM/L3
    - Same happens on every write from either side
    - Both threads' writes cause cache ping-pong through L3/RAM
    - Effective cost: ~70ns per write instead of ~1ns
    This is called "false sharing" — the variables aren't logically
    shared, but physically share a cache line.

    EXAMPLE OF FALSE SHARING:
      struct Counters {
          int64_t thread0_count;   // bytes 0-7
          int64_t thread1_count;   // bytes 8-15  ← SAME cache line as above!
      };

    FIX: separate the variables with padding to 64-byte boundaries:
      struct alignas(64) Counter {
          int64_t count;           // bytes 0-7
          char    pad[56];         // bytes 8-63 (padding to fill the cache line)
      };
      Counter counters[NUM_THREADS];   // now each Counter is on its own cache line

  ALIGNAS:
    alignas(N) T var;  — align var to N bytes (must be power of 2)
    alignas(64) ensures a struct starts at a cache-line boundary.
    Use on:
    - Per-thread data arrays: counters[NUM_THREADS]
    - SPSC queue head/tail (shown in L38)
    - Order book price levels (ensure level struct fits in one cache line)

  CACHE-FRIENDLY DATA LAYOUT:
    Hot fields first: fields accessed in the hot loop go at offset 0
    (always in the first cache line loaded).
    Cold fields last: rarely accessed fields at higher offsets.
    Example: Order struct — price and qty in first 16 bytes (hot);
    symbol, timestamp, status in later bytes (cold, for logging).

  TRADING USE CASE:
    // Per-thread stats: no mutex, no atomic
    thread_local int64_t thread_tick_count = 0;
    thread_local int64_t thread_pnl = 0;

    void on_tick(const Tick& t) {
        ++thread_tick_count;   // no sync needed — private to this thread
        thread_pnl += compute_pnl(t);
    }

    // Gather at EOD:
    int64_t total_ticks = 0;
    for (int i = 0; i < NUM_THREADS; ++i) {
        total_ticks += per_thread_stats[i].tick_count;
    }

  COMMON MISTAKES:
    - Two hot-path variables sharing a cache line (usually adjacent fields)
    - Using alignas(64) but not making the array itself cache-line aligned
    - thread_local with expensive constructors (runs on every thread's first access)
    - Thinking thread_local is like static — it IS like static but per-thread
    - Checking sizeof(CacheLinePadded<T>) instead of alignof to verify alignment
*/

#include <iostream>
#include <thread>
#include <atomic>
#include <chrono>
#include <vector>
#include <cstdint>
#include <cstring>   // memset
#include <numeric>   // accumulate

using namespace std::chrono_literals;

// ============================================================
// FALSE SHARING — DEMO OF THE PROBLEM AND FIX
// ============================================================

constexpr int CACHE_LINE = 64;

// BAD: thread 0 writes count[0], thread 1 writes count[1]
// Both are in the SAME cache line → false sharing
struct BadCounters {
    int64_t count[4];   // all 4 are in the same 32-byte region
};

// GOOD: each counter is on its own 64-byte cache line
struct alignas(CACHE_LINE) GoodCounter {
    int64_t count;
    char    pad[CACHE_LINE - sizeof(int64_t)];  // pad to fill cache line
};

// Even cleaner: template wrapper
template<typename T>
struct alignas(CACHE_LINE) CacheLinePadded {
    T    value{};
    char pad[CACHE_LINE - sizeof(T)];

    CacheLinePadded() = default;
    explicit CacheLinePadded(T v) : value(v) {}
};

static_assert(sizeof(GoodCounter) == CACHE_LINE, "GoodCounter must be exactly one cache line");
static_assert(sizeof(CacheLinePadded<int64_t>) == CACHE_LINE);

// ============================================================
// BENCHMARK: false sharing vs cache-line separated
// ============================================================

uint64_t bench_false_sharing(int iters, int num_threads) {
    BadCounters bad{};
    std::vector<std::thread> threads;

    auto t0 = std::chrono::steady_clock::now();

    for (int i = 0; i < num_threads; ++i) {
        threads.emplace_back([i, iters, &bad]() {
            for (int j = 0; j < iters; ++j) {
                ++bad.count[i];   // writes to adjacent cache-line slots
            }
        });
    }
    for (auto& t : threads) t.join();

    auto t1 = std::chrono::steady_clock::now();
    return static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());
}

uint64_t bench_no_false_sharing(int iters, int num_threads) {
    std::vector<GoodCounter> good(num_threads);
    std::vector<std::thread> threads;

    auto t0 = std::chrono::steady_clock::now();

    for (int i = 0; i < num_threads; ++i) {
        threads.emplace_back([i, iters, &good]() {
            for (int j = 0; j < iters; ++j) {
                ++good[i].count;   // each thread writes to its own cache line
            }
        });
    }
    for (auto& t : threads) t.join();

    auto t1 = std::chrono::steady_clock::now();
    return static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());
}

// ============================================================
// THREAD_LOCAL — per-thread statistics
// ============================================================

// Each thread accumulates its own stats — no mutex, no atomic
thread_local int64_t tl_tick_count = 0;
thread_local int64_t tl_signal_count = 0;
thread_local double  tl_cumulative_pnl = 0.0;

// Gather all thread-local stats at EOD
struct ThreadStats {
    int64_t tick_count;
    int64_t signal_count;
    double  cumulative_pnl;
};

// Shared storage for per-thread stats (indexed by thread id)
// Written by each thread at shutdown, read by main thread for reporting
std::vector<ThreadStats> per_thread_stats(4);  // up to 4 threads

void simulate_trading_thread(int thread_idx, int ticks_to_process) {
    // Process ticks — increment thread-local counters (zero synchronization)
    for (int i = 0; i < ticks_to_process; ++i) {
        ++tl_tick_count;

        // Simulate occasional signal (every 10th tick)
        if (i % 10 == 0) {
            ++tl_signal_count;
            tl_cumulative_pnl += (i % 2 == 0 ? 12.50 : -8.75);
        }
    }

    // At thread shutdown: write thread-local stats to shared array (once, no mutex)
    per_thread_stats[thread_idx] = {tl_tick_count, tl_signal_count, tl_cumulative_pnl};
}

// ============================================================
// CACHE-FRIENDLY ORDER STRUCT
// ============================================================

// Hot fields (accessed every tick) at the FRONT (first 64 bytes = first cache line)
// Cold fields (accessed only for logging, reporting) after the first cache line
struct Order {
    // --- FIRST CACHE LINE: hot fields (accessed in the matching/risk loop) ---
    int64_t  price;         // offset  0: 8 bytes
    int32_t  qty;           // offset  8: 4 bytes
    int32_t  remaining_qty; // offset 12: 4 bytes
    uint64_t order_id;      // offset 16: 8 bytes
    bool     is_buy;        // offset 24: 1 byte
    uint8_t  status;        // offset 25: 1 byte (NEW/PARTIAL/FILLED/CANCEL)
    char     pad1[6];       // offset 26: 6 bytes padding (align next field)
    // Total: 32 bytes — fits in first half of cache line

    // --- SECOND CACHE LINE: cold fields (logging, display) ---
    uint64_t timestamp_ns;  // offset 32
    uint64_t fill_time_ns;  // offset 40
    double   avg_fill_price;// offset 48
    char     symbol[8];     // offset 56
};

static_assert(sizeof(Order) == 64, "Order should fit in one cache line");

// ============================================================
// THREAD-LOCAL RNG (per-thread, no synchronization)
// ============================================================

// Simple xorshift64 per-thread random number generator
thread_local uint64_t tl_rng_state = 0;

void seed_rng(uint64_t seed) { tl_rng_state = seed; }

uint64_t next_rand() {
    tl_rng_state ^= tl_rng_state << 13;
    tl_rng_state ^= tl_rng_state >> 7;
    tl_rng_state ^= tl_rng_state << 17;
    return tl_rng_state;
}

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // CACHE LINE SIZE AND STRUCT SIZES
    // -------------------------------------------------------

    std::cout << "=== Cache line info ===\n";
    std::cout << "  Cache line size: " << CACHE_LINE << " bytes\n";
    std::cout << "  sizeof(Order):               " << sizeof(Order) << " bytes\n";
    std::cout << "  sizeof(GoodCounter):         " << sizeof(GoodCounter) << " bytes\n";
    std::cout << "  sizeof(CacheLinePadded<int64_t>): "
              << sizeof(CacheLinePadded<int64_t>) << " bytes\n";
    std::cout << "  sizeof(BadCounters):         " << sizeof(BadCounters) << " bytes\n";

    // -------------------------------------------------------
    // FALSE SHARING BENCHMARK
    // -------------------------------------------------------

    std::cout << "\n=== False sharing benchmark ===\n";

    {
        const int ITERS = 1000000;
        const int THREADS = std::min(4, static_cast<int>(
            std::thread::hardware_concurrency()));

        auto bad_ns  = bench_false_sharing(ITERS, THREADS);
        auto good_ns = bench_no_false_sharing(ITERS, THREADS);

        std::cout << "  Threads: " << THREADS
                  << ", iterations each: " << ITERS << "\n";
        std::cout << "  False sharing (bad layout):    " << bad_ns  << "ns\n";
        std::cout << "  No false sharing (good layout): " << good_ns << "ns\n";
        if (good_ns > 0) {
            double ratio = static_cast<double>(bad_ns) / good_ns;
            std::cout << "  Ratio (bad/good): " << ratio << "x\n";
            std::cout << "  (expect 2-10x on multi-core; less on single-core)\n";
        }
    }

    // -------------------------------------------------------
    // THREAD_LOCAL STATS
    // -------------------------------------------------------

    std::cout << "\n=== thread_local per-thread stats ===\n";

    {
        const int NUM_THREADS = 3;
        std::vector<std::thread> threads;

        for (int i = 0; i < NUM_THREADS; ++i) {
            threads.emplace_back([i]() {
                int ticks = 100 + i * 50;   // different workload per thread
                simulate_trading_thread(i, ticks);
                std::cout << "  [Thread " << i << "] ticks=" << per_thread_stats[i].tick_count
                          << " signals=" << per_thread_stats[i].signal_count
                          << " pnl=$" << per_thread_stats[i].cumulative_pnl << "\n";
            });
        }
        for (auto& t : threads) t.join();

        // Aggregate from per-thread stats (main thread, post-shutdown)
        int64_t total_ticks   = 0;
        int64_t total_signals = 0;
        double  total_pnl     = 0.0;
        for (int i = 0; i < NUM_THREADS; ++i) {
            total_ticks   += per_thread_stats[i].tick_count;
            total_signals += per_thread_stats[i].signal_count;
            total_pnl     += per_thread_stats[i].cumulative_pnl;
        }
        std::cout << "  Aggregate: ticks=" << total_ticks
                  << " signals=" << total_signals
                  << " pnl=$" << total_pnl << "\n";
    }

    // -------------------------------------------------------
    // THREAD-LOCAL RNG
    // -------------------------------------------------------

    std::cout << "\n=== thread_local RNG ===\n";

    {
        std::vector<std::thread> threads;
        std::vector<uint64_t> first_vals(2);

        for (int i = 0; i < 2; ++i) {
            threads.emplace_back([i, &first_vals]() {
                seed_rng(12345 + i * 1000);   // each thread seeds its own RNG
                first_vals[i] = next_rand();
                std::cout << "  [Thread " << i << "] first rand: " << first_vals[i] << "\n";
            });
        }
        for (auto& t : threads) t.join();
        std::cout << "  (Different values = independent per-thread RNG states)\n";
    }

    // -------------------------------------------------------
    // ORDER STRUCT LAYOUT
    // -------------------------------------------------------

    std::cout << "\n=== Cache-friendly Order struct ===\n";

    {
        Order o{};
        o.price         = 1825000;
        o.qty           = 100;
        o.remaining_qty = 100;
        o.order_id      = 1001;
        o.is_buy        = true;
        o.status        = 0;   // NEW

        // Hot-path fields accessed via pointer to Order
        // These are all within the first 32 bytes (first half of L1 cache line load)
        std::cout << "  Order size: " << sizeof(Order) << " bytes (= 1 cache line)\n";
        std::cout << "  offsetof(price):         " << offsetof(Order, price) << "\n";
        std::cout << "  offsetof(qty):           " << offsetof(Order, qty) << "\n";
        std::cout << "  offsetof(order_id):      " << offsetof(Order, order_id) << "\n";
        std::cout << "  offsetof(timestamp_ns):  " << offsetof(Order, timestamp_ns)
                  << " (cold: second half of cache line)\n";
        std::cout << "  offsetof(symbol):        " << offsetof(Order, symbol)
                  << " (cold)\n";
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Per-thread order ID ranges — zero contention:

        // At startup: assign each thread a non-overlapping ID range
        // No atomic, no mutex — each thread has exclusive ownership
        constexpr uint64_t IDS_PER_THREAD = 1'000'000ULL;

        thread_local uint64_t tl_next_order_id = 0;
        thread_local uint64_t tl_id_ceiling    = 0;

        void init_thread_ids(int thread_idx) {
            tl_next_order_id = uint64_t(thread_idx) * IDS_PER_THREAD;
            tl_id_ceiling    = tl_next_order_id + IDS_PER_THREAD;
        }

        uint64_t next_order_id() {
            assert(tl_next_order_id < tl_id_ceiling && "Thread ID range exhausted");
            return tl_next_order_id++;
        }

        // Thread 0 → IDs 0–999,999
        // Thread 1 → IDs 1,000,000–1,999,999
        // Thread 2 → IDs 2,000,000–2,999,999
        // All unique, no synchronization, O(1) per call.

        // Combined with per-thread position tracking:
        thread_local int64_t tl_position = 0;  // private to this strategy thread

        void on_fill(int64_t delta) {
            tl_position += delta;  // no atomic — this thread is the ONLY writer
        }

        // At EOD: aggregate all per-thread positions into the risk report
    */
}
