# ============================================================
# L02: Spark RDDs (Resilient Distributed Datasets)
# ============================================================
# WHAT: The low-level distributed data abstraction in Spark.
#       An RDD is an immutable, partitioned collection of records
#       that can be operated on in parallel across a cluster.
# WHY:  RDDs are the foundation of Spark. Even DataFrames are
#       built on top of them. Understanding RDDs explains WHY
#       Spark behaves the way it does (lazy eval, shuffles, etc).
# LEVEL: Foundations
# ============================================================
"""
CONCEPT OVERVIEW:
    RDD = Resilient Distributed Dataset.
    - Resilient: auto-recovers from node failures using lineage graph.
    - Distributed: data is split into partitions across executors.
    - Dataset: a collection of records (any Python object).

    Two types of RDD operations:
      1. Transformations (lazy) — describe WHAT to do, nothing runs.
      2. Actions         (eager) — trigger actual computation.

    Spark builds a DAG (Directed Acyclic Graph) of transformations.
    When an action is called, the DAG is compiled into stages and
    sent to executors as tasks.

PRODUCTION USE CASE:
    - Parsing raw, unstructured log files where each record needs
      complex Python-object manipulation (e.g., regex, custom classes).
    - ML model training loops that re-use the same dataset many times
      (cache the RDD to avoid recomputation each iteration).
    - Processing binary or custom-serialized formats that Spark's
      built-in readers don't support.

COMMON MISTAKES:
    1. Calling collect() on a huge RDD → OOM on the driver.
    2. Using groupByKey() instead of reduceByKey() → massive shuffle.
    3. Forgetting to cache() an RDD used in a loop → recomputed every iteration.
    4. Creating accumulators inside transformations and reading inside the same job
       (task retries can double-count).
    5. Using too many partitions (overhead per task) or too few (one huge task).
"""

# ── Imports ──────────────────────────────────────────────────
from pyspark import SparkContext, SparkConf
from pyspark.storagelevel import StorageLevel

# In a real job you'd get sc from SparkSession.sparkContext.
# Here we show explicit construction for clarity.
conf = SparkConf().setAppName("L02_RDDs").setMaster("local[4]")
sc   = SparkContext(conf=conf)
sc.setLogLevel("ERROR")  # reduce noise in demo output

# ─────────────────────────────────────────────────────────────
# SECTION 1: RDD CREATION
# ─────────────────────────────────────────────────────────────

# --- 1a. parallelize: distribute a local Python collection ---
# numSlices controls how many partitions are created.
# Rule of thumb: 2-4 partitions per CPU core.
numbers_rdd = sc.parallelize([1, 2, 3, 4, 5, 6, 7, 8], numSlices=4)
print("Partitions:", numbers_rdd.getNumPartitions())  # 4

# --- 1b. textFile: read a text file (one line = one record) ---
# Spark splits the file across partitions automatically.
# minPartitions hint: Spark may create more, never fewer.
# lines_rdd = sc.textFile("hdfs:///data/logs/*.log", minPartitions=8)

# --- 1c. wholeTextFiles: reads ENTIRE file as one record ---
# Returns (path, content) pairs. Good for small files where you
# need the full file content together (e.g., JSON configs, XML docs).
# files_rdd = sc.wholeTextFiles("hdfs:///data/configs/")
# path, content = files_rdd.first()

# ─────────────────────────────────────────────────────────────
# SECTION 2: TRANSFORMATIONS (LAZY — nothing executes yet)
# ─────────────────────────────────────────────────────────────

# --- map: apply a function to every element, one-to-one ---
squared = numbers_rdd.map(lambda x: x ** 2)
# [1, 4, 9, 16, 25, 36, 49, 64]  (not computed yet!)

# --- flatMap: like map but flattens one level of nesting ---
# Each input element can produce 0, 1, or many output elements.
words_rdd = sc.parallelize(["hello world", "spark is fast"])
word_list  = words_rdd.flatMap(lambda line: line.split(" "))
# ["hello", "world", "spark", "is", "fast"]

# --- filter: keep only elements where f(x) is True ---
evens = numbers_rdd.filter(lambda x: x % 2 == 0)
# [2, 4, 6, 8]

# --- mapPartitions: like map but operates on an ENTIRE partition ---
# More efficient than map when each call has setup overhead
# (e.g., opening a DB connection once per partition, not per row).
def process_partition(iterator):
    # Imagine: conn = db.connect()  ← done ONCE per partition
    for record in iterator:
        yield record * 10
    # conn.close()

scaled = numbers_rdd.mapPartitions(process_partition)

# --- sample: random sample of the RDD ---
# withReplacement=False, fraction=0.5, seed=42
sampled = numbers_rdd.sample(withReplacement=False, fraction=0.5, seed=42)

# --- Set operations ---
rdd_a = sc.parallelize([1, 2, 3, 4])
rdd_b = sc.parallelize([3, 4, 5, 6])
union_rdd        = rdd_a.union(rdd_b)          # [1,2,3,4,3,4,5,6] — includes dupes
intersection_rdd = rdd_a.intersection(rdd_b)   # [3, 4] — shuffle required
distinct_rdd     = union_rdd.distinct()         # [1,2,3,4,5,6] — shuffle required

# --- Pair RDD transformations (require (key, value) tuples) ---
pairs = sc.parallelize([
    ("apple", 3), ("banana", 1), ("apple", 2),
    ("cherry", 5), ("banana", 4), ("cherry", 1),
])

# reduceByKey: pre-aggregates locally on each partition FIRST,
# then shuffles only the partial results. Much more efficient than groupByKey.
totals = pairs.reduceByKey(lambda a, b: a + b)
# [("apple",5), ("banana",5), ("cherry",6)]

# sortByKey: sorts by key. asc=False for descending.
sorted_pairs = totals.sortByKey(ascending=True)

# join: inner join two pair RDDs on key.
# Only keys present in BOTH RDDs appear in the result.
product_info = sc.parallelize([("apple", "fruit"), ("banana", "fruit")])
joined = totals.join(product_info)
# [("apple", (5, "fruit")), ("banana", (5, "fruit"))]

# cogroup: group all values for each key from MULTIPLE RDDs.
# Returns (key, (iter_from_rdd1, iter_from_rdd2)).
cogrouped = pairs.cogroup(product_info)

# cartesian: every combination of elements. O(m*n) size!
# Use sparingly — only for small RDDs.
small_a = sc.parallelize([1, 2])
small_b = sc.parallelize(["a", "b"])
cart = small_a.cartesian(small_b)  # [(1,"a"),(1,"b"),(2,"a"),(2,"b")]

# ─────────────────────────────────────────────────────────────
# SECTION 3: WHY groupByKey() IS DANGEROUS
# ─────────────────────────────────────────────────────────────

# BAD: groupByKey shuffles ALL values across the network.
# All ("apple", 3), ("apple", 2) values physically move to one node.
# If one key has millions of values → one executor OOMs.
bad_totals = pairs.groupByKey().mapValues(sum)

# GOOD: reduceByKey applies the combiner LOCALLY first.
# Only one ("apple", 5) per partition crosses the network.
# This is like a map-side combine in Hadoop.
good_totals = pairs.reduceByKey(lambda a, b: a + b)

# ─────────────────────────────────────────────────────────────
# SECTION 4: aggregateByKey — COUNT + SUM IN ONE PASS
# ─────────────────────────────────────────────────────────────

# aggregateByKey(zeroValue, seqFunc, combFunc)
# zeroValue: initial accumulator state per partition (not shared).
# seqFunc(acc, value): folds one value into the accumulator.
# combFunc(acc1, acc2): merges two accumulators (from different partitions).

# Goal: compute (count, total_sum) per key in a single shuffle.
zero   = (0, 0)                              # (count, sum)
seqOp  = lambda acc, v: (acc[0]+1, acc[1]+v) # add one record
combOp = lambda a,  b:  (a[0]+b[0], a[1]+b[1]) # merge partitions

agg_result = pairs.aggregateByKey(zero, seqOp, combOp)
# [("apple",(2,5)), ("banana",(2,5)), ("cherry",(2,6))]

# ─────────────────────────────────────────────────────────────
# SECTION 5: ACTIONS (trigger computation)
# ─────────────────────────────────────────────────────────────

# collect(): brings ALL data to the driver as a Python list.
# DANGER: never call on large RDDs. Use only when data fits in driver RAM.
result_list = totals.collect()  # safe here (tiny RDD)
print("collect():", result_list)

# count(): number of elements. Efficient — no data transfer to driver.
print("count():", numbers_rdd.count())  # 8

# first(): returns first element. Very fast (only evaluates first partition).
print("first():", numbers_rdd.first())  # 1

# take(n): first n elements. Does NOT sort. Efficient.
print("take(3):", numbers_rdd.take(3))  # [1, 2, 3]

# takeSample: random n elements. withReplacement controls re-sampling.
print("takeSample:", numbers_rdd.takeSample(withReplacement=False, num=3, seed=1))

# reduce: aggregate all elements to a single value on the driver.
total = numbers_rdd.reduce(lambda a, b: a + b)
print("sum via reduce:", total)  # 36

# foreach: runs f(element) on each element IN THE EXECUTORS.
# Used for writing to external systems (Kafka, DB). No return value.
numbers_rdd.foreach(lambda x: None)  # placeholder

# saveAsTextFile: writes each partition as a file in the directory.
# numbers_rdd.saveAsTextFile("hdfs:///output/numbers/")

# countByKey: returns {key: count} dict on driver. OK for small key sets.
print("countByKey:", pairs.countByKey())

# collectAsMap: returns {key: value} dict. Only safe for small pair RDDs.
print("collectAsMap:", totals.collectAsMap())

# ─────────────────────────────────────────────────────────────
# SECTION 6: PARTITIONS — repartition vs coalesce
# ─────────────────────────────────────────────────────────────

# sc.defaultParallelism = number of CPU cores (or executor cores).
print("Default parallelism:", sc.defaultParallelism)

# repartition(n): FULL shuffle. Can increase OR decrease partitions.
# Use when you need more parallelism (e.g., after a filter that removed 90% of data).
more_parts = numbers_rdd.repartition(8)

# coalesce(n): NARROW transformation (no full shuffle). Only DECREASES.
# Much faster than repartition when reducing partition count.
# Use before write operations to avoid writing 200 tiny files.
fewer_parts = numbers_rdd.coalesce(2)
# fewer_parts.saveAsTextFile("output/")  → writes 2 files

# ─────────────────────────────────────────────────────────────
# SECTION 7: PERSISTENCE (CACHING)
# ─────────────────────────────────────────────────────────────

# Without caching: each action on an RDD recomputes from source.
# With caching: the first action materializes the RDD in memory,
# subsequent actions read from cache. Critical for iterative ML.

hot_rdd = numbers_rdd.map(lambda x: x * 2)

# cache() = persist(MEMORY_ONLY). Stores Java objects in heap.
hot_rdd.cache()

# persist(level) gives explicit control:
# MEMORY_ONLY       → fastest, fails if RAM full (re-computes on miss)
# MEMORY_AND_DISK   → spills to disk if RAM full (slower but reliable)
# DISK_ONLY         → no RAM at all (slow, useful for very large RDDs)
# MEMORY_ONLY_SER   → stores serialized bytes (2x smaller, 20% slower to read)
# OFF_HEAP          → Tungsten off-heap memory (avoids GC pressure)

big_rdd = sc.parallelize(range(1_000_000))
big_rdd.persist(StorageLevel.MEMORY_AND_DISK)

# Trigger caching (lazy — nothing stored until first action):
big_rdd.count()

# Free memory when done:
big_rdd.unpersist()
hot_rdd.unpersist()

# ─────────────────────────────────────────────────────────────
# SECTION 8: ACCUMULATORS
# ─────────────────────────────────────────────────────────────

# Accumulators: distributed counters/sums. Workers only ADD to them.
# The driver reads the final value after an action completes.
# WARNING: if a task is retried (due to failure), it may add twice.
# Only reliable in deterministic, non-retried actions.

error_count = sc.accumulator(0, "parse_errors")

def parse_record(line):
    global error_count
    try:
        return int(line.strip())
    except ValueError:
        error_count += 1  # only executed inside executor
        return None

raw_lines = sc.parallelize(["1", "2", "bad", "4", "oops"])
parsed    = raw_lines.map(parse_record).filter(lambda x: x is not None)
parsed.count()  # triggers the action → accumulators updated

print("Parse errors:", error_count.value)  # 2

# ─────────────────────────────────────────────────────────────
# SECTION 9: BROADCAST VARIABLES
# ─────────────────────────────────────────────────────────────

# Without broadcast: if a task uses a large Python dict, Spark ships
# a copy of it with EVERY task (100 tasks → 100 copies of the dict).
# With broadcast: ONE copy is sent to each executor node and cached.
# All tasks on that node share the single copy.

# Good for: lookup tables, model weights, config dicts.
lookup_table = {"apple": "fruit", "banana": "fruit", "carrot": "vegetable"}
bc_lookup    = sc.broadcast(lookup_table)

def categorize(pair):
    name, count = pair
    # bc.value accesses the executor-local copy (no network call):
    category = bc_lookup.value.get(name, "unknown")
    return (category, count)

categorized = pairs.map(categorize).reduceByKey(lambda a, b: a + b)
print("Categorized:", categorized.collect())

# Free broadcast from executor memory when no longer needed:
bc_lookup.unpersist()

# ─────────────────────────────────────────────────────────────
# SECTION 10: RDD vs DataFrame — WHEN TO USE WHICH
# ─────────────────────────────────────────────────────────────

# RDD is the RIGHT choice when:
#   - Data is truly unstructured (binary, custom serialized, mixed types).
#   - You need Python-object-level transformations (custom classes, closures).
#   - You're implementing low-level Spark internals or ML algorithms.
#   - You need fine-grained control over partitioning and data locality.

# DataFrame is the RIGHT choice when:
#   - Data has a schema (CSV, JSON, Parquet, DB tables).
#   - You're doing analytics: filter, join, aggregate, group.
#   - Performance matters — Catalyst optimizer + Tungsten engine
#     generates JVM bytecode, 5-10x faster than Python RDD.

# ── Classic Word Count: RDD (5 lines) ──
from pyspark.sql import SparkSession
spark = SparkSession.builder.getOrCreate()

text_rdd   = sc.parallelize(["the cat sat on the mat", "the cat wore a hat"])
wc_rdd     = (text_rdd
               .flatMap(lambda l: l.split())
               .map(lambda w: (w, 1))
               .reduceByKey(lambda a, b: a + b)
               .sortBy(lambda kv: -kv[1]))
print("RDD word count:", wc_rdd.take(5))

# ── Same Word Count: DataFrame (3 lines) — FASTER ──
from pyspark.sql.functions import explode, split, col, count as cnt

text_df = spark.createDataFrame([("the cat sat on the mat",), ("the cat wore a hat",)], ["line"])
wc_df   = (text_df
            .select(explode(split(col("line"), " ")).alias("word"))
            .groupBy("word").agg(cnt("*").alias("count"))
            .orderBy(col("count").desc()))
wc_df.show(5)
# DataFrame wins: Catalyst rewrites the plan, Tungsten avoids Python GIL.

# ── Cleanup ──────────────────────────────────────────────────
sc.stop()
