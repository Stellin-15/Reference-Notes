// ============================================================
// L35: std::thread — Creation, Join, Detach
// ============================================================
// WHAT: std::thread launches a function on a new OS thread.
//       join() waits for it to finish. detach() lets it run
//       independently. Thread arguments are passed by value
//       (copy) unless you explicitly use std::ref.
// WHY (TRADING): A production trading system runs multiple
//   concurrent threads so that slow operations never block
//   fast ones:
//     - Market data thread: receives and parses packets
//     - Order management thread: tracks open orders
//     - Strategy thread: evaluates signals
//     - Risk thread: checks limits in real time
//     - Logger thread: drains log queue to disk (async)
//   Without threads, a disk write would stall your feed parser.
// PHASE: Concurrency
// ============================================================

/*
  CONCEPT OVERVIEW:

  CREATING A THREAD:
    std::thread t(function, arg1, arg2, ...);
    The constructor immediately starts the thread.
    Arguments are COPIED into the thread by default.
    To pass by reference: std::ref(x) or std::cref(x).

  JOIN vs DETACH:
    t.join()   — blocks the calling thread until t finishes.
                 Must call either join() or detach() before t's
                 destructor — otherwise: std::terminate() is called.
    t.detach() — lets t run independently. You lose all control.
                 Only use for fire-and-forget tasks.
    t.joinable()— true if join/detach has not been called yet.

  THREAD ID:
    std::this_thread::get_id()  — get current thread's ID
    t.get_id()                  — get t's ID

  HARDWARE CONCURRENCY:
    std::thread::hardware_concurrency() — number of logical CPU cores
    Use to decide how many threads to spawn.

  SLEEP (for non-hot-path threads):
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    std::this_thread::yield()  — hint to scheduler to switch threads

  PASSING ARGUMENTS:
    // By value (copy):
    std::thread t(func, value);            // copies value into thread

    // By reference (must use std::ref):
    std::thread t(func, std::ref(shared)); // references shared in thread
    WARNING: shared must outlive the thread (lifetime guarantee)

    // By pointer (shared lifetime via pointer):
    std::thread t(func, &shared);

    // Lambda (captures context):
    std::thread t([&shared]() { shared.do_work(); });

  TRADING THREAD MODEL:
    Feed Thread  → parses market data → pushes to SPSC queue
    Book Thread  ← reads from queue → updates order book → signals strategy
    Strategy Thread → evaluates → sends orders to gateway
    Risk Thread  → monitors positions → kills switch on breach
    Logger Thread → drains async log queue → writes to disk

    Each thread owns its resources. Communication via queues (L38).

  COMMON MISTAKES:
    - Forgetting to join() or detach() → std::terminate() on thread destruction
    - Passing reference to a local that goes out of scope before thread ends
    - Spawning threads in a tight loop (thread creation is ~50µs — expensive)
    - Using detach() for threads that access shared state (race condition)
    - Not calling join() in destructor of a RAII wrapper (resource leak)
*/

#include <iostream>
#include <thread>
#include <chrono>
#include <vector>
#include <atomic>
#include <string>
#include <functional>  // std::ref

using namespace std::chrono_literals;

// ============================================================
// THREAD FUNCTION TYPES
// ============================================================

// Free function: simplest form
void market_data_function(int core_id, std::atomic<bool>& running) {
    std::cout << "[MDThread core=" << core_id << "] started, id="
              << std::this_thread::get_id() << "\n";

    int ticks_processed = 0;
    while (running.load(std::memory_order_relaxed)) {
        // Simulate receiving and processing a tick
        ++ticks_processed;
        std::this_thread::sleep_for(1ms);  // simulate tick interval

        if (ticks_processed >= 3) break;   // stop after 3 for demo
    }

    std::cout << "[MDThread core=" << core_id << "] processed "
              << ticks_processed << " ticks, exiting\n";
}

// ============================================================
// RAII THREAD WRAPPER
// ============================================================

// Ensures join() is always called — prevents std::terminate() if
// the owning object is destroyed before the thread finishes.
class JoinableThread {
public:
    template<typename F, typename... Args>
    explicit JoinableThread(F&& fn, Args&&... args)
        : thread_(std::forward<F>(fn), std::forward<Args>(args)...)
    {}

    ~JoinableThread() {
        if (thread_.joinable()) {
            thread_.join();   // guaranteed cleanup on all exit paths
        }
    }

    // Not copyable (threads can't be copied)
    JoinableThread(const JoinableThread&)            = delete;
    JoinableThread& operator=(const JoinableThread&) = delete;

    // Movable
    JoinableThread(JoinableThread&&)            = default;
    JoinableThread& operator=(JoinableThread&&) = default;

    std::thread::id get_id() const { return thread_.get_id(); }
    void join() { if (thread_.joinable()) thread_.join(); }

private:
    std::thread thread_;
};

// ============================================================
// TRADING THREAD ROLES — simulated
// ============================================================

struct SharedState {
    std::atomic<int>  tick_count{0};
    std::atomic<int>  order_count{0};
    std::atomic<bool> running{true};
    std::atomic<bool> kill_switch{false};
};

void feed_thread(SharedState& state) {
    std::cout << "[Feed] thread started\n";
    for (int i = 0; i < 5 && state.running; ++i) {
        state.tick_count.fetch_add(1, std::memory_order_relaxed);
        std::this_thread::sleep_for(2ms);
    }
    std::cout << "[Feed] thread done, ticks=" << state.tick_count.load() << "\n";
}

void strategy_thread(SharedState& state) {
    std::cout << "[Strategy] thread started\n";
    int last_tick = 0;
    for (int iter = 0; iter < 10 && state.running; ++iter) {
        int current = state.tick_count.load(std::memory_order_relaxed);
        if (current > last_tick) {
            // New tick arrived — evaluate signal
            state.order_count.fetch_add(1, std::memory_order_relaxed);
            last_tick = current;
        }
        std::this_thread::sleep_for(1ms);
    }
    std::cout << "[Strategy] thread done, orders=" << state.order_count.load() << "\n";
}

void risk_thread(SharedState& state) {
    std::cout << "[Risk] thread started\n";
    constexpr int MAX_ORDERS = 10;
    while (state.running) {
        int orders = state.order_count.load(std::memory_order_relaxed);
        if (orders > MAX_ORDERS) {
            state.kill_switch.store(true, std::memory_order_relaxed);
            std::cout << "[Risk] KILL SWITCH activated at " << orders << " orders\n";
            break;
        }
        std::this_thread::sleep_for(3ms);
    }
    std::cout << "[Risk] thread done\n";
}

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // HARDWARE CONCURRENCY
    // -------------------------------------------------------

    std::cout << "=== Hardware info ===\n";
    std::cout << "  Logical CPU cores: "
              << std::thread::hardware_concurrency() << "\n";
    std::cout << "  Main thread id: " << std::this_thread::get_id() << "\n";

    // -------------------------------------------------------
    // BASIC THREAD CREATION AND JOIN
    // -------------------------------------------------------

    std::cout << "\n=== Basic thread: join ===\n";

    {
        std::atomic<bool> running{true};

        // Launch thread passing atomic by reference with std::ref
        std::thread t(market_data_function, 0, std::ref(running));

        std::cout << "[Main] launched thread " << t.get_id() << "\n";
        std::cout << "[Main] waiting for thread to finish...\n";

        t.join();   // block until thread exits
        std::cout << "[Main] thread joined\n";
    }

    // -------------------------------------------------------
    // LAMBDA THREAD
    // -------------------------------------------------------

    std::cout << "\n=== Lambda thread ===\n";

    {
        int       result    = 0;
        const int num_ticks = 5;

        // Lambda captures result by reference — thread modifies it
        std::thread t([&result, num_ticks]() {
            std::cout << "[Lambda thread] processing " << num_ticks << " ticks\n";
            for (int i = 1; i <= num_ticks; ++i) result += i;
        });

        t.join();   // wait for lambda to complete
        std::cout << "[Main] sum of 1.." << num_ticks << " = " << result << "\n";
    }

    // -------------------------------------------------------
    // RAII THREAD WRAPPER
    // -------------------------------------------------------

    std::cout << "\n=== RAII JoinableThread ===\n";

    {
        std::atomic<bool> running{true};

        // JoinableThread automatically joins in its destructor
        JoinableThread jt(market_data_function, 1, std::ref(running));
        std::cout << "[Main] JoinableThread id: " << jt.get_id() << "\n";
        // jt destructor calls join() here — no explicit join needed
    }
    std::cout << "[Main] JoinableThread destroyed and joined\n";

    // -------------------------------------------------------
    // MULTIPLE THREADS (THREAD POOL PREVIEW)
    // -------------------------------------------------------

    std::cout << "\n=== Multiple threads ===\n";

    {
        const int NUM_THREADS = 3;
        std::vector<int> results(NUM_THREADS, 0);
        std::vector<std::thread> threads;
        threads.reserve(NUM_THREADS);

        for (int i = 0; i < NUM_THREADS; ++i) {
            // Each thread computes its own result
            threads.emplace_back([i, &results]() {
                results[i] = i * i;   // i is captured by value (copy)
                std::cout << "  [Thread " << i << "] result=" << results[i] << "\n";
                std::this_thread::sleep_for(std::chrono::milliseconds(i));
            });
        }

        // Join all threads before using results
        for (auto& t : threads) {
            t.join();
        }

        std::cout << "  All threads joined. Results: ";
        for (int r : results) std::cout << r << " ";
        std::cout << "\n";
    }

    // -------------------------------------------------------
    // TRADING SYSTEM — three cooperating threads
    // -------------------------------------------------------

    std::cout << "\n=== Trading system threads ===\n";

    {
        SharedState state;

        // Launch all three trading threads
        std::thread feed(feed_thread, std::ref(state));
        std::thread strat(strategy_thread, std::ref(state));
        std::thread risk(risk_thread, std::ref(state));

        // Wait for feed to finish, then signal others to stop
        feed.join();
        state.running.store(false, std::memory_order_relaxed);

        strat.join();
        risk.join();

        std::cout << "[Main] System shutdown. Total ticks=" << state.tick_count
                  << " orders=" << state.order_count
                  << " kill_switch=" << state.kill_switch.load() << "\n";
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Production thread launch sequence:

        // Pre-allocate all memory BEFORE launching threads
        // (no allocations allowed in threads after this point)
        auto order_pool     = std::make_unique<OrderPool>(10000);
        auto tick_ring      = std::make_unique<RingBuffer<Tick, 65536>>();
        auto order_queue    = std::make_unique<SPSCQueue<Order, 1024>>();

        std::atomic<bool> running{true};

        // Launch in priority order:
        // 1. Risk first — must be monitoring before any orders flow
        JoinableThread risk_t(run_risk, std::ref(*risk_mgr), std::ref(running));

        // 2. Strategy — needs book and risk ready
        JoinableThread strat_t(run_strategy, std::ref(*strategy), std::ref(running));

        // 3. Feed last — starts the data flowing
        JoinableThread feed_t(run_feed, std::ref(*feed_handler), std::ref(running));

        // All threads auto-join when JoinableThread goes out of scope
        // Teardown: signal running=false, threads finish naturally
    */
}
