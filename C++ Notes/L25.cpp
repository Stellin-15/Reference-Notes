// ============================================================
// L25: constexpr and Compile-Time Computation
// ============================================================
// WHAT: constexpr moves computation from runtime to compile time.
//       The result is baked directly into the executable — the
//       CPU never has to compute it, not even once.
// WHY (TRADING): Protocol field offsets, tick sizes, lot sizes,
//   fee rate lookup tables, price precision constants — all of
//   these are known before the program starts. Making them
//   constexpr means zero runtime cost. Compile-time lookup
//   tables (like a 256-entry message type dispatch table) let
//   the CPU jump to the right handler in a single instruction
//   with no branching and no cache misses.
// PHASE: Modern C++
// ============================================================

/*
  CONCEPT OVERVIEW:

  CONST vs CONSTEXPR:
    const:      value cannot change at runtime, but might be computed at runtime
    constexpr:  value MUST be computable at compile time — baked into binary

    const double fee = config.load("fee");     // computed at runtime, then fixed
    constexpr double TICK_SIZE = 0.01;         // baked at compile time (zero runtime cost)

  CONSTEXPR VARIABLES:
    constexpr int N = 1024;            // compile-time constant
    int arr[N];                        // OK: N is compile-time → valid array size
    constexpr int M = get_value();     // ERROR: get_value() must also be constexpr

  CONSTEXPR FUNCTIONS (C++11+):
    constexpr int square(int x) { return x * x; }
    constexpr int s = square(5);   // evaluated at compile time → s=25 baked in binary
    int runtime_n = get_n();
    int s2 = square(runtime_n);    // evaluated at runtime (input not constexpr)
    Same function, used both ways — compiler decides based on context.

  CONSTEVAL (C++20):
    consteval int square(int x) { return x * x; }
    FORCES compile-time evaluation. Cannot be called with a runtime argument.
    Use for: pure compile-time tools (like static assertions, template helpers)

  IF CONSTEXPR (C++17):
    template<typename T>
    void process(T val) {
        if constexpr (std::is_integral_v<T>) {
            // This branch compiled only for integral T
        } else {
            // This branch compiled only for non-integral T
        }
    }
    Branches that are not taken are DISCARDED at compile time.
    No runtime cost, no dead code. Used in template specialization.

  CONSTEXPR LOOKUP TABLES:
    Lookup tables computed at compile time — no initialization cost at startup.
    Common in: protocol parsers (byte → message type), fee schedules
    (volume tier → fee rate), market session masks (minute → is_open bool).

  STATIC_ASSERT:
    static_assert(condition, "message");
    Checked at COMPILE TIME — program fails to compile if condition is false.
    Use for: validating template arguments, checking struct sizes,
    ensuring constants are in valid ranges. Zero runtime cost.

  TRADING USE CASE:
    constexpr int64_t PRICE_PRECISION = 10000;     // 4 decimal places
    constexpr int64_t TICK_SIZE_TICKS = 1;         // 1 unit = 0.0001 dollars
    constexpr int     MAX_ORDER_LEVELS = 10;
    constexpr double  MAKER_FEE_RATE = 0.0002;     // 0.02%

    // Compile-time fee table: pre-computed for volume tiers 0-9
    constexpr std::array<double,10> FEE_TABLE = compute_fee_table();

  COMMON MISTAKES:
    - Calling non-constexpr functions inside constexpr functions
    - Using constexpr with types that have non-trivial runtime initialization
    - Expecting constexpr to always evaluate at compile time — it only guarantees
      it CAN, not that it WILL in all contexts (use consteval to force it)
    - Forgetting static_assert for template parameter constraints
*/

#include <iostream>
#include <array>
#include <cstdint>
#include <type_traits>  // std::is_integral_v

// ============================================================
// COMPILE-TIME CONSTANTS — the basics
// ============================================================

// Protocol and risk constants — evaluated at compile time, zero runtime cost
constexpr int64_t PRICE_PRECISION   = 10000;     // 4 decimal places (e.g. 1.0000)
constexpr int64_t TICK_SIZE_TICKS   = 1;         // minimum price increment
constexpr int32_t MAX_ORDER_QTY     = 10000;     // hard risk limit
constexpr int32_t MAX_POSITION      = 50000;     // max net position per symbol
constexpr double  MAKER_FEE_RATE    = 0.0002;    // 0.02% maker rebate/fee
constexpr double  TAKER_FEE_RATE    = 0.0005;    // 0.05% taker fee
constexpr int     BOOK_LEVELS       = 10;        // top-of-book levels to track
constexpr int     MAX_SYMBOLS       = 256;       // max symbols in our universe

// Static assert: validate constants at compile time — fails compilation if wrong
static_assert(MAX_ORDER_QTY > 0,       "Max order qty must be positive");
static_assert(MAX_POSITION > 0,        "Max position must be positive");
static_assert(MAKER_FEE_RATE >= 0.0,   "Fee rate cannot be negative");
static_assert(BOOK_LEVELS <= 20,       "Too many book levels");
static_assert((MAX_SYMBOLS & (MAX_SYMBOLS - 1)) == 0, "MAX_SYMBOLS must be power of 2");

// ============================================================
// CONSTEXPR FUNCTIONS
// ============================================================

// Convert dollars to ticks at compile time
constexpr int64_t dollars_to_ticks(double dollars) {
    return static_cast<int64_t>(dollars * PRICE_PRECISION);
}

// Convert ticks to dollars (display only — not for calculation)
constexpr double ticks_to_dollars(int64_t ticks) {
    return static_cast<double>(ticks) / PRICE_PRECISION;
}

// Calculate fee in ticks for a given notional
constexpr int64_t taker_fee_ticks(int64_t price_ticks, int32_t qty) {
    // fee = notional * fee_rate = price * qty * rate
    return static_cast<int64_t>(price_ticks * qty * TAKER_FEE_RATE);
}

// Compile-time power function
constexpr int64_t power(int64_t base, int exp) {
    int64_t result = 1;
    for (int i = 0; i < exp; ++i) result *= base;
    return result;
}

// Compile-time check if n is a power of 2
constexpr bool is_power_of_two(int n) {
    return n > 0 && (n & (n - 1)) == 0;
}

// ============================================================
// COMPILE-TIME LOOKUP TABLE — fee schedule by volume tier
// ============================================================

// Volume tiers: 10 tiers, fee decreases as volume increases
constexpr std::array<double, 10> compute_fee_schedule() {
    std::array<double, 10> fees{};
    for (int tier = 0; tier < 10; ++tier) {
        // Fee = base_fee * (1 - tier * 0.05): 0.50%, 0.45%, ..., 0.05%
        fees[tier] = 0.0050 - tier * 0.0005;
    }
    return fees;
}

// This table is computed AT COMPILE TIME — baked into the binary
constexpr auto FEE_SCHEDULE = compute_fee_schedule();

// ============================================================
// COMPILE-TIME MESSAGE TYPE TABLE
// ============================================================

// NASDAQ ITCH message types (subset): byte value → message name
// This is a 256-entry table built at compile time.
// At runtime: one array access to get the message name — no branches.

enum class ITCHMsgType : uint8_t {
    SYSTEM_EVENT  = 'S',
    ADD_ORDER     = 'A',
    ADD_ORDER_MPID= 'F',
    EXECUTE_ORDER = 'E',
    CANCEL_ORDER  = 'X',
    DELETE_ORDER  = 'D',
    REPLACE_ORDER = 'U',
    TRADE         = 'P',
    UNKNOWN       = 0
};

constexpr const char* itch_msg_name(uint8_t byte) {
    switch (byte) {
        case 'S': return "SystemEvent";
        case 'A': return "AddOrder";
        case 'F': return "AddOrderMPID";
        case 'E': return "ExecuteOrder";
        case 'X': return "CancelOrder";
        case 'D': return "DeleteOrder";
        case 'U': return "ReplaceOrder";
        case 'P': return "Trade";
        default:  return "Unknown";
    }
}

// ============================================================
// IF CONSTEXPR — compile-time branch selection in templates
// ============================================================

// Serialize a value to bytes differently based on its type.
// The if constexpr branches are eliminated at compile time —
// only the relevant branch is compiled into each instantiation.
template<typename T>
void serialize_field(T value, const char* field_name) {
    std::cout << "Field [" << field_name << "] = ";

    if constexpr (std::is_integral_v<T>) {
        // For integers: show as decimal and hex
        std::cout << value << " (int, hex=0x" << std::hex << value << std::dec << ")\n";
    } else if constexpr (std::is_floating_point_v<T>) {
        // For floats: show as decimal and in ticks
        std::cout << value << " (float, ticks=" << static_cast<int64_t>(value * PRICE_PRECISION) << ")\n";
    } else {
        // For anything else: just print
        std::cout << value << " (other)\n";
    }
}

// ============================================================
// CONSTEVAL — compile-time only (C++20)
// ============================================================

// This CAN ONLY be called with compile-time arguments.
// Calling with a runtime value is a compile error.
consteval int64_t make_price_constant(double dollars) {
    return static_cast<int64_t>(dollars * PRICE_PRECISION);
}

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // COMPILE-TIME CONSTANTS IN USE
    // -------------------------------------------------------

    std::cout << "=== Compile-time constants ===\n";
    std::cout << "Price precision:  " << PRICE_PRECISION    << " ticks/dollar\n";
    std::cout << "Max order qty:    " << MAX_ORDER_QTY      << " shares\n";
    std::cout << "Max position:     " << MAX_POSITION       << " shares\n";
    std::cout << "Maker fee rate:   " << MAKER_FEE_RATE     << " (" << MAKER_FEE_RATE*100 << "%)\n";
    std::cout << "Taker fee rate:   " << TAKER_FEE_RATE     << " (" << TAKER_FEE_RATE*100 << "%)\n";

    // -------------------------------------------------------
    // CONSTEXPR FUNCTIONS
    // -------------------------------------------------------

    std::cout << "\n=== constexpr functions ===\n";

    // Compile-time: result baked into binary (like a literal constant)
    constexpr int64_t limit_price = dollars_to_ticks(182.50);   // 1825000 at compile time
    constexpr int64_t tick_one    = dollars_to_ticks(0.0001);    // 1 tick
    std::cout << "$182.50 in ticks: " << limit_price << "\n";
    std::cout << "1 tick in ticks:  " << tick_one   << "\n";
    std::cout << "Back to dollars:  $" << ticks_to_dollars(limit_price) << "\n";

    // Fee calculation: both constexpr and runtime paths
    constexpr int64_t known_fee = taker_fee_ticks(1825000LL, 100);   // compile time
    std::cout << "Taker fee (100 @ 182.50): " << known_fee << " ticks = $"
              << ticks_to_dollars(known_fee) << "\n";

    // Runtime: still uses the same function
    int64_t runtime_price = 1830000LL;
    int32_t runtime_qty   = 500;
    int64_t runtime_fee   = taker_fee_ticks(runtime_price, runtime_qty);
    std::cout << "Taker fee (500 @ 183.00): " << runtime_fee << " ticks = $"
              << ticks_to_dollars(runtime_fee) << "\n";

    // Power of 2 check (compile-time)
    constexpr bool ring_size_ok = is_power_of_two(1024);
    static_assert(ring_size_ok, "Ring buffer size must be power of 2");
    std::cout << "1024 is power of 2: " << ring_size_ok << "\n";

    // -------------------------------------------------------
    // COMPILE-TIME FEE SCHEDULE
    // -------------------------------------------------------

    std::cout << "\n=== Compile-time fee schedule ===\n";
    std::cout << "Volume tier → fee rate:\n";
    for (int tier = 0; tier < 10; ++tier) {
        std::cout << "  Tier " << tier << ": " << FEE_SCHEDULE[tier] * 100 << " bps\n";
    }
    // FEE_SCHEDULE is in read-only memory — computed before main() even ran

    // -------------------------------------------------------
    // CONSTEXPR PRICE CONSTANTS
    // -------------------------------------------------------

    std::cout << "\n=== constexpr price constants ===\n";

    // These are resolved entirely at compile time
    constexpr int64_t PRICE_FLOOR   = make_price_constant(0.01);   // $0.01 minimum
    constexpr int64_t PRICE_CEILING = make_price_constant(999999.9999);  // $999,999.9999
    constexpr int64_t HALF_SPREAD   = dollars_to_ticks(0.0050);    // $0.005 half-spread

    std::cout << "Price floor:   " << PRICE_FLOOR   << " ticks\n";
    std::cout << "Price ceiling: " << PRICE_CEILING << " ticks\n";
    std::cout << "Half spread:   " << HALF_SPREAD   << " ticks\n";

    // -------------------------------------------------------
    // IF CONSTEXPR — type-aware serialization
    // -------------------------------------------------------

    std::cout << "\n=== if constexpr serialization ===\n";

    serialize_field(int64_t(1825000),  "price_ticks");
    serialize_field(int32_t(100),      "quantity");
    serialize_field(double(182.5000),  "display_price");
    serialize_field(uint8_t('A'),      "msg_type_byte");

    // -------------------------------------------------------
    // ITCH MESSAGE TYPE LOOKUP
    // -------------------------------------------------------

    std::cout << "\n=== Compile-time ITCH message dispatch ===\n";

    uint8_t incoming_bytes[] = {'A', 'E', 'D', 'P', 'X', 'Z'};  // Z is unknown
    for (uint8_t b : incoming_bytes) {
        std::cout << "Byte 0x" << std::hex << (int)b << std::dec
                  << " (" << (char)b << "): " << itch_msg_name(b) << "\n";
    }

    // -------------------------------------------------------
    // STATIC_ASSERT — compile-time validation
    // -------------------------------------------------------

    std::cout << "\n=== static_assert examples ===\n";

    // Validate struct layout for binary protocol compatibility
    struct OrderMsg {
        uint64_t timestamp;   // 8 bytes
        uint64_t order_id;    // 8 bytes
        int64_t  price;       // 8 bytes
        int32_t  qty;         // 4 bytes
        uint8_t  side;        // 1 byte
        uint8_t  type;        // 1 byte
        uint16_t _pad;        // 2 bytes padding (to align to 8-byte boundary)
    };  // total: 32 bytes

    static_assert(sizeof(OrderMsg) == 32, "OrderMsg must be 32 bytes (matches exchange protocol)");
    static_assert(offsetof(OrderMsg, price) == 16, "Price field must be at byte 16");
    std::cout << "OrderMsg size: " << sizeof(OrderMsg) << " bytes (protocol-correct)\n";
    std::cout << "Price offset:  " << offsetof(OrderMsg, price) << " bytes\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      A complete set of CME MDP3 protocol constants — all constexpr:

        namespace CME {
            constexpr int64_t PRICE_NULL      = INT64_MIN;      // "no price" sentinel
            constexpr int64_t PRICE_PRECISION = 1'000'000'000;  // 9 decimal places (Price9)
            constexpr uint32_t MAX_DEPTH      = 10;
            constexpr uint16_t TEMPLATE_ID_MD_INCREMENTAL = 32;
            constexpr uint16_t TEMPLATE_ID_SNAPSHOT       = 38;

            // Compile-time array of valid security types
            constexpr std::array<const char*, 5> SECURITY_TYPES = {
                "FUT", "OPT", "COMBO", "SPREAD", "INDEX"
            };

            // Price conversion: integer to display (constexpr for compile-time use)
            constexpr double to_display(int64_t price9) {
                return static_cast<double>(price9) / PRICE_PRECISION;
            }
        }

      Every field offset, every sentinel value, every protocol constant:
      constexpr. Zero startup cost. Zero runtime lookup.
    */
}
