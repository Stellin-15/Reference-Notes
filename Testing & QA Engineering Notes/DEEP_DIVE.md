# Testing & QA Engineering — Principal Engineer Deep Dive

Companion to L01-L08. Narrative depth, then a comprehensive common-to-
uncommon reference.


## Test Doubles — Precisely Distinguished, and Why It Matters

**Beyond the lesson**: "Mock" is used loosely by most engineers to mean
"any fake object in a test," but the precise vocabulary (dummy, stub,
mock, fake, spy) exists because each solves a genuinely different testing
need, and conflating them leads to over-specified, brittle tests. A STUB
just returns canned data when called (no verification of HOW it was
called); a MOCK additionally VERIFIES specific interactions occurred
(asserting a method was called exactly once with specific arguments) — a
test that mocks everything and asserts every call's exact arguments
becomes brittle to harmless refactors (changing an internal implementation
detail breaks the test even though behavior is unchanged) — the
practical guidance: prefer STUBS/FAKES for setting up test state, reserve
true MOCKS with call-verification for the SPECIFIC interactions that are
actually the point of the test (e.g., verifying a payment API was actually called, not just that some internal helper ran).

**Interview Q&A**:
- *Q: A test suite is described as "brittle" — breaking on every refactor even when behavior is unchanged. What testing anti-pattern is the likely cause?* A: Over-mocking — asserting on internal implementation details (exact call counts/arguments to internal collaborators) rather than observable BEHAVIOR (the actual output/side effect that matters) — the fix is testing behavior through the public interface, using mocks/verification only for genuine external-boundary interactions (a real API call, a database write) where the interaction ITSELF is the thing being tested.


## Why Coverage Isn't Quality — Mutation Testing's Actual Point

**Beyond the lesson**: Code coverage measures whether a line was
EXECUTED during tests, not whether the test would actually CATCH a bug
in that line — a test that calls a function but never asserts on its
result achieves 100% coverage of that function while verifying nothing.
Mutation testing (see L06) exposes this gap directly: it automatically
introduces small bugs (mutants — flip a `>` to `>=`, change a `+` to a
`-`) into your code and reruns your test suite; if the tests still PASS
despite the introduced bug, that's a mutant that "survived," revealing a
genuine gap in test quality that coverage metrics alone would never
surface — a test suite with 100% coverage but a low mutation score is
providing false confidence, a real, common organizational trap of
over-indexing on coverage as the only testing quality metric.

**Interview Q&A**:
- *Q: A codebase has 95% test coverage but ships bugs regularly. What's a likely explanation?* A: High coverage with weak ASSERTIONS — tests that execute code paths without meaningfully verifying correct behavior (missing edge cases, asserting only "it didn't throw" rather than checking actual output correctness) — mutation testing or a deliberate manual review of assertion quality (not just line coverage) is the diagnostic step, since coverage percentage alone can't distinguish thorough tests from superficial ones.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### The testing pyramid, and its real-world violations
- **Unit tests** (many, fast, isolated) — the base of the pyramid; should
  be the vast majority of a healthy test suite by count.
- **Integration tests** (fewer, slower, real dependencies via
  Testcontainers — see L03) — verify components actually work together correctly.
- **E2E tests** (fewest, slowest, most brittle) — verify the full system
  from a user's perspective; genuinely valuable but expensive to
  maintain, which is exactly why the pyramid shape (few E2E, many unit) is the target.
- **The "ice cream cone" anti-pattern** (see L01) — an inverted pyramid
  (mostly E2E tests, few unit tests) that's genuinely common in
  organizations that adopted testing late or treat E2E tests as the
  primary safety net — leads to slow, flaky CI and long feedback loops,
  a real, common organizational testing-maturity problem worth being able to diagnose and argue against.

### Contract testing depth (see L05)
- **Consumer-driven contracts (Pact)** — the CONSUMER of an API defines
  its expectations as a contract; the PROVIDER's test suite verifies it
  satisfies every registered consumer's contract — catches breaking
  changes to a shared API BEFORE deployment, without needing full
  integration tests spanning every service simultaneously — a real,
  scalable alternative to "just run all the E2E tests" as microservice count grows.

### Flaky test diagnosis & elimination (see L07)
- **Common flaky-test root causes**: unguarded async waits (assuming an
  operation completed without actually waiting for it), test ORDER
  dependencies (shared mutable state between tests that pass individually
  but fail depending on execution order), and non-deterministic data
  (relying on the current real time/random values without injecting a
  controllable clock/seed) — each has a specific, real fix (explicit
  waits/polling, test isolation, injectable clocks) rather than "just retry the flaky test," which masks the underlying bug.
- **Test quarantine** — a genuine, pragmatic practice: moving a known-
  flaky test out of the blocking CI path (into a separate, monitored,
  non-blocking suite) while it's being fixed, rather than either ignoring
  it entirely or letting it block every unrelated PR — a real
  organizational practice for managing flaky-test debt without grinding CI to a halt.

### Specialized testing categories
- **Visual regression testing** (Chromatic, Percy) — automatically
  screenshots UI components/pages and diffs them against a baseline,
  catching unintended visual changes that functional tests alone (which
  check behavior, not appearance) would miss entirely.
- **Chaos engineering as a testing discipline** (see DevOps & SRE deep
  dive) — deliberately injecting failure in a controlled way, testing
  resilience ASSUMPTIONS the same way unit tests verify functional assumptions.
- **Load/performance testing** (see DevOps & SRE deep dive's k6/Locust
  coverage) — genuinely a distinct testing discipline from functional
  correctness testing, answering "does it work under realistic load," not just "does it work at all."


## NICHE BUT REAL

- **Property-based testing** (Hypothesis in Python, QuickCheck's
  original Haskell implementation) — instead of hand-writing specific
  example test cases, you define PROPERTIES that should hold for ANY
  valid input, and the framework generates many random inputs
  (including deliberately adversarial edge cases) trying to falsify the
  property — genuinely effective at finding edge cases human test-writers
  never think to check, a real and underused technique outside of a
  smaller circle of functional-programming-influenced teams.
- **Snapshot testing** — capturing a component/function's full output
  and comparing against a saved "snapshot" on subsequent runs — fast to
  write but a real risk of becoming a rubber-stamp ("just update the
  snapshot") rather than genuine verification if developers aren't
  disciplined about actually REVIEWING snapshot diffs before accepting them.
- **Test data builders/factories at scale** (factory_boy, similar
  patterns in other languages) — generating realistic, valid test data
  programmatically rather than hand-maintaining large literal fixture
  files — a real, significant maintainability improvement as a test suite's data needs grow complex.
- **Testing in production** (feature flags + canary deployment, see
  DevOps & SRE and MLOps deep dives) — a genuinely legitimate, modern
  complement to pre-deployment testing, not a replacement for it —
  acknowledging that some classes of issues (real traffic patterns, real
  data distributions) are only fully observable in production, and
  designing deployment/monitoring specifically to catch them safely and
  quickly rather than pretending pre-production testing alone can catch everything.
