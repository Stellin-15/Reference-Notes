"""
WHAT: Four realistic full-stack problems, each solved with THREE
      genuinely different, individually defensible approaches drawn from
      L01-L10 -- with an explicit comparison table and reasoning for why
      each answer is valid under different constraints.
WHY:  "React or Vue," "REST or WebSocket for this feature," "Context or
      Redux" are all questions L01-L10 gave you real tools for, not one
      universal answer -- this lesson is about the decision process
      under real product and team constraints.
LEVEL: Capstone -- read after L01-L10.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L10's concepts.
"""

# ============================================================================
# CASE STUDY 1 — STATE MANAGEMENT FOR A GROWING REACT APPLICATION
# ============================================================================
#
# SETUP: a React app started small with `useState`/Context, but has
# grown to the point where prop-drilling and Context re-render
# performance are becoming real problems across a dozen+ components.
#
# ------------------------------------------------------------------------
# APPROACH A: Keep using Context API, but split it into MULTIPLE, more
# granular contexts (L02) rather than one large global context
# ------------------------------------------------------------------------
#   WHY VALID: per L02, Context's main performance problem is that ANY
#   consumer re-renders when ANY value in that context changes --
#   splitting one large context into several smaller, more focused ones
#   (e.g. separate UserContext, ThemeContext, CartContext) directly
#   addresses this by letting components subscribe only to the specific
#   slice of state they actually need, without adopting a new
#   dependency at all.
#   COST: per L02, this doesn't solve Context's OTHER limitation --
#   it's still not well-suited to very frequently-changing state (e.g.
#   state updated on every keystroke or every animation frame) even
#   when split finely, and managing many separate context providers/
#   consumers can itself become its own source of boilerplate and
#   structural complexity as the number of contexts grows.
#
# ------------------------------------------------------------------------
# APPROACH B: Adopt Zustand (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, Zustand provides fine-grained subscriptions
#   (components only re-render when the SPECIFIC piece of state they
#   read changes, regardless of how the store is structured) with
#   dramatically less boilerplate than Redux -- a strong middle ground
#   for a team that has genuinely outgrown Context's performance
#   characteristics but doesn't want Redux's full ceremony.
#   COST: per L02, adds a new dependency and a new state-management
#   pattern the team needs to learn -- a real, if generally modest,
#   adoption cost, and (compared to Redux) a less extensive ecosystem
#   of devtools/middleware for very large, complex applications with
#   deep debugging/time-travel needs.
#
# ------------------------------------------------------------------------
# APPROACH C: Adopt Redux (with Redux Toolkit) (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, Redux's strict unidirectional data flow, mature
#   devtools (time-travel debugging, detailed action/state history), and
#   large ecosystem make it the strongest choice for a GENUINELY large,
#   complex application where predictable, debuggable state transitions
#   and a large team's shared conventions matter -- especially valuable
#   when many developers touch the same state logic.
#   COST: per L02, even with Redux Toolkit's boilerplate reduction, this
#   remains the heaviest-weight of the three options -- real ceremony
#   (actions, reducers, the store setup) that's genuine overkill for an
#   application that isn't ACTUALLY at the scale/team-size where Redux's
#   strict structure pays for itself.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Migration effort from current Context setup | Performance at scale | Ecosystem/devtools maturity |
#   |----------|----------------------------------------------------|----------------------------|------------------------------------|
#   | A: split Context more granularly | Lowest | Good, with effort | N/A (native React) |
#   | B: Zustand | Medium | Best-in-class, minimal ceremony | Good, growing |
#   | C: Redux Toolkit | Highest | Best-in-class | Most mature |
#   A is worth trying first as the lowest-effort fix -- per L02's own
#   "escalating only as needed" philosophy, only reach for B once A's
#   limits are actually hit, and only reach for C once the team/app
#   scale genuinely justifies its ceremony, not by default.


# ============================================================================
# CASE STUDY 2 — REAL-TIME UPDATES FOR A COLLABORATIVE FEATURE (E.G. A
# SHARED TASK BOARD)
# ============================================================================
#
# SETUP: multiple users need to see each other's changes to a shared task
# board in near-real-time.
#
# ------------------------------------------------------------------------
# APPROACH A: Polling -- the frontend re-fetches the board's state via a
# normal REST GET request every few seconds (L08)
# ------------------------------------------------------------------------
#   WHY VALID: per L08, the simplest possible implementation -- no new
#   backend infrastructure or connection-management logic needed, just
#   a `setInterval` and a normal REST call, genuinely adequate if the
#   "near-real-time" requirement tolerates a few seconds of staleness
#   and the number of concurrent users is modest.
#   COST: per L08, polling wastes real requests/bandwidth on checks that
#   usually find NOTHING has changed, and inherently has WORSE
#   perceived latency than a push-based mechanism (a change is only seen
#   at the NEXT poll interval, not immediately) -- both a real
#   efficiency cost and a real UX cost that grows with more concurrent
#   users and a tighter freshness expectation.
#
# ------------------------------------------------------------------------
# APPROACH B: WebSockets (L06, L08) -- a persistent connection, server
# pushes updates the instant they happen
# ------------------------------------------------------------------------
#   WHY VALID: per L06/L08, this directly solves A's staleness and
#   waste problems -- updates arrive the moment they happen, with no
#   wasted polling requests, the standard answer for genuinely
#   real-time, bidirectional collaborative features.
#   COST: per L06/L08, requires real connection-management complexity --
#   handling reconnection on network drops, connection-manager/pub-sub
#   fan-out infrastructure on the backend to broadcast updates to all
#   connected clients, and (per L06) careful backpressure handling if
#   updates can arrive faster than a slow client can consume them -- a
#   meaningfully larger implementation surface than A.
#
# ------------------------------------------------------------------------
# APPROACH C: Server-Sent Events (SSE) (L08) -- a simpler, one-directional
# (server-to-client only) persistent connection
# ------------------------------------------------------------------------
#   WHY VALID: per L08, if the ACTUAL data flow is one-directional (the
#   server pushes board updates to clients, but clients still submit
#   their OWN changes via ordinary REST POST/PUT requests, not over the
#   same channel), SSE provides much of WebSocket's real-time push
#   benefit with a simpler protocol/implementation, built on standard
#   HTTP rather than a separate WebSocket handshake/protocol.
#   COST: per L08, SSE is fundamentally one-directional -- if the
#   feature later needs genuinely bidirectional real-time communication
#   over the SAME channel (e.g. cursor-position sharing needing very
#   low-latency client-to-server AND server-to-client flow), SSE alone
#   doesn't provide that, and the team would need WebSockets (B) anyway
#   for that specific need.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Update latency | Backend complexity | Fits pure server-push vs bidirectional need |
#   |----------|---------------------|--------------------------|------------------------------------------------------|
#   | A: polling | Worst (interval-bound) | Lowest | Either (doesn't matter, it's just fetch) |
#   | B: WebSockets | Best | Highest | Bidirectional |
#   | C: SSE | Best (server-to-client) | Medium | Server-push only |
#   For a task board where users submit changes via ordinary form
#   actions but need to SEE others' changes live, C is often the
#   simplest sufficient answer; B becomes necessary once the feature
#   genuinely needs low-latency bidirectional flow over one channel
#   (e.g. live cursors, as in System Design Case Studies Notes' Google
#   Docs presence lessons).


# ============================================================================
# CASE STUDY 3 — CHOOSING A DATA MODEL FOR A PRODUCT CATALOG (MONGODB
# VS. A RELATIONAL APPROACH)
# ============================================================================
#
# SETUP: a product catalog with varying attributes per category (echoing
# NoSQL & Specialized Databases Notes' Case Study 3, now specifically
# from a MongoDB-vs-relational framing per L06).
#
# ------------------------------------------------------------------------
# APPROACH A: MongoDB, embedding all product attributes as nested
# documents (L06)
# ------------------------------------------------------------------------
#   WHY VALID: per L06, MongoDB's document model naturally accommodates
#   varying per-category attribute sets without a rigid schema, and
#   EMBEDDING related data (e.g. reviews embedded within a product
#   document) means a single query retrieves everything needed for a
#   product page, avoiding joins entirely for the common read pattern.
#   COST: per L06, embedding works well for data with a natural
#   "belongs to and is read together with" relationship, but for data
#   that's genuinely reused/referenced across many products (e.g. a
#   shared brand or manufacturer entity), embedding duplicates that data
#   across every product document, creating real update-consistency
#   challenges if that shared data changes.
#
# ------------------------------------------------------------------------
# APPROACH B: MongoDB, but using REFERENCES (not embedding) for shared/
# reused entities, embedding only truly product-specific varying
# attributes (L06)
# ------------------------------------------------------------------------
#   WHY VALID: per L06's embedding-vs-referencing framework, this
#   directly addresses A's shared-data duplication problem -- reference
#   genuinely shared entities (brand, manufacturer) while still
#   embedding the category-varying attributes that benefit from
#   MongoDB's flexible schema, a more nuanced application of the same
#   underlying database.
#   COST: referenced data requires an additional query (or MongoDB's
#   `$lookup` aggregation, effectively a join) to retrieve -- some of
#   the "one query gets everything" simplicity A provided is given up
#   specifically for the referenced portions, a real complexity/
#   performance tradeoff traded for consistency correctness.
#
# ------------------------------------------------------------------------
# APPROACH C: A relational database with a JSONB column for the varying
# attributes (directly matching SQL Notes/NoSQL Notes' own case studies
# on this exact tradeoff)
# ------------------------------------------------------------------------
#   WHY VALID: gets strong relational integrity/typing for the STABLE,
#   well-structured parts of the catalog (products, brands, categories,
#   with real foreign keys) while still accommodating category-varying
#   attributes via JSONB -- appropriate specifically if the REST of the
#   application's data is already relational, avoiding introducing
#   MongoDB as an entirely separate system just for the catalog.
#   COST: as established in SQL/NoSQL Notes' own case studies, JSONB
#   loses some of the type-safety a fully-typed relational schema (or,
#   differently, a fully-embracing document model) would provide, and
#   if the REST of the application isn't already relational, introducing
#   a relational database purely for this feature is its own new-system
#   cost, symmetric to A/B's "introduce MongoDB" cost.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Handles varying attributes | Handles shared/reused entities | Fits an existing relational app |
#   |----------|---------------------------------|--------------------------------------|--------------------------------------|
#   | A: MongoDB, full embedding | Best | Poor (duplication) | No (new system) |
#   | B: MongoDB, embed + reference appropriately | Best | Good | No (new system) |
#   | C: relational + JSONB | Good | Best (native FKs) | Yes |
#   If the broader application is already relational, C avoids
#   introducing a second database system for one feature; if the app is
#   already MongoDB-based (or catalog-heavy enough to justify a
#   dedicated document store), B is the correct, nuanced application of
#   the document model rather than A's simpler-but-flawed full-embedding
#   default.


# ============================================================================
# CASE STUDY 4 — BUILDING THE FRONTEND FOR AN AI CHAT FEATURE WITH
# STREAMING RESPONSES
# ============================================================================
#
# SETUP: an AI chat UI (L09) needs to display streaming token-by-token
# responses, show tool-call activity, and handle the case where a
# response takes a long time or fails partway through.
#
# ------------------------------------------------------------------------
# APPROACH A: Wait for the full response, then render it all at once
# (no streaming UI)
# ------------------------------------------------------------------------
#   WHY VALID: per L09, dramatically simpler frontend state management
#   -- no partial-response state to track, no need to handle mid-stream
#   errors differently from complete-request errors, genuinely
#   appropriate for a use case where response latency is consistently
#   low enough that streaming's UX benefit wouldn't be noticeable anyway.
#   COST: per L09, for LLM responses that can take several seconds
#   (LLM Core Theory Notes L06's inference-latency discussion), users
#   stare at a blank/loading state the whole time with no incremental
#   feedback -- a well-documented, real UX regression relative to
#   streaming, especially for longer responses.
#
# ------------------------------------------------------------------------
# APPROACH B: Stream tokens via SSE or a streaming fetch response,
# rendering incrementally as they arrive (L09)
# ------------------------------------------------------------------------
#   WHY VALID: per L09, this is the now-standard UX pattern for AI chat
#   -- users see the response forming progressively, a much better
#   perceived-latency experience, and per L09's "optimistic updates"
#   discussion, the UI can also optimistically show the user's OWN
#   message immediately while the response streams in.
#   COST: per L09, requires real, careful frontend state management for
#   partial responses -- correctly handling a stream that errors out
#   PARTWAY through (showing what was received so far, plus a clear
#   error indicator, rather than either silently dropping the partial
#   content or crashing), and displaying tool-call activity (per L09's
#   agent-tool-call-display discussion) interleaved with streaming text
#   is genuinely more complex UI state to model than A's single
#   request/response cycle.
#
# ------------------------------------------------------------------------
# APPROACH C: B, plus explicit RESUMABILITY -- if the connection drops
# mid-stream, the frontend can reconnect and resume displaying the
# response from where it left off (rather than losing the partial
# response or restarting the whole request), relying on the backend
# persisting stream state (L09's response-state-modeling discussion)
# ------------------------------------------------------------------------
#   WHY VALID: per L09, directly addresses B's real gap -- a dropped
#   connection mid-stream (a genuinely common occurrence on mobile
#   networks specifically) shouldn't mean losing a long, expensive-to-
#   generate response entirely; resumability preserves both the user's
#   experience and the compute cost already spent generating the
#   partial response.
#   COST: requires real BACKEND infrastructure to persist in-progress
#   stream state (not just a frontend concern) -- meaningfully more
#   engineering investment than B alone, justified specifically once
#   response length/cost and connection-reliability concerns (e.g. a
#   primarily mobile user base) make this resumability genuinely
#   valuable rather than a nice-to-have.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Perceived latency | Frontend state complexity | Resilience to dropped connections |
#   |----------|------------------------|---------------------------------|-------------------------------------------|
#   | A: no streaming | Worst | Lowest | N/A (simple retry of the whole request) |
#   | B: streaming, no resumability | Best | Medium-high | Poor (loses partial response) |
#   | C: streaming + resumability | Best | Highest | Best |
#   B is the strong standard default for a modern AI chat UI; C is
#   worth the added backend investment specifically for a user base
#   with meaningfully unreliable connectivity or long/expensive
#   responses where losing partial progress is a real, recurring cost.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
