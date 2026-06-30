# ============================================================
# L05: Spark Performance Tuning
# ============================================================
# WHAT: Deep-dive into Spark performance configuration, data skew,
#       adaptive query execution, caching, file formats, and
#       real-world optimization strategies.
# WHY:  Default Spark config works for toy workloads. Production
#       jobs on terabytes fail, spill to disk, or take hours when
#       tuning is neglected. Knowing these levers is the difference
#       between a 2-hour job and an 8-minute job.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    Spark performance is a multi-layer problem: cluster resources,
    data layout on disk, in-memory partitioning, join strategy, and
    query planning all interact. This file works through each layer
    systematically, explaining the default, the failure mode, and
    the correct tuning target.

PRODUCTION USE CASE:
    Daily ETL on 1 TB of order data. Initial run: 2 hours, 3 spills
    to disk, one skewed task holding up the entire stage. After
    applying techniques in this file: 8 minutes, zero spills, all
    tasks balanced.

COMMON MISTAKES:
    1. Leaving shuffle partitions at 200 for a 10 GB dataset (200
       partitions × 50 MB each is fine) but also for a 2 TB dataset
       (200 partitions × 10 GB each = guaranteed spill).
    2. Caching a DataFrame once and forgetting to unpersist — wastes
       executor memory for the rest of the job.
    3. Writing partitioned Parquet with a high-cardinality column
       (e.g., user_id) producing millions of tiny files.
    4. Broadcasting a table that is actually 500 MB — driver OOM.
    5. Fixing skew with salting but forgetting to explode/join the
       salt on the other side.
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, LongType, DoubleType
import random

# ============================================================
# SECTION 1: CREATING A TUNED SPARK SESSION
# ============================================================
# In production you pass these via spark-submit --conf flags.
# Here they are set programmatically so the file is self-contained.
#
# NOTE: SparkSession.builder.getOrCreate() returns the existing
# session if one exists, so these configs may be ignored in an
# interactive notebook. Use spark.conf.set() post-creation instead.

spark = (
    SparkSession.builder
    .appName("L05_PerformanceTuning")

    # --- SHUFFLE PARTITIONS ---
    # Default: 200. This is the number of partitions created after
    # a shuffle (groupBy, join, distinct, repartition).
    #
    # Too few  → each partition is huge → spill to disk → slow.
    # Too many → each partition is tiny → scheduling overhead → slow.
    #
    # Rule of thumb 1: 2-3× number of CPU cores across all executors.
    #   4 executors × 4 cores = 16 cores → 32-48 shuffle partitions.
    #
    # Rule of thumb 2 for large shuffles: total shuffle data / 128 MB.
    #   500 GB shuffle → 500000 MB / 128 = ~3900 partitions.
    #
    # AQE (see below) auto-tunes this at runtime in Spark 3.2+.
    .config("spark.sql.shuffle.partitions", "400")

    # --- MAX PARTITION BYTES (reads) ---
    # Controls how large a partition can be when reading Parquet/ORC.
    # Default: 128 MB. Spark tries to create partitions <= this size.
    #
    # Reading 100 files of 1 GB each → 100 tasks initially, but Spark
    # will split each 1 GB file into ~8 partitions of 128 MB = 800 tasks.
    #
    # Increase to 256 MB if you have few rows but large rows (wide schema).
    # Decrease to 64 MB if CPU is the bottleneck (more parallelism).
    .config("spark.sql.files.maxPartitionBytes", str(128 * 1024 * 1024))  # 128 MB

    # --- BROADCAST JOIN THRESHOLD ---
    # If one side of a join is smaller than this threshold, Spark
    # broadcasts it to every executor, avoiding a shuffle entirely.
    #
    # Default: 10 MB. Very conservative — raise it if you have
    # dimension tables up to 200-500 MB.
    #
    # WARNING: Set too high → driver tries to collect and broadcast a
    # huge table → driver OOM. Test before raising beyond 512 MB.
    .config("spark.sql.autoBroadcastJoinThreshold", str(50 * 1024 * 1024))  # 50 MB

    # --- ADAPTIVE QUERY EXECUTION (AQE) ---
    # AQE re-optimizes the query plan at runtime using actual statistics
    # from completed shuffle stages. This is near-magic for most perf issues.
    #
    # Default: true in Spark 3.2+. Explicitly set it to be safe.
    #
    # AQE automatically:
    #   1. Coalesces small shuffle partitions (merge 400 empty partitions
    #      into 10 non-trivial ones after aggregation).
    #   2. Converts sort-merge join to broadcast join at runtime (if one
    #      side turns out small after filtering).
    #   3. Handles skewed partitions (splits large partitions).
    .config("spark.sql.adaptive.enabled", "true")

    # AQE skew join: detect and mitigate skewed partitions automatically.
    # A partition is "skewed" if it's > 5× the median and > skewedPartitionThresholdInBytes.
    .config("spark.sql.adaptive.skewJoin.enabled", "true")
    .config("spark.sql.adaptive.skewJoin.skewedPartitionFactor", "5")
    .config("spark.sql.adaptive.skewJoin.skewedPartitionThresholdInBytes", str(256 * 1024 * 1024))

    # AQE coalesce: merge tiny post-shuffle partitions.
    # advisoryPartitionSizeInBytes = target size for coalesced partitions.
    .config("spark.sql.adaptive.coalescePartitions.enabled", "true")
    .config("spark.sql.adaptive.advisoryPartitionSizeInBytes", str(64 * 1024 * 1024))

    # --- SPECULATIVE EXECUTION ---
    # Detects "straggler" tasks (running much longer than peers) and
    # launches a duplicate copy on another executor. First to finish wins.
    #
    # When to enable: jobs with unpredictable task times (e.g., calling
    # external APIs per partition, non-uniform data distribution).
    # When NOT to enable: tasks with side effects (writing to DB, Kafka).
    .config("spark.speculation", "true")
    .config("spark.speculation.multiplier", "3")   # 3× median task time = straggler
    .config("spark.speculation.quantile", "0.90")   # wait until 90% tasks done

    # --- EXECUTOR SIZING: RULE OF 4 ---
    # 4 cores per executor, memory = 4 × 4 GB = 16 GB.
    # Reason: more cores per executor → HDFS throughput drops (HDFS client
    # has per-JVM thread contention above ~5 threads).
    # Memory overhead: Spark needs off-heap memory for JVM internals.
    # Set memoryOverhead to 10% of executor memory (minimum 384 MB).
    .config("spark.executor.cores", "4")
    .config("spark.executor.memory", "16g")
    .config("spark.executor.memoryOverhead", "2g")   # 10% of 16g + buffer
    .config("spark.driver.memory", "8g")

    # --- MEMORY FRACTIONS ---
    # spark.memory.fraction: fraction of JVM heap used for Spark
    # execution + storage. Default 0.6. Remaining 0.4 = user data
    # structures (Python objects, UDF overhead, etc.)
    #
    # spark.memory.storageFraction: within the Spark fraction, this
    # share is reserved for cached RDDs/DataFrames. Default 0.5.
    # So: 0.6 × 0.5 = 30% of total heap for cache.
    #
    # Tune: if cache-heavy (lots of .cache() calls) → raise storageFraction.
    #        if compute-heavy (complex joins, aggregations) → lower storageFraction.
    .config("spark.memory.fraction", "0.6")
    .config("spark.memory.storageFraction", "0.5")

    # --- DYNAMIC ALLOCATION ---
    # Let Spark request more executors when tasks queue up, release
    # idle executors. Best for shared clusters or variable workloads.
    # Disable for fixed-cost batch jobs where you want predictable perf.
    .config("spark.dynamicAllocation.enabled", "false")   # explicit for this demo

    # --- KRYO SERIALIZATION ---
    # Default Java serialization is slow and large. Kryo is 3-5×
    # faster and produces smaller serialized objects.
    # Required for: shuffles, caching serialized RDDs, broadcasting.
    .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")

    .master("local[4]")
    .getOrCreate()
)

spark.sparkContext.setLogLevel("WARN")

# ============================================================
# SECTION 2: SHUFFLE PARTITIONS — HANDS-ON DEMONSTRATION
# ============================================================

print("=== SECTION 2: Shuffle Partitions ===")

# Simulate a dataset. In production this is a Parquet read from S3.
orders_data = [(i, f"user_{i % 1000}", float(i * 1.5), "2024-01-01") for i in range(100_000)]
orders = spark.createDataFrame(orders_data, ["order_id", "user_id", "amount", "date"])

# Without tuning: default 200 shuffle partitions regardless of data size.
# For 100K rows this creates 200 tiny partitions after aggregation.
spark.conf.set("spark.sql.shuffle.partitions", "200")
bad_agg = orders.groupBy("user_id").agg(F.sum("amount").alias("total_amount"))
# bad_agg.explain()  # Uncomment to see query plan

# Tuned: match to data + cluster
# Rule: total shuffle data / 128MB, minimum = 2× CPU cores
# For 100K rows (~10 MB) → 1 partition is plenty. Set 8 for safety.
spark.conf.set("spark.sql.shuffle.partitions", "8")
good_agg = orders.groupBy("user_id").agg(F.sum("amount").alias("total_amount"))

# After AQE is enabled, Spark would auto-coalesce the 200 partitions
# down to the right number anyway. AQE = automatic version of this.

print(f"Partition count after aggregation: {good_agg.rdd.getNumPartitions()}")

# ============================================================
# SECTION 3: PARTITION COUNT AFTER FILE READS
# ============================================================
# Parquet: Spark creates one task per Parquet file, but splits files
# larger than maxPartitionBytes (128 MB default) into multiple tasks.
#   - 10 files of 50 MB each → 10 tasks (each < 128 MB, no split)
#   - 10 files of 256 MB each → 20 tasks (each split into 2 × 128 MB)
#   - 10000 files of 1 KB each → 10000 tasks (1 task per file, tiny!)
#
# CSV/JSON: one task per HDFS block (128 MB). Splittable because
# text format can start reading at any byte offset.
#
# Problem: too many small files (common with streaming or frequent
# incremental writes) → thousands of tasks, overhead dominates.
# Solution: coalesce() or repartition() after read, or OPTIMIZE in Delta.

# Demonstrate partition count tuning after a read
# (using our in-memory DF as stand-in for file read)
print(f"\nPartitions before repartition: {orders.rdd.getNumPartitions()}")

# repartition() → full shuffle, evenly distributes. Use when increasing
# partition count or when you need even distribution.
orders_repartitioned = orders.repartition(16)
print(f"Partitions after repartition(16): {orders_repartitioned.rdd.getNumPartitions()}")

# coalesce() → no shuffle (or minimal shuffle), merges existing partitions.
# Use when DECREASING partition count. Much cheaper than repartition().
# LIMITATION: can produce uneven partitions (some tasks slow).
orders_coalesced = orders.coalesce(4)
print(f"Partitions after coalesce(4): {orders_coalesced.rdd.getNumPartitions()}")

# ============================================================
# SECTION 4: BROADCAST JOINS
# ============================================================
print("\n=== SECTION 4: Broadcast Joins ===")

# Sort-merge join (default for large tables):
#   1. Sort both sides by join key.
#   2. Merge-join the sorted data.
#   Cost: TWO shuffles (one per side). Expensive on large data.
#
# Broadcast join:
#   1. Collect one (small) side to driver.
#   2. Broadcast (copy) it to every executor.
#   3. Each executor joins its partition against the local copy.
#   Cost: ZERO shuffles. 10-100× faster when one side is small.
#
# Auto-broadcast: triggered when table < autoBroadcastJoinThreshold.
# AQE also auto-converts sort-merge → broadcast at runtime if one
# side is small after filtering (even if estimated large initially).

# Create a small dimension table (cities → region mapping)
# In production: 50-row country table, 500-row product category table, etc.
cities_data = [("New York", "Northeast"), ("Los Angeles", "West"),
               ("Chicago", "Midwest"), ("Houston", "South")]
cities = spark.createDataFrame(cities_data, ["city", "region"])

# Create a large fact table
orders_with_city = orders.withColumn(
    "city",
    F.when(F.col("order_id") % 4 == 0, "New York")
     .when(F.col("order_id") % 4 == 1, "Los Angeles")
     .when(F.col("order_id") % 4 == 2, "Chicago")
     .otherwise("Houston")
)

# EXPLICIT broadcast hint: forces broadcast even if table is above threshold.
# Use when you KNOW the table is small but Spark doesn't (e.g., after filters
# that Spark's optimizer doesn't know will eliminate most rows).
result = orders_with_city.join(
    F.broadcast(cities),  # <-- explicit hint
    on="city",
    how="left"
)

# View the plan: look for "BroadcastHashJoin" vs "SortMergeJoin"
result.explain()  # Will show BroadcastHashJoin

# ============================================================
# SECTION 5: DATA SKEW — DETECTION AND SOLUTIONS
# ============================================================
print("\n=== SECTION 5: Data Skew ===")

# WHAT IS DATA SKEW:
# One (or a few) partition(s) has dramatically more data than others.
# Symptom: 199 tasks complete in 30 seconds, 1 task runs for 20 minutes.
# The entire stage is held up by the slowest partition.
#
# COMMON CAUSES:
#   - Popular keys: user_id=0 is the "unknown" user with 5M rows.
#   - Null keys: all NULLs land in the same partition.
#   - Power-law distribution: top 1% of users generate 90% of orders.
#
# DETECTION:
#   1. Spark UI → Stages → click stage → see task duration distribution.
#   2. Check: df.groupBy("key").count().orderBy(F.desc("count")).show(20)

# Simulate a heavily skewed dataset
# user_0 has 50,000 rows; all others share the remaining 50,000
skewed_data = (
    [(0, float(i)) for i in range(50_000)] +       # 50% of data in one key
    [(i % 999 + 1, float(i)) for i in range(50_000)]  # rest spread across 999 keys
)
skewed_df = spark.createDataFrame(skewed_data, ["user_id", "amount"])

# Check for skew
skew_check = (
    skewed_df
    .groupBy("user_id")
    .count()
    .orderBy(F.desc("count"))
)
print("Top 5 keys by row count (skew detection):")
skew_check.show(5)

# ---- SOLUTION 1: SALTING ----
# Append a random number (the "salt") to the skewed join key.
# This spreads rows across multiple partitions.
#
# CRITICAL: you must apply the salt to BOTH sides of the join.
# Fact side: add random salt 0..N-1
# Dim side: explode the salt (create N copies of each row, one per salt value)

SALT_FACTOR = 16  # number of "virtual keys" per original key

# Salt the fact table
salted_fact = skewed_df.withColumn(
    "salted_user_id",
    F.concat_ws("_", F.col("user_id"), (F.rand() * SALT_FACTOR).cast("int"))
)

# Create a small dimension table to join against
user_data = [(i, f"User_{i}") for i in range(1000)]
users = spark.createDataFrame(user_data, ["user_id", "user_name"])

# Explode the dimension table: each user_id gets SALT_FACTOR copies
# with salted keys user_id_0, user_id_1, ..., user_id_{N-1}
salted_dim = users.withColumn(
    "salt",
    F.explode(F.array([F.lit(i) for i in range(SALT_FACTOR)]))
).withColumn(
    "salted_user_id",
    F.concat_ws("_", F.col("user_id"), F.col("salt"))
)

# Now join on the salted key — data is spread evenly
salted_result = salted_fact.join(salted_dim, on="salted_user_id", how="left")
print(f"\nSalted join partition count: {salted_result.rdd.getNumPartitions()}")
# AQE skew join handles this automatically in Spark 3.2+ without salting.

# ---- SOLUTION 2: FILTER SKEWED KEYS, PROCESS SEPARATELY, UNION ----
# If you know which keys are skewed (e.g., user_id=0 is always a null user):
non_skewed = skewed_df.filter(F.col("user_id") != 0)
skewed_only = skewed_df.filter(F.col("user_id") == 0)

result_non_skewed = non_skewed.groupBy("user_id").agg(F.sum("amount"))
result_skewed = skewed_only.groupBy("user_id").agg(F.sum("amount"))

# Union the two results back together
final_result = result_non_skewed.union(result_skewed)
print(f"Final result row count: {final_result.count()}")

# ============================================================
# SECTION 6: CACHING STRATEGY
# ============================================================
print("\n=== SECTION 6: Caching ===")

# cache() stores a DataFrame in executor memory after the first action.
# Subsequent actions reuse the in-memory copy (no recomputation/reread).
#
# Use cache() when:
#   - The same DataFrame is used in multiple downstream operations in
#     the same Spark session (e.g., used in 3 different aggregations).
#   - Recomputation is expensive (large parquet reads + complex transforms).
#
# Do NOT cache() when:
#   - The DataFrame is only used once.
#   - It doesn't fit in memory (spills to disk → slower than just rereading).
#   - The job is a single linear pipeline (Spark's pipeline optimizer handles it).
#
# Storage levels (via persist()):
#   MEMORY_ONLY          → fastest, but evicts if memory pressure
#   MEMORY_AND_DISK      → spills to disk if evicted (safe default)
#   MEMORY_ONLY_SER      → serialized, smaller memory footprint
#   DISK_ONLY            → use when data is too large for memory

from pyspark import StorageLevel

# Default cache() uses MEMORY_AND_DISK_DESER (Spark 3.x default)
orders_cached = orders.cache()

# Force materialization (cache is lazy — only populated on first action)
orders_cached.count()  # First action: reads data and caches

# All subsequent actions reuse cached data
agg1 = orders_cached.groupBy("user_id").agg(F.count("*").alias("order_count"))
agg2 = orders_cached.groupBy("date").agg(F.sum("amount").alias("daily_revenue"))
# Both use cached data — no re-read from source

# CRITICAL: always unpersist when done
# Without unpersist(), cache persists until executor memory eviction or
# Spark session ends, wasting memory for other operations.
orders_cached.unpersist()
print("Cache unpersisted — memory freed.")

# ============================================================
# SECTION 7: FILE FORMATS AND PREDICATE PUSHDOWN
# ============================================================
print("\n=== SECTION 7: File Formats ===")

# FILE FORMAT COMPARISON:
#
# CSV / JSON
#   - Row-based: reading 1 column means reading all columns.
#   - No schema enforcement: silent type coercions.
#   - No predicate pushdown: Spark must read all data then filter.
#   - Good for: interchange, debugging, small files.
#
# ORC
#   - Columnar, compressed. HIVE-native.
#   - Supports predicate pushdown and column pruning.
#   - BLOOM FILTER statistics per stripe.
#   - Good for: Hive workloads.
#
# PARQUET (preferred for Spark analytics)
#   - Columnar: reading 3 columns out of 100 reads only those columns.
#   - Snappy compressed by default (fast, reasonable compression).
#   - Embedded schema (no schema-on-read ambiguity).
#   - Row group statistics (min/max per column per row group).
#   - Predicate pushdown: Spark reads row group statistics → skips row
#     groups where min/max tells us no matching rows exist.
#   - Compatible with: Spark, Hive, Presto, BigQuery, Athena, DuckDB.

# Writing Parquet with Snappy compression (default in Spark)
import tempfile, os

tmp_dir = tempfile.mkdtemp()
parquet_path = os.path.join(tmp_dir, "orders_parquet")

# partitionBy creates a directory per unique value of "date"
# → enables partition pruning (see Section 8)
orders.write.mode("overwrite").partitionBy("date").parquet(parquet_path)
print(f"Parquet written to: {parquet_path}")

# ============================================================
# SECTION 8: PARTITION PRUNING
# ============================================================
print("\n=== SECTION 8: Partition Pruning ===")

# WHAT IS PARTITION PRUNING:
# When data is stored partitioned by a column (e.g., date), Spark can
# use the filter predicate to skip entire directories of data.
#
# Without partition pruning: read all files, then filter → wastes I/O.
# With partition pruning:  read only 2024-01-01 directory → 99% less I/O
#                          for a daily query on years of data.
#
# REQUIREMENTS:
#   1. Data must be physically partitioned: .write.partitionBy("date").
#   2. Filter must be on the partition column (not derived from it).
#   3. Use Hive metastore (or Delta) — Spark reads directory names.
#
# Partition pruning works automatically when Spark knows which
# directories exist (file listing → filter by directory name).

orders_from_parquet = spark.read.parquet(parquet_path)

# This read only accesses the 2024-01-01 partition directory
pruned_read = orders_from_parquet.filter(F.col("date") == "2024-01-01")
print("Partition pruned query plan:")
pruned_read.explain()
# Look for "PartitionFilters" in the scan node → pruning is active.

# ============================================================
# SECTION 9: BUCKETING
# ============================================================
print("\n=== SECTION 9: Bucketing ===")

# WHAT IS BUCKETING:
# Pre-partition data by a column's hash into a fixed number of buckets.
# Both sides of a join bucketed on the join key with the same bucket count
# → Spark co-locates matching rows on the same executor → ZERO shuffle.
#
# Also pre-sorts within each bucket → sort-merge join becomes merge-only
# (skip the sort phase).
#
# WHEN TO USE:
#   - Large tables joined repeatedly on the same key (e.g., user_id).
#   - Avoids shuffle on every join → massive savings for repeated joins.
#
# LIMITATIONS:
#   - Only works with Hive metastore (saveAsTable, not save).
#   - Bucket count must match on both sides of join.
#   - Initial write is more expensive (shuffle during bucketed write).
#   - Not supported on all file systems equally.

# In production (with Hive metastore):
#
# orders.write.bucketBy(256, "user_id").sortBy("user_id") \
#             .mode("overwrite").saveAsTable("orders_bucketed")
#
# users.write.bucketBy(256, "user_id").sortBy("user_id") \
#            .mode("overwrite").saveAsTable("users_bucketed")
#
# orders_b = spark.table("orders_bucketed")
# users_b  = spark.table("users_bucketed")
# result = orders_b.join(users_b, "user_id")
# → Spark uses BucketedHashJoin (no shuffle) instead of SortMergeJoin

print("Bucketing demo requires Hive metastore — see comments above.")

# ============================================================
# SECTION 10: READING MANY SMALL FILES
# ============================================================
print("\n=== SECTION 10: Small Files Problem ===")

# Problem: 100,000 files of 1 KB each on S3.
# Each file → 1 Spark task → 100,000 tasks.
# Task scheduling overhead per task: ~10-100 ms.
# Total overhead: 100,000 × 50 ms = 83 minutes of pure overhead.
#
# Solutions:
#   1. coalesce() after read: merge into fewer partitions.
#   2. Increase maxPartitionBytes: Spark groups small files together.
#      (Only works within a single directory — cross-file grouping.)
#   3. OPTIMIZE (Delta Lake): compacts small files periodically.
#   4. Wholetext / binary reads: spark.read.text() on directory groups files.
#   5. Pre-process with EMR S3DistCp or similar to compact files.

# Simulated fix with coalesce after a multi-file read
many_small = orders.repartition(1000)   # simulate 1000 small partitions
print(f"Before coalesce: {many_small.rdd.getNumPartitions()} partitions")

compacted = many_small.coalesce(16)     # merge down to 16 sensible partitions
print(f"After coalesce:  {compacted.rdd.getNumPartitions()} partitions")

# ============================================================
# SECTION 11: REAL CASE — 2 HOURS TO 8 MINUTES
# ============================================================
print("\n=== SECTION 11: Full Optimization Example ===")

# Starting point: naive job on 1 TB of order data
# Problem symptoms:
#   - 2 hour runtime
#   - Spark UI shows 1 task running 100× longer than others (skew)
#   - Stage 4 has 200 shuffle partitions, each 5 GB (spill)
#   - A 10 MB product dimension table is being shuffle-joined
#
# STEP-BY-STEP OPTIMIZATION:

# Step 1: Enable AQE (auto-coalesces shuffle partitions, auto-broadcasts,
#          auto-handles skew). This alone often cuts time by 30-50%.
spark.conf.set("spark.sql.adaptive.enabled", "true")
spark.conf.set("spark.sql.adaptive.skewJoin.enabled", "true")

# Step 2: Add partition pruning — ensure filters use partition column.
# Before: spark.read.parquet("s3://orders/").filter(col("date") > "2024-01-01")
# After:  spark.read.parquet("s3://orders/date=2024-01-01/")
#         OR ensure data is partitioned by date and filter column matches.

# Step 3: Cache the intermediate silver table used in 3 aggregations.
# Read raw → clean → cache; then run 3 aggregations against cache.
silver = orders.filter(F.col("amount") > 0).cache()
silver.count()   # materialize cache

# Step 4: Tune shuffle partitions for the specific shuffle size.
# 1 TB shuffle → 1,000,000 MB / 128 MB = ~7800 partitions.
spark.conf.set("spark.sql.shuffle.partitions", "7800")
# (AQE will coalesce down from 7800 if actual partitions are small.)

# Step 5: Broadcast the small dimension table explicitly.
product_data = [(i, f"Product_{i}", "Electronics") for i in range(5000)]
products = spark.createDataFrame(product_data, ["product_id", "product_name", "category"])
# products is 5000 rows × ~50 bytes = ~250 KB → safely broadcastable

orders_with_product = orders.withColumn("product_id", (F.col("order_id") % 5000))
enriched = orders_with_product.join(F.broadcast(products), on="product_id")

# Step 6: Compute aggregations (all use cached silver data)
revenue_by_category = (
    enriched
    .groupBy("category", "date")
    .agg(
        F.sum("amount").alias("total_revenue"),
        F.count("*").alias("order_count"),
        F.avg("amount").alias("avg_order_value")
    )
    .orderBy("date", "category")
)

revenue_by_user = (
    silver
    .groupBy("user_id")
    .agg(F.sum("amount").alias("lifetime_value"))
)

print(f"Revenue categories: {revenue_by_category.count()}")
print(f"User LTV rows:      {revenue_by_user.count()}")

# Final cleanup
silver.unpersist()

print("\n=== L05 Complete ===")
print("Key takeaways:")
print("  1. AQE first — handles 80% of perf issues automatically")
print("  2. Partition pruning — biggest win for time-partitioned data")
print("  3. Broadcast small tables — eliminate shuffle joins")
print("  4. Cache sparingly and always unpersist")
print("  5. Tune shuffle partitions to data_size / 128MB")
print("  6. Salt or use AQE skew join for skewed keys")

spark.stop()
