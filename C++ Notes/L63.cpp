// ============================================================
// L63: Configuration System
// ============================================================
// WHAT: A configuration system that loads all trading parameters
//       at startup from a key=value config file. Parameters include
//       exchange connectivity, risk limits, strategy settings,
//       and system tuning. Config is immutable during trading —
//       never read from disk in the hot path.
// WHY (TRADING): Hard-coding parameters means a code recompile for
//   every tuning change. A config file lets you change risk limits,
//   strategy parameters, and exchange connections without touching
//   source code. Config is loaded ONCE at startup and cached in a
//   struct — zero runtime cost to read any parameter.
// PHASE: Trading Systems Implementation
// ============================================================

/*
  CONCEPT OVERVIEW:

  DESIGN PRINCIPLES:
    1. Load once at startup, never at runtime (no fopen() in the hot path)
    2. Validate all values at load time — fail fast with a clear error message
    3. Provide typed accessors (get_int, get_double, get_string, get_bool)
    4. Support defaults: if a key is missing, use the default value
    5. Support sections: [risk], [strategy.momentum], [exchange.nyse]
    6. Fail loudly for required parameters: throw if missing with no default

  CONFIG FILE FORMAT (key=value, # comments, [sections]):
    # Trading System Configuration
    [system]
    log_level = INFO
    log_file = trading_log.txt
    dry_run = false

    [exchange]
    host = 10.0.0.1
    port = 9000
    sender_comp_id = ALGO_TRADER
    target_comp_id = NYSE

    [risk]
    max_order_qty = 500
    max_position = 5000
    max_daily_loss_usd = 50000
    fat_finger_pct = 2.0

    [strategy.momentum]
    enabled = true
    sma_period = 20
    entry_threshold_ticks = 5
    order_qty = 100
    symbols = SPY,QQQ,AAPL

  LIVE RELOAD (SIGHUP):
    In production: send SIGHUP to reload config without restarting.
    Only the slow path (risk limits, logging level) can be reloaded.
    Never reload hot-path parameters like buffer sizes or thread affinity.

  COMMON MISTAKES:
    - Reading config file inside the trading loop (extremely slow)
    - No type validation (accepting "abc" for an integer field)
    - No range validation (accepting max_position = -999999)
    - Hard-coding magic numbers anywhere in trading code
    - Using config values that depend on each other without validating consistency
    - Storing secrets (API keys, passwords) in config files (use env vars or vault)
*/

#include <iostream>
#include <fstream>
#include <string>
#include <unordered_map>
#include <stdexcept>
#include <sstream>
#include <vector>
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <optional>

// ============================================================
// CONFIG PARSER — reads key=value pairs, supports [sections]
// ============================================================

class Config {
public:
    // Load from file. Throws std::runtime_error on file-not-found.
    static Config from_file(const std::string& path) {
        Config cfg;
        std::ifstream f(path);
        if (!f.is_open())
            throw std::runtime_error("Config: cannot open file: " + path);
        cfg.parse(f);
        return cfg;
    }

    // Load from a string (useful for testing)
    static Config from_string(const std::string& content) {
        Config cfg;
        std::istringstream ss(content);
        cfg.parse(ss);
        return cfg;
    }

    // ── TYPED ACCESSORS ──────────────────────────────────────

    // Get a required string value — throws if key is missing
    std::string get_string(const std::string& key) const {
        auto it = data_.find(key);
        if (it == data_.end())
            throw std::runtime_error("Config: required key missing: " + key);
        return it->second;
    }

    // Get optional string, returns default if missing
    std::string get_string(const std::string& key, const std::string& def) const {
        auto it = data_.find(key);
        return (it != data_.end()) ? it->second : def;
    }

    // Get required integer
    int64_t get_int(const std::string& key) const {
        return parse_int(key, get_string(key));
    }

    int64_t get_int(const std::string& key, int64_t def) const {
        auto it = data_.find(key);
        if (it == data_.end()) return def;
        return parse_int(key, it->second);
    }

    // Get required double
    double get_double(const std::string& key) const {
        return parse_double(key, get_string(key));
    }

    double get_double(const std::string& key, double def) const {
        auto it = data_.find(key);
        if (it == data_.end()) return def;
        return parse_double(key, it->second);
    }

    // Get required bool (true/false, yes/no, 1/0)
    bool get_bool(const std::string& key) const {
        return parse_bool(key, get_string(key));
    }

    bool get_bool(const std::string& key, bool def) const {
        auto it = data_.find(key);
        if (it == data_.end()) return def;
        return parse_bool(key, it->second);
    }

    // Get comma-separated list of strings
    std::vector<std::string> get_list(const std::string& key) const {
        auto it = data_.find(key);
        if (it == data_.end()) return {};
        return split(it->second, ',');
    }

    // Check if a key exists
    bool has(const std::string& key) const {
        return data_.count(key) > 0;
    }

    // Dump all key-value pairs (for debugging)
    void print() const {
        std::cout << "  === Config (" << data_.size() << " keys) ===\n";
        for (auto& [k, v] : data_)
            std::cout << "  " << k << " = " << v << "\n";
    }

private:
    std::unordered_map<std::string, std::string> data_;

    void parse(std::istream& stream) {
        std::string line;
        std::string current_section;

        while (std::getline(stream, line)) {
            // Strip comment (# to end of line)
            auto comment = line.find('#');
            if (comment != std::string::npos) line = line.substr(0, comment);

            // Trim whitespace
            line = trim(line);
            if (line.empty()) continue;

            // Section header: [section_name]
            if (line.front() == '[' && line.back() == ']') {
                current_section = line.substr(1, line.size() - 2);
                current_section = trim(current_section);
                continue;
            }

            // Key=value pair
            auto eq = line.find('=');
            if (eq == std::string::npos) continue;

            std::string key = trim(line.substr(0, eq));
            std::string val = trim(line.substr(eq + 1));

            // Prefix key with section: "risk.max_order_qty"
            std::string full_key = current_section.empty() ? key : current_section + "." + key;
            data_[full_key] = val;
        }
    }

    static std::string trim(const std::string& s) {
        size_t start = s.find_first_not_of(" \t\r\n");
        if (start == std::string::npos) return "";
        size_t end = s.find_last_not_of(" \t\r\n");
        return s.substr(start, end - start + 1);
    }

    static std::vector<std::string> split(const std::string& s, char delim) {
        std::vector<std::string> result;
        std::istringstream ss(s);
        std::string token;
        while (std::getline(ss, token, delim)) {
            std::string trimmed = trim(token);
            if (!trimmed.empty()) result.push_back(trimmed);
        }
        return result;
    }

    static int64_t parse_int(const std::string& key, const std::string& val) {
        try { return std::stoll(val); }
        catch (...) { throw std::runtime_error("Config: invalid integer for key '" + key + "': " + val); }
    }

    static double parse_double(const std::string& key, const std::string& val) {
        try { return std::stod(val); }
        catch (...) { throw std::runtime_error("Config: invalid double for key '" + key + "': " + val); }
    }

    static bool parse_bool(const std::string& key, const std::string& val) {
        if (val == "true"  || val == "yes" || val == "1") return true;
        if (val == "false" || val == "no"  || val == "0") return false;
        throw std::runtime_error("Config: invalid bool for key '" + key + "': " + val);
    }
};

// ============================================================
// TYPED CONFIG STRUCTS — loaded once, used everywhere
// ============================================================

struct SystemConfig {
    std::string log_level;
    std::string log_file;
    bool        dry_run;

    static SystemConfig from_config(const Config& c) {
        SystemConfig s;
        s.log_level = c.get_string("system.log_level", "INFO");
        s.log_file  = c.get_string("system.log_file",  "trading_log.txt");
        s.dry_run   = c.get_bool("system.dry_run", false);
        return s;
    }
};

struct ExchangeConfig {
    std::string host;
    int         port;
    std::string sender_comp_id;
    std::string target_comp_id;

    static ExchangeConfig from_config(const Config& c) {
        ExchangeConfig e;
        e.host            = c.get_string("exchange.host");
        e.port            = static_cast<int>(c.get_int("exchange.port"));
        e.sender_comp_id  = c.get_string("exchange.sender_comp_id");
        e.target_comp_id  = c.get_string("exchange.target_comp_id");
        return e;
    }
};

struct RiskConfig {
    int32_t max_order_qty;
    int32_t max_position;
    double  max_daily_loss_usd;
    double  fat_finger_pct;

    static RiskConfig from_config(const Config& c) {
        RiskConfig r;
        r.max_order_qty     = static_cast<int32_t>(c.get_int("risk.max_order_qty", 500));
        r.max_position      = static_cast<int32_t>(c.get_int("risk.max_position", 5000));
        r.max_daily_loss_usd= c.get_double("risk.max_daily_loss_usd", 50000.0);
        r.fat_finger_pct    = c.get_double("risk.fat_finger_pct", 2.0) / 100.0;

        // Validate
        if (r.max_order_qty <= 0 || r.max_order_qty > 10000)
            throw std::runtime_error("Config: max_order_qty out of range [1, 10000]");
        if (r.max_daily_loss_usd < 0)
            throw std::runtime_error("Config: max_daily_loss_usd must be positive");

        return r;
    }
};

struct StrategyConfig {
    bool                     enabled;
    int                      sma_period;
    int                      entry_threshold_ticks;
    int                      order_qty;
    std::vector<std::string> symbols;

    static StrategyConfig from_config(const Config& c, const std::string& name) {
        std::string prefix = "strategy." + name + ".";
        StrategyConfig s;
        s.enabled               = c.get_bool(prefix + "enabled", false);
        s.sma_period            = static_cast<int>(c.get_int(prefix + "sma_period", 20));
        s.entry_threshold_ticks = static_cast<int>(c.get_int(prefix + "entry_threshold_ticks", 5));
        s.order_qty             = static_cast<int>(c.get_int(prefix + "order_qty", 100));
        s.symbols               = c.get_list(prefix + "symbols");
        return s;
    }
};

// ============================================================
// TRADING SYSTEM CONFIG — the single top-level config object
// ============================================================

struct TradingSystemConfig {
    SystemConfig   system;
    ExchangeConfig exchange;
    RiskConfig     risk;
    StrategyConfig momentum;

    static TradingSystemConfig load(const std::string& path) {
        Config c = Config::from_file(path);
        TradingSystemConfig tc;
        tc.system   = SystemConfig::from_config(c);
        tc.exchange = ExchangeConfig::from_config(c);
        tc.risk     = RiskConfig::from_config(c);
        tc.momentum = StrategyConfig::from_config(c, "momentum");
        return tc;
    }

    static TradingSystemConfig from_string(const std::string& content) {
        Config c = Config::from_string(content);
        TradingSystemConfig tc;
        tc.system   = SystemConfig::from_config(c);
        tc.exchange = ExchangeConfig::from_config(c);
        tc.risk     = RiskConfig::from_config(c);
        tc.momentum = StrategyConfig::from_config(c, "momentum");
        return tc;
    }

    void print() const {
        std::cout << "  === Trading System Config ===\n";
        std::cout << "  System:   log=" << system.log_level
                  << " file=" << system.log_file
                  << " dry_run=" << (system.dry_run ? "true" : "false") << "\n";
        std::cout << "  Exchange: " << exchange.host << ":" << exchange.port
                  << " sender=" << exchange.sender_comp_id << "\n";
        std::cout << "  Risk:     max_order=" << risk.max_order_qty
                  << " max_pos=" << risk.max_position
                  << " max_loss=$" << risk.max_daily_loss_usd << "\n";
        std::cout << "  Momentum: enabled=" << (momentum.enabled ? "true" : "false")
                  << " sma=" << momentum.sma_period
                  << " qty=" << momentum.order_qty
                  << " symbols=";
        for (const auto& s : momentum.symbols) std::cout << s << " ";
        std::cout << "\n";
    }
};

// ============================================================
// MAIN
// ============================================================

int main() {
    std::cout << "=== Configuration System ===\n";

    // -------------------------------------------------------
    // LOAD FROM STRING (simulating a config file)
    // -------------------------------------------------------

    std::string config_content = R"(
# Trading System Configuration
# Generated: 2023-12-01

[system]
log_level = INFO
log_file = trading_log.txt
dry_run = false

[exchange]
host = 10.0.0.1
port = 9000
sender_comp_id = ALGO_TRADER
target_comp_id = NYSE

[risk]
max_order_qty = 200
max_position = 500
max_daily_loss_usd = 10000.0
fat_finger_pct = 2.0

[strategy.momentum]
enabled = true
sma_period = 20
entry_threshold_ticks = 5
order_qty = 100
symbols = SPY, QQQ, AAPL
)";

    try {
        TradingSystemConfig tc = TradingSystemConfig::from_string(config_content);
        tc.print();

        // -------------------------------------------------------
        // DEMONSTRATE TYPED ACCESS
        // -------------------------------------------------------

        std::cout << "\n=== Direct config access ===\n";

        Config cfg = Config::from_string(config_content);

        std::cout << "  risk.max_order_qty: " << cfg.get_int("risk.max_order_qty") << "\n";
        std::cout << "  risk.fat_finger_pct: " << cfg.get_double("risk.fat_finger_pct") << "\n";
        std::cout << "  system.dry_run: " << (cfg.get_bool("system.dry_run") ? "true" : "false") << "\n";

        auto syms = cfg.get_list("strategy.momentum.symbols");
        std::cout << "  symbols (" << syms.size() << "): ";
        for (auto& s : syms) std::cout << s << " ";
        std::cout << "\n";

        // -------------------------------------------------------
        // DEFAULT VALUES
        // -------------------------------------------------------

        std::cout << "\n=== Default values for missing keys ===\n";

        std::cout << "  missing_key (default=42): "
                  << cfg.get_int("missing_key", 42) << "\n";
        std::cout << "  missing_str (default=hello): "
                  << cfg.get_string("missing_key2", "hello") << "\n";

        // -------------------------------------------------------
        // VALIDATION ERROR DEMO
        // -------------------------------------------------------

        std::cout << "\n=== Validation errors ===\n";

        // Try to load config with an out-of-range value
        std::string bad_config = R"(
[risk]
max_order_qty = -100
max_position = 5000
max_daily_loss_usd = 50000
fat_finger_pct = 2.0
[exchange]
host = localhost
port = 9000
sender_comp_id = TEST
target_comp_id = EXCH
[system]
log_level = INFO
log_file = log.txt
dry_run = false
[strategy.momentum]
enabled = false
sma_period = 20
entry_threshold_ticks = 5
order_qty = 100
)";

        try {
            auto bad = TradingSystemConfig::from_string(bad_config);
            (void)bad;
            std::cout << "  ERROR: should have thrown for max_order_qty=-100\n";
        } catch (const std::exception& e) {
            std::cout << "  Caught expected error: " << e.what() << "\n";
        }

        // -------------------------------------------------------
        // WRITE A SAMPLE CONFIG FILE
        // -------------------------------------------------------

        std::cout << "\n=== Writing sample config file ===\n";

        {
            std::ofstream f("sample_config.ini");
            f << config_content;
        }
        std::cout << "  Written to sample_config.ini\n";

        // Load it back from file
        TradingSystemConfig from_file = TradingSystemConfig::load("sample_config.ini");
        std::cout << "  Loaded from file — host: " << from_file.exchange.host << "\n";

    } catch (const std::exception& e) {
        std::cerr << "  Config error: " << e.what() << "\n";
        return 1;
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      At startup:
        TradingSystemConfig cfg = TradingSystemConfig::load("trading.ini");
        // Fail if required values are missing (exchange host, etc.)
        // Validate all ranges at load time

        // Pass config to each subsystem — all use the cached struct, never re-read file
        RiskManager risk(cfg.risk_params());
        FIXGateway  gw(cfg.exchange.host, cfg.exchange.port,
                        cfg.exchange.sender_comp_id, cfg.exchange.target_comp_id);
        AsyncLogger logger(cfg.system.log_file);

        // Strategy uses cfg.momentum
        MomentumStrategy strat(cfg.momentum, risk, gw, logger);

        // To hot-reload risk limits only (on SIGHUP):
        signal(SIGHUP, [](int) {
            auto new_cfg = TradingSystemConfig::load("trading.ini");
            risk.update_limits(new_cfg.risk_params());  // thread-safe atomic update
        });
    */
}
