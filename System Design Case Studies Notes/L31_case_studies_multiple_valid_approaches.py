"""
WHAT: Four ADDITIONAL realistic hard-subsystem problems (in the same
      spirit as this domain's Google Meet/Docs/Spotify/Shazam/Reddit
      deep dives), each solved with THREE genuinely different,
      individually defensible approaches drawn from L01-L30 -- with an
      explicit comparison table and reasoning for why each answer is
      valid under different constraints. Distinct from L30's capstone
      (one specific full infra-stack trace) -- this lesson is about the
      decision process across competing options for new problems.
WHY:  Every one of this domain's 30 lessons picked ONE specific
      technique for a specific subsystem -- this lesson tests whether
      you can apply the SAME underlying tradeoffs to problems not
      explicitly covered, the actual skill a staff-level system-design
      interview is probing for.
LEVEL: Capstone -- read after L01-L30.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L30's concepts.
"""

# ============================================================================
# CASE STUDY 1 — DESIGNING "TYPING INDICATORS" FOR A CHAT APPLICATION
# (SIMILAR IN SPIRIT TO L08's PRESENCE/CURSOR DISCUSSION, APPLIED TO A
# NEW FEATURE)
# ============================================================================
#
# SETUP: a chat app needs to show "so-and-so is typing..." to other
# participants in a conversation, updating in near-real-time as users
# type and stop typing.
#
# ------------------------------------------------------------------------
# APPROACH A: Send a "typing" event to the server on EVERY keystroke,
# broadcast to other participants immediately
# ------------------------------------------------------------------------
#   WHY VALID: the simplest, most direct implementation -- maximum
#   responsiveness, the indicator appears the instant typing starts.
#   COST: per L08's ephemeral-presence-data discussion, this generates
#   an enormous volume of near-useless events (most keystrokes don't
#   meaningfully change the "is this person currently typing" answer) --
#   a real, unnecessary bandwidth and server-load cost at any
#   meaningful scale, broadcasting far more updates than the feature
#   actually needs to convey.
#
# ------------------------------------------------------------------------
# APPROACH B: Debounced/throttled typing events -- send a "started
# typing" event once when typing begins, a "stopped typing" event only
# after a pause (e.g. 3 seconds of no keystrokes), not on every
# keystroke (L08's ephemeral-data pattern)
# ------------------------------------------------------------------------
#   WHY VALID: per L08, this directly reduces A's event volume to
#   roughly two events per "typing session" instead of one per
#   keystroke, while still conveying the actually-relevant information
#   (is this person currently in the middle of typing something) --
#   the standard, well-established pattern most real chat apps use.
#   COST: introduces a small, deliberate LATENCY/staleness window (the
#   debounce interval) -- the indicator doesn't disappear the INSTANT
#   someone stops typing, only after the debounce timeout, a minor but
#   real UX tradeoff versus A's (wasteful but instant) approach.
#
# ------------------------------------------------------------------------
# APPROACH C: B, plus TTL-based expiration on the "typing" state itself
# (L08's heartbeat/cleanup pattern) -- if no "stopped typing" event
# arrives within a bounded window (e.g. the client crashed or lost
# connection mid-typing), the server-side typing state expires
# automatically
# ------------------------------------------------------------------------
#   WHY VALID: per L08's presence-cleanup discussion, directly closes a
#   real gap B has -- if a client disconnects abruptly WHILE a "typing"
#   indicator is active (crash, network drop, closing the browser tab
#   mid-sentence), B alone has no mechanism to ever send the "stopped
#   typing" event, leaving OTHER users seeing a stale "is typing..."
#   indicator indefinitely; a TTL-based expiration guarantees the
#   indicator eventually clears regardless of whether a clean
#   "stopped typing" event ever arrives.
#   COST: requires the server to track a per-user, per-conversation TTL
#   timer for typing state -- real, if modest, additional server-side
#   state and cleanup logic beyond B's simpler "just relay events"
#   approach, and choosing the TTL duration itself requires a real
#   tradeoff decision (too short: legitimate pauses in typing
#   incorrectly clear the indicator; too long: a genuinely stale
#   indicator lingers longer after a disconnect).
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Event volume | Handles abrupt client disconnect | Implementation complexity |
#   |----------|------------------|-----------------------------------------|----------------------------------|
#   | A: every keystroke | Highest | No (same gap as B) | Lowest |
#   | B: debounced start/stop events | Low | No (indicator can stick if client crashes) | Low |
#   | C: B + TTL expiration | Low | Yes | Medium |
#   C is the strongest production answer -- B alone has a real,
#   commonly-hit correctness gap (users see stale typing indicators
#   after other users' app crashes or network drops), which is exactly
#   the kind of "ephemeral state needs cleanup" lesson L08 teaches
#   applied to a new, related feature.


# ============================================================================
# CASE STUDY 2 — DESIGNING RATE LIMITING FOR A PUBLIC API WITH BOTH
# FREE-TIER AND PAID USERS
# ============================================================================
#
# SETUP: a public API needs different rate limits for free vs. paid
# tiers, and the limiting must be enforced consistently across MULTIPLE
# API gateway instances (a horizontally-scaled deployment, echoing this
# domain's infra-deep-dive lessons L21-L30).
#
# ------------------------------------------------------------------------
# APPROACH A: In-memory, per-instance rate limiting (each gateway
# instance tracks its own local counters, L27-L28's resource-allocation
# framing)
# ------------------------------------------------------------------------
#   WHY VALID: fastest possible check (no network call needed to enforce
#   a limit), zero additional infrastructure dependency -- if the load
#   balancer uses STICKY sessions (a given user always routes to the
#   same gateway instance, L22), each instance's local view of that
#   user's rate is actually accurate.
#   COST: without sticky sessions (or even with them, if a user's
#   requests happen to hit multiple instances, e.g. after a rebalance,
#   L23), each instance only sees a FRACTION of a given user's total
#   request rate -- a user could genuinely exceed the intended limit by
#   distributing requests across multiple gateway instances, each of
#   which independently thinks the user is under their local limit.
#
# ------------------------------------------------------------------------
# APPROACH B: Centralized rate limiting via a shared Redis instance
# (token bucket or sliding window, L06's rate-limiting-and-API-patterns
# lesson, combined with Redis & Caching Notes)
# ------------------------------------------------------------------------
#   WHY VALID: per L06, a SHARED counter store (Redis) gives every
#   gateway instance a consistent, accurate view of a given user's TOTAL
#   request rate across the whole fleet, directly solving A's
#   distributed-undercounting problem -- the standard, well-established
#   answer for rate limiting across a horizontally-scaled deployment.
#   COST: every single rate-limit check now requires a network round-
#   trip to Redis -- real, added latency per request (though typically
#   small, sub-millisecond, for a well-placed Redis instance) and Redis
#   itself becomes a genuine dependency in the request hot path; if
#   Redis is unavailable, the rate-limiting mechanism itself needs an
#   explicit fail-open/fail-closed policy decision.
#
# ------------------------------------------------------------------------
# APPROACH C: B, but with a LOCAL, approximate cache layer on top --
# each gateway instance caches a recently-fetched view of a user's rate-
# limit state for a very short window (e.g. tens of milliseconds),
# reducing the Redis round-trip frequency for high-request-rate users
# ------------------------------------------------------------------------
#   WHY VALID: reduces B's per-request Redis round-trip cost for the
#   highest-traffic users specifically (where the added latency matters
#   most in aggregate), while still periodically re-syncing with the
#   authoritative shared count often enough to keep enforcement
#   reasonably accurate -- a genuine latency/accuracy tradeoff dial,
#   not an all-or-nothing choice between A's pure-local and B's pure-
#   centralized extremes.
#   COST: introduces a real, if small and bounded, WINDOW where a user
#   could technically exceed their true limit slightly (using the
#   locally-cached, briefly-stale count) before the next resync catches
#   up -- an explicit, deliberate accuracy-for-latency tradeoff that
#   must be an acceptable one for a rate limiter (usually is, since
#   rate limits are rarely required to be perfectly, instantaneously
#   precise) but should be a conscious design decision, not an
#   unexamined side effect.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Accuracy across a fleet | Per-request latency cost | Handles Redis unavailability gracefully |
#   |----------|------------------------------|--------------------------------|-----------------------------------------------|
#   | A: per-instance local | Poor (undercounts) | None | N/A (no dependency) |
#   | B: centralized Redis | Best | Real (network round-trip) | Needs explicit fail-open/closed policy |
#   | C: B + short-lived local cache | Good, slightly approximate | Reduced | Needs the same explicit policy as B |
#   B is the correct default for accurate, fleet-wide enforcement; C is
#   the right optimization specifically once B's per-request Redis cost
#   is measured to be a genuine latency bottleneck at very high request
#   volumes.


# ============================================================================
# CASE STUDY 3 — DESIGNING A "READ RECEIPTS" FEATURE FOR A MESSAGING APP
# AT LARGE GROUP-CHAT SCALE (GROUPS WITH THOUSANDS OF MEMBERS)
# ============================================================================
#
# SETUP: users want to know who has read their message -- straightforward
# for a 1-on-1 chat, but a group with thousands of members raises real
# scale questions (echoing L16's comment-tree-storage-at-scale reasoning,
# applied to a related "who has seen this" problem).
#
# ------------------------------------------------------------------------
# APPROACH A: Store a full list of (user_id, read_timestamp) pairs per
# message, updated whenever a user reads it
# ------------------------------------------------------------------------
#   WHY VALID: complete, precise data -- can answer "exactly who has
#   read this, and when" for any message, the richest possible feature
#   set, genuinely appropriate for a small group chat where showing a
#   full read-by list is a valued feature.
#   COST: for a group with THOUSANDS of members, a popular message
#   could accumulate thousands of individual read-receipt rows -- a
#   real storage-volume and write-amplification cost (every message,
#   read by every member, multiplies out fast), and per L16's storage-
#   at-scale reasoning, both the write pattern (thousands of individual
#   updates per message) and any query needing to summarize this data
#   become genuinely expensive at this scale.
#
# ------------------------------------------------------------------------
# APPROACH B: Store only an AGGREGATE read count per message (e.g. "seen
# by 1,247 people"), not individual identities, for large groups --
# switch to full per-user tracking (A) only for small groups (e.g. under
# 20 members)
# ------------------------------------------------------------------------
#   WHY VALID: per L16/L20's scale-appropriate-data-structure reasoning,
#   a simple counter (incrementable, cheap to update and read) avoids
#   A's storage/write-amplification cost entirely for large groups,
#   while preserving A's full richness where it's actually valuable AND
#   affordable (small groups, where the per-member list is both useful
#   and cheap).
#   COST: loses the ability to answer "specifically WHO has read this"
#   for large groups -- a real feature reduction, not just a technical
#   optimization, that the product needs to explicitly accept as a
#   scale-dependent tradeoff (and communicate to users, e.g. showing an
#   aggregate count instead of a name list once a group crosses the
#   size threshold).
#
# ------------------------------------------------------------------------
# APPROACH C: B's aggregate count for the common case, PLUS a
# probabilistic data structure (a Bloom filter or HyperLogLog, Redis &
# Caching Notes L03) if an APPROXIMATE "has this specific person read
# it" check is still needed for large groups, without the full storage
# cost of A
# ------------------------------------------------------------------------
#   WHY VALID: per Redis & Caching Notes L03's HyperLogLog/probabilistic-
#   structure discussion, this recovers SOME of A's per-user query
#   capability (an approximate "did user X read this" check) at a
#   fraction of A's storage cost, if the product need is specifically
#   "let ME check if a particular person saw my message" rather than
#   "show everyone a full list of readers."
#   COST: probabilistic data structures have inherent, real error rates
#   (false positives for Bloom filters, approximate counts for
#   HyperLogLog) -- genuinely inappropriate if the feature needs an
#   EXACT answer (a compliance or dispute-resolution context, for
#   instance), and adds real conceptual complexity to the system beyond
#   B's simple counter for a capability that may not even be a real
#   product requirement.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Storage cost at scale | Per-user read-status query | Fits thousands-of-members groups |
#   |----------|----------------------------|----------------------------------|-------------------------------------------|
#   | A: full per-user list | Highest | Exact | Poorly |
#   | B: aggregate count only, for large groups | Lowest | Not available | Well |
#   | C: B + probabilistic per-user check | Low | Approximate | Well |
#   B is the right default unless there's a CONFIRMED product need for
#   per-user read status even in large groups; C is only worth the added
#   complexity if that specific need is real and an approximate answer
#   is genuinely acceptable for it.


# ============================================================================
# CASE STUDY 4 — DESIGNING GEOGRAPHIC LOAD BALANCING FOR A GLOBAL
# SERVICE (EXTENDING L21-L26's LOAD-BALANCING DEEP DIVE TO A
# MULTI-REGION QUESTION)
# ============================================================================
#
# SETUP: a service now runs in three geographic regions; incoming
# traffic needs to be routed to the NEAREST/best-performing region, with
# automatic failover if a region goes down.
#
# ------------------------------------------------------------------------
# APPROACH A: DNS-based geographic routing (e.g. Route 53 geolocation/
# latency-based routing, Cloud Platforms Notes L08) -- DNS resolves a
# user's request to the nearest region's IP
# ------------------------------------------------------------------------
#   WHY VALID: per Cloud Platforms Notes L08, this is the standard,
#   well-established mechanism for multi-region traffic routing --
#   works at the DNS layer, before any connection is even established,
#   and integrates with health checks to automatically stop routing to
#   an unhealthy region.
#   COST: per Cloud Platforms Notes L08 and general DNS behavior, DNS
#   responses are CACHED by clients/resolvers for a TTL period -- a
#   region failover isn't instant; some fraction of users continue
#   trying to reach a now-unhealthy region until their cached DNS
#   record expires, a real, bounded-but-nonzero failover delay
#   inherent to DNS-based approaches.
#
# ------------------------------------------------------------------------
# APPROACH B: Anycast IP routing (a single IP address, announced from
# multiple regions, with network-layer routing directing each user to
# the topologically nearest announcing region)
# ------------------------------------------------------------------------
#   WHY VALID: operates at the NETWORK layer (BGP), not DNS -- failover
#   can be significantly faster than DNS-based approaches once a
#   region's route is withdrawn (no client-side DNS cache to wait out),
#   and users are naturally routed to the network-topologically closest
#   healthy region.
#   COST: anycast requires genuine network-infrastructure capability
#   (BGP route announcement across regions) that's a significantly
#   bigger operational/infrastructure lift than DNS-based routing --
#   typically only available via specific cloud provider offerings or
#   real investment in networking infrastructure, not a simple
#   configuration change like A.
#
# ------------------------------------------------------------------------
# APPROACH C: A, but with a DELIBERATELY SHORT DNS TTL specifically to
# minimize A's failover-delay weakness, combined with CLIENT-SIDE retry
# logic that, on a connection failure, doesn't just retry the same
# (possibly still-cached, still-unhealthy) endpoint but explicitly
# re-resolves DNS before retrying
# ------------------------------------------------------------------------
#   WHY VALID: directly targets A's specific weakness (DNS caching
#   delaying failover) with two complementary, comparatively low-effort
#   mitigations -- a shorter TTL bounds the worst-case staleness window
#   more tightly, and client-side "re-resolve on failure" logic can
#   often recover almost immediately upon a connection error, without
#   needing to wait for the TTL to naturally expire at all.
#   COST: a very short DNS TTL means MORE frequent DNS lookups overall
#   (even during normal, non-failover operation), a real, if usually
#   small, added load on DNS infrastructure and marginal latency cost
#   per lookup; and the client-side retry logic requires control over
#   the CLIENT (straightforward for a mobile app or a controlled backend
#   service calling this API, but not something you can enforce for an
#   arbitrary third-party client hitting a public API).
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Failover speed | Infrastructure investment required | Requires client-side cooperation |
#   |----------|---------------------|-------------------------------------------|------------------------------------------|
#   | A: DNS geo-routing, standard TTL | Slower (TTL-bound) | Low | No |
#   | B: Anycast | Fastest | Highest | No |
#   | C: A + short TTL + client re-resolve retry | Faster than A alone | Low | Yes, for the retry-logic benefit |
#   For most teams, A is the practical starting point; C is a strong,
#   comparatively low-effort improvement worth making specifically
#   where the calling client is under the team's own control; B is
#   justified specifically once failover-speed requirements are strict
#   enough to justify its significantly higher infrastructure investment.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
