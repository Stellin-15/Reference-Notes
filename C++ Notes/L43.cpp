// ============================================================
// L43: Memory Layout and Cache Efficiency
// ============================================================
// WHAT: How the CPU cache hierarchy works, how struct layout
//       affects performance, and how to choose between AoS
//       (Array of Structs) vs SoA (Struct of Arrays) for
//       maximum cache efficiency in hot loops.
// WHY (TRADING): Cache misses are the #1 hidden latency killer
//   in trading systems. L1 hit: 1ns. L3 miss → RAM: 70-100ns.
//   In a 10,000-level order book scan, if your struct layout
//   forces a cache miss per level, you pay 10,000 × 70ns = 700µs
//   just to scan the book. With cache-friendly SoA layout:
//   10,000 × 1ns = 10µs. The difference wins or loses fills.
// PHASE: Low-Latency Systems
// ============================================================

/*
  CONCEPT OVERVIEW:

  CPU CACHE HIERARCHY (typical x86_64 server):
    L1 data cache:  32-64 KB per core, ~1ns access
    L2 cache:       256KB-1MB per core, ~4ns access
    L3 cache:       8-64MB shared, ~15-40ns access
    Main RAM:       GB range, ~70-100ns access
    RULE: code that fits in L1 cache runs at full speed.
          Code that spills to RAM runs 70-100x slower.

  CACHE LINE = 64 BYTES (on all modern x86_64):
    The smallest unit of memory the CPU loads or stores.
    Even reading a single byte loads the entire 64-byte line.
    Implication: if you read field A at offset 0 and field B at
    offset 4 of the same struct, they come in the same cache line —
    B is "free" after A is loaded.

  PREFETCHING:
    CPU predicts what memory you'll need next and loads it ahead.
    Automatic for sequential access (stride-1): great for arrays.
    Manual: __builtin_prefetch(ptr, rw, locality) [GCC/Clang]
            _mm_prefetch(ptr, hint) [MSVC / intrinsics]
    HFT use: prefetch the next order book level while processing the current one.

  STRUCT PADDING AND ALIGNMENT:
    Compiler pads structs so each field is aligned to its size.
    int32_t at offset 4; int64_t at offset 8 (aligned to 8 bytes).
    Padding wastes bytes and means fewer useful fields per cache line.
    __attribute__((packed)) / #pragma pack — remove padding.
    Use only when you control the exact byte layout (binary protocol parsing).
    Cost: unaligned access is slow (or illegal on some architectures).

  AoS (Array of Structs) — default layout:
    struct Order { int64_t price; int32_t qty; ... };
    Order orders[N];
    Memory: [price0|qty0|...|price1|qty1|...|price2|qty2|...]
    Hot loop accessing only price: loads entire struct every time.
    Cache line carries qty, symbol, timestamp — all wasted.

  SoA (Struct of Arrays) — cache-friendly for loops:
    struct OrderBook {
        int64_t prices[N];
        int32_t qtys[N];
        ...
    };
    Memory: [price0|price1|price2|...|qty0|qty1|qty2|...]
    Hot loop accessing only price: 8 prices per cache line.
    8x fewer cache misses. Auto-vectorizable (SIMD for free).

  WHEN TO USE AoS vs SoA:
    AoS: when you always access many fields of the same object together.
         Example: processing a single Order (need price AND qty AND symbol).
    SoA: when you access ONE field across MANY objects in a loop.
         Example: scanning all bid prices to find the best bid.
    Hybrid: Hot fields in SoA, cold fields in AoS. Most HFT systems use hybrid.

  TRADING USE CASE:
    // Finding best bid — hot loop: access price only
    // SoA: 8 prices per cache line, ~1250 cache lines for 10K levels
    // AoS: 1 price per 64-byte struct, ~10K cache lines for 10K levels
    int64_t find_best_bid_SoA(const int64_t* prices, int n) {
        int64_t best = 0;
        for (int i = 0; i < n; ++i) {
            if (prices[i] > best) best = prices[i];
        }
        return best;  // 8x fewer cache misses vs AoS
    }

  COMMON MISTAKES:
    - Adding fields to hot structs without checking cache line count
    - Using AoS when only scanning one field (common mistake)
    - Forgetting that padding wastes cache lines (check offsetof/sizeof)
    - Using __attribute__((packed)) on structs with int64 fields (misaligned reads)
    - Not prefetching in order book sweep loops (easy 20-30% win)
*/

#include <iostream>
#include <chrono>
#include <vector>
#include <cstdint>
#include <cstring>
#include <algorithm>
#include <random>
#include <cassert>
#include <cstddef>   // offsetof

#if defined(__x86_64__) || defined(_M_X64)
#  include <immintrin.h>
#  define PREFETCH(ptr) _mm_prefetch((const char*)(ptr), _MM_HINT_T0)
#else
#  define PREFETCH(ptr) ((void)(ptr))
#endif

// ============================================================
// STRUCT LAYOUT DEMOS
// ============================================================

// BAD layout: fields in wrong order → 3 cache lines for a small struct
struct BadOrder {
    bool     is_buy;        // 1 byte — offset 0
    // 7 bytes padding (compiler aligns next int64_t to 8)
    int64_t  price;         // 8 bytes — offset 8
    bool     is_ioc;        // 1 byte — offset 16
    // 3 bytes padding
    int32_t  qty;           // 4 bytes — offset 20
    bool     is_market;     // 1 byte — offset 24
    // 7 bytes padding
    int64_t  order_id;      // 8 bytes — offset 32
    // Total size: 40 bytes, but padded larger for alignment
};

// GOOD layout: fields sorted largest to smallest → minimal padding
struct GoodOrder {
    int64_t  price;         // offset  0
    int64_t  order_id;      // offset  8
    int32_t  qty;           // offset 16
    uint8_t  is_buy;        // offset 20
    uint8_t  is_ioc;        // offset 21
    uint8_t  is_market;     // offset 22
    uint8_t  status;        // offset 23
    // 0 bytes padding
    // Total: 24 bytes — fits in first 24 bytes of a cache line
};

// ============================================================
// AoS (Array of Structs)
// ============================================================

struct Level_AoS {
    int64_t price;      // offset  0
    int32_t qty;        // offset  8
    int32_t num_orders; // offset 12
    char    pad[48];    // offset 16 — simulate a bigger struct with cold fields
    // Total: 64 bytes = 1 cache line
};

// ============================================================
// SoA (Struct of Arrays)
// ============================================================

struct OrderBook_SoA {
    static constexpr int LEVELS = 10000;

    int64_t prices[LEVELS];     // all prices contiguous
    int32_t qtys[LEVELS];       // all quantities contiguous
    int32_t num_orders[LEVELS]; // all order counts contiguous
};

// ============================================================
// BENCHMARKS
// ============================================================

int64_t find_best_bid_AoS(const Level_AoS* levels, int n) {
    int64_t best = 0;
    for (int i = 0; i < n; ++i) {
        if (levels[i].price > best) best = levels[i].price;
        // AoS: each access touches 64 bytes of data but only uses 8 bytes (price)
        // The other 56 bytes (qty, pad) are wasted cache space
    }
    return best;
}

int64_t find_best_bid_SoA(const int64_t* prices, int n) {
    int64_t best = 0;
    for (int i = 0; i < n; ++i) {
        if (prices[i] > best) best = prices[i];
        // SoA: 8 prices per cache line (int64 = 8 bytes, 64/8 = 8 per line)
        // 8x more useful data per cache miss
    }
    return best;
}

int64_t find_best_bid_SoA_prefetch(const int64_t* prices, int n) {
    int64_t best = 0;
    const int PREFETCH_DIST = 16;   // prefetch 16 elements ahead
    for (int i = 0; i < n; ++i) {
        if (i + PREFETCH_DIST < n) {
            PREFETCH(&prices[i + PREFETCH_DIST]);   // request next cache line early
        }
        if (prices[i] > best) best = prices[i];
    }
    return best;
}

template<typename Fn>
uint64_t bench(const std::string& label, Fn fn, int reps) {
    // Warmup
    for (int i = 0; i < 3; ++i) fn();

    auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < reps; ++i) fn();
    auto t1 = std::chrono::steady_clock::now();

    uint64_t ns = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());
    std::cout << "  [" << label << "] " << ns << "ns total, "
              << ns / reps << "ns/call\n";
    return ns;
}

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // STRUCT LAYOUT ANALYSIS
    // -------------------------------------------------------

    std::cout << "=== Struct layout analysis ===\n";

    std::cout << "  BadOrder:\n"
              << "    sizeof: " << sizeof(BadOrder) << " bytes\n"
              << "    offsetof(is_buy):   " << offsetof(BadOrder, is_buy) << "\n"
              << "    offsetof(price):    " << offsetof(BadOrder, price) << "\n"
              << "    offsetof(qty):      " << offsetof(BadOrder, qty) << "\n"
              << "    offsetof(order_id): " << offsetof(BadOrder, order_id) << "\n"
              << "    cache lines needed: " << (sizeof(BadOrder) + 63) / 64 << "\n";

    std::cout << "  GoodOrder:\n"
              << "    sizeof: " << sizeof(GoodOrder) << " bytes\n"
              << "    offsetof(price):    " << offsetof(GoodOrder, price) << "\n"
              << "    offsetof(order_id): " << offsetof(GoodOrder, order_id) << "\n"
              << "    offsetof(qty):      " << offsetof(GoodOrder, qty) << "\n"
              << "    offsetof(is_buy):   " << offsetof(GoodOrder, is_buy) << "\n"
              << "    cache lines needed: " << (sizeof(GoodOrder) + 63) / 64 << "\n";

    // -------------------------------------------------------
    // CACHE LINE MATH
    // -------------------------------------------------------

    std::cout << "\n=== Cache line utilization ===\n";

    {
        constexpr int LEVELS = 10000;
        int AoS_cache_lines = (sizeof(Level_AoS) * LEVELS + 63) / 64;
        int SoA_price_lines = (sizeof(int64_t)   * LEVELS + 63) / 64;
        std::cout << "  " << LEVELS << " order book levels:\n"
                  << "    AoS layout: " << AoS_cache_lines
                  << " cache lines to scan all prices\n"
                  << "    SoA layout: " << SoA_price_lines
                  << " cache lines to scan all prices\n"
                  << "    Ratio: " << AoS_cache_lines / SoA_price_lines << "x more cache lines in AoS\n";
    }

    // -------------------------------------------------------
    // BENCHMARK: AoS vs SoA
    // -------------------------------------------------------

    std::cout << "\n=== AoS vs SoA benchmark (find best bid) ===\n";

    {
        constexpr int N = 10000;
        constexpr int REPS = 1000;

        // Fill AoS with random prices
        std::vector<Level_AoS> aos(N);
        std::mt19937_64 rng(42);
        for (auto& lv : aos) {
            lv.price = int64_t(1800000 + rng() % 50000);
            lv.qty   = 100;
        }

        // Fill SoA with same prices
        OrderBook_SoA soa{};
        for (int i = 0; i < N; ++i) soa.prices[i] = aos[i].price;

        auto b_aos = bench("AoS (best bid)", [&]() {
            return find_best_bid_AoS(aos.data(), N);
        }, REPS);

        auto b_soa = bench("SoA (best bid)", [&]() {
            return find_best_bid_SoA(soa.prices, N);
        }, REPS);

        auto b_pre = bench("SoA+prefetch  ", [&]() {
            return find_best_bid_SoA_prefetch(soa.prices, N);
        }, REPS);

        if (b_soa > 0) {
            std::cout << "  AoS/SoA ratio:     " << double(b_aos)/b_soa << "x\n";
            std::cout << "  AoS/SoA+pre ratio: " << double(b_aos)/b_pre << "x\n";
        }
        std::cout << "  (improvement is most pronounced on cold cache / large datasets)\n";
    }

    // -------------------------------------------------------
    // HOT vs COLD FIELD SEPARATION
    // -------------------------------------------------------

    std::cout << "\n=== Hot/cold field split ===\n";

    {
        // PRINCIPLE: put hot (frequently accessed) fields first.
        // In matching: we access price, qty, order_id constantly.
        // symbol, timestamp, client_id — rarely accessed (logging only).

        struct alignas(64) OrderHot {
            int64_t  price;       // 8
            int32_t  qty;         // 4
            int32_t  remain_qty;  // 4
            uint64_t order_id;    // 8
            uint8_t  side;        // 1
            uint8_t  type;        // 1
            uint8_t  status;      // 1
            uint8_t  pad[5];      // 5 → total 32 bytes (half a cache line)
        };
        // Cold fields in a separate array, indexed by the same position:
        struct OrderCold {
            char     symbol[8];
            uint64_t timestamp_ns;
            uint64_t client_order_id;
            char     account[8];
        };

        std::cout << "  OrderHot size:  " << sizeof(OrderHot)  << " bytes\n";
        std::cout << "  OrderCold size: " << sizeof(OrderCold) << " bytes\n";
        std::cout << "  Hot/cold split: only load cold fields when logging/reporting\n";
        std::cout << "  Matching engine never touches cold — stays in L1 cache\n";
    }

    // -------------------------------------------------------
    // PREFETCH MANUAL DEMO
    // -------------------------------------------------------

    std::cout << "\n=== Manual prefetch ===\n";

    {
        std::vector<int64_t> data(1024);
        for (int i = 0; i < 1024; ++i) data[i] = i * 100;

        const int PREFETCH_DIST = 8;
        int64_t sum = 0;

        for (int i = 0; i < 1024; ++i) {
            if (i + PREFETCH_DIST < 1024) {
                PREFETCH(&data[i + PREFETCH_DIST]);
            }
            sum += data[i];
        }
        std::cout << "  Sum with prefetch: " << sum << " (correctness check)\n";
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Hybrid layout for a real order book with 5 levels of depth:

        // Hot path: price and qty for bid/ask matching
        // Stored in SoA for vectorized scanning

        struct alignas(64) BookHot {
            int64_t bid_prices[5];   // 40 bytes: top 5 bid prices
            int64_t ask_prices[5];   // 40 bytes: top 5 ask prices
            int32_t bid_qtys[5];     // 20 bytes: top 5 bid quantities
            int32_t ask_qtys[5];     // 20 bytes: top 5 ask quantities
        };
        // 120 bytes = 2 cache lines — entire BBO view in 2 lines

        // Cold path: order IDs at each level (for cancel/modify)
        struct BookCold {
            std::vector<uint64_t> bid_order_ids[5];
            std::vector<uint64_t> ask_order_ids[5];
        };

        // Hot path (every tick): only access BookHot — 2 cache lines
        void on_tick(const BookHot& hot) {
            int64_t best_bid = hot.bid_prices[0];
            int64_t best_ask = hot.ask_prices[0];
            double mid = (best_bid + best_ask) / 2.0 / 10000.0;
            if (has_signal(mid)) send_order(...);
        }

        // Cold path (cancel event): access BookCold
        void on_cancel(int level, uint64_t id, BookCold& cold) {
            auto& ids = cold.bid_order_ids[level];
            ids.erase(std::find(ids.begin(), ids.end(), id));
        }
    */
}
