// ============================================================
// L12: Pointers
// ============================================================
// WHAT: Pointers store the memory ADDRESS of another variable.
//       They let you directly read and write any memory location.
// WHY (TRADING): Pointers are the foundation of everything fast:
//   - Accessing shared market data buffers without copying
//   - Function pointers for zero-overhead strategy callbacks
//   - reinterpret_cast of raw network bytes into protocol structs
//   - Memory pool allocation (L44)
//   - Lock-free data structures (L38)
//   Raw pointers are dangerous but are used in HFT where
//   smart pointers add overhead that's unacceptable.
// PHASE: Foundation
// ============================================================

/*
  CONCEPT OVERVIEW:

  POINTER BASICS:
    int* p;           — declare a pointer to int (p stores an address)
    p = &x;          — & is "address-of": get the address of variable x
    *p = 5;          — * is "dereference": read/write the value at the address p holds
    int val = *p;    — read the int that p points to

  POINTER ARITHMETIC:
    p + 1            — address of the NEXT int (moves 4 bytes for int, 8 for double)
    p[i]             — same as *(p + i) — array indexing IS pointer arithmetic
    p++              — advance pointer by sizeof(*p) bytes

  NULL / NULLPTR:
    nullptr          — a pointer that points to nothing (C++11, use this)
    NULL             — old C-style null (avoid in C++)
    Always check if (p != nullptr) before dereferencing

  POINTERS TO STRUCTS:
    Order* p = &order;
    (*p).price       — dereference then access field (verbose)
    p->price         — same thing, cleaner syntax (prefer this)

  CONST AND POINTERS (4 combinations):
    int* p              — non-const ptr to non-const int: can change both
    const int* p        — non-const ptr to const int: can't change the int via p
    int* const p        — const ptr to non-const int: can't change the address p holds
    const int* const p  — const everything: read-only in every way

  VOID POINTER (void*):
    Pointer to unknown type — must be cast before use.
    Used in: C APIs, memory allocators, serialization buffers.
    In HFT: raw network receive buffer is often void* or uint8_t*

  FUNCTION POINTERS:
    void (*fp)(int) = &my_function;   — pointer to a function
    fp(42);                           — call the function through the pointer
    Used in: strategy callbacks, message dispatch tables

  WHEN HFT USES RAW POINTERS:
    - Pointing into pre-allocated memory pools (no smart pointer overhead)
    - Pointing into a shared memory region (mmap'd market data)
    - reinterpret_cast<MsgHeader*>(buf) — parse bytes as a struct
    - Function pointer dispatch tables for message type routing

  TRADING USE CASE:
    uint8_t* buf = receive_packet();             // raw bytes from network
    auto* header = reinterpret_cast<MsgHeader*>(buf);  // interpret as struct
    uint32_t msg_type = ntohl(header->msg_type); // read field (big-endian swap)

  COMMON MISTAKES:
    - Dangling pointer: pointer to a variable that has been destroyed
    - Null dereference: calling *p when p is nullptr (crash)
    - Double free: deleting memory twice (use smart pointers to avoid)
    - Buffer overrun: incrementing a pointer past the end of an array
    - Confusing * in declaration (means "pointer type") vs * in expression (means "dereference")
*/

#include <iostream>
#include <cstdint>

// Simple structs for demonstration
struct Order {
    uint64_t id;
    double   price;
    int32_t  quantity;
    uint8_t  side;   // 0=BUY, 1=SELL
};

// Function that takes a pointer to avoid copying the Order struct
void print_order(const Order* order) {
    if (order == nullptr) {
        std::cout << "[ERROR] Null order pointer\n";
        return;
    }
    std::cout << "Order #" << order->id        // -> is shorthand for (*order).id
              << " " << (order->side == 0 ? "BUY" : "SELL")
              << " " << order->quantity
              << " @ $" << order->price << "\n";
}

// Function pointer type: a function that takes an Order and returns bool
using RiskCheckFn = bool (*)(const Order&);

// A sample risk check function matching that signature
bool basic_risk_check(const Order& order) {
    return order.quantity > 0 && order.price > 0.0 && order.quantity <= 10000;
}

int main() {

    // -------------------------------------------------------
    // BASIC POINTER MECHANICS
    // -------------------------------------------------------

    std::cout << "--- Basic pointer mechanics ---\n";

    double price = 182.50;

    double* ptr = &price;           // ptr holds the ADDRESS of 'price'

    std::cout << "price value:     " << price  << "\n";
    std::cout << "price address:   " << &price << "\n";    // hex address
    std::cout << "ptr holds:       " << ptr    << "\n";    // same hex address
    std::cout << "value at ptr:    " << *ptr   << "\n";    // dereference: 182.50

    // Modify the original through the pointer
    *ptr = 183.00;
    std::cout << "After *ptr=183:  price=" << price << "\n";  // price is now 183.00

    // -------------------------------------------------------
    // NULLPTR — safe "no value" sentinel
    // -------------------------------------------------------

    std::cout << "\n--- nullptr guard ---\n";

    Order* order_ptr = nullptr;   // no order yet

    if (order_ptr == nullptr) {
        std::cout << "No order to process (ptr is null)\n";
    }

    // Now assign a real order
    Order live_order = {1001, 182.50, 100, 0};  // BUY 100 @ 182.50
    order_ptr = &live_order;

    print_order(order_ptr);  // now safe to dereference

    // -------------------------------------------------------
    // POINTER ARITHMETIC — iterating arrays
    // -------------------------------------------------------

    std::cout << "\n--- Pointer arithmetic ---\n";

    double prices[] = {100.10, 100.20, 100.30, 100.40, 100.50};
    double* p = prices;   // pointer to first element

    std::cout << "prices[0] via ptr: " << *p      << "\n";   // 100.10
    std::cout << "prices[1] via ptr: " << *(p+1)  << "\n";   // 100.20
    std::cout << "prices[2] via ptr: " << p[2]    << "\n";   // p[2] == *(p+2)

    // Walk through the array with pointer increment
    std::cout << "All prices: ";
    double* end = prices + 5;   // one-past-end pointer
    for (double* it = prices; it != end; ++it) {
        std::cout << *it << " ";
    }
    std::cout << "\n";

    // -------------------------------------------------------
    // reinterpret_cast — reading raw bytes as a struct
    // -------------------------------------------------------

    std::cout << "\n--- reinterpret_cast: raw bytes as struct ---\n";

    // Simulate a raw network packet (fixed-layout binary protocol)
    // In real HFT, this buffer comes directly from recv() or mmap
    uint8_t raw_packet[] = {
        0x00, 0x00, 0x03, 0xE9,   // order_id = 1001 in big-endian (4 bytes)
        0x00, 0x00, 0x00, 0x64,   // quantity = 100  in big-endian (4 bytes)
    };

    // Interpret the first 4 bytes as a uint32_t (without copying)
    // This is how exchange protocol parsers work
    uint32_t* id_ptr  = reinterpret_cast<uint32_t*>(raw_packet);
    uint32_t* qty_ptr = reinterpret_cast<uint32_t*>(raw_packet + 4);

    // On little-endian CPUs (x86), we'd need to byte-swap big-endian values
    // For demo purposes, just print the raw interpreted value
    std::cout << "Raw order_id bytes:  " << *id_ptr  << "\n";   // big-endian value
    std::cout << "Raw quantity bytes:  " << *qty_ptr << "\n";

    // -------------------------------------------------------
    // CONST POINTER COMBINATIONS
    // -------------------------------------------------------

    std::cout << "\n--- const pointer variations ---\n";

    int x = 10;
    int y = 20;

    // 1. Non-const ptr to non-const: can change both
    int* p1 = &x;
    *p1 = 15;           // OK: change the value
    p1  = &y;           // OK: change where ptr points

    // 2. Ptr to const: can't change the value through ptr
    const int* p2 = &x;
    // *p2 = 15;        // COMPILE ERROR: value is const through this ptr
    p2 = &y;            // OK: can still re-point the pointer

    // 3. Const ptr to non-const: can't change where ptr points
    int* const p3 = &x;
    *p3 = 30;           // OK: can change value
    // p3 = &y;         // COMPILE ERROR: pointer itself is const

    // 4. Const ptr to const: can't change either
    const int* const p4 = &x;
    // *p4 = 5;         // COMPILE ERROR
    // p4 = &y;         // COMPILE ERROR
    std::cout << "p4 reads: " << *p4 << "\n";   // read-only

    // In trading: const Order* is used to pass an order for READ ONLY inspection
    // (risk check, logging) — pointer to const means "I won't modify this order"

    // -------------------------------------------------------
    // FUNCTION POINTERS — dispatch table for order types
    // -------------------------------------------------------

    std::cout << "\n--- Function pointer: risk check dispatch ---\n";

    // Assign the function's address to a function pointer
    RiskCheckFn risk_fn = &basic_risk_check;

    Order test_order = {2001, 185.00, 500, 1};   // SELL 500 @ 185.00
    bool  passed     = risk_fn(test_order);        // call through function pointer

    std::cout << "Risk check result: " << (passed ? "PASS" : "FAIL") << "\n";

    // Function pointer arrays enable O(1) dispatch by message type
    // (covered in detail in L56/L57 when building a protocol parser)

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Reading market data from shared memory (mmap):

        // Market data process writes ticks here; strategy reads with a pointer
        void* shm = mmap(nullptr, SHM_SIZE, PROT_READ, MAP_SHARED, shm_fd, 0);

        // Cast to our tick structure — zero copy, zero allocation
        const Tick* latest_tick = reinterpret_cast<const Tick*>(shm);

        while (running) {
            // Reading current price directly from shared memory via pointer
            // No system call, no copy — just a memory read
            double bid = latest_tick->bid;
            double ask = latest_tick->ask;
            // ... process ...
        }

      This is how the fastest market data feeds work:
      one process writes to shared memory, strategy reads with a pointer.
      Latency: ~100ns vs ~10us for a socket-based approach.
    */
}
