# ============================================================
# L12: Production Data Platform Architecture — The Medallion Pattern
# ============================================================
# WHAT: A capstone lesson tying L01-L11 together into one coherent,
#       production-grade data platform: the medallion (Bronze/Silver/
#       Gold) architecture, how ingestion/orchestration/warehousing/
#       quality/observability compose end to end, and a full reference
#       architecture diagram.
# WHY: Every prior lesson covered one piece in isolation. Real data
#      platforms are an INTEGRATED system — this lesson is where you see
#      how ETL fundamentals, incremental loading, an orchestrator, a
#      lakehouse/warehouse, and data quality/observability all fit
#      together as one architecture, not a pile of independent tools.
# LEVEL: Capstone
# ============================================================

"""
CONCEPT OVERVIEW:
The MEDALLION ARCHITECTURE organizes data into three progressively
refined layers:

  - BRONZE: raw data, ingested AS-IS from source systems, with minimal
    transformation — the goal is fidelity to the source, not usability.
    Ingested via CDC (L02), Auto Loader (L06), or Snowpipe (L07)
    depending on platform. Schema drift here is often auto-accepted
    (L01) since Bronze is meant to preserve whatever the source sent.
  - SILVER: cleaned, validated, conformed data — deduplicated, typed
    correctly, with DATA QUALITY EXPECTATIONS enforced (L06's DLT
    expectations, L11's dbt tests/Great Expectations checks). This is
    where "garbage in" from Bronze gets caught and either fixed or
    excluded, rather than silently flowing downstream.
  - GOLD: business-level, aggregated, purpose-built tables — the layer
    dashboards and ML models actually query. Gold tables are typically
    denormalized/aggregated specifically for their consuming use case,
    unlike Silver's more normalized, general-purpose shape.

This layering exists because it lets you REPROCESS: if a Silver
transformation rule turns out to be wrong, you can fix it and re-derive
Silver/Gold from the UNCHANGED Bronze data, without re-extracting from
the original source system (which might no longer even have the old data
available, or might be expensive/slow to re-query).

An ORCHESTRATOR (L03-L04, L06, L10) sequences the Bronze -> Silver ->
Gold progression, handles retries/scheduling, and often coordinates
across multiple platforms (e.g. ingesting from a vendor API, landing in
a lake, transforming in Databricks, serving from Snowflake).

PRODUCTION USE CASE:
See the full reference architecture below — this is the shape most
production data platforms converge on, whether built primarily on
Databricks (Bronze/Silver/Gold as Delta tables, orchestrated by DLT/
Workflows) or Snowflake (raw/staging/analytics schemas, orchestrated by
Streams & Tasks or an external Airflow), or a hybrid of both plus ADF
for Azure-specific ingestion.

COMMON MISTAKES:
- Skipping the Bronze layer entirely and transforming directly from
  source into a "clean" table — this makes REPROCESSING impossible
  without re-extracting from source, which is often slower, sometimes
  no longer possible (if the source has since changed/deleted the data),
  and always more operationally complex than replaying from an existing
  Bronze layer.
- Applying data quality enforcement (L11) only at the very end (Gold)
  instead of at Silver — this lets bad data propagate through multiple
  transformation stages before being caught, making root-causing harder
  and wasting compute on transformations of data that should have been
  rejected earlier.
- Treating this architecture as one-size-fits-all without adapting
  layer definitions to actual business needs — a real platform's
  Silver/Gold boundary is a judgment call based on what transformations
  are broadly reusable (Silver) versus specific to one consumer's needs
  (Gold), not a rigid, universal rule.
"""

import textwrap


# ------------------------------------------------------------------
# 1. The medallion layers, concretely
# ------------------------------------------------------------------
MEDALLION_LAYER_DEFINITIONS = {
    "Bronze": {
        "purpose": "Raw, source-fidelity data — minimal transformation",
        "ingestion": "CDC (L02) / Auto Loader (L06) / Snowpipe (L07) / ADF Copy Activity (L09)",
        "schema_handling": "Often auto-accept new fields (L01) — fidelity over strictness",
        "typical_retention": "Long (often indefinite) — this is your ability to reprocess "
                              "from scratch if downstream logic changes",
    },
    "Silver": {
        "purpose": "Cleaned, deduplicated, validated, conformed to a stable schema",
        "ingestion": "Incremental transformation FROM Bronze (Streams & Tasks / DLT / dbt models)",
        "schema_handling": "Enforced quality expectations (L06, L11) — this is where bad "
                            "data gets caught, not passed through",
        "typical_retention": "Medium — long enough to support Gold reprocessing needs",
    },
    "Gold": {
        "purpose": "Business-level, aggregated, purpose-built for specific consumers",
        "ingestion": "Aggregation/denormalization FROM Silver",
        "schema_handling": "Stable, contract-like schema — this is what BI tools/ML "
                            "pipelines depend on directly",
        "typical_retention": "As needed for the specific consuming use case",
    },
}

# ------------------------------------------------------------------
# 2. A concrete end-to-end pipeline definition, tying every prior lesson together
# ------------------------------------------------------------------
END_TO_END_PIPELINE_SKETCH = textwrap.dedent("""\
    # BRONZE — Auto Loader (L06) incrementally ingests raw JSON order
    # events landing in cloud storage, with schema drift auto-accepted.
    @dlt.table(comment="Raw order events")
    def bronze_orders():
        return (
            spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "json")
            .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
            .load("/mnt/raw/orders/")
        )

    # SILVER — cleaned and quality-enforced (L06, L11). This is the
    # REPROCESSING BOUNDARY: if this transformation logic has a bug,
    # fix it and re-run FROM bronze_orders, no re-extraction from the
    # original source needed.
    @dlt.table(comment="Cleaned, validated orders")
    @dlt.expect_or_fail("valid_order_id", "order_id IS NOT NULL")
    @dlt.expect_or_drop("valid_amount", "amount_cents > 0")
    def silver_orders():
        return (
            dlt.read_stream("bronze_orders")
            .dropDuplicates(["order_id"])
            .withColumn("amount_usd", col("amount_cents") / 100)
        )

    # GOLD — business-level aggregate, purpose-built for the executive
    # revenue dashboard specifically (a DIFFERENT Gold table would exist
    # for, say, an ML churn-prediction feature pipeline consuming the
    # SAME Silver table differently).
    @dlt.table(comment="Daily revenue by region, for exec dashboard")
    def gold_daily_revenue_by_region():
        return (
            dlt.read("silver_orders")
            .groupBy("order_date", "region")
            .agg(sum("amount_usd").alias("total_revenue_usd"))
        )

    # ORCHESTRATION (L10): if this whole pipeline is one stage in a
    # larger cross-system flow (e.g. triggered after a vendor API sync,
    # feeding a Snowflake-based BI layer afterward), an Airflow DAG
    # wraps it:
    #   fetch_vendor_data >> trigger_dlt_pipeline >> sync_gold_to_snowflake
""")

# ------------------------------------------------------------------
# 3. Full reference architecture
# ------------------------------------------------------------------
REFERENCE_ARCHITECTURE = r"""
    Source Systems                Ingestion              Bronze
    +----------------+       +------------------+   +----------------+
    | Postgres (CDC) |------>| Debezium/Snowpipe |-->|  raw.* tables  |
    | Vendor APIs    |------>| Airflow extractors |->|  (Delta/raw    |
    | On-prem SQL    |------>| ADF Self-Hosted IR |->|   schema)      |
    +----------------+       +------------------+   +-------+--------+
                                                              |
                          Orchestration (Airflow/ADF/         v
                          Databricks Workflows — L10)   +----------------+
                                                          |  Silver layer  |
                          Data quality gate (L11) <-------|  (validated,   |
                                                          |   deduplicated)|
                                                          +-------+--------+
                                                                  |
                                                                  v
                                                          +----------------+
                                                          |  Gold layer     |
                                                          |  (business      |
                                                          |   aggregates)   |
                                                          +-------+--------+
                                                                  |
                              +-----------------------------------+
                              |                                    |
                              v                                    v
                     +----------------+                  +----------------+
                     | BI dashboards  |                  | ML feature      |
                     | (Snowflake/    |                  | pipelines       |
                     |  Databricks SQL)|                 +----------------+
                     +----------------+

    Cross-cutting: pipeline observability (freshness/runtime/volume
    monitoring, L11) and lineage tracking wrap EVERY layer, not just one.
"""


if __name__ == "__main__":
    for layer, details in MEDALLION_LAYER_DEFINITIONS.items():
        print(f"=== {layer} ===")
        for k, v in details.items():
            print(f"  {k}: {v}")
        print()

    print(END_TO_END_PIPELINE_SKETCH)
    print(REFERENCE_ARCHITECTURE)

"""
PRODUCTION CONTEXT EXAMPLE:
A mid-size SaaS company's data platform: Fivetran (a managed CDC/ELT
tool) lands raw data from Postgres and vendor APIs into Bronze Delta
tables; a DLT pipeline enforces quality expectations building Silver;
separate Gold tables serve the finance team's revenue dashboard and the
data science team's churn-prediction feature pipeline from the SAME
Silver layer, each shaped for its own consumer; Airflow orchestrates the
handful of cross-system steps (triggering the DLT pipeline after
Fivetran's sync completes, then syncing specific Gold tables into
Snowflake for the BI team's preferred query tool) — every technique from
L01 (idempotent, schema-aware ingestion) through L11 (quality gates,
freshness monitoring) is present in this one platform, composed rather
than used in isolation.
"""
