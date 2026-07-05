# ============================================================
# L06: Production Databricks — Workflows, Delta Live Tables, Auto Loader
# ============================================================
# WHAT: Databricks Workflows (multi-task job orchestration), Delta Live
#       Tables (declarative pipeline definitions with built-in data
#       quality enforcement), Auto Loader (efficient incremental file
#       ingestion), and cluster cost/sizing optimization.
# WHY: L05 covered Databricks' building blocks; this lesson covers the
#      layer that turns "a notebook that works" into a production
#      pipeline with orchestration, incremental ingestion, and enforced
#      data quality — directly comparable to Airflow (L03-L04) but native
#      to the Databricks platform.
# LEVEL: Intermediate/Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
DATABRICKS WORKFLOWS is Databricks' native orchestrator — a Workflow
(Job) is a DAG of TASKS, each of which can be a notebook, a Python
script, a SQL query, or another Workflow. It provides scheduling,
retries, alerting, and task-level dependencies natively, without needing
an external orchestrator like Airflow for pipelines that live entirely
within Databricks. Many teams use Airflow for CROSS-SYSTEM orchestration
(e.g. "wait for an external API, then trigger a Databricks job, then
load to Snowflake") and Databricks Workflows for orchestration ENTIRELY
within Databricks — the two aren't mutually exclusive.

DELTA LIVE TABLES (DLT) is a DECLARATIVE framework for building data
pipelines: instead of imperatively writing "read this, transform it,
write it," you declare the DESIRED tables and their dependencies (via
`@dlt.table` decorators), and DLT figures out execution order, handles
incremental processing automatically, and — critically — lets you attach
DATA QUALITY EXPECTATIONS directly to a table definition (`@dlt.expect`),
which DLT enforces on every pipeline run (dropping, warning on, or
failing the pipeline for rows that violate an expectation, per your
configuration) rather than quality checks being a separate, easily-
skipped afterthought.

AUTO LOADER (`cloudFiles` format) incrementally and efficiently ingests
new files landing in cloud storage (S3/ADLS/GCS) WITHOUT needing to list
the entire directory on every run — it uses cloud-native file
notification services (e.g. S3 event notifications via SQS) to discover
new files, making it efficient even at millions of files, unlike a naive
directory-listing approach that gets slower as the number of files grows.

PRODUCTION USE CASE:
A DLT pipeline defines a Bronze table (raw ingested via Auto Loader),
Silver table (cleaned, with `@dlt.expect_or_drop` quality rules), and
Gold table (business-level aggregates) — the medallion architecture (see
L12) expressed as a few declarative table definitions, with DLT handling
incremental processing and quality enforcement across the whole chain
automatically.

COMMON MISTAKES:
- Using a plain directory listing (`dbutils.fs.ls` in a loop, or a full
  `spark.read` over the whole path) for incremental file ingestion
  instead of Auto Loader — this gets progressively slower as file count
  grows and doesn't scale to the millions-of-files scenario Auto Loader
  is built for.
- Treating DLT's data-quality expectations as purely informational
  (using `@dlt.expect`, which only WARNS) when the business actually
  needs violating rows dropped or the pipeline halted — the choice
  between `expect`, `expect_or_drop`, and `expect_or_fail` is a real
  decision, not a default to leave unexamined.
- Building deeply nested Workflow task dependencies without leveraging
  DLT for the actual data transformation logic — Workflows orchestrates
  WHEN things run; DLT (or plain notebooks/scripts) defines WHAT they
  compute; conflating the two responsibilities makes pipelines harder to
  reason about.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Databricks Workflows — multi-task job definition
# ------------------------------------------------------------------
WORKFLOW_JOB_CONFIG = textwrap.dedent("""\
    {
      "name": "daily-orders-pipeline",
      "tasks": [
        {
          "task_key": "ingest",
          "notebook_task": {"notebook_path": "/pipelines/ingest_orders"},
          "job_cluster_key": "etl_cluster"
        },
        {
          "task_key": "transform",
          "depends_on": [{"task_key": "ingest"}],
          "notebook_task": {"notebook_path": "/pipelines/transform_orders"},
          "job_cluster_key": "etl_cluster"
        },
        {
          "task_key": "quality_check",
          "depends_on": [{"task_key": "transform"}],
          "notebook_task": {"notebook_path": "/pipelines/validate_orders"},
          "job_cluster_key": "etl_cluster"
        }
      ],
      "job_clusters": [{
        "job_cluster_key": "etl_cluster",
        "new_cluster": {"autoscale": {"min_workers": 2, "max_workers": 8}}
      }],
      "schedule": {"quartz_cron_expression": "0 0 6 * * ?", "timezone_id": "UTC"},
      "email_notifications": {"on_failure": ["data-eng@company.com"]}
    }
""")

# ------------------------------------------------------------------
# 2. Delta Live Tables — declarative pipelines with data quality
# ------------------------------------------------------------------
DLT_PIPELINE_EXAMPLE = textwrap.dedent("""\
    import dlt
    from pyspark.sql.functions import col

    # BRONZE: raw ingestion via Auto Loader — DLT handles the incremental
    # file discovery/processing automatically once declared this way.
    @dlt.table(comment="Raw orders, ingested as-is")
    def bronze_orders():
        return (
            spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "json")
            .load("/mnt/raw/orders/")
        )

    # SILVER: cleaned, with QUALITY EXPECTATIONS enforced on every run.
    @dlt.table(comment="Cleaned orders, quality-checked")
    @dlt.expect_or_drop("valid_amount", "amount_cents > 0")
    @dlt.expect_or_drop("valid_order_id", "order_id IS NOT NULL")
    @dlt.expect("reasonable_amount", "amount_cents < 10000000")  # warn only, don't drop
    def silver_orders():
        return (
            dlt.read_stream("bronze_orders")
            .withColumn("total_usd", col("amount_cents") / 100)
        )

    # GOLD: business-level aggregate, built on the quality-enforced Silver table.
    @dlt.table(comment="Daily order totals by region")
    def gold_daily_order_totals():
        return (
            dlt.read("silver_orders")
            .groupBy("order_date", "region")
            .agg({"total_usd": "sum"})
        )

    # DLT automatically infers the Bronze -> Silver -> Gold dependency
    # graph from the dlt.read()/dlt.read_stream() calls — you never
    # manually declare task ordering the way you would in Workflows.
""")

EXPECTATION_MODES = {
    "@dlt.expect": "Log a warning for violating rows, but KEEP them in "
        "the output table — use when you want VISIBILITY into data "
        "quality issues without blocking the pipeline.",
    "@dlt.expect_or_drop": "Silently DROP violating rows from the output "
        "— use when bad rows are safe to simply exclude (e.g. malformed "
        "test records) rather than being a signal of a real upstream problem.",
    "@dlt.expect_or_fail": "FAIL the entire pipeline run if any row "
        "violates — use for expectations where violation indicates a "
        "genuine, must-investigate data integrity problem (e.g. a "
        "primary key that must never be null).",
}

# ------------------------------------------------------------------
# 3. Auto Loader — efficient incremental file ingestion
# ------------------------------------------------------------------
AUTO_LOADER_EXAMPLE = textwrap.dedent("""\
    # Auto Loader uses cloud-native file notifications (S3 event
    # notifications -> SQS, by default, when configured) to discover NEW
    # files without re-listing the entire directory — this is what makes
    # it scale to millions of files where a naive `spark.read` over the
    # whole path would get progressively slower every run.
    df = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .option("cloudFiles.schemaLocation", "/mnt/schemas/orders")
        .option("cloudFiles.inferColumnTypes", "true")
        .load("/mnt/raw/orders/")
    )

    # Schema evolution handling — directly connects to Data Engineering
    # Notes L01's schema-drift discussion, but as a first-class Auto
    # Loader configuration option rather than custom logic:
    #   "addNewColumns" (default) - new columns are added automatically
    #   "failOnNewColumns" - pipeline fails, forcing explicit review
    #   "rescue" - unexpected columns are captured in a _rescued_data column
    #              instead of being dropped OR failing the whole pipeline
""")


if __name__ == "__main__":
    print(WORKFLOW_JOB_CONFIG)
    print(DLT_PIPELINE_EXAMPLE)
    print("=== DLT expectation modes ===")
    for mode, desc in EXPECTATION_MODES.items():
        print(f"{mode}: {desc}\n")
    print(AUTO_LOADER_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
An e-commerce platform's order pipeline uses Auto Loader to ingest
hundreds of thousands of small JSON files landing continuously in S3,
feeding a DLT pipeline with `expect_or_fail` on `order_id IS NOT NULL`
(a null order ID indicates a genuine upstream bug worth halting the
pipeline for) and `expect_or_drop` on a handful of known-malformed test
records from a staging environment that occasionally leak into
production data — the SAME quality-check codebase making two
deliberately different severity decisions based on what each violation
actually signals.
"""
