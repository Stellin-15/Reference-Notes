# =============================================================================
# WHAT: FastAPI Testing — TestClient, AsyncClient, fixtures, mocking, coverage
# WHY:  Untested APIs break silently in production. Proper test suites catch
#       regressions, document expected behavior, and give confidence to refactor.
# LEVEL: Intermediate → Advanced
# =============================================================================

# CONCEPT OVERVIEW
# ─────────────────
# FastAPI testing revolves around two clients:
#   1. TestClient   — wraps httpx under the hood, synchronous, great for most tests
#   2. AsyncClient  — truly async, required when your route does async-only work
#
# The killer feature is dependency_overrides: swap real DB/services for mocks
# without changing any production code. Tests stay isolated, fast, and repeatable.
#
# PRODUCTION USE CASE
# ────────────────────
# A SaaS platform runs 3,000+ unit + integration tests in CI. Each PR triggers
# the full suite (~ 4 min). dependency_overrides swap the real Postgres for a
# test DB that rolls back after each test. External APIs (Stripe, SendGrid,
# OpenAI) are mocked with pytest-httpx. Load tests run nightly with Locust to
# detect regressions before deployment.
#
# COMMON MISTAKES
# ────────────────
# 1. Using SQLite for tests when prod uses PostgreSQL — behavior differs (JSON
#    columns, ON CONFLICT, CTEs). Always test against the same DB engine.
# 2. Forgetting to reset dependency_overrides — bleeds state between tests.
# 3. Not testing 422 validation errors — they're the most common user-facing bug.
# 4. Over-mocking: mocking too deeply means you're testing your mock, not code.
# 5. Testing FastAPI internals (routing, pydantic) — test YOUR logic instead.

# ── Imports ──────────────────────────────────────────────────────────────────
import pytest
import factory
import httpx

from typing import Generator, AsyncGenerator
from unittest.mock import AsyncMock, patch

# FastAPI testing
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.testclient import TestClient  # sync client, wraps httpx
from fastapi.websockets import WebSocket

# Database (SQLAlchemy async)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer

# ── Minimal app for demonstration ────────────────────────────────────────────

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id:    Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    role:  Mapped[str] = mapped_column(String, default="user")

# In real projects this lives in app/database.py
# We define it here so the file is self-contained
TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/test_db"

# Dependency that routes inject — the thing we'll OVERRIDE in tests
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Real database session dependency. Replaced in tests via overrides."""
    # In production: yield a real AsyncSession from the engine
    raise NotImplementedError("Replace this via dependency_overrides in tests")

app = FastAPI(title="Test Demo App")

@app.get("/users/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    """Fetch a user by ID. Returns 404 if not found."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user.id, "email": user.email, "role": user.role}

@app.post("/users", status_code=201)
async def create_user(email: str, role: str = "user", db: AsyncSession = Depends(get_db)):
    """Create a user. Returns 422 if email is missing (Pydantic validates)."""
    user = User(email=email, role=role)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"id": user.id, "email": user.email}

@app.post("/auth/token")
async def login(username: str, password: str, db: AsyncSession = Depends(get_db)):
    """Simple auth endpoint — returns a fake JWT for demo purposes."""
    # Real implementation would verify hash, generate JWT
    if password != "correct-password":
        raise HTTPException(status_code=401, detail="Bad credentials")
    return {"access_token": f"fake-token-for-{username}", "token_type": "bearer"}

@app.get("/me")
async def get_me(authorization: str = None):
    """Protected endpoint — reads from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.replace("Bearer ", "")
    # Real: decode JWT, look up user
    return {"token": token, "user": "decoded-from-token"}

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket echo endpoint for testing."""
    await websocket.accept()
    data = await websocket.receive_json()
    await websocket.send_json({"echo": data, "client": client_id})
    await websocket.close()

@app.post("/notify")
async def send_notification(email: str, message: str):
    """Calls an external email API — must be mocked in tests."""
    import httpx as _httpx
    async with _httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.sendgrid.com/v3/mail/send",
            json={"to": email, "text": message},
            headers={"Authorization": "Bearer SG.fake"}
        )
        response.raise_for_status()
    return {"status": "sent"}

# =============================================================================
# PYTEST FIXTURES
# =============================================================================

# ── In-memory SQLite engine for tests (accept the trade-offs) ────────────────
# For demos we use SQLite; for production tests, point at a real Postgres test DB
SQLITE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="session")
def event_loop_policy():
    """Use default asyncio event loop policy for the test session."""
    import asyncio
    return asyncio.DefaultEventLoopPolicy()

@pytest.fixture(scope="session")
async def test_engine():
    """
    Create the test database engine ONCE per session.
    scope="session" means this runs once for all tests — engine creation is expensive.
    """
    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        # Create all tables defined in Base metadata
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    # Teardown: drop all tables when session ends
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Provides a clean DB session per test with automatic rollback.

    Pattern: begin a transaction → run test → rollback (never commit to disk).
    This means each test starts with a clean slate without truncating tables.
    For Postgres: use SAVEPOINT for nested transactions (supports rollback).
    """
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_factory() as session:
        async with session.begin():          # start transaction
            yield session                    # give session to test
            await session.rollback()         # rollback after test — clean state

@pytest.fixture
def client(db_session: AsyncSession) -> Generator[TestClient, None, None]:
    """
    TestClient with DB dependency overridden.

    This is the key FastAPI testing pattern:
      - Production code calls get_db() → real Postgres
      - Tests call get_db() → this db_session (rolls back after each test)
    """
    # Override the dependency: any route that Depends(get_db) gets db_session
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    # CRITICAL: reset overrides after each test to avoid bleeding into other tests
    app.dependency_overrides = {}

@pytest.fixture
def auth_headers(client: TestClient) -> dict:
    """
    Fixture that logs in and returns Authorization headers.
    Reusable: any test that needs auth just depends on this fixture.
    """
    response = client.post(
        "/auth/token",
        params={"username": "admin@example.com", "password": "correct-password"}
    )
    assert response.status_code == 200, f"Login failed: {response.json()}"
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

# =============================================================================
# FACTORY BOY — test data generation
# =============================================================================

class UserFactory(factory.alchemy.SQLAlchemyModelFactory):
    """
    Factory for creating User records in tests.
    factory.Faker() generates realistic random data — no more "test@test.com".
    Usage:
        user = UserFactory.create()                    # random user
        admin = UserFactory.create(role="admin")       # override specific field
        users = UserFactory.create_batch(5)            # create 5 users at once
    """
    class Meta:
        model = User
        # sqlalchemy_session is set per-test (see conftest in real projects)
        sqlalchemy_session_persistence = "commit"

    # Each call generates a unique realistic email
    email = factory.Faker("email")
    role  = factory.Iterator(["user", "admin", "moderator"])

# =============================================================================
# ACTUAL TESTS
# =============================================================================

class TestUserCRUD:
    """Test suite for user CRUD endpoints."""

    def test_get_user_returns_200(self, client: TestClient, db_session: AsyncSession):
        """
        Happy path: user exists, GET returns 200 with correct data.
        We manually insert a user because Factory Boy needs sync session for SQLite demo.
        In real projects, use UserFactory.create() with the session.
        """
        # Arrange: directly run coroutine to insert test data
        import asyncio
        async def _insert():
            user = User(id=1, email="alice@example.com", role="admin")
            db_session.add(user)
            # Note: we don't commit — rollback fixture handles cleanup

        asyncio.get_event_loop().run_until_complete(_insert())

        # Act
        response = client.get("/users/1")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "alice@example.com"
        assert data["role"] == "admin"

    def test_get_user_404_when_not_found(self, client: TestClient):
        """
        Non-existent user returns 404.
        Tests the HTTPException path — very common to forget this.
        """
        response = client.get("/users/99999")

        assert response.status_code == 404
        assert response.json()["detail"] == "User not found"

    def test_create_user_returns_201(self, client: TestClient):
        """POST /users creates a user and returns 201 Created."""
        response = client.post("/users", params={"email": "bob@example.com"})

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "bob@example.com"
        assert "id" in data  # ID was assigned by DB

    def test_create_user_missing_email_returns_422(self, client: TestClient):
        """
        422 Unprocessable Entity when required field is missing.
        FastAPI/Pydantic generates this automatically — but you must TEST it.
        Ensures your schema validation is wired correctly.
        """
        response = client.post("/users")  # no email param

        # 422 = validation error, not 400 (bad request) or 500 (server error)
        assert response.status_code == 422
        errors = response.json()["detail"]
        # Pydantic returns a list of field errors
        assert any("email" in str(e) for e in errors)


class TestAuthentication:
    """Tests for auth flow: login → get token → use token."""

    def test_login_returns_token(self, client: TestClient):
        """Correct credentials → 200 with access_token."""
        response = client.post(
            "/auth/token",
            params={"username": "user@example.com", "password": "correct-password"}
        )
        assert response.status_code == 200
        assert "access_token" in response.json()
        assert response.json()["token_type"] == "bearer"

    def test_login_wrong_password_returns_401(self, client: TestClient):
        """Wrong password → 401 Unauthorized (not 403 Forbidden)."""
        response = client.post(
            "/auth/token",
            params={"username": "user@example.com", "password": "wrong-password"}
        )
        assert response.status_code == 401

    def test_protected_endpoint_with_valid_token(self, client: TestClient, auth_headers: dict):
        """
        Full auth flow test: use auth_headers fixture (which already logged in).
        This is the recommended pattern — auth_headers fixture is reusable.
        """
        response = client.get("/me", headers=auth_headers)
        assert response.status_code == 200

    def test_protected_endpoint_without_token_returns_401(self, client: TestClient):
        """No Authorization header → 401."""
        response = client.get("/me")  # no headers
        assert response.status_code == 401


class TestWebSocket:
    """WebSocket connection tests using TestClient's websocket_connect()."""

    def test_websocket_echo(self, client: TestClient):
        """
        Connect to WebSocket, send JSON, receive echo.
        client.websocket_connect() is a context manager — connection closes on exit.
        """
        with client.websocket_connect("/ws/client-123") as websocket:
            # Send a message
            websocket.send_json({"message": "hello", "type": "chat"})
            # Receive the response
            data = websocket.receive_json()

        assert data["echo"]["message"] == "hello"
        assert data["client"] == "client-123"


class TestExternalServiceMocking:
    """Tests that mock external HTTP calls using pytest-httpx."""

    def test_send_notification_mocks_sendgrid(self, client: TestClient):
        """
        Mock the SendGrid HTTP call. Without mocking, this would:
        - Hit real SendGrid API (slow, costs money, flaky in CI)
        - Require real API keys in test environment
        pytest-httpx intercepts httpx calls and returns mock responses.

        Usage requires: pip install pytest-httpx
        The httpx_mock fixture is provided by the pytest-httpx plugin.
        """
        # In real usage, use the httpx_mock fixture from pytest-httpx:
        # def test_notify(client, httpx_mock):
        #     httpx_mock.add_response(
        #         method="POST",
        #         url="https://api.sendgrid.com/v3/mail/send",
        #         status_code=202
        #     )
        #     response = client.post("/notify", params={...})
        #     assert response.status_code == 200
        #
        # For this demo, we use unittest.mock.patch:
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.status_code = 202
            mock_post.return_value.raise_for_status = lambda: None

            response = client.post(
                "/notify",
                params={"email": "user@example.com", "message": "Welcome!"}
            )

        # Verify the external API was called (not just that our code ran)
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "sendgrid.com" in str(call_kwargs)


# =============================================================================
# PARAMETRIZE — same test, multiple inputs
# =============================================================================

@pytest.mark.parametrize("email,expected_valid", [
    ("valid@example.com", True),
    ("also.valid+tag@subdomain.example.co.uk", True),
    ("notanemail", False),          # missing @ and domain
    ("missing@", False),            # incomplete domain
    ("@nodomain.com", False),       # missing local part
    ("", False),                    # empty string
])
def test_email_validation_parametrize(client: TestClient, email: str, expected_valid: bool):
    """
    @pytest.mark.parametrize runs the same test body with each set of inputs.
    This is far better than writing 6 separate test functions.
    Here we check that FastAPI's Pydantic validation correctly accepts/rejects emails.

    Note: FastAPI validates query params as strings, not email format by default.
    In real code, use EmailStr from pydantic for proper email validation.
    This demo tests the 422 behavior when email is empty.
    """
    if not expected_valid and not email:
        # Empty email should fail validation
        response = client.post("/users", params={"email": email})
        # Depending on your schema, this might be 422 or 400
        assert response.status_code in (422, 400)
    else:
        # For this demo, just check the endpoint accepts/rejects gracefully
        response = client.post("/users", params={"email": email})
        assert response.status_code in (201, 422)  # created or validation error


# =============================================================================
# ASYNC CLIENT — for truly async test scenarios
# =============================================================================

@pytest.mark.anyio  # requires anyio or pytest-anyio installed
async def test_async_client_example():
    """
    Use httpx.AsyncClient when you need to test async code paths accurately.
    TestClient runs in a sync context and may hide async bugs.
    AsyncClient is more faithful to how your app runs in production.

    Requires: pip install anyio pytest-anyio
    Mark the test with @pytest.mark.anyio (or @pytest.mark.asyncio with pytest-asyncio).
    """
    # Override dependency for async test
    app.dependency_overrides[get_db] = AsyncMock()

    async with httpx.AsyncClient(app=app, base_url="http://test") as ac:
        # Can await multiple requests concurrently — tests async behavior
        response = await ac.get("/me", headers={"Authorization": "Bearer fake-token"})

    assert response.status_code == 200

    # Cleanup
    app.dependency_overrides = {}


# =============================================================================
# LOAD TESTING WITH LOCUST (conceptual — runs as separate process)
# =============================================================================

# Locust load test (save as locustfile.py, run separately):
#
#   from locust import HttpUser, task, between
#
#   class APIUser(HttpUser):
#       # Each simulated user waits 1-3 seconds between tasks
#       wait_time = between(1, 3)
#
#       def on_start(self):
#           """Called once per simulated user — login and store token."""
#           resp = self.client.post("/auth/token",
#               params={"username": "test@ex.com", "password": "correct-password"})
#           self.token = resp.json()["access_token"]
#           self.headers = {"Authorization": f"Bearer {self.token}"}
#
#       @task(3)   # weight 3 — called 3x more often than weight-1 tasks
#       def get_user(self):
#           self.client.get("/users/1", headers=self.headers)
#
#       @task(1)
#       def create_user(self):
#           self.client.post("/users",
#               params={"email": f"load-{self.user_id}@test.com"},
#               headers=self.headers)
#
# Run: locust -f locustfile.py --headless -u 100 -r 10 --run-time 60s
#   -u 100 = 100 concurrent users
#   -r 10  = ramp up 10 users/second (reach 100 in 10 seconds)
#   --run-time 60s = run for 60 seconds then stop
# Find p95, p99 latency and the requests-per-second at which errors start.

# =============================================================================
# COVERAGE
# =============================================================================

# Run tests with coverage:
#   pytest --cov=app --cov-report=html --cov-report=term-missing
#
# This generates:
#   - Terminal output showing % covered per file + which lines are missing
#   - htmlcov/index.html — visual report, click to see uncovered lines
#
# Coverage targets (pragmatic, not dogmatic):
#   - Business logic (services, validators): 90%+
#   - API routes:                            80%+
#   - Database models:                       70%+
#   - Overall:                               75%+
#   - Utility helpers:                       60%+ (some are trivial)
#
# DO NOT aim for 100% — you'll end up testing print statements and __repr__.
# Coverage is a signal, not a goal. A test that covers a line without asserting
# anything is worse than no test (false confidence).
#
# .coveragerc (put in project root):
#   [run]
#   source = app
#   omit = app/migrations/*, app/tests/*, */conftest.py
#   [report]
#   exclude_lines = pragma: no cover, def __repr__, if TYPE_CHECKING:

# =============================================================================
# CONFTEST.PY STRUCTURE (real project)
# =============================================================================
# tests/
# ├── conftest.py          ← session/module fixtures (engine, event loop)
# ├── fixtures/
# │   ├── db.py            ← db_session fixture
# │   ├── client.py        ← TestClient fixture with overrides
# │   └── factories.py     ← Factory Boy classes
# ├── unit/
# │   ├── test_services.py ← pure logic, no HTTP
# │   └── test_validators.py
# └── integration/
#     ├── test_users.py    ← full HTTP round-trip
#     ├── test_auth.py
#     └── test_websockets.py
