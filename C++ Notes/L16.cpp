// ============================================================
// L16: Classes — Fields, Methods, Constructors, Destructors
// ============================================================
// WHAT: Classes bundle data (fields) and behavior (methods)
//       into a single named type. They are the primary building
//       block of object-oriented C++.
// WHY (TRADING): Every major component of a trading system is
//   modeled as a class: Order, Position, OrderBook, Strategy,
//   RiskManager, Gateway. Classes let you group related data
//   together, enforce invariants through constructors, and
//   clean up resources automatically through destructors (RAII).
// PHASE: OOP
// ============================================================

/*
  CONCEPT OVERVIEW:

  CLASS vs STRUCT:
    struct: members are PUBLIC by default
    class:  members are PRIVATE by default
    No other difference in C++. Convention:
    - Use struct for plain data holders (Order, Quote, Level)
    - Use class for objects with behavior and invariants (OrderBook, Strategy)

  CONSTRUCTOR:
    Special method that runs when an object is created.
    Same name as the class, no return type.
    Types:
      Default constructor:      Order()               — no arguments
      Parameterized constructor: Order(id, price, qty) — takes arguments
      Copy constructor:          Order(const Order&)   — covered in L21
      Member initializer list:   Order() : field(val), field2(val2) {}
        — ALWAYS prefer initializer list over assignment in body
        — Directly constructs members, vs body assignment which constructs then assigns

  DESTRUCTOR:
    ~Order()  — runs automatically when object goes out of scope or is deleted
    Used for: releasing resources, closing handles, logging, cleanup
    If no destructor defined: compiler provides a no-op one
    RAII pattern: destructor guarantees cleanup regardless of how scope exits

  THIS POINTER:
    Inside any method, 'this' is a pointer to the current object.
    this->field is the same as field (but needed when parameter shadows the field).

  CONST METHODS:
    void print() const;  — method that does NOT modify the object
    Can be called on const objects. Cannot call non-const methods from inside.
    Mark ALL methods that don't change state as const — it's enforced by compiler.

  STATIC MEMBERS:
    static int count;          — one copy shared across ALL instances
    static void reset();       — static method: no 'this', no access to instance data
    Used for: order ID counters, shared config, singleton patterns

  TRADING USE CASE:
    class Order {
        uint64_t id_;        // private: no direct external access
        double   price_;
        int32_t  qty_;
        Side     side_;
    public:
        Order(uint64_t id, double price, int32_t qty, Side side);
        void   reduce_qty(int32_t n) { qty_ -= n; }
        double price() const { return price_; }   // const: read-only accessor
        bool   is_filled() const { return qty_ == 0; }
    };

  COMMON MISTAKES:
    - Forgetting the trailing semicolon after the closing } of a class
    - Assigning in constructor body instead of using initializer list
    - Not marking read-only methods as const
    - Accessing static member via instance (use ClassName::member instead)
*/

#include <iostream>
#include <string>
#include <cstdint>

// ============================================================
// ORDER CLASS — the central data type of any trading system
// ============================================================

class Order {
public:
    // --- Enums nested inside the class (scoped to Order::) ---
    enum class Side { BUY, SELL };
    enum class Type { LIMIT, MARKET, IOC, FOK };
    enum class Status { NEW, PARTIAL, FILLED, CANCELLED, REJECTED };

    // --- CONSTRUCTORS ---

    // Default constructor: creates an empty/invalid order
    Order()
        : id_(0), price_(0.0), qty_(0), remaining_qty_(0)
        , side_(Side::BUY), type_(Type::LIMIT), status_(Status::NEW)
    {
        ++order_count_;   // track how many orders have been created
        std::cout << "[Order] Default constructed (id=0)\n";
    }

    // Parameterized constructor: the one you'll actually use
    // Initializer list: constructs members directly — preferred over body assignment
    Order(uint64_t id, double price, int32_t qty, Side side, Type type = Type::LIMIT)
        : id_(id), price_(price), qty_(qty), remaining_qty_(qty)
        , side_(side), type_(type), status_(Status::NEW)
    {
        ++order_count_;
        std::cout << "[Order] Constructed #" << id_ << "\n";
    }

    // --- DESTRUCTOR ---
    ~Order() {
        --order_count_;
        std::cout << "[Order] Destroyed #" << id_ << "\n";
    }

    // --- CONST METHODS (read-only: don't modify the object) ---

    uint64_t id()            const { return id_; }
    double   price()         const { return price_; }
    int32_t  qty()           const { return qty_; }
    int32_t  remaining_qty() const { return remaining_qty_; }
    Side     side()          const { return side_; }
    Status   status()        const { return status_; }

    bool is_buy()    const { return side_ == Side::BUY; }
    bool is_filled() const { return remaining_qty_ == 0; }
    bool is_active() const { return status_ == Status::NEW || status_ == Status::PARTIAL; }

    // Compute notional value (read-only calculation — const method)
    double notional() const { return price_ * qty_; }

    // Print the order summary
    void print() const {
        std::cout << "Order #" << id_
                  << " " << (side_ == Side::BUY ? "BUY" : "SELL")
                  << " " << qty_ << " (rem:" << remaining_qty_ << ")"
                  << " @ $" << price_
                  << " [" << status_name() << "]\n";
    }

    // --- NON-CONST METHODS (modify the object) ---

    // Partially or fully fill this order
    void fill(int32_t fill_qty) {
        if (fill_qty <= 0 || fill_qty > remaining_qty_) {
            std::cout << "[Error] Invalid fill qty: " << fill_qty << "\n";
            return;
        }
        remaining_qty_ -= fill_qty;
        status_ = (remaining_qty_ == 0) ? Status::FILLED : Status::PARTIAL;
        std::cout << "[Fill] #" << id_ << " filled " << fill_qty
                  << ", remaining: " << remaining_qty_ << "\n";
    }

    void cancel() {
        status_ = Status::CANCELLED;
        std::cout << "[Cancel] Order #" << id_ << " cancelled\n";
    }

    void reject(const std::string& reason) {
        status_ = Status::REJECTED;
        std::cout << "[Reject] Order #" << id_ << ": " << reason << "\n";
    }

    // --- STATIC MEMBERS ---

    // One count shared across ALL Order instances — how many are alive right now
    static int active_count() { return order_count_; }

    // Static factory method: next auto-generated order ID
    static uint64_t next_id() {
        static uint64_t id_seq = 10000000;
        return ++id_seq;
    }

private:
    // --- FIELDS (all private — access via methods only) ---
    uint64_t id_;
    double   price_;
    int32_t  qty_;
    int32_t  remaining_qty_;
    Side     side_;
    Type     type_;
    Status   status_;

    // Static: shared across ALL Order instances (not per-object)
    static int order_count_;

    // Private helper method — not part of the public API
    const char* status_name() const {
        switch (status_) {
            case Status::NEW:       return "NEW";
            case Status::PARTIAL:   return "PARTIAL";
            case Status::FILLED:    return "FILLED";
            case Status::CANCELLED: return "CANCELLED";
            case Status::REJECTED:  return "REJECTED";
            default:                return "UNKNOWN";
        }
    }
};

// Static member must be defined OUTSIDE the class (in one .cpp file)
int Order::order_count_ = 0;

// ============================================================
// QUOTE STRUCT — plain data holder (struct, not class)
// ============================================================
// Use struct for simple data with no behavior or invariants
struct Quote {
    std::string symbol;
    double      bid;
    double      ask;
    int32_t     bid_size;
    int32_t     ask_size;
    uint64_t    timestamp_ns;   // nanoseconds since epoch

    double spread() const { return ask - bid; }
    double mid()    const { return (bid + ask) / 2.0; }
};

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // CONSTRUCTORS
    // -------------------------------------------------------

    std::cout << "--- Order construction ---\n";
    std::cout << "Active orders before: " << Order::active_count() << "\n";

    {
        // Parameterized constructor
        Order buy_order(Order::next_id(), 182.50, 100, Order::Side::BUY);
        buy_order.print();

        Order sell_order(Order::next_id(), 183.00, 50, Order::Side::SELL, Order::Type::IOC);
        sell_order.print();

        std::cout << "Active orders (2 alive): " << Order::active_count() << "\n";

        // -------------------------------------------------------
        // METHODS
        // -------------------------------------------------------

        std::cout << "\n--- Order fill lifecycle ---\n";
        buy_order.print();
        buy_order.fill(30);   // partial fill: 100 → 70 remaining
        buy_order.print();
        buy_order.fill(70);   // final fill: 70 → 0 remaining
        buy_order.print();
        std::cout << "Is filled: " << buy_order.is_filled() << "\n";

        // Reject the sell order
        sell_order.reject("Exceeds daily loss limit");
        sell_order.print();

        // Const methods work on const objects too
        const Order& const_ref = sell_order;
        std::cout << "Notional: $" << const_ref.notional() << "\n";
        // const_ref.cancel();   // COMPILE ERROR: cancel() is not const

        std::cout << "Active orders before scope exit: " << Order::active_count() << "\n";

    }   // buy_order and sell_order destructors run here

    std::cout << "Active orders after scope: " << Order::active_count() << "\n";

    // -------------------------------------------------------
    // STRUCT: Quote (plain data holder)
    // -------------------------------------------------------

    std::cout << "\n--- Quote struct ---\n";

    Quote q{"AAPL", 182.45, 182.55, 500, 300, 1700000000000000000ULL};
    std::cout << "Symbol: " << q.symbol
              << " Bid: $" << q.bid
              << " Ask: $" << q.ask
              << " Spread: $" << q.spread()
              << " Mid: $" << q.mid() << "\n";

    // -------------------------------------------------------
    // STACK vs HEAP CONSTRUCTION
    // -------------------------------------------------------

    std::cout << "\n--- Stack vs heap construction ---\n";

    // Stack: automatic lifetime — destroyed when scope ends
    Order stack_order(Order::next_id(), 185.00, 200, Order::Side::BUY);
    stack_order.print();

    // Heap: manual — must delete explicitly (or use unique_ptr — L23)
    Order* heap_order = new Order(Order::next_id(), 185.50, 100, Order::Side::SELL);
    heap_order->print();
    delete heap_order;   // destructor runs here
    heap_order = nullptr;

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      A full order lifecycle in a live system:

        // Order arrives from strategy
        Order o(Order::next_id(), signal.price, signal.qty, signal.side);

        // Pre-trade risk check (read-only: const Order&)
        if (!risk.check(o)) {
            o.reject("Risk limit breach");
            return;
        }

        // Send to exchange
        gateway.send(o);
        o.print();  // log: NEW

        // Exchange sends back partial fill
        o.fill(partial_qty);
        o.print();  // log: PARTIAL

        // Exchange sends back remaining fill
        o.fill(o.remaining_qty());
        o.print();  // log: FILLED

        // o destructor runs when it goes out of scope — no leak, no manual cleanup
    */
}
