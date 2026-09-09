# Apache Spark — Principal Engineer Deep Dive

Companion to L01-L08. Narrative depth, then a comprehensive common-to-
uncommon reference.


## Lazy Evaluation & the DAG, Precisely

**Beyond the lesson**: Spark's laziness isn't just "runs later" — every
transformation (`filter`, `select`, `join`) builds a logical plan
(a DAG of operations) WITHOUT touching data; only an ACTION (`collect`,
`write`, `count`) triggers actual execution. Catalyst (Spark SQL's
optimizer) then rewrites that logical plan — predicate pushdown (filter as
early/close to the data source as possible), column pruning (only read
columns actually used downstream), and join reordering — all BEFORE a
single task runs. This is why `df.filter(...).select(...)` written in a
"wasteful" order often performs identically to a hand-optimized version —
the optimizer rewrites it regardless of how you wrote it, within limits.

**Worked example**: A job that "hangs" isn't always stuck — checking the
Spark UI's DAG visualization for a job showing 1 task out of 200 running
for 10 minutes while 199 finished in seconds is the classic signature of
DATA SKEW (one partition has vastly more data than others, usually from a
join key or groupBy key with a hugely disproportionate value) — the fix is
salting the skewed key (adding a random suffix to spread it across more
partitions) or using Spark's adaptive query execution to handle skew automatically.

**Interview Q&A**:
- *Q: Why does calling `.collect()` on a huge DataFrame crash the driver, when the same computation runs fine distributed?* A: `.collect()` pulls ALL result rows back to the single driver process's memory — the computation itself was distributed across the cluster, but the ACTION of collecting concentrates everything onto one JVM with a fixed memory budget; use `.take(n)` for a sample, or write results to distributed storage instead of collecting to the driver.


## Shuffle — The Expensive Operation Everything Traces Back To

**Beyond the lesson**: A "shuffle" (redistributing data across the cluster
so records with the same key end up on the same partition — required for
`groupBy`, `join`, `distinct`) is THE dominant cost in most slow Spark
jobs, because it involves disk writes, network transfer, and disk reads
again — orders of magnitude slower than in-partition computation. Almost
every Spark performance-tuning technique (broadcast joins, bucketing,
partition pruning, `reduceByKey` over `groupByKey`) exists specifically to
AVOID or MINIMIZE shuffle, not to make the shuffle itself faster.

**Worked example**: Broadcast joins — when joining a huge DataFrame with a
SMALL one (small enough to fit in each executor's memory), Spark can
broadcast the small one to every executor and perform the join LOCALLY,
avoiding a shuffle of the huge DataFrame entirely. `spark.sql.autoBroadcastJoinThreshold`
controls the automatic threshold, but explicitly hinting
(`broadcast(small_df)`) is common when Spark's size estimate is wrong (a
filtered DataFrame's estimated size doesn't always reflect its post-filter reality).

**Interview Q&A**:
- *Q: `reduceByKey` vs `groupByKey` — why does one scale better?* A: `reduceByKey` combines values PER PARTITION before shuffling (a map-side combine, like a mini pre-aggregation), sending far less data over the network; `groupByKey` shuffles ALL raw values across the network first and only aggregates after — for a genuine reduction operation (sum, max), always prefer `reduceByKey`/`aggregateByKey` over `groupByKey` followed by a manual reduce.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Spark's execution model in practice
- **Driver vs Executors** — the driver holds the SparkContext, builds the
  DAG, and coordinates; executors do the actual distributed work — a
  driver that's undersized (memory) for the result-collection pattern
  above, or oversized relative to actual coordination needs, are both real, common misconfigurations.
- **Dynamic allocation** — lets a Spark application request MORE/FEWER
  executors during its run based on actual workload, instead of a fixed
  executor count for the whole job — important on shared clusters (YARN/K8s) to avoid over-reserving resources.
- **Adaptive Query Execution (AQE)** — Spark 3.x+'s runtime re-optimization:
  adjusts join strategies and partition counts based on ACTUAL
  runtime statistics (not just the pre-execution estimate), automatically
  handling many skew/sizing issues that used to require manual tuning.

### Storage formats & I/O
- **Parquet** — the dominant columnar format for Spark workloads;
  columnar layout means reading only needed columns skips the rest
  entirely on disk, plus built-in compression/predicate-pushdown support
  at the FILE level (not just Spark's own logic).
- **ORC** — a Parquet alternative, more common in the Hive/Hadoop ecosystem specifically.
  Delta Lake/Iceberg/Hudi (table formats, covered in Apache Spark L07 and
  Feature Stores & Modern Data Lake Notes) all build ON TOP of Parquet
  files, adding ACID transactions/schema evolution/time travel that raw
  Parquet files alone don't provide.

### Cluster managers & deployment
- **YARN** — the traditional Hadoop-ecosystem cluster manager, still
  common in on-prem/legacy big-data deployments.
- **Kubernetes** — the modern default for new Spark deployments,
  running executors as pods — see Kubernetes Notes for the underlying
  orchestration; Spark on K8s has matured significantly and is now the recommended path for greenfield deployments.
- **Databricks / EMR / Dataproc / HDInsight** — the managed Spark
  platforms (see Data Engineering Notes L05-L06 for Databricks depth) —
  most companies run managed Spark rather than hand-operating raw clusters at this point.

### Alternatives & complementary tools
- **Flink** — a genuine alternative for TRUE streaming (event-at-a-time,
  lower latency) versus Spark Structured Streaming's micro-batch model —
  chosen specifically when sub-second processing latency matters more than Spark's broader ecosystem/batch capability.
- **Dask** — a Python-native distributed computing library, a lighter-
  weight alternative to Spark for teams already deep in the pandas/NumPy
  ecosystem who want to scale existing Python code rather than rewrite in
  Spark's DataFrame API.
- **Ray** — increasingly used for distributed ML workloads specifically
  (distributed training/hyperparameter tuning), a different niche from
  Spark's data-processing focus though the two are sometimes used together in ML pipelines.


## NICHE BUT REAL

- **Bucketing** — pre-shuffling and pre-sorting data by a key at WRITE
  time (not read time), so subsequent joins on that same key can skip the
  shuffle step entirely at read time — a genuinely underused technique for
  frequently-joined large tables in a data warehouse setting.
- **Speculative execution** — Spark can proactively launch a duplicate
  task for a straggling task (one running much slower than its peers,
  often due to a slow/failing node) and use whichever finishes first — a
  real mitigation for the "one slow node drags down the whole job" problem
  distinct from data-skew-caused straggling.
- **Z-ordering / data skipping** (Delta Lake) — physically co-locating
  related data on disk based on a chosen column, letting queries filtering
  on that column skip reading entire files that can't possibly contain matching rows.
- **Off-heap memory tuning** — Spark's default on-heap JVM memory model
  can suffer GC pauses under memory pressure; off-heap storage
  (`spark.memory.offHeap.enabled`) bypasses JVM garbage collection for
  cached data, a real production tuning lever for GC-pause-sensitive
  latency-critical Spark applications.
