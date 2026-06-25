// ============================================================
// L23: Smart Pointers — unique_ptr, shared_ptr, weak_ptr
// ============================================================
// WHAT: RAII wrappers around raw pointers that automatically
//       call delete when they go out of scope. Prevent memory
//       leaks and double-free bugs without manual delete.
// WHY (TRADING): In trading systems, owning heap objects safely
//   is critical. A leaked strategy object or a double-freed
//   order can crash the entire system. unique_ptr is preferred
//   in HFT (zero overhead vs raw pointer). shared_ptr has an
//   atomic reference count (~10-50ns per copy) — avoid in hot
//   paths. weak_ptr breaks shared_ptr cycles (e.g., circular
//   references between order and fill records).
// PHASE: Modern C++
// ============================================================

/*
  CONCEPT OVERVIEW:

  unique_ptr<T>:
    - Owns ONE object. Cannot be copied, only moved.
    - Destructor calls delete automatically.
    - Zero overhead over raw pointer (no ref count, no extra allocation).
    - Use for: strategy objects, gateway connections, owned subsystems.
    - Make with: std::make_unique<T>(args)  (never write "new" directly)

  shared_ptr<T>:
    - Shared ownership. Multiple shared_ptrs can point to same object.
    - Reference counted: atomically incremented/decremented on copy.
    - Object deleted when last shared_ptr to it is destroyed (count hits 0).
    - COST: atomic ref count = ~10-50ns per copy operation.
            Extra heap allocation for control block.
    - Use for: shared market data snapshots, shared config, shared logger.
    - AVOID IN HOT PATH: copying shared_ptr in a tight loop is expensive.
    - Make with: std::make_shared<T>(args)

  weak_ptr<T>:
    - Non-owning observer of a shared_ptr-managed object.
    - Does NOT increment the ref count.
    - Must call .lock() to get a shared_ptr before use (may return null if expired).
    - Use for: breaking circular references, optional back-references.

  CUSTOM DELETERS:
    unique_ptr<T, Deleter> — use a custom function to release the resource.
    Useful for: file descriptors (close() not delete), socket handles,
    OS resources, memory pool deallocation.

  MAKE_UNIQUE vs NEW:
    ALWAYS use make_unique / make_shared. Never write "new" directly.
    Reason 1: Exception safety — foo(new T, new U) can leak if U throws.
    Reason 2: make_shared does ONE allocation for both object + control block.
    Reason 3: Clearer intent.

  TRADING USE CASE:
    // Strategy ownership: unique_ptr — one owner, auto cleanup
    auto strat = std::make_unique<MomentumStrategy>(1000, 5.0);
    strat->on_quote(q);

    // Shared market data: shared_ptr — multiple readers, no copy of data
    auto snapshot = std::make_shared<OrderBookSnapshot>(book);
    risk_thread.set_snapshot(snapshot);     // shared ownership
    display_thread.set_snapshot(snapshot);  // both see same data

    // Custom deleter: release back to pool instead of delete
    auto order = unique_ptr<Order, OrderPool::Releaser>(pool.acquire(), pool.releaser());

  COMMON MISTAKES:
    - Copying shared_ptr in a hot loop (expensive atomic ops)
    - Creating shared_ptr from a raw pointer multiple times (double free)
    - Circular shared_ptr references without weak_ptr (memory leak)
    - Using unique_ptr where you mean to share ownership
    - enable_shared_from_this misuse (creating shared_ptr from 'this' in constructor)
*/

#include <iostream>
#include <memory>     // unique_ptr, shared_ptr, weak_ptr, make_unique, make_shared
#include <string>
#include <vector>
#include <functional> // std::function

// ============================================================
// TRADING TYPES
// ============================================================

struct Quote { std::string symbol; double bid, ask; };

class Strategy {
public:
    explicit Strategy(std::string name, int max_pos)
        : name_(std::move(name)), max_pos_(max_pos), ticks_(0) {}

    ~Strategy() {
        std::cout << "[Strategy:" << name_ << "] Destroyed after " << ticks_ << " ticks\n";
    }

    void on_quote(const Quote& q) {
        ++ticks_;
        // ... strategy logic ...
    }

    const std::string& name()  const { return name_; }
    int                ticks() const { return ticks_; }

private:
    std::string name_;
    int         max_pos_;
    int         ticks_;
};

// An order book snapshot shared by multiple threads
class BookSnapshot {
public:
    explicit BookSnapshot(int id, double bid, double ask)
        : id_(id), bid_(bid), ask_(ask) {
        std::cout << "[Snapshot #" << id_ << "] Created\n";
    }
    ~BookSnapshot() {
        std::cout << "[Snapshot #" << id_ << "] Released\n";
    }

    double bid() const { return bid_; }
    double ask() const { return ask_; }
    int    id()  const { return id_; }

private:
    int    id_;
    double bid_, ask_;
};

// ============================================================
// OBJECT POOL with custom deleter
// ============================================================

struct Order { uint64_t id; double price; int qty; bool in_use; };

class OrderPool {
public:
    static constexpr int SIZE = 4;

    OrderPool() {
        for (int i = 0; i < SIZE; ++i) {
            orders_[i].in_use = false;
            free_[i] = i;
        }
        free_count_ = SIZE;
    }

    Order* acquire() {
        if (free_count_ == 0) return nullptr;
        int idx = free_[--free_count_];
        orders_[idx].in_use = true;
        std::cout << "[Pool] Acquired slot " << idx << "\n";
        return &orders_[idx];
    }

    void release(Order* o) {
        if (!o) return;
        int idx = static_cast<int>(o - orders_);
        o->in_use = false;
        free_[free_count_++] = idx;
        std::cout << "[Pool] Released slot " << idx << "\n";
    }

    // Returns a deleter lambda — used with unique_ptr custom deleter
    auto make_deleter() {
        return [this](Order* o) { this->release(o); };
    }

private:
    Order orders_[SIZE];
    int   free_[SIZE];
    int   free_count_;
};

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // unique_ptr — single ownership, zero overhead
    // -------------------------------------------------------

    std::cout << "=== unique_ptr ===\n";

    {
        // make_unique<T>(args): preferred over new — no raw pointer exposed
        auto strat = std::make_unique<Strategy>("Momentum", 1000);
        std::cout << "Strategy: " << strat->name() << "\n";

        // Use like a raw pointer — arrow operator works normally
        strat->on_quote({"AAPL", 182.50, 182.55});
        strat->on_quote({"AAPL", 182.55, 182.60});
        std::cout << "Ticks processed: " << strat->ticks() << "\n";

        // unique_ptr CANNOT be copied (only moved)
        // auto copy = strat;   // COMPILE ERROR: copy constructor is deleted

        // CAN be moved: transfer ownership
        auto new_owner = std::move(strat);  // strat is now nullptr
        std::cout << "Moved. strat is null: " << (strat == nullptr) << "\n";
        std::cout << "new_owner ticks: " << new_owner->ticks() << "\n";

        // Can get raw pointer when needed (for APIs that take T*)
        Strategy* raw = new_owner.get();
        raw->on_quote({"AAPL", 182.60, 182.65});

        // release(): gives up ownership (YOU must delete)
        // Strategy* released = new_owner.release();
        // delete released;  // now your responsibility

    }   // new_owner destructor runs here: Strategy automatically deleted

    // -------------------------------------------------------
    // unique_ptr in a vector — polymorphic strategy list
    // -------------------------------------------------------

    std::cout << "\n--- unique_ptr in vector (polymorphic) ---\n";

    {
        std::vector<std::unique_ptr<Strategy>> strategies;
        strategies.push_back(std::make_unique<Strategy>("Momentum",    1000));
        strategies.push_back(std::make_unique<Strategy>("MeanRev",     500));
        strategies.push_back(std::make_unique<Strategy>("StatArb",     750));

        Quote q{"AAPL", 183.00, 183.05};
        for (auto& s : strategies) {
            s->on_quote(q);
            std::cout << s->name() << " processed 1 tick\n";
        }
        // All strategies destroyed when vector goes out of scope — no leaks
    }

    // -------------------------------------------------------
    // shared_ptr — shared ownership, ref counted
    // -------------------------------------------------------

    std::cout << "\n=== shared_ptr ===\n";

    {
        // make_shared does ONE allocation for object + control block (more efficient)
        auto snap1 = std::make_shared<BookSnapshot>(1, 182.50, 182.55);
        std::cout << "Snapshot ref count: " << snap1.use_count() << "\n";  // 1

        {
            auto snap2 = snap1;   // COPY: ref count goes to 2, BOTH own the snapshot
            auto snap3 = snap1;   // ref count → 3
            std::cout << "After 2 copies, ref count: " << snap1.use_count() << "\n";  // 3

            // All three point to the same BookSnapshot object
            std::cout << "snap1 bid: $" << snap1->bid() << "\n";
            std::cout << "snap2 bid: $" << snap2->bid() << "\n";
            std::cout << "snap3 bid: $" << snap3->bid() << "\n";

        }   // snap2 and snap3 destructors: ref count goes to 1

        std::cout << "After inner scope, ref count: " << snap1.use_count() << "\n";  // 1

    }   // snap1 destructor: ref count → 0 → BookSnapshot deleted

    // -------------------------------------------------------
    // shared_ptr performance warning
    // -------------------------------------------------------

    std::cout << "\n--- shared_ptr performance note ---\n";

    {
        auto shared = std::make_shared<BookSnapshot>(2, 183.00, 183.05);

        // In a hot loop: use a REFERENCE to avoid atomic ref count ops
        // BAD (copies shared_ptr 1M times — 1M atomic ops):
        //   for (int i = 0; i < 1'000'000; ++i) {
        //       auto local = shared;   // atomic increment + decrement each iteration
        //       process(local->bid());
        //   }

        // GOOD: take a reference OR raw pointer once, use in loop
        const BookSnapshot& snap_ref = *shared;  // no ref count change
        for (int i = 0; i < 3; ++i) {
            // snap_ref.bid() — no atomic operation, same speed as raw pointer
            std::cout << "Tick " << i << " bid: $" << snap_ref.bid() << "\n";
        }
    }

    // -------------------------------------------------------
    // weak_ptr — non-owning observer
    // -------------------------------------------------------

    std::cout << "\n=== weak_ptr ===\n";

    {
        std::weak_ptr<BookSnapshot> weak;

        {
            auto shared = std::make_shared<BookSnapshot>(3, 184.00, 184.05);
            weak = shared;   // weak_ptr observes but does NOT increment ref count
            std::cout << "shared ref count: " << shared.use_count() << "\n";  // still 1

            // To use weak_ptr: call .lock() to get a temporary shared_ptr
            if (auto locked = weak.lock()) {
                std::cout << "Locked snapshot bid: $" << locked->bid() << "\n";
                std::cout << "Ref count while locked: " << locked.use_count() << "\n";  // 2
            }

        }   // shared destroyed: ref count → 0, BookSnapshot deleted

        // After shared is gone, weak.lock() returns nullptr
        if (auto locked = weak.lock()) {
            std::cout << "Still alive\n";
        } else {
            std::cout << "weak_ptr expired — object was destroyed\n";
        }
    }

    // -------------------------------------------------------
    // CUSTOM DELETER — return to pool instead of delete
    // -------------------------------------------------------

    std::cout << "\n=== Custom deleter (pool return) ===\n";

    {
        OrderPool pool;

        // unique_ptr with custom deleter: when the ptr goes out of scope,
        // it calls pool.release() instead of delete
        {
            auto deleter = pool.make_deleter();
            std::unique_ptr<Order, decltype(deleter)> o1(pool.acquire(), deleter);
            std::unique_ptr<Order, decltype(deleter)> o2(pool.acquire(), deleter);

            if (o1 && o2) {
                o1->id = 5001; o1->price = 185.00; o1->qty = 100;
                o2->id = 5002; o2->price = 185.05; o2->qty =  50;
                std::cout << "Using Order #" << o1->id << " and #" << o2->id << "\n";
                std::cout << "Pool available: " << pool.available() << "\n";
            }
        }   // unique_ptr destructors: call pool.release() — NOT delete
        std::cout << "Pool available after scope: " << pool.available() << "\n";
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      How a real trading system uses smart pointers:

        // Startup: create subsystems (unique ownership)
        auto risk    = std::make_unique<RiskManager>(config);
        auto gateway = std::make_unique<ExchangeGateway>(config);
        auto book    = std::make_unique<OrderBook>("AAPL");

        // Strategy gets shared access to the book (read-only)
        auto book_view = std::shared_ptr<const OrderBook>(book.get(), [](auto*){});
        // null deleter: strategy observes but doesn't own

        // Snapshot shared between risk thread and display thread:
        auto snapshot = std::make_shared<BookSnapshot>(book->snapshot());
        risk_thread.update_snapshot(snapshot);   // shared_ptr copy: ref count = 2
        display_thread.update_snapshot(snapshot);// shared_ptr copy: ref count = 3

        // Tick loop uses raw reference into shared snapshot (no atomic ops)
        const auto& snap = *snapshot;
        while (running) {
            strategy->on_tick(snap.bid(), snap.ask());  // zero overhead
        }
    */
}
