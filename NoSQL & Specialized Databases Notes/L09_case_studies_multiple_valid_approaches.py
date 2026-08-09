"""
WHAT: Four realistic data-storage problems, each solved with THREE
      genuinely different, individually defensible NoSQL (or NoSQL-vs-SQL)
      choices drawn from L01-L08 -- with an explicit comparison table and
      reasoning for why each answer is valid under different constraints.
      Distinct from L08's capstone (one specific 7-database architecture
      walkthrough) -- this lesson is about the DECISION process across
      competing options for a single problem, not one worked build.
WHY:  "Which database should I use" is the central question this whole
      domain exists to teach you NOT to answer with a single favorite --
      L06 already gave you a decision framework; this lesson applies it
      to four concrete scenarios where the "obvious" choice and the
      objectively-correct choice can differ.
LEVEL: Capstone -- read after L01-L08.

This file, like this repo's other case-study capstones, is reference
material, not meant to run top-to-bottom. Before checking each comparison
table, try reconstructing it yourself using only L01-L08's concepts.
"""

# ============================================================================
# CASE STUDY 1 — STORING A SOCIAL NETWORK'S "PEOPLE YOU MAY KNOW" GRAPH
# ============================================================================
#
# SETUP: a social app needs to compute "friends of friends who aren't
# already your friend" for a recommendation feature, across ~50M users
# with an average of ~200 connections each.
#
# ------------------------------------------------------------------------
# APPROACH A: Model connections as rows in a relational (SQL) table --
# `connections(user_id, friend_id)` -- and compute via SQL self-joins
# ------------------------------------------------------------------------
#   WHY VALID: for a SHALLOW query (direct friends, or even one hop of
#   "friends of friends" via a single self-join), a well-indexed
#   relational table performs perfectly well, and keeps this data in the
#   SAME system as the rest of a typical social app's relational data
#   (user profiles, posts) -- avoiding a separate database's operational
#   overhead when the query need doesn't yet justify it.
#   COST: per L04's graph-vs-SQL discussion, EACH additional hop
#   ("friends of friends of friends") requires ANOTHER self-join --
#   these compound expensively, and at 50M users x 200 connections each
#   (10 billion edges), even a 2-hop join becomes a genuinely heavy
#   relational operation; multi-hop traversal is exactly the query
#   pattern relational self-joins scale worst at.
#
# ------------------------------------------------------------------------
# APPROACH B: A dedicated graph database (Neo4j, L04) modeling users as
# nodes and connections as edges, using Cypher's native traversal
# ------------------------------------------------------------------------
#   WHY VALID: per L04, graph databases store adjacency information
#   DIRECTLY (each node physically references its edges), making multi-
#   hop traversal a matter of following pointers rather than repeated
#   joins -- Cypher's `(:User)-[:FRIENDS_WITH*2]-(:User)` pattern
#   expresses "2 hops" directly and executes efficiently regardless of
#   how many hops are needed, exactly the query pattern this case study
#   needs and exactly what graph databases are purpose-built for.
#   COST: introduces a SEPARATE database system to operate, monitor, and
#   keep in sync with the primary user-data store (a real operational
#   and consistency-management cost, per L07's polyglot-persistence
#   discussion) -- and most of the REST of a typical social app's data
#   (posts, comments, profile fields) doesn't benefit from a graph
#   model at all, meaning this is a targeted addition, not a wholesale
#   replacement of the primary datastore.
#
# ------------------------------------------------------------------------
# APPROACH C: Precompute and cache "people you may know" results
# periodically (a batch job) into a fast key-value store (Redis, or
# DynamoDB, L03), read directly at request time with NO live traversal
# ------------------------------------------------------------------------
#   WHY VALID: sidesteps the live-query-cost problem entirely -- if
#   "who you may know" doesn't need to be perfectly real-time (a
#   reasonable assumption for most social apps; a brand-new connection
#   doesn't need to instantly ripple into everyone's recommendations),
#   computing it as an offline batch job (potentially still using a
#   graph engine or a big-data framework internally for the actual
#   traversal, Apache Spark Notes) and serving the RESULT from a simple,
#   extremely fast key-value lookup is often the best user-facing
#   latency of all three options.
#   COST: results are STALE between batch runs (the same eventually-
#   consistent tradeoff pattern seen in SQL Notes' capstone) -- and the
#   batch computation itself still needs to solve the underlying multi-
#   hop traversal problem somewhere (this doesn't eliminate that need,
#   it just moves WHEN and WHERE it happens, away from the live request
#   path).
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Multi-hop query cost | Live vs. batch | Operational overhead | Read latency |
#   |----------|---------------------------|--------------------|-----------------------------|-------------------|
#   | A: SQL self-joins | Poor beyond 1-2 hops | Live | Lowest (one system) | Medium-poor at scale |
#   | B: graph database | Good at any hop depth | Live | Higher (second system) | Good |
#   | C: precomputed + KV cache | N/A (solved offline) | Batch | Medium (batch pipeline) | Best |
#   Many production social apps actually combine B and C: a graph
#   database for the traversal logic, with results cached into a fast KV
#   store for the actual read path -- getting graph's traversal power
#   without paying its query latency on every single page load.


# ============================================================================
# CASE STUDY 2 — STORING SHOPPING CART STATE FOR AN E-COMMERCE SITE
# ============================================================================
#
# SETUP: cart state (items, quantities) needs sub-10ms reads/writes,
# survives brief service restarts, and doesn't need complex querying --
# just "get cart for user X" and "update cart for user X."
#
# ------------------------------------------------------------------------
# APPROACH A: DynamoDB (L03) with `user_id` as the partition key
# ------------------------------------------------------------------------
#   WHY VALID: per L03, DynamoDB's single-table, partition-key-based
#   design is EXACTLY suited to this access pattern -- a single, simple
#   key lookup, no complex querying needed, and DynamoDB's managed,
#   auto-scaling nature avoids needing to operate any infrastructure at
#   all, while providing durable, replicated storage that survives
#   service restarts by design.
#   COST: DynamoDB's pricing model (request-based, plus storage) means
#   cost scales with request VOLUME directly -- for an extremely
#   high-frequency access pattern (carts updated on every single item
#   interaction), this can become a real, direct line-item cost that a
#   flat-rate self-hosted alternative wouldn't incur in the same way.
#
# ------------------------------------------------------------------------
# APPROACH B: Redis (Redis & Caching Notes), with cart state as a Redis
# hash, `TTL`'d and periodically persisted
# ------------------------------------------------------------------------
#   WHY VALID: Redis's in-memory design gives the LOWEST possible read/
#   write latency of the three options (sub-millisecond, typically) --
#   for a cart, which is inherently ephemeral, semi-disposable state
#   (abandoned carts are normal and expected), Redis's optional
#   persistence (RDB/AOF) combined with a TTL (auto-expiring genuinely
#   abandoned carts) is a very natural fit.
#   COST: Redis persistence, even with AOF, has a narrower durability
#   guarantee than DynamoDB's fully-managed multi-AZ replication by
#   default -- a Redis instance failure between persistence checkpoints
#   CAN lose recent writes unless carefully configured (clustering,
#   replication) for stronger durability, a real operational
#   responsibility DynamoDB's managed service absorbs on your behalf.
#
# ------------------------------------------------------------------------
# APPROACH C: Cassandra (L02), with `user_id` as the partition key,
# cart items as a collection column
# ------------------------------------------------------------------------
#   WHY VALID: per L02, Cassandra's write-optimized architecture and
#   tunable consistency handle very high WRITE volume (frequent cart
#   updates) with strong horizontal scalability and NO single point of
#   failure (a genuinely decentralized, masterless cluster) -- a strong
#   choice if the team already operates Cassandra for other data and
#   wants to avoid adding a THIRD storage system (beyond a primary SQL
#   store and this cart store) to their operational surface.
#   COST: per L02's query-first schema design discussion, Cassandra is
#   the least "reach for it by default" of the three here for a workload
#   this SIMPLE (a single key lookup) -- its real strengths (massive
#   write throughput, multi-region active-active) are somewhat wasted on
#   a workload this straightforward, and it carries meaningfully more
#   operational complexity (cluster topology, consistency-level tuning)
#   than either A or B for a problem this size.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Latency | Durability (default config) | Operational overhead | Cost model |
#   |----------|-------------|----------------------------------|-----------------------------|----------------|
#   | A: DynamoDB | Good | Strong (managed, multi-AZ) | Lowest (fully managed) | Scales with request volume |
#   | B: Redis | Best | Weaker by default, tunable | Medium (self-managed unless using a managed Redis) | Flat instance cost |
#   | C: Cassandra | Good | Strong (tunable) | Highest (cluster ops) | Flat cluster cost |
#   For a team with NO existing NoSQL infrastructure, A (DynamoDB) is
#   usually the pragmatic default for exactly this access pattern; B is
#   compelling specifically when latency is the dominant requirement and
#   the team already runs Redis elsewhere; C is best justified by
#   existing Cassandra investment, not by this workload's own needs.


# ============================================================================
# CASE STUDY 3 — STORING SENSOR READINGS FROM 100,000 IoT DEVICES
# (10 READINGS/SECOND/DEVICE)
# ============================================================================
#
# SETUP: ~1M writes/second sustained, queries are almost always
# "readings for device X over time range Y," with downsampling/retention
# policies needed (raw data for 7 days, hourly rollups for 1 year).
#
# ------------------------------------------------------------------------
# APPROACH A: A purpose-built time-series database (L05) with native
# downsampling and retention-policy support
# ------------------------------------------------------------------------
#   WHY VALID: per L05, this is EXACTLY the workload time-series
#   databases are purpose-built for -- time-based partitioning matches
#   the query pattern (filter by device + time range) directly, and
#   built-in downsampling/retention-policy features handle the "raw for
#   7 days, hourly rollups for 1 year" requirement as FIRST-CLASS,
#   configured behavior rather than custom application logic.
#   COST: yet another specialized system in the stack (per L07's
#   polyglot-persistence operational-cost discussion), and if the team
#   has no prior time-series database experience, there's a genuine
#   learning curve for a tool category most engineers touch less often
#   than general-purpose relational/KV stores.
#
# ------------------------------------------------------------------------
# APPROACH B: Cassandra (L02) with a time-bucketed partition key (e.g.
# `device_id + date`), custom-written downsampling via a scheduled job
# ------------------------------------------------------------------------
#   WHY VALID: per L02, Cassandra's write-optimized architecture
#   comfortably handles 1M writes/second at the right cluster size, and
#   time-bucketed partition keys are a well-established Cassandra
#   pattern for exactly this kind of workload -- valid especially if the
#   team already operates Cassandra and wants to avoid a new specialized
#   system.
#   COST: downsampling/retention-policy logic that a time-series
#   database provides NATIVELY must be hand-built here (a scheduled job
#   reading raw data, computing rollups, writing to a separate table,
#   and expiring old raw data via TTL) -- genuine, ongoing custom code
#   to write, test, and maintain that a purpose-built tool would have
#   handled as configuration.
#
# ------------------------------------------------------------------------
# APPROACH C: Write raw readings to cheap object storage (e.g. as
# partitioned Parquet files) and query via a distributed SQL engine
# (Trino, Feature Stores & Modern Data Lake Notes) rather than any
# operational database at all
# ------------------------------------------------------------------------
#   WHY VALID: if queries are predominantly ANALYTICAL (aggregate
#   reporting, not "give me device X's LAST reading right now" for a
#   live dashboard), object storage is dramatically cheaper per byte
#   than any operational database, and a lakehouse-style architecture
#   (Feature Stores & Modern Data Lake Notes) avoids the write-heavy
#   operational database's ongoing infrastructure cost entirely for data
#   that's mostly written once and queried in aggregate later.
#   COST: object storage + a query engine is a poor fit for LOW-LATENCY,
#   POINT-LOOKUP access patterns (e.g. "show me this one device's most
#   recent reading, right now, for a live dashboard") -- query latency
#   for object-storage-backed analytical engines is typically seconds,
#   not milliseconds, disqualifying this approach for any part of the
#   workload that's genuinely latency-sensitive rather than analytical.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Write throughput fit | Downsampling/retention | Query latency | Cost at scale |
#   |----------|---------------------------|------------------------------|--------------------|--------------------|
#   | A: purpose-built TSDB | Excellent | Native/built-in | Fast | Medium |
#   | B: Cassandra + custom jobs | Excellent | Custom-built | Fast | Medium (cluster cost) |
#   | C: object storage + SQL engine | N/A (batch writes preferred) | Custom (batch jobs) | Slow (seconds) | Lowest per byte |
#   If ANY part of the workload needs live, low-latency point lookups
#   (a real-time device dashboard), A or B are required for that part;
#   C is excellent for the LONG-TERM analytical/reporting side of the
#   same data, and production IoT platforms frequently use BOTH — a
#   time-series database for the hot/recent path, object storage +
#   Trino for the cold/historical analytical path.


# ============================================================================
# CASE STUDY 4 — CHOOSING A CONSISTENCY MODEL FOR A MULTI-REGION
# INVENTORY-COUNT SYSTEM
# ============================================================================
#
# SETUP: an inventory count (units available per SKU per warehouse) is
# read/written from multiple geographic regions; the business wants to
# avoid overselling (a hard correctness requirement) but also wants fast
# reads globally.

# ------------------------------------------------------------------------
# APPROACH A: A single-leader relational database (or DynamoDB with
# strongly-consistent reads, L03) — all writes go to one primary region
# ------------------------------------------------------------------------
#   WHY VALID: strong consistency BY CONSTRUCTION -- every write and
#   every strongly-consistent read goes through the same single source
#   of truth, making overselling (the stated hard requirement) provably
#   impossible from a consistency standpoint, the simplest possible
#   correctness argument.
#   COST: every write (and every strongly-consistent read) from a
#   geographically distant region pays real cross-region network
#   latency to reach the single primary -- for a genuinely global user
#   base, this can mean a meaningfully worse experience for users far
#   from the primary region, and the single primary is also a single
#   point of REGIONAL failure for writes.
#
# ------------------------------------------------------------------------
# APPROACH B: Cassandra (L02) with tunable per-operation consistency —
# strong consistency (QUORUM) for the actual decrement-on-purchase
# operation, eventual consistency for read-only "how many are in stock"
# display queries
# ------------------------------------------------------------------------
#   WHY VALID: per L02's tunable-consistency discussion, this
#   selectively pays the LATENCY cost of strong consistency ONLY where
#   correctness genuinely requires it (the actual purchase/decrement),
#   while letting the FAR more frequent "just show me the count" display
#   reads use cheaper, faster eventual consistency -- a deliberate,
#   workload-aware consistency choice rather than one uniform policy
#   applied everywhere regardless of actual need.
#   COST: requires the team to correctly identify and consistently apply
#   the RIGHT consistency level to the RIGHT operation everywhere in the
#   codebase -- a genuine, ongoing discipline/code-review burden, since
#   accidentally using eventual consistency for the decrement operation
#   (a bug, not a deliberate choice) reintroduces exactly the overselling
#   risk the system is meant to prevent.
#
# ------------------------------------------------------------------------
# APPROACH C: Per-region inventory ALLOCATION -- split total stock into
# region-specific sub-pools upfront (e.g. "100 units total, allocate 40
# to US warehouse's pool, 60 to EU"), each region operates independently
# on its own pool with strong LOCAL consistency, periodic rebalancing
# ------------------------------------------------------------------------
#   WHY VALID: eliminates cross-region consistency coordination for the
#   hot path ENTIRELY -- each region's writes/reads only ever touch its
#   OWN local pool, giving both strong consistency AND low latency
#   simultaneously for the common case, a genuinely different strategy
#   from A/B's "coordinate consistency across regions" approaches.
#   COST: can genuinely oversell IN AGGREGATE relative to true total
#   stock if one region's local pool sells out while another region
#   still shows availability that, combined, exceeds true total stock —
#   or conversely can under-sell (leave real stock unsold) if a region's
#   pool is exhausted while another region still has slack — a real,
#   structural tradeoff requiring a periodic rebalancing process to
#   manage, not a strictly stronger correctness guarantee than A or B.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Overselling risk | Global read/write latency | Complexity |
#   |----------|----------------------|---------------------------------|----------------|
#   | A: single-leader strong consistency | None | Poor for distant regions | Lowest |
#   | B: Cassandra, tunable per-operation | Low (if applied correctly) | Good | Medium (discipline required) |
#   | C: per-region allocation | Possible (aggregate mismatch) | Best | Medium (rebalancing process) |
#   For a genuinely hard "never oversell" requirement, A or a carefully-
#   audited B are the safer choices; C is common in practice specifically
#   because a SMALL, bounded, correctable amount of aggregate mismatch is
#   often an acceptable business tradeoff for dramatically better global
#   latency -- which of these is "correct" depends entirely on how
#   strictly the business actually needs zero overselling versus how much
#   it values fast global reads, a business decision this domain's tools
#   can support but not make for you.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
