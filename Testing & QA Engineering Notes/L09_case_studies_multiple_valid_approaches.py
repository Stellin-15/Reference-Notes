"""
WHAT: Four realistic testing-strategy problems, each solved with THREE
      genuinely different, individually defensible approaches drawn from
      L01-L08 -- with an explicit comparison table and reasoning for why
      each answer is valid under different constraints. Distinct from
      L08's capstone (one complete layered test strategy) -- this lesson
      is about the decision process across competing options for a
      single problem, not one worked build.
WHY:  "Mock it or use a real dependency," "how much E2E coverage is
      enough," "is this flaky test worth fixing or deleting" are all
      questions L01-L08 gave you real tools for, not one universal
      answer -- this lesson is about choosing under real constraints.
LEVEL: Capstone -- read after L01-L08.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L08's concepts.
"""

# ============================================================================
# CASE STUDY 1 — TESTING A SERVICE THAT CALLS A THIRD-PARTY PAYMENT API
# ============================================================================
#
# SETUP: a checkout service calls a third-party payment provider's API;
# the team needs confidence the integration works correctly without
# making real charges during test runs or depending on the provider's
# uptime for CI to pass.
#
# ------------------------------------------------------------------------
# APPROACH A: Mock the payment API client entirely (L02) -- unit tests
# stub out the HTTP client, asserting the service calls it with the
# right parameters
# ------------------------------------------------------------------------
#   WHY VALID: per L02, mocks are fast, fully deterministic, and require
#   no network access at all -- CI runs are quick and never flake due to
#   the third party's availability, and this is the right tool for
#   testing the SERVICE's own logic (does it call the payment API
#   correctly given various internal states) in isolation.
#   COST: per L02's mock-vs-real distinction, a mock only verifies the
#   service calls the client the way the TEST AUTHOR believes the real
#   API works -- if the mock's assumed request/response shape drifts
#   from the ACTUAL provider API (a real API change, or a
#   misunderstanding baked into the mock from the start), every test
#   using that mock keeps passing while the real integration is
#   silently broken -- mocks can't catch integration-CONTRACT drift by
#   construction.
#
# ------------------------------------------------------------------------
# APPROACH B: Integration tests against the payment provider's official
# SANDBOX/test environment (L03)
# ------------------------------------------------------------------------
#   WHY VALID: per L03, testing against a real (if sandboxed) instance
#   of the actual API directly catches integration-contract drift that
#   mocks structurally can't -- if the provider changes their API, sandbox
#   tests fail for the RIGHT reason, unlike mocks which would keep
#   passing regardless.
#   COST: introduces a real network dependency into CI -- the sandbox
#   environment's uptime/latency now directly affects CI reliability and
#   speed, and per L03's discussion, SOME third-party sandboxes are
#   themselves less reliable/available than production, occasionally
#   causing test flakiness that has NOTHING to do with the team's own
#   code being broken.
#
# ------------------------------------------------------------------------
# APPROACH C: Consumer-driven contract testing (L05) -- the checkout
# service's test suite defines an explicit CONTRACT of expected request/
# response shapes, verified independently against the provider (or a
# contract-testing broker) without needing a live sandbox call in the
# team's own CI run
# ------------------------------------------------------------------------
#   WHY VALID: per L05, this is specifically designed to solve A and B's
#   respective gaps simultaneously -- it catches contract drift (unlike
#   pure mocking) WITHOUT requiring a live network call to a third
#   party's sandbox on every CI run (unlike B), by verifying the
#   contract independently/asynchronously.
#   COST: per L05, consumer-driven contract testing works best when the
#   PROVIDER also participates in the contract-verification process
#   (running provider-side verification against the same contract) --
#   for a THIRD-PARTY payment provider who almost certainly doesn't
#   participate in your team's specific contract-testing setup, this
#   pattern's full benefit is hard to realize; contract testing is most
#   powerful between services BOTH sides control, which a third-party
#   integration explicitly isn't.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Catches API contract drift | CI speed/reliability | Requires provider cooperation |
#   |----------|---------------------------------|----------------------------|-------------------------------------|
#   | A: full mocking | No | Best | No |
#   | B: sandbox integration tests | Yes | Worse (network-dependent) | No (just needs sandbox access) |
#   | C: consumer-driven contracts | Partially (self-verified only) | Good | Ideally yes, rarely available for 3rd parties |
#   For a genuinely third-party, non-cooperating provider, B run on a
#   SEPARATE, less-frequent schedule (not blocking every PR, but running
#   regularly, e.g. nightly) combined with A for fast per-PR feedback is
#   the standard, pragmatic answer -- getting mocking's speed for daily
#   development while still catching real drift on a reasonable cadence.


# ============================================================================
# CASE STUDY 2 — A CONSISTENTLY FLAKY E2E TEST THAT'S BEEN DISABLED FOR
# THREE MONTHS
# ============================================================================
#
# SETUP: a critical checkout-flow E2E test (L04) has been failing
# intermittently (~15% of runs) for months; it was disabled to stop
# blocking merges, and the team hasn't revisited it since.
#
# ------------------------------------------------------------------------
# APPROACH A: Delete the test entirely
# ------------------------------------------------------------------------
#   WHY VALID: per L07's flaky-test discussion, a disabled test that
#   nobody is actively fixing provides ZERO actual value while creating
#   a false sense of security (its presence in the test suite's file
#   listing implies coverage that doesn't actually exist) -- if there's
#   genuinely no near-term plan to fix it, an honest test suite that
#   doesn't claim coverage it doesn't have is arguably better than a
#   disabled test lying by omission.
#   COST: the checkout flow (explicitly called "critical" in this case
#   study's setup) now has NO E2E coverage at all -- a real regression
#   in test coverage for exactly the flow that most needs it, trading
#   "honest about the gap" for "actively worse off."
#
# ------------------------------------------------------------------------
# APPROACH B: Root-cause and fix the actual flakiness (L07's systematic
# flaky-test diagnosis) -- identify whether it's a race condition, a
# shared-state/ordering issue, or an environmental problem, and fix that
# specific cause
# ------------------------------------------------------------------------
#   WHY VALID: per L07, this is the only approach that actually restores
#   the critical flow's real E2E coverage rather than accepting a gap or
#   working around it -- the correct answer if the test's flakiness has
#   a genuinely findable, fixable root cause (a race condition in the
#   test itself, an unreliable test-data setup) rather than being
#   symptomatic of a deeper, harder problem.
#   COST: flaky-test root-causing can be genuinely time-consuming and
#   sometimes inconclusive -- per L07, some flakiness stems from
#   legitimately hard-to-reproduce timing issues in the APPLICATION
#   itself (not just the test), and three months of the test being
#   disabled means the team is starting this investigation with zero
#   fresh context on what might have changed when the flakiness first
#   appeared, a real, avoidable cost of having let it sit disabled so
#   long.
#
# ------------------------------------------------------------------------
# APPROACH C: Replace the flaky E2E test with a combination of a more
# reliable, narrower integration test (L03) covering the same critical
# path's core logic, PLUS synthetic production monitoring (a scheduled
# "canary" checkout performed against production itself)
# ------------------------------------------------------------------------
#   WHY VALID: per L03's testing-pyramid principle, E2E tests are
#   INHERENTLY the most flake-prone tier (many moving parts: browser
#   automation, network, timing) -- if the checkout flow's core LOGIC
#   can be covered by a narrower, more reliable integration test, and
#   the "does the full real flow actually work in production RIGHT NOW"
#   question is covered by synthetic monitoring instead, this may
#   provide comparable real-world confidence with dramatically less
#   flakiness than a full browser-automation E2E test.
#   COST: synthetic production monitoring and a narrower integration
#   test genuinely don't test the EXACT same thing a full E2E test
#   does (e.g. actual frontend JavaScript behavior, real browser
#   rendering issues) -- some classes of bugs a true E2E test would
#   catch (a frontend-only regression that doesn't touch backend logic
#   at all) could slip through this combination undetected.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Restores real coverage | Effort required | Addresses root cause |
#   |----------|------------------------------|----------------------|----------------------------|
#   | A: delete | No | Lowest | No |
#   | B: root-cause and fix | Yes, fully | Highest, uncertain | Yes |
#   | C: replace with narrower tests + monitoring | Partially, differently | Medium | Sidesteps rather than fixes |
#   For a genuinely CRITICAL flow (as stated), A alone is not
#   acceptable; B is the ideal outcome if the root cause is tractable;
#   C is a reasonable, pragmatic fallback specifically when E2E
#   flakiness has resisted fixing and the team needs SOME real coverage
#   restored sooner rather than continuing to invest in an
#   unfixable-so-far test.


# ============================================================================
# CASE STUDY 3 — TEST DATA STRATEGY FOR A GROWING INTEGRATION TEST SUITE
# ============================================================================
#
# SETUP: integration tests (L03) increasingly interfere with each other
# — tests that create/modify database rows sometimes see leftover data
# from a previous test run, causing intermittent, hard-to-reproduce
# failures.
#
# ------------------------------------------------------------------------
# APPROACH A: Wrap each test in a database transaction, rolled back at
# the end (L07's test-data-management discussion)
# ------------------------------------------------------------------------
#   WHY VALID: per L07, this is a well-established, low-overhead pattern
#   -- each test's changes are automatically and completely undone,
#   guaranteeing no leakage between tests regardless of what any
#   individual test does, without needing explicit per-test cleanup code.
#   COST: doesn't work cleanly for tests that need to verify behavior
#   ACROSS transaction boundaries (e.g. testing that a background job
#   correctly picks up committed data, or testing genuine concurrent-
#   access scenarios) -- a real, structural limitation for any test that
#   specifically needs to exercise cross-transaction behavior, which a
#   rollback-based test can't accurately simulate.
#
# ------------------------------------------------------------------------
# APPROACH B: Explicit factory-generated, uniquely-namespaced test data
# per test (L07's test-factory pattern) — every test creates its OWN
# data with unique identifiers, no shared fixtures
# ------------------------------------------------------------------------
#   WHY VALID: per L07, unique per-test data eliminates cross-test
#   interference even for tests that DO need real commits (unlike A),
#   since no two tests ever touch the same rows regardless of execution
#   order or parallelism -- works for the transaction-boundary cases A
#   can't handle.
#   COST: requires disciplined, consistent use of the factory pattern
#   across the ENTIRE test suite -- any test that doesn't follow the
#   convention (uses a hardcoded ID, or reuses a "known" fixture row)
#   reintroduces the exact interference problem this approach exists to
#   prevent, and retrofitting this discipline onto an EXISTING, already-
#   growing suite (this case study's actual situation) is real,
#   nontrivial migration work across every existing test.
#
# ------------------------------------------------------------------------
# APPROACH C: Run integration tests against EPHEMERAL, per-test-run
# database instances (e.g. Testcontainers, L03) rather than a shared
# persistent test database at all
# ------------------------------------------------------------------------
#   WHY VALID: per L03, Testcontainers spins up a fresh, isolated
#   database instance for each test run (or even each test), making
#   cross-test data interference structurally impossible -- no shared
#   state exists AT ALL to leak between tests, the strongest isolation
#   guarantee of the three.
#   COST: real per-test-run STARTUP overhead (spinning up an actual
#   database container takes real time, even if usually just seconds)
#   -- for a very large or frequently-run suite, this overhead
#   compounds, and per L03, this approach doesn't eliminate the need for
#   GOOD test data setup within each fresh instance (you still need B's
#   factory discipline within each ephemeral instance, just without the
#   cross-run leakage risk).
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Isolation strength | Handles cross-transaction tests | Migration effort for existing suite |
#   |----------|--------------------------|---------------------------------------|-------------------------------------------|
#   | A: transaction rollback | Strong, but limited scope | No | Low |
#   | B: unique factory-generated data | Strong, if consistently applied | Yes | High (retrofit discipline) |
#   | C: ephemeral Testcontainers instances | Strongest | Yes | Medium (infra change, not per-test rewrite) |
#   A is the right default for the MAJORITY of tests that don't need
#   cross-transaction behavior; C is the strongest structural fix for
#   this case study's actual stated problem (existing interference in a
#   growing suite) since it fixes the isolation problem at the
#   infrastructure level rather than requiring every test to be
#   individually correct; B remains necessary WITHIN either A or C for
#   good per-test data hygiene regardless.


# ============================================================================
# CASE STUDY 4 — DECIDING TEST COVERAGE TARGETS FOR A NEW, TIME-
# PRESSURED PROJECT
# ============================================================================
#
# SETUP: a team building a new feature under real deadline pressure is
# deciding how much test coverage to require before merging, balancing
# quality against shipping speed.
#
# ------------------------------------------------------------------------
# APPROACH A: A strict, uniform code-coverage percentage requirement
# (e.g. "80% line coverage or the PR doesn't merge")
# ------------------------------------------------------------------------
#   WHY VALID: simple, objective, easy to enforce automatically via CI
#   -- no subjective judgment calls needed about "is this tested
#   enough," a clear, unambiguous bar every PR is held to equally.
#   COST: per L06's mutation-testing discussion, line coverage measures
#   whether code EXECUTED during tests, not whether it was MEANINGFULLY
#   VERIFIED -- a test can execute a line without actually asserting
#   anything meaningful about its behavior, hitting an 80% target while
#   providing far less real confidence than the number suggests; a
#   uniform percentage also treats trivial getter/setter code and
#   complex business logic as equally important to cover, which they
#   clearly aren't.
#
# ------------------------------------------------------------------------
# APPROACH B: Risk-based, targeted coverage -- require thorough testing
# specifically for the highest-risk/highest-complexity logic (payment
# calculations, permission checks), lighter or no formal requirement for
# low-risk code (simple CRUD, display formatting)
# ------------------------------------------------------------------------
#   WHY VALID: directly addresses A's "uniform bar ignores actual risk"
#   problem -- concentrates testing EFFORT where a bug would actually
#   matter most, a more efficient use of limited time-pressured
#   engineering effort than spreading equal testing rigor uniformly
#   across code of wildly different criticality.
#   COST: "risk-based" requires actual JUDGMENT calls about what's high-
#   risk — a genuine, recurring source of disagreement/inconsistency
#   across a team (different engineers may reasonably disagree on what
#   counts as high-risk), and without a clear, agreed-upon rubric, this
#   can quietly degrade into "whatever the person under deadline
#   pressure feels like testing," the exact failure mode strict rules
#   (A) are meant to prevent.
#
# ------------------------------------------------------------------------
# APPROACH C: No formal coverage requirement at all; rely on thorough
# code review and the engineer's own judgment
# ------------------------------------------------------------------------
#   WHY VALID: maximum flexibility and speed under real deadline
#   pressure -- avoids BOTH A's rigid bar and B's judgment-call
#   overhead, appropriate specifically for a small, experienced team
#   with a strong shared quality culture where reviewers can be trusted
#   to push back on genuinely under-tested code without a formal rule
#   forcing the conversation.
#   COST: has NO objective, automatically-enforced floor at all --
#   under genuine deadline pressure (this case study's explicit
#   premise), "trust the team's judgment" is exactly the condition under
#   which testing rigor is most likely to quietly erode, since there's
#   no automated gate catching the drift; this approach's success
#   depends entirely on a team quality-culture strength that isn't
#   guaranteed to hold up under sustained pressure.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Objectivity/consistency | Testing-effort efficiency | Resilience under deadline pressure |
#   |----------|------------------------------|---------------------------------|-------------------------------------------|
#   | A: uniform coverage % | Highest | Low (spread evenly regardless of risk) | High (automated, can't be skipped) |
#   | B: risk-based targeted coverage | Medium (needs a shared rubric) | Highest | Medium (needs discipline to apply consistently) |
#   | C: review + judgment only, no formal bar | Lowest | Depends on team judgment | Lowest (easiest to erode under pressure) |
#   B is the strongest answer PROVIDED the team invests in an explicit,
#   shared rubric for "what counts as high-risk" (turning B's main
#   weakness into a solved problem rather than an ongoing ambiguity) --
#   without that investment, B degrades toward C's weaknesses; A remains
#   a reasonable, if blunt, fallback specifically when a team lacks the
#   maturity/agreement needed to make B work well.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
