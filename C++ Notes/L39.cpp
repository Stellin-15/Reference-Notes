// ============================================================
// L39: std::condition_variable and Signaling
// ============================================================
// WHAT: A condition variable lets one thread sleep until another
//       thread signals that some condition has become true.
//       It avoids busy-waiting (spinning) when you don't need
//       low latency — the sleeping thread costs zero CPU.
// WHY (TRADING): Condition variables are for SLOW PATH signaling:
//   - End-of-day processing: "market closed, compute PnL"
//   - Risk breach alert: "kill switch activated, notify operator"
//   - Background logger: "data in queue, wake up and write to disk"
//   - Config reload: "SIGHUP received, reload params"
//   In these cases, a 50–200µs wake-up latency is acceptable.
//   DO NOT use condition variables on the hot path (tick → order).
//   The hot path uses SPSC queues + spin loops (L38, L41).
// PHASE: Concurrency
// ============================================================

/*
  CONCEPT OVERVIEW:

  CONDITION VARIABLE:
    std::condition_variable  — works with std::unique_lock<std::mutex>
    std::condition_variable_any — works with any BasicLockable (std::shared_lock, etc.)

  BASIC USAGE:
    std::mutex mtx;
    std::condition_variable cv;
    bool ready = false;

    // WAITER thread:
    {
        std::unique_lock lock(mtx);
        cv.wait(lock, [&ready]{ return ready; });  // spurious wakeup safe!
        // lock is held here — condition is true
        consume_data();
    }

    // SIGNALER thread:
    {
        std::lock_guard lock(mtx);
        prepare_data();
        ready = true;
    }                        // unlock BEFORE notify (better performance)
    cv.notify_one();         // wake ONE waiting thread

  SPURIOUS WAKEUPS:
    wait() can return even if nobody called notify (OS limitation).
    Always use the predicate form: cv.wait(lock, predicate)
    This is equivalent to: while (!predicate()) cv.wait(lock);
    NEVER use raw cv.wait(lock) without a predicate — you'll process garbage.

  notify_one() vs notify_all():
    notify_one() — wake exactly one waiting thread (undefined which one)
    notify_all() — wake ALL waiting threads (each checks predicate, at most one proceeds)
    Use notify_all() when state change is relevant to multiple waiters.
    Use notify_one() for producer-consumer when only one consumer should act.

  TIMED WAIT:
    cv.wait_for(lock, timeout, predicate)  — give up after timeout
    cv.wait_until(lock, time_point, predicate)
    Returns true if condition became true, false if timed out.

  LATENCY OF condition_variable:
    notify_one() + OS scheduler wakeup: ~50µs–200µs on Linux with SCHED_OTHER.
    With SCHED_FIFO (real-time priority): ~10–50µs.
    Compare to: SPSC spin: < 1µs.
    This is why hot-path threads NEVER sleep on a condition variable.

  TRADING USE CASE:
    // Async logger: background thread sleeps until log queue has data
    // Strategy thread: push log entry to queue, notify_one()
    // Logger thread: cv.wait() until queue non-empty, drain to disk

    // EOD handler: sleeps until market close time
    // Timer thread: at 4:00 PM, notify_all()
    // Risk thread: wakes up, computes final PnL, writes report

  COMMON MISTAKES:
    - Forgetting the predicate in wait() — vulnerable to spurious wakeups
    - Calling notify() while holding the lock (works, but slower on some platforms)
    - Using condition_variable instead of SPSC for hot-path signaling
    - Accessing the condition variable after the mutex has been destroyed
    - Not holding the mutex when calling wait() — undefined behavior
*/

#include <iostream>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <queue>
#include <vector>
#include <string>
#include <chrono>
#include <atomic>
#include <functional>

using namespace std::chrono_literals;

// ============================================================
// ASYNC LOGGER — condition variable based
// ============================================================

struct LogEntry {
    uint64_t    timestamp_ns;
    std::string level;
    std::string message;
};

class AsyncLogger {
public:
    AsyncLogger() {
        // Background thread drains the queue to disk (or stdout here)
        worker_ = std::thread([this]() { run(); });
    }

    // Called from any thread — push entry and notify logger
    void log(const std::string& level, const std::string& msg) {
        uint64_t ts = static_cast<uint64_t>(
            std::chrono::steady_clock::now().time_since_epoch().count());

        {
            std::lock_guard lock(mtx_);
            queue_.push({ts, level, msg});
        }
        // Notify AFTER releasing the lock (avoids the notified thread
        // re-acquiring and immediately blocking on our lock)
        cv_.notify_one();
    }

    // Flush and wait for all pending entries to be written
    void flush() {
        std::unique_lock lock(mtx_);
        // Wait until queue is empty
        cv_flush_.wait(lock, [this]{ return queue_.empty(); });
    }

    ~AsyncLogger() {
        {
            std::lock_guard lock(mtx_);
            shutdown_ = true;
        }
        cv_.notify_all();   // wake worker so it sees shutdown_ == true
        if (worker_.joinable()) worker_.join();
    }

private:
    void run() {
        while (true) {
            std::unique_lock lock(mtx_);

            // Wait until there's something to write OR we're shutting down
            cv_.wait(lock, [this]{
                return !queue_.empty() || shutdown_;
            });

            // Drain the queue while holding the lock
            while (!queue_.empty()) {
                LogEntry entry = std::move(queue_.front());
                queue_.pop();
                lock.unlock();    // release lock while doing the slow I/O

                // Write to output (in real code: file write)
                std::cout << "  [LOG " << entry.level << "] " << entry.message
                          << " (ts=" << entry.timestamp_ns << ")\n";

                lock.lock();      // re-acquire before checking queue again
            }

            cv_flush_.notify_all();   // signal flush() waiters

            if (shutdown_ && queue_.empty()) break;
        }
    }

    std::mutex               mtx_;
    std::condition_variable  cv_;        // notified when queue has data or shutdown
    std::condition_variable  cv_flush_;  // notified when queue is empty
    std::queue<LogEntry>     queue_;
    bool                     shutdown_ = false;
    std::thread              worker_;
};

// ============================================================
// EOD (END OF DAY) SIGNAL
// ============================================================

class MarketCloseSignal {
public:
    // Blocks until market close is signaled
    void wait_for_close() {
        std::unique_lock lock(mtx_);
        cv_.wait(lock, [this]{ return closed_; });
        std::cout << "  [EOD] Market close received\n";
    }

    // Called from timer/operator thread at 4:00 PM
    void signal_close() {
        {
            std::lock_guard lock(mtx_);
            closed_ = true;
        }
        cv_.notify_all();   // notify all threads waiting (risk, PnL, logger)
    }

    bool is_closed() const {
        std::lock_guard lock(mtx_);
        return closed_;
    }

private:
    mutable std::mutex      mtx_;
    std::condition_variable cv_;
    bool                    closed_ = false;
};

// ============================================================
// WORK QUEUE — generic condition variable producer-consumer
// ============================================================

template<typename T>
class WorkQueue {
public:
    explicit WorkQueue(int max_size = 100) : max_size_(max_size) {}

    // Producer: push work item (blocks if queue is full)
    void push(T item) {
        std::unique_lock lock(mtx_);
        cv_not_full_.wait(lock, [this]{
            return static_cast<int>(queue_.size()) < max_size_ || shutdown_;
        });
        if (shutdown_) return;
        queue_.push(std::move(item));
        cv_not_empty_.notify_one();
    }

    // Consumer: pop work item (blocks if queue is empty)
    bool pop(T& item) {
        std::unique_lock lock(mtx_);
        cv_not_empty_.wait(lock, [this]{
            return !queue_.empty() || shutdown_;
        });
        if (queue_.empty()) return false;  // shutdown with empty queue
        item = std::move(queue_.front());
        queue_.pop();
        cv_not_full_.notify_one();
        return true;
    }

    void shutdown() {
        {
            std::lock_guard lock(mtx_);
            shutdown_ = true;
        }
        cv_not_empty_.notify_all();
        cv_not_full_.notify_all();
    }

    int size() const {
        std::lock_guard lock(mtx_);
        return static_cast<int>(queue_.size());
    }

private:
    mutable std::mutex      mtx_;
    std::condition_variable cv_not_empty_;
    std::condition_variable cv_not_full_;
    std::queue<T>           queue_;
    int                     max_size_;
    bool                    shutdown_ = false;
};

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // ASYNC LOGGER
    // -------------------------------------------------------

    std::cout << "=== Async logger ===\n";

    {
        AsyncLogger logger;

        // Multiple threads log simultaneously — no blocking in hot path
        std::vector<std::thread> threads;
        for (int i = 0; i < 3; ++i) {
            threads.emplace_back([i, &logger]() {
                logger.log("INFO",  "Thread " + std::to_string(i) + " started");
                std::this_thread::sleep_for(std::chrono::milliseconds(i));
                logger.log("INFO",  "Thread " + std::to_string(i) + " done");
            });
        }
        for (auto& t : threads) t.join();

        logger.log("WARN", "Risk check: position limit approaching");
        logger.log("ERROR", "Order rejected: insufficient margin");
        logger.flush();   // wait until all entries written
        std::cout << "  All log entries flushed\n";
    }

    // -------------------------------------------------------
    // EOD SIGNAL — notify_all pattern
    // -------------------------------------------------------

    std::cout << "\n=== EOD market close signal ===\n";

    {
        MarketCloseSignal close_signal;
        std::atomic<int> eod_tasks_done{0};

        // Multiple threads waiting for market close (risk, PnL, position reconcile)
        std::vector<std::thread> eod_threads;
        const char* task_names[] = {"Risk Report", "PnL Calc", "Position Reconcile"};
        for (int i = 0; i < 3; ++i) {
            eod_threads.emplace_back([i, &close_signal, &eod_tasks_done, &task_names]() {
                close_signal.wait_for_close();   // all three block here
                std::cout << "  [" << task_names[i] << "] running EOD processing\n";
                eod_tasks_done.fetch_add(1, std::memory_order_relaxed);
            });
        }

        // Simulate market close timer
        std::this_thread::sleep_for(10ms);
        std::cout << "  [Timer] Signaling market close...\n";
        close_signal.signal_close();   // notify_all wakes all 3 threads

        for (auto& t : eod_threads) t.join();
        std::cout << "  EOD tasks completed: " << eod_tasks_done.load() << "/3\n";
    }

    // -------------------------------------------------------
    // WORK QUEUE — producer/consumer with backpressure
    // -------------------------------------------------------

    std::cout << "\n=== Work queue (bounded, backpressure) ===\n";

    {
        WorkQueue<std::string> work_queue(5);   // max 5 items buffered

        // Producer: generates work items
        std::thread producer([&work_queue]() {
            for (int i = 0; i < 8; ++i) {
                std::string task = "Task_" + std::to_string(i);
                work_queue.push(task);
                std::cout << "  [Producer] pushed " << task << "\n";
            }
            work_queue.shutdown();
        });

        // Consumer: processes work items
        std::thread consumer([&work_queue]() {
            std::string task;
            while (work_queue.pop(task)) {
                std::cout << "  [Consumer] processed " << task << "\n";
                std::this_thread::sleep_for(2ms);  // simulate slow processing
            }
            std::cout << "  [Consumer] queue shut down\n";
        });

        producer.join();
        consumer.join();
    }

    // -------------------------------------------------------
    // TIMED WAIT — timeout example
    // -------------------------------------------------------

    std::cout << "\n=== Timed wait (timeout) ===\n";

    {
        std::mutex mtx;
        std::condition_variable cv;
        bool data_ready = false;

        // Consumer: wait with timeout
        std::thread consumer([&mtx, &cv, &data_ready]() {
            std::unique_lock lock(mtx);
            // Wait up to 5ms for data
            bool got_data = cv.wait_for(lock, 5ms, [&data_ready]{ return data_ready; });
            if (got_data) {
                std::cout << "  [Timed wait] Data arrived in time\n";
            } else {
                std::cout << "  [Timed wait] Timed out — no data in 5ms\n";
            }
        });

        // Producer: signals after 10ms (after timeout)
        std::this_thread::sleep_for(10ms);
        {
            std::lock_guard lock(mtx);
            data_ready = true;
        }
        cv.notify_one();

        consumer.join();
    }

    // -------------------------------------------------------
    // PERFORMANCE NOTE
    // -------------------------------------------------------

    std::cout << "\n=== Condition variable latency note ===\n";

    {
        std::mutex mtx;
        std::condition_variable cv;
        bool ready = false;

        auto t0 = std::chrono::steady_clock::now();

        std::thread waiter([&mtx, &cv, &ready]() {
            std::unique_lock lock(mtx);
            cv.wait(lock, [&ready]{ return ready; });
        });

        std::this_thread::sleep_for(1ms);
        {
            std::lock_guard lock(mtx);
            ready = true;
        }
        auto t_notify = std::chrono::steady_clock::now();
        cv.notify_one();

        waiter.join();
        auto t1 = std::chrono::steady_clock::now();

        auto notify_to_wake = std::chrono::duration_cast<std::chrono::microseconds>(
            t1 - t_notify).count();

        std::cout << "  notify_one() to wakeup: ~" << notify_to_wake << "µs\n";
        std::cout << "  (SPSC spin: < 1µs — 50-200x faster for hot path)\n";
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Complete async logger used by the hot-path trading thread:

        // In the trading system: hot path NEVER blocks on I/O
        // The SPSC queue feeds the logger thread (no mutex in hot path)

        // Hot path (strategy thread, < 1µs total):
        void on_tick(const Tick& t) noexcept {
            // ... evaluate strategy ...
            auto order = strategy_.evaluate(t);
            if (order) {
                log_queue_.push(LogEntry{now_ns(), "ORDER", order->to_string()});
                // push to SPSC — non-blocking, < 20ns
                gateway_.send(*order);
            }
        }

        // Logger thread (background, slow path is OK):
        void run_logger() {
            LogEntry entry;
            while (!shutdown_) {
                if (log_queue_.pop(entry)) {
                    file_ << entry.timestamp_ns << " " << entry.message << "\n";
                } else {
                    // No work: sleep until notified (saves CPU on slow periods)
                    std::unique_lock lock(mtx_);
                    cv_.wait_for(lock, 1ms, [this]{ return !log_queue_.empty(); });
                }
            }
        }

        // The logger thread is NOT in the critical latency path —
        // it wakes up when there's work, writes to disk, goes back to sleep.
        // The trading thread never waits for disk I/O.
    */
}
