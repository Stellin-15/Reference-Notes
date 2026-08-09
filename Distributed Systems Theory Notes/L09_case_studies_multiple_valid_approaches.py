"""
WHAT: Four realistic distributed-systems design problems, each solved
      with THREE genuinely different, individually defensible approaches
      drawn from L01-L08 -- with an explicit comparison table and
      reasoning for why each answer is valid under different
      constraints.
WHY:  "Paxos or Raft," "vector clocks or last-write-wins," "how strict a
      quorum" are all questions L01-L08 gave you real tools for, not one
      universal answer -- this lesson is about the decision process
      under real consistency and availability constraints.
LEVEL: Capstone -- read after L01-L08.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L08's concepts.
"""

# ============================================================================
# CASE STUDY 1 — CHOOSING A CONSENSUS ALGORITHM FOR A NEW DISTRIBUTED
# CONFIGURATION SERVICE
# ============================================================================
#
# SETUP: building a small, internal distributed configuration store (a
# simplified etcd/ZooKeeper-like service) that needs strong consistency
# for configuration changes across a 5-node cluster.
#
# ------------------------------------------------------------------------
# APPROACH A: Implement Paxos (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, Paxos is the original, formally proven consensus
#   algorithm -- if the team has deep expertise with its specific
#   formalism, or needs to interoperate with existing Paxos-based
#   infrastructure, implementing it directly is a defensible, well-
#   grounded choice.
#   COST: per L03, Paxos is well-documented as notoriously difficult to
#   understand and correctly implement -- its multi-phase protocol
#   (especially multi-Paxos variants needed for practical use) has a
#   real, well-known reputation for subtle implementation bugs even
#   among experienced engineers, a genuine engineering-risk cost.
#
# ------------------------------------------------------------------------
# APPROACH B: Implement Raft (L03)
# ------------------------------------------------------------------------
#   WHY VALID: per L03, Raft was EXPLICITLY designed as a more
#   understandable alternative to Paxos, with clearly separated concerns
#   (leader election, log replication) that map more directly onto an
#   implementable design -- this is precisely WHY Raft displaced Paxos
#   as the default choice for most new distributed systems built after
#   its publication (etcd, Consul, and many others use Raft
#   specifically for this reason).
#   COST: per L03, Raft's clarity comes partly from stronger
#   assumptions/structure (a strong, single leader model) that can be
#   LESS naturally suited to certain exotic deployment topologies or
#   optimization opportunities that more flexible (if harder-to-
#   implement-correctly) Paxos variants can exploit -- a real, if
#   usually not decisive, tradeoff for most practical use cases.
#
# ------------------------------------------------------------------------
# APPROACH C: Don't implement either from scratch -- use an EXISTING,
# battle-tested consensus-based system (etcd, embedded as a library or
# run as a dependency) rather than building custom consensus logic at
# all
# ------------------------------------------------------------------------
#   WHY VALID: per L02-L03's own implicit lesson (these algorithms are
#   subtle and easy to get wrong), reusing an existing, extensively
#   production-tested implementation avoids re-deriving and re-risking
#   correctness bugs that mature tooling has already solved -- for the
#   VAST majority of real engineering teams needing distributed
#   consensus, this is the practically dominant answer.
#   COST: takes on a real, external dependency (etcd's own operational
#   model, versioning, and any limitations of its specific API) rather
#   than having a custom-built system tailored exactly to this
#   configuration service's specific needs -- appropriate UNLESS there's
#   a genuine, specific reason (this domain's own pedagogical goal,
#   research, or a truly novel requirement existing tools don't meet)
#   to build custom consensus logic at all.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Implementation risk | Understandability | Practical recommendation for a REAL production need |
#   |----------|--------------------------|--------------------------|-----------------------------------------------------------|
#   | A: Paxos from scratch | Highest | Lowest | Rarely justified |
#   | B: Raft from scratch | Medium | Highest | Justified for learning/specific novel needs |
#   | C: reuse etcd or similar | Lowest | N/A (black box) | Strongly recommended for most real production needs |
#   For LEARNING distributed consensus deeply (this domain's own
#   purpose, L08's capstone build), implementing B yourself is the
#   right pedagogical choice; for an ACTUAL production configuration
#   service, C is almost always the correct engineering answer --
#   recognizing when "build it yourself, even the version explicitly
#   designed to be more implementable" is still the wrong call for
#   production is itself part of this lesson.


# ============================================================================
# CASE STUDY 2 — HANDLING CONCURRENT, CONFLICTING WRITES TO THE SAME KEY
# ACROSS MULTIPLE REPLICAS
# ============================================================================
#
# SETUP: a distributed key-value store allows writes to be accepted by
# ANY replica (for availability during partitions), meaning the SAME key
# can be concurrently written with different values on different
# replicas before they sync -- deciding how to resolve the conflict.
#
# ------------------------------------------------------------------------
# APPROACH A: Last-Write-Wins (LWW) based on wall-clock timestamps
# ------------------------------------------------------------------------
#   WHY VALID: the simplest possible conflict-resolution rule -- compare
#   timestamps, keep the later one, easy to implement and reason about
#   at a glance.
#   COST: per L05's logical-time discussion, wall-clock timestamps
#   across different machines are NOT reliably synchronized (clock
#   drift is real, and even NTP-synchronized clocks have genuine
#   bounded but nonzero skew) -- LWW can silently pick the WRONG write
#   as "later" purely due to clock skew between replicas, discarding a
#   causally-later write in favor of an earlier one that merely reports
#   a larger timestamp, a real, silent correctness risk.
#
# ------------------------------------------------------------------------
# APPROACH B: Vector clocks (L05) to detect genuine concurrency vs.
# causal ordering, surfacing true conflicts explicitly (e.g. to the
# application or the end user) rather than silently picking a winner
# ------------------------------------------------------------------------
#   WHY VALID: per L05, vector clocks correctly distinguish "these two
#   writes were genuinely concurrent (neither happened-before the
#   other)" from "this write causally followed and superseded that
#   one" -- a principled fix for A's clock-skew risk, since vector
#   clocks track causality directly via logical, not wall-clock, time.
#   COST: per L05, when a GENUINE conflict is detected (two truly
#   concurrent writes to the same key), vector clocks tell you a
#   conflict EXISTS but don't tell you which value is "correct" --
#   someone/something still needs to resolve it (surface it to the
#   user, as many systems do, or apply an application-specific merge
#   rule), and vector clock size grows with the number of replicas,
#   with real, if usually manageable, storage/comparison overhead.
#
# ------------------------------------------------------------------------
# APPROACH C: Application-specific, type-aware conflict resolution
# (CRDTs, System Design Case Studies Notes L07) -- design the data type
# itself (e.g. a counter, a set) so that concurrent updates can be
# merged automatically and deterministically, with NO conflict ever
# needing external resolution
# ------------------------------------------------------------------------
#   WHY VALID: per System Design Case Studies Notes L07's CRDT
#   discussion, this is the strongest answer WHEN the data type admits
#   a natural, mathematically well-defined merge operation (e.g. a
#   grow-only counter can always be merged by taking the max per
#   replica and summing; a set can be merged via union) -- conflicts
#   are resolved automatically and correctly by construction, with no
#   need for B's "surface it to a human/app logic" fallback.
#   COST: per System Design Case Studies Notes L07, NOT every data type
#   has a natural CRDT formulation -- for genuinely arbitrary, complex
#   application data (not a simple counter or set), designing a correct
#   CRDT merge semantic can be difficult or outright impossible without
#   real, careful data-modeling work, and CRDTs often require MORE
#   metadata/complexity per value than a plain scalar would need.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Correctness under clock skew | Requires human/app-level conflict resolution | Fits arbitrary data types |
#   |----------|------------------------------------|-----------------------------------------------------|---------------------------------|
#   | A: LWW by wall clock | Poor (clock-skew risk) | No (silently picks a winner, possibly wrong) | Yes, trivially |
#   | B: vector clocks | Best (causally correct) | Yes, for genuine conflicts | Yes |
#   | C: CRDTs | Best, by construction | No (automatic, correct merge) | Only for CRDT-amenable types |
#   C is the strongest answer specifically when the data type admits a
#   clean CRDT design (a large and growing fraction of real use cases,
#   per System Design Case Studies Notes L07); B is the right fallback
#   for genuinely arbitrary data where no clean automatic merge exists;
#   A should generally be avoided once correctness genuinely matters,
#   despite its simplicity.


# ============================================================================
# CASE STUDY 3 — CHOOSING QUORUM SETTINGS (N, R, W) FOR A REPLICATED
# DATA STORE
# ============================================================================
#
# SETUP: a data store replicates each piece of data across 5 nodes
# (N=5); the team needs to choose read (R) and write (W) quorum sizes
# (L06's N/R/W model).
#
# ------------------------------------------------------------------------
# APPROACH A: W=1, R=1 (write to just one replica, read from just one)
# ------------------------------------------------------------------------
#   WHY VALID: per L06, this maximizes AVAILABILITY and minimizes
#   latency for both reads and writes -- a write or read only needs ONE
#   node to respond, tolerating up to N-1 node failures for either
#   operation to still succeed.
#   COST: per L06, with R+W <= N (1+1=2 <= 5), there's NO guarantee a
#   read quorum and a write quorum overlap -- a read can genuinely
#   return STALE data that doesn't reflect a recent write, since the
#   read might hit a replica that hasn't received that write yet, the
#   weakest consistency guarantee of the N/R/W model.
#
# ------------------------------------------------------------------------
# APPROACH B: W=3, R=3 (a strict majority quorum for both) (L06)
# ------------------------------------------------------------------------
#   WHY VALID: per L06, with R+W > N (3+3=6 > 5), every read quorum is
#   GUARANTEED to overlap with every write quorum on at least one node
#   -- this directly guarantees a read always sees the most recent
#   completed write, strong consistency, while still tolerating some
#   node failures (up to 2 nodes down, since 3 of 5 can still respond).
#   COST: per L06, both reads AND writes now require waiting for 3
#   nodes to respond (not just 1) -- real, added latency for EVERY
#   operation compared to A, and if the number of unavailable nodes
#   exceeds N-3 (more than 2 nodes down), NEITHER reads nor writes can
#   complete at all, a real availability cost under multi-node failure.
#
# ------------------------------------------------------------------------
# APPROACH C: Asymmetric quorums tuned to the actual workload -- e.g.
# W=4, R=2 for a READ-HEAVY workload (fast reads, slower but still
# quorum-safe writes), since R+W=6 > 5 still guarantees overlap
# regardless of exactly how the 6 is split between R and W
# ------------------------------------------------------------------------
#   WHY VALID: per L06's TUNABLE-per-operation framing, the N/R/W model
#   doesn't require R and W to be equal -- as long as R+W > N holds, the
#   overlap guarantee (and hence strong consistency) is preserved,
#   letting the team bias latency toward whichever operation (reads or
#   writes) is more frequent/latency-sensitive for THIS specific
#   workload, rather than paying B's uniform cost on both.
#   COST: requires actually knowing/measuring the real workload's read/
#   write ratio and latency sensitivity to tune correctly -- a
#   genuinely workload-specific decision, not a safe universal default,
#   and choosing the wrong skew (e.g. optimizing reads when writes are
#   actually more latency-critical) gives up B's balanced guarantee for
#   no real benefit.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Consistency guarantee | Latency profile | Fault tolerance |
#   |----------|----------------------------|----------------------|----------------------|
#   | A: W=1, R=1 | Weak (stale reads possible) | Best (both fast) | Best (tolerates N-1 failures) |
#   | B: W=3, R=3 | Strong | Uniformly moderate | Tolerates up to 2 failures |
#   | C: asymmetric, e.g. W=4/R=2 | Strong (if R+W>N) | Biased toward the favored operation | Tolerates fewer failures on the heavier side |
#   B is the right, safe default when read/write frequency is roughly
#   balanced and workload characteristics aren't well known yet; C is
#   the right optimization once the actual workload's read/write skew
#   is measured and the team wants to bias latency accordingly, without
#   giving up the R+W>N consistency guarantee.


# ============================================================================
# CASE STUDY 4 — IMPLEMENTING A DISTRIBUTED LOCK FOR A CRITICAL SECTION
# ACROSS MULTIPLE SERVICE INSTANCES
# ============================================================================
#
# SETUP: multiple instances of a service need to ensure only ONE
# instance processes a given scheduled job at a time (avoiding duplicate
# processing) -- deciding on a distributed locking mechanism (L07).
#
# ------------------------------------------------------------------------
# APPROACH A: A simple lease-based lock in Redis (SET key value NX EX
# ttl) (L07, Redis & Caching Notes L05)
# ------------------------------------------------------------------------
#   WHY VALID: per L07/Redis & Caching Notes L05, this is a fast,
#   simple, widely-used pattern -- one atomic operation acquires a
#   time-bounded lock, and the TTL ensures the lock is eventually
#   released even if the holder crashes without explicitly releasing it.
#   COST: per L07's GC-pause problem discussion, a lease-based lock has
#   a genuine, well-documented failure mode -- if the lock holder
#   experiences an unexpectedly long pause (a GC pause, a slow disk I/O,
#   a network partition) LONGER than the lease TTL, the lock can expire
#   and be acquired by ANOTHER instance WHILE the original holder is
#   still (unknowingly) also acting as if it holds the lock -- a real,
#   subtle correctness risk for a "must never double-process" guarantee.
#
# ------------------------------------------------------------------------
# APPROACH B: A, plus FENCING TOKENS (L07) -- each lock acquisition
# returns a monotonically increasing token; any protected resource/
# operation validates that the token presented is the LATEST one issued,
# rejecting stale-token operations even from a lock holder that doesn't
# realize its lease has expired
# ------------------------------------------------------------------------
#   WHY VALID: per L07, this directly closes A's exact failure mode --
#   even if a paused instance wakes up believing it still holds the
#   lock and tries to act, the fencing-token check at the PROTECTED
#   RESOURCE rejects its now-stale token, preventing the double-
#   processing A was vulnerable to, without needing to prevent the lock
#   expiration/reacquisition from happening at all.
#   COST: per L07, fencing tokens only provide their safety guarantee if
#   the PROTECTED RESOURCE itself actually validates the token -- this
#   requires the downstream system/operation being protected to support
#   token-based validation, a real integration requirement that doesn't
#   help if the protected action is, e.g., a call to a third-party API
#   with no concept of accepting/validating a fencing token at all.
#
# ------------------------------------------------------------------------
# APPROACH C: Use a consensus-based lock service (e.g. built on Raft/
# etcd's distributed lock primitive, connecting back to Case Study 1)
# rather than a simple lease-based Redis lock
# ------------------------------------------------------------------------
#   WHY VALID: per L03/L07 combined, a consensus-based lock service
#   provides genuinely stronger guarantees than a simple Redis lease --
#   built on a real consensus protocol, it more robustly handles the
#   coordinator/leader-failure scenarios that can create subtle bugs in
#   a simpler single-Redis-instance lease approach, especially if Redis
#   itself isn't run in a fully consensus-safe replicated configuration.
#   COST: significantly more infrastructure investment and operational
#   complexity than A/B's Redis-based approach -- appropriate
#   specifically when the stakes of a locking failure are severe enough
#   (financial transactions, safety-critical operations) to justify it,
#   real overkill for a routine "don't double-run a scheduled job" need
#   that B's fencing-token fix already adequately addresses for most
#   practical purposes.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Protects against the GC-pause/expired-lease race | Infrastructure investment | Requires downstream token validation |
#   |----------|-----------------------------------------------------------|---------------------------------|--------------------------------------------|
#   | A: plain Redis lease lock | No (real, known vulnerability) | Lowest | N/A |
#   | B: A + fencing tokens | Yes, if the protected resource validates tokens | Low | Yes |
#   | C: consensus-based lock service | Yes, more robustly | Highest | No (stronger guarantee is structural) |
#   B is the standard, well-established, low-cost fix for most real
#   "avoid duplicate job processing" needs, PROVIDED the protected
#   resource can validate a token; C is justified specifically for
#   stakes severe enough to warrant its higher infrastructure cost, or
#   when B's token-validation requirement genuinely can't be met by the
#   protected resource.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
