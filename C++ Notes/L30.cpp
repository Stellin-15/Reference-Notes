// ============================================================
// L30: std::optional, std::variant, std::span
// ============================================================
// WHAT: Three utility types that express intent more clearly
//       and safely than raw pointers, unions, or raw arrays.
//       optional = "might have a value". variant = "one of these
//       types". span = "non-owning view of a contiguous range".
// WHY (TRADING): optional replaces nullable raw pointers for
//   "order might not have filled yet". variant replaces unsafe
//   C unions for "message could be AddOrder, CancelOrder, or
//   Trade". span replaces (pointer, length) pairs for passing
//   byte buffers without copying. Together they make protocol
//   parsing and data flow safer and more expressive.
// PHASE: Modern C++
// ============================================================

/*
  CONCEPT OVERVIEW:

  std::optional<T> (C++17):
    Holds either a value of type T OR nothing ("nullopt").
    Replaces: nullable pointers, sentinel values (-1, 0.0, ""), bool+value pairs.
    Access: *opt or opt.value() — throws std::bad_optional_access if empty.
    Check: opt.has_value() or just if (opt).
    Make: std::optional<T>{value} or just {value} or std::nullopt for empty.
    Cost: sizeof(optional<T>) = sizeof(T) + 1 byte (for the "has_value" flag).
    TRADING USE: optional<Fill> — returned by try_fill() — either fills or doesn't.
                 optional<Price> — best bid when book might be empty.
                 optional<Signal> — strategy might not generate a signal this tick.

  std::variant<T1, T2, ...> (C++17):
    Holds exactly ONE of the listed types at a time (type-safe union).
    Replaces: C unions (unsafe, no type tracking), void* with type tags.
    Access: std::get<T>(v) — throws if wrong type.
            std::get_if<T>(&v) — returns pointer (nullptr if wrong type, no throw).
            std::visit(visitor, v) — calls the right overload for whichever type is active.
    Check: v.index() returns which type is active (0, 1, 2...).
    TRADING USE: variant<AddOrder, CancelOrder, ReplaceOrder, Trade> — parsed messages.
                 variant<LimitOrder, MarketOrder, IOC, FOK> — order types.

  std::span<T> (C++20):
    Non-owning view of a contiguous range of T: just (pointer, length).
    Replaces: (T*, size_t) parameter pairs. No copy, no ownership.
    Works with: raw arrays, std::vector, std::array.
    span<const T> — read-only view.
    span<T>       — read-write view.
    TRADING USE: span<const uint8_t> for network receive buffers.
                 span<const double> for price arrays passed to calculations.
                 Avoids copying while keeping size information.

  OVERLOADED VISITOR PATTERN (for std::visit):
    struct Visitor {
        void operator()(const AddOrder& m) { ... }
        void operator()(const CancelOrder& m) { ... }
    };
    std::visit(Visitor{}, message);
    Or with lambdas (C++20 overloaded helper):
    std::visit(overloaded{
        [](const AddOrder& m) { ... },
        [](const CancelOrder& m) { ... },
    }, message);

  TRADING USE CASE:
    // optional: strategy signal
    std::optional<Signal> evaluate(const Quote& q) {
        if (signal_condition()) return Signal{...};
        return std::nullopt;  // no signal this tick
    }

    // variant: protocol message dispatch
    using Message = std::variant<AddOrder, CancelOrder, Trade>;
    Message msg = parse_itch_packet(buf, len);
    std::visit([&book](auto& m) { book.apply(m); }, msg);

    // span: parse bytes without copying
    void parse(std::span<const uint8_t> buf) { ... }
    parse({recv_buf, bytes_received});  // no copy

  COMMON MISTAKES:
    - Accessing optional without checking: *opt when opt is empty → undefined behavior
    - Using std::get<T> on wrong variant type → throws std::bad_variant_access
    - span pointing to a temporary that was destroyed — dangling span
    - Holding span after the underlying container is reallocated (vector resize)
*/

#include <iostream>
#include <optional>
#include <variant>
#include <span>
#include <vector>
#include <string>
#include <cstdint>
#include <cstring>   // memcpy

// ============================================================
// TYPES
// ============================================================

struct Quote  { std::string symbol; double bid, ask; };

struct Signal {
    bool   is_buy;
    double price;
    int    qty;
    std::string reason;
};

// ITCH-style message types (binary protocol — each is a different struct)
struct AddOrder {
    uint64_t order_id;
    int64_t  price;   // ticks
    int32_t  qty;
    bool     is_buy;
};

struct CancelOrder {
    uint64_t order_id;
    int32_t  cancel_qty;
};

struct ExecuteOrder {
    uint64_t order_id;
    uint64_t match_id;
    int32_t  exec_qty;
    int64_t  exec_price;
};

struct Trade {
    uint64_t match_id;
    int64_t  price;
    int32_t  qty;
};

// Variant holds exactly one message type at a time
using Message = std::variant<AddOrder, CancelOrder, ExecuteOrder, Trade>;

// ============================================================
// STRATEGY: returns optional<Signal>
// ============================================================

class MomentumStrategy {
public:
    // Returns a signal if there's one, or nullopt if not
    std::optional<Signal> evaluate(const Quote& q) {
        double mid = (q.bid + q.ask) / 2.0;
        ++ticks_;

        if (ticks_ < 2) { prev_mid_ = mid; return std::nullopt; }

        double change = (mid - prev_mid_) / prev_mid_;
        prev_mid_ = mid;

        if (change > 0.0005) {  // +5bps move
            return Signal{true, q.ask, 100, "Momentum UP"};
        }
        if (change < -0.0005) {
            return Signal{false, q.bid, 100, "Momentum DOWN"};
        }
        return std::nullopt;   // no signal this tick
    }

private:
    double prev_mid_ = 0.0;
    int    ticks_    = 0;
};

// ============================================================
// ORDER BOOK: best_bid/ask return optional
// ============================================================

class SimpleBook {
public:
    void update(double bid, double ask, int bid_sz, int ask_sz) {
        bid_ = bid; ask_ = ask; bid_sz_ = bid_sz; ask_sz_ = ask_sz; has_data_ = true;
    }

    // Returns nullopt if book is empty
    std::optional<double> best_bid() const {
        if (!has_data_) return std::nullopt;
        return bid_;
    }

    std::optional<double> best_ask() const {
        if (!has_data_) return std::nullopt;
        return ask_;
    }

    // Returns the spread, or nullopt if book has no data
    std::optional<double> spread() const {
        if (!has_data_) return std::nullopt;
        return ask_ - bid_;
    }

private:
    double bid_ = 0.0, ask_ = 0.0;
    int    bid_sz_ = 0, ask_sz_ = 0;
    bool   has_data_ = false;
};

// ============================================================
// VISITOR for std::variant message dispatch
// ============================================================

// Helper: create a visitor from multiple lambdas (overloaded pattern)
template<typename... Ts>
struct overloaded : Ts... { using Ts::operator()...; };
template<typename... Ts> overloaded(Ts...) -> overloaded<Ts...>;  // deduction guide

struct BookUpdater {
    void operator()(const AddOrder& m) {
        std::cout << "  AddOrder: #" << m.order_id
                  << " $" << m.price / 10000.0 << " x" << m.qty
                  << (m.is_buy ? " BUY" : " SELL") << "\n";
    }
    void operator()(const CancelOrder& m) {
        std::cout << "  CancelOrder: #" << m.order_id << " qty=" << m.cancel_qty << "\n";
    }
    void operator()(const ExecuteOrder& m) {
        std::cout << "  Execute: #" << m.order_id
                  << " match=" << m.match_id
                  << " qty=" << m.exec_qty
                  << " $" << m.exec_price / 10000.0 << "\n";
    }
    void operator()(const Trade& m) {
        std::cout << "  Trade: match=" << m.match_id
                  << " $" << m.price / 10000.0 << " x" << m.qty << "\n";
    }
};

// ============================================================
// SPAN: parse raw bytes without copying
// ============================================================

// Parse a fixed-layout binary AddOrder message from raw bytes
// span<const uint8_t> replaces (const uint8_t* buf, size_t len)
AddOrder parse_add_order(std::span<const uint8_t> buf) {
    // Minimal bounds check
    if (buf.size() < 17) return {};

    AddOrder msg{};
    std::memcpy(&msg.order_id, buf.data() + 0, 8);
    std::memcpy(&msg.price,    buf.data() + 8, 8);
    std::memcpy(&msg.qty,      buf.data() + 16, 4);
    // side byte would follow at offset 20
    return msg;
}

// Calculate VWAP from a span of prices and volumes — no copy of the arrays
double calculate_vwap(std::span<const double> prices, std::span<const double> volumes) {
    if (prices.size() != volumes.size() || prices.empty()) return 0.0;
    double sum_pv = 0.0, sum_v = 0.0;
    for (size_t i = 0; i < prices.size(); ++i) {
        sum_pv += prices[i] * volumes[i];
        sum_v  += volumes[i];
    }
    return sum_v > 0.0 ? sum_pv / sum_v : 0.0;
}

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // std::optional — nullable value without raw pointers
    // -------------------------------------------------------

    std::cout << "=== std::optional ===\n";

    {
        // Strategy produces optional signals
        MomentumStrategy strat;
        std::vector<Quote> quotes = {
            {"AAPL", 182.45, 182.55},
            {"AAPL", 182.60, 182.70},   // +10bps → BUY signal
            {"AAPL", 182.62, 182.72},   // small move → no signal
            {"AAPL", 182.50, 182.60},   // reversal → SELL signal
        };

        for (const auto& q : quotes) {
            auto signal = strat.evaluate(q);   // returns optional<Signal>

            if (signal) {   // if() tests has_value()
                std::cout << "Signal: " << (signal->is_buy ? "BUY" : "SELL")
                          << " @ $" << signal->price
                          << " [" << signal->reason << "]\n";
                // signal->field accesses the contained Signal's members
            } else {
                std::cout << "No signal this tick\n";
            }
        }

        // Empty book returns nullopt
        SimpleBook book;
        auto bid = book.best_bid();
        if (!bid.has_value()) {
            std::cout << "Book is empty — no best bid\n";
        }

        book.update(182.50, 182.55, 100, 200);

        // value_or: provide a default if empty
        double safe_bid = book.best_bid().value_or(0.0);
        double safe_spr = book.spread().value_or(-1.0);
        std::cout << "Best bid: $" << safe_bid << "\n";
        std::cout << "Spread:   $" << safe_spr << "\n";

        // Chaining with optional (value_or, and_then in C++23)
        auto display_spread = book.spread();
        if (display_spread && *display_spread < 0.10) {
            std::cout << "Tight spread: $" << *display_spread << " — consider trading\n";
        }
    }

    // -------------------------------------------------------
    // std::variant — type-safe message dispatch
    // -------------------------------------------------------

    std::cout << "\n=== std::variant ===\n";

    {
        // Simulate a stream of ITCH messages parsed from the network
        std::vector<Message> messages = {
            AddOrder{1001, 1825000, 100, true},    // holds AddOrder
            AddOrder{1002, 1825500, 200, false},
            CancelOrder{1001, 50},                  // holds CancelOrder
            Trade{9001, 1825200, 75},               // holds Trade
            ExecuteOrder{1002, 9002, 100, 1825500}, // holds ExecuteOrder
        };

        std::cout << "Processing " << messages.size() << " messages:\n";

        // OPTION 1: std::visit with a struct visitor
        BookUpdater updater;
        for (const auto& msg : messages) {
            std::visit(updater, msg);
        }

        // OPTION 2: std::visit with overloaded lambdas (inline)
        std::cout << "\nUsing overloaded lambdas:\n";
        for (const auto& msg : messages) {
            std::visit(overloaded{
                [](const AddOrder& m)    { std::cout << "  [A] Order #" << m.order_id << "\n"; },
                [](const CancelOrder& m) { std::cout << "  [C] Cancel #" << m.order_id << "\n"; },
                [](const ExecuteOrder& m){ std::cout << "  [E] Exec #" << m.order_id << "\n"; },
                [](const Trade& m)       { std::cout << "  [T] Trade match=" << m.match_id << "\n"; },
            }, msg);
        }

        // OPTION 3: std::get_if — check type without exception
        const auto& first_msg = messages[0];
        if (auto* add = std::get_if<AddOrder>(&first_msg)) {
            std::cout << "\nFirst message is AddOrder: #" << add->order_id << "\n";
        }
        if (std::get_if<Trade>(&first_msg) == nullptr) {
            std::cout << "First message is NOT a Trade\n";
        }

        // msg.index(): which type is active (0=AddOrder, 1=CancelOrder, ...)
        std::cout << "Message indices: ";
        for (const auto& m : messages) std::cout << m.index() << " ";
        std::cout << "\n";
    }

    // -------------------------------------------------------
    // std::span — non-owning view of contiguous data
    // -------------------------------------------------------

    std::cout << "\n=== std::span ===\n";

    {
        // Parse from a raw byte buffer (simulating a network packet)
        // In real HFT: this buf comes directly from recv() — no copy
        uint8_t raw_packet[21] = {};
        uint64_t order_id = 1234567890ULL;
        int64_t  price    = 1825000LL;
        int32_t  qty      = 100;
        std::memcpy(raw_packet + 0,  &order_id, 8);
        std::memcpy(raw_packet + 8,  &price,    8);
        std::memcpy(raw_packet + 16, &qty,      4);
        raw_packet[20] = 'B';  // side = BUY

        // Pass span to parser — no copy, just (pointer, 21)
        auto parsed = parse_add_order({raw_packet, 21});  // create span from array
        std::cout << "Parsed from span: order_id=" << parsed.order_id
                  << " price=$" << parsed.price / 10000.0
                  << " qty=" << parsed.qty << "\n";

        // span from std::vector — view into existing data
        std::vector<double> price_vec = {182.50, 182.55, 182.48, 182.60};
        std::vector<double> vol_vec   = {1000.0, 500.0,  800.0,  300.0};

        double vwap = calculate_vwap(price_vec, vol_vec);   // passes spans (no copy)
        std::cout << "VWAP from span: $" << vwap << "\n";

        // Subspan: view of just part of the data
        std::span<const double> all_prices = price_vec;
        std::span<const double> last_two   = all_prices.last(2);   // last 2 elements
        std::cout << "Last 2 prices: $" << last_two[0] << ", $" << last_two[1] << "\n";

        // first(n) / last(n) / subspan(offset, count)
        std::span<const double> first_three = all_prices.first(3);
        double first_three_avg = 0.0;
        for (double p : first_three) first_three_avg += p;
        first_three_avg /= first_three.size();
        std::cout << "First 3 avg: $" << first_three_avg << "\n";

        // span knows its size — unlike raw pointer + length pair
        std::cout << "Span size: " << all_prices.size() << "\n";
        std::cout << "Span data ptr: " << (void*)all_prices.data() << "\n";
        std::cout << "Vector data ptr: " << (void*)price_vec.data() << "\n";
        // Same pointer — span really is just a view, no copy
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Full ITCH message processing using variant and span:

        // The receive buffer: raw bytes from the network
        uint8_t recv_buf[4096];
        int bytes = recv(sock, recv_buf, sizeof(recv_buf), MSG_DONTWAIT);
        if (bytes <= 0) return;

        // Parse bytes into typed messages using span (no copy of bytes)
        std::span<const uint8_t> packet{recv_buf, static_cast<size_t>(bytes)};
        size_t offset = 0;

        while (offset < packet.size()) {
            uint8_t msg_type = packet[offset];
            auto msg_span    = packet.subspan(offset + 1);

            Message msg = parse_message(msg_type, msg_span);  // returns variant

            // Dispatch with zero overhead (compiler can devirtualize std::visit)
            std::visit([&book](auto& m) { book.apply(m); }, msg);

            // Advance to next message (using the parsed length)
            offset += message_length(msg_type);
        }

        // Result: bytes parsed → typed messages → book updated.
        // Zero copies. Zero heap allocations. All on the stack.
    */
}
