// ============================================================
// L09: Functions — Declaration, Definition, Overloading, inline
// ============================================================
// WHAT: How to break code into reusable named units (functions),
//       how to pass data in and get results out, and performance
//       considerations around how arguments are passed.
// WHY (TRADING): A trading system is made of functions:
//   calculatePnL(), checkRiskLimits(), sendOrder(), parseMessage().
//   Choosing the wrong argument passing method (value vs reference)
//   causes unnecessary copies — at microsecond scale, that matters.
//   Function inlining eliminates call overhead on the hot path.
// PHASE: Foundation
// ============================================================

/*
  CONCEPT OVERVIEW:

  FUNCTION ANATOMY:
    return_type  function_name ( parameters ) {
        // body
        return value;
    }

  ARGUMENT PASSING MODES:
    Pass by VALUE    — a COPY is made; caller's original is unchanged
                       Use for: small cheap types (int, double, bool, char)
    Pass by REFERENCE — no copy; function operates on the original
                        Use for: large objects (structs, strings, vectors)
                        Mark const& if you don't need to modify it
    Pass by POINTER  — similar to reference but can be nullptr
                       Use when: argument might be absent (nullable)

  WHEN TO USE EACH IN TRADING:
    double calculate_pnl(int qty, double entry, double exit_p) — pass small types by value
    void update_book(OrderBook& book, const Message& msg)      — pass large objects by ref
    bool try_fill(Order* order)  — pointer when order might not exist (nullable)

  RETURN VALUE:
    Return by value for small types (int, double, bool)
    Return by value for structs too — compiler usually elides the copy (RVO)
    Return by reference ONLY if the referenced object outlives the function

  FUNCTION OVERLOADING:
    Multiple functions can share the same name if their parameters differ.
    The compiler picks the right one based on argument types at the call site.
    Used in trading for: generic log() that accepts int, double, or string

  INLINE FUNCTIONS:
    inline hint asks the compiler to paste the function body at the call site
    instead of making an actual function call (eliminates call overhead).
    In HFT, hot-path functions are often inlined:
      __attribute__((always_inline))  — force inline (GCC/Clang)
      [[msvc::forceinline]]           — force inline (MSVC)
    BUT: inlining large functions increases code size → more instruction cache misses

  DEFAULT PARAMETERS:
    Parameters can have defaults used when caller doesn't supply them.
    Useful for: optional logging verbosity, optional timeout values.

  TRADING USE CASE:
    inline double mid_price(double bid, double ask) { return (bid + ask) / 2.0; }
    int64_t to_ticks(double price, int64_t precision) { return (int64_t)(price * precision); }
    bool check_risk(const Order& order, int current_pos, int max_pos);

  COMMON MISTAKES:
    - Passing large structs by value accidentally — copies the whole struct
    - Returning a reference to a local variable — dangling reference (crash)
    - Forgetting const on reference params — misleads readers that you'll modify it
    - Over-using default parameters — makes call sites ambiguous
*/

#include <iostream>
#include <string>
#include <cstdint>
#include <cmath>

// -------------------------------------------------------
// FUNCTION DECLARATIONS (prototypes)
// Tell the compiler a function exists before it's defined below.
// In larger projects, these go in header (.h) files.
// -------------------------------------------------------

double calculate_pnl(int quantity, double entry_price, double exit_price);
bool   check_risk(int order_qty, int current_position, int max_position);
void   log_order(const std::string& symbol, int qty, double price, bool is_buy);
double mid_price(double bid, double ask);

// Overloaded: log() works with different types
void log(const std::string& msg);
void log(const std::string& label, double value);
void log(const std::string& label, int value);

// Inline: compiled directly at call site (no function call overhead)
inline int64_t to_ticks(double price, int64_t precision = 100) {
    return static_cast<int64_t>(price * precision);
}

// -------------------------------------------------------
// MAIN
// -------------------------------------------------------

int main() {

    // --- Pass by VALUE: small types ---
    double pnl = calculate_pnl(100, 182.50, 185.00);
    std::cout << "PnL: $" << pnl << "\n";   // $250.00

    // --- Risk check ---
    bool ok = check_risk(200, 500, 1000);
    std::cout << "Order accepted: " << (ok ? "YES" : "NO") << "\n";

    // --- Log order (passes string and doubles) ---
    log_order("AAPL", 100, 185.00, true);

    // --- Inline function: zero call overhead ---
    int64_t ticks = to_ticks(100.55);         // uses default precision=100
    int64_t ticks2 = to_ticks(100.55, 1000);  // explicit precision
    std::cout << "100.55 in ticks (100): " << ticks  << "\n";   // 10055
    std::cout << "100.55 in ticks (1000):" << ticks2 << "\n";   // 100550

    // --- Function overloading ---
    log("System ready");
    log("Best bid", 100.50);
    log("Position", 500);

    // --- Mid price ---
    double mid = mid_price(100.50, 100.55);
    std::cout << "Mid: $" << mid << "\n";  // 100.525

    return 0;
}

// -------------------------------------------------------
// FUNCTION DEFINITIONS
// -------------------------------------------------------

// Pass small types (int, double) by value — cheap to copy
// Return double by value — compiler will likely inline/optimize this
double calculate_pnl(int quantity, double entry_price, double exit_price) {
    // PnL = (exit - entry) * quantity
    // Positive = profit, Negative = loss
    return (exit_price - entry_price) * quantity;
}

// Pass int by value (cheap), return bool by value
bool check_risk(int order_qty, int current_position, int max_position) {
    // Would the new order push us over the limit?
    if (current_position + order_qty > max_position) {
        std::cout << "[RISK] Rejected: " << (current_position + order_qty)
                  << " would exceed max " << max_position << "\n";
        return false;
    }
    return true;
}

// Pass std::string by const reference — avoids copying the string
// (std::string can be 24+ bytes; always pass it by reference)
void log_order(const std::string& symbol, int qty, double price, bool is_buy) {
    std::cout << "[ORDER] " << symbol
              << (is_buy ? " BUY " : " SELL ")
              << qty << " @ $" << price << "\n";
}

// Tiny function — perfect candidate for inlining
// Compiler will likely inline this even without inline keyword
double mid_price(double bid, double ask) {
    return (bid + ask) / 2.0;
}

// OVERLOADED LOG FUNCTIONS — same name, different parameter types
void log(const std::string& msg) {
    std::cout << "[LOG] " << msg << "\n";
}

void log(const std::string& label, double value) {
    std::cout << "[LOG] " << label << " = " << value << "\n";
}

void log(const std::string& label, int value) {
    std::cout << "[LOG] " << label << " = " << value << "\n";
}

/*
  TRADING CONTEXT EXAMPLE:
  A hot-path tick handler function — every performance decision matters:

    // Force inline: no call overhead on the hot path
    __attribute__((always_inline))
    inline void on_tick(const Quote& quote, OrderBook& book, Strategy& strat) {
        book.update(quote);           // update book by reference (no copy)
        auto signal = strat.evaluate(book);  // evaluate returns small struct by value
        if (signal.send) {
            gateway.send(signal.order);  // pass order by value (it's small)
        }
    }

  Note:
  - book and strat are references (large, no copy)
  - signal is returned by value (small struct, compiler elides copy)
  - The whole function is marked always_inline to eliminate call overhead
  This is the real HFT pattern for hot-path functions.
*/
