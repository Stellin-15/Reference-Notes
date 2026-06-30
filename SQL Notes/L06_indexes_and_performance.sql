-- ============================================================
-- L06: Indexes and Query Performance
-- ============================================================
-- WHAT: How PostgreSQL indexes work internally, when to use each
--       type, and how to read EXPLAIN ANALYZE output to diagnose
--       slow queries.
-- WHY:  A missing index on a 100M-row table turns a 2ms query
--       into a 40-second full table scan. Index knowledge is the
--       highest-ROI performance skill in SQL.
-- LEVEL: Advanced
-- ============================================================
/*
CONCEPT OVERVIEW:
    An index is a separate data structure maintained by PostgreSQL
    alongside the main table (the "heap"). Every INSERT/UPDATE/DELETE
    must update all indexes on the table — indexes make reads faster
    at the cost of write overhead and storage.

    The query planner chooses whether to use an index based on:
      - Estimated row count (selectivity)
      - Table statistics (pg_statistic, updated by ANALYZE)
      - Cost constants (seq_page_cost, random_page_cost)
    For small tables, a seq scan is FASTER than an index scan
    because the planner knows reading 5 pages sequentially beats
    5 random I/Os with index overhead.

PRODUCTION USE CASE:
    An e-commerce platform's order lookup was taking 8,000ms:
      SELECT * FROM orders WHERE customer_id = $1 AND status = 'pending';
    After adding a partial composite index on (customer_id) WHERE
    status = 'pending', query time dropped to 1ms. The partial index
    is 90% smaller than a full index because 'pending' is <10% of rows.

COMMON MISTAKES:
    - Adding indexes on low-cardinality columns (e.g., boolean, status
      with 3 values) — the planner may ignore them; seq scan is faster
    - Index on (a, b) does NOT help "WHERE b = ?" — column order matters
    - Implicit casts: WHERE created_at::date = '2024-01-01' disables index
    - LIKE '%suffix' is not indexable by B-tree (use pg_trgm GIN for that)
    - Forgetting to ANALYZE after bulk load — stale stats → bad plans
    - Too many indexes: a table with 15 indexes has 15x write amplification
*/


-- ============================================================
-- SECTION 1: B-tree index — the default
-- ============================================================
-- B-tree (Balanced tree): nodes split as data grows, keeping
-- tree height at O(log n). PostgreSQL B-trees use branching
-- factor ~400, so a 100M-row table has height ~4.
-- 4 page reads to find any row, regardless of table size.
--
-- Automatically created for: PRIMARY KEY, UNIQUE constraint.
-- Supports: =, <, <=, >, >=, BETWEEN, IN, IS NULL, ORDER BY.
-- Does NOT support: LIKE '%suffix' (only 'prefix%' is indexable).

CREATE TABLE IF NOT EXISTS orders (
    id          BIGSERIAL PRIMARY KEY,           -- implicit B-tree index
    customer_id BIGINT    NOT NULL,
    status      TEXT      NOT NULL DEFAULT 'pending',
    total       NUMERIC(12,2),
    email       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    region      TEXT
);

-- Explicit B-tree (default type — you don't need to specify USING btree)
CREATE INDEX IF NOT EXISTS idx_orders_customer
    ON orders (customer_id);

-- Multi-column B-tree: designed for queries that filter on BOTH columns.
-- Column order rule: put the MOST selective / most queried first.
-- (customer_id, status) helps:
--   WHERE customer_id = $1                      ✓ (left-prefix rule)
--   WHERE customer_id = $1 AND status = $2      ✓
--   WHERE status = $2                            ✗ (no left prefix)
CREATE INDEX IF NOT EXISTS idx_orders_customer_status
    ON orders (customer_id, status);


-- ============================================================
-- SECTION 2: Hash index — equality-only, O(1)
-- ============================================================
-- Hash index: stores a hash of the indexed value → direct slot lookup.
-- Faster than B-tree for pure equality (=) lookups on high-cardinality
-- columns. Cannot be used for range queries (>, <, BETWEEN, ORDER BY).
--
-- When PostgreSQL uses it: only when the query has col = $1 and
-- the planner estimates hash scan is cheaper than B-tree scan.
-- In practice, B-tree is usually preferred because it's more versatile.
-- Hash indexes in PostgreSQL 10+ are WAL-logged (crash-safe).

CREATE INDEX IF NOT EXISTS idx_orders_email_hash
    ON orders USING HASH (email);   -- good for "WHERE email = ?" lookups


-- ============================================================
-- SECTION 3: GIN index — for arrays, JSONB, full-text
-- ============================================================
-- GIN (Generalized Inverted Index): maps each element/token to
-- the set of rows containing it. Think: a book's index at the back.
--
-- Use cases:
--   - JSONB columns with @> (contains) operator
--   - Array columns with @> (array contains)
--   - Full-text search (tsvector)
--   - pg_trgm extension for LIKE '%pattern%' search
--
-- Cost: slow to build and update (every element is indexed separately).
-- GIN is NOT suitable for columns that change frequently.

CREATE TABLE IF NOT EXISTS products (
    id         BIGSERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    tags       TEXT[],                    -- array column
    attributes JSONB,                     -- json column
    search_vec TSVECTOR                   -- full-text vector
);

-- GIN on array column — enables: WHERE tags @> ARRAY['electronics']
CREATE INDEX IF NOT EXISTS idx_products_tags_gin
    ON products USING GIN (tags);

-- GIN on JSONB — enables: WHERE attributes @> '{"color": "red"}'
CREATE INDEX IF NOT EXISTS idx_products_attributes_gin
    ON products USING GIN (attributes);

-- GIN on tsvector — enables fast full-text: WHERE search_vec @@ to_tsquery('laptop')
CREATE INDEX IF NOT EXISTS idx_products_search_gin
    ON products USING GIN (search_vec);


-- ============================================================
-- SECTION 4: GiST index — geometric and full-text
-- ============================================================
-- GiST (Generalized Search Tree): extensible index for custom
-- data types. Supports overlap, containment, and distance queries.
--
-- Common use cases:
--   - PostGIS geometry types (Points, Polygons, LineStrings)
--   - Range types (int4range, tstzrange) with && (overlap) operator
--   - tsvector full-text (GiST is alternative to GIN; GIN is faster
--     for queries, GiST is faster to build and update)
--   - Nearest-neighbor search (ORDER BY point <-> target LIMIT 10)

-- CREATE INDEX idx_locations_geom ON locations USING GIST (geom);
-- Enables: WHERE geom && ST_MakeEnvelope(xmin,ymin,xmax,ymax, 4326)
-- Enables: ORDER BY geom <-> ST_Point(-73.9, 40.7)::geometry LIMIT 5


-- ============================================================
-- SECTION 5: BRIN index — block range for sequential data
-- ============================================================
-- BRIN (Block Range INdex): stores min/max values per block range
-- (default: 128 pages). When the table is physically ordered by the
-- indexed column (like an append-only timestamp column), BRIN can
-- skip large portions of the table.
--
-- Size: a BRIN index is TINY — often <1MB for a 100GB table.
-- Speed: builds in seconds. Updates are near-free.
-- When to use: large, append-only tables where the column value
-- correlates with physical insertion order (created_at, event_id).
-- When NOT to use: columns with no correlation to physical order.

CREATE INDEX IF NOT EXISTS idx_orders_created_brin
    ON orders USING BRIN (created_at)
    WITH (pages_per_range = 128);  -- default; tune up for better compression


-- ============================================================
-- SECTION 6: Partial index — index only the rows you query
-- ============================================================
-- A partial index includes a WHERE clause, so only rows matching
-- that clause are indexed. Result: much smaller index (faster scans,
-- less memory, faster writes) that only covers the hot subset.
--
-- CRITICAL: the WHERE clause in the index must EXACTLY match the
-- WHERE clause in your query for the planner to use it.
-- WHERE status = 'pending' in the index means queries must say
-- WHERE status = 'pending', not WHERE status != 'completed'.

-- Only 5% of orders are 'pending' — index just those rows.
-- Queries checking pending orders are now blazing fast.
CREATE INDEX IF NOT EXISTS idx_orders_pending
    ON orders (customer_id, created_at)
    WHERE status = 'pending';

-- Partial index for soft-deleted records pattern:
-- Most queries filter WHERE deleted_at IS NULL (active records).
CREATE TABLE IF NOT EXISTS users (
    id         BIGSERIAL PRIMARY KEY,
    email      TEXT UNIQUE NOT NULL,
    name       TEXT NOT NULL,
    deleted_at TIMESTAMPTZ NULL        -- NULL means active
);

CREATE INDEX IF NOT EXISTS idx_users_active_email
    ON users (email)
    WHERE deleted_at IS NULL;   -- only active users in index


-- ============================================================
-- SECTION 7: Covering index (INCLUDE) — index-only scan
-- ============================================================
-- An index-only scan returns data directly from the index without
-- touching the table heap at all. This is possible when the index
-- contains ALL columns referenced by the query.
--
-- INCLUDE columns: stored in leaf nodes of the B-tree but NOT
-- used for sorting/filtering. They make the index larger but
-- enable index-only scans for queries that project those columns.
--
-- Before INCLUDE was added (Postgres 11+), you'd add all columns
-- to the key — which hurt index ordering semantics.

-- Query: SELECT id, total FROM orders WHERE customer_id = $1 AND status = 'pending'
-- This index satisfies both the filter AND the projection — index-only scan.
CREATE INDEX IF NOT EXISTS idx_orders_covering
    ON orders (customer_id, status)
    INCLUDE (id, total, created_at);   -- fetched directly from index


-- ============================================================
-- SECTION 8: Expression index
-- ============================================================
-- Indexes can be built on EXPRESSIONS, not just raw columns.
-- The query must use the IDENTICAL expression for the planner
-- to recognize the index can be used.
--
-- Use case: case-insensitive email lookups without storing
-- a separate lowercased column.

CREATE INDEX IF NOT EXISTS idx_users_email_lower
    ON users (LOWER(email));

-- Query that uses this index:
--   SELECT * FROM users WHERE LOWER(email) = LOWER($1);
-- Query that does NOT use it (wrong expression):
--   SELECT * FROM users WHERE email = LOWER($1);
--   (LHS is 'email', not 'LOWER(email)' — no match)


-- ============================================================
-- SECTION 9: EXPLAIN and EXPLAIN ANALYZE
-- ============================================================
-- EXPLAIN: shows the ESTIMATED query plan without executing.
-- EXPLAIN ANALYZE: EXECUTES the query and shows actual vs estimated.
--   WARNING: EXPLAIN ANALYZE actually runs the query. Wrap DML in
--   a transaction and ROLLBACK if you don't want side effects:
--     BEGIN; EXPLAIN ANALYZE DELETE ...; ROLLBACK;
--
-- Key plan nodes to recognize:
--
--   Seq Scan          → reads every row in the table (usually slow for large tables)
--   Index Scan        → uses index to find rows, then fetches from heap (random I/O)
--   Index Only Scan   → uses index, never touches heap (fastest; requires INCLUDE)
--   Bitmap Index Scan → collects row addresses from index, sorts them, fetches
--                       heap pages in order (good for moderate row counts)
--   Hash Join         → hashes the smaller table, probes with the larger
--                       (fast for large joins with good hash on memory)
--   Nested Loop Join  → for each outer row, scan inner table
--                       (fast when inner is small or indexed)
--   Merge Join        → both sides must be pre-sorted; good for large sorted sets
--
-- Reading the output:
--   cost=0.00..1234.56  → startup cost .. total cost (planner's estimate)
--   rows=500            → estimated row count (check against actual!)
--   width=32            → estimated bytes per row
--   actual time=0.1..8.5 ms  → real elapsed time (ANALYZE only)
--   actual rows=482     → real row count (if far off → stale stats → ANALYZE)
--   loops=3             → this node ran 3 times (multiply cost by loops)

-- Check estimated vs actual — divergence means stale stats:
-- EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
--   SELECT * FROM orders
--   WHERE customer_id = 42 AND status = 'pending';
--
-- BUFFERS shows hit/read counts:
--   Buffers: shared hit=5 read=0   → entirely from cache (good)
--   Buffers: shared hit=0 read=500 → disk I/O (index or cache miss)


-- ============================================================
-- SECTION 10: ANALYZE and VACUUM
-- ============================================================
-- ANALYZE: samples the table and updates statistics in pg_statistic.
-- The planner uses these stats to estimate row counts and choose plans.
-- Run ANALYZE manually after:
--   - Bulk loading millions of rows
--   - Mass DELETE/UPDATE that changes data distribution significantly
--
-- Autovacuum runs ANALYZE automatically, but it lags after bulk loads.

ANALYZE orders;         -- update stats for one table
-- ANALYZE;            -- update stats for all tables (slow, use carefully)

-- VACUUM: reclaims storage from dead tuples (rows updated/deleted but
-- not yet removed — PostgreSQL uses MVCC, keeping old row versions).
-- Dead tuples cause table bloat and slow down seq scans.
--
-- VACUUM (without FULL): reclaims space for REUSE within the table.
--   Does not return space to OS. Non-blocking (concurrent reads/writes OK).
-- VACUUM FULL: rewrites the entire table. Returns space to OS.
--   Holds ACCESS EXCLUSIVE LOCK — blocks all reads and writes. Avoid in prod.
--   Use pg_repack extension instead for online table repacking.

VACUUM orders;          -- standard vacuum, non-blocking
-- VACUUM FULL orders;  -- only if absolutely necessary; takes a lock


-- ============================================================
-- SECTION 11: Common slow query causes
-- ============================================================

-- CAUSE 1: Implicit cast disabling index
-- BAD: PostgreSQL must cast EVERY row's age to text — index unused
-- SELECT * FROM users WHERE age::text = '30';
--
-- GOOD: cast the literal, not the column
-- SELECT * FROM users WHERE age = 30;

-- CAUSE 2: Function on indexed column in WHERE
-- BAD: the index is on created_at, but DATE() wraps it
-- SELECT * FROM orders WHERE DATE(created_at) = '2024-01-15';
--
-- GOOD: range condition that the index CAN use
-- SELECT * FROM orders WHERE created_at >= '2024-01-15' AND created_at < '2024-01-16';

-- CAUSE 3: LIKE with leading wildcard — B-tree can't help
-- BAD: '%gmail.com' requires full table scan
-- SELECT * FROM users WHERE email LIKE '%gmail.com';
-- Fix: use pg_trgm extension + GIN index for arbitrary LIKE patterns
-- CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- CREATE INDEX ON users USING GIN (email gin_trgm_ops);

-- CAUSE 4: OR conditions — planner may not use indexes
-- BAD: this can cause two seq scans
-- SELECT * FROM orders WHERE status = 'pending' OR status = 'failed';
-- GOOD: use IN() — planner handles this as one index scan
-- SELECT * FROM orders WHERE status IN ('pending', 'failed');

-- CAUSE 5: N+1 query problem
-- N+1: fetch 1000 customers, then loop and fetch orders for each → 1001 queries
-- BAD (in application code):
--   customers = SELECT * FROM customers LIMIT 1000
--   for each customer: SELECT * FROM orders WHERE customer_id = customer.id
--
-- GOOD: single JOIN fetches everything
-- SELECT c.id, c.name, o.id AS order_id, o.total
-- FROM   customers c
-- JOIN   orders o ON o.customer_id = c.id
-- WHERE  c.id = ANY($1::bigint[]);    -- $1 is the array of IDs


-- ============================================================
-- SECTION 12: pg_stat_statements — find slowest queries
-- ============================================================
-- pg_stat_statements tracks cumulative stats for every distinct
-- query shape (parameters normalized to $1, $2, etc.).
-- Enable in postgresql.conf: shared_preload_libraries = 'pg_stat_statements'

-- Top 10 slowest queries by total time:
-- SELECT
--     total_exec_time::BIGINT AS total_ms,
--     calls,
--     (total_exec_time / calls)::NUMERIC(10,2) AS avg_ms,
--     rows / calls AS avg_rows,
--     query
-- FROM pg_stat_statements
-- ORDER BY total_exec_time DESC
-- LIMIT 10;

-- Cache hit rate (should be >99% for a well-tuned server):
-- SELECT
--     sum(heap_blks_hit)  AS heap_hits,
--     sum(heap_blks_read) AS heap_reads,
--     round(100.0 * sum(heap_blks_hit) /
--           NULLIF(sum(heap_blks_hit) + sum(heap_blks_read), 0), 2) AS hit_rate_pct
-- FROM pg_statio_user_tables;


-- ============================================================
-- SECTION 13: Connection pooling — PgBouncer
-- ============================================================
-- PostgreSQL spawns a process (~5-10 MB) per connection.
-- 1000 direct connections = 5-10 GB RAM just for connection processes,
-- plus context-switching overhead → database grinds to a halt.
--
-- PgBouncer (or pgpool-II) is a lightweight proxy that maintains
-- a SMALL pool of real database connections and multiplexes
-- thousands of application connections onto them.
--
-- Modes:
--   Transaction pooling: connection returned to pool after each transaction.
--                        Best throughput. Incompatible with SET/LISTEN/NOTIFY.
--   Session pooling:     connection held for the life of the client session.
--                        Simpler, but less efficient.
--
-- Typical config: 10 app servers × 20 connections/server = 200 app connections
-- PgBouncer pool: 20 real DB connections → database sees only 20 processes.
-- Result: 10x reduction in DB process count, often 2-3x throughput increase.


-- ============================================================
-- SECTION 14: Real-world before/after example
-- ============================================================
-- Scenario: dashboard query fetching recent pending orders per customer
-- Table: orders (10 million rows)
-- Before: Seq Scan → Execution Time: 9,847ms

-- BEFORE (no useful index):
-- EXPLAIN ANALYZE
-- SELECT customer_id, COUNT(*), SUM(total)
-- FROM   orders
-- WHERE  status = 'pending'
--   AND  created_at > NOW() - INTERVAL '7 days'
-- GROUP BY customer_id;
-- → Seq Scan on orders  (cost=0.00..320000.00 rows=8500 width=24)
-- → Execution Time: 9847.221 ms

-- Fix: add a partial index covering the date range and status filter
CREATE INDEX IF NOT EXISTS idx_orders_pending_recent
    ON orders (customer_id, created_at)
    WHERE status = 'pending';

-- AFTER (index used):
-- EXPLAIN ANALYZE
-- SELECT customer_id, COUNT(*), SUM(total)
-- FROM   orders
-- WHERE  status = 'pending'
--   AND  created_at > NOW() - INTERVAL '7 days'
-- GROUP BY customer_id;
-- → Index Scan using idx_orders_pending_recent on orders
-- →   (cost=0.43..42.50 rows=850 width=24)
-- → Execution Time: 1.843 ms
-- ∆ = 9845ms saved. Same query, one index, 5000x speedup.
