# ============================================================
# L01: Apache Spark Fundamentals
# ============================================================
# WHAT: Conceptual foundation of Apache Spark — architecture,
#       execution model, optimization engine, and how to run
#       jobs locally and on a cluster.
# WHY:  Spark is the dominant framework for large-scale data
#       processing. Understanding how it works internally —
#       DAGs, lazy evaluation, Catalyst, Tungsten — lets you
#       write efficient jobs and diagnose performance problems
#       instead of guessing.
# LEVEL: Foundations
# ============================================================
"""
CONCEPT OVERVIEW:
    Apache Spark is a distributed in-memory compute engine for processing
    large datasets across a cluster of machines. It is NOT a database —
    it reads data from external storage (HDFS, S3, Delta Lake, JDBC) and
    writes results back. Spark's key innovations over its predecessor
    MapReduce: (1) in-memory computation (10-100x faster for iterative
    algorithms like ML training), (2) a rich API (SQL, streaming,
    MLlib, GraphX), (3) a lazy execution model with a query optimizer.

PRODUCTION USE CASE:
    ETL pipelines processing terabytes of raw logs daily. Data warehousing
    (read from S3 Parquet, join dimension tables, aggregate, write to
    Delta Lake). Machine learning feature engineering pipelines run on
    Spark before model training. Real-time analytics with Spark Streaming
    reading from Kafka.

COMMON MISTAKES:
    - Calling collect() on a large DataFrame (brings all data to driver,
      OOM crash). Use write() to save results to storage instead.
    - Not understanding that transformations are lazy — the fact that
      a line of code "ran" doesn't mean data was processed.
    - Using Python UDFs on DataFrames (leaves JVM, row-by-row processing,
      10-100x slower). Use native SQL functions or Pandas UDFs.
    - Creating a new SparkSession instead of reusing (expensive init).
    - Not partitioning data before writing (all data in one file = no
      parallelism for downstream readers).
    - Chaining too many narrow transformations without checkpointing
      (long lineage = long recompute on failure).
"""

# ============================================================
# IMPORTS
# ============================================================
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, LongType
import os

# ============================================================
# SECTION 1: Architecture Overview (conceptual — no code)
# ============================================================
# DRIVER:
#   Your program. Runs on the machine where you submit the job
#   (or on the cluster in "cluster" deploy mode).
#   Responsibilities:
#     - Builds the logical plan (what to compute).
#     - Requests resources from the Cluster Manager.
#     - Distributes tasks to Executors.
#     - Collects results (for actions like count() or collect()).
#   Memory: stores the SparkContext, broadcast variables, collected results.
#   Single point of failure — driver crash = job loss. Use checkpointing.
#
# EXECUTORS:
#   Worker processes on cluster nodes. Each Executor:
#     - Runs tasks assigned by the driver.
#     - Stores data in memory (RDD/DataFrame partitions) or disk.
#     - Reports task completion and metrics back to driver.
#   Number of Executors: --num-executors (YARN) or resource requests (K8s).
#   Executor memory: split between execution memory (shuffle, aggregation,
#   sort) and storage memory (cached RDD/DataFrame data). Default 50/50,
#   dynamic allocation adjusts the boundary.
#
# CLUSTER MANAGER:
#   Allocates resources (cores, memory) to Spark applications.
#   Options:
#     YARN:       Hadoop's resource manager. Most common on-prem.
#     Kubernetes: Container orchestration. Growing for cloud-native.
#     Standalone: Spark's built-in. Simple setups.
#     Mesos:      Legacy. Rarely used for new deployments.
#   Databricks uses its own cluster manager + Delta Engine (optimized Spark).
#
# DATA LOCALITY:
#   Spark tries to schedule tasks on the same machine/rack that holds
#   the data partition. This minimizes network transfer.
#   Locality levels (preferred order): PROCESS_LOCAL → NODE_LOCAL →
#   RACK_LOCAL → ANY. Check Spark UI for locality distribution.
# ============================================================

# ============================================================
# SECTION 2: SparkSession — Your Entry Point
# ============================================================
# WHAT: SparkSession is the single entry point for all Spark functionality.
#       It combines SparkContext (low-level RDD API) and SQLContext (SQL API)
#       which existed separately in earlier Spark versions.
#       One SparkSession per JVM process. Use getOrCreate() — if a session
#       already exists (in Databricks, for example), it returns that one.
#
# config() OPTIONS (partial list — see Spark documentation for full list):
#   spark.sql.shuffle.partitions:
#     Number of partitions after a shuffle (join, groupBy). Default: 200.
#     For small data, 200 is too many (tiny files problem).
#     For large data, 200 is too few (OOM, slow).
#     Rule of thumb: set to 2-3x the number of CPU cores in your cluster,
#     or tune based on data size (target 128MB-512MB per partition).
#
#   spark.executor.memory: RAM per executor (e.g., "4g", "16g").
#   spark.executor.cores:  CPU cores per executor (typically 2-5).
#   spark.driver.memory:   RAM for the driver process.
# ============================================================

def get_spark_session(app_name: str, local: bool = True) -> SparkSession:
    """
    Create or reuse a SparkSession.
    local=True: run on this machine using all cores ("local[*]").
    local=False: connect to a cluster (master URL from --master flag or env var).
    """
    builder = (
        SparkSession.builder
        .appName(app_name)
        # Shuffle partition count — reduce for local/small data development
        .config("spark.sql.shuffle.partitions", "4" if local else "200")
        # Enable adaptive query execution (Spark 3.0+) — auto-coalesces
        # shuffle partitions and handles join strategy dynamically
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.adaptive.coalescePartitions.enabled", "true")
        # Kryo serialization is faster and more compact than Java serialization
        # for RDD operations. Not used for DataFrame operations (Tungsten handles those).
        .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
    )

    if local:
        builder = builder.master("local[*]")
        # local[*] = use all available CPU cores on this machine
        # local[4] = use exactly 4 cores
        # local    = single-threaded (no parallelism, for debugging)

    return builder.getOrCreate()

# ============================================================
# SECTION 3: DAG and Lazy Evaluation
# ============================================================
# WHAT: When you write Spark transformations (filter, select, join),
#       Spark does NOT execute them immediately. Instead, it builds
#       a DAG (Directed Acyclic Graph) of operations representing
#       what needs to be computed.
#
#       Execution only begins when you call an ACTION.
#
# WHY LAZY EVALUATION:
#   It enables the Catalyst optimizer to see the ENTIRE pipeline
#   before executing anything. This allows optimizations like:
#
#   1. PREDICATE PUSHDOWN:
#      filter(col("status") == "ACTIVE") pushed to the data source.
#      Parquet files are scanned with the filter applied at read time,
#      so entire row groups are skipped. Massive I/O reduction.
#
#   2. PROJECTION PRUNING:
#      If you only select("name", "age"), Spark only reads those columns.
#      Parquet is columnar — unread columns add zero I/O cost.
#
#   3. CONSTANT FOLDING:
#      withColumn("x", lit(2) * lit(3)) becomes withColumn("x", lit(6)).
#      Computed at plan time, not per-row.
#
#   4. JOIN REORDERING:
#      Cost-based optimizer (CBO) reorders joins to process smaller
#      tables first, reducing shuffle size.
#
# TRANSFORMATIONS (lazy — return a new DataFrame, nothing runs):
#   select(), filter(), where(), withColumn(), drop(), join(),
#   groupBy(), agg(), orderBy(), limit(), distinct(), dropDuplicates(),
#   union(), repartition(), coalesce(), cache(), map(), flatMap()...
#
# ACTIONS (trigger execution — cause the DAG to run):
#   count(), collect(), show(), take(n), first(), head(),
#   write.save(), write.parquet(), foreach(), toPandas()
#
# Think of it as: transformations build the recipe, actions cook the food.
# ============================================================

def demonstrate_lazy_evaluation(spark: SparkSession) -> None:
    """
    Show that transformations don't run until an action is called.
    """
    # This line does NOT read any data — just creates a plan
    df = spark.read.csv("s3://my-bucket/orders/*.csv", header=True, inferSchema=True)

    # These transformations don't run yet — just add to the DAG
    filtered_df = df.filter(F.col("status") == "COMPLETED")
    selected_df = filtered_df.select("order_id", "user_id", "total_amount")
    renamed_df = selected_df.withColumnRenamed("total_amount", "revenue")

    # Nothing has executed yet. The DAG looks like:
    # CSV Read → Filter(status=COMPLETED) → Select(3 cols) → Rename

    # With Catalyst optimization, this becomes:
    # CSV Read (only 3 columns, only rows where status=COMPLETED)
    # The filter and projection are pushed INTO the read step.

    # THIS is when everything runs:
    row_count = renamed_df.count()   # ACTION — triggers DAG execution
    print(f"Completed orders: {row_count}")

    # Calling count() again runs the whole DAG again (no caching yet)
    # Solution: cache() the DataFrame if you'll use it multiple times

# ============================================================
# SECTION 4: Jobs, Stages, and Tasks
# ============================================================
# WHAT: Spark breaks work into a hierarchy: Job → Stages → Tasks.
#       Understanding this hierarchy is essential for performance tuning.
#
# JOB:
#   One job per action (count, write, collect).
#   If your script calls count() and then write(), that's 2 jobs.
#
# STAGE:
#   A job is divided into stages at SHUFFLE BOUNDARIES.
#   Shuffle: data must be redistributed across the cluster
#   (e.g., all records with the same key must end up on the same
#   executor for groupBy or join operations).
#   Shuffles are expensive: disk I/O (data written to disk before
#   shuffling), network transfer, disk I/O again (data read after).
#   You can see stages in the Spark UI's DAG visualization.
#
# TASK:
#   One task per partition per stage.
#   If you have 200 partitions and 3 stages, that's 600 tasks.
#   Tasks are the unit of parallelism — more tasks = more parallelism
#   (up to your total Executor cores).
#   All tasks in a stage can run in parallel. Stages run sequentially
#   (next stage can't start until all tasks in current stage finish).
#
# NARROW vs WIDE TRANSFORMATIONS:
#   Narrow: each input partition contributes to exactly one output
#           partition. No shuffle. Examples: filter, select, map, union.
#   Wide:   one output partition can receive data from multiple input
#           partitions. Causes a shuffle. Examples: groupBy, join,
#           orderBy, distinct, repartition.
#   Rule: minimize wide transformations. Combine them when possible.
# ============================================================

# ============================================================
# SECTION 5: RDD vs DataFrame vs Dataset
# ============================================================
# WHAT: Three abstractions in Spark for representing distributed data.
#
# RDD (Resilient Distributed Dataset):
#   - Spark 1.x. Low-level. Untyped (you know the type, Spark doesn't).
#   - Functional API: map(), flatMap(), filter(), reduce(), etc.
#   - No automatic optimization — Spark executes what you write.
#   - Python UDFs on RDDs: data crosses JVM-Python boundary per row.
#     This is called "PySpark row-at-a-time mode" and is very slow.
#   - When to use: complex iterative algorithms, low-level control,
#     or when you genuinely can't express logic in DataFrame API.
#
# DataFrame:
#   - Spark 1.3+. Like a table with named, typed columns.
#   - Catalyst optimizer and Tungsten execution engine.
#   - SQL-like API: select(), filter(), groupBy(), join().
#   - Runs in the JVM/native (fast). Python just submits the plan.
#   - USE THIS for 95%+ of Spark work.
#
# Dataset:
#   - Spark 1.6+. Strongly typed version of DataFrame (Scala/Java only).
#   - Python and R don't have Datasets (no compile-time type safety in Python).
#   - In practice, Python users work exclusively with DataFrames.
#
# PERFORMANCE COMPARISON:
#   DataFrames/SQL ≈ Datasets (JVM) >> RDD with Scala/Java >> RDD with Python
#   Python DataFrame and Scala DataFrame have the SAME performance since
#   Spark 2.x — Python is just a thin wrapper, execution is JVM + Tungsten.
# ============================================================

# ============================================================
# SECTION 6: Catalyst Optimizer
# ============================================================
# WHAT: Spark's query optimizer. Rewrites your logical plan into
#       an efficient physical plan before execution.
#
# FOUR PHASES:
#   1. ANALYSIS:
#      Resolve column names against the catalog. Check types.
#      If you reference a column that doesn't exist, error here.
#
#   2. LOGICAL OPTIMIZATION (rule-based):
#      Apply optimization rules:
#        - Predicate pushdown: move filters as early as possible.
#        - Column pruning: drop unused columns early.
#        - Constant folding: evaluate constant expressions at plan time.
#        - Null propagation: simplify null handling.
#        - Boolean simplification: simplify redundant conditions.
#
#   3. PHYSICAL PLANNING (cost-based, CBO):
#      Choose physical operators:
#        - Join strategy: BroadcastHashJoin (small table fits in memory)
#          vs SortMergeJoin (both tables large) vs ShuffleHashJoin.
#        - Partition strategy for aggregations.
#      CBO uses table statistics (row count, column cardinality).
#      Run ANALYZE TABLE to update statistics for better CBO decisions.
#
#   4. CODE GENERATION (Whole-Stage CodeGen):
#      Generates JVM bytecode for the entire query pipeline.
#      Instead of calling separate operators for each row, one function
#      processes a batch of rows through the entire pipeline.
#      Result: near-native performance, no virtual function call overhead.
# ============================================================

def show_query_plan(spark: SparkSession) -> None:
    """
    Use explain() to see Catalyst's query plans.
    Essential for debugging performance and verifying optimizations.
    """
    spark.sql("""
        SELECT user_id, SUM(amount) as total
        FROM orders
        WHERE status = 'COMPLETED'
          AND order_date >= '2024-01-01'
        GROUP BY user_id
        HAVING total > 1000
    """).explain(True)
    # explain(True) shows ALL four plans:
    # == Parsed Logical Plan ==     (your query as written)
    # == Analyzed Logical Plan ==   (column names resolved)
    # == Optimized Logical Plan ==  (after Catalyst rules applied — look for
    #                                 Filter pushed down to scan here)
    # == Physical Plan ==           (actual execution operators)
    #
    # Look for:
    #   *(n) prefix: inside a whole-stage codegen "stage"
    #   Exchange: shuffle (stage boundary)
    #   BroadcastExchange/BroadcastHashJoin: small table broadcast (good)
    #   SortMergeJoin: large table join (check if broadcast was missed)
    #   Filter pushed into Scan: predicate pushdown worked (good)

# ============================================================
# SECTION 7: Tungsten Execution Engine
# ============================================================
# WHAT: Spark's low-level execution engine that bypasses JVM
#       overheads for near-native performance.
#
# THREE KEY INNOVATIONS:
#
#   1. OFF-HEAP MEMORY MANAGEMENT:
#      Stores data in binary format in native (off-heap) memory.
#      Bypasses Java Garbage Collector — no GC pauses during processing.
#      Data stored as rows of fixed-width binary (like C structs).
#      Cache-friendly layout: sequential memory access = CPU cache hits.
#
#   2. WHOLE-STAGE CODE GENERATION:
#      Instead of calling operator.process(row) in a loop for each
#      operator, Catalyst generates a single function that processes
#      the entire pipeline for a batch of rows.
#      Example: a filter → project → hash aggregate pipeline becomes
#      one tight inner loop with no virtual function dispatch.
#      Result: 10x+ better performance vs Spark 1.x.
#
#   3. CACHE-AWARE SORT:
#      Sorting algorithms designed to maximize CPU cache usage.
#      Operates on compact binary representations, not Java objects.
#
# You don't need to do anything to use Tungsten — it's automatic for
# DataFrame operations. It does NOT apply to Python UDFs (those
# serialize/deserialize data between JVM and Python, bypassing Tungsten).
# This is the primary reason to avoid Python UDFs.
# ============================================================

# ============================================================
# SECTION 8: Running Spark — Local vs Cluster
# ============================================================
# LOCAL MODE (development/testing):
#   SparkSession with master("local[*]") — no cluster needed.
#   All computation happens in one JVM on your machine.
#   Data is still distributed across "virtual" partitions.
#   Good for: development, unit testing with small datasets,
#             debugging logic before deploying to cluster.
#
# SPARK-SUBMIT (production):
#   spark-submit \
#     --master yarn \                          # or k8s://apiserver:6443
#     --deploy-mode cluster \                  # driver runs on cluster
#     --num-executors 20 \                     # total executors
#     --executor-memory 8g \                   # RAM per executor
#     --executor-cores 4 \                     # cores per executor
#     --driver-memory 4g \
#     --conf spark.sql.shuffle.partitions=400 \
#     --py-files dependencies.zip \            # extra Python files
#     my_job.py --arg1 value1
#
# DEPLOY MODE:
#   client:  Driver runs on the machine where you submitted the job.
#            Good for: interactive shells, Jupyter notebooks, debugging.
#            Bad for: long-running jobs (your laptop closing kills the driver).
#   cluster: Driver runs on a cluster node.
#            Good for: production jobs (outlives your SSH session).
#            Logs are on the cluster (not your terminal).
#
# DATABRICKS (managed Spark):
#   - No spark-submit needed — Databricks handles cluster management.
#   - Interactive notebooks with auto-complete.
#   - Auto-scaling clusters.
#   - Delta Engine: optimized Spark runtime with Photon (C++ vectorized engine).
#   - Unity Catalog: fine-grained access control on tables.
#   - Cluster types: All-Purpose (always on), Job Clusters (per-job, cheaper).
# ============================================================

# ============================================================
# SECTION 9: Real Example — Word Count and Log Aggregation
# ============================================================

def word_count_example(spark: SparkSession) -> None:
    """
    Word count — the "hello world" of Spark.
    Simple but demonstrates the core patterns.
    """
    # Sample data — in production this would be sc.textFile("s3://...")
    lines = [
        "the quick brown fox jumps over the lazy dog",
        "the dog barked at the fox",
        "a quick brown fox",
    ]
    # Create RDD from local data
    rdd = spark.sparkContext.parallelize(lines, numSlices=2)

    # flatMap: each line → list of words → flatten to one word per element
    # map: each word → (word, 1)
    # reduceByKey: sum values per key (efficient — combines locally first)
    word_counts_rdd = (
        rdd
        .flatMap(lambda line: line.split())      # ["the", "quick", "brown", ...]
        .map(lambda word: (word.lower(), 1))     # ("the", 1), ("quick", 1), ...
        .reduceByKey(lambda a, b: a + b)         # ("the", 3), ("fox", 2), ...
        .sortBy(lambda kv: kv[1], ascending=False)
    )

    print("=== Word Count (RDD) ===")
    for word, count in word_counts_rdd.take(10):
        print(f"  {word}: {count}")

    # BETTER: Same thing using DataFrame API — Catalyst-optimized
    df = spark.createDataFrame([(line,) for line in lines], ["line"])
    word_counts_df = (
        df
        .select(F.explode(F.split(F.col("line"), r"\s+")).alias("word"))
        .select(F.lower(F.col("word")).alias("word"))
        .groupBy("word")
        .count()
        .orderBy(F.col("count").desc())
    )

    print("=== Word Count (DataFrame — better) ===")
    word_counts_df.show(10)
    # DataFrame is faster because Catalyst optimizes the plan.
    # The RDD version forces execution in the exact order you wrote it.


def log_aggregation_pipeline(spark: SparkSession, input_path: str, output_path: str) -> None:
    """
    Realistic log processing pipeline.
    Input:  S3 path to raw access logs (Apache/Nginx format as JSON).
    Output: Hourly request counts by endpoint and status code.
    """
    # Define schema explicitly — faster than inferSchema (no two-pass scan)
    schema = StructType([
        StructField("timestamp", StringType(), nullable=False),
        StructField("method", StringType(), nullable=True),
        StructField("endpoint", StringType(), nullable=True),
        StructField("status_code", IntegerType(), nullable=True),
        StructField("response_time_ms", LongType(), nullable=True),
        StructField("user_id", StringType(), nullable=True),
        StructField("bytes_sent", LongType(), nullable=True),
    ])

    # Read Parquet (in production, logs would be converted from raw format)
    logs_df = (
        spark.read
        .schema(schema)
        .parquet(input_path)
        # Partition pruning: if data is partitioned by date in S3,
        # Spark reads only the relevant partitions
        .where(F.col("timestamp") >= "2024-01-01")
    )

    # Transformations — all lazy
    result_df = (
        logs_df
        # Parse timestamp into date and hour
        .withColumn("hour", F.date_trunc("hour", F.to_timestamp("timestamp")))
        # Normalize endpoint: strip query params and trailing slashes
        .withColumn(
            "endpoint_normalized",
            F.regexp_replace(F.col("endpoint"), r"\?.*$", "")  # remove ?query=string
        )
        # Classify status codes
        .withColumn(
            "status_class",
            F.when(F.col("status_code") < 300, "2xx")
             .when(F.col("status_code") < 400, "3xx")
             .when(F.col("status_code") < 500, "4xx")
             .otherwise("5xx")
        )
        # Aggregate: count requests, avg latency, error rate per hour/endpoint
        .groupBy("hour", "endpoint_normalized", "status_class")
        .agg(
            F.count("*").alias("request_count"),
            F.avg("response_time_ms").alias("avg_latency_ms"),
            F.percentile_approx("response_time_ms", 0.99).alias("p99_latency_ms"),
            F.sum("bytes_sent").alias("total_bytes"),
        )
        .orderBy("hour", F.col("request_count").desc())
    )

    # Write to Parquet, partitioned by hour for efficient downstream reads
    # Partitioning by hour means queries for a specific hour read only that partition
    (
        result_df
        .write
        .mode("overwrite")
        .partitionBy("hour")
        .parquet(output_path)
    )

    print(f"Log aggregation complete. Results written to {output_path}")


# ============================================================
# SECTION 10: Main Entry Point
# ============================================================

if __name__ == "__main__":
    spark = get_spark_session("L01_SparkConcepts", local=True)

    print("=== Demonstrating Spark Concepts ===")
    print(f"Spark version: {spark.version}")
    print(f"Default parallelism: {spark.sparkContext.defaultParallelism}")

    # Word count demonstration
    word_count_example(spark)

    # Explain how Catalyst sees a simple query
    # (would need actual data; shown here as a pattern)
    # show_query_plan(spark)

    # Check Spark UI at http://localhost:4040 during execution
    # to see jobs, stages, tasks, and storage

    spark.stop()
