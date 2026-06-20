// ============================================================
// L11: Strings — std::string, string_view, Parsing
// ============================================================
// WHAT: How to work with text in C++. std::string for owning
//       text, std::string_view for non-owning references,
//       and string-to-number conversions.
// WHY (TRADING): Strings are everywhere in trading infrastructure:
//   FIX protocol fields are tag=value text, CSV market data,
//   symbol names, log messages, config files. But std::string
//   allocates heap memory — a problem in hot paths. std::string_view
//   (C++17) lets you parse raw bytes WITHOUT any allocation,
//   which is how real HFT parsers work.
// PHASE: Foundation
// ============================================================

/*
  CONCEPT OVERVIEW:

  std::string:
    - Owns its data (heap-allocated if > ~15 chars — SSO: Small String Optimization)
    - Mutable: can append, replace, erase
    - Operations: find, substr, append, compare, size, empty, clear
    - Implicit '\0' terminator (compatible with C APIs via .c_str())
    - NEVER modify std::string in the hot path — allocation = latency

  std::string_view (C++17):
    - NON-OWNING view of an existing string or char array
    - Just a (pointer, length) pair — 16 bytes, no allocation
    - Read-only: cannot modify the underlying data
    - Perfect for: parsing protocols, splitting fields, zero-copy substrings
    - IMPORTANT: the underlying string must outlive the string_view

  KEY METHODS:
    s.size() / s.length() — number of characters
    s.empty()             — true if length is 0
    s.find("x")          — returns index or std::string::npos if not found
    s.substr(pos, len)    — copy of substring (allocates! use string_view to avoid)
    s.append("x") / s += "x" — add to end
    s.compare(other)      — 0 if equal, <0 if less, >0 if greater
    s.starts_with("x")   — C++20
    s.ends_with("x")     — C++20

  STRING-TO-NUMBER:
    std::stoi("123")      — string to int
    std::stol("123")      — string to long
    std::stoll("123")     — string to long long
    std::stod("1.23")     — string to double
    std::to_string(123)   — number to string
    Note: all of these allocate and are slow — avoid in hot path.
    In HFT parsers: use hand-written atoi() equivalents on raw bytes.

  FIX PROTOCOL CONTEXT:
    FIX messages look like:  "8=FIX.4.2|35=D|49=TRADER|56=CME|55=AAPL|54=1|38=100|44=182.5|"
    Parsing this means splitting by '|', then splitting each field by '='.
    std::string_view lets you do this without copying any bytes.

  TRADING USE CASE:
    - Parse symbol from FIX tag 55: "55=AAPL" → "AAPL"
    - Parse price from CSV: "182.50" → 18250 ticks
    - Build log message: "[FILL] AAPL 100 @ 182.50"
    - Config file: read "max_position=10000" → parse key and value

  COMMON MISTAKES:
    - string_view pointing to a temporary — UB after the temp is destroyed
    - Using std::string in a hot path — triggers malloc
    - s.substr() in a parsing loop — O(n) allocation on every call
    - Comparing with == on float-derived string values (precision issues)
*/

#include <iostream>
#include <string>
#include <string_view>
#include <cstdint>

// Helper: hand-written fast integer parser (no allocation, no exceptions)
// Parses decimal integer from a string_view — used in protocol parsers
int64_t fast_atoi(std::string_view s) {
    int64_t result = 0;
    bool negative = false;
    size_t i = 0;
    if (i < s.size() && s[i] == '-') { negative = true; ++i; }
    for (; i < s.size(); ++i) {
        if (s[i] < '0' || s[i] > '9') break;  // stop at non-digit
        result = result * 10 + (s[i] - '0');
    }
    return negative ? -result : result;
}

int main() {

    // -------------------------------------------------------
    // std::string BASICS
    // -------------------------------------------------------

    std::cout << "--- std::string ---\n";

    std::string symbol = "AAPL";
    std::string exchange = "NASDAQ";
    std::string full_name = symbol + "@" + exchange;  // concatenation (allocates!)

    std::cout << "Symbol:    " << symbol    << "\n";
    std::cout << "Full name: " << full_name << "\n";
    std::cout << "Length:    " << symbol.size() << "\n";
    std::cout << "Empty?     " << symbol.empty() << "\n";

    // find() returns std::string::npos if not found
    size_t at_pos = full_name.find('@');
    if (at_pos != std::string::npos) {
        std::cout << "'@' found at index: " << at_pos << "\n";
    }

    // substr(start, length) — creates a COPY (avoid in hot path)
    std::string just_symbol = full_name.substr(0, at_pos);  // "AAPL"
    std::cout << "Extracted symbol: " << just_symbol << "\n";

    // append and +=
    std::string log_msg = "[ORDER] ";
    log_msg += symbol;
    log_msg += " BUY 100 @ $182.50";
    std::cout << log_msg << "\n";

    // compare() returns 0 if equal
    bool same = (symbol.compare("AAPL") == 0);
    std::cout << "Is AAPL: " << same << "\n";

    // -------------------------------------------------------
    // std::string_view — ZERO COPY (the HFT way)
    // -------------------------------------------------------

    std::cout << "\n--- std::string_view (zero copy) ---\n";

    // string_view is just a (pointer, length) — no heap allocation
    // It points INTO the original string — zero copy
    std::string_view sv = symbol;          // view of "AAPL" — no copy
    std::string_view sv2 = full_name;      // view of "AAPL@NASDAQ"

    std::cout << "string_view: " << sv << " (size=" << sv.size() << ")\n";

    // substr on string_view also returns a string_view — still zero copy!
    std::string_view sym_view = sv2.substr(0, at_pos);
    std::cout << "Extracted (zero copy): " << sym_view << "\n";

    // -------------------------------------------------------
    // PARSING A FIX-STYLE MESSAGE WITH string_view
    // -------------------------------------------------------

    std::cout << "\n--- FIX message parsing with string_view ---\n";

    // FIX uses | as field separator, = as tag-value separator
    // A real FIX NewOrderSingle (type 35=D) looks like this:
    const char* fix_msg = "8=FIX.4.2|35=D|49=TRADER|56=CME|55=AAPL|54=1|38=100|44=18250|";
    std::string_view msg_view(fix_msg);  // zero-copy view of the raw bytes

    std::cout << "Parsing FIX message...\n";

    // Split by '|' and find specific tags
    size_t pos = 0;
    while (pos < msg_view.size()) {
        size_t sep = msg_view.find('|', pos);  // find next '|'
        if (sep == std::string_view::npos) break;

        std::string_view field = msg_view.substr(pos, sep - pos);  // zero-copy slice

        // Split field by '='
        size_t eq = field.find('=');
        if (eq != std::string_view::npos) {
            std::string_view tag   = field.substr(0, eq);
            std::string_view value = field.substr(eq + 1);

            // Print interesting tags
            if (tag == "55") std::cout << "  Symbol (tag 55): " << value << "\n";
            if (tag == "38") std::cout << "  Quantity (tag 38): " << value << " (parsed: " << fast_atoi(value) << ")\n";
            if (tag == "44") std::cout << "  Price in ticks (tag 44): " << value << " → $" << (fast_atoi(value) / 100.0) << "\n";
            if (tag == "54") std::cout << "  Side (tag 54): " << (value == "1" ? "BUY" : "SELL") << "\n";
        }

        pos = sep + 1;  // move past the '|'
    }

    // -------------------------------------------------------
    // STRING-TO-NUMBER CONVERSIONS
    // -------------------------------------------------------

    std::cout << "\n--- String-to-number conversions ---\n";

    // Standard library versions (allocate, throw on error — avoid in hot path)
    std::string price_str = "182.50";
    std::string qty_str   = "100";

    double price = std::stod(price_str);    // string → double
    int    qty   = std::stoi(qty_str);      // string → int

    std::cout << "Price: $" << price << "\n";
    std::cout << "Qty:   " << qty   << "\n";

    // Fast version (zero allocation, no exception):
    std::string_view tick_str = "18250";
    int64_t ticks = fast_atoi(tick_str);
    std::cout << "Fast parse: " << tick_str << " → " << ticks << " ticks = $" << (ticks / 100.0) << "\n";

    // Number to string (allocates — only for logging, not hot path)
    std::string pnl_str = "PnL: $" + std::to_string(250.75);
    std::cout << pnl_str << "\n";

    // -------------------------------------------------------
    // CSV LINE PARSING — reading historical data files
    // -------------------------------------------------------

    std::cout << "\n--- CSV parsing with string_view ---\n";

    // Format: "timestamp,symbol,price,volume"
    const char* csv_line = "1700000000,AAPL,182.50,52300";
    std::string_view line(csv_line);

    // Split by comma using string_view (zero copy)
    size_t start = 0;
    int    field_idx = 0;
    const char* field_names[] = {"Timestamp", "Symbol", "Price", "Volume"};

    while (start <= line.size()) {
        size_t comma = line.find(',', start);
        size_t end   = (comma == std::string_view::npos) ? line.size() : comma;
        std::string_view token = line.substr(start, end - start);
        std::cout << field_names[field_idx++] << ": " << token << "\n";
        if (comma == std::string_view::npos) break;
        start = comma + 1;
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      A real HFT FIX parser NEVER uses std::string for individual fields.
      Instead it works directly on the raw receive buffer:

        // buf is a char[] received from the socket (no copy made)
        std::string_view msg(buf, bytes_received);

        // Parse tag 44 (price) without allocating anything:
        auto price_field = find_tag(msg, "44");   // returns string_view slice
        int64_t price = fast_atoi(price_field);   // pure integer parsing

        // Entire parse of a 200-byte FIX message: ~50ns
        // Same parse with std::string and stod(): ~500ns (10x slower)
    */
}
