# ============================================================
# L01: ETL Fundamentals — ETL vs ELT, Idempotency, Schema Evolution
# ============================================================
# WHAT: The core data pipeline pattern (Extract, Transform, Load), its
#       modern variant (Extract, Load, Transform), and the two properties
#       every production pipeline needs: idempotency and graceful schema
#       evolution.
# WHY: Every tool in this domain (Airflow, Databricks, Snowflake, ADF) is
#      just infrastructure for running THIS pattern reliably at scale —
#      get the fundamentals wrong and no amount of orchestration tooling
#      saves you from silently corrupt or duplicated data.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
ETL (Extract, Transform, Load): pull data from a source, transform it
(clean, join, aggregate, reshape) BEFORE loading it into the destination.
Transformation happens in a separate compute layer (traditionally an ETL
server), so the destination only ever receives already-clean data.

ELT (Extract, Load, Transform): pull data from a source, load it into the
destination AS-IS (raw), and transform it INSIDE the destination using
the destination's own compute (e.g. a Snowflake warehouse, a Databricks
cluster). This became the dominant pattern once cloud warehouses made
compute cheap and elastic — it's simpler operationally (one system holds
raw and transformed data) and lets you REPROCESS raw data with new
transformation logic without re-extracting from the source.

IDEMPOTENCY: running the same pipeline run twice (e.g. after a retry due
to a transient failure) must produce the SAME end state, not duplicated
or corrupted data. This is not automatic — a naive `INSERT` on every run
duplicates rows on retry; an idempotent design uses `MERGE`/upsert keyed
on a natural or surrogate key, or deletes-and-reinserts a specific
partition before writing.

SCHEMA EVOLUTION: source systems change their schema over time (a new
column appears, a type changes, a field is renamed) — a production
pipeline must decide, explicitly, whether to: (a) fail loudly (safest
default for critical pipelines), (b) auto-add new columns (common for
analytics lakes), or (c) map/rename via an explicit schema contract.
Silently DROPPING unexpected fields (many naive pipelines' default
behavior) is the worst outcome — it looks like success while quietly
losing data.

PRODUCTION USE CASE:
A daily orders pipeline extracts from a transactional Postgres database,
and a bug causes the extraction job to retry after a partial failure.
Without idempotency, retrying re-inserts the same day's orders, silently
doubling revenue in every downstream report — a bug that often isn't
caught until a stakeholder notices numbers don't reconcile weeks later.

COMMON MISTAKES:
- Building a pipeline that only works correctly on the "happy path" (no
  retries, no partial failures) — production pipelines retry constantly;
  idempotency isn't optional polish, it's a correctness requirement.
- Silently dropping unrecognized fields during extraction instead of
  either failing or explicitly logging the schema drift — this is how
  "the pipeline never broke" coexists with "we lost a column's worth of
  data six months ago and nobody noticed."
- Doing heavy transformation logic in a thin, hard-to-scale extraction
  layer instead of pushing it into the destination's compute (the ELT
  argument) — this becomes a scaling bottleneck as data volume grows.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum


# ------------------------------------------------------------------
# 1. ETL vs ELT — the same logical pipeline, different execution order
# ------------------------------------------------------------------
def etl_pipeline(raw_orders: list[dict]) -> list[dict]:
    """
    ETL: transform BEFORE loading. The transformation logic lives in
    THIS process (e.g. a Python/Spark job), and only clean data ever
    reaches the destination.
    """
    transformed = []
    for order in raw_orders:
        transformed.append({
            "order_id": order["id"],
            "total_usd": round(order["amount_cents"] / 100, 2),   # cents -> dollars
            "order_date": order["created_at"][:10],                 # timestamp -> date
        })
    return transformed
    # A real ETL job would then LOAD `transformed` into the destination —
    # the destination never sees the raw `amount_cents`/`created_at` shape.


ELT_LOAD_THEN_TRANSFORM_SQL = """
-- ELT: load raw data AS-IS first, transform INSIDE the warehouse.
-- Step 1 (Load): raw_orders lands in the warehouse completely unchanged.
CREATE TABLE raw.orders AS SELECT * FROM staged_orders;

-- Step 2 (Transform): a SQL model runs INSIDE the warehouse's own
-- compute, using the warehouse's parallelism instead of a separate
-- ETL server's — this is the entire ELT value proposition.
CREATE TABLE analytics.orders AS
SELECT
    id AS order_id,
    ROUND(amount_cents / 100.0, 2) AS total_usd,
    CAST(created_at AS DATE) AS order_date
FROM raw.orders;
"""


# ------------------------------------------------------------------
# 2. Idempotency — MERGE/upsert instead of naive INSERT
# ------------------------------------------------------------------
@dataclass
class OrderRecord:
    order_id: str
    total_usd: float
    order_date: date


class NaiveOrderStore:
    """Demonstrates the BROKEN, non-idempotent pattern."""

    def __init__(self):
        self.rows: list[OrderRecord] = []

    def load(self, records: list[OrderRecord]):
        # BUG: every call appends, regardless of whether these exact
        # records were already loaded by a previous (retried) run.
        self.rows.extend(records)


class IdempotentOrderStore:
    """The MERGE/upsert pattern — the correct, idempotent equivalent."""

    def __init__(self):
        self.rows_by_id: dict[str, OrderRecord] = {}

    def load(self, records: list[OrderRecord]):
        # Keyed on order_id: re-running with the SAME input records is a
        # no-op in effect (each record just overwrites itself with an
        # identical value) — running this pipeline twice for the same
        # day produces the SAME end state, not duplicates.
        for record in records:
            self.rows_by_id[record.order_id] = record

    @property
    def rows(self) -> list[OrderRecord]:
        return list(self.rows_by_id.values())


IDEMPOTENT_MERGE_SQL = """
-- The SQL equivalent of the upsert pattern above — this is the actual
-- statement you'd run in Snowflake/Databricks/most warehouses to load
-- a batch idempotently, keyed on order_id.
MERGE INTO analytics.orders AS target
USING staged_orders AS source
ON target.order_id = source.order_id
WHEN MATCHED THEN
    UPDATE SET total_usd = source.total_usd, order_date = source.order_date
WHEN NOT MATCHED THEN
    INSERT (order_id, total_usd, order_date)
    VALUES (source.order_id, source.total_usd, source.order_date);
"""


# ------------------------------------------------------------------
# 3. Schema evolution — explicit contract vs silent drop
# ------------------------------------------------------------------
class SchemaAction(Enum):
    FAIL = "fail"              # safest default for critical/financial pipelines
    AUTO_ADD_COLUMN = "auto_add"  # common for analytics lakes / exploratory data
    MAP_EXPLICITLY = "map"     # a maintained rename/type-mapping contract


EXPECTED_SCHEMA = {"id", "amount_cents", "created_at"}


def handle_schema_drift(record: dict, on_new_field: SchemaAction) -> dict:
    incoming_fields = set(record.keys())
    new_fields = incoming_fields - EXPECTED_SCHEMA

    if not new_fields:
        return record

    if on_new_field == SchemaAction.FAIL:
        raise ValueError(f"Unexpected new field(s) in source data: {new_fields}. "
                          f"Pipeline halted rather than silently processing "
                          f"unvalidated data.")
    elif on_new_field == SchemaAction.AUTO_ADD_COLUMN:
        # In a real warehouse pipeline this would ALTER TABLE ADD COLUMN
        # before loading — here we just pass the record through, noting
        # the drift for observability (see L11).
        print(f"  [schema drift] new field(s) auto-accepted: {new_fields}")
        return record
    else:  # MAP_EXPLICITLY
        raise NotImplementedError(
            "A real mapping contract would look up new_fields in a "
            "maintained rename/cast table here, not silently pass or fail."
        )


if __name__ == "__main__":
    raw = [
        {"id": "ord_1", "amount_cents": 2599, "created_at": "2026-01-15T10:30:00Z"},
        {"id": "ord_2", "amount_cents": 4999, "created_at": "2026-01-15T11:05:00Z"},
    ]
    print("ETL-transformed rows:", etl_pipeline(raw))

    print("\n--- Naive (non-idempotent) store, loaded TWICE ---")
    naive = NaiveOrderStore()
    records = [OrderRecord("ord_1", 25.99, date(2026, 1, 15))]
    naive.load(records)
    naive.load(records)  # simulates a retry
    print(f"  row count after 2 loads: {len(naive.rows)}  (BUG: should be 1)")

    print("\n--- Idempotent store, loaded TWICE ---")
    idempotent = IdempotentOrderStore()
    idempotent.load(records)
    idempotent.load(records)  # the same retry — now harmless
    print(f"  row count after 2 loads: {len(idempotent.rows)}  (correct: stays 1)")

    print("\n--- Schema drift handling ---")
    drifted_record = {"id": "ord_3", "amount_cents": 1000,
                       "created_at": "2026-01-15T12:00:00Z", "currency": "EUR"}
    handle_schema_drift(drifted_record, on_new_field=SchemaAction.AUTO_ADD_COLUMN)
    try:
        handle_schema_drift(drifted_record, on_new_field=SchemaAction.FAIL)
    except ValueError as e:
        print(f"  [correctly raised] {e}")

"""
PRODUCTION CONTEXT EXAMPLE:
A subscription-billing pipeline MUST be idempotent and MUST fail loudly
on schema drift (not auto-add) — a retried run that double-charges a
customer's MRR into an analytics table, or one that silently accepts an
unexpected new "discount_percent" field without applying it to revenue
calculations, both produce numbers finance will eventually catch and
distrust. A marketing-clickstream pipeline, by contrast, can reasonably
auto-add new event-property columns, since occasional schema growth is
expected and the cost of a missed field is far lower than a halted pipeline.
"""
