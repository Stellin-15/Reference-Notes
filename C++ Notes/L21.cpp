// ============================================================
// L21: Copy/Move Constructors, Rule of 5, Move Semantics
// ============================================================
// WHAT: When you copy an object, what exactly happens? When you
//       "move" one, what's the difference? The Rule of 5 says:
//       if you define ANY of destructor/copy-ctor/copy-assign/
//       move-ctor/move-assign, you should define all 5.
// WHY (TRADING): Move semantics enable ZERO-COPY data pipelines.
//   Moving a vector of 10,000 ticks between threads takes ~5ns.
//   Copying the same vector takes ~50µs (10,000x slower).
//   In HFT, market data is passed between components with
//   std::move — no copying, just transferring ownership of
//   the internal buffer pointer.
// PHASE: OOP
// ============================================================

/*
  CONCEPT OVERVIEW:

  COPY vs MOVE — the key mental model:
    COPY: duplicate everything — both original and copy exist after
      Think: "photocopy a document" — two separate copies
      Cost: O(n) time and memory proportional to size of data

    MOVE: transfer ownership — original is left empty/"moved-from"
      Think: "hand over a folder" — only one copy exists (in new place)
      Cost: O(1) — just swap a few pointers and sizes

  THE FIVE SPECIAL MEMBER FUNCTIONS:
    1. Destructor:           ~T()                  — cleanup on destruction
    2. Copy constructor:     T(const T&)           — create from another T
    3. Copy assignment:      T& operator=(const T&) — replace contents from T
    4. Move constructor:     T(T&&)                — create by stealing from rvalue T
    5. Move assignment:      T& operator=(T&&)     — replace by stealing from rvalue T

  RULE OF 5:
    If your class manages a resource (heap memory, file handle, socket, lock),
    define ALL 5 special member functions (or explicitly delete/default them).
    Reason: compiler-generated versions do SHALLOW copies — for raw pointer
    members, that means two objects point to the same memory, and double-free
    crashes the program when both destructors run.

  RULE OF 0 (BETTER):
    If your class ONLY contains types that manage their own resources
    (std::string, std::vector, std::unique_ptr) — let them handle it.
    Declare NO special member functions. The compiler-generated defaults
    will call each member's copy/move/destructor correctly.

  std::move:
    Just a CAST — casts an lvalue to an rvalue reference.
    Does NOT actually move anything by itself.
    It signals: "I'm done with this object, you can steal its guts."
    After std::move: the source object is in a "valid but unspecified state"
    (for std::vector: empty; for std::string: empty; for your class: whatever
    your move constructor does to the source).

  RETURN VALUE OPTIMIZATION (RVO / NRVO):
    When a function returns a local object by value, the compiler usually
    constructs it DIRECTLY in the caller's memory — no copy, no move.
    Don't std::move a return value — it can PREVENT RVO.

  TRADING USE CASE:
    // Without move (bad — copies entire buffer):
    void process(MarketDataBuffer buf) { ... }   // copies on every call
    process(my_buffer);  // O(n) copy

    // With move (O(1) — transfers ownership):
    void process(MarketDataBuffer buf) { ... }
    process(std::move(my_buffer));  // my_buffer is now empty; buf has the data

    // Moving market data between threads (lock-free queue):
    queue.push(std::move(tick_batch));  // no copy — just moves the internal pointer

  COMMON MISTAKES:
    - Using a moved-from object (undefined state — don't)
    - std::moving a return statement (prevents RVO — worse performance)
    - Rule of 3/5 violation: defining destructor but not copy/move — double free
    - Shallow copy of a raw pointer in copy constructor — two owners = crash
*/

#include <iostream>
#include <string>
#include <vector>
#include <cstring>   // memcpy
#include <cstdint>
#include <utility>   // std::move, std::swap
#include <chrono>

// ============================================================
// MARKET DATA BUFFER — manually managed (demonstrates Rule of 5)
// ============================================================
// This class owns a raw heap array — MUST define all 5 special functions.
// (In production: use std::vector instead — Rule of 0 applies there)

struct Tick {
    double   price;
    int32_t  qty;
    uint64_t timestamp_ns;
};

class MarketDataBuffer {
public:
    // --- CONSTRUCTOR ---
    explicit MarketDataBuffer(int capacity)
        : data_(new Tick[capacity])   // allocate heap array
        , capacity_(capacity)
        , size_(0)
    {
        std::cout << "[Buffer] Constructed, cap=" << capacity_ << "\n";
    }

    // --- 1. DESTRUCTOR ---
    ~MarketDataBuffer() {
        delete[] data_;   // free heap array
        std::cout << "[Buffer] Destroyed, had " << size_ << " ticks\n";
    }

    // --- 2. COPY CONSTRUCTOR — deep copy: duplicate the entire array ---
    MarketDataBuffer(const MarketDataBuffer& other)
        : data_(new Tick[other.capacity_])   // new allocation
        , capacity_(other.capacity_)
        , size_(other.size_)
    {
        std::memcpy(data_, other.data_, sizeof(Tick) * size_);  // copy all ticks
        std::cout << "[Buffer] Copy constructed, copied " << size_ << " ticks\n";
    }

    // --- 3. COPY ASSIGNMENT OPERATOR ---
    MarketDataBuffer& operator=(const MarketDataBuffer& other) {
        if (this == &other) return *this;   // guard against self-assignment

        delete[] data_;   // free OLD data first
        data_     = new Tick[other.capacity_];   // allocate new
        capacity_ = other.capacity_;
        size_     = other.size_;
        std::memcpy(data_, other.data_, sizeof(Tick) * size_);
        std::cout << "[Buffer] Copy assigned, copied " << size_ << " ticks\n";
        return *this;
    }

    // --- 4. MOVE CONSTRUCTOR — steal the pointer, leave source empty ---
    // T&& is an RVALUE REFERENCE — binds only to temporaries/moved-from objects
    MarketDataBuffer(MarketDataBuffer&& other) noexcept   // noexcept: important for STL optimization
        : data_(other.data_)          // steal the pointer (O(1))
        , capacity_(other.capacity_)
        , size_(other.size_)
    {
        // Leave source in valid but empty state — destructor must still work
        other.data_     = nullptr;
        other.capacity_ = 0;
        other.size_     = 0;
        std::cout << "[Buffer] Move constructed (no copy)\n";
    }

    // --- 5. MOVE ASSIGNMENT OPERATOR ---
    MarketDataBuffer& operator=(MarketDataBuffer&& other) noexcept {
        if (this == &other) return *this;

        delete[] data_;           // free our OLD data

        data_     = other.data_;       // steal the pointer
        capacity_ = other.capacity_;
        size_     = other.size_;

        other.data_     = nullptr;     // leave source empty
        other.capacity_ = 0;
        other.size_     = 0;

        std::cout << "[Buffer] Move assigned (no copy)\n";
        return *this;
    }

    // --- PUBLIC INTERFACE ---

    void push(double price, int32_t qty, uint64_t ts) {
        if (size_ < capacity_) {
            data_[size_++] = {price, qty, ts};
        }
    }

    int  size()     const { return size_; }
    int  capacity() const { return capacity_; }
    bool empty()    const { return size_ == 0; }

    const Tick& operator[](int i) const { return data_[i]; }

    void print() const {
        std::cout << "[Buffer] " << size_ << "/" << capacity_ << " ticks";
        if (size_ > 0) std::cout << " | first=$" << data_[0].price;
        std::cout << "\n";
    }

private:
    Tick* data_;
    int   capacity_;
    int   size_;
};

// ============================================================
// RULE OF 0 EXAMPLE — using std::vector (preferred)
// ============================================================

class TickStream {
public:
    // std::vector manages its own memory.
    // Compiler-generated copy/move/destructor call vector's copy/move/destructor.
    // We define NOTHING special — Rule of 0.

    void push(Tick t) { ticks_.push_back(std::move(t)); }  // move tick into vector

    int  size()  const { return static_cast<int>(ticks_.size()); }
    void clear()       { ticks_.clear(); }

    const Tick& operator[](int i) const { return ticks_[i]; }

    void print() const {
        std::cout << "[TickStream] " << ticks_.size() << " ticks\n";
    }

private:
    std::vector<Tick> ticks_;   // vector handles all resource management
};

// ============================================================
// BENCHMARK — copy vs move
// ============================================================

void benchmark_copy_vs_move() {
    constexpr int SIZE = 100'000;

    // Fill a large buffer
    MarketDataBuffer source(SIZE);
    for (int i = 0; i < SIZE; ++i) {
        source.push(182.50 + i * 0.001, 100, static_cast<uint64_t>(i));
    }
    std::cout << "Source: "; source.print();

    // --- COPY (O(n)) ---
    auto t1 = std::chrono::high_resolution_clock::now();
    MarketDataBuffer copy_dest(source);   // copy constructor
    auto t2 = std::chrono::high_resolution_clock::now();
    long copy_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(t2 - t1).count();

    // --- MOVE (O(1)) ---
    MarketDataBuffer move_src(SIZE);
    for (int i = 0; i < SIZE; ++i) move_src.push(183.00, 200, i);

    auto t3 = std::chrono::high_resolution_clock::now();
    MarketDataBuffer move_dest(std::move(move_src));   // move constructor
    auto t4 = std::chrono::high_resolution_clock::now();
    long move_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(t4 - t3).count();

    std::cout << "\n=== Copy vs Move Benchmark (" << SIZE << " ticks) ===\n";
    std::cout << "Copy constructor: " << copy_ns << " ns\n";
    std::cout << "Move constructor: " << move_ns << " ns\n";
    if (move_ns > 0)
        std::cout << "Speedup: ~" << (copy_ns / move_ns) << "x\n";
}

int main() {

    // -------------------------------------------------------
    // COPY CONSTRUCTOR AND ASSIGNMENT
    // -------------------------------------------------------

    std::cout << "--- Copy semantics ---\n";
    {
        MarketDataBuffer buf1(4);
        buf1.push(182.50, 100, 1000);
        buf1.push(182.55, 200, 1001);
        buf1.print();

        // Copy constructor: buf2 is an independent copy
        MarketDataBuffer buf2(buf1);   // calls copy constructor
        buf2.print();

        buf2.push(182.60, 300, 1002);
        std::cout << "After pushing to buf2:\n";
        buf1.print();   // buf1 unchanged (deep copy)
        buf2.print();   // buf2 has extra tick
    }

    // -------------------------------------------------------
    // MOVE CONSTRUCTOR AND ASSIGNMENT
    // -------------------------------------------------------

    std::cout << "\n--- Move semantics ---\n";
    {
        MarketDataBuffer buf3(4);
        buf3.push(183.00, 500, 2000);
        buf3.push(183.05, 300, 2001);
        buf3.print();

        // Move constructor: buf4 takes ownership; buf3 is now empty
        MarketDataBuffer buf4(std::move(buf3));   // O(1) — just pointer swap
        std::cout << "After move:\n";
        std::cout << "buf3 (moved-from): "; buf3.print();   // empty
        std::cout << "buf4 (new owner):  "; buf4.print();   // has the data
        // IMPORTANT: don't use buf3 again after moving from it
    }

    // -------------------------------------------------------
    // MOVE ASSIGNMENT
    // -------------------------------------------------------

    std::cout << "\n--- Move assignment ---\n";
    {
        MarketDataBuffer dst(4);   // empty destination
        MarketDataBuffer src(4);
        src.push(185.00, 100, 3000);
        src.push(185.05, 200, 3001);

        dst = std::move(src);     // move assignment: dst takes src's data
        std::cout << "After move assign:\n";
        std::cout << "src: "; src.print();
        std::cout << "dst: "; dst.print();
    }

    // -------------------------------------------------------
    // RULE OF 0: TickStream with std::vector
    // -------------------------------------------------------

    std::cout << "\n--- Rule of 0 (no special members defined) ---\n";
    {
        TickStream ts1;
        ts1.push({182.50, 100, 4000});
        ts1.push({182.55, 200, 4001});
        ts1.print();

        // Compiler-generated move constructor calls vector's move constructor
        TickStream ts2 = std::move(ts1);  // O(1) — just moves vector internals
        ts2.print();
        ts1.print();   // ts1 is now empty (vector was moved)
    }

    // -------------------------------------------------------
    // BENCHMARK
    // -------------------------------------------------------

    std::cout << "\n";
    benchmark_copy_vs_move();

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Moving batched market data between the feed handler and strategy threads:

        // Feed handler thread builds a batch of ticks
        std::vector<Tick> batch;
        batch.reserve(1024);
        while (batch.size() < 1024) {
            batch.push_back(receive_tick());
        }

        // Push to strategy thread via SPSC queue — MOVE, don't copy
        // The vector's internal buffer (8KB of tick data) is transferred
        // in ~10ns (just updating 3 pointers: data, size, capacity)
        tick_queue.push(std::move(batch));   // batch is now empty

        // Strategy thread
        auto received = tick_queue.pop();    // move out of queue
        for (const auto& tick : received) {
            strategy.on_tick(tick);
        }
        // received is auto-destroyed here — no manual cleanup needed

      Without move semantics, each batch push would copy 8KB of data.
      With move semantics: 3 pointer swaps (~10ns regardless of batch size).
    */
}
