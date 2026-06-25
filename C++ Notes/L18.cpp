// ============================================================
// L18: Inheritance and Polymorphism
// ============================================================
// WHAT: Inheritance lets a class (derived) build on another class
//       (base), reusing and extending its interface and behavior.
//       Polymorphism lets you write code that works on the base
//       type but behaves differently for each derived type.
// WHY (TRADING): Inheritance powers strategy frameworks.
//   A BaseStrategy defines the interface: onMarketData(), onFill(),
//   onTimer(). MomentumStrategy and MeanReversionStrategy each
//   implement their own logic. The system can run ANY strategy
//   through the same interface. You can swap strategies without
//   changing any surrounding infrastructure.
// PHASE: OOP
// ============================================================

/*
  CONCEPT OVERVIEW:

  INHERITANCE SYNTAX:
    class Derived : public Base { ... };
    - public inheritance: public/protected members of Base remain public/protected in Derived
    - private inheritance: all Base members become private in Derived (rare)
    - protected inheritance: all Base members become protected in Derived (very rare)
    Default for classes: private. Default for structs: public.
    In trading: always use public inheritance.

  WHAT DERIVED INHERITS:
    - All public and protected members of Base
    - NOT: constructors (must call explicitly), NOT: destructors (automatically chained)
    - NOT: private members (still exist in memory, but not accessible by name)

  CALLING THE BASE CONSTRUCTOR:
    Derived(args) : Base(base_args) { ... }
    Must explicitly pass the right arguments to the base constructor via initializer list.

  OVERRIDE:
    Derived class can redefine a virtual method from Base.
    Mark with 'override' keyword — compiler errors if the signature doesn't match.
    This catches typos: void onTick(Quote q) vs void onTick(const Quote& q) — different!

  FINAL:
    'final' on a class: prevents further inheritance.
    'final' on a method: prevents override in derived classes.
    Use sparingly — in HFT, 'final' on a class allows the compiler to devirtualize calls.

  IS-A vs HAS-A:
    IS-A: use inheritance.      MomentumStrategy IS-A BaseStrategy
    HAS-A: use composition.     Strategy HAS-A RiskManager (not inherits from it)
    Rule: if the relationship doesn't make sense as "X is a type of Y", use composition.
    Over-use of inheritance creates fragile hierarchies — prefer composition.

  SLICING:
    If you assign a Derived object to a Base value (not pointer/ref),
    the derived-class data is SLICED OFF — only Base data is copied.
    Always use Base* or Base& for polymorphic behavior.

  TRADING USE CASE:
    class BaseStrategy {
    public:
        virtual void on_quote(const Quote& q) = 0;  // must implement
        virtual void on_fill(const Fill& f) = 0;    // must implement
        virtual std::string name() const = 0;
        virtual ~BaseStrategy() = default;           // always virtual destructor
    };
    class MomentumStrategy : public BaseStrategy { ... };
    class MeanReversionStrategy : public BaseStrategy { ... };

  COMMON MISTAKES:
    - Non-virtual destructor in base class — derived class's destructor won't run when
      deleting via Base* (memory leak / resource leak)
    - Object slicing — assigning Derived to Base value, losing derived data
    - Calling virtual functions from a constructor — won't dispatch to derived class
      (object isn't fully constructed yet — always calls the Base version)
    - Deep inheritance hierarchies (more than 2 levels) — hard to maintain
*/

#include <iostream>
#include <string>
#include <vector>
#include <memory>    // std::unique_ptr
#include <cstdint>

// ============================================================
// SHARED DATA TYPES
// ============================================================

struct Quote {
    std::string symbol;
    double      bid;
    double      ask;
    uint64_t    seq;    // sequence number

    double mid()    const { return (bid + ask) / 2.0; }
    double spread() const { return ask - bid; }
};

struct Fill {
    uint64_t order_id;
    double   price;
    int32_t  qty;
    bool     is_buy;
};

struct Signal {
    bool    send_order;
    bool    is_buy;
    double  price;
    int32_t qty;
    Signal() : send_order(false), is_buy(true), price(0.0), qty(0) {}
};

// ============================================================
// BASE STRATEGY — the interface all strategies must implement
// ============================================================

class BaseStrategy {
public:
    // Constructor: all strategies need a name and a max position limit
    explicit BaseStrategy(std::string name, int max_position)
        : name_(std::move(name))
        , max_position_(max_position)
        , position_(0)
        , realized_pnl_(0.0)
    {}

    // Virtual destructor: MANDATORY in any base class.
    // Without this, deleting via BaseStrategy* won't call the derived destructor.
    virtual ~BaseStrategy() {
        std::cout << "[" << name_ << "] Shutting down. Final PnL: $" << realized_pnl_ << "\n";
    }

    // --- PURE VIRTUAL METHODS (= 0): derived class MUST implement these ---

    // Called every time a new quote arrives
    virtual Signal on_quote(const Quote& quote) = 0;

    // Called every time one of our orders gets filled
    virtual void on_fill(const Fill& fill) = 0;

    // A human-readable description of what this strategy does
    virtual std::string description() const = 0;

    // --- NON-VIRTUAL METHODS: shared behavior for ALL strategies ---

    const std::string& name()         const { return name_; }
    int                position()     const { return position_; }
    double             realized_pnl() const { return realized_pnl_; }
    int                max_position() const { return max_position_; }

    // Common risk check that all strategies share — not overridable
    bool within_position_limit(int order_qty, bool is_buy) const {
        int new_pos = position_ + (is_buy ? order_qty : -order_qty);
        return std::abs(new_pos) <= max_position_;
    }

    void print_status() const {
        std::cout << "[" << name_ << "] pos=" << position_
                  << " PnL=$" << realized_pnl_ << "\n";
    }

protected:
    // Protected: derived classes CAN access these directly
    // (they're internal strategy state, not public API)
    std::string name_;
    int         max_position_;
    int         position_;        // current net position (+ = long, - = short)
    double      realized_pnl_;

    // Protected helper for derived classes to record fills
    void record_fill(const Fill& fill) {
        if (fill.is_buy) {
            position_ += fill.qty;
        } else {
            position_ -= fill.qty;
            realized_pnl_ += (fill.price - last_entry_) * fill.qty;
        }
        last_entry_ = fill.price;
    }

private:
    double last_entry_ = 0.0;   // private: even derived classes don't access directly
};

// ============================================================
// MOMENTUM STRATEGY — buys when price is rising, sells on reversal
// ============================================================

class MomentumStrategy : public BaseStrategy {
public:
    MomentumStrategy(int max_position, double threshold_bps)
        : BaseStrategy("Momentum", max_position)   // call base constructor explicitly
        , threshold_bps_(threshold_bps)
        , prev_mid_(0.0)
        , ticks_seen_(0)
    {}

    // override keyword: compiler error if signature doesn't match BaseStrategy
    Signal on_quote(const Quote& quote) override {
        Signal sig;
        double mid = quote.mid();
        ++ticks_seen_;

        if (ticks_seen_ < 2) {
            prev_mid_ = mid;
            return sig;   // not enough data yet
        }

        double change_bps = (mid - prev_mid_) / prev_mid_ * 10000.0;

        // Buy if price moved up more than threshold
        if (change_bps > threshold_bps_ && within_position_limit(100, true)) {
            sig.send_order = true;
            sig.is_buy     = true;
            sig.price      = quote.ask;   // lift the ask to buy immediately
            sig.qty        = 100;
            std::cout << "[Momentum] BUY signal: +" << change_bps << " bps\n";
        }
        // Sell if price moved down more than threshold
        else if (change_bps < -threshold_bps_ && within_position_limit(100, false)) {
            sig.send_order = true;
            sig.is_buy     = false;
            sig.price      = quote.bid;   // hit the bid to sell immediately
            sig.qty        = 100;
            std::cout << "[Momentum] SELL signal: " << change_bps << " bps\n";
        }

        prev_mid_ = mid;
        return sig;
    }

    void on_fill(const Fill& fill) override {
        record_fill(fill);   // use base class helper
        std::cout << "[Momentum] Fill: " << (fill.is_buy ? "BUY" : "SELL")
                  << " " << fill.qty << " @ $" << fill.price << "\n";
        print_status();
    }

    std::string description() const override {
        return "Momentum: buys on upward price movement, sells on reversal. "
               "Threshold: " + std::to_string(threshold_bps_) + " bps";
    }

private:
    double threshold_bps_;   // minimum price move in basis points to trigger signal
    double prev_mid_;
    int    ticks_seen_;
};

// ============================================================
// MEAN REVERSION STRATEGY — fades moves, bets on price returning
// ============================================================

class MeanReversionStrategy : public BaseStrategy {
public:
    MeanReversionStrategy(int max_position, int lookback, double entry_sigma)
        : BaseStrategy("MeanReversion", max_position)
        , lookback_(lookback)
        , entry_sigma_(entry_sigma)
        , sum_(0.0)
        , sum_sq_(0.0)
        , count_(0)
    {}

    Signal on_quote(const Quote& quote) override {
        Signal sig;
        double mid = quote.mid();

        // Rolling mean and standard deviation
        sum_    += mid;
        sum_sq_ += mid * mid;
        ++count_;

        if (count_ < lookback_) return sig;  // not enough data

        double n     = static_cast<double>(lookback_);
        double mean  = sum_ / n;
        double var   = (sum_sq_ / n) - (mean * mean);
        double sigma = (var > 0) ? std::sqrt(var) : 0.0;
        double z     = (sigma > 0) ? (mid - mean) / sigma : 0.0;

        // Buy when price is significantly BELOW the mean (expect reversion up)
        if (z < -entry_sigma_ && within_position_limit(100, true)) {
            sig.send_order = true;
            sig.is_buy     = true;
            sig.price      = quote.ask;
            sig.qty        = 100;
            std::cout << "[MeanRev] BUY signal: z=" << z << " (below mean)\n";
        }
        // Sell when price is significantly ABOVE the mean (expect reversion down)
        else if (z > entry_sigma_ && within_position_limit(100, false)) {
            sig.send_order = true;
            sig.is_buy     = false;
            sig.price      = quote.bid;
            sig.qty        = 100;
            std::cout << "[MeanRev] SELL signal: z=" << z << " (above mean)\n";
        }

        // Roll the window: subtract oldest value (simplified — real impl uses deque)
        if (count_ > lookback_) {
            // Simplified rolling: reset every window (real impl: proper sliding window)
            sum_    = mid;
            sum_sq_ = mid * mid;
            count_  = 1;
        }

        return sig;
    }

    void on_fill(const Fill& fill) override {
        record_fill(fill);
        std::cout << "[MeanRev] Fill: " << (fill.is_buy ? "BUY" : "SELL")
                  << " " << fill.qty << " @ $" << fill.price << "\n";
    }

    std::string description() const override {
        return "MeanReversion: buys dips, sells rips. "
               "Lookback: " + std::to_string(lookback_) + " ticks, "
               "Entry: " + std::to_string(entry_sigma_) + " sigma";
    }

private:
    int    lookback_;
    double entry_sigma_;
    double sum_, sum_sq_;
    int    count_;
};

// ============================================================
// STRATEGY RUNNER — works with ANY BaseStrategy via polymorphism
// ============================================================

// This function doesn't know WHICH strategy it's running —
// it just calls the interface. Swap strategies without changing this.
void run_strategy(BaseStrategy& strategy, const std::vector<Quote>& quotes) {
    std::cout << "\n=== Running: " << strategy.name() << " ===\n";
    std::cout << "Description: " << strategy.description() << "\n\n";

    uint64_t order_id = 1000;
    for (const auto& quote : quotes) {
        Signal sig = strategy.on_quote(quote);   // polymorphic call

        if (sig.send_order) {
            // Simulate an immediate fill (in reality: sent to exchange, fill comes back async)
            Fill fill{order_id++, sig.price, sig.qty, sig.is_buy};
            strategy.on_fill(fill);   // polymorphic call
        }
    }
    strategy.print_status();
}

int main() {

    // Simulated market data: small uptrend then a dip
    std::vector<Quote> market_data = {
        {"AAPL", 182.40, 182.50, 1},
        {"AAPL", 182.50, 182.60, 2},
        {"AAPL", 182.70, 182.80, 3},   // rising — momentum buy
        {"AAPL", 182.80, 182.90, 4},
        {"AAPL", 182.60, 182.70, 5},   // falling — momentum sell signal
        {"AAPL", 182.40, 182.50, 6},
        {"AAPL", 182.45, 182.55, 7},
    };

    // --- Run two completely different strategies on the same data ---
    MomentumStrategy    momentum(1000, 5.0);      // 5 bps threshold
    MeanReversionStrategy mean_rev(1000, 3, 1.0); // 3-tick lookback, 1 sigma entry

    run_strategy(momentum, market_data);
    run_strategy(mean_rev, market_data);

    // --- POLYMORPHISM via base pointer (swap at runtime) ---
    std::cout << "\n--- Polymorphism: strategy selected at runtime ---\n";

    std::vector<std::unique_ptr<BaseStrategy>> strategies;
    strategies.push_back(std::make_unique<MomentumStrategy>(500, 3.0));
    strategies.push_back(std::make_unique<MeanReversionStrategy>(500, 5, 1.5));

    for (auto& strat : strategies) {
        std::cout << "Strategy: " << strat->name() << "\n";
        std::cout << "  " << strat->description() << "\n";
        strat->on_quote(market_data[2]);  // polymorphic: calls the right on_quote
    }

    return 0;
    // Destructor of each unique_ptr calls the RIGHT derived destructor (virtual destructor)

    /*
      TRADING CONTEXT EXAMPLE:
      A live system where you can hot-swap strategies:

        BaseStrategy* active = new MomentumStrategy(1000, 5.0);
        active->on_quote(tick);  // runs momentum logic

        // Switch strategy mid-day without stopping the system
        delete active;
        active = new MeanReversionStrategy(1000, 10, 1.0);
        active->on_quote(tick);  // now runs mean reversion logic

      This is the power of polymorphism: the market data loop doesn't change,
      only the strategy object being pointed to changes.
    */
}
