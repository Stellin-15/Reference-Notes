// ============================================================
// L17: Access Modifiers and Encapsulation
// ============================================================
// WHAT: public, private, and protected control which code can
//       access which members. Encapsulation hides implementation
//       details and exposes only a clean interface.
// WHY (TRADING): Encapsulation prevents invalid state. An
//   OrderBook with public price arrays can be accidentally
//   corrupted by any code that touches it. With encapsulation,
//   only OrderBook's own methods can modify it — enforcing
//   correct ordering, consistent bid/ask sorting, and valid
//   quantity updates. Bugs that corrupt market state are
//   extremely hard to find; encapsulation prevents them.
// PHASE: OOP
// ============================================================

/*
  CONCEPT OVERVIEW:

  ACCESS MODIFIERS:
    public:    — accessible from ANYWHERE (outside the class, from derived classes)
    private:   — accessible ONLY from within the class itself (not even derived classes)
    protected: — accessible from the class AND from derived classes (not external code)

  ENCAPSULATION PRINCIPLE:
    Make data PRIVATE. Expose only what callers need via PUBLIC methods.
    The internal representation can then change without breaking callers.
    Example: you can change price from double to int64_t ticks internally
             without changing the public interface — callers don't know or care.

  GETTERS AND SETTERS:
    Getter: const method that returns a private field value (read-only access)
    Setter: non-const method that validates + sets a private field
    In HFT: avoid setters when possible — prefer constructors + immutable state
            to eliminate the possibility of invalid mid-session changes.
    When to skip getters: for performance-critical inner structs accessed in
    tight loops, making data public (as a struct) is sometimes acceptable if
    invariants are managed at a higher level.

  INVARIANTS:
    Conditions that must ALWAYS be true about an object.
    Example: "ask price must always be greater than bid price"
             "remaining_qty can never be negative"
             "order_id is always > 0"
    Encapsulation enforces invariants: only the class's own methods can
    change the state, and those methods validate before changing.

  INTERFACE vs IMPLEMENTATION:
    Public methods = the INTERFACE (what callers can do)
    Private fields/methods = the IMPLEMENTATION (how it's done internally)
    Changing the implementation never breaks code that uses the interface.

  PROTECTED — WHEN TO USE:
    Only when a derived class MUST access the base class's internals.
    Prefer private + protected getters over protected data directly.
    Exposing protected data to derived classes creates coupling —
    a derived class then depends on the base's internal layout.

  TRADING USE CASE:
    class OrderBook {
    private:
        // Internal: callers don't know if this is a map or sorted vector
        std::map<int64_t, Level, std::greater<int64_t>> bids_;
        std::map<int64_t, Level>                         asks_;
    public:
        // Callers only see this clean interface:
        int64_t best_bid()  const;
        int64_t best_ask()  const;
        int64_t spread()    const;
        void    apply(const Message& msg);
    };

  COMMON MISTAKES:
    - Making all fields public for convenience — breaks encapsulation
    - Setter that doesn't validate — might allow price = -1.0
    - Protected data in base class — creates tight coupling with derived classes
    - Returning a non-const reference to a private field — exposes internals
*/

#include <iostream>
#include <string>
#include <cstdint>
#include <stdexcept>

// ============================================================
// POSITION CLASS — well-encapsulated trading position tracker
// ============================================================

class Position {
public:
    // Constructor validates initial state — enforces invariants from day one
    explicit Position(std::string symbol)
        : symbol_(std::move(symbol))
        , net_qty_(0)
        , avg_cost_(0.0)
        , realized_pnl_(0.0)
        , total_bought_(0)
        , total_sold_(0)
    {}

    // --- PUBLIC INTERFACE (read-only getters) ---

    // Getters: return copies of private data (callers can't corrupt it)
    const std::string& symbol()       const { return symbol_; }
    int64_t            net_qty()      const { return net_qty_; }
    double             avg_cost()     const { return avg_cost_; }
    double             realized_pnl() const { return realized_pnl_; }
    int64_t            total_bought() const { return total_bought_; }
    int64_t            total_sold()   const { return total_sold_; }

    // Derived values: computed from private fields, exposed as part of interface
    bool   is_long()  const { return net_qty_ > 0; }
    bool   is_short() const { return net_qty_ < 0; }
    bool   is_flat()  const { return net_qty_ == 0; }

    // Unrealized PnL at a given market price (read-only calculation)
    double unrealized_pnl(double market_price) const {
        return (market_price - avg_cost_) * static_cast<double>(net_qty_);
    }

    double total_pnl(double market_price) const {
        return realized_pnl_ + unrealized_pnl(market_price);
    }

    // --- PUBLIC MUTATING METHODS (with validation) ---

    // Record a BUY fill — updates position and average cost
    void on_buy(int64_t qty, double price) {
        // Invariant check: qty and price must be positive
        if (qty <= 0) throw std::invalid_argument("Buy qty must be positive");
        if (price <= 0.0) throw std::invalid_argument("Buy price must be positive");

        // If we're short and buying back, realize PnL on the covered portion
        if (net_qty_ < 0) {
            int64_t cover_qty = std::min(qty, -net_qty_);
            realized_pnl_ += (avg_cost_ - price) * static_cast<double>(cover_qty);
        }

        // Update average cost using weighted average formula
        if (net_qty_ >= 0) {
            // Adding to a long position
            double total_cost = avg_cost_ * static_cast<double>(net_qty_) + price * static_cast<double>(qty);
            net_qty_ += qty;
            avg_cost_ = (net_qty_ != 0) ? total_cost / static_cast<double>(net_qty_) : 0.0;
        } else {
            net_qty_ += qty;
            if (net_qty_ >= 0) avg_cost_ = (net_qty_ > 0) ? price : 0.0;
        }

        total_bought_ += qty;
        print_update("BUY", qty, price);
    }

    // Record a SELL fill — updates position and realizes PnL on long portion
    void on_sell(int64_t qty, double price) {
        if (qty <= 0) throw std::invalid_argument("Sell qty must be positive");
        if (price <= 0.0) throw std::invalid_argument("Sell price must be positive");

        // If we're long and selling, realize PnL on the sold portion
        if (net_qty_ > 0) {
            int64_t sell_qty = std::min(qty, net_qty_);
            realized_pnl_ += (price - avg_cost_) * static_cast<double>(sell_qty);
        }

        if (net_qty_ <= 0) {
            // Adding to a short position — average short cost
            double total_cost = avg_cost_ * static_cast<double>(-net_qty_) + price * static_cast<double>(qty);
            net_qty_ -= qty;
            avg_cost_ = (net_qty_ != 0) ? total_cost / static_cast<double>(-net_qty_) : 0.0;
        } else {
            net_qty_ -= qty;
            if (net_qty_ <= 0) avg_cost_ = (net_qty_ < 0) ? price : 0.0;
        }

        total_sold_ += qty;
        print_update("SELL", qty, price);
    }

    // Print current position summary
    void print(double market_price) const {
        std::cout << "=== Position: " << symbol_ << " ===\n"
                  << "  Net qty:        " << net_qty_
                  << (is_long() ? " (LONG)" : is_short() ? " (SHORT)" : " (FLAT)") << "\n"
                  << "  Avg cost:      $" << avg_cost_         << "\n"
                  << "  Market price:  $" << market_price      << "\n"
                  << "  Realized PnL:  $" << realized_pnl_     << "\n"
                  << "  Unrealized PnL:$" << unrealized_pnl(market_price) << "\n"
                  << "  Total PnL:     $" << total_pnl(market_price)      << "\n"
                  << "  Total bought:   " << total_bought_     << "\n"
                  << "  Total sold:     " << total_sold_       << "\n";
    }

private:
    // --- PRIVATE FIELDS — the internal state callers cannot touch ---

    std::string symbol_;
    int64_t     net_qty_;        // positive = long, negative = short
    double      avg_cost_;       // weighted average entry price
    double      realized_pnl_;   // PnL from closed portions
    int64_t     total_bought_;   // cumulative shares bought today
    int64_t     total_sold_;     // cumulative shares sold today

    // Private helper — only the class itself calls this
    void print_update(const char* action, int64_t qty, double price) const {
        std::cout << "[" << action << "] " << symbol_
                  << " " << qty << " @ $" << price
                  << " | Net: " << net_qty_
                  << " | Avg: $" << avg_cost_
                  << " | Realized PnL: $" << realized_pnl_ << "\n";
    }
};

// ============================================================
// ENCAPSULATED ORDER BOOK (simplified)
// ============================================================

class SimpleOrderBook {
public:
    explicit SimpleOrderBook(std::string symbol) : symbol_(symbol) {}

    // Clean public interface — callers don't know the internal structure
    void set_bid(double price, int qty) {
        // Invariant: bid must be less than ask (if ask exists)
        if (has_ask_ && price >= ask_price_) {
            std::cout << "[WARN] Bid " << price << " >= ask " << ask_price_ << " — crossing book!\n";
        }
        bid_price_ = price;
        bid_qty_   = qty;
        has_bid_   = true;
    }

    void set_ask(double price, int qty) {
        if (has_bid_ && price <= bid_price_) {
            std::cout << "[WARN] Ask " << price << " <= bid " << bid_price_ << " — crossing book!\n";
        }
        ask_price_ = price;
        ask_qty_   = qty;
        has_ask_   = true;
    }

    // Read-only accessors
    double best_bid()    const { return has_bid_ ? bid_price_ : 0.0; }
    double best_ask()    const { return has_ask_ ? ask_price_ : 0.0; }
    int    bid_size()    const { return has_bid_ ? bid_qty_   : 0;   }
    int    ask_size()    const { return has_ask_ ? ask_qty_   : 0;   }
    double spread()      const { return (has_bid_ && has_ask_) ? ask_price_ - bid_price_ : 0.0; }
    double mid_price()   const { return (has_bid_ && has_ask_) ? (bid_price_ + ask_price_) / 2.0 : 0.0; }
    bool   is_crossed()  const { return has_bid_ && has_ask_ && bid_price_ >= ask_price_; }

    void print() const {
        std::cout << "Book [" << symbol_ << "]: "
                  << "Bid=" << bid_qty_ << "@$" << bid_price_ << "  |  "
                  << "Ask=" << ask_qty_ << "@$" << ask_price_
                  << "  Spread=$" << spread() << "\n";
    }

private:
    std::string symbol_;
    double      bid_price_ = 0.0;
    double      ask_price_ = 0.0;
    int         bid_qty_   = 0;
    int         ask_qty_   = 0;
    bool        has_bid_   = false;
    bool        has_ask_   = false;
};

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // POSITION TRACKING WITH FULL ENCAPSULATION
    // -------------------------------------------------------

    std::cout << "--- Encapsulated Position Tracker ---\n\n";

    Position pos("AAPL");

    // All state changes go through validated methods — no direct field access
    pos.on_buy(100, 182.50);    // BUY 100 @ 182.50
    pos.on_buy( 50, 183.00);    // BUY  50 @ 183.00 (avg cost updates)
    pos.on_sell(80, 184.50);    // SELL 80 @ 184.50 (realize some PnL)
    pos.on_sell(70, 185.00);    // SELL 70 @ 185.00 (now short 0 or flipped)

    std::cout << "\n";
    pos.print(185.50);          // current market price = 185.50

    // Trying to set an invalid state:
    try {
        pos.on_buy(-10, 182.50);  // negative qty — validation rejects it
    } catch (const std::invalid_argument& e) {
        std::cout << "[CAUGHT] " << e.what() << "\n";
    }

    // -------------------------------------------------------
    // ENCAPSULATED ORDER BOOK
    // -------------------------------------------------------

    std::cout << "\n--- Encapsulated Order Book ---\n";

    SimpleOrderBook book("AAPL");
    book.set_bid(182.50, 500);
    book.set_ask(182.55, 300);
    book.print();

    std::cout << "Spread:    $" << book.spread()    << "\n";
    std::cout << "Mid price: $" << book.mid_price() << "\n";
    std::cout << "Is crossed: " << book.is_crossed() << "\n";

    // Update quotes
    book.set_bid(182.52, 200);
    book.set_ask(182.57, 400);
    book.print();

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Why encapsulation catches bugs that would otherwise destroy your account:

        // WITHOUT encapsulation (public fields — dangerous):
        order_book.bid_price = 99999.99;   // typo: accidentally set bid above ask
        order_book.ask_qty   = -100;       // corruption: negative quantity

        // WITH encapsulation (controlled methods):
        order_book.set_bid(99999.99, 100); // triggers is_crossed() warning
        order_book.set_ask_qty(-100);      // throws invalid_argument

        // In a live trading system, book corruption = wrong signals = wrong orders.
        // Encapsulation makes the class its own integrity enforcer.
    */
}
