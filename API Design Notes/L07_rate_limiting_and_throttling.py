# =============================================================================
# WHAT:  Rate limiting and throttling algorithms with production implementation
# WHY:   Without rate limiting, a single misbehaving client can exhaust your
#        server capacity, degrade service for everyone, and cause cascading
#        failures across downstream dependencies.
# LEVEL: Intermediate → Advanced (assumes Redis and HTTP headers knowledge)
# =============================================================================

# CONCEPT OVERVIEW
# ----------------
# Rate limiting: enforce a maximum number of requests in a time window.
# Throttling: slow requests down (shape traffic) rather than hard-blocking.
# Both protect YOUR infrastructure. Throttling protects DOWNSTREAM services too.
#
# Five standard algorithms, each with different trade-offs:
#   1. Fixed Window   — simple, but vulnerable to burst at window boundary
#   2. Sliding Window Log — precise, but high memory (stores all timestamps)
#   3. Sliding Window Counter — approximate, low memory, good for high volume
#   4. Token Bucket   — allows burst up to bucket capacity, then steady rate
#   5. Leaky Bucket   — strict output rate regardless of input burst pattern

# PRODUCTION USE CASE
# -------------------
# Public REST API: Free tier = 100 req/min per API key, burst up to 200.
# Premium tier = 1000 req/min. Per-IP limit = 50 req/min (bot protection).
# Specific expensive endpoints get stricter limits regardless of tier.

# COMMON MISTAKES
# ---------------
# 1. Not including Retry-After header — clients don't know when to retry
# 2. Using non-atomic Redis operations — race conditions under concurrency
# 3. Rate limiting only at app layer (not gateway) — bypassed by direct calls
# 4. Same limit for all endpoints — /search is 100x more expensive than /health
# 5. Not logging 429s — you can't tune limits without data
# 6. Counting failed requests against the limit — punishes clients for server errors

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Redis would be: import redis
# For this file we use a pseudo-Redis to keep it dependency-free
# In production: r = redis.Redis(host="localhost", port=6379, decode_responses=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# SECTION 1 — PSEUDO-REDIS (for running examples without a real Redis instance)
# =============================================================================

class PseudoRedis:
    """
    Simulates a subset of Redis commands for local demo purposes.
    Replace all usages with a real redis.Redis client in production.
    """
    def __init__(self):
        self._store: Dict[str, any] = {}
        self._expiry: Dict[str, float] = {}

    def _is_expired(self, key: str) -> bool:
        if key in self._expiry and time.time() > self._expiry[key]:
            del self._store[key]
            del self._expiry[key]
            return True
        return False

    def get(self, key: str) -> Optional[str]:
        if self._is_expired(key):
            return None
        return self._store.get(key)

    def set(self, key: str, value, ex: Optional[int] = None) -> None:
        self._store[key] = str(value)
        if ex:
            self._expiry[key] = time.time() + ex

    def incr(self, key: str) -> int:
        if self._is_expired(key):
            pass
        val = int(self._store.get(key, 0)) + 1
        self._store[key] = str(val)
        return val

    def expire(self, key: str, seconds: int) -> None:
        self._expiry[key] = time.time() + seconds

    def zadd(self, key: str, mapping: Dict[str, float]) -> None:
        """Add members to a sorted set."""
        if key not in self._store or not isinstance(self._store[key], dict):
            self._store[key] = {}
        self._store[key].update(mapping)

    def zrangebyscore(self, key: str, min_score: float, max_score: float) -> List[str]:
        """Return members with score between min and max."""
        if self._is_expired(key) or key not in self._store:
            return []
        return [
            m for m, s in self._store[key].items()
            if min_score <= s <= max_score
        ]

    def zremrangebyscore(self, key: str, min_score: float, max_score: float) -> int:
        """Remove members with score between min and max. Returns count removed."""
        if key not in self._store:
            return 0
        before = len(self._store[key])
        self._store[key] = {
            m: s for m, s in self._store[key].items()
            if not (min_score <= s <= max_score)
        }
        return before - len(self._store[key])

    def zcard(self, key: str) -> int:
        """Return number of members in sorted set."""
        if self._is_expired(key) or key not in self._store:
            return 0
        return len(self._store[key])

    def eval(self, script: str, numkeys: int, *args) -> any:
        """Placeholder — real Redis executes Lua scripts atomically."""
        # Real Redis guarantees atomicity; this simulation does NOT
        raise NotImplementedError("Use real Redis for atomic Lua scripts in production")


# =============================================================================
# SECTION 2 — RATE LIMIT RESULT (what every algorithm returns)
# =============================================================================

@dataclass
class RateLimitResult:
    """
    Unified result from any rate limiter.
    The caller uses `allowed` to gate the request, and the header fields
    to populate standard HTTP response headers.
    """
    allowed: bool           # True = request may proceed
    limit: int              # Total capacity (X-RateLimit-Limit)
    remaining: int          # Remaining capacity this window (X-RateLimit-Remaining)
    reset_at: float         # Unix timestamp when window resets (X-RateLimit-Reset)
    retry_after: int        # Seconds until retry is safe (Retry-After header)

    def to_headers(self) -> Dict[str, str]:
        """
        Convert to HTTP response headers per RFC 6585 and de-facto standards.
        Always include these headers — on both allowed AND rejected requests.
        Clients use them for self-throttling BEFORE hitting the limit.
        """
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(int(self.reset_at)),  # Unix timestamp
            "Retry-After": str(self.retry_after) if not self.allowed else "",
        }


# =============================================================================
# SECTION 3 — ALGORITHM 1: FIXED WINDOW
# =============================================================================
# Simplest algorithm. Count requests in the current window (e.g., this minute).
# Reset counter at the start of each new window.
#
# WEAKNESS: Allows 2x burst at window boundaries.
#   Example: 100 req/min limit. 100 at 11:59, 100 at 12:00 = 200 in 2 seconds.
# USE WHEN: Limits are loose, simplicity matters, burst at edges is acceptable.

class FixedWindowRateLimiter:
    """
    Fixed window counter. State stored in Redis for distributed safety.
    Key format: ratelimit:fixed:{identifier}:{window_number}
    """
    def __init__(self, redis_client, limit: int, window_seconds: int):
        self.redis = redis_client
        self.limit = limit
        self.window_seconds = window_seconds

    def check(self, identifier: str) -> RateLimitResult:
        """
        Check and increment counter for the current window.
        identifier: the entity to rate limit (user_id, api_key, ip_address)
        """
        # Compute which window we're in (integer division gives window number)
        current_window = int(time.time() // self.window_seconds)
        # Each window gets its own Redis key so it naturally expires
        key = f"ratelimit:fixed:{identifier}:{current_window}"

        # INCR is atomic in Redis — safe under concurrent requests
        count = self.redis.incr(key)

        if count == 1:
            # First request in this window — set TTL so key auto-cleans
            self.redis.expire(key, self.window_seconds * 2)  # 2x for safety

        # When does this window end?
        window_end = (current_window + 1) * self.window_seconds

        return RateLimitResult(
            allowed=count <= self.limit,
            limit=self.limit,
            remaining=self.limit - count,       # Can go negative — cap at 0 in headers
            reset_at=window_end,
            retry_after=max(0, int(window_end - time.time())),
        )


# =============================================================================
# SECTION 4 — ALGORITHM 2: SLIDING WINDOW LOG
# =============================================================================
# Store a timestamp for every request in a sorted set.
# On each request: remove timestamps outside the window, count what remains.
#
# STRENGTH: Perfectly precise — no boundary burst vulnerability.
# WEAKNESS: High memory — stores one entry per request. At 1000 req/min with
#           10k users = 10M entries. Impractical for high-volume public APIs.
# USE WHEN: Low volume, strict accuracy required (e.g., financial transaction limits).

class SlidingWindowLogRateLimiter:
    """
    Sliding window using Redis sorted set (zset) as a timestamp log.
    Score = timestamp, Member = unique request ID (to allow duplicates at same time).
    """
    def __init__(self, redis_client, limit: int, window_seconds: int):
        self.redis = redis_client
        self.limit = limit
        self.window_seconds = window_seconds

    def check(self, identifier: str) -> RateLimitResult:
        now = time.time()
        window_start = now - self.window_seconds   # Oldest timestamp still in window
        key = f"ratelimit:log:{identifier}"

        # Remove timestamps that have slid out of the window (older than window_start)
        self.redis.zremrangebyscore(key, 0, window_start)

        # Count requests in the current window
        current_count = self.redis.zcard(key)

        allowed = current_count < self.limit

        if allowed:
            # Add this request's timestamp to the log
            request_id = f"{now}:{id(object())}"  # Unique even at same timestamp
            self.redis.zadd(key, {request_id: now})

        # Reset = when the oldest request in the window expires
        # (approximated as window_seconds from now when log is empty)
        reset_at = now + self.window_seconds

        return RateLimitResult(
            allowed=allowed,
            limit=self.limit,
            remaining=max(0, self.limit - current_count - (1 if allowed else 0)),
            reset_at=reset_at,
            retry_after=0 if allowed else int(self.window_seconds),
        )


# =============================================================================
# SECTION 5 — ALGORITHM 3: SLIDING WINDOW COUNTER
# =============================================================================
# Approximation of sliding window log with O(1) memory.
# Uses TWO fixed window counters (current and previous) and interpolates.
#
# Formula: effective_count = prev_count * overlap_ratio + current_count
# WHERE overlap_ratio = fraction of previous window still inside current window
#
# ERROR BOUND: ≤ (limit / window_seconds) * window_seconds = limit
#              In practice error is much smaller; typically < 1%.
# USE WHEN: High-volume APIs where memory efficiency matters more than perfection.

class SlidingWindowCounterRateLimiter:
    """
    Sliding window approximation using two fixed-window counters.
    Recommended algorithm for production at scale (Cloudflare uses this).
    """
    def __init__(self, redis_client, limit: int, window_seconds: int):
        self.redis = redis_client
        self.limit = limit
        self.window_seconds = window_seconds

    def check(self, identifier: str) -> RateLimitResult:
        now = time.time()
        current_window = int(now // self.window_seconds)
        previous_window = current_window - 1

        current_key = f"ratelimit:swc:{identifier}:{current_window}"
        previous_key = f"ratelimit:swc:{identifier}:{previous_window}"

        # How far into the current window are we? (0.0 = just started, 1.0 = ending)
        elapsed_in_window = (now % self.window_seconds) / self.window_seconds
        # How much of the previous window is still "in scope" for the sliding window?
        previous_weight = 1.0 - elapsed_in_window

        # Fetch both counters (returns None if key doesn't exist yet)
        current_count_str = self.redis.get(current_key)
        previous_count_str = self.redis.get(previous_key)

        current_count = int(current_count_str) if current_count_str else 0
        previous_count = int(previous_count_str) if previous_count_str else 0

        # Weighted sum approximates the sliding window count
        effective_count = previous_count * previous_weight + current_count

        allowed = effective_count < self.limit

        if allowed:
            # Atomically increment current window counter
            new_count = self.redis.incr(current_key)
            if new_count == 1:
                # Set TTL to 2 windows so previous window data is available
                self.redis.expire(current_key, self.window_seconds * 2)

        window_end = (current_window + 1) * self.window_seconds

        return RateLimitResult(
            allowed=allowed,
            limit=self.limit,
            remaining=max(0, int(self.limit - effective_count)),
            reset_at=window_end,
            retry_after=max(0, int(window_end - now)) if not allowed else 0,
        )


# =============================================================================
# SECTION 6 — ALGORITHM 4: TOKEN BUCKET
# =============================================================================
# A "bucket" holds tokens (capacity = max burst). Each request consumes one
# token. Tokens refill at a fixed rate (e.g., 10/second).
#
# STRENGTH: Naturally handles burst up to bucket capacity. Smooth long-term rate.
# WEAKNESS: Slightly more complex state (current_tokens + last_refill_time).
# USE WHEN: You want to allow occasional bursts (API clients that batch requests)
#           while enforcing a long-term average rate.
#
# Example: bucket=100 tokens, refill=10/sec.
#   Client sends 100 requests instantly (uses full bucket).
#   Must then wait 10 seconds to accumulate enough tokens to send 100 more.

class TokenBucketRateLimiter:
    """
    Token bucket implemented with Redis for distributed state.
    State: (token_count, last_refill_timestamp) stored as Redis hash.
    """
    def __init__(
        self,
        redis_client,
        capacity: int,      # Maximum tokens (= max burst size)
        refill_rate: float, # Tokens added per second
    ):
        self.redis = redis_client
        self.capacity = capacity
        self.refill_rate = refill_rate  # e.g., 10.0 means 10 tokens/second

    def check(self, identifier: str, tokens_requested: int = 1) -> RateLimitResult:
        """
        Try to consume tokens_requested tokens from the bucket.
        tokens_requested > 1 useful for weighted requests (expensive ops cost more).
        """
        now = time.time()
        key = f"ratelimit:token:{identifier}"

        # Read current state (in production, use a Lua script for atomicity)
        tokens_str = self.redis.get(f"{key}:tokens")
        last_refill_str = self.redis.get(f"{key}:last_refill")

        # Initialize new buckets at full capacity
        current_tokens = float(tokens_str) if tokens_str else float(self.capacity)
        last_refill = float(last_refill_str) if last_refill_str else now

        # Calculate how many tokens to add based on time elapsed since last refill
        elapsed = now - last_refill
        tokens_to_add = elapsed * self.refill_rate
        # Cap at capacity — tokens don't accumulate beyond the bucket size
        current_tokens = min(self.capacity, current_tokens + tokens_to_add)

        allowed = current_tokens >= tokens_requested

        if allowed:
            current_tokens -= tokens_requested  # Consume the tokens

        # Persist updated state with TTL (auto-clean inactive clients)
        ttl = int(self.capacity / self.refill_rate) + 60  # Time to fill empty bucket + buffer
        self.redis.set(f"{key}:tokens", current_tokens, ex=ttl)
        self.redis.set(f"{key}:last_refill", now, ex=ttl)

        # Compute wait time: how long until enough tokens accumulate
        if not allowed:
            deficit = tokens_requested - current_tokens
            retry_after = int(deficit / self.refill_rate) + 1
        else:
            retry_after = 0

        # Reset = when bucket would be full again (informational)
        time_to_full = (self.capacity - current_tokens) / self.refill_rate
        reset_at = now + time_to_full

        return RateLimitResult(
            allowed=allowed,
            limit=self.capacity,
            remaining=int(current_tokens),
            reset_at=reset_at,
            retry_after=retry_after,
        )


# =============================================================================
# SECTION 7 — ALGORITHM 5: LEAKY BUCKET
# =============================================================================
# Incoming requests enter a queue (the "bucket"). Requests leak out at a fixed
# rate regardless of how fast they came in. If the queue is full, reject.
#
# DIFFERENCE from Token Bucket: Leaky bucket produces a CONSTANT output rate.
#   Token bucket allows burst; leaky bucket smooths ALL traffic.
# USE WHEN: You need strict output rate to protect a downstream service.
#   e.g., limiting outbound SMS to 5/sec regardless of how many arrive.

class LeakyBucketRateLimiter:
    """
    Leaky bucket: models a queue with constant drain rate.
    State: (queue_size, last_leak_timestamp)
    """
    def __init__(
        self,
        redis_client,
        capacity: int,      # Max queue size (= max queue depth before rejection)
        leak_rate: float,   # Requests drained per second (output rate)
    ):
        self.redis = redis_client
        self.capacity = capacity
        self.leak_rate = leak_rate

    def check(self, identifier: str) -> RateLimitResult:
        now = time.time()
        key = f"ratelimit:leaky:{identifier}"

        queue_str = self.redis.get(f"{key}:queue")
        last_leak_str = self.redis.get(f"{key}:last_leak")

        current_queue = float(queue_str) if queue_str else 0.0
        last_leak = float(last_leak_str) if last_leak_str else now

        # Drain the queue: remove requests that have "leaked" since last check
        elapsed = now - last_leak
        leaked = elapsed * self.leak_rate
        current_queue = max(0, current_queue - leaked)  # Queue can't go below 0

        allowed = current_queue < self.capacity

        if allowed:
            current_queue += 1  # Add this request to the queue

        ttl = int(self.capacity / self.leak_rate) + 60
        self.redis.set(f"{key}:queue", current_queue, ex=ttl)
        self.redis.set(f"{key}:last_leak", now, ex=ttl)

        # Time until queue has space = time for one slot to drain
        retry_after = int(1.0 / self.leak_rate) + 1 if not allowed else 0
        reset_at = now + (current_queue / self.leak_rate)

        return RateLimitResult(
            allowed=allowed,
            limit=self.capacity,
            remaining=max(0, int(self.capacity - current_queue)),
            reset_at=reset_at,
            retry_after=retry_after,
        )


# =============================================================================
# SECTION 8 — MULTI-DIMENSIONAL LIMITS (per-user, per-IP, per-key, per-endpoint)
# =============================================================================
# Real APIs apply MULTIPLE limits simultaneously. A request is allowed only if
# ALL applicable limits pass. The most restrictive limit wins.

@dataclass
class RequestContext:
    """Everything we know about an incoming API request."""
    api_key: Optional[str]
    user_id: Optional[str]
    ip_address: str
    endpoint: str       # e.g., "/v1/search"
    method: str         # GET, POST, etc.


class MultiDimensionalRateLimiter:
    """
    Applies multiple rate limits to a request and returns the combined result.
    Each dimension protects against a different abuse vector:
      - Per-IP:       bot protection, DDoS mitigation
      - Per-API-key:  fair use per customer
      - Per-user:     prevents shared key abuse
      - Per-endpoint: protect expensive operations specifically
    """
    def __init__(self, redis_client):
        self.redis = redis_client

        # Different limits for different dimensions
        self._ip_limiter = FixedWindowRateLimiter(redis_client, limit=50, window_seconds=60)
        self._key_limiter = SlidingWindowCounterRateLimiter(redis_client, limit=1000, window_seconds=60)
        self._user_limiter = TokenBucketRateLimiter(redis_client, capacity=200, refill_rate=3.3)

        # Endpoint-specific overrides (expensive endpoints get stricter limits)
        self._endpoint_limits = {
            "/v1/search": FixedWindowRateLimiter(redis_client, limit=20, window_seconds=60),
            "/v1/export": FixedWindowRateLimiter(redis_client, limit=5, window_seconds=3600),
        }

    def check(self, ctx: RequestContext) -> RateLimitResult:
        """
        Apply all relevant limits. Request allowed only if ALL pass.
        Returns the most restrictive result for header reporting.
        """
        results = []

        # Always apply IP-level limit (even unauthenticated requests)
        results.append(("ip", self._ip_limiter.check(f"ip:{ctx.ip_address}")))

        # Apply API key limit if authenticated
        if ctx.api_key:
            results.append(("key", self._key_limiter.check(f"key:{ctx.api_key}")))

        # Apply user limit if we know the user
        if ctx.user_id:
            results.append(("user", self._user_limiter.check(f"user:{ctx.user_id}")))

        # Apply endpoint-specific limit if one exists
        if ctx.endpoint in self._endpoint_limits:
            identifier = f"{ctx.api_key or ctx.ip_address}:{ctx.endpoint}"
            results.append(("endpoint", self._endpoint_limits[ctx.endpoint].check(identifier)))

        # A request is allowed only if ALL limits pass
        all_allowed = all(r.allowed for _, r in results)

        # Find the most restrictive result to report in headers
        # (lowest remaining, or the first blocking result)
        blocking = [r for _, r in results if not r.allowed]
        if blocking:
            most_restrictive = min(blocking, key=lambda r: r.remaining)
        else:
            most_restrictive = min(results, key=lambda nr: nr[1].remaining)[1]

        return RateLimitResult(
            allowed=all_allowed,
            limit=most_restrictive.limit,
            remaining=most_restrictive.remaining,
            reset_at=most_restrictive.reset_at,
            retry_after=most_restrictive.retry_after,
        )


# =============================================================================
# SECTION 9 — 429 RESPONSE AND GRACEFUL DEGRADATION
# =============================================================================
# Hard block (429): reject the request entirely. Use for clear abuse.
# Graceful degradation: serve a degraded response instead of full rejection.
#   - Cached results instead of live data
#   - Reduced page size (20 results vs 100)
#   - Queue the work for later execution
# Partial rate limiting: warn (via header) before hard-blocking.

def build_429_response(result: RateLimitResult) -> Dict:
    """
    Construct a standardized 429 Too Many Requests response body.
    Always include when to retry so clients can back off intelligently.
    """
    return {
        "error": {
            "type": "rate_limit_exceeded",
            "code": 429,
            "message": (
                f"Rate limit exceeded. You have sent too many requests. "
                f"Please retry after {result.retry_after} seconds."
            ),
            "retry_after": result.retry_after,
            "limit": result.limit,
            "reset_at": int(result.reset_at),
        }
    }


def check_with_warning_zone(
    limiter: FixedWindowRateLimiter,
    identifier: str,
    warning_threshold: float = 0.8,  # Warn when 80% of limit consumed
) -> Tuple[RateLimitResult, bool]:
    """
    Return (result, is_in_warning_zone).
    Caller can add X-RateLimit-Warning header to help clients self-throttle
    before they hit the hard limit.
    """
    result = limiter.check(identifier)
    warning_remaining = result.limit * (1 - warning_threshold)
    in_warning_zone = result.remaining <= warning_remaining and result.allowed
    return result, in_warning_zone


# =============================================================================
# SECTION 10 — DISTRIBUTED RATE LIMITING WITH REDIS LUA SCRIPT
# =============================================================================
# WHY LUA: Redis executes Lua scripts atomically on the server side.
#          No other command can interleave — eliminates TOCTOU race conditions.
#          Critical when multiple app servers share Redis state.

FIXED_WINDOW_LUA_SCRIPT = """
-- Atomic fixed-window rate limiting script
-- KEYS[1] = rate limit key
-- ARGV[1] = limit (max requests)
-- ARGV[2] = window_seconds (TTL)
-- Returns: {current_count, allowed (1/0)}

local current = redis.call('INCR', KEYS[1])
if current == 1 then
    -- First request in this window: set the TTL
    redis.call('EXPIRE', KEYS[1], ARGV[2])
end
local allowed = 0
if current <= tonumber(ARGV[1]) then
    allowed = 1
end
return {current, allowed}
"""

def atomic_fixed_window_check(redis_client, identifier: str, limit: int, window_seconds: int) -> RateLimitResult:
    """
    Atomic rate limit check using Redis Lua script.
    This is what you use in production with real Redis.
    """
    current_window = int(time.time() // window_seconds)
    key = f"ratelimit:atomic:{identifier}:{current_window}"
    window_end = (current_window + 1) * window_seconds

    # In production with real Redis:
    # result = redis_client.eval(FIXED_WINDOW_LUA_SCRIPT, 1, key, limit, window_seconds)
    # count, allowed_int = result[0], result[1]

    # Simulated for demo:
    count = redis_client.incr(key)
    allowed = count <= limit

    return RateLimitResult(
        allowed=allowed,
        limit=limit,
        remaining=limit - count,
        reset_at=window_end,
        retry_after=max(0, int(window_end - time.time())) if not allowed else 0,
    )


# =============================================================================
# SECTION 11 — RATE LIMITING IN KONG API GATEWAY
# =============================================================================
# Applying rate limiting at the API gateway layer means:
#   - No app code changes required
#   - Limits enforced BEFORE requests reach your service
#   - Centralized configuration and monitoring
#
# Kong rate-limit plugin configuration (YAML/declarative):
#
# plugins:
#   - name: rate-limiting
#     config:
#       minute: 1000          # 1000 req/min per consumer
#       hour: 10000           # 10k req/hour cap
#       policy: redis         # Use Redis for distributed counting
#       redis_host: redis     # Redis hostname
#       redis_port: 6379
#       limit_by: consumer    # Also supports: ip, credential, service, header
#       fault_tolerant: true  # Allow requests if Redis is down (fail open)
#       hide_client_headers: false  # Expose X-RateLimit-* headers
#       error_code: 429
#       error_message: "API rate limit exceeded"
#
# Application-layer rate limiting (this file) is needed for:
#   - Business-logic-aware limits (different limits per subscription tier)
#   - Per-user limits (gateway typically sees API key, not user)
#   - Partial limits (degraded responses instead of hard block)


# =============================================================================
# SECTION 12 — THROTTLING VS RATE LIMITING DISTINCTION
# =============================================================================
# RATE LIMITING: hard enforcement — requests over the limit are REJECTED (429)
#   Client must wait and retry. No processing occurs for rejected requests.
#
# THROTTLING: soft enforcement — requests are SLOWED DOWN, not rejected
#   Techniques:
#     1. Queue and delay: accept request, process it after a delay
#     2. Reduced priority: process at lower priority vs high-priority clients
#     3. Degraded response: process but return fewer results / lower fidelity
#     4. Jitter: add random delay to spread load spikes (also called "smoothing")
#
# In practice: use rate limiting for external clients, throttling internally
# to protect downstream services from your own application's bursts.

def throttled_call(func: callable, delay_seconds: float) -> any:
    """
    Simple throttle wrapper: add a delay before calling func.
    In production: use Celery rate_limit or a token bucket at call sites.
    """
    time.sleep(delay_seconds)  # This blocks the thread — use async in production
    return func()


# =============================================================================
# SECTION 13 — CIRCUIT BREAKER PATTERN
# =============================================================================
# Rate limiting protects YOUR service from clients.
# Circuit breaker protects DOWNSTREAM services from your application.
#
# States:
#   CLOSED: Normal operation. Requests flow through. Track failures.
#   OPEN:   Too many failures. Fast-fail all requests. Don't try downstream.
#   HALF_OPEN: Test recovery. Allow one request. If success → CLOSED.

class CircuitBreakerState(str):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Protects a downstream dependency from cascading failures.
    Pair with rate limiting: rate limit inbound, circuit break outbound.
    """
    def __init__(
        self,
        failure_threshold: int = 5,     # Failures before opening
        recovery_timeout: float = 60.0, # Seconds before trying HALF_OPEN
        half_open_max_calls: int = 1,   # Test calls in HALF_OPEN state
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0

    @property
    def state(self) -> str:
        # Auto-transition OPEN → HALF_OPEN after recovery timeout
        if (
            self._state == CircuitBreakerState.OPEN
            and self._last_failure_time
            and time.time() - self._last_failure_time >= self.recovery_timeout
        ):
            self._state = CircuitBreakerState.HALF_OPEN
            self._half_open_calls = 0
            logger.info("Circuit breaker → HALF_OPEN (testing recovery)")
        return self._state

    def call_allowed(self) -> bool:
        """Check if a call to the downstream service should proceed."""
        state = self.state
        if state == CircuitBreakerState.CLOSED:
            return True
        if state == CircuitBreakerState.OPEN:
            return False  # Fast fail — don't even try
        # HALF_OPEN: allow limited test calls
        if self._half_open_calls < self.half_open_max_calls:
            self._half_open_calls += 1
            return True
        return False

    def record_success(self) -> None:
        """Call succeeded — reset failure count, close the circuit."""
        self._failure_count = 0
        if self._state == CircuitBreakerState.HALF_OPEN:
            logger.info("Circuit breaker → CLOSED (downstream recovered)")
        self._state = CircuitBreakerState.CLOSED

    def record_failure(self) -> None:
        """Call failed — increment counter, open circuit if threshold hit."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            if self._state != CircuitBreakerState.OPEN:
                logger.warning(
                    "Circuit breaker → OPEN after %d failures", self._failure_count
                )
            self._state = CircuitBreakerState.OPEN


# =============================================================================
# SECTION 14 — DEMONSTRATION
# =============================================================================

def run_demo():
    """Show each algorithm in action with a simulated burst of requests."""
    print("=== Rate Limiting Demo ===\n")
    redis = PseudoRedis()

    # Fixed Window — limit 5 per 10 seconds
    print("--- Fixed Window (limit=5, window=10s) ---")
    fw = FixedWindowRateLimiter(redis, limit=5, window_seconds=10)
    for i in range(8):
        result = fw.check("user:alice")
        status = "ALLOW" if result.allowed else "DENY "
        print(f"  Request {i+1}: {status} | remaining={result.remaining} | reset_in={result.retry_after}s")

    print("\n--- Token Bucket (capacity=5, refill=1/sec) ---")
    tb = TokenBucketRateLimiter(redis, capacity=5, refill_rate=1.0)
    for i in range(8):
        result = tb.check("user:bob")
        status = "ALLOW" if result.allowed else "DENY "
        print(f"  Request {i+1}: {status} | tokens_left={result.remaining} | retry_in={result.retry_after}s")

    print("\n--- Circuit Breaker ---")
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=5.0)
    for i in range(6):
        if cb.call_allowed():
            print(f"  Attempt {i+1}: CALLED downstream | state={cb.state}")
            cb.record_failure()  # Simulate failures
        else:
            print(f"  Attempt {i+1}: FAST FAIL | state={cb.state}")

    print("\n--- 429 Response Body ---")
    sample_result = RateLimitResult(allowed=False, limit=100, remaining=0, reset_at=time.time()+30, retry_after=30)
    print(json.dumps(build_429_response(sample_result), indent=2))
    print("\n--- Response Headers ---")
    for k, v in sample_result.to_headers().items():
        if v:
            print(f"  {k}: {v}")


if __name__ == "__main__":
    run_demo()
