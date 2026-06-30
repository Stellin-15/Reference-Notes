// ============================================================
// L59: Risk Management System
// ============================================================
// WHAT: The risk manager is a mandatory gate on every order before
//       it leaves the system. It enforces pre-trade limits: maximum
//       order size, maximum position per symbol, maximum gross
//       exposure, maximum daily loss, and a kill switch. Violations
//       result in order rejection. A fat-finger check catches orders
//       that are wildly mispriced relative to the market.
// WHY (TRADING): Without a risk manager, a single software bug can
//   submit thousands of erroneous orders in milliseconds, resulting
//   in catastrophic losses. Knight Capital lost $440 million in 45
//   minutes due to a software error in 2012 with no adequate kill
//   switch. The risk manager is non-negotiable — it runs on EVERY
//   order, even if it costs 100ns per check.
// PHASE: Trading Systems Implementation
// ============================================================

/*
  CONCEPT OVERVIEW:

  PRE-TRADE CHECKS (in order of cheapness):
    1. Kill switch: if set, reject everything (1 atomic load, ~1ns)
    2. Order size: qty ≤ max_order_qty (1 compare, ~1ns)
    3. Price sanity: price in [min_price, max_price] (2 compares, ~2ns)
    4. Fat-finger: |price - best_bid_or_ask| / best < fat_finger_pct (a few ops, ~5ns)
    5. Symbol position: current_position + qty ≤ max_position (1 map lookup, ~50-100ns)
    6. Gross exposure: sum(|position| * price) + order_notional ≤ max_gross (O(symbols), ~1µs)
    7. Daily PnL: realized + unrealized PnL > -max_daily_loss (1 compare, ~1ns)

  KILL SWITCH:
    A hardware or software emergency stop. Software kill switch =
    std::atomic<bool> — any thread can set it, the hot path checks it
    on every order. Hardware kill switch = a separate process that kills
    the trading process if telemetry stops arriving.

  POSITION LIMITS:
    Per-symbol: e.g., max ±1000 shares of SPY
    Global: max ±5000 shares total across all symbols
    Notional: max $500,000 gross exposure (sum of |position × price|)

  FAT-FINGER CHECK:
    For a limit buy order at price P, if P > best_ask × 1.02 (2% above ask),
    the order is likely a mistake — we'd instantly get filled at a terrible price.
    This catches: wrong decimal point, wrong sign (buy instead of sell), etc.

  DAILY LOSS LIMIT:
    Track realized PnL + unrealized PnL (marked to market).
    If total PnL < -max_daily_loss, trigger kill switch and reject all orders.
    Reset at session start.

  ATOMICS FOR CONCURRENT ACCESS:
    The risk manager may be read from multiple threads (strategy checks
    before submitting, risk monitor reads for dashboards). Use atomics
    for position counters and PnL so reads are safe without locks.

  COMMON MISTAKES:
    - No kill switch → no way to stop a runaway strategy
    - Position limit per symbol but no GROSS limit → correlated positions blow up
    - Fat-finger uses absolute price threshold instead of % (fails at different price levels)
    - Not accounting for pending (in-flight) orders in position check
    - PnL check only on fills (not on price moves) — misses unrealized loss
*/

#include <iostream>
#include <cstdint>
#include <atomic>
#include <unordered_map>
#include <string>
#include <cassert>
#include <optional>
#include <mutex>
#include <chrono>
#include <cmath>

// ============================================================
// PRICE ENCODING
// ============================================================

constexpr int64_t PRICE_MULT = 10000;
constexpr int64_t to_ticks(double p) { return static_cast<int64_t>(p * PRICE_MULT + 0.5); }
constexpr double  to_price(int64_t t){ return static_cast<double>(t)  / PRICE_MULT; }

// ============================================================
// ORDER (simplified — just what risk needs to check)
// ============================================================

enum class Side : uint8_t { BUY = 0, SELL = 1 };

struct PendingOrder {
    std::string symbol;
    Side        side;
    int64_t     price;    // in ticks (0 for market orders)
    int32_t     qty;
    uint16_t    strategy_id;
};

// ============================================================
// RISK PARAMETERS — loaded from config at startup, never changed at runtime
// ============================================================

struct RiskParams {
    int32_t  max_order_qty     = 500;         // max shares per order
    int64_t  max_notional      = 500000 * PRICE_MULT; // max order notional ($500K in ticks×qty)
    int32_t  max_position_per_sym = 5000;     // max ±shares per symbol
    int64_t  max_gross_exposure   = 2000000LL * PRICE_MULT; // $2M in notional
    int64_t  max_daily_loss    = to_ticks(50000.0); // max $50K daily loss (in tick-dollars)
    double   fat_finger_pct    = 0.02;        // 2% away from best is a fat finger
    int64_t  min_price         = to_ticks(0.01);  // minimum valid price: 1 cent
    int64_t  max_price         = to_ticks(100000.0); // maximum valid price: $100K
};

// ============================================================
// RISK REJECTION REASON — for logging
// ============================================================

enum class RiskResult : uint8_t {
    OK              = 0,
    KILL_SWITCH     = 1,
    ORDER_TOO_LARGE = 2,
    PRICE_INVALID   = 3,
    FAT_FINGER      = 4,
    POSITION_LIMIT  = 5,
    GROSS_LIMIT     = 6,
    DAILY_LOSS      = 7
};

const char* risk_result_str(RiskResult r) {
    switch (r) {
        case RiskResult::OK:              return "OK";
        case RiskResult::KILL_SWITCH:     return "KILL_SWITCH";
        case RiskResult::ORDER_TOO_LARGE: return "ORDER_TOO_LARGE";
        case RiskResult::PRICE_INVALID:   return "PRICE_INVALID";
        case RiskResult::FAT_FINGER:      return "FAT_FINGER";
        case RiskResult::POSITION_LIMIT:  return "POSITION_LIMIT";
        case RiskResult::GROSS_LIMIT:     return "GROSS_LIMIT";
        case RiskResult::DAILY_LOSS:      return "DAILY_LOSS";
    }
    return "UNKNOWN";
}

// ============================================================
// RISK MANAGER
// ============================================================

class RiskManager {
public:
    explicit RiskManager(const RiskParams& params)
        : params_(params)
        , kill_switch_(false)
        , daily_realized_pnl_(0)
        , gross_exposure_(0)
        , orders_rejected_(0)
        , orders_passed_(0)
    {}

    // ── KILL SWITCH ─────────────────────────────────────────

    void trigger_kill_switch(const std::string& reason) {
        kill_switch_.store(true, std::memory_order_release);
        kill_reason_ = reason;
        std::cout << "  [KILL SWITCH] Triggered: " << reason << "\n";
    }

    void reset_kill_switch() {
        kill_switch_.store(false, std::memory_order_release);
        kill_reason_.clear();
    }

    bool is_killed() const {
        return kill_switch_.load(std::memory_order_acquire);
    }

    // ── PRE-TRADE CHECK (hot path) ───────────────────────────

    // Returns RiskResult::OK if the order is allowed, or a rejection reason.
    // noexcept: called on every order — no exceptions allowed.
    [[nodiscard]] RiskResult check(const PendingOrder& order,
                                    int64_t best_bid = 0,
                                    int64_t best_ask = 0) noexcept {
        // 1. Kill switch — cheapest check first
        if (kill_switch_.load(std::memory_order_acquire)) {
            ++orders_rejected_;
            return RiskResult::KILL_SWITCH;
        }

        // 2. Order size
        if (order.qty <= 0 || order.qty > params_.max_order_qty) {
            ++orders_rejected_;
            return RiskResult::ORDER_TOO_LARGE;
        }

        // 3. Price validity (skip for market orders)
        if (order.price != 0) {
            if (order.price < params_.min_price || order.price > params_.max_price) {
                ++orders_rejected_;
                return RiskResult::PRICE_INVALID;
            }

            // 4. Fat-finger check: price must be within fat_finger_pct of best
            if (order.side == Side::BUY && best_ask > 0) {
                int64_t pct_threshold = static_cast<int64_t>(best_ask * params_.fat_finger_pct);
                if (order.price > best_ask + pct_threshold) {
                    ++orders_rejected_;
                    return RiskResult::FAT_FINGER;
                }
            } else if (order.side == Side::SELL && best_bid > 0) {
                int64_t pct_threshold = static_cast<int64_t>(best_bid * params_.fat_finger_pct);
                if (order.price < best_bid - pct_threshold) {
                    ++orders_rejected_;
                    return RiskResult::FAT_FINGER;
                }
            }
        }

        // 5. Position limit (requires a map lookup — slightly slower)
        {
            // Use shared_lock so multiple strategies can check concurrently
            int32_t current = get_position(order.symbol);
            int32_t new_pos = current + (order.side == Side::BUY ? order.qty : -order.qty);
            if (new_pos > params_.max_position_per_sym ||
                new_pos < -params_.max_position_per_sym) {
                ++orders_rejected_;
                return RiskResult::POSITION_LIMIT;
            }
        }

        // 6. Gross exposure check
        {
            int64_t ref_price  = (order.price > 0) ? order.price
                                                    : (best_bid + best_ask) / 2;
            int64_t notional   = static_cast<int64_t>(order.qty) * ref_price;
            int64_t new_gross  = gross_exposure_.load(std::memory_order_relaxed) + notional;
            if (new_gross > params_.max_gross_exposure) {
                ++orders_rejected_;
                return RiskResult::GROSS_LIMIT;
            }
        }

        // 7. Daily PnL check
        {
            int64_t pnl = daily_realized_pnl_.load(std::memory_order_relaxed);
            if (pnl < -params_.max_daily_loss) {
                trigger_kill_switch("Daily loss limit breached");
                ++orders_rejected_;
                return RiskResult::DAILY_LOSS;
            }
        }

        ++orders_passed_;
        return RiskResult::OK;
    }

    // ── POSITION UPDATES (called on fills) ──────────────────

    void on_fill(const std::string& symbol, Side side, int32_t qty, int64_t fill_price) {
        int32_t delta = (side == Side::BUY) ? qty : -qty;

        {
            std::lock_guard<std::mutex> lock(pos_mutex_);
            positions_[symbol] += delta;
        }

        // Update gross exposure (simplified: add notional)
        int64_t notional = static_cast<int64_t>(qty) * fill_price;
        gross_exposure_.fetch_add(notional, std::memory_order_relaxed);
    }

    // Update realized PnL (called when a position is reduced/closed)
    void add_realized_pnl(int64_t pnl_ticks) {
        daily_realized_pnl_.fetch_add(pnl_ticks, std::memory_order_relaxed);
    }

    // Reset at start of day
    void reset_daily() {
        daily_realized_pnl_.store(0, std::memory_order_relaxed);
        gross_exposure_.store(0, std::memory_order_relaxed);
        {
            std::lock_guard<std::mutex> lock(pos_mutex_);
            positions_.clear();
        }
        reset_kill_switch();
        orders_passed_   = 0;
        orders_rejected_ = 0;
    }

    // ── QUERIES ─────────────────────────────────────────────

    int32_t get_position(const std::string& sym) const {
        std::lock_guard<std::mutex> lock(pos_mutex_);
        auto it = positions_.find(sym);
        return (it != positions_.end()) ? it->second : 0;
    }

    int64_t daily_pnl_ticks() const {
        return daily_realized_pnl_.load(std::memory_order_relaxed);
    }

    void print_status() const {
        std::cout << "  [RISK STATUS]\n";
        std::cout << "    Kill switch: " << (is_killed() ? "ACTIVE" : "off") << "\n";
        std::cout << "    Orders passed:   " << orders_passed_   << "\n";
        std::cout << "    Orders rejected: " << orders_rejected_ << "\n";
        std::cout << "    Daily PnL: $" << to_price(daily_pnl_ticks()) << "\n";
        std::cout << "    Gross exposure: $" << to_price(gross_exposure_.load()) << "\n";
        {
            std::lock_guard<std::mutex> lock(pos_mutex_);
            for (auto& [sym, pos] : positions_) {
                std::cout << "    " << sym << ": " << pos << " shares\n";
            }
        }
    }

private:
    RiskParams  params_;
    std::atomic<bool>    kill_switch_;
    std::string          kill_reason_;
    std::atomic<int64_t> daily_realized_pnl_;
    std::atomic<int64_t> gross_exposure_;
    std::atomic<int64_t> orders_rejected_;
    std::atomic<int64_t> orders_passed_;

    mutable std::mutex pos_mutex_;
    std::unordered_map<std::string, int32_t> positions_;  // symbol → net position
};

// ============================================================
// MAIN
// ============================================================

int main() {
    std::cout << "=== Risk Management System ===\n";

    RiskParams params;
    params.max_order_qty      = 200;
    params.max_position_per_sym = 500;
    params.max_daily_loss     = to_ticks(10000.0);  // $10K daily loss limit

    RiskManager risk(params);

    // Helper: print check result
    auto check_order = [&](const char* sym, Side side, double price, int32_t qty,
                             double best_bid, double best_ask, const char* desc) {
        PendingOrder o;
        o.symbol = sym;
        o.side   = side;
        o.price  = to_ticks(price);
        o.qty    = qty;

        RiskResult r = risk.check(o, to_ticks(best_bid), to_ticks(best_ask));
        std::cout << "  " << desc << " → " << risk_result_str(r)
                  << (r == RiskResult::OK ? " ✓" : " ✗") << "\n";
        return r;
    };

    // -------------------------------------------------------
    // NORMAL ORDERS (should pass)
    // -------------------------------------------------------

    std::cout << "\n--- Normal orders (should pass) ---\n";

    check_order("SPY", Side::BUY, 182.50, 100, 182.49, 182.51, "BUY 100 SPY @182.50");
    check_order("SPY", Side::SELL, 182.60, 50, 182.59, 182.61, "SELL 50 SPY @182.60");

    // -------------------------------------------------------
    // SIMULATED FILLS (update positions)
    // -------------------------------------------------------

    risk.on_fill("SPY", Side::BUY,  100, to_ticks(182.50));
    risk.on_fill("SPY", Side::SELL,  50, to_ticks(182.60));
    std::cout << "\n  Position after fills: " << risk.get_position("SPY") << " SPY shares\n";

    // -------------------------------------------------------
    // REJECTION SCENARIOS
    // -------------------------------------------------------

    std::cout << "\n--- Rejection scenarios ---\n";

    check_order("SPY", Side::BUY, 182.50, 201,  182.49, 182.51, "Order too large (qty=201)");
    check_order("SPY", Side::BUY, 200.00, 100,  182.49, 182.51, "Fat finger (200 vs ask 182.51)");
    check_order("SPY", Side::BUY, -1.00,  100,  182.49, 182.51, "Negative price");

    // Position limit: already have 50 long, max is 500. Buy 460 more = 510 > 500
    {
        PendingOrder big_buy{"SPY", Side::BUY, to_ticks(182.50), 460, 0};
        RiskResult r = risk.check(big_buy, to_ticks(182.49), to_ticks(182.51));
        std::cout << "  Position limit (460 more, already +50) → " << risk_result_str(r) << " ✗\n";
    }

    // -------------------------------------------------------
    // DAILY LOSS TRIGGER
    // -------------------------------------------------------

    std::cout << "\n--- Daily loss limit ---\n";

    risk.add_realized_pnl(to_ticks(-10001.0));  // exceed -$10K limit
    {
        PendingOrder o{"SPY", Side::BUY, to_ticks(182.50), 10, 0};
        RiskResult r = risk.check(o, to_ticks(182.49), to_ticks(182.51));
        std::cout << "  After -$10001 loss: " << risk_result_str(r) << " ✗\n";
    }

    // -------------------------------------------------------
    // KILL SWITCH
    // -------------------------------------------------------

    std::cout << "\n--- Kill switch ---\n";

    risk.reset_kill_switch();
    risk.reset_daily();
    risk.trigger_kill_switch("Manual emergency stop");

    {
        PendingOrder o{"SPY", Side::BUY, to_ticks(182.50), 10, 0};
        RiskResult r = risk.check(o, to_ticks(182.49), to_ticks(182.51));
        std::cout << "  Order during kill switch: " << risk_result_str(r) << " ✗\n";
    }

    // -------------------------------------------------------
    // STATUS REPORT
    // -------------------------------------------------------

    std::cout << "\n";
    risk.print_status();

    // -------------------------------------------------------
    // PERFORMANCE CHECK
    // -------------------------------------------------------

    std::cout << "\n=== Risk check latency ===\n";

    risk.reset_kill_switch();
    risk.reset_daily();

    PendingOrder fast_order{"SPY", Side::BUY, to_ticks(182.50), 50, 0};
    constexpr int REPS = 1000000;

    auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < REPS; ++i) {
        volatile auto r = risk.check(fast_order, to_ticks(182.49), to_ticks(182.51));
        (void)r;
    }
    auto t1 = std::chrono::steady_clock::now();

    uint64_t ns = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());

    std::cout << "  " << REPS << " risk checks in " << ns / 1000 << "µs\n";
    std::cout << "  Per check: " << ns / REPS << "ns\n";
    std::cout << "  (position lookup via unordered_map is the bottleneck)\n";
    std::cout << "  (replace with array-indexed by symbol ID for <20ns)\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Order submission flow:
        1. Strategy generates PendingOrder
        2. risk.check(order, best_bid, best_ask) → OK or rejection reason
        3. If OK: serialize to FIX (L56) → send via socket (L46)
        4. On fill from exchange: risk.on_fill(symbol, side, qty, fill_price)
        5. On fill: update PnL tracker (L60)
        6. PnL tracker calls risk.add_realized_pnl() when positions close
        7. If daily PnL < -max_daily_loss: kill switch triggered automatically

      The kill switch should also be wired to an external "dead man's switch":
      a separate watchdog process that kills the trading process if no
      heartbeat is received within N seconds.
    */
}
