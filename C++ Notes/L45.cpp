// ============================================================
// L45: SIMD and Vectorization
// ============================================================
// WHAT: SIMD (Single Instruction Multiple Data) executes one
//       instruction on multiple data elements simultaneously.
//       SSE2: 2 doubles per instruction. AVX2: 4 doubles.
//       Auto-vectorization: compiler does it for you when the
//       loop is simple. Manual intrinsics: you write the SIMD.
// WHY (TRADING): Scanning an order book of N price levels for
//   the best executable price is a hot inner loop. With scalar
//   code: 1 comparison per cycle. With AVX2: 4 comparisons per
//   cycle. 4x throughput = 4x more levels scanned per tick.
//   For risk: computing position × price for a 500-symbol
//   portfolio takes 500 multiplies. With AVX2 doubles: 125
//   instructions. Also: finding the minimum ask or maximum bid
//   across a sorted level array is a SIMD operation.
// PHASE: Low-Latency Systems
// ============================================================

/*
  CONCEPT OVERVIEW:

  SIMD REGISTER WIDTHS:
    SSE2  (128-bit): 2 × double, 4 × float, 4 × int32, 2 × int64
    AVX   (256-bit): 4 × double, 8 × float, 8 × int32, 4 × int64
    AVX2  (256-bit): same as AVX + integer operations
    AVX-512 (512-bit): 8 × double, 16 × float (server CPUs, Skylake-X+)
    ALL x86_64 CPUs support SSE2. Most Intel Haswell+ support AVX2.

  INTRINSIC NAMING CONVENTION:
    _mm256_<operation>_<type>
    _mm256   — 256-bit register (AVX/AVX2)
    _mm128   — 128-bit register (SSE2)
    loadu_pd — load unaligned, packed doubles (pd = packed double)
    load_pd  — load aligned (must be 32-byte aligned for AVX)
    add_pd   — add 4 doubles
    mul_pd   — multiply 4 doubles
    cmp_pd   — compare (returns mask)
    max_pd   — elementwise maximum
    storeu_pd— store unaligned result

  AUTO-VECTORIZATION:
    Compiler (gcc/clang with -O2 or higher) automatically vectorizes
    simple loops when:
    1. No data dependencies between iterations
    2. No function calls or branches inside the loop
    3. Array accesses are stride-1 (contiguous)
    4. Data types are float or double (or int with gcc)
    Help the compiler: -march=native (use all CPU features),
    #pragma GCC ivdep (assert no aliasing), restrict keyword.

  CHECK IF VECTORIZED:
    g++ -O2 -march=native -fopt-info-vec-optimized source.cpp
    Clang: -Rpass=loop-vectorize

  TRADING USE CASE:
    // AVX2: compute 4 bid prices simultaneously
    __m256i bid4 = _mm256_loadu_si256((__m256i*)&bids[i]);
    __m256i ask4 = _mm256_loadu_si256((__m256i*)&asks[i]);
    __m256i spread4 = _mm256_sub_epi64(ask4, bid4);

    // Auto-vectorized risk: PnL across 500 positions
    for (int i = 0; i < N; ++i) pnl += positions[i] * prices[i];  // auto-vectorized

  COMMON MISTAKES:
    - Using unaligned intrinsics (loadu) when data IS aligned (use load for speed)
    - Horizontal reduction with SIMD (add all 4 doubles in a register) is
      harder than vertical — use hadd or extract+scalar
    - AVX/AVX2 not available on older CPUs — check or compile conditionally
    - Mixing SSE and AVX without vzeroupper causes performance penalty on some CPUs
    - SIMD code often harder to debug — test with scalar reference implementation
*/

#include <iostream>
#include <vector>
#include <chrono>
#include <cstdint>
#include <cmath>
#include <cassert>
#include <numeric>

// SIMD headers — only include on x86
#if defined(__x86_64__) || defined(_M_X64)
#  include <immintrin.h>
#  if defined(__AVX2__) || defined(__AVX__)
#    define HAS_AVX2 1
#  else
#    define HAS_AVX2 0
#  endif
#  define HAS_SSE2 1
#else
#  define HAS_AVX2 0
#  define HAS_SSE2 0
#endif

// ============================================================
// BENCHMARK HELPER
// ============================================================

template<typename Fn>
uint64_t bench(const std::string& label, Fn fn, int reps) {
    fn(); fn(); fn();  // warmup
    auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < reps; ++i) fn();
    auto t1 = std::chrono::steady_clock::now();
    uint64_t ns = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());
    std::cout << "  [" << label << "] " << ns / reps << "ns/call\n";
    return ns;
}

// ============================================================
// SCALAR vs SIMD: VWAP CALCULATION
// ============================================================

// Scalar: loop over all (price × volume) pairs, sum both
double vwap_scalar(const double* prices, const double* volumes, int n) {
    double sum_pv = 0.0, sum_v = 0.0;
    for (int i = 0; i < n; ++i) {
        sum_pv += prices[i] * volumes[i];
        sum_v  += volumes[i];
    }
    return sum_v > 0.0 ? sum_pv / sum_v : 0.0;
}

#if HAS_AVX2
// AVX2: process 4 doubles at a time
double vwap_avx2(const double* prices, const double* volumes, int n) {
    __m256d sum_pv4 = _mm256_setzero_pd();   // accumulator: 4 × 0.0
    __m256d sum_v4  = _mm256_setzero_pd();

    int i = 0;
    for (; i + 4 <= n; i += 4) {
        // Load 4 prices and 4 volumes from memory
        __m256d p4 = _mm256_loadu_pd(prices + i);    // [p0, p1, p2, p3]
        __m256d v4 = _mm256_loadu_pd(volumes + i);   // [v0, v1, v2, v3]

        // Fused multiply-add: sum_pv4 += p4 * v4 (in one instruction on AVX2)
        sum_pv4 = _mm256_fmadd_pd(p4, v4, sum_pv4);
        sum_v4  = _mm256_add_pd(v4, sum_v4);
    }

    // Horizontal sum: reduce 4 lanes to 1 scalar
    // Store to array and sum — simple approach
    alignas(32) double pv_arr[4], v_arr[4];
    _mm256_store_pd(pv_arr, sum_pv4);
    _mm256_store_pd(v_arr,  sum_v4);

    double sum_pv = pv_arr[0] + pv_arr[1] + pv_arr[2] + pv_arr[3];
    double sum_v  = v_arr[0]  + v_arr[1]  + v_arr[2]  + v_arr[3];

    // Handle tail (n % 4 leftover elements) with scalar
    for (; i < n; ++i) {
        sum_pv += prices[i] * volumes[i];
        sum_v  += volumes[i];
    }
    return sum_v > 0.0 ? sum_pv / sum_v : 0.0;
}
#endif

// ============================================================
// AUTO-VECTORIZED PORTFOLIO PnL
// ============================================================

// This loop is simple enough that the compiler auto-vectorizes it
// with -O2 -march=native — no intrinsics needed
double portfolio_pnl_auto(const double* positions,   // N positions (can be negative)
                           const double* mark_prices, // N current prices
                           const double* cost_basis,  // N average entry prices
                           int n)
{
    double pnl = 0.0;
    for (int i = 0; i < n; ++i) {
        pnl += positions[i] * (mark_prices[i] - cost_basis[i]);
        // This loop: no dependencies, stride-1, all doubles → auto-vectorized
    }
    return pnl;
}

// ============================================================
// ORDER BOOK SCAN — find best bid with SSE2
// ============================================================

// Find maximum price in a sorted (or unsorted) array of int64_t prices
// Scalar version
int64_t max_price_scalar(const int64_t* prices, int n) {
    int64_t best = INT64_MIN;
    for (int i = 0; i < n; ++i) {
        if (prices[i] > best) best = prices[i];
    }
    return best;
}

// ============================================================
// SPREAD COMPUTATION — SSE2 integer SIMD
// ============================================================

#if HAS_SSE2
// Compute N spreads (ask - bid) simultaneously using SSE2
// SSE2: 2 int64 operations per instruction
void compute_spreads_sse2(const int64_t* bids, const int64_t* asks,
                          int64_t* spreads, int n)
{
    int i = 0;
    for (; i + 2 <= n; i += 2) {
        // Load 2 bid prices and 2 ask prices
        __m128i bid2 = _mm_loadu_si128((__m128i*)(bids + i));  // [bid0, bid1]
        __m128i ask2 = _mm_loadu_si128((__m128i*)(asks + i));  // [ask0, ask1]

        // Subtract: spread = ask - bid (int64 subtraction, SSE4.1 for 64-bit)
        // SSE2 doesn't have 64-bit sub directly, use 128-bit trick:
        __m128i spread2 = _mm_sub_epi64(ask2, bid2);

        // Store results
        _mm_storeu_si128((__m128i*)(spreads + i), spread2);
    }
    // Scalar tail
    for (; i < n; ++i) {
        spreads[i] = asks[i] - bids[i];
    }
}
#endif

// Scalar reference for verification
void compute_spreads_scalar(const int64_t* bids, const int64_t* asks,
                            int64_t* spreads, int n)
{
    for (int i = 0; i < n; ++i) {
        spreads[i] = asks[i] - bids[i];
    }
}

// ============================================================
// MAIN
// ============================================================

int main() {

    std::cout << "=== SIMD availability ===\n";
    std::cout << "  SSE2:  " << HAS_SSE2 << "\n";
    std::cout << "  AVX2:  " << HAS_AVX2 << "\n";

    // -------------------------------------------------------
    // VWAP BENCHMARK
    // -------------------------------------------------------

    std::cout << "\n=== VWAP: scalar vs AVX2 ===\n";

    {
        constexpr int N = 100000;
        std::vector<double> prices(N), volumes(N);
        for (int i = 0; i < N; ++i) {
            prices[i]  = 182.50 + (i % 100) * 0.01;
            volumes[i] = 100.0 + (i % 50) * 10.0;
        }

        double vwap_s = 0.0, vwap_a = 0.0;
        bench("scalar VWAP", [&]() { vwap_s = vwap_scalar(prices.data(), volumes.data(), N); }, 1000);
#if HAS_AVX2
        bench("AVX2 VWAP  ", [&]() { vwap_a = vwap_avx2(prices.data(), volumes.data(), N); }, 1000);
        double diff = std::abs(vwap_s - vwap_a);
        std::cout << "  VWAP scalar=" << vwap_s << " AVX2=" << vwap_a
                  << " diff=" << diff << " (should be ~0)\n";
#else
        std::cout << "  AVX2 not available — scalar only\n";
        std::cout << "  VWAP = " << vwap_s << "\n";
#endif
    }

    // -------------------------------------------------------
    // AUTO-VECTORIZED PNL
    // -------------------------------------------------------

    std::cout << "\n=== Auto-vectorized portfolio PnL ===\n";

    {
        constexpr int N = 500;
        std::vector<double> pos(N), mark(N), cost(N);
        for (int i = 0; i < N; ++i) {
            pos[i]  = (i % 3 == 0 ? -100.0 : 100.0);
            mark[i] = 182.50 + (i % 10) * 0.05;
            cost[i] = 182.00 + (i % 10) * 0.03;
        }

        double pnl = 0.0;
        bench("portfolio PnL (auto-vec)", [&]() {
            pnl = portfolio_pnl_auto(pos.data(), mark.data(), cost.data(), N);
        }, 10000);
        std::cout << "  Portfolio PnL (500 positions): $" << pnl << "\n";
    }

    // -------------------------------------------------------
    // SPREAD COMPUTATION
    // -------------------------------------------------------

    std::cout << "\n=== Spread computation: scalar vs SSE2 ===\n";

    {
        constexpr int N = 1024;
        std::vector<int64_t> bids(N), asks(N), sp_scalar(N), sp_sse2(N);
        for (int i = 0; i < N; ++i) {
            bids[i] = int64_t(1825000 + (i % 100) * 10);
            asks[i] = bids[i] + 100 + (i % 20);
        }

        bench("scalar spreads", [&]() {
            compute_spreads_scalar(bids.data(), asks.data(), sp_scalar.data(), N);
        }, 10000);

#if HAS_SSE2
        bench("SSE2 spreads  ", [&]() {
            compute_spreads_sse2(bids.data(), asks.data(), sp_sse2.data(), N);
        }, 10000);

        // Verify correctness
        bool ok = true;
        for (int i = 0; i < N; ++i) {
            if (sp_scalar[i] != sp_sse2[i]) { ok = false; break; }
        }
        std::cout << "  SSE2 results match scalar: " << ok << "\n";
        std::cout << "  Sample spread: " << sp_sse2[0] / 10000.0 << "x10K ticks"
                  << " = $" << sp_sse2[0] / 10000.0 << "\n";
#else
        std::cout << "  SSE2 not available\n";
#endif
    }

    // -------------------------------------------------------
    // ORDER BOOK SCAN
    // -------------------------------------------------------

    std::cout << "\n=== Order book scan (find best bid) ===\n";

    {
        constexpr int N = 10000;
        std::vector<int64_t> prices(N);
        for (int i = 0; i < N; ++i) {
            prices[i] = int64_t(1800000 + (i * 13) % 50000);
        }

        int64_t best = 0;
        bench("max_price scalar", [&]() {
            best = max_price_scalar(prices.data(), N);
        }, 10000);
        std::cout << "  Best price: $" << best / 10000.0 << "\n";
        std::cout << "  (auto-vectorizer handles this with -O2 -march=native)\n";
    }

    // -------------------------------------------------------
    // COMPILER AUTO-VECTORIZATION TIPS
    // -------------------------------------------------------

    std::cout << "\n=== Auto-vectorization tips ===\n";

    std::cout << "  Compile with: g++ -O2 -march=native -fopt-info-vec-optimized\n"
              << "  Or: clang++ -O2 -march=native -Rpass=loop-vectorize\n"
              << "\n"
              << "  Loops that auto-vectorize well:\n"
              << "    for(int i=0; i<N; ++i) out[i] = a[i] + b[i];  // stride-1, no deps\n"
              << "    for(int i=0; i<N; ++i) sum += arr[i];          // reduction\n"
              << "    for(int i=0; i<N; ++i) out[i] = arr[i] > 0;   // predicate\n"
              << "\n"
              << "  Loops that DON'T auto-vectorize:\n"
              << "    for(int i=0; i<N; ++i) out[i] = func(arr[i]); // function call\n"
              << "    for(int i=1; i<N; ++i) a[i] = a[i-1] + b[i]; // loop dependency\n"
              << "    for(int i=0; i<N; ++i) { if(arr[i]>0) ... }   // complex branch\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      AVX2 order book scan — find all levels with qty > threshold:

        // Find the first ask price level where there's enough qty to fill our order
        // Scalar: N comparisons. AVX2: N/4 comparisons.

        #include <immintrin.h>

        int find_fill_level(const int64_t* asks, const int32_t* qtys, int n,
                            int64_t limit_price, int32_t min_qty) {

            // AVX2 approach with 64-bit integers (ask prices)
            __m256i limit_vec = _mm256_set1_epi64x(limit_price);  // broadcast limit
            int i = 0;

            for (; i + 4 <= n; i += 4) {
                __m256i ask4 = _mm256_loadu_si256((__m256i*)(asks + i));

                // Compare: which of the 4 ask prices are <= limit_price?
                // (AVX2 has cmpeq_epi64 and cmpgt_epi64 for signed comparison)
                __m256i above = _mm256_cmpgt_epi64(ask4, limit_vec);  // > limit → 1

                int mask = _mm256_movemask_epi8(above);
                if (mask != 0) {
                    // At least one price exceeded limit — find exact index with scalar
                    for (int j = i; j < std::min(i+4, n); ++j) {
                        if (asks[j] > limit_price) return j;
                    }
                }
            }

            // Scalar tail
            for (; i < n; ++i) {
                if (asks[i] > limit_price) return i;
            }
            return n;  // all levels within limit
        }
    */
}
