# ============================================================
# L06: System Calls and the Kernel/User-Space Boundary
# ============================================================
# WHAT: Why normal application code CANNOT directly access hardware
#       (disk, network, memory management) and must instead go through
#       the KERNEL via SYSTEM CALLS — the actual mechanism of this
#       boundary crossing, and why it has a real, measurable cost.
# WHY: This repo's eBPF Notes covers kernel-level programming
#      extensively but assumes familiarity with the kernel/user-space
#      distinction it's built on — this lesson provides that
#      foundational understanding directly.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
USER SPACE AND KERNEL SPACE are two DISTINCT PRIVILEGE LEVELS the CPU
itself enforces (via hardware-level protection rings, or their modern
equivalent) — regular APPLICATION CODE runs in USER SPACE, a
RESTRICTED environment where it CANNOT directly execute privileged
CPU instructions or directly access hardware devices; the OPERATING
SYSTEM KERNEL runs in KERNEL SPACE, with FULL, unrestricted hardware
access — this separation exists SPECIFICALLY for stability and
security: if application code could directly manipulate hardware or
arbitrary memory, ONE buggy or malicious program could crash the
entire system or access another program's private data with no protection whatsoever.

A SYSTEM CALL (syscall) is the CONTROLLED, EXPLICIT mechanism by which
user-space code REQUESTS the kernel perform a privileged operation on
its behalf — reading a file, sending network data, allocating memory,
creating a new process — ALL of these require a syscall, because they
all involve resources (disk, network hardware, physical memory) that
only the kernel has direct authority over. When a syscall is invoked, the
CPU performs a controlled TRANSITION from user mode to kernel mode
(historically via a software interrupt, more efficiently via dedicated
CPU instructions like `syscall`/`sysenter` on modern x86 processors),
the kernel executes the requested operation with its full privileges,
then transitions BACK to user mode to return control (and the result) to the calling application.

THIS TRANSITION HAS A REAL, MEASURABLE COST — meaningfully more
expensive than a normal function call WITHIN the same privilege level
(a typical syscall might cost on the order of 100-1000+ CPU cycles of
pure overhead, even before the requested operation itself executes) —
this is EXACTLY why performance-sensitive code minimizes the NUMBER of
syscalls it makes, favoring techniques like BUFFERING (accumulating
data in user-space memory and making ONE larger syscall to write it,
rather than many small syscalls for each individual piece of data) —
this directly explains why, e.g., writing to a file byte-by-byte in a
loop is dramatically slower than buffering the data and writing it in
one larger chunk, a genuinely common performance pitfall.

WHY THIS MATTERS FOR THIS REPO'S EBPF NOTES SPECIFICALLY: eBPF's entire
value proposition is letting SAFE, SANDBOXED CODE run WITHIN THE
KERNEL ITSELF (rather than in user space) for specific hooks/events —
this AVOIDS the user-space/kernel-space TRANSITION COST for
observability/networking/security logic that would otherwise need to
constantly cross this boundary (e.g. a traditional user-space network
monitoring tool receiving a COPY of every packet via a syscall,
vs. an eBPF program processing packets DIRECTLY within the kernel's own execution context, with zero transition cost per packet).

PRODUCTION USE CASE:
A high-throughput logging library BUFFERS log messages in an in-memory
queue and FLUSHES them to disk via a SINGLE `write()` syscall
periodically (e.g. every 100ms or when the buffer reaches a certain
size), rather than issuing a separate syscall for every individual log
line — this directly minimizes syscall overhead for a workload that
could otherwise generate thousands of syscalls per second, a
significant, measurable performance difference for high-volume logging specifically.

COMMON MISTAKES:
- Writing code that makes MANY small syscalls (e.g. reading a file one
  byte at a time, or making a separate network `send()` call for every
  tiny piece of data) rather than BUFFERING and batching into fewer,
  larger syscalls — the fixed per-syscall overhead dominates for many
  small operations, a real and often significant performance cost.
- Assuming ALL code runs with the SAME privilege level and access —
  understanding that regular application code is DELIBERATELY
  restricted from direct hardware access (and must go through the
  kernel via syscalls) is foundational to understanding why certain
  operations (creating raw network sockets, accessing specific hardware
  devices) require elevated privileges (root/administrator) in the first place.
- Treating eBPF (this repo's eBPF Notes) as "just another user-space
  monitoring tool" without appreciating that its core value comes
  SPECIFICALLY from running within the kernel, avoiding the exact
  transition overhead this lesson describes for every single monitored event.
"""

import time


# ------------------------------------------------------------------
# 1. User space vs kernel space, illustrated conceptually
# ------------------------------------------------------------------
def kernel_boundary_illustration():
    print("User space (restricted) vs Kernel space (privileged):\n")
    print("  USER SPACE (your application code):")
    print("    - CANNOT directly read/write disk hardware")
    print("    - CANNOT directly send/receive network packets")
    print("    - CANNOT directly access another process's memory")
    print("    - MUST request these operations via SYSTEM CALLS\n")
    print("  KERNEL SPACE (the OS kernel):")
    print("    - Full, unrestricted hardware access")
    print("    - Enforces isolation/protection BETWEEN user-space processes")
    print("    - Executes the ACTUAL privileged operation on a syscall's behalf")


# ------------------------------------------------------------------
# 2. Syscall overhead — why batching matters, measured directly
# ------------------------------------------------------------------
def unbuffered_write_simulation(data: str, filepath: str):
    # SIMULATING many small syscalls — writing one character at a time
    # (in a REAL OS, EACH write() call here would be a separate syscall
    # with real transition overhead)
    syscall_count = 0
    with open(filepath, "w") as f:
        for char in data:
            f.write(char)   # each call HERE is conceptually a separate write, though
                              # Python's own buffering may reduce actual syscalls in practice
            syscall_count += 1
    return syscall_count


def buffered_write_simulation(data: str, filepath: str):
    # ONE larger write — a SINGLE syscall for the entire buffer
    with open(filepath, "w") as f:
        f.write(data)
    return 1


def syscall_overhead_demo():
    import tempfile
    import os

    data = "x" * 10000
    with tempfile.TemporaryDirectory() as tmpdir:
        path1 = os.path.join(tmpdir, "unbuffered.txt")
        path2 = os.path.join(tmpdir, "buffered.txt")

        start = time.perf_counter()
        unbuffered_calls = unbuffered_write_simulation(data, path1)
        unbuffered_time = time.perf_counter() - start

        start = time.perf_counter()
        buffered_calls = buffered_write_simulation(data, path2)
        buffered_time = time.perf_counter() - start

    print(f"\nUnbuffered (many small write calls): "
          f"~{unbuffered_calls} operations, {unbuffered_time*1000:.2f}ms")
    print(f"Buffered (one large write call): "
          f"{buffered_calls} operation, {buffered_time*1000:.2f}ms")
    print(f"\n  -> Even accounting for Python/OS-level buffering already helping")
    print(f"     somewhat, the PRINCIPLE holds generally: minimizing the NUMBER")
    print(f"     of syscalls (by batching data) avoids real, cumulative")
    print(f"     per-syscall transition overhead — critical at high volume.")


if __name__ == "__main__":
    kernel_boundary_illustration()
    syscall_overhead_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
This repo's eBPF Notes covers how tools like Cilium (for networking) and
Falco (for security monitoring) achieve dramatically better performance
than equivalent user-space-only tools specifically because eBPF
programs execute WITHIN the kernel's own context for each relevant
event (a packet arriving, a syscall being made) — avoiding the
user-space/kernel-space transition this lesson describes for EVERY
SINGLE monitored event, which is exactly why eBPF-based observability
tools can operate at line-rate network speeds where a traditional
user-space packet-capture approach (requiring a syscall-mediated copy
of every packet into user space) would introduce a measurable, often prohibitive performance bottleneck.
"""
