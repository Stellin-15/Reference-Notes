# ============================================================
# L08: Capstone — Designing a Full Polyglot Persistence Architecture
# ============================================================
# WHAT: A capstone lesson designing a COMPLETE, concrete data
#       architecture for a realistic multi-feature platform, applying
#       L01-L07's database categories, decision framework, and
#       synchronization patterns together end to end.
# WHY: L01-L07 each covered one database technology or one piece of the
#      decision-making/synchronization puzzle. This capstone shows how
#      they combine into ONE coherent architecture for a real,
#      multi-faceted product.
# LEVEL: Capstone
# ============================================================

"""
CONCEPT OVERVIEW:
Designing the FULL data architecture for a realistic ride-sharing
platform, applying every lesson in this domain:

  1. REAL-TIME DRIVER LOCATION (L01's key-value model): a Redis-backed
     key-value store, keyed by driver ID, updated every few seconds —
     extreme write frequency, simple direct-lookup access pattern,
     no need for complex queries against this specific data.

  2. TRIP HISTORY AND RECEIPTS (L01's document model): MongoDB,
     storing each trip as a naturally nested document (route, fare
     breakdown, timestamps) — flexible schema accommodates different
     trip types (standard, shared, premium) without rigid normalization.

  3. RIDE EVENT LOG (L02's wide-column model): Cassandra, partitioned
     by driver ID and by rider ID (TWO denormalized tables, per L02's
     query-first design), handling the platform's highest write-volume
     data — every location ping, every status change, during every active ride.

  4. FRAUD/COLLUSION DETECTION (L04's graph model): Neo4j, modeling
     riders, drivers, payment methods, and devices as nodes with
     relationships — multi-hop traversal queries identify suspicious
     clusters (e.g. a "rider" and "driver" account sharing a device
     fingerprint) that would be prohibitively complex as relational self-joins.

  5. PLATFORM METRICS AND MONITORING (L05's time-series model):
     Prometheus/a time-series database tracking ride volume, average
     wait times, and surge-pricing multipliers over time — retained at
     full resolution briefly, downsampled for long-term trend analysis.

  6. BILLING AND PAYOUTS (L06's "sometimes the answer is relational"
     lesson): PostgreSQL, specifically BECAUSE this data requires
     genuine ACID transactions (a payment must atomically debit the
     rider and credit the driver) and complex, joined financial reporting queries.

  7. SYNCHRONIZATION (L07's CDC pattern): PostgreSQL (billing) acts as
     one source of truth feeding a data warehouse for BI reporting;
     MongoDB's trip records feed Elasticsearch for rider-facing trip
     search — all via Debezium-style CDC through Kafka, avoiding any
     synchronous, application-level multi-database writes.

WHY THIS SEVEN-DATABASE ARCHITECTURE IS JUSTIFIED (not "over-
engineering for its own sake"): each database was chosen because its
OWN workload's dominant access pattern and consistency requirement
(L06's framework) genuinely mismatches the other six — this is the
practical payoff of the decision discipline this domain builds,
distinguishing a deliberately-architected polyglot system from
technology-chasing accumulation of unnecessary complexity.

PRODUCTION USE CASE:
This is, in outline, genuinely representative of how major ride-sharing
and delivery platforms (Uber, DoorDash, Lyft) structure their actual
production data architectures — publicly available engineering
writeups from these companies describe very similar polyglot
architectures, each database chosen for a specific, identified workload
mismatch with a single, unified alternative.

COMMON MISTAKES:
- Building this level of polyglot complexity WITHOUT the workload actually
  justifying it — a small startup's MVP with modest traffic likely
  doesn't need seven different database technologies; this capstone's
  complexity is justified specifically by the SCALE and DIVERSITY of
  access patterns a mature ride-sharing platform actually has.
- Choosing every database technology UPFRONT before understanding actual
  access patterns — most real systems (including the companies this
  architecture is modeled on) START simpler (often a single relational
  database) and MIGRATE specific workloads to specialized databases
  ONLY once a genuine, measured performance/scale mismatch is identified
  — polyglot architecture is typically an EVOLUTION, not a day-one design decision.
- Underinvesting in the SYNCHRONIZATION layer (L07) relative to the
  individual database choices — a beautifully chosen set of seven
  databases with a fragile, ad-hoc synchronization mechanism between
  them is a worse system than a simpler architecture with fewer,
  well-synchronized databases.
"""

import textwrap


FULL_ARCHITECTURE = textwrap.dedent("""\
    Ride-sharing platform — polyglot persistence architecture:

    +----------------------------------------------------------------+
    | Redis (Key-Value, L01): real-time driver locations                |
    | Extreme write frequency, simple lookup by driver ID                |
    +----------------------------------------------------------------+
    | MongoDB (Document, L01): trip history and receipts                 |
    | Flexible nested schema per trip type                               |
    +----------------------------------------------------------------+
    | Cassandra (Wide-Column, L02): ride event log                       |
    | Partitioned by driver_id AND rider_id (two denormalized tables)     |
    +----------------------------------------------------------------+
    | Neo4j (Graph, L04): fraud/collusion detection                      |
    | Multi-hop traversal across riders/drivers/devices/payment methods   |
    +----------------------------------------------------------------+
    | Time-series DB (L05): platform metrics                             |
    | Ride volume, wait times, surge pricing over time, downsampled       |
    +----------------------------------------------------------------+
    | PostgreSQL (Relational, L06): billing and payouts                  |
    | ACID transactions, complex joined financial reporting               |
    +----------------------------------------------------------------+
              |
              v  (Change Data Capture, L07, via Debezium + Kafka)
    +----------------------------------------------------------------+
    | Data warehouse (BI reporting)  |  Elasticsearch (trip search)      |
    | fed asynchronously from PostgreSQL and MongoDB's CDC event streams  |
    +----------------------------------------------------------------+
""")

DATABASE_JUSTIFICATION = {
    "Redis": "Extreme write frequency + simple key lookup -> no other option fits this shape as cheaply",
    "MongoDB": "Flexible, evolving trip-type schema -> rigid relational normalization would add friction",
    "Cassandra": "Highest write-volume data on the platform -> needs horizontal write scaling",
    "Neo4j": "Fraud rings ARE a multi-hop graph traversal problem -> SQL self-joins degrade badly here",
    "Time-series DB": "Time-range queries over metrics -> needs downsampling/retention this data pattern enables",
    "PostgreSQL": "Money movement needs ACID guarantees -> the ONE place strong consistency is non-negotiable",
}


if __name__ == "__main__":
    print(FULL_ARCHITECTURE)
    print("Why each database is justified for ITS specific workload:\n")
    for db, justification in DATABASE_JUSTIFICATION.items():
        print(f"  {db}: {justification}")

"""
FINAL CONTEXT (capstone of this domain):
The measure of having internalized this domain isn't naming Cassandra,
DynamoDB, Neo4j, and time-series databases correctly on a resume — it's
being able to look at a REAL, multi-faceted product's actual workloads,
apply L06's decision framework to each one independently (not
uniformly), recognize where the honest answer is still "just use
PostgreSQL," and design the L07 synchronization layer that lets these
choices coexist without becoming an unmanageable, inconsistent mess —
this is the genuine skill that separates a thoughtfully polyglot
architecture from one that merely accumulated trendy technologies over time.
"""
