// ============================================================
// L28: STL Algorithms
// ============================================================
// WHAT: The <algorithm> and <numeric> headers provide 100+
//       ready-to-use algorithms: sorting, searching, transforming,
//       accumulating, and more. All work on iterators — any
//       container that provides begin()/end() works.
// WHY (TRADING): STL algorithms are highly optimized and often
//   auto-vectorized by the compiler. Using them instead of manual
//   loops gets you SIMD vectorization for free. Sorting fills by
//   time, scanning for best execution price, computing VWAP,
//   finding position limits violations — all expressible as
//   one-liners with STL algorithms.
// PHASE: Modern C++
// ============================================================

/*
  KEY ALGORITHMS BY CATEGORY:

  SEARCHING:
    std::find(begin, end, val)             — first match or end
    std::find_if(begin, end, pred)         — first where pred returns true
    std::binary_search(begin, end, val)    — true/false if val exists (sorted range)
    std::lower_bound(begin, end, val)      — iterator to first element >= val (sorted)
    std::upper_bound(begin, end, val)      — iterator to first element >  val (sorted)

  SORTING:
    std::sort(begin, end)                  — O(n log n), not stable
    std::stable_sort(begin, end)           — preserves equal-element order
    std::partial_sort(begin, mid, end)     — sort only first N elements
    std::nth_element(begin, nth, end)      — nth element in sorted position, rest partitioned
    std::is_sorted(begin, end)             — check if already sorted

  TRANSFORMING:
    std::transform(begin, end, out, func)  — apply func to each, write to out
    std::for_each(begin, end, func)        — apply func to each (no output)
    std::copy(begin, end, out)             — copy range to out
    std::fill(begin, end, val)             — set all elements to val
    std::reverse(begin, end)              — reverse in place
    std::rotate(begin, mid, end)           — rotate so mid becomes first

  NUMERIC (in <numeric>):
    std::accumulate(begin, end, init)      — sum (or other reduction)
    std::reduce(begin, end)                — parallel-friendly accumulate (C++17)
    std::inner_product(begin,end,b2,init)  — dot product (correlation, regression)
    std::partial_sum(begin, end, out)      — running sum (cumulative PnL)
    std::adjacent_difference(begin,end,out)— element-to-element differences (returns)

  PARTITIONING:
    std::partition(begin, end, pred)       — all true-elements first, false after
    std::stable_partition(...)             — same, preserves relative order
    std::partition_copy(...)               — copy two partitions to two outputs

  MIN/MAX:
    std::min_element(begin, end)           — iterator to smallest
    std::max_element(begin, end)           — iterator to largest
    std::minmax_element(begin, end)        — both at once (efficient)

  BINARY SEARCH (CRITICAL FOR ORDER BOOK):
    std::lower_bound: find where to insert to keep sorted order
    std::upper_bound: find range end in a sorted container
    These are O(log n) on sorted containers. Used for: finding the best fill
    price level in a sorted book, checking if a price level exists.

  TRADING USE CASE:
    // VWAP calculation
    double vwap = std::inner_product(prices.begin(), prices.end(), volumes.begin(), 0.0)
                / std::accumulate(volumes.begin(), volumes.end(), 0.0);

    // Find first price level that exceeds our limit
    auto it = std::upper_bound(ask_prices.begin(), ask_prices.end(), limit_price);

    // Sort fills by time then price
    std::sort(fills.begin(), fills.end(), [](const Fill& a, const Fill& b) { ... });

    // Check if risk limit is violated (any position over max)
    bool violation = std::any_of(positions.begin(), positions.end(),
        [](const Pos& p) { return std::abs(p.qty) > MAX_POS; });
*/

#include <iostream>
#include <vector>
#include <algorithm>
#include <numeric>
#include <array>
#include <cstdint>
#include <cmath>
#include <string>

// ============================================================
// TYPES
// ============================================================

struct Fill {
    uint64_t    order_id;
    std::string symbol;
    double      price;
    int32_t     qty;
    bool        is_buy;
    uint64_t    timestamp_ns;
};

struct Position {
    std::string symbol;
    int64_t     net_qty;
    double      avg_cost;
};

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // SORTING
    // -------------------------------------------------------

    std::cout << "=== Sorting ===\n";

    {
        std::vector<Fill> fills = {
            {1001, "AAPL", 182.55, 100, true,  1000},
            {1002, "AAPL", 182.50, 200, true,  998},   // earlier
            {1003, "AAPL", 182.60,  50, false, 1001},
            {1004, "AAPL", 182.50, 150, true,  999},   // same price as 1002, later time
            {1005, "AAPL", 183.00,  75, false, 1002},
        };

        // Sort by price descending, then by timestamp ascending (FIFO at same price)
        std::sort(fills.begin(), fills.end(),
            [](const Fill& a, const Fill& b) {
                if (a.price != b.price) return a.price > b.price;  // price desc
                return a.timestamp_ns < b.timestamp_ns;             // time asc
            });

        std::cout << "Fills sorted by price (desc) then time:\n";
        for (const auto& f : fills) {
            std::cout << "  #" << f.order_id
                      << " $" << f.price << " x" << f.qty
                      << " ts=" << f.timestamp_ns << "\n";
        }

        // partial_sort: sort only the top 3 fills (saves work when n >> k)
        std::vector<Fill> top_fills = fills;  // copy
        std::partial_sort(top_fills.begin(), top_fills.begin() + 3, top_fills.end(),
            [](const Fill& a, const Fill& b) { return a.qty > b.qty; });  // largest qty first
        std::cout << "Top 3 by qty:\n";
        for (int i = 0; i < 3; ++i) {
            std::cout << "  #" << top_fills[i].order_id << " qty=" << top_fills[i].qty << "\n";
        }
    }

    // -------------------------------------------------------
    // SEARCHING AND BINARY SEARCH
    // -------------------------------------------------------

    std::cout << "\n=== Searching ===\n";

    {
        // Sorted ask prices (in ticks) — simulated order book
        std::vector<int64_t> ask_prices = {1825000, 1825100, 1825500, 1826000, 1826500, 1827000};

        int64_t limit_price = 1825300;  // we'll buy up to this price

        // lower_bound: first element >= limit_price
        auto lb = std::lower_bound(ask_prices.begin(), ask_prices.end(), limit_price);
        std::cout << "Lower bound of " << limit_price
                  << ": $" << *lb / 10000.0 << " (first >= limit)\n";

        // upper_bound: first element > limit_price
        auto ub = std::upper_bound(ask_prices.begin(), ask_prices.end(), limit_price);
        std::cout << "Upper bound of " << limit_price
                  << ": $" << *ub / 10000.0 << " (first > limit)\n";

        // Range of levels we can sweep with this limit order: [begin, lb)
        std::cout << "Sweepable levels:\n";
        for (auto it = ask_prices.begin(); it != lb; ++it) {
            std::cout << "  $" << *it / 10000.0 << "\n";
        }

        // find_if: first position that violates risk limit
        std::vector<Position> positions = {
            {"AAPL",  500, 182.50},
            {"TSLA", -1500, 245.00},  // short position, may violate
            {"MSFT",  800, 420.00},
        };

        constexpr int64_t MAX_ABS_QTY = 1000;
        auto violator = std::find_if(positions.begin(), positions.end(),
            [](const Position& p) { return std::abs(p.net_qty) > MAX_ABS_QTY; });

        if (violator != positions.end()) {
            std::cout << "Risk violation: " << violator->symbol
                      << " net_qty=" << violator->net_qty << "\n";
        }

        // binary_search: is a specific price in the book?
        bool has_182_55 = std::binary_search(ask_prices.begin(), ask_prices.end(), 1825500LL);
        bool has_182_52 = std::binary_search(ask_prices.begin(), ask_prices.end(), 1825200LL);
        std::cout << "Book has $182.55: " << has_182_55 << "\n";
        std::cout << "Book has $182.52: " << has_182_52 << "\n";
    }

    // -------------------------------------------------------
    // NUMERIC ALGORITHMS — VWAP, PnL, returns
    // -------------------------------------------------------

    std::cout << "\n=== Numeric algorithms ===\n";

    {
        // Trade data: price and volume for VWAP calculation
        std::vector<double> prices  = {182.50, 182.55, 182.48, 182.60, 182.52};
        std::vector<double> volumes = {1000.0, 500.0,  800.0,  300.0,  700.0};

        // VWAP = sum(price * volume) / sum(volume)
        double sum_pv = std::inner_product(prices.begin(), prices.end(), volumes.begin(), 0.0);
        double sum_v  = std::accumulate(volumes.begin(), volumes.end(), 0.0);
        double vwap   = sum_pv / sum_v;
        std::cout << "VWAP: $" << vwap << "\n";

        // Simple average price
        double avg_price = sum_v > 0 ? std::accumulate(prices.begin(), prices.end(), 0.0) / prices.size() : 0.0;
        std::cout << "Simple avg: $" << avg_price << "\n";

        // Max and min tick (daily high/low)
        auto [min_it, max_it] = std::minmax_element(prices.begin(), prices.end());
        std::cout << "Daily low: $" << *min_it << "  Daily high: $" << *max_it << "\n";

        // Daily PnL array (filled by each trade, running total at end)
        std::vector<double> trade_pnls = {+150.0, -75.0, +220.0, -30.0, +100.0, -50.0};

        // Cumulative PnL: partial_sum (running total)
        std::vector<double> cumulative_pnl(trade_pnls.size());
        std::partial_sum(trade_pnls.begin(), trade_pnls.end(), cumulative_pnl.begin());
        std::cout << "Cumulative PnL:\n";
        for (size_t i = 0; i < cumulative_pnl.size(); ++i) {
            std::cout << "  Trade " << i+1 << ": $" << cumulative_pnl[i] << "\n";
        }

        // Max drawdown: min element of cumulative PnL (simplistic version)
        double max_drawdown = *std::min_element(cumulative_pnl.begin(), cumulative_pnl.end());
        std::cout << "Max drawdown point: $" << max_drawdown << "\n";

        // Tick-to-tick returns (adjacent_difference)
        std::vector<double> returns(prices.size());
        std::adjacent_difference(prices.begin(), prices.end(), returns.begin());
        std::cout << "Tick returns:\n";
        for (size_t i = 1; i < returns.size(); ++i) {
            std::cout << "  return " << i << ": " << returns[i] << "\n";
        }
    }

    // -------------------------------------------------------
    // TRANSFORM — converting between representations
    // -------------------------------------------------------

    std::cout << "\n=== std::transform ===\n";

    {
        // Convert dollar prices to integer ticks
        std::vector<double>  prices_usd  = {182.50, 183.00, 182.75, 183.25};
        std::vector<int64_t> prices_ticks(prices_usd.size());

        std::transform(prices_usd.begin(), prices_usd.end(), prices_ticks.begin(),
            [](double p) { return static_cast<int64_t>(p * 10000); });

        std::cout << "Prices in ticks: ";
        for (int64_t t : prices_ticks) std::cout << t << " ";
        std::cout << "\n";

        // Compute notional values from price × quantity arrays
        std::vector<int32_t> quantities = {100, 200, 50, 300};
        std::vector<double>  notionals(quantities.size());

        std::transform(prices_usd.begin(), prices_usd.end(),
                       quantities.begin(),
                       notionals.begin(),
                       [](double p, int q) { return p * q; });

        std::cout << "Notionals: ";
        for (double n : notionals) std::cout << "$" << n << " ";
        std::cout << "\n";

        double total_notional = std::accumulate(notionals.begin(), notionals.end(), 0.0);
        std::cout << "Total notional: $" << total_notional << "\n";
    }

    // -------------------------------------------------------
    // PARTITION — split by condition
    // -------------------------------------------------------

    std::cout << "\n=== std::partition ===\n";

    {
        std::vector<Position> positions = {
            {"AAPL",  500, 182.50},
            {"TSLA", -200, 245.00},
            {"MSFT", 1200, 420.00},   // over limit
            {"NVDA", -800, 800.00},
            {"AMZN",   50, 185.00},
        };

        constexpr int64_t LIMIT = 1000;

        // Partition: positions within limit come first, violations at end
        auto mid = std::stable_partition(positions.begin(), positions.end(),
            [](const Position& p) { return std::abs(p.net_qty) <= LIMIT; });

        std::cout << "Within limit:\n";
        for (auto it = positions.begin(); it != mid; ++it) {
            std::cout << "  " << it->symbol << " " << it->net_qty << "\n";
        }
        std::cout << "Violations (need reducing):\n";
        for (auto it = mid; it != positions.end(); ++it) {
            std::cout << "  " << it->symbol << " " << it->net_qty << " [BREACH]\n";
        }
    }

    // -------------------------------------------------------
    // BOOLEAN CHECKS — any_of, all_of, none_of
    // -------------------------------------------------------

    std::cout << "\n=== any_of / all_of / none_of ===\n";

    {
        std::vector<Position> positions = {
            {"AAPL",  500, 182.50},
            {"TSLA", -200, 245.00},
            {"MSFT",  800, 420.00},
        };

        constexpr int64_t MAX_QTY = 1000;

        bool any_violation = std::any_of(positions.begin(), positions.end(),
            [](const Position& p) { return std::abs(p.net_qty) > MAX_QTY; });
        std::cout << "Any position violation: " << any_violation << "\n";

        bool all_long = std::all_of(positions.begin(), positions.end(),
            [](const Position& p) { return p.net_qty > 0; });
        std::cout << "All positions are long: " << all_long << "\n";

        bool none_flat = std::none_of(positions.begin(), positions.end(),
            [](const Position& p) { return p.net_qty == 0; });
        std::cout << "None are flat: " << none_flat << "\n";

        // Count: how many positions are short?
        int short_count = static_cast<int>(std::count_if(positions.begin(), positions.end(),
            [](const Position& p) { return p.net_qty < 0; }));
        std::cout << "Short positions: " << short_count << "\n";
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Nightly risk report using STL algorithms — compute everything in one pass:

        auto& positions = risk_manager.positions();

        // 1. Total gross notional
        double gross = std::accumulate(positions.begin(), positions.end(), 0.0,
            [&prices](double sum, const Position& p) {
                return sum + std::abs(p.net_qty) * prices[p.symbol];
            });

        // 2. Number of losing positions
        int losers = std::count_if(positions.begin(), positions.end(),
            [](const Position& p) { return p.unrealized_pnl < 0; });

        // 3. Best and worst position by PnL
        auto [worst, best] = std::minmax_element(positions.begin(), positions.end(),
            [](const Position& a, const Position& b) {
                return a.unrealized_pnl < b.unrealized_pnl;
            });

        // 4. Sort for report
        std::sort(positions.begin(), positions.end(),
            [](const Position& a, const Position& b) {
                return a.unrealized_pnl > b.unrealized_pnl;
            });
    */
}
