// ============================================================
// L31: Error Handling Strategies
// ============================================================
// WHAT: C++ offers three main error-reporting strategies:
//       exceptions (try/catch/throw), error return codes, and
//       std::expected (C++23). Each has very different cost and
//       semantics.
// WHY (TRADING): HFT code avoids exceptions in the hot path
//   because they cause non-deterministic latency — the C++
//   runtime unwinds the stack, calls destructors, and may
//   allocate heap memory just to carry the exception object.
//   A missed risk check at 2µs latency is better than a
//   surprise 500µs exception in the middle of order flow.
//   Use error codes on the hot path; exceptions only at startup
//   or in off-path (config loading, connection setup).
// PHASE: Modern C++
// ============================================================

/*
  CONCEPT OVERVIEW:

  EXCEPTIONS (try / catch / throw):
    throw expr;              — raise an exception, unwind the stack
    try { ... }              — scope that may throw
    catch (const T& e) { }  — handle exceptions of type T (catch by const ref)
    catch (...) { }          — catch everything (use only as last resort)
    throw;                   — re-throw the current exception (inside catch block)
    noexcept                 — mark that a function will NEVER throw (optimizer hint)
    noexcept(expr)           — conditional noexcept (true/false based on expr)

  STANDARD EXCEPTION HIERARCHY:
    std::exception             — base class, .what() returns error string
    std::runtime_error         — detectable at runtime (bad data, bad state)
    std::logic_error           — programming error (invalid argument, etc.)
    std::invalid_argument      — wrong argument value
    std::out_of_range          — index out of range
    std::overflow_error        — numeric overflow
    std::bad_alloc             — new/malloc out of memory

  EXCEPTION COST (WHY HFT AVOIDS THEM):
    No exception thrown: near-zero overhead (just a stack frame flag).
    Exception thrown:    ~500ns–10µs of non-deterministic latency.
    Reason: stack unwinding, destructor calls, OS page fault for exception object.
    In HFT: any non-determinism > 1µs is unacceptable in the hot path.
    Rule: exceptions are OK for startup (config load, connection), NOT trading.

  ERROR CODES:
    Return an int/enum/struct indicating success or failure.
    Checked immediately by the caller — deterministic, zero overhead.
    Downside: easy to ignore, must propagate manually through call stack.

  ASSERT:
    assert(condition)    — debug-build only (removed by -DNDEBUG in release)
    Use for: invariants that MUST be true, programmer bugs, never user errors.
    static_assert(expr, msg) — compile-time check. Zero runtime cost.

  STD::EXPECTED (C++23 preview):
    std::expected<T, E>  — holds either a T (success) or an E (error)
    Like a type-safe union of "success value" or "error value".
    Forces the caller to check which case they have.
    Similar to Rust's Result<T,E>. Zero overhead when not erroring.

  NOEXCEPT:
    Mark functions noexcept when they truly cannot throw.
    Benefits: compiler can optimize more aggressively, enables STL move optimizations.
    If a noexcept function does throw: std::terminate() is called immediately.
    Mark: all hot-path functions, move constructors/assignments, destructors.

  TRADING USE CASE:
    // Hot path: error code (deterministic, zero overhead)
    enum class OrderError { OK, PRICE_ZERO, QTY_ZERO, EXCEED_LIMIT, SYMBOL_UNKNOWN };
    OrderError send_order(const Order& o) noexcept {
        if (o.price <= 0)    return OrderError::PRICE_ZERO;
        if (o.qty <= 0)      return OrderError::QTY_ZERO;
        // ... send ...
        return OrderError::OK;
    }

    // Off-path: exception OK (happens only at startup)
    void load_config(const std::string& path) {
        std::ifstream f(path);
        if (!f) throw std::runtime_error("Config not found: " + path);
    }

  COMMON MISTAKES:
    - Catching by value: catch(std::exception e) — slicing! Always catch by const ref
    - Using exceptions for expected conditions (no fill is not exceptional)
    - Forgetting noexcept on hot-path functions — prevents inlining opportunities
    - Relying on assert() in release builds — it's compiled out with -DNDEBUG
    - Letting an exception propagate from a destructor — undefined behavior
*/

#include <iostream>
#include <stdexcept>    // runtime_error, logic_error, invalid_argument, etc.
#include <string>
#include <cassert>      // assert()
#include <cstdint>
#include <cmath>        // std::abs
#include <optional>

// ============================================================
// TYPES
// ============================================================

struct Order {
    int64_t     price;    // ticks
    int32_t     qty;
    bool        is_buy;
    std::string symbol;
};

// ============================================================
// ERROR CODES — hot path pattern
// ============================================================

// Strongly-typed error enum — can't confuse with int
enum class OrderError {
    OK,
    PRICE_ZERO,
    QTY_ZERO,
    QTY_NEGATIVE,
    PRICE_NEGATIVE,
    EXCEEDS_POSITION_LIMIT,
    SYMBOL_UNKNOWN,
    KILL_SWITCH_ACTIVE,
};

// Convert error to string for logging (off-path, so can use string)
const char* to_string(OrderError e) {
    switch (e) {
        case OrderError::OK:                   return "OK";
        case OrderError::PRICE_ZERO:           return "PRICE_ZERO";
        case OrderError::QTY_ZERO:             return "QTY_ZERO";
        case OrderError::QTY_NEGATIVE:         return "QTY_NEGATIVE";
        case OrderError::PRICE_NEGATIVE:       return "PRICE_NEGATIVE";
        case OrderError::EXCEEDS_POSITION_LIMIT: return "EXCEEDS_POSITION_LIMIT";
        case OrderError::SYMBOL_UNKNOWN:       return "SYMBOL_UNKNOWN";
        case OrderError::KILL_SWITCH_ACTIVE:   return "KILL_SWITCH_ACTIVE";
    }
    return "UNKNOWN";
}

// Hot-path risk check: returns error code, marked noexcept
// noexcept: tells compiler this can never throw — enables better inlining + optimization
OrderError check_order(const Order& o, int32_t current_position, bool kill_switch) noexcept {
    if (kill_switch)          return OrderError::KILL_SWITCH_ACTIVE;
    if (o.price <= 0)         return OrderError::PRICE_NEGATIVE;
    if (o.qty == 0)           return OrderError::QTY_ZERO;
    if (o.qty < 0)            return OrderError::QTY_NEGATIVE;

    // Position limit check (simplified)
    constexpr int32_t MAX_POSITION = 1000;
    int32_t new_pos = current_position + (o.is_buy ? o.qty : -o.qty);
    if (std::abs(new_pos) > MAX_POSITION) return OrderError::EXCEEDS_POSITION_LIMIT;

    return OrderError::OK;
}

// ============================================================
// EXCEPTIONS — only for startup/config (off-path)
// ============================================================

// Custom exception class — always inherit from std::exception
class ConfigError : public std::runtime_error {
public:
    explicit ConfigError(const std::string& msg) : std::runtime_error(msg) {}
};

class ConnectionError : public std::runtime_error {
public:
    explicit ConnectionError(const std::string& host, int port)
        : std::runtime_error("Cannot connect to " + host + ":" + std::to_string(port)) {}
};

// Off-path startup function — exceptions are fine here
// Simulates loading a config with validation
struct TradingConfig {
    std::string exchange_host;
    int         port;
    int32_t     max_position;
    double      max_daily_loss;
};

TradingConfig load_config(const std::string& path) {
    // Simulate config parsing (in real code: read file, parse JSON/TOML)
    if (path.empty()) {
        throw std::invalid_argument("Config path cannot be empty");
    }
    if (path == "bad_config.toml") {
        throw ConfigError("Invalid config file format");
    }
    if (path == "missing.toml") {
        throw std::runtime_error("Config file not found: " + path);
    }
    return {"exchange.example.com", 9000, 1000, 50000.0};
}

// ============================================================
// ASSERT — invariants / programming bugs
// ============================================================

// This function assumes input is always valid (internal use only)
// assert() catches bugs in debug builds — compiled out in release (-DNDEBUG)
int64_t dollars_to_ticks(double price) {
    assert(price > 0.0 && "Price must be positive");   // programmer error, not user error
    assert(price < 1000000.0 && "Price suspiciously large");
    return static_cast<int64_t>(price * 10000);
}

// ============================================================
// NOEXCEPT — move operations and hot-path functions
// ============================================================

// Move operations should always be noexcept
// If vector needs to grow, it can move elements instead of copying
// ONLY if the move constructor is noexcept — otherwise vector copies for safety
struct MarketDataFrame {
    int64_t* data = nullptr;
    int      size = 0;

    MarketDataFrame() = default;

    explicit MarketDataFrame(int n) : data(new int64_t[n]), size(n) {}

    // noexcept move — vector will use this during reallocation (fast path)
    MarketDataFrame(MarketDataFrame&& other) noexcept
        : data(other.data), size(other.size)
    {
        other.data = nullptr;
        other.size = 0;
    }

    MarketDataFrame& operator=(MarketDataFrame&& other) noexcept {
        if (this != &other) {
            delete[] data;
            data = other.data; size = other.size;
            other.data = nullptr; other.size = 0;
        }
        return *this;
    }

    ~MarketDataFrame() { delete[] data; }

    // Copy is expensive — explicitly deleted to prevent accidental copies
    MarketDataFrame(const MarketDataFrame&)            = delete;
    MarketDataFrame& operator=(const MarketDataFrame&) = delete;
};

// ============================================================
// OPTIONAL AS ERROR SIGNAL (alternative to error codes)
// ============================================================

// When the "no result" case is not an error, just absence of a value:
// optional<T> is cleaner than returning -1 or having a bool output param.
std::optional<int64_t> parse_price_ticks(const std::string& s) noexcept {
    if (s.empty()) return std::nullopt;
    try {
        double price = std::stod(s);   // stod can throw — wrap it
        if (price <= 0) return std::nullopt;
        return static_cast<int64_t>(price * 10000);
    } catch (...) {
        return std::nullopt;   // invalid string — not an error, just no value
    }
}

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // ERROR CODES — hot path
    // -------------------------------------------------------

    std::cout << "=== Error codes (hot path pattern) ===\n";

    {
        int32_t position = 800;   // already long 800
        bool    kill_sw  = false;

        std::vector<Order> orders = {
            {1825000, 100, true,  "AAPL"},   // OK
            {0,        50, true,  "AAPL"},   // PRICE_NEGATIVE
            {1825000,   0, true,  "AAPL"},   // QTY_ZERO
            {1825000, 300, true,  "AAPL"},   // EXCEEDS_POSITION_LIMIT (800+300 > 1000)
        };

        for (const auto& o : orders) {
            OrderError err = check_order(o, position, kill_sw);
            if (err == OrderError::OK) {
                std::cout << "  Order accepted: $" << o.price / 10000.0 << " x" << o.qty << "\n";
                // update position...
            } else {
                std::cout << "  Order rejected: " << to_string(err) << "\n";
            }
        }

        // Kill switch test
        kill_sw = true;
        OrderError err = check_order(orders[0], position, kill_sw);
        std::cout << "  Kill switch: " << to_string(err) << "\n";
    }

    // -------------------------------------------------------
    // EXCEPTIONS — startup/config (off-path)
    // -------------------------------------------------------

    std::cout << "\n=== Exceptions (off-path: startup) ===\n";

    {
        // Loading config at startup: exceptions are fine
        auto try_load = [](const std::string& path) {
            try {
                auto cfg = load_config(path);
                std::cout << "  Config loaded: host=" << cfg.exchange_host
                          << " port=" << cfg.port << "\n";
            }
            catch (const ConfigError& e) {
                // Catch most specific type first
                std::cout << "  [ConfigError] " << e.what() << "\n";
            }
            catch (const std::invalid_argument& e) {
                std::cout << "  [InvalidArg] " << e.what() << "\n";
            }
            catch (const std::runtime_error& e) {
                // Catch base after specific — catches runtime_error and its derivatives
                std::cout << "  [RuntimeError] " << e.what() << "\n";
            }
            catch (...) {
                // Last resort: catch absolutely anything
                std::cout << "  [Unknown exception]\n";
            }
        };

        try_load("config.toml");     // success
        try_load("");               // invalid_argument
        try_load("bad_config.toml");// ConfigError
        try_load("missing.toml");   // runtime_error
    }

    // -------------------------------------------------------
    // CUSTOM EXCEPTION — rethrow + context
    // -------------------------------------------------------

    std::cout << "\n=== Exception chaining (rethrow with context) ===\n";

    {
        auto initialize_system = [&]() {
            try {
                // Simulate a dependency that throws
                throw ConnectionError("10.0.0.1", 4001);
            }
            catch (const ConnectionError& e) {
                // Add context and rethrow as a different type
                throw std::runtime_error(
                    std::string("System init failed: ") + e.what());
            }
        };

        try {
            initialize_system();
        }
        catch (const std::runtime_error& e) {
            std::cout << "  Init error: " << e.what() << "\n";
        }
    }

    // -------------------------------------------------------
    // ASSERT — invariant checking (debug builds)
    // -------------------------------------------------------

    std::cout << "\n=== assert() (debug-only invariants) ===\n";

    {
        // These are valid — assert passes silently
        int64_t t1 = dollars_to_ticks(182.50);
        int64_t t2 = dollars_to_ticks(0.0001);
        std::cout << "  $182.50 = " << t1 << " ticks\n";
        std::cout << "  $0.0001 = " << t2 << " ticks\n";

        // Uncommenting the line below would trigger assert in debug builds:
        // int64_t t3 = dollars_to_ticks(-1.0);  // assert(price > 0) fires

        // static_assert: compile-time — always checked, even in release
        static_assert(sizeof(int64_t) == 8, "int64_t must be 8 bytes for price math");
        static_assert(sizeof(double)  == 8, "double must be 8 bytes");
        std::cout << "  static_assert: int64_t and double are 8 bytes [compile-time check]\n";
    }

    // -------------------------------------------------------
    // NOEXCEPT — move optimization
    // -------------------------------------------------------

    std::cout << "\n=== noexcept (move optimization) ===\n";

    {
        // noexcept on move constructor allows vector to use move during reallocation
        std::cout << "  MarketDataFrame has noexcept move: "
                  << std::is_nothrow_move_constructible<MarketDataFrame>::value << "\n";

        std::vector<MarketDataFrame> frames;
        frames.reserve(3);
        frames.emplace_back(100);
        frames.emplace_back(200);
        frames.emplace_back(300);
        std::cout << "  " << frames.size() << " frames in vector (moved, not copied)\n";
    }

    // -------------------------------------------------------
    // OPTIONAL AS ERROR SIGNAL
    // -------------------------------------------------------

    std::cout << "\n=== optional as error signal ===\n";

    {
        std::vector<std::string> inputs = {"182.50", "", "bad", "-5.0", "183.25"};
        for (const auto& s : inputs) {
            auto ticks = parse_price_ticks(s);
            if (ticks) {
                std::cout << "  \"" << s << "\" → " << *ticks << " ticks\n";
            } else {
                std::cout << "  \"" << s << "\" → invalid/empty\n";
            }
        }
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      The two-tier error strategy used in production:

        // TIER 1: HOT PATH — error codes, noexcept, deterministic
        OrderError route(const Order& o) noexcept {
            auto err = risk_.check(o);       // returns error code in nanoseconds
            if (err != OrderError::OK) {
                logger_.log_reject(o, err);   // async logger — no blocking
                return err;
            }
            gateway_.send(o);                // sends over socket
            return OrderError::OK;
        }

        // TIER 2: COLD PATH — exceptions OK
        void startup() {
            try {
                config_  = load_config("prod.toml");    // throws on bad file
                gateway_ = connect(config_.host, config_.port);  // throws if unreachable
                risk_    = RiskManager(config_.limits);
                logger_  = AsyncLogger("trades.log");
            }
            catch (const std::exception& e) {
                std::cerr << "Startup failed: " << e.what() << "\n";
                std::exit(1);   // cannot trade — abort cleanly
            }
            // Once startup succeeds, exceptions never occur in the hot path
        }

        // RULE OF THUMB:
        //   Trading thread → error codes + noexcept
        //   I/O thread     → error codes (no latency impact)
        //   Startup        → exceptions OK
        //   Destructors    → NEVER throw (undefined behavior)
    */
}
