# ============================================================
# L06: Quorum Systems — Tuning Consistency vs Availability Per Operation
# ============================================================
# WHAT: The generalized quorum math (N/R/W) that lets a distributed
#       database tune the consistency/availability tradeoff PER
#       OPERATION, rather than accepting one fixed tradeoff for the
#       entire system — the mechanism underneath Cassandra/DynamoDB-style databases.
# WHY: L02-L03's consensus algorithms used a FIXED majority quorum. Real
#      distributed databases generalize this into a TUNABLE parameter
#      exposed directly to application developers — this lesson covers
#      that generalization and its genuine tradeoffs.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
THE N/R/W MODEL: N is the total number of REPLICAS a piece of data is
stored on; W is the number of replicas that must ACKNOWLEDGE a WRITE
before it's considered successful; R is the number of replicas that must
respond to a READ before returning a result to the client. The
FUNDAMENTAL GUARANTEE: if W + R > N, every read is guaranteed to
overlap with at least one replica that has the MOST RECENT write — this
is the SAME majority-overlap principle underlying Paxos (L02) and Raft
(L03), generalized into a tunable parameter rather than a fixed majority.

TUNING THE TRADEOFF: a system can choose W=N, R=1 (writes must reach
EVERY replica, but reads only need ONE — fast reads, slow/less-available
writes, since a write fails if even one replica is unreachable); or W=1,
R=N (writes are fast and highly available, but reads must check EVERY
replica to guarantee seeing the latest write — slow/less-available
reads); or the common balanced choice, W=R=majority (e.g. N=3, W=2,
R=2), which balances read and write latency/availability roughly evenly
while still guaranteeing the W+R>N overlap property.

WHEN W + R <= N: the system EXPLICITLY sacrifices the strong-consistency
guarantee in exchange for LOWER LATENCY and HIGHER AVAILABILITY on both
reads and writes — e.g. W=1, R=1 with N=3 means writes/reads only need
ONE replica to respond, tolerating up to 2 replica failures for either
operation independently, at the cost that a read might return STALE data
(if it happens to hit a replica that hasn't yet received the most recent write).

THIS IS A PER-OPERATION, PER-QUERY DECISION in systems like Cassandra
and DynamoDB — a single application can use STRONG consistency (W+R>N)
for operations where correctness is critical (e.g. checking account
balance before a withdrawal) while using WEAKER, faster settings
(W+R<=N) for less critical reads (e.g. displaying a "last seen" timestamp
that being slightly stale is a fully acceptable tradeoff for) — this
PER-OPERATION tunability is a genuinely more flexible model than a
single system-wide consistency setting, letting different operations
within the SAME application make different, deliberate tradeoffs.

SLOPPY QUORUMS AND HINTED HANDOFF are a practical refinement: during a
network partition or node failure, a STRICT quorum requirement (always
requiring responses from the SAME specific N nodes) can make the system
UNAVAILABLE for writes even when PLENTY of other healthy nodes exist —
a sloppy quorum instead allows temporarily writing to DIFFERENT,
available nodes (not the "home" replicas for that data) during such an
outage, with HINTED HANDOFF later transferring that data to the correct
home replicas once they recover — trading TEMPORARY inconsistency
(the correct replicas are briefly unaware of the write) for continued write availability during partial outages.

PRODUCTION USE CASE:
A social media platform's Cassandra-backed like-counter uses W=1, R=1
(fast, highly available, occasionally-stale reads acceptable — nobody
notices if a like count is briefly off by a few), while the SAME
platform's Cassandra-backed billing/payment-ledger table uses W=majority,
R=majority (slower, but guarantees strong consistency for financial
data where staleness could cause a real, costly error) — both hosted on
the identical underlying database technology, tuned completely
differently PER TABLE based on each one's actual consistency requirements.

COMMON MISTAKES:
- Using the SAME quorum settings for every table/operation in a system
  regardless of its actual consistency requirements — a system's most
  consistency-sensitive operation (financial data) and its most
  latency-sensitive operation (a view counter) rarely have the same
  optimal tradeoff point, and treating them identically wastes the
  flexibility this model specifically provides.
- Choosing W + R <= N without understanding that this EXPLICITLY
  sacrifices strong consistency, then being surprised when stale reads
  occur in production — this is not a bug in the database; it's the
  DIRECT, expected consequence of the chosen quorum configuration.
- Disabling sloppy quorums/hinted handoff without understanding the
  availability cost — a strict quorum requirement can make a system
  UNAVAILABLE for writes to a specific partition during a transient
  node failure, even when the overall cluster has ample healthy capacity elsewhere.
"""


# ------------------------------------------------------------------
# 1. The N/R/W overlap guarantee, verified directly
# ------------------------------------------------------------------
def quorum_guarantees_consistency(n: int, r: int, w: int) -> bool:
    return (r + w) > n


def quorum_tradeoff_demo():
    configurations = [
        {"name": "Fast reads, slow/less-available writes", "n": 3, "r": 1, "w": 3},
        {"name": "Fast writes, slow/less-available reads", "n": 3, "r": 3, "w": 1},
        {"name": "Balanced (majority both ways)", "n": 3, "r": 2, "w": 2},
        {"name": "Fast BOTH, no strong consistency guarantee", "n": 3, "r": 1, "w": 1},
    ]
    for config in configurations:
        strong = quorum_guarantees_consistency(config["n"], config["r"], config["w"])
        print(f"  {config['name']} (N={config['n']}, R={config['r']}, W={config['w']}): "
              f"strong consistency guaranteed = {strong}")


# ------------------------------------------------------------------
# 2. Simulating stale reads when W + R <= N
# ------------------------------------------------------------------
class QuorumReplicatedStore:
    def __init__(self, num_replicas: int):
        self.replicas = ["" for _ in range(num_replicas)]

    def write(self, value: str, w: int):
        # Only write to the FIRST w replicas — simulating a write quorum
        # that doesn't reach every replica
        for i in range(w):
            self.replicas[i] = value

    def read(self, r: int) -> list[str]:
        # Only read from the FIRST r replicas
        return self.replicas[:r]


def stale_read_demo():
    print("\nDemonstrating a stale read when W + R <= N:\n")
    store = QuorumReplicatedStore(num_replicas=3)
    store.write("value_v1", w=3)   # initial write, reaches all 3
    print(f"  After initial write to all 3 replicas: {store.replicas}")

    store.write("value_v2", w=1)   # a SECOND write, but W=1 — only reaches replica[0]
    print(f"  After second write with W=1: {store.replicas}")

    read_result = store.read(r=1)   # R=1, happens to read replica[0] (has the new value, got lucky)
    print(f"  Read with R=1 (reading replica[0]): {read_result} -- happened to be fresh")

    # But reading a DIFFERENT replica (still valid under R=1) would be stale:
    stale_result = [store.replicas[1]]
    print(f"  Read with R=1 (reading replica[1] instead): {stale_result} -- STALE!")
    print("\n  -> With W=1, R=1, N=3 (W+R=2 <= N=3), a read is NOT guaranteed")
    print("     to see the latest write — this is the EXPECTED, deliberate")
    print("     consequence of choosing this configuration, not a bug.")


if __name__ == "__main__":
    quorum_tradeoff_demo()
    stale_read_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A Cassandra-backed e-commerce platform configures its "product view
count" table with LOCAL_ONE consistency (effectively W=1, R=1) for
maximum write/read throughput, since an occasionally-stale view count is
commercially irrelevant — while its "inventory stock level" table uses
QUORUM consistency (W=majority, R=majority) specifically because
overselling inventory due to a stale read would create a genuine,
costly customer-facing problem — the SAME underlying database engine,
configured with deliberately different N/R/W tradeoffs per table based
on each one's actual business consistency requirements.
"""
