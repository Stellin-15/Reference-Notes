# ============================================================
# L01: Process Scheduling and Context Switching
# ============================================================
# WHAT: How an operating system decides WHICH process/thread runs on a
#       CPU core at any given moment, when only a handful of cores exist
#       but potentially hundreds of processes want to run — scheduling
#       algorithms and the real cost of context switching between them.
# WHY: This repo's DevOps & SRE Practices Notes L04 (Linux systems
#      administration) and eBPF Notes cover OS-adjacent tooling but
#      assume kernel scheduling as a black box. This new domain opens
#      that box — the actual mechanism underneath process/thread execution.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
A CPU CORE CAN ONLY EXECUTE ONE INSTRUCTION STREAM AT A TIME — with
typically far more runnable processes/threads than available cores, the
OS SCHEDULER must decide, many times per second, WHICH one gets to run
next. The illusion of "many programs running simultaneously" on a
machine with, say, 8 cores and 200 running processes is created by the
scheduler rapidly SWITCHING which process each core executes, giving
each a small TIME SLICE (commonly a few milliseconds) before switching
to another — fast enough that, to a human observer, everything appears
to run concurrently.

CONTEXT SWITCHING is the mechanism enabling this: when the scheduler
decides to switch from process A to process B on a given core, it must
SAVE process A's complete CPU state (register values, program counter,
stack pointer) to memory, then LOAD process B's previously-saved state
— this is NOT free: it takes real, measurable time (commonly
microseconds), and CRITICALLY, it typically also invalidates the CPU's
CACHE (data process A had "warm" in the CPU cache gets evicted to make
room for process B's data) — this cache-invalidation cost, often larger
than the raw state-save/restore cost itself, is why EXCESSIVE context
switching (a system running far more active threads than it has cores,
each needing frequent switches) can measurably degrade overall
throughput even though the scheduler itself is working "correctly" — a
real, common performance problem called "thrashing" or excessive
context-switch overhead.

SCHEDULING ALGORITHMS make the actual "who runs next" decision under
different goals: ROUND ROBIN gives each runnable process a fixed
time slice in rotation — simple and fair, but doesn't account for
different processes' different priority/urgency; PRIORITY-BASED
scheduling lets more important processes preempt less important ones
— but risks STARVATION (a low-priority process never getting CPU time
if higher-priority processes are constantly available) without
additional safeguards like priority AGING (gradually increasing a
waiting process's priority the longer it waits, eventually guaranteeing
it runs); Linux's actual default scheduler (CFS — Completely Fair
Scheduler, in recent kernels) aims to give each runnable process a
FAIR SHARE of CPU time proportional to its weight/priority over time,
rather than using simple fixed time slices.

PROCESSES VS THREADS — a distinction with real scheduling implications:
a PROCESS has its own separate MEMORY SPACE (isolated from other
processes, requiring the OS to also switch memory-mapping/page-table
context on a process-level context switch — a MORE expensive
operation); a THREAD shares its PROCESS's memory space with other
threads of the SAME process (so switching between threads of the SAME
process, while still requiring CPU state save/restore, avoids the
memory-mapping switch cost) — this is WHY thread creation/switching is
generally CHEAPER than process creation/switching, a real, practical
consideration when choosing a concurrency model for a performance-sensitive application.

PRODUCTION USE CASE:
A web server handling many concurrent connections chooses a THREAD-based
(or even lighter-weight, user-space "green thread"/coroutine-based)
concurrency model specifically because thread/coroutine context
switches are cheaper than PROCESS-based concurrency (e.g. the older
"one process per connection" Apache model) — this choice, driven
directly by the scheduling/context-switching cost difference this
lesson covers, is exactly why event-loop and thread-pool-based server
architectures (this repo's FastAPI & Python Web Notes, Full-Stack &
Frontend Essentials Notes' Node.js coverage) generally outperform a
naive process-per-request model at high concurrency.

COMMON MISTAKES:
- Running dramatically more ACTIVE (CPU-bound, not I/O-waiting) threads
  than available CPU cores, assuming "more threads = more parallelism"
  — beyond the number of actual cores, additional CPU-bound threads
  primarily add CONTEXT-SWITCHING OVERHEAD rather than genuine
  additional throughput, since only as many threads as there are cores
  can ever truly execute simultaneously.
- Confusing "many threads exist" with "many threads are simultaneously
  RUNNING" — threads waiting on I/O (a network response, a disk read)
  are NOT consuming CPU scheduling time while waiting; a system can have
  thousands of "existing" threads with only a handful actually
  competing for CPU time at any given instant, which is precisely why
  I/O-bound applications can scale to far more concurrent connections than CPU-bound ones.
- Choosing a process-based (rather than thread-based) concurrency model
  for a workload with very frequent context switches between concurrent
  units of work, without accounting for the additional memory-mapping
  switch cost processes incur relative to threads — a real, measurable
  performance difference for switch-heavy workloads specifically.
"""

import time


# ------------------------------------------------------------------
# 1. Round robin scheduling, illustrated
# ------------------------------------------------------------------
def round_robin_schedule(processes: list[str], time_slice_ms: int, total_time_ms: int) -> list[str]:
    schedule = []
    elapsed = 0
    index = 0
    while elapsed < total_time_ms:
        schedule.append(processes[index % len(processes)])
        elapsed += time_slice_ms
        index += 1
    return schedule


def round_robin_demo():
    processes = ["process_A", "process_B", "process_C"]
    schedule = round_robin_schedule(processes, time_slice_ms=10, total_time_ms=90)
    print(f"Round robin schedule (10ms slices, 3 processes): {schedule}")
    print("  -> Each process gets an EQUAL share of CPU time in rotation,")
    print("     regardless of how urgent/important any specific one is.")


# ------------------------------------------------------------------
# 2. Priority scheduling with aging (avoiding starvation)
# ------------------------------------------------------------------
class SchedulableProcess:
    def __init__(self, name: str, priority: int):
        self.name = name
        self.priority = priority
        self.wait_time = 0

    def age(self):
        self.wait_time += 1
        # Priority AGING: the longer a process waits, the higher its
        # EFFECTIVE priority becomes — this is what prevents starvation
        self.effective_priority = self.priority + (self.wait_time // 5)


def priority_scheduling_with_aging_demo():
    print("\nPriority scheduling WITHOUT aging risks starvation:")
    high_priority = SchedulableProcess("critical_task", priority=10)
    low_priority = SchedulableProcess("background_task", priority=1)

    print(f"  Without aging: '{high_priority.name}' (priority 10) always runs")
    print(f"     before '{low_priority.name}' (priority 1) — potentially FOREVER")
    print(f"     if high-priority work keeps arriving.")

    print("\nWith priority aging, low_priority's EFFECTIVE priority rises over time:")
    for tick in range(25):
        low_priority.age()
    print(f"  After {low_priority.wait_time} time units waiting: "
          f"effective_priority = {low_priority.effective_priority} "
          f"(started at {low_priority.priority})")
    print("  -> Eventually, the aged low-priority process's effective")
    print("     priority EXCEEDS the high-priority process's, GUARANTEEING")
    print("     it eventually runs — this is the direct fix for starvation.")


# ------------------------------------------------------------------
# 3. Context switch overhead — thread vs process cost illustration
# ------------------------------------------------------------------
def context_switch_cost_illustration():
    print("\nRelative context switch cost (illustrative, not precise benchmarks):\n")
    costs = {
        "Thread switch (same process, shared memory space)": "~1-4 microseconds",
        "Process switch (separate memory space, page table reload)": "~5-20+ microseconds",
    }
    for switch_type, cost in costs.items():
        print(f"  {switch_type}: {cost}")
    print("\n  -> This difference is EXACTLY why thread-pool or event-loop-based")
    print("     server architectures generally outperform a process-per-")
    print("     connection model at high concurrency — fewer, cheaper switches.")


if __name__ == "__main__":
    round_robin_demo()
    priority_scheduling_with_aging_demo()
    context_switch_cost_illustration()

"""
PRODUCTION CONTEXT EXAMPLE:
A high-traffic web server observes that increasing its worker THREAD
count beyond roughly 2x its available CPU core count provides
DIMINISHING and eventually NEGATIVE returns on throughput for
CPU-bound request processing — profiling reveals a growing fraction of
total CPU time being spent on context switching (and its associated
cache invalidation) rather than actual request processing, directly
illustrating this lesson's core lesson: beyond the point of genuinely
utilizing available cores, additional concurrent CPU-bound work units
primarily add scheduling OVERHEAD, not additional throughput.
"""
