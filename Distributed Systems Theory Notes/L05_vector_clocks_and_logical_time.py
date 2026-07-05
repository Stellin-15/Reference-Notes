# ============================================================
# L05: Vector Clocks and Logical Time — Ordering Events Without a Clock
# ============================================================
# WHAT: How distributed systems determine the RELATIVE ORDER of events
#       across different nodes WITHOUT relying on synchronized physical
#       clocks (which L01's fallacies already warned aren't reliable
#       across a network) — Lamport timestamps and vector clocks.
# WHY: L02-L04 all needed SOME notion of ordering (proposal numbers,
#      terms, transaction sequencing). This lesson covers the general
#      theory of logical time those mechanisms are specific
#      applications of.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
WHY PHYSICAL CLOCKS DON'T WORK for ordering distributed events: even
with NTP synchronization, clocks across different machines can differ by
tens of milliseconds or more, and CLOCK DRIFT means this gap changes
over time — two events on DIFFERENT machines with very close physical
timestamps might ACTUALLY have happened in the opposite order their
timestamps suggest, making physical time an unreliable ordering
mechanism for distributed systems specifically (a single machine's own
local physical clock, by contrast, IS reliable for ordering ITS OWN sequential events).

LAMPORT TIMESTAMPS (also called Lamport clocks) provide a simple LOGICAL
clock: each node maintains a counter, incremented on every local event;
when SENDING a message, the counter is attached; when RECEIVING a
message, the local counter is updated to `max(local_counter,
received_counter) + 1`. This guarantees that if event A CAUSALLY
influenced event B (e.g. A is "send a message," B is "receive that
message"), then A's Lamport timestamp is guaranteed to be LESS THAN B's
— this property is called CLOCK CONSISTENCY. The critical LIMITATION:
Lamport timestamps only provide a PARTIAL guarantee in one direction — if
timestamp(A) < timestamp(B), you CANNOT conclude A causally happened
before B (they might be entirely CONCURRENT, unrelated events that just
happened to get assigned that relative ordering) — Lamport timestamps
cannot DISTINGUISH between "A causally preceded B" and "A and B are concurrent."

VECTOR CLOCKS fix this specific limitation: instead of a single integer,
each node maintains a VECTOR of counters, one per node in the system
(e.g. `[node_A_counter, node_B_counter, node_C_counter]`). On a local
event, a node increments ONLY its own position in the vector; when
sending a message, it attaches its full vector; when receiving, it takes
the ELEMENT-WISE MAXIMUM of its own vector and the received vector, then
increments its own position. This gives a PRECISE causality test: event
A causally precedes event B if and only if EVERY element of A's vector
is LESS THAN OR EQUAL TO the corresponding element of B's vector, AND at
least one element is STRICTLY less — if NEITHER vector dominates the
other this way, the events are PROVABLY CONCURRENT (genuinely
independent, with no causal relationship either direction) — this is
exactly the extra distinguishing power Lamport timestamps lack.

WHY THIS MATTERS PRACTICALLY: detecting CONCURRENT, POTENTIALLY
CONFLICTING updates is exactly what's needed for CONFLICT DETECTION in
distributed databases with multiple writers (this repo's System Design
Case Studies Notes L07 covered CRDTs, which solve a related problem for
collaborative editing specifically) — Amazon's original Dynamo paper
(and DynamoDB's lineage from it) used vector clocks SPECIFICALLY to
detect when two different replicas received CONCURRENT, conflicting
writes to the same key, surfacing this ambiguity for resolution (either
automatically via a merge function, or by surfacing both versions to
the application) rather than silently and arbitrarily picking one write to discard.

PRODUCTION USE CASE:
A distributed shopping cart service (the use case famously discussed in
Amazon's Dynamo paper) allows a customer to add items to their cart from
multiple devices that might be temporarily disconnected from each
other's updates — vector clocks attached to each cart-update event let
the system determine, on reconciliation, whether one update CAUSALLY
followed another (safe to simply keep the later one) or whether TWO
updates were genuinely CONCURRENT (e.g. adding item A on a phone while
simultaneously adding item B on a laptop, with neither device aware of
the other's update) — in the concurrent case, the system MERGES both
additions (the "keep everything a customer put in their cart" policy
Dynamo's paper specifically describes) rather than losing one update entirely.

COMMON MISTAKES:
- Using PHYSICAL wall-clock timestamps to determine event ordering
  across different machines — clock skew (even with NTP) makes this
  UNRELIABLE for anything requiring a correctness guarantee, not just a rough approximation.
- Using Lamport timestamps where TRUE CAUSALITY DETECTION is actually
  needed — Lamport timestamps CANNOT distinguish "A caused B" from "A
  and B are concurrent," a real limitation for use cases (like the
  Dynamo cart example) that specifically need to detect and handle
  genuine concurrency differently from causal ordering.
- Assuming vector clocks scale to VERY large numbers of nodes without
  concern — a vector clock's size grows LINEARLY with the number of
  distinct nodes/replicas in the system, which is a genuine practical
  concern for systems with very large, dynamic node counts (various
  size-bounding and pruning techniques exist specifically to address this).
"""


# ------------------------------------------------------------------
# 1. Lamport timestamps — partial ordering, cannot detect concurrency
# ------------------------------------------------------------------
class LamportClock:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.counter = 0

    def local_event(self) -> int:
        self.counter += 1
        return self.counter

    def send_message(self) -> int:
        self.counter += 1
        return self.counter

    def receive_message(self, received_counter: int) -> int:
        self.counter = max(self.counter, received_counter) + 1
        return self.counter


def lamport_demo():
    node_a = LamportClock("A")
    node_b = LamportClock("B")

    t1 = node_a.local_event()
    print(f"Node A local event -> Lamport timestamp {t1}")

    sent_timestamp = node_a.send_message()
    print(f"Node A sends message -> Lamport timestamp {sent_timestamp}")

    t2 = node_b.receive_message(sent_timestamp)
    print(f"Node B receives message -> Lamport timestamp {t2}")
    print(f"\n  Node A's send ({sent_timestamp}) < Node B's receive ({t2}): "
          f"CORRECTLY reflects causality (send happened before receive)")
    print("  -> But if we instead saw two UNRELATED events with timestamps")
    print("     3 and 5, we could NOT conclude one caused the other —")
    print("     Lamport timestamps can't distinguish causality from coincidence.")


# ------------------------------------------------------------------
# 2. Vector clocks — precise causality AND concurrency detection
# ------------------------------------------------------------------
class VectorClock:
    def __init__(self, node_id: str, all_node_ids: list[str]):
        self.node_id = node_id
        self.node_index = all_node_ids.index(node_id)
        self.vector = [0] * len(all_node_ids)

    def local_event(self) -> list[int]:
        self.vector[self.node_index] += 1
        return list(self.vector)

    def receive_message(self, received_vector: list[int]) -> list[int]:
        self.vector = [max(a, b) for a, b in zip(self.vector, received_vector)]
        self.vector[self.node_index] += 1
        return list(self.vector)


def compare_vector_clocks(v1: list[int], v2: list[int]) -> str:
    if all(a <= b for a, b in zip(v1, v2)) and any(a < b for a, b in zip(v1, v2)):
        return "v1 CAUSALLY PRECEDES v2"
    elif all(a >= b for a, b in zip(v1, v2)) and any(a > b for a, b in zip(v1, v2)):
        return "v2 CAUSALLY PRECEDES v1"
    elif v1 == v2:
        return "IDENTICAL (same event)"
    else:
        return "CONCURRENT — no causal relationship, a genuine conflict to resolve"


def vector_clock_demo():
    print("\nVector clocks — detecting a GENUINE conflict (Dynamo-style shopping cart):\n")
    nodes = ["phone", "laptop"]
    phone_clock = VectorClock("phone", nodes)
    laptop_clock = VectorClock("laptop", nodes)

    # Both devices update the cart INDEPENDENTLY, with NO communication
    # between them (e.g. both temporarily offline from each other)
    phone_vector = phone_clock.local_event()   # "add item A" on phone
    laptop_vector = laptop_clock.local_event()  # "add item B" on laptop, concurrently

    print(f"Phone's vector after adding item A: {phone_vector}")
    print(f"Laptop's vector after adding item B: {laptop_vector}")

    comparison = compare_vector_clocks(phone_vector, laptop_vector)
    print(f"\nComparing the two updates: {comparison}")
    print("  -> Detected as CONCURRENT — the system should MERGE both cart")
    print("     additions (keep item A AND item B) rather than arbitrarily")
    print("     discarding one, exactly as Amazon's Dynamo paper describes.")


if __name__ == "__main__":
    lamport_demo()
    vector_clock_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
DynamoDB's lineage traces directly to Amazon's original Dynamo paper,
which used vector clocks to handle exactly the shopping-cart scenario
this lesson simulates — when two replicas of a customer's cart diverge
due to concurrent, uncoordinated updates from different devices, vector
clocks let the system PROVE the updates were concurrent (rather than one
being a stale overwrite of the other) and apply an application-specific
merge policy (union the cart contents) — a direct, practical application
of the causality-vs-concurrency distinction this lesson's comparison function implements.
"""
