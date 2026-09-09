# SQL — Principal Engineer Deep Dive

Companion to L01-L08 (PostgreSQL-focused). Narrative depth, then a
comprehensive common-to-uncommon reference spanning engines/tooling companies actually run.


## Query Planning & the Optimizer

**Beyond the lesson**: `EXPLAIN ANALYZE` output isn't just "is there an
index" — the REAL skill is reading the planner's COST ESTIMATES against
ACTUAL row counts. A `Seq Scan` with an estimated 100 rows that actually
returns 2 million rows means the planner's STATISTICS are stale (run
`ANALYZE` to refresh them) — the planner isn't "wrong" about index usage in
isolation, it's making a bad decision because its row-count estimates are
wrong, and no amount of adding indexes fixes stale statistics.

**Worked example**: A query that's fast with a `LIMIT 10` but slow without
it isn't a coincidence — the planner may choose an INDEX SCAN when it
expects to stop early (satisfying LIMIT quickly) but a full SEQ SCAN +
SORT when it must return everything — the SAME query, radically different
plan, purely based on the LIMIT clause changing the planner's cost calculus.

**Interview Q&A**:
- *Q: A query got slower after adding MORE indexes. Why is that possible?* A: Every additional index adds WRITE overhead (every INSERT/UPDATE must update every index) and can occasionally mislead the planner into choosing a WORSE index for a specific query than the one that existed before — more indexes isn't strictly better; each one is a real tradeoff against write performance and planner complexity.


## Isolation Levels & Concurrency

**Beyond the lesson**: The ANSI SQL isolation levels (Read Uncommitted,
Read Committed, Repeatable Read, Serializable) describe increasingly
strict guarantees against three specific anomalies — dirty reads,
non-repeatable reads, phantom reads — but PostgreSQL's actual
implementation uses MVCC (Multi-Version Concurrency Control), meaning
readers NEVER block writers and vice versa by default, a materially
different practical behavior than the ANSI spec's abstract description,
and worth knowing PostgreSQL doesn't even offer true "Read Uncommitted" —
it silently upgrades that request to Read Committed.

**Worked example**: `SELECT ... FOR UPDATE` explicitly locks selected rows
until the transaction commits — the standard mechanism for "check a
condition, then act on it" patterns (checking inventory before decrementing
it) that would otherwise race under concurrent transactions; `SELECT ...
FOR UPDATE SKIP LOCKED` additionally skips already-locked rows entirely —
the exact mechanism behind most homegrown job-queue-on-Postgres implementations.

**Interview Q&A**:
- *Q: Two transactions read the same row, both compute a new value based on it, both write back. What goes wrong under Read Committed, and how do you fix it?* A: A lost update — the second write silently overwrites the first's result with no error. Fix with `SELECT FOR UPDATE` to lock the row on first read, or an optimistic-concurrency version column checked on write (`WHERE version = :expected_version`), failing the second writer explicitly instead of silently losing data.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Database engines beyond Postgres
- **MySQL/MariaDB** — still hugely common, especially in PHP/WordPress
  and older enterprise stacks; InnoDB (its default storage engine) has its
  own MVCC implementation with real behavioral differences from Postgres's
  (gap locking under certain isolation levels being a classic interview trap).
- **SQL Server** — dominant in .NET/enterprise Windows shops; T-SQL has
  real syntax differences (`TOP` instead of `LIMIT`, different window
  function edge cases) worth knowing exist if interviewing at a
  Microsoft-stack-heavy company.
- **SQLite** — embedded, zero-server, file-based — used far more in
  production than its "toy database" reputation suggests (mobile apps,
  desktop apps, and increasingly edge/local-first architectures).

### Indexing beyond B-tree
- **GIN** (Generalized Inverted Index) — for full-text search and JSONB
  containment queries (`@>` operator) — a B-tree can't efficiently index
  "does this JSON document contain this key/value," GIN specifically can.
- **GiST** — geometric/range-type indexing (PostGIS spatial queries,
  `daterange` overlap queries) — used when the query pattern is "does this
  overlap/contain/intersect," not simple equality/ordering.
- **BRIN** (Block Range Index) — extremely space-efficient for naturally
  ordered, huge tables (a time-series table ordered by insert time) — trades
  precision for a fraction of a B-tree's storage/maintenance cost at massive scale.
- **Partial indexes** (`WHERE status = 'active'`) — index only the SUBSET
  of rows actually queried frequently, dramatically smaller and faster to
  maintain than indexing an entire large table when most rows are never queried that way.
- **Covering indexes** (`INCLUDE` clause) — include extra columns in the
  index itself so a query can be satisfied entirely from the index without
  touching the underlying table at all (index-only scan) — a real,
  meaningful performance technique for read-heavy hot-path queries.

### Query optimization patterns
- **N+1 query detection/avoidance** — the classic ORM pitfall (see FastAPI
  & Python Web deep dive) — fixed via eager loading (`JOIN`/`IN` batching)
  instead of one query per row in a loop.
- **Materialized views** — precomputed, STORED query results, refreshed on
  a schedule or trigger — the standard answer for expensive aggregate
  queries run frequently against slowly-changing data, trading storage/
  staleness for query speed.
- **Window functions for analytics** (see L04) — running totals, rankings,
  moving averages computed WITHOUT collapsing rows via GROUP BY —
  genuinely central to any analytics/reporting SQL work.

### Replication & scaling
- **Streaming replication** (Postgres) — a physical, byte-level replica
  kept in sync via WAL (Write-Ahead Log) shipping — the standard HA
  mechanism, powering read-replica architectures and failover.
- **Logical replication** — replicates at the LOGICAL (row-change) level
  rather than physical WAL bytes, enabling selective table replication and
  cross-VERSION replication that physical streaming replication can't do.
- **Sharding** — horizontal partitioning across multiple database
  instances by a shard key; Postgres itself has no NATIVE automatic
  sharding (unlike some NoSQL systems) — Citus (a Postgres extension) is
  the most common way to add distributed/sharded Postgres without switching engines entirely.
- **Connection pooling**: PgBouncer/PgPool — see FastAPI deep dive's RDS
  Proxy discussion for WHY this matters; PgBouncer specifically is the
  Postgres-ecosystem-native answer to the same connection-exhaustion problem.

### Migrations & schema management
- **Alembic** (Python/SQLAlchemy), **Flyway**/**Liquibase** (Java/polyglot),
  **golang-migrate** — the standard schema-migration tooling across
  ecosystems; the shared discipline is VERSIONED, REVERSIBLE migrations
  applied in a known order, never hand-editing a production schema directly.
- **Zero-downtime migration patterns** — adding a column as NULLABLE
  first, backfilling in batches, THEN adding a NOT NULL constraint,
  instead of one blocking `ALTER TABLE ... NOT NULL` that locks a huge
  table for the duration of a full-table rewrite.


## NICHE BUT REAL

- **The "thundering herd" cache-stampede problem, database-side** — a
  cache expiring simultaneously for a hot key sends every waiting request
  straight to the database at once; mitigations (see Redis & Caching
  Notes) include jittered TTLs and request coalescing, but it's fundamentally a DATABASE load-protection concern too.
- **Common Table Expression (CTE) materialization behavior** — in older
  Postgres versions, a CTE was ALWAYS materialized (computed once,
  fully, before the outer query used it) even if that hurt performance; Postgres 12+ can inline/optimize CTEs like subqueries, a real behavioral
  version difference worth knowing when debugging an "identical query, different performance" surprise across Postgres versions.
- **Row-Level Security (RLS)** — Postgres-native, policy-based per-row
  access control enforced by the DATABASE itself regardless of which
  application code queries it — used for true multi-tenant data isolation
  where you don't want to trust every application code path to remember a `WHERE tenant_id = ?` filter.
- **EXPLAIN (ANALYZE, BUFFERS)** — the `BUFFERS` option specifically shows
  shared-buffer HIT vs actual DISK read counts per plan node — the
  difference between "this query is slow because of computation" and "this
  query is slow because of disk I/O" is invisible without this option.
