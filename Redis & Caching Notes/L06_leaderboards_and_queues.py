# ============================================================
# L06: Real-Time Leaderboards and Queue Patterns with Redis
# ============================================================
# WHAT: Implement leaderboards (gaming, scoring) and queue
#       systems (priority, delayed, reliable) using Redis
#       sorted sets and lists.
# WHY:  Redis sorted sets are O(log N) for insert/rank —
#       perfect for real-time scoring. Lists give you
#       blocking pops, making polling unnecessary.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    Redis Sorted Sets (ZSET) store members with a float score,
    automatically maintained in ascending order. This makes them
    ideal for leaderboards (rank = ZREVRANK), priority queues
    (priority = score, ZPOPMIN = highest priority), and delayed
    job scheduling (score = timestamp, ZRANGEBYSCORE -inf now).

    Redis Lists support LPUSH/BRPOP for a simple queue, and
    RPOPLPUSH for a reliable queue pattern where a message is
    moved to a processing list before being acknowledged.

    Rate limiting uses a combination of sorted sets (sliding
    window) and Lua scripts (atomic read-modify-write), which
    is the only safe way to implement compare-and-set logic in
    Redis without transactions.

PRODUCTION USE CASE:
    - Gaming platforms: millions of concurrent players updating
      scores every second. Redis ZADD is O(log N) even at scale.
    - Job schedulers: Sidekiq (Ruby), Celery (Python) both use
      Redis sorted sets for delayed/scheduled jobs internally.
    - API gateways: per-user rate limiting at the edge using
      Redis sliding window counters, often in Lua scripts.
    - Task queues with priorities: customer support ticket
      routing where paid users' requests take priority.

COMMON MISTAKES:
    1. Using ZRANGE instead of ZREVRANGE — ZRANGE returns
       lowest scores first (ascending), ZREVRANGE gives you
       the top scorers (descending). Easy to flip.
    2. Not setting EXPIRE on time-scoped leaderboard keys —
       weekly/daily keys accumulate forever and bloat memory.
    3. Using KEYS * in production to find leaderboard keys —
       KEYS is O(N) and blocks the entire server. Use SCAN.
    4. LRANGE on a huge list to check queue depth — use LLEN.
    5. Assuming RPOPLPUSH is atomic with business logic —
       it is atomic in Redis, but your consumer code still
       needs idempotency because the worker can crash after
       popping but before finishing work.
    6. Using a single sorted set for multi-dimensional ranking
       without ZUNIONSTORE — you lose the ability to weight
       different metrics independently.
"""

import redis
import time
import uuid
import json
from datetime import datetime, timedelta

# ============================================================
# CONNECTION SETUP
# ============================================================

# In production, use a connection pool shared across the app.
# See L08 for full pool configuration.
r = redis.Redis(
    host='localhost',
    port=6379,
    db=0,
    decode_responses=True  # return str instead of bytes
)

# ============================================================
# SECTION 1: BASIC LEADERBOARD OPERATIONS
# ============================================================

def add_score(leaderboard_key: str, user_id: str, score: float) -> None:
    """
    Add or update a user's score in the leaderboard.

    ZADD: O(log N) — sorted set insert/update.
    If the user already exists, their score is replaced (not added).
    To *add* points to an existing score, use ZINCRBY instead.
    """
    # ZADD key score member
    # The score is a float stored as a double-precision value.
    r.zadd(leaderboard_key, {user_id: score})
    print(f"Set {user_id} score to {score} in '{leaderboard_key}'")


def increment_score(leaderboard_key: str, user_id: str, points: float) -> float:
    """
    Add points to a user's existing score atomically.

    ZINCRBY is atomic — no race condition between read and write.
    If the user doesn't exist, they are created with score=points.
    Returns the new score after increment.
    """
    # ZINCRBY key increment member
    new_score = r.zincrby(leaderboard_key, points, user_id)
    print(f"{user_id} now has {new_score} points (added {points})")
    return new_score


def get_rank(leaderboard_key: str, user_id: str) -> int | None:
    """
    Get a user's 0-indexed rank in the leaderboard (highest score = rank 0).

    ZREVRANK: O(log N)
    Returns None if the user is not in the leaderboard.
    To display as "Rank 1", add 1 to the result.
    """
    # ZREVRANK: rank in descending order (highest score = 0)
    rank = r.zrevrank(leaderboard_key, user_id)
    if rank is None:
        print(f"{user_id} not found in leaderboard")
        return None
    print(f"{user_id} is rank {rank + 1} (0-indexed: {rank})")
    return rank


def get_top_n(leaderboard_key: str, n: int = 10) -> list[tuple[str, float]]:
    """
    Retrieve the top N players with their scores.

    ZREVRANGE start stop WITHSCORES: O(log N + M) where M is
    the number of elements returned. Returns highest score first.
    """
    # ZREVRANGE 0 (n-1) returns n elements, 0-indexed
    top = r.zrevrange(leaderboard_key, 0, n - 1, withscores=True)
    print(f"\nTop {n} in '{leaderboard_key}':")
    for i, (user, score) in enumerate(top):
        print(f"  #{i + 1}  {user:20s}  {score:.0f} pts")
    return top


def get_player_score(leaderboard_key: str, user_id: str) -> float | None:
    """
    Get a specific player's score without fetching the full leaderboard.

    ZSCORE: O(1) — direct lookup by member.
    """
    score = r.zscore(leaderboard_key, user_id)
    if score is None:
        print(f"{user_id} not in leaderboard")
    return score


# ============================================================
# SECTION 2: PAGINATED LEADERBOARD
# ============================================================

def get_leaderboard_page(
    leaderboard_key: str,
    page: int,
    page_size: int = 25
) -> list[tuple[str, float]]:
    """
    Fetch a page of the leaderboard using offset-based pagination.

    ZREVRANGE start stop is perfect for this — it supports
    arbitrary start/stop positions in O(log N + M) time.

    Page 1 = positions 0..24
    Page 2 = positions 25..49
    etc.

    Note: cursor-based pagination is better when the leaderboard
    changes rapidly between page fetches. For a snapshot, offset
    is fine. For a "next page" button on a live board, consider
    ZSCORE of the last seen member as the cursor.
    """
    start = (page - 1) * page_size
    stop = start + page_size - 1

    # ZREVRANGE with WITHSCORES returns list of (member, score) tuples
    results = r.zrevrange(leaderboard_key, start, stop, withscores=True)
    print(f"\nPage {page} (positions {start + 1}-{start + len(results)}):")
    for i, (user, score) in enumerate(results):
        rank = start + i + 1
        print(f"  #{rank:<5} {user:20s} {score:.0f}")
    return results


# ============================================================
# SECTION 3: TIME-SCOPED LEADERBOARDS (DAILY / WEEKLY / ALL-TIME)
# ============================================================

def get_time_scoped_keys(user_id: str = None) -> dict[str, str]:
    """
    Generate Redis keys for time-scoped leaderboards.

    Pattern: game:leaderboard:{scope}:{period_identifier}
    - Daily key expires after 2 days (safety buffer)
    - Weekly key expires after 8 days
    - All-time key never expires

    Including the date/week in the key means each period gets
    its own sorted set. Old periods auto-expire via TTL.
    """
    now = datetime.utcnow()

    # ISO week: 2026-W27 style
    week_str = now.strftime("%Y-W%W")
    # Day: 2026-06-30 style
    day_str = now.strftime("%Y-%m-%d")

    return {
        "daily": f"game:leaderboard:daily:{day_str}",
        "weekly": f"game:leaderboard:weekly:{week_str}",
        "alltime": "game:leaderboard:alltime",
    }


def record_game_score(user_id: str, score: float) -> None:
    """
    Record a game result across all three leaderboard scopes atomically.

    Uses a pipeline so all three writes happen in one round trip.
    ZINCRBY adds to existing scores (cumulative scoring).
    EXPIRE sets TTL only on the time-scoped keys.
    """
    keys = get_time_scoped_keys()

    # Pipeline: batch all commands, execute in one round trip
    # This is NOT atomic (no MULTI/EXEC), but it's fast and
    # fine here because a partial write just means one board
    # gets updated — not a data integrity issue.
    with r.pipeline() as pipe:
        # Increment score in all three boards
        pipe.zincrby(keys["daily"], score, user_id)
        pipe.zincrby(keys["weekly"], score, user_id)
        pipe.zincrby(keys["alltime"], score, user_id)

        # Set TTL on time-scoped keys (48h and 8 days respectively)
        # EXPIRE is safe to call repeatedly — it resets the TTL each time.
        # Use EXPIREAT with end-of-period timestamp for more precision.
        pipe.expire(keys["daily"], 60 * 60 * 48)       # 48 hours
        pipe.expire(keys["weekly"], 60 * 60 * 24 * 8)  # 8 days

        pipe.execute()

    print(f"Recorded {score} pts for {user_id} in daily/weekly/alltime boards")


# ============================================================
# SECTION 4: MULTI-METRIC LEADERBOARD WITH ZUNIONSTORE
# ============================================================

def update_multi_metric(user_id: str, kills: int, assists: int, wins: int) -> None:
    """
    Maintain separate sorted sets for each metric, then combine
    into a composite leaderboard using ZUNIONSTORE with weights.

    Why separate sets per metric:
    - Lets you show leaderboards for each stat independently
    - Lets you change the weighting formula without re-ingesting data
    - ZUNIONSTORE combines them into a new sorted set

    ZUNIONSTORE dest numkeys key [key...] [WEIGHTS w [w...]]
    Score in destination = sum of weighted scores across all keys.
    """
    # Update per-metric sorted sets
    r.zincrby("game:metric:kills", kills, user_id)
    r.zincrby("game:metric:assists", assists, user_id)
    r.zincrby("game:metric:wins", wins, user_id)

    # Rebuild composite leaderboard:
    # composite = kills*1 + assists*0.5 + wins*10
    r.zunionstore(
        dest="game:leaderboard:composite",
        keys={
            "game:metric:kills": 1,      # weight for kills
            "game:metric:assists": 0.5,  # assists worth half
            "game:metric:wins": 10,      # wins worth 10x
        }
    )
    print(f"Updated multi-metric leaderboard for {user_id}")


# ============================================================
# SECTION 5: PRIORITY QUEUE
# ============================================================

def enqueue_job(queue_key: str, job_data: dict, priority: int) -> str:
    """
    Add a job to a priority queue implemented as a sorted set.

    Score = priority (lower number = higher priority in ZPOPMIN).
    For "high priority = large number", use ZPOPMAX instead.

    Convention here: priority 1 = most urgent, 10 = lowest.
    """
    job_id = str(uuid.uuid4())
    payload = json.dumps({**job_data, "job_id": job_id})

    # ZADD: score=priority, member=serialized job
    r.zadd(queue_key, {payload: priority})
    print(f"Enqueued job {job_id} with priority {priority}")
    return job_id


def process_next_job(queue_key: str) -> dict | None:
    """
    Atomically pop the highest-priority job from the queue.

    ZPOPMIN: atomically removes and returns the member with
    the lowest score (= highest priority in our convention).
    This is the safe way — no separate ZRANGE + ZREM which
    would have a race condition between two workers.

    Returns None if the queue is empty.
    """
    # ZPOPMIN returns list of (member, score) tuples, count=1
    result = r.zpopmin(queue_key, count=1)
    if not result:
        print("Queue is empty")
        return None

    payload_str, score = result[0]
    job = json.loads(payload_str)
    print(f"Processing job {job['job_id']} (priority {score:.0f})")
    return job


# ============================================================
# SECTION 6: DELAYED JOB QUEUE (SCHEDULED EXECUTION)
# ============================================================

def schedule_job(queue_key: str, job_data: dict, run_at: datetime) -> str:
    """
    Schedule a job to run at a specific future time.

    Score = Unix timestamp of when the job should run.
    Workers poll using ZRANGEBYSCORE -inf <now> to find
    ready jobs, then ZPOPMIN to claim one atomically.

    This pattern is used by Celery (eta parameter),
    Sidekiq (perform_at), and BullMQ internally.
    """
    job_id = str(uuid.uuid4())
    run_timestamp = run_at.timestamp()
    payload = json.dumps({**job_data, "job_id": job_id})

    r.zadd(queue_key, {payload: run_timestamp})
    print(f"Scheduled job {job_id} to run at {run_at.isoformat()}")
    return job_id


def claim_ready_jobs(queue_key: str, max_jobs: int = 5) -> list[dict]:
    """
    Claim all jobs whose scheduled time has passed.

    ZRANGEBYSCORE -inf now: find all jobs ready to run.
    ZPOPMIN: atomically claim one (another worker may grab others).

    In a real worker loop, you'd call this every 1-5 seconds.
    Lua script alternative: atomically get + remove all ready
    jobs in one command to avoid race conditions at scale.
    """
    now = time.time()
    ready = []

    # Loop: each ZPOPMIN is atomic, so no two workers get the same job
    for _ in range(max_jobs):
        # Only pop if score (timestamp) <= now
        result = r.zpopmin(queue_key, count=1)
        if not result:
            break
        payload_str, score = result[0]
        if score > now:
            # This job isn't ready yet — put it back and stop
            r.zadd(queue_key, {payload_str: score})
            break
        ready.append(json.loads(payload_str))

    print(f"Claimed {len(ready)} ready jobs")
    return ready


# ============================================================
# SECTION 7: SIMPLE QUEUE WITH REDIS LIST (LPUSH + BRPOP)
# ============================================================

def enqueue_message(queue_key: str, message: dict) -> None:
    """
    Push a message to the left end of a Redis list.

    Redis List as a queue:
    - LPUSH: add to left (head)
    - BRPOP: block-pop from right (tail)
    This gives FIFO order (first in, first out).

    Lists are simpler than sorted sets for basic queues —
    no score needed, BRPOP blocks until a message arrives
    so workers don't need to poll.
    """
    r.lpush(queue_key, json.dumps(message))
    print(f"Enqueued message to '{queue_key}'")


def consume_message(queue_key: str, timeout: int = 5) -> dict | None:
    """
    Block-pop a message from the queue.

    BRPOP key timeout: blocks up to `timeout` seconds waiting
    for a message. Returns (key, value) tuple or None on timeout.

    Multiple consumers: each BRPOP call pops exactly one message.
    Redis delivers each message to exactly one waiting consumer.
    This is point-to-point (not pub/sub fan-out).

    timeout=0 means block forever — use with care in prod,
    as it ties up a connection indefinitely.
    """
    result = r.brpop(queue_key, timeout=timeout)
    if result is None:
        print("No message received (timeout)")
        return None
    _, raw = result
    message = json.loads(raw)
    print(f"Consumed message: {message}")
    return message


# ============================================================
# SECTION 8: RELIABLE QUEUE WITH RPOPLPUSH + ACK PATTERN
# ============================================================

PROCESSING_LIST = "queue:processing"
DEAD_LETTER_LIST = "queue:dlq"
MAX_RETRIES = 3


def enqueue_reliable(message: dict) -> None:
    """Push a message to the reliable queue."""
    payload = json.dumps({**message, "retries": 0})
    r.lpush("queue:reliable", payload)
    print(f"Enqueued reliable message: {message}")


def consume_reliable() -> dict | None:
    """
    Atomically move a message from the work queue to the
    processing list before starting work.

    RPOPLPUSH source dest:
    - Pops from the right of 'source'
    - Pushes to the left of 'dest'
    - Atomic: either both happen or neither

    If the worker crashes after this point, the message
    is still in PROCESSING_LIST and can be recovered.
    A separate "recovery" process scans PROCESSING_LIST
    for messages that have been there too long.
    """
    raw = r.rpoplpush("queue:reliable", PROCESSING_LIST)
    if raw is None:
        return None
    message = json.loads(raw)
    print(f"Claimed message for processing: {message}")
    return message


def ack_message(message: dict) -> None:
    """
    Acknowledge successful processing by removing from the
    processing list.

    LREM key count value:
    - count=1: remove the first occurrence
    - Removes the exact serialized string from PROCESSING_LIST

    This must match the exact bytes that were pushed — so
    serialize the message the same way every time.
    """
    raw = json.dumps({**message, "retries": message.get("retries", 0)})
    removed = r.lrem(PROCESSING_LIST, 1, raw)
    if removed:
        print(f"ACKed message: {message}")
    else:
        print(f"WARNING: message not found in processing list — already ACKed?")


def nack_message(message: dict) -> None:
    """
    Negative acknowledgement: re-queue or send to DLQ.

    On failure, increment retry count. If under MAX_RETRIES,
    re-queue. Otherwise, move to dead-letter queue (DLQ) for
    manual inspection or separate retry logic.
    """
    raw = json.dumps({**message, "retries": message.get("retries", 0)})
    r.lrem(PROCESSING_LIST, 1, raw)  # remove from processing

    retries = message.get("retries", 0) + 1
    message["retries"] = retries

    if retries >= MAX_RETRIES:
        # Too many failures — move to DLQ
        r.lpush(DEAD_LETTER_LIST, json.dumps(message))
        print(f"Moved message to DLQ after {retries} retries: {message}")
    else:
        # Re-queue for retry
        r.lpush("queue:reliable", json.dumps(message))
        print(f"Re-queued message (retry {retries}/{MAX_RETRIES}): {message}")


# ============================================================
# SECTION 9: RATE LIMITING WITH LUA SCRIPTS
# ============================================================

# Lua script: sliding window rate limiter
# Atomic — runs as a single Redis command, no race conditions.
# Counts requests in the last `window_ms` milliseconds.
SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])

-- Remove entries older than the window
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)

-- Count current entries in the window
local count = redis.call('ZCARD', key)

if count < limit then
    -- Add this request (score = timestamp, member = unique ID)
    redis.call('ZADD', key, now, now .. math.random(1, 1000000))
    redis.call('PEXPIRE', key, window)
    return 1  -- allowed
else
    return 0  -- rate limited
end
"""

_sliding_window_script = None

def is_allowed_sliding_window(
    user_id: str,
    limit: int,
    window_seconds: int
) -> bool:
    """
    Per-user sliding window rate limiter.

    Uses a sorted set where each element represents one request.
    Score = millisecond timestamp. Old entries are pruned on each
    call so the set size stays proportional to the limit, not time.

    Why Lua:
    - ZREMRANGEBYSCORE + ZCARD + ZADD must be atomic
    - Without Lua, two concurrent requests could both read count=99
      and both be allowed even if limit=100 and 2 requests arrive
      at the exact same millisecond
    """
    global _sliding_window_script
    if _sliding_window_script is None:
        _sliding_window_script = r.register_script(SLIDING_WINDOW_LUA)

    key = f"ratelimit:user:{user_id}"
    now_ms = int(time.time() * 1000)
    window_ms = window_seconds * 1000

    result = _sliding_window_script(
        keys=[key],
        args=[now_ms, window_ms, limit]
    )
    allowed = bool(result)
    status = "ALLOWED" if allowed else "RATE LIMITED"
    print(f"[{status}] User {user_id} | {limit} req/{window_seconds}s window")
    return allowed


def is_allowed_token_bucket(
    user_id: str,
    capacity: int,
    refill_rate: float  # tokens per second
) -> bool:
    """
    Per-user token bucket rate limiter.

    Stores two values per user: tokens remaining and last refill time.
    On each request, refill tokens based on elapsed time, then
    consume one token if available.

    This allows burst traffic up to `capacity` and sustained
    traffic at `refill_rate` requests/second.

    Note: this implementation uses a pipeline (not atomic).
    For true atomicity, use a Lua script — this simplified
    version is illustrative.
    """
    key = f"ratelimit:bucket:{user_id}"
    now = time.time()

    data = r.hmget(key, "tokens", "last_refill")
    tokens = float(data[0]) if data[0] else float(capacity)
    last_refill = float(data[1]) if data[1] else now

    # Calculate how many tokens to add since last refill
    elapsed = now - last_refill
    new_tokens = min(capacity, tokens + elapsed * refill_rate)

    if new_tokens >= 1:
        # Consume one token
        new_tokens -= 1
        r.hset(key, mapping={"tokens": new_tokens, "last_refill": now})
        r.expire(key, int(capacity / refill_rate) + 60)
        print(f"[ALLOWED] {user_id} | {new_tokens:.1f} tokens remaining")
        return True
    else:
        r.hset(key, mapping={"tokens": new_tokens, "last_refill": now})
        print(f"[RATE LIMITED] {user_id} | no tokens available")
        return False


# ============================================================
# SECTION 10: COMPLETE GAMING LEADERBOARD DEMO
# ============================================================

def demo_gaming_leaderboard() -> None:
    """
    Simulate a gaming leaderboard with daily, weekly, and all-time
    boards. Demonstrates score recording, ranking, and pagination.
    """
    print("\n" + "=" * 60)
    print("DEMO: Gaming Leaderboard")
    print("=" * 60)

    # Simulate players earning scores
    players = [
        ("player:alice", 1500),
        ("player:bob", 2200),
        ("player:charlie", 900),
        ("player:diana", 3100),
        ("player:eve", 1750),
    ]

    for user_id, score in players:
        record_game_score(user_id, score)

    # Show the daily leaderboard top 10
    keys = get_time_scoped_keys()
    get_top_n(keys["daily"], n=5)

    # Check individual player rank
    get_rank(keys["daily"], "player:alice")
    get_rank(keys["daily"], "player:diana")


def demo_priority_queue() -> None:
    """
    Simulate a job priority queue with delayed execution.
    """
    print("\n" + "=" * 60)
    print("DEMO: Priority Queue + Delayed Jobs")
    print("=" * 60)

    queue_key = "demo:priority_queue"

    # Enqueue jobs with different priorities (1 = most urgent)
    enqueue_job(queue_key, {"type": "email", "to": "user@example.com"}, priority=3)
    enqueue_job(queue_key, {"type": "payment", "amount": 99.99}, priority=1)
    enqueue_job(queue_key, {"type": "report", "period": "weekly"}, priority=5)
    enqueue_job(queue_key, {"type": "alert", "message": "Server down"}, priority=1)

    # Process jobs in priority order (priority=1 first)
    print("\nProcessing jobs in priority order:")
    for _ in range(4):
        process_next_job(queue_key)

    # Demo delayed jobs
    delayed_key = "demo:delayed_jobs"
    run_time = datetime.utcnow() + timedelta(seconds=2)
    schedule_job(delayed_key, {"type": "cleanup", "table": "sessions"}, run_at=run_time)
    schedule_job(delayed_key, {"type": "report_generation"}, run_at=run_time)

    print("\nWaiting 3 seconds for delayed jobs to become ready...")
    time.sleep(3)
    claim_ready_jobs(delayed_key)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    print("L06: Leaderboards and Queues with Redis")
    print("-" * 40)

    # Run leaderboard demo
    demo_gaming_leaderboard()

    # Run queue demo
    demo_priority_queue()

    # Demo rate limiting
    print("\n" + "=" * 60)
    print("DEMO: Rate Limiting")
    print("=" * 60)
    for i in range(7):
        is_allowed_sliding_window("user:123", limit=5, window_seconds=10)
