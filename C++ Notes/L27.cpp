// ============================================================
// L27: STL Containers In Depth
// ============================================================
// WHAT: The standard library containers: vector, array, deque,
//       map, unordered_map, set, and priority_queue.
//       Performance characteristics of each, and which to use
//       for each trading data structure.
// WHY (TRADING): Choosing the wrong container can make the
//   difference between a 50ns lookup and a 50µs lookup.
//   Order book = std::map (sorted). Symbol table = unordered_map
//   (O(1) lookup). Pending orders = priority_queue (best price
//   always at top). Price history = vector (sequential access,
//   cache friendly). Knowing the big-O and cache behavior of
//   each container is mandatory for HFT engineering.
// PHASE: Modern C++
// ============================================================

/*
  CONTAINER PERFORMANCE SUMMARY:
  ┌─────────────────┬──────────┬──────────┬──────────┬───────────────────┐
  │ Container       │ Access   │ Insert   │ Delete   │ Notes             │
  ├─────────────────┼──────────┼──────────┼──────────┼───────────────────┤
  │ vector          │ O(1)     │ O(1) end │ O(n)     │ Cache-friendly    │
  │ array           │ O(1)     │ N/A      │ N/A      │ Stack, fixed size │
  │ deque           │ O(1)     │ O(1)ends │ O(n) mid │ Good for queues   │
  │ list            │ O(n)     │ O(1)     │ O(1)     │ Rarely useful     │
  │ map             │ O(log n) │ O(log n) │ O(log n) │ Sorted, red-black │
  │ unordered_map   │ O(1) avg │ O(1) avg │ O(1) avg │ Hash table        │
  │ set             │ O(log n) │ O(log n) │ O(log n) │ Sorted unique     │
  │ unordered_set   │ O(1) avg │ O(1) avg │ O(1) avg │ Hash set          │
  │ priority_queue  │ O(1) top │ O(log n) │ O(log n) │ Heap, max on top  │
  └─────────────────┴──────────┴──────────┴──────────┴───────────────────┘

  TRADING USAGE GUIDE:
    vector:          tick history buffer, list of fills, sorted book levels array
    array:           fixed-size top-of-book, protocol field buffers
    map:             ORDER BOOK (sorted by price), IOI book, dark pool levels
    unordered_map:   symbol → instrument lookup, order_id → order lookup
    set:             set of active symbols, halted symbols
    priority_queue:  best-price-first order queue, event timer heap
    deque:           FIFO order queue (push back, pop front)

  MAP vs UNORDERED_MAP:
    map:          std::map<Key, Value> — sorted, O(log n), tree traversal = cache misses
    unordered_map: O(1) average, hash table — but worst case O(n) on hash collision
    In HFT:
      - unordered_map for symbol lookup (small, predictable keys)
      - map for order book (MUST be sorted for price priority)
      - Custom hash maps (robin-hood, flat hash map) for maximum performance

  VECTOR CAPACITY MANAGEMENT:
    .reserve(n)    — pre-allocate space for n elements (avoids reallocations)
    .resize(n)     — set size to n (fills with default value)
    .capacity()    — current allocated space
    .shrink_to_fit()— release excess capacity
    Always reserve() if you know the approximate size upfront.

  PRIORITY QUEUE:
    std::priority_queue<T>: max-heap (largest element on top)
    For min-heap: priority_queue<T, vector<T>, greater<T>>
    top():  O(1) — peek at best element
    push(): O(log n) — insert new element
    pop():  O(log n) — remove best element
*/

#include <iostream>
#include <vector>
#include <array>
#include <deque>
#include <map>
#include <unordered_map>
#include <set>
#include <unordered_set>
#include <queue>          // priority_queue
#include <algorithm>
#include <string>
#include <cstdint>
#include <chrono>

// ============================================================
// TYPES
// ============================================================

struct Level {
    int64_t price_ticks;
    int32_t qty;
    int     order_count;
};

struct Order {
    uint64_t    id;
    int64_t     price_ticks;
    int32_t     qty;
    bool        is_buy;
    uint64_t    timestamp_ns;
};

struct Fill {
    uint64_t order_id;
    int64_t  price_ticks;
    int32_t  qty;
};

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // VECTOR — the workhorse of C++ (cache-friendly, dynamic)
    // -------------------------------------------------------

    std::cout << "=== std::vector ===\n";

    {
        std::vector<double> tick_history;
        tick_history.reserve(1024);  // pre-allocate: avoids 10 reallocations

        // push_back: O(1) amortized — appends to end
        for (double p : {182.50, 182.55, 182.48, 182.60, 182.52}) {
            tick_history.push_back(p);
        }

        std::cout << "Size: " << tick_history.size()
                  << " Capacity: " << tick_history.capacity() << "\n";

        // Random access: O(1)
        std::cout << "First tick: $" << tick_history.front() << "\n";
        std::cout << "Last tick:  $" << tick_history.back()  << "\n";
        std::cout << "Tick[2]:    $" << tick_history[2]      << "\n";

        // Remove last: O(1)
        tick_history.pop_back();
        std::cout << "After pop_back, size: " << tick_history.size() << "\n";

        // Erase from middle: O(n) — shifts all elements after it
        auto it = tick_history.begin() + 1;   // erase second element
        tick_history.erase(it);
        std::cout << "After erase[1], size: " << tick_history.size() << "\n";
        for (double p : tick_history) std::cout << "  $" << p << "\n";

        // emplace_back: constructs in-place, no copy (prefer over push_back for non-trivial types)
        std::vector<Order> orders;
        orders.reserve(64);
        orders.emplace_back(Order{1001, 1825000, 100, true, 1000000000ULL});
        std::cout << "Order #" << orders.back().id << " emplaced\n";
    }

    // -------------------------------------------------------
    // MAP — sorted order book
    // -------------------------------------------------------

    std::cout << "\n=== std::map (sorted order book) ===\n";

    {
        // Ask side: sorted ascending (lowest ask first = best ask)
        std::map<int64_t, Level> asks;

        // Insert levels at various prices (map keeps them sorted automatically)
        asks[1825500] = {1825500, 300, 2};
        asks[1825000] = {1825000, 100, 1};  // will be before 1825500 in iteration
        asks[1826000] = {1826000, 500, 4};
        asks[1825200] = {1825200, 200, 3};

        // Best ask: first element (lowest price)
        auto best_ask = asks.begin();
        std::cout << "Best ask: " << best_ask->second.qty
                  << " @ " << best_ask->first / 10000.0 << "\n";

        // Iterate asks in price order (ascending automatically)
        std::cout << "All ask levels:\n";
        for (const auto& [price, level] : asks) {  // structured binding (C++17)
            std::cout << "  $" << price / 10000.0
                      << " x " << level.qty << " (" << level.order_count << " orders)\n";
        }

        // Bid side: sorted descending (highest bid first = best bid)
        std::map<int64_t, Level, std::greater<int64_t>> bids;
        bids[1824900] = {1824900, 400, 3};
        bids[1825000] = {1825000, 200, 2};  // higher = best bid → first in iteration
        bids[1824500] = {1824500, 100, 1};

        std::cout << "Best bid: " << bids.begin()->second.qty
                  << " @ $" << bids.begin()->first / 10000.0 << "\n";

        // Find a specific price level: O(log n)
        auto found = asks.find(1825500);
        if (found != asks.end()) {
            std::cout << "Found ask at 182.55: qty=" << found->second.qty << "\n";
        }

        // Modify a level's qty
        asks[1825000].qty += 50;   // add 50 shares at best ask
        std::cout << "Best ask qty after update: " << asks.begin()->second.qty << "\n";

        // Erase a level (order fully cancelled or exhausted)
        asks.erase(1825000);
        std::cout << "After erasing 182.50, new best ask: $"
                  << asks.begin()->first / 10000.0 << "\n";
    }

    // -------------------------------------------------------
    // UNORDERED_MAP — O(1) symbol and order lookups
    // -------------------------------------------------------

    std::cout << "\n=== std::unordered_map ===\n";

    {
        // Symbol → instrument info lookup table
        std::unordered_map<std::string, int> symbol_to_id;
        symbol_to_id.reserve(256);  // pre-size the hash table to avoid rehashing

        symbol_to_id["AAPL"] = 1;
        symbol_to_id["MSFT"] = 2;
        symbol_to_id["TSLA"] = 3;
        symbol_to_id["NVDA"] = 4;
        symbol_to_id["AMZN"] = 5;

        // O(1) average lookup
        std::cout << "TSLA ID: " << symbol_to_id["TSLA"] << "\n";
        std::cout << "NVDA ID: " << symbol_to_id.at("NVDA") << "\n";  // .at() throws if missing

        // Safe lookup: check before access
        auto it = symbol_to_id.find("GOOG");
        if (it == symbol_to_id.end()) {
            std::cout << "GOOG not in universe\n";
        }

        // Order ID → Order lookup (very common in HFT: check fill matches live order)
        std::unordered_map<uint64_t, Order> live_orders;
        live_orders[1001] = {1001, 1825000, 100, true,  1000000000ULL};
        live_orders[1002] = {1002, 1825500, 200, false, 1000000001ULL};

        // When a fill arrives from the exchange:
        uint64_t fill_order_id = 1001;
        auto order_it = live_orders.find(fill_order_id);
        if (order_it != live_orders.end()) {
            std::cout << "Fill matches live order #" << order_it->second.id
                      << " qty=" << order_it->second.qty << "\n";
            live_orders.erase(order_it);  // remove filled order
        }
        std::cout << "Live orders remaining: " << live_orders.size() << "\n";
    }

    // -------------------------------------------------------
    // SET / UNORDERED_SET — membership testing
    // -------------------------------------------------------

    std::cout << "\n=== std::set and std::unordered_set ===\n";

    {
        // Halted symbols (sorted, unique)
        std::set<std::string> halted_symbols;
        halted_symbols.insert("AAPL");
        halted_symbols.insert("TSLA");
        halted_symbols.insert("AAPL");   // duplicate — ignored (set stores unique values)
        std::cout << "Halted symbols: " << halted_symbols.size() << " (AAPL inserted twice)\n";

        // Check if a symbol is halted before sending an order: O(log n)
        auto symbol = std::string("TSLA");
        if (halted_symbols.count(symbol)) {
            std::cout << symbol << " is halted — not sending order\n";
        }

        halted_symbols.erase("TSLA");
        std::cout << "After un-halting TSLA: " << halted_symbols.size() << " halted\n";

        // Unordered set: O(1) membership check (better for large symbol universes)
        std::unordered_set<std::string> subscribed;
        subscribed.reserve(1024);
        subscribed.insert("AAPL");
        subscribed.insert("MSFT");
        subscribed.insert("NVDA");

        std::cout << "NVDA subscribed: " << subscribed.count("NVDA") << "\n";
        std::cout << "GOOG subscribed: " << subscribed.count("GOOG") << "\n";
    }

    // -------------------------------------------------------
    // PRIORITY_QUEUE — best order always at top
    // -------------------------------------------------------

    std::cout << "\n=== std::priority_queue ===\n";

    {
        // Custom comparator: for BUY orders, higher price = higher priority
        auto bid_priority = [](const Order& a, const Order& b) {
            if (a.price_ticks != b.price_ticks)
                return a.price_ticks < b.price_ticks;  // higher price = higher priority
            return a.timestamp_ns > b.timestamp_ns;     // earlier time = higher priority
        };

        // max-heap by default (we provide custom comparator)
        std::priority_queue<Order, std::vector<Order>, decltype(bid_priority)>
            bid_queue(bid_priority);

        bid_queue.push({2001, 1825000, 100, true, 1000});
        bid_queue.push({2002, 1825500, 200, true, 1001});  // higher price → goes to top
        bid_queue.push({2003, 1825000, 150, true,  999});  // same price, earlier time
        bid_queue.push({2004, 1824500, 300, true,  998});  // lowest price → worst

        std::cout << "Processing bids in priority order:\n";
        while (!bid_queue.empty()) {
            const auto& top = bid_queue.top();
            std::cout << "  #" << top.id << " @ $" << top.price_ticks / 10000.0
                      << " qty=" << top.qty << " ts=" << top.timestamp_ns << "\n";
            bid_queue.pop();
        }
    }

    // -------------------------------------------------------
    // DEQUE — FIFO order queue (push back, pop front)
    // -------------------------------------------------------

    std::cout << "\n=== std::deque (FIFO order queue) ===\n";

    {
        // Deque: O(1) push_back AND O(1) pop_front — perfect for FIFO queues
        // (vector can only O(1) push_back, O(n) pop_front due to shifting)
        std::deque<Order> order_queue;

        order_queue.push_back({3001, 1825000, 100, true,  100});
        order_queue.push_back({3002, 1825500, 200, false, 101});
        order_queue.push_back({3003, 1824500, 300, true,  102});

        std::cout << "Processing order queue (FIFO):\n";
        while (!order_queue.empty()) {
            const auto& front = order_queue.front();
            std::cout << "  #" << front.id << " " << (front.is_buy ? "BUY" : "SELL")
                      << " @ $" << front.price_ticks / 10000.0 << "\n";
            order_queue.pop_front();  // O(1) — no shifting
        }
    }

    // -------------------------------------------------------
    // PERFORMANCE: vector vs map vs unordered_map lookup
    // -------------------------------------------------------

    std::cout << "\n=== Performance comparison ===\n";

    constexpr int N = 100000;

    // Build containers
    std::vector<int>                 vec_keys(N);
    std::map<int, int>               sorted_map;
    std::unordered_map<int, int>     hash_map;
    hash_map.reserve(N);

    for (int i = 0; i < N; ++i) {
        vec_keys[i] = i;
        sorted_map[i]  = i * 2;
        hash_map[i]    = i * 2;
    }

    int target = N / 2;

    auto t1 = std::chrono::high_resolution_clock::now();
    auto vec_it = std::find(vec_keys.begin(), vec_keys.end(), target);
    auto t2 = std::chrono::high_resolution_clock::now();

    auto t3 = std::chrono::high_resolution_clock::now();
    auto map_it = sorted_map.find(target);
    auto t4 = std::chrono::high_resolution_clock::now();

    auto t5 = std::chrono::high_resolution_clock::now();
    auto ump_it = hash_map.find(target);
    auto t6 = std::chrono::high_resolution_clock::now();

    auto ns = [](auto a, auto b) {
        return std::chrono::duration_cast<std::chrono::nanoseconds>(b - a).count();
    };

    (void)vec_it; (void)map_it; (void)ump_it;
    std::cout << "vector linear search:  " << ns(t1, t2) << " ns  (O(n))\n";
    std::cout << "map find:              " << ns(t3, t4) << " ns  (O(log n))\n";
    std::cout << "unordered_map find:    " << ns(t5, t6) << " ns  (O(1) avg)\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Complete order book data structure choice:

        class OrderBook {
            // Bid side: sorted descending by price (highest bid first)
            std::map<int64_t, Level, std::greater<int64_t>> bids_;

            // Ask side: sorted ascending by price (lowest ask first)
            std::map<int64_t, Level> asks_;

            // Fast order lookup by ID (for cancels, modifies, fills)
            std::unordered_map<uint64_t, Order> orders_;
            orders_.reserve(10000);  // pre-size for expected peak order count

            // Recent trade history (FIFO, bounded size)
            std::deque<Trade> recent_trades_;

        public:
            void on_add(const AddOrderMsg& msg) {
                auto& side = msg.is_buy ? bids_ : asks_;
                side[msg.price].qty         += msg.qty;
                side[msg.price].order_count  += 1;
                orders_[msg.order_id]         = make_order(msg);
            }

            void on_cancel(const CancelOrderMsg& msg) {
                auto it = orders_.find(msg.order_id);  // O(1) lookup
                if (it == orders_.end()) return;        // unknown order
                auto& side = it->second.is_buy ? bids_ : asks_;
                side[it->second.price].qty -= msg.cancel_qty;
                if (side[it->second.price].qty == 0)
                    side.erase(it->second.price);  // level depleted
                orders_.erase(it);
            }
        };
    */
}
