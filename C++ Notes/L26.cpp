// ============================================================
// L26: Lambdas and std::function
// ============================================================
// WHAT: Lambdas are anonymous inline functions you define at
//       the point of use. std::function is a type-erased wrapper
//       that can hold any callable (lambda, function ptr, functor).
// WHY (TRADING): Lambdas are the modern replacement for verbose
//   functor classes. They're used for: filtering positions,
//   sorting orders, defining strategy callbacks, capturing
//   context for risk checks, and building event handlers.
//   std::function adds flexibility but has overhead — prefer
//   raw function pointers or templates in hot paths.
// PHASE: Modern C++
// ============================================================

/*
  CONCEPT OVERVIEW:

  LAMBDA SYNTAX:
    [capture](parameters) -> return_type { body }

    [capture]   — what from the enclosing scope is visible inside the lambda
    (parameters)— same as function parameters
    -> type     — return type (usually omitted — compiler deduces it)
    { body }    — the function body

  CAPTURE MODES:
    []           — capture nothing (only use global/static vars)
    [=]          — capture ALL locals by VALUE (copy at lambda creation time)
    [&]          — capture ALL locals by REFERENCE (direct access, no copy)
    [x]          — capture only x by value
    [&x]         — capture only x by reference
    [x, &y]      — x by value, y by reference (be explicit — prefer this)
    [this]       — capture the current object (for member lambdas)
    [=, &x]      — everything by value EXCEPT x (by ref)

  CAPTURE BY VALUE vs BY REFERENCE:
    By value [x]:  lambda gets its own COPY of x at creation time.
                   x can change later without affecting the lambda.
                   Safe to store and call later (no dangling reference).
    By reference [&x]:  lambda accesses the ORIGINAL x directly.
                   Fast (no copy), but DANGEROUS if lambda outlives x.
                   Only safe for lambdas that are used immediately.

  MUTABLE LAMBDAS:
    [x]() mutable { x++; }   — allows modifying captured-by-value copies
    (x is the lambda's private copy — doesn't affect the original)

  STD::FUNCTION:
    std::function<ReturnType(Args...)>
    Type-erased callable: can hold ANY callable with matching signature.
    OVERHEAD: ~50-200ns per call due to virtual dispatch + possible heap alloc.
    Use for: callback registries, strategy event handlers, plugin systems.
    AVOID IN HOT PATH: use raw function pointers or templates there.

  GENERIC LAMBDAS (C++14):
    [](auto x, auto y) { return x + y; }
    The 'auto' parameters make it a template — works for any type.

  IMMEDIATELY INVOKED LAMBDAS:
    int x = [&]() { return compute_something(); }();  // () at end invokes it
    Useful for complex initialization that doesn't fit in a simple expression.

  TRADING USE CASE:
    // Filter: find all positions exceeding a threshold
    auto over_limit = [max_pos](const Position& p) {
        return std::abs(p.net_qty) > max_pos;
    };
    auto it = std::find_if(positions.begin(), positions.end(), over_limit);

    // Sort: order the book by price then time
    std::sort(orders.begin(), orders.end(),
        [](const Order& a, const Order& b) {
            return a.price != b.price ? a.price > b.price : a.timestamp < b.timestamp;
        });

    // Callback: register a fill handler on the gateway
    gateway.on_fill([&risk, &book](const Fill& f) {
        risk.update(f);
        book.apply(f);
    });

  COMMON MISTAKES:
    - Capturing local by reference [&] in a lambda stored for later use
      — the local may be destroyed before the lambda is called (dangling ref)
    - Using std::function in a tight loop — the overhead accumulates
    - Forgetting mutable when you need to modify a captured-by-value var
    - [=] capturing 'this' in a method lambda (implicit this capture, C++20 deprecated)
*/

#include <iostream>
#include <functional>   // std::function
#include <vector>
#include <algorithm>    // std::sort, std::find_if, std::for_each
#include <string>
#include <cstdint>
#include <cmath>        // std::abs
#include <numeric>      // std::accumulate

// ============================================================
// TRADING TYPES
// ============================================================

struct Order {
    uint64_t    id;
    double      price;
    int32_t     qty;
    bool        is_buy;
    uint64_t    timestamp_ns;
    std::string symbol;
};

struct Position {
    std::string symbol;
    int64_t     net_qty;
    double      avg_cost;
    double      unrealized_pnl;
};

struct Fill {
    uint64_t order_id;
    double   price;
    int32_t  qty;
    bool     is_buy;
};

// ============================================================
// EVENT SYSTEM — uses std::function for callbacks
// ============================================================

class Gateway {
public:
    using FillCallback   = std::function<void(const Fill&)>;
    using RejectCallback = std::function<void(uint64_t order_id, const std::string& reason)>;

    // Register a callback to be called on every fill
    void on_fill(FillCallback cb)   { fill_callbacks_.push_back(std::move(cb)); }
    void on_reject(RejectCallback cb) { reject_callbacks_.push_back(std::move(cb)); }

    // Simulate receiving a fill from the exchange
    void simulate_fill(const Fill& f) {
        std::cout << "[Gateway] Received fill: " << (f.is_buy ? "BUY" : "SELL")
                  << " " << f.qty << " @ $" << f.price << "\n";
        for (auto& cb : fill_callbacks_) cb(f);  // invoke all registered callbacks
    }

    void simulate_reject(uint64_t id, const std::string& reason) {
        std::cout << "[Gateway] Order #" << id << " rejected: " << reason << "\n";
        for (auto& cb : reject_callbacks_) cb(id, reason);
    }

private:
    std::vector<FillCallback>   fill_callbacks_;
    std::vector<RejectCallback> reject_callbacks_;
};

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // BASIC LAMBDA SYNTAX
    // -------------------------------------------------------

    std::cout << "=== Basic lambdas ===\n";

    // No capture: just a function
    auto add = [](double a, double b) { return a + b; };
    std::cout << "182.50 + 0.05 = " << add(182.50, 0.05) << "\n";

    // Explicit return type
    auto to_ticks = [](double price) -> int64_t {
        return static_cast<int64_t>(price * 10000);
    };
    std::cout << "$182.5500 in ticks: " << to_ticks(182.5500) << "\n";

    // Immediately invoked lambda (IIFE): useful for complex initialization
    const double spread = [&]() {
        double bid = 182.50, ask = 182.55;
        return ask - bid;
    }();   // () at end calls it immediately
    std::cout << "Spread: $" << spread << "\n";

    // -------------------------------------------------------
    // CAPTURE BY VALUE vs BY REFERENCE
    // -------------------------------------------------------

    std::cout << "\n=== Capture modes ===\n";

    double risk_limit = 10000.0;
    int    max_qty    = 1000;

    // Capture by value [risk_limit]: lambda gets its own copy
    auto check_value = [risk_limit](double notional) -> bool {
        return notional <= risk_limit;   // uses the COPY taken at lambda creation
    };

    risk_limit = 99999.0;   // change original — lambda still uses old value 10000
    std::cout << "Notional 9500 OK? " << check_value(9500.0) << "\n";    // true (vs 10000 copy)
    std::cout << "Notional 11000 OK? " << check_value(11000.0) << "\n";  // false

    // Capture by reference [&max_qty]: lambda sees the original
    auto check_qty = [&max_qty](int qty) -> bool {
        return qty <= max_qty;   // references the ORIGINAL max_qty
    };

    max_qty = 500;  // change original — lambda sees the new value
    std::cout << "Qty 400 OK? " << check_qty(400) << "\n";  // true (vs new 500)
    std::cout << "Qty 600 OK? " << check_qty(600) << "\n";  // false

    // -------------------------------------------------------
    // LAMBDAS AS PREDICATES — STL algorithms
    // -------------------------------------------------------

    std::cout << "\n=== Lambdas with STL algorithms ===\n";

    std::vector<Position> portfolio = {
        {"AAPL",  500,  182.50,  1250.0},
        {"TSLA", -200,  245.00, -600.0},
        {"MSFT",  1500, 420.00,  4500.0},
        {"NVDA", -100,  800.00, -300.0},
        {"AMZN",  50,   185.00,  125.0},
    };

    // Sort by unrealized PnL descending (best first)
    std::sort(portfolio.begin(), portfolio.end(),
        [](const Position& a, const Position& b) {
            return a.unrealized_pnl > b.unrealized_pnl;  // descending
        });

    std::cout << "Portfolio sorted by unrealized PnL:\n";
    for (const auto& p : portfolio) {
        std::cout << "  " << p.symbol << ": qty=" << p.net_qty
                  << " PnL=$" << p.unrealized_pnl << "\n";
    }

    // Find positions exceeding size limit (500 shares either direction)
    constexpr int64_t SIZE_LIMIT = 400;
    auto it = std::find_if(portfolio.begin(), portfolio.end(),
        [](const Position& p) {
            return std::abs(p.net_qty) > SIZE_LIMIT;
        });

    if (it != portfolio.end()) {
        std::cout << "\nFirst oversized position: " << it->symbol
                  << " (" << it->net_qty << " shares)\n";
    }

    // Total PnL: sum with accumulate + lambda
    double total_pnl = std::accumulate(portfolio.begin(), portfolio.end(), 0.0,
        [](double sum, const Position& p) {
            return sum + p.unrealized_pnl;
        });
    std::cout << "Total portfolio PnL: $" << total_pnl << "\n";

    // Filter and count: how many positions are profitable?
    int profitable = 0;
    std::for_each(portfolio.begin(), portfolio.end(),
        [&profitable](const Position& p) {
            if (p.unrealized_pnl > 0) ++profitable;
        });
    std::cout << "Profitable positions: " << profitable << "/" << portfolio.size() << "\n";

    // -------------------------------------------------------
    // LAMBDAS AS SORT COMPARATORS FOR ORDERS
    // -------------------------------------------------------

    std::cout << "\n=== Order book sorting ===\n";

    std::vector<Order> buy_orders = {
        {1001, 182.50, 100, true, 1000, "AAPL"},
        {1002, 182.55, 200, true, 1001, "AAPL"},  // higher price = better bid
        {1003, 182.50, 150, true,  999, "AAPL"},  // same price, earlier = better
        {1004, 182.45, 300, true,  998, "AAPL"},  // lowest price = worst
    };

    // Sort bids: price descending, then timestamp ascending (FIFO)
    std::sort(buy_orders.begin(), buy_orders.end(),
        [](const Order& a, const Order& b) -> bool {
            if (a.price != b.price) return a.price > b.price;   // higher = better
            return a.timestamp_ns < b.timestamp_ns;              // earlier = better
        });

    std::cout << "Buy orders (best first):\n";
    for (const auto& o : buy_orders) {
        std::cout << "  #" << o.id << " @ $" << o.price
                  << " qty=" << o.qty << " ts=" << o.timestamp_ns << "\n";
    }

    // -------------------------------------------------------
    // MUTABLE LAMBDA
    // -------------------------------------------------------

    std::cout << "\n=== Mutable lambda (stateful counter) ===\n";

    // Mutable: can modify captured-by-value copies
    // This lambda maintains its OWN internal counter
    int initial_seq = 1000000;
    auto next_order_id = [seq = initial_seq]() mutable -> uint64_t {
        return ++seq;   // modifies the lambda's private copy of seq
    };
    // initial_seq is unaffected — lambda has its own copy
    std::cout << "Order ID 1: " << next_order_id() << "\n";  // 1000001
    std::cout << "Order ID 2: " << next_order_id() << "\n";  // 1000002
    std::cout << "Order ID 3: " << next_order_id() << "\n";  // 1000003
    std::cout << "initial_seq unchanged: " << initial_seq << "\n";

    // -------------------------------------------------------
    // GENERIC LAMBDA (C++14)
    // -------------------------------------------------------

    std::cout << "\n=== Generic lambda (auto params) ===\n";

    // Works for int, double, int64_t — any type with operator-
    auto calc_spread = [](auto bid, auto ask) {
        return ask - bid;
    };

    std::cout << "Double spread: $" << calc_spread(182.50, 182.55) << "\n";
    std::cout << "Int spread:     " << calc_spread(18250, 18255) << " ticks\n";
    std::cout << "int64 spread:   " << calc_spread(1825000LL, 1825500LL) << " ticks\n";

    // -------------------------------------------------------
    // STD::FUNCTION + GATEWAY CALLBACKS
    // -------------------------------------------------------

    std::cout << "\n=== std::function callbacks ===\n";

    Gateway gateway;

    double position_pnl = 0.0;
    int    fill_count   = 0;

    // Register fill handler via lambda — captures position_pnl by reference
    gateway.on_fill([&position_pnl, &fill_count](const Fill& f) {
        double trade_pnl = f.price * f.qty * (f.is_buy ? -1 : 1);
        position_pnl += trade_pnl;
        ++fill_count;
        std::cout << "[FillHandler] fill #" << fill_count
                  << " trade_pnl=$" << trade_pnl
                  << " cumulative=$" << position_pnl << "\n";
    });

    // Register reject handler
    gateway.on_reject([](uint64_t id, const std::string& reason) {
        std::cout << "[RejectHandler] Order #" << id << " rejected: " << reason << "\n";
    });

    // Simulate exchange events
    gateway.simulate_fill({1001, 182.55, 100, true});    // buy: PnL -= price * qty
    gateway.simulate_fill({1002, 183.00,  50, false});   // sell: PnL += price * qty
    gateway.simulate_reject(1003, "Exceeds position limit");

    // -------------------------------------------------------
    // PERFORMANCE NOTE: std::function vs template
    // -------------------------------------------------------

    std::cout << "\n=== std::function overhead note ===\n";

    // std::function has overhead: virtual dispatch, possible heap allocation
    // For hot paths, prefer:
    //   1. Direct lambda with template parameter (zero overhead)
    //   2. Raw function pointer (zero overhead)
    //   3. std::function ONLY on slow path (event registration, callbacks)

    // Template: lambda type deduced, compiler inlines everything — zero overhead
    auto hot_path_fn = [](double bid, double ask) { return (bid + ask) / 2.0; };

    // This template call is completely inlined — as fast as writing the expression inline
    auto apply_hot = [&hot_path_fn](double b, double a) {
        return hot_path_fn(b, a);
    };
    std::cout << "Mid via template lambda: $" << apply_hot(182.50, 182.55) << "\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      A complete order filtering and routing pipeline using lambdas:

        // Build a pipeline of checks as lambdas
        auto is_limit_order   = [](const Order& o) { return o.type == OrderType::LIMIT; };
        auto within_size      = [max](const Order& o) { return o.qty <= max; };
        auto has_valid_price  = [](const Order& o) { return o.price > 0.0; };

        // Combine checks into one predicate (all must pass)
        auto risk_check = [&](const Order& o) {
            return is_limit_order(o) && within_size(o) && has_valid_price(o);
        };

        // Apply to incoming orders
        for (auto& order : pending_orders) {
            if (risk_check(order)) {
                route_to_exchange(order);
            } else {
                reject(order, "Risk check failed");
            }
        }

        // Sort the remaining queue by price priority
        std::sort(pending_orders.begin(), pending_orders.end(),
            [](const Order& a, const Order& b) {
                return a.is_buy ? a.price > b.price : a.price < b.price;
            });
    */
}
