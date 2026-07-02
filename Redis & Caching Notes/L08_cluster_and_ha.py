# ============================================================
# L07: Redis Cluster, High Availability, and Production Ops
# ============================================================
# WHAT: Redis Cluster for horizontal scaling, Redis Sentinel
#       for single-node HA, persistence (AOF + RDB), memory
#       optimization, and monitoring/debugging tools.
# WHY:  A single Redis node caps at ~100k ops/sec and ~tens of
#       GB RAM. Cluster removes both limits. Sentinel removes
#       the single point of failure. Both are needed in prod.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    Redis Cluster splits 16384 hash slots across multiple master
    nodes. Every key is deterministically assigned to one slot
    via CRC16(key) % 16384. Each master owns a range of slots.
    Adding nodes rebalances slots without downtime.

    Hash tags let you force multiple keys to the same slot:
    keys containing {tag} are slotted by the tag, not the full
    key string. This is essential for MGET, MSET, transactions,
    and Lua scripts that touch multiple keys.

    Redis Sentinel is separate from Cluster — it's for a
    single master with replicas. Sentinel instances form a
    quorum to detect master failure and automatically elect a
    new master. Clients connect to Sentinel to discover the
    current master's address.

    Persistence: RDB is a periodic snapshot (fast to load, but
    you can lose up to the snapshot interval). AOF logs every
    write command (more durable, slower to replay on restart).
    Use both: RDB for fast restarts, AOF for data durability.

PRODUCTION USE CASE:
    - Twitter, GitHub, Shopify all use Redis Cluster for
      session storage, caching, and real-time counters at
      millions of ops/second across dozens of nodes.
    - Sentinel is used for smaller setups (e.g., per-service
      Redis) where a cluster is overkill but failover is required.
    - AOF with appendfsync everysec is the standard trade-off:
      at most 1 second of data loss on a crash.

COMMON MISTAKES:
    1. Using MGET/MSET across keys on different cluster nodes —
       this fails with a CROSSSLOT error. Use hash tags or
       individual GET commands in a pipeline instead.
    2. Running KEYS * in production on any node — it scans all
       keys in that node's slots and blocks the event loop.
       Use SCAN with a cursor and a MATCH pattern instead.
    3. Only running 2 Sentinel instances — you need an odd
       number >= 3 for quorum. With 2, you can never reach
       majority and failover won't happen.
    4. Not testing failover — Sentinel failover needs rehearsal.
       Run SENTINEL FAILOVER mymaster periodically in staging.
    5. Setting maxmemory without a maxmemory-policy — when
       memory is full, Redis will return OOM errors. Always
       set a policy (allkeys-lru for caching workloads).
    6. Using MONITOR in production — it logs every command,
       doubles the CPU load, and saturates your network. Dev only.
    7. Not setting save intervals for RDB — "save ''" disables
       RDB entirely. Many users think they have persistence but
       they turned it off during setup and forgot.
"""

import redis
from redis.cluster import RedisCluster
from redis.sentinel import Sentinel
import time


# ============================================================
# SECTION 1: REDIS CLUSTER CONCEPTS AND CLIENT SETUP
# ============================================================

def demo_cluster_connection() -> RedisCluster | None:
    """
    Connect to a Redis Cluster using redis-py's RedisCluster client.

    You only need to provide one or more startup nodes. The client
    auto-discovers the full cluster topology by sending CLUSTER NODES
    on startup and caches the slot-to-node mapping.

    MOVED redirections: if you send a key to the wrong node (e.g.,
    cached topology is stale), the node responds:
        MOVED 7638 192.168.1.2:6379
    The client transparently retries the correct node and updates
    its slot cache. You never see this as an application error.

    ASK redirections: sent during slot migration (resharding).
    The client sends ASKING to the target node before retrying.
    Again, transparent to the application.
    """
    # In production: provide 3+ startup nodes for resilience.
    # The client only needs ONE to bootstrap — the rest are fallbacks.
    startup_nodes = [
        {"host": "redis-node-1", "port": 6379},
        {"host": "redis-node-2", "port": 6379},
        {"host": "redis-node-3", "port": 6379},
    ]

    try:
        rc = RedisCluster(
            startup_nodes=startup_nodes,
            decode_responses=True,
            # skip_full_coverage_check=True: allow operations even if
            # some slots have no master (e.g., during a node failure)
            skip_full_coverage_check=True,
        )
        print("Connected to Redis Cluster")
        return rc
    except Exception as e:
        print(f"Could not connect to cluster (expected in dev): {e}")
        return None


def explain_hash_slots() -> None:
    """
    Explain how hash slots work and demonstrate the hash tag concept.

    Redis Cluster has exactly 16384 slots (0..16383).
    Each key is assigned: CLUSTER KEYSLOT key = CRC16(key) % 16384

    Without hash tags, two related keys often land on different
    nodes, making multi-key operations (MGET, transactions, Lua)
    impossible across them.

    With hash tags ({tag}), the slot is computed from only the
    part inside the first {...}, so you can co-locate related keys.
    """
    print("\n--- Hash Slot Explanation ---")
    print("Keys without hash tags may be on DIFFERENT nodes:")
    print("  user:1001:profile  -> slot A (node 1)")
    print("  user:1001:cart     -> slot B (node 3)")
    print("  MGET on these TWO keys -> CROSSSLOT ERROR")

    print("\nKeys WITH hash tags share a slot:")
    print("  {user:1001}:profile  -> slot of 'user:1001' (same node)")
    print("  {user:1001}:cart     -> slot of 'user:1001' (same node)")
    print("  MGET on these TWO keys -> works! Both on same node")

    print("\nHash tag use cases:")
    print("  - MGET/MSET for related keys in a single round trip")
    print("  - Lua scripts that access multiple keys (must be same slot)")
    print("  - MULTI/EXEC transactions on multiple keys")
    print("  - ZUNIONSTORE / ZINTERSTORE destination and sources")


def demo_cluster_info_commands() -> None:
    """
    Redis CLI commands to inspect cluster state.
    These are run via redis-cli, not redis-py directly.
    Shown as strings here for reference.
    """
    print("\n--- Cluster Inspection Commands ---")
    commands = {
        "CLUSTER INFO": (
            "Overview: cluster_state, slots_assigned, known_nodes, "
            "cluster_size. cluster_state:ok means all slots covered."
        ),
        "CLUSTER NODES": (
            "One line per node: nodeId, ip:port, flags (master/slave/fail), "
            "masterId, ping, pong, configEpoch, connected, slots."
        ),
        "CLUSTER KEYSLOT key": (
            "Returns the slot number for a key. Use to predict which "
            "node a key lands on. E.g.: CLUSTER KEYSLOT user:1001 -> 4782"
        ),
        "CLUSTER SLOTS": (
            "Maps slot ranges to master+replica addresses. "
            "Deprecated — use CLUSTER SHARDS in Redis 7+."
        ),
        "CLUSTER SHARDS": (
            "Redis 7+. Returns slot ranges, node IDs, and replica info. "
            "Preferred over CLUSTER SLOTS."
        ),
        "CLUSTER COUNTKEYSINSLOT 4782": (
            "Count keys in a specific slot. Useful for resharding decisions."
        ),
    }
    for cmd, explanation in commands.items():
        print(f"\n  {cmd}")
        print(f"    {explanation}")


# ============================================================
# SECTION 2: REDIS SENTINEL FOR SINGLE-INSTANCE HA
# ============================================================

def demo_sentinel_connection() -> redis.Redis | None:
    """
    Connect to Redis via Sentinel for automatic failover.

    Sentinel architecture:
    - 3+ Sentinel processes monitor the same master
    - If master is unreachable, Sentinels vote (quorum)
    - Quorum reached → Sentinel promotes a replica to master
    - Sentinel notifies clients of the new master address
    - Client libraries reconnect automatically

    The Sentinel client abstracts this: you connect to Sentinels
    and ask for the current master by logical name ('mymaster').
    If failover happens, the next connection goes to the new master.
    """
    # Provide all Sentinel addresses for resilience.
    # If one Sentinel is down, the client tries the next.
    sentinel_nodes = [
        ("sentinel-1", 26379),
        ("sentinel-2", 26379),
        ("sentinel-3", 26379),
    ]

    try:
        sentinel = Sentinel(
            sentinel_nodes,
            socket_timeout=0.1,       # fast timeout per Sentinel
            decode_responses=True,
        )

        # master_for: returns a Redis client always pointing to
        # the current master. On failover, the next call re-resolves.
        master = sentinel.master_for(
            "mymaster",               # logical name in sentinel.conf
            socket_timeout=0.1,
            password="your-password", # if auth required
        )

        # slave_for: returns a client pointing to a replica.
        # Use for read-heavy workloads to offload the master.
        # WARNING: replica may lag behind master (async replication).
        replica = sentinel.slave_for("mymaster", socket_timeout=0.1)

        print("Connected to master via Sentinel")
        return master
    except Exception as e:
        print(f"Could not connect via Sentinel (expected in dev): {e}")
        return None


def explain_sentinel_config() -> None:
    """
    Key Sentinel configuration directives (sentinel.conf).
    """
    print("\n--- sentinel.conf Key Directives ---")
    config = """
# Monitor 'mymaster' at 192.168.1.10:6379 with quorum=2
# quorum: minimum number of Sentinels that must agree
# master is unreachable before initiating failover.
# With 3 Sentinels, quorum=2 means majority agreement.
sentinel monitor mymaster 192.168.1.10 6379 2

# How long (ms) Sentinel waits after last successful ping
# before considering a master SDOWN (subjectively down).
sentinel down-after-milliseconds mymaster 5000

# How many replicas can be reconfigured simultaneously
# during failover. 1 = one at a time (safest).
sentinel parallel-syncs mymaster 1

# How long (ms) to wait for failover to complete.
# If exceeded, another Sentinel can take over.
sentinel failover-timeout mymaster 60000

# Require password on master/replicas
sentinel auth-pass mymaster your-password
    """
    print(config)


def explain_sentinel_commands() -> None:
    """
    Useful Sentinel CLI commands for monitoring and testing.
    """
    print("\n--- Sentinel Commands ---")
    commands = {
        "SENTINEL masters": "List all monitored masters and their state.",
        "SENTINEL replicas mymaster": "List replicas of 'mymaster'.",
        "SENTINEL sentinels mymaster": "List other Sentinel processes.",
        "SENTINEL get-master-addr-by-name mymaster": "Get current master IP:port.",
        "SENTINEL FAILOVER mymaster": (
            "Manually trigger a failover (test this in staging!)."
        ),
        "SENTINEL RESET mymaster": (
            "Reset Sentinel's internal state for 'mymaster'. "
            "Use after topology changes."
        ),
    }
    for cmd, explanation in commands.items():
        print(f"\n  {cmd}")
        print(f"    {explanation}")


# ============================================================
# SECTION 3: PERSISTENCE — AOF AND RDB
# ============================================================

def explain_aof_config() -> None:
    """
    AOF (Append-Only File) persistence configuration.

    AOF logs every write command to disk. On restart, Redis
    replays the log to reconstruct the dataset.
    """
    print("\n--- AOF Configuration (redis.conf) ---")
    config = """
# Enable AOF
appendonly yes

# AOF filename
appendfilename "appendonly.aof"

# appendfsync controls durability vs. performance trade-off:
#   always:   fsync after every command. Max durability, slowest.
#             ~1000 writes/sec cap. Use only for critical data.
#   everysec: fsync once per second (background thread).
#             At most 1 second of data loss. RECOMMENDED.
#   no:       Let the OS decide when to flush. Fastest, riskiest.
appendfsync everysec

# Don't fsync during AOF rewrite (avoids I/O contention).
# Accepts up to 30s extra data loss during rewrite.
no-appendfsync-on-rewrite yes

# Trigger AOF rewrite when file grows by 100% since last rewrite.
auto-aof-rewrite-percentage 100

# Minimum AOF file size before rewrite is considered.
auto-aof-rewrite-min-size 64mb

# Hybrid RDB+AOF format: start AOF file with RDB snapshot,
# then append commands. Faster to load than pure AOF.
# RECOMMENDED for new deployments.
aof-use-rdb-preamble yes
    """
    print(config)


def explain_rdb_config() -> None:
    """
    RDB (Redis Database) snapshot persistence configuration.

    RDB creates point-in-time snapshots using a fork-based
    copy-on-write approach. The main process continues serving
    requests while the child writes the snapshot.
    """
    print("\n--- RDB Configuration (redis.conf) ---")
    config = """
# Save format: save <seconds> <changes>
# Save every 900s if at least 1 key changed
save 900 1
# Save every 300s if at least 10 keys changed
save 300 10
# Save every 60s if at least 10000 keys changed
save 60 10000

# To disable RDB: save ""

# If a background save fails, refuse writes. This prevents
# silent data loss. Disable if you have external monitoring.
stop-writes-on-bgsave-error yes

# Compress the RDB file with LZF. Small CPU cost, ~30% smaller file.
rdbcompression yes

# Checksum the RDB file on load. 10% performance cost on load.
rdbchecksum yes

# RDB filename
dbfilename dump.rdb

# Directory for RDB and AOF files
dir /var/lib/redis
    """
    print(config)


def explain_persistence_trade_offs() -> None:
    """
    When to use RDB, AOF, or both.
    """
    print("\n--- Persistence Trade-Off Summary ---")
    trade_offs = [
        ("RDB only",
         "Fast restarts, small files, but can lose minutes of data. "
         "Good for: caches where losing recent data is acceptable."),
        ("AOF only",
         "At most 1s data loss (everysec), but slower restarts for "
         "large datasets (must replay all commands). Larger files."),
        ("Both (recommended)",
         "On restart, Redis uses AOF (more complete). RDB provides "
         "fast backup and speeds up AOF rewrite (hybrid format). "
         "Best durability + reasonable restart speed."),
        ("Neither",
         "Pure in-memory. Fastest. All data lost on restart. "
         "Use only for ephemeral data (sessions with re-login OK)."),
    ]
    for mode, description in trade_offs:
        print(f"\n  {mode}:")
        print(f"    {description}")


# ============================================================
# SECTION 4: MEMORY OPTIMIZATION
# ============================================================

def explain_memory_optimization() -> None:
    """
    Redis memory optimization techniques and commands.
    """
    print("\n--- Memory Optimization ---")

    print("\n1. INTERNAL ENCODING OPTIMIZATION")
    print("""
  Redis automatically uses compact encodings for small structures:
    Hash   < 128 fields, values < 64 bytes → listpack (was ziplist)
    List   < 128 elements, values < 64 bytes → listpack
    ZSet   < 128 members, values < 64 bytes → listpack
    Set    < 128 integers → intset

  Once these thresholds are exceeded, Redis switches to the full
  hash table / skiplist / linked list encoding — much more memory.

  Config to tune thresholds:
    hash-max-listpack-entries 128
    hash-max-listpack-value 64
    zset-max-listpack-entries 128
    zset-max-listpack-value 64
    list-max-listpack-size 128
    set-max-intset-entries 512
    """)

    print("\n2. MAXMEMORY POLICY")
    print("""
  Set a memory cap and eviction policy:
    maxmemory 4gb
    maxmemory-policy allkeys-lru

  Eviction policies:
    noeviction       Error on write when full. Use for queues (can't lose data).
    allkeys-lru      Evict any key using LRU. Best for general caches.
    volatile-lru     Evict only keys with TTL using LRU. Mix of persistent + cache.
    allkeys-lfu      LFU (frequency) — better than LRU for skewed access patterns.
    volatile-ttl     Evict shortest-lived TTL first. Evicts keys expiring soonest.
    allkeys-random   Random eviction. Not recommended (no intelligence).
    """)

    print("\n3. KEY OVERHEAD")
    print("""
  Every Redis key has ~50 bytes overhead regardless of content.
  A key named 'u:1234:sess' uses 50 + 12 = 62 bytes just for the key.
  Keep keys short. Use hash structures to group related fields:
    INSTEAD OF: SET user:1234:name "Alice"    (50 + 14 + 5 = 69 bytes)
                SET user:1234:email "a@b.com" (50 + 15 + 7 = 72 bytes)
    USE:        HSET user:1234 name "Alice" email "a@b.com"
                (50 + 9 bytes for key, fields stored in listpack)
    """)


def run_memory_commands(r: redis.Redis) -> None:
    """
    Redis commands for inspecting memory usage.
    """
    print("\n--- Memory Inspection Commands ---")
    commands = {
        "MEMORY USAGE key [SAMPLES n]": (
            "Bytes consumed by a specific key (including overhead). "
            "SAMPLES controls how many list/hash elements to sample. "
            "Default 5. Use 0 for exact (slower)."
        ),
        "MEMORY DOCTOR": (
            "High-level memory report. Flags issues like: "
            "'High allocator frag ratio', 'Big peak-to-current ratio'."
        ),
        "MEMORY STATS": (
            "Detailed memory breakdown: used_memory, rss, peak, "
            "fragmentation_ratio, allocator stats."
        ),
        "OBJECT ENCODING key": (
            "Show internal encoding: listpack, ziplist, hashtable, "
            "skiplist, quicklist, embstr, raw, int, etc."
        ),
        "DEBUG JMAP": (
            "Dev-only. Force memory consolidation. Never in production."
        ),
        "INFO memory": (
            "One-line-per-metric memory stats. Useful for time series "
            "monitoring. Key fields: used_memory_human, mem_fragmentation_ratio."
        ),
    }
    for cmd, explanation in commands.items():
        print(f"\n  {cmd}")
        print(f"    {explanation}")


# ============================================================
# SECTION 5: MONITORING AND DEBUGGING
# ============================================================

def explain_slow_log() -> None:
    """
    Redis Slow Log: track commands taking longer than a threshold.
    """
    print("\n--- Slow Log ---")
    print("""
  Config:
    slowlog-log-slower-than 10000   # microseconds (10ms default)
    slowlog-max-len 128             # number of entries to keep

  Commands:
    SLOWLOG GET 10      → last 10 slow commands
    SLOWLOG LEN         → number of entries currently in slow log
    SLOWLOG RESET       → clear the slow log

  Each entry contains:
    - Unique ID
    - Unix timestamp when the command was executed
    - Execution time in microseconds
    - Command + arguments (truncated if large)
    - Client IP:port
    - Client name (if SET CLIENT SETNAME was used)

  Common slow commands to watch for:
    KEYS *              → O(N) full scan — never in prod
    SMEMBERS on a huge set → O(N)
    SORT without LIMIT  → O(N log N)
    HGETALL on a large hash → O(N)
    LRANGE 0 -1         → O(N) full list scan
    """)


def explain_latency_monitoring() -> None:
    """
    Redis latency monitoring — tracks latency spikes over time.
    """
    print("\n--- Latency Monitoring ---")
    print("""
  Enable:
    CONFIG SET latency-monitor-threshold 100  # ms

  Commands:
    LATENCY LATEST          → Most recent latency spike per event type
    LATENCY HISTORY event   → Time series of latency for one event type
    LATENCY RESET           → Clear all latency data
    LATENCY GRAPH event     → ASCII art latency graph

  Common event types:
    command          → Command execution latency
    fast-command     → O(1) command took longer than expected
    aof-stat         → AOF flush latency
    rdb-unlink-temp-file → Post-snapshot cleanup latency

  LATENCY LATEST output example:
    command 1625000000 142 200
    (event, last_latency_ms, timestamp, max_ever_latency_ms)
    """)


def explain_monitor_command() -> None:
    """
    MONITOR: real-time command stream. DEV ONLY.
    """
    print("\n--- MONITOR (Dev Only) ---")
    print("""
  MONITOR streams every command received by Redis to your client.

  Usage (redis-cli):
    redis-cli MONITOR

  Output example:
    1625000001.234567 [0 127.0.0.1:52419] "SET" "key" "value"
    1625000001.235001 [0 127.0.0.1:52419] "GET" "key"

  WARNING:
    - Doubles CPU usage on a busy Redis instance
    - Can saturate your network link
    - Use only in development or very briefly in production
      for debugging a specific issue with rate limiting (MONITOR
      against a staging replica is safer)

  Alternatives for production debugging:
    - SLOWLOG GET for slow commands
    - LATENCY HISTORY for latency spikes
    - keyspace notifications (CONFIG SET notify-keyspace-events)
      to subscribe to specific event types (expiry, set, del, etc.)
    """)


def monitoring_checklist() -> None:
    """
    Monitoring metrics to collect and alert on in production.
    """
    print("\n--- Production Monitoring Checklist ---")
    metrics = {
        "used_memory / maxmemory": (
            "Memory utilization %. Alert at 80%, page at 90%. "
            "From INFO memory: used_memory."
        ),
        "mem_fragmentation_ratio": (
            "RSS / used_memory. >1.5 means fragmentation is wasting RAM. "
            "Run MEMORY PURGE to compact (pauses Redis briefly). "
            "Or restart Redis to reset fragmentation."
        ),
        "keyspace_hits / (hits + misses)": (
            "Cache hit rate. Alert if it drops below expected baseline "
            "(e.g., your usual 95% drops to 70% = cache invalidation bug)."
        ),
        "evicted_keys": (
            "Non-zero means maxmemory policy is evicting data. "
            "Fine for pure caches. Not OK for queues or persistent data."
        ),
        "connected_clients": (
            "Alert at 80% of maxclients (default 10000). "
            "Connection exhaustion = app errors."
        ),
        "blocked_clients": (
            "Clients waiting on BRPOP/BLPOP. Normal if using blocking pop. "
            "Unexpected spike = queue backup."
        ),
        "rejected_connections": (
            "Connections refused because maxclients hit. "
            "Critical — means requests are being dropped."
        ),
        "instantaneous_ops_per_sec": (
            "Commands per second. Track baseline. Unexpected spikes "
            "could be a rogue KEYS * or a retry storm."
        ),
        "rdb_last_bgsave_status / aof_last_bgrewrite_status": (
            "Alert if either shows 'err'. Persistence is broken."
        ),
        "replication_lag (master_repl_offset - slave_repl_offset)": (
            "From INFO replication. Alert if replica lag > 1MB or > 1s. "
            "High lag = replica data is stale."
        ),
    }
    for metric, explanation in metrics.items():
        print(f"\n  {metric}")
        print(f"    {explanation}")


# ============================================================
# SECTION 6: CLUSTER SETUP WALKTHROUGH
# ============================================================

def cluster_setup_steps() -> None:
    """
    Step-by-step Redis Cluster setup reference.
    """
    print("\n--- Redis Cluster Setup Steps ---")
    steps = """
STEP 1: Configure each node (redis.conf)
  port 6379
  cluster-enabled yes
  cluster-config-file nodes.conf      # auto-managed by Redis
  cluster-node-timeout 5000           # ms before a node is considered down
  appendonly yes                      # AOF persistence recommended
  protected-mode no                   # if binding to non-loopback

STEP 2: Start all Redis instances
  redis-server /etc/redis/redis-6379.conf
  redis-server /etc/redis/redis-6380.conf
  ... (one per node)

STEP 3: Create the cluster
  # --cluster-replicas 1: one replica per master
  # 6 nodes → 3 masters, 3 replicas
  redis-cli --cluster create \\
    192.168.1.1:6379 \\
    192.168.1.2:6379 \\
    192.168.1.3:6379 \\
    192.168.1.1:6380 \\
    192.168.1.2:6380 \\
    192.168.1.3:6380 \\
    --cluster-replicas 1

STEP 4: Verify cluster state
  redis-cli -c CLUSTER INFO
  redis-cli -c CLUSTER NODES

STEP 5: Test with a key
  redis-cli -c -h 192.168.1.1 -p 6379 SET foo bar
  # -c flag enables cluster mode (handles MOVED redirections)

ADD A NEW NODE:
  redis-cli --cluster add-node 192.168.1.4:6379 192.168.1.1:6379
  redis-cli --cluster reshard 192.168.1.1:6379

REMOVE A NODE:
  redis-cli --cluster reshard (move all slots away first)
  redis-cli --cluster del-node 192.168.1.1:6379 <node-id>
    """
    print(steps)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    print("L07: Redis Cluster, HA, Persistence, and Monitoring")
    print("-" * 40)

    # Run all explanation functions
    explain_hash_slots()
    demo_cluster_info_commands()
    explain_sentinel_config()
    explain_sentinel_commands()
    explain_aof_config()
    explain_rdb_config()
    explain_persistence_trade_offs()
    explain_memory_optimization()
    explain_slow_log()
    explain_latency_monitoring()
    explain_monitor_command()
    monitoring_checklist()
    cluster_setup_steps()

    # Attempt live connections (will gracefully fail in dev)
    print("\n--- Live Connection Attempts ---")
    demo_cluster_connection()
    demo_sentinel_connection()
