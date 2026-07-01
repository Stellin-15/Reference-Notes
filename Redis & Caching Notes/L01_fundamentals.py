# ============================================================
# L01: Redis Fundamentals — Data Types and Commands
# ============================================================
# WHAT: Core Redis data types (String, Hash, List, Set, Sorted Set),
#       their commands, TTL management, key naming conventions,
#       safe key scanning, memory inspection, and persistence modes.
# WHY:  Redis is the industry-standard in-memory data store. Its
#       single-threaded event loop eliminates race conditions, its
#       sub-millisecond latency makes it ideal for caching and
#       real-time features, and its rich data types let you model
#       sessions, queues, leaderboards, and rate limiters natively
#       without application-level complexity.
# LEVEL: Foundation
# ============================================================
"""
CONCEPT OVERVIEW:
    Redis (Remote Dictionary Server) stores all data in RAM,
    delivering O(1) or O(log N) operations at sub-millisecond
    speeds. Its single-threaded command execution guarantees
    atomicity — no two commands interleave, so INCR is safe
    for counters without locks. Each data type maps directly
    to a real-world use case: Strings for counters/flags,
    Hashes for objects, Lists for queues/stacks, Sets for
    unique membership, Sorted Sets for rankings.

PRODUCTION USE CASE:
    User session management: on login, create a Hash keyed by
    session ID containing user_id, email, and role. Set a TTL
    of 3600 seconds so idle sessions expire automatically. On
    each request, HGET the session fields needed, refresh TTL
    to implement sliding expiry. On logout, DEL the key. This
    replaces a DB query on every authenticated request with a
    single sub-millisecond Redis lookup.

COMMON MISTAKES:
    1. Using KEYS * in production — blocks the event loop while
       scanning all keys; use SCAN instead.
    2. Storing massive values in a single key — prefer splitting
       large objects; Redis is not a blob store.
    3. Forgetting TTL on cache keys — memory fills up silently.
    4. Using HMSET (deprecated) instead of HSET with multiple
       field-value pairs.
    5. Not namespacing keys — "user" collides across services;
       always use "service:type:id" format.
"""

import redis  # pip install redis
import time
import json

# ---------------------------------------------------------------------------
# Connection Setup
# ---------------------------------------------------------------------------

# Create a connection pool — reuse connections across requests.
# decode_responses=True returns Python strings instead of bytes.
pool = redis.ConnectionPool(
    host="localhost",
    port=6379,
    db=0,               # Redis supports 16 logical DBs (0–15); 0 is default
    decode_responses=True,
    max_connections=20  # cap pool size to avoid exhausting server file descriptors
)

# r is the primary client; all commands go through this object
r = redis.Redis(connection_pool=pool)

print("=" * 60)
print("SECTION 1: WHY REDIS")
print("=" * 60)

# Redis is in-memory: reads/writes touch RAM, not disk → sub-ms latency
# Single-threaded event loop: no concurrent command execution → no races
# Rich data types: model queues, rankings, sessions natively
# Expiry (TTL): keys auto-delete — no cron jobs needed for cache cleanup
# Replication + persistence: primary-replica + RDB/AOF for durability

print("\nPing test (should return True):", r.ping())

# ---------------------------------------------------------------------------
# SECTION 2: STRINGS
# ---------------------------------------------------------------------------
# String is the simplest type: one key maps to one value (text, int, float,
# or serialized JSON up to 512 MB). INCR/DECR are atomic — safe counters.

print("\n" + "=" * 60)
print("SECTION 2: STRINGS")
print("=" * 60)

# SET stores a string value; EX sets TTL in seconds atomically
r.set("user:1001:name", "Alice", ex=3600)       # expires in 1 hour
r.set("user:1001:login_count", 0)               # store an integer as string

# GET retrieves the value; returns None if key does not exist
name = r.get("user:1001:name")
print(f"GET name: {name}")

# INCR atomically increments by 1 — safe across multiple app instances
# because the single-threaded loop ensures no two INCRs interleave
r.incr("user:1001:login_count")   # 0 → 1
r.incr("user:1001:login_count")   # 1 → 2
r.incrby("user:1001:login_count", 5)  # add 5 in one command → 7
count = r.get("user:1001:login_count")
print(f"Login count after INCR/INCRBY: {count}")

# DECR / DECRBY for counters that go down (inventory, rate limit remaining)
r.decr("user:1001:login_count")         # 7 → 6
r.decrby("user:1001:login_count", 3)    # 6 → 3

# SETNX — "SET if Not eXists" — atomic conditional set.
# Used for distributed locks and one-time initialization.
acquired = r.setnx("feature_flag:dark_mode", "enabled")
print(f"SETNX acquired (first call): {acquired}")   # True — key did not exist
acquired = r.setnx("feature_flag:dark_mode", "disabled")
print(f"SETNX acquired (second call): {acquired}")  # False — key already exists

# GETSET — atomically GET old value and SET new value in one command
# Useful for read-then-reset counters
old = r.getset("user:1001:login_count", 0)  # read current, reset to 0
print(f"GETSET old value: {old}")

# ---------------------------------------------------------------------------
# SECTION 3: HASHES
# ---------------------------------------------------------------------------
# Hash maps field→value within one key. Think of it as a Redis-native dict.
# Ideal for objects (user profiles, sessions) — update individual fields
# without fetching and re-serializing the whole object.

print("\n" + "=" * 60)
print("SECTION 3: HASHES")
print("=" * 60)

# HSET sets one or more fields in one call (replaces deprecated HMSET)
r.hset("user:1001:profile", mapping={
    "user_id":  "1001",
    "email":    "alice@example.com",
    "role":     "admin",
    "created":  str(int(time.time()))
})

# HGET retrieves a single field — efficient; no need to fetch the whole hash
email = r.hget("user:1001:profile", "email")
print(f"HGET email: {email}")

# HGETALL returns all field-value pairs as a Python dict
profile = r.hgetall("user:1001:profile")
print(f"HGETALL profile: {profile}")

# HMGET retrieves multiple specific fields in one round-trip
selected = r.hmget("user:1001:profile", ["email", "role"])
print(f"HMGET selected fields: {selected}")

# HDEL removes specific fields from the hash without deleting the key
r.hdel("user:1001:profile", "created")  # remove a field we don't need to store

# HEXISTS checks for field presence without fetching the value
exists = r.hexists("user:1001:profile", "role")
print(f"HEXISTS role: {exists}")

# HINCRBY atomically increments an integer field inside a hash
r.hset("user:1001:profile", "post_count", 0)
r.hincrby("user:1001:profile", "post_count", 1)  # atomic increment inside hash

# ---------------------------------------------------------------------------
# SECTION 4: LISTS
# ---------------------------------------------------------------------------
# List is a linked list of strings. O(1) push/pop at head (L) or tail (R).
# Use as a queue (LPUSH + RPOP), stack (LPUSH + LPOP), or task buffer.

print("\n" + "=" * 60)
print("SECTION 4: LISTS")
print("=" * 60)

# RPUSH appends to the right (tail) — the "enqueue" side for a queue
r.delete("task_queue")  # start fresh
r.rpush("task_queue", "task:email_welcome")
r.rpush("task_queue", "task:resize_avatar")
r.rpush("task_queue", "task:send_sms")

# LPUSH prepends to the left (head) — use for stacks or high-priority items
r.lpush("task_queue", "task:urgent_payment")  # jumps to front

# LRANGE returns elements from index start to end (inclusive, -1 = last)
tasks = r.lrange("task_queue", 0, -1)  # fetch all elements
print(f"Queue contents: {tasks}")

# LLEN returns the current list length
print(f"Queue length: {r.llen('task_queue')}")

# LPOP removes and returns from the left — "dequeue" for FIFO queue
next_task = r.lpop("task_queue")
print(f"Dequeued (LPOP): {next_task}")

# RPOP removes and returns from the right — useful for stack behavior
last = r.rpop("task_queue")
print(f"Popped from tail (RPOP): {last}")

# BLPOP — BLOCKING pop: waits up to `timeout` seconds for an element.
# Workers use this instead of a polling loop — zero CPU waste when idle.
# Returns (key, value) tuple, or None on timeout.
# result = r.blpop("task_queue", timeout=1)  # commented out to avoid blocking demo
# print(f"BLPOP result: {result}")

# ---------------------------------------------------------------------------
# SECTION 5: SETS
# ---------------------------------------------------------------------------
# Set is an unordered collection of unique strings. O(1) add/check/remove.
# Use for: tags, follower lists, online users, unique visitors per day.

print("\n" + "=" * 60)
print("SECTION 5: SETS")
print("=" * 60)

# SADD adds members; duplicates are silently ignored — uniqueness enforced
r.delete("article:42:tags")
r.sadd("article:42:tags", "python", "redis", "backend", "caching")
r.sadd("article:42:tags", "python")  # duplicate — no effect, returns 0

# SMEMBERS returns all members (unordered)
tags = r.smembers("article:42:tags")
print(f"Article tags: {tags}")

# SISMEMBER checks membership in O(1) — much faster than fetching all + searching
has_python = r.sismember("article:42:tags", "python")
print(f"Has 'python' tag: {has_python}")

# SCARD returns the count of members
print(f"Tag count: {r.scard('article:42:tags')}")

# Set operations: SUNION, SINTER, SDIFF — powerful for recommendations,
# access control (roles = union of permissions), and A/B analysis
r.sadd("article:99:tags", "redis", "distributed", "caching")
union  = r.sunion("article:42:tags", "article:99:tags")   # all unique tags
inter  = r.sinter("article:42:tags", "article:99:tags")   # shared tags
diff   = r.sdiff("article:42:tags", "article:99:tags")    # tags only in 42
print(f"Tag union: {union}")
print(f"Tag intersection: {inter}")
print(f"Tag diff (42 only): {diff}")

# SREM removes a member; returns number of members actually removed
r.srem("article:42:tags", "backend")

# ---------------------------------------------------------------------------
# SECTION 6: SORTED SETS
# ---------------------------------------------------------------------------
# Sorted Set is like a Set but each member has a floating-point score.
# Members are always ordered by score. O(log N) for most ops.
# Use for: leaderboards, rate limiting windows, priority queues, job scheduling.

print("\n" + "=" * 60)
print("SECTION 6: SORTED SETS")
print("=" * 60)

# ZADD adds members with scores; duplicate members update their score
r.delete("leaderboard:global")
r.zadd("leaderboard:global", {
    "player:alice": 1500.0,
    "player:bob":   1200.0,
    "player:carol": 1800.0,
    "player:dave":  1350.0
})

# ZRANGE returns members in ascending score order (lowest first)
# WITHSCORES=True includes the score in the result
ascending = r.zrange("leaderboard:global", 0, -1, withscores=True)
print(f"Ascending ranking: {ascending}")

# ZREVRANGE returns members in descending order (highest score first)
# This is what you want for a leaderboard display
top_players = r.zrevrange("leaderboard:global", 0, 2, withscores=True)  # top 3
print(f"Top 3 players: {top_players}")

# ZRANK returns 0-indexed rank in ascending order
# ZREVRANK returns 0-indexed rank in descending order (use for leaderboards)
rank = r.zrevrank("leaderboard:global", "player:alice")
print(f"Alice's rank (0-indexed): {rank}")  # 0 = 1st place

# ZSCORE retrieves the score for a specific member
score = r.zscore("leaderboard:global", "player:bob")
print(f"Bob's score: {score}")

# ZINCRBY atomically adds to a member's score — perfect for "add 10 points"
r.zincrby("leaderboard:global", 200, "player:bob")  # bob gains 200 points
print(f"Bob's new score: {r.zscore('leaderboard:global', 'player:bob')}")

# ZRANGEBYSCORE returns members with scores in [min, max] range
# Use for: tasks due within a time range, rate limiting windows
mid_tier = r.zrangebyscore("leaderboard:global", 1300, 1600, withscores=True)
print(f"Mid-tier players: {mid_tier}")

# ---------------------------------------------------------------------------
# SECTION 7: TTL MANAGEMENT
# ---------------------------------------------------------------------------
# TTL (Time To Live) is Redis's built-in cache expiry. Keys auto-delete
# when TTL reaches 0 — no application-level cleanup cron needed.

print("\n" + "=" * 60)
print("SECTION 7: TTL MANAGEMENT")
print("=" * 60)

# EXPIRE sets TTL in seconds on an existing key
r.set("temp_token", "abc123xyz")
r.expire("temp_token", 300)    # expires in 5 minutes

# PEXPIRE sets TTL in milliseconds — for high-precision short-lived keys
r.set("rate_window", "1")
r.pexpire("rate_window", 1000)  # expires in exactly 1 second

# TTL returns remaining seconds; -1 = no expiry; -2 = key does not exist
remaining = r.ttl("temp_token")
print(f"temp_token TTL: {remaining}s")
print(f"nonexistent_key TTL: {r.ttl('nonexistent_key')}")  # -2

# PERSIST removes the TTL — key becomes permanent
r.persist("temp_token")
print(f"After PERSIST, TTL: {r.ttl('temp_token')}")  # -1 = no expiry

# EXPIREAT sets expiry to a Unix timestamp (absolute, not relative)
future_ts = int(time.time()) + 7200  # 2 hours from now
r.expireat("temp_token", future_ts)

# ---------------------------------------------------------------------------
# SECTION 8: KEY NAMING CONVENTIONS
# ---------------------------------------------------------------------------
# Colon-separated namespaces are the universal Redis convention.
# Format: "service:entity_type:id:field" or "service:entity_type:id"
# This groups related keys and prevents naming collisions across services.

print("\n" + "=" * 60)
print("SECTION 8: KEY NAMING CONVENTIONS")
print("=" * 60)

example_keys = [
    "user:1234:profile",          # user profile hash
    "user:1234:session",          # user session data
    "session:abc123xyz",          # session keyed by token
    "rate_limit:192.168.1.1",     # per-IP rate limiter
    "rate_limit:user:1234",       # per-user rate limiter
    "cache:product:99:detail",    # cached product detail
    "queue:email:welcome",        # email job queue
    "lock:payment:order:5678",    # distributed lock
]
print("Proper key naming examples:")
for k in example_keys:
    print(f"  {k}")

# ---------------------------------------------------------------------------
# SECTION 9: KEY SCANNING (SAFE vs DANGEROUS)
# ---------------------------------------------------------------------------
# KEYS pattern: scans ALL keys matching pattern in one call.
# This BLOCKS the Redis event loop until complete.
# With 10M keys this can block for seconds — NEVER use in production.
# SCAN is non-blocking: paginates through keys in batches, returns a cursor.

print("\n" + "=" * 60)
print("SECTION 9: KEY SCANNING")
print("=" * 60)

# DANGER: r.keys("user:*") — blocks event loop, crashes production
# DO NOT USE: print(r.keys("user:*"))

# SAFE: SCAN with cursor — iterates in small batches without blocking
# scan_iter is a Python wrapper that handles cursor iteration automatically
print("Safe scan with SCAN (paginated):")
for key in r.scan_iter(match="user:*", count=100):  # count=hint, not guarantee
    print(f"  Found key: {key}")

# Manual SCAN loop (shows the cursor mechanism explicitly):
# cursor = 0
# while True:
#     cursor, keys = r.scan(cursor, match="user:*", count=100)
#     for key in keys:
#         process(key)
#     if cursor == 0:   # cursor returns to 0 when full cycle is complete
#         break

# OBJECT ENCODING shows Redis's internal representation of a key's value.
# Redis uses compact encodings (listpack, ziplist, intset) for small data.
r.set("counter:example", 42)
encoding = r.object_encoding("counter:example")
print(f"Encoding of integer string: {encoding}")  # 'int'

# ---------------------------------------------------------------------------
# SECTION 10: MEMORY INSPECTION
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("SECTION 10: MEMORY INSPECTION")
print("=" * 60)

# MEMORY USAGE returns bytes consumed by a specific key (including overhead)
r.set("big_string", "x" * 10000)
mem_bytes = r.memory_usage("big_string")
print(f"Memory used by big_string: {mem_bytes} bytes")

# INFO memory returns global memory stats as a dict
mem_info = r.info("memory")
print(f"Used memory (human): {mem_info['used_memory_human']}")
print(f"Peak memory (human): {mem_info['used_memory_peak_human']}")

# ---------------------------------------------------------------------------
# SECTION 11: PERSISTENCE MODES
# ---------------------------------------------------------------------------
# RDB (Redis Database): periodic snapshot of the full dataset to .rdb file.
#   Pro: compact, fast restarts, low overhead.
#   Con: potential data loss between snapshots (last snapshot may be old).
#   Config: save 900 1  (save if 1 key changed in 900s)
#           save 300 10 (save if 10 keys changed in 300s)
#
# AOF (Append-Only File): every write command is appended to a log file.
#   Pro: near-zero data loss (fsync every second = max 1s of loss).
#   Con: larger files, slower restarts, needs periodic rewriting (BGREWRITEAOF).
#   Config: appendonly yes, appendfsync everysec
#
# Both: use AOF for durability + RDB for fast restarts. Most production setups.
#
# No persistence: pure cache use case (data can be rebuilt from DB on restart).

print("\n" + "=" * 60)
print("SECTION 11: PERSISTENCE INFO")
print("=" * 60)

persist_info = r.info("persistence")
print(f"RDB last save status: {persist_info.get('rdb_last_bgsave_status')}")
print(f"AOF enabled: {persist_info.get('aof_enabled')}")

# ---------------------------------------------------------------------------
# SECTION 12: REAL USE CASE — USER SESSION MANAGEMENT
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("SECTION 12: REAL — USER SESSION MANAGEMENT")
print("=" * 60)

def create_session(session_id: str, user_id: str, email: str, role: str,
                   ttl_seconds: int = 3600) -> None:
    """
    Create a user session hash in Redis.
    Hash chosen over String+JSON because individual fields can be updated
    (e.g., refresh role) without fetching and re-serializing the whole object.
    """
    session_key = f"session:{session_id}"
    # HSET with mapping sets all fields in one atomic command
    r.hset(session_key, mapping={
        "user_id":    user_id,
        "email":      email,
        "role":       role,
        "created_at": str(int(time.time())),
    })
    # Set TTL so idle sessions expire automatically — no cleanup job needed
    r.expire(session_key, ttl_seconds)
    print(f"Created session {session_id} for user {user_id} (TTL={ttl_seconds}s)")

def get_session(session_id: str) -> dict | None:
    """
    Retrieve session data and implement sliding expiry.
    Each read resets the TTL — session stays alive while user is active.
    """
    session_key = f"session:{session_id}"
    data = r.hgetall(session_key)  # fetch all fields in one round-trip
    if not data:
        return None  # key expired or never existed
    # Sliding expiry: reset TTL on every access so active sessions don't expire
    r.expire(session_key, 3600)
    return data

def update_session_role(session_id: str, new_role: str) -> None:
    """
    Update a single field without touching others — Hash advantage over JSON string.
    If we stored as JSON String, we'd need GET → deserialize → mutate → SET.
    """
    session_key = f"session:{session_id}"
    r.hset(session_key, "role", new_role)  # partial update — only role field changes

def delete_session(session_id: str) -> None:
    """Logout: immediately invalidate session by deleting the key."""
    r.delete(f"session:{session_id}")
    print(f"Session {session_id} invalidated")

# Demo the session lifecycle
create_session("sess_abc123", "1001", "alice@example.com", "admin")
session = get_session("sess_abc123")
print(f"Retrieved session: {session}")
update_session_role("sess_abc123", "superadmin")
print(f"Role after update: {r.hget('session:sess_abc123', 'role')}")
delete_session("sess_abc123")
print(f"Session after delete: {get_session('sess_abc123')}")  # None

# Cleanup demo keys
r.delete("user:1001:name", "user:1001:login_count", "user:1001:profile",
         "feature_flag:dark_mode", "task_queue", "article:42:tags",
         "article:99:tags", "leaderboard:global", "temp_token",
         "rate_window", "big_string", "counter:example")

print("\nDone. All demo keys cleaned up.")
