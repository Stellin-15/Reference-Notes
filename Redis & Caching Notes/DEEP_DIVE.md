# Redis & Caching — Principal Engineer Deep Dive

Companion to the existing lessons. Narrative depth, then a comprehensive
common-to-uncommon reference.


## Cache Invalidation — The Actually Hard Problem

**Beyond the lesson**: "There are only two hard things in computer
science: cache invalidation and naming things" is a joke with real teeth.
TTL-based expiry is simple but creates a window of staleness; explicit
invalidation (deleting/updating the cache entry the moment underlying data
changes) is fresher but requires EVERY write path to remember to invalidate
— miss one code path and you have a silent, hard-to-detect stale-cache bug
that only shows up as "weird, unreproducible" user reports.

**Worked example**: Cache-aside (lazy loading) vs write-through, precisely
— cache-aside (the most common pattern: check cache, on miss read from DB
and populate cache) only caches what's actually been requested, but every
first request pays the full DB-read cost; write-through (write to cache
AND DB synchronously on every write) keeps the cache always warm for
written data but adds latency to every write and wastes cache space on
data that's never read back.

**Interview Q&A**:
- *Q: A hot cache key just expired and 10,000 requests hit simultaneously. What happens, and how do you prevent it?* A: Cache stampede/thundering herd — all 10,000 requests miss the cache at once and hit the database simultaneously, potentially overwhelming it. Mitigations: request coalescing (only ONE request actually queries the DB, others wait for its result), jittered TTLs (avoid many keys expiring at the exact same instant), and probabilistic early expiration (refresh slightly before actual expiry, spreading refresh load over time).


## Redis Data Structures Beyond Simple KV

**Beyond the lesson**: Redis's real power beyond "a fast KV store" is its
RICH data structure support operating server-side — a Sorted Set
(`ZADD`/`ZRANGE`) gives O(log n) ranked leaderboard operations without
pulling all data client-side to sort; a HyperLogLog gives approximate
unique-count cardinality estimation in a fixed, tiny memory footprint
(a few KB) regardless of whether you're counting thousands or billions of
unique items — a genuinely different tool than "just cache the result of a COUNT DISTINCT."

**Worked example**: Rate limiting with Redis, precisely — a sliding-window
rate limiter using a Sorted Set keyed per user, where each request adds a
timestamp-scored entry, old entries outside the window are trimmed
(`ZREMRANGEBYSCORE`), and the remaining count (`ZCARD`) is checked against
the limit — all in a few atomic Redis commands, far simpler and more
accurate than a naive fixed-window counter that has hard edge effects at window boundaries.

**Interview Q&A**:
- *Q: Why use Redis for distributed locking instead of just a database row lock?* A: Latency — Redis operations are sub-millisecond in-memory, versus a database round-trip; the Redlock algorithm (or simpler single-instance `SET key value NX EX ttl`) provides a lock with automatic expiry (preventing permanent deadlock if a holder crashes) that's fast enough to use as a real concurrency-control primitive in a hot request path.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Caching layers, by position in the stack
- **Browser/HTTP cache** (`Cache-Control`, `ETag`) — the cheapest possible
  cache: never even reaching your servers at all for a repeat request.
- **CDN edge cache** (Cloudflare, Fastly, CloudFront) — caches at the
  network edge, closest to the user, for content shared across many users.
- **Application-level cache** (Redis/Memcached) — shared across all
  instances of your app, for computed results/DB query results/session data.
- **In-process/local cache** (Caffeine in Java, an in-memory dict in
  Python) — fastest possible access (no network hop at all) but not
  shared across instances — used for very hot, small, rarely-changing data
  (feature flags, config) where per-instance memory duplication is acceptable.

### Redis vs alternatives
- **Memcached** — simpler, pure KV, multi-threaded (can use multiple CPU
  cores natively, unlike Redis's traditionally single-threaded model) —
  chosen when you truly need ONLY simple caching and want the raw
  throughput-per-core Memcached's simplicity provides.
- **Redis** — richer data structures, persistence options, pub/sub,
  Lua scripting, and now multi-threading for I/O in recent versions — the
  more common default specifically because caching needs usually grow into needing these extra capabilities eventually.
- **Dragonfly** — a newer, API-compatible Redis alternative built for
  significantly better multi-core utilization and memory efficiency —
  worth knowing as an emerging drop-in replacement gaining production adoption.
- **KeyDB** — another Redis-fork aimed at multi-threading performance,
  similar niche to Dragonfly.

### Redis persistence & HA
- **RDB snapshots** — point-in-time binary dumps, fast to restore from,
  but can lose data since the last snapshot on a crash.
- **AOF (Append-Only File)** — logs every write operation, replayed on
  restart — more durable than RDB alone, configurable fsync frequency
  trading durability against write throughput.
- **Redis Sentinel** — automated failover for a primary/replica setup
  WITHOUT full cluster sharding — the simpler HA option for moderate scale.
- **Redis Cluster** — sharded, horizontally scalable Redis across many
  nodes — needed once dataset size or throughput exceeds what a single
  Redis instance (even with replicas) can handle.

### Managed caching services
- **ElastiCache** (AWS), **Azure Cache for Redis**, **Memorystore** (GCP)
  — managed Redis/Memcached, handling failover/patching/scaling
  operationally — the default choice for most companies over self-hosting
  Redis, similar tradeoff logic to RDS vs self-managed Postgres.
- **Upstash** — serverless, pay-per-request Redis — popular specifically
  for edge/serverless architectures (Vercel/Cloudflare Workers) where a
  traditional always-on Redis connection model doesn't fit a serverless function's lifecycle.


## NICHE BUT REAL

- **Redis Lua scripting** (`EVAL`) — lets you execute a sequence of Redis
  commands ATOMICALLY as a single script server-side, avoiding
  race conditions between separate round-trip commands from your
  application — the mechanism behind many "custom atomic operation" needs
  Redis doesn't natively provide a single command for.
- **Probabilistic data structures beyond HyperLogLog**: Bloom filters
  (Redis modules or standalone) — answer "have I possibly seen this
  before" with a tunable false-positive rate and near-zero memory,
  used heavily for deduplication at massive scale (has this URL been crawled, has this event ID been processed).
- **Cache warming** — proactively populating a cache BEFORE traffic hits
  it (after a deploy that flushed the cache, or ahead of an expected
  traffic spike) rather than letting the first wave of real users pay the
  cold-cache cost — a genuinely important operational practice for high-traffic launches.
- **Multi-tier caching with negative caching** — caching the FACT that a
  lookup returned "not found," not just successful results — prevents a
  repeated flood of requests for a nonexistent key from hammering the
  database every single time, a subtle but real production optimization.
