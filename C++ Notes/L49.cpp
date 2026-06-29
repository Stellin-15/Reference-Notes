// ============================================================
// L49: Memory-Mapped Files (mmap)
// ============================================================
// WHAT: mmap() maps a file (or anonymous memory) directly into
//       the process's virtual address space. Reads and writes
//       to that memory region go directly to the file — no
//       read()/write() syscalls in the hot path. The OS handles
//       paging lazily. Shared memory (shm_open) allows two
//       processes to share memory with zero copies.
// WHY (TRADING): Two key use cases:
//   1. Backtesting: map 2 years of binary tick data into memory
//      at startup. Replay by iterating a pointer — no read()
//      per tick, no kernel overhead. Reads at memory bus speed.
//   2. IPC between processes: feed handler process and strategy
//      process share a ring buffer via shared memory. No copy,
//      no network, no pipe overhead. Latency: < 100ns.
//   Compare to file read(): each tick requires a read() syscall
//   (200-500ns overhead). mmap: zero syscalls after initial setup.
// PHASE: Low-Latency Systems
// ============================================================

/*
  CONCEPT OVERVIEW:

  MMAP BASICS (Linux/macOS):
    void* ptr = mmap(NULL, size, PROT_READ | PROT_WRITE,
                     MAP_SHARED, fd, 0);
    After this: ptr[i] reads/writes byte i of the file.
    munmap(ptr, size)  — unmap (does NOT close the file)
    msync(ptr, size, MS_SYNC)  — force flush to disk (expensive)
    madvise(ptr, size, MADV_SEQUENTIAL)  — hint: read forward only

  PROTECTION FLAGS:
    PROT_READ   — read-only mapping
    PROT_WRITE  — writable mapping
    PROT_READ | PROT_WRITE  — read-write

  MAPPING FLAGS:
    MAP_SHARED   — writes go to the file, visible to other processes
    MAP_PRIVATE  — copy-on-write: writes don't affect the file
    MAP_ANON     — anonymous (no backing file, like malloc but larger)
    MAP_LOCKED   — pin pages in RAM, prevent paging (needs privileges)
    MAP_POPULATE — pre-fault all pages (no page faults during access)

  PAGE FAULTS:
    When you first access a page (4KB) that's mapped but not loaded,
    the OS pauses your thread to load the page from disk. This takes
    100µs-10ms per fault. In trading: unacceptable.
    Fix: touch all pages at startup (mlockall, MAP_POPULATE, or
    manually walking the array). After touching, no more faults.

  SHARED MEMORY (IPC):
    shm_open("/my_shm", O_CREAT | O_RDWR, 0600) — create named shared memory
    ftruncate(shm_fd, size)                       — set size
    mmap() both processes to the same shm object
    Now: both processes read/write the same physical memory.
    shm_unlink("/my_shm")                         — clean up name

  WINDOWS EQUIVALENT:
    CreateFileMapping()  — create/open file mapping object
    MapViewOfFile()      — map into address space
    UnmapViewOfFile()    — unmap
    CloseHandle()        — close the mapping/file handle
    CreateFileMapping(INVALID_HANDLE_VALUE) — anonymous (like MAP_ANON)
    CreateFileMapping with name for IPC (shared between processes)

  MADVISE HINTS:
    MADV_SEQUENTIAL  — will read forward: prefetch aggressively
    MADV_RANDOM      — will read randomly: don't prefetch
    MADV_WILLNEED    — hint: load these pages now (async prefetch)
    MADV_DONTNEED    — hint: can evict these pages, we don't need them

  TRADING USE CASE:
    // Tick replay at startup:
    int fd = open("ticks_2024.bin", O_RDONLY);
    fstat(fd, &sb);
    const Tick* ticks = (const Tick*)mmap(NULL, sb.st_size, PROT_READ, MAP_SHARED, fd, 0);
    madvise((void*)ticks, sb.st_size, MADV_SEQUENTIAL);  // hint: read forward
    int n = sb.st_size / sizeof(Tick);
    for (int i = 0; i < n; ++i) strategy.on_tick(ticks[i]);  // no syscall per tick!
    munmap((void*)ticks, sb.st_size);

    // Shared memory ring buffer between feed process and strategy process:
    // Feed process: writes ticks to shared memory ring buffer
    // Strategy process: reads ticks from the same memory region
    // Zero copy, latency < 100ns (compared to pipe: ~1-5µs)

  COMMON MISTAKES:
    - Not pre-faulting pages → random 100µs-10ms spikes during replay
    - Writing to a MAP_SHARED mapping and expecting it to be private (MAP_PRIVATE for that)
    - munmap() before all accesses are done → segfault
    - Not calling ftruncate() before mmap on a new file → bus error
    - Accessing beyond the mapped size → segfault
    - Forgetting to shm_unlink() → shared memory persists across reboots (Linux)
    - On Windows: not CloseHandle()'ing the file mapping object → resource leak
*/

#include <iostream>
#include <cstring>
#include <cstdint>
#include <string>
#include <vector>
#include <chrono>
#include <stdexcept>
#include <atomic>
#include <thread>
#include <cassert>

// Platform-specific mmap headers
#ifdef _WIN32
#  include <windows.h>
   // We'll use Windows CreateFileMapping API
#  define PLATFORM_WIN32 1
#else
#  include <sys/mman.h>
#  include <sys/stat.h>
#  include <fcntl.h>
#  include <unistd.h>
#  define PLATFORM_POSIX 1
#endif

using namespace std::chrono_literals;

// ============================================================
// TICK DATA TYPE — must be trivially copyable for mmap
// ============================================================

#pragma pack(push, 1)  // no padding — exact binary layout
struct Tick {
    uint64_t timestamp_ns;
    int64_t  bid;
    int64_t  ask;
    int32_t  bid_qty;
    int32_t  ask_qty;
    uint32_t seq;
};
#pragma pack(pop)

static_assert(sizeof(Tick) == 32, "Tick must be 32 bytes");

// ============================================================
// CROSS-PLATFORM MMAP WRAPPER
// ============================================================

class MappedFile {
public:
    // Map a file for reading
    static MappedFile open_read(const std::string& path) {
        MappedFile mf;
        mf.size_ = 0;
        mf.ptr_  = nullptr;
        mf.writable_ = false;
        mf.path_ = path;

#ifdef PLATFORM_WIN32
        mf.file_handle_ = CreateFileA(path.c_str(), GENERIC_READ, FILE_SHARE_READ,
                                       nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (mf.file_handle_ == INVALID_HANDLE_VALUE) {
            throw std::runtime_error("Cannot open file: " + path);
        }
        LARGE_INTEGER sz{};
        GetFileSizeEx(mf.file_handle_, &sz);
        mf.size_ = static_cast<size_t>(sz.QuadPart);

        mf.map_handle_ = CreateFileMapping(mf.file_handle_, nullptr, PAGE_READONLY, 0, 0, nullptr);
        if (!mf.map_handle_) {
            CloseHandle(mf.file_handle_);
            throw std::runtime_error("CreateFileMapping failed");
        }
        mf.ptr_ = MapViewOfFile(mf.map_handle_, FILE_MAP_READ, 0, 0, 0);
        if (!mf.ptr_) {
            CloseHandle(mf.map_handle_);
            CloseHandle(mf.file_handle_);
            throw std::runtime_error("MapViewOfFile failed");
        }
#else
        mf.fd_ = ::open(path.c_str(), O_RDONLY);
        if (mf.fd_ < 0) throw std::runtime_error("Cannot open file: " + path);
        struct stat sb{};
        fstat(mf.fd_, &sb);
        mf.size_ = static_cast<size_t>(sb.st_size);
        mf.ptr_  = ::mmap(nullptr, mf.size_, PROT_READ, MAP_SHARED, mf.fd_, 0);
        if (mf.ptr_ == MAP_FAILED) {
            ::close(mf.fd_);
            throw std::runtime_error("mmap failed");
        }
#  ifdef MADV_SEQUENTIAL
        ::madvise(mf.ptr_, mf.size_, MADV_SEQUENTIAL);
#  endif
#endif
        return mf;
    }

    ~MappedFile() {
#ifdef PLATFORM_WIN32
        if (ptr_)        UnmapViewOfFile(ptr_);
        if (map_handle_) CloseHandle(map_handle_);
        if (file_handle_ != INVALID_HANDLE_VALUE) CloseHandle(file_handle_);
#else
        if (ptr_ && ptr_ != MAP_FAILED) ::munmap(ptr_, size_);
        if (fd_ >= 0) ::close(fd_);
#endif
    }

    // Non-copyable, movable
    MappedFile(const MappedFile&)            = delete;
    MappedFile& operator=(const MappedFile&) = delete;
    MappedFile(MappedFile&& o) noexcept {
        *this = std::move(o);
    }
    MappedFile& operator=(MappedFile&& o) noexcept {
        ptr_  = o.ptr_;  size_ = o.size_;  path_ = o.path_;  writable_ = o.writable_;
        o.ptr_ = nullptr; o.size_ = 0;
#ifdef PLATFORM_WIN32
        file_handle_ = o.file_handle_; map_handle_ = o.map_handle_;
        o.file_handle_ = INVALID_HANDLE_VALUE; o.map_handle_ = nullptr;
#else
        fd_ = o.fd_; o.fd_ = -1;
#endif
        return *this;
    }

    const void* data() const { return ptr_; }
    size_t      size() const { return size_; }

    template<typename T>
    const T* as() const { return static_cast<const T*>(ptr_); }

    template<typename T>
    size_t count() const { return size_ / sizeof(T); }

private:
    MappedFile() {
#ifdef PLATFORM_WIN32
        file_handle_ = INVALID_HANDLE_VALUE;
        map_handle_  = nullptr;
#else
        fd_ = -1;
#endif
    }

    void*       ptr_      = nullptr;
    size_t      size_     = 0;
    bool        writable_ = false;
    std::string path_;

#ifdef PLATFORM_WIN32
    HANDLE file_handle_;
    HANDLE map_handle_;
#else
    int fd_ = -1;
#endif
};

// ============================================================
// SHARED MEMORY RING BUFFER (IPC between processes)
// ============================================================

// Layout in shared memory: header at offset 0, then ring buffer data
template<typename T, int N>
struct SharedRingBuffer {
    static_assert((N & (N-1)) == 0, "N must be power of 2");

    alignas(64) std::atomic<uint64_t> write_idx{0};
    char pad1[64 - sizeof(std::atomic<uint64_t>)];  // separate cache lines
    alignas(64) std::atomic<uint64_t> read_idx{0};
    char pad2[64 - sizeof(std::atomic<uint64_t>)];

    T data[N];

    bool push(const T& item) noexcept {
        uint64_t w = write_idx.load(std::memory_order_relaxed);
        uint64_t r = read_idx.load(std::memory_order_acquire);
        if ((w - r) >= N) return false;  // full
        data[w & (N-1)] = item;
        write_idx.store(w + 1, std::memory_order_release);
        return true;
    }

    bool pop(T& item) noexcept {
        uint64_t r = read_idx.load(std::memory_order_relaxed);
        uint64_t w = write_idx.load(std::memory_order_acquire);
        if (r == w) return false;  // empty
        item = data[r & (N-1)];
        read_idx.store(r + 1, std::memory_order_release);
        return true;
    }
};

using TickRing = SharedRingBuffer<Tick, 4096>;

// ============================================================
// WRITE TEST FILE
// ============================================================

bool write_tick_file(const std::string& path, int count) {
    FILE* f = fopen(path.c_str(), "wb");
    if (!f) return false;
    for (int i = 0; i < count; ++i) {
        Tick t{};
        t.timestamp_ns = uint64_t(1000000000ULL + i * 1000);
        t.bid          = int64_t(1825000 + (i % 100) * 10);
        t.ask          = t.bid + 100;
        t.bid_qty      = int32_t(100 + i % 50);
        t.ask_qty      = int32_t(150 + i % 50);
        t.seq          = uint32_t(i);
        fwrite(&t, sizeof(Tick), 1, f);
    }
    fclose(f);
    return true;
}

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // WRITE + MMAP READ DEMO
    // -------------------------------------------------------

    std::cout << "=== mmap tick file replay ===\n";

    {
        const std::string tick_file = "ticks_mmap_demo.bin";
        const int TICK_COUNT = 10000;

        // Write test data using normal file I/O
        if (!write_tick_file(tick_file, TICK_COUNT)) {
            std::cout << "  Could not write test file — skipping mmap demo\n";
        } else {
            std::cout << "  Wrote " << TICK_COUNT << " ticks (" << TICK_COUNT * sizeof(Tick)
                      << " bytes)\n";

            try {
                MappedFile mapped = MappedFile::open_read(tick_file);
                const Tick* ticks = mapped.as<Tick>();
                size_t      n     = mapped.count<Tick>();
                std::cout << "  Mapped " << n << " ticks\n";

                // Replay: iterate the mapped array — zero read() syscalls
                auto t0 = std::chrono::steady_clock::now();

                double sum_bid = 0.0;
                for (size_t i = 0; i < n; ++i) {
                    sum_bid += ticks[i].bid;  // access mapped memory directly
                }

                auto t1 = std::chrono::steady_clock::now();
                auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count();

                std::cout << "  Replayed " << n << " ticks in " << ns << "ns\n";
                std::cout << "  Per tick: " << ns / n << "ns\n";
                std::cout << "  Avg bid: $" << (sum_bid / n) / 10000.0 << "\n";
                std::cout << "  First tick: bid=$" << ticks[0].bid / 10000.0
                          << " seq=" << ticks[0].seq << "\n";
                std::cout << "  Last tick:  bid=$" << ticks[n-1].bid / 10000.0
                          << " seq=" << ticks[n-1].seq << "\n";
            }
            catch (const std::exception& e) {
                std::cout << "  mmap failed: " << e.what() << "\n";
            }
        }
    }

    // -------------------------------------------------------
    // MMAP vs READ BENCHMARK (conceptual)
    // -------------------------------------------------------

    std::cout << "\n=== mmap vs read() performance ===\n";

    std::cout << "  read() per tick:      ~200-500ns (syscall overhead)\n"
              << "  mmap (warm cache):    ~1-5ns (just a memory load)\n"
              << "  mmap (cold, HDD):     ~100µs per page fault (4KB = 128 ticks)\n"
              << "  mmap (cold, SSD):     ~10-50µs per page fault\n"
              << "  mmap (RAM, pre-touched): ~1ns (no page faults)\n"
              << "\n"
              << "  Fix cold page faults: madvise(MADV_WILLNEED) at startup\n"
              << "  Or: walk the entire array before trading starts\n";

    // -------------------------------------------------------
    // SHARED MEMORY IPC DEMO
    // -------------------------------------------------------

    std::cout << "\n=== Shared memory ring buffer (same process, 2 threads) ===\n";

    {
        // Allocate the ring buffer as anonymous mapped memory
        // In production: use shm_open() to share between processes
#ifdef PLATFORM_POSIX
        TickRing* ring = static_cast<TickRing*>(
            ::mmap(nullptr, sizeof(TickRing), PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
        if (ring == MAP_FAILED) {
            std::cout << "  mmap(MAP_ANON) failed — using heap allocation\n";
            ring = new TickRing();
        }
#else
        // Windows: use VirtualAlloc for anonymous memory
        TickRing* ring = static_cast<TickRing*>(
            VirtualAlloc(nullptr, sizeof(TickRing),
                         MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
        if (!ring) ring = new TickRing();
        new(ring) TickRing();  // placement construct
#endif

        std::atomic<int> produced{0}, consumed{0};
        const int TOTAL = 1000;

        // Producer: feed thread pushing ticks to shared ring
        std::thread producer([ring, &produced, TOTAL]() {
            for (int i = 0; i < TOTAL; ++i) {
                Tick t{};
                t.seq = uint32_t(i);
                t.bid = int64_t(1825000 + i);
                while (!ring->push(t)) { std::this_thread::yield(); }
                produced.fetch_add(1, std::memory_order_relaxed);
            }
        });

        // Consumer: strategy thread reading from ring
        std::thread consumer([ring, &consumed, TOTAL]() {
            Tick t;
            while (consumed.load(std::memory_order_relaxed) < TOTAL) {
                if (ring->pop(t)) {
                    consumed.fetch_add(1, std::memory_order_relaxed);
                } else {
                    std::this_thread::yield();
                }
            }
        });

        producer.join();
        consumer.join();

        std::cout << "  Produced: " << produced.load()
                  << " Consumed: " << consumed.load() << "\n";

#ifdef PLATFORM_POSIX
        ::munmap(ring, sizeof(TickRing));
#else
        ring->~TickRing();
        VirtualFree(ring, 0, MEM_RELEASE);
#endif
    }

    // -------------------------------------------------------
    // SHARED MEMORY IPC ARCHITECTURE
    // -------------------------------------------------------

    std::cout << "\n=== Inter-process shared memory architecture ===\n";

    std::cout << "  Production pattern (Linux):\n"
              << "\n"
              << "  Feed Process:\n"
              << "    int fd = shm_open(\"/itch_feed\", O_CREAT|O_RDWR, 0600);\n"
              << "    ftruncate(fd, sizeof(TickRing));\n"
              << "    auto* ring = (TickRing*)mmap(NULL, sizeof(TickRing),\n"
              << "                  PROT_READ|PROT_WRITE, MAP_SHARED, fd, 0);\n"
              << "    new(ring) TickRing();  // construct atomics in shared mem\n"
              << "    // Push ticks as they arrive from the network\n"
              << "\n"
              << "  Strategy Process:\n"
              << "    int fd = shm_open(\"/itch_feed\", O_RDWR, 0);\n"
              << "    auto* ring = (TickRing*)mmap(NULL, sizeof(TickRing),\n"
              << "                  PROT_READ|PROT_WRITE, MAP_SHARED, fd, 0);\n"
              << "    // Pop ticks and evaluate strategy\n"
              << "\n"
              << "  Latency: ~50-100ns (vs ~1-5µs for pipe, ~5-20µs for socket IPC)\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Complete backtester using mmap:

        void Backtester::run(const std::string& tick_file, BaseStrategy& strategy) {
            // Map entire tick file at startup
            MappedFile file = MappedFile::open_read(tick_file);
            const Tick* ticks = file.as<Tick>();
            size_t      n     = file.count<Tick>();

            // Pre-touch all pages to eliminate page faults during replay
            volatile uint64_t sum = 0;
            for (size_t i = 0; i < n; i += 64) {  // one touch per 4KB page (64 * 64 bytes)
                sum += ticks[i].timestamp_ns;
            }
            // Pages are now in RAM — replay is just memory reads

            // Replay
            int fills = 0;
            for (size_t i = 0; i < n; ++i) {
                auto signal = strategy.on_tick(ticks[i]);
                if (signal) {
                    fills += simulate_fill(ticks[i], *signal);
                }
            }

            // Print results
            std::cout << "Replayed " << n << " ticks\n"
                      << "Fills: " << fills << "\n"
                      << "Final PnL: $" << strategy.pnl() << "\n";

            // file goes out of scope → MappedFile destructor calls munmap()
        }
    */
}
