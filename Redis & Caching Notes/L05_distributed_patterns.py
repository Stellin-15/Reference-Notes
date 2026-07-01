# ============================================================
# L05: Distributed Patterns with Redis
# ============================================================
# WHAT: Production-grade distributed systems patterns implemented
#       with Redis: distributed locks, session management,
#       atomic counters, deduplication, rate limiting, and
#       shared state synchronization across services.
# WHY:  Stateless microservices need shared coordination primitives.
#       Redis provides sub-millisecond atomic operations that make
#       it the standard coordination layer: every instance of your
#       service sees the same lock, the same session, the same count.
# LEVEL: Intermediate
# ============================================================
"""
CONCEPT OVERVIEW:
    Distributed Lock: mutual exclusion across multiple processes/hosts.
    The Redis SET NX PX pattern acquires a lock atomically. A unique
    token (UUID) in the value prevents a timed-out holder from
    accidentally releasing a lock acquired by a different process.
    Release MUST be done with a Lua script to compare-and-delete
    atomically — otherwise a race between GET and DEL releases
    someone else's lock.

    Redlock: consensus-based distributed lock across N independent
    Redis nodes. The lock is valid only if acquired on N/2+1 nodes
    within a time window. Survives single-node failure. Use the
    redlock-py library in production.

    Session Management: Redis HASH stores session fields (user_id,
    email, roles, device). EXPIRE extends TTL on each request
    (sliding expiry). HSETNX for atomic set-if-absent. On privilege
    escalation (login → admin), rotate the session ID to prevent
    session fixation attacks.

    Distributed Counter: Redis INCR is atomic across all instances.
    No application-level locking required. INCRBY for batch increments.
    GETDEL for read-and-reset (e.g., flush page view count to DB).

    Deduplication: SETNX processed:{msg_id} + EXPIRE implements
    exactly-once processing. If the key already exists, the message
    was already processed — skip it. The TTL prevents the dedup set
    from growing unbounded.

    Shared State: one service publishes changes to Redis (SET or
    PUBLISH). Other services subscribe or poll. Eliminates the need
    for all services to share a DB table for coordination.

PRODUCTION USE CASE:
    E-commerce checkout:
      - Distributed lock on inventory:{sku} prevents overselling when
        two users buy the last item simultaneously (race condition).
      - Session store: HSET session:{uuid} with cart, user, preferences.
        Shared across API gateway, checkout service, recommendation service.
      - Payment deduplication: SETNX dedup:payment:{idempotency_key}
        prevents double-charging if the client retries the request.
      - Page view counters: INCR view:{product_id}:daily flushed to
        the DB every 5 minutes by a background worker (GETDEL).

COMMON MISTAKES:
    1. SET NX without an expiry (PX/EX): if the lock holder crashes,
       the lock is never released — deadlock forever.
    2. Releasing the lock without checking the value: if lock A expires
       and B acquires it, then A completes and does a plain DEL — it
       deletes B's lock, not its own.
    3. Setting lock timeout < critical section duration: the lock expires
       while the holder is still in the critical section. Another process
       acquires it — now two processes are in the section simultaneously.
    4. Using SETNX for deduplication without EXPIRE: the dedup set grows
       to billions of entries and Redis runs out of memory.
    5. Session fixation: not rotating the session ID after privilege
       escalation — an attacker who stole the pre-login session ID now
       has an authenticated session.
    6. Using INCR for financial values (balances): INCR has no atomicity
       across the read-modify-write of a decimal. Use MULTI/EXEC or Lua.
    7. Single-Redis distributed lock for genuinely critical resources:
       if the Redis node fails, all locks are lost. Use Redlock for
       true high-availability lock semantics.
"""

import time
import uuid
import random
import threading
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional, Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


# ============================================================
# MINIMAL REDIS SIMULATION
# ============================================================
# In production, replace FakeRedis with redis.Redis(...) and
# use the redis-py methods shown in each docstring.
# ============================================================

class FakeRedis:
    """Thread-safe in-memory Redis simulation."""

    def __init__(self):
        self._store: dict[str, tuple[Any, Optional[float]]] = {}
        self._hstore: dict[str, dict[str, str]] = {}
        self._counters: dict[str, int] = {}
        self._lock = threading.Lock()

    def _is_expired(self, key: str) -> bool:
        entry = self._store.get(key)
        if entry is None:
            return True
        _, expires_at = entry
        if expires_at and time.time() > expires_at:
            del self._store[key]
            return True
        return False

    def get(self, key: str) -> Optional[str]:
        """GET key"""
        with self._lock:
            if self._is_expired(key):
                return None
            entry = self._store.get(key)
            return entry[0] if entry else None

    def set(self, key: str, value: str, ex: Optional[int] = None,
            px: Optional[int] = None, nx: bool = False) -> Optional[bool]:
        """
        SET key value [EX seconds | PX milliseconds] [NX]
        Returns True on success, None if NX condition not met.
        redis-py: r.set(key, value, ex=30, nx=True)
        """
        with self._lock:
            # Check NX (set only if not exists)
            if nx:
                entry = self._store.get(key)
                if entry is not None:
                    _, expires_at = entry
                    if expires_at is None or time.time() < expires_at:
                        return None    # Key exists — NX condition fails

            # Determine expiry
            expires_at = None
            if ex is not None:
                expires_at = time.time() + ex
            elif px is not None:
                expires_at = time.time() + px / 1000.0

            self._store[key] = (value, expires_at)
            return True

    def delete(self, *keys: str) -> int:
        """DEL key [key ...]"""
        with self._lock:
            count = 0
            for key in keys:
                if self._store.pop(key, None) is not None or \
                   self._hstore.pop(key, None) is not None or \
                   key in self._counters:
                    self._counters.pop(key, None)
                    count += 1
            return count

    def expire(self, key: str, seconds: int) -> int:
        """EXPIRE key seconds  →  1 if set, 0 if key not found"""
        with self._lock:
            if key in self._store:
                val, _ = self._store[key]
                self._store[key] = (val, time.time() + seconds)
                return 1
            if key in self._hstore:
                # For HASH keys track expiry separately (simplified)
                self._store[f"__hexpiry__{key}"] = ("1", time.time() + seconds)
                return 1
            return 0

    # ---- HASH commands ----

    def hset(self, key: str, mapping: dict[str, str]) -> int:
        """HSET key field value [field value ...]  →  number of new fields added"""
        with self._lock:
            if key not in self._hstore:
                self._hstore[key] = {}
            new_fields = 0
            for f, v in mapping.items():
                if f not in self._hstore[key]:
                    new_fields += 1
                self._hstore[key][f] = str(v)
            return new_fields

    def hget(self, key: str, field: str) -> Optional[str]:
        """HGET key field"""
        with self._lock:
            return self._hstore.get(key, {}).get(field)

    def hgetall(self, key: str) -> dict[str, str]:
        """HGETALL key  →  all fields and values as a dict"""
        with self._lock:
            return dict(self._hstore.get(key, {}))

    def hdel(self, key: str, *fields: str) -> int:
        """HDEL key field [field ...]  →  number of fields removed"""
        with self._lock:
            h = self._hstore.get(key, {})
            count = 0
            for f in fields:
                if h.pop(f, None) is not None:
                    count += 1
            return count

    def hsetnx(self, key: str, field: str, value: str) -> int:
        """HSETNX key field value  →  1 if set, 0 if field already exists"""
        with self._lock:
            h = self._hstore.setdefault(key, {})
            if field in h:
                return 0
            h[field] = str(value)
            return 1

    # ---- Counter commands ----

    def incr(self, key: str) -> int:
        """INCR key  →  new value (atomic increment by 1)"""
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + 1
            return self._counters[key]

    def incrby(self, key: str, amount: int) -> int:
        """INCRBY key amount  →  new value"""
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + amount
            return self._counters[key]

    def getdel(self, key: str) -> Optional[int]:
        """
        GETDEL key  →  value then delete atomically (Redis 6.2+)
        Used for read-and-reset counters.
        redis-py: r.getdel(key)
        """
        with self._lock:
            val = self._counters.pop(key, None)
            return val

    def incrbyfloat(self, key: str, amount: float) -> float:
        """INCRBYFLOAT key amount  →  new float value"""
        with self._lock:
            current = float(self._counters.get(key, 0))
            new_val = current + amount
            self._counters[key] = new_val
            return new_val


# ============================================================
# PATTERN 1: DISTRIBUTED LOCK
# ============================================================
# Acquire:  SET lock:{resource} {unique_id} NX PX 30000
#   NX  = only set if key does not exist (atomic check-and-set)
#   PX  = expire in 30,000ms (prevents deadlock on crash)
#
# Release:  Lua script — compare value, DELETE only if match
#   Without Lua, the GET + DEL has a race: another holder could
#   acquire the lock between your GET and DEL, and you'd delete theirs.
#
# Rule: lock timeout MUST be longer than the worst-case duration
# of the critical section, INCLUDING any downstream I/O (DB, API).
# ============================================================

LOCK_RELEASE_LUA = """
-- KEYS[1] = lock key
-- ARGV[1] = our unique lock token
-- Returns 1 if we released the lock, 0 if it wasn't ours
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""

class DistributedLock:
    """
    Redis-backed distributed mutex lock using SET NX PX.
    Usage:
        lock = DistributedLock(redis, "inventory:SKU-001", ttl_ms=5000)
        with lock:
            # Only one process in this block at a time
            reserve_inventory(...)

    In production: use the rediscluster or redlock-py library for
    Redlock (multi-node consensus lock) when single-Redis is insufficient.
    """

    def __init__(
        self,
        redis: FakeRedis,
        resource: str,
        ttl_ms: int = 30_000,      # Lock expires in 30s if holder crashes
        retry_delay_ms: int = 50,  # Wait 50ms between acquisition retries
        max_retries: int = 20,     # Give up after 20 retries (~1s)
    ):
        self.redis = redis
        self.lock_key = f"lock:{resource}"
        self.ttl_ms = ttl_ms
        self.retry_delay_ms = retry_delay_ms
        self.max_retries = max_retries
        self._token: Optional[str] = None    # Our unique lock token

    def acquire(self) -> bool:
        """
        Attempt to acquire the lock. Retries up to max_retries times.
        Returns True if acquired, False if not (lock held by another).

        redis-py: result = r.set(self.lock_key, token, nx=True, px=self.ttl_ms)
        """
        token = str(uuid.uuid4())    # Unique per lock acquisition attempt
        for attempt in range(self.max_retries):
            # SET lock_key token NX PX ttl_ms — atomic check-and-set
            result = self.redis.set(self.lock_key, token, px=self.ttl_ms, nx=True)
            if result:
                self._token = token
                logging.debug("Lock '%s' acquired (attempt %d)", self.lock_key, attempt + 1)
                return True
            # Lock held by another — wait and retry
            time.sleep(self.retry_delay_ms / 1000)

        logging.warning("Failed to acquire lock '%s' after %d retries", self.lock_key, self.max_retries)
        return False

    def release(self):
        """
        Release the lock using a compare-and-delete operation.
        MUST check that the token matches before deleting — prevents
        releasing a lock we no longer own (timed out and re-acquired by another).

        In real Redis this runs as EVAL LOCK_RELEASE_LUA 1 key token.
        redis-py: script = r.register_script(LOCK_RELEASE_LUA)
                  script(keys=[self.lock_key], args=[self._token])
        """
        if not self._token:
            return

        # Simulate the Lua compare-and-delete (atomic in real Redis)
        current = self.redis.get(self.lock_key)
        if current == self._token:
            self.redis.delete(self.lock_key)
            logging.debug("Lock '%s' released", self.lock_key)
        else:
            logging.warning(
                "Lock '%s' was NOT ours (token mismatch) — already expired and re-acquired?",
                self.lock_key,
            )
        self._token = None

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(f"Could not acquire lock: {self.lock_key}")
        return self

    def __exit__(self, *_):
        self.release()


def demonstrate_inventory_lock(redis: FakeRedis):
    """
    Simulate two concurrent threads trying to reserve the last unit
    of inventory. Without a lock, both would succeed (overselling).
    With a lock, only one succeeds.
    """
    inventory = {"SKU-001": 1}   # Only 1 unit left
    sold_to = []

    def try_purchase(buyer: str):
        lock = DistributedLock(redis, "inventory:SKU-001", ttl_ms=5000)
        try:
            with lock:
                # Critical section: read, check, decrement
                current_stock = inventory["SKU-001"]
                time.sleep(0.01)    # Simulate DB read latency
                if current_stock > 0:
                    inventory["SKU-001"] -= 1
                    sold_to.append(buyer)
                    logging.info("Sold to %s (stock now %d)", buyer, inventory["SKU-001"])
                else:
                    logging.info("%s: out of stock", buyer)
        except RuntimeError as e:
            logging.warning("%s could not acquire lock: %s", buyer, e)

    threads = [threading.Thread(target=try_purchase, args=(f"buyer_{i}",)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(sold_to) <= 1, f"OVERSELL DETECTED: sold to {sold_to}"
    print(f"\nInventory lock result: sold to {sold_to or ['nobody (all failed)']}")
    print(f"Remaining stock: {inventory['SKU-001']} (should be 0 or 1)")


# ============================================================
# PATTERN 2: SESSION MANAGEMENT
# ============================================================
# Store session data as a Redis HASH. Each field is a session attribute.
# Use EXPIRE with sliding window (reset on each request).
#
# Key: session:{uuid}
# Fields: user_id, email, roles, device, created_at, last_seen
#
# Rotate the session ID on privilege escalation (sudo, login):
#   1. HGETALL old_session_key
#   2. HSET new_session_key <all fields>
#   3. DEL old_session_key
#   This prevents session fixation — an attacker who stole the
#   pre-login session ID cannot use it after login completes.
# ============================================================

SESSION_TTL = 3600    # 1 hour — reset on each request (sliding expiry)

class SessionStore:
    """
    Redis-backed session store using HASH commands.
    Sessions expire after SESSION_TTL seconds of inactivity.
    """

    def __init__(self, redis: FakeRedis):
        self.redis = redis

    def create(self, user_id: str, email: str, roles: list[str]) -> str:
        """
        Create a new session. Returns the session ID (UUID).

        redis-py:
            session_id = str(uuid.uuid4())
            r.hset(f"session:{session_id}", mapping={...})
            r.expire(f"session:{session_id}", SESSION_TTL)
        """
        session_id = str(uuid.uuid4())
        key = f"session:{session_id}"
        self.redis.hset(key, {
            "user_id":    user_id,
            "email":      email,
            "roles":      ",".join(roles),
            "created_at": str(int(time.time())),
            "last_seen":  str(int(time.time())),
        })
        self.redis.expire(key, SESSION_TTL)
        logging.info("Session created: %s for user %s", session_id, user_id)
        return session_id

    def load(self, session_id: str) -> Optional[dict]:
        """
        Load and refresh a session. Resets TTL (sliding expiry).
        Returns None if session not found or expired.

        redis-py:
            data = r.hgetall(f"session:{session_id}")
            r.hset(f"session:{session_id}", "last_seen", int(time.time()))
            r.expire(f"session:{session_id}", SESSION_TTL)
        """
        key = f"session:{session_id}"
        data = self.redis.hgetall(key)
        if not data:
            return None     # Session expired or never existed

        # Update last_seen and slide the expiry window forward
        self.redis.hset(key, {"last_seen": str(int(time.time()))})
        self.redis.expire(key, SESSION_TTL)
        return data

    def update_field(self, session_id: str, field: str, value: str):
        """
        Update a single session field without reloading the whole session.
        redis-py: r.hset(f"session:{session_id}", field, value)
        """
        self.redis.hset(f"session:{session_id}", {field: value})

    def remove_field(self, session_id: str, field: str):
        """
        Remove a field from the session hash.
        redis-py: r.hdel(f"session:{session_id}", field)
        """
        self.redis.hdel(f"session:{session_id}", field)

    def rotate(self, old_session_id: str) -> str:
        """
        Rotate the session ID on privilege escalation.
        Old session is destroyed; data is copied to a new UUID.

        This prevents session fixation: an attacker who pre-captured
        the session ID cannot elevate privileges with it.

        redis-py:
            old_data = r.hgetall(old_key)
            new_id = str(uuid.uuid4())
            r.hset(new_key, mapping=old_data)
            r.expire(new_key, SESSION_TTL)
            r.delete(old_key)
        """
        old_key = f"session:{old_session_id}"
        data = self.redis.hgetall(old_key)
        if not data:
            raise ValueError(f"Session {old_session_id} not found")

        new_session_id = str(uuid.uuid4())
        new_key = f"session:{new_session_id}"
        self.redis.hset(new_key, data)
        self.redis.expire(new_key, SESSION_TTL)
        self.redis.delete(old_key)

        logging.info("Session rotated: %s → %s", old_session_id, new_session_id)
        return new_session_id

    def destroy(self, session_id: str):
        """Logout: immediately invalidate the session."""
        self.redis.delete(f"session:{session_id}")
        logging.info("Session destroyed: %s", session_id)


# ============================================================
# PATTERN 3: DISTRIBUTED COUNTER
# ============================================================
# INCR is atomic in Redis — safe across all instances with no
# application-level locking. Every instance increments the same key.
#
# INCRBY for batch increments (e.g., flush local buffer to Redis).
# GETDEL for read-and-reset: atomically read the current value
#         and reset to 0 (e.g., flush page views to the DB).
# INCRBYFLOAT for fractional values (e.g., revenue tracking).
#
# WARNING: Do NOT use INCR for financial account balances. Balances
# require DB-level transactions for audit trails and consistency.
# ============================================================

class DistributedCounter:
    """
    Atomic distributed counter using Redis INCR/INCRBY/GETDEL.
    All increments are atomic — safe from multiple processes simultaneously.
    """

    def __init__(self, redis: FakeRedis, namespace: str = "counters"):
        self.redis = redis
        self.namespace = namespace

    def _key(self, name: str) -> str:
        return f"{self.namespace}:{name}"

    def increment(self, name: str, by: int = 1) -> int:
        """
        Atomically increment a counter.
        redis-py: return r.incrby(key, by)
        """
        if by == 1:
            return self.redis.incr(self._key(name))
        return self.redis.incrby(self._key(name), by)

    def read_and_reset(self, name: str) -> int:
        """
        Atomically read the current value and reset to 0.
        Used by background workers to flush counters to persistent storage.

        redis-py: return r.getdel(key) or 0
        """
        val = self.redis.getdel(self._key(name))
        return val if val is not None else 0

    def increment_float(self, name: str, amount: float) -> float:
        """
        Atomically add a float value to the counter.
        redis-py: return r.incrbyfloat(key, amount)
        """
        return self.redis.incrbyfloat(self._key(name), amount)


# ============================================================
# PATTERN 4: DISTRIBUTED DEDUPLICATION
# ============================================================
# Problem: idempotent processing — the same message may arrive
# more than once (network retry, at-least-once delivery).
# Solution: SETNX processed:{msg_id} 1, EXPIRE 24h.
#   If SETNX returns 1 → first time we've seen this message → process.
#   If SETNX returns 0 → duplicate → skip.
#
# TTL choice: must be longer than the maximum retry window.
# For payment idempotency keys, 24h is typical.
# For event deduplication, 7 days may be needed.
#
# At scale: consider a Bloom filter for approximate deduplication
# with sub-millisecond lookup and zero false negatives (only
# false positives → recheck the source). See pybloom-live library.
# ============================================================

class MessageDeduplicator:
    """
    Prevents duplicate message processing using Redis SETNX.
    Guarantees at-most-once processing when combined with
    correct consumer acknowledgment (see Streams L04).
    """

    def __init__(self, redis: FakeRedis, ttl_seconds: int = 86400):
        self.redis = redis
        self.ttl = ttl_seconds    # 24h default

    def is_new(self, message_id: str, namespace: str = "dedup") -> bool:
        """
        Returns True if this message_id has NOT been seen before
        (and marks it as seen). Returns False if it is a duplicate.

        redis-py:
            result = r.set(f"{namespace}:{message_id}", "1", nx=True, ex=self.ttl)
            return result is not None  # None means NX failed (already exists)
        """
        key = f"{namespace}:{message_id}"
        result = self.redis.set(key, "1", ex=self.ttl, nx=True)
        return result is not None   # True = set succeeded = first occurrence

    def mark_processed(self, message_id: str, namespace: str = "dedup"):
        """
        Explicitly mark a message as processed without the is_new check.
        Use when dedup check and processing are not in the same call.
        """
        key = f"{namespace}:{message_id}"
        self.redis.set(key, "1", ex=self.ttl)


# ============================================================
# PATTERN 5: ATOMIC SLIDING WINDOW RATE LIMITER (LUA)
# ============================================================
# Full Lua implementation for atomic sliding window rate limiting.
# This is the production-ready version — the non-Lua version in
# L03 has a race condition between ZREMRANGEBYSCORE and ZADD.
#
# The Lua script runs atomically (single-threaded in Redis):
#   1. Remove timestamps older than the window
#   2. Count remaining timestamps
#   3. If under limit: add current timestamp + EXPIRE
#   4. Return 1 (allowed) or 0 (rejected)
# ============================================================

SLIDING_WINDOW_LUA = """
-- KEYS[1] = rate limit key, e.g. "rl:user:42"
-- ARGV[1] = limit (max requests per window)
-- ARGV[2] = window size in seconds
-- ARGV[3] = current timestamp (float, from time.time())
-- ARGV[4] = unique request ID (prevents duplicate members)

local key    = KEYS[1]
local limit  = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now    = tonumber(ARGV[3])
local req_id = ARGV[4]

-- Remove requests older than the window
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

-- Count requests within the window
local count = tonumber(redis.call('ZCARD', key))

if count < limit then
    -- Record this request with its unique ID as member
    redis.call('ZADD', key, now, req_id)
    -- Reset TTL so idle users' keys expire automatically
    redis.call('EXPIRE', key, window)
    return {1, count + 1}   -- {allowed, new_count}
else
    return {0, count}       -- {rejected, current_count}
end
"""


class AtomicRateLimiter:
    """
    Production-grade atomic sliding window rate limiter.
    The Lua script eliminates the race condition present in
    the non-atomic version (see L03_sorted_sets_and_advanced.py).

    In production:
        script = r.register_script(SLIDING_WINDOW_LUA)
        result = script(
            keys=[f"rl:{user_id}"],
            args=[limit, window, time.time(), str(uuid.uuid4())]
        )
        allowed, count = result[0], result[1]
    """

    def __init__(self, redis: FakeRedis, limit: int, window_seconds: int):
        self.redis = redis
        self.limit = limit
        self.window = window_seconds
        # Simulate the Lua script with a regular Python dict (single-threaded demo)
        self._zsets: dict[str, list[tuple[float, str]]] = {}
        self._lock = threading.Lock()

    def check(self, user_id: str) -> tuple[bool, int]:
        """
        Atomically check and record a rate-limit request.
        Returns (allowed: bool, current_count: int).
        """
        key = f"rl:{user_id}"
        now = time.time()
        req_id = str(uuid.uuid4())

        with self._lock:
            # ZREMRANGEBYSCORE: prune old entries
            if key in self._zsets:
                self._zsets[key] = [
                    (ts, rid) for ts, rid in self._zsets[key]
                    if ts > now - self.window
                ]
            else:
                self._zsets[key] = []

            count = len(self._zsets[key])

            if count < self.limit:
                self._zsets[key].append((now, req_id))
                return True, count + 1
            else:
                return False, count


# ============================================================
# PATTERN 6: SHARED STATE BETWEEN SERVICES
# ============================================================
# Problem: Service A computes a result that Service B needs.
# Without Redis: B queries A's DB directly (coupling) or A writes
# to a shared DB table (latency).
# With Redis: A publishes state to Redis. B reads from Redis.
# Changes propagate in microseconds.
#
# Pattern variants:
#   a) SET/GET: B polls Redis for A's state (simple, polling delay)
#   b) PUBLISH: A publishes a change event; B subscribes and
#      updates its local cache (real-time, see Pub/Sub in L03)
#   c) HSET: A writes a HASH; B reads specific fields (partial reads)
# ============================================================

class FeatureFlagStore:
    """
    Shared feature flags stored in Redis HASH.
    All services read from the same Redis key — no deployment needed
    to toggle a feature. Changes take effect in < 1ms.
    """

    FLAG_KEY = "feature_flags"

    def __init__(self, redis: FakeRedis):
        self.redis = redis

    def set_flag(self, flag: str, enabled: bool):
        """Enable or disable a feature flag across all services instantly."""
        self.redis.hset(self.FLAG_KEY, {flag: "1" if enabled else "0"})
        logging.info("Feature flag '%s' set to %s", flag, enabled)

    def is_enabled(self, flag: str) -> bool:
        """Check if a feature is enabled. All services share this state."""
        val = self.redis.hget(self.FLAG_KEY, flag)
        return val == "1"

    def get_all(self) -> dict[str, bool]:
        """Load all feature flags in one HGETALL round-trip."""
        raw = self.redis.hgetall(self.FLAG_KEY)
        return {k: v == "1" for k, v in raw.items()}


# ============================================================
# REDLOCK ALGORITHM (CONCEPT)
# ============================================================
# For true distributed locking across a Redis cluster:
# 1. Get current timestamp T1.
# 2. Try to acquire the lock on N independent Redis nodes using
#    SET NX PX with the same key and token.
# 3. Lock is acquired if N/2+1 nodes succeed AND total elapsed
#    time < lock TTL (to account for network delays).
# 4. Effective TTL = initial TTL - (T2 - T1).
# 5. On failure: release on all nodes (including partial acquires).
#
# Use the 'redlock-py' library in production:
#   from redlock import RedLockFactory
#   factory = RedLockFactory(connection_details=[
#       {"host": "redis1"},
#       {"host": "redis2"},
#       {"host": "redis3"},
#   ])
#   with factory.create_lock("my_resource", ttl=10000):
#       # Critical section
# ============================================================

@dataclass
class RedlockConcept:
    """
    Pseudo-code illustration of the Redlock algorithm.
    Does NOT implement real networking — shows the logic only.
    In production: use the 'redlock-py' or 'pottery' library.
    """
    nodes: list            # List of independent Redis instances
    resource: str
    ttl_ms: int = 30_000

    def acquire(self) -> bool:
        token = str(uuid.uuid4())
        quorum = len(self.nodes) // 2 + 1    # Majority required
        start_time = time.time()

        acquired_on = []
        for node in self.nodes:
            # result = node.set(f"lock:{self.resource}", token, nx=True, px=self.ttl_ms)
            # Simulated — in reality each call goes to a different Redis server
            if random.random() > 0.2:    # 80% success per node (simulation)
                acquired_on.append(node)

        elapsed_ms = (time.time() - start_time) * 1000
        effective_ttl = self.ttl_ms - elapsed_ms

        if len(acquired_on) >= quorum and effective_ttl > 0:
            logging.info(
                "Redlock acquired on %d/%d nodes (TTL=%.0fms)",
                len(acquired_on), len(self.nodes), effective_ttl,
            )
            return True

        # Failed to reach quorum — release partial locks
        for node in acquired_on:
            pass   # node.delete(f"lock:{self.resource}") [if token matches]

        logging.warning(
            "Redlock failed: only %d/%d nodes (quorum=%d)",
            len(acquired_on), len(self.nodes), quorum,
        )
        return False


# ============================================================
# DEMO
# ============================================================

def run_demo():
    print("\n=== Distributed Lock: Inventory Reservation ===")
    redis = FakeRedis()
    demonstrate_inventory_lock(redis)

    print("\n=== Session Management Demo ===")
    sessions = SessionStore(redis)
    sid = sessions.create("user_42", "alice@example.com", ["buyer", "seller"])
    data = sessions.load(sid)
    print(f"Session loaded: user={data['user_id']} email={data['email']} roles={data['roles']}")

    # Add a cart field
    sessions.update_field(sid, "cart_id", "CART-8899")
    data = sessions.load(sid)
    print(f"Session with cart: cart_id={data.get('cart_id')}")

    # Rotate session ID after login → admin escalation
    new_sid = sessions.rotate(sid)
    assert sessions.load(sid) is None,     "Old session should be gone"
    assert sessions.load(new_sid) is not None, "New session should exist"
    print(f"Session rotated: old={sid[:8]}... → new={new_sid[:8]}...")

    sessions.destroy(new_sid)
    assert sessions.load(new_sid) is None, "Destroyed session should be gone"
    print("Session destroyed — confirmed gone")

    print("\n=== Distributed Counter Demo ===")
    counters = DistributedCounter(redis)
    # Simulate 10 concurrent services incrementing a page view counter
    threads = [threading.Thread(target=lambda: counters.increment("views:product:42"))
               for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = counters.read_and_reset("views:product:42")
    print(f"Page views after 10 concurrent increments: {total} (should be 10)")
    assert counters.read_and_reset("views:product:42") == 0, "Counter should be 0 after GETDEL"
    print("Counter reset to 0 after read_and_reset — confirmed")

    revenue = 0.0
    for _ in range(5):
        revenue = counters.increment_float("revenue:today", round(random.uniform(9.99, 99.99), 2))
    print(f"Accumulated float revenue: ${revenue:.2f}")

    print("\n=== Deduplication Demo ===")
    dedup = MessageDeduplicator(redis, ttl_seconds=60)
    msg_id = "PAY-" + str(uuid.uuid4())

    result1 = dedup.is_new(msg_id, "payments")
    result2 = dedup.is_new(msg_id, "payments")   # Same ID — should be False
    result3 = dedup.is_new(msg_id, "payments")   # Same ID again

    print(f"First  attempt: {'PROCESS' if result1 else 'DUPLICATE'} (expected: PROCESS)")
    print(f"Second attempt: {'PROCESS' if result2 else 'DUPLICATE'} (expected: DUPLICATE)")
    print(f"Third  attempt: {'PROCESS' if result3 else 'DUPLICATE'} (expected: DUPLICATE)")

    print("\n=== Atomic Rate Limiter Demo ===")
    limiter = AtomicRateLimiter(redis, limit=3, window_seconds=10)
    print("Rate limit: 3 requests per 10 seconds")
    for i in range(6):
        allowed, count = limiter.check("user_99")
        status = "ALLOWED" if allowed else "REJECTED"
        print(f"  Request {i+1}: {status} (window count={count})")

    print("\n=== Feature Flags (Shared State) Demo ===")
    flags = FeatureFlagStore(redis)
    flags.set_flag("new_checkout_flow", True)
    flags.set_flag("dark_mode",         False)
    flags.set_flag("ai_recommendations", True)

    all_flags = flags.get_all()
    print("Current feature flags (shared across all services):")
    for flag, enabled in all_flags.items():
        print(f"  {flag:<25s}  {'ON' if enabled else 'OFF'}")

    # Toggle a flag — all services see the change immediately
    flags.set_flag("dark_mode", True)
    print(f"\nAfter toggling dark_mode: {flags.is_enabled('dark_mode')} (should be True)")

    print("\n=== Redlock Concept Demo ===")
    fake_nodes = ["redis1", "redis2", "redis3", "redis4", "redis5"]
    rlock = RedlockConcept(fake_nodes, "critical_job_scheduler", ttl_ms=5000)
    for attempt in range(3):
        acquired = rlock.acquire()
        print(f"  Redlock attempt {attempt+1}: {'ACQUIRED' if acquired else 'FAILED'}")

    print("\n=== Why unique_id in lock matters ===")
    print("""
Scenario WITHOUT unique ID (bug):
  T=0s  Process A acquires lock (plain DEL on release)
  T=5s  Lock expires (A still running — it took longer than TTL)
  T=5s  Process B acquires lock (lock was free)
  T=6s  Process A finishes, calls DEL lock:{resource}
         → A just deleted B's lock!
  T=6s  Process C acquires lock simultaneously with B
         → Two processes now in the critical section → data corruption

Scenario WITH unique ID (correct):
  T=0s  A acquires lock, value = "uuid-A"
  T=5s  Lock expires
  T=5s  B acquires lock, value = "uuid-B"
  T=6s  A calls Lua: GET lock → "uuid-B" ≠ "uuid-A" → DO NOT DELETE
         → A's release is a no-op → B's lock is safe
    """)


if __name__ == "__main__":
    run_demo()
