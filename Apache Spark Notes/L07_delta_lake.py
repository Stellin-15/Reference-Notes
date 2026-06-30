# ============================================================
# L07: Delta Lake — ACID Transactions on the Data Lake
# ============================================================
# WHAT: Delta Lake is an open-source storage layer that brings
#       ACID transactions, schema enforcement, time travel, and
#       DML operations (UPDATE/DELETE/MERGE) to data lakes built
#       on S3, ADLS, or GCS.
# WHY:  Raw Parquet on object storage has no ACID guarantees.
#       A failed write leaves corrupt partial data. You cannot
#       UPDATE or DELETE rows. Two concurrent writers corrupt
#       each other's output. Delta solves all of this with a
#       transaction log on top of plain Parquet files.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    A Delta table = Parquet files + _delta_log/ directory.
    The _delta_log/ is a sequence of JSON files (one per transaction)
    that record which Parquet files were added or removed. Reading a
    Delta table means reading the latest snapshot: the set of Parquet
    files that are "live" according to the transaction log.

    Because writes go through the log atomically, two writers cannot
    conflict silently. Delta uses optimistic concurrency: each writer
    reads the current version, performs its changes, then tries to
    commit. If another writer committed in the meantime, Delta detects
    the conflict and retries or fails with a meaningful error.

PRODUCTION USE CASE:
    CDC (Change Data Capture) pipeline from Postgres via Debezium →
    Kafka → Spark Structured Streaming → Delta Lake MERGE. Each
    Kafka message is an INSERT/UPDATE/DELETE event. MERGE upserts
    changed rows and hard-deletes removed rows atomically.

COMMON MISTAKES:
    1. Running VACUUM with RETAIN 0 HOURS — destroys time travel
       history and may break concurrent readers. Use >= 168 HOURS.
    2. Not running OPTIMIZE periodically — thousands of tiny files
       accumulate, making reads slow (the "small files problem").
    3. Z-ordering on high-cardinality columns with few reads — ZORDER
       helps when the query filter matches the ZORDER column. If you
       ZORDER by user_id but never filter by user_id, it's wasted.
    4. Using mergeSchema=True blindly — accidentally adding nullable
       columns with no values, or widening types unexpectedly.
    5. Relying on time travel beyond the VACUUM retention window —
       data is gone after VACUUM runs.
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, LongType,
    DoubleType, TimestampType, IntegerType, BooleanType
)
import tempfile, os

# Delta Lake requires the delta-core JAR on the classpath.
# In Databricks: built-in.
# Standalone: add to spark-submit:
#   --packages io.delta:delta-spark_2.12:3.1.0
# Or add to SparkSession:
spark = (
    SparkSession.builder
    .appName("L07_DeltaLake")
    # Delta Lake extension (required when running standalone)
    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
    .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
    .config("spark.sql.shuffle.partitions", "8")
    .master("local[4]")
    .getOrCreate()
)
spark.sparkContext.setLogLevel("WARN")

# Base directory for all demo Delta tables
BASE_DIR = tempfile.mkdtemp()
ORDERS_DELTA = os.path.join(BASE_DIR, "orders_delta")
CUSTOMERS_DELTA = os.path.join(BASE_DIR, "customers_delta")

print(f"Delta tables will be stored at: {BASE_DIR}")

# ============================================================
# SECTION 1: WHY NOT RAW PARQUET
# ============================================================
# Problem 1 — Partial writes corrupt the table:
#   Writer writes 5 of 10 Parquet files, then fails.
#   Reader sees partial data. No way to know which files are valid.
#
# Problem 2 — No UPDATE or DELETE:
#   To update one row, you must rewrite the entire file/partition.
#   No transactional guarantee that other readers see a consistent view.
#
# Problem 3 — Concurrent writers overwrite each other:
#   Two Spark jobs write to the same partition simultaneously.
#   Second writer's output silently overwrites the first.
#
# Problem 4 — No schema enforcement:
#   A new column written to a Parquet directory is read by old readers
#   as null. A column removed is silently missing. No alert.
#
# Delta solves ALL of these with the transaction log.

# ============================================================
# SECTION 2: CREATING A DELTA TABLE
# ============================================================
print("=== SECTION 2: Creating Delta Table ===")

# Create sample order data
orders_data = [
    (1, "user_001", "product_A", 150.0, "2024-01-01", "pending"),
    (2, "user_002", "product_B", 89.99, "2024-01-01", "shipped"),
    (3, "user_001", "product_C", 299.0, "2024-01-02", "pending"),
    (4, "user_003", "product_A", 150.0, "2024-01-02", "cancelled"),
    (5, "user_004", "product_D", 45.0, "2024-01-03", "shipped"),
]
orders_schema = StructType([
    StructField("order_id", IntegerType()),
    StructField("user_id", StringType()),
    StructField("product_id", StringType()),
    StructField("amount", DoubleType()),
    StructField("order_date", StringType()),
    StructField("status", StringType()),
])
orders_df = spark.createDataFrame(orders_data, orders_schema)

# Write as Delta table
# partitionBy is optional but recommended for large tables.
# Partitioning on order_date enables partition pruning on date filters.
orders_df.write \
    .format("delta") \
    .mode("overwrite") \
    .partitionBy("order_date") \
    .save(ORDERS_DELTA)

print(f"Delta table written to: {ORDERS_DELTA}")
print("_delta_log directory contains transaction log JSON files.")
# ls ORDERS_DELTA/_delta_log/ → 00000000000000000000.json (commit 0)

# ============================================================
# SECTION 3: READING A DELTA TABLE
# ============================================================
print("\n=== SECTION 3: Reading Delta Table ===")

orders_read = spark.read.format("delta").load(ORDERS_DELTA)
orders_read.show()
print(f"Schema: {orders_read.schema.simpleString()}")

# Partition pruning works exactly as with Parquet:
daily_orders = (
    orders_read
    .filter(F.col("order_date") == "2024-01-01")
)
daily_orders.explain()   # Should show PartitionFilters: order_date=2024-01-01

# ============================================================
# SECTION 4: ACID — UPDATE AND DELETE
# ============================================================
# Raw Parquet: no native UPDATE or DELETE.
# Delta: full DML support. Each DML operation is an atomic transaction.
# The transaction log records which files were removed (old) and added (new).
# A reader mid-transaction sees either the old snapshot or the new one. Never both.

# Delta SQL approach (requires Spark SQL session with Delta catalog)
# Programmatic approach via DeltaTable API:

try:
    from delta.tables import DeltaTable

    delta_table = DeltaTable.forPath(spark, ORDERS_DELTA)

    # UPDATE: change status of order 1 from "pending" to "processing"
    # Under the hood: Delta reads affected files, rewrites with updated rows,
    # adds new files to log, marks old files as removed (not deleted from disk yet).
    delta_table.update(
        condition=F.col("order_id") == 1,
        set={"status": F.lit("processing")}
    )
    print("\nAfter UPDATE order_id=1:")
    spark.read.format("delta").load(ORDERS_DELTA).filter(F.col("order_id") == 1).show()

    # DELETE: remove cancelled orders
    delta_table.delete(condition=F.col("status") == "cancelled")
    print("After DELETE cancelled orders:")
    spark.read.format("delta").load(ORDERS_DELTA).show()

except ImportError:
    print("delta package not available — UPDATE/DELETE shown as SQL comments.")
    # Equivalent SQL:
    # spark.sql("UPDATE delta.`path` SET status='processing' WHERE order_id=1")
    # spark.sql("DELETE FROM delta.`path` WHERE status='cancelled'")

# ============================================================
# SECTION 5: MERGE (UPSERT)
# ============================================================
# MERGE is the workhorse of incremental Delta pipelines.
# Replaces the pattern: read full table → deduplicate → overwrite.
# Instead: only touch rows that changed.
#
# MERGE logic:
#   For each source row:
#     IF source.id matches target.id:
#       WHEN MATCHED AND source.is_delete = true  → DELETE target row
#       WHEN MATCHED AND source.is_delete = false → UPDATE target row
#     IF NO MATCH:
#       WHEN NOT MATCHED → INSERT new row

# Simulate incoming CDC events (Debezium format from Postgres)
# op: 'c' = create/insert, 'u' = update, 'd' = delete
cdc_data = [
    # Update order 2's status to "delivered"
    (2, "user_002", "product_B", 89.99, "2024-01-01", "delivered", False),
    # Insert a brand new order
    (6, "user_005", "product_E", 199.0, "2024-01-04", "pending", False),
    # Delete order 5 (customer cancelled)
    (5, None, None, None, None, None, True),
]
cdc_schema = StructType([
    StructField("order_id", IntegerType()),
    StructField("user_id", StringType()),
    StructField("product_id", StringType()),
    StructField("amount", DoubleType()),
    StructField("order_date", StringType()),
    StructField("status", StringType()),
    StructField("is_delete", BooleanType()),
])
cdc_df = spark.createDataFrame(cdc_data, cdc_schema)

try:
    from delta.tables import DeltaTable

    delta_table = DeltaTable.forPath(spark, ORDERS_DELTA)

    (
        delta_table.alias("target")
        .merge(
            source=cdc_df.alias("source"),
            condition="target.order_id = source.order_id"
        )
        # DELETE matching rows flagged for deletion
        .whenMatchedDelete(condition="source.is_delete = true")
        # UPDATE matching rows not flagged for deletion
        .whenMatchedUpdate(
            condition="source.is_delete = false",
            set={
                "status": "source.status",
                "amount": "source.amount",
            }
        )
        # INSERT new rows (no match in target)
        .whenNotMatchedInsertAll()
        .execute()
    )

    print("\nAfter MERGE (CDC upsert):")
    spark.read.format("delta").load(ORDERS_DELTA).orderBy("order_id").show()

except ImportError:
    print("delta package not available — MERGE shown as SQL comment.")
    # SQL equivalent:
    # MERGE INTO delta.`/path/orders` AS target
    # USING cdc_table AS source ON target.order_id = source.order_id
    # WHEN MATCHED AND source.is_delete = true THEN DELETE
    # WHEN MATCHED AND source.is_delete = false THEN UPDATE SET ...
    # WHEN NOT MATCHED THEN INSERT *

# ============================================================
# SECTION 6: TIME TRAVEL
# ============================================================
# Every transaction in Delta creates a new version.
# You can read any previous version by specifying:
#   - VERSION AS OF N (version number)
#   - TIMESTAMP AS OF 'datetime string'
#
# Use cases:
#   1. Audit: "What did the table look like at 2 PM yesterday?"
#   2. Rollback: Read version N-1, overwrite current table.
#   3. ML reproducibility: Pin training data to version 100.
#   4. Debugging: "When did this bad row appear?"
#
# Time travel works by reading the transaction log to reconstruct
# which files were present at that version → reads those Parquet files.

print("\n=== SECTION 6: Time Travel ===")

# Read version 0 (initial write before any updates)
initial_version = (
    spark.read
    .format("delta")
    .option("versionAsOf", 0)
    .load(ORDERS_DELTA)
)
print("Table at version 0 (initial state):")
initial_version.show()

# Read current version
current_version = spark.read.format("delta").load(ORDERS_DELTA)
print("Table at current version:")
current_version.show()

# SQL equivalent:
# SELECT * FROM delta.`/path/orders` VERSION AS OF 0
# SELECT * FROM delta.`/path/orders` TIMESTAMP AS OF '2024-01-01 10:00:00'

# List transaction history
try:
    from delta.tables import DeltaTable
    history = DeltaTable.forPath(spark, ORDERS_DELTA).history()
    print("Transaction history:")
    history.select("version", "timestamp", "operation", "operationParameters").show(truncate=False)
except ImportError:
    print("DeltaTable not available — showing history via SQL:")
    # spark.sql(f"DESCRIBE HISTORY delta.`{ORDERS_DELTA}`").show()

# ============================================================
# SECTION 7: SCHEMA ENFORCEMENT AND EVOLUTION
# ============================================================
print("\n=== SECTION 7: Schema Enforcement ===")

# Schema enforcement = Delta rejects writes that don't match the table schema.
# This is the OPPOSITE of raw Parquet (which accepts anything silently).

# This would FAIL with Delta (schema enforcement):
bad_data = spark.createDataFrame(
    [(99, "user_X", "product_Z", 10.0, "2024-01-01", "pending", "EXTRA_COLUMN")],
    ["order_id", "user_id", "product_id", "amount", "order_date", "status", "unexpected_col"]
)
try:
    bad_data.write.format("delta").mode("append").save(ORDERS_DELTA)
    print("Write succeeded (delta package may not enforce schema here)")
except Exception as e:
    print(f"Schema enforcement BLOCKED write: {type(e).__name__}")

# Schema evolution: opt-in by adding mergeSchema=True
# This allows ADDING new nullable columns.
new_data_with_extra = (
    spark.createDataFrame(
        [(10, "user_006", "product_F", 75.0, "2024-01-05", "pending", "PRIO")],
        ["order_id", "user_id", "product_id", "amount", "order_date", "status", "priority"]
    )
)
new_data_with_extra.write \
    .format("delta") \
    .mode("append") \
    .option("mergeSchema", "true") \     # allow adding "priority" column
    .save(ORDERS_DELTA)

print("\nAfter mergeSchema write (new 'priority' column added):")
spark.read.format("delta").load(ORDERS_DELTA).show(truncate=False)
# Existing rows will have null for the new "priority" column.

# ============================================================
# SECTION 8: OPTIMIZE AND Z-ORDERING
# ============================================================
# OPTIMIZE compacts small Parquet files into larger ones (target: 1 GB).
# Why: streaming writes, frequent small merges, and incremental appends
# produce thousands of small files → many tasks → slow reads.
#
# ZORDER BY: co-locate rows with the same value of a column in the same
# Parquet files. Combined with Delta's file statistics (min/max per column
# per file), Spark can SKIP entire files that can't satisfy the filter.
#
# Example:
#   Without ZORDER: a query WHERE user_id='user_001' must scan all files.
#   With ZORDER BY user_id: all user_001 rows are in the same few files.
#     Delta sees file statistics: min_user_id='user_001', max_user_id='user_001'
#     → only reads those files, skips the rest.
#
# Best ZORDER candidates:
#   - High-cardinality columns used frequently in WHERE clauses.
#   - Join keys (user_id, product_id).
#   - NOT partition columns (partitioning already handles coarse-grained skipping).

# SQL (preferred for OPTIMIZE — no Python API in open-source Delta):
# OPTIMIZE delta.`/path/orders` ZORDER BY (user_id, order_date)
#
# DeltaTable Python API:
try:
    from delta.tables import DeltaTable
    # OPTIMIZE without ZORDER (just compaction)
    DeltaTable.forPath(spark, ORDERS_DELTA).optimize().executeCompaction()
    # OPTIMIZE with ZORDER
    # DeltaTable.forPath(spark, ORDERS_DELTA).optimize().executeZOrderBy("user_id")
    print("OPTIMIZE executed successfully.")
except (ImportError, AttributeError):
    print("OPTIMIZE API requires delta >= 2.0 — use SQL: OPTIMIZE delta.`path` ZORDER BY (user_id)")

# ============================================================
# SECTION 9: VACUUM
# ============================================================
# VACUUM deletes old Parquet files that are no longer referenced by
# the current (or recent) transaction log.
#
# These "obsolete" files accumulate from:
#   - UPDATE / DELETE operations (old files kept for time travel)
#   - OPTIMIZE (old small files kept for time travel)
#   - Failed writes (partial data never committed)
#
# Default retention: 7 days (168 hours).
# DO NOT reduce below 168 hours in production unless you are certain
# no reader is reading an old version (long-running jobs, BI tools).
#
# RETAIN N HOURS protects files that were removed from the log fewer
# than N hours ago. Lower = less storage, less time travel history.

# SQL equivalent (requires catalog):
# SET spark.databricks.delta.retentionDurationCheck.enabled = false;  -- only for < 7 days
# VACUUM delta.`/path/orders` RETAIN 168 HOURS;

try:
    from delta.tables import DeltaTable
    # Uncomment to run (takes a few seconds):
    # DeltaTable.forPath(spark, ORDERS_DELTA).vacuum(retentionHours=168)
    print("VACUUM would delete files older than 168 hours (7 days).")
except ImportError:
    print("DeltaTable API not available — use SQL: VACUUM delta.`path` RETAIN 168 HOURS")

# ============================================================
# SECTION 10: CHANGE DATA FEED (CDF)
# ============================================================
# CDF records row-level changes (insert/update/delete) as the table is modified.
# Consumers can read only the changes since their last checkpoint.
#
# Enable on table creation:
#   .option("delta.enableChangeDataFeed", "true")
# Or alter existing table:
#   ALTER TABLE SET TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
#
# Reading CDF:
#   spark.read.format("delta")
#       .option("readChangeFeed", "true")
#       .option("startingVersion", 5)   # or startingTimestamp
#       .load("path")
# Returns additional columns:
#   _change_type: "insert", "update_preimage", "update_postimage", "delete"
#   _commit_version: Delta version when this change was committed
#   _commit_timestamp: timestamp of the commit
#
# Use cases:
#   1. Stream Delta table changes into downstream Silver tables (without Kafka).
#   2. Maintain real-time search index by streaming changes to Elasticsearch.
#   3. Audit trail of all row modifications.

print("\n=== SECTION 10: Change Data Feed ===")
print("CDF requires TBLPROPERTIES set at table creation or via ALTER TABLE.")
print("Then: spark.read.format('delta').option('readChangeFeed','true')")
print("      .option('startingVersion', N).load(path)")

# ============================================================
# SECTION 11: MEDALLION ARCHITECTURE
# ============================================================
# The canonical Delta Lake architecture with three layers:
#
# BRONZE (Raw / Ingestion)
#   - Exact copy of source data, no transformations.
#   - Schema-on-read: accept anything, store everything.
#   - Append-only (no deletes).
#   - Purpose: immutable audit trail of all inbound data.
#   - Example: raw JSON from Kafka, raw CSV from SFTP drops.
#
# SILVER (Cleaned / Enriched)
#   - Deduplicated: remove duplicate events (exactly-once guarantees).
#   - Validated: null checks, type casts, range checks.
#   - Enriched: join with dimension tables (product catalog, customer info).
#   - Conformed: standardized date formats, currency, units.
#   - Purpose: analyst-ready, domain-agnostic fact tables.
#   - Example: cleaned order events with product names and customer regions.
#
# GOLD (Aggregated / Business-Ready)
#   - Pre-aggregated for specific business questions.
#   - Denormalized for query performance.
#   - BI/ML-ready: directly queryable by Tableau, Power BI, Redshift Spectrum.
#   - Purpose: answer specific business questions fast.
#   - Example: daily revenue by product category and region.
#
# Each layer is a Delta table. Each layer reads from the previous.
# Airflow / Databricks Workflows orchestrate the DAGs.

def ingest_to_bronze(raw_df, bronze_path):
    """
    Bronze layer: append raw data with ingestion metadata.
    No transformation — schema enforcement is OFF (accept anything).
    """
    (
        raw_df
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source", F.lit("orders_api"))
        .write
        .format("delta")
        .mode("append")
        # mergeSchema: accept new columns as the API evolves
        .option("mergeSchema", "true")
        .save(bronze_path)
    )
    print(f"Bronze: {raw_df.count()} rows ingested.")

def transform_to_silver(bronze_path, silver_path):
    """
    Silver layer: deduplicate, validate, enrich.
    """
    bronze = spark.read.format("delta").load(bronze_path)

    silver = (
        bronze
        # Deduplicate: keep latest record per order_id
        .withColumn(
            "_row_num",
            F.row_number().over(
                # Window requires import — shown inline for clarity
                __import__("pyspark.sql.window", fromlist=["Window"])
                .Window.partitionBy("order_id")
                .orderBy(F.desc("_ingested_at"))
            )
        )
        .filter(F.col("_row_num") == 1)
        .drop("_row_num")

        # Validate: drop rows with null order_id (corrupt data)
        .filter(F.col("order_id").isNotNull())

        # Validate: amount must be positive
        .filter(F.col("amount") > 0)

        # Enrich: parse order_date to proper date type
        .withColumn("order_date_ts", F.to_date("order_date", "yyyy-MM-dd"))
    )

    (
        silver.write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .save(silver_path)
    )
    print(f"Silver: {silver.count()} rows after dedup + validation.")
    return silver

def aggregate_to_gold(silver_path, gold_path):
    """
    Gold layer: aggregate for BI dashboards.
    """
    silver = spark.read.format("delta").load(silver_path)

    gold = (
        silver
        .groupBy("order_date", "product_id")
        .agg(
            F.sum("amount").alias("total_revenue"),
            F.count("*").alias("order_count"),
            F.avg("amount").alias("avg_order_value"),
            F.countDistinct("user_id").alias("unique_customers")
        )
    )

    (
        gold.write
        .format("delta")
        .mode("overwrite")
        .save(gold_path)
    )
    print(f"Gold: {gold.count()} aggregate rows.")

# Run the medallion pipeline
BRONZE_PATH = os.path.join(BASE_DIR, "bronze")
SILVER_PATH = os.path.join(BASE_DIR, "silver")
GOLD_PATH = os.path.join(BASE_DIR, "gold")

print("\n=== SECTION 11: Medallion Pipeline ===")
ingest_to_bronze(orders_df, BRONZE_PATH)
silver_df = transform_to_silver(BRONZE_PATH, SILVER_PATH)
aggregate_to_gold(SILVER_PATH, GOLD_PATH)

print("\nGold layer — daily revenue by product:")
spark.read.format("delta").load(GOLD_PATH).orderBy("order_date", "product_id").show()

print("\n=== L07 Complete ===")
print("Key takeaways:")
print("  1. Delta = Parquet + transaction log → ACID on object storage")
print("  2. MERGE is the primary ingestion pattern (CDC, upsert)")
print("  3. Time travel = read any version → audit, rollback, ML repro")
print("  4. OPTIMIZE + ZORDER periodically for read performance")
print("  5. VACUUM with >= 168h retention to preserve time travel window")
print("  6. Medallion: Bronze (raw) → Silver (clean) → Gold (aggregated)")

spark.stop()
