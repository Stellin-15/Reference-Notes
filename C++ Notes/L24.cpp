// ============================================================
// L24: Move Semantics and Perfect Forwarding In Depth
// ============================================================
// WHAT: The full story of lvalues, rvalues, std::move,
//       std::forward, and forwarding references. These are the
//       tools that eliminate unnecessary copies in C++.
// WHY (TRADING): Move semantics are the foundation of zero-copy
//   pipelines in HFT. Every time market data flows from the
//   feed handler to the strategy to the risk engine, it should
//   MOVE — not copy. Perfect forwarding lets utility functions
//   pass arguments without imposing copy overhead. Together,
//   these make it possible to build sub-microsecond pipelines.
// PHASE: Modern C++
// ============================================================

/*
  CONCEPT OVERVIEW:

  LVALUE vs RVALUE (the deepest C++ concept):
    Lvalue ("locator value"):
      - Has a name, has a persistent address in memory
      - Can appear on the LEFT of an assignment (hence "l")
      - Examples: int x; std::string s; a named variable
      - Lvalue reference: int& — binds ONLY to lvalues

    Rvalue ("right value"):
      - Temporary, no name, no persistent address
      - Can only appear on the RIGHT of an assignment
      - Examples: 5, (x + y), make_order(), std::move(x)
      - Rvalue reference: int&& — binds ONLY to rvalues

    xvalue ("expiring value"):
      - Has an address but you've signaled it's about to expire
      - Result of std::move() or a function returning T&&
      - Can be moved from

  STD::MOVE — just a cast:
    std::move(x) does NOT move anything by itself.
    It casts x to T&& (an rvalue reference).
    This tells the compiler: "treat x as a temporary — it's safe to steal from it."
    The ACTUAL move happens in the move constructor/assignment that's called next.
    After std::move, x is in a "valid but unspecified state" — don't use it.

  FORWARDING REFERENCES (universal references):
    When a template parameter T is deduced AND the parameter is T&&, it's NOT
    an rvalue reference — it's a "forwarding reference" that can bind to EITHER:
      template<typename T> void foo(T&& arg);
      foo(lvalue)   — T deduced as T&,  arg is T&   (lvalue)
      foo(rvalue)   — T deduced as T,   arg is T&&  (rvalue)
    This is called reference collapsing.

  STD::FORWARD — preserve the value category:
    Inside a template, you don't know if arg is lvalue or rvalue.
    std::forward<T>(arg) preserves the original value category:
      if T was deduced as T& (lvalue), forward returns T&
      if T was deduced as T  (rvalue), forward returns T&&
    Use std::forward in generic code. Use std::move for concrete known-owned objects.

  RETURN VALUE OPTIMIZATION (RVO / NRVO):
    When returning a local object from a function, the compiler constructs it
    DIRECTLY in the caller's storage — no copy, no move at all.
    This is better than std::move on a return — don't write: return std::move(x);
    It PREVENTS RVO. Just write: return x;

  TRADING USE CASE:
    // Feed handler builds a batch and MOVES it to the strategy
    auto batch = build_tick_batch();           // RVO: no copy
    strategy.process(std::move(batch));        // move: O(1) pointer transfer
    // batch is now empty — don't use it again

    // Generic queue push — forward preserves original value category
    template<typename T>
    void push(T&& item) {
        buffer_[tail_] = std::forward<T>(item);  // move if rvalue, copy if lvalue
    }

  COMMON MISTAKES:
    - Using a moved-from object: undefined behavior (well, valid but empty for STL types)
    - return std::move(x): prevents RVO, actually WORSE than return x
    - std::forward on a non-template parameter: use std::move instead
    - Applying std::move to const objects: const T&& can't call the move constructor
      (it needs T&&) — silently falls back to copy! Never move from const.
*/

#include <iostream>
#include <string>
#include <vector>
#include <utility>   // std::move, std::forward
#include <cstdint>

// ============================================================
// TICK BATCH — demonstrates move semantics in practice
// ============================================================

struct Tick {
    double   price;
    int32_t  qty;
    uint64_t seq;
};

class TickBatch {
public:
    explicit TickBatch(std::string source)
        : source_(std::move(source))  // move the string arg into member
    {
        ticks_.reserve(128);
        std::cout << "[Batch:" << source_ << "] Created\n";
    }

    // Move constructor: called when Batch is std::moved
    TickBatch(TickBatch&& other) noexcept
        : source_(std::move(other.source_))   // move the string (O(1))
        , ticks_(std::move(other.ticks_))     // move the vector (O(1))
    {
        std::cout << "[Batch] Moved (" << ticks_.size() << " ticks transferred)\n";
    }

    ~TickBatch() {
        std::cout << "[Batch:" << source_ << "] Destroyed (" << ticks_.size() << " ticks)\n";
    }

    void add(double price, int32_t qty, uint64_t seq) {
        ticks_.push_back({price, qty, seq});
    }

    int         size()   const { return static_cast<int>(ticks_.size()); }
    bool        empty()  const { return ticks_.empty(); }
    const Tick& operator[](int i) const { return ticks_[i]; }

private:
    std::string       source_;
    std::vector<Tick> ticks_;
};

// ============================================================
// RVO DEMONSTRATION
// ============================================================

// Compiler elides the copy/move entirely — TickBatch constructed in caller's space
TickBatch build_batch(const std::string& feed_name) {
    TickBatch batch(feed_name);   // local variable
    batch.add(182.50, 100, 1);
    batch.add(182.55, 200, 2);
    batch.add(182.60, 150, 3);
    return batch;   // RVO: no copy, no move — direct construction in caller
    // DO NOT write: return std::move(batch);  — this PREVENTS RVO
}

// ============================================================
// PERFECT FORWARDING
// ============================================================

// A generic "emplace" function that constructs T in-place,
// forwarding args without imposing copy overhead.
template<typename T, typename... Args>
T* emplace_construct(void* memory, Args&&... args) {
    // placement new: construct T at an existing memory address (no allocation)
    // std::forward preserves the value category of each argument
    return new(memory) T(std::forward<Args>(args)...);
}

// Generic wrapper that forwards to any callable
template<typename Func, typename Arg>
auto forward_to(Func&& func, Arg&& arg) {
    // Both func and arg are forwarded: if they were lvalues → lvalue refs
    //                                  if they were rvalues → moved from
    return std::forward<Func>(func)(std::forward<Arg>(arg));
}

// ============================================================
// SHOWING LVALUE vs RVALUE BINDING
// ============================================================

void process_lvalue(const TickBatch& batch) {
    std::cout << "[process_lvalue] Received " << batch.size() << " ticks (COPY or const-ref)\n";
}

void process_rvalue(TickBatch&& batch) {
    std::cout << "[process_rvalue] Received " << batch.size() << " ticks (MOVED IN)\n";
    // We OWN batch here — safe to modify or move further
}

// Overloaded: compiler picks based on whether arg is lvalue or rvalue
void process(const TickBatch& b) { std::cout << "[process lvalue overload] " << b.size() << " ticks\n"; }
void process(TickBatch&&      b) { std::cout << "[process rvalue overload] " << b.size() << " ticks\n"; }

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // LVALUE vs RVALUE — the fundamentals
    // -------------------------------------------------------

    std::cout << "=== Lvalue vs Rvalue ===\n";

    int x = 5;       // x is an lvalue (has a name, has an address)
    int y = x + 3;   // x+3 is an rvalue (temporary result)
    // int& r = x+3; // ERROR: can't bind lvalue ref to rvalue
    const int& cr = x + 3;  // OK: const lvalue ref CAN bind to rvalue
    int&&      rr = x + 3;  // OK: rvalue ref binds to rvalue
    (void)y; (void)cr; (void)rr;

    std::cout << "x (lvalue): " << x << "\n";
    std::cout << "rvalue ref rr: " << rr << "\n";

    // -------------------------------------------------------
    // RVO — Return Value Optimization
    // -------------------------------------------------------

    std::cout << "\n=== RVO (no copy, no move) ===\n";

    // The compiler builds the TickBatch DIRECTLY in b's storage.
    // Watch the output — you should see only [Created], no [Moved].
    TickBatch b = build_batch("ITCH-Feed");
    std::cout << "Batch has " << b.size() << " ticks\n";

    // -------------------------------------------------------
    // STD::MOVE — transfer ownership
    // -------------------------------------------------------

    std::cout << "\n=== std::move ===\n";

    {
        TickBatch src("CME-Feed");
        src.add(183.00, 500, 10);
        src.add(183.05, 300, 11);
        std::cout << "src size before move: " << src.size() << "\n";

        // std::move(src) casts src to an rvalue — triggers move constructor
        TickBatch dst = std::move(src);
        std::cout << "dst size after move: " << dst.size() << "\n";
        std::cout << "src size after move: " << src.size() << "\n";  // src is empty now
        // NEVER use src again after moving from it — it's in an unspecified state
    }

    // -------------------------------------------------------
    // OVERLOAD RESOLUTION: lvalue vs rvalue
    // -------------------------------------------------------

    std::cout << "\n=== Overload by value category ===\n";

    {
        TickBatch named("NYSE-Feed");
        named.add(184.00, 100, 20);

        process(named);              // calls lvalue overload (named is an lvalue)
        process(std::move(named));   // calls rvalue overload (std::move makes it rvalue)
        // After std::move(named): don't use named again

        // Temporary (rvalue): also calls rvalue overload
        process(build_batch("BATS-Feed"));  // temporary = rvalue
    }

    // -------------------------------------------------------
    // MOVE IN A PIPELINE — the HFT pattern
    // -------------------------------------------------------

    std::cout << "\n=== Move pipeline: feed → strategy → risk ===\n";

    {
        // Stage 1: feed handler builds a batch
        TickBatch feed_batch("NASDAQ-ITCH");
        for (int i = 0; i < 5; ++i) {
            feed_batch.add(182.50 + i * 0.01, 100 * (i + 1), 100 + i);
        }
        std::cout << "Feed batch: " << feed_batch.size() << " ticks\n";

        // Stage 2: MOVE to strategy (O(1) — just pointer swap)
        TickBatch strat_batch = std::move(feed_batch);
        // feed_batch is now empty — the internal vector was transferred
        std::cout << "feed_batch after move: " << feed_batch.size() << " ticks\n";
        std::cout << "strat_batch: " << strat_batch.size() << " ticks\n";

        // Stage 3: MOVE to risk engine
        TickBatch risk_batch = std::move(strat_batch);
        std::cout << "risk_batch: " << risk_batch.size() << " ticks\n";

        // Each move is O(1) regardless of how many ticks are in the batch.
        // No data was ever copied — the same memory was just "handed off" each time.
    }

    // -------------------------------------------------------
    // PERFECT FORWARDING
    // -------------------------------------------------------

    std::cout << "\n=== Perfect forwarding ===\n";

    {
        // Allocate raw memory (simulating a pool allocator)
        alignas(TickBatch) char buf[sizeof(TickBatch)];

        // emplace_construct forwards args perfectly to TickBatch constructor
        // If args are lvalues: they're passed as lvalue refs (no copy)
        // If args are rvalues: they're moved
        std::string feed_name = "SIP-Feed";
        TickBatch* tb = emplace_construct<TickBatch>(buf, std::move(feed_name));
        tb->add(185.00, 200, 200);
        std::cout << "Emplaced batch size: " << tb->size() << "\n";

        // Must manually destroy (placement new bypasses normal construction)
        tb->~TickBatch();
    }

    // -------------------------------------------------------
    // COMMON MISTAKE: std::move on const → silently copies
    // -------------------------------------------------------

    std::cout << "\n=== const move warning ===\n";

    {
        // This looks like a move but ISN'T — const T cannot be moved from
        const std::string immutable = "cannot move me";
        std::string       attempt   = std::move(immutable);  // COPIES, not moves!
        // const T&& doesn't match std::string's move constructor (T&&)
        // Falls back to the copy constructor silently
        std::cout << "immutable still alive: [" << immutable << "]\n";
        std::cout << "attempt got a copy:    [" << attempt   << "]\n";
        // Lesson: NEVER apply std::move to const objects
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      A generic SPSC queue's push method using perfect forwarding:

        template<typename T, int N>
        class SPSCQueue {
        public:
            // Perfect forward: works for both lvalue and rvalue T
            template<typename U>
            bool push(U&& item) {
                int next = (tail_ + 1) & (N - 1);
                if (next == head_.load(std::memory_order_acquire)) return false; // full
                buf_[tail_] = std::forward<U>(item);  // move if rvalue, copy if lvalue
                tail_.store(next, std::memory_order_release);
                return true;
            }
        };

        TickBatch batch = build_batch("CME");
        queue.push(std::move(batch));  // moves batch into queue (O(1))
        queue.push(build_batch("CME")); // temporary: also moves (O(1))
        queue.push(batch);             // lvalue: copies (only if you need to keep batch)
    */
}
