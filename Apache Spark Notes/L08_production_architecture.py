# ============================================================
# L08: Spark Production Architecture
# ============================================================
# WHAT: How real Spark jobs are deployed, orchestrated, monitored,
#       and maintained in production. Covers submission, cluster
#       platforms, job orchestration, testing, CI/CD, cost
#       optimization, and a complete medallion ETL pipeline.
# WHY:  Writing a Spark job locally is step 1. Making it run reliably
#       on 1 TB of data every day, automatically, with alerting on
#       failures, cost guardrails, and rollback capability — that
#       is what separates a data engineer from a data scientist
#       who writes Spark.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    Production Spark has four layers:
    1. COMPUTE: where and how Spark runs (Databricks, EMR, Dataproc,
       on-prem YARN). Trade-offs: managed vs self-managed, spot pricing,
       cluster sizing, dynamic allocation.
    2. ORCHESTRATION: what triggers the job and what depends on what
       (Airflow DAGs, Databricks Workflows, AWS Step Functions).
    3. MONITORING: did the job succeed? How long did it take? Which stage
       was slow? (Spark UI, History Server, Prometheus, Datadog).
    4. DATA QUALITY + LINEAGE: is the output correct? Where did the data
       come from? (Great Expectations, dbt tests, OpenLineage/Marquez).

PRODUCTION USE CASE:
    Daily ETL for 1 TB of e-commerce order data:
    - 02:00 AM: ingest raw CSV from S3 into Bronze Delta.
    - 02:30 AM: clean + deduplicate → Silver Delta.
    - 04:00 AM: aggregate revenue by category → Gold Delta.
    - 05:00 AM: sync Gold to Redshift Spectrum for BI queries.
    SLA: Gold layer ready by 06:00 AM. Alert if job exceeds 5 hours.

COMMON MISTAKES:
    1. Running driver in client mode for production jobs — driver runs
       on the submitting node (laptop/CI runner), which can fail or
       be killed, crashing the entire job. Use cluster deploy mode.
    2. Using all-purpose Databricks clusters for scheduled jobs —
       you pay per DBU even when idle. Job clusters spin up fresh,
       cost 3-4× less per DBU, and are the right choice for batch jobs.
    3. Not enabling dynamic allocation on variable workloads — paying
       for 20 executors during idle periods between stages.
    4. No retry logic in Airflow — a transient S3 API error kills
       the entire DAG. Use retries=3, retry_delay=5m.
    5. Testing with full production datasets — unit tests should use
       tiny synthetic data. Integration tests on a sample (1%).
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType,
    DoubleType, TimestampType
)
import tempfile, os, sys

# ============================================================
# SECTION 1: SPARK-SUBMIT REFERENCE
# ============================================================
# spark-submit is the standard way to run Spark jobs in production.
# All configurations can be set here (or via --conf for individual settings).
#
# Full production spark-submit command:
#
# spark-submit \
#   --master yarn \                        # or k8s://https://..., spark://host:7077
#   --deploy-mode cluster \                # driver runs ON THE CLUSTER (not submitter)
#                                          # vs client: driver on submitting machine
#                                          # ALWAYS use cluster in production
#   --num-executors 20 \                   # static allocation: 20 executors
#   --executor-cores 4 \                   # 4 vCPUs per executor (Rule of 4)
#   --executor-memory 16g \               # 16 GB RAM per executor
#   --driver-memory 16g \                  # driver needs memory for collect(), broadcast()
#   --driver-cores 4 \
#   --conf spark.executor.memoryOverhead=2g \  # off-heap JVM overhead (10% of executor mem)
#   --conf spark.sql.adaptive.enabled=true \
#   --conf spark.sql.shuffle.partitions=800 \
#   --conf spark.speculation=true \
#   --conf spark.serializer=org.apache.spark.serializer.KryoSerializer \
#   --conf spark.dynamicAllocation.enabled=false \  # static sizing for predictable cost
#   --py-files dist/my_lib.zip \          # additional Python modules to distribute
#   --files config/prod.yaml \            # files distributed to executors
#   my_job.py \                           # main script
#   --date 2024-01-01 \                   # application arguments
#   --env prod
#
# DEPLOY MODE COMPARISON:
#
# client mode:
#   Driver: on submitting machine (your laptop, CI server, Airflow worker).
#   Logs: appear directly in the terminal.
#   Risk: if the machine is killed/disconnected, the job dies.
#   Use: development, debugging, jobs where you need interactive output.
#
# cluster mode:
#   Driver: runs on a cluster node (YARN ApplicationMaster, K8s driver pod).
#   Logs: collected by cluster; retrieve with: yarn logs -applicationId appId
#   Risk: job continues even if you disconnect.
#   Use: ALWAYS in production. If Airflow restarts, the job keeps running.

print("=== SECTION 1: Spark-Submit Reference ===")
print("See comments above for full spark-submit command with production settings.")
print(f"Current Python: {sys.version}")
print(f"PySpark version: ", end="")
try:
    import pyspark; print(pyspark.__version__)
except ImportError:
    print("not installed")

# ============================================================
# SECTION 2: AIRFLOW ORCHESTRATION PATTERNS
# ============================================================
# Apache Airflow is the industry-standard orchestrator for Spark jobs.
# A DAG (Directed Acyclic Graph) defines the sequence and dependencies
# between tasks.
#
# KEY OPERATORS:
#
# SparkSubmitOperator
#   - Calls spark-submit on the Airflow worker.
#   - Requires Spark binaries on the Airflow worker node.
#   - Works for YARN, standalone, Kubernetes.
#
# LivyOperator
#   - Submits jobs via Apache Livy REST API.
#   - Airflow worker needs NO Spark installation.
#   - Livy server manages the Spark session on the cluster.
#   - Better for Databricks + Spark via REST (LivyOperator or
#     DatabricksSubmitRunOperator).
#
# DatabricksSubmitRunOperator (databricks provider)
#   - Submits a one-time job run to Databricks via Jobs API.
#   - Supports: notebook, JAR, Python wheel, spark-submit.
#   - Polls for completion; raises exception on failure.
#
# EXAMPLE AIRFLOW DAG (Python — not runnable without Airflow):
AIRFLOW_DAG_EXAMPLE = '''
from airflow import DAG
from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator
from airflow.providers.databricks.operators.databricks import DatabricksSubmitRunOperator
from datetime import datetime, timedelta

default_args = {
    "owner": "data-engineering",
    "retries": 3,                        # retry failed tasks 3 times
    "retry_delay": timedelta(minutes=5), # wait 5 min between retries
    "email_on_failure": True,
    "email": ["data-oncall@company.com"],
    "sla": timedelta(hours=4),           # alert if task takes > 4 hours
}

with DAG(
    dag_id="daily_orders_etl",
    start_date=datetime(2024, 1, 1),
    schedule_interval="0 2 * * *",       # 2 AM daily
    catchup=False,                        # don't backfill missed runs
    default_args=default_args,
    tags=["etl", "orders", "delta"],
) as dag:

    # Task 1: Bronze ingest (raw CSV → Delta)
    bronze_ingest = SparkSubmitOperator(
        task_id="bronze_ingest",
        application="s3://code/bronze_ingest.py",
        conf={
            "spark.sql.adaptive.enabled": "true",
            "spark.sql.shuffle.partitions": "800",
        },
        application_args=["--date", "{{ ds }}"],  # Airflow template: run date
        executor_memory="16g",
        num_executors=10,
        name="bronze_ingest_{{ ds }}",
        conn_id="spark_default",
    )

    # Task 2: Silver clean (runs AFTER bronze completes)
    silver_clean = DatabricksSubmitRunOperator(
        task_id="silver_clean",
        databricks_conn_id="databricks_default",
        new_cluster={
            "spark_version": "14.3.x-scala2.12",
            "node_type_id": "i3.xlarge",
            "num_workers": 8,
            "aws_attributes": {
                "availability": "SPOT_WITH_FALLBACK",  # spot for cost savings
                "spot_bid_price_percent": 80,
            },
        },
        spark_python_task={
            "python_file": "s3://code/silver_clean.py",
            "parameters": ["--date", "{{ ds }}"],
        },
        timeout_seconds=7200,   # fail if takes > 2 hours
    )

    # Task 3: Gold aggregate (runs AFTER silver completes)
    gold_aggregate = SparkSubmitOperator(
        task_id="gold_aggregate",
        application="s3://code/gold_aggregate.py",
        executor_memory="32g",   # aggregations need more memory
        num_executors=20,
        application_args=["--date", "{{ ds }}"],
        conn_id="spark_default",
    )

    # Define task dependencies
    bronze_ingest >> silver_clean >> gold_aggregate
'''
print("\n=== SECTION 2: Airflow DAG Pattern ===")
print("See AIRFLOW_DAG_EXAMPLE variable — full production DAG with retries + SLA.")

# ============================================================
# SECTION 3: CLUSTER PLATFORMS
# ============================================================
print("\n=== SECTION 3: Cluster Platforms ===")

PLATFORM_COMPARISON = {
    "Databricks": {
        "key_features": [
            "Photon engine (10x speedup on Delta)",
            "Unity Catalog (data governance + lineage)",
            "Workflows (native DAG scheduler)",
            "MLflow integration",
            "Repos (git sync to notebooks)",
        ],
        "cluster_types": {
            "All-purpose": "Interactive. Always-on. Pay per DBU while running. Use for dev.",
            "Job cluster":  "Auto-spun for one job, then terminated. 3-4x cheaper per DBU. Use for prod.",
        },
        "cost_tip": "Job clusters + spot instances + autoscaling = 70-80% cost reduction vs all-purpose.",
        "when_to_use": "Best UX, best Delta integration, best for teams on cloud (AWS/Azure/GCP).",
    },
    "EMR (AWS)": {
        "key_features": [
            "Native AWS IAM + S3 integration",
            "EMR Serverless (no cluster management)",
            "EMR on EKS (Kubernetes-native)",
            "Tight Glue catalog integration",
            "Spot instance support for task nodes",
        ],
        "cluster_types": {
            "Transient": "Spin up → process → terminate. Cheapest. Best for scheduled batch jobs.",
            "Persistent": "Long-running. Pay even when idle. Use for frequent interactive workloads.",
            "Serverless": "No cluster provisioning. Pay per vCPU-hour. Best for variable workloads.",
        },
        "cost_tip": "Task nodes on Spot = 70% savings. Master + Core = on-demand (stability).",
        "when_to_use": "Deep AWS integration. EMR Serverless for ops simplicity.",
    },
    "Dataproc (GCP)": {
        "key_features": [
            "Dataproc Serverless (no cluster management)",
            "Preemptible VMs (like AWS Spot)",
            "Native BigQuery connector",
            "Ephemeral clusters: create, use, delete",
        ],
        "when_to_use": "GCP-native stacks. BigQuery integration. Serverless for simplicity.",
    },
    "Azure HDInsight / Synapse Spark": {
        "when_to_use": "Azure-native. Synapse Spark integrates with Synapse Analytics DW.",
    },
}

for platform, info in PLATFORM_COMPARISON.items():
    print(f"\n  {platform}: {info.get('when_to_use', 'N/A')}")

# ============================================================
# SECTION 4: CLUSTER SIZING
# ============================================================
# RULE OF 4 for executor sizing:
#   4 cores per executor, memory = 4 cores × 4 GB/core = 16 GB.
#   Reason: more cores → HDFS client threads → throughput degrades above 5.
#   Memory overhead: 10% of executor memory (minimum 384 MB).
#   Leave OS headroom: total node memory × 0.9 for executor pool.
#
# FORMULA: number of executors for a job
#   Data size: 1 TB = 1,000 GB
#   Partition size target: 128 MB
#   Partitions: 1,000,000 MB / 128 MB = 7,812 partitions
#   Parallelism per executor: 4 cores = 4 concurrent tasks
#   Executors needed: 7,812 / 4 = ~1,953 executor-tasks needed
#   If job has 30 stages, can reuse same executors:
#     1,953 / 30 stages = ~65 executors to keep pipeline full.
#   Round up to nearest convenient number: 80 executors.
#
# DRIVER sizing:
#   16-32 GB RAM: driver collects results of .collect() and broadcasts.
#   4-8 cores: driver runs DAG scheduler, task scheduling.
#   NEVER use tiny driver — driver is the single point of failure.

print("\n=== SECTION 4: Cluster Sizing Calculator ===")

def calculate_cluster_size(data_size_gb, avg_stages=20, cores_per_executor=4, ram_per_core_gb=4):
    """
    Rule-of-thumb cluster sizing for a Spark batch job.

    Args:
        data_size_gb:        total data processed (after any partition pruning)
        avg_stages:          typical number of Spark stages in the job
        cores_per_executor:  Rule of 4 default
        ram_per_core_gb:     RAM per core (4 GB is typical for analytics)
    """
    partition_size_mb = 128
    total_partitions = (data_size_gb * 1024) / partition_size_mb
    tasks_per_executor = cores_per_executor
    executor_ram_gb = cores_per_executor * ram_per_core_gb
    executor_overhead_gb = max(executor_ram_gb * 0.1, 0.384)

    # Rough formula: enough executors so that each stage finishes in reasonable time
    # Assume we want each stage to run in ~5 minutes max
    # With 5 min per stage and avg_stages stages, total = avg_stages * 5 = goal
    # Adjust: more executors → each stage faster
    target_executors = max(int(total_partitions / tasks_per_executor / avg_stages), 4)

    print(f"  Data size:          {data_size_gb} GB")
    print(f"  Est. partitions:    {int(total_partitions)}")
    print(f"  Executor cores:     {cores_per_executor}")
    print(f"  Executor RAM:       {executor_ram_gb} GB + {executor_overhead_gb:.1f} GB overhead")
    print(f"  Suggested executors:{target_executors}")
    print(f"  Shuffle partitions: {max(int(total_partitions), 200)}")
    print(f"  Driver RAM:         {max(16, executor_ram_gb)} GB")

calculate_cluster_size(data_size_gb=1000)  # 1 TB job

# ============================================================
# SECTION 5: DYNAMIC ALLOCATION
# ============================================================
# spark.dynamicAllocation.enabled=true
#   Spark requests new executors when there are pending tasks in the queue.
#   Releases executors that have been idle for X seconds.
#
# Best for: shared clusters, variable workloads, streaming jobs.
# Worst for: predictable batch jobs where you want consistent performance.
#   (Dynamic allocation can SCALE DOWN during an idle stage, then scale
#    up again — adds executor startup latency between stages.)
#
# Configuration:
#   spark.dynamicAllocation.minExecutors: floor (default 0)
#   spark.dynamicAllocation.maxExecutors: ceiling
#   spark.dynamicAllocation.initialExecutors: starting point
#   spark.dynamicAllocation.executorIdleTimeout: release after N seconds idle
#   spark.dynamicAllocation.schedulerBacklogTimeout: request new exec after N seconds backlog
#
# REQUIRES external shuffle service (spark.shuffle.service.enabled=true)
# so that executor data is not lost when executors are released.

print("\n=== SECTION 5: Dynamic Allocation Config ===")
DYNAMIC_ALLOC_CONFIG = {
    "spark.dynamicAllocation.enabled": "true",
    "spark.dynamicAllocation.minExecutors": "2",
    "spark.dynamicAllocation.maxExecutors": "50",
    "spark.dynamicAllocation.initialExecutors": "10",
    "spark.dynamicAllocation.executorIdleTimeout": "60s",
    "spark.dynamicAllocation.schedulerBacklogTimeout": "1s",
    "spark.shuffle.service.enabled": "true",  # required with dynamic alloc on YARN
}
for k, v in DYNAMIC_ALLOC_CONFIG.items():
    print(f"  {k} = {v}")

# ============================================================
# SECTION 6: TESTING SPARK JOBS
# ============================================================
# Testing philosophy:
#   Unit tests  → test transformations on tiny synthetic DataFrames (local mode).
#   Integration → test on 1% sample of real data against staging cluster.
#   End-to-end  → full pipeline on staging with production-like data volume.
#
# CHISPA: drop-in assertion library for Spark DataFrame equality.
#   from chispa.dataframe_comparer import assert_df_equality
#   assert_df_equality(actual_df, expected_df, ignore_row_order=True)
#
# KEY PRINCIPLES:
#   1. Never test with production data in CI (PII, cost, speed).
#   2. Use local[*] master — no Hadoop/YARN needed for unit tests.
#   3. Inject SparkSession as a parameter to keep functions testable.
#   4. Test transformation logic, not Spark internals.
#   5. Avoid: collect() in tests on large DataFrames (slow + memory).

# Example testable transformation (pure function, takes/returns DataFrame)
def clean_orders(df):
    """
    Silver layer cleaning logic.
    This function is testable in isolation with any SparkSession.
    """
    return (
        df
        .filter(F.col("order_id").isNotNull())
        .filter(F.col("amount") > 0)
        .withColumn("amount_usd", F.round(F.col("amount"), 2))
        .withColumn("date_ts", F.to_date("order_date", "yyyy-MM-dd"))
        .dropDuplicates(["order_id"])
    )

# Example unit test structure (pytest — not runnable here without pytest):
UNIT_TEST_EXAMPLE = '''
# tests/test_clean_orders.py
import pytest
from pyspark.sql import SparkSession
from chispa.dataframe_comparer import assert_df_equality
from my_job import clean_orders

@pytest.fixture(scope="session")
def spark():
    return SparkSession.builder.master("local[2]").appName("tests").getOrCreate()

def test_clean_orders_removes_null_order_id(spark):
    input_df = spark.createDataFrame(
        [(None, "user_1", 50.0, "2024-01-01"),
         (1,    "user_2", 25.0, "2024-01-01")],
        ["order_id", "user_id", "amount", "order_date"]
    )
    result = clean_orders(input_df)
    assert result.count() == 1   # null row removed
    assert result.first()["order_id"] == 1

def test_clean_orders_removes_negative_amounts(spark):
    input_df = spark.createDataFrame(
        [(1, "user_1", -5.0, "2024-01-01"),
         (2, "user_2", 10.0, "2024-01-01")],
        ["order_id", "user_id", "amount", "order_date"]
    )
    result = clean_orders(input_df)
    assert result.count() == 1

def test_clean_orders_deduplicates(spark):
    input_df = spark.createDataFrame(
        [(1, "user_1", 50.0, "2024-01-01"),
         (1, "user_1", 50.0, "2024-01-01")],  # duplicate
        ["order_id", "user_id", "amount", "order_date"]
    )
    result = clean_orders(input_df)
    assert result.count() == 1
'''
print("\n=== SECTION 6: Unit Testing Pattern ===")
print("See UNIT_TEST_EXAMPLE variable for pytest + chispa test structure.")

# Demonstrate the clean_orders function locally
spark = (
    SparkSession.builder
    .appName("L08_ProductionArchitecture")
    .config("spark.sql.shuffle.partitions", "4")
    .master("local[4]")
    .getOrCreate()
)
spark.sparkContext.setLogLevel("WARN")

test_data = [
    (1, "user_001", 150.0, "2024-01-01"),
    (None, "user_002", 89.0, "2024-01-01"),  # null order_id → removed
    (3, "user_003", -5.0, "2024-01-02"),     # negative amount → removed
    (4, "user_004", 45.0, "2024-01-03"),
    (4, "user_004", 45.0, "2024-01-03"),     # duplicate → deduped
]
test_schema = ["order_id", "user_id", "amount", "order_date"]
raw_test = spark.createDataFrame(test_data, test_schema)
cleaned = clean_orders(raw_test)
print("\nClean orders result (should be 2 rows: order_id 1 and 4):")
cleaned.show()

# ============================================================
# SECTION 7: CI/CD FOR SPARK JOBS
# ============================================================
# Standard CI/CD pipeline for a Python Spark project:
#
# 1. PACKAGE: build Python wheel (or JAR for Scala/Java)
#    python setup.py bdist_wheel
#    → dist/my_spark_job-1.0.0-py3-none-any.whl
#
# 2. UNIT TESTS: run in CI with local mode
#    pytest tests/unit/ -v --tb=short
#    No cluster needed — SparkSession in local mode is instant.
#
# 3. INTEGRATION TESTS: deploy to staging cluster, run on sample data
#    spark-submit --master yarn ... my_job.py --env staging --date $(date)
#
# 4. PROMOTE: if staging passes, tag release and deploy to production
#    Upload wheel to S3:
#      aws s3 cp dist/my_spark_job-1.0.0.whl s3://code/releases/
#    Update Airflow DAG to point to new version.
#
# Example GitHub Actions workflow (CI):
GITHUB_ACTIONS_EXAMPLE = '''
# .github/workflows/spark_ci.yml
name: Spark CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with: {python-version: "3.11"}
      - run: pip install pyspark==3.5.0 chispa pytest
      - run: pytest tests/unit/ -v --tb=short
        env:
          PYSPARK_PYTHON: python3

  package:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v3
      - run: pip install build
      - run: python -m build --wheel
      - run: aws s3 cp dist/*.whl s3://my-code-bucket/releases/
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_KEY }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET }}
'''
print("\n=== SECTION 7: CI/CD Pipeline ===")
print("See GITHUB_ACTIONS_EXAMPLE for full CI/CD workflow.")

# ============================================================
# SECTION 8: MONITORING
# ============================================================
# SPARK UI (real-time, port 4040 while job runs):
#   Jobs → Stages → Tasks:
#     Task timings: see min/median/max duration. Large variance = skew.
#     Shuffle write/read size: large values = expensive shuffles.
#     GC time: > 20% of task time = too much GC → increase executor memory.
#     Spill (disk): non-zero = executor memory too small.
#   SQL tab: visualize query plan DAG with timing per node.
#   Storage tab: what is cached, how much memory used.
#
# SPARK HISTORY SERVER (post-job, port 18080):
#   Stores compressed event logs for completed jobs.
#   Configure: spark.eventLog.enabled=true, spark.eventLog.dir=s3://bucket/logs/
#   Run: ./sbin/start-history-server.sh
#
# CUSTOM METRICS → Prometheus → Grafana:
#   spark.metrics.conf: configure metric sinks (GraphiteSink, PrometheusSink).
#   JVM metrics: heap usage, GC time, thread count.
#   Application metrics: tasks completed, shuffle bytes, active stages.
#
# ALERTING:
#   PagerDuty / OpsGenie for SLA breaches.
#   Airflow email_on_failure + SLA miss callbacks.
#   CloudWatch / Stackdriver for cluster-level alerts (node failures, OOM).

print("\n=== SECTION 8: Monitoring Checklist ===")
monitoring_checklist = [
    "Spark UI: Stage → Task distribution (skew detection)",
    "Spark UI: Shuffle write/read bytes (large = expensive shuffles)",
    "Spark UI: GC time % (>20% = executor memory too small)",
    "Spark UI: Spill to disk (any non-zero = memory pressure)",
    "History Server: compare job duration trend across days",
    "Airflow: SLA miss alerts → PagerDuty",
    "CloudWatch/Stackdriver: executor OOM events, node failures",
    "Custom: job start/end timestamps to a metrics table in Delta",
]
for item in monitoring_checklist:
    print(f"  [ ] {item}")

# ============================================================
# SECTION 9: COMPLETE PRODUCTION PIPELINE
# ============================================================
print("\n=== SECTION 9: Full Medallion ETL Pipeline ===")

# Simulating 1 TB of daily order data (we use 100K rows as stand-in)
BASE_DIR = tempfile.mkdtemp()

# --- GENERATE SYNTHETIC DATA ---
order_rows = [
    (i, f"user_{i % 10000}", f"product_{i % 500}", round(10.0 + (i % 500) * 0.99, 2),
     "2024-01-" + str((i % 28 + 1)).zfill(2), ["pending", "shipped", "cancelled", "delivered"][i % 4])
    for i in range(100_000)
]
raw_schema = StructType([
    StructField("order_id", IntegerType()),
    StructField("user_id", StringType()),
    StructField("product_id", StringType()),
    StructField("amount", DoubleType()),
    StructField("order_date", StringType()),
    StructField("status", StringType()),
])
raw_df = spark.createDataFrame(order_rows, raw_schema)

# Add some dirty data for testing
dirty_rows = [
    (None, "user_X", "product_A", 100.0, "2024-01-01", "pending"),   # null order_id
    (100_001, "user_Y", "product_B", -50.0, "2024-01-01", "pending"), # negative amount
    (1, "user_001", "product_A", 150.0, "2024-01-01", "pending"),     # duplicate order_id=1
]
dirty_df = spark.createDataFrame(dirty_rows, raw_schema)
raw_with_dirty = raw_df.union(dirty_df)

# --- BRONZE LAYER ---
def bronze_ingest(raw_df, output_path, run_date):
    """
    Bronze: minimal transformation. Just add metadata columns.
    Schema-on-read: accept all columns including future ones (mergeSchema).
    """
    bronze_df = (
        raw_df
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_run_date", F.lit(run_date))
        .withColumn("_source_system", F.lit("orders_api_v2"))
    )
    (
        bronze_df.write
        .format("parquet")    # Use parquet for this demo (no Delta JAR)
        .mode("append")
        .partitionBy("order_date")
        .save(output_path)
    )
    count = bronze_df.count()
    print(f"  [Bronze] Ingested {count:,} rows to {output_path}")
    return count

# --- SILVER LAYER ---
def silver_transform(bronze_path, output_path):
    """
    Silver: deduplicate, validate, standardize, enrich.
    """
    bronze = spark.read.parquet(bronze_path)

    from pyspark.sql.window import Window

    silver = (
        bronze
        # Remove rows with null primary key
        .filter(F.col("order_id").isNotNull())
        # Remove invalid amounts
        .filter(F.col("amount") > 0)
        # Deduplicate: keep most recent ingestion per order_id
        .withColumn(
            "_rn",
            F.row_number().over(
                Window.partitionBy("order_id").orderBy(F.desc("_ingested_at"))
            )
        )
        .filter(F.col("_rn") == 1)
        .drop("_rn")
        # Standardize: parse date string to date type
        .withColumn("order_date_ts", F.to_date("order_date", "yyyy-MM-dd"))
        # Add derived columns for analytics
        .withColumn("is_cancelled", F.col("status") == "cancelled")
        .withColumn("is_completed", F.col("status").isin("shipped", "delivered"))
        # Extract year and month for partitioning
        .withColumn("year", F.year("order_date_ts"))
        .withColumn("month", F.month("order_date_ts"))
    )

    (
        silver.write
        .format("parquet")
        .mode("overwrite")
        .partitionBy("year", "month")
        .save(output_path)
    )
    count = silver.count()
    print(f"  [Silver] {count:,} clean rows written to {output_path}")
    return silver

# --- GOLD LAYER ---
def gold_aggregate(silver_path, output_path):
    """
    Gold: pre-aggregate for BI consumption.
    Daily revenue by product, user cohort metrics.
    """
    silver = spark.read.parquet(silver_path)

    # Aggregation 1: Daily revenue by product
    revenue_by_product = (
        silver
        .filter(F.col("is_cancelled") == False)
        .groupBy("order_date_ts", "product_id")
        .agg(
            F.sum("amount").alias("total_revenue"),
            F.count("*").alias("order_count"),
            F.avg("amount").alias("avg_order_value"),
            F.countDistinct("user_id").alias("unique_buyers"),
        )
        .withColumn("metric_type", F.lit("daily_product_revenue"))
    )

    # Aggregation 2: User cohort — first order date analysis
    user_first_order = (
        silver
        .groupBy("user_id")
        .agg(
            F.min("order_date_ts").alias("first_order_date"),
            F.count("*").alias("total_orders"),
            F.sum("amount").alias("lifetime_value"),
        )
        .withColumn("metric_type", F.lit("user_lifetime_value"))
    )

    # For this demo, write only the product revenue (schemas differ)
    (
        revenue_by_product.write
        .format("parquet")
        .mode("overwrite")
        .partitionBy("order_date_ts")
        .save(output_path)
    )
    print(f"  [Gold]   {revenue_by_product.count():,} aggregate rows written to {output_path}")

    return revenue_by_product

# --- RUN THE PIPELINE ---
BRONZE_PATH = os.path.join(BASE_DIR, "bronze")
SILVER_PATH = os.path.join(BASE_DIR, "silver")
GOLD_PATH = os.path.join(BASE_DIR, "gold")

print("\n--- Running Daily ETL Pipeline ---")
bronze_count = bronze_ingest(raw_with_dirty, BRONZE_PATH, "2024-01-01")
silver_df = silver_transform(BRONZE_PATH, SILVER_PATH)
gold_df = gold_aggregate(SILVER_PATH, GOLD_PATH)

# Final validation
gold_result = spark.read.parquet(GOLD_PATH)
print("\nTop 5 products by daily revenue:")
gold_result.orderBy(F.desc("total_revenue")).show(5, truncate=False)

# --- PIPELINE QUALITY CHECKS ---
print("\n--- Data Quality Checks ---")
silver_read = spark.read.parquet(SILVER_PATH)

# Check 1: No null order IDs
null_ids = silver_read.filter(F.col("order_id").isNull()).count()
print(f"  Null order_ids in Silver: {null_ids} (expected: 0)")
assert null_ids == 0, "QUALITY FAIL: null order_ids found"

# Check 2: No negative amounts
neg_amounts = silver_read.filter(F.col("amount") <= 0).count()
print(f"  Negative amounts in Silver: {neg_amounts} (expected: 0)")
assert neg_amounts == 0, "QUALITY FAIL: non-positive amounts found"

# Check 3: No duplicates by order_id
total_rows = silver_read.count()
distinct_order_ids = silver_read.select("order_id").distinct().count()
print(f"  Total rows: {total_rows:,}, Distinct order_ids: {distinct_order_ids:,}")
assert total_rows == distinct_order_ids, "QUALITY FAIL: duplicate order_ids found"

print("\nAll quality checks passed.")

print("\n=== L08 Complete ===")
print("Key takeaways:")
print("  1. Always use cluster deploy mode in production (not client)")
print("  2. Job clusters on Databricks, transient/serverless on EMR/Dataproc = cost savings")
print("  3. Airflow: retries=3, SLA monitors, email_on_failure")
print("  4. Unit test transformation functions with local SparkSession + chispa")
print("  5. Monitor: Spark UI for skew/spill, History Server for trends")
print("  6. Bronze → Silver → Gold with partition pruning and data quality checks")

spark.stop()
