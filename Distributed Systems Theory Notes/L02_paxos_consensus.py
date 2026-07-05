# ============================================================
# L02: Paxos — The Original Distributed Consensus Algorithm
# ============================================================
# WHAT: How a group of unreliable nodes, communicating over an
#       unreliable network (L01), can agree on a SINGLE value even if
#       some nodes fail or messages are lost or reordered — the Paxos
#       algorithm's two-phase protocol.
# WHY: CONSENSUS is the fundamental building block underneath
#      distributed databases, leader election (L07), and distributed
#      locks — Paxos was the first widely-adopted, formally-proven
#      solution, and understanding it (even though Raft, L03, is more
#      commonly implemented today) is what makes the PROBLEM Paxos and
#      Raft both solve genuinely clear.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
THE CONSENSUS PROBLEM: a set of nodes must agree on a SINGLE value
(e.g. "what is the next log entry," "who is the leader"), such that (1)
only a value that was actually PROPOSED can be chosen (VALIDITY), (2)
only ONE value is ever chosen (AGREEMENT), and (3) if enough nodes are
up and can communicate, SOME value eventually gets chosen (TERMINATION,
in practice) — achieving this correctly DESPITE L01's partial failures
and unreliable network is what makes consensus genuinely hard.

PAXOS SOLVES THIS via a TWO-PHASE protocol with three roles (a single
physical node can play multiple roles): PROPOSERS suggest values;
ACCEPTORS vote on proposals; LEARNERS find out what was chosen. PHASE 1
(PREPARE): a proposer picks a PROPOSAL NUMBER (must be unique and
increasing across all proposers) and sends a "prepare" request to a
MAJORITY of acceptors. Each acceptor PROMISES not to accept any FUTURE
proposal with a LOWER number, and replies with the highest-numbered
proposal it has ALREADY accepted (if any). PHASE 2 (ACCEPT): if the
proposer receives promises from a majority, it sends an "accept" request
— crucially, using the VALUE from the highest-numbered proposal any
acceptor already reported (if any acceptor had already accepted
something), or its OWN value if no acceptor had. If a majority of
acceptors accept, that value is CHOSEN.

WHY MAJORITY QUORUMS: requiring a MAJORITY (not all, not just one) of
acceptors to agree is what makes Paxos tolerate a MINORITY of node
failures while still guaranteeing agreement — critically, any two
majorities of the SAME group must OVERLAP by at least one node (a
simple pigeonhole argument for any group size), which is the
mathematical property that prevents two DIFFERENT values from being
chosen by two different majorities simultaneously.

WHY THE "USE THE HIGHEST-NUMBERED ALREADY-ACCEPTED VALUE" RULE MATTERS:
this is the subtle mechanism that actually GUARANTEES agreement — if a
value was already chosen by an earlier majority (even if the CURRENT
proposer doesn't directly know this), that value will necessarily show
up in at least one acceptor's response during phase 1 (due to the
majority-overlap property above), forcing the new proposer to
PROPAGATE the already-chosen value rather than accidentally choosing a
DIFFERENT one — this is what prevents the agreement guarantee from
being violated even when multiple proposers are racing concurrently.

WHY PAXOS IS NOTORIOUSLY HARD TO UNDERSTAND (AND WHY RAFT EXISTS, L03):
the BASIC Paxos protocol described above only agrees on a SINGLE value
— building a REPLICATED LOG (agreeing on an ordered SEQUENCE of values,
what real systems actually need) requires running MANY INSTANCES of
Paxos, plus substantial additional engineering (leader election
optimization, log compaction) that the original papers left largely as
an exercise — this gap between "the elegant core algorithm" and "an
actual production-ready implementation" is widely cited as Paxos's
biggest practical weakness, directly motivating Raft's design goal of
being more DIRECTLY implementable.

PRODUCTION USE CASE:
Google's Chubby lock service (and Spanner's underlying replication) uses
Paxos-family consensus to ensure that even if a datacenter fails, the
remaining majority of replicas can still agree on the current state
without any two replicas disagreeing about what was decided — this is
the algorithmic foundation underneath "your distributed database
doesn't lose or corrupt data even during a partial outage."

COMMON MISTAKES:
- Implementing "consensus" as a simple majority vote WITHOUT the
  proposal-numbering and "adopt the highest already-accepted value"
  mechanism — this looks superficially similar to Paxos but does NOT
  actually guarantee agreement under concurrent proposals, a subtle
  correctness bug that only manifests during specific interleavings/failures.
- Assuming Paxos (or any consensus algorithm) requires ALL nodes to
  respond — it specifically requires only a MAJORITY, which is precisely
  what allows it to keep functioning despite a MINORITY of nodes being
  down, a deliberate design choice enabling fault tolerance.
- Underestimating the gap between "understanding single-value Paxos" and
  "building a production consensus system" — this gap (multi-Paxos, log
  compaction, membership changes, leader-election optimization) is
  substantial, which is exactly why most engineers today reach for Raft
  (L03) or an existing implementation (etcd, ZooKeeper) rather than
  implementing Paxos from scratch.
"""


# ------------------------------------------------------------------
# 1. A simplified single-value Paxos simulation
# ------------------------------------------------------------------
class Acceptor:
    def __init__(self, name: str):
        self.name = name
        self.promised_proposal_number = None
        self.accepted_proposal_number = None
        self.accepted_value = None

    def receive_prepare(self, proposal_number: int) -> dict:
        if self.promised_proposal_number is None or proposal_number > self.promised_proposal_number:
            self.promised_proposal_number = proposal_number
            return {
                "promised": True,
                "previously_accepted_number": self.accepted_proposal_number,
                "previously_accepted_value": self.accepted_value,
            }
        return {"promised": False}

    def receive_accept(self, proposal_number: int, value) -> bool:
        if self.promised_proposal_number is None or proposal_number >= self.promised_proposal_number:
            self.accepted_proposal_number = proposal_number
            self.accepted_value = value
            return True
        return False


def run_paxos_round(acceptors: list[Acceptor], proposal_number: int, proposed_value) -> str | None:
    # PHASE 1: prepare
    promises = [a.receive_prepare(proposal_number) for a in acceptors]
    granted = [p for p in promises if p["promised"]]

    majority = len(acceptors) // 2 + 1
    if len(granted) < majority:
        return None   # failed to get a majority promise

    # CRITICAL RULE: adopt the highest-numbered ALREADY-ACCEPTED value,
    # if any acceptor reported one — do NOT blindly use our own proposed value
    already_accepted = [p for p in granted if p["previously_accepted_value"] is not None]
    if already_accepted:
        highest = max(already_accepted, key=lambda p: p["previously_accepted_number"])
        value_to_propose = highest["previously_accepted_value"]
        print(f"  Proposer discovered an ALREADY-ACCEPTED value "
              f"('{value_to_propose}') during phase 1 — adopting it instead "
              f"of its own proposed value ('{proposed_value}').")
    else:
        value_to_propose = proposed_value

    # PHASE 2: accept
    accepts = [a.receive_accept(proposal_number, value_to_propose) for a in acceptors]
    if sum(accepts) >= majority:
        return value_to_propose
    return None


def paxos_demo():
    acceptors = [Acceptor(f"acceptor-{i}") for i in range(5)]

    print("Round 1: Proposer A proposes 'value-A' with proposal number 1")
    result_a = run_paxos_round(acceptors, proposal_number=1, proposed_value="value-A")
    print(f"  Chosen value: {result_a}\n")

    print("Round 2: Proposer B (unaware of round 1) proposes 'value-B' "
          "with a HIGHER proposal number 2")
    result_b = run_paxos_round(acceptors, proposal_number=2, proposed_value="value-B")
    print(f"  Chosen value: {result_b}")
    print("\n  -> Even though Proposer B tried to propose a DIFFERENT value,")
    print("     the protocol forced it to discover and adopt the ALREADY-")
    print("     CHOSEN value from round 1 — this is EXACTLY the mechanism")
    print("     that guarantees agreement despite concurrent proposals.")


if __name__ == "__main__":
    paxos_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
Google's Chubby distributed lock service uses a Paxos-based replicated
state machine across 5 servers — if 2 of them crash simultaneously, the
remaining 3 (still a majority) continue reaching agreement on lock state
correctly, and when the crashed servers eventually recover and rejoin,
Paxos's "adopt the highest already-accepted value" mechanism ensures
they catch up to the CORRECT, already-agreed state rather than
introducing any inconsistency — precisely the guarantee this lesson's
simulation demonstrates at a small, illustrative scale.
"""
