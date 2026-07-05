# ============================================================
# L02: Incremental Loading, Change Data Capture, and Partitioning
# ============================================================
# WHAT: How to load ONLY new/changed data instead of reprocessing an
#       entire source every run — incremental loading strategies, Change
#       Data Capture (CDC), and the partitioning schemes that make
#       incremental loads and queries efficient at scale.
# WHY: Reprocessing a full multi-billion-row table on every pipeline run
#      is what makes pipelines slow, expensive, and eventually
#      infeasible. Every production-scale pipeline in Airflow/Databricks/
#      Snowflake/ADF is built around incremental patterns.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
FULL LOAD: reprocess the entire source table every run. Simple, always
correct, but scales terribly — a 500M row table reprocessed nightly is
enormously wasteful when only 50,000 rows actually changed.

INCREMENTAL LOAD (watermark-based): track a "high-water mark" (typically
a timestamp or monotonically increasing ID) from the last successful run,
and only extract rows NEWER than that watermark. Requires the source to
have a reliable "last modified" column — and requires handling the edge
case where a row is UPDATED after the watermark already passed it (a
"late-arriving update" — often solved by using a `updated_at` column and
re-extracting a small overlapping window, not just `> watermark`).

CDC (Change Data Capture): instead of periodically POLLING the source
for changes (watermark approach), CDC STREAMS every insert/update/delete
event directly from the source database's transaction/write-ahead log in
near-real-time (tools: Debezium, Fivetran, native cloud CDC connectors).
This captures deletes (which a watermark-based `updated_at` scan cannot
see at all — a deleted row simply isn't there to query) and gives much
lower latency than periodic batch polling.

PARTITIONING: physically organizing a table's data into separate,
independently-addressable chunks (typically by date) so that both
incremental loads AND queries can skip reading irrelevant partitions
entirely (partition pruning). A table partitioned by `order_date`
lets a query for "yesterday's orders" read ONE partition instead of
scanning the entire table's history.

PRODUCTION USE CASE:
A CDC pipeline captures every row-level change from a production
Postgres orders table via its write-ahead log, streaming inserts,
updates, AND deletes into a data lake within seconds — enabling
near-real-time dashboards that a nightly full-load or even hourly
watermark-based batch job could never achieve, while also correctly
reflecting deleted/cancelled orders that a naive `updated_at` scan misses.

COMMON MISTAKES:
- Using `> watermark` on an `updated_at` column without any overlap
  window — a row updated in the same millisecond the previous run
  captured its watermark can be silently skipped (a real, if narrow,
  race condition in watermark-based incremental loading).
- Choosing a watermark-based approach when the business actually needs
  to know about DELETES — watermark/polling approaches fundamentally
  cannot detect deletions unless the source uses soft-deletes (a
  `deleted_at` flag rather than a real `DELETE`).
- Partitioning by a column with very high cardinality relative to query
  patterns (e.g. partitioning by `user_id` when queries are almost always
  filtered by date) — this creates too many small partitions and can hurt
  performance rather than help it; partition scheme should match actual
  query/load patterns.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta


# ------------------------------------------------------------------
# 1. Full load vs watermark-based incremental load
# ------------------------------------------------------------------
@dataclass
class SourceRow:
    id: str
    updated_at: datetime
    value: str


def full_load(source_rows: list[SourceRow]) -> list[SourceRow]:
    """Reprocesses everything, every time — correct but wasteful at scale."""
    return list(source_rows)


def incremental_load(source_rows: list[SourceRow], last_watermark: datetime,
                       overlap: timedelta = timedelta(minutes=5)) -> tuple[list[SourceRow], datetime]:
    """
    Only extracts rows updated after (watermark - overlap). The overlap
    window re-fetches a small amount of already-seen data on purpose —
    downstream loading MUST be idempotent (L01) so re-processing those
    overlapping rows is harmless, while still catching any row that was
    updated right at the watermark boundary and might otherwise be missed.
    """
    effective_watermark = last_watermark - overlap
    new_rows = [r for r in source_rows if r.updated_at > effective_watermark]
    next_watermark = max((r.updated_at for r in source_rows), default=last_watermark)
    return new_rows, next_watermark


# ------------------------------------------------------------------
# 2. CDC — capturing inserts, updates, AND deletes
# ------------------------------------------------------------------
class ChangeType:
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


@dataclass
class ChangeEvent:
    """
    Mirrors the shape of a real CDC event (e.g. from Debezium reading a
    Postgres WAL) — note DELETE events carry the row's ID but no new
    data, since the row no longer exists at the source.
    """
    change_type: str
    row_id: str
    data: dict | None
    timestamp: datetime


def apply_cdc_stream(events: list[ChangeEvent], destination: dict[str, dict]):
    """
    Applies a stream of change events to a destination table, in order.
    This is the CDC consumer's core loop — the SAME idempotency principle
    from L01 applies: applying the same event twice (e.g. after a
    consumer restart re-reads a few already-processed events) must be
    safe, which is why each event carries a timestamp/offset that can be
    checked before re-applying.
    """
    for event in events:
        if event.change_type in (ChangeType.INSERT, ChangeType.UPDATE):
            destination[event.row_id] = event.data
        elif event.change_type == ChangeType.DELETE:
            # THE key capability watermark-based polling cannot replicate:
            # a real DELETE at the source is reflected as an explicit
            # DELETE event here, not silently invisible.
            destination.pop(event.row_id, None)


# ------------------------------------------------------------------
# 3. Partitioning — pruning irrelevant data at load AND query time
# ------------------------------------------------------------------
@dataclass
class Partition:
    partition_key: str   # e.g. "2026-01-15"
    row_count: int


def partition_pruning_demo(partitions: list[Partition], target_date: str) -> list[Partition]:
    """
    A query/load for a SPECIFIC date only needs to touch the ONE matching
    partition — this is "partition pruning," and it's the mechanism that
    makes incremental loads on partitioned tables cheap: loading "just
    today's data" becomes "read one partition," not "scan the whole table
    and filter."
    """
    return [p for p in partitions if p.partition_key == target_date]


def partitioning_scheme_comparison():
    """
    Illustrates why partition GRANULARITY and COLUMN CHOICE matter —
    too fine-grained creates overhead from too many small partitions;
    too coarse-grained doesn't prune enough to help.
    """
    scenarios = {
        "By day (typical for time-series/event data)":
            "365 partitions/year — good balance for daily-batch pipelines "
            "and date-range queries; the most common default.",
        "By hour (high-volume streaming ingestion)":
            "8,760 partitions/year — finer pruning for latency-sensitive "
            "near-real-time queries, at the cost of more partition-metadata "
            "overhead to manage.",
        "By high-cardinality user_id (usually a MISTAKE for this use case)":
            "Millions of tiny partitions if queries are actually date-"
            "filtered — pruning by user_id doesn't help a "
            "'orders from yesterday' query at all, and the partition "
            "explosion hurts metadata/listing performance.",
    }
    for scheme, note in scenarios.items():
        print(f"{scheme}:\n  {note}\n")


if __name__ == "__main__":
    rows = [
        SourceRow("r1", datetime(2026, 1, 15, 10, 0), "a"),
        SourceRow("r2", datetime(2026, 1, 15, 14, 0), "b"),
        SourceRow("r3", datetime(2026, 1, 16, 9, 0), "c"),
    ]
    new_rows, next_wm = incremental_load(rows, last_watermark=datetime(2026, 1, 15, 12, 0))
    print(f"Incremental load found {len(new_rows)} rows, next watermark = {next_wm}")

    print("\n--- CDC stream application ---")
    dest: dict[str, dict] = {}
    events = [
        ChangeEvent(ChangeType.INSERT, "ord_1", {"amount": 100}, datetime(2026, 1, 15, 10)),
        ChangeEvent(ChangeType.UPDATE, "ord_1", {"amount": 150}, datetime(2026, 1, 15, 10, 5)),
        ChangeEvent(ChangeType.DELETE, "ord_1", None, datetime(2026, 1, 15, 10, 10)),
    ]
    apply_cdc_stream(events, dest)
    print(f"  destination after INSERT->UPDATE->DELETE: {dest}  (correctly empty)")

    print("\n--- Partition pruning ---")
    parts = [Partition("2026-01-14", 50_000), Partition("2026-01-15", 48_000), Partition("2026-01-16", 51_000)]
    pruned = partition_pruning_demo(parts, "2026-01-15")
    print(f"  pruned to {len(pruned)} partition(s) instead of scanning all {len(parts)}")

    print()
    partitioning_scheme_comparison()

"""
PRODUCTION CONTEXT EXAMPLE:
A retail analytics platform partitions its `orders` fact table by
`order_date` (day granularity) in Snowflake/Databricks, and uses CDC
(via Debezium reading the source Postgres WAL) instead of watermark
polling specifically because refunds/cancellations (DELETEs or soft-
delete UPDATEs at the source) must be reflected in near-real-time revenue
dashboards — a watermark-based nightly batch would show yesterday's
cancelled order as still-active revenue until the next batch run catches
the update, a gap CDC closes to seconds.
"""
