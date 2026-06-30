// ============================================================
// L60: Position and PnL Tracking
// ============================================================
// WHAT: Tracks the current position (long/short shares) for each
//       symbol and computes both realized and unrealized PnL.
//       Realized PnL: from closed trades (locked in).
//       Unrealized PnL: from open positions marked to market.
//       Supports FIFO and average-cost methods.
// WHY (TRADING): You must know at every moment what you own and
//   what it's worth. PnL tracking feeds into the risk system (L59)
//   for daily loss limits and is the source of truth for the
//   end-of-day reconciliation. Errors here mean either taking
//   more risk than intended, or missing profitable opportunities.
// PHASE: Trading Systems Implementation
// ============================================================

/*
  CONCEPT OVERVIEW:

  POSITION:
    net_position = sum(buy_qty) - sum(sell_qty) for a symbol
    Positive = long (bought more than sold)
    Negative = short (sold more than bought, often via borrow)

  REALIZED PnL (closed profit/loss):
    When you BUY and then SELL the same shares:
      P&L = (sell_price - buy_price) × qty
    Accumulated as positions are reduced.

  UNREALIZED PnL (mark-to-market):
    On open positions:
      unrealized_pnl = (current_market_price - avg_cost) × net_position
    This changes every tick as the market price moves.

  AVERAGE COST METHOD:
    When adding to an existing long position:
      new_avg_cost = (old_position × old_avg_cost + new_qty × fill_price)
                   / (old_position + new_qty)
    When reducing:
      realized_pnl += (fill_price - avg_cost) × qty_reduced
      position -= qty_reduced  (avg_cost stays the same until reversed)

  FIFO METHOD:
    Treats each buy as a separate lot with its own cost basis.
    Sells consume the earliest lots first (first in, first out).
    More complex than average cost, but required for tax purposes.
    We implement both: average cost for speed, FIFO for reconciliation.

  TOTAL PnL:
    total_pnl = realized_pnl + unrealized_pnl

  MARK-TO-MARKET:
    At any point: call mark_to_market(symbol, current_price) to
    update unrealized_pnl. Should be called on every tick.

  COMMON MISTAKES:
    - Forgetting to update avg_cost when adding to a position
    - Computing unrealized PnL on the wrong side (e.g., using bid for a long
      position when you should use bid for realistic exit value)
    - Integer overflow: position × price can overflow int32_t × int32_t = int64_t
      Always use int64_t for PnL computations.
    - Not handling short positions correctly: avg_cost for a short is the
      price you SOLD at; PnL on a short is (avg_cost - current_price) × abs(position)
*/

#include <iostream>
#include <unordered_map>
#include <string>
#include <deque>
#include <cstdint>
#include <cassert>
#include <optional>
#include <iomanip>
#include <chrono>
#include <numeric>

constexpr int64_t PRICE_MULT = 10000;
constexpr int64_t to_ticks(double p) { return static_cast<int64_t>(p * PRICE_MULT + 0.5); }
constexpr double  to_price(int64_t t){ return static_cast<double>(t)  / PRICE_MULT; }

enum class Side : uint8_t { BUY = 0, SELL = 1 };

// ============================================================
// FIFO LOT — one purchase lot for FIFO cost basis
// ============================================================

struct Lot {
    int64_t buy_price;  // price paid, in ticks
    int32_t qty;        // remaining shares in this lot
};

// ============================================================
// SYMBOL POSITION — tracks position and PnL for one instrument
// ============================================================

class SymbolPosition {
public:
    explicit SymbolPosition(const std::string& sym) : symbol_(sym) {}

    // ── APPLY A FILL ─────────────────────────────────────────

    void on_fill(Side side, int32_t qty, int64_t fill_price) {
        assert(qty > 0);

        if (side == Side::BUY) {
            apply_buy(qty, fill_price);
        } else {
            apply_sell(qty, fill_price);
        }

        // Track VWAP of all fills for this session
        total_fill_value_ += static_cast<int64_t>(qty) * fill_price;
        total_fill_qty_   += qty;
    }

    // ── MARK TO MARKET ───────────────────────────────────────

    // Update unrealized PnL based on current market price.
    // Call on every tick for accurate mark-to-market.
    void mark(int64_t current_price) {
        last_mark_price_ = current_price;

        if (net_position_ == 0) {
            unrealized_pnl_ = 0;
            return;
        }

        if (net_position_ > 0) {
            // Long: unrealized = (current - avg_cost) × position
            unrealized_pnl_ = (current_price - avg_cost_) * net_position_;
        } else {
            // Short: unrealized = (avg_cost - current) × |position|
            unrealized_pnl_ = (avg_cost_ - current_price) * (-net_position_);
        }
    }

    // ── QUERIES ─────────────────────────────────────────────

    int32_t net_position()     const { return net_position_; }
    int64_t avg_cost()         const { return avg_cost_; }
    int64_t realized_pnl()     const { return realized_pnl_; }
    int64_t unrealized_pnl()   const { return unrealized_pnl_; }
    int64_t total_pnl()        const { return realized_pnl_ + unrealized_pnl_; }
    int64_t last_mark_price()  const { return last_mark_price_; }
    int32_t total_bought()     const { return total_bought_; }
    int32_t total_sold()       const { return total_sold_; }
    int64_t session_vwap()     const {
        return (total_fill_qty_ > 0) ? total_fill_value_ / total_fill_qty_ : 0;
    }

    const std::string& symbol() const { return symbol_; }

    void print() const {
        std::cout << "  [" << symbol_ << "]\n";
        std::cout << "    Net position:   " << net_position_ << " shares\n";
        std::cout << "    Avg cost:       $" << to_price(avg_cost_) << "\n";
        std::cout << "    Last mark:      $" << to_price(last_mark_price_) << "\n";
        std::cout << "    Realized PnL:   $" << to_price(realized_pnl_) << "\n";
        std::cout << "    Unrealized PnL: $" << to_price(unrealized_pnl_) << "\n";
        std::cout << "    Total PnL:      $" << to_price(total_pnl()) << "\n";
        std::cout << "    Session VWAP:   $" << to_price(session_vwap()) << "\n";
        std::cout << "    Total bought:   " << total_bought_ << "\n";
        std::cout << "    Total sold:     " << total_sold_   << "\n";
    }

private:
    std::string symbol_;
    int32_t     net_position_   = 0;
    int64_t     avg_cost_       = 0;   // weighted average cost basis (ticks)
    int64_t     realized_pnl_   = 0;   // locked-in profit/loss (ticks × qty, not per share)
    int64_t     unrealized_pnl_ = 0;   // mark-to-market (ticks × qty)
    int64_t     last_mark_price_= 0;

    int32_t     total_bought_   = 0;
    int32_t     total_sold_     = 0;
    int64_t     total_fill_value_= 0;
    int32_t     total_fill_qty_ = 0;

    // FIFO lots for detailed cost basis tracking
    std::deque<Lot> lots_;

    void apply_buy(int32_t qty, int64_t fill_price) {
        total_bought_ += qty;

        if (net_position_ >= 0) {
            // Adding to a long or opening a new long
            int64_t existing_value = avg_cost_ * net_position_;
            int64_t new_value      = fill_price * qty;
            net_position_         += qty;
            avg_cost_              = net_position_ > 0 ?
                (existing_value + new_value) / net_position_ : 0;

            // FIFO: add a new lot
            lots_.push_back({fill_price, qty});

        } else {
            // Covering a short position
            // Realized PnL on covered shares: (entry_short_price - fill_price) × covered_qty
            int32_t cover_qty = std::min(qty, -net_position_);
            realized_pnl_    += (avg_cost_ - fill_price) * cover_qty;  // avg_cost = short entry
            net_position_    += cover_qty;

            int32_t leftover  = qty - cover_qty;
            if (leftover > 0) {
                // Remaining qty opens a new long
                avg_cost_     = fill_price;
                net_position_ = leftover;
                lots_.push_back({fill_price, leftover});
            }
        }
    }

    void apply_sell(int32_t qty, int64_t fill_price) {
        total_sold_ += qty;

        if (net_position_ > 0) {
            // Selling out of a long position
            int32_t close_qty  = std::min(qty, net_position_);
            realized_pnl_     += (fill_price - avg_cost_) * close_qty;
            net_position_     -= close_qty;
            if (net_position_ == 0) avg_cost_ = 0;

            // FIFO lot reduction (for detailed tracking)
            int32_t to_remove = close_qty;
            while (to_remove > 0 && !lots_.empty()) {
                Lot& lot = lots_.front();
                if (lot.qty <= to_remove) {
                    to_remove -= lot.qty;
                    lots_.pop_front();
                } else {
                    lot.qty   -= to_remove;
                    to_remove  = 0;
                }
            }

            int32_t leftover = qty - close_qty;
            if (leftover > 0) {
                // Now going short
                avg_cost_     = fill_price;  // short entry price
                net_position_ = -leftover;
            }
        } else {
            // Adding to a short or opening a new short
            int64_t existing_value = avg_cost_ * (-net_position_);
            int64_t new_value      = fill_price * qty;
            net_position_         -= qty;
            avg_cost_              = net_position_ < 0 ?
                (existing_value + new_value) / (-net_position_) : 0;
        }
    }
};

// ============================================================
// PORTFOLIO — tracks all symbols
// ============================================================

class Portfolio {
public:
    // Process a fill for a symbol
    void on_fill(const std::string& sym, Side side, int32_t qty, int64_t fill_price) {
        get_or_create(sym).on_fill(side, qty, fill_price);
    }

    // Mark all positions to current prices
    void mark(const std::string& sym, int64_t price) {
        auto it = positions_.find(sym);
        if (it != positions_.end()) it->second.mark(price);
    }

    // Mark all positions using a price map
    void mark_all(const std::unordered_map<std::string, int64_t>& prices) {
        for (auto& [sym, pos] : positions_) {
            auto it = prices.find(sym);
            if (it != prices.end()) pos.mark(it->second);
        }
    }

    // Aggregate PnL across all symbols
    int64_t total_realized_pnl() const {
        int64_t total = 0;
        for (auto& [sym, pos] : positions_) total += pos.realized_pnl();
        return total;
    }

    int64_t total_unrealized_pnl() const {
        int64_t total = 0;
        for (auto& [sym, pos] : positions_) total += pos.unrealized_pnl();
        return total;
    }

    int64_t total_pnl() const {
        return total_realized_pnl() + total_unrealized_pnl();
    }

    // Gross notional exposure (sum of |position × price|)
    int64_t gross_exposure() const {
        int64_t total = 0;
        for (auto& [sym, pos] : positions_) {
            if (pos.last_mark_price() > 0)
                total += std::abs(pos.net_position()) * pos.last_mark_price();
        }
        return total;
    }

    const SymbolPosition* get(const std::string& sym) const {
        auto it = positions_.find(sym);
        return (it != positions_.end()) ? &it->second : nullptr;
    }

    void print_all() const {
        std::cout << "\n  === Portfolio ===\n";
        for (auto& [sym, pos] : positions_) pos.print();
        std::cout << "  ─────────────────────────────\n";
        std::cout << "  Total realized:   $" << to_price(total_realized_pnl()) << "\n";
        std::cout << "  Total unrealized: $" << to_price(total_unrealized_pnl()) << "\n";
        std::cout << "  Total PnL:        $" << to_price(total_pnl()) << "\n";
        std::cout << "  Gross exposure:   $" << to_price(gross_exposure()) << "\n";
    }

private:
    std::unordered_map<std::string, SymbolPosition> positions_;

    SymbolPosition& get_or_create(const std::string& sym) {
        auto it = positions_.find(sym);
        if (it != positions_.end()) return it->second;
        positions_.emplace(sym, SymbolPosition(sym));
        return positions_.at(sym);
    }
};

// ============================================================
// MAIN
// ============================================================

int main() {
    std::cout << "=== Position and PnL Tracker ===\n";

    Portfolio portfolio;

    // -------------------------------------------------------
    // SCENARIO 1: Buy, price rises, sell for profit
    // -------------------------------------------------------

    std::cout << "\n--- Scenario 1: SPY long trade ---\n";

    portfolio.on_fill("SPY", Side::BUY,  200, to_ticks(182.50));
    std::cout << "  Bought 200 SPY @ $182.50\n";

    portfolio.on_fill("SPY", Side::BUY,  100, to_ticks(182.60));
    std::cout << "  Bought 100 SPY @ $182.60 (adds to position)\n";

    if (auto* p = portfolio.get("SPY"))
        std::cout << "  Position: " << p->net_position()
                  << " | Avg cost: $" << to_price(p->avg_cost()) << "\n";

    // Mark to market at $183.00
    portfolio.mark("SPY", to_ticks(183.00));
    if (auto* p = portfolio.get("SPY"))
        std::cout << "  MTM @ $183.00 → Unrealized: $" << to_price(p->unrealized_pnl()) << "\n";

    // Sell half
    portfolio.on_fill("SPY", Side::SELL, 150, to_ticks(183.00));
    std::cout << "  Sold 150 SPY @ $183.00\n";

    // Sell remaining
    portfolio.on_fill("SPY", Side::SELL, 150, to_ticks(183.10));
    std::cout << "  Sold 150 SPY @ $183.10\n";

    portfolio.get("SPY")->print();

    // -------------------------------------------------------
    // SCENARIO 2: Short trade
    // -------------------------------------------------------

    std::cout << "\n--- Scenario 2: AAPL short trade ---\n";

    portfolio.on_fill("AAPL", Side::SELL, 100, to_ticks(175.00));
    std::cout << "  Sold short 100 AAPL @ $175.00\n";

    portfolio.mark("AAPL", to_ticks(173.00));  // price dropped — profit for short
    if (auto* p = portfolio.get("AAPL"))
        std::cout << "  MTM @ $173.00 → Unrealized: $" << to_price(p->unrealized_pnl())
                  << " (should be positive — short in profit)\n";

    portfolio.on_fill("AAPL", Side::BUY, 100, to_ticks(173.50));
    std::cout << "  Covered 100 AAPL @ $173.50\n";

    portfolio.get("AAPL")->print();

    // -------------------------------------------------------
    // SCENARIO 3: Partial fill sequence
    // -------------------------------------------------------

    std::cout << "\n--- Scenario 3: QQQ partial fills ---\n";

    portfolio.on_fill("QQQ", Side::BUY, 50, to_ticks(350.00));
    portfolio.on_fill("QQQ", Side::BUY, 30, to_ticks(350.10));
    portfolio.on_fill("QQQ", Side::BUY, 20, to_ticks(350.20));
    portfolio.mark("QQQ", to_ticks(350.50));

    portfolio.get("QQQ")->print();

    // -------------------------------------------------------
    // PORTFOLIO SUMMARY
    // -------------------------------------------------------

    portfolio.mark_all({
        {"SPY",  to_ticks(183.10)},
        {"AAPL", to_ticks(173.50)},
        {"QQQ",  to_ticks(350.50)}
    });

    portfolio.print_all();

    // -------------------------------------------------------
    // PERFORMANCE
    // -------------------------------------------------------

    std::cout << "\n=== Performance: on_fill + mark ===\n";

    Portfolio bench;
    constexpr int REPS = 1000000;

    auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < REPS; ++i) {
        Side side = (i % 2 == 0) ? Side::BUY : Side::SELL;
        bench.on_fill("SPY", side, 10, to_ticks(182.50 + (i % 100) * 0.01));
        bench.mark("SPY", to_ticks(182.50));
    }
    auto t1 = std::chrono::steady_clock::now();

    uint64_t ns = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());

    std::cout << "  " << REPS << " fills+marks in " << ns / 1000 << "µs\n";
    std::cout << "  Per fill+mark: " << ns / REPS << "ns\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Integration with the risk manager (L59):

        void on_exec_report(const FIXParser& exec) {
            if (exec.exec_type() == 2 || exec.exec_type() == 1) {
                // 2=fill, 1=partial fill
                Side side = (exec.side() == 1) ? Side::BUY : Side::SELL;
                portfolio.on_fill(
                    std::string(exec.symbol()),
                    side,
                    exec.last_qty(),
                    to_ticks(exec.last_px())
                );

                // Update risk manager with fill
                risk.on_fill(
                    std::string(exec.symbol()),
                    side,
                    exec.last_qty(),
                    to_ticks(exec.last_px())
                );

                // Propagate realized PnL to risk system
                if (auto* pos = portfolio.get(std::string(exec.symbol()))) {
                    risk.add_realized_pnl(pos->realized_pnl());
                }
            }
        }

        // On every market data tick:
        void on_tick(const std::string& sym, int64_t mid_price) {
            portfolio.mark(sym, mid_price);
            // unrealized PnL is now up to date — can read from dashboard
        }
    */
}
