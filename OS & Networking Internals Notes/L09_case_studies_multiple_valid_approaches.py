"""
WHAT: Four realistic OS/networking-internals diagnostic problems, each
      solved with THREE genuinely different, individually defensible
      approaches drawn from L01-L08 -- with an explicit comparison table
      and reasoning for why each answer is valid under different
      constraints.
WHY:  "Is this a scheduling problem or a memory problem," "TCP tuning or
      application-layer fix," "which diagnostic tool" are all questions
      L01-L08 gave you real tools for, not one universal answer -- this
      lesson is about the decision process when a production symptom
      could have multiple genuinely different root causes at the OS/
      network layer.
LEVEL: Capstone -- read after L01-L08.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L08's concepts.
"""

# ============================================================================
# CASE STUDY 1 — DIAGNOSING A SERVICE WITH INTERMITTENT HIGH TAIL
# LATENCY DESPITE LOW AVERAGE CPU UTILIZATION
# ============================================================================
#
# SETUP: a service shows low AVERAGE CPU usage (well under capacity) but
# occasional, severe p99 latency spikes -- the team needs to determine
# the actual mechanism, not just observe the symptom.
#
# ------------------------------------------------------------------------
# APPROACH A: Investigate SCHEDULING behavior (L01) -- check for run-
# queue latency (time a process spends READY to run but not actually
# scheduled onto a CPU)
# ------------------------------------------------------------------------
#   WHY VALID: per L01, LOW AVERAGE CPU utilization does NOT rule out
#   scheduling-induced latency -- if many processes/threads briefly
#   contend for CPU time simultaneously (even if the AVERAGE utilization
#   across a longer window is low), a specific request's thread can
#   still experience real run-queue wait time during those brief
#   contention windows, exactly the kind of tail-latency-causing,
#   average-masking phenomenon L01's scheduling discussion covers.
#   COST: per L01, confirming this requires tools that specifically
#   measure SCHEDULING latency (not just CPU utilization) -- if the
#   actual cause is unrelated to scheduling, this investigation,
#   while a reasonable first hypothesis, won't find anything and time
#   is spent ruling it out rather than finding the true cause.
#
# ------------------------------------------------------------------------
# APPROACH B: Investigate VIRTUAL MEMORY/PAGING behavior (L02) -- check
# for page faults, particularly MAJOR page faults requiring disk I/O,
# or swapping
# ------------------------------------------------------------------------
#   WHY VALID: per L02, a major page fault (data that must be read from
#   disk, not just remapped in memory) can cause a genuinely severe,
#   multi-millisecond-plus latency spike for the specific request that
#   triggers it, while barely registering in AVERAGE CPU metrics (the
#   process is mostly WAITING on I/O during a page fault, not consuming
#   CPU) -- a strong, distinct candidate hypothesis for exactly this
#   symptom shape (low avg CPU, occasional severe tail latency).
#   COST: per L02, this requires checking page-fault-specific metrics
#   (major vs. minor fault rates, swap activity) which many standard
#   monitoring dashboards don't surface by default -- if the actual
#   cause is scheduling (A) or something else entirely, this
#   investigation similarly finds nothing.
#
# ------------------------------------------------------------------------
# APPROACH C: Investigate ALL plausible mechanisms systematically using
# eBPF-based tooling (L08's capstone connection) -- rather than guessing
# which single layer (scheduling, memory, I/O) is responsible, use
# tracing tools that can correlate a SPECIFIC slow request's execution
# across scheduling, memory, and I/O events simultaneously
# ------------------------------------------------------------------------
#   WHY VALID: per L08, this avoids the "guess one hypothesis,
#   investigate, repeat if wrong" cost of A/B by directly observing
#   what ACTUALLY happened during a specific slow request's execution,
#   across every relevant OS-level subsystem at once -- eBPF-based
#   tracing (L08) is specifically well-suited to correlating exactly
#   this kind of cross-subsystem, intermittent, hard-to-reproduce issue
#   without needing to guess the right layer upfront.
#   COST: per L08, eBPF-based tracing tooling has a real setup/learning-
#   curve cost, and capturing the SPECIFIC intermittent slow event
#   requires either the tooling running continuously (real, if usually
#   modest, overhead) or getting fortunate enough to have it active
#   during a spike -- more powerful, but not free to set up and
#   operate relative to checking a specific, narrower metric.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Diagnostic scope | Setup/tooling cost | Risk of investigating the wrong layer |
#   |----------|----------------------|---------------------------|------------------------------------------------|
#   | A: scheduling investigation | Narrow (one subsystem) | Low | Real |
#   | B: paging/memory investigation | Narrow (one subsystem) | Low | Real |
#   | C: eBPF cross-subsystem tracing | Broad (correlates everything) | Higher | Low (observes actual causation directly) |
#   For a first, cheap pass, checking A and B's specific metrics in
#   parallel is reasonable given how common both are as causes; C is
#   the strongest answer once A/B's targeted checks don't turn up an
#   obvious answer, or when the issue is severe/recurring enough to
#   justify the eBPF tooling investment upfront.


# ============================================================================
# CASE STUDY 2 — DIAGNOSING SLOW APPLICATION STARTUP TIME
# ============================================================================
#
# SETUP: an application's cold-start time has grown noticeably slower
# over several releases; the team needs to determine the actual cause
# rather than guessing.
#
# ------------------------------------------------------------------------
# APPROACH A: Investigate FILE SYSTEM behavior (L03) -- check whether
# startup involves reading many small files, and whether that read
# pattern is genuinely efficient
# ------------------------------------------------------------------------
#   WHY VALID: per L03, applications that read MANY small files at
#   startup (e.g. loading many small config/dependency files
#   individually) can suffer real, measurable overhead from per-file
#   syscall/metadata-lookup cost, especially on certain file systems or
#   storage backends -- a legitimate, common cause of slow startup as
#   an application's dependency/config surface grows over releases.
#   COST: per L03, this specific investigation only helps if the actual
#   bottleneck IS file I/O pattern -- if startup slowness is actually
#   dominated by, e.g., CPU-bound initialization logic or network calls
#   during startup, this investigation finds nothing.
#
# ------------------------------------------------------------------------
# APPROACH B: Investigate SYSCALL overhead directly (L06) -- trace the
# actual syscalls made during startup (via strace or similar) to see
# where time is genuinely being spent at the kernel-userspace boundary
# ------------------------------------------------------------------------
#   WHY VALID: per L06, this is a more DIRECT, lower-level diagnostic
#   than A -- rather than hypothesizing about file access PATTERNS
#   specifically, it shows exactly which syscalls (file-related,
#   network-related, memory-related, or otherwise) are consuming the
#   most time during the actual startup sequence, a broader, more
#   agnostic-to-hypothesis diagnostic.
#   COST: per L06, syscall tracing itself adds real overhead to the
#   traced process (strace, in particular, can slow down execution
#   substantially while tracing is active) -- the MEASURED startup time
#   while tracing may not exactly match real-world untraced startup
#   time, a real, if usually well-understood and accounted-for, caveat
#   when interpreting the results.
#
# ------------------------------------------------------------------------
# APPROACH C: Bisect across releases -- use the version-control history
# to identify WHICH SPECIFIC release(s) introduced the regression,
# before deeply investigating the OS-level mechanism at all
# ------------------------------------------------------------------------
#   WHY VALID: per general engineering practice (complementing L03/L06's
#   OS-level tools), if startup time degraded gradually "over several
#   releases" (as stated), bisecting to find WHICH specific change(s)
#   correlate with the slowdown can directly point at the RESPONSIBLE
#   CODE CHANGE (e.g. "release N added a new dependency that reads 200
#   extra config files") far faster than deep OS-level tracing without
#   that context -- often the fastest path to a root cause when a
#   regression (not a fixed, unchanging problem) is the actual situation.
#   COST: bisecting requires the ability to actually build/run
#   historical versions and measure startup time consistently across
#   them -- real, if usually straightforward, tooling/process
#   investment, and once you've identified WHICH release/change caused
#   it, you often still need A or B's OS-level tools to understand
#   EXACTLY why that change caused slower startup, so this doesn't
#   replace A/B, it focuses where to apply them.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Points to WHY startup is slow | Points to WHICH change caused it | Speed to root cause for a gradual regression |
#   |----------|------------------------------------|------------------------------------------|-----------------------------------------------------|
#   | A: file system investigation | Yes, if that's the cause | No | Slower, without narrowing scope first |
#   | B: syscall tracing | Yes, broadly | No | Slower, without narrowing scope first |
#   | C: bisect across releases | No, by itself | Yes | Fastest, for a genuine gradual regression |
#   Given this case study's explicit framing ("grown slower over several
#   releases," i.e. a regression, not a fixed constant problem), C is
#   the strongest FIRST step to narrow scope, with A or B then applied
#   specifically to the identified change to understand the mechanism.


# ============================================================================
# CASE STUDY 3 — DIAGNOSING WHY A SERVICE'S NETWORK THROUGHPUT IS LOWER
# THAN EXPECTED GIVEN AVAILABLE BANDWIDTH
# ============================================================================
#
# SETUP: two services communicate over a link with plenty of raw
# available bandwidth, but observed throughput between them is
# noticeably below that capacity.
#
# ------------------------------------------------------------------------
# APPROACH A: Check TCP window sizing/scaling (L04)
# ------------------------------------------------------------------------
#   WHY VALID: per L04's TCP deep-dive, throughput on a high-bandwidth,
#   high-latency ("long fat network") link is fundamentally bounded by
#   the TCP window size relative to the round-trip time (the bandwidth-
#   delay product) -- if window scaling isn't properly negotiated/
#   configured, throughput can be capped well below the link's actual
#   raw bandwidth, REGARDLESS of how much bandwidth is technically
#   available, a well-known, specific TCP-layer cause for exactly this
#   symptom.
#   COST: per L04, this is a SPECIFIC hypothesis about a SPECIFIC
#   mechanism -- if the actual bottleneck is elsewhere (application-
#   layer serialization overhead, a different network path issue),
#   checking window scaling configuration won't find it.
#
# ------------------------------------------------------------------------
# APPROACH B: Check for PACKET LOSS/retransmission on the path (L04) --
# even a small loss rate can severely degrade TCP throughput due to
# congestion-control backoff behavior
# ------------------------------------------------------------------------
#   WHY VALID: per L04, TCP's congestion control REACTS to perceived
#   packet loss by aggressively reducing its send rate -- even a
#   modest, easy-to-overlook loss rate on the path (a flaky link, a
#   congested intermediate hop) can cause TCP to throttle itself well
#   below the path's actual available bandwidth, a genuinely different
#   mechanism than A's window-sizing issue, producing a similar
#   "throughput below expected capacity" symptom.
#   COST: per L04, confirming this requires actually measuring loss/
#   retransmission rates on the specific path (not just assuming based
#   on "available bandwidth" figures, which don't directly reveal loss)
#   -- if the actual cause is A's window-sizing issue instead, checking
#   for loss won't find anything.
#
# ------------------------------------------------------------------------
# APPROACH C: Systematically test EACH LAYER independently -- first a
# raw network benchmark tool (e.g. iperf) between the same two hosts
# (isolating pure network-path throughput, no application logic
# involved) to determine if the bottleneck is even IN the network layer
# at all, before investigating A or B specifically
# ------------------------------------------------------------------------
#   WHY VALID: per L04's own framing, this FIRST determines whether the
#   problem is genuinely a network/TCP-layer issue (A or B's territory)
#   or an APPLICATION-layer issue (e.g. slow serialization,
#   inefficient batching, a rate limit in the application code itself)
#   BEFORE investing time in TCP-specific diagnostics that would be
#   wasted effort if the real bottleneck is actually in the application
#   layer, not the network layer at all.
#   COST: requires the ability to run an isolated network benchmark
#   between the same two hosts (real, if usually straightforward,
#   access/tooling requirement) and adds a diagnostic step before
#   getting to the SPECIFIC mechanism (A or B) if the bottleneck does
#   turn out to be network-layer -- a deliberate "scope first, then
#   drill in" sequencing cost.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Confirms network vs application layer first | Points to a specific TCP mechanism | Risk of investigating the wrong layer entirely |
#   |----------|-----------------------------------------------------|-------------------------------------------|--------------------------------------------------------|
#   | A: window scaling check | No (assumes network-layer) | Yes, if this is the cause | Real, if the issue is actually application-layer |
#   | B: packet loss check | No (assumes network-layer) | Yes, if this is the cause | Real, if the issue is actually application-layer |
#   | C: isolated network benchmark first | Yes | No, by itself (narrows scope only) | Low |
#   C is the strongest first step -- it directly answers "is this even
#   a network problem" before committing to A or B's more specific,
#   network-layer-assuming investigations, avoiding wasted diagnostic
#   effort if the real bottleneck turns out to be in the application
#   layer instead.


# ============================================================================
# CASE STUDY 4 — DIAGNOSING WHY DNS RESOLUTION IS INTERMITTENTLY SLOW
# FOR A SERVICE
# ============================================================================
#
# SETUP: a service occasionally experiences slow (multi-second) DNS
# resolution for outbound calls to a dependency, despite the dependency's
# DNS records having a reasonable, short TTL.
#
# ------------------------------------------------------------------------
# APPROACH A: Check the LOCAL DNS resolver/cache configuration (L05) --
# is the service's local resolver correctly caching per the TTL, or is
# every request making a fresh, full resolution?
# ------------------------------------------------------------------------
#   WHY VALID: per L05, if the local resolver ISN'T caching correctly
#   (a misconfiguration, or an application bypassing OS-level DNS
#   caching entirely with its own broken caching logic), EVERY request
#   pays full resolution latency -- checking this first is cheap and
#   addresses a common, easy-to-introduce misconfiguration.
#   COST: per L05, if caching IS working correctly and the issue is
#   INTERMITTENT (as stated) rather than affecting every single
#   request, this investigation alone doesn't explain WHY it's
#   intermittent specifically -- correct caching behavior with an
#   occasional slow outlier points toward a different mechanism.
#
# ------------------------------------------------------------------------
# APPROACH B: Investigate the full DNS resolution CHAIN (L05) -- trace
# an actual slow resolution through recursive resolvers, checking for a
# specific slow/unreliable upstream nameserver in the chain
# ------------------------------------------------------------------------
#   WHY VALID: per L05's DNS-resolution-internals discussion, a
#   resolution chain involves multiple hops (local resolver ->
#   recursive resolver -> potentially multiple authoritative
#   nameservers) -- an INTERMITTENT slowdown is consistent with one
#   specific nameserver in that chain being occasionally slow/
#   unreliable (not a caching misconfiguration, which would typically
#   cause consistent, not intermittent, behavior), a genuinely
#   different and more specific hypothesis than A.
#   COST: per L05, tracing a full resolution chain (e.g. via `dig
#   +trace`) requires actually catching the issue WHILE it's happening
#   (or reasoning from historical data) -- for a genuinely intermittent
#   issue, reproducing it on demand for live tracing can be difficult,
#   similar to Case Study 1's intermittent-issue challenge.
#
# ------------------------------------------------------------------------
# APPROACH C: Check whether the slowness correlates with TTL EXPIRY
# TIMING specifically -- i.e., does the slow resolution happen roughly
# once per TTL period (consistent with "fresh resolution needed" being
# the trigger) or does it appear genuinely randomly (consistent with an
# unreliable upstream nameserver, B's hypothesis)?
# ------------------------------------------------------------------------
#   WHY VALID: this is a targeted DIAGNOSTIC STEP (not a fix) that
#   directly distinguishes between A/B's competing hypotheses using data
#   the team likely already has (request timing logs, DNS TTL values)
#   without needing to catch the issue live -- correlating slow-
#   resolution TIMESTAMPS against the TTL period is a relatively cheap
#   way to determine which deeper investigation (A or B) is actually
#   worth pursuing before committing to either.
#   COST: this diagnostic step alone doesn't identify the root cause,
#   only which FAMILY of causes (caching-related vs. upstream-
#   nameserver-related) is more likely -- still requires following up
#   with A or B's deeper investigation once the correlation analysis
#   narrows the hypothesis space.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Explains a TRULY intermittent (not per-request) pattern | Requires catching the issue live | Directly identifies root cause |
#   |----------|------------------------------------------------------------------|----------------------------------------|--------------------------------------|
#   | A: local caching config check | Poorly (would predict consistent, not intermittent, behavior) | No | Only if this is the actual cause |
#   | B: full resolution chain trace | Well | Yes, ideally | Yes, if caught |
#   | C: correlate timing against TTL period | N/A (a diagnostic filter, not a direct answer) | No (uses existing logs) | No, narrows the hypothesis space |
#   C is the strongest, cheapest FIRST step to decide whether to
#   pursue A or B further -- given the intermittent (not universal)
#   nature of the symptom, B's hypothesis is more consistent with the
#   stated symptom shape than A's, and C's correlation check can
#   confirm this cheaply before investing in B's harder-to-execute live
#   tracing.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
