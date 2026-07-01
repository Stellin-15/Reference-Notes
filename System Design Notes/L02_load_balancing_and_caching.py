# =============================================================================
# WHAT: Load Balancing Algorithms and Caching Strategies
# WHY:  Traffic distribution and caching are the first line of defense against
#       scale — they determine how well a system absorbs traffic spikes, reduces
#       latency, and avoids overloading backend services.
# LEVEL: Intermediate → Advanced (System Design Interview / Production Ready)
# =============================================================================
#
# CONCEPT OVERVIEW:
#   Load Balancing  → distributing incoming requests across multiple servers to
#                     maximize throughput, minimize latency, and avoid single
#                     points of failure.
#   Caching         → storing copies of expensive computation results or data
#                     closer to the consumer to avoid re-fetching or re-computing.
#
# PRODUCTION USE CASES:
#   - Netflix uses weighted round-robin + health checks to distribute playback
#     requests across regional servers.
#   - Cloudflare's CDN sits in front of millions of origins, absorbing the vast
#     majority of traffic at the edge before it reaches the origin server.
#   - Redis is used by Twitter/X as an application-layer cache for timelines.
#
# COMMON MISTAKES:
#   1. Caching mutable data without a TTL  → stale data served indefinitely.
#   2. Not implementing health checks      → dead backends still receive traffic.
#   3. Using sticky sessions + auto-scaling → new nodes never get traffic.
#   4. Cache stampede on cold start        → thundering herd hammers the database.
#   5. Forgetting cache warming after deploy → cache miss storm on go-live.
#   6. Treating CDN Cache-Control headers as an afterthought.
# =============================================================================

import time
import hashlib
import threading
import random
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Callable, Any, Tuple
from enum import Enum

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# =============================================================================
# SECTION 1: L4 vs L7 LOAD BALANCING
# =============================================================================
# L4 (Transport Layer) → operates on TCP/UDP packets. Routes by IP + port only.
#   - No HTTP awareness; cannot inspect URLs, cookies, or headers.
#   - Extremely fast — no packet reassembly required.
#   - Used by: AWS Network Load Balancer (NLB), HAProxy in TCP mode.
#   - Good for: database connections, WebSockets at massive scale, SMTP.
#
# L7 (Application Layer) → reads and parses HTTP headers, cookies, URL paths.
#   - Can route /api/* to one server pool, /static/* to another pool.
#   - Supports content-based routing, SSL termination, request rewriting.
#   - Used by: AWS ALB, Nginx (http mode), HAProxy (http mode), Envoy.
#   - Good for: microservices routing, A/B testing, canary deployments.
#   - Overhead: must buffer and parse the full HTTP request before routing.

# =============================================================================
# SECTION 2: CORE DATA MODEL
# =============================================================================

@dataclass
class Backend:
    """Represents one upstream server in the load balancer pool."""
    host: str
    port: int
    weight: int = 1           # for weighted algorithms — higher = more traffic
    is_healthy: bool = True   # toggled by health-check loop
    active_connections: int = 0  # tracked by least-connections algorithm
    current_weight: int = 0   # internal counter for smooth weighted round-robin

    @property
    def address(self) -> str:
        """Canonical address string, used as dict keys and log output."""
        return f"{self.host}:{self.port}"


# =============================================================================
# SECTION 3: LOAD BALANCING ALGORITHMS
# =============================================================================

class RoundRobinBalancer:
    """
    ROUND-ROBIN: requests are distributed evenly in a circular sequence.
    WHY: simple, stateless, works well when all backends have identical capacity.
    LIMITATION: ignores server load — a slow server still gets equal share.
    PRODUCTION: DNS round-robin, simple Nginx upstream blocks.
    """

    def __init__(self, backends: List[Backend]):
        self.backends = backends
        self._index = 0           # tracks which backend is next in rotation
        self._lock = threading.Lock()  # thread-safe index increment

    def next_backend(self) -> Optional[Backend]:
        """Return the next healthy backend in round-robin order."""
        with self._lock:
            healthy = [b for b in self.backends if b.is_healthy]
            if not healthy:
                return None   # all backends down — propagate error to caller
            backend = healthy[self._index % len(healthy)]
            self._index += 1  # advance pointer; wraps via modulo on next call
            return backend


class WeightedRoundRobinBalancer:
    """
    WEIGHTED ROUND-ROBIN: backends with higher weight receive proportionally
    more requests. Useful when servers have different capacities.
    ALGORITHM: Nginx smooth WRR (avoids bursty assignment):
      Each step → add static weight to every backend's current_weight,
                  pick the highest current_weight winner,
                  subtract total_weight from winner so others catch up.
    EXAMPLE: weights [3, 1, 2] → sequence: A, A, B, A, C, A, C, B, ...
    PRODUCTION: Nginx upstream `weight` directive uses this exact algorithm.
    """

    def __init__(self, backends: List[Backend]):
        self.backends = backends
        for b in backends:
            b.current_weight = 0  # ensure smooth WRR starts clean

    def next_backend(self) -> Optional[Backend]:
        healthy = [b for b in self.backends if b.is_healthy]
        if not healthy:
            return None

        total_weight = sum(b.weight for b in healthy)

        # Step 1: raise every backend's running weight by its static weight
        for b in healthy:
            b.current_weight += b.weight

        # Step 2: pick the backend with the highest accumulated weight
        selected = max(healthy, key=lambda b: b.current_weight)

        # Step 3: penalise the winner so all backends converge over time
        selected.current_weight -= total_weight
        return selected


class LeastConnectionsBalancer:
    """
    LEAST CONNECTIONS: route to the backend with fewest active connections.
    WHY: fairer than round-robin when request durations vary widely
         (e.g., file uploads vs quick API responses on the same pool).
    OVERHEAD: must track active connection count per backend.
    PRODUCTION: HAProxy default mode, AWS ALB "least outstanding requests".
    """

    def __init__(self, backends: List[Backend]):
        self.backends = backends
        self._lock = threading.Lock()

    def acquire(self, backend: Backend):
        """Increment counter when a request starts on this backend."""
        with self._lock:
            backend.active_connections += 1

    def release(self, backend: Backend):
        """Decrement counter when a request finishes on this backend."""
        with self._lock:
            backend.active_connections = max(0, backend.active_connections - 1)

    def next_backend(self) -> Optional[Backend]:
        healthy = [b for b in self.backends if b.is_healthy]
        if not healthy:
            return None
        # ties broken by list order (first backend wins) — acceptable in practice
        return min(healthy, key=lambda b: b.active_connections)


class IPHashBalancer:
    """
    IP HASH: client IP is hashed to always land on the same backend.
    WHY: provides sticky sessions without requiring cookies — useful for
         WebSocket connections and in-memory session state.
    LIMITATION: breaks even distribution behind NAT (many clients → one IP
                → one backend gets all that traffic → hot server problem).
    PRODUCTION: Nginx `ip_hash` directive; also used in consistent hashing rings.
    """

    def __init__(self, backends: List[Backend]):
        self.backends = backends

    def next_backend(self, client_ip: str) -> Optional[Backend]:
        healthy = [b for b in self.backends if b.is_healthy]
        if not healthy:
            return None
        # MD5 produces a stable numeric hash; modulo maps to a backend index
        hash_val = int(hashlib.md5(client_ip.encode()).hexdigest(), 16)
        index = hash_val % len(healthy)  # deterministic — same IP → same index
        return healthy[index]


# =============================================================================
# SECTION 4: HEALTH CHECKS
# =============================================================================
# Health checks let the load balancer detect dead backends before routing real
# traffic to them. Without health checks, a crashed backend gets requests and
# every user hitting it gets a 502 error.
#
# ACTIVE CHECKS  → LB probes each backend periodically (HTTP GET /health, TCP connect).
# PASSIVE CHECKS → LB watches real traffic; marks unhealthy after N consecutive 5xx.
#
# KEY PARAMETERS:
#   interval         → how often to probe (10 s is typical)
#   timeout          → max wait for response before counting as failure (2–5 s)
#   failure_threshold → consecutive failures before marking unhealthy (3 is typical)
#   recovery_threshold → consecutive successes before marking healthy again (2 typical)

class HealthChecker:
    """
    Simulates an active health check loop that updates backend.is_healthy.
    In production: Nginx `health_check` module, AWS Target Group health checks,
                   Consul health check, or custom heartbeat endpoints.
    Uses hysteresis (thresholds) to prevent flapping (rapid healthy/unhealthy toggling).
    """

    def __init__(
        self,
        backends: List[Backend],
        check_fn: Callable[[Backend], bool],  # returns True if backend is healthy
        interval: float = 10.0,
        failure_threshold: int = 3,
        recovery_threshold: int = 2,
    ):
        self.backends = backends
        self.check_fn = check_fn
        self.interval = interval
        self.failure_threshold = failure_threshold
        self.recovery_threshold = recovery_threshold
        # per-backend streak counters (reset on state flip)
        self._failure_counts: Dict[str, int] = defaultdict(int)
        self._success_counts: Dict[str, int] = defaultdict(int)

    def check_once(self):
        """Run one round of health checks across all backends."""
        for backend in self.backends:
            ok = self.check_fn(backend)  # simulate HTTP GET /health
            addr = backend.address

            if ok:
                self._failure_counts[addr] = 0  # reset failure streak on success
                self._success_counts[addr] += 1
                if (not backend.is_healthy and
                        self._success_counts[addr] >= self.recovery_threshold):
                    backend.is_healthy = True
                    logger.info(f"Backend {addr} recovered → HEALTHY")
            else:
                self._success_counts[addr] = 0  # reset success streak on failure
                self._failure_counts[addr] += 1
                if (backend.is_healthy and
                        self._failure_counts[addr] >= self.failure_threshold):
                    backend.is_healthy = False
                    logger.warning(f"Backend {addr} → UNHEALTHY (removed from pool)")


# =============================================================================
# SECTION 5: STICKY SESSIONS
# =============================================================================
# Sticky sessions (session affinity) ensure a client always hits the same backend.
# USE WHEN: session state is stored locally on the backend (in-memory, local disk).
# PROBLEM: breaks auto-scaling — new nodes never receive traffic from existing clients.
# BETTER: externalise session state to Redis → any backend can serve any client.

class StickySessionBalancer:
    """
    Cookie-based sticky sessions.
    First request → assign a backend via round-robin, store mapping in session_map.
    Subsequent requests → read session_id and route to pinned backend.
    PRODUCTION: AWS ALB uses the AWSALB cookie; Nginx has the `sticky` module.
    FAILURE MODE: if pinned backend dies, re-assign to a healthy backend (session data lost).
    """

    def __init__(self, backends: List[Backend]):
        self.backends = backends
        self._session_map: Dict[str, str] = {}  # session_id → backend.address
        self._rr = RoundRobinBalancer(backends)  # fallback for new sessions

    def next_backend(self, session_id: Optional[str]) -> Optional[Backend]:
        if session_id and session_id in self._session_map:
            pinned_addr = self._session_map[session_id]
            for b in self.backends:
                if b.address == pinned_addr and b.is_healthy:
                    return b  # serve from pinned backend — happy path

        # no session cookie, or pinned backend is down → pick fresh backend
        backend = self._rr.next_backend()
        if backend and session_id:
            self._session_map[session_id] = backend.address  # pin for future requests
        return backend


# =============================================================================
# SECTION 6: CDN FUNDAMENTALS
# =============================================================================
# CDN (Content Delivery Network) = globally distributed edge caches.
# Edge nodes (PoPs — Points of Presence) cache responses close to users.
# Subsequent requests for the same resource are served from the edge;
# the origin server never sees them.
#
# CACHE-CONTROL HEADER (the primary CDN control mechanism):
#   public, max-age=86400          → CDN + browser cache for 24 hours
#   private, max-age=3600          → browser only, NOT CDN (personal data)
#   no-store                       → never cache anywhere (sensitive responses)
#   stale-while-revalidate=60      → serve stale for 60 s while refreshing async
#   stale-if-error=3600            → serve stale if origin returns 5xx
#   immutable                      → browser: never revalidate during max-age
#
# CACHE INVALIDATION (the genuinely hard problem):
#   1. TTL expiry       → wait for max-age to expire (stale window exists)
#   2. Purge API        → Cloudflare/Fastly provide purge-by-URL or tag APIs
#   3. Cache tags        → tag objects; purge entire tag category instantly
#   4. Filename hashing  → embed content hash in URL; new content = new URL

def build_cache_control_header(
    is_public: bool = True,
    max_age: int = 3600,
    stale_while_revalidate: int = 0,
    stale_if_error: int = 0,
    immutable: bool = False,
    no_store: bool = False,
) -> str:
    """
    Build a Cache-Control header value string for HTTP responses.

    GUIDANCE BY RESOURCE TYPE:
      Static assets (hashed filename) → public, max-age=31536000, immutable
      API responses (shared data)     → public, max-age=60, stale-while-revalidate=30
      User-specific API responses     → private, max-age=300
      Auth tokens / payment pages     → no-store
      HTML pages                      → no-store or max-age=0
    """
    if no_store:
        return "no-store"

    parts = ["public" if is_public else "private"]
    parts.append(f"max-age={max_age}")

    if immutable:
        parts.append("immutable")  # tells browser: don't even check; trust max-age

    if stale_while_revalidate:
        # serve stale content immediately while refreshing in background
        parts.append(f"stale-while-revalidate={stale_while_revalidate}")

    if stale_if_error:
        # graceful degradation: serve stale if origin is down
        parts.append(f"stale-if-error={stale_if_error}")

    return ", ".join(parts)


# Pre-built headers for common resource types
STATIC_ASSET_HEADER = build_cache_control_header(
    is_public=True,
    max_age=31_536_000,   # 1 year — safe because filename includes content hash
    immutable=True,       # browser never revalidates; assumes URL is unique per version
)

API_RESPONSE_HEADER = build_cache_control_header(
    is_public=True,
    max_age=60,                   # fresh for 60 seconds
    stale_while_revalidate=30,    # serve stale for 30 more seconds while refreshing
    stale_if_error=3600,          # serve stale for 1 hour if origin is down
)

PRIVATE_USER_HEADER = build_cache_control_header(
    is_public=False,
    max_age=300,          # browser caches for 5 minutes; CDN does NOT cache
)

SENSITIVE_HEADER = build_cache_control_header(no_store=True)  # never cache


# =============================================================================
# SECTION 7: CACHE HIERARCHY
# =============================================================================
# Browser → CDN Edge → API Gateway → Application (Redis) → Database
#
# Each layer absorbs traffic, reducing load and latency at the next layer.
# Goal: answer every request as close to the client as physically possible.

class CacheLayer(Enum):
    BROWSER     = "browser"      # zero network hops; lives on user's machine
    CDN         = "cdn"          # ~5–20 ms; nearest edge PoP
    API_GATEWAY = "api_gateway"  # ~10–30 ms; before app servers are reached
    APPLICATION = "application"  # ~1–5 ms; in-process or Redis
    DATABASE    = "database"     # ~5–50 ms; last resort


class TieredCache:
    """
    Simplified multi-layer cache illustrating the lookup hierarchy.
    In production, each layer is a separate system.
    """

    def __init__(self):
        # one dict per layer simulates independent cache stores
        self._stores: Dict[CacheLayer, Dict[str, Any]] = {
            layer: {} for layer in CacheLayer
        }

    def get(self, key: str) -> Tuple[Optional[Any], CacheLayer]:
        """
        Walk layers from fastest to slowest. Return (value, layer_that_hit).
        Stops as soon as a hit is found — avoids touching slower layers unnecessarily.
        """
        for layer in [
            CacheLayer.BROWSER,
            CacheLayer.CDN,
            CacheLayer.API_GATEWAY,
            CacheLayer.APPLICATION,
        ]:
            val = self._stores[layer].get(key)
            if val is not None:
                return val, layer  # cache hit — return immediately

        return None, CacheLayer.DATABASE  # miss at all layers → must hit DB

    def set(self, key: str, value: Any, layers: List[CacheLayer]):
        """Populate one or more cache layers (e.g., after a DB read)."""
        for layer in layers:
            self._stores[layer][key] = value

    def invalidate(self, key: str, layers: Optional[List[CacheLayer]] = None):
        """Remove a key from the specified layers, or all layers if unspecified."""
        target = layers or list(CacheLayer)
        for layer in target:
            self._stores[layer].pop(key, None)


# =============================================================================
# SECTION 8: CACHE-ASIDE, WRITE-THROUGH, WRITE-BEHIND PATTERNS
# =============================================================================

class CacheAsidePattern:
    """
    CACHE-ASIDE (Lazy Loading): application manages the cache explicitly.
    READ path:  check cache → cache miss → read DB → store in cache → return.
    WRITE path: write DB → invalidate cache (next read re-populates from DB).
    PROS: only caches data that is actually read (no wasted memory).
    CONS: first read after invalidation always misses (cold-start latency).
    USED BY: most Redis + PostgreSQL setups. The most common caching pattern.
    """

    def __init__(self, cache: dict, db_read_fn: Callable[[str], Any]):
        self.cache = cache            # dict simulating Redis
        self.db_read_fn = db_read_fn  # callable simulating a DB SELECT

    def read(self, key: str) -> Any:
        if key in self.cache:
            return self.cache[key]   # cache HIT — return without touching DB

        # cache MISS — go to DB (expensive operation)
        value = self.db_read_fn(key)
        if value is not None:
            self.cache[key] = value  # populate cache to speed up future reads
        return value

    def write(self, key: str, value: Any, db_write_fn: Callable):
        db_write_fn(key, value)      # persist to DB first — source of truth
        self.cache.pop(key, None)    # invalidate stale cache entry
        # IMPORTANT: do NOT write new value to cache here — avoids a race condition
        # where two concurrent writes interleave and leave wrong data in cache


class WriteThroughPattern:
    """
    WRITE-THROUGH: every write is synchronously persisted to both cache and DB.
    PROS: cache is always consistent with DB — no stale reads after writes.
    CONS: write latency is higher (must wait for DB commit + cache update).
    USED FOR: user profiles, account balances — correctness > write throughput.
    """

    def __init__(self, cache: dict, db_write_fn: Callable, db_read_fn: Callable):
        self.cache = cache
        self.db_write_fn = db_write_fn
        self.db_read_fn = db_read_fn

    def write(self, key: str, value: Any):
        # write DB first; if DB fails, the cache is NOT updated → stays consistent
        self.db_write_fn(key, value)
        self.cache[key] = value  # only update cache after DB confirms success

    def read(self, key: str) -> Optional[Any]:
        # in write-through, cache should always have the latest value
        if key not in self.cache:
            val = self.db_read_fn(key)   # cold start: populate from DB
            if val is not None:
                self.cache[key] = val
        return self.cache.get(key)


class WriteBehindPattern:
    """
    WRITE-BEHIND (Write-Back): writes go to cache immediately; DB is updated async.
    PROS: very low write latency — caller doesn't wait for DB round-trip.
    CONS: risk of data loss if cache node crashes before flushing to DB.
    MITIGATION: use Redis AOF (Append-Only File) for durability; flush frequently.
    USED FOR: analytics counters, shopping cart updates, view counts, log aggregation.
    PRODUCTION: Redis → periodic batch flush to PostgreSQL/MySQL by a background worker.
    """

    def __init__(self):
        self.cache: Dict[str, Any] = {}
        self._dirty_queue: deque = deque()   # keys pending flush to DB
        self._lock = threading.Lock()

    def write(self, key: str, value: Any):
        """Fast path: update in-memory cache and mark key dirty for async flush."""
        with self._lock:
            self.cache[key] = value
            self._dirty_queue.append(key)   # will be persisted by background worker

    def flush_to_db(self, db_write_fn: Callable[[str, Any], None]):
        """
        Background worker drains dirty queue and persists to DB.
        Call this on a timer (e.g., every 500 ms) or when queue depth exceeds threshold.
        """
        with self._lock:
            while self._dirty_queue:
                key = self._dirty_queue.popleft()
                value = self.cache.get(key)
                if value is not None:
                    db_write_fn(key, value)  # actual DB write — can be batched


# =============================================================================
# SECTION 9: CACHE STAMPEDE / THUNDERING HERD
# =============================================================================
# PROBLEM: a popular cache key expires. Hundreds of requests arrive simultaneously.
#          All see a cache miss and all race to query the DB → DB overload.
#
# SOLUTIONS (in increasing sophistication):
#   1. Mutex / distributed lock: only one request fetches; others wait.
#   2. Probabilistic early expiry (XFetch): refresh before expiry based on probability.
#   3. Background refresh: async worker refreshes cache before TTL reaches zero.
#   4. Staggered TTLs: add jitter to TTL so keys don't all expire simultaneously.

_cache_locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)

def get_with_mutex(
    cache: dict,
    key: str,
    fetch_fn: Callable[[], Any],
    ttl: float = 60.0,
) -> Any:
    """
    Cache-aside with per-key mutex to prevent cache stampede.
    Only the first thread acquires the lock and fetches from DB.
    All other threads block, then read from cache once the winner populates it.
    PRODUCTION: use Redis SET NX EX (set-if-not-exists with expiry) as distributed lock.
    """
    if key in cache:
        return cache[key]  # fast path — no lock needed

    lock = _cache_locks[key]  # per-key lock avoids contention between unrelated keys
    with lock:
        # double-check inside lock — another thread may have populated it while we waited
        if key in cache:
            return cache[key]

        value = fetch_fn()   # only ONE thread executes this
        cache[key] = value   # all other threads will now read from cache
        return value


def get_with_ttl_jitter(base_ttl: int, jitter_fraction: float = 0.1) -> int:
    """
    Add random jitter to TTL so a group of similar keys don't expire at the same time.
    EXAMPLE: base_ttl=3600, jitter=0.1 → actual TTL between 3240 and 3960.
    PRODUCTION: used widely in CDN purge scheduling and Redis key expiry.
    """
    jitter = int(base_ttl * jitter_fraction)
    return base_ttl + random.randint(-jitter, jitter)


# =============================================================================
# SECTION 10: TTL STRATEGIES BY DATA TYPE
# =============================================================================
# Staleness tolerance varies enormously by data type.
# Setting TTL too high → stale data served to users.
# Setting TTL too low  → too many DB hits; defeats the purpose of caching.

TTL_POLICY: Dict[str, int] = {
    "session_token":    1_800,       # 30 min — expire with session
    "user_profile":     600,         # 10 min — changes rarely; short enough to stay fresh
    "product_catalog":  3_600,       # 1 hour — curated content, infrequent updates
    "inventory_count":  30,          # 30 s — must be near-real-time for purchases
    "static_asset":     31_536_000,  # 1 year — filename hash guarantees uniqueness
    "feature_flag":     60,          # 1 min — allow rapid rollout/rollback control
    "search_results":   300,         # 5 min — expensive to compute, slight staleness OK
    "rate_limit_count": 60,          # matches rate window size
    "homepage_feed":    30,          # 30 s — freshness matters; stale-while-revalidate helps
    "auth_token_valid": 300,         # 5 min — avoid hitting auth service on every request
}


class TTLCache:
    """
    Thread-safe in-memory TTL cache (use Redis in production for distributed setups).
    Implements lazy eviction: expired entries are removed only on access.
    """

    def __init__(self):
        self._store: Dict[str, Tuple[Any, float]] = {}  # key → (value, expiry_epoch)
        self._lock = threading.Lock()

    def set(self, key: str, value: Any, ttl: int):
        """Store a value with a TTL (in seconds)."""
        with self._lock:
            expiry = time.monotonic() + ttl  # absolute expiry timestamp
            self._store[key] = (value, expiry)

    def get(self, key: str) -> Optional[Any]:
        """Return value if present and not expired; evict and return None otherwise."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expiry = entry
            if time.monotonic() > expiry:
                del self._store[key]   # lazy eviction — remove on first stale access
                return None
            return value

    def delete(self, key: str):
        with self._lock:
            self._store.pop(key, None)

    def set_with_jitter(self, key: str, value: Any, base_ttl: int):
        """Set with jittered TTL to prevent simultaneous mass expiry."""
        ttl = get_with_ttl_jitter(base_ttl)
        self.set(key, value, ttl)


# =============================================================================
# SECTION 11: CACHE WARMING STRATEGIES
# =============================================================================
# Cache warming = pre-populating the cache before traffic arrives.
# Prevents a cold-start miss storm when a new server or deployment goes live.
#
# STRATEGIES:
#   1. Offline script: run before deployment to fill Redis from DB.
#   2. Gradual rollout: shift 1% of traffic first; cache warms naturally; then ramp.
#   3. Shadow traffic: replay production traffic against new cache to pre-warm.
#   4. Lazy warming: accept initial misses; cache fills as real traffic arrives.

class CacheWarmer:
    """
    Pre-populates a TTLCache from a source (e.g., database) for a list of known hot keys.
    Failures are logged but non-fatal — the cache will populate lazily for missed keys.
    """

    def __init__(self, cache: TTLCache, fetch_fn: Callable[[str], Any]):
        self.cache = cache
        self.fetch_fn = fetch_fn  # fetches data from the source of truth

    def warm(self, keys: List[str], ttl: int):
        """Pre-populate cache for a list of high-traffic keys."""
        logger.info(f"Starting cache warm for {len(keys)} keys ...")
        warmed, failed = 0, 0
        for key in keys:
            try:
                value = self.fetch_fn(key)   # fetch from DB / API
                self.cache.set(key, value, ttl)  # load into cache
                warmed += 1
            except Exception as e:
                logger.error(f"Failed to warm key={key}: {e}")  # non-fatal
                failed += 1
        logger.info(f"Cache warm complete: {warmed} warmed, {failed} failed.")


# =============================================================================
# SECTION 12: DEMO
# =============================================================================

def demo():
    print("\n" + "="*60)
    print("LOAD BALANCING DEMO")
    print("="*60)

    backends = [
        Backend("10.0.0.1", 8080, weight=3),   # high-capacity server
        Backend("10.0.0.2", 8080, weight=1),   # low-capacity server
        Backend("10.0.0.3", 8080, weight=2),   # medium server
    ]

    print("\nWeighted Round-Robin (weights 3:1:2) — 6 requests:")
    wrr = WeightedRoundRobinBalancer(backends)
    for i in range(6):
        b = wrr.next_backend()
        print(f"  Request {i+1} → {b.address}")

    print("\nIP Hash — same IP always maps to same backend:")
    iphash = IPHashBalancer(backends)
    for ip in ["192.168.1.1", "10.20.30.40", "192.168.1.1"]:
        b = iphash.next_backend(ip)
        print(f"  {ip} → {b.address}")

    backends[0].active_connections = 10
    backends[1].active_connections = 2
    backends[2].active_connections = 5
    lc = LeastConnectionsBalancer(backends)
    winner = lc.next_backend()
    print(f"\nLeast Connections (loads: 10,2,5) → {winner.address} (should be .2)")

    print("\n" + "="*60)
    print("CACHE PATTERNS DEMO")
    print("="*60)

    db = {"user:1": {"name": "Alice"}, "user:2": {"name": "Bob"}}
    aside = CacheAsidePattern({}, lambda k: db.get(k))
    print(f"\nCache-Aside miss:  {aside.read('user:1')}")
    print(f"Cache-Aside hit:   {aside.read('user:1')}")

    print(f"\nCache-Control (static asset):  {STATIC_ASSET_HEADER}")
    print(f"Cache-Control (API response):  {API_RESPONSE_HEADER}")
    print(f"Cache-Control (private user):  {PRIVATE_USER_HEADER}")
    print(f"Cache-Control (sensitive):     {SENSITIVE_HEADER}")

    ttl_cache = TTLCache()
    ttl_cache.set("feature_flag:dark_mode", True, ttl=60)
    print(f"\nTTL Cache get: {ttl_cache.get('feature_flag:dark_mode')}")

    print(f"\nTTL with jitter (base=3600): {get_with_ttl_jitter(3600)}")
    print("Demo complete.")


if __name__ == "__main__":
    demo()
