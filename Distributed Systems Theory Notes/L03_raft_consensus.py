# ============================================================
# L03: Raft — Consensus Designed for Understandability
# ============================================================
# WHAT: The Raft consensus algorithm — explicitly designed as an
#       easier-to-understand, easier-to-implement alternative to Paxos
#       (L02) that solves the SAME consensus problem via explicit leader
#       election and a replicated log.
# WHY: Paxos (L02) is notoriously difficult to build a complete,
#      production-correct system from. Raft is the algorithm actually
#      used by most modern systems you'll encounter (etcd, Consul,
#      CockroachDB, TiKV) — precisely because of this understandability
#      and implementability advantage.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
RAFT DECOMPOSES CONSENSUS into three separable sub-problems that Paxos
(L02) leaves comparatively entangled: LEADER ELECTION (choosing a single
node to coordinate all writes), LOG REPLICATION (the leader appending
entries to its own log and replicating them to followers), and SAFETY
(ensuring the algorithm's guarantees hold even during leader crashes,
network partitions, and concurrent elections) — each is described and
reasoned about largely independently, which is the core source of
Raft's comparative clarity over Paxos's more unified, harder-to-decompose treatment.

LEADER ELECTION: every node is in one of three states — FOLLOWER,
CANDIDATE, or LEADER. All nodes start as followers. If a follower
doesn't hear from a leader within a randomized ELECTION TIMEOUT, it
becomes a candidate, increments a TERM number, votes for itself, and
requests votes from other nodes. A candidate becomes leader if it
receives votes from a MAJORITY (the same quorum concept as Paxos, L02).
The RANDOMIZED timeout (each node picks a different random timeout
duration) is a deliberately simple mechanism to avoid SPLIT VOTES —
without randomization, multiple followers would likely time out
SIMULTANEOUSLY and start competing elections repeatedly, indefinitely
delaying convergence on a single leader.

LOG REPLICATION: once elected, a leader is the ONLY node that accepts
new write requests — it appends each entry to its own log, then
replicates it to followers via AppendEntries RPCs. An entry is
considered COMMITTED once a MAJORITY of nodes have replicated it — at
that point, it's guaranteed to be durable even if the leader immediately
crashes (since a majority already has it, and any future leader election
requires votes from a majority, guaranteeing overlap with at least one
node holding the committed entry — the SAME majority-overlap property
underlying Paxos's correctness).

TERMS act as a LOGICAL CLOCK (a simpler relative of L05's vector clocks)
— every message includes the sender's current term number; a node
receiving a message with a HIGHER term number than its own immediately
recognizes its own information is STALE (e.g. it thought it was still
leader, but a new election has already happened) and steps down/updates
accordingly — this simple, monotonically-increasing counter is what lets
nodes detect and resolve STALE LEADERSHIP without any more complex
coordination mechanism.

WHY RAFT DISPLACED PAXOS IN PRACTICE for new systems: Raft's paper
included, from the start, the "boring but essential" parts Paxos's
original presentation left as an exercise — membership changes (adding/
removing nodes from the cluster safely), log compaction (preventing the
replicated log from growing forever), and a complete, unambiguous
leader-election protocol — this completeness is why etcd (Kubernetes'
own configuration store), Consul, and CockroachDB all chose to implement
Raft rather than Paxos directly, despite both algorithms solving the identical underlying problem.

PRODUCTION USE CASE:
Kubernetes' control plane relies on etcd, which uses Raft to replicate
the cluster's entire configuration state across multiple etcd nodes — if
the etcd leader crashes, the remaining nodes detect this via election
timeout, hold a new election (using randomized timeouts to avoid split
votes), and a new leader is chosen and continues serving writes within a
bounded time window, with NO data loss for any entry that had already
been committed to a majority before the crash.

COMMON MISTAKES:
- Using a FIXED (non-randomized) election timeout across all nodes —
  this causes REPEATED SPLIT VOTES, since multiple followers would
  detect the missing leader and start competing elections at the exact
  same moment, indefinitely — randomization is what breaks this symmetry
  and ensures elections actually converge in practice.
- Allowing a FOLLOWER to accept write requests directly — Raft's design
  specifically routes ALL writes through the single current leader;
  allowing followers to accept writes independently would reintroduce
  exactly the kind of conflicting-value problem consensus exists to prevent.
- Considering an entry "durable" as soon as the LEADER has written it
  locally, before replicating to a majority — this is a critical
  correctness bug: if the leader crashes before replication, that entry
  is LOST, despite having been acknowledged; true durability specifically
  requires majority replication, not merely local persistence.
"""

import random


# ------------------------------------------------------------------
# 1. Leader election with randomized timeouts (avoiding split votes)
# ------------------------------------------------------------------
class RaftNode:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.state = "follower"
        self.current_term = 0
        self.voted_for = None
        self.election_timeout = random.uniform(150, 300)   # randomized, in ms (illustrative)

    def start_election(self, all_nodes: list["RaftNode"]) -> bool:
        self.state = "candidate"
        self.current_term += 1
        self.voted_for = self.node_id
        votes = 1   # votes for itself

        for node in all_nodes:
            if node.node_id != self.node_id:
                if node.receive_vote_request(self.current_term, self.node_id):
                    votes += 1

        majority = len(all_nodes) // 2 + 1
        if votes >= majority:
            self.state = "leader"
            print(f"  {self.node_id} elected LEADER for term {self.current_term} "
                  f"with {votes}/{len(all_nodes)} votes")
            return True
        else:
            self.state = "follower"
            return False

    def receive_vote_request(self, candidate_term: int, candidate_id: str) -> bool:
        if candidate_term > self.current_term and self.voted_for is None:
            self.current_term = candidate_term
            self.voted_for = candidate_id
            return True
        return False


def leader_election_demo():
    nodes = [RaftNode(f"node-{i}") for i in range(5)]
    # In a real Raft implementation, the node with the SHORTEST randomized
    # timeout naturally times out first and starts the election
    candidate = min(nodes, key=lambda n: n.election_timeout)
    print(f"Node with shortest randomized timeout ({candidate.election_timeout:.0f}ms) "
          f"starts an election: {candidate.node_id}\n")
    candidate.start_election(nodes)


# ------------------------------------------------------------------
# 2. Log replication and the commit rule (majority = durable)
# ------------------------------------------------------------------
class RaftLog:
    def __init__(self, num_followers: int):
        self.entries: list[dict] = []
        self.num_followers = num_followers

    def leader_append(self, command: str, term: int) -> int:
        entry = {"command": command, "term": term, "replicated_count": 1}   # leader itself counts
        self.entries.append(entry)
        return len(self.entries) - 1

    def follower_replicate(self, entry_index: int):
        self.entries[entry_index]["replicated_count"] += 1

    def is_committed(self, entry_index: int) -> bool:
        majority = (self.num_followers + 1) // 2 + 1   # +1 for the leader itself
        return self.entries[entry_index]["replicated_count"] >= majority


def log_replication_demo():
    print("\nLog replication and commit rule:")
    log = RaftLog(num_followers=4)   # 5-node cluster total
    entry_index = log.leader_append("SET x = 5", term=3)
    print(f"  Leader appends entry locally. Committed? {log.is_committed(entry_index)}")

    log.follower_replicate(entry_index)
    log.follower_replicate(entry_index)
    print(f"  After 2 followers replicate (3/5 total). "
          f"Committed? {log.is_committed(entry_index)}")
    print("  -> Only once a MAJORITY has the entry is it considered durable —")
    print("     the leader crashing at this point would NOT lose this entry,")
    print("     since a future leader election requires majority votes,")
    print("     guaranteeing overlap with at least one node holding it.")


if __name__ == "__main__":
    leader_election_demo()
    log_replication_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
When a Kubernetes cluster's etcd leader node is terminated (a routine
node replacement, or an actual failure), the remaining etcd nodes detect
the missing heartbeat within their randomized election timeouts, one of
them wins a new leader election, and the Kubernetes API server
continues functioning against the new leader within a bounded
window — any cluster-state write that had already been acknowledged to
a client before the crash is GUARANTEED to still be present after the
new leader takes over, precisely because Raft's commit rule required
majority replication before ever acknowledging that write in the first place.
"""
