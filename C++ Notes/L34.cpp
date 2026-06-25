// ============================================================
// L34: Type Traits, Concepts (C++20), and SFINAE
// ============================================================
// WHAT: Type traits let you query properties of types at
//       compile time. Concepts (C++20) let you constrain
//       templates with readable requirements. SFINAE is the
//       older mechanism for the same thing.
// WHY (TRADING): Generic trading code (RingBuffer<T>, ObjectPool<T>,
//   price converters) must work only with the right types.
//   Type traits and concepts let you:
//   - Reject wrong types at compile time (clear error messages)
//   - Select different implementations based on type properties
//   - Enforce invariants: "T must be trivially copyable" for
//     binary serialization of market data structs
//   - Write generic math that works for int, double, int64_t
//     but rejects std::string at compile time, not runtime.
// PHASE: Modern C++
// ============================================================

/*
  CONCEPT OVERVIEW:

  TYPE TRAITS (<type_traits>):
    Compile-time boolean/type queries about types.

    IDENTITY / CLASSIFICATION:
      is_same<T, U>           — T and U are the same type
      is_integral<T>          — int, char, bool, long, int64_t...
      is_floating_point<T>    — float, double, long double
      is_arithmetic<T>        — integral OR floating point
      is_pointer<T>           — T is a raw pointer
      is_reference<T>         — T is a reference
      is_const<T>             — T is const-qualified
      is_class<T>             — T is a class or struct
      is_enum<T>              — T is an enum
      is_void<T>              — T is void
      is_array<T>             — T is a C-array type

    OBJECT PROPERTIES:
      is_trivially_copyable<T>     — can memcpy safely (no vtable, no non-trivial copy)
      is_trivially_destructible<T> — destructor is trivial (no cleanup needed)
      is_standard_layout<T>        — C-compatible struct layout
      is_pod<T>                    — deprecated in C++20, was trivial + standard layout
      is_empty<T>                  — class with no non-static data members (EBO)

    CONSTRUCTION:
      is_constructible<T, Args...> — can construct T from Args
      is_default_constructible<T>  — T has a default constructor
      is_copy_constructible<T>     — T has a copy constructor
      is_move_constructible<T>     — T has a move constructor
      is_nothrow_move_constructible<T> — move constructor is noexcept

    MODIFIERS (type transformations):
      remove_const<T>     — strip const from T
      remove_reference<T> — strip & or && from T
      add_pointer<T>      — T*
      decay<T>            — what type T becomes when passed by value (strips const, &, arrays → ptr)
      underlying_type<E>  — underlying integer type of an enum class

    ACCESS:
      std::is_same<T,U>::value  — true/false
      std::is_integral_v<T>     — C++17 shorthand (::value built in)

  STATIC_ASSERT:
    static_assert(condition, "message");
    Fires at compile time if condition is false.
    Use to enforce constraints on template parameters.
    Zero runtime cost — it's a compile-time check only.

  SFINAE (Substitution Failure Is Not An Error):
    When template substitution fails (wrong type), the compiler silently removes
    that overload candidate instead of emitting an error.
    std::enable_if<condition, T> — provides type T only when condition is true.
    enable_if<false, T> → no type → overload removed → compilation continues.
    This is the pre-C++20 way to constrain templates.

  CONCEPTS (C++20 — preferred over SFINAE):
    Readable, composable, clear error messages.
    template <Numeric T>     — "T must satisfy the Numeric concept"
    requires <condition>     — inline requirement

    BUILT-IN CONCEPTS (<concepts> header):
      std::integral<T>           — any integer type
      std::floating_point<T>     — float, double, long double
      std::same_as<T, U>         — T and U are the same type
      std::convertible_to<T, U>  — T is convertible to U
      std::copyable<T>           — T can be copied
      std::movable<T>            — T can be moved
      std::regular<T>            — copyable + default constructible + equality comparable
      std::totally_ordered<T>    — supports <, >, <=, >=

    DEFINE A CONCEPT:
      template<typename T>
      concept MyConstraint = std::integral<T> && sizeof(T) >= 4;

  TRADING USE CASE:
    // Enforce that a price type is an integer (never float!)
    template <std::integral T>
    T dollars_to_ticks(double price, int precision) { return T(price * precision); }

    // Enforce that a struct can be binary-serialized (no pointers, no vtable)
    template <typename T>
    requires std::is_trivially_copyable_v<T>
    void write_binary(std::ofstream& f, const T& val) {
        f.write(reinterpret_cast<const char*>(&val), sizeof(T));
    }

  COMMON MISTAKES:
    - enable_if instead of concepts for new code (harder to read, worse errors)
    - static_assert with no message — always add a human-readable message
    - is_pod: deprecated in C++20, use is_trivially_copyable && is_standard_layout
    - Checking is_trivially_copyable on a struct that has a std::string member
      (std::string is NOT trivially copyable — it has a pointer and destructor)
*/

#include <iostream>
#include <type_traits>
#include <concepts>     // C++20 standard concepts
#include <cstdint>
#include <string>
#include <vector>
#include <cmath>

// ============================================================
// CUSTOM CONCEPTS — trading-specific constraints
// ============================================================

// A numeric type suitable for price/quantity math
template<typename T>
concept Numeric = std::integral<T> || std::floating_point<T>;

// An integer type that can represent prices as ticks (must be >= 32 bits)
template<typename T>
concept TickPrice = std::integral<T> && sizeof(T) >= 4;

// A type safe for binary serialization (memcpy-able)
template<typename T>
concept BinarySerializable = std::is_trivially_copyable_v<T>
                          && std::is_standard_layout_v<T>;

// ============================================================
// TRIVIALLY COPYABLE STRUCTS (OK for binary I/O)
// ============================================================

// OK: trivially copyable (POD-like)
struct Tick {
    uint64_t timestamp_ns;
    int64_t  price;
    int32_t  qty;
    // No std::string, no pointer, no virtual — memcpy-safe
};

// NOT trivially copyable: has std::string (which has a pointer + heap allocation)
struct BadTick {
    uint64_t    timestamp_ns;
    int64_t     price;
    std::string symbol;  // <-- std::string is NOT trivially copyable
};

// ============================================================
// FUNCTIONS USING CONCEPTS
// ============================================================

// Accepts only integer-based price types (TickPrice concept)
// Rejects float, double — floating-point tick prices are a bug
template<TickPrice T>
T dollars_to_ticks(double price, T precision) {
    return static_cast<T>(price * precision);
}

// Accepts any numeric type for general math
template<Numeric T>
T clamp(T val, T lo, T hi) {
    if (val < lo) return lo;
    if (val > hi) return hi;
    return val;
}

// Generic binary write — only compiles for BinarySerializable types
// If T has a std::string member, this fails to compile with a clear error
template<BinarySerializable T>
void describe_binary_layout(const std::string& name) {
    std::cout << "  " << name
              << ": sizeof=" << sizeof(T)
              << " trivially_copyable=true"
              << " standard_layout=true\n";
}

// ============================================================
// SFINAE — the old way (for reference; prefer concepts in new code)
// ============================================================

// enable_if: only enabled when T is integral
// The return type is either "T" (if integral) or "void" (removed from overload set)
template<typename T>
std::enable_if_t<std::is_integral_v<T>, T>
safe_add(T a, T b) {
    // Integer addition — check for overflow
    return a + b;
}

// enable_if: separate overload for floating point
template<typename T>
std::enable_if_t<std::is_floating_point_v<T>, T>
safe_add(T a, T b) {
    return a + b;  // float — no overflow check needed for this example
}

// ============================================================
// TYPE TRAIT QUERIES — runtime inspection for demonstration
// ============================================================

template<typename T>
void print_type_traits(const std::string& type_name) {
    std::cout << "  " << type_name << ":\n"
              << "    is_integral:          " << std::is_integral_v<T> << "\n"
              << "    is_floating_point:    " << std::is_floating_point_v<T> << "\n"
              << "    is_trivially_copyable:" << std::is_trivially_copyable_v<T> << "\n"
              << "    is_standard_layout:   " << std::is_standard_layout_v<T> << "\n"
              << "    sizeof:               " << sizeof(T) << " bytes\n";
}

// ============================================================
// IF CONSTEXPR — compile-time branch on type
// ============================================================

// Different behavior depending on whether T is integer or float
// if constexpr: the branch is selected at compile time (dead branch is not compiled)
template<Numeric T>
void print_price(T price) {
    if constexpr (std::is_integral_v<T>) {
        // Integer path: treat as ticks, convert to dollars for display
        std::cout << "  Tick price: " << price
                  << " (= $" << price / 10000.0 << ")\n";
    } else {
        // Float path: already in dollars
        std::cout << "  Dollar price: $" << price << "\n";
    }
}

// ============================================================
// STATIC ASSERT — enforce invariants on structs
// ============================================================

// Ensure Tick struct can be safely binary-serialized
static_assert(std::is_trivially_copyable_v<Tick>,
              "Tick must be trivially copyable for binary file I/O");
static_assert(std::is_standard_layout_v<Tick>,
              "Tick must be standard layout for C interop and binary I/O");
static_assert(sizeof(Tick) == 20,
              "Tick struct size changed — check alignment/padding in binary files");

// Ensure our fixed-width types are what we think they are
static_assert(sizeof(int64_t) == 8, "int64_t must be 8 bytes");
static_assert(sizeof(uint64_t) == 8, "uint64_t must be 8 bytes");
static_assert(sizeof(int32_t) == 4, "int32_t must be 4 bytes");

// ============================================================
// RING BUFFER WITH CONCEPT CONSTRAINTS
// ============================================================

// T must be trivially copyable so we can safely store it in a raw array
// and move it around with memcpy if needed.
template<typename T, int N>
requires BinarySerializable<T>   // C++20 requires clause
class TradingRingBuffer {
    static_assert((N & (N - 1)) == 0, "N must be power of 2 for fast modulo");

public:
    void push(const T& item) {
        buf_[head_ & (N - 1)] = item;   // head_ & (N-1) = head_ % N (fast)
        ++head_;
        if (count_ < N) ++count_;
    }

    const T& latest() const { return buf_[(head_ - 1) & (N - 1)]; }
    int size() const { return count_; }

private:
    T   buf_[N] = {};
    int head_   = 0;
    int count_  = 0;
};

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // TYPE TRAIT QUERIES
    // -------------------------------------------------------

    std::cout << "=== Type trait queries ===\n";

    print_type_traits<int64_t>("int64_t");
    print_type_traits<double>("double");
    print_type_traits<Tick>("Tick");
    print_type_traits<BadTick>("BadTick");

    // -------------------------------------------------------
    // BINARY SERIALIZABLE CHECK
    // -------------------------------------------------------

    std::cout << "\n=== BinarySerializable concept ===\n";

    describe_binary_layout<Tick>("Tick");
    // describe_binary_layout<BadTick>("BadTick");  // would NOT compile — BadTick has std::string
    std::cout << "  BadTick: trivially_copyable=" << std::is_trivially_copyable_v<BadTick>
              << " (NOT serializable — has std::string)\n";

    // -------------------------------------------------------
    // CONCEPTS ON FUNCTION TEMPLATES
    // -------------------------------------------------------

    std::cout << "\n=== Concept-constrained functions ===\n";

    // TickPrice: only integral types >= 4 bytes
    int64_t price_ticks = dollars_to_ticks(182.50, int64_t{10000});
    int32_t price_i32   = dollars_to_ticks(182.50, int32_t{100});
    std::cout << "  $182.50 = " << price_ticks << " ticks (int64)\n";
    std::cout << "  $182.50 = " << price_i32   << " ticks (int32)\n";

    // dollars_to_ticks<double>(182.50, 10000.0) — would NOT compile (float is not TickPrice)

    // Numeric: works for int, double, int64_t
    std::cout << "  clamp(150, 0, 100) int:    " << clamp(150, 0, 100) << "\n";
    std::cout << "  clamp(0.5, 0.0, 1.0) dbl:  " << clamp(0.5, 0.0, 1.0) << "\n";

    // clamp(std::string{}, ...) — would NOT compile (string is not Numeric)

    // -------------------------------------------------------
    // IF CONSTEXPR — type-based dispatch
    // -------------------------------------------------------

    std::cout << "\n=== if constexpr dispatch ===\n";

    print_price(int64_t{1825000});    // integer path: tick → dollars
    print_price(182.5);               // float path: already dollars

    // -------------------------------------------------------
    // SFINAE (old way — shown for reference)
    // -------------------------------------------------------

    std::cout << "\n=== SFINAE (legacy approach) ===\n";

    auto r1 = safe_add(int32_t{100}, int32_t{200});
    auto r2 = safe_add(1825.00, 0.50);
    std::cout << "  safe_add(100, 200) [int]:    " << r1 << "\n";
    std::cout << "  safe_add(1825.0, 0.5) [dbl]: " << r2 << "\n";

    // -------------------------------------------------------
    // RING BUFFER WITH CONCEPT CONSTRAINT
    // -------------------------------------------------------

    std::cout << "\n=== TradingRingBuffer<Tick, 8> ===\n";

    TradingRingBuffer<Tick, 8> rb;
    for (int i = 0; i < 5; ++i) {
        rb.push({uint64_t(1000000 + i * 100), int64_t(1825000 + i * 50), int32_t(100)});
    }
    std::cout << "  Buffer size: " << rb.size() << "\n";
    const auto& latest = rb.latest();
    std::cout << "  Latest tick: ts=" << latest.timestamp_ns
              << " price=$" << latest.price / 10000.0 << "\n";

    // TradingRingBuffer<BadTick, 8> bad_rb;  // would NOT compile — BadTick not BinarySerializable

    // -------------------------------------------------------
    // STATIC_ASSERT VERIFICATION
    // -------------------------------------------------------

    std::cout << "\n=== static_assert verification (compile-time) ===\n";

    std::cout << "  sizeof(Tick) == 20: confirmed at compile time\n";
    std::cout << "  Tick is trivially copyable: confirmed at compile time\n";
    std::cout << "  int64_t is 8 bytes: confirmed at compile time\n";

    // -------------------------------------------------------
    // UNDERLYING TYPE OF ENUM CLASS
    // -------------------------------------------------------

    std::cout << "\n=== Underlying type of enum class ===\n";

    enum class Side : uint8_t { BUY = 0, SELL = 1 };
    enum class OrderType : uint16_t { LIMIT = 0, MARKET = 1, IOC = 2, FOK = 3 };

    using SideUnderlying      = std::underlying_type_t<Side>;
    using OrderTypeUnderlying = std::underlying_type_t<OrderType>;

    std::cout << "  Side underlying type size:      " << sizeof(SideUnderlying) << " byte\n";
    std::cout << "  OrderType underlying type size: " << sizeof(OrderTypeUnderlying) << " bytes\n";

    static_assert(sizeof(Side) == 1, "Side must be 1 byte for wire protocol packing");
    std::cout << "  static_assert: Side is 1 byte [compile-time verified]\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Using type traits to write a generic binary serializer for all POD market data:

        // Works for Tick, Fill, OrderBookLevel — any BinarySerializable type
        // Fails at compile time for types with std::string or pointers
        template<BinarySerializable T>
        class BinaryFileWriter {
        public:
            // ... (as in L32, but now type-constrained)
            void write(const T& record) {
                file_.write(reinterpret_cast<const char*>(&record), sizeof(T));
            }
        };

        // This catches a bug at compile time instead of producing
        // garbage data at runtime:
        struct BadOrder {
            int64_t     price;
            std::string symbol;    // pointer — NOT safe to write as raw bytes
        };

        BinaryFileWriter<BadOrder> w("bad.bin");  // COMPILE ERROR — caught early!
        BinaryFileWriter<Tick> w2("ticks.bin");   // compiles fine — Tick is safe

        // Compare this to: naively writing &bad_order, sizeof(BadOrder) —
        // you'd write the string's internal pointer to disk, not the string data.
        // static_assert and BinarySerializable concept prevent this entire class of bugs.
    */
}
