# eBPF — Principal Engineer Deep Dive

Companion to the existing lessons. Narrative depth on core mechanisms, then
a comprehensive common-to-uncommon tool reference.


## What eBPF Actually Is

**Beyond the lesson**: eBPF (extended Berkeley Packet Filter) lets you run
sandboxed, JIT-compiled programs INSIDE the Linux kernel, triggered by
events (a syscall, a network packet, a function entry) — WITHOUT writing a
kernel module or recompiling the kernel. The verifier is what makes this
safe: before an eBPF program is loaded, the kernel statically analyzes it
to guarantee it terminates (no unbounded loops — a strict instruction-count
bound applies), can't access arbitrary memory, and can't crash the kernel —
a genuinely novel safety guarantee that's why eBPF exploded in adoption
where kernel modules never could (a bad kernel module panics the whole machine).

**Worked example**: The classic three-part architecture — a small eBPF
program is written (commonly in restricted C, compiled via LLVM to eBPF
bytecode), loaded into the kernel and attached to a hook point (a kprobe on
a syscall, an XDP hook on a NIC, a cgroup hook), and communicates with
userspace via eBPF MAPS (shared key-value data structures the kernel
program writes to and a userspace program reads from) — this map-based
communication is how tools like `bpftrace`/Cilium/Pixie get kernel-level
data out to something a human or dashboard can actually use.

**Interview Q&A**:
- *Q: Why can eBPF replace both a kernel module AND a sidecar container for observability?* A: A kernel module requires kernel-version-specific compilation and can crash the whole machine if buggy; a sidecar container only sees userspace/network-boundary behavior, missing syscall-level visibility. eBPF gets kernel-level visibility (like a module) with verifier-enforced safety (unlike a module) and without adding a container per host (unlike a sidecar).


## Hook Points & Program Types

**Beyond the lesson**: Different hook points solve genuinely different
problems, and knowing which one to reach for is the actual skill:
- **kprobes/uprobes** — attach to (almost) any kernel or userspace function
  entry/exit dynamically, without that function needing to have been
  designed with tracing in mind — maximally flexible, but can break across
  kernel versions since it hooks internal, unstable function signatures.
- **tracepoints** — stable, kernel-maintainer-blessed hook points (unlike
  raw kprobes) — the safer choice when a tracepoint exists for what you need.
- **XDP** (eXpress Data Path) — runs at the earliest possible point in the
  network stack, on the NIC driver itself, before the kernel even builds a
  full `sk_buff` — used for line-rate packet filtering/load balancing
  (Cloudflare's DDoS mitigation, Cilium's fast-path packet processing).
- **cgroup hooks** — attach to a cgroup (see Docker Notes) to enforce
  per-container network/syscall policy — this is exactly how Cilium
  implements Kubernetes NetworkPolicy without iptables at all.

**Interview Q&A**:
- *Q: Why does Cilium replace kube-proxy's iptables-based service routing with eBPF?* A: iptables rule evaluation is O(n) in the number of rules and gets measurably slower as a cluster's service count grows; eBPF maps provide O(1) hash-lookup-based routing regardless of service count, which is why large K8s clusters see real latency/CPU improvements switching to Cilium's eBPF dataplane.


## COMPREHENSIVE TOOL REFERENCE — COMMON TO UNCOMMON

### Observability & tracing tools built on eBPF
- **bpftrace** — a high-level, awk/DTrace-like scripting language for
  writing one-off eBPF tracing scripts quickly, without full C+LLVM
  compilation — the "quick production diagnostic" tool of choice.
- **BCC (BPF Compiler Collection)** — a library + collection of pre-built
  tracing tools (`biolatency`, `execsnoop`, `tcplife`) covering the most
  common "why is this slow" questions out of the box, no custom code needed.
- **Pixie** — auto-instruments a Kubernetes cluster with eBPF for full
  request tracing/service-map visibility with ZERO application code
  changes — a genuinely distinctive "no instrumentation SDK required" value
  proposition versus traditional OpenTelemetry-based tracing.
- **Parca / Pyroscope** — continuous, always-on eBPF-based CPU profiling in
  production with negligible overhead (see Observability Notes deep dive
  section on continuous profiling).

### Networking & security
- **Cilium** — the dominant eBPF-based CNI (see Kubernetes Notes deep dive
  section 21) — networking, network policy, load balancing, AND observability (Hubble) in one.
- **Falco** — runtime security monitoring via eBPF (see Ethical Hacking
  Notes section 15) — watches syscalls for suspicious in-container behavior.
- **Katran** (Meta) — an eBPF/XDP-based L4 load balancer, open-sourced,
  used as a reference for building extremely high-throughput load balancers
  in software rather than dedicated hardware appliances.

### Development & tooling
- **libbpf** — the standard C library for loading/managing eBPF programs,
  increasingly the portable foundation other tools build on (CO-RE —
  Compile Once, Run Everywhere — lets a compiled eBPF program run across
  different kernel versions without recompilation, solving what used to be
  eBPF's biggest portability pain point).
- **Cilium's eBPF Go library** — for teams building custom eBPF tooling in
  Go rather than C, increasingly common as eBPF adoption grows beyond
  historically C-only kernel programming circles.


## NICHE BUT REAL

- **eBPF for security enforcement, not just observation** — beyond Falco's
  passive monitoring, some tools use eBPF to actively BLOCK a syscall in
  real time (not just alert after the fact) — a meaningfully stronger
  security posture than log-and-alert, still an emerging practice area.
- **Sidecar-less service mesh** — Cilium's "service mesh without sidecars"
  pitch replaces the per-pod Envoy proxy (Istio's traditional model) with
  eBPF enforcement at the node/kernel level — a real, actively-debated
  architectural alternative to sidecar-based meshes, trading some L7
  feature richness for lower per-pod resource overhead.
- **eBPF verifier limitations in practice** — the verifier's strict
  instruction-count and loop-bounding rules mean genuinely complex logic
  sometimes CAN'T be expressed as a single eBPF program and must be split
  across a chain of tail-called programs — a real constraint that shapes
  how eBPF tools are architected internally.
- **Kernel version fragmentation** — despite BTF/CO-RE improving
  portability significantly, eBPF feature availability still varies by
  kernel version in the wild (especially on older enterprise Linux
  distributions) — a genuine deployment constraint for eBPF-based products
  targeting heterogeneous fleets.
