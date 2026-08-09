"""
WHAT: Four realistic eBPF-based observability/networking/security
      problems, each solved with THREE genuinely different, individually
      defensible approaches drawn from L01-L08 -- with an explicit
      comparison table and reasoning for why each answer is valid under
      different constraints.
WHY:  "bcc or libbpf," "XDP or a userspace solution," "Cilium or a
      hand-rolled eBPF program" are all questions L01-L08 gave you real
      tools for, not one universal answer -- this lesson is about the
      decision process under real performance and maintainability
      constraints.
LEVEL: Capstone -- read after L01-L08.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L08's concepts.
"""

# ============================================================================
# CASE STUDY 1 — CHOOSING A TOOLING APPROACH FOR A NEW EBPF-BASED
# OBSERVABILITY TOOL
# ============================================================================
#
# SETUP: building a custom tool to trace a specific kernel event pattern
# relevant to the team's production workload -- deciding on the
# development toolchain (L02, L07).
#
# ------------------------------------------------------------------------
# APPROACH A: BCC (BPF Compiler Collection) (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, BCC provides a Python-based development
#   experience with an extensive library of pre-built tracing tools and
#   examples -- the fastest path to a working prototype, especially for
#   a team more comfortable in Python than C, and BCC compiles eBPF C
#   code at RUNTIME, requiring no separate build/deployment step for the
#   BPF bytecode itself.
#   COST: per L02/L07, BCC's runtime compilation approach requires the
#   FULL kernel headers/LLVM toolchain to be present on every machine
#   the tool runs on -- a real, nontrivial deployment dependency for
#   production machines, and BCC's Python wrapper layer adds real
#   startup latency/overhead compared to a pre-compiled approach.
#
# ------------------------------------------------------------------------
# APPROACH B: libbpf with CO-RE (Compile Once - Run Everywhere) (L07)
# ------------------------------------------------------------------------
#   WHY VALID: per L07, libbpf+CO-RE compiles the eBPF program ONCE,
#   producing a portable bytecode artifact that runs across different
#   kernel versions without needing kernel headers or a compiler
#   present on the target machine at runtime -- directly solves A's
#   deployment-dependency problem, the modern standard for
#   production-grade eBPF tooling distribution.
#   COST: per L07, requires writing the eBPF program in C (or Go via
#   cilium/ebpf, still requiring more careful, lower-level programming
#   than BCC's Python convenience layer) -- a real, steeper development
#   experience than A's more accessible Python-centric workflow,
#   especially for a team without existing C/systems-programming
#   comfort.
#
# ------------------------------------------------------------------------
# APPROACH C: Prototype quickly with BCC (A) to validate the tracing
# approach actually captures the needed data correctly, THEN reimplement
# in libbpf+CO-RE (B) for the production-deployed version
# ------------------------------------------------------------------------
#   WHY VALID: per L02/L07's own framing (BCC as prototyping-friendly,
#   libbpf+CO-RE as the production-portable answer), this captures A's
#   fast iteration speed for the exploratory phase (where the actual
#   tracing LOGIC might need real experimentation to get right) while
#   still arriving at B's deployment-friendly artifact for the version
#   that actually ships to production machines.
#   COST: genuinely more total work than either A or B alone -- the
#   tracing logic effectively gets implemented twice (once in BCC's
#   Python/C hybrid for prototyping, once properly in libbpf C/CO-RE for
#   production), a real, if often worthwhile, cost specifically when
#   the tracing logic's correctness is genuinely uncertain upfront and
#   worth de-risking before committing to the more effort-intensive
#   production implementation.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Development speed | Production deployment friction | Portability across kernel versions |
#   |----------|------------------------|---------------------------------------|--------------------------------------------|
#   | A: BCC | Fastest | High (needs kernel headers/LLVM at runtime) | Poor without those dependencies present |
#   | B: libbpf + CO-RE | Slower | Low (portable compiled artifact) | Good |
#   | C: BCC prototype, then libbpf for production | Medium overall | Low, for the final artifact | Good, for the final artifact |
#   C is the strongest answer when the tracing logic itself is
#   genuinely uncertain/exploratory; go straight to B if the team
#   already has clear confidence in the exact kernel events/logic
#   needed and C's prototyping phase wouldn't meaningfully change the
#   final implementation.


# ============================================================================
# CASE STUDY 2 — MITIGATING A DDOS-STYLE TRAFFIC PATTERN AT THE NETWORK
# EDGE
# ============================================================================
#
# SETUP: a service is receiving a high volume of malicious/unwanted
# traffic that needs to be dropped as early and cheaply as possible
# (L04's XDP discussion).
#
# ------------------------------------------------------------------------
# APPROACH A: Filter the traffic in USERSPACE, in the application's own
# request-handling code (e.g. check a source-IP blocklist and reject
# early in the request handler)
# ------------------------------------------------------------------------
#   WHY VALID: simplest to implement -- ordinary application code, no
#   new kernel-level tooling, easy to iterate on the filtering logic
#   using familiar application-development tools and deployment
#   processes.
#   COST: per L04, by the time traffic reaches USERSPACE application
#   code, it has already traversed the FULL kernel networking stack
#   (interrupt handling, socket buffer allocation, protocol processing)
#   -- for a genuinely high-volume malicious traffic pattern, this
#   means the SERVER is still paying substantial per-packet processing
#   cost for traffic that's ultimately just going to be dropped anyway,
#   real wasted CPU/resources precisely during an attack, when
#   resources matter most.
#
# ------------------------------------------------------------------------
# APPROACH B: An XDP (eXpress Data Path) program (L04) that drops
# malicious traffic at the EARLIEST possible point -- directly at the
# network driver level, before the packet even enters the normal kernel
# networking stack
# ------------------------------------------------------------------------
#   WHY VALID: per L04, XDP operates at the lowest practical software
#   layer (right after the NIC driver receives a packet), letting
#   malicious packets be dropped with DRAMATICALLY less per-packet CPU
#   cost than A -- directly targets the actual problem (wasting
#   resources processing traffic that's going to be discarded anyway)
#   at its root, the standard, well-established answer for exactly this
#   high-volume-filtering use case.
#   COST: per L04, XDP programs are genuinely more complex to write and
#   debug than userspace application code -- operating at this low a
#   level means less access to rich application-level context (an XDP
#   program sees raw packets, not application-level request semantics),
#   and getting the filtering LOGIC itself wrong at this level (e.g. an
#   overly broad rule) can silently drop LEGITIMATE traffic with less
#   visibility/debuggability than an equivalent application-level
#   mistake would have.
#
# ------------------------------------------------------------------------
# APPROACH C: A managed DDoS protection service/CDN (e.g. Cloudflare,
# AWS Shield) positioned upstream of the infrastructure entirely, rather
# than building custom XDP-based filtering
# ------------------------------------------------------------------------
#   WHY VALID: per general infrastructure practice (complementing L04's
#   technical XDP discussion), a managed service absorbs the FULL
#   engineering burden of building, maintaining, and continuously
#   updating attack-detection/mitigation logic against an evolving
#   threat landscape -- for most organizations, this is dramatically
#   less ongoing effort than maintaining custom XDP-based filtering,
#   and such services often have visibility into attack patterns across
#   MANY customers, informing better detection than one team's own,
#   necessarily narrower view.
#   COST: real, ongoing service cost, and introduces a genuine
#   third-party dependency in the critical traffic path -- for
#   organizations with very specific, unusual traffic-filtering needs
#   a general-purpose managed service doesn't address well, or with
#   strong reasons to keep all infrastructure self-managed, custom XDP
#   tooling (B) remains the more tailored, if more effort-intensive,
#   answer.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Per-packet filtering cost | Engineering/maintenance burden | Fits highly custom filtering needs |
#   |----------|--------------------------------|---------------------------------------|--------------------------------------------|
#   | A: userspace application filtering | Highest (full stack traversal first) | Lowest | Best (full application context) |
#   | B: XDP-based filtering | Lowest | Medium-high (ongoing custom development) | Good, with more effort |
#   | C: managed DDoS protection service | Lowest (filtered before reaching your infra at all) | Lowest (outsourced) | Limited to the service's capabilities |
#   For most organizations facing genuine, large-scale malicious
#   traffic, C is the pragmatic default (dedicated services do this
#   better than most teams can build/maintain themselves); B is the
#   right answer for genuinely custom, self-managed infrastructure
#   needs a managed service doesn't cover, where the team has the
#   eBPF/XDP expertise to build and maintain it well.


# ============================================================================
# CASE STUDY 3 — ENFORCING NETWORK POLICY IN A KUBERNETES CLUSTER
# ============================================================================
#
# SETUP: a Kubernetes cluster needs fine-grained network policy
# enforcement (which pods can talk to which) -- deciding on the
# implementation approach (L06, Kubernetes Notes).
#
# ------------------------------------------------------------------------
# APPROACH A: Standard Kubernetes NetworkPolicy resources, enforced by
# whatever CNI plugin's default implementation (Kubernetes Notes L08)
# ------------------------------------------------------------------------
#   WHY VALID: uses the standard, portable Kubernetes API for network
#   policy -- works across any CNI plugin that supports NetworkPolicy,
#   no vendor/implementation-specific lock-in, the most broadly
#   compatible and simplest starting point.
#   COST: standard NetworkPolicy resources have real EXPRESSIVENESS
#   limits -- they support relatively basic pod/namespace-selector-based
#   rules, but lack more advanced capabilities (L7/application-layer-
#   aware policy, e.g. "allow GET requests to this API but not POST")
#   that some organizations genuinely need.
#
# ------------------------------------------------------------------------
# APPROACH B: Cilium (L06), an eBPF-based CNI providing richer policy
# capabilities beyond standard NetworkPolicy
# ------------------------------------------------------------------------
#   WHY VALID: per L06, Cilium's eBPF-based implementation directly
#   addresses A's expressiveness limit -- supports L7-aware policies,
#   richer identity-based security models, and (per L06) generally
#   more efficient packet processing than traditional iptables-based CNI
#   implementations, since eBPF operates at a lower, more efficient
#   layer than iptables' rule-chain-traversal model.
#   COST: per L06, adopting Cilium is a genuine CNI-level infrastructure
#   decision -- migrating an existing cluster's networking layer is
#   real, nontrivial operational work, and the team takes on Cilium-
#   specific operational knowledge/troubleshooting skills beyond
#   generic Kubernetes networking knowledge.
#
# ------------------------------------------------------------------------
# APPROACH C: Standard NetworkPolicy (A) for the BASELINE, broad-strokes
# pod-to-pod access control (which is often sufficient for MOST of a
# cluster's actual policy needs), reserving Cilium-specific advanced
# features (B) only for the SPECIFIC services that genuinely need L7-
# aware or more sophisticated policy
# ------------------------------------------------------------------------
#   WHY VALID: recognizes that Cilium (once adopted as the CNI) can
#   still ENFORCE standard NetworkPolicy resources alongside its own
#   advanced CiliumNetworkPolicy CRDs -- adopting Cilium as the CNI
#   doesn't require using its advanced features everywhere; most
#   services can use the simpler, more portable standard API, with
#   Cilium's advanced capabilities reserved for the genuinely complex
#   cases, minimizing unnecessary Cilium-specific configuration
#   surface.
#   COST: still requires the full Cilium CNI migration/adoption cost
#   from B (this isn't a way to get Cilium's advanced features without
#   the underlying CNI decision) -- the "cost" savings here are purely
#   in POLICY CONFIGURATION complexity (using simpler policies where
#   sufficient), not in avoiding the CNI migration itself.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Policy expressiveness | Migration/adoption cost | Portability across CNI plugins |
#   |----------|----------------------------|--------------------------------|---------------------------------------|
#   | A: standard NetworkPolicy, default CNI | Limited | Lowest | Best |
#   | B: Cilium, using advanced features broadly | Richest | Highest | Cilium-specific |
#   | C: Cilium adopted, standard policy as default + advanced where needed | Richest, used judiciously | Same as B (CNI migration) | Cilium-specific, but simpler config where possible |
#   If genuine L7-aware or advanced policy needs exist ANYWHERE in the
#   cluster, adopting Cilium (B or C) is justified, and C's judicious
#   use of simpler standard policies where sufficient is the right
#   practice once Cilium is adopted; A remains sufficient and the
#   right, lower-effort choice if the cluster's actual policy needs
#   never exceed what standard NetworkPolicy already provides.


# ============================================================================
# CASE STUDY 4 — DEPLOYING A NEW EBPF PROGRAM TO PRODUCTION SAFELY
# ============================================================================
#
# SETUP: a new eBPF-based observability/security program has been
# developed and tested in staging; deciding how to roll it out to
# production safely (L08).
#
# ------------------------------------------------------------------------
# APPROACH A: Deploy to all production hosts simultaneously
# ------------------------------------------------------------------------
#   WHY VALID: fastest path to full production coverage/benefit --
#   appropriate if the program has been extensively tested and the team
#   has high confidence, or if the observability/security capability is
#   urgently needed everywhere immediately.
#   COST: per L08's production-eBPF discussion, an eBPF program running
#   in kernel space that has a genuine bug (even though the kernel's
#   verifier prevents many classes of unsafe behavior, it doesn't
#   guarantee the program's LOGIC is correct or performant) can affect
#   EVERY production host simultaneously if something unexpected
#   happens under real production load/traffic patterns that staging
#   didn't fully replicate -- a real, severe blast-radius risk for a
#   kernel-level component specifically.
#
# ------------------------------------------------------------------------
# APPROACH B: A canary rollout -- deploy to a small subset of production
# hosts first, monitor for any adverse effects (CPU overhead, dropped
# packets, unexpected behavior), before expanding (L08, echoing CICD
# Notes' canary pattern applied to kernel-level tooling specifically)
# ------------------------------------------------------------------------
#   WHY VALID: per L08, directly mitigates A's blast-radius risk --
#   if the eBPF program has an unexpected issue under real production
#   conditions, it's caught while only affecting a small fraction of
#   hosts, standard risk-mitigation practice applied specifically to
#   kernel-level tooling where the consequences of a bug can be more
#   severe (potential impact on ALL traffic through an affected host,
#   not just one application's behavior) than a typical application-
#   level canary would need to guard against.
#   COST: per L08, slower to reach full production coverage, and
#   requires genuinely meaningful MONITORING during the canary phase
#   specifically for eBPF-relevant signals (CPU overhead attributable
#   to the eBPF program, verifier-related host issues) -- generic
#   application monitoring may not surface the RIGHT signals to
#   confirm the eBPF program itself is behaving well, requiring some
#   eBPF-specific observability of the observability tool itself.
#
# ------------------------------------------------------------------------
# APPROACH C: B, plus an explicit, tested "detach/unload" procedure
# verified BEFORE the canary begins -- confirming the team can quickly
# and reliably remove the eBPF program from a host if something goes
# wrong, not just detecting a problem via monitoring
# ------------------------------------------------------------------------
#   WHY VALID: per L08, this closes a real gap in B alone -- DETECTING a
#   problem via canary monitoring is necessary but not sufficient;
#   the team also needs a confirmed, FAST, reliable way to actually
#   remove/roll back the problematic eBPF program once detected, and
#   verifying this rollback procedure works BEFORE it's urgently needed
#   (not discovering it's broken or slow during an actual incident) is
#   a genuine, additional safety practice.
#   COST: real, additional upfront preparation work (building and
#   testing the detach/rollback tooling/procedure) before the canary
#   rollout can even begin -- a deliberate, worthwhile investment of
#   time specifically because kernel-level rollback needs to be fast
#   and reliable, given the potential severity of an eBPF program
#   misbehaving in production.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Blast radius if something goes wrong | Rollout speed | Confirmed fast rollback capability |
#   |----------|--------------------------------------------|--------------------|--------------------------------------------|
#   | A: full simultaneous deployment | Entire fleet | Fastest | Not specifically verified |
#   | B: canary rollout with monitoring | Small subset, if caught during canary | Slower | Not specifically verified |
#   | C: B + pre-verified detach/rollback procedure | Small subset, with fast confirmed recovery | Slowest (extra prep) | Yes, explicitly verified |
#   C is the strongest production practice specifically for kernel-
#   level tooling, given the real severity difference between an
#   application-level bug and a kernel-level eBPF program
#   misbehaving -- the extra upfront rollback-verification work is a
#   proportionate response to that elevated risk level.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
