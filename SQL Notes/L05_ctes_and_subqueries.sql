-- ============================================================
-- L05: CTEs, Subqueries, and LATERAL Joins
-- ============================================================
-- WHAT: WITH clause (CTEs), recursive CTEs, correlated
--       subqueries, EXISTS vs IN vs JOIN, LATERAL joins,
--       materialization behavior.
-- WHY:  CTEs transform spaghetti queries into maintainable,
--       testable pipelines. Recursive CTEs solve graph and
--       hierarchy problems that loops require in application
--       code. Choosing the wrong approach (correlated subquery
--       vs JOIN) can make a query 1000x slower.
-- LEVEL: Advanced
-- ============================================================

/*
CONCEPT OVERVIEW:
A CTE (Common Table Expression) is a named, temporary result
set defined with the WITH clause, scoped to the query.

  WITH cte_name AS (
      SELECT ...
  )
  SELECT * FROM cte_name;

CTEs vs subqueries:
  - Both are equivalent in most cases (planner can inline CTEs)
  - CTEs improve readability by naming intermediate results
  - CTEs can be referenced multiple times in the same query
  - In PostgreSQL < 12, CTEs were always materialized (fence).
    In PostgreSQL >= 12, the planner may inline non-recursive CTEs.
  - Use MATERIALIZED / NOT MATERIALIZED to force behavior.

PRODUCTION USE CASE:
- Multi-step transformation pipelines in reporting
- Hierarchy traversal (org charts, categories, permissions)
- Graph shortest-path for recommendation engines
- Generating test data or date scaffolds

COMMON MISTAKES:
1. Using correlated subqueries in WHERE (N+1 query problem)
2. Misusing EXISTS (it only checks existence, returns true/false)
3. Deep recursive CTEs without a termination condition (infinite loop)
4. Assuming CTE = temp table (it may be inlined by the planner)
5. IN with large subquery list (prefer EXISTS or JOIN)
*/


-- ============================================================
-- SECTION 1: BASIC CTEs
-- ============================================================

-- Without CTE: nested subqueries (hard to read and debug)
SELECT
    user_id,
    total_spent,
    RANK() OVER (ORDER BY total_spent DESC) AS spending_rank
FROM (
    SELECT user_id, SUM(amount) AS total_spent
    FROM (
        SELECT user_id, amount
        FROM orders
        WHERE status = 'completed'
          AND created_at >= '2024-01-01'
    ) recent_completed
    GROUP BY user_id
) user_totals;

-- With CTEs: each step is named and readable
WITH recent_completed_orders AS (
    -- Step 1: filter to relevant orders
    SELECT user_id, amount
    FROM orders
    WHERE status = 'completed'
      AND created_at >= '2024-01-01'
),
user_totals AS (
    -- Step 2: aggregate per user
    SELECT user_id, SUM(amount) AS total_spent
    FROM recent_completed_orders
    GROUP BY user_id
),
ranked_users AS (
    -- Step 3: rank by spending
    SELECT
        user_id,
        total_spent,
        RANK() OVER (ORDER BY total_spent DESC) AS spending_rank
    FROM user_totals
)
-- Step 4: final filter and join to get user details
SELECT
    u.email,
    u.plan_type,
    r.total_spent,
    r.spending_rank
FROM ranked_users r
JOIN users        u ON r.user_id = u.user_id
WHERE r.spending_rank <= 100
ORDER BY r.spending_rank;

-- Key benefit: you can test each CTE step independently by
-- running just that SELECT — invaluable for debugging complex reports.


-- ============================================================
-- SECTION 2: MULTIPLE CHAINED CTEs
-- ============================================================

-- Multi-step revenue attribution pipeline:
WITH
-- Step 1: Get all orders in the period
period_orders AS (
    SELECT
        o.order_id,
        o.user_id,
        o.amount,
        o.created_at,
        o.channel  -- 'organic', 'paid_search', 'email', etc.
    FROM orders o
    WHERE o.status = 'completed'
      AND o.created_at BETWEEN '2024-01-01' AND '2024-03-31'
),
-- Step 2: Get user cohort info
user_cohorts AS (
    SELECT
        user_id,
        DATE_TRUNC('month', created_at) AS signup_month,
        acquisition_channel
    FROM users
),
-- Step 3: Join and compute per-channel totals
channel_revenue AS (
    SELECT
        po.channel,
        uc.acquisition_channel,
        COUNT(po.order_id)    AS order_count,
        SUM(po.amount)        AS revenue,
        COUNT(DISTINCT po.user_id) AS unique_customers
    FROM period_orders  po
    JOIN user_cohorts   uc ON po.user_id = uc.user_id
    GROUP BY po.channel, uc.acquisition_channel
),
-- Step 4: Add percentage of total
channel_with_pct AS (
    SELECT
        *,
        SUM(revenue) OVER () AS total_revenue,
        ROUND(100.0 * revenue / SUM(revenue) OVER (), 2) AS pct_of_total
    FROM channel_revenue
)
SELECT * FROM channel_with_pct
ORDER BY revenue DESC;


-- ============================================================
-- SECTION 3: RECURSIVE CTEs
-- ============================================================

/*
Recursive CTEs enable iterative computation within SQL.
They consist of two parts separated by UNION ALL:
  1. Base case (anchor): the starting rows
  2. Recursive case: references the CTE itself, adding more rows

The engine alternates: run recursive part on last results,
until recursive part returns no rows.

CRITICAL: Always include a termination condition (depth limit
or WHERE clause) to prevent infinite loops.

Format:
  WITH RECURSIVE cte AS (
      -- Base case
      SELECT ...
      UNION ALL
      -- Recursive case (references cte)
      SELECT ...
      FROM cte
      WHERE <termination condition>
  )
  SELECT * FROM cte;
*/

-- Example 1: Org chart traversal (top-down)
-- Find all reports under a given manager (direct + indirect)
WITH RECURSIVE org_hierarchy AS (
    -- Base case: start from the root manager
    SELECT
        employee_id,
        name,
        title,
        manager_id,
        0 AS depth,                    -- depth 0 = the root
        ARRAY[employee_id] AS path     -- track path to detect cycles
    FROM employees
    WHERE employee_id = 42             -- starting manager ID

    UNION ALL

    -- Recursive case: add each employee's direct reports
    SELECT
        e.employee_id,
        e.name,
        e.title,
        e.manager_id,
        oh.depth + 1,                  -- increment depth
        oh.path || e.employee_id       -- append to path
    FROM employees          e
    JOIN org_hierarchy      oh ON e.manager_id = oh.employee_id
    WHERE oh.depth < 10                -- safety: max 10 levels deep
      AND NOT e.employee_id = ANY(oh.path)  -- cycle detection
)
SELECT
    REPEAT('  ', depth) || name AS indented_name,  -- visual indent
    title,
    depth,
    employee_id
FROM org_hierarchy
ORDER BY path;

-- Example 2: Category tree (product catalog hierarchy)
-- Navigate parent → child → grandchild categories
WITH RECURSIVE category_tree AS (
    -- Base: root categories (no parent)
    SELECT
        category_id,
        name,
        parent_id,
        name::TEXT AS full_path,
        1 AS level
    FROM categories
    WHERE parent_id IS NULL

    UNION ALL

    -- Recursive: child categories
    SELECT
        c.category_id,
        c.name,
        c.parent_id,
        ct.full_path || ' > ' || c.name,  -- build breadcrumb
        ct.level + 1
    FROM categories     c
    JOIN category_tree  ct ON c.parent_id = ct.category_id
)
SELECT
    category_id,
    name,
    full_path,
    level
FROM category_tree
ORDER BY full_path;

-- Example 3: Generate a date series (without generate_series())
-- Useful in databases that don't have generate_series
WITH RECURSIVE date_series AS (
    SELECT '2024-01-01'::DATE AS d
    UNION ALL
    SELECT d + INTERVAL '1 day'
    FROM date_series
    WHERE d < '2024-12-31'
)
SELECT d FROM date_series;

-- PostgreSQL has generate_series() which is faster:
SELECT generate_series('2024-01-01'::DATE, '2024-12-31'::DATE, '1 day')::DATE;

-- Example 4: Bill of Materials (parts explosion)
-- A product is made of sub-components, which themselves have components.
WITH RECURSIVE bom_exploded AS (
    -- Base: the top-level product
    SELECT
        component_id,
        parent_id,
        name,
        quantity_needed,
        unit_cost,
        1 AS level,
        quantity_needed AS total_quantity
    FROM bill_of_materials
    WHERE parent_id IS NULL

    UNION ALL

    -- Recursive: multiply quantities through the hierarchy
    SELECT
        bom.component_id,
        bom.parent_id,
        bom.name,
        bom.quantity_needed,
        bom.unit_cost,
        be.level + 1,
        be.total_quantity * bom.quantity_needed AS total_quantity
    FROM bill_of_materials bom
    JOIN bom_exploded       be ON bom.parent_id = be.component_id
)
SELECT
    name,
    level,
    total_quantity,
    unit_cost,
    total_quantity * unit_cost AS total_cost
FROM bom_exploded
ORDER BY level, name;


-- ============================================================
-- SECTION 4: CORRELATED SUBQUERIES
-- ============================================================

/*
A correlated subquery references columns from the outer query.
It executes ONCE PER ROW of the outer query — this is the N+1
problem in SQL. For large tables, this is catastrophically slow.

Use correlated subqueries ONLY when:
  1. The dataset is small, OR
  2. There is no equivalent JOIN (rare), OR
  3. You are using EXISTS (which short-circuits at first match)

Almost always replace with a JOIN or window function.
*/

-- Correlated subquery (SLOW — executes per user row):
SELECT
    u.user_id,
    u.email,
    (
        SELECT SUM(o.amount)
        FROM orders o
        WHERE o.user_id = u.user_id   -- reference to outer query
          AND o.status = 'completed'
    ) AS total_spent
FROM users u;

-- Equivalent JOIN (FAST — single scan):
SELECT
    u.user_id,
    u.email,
    COALESCE(SUM(o.amount), 0) AS total_spent
FROM users   u
LEFT JOIN orders o
    ON u.user_id = o.user_id
    AND o.status = 'completed'
GROUP BY u.user_id, u.email;

-- Or with CTE (clear and fast):
WITH user_spending AS (
    SELECT user_id, SUM(amount) AS total_spent
    FROM orders
    WHERE status = 'completed'
    GROUP BY user_id
)
SELECT u.user_id, u.email, COALESCE(s.total_spent, 0) AS total_spent
FROM users         u
LEFT JOIN user_spending s ON u.user_id = s.user_id;


-- ============================================================
-- SECTION 5: EXISTS vs IN vs JOIN
-- ============================================================

/*
EXISTS: returns true if the subquery returns ANY row.
  - Short-circuits at first match (fast).
  - Correct for "does related data exist?" checks.
  - Handles NULLs correctly (unlike IN with NULLs).

IN: returns true if the value is in the subquery's result set.
  - Evaluates entire subquery first.
  - BUG: IN (subquery) returns no rows if subquery contains NULLs.
    NULL propagation: col IN (1, NULL, 2) = NULL (not false) for non-matches.
  - Avoid for large subquery result sets.

JOIN: returns matched rows.
  - Use when you need columns from both tables.
  - Be aware of row duplication (use DISTINCT or aggregate).
*/

-- EXISTS (preferred for existence check):
SELECT u.user_id, u.email
FROM users u
WHERE EXISTS (
    SELECT 1   -- SELECT 1 or SELECT * — content doesn't matter, only row count
    FROM orders o
    WHERE o.user_id = u.user_id
      AND o.status = 'completed'
      AND o.amount > 1000
);

-- IN (works but evaluates full subquery):
SELECT user_id, email
FROM users
WHERE user_id IN (
    SELECT user_id
    FROM orders
    WHERE status = 'completed'
      AND amount > 1000
);

-- NOT EXISTS (anti-join — users who have never ordered):
SELECT u.user_id, u.email
FROM users u
WHERE NOT EXISTS (
    SELECT 1
    FROM orders o
    WHERE o.user_id = u.user_id
);
-- Preferred over NOT IN because NOT IN with NULLs in subquery
-- returns NO ROWS (due to NULL propagation bug):
-- WHERE user_id NOT IN (SELECT user_id FROM orders)
-- If ANY user_id in orders is NULL, the NOT IN returns empty set!

-- JOIN equivalent (anti-join pattern):
SELECT u.user_id, u.email
FROM users   u
LEFT JOIN orders o ON u.user_id = o.user_id
WHERE o.order_id IS NULL;


-- ============================================================
-- SECTION 6: LATERAL JOINS
-- ============================================================

/*
LATERAL allows a subquery in the FROM clause to reference
columns from preceding tables in the same FROM clause.
Without LATERAL, FROM subqueries cannot reference outer tables.

Think of LATERAL as a "for each row, run this subquery."
It's like a correlated subquery in the FROM clause.

Use for: top-N per group, unnesting arrays, applying functions
to each row when a simple JOIN isn't expressive enough.
*/

-- Top 3 products for each category (without LATERAL = complex CTE):
SELECT
    c.category_name,
    top_products.product_id,
    top_products.name,
    top_products.revenue
FROM categories c
CROSS JOIN LATERAL (
    -- This subquery CAN reference c.category_id (LATERAL allows it)
    SELECT
        p.product_id,
        p.name,
        SUM(oi.quantity * oi.unit_price) AS revenue
    FROM products    p
    JOIN order_items oi ON p.product_id = oi.product_id
    WHERE p.category_id = c.category_id   -- references outer table
    GROUP BY p.product_id, p.name
    ORDER BY revenue DESC
    LIMIT 3   -- top 3 per category
) top_products
ORDER BY c.category_name, top_products.revenue DESC;

-- Most recent event per user (LATERAL is clean alternative to ROW_NUMBER):
SELECT
    u.user_id,
    u.email,
    latest_event.event_type,
    latest_event.created_at
FROM users u
LEFT JOIN LATERAL (
    SELECT event_type, created_at
    FROM user_events e
    WHERE e.user_id = u.user_id
    ORDER BY created_at DESC
    LIMIT 1
) latest_event ON true;   -- LATERAL LEFT JOIN requires ON true


-- ============================================================
-- SECTION 7: MATERIALIZATION BEHAVIOR
-- ============================================================

/*
PostgreSQL CTE materialization:
  - PostgreSQL 12+: non-recursive CTEs are inlined by default
    (treated as views, planner can push predicates inside).
  - MATERIALIZED hint: forces the CTE to execute once, result
    stored in memory. Use when:
      * CTE is expensive and referenced multiple times
      * You want to prevent the planner from "peeking inside"
        (rare — usually inlining is better)
  - NOT MATERIALIZED hint: forces inlining even for recursive CTEs.
*/

-- Force materialization (execute once, cache result):
WITH MATERIALIZED expensive_aggregation AS (
    SELECT user_id, SUM(amount) AS total
    FROM orders
    GROUP BY user_id
)
SELECT
    ea.user_id,
    ea.total,
    u.email
FROM expensive_aggregation ea
JOIN users u ON ea.user_id = u.user_id
WHERE ea.total > 1000;

-- Prevent materialization (let planner inline and optimize):
WITH NOT MATERIALIZED user_filter AS (
    SELECT user_id FROM users WHERE plan_type = 'enterprise'
)
SELECT o.*
FROM orders o
JOIN user_filter uf ON o.user_id = uf.user_id;

-- ============================================================
-- END OF L05
-- ============================================================
