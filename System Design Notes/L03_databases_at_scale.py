# =============================================================================
# WHAT: Databases at Scale — Replication, Sharding, Indexing, CQRS, CAP Theorem
# WHY:  A single database server cannot handle millions of concurrent reads/writes.
#       Understanding when and how to scale the data layer is the most critical
#       and irreversible architectural decision in a distributed system.
# LEVEL: Intermediate → Advanced (System Design Interview / Production Ready)
# =============================================================================
#
# CONCEPT OVERVIEW:
#   Read Replicas       → copies of the primary DB that serve reads; primary handles writes.
#   Vertical Scaling    → bigger machine (more CPU/RAM). Simple but has a ceiling.
#   Horizontal Scaling  → more machines. Required beyond the vertical ceiling.
#   Sharding            → splitting data across multiple DB instances (shards).
#   Connection Pooling  → reusing DB connections to avoid per-request overhead.
#   CQRS                → separate read and write models for independent scaling.
#   Event Sourcing      → store events, not state; derive current state by replay.
#   CAP Theorem         → a distributed system can guarantee at most 2 of:
#                         Consistency, Availability, Partition Tolerance.
#
# PRODUCTION USE CASES:
#   - Instagram uses PostgreSQL with read replicas + sharding by user ID.
#   - Cassandra (AP system) powers Discord's message storage at billions of messages.
#   - PgBouncer sits in front of PostgreSQL at Notion/Shopify to pool thousands
#     of app connections into a handful of DB connections.
#   - CQRS + Event Sourcing is used by bank ledgers and e-commerce order systems.
#
# COMMON MISTAKES:
#   1. Reading from primary when a replica suffices → unnecessary primary load.
#   2. Sharding too early → complexity without benefit.
#   3. Choosing a shard key that creates hot shards (e.g., timestamp as shard key).
#   4. Not accounting for cross-shard queries and distributed transactions.
#   5. Using a relational DB for everything → graph or time-series would be far better.
#   6. Confusing CAP "Consistency" with ACID "Consistency" — they are different things.
# =============================================================================

import hashlib
import bisect
import time
import random
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, Tuple
from enum import Enum
from collections import defaultdict
from abc import ABC, abstractmethod

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# =============================================================================
# SECTION 1: VERTICAL vs HORIZONTAL SCALING
# =============================================================================
# VERTICAL SCALING (Scale-Up):
#   → Replace server with a bigger one (more CPU cores, RAM, NVMe SSDs).
#   PROS: simple — no application changes required; no distribution complexity.
#   CONS: has a hard ceiling (largest available instance); single point of failure;
#         expensive; requires downtime for the hardware swap.
#   WHEN: start here; delay horizontal scaling as long as economically viable.
#
# HORIZONTAL SCALING (Scale-Out):
#   → Add more servers; distribute data and/or requests across them.
#   PROS: theoretically unlimited scale; redundancy (no SPOF); cheaper commodity hardware.
#   CONS: complexity — distributed transactions, cross-node joins, consistency challenges.
#   WHEN: when vertical scaling ceiling is hit or cost exceeds benefits.

class ScalingStrategy(Enum):
    VERTICAL   = "vertical"    # bigger machine
    HORIZONTAL = "horizontal"  # more machines


# =============================================================================
# SECTION 2: READ REPLICAS AND WRITE SCALING
# =============================================================================
# Read Replicas = additional DB servers that receive a copy of every write
# from the primary (via replication log / WAL), but are only used for reads.
#
# REPLICATION LAG: replicas are slightly behind the primary (typically < 100 ms,
# but can be seconds under heavy write load). This means reads from a replica
# may return slightly stale data — this is called EVENTUAL CONSISTENCY.
#
# USE READ REPLICAS FOR:
#   - Dashboard / analytics queries (can tolerate slight staleness)
#   - Full-text search queries
#   - Background report generation
# ALWAYS USE PRIMARY FOR:
#   - Reads immediately after a write (read-your-writes requirement)
#   - Inventory checks before purchase
#   - Auth token lookups

@dataclass
class DatabaseNode:
    """Represents one database server (primary or replica)."""
    node_id: str
    is_primary: bool
    region: str
    replication_lag_ms: float = 0.0  # only relevant for replicas

    def execute_read(self, query: str) -> str:
        """Simulate a SELECT query."""
        return f"[{self.node_id}] result for: {query}"

    def execute_write(self, query: str) -> bool:
        """Simulate an INSERT/UPDATE/DELETE. Only valid on primary."""
        if not self.is_primary:
            raise PermissionError(f"Cannot write to replica {self.node_id}")
        return True


class ReplicationSetRouter:
    """
    Routes reads to replicas and writes to the primary.
    PRODUCTION: implemented by PgBouncer (read-write splitting),
                ProxySQL (MySQL), or RDS Proxy (AWS).
    STRATEGY: round-robin across healthy replicas for reads.
    """

    def __init__(self, primary: DatabaseNode, replicas: List[DatabaseNode]):
        self.primary = primary
        self.replicas = replicas
        self._replica_index = 0  # round-robin state

    def get_write_node(self) -> DatabaseNode:
        """All writes go to the single primary."""
        return self.primary  # never write to a replica

    def get_read_node(self, require_fresh: bool = False) -> DatabaseNode:
        """
        Route read to a replica for throughput; fall back to primary if fresh data required.
        require_fresh=True → read-your-writes scenarios (e.g., after creating an account).
        """
        if require_fresh or not self.replicas:
            return self.primary  # must be consistent → use primary

        # round-robin across replicas
        node = self.replicas[self._replica_index % len(self.replicas)]
        self._replica_index += 1
        return node


# =============================================================================
# SECTION 3: CONNECTION POOLING (PgBouncer)
# =============================================================================
# Each DB connection has overhead: ~5–10 MB RAM on PostgreSQL, TCP handshake,
# auth negotiation. An app server opening a new connection per request is fatal
# at scale (1000 concurrent requests = 1000 connections = 5–10 GB RAM on DB).
#
# CONNECTION POOLER: maintains a small pool of long-lived DB connections and
# lends them to application requests for the duration of a query.
#
# PgBouncer MODES:
#   session    → one DB connection per client session (least efficient)
#   transaction → connection returned to pool after each transaction (most common)
#   statement  → connection returned after each statement (aggressive; breaks multi-stmt txns)
#
# PRODUCTION: PgBouncer between app servers and PostgreSQL. Pool size = 10–50
# connections per DB CPU core is a good starting point.

class ConnectionPool:
    """
    Simulates a simple connection pool (modelled after PgBouncer transaction mode).
    In production use: psycopg2's ThreadedConnectionPool, SQLAlchemy's QueuePool,
    or PgBouncer as a dedicated process.
    """

    def __init__(self, max_connections: int, dsn: str):
        self.max_connections = max_connections
        self.dsn = dsn
        self._available: List[str] = [  # simulated connection objects
            f"conn_{i}" for i in range(max_connections)
        ]
        self._in_use: List[str] = []
        self._waiters = 0  # requests waiting for a connection

    def acquire(self) -> Optional[str]:
        """
        Borrow a connection from the pool.
        Returns None if pool is exhausted (caller should retry or fail fast).
        PRODUCTION: set a wait_timeout; fail with 503 rather than queue indefinitely.
        """
        if self._available:
            conn = self._available.pop()   # take from pool
            self._in_use.append(conn)
            logger.debug(f"Acquired {conn}. Pool: {len(self._available)} free")
            return conn
        else:
            self._waiters += 1
            logger.warning(f"Pool exhausted! {self._waiters} request(s) waiting.")
            return None  # pool exhausted — caller must handle

    def release(self, conn: str):
        """Return a connection to the pool after query completes."""
        if conn in self._in_use:
            self._in_use.remove(conn)
            self._available.append(conn)  # make available for next request
            logger.debug(f"Released {conn}. Pool: {len(self._available)} free")


# =============================================================================
# SECTION 4: SHARDING STRATEGIES
# =============================================================================
# Sharding = horizontal partitioning of data across multiple DB instances.
# Each shard holds a subset of the total data; queries are routed to the
# correct shard based on a shard key.
#
# WHY SHARD?
#   When a single DB (+ replicas) cannot handle write throughput or data volume.
#   Writes cannot be offloaded to replicas — only the primary handles writes.
#
# WHEN NOT TO SHARD (premature sharding):
#   - Before optimising queries and adding indexes
#   - Before adding read replicas
#   - Before vertical scaling
#   Sharding adds enormous complexity. Only shard when the above options are exhausted.

class RangeSharding:
    """
    RANGE SHARDING: data is divided into consecutive ranges of the shard key.
    EXAMPLE: users 1–1M on shard-0, 1M–2M on shard-1, etc.
    PROS: range queries are efficient (all data for a range is on one shard).
    CONS: hot shard problem — new/active users cluster at the high end of the range,
          causing the last shard to receive disproportionately more writes.
    USED FOR: time-series data (by date range), archival by year/month.
    """

    def __init__(self, shard_ranges: List[Tuple[int, int, str]]):
        # each tuple: (range_start, range_end_exclusive, shard_id)
        self.shard_ranges = sorted(shard_ranges, key=lambda x: x[0])

    def get_shard(self, key_value: int) -> Optional[str]:
        for start, end, shard_id in self.shard_ranges:
            if start <= key_value < end:
                return shard_id
        return None  # key is out of all defined ranges


class HashSharding:
    """
    HASH SHARDING: shard = hash(key) % num_shards.
    PROS: even data distribution; eliminates hot shards caused by sequential keys.
    CONS: range queries require querying ALL shards (scatter-gather).
          Re-sharding (changing num_shards) invalidates all existing assignments
          and requires expensive data migration.
    USED FOR: user data, product data — random access patterns dominate.
    """

    def __init__(self, num_shards: int):
        self.num_shards = num_shards

    def get_shard(self, key: str) -> int:
        """Map any string key to a shard index deterministically."""
        hash_val = int(hashlib.md5(key.encode()).hexdigest(), 16)
        return hash_val % self.num_shards  # simple but inflexible to re-sharding


class DirectoryBasedSharding:
    """
    DIRECTORY SHARDING: a lookup table (the directory) maps each key to its shard.
    PROS: flexible — any key can be moved to any shard without formula changes;
          supports non-uniform distribution (put large tenants on dedicated shards).
    CONS: the directory becomes a bottleneck and SPOF; must be highly available.
    USED FOR: multi-tenant SaaS (each customer can be on a dedicated shard),
              sharding by geography.
    PRODUCTION: shard directory stored in Redis or a dedicated metadata service.
    """

    def __init__(self):
        self._directory: Dict[str, str] = {}  # key → shard_id mapping

    def assign(self, key: str, shard_id: str):
        """Explicitly assign a key to a shard."""
        self._directory[key] = shard_id

    def get_shard(self, key: str) -> Optional[str]:
        return self._directory.get(key)  # O(1) lookup

    def migrate(self, key: str, new_shard_id: str):
        """Move a key to a different shard (after data is physically moved)."""
        self._directory[key] = new_shard_id  # update directory after migration


# =============================================================================
# SECTION 5: CONSISTENT HASHING
# =============================================================================
# PROBLEM with simple hash sharding: adding or removing a shard causes almost
# ALL keys to remap (hash(key) % N changes for most keys when N changes).
# This means massive data migration on every cluster resize.
#
# CONSISTENT HASHING: places shards and keys on a virtual ring (0 to 2^32).
# When a shard is added/removed, only the keys on the ring segment adjacent to
# that shard need to move — all others remain on the same shard.
#
# VIRTUAL NODES: each physical shard is represented by V virtual nodes on the ring.
# This improves load distribution and reduces the hot-shard problem.
# PRODUCTION: used by Cassandra, DynamoDB, Riak, Redis Cluster.

class ConsistentHashRing:
    """
    Consistent hash ring with virtual nodes for even load distribution.
    VIRTUAL NODES: each real node gets `replicas` positions on the ring.
    More virtual nodes → better distribution but higher memory for the ring.
    PRODUCTION PARAMETER: 150–200 virtual nodes per physical node is typical.
    """

    def __init__(self, replicas: int = 150):
        self.replicas = replicas          # virtual nodes per physical shard
        self._ring: Dict[int, str] = {}   # hash position → shard_id
        self._sorted_keys: List[int] = [] # sorted list of positions for bisect

    def add_shard(self, shard_id: str):
        """
        Add a shard to the ring by placing `replicas` virtual nodes.
        After adding, only the keys between the new vnode and its predecessor
        need to move from their current shard to the new shard.
        """
        for i in range(self.replicas):
            # each virtual node has a unique hash based on shard_id + replica index
            vnode_key = f"{shard_id}:{i}"
            position = int(hashlib.md5(vnode_key.encode()).hexdigest(), 16)
            self._ring[position] = shard_id
            bisect.insort(self._sorted_keys, position)  # maintain sorted order

    def remove_shard(self, shard_id: str):
        """Remove a shard and all its virtual nodes from the ring."""
        for i in range(self.replicas):
            vnode_key = f"{shard_id}:{i}"
            position = int(hashlib.md5(vnode_key.encode()).hexdigest(), 16)
            del self._ring[position]
            self._sorted_keys.remove(position)

    def get_shard(self, key: str) -> Optional[str]:
        """
        Find the shard responsible for a given key.
        Walk clockwise from the key's position until the first virtual node.
        """
        if not self._ring:
            return None
        position = int(hashlib.md5(key.encode()).hexdigest(), 16)
        # bisect_right finds insertion point → next virtual node clockwise
        idx = bisect.bisect_right(self._sorted_keys, position)
        if idx == len(self._sorted_keys):
            idx = 0  # wrap around the ring
        return self._ring[self._sorted_keys[idx]]


# =============================================================================
# SECTION 6: HOT SHARD PROBLEM AND MITIGATIONS
# =============================================================================
# HOT SHARD: one shard receives disproportionately more reads/writes than others.
# CAUSES:
#   - Bad shard key (e.g., celebrity user has millions of followers → all writes to one shard)
#   - Range sharding with monotonically increasing keys (recent data is always on last shard)
#   - Viral content causing read hot-spots
#
# MITIGATIONS:
#   1. Add random suffix to shard key: key = f"{user_id}_{random.randint(0, 99)}"
#      → spreads writes across 100 sub-shards; reads must aggregate across them.
#   2. Move hot keys to a dedicated shard (directory-based sharding).
#   3. Cache hot items at application layer (Redis) to absorb read load.
#   4. Background job detects hot shards and triggers automatic shard splitting.

def shard_key_with_suffix(base_key: str, num_suffixes: int = 100) -> str:
    """
    Append a random suffix to spread writes for a hot key across sub-shards.
    WRITE: write to a random sub-shard (key_42, key_17, key_83, ...).
    READ:  must read from ALL sub-shards and aggregate — this is the trade-off.
    USE CASE: global counters (view counts, likes) — use Redis INCR instead.
    """
    suffix = random.randint(0, num_suffixes - 1)
    return f"{base_key}_{suffix}"  # e.g., "user:celeb_42"


# =============================================================================
# SECTION 7: QUERY OPTIMIZATION — EXPLAIN ANALYZE AND COVERING INDEXES
# =============================================================================
# EXPLAIN ANALYZE (PostgreSQL): executes the query and shows the actual execution plan.
# Reveals: Sequential Scan (bad at scale) vs Index Scan (good) vs Index-Only Scan (best).
#
# COVERING INDEX: an index that includes all columns needed by a query.
# This enables an "Index-Only Scan" — the DB never touches the heap (table data).
# EXAMPLE: if your query is SELECT email FROM users WHERE status = 'active',
#          a covering index on (status, email) satisfies it without reading the table.
#
# COMPOSITE INDEX KEY ORDER: place the most selective column first.
#   (status, created_at) → good if you filter on status frequently.
#   (created_at, status) → only useful if created_at is always in the WHERE clause.

QUERY_EXAMPLES = {
    "seq_scan_bad": """
        -- EXPLAIN shows: Seq Scan on orders (cost=0.00..15432.00 rows=500000)
        -- Reads every row in the table. Fatal for large tables.
        SELECT * FROM orders WHERE customer_id = 42;
    """,

    "index_scan_good": """
        -- After: CREATE INDEX idx_orders_customer ON orders(customer_id);
        -- EXPLAIN shows: Index Scan using idx_orders_customer (cost=0.43..8.46 rows=3)
        SELECT * FROM orders WHERE customer_id = 42;
    """,

    "covering_index_best": """
        -- CREATE INDEX idx_users_status_email ON users(status, email);
        -- EXPLAIN shows: Index Only Scan (never reads table heap)
        -- Best possible: zero table I/O.
        SELECT email FROM users WHERE status = 'active';
    """,

    "explain_analyze_template": """
        EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
        SELECT o.id, o.total, c.email
        FROM orders o
        JOIN customers c ON c.id = o.customer_id
        WHERE o.created_at > NOW() - INTERVAL '7 days'
          AND o.status = 'pending';
        -- Look for: "Seq Scan" → needs an index.
        -- Look for: "Hash Join" vs "Nested Loop" — NL is faster for small result sets.
        -- Look for: "Buffers: hit=X read=Y" — high Y means lots of disk I/O.
    """,
}


# =============================================================================
# SECTION 8: DATABASE FEDERATION AND POLYGLOT PERSISTENCE
# =============================================================================
# DATABASE FEDERATION: split a monolithic database by domain/function.
# EXAMPLE: users DB, orders DB, inventory DB are separate PostgreSQL instances.
# PROS: each domain scales independently; teams own their own data store.
# CONS: cross-domain joins are impossible; cross-domain transactions require sagas.
#
# POLYGLOT PERSISTENCE: different data types use the best-fit database technology.
# EXAMPLE STACK:
#   PostgreSQL  → transactional records (orders, payments, users)
#   Redis       → sessions, leaderboards, rate limit counters, pub/sub
#   Elasticsearch → full-text search (product catalog, log search)
#   Cassandra   → time-series writes (activity feeds, IoT sensor data)
#   Neo4j       → graph queries (social connections, fraud detection)
#   S3          → blob storage (images, videos, document files)

POLYGLOT_GUIDE: Dict[str, Dict[str, str]] = {
    "PostgreSQL": {
        "use_for":   "Transactional data, complex joins, ACID guarantees",
        "CAP":       "CP (Consistency + Partition Tolerance)",
        "avoid_for": "High write throughput > 100K/s, simple key-value lookups",
    },
    "Redis": {
        "use_for":   "Sessions, caching, pub/sub, sorted sets for leaderboards",
        "CAP":       "AP (Availability + Partition Tolerance) in cluster mode",
        "avoid_for": "Primary persistence (unless using RDB+AOF carefully)",
    },
    "Cassandra": {
        "use_for":   "High write throughput, time-series, append-only workloads",
        "CAP":       "AP (tunable consistency per query)",
        "avoid_for": "Ad-hoc queries, frequent updates, strong consistency requirements",
    },
    "MongoDB": {
        "use_for":   "Flexible schema documents, nested objects, prototyping",
        "CAP":       "CP (with replica set, primary failure blocks writes briefly)",
        "avoid_for": "Complex multi-document transactions at scale",
    },
    "Elasticsearch": {
        "use_for":   "Full-text search, log analytics, faceted search",
        "CAP":       "AP (availability prioritised; may return slightly stale results)",
        "avoid_for": "Primary transactional store; primary source of truth",
    },
    "Neo4j": {
        "use_for":   "Highly connected data: social graphs, recommendation engines",
        "CAP":       "CA (single-instance; cluster adds partition tolerance)",
        "avoid_for": "Simple key-value or relational workloads",
    },
}


# =============================================================================
# SECTION 9: CAP THEOREM APPLIED TO REAL DATABASES
# =============================================================================
# CAP THEOREM (Brewer, 2000): in a network partition, a distributed system must
# choose between Consistency and Availability.
#   Consistency  → every read receives the most recent write or an error.
#   Availability → every request receives a non-error response (may be stale).
#   Partition T. → the system continues operating despite network partitions.
#                  This is a reality in distributed systems — you cannot opt out.
# Therefore: during a partition, choose C or A (not both).
#
# NOTE: "Consistency" in CAP is NOT the same as ACID "Consistency".
#   CAP C  → linearisability / all nodes see the same data at the same time.
#   ACID C → a transaction leaves the DB in a valid state per its invariants.

CAP_REAL_WORLD = {
    # CP systems: sacrifice availability during partition (return error rather than stale data)
    "PostgreSQL (single primary)":   "CP — strong consistency; primary failure blocks writes",
    "HBase":                         "CP — region master ensures consistent reads",
    "ZooKeeper":                     "CP — majority quorum required; minority partitions reject writes",
    "MongoDB (w: majority)":         "CP — majority write/read concern provides linearisability",

    # AP systems: sacrifice consistency during partition (return stale data rather than error)
    "Cassandra":     "AP — tunable consistency; eventual consistency by default",
    "CouchDB":       "AP — multi-master replication; conflicts resolved later",
    "DynamoDB":      "AP — eventually consistent reads by default (strongly consistent optional)",
    "Riak":          "AP — availability-first; uses vector clocks for conflict resolution",

    # CA systems: only possible without partitions (single-node or same-DC sync replication)
    "SQLite":        "CA — single file, no network → CAP not applicable",
    "MySQL (sync replication)": "CA — sync replication in same DC; fails under partition",
}

# PACELC (extension to CAP): even without a partition, latency vs consistency trade-off exists.
# Cassandra: PA/EL → partition: Available; else: favours Low latency over Consistency.
# PostgreSQL: PC/EC → partition: Consistent; else: favours Consistency over Low latency.


# =============================================================================
# SECTION 10: CQRS — COMMAND QUERY RESPONSIBILITY SEGREGATION
# =============================================================================
# CQRS: use a separate model (and often separate data store) for reads vs writes.
# WRITE SIDE (Command): handles inserts, updates, deletes. Optimised for consistency.
# READ SIDE (Query):    handles selects. Optimised for query performance.
#
# WHY:
#   - Read and write workloads often have different shapes and scale needs.
#   - Write model can be normalised (OLTP); read model can be denormalised (OLAP/search).
#   - Read replicas can serve the query side independently.
#
# TRADE-OFF: eventual consistency between write and read models.
#            A write on the command side propagates to the read side asynchronously.
# USED IN: e-commerce (write: order DB; read: Elasticsearch product index),
#           banking dashboards, social media timelines.

class OrderCommandHandler:
    """Write side: processes commands that mutate state."""

    def __init__(self, event_bus: List[Dict]):
        self._event_bus = event_bus  # list simulating Kafka/RabbitMQ

    def place_order(self, order_id: str, user_id: str, total: float):
        """Command: PlaceOrder → validates, persists, emits event."""
        # In production: write to transactional DB (PostgreSQL)
        logger.info(f"Order {order_id} placed by user {user_id} for ${total:.2f}")
        # Emit domain event for the read-side projector to consume
        self._event_bus.append({
            "event":    "OrderPlaced",
            "order_id": order_id,
            "user_id":  user_id,
            "total":    total,
            "timestamp": time.time(),
        })

    def cancel_order(self, order_id: str, reason: str):
        logger.info(f"Order {order_id} cancelled: {reason}")
        self._event_bus.append({
            "event":    "OrderCancelled",
            "order_id": order_id,
            "reason":   reason,
            "timestamp": time.time(),
        })


class OrderQueryService:
    """Read side: serves queries from a pre-built, denormalised read model."""

    def __init__(self):
        # In production: Elasticsearch index, Redis hash, or read-only PostgreSQL replica
        self._read_model: Dict[str, Dict] = {}

    def apply_event(self, event: Dict):
        """Projector: update read model based on domain events from write side."""
        if event["event"] == "OrderPlaced":
            # denormalise into a flat read-optimised structure
            self._read_model[event["order_id"]] = {
                "order_id": event["order_id"],
                "user_id":  event["user_id"],
                "total":    event["total"],
                "status":   "placed",
            }
        elif event["event"] == "OrderCancelled":
            if event["order_id"] in self._read_model:
                self._read_model[event["order_id"]]["status"] = "cancelled"

    def get_order(self, order_id: str) -> Optional[Dict]:
        """Query: no joins, no complex SQL — just a fast key lookup."""
        return self._read_model.get(order_id)

    def get_orders_for_user(self, user_id: str) -> List[Dict]:
        """Query: filter read model; in production this is an Elasticsearch query."""
        return [o for o in self._read_model.values() if o["user_id"] == user_id]


# =============================================================================
# SECTION 11: EVENT SOURCING
# =============================================================================
# EVENT SOURCING: never store current state. Store only the sequence of events
# that led to it. Current state is derived by replaying events.
#
# PROS:
#   - Complete audit log with zero extra effort.
#   - Time travel: replay to any point in history.
#   - Easy to add new projections (new read models) by replaying event history.
# CONS:
#   - Current state requires event replay (mitigated by snapshots).
#   - Schema evolution is hard — old events may not match new schemas.
#   - Overkill for simple CRUD applications.
# USED FOR: bank ledgers, e-commerce order lifecycle, collaborative document editing.

@dataclass
class Event:
    event_type: str
    aggregate_id: str
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    version: int = 0  # monotonically increasing per aggregate


class EventSourcedBankAccount:
    """
    Bank account implemented with event sourcing.
    State is NOT stored directly — only events are stored.
    Balance is computed by replaying all events for this account.
    """

    def __init__(self, account_id: str):
        self.account_id = account_id
        self._events: List[Event] = []  # the event store (append-only)

    def deposit(self, amount: float):
        """Append a Deposited event. Do NOT mutate stored balance directly."""
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        self._append_event("Deposited", {"amount": amount})

    def withdraw(self, amount: float):
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        if self.balance < amount:
            raise ValueError("Insufficient funds")  # checked against projected balance
        self._append_event("Withdrawn", {"amount": amount})

    def _append_event(self, event_type: str, payload: Dict):
        version = len(self._events)  # version = number of events so far
        event = Event(
            event_type=event_type,
            aggregate_id=self.account_id,
            payload=payload,
            version=version,
        )
        self._events.append(event)   # append-only — never modify or delete events

    @property
    def balance(self) -> float:
        """Compute current balance by replaying all events (projection)."""
        balance = 0.0
        for event in self._events:
            if event.event_type == "Deposited":
                balance += event.payload["amount"]
            elif event.event_type == "Withdrawn":
                balance -= event.payload["amount"]
        return balance

    def get_history(self) -> List[Event]:
        """Return full audit trail — one of the key benefits of event sourcing."""
        return list(self._events)

    def snapshot(self) -> Dict:
        """
        Snapshot captures current state so future replays start from here.
        PRODUCTION: store snapshot every N events; replay only events after snapshot.
        """
        return {"account_id": self.account_id, "balance": self.balance,
                "event_count": len(self._events)}


# =============================================================================
# SECTION 12: NoSQL vs SQL — DECISION FRAMEWORK
# =============================================================================

def should_use_nosql(
    need_flexible_schema: bool,
    need_horizontal_write_scale: bool,
    need_complex_joins: bool,
    need_acid_transactions: bool,
    data_is_graph_like: bool,
    data_is_time_series: bool,
) -> str:
    """
    Simple decision tree for SQL vs NoSQL selection.
    In practice this decision involves many more factors; treat as a starting point.
    """
    if need_acid_transactions and need_complex_joins:
        return "Use PostgreSQL / MySQL — relational DB is the clear choice"

    if data_is_graph_like:
        return "Use Neo4j or Amazon Neptune — graph traversals are O(edges) not O(rows)"

    if data_is_time_series:
        return "Use InfluxDB or TimescaleDB — time-series optimised storage and queries"

    if need_horizontal_write_scale and not need_acid_transactions:
        return "Use Cassandra or DynamoDB — wide-column, AP, designed for write scale"

    if need_flexible_schema and not need_complex_joins:
        return "Consider MongoDB or DynamoDB — document model fits schema flexibility"

    return "Default to PostgreSQL — battle-tested, flexible, strong ecosystem"


# =============================================================================
# SECTION 13: DEMO
# =============================================================================

def demo():
    print("\n" + "="*60)
    print("CONSISTENT HASHING DEMO")
    print("="*60)

    ring = ConsistentHashRing(replicas=100)
    for shard in ["shard-0", "shard-1", "shard-2"]:
        ring.add_shard(shard)

    keys = ["user:alice", "user:bob", "user:charlie", "user:dave"]
    print("\nInitial placement (3 shards):")
    for k in keys:
        print(f"  {k} → {ring.get_shard(k)}")

    ring.add_shard("shard-3")  # simulate adding a new shard
    print("\nAfter adding shard-3 (only ~25% of keys should move):")
    for k in keys:
        print(f"  {k} → {ring.get_shard(k)}")

    print("\n" + "="*60)
    print("CQRS + EVENT SOURCING DEMO")
    print("="*60)

    event_bus: List[Dict] = []
    cmd = OrderCommandHandler(event_bus)
    qry = OrderQueryService()

    cmd.place_order("ord-001", "user-42", 149.99)
    cmd.place_order("ord-002", "user-42", 29.99)
    cmd.cancel_order("ord-001", "Customer changed mind")

    # Projector applies events from bus to read model
    for event in event_bus:
        qry.apply_event(event)

    print(f"\nOrder ord-002: {qry.get_order('ord-002')}")
    print(f"Order ord-001 (cancelled): {qry.get_order('ord-001')}")
    print(f"All orders for user-42: {qry.get_orders_for_user('user-42')}")

    print("\n" + "="*60)
    print("EVENT SOURCING — BANK ACCOUNT DEMO")
    print("="*60)

    acct = EventSourcedBankAccount("acc-999")
    acct.deposit(1000.00)
    acct.deposit(500.00)
    acct.withdraw(200.00)
    print(f"\nBalance after deposit(1000) + deposit(500) + withdraw(200): ${acct.balance:.2f}")
    print(f"Event log: {[e.event_type for e in acct.get_history()]}")
    print(f"Snapshot: {acct.snapshot()}")

    print("\n" + "="*60)
    print("CONNECTION POOL DEMO")
    print("="*60)

    pool = ConnectionPool(max_connections=3, dsn="postgresql://localhost/mydb")
    conns = [pool.acquire() for _ in range(4)]  # 4th should warn
    print(f"Connections acquired: {conns}")
    pool.release(conns[0])  # return first connection to pool
    print(f"After release, can acquire: {pool.acquire()}")

    print("\nDemo complete.")


if __name__ == "__main__":
    demo()
