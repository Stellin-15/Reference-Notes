// ============================================================
// L05: User Input — cin, getline, and I/O Basics
// ============================================================
// WHAT: How to read input from the user/terminal at runtime.
// WHY (TRADING): Live trading systems are event-driven — they
//   react to market data, not keyboard input. But for building
//   config tools, CLI parameter entry, paper trading simulations,
//   and strategy parameter tuning tools, you need input handling.
//   Understanding cin also helps when writing CSV/file parsers.
// PHASE: Foundation
// ============================================================

/*
  CONCEPT OVERVIEW:

  std::cin  — standard input stream (reads from keyboard by default)
    >>        — stream extraction operator (reads until whitespace)
    getline() — reads an entire line including spaces

  IMPORTANT: cin >> stops at whitespace (space, tab, newline).
  getline() reads the whole line up to '\n'.

  BUFFERING:
    cin maintains an internal buffer. After cin >> reads a value,
    the '\n' (from pressing Enter) is LEFT in the buffer.
    If you then call getline(), it reads that leftover '\n' as an
    empty string. Fix: call cin.ignore() to discard the newline first.

  WHY HFT DOESN'T USE cin AT RUNTIME:
    - cin BLOCKS — the program stops and waits for keyboard input
    - In a live trading system, blocking for ANY reason = missed trades
    - Instead: read all config at STARTUP from files, never block during trading
    - User commands (pause/resume strategy) use signals (SIGINT, SIGUSR1)
      or a separate control thread, never cin on the hot path

  TRADING USE CASE:
    cin is used in:
    - CLI config tools: "Enter max position size: "
    - Strategy parameter testing: interactive parameter sweeps
    - Paper trading simulators: "Enter simulated fill price: "
    - NOT in: live order execution, market data processing, risk checks

  COMMON MISTAKES:
    - Forgetting cin.ignore() before getline() after cin >>
    - Not validating cin success (cin.fail() after bad input)
    - Mixing cin >> and getline() without clearing the buffer
*/

#include <iostream>
#include <string>
#include <limits>   // for std::numeric_limits (used to clear cin buffer)

int main() {

    // -------------------------------------------------------
    // BASIC cin >> — reads one token (stops at whitespace)
    // -------------------------------------------------------

    int    quantity;
    double price;

    std::cout << "Enter order quantity: ";
    std::cin >> quantity;   // Reads an integer from keyboard

    std::cout << "Enter order price: ";
    std::cin >> price;      // Reads a double from keyboard

    std::cout << "Order received: " << quantity << " @ $" << price << "\n";
    std::cout << "Notional value: $" << (quantity * price) << "\n";

    // -------------------------------------------------------
    // cin.ignore() — clear the leftover '\n' in the buffer
    // -------------------------------------------------------

    // After "cin >> price", the '\n' from pressing Enter is still in the buffer.
    // The next getline() would immediately see that '\n' and return empty string.
    // cin.ignore() discards characters up to and including the next '\n'.
    std::cin.ignore(std::numeric_limits<std::streamsize>::max(), '\n');

    // -------------------------------------------------------
    // getline() — reads the entire line including spaces
    // -------------------------------------------------------

    std::string symbol;
    std::cout << "Enter symbol (e.g. 'AAPL US Equity'): ";
    std::getline(std::cin, symbol);  // Reads full line with spaces
    std::cout << "Symbol entered: [" << symbol << "]\n";

    // -------------------------------------------------------
    // INPUT VALIDATION — always validate user input
    // -------------------------------------------------------

    int max_position;
    std::cout << "\nEnter max position limit: ";
    std::cin >> max_position;

    // cin.fail() is true if the input didn't match the expected type
    if (std::cin.fail()) {
        std::cout << "[ERROR] Invalid input — expected an integer.\n";
        std::cin.clear();  // Reset the error state on cin
        std::cin.ignore(std::numeric_limits<std::streamsize>::max(), '\n');  // Discard bad input
        max_position = 1000;  // Fall back to a safe default
    }

    // Basic range validation — a real risk system would also do this
    if (max_position <= 0 || max_position > 100000) {
        std::cout << "[RISK] Position limit out of range. Using default 1000.\n";
        max_position = 1000;
    }

    std::cout << "Max position set to: " << max_position << "\n";

    // -------------------------------------------------------
    // MULTIPLE VALUES ON ONE LINE
    // -------------------------------------------------------

    // cin >> can chain to read multiple values separated by spaces
    // User types: "MSFT 150.25 200"
    std::string sym;
    double      order_price;
    int         order_qty;

    std::cin.ignore(std::numeric_limits<std::streamsize>::max(), '\n');  // clear buffer
    std::cout << "\nEnter: symbol price qty (e.g. MSFT 150.25 200): ";
    std::cin >> sym >> order_price >> order_qty;

    std::cout << "Symbol: " << sym        << "\n";
    std::cout << "Price:  $" << order_price << "\n";
    std::cout << "Qty:    " << order_qty   << "\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      A strategy parameter tool (used BEFORE market hours, not during):

        double entry_threshold, exit_threshold;
        int    max_qty;

        std::cout << "=== Strategy Config ===\n";
        std::cout << "Entry threshold (bps): ";   std::cin >> entry_threshold;
        std::cout << "Exit threshold (bps):  ";   std::cin >> exit_threshold;
        std::cout << "Max order size:        ";   std::cin >> max_qty;

        // Validate, then pass to strategy engine
        // Strategy runs event-driven after this — no more cin

      The key rule: collect all user input at startup, then run
      the trading loop without any blocking I/O.
    */
}
