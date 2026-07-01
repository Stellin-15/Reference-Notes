# ============================================================
# L03: Sorted Sets and Advanced Redis Data Structures
# ============================================================
# WHAT: Redis Sorted Sets (ZSETs), HyperLogLog, Geo commands,
#       Lua scripting, Pipelines, and Pub/Sub — the advanced
#       toolkit for high-performance real-time applications.
# WHY:  These primitives solve problems that would require
#       complex application logic + heavy DB queries elsewhere.
#       A leaderboard in PostgreSQL needs ORDER BY + index scans;
#       in Redis it is O(log N) with ZADD and ZREVRANK.
# LEVEL: Intermediate
# ============================================================
"""
CONCEPT OVERVIEW:
    Sorted Sets (ZSETs) store members with an associated float
    score. Members are unique; scores are not. Redis keeps members
    sorted by score automatically. This makes ZSETs ideal for
    leaderboards (score = points), rate limiting (score =
    timestamp), priority queues (score = priority or process_time),
    and delayed job queues (score = scheduled execution time).

    HyperLogLog is a probabilistic data structure that estimates
    the cardinality (count of distinct elements) of a set using
    a fixed 12KB of memory regardless of input size. The error
    margin is 0.81%. Perfect for counting unique visitors or
    distinct search queries at massive scale without storing
    every element.

    Geo commands store longitude/latitude as a sorted set
    internally (score = geohash). GEOADD, GEODIST, GEORADIUS
    enable proximity queries — "find stores within 5km" — without
    a spatial database.

    Lua scripting via EVAL executes multiple commands atomically.
    Redis is single-threaded: no other command executes between
    the lines of a Lua script, guaranteeing no race conditions.

    Pipeline batches multiple commands into a single network
    round-trip, eliminating RTT overhead for bulk operations.
    Throughput improvement: 10-50x for bulk writes.

    Pub/Sub provides a fire-and-forget messaging channel. Messages
    are not persisted — if no subscriber is listening, the message
    is lost. Use for live notifications and cache invalidation
    signals, not for durable event delivery.

PRODUCTION USE CASE:
    Multiplayer gaming leaderboard: millions of players, real-time
    rank updates after every match. ZADD to post scores, ZINCRBY
    for incremental point awards, ZREVRANK to show a player their
    rank, ZREVRANGE for the top-10 display, EXPIRE on the weekly
    leaderboard key to auto-reset. Geo-based matchmaking uses
    GEORADIUS to find nearby players for low-latency matches.

COMMON MISTAKES:
    1. Using ZRANGEBYSCORE or ZREVRANGE on a very large set without
       pagination — returns millions of members in one reply.
       Always use LIMIT offset count.
    2. Forgetting ZREMRANGEBYSCORE in the sliding-window rate limiter
       — old timestamps accumulate and ZCARD returns inflated counts.
    3. Treating HyperLogLog as exact — it has 0.81% error. Use a
       real SET (or a Bloom filter) when exact counts matter.
    4. Using Pub/Sub for reliable messaging — messages are lost if
       the subscriber is down. Use Streams (L04) for durability.
    5. Abusing Lua scripts for heavy computation — Redis is single-
       threaded; a slow Lua script blocks ALL other operations.
    6. Not using Pipeline for bulk writes — individual round-trips
       for N inserts = N * RTT latency instead of 1 * RTT.
"""

import time
import math
import random
import threading
import logging
from typing import Optional
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# --------------- Minimal in-memory ZSET simulation ---------------
# In production every method maps directly to the redis-py call shown.

class FakeZSet:
    """Simulates a Redis Sorted Set with the commands used in this module."""

    def __init__(self):
        # member -> score
        self._data: dict[str, float] = {}

    def zadd(self, member: str, score: float) -> int:
        """ZADD key score member  →  1 if new, 0 if updated"""
        is_new = member not in self._data
        self._data[member] = score
        return 1 if is_new else 0

    def zincrby(self, member: str, increment: float) -> float:
        """ZINCRBY key increment member  →  new score (atomic add)"""
        self._data[member] = self._data.get(member, 0.0) + increment
        return self._data[member]

    def zrevrank(self, member: str) -> Optional[int]:
        """ZREVRANK key member  →  0-indexed rank (0 = highest score)"""
        if member not in self._data:
            return None
        sorted_members = sorted(self._data, key=self._data.__getitem__, reverse=True)
        return sorted_members.index(member)

    def zrevrange(self, start: int, stop: int, withscores: bool = False):
        """ZREVRANGE key start stop [WITHSCORES]  →  list of members (desc)"""
        sorted_members = sorted(self._data, key=self._data.__getitem__, reverse=True)
        # Redis uses inclusive stop; -1 means the last element
        if stop == -1:
            stop = len(sorted_members) - 1
        sliced = sorted_members[start : stop + 1]
        if withscores:
            return [(m, self._data[m]) for m in sliced]
        return sliced

    def zrangebyscore(self, min_score: float, max_score: float):
        """ZRANGEBYSCORE key min max  →  members with score in [min, max]"""
        return [m for m, s in self._data.items() if min_score <= s <= max_score]

    def zremrangebyscore(self, min_score: float, max_score: float) -> int:
        """ZREMRANGEBYSCORE key min max  →  number of removed members"""
        to_remove = [m for m, s in self._data.items() if min_score <= s <= max_score]
        for m in to_remove:
            del self._data[m]
        return len(to_remove)

    def zcard(self) -> int:
        """ZCARD key  →  number of members in the sorted set"""
        return len(self._data)

    def zpopmax(self, count: int = 1):
        """ZPOPMAX key [count]  →  remove and return highest-scored members"""
        sorted_members = sorted(self._data, key=self._data.__getitem__, reverse=True)
        result = []
        for m in sorted_members[:count]:
            result.append((m, self._data.pop(m)))
        return result

    def zpopmin(self, count: int = 1):
        """ZPOPMIN key [count]  →  remove and return lowest-scored members"""
        sorted_members = sorted(self._data, key=self._data.__getitem__)
        result = []
        for m in sorted_members[:count]:
            result.append((m, self._data.pop(m)))
        return result

    def all_members(self):
        return dict(self._data)


# ============================================================
# SORTED SETS: LEADERBOARD
# ============================================================
# ZSETs are the canonical Redis leaderboard primitive.
# All operations are O(log N) in the number of members.
#
# Real redis-py usage:
#   r.zadd("leaderboard:week:2024-01", {"alice": 1500})
#   r.zincrby("leaderboard:week:2024-01", 100, "alice")
#   rank = r.zrevrank("leaderboard:week:2024-01", "alice")
#   top10 = r.zrevrange("leaderboard:week:2024-01", 0, 9, withscores=True)
# ============================================================

@dataclass
class Leaderboard:
    """
    Weekly gaming leaderboard backed by a Redis Sorted Set.
    Score = total points earned this week.
    Rank = ZREVRANK (0-indexed, 0 = top player).
    Weekly reset: just EXPIRE the key with the next Sunday's TTL.
    """
    name: str
    zset: FakeZSet = field(default_factory=FakeZSet)

    def post_score(self, player: str, score: float) -> float:
        """
        Record a player's score. Uses ZINCRBY for atomic increment
        so concurrent updates from multiple game servers don't race.

        redis-py:  r.zincrby(self.name, score, player)
        """
        new_score = self.zset.zincrby(player, score)
        logging.info("Player %-12s → total score: %.0f", player, new_score)
        return new_score

    def get_rank(self, player: str) -> Optional[int]:
        """
        Get a player's 0-indexed rank (0 = first place).
        Return None if the player has no score yet.

        redis-py:  r.zrevrank(self.name, player)
        """
        return self.zset.zrevrank(player)

    def get_top_n(self, n: int = 10):
        """
        Retrieve the top-N players with their scores.
        WITHSCORES returns (member, score) tuples.

        redis-py:  r.zrevrange(self.name, 0, n-1, withscores=True)
        """
        return self.zset.zrevrange(0, n - 1, withscores=True)

    def get_players_in_score_range(self, min_score: float, max_score: float):
        """
        Find players with scores between min and max (inclusive).
        Useful for tier brackets (Bronze/Silver/Gold).

        redis-py:  r.zrangebyscore(self.name, min_score, max_score)
        """
        return self.zset.zrangebyscore(min_score, max_score)


# ============================================================
# SORTED SETS: SLIDING WINDOW RATE LIMITER
# ============================================================
# Store each request's timestamp as both the score AND the member.
# On each request:
#   1. ZADD rate:{uid} now now               (record this request)
#   2. ZREMRANGEBYSCORE 0 (now - window)     (remove expired entries)
#   3. ZCARD                                 (count requests in window)
#   4. EXPIRE rate:{uid} window              (cleanup idle users)
#   5. If count > limit → reject
#
# More accurate than the token-bucket because it tracks exact
# timestamps. No "boundary burst" problem of fixed windows.
# ============================================================

class SlidingWindowRateLimiter:
    """
    Per-user sliding window rate limiter using a Redis Sorted Set.
    Each member is the timestamp of a request; score = same timestamp.
    This allows ZREMRANGEBYSCORE to prune requests older than the window.
    """

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit                  # Max requests allowed
        self.window = window_seconds        # Window size in seconds
        # In production: self.redis = redis.Redis(...)
        self._user_zsets: dict[str, FakeZSet] = {}

    def _get_zset(self, user_id: str) -> FakeZSet:
        if user_id not in self._user_zsets:
            self._user_zsets[user_id] = FakeZSet()
        return self._user_zsets[user_id]

    def is_allowed(self, user_id: str) -> tuple[bool, int]:
        """
        Check whether the user is within the rate limit.
        Returns (allowed: bool, current_count: int).

        In production this entire method would be a single Lua script
        to execute steps 1-5 atomically (see rate_limiter_lua below).
        """
        now = time.time()
        window_start = now - self.window
        zset = self._get_zset(user_id)

        # Use a unique member to allow duplicate timestamps (millisecond precision)
        # In practice append a random suffix: f"{now:.6f}-{uuid.uuid4().hex[:8]}"
        member = f"{now:.6f}"

        # Step 1: Record this request
        zset.zadd(member, now)

        # Step 2: Remove requests older than the window
        zset.zremrangebyscore(0, window_start)

        # Step 3: Count requests currently in the window
        count = zset.zcard()

        # Step 4: (Simulated) EXPIRE the key after window seconds of inactivity
        # redis-py:  r.expire(f"rate:{user_id}", self.window)

        allowed = count <= self.limit
        if not allowed:
            # Remove the request we just added — it was rejected
            zset.zremrangebyscore(now, now)

        return allowed, count


# ============================================================
# HYPERLOGLOG: APPROXIMATE CARDINALITY
# ============================================================
# PFADD key element [element ...]
# PFCOUNT key [key ...]
#
# Fixed 12KB memory regardless of how many unique elements are added.
# Error rate: 0.81% — acceptable for analytics (unique page views,
# distinct search queries, DAU estimation).
#
# DO NOT use when exact counts are required (billing, fraud detection).
#
# redis-py:
#   r.pfadd("uv:2024-01-15", user_id)   → 1 if cardinality changed
#   r.pfcount("uv:2024-01-15")           → approximate unique count
#   r.pfmerge("uv:week", "uv:mon", "uv:tue", ...)  → merge HLLs
# ============================================================

class HyperLogLogSimulator:
    """
    Naive cardinality estimator to illustrate the concept.
    Real Redis HyperLogLog uses the LogLog algorithm with 16384 registers.
    This demo uses a set to track uniques exactly (just for demonstration).
    """

    def __init__(self, error_rate: float = 0.0081):
        self._seen: set = set()
        self.error_rate = error_rate

    def pfadd(self, element) -> int:
        """PFADD key element  →  1 if the estimate changed, 0 if unchanged"""
        before = len(self._seen)
        self._seen.add(element)
        return 1 if len(self._seen) != before else 0

    def pfcount(self) -> int:
        """
        PFCOUNT key  →  approximate cardinality.
        Real Redis introduces up to 0.81% error; we simulate it here.
        """
        exact = len(self._seen)
        # Simulate the probabilistic error of the real HLL algorithm
        noise = random.gauss(0, exact * self.error_rate)
        return max(0, int(exact + noise))

    def memory_bytes(self) -> int:
        """Real Redis HyperLogLog is always exactly 12,304 bytes (12KB)."""
        return 12_304  # Fixed regardless of cardinality


def demonstrate_hyperloglog():
    """
    Show that HyperLogLog uses constant memory while a SET grows linearly.
    Real numbers for 1 million unique users:
      - Python set:       ~56MB  (64 bytes per element)
      - Redis HyperLogLog: 12KB  (fixed)
    """
    hll = HyperLogLogSimulator()
    unique_users = [f"user_{i}" for i in range(100_000)]

    for uid in unique_users:
        hll.pfadd(uid)

    estimated = hll.pfcount()
    exact = 100_000
    error_pct = abs(estimated - exact) / exact * 100

    print(f"\n=== HyperLogLog Demo ===")
    print(f"Exact unique users: {exact:,}")
    print(f"HLL estimate:       {estimated:,}")
    print(f"Error:              {error_pct:.3f}%  (target < 0.81%)")
    print(f"Memory (real Redis): {hll.memory_bytes():,} bytes (12KB fixed)")
    print(f"Memory (Python set): ~{exact * 64 // 1024:,} KB  (64B/element)")


# ============================================================
# GEO COMMANDS: PROXIMITY SEARCH
# ============================================================
# Redis stores coordinates as a geohash encoded in a sorted set score.
# Precision: ~0.6mm at the equator.
#
# GEOADD  locations lon lat name
# GEOPOS  locations name           → (lon, lat)
# GEODIST locations from to km     → distance in km
# GEORADIUS center-lon center-lat radius km WITHCOORD WITHDIST COUNT 10 ASC
#   → find up to 10 nearest locations within radius, sorted by distance
# GEOSEARCH (Redis 6.2+): preferred over deprecated GEORADIUS
# ============================================================

@dataclass
class GeoPoint:
    name: str
    lon: float   # Longitude  (-180 to +180)
    lat: float   # Latitude   (-90  to +90)


class GeoIndex:
    """
    Simulated Redis Geo index for player proximity matching.
    All distance calculations use the Haversine formula.
    Real Redis internally stores geohash integers in a ZSET.
    """

    EARTH_RADIUS_KM = 6371.0

    def __init__(self):
        self._points: dict[str, GeoPoint] = {}

    def geoadd(self, lon: float, lat: float, name: str):
        """
        GEOADD locations lon lat name
        redis-py:  r.geoadd("player_locations", {name: (lon, lat)})
        """
        self._points[name] = GeoPoint(name, lon, lat)

    def geopos(self, name: str) -> Optional[tuple[float, float]]:
        """
        GEOPOS locations name  →  (lon, lat) or None
        redis-py:  r.geopos("player_locations", name)
        """
        p = self._points.get(name)
        return (p.lon, p.lat) if p else None

    def geodist(self, name1: str, name2: str) -> Optional[float]:
        """
        GEODIST locations name1 name2 km  →  distance in km
        Uses Haversine formula (same as Redis internally).
        redis-py:  r.geodist("player_locations", name1, name2, unit="km")
        """
        p1, p2 = self._points.get(name1), self._points.get(name2)
        if not p1 or not p2:
            return None
        return self._haversine(p1.lat, p1.lon, p2.lat, p2.lon)

    def georadius(
        self,
        center_lon: float,
        center_lat: float,
        radius_km: float,
        count: int = 10,
    ) -> list[tuple[str, float]]:
        """
        GEORADIUS center-lon center-lat radius km WITHDIST COUNT count ASC
        Returns list of (name, distance_km) sorted by distance ascending.

        Redis 6.2+:
          r.geosearch("player_locations", longitude=center_lon,
                      latitude=center_lat, radius=radius_km, unit="km",
                      withdist=True, count=count, sort="ASC")
        """
        results = []
        for p in self._points.values():
            dist = self._haversine(center_lat, center_lon, p.lat, p.lon)
            if dist <= radius_km:
                results.append((p.name, dist))
        # Sort by distance ascending, take top N
        results.sort(key=lambda x: x[1])
        return results[:count]

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Haversine great-circle distance formula."""
        r = GeoIndex.EARTH_RADIUS_KM
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
        return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ============================================================
# LUA SCRIPTING: ATOMIC MULTI-COMMAND OPERATIONS
# ============================================================
# Redis executes Lua scripts atomically. No command from any
# other client runs between statements. This is essential for
# operations like "check-and-increment" where a read-modify-write
# would otherwise have a race condition.
#
# Syntax:  EVAL script numkeys key [key ...] arg [arg ...]
# In Lua:  KEYS[1], KEYS[2], ARGV[1], ARGV[2] ...
#
# Rate limiter Lua script (what runs in real Redis):
#
#   local key    = KEYS[1]
#   local limit  = tonumber(ARGV[1])
#   local window = tonumber(ARGV[2])
#   local now    = tonumber(ARGV[3])
#   -- Remove timestamps outside the window
#   redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
#   -- Count remaining timestamps
#   local count = redis.call('ZCARD', key)
#   if count < limit then
#       redis.call('ZADD', key, now, now)
#       redis.call('EXPIRE', key, window)
#       return 1  -- allowed
#   end
#   return 0  -- rejected
# ============================================================

RATE_LIMITER_LUA = """
local key    = KEYS[1]
local limit  = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now    = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count < limit then
    redis.call('ZADD', key, now, tostring(now))
    redis.call('EXPIRE', key, window)
    return 1
end
return 0
"""
# redis-py usage:
#   script = r.register_script(RATE_LIMITER_LUA)
#   allowed = script(keys=[f"rate:{user_id}"], args=[limit, window, time.time()])

DISTRIBUTED_LOCK_LUA = """
-- Release lock only if the value matches our unique token
-- Prevents releasing a lock acquired by a different holder
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""
# redis-py:
#   unlock_script = r.register_script(DISTRIBUTED_LOCK_LUA)
#   unlock_script(keys=[lock_key], args=[lock_token])


# ============================================================
# PIPELINE: BATCH COMMANDS IN ONE NETWORK ROUND-TRIP
# ============================================================
# Every redis-py call normally does: send → wait → receive.
# That RTT (~0.1-1ms per call) adds up fast for bulk operations.
#
# Pipeline queues commands client-side and sends them all at once.
# The server processes them in order and returns all replies together.
#
# redis-py usage:
#   with r.pipeline() as pipe:
#       for player, score in updates:
#           pipe.zincrby("leaderboard", score, player)
#       results = pipe.execute()   # One round-trip for all commands
#
# CAUTION: Pipeline is NOT atomic (unlike Lua/MULTI-EXEC).
# For atomicity use MULTI/EXEC or Lua. For pure throughput use Pipeline.
#
# Benchmark (representative numbers):
#   100 individual ZADDs:  ~100ms  (100 round-trips × 1ms RTT)
#   100 ZADDs in pipeline: ~2ms    (1 round-trip + server processing)
#   Speedup: ~50x
# ============================================================

def bulk_update_scores_pipeline(leaderboard: Leaderboard, score_updates: list[tuple[str, float]]):
    """
    Simulates a pipeline bulk-update of the leaderboard.
    In real code this collapses N redis calls into 1 network round-trip.

    redis-py equivalent:
        with r.pipeline() as pipe:
            for player, score in score_updates:
                pipe.zincrby("leaderboard:week", score, player)
            results = pipe.execute()
    """
    # Simulation: apply all updates sequentially (no real pipeline benefit here)
    results = []
    for player, score in score_updates:
        new_score = leaderboard.zset.zincrby(player, score)
        results.append(new_score)
    return results


# ============================================================
# PUB/SUB: FIRE-AND-FORGET MESSAGING
# ============================================================
# Pub/Sub channels are ephemeral — if no subscriber is listening,
# the message is dropped. This distinguishes it from Streams (L04),
# which persist messages until explicitly acknowledged.
#
# Use Pub/Sub for:
#   - Cache invalidation signals ("product 42 was updated — evict it")
#   - Live notifications (chat messages, score updates)
#   - Real-time dashboard refreshes
#
# Do NOT use Pub/Sub for:
#   - Work queues (a crashed consumer loses messages)
#   - Event sourcing (messages aren't stored for replay)
#
# redis-py:
#   Publisher:
#     r.publish("cache:invalidate", "product:42")
#
#   Subscriber (blocks in a thread):
#     pubsub = r.pubsub()
#     pubsub.subscribe("cache:invalidate")
#     for message in pubsub.listen():
#         if message["type"] == "message":
#             key = message["data"]
#             redis_cache.delete(key)
# ============================================================

class FakePubSub:
    """
    Minimal Pub/Sub simulation using in-process callbacks.
    Real Redis Pub/Sub uses a dedicated TCP connection per subscriber.
    """

    def __init__(self):
        self._subscribers: dict[str, list] = {}
        self._lock = threading.Lock()

    def subscribe(self, channel: str, callback):
        """Register a callback for messages on channel."""
        with self._lock:
            self._subscribers.setdefault(channel, []).append(callback)

    def publish(self, channel: str, message: str) -> int:
        """PUBLISH channel message  →  number of subscribers that received it"""
        with self._lock:
            callbacks = list(self._subscribers.get(channel, []))
        for cb in callbacks:
            cb(message)            # Fire-and-forget in simulation
        return len(callbacks)


# ============================================================
# DELAYED JOB QUEUE: SORTED SET AS A PRIORITY QUEUE
# ============================================================
# Store job IDs in a ZSET with score = unix timestamp to execute at.
# A worker polls with ZPOPMIN and processes any job whose score <= now.
#
# Redis commands:
#   Schedule: ZADD jobs <execute_at_unix> <job_id>
#   Poll:     ZRANGEBYSCORE jobs 0 <now> LIMIT 0 10   (peek ready jobs)
#             ZPOPMIN jobs 10                           (pop ready jobs atomically)
# ============================================================

class DelayedJobQueue:
    """
    Job scheduler backed by a Redis Sorted Set.
    Score = scheduled execution timestamp (Unix seconds).
    Jobs due for processing have score <= now.
    """

    def __init__(self):
        self._queue = FakeZSet()
        self._job_data: dict[str, dict] = {}

    def schedule(self, job_id: str, payload: dict, run_at: float):
        """
        Schedule a job to run at a specific Unix timestamp.
        redis-py:  r.zadd("delayed_jobs", {job_id: run_at})
        """
        self._queue.zadd(job_id, run_at)
        self._job_data[job_id] = payload
        logging.info("Scheduled job %s for %.0f (in %.1fs)",
                     job_id, run_at, run_at - time.time())

    def poll_ready(self, now: Optional[float] = None) -> list[tuple[str, dict]]:
        """
        Return and remove all jobs due for execution.
        In production: use ZRANGEBYSCORE + ZPOPMIN inside a Lua script
        to atomically peek and pop — avoids two workers grabbing the same job.
        """
        now = now or time.time()
        ready_ids = self._queue.zrangebyscore(0, now)
        result = []
        for jid in ready_ids:
            # Simulate ZPOPMIN: remove from ZSET
            self._queue.zremrangebyscore(0, now)
            result.append((jid, self._job_data.pop(jid, {})))
        return result


# ============================================================
# DEMO: Full gaming leaderboard + geo matchmaking
# ============================================================

def run_demo():
    print("\n=== Leaderboard Demo ===")

    board = Leaderboard("leaderboard:week:2024-01")
    players = ["alice", "bob", "carol", "dave", "eve",
               "frank", "grace", "henry", "iris", "jack"]

    # Simulate post-match score submissions
    for _ in range(30):
        player = random.choice(players)
        score  = random.randint(50, 300)
        board.post_score(player, score)

    print("\nTop 5 players:")
    for rank, (player, score) in enumerate(board.get_top_n(5), start=1):
        print(f"  #{rank:2d}  {player:<10s}  {score:.0f} pts")

    alice_rank = board.get_rank("alice")
    print(f"\nAlice's rank: #{alice_rank + 1 if alice_rank is not None else 'N/A'}")

    print("\n=== Sliding Window Rate Limiter Demo ===")
    limiter = SlidingWindowRateLimiter(limit=5, window_seconds=10)
    results = []
    for i in range(8):
        allowed, count = limiter.is_allowed("user_42")
        results.append(f"Request {i+1}: {'ALLOWED' if allowed else 'REJECTED'} (count={count})")
    for r in results:
        print(f"  {r}")

    print("\n=== HyperLogLog Demo ===")
    demonstrate_hyperloglog()

    print("\n=== Geo Proximity Demo ===")
    geo = GeoIndex()
    cities = [
        ("London",    -0.1278, 51.5074),
        ("Paris",      2.3522, 48.8566),
        ("Amsterdam",  4.9041, 52.3676),
        ("Berlin",    13.4050, 52.5200),
        ("Brussels",   4.3517, 50.8503),
    ]
    for name, lon, lat in cities:
        geo.geoadd(lon, lat, name)

    center_lon, center_lat = 3.0, 51.0   # Roughly Belgium
    nearby = geo.georadius(center_lon, center_lat, radius_km=300)
    print(f"\nCities within 300km of ({center_lon}, {center_lat}):")
    for city, dist in nearby:
        print(f"  {city:<12s}  {dist:.1f} km")

    dist_lp = geo.geodist("London", "Paris")
    print(f"\nLondon → Paris: {dist_lp:.1f} km")

    print("\n=== Delayed Job Queue Demo ===")
    jq = DelayedJobQueue()
    now = time.time()
    jq.schedule("job:001", {"type": "email", "to": "user@example.com"}, now + 0.01)
    jq.schedule("job:002", {"type": "report", "id": 42},                now + 100)
    jq.schedule("job:003", {"type": "cleanup", "table": "sessions"},    now + 0.02)

    time.sleep(0.05)
    ready = jq.poll_ready()
    print(f"Ready jobs after 50ms: {[jid for jid, _ in ready]}")
    # job:002 should still be in the queue (scheduled for 100s from now)

    print("\n=== Pub/Sub Cache Invalidation Demo ===")
    pubsub = FakePubSub()
    invalidated_keys = []

    def on_invalidation(key: str):
        invalidated_keys.append(key)
        print(f"  [subscriber] Evicting cache key: {key}")

    pubsub.subscribe("cache:invalidate", on_invalidation)
    pubsub.publish("cache:invalidate", "product:42")
    pubsub.publish("cache:invalidate", "product:99")
    print(f"Keys invalidated via Pub/Sub: {invalidated_keys}")


if __name__ == "__main__":
    run_demo()
