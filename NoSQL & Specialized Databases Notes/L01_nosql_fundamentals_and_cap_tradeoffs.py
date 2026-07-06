# ============================================================
# L01: NoSQL Fundamentals and CAP Tradeoffs
# ============================================================
# WHAT: Why NoSQL databases exist at all, the four major NoSQL data
#       models (key-value, document, wide-column, graph), and how CAP
#       theorem's tradeoffs manifest concretely in real NoSQL database choices.
# WHY: This repo's SQL Notes and Full-Stack & Frontend Essentials Notes
#      L06 (MongoDB) each cover ONE database in depth. This new domain
#      surveys the BROADER NoSQL landscape (Cassandra, DynamoDB, Neo4j,
#      time-series DBs) and, critically, the DECISION FRAMEWORK for
#      choosing among them.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
NOSQL DATABASES emerged specifically to address workloads where a
traditional RELATIONAL database's constraints (a FIXED SCHEMA, strong
ACID transactions across arbitrary joins, vertical-scaling-oriented
architecture) become a genuine LIMITATION rather than a benefit — at
massive write scale (needing to distribute writes across many machines
horizontally), for RAPIDLY EVOLVING or inherently non-tabular data
shapes (nested documents, graphs, wide sparse columns), or when
AVAILABILITY under network partition matters more than immediate strong
consistency for a specific workload (this repo's Distributed Systems
Theory Notes L06 covers the underlying quorum math this section builds on directly).

THE FOUR MAJOR NOSQL DATA MODELS, each optimized for a genuinely
DIFFERENT access pattern: KEY-VALUE stores (Redis, DynamoDB in its
simplest use) — the simplest model, extremely fast for direct
lookups by a known key, but with NO query capability beyond that key;
DOCUMENT stores (MongoDB, this repo's Full-Stack & Frontend Essentials
Notes L06) — semi-structured JSON-like documents, good for nested,
naturally-hierarchical data with flexible schema; WIDE-COLUMN stores
(Cassandra, HBase) — optimized for MASSIVE write throughput and
querying by a known partition key across huge, sparse datasets;
GRAPH databases (Neo4j) — optimized SPECIFICALLY for traversing
RELATIONSHIPS between entities efficiently, a query pattern relational
JOINs handle progressively worse as traversal depth increases.

CAP THEOREM IN PRACTICE — WHY MOST NOSQL DATABASES ARE "AP" OR
TUNABLE, NOT STRICTLY "CP": CAP theorem states a distributed system can
only guarantee two of Consistency, Availability, and Partition
tolerance at once — since network Partitions are a real, unavoidable
possibility in any distributed system (you can't simply "opt out" of P),
the PRACTICAL choice is really between CP (sacrifice availability during
a partition, favoring consistency) and AP (sacrifice strict consistency
during a partition, favoring availability) — Cassandra and DynamoDB were
BOTH explicitly designed as AP-leaning systems (per their lineage from
Amazon's Dynamo paper), with TUNABLE consistency (this repo's
Distributed Systems Theory Notes L06's N/R/W quorum model) letting
individual operations choose a STRONGER consistency point when needed,
at a cost to availability/latency for THOSE specific operations.

CHOOSING A DATA MODEL IS A DECISION ABOUT ACCESS PATTERNS, NOT JUST
DATA SHAPE: the same underlying data (e.g. a social network) could be
modeled as documents (each user's profile as one document), wide-column
(user activity feeds partitioned by user ID), OR a graph (the
follow/friend relationships themselves) — the RIGHT choice depends on
which access pattern is actually MOST FREQUENT and PERFORMANCE-CRITICAL
for the specific system being built — a genuinely different lens than
"which model best represents this data conceptually."

PRODUCTION USE CASE:
A social media platform uses MULTIPLE NoSQL databases simultaneously,
each for a different access pattern: DynamoDB (key-value/document
hybrid) for fast, direct user-profile lookups by user ID; Cassandra
(wide-column) for write-heavy activity feeds partitioned by user;
and Neo4j (graph) SPECIFICALLY for "friends of friends" and
recommendation-relevant relationship-traversal queries that would be
prohibitively slow as repeated SQL JOINs at this scale — a single
POLYGLOT PERSISTENCE architecture (covered further in L07), not a
single "best" database serving every need.

COMMON MISTAKES:
- Choosing a NoSQL database because "it's what modern systems use,"
  without a specific access-pattern requirement it actually solves
  better than a relational database — many workloads are genuinely
  well-served by PostgreSQL/MySQL (this repo's SQL Notes), and adopting
  NoSQL without a concrete need adds real operational complexity for
  little to no actual benefit.
- Modeling relationship-heavy data (social graphs, recommendation
  networks) in a document or wide-column store when a GRAPH database
  would handle the actual dominant query pattern (multi-hop traversal)
  far more efficiently — this is one of the clearest cases where data
  MODEL choice directly determines whether a common query is fast or prohibitively slow.
- Assuming ALL NoSQL databases sacrifice consistency uniformly — modern
  systems like Cassandra and DynamoDB offer TUNABLE consistency per
  operation (Distributed Systems Theory Notes L06); treating "NoSQL"
  as synonymous with "eventually consistent, no exceptions" misses this
  genuinely important nuance.
"""

import textwrap


# ------------------------------------------------------------------
# 1. The four NoSQL data models and their ideal access patterns
# ------------------------------------------------------------------
DATA_MODEL_COMPARISON = textwrap.dedent("""\
    Key-Value (Redis, DynamoDB simple mode):
      Ideal for: direct lookup by a known key, caching, session storage
      Query capability: essentially NONE beyond get/set by key
      Example: cache[user_id] -> user session data

    Document (MongoDB):
      Ideal for: nested, hierarchical, flexible-schema data
      Query capability: rich queries within/across documents, indexing on nested fields
      Example: a full user profile with nested address, preferences, order history

    Wide-Column (Cassandra, HBase):
      Ideal for: massive write throughput, querying by a KNOWN partition key
      Query capability: efficient for partition-key lookups; poor for ad-hoc queries
      Example: time-ordered activity events, partitioned by user_id

    Graph (Neo4j):
      Ideal for: multi-hop RELATIONSHIP traversal (friends-of-friends, recommendations)
      Query capability: extremely efficient traversal; poor fit for tabular aggregation
      Example: "find all products purchased by friends of friends who also liked X"
""")

# ------------------------------------------------------------------
# 2. CAP theorem — AP vs CP, concretely
# ------------------------------------------------------------------
def cap_tradeoff_illustration():
    print("During a network partition, a distributed database must choose:\n")
    print("  CP (Consistency + Partition tolerance):")
    print("    Reject requests to the MINORITY partition (return an error)")
    print("    rather than risk returning stale/conflicting data.")
    print("    Example lineage: traditional consensus-backed systems (etcd, ZooKeeper)")
    print()
    print("  AP (Availability + Partition tolerance):")
    print("    CONTINUE serving requests on BOTH sides of the partition,")
    print("    accepting that they may temporarily diverge — reconciled")
    print("    later (e.g. via vector clocks, this repo's Distributed")
    print("    Systems Theory Notes L05) once the partition heals.")
    print("    Example lineage: Cassandra, DynamoDB (both from Amazon's Dynamo paper)")


# ------------------------------------------------------------------
# 3. Choosing a data model based on the DOMINANT access pattern
# ------------------------------------------------------------------
def choose_data_model(dominant_access_pattern: str) -> str:
    decision_map = {
        "direct lookup by known key, high throughput": "Key-Value (Redis/DynamoDB)",
        "flexible, nested document structure": "Document (MongoDB)",
        "massive write volume, partition-key queries": "Wide-Column (Cassandra)",
        "multi-hop relationship traversal": "Graph (Neo4j)",
    }
    return decision_map.get(dominant_access_pattern, "Consider whether a relational database actually fits better")


if __name__ == "__main__":
    print(DATA_MODEL_COMPARISON)
    cap_tradeoff_illustration()

    print("\nData model selection based on DOMINANT access pattern:")
    for pattern in ["direct lookup by known key, high throughput",
                    "multi-hop relationship traversal"]:
        print(f"  '{pattern}' -> {choose_data_model(pattern)}")

"""
PRODUCTION CONTEXT EXAMPLE:
A ride-sharing platform stores real-time driver location data in a
key-value store (Redis) for extremely fast direct lookups by driver ID,
trip history in a document store (MongoDB) for its naturally nested,
evolving schema (different trip types have different fields), ride
event logs in a wide-column store (Cassandra) for massive write
throughput during peak hours, and rider/driver relationship data (for
fraud detection — identifying suspicious clusters of accounts) in a
graph database (Neo4j) — FOUR different NoSQL data models within one
platform, each chosen specifically for its own dominant access pattern
rather than any single database serving every one of these genuinely different needs.
"""
