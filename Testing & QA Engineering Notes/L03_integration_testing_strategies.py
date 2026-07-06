# ============================================================
# L03: Integration Testing Strategies
# ============================================================
# WHAT: How to test that MULTIPLE components (your code + a real
#       database, a real message queue, a real external API) actually
#       work together correctly — the middle layer of L01's test
#       pyramid, and the specific techniques (test containers, sandboxed
#       APIs) that make this practical without being painfully slow.
# WHY: L02 covered ISOLATING units from their dependencies via test
#      doubles. Integration tests deliberately do the OPPOSITE for a
#      SMALLER set of tests — verifying the REAL integration points
#      actually work, which test doubles can never fully guarantee.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
WHY TEST DOUBLES ALONE ARE INSUFFICIENT: a unit test using a STUBBED
database (L02) verifies your code correctly HANDLES a given database
response — but it can NEVER catch a bug where your actual SQL query is
malformed, your ORM mapping is wrong, or your assumptions about the
real database's actual behavior (transaction isolation level, specific
error codes) are incorrect — these bugs only surface when your code
talks to something that behaves like the REAL dependency, which is
exactly the gap integration tests exist to close.

TEST CONTAINERS (a widely-adopted pattern, with dedicated libraries like
"Testcontainers" across multiple languages) solve the practical problem
of "how do I test against a REAL database without a shared, stateful,
slow-to-reset test environment": each test run spins up a REAL,
EPHEMERAL database instance (via Docker — this repo's Docker Notes) just
for that test run, fully isolated from other test runs, and tears it
down afterward — this gives you the CORRECTNESS benefit of testing
against real software while avoiding the coordination problems of a
SHARED test database (test pollution between runs, tests needing to run
sequentially to avoid conflicts, an unreliable/slow shared environment
becoming a bottleneck for the whole team).

SANDBOXED/TEST-MODE EXTERNAL APIS: for THIRD-PARTY dependencies you
don't control (a payment gateway, an email-sending service), most
production-grade providers offer a SANDBOX or TEST MODE — a fully
functional but non-production version of their API that behaves
realistically (including realistic error responses for specific test
inputs, e.g. Stripe's well-known "use this specific card number to
simulate a declined payment") without actually charging real money or
sending real emails — integration tests against this sandbox catch
REAL integration bugs (malformed requests, incorrect handling of a
specific real error response shape) that a hand-written stub could
never anticipate without already knowing about that exact behavior.

CONTRACT TESTING (introduced briefly here, covered in depth in L05) is
a related but DISTINCT technique for a specific integration scenario:
verifying that TWO SERVICES' assumptions about each other's API
actually match, WITHOUT needing to run both services together in every
test run — useful specifically for microservices architectures where
spinning up every dependent service for every test would be impractical.

THE RIGHT SCOPE FOR AN INTEGRATION TEST: test the INTEGRATION POINT
itself (does my code correctly read/write to a real database; does my
HTTP client correctly parse a real API's response shape) — NOT the
entire application's business logic through that integration point
(that's what unit tests, testing the logic directly, are for) — a
common mistake is writing integration tests that re-test business logic
ALREADY covered by fast unit tests, just slower and through a real
database, providing little additional value for a real cost in speed.

PRODUCTION USE CASE:
A team's order-processing service has unit tests (L01-L02) covering
pricing/validation LOGIC using stubs, PLUS a smaller set of integration
tests using Testcontainers to spin up a real PostgreSQL instance,
verifying that the actual SQL queries/ORM mappings correctly persist
and retrieve order records — and separately, integration tests against
their payment provider's SANDBOX API specifically to verify their code
correctly handles that provider's REAL declined-payment error response
shape, which a hand-rolled stub might have modeled incorrectly.

COMMON MISTAKES:
- Testing against a SHARED, persistent test database rather than an
  ephemeral, per-test-run instance — this causes TEST POLLUTION (one
  test's leftover data affecting another test's results) and forces
  tests to run sequentially/carefully to avoid interference, a
  significant and unnecessary source of flakiness and slowness.
- Re-testing business LOGIC (already covered by fast unit tests) inside
  slow integration tests, rather than scoping integration tests
  specifically to the INTEGRATION POINT itself — this duplicates test
  coverage at a much higher time cost with little additional value.
- Testing against a THIRD-PARTY API's PRODUCTION endpoint instead of its
  sandbox/test mode — beyond the obvious risk (real charges, real
  emails sent during test runs), production endpoints often have
  stricter rate limits that a test suite running frequently in CI can hit.
"""

import textwrap


# ------------------------------------------------------------------
# 1. The gap test doubles can't close — illustrated
# ------------------------------------------------------------------
def test_double_gap_illustration():
    print("What a STUBBED database test CAN verify:")
    print("  - Your code correctly handles a GIVEN response shape")
    print("  - Your code's LOGIC given that response is correct\n")

    print("What a STUBBED database test CANNOT verify:")
    print("  - Your actual SQL query is syntactically/semantically correct")
    print("  - Your ORM's mapping between objects and table columns is correct")
    print("  - Your assumptions about the real database's actual error codes,")
    print("    transaction isolation behavior, or constraint enforcement are correct")
    print("\n  -> These are EXACTLY the bugs integration tests, run against a")
    print("     REAL (even if ephemeral/containerized) database, are needed to catch.")


# ------------------------------------------------------------------
# 2. Test containers pattern (conceptual — real usage needs Docker)
# ------------------------------------------------------------------
TESTCONTAINERS_EXAMPLE = textwrap.dedent("""\
    # Python example using the testcontainers library (conceptual)
    from testcontainers.postgres import PostgresContainer
    import pytest

    @pytest.fixture(scope="module")
    def real_postgres():
        # Spins up a REAL, throwaway PostgreSQL container just for this
        # test module — fully isolated from any other test run
        with PostgresContainer("postgres:16") as postgres:
            yield postgres.get_connection_url()
        # Container is automatically torn down here — no leftover state
        # for the NEXT test run to accidentally depend on or be polluted by

    def test_order_repository_persists_correctly(real_postgres):
        repo = OrderRepository(connection_string=real_postgres)
        repo.save(Order(id="123", total=99.99))

        retrieved = repo.get("123")
        assert retrieved.total == 99.99
        # This test exercises the REAL SQL query and ORM mapping code path —
        # a stubbed database test could never have caught a malformed
        # query or incorrect column mapping the way this test can.
""")

# ------------------------------------------------------------------
# 3. Sandboxed third-party API testing (conceptual)
# ------------------------------------------------------------------
SANDBOX_API_EXAMPLE = textwrap.dedent("""\
    # Testing against a payment provider's SANDBOX mode (conceptual,
    # patterned after Stripe's well-documented test-card conventions)

    def test_handles_declined_card_correctly():
        # A SPECIFIC test card number that Stripe's sandbox is documented
        # to always decline, with a REALISTIC error response shape
        result = charge_card(
            card_number="4000000000000002",  # Stripe's "always declined" test card
            amount=1000,
            api_mode="test",   # never touches real money
        )
        assert result.status == "declined"
        assert result.decline_code == "generic_decline"
        # This verifies our code handles the PROVIDER'S ACTUAL response
        # shape for a decline — a hand-written stub might have modeled
        # this incorrectly without ever being caught until a REAL
        # decline happened in production.
""")


if __name__ == "__main__":
    test_double_gap_illustration()
    print()
    print(TESTCONTAINERS_EXAMPLE)
    print(SANDBOX_API_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A team's unit tests (using a stubbed database, L02) all passed, but a
production incident revealed their ORM was silently truncating a text
field beyond the real database column's actual character limit — the
stub had no way to catch this, since it never represented the REAL
database's actual column constraints. After the incident, the team
added a Testcontainers-based integration test specifically verifying
that saving and retrieving a maximum-length value round-trips
correctly against a REAL PostgreSQL instance — a test category their
unit-test-only strategy had a genuine, now-closed gap in.
"""
