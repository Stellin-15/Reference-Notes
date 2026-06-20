// ============================================================
// L01: Hello World — Output, Headers, and Namespaces
// ============================================================
// WHAT: The absolute basics — how a C++ program is structured,
//       how to print to the console, and what namespaces are.
// WHY (TRADING): Console output is how trading systems surface
//   debug info, order status, and errors during development.
//   Understanding std:: vs using namespace is day-one hygiene
//   in any professional codebase.
// PHASE: Foundation
// ============================================================

/*
  CONCEPT OVERVIEW:

  Every C++ program needs:
    1. #include — pulls in a library (like a toolbox)
    2. A main() function — execution always starts here
    3. A return statement — 0 means "success" to the OS

  PRINTING TO CONSOLE:
    std::cout  — the standard output stream ("c out")
    <<         — the "stream insertion" operator, pipes data into cout
    std::endl  — ends the line AND flushes the buffer (slower)
    "\n"       — just ends the line, NO flush (faster — prefer this)

  NAMESPACES:
    Everything in the C++ standard library lives in the "std" namespace.
    std::cout means "cout from the std namespace".

    "using namespace std;" saves typing but is BANNED in professional
    HFT code because it causes naming collisions (e.g., your own
    function named "sort" clashes with std::sort silently).

  TRADING USE CASE:
    When your order management system rejects an order, you log:
      std::cout << "[REJECT] Order " << orderId << " price out of range\n";
    Always use std:: explicitly so the codebase is unambiguous at a glance.

  COMMON MISTAKES:
    - Forgetting #include <iostream> -> compiler error: cout not found
    - Using endl in a hot loop (each flush can take microseconds)
    - Two main() functions in one file -> linker error
*/

#include <iostream>  // Provides std::cout, std::cin, std::endl

int main() {

    // --- Basic output ---

    // std::cout sends text to the terminal
    // "\n" moves to the next line (fast, no flush)
    std::cout << "Hello World!\n";

    // You can chain << to print multiple things in one line
    // This is called "chaining the insertion operator"
    int num = 15;
    std::cout << "The value of num is: " << num << "\n";

    // endl vs \n:
    //   std::endl  = "\n" + flush (empties the output buffer to screen NOW)
    //   "\n"       = just a newline, no flush
    // In trading, flushing inside a hot loop kills latency — use "\n"
    std::cout << "Using endl (slow flush): " << num << std::endl;
    std::cout << "Using \\n  (fast):        " << num << "\n";

    // --- Why NOT "using namespace std;" in trading code ---
    // If you wrote: using namespace std;
    // then "cout" works fine — BUT if you also define your own "sort()"
    // function, the compiler silently picks std::sort instead of yours.
    // HFT codebases ALWAYS qualify: std::cout, std::sort, std::vector
    // so there is zero ambiguity.

    return 0;  // Tell the OS the program finished successfully (0 = OK)

    /*
      TRADING CONTEXT EXAMPLE:
      In a live order gateway, the startup sequence prints:
        std::cout << "[BOOT] Connecting to exchange: CME\n";
        std::cout << "[BOOT] Session ID: " << sessionId << "\n";
        std::cout << "[BOOT] Ready. Waiting for market open.\n";
      This is the only acceptable use of cout in a live system;
      during trading hours, logging goes through a dedicated
      lock-free async logger (covered in L62).
    */
}
