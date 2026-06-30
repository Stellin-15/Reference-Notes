# ============================================================
# L04: Spark Window Functions
# ============================================================
# WHAT: Window functions compute a value for each row based on a
#       set of related rows (the "window") WITHOUT collapsing them
#       into a single group. Unlike GROUP BY, all original rows
#       are preserved and each gets a new computed column.
# WHY:  Many analytics patterns are impossible with pure GROUP BY:
#       running totals, moving averages, ranking within groups,
#       lag/lead comparisons, deduplication, session detection.
#       Window functions express these idioms cleanly and efficiently.
# LEVEL: Intermediate
# ============================================================
"""
CONCEPT OVERVIEW:
    A window = { partitionBy (which rows are peers) +
                 orderBy    (order within the partition) +
                 frame      (which rows around current row count) }

    Three categories of window functions:
      1. Ranking   — row_number, rank, dense_rank, ntile, percent_rank
      2. Analytics — lag, lead, first_value, last_value, nth_value
      3. Aggregate — sum, avg, max, min, count used with .over(window)

    Key insight: unlike GROUP BY, window functions never reduce row count.
    Every input row appears in the output, decorated with the window result.

PRODUCTION USE CASE:
    - Deduplication: keep the latest version of each entity record when
      a CDC (change-data-capture) feed produces multiple versions.
    - Sessionization: turn raw clickstream events into user sessions
      by detecting idle gaps > N minutes.
    - Financial reporting: running revenue totals, 7-day moving averages
      for dashboards.
    - E-commerce ranking: rank products by revenue within each category
      to build "Top N per Category" pages.

COMMON MISTAKES:
    1. last_value() without ROWS BETWEEN unboundedPreceding AND
       unboundedFollowing returns the CURRENT ROW's value (default frame
       ends at current row). Almost always a bug.
    2. Partitioning on a low-cardinality column (e.g., gender=M/F) sends
       half the dataset to a single executor → skew and OOM.
    3. Forgetting orderBy when using lag/lead → results are non-deterministic.
    4. Using collect_list().over(window) for sessionization when a simpler
       cumulative sum pattern is cleaner and faster.
    5. Not caching the DataFrame before multiple window computations —
       each .over() triggers a separate shuffle.
"""

# ── Imports ──────────────────────────────────────────────────
from pyspark.sql import SparkSession
from pyspark.sql.window import Window
from pyspark.sql.functions import (
    col, lit, sum as spark_sum, avg, max as spark_max,
    count, row_number, rank, dense_rank, ntile,
    lag, lead, first, last,
    when, unix_timestamp, to_timestamp,
    round as spark_round,
)

spark = SparkSession.builder \
    .appName("L04_WindowFunctions") \
    .config("spark.sql.adaptive.enabled", "true") \
    .getOrCreate()
spark.sparkContext.setLogLevel("ERROR")

# ─────────────────────────────────────────────────────────────
# SECTION 1: WINDOW SPEC FUNDAMENTALS
# ─────────────────────────────────────────────────────────────

# A Window spec is a blueprint — it does nothing on its own.
# It is COMBINED with a function via function.over(window_spec).

# partitionBy: like GROUP BY — splits data into independent windows.
#   All rows with the same partition key are in the same window.
#   Window function only looks at rows within its own partition.
# orderBy: defines the row ordering WITHIN each partition.
#   Required for lag, lead, row_number, cumulative aggregates.
# rowsBetween / rangeBetween: defines which rows around the current
#   row are included in the aggregate frame.

user_window = Window.partitionBy("user_id").orderBy(col("event_time").asc())

# Constants for frame boundaries:
UNBOUNDED_PREC = Window.unboundedPreceding  # -inf (start of partition)
UNBOUNDED_FOLL = Window.unboundedFollowing  # +inf (end of partition)
CURRENT_ROW    = Window.currentRow          # 0

# ─────────────────────────────────────────────────────────────
# SECTION 2: RANKING FUNCTIONS
# ─────────────────────────────────────────────────────────────

sales_data = [
    ("alice",   "Q1", 1500), ("alice",   "Q2", 2000), ("alice",   "Q3", 1800),
    ("bob",     "Q1", 2500), ("bob",     "Q2", 2500), ("bob",     "Q3", 1200),
    ("charlie", "Q1", 800),  ("charlie", "Q2", 1200), ("charlie", "Q3", 2200),
]
df_sales = spark.createDataFrame(sales_data, ["rep", "quarter", "revenue"])

# Window: rank all reps by revenue across all quarters (no partitionBy).
global_win = Window.orderBy(col("revenue").desc())

df_ranked = df_sales \
    .withColumn("row_num",    row_number().over(global_win)) \
    .withColumn("rank_col",   rank().over(global_win)) \
    .withColumn("dense_rank", dense_rank().over(global_win)) \
    .withColumn("quartile",   ntile(4).over(global_win))

# row_number: unique sequence 1..N. Ties broken arbitrarily.
# rank:       gaps on ties. Scores 2500,2500,2200 → ranks 1,1,3.
# dense_rank: no gaps.     Scores 2500,2500,2200 → ranks 1,1,2.
# ntile(n):   assigns 1..n bucket (like percentile buckets).
df_ranked.orderBy("row_num").show()

# ─────────────────────────────────────────────────────────────
# SECTION 3: LAG AND LEAD
# ─────────────────────────────────────────────────────────────

# lag(col, offset, default):  value from N rows BEFORE current row.
# lead(col, offset, default): value from N rows AFTER current row.
# default: returned when the window boundary is exceeded (NULL by default).

per_rep_win = Window.partitionBy("rep").orderBy("quarter")

df_sales = df_sales \
    .withColumn("prev_revenue", lag("revenue",  1, 0).over(per_rep_win)) \
    .withColumn("next_revenue", lead("revenue", 1, 0).over(per_rep_win)) \
    .withColumn("qoq_change",   col("revenue") - lag("revenue", 1).over(per_rep_win))

df_sales.show()
# Use case: detect if revenue increased or decreased quarter-over-quarter.
# qoq_change is NULL for Q1 (no previous row) — expected behavior.

# ─────────────────────────────────────────────────────────────
# SECTION 4: FRAME SPECIFICATION (ROWS BETWEEN vs RANGE BETWEEN)
# ─────────────────────────────────────────────────────────────

# Frame determines WHICH rows contribute to the aggregate for each row.

# ROWS BETWEEN: frame boundary based on physical row POSITION.
#   rowsBetween(-2, 0)  → current row + 2 preceding rows (3-row window).
#   rowsBetween(UNBOUNDED_PREC, CURRENT_ROW) → all rows from start to here.

# RANGE BETWEEN: frame boundary based on VALUE in orderBy column.
#   rangeBetween(-7, 0) → rows where orderBy value is within 7 of current.
#   Useful for time ranges when timestamps are numeric (unix epoch).
#   CAUTION: rows with identical orderBy values are all included or excluded together.

daily_data = [
    ("2024-01-01", 100), ("2024-01-02", 150), ("2024-01-03", 120),
    ("2024-01-04", 200), ("2024-01-05", 180), ("2024-01-06", 220),
    ("2024-01-07", 170), ("2024-01-08", 190), ("2024-01-09", 210),
]
df_daily = spark.createDataFrame(daily_data, ["date_str", "dau"]) \
    .withColumn("date_col", col("date_str").cast("date"))

date_win = Window.orderBy("date_str")  # global (no partitionBy)

# Cumulative sum from the very beginning up to the current row:
cumulative_frame = Window.orderBy("date_str").rowsBetween(UNBOUNDED_PREC, CURRENT_ROW)
df_daily = df_daily.withColumn("cumulative_dau", spark_sum("dau").over(cumulative_frame))

# 3-day moving average (current row + 2 preceding rows):
moving_3 = Window.orderBy("date_str").rowsBetween(-2, CURRENT_ROW)
df_daily = df_daily.withColumn("ma_3day", spark_round(avg("dau").over(moving_3), 1))

# Entire partition total (same value on all rows — like a GROUP BY broadcast):
total_frame = Window.orderBy("date_str").rowsBetween(UNBOUNDED_PREC, UNBOUNDED_FOLL)
df_daily = df_daily.withColumn("total_dau", spark_sum("dau").over(total_frame))

# Percent of total: combine running total with partition total:
df_daily = df_daily.withColumn(
    "pct_of_total",
    spark_round(col("cumulative_dau") / col("total_dau") * 100, 1)
)

df_daily.show()

# ─────────────────────────────────────────────────────────────
# SECTION 5: FIRST_VALUE AND LAST_VALUE GOTCHA
# ─────────────────────────────────────────────────────────────

# first_value: returns the first value in the window frame.
# last_value:  returns the last value in the window frame.
#              DEFAULT FRAME: rowsBetween(UNBOUNDED_PREC, CURRENT_ROW)
#              This means last_value returns the CURRENT ROW'S value
#              (always the last in the frame that ends here).
#              FIX: extend the frame to UNBOUNDED_FOLL.

w_full = Window.partitionBy("rep").orderBy("quarter") \
    .rowsBetween(UNBOUNDED_PREC, UNBOUNDED_FOLL)

df_sales = df_sales \
    .withColumn("first_qtr_rev", first("revenue").over(w_full)) \
    .withColumn("last_qtr_rev",  last("revenue").over(w_full))  # correct with full frame

df_sales.show()

# ─────────────────────────────────────────────────────────────
# EXAMPLE 1: Running Revenue Total Per User Per Month
# ─────────────────────────────────────────────────────────────

orders_data = [
    (1, "2024-01-05", 99.0), (1, "2024-01-12", 45.0), (1, "2024-01-20", 30.0),
    (1, "2024-02-03", 120.0),(2, "2024-01-08", 60.0), (2, "2024-01-22", 75.0),
]
df_ord = spark.createDataFrame(orders_data, ["user_id", "order_date", "amount"]) \
    .withColumn("order_date", col("order_date").cast("date"))

# Running total resets per user.
# partitionBy user_id ensures each user has an independent window.
run_win = Window.partitionBy("user_id").orderBy("order_date") \
    .rowsBetween(UNBOUNDED_PREC, CURRENT_ROW)

df_ord = df_ord.withColumn("running_total", spark_sum("amount").over(run_win))
print("=== Example 1: Running Revenue ===")
df_ord.orderBy("user_id", "order_date").show()

# ─────────────────────────────────────────────────────────────
# EXAMPLE 2: 7-Day Moving Average of Daily Active Users
# ─────────────────────────────────────────────────────────────

# 7-day window = current row + 6 preceding rows.
# rowsBetween(-6, 0) means: go back 6 physical rows, come forward to current.
ma7_win = Window.orderBy("date_str").rowsBetween(-6, CURRENT_ROW)
df_ma7  = df_daily.withColumn("ma_7day", spark_round(avg("dau").over(ma7_win), 1))
print("=== Example 2: 7-Day Moving Average ===")
df_ma7.select("date_str", "dau", "ma_7day").show()

# ─────────────────────────────────────────────────────────────
# EXAMPLE 3: Rank Products by Revenue Within Category
# ─────────────────────────────────────────────────────────────

prod_data = [
    ("electronics", "TV",      5000), ("electronics", "Laptop",  8000),
    ("electronics", "Tablet",  3000), ("books",       "Sci-Fi",   500),
    ("books",       "Thriller", 700), ("books",       "History",  300),
]
df_prod = spark.createDataFrame(prod_data, ["category", "product", "revenue"])

# partitionBy category → each category gets independent ranking.
cat_win = Window.partitionBy("category").orderBy(col("revenue").desc())

df_prod = df_prod \
    .withColumn("rank_in_cat", dense_rank().over(cat_win)) \
    .withColumn("top3", col("rank_in_cat") <= 3)  # True if top 3 in category

print("=== Example 3: Rank Within Category ===")
df_prod.orderBy("category", "rank_in_cat").show()

# ─────────────────────────────────────────────────────────────
# EXAMPLE 4: Deduplication — Keep Latest Record Per user_id
# ─────────────────────────────────────────────────────────────

# Classic pattern for CDC (Change Data Capture) feeds.
# Each entity can have multiple versions; we want the most recent.

user_records = [
    (101, "alice@old.com",  "2024-01-01 08:00:00"),
    (101, "alice@new.com",  "2024-06-01 12:00:00"),  # ← keep this
    (102, "bob@example.com","2024-03-15 10:00:00"),  # ← keep this (only record)
    (103, "charlie@a.com",  "2024-02-01 09:00:00"),
    (103, "charlie@b.com",  "2024-05-01 11:00:00"),  # ← keep this
]
df_users = spark.createDataFrame(user_records, ["user_id", "email", "updated_at_str"]) \
    .withColumn("updated_at", to_timestamp(col("updated_at_str"), "yyyy-MM-dd HH:mm:ss"))

# row_number() OVER (PARTITION BY user_id ORDER BY updated_at DESC)
# Row 1 = most recent version of each user_id.
dedup_win = Window.partitionBy("user_id").orderBy(col("updated_at").desc())

df_deduped = df_users \
    .withColumn("rn", row_number().over(dedup_win)) \
    .filter(col("rn") == 1) \
    .drop("rn", "updated_at_str")

print("=== Example 4: Deduplication ===")
df_deduped.show()

# WHY row_number over distinct/dropDuplicates?
#   distinct() removes rows with identical ALL columns (doesn't help here).
#   dropDuplicates(["user_id"]) keeps an arbitrary row (non-deterministic).
#   row_number() is deterministic and lets you control which row to keep.

# ─────────────────────────────────────────────────────────────
# EXAMPLE 5: Session Detection from Clickstream Events
# ─────────────────────────────────────────────────────────────

# A session = continuous sequence of events with < 30 min idle gap.
# Approach:
#   1. Order events by user + time.
#   2. Compute time gap from previous event (via lag).
#   3. Mark gap > 30 min as session boundary (new_session_flag = 1/0).
#   4. Cumulative sum of flags = session ID (increments at each boundary).

SESSION_GAP_SECONDS = 30 * 60  # 30 minutes in seconds

click_data = [
    (1, "2024-01-01 09:00:00"), (1, "2024-01-01 09:05:00"),
    (1, "2024-01-01 09:10:00"), (1, "2024-01-01 10:00:00"),  # 50 min gap → new session
    (1, "2024-01-01 10:05:00"), (2, "2024-01-01 08:00:00"),
    (2, "2024-01-01 08:20:00"), (2, "2024-01-01 09:00:00"),  # 40 min gap → new session
]
df_clicks = spark.createDataFrame(click_data, ["user_id", "event_time_str"]) \
    .withColumn("event_time", to_timestamp(col("event_time_str"), "yyyy-MM-dd HH:mm:ss")) \
    .withColumn("epoch",      unix_timestamp(col("event_time"))) \
    .drop("event_time_str")

click_win = Window.partitionBy("user_id").orderBy("event_time")

df_sessions = df_clicks \
    .withColumn("prev_epoch",  lag("epoch", 1, None).over(click_win)) \
    .withColumn("gap_seconds", col("epoch") - col("prev_epoch")) \
    .withColumn(
        "is_new_session",
        # NULL previous epoch = first event for this user = new session (1).
        # Gap > threshold = new session (1). Otherwise same session (0).
        when(col("prev_epoch").isNull(), 1)
        .when(col("gap_seconds") > SESSION_GAP_SECONDS, 1)
        .otherwise(0)
    ) \
    .withColumn(
        "session_id",
        # Cumulative sum of is_new_session = monotonically increasing session counter.
        # Starts at 1 for each user (because first event always sets is_new_session=1).
        spark_sum("is_new_session").over(
            Window.partitionBy("user_id")
                  .orderBy("event_time")
                  .rowsBetween(UNBOUNDED_PREC, CURRENT_ROW)
        )
    ) \
    .withColumn("session_key", col("user_id") * 1000 + col("session_id"))

print("=== Example 5: Session Detection ===")
df_sessions.select("user_id", "event_time", "gap_seconds", "is_new_session", "session_id").show(15)

# ─────────────────────────────────────────────────────────────
# SECTION 6: PERFORMANCE CONSIDERATIONS
# ─────────────────────────────────────────────────────────────

# Window functions ALWAYS require a shuffle (unless partitionBy columns
# match the existing data distribution).
#
# Shuffle key = partitionBy columns.
# All rows with the same partition key must arrive at the same executor.
#
# HIGH CARDINALITY partitionBy = good:
#   partitionBy("user_id") — millions of users, manageable per-partition size.
#
# LOW CARDINALITY partitionBy = BAD (skew):
#   partitionBy("country") — only 50 countries, all US traffic → 1 executor.
#   partitionBy("gender")  — only M/F, half the dataset on each executor.
#
# SOLUTIONS for skew:
#   1. Add a high-cardinality secondary key: partitionBy("country", "user_id").
#   2. Salt: add a random bucket column and partitionBy both.
#
# OPTIMIZATION TIP:
#   Cache the DataFrame before computing multiple window functions.
#   Each .withColumn(...over(window)) may trigger a shuffle.
#   If you have 5 windows on the same spec, cache the base DF first.

# spark.stop()  # uncomment when running as a standalone script
