# Distributed Systems Theory — Principal Engineer Deep Dive

Companion to the existing lessons. Narrative depth, then a comprehensive
common-to-uncommon reference.


## Consensus Algorithms — Why Raft Won the Popularity Contest

**Beyond the lesson**: Paxos is CORRECT but notoriously hard to
understand and implement correctly — its own paper admits engineers
routinely got subtly-wrong implementations into production. Raft was
explicitly designed as a more UNDERSTANDABLE alternative achieving the
same guarantees, by decomposing the problem into clearly separable
sub-problems (leader election, log replication, safety) with a strong
invariant: only ONE leader exists per term, and the leader has full
authority over log entries — this decomposition is WHY Raft became the
default choice for new systems (etcd, Consul, CockroachDB all use it)
despite Paxos being "first" — implementability and auditability won out over theoretical primacy.

**Worked example**: Leader election in Raft, concretely — nodes start as
followers with a randomized election timeout; if a follower doesn't hear
from a leader within that timeout, it becomes a candidate, increments its
term, and requests votes; a candidate that receives a MAJORITY of votes
becomes leader for that term. The RANDOMIZED timeout is deliberate — it
makes split votes (multiple candidates simultaneously) statistically
unlikely without needing any centralized coordination to prevent them.

**Interview Q&A**:
- *Q: Why does Raft require a MAJORITY (not just "more than one") of nodes to agree before committing a log entry?* A: A majority quorum guarantees that any two committed decisions must have at least ONE overlapping node between their respective majorities — this overlap is what prevents two conflicting decisions from both being considered "committed" during a network partition, the core safety property consensus needs to hold.


## The FLP Impossibility Result & Why It Matters Practically

**Beyond the lesson**: The Fischer-Lynch-Paterson (FLP) result proves
that in a fully ASYNCHRONOUS system (no bound on message delay), NO
consensus algorithm can guarantee both safety AND termination if even
ONE node can fail — this sounds purely theoretical but has a real
practical consequence: every real consensus system (Raft, Paxos) achieves
liveness in practice by relying on PARTIAL SYNCHRONY assumptions
(timeouts, leases) that aren't formally guaranteed but hold "usually" —
this is exactly why a consensus system can occasionally stall (no leader
elected) during genuinely pathological network conditions, and why
understanding this tradeoff (safety is ALWAYS guaranteed; liveness is
guaranteed only under reasonable network conditions) is a real, senior-level distinction.

**Interview Q&A**:
- *Q: A Raft cluster of 5 nodes lost network connectivity, splitting into a 3-node and a 2-node partition. What happens?* A: The 3-node partition (having a majority) can elect a leader and continue operating normally; the 2-node partition cannot reach a majority and cannot elect a leader or commit new entries — this is the system correctly CHOOSING safety over availability during the partition (a CP choice, tying directly back to the CAP theorem discussion in NoSQL Notes deep dive).


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Consistency models, precisely ordered from strongest to weakest
- **Linearizability** — the strongest practical guarantee: every
  operation appears to happen instantaneously at some point between its
  invocation and completion, and all operations across all clients agree
  on a single global order — genuinely expensive to achieve at scale
  (requires real coordination), but the easiest model to reason about.
- **Sequential consistency** — all operations appear in SOME consistent
  order across all clients, but not necessarily REAL-TIME order — weaker
  than linearizability but still globally agreed-upon.
- **Causal consistency** — operations that are causally related (a write
  that happened-before another) are seen in that order by everyone, but
  CONCURRENT, unrelated operations may be seen in different orders by
  different clients — a genuinely useful middle ground many real systems target.
- **Eventual consistency** — the weakest common guarantee: given no new
  writes, all replicas EVENTUALLY converge to the same value, with no
  bound on how long "eventually" takes — DynamoDB/Cassandra's default,
  trading consistency strength for availability/partition tolerance (see NoSQL deep dive).

### Distributed system building blocks
- **Vector clocks** — a mechanism for tracking CAUSAL ordering across
  distributed events without a synchronized global clock — each node
  maintains a vector of logical counters (one per node), incremented on
  each event, letting the system determine whether two events are
  causally ordered or genuinely concurrent (and therefore potentially conflicting).
- **Gossip protocols** — nodes periodically exchange state with a random
  subset of peers, propagating information eventually to the whole
  cluster without a central coordinator — the mechanism underneath
  Cassandra's cluster membership/failure detection and many other
  large-scale distributed systems' metadata propagation.
- **CRDTs (Conflict-free Replicated Data Types)** — data structures
  mathematically designed so that concurrent updates from different
  replicas can always be MERGED deterministically without conflicts,
  regardless of the order they're applied — used in collaborative editing
  (Google Docs-style) and offline-first sync systems (see Edge Computing deep dive).
- **Quorum reads/writes** — requiring a majority (or configurable
  W/R threshold) of replicas to acknowledge a write/participate in a read
  — the tunable knob (see DynamoDB's tunable consistency, NoSQL deep dive)
  letting a system trade consistency strength against latency/availability per-operation.

### Failure detection & fault tolerance
- **Heartbeats & timeouts** — the basic mechanism for detecting a failed
  node, with a real, unavoidable tradeoff: a short timeout detects
  failures fast but risks FALSE POSITIVES (a slow-but-alive node gets
  incorrectly marked dead) under network jitter; too long a timeout
  delays real failure detection.
- **Phi Accrual Failure Detector** — a more sophisticated approach
  (used by Cassandra/Akka) that computes a continuous SUSPICION LEVEL
  based on historical heartbeat arrival patterns, rather than a binary
  alive/dead threshold — adapts to a node's normal jitter pattern instead
  of using one fixed timeout for the whole cluster.


## NICHE BUT REAL

- **Byzantine Fault Tolerance (BFT)** — consensus that tolerates not just
  crashed/unresponsive nodes (the "fail-stop" model Raft/Paxos assume) but
  ACTIVELY MALICIOUS nodes sending conflicting/false information — needed
  in blockchain/untrusted multi-party systems (see Blockchain & Web3
  Notes), requires a much higher quorum threshold (>2/3 rather than >1/2)
  and is genuinely more expensive/complex than crash-fault-tolerant consensus.
- **The Two Generals' Problem** — a foundational thought experiment
  proving that two parties CANNOT achieve guaranteed agreement over an
  unreliable communication channel (a message or its acknowledgment could
  always be lost) — the conceptual ancestor of FLP impossibility, worth
  knowing as the simplest possible illustration of why perfect distributed
  agreement is fundamentally, not just practically, hard.
- **Split-brain** — a named failure mode where a partition causes TWO
  nodes to both believe they're the leader/primary simultaneously,
  potentially both accepting writes — the exact scenario quorum-based
  consensus is designed to prevent, and a real, recurring root cause when
  homegrown "leader election" (without a proper consensus algorithm
  underneath) is naively implemented via something like a simple heartbeat check.
- **Lamport timestamps** — a simpler predecessor to vector clocks,
  providing a total ordering consistent with causality (if A happened-
  before B, A's timestamp is less than B's) but WITHOUT vector clocks'
  ability to definitively detect concurrent (non-causally-related) events
  — a real, historically foundational building block worth knowing by name.
