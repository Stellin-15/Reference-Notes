-- ============================================================
-- L01: SQL Foundations
-- ============================================================
-- WHAT: Core SELECT mechanics, data types, NULL handling,
--       string/date functions, aliases, DISTINCT
-- WHY:  Every query starts here. Misunderstanding NULL,
--       type coercion, or date arithmetic causes silent data
--       corruption in production systems.
-- LEVEL: Foundations
-- ============================================================

/*
CONCEPT OVERVIEW:
SQL (Structured Query Language) is a declarative language —
you describe WHAT data you want, not HOW to retrieve it.
The database engine's query planner decides the execution path.

PRODUCTION USE CASE:
A SaaS analytics dashboard fetching user activity, revenue
reports, and time-series data all rely on these fundamentals.
Getting them wrong means wrong numbers at the C-suite level.

COMMON MISTAKES:
1. Comparing NULL with = instead of IS NULL (always returns false)
2. Assuming VARCHAR = TEXT (they are different in some engines)
3. Ignoring timezone handling in TIMESTAMP columns
4. Using SELECT * in production queries (breaks on schema changes)
*/

-- ============================================================
-- SECTION 1: SELECT, FROM, WHERE, ORDER BY, LIMIT
-- ============================================================

-- SELECT tells the engine which columns to project (return).
-- FROM tells it which relation (table/view) to scan.
-- Always be explicit — SELECT * is a code smell in production
-- because adding a column to the table silently breaks APIs.

SELECT
    user_id,
    email,
    created_at,
    plan_type
FROM users
-- WHERE filters rows BEFORE they are returned (row-level filter).
-- The engine applies WHERE during the scan, reducing I/O.
WHERE plan_type = 'enterprise'
  AND created_at >= '2024-01-01'
-- ORDER BY sorts the result set. Without it, row order is
-- UNDEFINED — PostgreSQL may return rows in heap order,
-- index order, or parallel scan order. Never rely on implicit order.
ORDER BY created_at DESC
-- LIMIT caps the result set. Critical for pagination and
-- protecting the application from massive result sets.
-- Without LIMIT, a query on a 100M-row table returns all rows.
LIMIT 100;


-- ============================================================
-- SECTION 2: DATA TYPES
-- ============================================================

/*
Choosing the right data type is an architectural decision:
  - Storage: SMALLINT (2 bytes) vs BIGINT (8 bytes) — for 1B rows,
    that's 6 GB of wasted disk and memory for a wrong choice.
  - Precision: DECIMAL/NUMERIC for money. FLOAT for money is wrong
    because IEEE 754 floating point introduces rounding errors.
    0.1 + 0.2 = 0.30000000000000004 in FLOAT.
  - Indexability: JSON fields cannot be B-tree indexed directly;
    use JSONB with GIN indexes or extract to columns.
*/

-- Example table demonstrating correct type choices:
CREATE TABLE orders (
    -- BIGSERIAL: auto-incrementing 64-bit integer PK.
    -- Use BIGINT not INT for PKs — INT overflows at 2.1 billion rows,
    -- which is reachable for high-volume SaaS in 2-3 years.
    order_id        BIGSERIAL PRIMARY KEY,

    user_id         BIGINT NOT NULL,           -- FK to users table

    -- DECIMAL(precision, scale): exact numeric arithmetic.
    -- DECIMAL(12, 2) supports up to $9,999,999,999.99.
    -- NEVER use FLOAT/DOUBLE for currency.
    amount          DECIMAL(12, 2) NOT NULL,

    -- VARCHAR(n): variable-length string capped at n chars.
    -- TEXT: unlimited length string. In PostgreSQL, TEXT and
    -- VARCHAR are stored identically — VARCHAR just adds a
    -- length check constraint. Use TEXT when length is unknown.
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    notes           TEXT,

    -- TIMESTAMPTZ: timestamp WITH time zone.
    -- Always store timestamps in UTC using TIMESTAMPTZ.
    -- TIMESTAMP (without TZ) stores local time with no TZ info —
    -- a disaster when servers move regions or DST changes.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- BOOLEAN: true/false/NULL in PostgreSQL.
    is_refunded     BOOLEAN NOT NULL DEFAULT FALSE,

    -- JSONB: binary JSON — stored compressed, supports indexing.
    -- Use for truly schemaless data. Do not use as a crutch to
    -- avoid schema design — it makes queries 10x harder to write.
    metadata        JSONB
);


-- ============================================================
-- SECTION 3: NULL HANDLING
-- ============================================================

/*
NULL is not zero, not empty string, not false.
NULL means "unknown" or "missing". This has major consequences:

  - NULL = NULL is FALSE (unknown = unknown is still unknown)
  - NULL != NULL is also FALSE
  - Any arithmetic with NULL returns NULL: 5 + NULL = NULL
  - COUNT(*) counts all rows; COUNT(col) ignores NULLs

This is the most common source of silent bugs in SQL.
*/

-- IS NULL / IS NOT NULL: correct way to check for NULL
SELECT order_id, notes
FROM orders
WHERE notes IS NULL;          -- rows where notes was never set

SELECT order_id, notes
FROM orders
WHERE notes IS NOT NULL;      -- rows where notes has a value

-- WRONG: this returns 0 rows even if notes is NULL
-- WHERE notes = NULL          -- NULL = NULL is always false/unknown


-- COALESCE: returns first non-NULL value in the list.
-- Production use: supply a fallback value to avoid NULL propagation
-- in calculations. Essential for reporting queries.
SELECT
    order_id,
    -- If discount is NULL (no discount applied), treat it as 0
    amount - COALESCE(discount, 0) AS net_amount,
    -- Display user-facing label
    COALESCE(promo_code, 'NONE') AS promo_display
FROM orders;


-- NULLIF: returns NULL if two values are equal, otherwise first value.
-- Classic use: prevent division-by-zero errors.
SELECT
    category,
    total_revenue / NULLIF(total_orders, 0) AS avg_order_value
    -- Without NULLIF, dividing by 0 throws an error.
    -- With NULLIF(total_orders, 0), when orders=0 we divide by NULL,
    -- which safely returns NULL instead of crashing.
FROM category_stats;


-- ============================================================
-- SECTION 4: STRING FUNCTIONS
-- ============================================================

-- LIKE: pattern matching with wildcards.
-- % matches any sequence of characters.
-- _ matches exactly one character.
-- LIKE is case-SENSITIVE in PostgreSQL.
SELECT email FROM users WHERE email LIKE '%@gmail.com';
SELECT sku FROM products WHERE sku LIKE 'SKU-___-2024'; -- exactly 3 chars

-- ILIKE: case-INSENSITIVE LIKE (PostgreSQL extension).
-- Use for user-facing search where case shouldn't matter.
-- WARNING: ILIKE cannot use standard B-tree indexes.
-- Use pg_trgm (trigram) extension + GIN index for fast ILIKE.
SELECT * FROM products WHERE name ILIKE '%wireless%';

-- CONCAT / || operator: string concatenation
SELECT
    first_name || ' ' || last_name AS full_name,  -- operator style
    CONCAT(first_name, ' ', last_name) AS full_name_2  -- function style
    -- || returns NULL if any operand is NULL
    -- CONCAT treats NULL as empty string — choose based on your needs
FROM users;

-- SUBSTRING: extract part of a string
SELECT
    SUBSTRING(phone FROM 1 FOR 3) AS area_code,  -- SQL standard syntax
    SUBSTRING(email FROM POSITION('@' IN email) + 1) AS email_domain
FROM users;

-- TRIM / LTRIM / RTRIM: remove whitespace or specified chars
-- Critical for cleaning user-submitted data
SELECT TRIM('   hello world   ');        -- 'hello world'
SELECT TRIM(BOTH 'x' FROM 'xxhelloxx'); -- 'hello'

-- LOWER / UPPER: case conversion
-- Best practice: store emails in lowercase at insert time,
-- not just at query time, to allow index usage.
SELECT LOWER(email) AS email_normalized FROM users;
SELECT UPPER(country_code) FROM addresses;

-- LENGTH: character count (not byte count for multibyte chars)
SELECT
    email,
    LENGTH(email) AS email_length
FROM users
WHERE LENGTH(email) > 100;  -- find suspiciously long emails


-- ============================================================
-- SECTION 5: DATE AND TIME FUNCTIONS
-- ============================================================

/*
Date/time handling is where most production bugs hide.
Always:
  1. Store as TIMESTAMPTZ (UTC)
  2. Convert to user's timezone only at the display layer
  3. Use DATE_TRUNC for period grouping (not TO_CHAR)
  4. Be aware of DST gaps and overlaps
*/

-- NOW(): current timestamp with timezone (equivalent to CURRENT_TIMESTAMP)
SELECT NOW();                             -- 2024-03-15 14:32:00+00

-- CURRENT_DATE: just the date portion (no time)
SELECT CURRENT_DATE;                      -- 2024-03-15

-- DATE_TRUNC: truncate timestamp to a time boundary.
-- This is the correct way to group by day/week/month.
-- Never use TO_CHAR for grouping — it converts to string and
-- loses sort order and date arithmetic capabilities.
SELECT
    DATE_TRUNC('day',   created_at) AS day,
    DATE_TRUNC('week',  created_at) AS week_start,   -- Monday
    DATE_TRUNC('month', created_at) AS month_start,
    DATE_TRUNC('year',  created_at) AS year_start
FROM orders;

-- EXTRACT / DATE_PART: extract a single component as a number
SELECT
    EXTRACT(YEAR  FROM created_at) AS year,
    EXTRACT(MONTH FROM created_at) AS month,    -- 1-12
    EXTRACT(DOW   FROM created_at) AS day_of_week, -- 0=Sunday
    EXTRACT(HOUR  FROM created_at) AS hour,
    EXTRACT(EPOCH FROM created_at) AS unix_seconds  -- seconds since 1970-01-01
FROM orders;

-- INTERVAL arithmetic: add/subtract time periods
-- This is correct date math — no integer day-counting hacks.
SELECT
    NOW() + INTERVAL '7 days'    AS one_week_from_now,
    NOW() - INTERVAL '30 days'   AS thirty_days_ago,
    NOW() + INTERVAL '1 month'   AS next_month,     -- handles month lengths
    NOW() + INTERVAL '1 year'    AS next_year
;

-- Real example: find orders from the last 30 days
SELECT order_id, amount, created_at
FROM orders
WHERE created_at >= NOW() - INTERVAL '30 days';

-- AT TIME ZONE: convert timestamps for display
-- Store UTC, display in user's timezone
SELECT
    created_at AS utc_time,
    created_at AT TIME ZONE 'America/New_York' AS eastern_time,
    created_at AT TIME ZONE 'Asia/Tokyo'       AS tokyo_time
FROM orders;


-- ============================================================
-- SECTION 6: ALIASES
-- ============================================================

-- Column aliases (AS): rename output columns.
-- Essential for: calculated columns, removing ambiguity,
-- clean API output (snake_case to camelCase conventions).
SELECT
    user_id                                    AS id,
    first_name || ' ' || last_name            AS full_name,
    EXTRACT(YEAR FROM AGE(birth_date))         AS age_years,
    created_at AT TIME ZONE 'UTC'              AS created_at_utc
FROM users;

-- Table aliases: shorten long table names in complex queries.
-- REQUIRED when joining a table to itself (self join).
SELECT
    u.user_id,
    u.email,
    o.order_id,
    o.amount
FROM users    u   -- 'u' is now the alias for users
JOIN orders   o   -- 'o' is now the alias for orders
    ON u.user_id = o.user_id;


-- ============================================================
-- SECTION 7: DISTINCT
-- ============================================================

/*
DISTINCT eliminates duplicate rows from the result set.
It comes AFTER the SELECT projection step.

Cost: DISTINCT requires a sort or hash step — O(n log n).
For large datasets, this is expensive. Consider whether
you actually need DISTINCT or whether a JOIN issue is
creating unwanted duplicates (usually the real problem).
*/

-- How many unique countries do our users come from?
SELECT DISTINCT country FROM users ORDER BY country;

-- DISTINCT ON (PostgreSQL-specific): keep one row per group,
-- choosing which row based on ORDER BY.
-- This is extremely powerful for "latest record per entity" queries.
SELECT DISTINCT ON (user_id)
    user_id,
    order_id,
    amount,
    created_at
FROM orders
ORDER BY user_id, created_at DESC;
-- Result: for each user_id, the most recent order only.
-- This is more efficient than a correlated subquery for this pattern.


-- ============================================================
-- SECTION 8: PUTTING IT ALL TOGETHER
-- ============================================================

-- Real-world query: daily revenue report for enterprise users
-- in the last 90 days, showing trend data
SELECT
    DATE_TRUNC('day', o.created_at)              AS revenue_date,
    COUNT(DISTINCT o.user_id)                     AS unique_customers,
    COUNT(o.order_id)                             AS total_orders,
    SUM(o.amount)                                 AS gross_revenue,
    SUM(o.amount - COALESCE(o.discount, 0))       AS net_revenue,
    AVG(o.amount)                                 AS avg_order_value
FROM orders      o
JOIN users       u ON o.user_id = u.user_id
WHERE
    u.plan_type = 'enterprise'
    AND o.status != 'cancelled'
    AND o.created_at >= NOW() - INTERVAL '90 days'
    AND o.created_at <  NOW()
GROUP BY DATE_TRUNC('day', o.created_at)
ORDER BY revenue_date DESC
LIMIT 90;

-- ============================================================
-- END OF L01
-- ============================================================
