// ============================================================
// L44: Custom Allocators and Memory Pools
// ============================================================
// WHAT: A memory pool pre-allocates a large slab of memory at
//       startup and hands out fixed-size chunks from it in O(1)
//       without calling malloc/free. An arena allocator bumps a
//       pointer forward for each allocation and frees everything
//       at once. Both eliminate malloc overhead in the hot path.
// WHY (TRADING): std::malloc/new takes 50-500ns and is
//   non-deterministic (depends on heap fragmentation state).
//   Worse: it acquires a global lock — two threads calling new
//   simultaneously contend on that lock.
//   In HFT: every Order, every Level, every Tick object must
//   be allocated in < 10ns. Solution: pre-allocate at startup,
//   reuse objects from a pool. malloc/new are BANNED from all
//   hot paths. This is probably the single most impactful
//   low-latency technique after CPU pinning.
// PHASE: Low-Latency Systems
// ============================================================

/*
  CONCEPT OVERVIEW:

  WHY MALLOC IS BAD IN HOT PATH:
    1. Latency: 50-500ns, non-deterministic (depends on heap state)
    2. Locking: glibc malloc acquires a global lock per call
    3. Fragmentation: heap fragments over time → cache misses
    4. jemalloc / tcmalloc: better, but still 50-100ns
    5. The fix: never call malloc during trading hours

  POOL ALLOCATOR:
    Pre-allocate N objects at startup in a contiguous array.
    Maintain a free list (stack of available indices).
    alloc() = pop from free stack → O(1), no syscall
    free()  = push to free stack → O(1), no syscall
    Works for: Order objects, Level objects, ITCH messages.

  ARENA ALLOCATOR:
    Allocate from a contiguous region by bumping a pointer.
    No per-object free — free the entire arena at once.
    alloc(n bytes) = ptr; ptr += n; → O(1), just a pointer add
    Works for: per-message parse buffers, per-request temp state.
    Pattern: allocate objects for one message, process it, reset arena.

  STD::ALLOCATOR INTERFACE:
    Custom allocators can be plugged into STL containers:
    std::vector<T, MyAllocator<T>> — uses your allocator for elements.
    std::unordered_map<K,V, Hash, Eq, PoolAllocator<std::pair<K,V>>>
    This lets you use STL with pool-backed allocation in hot paths.

  PLACEMENT NEW:
    new(ptr) T(args...)  — construct T at an existing memory address.
    No allocation — just calls the constructor.
    Use in: pool allocator (memory pre-allocated, just construct in-place).
    Paired with explicit destructor call: obj->~T();

  TRADING USE CASE:
    // At startup:
    OrderPool   order_pool(10000);   // 10K orders pre-allocated
    LevelPool   level_pool(100000);  // 100K price levels
    MessageArena msg_arena(65536);   // 64KB parse buffer

    // Hot path:
    Order* o = order_pool.alloc();   // O(1), no malloc
    o->price = 1825000; o->qty = 100;
    // ... process ...
    order_pool.free(o);              // O(1), no free()

  COMMON MISTAKES:
    - Forgetting to call the destructor before returning to pool
      (leave a dangling std::string or std::vector — memory leak or corruption)
    - Pool overflow: running out of pre-allocated objects during a fast market
      (fix: allocate 5-10x your expected peak, log near-overflow)
    - Thread-safety: pool allocator shown here is NOT thread-safe.
      Each thread should have its own pool, OR protect with spinlock.
    - Using placement new on misaligned memory (UB on some platforms)
    - Arena never being reset → effectively a memory leak during long sessions
*/

#include <iostream>
#include <vector>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <chrono>
#include <new>         // placement new, std::launder
#include <type_traits> // std::is_trivially_destructible_v

// ============================================================
// POOL ALLOCATOR — fixed-size objects, O(1) alloc/free
// ============================================================

template<typename T, int N>
class PoolAllocator {
    static_assert(N > 0, "Pool size must be positive");

public:
    PoolAllocator() {
        // Build free list: stack of all available indices (0..N-1)
        // We push them in reverse so index 0 is allocated first
        for (int i = N - 1; i >= 0; --i) {
            free_stack_[free_top_++] = i;
        }
    }

    // Allocate one T from the pool — O(1), no malloc
    T* alloc() {
        if (free_top_ == 0) return nullptr;  // pool exhausted
        int idx = free_stack_[--free_top_];
        T* ptr = reinterpret_cast<T*>(&storage_[idx]);
        return ptr;   // caller must construct with placement new or direct assignment
    }

    // Initialize (allocate + construct)
    template<typename... Args>
    T* construct(Args&&... args) {
        T* ptr = alloc();
        if (!ptr) return nullptr;
        return new(ptr) T(std::forward<Args>(args)...);  // placement new
    }

    // Free one object back to the pool — O(1), no free()
    void free(T* ptr) {
        if (!ptr) return;

        // Compute which slot this pointer belongs to
        auto* base = reinterpret_cast<T*>(&storage_[0]);
        int idx = static_cast<int>(ptr - base);
        assert(idx >= 0 && idx < N && "Pointer not from this pool");

        free_stack_[free_top_++] = idx;
    }

    // Destroy and return to pool
    void destroy(T* ptr) {
        if (!ptr) return;
        ptr->~T();   // call destructor explicitly
        free(ptr);
    }

    int capacity()  const { return N; }
    int available() const { return free_top_; }
    int in_use()    const { return N - free_top_; }

private:
    // Raw aligned storage for N objects — NO default construction
    alignas(T) std::byte storage_[N][sizeof(T)];

    int free_stack_[N];
    int free_top_ = 0;
};

// ============================================================
// ARENA ALLOCATOR — bump-pointer, reset entire arena at once
// ============================================================

class ArenaAllocator {
public:
    explicit ArenaAllocator(size_t capacity)
        : buf_(new std::byte[capacity])
        , cap_(capacity)
        , used_(0)
    {}

    // Allocate n bytes aligned to `align` — O(1), just a pointer bump
    void* alloc(size_t n, size_t align = alignof(std::max_align_t)) {
        // Round up current offset to alignment
        size_t aligned_used = (used_ + align - 1) & ~(align - 1);
        if (aligned_used + n > cap_) return nullptr;  // arena full

        void* ptr = buf_.get() + aligned_used;
        used_ = aligned_used + n;
        return ptr;
    }

    // Allocate and construct a T
    template<typename T, typename... Args>
    T* make(Args&&... args) {
        void* mem = alloc(sizeof(T), alignof(T));
        if (!mem) return nullptr;
        return new(mem) T(std::forward<Args>(args)...);
    }

    // Reset: all prior allocations are invalidated. Extremely fast.
    void reset() { used_ = 0; }

    size_t used()      const { return used_; }
    size_t capacity()  const { return cap_; }
    size_t remaining() const { return cap_ - used_; }

private:
    std::unique_ptr<std::byte[]> buf_;
    size_t cap_, used_;
};

// ============================================================
// TRADING TYPES
// ============================================================

struct Order {
    int64_t  price;
    int32_t  qty;
    int32_t  remain_qty;
    uint64_t order_id;
    bool     is_buy;
    uint8_t  status;

    Order() = default;
    Order(int64_t p, int32_t q, uint64_t id, bool buy)
        : price(p), qty(q), remain_qty(q), order_id(id)
        , is_buy(buy), status(0)
    {}
    ~Order() { status = 255; }  // mark destroyed for debugging
};

struct ParsedMessage {
    char    type;
    char    symbol[8];
    int64_t price;
    int32_t qty;
};

// ============================================================
// BENCHMARK: malloc vs pool
// ============================================================

template<typename Fn>
uint64_t time_ns(Fn fn, int reps) {
    auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < reps; ++i) fn();
    auto t1 = std::chrono::steady_clock::now();
    return static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());
}

// ============================================================
// CUSTOM STL ALLOCATOR — plugs pool into std::vector
// ============================================================

// A minimal STL-compatible allocator backed by a global pool
// (in real code: pass a reference to your specific pool)
template<typename T>
struct PoolStlAllocator {
    using value_type = T;

    PoolStlAllocator() = default;
    template<typename U> PoolStlAllocator(const PoolStlAllocator<U>&) noexcept {}

    T* allocate(size_t n) {
        // Fallback to malloc for demo — in real code: use your pool
        void* ptr = ::operator new(n * sizeof(T));
        return static_cast<T*>(ptr);
    }
    void deallocate(T* ptr, size_t) noexcept {
        ::operator delete(ptr);
    }

    bool operator==(const PoolStlAllocator&) const noexcept { return true; }
    bool operator!=(const PoolStlAllocator&) const noexcept { return false; }
};

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // POOL ALLOCATOR BASIC TEST
    // -------------------------------------------------------

    std::cout << "=== Pool allocator ===\n";

    {
        PoolAllocator<Order, 16> pool;

        std::cout << "  Pool capacity: " << pool.capacity() << "\n";
        std::cout << "  Initially available: " << pool.available() << "\n";

        // Construct 5 orders
        std::vector<Order*> orders;
        for (int i = 0; i < 5; ++i) {
            Order* o = pool.construct(
                int64_t(1825000 + i * 100), int32_t(100),
                uint64_t(1000 + i), bool(i % 2 == 0));
            orders.push_back(o);
            std::cout << "  Allocated order #" << o->order_id
                      << " @ $" << o->price / 10000.0 << "\n";
        }

        std::cout << "  In use: " << pool.in_use()
                  << ", available: " << pool.available() << "\n";

        // Return 3 orders to pool
        for (int i = 0; i < 3; ++i) {
            std::cout << "  Freeing order #" << orders[i]->order_id << "\n";
            pool.destroy(orders[i]);
            orders[i] = nullptr;
        }

        std::cout << "  After frees: in_use=" << pool.in_use()
                  << " available=" << pool.available() << "\n";
    }

    // -------------------------------------------------------
    // ARENA ALLOCATOR
    // -------------------------------------------------------

    std::cout << "\n=== Arena allocator ===\n";

    {
        ArenaAllocator arena(4096);   // 4KB for one message's worth of parse state

        // Parse several objects from one incoming message — all on the arena
        auto* header = arena.make<ParsedMessage>();
        header->type = 'A';
        std::memcpy(header->symbol, "AAPL\0\0\0\0", 8);
        header->price = 1825000;
        header->qty   = 100;

        auto* footer = arena.make<ParsedMessage>();
        footer->type = 'X';
        footer->qty  = 0;

        std::cout << "  Arena used: " << arena.used() << "/" << arena.capacity() << " bytes\n";
        std::cout << "  Header: type=" << header->type
                  << " symbol=" << header->symbol
                  << " price=$" << header->price / 10000.0 << "\n";

        // Done with this message: reset arena in O(1) — all objects invalidated
        arena.reset();
        std::cout << "  After reset: used=" << arena.used() << " bytes\n";

        // Next message: reuse the same arena memory
        auto* next = arena.make<ParsedMessage>();
        next->type = 'D';
        std::cout << "  Reused arena for next message\n";
    }

    // -------------------------------------------------------
    // BENCHMARK: new/delete vs pool
    // -------------------------------------------------------

    std::cout << "\n=== Benchmark: new/delete vs pool ===\n";

    {
        const int REPS = 10000;

        // Warmup
        {
            auto* p = new Order(1825000, 100, 1, true);
            delete p;
        }

        uint64_t malloc_ns = time_ns([&]() {
            auto* o = new Order(1825000, 100, 1, true);
            delete o;
        }, REPS);

        PoolAllocator<Order, 64> pool;
        uint64_t pool_ns = time_ns([&]() {
            Order* o = pool.construct(1825000, 100, 1ULL, true);
            pool.destroy(o);
        }, REPS);

        std::cout << "  " << REPS << " alloc+free cycles:\n";
        std::cout << "    new/delete: " << malloc_ns << "ns (" << malloc_ns / REPS << "ns each)\n";
        std::cout << "    pool:       " << pool_ns   << "ns (" << pool_ns   / REPS << "ns each)\n";
        if (pool_ns > 0) {
            std::cout << "    Speedup: " << double(malloc_ns) / pool_ns << "x\n";
        }
    }

    // -------------------------------------------------------
    // PLACEMENT NEW DEMO
    // -------------------------------------------------------

    std::cout << "\n=== Placement new ===\n";

    {
        // Allocate raw memory (could come from a pool or arena)
        alignas(Order) std::byte raw[sizeof(Order)];

        // Construct Order at this memory location — no allocation
        Order* o = new(raw) Order(1825500, 200, 9999ULL, false);
        std::cout << "  Placed Order: id=" << o->order_id
                  << " price=$" << o->price / 10000.0 << "\n";

        // Explicitly destroy (don't call delete — we didn't allocate)
        o->~Order();
        std::cout << "  Order destroyed in place (status=" << (int)o->status << "=255 expected)\n";
    }

    // -------------------------------------------------------
    // POOL OVERFLOW DETECTION
    // -------------------------------------------------------

    std::cout << "\n=== Pool overflow detection ===\n";

    {
        PoolAllocator<Order, 4> tiny_pool;   // deliberately tiny

        std::vector<Order*> ptrs;
        for (int i = 0; i < 6; ++i) {
            Order* o = tiny_pool.alloc();
            if (!o) {
                std::cout << "  Pool overflow at allocation #" << i
                          << " — ALERT: increase pool size!\n";
                break;
            }
            new(o) Order(int64_t(1000 * i), int32_t(10), uint64_t(i), true);
            ptrs.push_back(o);
            std::cout << "  Allocated #" << i << " (remaining=" << tiny_pool.available() << ")\n";
        }
        for (auto* p : ptrs) tiny_pool.destroy(p);
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      How pool allocators fit into the full system:

        // At startup (before any trading):
        constexpr int MAX_ORDERS = 100'000;
        constexpr int MAX_LEVELS = 1'000'000;
        constexpr int MSG_ARENA_SIZE = 64 * 1024;

        PoolAllocator<Order, MAX_ORDERS>  order_pool;
        PoolAllocator<Level, MAX_LEVELS>  level_pool;
        ArenaAllocator                    msg_arena(MSG_ARENA_SIZE);

        // In the hot path (feed thread — NEVER calls malloc):
        void on_packet(const uint8_t* buf, int len) {
            msg_arena.reset();   // O(1): reuse arena for this message

            // Parse into arena-allocated objects (no malloc)
            auto* msg = msg_arena.make<ITCHMessage>(buf, len);

            if (msg->type == 'A') {
                // AddOrder: allocate from pool (O(1))
                Order* o = order_pool.construct(
                    msg->price, msg->qty, msg->order_id, msg->side == 'B');
                book_.add(o);
            }
            else if (msg->type == 'D') {
                // DeleteOrder: find and return to pool
                Order* o = book_.remove(msg->order_id);
                if (o) order_pool.destroy(o);
            }
            // msg_arena goes "out of scope" conceptually — reset at next on_packet()
        }

        // Zero malloc/free calls during the entire trading session.
        // All memory was pre-allocated at startup.
    */
}
