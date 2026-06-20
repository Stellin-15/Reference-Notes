// ============================================================
// L10: Arrays and Multi-Dimensional Arrays
// ============================================================
// WHAT: Fixed-size collections of same-type elements stored
//       contiguously in memory. C-style arrays and std::array.
// WHY (TRADING): Arrays are the core of performance-critical
//   data storage. Price history buffers, order book levels,
//   portfolio weight vectors — all arrays. Contiguous memory
//   means the CPU prefetcher can load the next elements before
//   you even ask for them, making iteration very fast.
// PHASE: Foundation
// ============================================================

/*
  CONCEPT OVERVIEW:

  C-STYLE ARRAY:
    type name[SIZE];               — declare
    type name[SIZE] = {v1, v2};   — declare + initialize
    name[0] = value;               — access (0-indexed!)
    sizeof(arr) / sizeof(arr[0])   — number of elements
    No bounds checking — out-of-bounds access = undefined behavior (UB)

  std::array (PREFER THIS):
    #include <array>
    std::array<type, SIZE> name = {v1, v2};
    name[i]       — access without bounds check (fast)
    name.at(i)    — access WITH bounds check (throws if out of range)
    name.size()   — number of elements (safe)
    name.data()   — raw pointer to first element (for C APIs)
    Benefits over C arrays: knows its own size, works with STL algorithms,
    can be returned from functions, has .fill(), .begin(), .end()

  STACK vs HEAP:
    Both C arrays and std::array live on the STACK (fast allocation, auto cleanup).
    For runtime-sized arrays, use std::vector (heap — covered in L27).
    In HFT: prefer stack arrays for fixed-size buffers (order book levels, tick history)

  MEMORY LAYOUT — WHY ARRAYS ARE FAST:
    Elements are stored consecutively in memory (no gaps for same-type arrays).
    A cache line is 64 bytes. A double array of 8 elements = exactly 1 cache line.
    When you access arr[0], the CPU loads the entire cache line,
    so arr[1] through arr[7] are already in cache — "free" accesses.

  MULTI-DIMENSIONAL ARRAYS:
    double matrix[ROWS][COLS];     — row-major storage
    matrix[row][col]               — access
    IMPORTANT: in C++, the LAST index varies fastest in memory.
    Efficient: for(row) { for(col) { matrix[row][col]; } }   — sequential
    Inefficient: for(col) { for(row) { matrix[row][col]; } } — cache thrashing

  TRADING USE CASE:
    std::array<double, 256> price_buffer;  // last 256 ticks
    std::array<int, 10>     book_quantities;  // top 10 levels of order book
    double correlation[SYMBOLS][SYMBOLS];  // correlation matrix for pairs trading

  COMMON MISTAKES:
    - Off-by-one: arr[size] accesses one past the end (UB, crash)
    - C-style array decay to pointer when passed to functions (loses size info)
    - Wrong loop order for 2D arrays (cache thrashing)
    - Declaring huge arrays on the stack (stack overflow — use vector/heap)
*/

#include <iostream>
#include <array>
#include <algorithm>   // std::sort, std::fill, std::min/max_element
#include <numeric>     // std::accumulate

int main() {

    // -------------------------------------------------------
    // C-STYLE ARRAY — the original (use std::array instead)
    // -------------------------------------------------------

    std::cout << "--- C-style array ---\n";

    // Fixed size must be a compile-time constant
    const int HISTORY_SIZE = 5;
    double price_history[HISTORY_SIZE] = {100.10, 100.25, 100.15, 100.30, 100.20};

    // Access elements by index (0-based)
    std::cout << "Latest price: $" << price_history[HISTORY_SIZE - 1] << "\n";

    // Iterate
    double sum = 0.0;
    for (int i = 0; i < HISTORY_SIZE; ++i) {
        sum += price_history[i];
    }
    double moving_avg = sum / HISTORY_SIZE;
    std::cout << "5-period moving average: $" << moving_avg << "\n";

    // sizeof trick to get element count (use with caution — doesn't work on pointer)
    int count = sizeof(price_history) / sizeof(price_history[0]);
    std::cout << "Array element count: " << count << "\n";

    // -------------------------------------------------------
    // std::array — PREFER THIS over C arrays
    // -------------------------------------------------------

    std::cout << "\n--- std::array (modern C++) ---\n";

    // std::array<type, size> — size must be compile-time constant
    std::array<double, 10> tick_buffer = {};  // zero-initialize all elements
    tick_buffer[0] = 100.50;
    tick_buffer[1] = 100.55;
    tick_buffer[2] = 100.48;

    std::cout << "Size: " << tick_buffer.size() << "\n";  // 10 (always knows its size)
    std::cout << "First tick: $" << tick_buffer[0] << "\n";

    // .fill() sets all elements to a value
    tick_buffer.fill(0.0);   // reset buffer

    // .data() gives raw pointer (needed when passing to C-style APIs)
    double* raw_ptr = tick_buffer.data();
    raw_ptr[0] = 101.00;
    std::cout << "After fill+set via pointer: " << tick_buffer[0] << "\n";

    // -------------------------------------------------------
    // STL ALGORITHMS ON ARRAYS
    // -------------------------------------------------------

    std::cout << "\n--- STL algorithms on array ---\n";

    std::array<double, 8> prices = {182.5, 185.0, 181.0, 187.5, 183.0, 186.0, 184.5, 188.0};

    // Sort ascending
    std::sort(prices.begin(), prices.end());
    std::cout << "Sorted: ";
    for (double p : prices) std::cout << p << " ";
    std::cout << "\n";

    // Min and max (useful for daily high/low)
    auto [min_it, max_it] = std::minmax_element(prices.begin(), prices.end());
    std::cout << "Daily low:  $" << *min_it << "\n";
    std::cout << "Daily high: $" << *max_it << "\n";

    // Sum (for VWAP numerator)
    double total = std::accumulate(prices.begin(), prices.end(), 0.0);
    std::cout << "Sum: $" << total << " | Avg: $" << (total / prices.size()) << "\n";

    // -------------------------------------------------------
    // MULTI-DIMENSIONAL ARRAY — correlation/covariance matrix
    // -------------------------------------------------------

    std::cout << "\n--- 2D array: correlation matrix ---\n";

    const int N = 3;   // 3 symbols: AAPL, MSFT, TSLA
    const char* symbols[N] = {"AAPL", "MSFT", "TSLA"};

    // Pre-computed correlation values (normally calculated from historical data)
    double correlation[N][N] = {
        {1.00, 0.72, 0.45},   // AAPL vs [AAPL, MSFT, TSLA]
        {0.72, 1.00, 0.38},   // MSFT vs [AAPL, MSFT, TSLA]
        {0.45, 0.38, 1.00},   // TSLA vs [AAPL, MSFT, TSLA]
    };

    // Print matrix — iterate ROW first (cache efficient: row-major storage)
    for (int i = 0; i < N; ++i) {
        std::cout << symbols[i] << ": ";
        for (int j = 0; j < N; ++j) {
            std::cout << correlation[i][j] << "  ";
        }
        std::cout << "\n";
    }

    // Find highly correlated pairs (for pairs trading strategy)
    std::cout << "\nHighly correlated pairs (>0.6):\n";
    for (int i = 0; i < N; ++i) {
        for (int j = i + 1; j < N; ++j) {   // j = i+1 to avoid duplicates
            if (correlation[i][j] > 0.6) {
                std::cout << "  " << symbols[i] << " / " << symbols[j]
                          << " = " << correlation[i][j] << "\n";
            }
        }
    }

    // -------------------------------------------------------
    // RING BUFFER — the HFT tick history pattern
    // -------------------------------------------------------

    std::cout << "\n--- Ring buffer: tick history ---\n";

    // A ring buffer stores the last N ticks without shifting memory.
    // Write pointer wraps around using modulo (or bitwise AND if power of 2).
    constexpr int  RING_SIZE = 8;  // power of 2 for fast wrap
    std::array<double, RING_SIZE> ring_buffer = {};
    int write_pos = 0;

    // Simulate receiving 12 ticks into an 8-slot buffer
    double incoming_ticks[] = {100.1, 100.2, 100.3, 100.4, 100.5, 100.6, 100.7, 100.8, 100.9, 101.0, 101.1, 101.2};

    for (double t : incoming_ticks) {
        ring_buffer[write_pos & (RING_SIZE - 1)] = t;  // fast modulo (power of 2)
        write_pos++;
    }

    std::cout << "Last " << RING_SIZE << " ticks in ring buffer:\n";
    for (int i = 0; i < RING_SIZE; ++i) {
        // Read in chronological order from oldest to newest
        int idx = (write_pos + i) & (RING_SIZE - 1);
        std::cout << "  [" << i << "] $" << ring_buffer[idx] << "\n";
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Order book top-of-book array (the most accessed data in HFT):

        constexpr int MAX_LEVELS = 10;

        struct Level {
            int64_t price;    // price in ticks
            int32_t qty;      // total quantity at this level
            int16_t count;    // number of orders at this level
        };  // 14 bytes — 4 Level structs fit in one cache line (64 bytes)

        std::array<Level, MAX_LEVELS> bids;  // top 10 bids, sorted descending
        std::array<Level, MAX_LEVELS> asks;  // top 10 asks, sorted ascending

        // Entire bids or asks array fits in ~2-3 cache lines.
        // Sweeping through levels on a large order = all cache hits.
    */
}
