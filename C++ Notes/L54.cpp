// ============================================================
// L54: Order Book Implementation
// ============================================================
// WHAT: A limit order book (LOB) — the central data structure of
//       every exchange and trading system. Maintains sorted lists
//       of buy orders (bids, highest price first) and sell orders
//       (asks, lowest price first). Provides best bid/ask (BBO),
//       mid price, spread, and depth queries.
// WHY (TRADING): The order book IS the market. Every strategy
//   reads from the book: what is the best bid? best ask? how deep
//   is the book at this price? Every order you send updates the book.
//   Understanding book state is the core of market making, stat arb,
//   momentum strategies, and execution algorithms.
// PHASE: Trading Systems Implementation
// ============================================================

/*
  CONCEPT OVERVIEW:

  PRICE-TIME PRIORITY (FIFO):
    Most equity exchanges use price-time priority:
    1. Orders at better prices fill first (price priority)
    2. Among orders at the same price, earlier orders fill first (time priority)

    Bids:  descending price → highest bid has first priority
    Asks:  ascending price  → lowest ask has first priority

  DATA STRUCTURE CHOICES:
    std::map<int64_t, Level, Compare>:
      + O(log N) insert/delete/lookup
      + Always sorted
      + Simple iterator-based depth queries
      - Not cache-friendly (tree nodes scattered in memory)
      - ~100ns per operation (red-black tree traversal)
    Intrusive skip list or sorted array:
      + Cache-friendly for linear scan
      - More complex to implement correctly
    We use std::map here for clarity. Production systems often use
    a custom sorted array or B-tree for better cache behavior.

  TICK SIZE:
    All prices in ticks (int64_t). Different instruments have different
    minimum price increments (tick sizes). The book doesn't need to know
    the tick size — it works in ticks throughout.

  AGGREGATED LEVEL vs PER-ORDER:
    Two common designs:
    1. Aggregated: Level{price, total_qty, num_orders} — simpler, less memory
    2. Per-order: each order as a separate entry with time ordering
    We implement aggregated levels (design 1). For a matching engine
    with FIFO fills, you need design 2 (see L55).

  TOP OF BOOK (BBO = Best Bid/Offer):
    best_bid  = bids.begin()->first   (largest price in descending map)
    best_ask  = asks.begin()->first   (smallest price in ascending map)
    mid       = (best_bid + best_ask) / 2
    spread    = best_ask - best_bid   (in ticks)

  COMMON MISTAKES:
    - Using floating-point prices in the map key (hash collisions, equality issues)
    - std::map<double, Level> — two prices that should be equal may differ by 1e-15
    - Not checking for crossed book (best_bid >= best_ask = bug)
    - Erasing a level from the map when qty drops to 0 — must do this or
      the book accumulates ghost levels
    - Thread safety: the book is NOT thread-safe. Wrap all access in a mutex or
      ensure only one thread writes to it.
*/

#include <iostream>
#include <map>
#include <functional>  // std::greater
#include <optional>
#include <cstdint>
#include <cassert>
#include <string>
#include <vector>
#include <chrono>
#include <iomanip>

// ============================================================
// PRICE ENCODING (reuse from L53)
// ============================================================

constexpr int64_t PRICE_MULT = 10000;

constexpr int64_t to_ticks(double p)   { return static_cast<int64_t>(p * PRICE_MULT + 0.5); }
constexpr double  to_price(int64_t t)  { return static_cast<double>(t) / PRICE_MULT; }

// ============================================================
// AGGREGATED PRICE LEVEL
// ============================================================

struct Level {
    int64_t price;      // price in ticks
    int32_t qty;        // total quantity at this price level
    int32_t num_orders; // number of open orders at this level

    // For display
    std::string to_string() const {
        return "$" + std::to_string(to_price(price)) +
               " x " + std::to_string(qty) +
               " (" + std::to_string(num_orders) + " orders)";
    }
};

// ============================================================
// ORDER BOOK
// ============================================================

class OrderBook {
public:
    // Bids: descending price (highest bid first)
    using BidMap = std::map<int64_t, Level, std::greater<int64_t>>;
    // Asks: ascending price (lowest ask first)
    using AskMap = std::map<int64_t, Level, std::less<int64_t>>;

    explicit OrderBook(const std::string& symbol) : symbol_(symbol) {}

    // ── Mutators ─────────────────────────────────────────

    // Add or increase quantity at a price level (bid side)
    void add_bid(int64_t price, int32_t qty, int32_t num_orders = 1) {
        auto& lvl       = bids_[price];
        lvl.price      = price;
        lvl.qty        += qty;
        lvl.num_orders += num_orders;
        ++update_count_;
    }

    // Add or increase quantity at a price level (ask side)
    void add_ask(int64_t price, int32_t qty, int32_t num_orders = 1) {
        auto& lvl       = asks_[price];
        lvl.price      = price;
        lvl.qty        += qty;
        lvl.num_orders += num_orders;
        ++update_count_;
    }

    // Remove quantity from a bid level. Erases the level if qty reaches 0.
    void reduce_bid(int64_t price, int32_t qty, int32_t num_orders = 1) {
        auto it = bids_.find(price);
        if (it == bids_.end()) return;  // level doesn't exist — stale update
        it->second.qty        -= qty;
        it->second.num_orders -= num_orders;
        if (it->second.qty <= 0) bids_.erase(it);  // remove ghost levels
        ++update_count_;
    }

    // Remove quantity from an ask level. Erases the level if qty reaches 0.
    void reduce_ask(int64_t price, int32_t qty, int32_t num_orders = 1) {
        auto it = asks_.find(price);
        if (it == asks_.end()) return;
        it->second.qty        -= qty;
        it->second.num_orders -= num_orders;
        if (it->second.qty <= 0) asks_.erase(it);
        ++update_count_;
    }

    // Replace an entire level (used by snapshot-based feeds like CME MDP3)
    void set_bid_level(int64_t price, int32_t qty, int32_t num_orders) {
        if (qty <= 0) { bids_.erase(price); return; }
        bids_[price] = Level{price, qty, num_orders};
        ++update_count_;
    }

    void set_ask_level(int64_t price, int32_t qty, int32_t num_orders) {
        if (qty <= 0) { asks_.erase(price); return; }
        asks_[price] = Level{price, qty, num_orders};
        ++update_count_;
    }

    // Clear the entire book (e.g., on reconnect or symbol halt)
    void clear() {
        bids_.clear();
        asks_.clear();
        ++update_count_;
    }

    // ── Accessors ────────────────────────────────────────

    bool has_bids() const { return !bids_.empty(); }
    bool has_asks() const { return !asks_.empty(); }
    bool has_both() const { return has_bids() && has_asks(); }

    // Best bid price (highest bid). Returns nullopt if no bids.
    std::optional<int64_t> best_bid() const {
        if (bids_.empty()) return std::nullopt;
        return bids_.begin()->first;
    }

    // Best ask price (lowest ask). Returns nullopt if no asks.
    std::optional<int64_t> best_ask() const {
        if (asks_.empty()) return std::nullopt;
        return asks_.begin()->first;
    }

    // Best bid level (price + qty + num_orders)
    std::optional<Level> best_bid_level() const {
        if (bids_.empty()) return std::nullopt;
        return bids_.begin()->second;
    }

    std::optional<Level> best_ask_level() const {
        if (asks_.empty()) return std::nullopt;
        return asks_.begin()->second;
    }

    // Mid price in ticks (integer arithmetic — truncates toward zero)
    std::optional<int64_t> mid_price() const {
        auto bb = best_bid();
        auto ba = best_ask();
        if (!bb || !ba) return std::nullopt;
        return (*bb + *ba) / 2;
    }

    // Spread in ticks (best_ask - best_bid). Positive when book is uncrossed.
    std::optional<int64_t> spread() const {
        auto bb = best_bid();
        auto ba = best_ask();
        if (!bb || !ba) return std::nullopt;
        return *ba - *bb;
    }

    // True if best_ask <= best_bid — indicates data error or locked market
    bool is_crossed() const {
        auto bb = best_bid();
        auto ba = best_ask();
        if (!bb || !ba) return false;
        return *ba <= *bb;
    }

    // Total quantity available from asks at or below 'max_price' ticks
    int32_t ask_depth_at_or_below(int64_t max_price) const {
        int32_t total = 0;
        for (auto it = asks_.begin(); it != asks_.end() && it->first <= max_price; ++it)
            total += it->second.qty;
        return total;
    }

    // Total quantity available from bids at or above 'min_price' ticks
    int32_t bid_depth_at_or_above(int64_t min_price) const {
        int32_t total = 0;
        for (auto it = bids_.begin(); it != bids_.end() && it->first >= min_price; ++it)
            total += it->second.qty;
        return total;
    }

    // Estimated fill price for buying 'qty' shares (sweeps the ask side)
    // Returns: VWAP of the sweep in ticks, or nullopt if not enough liquidity
    std::optional<int64_t> estimate_buy_vwap(int32_t qty) const {
        int64_t total_value = 0;
        int32_t remaining   = qty;
        for (auto& [price, lvl] : asks_) {
            int32_t take = std::min(remaining, lvl.qty);
            total_value += static_cast<int64_t>(take) * price;
            remaining   -= take;
            if (remaining == 0) break;
        }
        if (remaining > 0) return std::nullopt;  // not enough liquidity
        return total_value / qty;
    }

    // Estimated fill price for selling 'qty' shares (sweeps the bid side)
    std::optional<int64_t> estimate_sell_vwap(int32_t qty) const {
        int64_t total_value = 0;
        int32_t remaining   = qty;
        for (auto& [price, lvl] : bids_) {
            int32_t take = std::min(remaining, lvl.qty);
            total_value += static_cast<int64_t>(take) * price;
            remaining   -= take;
            if (remaining == 0) break;
        }
        if (remaining > 0) return std::nullopt;
        return total_value / qty;
    }

    // Bid-ask imbalance: (bid_qty - ask_qty) / (bid_qty + ask_qty), scaled 0-100
    // Positive = more bid pressure (bullish), Negative = more ask pressure (bearish)
    // Uses top N levels only
    int32_t bbo_imbalance(int n_levels = 5) const {
        int64_t bid_qty = 0, ask_qty = 0;
        int i = 0;
        for (auto& [p, l] : bids_) { bid_qty += l.qty; if (++i >= n_levels) break; }
        i = 0;
        for (auto& [p, l] : asks_) { ask_qty += l.qty; if (++i >= n_levels) break; }
        int64_t total = bid_qty + ask_qty;
        if (total == 0) return 0;
        return static_cast<int32_t>((bid_qty - ask_qty) * 100 / total);
    }

    // Number of levels on each side
    int bid_levels() const { return static_cast<int>(bids_.size()); }
    int ask_levels() const { return static_cast<int>(asks_.size()); }

    uint64_t update_count() const { return update_count_; }
    const std::string& symbol() const { return symbol_; }

    // Raw access for matching engine
    BidMap& bids() { return bids_; }
    AskMap& asks() { return asks_; }
    const BidMap& bids() const { return bids_; }
    const AskMap& asks() const { return asks_; }

    // ── Display ──────────────────────────────────────────

    void print(int depth = 5) const {
        std::cout << "\n  ─── Order Book: " << symbol_ << " ───\n";

        // Print asks (reversed: worst ask first, best ask last at the top)
        std::vector<std::pair<int64_t, Level>> ask_vec(asks_.begin(), asks_.end());
        int show_asks = std::min((int)ask_vec.size(), depth);
        for (int i = show_asks - 1; i >= 0; --i) {
            const auto& [price, lvl] = ask_vec[i];
            std::cout << "  ASK  " << std::setw(10) << to_price(price)
                      << "  " << std::setw(8) << lvl.qty
                      << "  (" << lvl.num_orders << " orders)\n";
        }

        // Spread line
        auto sp = spread();
        if (sp) std::cout << "  ─────  spread: " << *sp << " ticks  ─────\n";

        // Print bids
        int shown_bids = 0;
        for (auto& [price, lvl] : bids_) {
            std::cout << "  BID  " << std::setw(10) << to_price(price)
                      << "  " << std::setw(8) << lvl.qty
                      << "  (" << lvl.num_orders << " orders)\n";
            if (++shown_bids >= depth) break;
        }
        std::cout << "  (updates: " << update_count_ << ")\n";
    }

private:
    std::string symbol_;
    BidMap      bids_;
    AskMap      asks_;
    uint64_t    update_count_ = 0;
};

// ============================================================
// MAIN
// ============================================================

int main() {
    // -------------------------------------------------------
    // BUILD A SAMPLE ORDER BOOK (SPY)
    // -------------------------------------------------------

    OrderBook book("SPY");

    std::cout << "=== Building SPY order book ===\n";

    // Add ask levels (ascending: best ask = lowest price)
    book.add_ask(to_ticks(182.75), 500,  3);
    book.add_ask(to_ticks(182.76), 1200, 8);
    book.add_ask(to_ticks(182.77), 800,  5);
    book.add_ask(to_ticks(182.78), 2000, 12);
    book.add_ask(to_ticks(182.80), 3000, 20);

    // Add bid levels (descending: best bid = highest price)
    book.add_bid(to_ticks(182.74), 600,  4);
    book.add_bid(to_ticks(182.73), 1500, 10);
    book.add_bid(to_ticks(182.72), 900,  6);
    book.add_bid(to_ticks(182.71), 2500, 15);
    book.add_bid(to_ticks(182.70), 4000, 25);

    book.print(5);

    // -------------------------------------------------------
    // BBO QUERIES
    // -------------------------------------------------------

    std::cout << "\n=== BBO Queries ===\n";

    if (auto bb = book.best_bid()) std::cout << "  Best bid: $" << to_price(*bb) << "\n";
    if (auto ba = book.best_ask()) std::cout << "  Best ask: $" << to_price(*ba) << "\n";
    if (auto mid = book.mid_price()) std::cout << "  Mid:      $" << to_price(*mid) << "\n";
    if (auto sp  = book.spread())    std::cout << "  Spread:   " << *sp << " ticks\n";

    std::cout << "  Crossed: " << (book.is_crossed() ? "YES" : "NO") << "\n";
    std::cout << "  Bid levels: " << book.bid_levels() << "\n";
    std::cout << "  Ask levels: " << book.ask_levels() << "\n";

    // -------------------------------------------------------
    // DEPTH AND LIQUIDITY QUERIES
    // -------------------------------------------------------

    std::cout << "\n=== Depth and Liquidity ===\n";

    int64_t max_ask_price = to_ticks(182.76);  // willing to pay up to $182.76
    std::cout << "  Ask qty at or below $182.76: "
              << book.ask_depth_at_or_below(max_ask_price) << " shares\n";

    if (auto vwap = book.estimate_buy_vwap(1000))
        std::cout << "  Estimated VWAP to buy 1000 shares: $" << to_price(*vwap) << "\n";

    if (auto vwap = book.estimate_sell_vwap(2000))
        std::cout << "  Estimated VWAP to sell 2000 shares: $" << to_price(*vwap) << "\n";

    std::cout << "  BBO imbalance (top 5 levels): "
              << book.bbo_imbalance(5) << "/100\n";
    std::cout << "  (positive = more bids = bullish pressure)\n";

    // -------------------------------------------------------
    // SIMULATE MARKET DATA UPDATES (like ITCH messages)
    // -------------------------------------------------------

    std::cout << "\n=== Simulated market data updates ===\n";

    // New order added at ask $182.75 (more selling pressure)
    book.add_ask(to_ticks(182.75), 200, 1);
    std::cout << "  +200 ask @ $182.75 (new order arrived)\n";

    // 300 shares executed at bid $182.74 (buyer got filled)
    book.reduce_bid(to_ticks(182.74), 300, 1);
    std::cout << "  -300 bid @ $182.74 (execution)\n";

    // Entire ask level at $182.75 swept by a large buy
    book.reduce_ask(to_ticks(182.75), 700, 4);  // wipes out 500+200=700
    std::cout << "  -700 ask @ $182.75 (level wiped)\n";

    book.print(3);

    // -------------------------------------------------------
    // PERFORMANCE BENCHMARK
    // -------------------------------------------------------

    std::cout << "\n=== Performance: 1M order book updates ===\n";

    OrderBook bench_book("BENCH");

    // Pre-populate 10 levels each side
    for (int i = 0; i < 10; ++i) {
        bench_book.add_bid(to_ticks(100.00 - i * 0.01), 1000, 5);
        bench_book.add_ask(to_ticks(100.01 + i * 0.01), 1000, 5);
    }

    constexpr int BENCH_OPS = 1000000;
    auto t0 = std::chrono::steady_clock::now();

    for (int i = 0; i < BENCH_OPS; ++i) {
        int64_t price = to_ticks(100.00 - (i % 10) * 0.01);
        // Alternate add/reduce to simulate real updates
        if (i % 2 == 0)
            bench_book.add_bid(price, 10, 1);
        else
            bench_book.reduce_bid(price, 10, 1);
    }

    auto t1 = std::chrono::steady_clock::now();
    uint64_t ns = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());

    std::cout << "  " << BENCH_OPS << " updates in " << ns / 1000 << "µs\n";
    std::cout << "  Per update: " << ns / BENCH_OPS << "ns\n";
    std::cout << "  (std::map: O(log N) per operation, ~100-200ns each)\n";
    std::cout << "  Production: use intrusive skip list or sorted array for <50ns\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      A market-making strategy maintains one OrderBook per instrument.
      On each tick from the feed handler (L58):
        1. Parse ITCH message (L57)
        2. Call book.add_bid() / book.reduce_ask() / etc.
        3. Query book.best_bid(), best_ask(), spread(), bbo_imbalance()
        4. If spread > threshold and imbalance signals direction:
             Submit a limit order (L53) on the favorable side
        5. Risk check (L59): is new position within limits?
        6. If yes: send order via FIX gateway (L56)

      The order book update loop must complete in <1µs.
      With std::map: ~100ns per level update × 10 levels = ~1µs (tight).
      With a hand-rolled sorted array: ~10-20ns per update = comfortable.
    */
}
