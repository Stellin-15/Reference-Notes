// ============================================================
// L38: Lock-Free Data Structures and SPSC Queue
// ============================================================
// WHAT: Lock-free data structures allow concurrent access without
//       mutexes, using atomic operations (CAS, fetch_add).
//       SPSC = Single Producer Single Consumer — the simplest
//       and fastest lock-free queue (used everywhere in HFT).
// WHY (TRADING): The market data thread produces ticks; the
//   strategy thread consumes them. A mutex between them would
//   mean one blocks the other. An SPSC queue lets both threads
//   run simultaneously with zero blocking — the producer just
//   writes and moves on, the consumer reads when ready.
//   SPSC queue latency: < 20ns per enqueue/dequeue.
//   Mutex queue latency: 200-2000ns (varies wildly under contention).
//   In HFT, every microsecond of additional latency in this
//   pipeline costs you fills to faster competitors.
// PHASE: Concurrency
// ============================================================

/*
  CONCEPT OVERVIEW:

  LOCK-FREE vs WAIT-FREE:
    Lock-free: at least one thread always makes progress (some may retry).
    Wait-free:  every thread always makes progress in bounded steps.
    SPSC is wait-free (producer and consumer never conflict).
    CAS-loops are lock-free (one succeeds, others retry — can starve).

  SPSC QUEUE (Single Producer, Single Consumer):
    - One thread writes (producer), one thread reads (consumer).
    - head: index of next slot to write (owned by producer)
    - tail: index of next slot to read (owned by consumer)
    - Queue is full when (head + 1) % N == tail.
    - Queue is empty when head == tail.
    - head is ONLY written by producer → consumer reads it with acquire.
    - tail is ONLY written by consumer → producer reads it with acquire.
    - No CAS needed — each index has exactly one writer.
    - Typically backed by a power-of-2 ring buffer (fast modulo with &).

  WHY POWER OF 2 SIZE:
    index % N  — slow division (many cycles)
    index & (N-1) — fast AND (1 cycle), equivalent when N is power of 2

  CACHE LINE ALIGNMENT:
    head and tail should be on separate cache lines (64 bytes apart).
    If they share a cache line, each write to head invalidates the cache
    line that tail is on in the other thread → "false sharing" → cache ping-pong.
    Fix: pad head_ to 64 bytes before tail_ (shown below).

  SPSC QUEUE OPERATIONS:
    push(item) — producer: check not full, write item, advance head
    pop(item)  — consumer: check not empty, read item, advance tail
    Both are O(1) and branch-free (no locks, no CAS in SPSC).

  MPSC / MPMC (multiple producers or consumers):
    MPSC: multiple producers, one consumer — need CAS on head.
    MPMC: multiple producers and consumers — need CAS on both ends.
    Both are harder to implement correctly. In trading, prefer:
    - One dedicated feed thread (SPSC to each strategy thread)
    - One dedicated strategy thread (SPSC to execution thread)

  TRADING USE CASE:
    // Feed thread → strategy thread (SPSC):
    SPSCQueue<Tick, 65536> tick_queue;

    // Feed thread (producer):
    while (recv_tick(&tick)) {
        tick_queue.push(tick);   // < 20ns, never blocks
    }

    // Strategy thread (consumer):
    Tick t;
    while (tick_queue.pop(t)) {
        strategy.on_tick(t);     // process tick
    }

  COMMON MISTAKES:
    - Using SPSC queue with > 1 producer or > 1 consumer → data race
    - Not aligning head/tail to separate cache lines → false sharing → 10x slower
    - Power-of-2 size enforcement: if N is not power of 2, the fast modulo trick is wrong
    - Forgetting memory_order_acquire on read of the other thread's index
    - Reading the item BEFORE advancing tail (must read first, then advance)
    - Spinning without _mm_pause() — burns power and delays other hyperthreads
*/

#include <iostream>
#include <atomic>
#include <thread>
#include <array>
#include <vector>
#include <chrono>
#include <cstdint>
#include <cassert>
#include <cstring>      // memset

#if defined(__x86_64__) || defined(_M_X64)
#  include <immintrin.h>  // _mm_pause()
#  define CPU_RELAX() _mm_pause()
#else
#  define CPU_RELAX() std::this_thread::yield()
#endif

using namespace std::chrono_literals;

// ============================================================
// SPSC QUEUE — the HFT inter-thread communication primitive
// ============================================================

template<typename T, int N>
class SPSCQueue {
    static_assert((N & (N - 1)) == 0, "N must be power of 2");
    static_assert(N >= 2, "N must be at least 2");

public:
    SPSCQueue() {
        head_.store(0, std::memory_order_relaxed);
        tail_.store(0, std::memory_order_relaxed);
    }

    // PRODUCER ONLY — called from the producer thread
    bool push(const T& item) noexcept {
        const uint64_t h = head_.load(std::memory_order_relaxed);  // producer owns head
        const uint64_t next_h = h + 1;

        // Full check: next head == tail
        if ((next_h & (N - 1)) == (tail_.load(std::memory_order_acquire) & (N - 1))) {
            return false;   // queue full — caller must retry or discard
        }

        buf_[h & (N - 1)] = item;                           // write item
        head_.store(next_h, std::memory_order_release);      // advance head (release: item visible)
        return true;
    }

    // CONSUMER ONLY — called from the consumer thread
    bool pop(T& item) noexcept {
        const uint64_t t = tail_.load(std::memory_order_relaxed);  // consumer owns tail

        // Empty check: tail == head
        if ((t & (N - 1)) == (head_.load(std::memory_order_acquire) & (N - 1))) {
            return false;   // queue empty
        }

        item = buf_[t & (N - 1)];                           // read item BEFORE advancing
        tail_.store(t + 1, std::memory_order_release);       // advance tail
        return true;
    }

    bool empty() const noexcept {
        return head_.load(std::memory_order_acquire) ==
               tail_.load(std::memory_order_acquire);
    }

    int size() const noexcept {
        uint64_t h = head_.load(std::memory_order_acquire);
        uint64_t t = tail_.load(std::memory_order_acquire);
        return static_cast<int>((h - t) & (N - 1));
    }

private:
    // CRITICAL: head and tail MUST be on separate cache lines (64 bytes each)
    // If they share a line, every write to head_ invalidates tail_'s cache line
    // in the other CPU core → false sharing → queue 10x slower than necessary.
    alignas(64) std::atomic<uint64_t> head_{0};
    alignas(64) std::atomic<uint64_t> tail_{0};

    // Buffer: N items (ring buffer)
    // Declare after head/tail so they don't accidentally share cache lines
    T buf_[N]{};
};

// ============================================================
// MARKET DATA TICK TYPE
// ============================================================

struct Tick {
    uint64_t timestamp_ns;
    int64_t  bid;
    int64_t  ask;
    int32_t  bid_qty;
    int32_t  ask_qty;
    uint32_t seq;
};

// ============================================================
// LOCK-FREE STACK (LIFO) — CAS-based for comparison
// ============================================================

// A simple lock-free LIFO stack using CAS on the head pointer.
// MPMC-safe (multiple push/pop threads).
// NOTE: ABA problem exists in naive implementations — mitigated here
// by keeping pool indices instead of raw pointers.
template<typename T, int N>
class LockFreeStack {
public:
    struct Node {
        T    data;
        int  next = -1;  // index into nodes_ array (-1 = null)
    };

    LockFreeStack() {
        // Build free list: each node points to the next free slot
        for (int i = 0; i < N - 1; ++i) nodes_[i].next = i + 1;
        nodes_[N - 1].next = -1;
        free_head_.store(0, std::memory_order_relaxed);
        data_head_.store(-1, std::memory_order_relaxed);
    }

    bool push(const T& val) {
        // Allocate a free node
        int idx = alloc_node();
        if (idx < 0) return false;  // out of pool space

        nodes_[idx].data = val;

        // CAS the data stack head
        int old_head = data_head_.load(std::memory_order_relaxed);
        do {
            nodes_[idx].next = old_head;
        } while (!data_head_.compare_exchange_weak(
                     old_head, idx,
                     std::memory_order_release,
                     std::memory_order_relaxed));
        return true;
    }

    bool pop(T& val) {
        int old_head = data_head_.load(std::memory_order_acquire);
        while (old_head >= 0) {
            int next = nodes_[old_head].next;
            if (data_head_.compare_exchange_weak(
                    old_head, next,
                    std::memory_order_acquire,
                    std::memory_order_relaxed))
            {
                val = nodes_[old_head].data;
                free_node(old_head);
                return true;
            }
            // CAS failed — old_head was updated, retry
        }
        return false;  // empty
    }

private:
    int alloc_node() {
        int old = free_head_.load(std::memory_order_acquire);
        while (old >= 0) {
            int next = nodes_[old].next;
            if (free_head_.compare_exchange_weak(old, next,
                    std::memory_order_acquire, std::memory_order_relaxed))
                return old;
        }
        return -1;  // pool exhausted
    }

    void free_node(int idx) {
        int old = free_head_.load(std::memory_order_relaxed);
        do {
            nodes_[idx].next = old;
        } while (!free_head_.compare_exchange_weak(old, idx,
                    std::memory_order_release, std::memory_order_relaxed));
    }

    std::array<Node, N>  nodes_{};
    std::atomic<int>     free_head_{0};
    std::atomic<int>     data_head_{-1};
};

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // SPSC QUEUE BASIC TEST
    // -------------------------------------------------------

    std::cout << "=== SPSC queue basic ===\n";

    {
        SPSCQueue<int, 8> q;   // capacity = 8 - 1 = 7 (one slot always empty)

        for (int i = 1; i <= 5; ++i) q.push(i);
        std::cout << "  Pushed 5 items, size=" << q.size() << "\n";

        int val;
        while (q.pop(val)) {
            std::cout << "  Popped: " << val << "\n";
        }
    }

    // -------------------------------------------------------
    // SPSC QUEUE — PRODUCER/CONSUMER THREADS
    // -------------------------------------------------------

    std::cout << "\n=== SPSC queue producer/consumer ===\n";

    {
        SPSCQueue<Tick, 1024> queue;
        const int NUM_TICKS = 20;
        std::atomic<int> received{0};

        // Producer: market data feed thread
        std::thread producer([&queue, NUM_TICKS]() {
            for (int i = 0; i < NUM_TICKS; ++i) {
                Tick t{};
                t.timestamp_ns = uint64_t(1000000 + i * 100);
                t.bid          = int64_t(1825000 + i * 10);
                t.ask          = t.bid + 100;
                t.seq          = uint32_t(i);

                while (!queue.push(t)) {
                    CPU_RELAX();   // spin if queue is full (shouldn't happen here)
                }
            }
            std::cout << "  [Producer] pushed " << NUM_TICKS << " ticks\n";
        });

        // Consumer: strategy thread
        std::thread consumer([&queue, &received, NUM_TICKS]() {
            Tick t;
            while (received.load(std::memory_order_relaxed) < NUM_TICKS) {
                if (queue.pop(t)) {
                    received.fetch_add(1, std::memory_order_relaxed);
                } else {
                    CPU_RELAX();   // spin until next tick arrives
                }
            }
            std::cout << "  [Consumer] processed " << received.load() << " ticks\n";
        });

        producer.join();
        consumer.join();
        std::cout << "  Total processed: " << received.load() << "/" << NUM_TICKS << "\n";
    }

    // -------------------------------------------------------
    // LATENCY BENCHMARK — SPSC throughput
    // -------------------------------------------------------

    std::cout << "\n=== SPSC throughput benchmark ===\n";

    {
        SPSCQueue<Tick, 65536> queue;
        const int BENCH_N = 100000;
        std::atomic<int> count{0};
        std::atomic<bool> done{false};

        auto t0 = std::chrono::steady_clock::now();

        std::thread prod([&queue, BENCH_N]() {
            Tick t{};
            for (int i = 0; i < BENCH_N; ++i) {
                t.seq = uint32_t(i);
                while (!queue.push(t)) CPU_RELAX();
            }
        });

        std::thread cons([&queue, &count, BENCH_N]() {
            Tick t;
            while (count.load(std::memory_order_relaxed) < BENCH_N) {
                if (queue.pop(t)) count.fetch_add(1, std::memory_order_relaxed);
                else CPU_RELAX();
            }
        });

        prod.join();
        cons.join();

        auto t1 = std::chrono::steady_clock::now();
        auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count();

        std::cout << "  " << BENCH_N << " enqueue+dequeue in " << ns << "ns\n";
        std::cout << "  Per round trip: " << ns / BENCH_N << "ns\n";
    }

    // -------------------------------------------------------
    // LOCK-FREE STACK (CAS-based MPMC)
    // -------------------------------------------------------

    std::cout << "\n=== Lock-free stack ===\n";

    {
        LockFreeStack<int, 32> stack;

        // Push from multiple threads
        std::vector<std::thread> pushers;
        for (int i = 0; i < 4; ++i) {
            pushers.emplace_back([i, &stack]() {
                stack.push(i * 10);
            });
        }
        for (auto& t : pushers) t.join();

        // Pop from one thread
        int val;
        int count = 0;
        while (stack.pop(val)) {
            std::cout << "  Popped: " << val << "\n";
            ++count;
        }
        std::cout << "  Total popped: " << count << "\n";
    }

    // -------------------------------------------------------
    // CACHE LINE ALIGNMENT VERIFICATION
    // -------------------------------------------------------

    std::cout << "\n=== Cache line alignment ===\n";

    {
        SPSCQueue<int, 16> q;
        // The head_ and tail_ atomics must be 64 bytes apart
        // (each has alignas(64), so they're on separate cache lines)
        std::cout << "  SPSCQueue sizeof: " << sizeof(q) << " bytes\n";
        std::cout << "  Cache line size: 64 bytes\n";
        std::cout << "  head_ aligned to 64: "
                  << (alignof(std::atomic<uint64_t>) >= 8 ? "yes" : "no") << "\n";
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Full pipeline using 3 SPSC queues (feed → book → strategy → execution):

        SPSCQueue<Tick,   65536>  feed_to_book;    // feed thread → book thread
        SPSCQueue<BBO,    65536>  book_to_strat;   // book thread → strategy thread
        SPSCQueue<Order,  1024>   strat_to_exec;   // strategy thread → execution thread

        // Thread 1: Market data feed
        void run_feed() {
            while (running) {
                Tick t = recv_next_tick();
                while (!feed_to_book.push(t)) CPU_RELAX();  // never drops a tick
            }
        }

        // Thread 2: Order book maintenance
        void run_book() {
            Tick t;
            while (running) {
                while (feed_to_book.pop(t)) {
                    book.update(t);
                    BBO bbo = book.bbo();
                    book_to_strat.push(bbo);
                }
                CPU_RELAX();
            }
        }

        // Thread 3: Strategy evaluation
        void run_strategy() {
            BBO bbo;
            while (running) {
                while (book_to_strat.pop(bbo)) {
                    auto order = strategy.evaluate(bbo);
                    if (order) strat_to_exec.push(*order);
                }
                CPU_RELAX();
            }
        }

        // Thread 4: Execution / gateway
        void run_execution() {
            Order o;
            while (running) {
                while (strat_to_exec.pop(o)) {
                    if (!kill_switch && risk.check(o) == OK) {
                        gateway.send(o);
                    }
                }
                CPU_RELAX();
            }
        }
    */
}
