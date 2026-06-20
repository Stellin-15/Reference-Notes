// ============================================================
// L03: Variables and Data Types
// ============================================================
// WHAT: The fundamental types C++ provides, how to declare
//       variables, and the memory size of each type.
// WHY (TRADING): Choosing the WRONG type for a price or
//   quantity can silently corrupt your calculations. HFT
//   code uses specific types for every field — never
//   "just use int" without thinking. This lesson covers
//   what to use and WHY for each trading concept.
// PHASE: Foundation
// ============================================================

/*
  CONCEPT OVERVIEW — PRIMITIVE TYPES:

    int       — whole number, usually 32-bit, range ~±2 billion
    long      — at least 32-bit (64-bit on most 64-bit systems)
    long long — guaranteed 64-bit, range ~±9.2 quintillion
    double    — 64-bit floating point, ~15 decimal digits of precision
    float     — 32-bit floating point, ~7 decimal digits (AVOID in trading)
    char      — single character, 1 byte, ASCII value 0-127
    bool      — true or false, 1 byte
    string    — text (not a primitive — it's a class from <string>)

  FIXED-WIDTH TYPES (from <cstdint>) — USE THESE IN TRADING CODE:
    int8_t    — exactly  8 bits, signed  (-128 to 127)
    uint8_t   — exactly  8 bits, unsigned (0 to 255)
    int16_t   — exactly 16 bits, signed
    uint16_t  — exactly 16 bits, unsigned
    int32_t   — exactly 32 bits, signed  (~±2 billion)
    uint32_t  — exactly 32 bits, unsigned (~4 billion)
    int64_t   — exactly 64 bits, signed  — USE FOR PRICES IN TICKS
    uint64_t  — exactly 64 bits, unsigned — USE FOR ORDER IDs, TIMESTAMPS

  WHY FIXED-WIDTH? The size of plain "int" can change between compilers
  and platforms. In trading, your message structs must match the exchange's
  binary format exactly — so you MUST use fixed-width types.

  PRICES IN HFT — NEVER USE double:
    double has rounding errors: 0.1 + 0.2 = 0.30000000000000004
    Instead, store price as integer ticks:
      $100.05 with tick size 0.01 = 10005 ticks (stored as int64_t)
    Then convert to display price only when printing.
    This is what real exchange protocols (CME, ITCH) do.

  sizeof() OPERATOR:
    Returns the size in BYTES of a type or variable.
    Critical for: struct layout, network message parsing, memory pools.

  TRADING USE CASE:
    struct Order {
        uint64_t order_id;    // 8 bytes — unique ID, never overflows
        int64_t  price;       // 8 bytes — price in ticks, not dollars
        int32_t  quantity;    // 4 bytes — number of shares/contracts
        uint8_t  side;        // 1 byte  — 0=BUY, 1=SELL
        uint8_t  order_type;  // 1 byte  — 0=LIMIT, 1=MARKET, etc.
    };  // Total: 22 bytes (may be padded to 24 — see L43 on alignment)

  COMMON MISTAKES:
    - Using double for prices → floating point rounding errors
    - Using int when you need int64_t → overflow on large prices/quantities
    - Using float instead of double → only 7 digits of precision
    - Declaring a variable twice in the same scope → compiler error
*/

#include <iostream>
#include <string>    // Required for std::string
#include <cstdint>   // Required for int64_t, uint64_t, etc. (fixed-width types)

int main() {

    // -------------------------------------------------------
    // BASIC TYPES — what they store and their size
    // -------------------------------------------------------

    int    myInt    = 5;              // Whole number — 4 bytes typically
    double myDouble = 5.99;           // Decimal number, 64-bit — 8 bytes
    float  myFloat  = 5.99f;          // Decimal, 32-bit (less precise) — 4 bytes
    char   myChar   = 'D';            // Single character in single quotes — 1 byte
    std::string myText = "Hello";     // Text — variable size, heap-allocated
    bool   myBool   = true;           // true or false — 1 byte

    std::cout << "int:    " << myInt    << "  (" << sizeof(myInt)    << " bytes)\n";
    std::cout << "double: " << myDouble << "  (" << sizeof(myDouble)  << " bytes)\n";
    std::cout << "float:  " << myFloat  << "  (" << sizeof(myFloat)   << " bytes)\n";
    std::cout << "char:   " << myChar   << "  (" << sizeof(myChar)    << " bytes)\n";
    std::cout << "bool:   " << myBool   << "  (" << sizeof(myBool)    << " bytes)\n";
    // Note: sizeof(string) gives the size of the string OBJECT, not the text length

    // -------------------------------------------------------
    // FIXED-WIDTH TYPES — what trading code actually uses
    // -------------------------------------------------------

    uint64_t order_id   = 1000000001ULL; // Order ID — never negative, needs 64 bits
    int64_t  price_ticks = 10005LL;      // $100.05 stored as 10005 ticks (tick=0.01)
    int32_t  quantity    = 500;          // Number of shares — signed (can be negative for short)
    uint8_t  side        = 0;            // 0 = BUY, 1 = SELL — fits in 1 byte
    uint8_t  order_type  = 0;            // 0 = LIMIT, 1 = MARKET, 2 = IOC, etc.

    std::cout << "\n--- Trading Types ---\n";
    std::cout << "Order ID:     " << order_id    << "  (" << sizeof(order_id)    << " bytes)\n";
    std::cout << "Price ticks:  " << price_ticks << "  (" << sizeof(price_ticks) << " bytes)\n";
    std::cout << "Quantity:     " << quantity     << "  (" << sizeof(quantity)    << " bytes)\n";
    std::cout << "Side:         " << (int)side    << "  (" << sizeof(side)        << " byte)\n";

    // Convert ticks back to display price (only for printing, never for math)
    double display_price = price_ticks / 100.0;  // 10005 / 100.0 = 100.05
    std::cout << "Display price: $" << display_price << "\n";

    // -------------------------------------------------------
    // FLOATING POINT ROUNDING — why NOT to use double for prices
    // -------------------------------------------------------

    double a = 0.1;
    double b = 0.2;
    std::cout << "\n0.1 + 0.2 = " << (a + b) << "\n";  // NOT 0.3 exactly!
    // This is why HFT uses integer ticks for prices.
    // Even a tiny rounding error, multiplied across millions of trades,
    // produces incorrect PnL and risk calculations.

    // -------------------------------------------------------
    // sizeof() — memory size matters for struct layout and protocols
    // -------------------------------------------------------

    std::cout << "\n--- sizeof() for all types ---\n";
    std::cout << "int8_t:   " << sizeof(int8_t)   << " byte\n";
    std::cout << "int16_t:  " << sizeof(int16_t)  << " bytes\n";
    std::cout << "int32_t:  " << sizeof(int32_t)  << " bytes\n";
    std::cout << "int64_t:  " << sizeof(int64_t)  << " bytes\n";
    std::cout << "uint64_t: " << sizeof(uint64_t) << " bytes\n";
    std::cout << "double:   " << sizeof(double)   << " bytes\n";
    std::cout << "float:    " << sizeof(float)    << " bytes\n";
    std::cout << "char:     " << sizeof(char)     << " byte\n";
    std::cout << "bool:     " << sizeof(bool)     << " byte\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      CME Group's MDP3 binary market data protocol encodes prices as:
        int64_t Price9 — price with 9 decimal places of precision
        e.g., $100.05 = 100050000000 (100.05 * 10^9)

      This is the industry standard: always integers, never floats,
      with a known scale factor. Your code must match this exactly
      when parsing exchange messages.
    */
}
