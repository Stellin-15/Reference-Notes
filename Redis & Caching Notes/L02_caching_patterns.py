# ============================================================
# L02: Caching Patterns
# ============================================================
# WHAT: Core strategies for reading/writing data with a cache layer
#       (Redis) in front of a primary store (PostgreSQL/MySQL).
# WHY:  Caching reduces DB load by orders of magnitude, cuts
#       latency from ~10ms (DB) to ~0.1ms (Redis), and enables
#       horizontal scale without proportional DB growth.
# LEVEL: Intermediate
# ============================================================
"""
CONCEPT OVERVIEW:
    There are four canonical caching patterns. Cache-aside (lazy
    loading) is the most common: the application checks the cache
    first, goes to the DB on a miss, then populates the cache.
    Write-through keeps cache and DB in sync synchronously on every
    write. Write-behind (write-back) writes to cache immediately
    and persists to the DB asynchronously in batches — fast writes
    but small risk of data loss on crash. Read-through makes the
    cache itself responsible for loading from the DB on a miss,
    transparent to the application.

    Eviction policies determine what gets removed when Redis hits
    its maxmemory limit. Choosing the right policy is critical to
    cache effectiveness.

    Cache stampede (thundering herd) is a failure mode where
    many concurrent requests all miss the cache simultaneously
    and hammer the DB. Mutex locks and probabilistic early expiry
    are the standard mitigations.

    Invalidation is the hardest problem in caching. Three main
    approaches: delete-on-write (simple, immediate), versioned keys
    (no deletes needed, storage overhead), event-driven (pub/sub
    invalidation signal triggers consumer to evict the key).

PRODUCTION USE CASE:
    E-commerce product catalog: millions of SKUs, each page load
    would be 5-10 DB queries without caching. Cache-aside with a
    15-minute TTL on product data. Stampede protection via Redis
    SET NX mutex on the first miss. Invalidation triggered by the
    product-update event in the event bus — consumer deletes the
    key. Hit rate target > 95% in steady state.

COMMON MISTAKES:
    1. Caching mutable, user-specific data (e.g., shopping cart
       balances) without strict invalidation — users see stale totals.
    2. No TTL on cached keys — stale data accumulates indefinitely
       and Redis memory fills up.
    3. Caching at the wrong granularity — caching an entire user
       object when only one field changes causes excessive churn.
    4. Not tracking hit/miss ratio — you cannot know if the cache
       is actually helping without measuring.
    5. Using noeviction in production without alerting — Redis will
       start returning errors to clients when full.
    6. Forgetting to handle the cache miss under high concurrency
       (stampede) — one missing cache key can take down the DB.
"""

import time
import uuid
import random
import threading
import logging
from typing import Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict

# --------------- Simulated infrastructure ---------------
# In a real service these would be redis.Redis() and a DB connection pool.

class FakeRedis:
    """Minimal in-memory Redis stand-in for demonstration purposes.
    Supports GET/SET/DELETE/SETNX and TTL-aware expiry."""

    def __init__(self):
        self._store: dict[str, tuple[Any, Optional[float]]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            # Lazy expiry check — same as real Redis
            if expires_at and time.time() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """SET key value [EX seconds]"""
        with self._lock:
            expires_at = time.time() + ex if ex else None
            self._store[key] = (value, expires_at)
            return True

    def setex(self, key: str, seconds: int, value: Any) -> bool:
        return self.set(key, value, ex=seconds)

    def set_nx(self, key: str, value: Any, ex: int = 10) -> bool:
        """SET key value NX EX — only set if key does not exist.
        Returns True if the key was set, False if it already existed."""
        with self._lock:
            entry = self._store.get(key)
            if entry is not None:
                _, expires_at = entry
                if expires_at is None or time.time() < expires_at:
                    return False          # Key exists and is valid
            expires_at = time.time() + ex
            self._store[key] = (value, expires_at)
            return True

    def delete(self, key: str) -> int:
        with self._lock:
            return 1 if self._store.pop(key, None) is not None else 0

    def exists(self, key: str) -> bool:
        return self.get(key) is not None


class FakeDatabase:
    """Simulates a PostgreSQL round-trip with ~10ms latency."""

    def __init__(self):
        # Pre-seed some product rows
        self._products = {
            i: {
                "id": i,
                "name": f"Product {i}",
                "price": round(9.99 + i * 1.5, 2),
                "stock": 100 - i,
                "description": f"A great product number {i}.",
            }
            for i in range(1, 21)
        }
        self.query_count = 0

    def get_product(self, product_id: int) -> Optional[dict]:
        time.sleep(0.01)          # Simulate 10ms DB round-trip
        self.query_count += 1
        return self._products.get(product_id)

    def update_product(self, product_id: int, updates: dict) -> bool:
        time.sleep(0.01)
        self.query_count += 1
        if product_id in self._products:
            self._products[product_id].update(updates)
            return True
        return False


# ============================================================
# PATTERN 1: Cache-Aside (Lazy Loading)
# ============================================================
# The application is responsible for the full read path.
# Read:  check cache → hit → return | miss → query DB → SET cache → return
# Write: update DB → delete (or update) cache key
#
# PROS: Only caches data that is actually requested. Cache failures
#       are tolerable — requests fall through to the DB.
# CONS: First request after a miss is slow (DB latency). Requires
#       the application to manage the cache explicitly.
# ============================================================

@dataclass
class CacheMetrics:
    """Track hit/miss ratio — the single most important cache metric.
    A well-tuned cache should sustain > 90% hit rate in production."""
    hits: int = 0
    misses: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0

    def __repr__(self):
        return (f"CacheMetrics(hits={self.hits}, misses={self.misses}, "
                f"hit_rate={self.hit_rate:.1f}%)")


def get_product_cache_aside(
    product_id: int,
    redis: FakeRedis,
    db: FakeDatabase,
    metrics: CacheMetrics,
    ttl: int = 900,          # 15 minutes — product data changes infrequently
) -> Optional[dict]:
    """
    Cache-aside read path with hit/miss tracking.

    The key naming convention encodes the entity type and ID.
    Prefixing with 'product:' allows SCAN patterns and avoids
    collisions with other key types in the same Redis instance.
    """
    cache_key = f"product:{product_id}"

    # Step 1: Check the cache first
    cached = redis.get(cache_key)
    if cached is not None:
        metrics.hits += 1
        return cached                 # Cache HIT — fast path, ~0.1ms

    # Step 2: Cache MISS — go to the DB (slow path, ~10ms)
    metrics.misses += 1
    product = db.get_product(product_id)

    if product is None:
        # Even a negative result should be cached to avoid repeated DB hits
        # for missing IDs ("negative caching"). Use a short TTL for negatives.
        redis.setex(cache_key, 60, "__NOT_FOUND__")  # 60s for negative cache
        return None

    # Step 3: Populate the cache so the next request is fast
    redis.setex(cache_key, ttl, product)
    return product


def invalidate_product_cache(
    product_id: int,
    updates: dict,
    redis: FakeRedis,
    db: FakeDatabase,
) -> bool:
    """
    Write path for cache-aside: update DB first, then invalidate.
    ALWAYS write to the DB before touching the cache. If the cache
    update fails the data is still durable. Never write cache-first.
    """
    # Step 1: Persist the update to the source of truth
    success = db.update_product(product_id, updates)
    if not success:
        return False

    # Step 2: Delete the stale cache entry.
    # Prefer DELETE over SET here: a concurrent read will re-populate
    # the cache with fresh data. Setting stale data introduces a race
    # between the write and a concurrent cache population.
    cache_key = f"product:{product_id}"
    redis.delete(cache_key)
    logging.info("Invalidated cache key: %s", cache_key)
    return True


# ============================================================
# PATTERN 2: Write-Through
# ============================================================
# Write to cache AND database synchronously in the same request.
# The cache is always consistent with the DB (no stale reads).
#
# PROS: Data is always warm in the cache. No cache miss on first
#       read after a write.
# CONS: Write latency = cache latency + DB latency (both blocking).
#       Cache may contain data that is never read (write-heavy loads).
# ============================================================

def update_product_write_through(
    product_id: int,
    updates: dict,
    redis: FakeRedis,
    db: FakeDatabase,
    ttl: int = 900,
) -> bool:
    """
    Write-through: both cache and DB are updated before returning.
    Best for read-heavy workloads where the just-written data will
    be read again soon (e.g., user profile updates).
    """
    # Write to DB first — it is the authoritative source of truth
    success = db.update_product(product_id, updates)
    if not success:
        return False

    # Fetch the complete updated row to cache it (avoids partial state)
    product = db.get_product(product_id)
    if product:
        cache_key = f"product:{product_id}"
        redis.setex(cache_key, ttl, product)
        logging.info("Write-through: updated cache key %s", cache_key)

    return True


# ============================================================
# PATTERN 3: Write-Behind (Write-Back)
# ============================================================
# Write to cache immediately (fast) and persist to DB later
# (async batch). Used when write throughput is the bottleneck.
#
# PROS: Extremely low write latency. DB batching reduces I/O.
# CONS: Data in cache is not yet in the DB — a Redis crash between
#       write and flush = data loss. Complexity: need a reliable
#       flush worker (Celery, background thread, Redis Streams).
# REAL USAGE: Session counters, view counts, rate limit buckets —
#             places where losing a few counts is acceptable.
# ============================================================

class WriteBehindBuffer:
    """
    Accumulates writes in memory (or Redis) and flushes them to
    the DB in batches. In production this would live in a Celery
    task or a Redis Stream consumer, not a plain thread.
    """

    def __init__(self, db: FakeDatabase, flush_interval: float = 5.0):
        self._pending: dict[int, dict] = {}   # product_id -> merged updates
        self._lock = threading.Lock()
        self._db = db
        self._flush_interval = flush_interval

    def write(self, product_id: int, updates: dict, redis: FakeRedis, ttl: int = 900):
        """Accept a write: update cache immediately, queue for DB."""
        # Update the cache synchronously so reads see the new data at once
        cache_key = f"product:{product_id}"
        cached = redis.get(cache_key) or {}
        cached.update(updates)
        redis.setex(cache_key, ttl, cached)

        # Merge into the pending batch — later writes overwrite earlier ones
        with self._lock:
            self._pending.setdefault(product_id, {}).update(updates)

        logging.debug("Write-behind: queued update for product %d", product_id)

    def flush(self):
        """Drain the pending queue into the DB. Called periodically."""
        with self._lock:
            batch = dict(self._pending)
            self._pending.clear()

        for product_id, updates in batch.items():
            self._db.update_product(product_id, updates)
            logging.info("Write-behind: flushed product %d to DB", product_id)


# ============================================================
# CACHE STAMPEDE (Thundering Herd) Protection
# ============================================================
# Problem: a high-traffic key expires. Before it is repopulated,
# N concurrent requests all see a miss and all query the DB.
# With N=1000 requests/s and a 10ms DB query, this creates
# 1000 simultaneous DB queries — often enough to crash it.
#
# Solution 1: Mutex lock (SET NX)
#   Only one request gets the lock. Others spin-wait briefly
#   and then hit the cache (now populated by the lock holder).
#
# Solution 2: Probabilistic Early Expiry (XFetch)
#   Occasionally refresh the cache BEFORE it expires, with
#   probability increasing as the TTL approaches zero.
#   No locks needed; background refresh keeps the key warm.
# ============================================================

def get_product_with_mutex(
    product_id: int,
    redis: FakeRedis,
    db: FakeDatabase,
    metrics: CacheMetrics,
    ttl: int = 900,
    lock_timeout: int = 5,      # Lock expires in 5s — prevents deadlock
    max_wait_ms: int = 200,     # Give up waiting after 200ms
) -> Optional[dict]:
    """
    Cache-aside with mutex (SET NX) stampede protection.

    Only the request that wins the SET NX lock queries the DB.
    All others spin-wait (up to max_wait_ms) and then retry the
    cache — by which point the winner has populated it.
    """
    cache_key = f"product:{product_id}"
    lock_key  = f"lock:product:{product_id}"

    # Fast path: cache hit (no locking needed)
    cached = redis.get(cache_key)
    if cached is not None:
        metrics.hits += 1
        return cached

    metrics.misses += 1

    # Try to acquire the mutex lock using SET NX
    lock_value = str(uuid.uuid4())      # Unique ID so only we can release it
    acquired = redis.set_nx(lock_key, lock_value, ex=lock_timeout)

    if acquired:
        # We won the lock — we are responsible for DB query + cache population
        try:
            product = db.get_product(product_id)
            if product:
                redis.setex(cache_key, ttl, product)
            return product
        finally:
            # Only release OUR lock (check the value before deleting)
            # In production this must be a Lua script for atomicity
            if redis.get(lock_key) == lock_value:
                redis.delete(lock_key)
    else:
        # Another request is populating the cache. Wait and retry.
        deadline = time.time() + max_wait_ms / 1000
        while time.time() < deadline:
            time.sleep(0.01)             # 10ms polling interval
            cached = redis.get(cache_key)
            if cached is not None:
                metrics.hits += 1        # Counted as a cache hit — it was served from cache
                return cached

        # Deadline exceeded — fall through to direct DB query as a last resort
        logging.warning("Mutex wait timeout for product %d", product_id)
        return db.get_product(product_id)


def should_refresh_early(remaining_ttl: float, delta: float, beta: float = 1.0) -> bool:
    """
    Probabilistic Early Expiry (XFetch algorithm).
    Returns True if we should proactively refresh the cache now,
    based on how expensive the recompute is (delta) and how much
    TTL is left. Beta > 1 makes early refresh more aggressive.

    Formula: current_time - (delta * beta * log(random())) > expiry_time
    Which simplifies to checking if random() < exp(-remaining_ttl / (delta * beta))
    """
    if remaining_ttl <= 0:
        return True      # Already expired — always refresh
    probability = random.random()
    threshold = (delta * beta * (-random.log(probability + 1e-9))) / remaining_ttl
    return threshold > 1.0


# ============================================================
# EVICTION POLICIES — what Redis removes when maxmemory is reached
# ============================================================
# Configure in redis.conf or via CONFIG SET maxmemory-policy <policy>
#
# allkeys-lru    → evict the least recently used key from ALL keys
#                  BEST DEFAULT for general caching workloads
# volatile-lru   → evict LRU key but ONLY among keys with a TTL set
#                  Safe if you mix persistent and ephemeral keys
# allkeys-lfu    → evict least frequently used (tracks access count)
#                  Better than LRU for highly skewed (Zipfian) access
# volatile-lfu   → LFU but only among keys with TTL
# allkeys-random → evict a random key — rarely the right choice
# volatile-ttl   → evict the key with the shortest TTL first
# noeviction     → return an error when maxmemory is hit (default)
#                  Use only when you NEVER want silent data loss
#
# NOTE: "allkeys-lru" is the recommended starting point.
# Switch to "allkeys-lfu" if your workload has a hot minority of
# keys (e.g., top 1% of products get 80% of reads).
# ============================================================

EVICTION_POLICY_GUIDE = {
    "allkeys-lru":    "General caching — evict LRU from all keys",
    "volatile-lru":   "Mixed persistent+cache data in one Redis instance",
    "allkeys-lfu":    "Skewed access (some keys much hotter than others)",
    "noeviction":     "Session store / primary data — errors > data loss",
    "volatile-ttl":   "Prefer removing keys closest to natural expiry",
}


# ============================================================
# CACHE WARMING — preloading hot keys before traffic hits
# ============================================================
# Problem: after a deploy or Redis failover the cache is empty.
# The first wave of traffic hits the DB cold. For high-QPS services
# this can cause a DB overload spike before the cache warms up.
#
# Solution: explicitly pre-populate the cache at startup.
# Source the hot key list from: analytics logs, a top-N query, or
# a static seed file maintained by the team.
# ============================================================

def warm_cache(
    product_ids: list[int],
    redis: FakeRedis,
    db: FakeDatabase,
    ttl: int = 900,
    batch_size: int = 50,       # Avoid blasting the DB; use batches
):
    """
    Warm the cache by preloading a list of known-hot product IDs.
    Called at service startup or after a Redis failover recovery.
    In production, source product_ids from an analytics table:
      SELECT product_id FROM top_products ORDER BY view_count DESC LIMIT 1000
    """
    logging.info("Cache warming: loading %d products", len(product_ids))
    loaded = 0

    for i in range(0, len(product_ids), batch_size):
        batch = product_ids[i : i + batch_size]
        for pid in batch:
            product = db.get_product(pid)
            if product:
                redis.setex(f"product:{pid}", ttl, product)
                loaded += 1
        # Brief pause between batches to avoid saturating the DB
        time.sleep(0.05)

    logging.info("Cache warming complete: %d/%d products loaded", loaded, len(product_ids))


# ============================================================
# INVALIDATION STRATEGIES
# ============================================================
# 1. Delete-on-write: simplest, most common. Delete the key when
#    the underlying data changes. Next read re-populates.
#
# 2. Versioned keys: embed a version counter in the key name.
#    product:v3:1234 → bump to product:v4:1234 on update.
#    No delete needed; old versions age out via TTL.
#    TRADE-OFF: old keys are orphaned until TTL — wastes memory.
#
# 3. Event-driven: the write service publishes a "product_updated"
#    event. A cache-invalidation consumer subscribes and deletes
#    the relevant key. Decoupled; works across microservices.
# ============================================================

def versioned_cache_key(entity: str, version: int, entity_id: int) -> str:
    """
    Build a version-embedded cache key.
    When the schema or business logic changes, bump the version
    globally (e.g., via config) and all old keys become unreachable
    without any explicit DELETE sweep.

    Example: versioned_cache_key("product", 3, 1234) → "product:v3:1234"
    """
    return f"{entity}:v{version}:{entity_id}"


# ============================================================
# WHAT NOT TO CACHE
# ============================================================
# Some data is worse cached than not:
#
# - Financial balances / inventory counts: stale values cause
#   overselling or incorrect charges. Always query the DB live,
#   or use Redis as the authoritative store (INCR/DECR).
#
# - Large user-specific objects: a 50KB serialized user session
#   for millions of users = 50GB Redis memory. Cache only the
#   hot fields, or use a dedicated session store with compression.
#
# - Rapidly changing data: if TTL < average recompute cost, the
#   cache is net negative (you're paying to cache AND for the
#   frequent DB reloads). Benchmark before caching.
#
# - Personally Identifiable Information (PII): check your
#   compliance requirements — some data must not be cached at
#   all or must be encrypted at rest in the cache.
# ============================================================

DO_NOT_CACHE = [
    "account_balance",        # Must be real-time accurate
    "inventory_count",        # Overselling risk
    "auth_token",             # Security: stale token could be revoked
    "pii_full_profile",       # GDPR / compliance risk
]


# ============================================================
# DEMO: Full cache-aside flow with stampede protection
# ============================================================

def run_demo():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    redis = FakeRedis()
    db    = FakeDatabase()
    metrics = CacheMetrics()

    print("\n=== Cache-Aside Demo ===")

    # First access — cold cache, expect a DB hit
    p = get_product_cache_aside(1, redis, db, metrics)
    print(f"First fetch  (cold):  {p['name']} | DB queries: {db.query_count}")

    # Second access — warm cache, expect a cache hit
    p = get_product_cache_aside(1, redis, db, metrics)
    print(f"Second fetch (warm):  {p['name']} | DB queries: {db.query_count}")

    print(f"Metrics after 2 reads: {metrics}")

    print("\n=== Cache Warming Demo ===")
    warm_cache(list(range(1, 11)), redis, db, ttl=900)
    db.query_count = 0   # Reset counter to measure post-warm behaviour

    # All warmed IDs should now be cache hits
    for pid in range(1, 11):
        get_product_cache_aside(pid, redis, db, metrics)

    print(f"Post-warm: DB queries for 10 reads: {db.query_count} (should be 0)")
    print(f"Final metrics: {metrics}")

    print("\n=== Write-Through Demo ===")
    update_product_write_through(1, {"price": 19.99}, redis, db)
    cached_product = redis.get("product:1")
    print(f"Price in cache after write-through: {cached_product['price']}")

    print("\n=== Invalidation Demo ===")
    invalidate_product_cache(2, {"price": 29.99}, redis, db)
    # After invalidation the key should be gone; next read will miss
    assert redis.get("product:2") is None, "Key should have been deleted"
    print("product:2 cache entry deleted after update — confirmed.")

    print("\n=== Versioned Key Demo ===")
    key_v1 = versioned_cache_key("product", 1, 42)
    key_v2 = versioned_cache_key("product", 2, 42)
    print(f"Old key: {key_v1}  →  New key after schema change: {key_v2}")

    print("\n=== Stampede Protection (Mutex) Demo ===")
    mutex_metrics = CacheMetrics()
    results = []

    def fetch_with_mutex():
        r = get_product_with_mutex(5, redis, db, mutex_metrics)
        results.append(r["name"] if r else None)

    threads = [threading.Thread(target=fetch_with_mutex) for _ in range(20)]
    pre_count = db.query_count
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    db_calls_made = db.query_count - pre_count
    print(f"20 concurrent requests for product:5 → DB calls made: {db_calls_made} (should be 1)")
    print(f"Stampede metrics: {mutex_metrics}")


if __name__ == "__main__":
    run_demo()
