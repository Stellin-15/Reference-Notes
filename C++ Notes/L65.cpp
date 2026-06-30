// ============================================================
// L65: System Architecture — Putting It All Together
// ============================================================
// WHAT: A complete architectural overview of the solo-trader HFT
//       system we've built across all 65 lessons. Shows how every
//       component connects: feed handler → order book → strategy
//       → risk → gateway → PnL → logger. Includes thread model,
//       IPC design, startup sequence, shutdown, and monitoring.
// WHY (TRADING): The biggest mistakes in system architecture happen
//   when components are wired together incorrectly: wrong thread
//   owns data it shouldn't, hot path crosses a mutex, order book
//   is shared between threads without synchronization. This lesson
//   is the blueprint — read it before you build.
// PHASE: Trading Systems Implementation
// ============================================================

/*
  ============================================================
  FULL SYSTEM ARCHITECTURE
  ============================================================

  ┌─────────────────────────────────────────────────────────────────────┐
  │                    SOLO TRADER HFT SYSTEM                           │
  │                                                                     │
  │  ┌───────────────────────────────────────────────────────────────┐  │
  │  │ CORE 0: Market Data Thread (real-time, isolated CPU)          │  │
  │  │                                                               │  │
  │  │  NIC (multicast UDP) → ITCH Parser (L57) → FeedHandler (L58) │  │
  │  │       → SPSC Queue (L38)                                      │  │
  │  └───────────────────────────────────────────────────────────────┘  │
  │                         │ MktEvent (64 bytes)                       │
  │                         ▼                                           │
  │  ┌───────────────────────────────────────────────────────────────┐  │
  │  │ CORE 1: Trading Thread (hot path, isolated CPU)               │  │
  │  │                                                               │  │
  │  │  OrderBook update (L54) → Strategy (L61, CRTP) →             │  │
  │  │       Risk check (L59) → FIX builder (L56) →                 │  │
  │  │       SPSC Queue → Gateway Thread                             │  │
  │  │                                                               │  │
  │  │  PnL tracking (L60) — updated on fills                        │  │
  │  └───────────────────────────────────────────────────────────────┘  │
  │                    │ OrderRequest                                    │
  │                    ▼                                                 │
  │  ┌───────────────────────────────────────────────────────────────┐  │
  │  │ CORE 2: Gateway Thread (order management)                     │  │
  │  │                                                               │  │
  │  │  FIX Session (L56) → TCP socket (L46) → Exchange             │  │
  │  │  Receive execution reports → fill callback → SPSC →           │  │
  │  │       Trading thread fills PnL tracker                        │  │
  │  └───────────────────────────────────────────────────────────────┘  │
  │                                                                     │
  │  ┌───────────────────────────────────────────────────────────────┐  │
  │  │ CORE 3: Logging Thread (background, non-isolated)             │  │
  │  │  AsyncLogger (L62) drains SPSC log queue → disk               │  │
  │  └───────────────────────────────────────────────────────────────┘  │
  │                                                                     │
  │  ┌───────────────────────────────────────────────────────────────┐  │
  │  │ CORE 4: Monitoring Thread (non-isolated)                       │  │
  │  │  Reads atomic counters (no locks) → sends to dashboard        │  │
  │  │  Heartbeat watchdog: kills process if trading thread stalls   │  │
  │  └───────────────────────────────────────────────────────────────┘  │
  └─────────────────────────────────────────────────────────────────────┘

  ============================================================
  IPC: HOW DATA MOVES BETWEEN THREADS
  ============================================================

  All inter-thread communication uses SPSC queues (L38):
    Feed Thread   → Trading Thread:  SPSCQueue<MktEvent, 4096>
    Trading Thread → Gateway Thread: SPSCQueue<OrderRequest, 1024>
    Gateway Thread → Trading Thread: SPSCQueue<SimFill, 1024>
    Trading Thread → Logger Thread:  SPSCQueue<LogRecord, 4096>

  Why SPSC only (not MPSC/MPMC):
    - Each queue has exactly one producer and one consumer
    - SPSC is lock-free with just two atomic loads per push/pop
    - No kernel involvement, no context switch, no cache line bouncing

  Atomic counters for monitoring (read from any thread):
    std::atomic<int64_t> g_tick_count       // ticks processed
    std::atomic<int64_t> g_order_count      // orders submitted
    std::atomic<int64_t> g_fill_count       // fills received
    std::atomic<int64_t> g_running_pnl      // unrealized + realized PnL
    std::atomic<bool>    g_kill_switch      // emergency stop

  ============================================================
  THREAD MODEL
  ============================================================

  Thread       | Core | Priority | Isolated | Role
  -------------|------|----------|----------|---------------------
  FeedThread   |  0   | 99 (RT) |   YES    | Parse market data
  TradingThread|  1   | 99 (RT) |   YES    | Strategy + risk
  GatewayThread|  2   | 90 (RT) |   YES    | FIX order management
  LoggerThread |  3   |  0      |   NO     | Async disk write
  MonitorThread|  4   |  0      |   NO     | Dashboards/alerts

  Isolated cores: /proc/cmdline: isolcpus=0,1,2
  Real-time priority: pthread_setschedparam(SCHED_FIFO, priority)
  (See L40 for thread pinning implementation)

  ============================================================
  MEMORY LAYOUT
  ============================================================

  Pre-allocated at startup (never malloc during trading):
    OrderPool:    10,000 Order objects (pool allocator, L44)
    EventBuffer:  64MB ring buffer (mmap anonymous, L49)
    LogBuffer:    4MB pre-allocated log records (L62)
    FIXBuffer:    128KB for FIX message construction (L56)

  Stack sizes:
    FeedThread:    2MB (default is fine — no recursion)
    TradingThread: 2MB
    GatewayThread: 2MB

  ============================================================
  STARTUP SEQUENCE
  ============================================================

  1. Load configuration (L63): trading.ini → TradingSystemConfig
  2. Validate config: exchange connectivity, risk parameters
  3. Pre-allocate all memory (pool allocators, ring buffers)
  4. Start logger thread (L62)
  5. Connect to exchange FIX session (L46) — logon handshake
  6. Subscribe to market data feed (L47) — join multicast groups
  7. Receive market data snapshot → populate order book (L54)
  8. Apply pending delta messages (any that arrived during snapshot)
  9. Set CPU affinity for all threads (L40)
  10. Enable real-time scheduling (L40)
  11. Start strategy (L61) — on_startup() callback
  12. Begin main loop: feed thread polls, trading thread processes

  ============================================================
  SHUTDOWN SEQUENCE
  ============================================================

  1. Receive shutdown signal (SIGTERM or manual)
  2. Set running_ = false (std::atomic<bool>)
  3. Strategy: on_shutdown() — cancel all open orders
  4. Wait for gateway: all cancels acknowledged (timeout: 5 seconds)
  5. Stop feed thread
  6. Flush log queue to disk (L62)
  7. Write end-of-day PnL report
  8. Close FIX session (Logout message)
  9. Close sockets
  10. Deallocate memory

  ============================================================
  LATENCY BUDGET (co-located, kernel bypass)
  ============================================================

  Stage                       | Target | Notes
  --------------------------- | ------ | --------------------
  NIC → user space            | 500 ns | DPDK/Solarflare (L52)
  ITCH parsing                |  50 ns | zero-copy (L57)
  Order book update           | 100 ns | std::map or custom (L54)
  Strategy evaluation         |  50 ns | CRTP, no malloc (L61)
  Risk check                  |  20 ns | atomic loads (L59)
  FIX message build           |  50 ns | pre-allocated buffer (L56)
  NIC TX                      | 500 ns | DPDK send
  ─────────────────────────── | ────── | --------------------
  TOTAL (wire-to-wire)        | 1.3 µs | at co-location

  ============================================================
  MONITORING
  ============================================================

  Read every 100ms (no locks — all reads are atomic):
    - ticks/sec: g_tick_count / elapsed
    - orders/min: g_order_count delta
    - fill rate: g_fill_count / g_order_count
    - PnL: $g_running_pnl
    - SPSC queue depths: how full are the queues?
    - Last latency samples from LatencyHistogram (L50)

  Alerts (triggered if thresholds exceeded):
    - Kill switch: on any breach
    - SPSC queue > 80% full: trading thread falling behind
    - Heartbeat timeout: trading thread stalled (deadlock?)
    - Fill rate < 30%: orders being rejected by exchange
    - PnL < -max_daily_loss: auto-kill

  ============================================================
  HARDWARE REQUIREMENTS (for serious co-lo)
  ============================================================

  Category       | Component                    | Cost
  -------------- | ---------------------------- | --------
  Server         | Intel Xeon or AMD EPYC       | $3-10K
  NIC            | Solarflare X2 or Mellanox    | $1-5K
  RAM            | 32GB DDR4 ECC (huge pages)   | $200
  Storage        | NVMe SSD (log files)         | $200
  Co-location    | CME/NYSE co-lo rack space    | $5-15K/month
  Market data    | Full depth (L2) feed         | $500-2K/month
  FIX connection | Exchange order entry         | $1-5K setup + monthly
  Total (year 1) |                              | ~$50-100K

  Solo trader path (not co-located):
    Use a VPS near the exchange (Amazon us-east-1 for NASDAQ)
    Total wire-to-wire: ~500µs–1ms (still much faster than manual)
    Cost: ~$500-2K/month all-in

*/

#include <iostream>
#include <atomic>
#include <thread>
#include <chrono>
#include <cstdint>
#include <cassert>
#include <array>
#include <cstring>

// ============================================================
// GLOBAL TELEMETRY COUNTERS (read by monitoring thread)
// ============================================================

struct alignas(64) Telemetry {
    std::atomic<int64_t> tick_count    {0};
    std::atomic<int64_t> order_count   {0};
    std::atomic<int64_t> fill_count    {0};
    std::atomic<int64_t> running_pnl   {0};
    std::atomic<bool>    kill_switch   {false};
    std::atomic<bool>    running       {true};
    // Each atomic on its own cache line (alignas(64) on the struct pads the whole struct)
};

static Telemetry g_telem;

// ============================================================
// SIMULATED MINIMAL TRADING SYSTEM (demonstrate the architecture)
// ============================================================

void feed_thread_fn() {
    while (g_telem.running.load(std::memory_order_relaxed)) {
        // Simulate receiving a market data tick
        g_telem.tick_count.fetch_add(1, std::memory_order_relaxed);

        // In production: poll NIC ring buffer (L52), parse ITCH (L57),
        // push MktEvent to SPSC queue (L38)

        std::this_thread::sleep_for(std::chrono::microseconds(100)); // simulate tick rate
    }
}

void trading_thread_fn() {
    while (g_telem.running.load(std::memory_order_relaxed)) {
        if (g_telem.kill_switch.load(std::memory_order_acquire)) break;

        // In production: pop from feed SPSC queue, update book (L54),
        // call strategy.on_market_data() (L61), risk check (L59),
        // push order to gateway SPSC queue

        // Simulate 1 order per 10 ticks
        int64_t ticks = g_telem.tick_count.load(std::memory_order_relaxed);
        static int64_t last_order_tick = 0;
        if (ticks - last_order_tick >= 10) {
            g_telem.order_count.fetch_add(1, std::memory_order_relaxed);
            last_order_tick = ticks;
        }

        std::this_thread::sleep_for(std::chrono::microseconds(50));
    }
}

void gateway_thread_fn() {
    while (g_telem.running.load(std::memory_order_relaxed)) {
        // In production: pop from order SPSC queue, serialize to FIX (L56),
        // send via socket (L46), receive execution report, push fill to trading thread

        // Simulate fills arriving
        int64_t orders = g_telem.order_count.load(std::memory_order_relaxed);
        static int64_t last_fill_order = 0;
        if (orders > last_fill_order) {
            g_telem.fill_count.fetch_add(1, std::memory_order_relaxed);
            g_telem.running_pnl.fetch_add(100, std::memory_order_relaxed); // +$0.01
            last_fill_order = orders;
        }

        std::this_thread::sleep_for(std::chrono::microseconds(200));
    }
}

void monitor_thread_fn() {
    auto start = std::chrono::steady_clock::now();

    for (int i = 0; i < 5 && g_telem.running.load(); ++i) {
        std::this_thread::sleep_for(std::chrono::milliseconds(200));

        auto now     = std::chrono::steady_clock::now();
        double secs  = std::chrono::duration<double>(now - start).count();

        int64_t ticks  = g_telem.tick_count.load(std::memory_order_relaxed);
        int64_t orders = g_telem.order_count.load(std::memory_order_relaxed);
        int64_t fills  = g_telem.fill_count.load(std::memory_order_relaxed);
        int64_t pnl    = g_telem.running_pnl.load(std::memory_order_relaxed);

        std::cout << "  [MONITOR t=" << std::fixed << secs << "s]"
                  << " ticks=" << ticks
                  << " orders=" << orders
                  << " fills=" << fills
                  << " PnL=$" << pnl / 10000.0 << "\n";
    }
}

// ============================================================
// MAIN
// ============================================================

int main() {
    std::cout << "=== L65: System Architecture — Full System Demo ===\n\n";

    // Print the architecture
    std::cout << "Architecture:\n";
    std::cout << "  Core 0: Feed thread     → parse ITCH, push to SPSC\n";
    std::cout << "  Core 1: Trading thread  → book update, strategy, risk, FIX build\n";
    std::cout << "  Core 2: Gateway thread  → send FIX, receive exec reports\n";
    std::cout << "  Core 3: Logger thread   → async disk write\n";
    std::cout << "  Core 4: Monitor thread  → read atomics, dashboard\n\n";

    // -------------------------------------------------------
    // START ALL THREADS
    // -------------------------------------------------------

    std::cout << "Starting threads...\n";

    std::thread feed_th(feed_thread_fn);
    std::thread trading_th(trading_thread_fn);
    std::thread gateway_th(gateway_thread_fn);
    std::thread monitor_th(monitor_thread_fn);

    // Run for 1 second then shutdown
    std::this_thread::sleep_for(std::chrono::seconds(1));

    // -------------------------------------------------------
    // SHUTDOWN
    // -------------------------------------------------------

    std::cout << "\nShutting down...\n";

    g_telem.running.store(false, std::memory_order_release);

    feed_th.join();
    trading_th.join();
    gateway_th.join();
    monitor_th.join();

    std::cout << "All threads stopped.\n";

    // -------------------------------------------------------
    // FINAL SUMMARY
    // -------------------------------------------------------

    std::cout << "\n=== Final System State ===\n";
    std::cout << "  Ticks processed:  " << g_telem.tick_count  << "\n";
    std::cout << "  Orders submitted: " << g_telem.order_count << "\n";
    std::cout << "  Fills received:   " << g_telem.fill_count  << "\n";
    std::cout << "  Running PnL:      $" << g_telem.running_pnl / 10000.0 << "\n";
    std::cout << "  Kill switch:      " << (g_telem.kill_switch ? "ACTIVE" : "off") << "\n";

    // -------------------------------------------------------
    // CURRICULUM COMPLETE
    // -------------------------------------------------------

    std::cout << "\n";
    std::cout << "╔═══════════════════════════════════════════════════════╗\n";
    std::cout << "║      C++ HFT Reference Notes — COMPLETE               ║\n";
    std::cout << "╠═══════════════════════════════════════════════════════╣\n";
    std::cout << "║  Phase 1: Core C++           L01–L15  (15 lessons)    ║\n";
    std::cout << "║  Phase 2: OOP                L16–L22  ( 7 lessons)    ║\n";
    std::cout << "║  Phase 3: Modern C++         L23–L34  (12 lessons)    ║\n";
    std::cout << "║  Phase 4: Concurrency        L35–L42  ( 8 lessons)    ║\n";
    std::cout << "║  Phase 5: Low-Latency        L43–L52  (10 lessons)    ║\n";
    std::cout << "║  Phase 6: Trading Systems    L53–L65  (13 lessons)    ║\n";
    std::cout << "╠═══════════════════════════════════════════════════════╣\n";
    std::cout << "║  Total: 65 lessons                                    ║\n";
    std::cout << "╚═══════════════════════════════════════════════════════╝\n";

    std::cout << "\nKey HFT hot-path rules:\n";
    std::cout << "  ✓ No malloc/free in the hot path (L44: pool allocators)\n";
    std::cout << "  ✓ No exceptions in the hot path (L31: error codes)\n";
    std::cout << "  ✓ No virtual calls in the hot path (L61: CRTP)\n";
    std::cout << "  ✓ No mutex in the hot path (L38: SPSC queue)\n";
    std::cout << "  ✓ No system calls in the hot path (L52: kernel bypass)\n";
    std::cout << "  ✓ Prices as int64_t ticks, NEVER double (L03, L53)\n";
    std::cout << "  ✓ Fixed-size char arrays for symbols, NEVER std::string\n";
    std::cout << "  ✓ Thread affinity: one thread per core (L40)\n";
    std::cout << "  ✓ Kill switch on EVERY order, ALWAYS (L59)\n";

    return 0;
}
