// ============================================================
// L62: Async Logger (Lock-Free)
// ============================================================
// WHAT: A trading system logger that logs without blocking the
//       hot path. A lock-free SPSC queue decouples the trading
//       thread (producer) from the disk writer (consumer). The
//       trading thread enqueues a log record in ~20ns; the
//       background thread flushes to disk when convenient.
// WHY (TRADING): std::cout or fprintf in the hot path can take
//   1-10µs (system call, formatting, flushing). That destroys
//   latency. Solution: the trading thread writes a compact record
//   to a lock-free queue (no syscall), and a background thread
//   writes to disk. Every order, fill, risk event, and state
//   change is logged without stalling the trading loop.
// PHASE: Trading Systems Implementation
// ============================================================

/*
  CONCEPT OVERVIEW:

  WHY LOGGING IS SLOW:
    - std::cout: mutex lock + format + write syscall + optional flush
    - fprintf: format + write syscall
    - spdlog: lock-free queue (fast path ~100ns), background flush
    - Our logger: memcpy to SPSC queue (~20ns hot path), async write

  LOG RECORD DESIGN:
    Fixed-size records (no heap allocation, no std::string):
    struct LogRecord {
        uint64_t ts_ns;    // rdtsc timestamp
        uint8_t  level;    // DEBUG/INFO/WARN/ERROR
        uint8_t  category; // FILL, ORDER, RISK, MARKET, SYS
        char     msg[246]; // message, null-terminated
    };  // 256 bytes = 4 cache lines

  SPSC QUEUE:
    Producer (trading thread): pushes records
    Consumer (logger thread):  pops records, formats, writes to file
    No locks, no condition variables — spin-polling consumer.

  LOG LEVELS:
    TRACE: every tick (disable in production, floods disk)
    DEBUG: order lifecycle events, fill details
    INFO:  strategy signals, risk checks
    WARN:  approaching position limits, unusual conditions
    ERROR: system errors, rejected orders
    FATAL: trigger kill switch, then log

  DISK WRITE STRATEGY:
    - Open file in O_APPEND | O_WRONLY mode
    - Write batches of records (reduce syscall frequency)
    - fsync() only on FATAL or shutdown (not per-record)

  COMMON MISTAKES:
    - Logging inside the hot path with a mutex → 1µs+ overhead
    - Formatting (sprintf) inside the hot path → 500ns overhead
    - SPSC queue overflow → silently dropped log records
      (add a dropped_count_ counter; alert if non-zero)
    - Calling fflush() after every write → serializes I/O
    - Storing std::string in the log record (heap allocation)
*/

#include <iostream>
#include <cstdint>
#include <cstring>
#include <atomic>
#include <thread>
#include <fstream>
#include <cstdio>
#include <ctime>
#include <chrono>
#include <cassert>
#include <string>
#include <array>

// ============================================================
// LOG LEVELS AND CATEGORIES
// ============================================================

enum class LogLevel : uint8_t {
    TRACE = 0,
    DEBUG = 1,
    INFO  = 2,
    WARN  = 3,
    ERROR = 4,
    FATAL = 5
};

enum class LogCategory : uint8_t {
    SYS     = 0,
    ORDER   = 1,
    FILL    = 2,
    RISK    = 3,
    MARKET  = 4,
    STRAT   = 5
};

const char* level_str(LogLevel l) {
    switch (l) {
        case LogLevel::TRACE: return "TRACE";
        case LogLevel::DEBUG: return "DEBUG";
        case LogLevel::INFO:  return "INFO ";
        case LogLevel::WARN:  return "WARN ";
        case LogLevel::ERROR: return "ERROR";
        case LogLevel::FATAL: return "FATAL";
    }
    return "?????";
}

// ============================================================
// LOG RECORD — fixed size, trivially copyable (no malloc)
// ============================================================

constexpr int LOG_MSG_SIZE = 246;

struct alignas(64) LogRecord {
    uint64_t    ts_ns;              // nanoseconds since epoch (from steady_clock)
    LogLevel    level;              // log level
    LogCategory category;           // subsystem
    uint16_t    strategy_id;        // 0 = system
    char        msg[LOG_MSG_SIZE];  // null-terminated message
    // Total: 8 + 1 + 1 + 2 + 246 = 258 bytes → pad to 4 cache lines (256 bytes)
    // The alignas(64) means the struct starts on a cache-line boundary
};
// Practical size — keeping the design clear matters more than exact 256B here

// ============================================================
// LOCK-FREE SPSC QUEUE (from L38)
// ============================================================

template<typename T, int N>
class SPSCQueue {
    static_assert((N & (N-1)) == 0, "N must be power of 2");
    alignas(64) std::atomic<uint64_t> head_{0};
    alignas(64) std::atomic<uint64_t> tail_{0};
    T buf_[N]{};

public:
    bool push(const T& item) noexcept {
        uint64_t h = head_.load(std::memory_order_relaxed);
        if (h - tail_.load(std::memory_order_acquire) >= N) return false;
        buf_[h & (N-1)] = item;
        head_.store(h + 1, std::memory_order_release);
        return true;
    }

    bool pop(T& item) noexcept {
        uint64_t t = tail_.load(std::memory_order_relaxed);
        if (head_.load(std::memory_order_acquire) == t) return false;
        item = buf_[t & (N-1)];
        tail_.store(t + 1, std::memory_order_release);
        return true;
    }
};

// ============================================================
// ASYNC LOGGER
// ============================================================

class AsyncLogger {
public:
    static constexpr int QUEUE_SIZE = 4096;   // must be power of 2

    explicit AsyncLogger(const std::string& filename, LogLevel min_level = LogLevel::DEBUG)
        : min_level_(min_level)
        , running_(false)
        , dropped_(0)
    {
        file_ = fopen(filename.c_str(), "a");  // append mode
        if (!file_) {
            std::cerr << "[Logger] Failed to open " << filename << "\n";
        }
    }

    ~AsyncLogger() {
        stop();
        if (file_) fclose(file_);
    }

    // Start the background consumer thread
    void start() {
        running_.store(true, std::memory_order_release);
        thread_ = std::thread([this]() { consume_loop(); });
    }

    // Stop: drain the queue, then join the thread
    void stop() {
        if (!running_.load(std::memory_order_acquire)) return;
        running_.store(false, std::memory_order_release);
        if (thread_.joinable()) thread_.join();
        flush_to_disk();  // final drain
    }

    // ── HOT PATH: called from the trading thread ─────────────

    // Log with printf-style formatting.
    // This runs on the trading thread — must be fast.
    // Worst case: one snprintf + one memcpy to the queue.
    template<typename... Args>
    void log(LogLevel level, LogCategory cat, uint16_t strat_id,
             const char* fmt, Args... args) noexcept {
        if (level < min_level_) return;  // filter before formatting

        LogRecord rec{};
        rec.ts_ns       = now_ns();
        rec.level       = level;
        rec.category    = cat;
        rec.strategy_id = strat_id;

        // Format message into the record's buffer — no heap allocation
        snprintf(rec.msg, LOG_MSG_SIZE, fmt, args...);

        if (!queue_.push(rec)) {
            ++dropped_;  // queue full — log record dropped
        }
    }

    // Shortcut macros for common cases
    void info (const char* msg, uint16_t strat = 0) {
        log(LogLevel::INFO,  LogCategory::SYS,   strat, "%s", msg);
    }
    void warn (const char* msg, uint16_t strat = 0) {
        log(LogLevel::WARN,  LogCategory::SYS,   strat, "%s", msg);
    }
    void error(const char* msg, uint16_t strat = 0) {
        log(LogLevel::ERROR, LogCategory::SYS,   strat, "%s", msg);
    }

    uint64_t dropped() const { return dropped_.load(std::memory_order_relaxed); }

private:
    FILE*               file_;
    LogLevel            min_level_;
    std::atomic<bool>   running_;
    std::atomic<uint64_t> dropped_;
    std::thread         thread_;
    SPSCQueue<LogRecord, QUEUE_SIZE> queue_;

    // Flush buffer — accumulate records here before writing to disk
    static constexpr int FLUSH_BUF = 16384;
    char flush_buf_[FLUSH_BUF];
    int  flush_pos_ = 0;

    uint64_t now_ns() const {
        return static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::steady_clock::now().time_since_epoch()).count());
    }

    // Consumer loop — runs on the background thread
    void consume_loop() {
        LogRecord rec;
        while (running_.load(std::memory_order_relaxed)) {
            if (queue_.pop(rec)) {
                format_and_buffer(rec);
            } else {
                // Queue empty — flush pending writes to disk
                flush_to_disk();
                // Yield briefly to avoid burning 100% CPU in logger thread
                // In production: use condition_variable for slow-path wakeup
                std::this_thread::yield();
            }
        }
    }

    // Format one record into the flush buffer
    void format_and_buffer(const LogRecord& rec) {
        // Convert nanoseconds to HH:MM:SS.nnnnnnnnn
        time_t secs = static_cast<time_t>(rec.ts_ns / 1000000000ULL);
        uint64_t nanos = rec.ts_ns % 1000000000ULL;

        struct tm t{};
#if defined(_MSC_VER) || defined(_WIN32)
        gmtime_s(&t, &secs);
#else
        gmtime_r(&secs, &t);
#endif

        char line[512];
        int len = snprintf(line, sizeof(line),
            "%02d:%02d:%02d.%09llu [%s] [%s] strat=%u | %s\n",
            t.tm_hour, t.tm_min, t.tm_sec, (unsigned long long)nanos,
            level_str(rec.level),
            cat_str(rec.category),
            rec.strategy_id,
            rec.msg
        );

        if (flush_pos_ + len < FLUSH_BUF) {
            memcpy(flush_buf_ + flush_pos_, line, len);
            flush_pos_ += len;
        } else {
            flush_to_disk();
            memcpy(flush_buf_, line, len);
            flush_pos_ = len;
        }
    }

    void flush_to_disk() {
        if (flush_pos_ > 0 && file_) {
            fwrite(flush_buf_, 1, flush_pos_, file_);
            flush_pos_ = 0;
            // Note: NOT calling fflush() here — batches writes for throughput
            // Call fflush(file_) only on FATAL or shutdown
        }
    }

    const char* cat_str(LogCategory c) const {
        switch (c) {
            case LogCategory::SYS:    return "SYS   ";
            case LogCategory::ORDER:  return "ORDER ";
            case LogCategory::FILL:   return "FILL  ";
            case LogCategory::RISK:   return "RISK  ";
            case LogCategory::MARKET: return "MARKET";
            case LogCategory::STRAT:  return "STRAT ";
        }
        return "?     ";
    }
};

// ============================================================
// GLOBAL LOGGER (singleton pattern for easy access across modules)
// ============================================================

static AsyncLogger* g_logger = nullptr;

// Convenience macros — zero overhead when level is filtered
#define LOG_INFO(cat, strat, fmt, ...) \
    if (g_logger) g_logger->log(LogLevel::INFO, LogCategory::cat, strat, fmt, ##__VA_ARGS__)
#define LOG_WARN(cat, strat, fmt, ...) \
    if (g_logger) g_logger->log(LogLevel::WARN, LogCategory::cat, strat, fmt, ##__VA_ARGS__)
#define LOG_ERROR(cat, strat, fmt, ...) \
    if (g_logger) g_logger->log(LogLevel::ERROR, LogCategory::cat, strat, fmt, ##__VA_ARGS__)
#define LOG_FILL(strat, price, qty, sym) \
    if (g_logger) g_logger->log(LogLevel::INFO, LogCategory::FILL, strat, \
                                 "FILL %s qty=%d px=%.4f", sym, qty, price)

// ============================================================
// MAIN
// ============================================================

int main() {
    std::cout << "=== Async Logger ===\n";
    std::cout << "  LogRecord size: " << sizeof(LogRecord) << " bytes\n";

    // -------------------------------------------------------
    // START LOGGER
    // -------------------------------------------------------

    // Write to stdout as well for demo (in production: use a real log file)
    AsyncLogger logger("trading_log.txt", LogLevel::DEBUG);
    g_logger = &logger;
    logger.start();

    // -------------------------------------------------------
    // LOG VARIOUS EVENTS (from the "trading thread")
    // -------------------------------------------------------

    std::cout << "\n--- Logging events ---\n";

    LOG_INFO(SYS,   0,   "Trading system starting up");
    LOG_INFO(ORDER, 1,   "New order: BUY 100 SPY @ 182.50");
    LOG_FILL(1, 182.50, 100, "SPY");
    LOG_WARN(RISK,  0,   "Position approaching limit: SPY %d / 500", 450);
    LOG_ERROR(SYS,  0,   "Connection to exchange dropped");
    LOG_INFO(STRAT, 2,   "Signal: momentum triggered, price=%.2f sma=%.2f", 183.0, 182.5);

    // -------------------------------------------------------
    // HOT PATH LATENCY TEST
    // -------------------------------------------------------

    std::cout << "\n=== Hot-path log latency ===\n";

    constexpr int REPS = 1000000;
    auto t0 = std::chrono::steady_clock::now();

    for (int i = 0; i < REPS; ++i) {
        // This is what the trading thread calls on the hot path
        logger.log(LogLevel::DEBUG, LogCategory::MARKET, 1,
                   "tick #%d bid=%.4f ask=%.4f", i, 182.50 + i*0.0001, 182.51 + i*0.0001);
    }

    auto t1 = std::chrono::steady_clock::now();

    uint64_t ns = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());

    std::cout << "  " << REPS << " log calls in " << ns / 1000 << "µs\n";
    std::cout << "  Per log call: " << ns / REPS << "ns (on trading thread)\n";
    std::cout << "  Dropped (queue full): " << logger.dropped() << "\n";
    std::cout << "  (queue full = QUEUE_SIZE=" << AsyncLogger::QUEUE_SIZE
              << " records. Increase or drain faster if drops occur.)\n";

    // -------------------------------------------------------
    // STOP
    // -------------------------------------------------------

    std::cout << "\n--- Stopping logger ---\n";
    logger.stop();
    g_logger = nullptr;

    std::cout << "  Logger stopped. Log written to trading_log.txt\n";
    std::cout << "  Total dropped: " << logger.dropped() << "\n";

    // Show first few lines of the log
    std::cout << "\n--- First lines of trading_log.txt ---\n";
    std::ifstream logfile("trading_log.txt");
    std::string line;
    int lines = 0;
    while (std::getline(logfile, line) && lines < 8) {
        std::cout << "  " << line << "\n";
        ++lines;
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Every significant event in the trading lifecycle is logged:
        on_market_data → LOG(TRACE, MARKET, strat, "bid=%.4f ask=%.4f", ...)
        on_order_submit → LOG(INFO, ORDER, strat, "NEW %s %d@%.4f id=%lu", ...)
        on_ack          → LOG(INFO, ORDER, strat, "ACK id=%lu exchg=%lu", ...)
        on_fill         → LOG(INFO, FILL, strat, "FILL %d@%.4f cum=%d", ...)
        on_reject       → LOG(WARN, ORDER, strat, "REJECT id=%lu reason=%s", ...)
        on_risk_breach  → LOG(ERROR, RISK, strat, "LIMIT %s pos=%d max=%d", ...)

      End of day: concatenate log files, grep for FILL to get trade blotter,
      grep for ERROR/WARN for post-trade review.

      Log file rotation: at midnight, rename trading_log.txt to trading_log_YYYYMMDD.txt.
      Keep 30 days of logs. Compress old logs with zstd for storage efficiency.
    */
}
