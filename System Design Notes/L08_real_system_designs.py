# =============================================================================
# WHAT: Real-World System Designs — URL Shortener, Rate Limiter,
#       Notification System, Distributed Job Scheduler
# WHY:  System design interviews require end-to-end architectural reasoning.
#       These four designs cover the most commonly asked problems and illustrate
#       how all the lower-level concepts (caching, messaging, distributed state)
#       combine into complete production systems.
# LEVEL: Advanced (System Design Interview / Production Architecture)
# =============================================================================
#
# DESIGNS COVERED:
#   1. URL Shortener at Scale         → hash generation, redirect, analytics, storage.
#   2. Rate Limiter Service           → sliding window, token bucket, Redis Lua script.
#   3. Notification System            → fanout strategies, push/pull, Kafka for durability.
#   4. Distributed Job Scheduler      → worker pools, cron parsing, retry logic.
#
# HOW TO USE THIS FILE:
#   Each design section follows the same structure:
#     a) Requirements (functional + non-functional)
#     b) Capacity estimation
#     c) ASCII component diagram
#     d) Data model
#     e) API design
#     f) Core implementation
#     g) Scaling considerations
#
# COMMON INTERVIEW MISTAKES:
#   1. Jumping to solution before clarifying requirements and scale.
#   2. Not doing back-of-envelope math before choosing storage/compute.
#   3. Ignoring failure modes (what happens when Redis / Kafka is down?).
#   4. Under-specifying the data model (schema and indexes matter enormously).
#   5. Forgetting idempotency in distributed systems.
# =============================================================================

import time
import uuid
import math
import hashlib
import random
import string
import heapq
import threading
import logging
import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, Tuple
from enum import Enum
from abc import ABC, abstractmethod

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# =============================================================================
# DESIGN 1: URL SHORTENER AT SCALE (e.g., bit.ly, TinyURL)
# =============================================================================
#
# REQUIREMENTS:
#   Functional:
#     - POST /shorten  → accepts long URL, returns short code (e.g., abc123)
#     - GET  /{code}   → redirects to original long URL (HTTP 301 / 302)
#     - Optional: custom alias, expiry date, analytics (click counts)
#   Non-Functional:
#     - 100M new URLs/day → ~1200 writes/s
#     - 10B redirects/day → ~115,000 reads/s (reads >> writes, ~10:1 or 100:1)
#     - URL data lives indefinitely (or until TTL)
#     - Latency < 10 ms for redirects (SLA)
#
# CAPACITY ESTIMATION:
#   Writes: 100M URLs/day × 365 = 36.5B URLs/year
#   Storage per URL: code(7B) + long_url(200B) + metadata(100B) ≈ 300 B
#   Total storage: 36.5B × 300 B ≈ 11 TB/year (manageable on a single DB cluster)
#   Read QPS: 115K/s — must be served from cache; DB alone cannot handle this.
#   Cache size: 20% of URLs account for 80% of traffic (Pareto principle)
#               cache top 20% × 300B = 2.2 TB → fits in Redis cluster.
#
# ASCII COMPONENT DIAGRAM:
#
#   Browser / App
#        │
#        ▼
#   ┌─────────────┐   short code   ┌──────────────┐
#   │  Load       │────────────────▶  Redirect     │──── HTTP 301/302 ──▶ Origin
#   │  Balancer   │                │  Service      │◄──── Redis Cache ───┘
#   │  (L7/Nginx) │   POST /shorten│  (stateless)  │
#   └──────┬──────┘────────────────▶──────┬────────┘
#          │                              │
#          │                         cache miss
#          │                              │
#          ▼                              ▼
#   ┌─────────────┐              ┌───────────────┐
#   │  URL Write  │              │  PostgreSQL    │
#   │  Service    │──────────────▶  (urls table)  │
#   │             │              │  Primary +     │
#   └──────┬──────┘              │  Read Replicas │
#          │                     └───────────────┘
#   ┌──────▼──────┐
#   │  Analytics  │  async writes via Kafka
#   │  Service    │──────────────▶  ClickHouse / BigQuery
#   └─────────────┘
#
# DATA MODEL:
#   Table: urls
#     code        CHAR(7)   PRIMARY KEY    -- the short code, indexed
#     long_url    TEXT      NOT NULL
#     user_id     UUID      (nullable for anonymous)
#     created_at  TIMESTAMP DEFAULT NOW()
#     expires_at  TIMESTAMP (nullable)
#     click_count BIGINT    DEFAULT 0     -- eventually consistent; updated async
#   Index: (code) -- already covered by PRIMARY KEY
#   Index: (user_id, created_at) -- for "list my URLs" endpoint
#
# API:
#   POST /api/v1/shorten
#     Request:  { "url": "https://...", "alias": "mylink", "ttl_days": 30 }
#     Response: { "code": "abc123", "short_url": "https://sho.rt/abc123" }
#   GET /{code}
#     Response: HTTP 301 Location: <long_url>  (301 = cached by browser; 302 = not cached)
#   GET /api/v1/stats/{code}
#     Response: { "code": "abc123", "clicks": 12345, "created_at": "..." }

ALPHABET = string.ascii_letters + string.digits  # 62 characters
SHORT_CODE_LENGTH = 7  # 62^7 ≈ 3.5 trillion unique codes


class HashGenerator:
    """
    Generates short codes for URLs.
    APPROACH 1: MD5/SHA256 of long_url → take first 7 chars of base62-encoded hash.
      PROBLEM: collisions (two URLs hash to same code); must check DB and retry.
    APPROACH 2: Base62 encode a globally unique counter (auto-increment ID).
      PROS: no collisions; deterministic.
      CONS: codes are sequential → guessable (security concern for private URLs).
    APPROACH 3: Pre-generate random codes in a pool; assign on demand.
      PROS: no collisions if managed correctly; codes are non-sequential.
      PROD: generate batches offline; store in a Redis set (SPOP for O(1) assignment).
    """

    def __init__(self, strategy: str = "hash"):
        self.strategy = strategy
        self._counter = 0  # for counter-based strategy
        self._lock = threading.Lock()

    def generate(self, long_url: str = "") -> str:
        if self.strategy == "hash":
            return self._hash_based(long_url)
        elif self.strategy == "counter":
            return self._counter_based()
        else:
            return self._random_based()

    def _hash_based(self, url: str) -> str:
        """
        Hash the URL and take the first 7 chars of its base62 representation.
        COLLISION HANDLING: if code exists in DB, append a salt and retry.
        """
        digest = hashlib.sha256(url.encode()).hexdigest()
        # convert hex digest to integer, then encode in base62
        num = int(digest[:16], 16)  # use first 16 hex chars → 64-bit int
        return self._to_base62(num)[:SHORT_CODE_LENGTH]

    def _counter_based(self) -> str:
        """
        Encode a monotonically increasing counter in base62.
        In production, use a distributed counter (Redis INCR, or a dedicated ID service
        like Twitter Snowflake / Flickr ticket server).
        """
        with self._lock:
            self._counter += 1
            return self._to_base62(self._counter).zfill(SHORT_CODE_LENGTH)

    def _random_based(self) -> str:
        """Randomly sample 7 characters from the alphabet (collision-checked externally)."""
        return "".join(random.choices(ALPHABET, k=SHORT_CODE_LENGTH))

    @staticmethod
    def _to_base62(num: int) -> str:
        """Convert an integer to a base62 string (URL-safe, no +/ chars like base64)."""
        if num == 0:
            return ALPHABET[0]
        result = []
        while num > 0:
            result.append(ALPHABET[num % 62])
            num //= 62
        return "".join(reversed(result))


@dataclass
class URLRecord:
    """One row in the urls table."""
    code: str
    long_url: str
    user_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    click_count: int = 0


class URLShortenerService:
    """
    Core URL shortener business logic.
    In production: backed by PostgreSQL (primary) + Redis (cache) + Kafka (analytics).
    """

    def __init__(self, generator: HashGenerator):
        self.generator = generator
        self._db: Dict[str, URLRecord] = {}       # simulates PostgreSQL
        self._cache: Dict[str, str] = {}          # simulates Redis (code → long_url)
        self._analytics_queue: List[Dict] = []    # simulates Kafka topic

    def shorten(self, long_url: str, user_id: Optional[str] = None,
                ttl_days: Optional[int] = None, alias: Optional[str] = None) -> str:
        """
        Create a short code for a long URL.
        IDEMPOTENCY: if the same URL was already shortened by this user, return existing code.
        """
        code = alias or self.generator.generate(long_url)

        # collision detection — retry with different hash if code is taken
        attempts = 0
        while code in self._db and self._db[code].long_url != long_url:
            code = self.generator.generate(long_url + str(attempts))  # add salt
            attempts += 1
            if attempts > 5:
                raise RuntimeError("Failed to generate unique code after 5 attempts")

        if code not in self._db:
            expires_at = time.time() + ttl_days * 86400 if ttl_days else None
            record = URLRecord(code=code, long_url=long_url, user_id=user_id, expires_at=expires_at)
            self._db[code] = record           # persist to PostgreSQL
            self._cache[code] = long_url      # warm cache on write (write-through)

        return code

    def resolve(self, code: str) -> Optional[str]:
        """
        Resolve a short code to its long URL.
        FAST PATH: check Redis cache first; avoids DB hit for popular links.
        REDIRECT TYPE:
          301 Permanent → browser caches redirect; reduces our server load but loses analytics.
          302 Temporary → browser always asks us; we can track clicks and update destinations.
        """
        long_url = self._cache.get(code)  # cache hit (Redis O(1))
        if long_url:
            self._record_click(code)      # async analytics event
            return long_url

        record = self._db.get(code)       # cache miss → hit DB
        if not record:
            return None  # 404

        if record.expires_at and time.time() > record.expires_at:
            return None  # 410 Gone — URL has expired

        self._cache[code] = record.long_url  # populate cache for future requests
        self._record_click(code)
        return record.long_url

    def _record_click(self, code: str):
        """
        Publish click event to Kafka (async, non-blocking).
        Analytics service consumes and aggregates asynchronously.
        NEVER update click_count synchronously on every request — that's a DB write
        on every redirect, which destroys write throughput.
        """
        self._analytics_queue.append({
            "event": "click",
            "code": code,
            "timestamp": time.time(),
        })

    def get_stats(self, code: str) -> Optional[Dict]:
        """Return analytics for a short code (served from a read replica or OLAP store)."""
        record = self._db.get(code)
        if not record:
            return None
        click_count = sum(1 for e in self._analytics_queue if e["code"] == code)
        return {"code": code, "long_url": record.long_url, "clicks": click_count}

    # SCALING CONSIDERATIONS:
    # - Read replicas for the urls table (reads >> writes).
    # - Redis cluster for the cache (cache 20% of hot URLs → serves 80% of traffic).
    # - Use 301 for anonymous links (browser caches → free CDN-like effect).
    # - Use 302 for user-owned links (need click analytics, ability to change destination).
    # - Custom domains: store (custom_domain, code) → long_url mapping in a separate table.
    # - Bloom filter: check if code exists before hitting DB (saves a DB lookup on 404s).


# =============================================================================
# DESIGN 2: RATE LIMITER SERVICE
# =============================================================================
#
# REQUIREMENTS:
#   Functional:
#     - Allow/deny requests based on client ID (user ID, API key, IP address)
#     - Support multiple limits: per-minute, per-hour, per-day
#     - Rate limit at the API gateway layer (global) + per endpoint
#   Non-Functional:
#     - < 1 ms overhead per request check (must not add perceptible latency)
#     - Distributed: same limits enforced across all API gateway nodes
#     - Graceful degradation: if Redis is down, fail open (allow requests)
#
# CAPACITY ESTIMATION:
#   100K QPS through the API gateway
#   Each request = 1 Redis command (INCR + EXPIRE) ≈ 0.1–0.3 ms
#   Redis can handle 1M+ simple commands/sec → not a bottleneck
#
# ASCII COMPONENT DIAGRAM:
#
#   Client Request
#        │
#        ▼
#   ┌────────────┐         ┌──────────────────┐
#   │ API        │──────── ▶  Rate Limiter     │
#   │ Gateway    │◄──allow─│  Middleware       │
#   │            │◄──deny──│  (embedded)       │
#   └────┬───────┘         └──────┬───────────┘
#        │                        │   Redis INCR + EXPIRE
#        │                        ▼
#        │                 ┌──────────────┐
#        │                 │  Redis       │
#        │                 │  Cluster     │
#        │                 │  (counters)  │
#        │                 └──────────────┘
#        ▼
#   Upstream Microservices
#
# ALGORITHMS:
#   Fixed Window:  count requests per fixed window (e.g., per minute 0:00–0:59).
#                  PROBLEM: burst at window boundary (99 + 99 = 198 in 1 second).
#   Sliding Window Log: store timestamp of each request; count in last N seconds.
#                  PROBLEM: memory-intensive for high QPS.
#   Sliding Window Counter: blend of fixed windows; accurate + memory-efficient. ← preferred
#   Token Bucket:  tokens refill at a constant rate; each request consumes one token.
#                  PRO: allows short bursts up to bucket_size.
#   Leaky Bucket:  requests drip out at a constant rate regardless of burst.
#                  USE: output shaping (e.g., SMS gateway sending at 100/s).

class FixedWindowRateLimiter:
    """
    Fixed window counter: straightforward but vulnerable to boundary bursts.
    REDIS KEY: rate:{client_id}:{window_id}
    REDIS COMMAND: INCR key; EXPIRE key window_seconds (on first increment).
    """

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self._store: Dict[str, Tuple[int, float]] = {}  # key → (count, window_start)

    def is_allowed(self, client_id: str) -> bool:
        """Return True if the client is within their rate limit."""
        now = time.time()
        window_id = int(now // self.window_seconds)  # which window are we in?
        key = f"{client_id}:{window_id}"

        if key not in self._store:
            self._store[key] = (1, now)   # first request in this window
            return True

        count, _ = self._store[key]
        if count >= self.limit:
            return False  # limit exceeded for this window

        self._store[key] = (count + 1, now)
        return True


class SlidingWindowCounterRateLimiter:
    """
    Sliding window counter: accurate approximation using two adjacent fixed windows.
    FORMULA: count = current_window_count + prev_window_count × overlap_fraction
    WHERE overlap_fraction = fraction of the previous window that is still within the sliding window.
    REDIS: two INCR keys + pipeline for atomicity.
    ACCURACY: within ~0.003% error at high QPS (Cloudflare's finding).
    """

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self._counts: Dict[str, int] = defaultdict(int)  # window_key → count

    def is_allowed(self, client_id: str) -> bool:
        now = time.time()
        current_window = int(now // self.window_seconds)
        prev_window = current_window - 1

        current_key = f"{client_id}:{current_window}"
        prev_key = f"{client_id}:{prev_window}"

        current_count = self._counts[current_key]
        prev_count = self._counts[prev_key]

        # fraction of the previous window that falls within our sliding window
        elapsed_in_current = now - (current_window * self.window_seconds)
        overlap = 1.0 - (elapsed_in_current / self.window_seconds)

        # weighted count: approximate how many requests are in the last window_seconds
        estimated_count = current_count + (prev_count * overlap)

        if estimated_count >= self.limit:
            return False  # would exceed limit

        self._counts[current_key] += 1  # count this request
        return True


class TokenBucketRateLimiter:
    """
    Token bucket: allows bursts up to bucket_size while enforcing an average rate.
    PRODUCTION: AWS API Gateway uses token bucket; Nginx uses leaky bucket.
    TOKENS REFILL: at rate tokens/second continuously (not in discrete batches).
    REDIS IMPLEMENTATION: store (tokens, last_refill_time) as a hash.
                         Use a Lua script to atomically compute tokens + check limit.
    """

    def __init__(self, capacity: int, refill_rate: float):
        """
        capacity:     maximum tokens the bucket can hold (burst limit)
        refill_rate:  tokens added per second (average rate limit)
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        # per-client state (in production, stored in Redis)
        self._buckets: Dict[str, Tuple[float, float]] = {}  # id → (tokens, last_refill_ts)

    def is_allowed(self, client_id: str, tokens_required: int = 1) -> bool:
        """
        Check if the client has enough tokens. Consume tokens_required on success.
        tokens_required > 1 is used for "expensive" operations (e.g., large file upload = 10 tokens).
        """
        now = time.time()

        if client_id not in self._buckets:
            self._buckets[client_id] = (float(self.capacity), now)

        tokens, last_refill = self._buckets[client_id]

        # refill tokens based on time elapsed since last request
        elapsed = now - last_refill
        tokens = min(self.capacity, tokens + elapsed * self.refill_rate)

        if tokens < tokens_required:
            logger.debug(f"Rate limited: {client_id} has {tokens:.2f} tokens, needs {tokens_required}")
            return False  # insufficient tokens → reject request

        tokens -= tokens_required  # consume tokens
        self._buckets[client_id] = (tokens, now)
        return True


# Redis Lua script for atomic token bucket check + update.
# Run with EVAL on Redis to ensure atomicity (no race conditions between HGET and HSET).
REDIS_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local tokens_required = tonumber(ARGV[4])

-- Read current state from Redis hash
local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(data[1]) or capacity
local last_refill = tonumber(data[2]) or now

-- Refill tokens based on elapsed time
local elapsed = now - last_refill
tokens = math.min(capacity, tokens + elapsed * refill_rate)

-- Check if enough tokens
if tokens < tokens_required then
    return 0  -- rejected
end

-- Consume tokens and persist
tokens = tokens - tokens_required
redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
redis.call('EXPIRE', key, 3600)  -- expire state after 1 hour of inactivity
return 1  -- allowed
"""

# RESPONSE HEADERS for rate-limited APIs (standard practice):
# X-RateLimit-Limit:     100       # total requests allowed per window
# X-RateLimit-Remaining: 42        # requests left in current window
# X-RateLimit-Reset:     1719836400 # Unix timestamp when window resets
# Retry-After:           30         # seconds to wait after 429 Too Many Requests


# =============================================================================
# DESIGN 3: NOTIFICATION SYSTEM
# =============================================================================
#
# REQUIREMENTS:
#   Functional:
#     - Send notifications via: push (mobile), email, SMS, in-app
#     - Notification types: marketing (bulk), transactional (targeted), real-time alerts
#     - Users can opt out of specific notification types
#   Non-Functional:
#     - 1M users; 10M notifications/day for marketing campaigns
#     - Transactional notifications (order shipped) delivered < 5 seconds
#     - At-least-once delivery with idempotency (no duplicate notifications)
#     - Scale to 100M users in the future
#
# CAPACITY ESTIMATION:
#   10M/day = ~115 notifications/s average; peak (campaign launch) = 10K/s
#   Storage per notification: ~500 B → 10M × 500 B = 5 GB/day
#   Retained 30 days → 150 GB (manageable in a single Cassandra cluster)
#
# FANOUT STRATEGIES:
#   FANOUT ON WRITE (push model):
#     When a celebrity posts, immediately write to all N followers' inboxes.
#     PROS: reads are O(1) — just read your inbox.
#     CONS: write amplification — 1 post × 1M followers = 1M writes.
#     USE: users with < 10K followers; real-time notifications.
#
#   FANOUT ON READ (pull model):
#     Don't write to inboxes; let each user fetch and aggregate on read.
#     PROS: no write amplification; good for celebrity accounts.
#     CONS: read is expensive — must aggregate from many sources.
#     USE: celebrity/influencer accounts; archive access.
#
#   HYBRID: fanout-on-write for regular users; fanout-on-read for celebrities.
#
# ASCII COMPONENT DIAGRAM:
#
#   Trigger (User action / Marketing job / System alert)
#        │
#        ▼
#   ┌────────────────┐
#   │  Notification  │──── persist event ──▶  PostgreSQL (notification log)
#   │  Service API   │
#   └───────┬────────┘
#           │  publish to Kafka topic: "notifications"
#           ▼
#   ┌───────────────┐
#   │  Kafka        │  (at-least-once delivery; persisted for replay)
#   │  Cluster      │
#   └───────┬───────┘
#     ┌─────┴──────┐────────────────────────┐
#     ▼            ▼                        ▼
# ┌───────┐  ┌──────────┐         ┌────────────────┐
# │ Push  │  │  Email   │         │  SMS           │
# │Worker │  │  Worker  │         │  Worker        │
# │(FCM/  │  │(SendGrid)│         │(Twilio/SNS)    │
# │APNS)  │  └──────────┘         └────────────────┘
# └───────┘
#           ┌──────────────────────────────────────┐
#           │  User Preference Service              │
#           │  (check opt-out before sending)      │
#           └──────────────────────────────────────┘

class NotificationChannel(Enum):
    PUSH  = "push"    # mobile push (FCM for Android, APNS for iOS)
    EMAIL = "email"   # transactional email (SendGrid, SES)
    SMS   = "sms"     # SMS (Twilio, AWS SNS)
    INAPP = "inapp"   # in-app notification (stored, read when app opens)


@dataclass
class NotificationRequest:
    """Represents a notification to be sent to one or more users."""
    notification_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_ids: List[str] = field(default_factory=list)  # empty = broadcast
    title: str = ""
    body: str = ""
    channels: List[NotificationChannel] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)  # deep link, data
    priority: str = "normal"   # "high" for real-time alerts (bypasses FCM batching)
    idempotency_key: str = ""  # prevents duplicate sends on retry


class UserPreferenceService:
    """
    Stores user notification opt-in/opt-out preferences.
    PRODUCTION: backed by DynamoDB or PostgreSQL; cached in Redis.
    """

    def __init__(self):
        # user_id → set of opted-out channels
        self._opt_outs: Dict[str, set] = defaultdict(set)

    def opt_out(self, user_id: str, channel: NotificationChannel):
        self._opt_outs[user_id].add(channel)

    def opt_in(self, user_id: str, channel: NotificationChannel):
        self._opt_outs[user_id].discard(channel)

    def get_allowed_channels(
        self, user_id: str, requested: List[NotificationChannel]
    ) -> List[NotificationChannel]:
        """Return channels the user has not opted out of."""
        opted_out = self._opt_outs.get(user_id, set())
        return [ch for ch in requested if ch not in opted_out]


class FanoutService:
    """
    Handles the two fanout strategies.
    In production, this publishes individual per-user messages to Kafka.
    Worker processes (one per channel) consume from Kafka and call the external APIs.
    """

    def __init__(self, prefs: UserPreferenceService):
        self.prefs = prefs
        self._user_follower_counts: Dict[str, int] = {}  # used for hybrid strategy
        self._outbox: List[Dict] = []  # simulates Kafka topic messages
        self._celebrity_threshold = 10_000  # users with > 10K followers use pull model

    def set_follower_count(self, user_id: str, count: int):
        self._user_follower_counts[user_id] = count

    def fanout_write(self, request: NotificationRequest, all_follower_ids: List[str]):
        """
        FANOUT ON WRITE: immediately enqueue one message per follower.
        USE: regular users. O(followers) writes — acceptable for small follower counts.
        """
        for follower_id in all_follower_ids:
            allowed_channels = self.prefs.get_allowed_channels(
                follower_id, request.channels
            )
            if not allowed_channels:
                continue  # user has opted out of all requested channels

            # Publish one work item per user per channel to Kafka
            for channel in allowed_channels:
                self._outbox.append({
                    "notification_id": request.notification_id,
                    "user_id":         follower_id,
                    "channel":         channel.value,
                    "title":           request.title,
                    "body":            request.body,
                    "priority":        request.priority,
                })
        logger.info(f"Fanout-write: queued {len(all_follower_ids)} notifications")

    def hybrid_fanout(
        self,
        publisher_id: str,
        request: NotificationRequest,
        followers: List[str],
    ):
        """
        HYBRID: push to regular followers inline; celebrities' followers pull on-demand.
        Regular followers → fanout-on-write (immediate queue entry).
        Celebrity followers → store event pointer; followers fetch when they open app.
        """
        follower_count = self._user_follower_counts.get(publisher_id, 0)

        if follower_count > self._celebrity_threshold:
            # Celebrity: store only the event pointer, not per-user copies
            self._outbox.append({
                "type":            "celebrity_post_pointer",
                "notification_id": request.notification_id,
                "publisher_id":    publisher_id,
                "title":           request.title,
                "pull_required":   True,  # followers must fetch when they open app
            })
            logger.info(f"Celebrity fanout-on-read for {publisher_id} ({follower_count} followers)")
        else:
            self.fanout_write(request, followers)

    def get_queued_count(self) -> int:
        return len(self._outbox)


class NotificationDeduplicator:
    """
    Prevents duplicate notifications for at-least-once delivery.
    REDIS SETNX pattern: SET notification_id NX EX 86400
    Returns True if this is a new notification (safe to send).
    Returns False if already sent (skip to avoid duplicate).
    """

    def __init__(self):
        self._sent: Dict[str, float] = {}  # notification_id → sent_at
        self._ttl = 86400.0  # deduplicate within 24 hours

    def mark_if_new(self, notification_id: str) -> bool:
        """Atomically check-and-set. Returns True if new (first time seen)."""
        now = time.time()
        if notification_id in self._sent:
            if now - self._sent[notification_id] < self._ttl:
                return False  # duplicate — skip
        self._sent[notification_id] = now
        return True  # new notification — safe to send


# =============================================================================
# DESIGN 4: DISTRIBUTED JOB SCHEDULER
# =============================================================================
#
# REQUIREMENTS:
#   Functional:
#     - Schedule jobs to run at a specific time or on a cron schedule
#     - At-least-once execution guarantee (retry on failure)
#     - Distributed: multiple workers pick up jobs; no duplicate execution
#     - Cancel or pause scheduled jobs
#   Non-Functional:
#     - Support 100K scheduled jobs; 10K executions/minute peak
#     - Job execution latency < 1 second from scheduled time
#     - Fault-tolerant: worker crash doesn't lose the job
#
# CAPACITY ESTIMATION:
#   100K jobs; mostly idle; ~10K fire simultaneously per minute at peak
#   Job metadata: 100K × 1KB = 100 MB (fits in a single PostgreSQL table easily)
#
# ASCII COMPONENT DIAGRAM:
#
#   API (create/cancel/list jobs)
#        │
#        ▼
#   ┌────────────────┐
#   │  Scheduler     │──── cron evaluation ──▶  Job Queue (Redis Sorted Set)
#   │  Service       │                           │  (score = next_run_at timestamp)
#   └────────────────┘                           │
#                                                ▼
#   ┌────────────────────────────────────────────────────┐
#   │  Worker Pool (N workers, each polls the queue)     │
#   │  Worker claims job via Redis ZPOPMIN (atomic)      │
#   │  Executes job; on success → mark done              │
#   │  On failure → increment retry_count; re-enqueue   │
#   └───────────────────────────┬────────────────────────┘
#                               │ write execution history
#                               ▼
#                        ┌─────────────┐
#                        │ PostgreSQL   │
#                        │ jobs table  │
#                        │ job_runs    │
#                        └─────────────┘
#
# DATA MODEL:
#   Table: jobs
#     id            UUID      PRIMARY KEY
#     name          TEXT
#     handler_type  TEXT       -- which worker type handles this job
#     payload       JSONB      -- job-specific data
#     schedule      TEXT       -- cron expression OR null (one-shot)
#     next_run_at   TIMESTAMP  -- when to fire next; indexed
#     status        TEXT       -- active, paused, cancelled
#     max_retries   INT        DEFAULT 3
#     created_at    TIMESTAMP
#   Table: job_runs
#     id            UUID       PRIMARY KEY
#     job_id        UUID       FK jobs(id)
#     started_at    TIMESTAMP
#     finished_at   TIMESTAMP
#     status        TEXT       -- running, success, failed
#     retry_count   INT
#     error_msg     TEXT
#   Index: jobs(next_run_at) WHERE status = 'active'  -- critical for scheduler poll

class JobStatus(Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCESS   = "success"
    FAILED    = "failed"
    CANCELLED = "cancelled"
    PAUSED    = "paused"


@dataclass
class Job:
    """Represents a scheduled job definition."""
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    handler_type: str = ""              # which handler processes this type
    payload: Dict[str, Any] = field(default_factory=dict)
    cron_expression: Optional[str] = None  # None = one-shot job
    next_run_at: float = field(default_factory=time.time)
    status: JobStatus = JobStatus.PENDING
    max_retries: int = 3
    retry_count: int = 0
    retry_delay_seconds: float = 60.0   # initial retry delay; use exponential backoff


class CronParser:
    """
    Simplified cron expression parser.
    STANDARD CRON: minute hour day_of_month month day_of_week
    EXAMPLES:
      "0 * * * *"     → every hour at minute 0
      "*/5 * * * *"   → every 5 minutes
      "0 9 * * MON"   → every Monday at 9:00 AM
    PRODUCTION: use python-crontab, croniter, or APScheduler libraries.
    """

    def next_run(self, cron_expr: str, after: float) -> float:
        """
        Compute the next run timestamp after `after`.
        This is a simplified simulation — real implementation parses all 5 fields.
        """
        # Simplified: only handle "*/N * * * *" (every N minutes) for demo purposes
        parts = cron_expr.strip().split()
        if len(parts) == 5 and parts[0].startswith("*/"):
            interval_minutes = int(parts[0][2:])
            interval_seconds = interval_minutes * 60
            # next run = ceiling to next interval boundary
            next_ts = math.ceil(after / interval_seconds) * interval_seconds
            return next_ts
        elif parts[0] == "0" and parts[1] == "*":
            # every hour
            next_ts = math.ceil(after / 3600) * 3600
            return next_ts
        else:
            # fallback: run 60 seconds from now (production would use a full parser)
            return after + 60


class JobQueue:
    """
    Priority queue of jobs sorted by next_run_at (earliest first).
    PRODUCTION: Redis sorted set (ZADD score=next_run_at, ZPOPMIN for atomic claim).
    ZPOPMIN ensures only one worker picks up a job — distributed mutex via Redis.
    """

    def __init__(self):
        self._heap: List[Tuple[float, str, Job]] = []  # (next_run_at, job_id, job)
        self._lock = threading.Lock()

    def enqueue(self, job: Job):
        """Add or re-add a job to the queue."""
        with self._lock:
            heapq.heappush(self._heap, (job.next_run_at, job.job_id, job))

    def dequeue_due(self) -> List[Job]:
        """
        Atomically dequeue all jobs due for execution (next_run_at <= now).
        REDIS: ZRANGEBYSCORE queue 0 <now_timestamp> → ZREM (non-atomic).
               Use Lua script for atomicity: ZRANGEBYSCORE + ZREM in one operation.
        """
        now = time.time()
        due_jobs = []
        with self._lock:
            while self._heap and self._heap[0][0] <= now:
                _, _, job = heapq.heappop(self._heap)
                due_jobs.append(job)
        return due_jobs


class Worker:
    """
    Job worker: picks up due jobs from the queue and executes them.
    Each worker runs in its own thread. Multiple workers process jobs concurrently.
    AT-LEAST-ONCE: if a worker crashes mid-execution, a "heartbeat timeout" mechanism
    detects the zombie job and re-enqueues it.
    """

    def __init__(self, worker_id: str, handlers: Dict[str, Callable[[Job], bool]]):
        self.worker_id = worker_id
        self.handlers = handlers  # handler_type → callable(job) → success bool

    def execute(self, job: Job) -> bool:
        """
        Run the job handler. Return True = success, False = failure (will retry).
        PRODUCTION: execution happens in a subprocess or container for isolation.
        """
        handler = self.handlers.get(job.handler_type)
        if not handler:
            logger.error(f"[Worker {self.worker_id}] No handler for type '{job.handler_type}'")
            return False

        try:
            logger.info(f"[Worker {self.worker_id}] Executing job {job.job_id} ({job.name})")
            success = handler(job)
            return success
        except Exception as e:
            logger.error(f"[Worker {self.worker_id}] Job {job.job_id} raised exception: {e}")
            return False


class JobScheduler:
    """
    Orchestrates the scheduling loop: evaluates due jobs, dispatches to workers,
    handles retries with exponential backoff, reschedules recurring jobs.
    """

    def __init__(self, queue: JobQueue, cron_parser: CronParser):
        self.queue = queue
        self.cron_parser = cron_parser
        self._job_store: Dict[str, Job] = {}  # simulates PostgreSQL jobs table

    def register(self, job: Job):
        """Register a new job and add it to the scheduling queue."""
        self._job_store[job.job_id] = job
        self.queue.enqueue(job)
        logger.info(f"Registered job {job.job_id} ({job.name}), "
                    f"next run at {job.next_run_at:.0f}")

    def tick(self, worker: Worker):
        """
        One iteration of the scheduler loop.
        PRODUCTION: run in a tight loop (sleep 100 ms between ticks).
        Each tick: fetch due jobs, dispatch to workers, handle results.
        """
        due_jobs = self.queue.dequeue_due()

        for job in due_jobs:
            if job.status == JobStatus.CANCELLED:
                continue  # skip cancelled jobs

            job.status = JobStatus.RUNNING
            success = worker.execute(job)

            if success:
                job.status = JobStatus.SUCCESS
                job.retry_count = 0  # reset on success
                logger.info(f"Job {job.job_id} completed successfully")

                # Reschedule recurring job
                if job.cron_expression:
                    job.next_run_at = self.cron_parser.next_run(
                        job.cron_expression, time.time()
                    )
                    job.status = JobStatus.PENDING
                    self.queue.enqueue(job)  # put back in queue for next run
                    logger.info(f"Rescheduled job {job.job_id} for {job.next_run_at:.0f}")
            else:
                job.retry_count += 1
                if job.retry_count <= job.max_retries:
                    # Exponential backoff: delay doubles on each retry
                    backoff = job.retry_delay_seconds * (2 ** (job.retry_count - 1))
                    job.next_run_at = time.time() + backoff
                    job.status = JobStatus.PENDING
                    self.queue.enqueue(job)  # re-enqueue for retry
                    logger.warning(f"Job {job.job_id} failed, retry {job.retry_count}/{job.max_retries} "
                                   f"in {backoff:.0f}s")
                else:
                    job.status = JobStatus.FAILED
                    logger.error(f"Job {job.job_id} permanently failed after {job.max_retries} retries")
                    # PRODUCTION: send alert; move to dead-letter job table for manual inspection

    def cancel(self, job_id: str):
        """Mark a job as cancelled. It will be skipped on next dequeue."""
        job = self._job_store.get(job_id)
        if job:
            job.status = JobStatus.CANCELLED
            logger.info(f"Cancelled job {job_id}")

    # SCALING CONSIDERATIONS:
    # - Multiple scheduler instances: use leader election (via Redis SETNX or ZooKeeper)
    #   so only ONE scheduler is the "leader" that dequeues at any time.
    #   OR: use a distributed job queue (Redis ZPOPMIN is atomic → safe for multiple pollers).
    # - Worker pools: scale workers horizontally; each worker is stateless.
    # - Observability: track job execution latency (scheduled_at vs started_at).
    #   Alert if p99 exceeds 5 seconds → means queue is backed up.
    # - Idempotency in job handlers: jobs may be re-executed on retry; handlers must be safe.


# =============================================================================
# DEMO: All Four Designs
# =============================================================================

def demo():
    print("\n" + "="*60)
    print("DESIGN 1: URL SHORTENER")
    print("="*60)

    gen = HashGenerator(strategy="counter")
    svc = URLShortenerService(gen)

    code1 = svc.shorten("https://www.example.com/very/long/url/path", user_id="user-1")
    code2 = svc.shorten("https://openai.com/blog/gpt-4", user_id="user-2", ttl_days=30)
    print(f"\nShortened URL 1 → code: {code1}")
    print(f"Shortened URL 2 → code: {code2}")
    print(f"Resolve {code1} → {svc.resolve(code1)}")
    print(f"Stats {code1}: {svc.get_stats(code1)}")

    print("\n" + "="*60)
    print("DESIGN 2: RATE LIMITER")
    print("="*60)

    tb = TokenBucketRateLimiter(capacity=10, refill_rate=2.0)  # 2 tokens/sec
    client = "user-42"
    results = []
    for i in range(15):
        allowed = tb.is_allowed(client)
        results.append("ALLOW" if allowed else "DENY ")
    print(f"\nToken Bucket (capacity=10, rate=2/s) — 15 rapid requests:")
    print(f"  {' '.join(results)}")

    sw = SlidingWindowCounterRateLimiter(limit=5, window_seconds=60)
    results2 = [("ALLOW" if sw.is_allowed("userA") else "DENY ") for _ in range(7)]
    print(f"\nSliding Window (limit=5/min) — 7 requests: {' '.join(results2)}")

    print("\n" + "="*60)
    print("DESIGN 3: NOTIFICATION SYSTEM")
    print("="*60)

    prefs = UserPreferenceService()
    prefs.opt_out("user-5", NotificationChannel.EMAIL)  # user-5 opted out of email

    fanout = FanoutService(prefs)
    req = NotificationRequest(
        title="Your order shipped!",
        body="Your order #1234 is on its way.",
        channels=[NotificationChannel.PUSH, NotificationChannel.EMAIL],
    )
    followers = [f"user-{i}" for i in range(10)]
    fanout.fanout_write(req, followers)
    print(f"\nQueued notifications (10 users × 2 channels - 1 opt-out): "
          f"{fanout.get_queued_count()}")

    dedup = NotificationDeduplicator()
    nid = "notif-abc123"
    print(f"\nFirst send attempt (should allow): {dedup.mark_if_new(nid)}")
    print(f"Duplicate attempt (should reject): {dedup.mark_if_new(nid)}")

    print("\n" + "="*60)
    print("DESIGN 4: DISTRIBUTED JOB SCHEDULER")
    print("="*60)

    queue = JobQueue()
    cron = CronParser()
    scheduler = JobScheduler(queue, cron)

    execute_counts = defaultdict(int)

    def send_report(job: Job) -> bool:
        execute_counts[job.job_id] += 1
        print(f"  Executed: {job.name} (payload={job.payload})")
        return True

    def flaky_cleanup(job: Job) -> bool:
        execute_counts[job.job_id] += 1
        # fail on first two attempts to demonstrate retry
        return execute_counts[job.job_id] > 2

    worker = Worker("w-1", {
        "report":  send_report,
        "cleanup": flaky_cleanup,
    })

    # Schedule a one-shot job to run immediately
    job1 = Job(name="Daily Report", handler_type="report",
               payload={"report_type": "sales"}, next_run_at=time.time())

    # Schedule a recurring job (every 5 minutes) starting now
    job2 = Job(name="DB Cleanup", handler_type="cleanup",
               cron_expression="*/5 * * * *", next_run_at=time.time(),
               max_retries=3, retry_delay_seconds=5)

    scheduler.register(job1)
    scheduler.register(job2)

    print(f"\nRunning scheduler tick ...")
    scheduler.tick(worker)  # executes due jobs

    print(f"\nJob1 status: {job1.status.value}")
    print(f"Job2 status: {job2.status.value} (flaky, may have been retried)")
    print(f"Jobs in queue after tick: {len(queue._heap)}")

    print("\nDemo complete.")


if __name__ == "__main__":
    demo()
