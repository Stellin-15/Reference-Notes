-- ============================================================
-- L04: Window Functions
-- ============================================================
-- WHAT: ROW_NUMBER, RANK, DENSE_RANK, NTILE, LAG, LEAD,
--       FIRST_VALUE, LAST_VALUE, SUM/AVG OVER, PARTITION BY,
--       ROWS vs RANGE frame clause, named WINDOW clause.
-- WHY:  Window functions compute analytics without collapsing
--       rows. They unlock running totals, moving averages,
--       ranking, deduplication, and session detection in pure
--       SQL — no application-side loops needed.
-- LEVEL: Advanced
-- ============================================================

/*
CONCEPT OVERVIEW:
A window function operates across a "window" of rows related
to the current row, returning a value for EACH row (unlike
GROUP BY which collapses rows into one).

Syntax:
  function_name() OVER (
      PARTITION BY column       -- divide into groups (like GROUP BY)
      ORDER BY    column        -- define row order within partition
      ROWS/RANGE  frame_clause  -- which rows are "in the window"
  )

Key insight: the result set still has the same number of rows.
Window functions ADD a column; GROUP BY REDUCES rows.

Execution order: window functions execute AFTER WHERE, GROUP BY,
and HAVING — they operate on the result set before ORDER BY and LIMIT.

PRODUCTION USE CASE:
- Running totals for financial statements
- Moving averages for trend smoothing
- Percentile ranking of customers by LTV
- Deduplication of event streams
- Session detection in clickstream data

COMMON MISTAKES:
1. Confusing PARTITION BY (window) with GROUP BY (aggregation)
2. Using LAST_VALUE without proper frame clause (silent bug)
3. Expecting ORDER BY inside OVER to sort final output
4. Forgetting that window functions run after WHERE/GROUP BY
*/


-- ============================================================
-- SECTION 1: PARTITION BY vs GROUP BY
-- ============================================================

/*
GROUP BY: collapses multiple rows into ONE row per group.
PARTITION BY: keeps ALL rows, adds a column with the group's value.

GROUP BY:
  user_id | total_spent
  1       | 500
  2       | 200

PARTITION BY (window function):
  user_id | order_id | amount | total_spent_by_user
  1       | 101      | 300    | 500           <- same row, group total added
  1       | 102      | 200    | 500           <- same row, group total added
  2       | 103      | 200    | 200           <- same row, group total added
*/

-- GROUP BY example (collapses rows):
SELECT user_id, SUM(amount) AS total_spent
FROM orders
GROUP BY user_id;

-- Equivalent with window function (keeps all rows):
SELECT
    order_id,
    user_id,
    amount,
    SUM(amount) OVER (PARTITION BY user_id) AS user_total_spent,
    -- Shows each order next to the user's total — not possible with GROUP BY
    amount / SUM(amount) OVER (PARTITION BY user_id) AS pct_of_user_total
FROM orders;


-- ============================================================
-- SECTION 2: RANKING FUNCTIONS
-- ============================================================

/*
ROW_NUMBER():   unique sequential number, no ties (1, 2, 3, 4)
RANK():         ties get same rank, next rank skips (1, 2, 2, 4)
DENSE_RANK():   ties get same rank, next rank does NOT skip (1, 2, 2, 3)
NTILE(n):       divides rows into n roughly equal buckets (1..n)

Choose based on how you want to handle ties.
*/

-- Rank orders by amount for each user:
SELECT
    user_id,
    order_id,
    amount,
    ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY amount DESC) AS row_num,
    RANK()       OVER (PARTITION BY user_id ORDER BY amount DESC) AS rank,
    DENSE_RANK() OVER (PARTITION BY user_id ORDER BY amount DESC) AS dense_rank
FROM orders;

/*
Example output (user_id=1 has two orders of $100):
user_id | order_id | amount | row_num | rank | dense_rank
1       | 101      | 300    | 1       | 1    | 1
1       | 102      | 100    | 2       | 2    | 2
1       | 103      | 100    | 3       | 2    | 2    <- tie: rank=2, row_num=3
1       | 104      | 50     | 4       | 4    | 3    <- rank skips to 4, dense stays at 3
*/

-- Deduplication: keep only the most recent order per user
-- ROW_NUMBER() is the correct tool — RANK/DENSE_RANK can keep ties
SELECT *
FROM (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY user_id
            ORDER BY created_at DESC
        ) AS rn
    FROM orders
) ranked
WHERE rn = 1;   -- only the latest order per user

-- NTILE: divide customers into quartiles by lifetime value
SELECT
    user_id,
    lifetime_value,
    NTILE(4) OVER (ORDER BY lifetime_value DESC) AS quartile
    -- Quartile 1 = top 25% by LTV (highest value customers)
FROM customer_ltv;


-- ============================================================
-- SECTION 3: LAG AND LEAD
-- ============================================================

/*
LAG(col, offset, default):  access a previous row's value
LEAD(col, offset, default): access a next row's value

Both require ORDER BY in the OVER clause to define "previous/next."
Both accept an optional offset (default 1) and a default value
for when the lag/lead goes beyond the partition boundary.

Use for: period-over-period comparisons, detecting changes,
computing deltas between consecutive events.
*/

-- Month-over-month revenue comparison:
SELECT
    revenue_month,
    monthly_revenue,
    LAG(monthly_revenue, 1, 0) OVER (ORDER BY revenue_month) AS prev_month_revenue,
    monthly_revenue - LAG(monthly_revenue) OVER (ORDER BY revenue_month) AS mom_delta,
    ROUND(
        100.0 * (monthly_revenue - LAG(monthly_revenue) OVER (ORDER BY revenue_month))
              / NULLIF(LAG(monthly_revenue) OVER (ORDER BY revenue_month), 0),
        2
    ) AS mom_pct_change
FROM monthly_revenue_rollup
ORDER BY revenue_month;

-- Session detection: identify sessions from clickstream events.
-- A new session starts if the gap since the previous event > 30 minutes.
SELECT
    user_id,
    event_time,
    prev_event_time,
    event_time - prev_event_time AS gap,
    CASE
        WHEN prev_event_time IS NULL
          OR event_time - prev_event_time > INTERVAL '30 minutes'
        THEN 1
        ELSE 0
    END AS is_session_start
FROM (
    SELECT
        user_id,
        event_time,
        LAG(event_time) OVER (
            PARTITION BY user_id
            ORDER BY event_time
        ) AS prev_event_time
    FROM clickstream_events
) lagged;

-- Assign session IDs by cumulative sum of session starts:
SELECT
    user_id,
    event_time,
    SUM(is_session_start) OVER (
        PARTITION BY user_id
        ORDER BY event_time
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS session_id
FROM (
    -- previous subquery result
    SELECT
        user_id,
        event_time,
        CASE
            WHEN LAG(event_time) OVER (PARTITION BY user_id ORDER BY event_time) IS NULL
              OR event_time - LAG(event_time) OVER (PARTITION BY user_id ORDER BY event_time) > INTERVAL '30 minutes'
            THEN 1
            ELSE 0
        END AS is_session_start
    FROM clickstream_events
) session_starts;


-- ============================================================
-- SECTION 4: FIRST_VALUE AND LAST_VALUE
-- ============================================================

/*
FIRST_VALUE(col): value of col from the first row in the window frame
LAST_VALUE(col):  value of col from the last row in the window frame

CRITICAL BUG: The default frame for LAST_VALUE is:
  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
This means LAST_VALUE returns the CURRENT row's value by default,
not the last row of the partition!

Always specify the frame explicitly when using LAST_VALUE.
*/

-- First and last order dates per user — note the frame clause:
SELECT
    user_id,
    order_id,
    created_at,
    FIRST_VALUE(created_at) OVER (
        PARTITION BY user_id
        ORDER BY created_at
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    ) AS first_order_date,
    LAST_VALUE(created_at) OVER (
        PARTITION BY user_id
        ORDER BY created_at
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        -- Without this frame clause, LAST_VALUE = current row value (wrong!)
    ) AS last_order_date
FROM orders;

-- Often, MIN/MAX OVER is simpler and safer than FIRST/LAST VALUE:
SELECT
    user_id,
    order_id,
    created_at,
    MIN(created_at) OVER (PARTITION BY user_id) AS first_order_date,
    MAX(created_at) OVER (PARTITION BY user_id) AS last_order_date
FROM orders;


-- ============================================================
-- SECTION 5: RUNNING TOTALS AND MOVING AVERAGES
-- ============================================================

/*
The FRAME CLAUSE defines which rows are included in the window:

  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    -- all rows from partition start to current row (running total)

  ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    -- current row + previous 6 rows = 7-row window (7-day moving avg)

  ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    -- entire partition (same as no frame for SUM → partition total)

  RANGE vs ROWS:
    ROWS:  physical rows (based on position)
    RANGE: logical range (based on value — groups equal values together)
    ROWS is almost always what you want for moving averages.
*/

-- Running total of revenue (cumulative sum):
SELECT
    order_date,
    daily_revenue,
    SUM(daily_revenue) OVER (
        ORDER BY order_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_revenue
FROM daily_revenue;

-- 7-day moving average of daily revenue:
SELECT
    order_date,
    daily_revenue,
    AVG(daily_revenue) OVER (
        ORDER BY order_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW  -- current + 6 prior = 7 days
    ) AS moving_avg_7d,
    AVG(daily_revenue) OVER (
        ORDER BY order_date
        ROWS BETWEEN 29 PRECEDING AND CURRENT ROW -- 30-day moving average
    ) AS moving_avg_30d
FROM daily_revenue
ORDER BY order_date;

-- Running total partitioned by category (resets per category):
SELECT
    category,
    order_date,
    daily_revenue,
    SUM(daily_revenue) OVER (
        PARTITION BY category        -- separate running total per category
        ORDER BY order_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS category_cumulative_revenue
FROM daily_revenue_by_category;


-- ============================================================
-- SECTION 6: PERCENTILE AND DISTRIBUTION FUNCTIONS
-- ============================================================

-- PERCENT_RANK: relative rank as percentage (0 to 1)
-- CUME_DIST: cumulative distribution (fraction of rows <= current)
SELECT
    user_id,
    lifetime_value,
    PERCENT_RANK() OVER (ORDER BY lifetime_value)  AS percentile_rank,
    CUME_DIST()    OVER (ORDER BY lifetime_value)  AS cumulative_dist,
    NTILE(100)     OVER (ORDER BY lifetime_value)  AS percentile_bucket
FROM customer_ltv;

-- Ordered-set aggregate functions (distinct from window functions):
-- These compute percentiles as a single value per group.
SELECT
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY amount) AS median_order_value,
    PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY amount) AS p90_order_value,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY amount) AS p99_order_value,
    PERCENTILE_DISC(0.50) WITHIN GROUP (ORDER BY amount) AS median_discrete
    -- CONT: interpolates between values
    -- DISC: returns an actual value from the dataset
FROM orders
WHERE status = 'completed';


-- ============================================================
-- SECTION 7: NAMED WINDOW CLAUSE
-- ============================================================

/*
When you use the same OVER(...) specification multiple times,
define it once with WINDOW and reference it by name.
This avoids repetition and ensures consistency — changing the
window definition in one place updates all references.
*/

SELECT
    user_id,
    order_id,
    amount,
    created_at,
    SUM(amount)      OVER w AS running_total,
    AVG(amount)      OVER w AS running_avg,
    COUNT(*)         OVER w AS running_count,
    ROW_NUMBER()     OVER w AS row_num,
    LAG(amount)      OVER w AS prev_amount
FROM orders
WINDOW w AS (
    PARTITION BY user_id
    ORDER BY created_at
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
)
ORDER BY user_id, created_at;

-- Multiple named windows:
SELECT
    product_id,
    sale_date,
    daily_units,
    SUM(daily_units) OVER by_product      AS product_running_total,
    AVG(daily_units) OVER by_product_7d   AS product_7d_avg
FROM product_sales
WINDOW
    by_product    AS (PARTITION BY product_id ORDER BY sale_date
                      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW),
    by_product_7d AS (PARTITION BY product_id ORDER BY sale_date
                      ROWS BETWEEN 6 PRECEDING AND CURRENT ROW);


-- ============================================================
-- SECTION 8: REAL PRODUCTION EXAMPLES
-- ============================================================

-- Deduplication of CDC (Change Data Capture) events:
-- Keep only the latest version of each record.
SELECT *
FROM (
    SELECT
        record_id,
        payload,
        updated_at,
        ROW_NUMBER() OVER (
            PARTITION BY record_id
            ORDER BY updated_at DESC
        ) AS rn
    FROM cdc_events
) deduped
WHERE rn = 1;

-- Customer percentile ranking for marketing segmentation:
WITH customer_stats AS (
    SELECT
        user_id,
        COUNT(*)    AS order_count,
        SUM(amount) AS lifetime_value,
        MAX(created_at) AS last_order_date
    FROM orders
    WHERE status = 'completed'
    GROUP BY user_id
),
ranked AS (
    SELECT
        user_id,
        lifetime_value,
        order_count,
        last_order_date,
        NTILE(10) OVER (ORDER BY lifetime_value DESC)    AS ltv_decile,
        NTILE(10) OVER (ORDER BY order_count DESC)       AS frequency_decile,
        NTILE(10) OVER (ORDER BY last_order_date DESC)   AS recency_decile
    FROM customer_stats
)
SELECT
    user_id,
    lifetime_value,
    ltv_decile,
    frequency_decile,
    recency_decile,
    -- RFM score: Recency + Frequency + Monetary (LTV)
    recency_decile + frequency_decile + ltv_decile AS rfm_score
FROM ranked
ORDER BY rfm_score DESC;

-- ============================================================
-- END OF L04
-- ============================================================
