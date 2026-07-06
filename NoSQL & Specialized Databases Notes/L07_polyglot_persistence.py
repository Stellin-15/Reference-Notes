# ============================================================
# L07: Polyglot Persistence — Architecting with Multiple Databases Together
# ============================================================
# WHAT: The practical ENGINEERING CHALLENGES of actually running multiple
#       different database technologies together in one system — data
#       synchronization between them, maintaining consistency across
#       stores, and the operational overhead this genuinely adds.
# WHY: L06 established the DECISION framework for choosing polyglot
#      persistence. This lesson covers what it actually takes to
#      OPERATE such a system correctly — the synchronization and
#      consistency challenges L06's walkthrough glossed over.
# LEVEL: Advanced (capstone-adjacent)
# ============================================================

"""
CONCEPT OVERVIEW:
THE CORE CHALLENGE OF POLYGLOT PERSISTENCE: once the SAME conceptual
entity (e.g. "a user") has data spread across MULTIPLE different
databases (a document store for their profile, a graph database for
their social connections, a wide-column store for their activity feed),
keeping these representations SYNCHRONIZED becomes a genuine,
non-trivial engineering problem — a naive "just write to all of them"
approach reintroduces exactly the DISTRIBUTED TRANSACTION problem this
repo's Distributed Systems Theory Notes L04 covered (2PC's blocking
weakness, or a Saga's eventual-consistency window), now applied ACROSS
genuinely different database TECHNOLOGIES rather than just different
service instances of the same type.

EVENT-DRIVEN SYNCHRONIZATION (CHANGE DATA CAPTURE) is the most common
production pattern for keeping polyglot stores in sync: rather than an
application explicitly writing to every database synchronously (fragile,
and reintroducing 2PC-like coordination problems), a CHANGE DATA CAPTURE
(CDC) tool (e.g. Debezium) monitors ONE "source of truth" database's
write-ahead log and PUBLISHES each change as an EVENT (this repo's
Apache Kafka Notes and Event-Driven & Real-Time AI Systems Notes cover
the event-streaming infrastructure this relies on) — OTHER databases
(the graph database, the search index, the cache) SUBSCRIBE to this
event stream and update themselves ASYNCHRONOUSLY, achieving EVENTUAL
consistency across all the polyglot stores WITHOUT the application
needing to explicitly coordinate every write across every database
synchronously — this decouples "how many databases does this data
exist in" from the application's write path entirely.

THE CONSISTENCY WINDOW this introduces is a genuine, unavoidable
tradeoff: between a write happening in the SOURCE database and that
change propagating to EVERY dependent database via CDC, there's a
BRIEF window where different parts of the system see DIFFERENT,
temporarily-inconsistent views of the same underlying entity — this is
directly analogous to L06's Distributed Systems Theory-adjacent
eventual-consistency tradeoffs, but now specifically across
HETEROGENEOUS database technologies rather than replicas of the SAME
database — applications need to be DESIGNED with this window in mind
(e.g. showing a "processing..." state briefly, rather than assuming
instant cross-store consistency).

OPERATIONAL OVERHEAD is a real, often underestimated cost of polyglot
persistence: EVERY additional database technology in a system's
architecture requires its OWN operational expertise (backup/restore
procedures, monitoring, capacity planning, security patching,
on-call runbooks) — a team maintaining 5 different database
technologies has a genuinely larger operational surface area than a
team maintaining 1 or 2, and this cost needs to be WEIGHED against the
per-workload performance benefits L06's framework identifies, not
treated as a given, zero-cost architectural choice.

PRODUCTION USE CASE:
An e-commerce platform's PostgreSQL database is the SOURCE OF TRUTH for
product and order data — a CDC pipeline (Debezium, streaming through
Kafka) publishes every change as an event, which is consumed by: an
Elasticsearch index (kept in sync for full-text product search, this
repo's Full-Stack & Frontend Essentials Notes L07), a Redis cache
(invalidated/updated for fast product-detail page loads), and a
data warehouse (for business intelligence reporting) — the PostgreSQL
application code never explicitly writes to any of these THREE other
systems directly; they all update themselves asynchronously from the SAME event stream.

COMMON MISTAKES:
- Having application code explicitly, synchronously write to EVERY
  polyglot store on every operation — this reintroduces distributed-
  transaction coordination problems (partial failure: what if the write
  to the graph database succeeds but the write to the search index
  fails?) that a CDC-based, event-driven synchronization approach avoids
  by design.
- Failing to design the APPLICATION/UI layer to account for the
  eventual-consistency window between the source of truth and dependent
  stores — a user expecting a just-created item to IMMEDIATELY appear in
  search results (backed by an asynchronously-updated Elasticsearch
  index) may experience genuine, confusing-seeming delay if this window isn't accounted for in the UX design.
- Underestimating the OPERATIONAL cost of running many different
  database technologies simultaneously — each one requires genuine,
  ongoing operational investment (this repo's DevOps & SRE Practices
  Notes covers the incident-response/on-call burden this creates)
  that should be weighed explicitly against the specific per-workload
  performance benefits, not assumed to be "free" once the architecture is designed.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Change Data Capture architecture, illustrated
# ------------------------------------------------------------------
CDC_ARCHITECTURE = textwrap.dedent("""\
    Source of truth: PostgreSQL (orders, products)
      |
      v
    [Debezium CDC] reads the database's write-ahead log,
    publishes every INSERT/UPDATE/DELETE as an event
      |
      v
    [Kafka topic: "product-changes"]
      |
      +----------------+----------------+
      v                v                v
    [Elasticsearch] [Redis cache]   [Data warehouse]
    (search index    (invalidate/    (analytics/BI
     kept in sync)    update cache)   reporting)

    The application ONLY ever writes to PostgreSQL directly — every
    OTHER store updates itself ASYNCHRONOUSLY from the event stream,
    with NO explicit multi-database coordination in the application code.
""")

# ------------------------------------------------------------------
# 2. The consistency window, simulated
# ------------------------------------------------------------------
import time


class SourceOfTruthDB:
    def __init__(self):
        self.data: dict[str, dict] = {}
        self.pending_events: list[dict] = []

    def write(self, key: str, value: dict, timestamp: float):
        self.data[key] = value
        # CDC captures this change as an event, to be propagated ASYNCHRONOUSLY
        self.pending_events.append({"key": key, "value": value, "timestamp": timestamp})


class DependentSearchIndex:
    def __init__(self):
        self.indexed_data: dict[str, dict] = {}

    def consume_events(self, events: list[dict], processing_delay_applied: bool):
        for event in events:
            if not processing_delay_applied:   # simulate the CDC pipeline's real propagation delay
                self.indexed_data[event["key"]] = event["value"]


def consistency_window_demo():
    print(CDC_ARCHITECTURE)
    source_db = SourceOfTruthDB()
    search_index = DependentSearchIndex()

    source_db.write("product:123", {"name": "New Widget"}, timestamp=time.time())
    print("Write completed in source-of-truth database (PostgreSQL).")

    # Immediately checking the search index — the CDC event hasn't
    # propagated yet, a REAL, brief but non-zero window
    print(f"Immediately checking search index: {search_index.indexed_data.get('product:123')}")
    print("  -> NOT YET VISIBLE — this is the eventual-consistency window")
    print("     between the source of truth and every dependent, CDC-fed store.")

    # After the CDC pipeline processes the event (simulated)
    search_index.consume_events(source_db.pending_events, processing_delay_applied=False)
    print(f"\nAfter CDC propagation: {search_index.indexed_data.get('product:123')}")
    print("  -> NOW visible in the search index — the UI/application should")
    print("     be designed with this brief window in mind, rather than")
    print("     assuming instantaneous cross-store consistency.")


if __name__ == "__main__":
    consistency_window_demo()

"""
FINAL CONTEXT (capstone of this domain):
The measure of having internalized this domain isn't being able to name
Cassandra, DynamoDB, Neo4j, and a time-series database's individual
strengths in isolation — it's being able to look at a REAL system's
requirements, apply L06's decision framework to choose the right
database PER workload, and then correctly architect the SYNCHRONIZATION
between them (via CDC/event-driven patterns, per this lesson) while
consciously accounting for the eventual-consistency window and genuine
operational overhead this introduces — the difference between a
polyglot architecture that's a genuine engineering asset versus one
that's an unmanaged, synchronization-bug-prone liability comes down
entirely to getting THIS part right, not merely choosing good individual database technologies.
"""
