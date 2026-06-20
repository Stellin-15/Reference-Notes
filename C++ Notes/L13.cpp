// ============================================================
// L13: References vs Pointers, const Correctness
// ============================================================
// WHAT: References are aliases for existing variables. How they
//       differ from pointers. Why const-correctness is essential.
// WHY (TRADING): References let you pass large trading objects
//   (OrderBook, Position, Order structs) to functions without
//   copying them. const& is the correct way to pass a read-only
//   object. Lvalue vs rvalue references underpin move semantics —
//   the key to zero-copy data pipelines in HFT (covered in L24).
// PHASE: Foundation
// ============================================================

/*
  CONCEPT OVERVIEW:

  REFERENCES:
    int& ref = x;   — ref is an alias: ref IS x, they share the same memory
    You cannot have a null reference (unlike pointers)
    You cannot rebind a reference (unlike pointers — once bound, always bound)
    You cannot take the address of a reference to get the ref itself (& gives you x's address)

  REFERENCE vs POINTER COMPARISON:
    Reference:                      Pointer:
      int& r = x;                     int* p = &x;
      r = 5;       (sets x to 5)      *p = 5;      (sets x to 5)
      Can't be null                   Can be nullptr
      Can't be rebound                Can point elsewhere
      No need to dereference          Must dereference: *p or p->
      Cleaner syntax                  More explicit (shows memory)

  WHEN TO USE WHICH:
    Reference: prefer when argument is always valid (never null)
    Pointer:   use when argument might be absent (nullable), or when
               you need pointer arithmetic, or when calling C APIs

  PASSING BY REFERENCE — THE MOST IMPORTANT PATTERN:
    void process(const Order& order)  — read-only, no copy
    void fill(Order& order)           — modifiable, no copy
    Order make_order()                — return by value (compiler optimizes this)

  CONST CORRECTNESS:
    Mark EVERYTHING as const that shouldn't change.
    const int x = 5;               — const variable
    const Order& order             — const reference parameter (read-only)
    void print() const;            — const method: won't modify the object (class methods)
    Benefits:
    - Catches bugs at compile time ("oops I accidentally modified this")
    - Documents intent: "this function will NOT change your data"
    - Allows the compiler to optimize more aggressively
    - Enables passing temporaries and literals to const& parameters

  LVALUE vs RVALUE (INTRO — full coverage in L24):
    Lvalue: has a name, has an address, can appear on LEFT of =
      int x = 5;    x is an lvalue
    Rvalue: temporary, no name, appears on RIGHT of =, can't take its address
      5, (x+y), make_order()   are rvalues
    int& r = x;         — lvalue reference: binds to lvalues
    int&& rr = 5;       — rvalue reference: binds to temporaries (enables move semantics)
    const int& cr = 5;  — const lvalue ref can bind to rvalues (special rule)

  TRADING USE CASE:
    // Process a market data tick — read only, no copy, always valid
    void on_tick(const Quote& quote, OrderBook& book) {
        book.apply(quote);   // book is modified, quote is read-only
    }

    // Return an Order by value — compiler elides the copy (RVO)
    Order build_order(const Signal& signal) {
        return Order{next_id(), signal.price, signal.qty, signal.side};
    }

  COMMON MISTAKES:
    - Returning a local variable by reference — dangling reference (UB, crash)
    - Forgetting const on a reference parameter — misleads readers
    - Binding an rvalue to a non-const lvalue ref — compile error
    - Thinking int& ref = 5; works — it doesn't (5 is an rvalue)
*/

#include <iostream>
#include <string>
#include <cstdint>

// -------------------------------------------------------
// TRADING STRUCTS (we'll pass these by reference)
// -------------------------------------------------------

struct Order {
    uint64_t    id;
    double      price;
    int32_t     quantity;
    uint8_t     side;  // 0=BUY 1=SELL
    std::string symbol;
};

struct Position {
    std::string symbol;
    int64_t     net_qty;      // positive=long, negative=short
    double      avg_cost;
    double      unrealized_pnl;
};

// -------------------------------------------------------
// FUNCTIONS DEMONSTRATING REFERENCE PATTERNS
// -------------------------------------------------------

// const Order& — read-only, no copy, always valid
// This is the STANDARD pattern for "I need to inspect this order"
void log_order(const Order& order) {
    std::cout << "[LOG] #" << order.id
              << " " << order.symbol
              << " " << (order.side == 0 ? "BUY" : "SELL")
              << " " << order.quantity
              << " @ $" << order.price << "\n";
    // Cannot modify order here — compiler enforces this
}

// Order& (non-const reference) — modifies the order in place
// Used when function NEEDS to update the order's state
void fill_order(Order& order, int fill_qty, double fill_price) {
    // This modifies the caller's actual Order object
    std::cout << "[FILL] Filling " << fill_qty << " of order #" << order.id << "\n";
    order.quantity -= fill_qty;   // reduce remaining qty
    // In a real system: also update status, add fill record, etc.
}

// const reference parameter enables passing temporaries and literals
void print_symbol(const std::string& sym) {
    std::cout << "Symbol: " << sym << "\n";
}

// Update a position by reference — modifies the caller's Position struct
void update_position(Position& pos, int qty_delta, double price) {
    double old_cost = pos.avg_cost * pos.net_qty;
    pos.net_qty += qty_delta;
    // Recalculate average cost (simplified — real version handles direction changes)
    if (pos.net_qty != 0) {
        pos.avg_cost = (old_cost + price * qty_delta) / pos.net_qty;
    }
    pos.unrealized_pnl = (price - pos.avg_cost) * pos.net_qty;
}

// DANGER: Never return a reference to a LOCAL variable
// The local variable is destroyed when the function returns
// Uncommenting this would be undefined behavior:
// const Order& bad_function() {
//     Order local_order = {999, 100.0, 50, 0, "BAD"};
//     return local_order;  // DANGLING REFERENCE — local destroyed here!
// }

// OK: Return reference to something that outlives the function (e.g., global or member)
Order global_orders[10];
Order& get_order(int idx) { return global_orders[idx]; }  // OK: global lives forever

int main() {

    // -------------------------------------------------------
    // BASIC REFERENCE MECHANICS
    // -------------------------------------------------------

    std::cout << "--- Reference basics ---\n";

    double bid = 100.50;
    double& ref_bid = bid;     // ref_bid IS bid — same memory location

    std::cout << "bid:     " << bid     << "\n";
    std::cout << "ref_bid: " << ref_bid << "\n";  // same value

    ref_bid = 100.55;          // modifies bid through the reference
    std::cout << "After ref_bid=100.55: bid=" << bid << "\n";  // bid is now 100.55

    // &bid and &ref_bid return the SAME address (they're the same variable)
    std::cout << "bid address:     " << &bid     << "\n";
    std::cout << "ref_bid address: " << &ref_bid << "\n";  // identical

    // -------------------------------------------------------
    // PASS BY CONST REFERENCE — read-only, no copy
    // -------------------------------------------------------

    std::cout << "\n--- Pass by const reference (most common pattern) ---\n";

    Order my_order = {1001, 182.50, 100, 0, "AAPL"};   // 24+ bytes — we don't want to copy this

    log_order(my_order);      // passes reference — my_order is NOT copied

    // Can also pass a temporary to const reference (special rule in C++)
    print_symbol("TSLA");     // "TSLA" is a temporary string — works with const&

    // -------------------------------------------------------
    // PASS BY NON-CONST REFERENCE — modify in place
    // -------------------------------------------------------

    std::cout << "\n--- Pass by non-const reference (modification) ---\n";

    std::cout << "Before fill: qty=" << my_order.quantity << "\n";
    fill_order(my_order, 30, 182.50);  // modifies my_order directly
    std::cout << "After fill:  qty=" << my_order.quantity << "\n";

    // -------------------------------------------------------
    // UPDATING POSITION BY REFERENCE
    // -------------------------------------------------------

    std::cout << "\n--- Position update via reference ---\n";

    Position pos = {"AAPL", 0, 0.0, 0.0};

    update_position(pos, 100, 182.50);  // BUY 100 @ 182.50
    std::cout << "After BUY 100:   qty=" << pos.net_qty
              << " avg=$" << pos.avg_cost
              << " uPnL=$" << pos.unrealized_pnl << "\n";

    update_position(pos, 50, 183.00);   // BUY another 50 @ 183.00
    std::cout << "After BUY 50:    qty=" << pos.net_qty
              << " avg=$" << pos.avg_cost << "\n";

    update_position(pos, -80, 184.00);  // SELL 80 @ 184.00
    std::cout << "After SELL 80:   qty=" << pos.net_qty
              << " avg=$" << pos.avg_cost
              << " uPnL=$" << pos.unrealized_pnl << "\n";

    // -------------------------------------------------------
    // REFERENCE vs POINTER COMPARISON
    // -------------------------------------------------------

    std::cout << "\n--- Reference vs Pointer comparison ---\n";

    double ask = 100.55;

    // POINTER: must explicitly take address (&), dereference (*), can be null
    double* ptr = &ask;
    *ptr = 100.60;             // must dereference to write
    std::cout << "Via pointer: ask=" << ask << "\n";  // 100.60

    // REFERENCE: syntactically identical to using the original variable, can't be null
    double& ref = ask;
    ref = 100.65;              // no dereference needed
    std::cout << "Via reference: ask=" << ask << "\n";  // 100.65

    // Use pointer when: nullable, need arithmetic, need to rebind, calling C API
    // Use reference when: always valid, cleaner syntax, non-nullable semantics

    // -------------------------------------------------------
    // RVALUE REFERENCE INTRO (full coverage in L24)
    // -------------------------------------------------------

    std::cout << "\n--- Rvalue reference (intro) ---\n";

    int x = 10;          // x is an lvalue (has a name, has an address)
    int& lref = x;       // lvalue reference: binds to named variables
    // int& bad = 5;     // COMPILE ERROR: can't bind non-const lref to rvalue

    const int& const_ref = 5;   // OK: const lvalue ref CAN bind to rvalue 5
    int&& rref = 5;             // rvalue reference: binds to temporaries
    int&& rref2 = x + 1;       // x+1 is a temporary (rvalue)

    std::cout << "const_ref: " << const_ref << "\n";
    std::cout << "rref:      " << rref      << "\n";
    std::cout << "rref2:     " << rref2     << "\n";

    // Rvalue references are the key to MOVE SEMANTICS:
    // Instead of COPYING a large vector of market data, we can MOVE it
    // (transfer ownership in O(1) instead of O(n) copy)
    // Covered fully in L24.

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Const-correct order processing pipeline:

        // Read-only: risk check inspects but doesn't change the order
        bool risk_check(const Order& order, const Position& pos);

        // Read-write: gateway tags the order with a sequence number before sending
        void stamp_and_send(Order& order, uint64_t seq_num);

        // Return by value: compiler applies Return Value Optimization (RVO)
        // — no copy, the Order is constructed directly at the call site
        Order create_limit_order(const Signal& signal, uint64_t id) {
            return Order{id, signal.price, signal.qty, signal.side, signal.symbol};
        }

      This const-correctness pattern makes it IMPOSSIBLE to accidentally
      modify an order inside the risk check — the compiler enforces it.
    */
}
