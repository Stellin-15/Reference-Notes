# ============================================================
# L02: Virtual Memory and Paging
# ============================================================
# WHAT: How the OS gives every process the ILLUSION of its own private,
#       contiguous memory space (virtual memory), backed by physical
#       RAM organized into fixed-size PAGES — and what actually happens
#       during a "page fault" and when a system runs out of RAM.
# WHY: This repo's GPU Computing & Distributed Training Notes L01 and
#      C++ Notes L14 both reference "memory" as a resource without
#      covering how the OS actually virtualizes and manages it — this
#      lesson opens that abstraction.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
VIRTUAL MEMORY gives EVERY process the illusion that it has access to
its OWN large, contiguous, private address space (e.g. addresses 0 to
several terabytes on a 64-bit system) — starting at the SAME apparent
address range regardless of what other processes are running or how
much PHYSICAL RAM actually exists — this is a genuinely powerful
abstraction: application code never needs to know or care about actual
physical memory addresses, or coordinate with other processes about
which physical memory regions are "theirs."

PAGING is the mechanism making this illusion possible: both virtual and
physical memory are divided into fixed-size chunks called PAGES
(commonly 4KB) — a PAGE TABLE (maintained per-process by the OS, with
hardware acceleration via the CPU's Memory Management Unit, or MMU)
maps each VIRTUAL page a process references to wherever that data
ACTUALLY lives in PHYSICAL memory — critically, a process's virtual
pages do NOT need to be physically CONTIGUOUS in RAM at all (page 5 and
page 6 in the process's virtual address space might be scattered to
completely unrelated physical RAM locations) — the page table hides
this scattering entirely from the application.

A PAGE FAULT occurs when a process accesses a virtual memory address
whose PAGE TABLE ENTRY indicates the data is NOT currently in physical
RAM — this happens in TWO genuinely different scenarios: a MINOR
(soft) page fault, where the data is actually already somewhere in
memory (e.g. a shared library already loaded for another process) and
just needs its page table entry updated — relatively cheap; and a MAJOR
(hard) page fault, where the data must be read from DISK (either the
program's own executable file, or previously-SWAPPED-OUT memory) —
substantially more expensive, since disk I/O is orders of magnitude
slower than RAM access, even with modern SSDs.

SWAPPING (or "paging to disk") is what happens when the system runs low
on physical RAM: the OS moves LESS RECENTLY USED pages OUT of RAM onto
disk (the "swap space" or "page file"), freeing physical RAM for more
actively-used data — if a process later accesses a SWAPPED-OUT page,
this triggers exactly the expensive major page fault described above,
requiring the OS to read it back from disk before the process can
continue. "THRASHING" is the severe pathological case where a system is
so memory-constrained that it spends MORE time swapping pages in and
out than doing actual useful work — a system under active thrashing can
become nearly unresponsive despite the CPU technically being "busy" the
entire time, just busy handling page faults rather than genuine application work.

PRODUCTION USE CASE:
A server running multiple memory-intensive applications simultaneously
experiences a sudden, severe performance degradation — monitoring
reveals the system has exhausted available physical RAM and is actively
SWAPPING, with a large fraction of CPU time going toward major page
faults rather than actual application processing — the fix (adding
more RAM, or reducing memory usage/the number of co-located
applications) directly addresses the ROOT CAUSE (insufficient physical
memory for the actual working set) rather than a CPU or application-logic problem the symptoms might initially suggest.

COMMON MISTAKES:
- Diagnosing severe performance degradation as a CPU or application-code
  problem when the actual root cause is memory exhaustion causing
  thrashing — checking swap usage/page fault rates specifically is a
  standard, important diagnostic step this repo's Observability Notes
  and DevOps & SRE Practices Notes' incident-response coverage would
  reinforce, before assuming a purely CPU-bound explanation.
- Assuming virtual memory addresses correspond directly to physical
  memory locations — this is EXACTLY the abstraction paging exists to
  hide; two processes can reference the SAME virtual address (e.g. both
  believing their code starts at a similar address) while actually
  residing in completely different physical RAM locations.
- Provisioning a system with insufficient RAM for its actual working set
  while relying on swap space to "make up the difference" as a
  long-term strategy — swap is a genuine, valuable safety net for
  occasional memory pressure, but relying on it CONSTANTLY for a
  system's normal operating load produces the thrashing pathology this
  lesson describes, a fundamentally different situation than swap's occasional, brief use.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Virtual to physical address translation, illustrated
# ------------------------------------------------------------------
class SimplePageTable:
    def __init__(self):
        self.mappings: dict[int, int] = {}   # virtual_page -> physical_page
        self.next_physical_page = 0

    def translate(self, virtual_page: int) -> int:
        if virtual_page not in self.mappings:
            # A NEW mapping — allocate the next available physical page
            self.mappings[virtual_page] = self.next_physical_page
            self.next_physical_page += 1
        return self.mappings[virtual_page]


def page_table_demo():
    process_a_table = SimplePageTable()
    process_b_table = SimplePageTable()

    print("Two DIFFERENT processes, both referencing 'virtual page 5':\n")
    physical_for_a = process_a_table.translate(5)
    physical_for_b = process_b_table.translate(5)

    print(f"  Process A's virtual page 5 -> physical page {physical_for_a}")
    print(f"  Process B's virtual page 5 -> physical page {physical_for_b}")
    print("\n  -> BOTH processes reference 'virtual page 5', but each has")
    print("     its OWN, completely independent page table mapping it to")
    print("     a DIFFERENT physical location — this is the isolation")
    print("     virtual memory provides, transparently to each process.")


# ------------------------------------------------------------------
# 2. Minor vs major page faults
# ------------------------------------------------------------------
def page_fault_illustration():
    print("\nMinor (soft) vs major (hard) page faults:\n")
    print("  MINOR fault: data is somewhere in RAM already (e.g. a shared")
    print("    library loaded for another process) — just needs a page")
    print("    table entry update. Cost: microseconds.")
    print()
    print("  MAJOR fault: data must be read from DISK (originally on")
    print("    disk, or previously swapped out). Cost: potentially")
    print("    MILLISECONDS — orders of magnitude slower than a minor fault,")
    print("    even on fast SSDs, relative to RAM access speed.")


# ------------------------------------------------------------------
# 3. Thrashing simulation — memory pressure vs useful work ratio
# ------------------------------------------------------------------
def simulate_thrashing(available_ram_pages: int, working_set_pages: int) -> dict:
    if working_set_pages <= available_ram_pages:
        return {"status": "healthy", "page_fault_rate": "low", "useful_work_pct": 95}

    # As working set exceeds available RAM, an increasing fraction of
    # time goes to major page faults (swapping) rather than useful work
    overcommit_ratio = working_set_pages / available_ram_pages
    useful_work_pct = max(5, 95 - (overcommit_ratio - 1) * 60)
    return {"status": "THRASHING" if useful_work_pct < 30 else "degraded",
            "page_fault_rate": "high", "useful_work_pct": round(useful_work_pct, 1)}


def thrashing_demo():
    print("\nMemory pressure simulation:\n")
    scenarios = [
        {"available": 1000, "working_set": 800},
        {"available": 1000, "working_set": 1500},
        {"available": 1000, "working_set": 3000},
    ]
    for s in scenarios:
        result = simulate_thrashing(s["available"], s["working_set"])
        print(f"  Available RAM: {s['available']} pages, working set: {s['working_set']} pages")
        print(f"    -> status={result['status']}, useful work: {result['useful_work_pct']}%\n")
    print("  -> As the working set exceeds available RAM, useful work")
    print("     percentage COLLAPSES — the CPU is 'busy' but mostly")
    print("     handling page faults, not application logic.")


if __name__ == "__main__":
    page_table_demo()
    page_fault_illustration()
    thrashing_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A database server experiencing intermittent, severe query latency
spikes is diagnosed via `vmstat`/similar OS-level monitoring tools
(this repo's DevOps & SRE Practices Notes L04's systems administration
coverage) to be actively swapping during peak load — its physical RAM
had been sized for the database's index working set under NORMAL load,
but peak-hour query patterns push the actual working set beyond
available RAM, triggering major page faults precisely when the system
is least able to tolerate the additional latency — the fix (increasing
RAM to comfortably exceed the PEAK working set, not just the average)
directly addresses this virtual-memory-level root cause.
"""
