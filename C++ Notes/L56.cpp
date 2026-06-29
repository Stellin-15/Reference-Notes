// ============================================================
// L56: FIX Protocol Parsing
// ============================================================
// WHAT: FIX (Financial Information eXchange) is the universal
//       order entry protocol used by most exchanges and brokers.
//       It uses a tag=value format delimited by ASCII 0x01 (SOH).
//       This lesson covers parsing incoming FIX messages (execution
//       reports) and building outgoing FIX messages (new orders,
//       cancels). Uses std::string_view for zero-copy parsing.
// WHY (TRADING): You WILL encounter FIX. Every prime broker,
//   most exchanges, and all algo-trading platforms speak FIX.
//   FIX 4.2 / 4.4 for equities. FIX 5.0 / FIXT for futures.
//   FIX parsing must be fast: 10µs parsing on a 10µs hot path
//   is unacceptable. We use string_view (no copies) and manual
//   scanning instead of std::string::find (avoids allocation).
// PHASE: Trading Systems Implementation
// ============================================================

/*
  CONCEPT OVERVIEW:

  FIX MESSAGE FORMAT:
    8=FIX.4.2|9=176|35=D|49=CLIENT|56=EXCHANGE|34=1|52=20231201-09:30:00.123|
    11=ORD001|21=1|55=SPY|54=1|60=20231201-09:30:00.123|38=100|40=2|44=182.50|
    10=078|
    (| represents SOH = ASCII character 0x01)

    Key tags:
      8  = BeginString      (FIX.4.2, FIX.4.4, FIXT.1.1)
      9  = BodyLength       (byte count from tag 35 to checksum delimiter)
      10 = CheckSum         (3-digit modulo 256 sum of all bytes)
      11 = ClOrdID          (client order ID, must be unique per session)
      21 = HandlInst        (1=automated, 2=semi-auto, 3=manual)
      34 = MsgSeqNum        (monotonic message sequence number)
      35 = MsgType          (D=new order, F=cancel, 8=exec report, etc.)
      38 = OrderQty         (quantity)
      40 = OrdType          (1=market, 2=limit, 3=stop, etc.)
      44 = Price            (limit price as decimal string)
      49 = SenderCompID     (who sent this)
      52 = SendingTime      (UTC timestamp)
      54 = Side             (1=buy, 2=sell)
      55 = Symbol           (ticker symbol)
      56 = TargetCompID     (recipient)
      58 = Text             (free-form text, e.g. rejection reason)
      60 = TransactTime     (transaction timestamp)

  MESSAGE TYPES (MsgType, tag 35):
    'D'  = NewOrderSingle      (client → exchange: submit order)
    'F'  = OrderCancelRequest  (client → exchange: cancel order)
    'G'  = OrderCancelReplaceRequest (modify)
    '8'  = ExecutionReport     (exchange → client: fill, reject, ack)
    '0'  = Heartbeat           (keep-alive every 30 seconds)
    'A'  = Logon               (session start)
    '5'  = Logout              (session end)
    '9'  = OrderCancelReject   (cancel was rejected)

  EXECUTION REPORT (35=8) KEY FIELDS:
    37 = OrderID              (exchange-assigned order ID)
    11 = ClOrdID              (our ClOrdID, echoed back)
    39 = OrdStatus            (0=new, 1=partial, 2=filled, 4=cancelled, 8=rejected)
    14 = CumQty               (total filled so far)
    32 = LastQty              (qty filled in this report)
    31 = LastPx               (price of this fill)
    151= LeavesQty            (remaining open qty)
    150= ExecType             (0=new, 1=partial, 2=fill, 4=cancel, 8=reject)
    58 = Text                 (rejection reason if 39=8)

  CHECKSUM:
    Sum of all byte values in the message (except tag 10= itself),
    modulo 256, formatted as 3-digit zero-padded decimal.
    10=078|  → checksum is 78

  PARSING STRATEGY:
    Incoming: use string_view to scan tag=value pairs without copying.
    Outgoing: use a pre-allocated char buffer and write directly.
    Avoid: std::string construction, std::stoi on hot path (use manual atoi).

  COMMON MISTAKES:
    - Using std::string instead of string_view for field values (heap alloc)
    - Parsing price with std::stod (slow, locale-dependent)
    - Forgetting the SOH (0x01) delimiter — printing with '|' but sending 0x01
    - Not validating checksum on received messages
    - Reusing ClOrdID (must be unique per session)
    - Not handling sequence number gaps (triggers resend request)
*/

#include <iostream>
#include <string>
#include <string_view>
#include <cstdint>
#include <cstring>
#include <cassert>
#include <optional>
#include <array>
#include <vector>
#include <charconv>   // std::from_chars (fast, no locale, no exception)

// FIX delimiter: ASCII SOH (Start Of Header) = 0x01
// In examples below we use '|' for readability; real messages use '\x01'
constexpr char FIX_SOH     = '\x01';
constexpr char FIX_SOH_DISPLAY = '|';  // display substitute

// ============================================================
// FAST PARSING HELPERS (no malloc, no exceptions, no locale)
// ============================================================

// Parse integer from string_view in-place using std::from_chars
// Returns 0 on failure (sufficient for tags where 0 means unset)
static int64_t sv_to_int(std::string_view sv) {
    int64_t result = 0;
    std::from_chars(sv.data(), sv.data() + sv.size(), result);
    return result;
}

// Parse double from string_view using std::from_chars (C++17)
// Falls back to 0.0 on failure
static double sv_to_double(std::string_view sv) {
    double result = 0.0;
#if defined(__cpp_lib_to_chars) && __cpp_lib_to_chars >= 201611L
    std::from_chars(sv.data(), sv.data() + sv.size(), result);
#else
    // Fallback: manual parse (avoid std::stod — locale-dependent)
    // This is simplified; production uses a purpose-built parser
    result = std::stod(std::string(sv));
#endif
    return result;
}

// Compute FIX checksum: sum of all bytes mod 256
static uint8_t fix_checksum(std::string_view msg) {
    uint32_t sum = 0;
    for (char c : msg) sum += static_cast<uint8_t>(c);
    return static_cast<uint8_t>(sum & 0xFF);
}

// ============================================================
// PARSED FIX FIELD — lightweight view into the raw message
// ============================================================

struct FIXField {
    int          tag;    // tag number (e.g. 35, 49, 55)
    std::string_view value;  // view into the original message buffer (no copy!)
};

// ============================================================
// FIX MESSAGE PARSER — zero-copy field extraction
// ============================================================

class FIXParser {
public:
    // Parse all fields from a FIX message string.
    // The string MUST remain alive while fields are accessed (string_view!).
    // Separator: use SOH for real messages, '|' for testing.
    void parse(std::string_view msg, char sep = FIX_SOH) {
        fields_.clear();
        size_t pos = 0;
        while (pos < msg.size()) {
            // Find '=' separating tag from value
            size_t eq = msg.find('=', pos);
            if (eq == std::string_view::npos) break;

            // Find field delimiter (SOH)
            size_t end = msg.find(sep, eq + 1);
            if (end == std::string_view::npos) end = msg.size();

            std::string_view tag_sv  = msg.substr(pos, eq - pos);
            std::string_view val_sv  = msg.substr(eq + 1, end - eq - 1);

            int tag = static_cast<int>(sv_to_int(tag_sv));
            if (tag > 0) fields_.push_back({tag, val_sv});

            pos = end + 1;  // skip past the separator
        }
    }

    // Get value for a tag. Returns empty string_view if not found.
    std::string_view get(int tag) const {
        for (const auto& f : fields_) {
            if (f.tag == tag) return f.value;
        }
        return {};
    }

    // Returns true if tag is present
    bool has(int tag) const { return !get(tag).empty(); }

    // Convenience accessors
    std::string_view msg_type()  const { return get(35); }  // '8', 'D', etc.
    std::string_view cl_ord_id() const { return get(11); }
    std::string_view symbol()    const { return get(55); }
    std::string_view text()      const { return get(58); }
    int64_t          qty()       const { return sv_to_int(get(38)); }
    int64_t          cum_qty()   const { return sv_to_int(get(14)); }
    int64_t          last_qty()  const { return sv_to_int(get(32)); }
    int64_t          leaves_qty()const { return sv_to_int(get(151)); }
    double           price()     const { return sv_to_double(get(44)); }
    double           last_px()   const { return sv_to_double(get(31)); }
    int              ord_status()const { return static_cast<int>(sv_to_int(get(39))); }
    int              exec_type() const { return static_cast<int>(sv_to_int(get(150))); }
    int              side()      const { return static_cast<int>(sv_to_int(get(54))); }

    const std::vector<FIXField>& fields() const { return fields_; }
    size_t field_count() const { return fields_.size(); }

private:
    std::vector<FIXField> fields_;
};

// ============================================================
// FIX MESSAGE BUILDER — writes directly to a char buffer
// ============================================================

class FIXBuilder {
public:
    explicit FIXBuilder(char* buf, size_t cap)
        : buf_(buf), cap_(cap), len_(0) {}

    // Append tag=value| for various value types
    FIXBuilder& add(int tag, std::string_view val, char sep = FIX_SOH) {
        len_ += snprintf(buf_ + len_, cap_ - len_, "%d=%.*s%c",
                         tag, (int)val.size(), val.data(), sep);
        return *this;
    }
    FIXBuilder& add(int tag, int64_t val, char sep = FIX_SOH) {
        len_ += snprintf(buf_ + len_, cap_ - len_, "%d=%lld%c", tag, (long long)val, sep);
        return *this;
    }
    FIXBuilder& add(int tag, double val, int decimals, char sep = FIX_SOH) {
        len_ += snprintf(buf_ + len_, cap_ - len_, "%d=%.*f%c", tag, decimals, val, sep);
        return *this;
    }

    size_t len()  const { return len_; }
    std::string_view view() const { return {buf_, len_}; }

private:
    char*  buf_;
    size_t cap_;
    size_t len_;
};

// ============================================================
// BUILD A NewOrderSingle (35=D)
// ============================================================

// Returns length of message written into buf
size_t build_new_order_single(char* buf, size_t cap,
                               const std::string& cl_ord_id,
                               const std::string& symbol,
                               int side,           // 1=buy, 2=sell
                               int ord_type,       // 1=market, 2=limit
                               double price,
                               int64_t qty,
                               const std::string& sender_comp_id,
                               const std::string& target_comp_id,
                               int64_t seq_num) {
    // Step 1: build body (everything between tag 9 and tag 10)
    char body[1024];
    FIXBuilder b(body, sizeof(body));
    b.add(35, "D")                    // MsgType = NewOrderSingle
     .add(49, sender_comp_id)         // SenderCompID
     .add(56, target_comp_id)         // TargetCompID
     .add(34, seq_num)                // MsgSeqNum
     .add(52, "20231201-09:30:00.000")// SendingTime (simplified)
     .add(11, cl_ord_id)              // ClOrdID
     .add(21, 1LL)                    // HandlInst = Automated
     .add(55, symbol)                 // Symbol
     .add(54, (int64_t)side)          // Side
     .add(60, "20231201-09:30:00.000")// TransactTime
     .add(38, qty)                    // OrderQty
     .add(40, (int64_t)ord_type);     // OrdType

    if (ord_type == 2 && price > 0.0)
        b.add(44, price, 2);          // Price (only for limit orders)

    // Step 2: prepend header with BodyLength
    FIXBuilder header(buf, cap);
    header.add(8, "FIX.4.2")          // BeginString
          .add(9, (int64_t)b.len());  // BodyLength

    // Copy body into buf after header
    memcpy(buf + header.len(), body, b.len());
    size_t total_body_end = header.len() + b.len();

    // Step 3: compute checksum over entire message so far
    uint8_t cs = fix_checksum({buf, total_body_end});

    // Step 4: append checksum
    FIXBuilder tail(buf + total_body_end, cap - total_body_end);
    tail.add(10, (int64_t)cs);  // CheckSum (must be exactly 3 digits in practice)

    return total_body_end + tail.len();
}

// ============================================================
// PROCESS AN EXECUTION REPORT (35=8)
// ============================================================

void process_exec_report(const FIXParser& msg) {
    auto exec_type  = msg.exec_type();
    auto ord_status = msg.ord_status();
    auto cl_ord_id  = msg.cl_ord_id();
    auto sym        = msg.symbol();
    auto last_qty   = msg.last_qty();
    auto last_px    = msg.last_px();
    auto leaves_qty = msg.leaves_qty();
    auto cum_qty    = msg.cum_qty();

    std::cout << "  ExecReport: ClOrdID=" << cl_ord_id
              << " Symbol=" << sym
              << " OrdStatus=" << ord_status
              << " ExecType=" << exec_type
              << "\n";

    if (exec_type == 2 || exec_type == 1) {
        // 2=Fill, 1=Partial Fill
        std::cout << "    Fill: " << last_qty << " @ $" << last_px
                  << " | CumQty=" << cum_qty
                  << " | LeavesQty=" << leaves_qty << "\n";
    } else if (exec_type == 8) {
        // 8=Rejected
        std::cout << "    Rejected: " << msg.text() << "\n";
    } else if (exec_type == 4) {
        std::cout << "    Cancelled\n";
    } else if (exec_type == 0) {
        std::cout << "    New (acknowledged)\n";
    }
}

// ============================================================
// MAIN
// ============================================================

int main() {
    // -------------------------------------------------------
    // PARSE AN EXECUTION REPORT
    // -------------------------------------------------------

    std::cout << "=== Parsing FIX Execution Report ===\n";

    // Using '|' as separator for readability (real FIX uses '\x01')
    std::string exec_msg =
        "8=FIX.4.2|9=200|35=8|49=EXCHANGE|56=CLIENT|34=5|"
        "52=20231201-09:30:01.456|"
        "11=ORD001|37=EXCH-99001|39=1|150=1|"   // OrdStatus=1(partial), ExecType=1(partial)
        "55=SPY|54=1|38=100|32=30|31=182.50|"   // filled 30@182.50
        "14=30|151=70|"                           // cumQty=30, leavesQty=70
        "10=123|";

    FIXParser parser;
    parser.parse(exec_msg, '|');

    std::cout << "  Fields parsed: " << parser.field_count() << "\n";
    std::cout << "  MsgType: " << parser.msg_type() << "\n";
    std::cout << "  Symbol:  " << parser.symbol() << "\n";
    std::cout << "  Qty:     " << parser.qty() << "\n";
    std::cout << "  LastPx:  $" << parser.last_px() << "\n";
    std::cout << "  LastQty: " << parser.last_qty() << "\n";
    std::cout << "  CumQty:  " << parser.cum_qty() << "\n";
    std::cout << "  Leaves:  " << parser.leaves_qty() << "\n";
    std::cout << "\n";

    process_exec_report(parser);

    // -------------------------------------------------------
    // BUILD A NEW ORDER SINGLE
    // -------------------------------------------------------

    std::cout << "\n=== Building NewOrderSingle (35=D) ===\n";

    char order_buf[2048];
    size_t len = build_new_order_single(
        order_buf, sizeof(order_buf),
        "ORD002",       // ClOrdID
        "SPY",          // Symbol
        1,              // Side: 1=buy
        2,              // OrdType: 2=limit
        182.50,         // Price
        100,            // Qty
        "ALGO_TRADER",  // SenderCompID
        "NYSE",         // TargetCompID
        2               // SeqNum
    );

    // Display with | for readability
    std::string display(order_buf, len);
    for (char& c : display) if (c == FIX_SOH) c = FIX_SOH_DISPLAY;
    std::cout << "  FIX: " << display << "\n";
    std::cout << "  Len: " << len << " bytes\n";

    // -------------------------------------------------------
    // PARSE ALL FIELDS (debugging)
    // -------------------------------------------------------

    std::cout << "\n=== All fields in exec report ===\n";
    for (const auto& f : parser.fields()) {
        std::cout << "  Tag " << f.tag << " = " << f.value << "\n";
    }

    // -------------------------------------------------------
    // PERFORMANCE: how fast can we parse FIX messages?
    // -------------------------------------------------------

    std::cout << "\n=== Performance: FIX parsing ===\n";

    constexpr int REPS = 1000000;
    FIXParser bench_parser;

    auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < REPS; ++i) {
        bench_parser.parse(exec_msg, '|');
        // Access a field to prevent dead-code elimination
        volatile auto side = bench_parser.side();
        (void)side;
    }
    auto t1 = std::chrono::steady_clock::now();

    uint64_t ns = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());

    std::cout << "  " << REPS << " parses in " << ns / 1000 << "µs\n";
    std::cout << "  Per parse: " << ns / REPS << "ns\n";
    std::cout << "  (includes vector resize — pre-reserve() improves this)\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Your FIX gateway (order management) connects to the exchange via TCP.
      Incoming execution reports are parsed and dispatched:
        void on_fix_message(const char* buf, int len) {
            FIXParser parser;
            parser.parse(std::string_view(buf, len));
            auto msg_type = parser.msg_type();
            if (msg_type == "8")       { on_exec_report(parser); }
            else if (msg_type == "9")  { on_cancel_reject(parser); }
            else if (msg_type == "0")  { send_heartbeat(); }
            else if (msg_type == "5")  { reconnect(); }
        }

      FIX parsing must complete in <10µs. Our string_view approach
      avoids all heap allocation during parsing. The only allocation
      is the vector of FIXField objects — which can be replaced with
      a stack array for the hot path if needed.
    */
}

// need chrono include
#include <chrono>
