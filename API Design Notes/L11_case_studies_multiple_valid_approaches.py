"""
WHAT: Four realistic API-design problems, each solved with THREE
      genuinely different, individually defensible approaches drawn from
      L01-L10 -- with an explicit comparison table and reasoning for why
      each answer is valid under different constraints.
WHY:  "REST or GraphQL or gRPC," "webhook or polling," "how to version"
      are all questions L01-L10 gave you real tools for, not one
      universal answer -- this lesson is about the decision process
      under real consumer and evolution constraints.
LEVEL: Capstone -- read after L01-L10.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L10's concepts.
"""

# ============================================================================
# CASE STUDY 1 — CHOOSING AN API STYLE FOR A NEW PUBLIC DEVELOPER
# PLATFORM
# ============================================================================
#
# SETUP: a company is launching a public API for third-party developers
# to build integrations against -- deciding between REST, GraphQL, and
# gRPC (L01, L03-L04).
#
# ------------------------------------------------------------------------
# APPROACH A: REST (L01)
# ------------------------------------------------------------------------
#   WHY VALID: per L01, REST is the most widely understood, tooling-
#   supported style among external developers -- nearly every developer
#   already knows how to consume a REST API, extensive documentation/
#   client-generation tooling exists, and it works naturally over plain
#   HTTP with standard caching semantics -- the lowest-friction choice
#   for MAXIMIZING the number of third-party developers who can easily
#   integrate.
#   COST: per L01, REST endpoints are relatively rigid -- if different
#   consumers need different subsets/shapes of data, REST typically
#   means either over-fetching (returning more than a given consumer
#   needs) or building many narrow, purpose-specific endpoints, neither
#   of which is as flexible as GraphQL's client-specified query shape.
#
# ------------------------------------------------------------------------
# APPROACH B: GraphQL (L04)
# ------------------------------------------------------------------------
#   WHY VALID: per L04, GraphQL lets each consumer request EXACTLY the
#   fields they need in one request, directly solving REST's over/
#   under-fetching problem -- valuable when third-party developers have
#   genuinely diverse, unpredictable data needs (some want minimal
#   summary data, others want deeply nested related data) that a fixed
#   set of REST endpoints would poorly anticipate.
#   COST: per L04, GraphQL has a real, steeper learning curve for
#   developers unfamiliar with it, and standard HTTP caching (a REST
#   strength) doesn't apply cleanly to GraphQL's single-endpoint, query-
#   in-the-body model -- for a PUBLIC, broad-developer-audience API,
#   this can genuinely narrow the addressable developer base relative
#   to REST's universal familiarity.
#
# ------------------------------------------------------------------------
# APPROACH C: REST as the primary, public-facing API (A), with gRPC
# (L03) reserved for INTERNAL service-to-service communication if the
# company also has that need -- NOT exposed to third-party developers
# at all
# ------------------------------------------------------------------------
#   WHY VALID: per L01/L03, this recognizes that "public developer
#   platform" and "internal service communication" are genuinely
#   different problems with different optimal answers -- gRPC's binary
#   protocol and strict schema (L03) are excellent for internal,
#   controlled-client communication (lower latency, strong typing) but
#   a poor fit for a public API meant to be broadly, easily consumable
#   by developers who may be using any language/tooling, some of which
#   has weaker gRPC support than plain HTTP/REST.
#   COST: doesn't directly compare to A/B as an alternative "public API
#   style" at all -- it's really a scoping clarification (gRPC isn't
#   competing for the public-facing role), which means this case study
#   still needs an answer to the actual question (REST vs GraphQL) for
#   the public-facing piece; this framing is a genuine, useful insight
#   but not a complete standalone answer.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Developer accessibility (broad audience) | Flexibility for diverse data needs | Fits internal service-to-service use |
#   |----------|-------------------------------------------------|--------------------------------------------|-------------------------------------------|
#   | A: REST | Best | Lower | Workable, not optimal |
#   | B: GraphQL | Lower (steeper learning curve) | Best | Workable, not optimal |
#   | C: REST public + gRPC internal (if needed) | Best (for the public piece) | Same as A for the public piece | Best (for the internal piece) |
#   For a broad, general-purpose public developer platform, A remains
#   the strongest default; B is justified specifically when third-party
#   consumer data needs are confirmed to be genuinely diverse enough
#   that REST's fixed-shape endpoints would be a real, recurring
#   friction point for many consumers, not just a theoretical concern.


# ============================================================================
# CASE STUDY 2 — NOTIFYING THIRD-PARTY INTEGRATIONS OF EVENTS (WEBHOOKS
# VS. POLLING VS. A STREAMING API)
# ============================================================================
#
# SETUP: third-party integrations need to know when a resource changes
# (e.g. "an order was fulfilled") in near-real-time (L06-L07).
#
# ------------------------------------------------------------------------
# APPROACH A: Require third parties to POLL a REST endpoint periodically
# for changes
# ------------------------------------------------------------------------
#   WHY VALID: per L06, simplest to implement on the PROVIDER side (no
#   need to manage outbound delivery, retries, or third-party endpoint
#   reliability) -- the integration owns the entire complexity of
#   checking for updates on their own schedule.
#   COST: per L06-L07, wastes resources on both sides (most polls find
#   nothing new) and has inherently worse latency (an update is only
#   noticed at the NEXT poll) than a push-based mechanism -- for a
#   "near-real-time" requirement, polling frequency needs to be tuned
#   tightly against this latency need, at the cost of proportionally
#   more wasted polling overhead.
#
# ------------------------------------------------------------------------
# APPROACH B: Webhooks (L06-L07) -- the provider POSTs an event payload
# to a URL the third party registers, the instant the event occurs
# ------------------------------------------------------------------------
#   WHY VALID: per L06-L07, this is the standard answer for exactly this
#   use case -- near-instant delivery, no wasted polling on either side,
#   the well-established pattern most third-party integration platforms
#   expect and support.
#   COST: per L06-L07, the PROVIDER now owns real, genuine delivery-
#   reliability complexity -- retries with backoff for failed
#   deliveries, handling a third party's endpoint being temporarily
#   down, and (per L07's async-API discussion) needing a way for third
#   parties to verify webhook authenticity (signature verification) to
#   prevent spoofed events -- meaningfully more provider-side
#   engineering than A.
#
# ------------------------------------------------------------------------
# APPROACH C: A persistent streaming connection (e.g. Server-Sent Events
# or a WebSocket-based event stream, adjacent to Full-Stack & Frontend
# Essentials Notes L08) that third parties connect to and receive events
# over, rather than requiring an exposed, publicly-reachable webhook URL
# ------------------------------------------------------------------------
#   WHY VALID: solves a REAL practical problem B has -- some third-party
#   integrations (e.g. a script running behind a corporate firewall, or
#   a simple client without its own public-facing server) genuinely
#   CANNOT receive inbound webhook POSTs at all, since they have no
#   publicly reachable endpoint; an outbound, third-party-INITIATED
#   streaming connection works for these consumers where webhooks
#   structurally cannot.
#   COST: requires the third party to maintain a genuinely persistent
#   connection (real client-side complexity: reconnection logic, missed-
#   event recovery after a disconnect) and the provider to operate
#   connection-management infrastructure at scale for potentially many
#   concurrent long-lived connections -- a different, not obviously
#   smaller, complexity burden than B's delivery-retry logic.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Latency | Provider-side complexity | Works for consumers with no public endpoint |
#   |----------|-------------|--------------------------------|------------------------------------------------------|
#   | A: polling | Worst (poll-interval-bound) | Lowest | Yes (consumer-initiated) |
#   | B: webhooks | Best | Real (retries, signature verification) | No (requires a public endpoint) |
#   | C: streaming connection | Best | Real (connection management at scale) | Yes (consumer-initiated) |
#   B is the standard default for most integration platforms; offering C
#   as an ALTERNATIVE delivery mechanism (not a replacement) specifically
#   accommodates consumers who can't receive webhooks; A remains a
#   reasonable low-effort fallback/complement for consumers who don't
#   need true real-time delivery.


# ============================================================================
# CASE STUDY 3 — VERSIONING STRATEGY FOR A REST API WITH MANY EXISTING
# THIRD-PARTY CONSUMERS
# ============================================================================
#
# SETUP: an established REST API needs a breaking change (removing a
# deprecated field, changing a response shape) but has many existing
# third-party integrations that would break if the change were applied
# in place (L02).
#
# ------------------------------------------------------------------------
# APPROACH A: URL path versioning (e.g. `/v1/orders` -> `/v2/orders`)
# (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, the most explicit, visible, widely-understood
#   versioning scheme -- consumers can see exactly which version
#   they're calling from the URL itself, and running v1 and v2 as
#   genuinely separate routes/implementations is straightforward to
#   reason about and operate independently.
#   COST: per L02, maintaining multiple FULL versions of the API
#   (potentially entire duplicated route trees/implementations) is real,
#   ongoing engineering burden -- every new feature/bugfix may need to
#   be considered for backporting to still-supported older versions,
#   and the maintenance surface grows with each new version introduced
#   without a clear old-version retirement plan.
#
# ------------------------------------------------------------------------
# APPROACH B: Header-based versioning (e.g. an `API-Version` request
# header, or content negotiation via `Accept`) rather than the URL (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, keeps URLs stable/canonical across versions (a
#   genuine REST purist argument -- a URL should identify a RESOURCE,
#   not a version of an API), and can allow more granular, per-request
#   version negotiation without needing an entirely separate route tree.
#   COST: per L02, meaningfully less DISCOVERABLE/obvious to developers
#   than A -- the version isn't visible just by looking at a URL in
#   documentation, browser history, or logs, a real, if usually
#   modest, developer-experience cost relative to URL versioning's
#   immediate visibility.
#
# ------------------------------------------------------------------------
# APPROACH C: Avoid a breaking version bump entirely where possible --
# make the change ADDITIVE (introduce the new field/shape ALONGSIDE the
# old one, deprecate the old field with a clear sunset timeline and
# deprecation warnings, per L02's OpenAPI/documentation discussion,
# rather than removing/changing it outright)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, this sidesteps A/B's version-proliferation cost
#   entirely for changes that CAN be made additively -- existing
#   consumers keep working completely unchanged (no migration required
#   at all), while new consumers can adopt the new field/shape
#   immediately; genuinely the lowest-disruption path whenever the
#   underlying change permits an additive approach.
#   COST: not every breaking change CAN be made additive -- some changes
#   (a field being removed for a real reason, like a security or data-
#   correctness issue, not just cosmetic cleanup) genuinely require the
#   old behavior to eventually stop being supported, at which point C
#   still needs SOME real versioning mechanism (A or B) for the
#   eventual, unavoidable breaking transition, just deferred as long as
#   possible.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Consumer disruption | Discoverability | Maintenance burden of multiple versions |
#   |----------|--------------------------|-----------------------|--------------------------------------------------|
#   | A: URL path versioning | Requires consumer migration to /v2 | Best | Real, ongoing |
#   | B: header-based versioning | Requires consumer migration | Lower | Real, ongoing |
#   | C: additive change, no version bump | None, if the change is genuinely additive | N/A | Lowest, if achievable |
#   Always attempt C first; when a change genuinely cannot be additive,
#   A is the stronger default for a PUBLIC API specifically because of
#   its superior discoverability for third-party developers who aren't
#   deeply embedded in the provider's own conventions.


# ============================================================================
# CASE STUDY 4 — RATE LIMITING STRATEGY FOR AN API WITH BOTH BURSTY AND
# STEADY-STATE CONSUMERS
# ============================================================================
#
# SETUP: some API consumers make requests in occasional bursts (a batch
# job running once an hour), others make steady, evenly-distributed
# requests -- deciding on a rate-limiting algorithm (L08).
#
# ------------------------------------------------------------------------
# APPROACH A: Fixed window counting (e.g. "max 1000 requests per
# calendar minute") (L08)
# ------------------------------------------------------------------------
#   WHY VALID: per L08, the simplest rate-limiting algorithm to
#   implement and reason about -- a counter that resets at fixed
#   intervals.
#   COST: per L08, fixed windows have a well-documented boundary problem
#   -- a consumer can send 1000 requests in the LAST second of one
#   window and another 1000 in the FIRST second of the next window,
#   effectively bursting 2000 requests in ~1 second while technically
#   staying within the "1000/minute" limit at each individual window
#   boundary -- a real, exploitable gap for exactly the bursty consumer
#   pattern this case study describes.
#
# ------------------------------------------------------------------------
# APPROACH B: Sliding window log or sliding window counter (L08)
# ------------------------------------------------------------------------
#   WHY VALID: per L08, this directly fixes A's boundary-burst problem
#   by considering a continuously-moving window rather than fixed,
#   resetting intervals -- a consumer genuinely cannot exceed the true
#   rate limit by timing requests around a window boundary.
#   COST: per L08, sliding window log (storing every request timestamp)
#   has real memory cost proportional to request volume within the
#   window; sliding window counter (an approximation) trades some
#   precision for lower memory cost -- either way, this is more
#   implementation/storage complexity than A's simple counter.
#
# ------------------------------------------------------------------------
# APPROACH C: Token bucket (L08) -- a bucket refills at a steady rate,
# each request consumes a token, requests are allowed as long as tokens
# are available, letting the bucket size (burst capacity) be tuned
# separately from the steady refill rate
# ------------------------------------------------------------------------
#   WHY VALID: per L08, token bucket is SPECIFICALLY well-suited to this
#   case study's exact stated need -- mixed bursty and steady-state
#   consumers -- because it has TWO independently tunable parameters:
#   the refill rate (steady-state throughput limit) and the bucket
#   capacity (how much burst above the steady rate is allowed before
#   throttling) -- a legitimate occasional burst (the hourly batch job)
#   can be explicitly accommodated by bucket size, while still enforcing
#   a genuine steady-state ceiling via the refill rate.
#   COST: per L08, requires understanding and correctly tuning TWO
#   parameters (rate and capacity) rather than B's single window/limit
#   value -- a real, if modest, added configuration complexity, and
#   choosing bucket capacity too generously can allow bursts large
#   enough to still cause real downstream load spikes despite the
#   overall rate being nominally "limited."
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Boundary-burst exploit risk | Explicitly accommodates legitimate bursts | Tuning complexity |
#   |----------|-----------------------------------|--------------------------------------------------|--------------------------|
#   | A: fixed window | Real | No (uniform limit only) | Lowest |
#   | B: sliding window | None | No (uniform limit only) | Medium |
#   | C: token bucket | None | Yes (separate burst/steady parameters) | Medium-high |
#   Given this case study's EXPLICIT mixed bursty/steady-state consumer
#   population, C is the strongest fit -- it's the only one of the three
#   that can accommodate the legitimate batch-job burst pattern by
#   design, rather than either allowing an exploitable gap (A) or
#   applying a uniform limit that doesn't distinguish burst tolerance
#   from steady-state rate (B).


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
