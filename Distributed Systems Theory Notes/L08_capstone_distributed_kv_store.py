# ============================================================
# L08: Capstone — Building a Minimal Distributed Key-Value Store
# ============================================================
# WHAT: A capstone lesson wiring L01-L07's consensus, quorum, vector
#       clock, and locking concepts into ONE working, illustrative
#       distributed key-value store — proving out how these pieces
#       actually combine into a real system.
# WHY: L01-L07 each covered ONE piece in isolation. A real distributed
#      database (Cassandra, DynamoDB, etcd) combines ALL of these
#      concepts simultaneously — this capstone shows, concretely, how
#      they fit together.
# LEVEL: Capstone
# ============================================================

"""
CONCEPT OVERVIEW:
This capstone combines, in ONE illustrative system:

  1. REPLICATION across N nodes (L06's quorum model) — each key is
     stored on multiple replicas, not just one, for fault tolerance.
  2. TUNABLE READ/WRITE QUORUMS (L06) — the store exposes W and R as
     configurable parameters, letting a caller choose their own
     consistency/availability tradeoff per operation.
  3. VECTOR CLOCKS (L05) for conflict detection — concurrent,
     conflicting writes to the same key are DETECTED rather than one
     silently overwriting the other.
  4. A DISTRIBUTED LOCK (L07) for operations that need strict mutual
     exclusion across the whole cluster (e.g. a cluster-wide
     administrative operation), layered on top of the quorum-based storage.

This is NOT how you'd build a production system (real systems like
Cassandra handle partitioning/hashing across MANY more nodes, network
failure recovery, anti-entropy repair, and far more edge cases than this
illustrative version) — it's built to make the CONCEPTS from L01-L07
concrete by seeing them work together in actual, runnable code, the same
capstone philosophy used throughout this repo's other domains.

THE FULL PICTURE THIS DEMONSTRATES: consensus (L02-L03) underlies the
distributed lock (L07) used for administrative coordination; quorum
math (L06) governs every individual read/write's consistency
guarantee; vector clocks (L05) detect when quorum-based replication
allows genuinely concurrent, conflicting writes to occur; and L01's
foundational fallacies (network unreliability, partial failure) are
the reason EVERY one of these mechanisms exists in the first place —
none of them would be necessary if the network were actually reliable
and nodes never failed partially.

PRODUCTION USE CASE:
This is, in miniature, the shape of systems like Cassandra, Riak, and
DynamoDB — quorum-based replicated storage with vector-clock-based
conflict detection for eventual consistency, PLUS a separate,
consensus-backed coordination layer (like ZooKeeper alongside
Cassandra, or etcd alongside many modern systems) for the smaller set
of operations that genuinely need strict, cluster-wide coordination
rather than the eventually-consistent quorum model.

COMMON MISTAKES:
- Assuming ONE consistency mechanism (either pure quorum-based
  eventual consistency, OR pure consensus-based strong consistency)
  should be used for EVERY operation in a real system — production
  systems, as this capstone illustrates, typically use BOTH: quorum-
  based replication for routine data operations (fast, available) and
  consensus-based coordination for the smaller set of operations
  genuinely needing strict ordering/mutual exclusion.
- Treating vector clocks as solving the SAME problem as quorum
  tuning — they're COMPLEMENTARY: quorums determine HOW MANY replicas
  must respond; vector clocks determine WHETHER two responses represent
  a genuine conflict needing resolution. Confusing the two leads to
  incomplete distributed-storage designs.
- Building a system like this WITHOUT first understanding L01's
  foundational fallacies — every mechanism in this capstone exists
  SPECIFICALLY as a response to network unreliability and partial
  failure; skipping that foundation makes the mechanisms in L02-L07 look
  like arbitrary complexity rather than necessary responses to real constraints.
"""

import time


# ------------------------------------------------------------------
# A minimal distributed KV store combining L05-L07's concepts
# ------------------------------------------------------------------
class Replica:
    def __init__(self, name: str):
        self.name = name
        self.data: dict[str, dict] = {}   # key -> {"value": ..., "vector_clock": [...]}
        self.alive = True


class DistributedKVStore:
    def __init__(self, replica_names: list[str]):
        self.replicas = {name: Replica(name) for name in replica_names}
        self.replica_names = replica_names
        self.admin_lock_holder = None

    def write(self, key: str, value: str, client_vector_clock: list[int], w: int) -> str:
        alive_replicas = [r for r in self.replicas.values() if r.alive]
        if len(alive_replicas) < w:
            return f"WRITE FAILED — insufficient alive replicas ({len(alive_replicas)} < W={w})"

        acked = 0
        for replica in alive_replicas:
            existing = replica.data.get(key)
            if existing:
                comparison = self._compare_clocks(existing["vector_clock"], client_vector_clock)
                if comparison == "CONCURRENT":
                    print(f"    [{replica.name}] CONFLICT DETECTED for key '{key}' — "
                          f"storing BOTH versions for later resolution (L05's vector clock check)")
                    replica.data[key] = {"value": value, "vector_clock": client_vector_clock,
                                          "conflict_with": existing["value"]}
                else:
                    replica.data[key] = {"value": value, "vector_clock": client_vector_clock}
            else:
                replica.data[key] = {"value": value, "vector_clock": client_vector_clock}
            acked += 1
            if acked >= w:
                break
        return f"WRITE ACKED by {acked} replicas (W={w} required)"

    def read(self, key: str, r: int) -> list[dict]:
        alive_replicas = [rep for rep in self.replicas.values() if rep.alive]
        if len(alive_replicas) < r:
            return [{"error": f"insufficient alive replicas ({len(alive_replicas)} < R={r})"}]
        results = []
        for replica in alive_replicas[:r]:
            if key in replica.data:
                results.append({"replica": replica.name, **replica.data[key]})
        return results

    def _compare_clocks(self, v1: list[int], v2: list[int]) -> str:
        if all(a <= b for a, b in zip(v1, v2)) and any(a < b for a, b in zip(v1, v2)):
            return "V1_PRECEDES"
        elif all(a >= b for a, b in zip(v1, v2)) and any(a > b for a, b in zip(v1, v2)):
            return "V2_PRECEDES"
        elif v1 == v2:
            return "SAME"
        return "CONCURRENT"

    def acquire_admin_lock(self, client_id: str) -> bool:
        # A cluster-wide administrative lock — conceptually backed by
        # consensus (L02-L03) in a real system, simplified here
        if self.admin_lock_holder is None:
            self.admin_lock_holder = client_id
            return True
        return False

    def release_admin_lock(self, client_id: str):
        if self.admin_lock_holder == client_id:
            self.admin_lock_holder = None


def capstone_demo():
    store = DistributedKVStore(["replica-1", "replica-2", "replica-3"])

    print("=== Quorum-based write and read (L06) ===")
    result = store.write("user:42:cart", "[itemA]", client_vector_clock=[1, 0], w=2)
    print(f"  {result}")
    read_result = store.read("user:42:cart", r=2)
    print(f"  Read result: {read_result}\n")

    print("=== Concurrent conflicting write, detected via vector clocks (L05) ===")
    # A SECOND, genuinely concurrent write (neither vector clock dominates the other)
    result = store.write("user:42:cart", "[itemB]", client_vector_clock=[0, 1], w=2)
    print(f"  {result}\n")

    print("=== Cluster-wide administrative lock (L07, conceptually consensus-backed) ===")
    acquired = store.acquire_admin_lock("admin-client-1")
    print(f"  admin-client-1 acquired cluster lock: {acquired}")
    blocked = store.acquire_admin_lock("admin-client-2")
    print(f"  admin-client-2 attempts to acquire (should be blocked): {blocked}")
    store.release_admin_lock("admin-client-1")
    now_acquired = store.acquire_admin_lock("admin-client-2")
    print(f"  admin-client-2 acquires after release: {now_acquired}")


if __name__ == "__main__":
    capstone_demo()

"""
FINAL CONTEXT (capstone of this domain):
The measure of having internalized this domain isn't reciting the Paxos
or Raft protocols from memory — it's recognizing, when evaluating or
designing a REAL distributed system (a database, a coordination
service, a distributed job scheduler), which of these mechanisms
(consensus for strict coordination, quorums for tunable replicated
storage, vector clocks for conflict detection, fencing tokens for safe
locking) actually applies to a given requirement, and why — this is the
theoretical foundation underneath essentially every distributed
database and coordination service covered elsewhere in this repo
(Cassandra and DynamoDB in NoSQL & Specialized Databases Notes, etcd
underneath Kubernetes Notes, ZooKeeper underneath Apache Kafka Notes),
and understanding it here is what makes THEIR design decisions make sense rather than feel arbitrary.
"""
