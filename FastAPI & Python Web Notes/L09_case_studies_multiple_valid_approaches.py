"""
WHAT: Four realistic production Python web-service problems, each solved
      with THREE genuinely different, individually defensible approaches
      drawn from L01-L08 -- with an explicit comparison table and
      reasoning for why each answer is valid under different
      constraints.
WHY:  "Sync or async," "background task or a real queue," "how to
      structure auth" are all questions L01-L08 gave you real tools for,
      not one universal answer -- this lesson is about the decision
      process under real latency and reliability constraints.
LEVEL: Capstone -- read after L01-L08.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L08's concepts.
"""

# ============================================================================
# CASE STUDY 1 — HANDLING A SLOW, EXTERNAL API CALL WITHIN A REQUEST
# HANDLER
# ============================================================================
#
# SETUP: an endpoint needs to call a third-party API that takes 2-5
# seconds to respond, as part of fulfilling the user's request.
#
# ------------------------------------------------------------------------
# APPROACH A: Call it synchronously, `await`ed directly in the async
# endpoint handler (L01, L03)
# ------------------------------------------------------------------------
#   WHY VALID: per L01/L03, if the user's request GENUINELY needs the
#   third-party API's result before a meaningful response can be
#   returned (the API call's result is directly part of what the client
#   needs back), this is simply the correct, honest shape of the
#   request -- and per L03's async discussion, using an async HTTP
#   client means the server can still handle OTHER requests concurrently
#   while waiting, not blocking the whole process during those 2-5
#   seconds.
#   COST: the CLIENT still waits the full 2-5 seconds for a response --
#   for a user-facing feature, this is a real, direct latency cost
#   users experience, regardless of how efficiently the server handles
#   concurrency internally.
#
# ------------------------------------------------------------------------
# APPROACH B: Kick off the API call as a FastAPI BackgroundTask (L07)
# after immediately returning a response to the client
# ------------------------------------------------------------------------
#   WHY VALID: per L07, this gets the client an immediate response,
#   directly solving A's latency problem -- appropriate specifically
#   when the third-party API call's RESULT doesn't need to be part of
#   the immediate response at all (e.g. "send a confirmation email" or
#   "log this event to an analytics service" -- fire-and-forget work).
#   COST: per L07, BackgroundTasks run WITHIN the same server process,
#   with NO retry mechanism, no persistence if the process crashes
#   mid-task, and no visibility into whether the task actually
#   succeeded -- genuinely inappropriate if the third-party call's
#   result actually needs to reach the user (this case study's
#   framing, if the user needs the API's result, immediately
#   disqualifies this approach) or if task reliability matters at all.
#
# ------------------------------------------------------------------------
# APPROACH C: Return an immediate "processing" response with a job ID,
# perform the API call via a REAL task queue (e.g. Celery, or a
# dedicated worker service), and let the client POLL or receive a
# WebSocket/webhook notification when the result is ready (L06's
# WebSocket discussion, combined with L07's background-task limitations)
# ------------------------------------------------------------------------
#   WHY VALID: directly addresses BOTH A's latency problem and B's
#   reliability gap -- a real task queue provides retries, persistence
#   across process restarts, and observability into task status, while
#   still giving the client an immediate initial response; the
#   WebSocket/polling mechanism (L06) lets the client eventually GET the
#   result once ready, unlike B's fire-and-forget approach.
#   COST: significantly more infrastructure and architectural complexity
#   than A or B -- a real task queue system to operate, plus either
#   polling logic or a WebSocket connection to manage on both client and
#   server, appropriate specifically when the result DOES matter to the
#   user AND genuine reliability/retry guarantees are needed, not for
#   every slow-API-call situation.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Client latency | Reliability if it fails mid-call | Fits "user needs the result" |
#   |----------|---------------------|-----------------------------------------|--------------------------------------|
#   | A: await directly | Full 2-5s | Good (request fails visibly, can be retried by client) | Yes |
#   | B: BackgroundTask | Immediate | Poor (silent failure, no retry) | No |
#   | C: task queue + poll/WebSocket | Immediate | Good (retries, persistence) | Yes |
#   If the result must reach the user, choose between A (simpler, user
#   waits) and C (more complex, user doesn't wait) based on how
#   latency-sensitive the feature genuinely is; B is only correct when
#   the API call's outcome truly doesn't need to reach the user at all.


# ============================================================================
# CASE STUDY 2 — STRUCTURING AUTHENTICATION FOR AN API SERVING BOTH A
# WEB FRONTEND AND THIRD-PARTY DEVELOPER INTEGRATIONS
# ============================================================================
#
# SETUP: the same API needs to authenticate first-party web-app users
# (via login) AND third-party developers building integrations against
# a public API.
#
# ------------------------------------------------------------------------
# APPROACH A: JWT-based session auth for everyone, including third-party
# developers (L04)
# ------------------------------------------------------------------------
#   WHY VALID: per L04, one consistent authentication mechanism across
#   the whole API is simpler to build and document than supporting
#   multiple schemes -- for a small number of trusted third-party
#   integrations, issuing them long-lived JWTs isn't unreasonable.
#   COST: per L04, JWTs are typically designed around a LOGIN flow (a
#   human authenticating with credentials, receiving a session token) --
#   this is an awkward fit for programmatic, third-party API access,
#   which conventionally expects a simpler API-key model, and JWT
#   refresh/expiry semantics designed for a browser session don't map
#   cleanly onto a long-running server-to-server integration.
#
# ------------------------------------------------------------------------
# APPROACH B: API keys for third-party developers, JWT/session auth for
# the first-party web frontend -- two separate auth mechanisms (L04)
# ------------------------------------------------------------------------
#   WHY VALID: per L04, this matches each auth mechanism to its actual
#   USE CASE -- JWTs suit the human-login, browser-session pattern well;
#   API keys suit programmatic, server-to-server access well (simple to
#   generate, revoke, and rate-limit per key) -- the standard, well-
#   established pattern most public APIs with both consumer types
#   actually use.
#   COST: genuinely more implementation complexity than A -- two
#   separate authentication code paths to build, test, and maintain
#   (key generation/validation/revocation UI for API keys, alongside the
#   JWT session flow), and the API's authorization/middleware logic
#   needs to correctly handle both.
#
# ------------------------------------------------------------------------
# APPROACH C: OAuth2 with different grant types for each use case (L04)
# -- Authorization Code flow for the web frontend, Client Credentials
# flow for third-party server-to-server integrations
# ------------------------------------------------------------------------
#   WHY VALID: per L04's OAuth2PasswordBearer discussion extended to
#   full OAuth2, this is the INDUSTRY-STANDARD approach for exactly this
#   dual use case, with well-documented, widely-understood semantics
#   third-party developers are likely already familiar with from other
#   APIs -- also naturally extends to supporting THIRD-PARTY-BUILT
#   applications acting on behalf of a USER (not just server-to-server),
#   a capability neither A nor B directly provides.
#   COST: meaningfully more complex to implement correctly than B's
#   simpler API-key model -- OAuth2's various grant types, token refresh
#   flows, and scope management represent real additional engineering
#   and security-review surface, justified specifically if the API
#   genuinely needs to support third-party apps acting on behalf of
#   individual end users, not just simple server-to-server access.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Implementation complexity | Fits programmatic third-party access | Supports "acting on behalf of a user" |
#   |----------|--------------------------------|--------------------------------------------|-----------------------------------------------|
#   | A: JWT for everyone | Lowest | Poorly | No (not naturally) |
#   | B: JWT + separate API keys | Medium | Well | No |
#   | C: OAuth2 with multiple grant types | Highest | Well | Yes |
#   B is the right-sized answer if third-party integrations are purely
#   server-to-server; C is justified specifically once the product needs
#   third-party apps to act on behalf of individual end users (e.g. "log
#   in with our platform" style integrations), a genuinely different
#   requirement B doesn't address.


# ============================================================================
# CASE STUDY 3 — DATABASE CONNECTION STRATEGY UNDER A TRAFFIC SPIKE
# ============================================================================
#
# SETUP: an API's traffic occasionally spikes to 5x normal load; the
# team observes database connection errors during these spikes.
#
# ------------------------------------------------------------------------
# APPROACH A: Increase the database connection pool size (L03)
# ------------------------------------------------------------------------
#   WHY VALID: per L03, if the pool is simply too SMALL for peak
#   concurrent demand, increasing it directly fixes the immediate
#   symptom -- the fastest, simplest fix to try first.
#   COST: per L03, the database server itself has a hard MAXIMUM
#   connection limit -- simply increasing the application's pool size
#   without checking this ceiling can just shift the failure from "pool
#   exhausted" to "database rejects new connections outright" once
#   enough application instances (each with their own enlarged pool) are
#   running, especially in a horizontally-scaled deployment with
#   multiple app instances each holding their own pool.
#
# ------------------------------------------------------------------------
# APPROACH B: Add PgBouncer (or an equivalent connection pooler) between
# the application and the database (SQL Notes, adjacent to L03)
# ------------------------------------------------------------------------
#   WHY VALID: a connection pooler multiplexes many application-level
#   "logical" connections onto a smaller number of ACTUAL database
#   connections -- directly addresses A's ceiling problem by decoupling
#   application-side concurrency from the database's real connection
#   limit, letting many more concurrent REQUESTS be served without a
#   proportional increase in actual database connections.
#   COST: adds a new piece of infrastructure to deploy, configure, and
#   monitor, and (depending on the pooling mode, e.g. transaction-level
#   vs. session-level pooling) can have subtle interaction effects with
#   application code relying on session-level Postgres features (e.g.
#   session-scoped temporary tables, certain prepared-statement caching
#   behaviors) that need to be understood and accounted for.
#
# ------------------------------------------------------------------------
# APPROACH C: Add rate limiting / a request queue at the application
# layer during spikes, rather than trying to serve ALL spike traffic at
# full database-connection concurrency
# ------------------------------------------------------------------------
#   WHY VALID: reframes the problem -- rather than trying to scale
#   database connection capacity to match ANY possible spike (A, B), this
#   accepts that some requests during a genuine spike may need to WAIT
#   briefly or be gracefully rejected/queued, trading a controlled,
#   predictable degradation (some requests queued/delayed) for
#   protection against the database being overwhelmed entirely -- often
#   the more resilient overall system behavior under genuinely
#   unpredictable spike severity.
#   COST: requires the PRODUCT to accept that some requests during a
#   spike get queued/delayed/rejected rather than served immediately at
#   full capacity -- a real user-experience tradeoff that needs
#   explicit product buy-in, not purely a backend engineering decision
#   to make unilaterally.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Fixes the immediate symptom | Scales to arbitrarily large spikes | Requires product/UX tradeoff |
#   |----------|-----------------------------------|-------------------------------------------|------------------------------------|
#   | A: bigger connection pool | Partially, until DB's own limit | No (hits DB's hard ceiling) | No |
#   | B: connection pooler (PgBouncer) | Yes, more robustly | Better, but still finite | No |
#   | C: rate limiting/queueing | Yes, via graceful degradation | Yes (bounded, predictable) | Yes |
#   B is the standard, strong architectural fix for genuine connection-
#   exhaustion problems; C is the right ADDITIONAL layer specifically
#   once spike severity is genuinely unpredictable/unbounded, since no
#   amount of connection-pool tuning alone can protect against an
#   arbitrarily large spike.


# ============================================================================
# CASE STUDY 4 — TESTING AN ENDPOINT THAT DEPENDS ON THE CURRENT TIME
# ============================================================================
#
# SETUP: an endpoint's behavior depends on the current date/time (e.g. a
# subscription-expiration check) -- the team needs reliable, repeatable
# tests for this time-dependent logic.
#
# ------------------------------------------------------------------------
# APPROACH A: Test using the REAL current time (`datetime.now()`
# directly in both the endpoint and the test) (L05)
# ------------------------------------------------------------------------
#   WHY VALID: no special test infrastructure needed -- the test simply
#   runs and checks behavior "as of whenever it happens to run," the
#   lowest-effort option to write initially.
#   COST: per L05's testing discussion (and Testing & QA Engineering
#   Notes L07's test-data-management lesson), this makes tests
#   inherently FLAKY/order-dependent around time boundaries -- a test
#   checking "expires in 3 days" behavior can pass today and silently
#   fail months later purely because real time passed, or fail
#   intermittently near a date boundary the test author didn't account
#   for, a well-documented, avoidable source of flaky tests.
#
# ------------------------------------------------------------------------
# APPROACH B: Inject the current time as an explicit DEPENDENCY (L02's
# `Depends()` pattern) rather than calling `datetime.now()` directly
# inside the endpoint, overridden in tests via FastAPI's dependency-
# override mechanism (L05)
# ------------------------------------------------------------------------
#   WHY VALID: per L02/L05, this directly fixes A's flakiness -- tests
#   can inject any SPECIFIC, fixed time value they want (e.g. "test
#   exactly at the expiration boundary," "test one second before/after"),
#   making time-dependent tests fully deterministic and repeatable
#   regardless of when they actually run, using FastAPI's own dependency-
#   injection machinery the team is already using for other purposes.
#   COST: requires refactoring the endpoint's code to accept time as an
#   injected dependency rather than calling `datetime.now()` directly --
#   a real, if usually small, code change, and every NEW piece of time-
#   dependent logic added later must remember to follow the same pattern
#   or the flakiness risk (A) creeps back in for that new code.
#
# ------------------------------------------------------------------------
# APPROACH C: Use a time-mocking library (e.g. `freezegun` or
# `time-machine`) to globally freeze/control time during specific tests,
# without needing to refactor the endpoint's code at all
# ------------------------------------------------------------------------
#   WHY VALID: gets B's deterministic-testing benefit WITHOUT requiring
#   the endpoint code itself to be refactored into a dependency-
#   injection pattern -- appropriate when the codebase has many existing
#   call sites of `datetime.now()` that would be impractical to refactor
#   all at once, or for third-party code the team doesn't control that
#   also calls the real system clock.
#   COST: relies on a library that monkey-patches/intercepts the SYSTEM
#   clock globally during the test -- a real, if usually reliable,
#   "magic" mechanism that can occasionally interact unexpectedly with
#   other time-sensitive code running during the same test (timeouts,
#   background schedulers, certain C-extension code that reads time via
#   a path the mocking library doesn't intercept), a genuinely different
#   and sometimes subtler class of risk than B's explicit, structural
#   fix.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Test determinism | Code changes required | Risk of unexpected interactions |
#   |----------|------------------------|------------------------------|------------------------------------------|
#   | A: real current time | Poor (flaky) | None | N/A |
#   | B: dependency-injected time | Best | Real (refactor endpoints) | Lowest (explicit, structural) |
#   | C: time-mocking library | Best | None | Real, if less common |
#   B is the architecturally cleaner, more explicit long-term answer,
#   especially for NEW code; C is the pragmatic choice for retrofitting
#   determinism onto a large EXISTING codebase without a full refactor,
#   accepting its different (usually smaller, but real) risk profile.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
