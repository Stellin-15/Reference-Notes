// ============================================================
// L40: Thread Affinity and CPU Pinning
// ============================================================
// WHAT: CPU pinning locks a thread to a specific CPU core,
//       preventing the OS scheduler from migrating it. NUMA
//       awareness ensures threads access memory on their local
//       NUMA node. Both techniques eliminate key sources of
//       non-deterministic latency in HFT systems.
// WHY (TRADING): When an OS migrates a thread from core 0 to
//   core 3, it pays:
//   - 1-5ms OS scheduler latency (the thread is paused)
//   - L1/L2 cache is cold on the new core (many cache misses)
//   - TLB must be rebuilt on the new core
//   Total: up to 5ms of extra latency per migration.
//   In HFT, we cannot afford even 50µs. Pinning the market
//   data thread to core 0 guarantees it ALWAYS runs there —
//   cold cache never happens, scheduler never intervenes.
//   Result: consistent sub-microsecond latency instead of
//   occasional 1ms+ spikes.
// PHASE: Concurrency
// ============================================================

/*
  CONCEPT OVERVIEW:

  THREAD AFFINITY:
    Restricts a thread to run only on specified CPU core(s).
    Linux API:  pthread_setaffinity_np(thread, cpuset_size, &cpuset)
    Windows API: SetThreadAffinityMask(handle, mask)
    CPU set manipulation (Linux):
      cpu_set_t cpuset;
      CPU_ZERO(&cpuset);           — clear all cores
      CPU_SET(core_id, &cpuset);   — add core_id to the set
      CPU_CLR(core_id, &cpuset);   — remove core_id
      CPU_ISSET(core_id, &cpuset)  — check if core is in set

  ISOLCPUS (Linux kernel parameter):
    Boot param: isolcpus=2,3,4,5  — reserve cores 2-5 for HFT threads
    OS scheduler NEVER assigns normal processes to isolated cores.
    Combined with thread affinity: guaranteed exclusive core ownership.
    Set in /etc/default/grub: GRUB_CMDLINE_LINUX="isolcpus=2,3,4,5"
    Verify: cat /sys/devices/system/cpu/isolated

  NUMA (Non-Uniform Memory Access):
    Multi-socket servers have 2+ NUMA nodes.
    Core 0-7 on socket 0 → local DRAM (fast: 80ns access)
    Core 8-15 on socket 1 → remote DRAM from socket 0 (slow: 160ns access)
    If your trading thread is on core 0 but its data is allocated
    on socket 1's memory, EVERY memory access is 2x slower.
    Fix: numa_alloc_onnode() to allocate on local node.
    Or: numactl --membind=0 --cpunodebind=0 ./trading_engine

  THREAD PRIORITIES (Linux):
    Default scheduler: SCHED_OTHER (fair, time-sliced, unpredictable)
    Real-time scheduler: SCHED_FIFO (run until preempted by higher priority)
    Set with: sched_setscheduler(0, SCHED_FIFO, &param) (requires root)
    SCHED_FIFO threads NEVER get context-switched unless:
      1. A higher-priority RT thread needs the core, OR
      2. The thread blocks (I/O, mutex, sleep)
    In production HFT: market data thread is SCHED_FIFO, priority 99.

  HYPERTHREADING:
    Each physical core has 2 logical cores (hyperthreads) on x86.
    Core 0 physical = logical cores 0 and 1.
    Two hyperthreads share: execution units, L1 cache, L2 cache.
    If you pin thread A to core 0 and thread B to core 1 (same physical core):
    they share L1 cache and compete for execution units.
    In HFT: disable hyperthreading or pin critical threads to different physical cores.
    Check physical layout: cat /sys/devices/system/cpu/cpu0/topology/thread_siblings_list

  TRADING THREAD MAP:
    Physical Core 0 (logical core 0):  Market data feed thread (SCHED_FIFO, prio 99)
    Physical Core 1 (logical core 2):  Order book + strategy thread (SCHED_FIFO, prio 90)
    Physical Core 2 (logical core 4):  Execution / gateway thread (SCHED_FIFO, prio 80)
    Physical Core 3 (logical core 6):  Risk monitoring thread (SCHED_OTHER)
    Physical Core 4 (logical core 8):  Async logger thread (SCHED_OTHER, nice 10)
    Remaining cores: OS + other processes

  COMMON MISTAKES:
    - Pinning all threads to core 0 — they compete with each other
    - Pinning to a logical core that shares a physical core with another hot thread
    - Forgetting to pin memory allocation (NUMA) — pinned thread reads remote memory
    - Not requesting root/CAP_SYS_NICE for SCHED_FIFO (silently fails without it)
    - Disabling hyperthreading in BIOS but not updating the core map
*/

#include <iostream>
#include <thread>
#include <chrono>
#include <vector>
#include <atomic>
#include <string>
#include <sstream>
#include <cstdint>

// Platform-specific affinity headers
#if defined(__linux__)
#  include <pthread.h>
#  include <sched.h>
#  include <unistd.h>
#  define PLATFORM_LINUX 1
#elif defined(_WIN32)
#  include <windows.h>
#  define PLATFORM_WIN32 1
#endif

using namespace std::chrono_literals;

// ============================================================
// CROSS-PLATFORM PIN_THREAD UTILITY
// ============================================================

// Pin the current thread (or a given thread) to a specific CPU core.
// Returns true on success, false if the OS call failed or is unsupported.
bool pin_thread_to_core(int core_id) {
#if defined(PLATFORM_LINUX)
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);         // clear all bits
    CPU_SET(core_id, &cpuset); // set only core_id

    int rc = pthread_setaffinity_np(
        pthread_self(),        // current thread's pthread handle
        sizeof(cpu_set_t),
        &cpuset);

    if (rc != 0) {
        std::cerr << "  [pin_thread] pthread_setaffinity_np failed: "
                  << rc << "\n";
        return false;
    }
    return true;

#elif defined(PLATFORM_WIN32)
    DWORD_PTR mask = DWORD_PTR(1) << core_id;
    DWORD_PTR result = SetThreadAffinityMask(GetCurrentThread(), mask);
    if (result == 0) {
        std::cerr << "  [pin_thread] SetThreadAffinityMask failed\n";
        return false;
    }
    return true;

#else
    (void)core_id;
    std::cerr << "  [pin_thread] Thread affinity not supported on this platform\n";
    return false;
#endif
}

// Get the current logical CPU core this thread is running on.
int get_current_core() {
#if defined(PLATFORM_LINUX)
    return sched_getcpu();   // Linux syscall — returns logical CPU id
#elif defined(PLATFORM_WIN32)
    return static_cast<int>(GetCurrentProcessorNumber());
#else
    return -1;
#endif
}

// Get number of logical CPUs available
int num_logical_cpus() {
    return static_cast<int>(std::thread::hardware_concurrency());
}

// ============================================================
// LATENCY SAMPLER — measures jitter on a pinned vs unpinned thread
// ============================================================

struct LatencyResult {
    std::string label;
    double      min_ns;
    double      max_ns;
    double      avg_ns;
    int         samples;
};

LatencyResult measure_loop_jitter(const std::string& label,
                                  bool pin_to_core,
                                  int core_id,
                                  int iters)
{
    if (pin_to_core) {
        pin_thread_to_core(core_id);
    }

    // Warm up
    for (int i = 0; i < 1000; ++i) {
        volatile int x = i * 2;
        (void)x;
    }

    double min_ns = 1e18, max_ns = 0, total_ns = 0;

    for (int i = 0; i < iters; ++i) {
        auto t0 = std::chrono::steady_clock::now();

        // Simulate one tick processing cycle
        volatile double sum = 0.0;
        for (int j = 0; j < 50; ++j) sum += j * 0.1;
        (void)sum;

        auto t1 = std::chrono::steady_clock::now();
        double ns = static_cast<double>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());

        if (ns < min_ns) min_ns = ns;
        if (ns > max_ns) max_ns = ns;
        total_ns += ns;
    }

    return {label, min_ns, max_ns, total_ns / iters, iters};
}

// ============================================================
// NUMA TOPOLOGY HELPER
// ============================================================

void print_cpu_topology() {
    int logical_cpus = num_logical_cpus();
    std::cout << "  Logical CPU count: " << logical_cpus << "\n";

#if defined(PLATFORM_LINUX)
    // Print NUMA node info if available
    std::cout << "  Checking NUMA nodes (Linux):\n";
    for (int cpu = 0; cpu < std::min(logical_cpus, 8); ++cpu) {
        // Read NUMA node from sysfs
        std::string path = "/sys/devices/system/cpu/cpu"
                         + std::to_string(cpu) + "/topology/physical_package_id";
        FILE* f = fopen(path.c_str(), "r");
        if (f) {
            int socket = -1;
            if (fscanf(f, "%d", &socket) == 1) {
                std::cout << "    CPU " << cpu << " → socket " << socket << "\n";
            }
            fclose(f);
        }
    }

    // Check for isolated CPUs
    FILE* f = fopen("/sys/devices/system/cpu/isolated", "r");
    if (f) {
        char buf[256] = {};
        if (fgets(buf, sizeof(buf), f)) {
            std::cout << "  Isolated CPUs: " << buf;
        }
        fclose(f);
    } else {
        std::cout << "  Isolated CPUs: (none — isolcpus not configured)\n";
    }
#else
    std::cout << "  NUMA info: use Sysinternals CoreInfo on Windows\n";
#endif
}

// ============================================================
// THREAD STRUCT — models a trading system thread with affinity
// ============================================================

struct TradingThread {
    std::string name;
    int         core_id;
    int         priority;   // 0 = normal, 1-99 = RT priority (Linux only)
    std::string role;
};

// Describe the thread assignment plan (can't always apply in sandbox)
void describe_thread_map(const std::vector<TradingThread>& threads) {
    std::cout << "  Trading system thread map:\n";
    for (const auto& t : threads) {
        std::cout << "    Core " << t.core_id
                  << " [" << t.name << "]: " << t.role;
        if (t.priority > 0) {
            std::cout << " (RT prio=" << t.priority << ")";
        }
        std::cout << "\n";
    }
}

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // CPU TOPOLOGY
    // -------------------------------------------------------

    std::cout << "=== CPU topology ===\n";
    print_cpu_topology();

    // -------------------------------------------------------
    // PIN MAIN THREAD AND VERIFY
    // -------------------------------------------------------

    std::cout << "\n=== Thread affinity: pin main thread ===\n";

    {
        int before = get_current_core();
        std::cout << "  Running on core: " << before << " (before pin)\n";

        int target_core = 0;   // pin to core 0
        bool ok = pin_thread_to_core(target_core);

        if (ok) {
            int after = get_current_core();
            std::cout << "  Pinned to core " << target_core
                      << ". Now running on: " << after << "\n";
        } else {
            std::cout << "  Affinity not available (needs privileges or Linux)\n";
        }
    }

    // -------------------------------------------------------
    // SPAWN PINNED THREAD
    // -------------------------------------------------------

    std::cout << "\n=== Spawn pinned threads ===\n";

    {
        int logical_cpus = num_logical_cpus();
        // Pick 2 cores (or fewer if system has only 1 or 2)
        std::vector<int> cores = {0};
        if (logical_cpus > 1) cores.push_back(1);

        std::vector<std::thread> threads;
        for (int core : cores) {
            threads.emplace_back([core]() {
                // Pin this thread to its designated core
                bool ok = pin_thread_to_core(core);
                int actual = get_current_core();
                std::cout << "  [Thread for core " << core << "] "
                          << "pinned=" << ok
                          << " running_on=" << actual << "\n";

                // Simulate trading work
                volatile double sum = 0.0;
                for (int i = 0; i < 100000; ++i) sum += i * 0.001;
                (void)sum;
            });
        }
        for (auto& t : threads) t.join();
    }

    // -------------------------------------------------------
    // JITTER MEASUREMENT — pinned vs unpinned
    // -------------------------------------------------------

    std::cout << "\n=== Latency jitter: pinned vs unpinned ===\n";

    {
        const int ITERS = 10000;

        LatencyResult unpinned_result, pinned_result;

        // Unpinned: OS can migrate thread between iterations
        std::thread t1([&unpinned_result, ITERS]() {
            unpinned_result = measure_loop_jitter("unpinned", false, -1, ITERS);
        });
        t1.join();

        // Pinned: stays on core 0, cache stays warm
        int target = std::min(0, num_logical_cpus() - 1);
        std::thread t2([&pinned_result, ITERS, target]() {
            pinned_result = measure_loop_jitter("pinned-core0", true, target, ITERS);
        });
        t2.join();

        auto print_result = [](const LatencyResult& r) {
            std::cout << "  [" << r.label << "] "
                      << "min=" << r.min_ns << "ns "
                      << "avg=" << r.avg_ns << "ns "
                      << "max=" << r.max_ns << "ns "
                      << "(n=" << r.samples << ")\n";
        };
        print_result(unpinned_result);
        print_result(pinned_result);

        std::cout << "  NOTE: Improvement is most visible on loaded production systems.\n"
                  << "  On a dev machine with few threads: similar results.\n"
                  << "  On a production trading server: pinned reduces max latency 10-100x.\n";
    }

    // -------------------------------------------------------
    // RECOMMENDED THREAD MAP
    // -------------------------------------------------------

    std::cout << "\n=== Recommended trading thread map ===\n";

    {
        std::vector<TradingThread> thread_map = {
            {"FeedThread",   0, 99, "Recv multicast UDP, parse ITCH, push to SPSC"},
            {"BookThread",   2, 90, "Update order book, compute BBO, push to strategy"},
            {"StratThread",  4, 80, "Evaluate signals, generate orders, risk pre-check"},
            {"ExecThread",   6, 70, "Send FIX orders to exchange gateway"},
            {"RiskThread",   8,  0, "Monitor positions, PnL, kill switch check"},
            {"LoggerThread", 10,  0, "Drain async log queue to disk (nice +10)"},
        };
        describe_thread_map(thread_map);

        std::cout << "\n  How to apply this map in code:\n"
                  << "  1. Create each thread (std::thread or JoinableThread)\n"
                  << "  2. Immediately call pin_thread_to_core(core_id) from INSIDE the thread\n"
                  << "  3. Set scheduler: sched_setscheduler(0, SCHED_FIFO, &param)  [Linux root]\n"
                  << "  4. Pre-fault stack: touch each page to avoid page faults during trading\n"
                  << "  5. mlockall(MCL_CURRENT | MCL_FUTURE) to prevent paging  [Linux root]\n";
    }

    // -------------------------------------------------------
    // HYPERTHREADING NOTE
    // -------------------------------------------------------

    std::cout << "\n=== Hyperthreading note ===\n";

    std::cout << "  x86_64: each physical core = 2 logical cores (hyperthreads)\n"
              << "  Physical core 0 = logical 0 (hyperthread 0) + logical 1 (hyperthread 1)\n"
              << "  If you pin FeedThread to logical 0 and BookThread to logical 1:\n"
              << "  → they SHARE L1/L2 cache and execution units → slower than expected\n"
              << "  Best practice: pin each hot thread to a different physical core\n"
              << "  Check: cat /sys/devices/system/cpu/cpu0/topology/thread_siblings_list\n"
              << "  Recommended: disable SMT in BIOS for lowest HFT latency\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Complete thread startup sequence with affinity:

        void TradingSystem::start() {
            // Pin and start each thread in reverse priority order
            // (risk up first, data last — risk must be monitoring before data flows)

            risk_thread_ = JoinableThread([this]() {
                pin_thread_to_core(8);   // physical core 4
                // sched_setscheduler(SCHED_OTHER) — already default
                run_risk();
            });

            exec_thread_ = JoinableThread([this]() {
                pin_thread_to_core(6);   // physical core 3
                set_realtime_priority(70);
                run_exec();
            });

            strat_thread_ = JoinableThread([this]() {
                pin_thread_to_core(4);   // physical core 2
                set_realtime_priority(80);
                run_strategy();
            });

            book_thread_ = JoinableThread([this]() {
                pin_thread_to_core(2);   // physical core 1
                set_realtime_priority(90);
                run_book();
            });

            feed_thread_ = JoinableThread([this]() {
                pin_thread_to_core(0);   // physical core 0 — hottest thread
                set_realtime_priority(99);
                // Pre-fault stack (allocate max possible stack usage)
                char stack[65536];
                memset(stack, 0, sizeof(stack));
                run_feed();
            });
        }

        void set_realtime_priority(int prio) {
            struct sched_param param;
            param.sched_priority = prio;
            sched_setscheduler(0, SCHED_FIFO, &param);  // 0 = current thread
        }
    */
}
