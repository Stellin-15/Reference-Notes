// ============================================================
// L52: Kernel Bypass and DPDK (Overview)
// ============================================================
// WHAT: The Linux network stack adds ~10µs of latency between a packet
//       arriving at the NIC and your application reading it. Kernel
//       bypass eliminates this by having the NIC DMA packets directly
//       into user-space memory, bypassing the OS kernel entirely.
//       DPDK, Solarflare OpenOnload, RDMA, and XDP are the main
//       technologies. FPGAs can go sub-microsecond.
// WHY (TRADING): A 10µs latency floor means you will NEVER react faster
//   than 10µs using normal sockets, regardless of how fast your C++ is.
//   Top-tier HFT firms use kernel bypass to get to 500ns–2µs total
//   latency. If you're co-located and competing on speed, you need this.
// PHASE: Low-Latency Systems
// ============================================================

/*
  CONCEPT OVERVIEW:

  ┌─────────────────────────────────────────────────────────────┐
  │ NORMAL SOCKET PATH (baseline, ~10µs)                        │
  │                                                             │
  │  NIC → kernel interrupt → OS network stack → socket buffer  │
  │      → recv() system call → user space application         │
  │                                                             │
  │  Latency killers:                                           │
  │    - Hardware interrupt to CPU: 1-3µs                       │
  │    - Kernel network stack processing: 3-7µs                 │
  │    - Context switch (kernel → user): 1-3µs                  │
  │    - Lock contention in kernel socket buffer: 1-5µs         │
  └─────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────┐
  │ KERNEL BYPASS PATH (~500ns–2µs)                             │
  │                                                             │
  │  NIC → DMA directly to user-space ring buffer               │
  │       → user-space poll loop reads directly                 │
  │                                                             │
  │  Eliminated:                                                │
  │    - Hardware interrupts (NIC never interrupts the CPU)      │
  │    - OS network stack entirely bypassed                      │
  │    - No system calls (no context switch)                     │
  │    - No kernel locking                                       │
  └─────────────────────────────────────────────────────────────┘

  LATENCY STACK — WHERE TIME IS SPENT:
    Source          | Normal sockets | Kernel bypass | FPGA/ASIC
    --------------- | -------------- | ------------- | ----------
    NIC DMA         |    0.5µs       |    0.5µs      |   0.1µs
    Interrupt/poll  |    2.0µs       |    0µs        |   0µs
    Kernel net stack|    5.0µs       |    0µs        |   0µs
    Context switch  |    2.0µs       |    0µs        |   0µs
    User-space code |    0.5µs       |    0.5µs      |   0µs*
    FIX encode/decode|   0.5µs       |    0.5µs      |   0µs*
    NIC TX          |    0.5µs       |    0.5µs      |   0.1µs
    --------------- | -------------- | ------------- | ----------
    TOTAL           |   ~11µs        |   ~1.5µs      |  ~200ns
    *FPGA: decoding and strategy logic are done in hardware

  ─────────────────────────────────────────────────────────────

  1. DPDK (Data Plane Development Kit)
     - Open-source framework from Intel (now part of Linux Foundation)
     - Works with Intel 82599, X710, Mellanox ConnectX, etc.
     - Concept: polls the NIC in a tight loop (no interrupts, no kernel)
     - RTE (Run-To-End) ring buffers: NIC writes, your code reads directly
     - One core dedicated to polling (burns 100% CPU — that's intentional)
     - Latency: 1-3µs (software), down to ~500ns with careful tuning

     Rough DPDK code structure (Linux, C, not C++ idiomatic):
       rte_eal_init(argc, argv);           // init DPDK environment
       struct rte_mbuf* pkts[32];
       while (running) {
           int n = rte_eth_rx_burst(port, queue, pkts, 32);  // poll NIC
           for (int i = 0; i < n; i++) {
               uint8_t* data = rte_pktmbuf_mtod(pkts[i], uint8_t*);
               uint16_t len  = rte_pktmbuf_data_len(pkts[i]);
               process_packet(data, len);       // your trading logic
               rte_pktmbuf_free(pkts[i]);
           }
       }

  2. SOLARFLARE OPENONLOAD
     - Solarflare/Xilinx kernel bypass driver for their NICs
     - Plugs into the standard BSD socket API (no code changes needed!)
     - Run: LD_PRELOAD=libonload.so ./your_trading_app
     - Uses ef_vi (Vendor Interface) for ultra-low-latency access
     - Latency: ~500ns–1µs
     - Preferred by firms who want kernel bypass but don't want to
       rewrite all their network code for DPDK

  3. RDMA (Remote Direct Memory Access) — InfiniBand / RoCE
     - Used for: exchange co-lo server-to-server communication
     - A remote host writes DIRECTLY into your process's memory
     - No CPU involvement on the receiver — DMA from remote NIC
     - Verbs API: ibv_post_send(), ibv_poll_cq()
     - Latency: ~1µs for InfiniBand (IB), ~2µs for RoCE (RDMA over Ethernet)
     - Used by: CME co-location, some HFT order routing

  4. XDP / AF_XDP (Linux kernel 4.18+)
     - eBPF hook in the kernel NIC driver — before the socket stack
     - Faster than sockets, slower than DPDK (still involves kernel)
     - AF_XDP socket lets user space receive XDP-redirected packets
     - No need for special NIC hardware or root DPDK hugepages
     - Latency: ~3-5µs (better than normal, worse than DPDK)
     - Good for: latency-sensitive but not ultra-HFT workloads

  5. FPGA (Field-Programmable Gate Array)
     - Hardware-level packet processing — no CPU at all for hot path
     - FPGA directly parses market data feeds and generates orders
     - Latency: 100-400ns total (limited by light travel time!)
     - Used by: Jane Street, Virtu, Citadel for co-located equity
     - Cost: NIC-attached FPGA board $5K-$100K, PCIe FPGA $1K-$10K
     - Tools: Xilinx Vitis HLS (C++ → VHDL/Verilog), Intel OpenCL

  6. SMARTNIC
     - NIC with an onboard CPU (ARM or FPGA) that runs code
     - Packet filtering, parsing, and even simple strategy logic on the NIC
     - Host CPU only sees pre-filtered, pre-parsed data
     - Bluefield (NVIDIA), Pensando, Alveo (AMD/Xilinx)
     - Latency: ~500ns–1µs for SmartNIC processing + DMA to host

  ─────────────────────────────────────────────────────────────

  HUGE PAGES:
    - Normal page size: 4KB
    - HugePage size: 2MB (or 1GB)
    - DPDK uses huge pages to avoid TLB misses when accessing NIC buffers
    - Allocate: echo 512 > /proc/sys/vm/nr_hugepages
    - Map: mmap(NULL, 2MB, PROT_RW, MAP_HUGETLB | MAP_ANON | MAP_PRIVATE, ...)
    - Why: With 512 x 2MB pages → 1GB of NIC buffer with 512 TLB entries
      vs 1GB with normal pages → 262,144 TLB entries → constant TLB misses

  BUSY POLLING:
    - SO_BUSY_POLL socket option (Linux): tells kernel not to sleep
    - NAPI busy polling: kernel polls NIC on same CPU before sleeping
    - Better than polling from user space, worse than full bypass
    - Enable: sysctl net.core.busy_read=50 (50µs budget for busy poll)

  KERNEL TUNING (before kernel bypass):
    sysctl -w net.core.rmem_max=268435456     # 256MB receive buffer
    sysctl -w net.core.wmem_max=268435456     # 256MB send buffer
    sysctl -w net.ipv4.tcp_timestamps=0       # disable TCP timestamps
    sysctl -w net.ipv4.tcp_sack=0             # disable SACK
    sysctl -w net.ipv4.tcp_low_latency=1      # preempt ack coalescing
    ethtool -C eth0 rx-usecs 0                # disable IRQ coalescing
    ethtool -G eth0 rx 4096 tx 4096           # large ring buffers

  TRADING USE CASE:
    A co-located HFT firm's market data path:
      Exchange NIC (multicast ITCH) →
      Solarflare NIC (kernel bypass) →
      DPDK poll thread (core 0, pinned) →
      ITCH parser (L → H byte swap, decode message type) →
      Order book update (L54) →
      Strategy evaluation (L61) →
      FIX order builder (L56) →
      Solarflare NIC TX (kernel bypass) →
      Exchange TCP socket
    Total: ~800ns wire-to-wire at co-location.

  COMMON MISTAKES:
    - Thinking -O3 alone will get you to µs latency — it won't without kernel bypass
    - Running DPDK on a VM (hypervisor adds latency; DPDK needs bare metal or SR-IOV)
    - Not allocating huge pages before running DPDK (it will fail to init)
    - Using DPDK on the same NIC as your OS traffic (bypass = NIC is owned by DPDK)
    - FPGA over-engineering: most solo traders don't need FPGA — DPDK is sufficient
    - Forgetting CPU isolation: DPDK poll core must be isolated (isolcpus=0,1 in grub)
*/

// ============================================================
// SIMULATION: What kernel bypass looks like conceptually in C++
// The actual DPDK API is C and requires a DPDK-linked binary.
// This shows the POLLING ARCHITECTURE that underlies all bypass.
// ============================================================

#include <iostream>
#include <cstdint>
#include <cstring>
#include <vector>
#include <chrono>
#include <atomic>
#include <thread>
#include <array>

// ============================================================
// SIMULATED NIC RING BUFFER
// Mimics how DPDK's rte_mbuf ring works:
// Producer (NIC DMA / simulated feed) writes to head.
// Consumer (poll thread) reads from tail.
// No locks. No kernel. Just memory and atomics.
// ============================================================

constexpr int RING_SIZE = 4096;  // must be power of 2
constexpr int RING_MASK = RING_SIZE - 1;
constexpr int MAX_PKT   = 1500;  // max packet size in bytes

struct alignas(64) Packet {
    uint8_t  data[MAX_PKT];  // raw bytes (ITCH message, FIX, etc.)
    uint16_t len;            // actual payload length
    uint64_t arrival_ns;     // when NIC received it (hardware timestamp)
    uint32_t seq;            // sequence number (for gap detection)
    char     pad[46];        // pad to 1600 bytes for cache alignment
};

struct alignas(64) NicRing {
    alignas(64) std::atomic<uint64_t> head{0};  // producer advances
    alignas(64) std::atomic<uint64_t> tail{0};  // consumer advances
    Packet bufs[RING_SIZE];                       // DMA target memory

    bool enqueue(const uint8_t* pkt, uint16_t len, uint64_t ns, uint32_t seq) {
        uint64_t h = head.load(std::memory_order_relaxed);
        uint64_t t = tail.load(std::memory_order_acquire);
        if (h - t >= RING_SIZE) return false;  // ring full — drop packet

        Packet& slot = bufs[h & RING_MASK];
        memcpy(slot.data, pkt, len);
        slot.len        = len;
        slot.arrival_ns = ns;
        slot.seq        = seq;

        head.store(h + 1, std::memory_order_release);  // publish to consumer
        return true;
    }

    bool dequeue(Packet& out) {
        uint64_t t = tail.load(std::memory_order_relaxed);
        uint64_t h = head.load(std::memory_order_acquire);
        if (t == h) return false;  // ring empty

        out = bufs[t & RING_MASK];
        tail.store(t + 1, std::memory_order_release);
        return true;
    }
};

// ============================================================
// SIMULATED ITCH PARSER (same as L47, shown here in bypass context)
// In a real DPDK system, this runs on the poll core, no kernel.
// ============================================================

struct ITCH_AddOrder {
    char     msg_type;   // 'A'
    uint32_t seq;
    uint64_t order_ref;
    char     side;       // 'B' or 'S'
    int32_t  qty;
    char     symbol[8];
    int64_t  price;
} __attribute__((packed));

struct BookStats {
    int     packets_processed = 0;
    int     adds              = 0;
    int64_t last_price        = 0;
};

void parse_itch_packet(const uint8_t* data, uint16_t len, BookStats& stats) {
    if (len < 1) return;

    switch (data[0]) {
        case 'A': {
            if (len < sizeof(ITCH_AddOrder)) break;
            const auto* msg = reinterpret_cast<const ITCH_AddOrder*>(data);
            stats.adds++;
            stats.last_price = msg->price;
            break;
        }
        default:
            break;
    }
    stats.packets_processed++;
}

// ============================================================
// POLL LOOP — the heart of kernel bypass
// In production: this thread is pinned to an isolated core,
// busy-polls the NIC ring buffer continuously, processes each
// packet inline (no queue, no thread handoff for the hot path).
// ============================================================

void kernel_bypass_poll_loop(NicRing& ring,
                              std::atomic<bool>& running,
                              BookStats& stats) {
    Packet pkt;
    uint64_t idle_spins = 0;

    while (running.load(std::memory_order_relaxed)) {
        if (ring.dequeue(pkt)) {
            // Process inline — no system call, no lock, no context switch
            parse_itch_packet(pkt.data, pkt.len, stats);
            idle_spins = 0;
        } else {
            ++idle_spins;
            // In real DPDK: _mm_pause() here, or adaptive batching
#if defined(__x86_64__) || defined(_M_X64)
#  if defined(__GNUC__) || defined(__clang__)
            __asm__ volatile("pause" ::: "memory");
#  elif defined(_MSC_VER)
            _mm_pause();
#  endif
#endif
        }
    }
    (void)idle_spins;
}

// ============================================================
// LATENCY COMPARISON TABLE (simulated output)
// ============================================================

void print_latency_comparison() {
    std::cout << "\n=== Latency stack comparison ===\n";
    std::cout << "  Method              | Wire-to-app | Notes\n";
    std::cout << "  ------------------- | ----------- | ----------------------------------\n";
    std::cout << "  Normal BSD socket   |   10-30µs   | interrupt + kernel stack + syscall\n";
    std::cout << "  SO_BUSY_POLL        |    5-10µs   | kernel polls NIC, skips some sleep\n";
    std::cout << "  AF_XDP              |    3-5µs    | eBPF hook, kernel still involved\n";
    std::cout << "  Solarflare OO       |    1-2µs    | user-space driver, same socket API\n";
    std::cout << "  DPDK                |    0.5-2µs  | full bypass, polling, hugepages\n";
    std::cout << "  FPGA (SmartNIC)     |    0.2-0.5µs| parsing/logic in hardware\n";
    std::cout << "  FPGA (PCIe/co-lo)   |    0.1-0.2µs| fully hardware-defined hot path\n";
    std::cout << "\n";
    std::cout << "  Co-lo physics limit: ~100ns RTT to exchange matching engine\n";
    std::cout << "  Speed of light: 1µs per 300m of fiber\n";
}

void print_dpdk_setup_notes() {
    std::cout << "\n=== DPDK setup outline (Linux) ===\n";
    std::cout << "  # 1. Allocate huge pages\n";
    std::cout << "  echo 1024 > /proc/sys/vm/nr_hugepages\n";
    std::cout << "  mkdir -p /mnt/huge && mount -t hugetlbfs none /mnt/huge\n\n";
    std::cout << "  # 2. Bind NIC to DPDK driver (removes NIC from OS)\n";
    std::cout << "  dpdk-devbind.py --bind=vfio-pci 0000:01:00.0\n\n";
    std::cout << "  # 3. Build your app against DPDK\n";
    std::cout << "  g++ -O3 -march=native $(pkg-config --cflags --libs libdpdk) app.cpp\n\n";
    std::cout << "  # 4. Run with EAL options\n";
    std::cout << "  ./trading_engine -l 0,1 --socket-mem=1024 -- --port=0\n";
    std::cout << "  #   -l 0,1 : use cores 0 and 1\n";
    std::cout << "  #   socket-mem=1024 : 1GB huge page memory on NUMA node 0\n";
}

// ============================================================
// MAIN: demonstrate simulated bypass ring
// ============================================================

int main() {
    print_latency_comparison();
    print_dpdk_setup_notes();

    // -------------------------------------------------------
    // DEMO: NIC ring buffer (simulating kernel bypass DMA)
    // -------------------------------------------------------

    std::cout << "\n=== Simulated NIC ring buffer (bypassing the kernel) ===\n";

    NicRing ring;
    BookStats stats;
    std::atomic<bool> running{true};

    // Simulated ITCH Add Order packet
    ITCH_AddOrder add{};
    add.msg_type  = 'A';
    add.seq       = 1;
    add.order_ref = 12345678;
    add.side      = 'B';
    add.qty       = 100;
    add.price     = 1825000;  // $182.50 in ticks (× 10000)
    memcpy(add.symbol, "SPY     ", 8);

    // Start poll thread (represents the DPDK poll core)
    std::thread poll_thread([&]() {
        kernel_bypass_poll_loop(ring, running, stats);
    });

    // Simulated NIC DMA: inject 1000 packets into ring
    auto t0 = std::chrono::steady_clock::now();

    for (int i = 0; i < 1000; ++i) {
        add.seq = static_cast<uint32_t>(i);
        add.price = 1825000 + (i % 10);

        uint64_t now_ns = static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::steady_clock::now().time_since_epoch()).count());

        // Retry if ring full (in real DPDK: NIC drops the packet)
        while (!ring.enqueue(reinterpret_cast<const uint8_t*>(&add),
                              sizeof(add), now_ns, add.seq)) {
            std::this_thread::yield();
        }
    }

    // Give poll thread time to drain
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
    running.store(false, std::memory_order_relaxed);
    poll_thread.join();

    auto t1 = std::chrono::steady_clock::now();
    uint64_t elapsed_ns = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());

    std::cout << "  Processed: " << stats.packets_processed << " packets\n";
    std::cout << "  Add orders: " << stats.adds << "\n";
    std::cout << "  Last price: " << stats.last_price << " ticks\n";
    std::cout << "  Total time: " << elapsed_ns / 1000 << "µs\n";
    std::cout << "  Throughput: "
              << (stats.packets_processed * 1000ULL * 1000000ULL) / (elapsed_ns ? elapsed_ns : 1)
              << " packets/sec\n";

    // -------------------------------------------------------
    // FPGA NOTE
    // -------------------------------------------------------

    std::cout << "\n=== FPGA overview ===\n";
    std::cout << "  FPGA does not run C++ — it runs in parallel hardware gates.\n";
    std::cout << "  You describe logic in VHDL, Verilog, or HLS (High-Level Synthesis).\n";
    std::cout << "  Xilinx Vitis HLS can compile a subset of C++ to FPGA logic.\n\n";
    std::cout << "  Example HLS kernel (conceptually):\n";
    std::cout << "    void parse_itch(hls::stream<ap_uint<8>>& in,\n";
    std::cout << "                    hls::stream<Order>& out) {\n";
    std::cout << "        #pragma HLS PIPELINE II=1   // one output per clock\n";
    std::cout << "        ap_uint<8> byte = in.read();\n";
    std::cout << "        // parse and output an Order every clock cycle\n";
    std::cout << "    }\n\n";
    std::cout << "  At 300MHz: 1 cycle = 3.3ns. ITCH parsing in <10ns.\n";
    std::cout << "  But: FPGA has fixed logic — strategy changes require recompile (hours).\n";
    std::cout << "  Use FPGA for: feed parsing, order encoding, checksum, timestamping.\n";
    std::cout << "  Use CPU for: strategy logic (flexible, fast to change).\n";

    std::cout << "\n=== Phase 5 (Low-Latency Systems) complete ===\n";
    std::cout << "  L43: Cache efficiency (AoS vs SoA, prefetching)\n";
    std::cout << "  L44: Memory pools (pool allocator, arena allocator)\n";
    std::cout << "  L45: SIMD (SSE2, AVX2, auto-vectorization)\n";
    std::cout << "  L46: Network sockets (TCP_NODELAY, non-blocking)\n";
    std::cout << "  L47: Multicast UDP (ITCH, gap detection)\n";
    std::cout << "  L48: epoll/select (event-driven I/O)\n";
    std::cout << "  L49: mmap (memory-mapped files, shared memory IPC)\n";
    std::cout << "  L50: rdtsc + profiling (latency histograms, perf)\n";
    std::cout << "  L51: Compiler optimizations (-O3, PGO, always_inline)\n";
    std::cout << "  L52: Kernel bypass + DPDK (this file)\n";
    std::cout << "\nNext: Phase 6 — Trading Systems Implementation (L53–L65)\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Firm A (normal sockets):
        Market data arrives → 15µs later, strategy sees it → order sent at 16µs
        Competitor B (DPDK, same co-lo):
        Market data arrives → 1µs later, strategy sees it → order sent at 1.5µs
      B is 10x faster. A NEVER wins the race. The C++ optimization ceiling
      without kernel bypass is ~10µs at co-location.

      When to invest in kernel bypass:
        - Solo trader testing strategies: NOT NEEDED (use normal sockets)
        - Live trading, latency-sensitive but not ultra-HFT: Solarflare OpenOnload
        - Co-located, competing on speed: DPDK minimum, FPGA if you need sub-µs
        - Market-making on equity: FPGA for feed parsing + CPU for quoting logic

      Hardware cost guide:
        - Mellanox ConnectX-5 NIC: ~$500 (works with DPDK + OpenOnload)
        - Solarflare X2 NIC: ~$1,000 (OpenOnload, sub-µs)
        - Alveo U50 FPGA: ~$3,000 (PCIe FPGA, HLS programmable)
        - Xilinx VCU1525: ~$2,000 (ex-mining FPGA, repurposable)
        - Co-location rack at CME Aurora: ~$5,000-$15,000/month
    */
}
