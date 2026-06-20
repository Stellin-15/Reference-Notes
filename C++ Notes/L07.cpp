// ============================================================
// L07: Control Flow — if, else, switch, Ternary
// ============================================================
// WHAT: How to make decisions in code — conditionally execute
//       blocks based on values or comparisons.
// WHY (TRADING): Every trading decision is a branch:
//   "If price crosses threshold, send buy order."
//   "If position > limit, reject."
//   "If market is closed, do nothing."
//   Understanding branch performance matters in HFT — branch
//   misprediction costs ~15 clock cycles on modern CPUs.
// PHASE: Foundation
// ============================================================

/*
  CONCEPT OVERVIEW:

  IF / ELSE IF / ELSE:
    if (condition) { ... }
    else if (other_condition) { ... }
    else { ... }
    Conditions are evaluated top to bottom — first true branch wins.

  SWITCH / CASE:
    Faster than long if-else chains for integer/enum comparisons.
    The compiler can generate a jump table — O(1) lookup regardless
    of how many cases there are.
    ALWAYS include "default:" as a safety net.
    ALWAYS include "break;" unless you intentionally want fall-through.

  TERNARY OPERATOR:
    condition ? value_if_true : value_if_false
    Single-expression conditional — more concise, same semantics as if/else.
    Good for: inline assignments, return values, logging messages.

  BRANCH PREDICTION:
    Modern CPUs GUESS which branch will be taken before evaluating the condition.
    If the guess is wrong = ~15 clock cycle penalty (branch misprediction).
    In HFT, unpredictable branches (e.g., 50/50 buy vs sell) can cost latency.
    Solutions: branchless code, [[likely]]/[[unlikely]] hints (C++20), cmov.
    (Covered in depth in L51)

  ORDER OF CONDITIONS IN if-else chains:
    Put the MOST LIKELY case first.
    Put the CHEAPEST check first (short-circuit evaluation).
    Example: check position limits before calling an expensive risk function.

  TRADING USE CASE:
    if (order.side == Side::BUY && position < max_long) {
        send_order(order);
    } else if (order.side == Side::SELL && position > max_short) {
        send_order(order);
    } else {
        log("Order rejected: position limit");
    }

  COMMON MISTAKES:
    - Using = instead of == in a condition: if (x = 5) always true!
    - Forgetting break in switch → unintended fall-through
    - Deeply nested ifs → hard to read, potential performance issues
    - Comparing floating point with ==: never do if (price == 100.0)
      because floating point is imprecise. Use: if (std::abs(price - 100.0) < 1e-9)
*/

#include <iostream>
#include <cstdint>
#include <cmath>    // for std::abs

int main() {

    // -------------------------------------------------------
    // BASIC if / else if / else
    // -------------------------------------------------------

    double bid      = 100.50;
    double ask      = 100.55;
    double my_price = 100.52;

    std::cout << "--- Basic if/else ---\n";

    if (my_price <= bid) {
        // Can hit the bid immediately (market sell)
        std::cout << "Price at/below bid — SELL immediately\n";
    } else if (my_price >= ask) {
        // Can lift the ask immediately (market buy)
        std::cout << "Price at/above ask — BUY immediately\n";
    } else {
        // Price is inside the spread — must post a limit order and wait
        std::cout << "Price inside spread — post limit order and wait\n";
    }

    // -------------------------------------------------------
    // RISK GATE — layered checks (cheapest first)
    // -------------------------------------------------------

    bool market_open    = true;
    bool risk_enabled   = true;
    int  position       = 500;
    int  order_qty      = 200;
    int  MAX_POSITION   = 1000;
    bool is_halted      = false;

    std::cout << "\n--- Risk Gate (order of evaluation matters) ---\n";

    // Check cheapest/most-obvious conditions first (short-circuit evaluation):
    // If market_open is false, none of the other (potentially expensive) checks run
    if (!market_open) {
        std::cout << "[REJECT] Market closed\n";
    } else if (is_halted) {
        std::cout << "[REJECT] Symbol halted\n";
    } else if (!risk_enabled) {
        std::cout << "[REJECT] Risk disabled (kill switch)\n";
    } else if (position + order_qty > MAX_POSITION) {
        std::cout << "[REJECT] Would exceed max position: "
                  << (position + order_qty) << " > " << MAX_POSITION << "\n";
    } else {
        std::cout << "[ACCEPT] Order passed all risk checks\n";
    }

    // -------------------------------------------------------
    // SWITCH / CASE — fast for enum/integer dispatch
    // -------------------------------------------------------

    // Order types encoded as integers (in a real system, use enum class)
    constexpr int ORDER_MARKET = 0;
    constexpr int ORDER_LIMIT  = 1;
    constexpr int ORDER_IOC    = 2;  // Immediate Or Cancel
    constexpr int ORDER_FOK    = 3;  // Fill Or Kill

    int order_type = ORDER_IOC;

    std::cout << "\n--- Switch on order type ---\n";

    switch (order_type) {
        case ORDER_MARKET:
            // Execute immediately at best available price
            std::cout << "MARKET order: execute at best price\n";
            break;  // MUST break, otherwise falls into LIMIT case

        case ORDER_LIMIT:
            // Post to order book if price not immediately available
            std::cout << "LIMIT order: post to book if no immediate fill\n";
            break;

        case ORDER_IOC:
            // Fill what you can immediately, cancel the rest
            std::cout << "IOC order: fill immediately, cancel remainder\n";
            break;

        case ORDER_FOK:
            // Only fill if the ENTIRE quantity can be filled at once
            std::cout << "FOK order: fill entire qty or cancel completely\n";
            break;

        default:
            // Always have a default — catches unexpected values
            std::cout << "[ERROR] Unknown order type: " << order_type << "\n";
            break;
    }

    // -------------------------------------------------------
    // INTENTIONAL FALL-THROUGH (rare, document it clearly)
    // -------------------------------------------------------

    int msg_type = 2;
    std::cout << "\n--- Intentional fall-through ---\n";
    switch (msg_type) {
        case 1:
        case 2:
        case 3:
            // All three message types are handled the same way
            // The fall-through from 1 → 2 → 3 is intentional here
            std::cout << "Message type 1, 2, or 3: process as quote update\n";
            break;
        case 4:
            std::cout << "Message type 4: process as trade execution\n";
            break;
        default:
            std::cout << "Unknown message type\n";
            break;
    }

    // -------------------------------------------------------
    // TERNARY OPERATOR — concise conditional assignment
    // -------------------------------------------------------

    double entry_price = 100.00;
    double exit_price  = 101.50;

    // Ternary: (condition) ? if_true : if_false
    double pnl = exit_price - entry_price;
    std::string outcome = (pnl > 0) ? "PROFIT" : (pnl < 0) ? "LOSS" : "BREAKEVEN";
    std::cout << "\nTrade outcome: " << outcome << " ($" << pnl << ")\n";

    // Common use: pick display string based on side
    int    side        = 0;   // 0=BUY, 1=SELL
    const char* side_str = (side == 0) ? "BUY" : "SELL";
    std::cout << "Side: " << side_str << "\n";

    // -------------------------------------------------------
    // FLOATING POINT COMPARISON — never use == with doubles
    // -------------------------------------------------------

    double a = 0.1 + 0.2;   // 0.30000000000000004 due to floating point
    double b = 0.3;

    std::cout << "\n--- Floating point comparison ---\n";

    // WRONG: direct equality comparison
    if (a == b) {
        std::cout << "Equal (WRONG — will never print)\n";
    }

    // CORRECT: compare within a small epsilon (tolerance)
    double epsilon = 1e-9;   // 0.000000001 — one billionth
    if (std::abs(a - b) < epsilon) {
        std::cout << "Approximately equal (CORRECT)\n";
    }

    // In HFT, this is why prices are stored as int64_t ticks, not doubles —
    // integer comparison is exact: no epsilon needed.

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Routing logic for a smart order router (SOR):

        switch (venue_latency_rank) {
            case 0:  route_to("NYSE");     break;   // fastest venue
            case 1:  route_to("NASDAQ");   break;
            case 2:  route_to("BATS");     break;
            default: route_to("IEX");      break;   // fallback
        }

      And the inner risk check (layered, cheapest first):
        if (!is_open(venue)) return REJECT_MARKET_CLOSED;
        if (order.qty > MAX_QTY) return REJECT_SIZE;
        if (would_exceed_position(order)) return REJECT_POSITION;
        return ACCEPT;
    */
}
