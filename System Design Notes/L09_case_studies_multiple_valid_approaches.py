"""
WHAT: Four realistic system-design tradeoff problems, each solved with
      THREE genuinely different, individually defensible approaches
      drawn from L01-L08 -- with an explicit comparison table and
      reasoning for why each answer is valid under different
      constraints.
WHY:  "SQL or NoSQL," "sync or async," "cache invalidation strategy" are
      all questions L01-L08 gave you real tools for, not one universal
      answer -- this lesson is about the decision process under real
      consistency, latency, and scale constraints, the actual skill
      system-design interviews test.
LEVEL: Capstone -- read after L01-L08.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L08's concepts.
"""

# ============================================================================
# CASE STUDY 1 — DESIGNING THE WRITE PATH FOR A "LIKE" BUTTON AT MASSIVE
# SCALE (MILLIONS OF LIKES/SECOND DURING A VIRAL MOMENT)
# ============================================================================
#
# SETUP: a social platform's like-count needs to handle extreme,
# unpredictable write bursts (a viral post can receive millions of likes
# within minutes) while keeping the displayed count reasonably accurate.
#
# ------------------------------------------------------------------------
# APPROACH A: Write directly to the primary database on every like,
# with strong consistency (L03)
# ------------------------------------------------------------------------
#   WHY VALID: per L03, this guarantees the displayed count is always
#   exactly correct -- no eventual-consistency window, no risk of a
#   count ever being wrong, the simplest CORRECTNESS story of the three.
#   COST: per L03, a single database row (the like counter for one
#   viral post) becomes an extreme write-contention hotspot at this
#   scale -- millions of concurrent writes to the SAME row, hitting a
#   hard throughput ceiling on that row's lock/update rate regardless of
#   how much the database is otherwise scaled, a well-known "hot key"
#   failure mode.
#
# ------------------------------------------------------------------------
# APPROACH B: Buffer likes in a message queue (L04), batch-aggregate and
# apply updates to the count periodically (e.g. every few seconds)
# ------------------------------------------------------------------------
#   WHY VALID: per L04, decouples the WRITE RATE clients experience
#   (fire into a queue, fast and cheap) from the actual database UPDATE
#   rate (batched, far fewer actual writes to the hot row) -- directly
#   solves A's hot-row contention problem by trading immediate
#   consistency for batched throughput.
#   COST: per L04, the displayed count is now EVENTUALLY consistent,
#   lagging by the batch interval -- a real, if usually acceptable for
#   this specific feature, accuracy tradeoff, and the queue itself
#   needs to be provisioned to handle the peak burst rate, a real
#   capacity-planning requirement.
#
# ------------------------------------------------------------------------
# APPROACH C: Client-side/edge approximate counting -- maintain
# SHARDED counters (multiple independent counter rows for the same
# post, writes randomly distributed across shards, summed only at READ
# time) combined with B's batching (System Design Case Studies Notes
# L18's voting-system discussion)
# ------------------------------------------------------------------------
#   WHY VALID: per System Design Case Studies Notes L18, sharding the
#   counter itself directly eliminates A's single-hot-row bottleneck
#   (writes spread across N shards, each individually far below the
#   contention ceiling) while STILL applying B's batching for additional
#   throughput headroom -- the strongest scalability answer of the
#   three, combining two complementary techniques.
#   COST: reading the CURRENT count now requires summing across all
#   shards (a more expensive read than A/B's single-row read) -- a real
#   read-side cost traded for write-side scalability, and choosing the
#   right shard COUNT requires real capacity planning (too few shards
#   and contention returns; too many and read-time summing cost grows
#   for comparatively little additional write benefit).
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Write scalability | Count accuracy | Read cost |
#   |----------|------------------------|---------------------|---------------|
#   | A: direct write, strong consistency | Worst (hot-row ceiling) | Perfect | Cheapest |
#   | B: queued + batched writes | Better | Eventually consistent | Cheap |
#   | C: sharded counters + batching | Best | Eventually consistent | More expensive |
#   For a feature genuinely expecting VIRAL-scale bursts, C is the
#   correct answer -- A fails outright at the stated scale, and B alone
#   still concentrates all writes on one logical counter even if
#   batched, leaving real headroom on the table that C's sharding
#   captures.


# ============================================================================
# CASE STUDY 2 — CACHE INVALIDATION STRATEGY FOR A PRODUCT-CATALOG
# SERVICE
# ============================================================================
#
# SETUP: product pages are heavily cached for read performance, but
# price/stock updates need to be reflected reasonably promptly, not left
# indefinitely stale.
#
# ------------------------------------------------------------------------
# APPROACH A: TTL-based expiration only -- cache entries expire after a
# fixed time (e.g. 60 seconds), no explicit invalidation on update (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, the simplest possible cache-management scheme --
#   no coordination needed between the write path and the cache at all,
#   the cache "self-heals" to correctness within, at worst, one TTL
#   window after any update.
#   COST: per L02, EVERY update is stale for up to the FULL TTL window,
#   regardless of how urgently that specific update needs to be visible
#   -- for a price change or a "just sold out" stock update, users can
#   see incorrect information for the entire TTL period, a real,
#   directly-noticeable correctness gap for exactly the updates that
#   matter most (pricing, availability).
#
# ------------------------------------------------------------------------
# APPROACH B: Explicit invalidation on write -- when a product updates,
# actively evict/update its specific cache entry immediately (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, this directly closes A's staleness gap for the
#   UPDATED item specifically -- the moment a price changes, the cache
#   entry is invalidated, and the next read repopulates it with current
#   data, giving near-immediate consistency for anything that actually
#   changed.
#   COST: per L02, requires the write path to correctly identify and
#   invalidate EVERY cache entry that could be affected by an update --
#   for a product page that might be cached under multiple keys (by ID,
#   by category listing, by search result), missing even one cache
#   location leaves a real, silent staleness gap that TTL-only (A)
#   doesn't have (since A's blanket TTL eventually catches everything,
#   even entries the invalidation logic forgot).
#
# ------------------------------------------------------------------------
# APPROACH C: Explicit invalidation (B) as the primary mechanism, PLUS a
# SHORTER backup TTL (e.g. 30 seconds) as a safety net for any cache
# entry the invalidation logic might have missed
# ------------------------------------------------------------------------
#   WHY VALID: directly combines B's near-immediate consistency for the
#   common case with A's self-healing guarantee as a backstop for the
#   cases B's invalidation logic doesn't (or can't practically) cover
#   -- a defense-in-depth approach where a missed invalidation is a
#   bounded, TTL-limited staleness window rather than an indefinite one.
#   COST: the most implementation and reasoning complexity of the three
#   -- requires BOTH a correct invalidation-on-write implementation AND
#   a sensibly-chosen backup TTL, and a team can be tempted to under-
#   invest in getting B's invalidation logic fully correct ("the TTL
#   will catch it eventually anyway"), quietly degrading toward A's
#   weaker guarantee if that discipline slips.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Staleness for updated items | Robustness to missed invalidation cases | Implementation complexity |
#   |----------|------------------------------------|------------------------------------------------|----------------------------------|
#   | A: TTL only | Up to full TTL, always | N/A (nothing to miss) | Lowest |
#   | B: explicit invalidation only | Near-zero, if correctly implemented | Poor (a miss = indefinite staleness) | Medium |
#   | C: invalidation + backup TTL | Near-zero, bounded worst case | Good (TTL bounds any miss) | Highest |
#   C is the strongest production answer for data where staleness has
#   real user-facing consequences (pricing, stock); A alone is
#   reasonable specifically for content where a short staleness window
#   is genuinely inconsequential (e.g. a product description that
#   rarely changes).


# ============================================================================
# CASE STUDY 3 — DESIGNING FOR A SERVICE THAT NEEDS TO CALL THREE
# DOWNSTREAM SERVICES TO FULFILL ONE REQUEST
# ============================================================================
#
# SETUP: an "order summary" API aggregates data from an orders service,
# a shipping service, and a payments service -- deciding how to
# structure this fan-out (L02, L05).
#
# ------------------------------------------------------------------------
# APPROACH A: Sequential calls -- call orders, then shipping, then
# payments, one after another (L02)
# ------------------------------------------------------------------------
#   WHY VALID: the simplest possible implementation, easiest to reason
#   about and debug (a linear execution trace), appropriate if the calls
#   genuinely have a DEPENDENCY order (e.g. shipping info can't be
#   fetched without first knowing the order ID from the orders call).
#   COST: per L02/L05, if the three calls are actually INDEPENDENT (all
#   just need the same order ID, no call depends on another's result),
#   sequential execution needlessly SUMS their individual latencies --
#   three 100ms calls become 300ms total, when they could have completed
#   concurrently in roughly 100ms if genuinely independent.
#
# ------------------------------------------------------------------------
# APPROACH B: Concurrent/parallel calls (fan-out, then fan-in) when the
# calls are genuinely independent (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, directly fixes A's needless latency-summing --
#   independent calls launched concurrently complete in roughly the
#   time of the SLOWEST single call, not the sum of all three, a real,
#   substantial latency improvement for genuinely independent fan-out.
#   COST: per L02, requires the calling service to handle PARTIAL
#   failure explicitly -- what happens if 2 of 3 calls succeed but one
#   times out or errors? Sequential code has an obvious, if slow, answer
#   (stop at the failed step); concurrent fan-out needs an explicit
#   policy (return partial data with an error indicator? fail the whole
#   request? retry just the failed call?) that sequential execution
#   doesn't force you to design as deliberately.
#
# ------------------------------------------------------------------------
# APPROACH C: An API Gateway/Backend-for-Frontend (BFF) pattern (L06)
# that owns this aggregation logic, with circuit breakers (Python Notes
# L08) per downstream dependency, returning gracefully-degraded partial
# responses when a downstream service is unhealthy
# ------------------------------------------------------------------------
#   WHY VALID: per L06 combined with the circuit-breaker pattern,
#   directly addresses B's partial-failure-handling gap with an explicit,
#   robust policy -- if the payments service is having an outage, the
#   circuit breaker trips quickly (rather than every request waiting out
#   a slow timeout) and the response gracefully includes orders/shipping
#   data with a clear "payment info temporarily unavailable" indicator,
#   rather than either the whole request failing or hanging.
#   COST: the most architectural investment of the three -- circuit
#   breaker state management per downstream dependency, and genuine
#   product-level design work deciding what a "gracefully degraded"
#   response should actually look like for each possible partial-failure
#   combination, real complexity beyond B's simpler (if less resilient)
#   concurrent-fan-out-with-basic-error-handling approach.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Latency (if calls are independent) | Partial-failure handling | Implementation complexity |
#   |----------|-------------------------------------------|--------------------------------|----------------------------------|
#   | A: sequential | Worst (sum of all calls) | Simple (stop at failure) | Lowest |
#   | B: concurrent fan-out | Best (max of all calls) | Needs explicit policy | Medium |
#   | C: B + circuit breakers + graceful degradation | Best, resilient to slow/down dependencies | Best (explicit, graceful) | Highest |
#   B is the right fix once calls are confirmed independent; C is the
#   right escalation specifically once this endpoint is important/high-
#   traffic enough that a downstream outage's blast radius (a fully
#   failed or hung request) is worth the added resilience engineering.


# ============================================================================
# CASE STUDY 4 — CHOOSING A DATA-CONSISTENCY MODEL FOR A MULTI-STEP
# CHECKOUT FLOW (RESERVE INVENTORY, CHARGE PAYMENT, CREATE ORDER)
# ============================================================================
#
# SETUP: a checkout flow spans three separate services/database
# operations that all need to succeed together, or the whole checkout
# should be reverted -- a classic distributed-transaction problem
# (L04, Distributed Systems Theory Notes L04).
#
# ------------------------------------------------------------------------
# APPROACH A: A single, monolithic database transaction spanning all
# three operations (only feasible if all three actually live in the SAME
# database)
# ------------------------------------------------------------------------
#   WHY VALID: per SQL Notes' transaction/isolation discussion, a real
#   ACID transaction gives the strongest possible guarantee -- either
#   ALL three operations commit together, or none do, with zero
#   possibility of a partial, inconsistent state ever being visible.
#   COST: only works if inventory, payment, and order data ALL live in
#   the SAME database/transaction boundary -- per Distributed Systems
#   Theory Notes L04, payment processing in particular typically
#   involves an EXTERNAL third-party payment provider's API, which
#   categorically cannot participate in a local database transaction --
#   this approach simply doesn't apply once payment is external, which
#   is the realistic, common case.
#
# ------------------------------------------------------------------------
# APPROACH B: Two-Phase Commit (2PC) across the three services
# (Distributed Systems Theory Notes L04)
# ------------------------------------------------------------------------
#   WHY VALID: per Distributed Systems Theory Notes L04, 2PC provides a
#   genuine distributed atomicity guarantee across multiple independent
#   systems -- closer to A's strong guarantee, but actually usable
#   across service/database boundaries, unlike A.
#   COST: per Distributed Systems Theory Notes L04, 2PC has a well-
#   documented BLOCKING weakness -- if the coordinator crashes mid-
#   protocol, participants can be left holding locks indefinitely,
#   waiting for a resolution that may never come, and (critically for
#   THIS case study) most external payment providers don't support
#   participating in a 2PC protocol at all, making this frequently
#   inapplicable for the same reason as A once a third-party payment
#   API is involved.
#
# ------------------------------------------------------------------------
# APPROACH C: The Saga pattern (Distributed Systems Theory Notes L04,
# System Design Notes L04) -- each step commits independently, with an
# explicit COMPENSATING action defined for each step to undo it if a
# LATER step fails
# ------------------------------------------------------------------------
#   WHY VALID: per Distributed Systems Theory Notes L04 and System
#   Design Notes L04, Sagas are specifically designed for exactly this
#   scenario -- independent services (including external payment APIs
#   that support simple charge/refund operations but not distributed
#   transaction protocols) each commit their own step, with a defined
#   "undo" (e.g. release the inventory reservation, refund the payment)
#   if a later step in the sequence fails -- the standard, practical
#   answer for real-world multi-service checkout flows.
#   COST: per Distributed Systems Theory Notes L04, Sagas provide only
#   EVENTUAL consistency, not the strong atomicity of A/B -- there IS a
#   real window where, e.g., inventory is reserved and payment is
#   charged, but the order record hasn't been created yet, during which
#   an inconsistent intermediate state genuinely exists and is
#   potentially observable; and every step needs a correctly-designed,
#   genuinely reliable compensating action, real design and testing
#   effort (what if the "refund payment" compensating action itself
#   fails?).
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Consistency strength | Works across external payment APIs | Failure-mode complexity |
#   |----------|---------------------------|-------------------------------------------|-------------------------------|
#   | A: single DB transaction | Strongest | No (rarely applicable) | Lowest |
#   | B: Two-Phase Commit | Strong | Rarely (most providers don't support it) | Real (blocking risk) |
#   | C: Saga pattern | Eventual | Yes | Real (compensating-action design) |
#   Given that real checkout flows almost always involve an external
#   payment provider, C is the practically dominant answer in production
#   -- A and B are largely theoretical alternatives for this specific
#   scenario once a genuine third-party payment API is in the picture,
#   which is the overwhelmingly common real-world case.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
