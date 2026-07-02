# ============================================================
# L05: eBPF for Runtime Security
# ============================================================
# WHAT: Using eBPF's syscall/LSM visibility to detect and enforce security
#       policy on running workloads in real time — the mechanism behind
#       Falco, Tetragon, and Tracee.
# WHY (PRODUCTION): Traditional security tooling (log-based, agent-polling)
#       has minutes of detection lag. eBPF hooks kernel events as they
#       happen — a container escape attempt or unexpected process execution
#       is visible (and can be BLOCKED, not just logged) in real time.
# LEVEL: Senior / Staff security & platform engineer
# ============================================================

"""
CONCEPT OVERVIEW:
Runtime security tools built on eBPF attach to syscall tracepoints (execve,
openat, connect) or LSM (Linux Security Module) hooks, giving visibility
into every process execution, file access, and network connection on a
host — without the overhead of a full audit subsystem or per-process agent.

The key architectural distinction is DETECTION vs ENFORCEMENT: kprobe/
tracepoint-based tools (Falco, Tracee) can only observe and alert AFTER an
action already happened. LSM BPF hooks run at the actual kernel security
decision point, BEFORE the action completes, and can return a non-zero
value to BLOCK it — this is what makes Tetragon capable of "enforcement",
not just detection.

PRODUCTION USE CASE:
A Kubernetes cluster runs Falco with a rule set that alerts when a shell is
spawned inside a container that shouldn't normally have one (`spawned
process is a shell in a container` — a classic reverse-shell indicator).
Tetragon, running with an LSM enforcement policy, actively BLOCKS any
process in production namespaces from executing `/bin/sh` at all, closing
off entire attack classes rather than just alerting on them after the fact.

COMMON MISTAKES:
- Treating detection-only tools (Falco/Tracee) as if they prevent
  anything — they alert; a human or automated response system must still
  act (kill pod, page on-call) for it to matter.
- Deploying default rule sets without tuning — Falco's stock rules
  generate significant noise in normal Kubernetes clusters (e.g. package
  managers running during image builds trigger "package management process
  launched" alerts constantly if not scoped).
- Confusing seccomp with eBPF LSM: seccomp filters syscalls by number/args
  with no kernel-state context; eBPF LSM hooks have full context (which
  file, which process, which container) and can express far richer policy.
"""

import textwrap

# ------------------------------------------------------------------
# 1. Falco rules — syscall-based detection
# ------------------------------------------------------------------
FALCO_RULE_EXAMPLE = textwrap.dedent("""\
    # /etc/falco/falco_rules.local.yaml
    - rule: Unexpected shell in container
      desc: A shell was spawned inside a container that shouldn't have one
      condition: >
        spawned_process
        and container
        and shell_procs
        and not proc.pname in (allowed_shell_parents)
      output: >
        Shell spawned in container (user=%user.name container=%container.name
        shell=%proc.name parent=%proc.pname cmdline=%proc.cmdline)
      priority: WARNING
      tags: [container, shell, mitre_execution]

    - rule: Write below etc
      desc: An attempt to write to /etc, often used for persistence
      condition: >
        open_write and fd.name startswith /etc
        and not proc.name in (trusted_etc_writers)
      output: "File below /etc opened for writing (file=%fd.name proc=%proc.name)"
      priority: ERROR
""")

# ------------------------------------------------------------------
# 2. LSM BPF — enforcement, not just detection
# ------------------------------------------------------------------
LSM_BPF_PROGRAM = textwrap.dedent("""\
    // LSM BPF programs attach to actual kernel security hook points
    // (bprm_check_security runs before a new process image is executed)
    // and can return non-zero to DENY the action outright.
    #include <linux/bpf.h>
    #include <bpf/bpf_helpers.h>

    SEC("lsm/bprm_check_security")
    int BPF_PROG(deny_shell_exec, struct linux_binprm *bprm) {
        char comm[16];
        bpf_probe_read_kernel_str(&comm, sizeof(comm), bprm->filename);

        // Compare against a denylist — real implementations use a BPF
        // map for the denylist rather than a hardcoded string, so policy
        // updates don't require recompiling/reloading the program.
        if (__builtin_memcmp(comm, "/bin/sh", 7) == 0) {
            return -1;  // EPERM — the exec syscall itself fails for the caller
        }
        return 0;  // allow
    }
    char _license[] SEC("license") = "GPL";

    // This is fundamentally different from a kprobe on execve: a kprobe
    // fires AFTER the kernel has already decided to allow the exec — you
    // can only log/kill after the fact. LSM hooks run AT the decision
    // point and can prevent the action from ever completing.
""")

# ------------------------------------------------------------------
# 3. Tetragon — Cilium's process-execution enforcement
# ------------------------------------------------------------------
TETRAGON_POLICY = textwrap.dedent("""\
    apiVersion: cilium.io/v1alpha1
    kind: TracingPolicy
    metadata:
      name: block-shell-in-prod
    spec:
      kprobes:
        - call: "sys_execve"
          syscall: true
          args:
            - index: 0
              type: "string"
          selectors:
            - matchArgs:
                - index: 0
                  operator: "Equal"
                  values: ["/bin/sh", "/bin/bash"]
              matchNamespaces:
                - namespace: NAMESPACE
                  operator: In
                  values: ["production"]
              matchActions:
                - action: Sigkill   # actively kill the process, not just log
""")

# ------------------------------------------------------------------
# 4. Container escape detection
# ------------------------------------------------------------------
CONTAINER_ESCAPE_INDICATORS = [
    "A process inside a container gains a new mount namespace matching "
    "the HOST's mount namespace ID — a strong signal of a successful "
    "container-breakout technique (e.g. via a mounted docker.sock).",
    "A container process writes to a cgroup release_agent file — a "
    "well-known container escape technique; eBPF can hook the specific "
    "openat/write syscalls targeting that path.",
    "Unexpected capability usage: a process using CAP_SYS_ADMIN or "
    "CAP_SYS_PTRACE inside a container that was not granted those "
    "capabilities at pod creation — visible via LSM capable() hook.",
]

# ------------------------------------------------------------------
# 5. Tracee (Aqua Security) — event-driven security monitoring
# ------------------------------------------------------------------
TRACEE_NOTE = (
    "Tracee focuses on 'security events' as a curated, higher-level "
    "abstraction over raw syscalls — e.g. a single 'anti_debugging' event "
    "instead of requiring the operator to know which specific ptrace "
    "syscall arguments indicate anti-debugging behavior. It ships "
    "pre-built detection signatures (Go plugins) for common attack "
    "techniques (MITRE ATT&CK-mapped) rather than requiring the operator "
    "to write raw Falco-style rule conditions from scratch."
)

# ------------------------------------------------------------------
# 6. seccomp vs eBPF LSM — a real distinction
# ------------------------------------------------------------------
SECCOMP_VS_LSM = {
    "seccomp": "Filters by syscall NUMBER and raw argument VALUES only — "
        "no kernel-state context (can't ask 'is this file inside /etc',  "
        "only 'is this the openat syscall with this exact flag bitmask'). "
        "Simpler, lower overhead, supported everywhere (no BTF/CO-RE "
        "requirement).",
    "eBPF LSM": "Full kernel context available at the hook — can inspect "
        "the actual resolved file path, the calling process's full "
        "credential/namespace state, container identity via cgroup ID. "
        "Requires a modern kernel (5.7+) with LSM BPF support (CONFIG_"
        "BPF_LSM=y) — not universally available on older/managed "
        "Kubernetes node images without opt-in.",
}

# ------------------------------------------------------------------
# 7. Incident response with eBPF
# ------------------------------------------------------------------
IR_USE_CASES = [
    "Real-time process tree reconstruction: eBPF captures the FULL "
    "parent-child exec chain as it happens, giving IR responders exact "
    "provenance (which process spawned which) without relying on "
    "after-the-fact /proc scraping that may have already lost the data.",
    "Network flow capture at the syscall level (connect/accept) gives an "
    "authoritative record of every outbound connection a compromised "
    "process made — more reliable than netflow sampling, which can miss "
    "short-lived connections entirely.",
]

if __name__ == "__main__":
    print("Container escape indicators:")
    for i in CONTAINER_ESCAPE_INDICATORS:
        print(f"  - {i}")

"""
TRADING/PRODUCTION CONTEXT EXAMPLE:
A trading firm's production Kubernetes namespace runs a Tetragon policy
that kills any process attempting to exec a shell inside an order-execution
pod — even a successful RCE against the application can't escalate into an
interactive shell, because the kernel-level LSM hook blocks the exec before
it completes, closing off the most common post-exploitation step regardless
of which application-layer vulnerability was exploited to get there.
"""
