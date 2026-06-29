// ============================================================
// L50: rdtsc, Profiling, and Latency Measurement
// ============================================================
// WHAT: Techniques for measuring exactly HOW FAST your code is
//       and WHERE the latency comes from. rdtsc reads CPU cycle
//       counter. perf is the Linux profiling tool. Percentile
//       distributions show you p99/p99.9 (worst-case latency)
//       which is what actually matters in HFT.
// WHY (TRADING): "My code feels fast" is not good enough.
//   You need to know: does the tick→order path take 500ns or
//   5µs? Is the bottleneck parsing, book update, or strategy?
//   And critically: what's the p99.9 latency? In HFT, the
//   worst-case latency on the rare but critical market-moving
//   tick is what determines if you get filled or not. A system
//   with avg=300ns but p99.9=50µs loses fills whenever it
//   matters most. You need consistent sub-microsecond latency.
// PHASE: Low-Latency Systems
// ============================================================

/*
  CONCEPT OVERVIEW:

  RDTSC (Read Time-Stamp Counter):
    uint64_t t = __rdtsc();
    Returns the CPU's cycle counter — increments once per clock cycle.
    On a 3GHz CPU: 3 × 10^9 ticks/second → 1 tick ≈ 0.333ns.
    ADVANTAGES over chrono:
    - ~5 CPU cycles of overhead (vs ~20-50 for chrono)
    - Sub-nanosecond resolution
    - No syscall
    DISADVANTAGES:
    - CPU migration can cause jumps (pin the thread to fix)
    - Frequency scaling (Intel SpeedStep) makes tick→ns conversion variable
    - Out-of-order execution can reorder reads around the timestamp
    FIX: Use CPUID fence before rdtsc (__cpuid) to prevent reordering.
         Or use rdtscp which includes a pipeline fence.

  RDTSCP:
    uint64_t rdtscp(uint32_t& aux_cpu_id) {
        return __rdtscp(&aux_cpu_id);
    }
    Returns TSC and fills aux_cpu_id with the current CPU core ID.
    The "p" means "serializing" — no instructions reorder past it.
    Use rdtscp (not rdtsc) for accurate start/stop measurement.

  CONVERT CYCLES TO NANOSECONDS:
    1. Measure CPU frequency: TSC ticks per second = CPU GHz × 10^9
    2. Calibrate: sleep(1s) and measure TSC delta → TSC per second
    3. ns = cycles * 1e9 / tsc_per_second
    On x86: TSC frequency is fixed on modern CPUs (constant_tsc).
    Check: grep "constant_tsc" /proc/cpuinfo (Linux)

  LATENCY PERCENTILES:
    Never report average latency for HFT systems.
    Report: p50 (median), p99, p99.9, p99.99, max.
    WHY: outliers (GC pauses, page faults, OS interrupts) appear at p99+.
         These outliers are exactly when the market is moving and fills matter.
    p99.9 means: 1 in 1000 events take longer than this.
    p99.99 means: 1 in 10,000 — might still happen many times per day.

  PERF (Linux profiling tool):
    perf stat ./trading_engine        — counts: cycles, cache misses, branches
    perf record -g ./trading_engine   — record call graph
    perf report                        — interactive view of hotspots
    perf top                           — live view (like htop for functions)
    Key counters:
      cache-misses:    L1/L2/L3 cache miss events
      branch-misses:   mispredicted branches (pipeline flushes)
      instructions:    total instruction count
      cycles:          total cycle count
      IPC (instructions/cycle): > 3 is good, < 1 is bad (cache-bound)

  VTUNE (Intel, Windows/Linux):
    More detailed than perf. Shows: memory access latency per variable,
    vectorization efficiency, lock contention, NUMA topology.
    Commercial but free for basic use.

  ANNOTATING HOT PATHS:
    __attribute__((noinline)) void foo() { ... }
    Mark functions noinline to see them as separate entries in perf report.
    Otherwise the compiler inlines everything and you can't see individual functions.

  TRADING USE CASE:
    Measure every component of the tick→order pipeline:
    t0 = rdtscp: packet arrives from NIC
    t1 = rdtscp: ITCH parsed
    t2 = rdtscp: book updated
    t3 = rdtscp: signal evaluated
    t4 = rdtscp: order sent via FIX
    Record (t4-t0) in a ring buffer, report percentiles every 1M ticks.

  COMMON MISTAKES:
    - Reporting average latency instead of p99/p99.9 (hides outliers)
    - Not pinning thread during benchmark (OS migration causes jumps)
    - Using chrono for microbenchmarks (too much overhead for ns measurement)
    - Benchmarking with debugging flags (-O0, ASAN) — results are meaningless
    - Forgetting compiler optimization ruins the benchmark: use volatile or side effects
    - Measuring a function in isolation (it runs from L1 cache), not in context
      (it runs from L3 after cache was evicted by preceding code)
*/

#include <iostream>
#include <vector>
#include <algorithm>
#include <numeric>
#include <cstdint>
#include <cmath>
#include <chrono>
#include <string>
#include <thread>
#include <cassert>
#include <fstream>
#include <iomanip>

// rdtsc intrinsics
#if defined(__x86_64__) || defined(_M_X64) || defined(__i386__) || defined(_M_IX86)
#  include <intrin.h>   // MSVC: __rdtsc, __rdtscp
#  define HAS_RDTSC 1
   static inline uint64_t rdtsc_now() { return __rdtsc(); }
   static inline uint64_t rdtscp_now() {
       unsigned int aux;
       return __rdtscp(&aux);
   }
#else
#  define HAS_RDTSC 0
   static inline uint64_t rdtsc_now() {
       return static_cast<uint64_t>(
           std::chrono::steady_clock::now().time_since_epoch().count());
   }
   static inline uint64_t rdtscp_now() { return rdtsc_now(); }
#endif

// ============================================================
// TSC CALIBRATION — determine cycles per nanosecond
// ============================================================

double calibrate_tsc_ghz() {
    auto t0_ns = std::chrono::steady_clock::now();
    uint64_t t0_tsc = rdtsc_now();

    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    auto t1_ns = std::chrono::steady_clock::now();
    uint64_t t1_tsc = rdtsc_now();

    uint64_t elapsed_ns  = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1_ns - t0_ns).count());
    uint64_t elapsed_tsc = t1_tsc - t0_tsc;

    return static_cast<double>(elapsed_tsc) / elapsed_ns;  // cycles per ns ≈ GHz
}

// ============================================================
// LATENCY HISTOGRAM
// ============================================================

class LatencyHistogram {
public:
    void record(uint64_t ns) {
        samples_.push_back(ns);
    }

    void record_tsc(uint64_t cycles, double cycles_per_ns) {
        record(static_cast<uint64_t>(cycles / cycles_per_ns));
    }

    void print(const std::string& label, bool detailed = false) const {
        if (samples_.empty()) {
            std::cout << "  [" << label << "] no samples\n";
            return;
        }

        std::vector<uint64_t> sorted = samples_;
        std::sort(sorted.begin(), sorted.end());

        size_t n = sorted.size();
        double sum = std::accumulate(sorted.begin(), sorted.end(), 0.0);
        double avg = sum / n;
        double p50  = sorted[n * 50  / 100];
        double p90  = sorted[n * 90  / 100];
        double p99  = sorted[n * 99  / 100];
        double p999 = n >= 1000 ? sorted[n * 999 / 1000] : sorted.back();
        double p9999= n >= 10000 ? sorted[n * 9999 / 10000] : sorted.back();
        double max  = sorted.back();
        double min  = sorted.front();

        // Variance/stddev
        double sq_sum = 0;
        for (uint64_t s : sorted) sq_sum += (s - avg) * (s - avg);
        double stddev = std::sqrt(sq_sum / n);

        std::cout << "  [" << label << "] n=" << n << "\n"
                  << "    min=" << min << "ns  avg=" << avg << "ns  stddev=" << stddev << "ns\n"
                  << "    p50=" << p50 << "ns  p90=" << p90 << "ns\n"
                  << "    p99=" << p99 << "ns  p99.9=" << p999 << "ns  p99.99=" << p9999 << "ns\n"
                  << "    max=" << max << "ns\n";

        if (detailed) {
            // Print a text histogram
            std::cout << "  Histogram (ns):\n";
            uint64_t bucket_size = std::max(uint64_t(1), uint64_t((max - min) / 10));
            std::vector<int> buckets(11, 0);
            for (uint64_t s : sorted) {
                int b = std::min(10, int((s - min) / bucket_size));
                ++buckets[b];
            }
            for (int i = 0; i <= 10; ++i) {
                uint64_t lo = min + i * bucket_size;
                std::cout << "    [" << std::setw(6) << lo << "ns]: ";
                int bars = buckets[i] * 30 / (int)n;
                for (int j = 0; j < bars; ++j) std::cout << '#';
                std::cout << " (" << buckets[i] << ")\n";
            }
        }
    }

    void reset() { samples_.clear(); }
    size_t size() const { return samples_.size(); }

private:
    std::vector<uint64_t> samples_;
};

// ============================================================
// SCOPED TSC TIMER
// ============================================================

class TscTimer {
public:
    TscTimer() : start_(rdtscp_now()) {}

    uint64_t elapsed_cycles() const { return rdtscp_now() - start_; }

    uint64_t elapsed_ns(double cycles_per_ns) const {
        return static_cast<uint64_t>(elapsed_cycles() / cycles_per_ns);
    }

    void reset() { start_ = rdtscp_now(); }

private:
    uint64_t start_;
};

// ============================================================
// SIMULATED PIPELINE LATENCY BREAKDOWN
// ============================================================

struct PipelineStats {
    LatencyHistogram parse;
    LatencyHistogram book_update;
    LatencyHistogram signal_eval;
    LatencyHistogram order_send;
    LatencyHistogram total;
};

void simulate_pipeline(PipelineStats& stats, double cpns, int iterations) {
    for (int i = 0; i < iterations; ++i) {

        // T0: packet arrives
        uint64_t t0 = rdtscp_now();

        // Simulate ITCH parse (~50-200 cycles)
        volatile int parse_work = 0;
        for (int j = 0; j < 30; ++j) parse_work += j;
        uint64_t t1 = rdtscp_now();
        stats.parse.record_tsc(t1 - t0, cpns);

        // Simulate book update (~100-500 cycles)
        volatile double book_work = 0.0;
        for (int j = 0; j < 50; ++j) book_work += j * 0.1;
        uint64_t t2 = rdtscp_now();
        stats.book_update.record_tsc(t2 - t1, cpns);

        // Simulate signal evaluation (~50-200 cycles)
        volatile double sig_work = 0.0;
        for (int j = 0; j < 20; ++j) sig_work += j * 0.01;
        uint64_t t3 = rdtscp_now();
        stats.signal_eval.record_tsc(t3 - t2, cpns);

        // Simulate order send (FIX message format, ~100-300 cycles)
        volatile int ord_work = 0;
        for (int j = 0; j < 40; ++j) ord_work += j;
        uint64_t t4 = rdtscp_now();
        stats.order_send.record_tsc(t4 - t3, cpns);
        stats.total.record_tsc(t4 - t0, cpns);
    }
}

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // CALIBRATE TSC
    // -------------------------------------------------------

    std::cout << "=== TSC calibration ===\n";

    double cpns = 1.0;  // fallback: 1 cycle per ns
#if HAS_RDTSC
    std::cout << "  Calibrating TSC (100ms sleep)...\n";
    cpns = calibrate_tsc_ghz();
    std::cout << "  TSC frequency: " << cpns << " GHz (cycles per ns)\n";
    std::cout << "  1 TSC tick ≈ " << 1.0 / cpns << "ns\n";
#else
    std::cout << "  rdtsc not available — using steady_clock\n";
#endif

    // -------------------------------------------------------
    // RDTSC OVERHEAD
    // -------------------------------------------------------

    std::cout << "\n=== rdtsc overhead ===\n";

    {
        LatencyHistogram h;
        for (int i = 0; i < 10000; ++i) {
            uint64_t t0 = rdtscp_now();
            uint64_t t1 = rdtscp_now();
            h.record_tsc(t1 - t0, cpns);
        }
        h.print("rdtscp() overhead");
    }

    // -------------------------------------------------------
    // CHRONO OVERHEAD
    // -------------------------------------------------------

    std::cout << "\n=== chrono overhead ===\n";

    {
        LatencyHistogram h;
        for (int i = 0; i < 10000; ++i) {
            auto t0 = std::chrono::steady_clock::now();
            auto t1 = std::chrono::steady_clock::now();
            h.record(static_cast<uint64_t>(
                std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count()));
        }
        h.print("steady_clock::now() overhead");
    }

    // -------------------------------------------------------
    // PIPELINE BREAKDOWN
    // -------------------------------------------------------

    std::cout << "\n=== Pipeline latency breakdown ===\n";

    {
        PipelineStats stats;
        const int ITERS = 100000;

        simulate_pipeline(stats, cpns, ITERS);

        stats.parse.print("ITCH parse      ");
        stats.book_update.print("Book update     ");
        stats.signal_eval.print("Signal eval     ");
        stats.order_send.print("Order format    ");
        stats.total.print("TOTAL wire-order", true);
    }

    // -------------------------------------------------------
    // CACHE MISS LATENCY DEMO
    // -------------------------------------------------------

    std::cout << "\n=== Cache miss latency ===\n";

    {
        const int N = 1024 * 1024;   // 1M int64 = 8MB (doesn't fit in L2)
        std::vector<int64_t> arr(N);
        for (int i = 0; i < N; ++i) arr[i] = i;

        // Sequential access: cache-friendly, mostly L1/L2 hits
        {
            LatencyHistogram h;
            for (int trial = 0; trial < 1000; ++trial) {
                uint64_t t0 = rdtscp_now();
                volatile int64_t sum = 0;
                for (int i = 0; i < 1000; ++i) sum += arr[i];  // sequential
                uint64_t t1 = rdtscp_now();
                h.record_tsc(t1 - t0, cpns);
            }
            h.print("Sequential 1K reads (L1/L2)");
        }

        // Random access: cache-unfriendly, mostly L3/RAM misses
        {
            // Create a random permutation for random access
            std::vector<int> idx(1000);
            for (int i = 0; i < 1000; ++i) idx[i] = (i * 197) % N;

            LatencyHistogram h;
            for (int trial = 0; trial < 1000; ++trial) {
                uint64_t t0 = rdtscp_now();
                volatile int64_t sum = 0;
                for (int i : idx) sum += arr[i];  // random
                uint64_t t1 = rdtscp_now();
                h.record_tsc(t1 - t0, cpns);
            }
            h.print("Random 1K reads (L3/RAM)  ");
        }
    }

    // -------------------------------------------------------
    // PERF WORKFLOW
    // -------------------------------------------------------

    std::cout << "\n=== perf profiling workflow ===\n";

    std::cout << "  Build with debug info but optimizations:\n"
              << "    g++ -O2 -g -march=native -o engine trading_engine.cpp\n"
              << "\n"
              << "  Count hardware events:\n"
              << "    perf stat -e cycles,instructions,cache-misses,branch-misses ./engine\n"
              << "\n"
              << "  Record call graph for hotspot analysis:\n"
              << "    perf record -g --call-graph dwarf ./engine\n"
              << "    perf report  (interactive TUI)\n"
              << "\n"
              << "  Live function-level profiling:\n"
              << "    perf top -p $(pgrep engine)\n"
              << "\n"
              << "  Key metrics to watch:\n"
              << "    IPC (instructions per cycle) > 3: good, < 1: cache/memory bound\n"
              << "    cache-misses / instructions > 0.01: too many cache misses\n"
              << "    branch-miss-rate > 1%: poorly predicted branches\n";

    // -------------------------------------------------------
    // LATENCY BUDGET EXAMPLE
    // -------------------------------------------------------

    std::cout << "\n=== Latency budget (target: 500ns wire-to-order) ===\n";

    std::cout << "  Component           Budget    Notes\n"
              << "  ---------           ------    -----\n"
              << "  NIC receive DMA     50ns      Hardware, not tunable\n"
              << "  Kernel network stack 50ns     Bypass with DPDK/Solarflare\n"
              << "  memcpy to userspace  20ns     Kernel bypass = 0\n"
              << "  ITCH message parse   50ns     ~150 cycles on 3GHz\n"
              << "  Order book update   100ns     ~300 cycles: map insert/update\n"
              << "  Signal evaluation    50ns     ~150 cycles: fast strategy\n"
              << "  FIX order format     50ns     ~150 cycles: sprintf or manual\n"
              << "  TCP kernel send      80ns     Kernel bypass: ~20ns\n"
              << "  TOTAL               450ns     Within 500ns budget\n"
              << "\n"
              << "  To measure actual: log t_recv and t_send with rdtscp\n"
              << "  and compare to budget. Find which component exceeds its budget.\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Production latency logging with rdtscp:

        // In the hot path: log latency breakdown per tick
        // Uses a lock-free ring buffer to avoid blocking

        struct LatencyRecord {
            uint64_t t_recv;       // rdtscp when packet arrived
            uint64_t t_parsed;     // rdtscp after ITCH parse
            uint64_t t_book;       // rdtscp after book update
            uint64_t t_signal;     // rdtscp after strategy eval
            uint64_t t_sent;       // rdtscp after FIX send
            uint32_t seq;          // packet sequence number
        };

        SPSCQueue<LatencyRecord, 65536> latency_log;

        // In feed thread (hot path):
        void on_packet(const uint8_t* buf, int len) {
            LatencyRecord rec;
            rec.t_recv   = rdtscp_now();
            rec.seq      = parse_sequence(buf);

            parse_itch(buf, len);
            rec.t_parsed = rdtscp_now();

            book_.update(msg_);
            rec.t_book   = rdtscp_now();

            auto signal = strategy_.evaluate(book_.bbo());
            rec.t_signal = rdtscp_now();

            if (signal) gateway_.send(make_order(*signal));
            rec.t_sent   = rdtscp_now();

            latency_log.push(rec);   // < 20ns: doesn't affect hot path
        }

        // In reporting thread (every 1M ticks):
        void report_latency() {
            LatencyRecord rec;
            LatencyHistogram parse_hist, book_hist, total_hist;
            while (latency_log.pop(rec)) {
                parse_hist.record_tsc(rec.t_parsed - rec.t_recv, cpns_);
                book_hist.record_tsc(rec.t_book - rec.t_parsed, cpns_);
                total_hist.record_tsc(rec.t_sent - rec.t_recv, cpns_);
            }
            parse_hist.print("ITCH parse");
            book_hist.print("Book update");
            total_hist.print("Wire-to-order");
        }
    */
}
