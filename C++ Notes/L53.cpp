// ============================================================
// L53: Order Representation
// ============================================================
// WHAT: The canonical data model for an order in a trading system.
//       Defines the Order struct and all associated enumerations:
//       Side (buy/sell), OrderType (limit/market/IOC/FOK/GTD),
//       OrderStatus (new/partial/filled/cancelled/rejected),
//       TimeInForce, and a compact numeric ID scheme.
// WHY (TRADING): Every other component — order book, matching
//   engine, risk system, FIX gateway, PnL tracker — receives and
//   passes Orders. Getting this model right from the start prevents
//   bugs that are painful to fix once the rest of the system is built.
//   Key choices: int64_t for prices (never double), int32_t for qty,
//   fixed-size char arrays for symbols (no std::string on hot path).
// PHASE: Trading Systems Implementation
// ============================================================

/*
  CONCEPT OVERVIEW:

  PRICE REPRESENTATION:
    Always store prices as int64_t in "ticks" (integer multiples of
    the minimum price increment). Never use double — floating point
    arithmetic accumulates error over millions of trades.

    Tick size examples:
      US equities (e.g. SPY):  tick = $0.01 → price_ticks = price * 100
      Futures (e.g. ES):       tick = $0.25 → price_ticks = price * 4
      FX (e.g. EURUSD):        tick = 0.0001 → price_ticks = price * 10000
      Crypto (BTC):            tick = $0.01 → price_ticks = price * 100

    We use a universal convention: PRICE_MULTIPLIER = 10000
    $182.50 → 1825000 ticks

  QUANTITY:
    int32_t for quantity. In equities: 1 share = 1 unit.
    In futures: 1 contract = 1 unit. Range: ±2.1 billion — sufficient.

  SYMBOL:
    char[8] zero-padded, not std::string. Reasons:
    1. No heap allocation in hot path
    2. Fits in one cache line (or part of one)
    3. Trivially copyable → can be passed in registers
    4. strcmp() works correctly on fixed-width

  ORDER ID:
    uint64_t — 64-bit monotonic counter. Never reuse IDs within a session.
    Exchange order IDs may be different from internal IDs — track both.

  COMMON MISTAKES:
    - Using float or double for price (floating point error accumulates)
    - Using std::string for symbol (heap allocation, not trivially copyable)
    - Using int instead of int64_t for price (overflow at ~$21M for int32_t)
    - Forgetting to set timestamps at each state transition
    - Not distinguishing internal order ID from exchange order ID (ClOrdID vs ExecID)
*/

#include <iostream>
#include <cstdint>
#include <cstring>
#include <cassert>
#include <array>
#include <string>
#include <chrono>

// ============================================================
// PRICE ENCODING
// ============================================================

constexpr int64_t PRICE_MULTIPLIER = 10000;  // 4 decimal places

// Convert human-readable price to internal ticks
constexpr int64_t to_ticks(double price) {
    return static_cast<int64_t>(price * PRICE_MULTIPLIER + 0.5);  // round half-up
}

// Convert ticks back to double (for display only — never use in calculations)
constexpr double to_price(int64_t ticks) {
    return static_cast<double>(ticks) / PRICE_MULTIPLIER;
}

// ============================================================
// SYMBOL HELPERS
// ============================================================

constexpr int SYMBOL_LEN = 8;  // max symbol length (null-padded)

using Symbol = std::array<char, SYMBOL_LEN>;

// Create a Symbol from a string literal — pads with '\0'
Symbol make_symbol(const char* s) {
    Symbol sym{};  // zero-initialize
    for (int i = 0; i < SYMBOL_LEN && s[i] != '\0'; ++i) sym[i] = s[i];
    return sym;
}

// Display a Symbol as a printable string
const char* sym_str(const Symbol& s) { return s.data(); }

// ============================================================
// ENUMERATIONS
// ============================================================

// Which side of the market — fundamental to all order logic
enum class Side : uint8_t {
    BUY  = 0,  // want to buy (bid side)
    SELL = 1   // want to sell (ask side)
};

// Order type — determines how the exchange processes the order
enum class OrderType : uint8_t {
    LIMIT       = 0,  // rest at price if not immediately matchable
    MARKET      = 1,  // fill immediately at any price
    STOP        = 2,  // becomes MARKET when stop price is touched
    STOP_LIMIT  = 3,  // becomes LIMIT when stop price is touched
    IOC         = 4,  // Immediate Or Cancel: fill what's available now, cancel rest
    FOK         = 5,  // Fill Or Kill: fill entire qty now or cancel entirely
    GTD         = 6   // Good Till Date: rests until specific date
};

// Time-in-force — how long the order remains active
enum class TimeInForce : uint8_t {
    DAY  = 0,  // expires at end of trading session
    GTC  = 1,  // Good Till Cancelled: persists across sessions
    IOC  = 2,  // fill now or cancel (same semantic as OrderType::IOC for some venues)
    GTD  = 3,  // Good Till Date
    AT_OPEN  = 4,  // participate in opening auction only
    AT_CLOSE = 5   // participate in closing auction only
};

// Order lifecycle state — updated at each state transition
enum class OrderStatus : uint8_t {
    NEW              = 0,  // just created, not yet sent to exchange
    PENDING_NEW      = 1,  // sent to exchange, awaiting acknowledgment
    ACKNOWLEDGED     = 2,  // exchange confirmed receipt
    PARTIALLY_FILLED = 3,  // some quantity has been executed
    FILLED           = 4,  // entire quantity executed
    PENDING_CANCEL   = 5,  // cancel request sent, awaiting confirmation
    CANCELLED        = 6,  // cancelled by us or by exchange (e.g. IOC rest)
    REJECTED         = 7,  // exchange rejected the order
    EXPIRED          = 8   // GTD/DAY order that expired
};

// ============================================================
// FILL — record of a single execution
// ============================================================

struct Fill {
    uint64_t fill_id;          // unique ID for this fill (from exchange)
    uint64_t order_id;         // which order was (partially) filled
    uint64_t exec_id;          // exchange execution ID (for reconciliation)
    Symbol   symbol;           // instrument
    Side     side;             // BUY or SELL
    int64_t  price;            // fill price in ticks
    int32_t  qty;              // fill quantity
    uint64_t exchange_ts_ns;   // exchange-reported timestamp
    uint64_t local_ts_ns;      // when we received the fill report
    bool     is_last;          // true if this fill completes the order
};

// ============================================================
// ORDER — the central data model
// ============================================================

struct Order {
    // ── Identity ──────────────────────────────────────────
    uint64_t order_id;          // internal monotonic ID
    uint64_t client_order_id;   // ClOrdID sent to exchange (can differ)
    uint64_t exchange_order_id; // assigned by exchange on ACK (may be 0 until ACK'd)

    // ── Instrument ────────────────────────────────────────
    Symbol   symbol;            // instrument name (8 chars, zero-padded)

    // ── Order parameters ─────────────────────────────────
    Side         side;          // BUY or SELL
    OrderType    type;          // LIMIT, MARKET, IOC, etc.
    TimeInForce  tif;           // DAY, GTC, etc.
    int64_t      price;         // limit price in ticks (0 for MARKET orders)
    int64_t      stop_price;    // stop trigger price in ticks (0 if not a stop)
    int32_t      quantity;      // total order quantity
    int32_t      filled_qty;    // how much has been executed so far
    int32_t      remaining_qty; // quantity - filled_qty (derived, kept for speed)

    // ── State ─────────────────────────────────────────────
    OrderStatus  status;        // current lifecycle state

    // ── Timestamps ────────────────────────────────────────
    uint64_t created_ns;        // when order was created locally
    uint64_t sent_ns;           // when order was sent to exchange
    uint64_t acked_ns;          // when exchange acknowledged
    uint64_t last_fill_ns;      // timestamp of most recent fill

    // ── Strategy tag ──────────────────────────────────────
    uint16_t strategy_id;       // which strategy generated this order
    uint16_t account_id;        // which account to trade under

    // ── Fill tracking ─────────────────────────────────────
    int64_t  avg_fill_price;    // volume-weighted average fill price (ticks)
    int64_t  total_fill_value;  // sum of price*qty (numerator for VWAP)

    // ── Padding to cache line ─────────────────────────────
    // sizeof so far: let compiler lay it out, add padding to reach 128 bytes
    // for frequent access patterns where two orders fit in 2 cache lines
    char _pad[4];               // adjust as needed after measuring sizeof(Order)
};

// ============================================================
// ORDER BUILDER — ergonomic factory functions
// ============================================================

// Get current time in nanoseconds
static uint64_t now_ns() {
    return static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count());
}

// Monotonically increasing order ID
static uint64_t next_order_id() {
    static uint64_t counter = 1;
    return counter++;
}

Order make_limit_order(const char* sym, Side side, double price, int32_t qty,
                       uint16_t strategy_id = 0, uint16_t account_id = 0) {
    Order o{};
    o.order_id         = next_order_id();
    o.client_order_id  = o.order_id;           // use same as internal until ACK
    o.exchange_order_id = 0;                    // assigned on ACK
    o.symbol           = make_symbol(sym);
    o.side             = side;
    o.type             = OrderType::LIMIT;
    o.tif              = TimeInForce::DAY;
    o.price            = to_ticks(price);
    o.stop_price       = 0;
    o.quantity         = qty;
    o.filled_qty       = 0;
    o.remaining_qty    = qty;
    o.status           = OrderStatus::NEW;
    o.created_ns       = now_ns();
    o.sent_ns          = 0;
    o.acked_ns         = 0;
    o.last_fill_ns     = 0;
    o.strategy_id      = strategy_id;
    o.account_id       = account_id;
    o.avg_fill_price   = 0;
    o.total_fill_value = 0;
    return o;
}

Order make_market_order(const char* sym, Side side, int32_t qty,
                        uint16_t strategy_id = 0, uint16_t account_id = 0) {
    Order o = make_limit_order(sym, side, 0.0, qty, strategy_id, account_id);
    o.type  = OrderType::MARKET;
    o.price = 0;  // market orders have no price
    return o;
}

Order make_ioc_order(const char* sym, Side side, double price, int32_t qty,
                     uint16_t strategy_id = 0, uint16_t account_id = 0) {
    Order o = make_limit_order(sym, side, price, qty, strategy_id, account_id);
    o.type  = OrderType::IOC;
    o.tif   = TimeInForce::IOC;
    return o;
}

// ============================================================
// ORDER STATE MACHINE — legal transitions
// ============================================================

// Returns true if the transition is legal; false if invalid.
bool can_transition(OrderStatus from, OrderStatus to) {
    switch (from) {
        case OrderStatus::NEW:
            return to == OrderStatus::PENDING_NEW ||
                   to == OrderStatus::REJECTED;

        case OrderStatus::PENDING_NEW:
            return to == OrderStatus::ACKNOWLEDGED ||
                   to == OrderStatus::REJECTED      ||
                   to == OrderStatus::PARTIALLY_FILLED ||
                   to == OrderStatus::FILLED;

        case OrderStatus::ACKNOWLEDGED:
            return to == OrderStatus::PARTIALLY_FILLED ||
                   to == OrderStatus::FILLED           ||
                   to == OrderStatus::PENDING_CANCEL   ||
                   to == OrderStatus::CANCELLED        ||
                   to == OrderStatus::EXPIRED;

        case OrderStatus::PARTIALLY_FILLED:
            return to == OrderStatus::PARTIALLY_FILLED ||
                   to == OrderStatus::FILLED           ||
                   to == OrderStatus::PENDING_CANCEL   ||
                   to == OrderStatus::CANCELLED;

        case OrderStatus::FILLED:
        case OrderStatus::CANCELLED:
        case OrderStatus::REJECTED:
        case OrderStatus::EXPIRED:
            return false;  // terminal states

        case OrderStatus::PENDING_CANCEL:
            return to == OrderStatus::CANCELLED     ||
                   to == OrderStatus::ACKNOWLEDGED; // cancel rejected — stays open
    }
    return false;
}

// ============================================================
// APPLY A FILL to an Order — updates state inline
// ============================================================

void apply_fill(Order& o, const Fill& f) {
    assert(f.qty > 0);
    assert(f.qty <= o.remaining_qty);

    o.filled_qty    += f.qty;
    o.remaining_qty -= f.qty;
    o.total_fill_value += f.price * f.qty;  // accumulate numerator
    o.last_fill_ns   = f.local_ts_ns;

    if (o.filled_qty > 0)
        o.avg_fill_price = o.total_fill_value / o.filled_qty;  // VWAP integer

    if (o.remaining_qty == 0)
        o.status = OrderStatus::FILLED;
    else
        o.status = OrderStatus::PARTIALLY_FILLED;
}

// ============================================================
// DISPLAY HELPERS
// ============================================================

const char* side_str(Side s) {
    return s == Side::BUY ? "BUY" : "SELL";
}

const char* type_str(OrderType t) {
    switch (t) {
        case OrderType::LIMIT:      return "LIMIT";
        case OrderType::MARKET:     return "MARKET";
        case OrderType::IOC:        return "IOC";
        case OrderType::FOK:        return "FOK";
        case OrderType::STOP:       return "STOP";
        case OrderType::STOP_LIMIT: return "STOP_LIMIT";
        case OrderType::GTD:        return "GTD";
    }
    return "UNKNOWN";
}

const char* status_str(OrderStatus s) {
    switch (s) {
        case OrderStatus::NEW:              return "NEW";
        case OrderStatus::PENDING_NEW:      return "PENDING_NEW";
        case OrderStatus::ACKNOWLEDGED:     return "ACKNOWLEDGED";
        case OrderStatus::PARTIALLY_FILLED: return "PARTIALLY_FILLED";
        case OrderStatus::FILLED:           return "FILLED";
        case OrderStatus::PENDING_CANCEL:   return "PENDING_CANCEL";
        case OrderStatus::CANCELLED:        return "CANCELLED";
        case OrderStatus::REJECTED:         return "REJECTED";
        case OrderStatus::EXPIRED:          return "EXPIRED";
    }
    return "UNKNOWN";
}

void print_order(const Order& o) {
    std::cout << "  Order #" << o.order_id
              << " | " << sym_str(o.symbol)
              << " | " << side_str(o.side)
              << " " << type_str(o.type)
              << " | price=" << to_price(o.price)
              << " | qty=" << o.quantity
              << " | filled=" << o.filled_qty
              << " | remaining=" << o.remaining_qty
              << " | status=" << status_str(o.status) << "\n";
}

// ============================================================
// MAIN
// ============================================================

int main() {
    // Verify assumptions about our data model
    static_assert(sizeof(int64_t) == 8, "int64_t must be 8 bytes");
    static_assert(sizeof(Symbol)  == SYMBOL_LEN, "Symbol size mismatch");

    std::cout << "=== Order model sizes ===\n";
    std::cout << "  sizeof(Order):  " << sizeof(Order)  << " bytes\n";
    std::cout << "  sizeof(Fill):   " << sizeof(Fill)   << " bytes\n";
    std::cout << "  sizeof(Symbol): " << sizeof(Symbol) << " bytes\n";
    std::cout << "  sizeof(Side):   " << sizeof(Side)   << " bytes (enum class uint8_t)\n";

    // -------------------------------------------------------
    // CREATE ORDERS
    // -------------------------------------------------------

    std::cout << "\n=== Creating orders ===\n";

    Order buy_limit  = make_limit_order("SPY",   Side::BUY,  182.50, 100, /*strategy=*/1);
    Order sell_limit = make_limit_order("SPY",   Side::SELL, 182.75, 100, /*strategy=*/1);
    Order mkt_order  = make_market_order("AAPL", Side::BUY,   50,         /*strategy=*/2);
    Order ioc_order  = make_ioc_order("QQQ",    Side::BUY,  350.00, 200, /*strategy=*/1);

    print_order(buy_limit);
    print_order(sell_limit);
    print_order(mkt_order);
    print_order(ioc_order);

    // -------------------------------------------------------
    // SIMULATE STATE TRANSITIONS
    // -------------------------------------------------------

    std::cout << "\n=== State transitions ===\n";

    std::cout << "  Initial: " << status_str(buy_limit.status) << "\n";

    // Sent to exchange
    buy_limit.status  = OrderStatus::PENDING_NEW;
    buy_limit.sent_ns = now_ns();
    std::cout << "  After send: " << status_str(buy_limit.status) << "\n";

    // Exchange ACK
    buy_limit.status           = OrderStatus::ACKNOWLEDGED;
    buy_limit.acked_ns         = now_ns();
    buy_limit.exchange_order_id = 9900001;
    std::cout << "  After ACK (exch id=" << buy_limit.exchange_order_id << "): "
              << status_str(buy_limit.status) << "\n";

    // -------------------------------------------------------
    // SIMULATE FILLS
    // -------------------------------------------------------

    std::cout << "\n=== Applying fills ===\n";

    // Partial fill: 30 shares at $182.50
    Fill f1{};
    f1.fill_id       = 1001;
    f1.order_id      = buy_limit.order_id;
    f1.symbol        = buy_limit.symbol;
    f1.side          = Side::BUY;
    f1.price         = to_ticks(182.50);
    f1.qty           = 30;
    f1.local_ts_ns   = now_ns();

    apply_fill(buy_limit, f1);
    print_order(buy_limit);
    std::cout << "  VWAP: $" << to_price(buy_limit.avg_fill_price) << "\n";

    // Second fill: remaining 70 shares at $182.51
    Fill f2{};
    f2.fill_id       = 1002;
    f2.order_id      = buy_limit.order_id;
    f2.symbol        = buy_limit.symbol;
    f2.side          = Side::BUY;
    f2.price         = to_ticks(182.51);
    f2.qty           = 70;
    f2.local_ts_ns   = now_ns();

    apply_fill(buy_limit, f2);
    print_order(buy_limit);
    std::cout << "  VWAP: $" << to_price(buy_limit.avg_fill_price) << "\n";

    // -------------------------------------------------------
    // PRICE TICK ENCODING DEMO
    // -------------------------------------------------------

    std::cout << "\n=== Price encoding ===\n";

    double prices[] = {182.50, 100.00, 1.2345, 0.0001, 99999.99};
    for (double p : prices) {
        int64_t ticks = to_ticks(p);
        double  back  = to_price(ticks);
        std::cout << "  $" << p << " → " << ticks << " ticks → $" << back << "\n";
    }

    // -------------------------------------------------------
    // STATE MACHINE LEGALITY CHECK
    // -------------------------------------------------------

    std::cout << "\n=== State machine validation ===\n";

    auto check = [](OrderStatus from, OrderStatus to, bool expected) {
        bool result = can_transition(from, to);
        std::cout << "  " << status_str(from) << " → " << status_str(to)
                  << ": " << (result ? "ALLOWED" : "ILLEGAL")
                  << (result == expected ? "" : " ***UNEXPECTED***") << "\n";
    };

    check(OrderStatus::NEW,          OrderStatus::PENDING_NEW,      true);
    check(OrderStatus::PENDING_NEW,  OrderStatus::ACKNOWLEDGED,     true);
    check(OrderStatus::ACKNOWLEDGED, OrderStatus::PARTIALLY_FILLED, true);
    check(OrderStatus::FILLED,       OrderStatus::CANCELLED,        false);  // terminal
    check(OrderStatus::CANCELLED,    OrderStatus::ACKNOWLEDGED,     false);  // can't reopen

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      In production, every component receives orders by pointer or
      reference — never by value. The order lives in a pre-allocated
      pool (see L44) and moves through states as the order lifecycle
      progresses. The FIX gateway (L56) serializes Order → FIX message.
      The risk system (L59) checks the Order before it's sent.
      The PnL tracker (L60) updates on each Fill.
      All components share the same Order definition from this file.
    */
}
