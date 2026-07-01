# ============================================================
# L01: eBPF Fundamentals — What It Is and Why It Matters
# ============================================================
# WHAT: eBPF lets you run sandboxed programs inside the Linux kernel
#       without changing kernel source code or loading kernel modules.
# WHY:  Enables zero-overhead observability, security enforcement, and
#       networking at kernel speed — safely, without rebooting or risking
#       kernel panics from bad module code.
# LEVEL: Foundation
# ============================================================
"""
CONCEPT OVERVIEW:
    eBPF (extended Berkeley Packet Filter) is a virtual machine inside the
    Linux kernel. You write small programs in a C-like language, compile them
    to eBPF bytecode, and load them into the kernel. The kernel's verifier
    checks every program before it runs — guaranteeing no infinite loops,
    no out-of-bounds memory access, and no unsafe pointer arithmetic. After
    verification, the JIT compiler translates bytecode to native machine code
    for near-native performance. Programs attach to kernel events (syscalls,
    network packets, function calls, tracepoints) and execute whenever those
    events fire. Data flows between kernel and userspace through BPF maps.

PRODUCTION USE CASE:
    Netflix uses eBPF (via BCC tools) to profile production latency without
    any application changes. Cloudflare uses XDP eBPF programs to drop DDoS
    packets at line rate before they reach the kernel networking stack.
    Datadog Agent uses eBPF for system-call-level tracing to build distributed
    traces without modifying application code.

COMMON MISTAKES:
    1. Thinking eBPF is just for networking — it covers CPU profiling,
       security, file tracing, scheduler analysis, and more.
    2. Forgetting the verifier limits: max 1 million instructions (kernel 5.2+),
       bounded loops only, stack limited to 512 bytes.
    3. Using BCC in production containers — it requires kernel headers at
       runtime. Prefer libbpf + CO-RE for portable deployments.
    4. Writing to maps without considering concurrent access — use per-CPU
       maps or atomic operations where needed.
    5. Not checking kernel version — many features require kernel 5.x+.
"""

# ============================================================
# SECTION 1: THE PROBLEM eBPF SOLVES
# ============================================================
# Traditional kernel observability had two painful options:
#
# Option A: Kernel Modules
#   - Loaded as kernel code — a bug crashes the entire machine (kernel panic)
#   - Must be compiled for each specific kernel version
#   - Requires rebooting to load/unload safely
#   - Signing requirements in secure-boot environments
#
# Option B: Userspace sampling (strace, perf, /proc polling)
#   - strace adds 2-10x overhead via ptrace — unusable in production
#   - /proc polling misses short-lived events (processes that exec and exit fast)
#   - Userspace context switches add latency to every observation
#
# eBPF Option:
#   - Runs inside the kernel — zero context switch overhead
#   - Verified safe before execution — no kernel panics
#   - JIT compiled — near-native speed
#   - Event-driven — zero cost when event doesn't fire
#   - Portable (with CO-RE) — one binary runs across kernel versions

# ============================================================
# SECTION 2: eBPF PROGRAM TYPES AND ATTACH POINTS
# ============================================================
# Each eBPF program type attaches to a specific kernel location.
# The program type determines what context (arguments) it receives
# and what helper functions it can call.

ebpf_program_types = {
    # --- Tracing and Observability ---
    "kprobe": {
        "description": "Attach to entry of any kernel function",
        "use_case": "Trace sys_read, tcp_sendmsg, do_filp_open, etc.",
        "context": "pt_regs (CPU registers at function entry)",
        "example_attach": "bpf_attach_kprobe(fd, BPF_PROBE_ENTRY, 'do_sys_open', ...)",
    },
    "kretprobe": {
        "description": "Attach to return of any kernel function",
        "use_case": "Measure function latency, capture return values",
        "context": "pt_regs (return value in ax register)",
        "example_attach": "bpf_attach_kprobe(fd, BPF_PROBE_RETURN, 'do_sys_open', ...)",
    },
    "tracepoint": {
        "description": "Attach to static trace points compiled into kernel",
        "use_case": "Stable API, survives kernel updates. syscalls:sys_enter_read, sched:sched_switch",
        "context": "Typed struct specific to each tracepoint",
        "advantage": "More stable than kprobes — tracepoints are ABI-stable",
    },
    "uprobe": {
        "description": "Attach to userspace function entry/exit",
        "use_case": "Trace Python, Go, Java, Node.js functions without modifying code",
        "context": "pt_regs pointing to userspace memory",
        "example": "uprobe:/usr/lib/libssl.so:SSL_write — trace TLS before encryption",
    },
    "perf_event": {
        "description": "Attach to hardware/software perf events",
        "use_case": "CPU profiling at fixed frequency, cache miss analysis",
        "context": "perf_sample_data with stack trace",
    },
    # --- Networking ---
    "XDP": {
        "description": "eXpress Data Path — earliest packet hook, before skb allocation",
        "use_case": "DDoS mitigation, load balancing, packet filtering at line rate",
        "context": "xdp_md (raw packet data pointer, network device)",
        "return_codes": ["XDP_DROP", "XDP_PASS", "XDP_TX", "XDP_REDIRECT", "XDP_ABORTED"],
        "performance": "Can process 24+ million packets/second on commodity hardware",
    },
    "TC": {
        "description": "Traffic Control — hooks into kernel qdisc layer",
        "use_case": "Packet mangling, bandwidth control, container networking",
        "context": "__sk_buff (socket buffer — more features than XDP)",
        "advantage": "Can modify packets, XDP cannot on all hardware",
    },
    "socket_filter": {
        "description": "Classic BPF origin — filter packets on a socket",
        "use_case": "tcpdump, Wireshark, raw socket filtering",
    },
    "cgroup_skb": {
        "description": "Filter traffic per cgroup (container/pod)",
        "use_case": "Per-container network policy, accounting",
    },
    # --- Security ---
    "LSM": {
        "description": "Linux Security Module hooks",
        "use_case": "Enforce security policy at syscall level (file access, exec, network)",
        "context": "Arguments to the security hook being intercepted",
        "min_kernel": "5.7",
    },
    "seccomp": {
        "description": "System call filtering using BPF",
        "use_case": "Container sandboxing (Docker, Kubernetes default seccomp profiles)",
        "context": "seccomp_data (syscall number, arguments)",
    },
}

# ============================================================
# SECTION 3: BPF MAPS — KERNEL-USERSPACE COMMUNICATION
# ============================================================
# Maps are the ONLY way eBPF programs communicate with userspace.
# They are key-value stores that live in kernel memory.
# Both kernel eBPF programs and userspace processes can read/write them.

bpf_map_types = {
    "BPF_MAP_TYPE_HASH": {
        "description": "Hash table — arbitrary key, value types",
        "use_case": "Count events per PID, per IP address, per filename",
        "key": "Any fixed-size type (u32, struct, string)",
        "operations": ["lookup", "update", "delete", "get_next_key"],
        "example": "Map PID -> count of syscalls made",
    },
    "BPF_MAP_TYPE_ARRAY": {
        "description": "Fixed-size array indexed by u32",
        "use_case": "Per-CPU counters, configuration values",
        "note": "All elements pre-allocated at creation — no delete, values zero-initialized",
        "fast": "Faster than hash for sequential/small integer keys",
    },
    "BPF_MAP_TYPE_PERCPU_HASH": {
        "description": "Hash table with per-CPU values",
        "use_case": "High-frequency counters without lock contention",
        "note": "Userspace aggregates across CPUs. Avoids cache line bouncing.",
    },
    "BPF_MAP_TYPE_PERF_EVENT_ARRAY": {
        "description": "Ring buffer to send variable-length data to userspace",
        "use_case": "Stream events (exec events, network connections) to userspace",
        "kernel_api": "bpf_perf_event_output(ctx, &map, BPF_F_CURRENT_CPU, &data, sizeof(data))",
        "userspace": "perf_buffer__poll() in libbpf, or b['events'].open_perf_buffer() in BCC",
        "downside": "Copies data twice — once per CPU, once to userspace",
    },
    "BPF_MAP_TYPE_RINGBUF": {
        "description": "Single shared ring buffer (kernel 5.8+)",
        "use_case": "Replace PERF_EVENT_ARRAY — more efficient, ordered output",
        "advantage": "50% less memory, no per-CPU copies, memory-mappable by userspace",
        "kernel_api": "bpf_ringbuf_output() or bpf_ringbuf_reserve/submit()",
    },
    "BPF_MAP_TYPE_LRU_HASH": {
        "description": "Hash table that evicts least-recently-used entries when full",
        "use_case": "Connection tracking, flow tables — bounded memory automatically",
    },
    "BPF_MAP_TYPE_STACK_TRACE": {
        "description": "Store kernel or userspace stack traces",
        "use_case": "CPU profiling, off-CPU analysis, flamegraph generation",
        "kernel_api": "bpf_get_stackid(ctx, &map, flags)",
    },
    "BPF_MAP_TYPE_PROG_ARRAY": {
        "description": "Array of eBPF program file descriptors",
        "use_case": "Tail calls — jump from one eBPF program to another",
        "note": "Used to work around the 1M instruction limit by chaining programs",
    },
}

# ============================================================
# SECTION 4: THE VERIFIER — WHAT MAKES eBPF SAFE
# ============================================================
# The BPF verifier runs every program through static analysis before
# allowing it to execute in the kernel. This is what makes eBPF safe.

verifier_checks = [
    "DAG check: program must be a directed acyclic graph — no unreachable code",
    "Bounded loops: all loops must provably terminate (bounded by verifier)",
    "Stack size: limited to 512 bytes total",
    "No null pointer dereference: all pointer accesses validated",
    "No out-of-bounds array access: array indices checked against map size",
    "Register type tracking: verifier tracks type of each register through every code path",
    "Helper call validation: only allowed helpers can be called per program type",
    "Return value: program must return a valid value for its type",
    "Instruction limit: max 1,000,000 instructions (kernel 5.2+, was 4,096 before)",
    "No sleeping: eBPF programs run in interrupt/preempt context — cannot sleep or block",
]

# Programs that FAIL verification are rejected before loading.
# The kernel returns -EINVAL and an error message explaining the violation.
# This is why eBPF cannot crash the kernel — bad programs never run.

# ============================================================
# SECTION 5: JIT COMPILATION
# ============================================================
# After verification, eBPF bytecode is JIT-compiled to native machine code.
# Supported architectures: x86_64, ARM64, s390, MIPS, PowerPC, RISC-V.
#
# Enable JIT (should be on by default in modern kernels):
#   echo 1 > /proc/sys/net/core/bpf_jit_enable
#
# JIT performance: within ~5-10% of equivalent native C code.
# The interpreted path (no JIT) is ~4x slower — always use JIT in production.

# ============================================================
# SECTION 6: HELLO WORLD — TRACE execve() SYSCALL
# ============================================================
# This is the canonical eBPF hello world using BCC (Python frontend).
# It traces every exec() call and prints process name + PID.
# Run with: sudo python3 L01_fundamentals.py

hello_world_bpf_c = """
// This C code runs INSIDE the kernel as an eBPF program.
// It attaches to the sys_clone/execve tracepoint and fires on each exec.

#include <uapi/linux/ptrace.h>   // pt_regs type
#include <linux/sched.h>         // TASK_COMM_LEN

// BPF_PERF_OUTPUT defines a perf event map to send data to userspace.
// BCC macro — expands to map definition.
BPF_PERF_OUTPUT(events);

// Data structure we'll send to userspace for each event.
struct event_t {
    u32 pid;
    u32 ppid;
    char comm[TASK_COMM_LEN];   // process name (max 16 bytes)
    char filename[256];
};

// This function is called every time execve() is called.
// 'ctx' is the syscall context (registers, arguments).
int trace_execve(struct tracepoint__syscalls__sys_enter_execve *ctx) {
    struct event_t event = {};

    // bpf_get_current_pid_tgid() returns (tgid << 32 | pid).
    // In Linux, "pid" in kernel = thread ID, "tgid" = process ID.
    u64 id = bpf_get_current_pid_tgid();
    event.pid = id >> 32;        // tgid = userspace PID

    // bpf_get_current_comm() fills buffer with the current process name.
    bpf_get_current_comm(&event.comm, sizeof(event.comm));

    // Read the filename argument from userspace memory.
    // bpf_probe_read_user_str is safe — verifier-checked bounds.
    bpf_probe_read_user_str(&event.filename, sizeof(event.filename),
                            (void *)ctx->filename);

    // Send event to userspace via the perf ring buffer.
    events.perf_submit(ctx, &event, sizeof(event));

    return 0;
}
"""

# Python userspace code (runs outside kernel, reads events from map):
#
# from bcc import BPF
# import ctypes
#
# b = BPF(text=hello_world_bpf_c)
# b.attach_tracepoint(tp="syscalls:sys_enter_execve", fn_name="trace_execve")
#
# class Event(ctypes.Structure):
#     _fields_ = [("pid", ctypes.c_uint32),
#                 ("ppid", ctypes.c_uint32),
#                 ("comm", ctypes.c_char * 16),
#                 ("filename", ctypes.c_char * 256)]
#
# def print_event(cpu, data, size):
#     event = ctypes.cast(data, ctypes.POINTER(Event)).contents
#     print(f"PID={event.pid} COMM={event.comm.decode()} FILE={event.filename.decode()}")
#
# b["events"].open_perf_buffer(print_event)
# print("Tracing execve... Ctrl+C to stop")
# while True:
#     b.perf_buffer_poll()

# ============================================================
# SECTION 7: TOOLING ECOSYSTEM
# ============================================================

ebpf_tools = {
    "BCC (BPF Compiler Collection)": {
        "language": "Python + embedded C",
        "install": "apt install bpfcc-tools python3-bpfcc  OR  pip install bcc",
        "best_for": "Development, scripting, one-off tools",
        "downside": "Requires kernel headers at runtime, LLVM/Clang dependency",
        "included_tools": [
            "execsnoop  - trace new process executions",
            "opensnoop  - trace file open() calls",
            "tcplife    - trace TCP connection lifecycle",
            "biolatency - block IO latency histogram",
            "profile    - CPU profiling with flamegraphs",
            "memleak    - detect memory leaks in userspace programs",
            "runqlat    - scheduler run queue latency",
        ],
    },
    "bpftrace": {
        "language": "High-level tracing language (like awk for kernel events)",
        "install": "apt install bpftrace",
        "best_for": "One-liners and quick investigations",
        "example_1": "bpftrace -e 'kprobe:do_sys_open { printf(\"%s\\n\", comm); }'",
        "example_2": "bpftrace -e 'tracepoint:syscalls:sys_enter_read { @[comm] = count(); }'",
        "example_3": "bpftrace -e 'profile:hz:99 { @[kstack] = count(); }'  # CPU profiling",
    },
    "libbpf (C library)": {
        "language": "C",
        "best_for": "Production tools, portable (CO-RE), low dependency",
        "workflow": "Write BPF C → compile with clang → load with libbpf API",
        "portability": "CO-RE: one compiled binary works across kernel versions",
    },
    "cilium/ebpf (Go library)": {
        "language": "Go (no CGO)",
        "best_for": "Go services that need eBPF — Kubernetes operators, agents",
        "codegen": "bpf2go generates Go types from BPF C code",
        "used_by": "Cilium, Datadog Agent, Parca profiler",
    },
    "Aya (Rust library)": {
        "language": "Rust",
        "best_for": "Rust services, memory safety in both BPF and userspace code",
        "note": "Write BPF programs in Rust — compiled with rustc's BPF target",
    },
}

# ============================================================
# SECTION 8: KEY KERNEL VERSION MILESTONES
# ============================================================
# Know your minimum kernel version requirements before deploying.

kernel_milestones = {
    "3.15": "eBPF introduced (network only)",
    "3.18": "BPF syscall, verifier, maps",
    "4.1":  "kprobes, tracepoints support",
    "4.4":  "JIT for all architectures",
    "4.7":  "perf events, stack traces",
    "4.9":  "hardware perf events",
    "4.15": "BTF support begins",
    "5.1":  "Ring buffer map",
    "5.2":  "1M instruction limit (up from 4,096)",
    "5.3":  "Bounded loops (verifier can prove termination)",
    "5.7":  "BPF LSM hooks, CAP_BPF capability",
    "5.8":  "Ring buffer map (BPF_MAP_TYPE_RINGBUF), CO-RE improvements",
    "5.13": "Unsigned BPF programs (kernel module signing requirement)",
    "6.0":  "BPF exceptions, improved verifier for complex programs",
}

print("eBPF L01: Fundamentals loaded. See comments for BCC hello-world example.")
print(f"Kernel milestones tracked: {len(kernel_milestones)}")
print(f"Map types documented: {len(bpf_map_types)}")
print(f"Program types documented: {len(ebpf_program_types)}")
