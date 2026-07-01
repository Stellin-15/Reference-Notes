# =============================================================================
# WHAT: Redis High Availability — Sentinel mode, Redis Cluster, replication,
#       hash slots, cross-slot limitations, and Python client patterns
# WHY:  A single Redis node is a single point of failure. HA architectures
#       eliminate downtime via automatic failover (Sentinel) or horizontal
#       sharding with built-in redundancy (Cluster). Understanding both lets
#       you pick the right model and code against it correctly.
# LEVEL: Advanced
# =============================================================================
#
# CONCEPT OVERVIEW
# ----------------
# Redis offers two complementary HA mechanisms:
#
#   SENTINEL  — monitors a primary + replicas, promotes a replica if the
#               primary dies. Single dataset, replicated N ways. Solves
#               availability WITHOUT scaling writes.
#
#   CLUSTER   — shards data across N primary nodes (each with replicas).
#               Solves BOTH availability AND horizontal write scaling.
#               Adds complexity: cross-slot operations are forbidden.
#
# Choose Sentinel when:
#   - Dataset fits on one machine
#   - You need simple failover without resharding
#   - You use multi-key transactions (MULTI/EXEC)
#
# Choose Cluster when:
#   - Dataset exceeds single-node memory
#   - You need horizontal write throughput
#   - You can redesign cross-slot operations (hash tags)
#
# PRODUCTION USE CASE
# -------------------
# Fintech platform storing sessions (Sentinel) + rate-limit counters (Cluster):
#   - Session store: small dataset, needs MULTI/EXEC for atomic session ops
#     → Sentinel with 3 sentinels, 1 primary, 2 replicas
#   - Rate limiter: billions of per-user counters, pure INCR, no transactions
#     → 6-node cluster (3 primary + 3 replica)
#
# COMMON MISTAKES
# ---------------
# 1. Cross-slot MGET in Cluster mode — fails if keys hash to different slots.
#    Fix: use hash tags {user:123}:profile and {user:123}:settings to force
#    both keys to the same slot.
# 2. Using StrictRedis instead of RedisCluster for cluster setups — regular
#    client ignores MOVED redirects.
# 3. Treating WAIT as a guarantee — WAIT blocks until N replicas acknowledge
#    but Redis replication is asynchronous; data loss is still possible in a
#    catastrophic failure.
# 4. Forgetting to handle CLUSTERDOWN errors — during a failover window the
#    cluster may refuse writes; implement retry logic.
# 5. Pipeline in cluster mode spans only ONE slot — pipeline calls that touch
#    multiple slots are silently broken into per-slot sub-pipelines by redis-py,
#    which kills the atomicity assumption.
# =============================================================================

import redis
from redis.sentinel import Sentinel
from redis.cluster import RedisCluster, ClusterNode
from redis.exceptions import (
    RedisClusterException,
    ConnectionError as RedisConnectionError,
    ResponseError,
)
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s"
)
log = logging.getLogger(__name__)

# =============================================================================
# PART 1: REPLICATION — Primary / Replica
# =============================================================================
#
# Redis replication is asynchronous by default:
#   1. Client writes to PRIMARY
#   2. PRIMARY acknowledges the client (write is committed locally)
#   3. PRIMARY streams the write to REPLICA(S) in the background
#
# This means a primary failure BEFORE the replica receives the write = data loss.
# The WAIT command can partially mitigate this.
#
# Key replication commands:
#   REPLICAOF <host> <port>  — make this instance a replica of another
#   REPLICAOF NO ONE          — promote this replica to primary (manual)
#   INFO replication          — show role, connected replicas, lag
#   WAIT <numreplicas> <timeout_ms> — block until N replicas confirm replication
# -----------------------------------------------------------------------------

def replication_demo(primary_host="localhost", primary_port=6379):
    """
    Demonstrate the WAIT command for synchronous-ish replication confirmation.

    WAIT <numreplicas> <timeout>
      - Blocks the CLIENT (not Redis) until numreplicas have acknowledged ALL
        pending writes, OR until timeout_ms milliseconds pass.
      - Returns the number of replicas that acknowledged — may be less than
        requested if timeout fires first.
      - timeout=0 means wait forever — dangerous in production, use a bound.
    """
    primary = redis.Redis(host=primary_host, port=primary_port, decode_responses=True)

    # Write a critical piece of data
    primary.set("payment:txn:9001", "confirmed", ex=3600)

    # Ask Redis to wait until 1 replica has confirmed receipt, max 500ms
    acknowledged = primary.wait(numreplicas=1, timeout=500)

    if acknowledged < 1:
        # Replication lagging — handle with care (retry, alert, etc.)
        log.warning("Replication not confirmed within timeout (got %d ack)", acknowledged)
    else:
        log.info("Write replicated to %d replica(s)", acknowledged)

    # Check replication health
    info = primary.info("replication")
    log.info("Role: %s", info.get("role"))
    log.info("Connected replicas: %d", info.get("connected_slaves", 0))

    # Display per-replica lag
    for i in range(info.get("connected_slaves", 0)):
        replica_info = info.get(f"slave{i}", "")
        log.info("Replica %d: %s", i, replica_info)


# =============================================================================
# PART 2: SENTINEL MODE
# =============================================================================
#
# Redis Sentinel is a separate process (redis-sentinel) that:
#   1. Monitors primary and replicas via PING heartbeats
#   2. Detects failure: primary fails to reply within down-after-milliseconds
#   3. Quorum: sentinels vote — at least <quorum> must agree before failover
#   4. Elects a sentinel leader to orchestrate failover
#   5. Promotes the most up-to-date replica to new primary
#   6. Reconfigures other replicas to follow new primary
#   7. Notifies clients of new primary address via Pub/Sub
#
# Sentinel setup (sentinel.conf excerpt):
#   sentinel monitor mymaster 127.0.0.1 6379 2
#     └─ name=mymaster, primary at 127.0.0.1:6379, quorum=2
#   sentinel down-after-milliseconds mymaster 5000
#     └─ primary unreachable for 5s → subjectively down (SDOWN)
#   sentinel failover-timeout mymaster 60000
#     └─ entire failover must complete within 60s
#   sentinel parallel-syncs mymaster 1
#     └─ only 1 replica resyncs at a time (limits load during failover)
#
# Quorum math:
#   Deploy an ODD number of sentinels (3 or 5).
#   quorum = (N sentinels // 2) + 1
#   3 sentinels → quorum 2 (can tolerate 1 sentinel failure)
#   5 sentinels → quorum 3 (can tolerate 2 sentinel failures)
# -----------------------------------------------------------------------------

SENTINEL_HOSTS = [
    ("sentinel1.internal", 26379),
    ("sentinel2.internal", 26379),
    ("sentinel3.internal", 26379),
]
SENTINEL_MASTER_NAME = "mymaster"

def get_sentinel_clients(
    sentinels=SENTINEL_HOSTS,
    master_name=SENTINEL_MASTER_NAME,
    password: str = None,
):
    """
    Create primary and replica clients via Sentinel.

    The Sentinel object:
      - Contacts one of the listed sentinel nodes
      - Asks "who is the current primary for <master_name>?"
      - Returns a Redis client connected to that primary
      - Automatically reconnects through Sentinel if primary changes

    sentinel.master_for()  → primary client (reads + writes)
    sentinel.slave_for()   → replica client (reads only, load-balanced)
    """
    sentinel = Sentinel(
        sentinels,
        socket_timeout=0.5,         # sentinel contact timeout
        password=password,          # Redis AUTH password (if set)
        decode_responses=True,
    )

    # Primary client — Sentinel resolves the current primary's address
    primary = sentinel.master_for(
        master_name,
        socket_timeout=2,
        retry_on_timeout=True,
    )

    # Replica client — Sentinel picks a random replica for load balancing
    replica = sentinel.slave_for(
        master_name,
        socket_timeout=2,
    )

    return primary, replica


def sentinel_health_check(sentinels=SENTINEL_HOSTS, master_name=SENTINEL_MASTER_NAME):
    """
    Query Sentinel for cluster health without going through redis-py abstraction.
    Useful in monitoring dashboards and readiness probes.
    """
    for host, port in sentinels:
        try:
            s = redis.Redis(host=host, port=port, socket_timeout=1, decode_responses=True)
            # SENTINEL MASTER <name> returns info about the monitored primary
            info = s.execute_command("SENTINEL", "MASTER", master_name)
            log.info("Sentinel %s:%d reports master: %s", host, port, info)

            # SENTINEL SLAVES <name> lists all known replicas
            slaves = s.execute_command("SENTINEL", "SLAVES", master_name)
            log.info("  Replicas: %d", len(slaves) if slaves else 0)

            # SENTINEL SENTINELS <name> lists peer sentinels (not itself)
            peers = s.execute_command("SENTINEL", "SENTINELS", master_name)
            log.info("  Peer sentinels: %d", len(peers) if peers else 0)
            break   # one healthy sentinel is enough for the health check
        except Exception as exc:
            log.warning("Sentinel %s:%d unreachable: %s", host, port, exc)


# =============================================================================
# PART 3: REDIS CLUSTER — Hash slots and sharding
# =============================================================================
#
# Hash slot mechanics:
#   - The keyspace is divided into exactly 16384 slots (0–16383).
#   - Each primary node owns a contiguous or discontiguous range of slots.
#   - When a client writes key K, Redis computes:
#       slot = CRC16(K) mod 16384
#   - The request is routed to whichever node owns that slot.
#
# Slot assignment example (3-node cluster):
#   Node A (primary): slots 0–5460
#   Node B (primary): slots 5461–10922
#   Node C (primary): slots 10923–16383
#   Each primary has 1–2 replica nodes that own 0 slots but mirror the primary.
#
# MOVED vs ASK redirects:
#   MOVED: permanent redirect — the key lives on another node, update your
#          routing table and send the command there from now on.
#   ASK:   temporary redirect during resharding — try this node just once,
#          don't update your routing table yet.
#
# Hash tags — force keys to the same slot:
#   CRC16 only hashes the content INSIDE the first {...} if present.
#   {user:123}:profile   → slot = CRC16("user:123") mod 16384
#   {user:123}:settings  → slot = CRC16("user:123") mod 16384
#   Both keys always land on the same node → multi-key ops allowed.
#
# Cross-slot operations that FAIL without hash tags:
#   MGET key1 key2          (keys on different nodes)
#   SUNIONSTORE dest src1 src2
#   MULTI/EXEC spanning multiple slots
#   Pipelines containing keys from different slots (redis-py silently fixes
#   this by splitting into per-slot sub-pipelines, losing atomicity)
# -----------------------------------------------------------------------------

CLUSTER_NODES = [
    ClusterNode("redis-node1.internal", 7000),
    ClusterNode("redis-node2.internal", 7001),
    ClusterNode("redis-node3.internal", 7002),
]

def get_cluster_client(startup_nodes=CLUSTER_NODES, password: str = None):
    """
    Create a cluster-aware Redis client.

    RedisCluster auto-discovers all nodes from the startup list,
    maintains a local slot map, and handles MOVED/ASK redirects.

    skip_full_coverage_check=True:
      In some setups not all 16384 slots are covered (e.g. during resharding).
      This flag prevents the client from raising an error in that state.
    """
    rc = RedisCluster(
        startup_nodes=startup_nodes,
        password=password,
        decode_responses=True,
        skip_full_coverage_check=True,
        # Max connections PER NODE — total pool = max_connections × node_count
        max_connections=50,
        socket_timeout=2,
        socket_connect_timeout=2,
        retry_on_timeout=True,
    )
    return rc


def cluster_basics(rc: RedisCluster):
    """
    Demonstrate basic cluster operations and slot awareness.
    """
    # Normal single-key operations work identically to standalone Redis
    rc.set("session:abc123", "user:42", ex=3600)
    val = rc.get("session:abc123")
    log.info("Got: %s", val)

    # Multi-key operation WITHOUT hash tags — may fail if keys on diff nodes
    try:
        rc.mset({"counter:a": 1, "counter:b": 2})
        vals = rc.mget("counter:a", "counter:b")
        log.info("MGET (no hash tag): %s", vals)
    except RedisClusterException as exc:
        log.warning("Cross-slot error (expected): %s", exc)

    # Multi-key operation WITH hash tags — guaranteed same slot
    rc.mset({"{counters}:a": 1, "{counters}:b": 2})
    vals = rc.mget("{counters}:a", "{counters}:b")
    log.info("MGET (hash tag): %s", vals)   # always works


def cluster_info_commands(rc: RedisCluster):
    """
    Inspect cluster topology using CLUSTER subcommands.
    These commands are forwarded to a specific node; RedisCluster
    exposes helpers that aggregate across all nodes.
    """
    # CLUSTER INFO — cluster-wide summary from one node
    info = rc.cluster_info()
    log.info("Cluster state: %s", info.get("cluster_state"))   # "ok" = healthy
    log.info("Known nodes: %s", info.get("cluster_known_nodes"))
    log.info("Slots assigned: %s", info.get("cluster_slots_assigned"))  # should be 16384

    # CLUSTER NODES — full topology: node IDs, addresses, roles, slot ranges
    nodes = rc.cluster_nodes()
    for node_id, node_data in nodes.items():
        log.info(
            "Node %s  role=%-8s  slots=%s",
            node_data.get("host"),
            node_data.get("server_type"),   # "primary" or "replica"
            node_data.get("slots"),
        )

    # CLUSTER KEYSLOT — which slot a key belongs to (useful for debugging)
    key = "session:xyz"
    slot = rc.cluster_keyslot(key)
    log.info("Key '%s' → slot %d", key, slot)


def cluster_pipeline_demo(rc: RedisCluster):
    """
    Pipeline behavior in cluster mode.

    redis-py's ClusterPipeline splits commands across per-slot sub-pipelines
    transparently. Commands to different slots are batched per-node and sent
    in parallel. This maximizes throughput but BREAKS the atomicity guarantee
    of a normal pipeline — commands are NOT executed in one atomic operation.

    If you need atomicity, use MULTI/EXEC on keys with the same hash tag.
    """
    # All keys share hash tag {session} → same slot → truly batched to one node
    pipe = rc.pipeline(transaction=False)
    pipe.set("{session}:user:1", "alice")
    pipe.set("{session}:user:2", "bob")
    pipe.get("{session}:user:1")
    pipe.get("{session}:user:2")
    results = pipe.execute()    # redis-py sends all to the same node
    log.info("Pipeline results: %s", results)


def demonstrate_hash_tags():
    """
    Reference table of hash tag usage patterns.

    Without hash tag → slot computed from full key name → may differ per key.
    With hash tag    → slot computed from {...} content  → same for matching tags.
    """
    examples = [
        # (key, hash_tag_content, notes)
        ("user:123:profile",        None,           "no hash tag, any slot"),
        ("user:123:settings",       None,           "no hash tag, different slot likely"),
        ("{user:123}:profile",      "user:123",     "same slot as next key"),
        ("{user:123}:settings",     "user:123",     "same slot, multi-key ops allowed"),
        ("{orders}:pending",        "orders",       "groups all order keys"),
        ("{orders}:fulfilled",      "orders",       "same slot as pending"),
        ("{}:key",                  "",             "empty tag → full key used for CRC16"),
        ("a{}b:key",                None,           "no valid tag → full key for CRC16"),
    ]
    log.info("Hash tag examples:")
    for key, tag, notes in examples:
        # Simulate slot computation (python pure implementation)
        import binascii
        def keyslot(k):
            # Extract hash tag if present
            s = k.find("{")
            e = k.find("}", s + 1) if s >= 0 else -1
            if s >= 0 and e > s + 1:
                k = k[s + 1:e]
            crc = binascii.crc_hqx(k.encode(), 0)
            return crc % 16384
        log.info("  slot=%5d  key=%-35s  tag=%s  (%s)", keyslot(key), key, tag, notes)


# =============================================================================
# PART 4: Connection pooling in clustered setups
# =============================================================================
#
# In standalone Redis, one pool is shared across the app.
# In Cluster mode, redis-py maintains a pool PER NODE automatically.
#
# Sizing guidance:
#   pool_size = threads_per_process × 2
#   (×2 because a request may briefly hold two connections: read + write)
#
# For Cluster with N nodes:
#   total_connections = pool_size_per_node × N
#   e.g. 50 per node × 6 nodes = 300 connections total
#   Check: ulimit -n (open files) on the Redis server host.
# -----------------------------------------------------------------------------

def create_sized_cluster_client(max_conn_per_node: int = 50):
    """
    Create a cluster client with explicit connection pool sizing.
    Monitor pool exhaustion with ConnectionError: too many connections.
    """
    rc = RedisCluster(
        startup_nodes=CLUSTER_NODES,
        decode_responses=True,
        max_connections=max_conn_per_node,   # per node, not total
        socket_keepalive=True,               # keep TCP alive to detect drops
        health_check_interval=30,            # background PING every 30s
    )
    return rc


# =============================================================================
# PART 5: Sentinel vs Cluster — Decision summary
# =============================================================================
#
# ┌───────────────────────────┬──────────────────────┬──────────────────────┐
# │ Dimension                 │ Sentinel             │ Cluster              │
# ├───────────────────────────┼──────────────────────┼──────────────────────┤
# │ Data sharding             │ No (all on primary)  │ Yes (16384 slots)    │
# │ Write scalability         │ No                   │ Yes (N primaries)    │
# │ Dataset size limit        │ Single node RAM       │ N × node RAM         │
# │ Multi-key transactions    │ Yes (MULTI/EXEC)     │ Only same-slot keys  │
# │ Pipelining atomicity      │ Yes                  │ Only same-slot keys  │
# │ Lua scripts               │ Yes (all keys)       │ Only same-slot keys  │
# │ SCAN across all keys      │ Yes                  │ Need SCAN per node   │
# │ Failover time             │ ~5–30s (configurable)│ ~1–3s                │
# │ Operational complexity    │ Low                  │ Medium–High          │
# │ Minimum recommended nodes │ 1 primary + 2 replicas│ 6 (3+3)            │
# │                           │ + 3 sentinels        │                      │
# │ Resharding (add nodes)    │ Requires data move   │ Online resharding    │
# │ Sentinel needed?          │ Yes                  │ No (built-in)        │
# └───────────────────────────┴──────────────────────┴──────────────────────┘
#
# TL;DR:
#   Single large instance, complex transactions → Sentinel
#   Massive dataset or write throughput needed  → Cluster
# =============================================================================

def sentinel_vs_cluster_code_example():
    """
    Show how application code changes (or doesn't) between Sentinel and Cluster.
    Most Redis commands look identical — the difference is in client setup.
    """

    # --- Sentinel setup ---
    sentinel = Sentinel([("sentinel1", 26379)], socket_timeout=0.5)
    sentinel_primary = sentinel.master_for("mymaster", decode_responses=True)

    # --- Cluster setup ---
    cluster_client = RedisCluster(
        startup_nodes=[ClusterNode("redis-node1", 7000)],
        decode_responses=True,
    )

    # The application code below is IDENTICAL for both clients:
    for client in [sentinel_primary, cluster_client]:
        try:
            client.set("test:key", "hello")
            val = client.get("test:key")
            log.info("Got from %s: %s", type(client).__name__, val)
        except Exception as exc:
            log.warning("Client %s error: %s", type(client).__name__, exc)


# =============================================================================
# PART 6: Consistent hashing vs Hash slots
# =============================================================================
#
# Consistent hashing (used by Memcached, some older Redis proxies):
#   - Keys are placed on a virtual ring of 2^32 positions
#   - Nodes occupy positions on the ring
#   - Key goes to the nearest node clockwise on the ring
#   - Adding/removing a node only remaps 1/N of the keys
#   - Pro: minimal remapping on topology changes
#   - Con: uneven distribution unless virtual nodes are added
#
# Hash slots (Redis Cluster):
#   - Fixed 16384 slots, explicitly assigned to nodes
#   - CRC16(key) mod 16384 is deterministic and fast
#   - Resharding moves whole slots between nodes (not individual keys)
#   - Pro: explicit control, easy to reason about placement
#   - Con: resharding requires coordination (CLUSTER SETSLOT, migrate)
#   - Why 16384? 16384 bits fits in a cluster gossip heartbeat message,
#     and it gives fine enough granularity for 1000 nodes (16 slots/node).
# =============================================================================

def explain_slot_computation(key: str) -> int:
    """
    Pure-Python slot computation matching Redis's algorithm.
    Useful for debugging placement without a live cluster.
    """
    import binascii

    # If key contains {...}, use only the content inside braces
    start = key.find("{")
    if start >= 0:
        end = key.find("}", start + 1)
        if end > start + 1:
            key = key[start + 1:end]    # strip to hash tag content

    # CRC-16/CCITT (using Python's crc_hqx which implements CCITT variant)
    crc = binascii.crc_hqx(key.encode("utf-8"), 0)
    slot = crc % 16384
    log.info("Key '%s' → slot %d", key, slot)
    return slot


if __name__ == "__main__":
    # Demonstrate slot computation (no live Redis needed)
    keys_to_check = [
        "user:123",
        "{user:123}:profile",
        "{user:123}:settings",
        "order:456",
        "{order:456}:items",
    ]
    log.info("=== Slot computation demo ===")
    for k in keys_to_check:
        explain_slot_computation(k)

    # To test against a live Sentinel:
    # primary, replica = get_sentinel_clients()
    # replication_demo()

    # To test against a live Cluster:
    # rc = get_cluster_client()
    # cluster_basics(rc)
    # cluster_info_commands(rc)
