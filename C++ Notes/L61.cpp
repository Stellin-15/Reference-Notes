// ============================================================
// L61: Strategy Framework (CRTP)
// ============================================================
// WHAT: A strategy framework that defines the interface for all
//       trading strategies (on_market_data, on_fill, on_timer)
//       and uses CRTP (Curiously Recurring Template Pattern) to
//       provide zero-overhead polymorphism — all calls are resolved
//       at compile time with no vtable lookup.
// WHY (TRADING): The strategy is where the alpha lives. The framework
//   separates WHAT to compute (strategy logic) from HOW to connect
//   it (market data routing, order submission, risk checks). CRTP
//   gives us the clean polymorphism of virtual functions without the
//   ~5ns vtable indirection on every tick — at 1M ticks/second,
//   that's 5ms of extra latency per second.
// PHASE: Trading Systems Implementation
// ============================================================

/*
  CONCEPT OVERVIEW:

  CRTP (CURIOUSLY RECURRING TEMPLATE PATTERN):
    template<typename Derived>
    class Base {
        void on_tick(const Tick& t) {
            static_cast<Derived*>(this)->on_tick_impl(t);  // compile-time dispatch
        }
    };
    class MyStrategy : public Base<MyStrategy> {
        void on_tick_impl(const Tick& t) { /* actual logic */ }
    };
    RESULT: on_tick_impl is inlined at compile time — zero virtual dispatch.

  vs VIRTUAL FUNCTIONS:
    With virtual: 1 indirect call (load vtable ptr, load fn ptr, call) = ~5ns
    With CRTP:    0 indirect calls (compiler knows the exact function) = ~0ns
    At 1M ticks/sec: 5ms saved per second. Over a 6.5hr trading day: 117ms total.
    In HFT, that 117ms represents thousands of trades.

  STRATEGY LIFECYCLE:
    1. on_startup()        — called once at system start
    2. on_market_data()    — called on every tick (most frequent)
    3. on_fill()           — called when an order is filled
    4. on_cancel()         — called when a cancel is confirmed
    5. on_timer()          — called periodically (e.g., every 1ms)
    6. on_shutdown()       — called on graceful shutdown

  ORDER SUBMISSION:
    Strategies don't submit orders directly. They call:
      context_.submit_order(order)  — goes through risk, then gateway
    This decoupling allows the framework to enforce risk checks, apply
    kill switches, and log without touching strategy code.

  STATE MACHINE:
    A strategy has lifecycle states:
      INACTIVE → ACTIVE → FLAT → CLOSING → CLOSED
    The framework manages transitions; the strategy only handles events.

  COMMON MISTAKES:
    - Strategy calls malloc/free in on_market_data (destroys latency)
    - Strategy stores std::string symbol names (heap allocation)
    - No guard against submitting orders when already flat or closing
    - Strategy logic in on_fill that takes >10µs (blocks the fill path)
    - Multiple strategies sharing the same order book without synchronization
*/

#include <iostream>
#include <cstdint>
#include <cstring>
#include <string>
#include <optional>
#include <functional>
#include <cassert>
#include <chrono>
#include <atomic>

// ============================================================
// SHARED TYPES (condensed from earlier lessons)
// ============================================================

constexpr int64_t PRICE_MULT = 10000;
constexpr int64_t to_ticks(double p) { return static_cast<int64_t>(p * PRICE_MULT + 0.5); }
constexpr double  to_price(int64_t t){ return static_cast<double>(t)  / PRICE_MULT; }

enum class Side      : uint8_t { BUY = 0, SELL = 1 };
enum class OrderType : uint8_t { LIMIT = 0, MARKET = 1, IOC = 2 };

struct Tick {
    char    symbol[8];
    int64_t bid_price;    // in ticks
    int64_t ask_price;
    int32_t bid_qty;
    int32_t ask_qty;
    uint64_t timestamp_ns;
};

struct Fill {
    uint64_t order_id;
    char     symbol[8];
    Side     side;
    int64_t  fill_price;
    int32_t  fill_qty;
    int32_t  remaining_qty;
};

struct OrderRequest {
    char      symbol[8];
    Side      side;
    OrderType type;
    int64_t   price;      // 0 for market orders
    int32_t   qty;
    uint16_t  strategy_id;
};

// ============================================================
// STRATEGY CONTEXT — the framework services available to strategies
// ============================================================

class StrategyContext {
public:
    using OrderHandler = std::function<void(const OrderRequest&)>;

    explicit StrategyContext(OrderHandler submit_fn)
        : submit_fn_(submit_fn) {}

    // Submit an order (goes through risk → gateway)
    void submit_order(const OrderRequest& req) {
        ++orders_submitted_;
        submit_fn_(req);
    }

    // Get current time in nanoseconds
    uint64_t now_ns() const {
        return static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::steady_clock::now().time_since_epoch()).count());
    }

    uint64_t orders_submitted() const { return orders_submitted_; }

private:
    OrderHandler submit_fn_;
    uint64_t     orders_submitted_ = 0;
};

// ============================================================
// BASE STRATEGY (CRTP) — zero-overhead dispatch
// ============================================================

template<typename Derived>
class BaseStrategy {
public:
    explicit BaseStrategy(uint16_t id, StrategyContext& ctx)
        : strategy_id_(id), ctx_(ctx) {}

    // Called on every market data tick (highest frequency)
    void on_market_data(const Tick& tick) {
        ++tick_count_;
        static_cast<Derived*>(this)->on_market_data_impl(tick);
    }

    // Called when one of our orders is filled
    void on_fill(const Fill& fill) {
        ++fill_count_;
        static_cast<Derived*>(this)->on_fill_impl(fill);
    }

    // Called on a periodic timer (e.g., every 1ms)
    void on_timer(uint64_t ts_ns) {
        static_cast<Derived*>(this)->on_timer_impl(ts_ns);
    }

    // Startup/shutdown hooks
    void on_startup()  { static_cast<Derived*>(this)->on_startup_impl();  }
    void on_shutdown() { static_cast<Derived*>(this)->on_shutdown_impl(); }

    uint16_t strategy_id() const { return strategy_id_; }
    uint64_t tick_count()  const { return tick_count_;  }
    uint64_t fill_count()  const { return fill_count_;  }

protected:
    // Helpers available to all derived strategies

    void submit_limit(const char* sym, Side side, double price, int32_t qty) {
        OrderRequest req{};
        memcpy(req.symbol, sym, std::min((int)strlen(sym), 8));
        req.side        = side;
        req.type        = OrderType::LIMIT;
        req.price       = to_ticks(price);
        req.qty         = qty;
        req.strategy_id = strategy_id_;
        ctx_.submit_order(req);
    }

    void submit_market(const char* sym, Side side, int32_t qty) {
        OrderRequest req{};
        memcpy(req.symbol, sym, std::min((int)strlen(sym), 8));
        req.side        = side;
        req.type        = OrderType::MARKET;
        req.price       = 0;
        req.qty         = qty;
        req.strategy_id = strategy_id_;
        ctx_.submit_order(req);
    }

    StrategyContext& ctx_;

    uint16_t strategy_id_;
    uint64_t tick_count_ = 0;
    uint64_t fill_count_ = 0;

    // Default implementations (do nothing) — derived class can override any subset
    void on_market_data_impl(const Tick&)   {}
    void on_fill_impl(const Fill&)          {}
    void on_timer_impl(uint64_t)            {}
    void on_startup_impl()                  {}
    void on_shutdown_impl()                 {}
};

// ============================================================
// STRATEGY 1: Momentum — buys when bid rises above 20-tick SMA
// ============================================================

class MomentumStrategy : public BaseStrategy<MomentumStrategy> {
public:
    MomentumStrategy(StrategyContext& ctx)
        : BaseStrategy(1, ctx) {}

    void on_market_data_impl(const Tick& tick) {
        // Update simple moving average of mid price
        int64_t mid = (tick.bid_price + tick.ask_price) / 2;
        add_to_sma(mid);

        if (sma_ready_ && position_ == 0) {
            // BUY signal: current mid > SMA (upward momentum)
            if (mid > current_sma_ + TICK_THRESHOLD) {
                submit_market("SPY", Side::BUY, ORDER_QTY);
                pending_buy_ = true;
            }
        }

        // Exit: mid falls below SMA
        if (position_ > 0 && mid < current_sma_) {
            submit_market("SPY", Side::SELL, position_);
        }

        last_mid_ = mid;
    }

    void on_fill_impl(const Fill& fill) {
        if (fill.side == Side::BUY) {
            position_    += fill.fill_qty;
            avg_entry_    = fill.fill_price;
            pending_buy_  = false;
        } else {
            position_    -= fill.fill_qty;
            int64_t realized = (fill.fill_price - avg_entry_) * fill.fill_qty;
            total_realized_pnl_ += realized;
        }
    }

    void on_startup_impl() {
        std::cout << "  [MOMENTUM] Starting up\n";
        sma_ready_ = false;
        sma_idx_   = 0;
    }

    void on_shutdown_impl() {
        std::cout << "  [MOMENTUM] Shutdown | fills=" << fill_count_
                  << " PnL=$" << to_price(total_realized_pnl_) << "\n";
    }

    int32_t position()    const { return position_; }
    int64_t realized_pnl()const { return total_realized_pnl_; }

private:
    static constexpr int     SMA_PERIOD      = 20;
    static constexpr int64_t TICK_THRESHOLD  = 5;   // 5 ticks above SMA = buy signal
    static constexpr int32_t ORDER_QTY       = 100;

    int64_t sma_buf_[SMA_PERIOD] = {};
    int     sma_idx_   = 0;
    bool    sma_ready_ = false;
    int64_t current_sma_= 0;
    int64_t last_mid_  = 0;

    int32_t position_   = 0;
    int64_t avg_entry_  = 0;
    int64_t total_realized_pnl_ = 0;
    bool    pending_buy_ = false;

    void add_to_sma(int64_t mid) {
        sma_buf_[sma_idx_] = mid;
        sma_idx_           = (sma_idx_ + 1) % SMA_PERIOD;
        if (!sma_ready_ && sma_idx_ == 0) sma_ready_ = true;

        if (sma_ready_) {
            int64_t sum = 0;
            for (int i = 0; i < SMA_PERIOD; ++i) sum += sma_buf_[i];
            current_sma_ = sum / SMA_PERIOD;
        }
    }
};

// ============================================================
// STRATEGY 2: Market Maker — posts bid and ask, earns the spread
// ============================================================

class MarketMakerStrategy : public BaseStrategy<MarketMakerStrategy> {
public:
    MarketMakerStrategy(StrategyContext& ctx)
        : BaseStrategy(2, ctx) {}

    void on_market_data_impl(const Tick& tick) {
        int64_t spread = tick.ask_price - tick.bid_price;
        if (spread < MIN_SPREAD) return;  // spread too tight — no edge

        int64_t mid = (tick.bid_price + tick.ask_price) / 2;

        // Quote 1 tick inside the spread on each side
        int64_t our_bid = mid - HALF_SPREAD;
        int64_t our_ask = mid + HALF_SPREAD;

        if (position_ == 0 && !quotes_live_) {
            // Post both sides
            OrderRequest bid_req{};
            memcpy(bid_req.symbol, "SPY     ", 8);
            bid_req.side        = Side::BUY;
            bid_req.type        = OrderType::LIMIT;
            bid_req.price       = our_bid;
            bid_req.qty         = QUOTE_QTY;
            bid_req.strategy_id = strategy_id_;
            ctx_.submit_order(bid_req);

            OrderRequest ask_req = bid_req;
            ask_req.side  = Side::SELL;
            ask_req.price = our_ask;
            ctx_.submit_order(ask_req);

            quotes_live_ = true;
            ++quote_cycles_;
        }
    }

    void on_fill_impl(const Fill& fill) {
        if (fill.side == Side::BUY) {
            position_   += fill.fill_qty;
        } else {
            position_   -= fill.fill_qty;
            // Compute realized PnL if we're now flat
            if (position_ == 0) {
                quotes_live_ = false;  // repost quotes on next tick
            }
        }
    }

    void on_startup_impl() {
        std::cout << "  [MARKET_MAKER] Starting up\n";
    }

    int32_t position()    const { return position_; }
    int64_t quote_cycles()const { return quote_cycles_; }

private:
    static constexpr int64_t MIN_SPREAD  = 2;    // 2 ticks minimum spread to quote
    static constexpr int64_t HALF_SPREAD = 1;    // our quote is ±1 tick from mid
    static constexpr int32_t QUOTE_QTY  = 50;

    int32_t position_    = 0;
    bool    quotes_live_ = false;
    int64_t quote_cycles_= 0;
};

// ============================================================
// STRATEGY RUNNER — dispatches ticks to multiple strategies
// ============================================================

class StrategyRunner {
public:
    // Add a strategy to the runner (type-erased via std::function)
    template<typename S>
    void add_strategy(S& strategy) {
        on_tick_fns_.push_back([&strategy](const Tick& t) { strategy.on_market_data(t); });
        on_fill_fns_.push_back([&strategy](const Fill& f) { strategy.on_fill(f); });
        strategies_.push_back([&strategy]() { strategy.on_startup(); });
    }

    void startup() {
        for (auto& fn : strategies_) fn();
    }

    // Called on every tick — dispatches to all strategies
    void dispatch_tick(const Tick& tick) {
        for (auto& fn : on_tick_fns_) fn(tick);
    }

    void dispatch_fill(const Fill& fill) {
        for (auto& fn : on_fill_fns_) fn(fill);
    }

private:
    std::vector<std::function<void(const Tick&)>> on_tick_fns_;
    std::vector<std::function<void(const Fill&)>> on_fill_fns_;
    std::vector<std::function<void()>>            strategies_;
};

// ============================================================
// MAIN
// ============================================================

int main() {
    std::cout << "=== Strategy Framework (CRTP) ===\n";

    // -------------------------------------------------------
    // SETUP CONTEXT AND STRATEGIES
    // -------------------------------------------------------

    std::vector<OrderRequest> submitted_orders;
    StrategyContext ctx([&](const OrderRequest& req) {
        submitted_orders.push_back(req);
        std::cout << "  ORDER: " << (req.side == Side::BUY ? "BUY" : "SELL")
                  << " " << req.qty
                  << " @ $" << to_price(req.price)
                  << " strategy=" << req.strategy_id << "\n";
    });

    MomentumStrategy   momentum(ctx);
    MarketMakerStrategy mm(ctx);

    StrategyRunner runner;
    runner.add_strategy(momentum);
    runner.add_strategy(mm);
    runner.startup();

    // -------------------------------------------------------
    // SIMULATE MARKET DATA TICKS
    // -------------------------------------------------------

    std::cout << "\n--- Market data ticks ---\n";

    // Build a tick helper
    auto make_tick = [](double bid, double ask) {
        Tick t{};
        memcpy(t.symbol, "SPY     ", 8);
        t.bid_price = to_ticks(bid);
        t.ask_price = to_ticks(ask);
        t.bid_qty   = 500;
        t.ask_qty   = 500;
        t.timestamp_ns = static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::steady_clock::now().time_since_epoch()).count());
        return t;
    };

    // Feed 25 ticks: price drifts up → momentum signal triggers
    double price = 182.50;
    for (int i = 0; i < 25; ++i) {
        if (i > 10) price += 0.05;  // price rises after 10 ticks
        runner.dispatch_tick(make_tick(price, price + 0.01));
    }

    std::cout << "\nTicks dispatched: momentum=" << momentum.tick_count()
              << " mm=" << mm.tick_count() << "\n";
    std::cout << "Orders submitted: " << submitted_orders.size() << "\n";

    // -------------------------------------------------------
    // CRTP vs VIRTUAL OVERHEAD DEMO
    // -------------------------------------------------------

    std::cout << "\n=== CRTP vs virtual overhead ===\n";

    Tick bench_tick = make_tick(182.50, 182.51);
    constexpr int REPS = 5000000;

    // CRTP dispatch
    auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < REPS; ++i) {
        momentum.on_market_data(bench_tick);
    }
    auto t1 = std::chrono::steady_clock::now();

    uint64_t crtp_ns = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());

    std::cout << "  CRTP (5M ticks): " << crtp_ns / 1000 << "µs\n";
    std::cout << "  Per tick: " << crtp_ns / REPS << "ns\n";
    std::cout << "  (virtual would add ~5ns per tick from vtable indirection)\n";

    // -------------------------------------------------------
    // SHUTDOWN
    // -------------------------------------------------------

    std::cout << "\n--- Shutdown ---\n";
    momentum.on_shutdown();

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      A production strategy runner:
        1. All strategies share the same order book (read-only access)
        2. Each strategy has its own position tracker and risk budget
        3. Strategies run in order of priority on the same thread
        4. The runner measures on_market_data() latency for each strategy
           using rdtsc (L50) and logs if any strategy exceeds its budget

      CRTP allows the compiler to:
        - Inline on_market_data_impl() into on_market_data()
        - Eliminate dead code for unused virtual methods
        - Enable further optimizations (loop unrolling, SIMD) on strategy logic
        This is why production HFT systems use CRTP for their strategy interfaces.
    */
}
