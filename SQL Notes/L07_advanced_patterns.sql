-- ============================================================
-- L07: Advanced SQL Patterns
-- ============================================================
-- WHAT: Production patterns for upserts, transactions, locking,
--       partitioning, materialized views, lateral joins, JSONB,
--       and concurrent job queue design.
-- WHY:  These patterns appear in every serious production system.
--       Using INSERT instead of upsert causes duplicates; wrong
--       isolation level causes race conditions; missing partition
--       pruning causes full scans on multi-TB tables.
-- LEVEL: Advanced
-- ============================================================
/*
CONCEPT OVERVIEW:
    SQL is not just SELECT — it is a concurrent, transactional system.
    The patterns here address the hardest parts of that:
      - Concurrent writes without data corruption (locking, isolation)
      - Huge tables that still need to be fast (partitioning)
      - Expensive queries that need to be pre-computed (materialized views)
      - Idempotent operations that can be retried safely (upsert)
      - Flexible schema that doesn't require migrations for every feature (JSONB)

    These patterns exist at the boundary of application code and database.
    Getting them wrong causes subtle bugs that only appear under load.

PRODUCTION USE CASE:
    A high-throughput job queue serves 50 workers pulling tasks
    concurrently. Without SELECT FOR UPDATE SKIP LOCKED, workers
    would all lock the same row, causing 49 of 50 workers to block.
    With SKIP LOCKED, each worker instantly grabs a different row.
    This single change scaled throughput from 100 jobs/min to 5000.

COMMON MISTAKES:
    - Using INSERT then UPDATE as two statements instead of upsert
      (race condition: two concurrent INSERTs on the same key)
    - Not understanding that READ COMMITTED allows non-repeatable reads
      (SELECT twice in same transaction can return different rows)
    - Deadlocks from locking rows in different orders across transactions
    - Partition key in WHERE clause uses a function → no partition pruning
    - REFRESH MATERIALIZED VIEW (without CONCURRENTLY) locks the view
      for the duration of the refresh — use CONCURRENTLY in production
    - Storing JSON as TEXT instead of JSONB (TEXT is not indexed, not validated)
*/


-- ============================================================
-- SECTION 1: Upsert — INSERT ... ON CONFLICT
-- ============================================================
-- Upsert = INSERT, but if a conflict on a unique key occurs,
-- either UPDATE the existing row or silently skip.
-- This is ATOMIC — no race condition between "check then insert".
-- Idempotent: safe to retry on failure without causing duplicates.
--
-- ON CONFLICT (col) DO UPDATE SET ...:
--   EXCLUDED refers to the row that WOULD have been inserted.
--   Use EXCLUDED.column_name to access the incoming values.
--
-- ON CONFLICT DO NOTHING:
--   Silent skip on conflict. Useful for idempotent event ingestion
--   where re-processing is expected (at-least-once delivery).

CREATE TABLE IF NOT EXISTS event_log (
    event_id    TEXT        PRIMARY KEY,   -- idempotency key
    payload     JSONB       NOT NULL,
    processed   BOOLEAN     NOT NULL DEFAULT false,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotent event ingestion: retry-safe, no duplicate rows.
-- If the same event_id arrives again, silently skip it.
INSERT INTO event_log (event_id, payload)
VALUES ('evt-abc-123', '{"type": "order.placed", "amount": 99.95}')
ON CONFLICT (event_id) DO NOTHING;

-- Upsert with update: user profile sync from external system.
-- If user exists → update name/email. If not → insert.
CREATE TABLE IF NOT EXISTS user_profiles (
    external_id  TEXT        PRIMARY KEY,
    email        TEXT        NOT NULL,
    name         TEXT        NOT NULL,
    last_synced  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO user_profiles (external_id, email, name, last_synced)
VALUES ('ext-456', 'alice@example.com', 'Alice Smith', NOW())
ON CONFLICT (external_id)
DO UPDATE SET
    email       = EXCLUDED.email,        -- take values from the incoming row
    name        = EXCLUDED.name,
    last_synced = NOW()
-- Optional guard: only update if data actually changed (avoids unnecessary I/O)
WHERE user_profiles.email != EXCLUDED.email
   OR user_profiles.name  != EXCLUDED.name;


-- ============================================================
-- SECTION 2: MERGE statement (PostgreSQL 15+)
-- ============================================================
-- MERGE is standard SQL (ISO/IEC 9075) and more expressive than
-- ON CONFLICT. Allows conditional WHEN MATCHED / WHEN NOT MATCHED
-- branches with different actions (INSERT/UPDATE/DELETE).
-- Use when you need more complex logic than ON CONFLICT allows.

-- MERGE INTO user_profiles AS target
-- USING (VALUES ('ext-456', 'alice@new.com', 'Alice Updated')) AS source(external_id, email, name)
-- ON target.external_id = source.external_id
-- WHEN MATCHED AND target.email != source.email THEN
--     UPDATE SET email = source.email, name = source.name, last_synced = NOW()
-- WHEN NOT MATCHED THEN
--     INSERT (external_id, email, name) VALUES (source.external_id, source.email, source.name)
-- WHEN MATCHED AND source.name = 'DELETED' THEN
--     DELETE;


-- ============================================================
-- SECTION 3: Transactions, savepoints, isolation levels
-- ============================================================
-- Transaction: a group of statements that succeed or fail together.
-- BEGIN ... COMMIT: success path.
-- BEGIN ... ROLLBACK: failure path — all changes undone.
--
-- SAVEPOINT: partial rollback point within a transaction.
-- Useful when part of a transaction fails and you want to
-- continue the rest rather than rolling back everything.

BEGIN;
    INSERT INTO event_log (event_id, payload)
    VALUES ('evt-savepoint-test', '{"type": "test"}');

    SAVEPOINT before_risky_operation;

    -- If this fails, we can roll back just to the savepoint
    -- without losing the INSERT above.
    UPDATE user_profiles SET email = 'test@test.com' WHERE external_id = 'nonexistent';

    -- This would be used in application code:
    -- IF something_went_wrong THEN
    --     ROLLBACK TO SAVEPOINT before_risky_operation;
    -- END IF;

    RELEASE SAVEPOINT before_risky_operation;  -- discard savepoint (commit to here)
ROLLBACK;  -- rolling back the whole demo transaction


-- ISOLATION LEVELS and what they prevent:
--
-- Phenomenon          │ READ COMMITTED │ REPEATABLE READ │ SERIALIZABLE
-- ────────────────────┼────────────────┼─────────────────┼──────────────
-- Dirty read          │ prevented      │ prevented       │ prevented
-- Non-repeatable read │ POSSIBLE       │ prevented       │ prevented
-- Phantom read        │ POSSIBLE       │ prevented*      │ prevented
-- Serialization anomaly│ POSSIBLE      │ POSSIBLE        │ prevented
-- * PostgreSQL REPEATABLE READ also prevents phantom reads (better than SQL standard)
--
-- READ COMMITTED (PostgreSQL default):
--   Each statement sees a fresh snapshot of committed data.
--   Two SELECTs in the same transaction CAN return different rows
--   if another transaction committed between them.
--   → Safe for most OLTP workloads.
--
-- REPEATABLE READ:
--   All statements in the transaction see the SAME snapshot (taken at first statement).
--   Prevents phantom reads in PostgreSQL (better than SQL standard guarantees).
--   → Use for analytical queries that must see consistent data.
--
-- SERIALIZABLE:
--   Transactions appear to have run one-at-a-time (serially), even if concurrent.
--   PostgreSQL uses SSI (Serializable Snapshot Isolation) — detects and aborts
--   transactions that would violate serializability.
--   → Use for financial ledgers, inventory where correctness > throughput.

-- SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;
-- SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;


-- ============================================================
-- SECTION 4: SELECT FOR UPDATE and job queue with SKIP LOCKED
-- ============================================================
-- SELECT FOR UPDATE: acquires a row-level lock.
-- Other transactions trying to SELECT FOR UPDATE on the same row
-- will BLOCK until the first transaction commits or rolls back.
-- Use case: "claim" a row for update, preventing concurrent updates.
--
-- FOR UPDATE SKIP LOCKED: if a row is already locked, SKIP it.
-- This is the key to an efficient concurrent job queue:
-- Worker 1 locks job row 1 (row 2 is unlocked)
-- Worker 2 tries to get a job → row 1 is locked → SKIPS it → gets row 2
-- No blocking, no serialization, maximum concurrency.

CREATE TABLE IF NOT EXISTS job_queue (
    id          BIGSERIAL   PRIMARY KEY,
    job_type    TEXT        NOT NULL,
    payload     JSONB       NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'pending',   -- pending/running/done/failed
    attempts    INT         NOT NULL DEFAULT 0,
    max_attempts INT        NOT NULL DEFAULT 3,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()        -- for delayed/scheduled jobs
);

-- Worker polling query: claim the next available job atomically.
-- This entire SELECT + UPDATE is atomic within a transaction.
-- BEGIN and COMMIT are issued by the application around this block.
--
-- BEGIN;
WITH claimed AS (
    SELECT id
    FROM   job_queue
    WHERE  status = 'pending'
      AND  run_at <= NOW()
      AND  attempts < max_attempts
    ORDER BY run_at ASC
    LIMIT  1                      -- each worker claims exactly one job
    FOR UPDATE SKIP LOCKED        -- skip any row another worker has locked
)
UPDATE job_queue
SET    status   = 'running',
       attempts = attempts + 1
FROM   claimed
WHERE  job_queue.id = claimed.id
RETURNING job_queue.*;            -- return the claimed row to the application
-- COMMIT;

-- After processing (in application code):
-- On success:  UPDATE job_queue SET status = 'done'   WHERE id = $1;
-- On failure:  UPDATE job_queue SET status = 'failed' WHERE id = $1;
-- On retry:    UPDATE job_queue SET status = 'pending', run_at = NOW() + INTERVAL '5 minutes' WHERE id = $1;


-- ============================================================
-- SECTION 5: Deadlocks and prevention
-- ============================================================
-- Deadlock: T1 holds lock on row A, waits for row B.
--           T2 holds lock on row B, waits for row A.
--           Neither can proceed. PostgreSQL detects this and
--           aborts one transaction (the "victim") automatically.
--
-- DETECTION: PostgreSQL has a deadlock detector that runs when
-- a lock wait exceeds deadlock_timeout (default 1s). Check:
-- SELECT * FROM pg_locks WHERE NOT granted;
--
-- PREVENTION (always lock resources in the SAME ORDER):
-- If all transactions lock rows in ascending ID order, cycles
-- cannot form. Example: transfer money between accounts A and B
-- always locks min(A,B) first, then max(A,B).
--
-- T1: LOCK account 100, then account 200
-- T2: LOCK account 100, then account 200  ← same order = no deadlock

-- lock_timeout: fail immediately if can't get lock in N ms
-- SET lock_timeout = '5s';

-- Optimistic locking: version column, no DB-level lock needed.
-- Read the row, note version. Update WHERE version = old_version.
-- Check affected rows = 1. If 0, someone else modified it → retry.
-- Best for low-contention scenarios (avoids holding locks).
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 0;

-- Application reads: SELECT id, email, version FROM user_profiles WHERE external_id = $1;
-- Application writes (optimistic):
-- UPDATE user_profiles
-- SET    email = $new_email, version = version + 1
-- WHERE  external_id = $1 AND version = $old_version;
-- → If rows_affected = 0: someone else updated → re-read and retry


-- ============================================================
-- SECTION 6: Table partitioning
-- ============================================================
-- Partitioning: split one logical table into multiple physical
-- child tables ("partitions"). The query planner can prune
-- partitions that can't possibly contain matching rows.
--
-- PARTITION BY RANGE: for dates, IDs in ranges (logs, time-series)
-- PARTITION BY LIST:  for discrete values (region, status)
-- PARTITION BY HASH:  for even distribution by hash of a key (user_id)
--
-- RULES:
--   1. Partition key must appear in the PRIMARY KEY (if any)
--   2. Queries must filter on the partition key for pruning to work
--   3. Attaching/detaching partitions is DDL, not a data operation
--      (instant; use DETACH to archive old partitions)
--   4. Global indexes don't exist; each partition has its own indexes

-- Range partition by month — common for event/log/audit tables
CREATE TABLE IF NOT EXISTS events (
    id         BIGSERIAL,
    event_type TEXT        NOT NULL,
    user_id    BIGINT,
    payload    JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)              -- partition key must be in PK
) PARTITION BY RANGE (created_at);

-- Create partitions for specific date ranges.
-- Best practice: create future partitions in advance (cron job or pg_partman).
CREATE TABLE IF NOT EXISTS events_2024_01
    PARTITION OF events
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');

CREATE TABLE IF NOT EXISTS events_2024_02
    PARTITION OF events
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');

-- Partition pruning in action:
-- EXPLAIN SELECT * FROM events WHERE created_at >= '2024-01-01' AND created_at < '2024-02-01';
-- → Scans ONLY events_2024_01 (pruning skips events_2024_02 and others)
--
-- NO pruning (function wraps the column):
-- SELECT * FROM events WHERE DATE(created_at) = '2024-01-15';
-- → Seq scan on ALL partitions — the function hides the value from the planner

-- Hash partition for user data — even load distribution
-- CREATE TABLE user_data (user_id BIGINT, ...) PARTITION BY HASH (user_id);
-- CREATE TABLE user_data_0 PARTITION OF user_data FOR VALUES WITH (MODULUS 4, REMAINDER 0);
-- CREATE TABLE user_data_1 PARTITION OF user_data FOR VALUES WITH (MODULUS 4, REMAINDER 1);
-- ... etc.

-- Detach old partition for archiving (instant DDL, no data movement):
-- ALTER TABLE events DETACH PARTITION events_2024_01;
-- Now events_2024_01 is a standalone table; can be pg_dump'd and dropped.


-- ============================================================
-- SECTION 7: Materialized views
-- ============================================================
-- Materialized view: a pre-computed result set stored on disk.
-- Unlike a regular view (executes query on every access), a
-- materialized view is snapshotted at refresh time.
--
-- Use when:
--   - The underlying query is expensive (many joins, aggregations)
--   - Slight staleness is acceptable
--   - The view is queried frequently (many reads, few refreshes)
--
-- REFRESH MATERIALIZED VIEW:
--   - Truncates the view and repopulates it → EXCLUSIVE LOCK during refresh
--   - No reads allowed while refreshing → use CONCURRENTLY
--
-- REFRESH MATERIALIZED VIEW CONCURRENTLY:
--   - Uses a diff approach: builds new data in temp table, then swaps
--   - Allows concurrent reads during refresh (no lock held on view)
--   - Requires a UNIQUE index on the materialized view

CREATE MATERIALIZED VIEW IF NOT EXISTS daily_order_summary AS
SELECT
    DATE_TRUNC('day', created_at)::DATE  AS day,
    COUNT(*)                              AS order_count,
    SUM(total)                            AS revenue,
    AVG(total)                            AS avg_order_value
FROM events
WHERE event_type = 'order.placed'
GROUP BY 1
WITH DATA;   -- populate immediately; WITH NO DATA = create empty, populate later

-- Required for CONCURRENTLY refresh:
CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_order_summary_day
    ON daily_order_summary (day);

-- Refresh in production (safe, non-blocking):
REFRESH MATERIALIZED VIEW CONCURRENTLY daily_order_summary;

-- Schedule via pg_cron or application cron job:
-- SELECT cron.schedule('refresh-daily-summary', '5 0 * * *',
--   'REFRESH MATERIALIZED VIEW CONCURRENTLY daily_order_summary');


-- ============================================================
-- SECTION 8: Lateral joins — correlated subquery per row
-- ============================================================
-- LATERAL: the subquery on the right side can reference columns
-- from the table on the left side (like a correlated subquery,
-- but can return multiple rows and be JOINed like a table).
--
-- Classic use: top-N per group without window functions.
-- Get the 3 most recent orders per customer:

CREATE TABLE IF NOT EXISTS customers (
    id    BIGSERIAL PRIMARY KEY,
    name  TEXT NOT NULL,
    email TEXT NOT NULL
);

-- Top-3 most recent orders per customer using LATERAL
-- SELECT c.name, recent.id AS order_id, recent.total, recent.created_at
-- FROM   customers c
-- CROSS JOIN LATERAL (
--     SELECT id, total, created_at
--     FROM   orders o
--     WHERE  o.customer_id = c.id        -- ← references outer row c
--     ORDER BY created_at DESC
--     LIMIT 3
-- ) AS recent
-- ORDER BY c.name, recent.created_at DESC;
--
-- CROSS JOIN LATERAL: every customer row is processed; if no orders,
-- the customer is omitted. Use LEFT JOIN LATERAL ... ON true to keep
-- customers with no orders (LATERAL equivalent of LEFT JOIN).


-- ============================================================
-- SECTION 9: JSONB — flexible schema in PostgreSQL
-- ============================================================
-- JSON vs JSONB:
--   JSON:  stored as text, preserves whitespace and key order,
--          parsed on every access — slower for querying.
--   JSONB: stored as binary parsed tree, deduplicated keys,
--          last value wins for duplicate keys, indexable with GIN.
--   → Almost always use JSONB. JSON is only for preserving exact input.
--
-- JSONB operators:
--   ->   returns JSON (for sub-objects)
--   ->>  returns TEXT (for leaf values)
--   #>   path access returning JSON:  payload #> '{address,city}'
--   #>>  path access returning TEXT:  payload #>> '{address,city}'
--   @>   contains: payload @> '{"status": "active"}'
--   ?    key exists: payload ? 'email'
--   ?|   any key exists: payload ?| ARRAY['email', 'phone']

CREATE TABLE IF NOT EXISTS flexible_records (
    id      BIGSERIAL PRIMARY KEY,
    type    TEXT  NOT NULL,
    data    JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert structured data without schema migration:
INSERT INTO flexible_records (type, data) VALUES
('user', '{"name": "Alice", "age": 30, "tags": ["admin", "beta"]}'),
('order', '{"amount": 150.00, "items": [{"sku": "A1", "qty": 2}]}')
ON CONFLICT DO NOTHING;

-- Query JSONB fields:
-- SELECT data->>'name' AS name FROM flexible_records WHERE type = 'user';
-- SELECT data->'items'->0->>'sku' AS first_sku FROM flexible_records WHERE type = 'order';

-- Array access in JSONB:
-- SELECT jsonb_array_elements(data->'tags') AS tag
-- FROM   flexible_records WHERE type = 'user';

-- Contains operator (uses GIN index if present):
-- SELECT * FROM flexible_records WHERE data @> '{"tags": ["admin"]}';

-- GIN index for fast JSONB queries:
CREATE INDEX IF NOT EXISTS idx_flexible_records_data_gin
    ON flexible_records USING GIN (data);


-- ============================================================
-- SECTION 10: Generated columns
-- ============================================================
-- Generated column: always computed from other columns.
-- STORED: computed and saved to disk (takes space, faster to read).
-- Cannot be inserted or updated directly.
-- Useful for: pre-computing a TSVECTOR for full-text, normalizing
-- a value for indexing (e.g., LOWER(email)), or derived metrics.

CREATE TABLE IF NOT EXISTS products_gen (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT    NOT NULL,
    price_cents INT     NOT NULL,
    quantity    INT     NOT NULL DEFAULT 0,
    -- GENERATED ALWAYS AS: computed from other columns, stored on disk
    total_value_cents INT GENERATED ALWAYS AS (price_cents * quantity) STORED,
    -- Full-text search vector auto-maintained:
    search_vec  TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', name)) STORED
);

CREATE INDEX IF NOT EXISTS idx_products_gen_search
    ON products_gen USING GIN (search_vec);

-- Query full-text:
-- SELECT name FROM products_gen WHERE search_vec @@ to_tsquery('english', 'laptop & gaming');


-- ============================================================
-- SECTION 11: Complete job queue implementation
-- ============================================================
-- Putting it all together: a production-grade job queue using
-- SELECT FOR UPDATE SKIP LOCKED + upsert + partitioning.

-- Full job queue table with all production features:
CREATE TABLE IF NOT EXISTS jobs (
    id           BIGSERIAL,
    queue_name   TEXT        NOT NULL DEFAULT 'default',
    job_type     TEXT        NOT NULL,
    payload      JSONB       NOT NULL DEFAULT '{}',
    status       TEXT        NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending','running','done','failed')),
    priority     INT         NOT NULL DEFAULT 5,          -- lower = higher priority
    attempts     INT         NOT NULL DEFAULT 0,
    max_attempts INT         NOT NULL DEFAULT 3,
    scheduled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_at    TIMESTAMPTZ,
    locked_by    TEXT,                                    -- worker identifier
    done_at      TIMESTAMPTZ,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE TABLE IF NOT EXISTS jobs_2024
    PARTITION OF jobs
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');

-- Worker claim query (application wraps in BEGIN/COMMIT):
-- WITH claimed AS (
--     SELECT id, created_at
--     FROM   jobs
--     WHERE  status       = 'pending'
--       AND  queue_name   = $1
--       AND  scheduled_at <= NOW()
--       AND  attempts     < max_attempts
--     ORDER BY priority ASC, scheduled_at ASC
--     LIMIT 1
--     FOR UPDATE SKIP LOCKED
-- )
-- UPDATE jobs SET
--     status    = 'running',
--     locked_at = NOW(),
--     locked_by = $worker_id,
--     attempts  = attempts + 1
-- FROM claimed
-- WHERE jobs.id = claimed.id
--   AND jobs.created_at = claimed.created_at   -- required for partitioned table PK
-- RETURNING *;
