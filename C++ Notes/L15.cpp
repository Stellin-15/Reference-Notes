// ============================================================
// L15: Scope, Lifetime, and RAII
// ============================================================
// WHAT: Every variable has a scope (where it can be named) and
//       a lifetime (how long its memory exists). RAII ties
//       resource management to object lifetime automatically.
// WHY (TRADING): RAII is the single most important C++ idiom
//   for correctness in trading systems. It guarantees that:
//   - Mutexes are always unlocked (never deadlock from early return)
//   - File handles are always closed (no fd leaks in logging)
//   - Network connections are always closed (no ghost sessions)
//   - Memory is always freed (no leaks during exceptions)
//   ALL of this happens automatically, even when the code path
//   exits early due to errors or exceptions.
// PHASE: Foundation
// ============================================================

/*
  CONCEPT OVERVIEW:

  SCOPE:
    The region of code where a name is visible.
    Defined by { } braces — a new scope begins at { and ends at }.
    Inner scopes can see outer scopes. Outer scopes cannot see inner ones.
    Variables declared inside a scope SHADOW outer variables of the same name
    (compilers warn about this — it's almost always a bug).

  LIFETIME:
    How long a variable's memory actually exists.
    - Local variables: live from declaration to end of their scope { }
    - Static local variables: live from first execution to program end
    - Global variables: live for the entire program duration
    - Heap variables: live from new until delete (or until unique_ptr dies)

  STATIC LOCAL VARIABLES:
    static T x = init_value;   — initialized ONCE on first call, persists forever
    Thread-safe initialization in C++11 (no locks needed for the init itself)
    Used in: singleton patterns, memoization, counters

  RAII — Resource Acquisition Is Initialization:
    The CORE C++ pattern for resource safety.
    Idea:
      - Acquire a resource (lock, file, socket, memory) in a CONSTRUCTOR
      - Release it in the DESTRUCTOR
      - The destructor ALWAYS runs when the object goes out of scope — even on error
    This makes resource leaks structurally IMPOSSIBLE if done right.

    Real examples in trading:
      std::lock_guard<std::mutex> lock(mtx);   — unlocks when lock goes out of scope
      std::unique_ptr<Order> p(new Order);      — deletes when p goes out of scope
      std::fstream file("log.txt");             — closes file when file goes out of scope

  RAII IN HFT:
    - Mutex guards: every lock is wrapped in a RAII guard
    - Scope-based timing: "start timer at entry, stop at exit" — RAII
    - Transaction guards: "begin transaction, commit/rollback on exit" — RAII
    - Order lifecycle: "begin processing, mark done on exit" — RAII

  STATIC CLASS MEMBERS:
    static int count;  — ONE instance shared by all objects of that class
    Used in: order ID generators, singleton exchange connections

  TRADING USE CASE:
    // RAII lock guard: mutex ALWAYS unlocked, even if return/exception happens
    {
        std::lock_guard<std::mutex> guard(position_mutex);
        position[symbol] += qty;  // thread-safe access
    }  // guard destructor runs here: mutex unlocked

    // RAII timer: automatically records elapsed time at scope exit
    {
        ScopedTimer timer("tick_to_order");
        process_tick(tick);   // even if this throws, timer.stop() is called
        build_order(signal);
        send_order(order);
    }  // timer logs the total latency here

  COMMON MISTAKES:
    - Shadowing outer variable with same name inside inner scope
    - Forgetting static means "initialized once" — can't reset on next call
    - Thinking RAII requires exceptions — it works without them
    - Letting RAII guards go out of scope too late (holding locks too long)
*/

#include <iostream>
#include <string>
#include <cstdint>
#include <mutex>    // std::mutex, std::lock_guard
#include <chrono>   // for timing demo

// -------------------------------------------------------
// RAII CLASSES — building blocks for trading systems
// -------------------------------------------------------

// RAII Timer: measures and prints elapsed time at scope exit
class ScopedTimer {
public:
    ScopedTimer(const char* name)
        : name_(name)
        , start_(std::chrono::high_resolution_clock::now()) {
        std::cout << "[Timer] " << name_ << " started\n";
    }

    ~ScopedTimer() {
        // Destructor ALWAYS runs when this object goes out of scope
        auto end = std::chrono::high_resolution_clock::now();
        auto ns  = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start_).count();
        std::cout << "[Timer] " << name_ << " elapsed: " << ns << " ns\n";
    }

private:
    const char*                                             name_;
    std::chrono::time_point<std::chrono::high_resolution_clock> start_;
};

// RAII File Logger: opens file on construction, closes on destruction
class LogFile {
public:
    LogFile(const char* filename) : filename_(filename) {
        // In real code: open the file here
        std::cout << "[LogFile] Opened: " << filename_ << "\n";
        is_open_ = true;
    }

    ~LogFile() {
        if (is_open_) {
            // In real code: flush and close the file here
            std::cout << "[LogFile] Closed: " << filename_ << "\n";
            is_open_ = false;
        }
    }

    void write(const std::string& msg) {
        if (is_open_) {
            std::cout << "[LogFile:" << filename_ << "] " << msg << "\n";
        }
    }

    // Disable copying — a file handle shouldn't be copied
    LogFile(const LogFile&) = delete;
    LogFile& operator=(const LogFile&) = delete;

private:
    const char* filename_;
    bool        is_open_;
};

// RAII Order Guard: ensures an order is marked "done" when processing exits
class OrderProcessingGuard {
public:
    explicit OrderProcessingGuard(uint64_t order_id)
        : order_id_(order_id), committed_(false) {
        std::cout << "[Guard] Begin processing order #" << order_id_ << "\n";
    }

    void commit() {
        committed_ = true;
    }

    ~OrderProcessingGuard() {
        if (!committed_) {
            // Order processing exited without commit — mark as failed
            std::cout << "[Guard] Order #" << order_id_ << " was NOT committed — marking failed\n";
        } else {
            std::cout << "[Guard] Order #" << order_id_ << " committed successfully\n";
        }
    }

private:
    uint64_t order_id_;
    bool     committed_;
};

// Static member: shared across all instances — used for order ID generation
class OrderIdGenerator {
public:
    static uint64_t next() {
        static uint64_t counter = 1000000;   // static local: initialized ONCE
        return ++counter;                     // atomicity not shown — see L37 for atomic
    }
};

int main() {

    // -------------------------------------------------------
    // SCOPE BASICS
    // -------------------------------------------------------

    std::cout << "--- Scope demonstration ---\n";

    int x = 10;  // outer scope

    {  // new scope begins
        int y = 20;   // y only exists inside these braces
        std::cout << "Inside inner scope: x=" << x << " y=" << y << "\n";

        // Shadowing: x is a new variable that HIDES the outer x
        // (compiler usually warns about this — almost always a bug)
        // int x = 99;   // would shadow the outer x

    }  // y is destroyed here — its destructor runs, memory is reclaimed
    // std::cout << y;  // COMPILE ERROR: y not in scope here

    std::cout << "Back in outer scope: x=" << x << "\n";

    // -------------------------------------------------------
    // LIFETIME DEMO
    // -------------------------------------------------------

    std::cout << "\n--- Variable lifetime ---\n";

    // Stack: lives until end of block
    {
        double tick_price = 182.50;
        std::cout << "tick_price alive: $" << tick_price << "\n";
    }
    // tick_price is gone here

    // Static local: lives from first call until program ends
    auto get_session_id = []() -> uint64_t {
        static uint64_t session_id = 20240101001;   // initialized ONCE
        return session_id;
    };
    std::cout << "Session ID: " << get_session_id() << "\n";
    std::cout << "Session ID: " << get_session_id() << "\n";  // same value every time

    // -------------------------------------------------------
    // RAII TIMER
    // -------------------------------------------------------

    std::cout << "\n--- RAII Timer ---\n";

    {
        ScopedTimer timer("order_processing");   // starts timing

        // Simulate some work
        volatile double price = 0.0;
        for (int i = 0; i < 1000000; ++i) price += 0.001;

        std::cout << "Work done (result: " << price << ")\n";

    }   // timer destructor runs HERE — prints elapsed time
    // No need to call stop() explicitly — RAII handles it

    // -------------------------------------------------------
    // RAII LOG FILE
    // -------------------------------------------------------

    std::cout << "\n--- RAII Log File ---\n";

    {
        LogFile trades_log("trades.log");   // opens file

        trades_log.write("BUY 100 AAPL @ 182.50");
        trades_log.write("SELL 50 TSLA @ 245.00");

        // Even if an exception were thrown here, the file would still close
        // because the destructor runs during stack unwinding

    }   // trades_log destructor runs: file is closed, buffers flushed

    // -------------------------------------------------------
    // RAII MUTEX GUARD (the standard pattern)
    // -------------------------------------------------------

    std::cout << "\n--- RAII Mutex Guard ---\n";

    std::mutex position_mutex;
    int        position = 0;

    {
        // std::lock_guard is a RAII wrapper around a mutex
        // Locks in constructor, unlocks in destructor
        std::lock_guard<std::mutex> guard(position_mutex);

        // Thread-safe access to shared position
        position += 100;  // BUY 100
        std::cout << "Position updated: " << position << " (mutex held)\n";

    }   // guard destructor runs here: mutex ALWAYS unlocked, even on early return
    std::cout << "Mutex released (lock_guard went out of scope)\n";

    // -------------------------------------------------------
    // RAII ORDER GUARD — cleanup on all exit paths
    // -------------------------------------------------------

    std::cout << "\n--- RAII Order Guard ---\n";

    // Success path: order is committed
    {
        OrderProcessingGuard guard(1001);
        // ... do the work ...
        guard.commit();   // mark success
    }   // destructor sees committed=true: prints success

    // Failure path: order NOT committed (e.g., risk check failed)
    {
        OrderProcessingGuard guard(1002);
        // Simulate a risk rejection — return early without committing
        bool risk_passed = false;
        if (!risk_passed) {
            std::cout << "Risk check failed — exiting early\n";
            // NO commit() call
        }
    }   // destructor sees committed=false: prints failure — auto cleanup

    // -------------------------------------------------------
    // STATIC ORDER ID GENERATOR
    // -------------------------------------------------------

    std::cout << "\n--- Static member: Order ID generator ---\n";

    for (int i = 0; i < 5; ++i) {
        uint64_t id = OrderIdGenerator::next();
        std::cout << "Generated order ID: " << id << "\n";
    }
    // IDs are sequential and never reset — persists for the program's lifetime

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Full RAII pattern for a complete order processing transaction:

        bool process_order(Order& order) {
            OrderProcessingGuard guard(order.id);  // marks failed on any exit
            ScopedTimer timer("process_order");     // measures latency on any exit

            // Step 1: validate
            if (!validate(order)) return false;     // guard auto-marks failed

            // Step 2: risk check
            {
                std::lock_guard<std::mutex> lock(risk_mutex);  // auto-unlocks
                if (!risk_check(order)) return false;          // lock auto-released
            }

            // Step 3: send to exchange
            gateway.send(order);

            // Step 4: log
            log_file.write("SENT: " + to_string(order.id));   // log auto-closes later

            guard.commit();   // success: guard will print success on destruction
            return true;
        }
        // On exit (success OR failure): guard prints result, timer logs latency,
        // mutex is unlocked, log file is not closed (it's shared), all automatically.
    */
}
