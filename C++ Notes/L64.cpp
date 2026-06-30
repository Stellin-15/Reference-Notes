// ============================================================
// L64: Backtesting Framework
// ============================================================
// WHAT: A historical data replay engine that simulates a live
//       trading system against stored tick data. Feeds ticks to
//       a strategy in sequence, simulates order fills using a
//       matching engine, and collects performance metrics:
//       total PnL, Sharpe ratio, max drawdown, hit rate, and
//       trade count.
// WHY (TRADING): You must test your strategy on historical data
//   before risking real capital. Backtesting reveals:
//   - Does the strategy make money at all?
//   - Does it survive different market regimes (volatile / flat)?
//   - What is the realistic drawdown? Can you stomach it?
//   - Does it degrade over time? (overfitting check)
//   A strategy that looks great in backtest but fails live usually
//   has bugs: look-ahead bias, unrealistic fill assumptions, or
//   ignoring transaction costs.
// PHASE: Trading Systems Implementation
// ============================================================

/*
  CONCEPT OVERVIEW:

  BACKTESTING PITFALLS:
    1. LOOK-AHEAD BIAS: using future data to make current decisions
       - Wrong: if (tomorrow_price > today_price) buy_today
       - Fix: process ticks strictly in time order, never peek ahead

    2. SURVIVORSHIP BIAS: testing only on stocks that still exist
       - Fix: include delisted stocks in your universe

    3. FILL ASSUMPTIONS: assuming your order fills at the exact price
       - Reality: large orders move the market (market impact)
       - Reality: limit orders may not fill if price barely touches the level
       - Fix: use a realistic slippage model

    4. TRANSACTION COSTS: forgetting commissions and fees
       - Equities: ~$0.001-$0.005 per share (ECN rebates/takes)
       - Futures: ~$2-$5 per contract per side
       - Fix: deduct from PnL on every fill

    5. OVERFITTING: strategy parameters tuned to historical noise
       - Symptom: great in-sample, terrible out-of-sample
       - Fix: in-sample / out-of-sample split, walk-forward testing

  PERFORMANCE METRICS:
    Sharpe Ratio = (mean_return - risk_free_rate) / std_dev_return
    - Daily Sharpe > 1: acceptable
    - Daily Sharpe > 2: good
    - Daily Sharpe > 3: excellent
    - Annualized = daily_sharpe × √252

    Max Drawdown = max peak-to-trough decline in equity curve
    - Tells you the worst historical loss streak
    - If max_drawdown > your pain tolerance, don't trade this strategy

    Hit Rate = winning_trades / total_trades
    - 50% hit rate can be profitable if wins are bigger than losses
    - High hit rate with small wins and large losses = losing strategy

    Profit Factor = gross_profit / gross_loss (should be > 1.5)

  SLIPPAGE MODEL:
    Simple: fill = price ± slippage_ticks
    Market order buy: fill_price = ask + slippage_ticks
    Limit order: fill only if ask ≤ limit_price (conservative)

  COMMON MISTAKES:
    - Using bid price for market buys (should be ask)
    - Ignoring partial fills (limit orders may not fill at all)
    - Not accounting for quote spread as a cost
    - Assuming infinite liquidity (your order fills 100% always)
*/

#include <iostream>
#include <vector>
#include <string>
#include <cstdint>
#include <cassert>
#include <cmath>
#include <algorithm>
#include <numeric>
#include <fstream>
#include <sstream>
#include <functional>
#include <chrono>
#include <optional>
#include <iomanip>

// ============================================================
// TYPES
// ============================================================

constexpr int64_t PRICE_MULT = 10000;
constexpr int64_t to_ticks(double p) { return static_cast<int64_t>(p * PRICE_MULT + 0.5); }
constexpr double  to_price(int64_t t){ return static_cast<double>(t)  / PRICE_MULT; }

enum class Side { BUY = 0, SELL = 1 };

struct Tick {
    uint64_t timestamp_ns;
    char     symbol[8];
    int64_t  bid_price;
    int64_t  ask_price;
    int32_t  bid_qty;
    int32_t  ask_qty;
    int64_t  last_price;  // last trade price
};

struct SimOrder {
    uint64_t id;
    Side     side;
    int64_t  limit_price;   // 0 = market order
    int32_t  qty;
    bool     is_ioc;
};

struct SimFill {
    uint64_t order_id;
    Side     side;
    int64_t  fill_price;
    int32_t  fill_qty;
    uint64_t fill_ts;
};

struct Trade {
    int64_t  entry_price;
    int64_t  exit_price;
    int32_t  qty;
    Side     side;
    int64_t  pnl;           // in ticks × qty (not per-share)
    bool     is_winner;
};

// ============================================================
// SLIPPAGE MODEL
// ============================================================

struct SlippageModel {
    int64_t fixed_slippage_ticks  = 1;    // 1 tick per market order
    double  market_impact_bps     = 0.5;  // 0.5 bps per 100 shares
    int64_t commission_per_share  = to_ticks(0.001);  // $0.001/share commission

    int64_t buy_fill_price(int64_t ask_price, int32_t qty) const {
        int64_t slippage = fixed_slippage_ticks;
        slippage += static_cast<int64_t>(ask_price * market_impact_bps / 10000.0 * qty / 100);
        return ask_price + slippage;
    }

    int64_t sell_fill_price(int64_t bid_price, int32_t qty) const {
        int64_t slippage = fixed_slippage_ticks;
        slippage += static_cast<int64_t>(bid_price * market_impact_bps / 10000.0 * qty / 100);
        return bid_price - slippage;
    }

    int64_t commission(int32_t qty) const {
        return commission_per_share * qty;
    }
};

// ============================================================
// SIMULATED FILL ENGINE — applies slippage, checks liquidity
// ============================================================

class SimFillEngine {
public:
    explicit SimFillEngine(SlippageModel model = {}) : model_(model) {}

    std::optional<SimFill> try_fill(const SimOrder& order, const Tick& tick,
                                     uint64_t& next_fill_id) {
        SimFill fill{};
        fill.order_id = order.id;
        fill.side     = order.side;
        fill.fill_ts  = tick.timestamp_ns;
        fill.fill_qty = order.qty;

        if (order.side == Side::BUY) {
            // Market buy: fill at ask + slippage
            if (order.limit_price == 0) {
                fill.fill_price = model_.buy_fill_price(tick.ask_price, order.qty);
            } else {
                // Limit buy: only fill if ask_price <= limit_price
                if (tick.ask_price > order.limit_price) return std::nullopt;
                fill.fill_price = std::min(order.limit_price, tick.ask_price);
            }
            // Check available quantity (simplified: assume up to 50% of ask_qty fills)
            int32_t available = tick.ask_qty / 2;
            if (available < order.qty) fill.fill_qty = available;

        } else {  // SELL
            if (order.limit_price == 0) {
                fill.fill_price = model_.sell_fill_price(tick.bid_price, order.qty);
            } else {
                if (tick.bid_price < order.limit_price) return std::nullopt;
                fill.fill_price = std::max(order.limit_price, tick.bid_price);
            }
            int32_t available = tick.bid_qty / 2;
            if (available < order.qty) fill.fill_qty = available;
        }

        if (fill.fill_qty <= 0) return std::nullopt;

        // Deduct commission from fill price (embedded in cost)
        if (order.side == Side::BUY)
            fill.fill_price += model_.commission(fill.fill_qty) / fill.fill_qty;
        else
            fill.fill_price -= model_.commission(fill.fill_qty) / fill.fill_qty;

        fill.order_id = next_fill_id++;
        return fill;
    }

private:
    SlippageModel model_;
};

// ============================================================
// PERFORMANCE METRICS
// ============================================================

struct BacktestMetrics {
    int     total_trades    = 0;
    int     winning_trades  = 0;
    int64_t total_pnl       = 0;     // in ticks (×qty not per share)
    int64_t max_drawdown    = 0;
    int64_t peak_equity     = 0;
    double  sharpe_ratio    = 0.0;

    std::vector<int64_t> daily_pnl;   // for Sharpe computation
    std::vector<int64_t> equity_curve;

    void record_trade(const Trade& t) {
        ++total_trades;
        if (t.pnl > 0) ++winning_trades;
        total_pnl += t.pnl;
    }

    void update_equity(int64_t running_pnl) {
        equity_curve.push_back(running_pnl);
        if (running_pnl > peak_equity) peak_equity = running_pnl;
        int64_t dd = peak_equity - running_pnl;
        if (dd > max_drawdown) max_drawdown = dd;
    }

    void compute_sharpe() {
        if (daily_pnl.size() < 2) { sharpe_ratio = 0; return; }

        double mean = 0;
        for (auto v : daily_pnl) mean += to_price(v);
        mean /= daily_pnl.size();

        double variance = 0;
        for (auto v : daily_pnl) {
            double diff = to_price(v) - mean;
            variance += diff * diff;
        }
        variance /= (daily_pnl.size() - 1);
        double std_dev = std::sqrt(variance);

        sharpe_ratio = (std_dev > 0) ? (mean / std_dev) * std::sqrt(252.0) : 0;
    }

    void print() const {
        double hit_rate = total_trades > 0 ?
            (100.0 * winning_trades / total_trades) : 0.0;

        std::cout << "\n  === Backtest Results ===\n";
        std::cout << "  Total trades:   " << total_trades << "\n";
        std::cout << "  Winning trades: " << winning_trades
                  << " (" << std::fixed << std::setprecision(1) << hit_rate << "%)\n";
        std::cout << "  Total PnL:      $" << to_price(total_pnl) << "\n";
        std::cout << "  Max Drawdown:   $" << to_price(max_drawdown) << "\n";
        std::cout << "  Sharpe ratio:   " << std::setprecision(2) << sharpe_ratio
                  << " (annualized)\n";
    }
};

// ============================================================
// SIMPLE MOMENTUM STRATEGY FOR BACKTESTING
// ============================================================

class BacktestMomentum {
public:
    BacktestMomentum(int sma_period, int threshold_ticks, int order_qty)
        : sma_period_(sma_period)
        , threshold_(threshold_ticks)
        , order_qty_(order_qty)
    {}

    // Called on each tick. Returns an optional order to submit.
    std::optional<SimOrder> on_tick(const Tick& tick) {
        int64_t mid = (tick.bid_price + tick.ask_price) / 2;

        // Update SMA
        sma_buf_.push_back(mid);
        if ((int)sma_buf_.size() > sma_period_) sma_buf_.erase(sma_buf_.begin());

        if ((int)sma_buf_.size() < sma_period_) return std::nullopt;  // warming up

        int64_t sma = std::accumulate(sma_buf_.begin(), sma_buf_.end(), 0LL) / sma_period_;

        if (position_ == 0) {
            // Entry: mid more than threshold above SMA → buy
            if (mid > sma + threshold_) {
                entry_price_ = tick.ask_price;
                SimOrder order{};
                order.id         = ++next_id_;
                order.side       = Side::BUY;
                order.limit_price= 0;  // market order
                order.qty        = order_qty_;
                position_        = order_qty_;
                return order;
            }
        } else if (position_ > 0) {
            // Exit: mid drops below SMA → sell
            if (mid < sma) {
                SimOrder order{};
                order.id         = ++next_id_;
                order.side       = Side::SELL;
                order.limit_price= 0;
                order.qty        = position_;
                position_        = 0;
                return order;
            }
        }

        return std::nullopt;
    }

    // Called when a fill arrives
    void on_fill(const SimFill& fill, BacktestMetrics& metrics) {
        if (fill.side == Side::BUY) {
            entry_price_ = fill.fill_price;
        } else {
            // Closing a long: compute PnL
            int64_t pnl = (fill.fill_price - entry_price_) * fill.fill_qty;
            Trade t{entry_price_, fill.fill_price, fill.fill_qty, Side::BUY, pnl, pnl > 0};
            metrics.record_trade(t);
            running_pnl_ += pnl;
            metrics.update_equity(running_pnl_);
        }
    }

    int32_t position()     const { return position_; }
    int64_t running_pnl()  const { return running_pnl_; }

private:
    int sma_period_;
    int threshold_;
    int order_qty_;

    std::vector<int64_t> sma_buf_;
    int32_t  position_    = 0;
    int64_t  entry_price_ = 0;
    int64_t  running_pnl_ = 0;
    uint64_t next_id_     = 1;
};

// ============================================================
// SYNTHETIC TICK GENERATOR (replaces real historical data)
// ============================================================

std::vector<Tick> generate_synthetic_ticks(int count, double start_price,
                                             double volatility, uint64_t seed) {
    std::vector<Tick> ticks;
    ticks.reserve(count);

    double price = start_price;
    uint64_t rng = seed;

    auto rng_next = [&rng]() -> double {
        rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17;
        // Box-Muller would be better but this gives enough variation for demo
        return static_cast<double>(static_cast<int64_t>(rng & 0xFFFF) - 32768) / 32768.0;
    };

    for (int i = 0; i < count; ++i) {
        // Random walk with slight upward drift
        price += rng_next() * volatility + 0.001;
        if (price < 1.0) price = 1.0;

        Tick t{};
        t.timestamp_ns = static_cast<uint64_t>(i) * 1000000;  // 1ms per tick
        memcpy(t.symbol, "SPY     ", 8);
        t.bid_price  = to_ticks(price - 0.005);   // half-cent spread
        t.ask_price  = to_ticks(price + 0.005);
        t.bid_qty    = 500 + static_cast<int32_t>(rng & 0x3FF);
        t.ask_qty    = 500 + static_cast<int32_t>((rng >> 10) & 0x3FF);
        t.last_price = to_ticks(price);
        ticks.push_back(t);
    }
    return ticks;
}

// ============================================================
// MAIN: RUN A BACKTEST
// ============================================================

int main() {
    std::cout << "=== Backtesting Framework ===\n";

    // -------------------------------------------------------
    // GENERATE SYNTHETIC DATA
    // -------------------------------------------------------

    constexpr int TICK_COUNT = 10000;
    std::cout << "\n  Generating " << TICK_COUNT << " synthetic ticks...\n";

    auto ticks = generate_synthetic_ticks(TICK_COUNT, 182.50, 0.10, 12345);

    // -------------------------------------------------------
    // RUN BACKTEST
    // -------------------------------------------------------

    BacktestMomentum strategy(20, 5, 100);  // SMA=20, threshold=5 ticks, qty=100
    SimFillEngine    fill_engine;
    BacktestMetrics  metrics;

    uint64_t next_fill_id  = 1;
    int      ticks_processed = 0;

    auto t0 = std::chrono::steady_clock::now();

    for (const Tick& tick : ticks) {
        ++ticks_processed;

        // Get strategy signal
        auto order = strategy.on_tick(tick);
        if (!order) continue;

        // Try to fill
        auto fill = fill_engine.try_fill(*order, tick, next_fill_id);
        if (!fill) continue;  // order not filled (limit not reached)

        strategy.on_fill(*fill, metrics);
    }

    // Record daily PnL (simplified: total at end = one "day")
    metrics.daily_pnl.push_back(strategy.running_pnl());
    metrics.compute_sharpe();

    auto t1 = std::chrono::steady_clock::now();
    uint64_t bt_ns = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());

    // -------------------------------------------------------
    // RESULTS
    // -------------------------------------------------------

    std::cout << "\n  Ticks processed: " << ticks_processed << "\n";
    std::cout << "  Backtest time: " << bt_ns / 1000 << "µs\n";
    std::cout << "  Throughput: " << (ticks_processed * 1000ULL) / (bt_ns / 1000 + 1)
              << " K ticks/sec\n";

    metrics.print();

    // -------------------------------------------------------
    // EQUITY CURVE SUMMARY
    // -------------------------------------------------------

    if (!metrics.equity_curve.empty()) {
        std::cout << "\n  Equity curve (every 5th trade):\n";
        for (int i = 0; i < (int)metrics.equity_curve.size(); i += 5) {
            std::cout << "  Trade " << i
                      << ": $" << to_price(metrics.equity_curve[i]) << "\n";
        }
        int64_t final_pnl = metrics.equity_curve.back();
        std::cout << "  Final PnL: $" << to_price(final_pnl) << "\n";
    }

    // -------------------------------------------------------
    // PARAMETER SWEEP (find optimal SMA period)
    // -------------------------------------------------------

    std::cout << "\n=== Parameter sweep: SMA period vs PnL ===\n";
    std::cout << "  SMA | PnL\n";
    std::cout << "  ----+-----------\n";

    for (int sma : {5, 10, 15, 20, 30, 50}) {
        BacktestMomentum strat_s(sma, 5, 100);
        BacktestMetrics  met_s;
        uint64_t fill_id_s = 1;

        for (const Tick& tick : ticks) {
            auto ord = strat_s.on_tick(tick);
            if (!ord) continue;
            auto fill = fill_engine.try_fill(*ord, tick, fill_id_s);
            if (!fill) continue;
            strat_s.on_fill(*fill, met_s);
        }

        std::cout << "  " << std::setw(3) << sma << " | $"
                  << std::setw(10) << to_price(strat_s.running_pnl()) << "\n";
    }

    std::cout << "\n  NOTE: parameter sweep on the SAME dataset is overfitting.\n";
    std::cout << "  In practice: use first 60% of data for training,\n";
    std::cout << "  last 40% for out-of-sample validation.\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      A real backtesting workflow:
        1. Download NASDAQ TotalView-ITCH binary files (or use your own tick data)
        2. Replay using the ITCH parser (L57) — generates synthetic Tick structs
        3. Feed ticks to your strategy via the backtesting framework
        4. Use the SimFillEngine with a realistic slippage model
        5. Compute metrics: Sharpe, max drawdown, hit rate
        6. Walk-forward test: train on months 1-6, test on months 7-12,
           retrain on 2-7, test on 8-12, etc.
        7. If strategy passes walk-forward, paper-trade on live data for 30 days
        8. If paper-trade passes, go live with minimal capital first
    */
}
