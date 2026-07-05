# ============================================================
# L05: Trino Fundamentals — Distributed SQL Query Engine, Connectors
# ============================================================
# WHAT: Trino's architecture (coordinator/worker model, cost-based query
#       planning) and its defining feature — CONNECTORS that let ONE SQL
#       query join data across genuinely different systems (a data lake,
#       a relational database, Kafka) as if they were one database.
# WHY: Feature platforms (L01-L04) need a query engine that can read
#      from wherever raw data actually lives — often multiple systems at
#      once (an on-prem Hadoop cluster, cloud object storage, a
#      warehouse). Trino is the dominant open-source engine built
#      specifically for this federated-query use case.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
Trino (formerly PrestoSQL) is a DISTRIBUTED SQL QUERY ENGINE, not a
database — it has NO storage of its own. Every query it runs reads data
FROM other systems via CONNECTORS, and Trino's job is purely
QUERY EXECUTION: parsing SQL, building a distributed execution plan, and
coordinating many WORKER nodes to execute that plan in parallel,
returning results to the client. This "compute separate from storage"
design (distinct from a traditional database where the same system owns
both) is what lets Trino query a data lake, a relational database, and a
message queue's recent messages ALL WITHIN ONE SQL QUERY.

The COORDINATOR/WORKER architecture: a single COORDINATOR node receives
the SQL query, parses it, and — critically — builds a QUERY PLAN using
COST-BASED OPTIMIZATION (estimating, from table statistics, the cheapest
execution strategy: which table to scan first, which join algorithm to
use, how to distribute work). The coordinator then DISTRIBUTES stages of
that plan to many WORKER nodes, which execute in parallel and stream
results back up through the plan's stages to the coordinator, which
returns the final result to the client.

A CONNECTOR is Trino's plugin mechanism for talking to a specific
external system — the Hive connector reads Iceberg/Parquet/ORC files
from HDFS/S3/GCS (directly relevant to L06-L07's lakehouse coverage),
the PostgreSQL/MySQL connectors query relational databases directly, the
Kafka connector can query recent Kafka topic messages as if they were a
table. FEDERATED QUERIES join data ACROSS connectors in one SQL
statement — e.g. joining a `customers` table living in PostgreSQL
against a `transactions` table living as Iceberg files on S3, in one
query, with Trino handling the cross-system join transparently.

PRODUCTION USE CASE:
A feature platform (L01-L04) needs to compute a feature joining a
customer's CURRENT profile (which lives in an operational PostgreSQL
database, since it's actively read/written by the application) against
their HISTORICAL transaction data (which lives as Iceberg files in a
data lake, since it's append-heavy and queried in bulk for feature
computation) — a single Trino query joins both sources directly, without
first ETL'ing PostgreSQL data into the lake or vice versa just to make
them queryable together.

COMMON MISTAKES:
- Treating Trino as a replacement for a transactional database — Trino
  has no ACID transaction support of its own and is built for ANALYTICAL
  (read-heavy, large-scan) queries, not high-frequency single-row
  read/write operational workloads.
- Writing a federated query that joins a LARGE table from one connector
  against a LARGE table from another without considering the actual
  data volume moving across the network between systems — federated
  joins are powerful but not free; Trino still has to pull data from
  each source system's connector, and a poorly-planned cross-system join
  on huge tables can be far slower than joining within a single
  co-located system.
- Not providing accurate table statistics to Trino's cost-based
  optimizer (common with Iceberg tables that haven't had ANALYZE run) —
  this leads to poor query plans (wrong join order, wrong join
  algorithm) that a stats-aware plan would have avoided.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Coordinator/worker architecture
# ------------------------------------------------------------------
ARCHITECTURE_NOTE = (
    "Coordinator: receives SQL, parses it, builds a cost-based query "
    "plan, schedules plan STAGES onto workers, and returns final "
    "results to the client — the coordinator itself does NOT execute "
    "the bulk of the actual data scanning/processing.\n\n"
    "Workers: execute the plan's stages in parallel — each worker "
    "handles a SPLIT (a chunk of the data being scanned), and results "
    "flow between stages (e.g. from a scan stage into a join stage) "
    "via Trino's internal exchange mechanism, without ever touching disk "
    "for intermediate results in the common case (in-memory streaming "
    "between stages when possible)."
)

# ------------------------------------------------------------------
# 2. Federated queries across connectors
# ------------------------------------------------------------------
FEDERATED_QUERY_EXAMPLE = textwrap.dedent("""\
    -- ONE query joining a PostgreSQL-backed operational table against
    -- an Iceberg-backed data-lake table — Trino handles pulling data
    -- from BOTH connectors and performing the join, transparently to
    -- the query author.
    SELECT
        c.customer_id,
        c.current_tier,          -- from the "postgres" catalog (operational DB)
        SUM(t.amount) AS total_spend_90d
    FROM postgres.public.customers c
    JOIN iceberg.lake.transactions t
        ON c.customer_id = t.customer_id
    WHERE t.transaction_date >= DATE '2025-10-01'
    GROUP BY c.customer_id, c.current_tier;

    -- "postgres" and "iceberg" here are CATALOG names, each backed by a
    -- different CONNECTOR configured in Trino's catalog properties —
    -- the query syntax itself doesn't distinguish "local" vs "federated"
    -- joins at all; it's just standard SQL against two catalogs.
""")

# ------------------------------------------------------------------
# 3. Connector configuration
# ------------------------------------------------------------------
CATALOG_CONFIG_EXAMPLE = textwrap.dedent("""\
    # etc/catalog/iceberg.properties — configures the "iceberg" catalog
    connector.name=iceberg
    hive.metastore.uri=thrift://metastore:9083
    iceberg.catalog.type=hive_metastore

    # etc/catalog/postgres.properties — configures the "postgres" catalog
    connector.name=postgresql
    connection-url=jdbc:postgresql://db-host:5432/app_db
    connection-user=trino_readonly
    connection-password=${ENV:TRINO_PG_PASSWORD}

    # Once both are configured, queries reference them as
    # catalog.schema.table — e.g. iceberg.lake.transactions,
    # postgres.public.customers — exactly as shown in the federated
    # query above.
""")

# ------------------------------------------------------------------
# 4. Cost-based optimization — why table statistics matter
# ------------------------------------------------------------------
STATISTICS_NOTE = textwrap.dedent("""\
    ANALYZE iceberg.lake.transactions;

    -- Without accurate statistics (row counts, distinct value counts,
    -- data size per column), Trino's cost-based optimizer must GUESS at
    -- table sizes when choosing a join strategy (e.g. broadcast a small
    -- table to every worker vs a full shuffle join for two large
    -- tables) — a wrong guess can mean broadcasting a much-larger-than-
    -- expected table, causing significant unnecessary network/memory
    -- pressure across the whole cluster. Running ANALYZE periodically
    -- (especially after large data loads) keeps the optimizer's cost
    -- estimates accurate.
""")

# ------------------------------------------------------------------
# 5. When Trino is (and isn't) the right tool
# ------------------------------------------------------------------
TRINO_FIT_COMPARISON = {
    "Good fit": "Analytical queries over large volumes of data, "
        "especially FEDERATED across multiple systems; ad-hoc "
        "exploration by data scientists; feature-computation queries "
        "reading from a lakehouse (L06-L07).",
    "Poor fit": "High-frequency, single-row transactional read/write "
        "workloads (use the operational database directly); use cases "
        "needing Trino's own ACID guarantees on writes (Trino can WRITE "
        "to Iceberg tables, but the transactional guarantees come from "
        "Iceberg's table format, L06, not from Trino as a database engine).",
}


if __name__ == "__main__":
    print(ARCHITECTURE_NOTE, "\n")
    print(FEDERATED_QUERY_EXAMPLE)
    print(CATALOG_CONFIG_EXAMPLE)
    print(STATISTICS_NOTE)
    print("=== When Trino fits ===")
    for fit, note in TRINO_FIT_COMPARISON.items():
        print(f"{fit}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A feature platform spanning an on-prem Hadoop cluster (historical data,
years of accumulated transactions) and a newer cloud data lake (recent
data, migrated incrementally) uses Trino with BOTH a Hive connector
(pointed at the on-prem HDFS/Iceberg tables) and an Iceberg connector
(pointed at the cloud object storage tables) configured as separate
catalogs — feature computation queries transparently join across both,
letting the platform team migrate data to the cloud gradually without
ever blocking feature computation on the migration being "complete,"
since Trino queries both locations as needed throughout the transition.
"""
