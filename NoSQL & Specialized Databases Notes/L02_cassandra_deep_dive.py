# ============================================================
# L02: Cassandra Deep Dive — Wide-Column Storage at Massive Write Scale
# ============================================================
# WHAT: Cassandra's core architecture — the partition key/clustering key
#       data model, its ring-based, leaderless (masterless) replication
#       architecture, and why "query-first" schema design is mandatory
#       rather than optional.
# WHY: L01 introduced wide-column stores conceptually. This lesson goes
#       deep on Cassandra specifically — the most widely deployed
#       wide-column database, and a direct, real application of this
#       repo's Distributed Systems Theory Notes' quorum/consensus concepts.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
CASSANDRA'S DATA MODEL centers on the PARTITION KEY and CLUSTERING KEY:
a table's PRIMARY KEY is composed of one or more PARTITION KEY columns
(which determine WHICH NODE(S) in the cluster store this data — all rows
sharing a partition key are stored TOGETHER) plus optional CLUSTERING
KEY columns (which determine the SORT ORDER of rows WITHIN a partition).
This is a fundamentally different design goal than a relational
database's normalized schema — Cassandra's model is built around making
ONE SPECIFIC query pattern (fetch by partition key, optionally filtered/
sorted by clustering key) extremely fast, at the cost of NOT supporting
arbitrary ad-hoc queries (like a relational JOIN) efficiently at all.

"QUERY-FIRST" SCHEMA DESIGN is Cassandra's central, non-negotiable
design discipline: you design your TABLE STRUCTURE based on the EXACT
QUERIES your application needs to run, often DUPLICATING the same
underlying data across MULTIPLE tables, each structured for a specific
query pattern (a practice called DENORMALIZATION) — this is the OPPOSITE
of relational database design's normalization-first approach.
A common, genuinely important consequence: if you need to query the
SAME data by two DIFFERENT keys (e.g. "orders by customer ID" AND
"orders by order date"), you typically create TWO SEPARATE tables, each
with a partition key matching one specific access pattern, and write to
BOTH on every insert — Cassandra deliberately does NOT support efficient
ad-hoc queries against arbitrary columns the way SQL's flexible WHERE
clauses do.

RING-BASED, LEADERLESS ARCHITECTURE: unlike Raft/Paxos-based systems
(this repo's Distributed Systems Theory Notes L02-L03) that elect a
single leader, Cassandra uses CONSISTENT HASHING (this repo's System
Design Case Studies Notes L22 covers this concept generally) to
distribute data across a RING of nodes with NO single leader — ANY node
can accept a read or write for ANY key (forwarding internally to the
correct replica nodes as needed), which is a deliberate availability-
maximizing design choice: there's no single leader whose failure could
create a coordination bottleneck or temporary unavailability window.

TUNABLE CONSISTENCY PER QUERY (directly implementing this repo's
Distributed Systems Theory Notes L06's N/R/W quorum model): Cassandra
exposes CONSISTENCY LEVELS like `ONE`, `QUORUM`, `ALL` directly in each
individual query — a single application can use `ONE` (fast, low
consistency guarantee) for a low-stakes read and `QUORUM` (slower, but
guarantees seeing the latest write given a `QUORUM` write) for a
critical read, choosing the tradeoff PER OPERATION rather than for the
entire database uniformly.

PRODUCTION USE CASE:
Apple's iMessage and Netflix's viewing-history/recommendation
infrastructure both run on Cassandra clusters specifically because of
its ability to handle EXTREMELY HIGH write throughput (constant message
delivery, constant viewing-progress updates) across globally distributed
data centers with no single point of failure — the query-first schema
design means each service maintains multiple denormalized tables, one
per actual query pattern the application needs, rather than a single
normalized schema.

COMMON MISTAKES:
- Designing a Cassandra schema the way you'd design a normalized
  relational schema (avoiding duplication, expecting flexible ad-hoc
  queries) — this fundamentally fights against Cassandra's actual
  design, producing a schema that performs poorly for the queries the
  application actually needs.
- Choosing a partition key that creates a "HOT PARTITION" — e.g.
  partitioning by a value with extremely skewed distribution (like a
  single global counter, or a celebrity user ID receiving vastly more
  traffic than others) concentrates load on a SMALL number of physical
  nodes, defeating the horizontal-scaling benefit the partition-key model is meant to provide.
- Using a strong consistency level (`ALL`) for every single query "to be
  safe," without considering the availability/latency cost — this
  negates much of Cassandra's core value proposition (high availability,
  tunable per-operation tradeoffs) by uniformly choosing the
  slowest/least-available option regardless of that specific query's actual requirements.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Query-first schema design — denormalized tables per query pattern
# ------------------------------------------------------------------
QUERY_FIRST_SCHEMA_EXAMPLE = textwrap.dedent("""\
    -- Cassandra CQL: TWO separate, denormalized tables for the SAME
    -- underlying order data, each structured for a DIFFERENT query pattern

    -- Table 1: optimized for "get all orders for a given customer"
    CREATE TABLE orders_by_customer (
        customer_id UUID,
        order_date TIMESTAMP,
        order_id UUID,
        total DECIMAL,
        PRIMARY KEY (customer_id, order_date)
        -- partition key: customer_id (all of a customer's orders live together)
        -- clustering key: order_date (sorted within that partition)
    );

    -- Table 2: optimized for "get all orders on a given date" (a
    -- DIFFERENT access pattern, requiring a DIFFERENT partition key)
    CREATE TABLE orders_by_date (
        order_date TIMESTAMP,
        order_id UUID,
        customer_id UUID,
        total DECIMAL,
        PRIMARY KEY (order_date, order_id)
    );

    -- On every INSERT, the application writes to BOTH tables — this
    -- DUPLICATION is deliberate and expected, unlike a normalized
    -- relational schema where this would be considered a design flaw.
""")

# ------------------------------------------------------------------
# 2. Tunable consistency levels per query
# ------------------------------------------------------------------
TUNABLE_CONSISTENCY_EXAMPLE = textwrap.dedent("""\
    -- Low-stakes read: fast, minimal consistency guarantee
    SELECT * FROM product_view_counts WHERE product_id = ?
    -- CONSISTENCY LEVEL: ONE (only 1 replica needs to respond)

    -- Critical read: slower, but guarantees seeing the latest QUORUM write
    SELECT * FROM account_balances WHERE account_id = ?
    -- CONSISTENCY LEVEL: QUORUM (majority of replicas must agree)

    -- Both queries run against the SAME Cassandra cluster — the
    -- consistency/availability tradeoff is chosen PER QUERY, directly
    -- implementing the N/R/W quorum model (Distributed Systems Theory
    -- Notes L06) rather than a single, system-wide setting.
""")

# ------------------------------------------------------------------
# 3. Hot partition — a concrete illustration of the anti-pattern
# ------------------------------------------------------------------
def simulate_partition_load(partition_key_choice: str, sample_data: list[dict]) -> dict:
    load_per_partition: dict[str, int] = {}
    for record in sample_data:
        key = record[partition_key_choice]
        load_per_partition[key] = load_per_partition.get(key, 0) + 1
    return load_per_partition


def hot_partition_demo():
    sample_events = (
        [{"celebrity_id": "celeb_1", "user_id": f"user_{i}"} for i in range(9000)]  # celeb hot spot
        + [{"celebrity_id": "celeb_2", "user_id": f"user_{i}"} for i in range(500)]
        + [{"celebrity_id": "celeb_3", "user_id": f"user_{i}"} for i in range(500)]
    )

    print("\nPartitioning events by 'celebrity_id' (a POOR choice — highly skewed):")
    load = simulate_partition_load("celebrity_id", sample_events)
    for key, count in load.items():
        print(f"  Partition '{key}': {count} events")
    print("  -> celeb_1's partition receives 9x the load of the others —")
    print("     this SINGLE partition (and the physical node(s) hosting it)")
    print("     becomes a bottleneck, regardless of how many total nodes")
    print("     the cluster has, defeating horizontal scaling for this hot key.")


if __name__ == "__main__":
    print(QUERY_FIRST_SCHEMA_EXAMPLE)
    print(TUNABLE_CONSISTENCY_EXAMPLE)
    hot_partition_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
Netflix's Cassandra-backed viewing-history system maintains SEPARATE,
denormalized tables for "viewing history by user" (partitioned by user
ID, for the personal viewing-history page) and "viewing events by
content ID" (partitioned by content ID, for aggregate popularity
analytics) — a single normalized table simply could not serve BOTH
access patterns efficiently at Netflix's write volume, which is exactly
why Cassandra's query-first, denormalized design philosophy — a
deliberate tradeoff, not a limitation to work around — is the correct
fit for this specific class of massive-write-volume, access-pattern-driven workload.
"""
