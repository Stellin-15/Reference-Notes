# ============================================================
# L07: Interrupts and I/O — How the CPU Handles Slow Devices Efficiently
# ============================================================
# WHAT: Why the CPU doesn't simply WAIT (busy-poll) for slow I/O
#       devices (disks, network cards) to finish — hardware interrupts,
#       interrupt handlers, and DMA (Direct Memory Access) as the
#       mechanisms that let the CPU do other useful work while I/O happens.
# WHY: L01 covered CPU scheduling assuming processes are "ready to run"
#      or "waiting" — this lesson covers exactly HOW a process
#      transitions from "waiting on I/O" back to "ready to run," and
#      why this matters enormously for overall system efficiency.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
BUSY-WAITING (POLLING) — repeatedly checking "is the disk/network
operation done yet?" in a tight loop — is a genuinely WASTEFUL approach
for slow I/O devices: disk and network operations can take MILLIONS of
CPU cycles to complete (relative to the CPU's own operation speed),
and a CPU stuck busy-polling during this entire time is 100% utilized
but doing ZERO useful work — this is directly why operating systems
use INTERRUPTS instead for most I/O, EXCEPT in specific latency-critical
scenarios (this repo's System Design Case Studies Notes' L03-adjacent,
and the C++ Notes HFT track's L41 busy-waiting lesson, cover the rare
cases where busy-waiting/spinning IS the right choice specifically
because even the interrupt mechanism's overhead is too slow).

A HARDWARE INTERRUPT is a SIGNAL sent DIRECTLY by a hardware device
(a disk controller, a network card) to the CPU, indicating "I've
finished the operation you asked me to do" — critically, this lets the
CPU be doing SOMETHING ELSE ENTIRELY (running other processes, per
L01's scheduling) WHILE the slow I/O operation is in progress, and only
needs to react WHEN the device signals actual completion — the CPU
temporarily SUSPENDS whatever it's currently running, executes a small,
fast INTERRUPT HANDLER (kernel code that processes the completion,
e.g. marking the waiting process as "ready to run" again so the
scheduler can resume it), then RESUMES whatever it was doing before the
interrupt occurred — this is dramatically more efficient than
busy-waiting for the vast majority of I/O scenarios.

DMA (DIRECT MEMORY ACCESS) further optimizes this: WITHOUT DMA, the CPU
itself would need to be involved in actually COPYING data between the
device and memory, byte by byte — WITH DMA, the CPU simply tells the
DMA CONTROLLER (a separate piece of hardware) "transfer this data from
the disk to this memory address," and the DMA controller performs the
ENTIRE transfer INDEPENDENTLY, WITHOUT further CPU involvement,
interrupting the CPU only ONCE the ENTIRE transfer is complete — this
frees the CPU to do useful work throughout the data transfer itself,
not just during the device's "thinking time" before the transfer even begins.

THE FULL I/O LIFECYCLE, tying L01, L02, and this lesson together: a
process requests a disk read (a syscall, L06) -> the OS initiates the
disk operation and marks the REQUESTING PROCESS as "blocked/waiting"
(removing it from the scheduler's ready queue, L01, so it consumes no
CPU time while waiting) -> the CPU is free to run OTHER ready processes
in the meantime -> the disk controller (using DMA) transfers the
requested data into memory -> once complete, the disk controller fires
a HARDWARE INTERRUPT -> the OS's interrupt handler marks the
ORIGINALLY-WAITING process as "ready" again -> the scheduler (L01)
eventually selects it to run again, now with its requested data available.

PRODUCTION USE CASE:
A database server handling thousands of concurrent connections
achieves high throughput specifically BECAUSE disk I/O operations don't
block the CPU while waiting — while ONE query's disk read is in
progress (potentially milliseconds, an ETERNITY in CPU-cycle terms),
the OS scheduler runs OTHER queries/connections' CPU-bound work
entirely concurrently, only returning to the original query once its
disk I/O interrupt signals completion — this interrupt-driven model is
foundational to how modern high-concurrency servers achieve efficient resource utilization at all.

COMMON MISTAKES:
- Assuming a "slow" I/O operation KEEPS THE CPU BUSY for its ENTIRE
  duration — modern OS I/O handling specifically AVOIDS this via
  interrupts; the CPU is genuinely free to do other useful work during
  the (often much longer) device operation time, not blocked waiting for it.
- Choosing busy-waiting/polling for a GENERAL, non-latency-critical I/O
  scenario "for simplicity" — this wastes CPU cycles that could
  otherwise serve other work, a real, measurable inefficiency at any
  meaningful concurrency level, appropriate only for the narrow,
  genuinely ultra-low-latency cases where even interrupt handling
  overhead is too slow (a rare, specialized scenario, not a general default).
- Underestimating DMA's role in I/O efficiency — assuming the CPU is
  necessarily involved in moving EVERY byte of a large data transfer,
  when DMA specifically offloads this bulk-transfer work to dedicated
  hardware, keeping the CPU free throughout the transfer itself, not just before it starts.
"""

import time


# ------------------------------------------------------------------
# 1. Busy-waiting vs interrupt-driven I/O, illustrated conceptually
# ------------------------------------------------------------------
def busy_wait_illustration():
    print("BUSY-WAITING (polling) for a slow disk operation:\n")
    print("  while (!disk_operation_complete()) {")
    print("      // CPU spins here, checking repeatedly, doing")
    print("      // ZERO useful work for potentially MILLIONS of cycles")
    print("  }")
    print("  -> CPU utilization: 100%, but USEFUL work done: essentially none\n")


def interrupt_driven_illustration():
    print("INTERRUPT-DRIVEN I/O:\n")
    print("  1. Process requests a disk read -> OS marks it as BLOCKED/WAITING")
    print("     (removed from the scheduler's ready queue, L01)")
    print("  2. CPU is now FREE -> scheduler runs OTHER ready processes")
    print("  3. Disk controller performs the read via DMA, INDEPENDENTLY,")
    print("     with NO further CPU involvement during the transfer itself")
    print("  4. Disk controller fires a HARDWARE INTERRUPT upon completion")
    print("  5. OS's interrupt handler marks the ORIGINAL process 'ready' again")
    print("  6. Scheduler (L01) eventually resumes it, now with data available")
    print("\n  -> CPU spent the ENTIRE waiting period doing OTHER useful work,")
    print("     only briefly interrupted to handle the completion signal.")


# ------------------------------------------------------------------
# 2. DMA's role — freeing the CPU during bulk data transfer
# ------------------------------------------------------------------
def dma_illustration():
    print("\nWithout DMA (CPU must copy every byte itself):")
    print("  CPU: read byte from device -> write to memory -> repeat,")
    print("       for EVERY byte of a potentially large transfer")
    print("  -> CPU is ACTIVELY BUSY (not free for other work) throughout")
    print("     the ENTIRE transfer duration, not just the setup\n")

    print("With DMA:")
    print("  CPU: 'DMA controller, transfer N bytes from device to address X'")
    print("  DMA controller: performs the ENTIRE transfer independently")
    print("  CPU: FREE to do other work throughout the transfer")
    print("  DMA controller: fires ONE interrupt when the FULL transfer is done")
    print("  -> CPU involvement: issuing the request + handling ONE completion")
    print("     interrupt, regardless of whether the transfer was 1KB or 1GB")


if __name__ == "__main__":
    busy_wait_illustration()
    interrupt_driven_illustration()
    dma_illustration()

"""
PRODUCTION CONTEXT EXAMPLE:
This repo's C++ Notes HFT track (L41, busy-waiting) covers a DELIBERATE
EXCEPTION to this lesson's general "avoid busy-waiting" guidance: in
ultra-low-latency trading systems, even the microseconds of overhead
from interrupt handling and the associated context switch (L01) back to
the waiting process can be UNACCEPTABLE — such systems DELIBERATELY
busy-wait (spin) on a tight loop checking a network receive buffer,
trading CPU efficiency (100% utilization, dedicating an entire core to
this one task) for the LOWEST POSSIBLE response latency — a genuine,
context-specific exception that only makes sense once you understand,
as this lesson covers, WHY interrupt-driven I/O is the general-purpose
default and specifically WHAT overhead busy-waiting is deliberately trading away in that narrow case.
"""
