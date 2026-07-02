# ============================================================
# L07: Modern eBPF Development — libbpf + Go (CO-RE)
# ============================================================
# WHAT: Writing production eBPF tooling using CO-RE (Compile Once, Run
#       Everywhere) and Go, instead of BCC's compile-on-target-host model.
# WHY (PRODUCTION): BCC compiles your BPF C program on EVERY target host at
#       load time (needs kernel headers installed everywhere, slow startup).
#       CO-RE compiles ONCE into a portable object file that runs across
#       different kernel versions unmodified, using BTF (BPF Type Format)
#       to resolve kernel struct layout differences at load time.
# LEVEL: Senior / Staff platform engineer
# ============================================================

"""
CONCEPT OVERVIEW:
CO-RE solves BCC's biggest operational problem: BCC needs a full LLVM/Clang
toolchain and kernel headers on every machine running the tool, and compiles
from scratch on every single load — noticeably slow and a real production
deployment burden (you're shipping a compiler to every node). CO-RE instead
compiles your BPF C once into an ELF object with special "relocation"
metadata; at load time, libbpf reads the target kernel's own BTF (embedded
in modern kernels at /sys/kernel/btf/vmlinux) and patches struct field
offsets to match — no compiler needed on the target host at all.

cilium/ebpf is the dominant Go library for loading and interacting with
these CO-RE objects, wrapping libbpf's C API in idiomatic Go without a CGo
dependency on libbpf itself (it reimplements the loader in pure Go).

PRODUCTION USE CASE:
A platform team ships a single static Go binary (containing an embedded,
pre-compiled BPF object file) as a DaemonSet across a heterogeneous
Kubernetes fleet spanning three different kernel versions. The binary loads
correctly on all of them without any host needing a compiler or kernel
headers installed — a meaningful deployment simplification over the BCC
model.

COMMON MISTAKES:
- Not regenerating the Go bindings (`bpf2go`) after changing the BPF C
  source — silent mismatch between the Go struct definitions and the
  actual compiled BPF object's map/program layout.
- Forgetting to pin BPF maps/programs when persistence across the loading
  process's lifetime is needed — an unpinned map is destroyed when the
  loading process exits, even if the attached program should keep running.
- Treating verifier rejections as opaque failures instead of reading the
  verifier log (`ebpf.LoadCollection` returns detailed rejection reasons)
  — the log almost always identifies the exact offending instruction.
"""

import textwrap

# ------------------------------------------------------------------
# 1. libbpf-bootstrap project structure
# ------------------------------------------------------------------
PROJECT_STRUCTURE = textwrap.dedent("""\
    myebpftool/
    ├── bpf/
    │   ├── vmlinux.h        # auto-generated kernel type definitions (via bpftool)
    │   └── program.bpf.c    # the actual BPF C source, CO-RE style
    ├── main.go               # Go userspace loader/consumer
    ├── gen.go                # //go:generate directive for bpf2go
    └── go.mod
""")

# ------------------------------------------------------------------
# 2. Generating vmlinux.h — the CO-RE type source
# ------------------------------------------------------------------
VMLINUX_GENERATION = (
    "bpftool btf dump file /sys/kernel/btf/vmlinux format c > vmlinux.h\n"
    "# This single header contains struct definitions for EVERY kernel "
    "type, extracted from the running kernel's own embedded BTF. Your BPF "
    "C includes this instead of the traditional <linux/sched.h> etc, and "
    "libbpf's CO-RE relocation logic handles differences between the "
    "kernel version you compiled against and the kernel version you "
    "actually load on."
)

# ------------------------------------------------------------------
# 3. CO-RE BPF C — using BPF_CORE_READ for portable field access
# ------------------------------------------------------------------
CORE_BPF_PROGRAM = textwrap.dedent("""\
    // program.bpf.c
    #include "vmlinux.h"
    #include <bpf/bpf_helpers.h>
    #include <bpf/bpf_core_read.h>

    struct {
        __uint(type, BPF_MAP_TYPE_RINGBUF);
        __uint(max_entries, 256 * 1024);
    } events SEC(".maps");

    SEC("tp/sched/sched_process_exec")
    int handle_exec(struct trace_event_raw_sched_process_exec *ctx) {
        struct task_struct *task = (struct task_struct *)bpf_get_current_task();

        // BPF_CORE_READ handles struct layout differences across kernel
        // versions automatically — if `task->real_parent->pid` is at a
        // different byte offset on the TARGET kernel than the kernel this
        // was COMPILED against, libbpf patches the offset at load time.
        pid_t ppid = BPF_CORE_READ(task, real_parent, pid);

        void *event = bpf_ringbuf_reserve(&events, sizeof(pid_t), 0);
        if (!event) return 0;
        *(pid_t *)event = ppid;
        bpf_ringbuf_submit(event, 0);
        return 0;
    }
    char _license[] SEC("license") = "GPL";
""")

# ------------------------------------------------------------------
# 4. bpf2go — generating Go bindings from the compiled object
# ------------------------------------------------------------------
BPF2GO_USAGE = textwrap.dedent("""\
    // gen.go
    package main

    //go:generate go run github.com/cilium/ebpf/cmd/bpf2go -cc clang \\
    //   -cflags "-O2 -g -Wall" execTracer bpf/program.bpf.c -- -I./bpf

    // `go generate` compiles program.bpf.c AND generates Go structs/loader
    // functions (execTracerObjects, execTracerPrograms, execTracerMaps)
    // that give type-safe Go access to the maps/programs defined in C —
    // no manual byte-offset fiddling required from application code.
""")

# ------------------------------------------------------------------
# 5. cilium/ebpf — loading, attaching, reading maps in Go
# ------------------------------------------------------------------
CILIUM_EBPF_GO_USAGE = textwrap.dedent("""\
    package main

    import (
        "log"
        "github.com/cilium/ebpf/link"
        "github.com/cilium/ebpf/ringbuf"
    )

    func main() {
        var objs execTracerObjects
        // LoadExecTracerObjects loads the CO-RE object, using the TARGET
        // kernel's own BTF for relocation — this call is where the "no
        // compiler needed on this host" property actually happens.
        if err := loadExecTracerObjects(&objs, nil); err != nil {
            log.Fatalf("loading objects: %v", err)
        }
        defer objs.Close()

        // Attach the loaded program to its tracepoint
        tp, err := link.Tracepoint("sched", "sched_process_exec", objs.HandleExec, nil)
        if err != nil {
            log.Fatalf("attaching tracepoint: %v", err)
        }
        defer tp.Close()

        // Read events from the ring buffer — much lower overhead than the
        // older perf buffer, since ringbuf avoids per-CPU buffer copies
        // and supports variable-length records naturally.
        rd, err := ringbuf.NewReader(objs.Events)
        if err != nil {
            log.Fatalf("opening ringbuf reader: %v", err)
        }
        defer rd.Close()

        for {
            record, err := rd.Read()
            if err != nil {
                log.Printf("reading ringbuf: %v", err)
                continue
            }
            log.Printf("parent pid: %d", record.RawSample)
        }
    }
""")

# ------------------------------------------------------------------
# 6. BPF object pinning — persistence beyond the loading process
# ------------------------------------------------------------------
PINNING_NOTE = (
    "By default, a BPF program/map is destroyed when the process that "
    "loaded it exits (unless something else is still attached/referencing "
    "it, e.g. an XDP attachment). Pinning to the BPF filesystem "
    "(/sys/fs/bpf/) keeps it alive independent of the loading process's "
    "lifetime — useful for a short-lived 'setup' CLI tool that configures "
    "a long-running datapath program managed separately.\n\n"
    "  objs.HandleExec.Pin(\"/sys/fs/bpf/exec_tracer_prog\")\n"
    "  # A later process can reattach to the SAME loaded program:\n"
    "  prog, _ := ebpf.LoadPinnedProgram(\"/sys/fs/bpf/exec_tracer_prog\", nil)"
)

# ------------------------------------------------------------------
# 7. Perf buffer vs ring buffer
# ------------------------------------------------------------------
RINGBUF_VS_PERFBUF = {
    "perf buffer (BPF_MAP_TYPE_PERF_EVENT_ARRAY)": "One buffer PER CPU — "
        "userspace must poll/merge across all of them, and events aren't "
        "globally ordered. Older API, still widely used but largely "
        "superseded for new code.",
    "ring buffer (BPF_MAP_TYPE_RINGBUF)": "A SINGLE shared buffer across "
        "all CPUs (using a lock-free MPSC design internally) — simpler "
        "consumer code, globally ordered events, generally lower memory "
        "overhead for the same effective buffering. The modern default "
        "choice for new eBPF tooling.",
}

# ------------------------------------------------------------------
# 8. Testing eBPF programs
# ------------------------------------------------------------------
TESTING_NOTE = (
    "bpf_prog_test_run (exposed via cilium/ebpf's ProgramOptions.Run) lets "
    "you invoke a loaded BPF program directly with synthetic input data "
    "and inspect its return value/output buffer — enabling real unit tests "
    "for XDP/TC programs without needing actual network traffic or a live "
    "kernel event to trigger them. This is the difference between "
    "'I manually curl'd it and it seemed to work' and an actual CI-gated "
    "test suite for kernel-level code."
)

if __name__ == "__main__":
    print(RINGBUF_VS_PERFBUF["ring buffer (BPF_MAP_TYPE_RINGBUF)"])

"""
TRADING/PRODUCTION CONTEXT EXAMPLE:
A platform team ships a single Go binary (using cilium/ebpf + CO-RE) as a
privileged DaemonSet that traces process execution across a fleet spanning
kernel 5.10 through 6.1 — the exact same compiled BPF object loads
correctly on every node via BTF-based relocation, eliminating what used to
be a per-kernel-version BCC compilation matrix the platform team had to
maintain and test separately for each node image.
"""
