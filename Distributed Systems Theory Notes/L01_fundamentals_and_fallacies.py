# ============================================================
# L01: Distributed Systems Fundamentals — The Fallacies and Why They Matter
# ============================================================
# WHAT: The foundational assumptions that make distributed systems hard
#       — the "Fallacies of Distributed Computing" (a classic list from
#       Sun Microsystems engineers), partial failure, and why a
#       distributed system cannot be reasoned about like a single program.
# WHY: This repo's System Design Notes covers CAP theorem at a practical
#      level. This new domain goes underneath that — the actual THEORY
#      (consensus algorithms, distributed transactions, logical time)
#      that CAP theorem and every distributed database ultimately rests on.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
THE FALLACIES OF DISTRIBUTED COMPUTING are a set of assumptions
engineers new to distributed systems commonly (and incorrectly) make,
each of which is FALSE in reality and causes real production bugs when
assumed true: "the network is reliable" (it isn't — packets drop,
connections reset); "latency is zero" (a same-datacenter call still
takes real, non-negligible time; a cross-region call can take hundreds
of milliseconds); "bandwidth is infinite" (network links have real
capacity limits); "the network is secure" (data in transit can be
intercepted without encryption); "topology doesn't change" (servers are
added/removed, IPs change); "there is one administrator" (real systems
span teams/organizations with different priorities); "transport cost is
zero" (serializing/deserializing and sending data has real CPU/time
cost); "the network is homogeneous" (different network segments have
different reliability/performance characteristics).

PARTIAL FAILURE is THE defining characteristic that separates
distributed systems from single-machine programs: in a single program,
if something fails, the ENTIRE program typically fails or an exception
propagates predictably — in a distributed system, SOME nodes can fail
while OTHERS continue operating normally, and — critically — a node
often CANNOT DISTINGUISH between "the remote node crashed," "the remote
node is just slow," and "the network link between us is down" — these
three genuinely different failure modes look IDENTICAL from the
observing node's perspective (a timeout), yet the CORRECT response to
each can be different, and a system design that doesn't account for
this ambiguity will make incorrect assumptions during real failures.

THE IMPOSSIBILITY OF PERFECT FAILURE DETECTION follows directly from
partial failure: in an ASYNCHRONOUS system (no guaranteed upper bound on
message delay — the reality of the actual internet), it is PROVABLY
IMPOSSIBLE to build a perfectly accurate failure detector — any timeout-
based detection mechanism will EITHER occasionally declare a
still-alive-but-slow node as dead (a false positive) OR wait
indefinitely for genuinely dead nodes (unbounded latency) — every real
distributed system's failure-detection mechanism is a DELIBERATE,
tuned tradeoff between these two failure modes, not a solved problem.

WHY THIS MATTERS FOR EVERYTHING THAT FOLLOWS IN THIS DOMAIN: consensus
algorithms (L02-L03), distributed transactions (L04), and quorum systems
(L06) all exist SPECIFICALLY to build reliable, coordinated behavior on
TOP of this fundamentally unreliable, partial-failure-prone foundation —
understanding WHY the foundation is this way is what makes the
(sometimes seemingly overcomplicated) solutions in later lessons make sense.

PRODUCTION USE CASE:
A payment processing system assumes "the network is reliable" when
calling a downstream fraud-check service — during a network partition, a
request the fraud service actually PROCESSED and approved never gets its
response back to the caller in time, which (incorrectly assuming the
call simply failed) retries the payment — resulting in a DOUBLE CHARGE.
The actual bug wasn't in either service's logic; it was in the
ASSUMPTION that "no response" means "didn't happen," when it actually
meant "happened, but the network dropped the response" — exactly the
kind of partial-failure ambiguity this lesson describes.

COMMON MISTAKES:
- Treating a timeout as equivalent to "the operation definitely did not
  happen" — a timeout only tells you "no response was received within
  the timeout window," which is consistent with EITHER the operation
  failing OR succeeding-but-the-response-being-lost/delayed — idempotent
  design (safe to retry) is the standard mitigation, not just retrying naively.
- Assuming a distributed system will fail "all or nothing," the way a
  single-process crash typically does — production distributed systems
  overwhelmingly fail PARTIALLY, with different nodes in different
  states simultaneously, which is a fundamentally different failure
  shape to design and test for.
- Under-investing in testing NETWORK-LEVEL failure scenarios (partitions,
  slow links, dropped packets) specifically because they're harder to
  simulate than simple process crashes — chaos engineering practices
  (deliberately injecting network faults) exist specifically to address
  this common testing gap.
"""

import random
import time


# ------------------------------------------------------------------
# 1. The fallacies, and what actually goes wrong when assumed
# ------------------------------------------------------------------
FALLACIES = [
    ("The network is reliable", "Packets drop, connections reset — retries and idempotency are mandatory, not optional."),
    ("Latency is zero", "Even same-datacenter calls take real time — chaining many synchronous calls compounds this."),
    ("Bandwidth is infinite", "Large payloads over constrained links cause real, measurable slowdowns."),
    ("The network is secure", "Unencrypted traffic can be intercepted; TLS (this domain's Case Studies L26) matters."),
    ("Topology doesn't change", "Servers scale up/down, IPs change — hardcoded addresses break in production."),
    ("There is one administrator", "Cross-team/cross-org systems have differing priorities and change schedules."),
    ("Transport cost is zero", "Serialization and network I/O have real CPU and time cost, especially at scale."),
    ("The network is homogeneous", "A mobile connection and a datacenter backbone have wildly different characteristics."),
]


def print_fallacies():
    print("The Fallacies of Distributed Computing:\n")
    for fallacy, consequence in FALLACIES:
        print(f"  FALSE ASSUMPTION: \"{fallacy}\"")
        print(f"    -> {consequence}\n")


# ------------------------------------------------------------------
# 2. Partial failure — three failure modes that look identical
# ------------------------------------------------------------------
def simulate_ambiguous_timeout(scenario: str) -> str:
    """From the CALLER's perspective, all three of these scenarios
    produce the EXACT SAME observable symptom: a timeout."""
    scenarios = {
        "crashed": "The remote node crashed before processing the request at all.",
        "slow": "The remote node is alive and processing, just slower than the timeout window.",
        "network_down": "The remote node fully processed the request, but the RESPONSE was lost in transit.",
    }
    return scenarios[scenario]


def partial_failure_demo():
    print("Three DIFFERENT failure scenarios, indistinguishable from the caller's side:\n")
    for scenario in ["crashed", "slow", "network_down"]:
        description = simulate_ambiguous_timeout(scenario)
        print(f"  Scenario '{scenario}': {description}")
        print(f"    Caller observes: TIMEOUT (identical in all three cases)\n")

    print("  -> The CORRECT response differs by scenario (don't retry if it")
    print("     already succeeded and isn't idempotent!), but the caller")
    print("     CANNOT tell which scenario actually occurred from a timeout alone.")


# ------------------------------------------------------------------
# 3. Failure detector tradeoff — false positives vs unbounded latency
# ------------------------------------------------------------------
def failure_detector_tradeoff_demo():
    print("\nFailure detector timeout tuning — a deliberate tradeoff:\n")
    configs = [
        {"timeout_ms": 100, "risk": "HIGH false-positive rate — a merely-slow node gets declared dead"},
        {"timeout_ms": 5000, "risk": "LOW false-positive rate, but genuinely dead nodes take 5s to detect"},
    ]
    for config in configs:
        print(f"  Timeout={config['timeout_ms']}ms: {config['risk']}")
    print("\n  -> There is NO timeout value that eliminates both risks")
    print("     simultaneously — this is a PROVABLE impossibility in an")
    print("     asynchronous network, not a tuning problem waiting for a perfect answer.")


if __name__ == "__main__":
    print_fallacies()
    partial_failure_demo()
    failure_detector_tradeoff_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
An e-commerce checkout system calls an inventory-reservation service and
times out waiting for a response — rather than assuming "it failed" and
simply retrying (risking a DOUBLE reservation if the original request
actually succeeded server-side), the system is designed with an
IDEMPOTENCY KEY: the retry carries the SAME unique request ID, and the
inventory service recognizes it's already processed that exact request,
returning the ORIGINAL result rather than reserving inventory twice —
this idempotent design is a direct, practical response to the partial-
failure ambiguity this lesson describes, and it's the foundation every
later lesson in this domain builds additional coordination machinery on top of.
"""
