# ============================================================
# L01: Testing Fundamentals and the Test Pyramid
# ============================================================
# WHAT: The foundational model for how to ALLOCATE testing effort across
#       different test types — the test pyramid (many fast unit tests,
#       fewer integration tests, fewest slow end-to-end tests) — and why
#       inverting this ratio ("the ice cream cone anti-pattern") causes real pain.
# WHY: This repo's CICD Notes L03 touches testing strategy briefly within
#      a pipeline context. This new domain covers TESTING as its own
#      discipline in depth — the actual test-writing skill, not just
#      where tests run in a pipeline.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
THE TEST PYRAMID (a model popularized by Mike Cohn) recommends a
specific SHAPE for a healthy test suite: MANY unit tests at the base
(fast, isolated, testing a single function/class in milliseconds), FEWER
integration tests in the middle (testing how multiple components work
together, slower — seconds — since they touch real or realistic
dependencies), and the FEWEST end-to-end tests at the top (testing the
entire system through its real interface, slowest — potentially minutes
— and most brittle). The shape matters because of a fundamental
TRADEOFF: tests higher in the pyramid give you MORE CONFIDENCE that the
whole system actually works together, but are SLOWER, MORE EXPENSIVE to
maintain, and FAIL for more varied, often less-specific reasons
(a flaky network call, a timing issue) — while tests lower in the
pyramid are fast and precise about WHAT broke, but don't verify
integration points at all.

THE "ICE CREAM CONE" ANTI-PATTERN is the test pyramid inverted — many
end-to-end tests, few integration tests, very few unit tests — and it's
a genuinely common real-world failure mode, not just a theoretical
warning: a suite with mostly E2E tests becomes SLOW (a full E2E suite
can take hours), FLAKY (E2E tests are inherently more prone to
non-deterministic failures — timing, network, environment differences),
and provides POOR FAILURE LOCALIZATION (an E2E test failing tells you
"something in this huge user flow broke," not "this specific function
has a bug") — teams that end up here typically got there by writing
tests that mirror how a MANUAL QA tester would test the app (clicking
through the UI) rather than testing individual units of logic directly.

WHAT MAKES A GOOD UNIT TEST: FAST (milliseconds, so it can run
constantly during development without breaking flow), ISOLATED (doesn't
depend on external systems — a database, network, filesystem — which
introduces both slowness and non-determinism), DETERMINISTIC (the same
input always produces the same result — a test that sometimes passes and
sometimes fails without code changes is worse than no test, since it
erodes trust in the ENTIRE suite), and testing ONE THING (a failing test
should tell you specifically what broke, not require investigation to
even localize the problem).

WHY TESTS EXIST AT ALL — THE ACTUAL VALUE PROPOSITION: tests aren't
primarily about "proving code is correct" (a test suite can never prove
the ABSENCE of bugs, only the presence of the specific behaviors it
checks) — their PRIMARY practical value is enabling CONFIDENT CHANGE: a
good test suite lets a developer refactor or extend code and know
QUICKLY (via test failures) if they broke existing behavior, without
manually re-verifying everything by hand — this reframes "why write
tests" from an abstract correctness argument into a concrete
development-velocity argument, which is often the more persuasive one in practice.

PRODUCTION USE CASE:
A team maintaining a payment-processing service has hundreds of fast
unit tests covering individual pricing/tax-calculation logic, a smaller
set of integration tests verifying the service correctly talks to its
real database and a sandboxed payment gateway, and just a handful of
E2E tests covering the most critical user-facing flows (successfully
completing a purchase, handling a declined card) — a bug in tax
calculation logic is caught by a millisecond-fast unit test failure
immediately, rather than requiring a slow E2E test run to even notice
something is wrong, let alone localize WHERE.

COMMON MISTAKES:
- Writing E2E tests for logic that could be tested with a fast, isolated
  unit test instead — this is the direct cause of the ice-cream-cone
  anti-pattern, and it compounds over time as a growing E2E suite
  becomes slower and flakier with every addition.
- Treating "100% code coverage" as the actual goal — coverage measures
  which LINES were executed during tests, not whether the test actually
  verified CORRECT behavior; it's possible to have high coverage with
  tests that execute code but assert nothing meaningful about its behavior.
- Allowing FLAKY tests (tests that fail intermittently without a code
  change) to persist and be routinely re-run/ignored — this erodes the
  team's trust in test failures generally, eventually leading to
  genuine failures being dismissed as "probably just flaky" and missed.
"""


# ------------------------------------------------------------------
# 1. Illustrating the pyramid shape and its speed/confidence tradeoff
# ------------------------------------------------------------------
def test_pyramid_illustration():
    layers = [
        {"name": "Unit tests", "count": 500, "avg_duration_ms": 2, "confidence": "Low (isolated)"},
        {"name": "Integration tests", "count": 50, "avg_duration_ms": 200, "confidence": "Medium"},
        {"name": "End-to-end tests", "count": 10, "avg_duration_ms": 15000, "confidence": "High (whole system)"},
    ]
    print("Healthy test pyramid shape:\n")
    total_time_ms = 0
    for layer in layers:
        layer_time = layer["count"] * layer["avg_duration_ms"]
        total_time_ms += layer_time
        print(f"  {layer['name']}: {layer['count']} tests, "
              f"~{layer['avg_duration_ms']}ms each, confidence={layer['confidence']}, "
              f"total suite time contribution: {layer_time/1000:.1f}s")
    print(f"\n  Total suite runtime: ~{total_time_ms/1000:.1f}s")
    print("  -> The 500 fast unit tests contribute LESS total time than the")
    print("     10 slow E2E tests, despite being 50x more numerous — this is")
    print("     exactly why the pyramid shape keeps a suite both FAST and thorough.")


# ------------------------------------------------------------------
# 2. The ice-cream-cone anti-pattern, quantified
# ------------------------------------------------------------------
def ice_cream_cone_illustration():
    inverted_layers = [
        {"name": "Unit tests", "count": 20, "avg_duration_ms": 2},
        {"name": "Integration tests", "count": 30, "avg_duration_ms": 200},
        {"name": "End-to-end tests", "count": 200, "avg_duration_ms": 15000},
    ]
    total_time_ms = sum(l["count"] * l["avg_duration_ms"] for l in inverted_layers)
    print(f"\nInverted ('ice cream cone') anti-pattern shape:\n")
    for layer in inverted_layers:
        print(f"  {layer['name']}: {layer['count']} tests")
    print(f"\n  Total suite runtime: ~{total_time_ms/1000/60:.1f} MINUTES")
    print("  -> The SAME number of total tests, but dominated by slow E2E")
    print("     tests, takes vastly longer to run AND provides worse failure")
    print("     localization when something breaks.")


# ------------------------------------------------------------------
# 3. What makes a good unit test — a concrete example
# ------------------------------------------------------------------
def calculate_order_total(items: list[dict], tax_rate: float) -> float:
    subtotal = sum(item["price"] * item["quantity"] for item in items)
    return round(subtotal * (1 + tax_rate), 2)


def good_unit_test_example():
    print("\nA GOOD unit test — fast, isolated, deterministic, tests ONE thing:")

    # No database, no network, no filesystem — pure function, pure input/output
    items = [{"price": 10.0, "quantity": 2}, {"price": 5.0, "quantity": 1}]
    result = calculate_order_total(items, tax_rate=0.08)
    expected = 27.0

    assert result == expected, f"Expected {expected}, got {result}"
    print(f"  calculate_order_total(...) == {result} -- PASSED")
    print("  -> Runs in microseconds, has NO external dependencies, and a")
    print("     failure would point EXACTLY at this one calculation function.")


if __name__ == "__main__":
    test_pyramid_illustration()
    ice_cream_cone_illustration()
    good_unit_test_example()

"""
PRODUCTION CONTEXT EXAMPLE:
A team inherits a legacy test suite consisting almost entirely of
Selenium-based E2E tests that take 3 hours to run and fail
unpredictably roughly 15% of the time for reasons unrelated to actual
bugs — after measuring this cost, they invest in extracting the CORE
business logic (pricing, validation, state transitions) into pure,
independently-testable functions covered by fast unit tests, reducing
E2E coverage to only the handful of flows that genuinely need full-
system verification — cutting suite runtime from 3 hours to under 5
minutes for the vast majority of changes, while INCREASING actual
defect-catching confidence, directly illustrating why the pyramid shape
is a practical engineering recommendation, not just a theoretical ideal.
"""
