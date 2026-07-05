# ============================================================
# L08: ScyllaDB and Online Feature Serving — The Redis+Scylla Hybrid
# ============================================================
# WHAT: Wide-column store fundamentals (ScyllaDB, a Cassandra-compatible
#       database), and the specific hybrid pattern of splitting online
#       feature serving across Redis (hot, low-latency) and ScyllaDB
#       (bulk, high-throughput) to separate latency SLOs from raw
#       storage/throughput needs.
# WHY: L01 established that online serving (Tier 3) needs millisecond
#      latency. At SMALL scale, Redis alone is enough. At LARGE scale —
#      many millions of entities, each with many features, high write
#      throughput from continuous materialization — a single Redis
#      instance's memory-bound nature becomes a real constraint, which is
#      exactly the gap ScyllaDB (disk-backed, horizontally scalable) fills.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
REDIS is an IN-MEMORY data store — extremely fast (sub-millisecond
typical latency) because there's no disk I/O on the read path, but
BOUNDED BY AVAILABLE RAM — storing billions of feature values for
millions of entities in Redis alone becomes very expensive (RAM is far
costlier per GB than disk) well before it becomes technically infeasible.

SCYLLADB is a WIDE-COLUMN store, API-compatible with Apache Cassandra
but re-implemented in C++ for significantly higher throughput per node
(avoiding Java's garbage-collection pauses that can affect Cassandra's
tail latencies). It's DISK-BACKED (with aggressive caching), and
horizontally scales by adding nodes to a ring — each node owns a
partition of the total key space (via consistent hashing on the
PARTITION KEY), and data is REPLICATED across multiple nodes for fault
tolerance. This makes ScyllaDB well-suited to storing a MUCH larger total
volume of feature data than fits economically in RAM, at somewhat higher
(but still low, typically single-digit-millisecond) latency than pure
in-memory Redis.

THE HYBRID PATTERN: rather than choosing ONE of these, many production
feature platforms use BOTH, splitting by ACCESS PATTERN — a small,
FREQUENTLY-ACCESSED "hot" subset of features/entities (e.g. features for
currently-active users in the last hour) lives in Redis for the fastest
possible lookup latency, while the FULL, BULK feature dataset (covering
all entities, including rarely-accessed ones) lives in ScyllaDB, sized
for total volume and throughput rather than absolute minimum latency.
This explicitly separates two different requirements that a single store
optimized for only one of them would struggle to satisfy simultaneously:
LATENCY SLOs (how fast must the fastest, most common lookups be) vs
THROUGHPUT/VOLUME (how much total data, and how many total
writes/second, must the system sustain).

Data modeling in ScyllaDB (as in Cassandra) is fundamentally
QUERY-DRIVEN, not normalized — you design your table's PARTITION KEY
based on how you'll actually QUERY it (e.g. partition by `entity_id` so
a single-entity feature lookup hits exactly one partition, one node, in
one request), rather than a normalized relational schema you'd then
query flexibly — this is a real modeling-mindset shift from relational
database design.

PRODUCTION USE CASE:
A feature platform serving real-time predictions for an e-commerce
recommendation system keeps the last-hour's ACTIVE shoppers' features in
Redis (a small, frequently-refreshed working set, millisecond lookups
critical for a live browsing session), while the FULL customer base's
features (including customers who haven't shopped in months, needed for
occasional batch scoring or re-engagement campaigns) live in ScyllaDB —
sized for total volume across the entire customer base, at a
still-acceptable single-digit-millisecond latency for the less
latency-critical batch/occasional-access use case.

COMMON MISTAKES:
- Defaulting to Redis for EVERYTHING because it's simpler to operate,
  then hitting a real memory-cost or capacity wall as the feature
  platform's entity count and feature count both grow — evaluating the
  hybrid split BEFORE hitting that wall (based on projected scale) avoids
  a disruptive later migration.
- Designing ScyllaDB tables with a relational, normalized mindset
  (multiple small, joinable tables) instead of a query-driven,
  partition-key-first design — ScyllaDB has NO real JOIN support; a
  schema requiring joins at read time to answer a common query pattern
  is a modeling mistake, not a query-optimization problem to solve later.
- Choosing an overly high-cardinality or overly low-cardinality
  partition key — too high cardinality (e.g. a unique key per single
  event) can create excessive numbers of tiny partitions; too low
  cardinality (e.g. partitioning by a coarse category) can create HOT
  PARTITIONS where one node handles disproportionate traffic, undermining
  the horizontal scaling ScyllaDB is meant to provide.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Redis vs ScyllaDB — the core tradeoff
# ------------------------------------------------------------------
STORE_TRADEOFF_COMPARISON = {
    "Redis (in-memory)": {
        "latency": "Sub-millisecond typical",
        "capacity_constraint": "Bounded by available RAM — expensive at "
                                "very large total data volume",
        "best_for": "A relatively SMALL, frequently-accessed 'hot' subset "
                     "of features where absolute minimum latency matters most",
    },
    "ScyllaDB (disk-backed, wide-column)": {
        "latency": "Low single-digit milliseconds typical",
        "capacity_constraint": "Scales horizontally by adding nodes — "
                                "economical at very large total data volume",
        "best_for": "The FULL, bulk feature dataset across all entities, "
                     "where total volume/throughput matters more than "
                     "shaving the last millisecond off latency",
    },
}


def print_tradeoff_comparison():
    for store, props in STORE_TRADEOFF_COMPARISON.items():
        print(f"{store}:")
        for k, v in props.items():
            print(f"  {k}: {v}")
        print()


# ------------------------------------------------------------------
# 2. ScyllaDB data modeling — query-driven, partition-key-first
# ------------------------------------------------------------------
CQL_TABLE_DESIGN_EXAMPLE = textwrap.dedent("""\
    -- CQL (Cassandra Query Language, which ScyllaDB implements)
    -- Partition key: entity_id — a single-entity feature lookup hits
    -- EXACTLY ONE partition (and therefore, typically, one node),
    -- making it a fast, targeted operation rather than a scatter-gather
    -- across the whole cluster.
    CREATE TABLE feature_store.online_features (
        entity_id text,
        feature_name text,
        feature_value double,
        updated_at timestamp,
        PRIMARY KEY (entity_id, feature_name)
        -- entity_id = PARTITION KEY (determines which node owns this data)
        -- feature_name = CLUSTERING KEY (sorts/organizes rows WITHIN a partition)
    );

    -- A lookup for ALL features of one entity — hits one partition,
    -- returns all clustered rows within it, a cheap, targeted query:
    SELECT feature_name, feature_value
    FROM feature_store.online_features
    WHERE entity_id = 'cust_12345';

    -- Contrast with a RELATIONAL mindset mistake: designing this as
    -- multiple normalized tables requiring a JOIN at read time —
    -- ScyllaDB has no real join support, so this query pattern would
    -- require either denormalization (as shown above) or expensive
    -- application-level multi-query stitching.
""")

# ------------------------------------------------------------------
# 3. Hot partition avoidance — choosing partition key cardinality well
# ------------------------------------------------------------------
PARTITION_KEY_GUIDANCE = textwrap.dedent("""\
    -- GOOD: entity_id as partition key — naturally high cardinality
    -- (millions of distinct customers), spreading load evenly across
    -- the cluster's nodes via consistent hashing.

    -- BAD: partitioning by a coarse, low-cardinality value like
    -- "region" (only a handful of distinct values) — this concentrates
    -- ALL of one region's traffic onto whichever few nodes own that
    -- partition, creating a HOT PARTITION that undermines horizontal
    -- scaling; the whole point of adding more nodes is defeated if one
    -- node still bears disproportionate load.
    CREATE TABLE feature_store.bad_design (
        region text,          -- BAD partition key choice — low cardinality
        entity_id text,
        feature_value double,
        PRIMARY KEY (region, entity_id)
    );
""")

# ------------------------------------------------------------------
# 4. The hybrid serving layer, illustrated
# ------------------------------------------------------------------
HYBRID_LOOKUP_EXAMPLE = textwrap.dedent("""\
    def get_online_features(entity_id: str, feature_names: list[str]) -> dict:
        # Check the "hot" Redis cache first — a small, frequently-
        # refreshed working set of recently-active entities.
        cached = redis_client.hgetall(f"features:{entity_id}")
        if cached and all(f in cached for f in feature_names):
            return {f: cached[f] for f in feature_names}   # fast path

        # Cache miss (entity not in the 'hot' working set) — fall back
        # to the bulk ScyllaDB store, which covers EVERY entity, at
        # slightly higher but still acceptable latency.
        rows = scylla_session.execute(
            "SELECT feature_name, feature_value FROM online_features "
            "WHERE entity_id = %s AND feature_name IN %s",
            (entity_id, tuple(feature_names)),
        )
        result = {row.feature_name: row.feature_value for row in rows}

        # Optionally, promote this entity into the hot Redis cache,
        # since a cache miss suggests it may become an active session.
        redis_client.hset(f"features:{entity_id}", mapping=result)
        return result
""")


if __name__ == "__main__":
    print_tradeoff_comparison()
    print(CQL_TABLE_DESIGN_EXAMPLE)
    print(PARTITION_KEY_GUIDANCE)
    print(HYBRID_LOOKUP_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A feature platform originally served ALL online features from a single
large Redis cluster, but as the entity count grew into the tens of
millions (most of them inactive at any given moment), the team split
serving into a hybrid: an "active session" Redis cache (population
capped, sized for actual concurrent active users) backed by a full
ScyllaDB store covering every entity — reducing Redis memory footprint
(and cost) by over 90% while keeping the actually latency-critical path
(active user sessions) just as fast as before, since those entities
remain served from the hot Redis tier.
"""
