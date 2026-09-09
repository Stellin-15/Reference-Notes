# OS & Networking Internals — Principal Engineer Deep Dive

Companion to the existing lessons. Narrative depth, then a comprehensive
common-to-uncommon reference.


## Process Scheduling, Beyond Round-Robin

**Beyond the lesson**: Modern Linux uses CFS (Completely Fair Scheduler,
historically) or EEVDF (Earliest Eligible Virtual Deadline First, the
newer default in recent kernels) — the core idea both share: track each
process's "virtual runtime" (CPU time consumed, weighted by priority/nice
value) and always schedule whichever runnable process has accumulated the
LEAST virtual runtime relative to its fair share — this achieves
proportional fairness without needing fixed time-slice round-robin, and
naturally gives interactive/I/O-bound processes (which sleep often and
accumulate less runtime) responsive scheduling without special-casing them.

**Worked example**: `nice`/`renice` (see DevOps deep dive) work by
adjusting a process's WEIGHT in this virtual-runtime calculation — a
higher nice value (lower priority) makes virtual runtime accumulate
FASTER for the same real CPU time, causing the scheduler to deprioritize
it sooner relative to other processes — this is a real, tunable production
lever for isolating a batch job's CPU impact on latency-sensitive
processes sharing the same host.

**Interview Q&A**:
- *Q: A latency-sensitive process occasionally sees multi-millisecond scheduling delays even with plenty of idle CPU. What's a likely cause beyond simple contention?* A: CPU throttling from a cgroup CPU quota (see Docker Notes deep dive's cgroups section) — even with idle physical cores, a process confined to a cgroup that's exhausted its quota for the current period gets throttled until the next period, a real and common source of "mysterious" latency spikes in containerized environments that pure `top`/`htop` CPU% doesn't reveal without checking `cpu.stat`'s throttling counters directly.


## Virtual Memory & Page Faults, In Depth

**Beyond the lesson**: Every process sees a private VIRTUAL address
space, translated to physical memory via page tables — this indirection
is what makes memory isolation between processes possible, and it's also
where a huge class of performance characteristics comes from. A MINOR
page fault (the page is in memory but not yet mapped into this process's
page table — common right after `fork()` or `mmap()`) is cheap; a MAJOR
page fault (the page must be read from DISK — swap, or a memory-mapped
file not yet cached) is genuinely expensive, potentially milliseconds
versus nanoseconds — this exact distinction is why swapping under memory
pressure causes such dramatic, sudden latency cliffs compared to gradual degradation.

**Worked example**: Copy-on-Write (COW) after `fork()` — a child process
initially shares ALL of its parent's physical memory pages (marked
read-only in both page tables); only when either process WRITES to a
shared page does the kernel actually copy it, creating a private copy for
the writer — this is why `fork()` is cheap even for a process with a huge
memory footprint, and it's the exact mechanism Redis's `BGSAVE`
(background snapshot) and many database backup tools rely on to take a
consistent snapshot without blocking the main process.

**Interview Q&A**:
- *Q: A container's memory usage as reported by `docker stats` seems higher than the application should need. What's a common explanation unrelated to an actual leak?* A: Page cache — the kernel caches recently-read file data in memory (counted toward the cgroup's memory usage) because it's cheap to evict under pressure and speeds up repeated reads; this is RECLAIMABLE memory, not a leak, but naive memory monitoring that doesn't distinguish "used by the app" from "cached, reclaimable if needed" can alarm on a healthy system.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Kernel-level concepts worth knowing by name
- **System calls & the user/kernel boundary** — `strace` (see Ethical
  Hacking Notes) traces exactly these — every file open, network call,
  and memory allocation eventually crosses into kernel mode via a syscall,
  a real, inspectable boundary rather than an abstract concept.
- **Interrupts vs polling** — hardware interrupts let the CPU respond to
  I/O completion without constantly checking (polling) — the fundamental
  mechanism underneath async I/O's efficiency versus a naive busy-loop.
- **NUMA (Non-Uniform Memory Access)** — on multi-socket servers, memory
  attached to a DIFFERENT CPU socket than the one accessing it has
  materially higher latency — a real, production-relevant consideration
  for high-performance/HFT-style workloads (see C++ Notes' thread affinity
  lessons), largely invisible on typical cloud VM instance sizes but
  significant on large bare-metal/dedicated hardware.

### Networking internals beyond the basics
- **TCP congestion control algorithms** — Reno (classic, conservative),
  Cubic (Linux's long-standing default, more aggressive window growth),
  BBR (Google's model-based algorithm, estimates actual bandwidth/RTT
  rather than reacting purely to packet loss) — a genuinely active area
  with real throughput/latency implications, BBR increasingly the choice
  for high-bandwidth, lossy, or long-distance links where loss-based
  algorithms underperform.
- **The TCP three-way handshake and TIME_WAIT** — a socket that closes a
  connection enters TIME_WAIT for a period (historically 2×MSL) before
  fully releasing — a server handling very high connection churn can
  exhaust available ephemeral ports/socket resources from accumulated
  TIME_WAIT sockets, a real, named production scaling issue
  (`SO_REUSEADDR`/tuning `net.ipv4.tcp_tw_reuse` are the standard mitigations).
- **Socket buffer tuning** — `net.core.rmem_max`/`wmem_max` and TCP's own
  auto-tuning windows directly affect achievable throughput on
  high-bandwidth, high-latency links (the bandwidth-delay product) — a
  real kernel tuning lever for genuinely high-throughput network services.

### Filesystem internals
- **inodes, precisely** — a file's DATA and its NAME are separate; a
  directory entry just maps a name to an inode number — this is why
  multiple hard links to the same inode share the same data (deleting one
  name doesn't free the data until the inode's link count reaches zero),
  and why "disk full but `df` shows space" sometimes traces to inode
  exhaustion (a filesystem can run out of AVAILABLE INODES for new files
  even with free disk space, especially with millions of tiny files).
- **Filesystem journaling** — ext4/XFS journal metadata changes before
  committing them, so an unclean shutdown can REPLAY the journal to
  restore a consistent state quickly, rather than needing a full `fsck`
  scan of the entire filesystem — the mechanism underneath modern
  filesystems' fast, safe recovery after a crash.


## NICHE BUT REAL

- **io_uring** — a relatively recent (2019+) Linux async I/O interface
  that dramatically reduces syscall overhead for high-throughput I/O
  workloads by using shared ring buffers between userspace and the kernel
  instead of one syscall per I/O operation — a genuinely significant,
  actively-adopted performance advance (used by newer high-performance
  databases/proxies) worth knowing exists beyond the older epoll-based model.
- **eBPF for kernel observability** — see the dedicated eBPF Notes domain
  for the full treatment; worth cross-referencing here as the modern
  answer to "how do I actually see what the kernel is doing" beyond
  traditional strace/tcpdump overhead.
- **Huge pages** — using larger memory page sizes (2MB/1GB instead of the
  standard 4KB) reduces TLB (Translation Lookaside Buffer) misses for
  memory-intensive applications with large working sets — a real,
  measurable performance technique in database/JVM-heavy production tuning.
- **The C10K/C10M problem** — the historical challenge of handling 10,000
  (then 10 million) concurrent connections on one server — the actual
  motivating problem behind epoll/io_uring's existence and modern
  event-driven server architectures generally; worth knowing this specific
  named historical framing since it comes up in systems-design interviews
  discussing connection-handling architecture choices.
