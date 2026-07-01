# ============================================================
# L02: BCC and bpftrace — Practical Kernel Tracing
# ============================================================
# WHAT: BCC (BPF Compiler Collection) is a Python + C framework for writing
#       eBPF programs. bpftrace is a high-level scripting language for
#       one-liner kernel tracing. Together they cover 90% of ad-hoc tracing.
# WHY:  They abstract the low-level BPF syscall API. BCC compiles eBPF C
#       inline, manages maps, and exposes them as Python objects. bpftrace
#       lets you answer "what is happening right now" in a single terminal line.
# LEVEL: Foundation
# ============================================================
"""
CONCEPT OVERVIEW:
    BCC workflow: embed C eBPF code as a Python string, instantiate BPF(),
    attach to kernel events, then poll maps or perf buffers from Python.
    The C code runs in the kernel; the Python code controls and reads it.
    bpftrace is for even faster exploration: its interpreter handles
    compilation and attachment automatically. Think of bpftrace as the
    'awk' for kernel events — powerful one-liners with minimal boilerplate.

PRODUCTION USE CASE:
    Site Reliability Engineers at large companies keep a library of BCC
    scripts for incident response: "which process is doing the most disk IO?",
    "what are the p99 read() latencies by process?", "which connections are
    being established right now?". These answer questions in seconds without
    application deploys or configuration changes.

COMMON MISTAKES:
    1. Running BCC tools without root (sudo required) or without CAP_BPF.
    2. BCC requires kernel headers: apt install linux-headers-$(uname -r).
       Without headers, BCC fails to compile the embedded C at runtime.
    3. Using b.trace_print() in production — it uses trace_pipe which has
       limited buffer; use perf buffers or ring buffers for real tools.
    4. Not cleaning up perf buffers — they consume locked kernel memory.
    5. bpftrace one-liners that aggregate too much data: @[kstack] with
       high-frequency events floods memory — always filter first.
"""

# ============================================================
# SECTION 1: BCC FRAMEWORK ARCHITECTURE
# ============================================================
# BCC flow:
#   [Python script]
#       |-- contains C string with eBPF program
#       |-- BPF(text=...) triggers: Clang compiles C → BPF bytecode
#       |                           Kernel verifier validates bytecode
#       |                           JIT compiles bytecode → native code
#       |-- attach_kprobe() / attach_tracepoint() loads program into kernel
#       |-- Access maps: b["map_name"] returns Python dict-like object
#       |-- Poll events: b.perf_buffer_poll() blocks waiting for kernel data
#
# Dependencies needed:
#   sudo apt install bpfcc-tools python3-bpfcc linux-headers-$(uname -r)
#   pip install bcc

# ============================================================
# SECTION 2: BCC HELLO WORLD — COUNT SYSCALLS PER PROCESS
# ============================================================

count_syscalls_bpf = """
#include <uapi/linux/ptrace.h>

// BPF_HASH creates a hash map: key=u32 (PID), value=u64 (count)
// Equivalent to: bpf_map_create(BPF_MAP_TYPE_HASH, sizeof(u32), sizeof(u64), 10240)
BPF_HASH(counts, u32, u64);

// Attach point: any syscall entry — we use a raw tracepoint for all syscalls.
// Alternatively attach to a specific syscall: attach_kprobe(event="sys_read")
int count_syscall(struct pt_regs *ctx) {
    u32 pid = bpf_get_current_pid_tgid() >> 32;

    // lookup_or_try_init: find existing count or initialize to 0
    u64 *count = counts.lookup_or_try_init(&pid, &(u64){0});
    if (count) {
        (*count)++;   // atomic increment (BCC wraps this in __sync_fetch_and_add)
    }
    return 0;
}
"""

# Python control code:
# from bcc import BPF
# import time
#
# b = BPF(text=count_syscalls_bpf)
# b.attach_kprobe(event=b.get_syscall_fnname("read"), fn_name="count_syscall")
# b.attach_kprobe(event=b.get_syscall_fnname("write"), fn_name="count_syscall")
# b.attach_kprobe(event=b.get_syscall_fnname("open"), fn_name="count_syscall")
#
# time.sleep(5)
#
# print(f"{'PID':<8} {'COUNT':<10}")
# for k, v in sorted(b["counts"].items(), key=lambda x: x[1].value, reverse=True)[:20]:
#     print(f"{k.value:<8} {v.value:<10}")

# ============================================================
# SECTION 3: MEASURING SYSCALL LATENCY WITH KPROBE + KRETPROBE
# ============================================================
# Classic pattern: record timestamp on entry, compute delta on return.
# The "start" hash map temporarily holds entry timestamps keyed by PID/TID.

latency_bpf = """
#include <uapi/linux/ptrace.h>

// start map: key = tid (thread ID), value = timestamp in nanoseconds
BPF_HASH(start, u32, u64);

// BPF_HISTOGRAM for latency distribution (log2 buckets)
BPF_HISTOGRAM(dist, u64);

// Called when read() syscall ENTERS the kernel
int trace_read_entry(struct pt_regs *ctx) {
    // Use TID (thread ID) not PID — one process can have many threads
    // all calling read() concurrently, each needs its own timestamp slot.
    u32 tid = bpf_get_current_pid_tgid() & 0xFFFFFFFF;
    u64 ts = bpf_ktime_get_ns();   // nanoseconds since boot (monotonic)
    start.update(&tid, &ts);
    return 0;
}

// Called when read() syscall RETURNS to userspace
int trace_read_return(struct pt_regs *ctx) {
    u32 tid = bpf_get_current_pid_tgid() & 0xFFFFFFFF;
    u64 *tsp = start.lookup(&tid);
    if (tsp == NULL) {
        // Entry was missed (program loaded after entry, or on different CPU)
        return 0;
    }

    u64 delta_ns = bpf_ktime_get_ns() - *tsp;
    u64 delta_us = delta_ns / 1000;

    // bpf_log2l() buckets: 0us, 1us, 2-3us, 4-7us, ... (powers of 2)
    dist.increment(bpf_log2l(delta_us));

    // Clean up start map — avoids memory leak for short-lived threads
    start.delete(&tid);
    return 0;
}
"""

# Python to attach and print histogram:
# from bcc import BPF
# import time
#
# b = BPF(text=latency_bpf)
# b.attach_kprobe(event=b.get_syscall_fnname("read"), fn_name="trace_read_entry")
# b.attach_kretprobe(event=b.get_syscall_fnname("read"), fn_name="trace_read_return")
#
# print("Tracing read() latency for 10 seconds...")
# time.sleep(10)
#
# print("Latency distribution (microseconds):")
# b["dist"].print_log2_hist("usecs")
# # Output looks like:
# #      usecs : count     distribution
# #        0 -> 1   : 12345    |********************|
# #        2 -> 3   : 4567     |*******             |
# #        4 -> 7   : 890      |*                   |
# #        8 -> 15  : 123      |                    |
# #       16 -> 31  : 45       |                    |

# ============================================================
# SECTION 4: TRACKING NETWORK CONNECTIONS
# ============================================================
# Trace connect() syscall to build a table of outbound connections.
# Captures source PID, destination IP and port without any packet capture.

tcp_connect_bpf = """
#include <uapi/linux/ptrace.h>
#include <net/sock.h>
#include <net/inet_sock.h>
#include <bcc/proto.h>

struct event_t {
    u32  pid;
    u32  saddr;    // source IP (network byte order)
    u32  daddr;    // destination IP
    u16  dport;    // destination port
    char comm[TASK_COMM_LEN];
};

BPF_PERF_OUTPUT(tcp_events);

// Attach to tcp_v4_connect — called when userspace calls connect() on TCP socket
int trace_connect(struct pt_regs *ctx, struct sock *sk) {
    struct event_t evt = {};
    evt.pid = bpf_get_current_pid_tgid() >> 32;
    bpf_get_current_comm(&evt.comm, sizeof(evt.comm));

    // Read from kernel struct using bpf_probe_read_kernel — safe pointer read
    struct inet_sock *inet = (struct inet_sock *)sk;
    bpf_probe_read_kernel(&evt.saddr, sizeof(evt.saddr), &inet->inet_saddr);
    bpf_probe_read_kernel(&evt.daddr, sizeof(evt.daddr), &inet->inet_daddr);
    bpf_probe_read_kernel(&evt.dport, sizeof(evt.dport), &inet->inet_dport);

    tcp_events.perf_submit(ctx, &evt, sizeof(evt));
    return 0;
}
"""

# ============================================================
# SECTION 5: BCC MAP ACCESS FROM PYTHON
# ============================================================
# BCC exposes all BPF maps as Python objects with dict-like behavior.

bcc_map_api_examples = {
    "Hash map access": """
        # b["counts"] returns a BPF table object
        counts = b["counts"]

        # Read single value
        pid_key = counts.Key(1234)
        value = counts[pid_key]
        print(value.value)   # ctypes integer

        # Iterate all entries
        for k, v in counts.items():
            print(f"PID {k.value}: {v.value} events")

        # Clear all entries
        counts.clear()
    """,

    "Histogram print": """
        # print_log2_hist: human-readable power-of-2 histogram
        b["dist"].print_log2_hist("usecs")

        # print_linear_hist: linear buckets
        b["dist"].print_linear_hist("bytes")
    """,

    "Perf buffer": """
        import ctypes

        class Event(ctypes.Structure):
            _fields_ = [
                ("pid",  ctypes.c_uint32),
                ("comm", ctypes.c_char * 16),
                ("data", ctypes.c_char * 256),
            ]

        def handle_event(cpu, data, size):
            event = ctypes.cast(data, ctypes.POINTER(Event)).contents
            print(f"CPU={cpu} PID={event.pid} COMM={event.comm.decode()}")

        # open_perf_buffer registers Python callback for kernel events
        b["events"].open_perf_buffer(handle_event, page_cnt=64)

        # Poll blocks until events arrive, calls handle_event for each
        while True:
            try:
                b.perf_buffer_poll(timeout=100)  # 100ms timeout
            except KeyboardInterrupt:
                break
    """,

    "Ring buffer (preferred, kernel 5.8+)": """
        def handle_event(ctx, data, size):
            event = b["events"].event(data)
            print(f"PID={event.pid}")

        b["events"].open_ring_buffer(handle_event)
        while True:
            b.ring_buffer_poll(timeout=100)
    """,
}

# ============================================================
# SECTION 6: bpftrace ONE-LINERS
# ============================================================
# bpftrace syntax:
#   probe_type:target:function /filter/ { action }
# Probes: kprobe, kretprobe, tracepoint, uprobe, software, hardware, profile
# Actions: printf(), @map = count/sum/hist/avg, @map[key] = ..., exit()

bpftrace_one_liners = [
    # Process tracing
    'bpftrace -e \'tracepoint:syscalls:sys_enter_execve { printf("%s exec %s\\n", comm, str(args->filename)); }\'',
    '# Trace new process executions with filename',

    'bpftrace -e \'tracepoint:sched:sched_process_exit { printf("exit: %s PID=%d\\n", comm, pid); }\'',
    '# Trace process exits',

    # File access
    'bpftrace -e \'tracepoint:syscalls:sys_enter_openat { printf("%s opened %s\\n", comm, str(args->filename)); }\'',
    '# Trace file opens with filename',

    'bpftrace -e \'tracepoint:syscalls:sys_enter_openat /comm == "nginx"/ { printf("%s\\n", str(args->filename)); }\'',
    '# Only trace nginx file opens (filter by process name)',

    # Syscall counting
    'bpftrace -e \'tracepoint:syscalls:sys_enter_read { @reads[comm] = count(); } interval:s:5 { print(@reads); clear(@reads); }\'',
    '# Count read() calls per process, print every 5 seconds',

    # Latency measurement
    'bpftrace -e \'kprobe:vfs_read { @start[tid] = nsecs; } kretprobe:vfs_read /@start[tid]/ { @us[comm] = hist((nsecs - @start[tid])/1000); delete(@start[tid]); }\'',
    '# Histogram of vfs_read latency in microseconds per process',

    # Network
    'bpftrace -e \'kprobe:tcp_connect { printf("%s connecting\\n", comm); }\'',
    '# Trace TCP connection attempts',

    'bpftrace -e \'tracepoint:net:net_dev_xmit { @bytes[args->dev_name] = sum(args->len); } interval:s:1 { print(@bytes); clear(@bytes); }\'',
    '# Bytes sent per network interface per second',

    # CPU profiling
    'bpftrace -e \'profile:hz:99 { @[comm, kstack] = count(); }\'',
    '# Sample kernel stack traces at 99Hz (prime avoids timer aliasing)',

    'bpftrace -e \'profile:hz:49 /pid == 1234/ { @[ustack] = count(); }\'',
    '# Profile userspace stack traces of specific PID at 49Hz',

    # Memory
    'bpftrace -e \'uprobe:/lib/x86_64-linux-gnu/libc.so.6:malloc { @allocs = hist(arg0); }\'',
    '# Histogram of malloc() allocation sizes',

    # Scheduler
    'bpftrace -e \'tracepoint:sched:sched_switch { @[prev_comm] = sum(nsecs - @start[prev_pid]); @start[next_pid] = nsecs; }\'',
    '# Measure off-CPU time per process (simplified)',
]

# ============================================================
# SECTION 7: bpftrace SCRIPT FILES (.bt)
# ============================================================
# For more complex logic, save to a .bt file and run with: sudo bpftrace script.bt

latency_bt_script = """
#!/usr/bin/env bpftrace
// File: read_latency.bt
// Usage: sudo bpftrace read_latency.bt
// Purpose: Histogram of read() syscall latency per process

BEGIN {
    printf("Tracing read() latency... Hit Ctrl-C to print histogram\\n");
}

tracepoint:syscalls:sys_enter_read
{
    // Store entry timestamp keyed by tid (thread ID)
    @start[tid] = nsecs;
}

tracepoint:syscalls:sys_exit_read
/@start[tid]/    // filter: only if we recorded entry
{
    $delta_us = (nsecs - @start[tid]) / 1000;

    // Store histogram per process name
    @latency_us[comm] = hist($delta_us);

    // Clean up — critical to avoid map memory leak
    delete(@start[tid]);
}

END {
    print("\\n=== Read() Latency Distribution (microseconds) ===");
    print(@latency_us);
    clear(@start);
}
"""

# ============================================================
# SECTION 8: UPROBE — TRACING USERSPACE FUNCTIONS
# ============================================================
# uprobes attach to symbols in shared libraries or executables.
# Useful for: tracing SSL/TLS before encryption, Go/Python/Java runtimes,
# database query tracing, language runtime internals.

uprobe_examples = {
    "SSL read/write (plaintext before encryption)": (
        "sudo bpftrace -e '"
        "uprobe:/usr/lib/x86_64-linux-gnu/libssl.so.3:SSL_write "
        "{ printf(\"%s wrote %d SSL bytes\\n\", comm, arg2); }'"
    ),
    "Python function calls": (
        "sudo bpftrace -e '"
        "uprobe:/usr/bin/python3:PyEval_EvalFrameEx "
        "{ @python_calls = count(); }'"
    ),
    "malloc size distribution": (
        "sudo bpftrace -e '"
        "uprobe:/lib/x86_64-linux-gnu/libc.so.6:malloc "
        "{ @size = hist(arg0); } "
        "interval:s:5 { print(@size); }'"
    ),
    "PostgreSQL query tracing": (
        "sudo bpftrace -e '"
        "uprobe:/usr/lib/postgresql/14/bin/postgres:exec_simple_query "
        "{ printf(\"query: %s\\n\", str(arg1)); }'"
    ),
}

# IMPORTANT: uprobe caveat with Go programs
# Go uses its own calling convention (not C ABI) for internal functions.
# Go 1.17+ uses register-based calling convention.
# Use uretprobe carefully — Go stack can move during GC.
# For Go, prefer userspace probing via USDT (User Statically Defined Tracepoints).

# ============================================================
# SECTION 9: PRACTICAL TOOL — READ LATENCY BY PROCESS
# ============================================================
# Complete BCC tool: measure read() latency, show histogram per process,
# refresh every interval, report top slow callers.

complete_latency_tool_bpf = """
#include <uapi/linux/ptrace.h>

struct key_t {
    u32  pid;
    char comm[TASK_COMM_LEN];
};

BPF_HASH(start, u32, u64);               // tid -> entry timestamp
BPF_HISTOGRAM(dist, u64, 64);            // global latency histogram
BPF_HASH(slow_procs, struct key_t, u64); // processes with >1ms reads

int entry(struct pt_regs *ctx) {
    u32 tid = bpf_get_current_pid_tgid();
    u64 ts  = bpf_ktime_get_ns();
    start.update(&tid, &ts);
    return 0;
}

int ret(struct pt_regs *ctx) {
    u32 tid = bpf_get_current_pid_tgid();
    u64 *tsp = start.lookup(&tid);
    if (!tsp) return 0;

    u64 delta_us = (bpf_ktime_get_ns() - *tsp) / 1000;
    dist.increment(bpf_log2l(delta_us));

    // Track processes with p99 slow reads (>1ms = 1000us)
    if (delta_us > 1000) {
        struct key_t key = {};
        key.pid = bpf_get_current_pid_tgid() >> 32;
        bpf_get_current_comm(&key.comm, sizeof(key.comm));
        u64 zero = 0;
        u64 *cnt = slow_procs.lookup_or_try_init(&key, &zero);
        if (cnt) (*cnt)++;
    }

    start.delete(&tid);
    return 0;
}
"""

# Usage pattern:
# b = BPF(text=complete_latency_tool_bpf)
# syscall = b.get_syscall_fnname("read")
# b.attach_kprobe(event=syscall, fn_name="entry")
# b.attach_kretprobe(event=syscall, fn_name="ret")
#
# while True:
#     time.sleep(args.interval)
#     print(f"\n--- Read() Latency @ {datetime.now()} ---")
#     b["dist"].print_log2_hist("usecs")
#     print("\nProcesses with >1ms reads:")
#     for k, v in sorted(b["slow_procs"].items(),
#                         key=lambda x: x[1].value, reverse=True)[:10]:
#         print(f"  PID={k.pid} COMM={k.comm.decode()}: {v.value} slow reads")
#     b["dist"].clear()
#     b["slow_procs"].clear()

print("eBPF L02: BCC and bpftrace tracing loaded.")
print("bpftrace one-liners documented:", len([x for x in bpftrace_one_liners if x.startswith('bpftrace')]))
