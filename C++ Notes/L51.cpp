// ============================================================
// L51: Compiler Optimizations
// ============================================================
// WHAT: Compiler flags, function attributes, and code patterns
//       that guide the compiler to produce faster machine code.
//       Includes: optimization levels, branch prediction hints,
//       always_inline, likely/unlikely, PGO (Profile-Guided
//       Optimization), and link-time optimization (LTO).
// WHY (TRADING): The same C++ code compiled with -O3 -march=native
//   runs 2-10x faster than -O0 (debug mode). Branch prediction
//   hints ([likely]/[unlikely]) tell the CPU which branch is
//   the common case, improving branch prediction by 50-200%.
//   always_inline eliminates function call overhead. LTO allows
//   the linker to optimize across translation units — critical
//   when your hot path spans multiple .cpp files.
// PHASE: Low-Latency Systems
// ============================================================

/*
  CONCEPT OVERVIEW:

  OPTIMIZATION LEVELS:
    -O0: no optimization (debug mode). Every variable lives in memory.
         slowest code, fastest compile, easiest to debug.
    -O1: basic optimizations (constant folding, dead code elimination).
    -O2: most safe optimizations (inlining, CSE, loop unrolling).
         Use for: production default when binary size matters.
    -O3: aggressive (vectorization, loop transformations).
         May increase binary size. Use for trading hot paths.
    -Os: optimize for size (fewer cache misses on code — sometimes faster!)
    -Ofast: -O3 + non-IEEE floating point (-ffast-math). AVOID for prices.
    -march=native: use all CPU features of the current machine.
         Enables AVX2, BMI2, etc. Binary is NOT portable to other CPUs.

  KEY FLAGS:
    -march=native         — use all available CPU instruction sets
    -mtune=native         — optimize instruction scheduling for this CPU
    -fno-exceptions       — disable C++ exception support (smaller, faster)
    -fno-rtti             — disable runtime type information (smaller)
    -flto                 — Link-Time Optimization (cross-TU inlining)
    -fprofile-generate    — PGO: instrument for profiling
    -fprofile-use         — PGO: apply profile data
    -fomit-frame-pointer  — free up one register (rbp) for general use
    -funroll-loops        — unroll small loops (increases code size)

  FUNCTION ATTRIBUTES:
    __attribute__((always_inline)) inline void foo();
      — force inlining even at -O0, even if the function is large
    __attribute__((noinline)) void bar();
      — prevent inlining (useful for profiling, or preventing code bloat)
    __attribute__((hot))        — optimizer hint: frequently called
    __attribute__((cold))       — rarely called (put in cold section)
    __attribute__((pure))       — no side effects, depends only on args
    __attribute__((const))      — like pure but doesn't read global state
    __attribute__((flatten))    — inline all calls within this function

  BRANCH PREDICTION HINTS (C++20):
    [[likely]]   — this branch is usually taken
    [[unlikely]] — this branch is rarely taken
    if (condition) [[likely]] { ... }
    Alternative (pre-C++20, GCC/Clang):
    if (__builtin_expect(condition, 1)) { ... }  // likely
    if (__builtin_expect(condition, 0)) { ... }  // unlikely

  CONSTANT PROPAGATION AND CONSTEXPR:
    Mark values constexpr when possible — compiler computes them at compile time.
    Template parameters are always constexpr — use for buffer sizes, mask values.

  LINK-TIME OPTIMIZATION (LTO):
    Without LTO: compiler sees each .cpp in isolation. Cannot inline across .cpp files.
    With LTO: linker combines all translation units → inlines across .cpp → sees full picture.
    Enable: -flto (GCC/Clang), /GL (MSVC)
    Use: compile AND link with -flto.
    Impact: 5-30% additional speedup for code that crosses compilation units.

  PROFILE-GUIDED OPTIMIZATION (PGO):
    1. Compile with -fprofile-generate
    2. Run the program with representative input
    3. Recompile with -fprofile-use
    Compiler now knows WHICH branches are hot, WHICH functions to inline.
    Impact: 10-30% speedup vs -O3 alone.
    Use for: production trading system build.

  RESTRICT KEYWORD:
    void f(int* restrict a, int* restrict b)  — a and b don't alias
    Tells compiler: these pointers point to different memory → better vectorization.
    C++ doesn't have restrict, but: __restrict__ (GCC/Clang), __restrict (MSVC)

  VOLATILE BARRIER:
    volatile int sink = val;  — prevents the compiler from optimizing away computation
    Use in benchmarks to ensure the work actually happens.
    Or: asm volatile("" : "+m"(val));  — zero-cost benchmark barrier

  TRADING USE CASE:
    // HOT PATH: always_inline, likely/unlikely, march=native for SIMD
    [[gnu::always_inline]] inline bool is_fill(const Fill& f) { return f.qty > 0; }
    if (order_count < MAX_ORDERS) [[likely]] { submit(order); }
    else [[unlikely]] { reject("position limit"); }

  COMMON MISTAKES:
    - Building trading system with -O0 or without -march=native (10x slower!)
    - Using __builtin_expect on a condition that's equally likely (helps only when truly biased)
    - LTO with shared libraries (doesn't work — only within the same binary)
    - -Ofast for price calculations (floating point reordering may corrupt results)
    - Forgetting -march=native when deploying (colocation box has AVX2, dev box may not)
    - always_inline on a large function — enlarges the binary, may hurt I-cache
*/

#include <iostream>
#include <vector>
#include <chrono>
#include <cstdint>
#include <cmath>
#include <string>
#include <cassert>
#include <array>
#include <numeric>

// Platform-specific attributes
#if defined(__GNUC__) || defined(__clang__)
#  define ALWAYS_INLINE __attribute__((always_inline)) inline
#  define NEVER_INLINE  __attribute__((noinline))
#  define HOT_FUNC      __attribute__((hot))
#  define COLD_FUNC     __attribute__((cold))
#  define RESTRICT      __restrict__
#elif defined(_MSC_VER)
#  define ALWAYS_INLINE __forceinline
#  define NEVER_INLINE  __declspec(noinline)
#  define HOT_FUNC
#  define COLD_FUNC
#  define RESTRICT      __restrict
#else
#  define ALWAYS_INLINE inline
#  define NEVER_INLINE
#  define HOT_FUNC
#  define COLD_FUNC
#  define RESTRICT
#endif

// ============================================================
// BENCHMARK HELPER
// ============================================================

template<typename Fn>
uint64_t bench_ns(Fn fn, int reps) {
    fn(); fn();  // warmup
    auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < reps; ++i) fn();
    auto t1 = std::chrono::steady_clock::now();
    return static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count()) / reps;
}

// ============================================================
// ALWAYS_INLINE vs NEVER_INLINE
// ============================================================

// Inlined: no call overhead, body visible to caller for further optimization
ALWAYS_INLINE bool is_within_limit(int64_t pos, int64_t limit) {
    return (pos > -limit) & (pos < limit);   // bitwise AND: branchless
}

// Not inlined: useful for profiling (appears as its own symbol in perf)
NEVER_INLINE void handle_risk_breach(int64_t pos, const char* sym) {
    std::cout << "  [RISK] " << sym << " position " << pos << " exceeds limit\n";
}

// ============================================================
// BRANCH PREDICTION: likely/unlikely
// ============================================================

struct Order { int64_t price; int32_t qty; bool is_buy; int32_t remaining; };

// Hot path: in the common case, the order is not filled.
// [[likely]] on the "not filled" branch tells CPU to predict that path.
ALWAYS_INLINE HOT_FUNC
void process_order(Order& o, int64_t best_ask, int64_t best_bid) {
    if (o.is_buy) {
        if (o.price >= best_ask) [[unlikely]] {
            // Fillable — rare in a limit order book at rest
            o.remaining -= 10;  // simulate fill
        }
        // else: order rests in the book — the common case
    } else {
        if (o.price <= best_bid) [[unlikely]] {
            o.remaining -= 10;
        }
    }
}

// ============================================================
// BRANCHLESS CODE — remove branches for predictable speedup
// ============================================================

// Branchy: compiler might generate conditional jump
NEVER_INLINE int64_t max_branchy(int64_t a, int64_t b) {
    return (a > b) ? a : b;  // conditional move or branch
}

// Branchless: always uses CMOV (conditional move) instruction
ALWAYS_INLINE int64_t max_branchless(int64_t a, int64_t b) {
    int64_t mask = -(a > b);   // all 1s if a>b, all 0s otherwise
    return (a & mask) | (b & ~mask);
}

// ============================================================
// RESTRICT — helps vectorization
// ============================================================

// Without restrict: compiler assumes a and out might alias — no vectorization
void compute_notional_normal(const double* a, const double* b, double* out, int n) {
    for (int i = 0; i < n; ++i) out[i] = a[i] * b[i];
}

// With restrict: compiler KNOWS no aliasing — can vectorize
void compute_notional_restrict(const double* RESTRICT a,
                                const double* RESTRICT b,
                                double* RESTRICT out, int n) {
    for (int i = 0; i < n; ++i) out[i] = a[i] * b[i];
}

// ============================================================
// VOLATILE BENCHMARK SINK (prevent dead code elimination)
// ============================================================

// In benchmarks, the compiler might eliminate "useless" computation.
// Use volatile to force the computation to actually happen.
template<typename T>
ALWAYS_INLINE void do_not_optimize(T const& val) {
    // GCC/Clang: inline asm barrier. MSVC: volatile assignment.
#if defined(__GNUC__) || defined(__clang__)
    asm volatile("" : : "r,m"(val) : "memory");
#else
    volatile T sink = val;
    (void)sink;
#endif
}

// ============================================================
// COMPILE-TIME CONSTANTS vs RUNTIME — always use constexpr
// ============================================================

// Runtime: division happens every call
double price_to_dollars_runtime(int64_t price_ticks, int precision) {
    return static_cast<double>(price_ticks) / precision;  // division at runtime
}

// Compile-time: division is computed by compiler
template<int Precision>
ALWAYS_INLINE constexpr double price_to_dollars(int64_t price_ticks) {
    constexpr double inv = 1.0 / Precision;  // constant folded at compile time
    return price_ticks * inv;  // now just a multiply (faster than divide)
}

// ============================================================
// HOT/COLD FUNCTION SEPARATION
// ============================================================

HOT_FUNC void hot_path_tick(int64_t bid, int64_t ask) {
    // Compiler places this in the .text.hot section
    // Keeps it in I-cache alongside other hot functions
    volatile int64_t mid = (bid + ask) >> 1;
    (void)mid;
}

COLD_FUNC void cold_path_reconnect(const char* host, int port) {
    // Placed in .text.cold — doesn't pollute the I-cache of hot functions
    std::cout << "  Reconnecting to " << host << ":" << port << "\n";
}

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // OPTIMIZATION FLAGS INFO
    // -------------------------------------------------------

    std::cout << "=== Recommended HFT compile flags ===\n";
    std::cout << "  g++ -O3 -march=native -mtune=native\n"
              << "      -fno-exceptions -fno-rtti\n"
              << "      -flto               (link-time optimization)\n"
              << "      -fomit-frame-pointer\n"
              << "      -DNDEBUG            (disable assert())\n"
              << "      -Wall -Wextra       (catch bugs at compile time)\n"
              << "\n"
              << "  PGO workflow:\n"
              << "    Step 1: g++ -O3 -march=native -fprofile-generate ...\n"
              << "    Step 2: ./trading_engine < sample_data.bin  (generate profile)\n"
              << "    Step 3: g++ -O3 -march=native -fprofile-use ...\n"
              << "    Result: 10-30% additional speedup\n";

    // -------------------------------------------------------
    // ALWAYS_INLINE vs NORMAL CALL
    // -------------------------------------------------------

    std::cout << "\n=== always_inline vs normal function ===\n";

    {
        constexpr int REPS = 1000000;
        int64_t limit = 1000;

        auto inline_ns = bench_ns([&]() {
            volatile bool r = is_within_limit(500, limit);
            do_not_optimize(r);
        }, REPS);

        std::cout << "  always_inline call: ~" << inline_ns << "ns/call\n";
        std::cout << "  (compiler inlines body — no call overhead, more optimization)\n";
    }

    // -------------------------------------------------------
    // BRANCH PREDICTION HINTS
    // -------------------------------------------------------

    std::cout << "\n=== Branch prediction hints ===\n";

    {
        constexpr int REPS = 1000000;
        std::vector<Order> orders(100);
        for (auto& o : orders) { o.price = 1825000; o.qty = 100; o.is_buy = true; o.remaining = 100; }

        auto ns = bench_ns([&]() {
            for (auto& o : orders) {
                process_order(o, 1826000, 1824000);  // no fill (common case)
            }
        }, REPS / 100);

        std::cout << "  100 orders with likely/unlikely hints: " << ns << "ns\n";
        std::cout << "  [[likely]]/[[unlikely]] tells CPU which branch to prefetch\n"
                  << "  Most effective when branch is ≥90% one direction\n";
    }

    // -------------------------------------------------------
    // BRANCHLESS CODE
    // -------------------------------------------------------

    std::cout << "\n=== Branchless max ===\n";

    {
        constexpr int REPS = 1000000;
        int64_t a = 1825000, b = 1826000;

        auto branchy_ns = bench_ns([&]() {
            volatile int64_t r = max_branchy(a, b);
            do_not_optimize(r);
        }, REPS);

        auto branchless_ns = bench_ns([&]() {
            volatile int64_t r = max_branchless(a, b);
            do_not_optimize(r);
        }, REPS);

        std::cout << "  Branchy:    " << branchy_ns    << "ns\n";
        std::cout << "  Branchless: " << branchless_ns << "ns\n";
        std::cout << "  Note: with predictable input, branchy may be faster (CMOV vs branch)\n"
                  << "  With random input: branchless avoids misprediction penalty (15-20 cycles)\n";
    }

    // -------------------------------------------------------
    // RESTRICT VECTORIZATION
    // -------------------------------------------------------

    std::cout << "\n=== restrict vs no-restrict vectorization ===\n";

    {
        constexpr int N = 10000;
        std::vector<double> a(N), b(N), out(N);
        for (int i = 0; i < N; ++i) { a[i] = i * 0.1; b[i] = (i+1) * 0.01; }

        constexpr int REPS = 10000;

        auto normal_ns = bench_ns([&]() {
            compute_notional_normal(a.data(), b.data(), out.data(), N);
        }, REPS);

        auto restrict_ns = bench_ns([&]() {
            compute_notional_restrict(a.data(), b.data(), out.data(), N);
        }, REPS);

        std::cout << "  Without restrict: " << normal_ns   << "ns\n";
        std::cout << "  With restrict:    " << restrict_ns << "ns\n";
        std::cout << "  (difference more pronounced with -fno-strict-aliasing)\n";
    }

    // -------------------------------------------------------
    // COMPILE-TIME vs RUNTIME DIVIDE
    // -------------------------------------------------------

    std::cout << "\n=== Compile-time division (constexpr) ===\n";

    {
        constexpr int REPS = 1000000;
        int64_t price_ticks = 1825000;

        auto runtime_ns = bench_ns([&]() {
            volatile double p = price_to_dollars_runtime(price_ticks, 10000);
            do_not_optimize(p);
        }, REPS);

        auto constexpr_ns = bench_ns([&]() {
            volatile double p = price_to_dollars<10000>(price_ticks);
            do_not_optimize(p);
        }, REPS);

        std::cout << "  Runtime divide:  " << runtime_ns  << "ns\n";
        std::cout << "  Constexpr inv multiply: " << constexpr_ns << "ns\n";
        std::cout << "  (Division takes ~20-80 cycles; multiply takes ~3-5 cycles)\n";
    }

    // -------------------------------------------------------
    // COMPILATION UNIT BOUNDARY ISSUE
    // -------------------------------------------------------

    std::cout << "\n=== LTO: cross-translation-unit optimization ===\n";

    std::cout << "  Without LTO: function calls across .cpp files are NOT inlined.\n"
              << "  feed_handler.cpp calls book.update() → not inlined → call overhead\n"
              << "\n"
              << "  With -flto: linker combines all .cpp → can inline across files\n"
              << "  book.update() call in the hot path gets inlined → zero call overhead\n"
              << "\n"
              << "  Build both compile and link step with -flto:\n"
              << "    g++ -O3 -march=native -flto -c feed_handler.cpp\n"
              << "    g++ -O3 -march=native -flto -c order_book.cpp\n"
              << "    g++ -O3 -march=native -flto feed_handler.o order_book.o -o engine\n";

    // -------------------------------------------------------
    // HOT/COLD SPLIT
    // -------------------------------------------------------

    std::cout << "\n=== hot/cold function placement ===\n";

    hot_path_tick(1825000, 1825100);
    cold_path_reconnect("10.0.0.1", 9000);

    std::cout << "  [[hot]] functions go in .text.hot section (stays in I-cache)\n"
              << "  [[cold]] functions go in .text.cold (doesn't pollute I-cache)\n"
              << "  I-cache size: typically 32KB (holds ~8K instructions)\n"
              << "  Keeping hot-path code small enough to fit entirely in I-cache\n"
              << "  is one of the most impactful latency optimizations.\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Production build script for lowest latency:

        #!/bin/bash
        # Step 1: Instrument build
        g++ -O3 -march=native -mtune=native \
            -fprofile-generate \
            -fno-exceptions -fno-rtti \
            -flto \
            -DNDEBUG \
            -o trading_engine_inst \
            main.cpp feed.cpp book.cpp strategy.cpp risk.cpp gateway.cpp

        # Step 2: Run with representative market data to generate profile
        ./trading_engine_inst --replay market_data_sample.bin

        # Step 3: Final build using profile data
        g++ -O3 -march=native -mtune=native \
            -fprofile-use \
            -fno-exceptions -fno-rtti \
            -flto \
            -fomit-frame-pointer \
            -funroll-loops \
            -DNDEBUG \
            -o trading_engine \
            main.cpp feed.cpp book.cpp strategy.cpp risk.cpp gateway.cpp

        # Verify the binary uses AVX2:
        objdump -d trading_engine | grep -c ymm  # should be > 0 for AVX2

        # Profile the final binary:
        perf stat -e cycles,instructions,cache-misses,branch-misses ./trading_engine
    */
}
