# ============================================================
# L07: Snowflake Fundamentals — Architecture, Warehouses, Snowpipe, Time Travel
# ============================================================
# WHAT: Snowflake's storage/compute separation architecture, virtual
#       warehouses (Snowflake's compute unit), micro-partitions (its
#       storage/pruning mechanism), Snowpipe (continuous ingestion), and
#       Time Travel (built-in historical data access).
# WHY: Snowflake is one of the dominant cloud data warehouses — its
#      architecture makes specific, deliberate tradeoffs (separating
#      storage from compute entirely) that explain both its cost model
#      and its performance characteristics, and that differ meaningfully
#      from Databricks' Spark-cluster-centric model (L05-L06).
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
Snowflake's foundational architectural decision: STORAGE and COMPUTE are
COMPLETELY SEPARATE and independently scalable. Data lives once, in
Snowflake-managed cloud storage (effectively S3/Azure Blob/GCS under the
hood), while any number of independent VIRTUAL WAREHOUSES can query that
SAME data simultaneously without contending for the same compute
resources. This is why Snowflake lets you run a heavy ETL warehouse and
a separate BI/dashboard warehouse against the same tables with zero
resource contention between them — a workload spike on one doesn't slow
down the other, because they're genuinely separate compute clusters.

A VIRTUAL WAREHOUSE is Snowflake's compute unit — sized in "T-shirt
sizes" (X-Small through 6X-Large, each roughly double the compute of the
previous size), billed per-second while running, and can AUTO-SUSPEND
after a period of inactivity and AUTO-RESUME on the next query — meaning
a warehouse used only during business hours can cost nothing overnight,
with no manual intervention required.

MICRO-PARTITIONS are Snowflake's automatic storage unit (roughly 50-500MB
of compressed data each) — Snowflake automatically tracks metadata (min/
max values per column) for every micro-partition, enabling PRUNING
(skipping irrelevant partitions during a query) WITHOUT you manually
defining partition keys, unlike the explicit partitioning schemes covered
in L02 for other systems. This is largely automatic, though clustering
keys (L08) let you influence it for very large tables.

SNOWPIPE is Snowflake's continuous, event-driven ingestion service — new
files landing in cloud storage trigger automatic, incremental loading
into a Snowflake table (via cloud storage event notifications, similar in
spirit to Databricks' Auto Loader from L06) without a scheduled batch job
polling for new files.

TIME TRAVEL lets you query a table AS IT EXISTED at any point within a
configurable retention window (1-90 days depending on edition) — useful
both for auditing/debugging ("what did this table look like before
yesterday's bad load?") and for recovering from an accidental bad write
via `UNDROP`/point-in-time restoration, without needing a separate manual
backup process.

PRODUCTION USE CASE:
A company runs a small X-Small warehouse for scheduled nightly ETL loads
and a separate Medium warehouse dedicated to BI dashboard queries during
business hours — both query the SAME underlying tables, but a slow
dashboard query never competes for compute with the nightly load job,
and each warehouse's auto-suspend means neither incurs cost when idle.

COMMON MISTAKES:
- Sizing one warehouse for the HEAVIEST workload and routing ALL query
  types through it — this wastes money on lightweight queries paying for
  oversized compute, and creates contention between workload types that
  separate, appropriately-sized warehouses would avoid entirely.
- Disabling or setting an overly long auto-suspend timeout "to avoid
  cold-start latency" without measuring the actual cost tradeoff — a
  warehouse idling for hours between queries at a large size is a direct,
  quantifiable cost leak.
- Relying on Time Travel as a substitute for a real backup/disaster
  recovery strategy — Time Travel's retention window is finite (and
  costs storage the longer it's set), and it doesn't protect against
  every failure mode a proper backup strategy would.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Storage/compute separation — the architectural foundation
# ------------------------------------------------------------------
ARCHITECTURE_NOTE = (
    "Three layers, each independently scalable: (1) Storage — compressed, "
    "columnar, Snowflake-managed, effectively unlimited and shared by "
    "everyone; (2) Compute — any number of virtual warehouses, each an "
    "independent cluster, scaled up/down/out without touching storage; "
    "(3) Cloud Services — query parsing/optimization, metadata, security, "
    "coordinating everything else. This is architecturally different from "
    "a traditional warehouse (or a Spark cluster) where compute and "
    "storage are tightly coupled to the same physical nodes."
)

# ------------------------------------------------------------------
# 2. Virtual warehouses — sizing and auto-suspend/resume
# ------------------------------------------------------------------
WAREHOUSE_DDL_EXAMPLE = textwrap.dedent("""\
    CREATE WAREHOUSE etl_warehouse
      WAREHOUSE_SIZE = 'MEDIUM'
      AUTO_SUSPEND = 60          -- suspend after 60 seconds of inactivity
      AUTO_RESUME = TRUE         -- automatically resume on the next query
      INITIALLY_SUSPENDED = TRUE;

    CREATE WAREHOUSE bi_warehouse
      WAREHOUSE_SIZE = 'SMALL'
      AUTO_SUSPEND = 300
      AUTO_RESUME = TRUE;

    -- Two SEPARATE compute pools querying the SAME underlying tables —
    -- a heavy ETL job on etl_warehouse never slows down a dashboard
    -- query running concurrently on bi_warehouse.
""")

WAREHOUSE_SIZE_SCALING = {
    "X-Small": "1 credit/hour — baseline unit",
    "Small": "2 credits/hour",
    "Medium": "4 credits/hour",
    "Large": "8 credits/hour",
    "X-Large": "16 credits/hour",
    "2X-Large": "32 credits/hour",
}
# Each size roughly DOUBLES compute (and cost) — sizing UP speeds up a
# single query's execution (more parallelism within that warehouse), but
# does NOT help if your bottleneck is actually QUEUING from too many
# concurrent queries — for that, scale OUT (multi-cluster warehouses,
# covered in L08) rather than up.

# ------------------------------------------------------------------
# 3. Micro-partitions and automatic pruning
# ------------------------------------------------------------------
MICROPARTITION_NOTE = textwrap.dedent("""\
    Every table is automatically divided into micro-partitions (~50-500MB
    compressed each) as data is loaded. Snowflake stores min/max metadata
    per column PER micro-partition. A query like:

        SELECT * FROM orders WHERE order_date = '2026-01-15';

    lets Snowflake's query optimizer PRUNE (skip reading) any
    micro-partition whose stored min/max for order_date doesn't overlap
    '2026-01-15' — similar in EFFECT to the manual partitioning from L02,
    but happening automatically based on natural data ordering, without
    you declaring a partition scheme up front. For very large tables
    where natural load order doesn't align with common query filters, a
    CLUSTERING KEY (L08) lets you influence this pruning explicitly.
""")

# ------------------------------------------------------------------
# 4. Snowpipe — continuous, event-driven ingestion
# ------------------------------------------------------------------
SNOWPIPE_EXAMPLE = textwrap.dedent("""\
    CREATE PIPE orders_pipe
      AUTO_INGEST = TRUE
    AS
      COPY INTO raw.orders
      FROM @orders_stage
      FILE_FORMAT = (TYPE = 'JSON');

    -- AUTO_INGEST relies on cloud storage event notifications (S3 Event
    -- Notifications -> SQS, in AWS) to trigger ingestion the moment a
    -- new file lands — no scheduled polling job required, directly
    -- analogous to Databricks Auto Loader's file-notification mechanism
    -- from L06, just Snowflake's native equivalent.
""")

# ------------------------------------------------------------------
# 5. Time Travel — historical queries and point-in-time recovery
# ------------------------------------------------------------------
TIME_TRAVEL_EXAMPLES = textwrap.dedent("""\
    -- Query a table as it existed 24 hours ago:
    SELECT * FROM orders AT (OFFSET => -60*60*24);

    -- Query as of a specific timestamp:
    SELECT * FROM orders AT (TIMESTAMP => '2026-01-14 09:00:00'::TIMESTAMP);

    -- Recover an accidentally dropped table entirely:
    UNDROP TABLE orders;

    -- Retention window is configurable per table/account (1 day on
    -- Standard edition, up to 90 days on Enterprise+) — longer retention
    -- means more historical query flexibility, at the cost of storing
    -- more historical micro-partition data (a real, billed storage cost).
""")


if __name__ == "__main__":
    print(ARCHITECTURE_NOTE, "\n")
    print(WAREHOUSE_DDL_EXAMPLE)
    print("Warehouse size scaling:")
    for size, credits in WAREHOUSE_SIZE_SCALING.items():
        print(f"  {size}: {credits}")
    print()
    print(MICROPARTITION_NOTE)
    print(SNOWPIPE_EXAMPLE)
    print(TIME_TRAVEL_EXAMPLES)

"""
PRODUCTION CONTEXT EXAMPLE:
A retail analytics team's Snowpipe continuously ingests point-of-sale
transaction files landing in S3 throughout the business day, feeding a
`raw.transactions` table queried by a separate, auto-suspending BI
warehouse for real-time dashboards — when a bad batch of test data
accidentally gets ingested, the team uses Time Travel to inspect the
table's state from an hour before the bad load, confirms the scope of
the problem, and corrects it, all without needing a separate backup
system or restore process.
"""
