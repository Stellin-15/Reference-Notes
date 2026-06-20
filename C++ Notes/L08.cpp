// ============================================================
// L08: Loops — for, while, do-while, range-based for
// ============================================================
// WHAT: How to repeat code a fixed number of times or until
//       a condition changes.
// WHY (TRADING): Loops power the core of every trading system:
//   - Iterating order book levels to find best execution price
//   - Processing a batch of market data messages
//   - Scanning a portfolio of positions for risk
//   - The main event loop that runs until market close
// PHASE: Foundation
// ============================================================

/*
  CONCEPT OVERVIEW:

  FOR LOOP — when you know how many iterations ahead of time:
    for (init; condition; update) { body }
    - init: runs once at the start
    - condition: checked before each iteration; false = stop
    - update: runs after each iteration
    Use int i, but prefer size_t for indices into arrays (unsigned)

  WHILE LOOP — when you don't know how many iterations:
    while (condition) { body }
    - Checks condition BEFORE each iteration
    - If condition is false at the start, body never runs

  DO-WHILE LOOP — when you need at least one iteration:
    do { body } while (condition);
    - Executes body FIRST, then checks condition
    - Rare in practice — useful for retry logic

  RANGE-BASED FOR (C++11):
    for (auto& element : container) { ... }
    - Cleaner than index-based for containers (vectors, arrays)
    - Use & (reference) to avoid copying each element
    - Use const& for read-only access

  BREAK AND CONTINUE:
    break    — immediately exits the loop
    continue — skips to the next iteration

  LOOP UNROLLING (advanced, mentioned for awareness):
    The compiler can duplicate loop body N times to reduce
    loop overhead (branch checks, counter updates).
    #pragma GCC unroll 4  — hint to unroll 4x
    Or just use algorithms (std::transform) which the compiler
    unrolls automatically. (Covered in L28/L45)

  PERFORMANCE — LOOP ORDER MATTERS FOR CACHE:
    When iterating a 2D array, iterate row by row (inner loop over columns),
    NOT column by column. Memory is stored row-major in C++.
    Iterating columns first = cache miss every step = 100x slower.

  TRADING USE CASE:
    // Scan order book levels for best execution
    for (int level = 0; level < book.num_levels; ++level) {
        if (book.ask[level].price > limit_price) break;  // gone past limit
        fill_qty += std::min(remaining, book.ask[level].qty);
        remaining -= fill_qty;
        if (remaining == 0) break;  // fully filled
    }

  COMMON MISTAKES:
    - Off-by-one: use < size, not <= size (last valid index is size-1)
    - Infinite loop: forgetting to update the loop variable
    - Modifying a container while iterating it (use index loop or erase-remove)
    - Using signed int for array index — prefer size_t or int carefully
*/

#include <iostream>
#include <vector>
#include <cstdint>
#include <cmath>   // for std::abs

int main() {

    // -------------------------------------------------------
    // FOR LOOP — scanning order book levels
    // -------------------------------------------------------

    std::cout << "--- For loop: scan ask levels ---\n";

    // Simulated order book ask side (price, quantity) pairs
    struct Level { double price; int qty; };
    Level asks[] = {
        {100.55, 200},
        {100.60, 500},
        {100.65, 300},
        {100.70, 100},
        {100.75, 800},
    };
    int num_levels = 5;

    double limit_price = 100.65;  // We'll only buy up to this price
    int    target_qty  = 600;
    int    filled      = 0;

    for (int i = 0; i < num_levels; ++i) {   // ++i preferred over i++ in loops
        if (asks[i].price > limit_price) {
            std::cout << "Reached limit price — stopping sweep\n";
            break;  // Don't buy above our limit
        }
        int take = std::min(target_qty - filled, asks[i].qty);
        filled += take;
        std::cout << "Level " << i << ": bought " << take
                  << " @ $" << asks[i].price << "\n";
        if (filled >= target_qty) {
            std::cout << "Target quantity reached\n";
            break;
        }
    }
    std::cout << "Total filled: " << filled << " / " << target_qty << "\n";

    // -------------------------------------------------------
    // WHILE LOOP — main event loop pattern
    // -------------------------------------------------------

    std::cout << "\n--- While loop: event loop pattern ---\n";

    // In a real trading system, this runs until market close or kill switch
    bool market_open  = true;
    int  ticks_received = 0;
    int  MAX_TICKS    = 5;   // Just for demo — in reality this loop runs all day

    while (market_open) {
        // Simulate receiving a market data tick
        ticks_received++;
        std::cout << "Processing tick " << ticks_received << "\n";

        // In a real system: parse the packet, update order book, run strategy
        // For demo: stop after MAX_TICKS
        if (ticks_received >= MAX_TICKS) {
            market_open = false;   // signal to end the loop
        }
    }
    std::cout << "Market closed. Total ticks processed: " << ticks_received << "\n";

    // -------------------------------------------------------
    // DO-WHILE — retry logic (connect to exchange)
    // -------------------------------------------------------

    std::cout << "\n--- Do-while: connection retry ---\n";

    int  attempts     = 0;
    bool connected    = false;
    int  MAX_ATTEMPTS = 3;

    do {
        attempts++;
        std::cout << "Connection attempt " << attempts << "...\n";

        // Simulate success on attempt 2
        if (attempts == 2) {
            connected = true;
            std::cout << "Connected to exchange!\n";
        }

    } while (!connected && attempts < MAX_ATTEMPTS);

    if (!connected) {
        std::cout << "[ERROR] Failed to connect after " << MAX_ATTEMPTS << " attempts\n";
    }

    // -------------------------------------------------------
    // RANGE-BASED FOR — iterating a portfolio
    // -------------------------------------------------------

    std::cout << "\n--- Range-based for: portfolio PnL ---\n";

    struct Position {
        const char* symbol;
        int         quantity;     // positive = long, negative = short
        double      avg_cost;
        double      current_price;
    };

    // Simulate a small portfolio
    std::vector<Position> portfolio = {
        {"AAPL",  100,  182.50, 185.00},
        {"TSLA", -50,   245.00, 240.00},
        {"MSFT",  200,  420.00, 418.50},
    };

    double total_pnl = 0.0;

    for (const auto& pos : portfolio) {     // const& = read-only, no copy
        double pnl = (pos.current_price - pos.avg_cost) * pos.quantity;
        total_pnl += pnl;
        std::cout << pos.symbol << ": qty=" << pos.quantity
                  << " avg=$" << pos.avg_cost
                  << " curr=$" << pos.current_price
                  << " PnL=$" << pnl << "\n";
    }
    std::cout << "Total portfolio PnL: $" << total_pnl << "\n";

    // -------------------------------------------------------
    // CONTINUE — skip invalid ticks without breaking the loop
    // -------------------------------------------------------

    std::cout << "\n--- Continue: skip bad ticks ---\n";

    // Simulate a stream of price ticks, some of which are invalid (0 price)
    double ticks[] = {100.50, 0.0, 100.55, 0.0, 100.52, 100.60};
    int    tick_count = 6;
    int    valid_ticks = 0;

    for (int i = 0; i < tick_count; ++i) {
        if (ticks[i] <= 0.0) {
            std::cout << "Tick " << i << ": invalid (skipping)\n";
            continue;   // skip to next iteration without processing
        }
        valid_ticks++;
        std::cout << "Tick " << i << ": $" << ticks[i] << " (valid)\n";
    }
    std::cout << "Valid ticks: " << valid_ticks << " / " << tick_count << "\n";

    // -------------------------------------------------------
    // 2D ARRAY LOOP — ROW-MAJOR access for cache efficiency
    // -------------------------------------------------------

    std::cout << "\n--- 2D loop: row-major access (cache friendly) ---\n";

    // Matrix of historical prices: [symbols][days]
    // Access pattern: iterate days for each symbol (row = symbol, col = day)
    const int SYMBOLS = 3;
    const int DAYS    = 4;

    double prices[SYMBOLS][DAYS] = {
        {180.0, 181.5, 182.0, 183.0},  // AAPL
        {420.0, 419.0, 421.5, 422.0},  // MSFT
        {240.0, 242.0, 241.0, 243.5},  // TSLA
    };

    // CORRECT order: outer loop = symbols (rows), inner = days (columns)
    // This accesses memory sequentially — cache lines stay warm
    for (int s = 0; s < SYMBOLS; ++s) {
        double sum = 0.0;
        for (int d = 0; d < DAYS; ++d) {
            sum += prices[s][d];   // sequential memory access = fast
        }
        std::cout << "Symbol " << s << " avg: $" << (sum / DAYS) << "\n";
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      The real-time event loop of a simple trading system:

        while (!kill_switch.load(std::memory_order_relaxed)) {
            // Try to receive a market data packet (non-blocking)
            int bytes = recv(sock_fd, buf, sizeof(buf), MSG_DONTWAIT);
            if (bytes <= 0) continue;   // No packet yet — loop again

            // Parse the message
            auto msg = parse_itch_message(buf, bytes);
            order_book.apply(msg);

            // Run strategy on updated book
            auto signal = strategy.on_tick(order_book);
            if (signal.has_value()) {
                risk.check(signal.value());  // pre-trade risk
                gateway.send(signal.value());
            }
        }

      This loop runs hundreds of thousands of times per second.
      Every branch and every memory access inside it matters.
    */
}
