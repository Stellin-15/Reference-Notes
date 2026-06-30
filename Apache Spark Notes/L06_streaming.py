# ============================================================
# L06: Spark Structured Streaming
# ============================================================
# WHAT: Spark's unified streaming API — treats an infinite stream
#       of arriving data as an unbounded DataFrame. Same API as
#       batch, but adds concepts for state, time, and fault tolerance.
# WHY:  Real-time data pipelines are the norm: fraud detection in
#       milliseconds, dashboards updating per minute, event-driven
#       microservices. Structured Streaming makes these possible at
#       scale with exactly the same DataFrame API you already know.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    Structured Streaming models an infinite stream as a table that
    keeps growing. You write a query against this "input table" and
    Spark runs it incrementally as new data arrives. The result is
    written to a "result table" (the sink). You never write a
    loop — Spark handles the micro-batch scheduling.

PRODUCTION USE CASE:
    Real-time fraud detection: read credit card transactions from
    Kafka, compute per-user transaction counts in a 5-minute window,
    flag users with > 10 transactions as suspicious, publish alerts
    back to a Kafka DLQ topic. Entire pipeline: < 30 second latency.

COMMON MISTAKES:
    1. Using output mode "complete" on a large result table — you
       write the entire table every micro-batch, crushing the sink.
    2. Forgetting withWatermark() on a windowed aggregation — Spark
       accumulates infinite state and the job eventually OOMs.
    3. Not setting checkpointLocation — on restart, the job
       reprocesses from the beginning (duplicate data) or fails.
    4. Writing non-idempotent code in foreachBatch — since delivery
       is at-least-once, duplicate processing must be safe.
    5. Using socket source in production — it is single-node,
       unscalable, and has no fault tolerance.
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, LongType,
    DoubleType, TimestampType, IntegerType
)
import tempfile, os

spark = (
    SparkSession.builder
    .appName("L06_StructuredStreaming")
    # AQE is less relevant for streaming (each micro-batch is planned
    # independently) but leave enabled.
    .config("spark.sql.adaptive.enabled", "true")
    # Shuffle partitions for streaming micro-batches: keep low.
    # Each micro-batch is small — 200 shuffle partitions is overkill.
    .config("spark.sql.shuffle.partitions", "4")
    .master("local[4]")
    .getOrCreate()
)
spark.sparkContext.setLogLevel("WARN")

# ============================================================
# SECTION 1: STREAMING SOURCES OVERVIEW
# ============================================================
# Spark supports several streaming sources:
#
# 1. KAFKA (most common in production)
#    - Distributed, fault-tolerant, high-throughput.
#    - Spark tracks offsets per partition.
#    - Supports exactly-once semantics with idempotent sinks.
#
# 2. FILES (directory watch mode)
#    - Spark polls a directory for new files.
#    - Good for: landing zone ingestion (S3 → Bronze Delta).
#    - Each new file = a micro-batch.
#    - Supports: JSON, CSV, Parquet, ORC, text.
#
# 3. SOCKET (testing only)
#    - Reads lines from a TCP socket.
#    - Single-node, no fault tolerance, data loss on restart.
#    - Never use in production.
#
# 4. RATE (synthetic, for testing and benchmarking)
#    - Generates N rows per second.
#    - Columns: timestamp, value (monotonically increasing long).
#    - Use to test your pipeline logic without a real source.
#
# 5. DELTA LAKE (via readStream.format("delta"))
#    - Stream changes from a Delta table (append-only reads).
#    - Reads new rows as they are committed.
#    - Requires delta on the classpath.

# ============================================================
# SECTION 2: KAFKA SOURCE — READING TRANSACTIONS
# ============================================================
# Kafka message structure from Spark's perspective:
#
# Column         | Type      | Description
# ----------------------------------------
# key            | binary    | Kafka message key (partition routing)
# value          | binary    | The actual message payload
# topic          | string    | Source topic name
# partition      | int       | Kafka partition number
# offset         | long      | Offset within the partition
# timestamp      | timestamp | Message timestamp (Kafka broker time)
# timestampType  | int       | 0=CreateTime, 1=LogAppendTime
#
# The value is always binary → cast to string → parse as JSON/Avro/Protobuf.

# Kafka connection (commented out — requires running Kafka broker):
#
# raw_kafka = (
#     spark.readStream
#     .format("kafka")
#
#     # Comma-separated list of broker host:port pairs.
#     # In production: use internal DNS names, not IPs.
#     .option("kafka.bootstrap.servers", "broker1:9092,broker2:9092")
#
#     # subscribe: single topic
#     # subscribePattern: regex of topic names (e.g., "transactions.*")
#     # assign: specific topic+partition combinations (advanced)
#     .option("subscribe", "transactions")
#
#     # startingOffsets:
#     #   "earliest" → read from beginning of topic (reprocessing)
#     #   "latest"   → read only new messages (default for fresh start)
#     #   JSON       → specific offsets per partition (exact resume point)
#     # NOTE: on checkpoint resume, Spark ignores startingOffsets and
#     # uses the committed offsets from the checkpoint instead.
#     .option("startingOffsets", "latest")
#
#     # Maximum records to fetch per micro-batch per partition.
#     # Prevents a huge backlog from creating a giant first micro-batch.
#     .option("maxOffsetsPerTrigger", "10000")
#
#     # If True, stop the stream if Kafka reports a topic/partition
#     # that was previously tracked is no longer available (deleted/compacted).
#     # Default True. Set False if you expect topic deletion.
#     .option("failOnDataLoss", "true")
#
#     .load()
# )

# ============================================================
# SECTION 3: SCHEMA DEFINITION AND JSON PARSING
# ============================================================
# Kafka value is binary. The parsing chain:
#   binary → cast("string") → from_json(col, schema) → struct columns

# Define the expected schema of each JSON transaction message.
# CRITICAL: schema must match the producer's output exactly.
# Type mismatches → null values (silent corruption).
transaction_schema = StructType([
    StructField("transaction_id", StringType(), nullable=False),
    StructField("user_id", StringType(), nullable=False),
    StructField("amount", DoubleType(), nullable=True),
    StructField("merchant_id", StringType(), nullable=True),
    StructField("event_time", TimestampType(), nullable=False),  # producer timestamp
    StructField("card_country", StringType(), nullable=True),
])

# For demonstration, create a Rate source that simulates Kafka input
# Rate source generates: timestamp (event time) + value (row number)
rate_stream = (
    spark.readStream
    .format("rate")
    .option("rowsPerSecond", "100")   # 100 synthetic events per second
    .load()
)

# Simulate the transaction payload by adding synthetic columns to Rate source
transactions_stream = (
    rate_stream
    .withColumn("transaction_id", F.concat(F.lit("TXN_"), F.col("value").cast("string")))
    .withColumn("user_id", F.concat(F.lit("user_"), (F.col("value") % 200).cast("string")))
    .withColumn("amount", (F.rand() * 500 + 1).cast("double"))
    .withColumn("merchant_id", F.concat(F.lit("merchant_"), (F.col("value") % 50).cast("string")))
    .withColumn("event_time", F.col("timestamp"))   # use rate's built-in timestamp
    .withColumn("card_country", F.when(F.col("value") % 10 == 0, "RU").otherwise("US"))
    .drop("value")
)

# ============================================================
# SECTION 4: OUTPUT MODES
# ============================================================
# OUTPUT MODE controls what Spark writes to the sink each micro-batch.
#
# APPEND (default)
#   - Only write rows that were ADDED since the last micro-batch.
#   - For non-aggregated streams: every new row.
#   - For aggregated streams: only works with windowed aggregations +
#     watermark (so Spark knows when a window is complete / won't change).
#   - Most efficient for append-only sinks (files, Kafka new-topic).
#
# COMPLETE
#   - Write the ENTIRE result table every micro-batch.
#   - For aggregations: the full count/sum for ALL keys, not just new ones.
#   - Use: dashboards where you need the complete current state.
#   - Problem: if result table has 10M rows, you write 10M rows every batch.
#   - DO NOT use for large unbounded result sets.
#
# UPDATE
#   - Write only the rows that CHANGED since the last micro-batch.
#   - For aggregations: only the keys whose aggregate changed.
#   - Most efficient for aggregated streaming to a key-value store (Redis,
#     Cassandra, Delta with MERGE).
#   - Not supported for all sinks (files don't support update mode).

# ============================================================
# SECTION 5: WATERMARKING FOR LATE DATA
# ============================================================
# PROBLEM: events arrive late (network delays, mobile offline sync,
# batch uploads). If you keep a window open forever for late data,
# you accumulate infinite state → executor OOM.
#
# SOLUTION: watermark — define how late data can arrive.
# withWatermark("event_time", "10 minutes") means:
#   "The current watermark = max(event_time seen) - 10 minutes.
#    Any event with event_time < watermark is DROPPED.
#    Windows with max_time < watermark are FINALIZED and emitted."
#
# WHY event_time and not processing_time?
#   Processing time is when Spark receives the event.
#   Event time is when the event actually occurred (in the producer).
#   For fraud detection on user behavior, event time is what matters.
#   A transaction at 10:05 PM must fall in the 10:00-10:05 window,
#   even if Spark processes it at 10:15 PM.

# TUMBLING WINDOW: non-overlapping 5-minute windows
# Each event belongs to exactly one window.
# Window("10:00", "10:05") covers events where 10:00 <= event_time < 10:05.
tumbling_window_agg = (
    transactions_stream
    # Allow late events up to 1 minute after the event_time watermark.
    # After 1 minute, the window is sealed and late data is dropped.
    .withWatermark("event_time", "1 minute")
    .groupBy(
        "user_id",
        F.window("event_time", "5 minutes")   # tumbling: 5-min windows
    )
    .agg(
        F.count("*").alias("transaction_count"),
        F.sum("amount").alias("total_amount"),
        F.max("amount").alias("max_transaction")
    )
)

# SLIDING WINDOW: overlapping windows
# window("event_time", "5 minutes", "1 minute"):
#   Window size = 5 minutes, slides every 1 minute.
#   Each event belongs to 5 overlapping windows (one per slide step).
#   More granular but 5× more state to maintain.
sliding_window_agg = (
    transactions_stream
    .withWatermark("event_time", "1 minute")
    .groupBy(
        "user_id",
        F.window("event_time", "5 minutes", "1 minute")   # sliding
    )
    .agg(F.count("*").alias("tx_count"))
)

# ============================================================
# SECTION 6: TRIGGERS
# ============================================================
# Triggers control how often Spark processes a micro-batch.
#
# processingTime("10 seconds")
#   - Process new data every 10 seconds regardless of volume.
#   - Most common for near-real-time latency requirements.
#   - If processing takes longer than 10s, the next batch starts
#     immediately after the current one finishes (no overlap).
#
# once()
#   - Process ALL available data in one micro-batch, then stop.
#   - Deprecated in Spark 3.3 — use availableNow() instead.
#   - Use case: schedule streaming job as a batch job in Airflow.
#     "Run every hour, process all data since last run, then stop."
#
# availableNow()
#   - Like once(), but runs multiple micro-batches to process all
#     available data, then stops. Better for large backlogs.
#   - Available in Spark 3.3+. Preferred over once().
#
# continuous("1 second")
#   - Experimental low-latency mode (< 100ms latency possible).
#   - Uses continuous processing engine, not micro-batches.
#   - Limited sink/source support. Not production-ready for most cases.

# ============================================================
# SECTION 7: SINKS AND foreachBatch
# ============================================================
# SINKS:
#   console  → print to stdout. Testing only.
#   memory   → in-memory table. Testing only.
#   files    → Parquet/JSON/CSV. Append mode only. At-least-once.
#   Kafka    → publish records back to Kafka topic.
#   Delta    → write to Delta table. Full ACID, merge support.
#   foreach  → custom row-by-row processing (slow, avoid if possible).
#   foreachBatch → custom batch-level processing (RECOMMENDED for custom).

# foreachBatch: most flexible sink
# Receives each micro-batch as a plain static DataFrame.
# You can write to multiple sinks, JDBC, REST APIs, Delta MERGE, etc.
#
# IDEMPOTENCY REQUIREMENT:
# Structured Streaming guarantees at-least-once delivery.
# On restart after failure, the last micro-batch may replay.
# Your foreachBatch function must be IDEMPOTENT:
#   - Use INSERT OR IGNORE / MERGE with dedup key.
#   - Use Delta Lake MERGE ON transaction_id (upsert, not insert).
#   - Add epochId to the function — Spark passes it so you can detect replays.

def write_to_delta_and_alert(micro_batch_df, epoch_id):
    """
    foreachBatch handler — called for each micro-batch.

    Args:
        micro_batch_df: static DataFrame of this micro-batch's data.
        epoch_id: monotonically increasing batch ID. Use for idempotency.
    """
    # The micro_batch_df is a static DataFrame — you have the full
    # batch API available: joins, aggregations, repartition, cache, etc.

    # Count records for monitoring
    count = micro_batch_df.count()
    print(f"[Epoch {epoch_id}] Processing {count} transactions")

    if count == 0:
        return  # skip empty batches

    # WRITE 1: Write raw transactions to Delta (Silver layer)
    # Idempotent: Delta handles duplicate writes if we use MERGE in production.
    # For demo: simple append with dedup guard via epoch_id.
    # micro_batch_df.write.format("delta").mode("append").save("/delta/silver/transactions")

    # WRITE 2: Compute per-user aggregates and write to Redis/Cassandra
    # In production: use cassandra-driver or redis-py within foreachBatch.
    user_agg = (
        micro_batch_df
        .groupBy("user_id")
        .agg(
            F.count("*").alias("tx_count"),
            F.sum("amount").alias("total_amount")
        )
    )
    # user_agg.write.format("org.apache.spark.sql.cassandra") \
    #         .option("keyspace", "fraud").option("table", "user_stats") \
    #         .mode("append").save()

    # WRITE 3: Detect suspicious and write alerts to another Kafka topic
    suspicious = micro_batch_df.filter(F.col("card_country") == "RU")
    # suspicious.selectExpr("transaction_id as key", "to_json(struct(*)) as value") \
    #           .write.format("kafka") \
    #           .option("kafka.bootstrap.servers", "broker:9092") \
    #           .option("topic", "fraud_alerts") \
    #           .save()

    print(f"[Epoch {epoch_id}] Suspicious transactions: {suspicious.count()}")

# ============================================================
# SECTION 8: CHECKPOINTING — FAULT TOLERANCE
# ============================================================
# Checkpointing stores:
#   1. Query metadata (schema, config, sink state).
#   2. Source offsets (which Kafka offsets have been processed).
#   3. Aggregation state (current window counts per user_id).
#
# On restart:
#   1. Spark reads the checkpoint → knows last committed offset.
#   2. Resumes from that offset → no data loss, no large-scale replay.
#   3. Restores aggregation state → ongoing windows continue correctly.
#
# Checkpoint location must be on durable storage:
#   - S3 (s3://bucket/checkpoints/fraud_pipeline/)
#   - HDFS (hdfs:///checkpoints/fraud_pipeline/)
#   - ADLS (abfss://container@account.dfs.core.windows.net/checkpoints/)
#   DO NOT use local filesystem for production — lost on node failure.
#
# One checkpoint per streaming query. Two queries cannot share a checkpoint.

tmp_checkpoint = os.path.join(tempfile.mkdtemp(), "streaming_checkpoint")
tmp_output = os.path.join(tempfile.mkdtemp(), "streaming_output")

# ============================================================
# SECTION 9: KAFKA SINK — WRITING ALERTS BACK TO KAFKA
# ============================================================
# Kafka sink requires exactly two columns (key and value are optional):
#   - value: binary or string. REQUIRED.
#   - key: binary or string. Optional (Kafka will use null key → round-robin partitioning).
#   - topic: string. Can be hardcoded via .option("topic", ...) or
#            set per-row as a column (dynamic topic routing).
#
# The value must be serialized: to_json(struct(*)) produces JSON string.

# Production Kafka sink example (commented — needs running Kafka):
#
# alerts = (
#     tumbling_window_agg
#     .filter(F.col("transaction_count") > 10)   # suspicious threshold
#     .select(
#         F.col("user_id").alias("key"),          # Kafka partition key
#         F.to_json(F.struct(                     # JSON payload
#             F.col("user_id"),
#             F.col("window"),
#             F.col("transaction_count"),
#             F.col("total_amount")
#         )).alias("value")
#     )
# )
#
# kafka_query = (
#     alerts.writeStream
#     .format("kafka")
#     .option("kafka.bootstrap.servers", "broker1:9092,broker2:9092")
#     .option("topic", "fraud_alerts")                  # static topic
#     .option("checkpointLocation", "s3://bucket/ckpt/fraud_alerts/")
#     .outputMode("update")                              # only changed keys
#     .trigger(processingTime="30 seconds")
#     .start()
# )

# ============================================================
# SECTION 10: FULL FRAUD DETECTION PIPELINE (RUNNABLE DEMO)
# ============================================================
print("=== SECTION 10: Running Fraud Detection Demo ===")

# Step 1: Read stream (Rate source simulating Kafka)
# Already defined as: transactions_stream

# Step 2: Apply watermark and compute per-user window aggregations
# Tumbling 5-minute windows, 1-minute late data tolerance
fraud_candidates = (
    transactions_stream
    .withWatermark("event_time", "1 minute")
    .groupBy(
        "user_id",
        F.window("event_time", "5 minutes")
    )
    .agg(
        F.count("*").alias("transaction_count"),
        F.sum("amount").alias("total_amount"),
        F.max("amount").alias("max_transaction"),
        F.countDistinct("card_country").alias("country_count")
    )
    # Step 3: Flag suspicious accounts
    # High transaction count OR transactions from multiple countries in 5 min
    .withColumn(
        "fraud_score",
        F.when(F.col("transaction_count") > 8, 0.9)   # many transactions
         .when(F.col("country_count") > 1, 0.7)        # multiple countries
         .otherwise(0.1)
    )
    .filter(F.col("fraud_score") >= 0.7)               # only emit suspicious
)

# Step 4: Write to console sink (testing) with append mode
# In production: writeStream.format("kafka") or foreachBatch
fraud_query = (
    fraud_candidates
    .writeStream
    .outputMode("append")       # append mode requires watermark (set above)
    .format("console")
    .option("truncate", False)  # show full column values
    .option("numRows", 5)
    .trigger(processingTime="5 seconds")
    .option("checkpointLocation", os.path.join(tmp_checkpoint, "fraud_query"))
    .queryName("fraud_detection_pipeline")
    .start()
)

# Step 5: foreachBatch demo on raw transaction stream
raw_query = (
    transactions_stream
    .writeStream
    .foreachBatch(write_to_delta_and_alert)
    .trigger(processingTime="5 seconds")
    .option("checkpointLocation", os.path.join(tmp_checkpoint, "raw_query"))
    .queryName("raw_ingest_pipeline")
    .start()
)

# ============================================================
# SECTION 11: MONITORING STREAMING QUERIES
# ============================================================
# spark.streams.active → list of all active streaming queries
# query.status → current status dict (isTriggerActive, isDataAvailable, ...)
# query.lastProgress → dict with metrics from last micro-batch:
#   - numInputRows
#   - inputRowsPerSecond
#   - processedRowsPerSecond
#   - durationMs (queryPlanning, triggerExecution, addBatch, etc.)
#   - stateOperators (number of rows in state, memory used)
# query.recentProgress → list of last N progress reports

print(f"Active streaming queries: {len(spark.streams.active)}")
for q in spark.streams.active:
    print(f"  Query: {q.name} | ID: {q.id} | Status: {q.status['message']}")

# Run for a few seconds then stop
import time
print("Running streaming pipeline for 15 seconds...")
time.sleep(15)

# ============================================================
# SECTION 12: GRACEFUL SHUTDOWN
# ============================================================
# query.stop() → gracefully stops the query.
#   - Completes the current micro-batch.
#   - Commits offsets to checkpoint.
#   - Clean state.
#
# query.awaitTermination(timeout) → block until query stops or timeout.
# spark.streams.awaitAnyTermination() → block until any query stops.
# StreamingQueryException is raised on query failure.

for q in spark.streams.active:
    q.stop()
    print(f"Stopped query: {q.name}")

print("\n=== L06 Complete ===")
print("Key takeaways:")
print("  1. Always set checkpointLocation — fault tolerance depends on it")
print("  2. withWatermark() is required for bounded state in windowed aggs")
print("  3. foreachBatch is the escape hatch for any custom sink logic")
print("  4. Output mode 'update' is most efficient for aggregations")
print("  5. AQE + shuffle.partitions=4 for streaming (batches are small)")
print("  6. Socket and Rate sources are for testing only")

spark.stop()
