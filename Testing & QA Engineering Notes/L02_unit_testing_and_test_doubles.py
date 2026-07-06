# ============================================================
# L02: Unit Testing and Test Doubles — Mocks, Stubs, Fakes, and Spies
# ============================================================
# WHAT: The precise vocabulary and use cases for the different kinds of
#       "test doubles" (fake objects standing in for real dependencies)
#       — mocks, stubs, fakes, and spies are NOT interchangeable terms,
#       despite common casual conflation.
# WHY: L01 established WHY unit tests need to be isolated from external
#      dependencies. This lesson covers the actual TECHNIQUE for
#      achieving that isolation, and the genuinely different use cases
#      for each type of test double.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
A DUMMY is an object passed in purely to satisfy a function signature's
parameter requirements — it's never actually USED by the code under
test (e.g. passing a placeholder logger object to a function that
accepts one but doesn't call it during this specific test path).

A STUB provides CANNED, pre-programmed responses to calls made during
the test — e.g. a stubbed database client that always returns a fixed
user object regardless of what query is issued — stubs exist to
CONTROL the test's inputs, letting you set up a specific scenario
(e.g. "the user does not exist") without needing a real database.

A MOCK is a stub that ADDITIONALLY records and later VERIFIES that
specific interactions actually happened — e.g. asserting that a
notification-sending function was called EXACTLY ONCE with specific
arguments. The key distinction from a stub: a stub is about CONTROLLING
what the dependency returns; a mock is about VERIFYING how the code
under test actually USED the dependency — using a mock changes what your
test is actually asserting (behavior/interaction, not just output).

A FAKE is a WORKING, SIMPLIFIED implementation of a dependency —
e.g. an in-memory dictionary standing in for a real database, correctly
supporting get/set/delete operations, just without persistence, network
calls, or the full feature set of the real thing — fakes are especially
useful for INTEGRATION-STYLE unit tests where you want realistic
behavior (multiple operations that need to interact correctly with each
other) without the overhead/flakiness of a genuinely real dependency.

A SPY wraps a REAL object/function, recording how it was called while
still delegating to (or partially delegating to) the real
implementation — useful when you want to verify an interaction
happened WITHOUT giving up the real behavior entirely.

WHY THIS VOCABULARY MATTERS (BEYOND PEDANTRY): choosing the WRONG kind
of test double for a given test's actual purpose creates BRITTLE tests
— over-using MOCKS (verifying exact interaction patterns) couples tests
tightly to IMPLEMENTATION DETAILS (e.g. "was this specific internal
method called") rather than OBSERABLE BEHAVIOR, meaning a purely
internal refactor (that doesn't change the function's actual output/
effect) can BREAK many tests despite the code's actual correctness being
unaffected — this is a common, genuine source of "our tests are so
brittle, every refactor breaks dozens of them" complaints, and it
traces directly back to overusing interaction-verifying mocks where
simpler state-verifying stubs/fakes would have sufficed.

PRODUCTION USE CASE:
Testing an order-processing function that (1) checks inventory via an
inventory service, and (2) sends a confirmation email: a STUB inventory
service returns a fixed "in stock" response (controlling the test's
input scenario), while a MOCK email service VERIFIES the confirmation
email was actually triggered with the correct order details (verifying
a genuinely important SIDE EFFECT that has no observable return value
to assert on otherwise) — using a mock specifically for the email step
(where behavior verification is the actual point) while using a
simpler stub for inventory (where only controlling the return value matters).

COMMON MISTAKES:
- Using a MOCK where a STUB would suffice — if a test only cares about
  what a function RETURNS given certain dependency responses, a mock's
  additional interaction-verification adds unnecessary coupling to
  implementation details without adding meaningful test value.
- Over-mocking to the point that a test verifies "did my code call
  functions in the exact sequence I expect" rather than "does my code
  produce the CORRECT observable result" — the former breaks on any
  internal refactor even when behavior is unchanged; the latter only
  breaks when actual behavior changes, which is what a test SHOULD care about.
- Using a FAKE that doesn't accurately represent the real dependency's
  actual behavior/constraints (e.g. an in-memory fake database with no
  uniqueness constraints, when the real database enforces them) — this
  can let bugs pass tests that would fail against the real dependency,
  a false sense of security worse than not testing that path at all.
"""

from unittest.mock import Mock


# ------------------------------------------------------------------
# 1. Stub — controlling inputs, not verifying interactions
# ------------------------------------------------------------------
class StubInventoryService:
    def __init__(self, canned_response: bool):
        self.canned_response = canned_response

    def check_in_stock(self, product_id: str) -> bool:
        return self.canned_response   # ALWAYS returns this, regardless of input


def process_order(inventory_service, email_service, product_id: str, customer_email: str) -> str:
    if not inventory_service.check_in_stock(product_id):
        return "OUT_OF_STOCK"
    email_service.send_confirmation(customer_email, product_id)
    return "ORDER_CONFIRMED"


def stub_demo():
    stub_inventory = StubInventoryService(canned_response=True)
    mock_email = Mock()

    result = process_order(stub_inventory, mock_email, "product-123", "customer@example.com")
    print(f"Order result: {result}")
    print("  -> The STUB controlled the test's INPUT scenario (item in stock)")
    print("     without us needing a real inventory service at all.")


# ------------------------------------------------------------------
# 2. Mock — verifying a genuinely important interaction/side effect
# ------------------------------------------------------------------
def mock_verification_demo():
    stub_inventory = StubInventoryService(canned_response=True)
    mock_email = Mock()

    process_order(stub_inventory, mock_email, "product-123", "customer@example.com")

    # VERIFYING the interaction happened correctly — this is what makes
    # it a MOCK rather than just a stub: we're asserting on BEHAVIOR
    mock_email.send_confirmation.assert_called_once_with("customer@example.com", "product-123")
    print("\nMock verification passed: send_confirmation was called EXACTLY")
    print("once with the correct arguments.")
    print("  -> This is verifying a SIDE EFFECT (an email being sent) that")
    print("     has no return value to check otherwise — exactly where mocks earn their keep.")


# ------------------------------------------------------------------
# 3. Fake — a working, simplified in-memory implementation
# ------------------------------------------------------------------
class FakeInMemoryDatabase:
    """A WORKING implementation, just simplified — supports real
    get/set/delete semantics without an actual database connection."""
    def __init__(self):
        self._store: dict[str, dict] = {}

    def save(self, key: str, value: dict):
        self._store[key] = value

    def get(self, key: str) -> dict | None:
        return self._store.get(key)

    def delete(self, key: str):
        self._store.pop(key, None)


def fake_demo():
    print("\nFake — realistic, working behavior without a real database:")
    fake_db = FakeInMemoryDatabase()
    fake_db.save("user:1", {"name": "Alice"})
    retrieved = fake_db.get("user:1")
    print(f"  Saved and retrieved: {retrieved}")
    fake_db.delete("user:1")
    print(f"  After delete: {fake_db.get('user:1')}")
    print("  -> Multiple operations interact CORRECTLY with each other,")
    print("     unlike a simple stub that would need pre-programmed responses")
    print("     for every possible call pattern in advance.")


if __name__ == "__main__":
    stub_demo()
    mock_verification_demo()
    fake_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A team refactors their order-processing service's internal method
structure (splitting one large function into several smaller private
helper methods) without changing its OBSERABLE behavior at all — tests
that had over-mocked internal method calls (asserting specific internal
methods were invoked in a specific order) broke across the board despite
zero actual behavior change, while tests using stubs/fakes at the
service's PUBLIC boundary (controlling external dependency responses,
verifying only genuinely important side effects like emails sent) passed
without modification — a direct, real illustration of why choosing the
right test double for each test's actual purpose matters for long-term test suite health.
"""
