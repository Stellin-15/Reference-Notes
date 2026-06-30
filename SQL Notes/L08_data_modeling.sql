-- ============================================================
-- L08: Data Modeling and Schema Design
-- ============================================================
-- WHAT: Normalization theory, dimensional modeling, temporal data,
--       multi-tenancy, sharding, migrations, and a complete
--       production e-commerce schema.
-- WHY:  Schema design decisions made on day 1 constrain the system
--       for years. A bad schema (no soft delete, no audit log,
--       wrong ID type) requires painful migrations at scale.
--       Getting it right upfront saves months of firefighting.
-- LEVEL: Advanced
-- ============================================================
/*
CONCEPT OVERVIEW:
    Data modeling operates at three levels:
      1. Conceptual: entities and relationships (ER diagram)
      2. Logical: tables, columns, constraints, normal form
      3. Physical: index choices, partitioning, storage parameters

    The trade-off in all modeling decisions is:
      NORMALIZATION  (write integrity, no redundancy)
      vs
      DENORMALIZATION (read speed, fewer joins, pre-aggregated)

    OLTP systems (transactional) → normalize to 3NF
    OLAP systems (analytical)    → denormalize to star schema or OBT

PRODUCTION USE CASE:
    An e-commerce platform started with a flat orders table containing
    product names as text. When products were renamed, historical
    orders showed the new name. The fix: foreign keys to a products
    table + SCD Type 2 for product history. Never store display
    values — store IDs and join. Always model history explicitly.

COMMON MISTAKES:
    - Storing email, product name, or price IN the orders table
      (should be FK to users/products; price should be snapshotted at order time)
    - Using VARCHAR(255) for everything (TEXT is better in PostgreSQL;
      VARCHAR(n) adds a check constraint with no storage benefit)
    - UUID PRIMARY KEY on a B-tree index → random insertions cause
      index fragmentation and slow inserts at scale (use UUIDv7 or BIGSERIAL)
    - No soft delete → permanent data loss on accidental delete
    - No audit log → can't answer "who changed this and when?"
    - Backward-incompatible migrations (renaming column in one step)
    - Multi-tenancy with no tenant_id check → data leakage between tenants
*/


-- ============================================================
-- SECTION 1: Normalization
-- ============================================================
-- Normal forms prevent UPDATE anomalies, INSERT anomalies, and
-- DELETE anomalies that arise from redundant data storage.
--
-- 1NF (First Normal Form):
--   - Every column is atomic (no comma-separated lists, no arrays
--     when relationships should be modeled as separate rows)
--   - No repeating groups (no phone1, phone2, phone3 columns)
--   - Each row is uniquely identifiable (primary key exists)
--
-- VIOLATION:
--   orders(id, customer_name, product1, product2, product3, ...)
--   → repeating product columns → 1NF violation
--
-- FIX: separate order_items table (one row per product per order)

-- 2NF (Second Normal Form — only applies to composite PKs):
--   - Must be in 1NF
--   - No partial dependencies: non-key attributes must depend on
--     the WHOLE primary key, not part of it.
--
-- VIOLATION (composite PK: order_id + product_id):
--   order_items(order_id, product_id, product_name, quantity)
--   product_name depends only on product_id (partial dependency)
--
-- FIX: move product_name to a products table; keep only the FK here.

-- 3NF (Third Normal Form):
--   - Must be in 2NF
--   - No transitive dependencies: non-key attributes must NOT
--     depend on other non-key attributes.
--
-- VIOLATION:
--   orders(id, customer_id, customer_zipcode, customer_city)
--   customer_city depends on customer_zipcode, not on order id
--
-- FIX: move zipcode→city mapping to a zip_codes lookup table.

-- BCNF (Boyce-Codd Normal Form): stricter 3NF.
--   Every determinant must be a candidate key.
--   Most practical designs don't go beyond 3NF.


-- ============================================================
-- SECTION 2: When to denormalize
-- ============================================================
-- Denormalization: intentionally introduce redundancy to speed reads.
-- WHEN it's justified:
--   1. Read-heavy workload: 95% reads, 5% writes
--   2. Joins are consistently slow even with indexes
--   3. Aggregations (COUNT, SUM) over large data run too slowly
--   4. Analytics on historical data where writes are already done
--
-- EXAMPLES of controlled denormalization:
--   - Store order total on the orders row (derived from order_items)
--     → avoids SUM(order_items.price * quantity) on every order read
--   - Store user.full_name even though first_name + last_name exist
--     → avoids string concatenation on every display
--   - Materialized views for dashboard aggregations
--
-- PRICE: every write must now update the redundant column too.
-- If it gets out of sync → data inconsistency → bugs.
-- Use triggers or application-level invariants to keep in sync.


-- ============================================================
-- SECTION 3: Star schema — dimensional modeling for analytics
-- ============================================================
-- Star schema: one central FACT table + surrounding DIMENSION tables.
-- The fact table contains measurements (metrics) and foreign keys
-- to dimension tables (context about what/who/when/where).
--
-- Fact table: wide, many rows, append-only (events, transactions).
-- Dimension table: narrow, fewer rows, describe context (users, products, time).
--
-- WHY it's fast for analytics:
--   - Analytics queries JOIN fact to 2-3 dimensions, then aggregate
--   - Dimension tables are small (fit in memory)
--   - Fact table can be partitioned by date
--   - Columnar storage (Redshift, BigQuery, DuckDB) works perfectly with star

-- Dimension: date (pre-populated, one row per day for 10 years)
CREATE TABLE IF NOT EXISTS dim_date (
    date_id       INT         PRIMARY KEY,   -- YYYYMMDD as int
    full_date     DATE        NOT NULL UNIQUE,
    day_of_week   INT         NOT NULL,      -- 0=Sunday, 6=Saturday
    day_name      TEXT        NOT NULL,
    month         INT         NOT NULL,
    month_name    TEXT        NOT NULL,
    quarter       INT         NOT NULL,
    year          INT         NOT NULL,
    is_weekend    BOOLEAN     NOT NULL,
    is_holiday    BOOLEAN     NOT NULL DEFAULT false
);

-- Dimension: product
CREATE TABLE IF NOT EXISTS dim_product (
    product_key   BIGSERIAL   PRIMARY KEY,   -- surrogate key (not the product's natural ID)
    product_id    TEXT        NOT NULL,      -- natural/business key
    name          TEXT        NOT NULL,
    category      TEXT        NOT NULL,
    subcategory   TEXT,
    brand         TEXT,
    unit_cost     NUMERIC(12,4)
);

-- Fact table: sales transactions
CREATE TABLE IF NOT EXISTS fact_sales (
    sale_id       BIGSERIAL   PRIMARY KEY,
    date_id       INT         NOT NULL REFERENCES dim_date(date_id),
    product_key   BIGINT      NOT NULL REFERENCES dim_product(product_key),
    customer_id   BIGINT      NOT NULL,
    quantity      INT         NOT NULL,
    unit_price    NUMERIC(12,4) NOT NULL,
    discount_pct  NUMERIC(5,2) NOT NULL DEFAULT 0,
    -- Pre-computed for fast aggregation:
    gross_revenue NUMERIC(14,4) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    net_revenue   NUMERIC(14,4) GENERATED ALWAYS AS
                  (quantity * unit_price * (1 - discount_pct/100)) STORED
);

-- Analytics query on star schema (fast because dimensions are small):
-- SELECT
--     d.month_name, d.year,
--     p.category,
--     SUM(f.net_revenue)  AS revenue,
--     COUNT(*)            AS transactions,
--     AVG(f.unit_price)   AS avg_price
-- FROM   fact_sales f
-- JOIN   dim_date    d ON d.date_id    = f.date_id
-- JOIN   dim_product p ON p.product_key = f.product_key
-- WHERE  d.year = 2024
-- GROUP BY 1, 2, 3
-- ORDER BY 2, 1, 4 DESC;


-- ============================================================
-- SECTION 4: Slowly Changing Dimensions (SCD)
-- ============================================================
-- The problem: a product's category changes. What happens to
-- historical sales that used the old category?
--
-- SCD Type 1 — Overwrite:
--   Just update the record. Historical reports now show the NEW value.
--   Use when history doesn't matter (e.g., fixing typos).
--
-- SCD Type 2 — New row with validity dates (most common):
--   Keep the old row, insert a new row with valid_from/valid_to.
--   Historical fact rows still point to the old dimension key.
--   Use is_current = true to find the active version.
--   COST: dimension table grows over time; queries must filter is_current.
--
-- SCD Type 3 — Previous value column:
--   Add a prev_category column. Only tracks ONE level of history.
--   Simple but limited — can't track more than one historical change.

-- SCD Type 2 implementation:
CREATE TABLE IF NOT EXISTS dim_product_scd2 (
    product_key   BIGSERIAL   PRIMARY KEY,   -- surrogate key, new one per version
    product_id    TEXT        NOT NULL,      -- natural key, same across all versions
    name          TEXT        NOT NULL,
    category      TEXT        NOT NULL,
    valid_from    DATE        NOT NULL,
    valid_to      DATE        NOT NULL DEFAULT '9999-12-31',  -- open-ended = current
    is_current    BOOLEAN     NOT NULL DEFAULT true
);

CREATE INDEX IF NOT EXISTS idx_dim_product_scd2_natural
    ON dim_product_scd2 (product_id, is_current);

-- When a product's category changes:
-- Step 1: Close the current record
-- UPDATE dim_product_scd2
-- SET    valid_to = CURRENT_DATE - 1, is_current = false
-- WHERE  product_id = 'PROD-001' AND is_current = true;
--
-- Step 2: Insert new current record
-- INSERT INTO dim_product_scd2 (product_id, name, category, valid_from)
-- VALUES ('PROD-001', 'Laptop Pro', 'Electronics', CURRENT_DATE);
--
-- Historical analysis: join fact table to dimension as-of sale date
-- SELECT f.*, p.category
-- FROM   fact_sales f
-- JOIN   dim_product_scd2 p
--     ON p.product_id = f.product_natural_id   -- assuming fact stores natural key
--    AND f.sale_date BETWEEN p.valid_from AND p.valid_to;


-- ============================================================
-- SECTION 5: Event sourcing in SQL
-- ============================================================
-- Event sourcing: the source of truth is an APPEND-ONLY log
-- of events. Current state is derived by replaying events.
--
-- Advantages:
--   - Complete audit trail (every change recorded, not just current state)
--   - Time travel: replay events up to any point in time
--   - Decoupled: multiple projections (views) of the same event stream
--
-- Disadvantages:
--   - Current state requires replaying (mitigate with snapshots)
--   - More complex than CRUD
--
-- Real use: bank account balance is the sum of all debit/credit events.

CREATE TABLE IF NOT EXISTS account_events (
    id          BIGSERIAL   PRIMARY KEY,
    account_id  BIGINT      NOT NULL,
    event_type  TEXT        NOT NULL CHECK (event_type IN ('deposit','withdrawal','fee','interest')),
    amount      NUMERIC(14,2) NOT NULL,    -- always positive; event_type determines sign
    balance_after NUMERIC(14,2),          -- snapshot: optional for fast current-balance reads
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_account_events_account
    ON account_events (account_id, created_at);

-- Current balance (replay):
-- SELECT
--     account_id,
--     SUM(CASE WHEN event_type IN ('deposit','interest') THEN  amount
--              WHEN event_type IN ('withdrawal','fee')   THEN -amount
--         END) AS current_balance
-- FROM account_events
-- WHERE account_id = $1
-- GROUP BY account_id;

-- Balance as-of a point in time:
-- SELECT SUM(...) FROM account_events
-- WHERE account_id = $1 AND created_at <= $2;  -- time travel!


-- ============================================================
-- SECTION 6: Temporal tables — valid-time modeling
-- ============================================================
-- Store rows with validity periods so you can query "as of" any time.
-- valid_from: when this version became effective
-- valid_to: when this version expired ('9999-12-31' = currently active)
-- This is different from event sourcing: temporal tables are mutable
-- rows with explicit time ranges, not an append-only event log.

CREATE TABLE IF NOT EXISTS employee_salaries (
    id          BIGSERIAL   PRIMARY KEY,
    employee_id BIGINT      NOT NULL,
    salary      NUMERIC(12,2) NOT NULL,
    valid_from  TIMESTAMPTZ NOT NULL,
    valid_to    TIMESTAMPTZ NOT NULL DEFAULT 'infinity',   -- PostgreSQL infinity literal
    EXCLUDE USING GIST (
        employee_id WITH =,
        tstzrange(valid_from, valid_to) WITH &&           -- no overlapping periods per employee
    )
);

-- Current salary:
-- SELECT salary FROM employee_salaries
-- WHERE employee_id = $1 AND valid_to = 'infinity';
--
-- Salary as of 2023-06-01:
-- SELECT salary FROM employee_salaries
-- WHERE employee_id = $1
--   AND valid_from <= '2023-06-01' AND valid_to > '2023-06-01';


-- ============================================================
-- SECTION 7: Soft delete
-- ============================================================
-- Hard delete (DELETE FROM): permanent, unrecoverable, breaks
-- FK references, and removes audit trail.
-- Soft delete (deleted_at column): mark as deleted, keep the row.
--
-- Pattern: add deleted_at TIMESTAMPTZ NULL.
-- All application queries add WHERE deleted_at IS NULL.
-- Partial index on active records keeps queries fast.
-- Deleted records can be archived or truly deleted after 30/90 days.

-- (users table already defined above with deleted_at)
-- Soft delete:
-- UPDATE users SET deleted_at = NOW() WHERE id = $1;
--
-- Restore:
-- UPDATE users SET deleted_at = NULL WHERE id = $1;
--
-- Find recently deleted:
-- SELECT * FROM users WHERE deleted_at > NOW() - INTERVAL '30 days';


-- ============================================================
-- SECTION 8: Audit logging
-- ============================================================
-- Audit log tracks EVERY change to sensitive tables: who, what, when.
-- Two approaches:
--   Application-level: application code writes to audit_log table.
--     Pro: captures user context (who), easy to customize.
--     Con: easy to forget in one code path → audit gaps.
--   Trigger-based: database trigger fires on every INSERT/UPDATE/DELETE.
--     Pro: cannot be bypassed (works even for direct psql changes).
--     Con: adds latency to every write; harder to capture app user context.

CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL   PRIMARY KEY,
    table_name  TEXT        NOT NULL,
    record_id   BIGINT      NOT NULL,
    operation   TEXT        NOT NULL CHECK (operation IN ('INSERT','UPDATE','DELETE')),
    old_values  JSONB,          -- NULL for INSERT
    new_values  JSONB,          -- NULL for DELETE
    changed_by  BIGINT,         -- user_id (NULL for system operations)
    changed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ip_address  INET,
    session_id  TEXT
) PARTITION BY RANGE (changed_at);  -- partition by month for manageability

-- Example trigger-based audit for the users table:
-- CREATE OR REPLACE FUNCTION audit_trigger_func() RETURNS TRIGGER AS $$
-- BEGIN
--     IF TG_OP = 'DELETE' THEN
--         INSERT INTO audit_log (table_name, record_id, operation, old_values, changed_at)
--         VALUES (TG_TABLE_NAME, OLD.id, 'DELETE', row_to_json(OLD)::jsonb, NOW());
--     ELSIF TG_OP = 'UPDATE' THEN
--         INSERT INTO audit_log (table_name, record_id, operation, old_values, new_values, changed_at)
--         VALUES (TG_TABLE_NAME, NEW.id, 'UPDATE', row_to_json(OLD)::jsonb, row_to_json(NEW)::jsonb, NOW());
--     ELSIF TG_OP = 'INSERT' THEN
--         INSERT INTO audit_log (table_name, record_id, operation, new_values, changed_at)
--         VALUES (TG_TABLE_NAME, NEW.id, 'INSERT', row_to_json(NEW)::jsonb, NOW());
--     END IF;
--     RETURN NULL;  -- AFTER trigger; return value ignored
-- END;
-- $$ LANGUAGE plpgsql;
--
-- CREATE TRIGGER users_audit
-- AFTER INSERT OR UPDATE OR DELETE ON users
-- FOR EACH ROW EXECUTE FUNCTION audit_trigger_func();


-- ============================================================
-- SECTION 9: UUID vs BIGSERIAL — ID type tradeoffs
-- ============================================================
-- BIGSERIAL (auto-incrementing 64-bit int):
--   Pro: sequential → B-tree index insertions are at the right end
--        (no fragmentation), cache-efficient, small (8 bytes).
--   Con: guessable, leaks record count, not globally unique across
--        databases (can't merge two databases without ID conflicts).
--
-- UUID v4 (random):
--   Pro: globally unique, not guessable, safe to expose in URLs.
--   Con: random → B-tree insertions scattered throughout index →
--        index fragmentation → 2-5x slower INSERT at scale.
--        Bloated pages → more cache pressure → slower reads too.
--
-- UUID v7 (time-ordered, RFC 9562):
--   Pro: globally unique AND time-ordered → sequential index behavior.
--        First 48 bits are millisecond timestamp → naturally sorted.
--        Best of both worlds.
--   Con: not yet in PostgreSQL stdlib (use pg_uuidv7 extension or generate in app).
--   → Prefer UUIDv7 for distributed systems needing global uniqueness.

-- Generate UUIDv7 (requires pg_uuidv7 extension or application generation):
-- CREATE EXTENSION IF NOT EXISTS pg_uuidv7;
-- SELECT uuid_generate_v7();  -- time-ordered UUID

-- Pattern: use BIGSERIAL for internal tables, UUIDv7 for externally-visible IDs.
-- This gives you fast internal joins AND safe external exposure.


-- ============================================================
-- SECTION 10: Schema migrations — backward-compatible patterns
-- ============================================================
-- Zero-downtime migrations require backward compatibility:
-- the new schema must work with BOTH old and new application code
-- simultaneously (during rolling deployments).
--
-- SAFE migration: adding a nullable column
--   Step 1: ALTER TABLE users ADD COLUMN nickname TEXT NULL;
--   Step 2: Backfill: UPDATE users SET nickname = name WHERE nickname IS NULL;
--            (do in batches to avoid locking: WHERE id BETWEEN $1 AND $2)
--   Step 3: ALTER TABLE users ALTER COLUMN nickname SET NOT NULL;
--            (only after all rows are populated)
--
-- UNSAFE: adding NOT NULL column in one step
--   ALTER TABLE users ADD COLUMN nickname TEXT NOT NULL DEFAULT '';
--   → On large tables, PostgreSQL must rewrite every row → table lock for minutes
--
-- NEVER rename a column in one migration:
--   Bad:  ALTER TABLE orders RENAME COLUMN amount TO total;
--         → Old app code still uses 'amount' → crashes immediately
--   Safe: Step 1: Add new column 'total', copy data, update app to write both
--         Step 2: Deploy new app version reading from 'total'
--         Step 3: Drop old 'amount' column in next release
--
-- TOOLS: Flyway, Liquibase, Alembic (Python), golang-migrate
--        These version-control migrations and track what's been applied.


-- ============================================================
-- SECTION 11: Multi-tenancy patterns
-- ============================================================
-- Three approaches to multi-tenant data isolation:

-- APPROACH 1: Separate databases per tenant
--   Pro: complete isolation, easy backup per tenant, different PG versions OK.
--   Con: connection pooling is hard (N databases × M connections),
--        cross-tenant reporting requires federation,
--        schema migrations must run N times.
--   Use when: strict compliance (HIPAA, SOC2), large enterprise tenants.

-- APPROACH 2: Separate schemas per tenant
--   One database, one schema per tenant (schema = namespace in PG).
--   Pro: easy to backup/restore one tenant (pg_dump -n tenant_schema),
--        natural isolation, can run different versions of tables.
--   Con: connection pooling still needs schema switching (SET search_path),
--        migrations must run per schema, PG has limits on active schemas.
--   Use when: medium isolation needs, < 1000 tenants.

-- APPROACH 3: Shared table with tenant_id column (most common)
--   Every table has tenant_id column. All queries filter on tenant_id.
--   Pro: simple infrastructure, easy migrations, easy cross-tenant analytics.
--   Con: data leakage risk if tenant_id filter is forgotten,
--        one noisy tenant can impact others (no storage quotas).
--   Use when: SaaS startups, homogeneous tenant sizes, < 100k tenants.

-- CRITICAL for shared table: enable Row Level Security (RLS)
-- to enforce tenant isolation at the database level (can't be bypassed by app code bugs).

-- ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY tenant_isolation ON orders
--     USING (tenant_id = current_setting('app.current_tenant_id')::BIGINT);
-- → Every query on 'orders' automatically adds WHERE tenant_id = $current_tenant


-- ============================================================
-- SECTION 12: Complete e-commerce schema
-- ============================================================
-- Production-ready schema incorporating: all constraints, indexes,
-- soft delete, audit timestamps, UUIDs, partitioning.

CREATE TABLE IF NOT EXISTS ec_users (
    id          BIGSERIAL       PRIMARY KEY,
    external_id UUID            NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    email       TEXT            NOT NULL UNIQUE,
    name        TEXT            NOT NULL,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deleted_at  TIMESTAMPTZ     NULL          -- soft delete
);
CREATE INDEX IF NOT EXISTS idx_ec_users_active
    ON ec_users (email) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS ec_addresses (
    id          BIGSERIAL   PRIMARY KEY,
    user_id     BIGINT      NOT NULL REFERENCES ec_users(id) ON DELETE CASCADE,
    label       TEXT        NOT NULL DEFAULT 'home',  -- 'home', 'work', 'other'
    line1       TEXT        NOT NULL,
    line2       TEXT,
    city        TEXT        NOT NULL,
    state_code  CHAR(2),
    postal_code TEXT        NOT NULL,
    country     CHAR(2)     NOT NULL DEFAULT 'US',
    is_default  BOOLEAN     NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ec_products (
    id          BIGSERIAL   PRIMARY KEY,
    sku         TEXT        NOT NULL UNIQUE,
    name        TEXT        NOT NULL,
    description TEXT,
    category    TEXT        NOT NULL,
    price_cents BIGINT      NOT NULL CHECK (price_cents >= 0),  -- store money as integer cents!
    stock_qty   INT         NOT NULL DEFAULT 0 CHECK (stock_qty >= 0),
    is_active   BOOLEAN     NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ec_products_active_category
    ON ec_products (category) WHERE is_active = true;

CREATE TABLE IF NOT EXISTS ec_orders (
    id              BIGSERIAL   PRIMARY KEY,
    external_id     UUID        NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    user_id         BIGINT      NOT NULL REFERENCES ec_users(id),
    shipping_addr_id BIGINT     REFERENCES ec_addresses(id) ON DELETE SET NULL,
    status          TEXT        NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending','confirmed','shipped','delivered','cancelled','refunded')),
    -- Snapshot price at order time (do NOT join to products for this)
    -- If product price changes, the order must reflect what was paid.
    subtotal_cents  BIGINT      NOT NULL DEFAULT 0,
    tax_cents       BIGINT      NOT NULL DEFAULT 0,
    shipping_cents  BIGINT      NOT NULL DEFAULT 0,
    total_cents     BIGINT      GENERATED ALWAYS AS (subtotal_cents + tax_cents + shipping_cents) STORED,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (created_at);

CREATE TABLE IF NOT EXISTS ec_orders_2024
    PARTITION OF ec_orders
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');

CREATE TABLE IF NOT EXISTS ec_orders_2025
    PARTITION OF ec_orders
    FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');

CREATE INDEX IF NOT EXISTS idx_ec_orders_user
    ON ec_orders (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ec_orders_status
    ON ec_orders (status) WHERE status NOT IN ('delivered', 'cancelled', 'refunded');

CREATE TABLE IF NOT EXISTS ec_order_items (
    id              BIGSERIAL   PRIMARY KEY,
    order_id        BIGINT      NOT NULL,   -- FK to ec_orders; cross-partition FK not supported
    order_created_at TIMESTAMPTZ NOT NULL,  -- needed to route FK to correct partition
    product_id      BIGINT      NOT NULL REFERENCES ec_products(id),
    -- Snapshot values at order time — NEVER join back to products for these
    product_name    TEXT        NOT NULL,
    sku             TEXT        NOT NULL,
    unit_price_cents BIGINT     NOT NULL,
    quantity        INT         NOT NULL CHECK (quantity > 0),
    line_total_cents BIGINT     GENERATED ALWAYS AS (unit_price_cents * quantity) STORED,
    FOREIGN KEY (order_id, order_created_at) REFERENCES ec_orders(id, created_at)
);

CREATE INDEX IF NOT EXISTS idx_ec_order_items_order
    ON ec_order_items (order_id);
CREATE INDEX IF NOT EXISTS idx_ec_order_items_product
    ON ec_order_items (product_id);

CREATE TABLE IF NOT EXISTS ec_payments (
    id              BIGSERIAL   PRIMARY KEY,
    order_id        BIGINT      NOT NULL,
    order_created_at TIMESTAMPTZ NOT NULL,
    amount_cents    BIGINT      NOT NULL,
    currency        CHAR(3)     NOT NULL DEFAULT 'USD',
    method          TEXT        NOT NULL CHECK (method IN ('card','paypal','bank_transfer','crypto')),
    status          TEXT        NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending','processing','succeeded','failed','refunded')),
    provider_id     TEXT,        -- Stripe charge ID, PayPal transaction ID, etc.
    error_message   TEXT,
    processed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (order_id, order_created_at) REFERENCES ec_orders(id, created_at)
);

-- Prevent duplicate payment for same order (only one successful payment allowed):
CREATE UNIQUE INDEX IF NOT EXISTS idx_ec_payments_order_success
    ON ec_payments (order_id)
    WHERE status = 'succeeded';

-- ============================================================
-- Summary: key design decisions in this schema
-- ============================================================
-- 1. BIGSERIAL PKs for all tables (fast sequential inserts, small joins)
-- 2. external_id UUID for user/order (expose to API; internal ID never exposed)
-- 3. Price stored as BIGINT cents (never FLOAT/NUMERIC for money; no rounding errors)
-- 4. Snapshot product_name and unit_price in order_items (immutable historical record)
-- 5. Soft delete on users (deleted_at column)
-- 6. Partial indexes on status (only index active/pending rows)
-- 7. Partitioned ec_orders by created_at (pruning for time-range queries)
-- 8. GENERATED ALWAYS AS for computed totals (no sync bugs, correct at all times)
-- 9. ON DELETE CASCADE / SET NULL defined explicitly (no orphaned rows)
-- 10. All timestamps as TIMESTAMPTZ (time zone aware; never TIMESTAMP without TZ)
-- ============================================================
