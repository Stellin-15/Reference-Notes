# ============================================================
# L07: Test Data Management and Flaky Test Elimination
# ============================================================
# WHAT: How to manage test data (fixtures, factories, seeding) so tests
#       remain independent and reproducible, and a systematic approach
#       to DIAGNOSING and eliminating FLAKY tests — tests that fail
#       intermittently without any actual code change.
# WHY: L01 flagged flaky tests as a genuine, trust-eroding problem.
#      This lesson covers the SPECIFIC categories of flakiness and how
#      to actually fix each one, plus the test-data practices that
#      prevent a large class of flakiness before it starts.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
TEST FIXTURES are pre-defined pieces of test data set up BEFORE a test
runs (and typically torn down after) — the key design goal is
INDEPENDENCE: each test should set up EXACTLY the data it needs, without
depending on data left behind by a PREVIOUS test or a SHARED, mutable
fixture that multiple tests modify — shared, mutable fixtures are a
classic and common source of flaky tests, since test EXECUTION ORDER
(which can vary, especially under parallelization) then affects whether
a test's assumptions about the data's current state actually hold.

TEST DATA FACTORIES (a common pattern, e.g. Factory Boy in Python,
Factory Bot in Ruby) generate REALISTIC test objects programmatically,
with sensible defaults for every field EXCEPT the ones a specific test
actually cares about — this avoids two problems simultaneously: (1)
tests that manually construct every field of a complex object become
extremely verbose and hide WHICH fields actually matter for that
specific test, and (2) hardcoded, shared test data (e.g. "user ID 1"
used across many tests) creates hidden coupling between tests that
happen to reference the same ID.

THE FOUR MAIN CATEGORIES OF FLAKY TESTS, each with a DIFFERENT root
cause and fix: (1) RACE CONDITIONS / TIMING (L04 covered this for E2E
specifically — an assertion runs before an async operation completes;
fixed via proper waiting, not longer fixed sleeps); (2) TEST ORDER
DEPENDENCE (a test passes only when run after/before a specific other
test, due to shared mutable state; fixed via proper test isolation and
fresh fixtures per test); (3) EXTERNAL DEPENDENCY UNRELIABILITY (a test
calls a REAL external service that's occasionally slow/unavailable;
fixed via appropriate test doubles for unit tests, or a genuinely
reliable sandboxed environment for integration tests); (4)
NON-DETERMINISTIC CODE UNDER TEST (e.g. code that depends on the current
time, random number generation, or concurrent/multi-threaded execution
order without proper synchronization; fixed by making these sources of
non-determinism CONTROLLABLE in tests — injecting a fixed clock,
seeding a random generator, or properly synchronizing concurrent test assertions).

A SYSTEMATIC APPROACH TO DIAGNOSING FLAKINESS: rather than immediately
assuming "it's just flaky, re-run it" (which erodes trust and hides real
bugs, per L01), a disciplined team RUNS THE SUSPECTED FLAKY TEST
REPEATEDLY IN ISOLATION (to rule out order-dependence) and under
DELIBERATE LOAD/DELAY INJECTION (to surface race conditions more
reliably than waiting for them to occur naturally) — this turns "it's
just flaky sometimes" into an actual reproducible bug report, which is
almost always the crucial first step to actually fixing the ROOT CAUSE
rather than merely tolerating the symptom.

PRODUCTION USE CASE:
A team's CI pipeline has a test that fails roughly 1 in 20 runs — rather
than adding a retry-on-failure rule (which HIDES the problem rather than
fixing it), the team runs the test 100 times in a tight loop locally and
finds it reliably fails when run IMMEDIATELY after a specific OTHER test
that leaves a shared in-memory cache in an unexpected state — the fix
(properly resetting that cache between tests, restoring true test
isolation) eliminates the flakiness entirely, rather than merely masking it with retries.

COMMON MISTAKES:
- Responding to a flaky test by adding automatic retries ("just re-run
  it if it fails") rather than diagnosing and fixing the ROOT CAUSE —
  this hides the underlying bug (which may indicate a REAL,
  user-facing race condition in the actual application code, not just
  the test) and erodes confidence that a passing test suite means anything.
- Using SHARED, mutable test fixtures across many tests to "save setup
  time" — this creates hidden coupling between tests that only manifests
  as flakiness under specific execution orders, often intermittently
  and confusingly under parallel test execution specifically.
- Writing tests that depend on the ACTUAL current wall-clock time,
  actual random number generation, or actual network timing without
  making these sources of non-determinism controllable/injectable — this
  makes a test's behavior depend on WHEN and under WHAT conditions it
  happens to run, a direct and common source of flakiness.
"""

import random
from datetime import datetime, timedelta


# ------------------------------------------------------------------
# 1. Test data factories — realistic defaults, explicit overrides
# ------------------------------------------------------------------
def create_user(**overrides) -> dict:
    """A simple test data factory — sensible defaults for every field,
    with only the fields a SPECIFIC test cares about explicitly overridden."""
    defaults = {
        "id": f"user_{random.randint(1000, 9999)}",
        "name": "Test User",
        "email": "test@example.com",
        "is_premium": False,
        "created_at": datetime(2026, 1, 1),
    }
    return {**defaults, **overrides}


def factory_demo():
    print("Test data factory — only override what THIS test actually cares about:\n")
    premium_user = create_user(is_premium=True)
    print(f"  Premium user test data: {premium_user}")
    print("  -> The test that needed a PREMIUM user only had to specify")
    print("     is_premium=True — every other field got a sensible default,")
    print("     keeping the test focused on what actually matters for it.")


# ------------------------------------------------------------------
# 2. Non-determinism made controllable — injectable clock
# ------------------------------------------------------------------
class Clock:
    """Rather than calling datetime.now() directly (making tests depend
    on the ACTUAL current time — a classic non-determinism source),
    inject a CONTROLLABLE clock that tests can fix to a known value."""
    def __init__(self, fixed_time: datetime = None):
        self._fixed_time = fixed_time

    def now(self) -> datetime:
        return self._fixed_time if self._fixed_time else datetime.now()


def is_subscription_expired(expiry_date: datetime, clock: Clock) -> bool:
    return clock.now() > expiry_date


def controllable_clock_demo():
    print("\nControllable clock — deterministic time-dependent testing:\n")
    fixed_clock = Clock(fixed_time=datetime(2026, 6, 1))
    expiry = datetime(2026, 5, 1)

    result = is_subscription_expired(expiry, fixed_clock)
    print(f"  With clock fixed to 2026-06-01, expiry 2026-05-01: expired={result}")
    print("  -> This test's result is COMPLETELY independent of when it")
    print("     actually runs (today, next year, at 11:59pm on New Year's Eve)")
    print("     — a test using datetime.now() directly would NOT have this guarantee.")


# ------------------------------------------------------------------
# 3. Diagnosing flakiness — running in isolation and under repetition
# ------------------------------------------------------------------
def diagnose_flaky_test_demo():
    print("\nSystematic flaky-test diagnosis approach:\n")
    print("  1. Run the SUSPECTED test in ISOLATION, repeated 100+ times")
    print("     -> If it NEVER fails in isolation, suspect TEST ORDER DEPENDENCE")
    print("        (shared mutable state from another test)")
    print("  2. Run the full suite with test order RANDOMIZED (many modern")
    print("     test runners support this) across many runs")
    print("     -> If failures correlate with specific OTHER tests running")
    print("        first, that confirms order-dependence, and identifies WHICH test")
    print("  3. If it fails even in isolation, inject deliberate delays around")
    print("     async operations to more RELIABLY surface a suspected race condition")
    print("     -> Reproducing INTERMITTENT failure CONSISTENTLY is the key")
    print("        step that turns 'random flakiness' into an actual, fixable bug report")


if __name__ == "__main__":
    factory_demo()
    controllable_clock_demo()
    diagnose_flaky_test_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A team notices a specific test fails roughly 5% of the time in CI. Instead
of accepting a "just re-run failed CI jobs" policy, they add a CI job
that runs the suspected test 200 times in a tight loop with randomized
test ordering enabled — this reveals the test ONLY fails when a specific
OTHER test (which mutates a shared, module-level cache dictionary) runs
immediately before it. The fix — giving each test its own isolated cache
instance via a proper fixture, rather than sharing module-level state —
eliminates the flakiness entirely and, as a side benefit, reveals that
the SAME shared-cache pattern existed in production code, a genuine
latent bug the flaky test had been trying to tell them about all along.
"""
