// ============================================================
// L22: Templates and Generic Programming
// ============================================================
// WHAT: Templates let you write code once that works for any
//       type. The compiler generates a specialized version for
//       each type you use it with. Zero runtime overhead.
// WHY (TRADING): Templates power the reusable infrastructure
//   of every HFT system: RingBuffer<Tick>, OrderPool<Order>,
//   SPSCQueue<Message>. You write the data structure once and
//   it works for any type with zero performance cost. Templates
//   are also the foundation of CRTP (L19), std::vector,
//   std::map, and all STL containers. They are preferred over
//   void* in all modern C++.
// PHASE: OOP
// ============================================================

/*
  CONCEPT OVERVIEW:

  FUNCTION TEMPLATES:
    template<typename T>
    T max_of(T a, T b) { return (a > b) ? a : b; }
    Calling: max_of(3, 5)       — compiler generates max_of<int>
             max_of(3.14, 2.7)  — compiler generates max_of<double>
    Each instantiation is a separate function compiled into machine code.

  CLASS TEMPLATES:
    template<typename T, int N>
    class RingBuffer { T buf_[N]; int head_, tail_; ... };
    Usage: RingBuffer<Tick, 1024>    — ring buffer of 1024 Ticks
           RingBuffer<Order, 512>    — ring buffer of 512 Orders
    Type parameter T can be any type. Non-type parameter N must be compile-time constant.

  TEMPLATE SPECIALIZATION:
    Full:    template<> class Foo<double> { ... };   — completely different impl for double
    Partial: template<typename T> class Foo<T*> { ... };  — different impl for all pointer types
    Used when: the generic version doesn't work correctly for a specific type.

  TYPENAME vs CLASS:
    template<typename T> and template<class T> are IDENTICAL for type parameters.
    Convention: use typename for types, class when you want to emphasize "any class".

  TEMPLATE PARAMETERS CAN BE:
    Types:         typename T, class T
    Integers:      int N, size_t N (must be compile-time constant)
    Booleans:      bool B
    Enums:         enum class Side; then Side S
    Other templates: template<typename> typename Container

  MULTIPLE TYPE PARAMETERS:
    template<typename Key, typename Value>
    class HashMap { ... };

  ADVANTAGES OVER void*:
    - Type-safe: wrong type = compile error, not runtime crash
    - No casting needed
    - Full optimization: compiler can inline, unroll, vectorize
    - Self-documenting: RingBuffer<Tick> vs RingBuffer<void*>

  TRADING USE CASE:
    template<typename T, int N>
    class RingBuffer {
        T    buf_[N];
        int  head_ = 0, tail_ = 0, count_ = 0;
    public:
        void push(T item) { buf_[tail_++ & (N-1)] = std::move(item); ++count_; }
        T    pop()        { --count_; return std::move(buf_[head_++ & (N-1)]); }
    };
    // Reuse for any type:
    RingBuffer<Tick,  1024>  tick_buffer;
    RingBuffer<Order, 256>   order_buffer;
    RingBuffer<Fill,  512>   fill_buffer;

  COMMON MISTAKES:
    - Template definitions must be in the HEADER FILE (not .cpp) because
      the compiler needs the full definition to instantiate it at each call site
    - N must be power of 2 for bitwise modulo (N-1 trick) — not enforced by default
    - template<typename T> is NOT the same as T being any type — T must support
      the operations you use (operator<, copy, etc.). Use Concepts (C++20) to enforce.
    - Don't std::move when you still need the value afterward
*/

#include <iostream>
#include <utility>     // std::move, std::forward
#include <stdexcept>
#include <cstdint>
#include <cstring>

// ============================================================
// PART 1: FUNCTION TEMPLATES
// ============================================================

// Generic clamp: works for ANY type with < operator (int, double, Price, etc.)
template<typename T>
T clamp(T value, T lo, T hi) {
    if (value < lo) return lo;
    if (value > hi) return hi;
    return value;
}

// Generic absolute value (works for int, double, int64_t)
template<typename T>
T abs_val(T x) {
    return (x < T{0}) ? -x : x;
}

// Two type parameters: convert from one numeric type to another
template<typename To, typename From>
To convert(From value) {
    return static_cast<To>(value);
}

// ============================================================
// PART 2: RING BUFFER — the HFT data structure template
// ============================================================
// A ring buffer (circular buffer) stores the last N items with:
// - O(1) push and pop
// - No heap allocation (stack array of size N)
// - No lock needed for single-producer single-consumer (SPSC)
// N MUST be a power of 2 for the bitwise modulo trick to work

template<typename T, int N>
class RingBuffer {
    static_assert((N & (N - 1)) == 0, "N must be a power of 2");
    static_assert(N > 0, "N must be positive");

public:
    RingBuffer() : head_(0), tail_(0), count_(0) {}

    // Push: store a new item (overwrites oldest if full)
    void push(T item) {
        buf_[tail_ & (N - 1)] = std::move(item);   // bitwise AND = fast modulo
        tail_++;
        if (count_ < N) ++count_;
        else            head_++;   // overwrite oldest — advance head too
    }

    // Pop: remove and return the oldest item
    T pop() {
        if (empty()) throw std::runtime_error("RingBuffer: pop from empty buffer");
        T item = std::move(buf_[head_ & (N - 1)]);
        head_++;
        --count_;
        return item;
    }

    // Peek: see the oldest item without removing it
    const T& front() const {
        if (empty()) throw std::runtime_error("RingBuffer: front of empty buffer");
        return buf_[head_ & (N - 1)];
    }

    // Access by index (0 = oldest, count-1 = newest)
    const T& operator[](int i) const {
        return buf_[(head_ + i) & (N - 1)];
    }

    bool empty()    const { return count_ == 0; }
    bool full()     const { return count_ == N; }
    int  size()     const { return count_; }
    int  capacity() const { return N; }

    void clear() { head_ = tail_ = count_ = 0; }

private:
    T   buf_[N];   // stack array — no heap allocation
    int head_;     // index of oldest item
    int tail_;     // index of next write position
    int count_;    // number of valid items currently stored
};

// ============================================================
// PART 3: SIMPLE ORDER POOL TEMPLATE
// ============================================================
// Pre-allocated pool of T objects — hand out and reclaim with O(1)
// Similar to L14 but fully generic.

template<typename T, int POOL_SIZE>
class ObjectPool {
public:
    ObjectPool() : count_(0) {
        // Initialize the free list: indices 0 to POOL_SIZE-1 are all free
        for (int i = 0; i < POOL_SIZE; ++i) {
            free_list_[i] = i;
        }
        count_ = POOL_SIZE;
    }

    // Get a pointer to a free slot (O(1))
    T* acquire() {
        if (count_ == 0) return nullptr;   // pool exhausted
        int idx = free_list_[--count_];
        return &objects_[idx];
    }

    // Return a slot to the free list (O(1))
    void release(T* obj) {
        if (!obj) return;
        int idx = static_cast<int>(obj - objects_);  // pointer arithmetic: which slot?
        free_list_[count_++] = idx;
    }

    int available() const { return count_; }
    int total()     const { return POOL_SIZE; }

private:
    T   objects_[POOL_SIZE];
    int free_list_[POOL_SIZE];
    int count_;
};

// ============================================================
// PART 4: TEMPLATE SPECIALIZATION
// ============================================================

// Generic sum: works for numeric types
template<typename T>
T sum_array(const T* arr, int n) {
    T result = T{0};   // T{} = value-initialization (0 for numeric types)
    for (int i = 0; i < n; ++i) result += arr[i];
    return result;
}

// Specialization for bool: count the number of true values
template<>
bool sum_array<bool>(const bool* arr, int n) {
    int count = 0;
    for (int i = 0; i < n; ++i) if (arr[i]) ++count;
    // Returns true if MORE than half are true (majority vote)
    return count > n / 2;
}

// ============================================================
// DATA TYPES FOR DEMO
// ============================================================

struct Tick {
    double   price;
    int32_t  qty;
    uint64_t seq;
};

struct Order {
    uint64_t id;
    double   price;
    int32_t  qty;
};

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // FUNCTION TEMPLATES
    // -------------------------------------------------------

    std::cout << "--- Function templates ---\n";

    // clamp: works for int, double, int64_t — all with same code
    int    clamped_qty   = clamp(15000, 0, 10000);        // clamp<int>
    double clamped_price = clamp(201.5, 100.0, 200.0);   // clamp<double>
    int64_t clamped_pos  = clamp(-5000LL, -1000LL, 1000LL); // clamp<int64_t>

    std::cout << "Clamped qty:   " << clamped_qty   << " (max 10000)\n";
    std::cout << "Clamped price: " << clamped_price << " (max 200.0)\n";
    std::cout << "Clamped pos:   " << clamped_pos   << " (range ±1000)\n";

    // Two-type-parameter template
    double price_dbl = 182.50;
    int64_t ticks    = convert<int64_t>(price_dbl * 100);  // double → int64_t
    std::cout << "$" << price_dbl << " = " << ticks << " ticks\n";

    // -------------------------------------------------------
    // RING BUFFER — same code, different types
    // -------------------------------------------------------

    std::cout << "\n--- RingBuffer<Tick, 4> ---\n";

    RingBuffer<Tick, 4> tick_buf;   // buffer of 4 Ticks — no heap allocation

    tick_buf.push({182.50, 100, 1});
    tick_buf.push({182.55, 200, 2});
    tick_buf.push({182.48, 300, 3});
    std::cout << "Size: " << tick_buf.size() << " / " << tick_buf.capacity() << "\n";
    std::cout << "Oldest tick price: $" << tick_buf[0].price << "\n";
    std::cout << "Newest tick price: $" << tick_buf[tick_buf.size()-1].price << "\n";

    // Push past capacity: overwrites oldest
    tick_buf.push({182.60, 400, 4});
    tick_buf.push({182.65, 500, 5});   // overwrites seq=1 (the oldest)
    std::cout << "After overflow, oldest price: $" << tick_buf[0].price << "\n";  // seq=2 now

    // Pop items
    while (!tick_buf.empty()) {
        Tick t = tick_buf.pop();
        std::cout << "  Popped: $" << t.price << " seq=" << t.seq << "\n";
    }

    // Reuse same template for Orders — zero new code
    std::cout << "\n--- RingBuffer<Order, 8> ---\n";
    RingBuffer<Order, 8> order_buf;
    order_buf.push({1001, 182.50, 100});
    order_buf.push({1002, 183.00,  50});
    std::cout << "Order buffer size: " << order_buf.size() << "\n";

    // -------------------------------------------------------
    // OBJECT POOL — generic reusable allocator
    // -------------------------------------------------------

    std::cout << "\n--- ObjectPool<Order, 4> ---\n";

    ObjectPool<Order, 4> pool;
    std::cout << "Available: " << pool.available() << "/" << pool.total() << "\n";

    Order* o1 = pool.acquire();
    Order* o2 = pool.acquire();
    if (o1) { o1->id = 2001; o1->price = 184.00; o1->qty = 100; }
    if (o2) { o2->id = 2002; o2->price = 184.05; o2->qty =  50; }

    std::cout << "After 2 acquires: " << pool.available() << " available\n";
    std::cout << "Order #" << o1->id << " @ $" << o1->price << "\n";
    std::cout << "Order #" << o2->id << " @ $" << o2->price << "\n";

    pool.release(o1);
    std::cout << "After releasing o1: " << pool.available() << " available\n";

    Order* o3 = pool.acquire();   // reuses the slot freed by o1
    if (o3) { o3->id = 2003; o3->price = 185.00; o3->qty = 200; }
    std::cout << "Reused slot for Order #" << o3->id << "\n";

    pool.release(o2);
    pool.release(o3);

    // -------------------------------------------------------
    // TEMPLATE SPECIALIZATION
    // -------------------------------------------------------

    std::cout << "\n--- Template specialization ---\n";

    double pnls[] = {+250.0, -100.0, +500.0, +75.0, -50.0};
    std::cout << "Sum of PnLs: $" << sum_array(pnls, 5) << "\n";   // sum_array<double>

    int fills[] = {100, 200, 50, 300};
    std::cout << "Total fills: " << sum_array(fills, 4) << "\n";   // sum_array<int>

    // Specialization for bool: majority vote
    bool signals[] = {true, true, false, true, false};
    std::cout << "Majority signal: " << sum_array(signals, 5) << "\n";   // sum_array<bool> specialization

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      A complete generic SPSC (Single Producer Single Consumer) queue,
      used to safely pass data between the market data thread and strategy thread:

        template<typename T, int N>
        class SPSCQueue {
        public:
            // Producer thread: push new item
            bool push(T item) {
                int next_tail = (tail_.load(relaxed) + 1) & (N - 1);
                if (next_tail == head_.load(acquire)) return false;  // full
                buf_[tail_.load(relaxed)] = std::move(item);
                tail_.store(next_tail, release);
                return true;
            }
            // Consumer thread: pop oldest item
            bool pop(T& out) {
                int h = head_.load(relaxed);
                if (h == tail_.load(acquire)) return false;  // empty
                out = std::move(buf_[h]);
                head_.store((h + 1) & (N-1), release);
                return true;
            }
        private:
            T                 buf_[N];
            std::atomic<int>  head_{0}, tail_{0};
        };

        SPSCQueue<Tick,  65536> tick_queue;   // 64K ticks, lock-free
        SPSCQueue<Fill,  4096>  fill_queue;   // 4K fills, lock-free

      This is the #1 inter-thread communication pattern in HFT.
      The template means you write it ONCE and use it for every type.
    */
}
