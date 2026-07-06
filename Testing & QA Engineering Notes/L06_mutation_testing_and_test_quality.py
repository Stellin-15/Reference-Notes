# ============================================================
# L06: Mutation Testing and Test Quality — Beyond Code Coverage
# ============================================================
# WHAT: Why CODE COVERAGE (which lines executed during tests) is a
#       genuinely weak proxy for "how good are my tests," and MUTATION
#       TESTING — a technique that measures whether your tests actually
#       CATCH bugs, not just whether they RUN code.
# WHY: L01's closing note flagged that "100% coverage" doesn't mean
#      "well-tested" — this lesson explains exactly WHY, and introduces
#      the concrete technique that actually measures test EFFECTIVENESS
#      rather than mere code execution.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
CODE COVERAGE measures the PERCENTAGE OF LINES (or branches) executed
at least once during a test run — it answers "was this code RUN during
testing?" but says NOTHING about whether the test actually VERIFIED
that code's behavior was correct. A test that calls a function but
asserts nothing meaningful about its result (or asserts something
trivially true regardless of the function's actual behavior) achieves
100% coverage of that function while providing ZERO actual protection
against bugs — this is not a hypothetical edge case; it's a genuinely
common way coverage metrics get "gamed" (often unintentionally) when
coverage percentage itself becomes the target rather than a proxy for
the actual goal (catching bugs).

MUTATION TESTING measures something meaningfully different and more
directly useful: it AUTOMATICALLY introduces small, deliberate bugs
("mutants") into your ACTUAL source code — e.g. changing a `>` to `>=`,
flipping a boolean, changing a `+` to a `-` — then RE-RUNS your existing
test suite against EACH mutated version. If your tests FAIL against the
mutant, the mutant is "KILLED" (your tests successfully caught this
specific injected bug) — if your tests still PASS despite the mutation,
the mutant "SURVIVED" (your tests did NOT actually verify the behavior
that specific code change affected), revealing a genuine gap in test
effectiveness that coverage alone would never surface.

THE MUTATION SCORE (percentage of mutants killed) is a substantially
more meaningful test-quality metric than code coverage precisely
because it measures whether tests ACTUALLY VERIFY correct behavior,
not merely whether code executes — a codebase with 100% line coverage
but only a 40% mutation score has extensive tests that RUN the code but
frequently fail to actually CATCH bugs in it — a genuinely different
and more actionable diagnosis than a coverage report alone would ever reveal.

THE REAL COST TRADEOFF: mutation testing is SIGNIFICANTLY more
computationally expensive than measuring coverage — it requires
re-running your ENTIRE test suite once PER MUTANT (potentially hundreds
or thousands of mutants for a non-trivial codebase) — this is why
mutation testing is typically NOT run on every single commit (unlike
coverage, which is cheap enough to check continuously), but rather
periodically (nightly, or on specific critical modules) to identify
test-quality gaps worth investing in, rather than as a continuous CI gate.

PRODUCTION USE CASE:
A team with a payment-calculation module showing 98% code coverage runs
a mutation testing tool and discovers a mutation score of only 55% —
investigating the surviving mutants reveals that several boundary
conditions (e.g. a discount threshold's exact `>=` vs `>` comparison)
were NEVER actually verified by any assertion, despite the surrounding
code being fully "covered" — this directly surfaces a specific,
actionable set of missing test cases that a coverage report alone had
completely hidden.

COMMON MISTAKES:
- Treating code coverage as a proxy for test QUALITY rather than merely
  test EXTENT — a team optimizing purely for a coverage percentage
  target can end up with extensive but low-value tests, exactly the gap
  mutation testing is designed to reveal.
- Running mutation testing as a continuous, every-commit CI gate given
  its substantial computational cost — this is usually impractical at
  scale; periodic (nightly/weekly) runs, or scoping to specific
  high-value modules, is the more practical adoption pattern.
- Chasing a 100% mutation score as a rigid target — some surviving
  mutants represent genuinely EQUIVALENT code changes (a mutation that
  doesn't actually change observable behavior, e.g. in genuinely dead
  code) that CANNOT be killed by any test, since there's no behavioral
  difference for a test to detect — mutation testing results need
  informed interpretation, not blind target-chasing.
"""


# ------------------------------------------------------------------
# 1. Code coverage's blind spot — illustrated directly
# ------------------------------------------------------------------
def calculate_discount(price: float, is_premium_member: bool) -> float:
    if is_premium_member:
        return price * 0.8   # 20% discount
    return price


def weak_test_with_full_coverage():
    """This test achieves 100% LINE coverage of calculate_discount,
    but asserts almost nothing meaningful about its actual behavior."""
    result = calculate_discount(100.0, is_premium_member=True)
    assert result is not None   # technically passes, verifies NOTHING useful
    print("Weak test: 100% coverage achieved, but assertion is meaningless.")


def strong_test_verifying_actual_behavior():
    """This test achieves the SAME coverage, but actually verifies
    the correct numeric behavior in both branches."""
    assert calculate_discount(100.0, is_premium_member=True) == 80.0
    assert calculate_discount(100.0, is_premium_member=False) == 100.0
    print("Strong test: SAME coverage, but verifies ACTUAL correct behavior.")


# ------------------------------------------------------------------
# 2. Mutation testing — injecting a bug and checking if tests catch it
# ------------------------------------------------------------------
def calculate_discount_MUTATED(price: float, is_premium_member: bool) -> float:
    """A deliberately mutated version — the discount rate was changed
    from 0.8 to 0.9 (simulating a real, subtle bug a mutation tool
    might automatically inject)."""
    if is_premium_member:
        return price * 0.9   # MUTATED: was 0.8
    return price


def run_test_against_mutant(test_function, target_function) -> str:
    try:
        # In real mutation testing, the test suite is re-run with the
        # SOURCE CODE itself mutated — simulated here by testing against
        # a manually "mutated" function directly
        if target_function == calculate_discount_MUTATED:
            result = calculate_discount_MUTATED(100.0, is_premium_member=True)
            assert result == 80.0   # the ORIGINAL expected value
        return "MUTANT KILLED (test correctly failed against the bug)"
    except AssertionError:
        return "MUTANT KILLED (test correctly failed against the bug)"
    return "MUTANT SURVIVED (test did not catch the injected bug)"


def mutation_testing_demo():
    print("\nMutation testing — injecting a bug (discount 0.8 -> 0.9):\n")

    print("Testing the WEAK test's assertion style against the mutant:")
    try:
        result = calculate_discount_MUTATED(100.0, is_premium_member=True)
        assert result is not None   # the weak test's actual assertion
        print(f"  Weak test result against mutant: MUTANT SURVIVED "
              f"(got {result}, but assertion 'is not None' doesn't catch this)")
    except AssertionError:
        print("  Weak test result against mutant: MUTANT KILLED")

    print("\nTesting the STRONG test's assertion style against the mutant:")
    try:
        result = calculate_discount_MUTATED(100.0, is_premium_member=True)
        assert result == 80.0   # the strong test's actual assertion
        print("  Strong test result against mutant: MUTANT SURVIVED")
    except AssertionError:
        print(f"  Strong test result against mutant: MUTANT KILLED "
              f"(correctly detected {result} != expected 80.0)")

    print("\n  -> BOTH tests achieve IDENTICAL code coverage, but only the")
    print("     STRONG test's specific-value assertion actually CATCHES")
    print("     this injected bug — this is precisely what mutation testing")
    print("     measures that coverage alone cannot.")


if __name__ == "__main__":
    weak_test_with_full_coverage()
    strong_test_verifying_actual_behavior()
    mutation_testing_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A financial services team runs mutation testing on their interest-rate
calculation module (which showed 100% code coverage) and discovers a
mutation score of just 45% — surviving mutants reveal that several tests
called the calculation function but only asserted "the result is a
positive number," never checking the ACTUAL expected value — this
finding directly leads the team to rewrite these tests with precise
expected-value assertions, catching two genuine, previously-undetected
rounding bugs in the process that had been silently present despite
"full test coverage" the entire time.
"""
