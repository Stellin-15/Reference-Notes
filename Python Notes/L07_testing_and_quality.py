# ============================================================
# L07: Testing and Code Quality in Python
# ============================================================
# WHAT: Comprehensive coverage of pytest, mocking, property-based
#       testing, async testing, and coverage analysis.
# WHY:  Tests are the only thing that lets you change code
#       confidently. Without them, every refactor is a gamble.
#       Good tests also force good design — testable code is
#       almost always better-structured code.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    Python's testing ecosystem centers on pytest — a framework that
    replaced unittest as the industry standard because of its simpler
    syntax (plain assert, not assertEqual), powerful fixture system,
    and rich plugin ecosystem.

    Testing hierarchy:
      Unit tests      → test one function/class in isolation (mocked deps)
      Integration tests → test multiple real components together
      End-to-end tests  → test the full system (real DB, real HTTP)

    The key architectural decision is WHERE to draw the mock boundary.
    Mock too little → tests are slow and brittle (real DB required).
    Mock too much   → tests pass even when real integrations are broken.

PRODUCTION USE CASE:
    A payment service with 2000 unit tests, 200 integration tests,
    and 20 E2E tests. The 2000 unit tests run in 3 seconds (all mocked).
    The 200 integration tests run in 30 seconds (real SQLite/Postgres).
    The 20 E2E tests run in 5 minutes (deployed to staging).
    CI gates on all three layers before merging to main.

COMMON MISTAKES:
    - Using assertEqual/assertTrue instead of plain assert in pytest
    - Fixtures that are too large / do too much (test setup should be obvious)
    - Mocking the thing under test (you're testing your mock, not your code)
    - Not using parametrize (copy-pasting test functions for variants)
    - Ignoring branch coverage — line coverage of 90% can hide uncovered paths
    - async tests that accidentally run synchronously (no @pytest.mark.asyncio)
"""

# ============================================================
# SECTION 1: pytest basics
# ============================================================
# Test discovery rules (no configuration needed):
#   - Files matching test_*.py or *_test.py in the current directory tree
#   - Functions starting with test_ inside those files
#   - Classes starting with Test (no __init__) with methods starting with test_
#
# pytest uses PLAIN ASSERT — not unittest's assertEqual/assertTrue.
# The framework rewrites assert statements at import time (assertion
# rewriting) so you get detailed failure messages automatically.
#
# Run tests:
#   pytest                       → discover and run all tests
#   pytest tests/test_user.py    → specific file
#   pytest -k "test_create"      → keyword filter (matches test names)
#   pytest -x                    → stop on first failure
#   pytest -v                    → verbose (print each test name)
#   pytest --tb=short            → shorter traceback format

# Example test file structure:

# def test_addition():
#     result = 1 + 1
#     assert result == 2          # plain assert — pytest rewrites this
#     assert result != 3
#
# def test_exception():
#     with pytest.raises(ValueError, match="invalid"):
#         int("not_a_number")     # match= is a regex on the exception message
#
# def test_approx_float():
#     assert 0.1 + 0.2 == pytest.approx(0.3)  # floating point comparison


# ============================================================
# SECTION 2: pytest fixtures
# ============================================================
# Fixtures are pytest's dependency injection system.
# A test function declares what it needs as PARAMETERS,
# and pytest resolves and provides them automatically.
#
# Scope controls how often the fixture is created:
#   function  → fresh instance per test (default, safest)
#   class     → shared within a test class
#   module    → shared within a test file
#   session   → shared across the entire test session
#
# Use the narrowest scope that works. Sharing mutable state
# between tests causes mysterious failures ("test order dependency").
#
# conftest.py: a special pytest file. Fixtures defined here are
# automatically available to all tests in the same directory and below.
# No import needed — pytest discovers conftest.py automatically.

# ---- conftest.py (would live at tests/conftest.py) ----
#
# import pytest
# import sqlite3
#
# @pytest.fixture(scope="function")
# def in_memory_db():
#     """
#     Provides a fresh SQLite in-memory database for each test.
#     The database is automatically destroyed when the test ends
#     because we use 'yield' — code after yield is teardown.
#     """
#     conn = sqlite3.connect(":memory:")
#     conn.execute("""
#         CREATE TABLE users (
#             id INTEGER PRIMARY KEY,
#             email TEXT UNIQUE NOT NULL,
#             name TEXT NOT NULL
#         )
#     """)
#     conn.commit()
#
#     yield conn    # ← test receives this value
#
#     conn.close()  # ← always runs, even if test fails
#
# @pytest.fixture(scope="session")
# def app_config():
#     """Session-scoped: read config once for all tests."""
#     return {"db_url": "sqlite:///:memory:", "debug": True}


# ============================================================
# SECTION 3: parametrize — data-driven tests
# ============================================================
# Instead of writing one test function per case (copy-paste),
# parametrize generates N test instances from a list of inputs.
# Each instance gets its own pass/fail status in the report.
#
# Benefits:
#   - Adding a new test case = adding one tuple to the list
#   - Failures show exactly which parameter set failed
#   - pytest -k "test_validate[empty]" runs just that case

# import pytest
#
# @pytest.mark.parametrize("email, expected_valid", [
#     ("user@example.com",   True),   # normal case
#     ("bad-email",          False),  # missing @
#     ("",                   False),  # empty string
#     ("a@b.c",              True),   # short but valid
#     ("user@.com",          False),  # missing domain name
# ])
# def test_email_validation(email, expected_valid):
#     assert validate_email(email) == expected_valid
#
# # Multiple parameter sets with ids for readable output:
# @pytest.mark.parametrize("a,b,result", [
#     (1, 2, 3),
#     (0, 0, 0),
#     (-1, 1, 0),
# ], ids=["positive", "zeros", "negative"])
# def test_add(a, b, result):
#     assert add(a, b) == result


# ============================================================
# SECTION 4: marks — tagging and controlling test execution
# ============================================================
# Marks attach metadata to tests. Built-in marks:
#   @pytest.mark.skip(reason="...")        → always skip
#   @pytest.mark.skipif(condition, reason) → conditional skip
#   @pytest.mark.xfail(reason="...")       → expected to fail (passes if it fails)
#   @pytest.mark.xfail(strict=True)       → fail the suite if it PASSES (used to
#                                            track bugs that get fixed unexpectedly)
#
# Custom marks: register in pytest.ini to avoid warnings.
#   [pytest]
#   markers =
#       slow: marks tests as slow (deselect with '-m "not slow"')
#       integration: tests that require a real database
#
# Then: pytest -m "not slow"  → skip all slow tests in CI fast path
#       pytest -m integration → run only integration tests

# @pytest.mark.slow
# @pytest.mark.integration
# def test_full_user_creation_flow(real_database):
#     ...


# ============================================================
# SECTION 5: tmp_path — temporary files per test
# ============================================================
# pytest provides a tmp_path fixture (pathlib.Path) that gives
# each test its own temporary directory, cleaned up automatically.
# Never use /tmp directly in tests — tests would collide.
#
# def test_writes_report_file(tmp_path):
#     report_file = tmp_path / "report.csv"
#     generate_report(output_path=report_file)
#     assert report_file.exists()
#     content = report_file.read_text()
#     assert "Total" in content


# ============================================================
# SECTION 6: monkeypatch — safe runtime patching
# ============================================================
# monkeypatch provides test-scoped patches that are AUTOMATICALLY
# undone after the test — no cleanup code needed.
#
# vs mock.patch: monkeypatch is simpler for simple cases;
# mock.patch is more powerful (tracks calls, supports return values).
#
# Key methods:
#   monkeypatch.setattr(obj, "attr", value)  → patch an attribute
#   monkeypatch.setenv("VAR", "value")       → set env variable
#   monkeypatch.delenv("VAR")                → delete env variable
#   monkeypatch.setitem(dict, key, value)    → patch a dict entry
#   monkeypatch.syspath_prepend(path)        → modify sys.path

# def test_uses_env_var(monkeypatch):
#     monkeypatch.setenv("API_KEY", "test-key-123")
#     monkeypatch.setenv("DEBUG", "true")
#     result = load_config()             # reads env vars
#     assert result.api_key == "test-key-123"
#
# def test_patches_datetime(monkeypatch):
#     fixed_now = datetime(2024, 1, 15, 12, 0, 0)
#     monkeypatch.setattr("mymodule.datetime", lambda: fixed_now)
#     assert get_current_date() == "2024-01-15"


# ============================================================
# SECTION 7: unittest.mock — Mock and MagicMock
# ============================================================
# Mock(): a generic mock object. Records all calls made to it.
#   - mock.some_method() → returns another Mock (auto-specs children)
#   - mock.return_value = 42 → mock() returns 42
#   - mock.side_effect = exception → calling mock() raises it
#   - mock.side_effect = [1, 2, 3] → returns values in sequence
#
# MagicMock(): Mock + pre-configured magic methods (__len__, __iter__,
#   __enter__/__exit__ for context managers, etc.)
#   Use MagicMock when the code under test uses the object in a
#   special way (e.g., with statement, len(), iteration).
#
# patch(): temporarily replaces a name in a module with a Mock.
#   IMPORTANT: patch the name WHERE IT IS USED, not where it is defined.
#   If mymodule.py does 'import requests', patch 'mymodule.requests',
#   NOT 'requests.get' — the latter won't affect the already-imported name.

from unittest.mock import Mock, MagicMock, patch, call, AsyncMock

# --- Basic Mock usage ---
def demonstrate_mock_basics():
    mock_db = Mock()

    # Configure return value
    mock_db.find_user.return_value = {'id': 1, 'name': 'Alice'}

    # Configure side effect (exception)
    mock_db.delete_user.side_effect = PermissionError("Not allowed")

    # Use the mock (simulating production code calling it)
    user = mock_db.find_user(user_id=1)
    assert user['name'] == 'Alice'

    # Assertion methods — these are what make Mock powerful
    mock_db.find_user.assert_called_once_with(user_id=1)
    mock_db.find_user.assert_called_with(user_id=1)   # same, but for last call
    assert mock_db.find_user.call_count == 1

    # call_args_list: inspect ALL calls if called multiple times
    mock_db.find_user(user_id=2)
    mock_db.find_user(user_id=3)
    assert mock_db.find_user.call_args_list == [
        call(user_id=1),
        call(user_id=2),
        call(user_id=3),
    ]


# --- patch as decorator ---
# @patch("mymodule.requests.get")
# def test_fetch_user(mock_get):
#     mock_get.return_value.json.return_value = {"id": 1, "name": "Alice"}
#     mock_get.return_value.status_code = 200
#
#     result = fetch_user_from_api(user_id=1)
#
#     mock_get.assert_called_once_with("https://api.example.com/users/1")
#     assert result["name"] == "Alice"

# --- patch as context manager ---
# def test_sends_email():
#     with patch("notifications.smtp.send") as mock_send:
#         mock_send.return_value = True
#         notify_user(user_id=1, message="Welcome!")
#         mock_send.assert_called_once()


# ============================================================
# SECTION 8: Testing async code
# ============================================================
# asyncio.run() doesn't work inside pytest's sync event loop.
# Use pytest-asyncio: pip install pytest-asyncio
#
# Configure in pytest.ini or pyproject.toml:
#   [tool.pytest.ini_options]
#   asyncio_mode = "auto"   # all async test functions get the marker
#
# AsyncMock: like Mock but returns a coroutine when called.
# Required when the code under test does 'await mock()'.

# import pytest
# from unittest.mock import AsyncMock
#
# @pytest.mark.asyncio
# async def test_async_fetch():
#     mock_client = AsyncMock()
#     mock_client.get.return_value = {"data": [1, 2, 3]}
#
#     result = await fetch_data(client=mock_client)
#
#     mock_client.get.assert_awaited_once_with("/data")
#     assert result == [1, 2, 3]
#
# # Test that async function raises correctly
# @pytest.mark.asyncio
# async def test_async_timeout():
#     mock_client = AsyncMock()
#     mock_client.get.side_effect = asyncio.TimeoutError()
#
#     with pytest.raises(ServiceUnavailableError):
#         await fetch_data(client=mock_client)


# ============================================================
# SECTION 9: hypothesis — property-based testing
# ============================================================
# Traditional tests: you write specific inputs and expected outputs.
# Property-based tests: you describe PROPERTIES that must always hold,
# and Hypothesis generates hundreds of inputs to try to falsify them.
#
# Hypothesis finds edge cases you wouldn't think to test manually:
#   - empty strings, very long strings, Unicode, null bytes
#   - integer overflow, negative numbers, zero
#   - NaN, infinity, -0.0 for floats
#
# When Hypothesis finds a failure, it SHRINKS the input to the
# smallest example that still fails — critical for debugging.
#
# Install: pip install hypothesis
#
# Core strategies:
#   st.integers(min_value=0, max_value=100)
#   st.text(alphabet=st.characters(whitelist_categories=('L',)))
#   st.lists(st.integers(), min_size=1, max_size=10)
#   st.from_regex(r'\d{3}-\d{4}')   → generates matching strings
#   st.builds(MyClass, name=st.text())  → build objects with strategies

# from hypothesis import given, settings, assume
# from hypothesis import strategies as st
#
# @given(st.lists(st.integers()))
# def test_sort_is_idempotent(lst):
#     """Sorting twice gives the same result as sorting once."""
#     assert sorted(sorted(lst)) == sorted(lst)
#
# @given(st.text())
# def test_encode_decode_roundtrip(s):
#     """Whatever we encode, we can decode back."""
#     encoded = encode(s)
#     decoded = decode(encoded)
#     assert decoded == s
#
# @given(st.integers(min_value=1), st.integers(min_value=1))
# def test_add_is_commutative(a, b):
#     assert add(a, b) == add(b, a)
#
# # assume() discards inputs that don't meet preconditions
# @given(st.integers())
# def test_positive_sqrt(n):
#     assume(n >= 0)           # discard negative inputs
#     assert sqrt(n) >= 0


# ============================================================
# SECTION 10: Coverage — measuring what's tested
# ============================================================
# Install: pip install pytest-cov
# Run:
#   pytest --cov=src --cov-report=html --cov-report=term-missing
#
# --cov=src          → measure coverage for the 'src' package only
# --cov-report=html  → generates htmlcov/index.html (browsable)
# term-missing       → shows which line numbers are NOT covered
#
# LINE COVERAGE vs BRANCH COVERAGE:
#   Line coverage: was this line executed at all?
#   Branch coverage: was EVERY branch (if/else) taken?
#
#   Example:
#     def check(x):
#         if x > 0:       # ← line covered
#             return True # ← line covered
#         return False    # ← NOT covered by "if x > 0" test alone
#
#   Line coverage: 75% (3 of 4 lines hit)
#   Branch coverage: 50% (only the True branch was tested)
#   → Always use branch coverage: pytest --cov-branch
#
# Setting thresholds (fail build if below):
#   [tool.coverage.report]
#   fail_under = 85


# ============================================================
# SECTION 11: Mocking vs not mocking
# ============================================================
# MOCK external dependencies:
#   - HTTP APIs (slow, requires network, may cost money)
#   - Email/SMS services (would send real messages)
#   - Payment gateways
#   - Time / random (non-deterministic)
#   - File system (sometimes — prefer tmp_path for simple cases)
#
# DO NOT MOCK your own business logic:
#   - If you mock the UserService to test the OrderService,
#     you're not testing their actual interaction
#   - If you mock a function to always return True, tests pass
#     even if the real function is broken
#
# RULE: mock at the BOUNDARY of your system (external I/O).
# Test your internal logic with real objects, possibly with
# test doubles (in-memory implementations of interfaces).


# ============================================================
# SECTION 12: Arrange-Act-Assert pattern
# ============================================================
# Every test should follow AAA:
#   Arrange: set up the data, fixtures, mocks needed
#   Act:     call the one thing being tested
#   Assert:  verify the outcome
#
# One test = one behavior. If a test has two Acts, split it.
# Tests that do multiple things become impossible to name clearly.

# def test_user_creation_sends_welcome_email():
#     # Arrange
#     db = InMemoryUserRepository()
#     mock_emailer = Mock()
#     service = UserService(db=db, emailer=mock_emailer)
#
#     # Act
#     user = service.create_user(email="alice@example.com", name="Alice")
#
#     # Assert
#     assert user.id is not None                          # user was persisted
#     assert db.find_by_email("alice@example.com") == user  # retrievable
#     mock_emailer.send_welcome.assert_called_once_with(  # email was sent
#         to="alice@example.com",
#         name="Alice"
#     )


# ============================================================
# SECTION 13: Complete real-world test suite example
# ============================================================
# A User service with DB interaction, showing both unit and
# integration test approaches.

import sqlite3
from dataclasses import dataclass, field
from typing import Optional

# ---- Domain model ----

@dataclass
class User:
    email: str
    name: str
    id: Optional[int] = None

class UserNotFoundError(Exception):
    pass

class DuplicateEmailError(Exception):
    pass

# ---- Repository (data access layer) ----

class UserRepository:
    """Production repository — talks to a real SQLite DB."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def save(self, user: User) -> User:
        try:
            cursor = self._conn.execute(
                "INSERT INTO users (email, name) VALUES (?, ?)",
                (user.email, user.name)
            )
            self._conn.commit()
            return User(email=user.email, name=user.name, id=cursor.lastrowid)
        except sqlite3.IntegrityError:
            raise DuplicateEmailError(f"Email already exists: {user.email}")

    def find_by_email(self, email: str) -> User:
        row = self._conn.execute(
            "SELECT id, email, name FROM users WHERE email = ?", (email,)
        ).fetchone()
        if row is None:
            raise UserNotFoundError(email)
        return User(id=row[0], email=row[1], name=row[2])

# ---- Service (business logic) ----

class UserService:
    """Business logic layer. Depends on abstractions, not concrete classes."""

    def __init__(self, repo: UserRepository, emailer):
        self._repo = repo
        self._emailer = emailer

    def create_user(self, email: str, name: str) -> User:
        if not email or '@' not in email:
            raise ValueError(f"Invalid email: {email}")
        user = self._repo.save(User(email=email, name=name))
        self._emailer.send_welcome(to=email, name=name)
        return user

# ============================================================
# TEST FILE EXAMPLE (would live at tests/test_user_service.py)
# ============================================================
# import pytest
# from unittest.mock import Mock
# from myapp.users import UserService, UserRepository, User
# from myapp.users import DuplicateEmailError, UserNotFoundError
#
# # ---- Unit tests (all mocked) ----
#
# class TestUserServiceUnit:
#
#     def setup_method(self):
#         """Runs before each test method. Fresh mocks each time."""
#         self.mock_repo = Mock()
#         self.mock_emailer = Mock()
#         self.service = UserService(repo=self.mock_repo, emailer=self.mock_emailer)
#
#     def test_create_user_success(self):
#         self.mock_repo.save.return_value = User(id=1, email="a@b.com", name="Alice")
#         user = self.service.create_user(email="a@b.com", name="Alice")
#         assert user.id == 1
#         self.mock_emailer.send_welcome.assert_called_once_with(to="a@b.com", name="Alice")
#
#     def test_create_user_invalid_email_raises(self):
#         with pytest.raises(ValueError, match="Invalid email"):
#             self.service.create_user(email="not-an-email", name="Alice")
#         self.mock_repo.save.assert_not_called()   # DB not touched
#
#     def test_create_user_duplicate_propagates(self):
#         self.mock_repo.save.side_effect = DuplicateEmailError("a@b.com")
#         with pytest.raises(DuplicateEmailError):
#             self.service.create_user(email="a@b.com", name="Alice")
#
# # ---- Integration tests (real SQLite, no HTTP mocks) ----
#
# @pytest.fixture(scope="function")
# def db_conn():
#     conn = sqlite3.connect(":memory:")
#     conn.execute("""
#         CREATE TABLE users (
#             id INTEGER PRIMARY KEY AUTOINCREMENT,
#             email TEXT UNIQUE NOT NULL,
#             name TEXT NOT NULL
#         )
#     """)
#     conn.commit()
#     yield conn
#     conn.close()
#
# class TestUserRepositoryIntegration:
#
#     def test_save_and_find(self, db_conn):
#         repo = UserRepository(db_conn)
#         saved = repo.save(User(email="x@y.com", name="Bob"))
#         assert saved.id is not None
#         found = repo.find_by_email("x@y.com")
#         assert found.name == "Bob"
#
#     def test_duplicate_email_raises(self, db_conn):
#         repo = UserRepository(db_conn)
#         repo.save(User(email="x@y.com", name="Bob"))
#         with pytest.raises(DuplicateEmailError):
#             repo.save(User(email="x@y.com", name="Alice"))
#
#     def test_find_nonexistent_raises(self, db_conn):
#         repo = UserRepository(db_conn)
#         with pytest.raises(UserNotFoundError):
#             repo.find_by_email("nobody@example.com")
