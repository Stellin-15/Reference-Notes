// ============================================================
// L02: Arithmetic Operators and Escape Sequences
// ============================================================
// WHAT: How to do math in C++, operator precedence rules,
//       and special characters you can embed in strings.
// WHY (TRADING): Price arithmetic is the foundation of every
//   trading calculation: PnL, spread, slippage, fees, position
//   value. You need to know exactly how C++ evaluates math
//   expressions to avoid silent errors in calculations.
// PHASE: Foundation
// ============================================================

/*
  CONCEPT OVERVIEW — ARITHMETIC OPERATORS:

    +   Addition
    -   Subtraction
    *   Multiplication
    /   Division   (IMPORTANT: integer / integer = integer, truncates!)
    %   Modulo (remainder after division)
    ++  Increment by 1  (prefix ++x vs postfix x++)
    --  Decrement by 1

  OPERATOR PRECEDENCE (high to low — same as math):
    1. ()         parentheses — evaluated first
    2. ++ --      increment/decrement
    3. * / %      multiply, divide, modulo
    4. + -        add, subtract
    When in doubt, use parentheses — they cost nothing at runtime.

  INTEGER DIVISION TRAP:
    10 / 3  = 3   (NOT 3.333...)
    C++ drops the decimal when both operands are integers.
    This silently breaks price calculations if you use int for prices.

  TRADING USE CASE:
    spread = ask_price - bid_price
    pnl    = (exit_price - entry_price) * quantity
    fee    = trade_value * fee_rate
    mid    = (bid + ask) / 2.0   <-- must use 2.0 not 2 to avoid int division

  ESCAPE SEQUENCES (special characters inside strings):
    \n    Newline (go to next line)
    \t    Horizontal tab (align columns in log output)
    \\    Literal backslash character
    \"    Literal double-quote inside a string
    \r    Carriage return (Windows line endings)
    \0    Null terminator (end of a C-style string)

  COMMON MISTAKES:
    - int / int truncates: 7 / 2 = 3, not 3.5
    - Modulo on floats: use fmod() from <cmath>, not %
    - Confusing prefix (++x, evaluates AFTER increment)
      vs postfix (x++, evaluates BEFORE increment)
*/

#include <iostream>

int main() {

    // -------------------------------------------------------
    // BASIC ARITHMETIC
    // -------------------------------------------------------

    // Printing raw numbers and expressions directly
    std::cout << 3 << "\n";       // Just the number 3
    std::cout << 3 + 3 << "\n";   // 6 — addition
    std::cout << 2 * 5 << "\n";   // 10 — multiplication

    // -------------------------------------------------------
    // TRADING MATH: PnL and spread calculations
    // -------------------------------------------------------

    double bid_price  = 100.50;   // Best buy price in the market
    double ask_price  = 100.55;   // Best sell price in the market
    int    quantity   = 100;      // Number of shares/contracts

    // Spread: cost of crossing the market immediately
    double spread = ask_price - bid_price;
    std::cout << "Spread: " << spread << "\n";  // 0.05

    // Mid price: fair value estimate between bid and ask
    // NOTE: must divide by 2.0 (double), not 2 (int), to avoid truncation
    double mid = (bid_price + ask_price) / 2.0;
    std::cout << "Mid price: " << mid << "\n";  // 100.525

    // PnL: profit/loss on a position
    double entry_price = 100.50;
    double exit_price  = 101.00;
    double pnl = (exit_price - entry_price) * quantity;
    std::cout << "PnL: $" << pnl << "\n";  // $50.00

    // -------------------------------------------------------
    // INTEGER DIVISION TRAP — critical to understand
    // -------------------------------------------------------

    int a = 10;
    int b = 3;

    std::cout << a / b << "\n";          // 3 (NOT 3.33!) — integer division truncates
    std::cout << (double)a / b << "\n";  // 3.333... — cast one to double first

    // Modulo: gives the REMAINDER after division
    std::cout << 10 % 3 << "\n";   // 1 (because 10 = 3*3 + 1)
    std::cout << 100 % 8 << "\n";  // 4 — useful for fast array index wrap-around

    // -------------------------------------------------------
    // INCREMENT AND DECREMENT
    // -------------------------------------------------------

    int order_id = 1000;

    // Prefix ++: increments THEN returns the new value
    std::cout << ++order_id << "\n";   // 1001 (incremented before printing)

    // Postfix ++: returns the current value THEN increments
    std::cout << order_id++ << "\n";   // 1001 (printed old value, now order_id=1002)
    std::cout << order_id << "\n";     // 1002 (confirms the increment happened)

    // In loops, prefer prefix (++i) — avoids creating a temporary copy
    // In HFT order counters, this distinction can matter at high throughput

    // -------------------------------------------------------
    // ESCAPE SEQUENCES — formatting log output
    // -------------------------------------------------------

    // \n — newline
    std::cout << "Order filled\nNext line\n";

    // \t — tab: useful for aligning columns in trade logs
    std::cout << "Symbol\tPrice\tQty\tSide\n";
    std::cout << "AAPL\t182.50\t100\tBUY\n";
    std::cout << "TSLA\t245.10\t50\tSELL\n";

    // \\ — literal backslash (file paths on Windows)
    std::cout << "Log path: C:\\trading\\logs\\orders.log\n";

    // \" — literal double quote inside a string
    std::cout << "Status: \"FILLED\"\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      A basic PnL tracker for a day trading session:

        double realized_pnl = 0.0;
        double entry = 150.00;
        double exit  = 151.25;
        int    qty   = 200;
        double commission = 0.005 * qty;  // $0.005 per share

        realized_pnl = (exit - entry) * qty - commission;
        // = (1.25 * 200) - 1.0 = $250 - $1 = $249 profit

      This exact pattern — price delta * quantity - fees —
      is inside every position tracking system ever written.
    */
}
