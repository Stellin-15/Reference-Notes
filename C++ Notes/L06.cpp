// ============================================================
// L06: All Operators — Arithmetic, Comparison, Logical, Bitwise
// ============================================================
// WHAT: Complete reference for every type of operator in C++.
//       Special focus on bitwise operators — critical in HFT.
// WHY (TRADING): Bitwise operations are used everywhere in trading:
//   packing order flags into a single byte, fast modulo for ring
//   buffers, masking message type fields, and implementing lock-free
//   data structures. They run in a single CPU instruction.
// PHASE: Foundation
// ============================================================

/*
  CONCEPT OVERVIEW:

  ARITHMETIC OPERATORS: (covered in L02)
    +  -  *  /  %  ++  --

  COMPARISON OPERATORS (return bool: true or false):
    ==   Equal to
    !=   Not equal to
    <    Less than
    >    Greater than
    <=   Less than or equal
    >=   Greater than or equal

  LOGICAL OPERATORS (combine bool conditions):
    &&   AND — both must be true
    ||   OR  — at least one must be true
    !    NOT — inverts the bool

    SHORT-CIRCUIT EVALUATION:
      A && B: if A is false, B is NOT evaluated (skipped)
      A || B: if A is true,  B is NOT evaluated (skipped)
      This matters in trading: put the cheapest check FIRST to avoid
      evaluating expensive checks when unnecessary.

  ASSIGNMENT OPERATORS (shortcuts):
    +=  -=  *=  /=  %=  &=  |=  ^=  <<=  >>=

  BITWISE OPERATORS (operate on individual BITS, not the whole value):
    &    AND   — bit is 1 only if BOTH bits are 1
    |    OR    — bit is 1 if EITHER bit is 1
    ^    XOR   — bit is 1 if bits are DIFFERENT
    ~    NOT   — flips all bits (bitwise complement)
    <<   Left shift  — shift bits left (multiply by 2 per shift)
    >>   Right shift — shift bits right (divide by 2 per shift)

  BITWISE TRICKS (used constantly in HFT):
    x & (x-1)       — check if x is a power of 2 (result 0 = yes)
    x & (N-1)       — fast modulo when N is power of 2 (x % N without division)
    x | (1 << n)    — set bit n
    x & ~(1 << n)   — clear bit n
    x ^ (1 << n)    — toggle bit n
    (x >> n) & 1    — check if bit n is set

  TRADING USE CASE:
    // Encode order flags in 1 byte instead of 8 separate bools (8 bytes):
    uint8_t flags = 0;
    const uint8_t FLAG_IS_IOC    = 0b00000001;  // bit 0
    const uint8_t FLAG_IS_FOK    = 0b00000010;  // bit 1
    const uint8_t FLAG_SHORT_SELL= 0b00000100;  // bit 2
    const uint8_t FLAG_HIDDEN    = 0b00001000;  // bit 3
    flags |= FLAG_IS_IOC;                       // set IOC flag
    bool is_ioc = flags & FLAG_IS_IOC;          // check IOC flag

  COMMON MISTAKES:
    - Using = (assignment) instead of == (comparison) inside if() → always true
    - Bitwise & vs logical && — very different! & works on bits, && on bools
    - Left shifting a negative number — undefined behavior
    - Right shift of signed integers is implementation-defined (use unsigned)
*/

#include <iostream>
#include <cstdint>

int main() {

    // -------------------------------------------------------
    // COMPARISON OPERATORS
    // -------------------------------------------------------

    double bid   = 100.50;
    double ask   = 100.55;
    double price = 100.52;

    std::cout << "--- Comparison Operators ---\n";
    std::cout << "bid == ask:  " << (bid == ask)  << "\n";  // 0 (false)
    std::cout << "bid < ask:   " << (bid < ask)   << "\n";  // 1 (true)
    std::cout << "price >= bid:" << (price >= bid) << "\n";  // 1 (true)
    std::cout << "bid != ask:  " << (bid != ask)  << "\n";  // 1 (true)

    // -------------------------------------------------------
    // LOGICAL OPERATORS — combining conditions
    // -------------------------------------------------------

    int  position    = 500;     // current shares held
    bool market_open = true;    // is the market open?
    bool risk_ok     = true;    // has risk check passed?

    std::cout << "\n--- Logical Operators ---\n";

    // Order can go through if: market open AND risk check passed AND we have room
    bool can_trade = market_open && risk_ok && (position < 10000);
    std::cout << "Can trade: " << can_trade << "\n";  // 1 (true)

    // Flatten trigger: either big loss OR market closed
    bool daily_loss_hit = false;
    bool should_flatten = !market_open || daily_loss_hit;
    std::cout << "Should flatten: " << should_flatten << "\n";  // 0 (false)

    // Short-circuit: if market_open is false, the expensive risk_check() is SKIPPED
    // Order the cheapest/most-likely-to-fail check FIRST for performance
    bool result = market_open && risk_ok;  // risk_ok not evaluated if !market_open

    // -------------------------------------------------------
    // ASSIGNMENT SHORTHAND OPERATORS
    // -------------------------------------------------------

    int64_t pnl = 0;
    pnl += 250;    // pnl = pnl + 250  → 250
    pnl -= 75;     // pnl = pnl - 75   → 175
    pnl *= 2;      // pnl = pnl * 2    → 350

    int qty = 1000;
    qty >>= 1;     // qty = qty / 2    → 500 (right shift is fastest division by 2)

    std::cout << "\n--- Assignment Shorthand ---\n";
    std::cout << "PnL after trades: " << pnl << "\n";  // 350
    std::cout << "Qty halved:       " << qty << "\n";  // 500

    // -------------------------------------------------------
    // BITWISE OPERATORS — the heart of low-level HFT code
    // -------------------------------------------------------

    std::cout << "\n--- Bitwise Operators ---\n";

    // Binary representation of 0b1010 = 10, 0b1100 = 12
    uint8_t a = 0b1010;   // bits: 1010
    uint8_t b = 0b1100;   // bits: 1100

    std::cout << "a      = " << (int)a             << "  (0b1010)\n";
    std::cout << "b      = " << (int)b             << "  (0b1100)\n";
    std::cout << "a & b  = " << (int)(a & b)       << "  (0b1000 = AND: both must be 1)\n";
    std::cout << "a | b  = " << (int)(a | b)       << "  (0b1110 = OR: either is 1)\n";
    std::cout << "a ^ b  = " << (int)(a ^ b)       << "  (0b0110 = XOR: different)\n";
    std::cout << "~a     = " << (int)(uint8_t)(~a) << "  (flip all bits)\n";
    std::cout << "a << 1 = " << (int)(a << 1)      << "  (shift left = multiply by 2)\n";
    std::cout << "a >> 1 = " << (int)(a >> 1)      << "  (shift right = divide by 2)\n";

    // -------------------------------------------------------
    // BITWISE TRADING PATTERNS
    // -------------------------------------------------------

    std::cout << "\n--- Order Flag Bitmask Example ---\n";

    // Pack multiple boolean flags into ONE byte (saves memory, cache-friendly)
    constexpr uint8_t FLAG_BUY        = 0b00000001;  // bit 0: side is BUY
    constexpr uint8_t FLAG_IOC        = 0b00000010;  // bit 1: Immediate Or Cancel
    constexpr uint8_t FLAG_FOK        = 0b00000100;  // bit 2: Fill Or Kill
    constexpr uint8_t FLAG_SHORT_SELL = 0b00001000;  // bit 3: short sale
    constexpr uint8_t FLAG_HIDDEN     = 0b00010000;  // bit 4: iceberg/hidden order

    uint8_t order_flags = 0;  // start with no flags set

    // SET a flag: use OR to turn a bit ON
    order_flags |= FLAG_BUY;   // set BUY flag
    order_flags |= FLAG_IOC;   // set IOC flag
    std::cout << "Flags byte: " << (int)order_flags << "\n";  // 3 (0b00000011)

    // CHECK a flag: use AND to test if a bit is set
    bool is_buy = order_flags & FLAG_BUY;   // true
    bool is_fok = order_flags & FLAG_FOK;   // false
    std::cout << "Is BUY:  " << is_buy << "\n";  // 1
    std::cout << "Is FOK:  " << is_fok << "\n";  // 0

    // CLEAR a flag: AND with NOT of the flag
    order_flags &= ~FLAG_IOC;   // turn off IOC bit
    std::cout << "After clearing IOC: " << (int)order_flags << "\n";  // 1 (only BUY)

    // TOGGLE a flag: use XOR
    order_flags ^= FLAG_HIDDEN;  // toggle hidden flag ON
    std::cout << "After toggling HIDDEN on: " << (int)order_flags << "\n";

    // -------------------------------------------------------
    // FAST MODULO WITH POWER-OF-2 SIZES (ring buffer trick)
    // -------------------------------------------------------

    // Normal modulo: index % capacity  (requires division — slow)
    // Fast modulo: index & (capacity - 1)  (bitwise AND — one instruction)
    // ONLY works when capacity is a power of 2: 2, 4, 8, 16, 32, 64, 256, 1024...

    constexpr int RING_BUFFER_SIZE = 1024;   // must be power of 2
    int write_index = 1025;                   // simulating an overflowed index

    int slow_wrap = write_index % RING_BUFFER_SIZE;             // division
    int fast_wrap = write_index & (RING_BUFFER_SIZE - 1);       // bitwise AND

    std::cout << "\nRing buffer wrap: slow=" << slow_wrap << " fast=" << fast_wrap << "\n";
    // Both give 1 — same result, but bitwise is faster in the hot path

    // -------------------------------------------------------
    // BIT SHIFTS AS FAST MULTIPLY/DIVIDE
    // -------------------------------------------------------

    int x = 8;
    std::cout << "\nBit shifts:\n";
    std::cout << "8 << 1 = " << (x << 1) << "  (8 * 2 = 16)\n";
    std::cout << "8 << 3 = " << (x << 3) << "  (8 * 8 = 64)\n";
    std::cout << "8 >> 1 = " << (x >> 1) << "  (8 / 2 = 4)\n";
    std::cout << "8 >> 2 = " << (x >> 2) << "  (8 / 4 = 2)\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Reading a message type from a raw exchange packet:

        uint8_t msg_byte = raw_packet[0];

        // Top 4 bits = message category, bottom 4 bits = message type
        uint8_t category = (msg_byte >> 4) & 0x0F;  // shift right, mask top
        uint8_t msg_type = msg_byte & 0x0F;          // mask bottom 4 bits

        if (category == 0x02 && msg_type == 0x01) {
            // This is an "Add Order" message — process it
        }

      This bit-parsing pattern is in EVERY binary protocol parser
      (ITCH, OUCH, CME MDP3, FIX binary).
    */
}
