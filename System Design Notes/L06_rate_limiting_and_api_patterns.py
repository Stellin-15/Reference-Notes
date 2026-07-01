# =============================================================================
# WHAT:  Rate Limiting, Idempotency, and API Design Patterns
# WHY:   Without rate limiting, a single bad actor (or bug) can take down
#        your API for everyone. Idempotency prevents double charges and
#        duplicate records. These patterns make APIs robust and safe.
# LEVEL: Intermediate (assumes REST APIs, Redis basics, HTTP knowledge)
# =============================================================================

# =============================================================================
# CONCEPT OVERVIEW
# =============================================================================
# Rate limiting enforces how many requests a client can make in a time window.
#
# WHY RATE LIMIT?
#   - Protect from abuse (scrapers, DDoS, buggy clients in tight loops)
#   - Enforce SaaS pricing tiers (free: 100/day, pro: 10,000/day)
#   - Protect downstream services from overload
#   - Fair use across all customers
#
# DIMENSIONS you can rate limit by:
#   - Per user ID (authenticated requests)
#   - Per IP address (anonymous requests)
#   - Per API key (SaaS billing)
#   - Global (protect your entire backend regardless of who's calling)
#   - Per endpoint (stricter on /payments than /profile)
#
# ALGORITHMS:
#   Token Bucket     — allows bursts, common in practice
#   Sliding Window   — accurate, no edge-case spikes
#   Fixed Window     — simplest, has double-spend edge case
#   Leaky Bucket     — smooths output rate, not burst input
#
# IDEMPOTENCY: making an operation safe to retry without side effects.
#   Client generates UUID → server stores result by UUID → if UUID seen again,
#   return cached result. Critical for: payments, order creation, emails.
# =============================================================================

# =============================================================================
# PRODUCTION USE CASE
# =============================================================================
# Stripe's API rate limiting:
#   - 100 req/s per API key (token bucket with burst)
#   - Returns 429 with Retry-After header
#   - All API servers share Redis for rate limit state
#   - Idempotency-Key header required for POST /charges (prevents double charge)
#   - Idempotency key stored 24h — same key always returns same result
#
# Architecture:
#   Client → Load Balancer → [API Server 1, 2, 3]
#                                    ↕ shared state
#                                  [Redis Cluster]
#   Without shared Redis: rate limits would be per-server, not global.
#   10 servers with 100 req/s limit each = 1000 req/s actual, not 100.
# =============================================================================

# =============================================================================
# COMMON MISTAKES
# =============================================================================
# 1. Rate limiting in application code without shared state — per-server limits
#    instead of global. Fix: use Redis for shared counters.
# 2. Fixed window at minute boundaries: allow 2x limit in 2 seconds at boundary.
#    Fix: use sliding window for accuracy.
# 3. No Retry-After header on 429 — clients don't know when to retry, so
#    they retry immediately, making the problem worse.
# 4. Retrying non-idempotent operations (POST /charges) — causes double charge.
#    Fix: idempotency keys for all state-changing operations.
# 5. Consistent hashing: using simple hash(key)%N means changing N remaps 90%+
#    of keys. Consistent hashing remaps only K/N keys. Critical for live systems.
# =============================================================================


import time
import uuid
import hmac
import hashlib
import json
import threading
from collections import deque, defaultdict
from typing import Optional, Any, Callable
from dataclasses import dataclass, field


# =============================================================================
# ALGORITHM 1: TOKEN BUCKET
# =============================================================================
# Metaphor: a bucket that holds N tokens. Tokens refill at R per second.
# Each request consumes 1 token. If bucket is empty → 429.
#
# PROPERTIES:
#   - Allows BURST traffic up to bucket capacity
#   - Smooth average rate enforced by refill rate
#   - Example: capacity=10, refill=2/s
#     → can burst 10 requests instantly, then 2/s sustained
#
# REDIS implementation:
#   Use Lua script for atomic check-and-update (prevents race conditions).
#   KEYS[1] = rate limit key, ARGV[1] = capacity, ARGV[2] = refill_rate
#
# LUA SCRIPT (reference, not executable here):
#   local tokens = tonumber(redis.call('GET', KEYS[1])) or ARGV[1]
#   local now = tonumber(ARGV[3])
#   local last = tonumber(redis.call('GET', KEYS[1] .. ':ts')) or now
#   local refill = (now - last) * tonumber(ARGV[2])
#   tokens = math.min(tonumber(ARGV[1]), tokens + refill)
#   if tokens >= 1 then
#     redis.call('SET', KEYS[1], tokens - 1)
#     redis.call('SET', KEYS[1] .. ':ts', now)
#     return 1  -- allowed
#   else
#     return 0  -- rejected
#   end

class TokenBucket:
    """
    In-memory token bucket rate limiter (single process).
    For distributed use: replace with Redis Lua script for atomicity.
    """
    def __init__(self, capacity: int, refill_rate: float):
        """
        Args:
            capacity:    max tokens (burst limit)
            refill_rate: tokens added per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._tokens = float(capacity)
        self._last_refill = time.time()
        self._lock = threading.Lock()

    def _refill(self):
        """Add tokens based on elapsed time. Called before every check."""
        now = time.time()
        elapsed = now - self._last_refill
        new_tokens = elapsed * self.refill_rate
        self._tokens = min(self.capacity, self._tokens + new_tokens)
        self._last_refill = now

    def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens. Returns True if allowed, False if rate-limited.
        Thread-safe via lock (in Redis version: Lua script is atomic).
        """
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def tokens_remaining(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens


# =============================================================================
# ALGORITHM 2: SLIDING WINDOW COUNTER
# =============================================================================
# More accurate than fixed window, less memory than sliding log.
# Divide the window into small buckets (e.g., 60 one-second buckets for 1-min window).
# Count requests in all buckets that fall within the window.
# Weighted edge bucket: partial credit for the current partial second.
#
# Example: 100 req/min limit. At 12:00:30.500 (halfway through second 30):
#   Sum buckets from 11:59:31 to 12:00:30 (full buckets)
#   + 0.5 * bucket[12:00:30] (half-weight for current partial second)
#
# MEMORY: O(window_size / bucket_size) — fixed, not growing with traffic.

class SlidingWindowCounter:
    """
    Sliding window counter rate limiter using time-bucketed counters.
    Redis implementation: HASH with bucket timestamps as fields,
    expire old buckets with HDEL or separate TTL management.
    """
    def __init__(self, limit: int, window_seconds: int, bucket_seconds: int = 1):
        """
        Args:
            limit:          max requests allowed in window
            window_seconds: rolling window size (e.g., 60 for per-minute)
            bucket_seconds: resolution of each bucket (e.g., 1 second)
        """
        self.limit = limit
        self.window_seconds = window_seconds
        self.bucket_seconds = bucket_seconds
        # key → {bucket_timestamp: count}
        self._counters: dict[str, dict[int, int]] = defaultdict(dict)
        self._lock = threading.Lock()

    def _current_bucket(self) -> int:
        """Current bucket timestamp (floored to bucket_seconds boundary)."""
        return int(time.time() // self.bucket_seconds) * self.bucket_seconds

    def _window_start(self) -> int:
        """Oldest bucket still in the window."""
        return self._current_bucket() - self.window_seconds

    def check_and_increment(self, key: str) -> tuple[bool, int]:
        """
        Check if key is within rate limit. Increment counter if allowed.
        Returns (allowed, current_count).
        """
        with self._lock:
            now_bucket = self._current_bucket()
            window_start = self._window_start()
            buckets = self._counters[key]

            # Evict expired buckets (Redis: TTL handles this automatically)
            expired = [ts for ts in buckets if ts <= window_start]
            for ts in expired:
                del buckets[ts]

            # Count total requests in window
            current_count = sum(buckets.values())

            if current_count >= self.limit:
                return False, current_count

            # Increment current bucket
            buckets[now_bucket] = buckets.get(now_bucket, 0) + 1
            return True, current_count + 1

    def retry_after(self, key: str) -> float:
        """Seconds until oldest bucket expires (when a slot opens up)."""
        with self._lock:
            buckets = self._counters.get(key, {})
            if not buckets:
                return 0
            oldest = min(buckets.keys())
            return max(0, oldest + self.window_seconds - time.time())


# =============================================================================
# ALGORITHM 3: FIXED WINDOW (simplest, edge case to know)
# =============================================================================
# Count requests in current time window. Reset at window boundary.
# PROBLEM: at boundary, allow 2x limit in 2x bucket_size time.
#   Example: limit=100/min. 100 requests at 11:59:59. Window resets at 12:00:00.
#   Another 100 requests at 12:00:01. = 200 requests in 2 seconds.
# Use sliding window to avoid this. Fixed window fine for rough limits.

class FixedWindowCounter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self._counters: dict[str, tuple[int, int]] = {}  # key → (count, window_start)
        self._lock = threading.Lock()

    def _window_start(self) -> int:
        return int(time.time() // self.window_seconds) * self.window_seconds

    def check_and_increment(self, key: str) -> bool:
        with self._lock:
            now_window = self._window_start()
            count, window = self._counters.get(key, (0, now_window))
            if window != now_window:
                count, window = 0, now_window  # New window — reset
            if count >= self.limit:
                return False
            self._counters[key] = (count + 1, window)
            return True


# =============================================================================
# LEAKY BUCKET (concept — output rate control)
# =============================================================================
# Queue requests up to queue_size. Process at fixed rate (drain rate).
# Good for: smoothing output (send emails at max 100/min, not burst 10K then 0).
# Bad for: interactive APIs (high-priority requests still queue behind low).
# The "leak" is the drain — even if no requests come in, nothing drips out.
#
# Queue full → new requests dropped (or return 429).
# Difference from token bucket: token bucket allows bursts through immediately.
# Leaky bucket queues bursts and processes them smoothly.


# =============================================================================
# IDEMPOTENCY KEYS
# =============================================================================
# Problem: POST /charges — client sends request, network times out.
#   Did the charge happen? Client doesn't know. Retry? Risk double charge.
#
# Solution: client generates a UUID before the request.
#   Include as Idempotency-Key: <uuid> header.
#   Server: check if UUID seen before.
#     Yes → return cached response (no operation performed again)
#     No  → process request, store result by UUID, return result
#
# Storage: Redis (key: "idem:{uuid}", value: serialized response, TTL: 24h)
# If two requests arrive simultaneously with same key: lock on key, second
#   waits, then sees result and returns it.

class IdempotencyStore:
    """
    Idempotency key store. In production: Redis with TTL.
    Prevents duplicate operations when clients retry.
    """
    def __init__(self, ttl_seconds: int = 86400):  # 24 hours
        self.ttl_seconds = ttl_seconds
        self._store: dict[str, dict] = {}  # key → {result, expires_at}
        self._lock = threading.Lock()

    def get(self, idempotency_key: str) -> Optional[dict]:
        """Return previously stored result, or None if not seen / expired."""
        with self._lock:
            entry = self._store.get(idempotency_key)
            if entry and time.time() < entry["expires_at"]:
                return entry["result"]
            return None

    def store(self, idempotency_key: str, result: dict):
        """Store result for this idempotency key."""
        with self._lock:
            self._store[idempotency_key] = {
                "result": result,
                "expires_at": time.time() + self.ttl_seconds
            }

    def process_once(self, idempotency_key: str, operation: Callable) -> dict:
        """
        Execute operation exactly once for this idempotency key.
        Subsequent calls with same key return the cached result.
        """
        cached = self.get(idempotency_key)
        if cached is not None:
            return {**cached, "_idempotent": True, "_replayed": True}

        result = operation()
        self.store(idempotency_key, result)
        return result


# =============================================================================
# DISTRIBUTED RATE LIMITER WITH RATE LIMIT HEADERS
# =============================================================================
# Real production middleware pattern for FastAPI / Flask.
# Returns standard HTTP rate limit response headers so clients can self-throttle.

@dataclass
class RateLimitResult:
    allowed: bool
    limit: int           # X-RateLimit-Limit
    remaining: int       # X-RateLimit-Remaining
    reset_at: float      # X-RateLimit-Reset (Unix timestamp)
    retry_after: float   # Retry-After (seconds, only on 429)

class RateLimiter:
    """
    Production-ready rate limiter with proper headers.
    Uses sliding window counter internally.
    In production: Redis backend for distributed state.
    """
    def __init__(self, limit: int = 100, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds
        self._counter = SlidingWindowCounter(limit, window_seconds)

    def check(self, identifier: str) -> RateLimitResult:
        """
        Check rate limit for identifier (user_id, ip, api_key).
        Returns RateLimitResult with all headers pre-computed.
        """
        allowed, count = self._counter.check_and_increment(identifier)
        remaining = max(0, self.limit - count)
        reset_at = time.time() + self.window_seconds  # Approximate
        retry_after = self._counter.retry_after(identifier) if not allowed else 0

        return RateLimitResult(
            allowed=allowed,
            limit=self.limit,
            remaining=remaining,
            reset_at=reset_at,
            retry_after=retry_after
        )

    def to_headers(self, result: RateLimitResult) -> dict:
        """Convert RateLimitResult to HTTP response headers."""
        headers = {
            "X-RateLimit-Limit": str(result.limit),
            "X-RateLimit-Remaining": str(result.remaining),
            "X-RateLimit-Reset": str(int(result.reset_at))
        }
        if not result.allowed:
            headers["Retry-After"] = str(int(result.retry_after) + 1)
        return headers


# =============================================================================
# CONSISTENT HASHING
# =============================================================================
# Problem: distributing data across N servers.
# Naive: hash(key) % N. When N changes (add/remove server), MOST keys remap.
#   With 4 servers: hash(key)%4. Add 5th: hash(key)%5. Almost all keys move.
#   During the move: cache misses spike, DB load spikes. Not good.
#
# Consistent hashing: both servers and keys are placed on a virtual ring (0 to 2^32).
#   A key belongs to the NEXT server clockwise on the ring.
#   Add/remove a server: only the keys between it and its neighbor remapped.
#   With N servers and K keys: only K/N keys need to move on average.
#
# Virtual nodes: each physical server gets V positions on the ring.
#   Provides better load distribution when servers have different capacities.
#   Cassandra: 256 virtual nodes per server by default.
#
# Used by: Cassandra, DynamoDB, Redis Cluster, CDNs (Akamai), memcached.

import hashlib
import bisect

class ConsistentHashRing:
    """
    Consistent hash ring for distributing keys across nodes.
    Virtual nodes improve load balance.
    """
    def __init__(self, nodes: list[str] = None, virtual_nodes: int = 150):
        self.virtual_nodes = virtual_nodes
        self._ring: dict[int, str] = {}      # hash position → node name
        self._sorted_keys: list[int] = []    # sorted ring positions

        for node in (nodes or []):
            self.add_node(node)

    def _hash(self, key: str) -> int:
        """Consistent hash function. MD5 for uniform distribution."""
        return int(hashlib.md5(key.encode()).hexdigest(), 16)

    def add_node(self, node: str):
        """Add a node. Creates virtual_nodes positions on the ring."""
        for i in range(self.virtual_nodes):
            virtual_key = f"{node}#{i}"
            position = self._hash(virtual_key)
            self._ring[position] = node
            bisect.insort(self._sorted_keys, position)
        print(f"[HashRing] Added node '{node}' with {self.virtual_nodes} virtual positions")

    def remove_node(self, node: str):
        """Remove a node. Only its K/N keys remap to neighbors."""
        for i in range(self.virtual_nodes):
            virtual_key = f"{node}#{i}"
            position = self._hash(virtual_key)
            if position in self._ring:
                del self._ring[position]
                self._sorted_keys.remove(position)
        print(f"[HashRing] Removed node '{node}'")

    def get_node(self, key: str) -> Optional[str]:
        """Find which node owns this key (next clockwise node on ring)."""
        if not self._ring:
            return None
        position = self._hash(key)
        # Find next position >= hash on the ring. Wrap around if past end.
        idx = bisect.bisect_right(self._sorted_keys, position)
        if idx == len(self._sorted_keys):
            idx = 0  # Wrap around the ring
        return self._ring[self._sorted_keys[idx]]

    def get_distribution(self, num_keys: int = 10000) -> dict[str, int]:
        """Simulate distributing num_keys to see load balance."""
        distribution: dict[str, int] = defaultdict(int)
        for i in range(num_keys):
            node = self.get_node(f"key_{i}")
            if node:
                distribution[node] += 1
        return dict(distribution)


# =============================================================================
# WEBHOOK PATTERN
# =============================================================================
# Instead of client polling ("did anything happen?"), server pushes events.
# Client registers an HTTPS endpoint. Server POSTs events to it.
#
# RELIABILITY:
#   - Retry with exponential backoff if client returns non-200
#   - Store delivery attempts and status in DB
#   - Webhook dashboard: show recent deliveries, allow manual retry
#
# SECURITY:
#   - Sign payload with HMAC-SHA256 using shared secret
#   - Client verifies signature before processing
#   - Include timestamp in signed payload to prevent replay attacks
#   - Use HTTPS only — no plaintext delivery

class WebhookSender:
    """Simulates outgoing webhook delivery with signing."""

    def __init__(self, secret: str):
        self.secret = secret.encode()

    def sign_payload(self, payload: dict, timestamp: int) -> str:
        """
        HMAC-SHA256 signature over 'timestamp.body'.
        Client verifies: hmac(secret, f'{timestamp}.{body}') == signature.
        Include timestamp in signature to prevent replay attacks.
        """
        body = json.dumps(payload, separators=(',', ':'), sort_keys=True)
        message = f"{timestamp}.{body}".encode()
        sig = hmac.new(self.secret, message, hashlib.sha256).hexdigest()
        return f"sha256={sig}"

    def create_delivery(self, event_type: str, payload: dict) -> dict:
        """Create a signed webhook delivery package."""
        timestamp = int(time.time())
        signature = self.sign_payload(payload, timestamp)
        return {
            "id": str(uuid.uuid4()),
            "event": event_type,
            "payload": payload,
            "timestamp": timestamp,
            "signature": signature,  # Goes in X-Webhook-Signature header
            "retry_count": 0
        }

class WebhookVerifier:
    """Client-side webhook signature verification."""

    def __init__(self, secret: str):
        self.secret = secret.encode()
        self.max_age_seconds = 300  # Reject webhooks older than 5 minutes

    def verify(self, payload: dict, timestamp: int, signature: str) -> bool:
        """Verify webhook came from legitimate sender. Reject if too old."""
        # Check timestamp freshness (prevents replay attacks)
        if abs(time.time() - timestamp) > self.max_age_seconds:
            return False  # Too old — could be a replay

        body = json.dumps(payload, separators=(',', ':'), sort_keys=True)
        message = f"{timestamp}.{body}".encode()
        expected = "sha256=" + hmac.new(self.secret, message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)  # Constant-time compare


# =============================================================================
# CURSOR-BASED PAGINATION
# =============================================================================
# OFFSET pagination: SELECT ... LIMIT 20 OFFSET 1000
#   Problem: DB must scan and discard 1000 rows. Slow for large offsets.
#   Problem: if rows inserted during pagination, duplicates or gaps appear.
#
# CURSOR pagination: SELECT ... WHERE id > :cursor LIMIT 20 ORDER BY id
#   Always O(1) — indexed seek directly to cursor position.
#   Consistent: new rows don't affect pagination of existing rows.
#   Limitation: can't jump to page 50. Only next/prev.
#   Use for: feeds, timelines, infinite scroll, large datasets.
#   Use OFFSET for: admin UIs needing page N, small datasets, total count needed.

def cursor_paginate(items: list, cursor: Optional[str], page_size: int = 20) -> dict:
    """
    Simulates cursor-based pagination.
    In production: cursor is base64-encoded (id, timestamp) pair.
    """
    # Decode cursor (in production: base64 decode the opaque cursor string)
    start_id = int(cursor) if cursor else 0

    page = [item for item in items if item["id"] > start_id][:page_size]

    next_cursor = str(page[-1]["id"]) if len(page) == page_size else None

    return {
        "data": page,
        "next_cursor": next_cursor,         # None = no more pages
        "has_more": next_cursor is not None
    }


# =============================================================================
# FULL DEMO
# =============================================================================

def demo_rate_limiting():
    print("=" * 60)
    print("RATE LIMITING AND API PATTERNS DEMO")
    print("=" * 60)

    # Token Bucket: burst of 5, refill 2/s
    print("\n--- Token Bucket (capacity=5, refill=2/s) ---")
    bucket = TokenBucket(capacity=5, refill_rate=2.0)
    for i in range(8):
        allowed = bucket.consume()
        print(f"  Request {i+1}: {'ALLOWED' if allowed else 'REJECTED (429)'} | tokens={bucket.tokens_remaining():.1f}")

    # Sliding Window
    print("\n--- Sliding Window Counter (10 req/10s) ---")
    sw = SlidingWindowCounter(limit=10, window_seconds=10)
    for i in range(13):
        allowed, count = sw.check_and_increment("user_001")
        status = "OK " if allowed else "429"
        print(f"  Request {i+1:02d}: {status} | window_count={count}")

    # Idempotency Keys
    print("\n--- Idempotency Keys ---")
    idem_store = IdempotencyStore()
    charge_count = {"n": 0}

    def charge_card():
        charge_count["n"] += 1
        return {"charge_id": f"ch_{uuid.uuid4().hex[:8]}", "amount": 99.99, "status": "success"}

    key = "idem_" + uuid.uuid4().hex[:8]
    result1 = idem_store.process_once(key, charge_card)
    result2 = idem_store.process_once(key, charge_card)  # Same key — no second charge
    result3 = idem_store.process_once(key, charge_card)  # Same key — no third charge
    print(f"  Charge function called: {charge_count['n']} time(s) (expected: 1)")
    print(f"  Result 1: {result1}")
    print(f"  Result 2 replayed: {result2.get('_replayed', False)}")

    # Consistent Hashing
    print("\n--- Consistent Hashing ---")
    ring = ConsistentHashRing(["cache-1", "cache-2", "cache-3"], virtual_nodes=50)
    dist = ring.get_distribution(3000)
    for node, count in sorted(dist.items()):
        bar = "#" * (count // 30)
        print(f"  {node}: {count:4d} keys  {bar}")

    print("\n  Adding cache-4:")
    ring.add_node("cache-4")
    dist2 = ring.get_distribution(3000)
    for node, count in sorted(dist2.items()):
        bar = "#" * (count // 30)
        print(f"  {node}: {count:4d} keys  {bar}")

    # Webhook Signing
    print("\n--- Webhook Signing & Verification ---")
    secret = "webhook_secret_abc123"
    sender = WebhookSender(secret)
    verifier = WebhookVerifier(secret)

    delivery = sender.create_delivery("order.created", {"order_id": "ord_001", "total": 59.99})
    is_valid = verifier.verify(delivery["payload"], delivery["timestamp"], delivery["signature"])
    print(f"  Valid signature: {is_valid}")

    tampered_sig = delivery["signature"][:-4] + "XXXX"
    is_valid_tampered = verifier.verify(delivery["payload"], delivery["timestamp"], tampered_sig)
    print(f"  Tampered signature accepted: {is_valid_tampered} (expected: False)")

    # Cursor Pagination
    print("\n--- Cursor Pagination ---")
    all_items = [{"id": i, "name": f"Item {i}"} for i in range(1, 51)]
    page1 = cursor_paginate(all_items, cursor=None, page_size=10)
    print(f"  Page 1: items {page1['data'][0]['id']}–{page1['data'][-1]['id']}, next_cursor={page1['next_cursor']}")
    page2 = cursor_paginate(all_items, cursor=page1["next_cursor"], page_size=10)
    print(f"  Page 2: items {page2['data'][0]['id']}–{page2['data'][-1]['id']}, next_cursor={page2['next_cursor']}")


if __name__ == "__main__":
    demo_rate_limiting()

# =============================================================================
# REDIS LUA SCRIPT FOR PRODUCTION RATE LIMITING (reference)
# =============================================================================
# Use EVAL to run atomically — no race conditions between check and increment.
#
# SLIDING_WINDOW_LUA = """
# local key = KEYS[1]
# local now = tonumber(ARGV[1])        -- current timestamp (ms)
# local window = tonumber(ARGV[2])     -- window size (ms)
# local limit = tonumber(ARGV[3])      -- max requests
#
# -- Remove timestamps outside the window
# redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
#
# -- Count current requests in window
# local count = redis.call('ZCARD', key)
#
# if count < limit then
#     -- Add current timestamp (score = timestamp, member = unique ID)
#     redis.call('ZADD', key, now, now .. '-' .. math.random())
#     redis.call('EXPIRE', key, math.ceil(window / 1000))
#     return {1, limit - count - 1}   -- {allowed, remaining}
# else
#     return {0, 0}                   -- {rejected, remaining=0}
# end
# """
#
# Usage: redis.eval(SLIDING_WINDOW_LUA, 1, key, now_ms, window_ms, limit)
# This is the sliding window LOG approach — exact, stores every timestamp.
# For high-traffic: use sliding window COUNTER (bucket approach) shown above.
# =============================================================================
