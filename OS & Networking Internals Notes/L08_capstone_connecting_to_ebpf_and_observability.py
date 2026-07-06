# ============================================================
# L08: Capstone — How OS Internals Connect to eBPF and Observability
# ============================================================
# WHAT: A capstone lesson tracing a single network request through
#       EVERY layer covered in L01-L07 — scheduling, virtual memory,
#       the filesystem, TCP/IP, DNS, syscalls, and interrupts — then
#       showing exactly how this repo's eBPF Notes and Observability
#       Notes build their capabilities directly on top of these mechanisms.
# WHY: L01-L07 each covered ONE OS/networking mechanism in isolation.
#      This capstone shows how they combine for a single real operation,
#      and connects this foundational domain to the rest of this
#      repo's infrastructure-observability content.
# LEVEL: Capstone
# ============================================================

"""
CONCEPT OVERVIEW:
Tracing ONE HTTP request from a client application to a server and
back, through every layer this domain covered:

  1. DNS RESOLUTION (L05): the client's OS resolves the server's
     domain name to an IP address, walking the root->TLD->authoritative
     chain (or hitting a cache), before any connection attempt begins.

  2. TCP HANDSHAKE (L04): the client's TCP stack performs the
     three-way handshake with the server, establishing a reliable
     connection over the network's fundamentally unreliable IP layer.

  3. SYSTEM CALLS (L06): the client application's `connect()` and
     `send()` calls are SYSCALLS — crossing from user space into the
     kernel, which has the actual privileged access to the network
     hardware needed to transmit data.

  4. INTERRUPTS AND DMA (L07): the network card signals data arrival
     via a hardware interrupt; DMA transfers the incoming data into
     kernel memory without requiring the CPU's active involvement
     throughout the transfer.

  5. PROCESS SCHEDULING (L01): while waiting for the network response,
     the requesting process is marked "blocked," freeing the CPU to run
     OTHER processes — and once the response interrupt arrives, the
     scheduler eventually resumes the waiting process.

  6. VIRTUAL MEMORY (L02): the response data, once available, is
     accessed by the application through its own virtual address space
     — the OS's page tables transparently map this to wherever the
     data actually landed in physical RAM.

  7. FILESYSTEM (L03): if the server needs to read a file to fulfill
     the request (e.g. serving a static asset), inode lookups and
     potentially disk I/O (again via interrupts/DMA) occur before the response is sent back.

HOW THIS CONNECTS TO EBPF (this repo's eBPF Notes) AND OBSERVABILITY
(this repo's Observability Notes): eBPF programs attach to SPECIFIC
KERNEL HOOK POINTS that exist PRECISELY because of this domain's
mechanisms — a network-monitoring eBPF program hooks into the kernel's
packet-handling code (running WITHIN the kernel, avoiding the
user-space/kernel-space transition cost L06 covered); a
syscall-tracing eBPF program hooks the syscall entry/exit points L06
described directly; a scheduler-monitoring tool observes the process
state transitions L01 covered — understanding THIS domain (L01-L07) is
what makes eBPF's various hook points and Observability Notes' metrics
(context switch rates, page fault rates, syscall latency) genuinely
MEANINGFUL rather than abstract numbers on a dashboard.

PRODUCTION USE CASE:
A performance engineer investigating an application's unexplained
latency uses this domain's full mental model to systematically rule
out causes: checking DNS resolution time (L05) to rule out slow
lookups; checking TCP connection setup/reuse patterns (L04) to rule out
excessive handshake overhead; checking syscall latency and frequency
(L06) via eBPF-based tracing tools to rule out excessive/slow syscalls;
checking for memory pressure and page fault rates (L02) to rule out
thrashing; and checking context switch rates (L01) to rule out
scheduler contention — a genuinely systematic diagnostic process only
possible with this domain's full mental model of what's actually
happening beneath the application layer.

COMMON MISTAKES:
- Treating "the network" or "the OS" as an opaque black box when
  diagnosing performance issues, rather than having a mental model of
  the SPECIFIC layers (DNS, TCP handshake, syscalls, scheduling, memory,
  disk) where a real bottleneck could actually be occurring — this
  domain's value is specifically in replacing that black box with
  concrete, individually-diagnosable mechanisms.
- Using eBPF-based observability tools (this repo's eBPF Notes) without
  understanding WHAT kernel mechanism each hook point is actually
  observing — a tool tracing syscalls is fundamentally different from
  one tracing scheduler events or network packet processing, and
  choosing the RIGHT tool for a specific investigation requires
  knowing which OS-level mechanism is actually suspected as the bottleneck.
- Assuming application-level code changes are always the right place to
  look for a performance problem, when the root cause may genuinely lie
  in this domain's territory (DNS TTL misconfiguration, excessive
  syscalls from unbuffered I/O, memory pressure causing thrashing) —
  this domain equips you to recognize and investigate these
  OS/networking-level root causes directly, rather than only ever looking at application code.
"""

import textwrap


FULL_REQUEST_TRACE = textwrap.dedent("""\
    Tracing ONE HTTP request through every OS/networking layer:

    Client application
      |
      v
    [DNS resolution, L05] -> IP address obtained (cached or full chain)
      |
      v
    [TCP three-way handshake, L04] -> reliable connection established
      |
      v
    [connect()/send() syscalls, L06] -> user space -> kernel space transition
      |
      v
    [Process scheduling, L01] -> requesting process marked BLOCKED,
      |                          CPU freed for other work while waiting
      v
    [Network interrupt + DMA, L07] -> response data arrives, CPU notified
      |                               only upon actual completion
      v
    [Process scheduling, L01] -> waiting process marked READY, eventually
      |                          resumed by the scheduler
      v
    [Virtual memory, L02] -> application accesses response data through
      |                      its own virtual address space
      v
    [Filesystem + inodes, L03] -> (if server needed to read a file to
                                    fulfill the request)
      |
      v
    Response delivered to the application
""")

EBPF_CONNECTION_MAP = {
    "Syscall tracing (L06)": "eBPF programs attach directly to syscall entry/exit points",
    "Network monitoring (L04, L07)": "eBPF hooks into kernel packet-processing code paths (XDP, TC hooks)",
    "Scheduler observability (L01)": "eBPF/kernel tracepoints observe process state transitions and context switches",
    "Memory pressure monitoring (L02)": "eBPF/kernel tracepoints observe page fault rates and memory reclaim events",
}


if __name__ == "__main__":
    print(FULL_REQUEST_TRACE)
    print("How this domain's mechanisms connect to eBPF's hook points:\n")
    for mechanism, connection in EBPF_CONNECTION_MAP.items():
        print(f"  {mechanism}: {connection}")

"""
FINAL CONTEXT (capstone of this domain):
The measure of having internalized this domain isn't memorizing the
steps of a TCP handshake or the definition of an inode in isolation —
it's being able to trace a real request end to end through EVERY layer
covered here, recognize WHICH layer a given performance symptom most
likely originates from, and know precisely which observability tool
(this repo's eBPF Notes, Observability Notes, DevOps & SRE Practices
Notes) to reach for to confirm or rule out each hypothesis — this
foundational, mechanism-level understanding is what separates debugging
by trial-and-error guesswork from a systematic, informed investigation
grounded in how the underlying system actually works.
"""
