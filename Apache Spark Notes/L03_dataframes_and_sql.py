# ============================================================
# L03: Spark DataFrames and SQL
# ============================================================
# WHAT: DataFrames are distributed tables with named, typed columns.
#       They expose a SQL-like API and map to the same physical engine
#       as Spark SQL queries. The Catalyst optimizer rewrites your
#       logical plan into an optimized physical plan before execution.
# WHY:  DataFrames are the primary API for 95% of Spark workloads.
#       They are 5-10x faster than RDDs for analytical work because
#       Catalyst + Tungsten generate native JVM code and avoid Python
#       serialization overhead. Always prefer DataFrames over RDDs
#       unless you genuinely need low-level control.
# LEVEL: Foundations
# ============================================================
"""
CONCEPT OVERVIEW:
    A Spark DataFrame is logically identical to a SQL table.
    Physically, it's a set of partitions distributed across executors.
    Unlike RDDs, DataFrames know the schema of their data (column names
    and types), which lets the optimizer make aggressive rewrites:
      - Push filters below joins (read less data).
      - Prune unneeded columns from scans (column pruning).
      - Reorder joins by estimated size (join reordering).
      - Replace SortMergeJoin with BroadcastHashJoin for small tables.

    DataFrame API and spark.sql() are interchangeable — they produce the
    same physical plan. Use whichever reads more clearly for the situation.

PRODUCTION USE CASE:
    E-commerce ETL pipeline:
      1. Read raw orders + products from Parquet in S3/GCS.
      2. Join on product_id (broadcast products as it's small).
      3. Filter to last 30 days.
      4. Aggregate revenue by category.
      5. Write results partitioned by year/month back to Parquet.
    DataFrames handle this efficiently end-to-end without any RDD code.

COMMON MISTAKES:
    1. Using inferSchema=True in production → reads data twice, slow.
       Always define schema explicitly with StructType.
    2. Writing Python UDFs that process one row at a time → 10-100x
       slower than native functions. Use Pandas UDFs for custom logic.
    3. Calling df.show() / df.count() in a loop → triggers a new Spark
       job each time. Compute once, cache, reuse.
    4. Joining on columns of different types → implicit cast or no match.
       Ensure join key types match.
    5. Forgetting to repartition before a large write → output is either
       too many tiny files or too few huge ones.
"""

# ── Imports ──────────────────────────────────────────────────
from pyspark.sql import SparkSession
from pyspark.sql.types import (
    StructType, StructField,
    StringType, IntegerType, DoubleType, LongType,
    TimestampType, DateType, BooleanType, ArrayType,
)
from pyspark.sql.functions import (
    col, lit, when,
    count, sum as spark_sum, avg, max as spark_max,
    min as spark_min, countDistinct,
    regexp_extract, regexp_replace,
    split, explode, collect_list, collect_set, array_contains,
    to_date, date_format, date_add, datediff,
    year, month, dayofweek, from_unixtime,
    struct, broadcast,
    udf, pandas_udf,
)
from pyspark.sql.types import StringType as ST
import pandas as pd

spark = SparkSession.builder \
    .appName("L03_DataFrames_SQL") \
    .config("spark.sql.adaptive.enabled", "true") \
    .getOrCreate()

spark.sparkContext.setLogLevel("ERROR")

# ─────────────────────────────────────────────────────────────
# SECTION 1: READING DATA AND WHY SCHEMA MATTERS
# ─────────────────────────────────────────────────────────────

# --- inferSchema=True: convenient but SLOW in production ---
# Spark reads the entire dataset TWICE: once to infer types,
# once to actually load. For a 100GB file that's 200GB of I/O.
# Use ONLY during exploration in a notebook.

# df_slow = spark.read.csv("orders.csv", header=True, inferSchema=True)

# --- Explicit schema: always use in production pipelines ---
# One pass over the data. Types are guaranteed. Nulls are controlled.
orders_schema = StructType([
    StructField("order_id",    LongType(),      nullable=False),
    StructField("user_id",     LongType(),      nullable=False),
    StructField("product_id",  LongType(),      nullable=False),
    StructField("quantity",    IntegerType(),   nullable=True),
    StructField("unit_price",  DoubleType(),    nullable=True),
    StructField("status",      StringType(),    nullable=True),
    StructField("created_at",  TimestampType(), nullable=True),
])

# Reading CSV with explicit schema:
# df_orders = spark.read.csv("s3://bucket/orders/", header=True, schema=orders_schema)

# --- Nested schema example ---
# JSON with {"user": {"id": 1, "name": "Alice"}, "amount": 99.5}
nested_schema = StructType([
    StructField("user", StructType([
        StructField("id",   LongType(),   nullable=False),
        StructField("name", StringType(), nullable=True),
    ])),
    StructField("amount", DoubleType(), nullable=True),
])
# df_nested = spark.read.json("events.json", schema=nested_schema)
# access: df_nested.select(col("user.id"), col("user.name"), col("amount"))

# --- Other readers ---
# df_parquet = spark.read.parquet("s3://bucket/data/")      # schema embedded in file
# df_json    = spark.read.json("data.json")                  # schema from first pass
# df_jdbc    = spark.read.jdbc(                              # RDBMS
#     url="jdbc:postgresql://host:5432/mydb",
#     table="orders",
#     properties={"user": "admin", "password": "secret", "driver": "org.postgresql.Driver"}
# )

# --- Sample DataFrame for demos ---
data = [
    (1, 101, 1001, 2, 29.99, "completed", "2024-11-15"),
    (2, 102, 1002, 1, 99.00, "completed", "2024-11-20"),
    (3, 101, 1003, 3, 15.50, "cancelled", "2024-11-25"),
    (4, 103, 1001, 1, 29.99, "completed", "2024-12-01"),
    (5, 102, 1004, 2, 45.00, "pending",   "2024-12-10"),
    (6, 104, 1002, 1, 99.00, "completed", "2024-12-12"),
]
columns = ["order_id", "user_id", "product_id", "quantity", "unit_price", "status", "created_at"]
df_orders = spark.createDataFrame(data, columns) \
    .withColumn("created_at", to_date(col("created_at"), "yyyy-MM-dd"))

products_data = [
    (1001, "Widget A",  "gadgets",   29.99),
    (1002, "Widget B",  "gadgets",   99.00),
    (1003, "Book X",    "books",     15.50),
    (1004, "Gadget Y",  "gadgets",   45.00),
]
df_products = spark.createDataFrame(products_data, ["product_id", "name", "category", "price"])

# ─────────────────────────────────────────────────────────────
# SECTION 2: SELECTING COLUMNS
# ─────────────────────────────────────────────────────────────

# --- By name (returns a new DataFrame) ---
df_orders.select("order_id", "user_id", "unit_price").show(3)

# --- Expression-based (col() allows arithmetic, aliasing) ---
df_orders.select(
    col("order_id"),
    (col("unit_price") * col("quantity")).alias("line_total"),  # compute on the fly
    col("status"),
).show(3)

# --- selectExpr: SQL string expressions — great for quick transforms ---
df_orders.selectExpr(
    "order_id",
    "unit_price * quantity AS line_total",
    "UPPER(status) AS status_upper",
).show(3)

# --- withColumn: add or replace a single column (keeps all existing cols) ---
df_orders = df_orders.withColumn(
    "line_total",
    col("unit_price") * col("quantity")
)
# Replace existing column (same name = overwrite):
df_orders = df_orders.withColumn("status", col("status").cast(StringType()))

# --- withColumnRenamed and drop ---
df_orders = df_orders.withColumnRenamed("created_at", "order_date")
df_clean  = df_orders.drop("line_total")  # remove column

# ─────────────────────────────────────────────────────────────
# SECTION 3: FILTERING
# ─────────────────────────────────────────────────────────────

# filter() and where() are identical — choose for readability.
completed = df_orders.filter(col("status") == "completed")
recent    = df_orders.where("order_date >= '2024-12-01'")

# Chaining filters: each adds a condition (logical AND).
# Catalyst merges all filters into one predicate before execution.
high_value_completed = (df_orders
    .filter(col("status") == "completed")
    .filter(col("unit_price") > 50.0)
)

# Null handling:
# df_orders.filter(col("quantity").isNull())
# df_orders.filter(col("quantity").isNotNull())

# ─────────────────────────────────────────────────────────────
# SECTION 4: AGGREGATIONS
# ─────────────────────────────────────────────────────────────

# groupBy creates a RelationalGroupedDataset.
# agg() applies multiple aggregate functions in a single pass (efficient).
summary = df_orders.groupBy("status").agg(
    count("*").alias("total_orders"),
    spark_sum("unit_price").alias("total_revenue"),
    avg("unit_price").alias("avg_price"),
    spark_max("unit_price").alias("max_price"),
    spark_min("unit_price").alias("min_price"),
    countDistinct("user_id").alias("unique_users"),
)
summary.show()

# ─────────────────────────────────────────────────────────────
# SECTION 5: BUILT-IN FUNCTIONS
# ─────────────────────────────────────────────────────────────

# --- Conditional logic: when().otherwise() ≈ SQL CASE WHEN ---
df_orders = df_orders.withColumn(
    "tier",
    when(col("unit_price") >= 90, "premium")
    .when(col("unit_price") >= 40,  "standard")
    .otherwise("budget")
)

# --- String functions ---
# Dummy text column for demonstration:
df_demo = spark.createDataFrame([
    ("user-12345",), ("user-67890",), ("admin-99999",)
], ["user_code"])

# regexp_extract: extract a capturing group from a pattern.
df_demo = df_demo.withColumn(
    "user_num",
    regexp_extract(col("user_code"), r"(\d+)$", 1)  # group 1 = digits at end
)

# regexp_replace: replace all matches of a pattern.
df_demo = df_demo.withColumn(
    "sanitized",
    regexp_replace(col("user_code"), r"admin-", "user-")
)

# split: splits a string into an ArrayType column.
df_demo = df_demo.withColumn("parts", split(col("user_code"), "-"))

# explode: converts one array-column row into multiple rows.
df_exploded = df_demo.select(explode(col("parts")).alias("part"))
df_exploded.show()

# collect_list / collect_set (inside groupBy):
# Aggregate all values into an array column.
df_orders.groupBy("user_id").agg(
    collect_list("product_id").alias("all_products"),   # keeps duplicates
    collect_set("product_id").alias("unique_products"), # deduplicates
).show()

# array_contains: check if value is in an array column.
# df_orders.filter(array_contains(col("tags"), "sale"))

# --- Date functions ---
df_orders = df_orders.withColumn("order_year",  year(col("order_date")))
df_orders = df_orders.withColumn("order_month", month(col("order_date")))
df_orders = df_orders.withColumn("day_of_week", dayofweek(col("order_date")))  # 1=Sun

# date_add: add N calendar days.
df_orders = df_orders.withColumn("due_date", date_add(col("order_date"), 30))

# datediff: integer days between two dates.
from pyspark.sql.functions import current_date
df_orders = df_orders.withColumn("days_old", datediff(current_date(), col("order_date")))

# date_format: format a date column as string.
df_orders.withColumn("month_str", date_format(col("order_date"), "yyyy-MM")).show(3)

# from_unixtime: convert Unix epoch to timestamp string.
# df.withColumn("ts", from_unixtime(col("epoch_ms") / 1000))

# --- struct: combine columns into a nested struct ---
df_orders.withColumn("meta", struct(col("order_id"), col("status"))).printSchema()

# ─────────────────────────────────────────────────────────────
# SECTION 6: JOINS
# ─────────────────────────────────────────────────────────────

# inner join: only matching keys on both sides.
df_joined = df_orders.join(df_products, on="product_id", how="inner")

# left join: all rows from left, NULLs for non-matching right.
df_left = df_orders.join(df_products, on="product_id", how="left")

# right, full (outer) follow the same pattern.

# left_semi: like IN (subquery). Returns left rows that HAVE a match.
# No columns from the right side are added. Efficient filter.
df_has_product = df_orders.join(df_products, on="product_id", how="left_semi")

# left_anti: like NOT IN. Returns left rows that have NO match.
df_no_product = df_orders.join(df_products, on="product_id", how="left_anti")

# --- Broadcast join: critical performance optimization ---
# When one side of a join is small (< spark.sql.autoBroadcastJoinThreshold,
# default 10MB), hint Spark to broadcast it.
# Effect: the small table is shipped to every executor. Zero shuffle.
# SortMergeJoin (shuffle) → BroadcastHashJoin (no shuffle).
df_joined_opt = df_orders.join(broadcast(df_products), on="product_id", how="inner")
df_joined_opt.explain()  # verify BroadcastHashJoin in physical plan

# ─────────────────────────────────────────────────────────────
# SECTION 7: UNION
# ─────────────────────────────────────────────────────────────

# union: by POSITION (dangerous if schemas differ even slightly).
# df_combined = df_q1.union(df_q2)

# unionByName: matches columns by NAME (safe, schema-tolerant).
# allowMissingColumns=True fills missing columns with NULL.
q3_data = [(10, 105, 1001, 1, 29.99, "completed", "2024-09-01", 29.99, "budget", 2024, 9, 5, "2024-10-01", 29)]
# df_q3.unionByName(df_q4, allowMissingColumns=True)

# ─────────────────────────────────────────────────────────────
# SECTION 8: TEMPORARY VIEWS AND SPARK SQL
# ─────────────────────────────────────────────────────────────

# createOrReplaceTempView: registers DF as a SQL table in this SparkSession.
# Lifetime = SparkSession. Multiple sessions cannot see each other's views.
df_orders.createOrReplaceTempView("orders")
df_products.createOrReplaceTempView("products")

# Now query with pure SQL. spark.sql returns a DataFrame.
sql_result = spark.sql("""
    SELECT
        p.category,
        COUNT(o.order_id)      AS num_orders,
        SUM(o.unit_price)      AS total_revenue,
        AVG(o.unit_price)      AS avg_price
    FROM orders  o
    JOIN products p ON o.product_id = p.product_id
    WHERE o.status = 'completed'
    GROUP BY p.category
    ORDER BY total_revenue DESC
""")
sql_result.show()

# createGlobalTempView: accessible as `global_temp.table_name`
# across DIFFERENT SparkSessions in the same application.
df_products.createGlobalTempView("global_products")
spark.sql("SELECT * FROM global_temp.global_products").show()

# ─────────────────────────────────────────────────────────────
# SECTION 9: UDFs AND PANDAS UDFs
# ─────────────────────────────────────────────────────────────

# --- Row-by-row Python UDF (SLOW — avoid in production) ---
# Spark serializes each row, sends to Python interpreter, gets result back.
# Overhead: Python ↔ JVM serialization per row. ~10x slower than native.
def categorize_price(price: float) -> str:
    if price is None:
        return "unknown"
    if price >= 90:
        return "premium"
    if price >= 40:
        return "standard"
    return "budget"

categorize_udf = udf(categorize_price, StringType())
# Use only when no native Spark function can do the same thing:
df_orders.withColumn("price_tier", categorize_udf(col("unit_price"))).show(3)

# --- Pandas UDF (vectorized — 10-100x faster than row UDF) ---
# Spark calls the function with a pandas Series (one partition at a time).
# No row-by-row Python serialization. Uses Apache Arrow for transfer.
@pandas_udf(ST())
def categorize_vectorized(series: pd.Series) -> pd.Series:
    def _cat(p):
        if p is None or pd.isna(p): return "unknown"
        if p >= 90:  return "premium"
        if p >= 40:  return "standard"
        return "budget"
    return series.apply(_cat)

df_orders.withColumn("price_tier2", categorize_vectorized(col("unit_price"))).show(3)

# ─────────────────────────────────────────────────────────────
# SECTION 10: QUERY PLAN INSPECTION (explain)
# ─────────────────────────────────────────────────────────────

# df.explain(True) prints 4 plans:
#   Parsed Logical Plan   → raw AST from your API calls
#   Analyzed Logical Plan → types resolved, columns validated
#   Optimized Logical Plan → Catalyst rules applied (filter pushdown, etc.)
#   Physical Plan         → actual execution strategy

df_joined_opt.explain(True)
# Look for in Physical Plan:
#   BroadcastHashJoin  → small table was broadcast (no shuffle)
#   SortMergeJoin      → both sides shuffled (expensive for large tables)
#   Filter             → check it appears ABOVE or BELOW join (below = better)
#   Project            → column pruning (fewer columns scanned)

# ─────────────────────────────────────────────────────────────
# SECTION 11: REAL E-COMMERCE PIPELINE
# ─────────────────────────────────────────────────────────────

# Full pipeline: orders + products → revenue by category → top 5 → write

# Step 1: Read (production would use explicit schemas and Parquet)
# df_orders   = spark.read.parquet("s3://bucket/orders/")
# df_products = spark.read.parquet("s3://bucket/products/")

# Step 2: Filter to last 30 days
from pyspark.sql.functions import current_date
last_30 = df_orders.filter(
    datediff(current_date(), col("order_date")) <= 30
)

# Step 3: Join — broadcast products (small dimension table)
enriched = last_30.join(broadcast(df_products), on="product_id", how="inner")

# Step 4: Compute revenue per category
revenue_by_cat = enriched \
    .filter(col("status") == "completed") \
    .groupBy("category", "order_year", "order_month") \
    .agg(
        spark_sum(col("unit_price") * col("quantity")).alias("revenue"),
        count("order_id").alias("num_orders"),
        countDistinct("user_id").alias("unique_buyers"),
    )

# Step 5: Top 5 categories by revenue
from pyspark.sql.window import Window
from pyspark.sql.functions import rank as spark_rank
w = Window.orderBy(col("revenue").desc())
top5 = revenue_by_cat \
    .withColumn("rank", spark_rank().over(w)) \
    .filter(col("rank") <= 5)

top5.show()

# Step 6: Write partitioned output
# Partitioning by year/month creates a directory tree:
# output/order_year=2024/order_month=12/part-00000.parquet
# Downstream tools can skip entire partitions (partition pruning).
# revenue_by_cat.write \
#     .mode("overwrite") \
#     .partitionBy("order_year", "order_month") \
#     .parquet("s3://bucket/output/revenue_by_category/")

spark.stop()
