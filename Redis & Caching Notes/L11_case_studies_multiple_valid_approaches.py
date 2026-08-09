"""
WHAT: Four realistic Redis/caching problems, each solved with THREE
      genuinely different, individually defensible approaches drawn
      from L01-L10 -- with an explicit comparison table and reasoning
      for why each answer is valid under different constraints.
WHY:  "Cache-aside or write-through," "Redis Cluster or Sentinel,"
      "which eviction policy" are all questions L01-L10 gave you real
      tools for, not one universal answer -- this lesson is about the
      decision process under real consistency and availability
      constraints.
LEVEL: Capstone -- read after L01-L10.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L10's concepts.
"""

# ============================================================================
# CASE STUDY 1 — CACHING STRATEGY FOR A PRODUCT-DETAIL PAGE (READ-HEAVY,
# OCCASIONAL PRICE UPDATES)
# ============================================================================
#
# SETUP: product detail pages are read far more often than the
# underlying data changes (price updates, description edits); deciding
# on a caching pattern (L02).
#
# ------------------------------------------------------------------------
# APPROACH A: Cache-aside (lazy loading) -- application checks cache
# first, falls back to the database on a miss, populates the cache with
# the result (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, this is the simplest, most widely-applicable
#   pattern -- the cache is populated lazily, only for data that's
#   actually requested (no wasted caching of never-read products), and
#   requires no changes to the WRITE path at all.
#   COST: per L02, the FIRST request for any given (or newly-updated)
#   product always misses the cache, paying full database latency --
#   for a very popular product immediately after an update, this first-
#   request-after-invalidation cost repeats for every cache-population
#   event, and under high concurrency, multiple simultaneous first
#   requests can trigger a "thundering herd" of redundant database
#   queries all racing to populate the same cache entry (L02's stampede
#   discussion).
#
# ------------------------------------------------------------------------
# APPROACH B: Write-through caching -- every write to the database ALSO
# immediately updates the cache, so the cache is never stale and never
# has a true "cold" miss for previously-written data (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, this eliminates A's cold-miss-after-update
#   problem entirely -- the cache is updated synchronously with every
#   write, so a read immediately after a price update finds the cache
#   already correct, no stale window and no first-request penalty.
#   COST: per L02, every write now pays the additional latency of ALSO
#   updating the cache synchronously (a real, if usually small, per-
#   write cost), and caches EVERY written product regardless of whether
#   it's ever actually read again -- for a catalog with many rarely-
#   viewed products, this wastes cache memory on data that provides no
#   read-side benefit.
#
# ------------------------------------------------------------------------
# APPROACH C: Cache-aside (A) as the primary mechanism, PLUS stampede
# protection (a short-lived "lock" or "in-progress" marker preventing
# multiple concurrent requests from all triggering redundant database
# queries for the same cold key, L02's stampede-protection pattern)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, directly fixes A's most serious specific gap
#   (the thundering-herd risk) while keeping A's lazy-population
#   efficiency advantage over B (only genuinely-requested products get
#   cached) -- the first request for a cold key populates the cache
#   while concurrent requests for the SAME key wait briefly (or receive
#   a slightly-stale value) rather than all hitting the database
#   simultaneously.
#   COST: real, added implementation complexity over plain A -- the
#   stampede-protection logic itself (a distributed lock, or a
#   "probabilistic early expiration" technique) needs correct
#   implementation, and concurrent requests during the population window
#   experience slightly different latency than a straightforward cache-
#   aside miss (either a brief wait, or a request routed to serve a
#   near-expiry stale value while refresh happens in the background).
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Cache freshness after writes | Wasted cache memory on unread data | Thundering-herd risk |
#   |----------|------------------------------------|-------------------------------------------|----------------------------|
#   | A: plain cache-aside | Stale until next read repopulates | None (lazy) | Real |
#   | B: write-through | Always fresh | Real (caches everything written) | None |
#   | C: cache-aside + stampede protection | Stale until next read repopulates | None | Mitigated |
#   C is the strongest default for a genuinely read-heavy, popularity-
#   skewed catalog (the common real case) -- B is the right choice
#   specifically when write-path latency headroom exists and near-
#   perfect freshness matters more than cache memory efficiency.


# ============================================================================
# CASE STUDY 2 — CHOOSING BETWEEN REDIS SENTINEL AND REDIS CLUSTER FOR
# HIGH AVAILABILITY
# ============================================================================
#
# SETUP: a team's Redis deployment currently runs as a single instance
# (a real single point of failure); deciding on a high-availability
# architecture (L08-L09).
#
# ------------------------------------------------------------------------
# APPROACH A: Redis Sentinel (L09) -- automated failover between a
# primary and one or more replicas, no data sharding
# ------------------------------------------------------------------------
#   WHY VALID: per L09, Sentinel directly solves the single-point-of-
#   failure problem (automatic failover to a replica if the primary
#   fails) WITHOUT introducing sharding complexity -- if the dataset
#   comfortably fits on a single node's memory, this is the simplest
#   path to real HA without needing to reason about cross-shard data
#   distribution or the cross-slot limitations L09 discusses.
#   COST: per L09, Sentinel doesn't provide any HORIZONTAL SCALING --
#   all data still lives on one primary node (with replicas as standby
#   copies, not additional capacity) -- if the dataset OUTGROWS a
#   single node's memory capacity, Sentinel alone doesn't help; this is
#   purely an availability solution, not a scale solution.
#
# ------------------------------------------------------------------------
# APPROACH B: Redis Cluster (L08-L09) -- data sharded across multiple
# nodes via hash slots, with built-in replication per shard
# ------------------------------------------------------------------------
#   WHY VALID: per L08-L09, Cluster provides BOTH horizontal scaling
#   (data spread across many nodes' combined memory) AND high
#   availability (each shard has its own replica(s) for failover) in one
#   architecture -- the right answer once the dataset genuinely exceeds
#   what a single node can hold, or write throughput exceeds a single
#   node's capacity.
#   COST: per L09, Cluster's HASH SLOT model introduces real
#   CROSS-SLOT limitations -- multi-key operations (transactions,
#   certain Lua scripts) only work cleanly when all involved keys hash
#   to the SAME slot, a genuine application-design constraint Sentinel's
#   single-node model doesn't impose at all; migrating an application
#   originally built assuming unrestricted multi-key operations onto
#   Cluster can require real refactoring.
#
# ------------------------------------------------------------------------
# APPROACH C: Sentinel (A) for now, with an explicit, monitored trigger
# (e.g. memory utilization crossing 70% of a single node's capacity) to
# migrate to Cluster (B) later, rather than adopting Cluster's added
# complexity preemptively
# ------------------------------------------------------------------------
#   WHY VALID: per L09's own framing, Cluster's cross-slot constraints
#   and operational complexity are real, ongoing costs that are only
#   worth paying once actually NEEDED -- if the current dataset
#   comfortably fits on one node (as is very often true, especially
#   early on), starting with Sentinel's simpler HA model and migrating
#   only once a measured, real capacity signal justifies it avoids
#   premature complexity.
#   COST: migrating from Sentinel to Cluster LATER is real, nontrivial
#   work (potential application changes for cross-slot operations, a
#   genuine data-migration/resharding process) -- if the team has
#   strong, confident signals from the START that the dataset WILL
#   exceed single-node capacity soon, building on Cluster from day one
#   avoids this later migration cost, making this sequencing
#   specifically wrong when that early confidence is warranted.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Solves availability | Solves horizontal scale | Application constraints (multi-key ops) |
#   |----------|--------------------------|--------------------------------|-------------------------------------------------|
#   | A: Sentinel | Yes | No | None |
#   | B: Cluster | Yes | Yes | Real (cross-slot limitations) |
#   | C: Sentinel now, Cluster when triggered | Yes, immediately | Deferred | None, until migration |
#   For a dataset genuinely likely to stay within single-node capacity,
#   A (or C's sequencing) is the right, lower-complexity answer; B is
#   correct to adopt from the start specifically when scale requirements
#   are already confidently known to exceed single-node capacity.


# ============================================================================
# CASE STUDY 3 — CHOOSING AN EVICTION POLICY FOR A MEMORY-CONSTRAINED
# CACHE
# ============================================================================
#
# SETUP: a Redis instance used purely as a cache (not primary storage)
# is approaching its configured memory limit; deciding on
# `maxmemory-policy` (L08's memory-tuning discussion).
#
# ------------------------------------------------------------------------
# APPROACH A: `noeviction` -- reject new writes once memory is full,
# rather than evicting anything
# ------------------------------------------------------------------------
#   WHY VALID: per L08, appropriate ONLY if Redis is being used for data
#   that must NEVER be silently lost (i.e., genuinely NOT just a cache,
#   but a primary data store) -- guarantees no existing data is ever
#   evicted without the application explicitly deciding to remove it.
#   COST: for a use case that IS genuinely a cache (as stated in this
#   case study's setup), this is actively the wrong policy -- it causes
#   WRITE FAILURES once memory fills, rather than gracefully evicting
#   old/unneeded cache entries to make room, turning a capacity-
#   management non-event into application-visible errors.
#
# ------------------------------------------------------------------------
# APPROACH B: `allkeys-lru` -- evict the least-recently-used key,
# regardless of whether it has a TTL set, when memory is full
# ------------------------------------------------------------------------
#   WHY VALID: per L08, this is the standard, well-understood default
#   for a PURE cache use case -- LRU is a reasonable, generally
#   effective proxy for "which data is least likely to be needed again
#   soon," and considering ALL keys (not just ones with an explicit TTL)
#   for eviction maximizes the pool of evictable data, giving the
#   eviction mechanism maximum flexibility to free memory.
#   COST: per L08, LRU is a HEURISTIC, not a guarantee of optimal
#   eviction -- for access patterns that don't follow a simple
#   recency-predicts-future-access pattern (e.g. a strong periodic/
#   cyclical access pattern, or drastically different-cost-to-
#   regenerate cache entries where a cheap-to-regenerate entry might be
#   fine to evict but an expensive-to-regenerate one really shouldn't
#   be), plain LRU doesn't account for that nuance.
#
# ------------------------------------------------------------------------
# APPROACH C: `volatile-lru` (evict LRU only among keys that HAVE an
# explicit TTL set), combined with a deliberate application-level
# convention that expensive-to-regenerate/critical cache entries are
# stored WITHOUT a TTL (making them ineligible for eviction under this
# policy) while cheap/routine cache entries always get a TTL
# ------------------------------------------------------------------------
#   WHY VALID: per L08, this gives the application EXPLICIT control over
#   what's evictable, directly addressing B's "doesn't distinguish
#   regeneration cost" limitation -- critical, expensive-to-recompute
#   entries are protected from eviction by the deliberate absence of a
#   TTL, while routine entries remain freely evictable.
#   COST: requires the APPLICATION to consistently follow this TTL-
#   setting convention correctly -- a real, ongoing discipline
#   requirement (a developer who forgets to set a TTL on a routine
#   cache entry accidentally makes it permanently protected from
#   eviction, potentially exhausting memory anyway if enough entries
#   accumulate this way), and if EVERY key ends up with a TTL (no
#   entries are ever "protected"), this degenerates to behaving like B
#   anyway.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Fits a pure-cache use case | Distinguishes regeneration cost | Discipline required |
#   |----------|----------------------------------|---------------------------------------|---------------------------|
#   | A: noeviction | No (wrong policy for a cache) | N/A | None |
#   | B: allkeys-lru | Yes | No | None |
#   | C: volatile-lru + TTL convention | Yes | Yes, via convention | Real, ongoing |
#   B is the correct, low-effort default for most pure-cache use cases;
#   C is worth the added discipline specifically when SOME cache
#   entries are meaningfully more expensive to regenerate than others
#   and protecting them from casual eviction has real, measurable value.


# ============================================================================
# CASE STUDY 4 — DECIDING WHETHER TO USE REDIS PUB/SUB OR REDIS STREAMS
# FOR AN EVENT-NOTIFICATION FEATURE
# ============================================================================
#
# SETUP: a feature needs to notify interested subscribers when an event
# occurs (e.g. "order status changed"); deciding between Redis's two
# messaging primitives (L04, L07).
#
# ------------------------------------------------------------------------
# APPROACH A: Redis Pub/Sub (L07)
# ------------------------------------------------------------------------
#   WHY VALID: per L07, Pub/Sub is the simplest possible messaging
#   primitive -- publish a message, any currently-subscribed clients
#   receive it immediately, minimal setup and conceptual overhead,
#   appropriate for genuinely ephemeral, best-effort notifications where
#   a subscriber missing a message (because it wasn't connected at that
#   exact moment) is an acceptable, low-consequence event.
#   COST: per L07, Pub/Sub provides NO persistence or delivery guarantee
#   whatsoever -- a subscriber that's briefly disconnected (a deploy, a
#   network blip) simply MISSES any messages published during that
#   window, permanently and silently, with no mechanism to catch up; a
#   real, disqualifying gap if "order status changed" notifications
#   genuinely need to reach every interested party reliably.
#
# ------------------------------------------------------------------------
# APPROACH B: Redis Streams (L04) with consumer groups
# ------------------------------------------------------------------------
#   WHY VALID: per L04, Streams provide PERSISTENCE (messages remain in
#   the stream, retrievable even by a consumer that connects later) and
#   consumer-group semantics (each message delivered to one consumer
#   within a group, with acknowledgment tracking and the ability to
#   reclaim unacknowledged messages via a watchdog pattern, L04) --
#   directly closes Pub/Sub's reliability gap.
#   COST: per L04, genuinely more operational complexity than Pub/Sub --
#   consumer group management, acknowledgment logic, and stream
#   trimming/retention policy (to prevent unbounded stream growth) all
#   need to be correctly configured and maintained, real additional
#   surface area beyond Pub/Sub's near-zero-configuration model.
#
# ------------------------------------------------------------------------
# APPROACH C: A dedicated message queue/broker (Apache Kafka Notes, or
# NATS from Event-Driven & Real-Time AI Systems Notes) instead of either
# Redis primitive, if this notification need is genuinely central to the
# product's architecture (not an incidental feature)
# ------------------------------------------------------------------------
#   WHY VALID: if event-driven messaging is a CORE, growing part of the
#   architecture (many event types, many producers/consumers, need for
#   schema evolution, replay, cross-service event sourcing), a purpose-
#   built message broker (Kafka Notes, or NATS per Event-Driven & Real-
#   Time AI Systems Notes L03's comparison) offers a richer, more
#   mature feature set (schema registries, longer retention, more
#   sophisticated partitioning/ordering guarantees) than Redis Streams
#   was primarily designed to provide.
#   COST: introduces an entirely separate messaging INFRASTRUCTURE
#   system beyond Redis (which the team may already be operating for
#   other purposes) -- real, additional operational surface, genuinely
#   unjustified if this is a single, contained notification feature
#   rather than a broader, architecture-wide event-driven need.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Delivery reliability | Operational complexity | Fits a single, contained feature vs. broader architecture |
#   |----------|---------------------------|------------------------------|--------------------------------------------------------------------|
#   | A: Pub/Sub | None (fire-and-forget) | Lowest | Fits only if loss is acceptable |
#   | B: Streams + consumer groups | Strong | Medium | Fits a contained feature needing reliability |
#   | C: dedicated message broker | Strongest, most feature-rich | Highest | Fits a broader, architecture-wide event need |
#   For THIS case study's single, order-status-notification feature
#   needing real reliability, B is the strongest fit; A is only
#   appropriate if message loss is genuinely acceptable; C is
#   over-engineering for a single contained feature but the right
#   answer once messaging becomes a genuinely central, growing part of
#   the broader system architecture.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
