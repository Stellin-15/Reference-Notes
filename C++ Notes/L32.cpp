// ============================================================
// L32: File I/O and Serialization
// ============================================================
// WHAT: Reading and writing files with <fstream>: text and
//       binary modes, seeking, and memory-mapped files.
// WHY (TRADING): Every trading system needs file I/O for:
//   - Trade logs (every fill, rejection, and risk event)
//   - Config loading at startup (symbols, risk limits, params)
//   - Market data replay (reading tick files for backtesting)
//   - Binary serialization (writing order books to disk fast)
//   Binary I/O is critical: writing 1M ticks as binary is ~10x
//   faster than writing them as text because no formatting cost.
// PHASE: Modern C++
// ============================================================

/*
  CONCEPT OVERVIEW:

  TEXT vs BINARY MODE:
    Text mode:   numbers stored as strings ("182.50\n") — human readable, slow
    Binary mode: numbers stored as raw bytes (8 bytes for double) — fast, compact
    Open with std::ios::binary to get binary mode.
    Rule: logs are text (grep-able); market data files are binary (fast replay).

  FSTREAM CLASSES:
    std::ifstream  — read from file (input)
    std::ofstream  — write to file (output)
    std::fstream   — read and write
    Open modes (combine with |):
      std::ios::in     — read
      std::ios::out    — write (truncates existing file)
      std::ios::app    — append (don't truncate)
      std::ios::binary — binary mode
      std::ios::trunc  — explicitly truncate on open
      std::ios::ate    — start at end of file

  CHECKING SUCCESS:
    if (!file) { ... }          — stream is in bad state (failed to open, etc.)
    file.good()                 — true if all OK
    file.fail()                 — true if last operation failed
    file.eof()                  — true if end of file
    file.is_open()              — true if currently open
    Always check after open AND after each critical read.

  POSITIONING (SEEK):
    file.seekg(offset, whence)  — seek read head (g = get)
    file.seekp(offset, whence)  — seek write head (p = put)
    file.tellg()                — current read position (returns std::streampos)
    file.tellp()                — current write position
    whence:
      std::ios::beg  — from beginning
      std::ios::cur  — from current position
      std::ios::end  — from end of file

  BINARY READ/WRITE:
    file.write(reinterpret_cast<const char*>(&val), sizeof(val))  — write T as raw bytes
    file.read (reinterpret_cast<char*>(&val),       sizeof(val))  — read raw bytes into T

  MEMORY-MAPPED FILES (mmap — Linux):
    OS maps the file into virtual address space.
    Reading: just read from the pointer — OS fetches pages lazily.
    Writing: write to the pointer — OS flushes to disk (msync or on close).
    LATENCY: For hot-path tick replay, mmap avoids read() syscall overhead.
    On Windows: CreateFileMapping / MapViewOfFile (similar concept).
    For cross-platform code: use a simple binary file with ifstream.

  TRADING USE CASE:
    // Write trade log (text, append mode):
    std::ofstream log("trades.csv", std::ios::app);
    log << timestamp_ns << "," << symbol << "," << price << "\n";

    // Write tick data (binary):
    std::ofstream ticks("data.bin", std::ios::binary);
    for (const Tick& t : buffer) {
        ticks.write(reinterpret_cast<const char*>(&t), sizeof(Tick));
    }

    // Read tick data (binary replay):
    Tick t;
    while (file.read(reinterpret_cast<char*>(&t), sizeof(Tick))) {
        strategy.on_tick(t);
    }

  COMMON MISTAKES:
    - Not checking if the file opened successfully before reading/writing
    - Forgetting std::ios::binary — text mode inserts \r\n on Windows, corrupts binary data
    - Using float/double in binary serialization that must be read on different hardware
      (same endianness, same sizeof — usually fine on x86, but verify)
    - Reading structs with pointers from disk — the pointers are meaningless after reload
    - Flushing every line with endl — use "\n" and flush explicitly when needed
    - Opening a log with ios::out and forgetting ios::app — you'll truncate your log!
*/

#include <iostream>
#include <fstream>
#include <sstream>      // std::ostringstream for in-memory formatting
#include <string>
#include <vector>
#include <cstdint>
#include <cstring>      // memset
#include <chrono>       // for fake timestamps

// ============================================================
// TYPES
// ============================================================

// POD (Plain Old Data) struct — safe to binary serialize
// All fields are fixed-width, no pointers, no virtual functions
struct Tick {
    uint64_t timestamp_ns;
    int64_t  bid_price;     // ticks (int64 * 10000 = cents * 100)
    int64_t  ask_price;
    int32_t  bid_qty;
    int32_t  ask_qty;
    char     symbol[8];     // fixed-size char array (NOT std::string — no pointer)
};

// Fill record for trade log
struct Fill {
    uint64_t timestamp_ns;
    int64_t  price;         // ticks
    int32_t  qty;
    bool     is_buy;
    char     symbol[8];
    uint64_t order_id;
};

// ============================================================
// TRADE LOG — text append, CSV format
// ============================================================

class TradeLog {
public:
    explicit TradeLog(const std::string& path) {
        // ios::app — append to existing file, don't truncate
        file_.open(path, std::ios::out | std::ios::app);
        if (!file_) {
            throw std::runtime_error("Cannot open trade log: " + path);
        }
        // Write header only if file was just created (file is at position 0)
        if (file_.tellp() == std::streampos(0)) {
            file_ << "timestamp_ns,symbol,price,qty,side,order_id\n";
        }
    }

    void record(const Fill& f) {
        // Use "\n" not std::endl — endl flushes, which is slow in the hot path
        file_ << f.timestamp_ns  << ","
              << f.symbol        << ","
              << f.price / 10000.0 << ","
              << f.qty           << ","
              << (f.is_buy ? "BUY" : "SELL") << ","
              << f.order_id      << "\n";
    }

    // Explicit flush when we want to guarantee disk write
    void flush() { file_.flush(); }

    ~TradeLog() {
        if (file_.is_open()) {
            file_.flush();
            file_.close();
        }
    }

private:
    std::ofstream file_;
};

// ============================================================
// BINARY TICK FILE — write and read back
// ============================================================

class TickFileWriter {
public:
    explicit TickFileWriter(const std::string& path) {
        // ios::binary — raw bytes, no newline translation
        // ios::trunc  — start fresh each time
        file_.open(path, std::ios::out | std::ios::binary | std::ios::trunc);
        if (!file_) {
            throw std::runtime_error("Cannot open tick file for writing: " + path);
        }
    }

    void write(const Tick& t) {
        // reinterpret_cast<const char*>(&t) — treat the struct as a byte array
        file_.write(reinterpret_cast<const char*>(&t), sizeof(Tick));
        ++written_;
    }

    void write_batch(const std::vector<Tick>& ticks) {
        if (ticks.empty()) return;
        // Write entire vector as contiguous bytes — single syscall
        file_.write(reinterpret_cast<const char*>(ticks.data()),
                    static_cast<std::streamsize>(ticks.size() * sizeof(Tick)));
        written_ += static_cast<int>(ticks.size());
    }

    int ticks_written() const { return written_; }

    ~TickFileWriter() {
        if (file_.is_open()) file_.close();
    }

private:
    std::ofstream file_;
    int           written_ = 0;
};

class TickFileReader {
public:
    explicit TickFileReader(const std::string& path) {
        file_.open(path, std::ios::in | std::ios::binary);
        if (!file_) {
            throw std::runtime_error("Cannot open tick file: " + path);
        }
        // Determine file size using seek
        file_.seekg(0, std::ios::end);
        auto file_size = file_.tellg();
        file_.seekg(0, std::ios::beg);
        tick_count_ = static_cast<int>(file_size / sizeof(Tick));
    }

    bool read_next(Tick& t) {
        return static_cast<bool>(
            file_.read(reinterpret_cast<char*>(&t), sizeof(Tick)));
    }

    // Read all ticks into a vector at once
    std::vector<Tick> read_all() {
        file_.seekg(0, std::ios::beg);
        std::vector<Tick> ticks(tick_count_);
        file_.read(reinterpret_cast<char*>(ticks.data()),
                   static_cast<std::streamsize>(tick_count_ * sizeof(Tick)));
        return ticks;
    }

    int tick_count() const { return tick_count_; }

private:
    std::ifstream file_;
    int           tick_count_ = 0;
};

// ============================================================
// CONFIG READER — text file, key=value format
// ============================================================

struct Config {
    std::string exchange_host;
    int         port         = 9000;
    int32_t     max_position = 1000;
    double      max_loss     = 50000.0;
};

Config read_config(const std::string& path) {
    std::ifstream file(path);
    if (!file) {
        throw std::runtime_error("Config file not found: " + path);
    }

    Config cfg;
    std::string line;
    while (std::getline(file, line)) {
        if (line.empty() || line[0] == '#') continue;  // skip comments and blanks

        auto eq = line.find('=');
        if (eq == std::string::npos) continue;

        std::string key   = line.substr(0, eq);
        std::string value = line.substr(eq + 1);

        if (key == "exchange_host") { cfg.exchange_host = value; }
        else if (key == "port")     { cfg.port = std::stoi(value); }
        else if (key == "max_position") { cfg.max_position = std::stoi(value); }
        else if (key == "max_loss")     { cfg.max_loss = std::stod(value); }
    }
    return cfg;
}

// ============================================================
// MAIN
// ============================================================

int main() {

    const std::string temp_dir = ""; // write to current directory for demo

    // -------------------------------------------------------
    // TEXT FILE — trade log
    // -------------------------------------------------------

    std::cout << "=== Text file: trade log ===\n";

    {
        const std::string log_path = "trades_demo.csv";
        try {
            TradeLog log(log_path);

            Fill fills[] = {
                {1000000000ULL, 1825500, 100, true,  "AAPL\0\0\0", 1001},
                {1000000100ULL, 1825500,  50, false, "AAPL\0\0\0", 1002},
                {1000000200ULL, 1826000,  75, false, "AAPL\0\0\0", 1003},
            };

            for (const auto& f : fills) {
                log.record(f);
                std::cout << "  Logged fill: " << f.symbol
                          << " $" << f.price / 10000.0 << "\n";
            }
            log.flush();
            std::cout << "  Trade log written: " << log_path << "\n";
        }
        catch (const std::exception& e) {
            std::cout << "  [Log error] " << e.what() << "\n";
        }
    }

    // -------------------------------------------------------
    // BINARY FILE — tick data
    // -------------------------------------------------------

    std::cout << "\n=== Binary file: tick data ===\n";

    {
        const std::string tick_path = "ticks_demo.bin";

        // Write ticks
        {
            TickFileWriter writer(tick_path);

            std::vector<Tick> batch;
            for (int i = 0; i < 5; ++i) {
                Tick t{};
                t.timestamp_ns = 1000000000ULL + i * 100;
                t.bid_price    = 1825000 + i * 100;
                t.ask_price    = 1825100 + i * 100;
                t.bid_qty      = 200;
                t.ask_qty      = 150;
                std::memset(t.symbol, 0, sizeof(t.symbol));
                std::memcpy(t.symbol, "AAPL", 4);
                batch.push_back(t);
            }
            writer.write_batch(batch);
            std::cout << "  Wrote " << writer.ticks_written() << " ticks to " << tick_path
                      << " (" << writer.ticks_written() * sizeof(Tick) << " bytes)\n";
        }

        // Read back
        {
            TickFileReader reader(tick_path);
            std::cout << "  File contains " << reader.tick_count() << " ticks\n";

            auto ticks = reader.read_all();
            std::cout << "  Replaying:\n";
            for (const auto& t : ticks) {
                std::cout << "    ts=" << t.timestamp_ns
                          << " bid=$" << t.bid_price / 10000.0
                          << " ask=$" << t.ask_price / 10000.0 << "\n";
            }
        }
    }

    // -------------------------------------------------------
    // TEXT FILE — config read
    // -------------------------------------------------------

    std::cout << "\n=== Text file: config ===\n";

    {
        // Write a sample config file
        const std::string cfg_path = "trading_demo.conf";
        {
            std::ofstream f(cfg_path);
            f << "# Trading system config\n"
              << "exchange_host=10.0.0.1\n"
              << "port=4001\n"
              << "max_position=500\n"
              << "max_loss=25000.0\n";
        }

        try {
            Config cfg = read_config(cfg_path);
            std::cout << "  exchange_host: " << cfg.exchange_host << "\n";
            std::cout << "  port:          " << cfg.port << "\n";
            std::cout << "  max_position:  " << cfg.max_position << "\n";
            std::cout << "  max_loss:      $" << cfg.max_loss << "\n";
        }
        catch (const std::exception& e) {
            std::cout << "  Config error: " << e.what() << "\n";
        }
    }

    // -------------------------------------------------------
    // SEEK — jump to specific tick in binary file
    // -------------------------------------------------------

    std::cout << "\n=== Seeking in binary file ===\n";

    {
        const std::string tick_path = "ticks_demo.bin";
        std::ifstream file(tick_path, std::ios::in | std::ios::binary);
        if (file) {
            // Jump directly to tick #3 (0-indexed)
            int target_tick = 3;
            file.seekg(target_tick * sizeof(Tick), std::ios::beg);

            Tick t{};
            if (file.read(reinterpret_cast<char*>(&t), sizeof(Tick))) {
                std::cout << "  Tick #" << target_tick
                          << ": ts=" << t.timestamp_ns
                          << " bid=$" << t.bid_price / 10000.0 << "\n";
            }

            // Get file size via seek to end
            file.seekg(0, std::ios::end);
            std::streampos file_size = file.tellg();
            std::cout << "  File size: " << static_cast<int64_t>(file_size)
                      << " bytes (" << static_cast<int64_t>(file_size) / sizeof(Tick)
                      << " ticks)\n";
        }
    }

    // -------------------------------------------------------
    // IN-MEMORY FORMATTING: ostringstream
    // -------------------------------------------------------

    std::cout << "\n=== ostringstream: build string before writing ===\n";

    {
        // When you want to format a string without writing to disk yet
        // (e.g., to send over the network or pass to a logger queue)
        std::ostringstream oss;
        oss << "FIX|35=D|49=CLIENT|56=EXCHANGE|"
            << "55=AAPL|38=100|44=182.50|54=1|";
        std::string fix_msg = oss.str();
        std::cout << "  FIX message: " << fix_msg << "\n";
        std::cout << "  Length: " << fix_msg.size() << " bytes\n";
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Binary tick replay for backtesting — reads at memory bus speed:

        // At startup: memory-map the entire tick file
        // (on Linux; Windows uses MapViewOfFile)
        int fd = open("market_data_2024.bin", O_RDONLY);
        fstat(fd, &sb);
        const Tick* ticks = static_cast<const Tick*>(
            mmap(nullptr, sb.st_size, PROT_READ, MAP_SHARED, fd, 0));
        int tick_count = sb.st_size / sizeof(Tick);

        // Replay: no syscalls per tick — OS handles paging automatically
        for (int i = 0; i < tick_count; ++i) {
            strategy.on_tick(ticks[i]);   // reads directly from mapped memory
        }

        munmap((void*)ticks, sb.st_size);
        close(fd);

        // RESULT: replaying 1 billion ticks ≈ 30 seconds
        //         vs fstream read loop:       ≈ 4 minutes

        // For Windows cross-platform use, stick with std::fstream binary
        // and call read_all() at startup — load into RAM once, replay from vector.
    */
}
