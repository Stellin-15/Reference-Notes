# ============================================================
# L08: Running eBPF in Production
# ============================================================
# WHAT: The operational concerns of deploying eBPF-based tooling on real
#       Kubernetes/Linux fleets — kernel compatibility, privileges,
#       performance overhead, debugging, and safe rollout.
# WHY (PRODUCTION): eBPF programs run in kernel space; a mistake has a
#       fundamentally different blast radius than a userspace bug. Treating
#       eBPF deployment with the same rigor as kernel-module deployment
#       (which it functionally resembles in risk, if not in safety
#       mechanism) is the difference between a smooth rollout and a
#       fleet-wide incident.
# LEVEL: Staff platform / security engineer
# ============================================================

"""
CONCEPT OVERVIEW:
eBPF's verifier provides strong safety guarantees (no unbounded loops, no
out-of-bounds memory access, bounded execution) that make it fundamentally
safer than a kernel module — but "safer than a kernel module" is not "risk
free". A production rollout still needs to account for kernel version
variance across the fleet, the privilege model for who can load BPF
programs, and the CPU/memory overhead the program adds to the hot path
it's attached to.

PRODUCTION USE CASE:
A platform team rolling out a new eBPF-based network observability agent
first deploys it to a canary node pool (5% of the fleet) with a
`resources.limits` bound and RollingUpdate maxUnavailable=1, monitoring
node-level CPU overhead and program-attach failure rate for 48 hours before
fleet-wide rollout — treating it with the same caution as any other
privileged DaemonSet, because a bug causing every node's eBPF program to
fail to load simultaneously would be a synchronized fleet-wide incident.

COMMON MISTAKES:
- Assuming BTF/CO-RE "just works" on every node without checking — older
  kernels or custom-built kernels without CONFIG_DEBUG_INFO_BTF enabled
  won't have /sys/kernel/btf/vmlinux at all, and the program fails to load.
- Running eBPF DaemonSets as fully privileged (`privileged: true`) instead
  of the minimal capability set (CAP_BPF, CAP_NET_ADMIN, CAP_PERFMON on
  modern kernels) — unnecessarily widens the attack surface if the
  container itself is compromised.
- No alerting on "eBPF program failed to load/attach" — a silent failure
  means your security/observability tool THINKS it's running but isn't
  actually watching anything.
"""

import textwrap

# ------------------------------------------------------------------
# 1. Kernel version compatibility
# ------------------------------------------------------------------
KERNEL_COMPATIBILITY_NOTES = {
    "4.x": "Basic eBPF (kprobes, socket filters) works; CO-RE/BTF support "
        "is absent or unreliable — effectively BCC-only territory.",
    "5.4+": "BTF support generally available; ring buffer maps "
        "(BPF_MAP_TYPE_RINGBUF) require 5.8+.",
    "5.7+": "LSM BPF hooks available (CONFIG_BPF_LSM=y required, often "
        "NOT enabled by default even on 5.7+ kernels — verify explicitly).",
    "5.10+": "Considered the practical modern baseline for full-featured "
        "CO-RE tooling in most current production deployments.",
}

CHECK_BTF_AVAILABILITY = (
    "ls -la /sys/kernel/btf/vmlinux\n"
    "# If this file doesn't exist, the running kernel wasn't built with\n"
    "# CONFIG_DEBUG_INFO_BTF=y — CO-RE programs relying on kernel BTF\n"
    "# relocation will fail to load. Check this as a PRE-DEPLOY gate,\n"
    "# not something discovered from a fleet-wide load failure."
)

# ------------------------------------------------------------------
# 2. Privilege requirements — beyond root
# ------------------------------------------------------------------
CAPABILITY_MODEL = textwrap.dedent("""\
    # Older kernels effectively required full root (CAP_SYS_ADMIN) to load
    # ANY BPF program. Modern kernels (5.8+) split this into finer-grained
    # capabilities — use the MINIMAL set your program actually needs:

    apiVersion: v1
    kind: Pod
    spec:
      containers:
        - name: ebpf-agent
          securityContext:
            privileged: false          # do NOT reach for this by default
            capabilities:
              add:
                - BPF                  # CAP_BPF — load/verify BPF programs
                - NET_ADMIN             # required for XDP/TC attachment specifically
                - PERFMON               # CAP_PERFMON — perf_event/tracing programs
              drop: ["ALL"]
""")

# ------------------------------------------------------------------
# 3. Performance overhead — what to actually measure
# ------------------------------------------------------------------
PERFORMANCE_OVERHEAD_NOTES = {
    "typical_cpu_overhead": "Well-written eBPF programs (simple map "
        "lookups, minimal branching) typically add well under 1% CPU "
        "overhead to the hot path they're attached to — but this is NOT "
        "guaranteed; a program doing expensive work per-packet (e.g. deep "
        "payload inspection) can be measurably more.",
    "map_lookup_cost": "Hash map lookups are the dominant per-invocation "
        "cost in most programs — LPM trie lookups (CIDR matching) are "
        "notably more expensive than plain hash lookups; benchmark before "
        "assuming a design choice is 'free'.",
    "perf_buffer_overhead": "High-frequency events through a perf buffer "
        "(not ring buffer) can generate meaningful per-CPU wakeup/copy "
        "overhead at very high event rates — this is one of the practical "
        "reasons ring buffer became the modern default (see L07).",
}

# ------------------------------------------------------------------
# 4. Debugging — verifier errors and runtime introspection
# ------------------------------------------------------------------
DEBUGGING_COMMANDS = textwrap.dedent("""\
    # List all currently loaded BPF programs system-wide, with their type
    # and attach point — the first stop when debugging "is my program even
    # running".
    bpftool prog show

    # Dump a specific map's live contents — invaluable for verifying your
    # program is actually populating the data you expect.
    bpftool map dump id 42

    # Verifier rejection output — read this carefully, it names the EXACT
    # instruction and register state that failed verification:
    #   "R1 offset is outside of the allowed memory range"
    #   -> almost always a missing/incorrect data_end bounds check (see L04)
    dmesg | grep -i "bpf"

    # bpftool prog dump xlated shows the JIT-compiled/translated program —
    # useful for confirming CO-RE relocations resolved as expected on this
    # specific kernel.
    bpftool prog dump xlated id 42
""")

COMMON_VERIFIER_ERRORS = {
    "invalid mem access": "Missing bounds check before dereferencing a "
        "packet-data pointer (see L04's mandatory data/data_end pattern).",
    "back-edge from insn X to Y": "An unbounded or verifier-unprovable "
        "loop — bound your loops explicitly with `#pragma unroll` or a "
        "compile-time-known iteration count.",
    "program is too large": "Instruction count limit exceeded (historically "
        "4096, raised significantly on modern kernels but still finite) — "
        "split logic across tail-called programs if genuinely needed.",
    "unreachable insn": "Usually a sign the compiler optimized code in a "
        "way the verifier's control-flow analysis couldn't follow — try "
        "adjusting optimization level or restructuring conditionals.",
}

# ------------------------------------------------------------------
# 5. Memory limits
# ------------------------------------------------------------------
MEMORY_LIMITS_NOTES = (
    "BPF programs have a fixed stack limit (512 bytes) — deeply nested "
    "struct copies or large local arrays will hit this quickly; use "
    "per-CPU BPF maps as 'scratch space' instead of large stack "
    "allocations when a program needs more working memory than the stack "
    "allows. Map entry COUNT and value SIZE are both bounded at map "
    "creation time (`max_entries`) — sizing this too small silently drops "
    "writes past capacity depending on map type, so size deliberately "
    "based on expected cardinality, not a guess."
)

# ------------------------------------------------------------------
# 6. Zero-downtime program updates
# ------------------------------------------------------------------
ATOMIC_REPLACE_NOTE = (
    "Updating an attached BPF program (e.g. new logic version) can be "
    "done atomically via bpf_link's UpdateProgram (cilium/ebpf) or the "
    "equivalent libbpf call — the old program continues handling in-flight "
    "events until the new one is fully attached, avoiding a window where "
    "NO program is attached (which for something like an XDP DDoS filter "
    "would mean a brief unprotected window during every update)."
)

# ------------------------------------------------------------------
# 7. Observability of eBPF itself
# ------------------------------------------------------------------
SELF_OBSERVABILITY_NOTES = [
    "Export a Prometheus metric on program load SUCCESS/FAILURE at "
    "startup — a DaemonSet whose eBPF program silently failed to attach "
    "looks 'Running' in Kubernetes but is doing nothing.",
    "Periodically read a BPF map holding a monotonic event counter your "
    "program itself increments, and alert if it stops changing — this "
    "distinguishes 'program running but no events matched' from 'program "
    "silently stopped receiving events'.",
    "Track bpftool prog show's run_time_ns / run_cnt fields (if JIT stats "
    "are enabled) as a lightweight signal of whether the program is "
    "actually being invoked at the expected rate.",
]

if __name__ == "__main__":
    for err, meaning in COMMON_VERIFIER_ERRORS.items():
        print(f"{err}: {meaning}")

"""
TRADING/PRODUCTION CONTEXT EXAMPLE:
A platform team canary-deploys an updated XDP-based DDoS mitigation
program to 5% of edge-facing nodes, monitoring bpftool-derived
invocation-count metrics to confirm the new program is actually being hit
at the expected packet rate before rolling out fleet-wide — because an
XDP program that fails to load leaves that node with ZERO DDoS protection
at the kernel level, silently, unless load success is explicitly monitored
rather than assumed from "the DaemonSet pod shows Running".
"""
