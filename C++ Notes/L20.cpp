// ============================================================
// L20: Operator Overloading
// ============================================================
// WHAT: Give custom meaning to C++ operators (+, -, ==, <, <<,
//       etc.) for your own types. Lets user-defined types work
//       like built-in types.
// WHY (TRADING): Custom types for prices, quantities, and orders
//   are cleaner and safer when they support natural operators.
//   Price + Spread reads naturally. order1 < order2 enables
//   sorting. operator<< enables logging any object to cout.
//   The comparison operators enable storing trading objects in
//   ordered containers (std::map, std::set, priority_queue).
// PHASE: OOP
// ============================================================

/*
  CONCEPT OVERVIEW:

  WHICH OPERATORS CAN BE OVERLOADED:
    Arithmetic:   +  -  *  /  %  +=  -=  *=  /=
    Comparison:   ==  !=  <  >  <=  >=  <=>  (C++20 spaceship)
    Stream:       <<  >> (for cout/cin)
    Other:        []  ()  ->  *  ++  --  bool conversion

  CANNOT OVERLOAD:
    ::   .   .*   ?:   sizeof   alignof   typeid

  WHERE TO DEFINE THEM:
    Member function: T& operator+=(const T& rhs)
      - Left operand is *this (the object itself)
      - Use for: +=, -=, ++, --, [], ()

    Free function: T operator+(T lhs, const T& rhs)
      - Neither operand is *this
      - Use for: +, -, *, / (pass left by value, modify, return)
      - Also use for << and >> (left operand is stream, not your type)

    Friend: mark free function as 'friend' inside class if it needs private access

  RETURN TYPES:
    operator+   → returns a NEW object (value)
    operator+=  → returns *this as reference (for chaining: a += b += c)
    operator==  → returns bool
    operator<   → returns bool
    operator<<  → returns std::ostream& (for chaining: cout << a << b)
    operator[]  → returns reference (for assignment: arr[i] = val)

  THE SPACESHIP OPERATOR <=> (C++20):
    auto operator<=>(const T&) const = default;
    Automatically generates <, >, <=, >= from one definition.
    = default means the compiler generates it field by field.

  RULE OF CONSISTENT OPERATORS:
    If you define ==, also define !=.
    If you define <, also define >, <=, >=.
    In C++20, use <=> to get all comparisons at once.

  TRADING USE CASE:
    Price p1(10050), p2(10055);
    Price spread = p2 - p1;    // natural arithmetic
    if (p1 < p2) { ... }       // natural comparison for order book sorting
    std::cout << p1;           // natural logging

    // Enables sorting in std::map (order book levels):
    std::map<Price, Level>   asks;   // sorted by Price using operator<
    std::priority_queue<Price> bids; // also uses operator<

  COMMON MISTAKES:
    - operator+ as member function: then 5 + myObj won't compile (5 has no operator+)
      — define symmetric operators as free functions
    - operator== without operator!= — inconsistent interface
    - operator= (assignment) — see L21; don't confuse with operator==
    - Returning *this from operator+ instead of a new object — modifies the left operand!
    - Forgetting & in operator<< return type — breaks chaining
*/

#include <iostream>
#include <compare>    // std::strong_ordering for <=>
#include <cstdint>
#include <string>
#include <map>

// ============================================================
// PRICE — strongly-typed price in integer ticks
// ============================================================
// Wrapping int64_t in a class prevents accidentally mixing
// prices with plain integers or other unrelated int64_t values.

class Price {
public:
    static constexpr int64_t PRECISION = 100;   // cents: 1 tick = $0.01

    explicit Price(int64_t ticks = 0) : ticks_(ticks) {}

    // Factory: construct from a dollar amount (e.g., Price::from_dollars(182.50))
    static Price from_dollars(double dollars) {
        return Price(static_cast<int64_t>(dollars * PRECISION));
    }

    int64_t ticks()   const { return ticks_; }
    double  dollars() const { return static_cast<double>(ticks_) / PRECISION; }
    bool    valid()   const { return ticks_ > 0; }

    // --- ARITHMETIC OPERATORS ---

    // operator+= as member (modifies *this, returns *this)
    Price& operator+=(const Price& rhs) {
        ticks_ += rhs.ticks_;
        return *this;   // return reference for chaining: a += b += c
    }

    Price& operator-=(const Price& rhs) {
        ticks_ -= rhs.ticks_;
        return *this;
    }

    Price& operator*=(int64_t scalar) {
        ticks_ *= scalar;
        return *this;
    }

    // Prefix increment: ++price (advances one tick)
    Price& operator++() {
        ++ticks_;
        return *this;
    }

    // Postfix increment: price++ (returns old value, then increments)
    Price operator++(int) {
        Price old = *this;
        ++ticks_;
        return old;   // return old value
    }

    // Explicit bool conversion: valid if ticks > 0
    explicit operator bool() const { return valid(); }

    // --- COMPARISON: spaceship operator gives < > <= >= == != for free (C++20) ---
    auto operator<=>(const Price&) const = default;

    // Also define == explicitly for clarity (C++20 <=> also generates it)
    bool operator==(const Price& rhs) const = default;

private:
    int64_t ticks_;
};

// --- FREE FUNCTION OPERATORS (not member — symmetric, both sides can be Price) ---

// operator+ as free function: takes left by VALUE (copy), modifies, returns
Price operator+(Price lhs, const Price& rhs) {
    lhs += rhs;    // reuse operator+=
    return lhs;
}

Price operator-(Price lhs, const Price& rhs) {
    lhs -= rhs;
    return lhs;
}

Price operator*(Price lhs, int64_t scalar) {
    lhs *= scalar;
    return lhs;
}

// operator<< for streaming to cout (left side is ostream, right is Price)
std::ostream& operator<<(std::ostream& os, const Price& p) {
    os << "$" << p.dollars();
    return os;   // return ostream& for chaining: cout << a << b
}

// ============================================================
// ORDER — comparable for sorting in order book
// ============================================================

struct Order {
    uint64_t id;
    Price    price;
    int32_t  qty;
    bool     is_buy;
    uint64_t timestamp_ns;   // time of order entry (for FIFO priority)

    // operator< for price-time priority sorting:
    // - For bids: higher price = higher priority (best bid first)
    // - For asks: lower price = higher priority (best ask first)
    // - Tie-break by timestamp: earlier = higher priority (FIFO)
    bool operator<(const Order& rhs) const {
        if (price != rhs.price) {
            return is_buy ? price > rhs.price    // bid: higher price = better
                          : price < rhs.price;   // ask: lower price = better
        }
        return timestamp_ns < rhs.timestamp_ns;  // FIFO: earlier entry wins
    }

    bool operator==(const Order& rhs) const {
        return id == rhs.id;   // two orders are equal iff they have the same ID
    }
};

std::ostream& operator<<(std::ostream& os, const Order& o) {
    os << "Order#" << o.id
       << " " << (o.is_buy ? "BUY" : "SELL")
       << " " << o.qty
       << " @ " << o.price;
    return os;
}

// ============================================================
// LEVEL — order book price level, supports comparison and addition
// ============================================================

struct Level {
    Price   price;
    int32_t qty;
    int     order_count;

    // Combine two levels at the same price
    Level& operator+=(const Level& rhs) {
        qty         += rhs.qty;
        order_count += rhs.order_count;
        return *this;
    }

    bool operator==(const Level& rhs) const {
        return price == rhs.price;
    }

    bool operator<(const Level& rhs) const {
        return price < rhs.price;   // sort by price
    }
};

std::ostream& operator<<(std::ostream& os, const Level& l) {
    os << l.price << " x " << l.qty << " (" << l.order_count << " orders)";
    return os;
}

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // PRICE ARITHMETIC
    // -------------------------------------------------------

    std::cout << "--- Price arithmetic ---\n";

    Price bid  = Price::from_dollars(182.50);
    Price ask  = Price::from_dollars(182.55);
    Price tick = Price(1);   // 1 tick = $0.01

    std::cout << "Bid:    " << bid << "\n";
    std::cout << "Ask:    " << ask << "\n";

    Price spread = ask - bid;
    std::cout << "Spread: " << spread << " (" << spread.ticks() << " ticks)\n";

    Price mid = Price((bid.ticks() + ask.ticks()) / 2);
    std::cout << "Mid:    " << mid << "\n";

    // Improve bid by 1 tick
    Price improved_bid = bid + tick;
    std::cout << "Improved bid: " << improved_bid << "\n";

    // Prefix increment (advance 1 tick)
    ++bid;
    std::cout << "After ++bid:  " << bid << "\n";

    // Compound assignment
    ask += Price(5);   // move ask up 5 ticks
    std::cout << "After ask += 5 ticks: " << ask << "\n";

    // -------------------------------------------------------
    // PRICE COMPARISON
    // -------------------------------------------------------

    std::cout << "\n--- Price comparison ---\n";

    Price p1 = Price::from_dollars(100.00);
    Price p2 = Price::from_dollars(100.05);

    std::cout << "p1 < p2:  " << (p1 < p2)  << "\n";   // 1
    std::cout << "p1 > p2:  " << (p1 > p2)  << "\n";   // 0
    std::cout << "p1 == p1: " << (p1 == p1) << "\n";   // 1
    std::cout << "p1 != p2: " << (p1 != p2) << "\n";   // 1

    // Bool conversion: if(price) checks validity
    Price invalid_price(0);
    std::cout << "Valid price:   " << (bool)p1          << "\n";   // 1
    std::cout << "Invalid price: " << (bool)invalid_price << "\n"; // 0

    // -------------------------------------------------------
    // ORDER SORTING (uses operator<)
    // -------------------------------------------------------

    std::cout << "\n--- Order sorting (price-time priority) ---\n";

    // Simulate 4 orders arriving at different times
    Order orders[] = {
        {1001, Price::from_dollars(182.50), 100, true, 1000},  // BUY 100 @ 182.50, t=1000
        {1002, Price::from_dollars(182.55), 200, true, 1001},  // BUY 200 @ 182.55 (higher = better for bid)
        {1003, Price::from_dollars(182.50), 150, true, 999 },  // BUY 150 @ 182.50, t=999  (earlier = better)
        {1004, Price::from_dollars(182.45), 300, true, 998 },  // BUY 300 @ 182.45 (lowest price = worst)
    };

    std::cout << "Before sort:\n";
    for (const auto& o : orders) std::cout << "  " << o << "\n";

    // std::sort uses operator< to order
    std::sort(std::begin(orders), std::end(orders));

    std::cout << "After sort (best bid first):\n";
    for (const auto& o : orders) std::cout << "  " << o << "\n";

    // -------------------------------------------------------
    // LEVEL ACCUMULATION (operator+=)
    // -------------------------------------------------------

    std::cout << "\n--- Level aggregation (operator+=) ---\n";

    Level level1{Price::from_dollars(182.50), 200, 2};
    Level level2{Price::from_dollars(182.50), 300, 3};   // same price, combine them

    std::cout << "Level 1: " << level1 << "\n";
    std::cout << "Level 2: " << level2 << "\n";
    level1 += level2;
    std::cout << "Combined: " << level1 << "\n";

    // -------------------------------------------------------
    // COUT CHAINING (operator<<)
    // -------------------------------------------------------

    std::cout << "\n--- Operator<< chaining ---\n";

    // operator<< returns ostream& — so you can chain
    Order best = {1002, Price::from_dollars(182.55), 200, true, 1001};
    std::cout << "Best order: " << best << " | Notional: $"
              << (best.price.dollars() * best.qty) << "\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      std::map uses operator< to keep prices sorted:

        // Order book ask side: lowest ask first (ascending)
        std::map<Price, Level> asks;
        asks[Price::from_dollars(182.55)] = {Price::from_dollars(182.55), 300, 2};
        asks[Price::from_dollars(182.60)] = {Price::from_dollars(182.60), 500, 5};
        asks[Price::from_dollars(182.50)] = {Price::from_dollars(182.50), 100, 1};

        // Best ask is always asks.begin() — map is sorted by Price operator<
        auto best_ask = asks.begin();
        std::cout << "Best ask: " << *best_ask << "\n";

        // Notional value of order vs best ask:
        Price limit = Price::from_dollars(182.55);
        if (order.price >= best_ask->first) {
            // order.price >= best ask → can fill immediately
        }

      Natural operator usage makes the book logic readable.
    */
}
