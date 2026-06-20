// ============================================================
// L04: const, auto, and Type Conversion/Casting
// ============================================================
// WHAT: How to make variables immutable (const), let the
//       compiler deduce types (auto), and convert between types.
// WHY (TRADING): Trading systems rely on constants for config
//   (tick sizes, lot sizes, risk limits). Type safety prevents
//   silent data corruption between integer and floating point
//   representations. Casting is used constantly when parsing
//   raw exchange message bytes.
// PHASE: Foundation
// ============================================================

/*
  CONCEPT OVERVIEW:

  CONST:
    const T x = value;   — x cannot be changed after this line
    If you try: x = 5;   — compiler error. This is GOOD — forces
    you to be explicit about what should and shouldn't change.
    In trading: tick sizes, lot sizes, fee rates, max position
    limits should ALL be const — they come from config and never
    change during a trading session.

  CONSTEXPR:
    constexpr T x = value;   — evaluated at COMPILE TIME, not runtime
    Even faster than const. Use for values known before the program runs.
    The compiler can embed the value directly in machine code.
    In trading: compile-time constants for message field offsets,
    protocol version numbers, price precision constants.

  AUTO:
    Lets the compiler figure out the type from the right-hand side.
    auto x = 5;       // x is int
    auto y = 5.0;     // y is double
    auto z = 5.0f;    // z is float
    Pro: less typing, especially for complex iterator types
    Con: can hide the type — in HFT code, be explicit when it matters
    Rule: use auto for complex/verbose types (iterators, lambdas),
    be explicit for primitives where the type has trading significance.

  TYPE CONVERSION:
    IMPLICIT (automatic, can be dangerous):
      int x = 5;
      double y = x;  // OK: int promoted to double (no data loss)
      int z = 5.9;   // DANGER: double truncated to int → z=5, not 6!

    EXPLICIT CASTS (always prefer these):
      static_cast<T>(x)      — safe, checked by compiler
      reinterpret_cast<T>(x) — raw bit reinterpretation (dangerous but used in HFT
                               for parsing binary protocol bytes)
      (T)x                   — C-style cast (avoid — bypasses compiler checks)

  INTEGER OVERFLOW:
    int32_t can hold up to ~2.1 billion.
    In trading: if price * quantity > 2.1B, you silently wrap to negative!
    Always use int64_t for values that could grow large.
    Example: 10,000 contracts at $500 = $5,000,000 — fits in int32_t fine.
             10,000 contracts at $500,000 (e.g., futures) = $5B — OVERFLOWS!

  TRADING USE CASE:
    constexpr int64_t TICK_SIZE       = 1;      // 1 cent minimum move
    constexpr int32_t MAX_ORDER_SIZE  = 10000;  // risk limit
    constexpr double  FEE_RATE        = 0.0003; // 0.03% maker fee
    const std::string EXCHANGE        = "CME";

  COMMON MISTAKES:
    - Assigning double to int without cast — silently truncates
    - Using int for position * price product — integer overflow
    - Forgetting constexpr doesn't work with values computed at runtime
*/

#include <iostream>
#include <string>
#include <cstdint>

int main() {

    // -------------------------------------------------------
    // CONST — values that must not change
    // -------------------------------------------------------

    const double TICK_SIZE  = 0.01;    // Minimum price increment (e.g., 1 cent)
    const int    LOT_SIZE   = 100;     // Minimum order size in shares
    const double FEE_RATE   = 0.0003;  // 0.03% per trade (maker fee, CME-style)

    std::cout << "Tick size: " << TICK_SIZE << "\n";
    std::cout << "Lot size:  " << LOT_SIZE  << "\n";
    std::cout << "Fee rate:  " << FEE_RATE  << "\n";

    // This would be a COMPILER ERROR — const cannot be reassigned:
    // TICK_SIZE = 0.05;  // error: assignment of read-only variable

    // -------------------------------------------------------
    // CONSTEXPR — evaluated at compile time
    // -------------------------------------------------------

    // These values are baked directly into the machine code at compile time.
    // Zero runtime cost — the CPU never has to load them from memory.
    constexpr int64_t PRICE_PRECISION  = 100;      // Ticks per dollar (0.01 tick)
    constexpr int32_t MAX_POSITION     = 50000;    // Max shares per symbol
    constexpr int32_t MAX_ORDER_QTY    = 10000;    // Max single order size

    std::cout << "\nMax position:  " << MAX_POSITION  << "\n";
    std::cout << "Max order qty: " << MAX_ORDER_QTY << "\n";

    // constexpr function: runs at compile time if all inputs are constexpr
    // (covered fully in L25 — just know the concept now)

    // -------------------------------------------------------
    // AUTO — type deduction
    // -------------------------------------------------------

    auto price   = 100.50;          // compiler deduces double
    auto qty     = 500;             // compiler deduces int
    auto symbol  = std::string("AAPL"); // std::string

    // Where auto is most useful: avoiding verbose type names
    // e.g., instead of: std::map<std::string, double>::iterator it = ...
    // you write:        auto it = ...
    // (More on this when we get to containers in L27)

    std::cout << "\nAuto examples:\n";
    std::cout << "price:  " << price  << " (double)\n";
    std::cout << "qty:    " << qty    << " (int)\n";
    std::cout << "symbol: " << symbol << " (string)\n";

    // -------------------------------------------------------
    // IMPLICIT CONVERSION — the dangerous kind
    // -------------------------------------------------------

    double exact_price  = 100.99;
    int    truncated    = exact_price;   // 100.99 → 100 (drops .99 silently!)
    std::cout << "\nImplicit truncation: " << exact_price << " → " << truncated << "\n";

    int    fill_qty   = 7;
    int    total_lots = 3;
    double ratio      = fill_qty / total_lots; // INTEGER division! 7/3=2, not 2.333
    std::cout << "Integer division danger: 7/3 = " << ratio << "\n";  // Prints 2.0

    // Fix: cast at least one operand to double
    double correct_ratio = (double)fill_qty / total_lots;
    std::cout << "Correct: 7.0/3 = " << correct_ratio << "\n";  // 2.333...

    // -------------------------------------------------------
    // EXPLICIT CASTS — the safe way to convert
    // -------------------------------------------------------

    // static_cast: safe, compile-time checked
    int64_t price_ticks = 10099LL;                           // 100.99 in ticks
    double  display     = static_cast<double>(price_ticks) / 100.0;  // back to dollars
    std::cout << "\nstatic_cast: " << price_ticks << " ticks = $" << display << "\n";

    // reinterpret_cast: raw bit-level reinterpretation
    // Used in HFT to read raw network bytes as a struct without copying
    // EXAMPLE (conceptual — real use is with byte buffers from the network):
    uint32_t raw_bytes = 0x42C80000;  // Raw IEEE 754 float bytes for 100.0
    float*   as_float  = reinterpret_cast<float*>(&raw_bytes);
    std::cout << "reinterpret_cast float: " << *as_float << "\n";  // 100.0

    // -------------------------------------------------------
    // INTEGER OVERFLOW — silent killer in trading
    // -------------------------------------------------------

    int32_t big_price = 2'000'000;       // $2,000,000 (e.g., S&P futures contract value)
    int32_t contracts = 2000;

    // OVERFLOW: 2,000,000 * 2,000 = 4,000,000,000 which exceeds int32_t max (2.1B)
    int32_t bad_notional  = big_price * contracts;   // SILENTLY WRAPS TO NEGATIVE!
    int64_t good_notional = (int64_t)big_price * contracts;  // Correct: 4B fits in 64-bit

    std::cout << "\nOverflow demo:\n";
    std::cout << "int32 overflow:  " << bad_notional  << " (WRONG — negative!)\n";
    std::cout << "int64 correct:   " << good_notional << " (RIGHT)\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      A real risk check for max notional value:

        constexpr int64_t MAX_NOTIONAL = 10'000'000LL; // $10M limit

        int64_t order_notional = static_cast<int64_t>(price_ticks) * quantity / PRICE_PRECISION;

        if (order_notional > MAX_NOTIONAL) {
            std::cout << "[RISK] Order rejected: notional " << order_notional
                      << " exceeds limit " << MAX_NOTIONAL << "\n";
            return 1; // reject
        }

      Notice: int64_t everywhere, constexpr for the limit, static_cast before multiply.
      This is the real pattern.
    */
}
