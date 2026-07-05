# ============================================================
# L05: Databricks Fundamentals — Workspace, Clusters, Delta Lake, Unity Catalog
# ============================================================
# WHAT: Databricks' core building blocks — the workspace/notebook model,
#       cluster types and sizing, Delta Lake (the storage format
#       underlying almost everything in Databricks), and Unity Catalog
#       (centralized governance across workspaces).
# WHY: Databricks is one of the dominant platforms for large-scale data
#      engineering and ML — it's built on Apache Spark (see this repo's
#      Apache Spark Notes for Spark internals) but adds a managed
#      workspace, Delta Lake's ACID guarantees on top of cheap object
#      storage, and unified governance that plain open-source Spark
#      doesn't provide out of the box.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
A DATABRICKS WORKSPACE is the top-level container: notebooks, clusters,
jobs, and data all live within one. Notebooks support multiple languages
per cell (Python, SQL, Scala, R) and can be attached to a running cluster
for interactive development, or run non-interactively as part of a
scheduled Job.

CLUSTERS are the actual Spark compute. Two cluster modes matter most:
ALL-PURPOSE clusters (long-running, shared, used for interactive
notebook development — billed while running, so left-running idle
clusters are a real cost leak) and JOB clusters (spun up automatically
for a scheduled job's duration and torn down immediately after — the
correct choice for production pipelines, since you never pay for idle
time). Cluster SIZING (node type, autoscaling min/max workers) directly
trades cost against job runtime, and Databricks' autoscaling can adjust
worker count DURING a job based on actual load.

DELTA LAKE is an open-source storage layer (Parquet files + a
transaction log) that adds ACID transactions, schema enforcement, and
TIME TRAVEL to plain object storage (S3/ADLS/GCS) — this is what
upgrades a "data lake" (files with no transactional guarantees) into a
"lakehouse" (warehouse-like guarantees on top of cheap lake storage).
Nearly every Databricks table you create by default is a Delta table.

UNITY CATALOG is Databricks' centralized governance layer: one place to
manage table/column-level permissions, data lineage, and audit logs
ACROSS multiple workspaces — solving the problem of governance
previously being siloed per-workspace (each with its own separate
permission model) before Unity Catalog existed.

PRODUCTION USE CASE:
A data engineering job runs as a scheduled Databricks Job on an
auto-terminating JOB cluster sized with autoscaling (2-8 workers) — the
cluster spins up only for the job's duration, autoscales up during a
heavy Spark shuffle stage, and terminates immediately after, so cost is
proportional to actual usage rather than a fixed always-on cluster size.

COMMON MISTAKES:
- Running production, scheduled workloads on an ALL-PURPOSE cluster
  instead of a JOB cluster — this pays for idle time between runs and
  couples production stability to whatever else is running on that
  shared cluster.
- Not understanding that Delta Lake's transaction log (`_delta_log/`) is
  what provides ACID guarantees — manually deleting/modifying the
  underlying Parquet files without going through Delta's own APIs
  corrupts the table's transactional consistency.
- Managing permissions at the individual workspace level instead of
  through Unity Catalog when running multiple workspaces — this creates
  permission drift and makes auditing "who can access what" across the
  organization far harder than it needs to be.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Cluster types and sizing
# ------------------------------------------------------------------
CLUSTER_TYPE_COMPARISON = {
    "All-purpose cluster": "Long-running, shared across users/notebooks "
        "for interactive development. Billed continuously while running "
        "— must be manually or auto-terminated after idle time to avoid "
        "wasted cost.",
    "Job cluster": "Created automatically when a scheduled Job starts, "
        "destroyed automatically when it finishes. The correct choice "
        "for ALL production pipelines — cost is proportional to actual "
        "work done, never idle.",
    "SQL warehouse": "A specialized compute type optimized for SQL "
        "workloads (BI tool connections, ad-hoc SQL queries) with faster "
        "startup and auto-scaling tuned for concurrent query patterns "
        "rather than long-running Spark jobs.",
}

CLUSTER_CONFIG_EXAMPLE = textwrap.dedent("""\
    {
      "cluster_name": "orders-etl-job-cluster",
      "spark_version": "14.3.x-scala2.12",
      "node_type_id": "i3.xlarge",
      "autoscale": {
        "min_workers": 2,
        "max_workers": 8
      },
      "autotermination_minutes": 20,
      "spark_conf": {
        "spark.databricks.delta.optimizeWrite.enabled": "true"
      }
    }
    // autoscale lets Databricks add workers DURING a heavy shuffle stage
    // and remove them once load drops — you pay for the compute the job
    // actually needed at each point in its execution, not a fixed worst-
    // case-sized cluster for the entire run.
""")

# ------------------------------------------------------------------
# 2. Delta Lake — ACID transactions on top of object storage
# ------------------------------------------------------------------
DELTA_LAKE_BASICS = textwrap.dedent("""\
    # Writing a Delta table (PySpark) — this is the DEFAULT format for
    # tables created in Databricks unless you specify otherwise.
    df.write.format("delta").mode("overwrite").saveAsTable("analytics.orders")

    # Delta's transaction log (_delta_log/*.json) records every write as
    # an atomic, ordered COMMIT — this is what gives Delta tables ACID
    # guarantees that raw Parquet files on S3 alone do not have (two
    # concurrent writers to plain Parquet files can corrupt each other;
    # Delta's log-based commit protocol prevents this).

    # TIME TRAVEL — query a table as it existed at a previous version or
    # timestamp, using the transaction log's history:
    df_yesterday = spark.read.format("delta") \\
        .option("timestampAsOf", "2026-01-14") \\
        .table("analytics.orders")

    # MERGE (upsert) — the Delta-native way to do the idempotent load
    # pattern from Data Engineering Notes L01, expressed directly against
    # the lakehouse table:
    from delta.tables import DeltaTable
    target = DeltaTable.forName(spark, "analytics.orders")
    target.alias("t").merge(
        source=updates_df.alias("s"),
        condition="t.order_id = s.order_id"
    ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
""")

# ------------------------------------------------------------------
# 3. Unity Catalog — centralized governance
# ------------------------------------------------------------------
UNITY_CATALOG_MODEL = textwrap.dedent("""\
    Unity Catalog's namespace is THREE levels: catalog.schema.table
    (e.g. `prod.analytics.orders`), one level deeper than a traditional
    two-level `schema.table` — the extra `catalog` level lets you cleanly
    separate environments (dev/staging/prod) or business units within
    ONE governance system, instead of relying on naming conventions or
    entirely separate workspaces.

    -- Grant SELECT on a specific table to a specific group, enforced
    -- centrally across every workspace attached to this Unity Catalog
    -- metastore, not per-workspace:
    GRANT SELECT ON TABLE prod.analytics.orders TO `data-analysts`;

    -- Column-level and row-level security are also expressible:
    ALTER TABLE prod.analytics.customers
    ALTER COLUMN ssn SET MASK mask_ssn_udf;
""")

# ------------------------------------------------------------------
# 4. Notebook vs Job — interactive development vs production execution
# ------------------------------------------------------------------
NOTEBOOK_VS_JOB_NOTE = (
    "A notebook attached to an all-purpose cluster is for EXPLORATION: "
    "iterating cell by cell, inspecting intermediate DataFrames. The SAME "
    "notebook (or a .py file) is then registered as a Databricks JOB — "
    "scheduled, run non-interactively on an auto-terminating job cluster, "
    "with retries/alerting/parameterization configured at the job level, "
    "not the notebook level. Treating a notebook as directly production-"
    "ready without wrapping it in a Job's operational controls (retries, "
    "monitoring, the right cluster type) is a common early mistake."
)


if __name__ == "__main__":
    print("=== Cluster types ===")
    for cluster_type, desc in CLUSTER_TYPE_COMPARISON.items():
        print(f"{cluster_type}: {desc}\n")

    print(CLUSTER_CONFIG_EXAMPLE)
    print(DELTA_LAKE_BASICS)
    print(UNITY_CATALOG_MODEL)
    print(NOTEBOOK_VS_JOB_NOTE)

"""
PRODUCTION CONTEXT EXAMPLE:
A financial services company runs three Databricks workspaces (dev,
staging, prod) all attached to ONE Unity Catalog metastore — an analyst
granted access to `prod.analytics.transactions` has that permission
enforced consistently regardless of which workspace they connect from,
and a compliance audit of "who accessed customer PII in the last 90
days" queries Unity Catalog's centralized audit log once, instead of
reconciling three separate per-workspace permission systems.
"""
