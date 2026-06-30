-- ============================================================
-- L03: Aggregations and Grouping
-- ============================================================
-- WHAT: GROUP BY, HAVING, aggregate functions, NULL behavior
--       in aggregates, ROLLUP/CUBE/GROUPING SETS, FILTER
-- WHY:  Aggregations power every business metric: revenue,
--       retention, cohort analysis, funnel conversion.
--       Misunderstanding GROUP BY or HAVING causes wrong
--       numbers in dashboards and financial reports.
-- LEVEL: Foundations → Advanced
-- ============================================================

/*
CONCEPT OVERVIEW:
Aggregation collapses multiple rows into one, applying a
function (SUM, COUNT, AVG, etc.) across the group.

SQL logical execution order (critical to understand):
  1. FROM     -- identify tables
  2. JOIN     -- combine tables
  3. WHERE    -- filter individual rows
  4. GROUP BY -- form groups
  5. HAVING   -- filter groups
  6. SELECT   -- compute output columns
  7. ORDER BY -- sort
  8. LIMIT    -- cap results

This order explains why WHERE cannot reference aggregate
results (aggregation hasn't happened yet) and why ORDER BY
can reference SELECT aliases (it happens after SELECT).

PRODUCTION USE CASE:
- Daily revenue dashboards
- User cohort analysis (retention curves)
- Funnel conversion rates
- Inventory reorder alerts (MIN stock by warehouse)

COMMON MISTAKES:
1. Putting aggregate filter in WHERE instead of HAVING
2. Confusing COUNT(*) vs COUNT(col) — NULL behavior differs
3. Not understanding NULL propagation in SUM/AVG
4. SELECT columns not in GROUP BY (causes error or wrong results)
5. GROUP BY before filtering (HAVING instead of WHERE)
*/


-- ============================================================
-- SECTION 1: GROUP BY AND HAVING
-- ============================================================

-- GROUP BY collapses rows sharing the same value(s) into one.
-- Every column in SELECT must either be:
--   (a) listed in GROUP BY, or
--   (b) wrapped in an aggregate function.
-- Violating this is a logical error (PostgreSQL enforces it).

-- Orders per user:
SELECT
    user_id,
    COUNT(*)         AS total_orders,
    SUM(amount)      AS total_revenue,
    AVG(amount)      AS avg_order_value,
    MIN(created_at)  AS first_order,
    MAX(created_at)  AS latest_order
FROM orders
WHERE status != 'cancelled'          -- WHERE filters BEFORE grouping
GROUP BY user_id
ORDER BY total_revenue DESC;


-- HAVING: filter on aggregate results AFTER grouping.
-- WHERE happens before aggregation; HAVING happens after.
-- This is the most important distinction in aggregation.

-- Find high-value customers (>= 5 orders AND > $1000 total):
SELECT
    user_id,
    COUNT(*)    AS order_count,
    SUM(amount) AS lifetime_value
FROM orders
WHERE status = 'completed'           -- row-level filter: only completed orders
GROUP BY user_id
HAVING COUNT(*) >= 5                 -- group-level filter: at least 5 orders
   AND SUM(amount) > 1000            -- group-level filter: LTV > $1000
ORDER BY lifetime_value DESC;

-- Why not WHERE here? Because at the WHERE stage, individual rows
-- haven't been grouped yet — there's no such thing as "count of group"
-- at that point. WHERE sees individual rows; HAVING sees groups.

-- Incorrect (would fail or give wrong results):
-- WHERE COUNT(*) >= 5    -- ERROR: aggregate function in WHERE
-- WHERE SUM(amount) > 1000  -- ERROR: same reason

-- Performance tip: always filter with WHERE first (reduces rows
-- before grouping), then filter groups with HAVING.
-- A large WHERE clause dramatically reduces the work for GROUP BY.


-- ============================================================
-- SECTION 2: COUNT VARIANTS — CRITICAL DIFFERENCES
-- ============================================================

/*
COUNT(*):           counts ALL rows including NULLs — counts the row itself
COUNT(column):      counts non-NULL values in that column
COUNT(DISTINCT col): counts unique non-NULL values

These give very different results. Wrong choice = wrong metrics.
*/

-- Demonstration with orders table:
SELECT
    COUNT(*)                    AS total_rows,        -- every row
    COUNT(user_id)              AS rows_with_user,    -- excludes NULL user_id
    COUNT(DISTINCT user_id)     AS unique_users,      -- unique users who ordered
    COUNT(promo_code)           AS orders_with_promo, -- excludes NULL promo_code
    COUNT(DISTINCT promo_code)  AS unique_promos_used -- unique promo codes
FROM orders;

-- Real metric: daily active users (unique users who did anything that day)
SELECT
    DATE_TRUNC('day', created_at) AS activity_date,
    COUNT(DISTINCT user_id)        AS daily_active_users
FROM user_events
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY DATE_TRUNC('day', created_at)
ORDER BY activity_date;


-- ============================================================
-- SECTION 3: NULL BEHAVIOR IN AGGREGATES
-- ============================================================

/*
All aggregate functions IGNORE NULL values (except COUNT(*)).

  SUM(col)  — sums non-NULL values; returns NULL if ALL are NULL
  AVG(col)  — averages non-NULL values; this can be misleading!
  MIN/MAX   — ignores NULLs
  COUNT(col)— ignores NULLs

AVG pitfall: if 8 out of 10 rows have NULL for a discount column,
AVG(discount) averages only the 2 non-NULL rows.
This is often NOT what you want — you may want to treat NULL as 0.
*/

SELECT
    COUNT(*)               AS total_orders,
    COUNT(discount)        AS orders_with_discount,
    AVG(discount)          AS avg_discount_among_discounted,  -- ignores NULLs
    AVG(COALESCE(discount, 0)) AS avg_discount_all_orders     -- NULL=0
FROM orders;

-- Safe SUM with NULL handling:
SELECT
    user_id,
    SUM(COALESCE(refund_amount, 0)) AS total_refunds
    -- Without COALESCE: if all refund_amounts are NULL, SUM returns NULL
    -- With COALESCE: NULL becomes 0, SUM returns 0 (often more useful)
FROM orders
GROUP BY user_id;


-- ============================================================
-- SECTION 4: SUM, AVG, MIN, MAX, STDDEV
-- ============================================================

-- Revenue statistics per product category:
SELECT
    p.category,
    COUNT(oi.item_id)            AS items_sold,
    SUM(oi.quantity)             AS units_sold,
    SUM(oi.quantity * oi.unit_price) AS gross_revenue,
    AVG(oi.unit_price)           AS avg_unit_price,
    MIN(oi.unit_price)           AS min_price,
    MAX(oi.unit_price)           AS max_price,
    STDDEV(oi.unit_price)        AS price_stddev,    -- how much prices vary
    VARIANCE(oi.unit_price)      AS price_variance
FROM order_items oi
JOIN products    p ON oi.product_id = p.product_id
JOIN orders      o ON oi.order_id   = o.order_id
WHERE o.status = 'completed'
GROUP BY p.category
ORDER BY gross_revenue DESC;


-- ============================================================
-- SECTION 5: ROLLUP, CUBE, GROUPING SETS
-- ============================================================

/*
These are extensions to GROUP BY that generate multiple levels
of aggregation in a single query — avoiding multiple UNION ALLs.

ROLLUP: generates subtotals and a grand total for a hierarchy.
  GROUP BY ROLLUP(a, b) generates groupings:
    (a, b) — finest grain
    (a)    — subtotal per a
    ()     — grand total

CUBE: generates all possible grouping combinations.
  GROUP BY CUBE(a, b) generates:
    (a, b), (a), (b), ()

GROUPING SETS: manually specify exactly which groupings you want.
  More flexible than ROLLUP or CUBE.

These are invaluable for financial reports and pivot tables.
*/

-- Revenue summary with ROLLUP: region → category → total
SELECT
    region,
    category,
    SUM(revenue)  AS total_revenue,
    GROUPING(region)   AS is_region_total,   -- 1 if this row is a region subtotal
    GROUPING(category) AS is_category_total  -- 1 if this row is a category subtotal
FROM sales_summary
GROUP BY ROLLUP(region, category)
ORDER BY region NULLS LAST, category NULLS LAST;

/*
Result example:
region      category    total_revenue   is_region_total  is_category_total
North       Electronics   50000         0                0
North       Clothing      20000         0                0
North       NULL          70000         0                1    <- region subtotal
South       Electronics   40000         0                0
South       NULL          40000         0                1    <- region subtotal
NULL        NULL         110000         1                1    <- grand total
*/

-- CUBE: all combinations of region, category, and year
SELECT
    region,
    category,
    EXTRACT(YEAR FROM sale_date) AS year,
    SUM(revenue) AS total_revenue
FROM sales
GROUP BY CUBE(region, category, EXTRACT(YEAR FROM sale_date))
ORDER BY region NULLS LAST, category NULLS LAST, year NULLS LAST;

-- GROUPING SETS: manually choose the groupings you need
-- More efficient than CUBE when you don't want all combinations
SELECT
    channel,
    DATE_TRUNC('month', created_at) AS month,
    COUNT(order_id)  AS orders,
    SUM(amount)      AS revenue
FROM orders
GROUP BY GROUPING SETS (
    (channel, DATE_TRUNC('month', created_at)),  -- by channel + month
    (channel),                                    -- by channel total
    (DATE_TRUNC('month', created_at)),            -- by month total
    ()                                            -- grand total
)
ORDER BY channel NULLS LAST, month NULLS LAST;


-- ============================================================
-- SECTION 6: FILTER CLAUSE ON AGGREGATES
-- ============================================================

/*
FILTER (WHERE ...) applies a condition to a specific aggregate
function, allowing multiple conditional aggregations in one pass.

This is far more efficient than multiple subqueries or CASE
statements — the engine makes a single pass over the data.
*/

-- Pivot-style report: orders broken down by status in one query
SELECT
    DATE_TRUNC('month', created_at)             AS month,
    COUNT(*)                                     AS total_orders,
    COUNT(*) FILTER (WHERE status = 'completed') AS completed_orders,
    COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled_orders,
    COUNT(*) FILTER (WHERE status = 'pending')   AS pending_orders,
    SUM(amount) FILTER (WHERE status = 'completed') AS completed_revenue,
    AVG(amount) FILTER (WHERE status = 'completed') AS avg_completed_value
FROM orders
GROUP BY DATE_TRUNC('month', created_at)
ORDER BY month;

-- Alternative (slower, less readable) using CASE:
-- SUM(CASE WHEN status = 'completed' THEN amount ELSE 0 END)
-- Both work, but FILTER is the SQL standard and more readable.


-- ============================================================
-- SECTION 7: REAL-WORLD EXAMPLES
-- ============================================================

-- Daily revenue report with day-over-day context:
SELECT
    date_day,
    daily_revenue,
    LAG(daily_revenue) OVER (ORDER BY date_day) AS prev_day_revenue,
    daily_revenue - LAG(daily_revenue) OVER (ORDER BY date_day) AS day_delta
FROM (
    SELECT
        DATE_TRUNC('day', created_at) AS date_day,
        SUM(amount)                    AS daily_revenue
    FROM orders
    WHERE status = 'completed'
      AND created_at >= NOW() - INTERVAL '30 days'
    GROUP BY DATE_TRUNC('day', created_at)
) daily_totals
ORDER BY date_day;


-- User cohort analysis: revenue by signup month and order month
-- This is the foundation of cohort retention analysis.
SELECT
    DATE_TRUNC('month', u.created_at)         AS cohort_month,
    DATE_TRUNC('month', o.created_at)         AS order_month,
    COUNT(DISTINCT u.user_id)                  AS active_users,
    SUM(o.amount)                              AS cohort_revenue,
    AVG(o.amount)                              AS avg_order_value
FROM users   u
JOIN orders  o ON u.user_id = o.user_id
WHERE o.status = 'completed'
GROUP BY
    DATE_TRUNC('month', u.created_at),
    DATE_TRUNC('month', o.created_at)
ORDER BY cohort_month, order_month;


-- Funnel analysis: conversion rates between signup steps
SELECT
    COUNT(*)                              FILTER (WHERE step_started    ) AS started,
    COUNT(*)                              FILTER (WHERE email_verified  ) AS email_verified,
    COUNT(*)                              FILTER (WHERE profile_complete) AS profile_complete,
    COUNT(*)                              FILTER (WHERE first_payment   ) AS converted,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE first_payment)
              / NULLIF(COUNT(*), 0),
        2
    ) AS overall_conversion_pct
FROM user_funnel_states
WHERE created_at >= NOW() - INTERVAL '90 days';


-- ABC analysis: classify products by revenue contribution
-- A-class: top 20% of products by revenue (typically 80% of revenue)
-- B-class: next 30%
-- C-class: bottom 50%
WITH product_revenue AS (
    SELECT
        p.product_id,
        p.name,
        SUM(oi.quantity * oi.unit_price) AS total_revenue
    FROM products    p
    JOIN order_items oi ON p.product_id = oi.product_id
    JOIN orders      o  ON oi.order_id  = o.order_id
    WHERE o.status = 'completed'
    GROUP BY p.product_id, p.name
),
ranked AS (
    SELECT *,
        PERCENT_RANK() OVER (ORDER BY total_revenue DESC) AS pct_rank
    FROM product_revenue
)
SELECT
    product_id,
    name,
    total_revenue,
    CASE
        WHEN pct_rank <= 0.20 THEN 'A - Top 20%'
        WHEN pct_rank <= 0.50 THEN 'B - Mid 30%'
        ELSE                       'C - Bottom 50%'
    END AS abc_class
FROM ranked
ORDER BY total_revenue DESC;

-- ============================================================
-- END OF L03
-- ============================================================
