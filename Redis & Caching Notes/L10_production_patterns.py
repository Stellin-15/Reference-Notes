# =============================================================================
# WHAT: Production Redis — connection pooling, health checks, graceful
#       degradation, monitoring, memory management, persistence, security,
#       ACLs, TLS, and backup/restore procedures
# WHY:  Redis is deceptively easy to start and dangerously easy to misconfigure
#       for production. This file collects the operational knowledge needed to
#       run Redis reliably, securely, and observably in a real environment.
# LEVEL: Advanced / SRE / Platform Engineering
# =============================================================================
#
# CONCEPT OVERVIEW
# ----------------
# Running Redis in production requires attention across five domains:
#
#   1. RELIABILITY — connection pooling, health checks, circuit breakers,
#      graceful degradation when Redis is unavailable
#
#   2. OBSERVABILITY — INFO sections, SLOWLOG, latency monitoring, key-level
#      metrics; integrating with Prometheus/Grafana via redis_exporter
#
#   3. MEMORY — maxmemory policy, eviction, memory fragmentation, key sizing
#
#   4. PERSISTENCE — RDB (snapshots) vs AOF (append-only file); durability
#      vs performance tradeoffs; BGSAVE, BGREWRITEAOF
#
#   5. SECURITY — requirepass, ACL users, dangerous command renaming, TLS,
#      network isolation, ACL LOG (Redis 7.x)
#
# PRODUCTION USE CASE
# -------------------
# High-traffic API gateway using Redis for:
#   - Rate limiting (INCR + EXPIRE)
#   - Auth token caching (GET/SET with TTL)
#   - Feature flag cache (HGETALL)
#   - Idempotency key deduplication (SET NX)
#
# The gateway serves 50k req/s. Redis reliability is critical — a Redis outage
# must not take down the API; it must fall back gracefully.
#
# COMMON MISTAKES
# ---------------
# 1. Using a single connection (not a pool) in a multi-threaded app → serialized
#    requests and connection errors under load.
# 2. Setting maxmemory without an eviction policy → Redis returns OOM errors
#    instead of gracefully evicting old data.
# 3. AOF with appendfsync=always on a write-heavy workload → massive throughput
#    drop because every write flushes to disk synchronously.
# 4. Leaving requirepass empty in a cloud environment → Redis accessible to
#    anyone who can reach the port (compromised in minutes).
# 5. No SLOWLOG monitoring → tail latency spikes go unnoticed until clients
#    report timeouts.
# 6. Forgetting to set a maxmemory budget → Redis consumes all available RAM,
#    triggering OS OOM-kill of the Redis process.
# =============================================================================

import redis
import redis.connection
import time
import logging
import threading
import functools
from enum import Enum
from typing import Optional, Any, Callable
from contextlib import contextmanager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s]: %(message)s"
)
log = logging.getLogger(__name__)

# =============================================================================
# PART 1: CONNECTION POOLING
# =============================================================================
#
# Why pool?
#   Opening a TCP connection to Redis takes ~1ms (localhost) to ~10ms (remote).
#   Pooling amortizes this cost. Each thread borrows a connection, issues
#   commands, then returns it. No teardown / reconnect per request.
#
# Sizing rule of thumb:
#   max_connections = concurrent_threads × 2
#   The ×2 accounts for brief moments when a thread holds a connection and
#   another one is being established in the background.
#
# Pool exhaustion:
#   If all connections are in use and a new request arrives, redis-py raises
#   ConnectionError("Too many connections"). Use max_connections conservatively
#   and monitor pool_connections_total in Prometheus.
#
# socket_keepalive:
#   Instructs the OS kernel to send TCP keepalive probes. Without this, idle
#   connections through NAT/firewalls are silently dropped, causing mysterious
#   "Broken pipe" errors hours after startup.
# -----------------------------------------------------------------------------

def create_production_pool(
    host: str = "localhost",
    port: int = 6379,
    db: int = 0,
    password: str = None,
    thread_count: int = 50,
    ssl: bool = False,
    ssl_certfile: str = None,
    ssl_keyfile: str = None,
    ssl_ca_certs: str = None,
) -> redis.Redis:
    """
    Create a production-grade Redis client with a properly sized connection pool.

    Returns a single redis.Redis instance — share this across the entire
    application. It is thread-safe; multiple threads can call .get(), .set()
    etc. concurrently.
    """
    pool_size = thread_count * 2    # see sizing rule above

    if ssl:
        # Use SSLConnection for TLS-encrypted connections to Redis
        pool = redis.connection.SSLConnectionPool(
            host=host,
            port=port,
            db=db,
            password=password,
            max_connections=pool_size,
            decode_responses=True,
            ssl_certfile=ssl_certfile,      # client certificate (mTLS)
            ssl_keyfile=ssl_keyfile,        # client private key
            ssl_ca_certs=ssl_ca_certs,      # CA bundle to verify server cert
            ssl_cert_reqs="required",       # enforce server cert validation
            socket_keepalive=True,
            socket_connect_timeout=3,
            socket_timeout=2,
            retry_on_timeout=True,
        )
    else:
        pool = redis.ConnectionPool(
            host=host,
            port=port,
            db=db,
            password=password,
            max_connections=pool_size,
            decode_responses=True,
            socket_keepalive=True,          # OS-level TCP keepalive
            socket_keepalive_options={
                "TCP_KEEPIDLE": 60,         # idle seconds before first probe
                "TCP_KEEPINTVL": 10,        # seconds between probes
                "TCP_KEEPCNT": 3,           # probes before declaring dead
            },
            socket_connect_timeout=3,       # fail fast if Redis unreachable
            socket_timeout=2,               # per-command read/write timeout
            retry_on_timeout=True,          # auto-retry timed-out commands once
        )

    client = redis.Redis(connection_pool=pool)
    log.info("Redis pool created: max_connections=%d ssl=%s", pool_size, ssl)
    return client


# =============================================================================
# PART 2: HEALTH CHECKS AND READINESS PROBE
# =============================================================================

def redis_ping(client: redis.Redis, timeout: float = 1.0) -> bool:
    """
    PING-based health check. Suitable for Kubernetes readiness/liveness probes.

    Returns True if Redis responds within timeout, False otherwise.
    Never raises — callers can safely use the boolean result.
    """
    try:
        # PING returns b"PONG" (or "PONG" with decode_responses)
        return client.ping()
    except Exception as exc:
        log.warning("Redis health check failed: %s", exc)
        return False


def redis_deep_health_check(client: redis.Redis) -> dict:
    """
    Comprehensive health check that validates Redis is not just alive but healthy.
    Returns a dict suitable for serialization to a /health endpoint JSON response.
    """
    result = {
        "ping": False,
        "latency_ms": None,
        "memory_used_mb": None,
        "connected_clients": None,
        "role": None,
        "status": "unhealthy",
    }
    try:
        start = time.perf_counter()
        client.ping()
        latency_ms = (time.perf_counter() - start) * 1000

        info = client.info("all")           # fetch all INFO sections at once

        result.update({
            "ping": True,
            "latency_ms": round(latency_ms, 2),
            "memory_used_mb": round(info["used_memory"] / 1_048_576, 1),
            "connected_clients": info["connected_clients"],
            "role": info["role"],           # "master" or "slave"
            "status": "healthy" if latency_ms < 100 else "degraded",
        })

    except Exception as exc:
        result["error"] = str(exc)

    return result


# =============================================================================
# PART 3: CIRCUIT BREAKER — graceful degradation
# =============================================================================
#
# Problem: If Redis is down and every request tries to connect, the connection
# attempts pile up, threads block, and the entire application stalls — even
# for functionality that doesn't need Redis.
#
# Solution: Circuit breaker pattern
#   CLOSED  → normal operation, all requests go to Redis
#   OPEN    → Redis is considered down, requests fail immediately (fast-fail)
#   HALF-OPEN → after a cooldown, allow one probe request through
#               If it succeeds → CLOSED; if it fails → OPEN again
#
# The application must implement fallback behavior for the OPEN state:
#   - Return a default value
#   - Serve stale cached data from an in-process dict
#   - Skip the Redis-dependent feature entirely
# -----------------------------------------------------------------------------

class CircuitState(Enum):
    CLOSED = "closed"        # normal, Redis is healthy
    OPEN = "open"            # Redis is down, fail fast
    HALF_OPEN = "half_open"  # probe state, try one request


class RedisCircuitBreaker:
    """
    Thread-safe circuit breaker wrapping a Redis client.

    Usage:
        cb = RedisCircuitBreaker(client, failure_threshold=5, recovery_timeout=30)
        value = cb.get("my:key", default="fallback_value")
    """

    def __init__(
        self,
        client: redis.Redis,
        failure_threshold: int = 5,     # consecutive failures before opening
        recovery_timeout: float = 30.0, # seconds to wait before probing
    ):
        self._client = client
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._state = CircuitState.CLOSED
        self._opened_at: Optional[float] = None
        self._lock = threading.Lock()

    def _record_success(self):
        with self._lock:
            self._failure_count = 0
            self._state = CircuitState.CLOSED

    def _record_failure(self):
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                log.error(
                    "Circuit OPENED after %d failures", self._failure_count
                )

    def _check_state(self):
        """Transition OPEN → HALF_OPEN if recovery timeout has elapsed."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                elapsed = time.monotonic() - self._opened_at
                if elapsed >= self._recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    log.info("Circuit HALF_OPEN — probing Redis")

    def execute(self, fn: Callable, *args, default: Any = None, **kwargs) -> Any:
        """
        Execute a Redis command through the circuit breaker.

        :param fn:      a bound method, e.g. self._client.get
        :param default: value returned when circuit is OPEN
        """
        self._check_state()

        with self._lock:
            state = self._state

        if state == CircuitState.OPEN:
            log.debug("Circuit OPEN — fast-failing, returning default")
            return default

        try:
            result = fn(*args, **kwargs)
            self._record_success()
            return result
        except (redis.ConnectionError, redis.TimeoutError) as exc:
            log.warning("Redis command failed: %s", exc)
            self._record_failure()
            return default

    def get(self, key: str, default: Any = None) -> Any:
        return self.execute(self._client.get, key, default=default)

    def set(self, key: str, value: Any, **kwargs) -> Any:
        return self.execute(self._client.set, key, value, default=None, **kwargs)

    @property
    def state(self) -> CircuitState:
        return self._state


# =============================================================================
# PART 4: MONITORING — INFO sections, SLOWLOG, latency
# =============================================================================

def parse_info_sections(client: redis.Redis) -> dict:
    """
    Fetch and log the most operationally important INFO metrics.
    In production, ship these to Prometheus via redis_exporter or custom scraper.

    INFO sections:
      server      — version, uptime, config file
      clients     — connected_clients, blocked_clients
      memory      — used_memory, mem_fragmentation_ratio, maxmemory
      stats       — total_commands_processed, instantaneous_ops_per_sec
      replication — role, connected_slaves, repl_offset lag
      keyspace    — db0: keys=N,expires=M (per-db key stats)
      latencystats— (Redis 7+) percentile latency per command
    """
    info = client.info("all")

    # --- Memory health ---
    used_mb = info["used_memory"] / 1_048_576
    peak_mb = info["used_memory_peak"] / 1_048_576
    frag_ratio = info.get("mem_fragmentation_ratio", 0)
    # fragmentation > 1.5 means Redis is using 50% more RAM than needed
    # fragmentation < 1.0 means Redis is using swap — VERY BAD for latency
    log.info("Memory: used=%.1fMB peak=%.1fMB frag_ratio=%.2f", used_mb, peak_mb, frag_ratio)
    if frag_ratio > 1.5:
        log.warning("High memory fragmentation (%.2f) — consider MEMORY PURGE or restart", frag_ratio)
    if frag_ratio < 1.0:
        log.error("Redis may be using swap! frag_ratio=%.2f — check vm.overcommit_memory", frag_ratio)

    # --- Connection pressure ---
    connected = info["connected_clients"]
    blocked = info.get("blocked_clients", 0)
    log.info("Clients: connected=%d blocked=%d", connected, blocked)

    # --- Throughput ---
    ops_per_sec = info.get("instantaneous_ops_per_sec", 0)
    total_cmds = info.get("total_commands_processed", 0)
    log.info("Throughput: ops/s=%d total_commands=%d", ops_per_sec, total_cmds)

    # --- Hit/miss ratio (only meaningful with maxmemory + eviction) ---
    hits = info.get("keyspace_hits", 0)
    misses = info.get("keyspace_misses", 0)
    total = hits + misses
    if total > 0:
        hit_rate = hits / total * 100
        log.info("Cache hit rate: %.1f%% (%d hits, %d misses)", hit_rate, hits, misses)

    # --- Keyspace summary ---
    for key, val in info.items():
        if key.startswith("db"):            # e.g. "db0": "keys=1000,expires=500,avg_ttl=3600000"
            log.info("Keyspace %s: %s", key, val)

    return info


def configure_latency_monitoring(client: redis.Redis, threshold_ms: int = 50):
    """
    Redis latency monitoring tracks events that take longer than a threshold.
    Results are viewable via LATENCY HISTORY and LATENCY LATEST commands.

    :param threshold_ms: log any operation taking longer than this many ms
    """
    # Enable latency monitoring — 0 disables it
    client.config_set("latency-monitor-threshold", threshold_ms)
    # Also enable the event-loop latency tracking (Redis 2.8.13+)
    client.config_set("latency-tracking", "yes")
    log.info("Latency monitoring enabled: threshold=%dms", threshold_ms)


def check_slowlog(client: redis.Redis, num_entries: int = 10):
    """
    SLOWLOG stores the N most recent commands that exceeded slowlog-log-slower-than.
    Default threshold is 10000 microseconds (10ms).

    Each entry: [id, timestamp, duration_us, [command_args], client_addr, client_name]

    In production: scrape SLOWLOG periodically and alert when p99 latency spikes.
    """
    # Set slowlog threshold (microseconds). 1000 = log anything > 1ms
    client.config_set("slowlog-log-slower-than", 1000)
    client.config_set("slowlog-max-len", 256)   # keep last 256 slow entries

    entries = client.slowlog_get(num_entries)
    if not entries:
        log.info("SLOWLOG is empty (good — no slow commands)")
        return

    for entry in entries:
        duration_ms = entry["duration"] / 1000  # convert µs → ms
        command = " ".join(str(a) for a in entry.get("command", []))
        log.warning(
            "SLOWLOG entry: %.2fms  cmd=[%s]  client=%s",
            duration_ms,
            command[:100],          # truncate long commands in logs
            entry.get("client_addr", "unknown"),
        )

    # Reset the slowlog after review (or leave it for continuous monitoring)
    # client.slowlog_reset()


# =============================================================================
# PART 5: MEMORY MANAGEMENT
# =============================================================================
#
# maxmemory policies (set via CONFIG SET maxmemory-policy):
#
#   noeviction      — OOM error on write when limit reached (default)
#                     Use for: primary datastores where data loss is unacceptable
#
#   allkeys-lru     — evict least recently used key from ALL keys
#                     Use for: general-purpose cache (most common)
#
#   volatile-lru    — LRU eviction only among keys WITH an expiry set
#                     Use for: mixed cache + persistent data in same DB
#
#   allkeys-lfu     — evict least frequently used (Redis 4.0+)
#                     Use for: cache where recency matters less than frequency
#
#   volatile-lfu    — LFU only among keys with expiry
#
#   allkeys-random  — random eviction (poor hit rate, rarely useful)
#
#   volatile-random — random eviction among keys with expiry
#
#   volatile-ttl    — evict the key with the shortest remaining TTL first
#                     Use for: when you want to expire short-lived items first
# -----------------------------------------------------------------------------

def configure_memory_limits(client: redis.Redis, max_mb: int = 512):
    """
    Set memory limit and eviction policy at runtime.
    In production, set these in redis.conf so they survive restarts.
    """
    max_bytes = max_mb * 1_048_576
    client.config_set("maxmemory", max_bytes)
    client.config_set("maxmemory-policy", "allkeys-lru")   # recommended for caches
    log.info("Memory limit set to %dMB with allkeys-lru eviction", max_mb)


def memory_diagnostics(client: redis.Redis):
    """
    Diagnose memory usage patterns using MEMORY commands (Redis 4.0+).
    """
    # MEMORY USAGE key — RAM cost of a specific key in bytes
    test_key = "diag:test"
    client.set(test_key, "x" * 1000)
    usage_bytes = client.memory_usage(test_key)
    log.info("Key '%s' uses %d bytes", test_key, usage_bytes)
    client.delete(test_key)

    # MEMORY DOCTOR — Redis's own diagnosis of memory health issues
    diagnosis = client.memory_doctor()
    log.info("MEMORY DOCTOR: %s", diagnosis)

    # MEMORY STATS — detailed internal allocator statistics
    stats = client.memory_stats()
    log.info("Allocator fragmentation: %.2f", stats.get("allocator_frag_ratio", 0))
    log.info("RSS overhead: %.2f", stats.get("rss_overhead_ratio", 0))

    # MEMORY PURGE — defragment allocator memory (Redis 4.0+, brief latency spike)
    # client.memory_purge()   # uncomment to trigger defrag


# =============================================================================
# PART 6: PERSISTENCE — RDB and AOF
# =============================================================================
#
# RDB (Redis Database Backup — snapshot):
#   - Fork a child process, write a full point-in-time snapshot to dump.rdb
#   - Triggered by BGSAVE or automatically by save rules in redis.conf
#   - redis.conf: save 900 1     → snapshot if 1 key changed in 900s
#                 save 300 10    → snapshot if 10 keys changed in 300s
#                 save 60 10000  → snapshot if 10k keys changed in 60s
#   - Pros: compact, fast restart, low I/O overhead during normal ops
#   - Cons: data since last snapshot is LOST on crash
#   - fork() on large datasets can cause millisecond latency spikes
#
# AOF (Append Only File):
#   - Log every write command to appendonly.aof
#   - appendfsync options:
#       always   — fsync after every write (safest, slowest: ~1k writes/s)
#       everysec — fsync once per second (default, good balance)
#       no       — let OS decide when to flush (fastest, least durable)
#   - Pros: configurable durability, AOF is human-readable
#   - Cons: larger file, slower restart (replay all commands)
#   - BGREWRITEAOF compacts the AOF by removing superseded commands
#
# Production recommendation:
#   Use BOTH: RDB for fast restarts and backups + AOF for durability.
#   appendfsync=everysec accepts at most 1 second of data loss.
# -----------------------------------------------------------------------------

def persistence_status(client: redis.Redis) -> dict:
    """
    Check persistence health: when was the last save, is one in progress?
    """
    info = client.info("persistence")

    status = {
        "rdb_last_save": time.ctime(info.get("rdb_last_save_time", 0)),
        "rdb_changes_since_save": info.get("rdb_changes_since_last_save", 0),
        "rdb_bgsave_in_progress": bool(info.get("rdb_bgsave_in_progress")),
        "rdb_last_bgsave_status": info.get("rdb_last_bgsave_status"),  # "ok" or "err"
        "aof_enabled": bool(info.get("aof_enabled")),
        "aof_rewrite_in_progress": bool(info.get("aof_rewrite_in_progress")),
        "aof_last_rewrite_status": info.get("aof_last_bgrewrite_status"),
    }

    log.info("Persistence status: %s", status)

    # Alert if data has accumulated since the last save (potential data loss window)
    if status["rdb_changes_since_save"] > 100_000:
        log.warning(
            "%d unsaved changes — trigger BGSAVE or check save config",
            status["rdb_changes_since_save"]
        )

    return status


def trigger_background_save(client: redis.Redis, rewrite_aof: bool = False):
    """
    Trigger a background save manually — useful before maintenance windows.

    BGSAVE — non-blocking RDB snapshot (runs in forked child)
    BGREWRITEAOF — non-blocking AOF compaction
    """
    if rewrite_aof:
        result = client.bgrewriteaof()          # returns confirmation string
        log.info("BGREWRITEAOF triggered: %s", result)
    else:
        result = client.bgsave()                # returns "Background saving started"
        log.info("BGSAVE triggered: %s", result)

    # Poll until save completes (don't do this in a request path — only in scripts)
    while True:
        info = client.info("persistence")
        if not info.get("rdb_bgsave_in_progress") and not info.get("aof_rewrite_in_progress"):
            break
        time.sleep(0.5)

    log.info("Background save completed")


# =============================================================================
# PART 7: SECURITY
# =============================================================================
#
# Redis security layers (apply ALL in production):
#   1. Network isolation — bind to private IP only, firewall ports
#   2. requirepass — simple password authentication (pre-ACL)
#   3. ACL users — fine-grained per-user command/key permissions (Redis 6+)
#   4. TLS — encrypt client-server traffic (Redis 6+ with TLS build)
#   5. Rename dangerous commands — rename or disable FLUSHALL, DEBUG, CONFIG
#   6. ACL LOG — audit failed auth attempts and command violations (Redis 7+)
# -----------------------------------------------------------------------------

def setup_acl_user(admin_client: redis.Redis):
    """
    ACL (Access Control List) examples.
    Run these from an admin connection that has ACL SETUSER permission.

    ACL SETUSER syntax:
      ACL SETUSER <username> [rules...]

    Rule types:
      on / off                 — enable / disable the user
      ><password>              — set password (>hash adds hashed password)
      ~<pattern>               — allow key patterns (e.g. ~session:*)
      %R~<pattern>             — allow reads to pattern (Redis 7+)
      %W~<pattern>             — allow writes to pattern (Redis 7+)
      +<command>               — allow specific command (e.g. +get)
      -<command>               — deny specific command
      +@<category>             — allow command category (e.g. +@read)
      -@all                    — deny all commands (use as base)
      allkeys / nokeys         — allow / deny all keys
      allchannels              — allow all Pub/Sub channels
      resetpass                — remove all passwords
      nopass                   — disable password requirement (dangerous)
    """
    # Read-only cache user: can only GET keys matching cache:*
    admin_client.acl_setuser(
        "cache_reader",
        enabled=True,
        passwords=[">StrongPassword123"],   # > prefix adds password
        commands=["+get", "+mget", "+exists", "+ttl", "+pttl", "-@all"],
        keys=["~cache:*"],                  # key pattern restriction
    )
    log.info("ACL user 'cache_reader' created")

    # API service user: read+write to session:* and rate_limit:*
    admin_client.acl_setuser(
        "api_service",
        enabled=True,
        passwords=[">AnotherStrongPass!"],
        commands=["+@read", "+@write", "-@dangerous", "-@admin"],
        keys=["~session:*", "~rate_limit:*"],
    )
    log.info("ACL user 'api_service' created")

    # View all ACL users
    users = admin_client.acl_list()
    for user_spec in users:
        log.info("ACL: %s", user_spec)


def list_acl_log(admin_client: redis.Redis, count: int = 20):
    """
    ACL LOG records authentication failures and command-denied events.
    Available in Redis 7.x. Use for security auditing and intrusion detection.

    Each entry contains:
      count      — how many times this event occurred
      reason     — "auth" (bad password) or "command" (denied command)
      context    — which command / channel triggered the denial
      object     — the key or command that was denied
      username   — which user triggered it
      age_seconds— seconds since the last occurrence
    """
    log_entries = admin_client.acl_log(count=count)
    if not log_entries:
        log.info("ACL LOG is empty")
        return

    for entry in log_entries:
        log.warning(
            "ACL violation: reason=%s user=%s object=%s count=%d age=%.1fs",
            entry.get("reason"),
            entry.get("username"),
            entry.get("object"),
            entry.get("count"),
            entry.get("age-seconds"),
        )


def rename_dangerous_commands_reference():
    """
    Commands that should be renamed or disabled in redis.conf for production.
    These cannot be changed at runtime — must be set in redis.conf.

    In redis.conf:
        rename-command FLUSHALL ""         # disabled completely
        rename-command FLUSHDB  ""         # disabled completely
        rename-command DEBUG    ""         # disabled completely
        rename-command CONFIG   "SomeHardToGuessString"   # restricted access
        rename-command SHUTDOWN "SomeOtherHardToGuessString"
        rename-command KEYS     ""         # KEYS is O(N) and blocks Redis

    WARNING: Disabling CONFIG means redis-py's config_set() will fail.
    If your app uses CONFIG SET (e.g. for SLOWLOG threshold), rename instead
    of disabling entirely. Communicate the renamed string to app config only.
    """
    snippet = """
    # redis.conf — dangerous command restrictions
    rename-command FLUSHALL  ""
    rename-command FLUSHDB   ""
    rename-command DEBUG     ""
    rename-command KEYS      ""
    rename-command CONFIG    "xQ9mP3kR7vL2nZ5"
    rename-command SHUTDOWN  "xM8tY1cW4hB6fK0"
    """
    log.info("redis.conf rename-command reference:\n%s", snippet)


# =============================================================================
# PART 8: BACKUP AND RESTORE
# =============================================================================

def backup_procedure(client: redis.Redis, backup_dir: str = "/var/backups/redis"):
    """
    Documented backup procedure for production Redis.

    Steps:
      1. Trigger BGSAVE to ensure dump.rdb is current
      2. Wait for the save to complete (poll rdb_bgsave_in_progress)
      3. Copy dump.rdb to backup location (use scp / S3 / GCS)
      4. Optionally also backup appendonly.aof if AOF is enabled

    This function demonstrates steps 1–2. Steps 3–4 are OS/infra operations
    outside Python (handled by backup agents, cron, or CI/CD pipelines).
    """
    log.info("Starting Redis backup procedure")

    # Step 1: Trigger snapshot
    client.bgsave()

    # Step 2: Wait for completion — poll until bgsave_in_progress goes to 0
    for attempt in range(60):           # max 60 × 0.5s = 30 seconds
        info = client.info("persistence")
        if not info.get("rdb_bgsave_in_progress"):
            status = info.get("rdb_last_bgsave_status")
            if status == "ok":
                log.info("RDB snapshot completed successfully")
            else:
                log.error("RDB snapshot FAILED: %s", status)
            break
        time.sleep(0.5)
    else:
        log.error("Backup timed out after 30 seconds")
        return

    # Step 3: Identify the RDB file path from config
    config = client.config_get("dir")       # {"dir": "/var/lib/redis"}
    rdb_dir = config.get("dir", "/var/lib/redis")
    rdb_source = f"{rdb_dir}/dump.rdb"
    log.info("Copy %s to %s  (implement via boto3/shutil/rsync)", rdb_source, backup_dir)


def restore_procedure_steps():
    """
    Restore steps performed at the OS level (not via redis-py).
    Document this as a runbook in your incident response wiki.

    RDB restore:
      1. SHUTDOWN NOSAVE the running Redis (stops cleanly, skips final save)
      2. Copy your backup dump.rdb to the Redis data directory
      3. Start Redis — it loads dump.rdb on startup automatically

    AOF restore:
      1. Set appendonly no in redis.conf temporarily
      2. Copy backup appendonly.aof to data directory
      3. Start Redis — it replays the AOF
      4. Re-enable AOF: CONFIG SET appendonly yes

    Validate after restore:
      redis-cli DBSIZE               — confirm expected key count
      redis-cli DEBUG RELOAD         — force reload from disk (integrity check)
      redis-cli RANDOMKEY            — spot-check a random key exists
    """
    steps = [
        "1. systemctl stop redis",
        "2. cp /backup/dump.rdb /var/lib/redis/dump.rdb",
        "3. chown redis:redis /var/lib/redis/dump.rdb",
        "4. systemctl start redis",
        "5. redis-cli DBSIZE           # verify key count",
        "6. redis-cli DEBUG RELOAD     # integrity check",
    ]
    log.info("Restore procedure:")
    for step in steps:
        log.info("  %s", step)


# =============================================================================
# PART 9: OPERATIONAL COMMAND REFERENCE
# =============================================================================

OPERATIONAL_COMMANDS = """
OPERATIONAL REDIS COMMANDS (redis-cli / redis-py)
==================================================

CONNECTION & AUTH
  AUTH <password>                    # authenticate
  ACL WHOAMI                         # which user am I?
  CLIENT LIST                        # list all connected clients
  CLIENT KILL ID <id>                # disconnect a specific client

MEMORY
  INFO memory                        # memory usage and fragmentation
  MEMORY USAGE <key>                 # bytes used by a specific key
  MEMORY DOCTOR                      # Redis diagnosis of memory health
  MEMORY PURGE                       # release unused memory back to OS

PERFORMANCE
  INFO stats                         # commands processed, ops/sec
  INFO latencystats                  # per-command percentile latency (Redis 7+)
  LATENCY LATEST                     # latest latency event per event type
  LATENCY HISTORY event              # time series for a latency event
  SLOWLOG GET [count]                # recent slow commands
  SLOWLOG RESET                      # clear the slowlog
  MONITOR                            # stream ALL commands (brief use only)

PERSISTENCE
  BGSAVE                             # trigger async RDB snapshot
  BGREWRITEAOF                       # trigger async AOF compaction
  LASTSAVE                           # unix timestamp of last successful save
  INFO persistence                   # RDB/AOF status

KEYS
  DBSIZE                             # total key count in current DB
  SCAN 0 COUNT 100                   # non-blocking key iteration (safe in prod)
  OBJECT ENCODING <key>              # internal encoding (ziplist, hashtable …)
  OBJECT IDLETIME <key>              # seconds since key was last accessed
  OBJECT FREQ <key>                  # LFU hit frequency counter

CLUSTER / REPLICATION
  INFO replication                   # role, replica list, replication offset
  CLUSTER INFO                       # cluster health summary
  CLUSTER NODES                      # full cluster topology
  CLUSTER KEYSLOT <key>              # which slot does this key hash to?
  WAIT <numreplicas> <timeout>       # block until N replicas confirm writes

SECURITY (Redis 6+)
  ACL LIST                           # all users and their rules
  ACL GETUSER <username>             # single user details
  ACL SETUSER <username> [rules]     # create/modify user
  ACL DELUSER <username>             # remove user
  ACL LOG [count]                    # recent auth/command violations (Redis 7+)
  ACL LOG RESET                      # clear ACL log
"""


def print_runbook():
    """Print the operational quick-reference to stdout."""
    print(OPERATIONAL_COMMANDS)


# =============================================================================
# PART 10: Production-ready cache wrapper — putting it all together
# =============================================================================

class ProductionCache:
    """
    Single object combining connection pool + circuit breaker + health checks.
    Application code imports this and calls get/set/delete without worrying
    about the underlying resilience mechanics.
    """

    def __init__(self, host: str, port: int, password: str = None, thread_count: int = 50):
        self._client = create_production_pool(
            host=host, port=port, password=password, thread_count=thread_count
        )
        self._cb = RedisCircuitBreaker(
            self._client,
            failure_threshold=5,
            recovery_timeout=30,
        )

    def get(self, key: str, default: Any = None) -> Optional[str]:
        """Get a value; returns default if Redis is down or circuit is open."""
        return self._cb.get(key, default=default)

    def set(self, key: str, value: str, ttl: int = 300) -> bool:
        """Set a value with TTL in seconds; returns False if Redis is down."""
        result = self._cb.execute(self._client.set, key, value, ex=ttl, default=False)
        return bool(result)

    def delete(self, key: str) -> int:
        """Delete a key; returns 0 if Redis is down."""
        return self._cb.execute(self._client.delete, key, default=0)

    def is_healthy(self) -> bool:
        """Fast PING check — suitable for Kubernetes readiness probe."""
        return redis_ping(self._client)

    def health_report(self) -> dict:
        """Full health report — suitable for /health endpoint."""
        return redis_deep_health_check(self._client)

    @property
    def circuit_state(self) -> str:
        """Current circuit breaker state: closed / open / half_open."""
        return self._cb.state.value


if __name__ == "__main__":
    # Quick smoke test — requires a running Redis on localhost:6379
    cache = ProductionCache(host="localhost", port=6379)

    if cache.is_healthy():
        log.info("Redis is healthy. Circuit state: %s", cache.circuit_state)
        cache.set("prod:test", "hello", ttl=60)
        val = cache.get("prod:test")
        log.info("Retrieved: %s", val)
        report = cache.health_report()
        log.info("Health: latency=%.2fms memory=%.1fMB role=%s",
                 report.get("latency_ms", 0),
                 report.get("memory_used_mb", 0),
                 report.get("role", "unknown"))
    else:
        log.error("Redis is not reachable — circuit state: %s", cache.circuit_state)

    print_runbook()
