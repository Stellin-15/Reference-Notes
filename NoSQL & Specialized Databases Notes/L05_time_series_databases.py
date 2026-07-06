# ============================================================
# L05: Time-Series Databases — InfluxDB, TimescaleDB, and Purpose-Built Storage
# ============================================================
# WHAT: Why TIME-SERIES data (metrics, sensor readings, financial ticks
#       — always timestamped, almost always queried by time range) gets
#       its OWN specialized database category, and the specific storage/
#       query optimizations (downsampling, retention policies,
#       time-based partitioning) that make them fast for this workload specifically.
# WHY: This repo's Observability Notes covers Prometheus (a time-series
#      database used for metrics) but doesn't cover time-series storage
#      as a general database CATEGORY — this lesson fills that gap,
#      covering the underlying storage engine principles broadly.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
TIME-SERIES DATA has a genuinely distinctive shape that general-purpose
databases handle sub-optimally: EVERY record has a TIMESTAMP as a core,
near-universal query dimension; data is overwhelmingly WRITE-ONCE,
APPEND-ONLY (a sensor reading from yesterday doesn't get updated
retroactively); queries overwhelmingly filter/aggregate by TIME RANGE
("show me the last 24 hours," "average CPU usage per hour over the past
week"); and RECENT data is accessed FAR more frequently than old data,
while OLD data still needs to be retained (often at reduced granularity)
for historical analysis. A general-purpose relational or document
database CAN store this data, but doesn't exploit any of these
distinctive properties for storage efficiency or query speed the way a
purpose-built time-series database does.

TIME-BASED PARTITIONING (often into fixed-size "chunks," e.g. one
partition per day or per week) is the foundational storage optimization:
since queries almost always filter by a time range, physically
organizing data into time-based partitions lets a query SKIP entire
partitions outside the requested range ENTIRELY, without even reading
their contents — a direct analog to the partition-pruning optimization
technique in general data warehousing, applied here because time-range
filtering is nearly UNIVERSAL for this specific workload rather than merely common.

DOWNSAMPLING AND RETENTION POLICIES directly address the "recent data
matters more, but old data must be retained cheaply" access pattern:
a RETENTION POLICY automatically expires/deletes raw data older than a
configured age (e.g. "keep raw per-second metrics for 7 days"), while
DOWNSAMPLING (also called "continuous aggregation" in some tools)
automatically computes and stores LOWER-RESOLUTION summaries (e.g.
hourly averages) for LONGER retention (e.g. "keep hourly averages for 2
years") — this lets a system answer "what was average latency last
Tuesday" from cheap, pre-aggregated data without needing to retain (or
scan) every individual raw data point from that day forever.

COLUMNAR STORAGE AND COMPRESSION: time-series databases commonly store
data in a COLUMNAR layout (all values for one specific metric stored
together, contiguous in storage) rather than a traditional row-oriented
layout — this is especially effective for time-series data because
consecutive readings of the SAME metric are often very SIMILAR in value
(e.g. CPU usage changing gradually, not randomly each second), enabling
much higher COMPRESSION RATIOS than row-oriented storage typically
achieves for this specific kind of gradually-changing numeric data.

PRODUCTION USE CASE:
An IoT platform ingesting sensor readings from millions of devices
every few seconds uses a time-series database (e.g. InfluxDB) configured
to retain raw per-second data for 3 days, downsampled per-minute
averages for 30 days, and per-hour averages indefinitely — a dashboard
query for "temperature trend over the past year" is answered instantly
from the cheap, pre-aggregated hourly data, while a debugging query for
"exact sensor readings in the last hour" can still access full raw-resolution data.

COMMON MISTAKES:
- Storing time-series data in a general-purpose relational database
  WITHOUT time-based partitioning or any downsampling strategy — as data
  volume grows over months/years, queries (and even simple table
  maintenance operations) progressively slow down, since every query
  scans an ever-growing, undifferentiated table rather than being able
  to skip irrelevant time ranges entirely.
- Retaining ALL raw-resolution data indefinitely "just in case," without
  a deliberate downsampling/retention strategy — this leads to
  unboundedly growing storage costs for data whose FULL RESOLUTION is
  rarely, if ever, actually needed beyond a recent window.
- Choosing a time-series database for data that ISN'T genuinely
  time-series shaped (e.g. data that's frequently UPDATED after initial
  write, rather than append-only) — time-series databases are optimized
  SPECIFICALLY for the write-once, time-range-query access pattern, and
  forcing a different access pattern onto them sacrifices their core
  optimization advantages.
"""

import time
from collections import defaultdict


# ------------------------------------------------------------------
# 1. Time-based partitioning — skipping irrelevant partitions entirely
# ------------------------------------------------------------------
def partition_by_day(timestamp: float) -> str:
    day_number = int(timestamp // 86400)
    return f"partition_day_{day_number}"


def time_partitioning_demo():
    now = time.time()
    sample_readings = [
        {"timestamp": now - 86400 * 0.5, "value": 42},   # today
        {"timestamp": now - 86400 * 1.5, "value": 38},   # yesterday
        {"timestamp": now - 86400 * 10, "value": 51},    # 10 days ago
    ]

    partitioned = defaultdict(list)
    for reading in sample_readings:
        partition = partition_by_day(reading["timestamp"])
        partitioned[partition].append(reading)

    print("Data organized into time-based partitions:")
    for partition, readings in partitioned.items():
        print(f"  {partition}: {len(readings)} reading(s)")

    print("\nQuery for 'last 24 hours': only needs to READ partitions")
    print("overlapping that range — older partitions are SKIPPED entirely,")
    print("without even scanning their contents.")


# ------------------------------------------------------------------
# 2. Downsampling — pre-aggregating for cheap long-term retention
# ------------------------------------------------------------------
def downsample_to_hourly_averages(raw_readings: list[dict]) -> dict[int, float]:
    hourly_buckets: dict[int, list[float]] = defaultdict(list)
    for reading in raw_readings:
        hour_bucket = int(reading["timestamp"] // 3600)
        hourly_buckets[hour_bucket].append(reading["value"])

    return {hour: sum(values) / len(values) for hour, values in hourly_buckets.items()}


def downsampling_demo():
    now = time.time()
    # Simulate 100 raw, per-second-ish readings within roughly the same hour
    raw_readings = [{"timestamp": now - i * 30, "value": 40 + (i % 5)} for i in range(100)]

    hourly_averages = downsample_to_hourly_averages(raw_readings)
    print(f"\n{len(raw_readings)} raw readings downsampled to "
          f"{len(hourly_averages)} hourly average(s): {hourly_averages}")
    print("  -> A retention policy might KEEP these hourly averages")
    print("     indefinitely while DELETING the 100 raw readings after a")
    print("     few days — 'what was the average last month' is answered")
    print("     instantly from cheap pre-aggregated data, no raw-data scan needed.")


if __name__ == "__main__":
    time_partitioning_demo()
    downsampling_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
This repo's Observability Notes covers Prometheus, itself a purpose-
built time-series database for metrics specifically because of these
exact properties — Prometheus's storage engine partitions data by time
block, applies compression optimized for gradually-changing numeric
metric values, and (via tools like Thanos or Cortex for long-term
storage) supports downsampling older data to keep years of historical
metrics queryable without the storage cost of retaining full-resolution
data indefinitely — the SAME underlying time-series database
principles this lesson covers generally, applied to the specific
metrics/observability use case.
"""
