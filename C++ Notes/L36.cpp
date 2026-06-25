// ============================================================
// L36: Mutexes and Locking
// ============================================================
// WHAT: A mutex (mutual exclusion) prevents two threads from
//       modifying shared data simultaneously. lock_guard and
//       unique_lock are RAII wrappers that automatically unlock.
//       scoped_lock (C++17) locks multiple mutexes safely.
// WHY (TRADING): Shared mutable state is the enemy of correct
//   concurrent code. Your position tracker, order registry,
//   and risk state are all shared between the strategy thread
//   and the fill/ack handler thread. Without a mutex, two
//   threads can corrupt data simultaneously (race condition).
//   That said, mutexes introduce latency — a locked mutex
//   means the second thread WAITS. In the hot path, use
//   atomics or lock-free queues (L37, L38) instead.
// PHASE: Concurrency
// ============================================================

/*
  CONCEPT OVERVIEW:

  MUTEX TYPES:
    std::mutex           — basic mutual exclusion, not recursive
    std::recursive_mutex — same thread can lock it multiple times
    std::timed_mutex     — try_lock_for(), try_lock_until() with timeout
    std::shared_mutex    — multiple readers OR one writer (reader-writer lock)

  LOCKING WRAPPERS (always prefer these over raw lock()/unlock()):
    std::lock_guard<std::mutex>  — lock on construct, unlock on destroy. No unlock.
    std::unique_lock<std::mutex> — flexible: can unlock() and relock(), movable
    std::scoped_lock<M1, M2>     — C++17: lock multiple mutexes atomically (deadlock-safe)
    std::shared_lock<std::shared_mutex> — read-only lock for shared_mutex

  DEADLOCK:
    Thread A holds lock1, waits for lock2.
    Thread B holds lock2, waits for lock1.
    Both wait forever.
    Prevention:
    1. Always lock mutexes in the same order.
    2. Use std::scoped_lock (locks all at once, deadlock-free).
    3. Use std::lock() + std::adopt_lock trick (pre-C++17).

  TRY_LOCK:
    m.try_lock()            — attempt lock, return immediately (true/false)
    unique_lock ul(m, std::try_to_lock)  — non-blocking attempt
    if (ul) { /* locked */ }

  READER-WRITER LOCK:
    Multiple threads can read simultaneously (shared_lock).
    Only one thread can write (unique_lock).
    Best for: order book read by many, written by one feed thread.
    std::shared_mutex bm;
    std::shared_lock rl(bm);   // read lock
    std::unique_lock wl(bm);   // write lock

  TRADING USE CASE:
    // Position tracker: many readers (risk, PnL), one writer (fill handler)
    class PositionTracker {
        mutable std::shared_mutex mtx_;
        std::unordered_map<std::string, int64_t> positions_;

        int64_t get(const std::string& sym) const {
            std::shared_lock rl(mtx_);   // concurrent reads OK
            return positions_.at(sym);
        }
        void on_fill(const std::string& sym, int64_t delta) {
            std::unique_lock wl(mtx_);   // exclusive write
            positions_[sym] += delta;
        }
    };

  COMMON MISTAKES:
    - Using raw lock()/unlock() instead of RAII wrappers (exception leaks the lock)
    - Holding a lock while doing slow I/O (blocks all other threads)
    - Forgetting mutex is not recursive — same thread locking twice → deadlock
    - Copying a unique_lock (it's move-only)
    - Using mutex in hot-path inner loop (use atomics or lock-free instead)
    - Two threads locking different mutexes in different orders → deadlock
*/

#include <iostream>
#include <thread>
#include <mutex>
#include <shared_mutex>
#include <vector>
#include <unordered_map>
#include <string>
#include <chrono>
#include <atomic>
#include <cassert>

using namespace std::chrono_literals;

// ============================================================
// POSITION TRACKER — reader-writer lock pattern
// ============================================================

class PositionTracker {
public:
    // Read: can be called from multiple threads simultaneously
    int64_t get(const std::string& symbol) const {
        std::shared_lock rl(mtx_);   // shared (read) lock — multiple readers OK
        auto it = positions_.find(symbol);
        return (it != positions_.end()) ? it->second : 0;
    }

    // Write: exclusive access — only one thread at a time
    void on_fill(const std::string& symbol, int64_t delta) {
        std::unique_lock wl(mtx_);   // exclusive (write) lock
        positions_[symbol] += delta;
    }

    // Read all positions: still needs shared lock (the map could be modified)
    std::unordered_map<std::string, int64_t> snapshot() const {
        std::shared_lock rl(mtx_);
        return positions_;   // copy under lock, then return
    }

    double gross_notional(const std::unordered_map<std::string, double>& prices) const {
        std::shared_lock rl(mtx_);
        double total = 0.0;
        for (const auto& [sym, qty] : positions_) {
            auto it = prices.find(sym);
            if (it != prices.end()) {
                total += std::abs(static_cast<double>(qty)) * it->second;
            }
        }
        return total;
    }

private:
    mutable std::shared_mutex                    mtx_;
    std::unordered_map<std::string, int64_t>     positions_;
};

// ============================================================
// ORDER REGISTRY — basic mutex + lock_guard
// ============================================================

struct Order {
    uint64_t    id;
    std::string symbol;
    int64_t     price;
    int32_t     qty;
    bool        is_open;
};

class OrderRegistry {
public:
    void add(const Order& o) {
        std::lock_guard lock(mtx_);   // RAII: unlocks on scope exit
        orders_[o.id] = o;
    }

    bool cancel(uint64_t id) {
        std::lock_guard lock(mtx_);
        auto it = orders_.find(id);
        if (it == orders_.end()) return false;
        it->second.is_open = false;
        return true;
    }

    int open_count() const {
        std::lock_guard lock(mtx_);   // mutable: lock_guard on mutable mutex
        int count = 0;
        for (const auto& [id, o] : orders_) {
            if (o.is_open) ++count;
        }
        return count;
    }

private:
    mutable std::mutex                   mtx_;
    std::unordered_map<uint64_t, Order>  orders_;
};

// ============================================================
// RISK STATE — multiple locks, deadlock-safe with scoped_lock
// ============================================================

struct RiskCounters {
    std::mutex mtx;
    int64_t    daily_pnl   = 0;
    int        order_count = 0;
    int        fill_count  = 0;
};

// Transfers PnL from one counter to another.
// Must lock BOTH — use scoped_lock to do it atomically.
void transfer_pnl(RiskCounters& src, RiskCounters& dst, int64_t amount) {
    // scoped_lock: locks both mutexes simultaneously (deadlock-safe)
    // Does NOT require locking in a fixed order — it uses internal deadlock avoidance
    std::scoped_lock lock(src.mtx, dst.mtx);   // both locked atomically
    src.daily_pnl -= amount;
    dst.daily_pnl += amount;
}

// ============================================================
// DEMO: data race WITHOUT mutex (intentionally bad — for comparison)
// ============================================================

// This counter is accessed from multiple threads WITHOUT a mutex.
// In a real system this would cause a data race (undefined behavior).
// We show it here to illustrate what a mutex prevents.
struct UnsafeCounter { int64_t value = 0; };

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // BASIC MUTEX + LOCK_GUARD
    // -------------------------------------------------------

    std::cout << "=== lock_guard (basic mutex) ===\n";

    {
        OrderRegistry registry;
        std::vector<std::thread> threads;

        // Launch 4 threads adding orders concurrently
        for (int i = 0; i < 4; ++i) {
            threads.emplace_back([i, &registry]() {
                Order o{uint64_t(1000 + i), "AAPL",
                        int64_t(1825000 + i * 100), 100, true};
                registry.add(o);
                std::cout << "  [Thread " << i << "] added order " << o.id << "\n";
            });
        }
        for (auto& t : threads) t.join();
        std::cout << "  Open orders: " << registry.open_count() << "\n";

        // Cancel one from main thread (concurrent with others safe via mutex)
        registry.cancel(1001);
        std::cout << "  After cancel: " << registry.open_count() << " open\n";
    }

    // -------------------------------------------------------
    // SHARED MUTEX — reader-writer pattern
    // -------------------------------------------------------

    std::cout << "\n=== shared_mutex (reader-writer) ===\n";

    {
        PositionTracker tracker;

        // One writer thread (fill handler)
        std::thread writer([&tracker]() {
            std::string fills[] = {"AAPL", "AAPL", "TSLA", "MSFT"};
            int64_t     deltas[] = {100, 50, -200, 300};
            for (int i = 0; i < 4; ++i) {
                tracker.on_fill(fills[i], deltas[i]);
                std::cout << "  [Writer] on_fill " << fills[i]
                          << " delta=" << deltas[i] << "\n";
                std::this_thread::sleep_for(1ms);
            }
        });

        // Multiple reader threads (risk, PnL display) — run concurrently
        std::vector<std::thread> readers;
        for (int i = 0; i < 3; ++i) {
            readers.emplace_back([i, &tracker]() {
                for (int j = 0; j < 3; ++j) {
                    int64_t pos = tracker.get("AAPL");
                    std::cout << "  [Reader " << i << "] AAPL position=" << pos << "\n";
                    std::this_thread::sleep_for(2ms);
                }
            });
        }

        writer.join();
        for (auto& r : readers) r.join();

        auto snap = tracker.snapshot();
        std::cout << "  Final positions:\n";
        for (const auto& [sym, qty] : snap) {
            std::cout << "    " << sym << ": " << qty << "\n";
        }
    }

    // -------------------------------------------------------
    // SCOPED_LOCK — multiple mutexes, deadlock-safe
    // -------------------------------------------------------

    std::cout << "\n=== scoped_lock (multi-mutex) ===\n";

    {
        RiskCounters main_desk;
        RiskCounters hedge_desk;

        main_desk.daily_pnl  = 50000;
        hedge_desk.daily_pnl = 10000;

        // Thread A: transfers from main to hedge
        std::thread tA([&main_desk, &hedge_desk]() {
            transfer_pnl(main_desk, hedge_desk, 5000);
            std::cout << "  [ThreadA] transferred 5000 from main to hedge\n";
        });

        // Thread B: transfers from hedge to main (opposite direction)
        // Without scoped_lock: A locks main, B locks hedge → deadlock
        // With scoped_lock: safe regardless of order
        std::thread tB([&main_desk, &hedge_desk]() {
            transfer_pnl(hedge_desk, main_desk, 2000);
            std::cout << "  [ThreadB] transferred 2000 from hedge to main\n";
        });

        tA.join(); tB.join();

        std::cout << "  Main desk PnL:  " << main_desk.daily_pnl << "\n";
        std::cout << "  Hedge desk PnL: " << hedge_desk.daily_pnl << "\n";
    }

    // -------------------------------------------------------
    // TRY_LOCK — non-blocking attempt
    // -------------------------------------------------------

    std::cout << "\n=== try_lock (non-blocking) ===\n";

    {
        std::mutex mtx;
        bool locked = mtx.try_lock();
        std::cout << "  First try_lock: " << locked << " (should be 1)\n";

        bool locked2 = mtx.try_lock();   // already locked by this thread — fails
        // Note: std::mutex is not recursive — this is undefined behavior.
        // In practice on most platforms try_lock returns false. In real code,
        // use std::recursive_mutex or restructure to avoid double-locking.
        std::cout << "  Second try_lock (same thread): " << locked2 << " (implementation-defined)\n";

        if (locked) mtx.unlock();
        if (locked2) mtx.unlock();

        // Better pattern: unique_lock with try_to_lock
        std::unique_lock ul(mtx, std::try_to_lock);
        if (ul) {
            std::cout << "  unique_lock acquired\n";
            // do work
        } else {
            std::cout << "  unique_lock: mutex busy — skipping\n";
        }
    }

    // -------------------------------------------------------
    // PERFORMANCE NOTE
    // -------------------------------------------------------

    std::cout << "\n=== Mutex performance note ===\n";

    {
        std::mutex mtx;
        const int ITERS = 100000;

        auto t0 = std::chrono::steady_clock::now();
        int64_t val = 0;
        for (int i = 0; i < ITERS; ++i) {
            std::lock_guard lock(mtx);
            ++val;
        }
        auto t1 = std::chrono::steady_clock::now();
        auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count();

        std::cout << "  " << ITERS << " mutex lock/unlock cycles: " << ns << "ns total\n";
        std::cout << "  Per cycle: " << ns / ITERS << "ns\n";
        std::cout << "  (uncontended mutex ≈ 20-50ns; contended ≈ 200-1000ns)\n";
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Two-tier locking strategy: mutex for slow path, atomic for hot path.

        // HOT PATH: atomic (no mutex, < 1ns)
        std::atomic<int64_t> position_{0};
        void on_fill_hot(int64_t delta) {
            position_.fetch_add(delta, std::memory_order_relaxed);
        }

        // SLOW PATH: mutex for complex state (risk report, EOD PnL)
        std::shared_mutex mtx_;
        std::unordered_map<std::string, PositionDetail> detailed_positions_;

        void on_fill_slow(const Fill& f) {
            std::unique_lock wl(mtx_);
            detailed_positions_[f.symbol].update(f);
        }
        PositionDetail get_detail(const std::string& sym) const {
            std::shared_lock rl(mtx_);
            return detailed_positions_.at(sym);
        }

        // Risk display thread (every 100ms): reads detailed positions
        // Fill handler thread: writes on every fill
        // Strategy hot path: reads atomic position_ (no mutex ever)
    */
}
