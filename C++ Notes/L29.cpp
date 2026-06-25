// ============================================================
// L29: Iterators and Ranges (C++20)
// ============================================================
// WHAT: Iterators are the glue between containers and algorithms.
//       Ranges (C++20) provide a cleaner, composable pipeline
//       syntax for processing sequences of data.
// WHY (TRADING): Understanding iterators lets you write correct
//   STL algorithm calls and build your own high-performance
//   containers (ring buffers, pool allocators) that integrate
//   with STL. Ranges enable lazy, composable pipelines — filter
//   a position list, transform it to notional values, and take
//   the top 5 — all in one expression, with zero intermediate
//   containers allocated.
// PHASE: Modern C++
// ============================================================

/*
  CONCEPT OVERVIEW:

  ITERATOR CATEGORIES (from weakest to strongest):
    Input     — read once, forward only (std::istream_iterator)
    Forward   — read multiple times, forward only (std::forward_list)
    Bidirectional — forward and backward (std::list, std::map)
    Random Access — jump anywhere in O(1) (std::vector, std::array, raw array)
    Contiguous    — Random Access + guaranteed contiguous memory (std::vector)

  KEY ITERATOR OPERATIONS:
    *it       — dereference: get the element at this position
    ++it      — advance to next (prefix: more efficient)
    it++      — advance to next (postfix: returns old value, slight overhead)
    --it      — go backward (bidirectional+ only)
    it += n   — jump n positions (random access only)
    it1 - it2 — distance between iterators (random access only)
    it1 == it2— compare positions

  SENTINEL (end iterator):
    begin() points to the first element.
    end()   points ONE PAST the last element (never dereference this!).
    A range is valid when: begin() != end()

  INSERT ITERATORS (write to containers):
    std::back_inserter(vec)   — appends via push_back
    std::front_inserter(deq)  — prepends via push_front
    std::inserter(set, pos)   — inserts at position
    Used with: std::copy, std::transform to write into containers

  REVERSE ITERATORS:
    rbegin() — points to last element
    rend()   — points one before first element
    std::sort(v.rbegin(), v.rend())  — sorts in DESCENDING order

  RANGES (C++20):
    namespace std::ranges;
    std::ranges::sort(vec);                     — takes container directly (no begin/end)
    std::ranges::sort(vec, std::greater{});     — descending
    std::ranges::find_if(vec, pred);            — find first match
    std::views::filter(vec, pred);              — lazy filtered view (no copy)
    std::views::transform(vec, func);           — lazy transform view (no copy)
    std::views::take(vec, n);                   — first n elements
    std::views::drop(vec, n);                   — skip first n elements
    PIPE SYNTAX: vec | views::filter(pred) | views::transform(func) | views::take(5)

  WHY RANGES ARE POWERFUL:
    Traditional approach: multiple loops, multiple intermediate vectors (allocations)
    Ranges approach: compose views — lazy evaluation, ZERO intermediate allocations
    The entire pipeline processes one element at a time as you iterate.

  TRADING USE CASE:
    // Top 5 winning positions by PnL (lazy, no intermediate vector):
    auto top5 = positions
        | std::views::filter([](const Pos& p) { return p.pnl > 0; })
        | std::views::transform([](const Pos& p) -> double { return p.pnl; })
        | std::views::take(5);

    // Custom ring buffer iterator (enables range-for and STL algorithms)
    for (const auto& tick : ring_buffer) { ... }  // works with begin()/end()

  COMMON MISTAKES:
    - Dereferencing end() — undefined behavior (access violation)
    - Invalidated iterator: after vector resize, ALL iterators are invalid
    - Using input iterator multiple times (can only iterate once)
    - Forgetting that erase/insert on vector invalidates iterators at or after the point
*/

#include <iostream>
#include <vector>
#include <array>
#include <map>
#include <algorithm>
#include <numeric>
#include <iterator>     // std::back_inserter, std::reverse_iterator, etc.
#include <ranges>       // C++20 ranges and views
#include <string>
#include <cstdint>
#include <cmath>

// ============================================================
// TYPES
// ============================================================

struct Position {
    std::string symbol;
    int64_t     net_qty;
    double      avg_cost;
    double      pnl;
};

struct Tick {
    double   price;
    int32_t  qty;
    uint64_t seq;
};

// ============================================================
// CUSTOM ITERATOR — ring buffer with begin()/end()
// ============================================================
// By providing begin() and end(), this ring buffer works with
// range-for, std::sort, std::copy, and all other STL algorithms.

template<typename T, int N>
class IterableRingBuffer {
    static_assert((N & (N-1)) == 0, "N must be power of 2");
public:
    IterableRingBuffer() : head_(0), tail_(0), count_(0) {}

    void push(T item) {
        buf_[tail_ & (N-1)] = std::move(item);
        tail_++;
        if (count_ < N) ++count_;
        else             head_++;
    }

    int  size()  const { return count_; }
    bool empty() const { return count_ == 0; }

    // --- Iterator: forward iterator over ring buffer contents ---
    struct Iterator {
        const IterableRingBuffer* rb;
        int idx;    // logical index: 0 = oldest, count-1 = newest

        using iterator_category = std::forward_iterator_tag;
        using value_type        = T;
        using difference_type   = int;
        using pointer           = const T*;
        using reference         = const T&;

        reference operator*()  const { return rb->buf_[(rb->head_ + idx) & (N-1)]; }
        Iterator& operator++()       { ++idx; return *this; }
        bool operator!=(const Iterator& o) const { return idx != o.idx; }
        bool operator==(const Iterator& o) const { return idx == o.idx; }
    };

    Iterator begin() const { return Iterator{this, 0}; }
    Iterator end()   const { return Iterator{this, count_}; }

private:
    T   buf_[N];
    int head_, tail_, count_;
};

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // ITERATOR BASICS
    // -------------------------------------------------------

    std::cout << "=== Iterator basics ===\n";

    {
        std::vector<double> prices = {182.50, 182.55, 182.48, 182.60, 182.52};

        // Manual iteration with iterators
        std::cout << "Manual iteration:\n  ";
        for (auto it = prices.begin(); it != prices.end(); ++it) {
            std::cout << *it << " ";
        }
        std::cout << "\n";

        // Reverse iteration (highest to lowest, reading from end)
        std::cout << "Reverse:\n  ";
        for (auto it = prices.rbegin(); it != prices.rend(); ++it) {
            std::cout << *it << " ";
        }
        std::cout << "\n";

        // Iterator arithmetic (random access — works on vector)
        auto it     = prices.begin();
        auto second = it + 1;      // jump 1 position
        auto last   = prices.end() - 1;  // last valid element
        std::cout << "Second price: " << *second << "\n";
        std::cout << "Last price:   " << *last   << "\n";
        std::cout << "Distance first to last: " << (last - it) << "\n";
    }

    // -------------------------------------------------------
    // INSERT ITERATORS — write into containers
    // -------------------------------------------------------

    std::cout << "\n=== Insert iterators ===\n";

    {
        std::vector<double> source = {182.50, 182.55, 182.60};
        std::vector<double> dest;

        // back_inserter: calls push_back for each element written to it
        std::copy(source.begin(), source.end(), std::back_inserter(dest));
        std::cout << "Copied " << dest.size() << " elements via back_inserter\n";

        // transform + back_inserter: convert prices to ticks while copying
        std::vector<int64_t> ticks;
        std::transform(source.begin(), source.end(), std::back_inserter(ticks),
            [](double p) { return static_cast<int64_t>(p * 10000); });
        std::cout << "Ticks: ";
        for (int64_t t : ticks) std::cout << t << " ";
        std::cout << "\n";
    }

    // -------------------------------------------------------
    // ITERATOR INVALIDATION — the danger zone
    // -------------------------------------------------------

    std::cout << "\n=== Iterator invalidation warning ===\n";

    {
        std::vector<int> v = {1, 2, 3, 4, 5};

        auto it = v.begin() + 2;   // points to element 3
        std::cout << "Before push_back, *it = " << *it << "\n";

        // push_back may cause reallocation if capacity is exceeded
        // After reallocation, ALL iterators, pointers, and references are INVALID
        v.push_back(6);   // if this triggers realloc, it is now dangling!

        // Safe approach: use indices instead of iterators when modifying the container
        int saved_index = 2;
        v.push_back(7);
        std::cout << "Safe index access after push: " << v[saved_index] << "\n";

        // To avoid invalidation: reserve() before pushing
        std::vector<double> safe_prices;
        safe_prices.reserve(1000);   // no reallocation until 1000 elements
        auto safe_it = safe_prices.begin();  // valid as long as size < 1000
        (void)safe_it;
        std::cout << "Reserved vector: no reallocation until 1000 elements\n";
    }

    // -------------------------------------------------------
    // MAP ITERATORS — bidirectional, sorted traversal
    // -------------------------------------------------------

    std::cout << "\n=== Map iterators (order book) ===\n";

    {
        // Simulated order book ask side (sorted by price)
        std::map<int64_t, int32_t> asks;  // price_ticks → qty
        asks[1825000] = 100;
        asks[1825500] = 200;
        asks[1826000] = 300;
        asks[1826500] = 150;
        asks[1827000] =  50;

        // Forward: best ask first (lowest price)
        std::cout << "Asks (best first):\n";
        for (const auto& [price, qty] : asks) {
            std::cout << "  $" << price / 10000.0 << " x " << qty << "\n";
        }

        // Reverse: worst ask first
        std::cout << "Asks (worst first):\n";
        for (auto it = asks.rbegin(); it != asks.rend(); ++it) {
            std::cout << "  $" << it->first / 10000.0 << " x " << it->second << "\n";
        }

        // Sweep: buy up to limit price — use lower_bound to find cutoff
        int64_t limit = 1826000LL;
        auto cutoff = asks.upper_bound(limit);  // first element AFTER limit
        int32_t total_fillable = 0;
        for (auto it = asks.begin(); it != cutoff; ++it) {
            total_fillable += it->second;
        }
        std::cout << "Fillable qty at/below $" << limit / 10000.0 << ": " << total_fillable << "\n";
    }

    // -------------------------------------------------------
    // CUSTOM RING BUFFER ITERATOR
    // -------------------------------------------------------

    std::cout << "\n=== Custom ring buffer with STL-compatible iterator ===\n";

    {
        IterableRingBuffer<Tick, 8> rb;

        for (int i = 0; i < 10; ++i) {   // push 10 into a buffer of 8 (wraps around)
            rb.push({182.50 + i * 0.01, 100, static_cast<uint64_t>(i)});
        }
        std::cout << "Buffer size (last 8 of 10 pushes): " << rb.size() << "\n";

        // Range-for works because we defined begin() and end()
        std::cout << "Contents (oldest to newest):\n";
        for (const auto& tick : rb) {
            std::cout << "  seq=" << tick.seq << " $" << tick.price << "\n";
        }

        // STL algorithms work too
        auto max_tick = std::max_element(rb.begin(), rb.end(),
            [](const Tick& a, const Tick& b) { return a.price < b.price; });
        std::cout << "Max price in buffer: $" << max_tick->price << "\n";

        double sum = std::accumulate(rb.begin(), rb.end(), 0.0,
            [](double acc, const Tick& t) { return acc + t.price; });
        std::cout << "Average price: $" << sum / rb.size() << "\n";
    }

    // -------------------------------------------------------
    // C++20 RANGES — composable lazy pipelines
    // -------------------------------------------------------

    std::cout << "\n=== C++20 Ranges ===\n";

    {
        std::vector<Position> positions = {
            {"AAPL",   500, 182.50,  1250.0},
            {"TSLA",  -200, 245.00,  -400.0},
            {"MSFT",   800, 420.00,  3200.0},
            {"NVDA",  -100, 800.00,  -300.0},
            {"AMZN",   300, 185.00,   600.0},
            {"GOOG",   150, 175.00,   225.0},
        };

        // std::ranges::sort — takes container directly (no begin/end)
        std::ranges::sort(positions, std::greater{},
            &Position::pnl);   // sort by pnl field descending
        std::cout << "Positions sorted by PnL (desc):\n";
        for (const auto& p : positions) {
            std::cout << "  " << p.symbol << ": $" << p.pnl << "\n";
        }

        // PIPE SYNTAX: filter → transform → take (lazy, zero intermediate containers)
        std::cout << "\nTop 3 winning positions (pnl > 0):\n";
        auto top_winners = positions
            | std::views::filter([](const Position& p) { return p.pnl > 0.0; })
            | std::views::take(3);  // lazy: only computes what we iterate

        for (const auto& p : top_winners) {
            std::cout << "  " << p.symbol << ": $" << p.pnl << "\n";
        }

        // Transform to notional values (lazy)
        auto notionals = positions
            | std::views::transform([](const Position& p) {
                return std::abs(p.net_qty) * p.avg_cost;
            });

        std::cout << "\nNotional values:\n";
        for (auto [pos, notional] : std::views::zip(positions, notionals)) {
            std::cout << "  " << pos.symbol << ": $" << notional << "\n";
        }

        // iota view: generate a sequence without allocating a vector
        std::cout << "\nOrder IDs 1001-1005 (iota view, no allocation):\n  ";
        for (int id : std::views::iota(1001, 1006)) {
            std::cout << id << " ";
        }
        std::cout << "\n";
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Lazy pipeline for real-time risk reporting — no intermediate containers:

        // Every tick: update position PnL, then run risk scan
        // The filter+transform pipeline processes one element at a time
        // and never allocates a separate output container.

        auto risk_violations = live_positions
            | std::views::filter([](const Position& p) {
                return std::abs(p.net_qty) > MAX_POSITION ||
                       p.pnl < -MAX_LOSS;
            })
            | std::views::transform([](const Position& p) {
                return RiskAlert{p.symbol, p.net_qty, p.pnl};
            });

        for (const auto& alert : risk_violations) {
            risk_log.write(alert);
            if (alert.is_critical()) kill_switch.activate();
        }

        // This scans positions, filters violations, and reports —
        // all in a single O(n) pass with ZERO heap allocations.
    */
}
