// ============================================================
// L14: Dynamic Memory — Heap vs Stack, new/delete, Memory Pools
// ============================================================
// WHAT: Two memory regions: stack (automatic, fast, limited size)
//       and heap (manual, flexible, unlimited but slower).
//       new allocates on heap, delete frees it.
// WHY (TRADING): This is one of the most critical HFT concepts.
//   malloc/new during trading hours = LATENCY SPIKES.
//   Real HFT systems pre-allocate ALL memory at startup and
//   reuse it throughout the trading day. Understanding why
//   dynamic allocation is slow drives the architecture of
//   every professional trading system.
// PHASE: Foundation
// ============================================================

/*
  CONCEPT OVERVIEW:

  STACK MEMORY:
    - Allocated automatically when a variable is declared
    - Freed automatically when the variable goes out of scope
    - Fast: just moving a stack pointer (one instruction)
    - Limited: typically 1-8MB per thread (OS-configurable)
    - Use for: local variables, small fixed-size arrays, function arguments

  HEAP MEMORY:
    - Allocated explicitly with new (or malloc in C)
    - You must free it explicitly with delete (or free in C)
    - Slow: malloc/new involves searching free lists, possibly OS calls
    - Unlimited: only limited by available RAM
    - Use for: large data structures, data that needs to outlive a function,
               data whose size is unknown at compile time

  NEW AND DELETE:
    T* p  = new T;          — allocate ONE object on the heap
    T* p  = new T(args);    — allocate + construct with args
    T* p  = new T[n];       — allocate array of n objects
    delete p;               — free one object (calls destructor first)
    delete[] p;             — free array (MUST match new[])
    Mismatching: delete vs delete[] = undefined behavior (crash)

  MEMORY LEAKS:
    Forgetting to call delete = the memory is never returned to the OS.
    In a trading system running 6.5 hours, even a small leak per tick
    can eat all available RAM.

  WHY new/delete IS BANNED IN HFT HOT PATHS:
    1. Non-deterministic latency: malloc can take anywhere from 100ns to 100µs
       depending on heap fragmentation and OS scheduling
    2. Thread contention: the global allocator has a lock
    3. Cache pollution: heap memory may be cold (not in CPU cache)

  SOLUTION: PRE-ALLOCATION + MEMORY POOLS
    At startup: allocate a large slab of memory once
    During trading: carve out pieces from the slab (no OS calls)
    End of day: release the slab once

    Order pool: pre-allocate 10,000 Order objects, hand them out from
    a free list, return them when done — zero allocation during trading.

  SMART POINTERS (preview — covered fully in L23):
    unique_ptr<T>  — auto-deletes when it goes out of scope
    shared_ptr<T>  — reference counted, auto-deletes when count hits 0
    Use these in NON-HOT paths to avoid memory leaks safely.

  TRADING USE CASE:
    // STARTUP: allocate once
    Order* order_pool = new Order[MAX_ORDERS];   // or use a proper pool allocator
    // TRADING HOURS: use pre-allocated memory (no new/delete in hot path)
    Order* o = allocate_from_pool();   // O(1), no OS call
    // END OF DAY: release once
    delete[] order_pool;

  COMMON MISTAKES:
    - Memory leak: new without delete
    - Double free: delete called twice on the same pointer → crash
    - Use after free: using a pointer after delete → undefined behavior
    - Array delete mismatch: new[] paired with delete (not delete[])
    - Stack overflow: allocating huge arrays on the stack
*/

#include <iostream>
#include <cstdint>
#include <cstring>   // memset

// -------------------------------------------------------
// SIMPLE MEMORY POOL — the HFT allocation pattern
// -------------------------------------------------------
// Pre-allocates N objects, hands them out via a free stack,
// returns them for reuse. Zero calls to malloc during trading.

struct Order {
    uint64_t id;
    double   price;
    int32_t  qty;
    uint8_t  side;
    bool     in_use;
};

class OrderPool {
public:
    static constexpr int POOL_SIZE = 8;   // small for demo; real systems use 10,000+

    OrderPool() {
        // Allocate the entire pool ONCE at construction (startup)
        pool_ = new Order[POOL_SIZE];
        std::memset(pool_, 0, sizeof(Order) * POOL_SIZE);  // zero-initialize

        // Build free stack: indices of available slots
        for (int i = 0; i < POOL_SIZE; ++i) {
            free_stack_[i] = i;
        }
        free_count_ = POOL_SIZE;
        std::cout << "[Pool] Pre-allocated " << POOL_SIZE << " orders\n";
    }

    ~OrderPool() {
        delete[] pool_;   // cleanup ONCE at shutdown
        std::cout << "[Pool] Released pool memory\n";
    }

    // O(1), no malloc — just pop an index off the free stack
    Order* allocate() {
        if (free_count_ == 0) return nullptr;   // pool exhausted
        int idx = free_stack_[--free_count_];
        pool_[idx].in_use = true;
        return &pool_[idx];
    }

    // O(1), no free — just push the index back onto the free stack
    void release(Order* order) {
        if (!order) return;
        int idx = static_cast<int>(order - pool_);  // pointer arithmetic: which slot?
        order->in_use = false;
        free_stack_[free_count_++] = idx;
    }

    int available() const { return free_count_; }

private:
    Order* pool_;
    int    free_stack_[POOL_SIZE];
    int    free_count_;
};

// -------------------------------------------------------
// MAIN
// -------------------------------------------------------

int main() {

    // -------------------------------------------------------
    // STACK vs HEAP: where does memory come from?
    // -------------------------------------------------------

    std::cout << "--- Stack vs Heap ---\n";

    // STACK: automatic, instant, freed when this block ends
    {
        double stack_price = 182.50;          // stack: allocated in one instruction
        int    stack_qty   = 100;
        std::cout << "Stack price: $" << stack_price << "\n";
        // stack_price and stack_qty are automatically freed here when } is reached
    }
    // stack_price no longer accessible here

    // HEAP: manual, slower to allocate, must be freed manually
    double* heap_price = new double(182.50);  // allocate ONE double on heap
    std::cout << "Heap price: $" << *heap_price << "\n";
    delete heap_price;   // free it — if you forget, this is a MEMORY LEAK
    heap_price = nullptr;  // good habit: null out after delete to prevent use-after-free

    // -------------------------------------------------------
    // NEW/DELETE FOR SINGLE OBJECTS
    // -------------------------------------------------------

    std::cout << "\n--- new/delete for single object ---\n";

    Order* order = new Order{1001, 185.00, 100, 0, true};   // allocate on heap
    std::cout << "Heap order: #" << order->id << " @ $" << order->price << "\n";
    delete order;          // free the memory
    order = nullptr;       // prevent accidental use-after-free

    // -------------------------------------------------------
    // NEW[]/DELETE[] FOR ARRAYS
    // -------------------------------------------------------

    std::cout << "\n--- new[]/delete[] for arrays ---\n";

    const int NUM_ORDERS = 5;
    Order* orders = new Order[NUM_ORDERS];   // allocate 5 Orders on heap

    // Initialize them
    for (int i = 0; i < NUM_ORDERS; ++i) {
        orders[i].id    = 2000 + i;
        orders[i].price = 185.00 + i * 0.05;
        orders[i].qty   = 100;
        orders[i].side  = (i % 2 == 0) ? 0 : 1;  // alternate BUY/SELL
    }

    for (int i = 0; i < NUM_ORDERS; ++i) {
        std::cout << "Order #" << orders[i].id
                  << " " << (orders[i].side == 0 ? "BUY" : "SELL")
                  << " @ $" << orders[i].price << "\n";
    }

    delete[] orders;   // MUST use delete[] for arrays (not delete)
    orders = nullptr;

    // -------------------------------------------------------
    // WHY malloc IS SLOW — demonstration of variance
    // -------------------------------------------------------

    std::cout << "\n--- Why dynamic allocation is unpredictable ---\n";

    // The time to allocate on the heap varies enormously depending on:
    // 1. Heap fragmentation (how scattered free blocks are)
    // 2. Whether the OS needs to provide more memory (page fault)
    // 3. Lock contention (other threads allocating simultaneously)
    //
    // In HFT, even a 10µs spike in allocation time can cause:
    // - Missed trading opportunities
    // - Order submissions arriving too late
    // - Risk checks lagging behind real-time positions
    //
    // This is why all allocation happens at STARTUP:
    std::cout << "In HFT: allocate at startup, reuse throughout the day.\n";
    std::cout << "No new/delete calls during trading hours.\n";

    // -------------------------------------------------------
    // MEMORY POOL — the real HFT pattern
    // -------------------------------------------------------

    std::cout << "\n--- Memory Pool (HFT allocation pattern) ---\n";

    OrderPool pool;   // pre-allocates POOL_SIZE orders at startup
    std::cout << "Available slots: " << pool.available() << "\n";

    // "Allocate" orders from pool — O(1), no malloc, deterministic latency
    Order* o1 = pool.allocate();
    Order* o2 = pool.allocate();
    Order* o3 = pool.allocate();

    if (o1 && o2 && o3) {
        o1->id = 3001; o1->price = 182.50; o1->qty = 100; o1->side = 0;
        o2->id = 3002; o2->price = 182.55; o2->qty =  50; o2->side = 1;
        o3->id = 3003; o3->price = 182.45; o3->qty = 200; o3->side = 0;

        std::cout << "Order #" << o1->id << " allocated from pool\n";
        std::cout << "Order #" << o2->id << " allocated from pool\n";
        std::cout << "Order #" << o3->id << " allocated from pool\n";
        std::cout << "Available after 3 allocs: " << pool.available() << "\n";
    }

    // "Free" orders back to pool — O(1), no free(), no OS call
    pool.release(o1);
    pool.release(o2);
    std::cout << "Available after 2 releases: " << pool.available() << "\n";

    // Slot reused immediately (same memory, no allocation overhead)
    Order* o4 = pool.allocate();
    if (o4) {
        o4->id = 3004;
        std::cout << "Order #" << o4->id << " reused a slot\n";
    }

    pool.release(o3);
    pool.release(o4);
    std::cout << "All orders released. Available: " << pool.available() << "\n";

    // Pool destructor called here: delete[] pool_ once at shutdown

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Real-world startup sequence of an HFT system:

        void initialize() {
            // Allocate everything at once — never allocate during trading
            order_pool   = new OrderPool(MAX_ORDERS);         // 10,000 orders
            message_buf  = new uint8_t[MAX_MSG_SIZE * 1024];  // 1MB message buffer
            book_memory  = new BookLevel[SYMBOLS * LEVELS];   // order book storage
            log_queue    = new LogEntry[LOG_QUEUE_SIZE];       // async log buffer

            // Pre-fault all the pages (force OS to map physical memory NOW)
            memset(order_pool, 0, sizeof(*order_pool));
            // Now all pages are in physical RAM — no page faults during trading
        }

        void shutdown() {
            // Free everything once, cleanly
            delete order_pool;
            delete[] message_buf;
            // etc.
        }

      Page-faulting at startup instead of during trading is critical:
      a single page fault can take 50-100µs — enough to miss a signal.
    */
}
