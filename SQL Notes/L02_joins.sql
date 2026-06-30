-- ============================================================
-- L02: JOINs — Combining Relations
-- ============================================================
-- WHAT: INNER, LEFT, RIGHT, FULL OUTER, CROSS, SELF JOINs.
--       ON vs USING, multi-condition joins, non-equi joins,
--       join performance, anti-patterns.
-- WHY:  JOINs are the core of relational algebra. A wrong JOIN
--       type silently drops rows or creates phantom rows,
--       producing incorrect reports without any error message.
-- LEVEL: Foundations → Advanced
-- ============================================================

/*
CONCEPT OVERVIEW:
A JOIN combines rows from two or more tables based on a
related column. The database engine implements joins using
one of three physical strategies:
  1. Nested Loop Join  — good for small tables or indexed lookups
  2. Hash Join         — good for large unsorted tables
  3. Merge Join        — good when both sides are pre-sorted

The query planner chooses automatically based on statistics.
Understanding join types (logical) is separate from join
algorithms (physical execution).

PRODUCTION USE CASE:
Every non-trivial report joins multiple tables. A billing
report might join: users → subscriptions → invoices →
line_items → products. Each join type decision changes
whether cancelled users appear in the report.

COMMON MISTAKES:
1. Using LEFT JOIN when INNER JOIN is intended (keeps NULLs unexpectedly)
2. JOIN condition on non-indexed columns (triggers full scans)
3. Implicit comma joins (FROM a, b WHERE a.id = b.id) — unmaintainable
4. Cartesian product from missing ON clause
5. Multiple LEFT JOINs multiplying rows (fanout problem)
*/

-- ============================================================
-- REFERENCE TABLES (used throughout this lesson)
-- ============================================================

/*
users            orders              products           order_items
-----------      -----------         -----------        -----------
user_id (PK)     order_id (PK)       product_id (PK)    item_id (PK)
email            user_id (FK)        name               order_id (FK)
name             status              price              product_id (FK)
plan_type        created_at          category           quantity
                                                        unit_price
*/


-- ============================================================
-- SECTION 1: INNER JOIN
-- ============================================================

/*
INNER JOIN returns ONLY rows that have a match in BOTH tables.
Rows without a match on either side are EXCLUDED.

Venn diagram:
  [Users] ∩ [Orders]
  Only users who have at least one order appear.

Use when: you want only rows with a corresponding record
on both sides. The most common join type.
*/

-- Find all orders with their user's email:
SELECT
    o.order_id,
    u.email,
    o.amount,
    o.status,
    o.created_at
FROM orders      o
INNER JOIN users u ON o.user_id = u.user_id
-- INNER is optional — JOIN alone defaults to INNER JOIN
WHERE o.status = 'completed';

-- Multi-table INNER JOIN: orders with line items and product names
SELECT
    o.order_id,
    u.email,
    p.name            AS product_name,
    oi.quantity,
    oi.unit_price,
    oi.quantity * oi.unit_price AS line_total
FROM orders      o
JOIN users       u  ON o.user_id    = u.user_id
JOIN order_items oi ON oi.order_id  = o.order_id
JOIN products    p  ON oi.product_id = p.product_id
WHERE o.created_at >= '2024-01-01';


-- ============================================================
-- SECTION 2: LEFT JOIN (LEFT OUTER JOIN)
-- ============================================================

/*
LEFT JOIN returns ALL rows from the LEFT table, plus matched
rows from the RIGHT table. Where no match exists, right-side
columns are NULL.

Venn diagram:
  [Users] — all users, with order data where it exists

Use when: you want to keep all records from the primary table
regardless of whether a related record exists.

Critical: After a LEFT JOIN, filter on the right table's columns
ONLY in the ON clause, not the WHERE clause. Filtering NULL
values in WHERE turns a LEFT JOIN into an INNER JOIN!
*/

-- All users and their order count (including users with 0 orders):
SELECT
    u.user_id,
    u.email,
    u.plan_type,
    COUNT(o.order_id) AS total_orders,  -- COUNT on right-side column: NULLs not counted
    COALESCE(SUM(o.amount), 0) AS total_spent
FROM users  u
LEFT JOIN orders o ON u.user_id = o.user_id
GROUP BY u.user_id, u.email, u.plan_type
ORDER BY total_spent DESC;

-- WRONG: This WHERE clause converts the LEFT JOIN to INNER JOIN
-- because NULL != 'completed', so users with no orders are excluded
-- FROM users u
-- LEFT JOIN orders o ON u.user_id = o.user_id
-- WHERE o.status = 'completed'   <-- BUG: excludes NULL rows

-- CORRECT: Push the filter into the ON clause to keep all users
SELECT
    u.user_id,
    u.email,
    COUNT(o.order_id) AS completed_orders
FROM users  u
LEFT JOIN orders o
    ON u.user_id = o.user_id
    AND o.status = 'completed'     -- filter applied during join, not after
GROUP BY u.user_id, u.email;

-- Anti-pattern detection: find users with NO orders (anti-join pattern)
SELECT u.user_id, u.email, u.created_at
FROM users  u
LEFT JOIN orders o ON u.user_id = o.user_id
WHERE o.order_id IS NULL   -- NULL on right side = no match = no orders
ORDER BY u.created_at DESC;


-- ============================================================
-- SECTION 3: RIGHT JOIN (RIGHT OUTER JOIN)
-- ============================================================

/*
RIGHT JOIN is the mirror of LEFT JOIN — keeps ALL rows from
the RIGHT table. Rarely used in practice because you can
always rewrite a RIGHT JOIN as a LEFT JOIN by swapping tables.
Most style guides prefer LEFT JOIN for consistency.

Use LEFT JOIN with tables swapped instead of RIGHT JOIN.
*/

-- This RIGHT JOIN:
SELECT u.email, o.order_id, o.amount
FROM orders o
RIGHT JOIN users u ON o.user_id = u.user_id;

-- Is identical to this LEFT JOIN:
SELECT u.email, o.order_id, o.amount
FROM users  u
LEFT JOIN orders o ON u.user_id = o.user_id;
-- Prefer the LEFT JOIN form — it reads naturally (primary table first).


-- ============================================================
-- SECTION 4: FULL OUTER JOIN
-- ============================================================

/*
FULL OUTER JOIN returns ALL rows from BOTH tables.
Where no match exists on either side, the other side is NULL.

Venn diagram:
  [Users] ∪ [Orders] — everything from both tables

Use when: reconciling two datasets and you need to see
unmatched records from both sides. Common in data quality,
migration validation, and ETL reconciliation.
*/

-- Reconcile expected payments vs received payments:
SELECT
    COALESCE(expected.invoice_id, received.invoice_id) AS invoice_id,
    expected.amount   AS expected_amount,
    received.amount   AS received_amount,
    CASE
        WHEN expected.invoice_id IS NULL THEN 'UNEXPECTED PAYMENT'
        WHEN received.invoice_id IS NULL THEN 'MISSING PAYMENT'
        WHEN expected.amount != received.amount THEN 'AMOUNT MISMATCH'
        ELSE 'OK'
    END AS reconciliation_status
FROM expected_payments  expected
FULL OUTER JOIN received_payments received
    ON expected.invoice_id = received.invoice_id
WHERE expected.invoice_id IS NULL
   OR received.invoice_id IS NULL
   OR expected.amount != received.amount;


-- ============================================================
-- SECTION 5: CROSS JOIN
-- ============================================================

/*
CROSS JOIN produces the Cartesian product — every row in
table A paired with every row in table B.
Result rows = |A| * |B|

10 rows × 10 rows = 100 rows
1000 rows × 1000 rows = 1,000,000 rows

Use intentionally for: generating combinations, test data,
calendar scaffolding. NEVER accidentally.
*/

-- Generate a grid of all sizes × colors for a product catalog:
SELECT
    s.size_name,
    c.color_name,
    s.size_name || '-' || c.color_name AS variant_sku
FROM product_sizes  s
CROSS JOIN product_colors c
ORDER BY s.size_name, c.color_name;

-- Generate a date scaffold for a report (all days in a month):
SELECT
    generate_series(
        DATE_TRUNC('month', NOW()),
        DATE_TRUNC('month', NOW()) + INTERVAL '1 month' - INTERVAL '1 day',
        INTERVAL '1 day'
    )::DATE AS report_date;

-- Accidental Cartesian product (DANGER — missing join condition):
-- SELECT * FROM users, orders;  -- returns users * orders rows!
-- This is the implicit join anti-pattern.


-- ============================================================
-- SECTION 6: SELF JOIN
-- ============================================================

/*
A self join joins a table to itself. Requires aliases.
Classic use cases:
  - Org chart: employee → manager (both in employees table)
  - Friend/follower relationships
  - Comparing rows within the same table
*/

-- Org chart: show each employee with their manager's name
SELECT
    e.employee_id,
    e.name          AS employee_name,
    e.title         AS employee_title,
    m.name          AS manager_name,
    m.title         AS manager_title
FROM employees e
LEFT JOIN employees m ON e.manager_id = m.employee_id
-- LEFT JOIN because the CEO has no manager (manager_id IS NULL)
ORDER BY m.name NULLS LAST, e.name;

-- Find pairs of products in the same category (self-join for combinations):
SELECT
    a.product_id AS product_a_id,
    a.name       AS product_a,
    b.product_id AS product_b_id,
    b.name       AS product_b
FROM products a
JOIN products b
    ON a.category = b.category
    AND a.product_id < b.product_id  -- prevents (A,B) and (B,A) duplicates
                                     -- and (A,A) self-pairs
ORDER BY a.category, a.name;


-- ============================================================
-- SECTION 7: ON vs USING
-- ============================================================

-- ON: explicit join condition, works for any column names
SELECT u.email, o.order_id
FROM users u
JOIN orders o ON u.user_id = o.user_id;

-- USING: shorthand when both tables have the same column name
-- Produces a single column in output (not duplicated)
SELECT email, order_id
FROM users
JOIN orders USING (user_id);   -- both tables must have 'user_id'
-- USING is cleaner but less flexible.
-- Use ON when column names differ or for complex conditions.


-- ============================================================
-- SECTION 8: MULTIPLE JOIN CONDITIONS
-- ============================================================

-- Join on multiple columns (composite key matching):
SELECT *
FROM order_items oi
JOIN inventory inv
    ON oi.product_id  = inv.product_id
    AND oi.warehouse_id = inv.warehouse_id;  -- composite FK

-- Range-based join condition (non-equi join):
-- Match transactions to the pricing tier that was active at the time
SELECT
    t.transaction_id,
    t.amount,
    pt.tier_name,
    pt.commission_rate
FROM transactions  t
JOIN pricing_tiers pt
    ON t.created_at BETWEEN pt.valid_from AND pt.valid_to
    AND t.amount    BETWEEN pt.min_amount  AND pt.max_amount;


-- ============================================================
-- SECTION 9: JOIN PERFORMANCE
-- ============================================================

/*
JOIN performance rules:

1. Index join columns:
   - The ON clause columns should be indexed on both tables.
   - For FK relationships: always index the FK column.
   - PK columns are automatically indexed.

2. Join order matters less than you think:
   - The planner reorders joins automatically (up to join_collapse_limit).
   - For > 8 tables, planner may use a suboptimal order.

3. Filter early:
   - Apply WHERE conditions before joining when possible.
   - Use CTEs or subqueries to pre-filter large tables.

4. Avoid functions on join columns:
   - ON LOWER(a.email) = LOWER(b.email)  -- can't use index on a.email
   - Solution: normalize data at write time (store lowercase).

5. Beware row multiplication:
   - If the right-side table has multiple matching rows,
     the left-side row is duplicated in output.
   - This silently inflates SUM() aggregations.
*/

-- Checking an index exists for join column:
-- \d orders   -- shows indexes in psql
-- SELECT * FROM pg_indexes WHERE tablename = 'orders';

-- Create index on FK column (if missing):
-- CREATE INDEX idx_orders_user_id ON orders (user_id);
-- CREATE INDEX idx_order_items_order_id ON order_items (order_id);

-- EXPLAIN ANALYZE to see join strategy chosen:
EXPLAIN ANALYZE
SELECT u.email, COUNT(o.order_id) AS order_count
FROM users  u
JOIN orders o ON u.user_id = o.user_id
GROUP BY u.email;
/*
Sample output:
  HashAggregate (cost=1240.00..1265.00 rows=2500 ...)
    -> Hash Join (cost=45.00..1190.00 rows=10000 ...)
          Hash Cond: (o.user_id = u.user_id)
          -> Seq Scan on orders ...
          -> Hash
               -> Seq Scan on users ...

If you see Nested Loop on large tables, you likely have
a missing index. Hash Join is normal for large tables.
Merge Join appears when both sides are indexed on the join key.
*/


-- ============================================================
-- SECTION 10: ANTI-PATTERNS
-- ============================================================

-- ANTI-PATTERN 1: Implicit comma join (old SQL-89 style)
-- Never write this — it's a Cartesian product with a filter.
-- FROM users u, orders o WHERE u.user_id = o.user_id
-- This is identical to INNER JOIN but much harder to read,
-- and a missing WHERE clause creates a silent Cartesian product.

-- ANTI-PATTERN 2: Joining on non-indexed columns
-- This works but forces a full table scan on the right table:
-- JOIN orders o ON o.customer_email = u.email
-- Fix: add index, or better, join on integer IDs.

-- ANTI-PATTERN 3: Row multiplication trap
-- If one user has 5 orders and 3 payments, joining both:
-- users → orders → payments can produce 5 * 3 = 15 rows per user.
-- SUM(order.amount) would then be 3x inflated.
-- Fix: aggregate before joining, or use DISTINCT.

-- Safe pattern — aggregate first, then join:
WITH user_order_totals AS (
    SELECT user_id, SUM(amount) AS total_orders
    FROM orders
    GROUP BY user_id
),
user_payment_totals AS (
    SELECT user_id, SUM(amount) AS total_payments
    FROM payments
    GROUP BY user_id
)
SELECT
    u.user_id,
    u.email,
    COALESCE(ot.total_orders,   0) AS total_orders,
    COALESCE(pt.total_payments, 0) AS total_payments
FROM users              u
LEFT JOIN user_order_totals   ot ON u.user_id = ot.user_id
LEFT JOIN user_payment_totals pt ON u.user_id = pt.user_id;

-- ============================================================
-- END OF L02
-- ============================================================
