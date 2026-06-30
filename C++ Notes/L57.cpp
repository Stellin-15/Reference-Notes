// ============================================================
// L57: NASDAQ ITCH Protocol (Binary Market Data)
// ============================================================
// WHAT: NASDAQ ITCH 5.0 is a binary market data protocol that
//       describes every order event on NASDAQ: adds, cancels,
//       deletions, executions, and trades. Each message is a
//       tightly packed struct with big-endian integer fields.
//       Parsing uses reinterpret_cast + ntohl/ntohs for byte swap.
// WHY (TRADING): ITCH is the canonical example of how real exchange
//   data feeds work. CME MDP 3.0, NYSE Pillar, and OPRA all use
//   similar binary-packed formats. Understanding ITCH gives you the
//   blueprint for parsing ANY binary market data feed. ITCH carries
//   the full limit order book — every add, cancel, and execute
//   message needed to reconstruct the exact state of the book.
// PHASE: Trading Systems Implementation
// ============================================================

/*
  CONCEPT OVERVIEW:

  ITCH 5.0 MESSAGE FORMAT:
    Each message begins with:
      uint16_t length;    (big-endian) — total message length including this field
      uint8_t  msg_type;  — identifies the message type
    Followed by type-specific fields, all big-endian.

  KEY MESSAGE TYPES:
    'S'  = System Event         (market open/close signals)
    'R'  = Stock Directory      (instrument reference data)
    'H'  = Stock Trading Action (halt/resume)
    'A'  = Add Order (no MPID)  — adds a new limit order to the book
    'F'  = Add Order (with MPID)— same, with market participant ID
    'E'  = Order Executed       — a resting order was executed
    'C'  = Order Executed with Price (price is different from limit)
    'X'  = Order Cancel         — partially cancel a resting order
    'D'  = Order Delete         — completely remove a resting order
    'U'  = Order Replace        — replace (cancel+add) a resting order
    'P'  = Trade (non-displayable)
    'Q'  = Cross Trade
    'B'  = Broken Trade
    'I'  = NOII (Net Order Imbalance Indicator, for opens/closes)

  BYTE ORDER:
    All multi-byte integers in ITCH are BIG-ENDIAN (network byte order).
    x86/x64 CPUs are LITTLE-ENDIAN.
    Use ntohl() for uint32_t, ntohs() for uint16_t, be64toh() for uint64_t.

  KEY FIELDS:
    order_ref_num  : uint64_t — unique ID for a resting order
    shares         : uint32_t — number of shares
    price          : uint32_t — price in 1/10000 cents (i.e. × 10000 × 100 = × 1000000)
      Example: price = 18250000 means $182.50 (divide by 10000)
    timestamp      : uint64_t nanoseconds since midnight
    stock          : char[8] — symbol, space-padded

  PRICE CONVERSION:
    ITCH price units: integer, 1/10000 of a cent (i.e. 1/1000000 of a dollar)
    $182.50 = 182500000 (in ITCH units)
    To convert to dollars: price / 10000.0 (for display)
    To convert to our internal ticks (× 10000): price / 100

  COMMON MISTAKES:
    - Forgetting to byte-swap multi-byte integers (reading garbage)
    - Misidentifying price units (ITCH uses 1/10000 cents, not 1/10000 dollars)
    - Not handling message framing (messages are variable length, concatenated)
    - Skipping the 'D' (Delete) message — ghost levels accumulate in the book
    - Not building the reference data (symbol → lot size, tick size) from 'R' messages
*/

#include <iostream>
#include <cstdint>
#include <cstring>
#include <cassert>
#include <unordered_map>
#include <optional>
#include <vector>
#include <array>

// Cross-platform byte swap
#if defined(_MSC_VER)
#  include <intrin.h>
#  include <winsock2.h>
#  pragma comment(lib, "Ws2_32.lib")
   static uint64_t be64(uint64_t x) { return _byteswap_uint64(x); }
#elif defined(__GNUC__) || defined(__clang__)
#  include <arpa/inet.h>
   static uint64_t be64(uint64_t x) { return __builtin_bswap64(x); }
#else
   static uint64_t be64(uint64_t x) {
       return ((x & 0xFF00000000000000ULL) >> 56) |
              ((x & 0x00FF000000000000ULL) >> 40) |
              ((x & 0x0000FF0000000000ULL) >> 24) |
              ((x & 0x000000FF00000000ULL) >> 8)  |
              ((x & 0x00000000FF000000ULL) << 8)  |
              ((x & 0x0000000000FF0000ULL) << 24) |
              ((x & 0x000000000000FF00ULL) << 40) |
              ((x & 0x00000000000000FFULL) << 56);
   }
   #include <netinet/in.h>
#endif

// ============================================================
// ITCH MESSAGE STRUCTS (all fields big-endian in the wire format)
// Using __attribute__((packed)) to prevent padding bytes.
// ============================================================

#pragma pack(push, 1)

// Common header at the start of every ITCH message after the length field
struct ITCH_Header {
    uint8_t  msg_type;    // message type character
    uint16_t stock_locate;// NASDAQ internal stock index
    uint16_t tracking_num;// NASDAQ tracking number
    uint64_t timestamp;   // nanoseconds since midnight (big-endian)
};

// A = Add Order (no MPID) — new resting limit order
struct ITCH_AddOrder {
    uint8_t  msg_type;       // 'A'
    uint16_t stock_locate;
    uint16_t tracking_num;
    uint64_t timestamp;      // ns since midnight (big-endian)
    uint64_t order_ref_num;  // unique order reference number (big-endian)
    uint8_t  side;           // 'B' = buy, 'S' = sell
    uint32_t shares;         // quantity (big-endian)
    char     stock[8];       // symbol, space-padded
    uint32_t price;          // in 1/10000 of a cent (big-endian)
};
static_assert(sizeof(ITCH_AddOrder) == 36, "ITCH_AddOrder must be 36 bytes");

// E = Order Executed — a resting order was partially or fully filled
struct ITCH_OrderExecuted {
    uint8_t  msg_type;       // 'E'
    uint16_t stock_locate;
    uint16_t tracking_num;
    uint64_t timestamp;
    uint64_t order_ref_num;  // which resting order was executed
    uint32_t executed_shares;// how many shares were executed
    uint64_t match_number;   // unique match number for this execution
};
static_assert(sizeof(ITCH_OrderExecuted) == 31, "ITCH_OrderExecuted must be 31 bytes");

// X = Order Cancel — partial cancellation of a resting order
struct ITCH_OrderCancel {
    uint8_t  msg_type;       // 'X'
    uint16_t stock_locate;
    uint16_t tracking_num;
    uint64_t timestamp;
    uint64_t order_ref_num;  // which order
    uint32_t cancelled_shares;// how many shares were cancelled
};
static_assert(sizeof(ITCH_OrderCancel) == 23, "ITCH_OrderCancel must be 23 bytes");

// D = Order Delete — complete removal of a resting order
struct ITCH_OrderDelete {
    uint8_t  msg_type;       // 'D'
    uint16_t stock_locate;
    uint16_t tracking_num;
    uint64_t timestamp;
    uint64_t order_ref_num;  // which order to remove
};
static_assert(sizeof(ITCH_OrderDelete) == 19, "ITCH_OrderDelete must be 19 bytes");

// U = Order Replace — cancel existing order, add new one at new price/qty
struct ITCH_OrderReplace {
    uint8_t  msg_type;           // 'U'
    uint16_t stock_locate;
    uint16_t tracking_num;
    uint64_t timestamp;
    uint64_t orig_order_ref_num; // existing order to replace
    uint64_t new_order_ref_num;  // new order reference number
    uint32_t shares;             // new quantity
    uint32_t price;              // new price
};
static_assert(sizeof(ITCH_OrderReplace) == 35, "ITCH_OrderReplace must be 35 bytes");

// P = Non-displayable Trade (e.g., dark pool cross)
struct ITCH_Trade {
    uint8_t  msg_type;       // 'P'
    uint16_t stock_locate;
    uint16_t tracking_num;
    uint64_t timestamp;
    uint64_t order_ref_num;
    uint8_t  side;
    uint32_t shares;
    char     stock[8];
    uint32_t price;
    uint64_t match_number;
};

#pragma pack(pop)

// ============================================================
// PRICE CONVERSION
// ============================================================

// ITCH price is in 1/10000 of a cent = 1/1000000 of a dollar
// Our internal ticks = 1/10000 of a dollar
// So: internal_ticks = itch_price / 100
static int64_t itch_price_to_ticks(uint32_t itch_price_be) {
    uint32_t itch_price = ntohl(itch_price_be);  // byte swap
    return static_cast<int64_t>(itch_price) / 100;
}

static double itch_price_to_dollars(uint32_t itch_price_be) {
    return static_cast<double>(ntohl(itch_price_be)) / 10000.0;
}

// ============================================================
// RESTING ORDER (for our internal book state)
// ============================================================

struct RestingOrder {
    uint64_t order_ref_num;
    char     side;          // 'B' or 'S'
    int32_t  shares;
    int64_t  price_ticks;
    char     stock[9];      // null-terminated
};

// ============================================================
// ITCH FEED HANDLER — processes a stream of ITCH messages
// ============================================================

class ITCHFeedHandler {
public:
    struct Stats {
        int adds      = 0;
        int executes  = 0;
        int cancels   = 0;
        int deletes   = 0;
        int replaces  = 0;
        int trades    = 0;
        int unknown   = 0;
    };

    // Process a single ITCH message starting at 'buf'
    // Returns number of bytes consumed, or 0 on error
    int process_message(const uint8_t* buf, int buf_len) {
        if (buf_len < 1) return 0;

        uint8_t msg_type = buf[0];

        switch (msg_type) {
            case 'A': return process_add_order(buf, buf_len);
            case 'E': return process_executed(buf, buf_len);
            case 'X': return process_cancel(buf, buf_len);
            case 'D': return process_delete(buf, buf_len);
            case 'U': return process_replace(buf, buf_len);
            case 'P': stats_.trades++; return sizeof(ITCH_Trade);
            case 'S': case 'R': case 'H': case 'Q': case 'B': case 'I':
                return -1;  // skip: caller should skip based on known lengths
            default:
                stats_.unknown++;
                return -1;
        }
    }

    const Stats& stats() const { return stats_; }

    // Look up a resting order by reference number
    const RestingOrder* find_order(uint64_t ref) const {
        auto it = orders_.find(ref);
        if (it == orders_.end()) return nullptr;
        return &it->second;
    }

    int order_count() const { return static_cast<int>(orders_.size()); }

private:
    Stats stats_;
    std::unordered_map<uint64_t, RestingOrder> orders_;  // ref → order

    int process_add_order(const uint8_t* buf, int len) {
        if (len < (int)sizeof(ITCH_AddOrder)) return 0;
        const auto* msg = reinterpret_cast<const ITCH_AddOrder*>(buf);

        uint64_t ref  = be64(msg->order_ref_num);
        int32_t  qty  = static_cast<int32_t>(ntohl(msg->shares));
        int64_t  px   = itch_price_to_ticks(msg->price);  // price already BE, function swaps

        RestingOrder o{};
        o.order_ref_num = ref;
        o.side          = static_cast<char>(msg->side);
        o.shares        = qty;
        o.price_ticks   = px;
        memcpy(o.stock, msg->stock, 8);
        o.stock[8] = '\0';

        orders_[ref] = o;
        stats_.adds++;
        return sizeof(ITCH_AddOrder);
    }

    int process_executed(const uint8_t* buf, int len) {
        if (len < (int)sizeof(ITCH_OrderExecuted)) return 0;
        const auto* msg = reinterpret_cast<const ITCH_OrderExecuted*>(buf);

        uint64_t ref  = be64(msg->order_ref_num);
        int32_t  exec = static_cast<int32_t>(ntohl(msg->executed_shares));

        auto it = orders_.find(ref);
        if (it != orders_.end()) {
            it->second.shares -= exec;
            if (it->second.shares <= 0) orders_.erase(it);  // fully filled
        }
        stats_.executes++;
        return sizeof(ITCH_OrderExecuted);
    }

    int process_cancel(const uint8_t* buf, int len) {
        if (len < (int)sizeof(ITCH_OrderCancel)) return 0;
        const auto* msg = reinterpret_cast<const ITCH_OrderCancel*>(buf);

        uint64_t ref      = be64(msg->order_ref_num);
        int32_t  cancelled = static_cast<int32_t>(ntohl(msg->cancelled_shares));

        auto it = orders_.find(ref);
        if (it != orders_.end()) {
            it->second.shares -= cancelled;
            if (it->second.shares <= 0) orders_.erase(it);
        }
        stats_.cancels++;
        return sizeof(ITCH_OrderCancel);
    }

    int process_delete(const uint8_t* buf, int len) {
        if (len < (int)sizeof(ITCH_OrderDelete)) return 0;
        const auto* msg = reinterpret_cast<const ITCH_OrderDelete*>(buf);

        uint64_t ref = be64(msg->order_ref_num);
        orders_.erase(ref);
        stats_.deletes++;
        return sizeof(ITCH_OrderDelete);
    }

    int process_replace(const uint8_t* buf, int len) {
        if (len < (int)sizeof(ITCH_OrderReplace)) return 0;
        const auto* msg = reinterpret_cast<const ITCH_OrderReplace*>(buf);

        uint64_t old_ref = be64(msg->orig_order_ref_num);
        uint64_t new_ref = be64(msg->new_order_ref_num);
        int32_t  new_qty = static_cast<int32_t>(ntohl(msg->shares));
        int64_t  new_px  = itch_price_to_ticks(msg->price);

        auto it = orders_.find(old_ref);
        if (it != orders_.end()) {
            RestingOrder updated = it->second;
            updated.order_ref_num = new_ref;
            updated.shares        = new_qty;
            updated.price_ticks   = new_px;
            orders_.erase(it);
            orders_[new_ref] = updated;
        }
        stats_.replaces++;
        return sizeof(ITCH_OrderReplace);
    }
};

// ============================================================
// BUILD SYNTHETIC ITCH MESSAGES FOR TESTING
// ============================================================

// Helper: write a uint32_t in big-endian into a byte buffer at offset
static void write_be32(uint8_t* buf, int offset, uint32_t val) {
    buf[offset+0] = (val >> 24) & 0xFF;
    buf[offset+1] = (val >> 16) & 0xFF;
    buf[offset+2] = (val >>  8) & 0xFF;
    buf[offset+3] = (val >>  0) & 0xFF;
}

static void write_be64(uint8_t* buf, int offset, uint64_t val) {
    for (int i = 7; i >= 0; --i, val >>= 8) buf[offset+i] = val & 0xFF;
}

// Build a synthetic AddOrder message
std::vector<uint8_t> make_add_order(uint64_t ref, char side, uint32_t shares,
                                     const char* stock, uint32_t price_itch) {
    ITCH_AddOrder msg{};
    msg.msg_type    = 'A';
    msg.stock_locate = htons(1);
    msg.tracking_num = htons(0);
    write_be64(reinterpret_cast<uint8_t*>(&msg), 3, 9000000000ULL);  // timestamp ns
    write_be64(reinterpret_cast<uint8_t*>(&msg), 11, ref);
    msg.side = static_cast<uint8_t>(side);
    write_be32(reinterpret_cast<uint8_t*>(&msg), 20, shares);
    memcpy(msg.stock, stock, 8);
    write_be32(reinterpret_cast<uint8_t*>(&msg), 32, price_itch);

    std::vector<uint8_t> buf(sizeof(msg));
    memcpy(buf.data(), &msg, sizeof(msg));
    return buf;
}

// ============================================================
// MAIN
// ============================================================

int main() {
    std::cout << "=== ITCH 5.0 Message Parsing ===\n";

    // Verify struct sizes (critical for correct parsing)
    std::cout << "  sizeof(ITCH_AddOrder):      " << sizeof(ITCH_AddOrder) << " bytes\n";
    std::cout << "  sizeof(ITCH_OrderExecuted): " << sizeof(ITCH_OrderExecuted) << " bytes\n";
    std::cout << "  sizeof(ITCH_OrderCancel):   " << sizeof(ITCH_OrderCancel) << " bytes\n";
    std::cout << "  sizeof(ITCH_OrderDelete):   " << sizeof(ITCH_OrderDelete) << " bytes\n";
    std::cout << "  sizeof(ITCH_OrderReplace):  " << sizeof(ITCH_OrderReplace) << " bytes\n";

    // -------------------------------------------------------
    // PRICE CONVERSION DEMO
    // -------------------------------------------------------

    std::cout << "\n=== ITCH price conversion ===\n";

    // $182.50 in ITCH units = 182.50 * 10000 (cents) * 100 (1/100 cent) = 182500000
    uint32_t itch_price = 182500000;
    uint32_t itch_price_be = htonl(itch_price);  // convert to big-endian for storage

    std::cout << "  ITCH raw: " << itch_price << "\n";
    std::cout << "  In dollars: $" << itch_price / 10000.0 << "\n";
    std::cout << "  In ticks (our format, ×10000 of dollar): " << itch_price / 100 << "\n";

    // -------------------------------------------------------
    // SIMULATE A FEED: ADD → EXECUTE → DELETE
    // -------------------------------------------------------

    std::cout << "\n=== Feed simulation ===\n";

    ITCHFeedHandler handler;

    // Synthetic message stream
    // Add order: ref=1001, BUY, 500 shares SPY, $182.50
    auto add1 = make_add_order(1001, 'B', 500, "SPY     ",
                                htonl(182500000));  // price already as int; htonl for BE
    handler.process_message(add1.data(), static_cast<int>(add1.size()));
    std::cout << "  Added order 1001: BUY 500 SPY @ $182.50\n";

    // Add order: ref=1002, SELL, 300 shares SPY, $182.75
    auto add2 = make_add_order(1002, 'S', 300, "SPY     ",
                                htonl(182750000));
    handler.process_message(add2.data(), static_cast<int>(add2.size()));
    std::cout << "  Added order 1002: SELL 300 SPY @ $182.75\n";

    // Execute 200 shares from order 1001
    {
        ITCH_OrderExecuted exec{};
        exec.msg_type = 'E';
        exec.stock_locate  = htons(1);
        exec.tracking_num  = htons(0);
        write_be64(reinterpret_cast<uint8_t*>(&exec), 3, 9000001000ULL);
        write_be64(reinterpret_cast<uint8_t*>(&exec), 11, 1001ULL);
        write_be32(reinterpret_cast<uint8_t*>(&exec), 19, 200);
        write_be64(reinterpret_cast<uint8_t*>(&exec), 23, 9999ULL);

        handler.process_message(reinterpret_cast<uint8_t*>(&exec), sizeof(exec));
        std::cout << "  Executed 200 from order 1001 (300 remain)\n";
    }

    // Delete order 1002 completely
    {
        ITCH_OrderDelete del{};
        del.msg_type = 'D';
        del.stock_locate = htons(1);
        del.tracking_num = htons(0);
        write_be64(reinterpret_cast<uint8_t*>(&del), 3, 9000002000ULL);
        write_be64(reinterpret_cast<uint8_t*>(&del), 11, 1002ULL);

        handler.process_message(reinterpret_cast<uint8_t*>(&del), sizeof(del));
        std::cout << "  Deleted order 1002 (fully cancelled)\n";
    }

    // -------------------------------------------------------
    // VERIFY STATE
    // -------------------------------------------------------

    std::cout << "\n=== Book state after updates ===\n";
    std::cout << "  Total resting orders: " << handler.order_count() << "\n";

    const RestingOrder* o1001 = handler.find_order(1001);
    if (o1001) {
        std::cout << "  Order 1001: side=" << o1001->side
                  << " shares=" << o1001->shares
                  << " price_ticks=" << o1001->price_ticks
                  << " ($" << o1001->price_ticks / 10000.0 << ")\n";
    }

    const RestingOrder* o1002 = handler.find_order(1002);
    std::cout << "  Order 1002 exists: " << (o1002 ? "YES (bug!)" : "NO (correct)") << "\n";

    // -------------------------------------------------------
    // STATS
    // -------------------------------------------------------

    auto& s = handler.stats();
    std::cout << "\n=== Feed handler stats ===\n";
    std::cout << "  Adds:     " << s.adds     << "\n";
    std::cout << "  Executes: " << s.executes << "\n";
    std::cout << "  Cancels:  " << s.cancels  << "\n";
    std::cout << "  Deletes:  " << s.deletes  << "\n";
    std::cout << "  Replaces: " << s.replaces << "\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      The NASDAQ TotalView-ITCH binary file contains a full day of
      order book events for all NASDAQ-listed symbols. Processing it:
        1. Open a .bin file (gzipped usually, ~5-10GB per day per exchange)
        2. Read messages sequentially: length(2 bytes BE) + payload
        3. Call process_message() for each payload
        4. Maintain the order book using L54's OrderBook class
        5. At each Add/Execute/Delete, update the book and run strategy

      ITCH data is free from ftp://emi.nasdaq.com/ITCH/ (historical samples).
      One second of NASDAQ trading: ~50,000-200,000 ITCH messages.
      The parser MUST complete each message in <500ns to keep up.
    */
}
