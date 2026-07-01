# ============================================================
# L02: Dependency Injection in FastAPI
# ============================================================
# WHAT: FastAPI's dependency injection system lets you declare what a route
#       needs — a database session, the current user, pagination params,
#       settings — and FastAPI provides it. You use Depends() to declare a
#       dependency. Dependencies are plain Python functions or callables.
#       They can depend on other dependencies, forming a resolution tree.
#
# WHY:  DI solves three problems at once:
#       1. Testability  — override any dependency in tests without touching
#          production code (app.dependency_overrides).
#       2. Reusability  — write the "get current user" logic once, use it in
#          every protected route.
#       3. Composability — dependencies can chain; FastAPI resolves the whole
#          tree, calling each dependency exactly once per request.
#
# LEVEL: Foundation → Intermediate
# ============================================================
"""
CONCEPT OVERVIEW:
    Depends(fn) tells FastAPI: "call fn, inject its return value here."
    If fn itself has Depends() arguments, FastAPI resolves those first,
    working bottom-up. If the same dependency appears multiple times in the
    resolution tree (e.g. get_db is used by two sub-dependencies), FastAPI
    calls it ONCE per request and caches the result — safe and efficient.

    Generator dependencies (yield) allow setup + teardown in one function:
        def get_db():
            db = SessionLocal()
            try:
                yield db        # route handler runs here
            finally:
                db.close()      # runs even if an exception occurred

PRODUCTION USE CASE:
    Blog API with layered auth: get_db (session) → get_token (extract JWT)
    → get_current_user (decode + DB lookup) → require_active_user (check
    is_active flag) → require_admin (check role). Each layer is testable
    independently. The entire stack is declared in function signatures —
    no global request context, no thread-locals.

COMMON MISTAKES:
    1. Not yielding in a generator dependency — just returning closes nothing;
       the finally block never runs and you leak DB connections.
    2. Making the dependency do too much: it should provide a resource or
       enforce a single rule, not contain business logic.
    3. Forgetting that async def get_db() and def get_db() behave differently
       under load — async dependencies run in the event loop; sync ones run
       in a threadpool. Mix carefully.
    4. Using lru_cache without Depends — settings loaded via lru_cache are
       fine, but anything that holds a connection must use Depends + yield.
    5. Not overriding dependencies in tests — instead re-creating the whole
       app or hitting a real DB in unit tests. Use dependency_overrides.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional, Generator, AsyncGenerator, Annotated

from fastapi import (
    FastAPI, APIRouter, Depends, HTTPException, Query, Header, status,
)
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from pydantic_settings import BaseSettings  # pip install pydantic-settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ===========================================================================
# SETTINGS — loaded from environment / .env file via pydantic-settings
# @lru_cache ensures the .env is read exactly once, at first call.
# After that, every Depends(get_settings) returns the cached singleton.
# ===========================================================================

class Settings(BaseSettings):
    app_name: str = "Blog API"
    secret_key: str = "change-me-in-production-use-at-least-32-chars"
    database_url: str = "postgresql+asyncpg://user:pass@localhost/blog"
    redis_url: str = "redis://localhost:6379"
    debug: bool = False
    max_page_size: int = 1000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache                                   # called once; result cached forever
def get_settings() -> Settings:
    logger.info("Loading settings from environment / .env")
    return Settings()


# ===========================================================================
# FAKE RESOURCES — in production these would be real DB sessions, Redis, etc.
# ===========================================================================

class FakeAsyncSession:
    """Mimics an SQLAlchemy AsyncSession for illustration."""
    def __init__(self, name: str):
        self.name = name
        self.closed = False

    async def execute(self, query: str) -> list:
        return []                             # real: await session.execute(select(...))

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        self.closed = True
        logger.info("DB session '%s' closed", self.name)


# Simulated user store
USERS_DB: dict[int, dict] = {
    1: {"id": 1, "email": "alice@example.com", "role": "admin",   "is_active": True},
    2: {"id": 2, "email": "bob@example.com",   "role": "editor",  "is_active": True},
    3: {"id": 3, "email": "eve@example.com",   "role": "reader",  "is_active": False},
}

# Simulated valid API keys (real: store in DB or Redis set)
VALID_API_KEYS: set[str] = {"prod-key-abc123", "dev-key-xyz789"}


# ===========================================================================
# PYDANTIC SCHEMAS
# ===========================================================================

class UserOut(BaseModel):
    id: int
    email: str
    role: str
    is_active: bool


class PostOut(BaseModel):
    id: int
    title: str
    author_id: int


class PaginationParams(BaseModel):
    """Typed container for pagination state — returned by the dependency."""
    skip: int
    limit: int


# ===========================================================================
# SIMPLE DEPENDENCIES
# ===========================================================================

# --- 1. Database session (generator / yield dependency) -------------------
# The `yield` makes this a context manager. FastAPI calls next() to get the
# session, injects it, then continues the generator (closing the session)
# after the route handler returns — even if an exception is raised.

async def get_db() -> AsyncGenerator[FakeAsyncSession, None]:
    session = FakeAsyncSession(name="request-session")
    logger.info("DB session opened")
    try:
        yield session                        # route handler runs here
        await session.commit()              # commit if handler succeeded
    except Exception:
        await session.rollback()            # rollback on any exception
        raise                               # re-raise so FastAPI returns 500
    finally:
        await session.close()               # ALWAYS close, success or failure


# Type alias — cleaner signatures throughout the file
DBSession = Annotated[FakeAsyncSession, Depends(get_db)]


# --- 2. Pagination parameters — reusable across all list endpoints ---------
# Query parameters declared here apply to every route that depends on this.
# The Query(le=...) constraint is enforced automatically — 422 if violated.

def get_pagination(
    skip: int = Query(default=0,   ge=0,    description="Number of records to skip"),
    limit: int = Query(default=20, ge=1, le=1000, description="Max records to return"),
) -> PaginationParams:
    return PaginationParams(skip=skip, limit=limit)


Pagination = Annotated[PaginationParams, Depends(get_pagination)]


# ===========================================================================
# SECURITY DEPENDENCIES
# ===========================================================================

# OAuth2PasswordBearer: looks for "Authorization: Bearer <token>" in headers.
# It is just a Callable that extracts the token string — nothing more.
# tokenUrl points to the endpoint that issues tokens (shown in /docs).

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


async def get_token(token: str = Depends(oauth2_scheme)) -> str:
    """Return the raw JWT string extracted from the Authorization header."""
    return token


async def get_current_user(
    token: str = Depends(get_token),         # depends on get_token
    db: FakeAsyncSession = Depends(get_db),  # depends on get_db — shares session
    settings: Settings = Depends(get_settings),
) -> UserOut:
    """
    Decode the JWT, look up the user in the DB.
    This is the central auth dependency — every protected route uses it.
    In production: use `jose.jwt.decode(token, settings.secret_key, algorithms=["HS256"])`.
    """
    # Simulate JWT decode — in real code: decode and extract sub (user_id)
    if token == "invalid":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},   # RFC 6750 requires this
        )

    # Simulate extracting user_id from token payload
    user_id = 1 if "admin" in token else 2   # real: jwt.decode(...)["sub"]
    user = USERS_DB.get(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")

    return UserOut(**user)


CurrentUser = Annotated[UserOut, Depends(get_current_user)]


# --- 3. Active user guard — chains from get_current_user ------------------

async def require_active_user(current_user: CurrentUser) -> UserOut:
    """Raises 403 if the account is deactivated. Chains on get_current_user."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact support.",
        )
    return current_user


ActiveUser = Annotated[UserOut, Depends(require_active_user)]


# ===========================================================================
# CLASS-BASED DEPENDENCY — for parameterised dependencies
# Use when you need to inject configuration into a dependency at declaration
# time (e.g., which role is required). The instance is the dependency.
# ===========================================================================

class RequireRole:
    """
    Parameterised dependency factory.
    Usage: Depends(RequireRole("admin"))
    The __call__ method is what FastAPI actually calls per request.
    """

    def __init__(self, required_role: str) -> None:
        self.required_role = required_role   # set once at route definition

    async def __call__(self, current_user: ActiveUser) -> UserOut:
        # current_user is already validated as active — we just check role
        if current_user.role != self.required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{self.required_role}' required; you have '{current_user.role}'.",
            )
        return current_user


# Convenience aliases — declare role requirements at definition site
require_admin = RequireRole("admin")
require_editor = RequireRole("editor")


# ===========================================================================
# API KEY DEPENDENCY — for machine-to-machine auth
# APIKeyHeader reads a custom header; validate against a set or DB lookup.
# ===========================================================================

from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: Optional[str] = Depends(api_key_header),
) -> str:
    """
    Machine-to-machine auth via X-API-Key header.
    auto_error=False: FastAPI won't auto-raise if header is missing — we
    handle it ourselves for a cleaner error message.
    """
    if not api_key or api_key not in VALID_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key.",
        )
    return api_key


# ===========================================================================
# APP + ROUTERS
# ===========================================================================

app = FastAPI(title="Blog API — Dependency Injection Demo")

# Router with a GLOBAL dependency: every route here requires a valid API key.
# You do not need to add Depends(verify_api_key) to each route individually.
internal_router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(verify_api_key)],  # applied to ALL routes in router
)


@internal_router.get("/stats")
async def internal_stats(settings: Settings = Depends(get_settings)) -> dict:
    """Only reachable with a valid X-API-Key header."""
    return {"app": settings.app_name, "debug": settings.debug}


# Public blog router — no global dependency; each route declares its own
blog_router = APIRouter(prefix="/posts", tags=["posts"])


@blog_router.get("/", response_model=list[PostOut])
async def list_posts(
    pagination: Pagination,                  # reusable query-param dependency
    db: DBSession,                           # DB session, auto-closed after request
) -> list[PostOut]:
    """
    Public list — no auth required. Pagination params injected automatically.
    ?skip=0&limit=20 → pagination.skip=0, pagination.limit=20
    """
    logger.info("Listing posts: skip=%d limit=%d", pagination.skip, pagination.limit)
    # Real: await db.execute(select(Post).offset(pagination.skip).limit(pagination.limit))
    return [PostOut(id=1, title="Hello FastAPI", author_id=1)]


@blog_router.get("/{post_id}", response_model=PostOut)
async def get_post(post_id: int, db: DBSession) -> PostOut:
    """Fetch a single post. DB session auto-managed."""
    # Real: result = await db.execute(select(Post).where(Post.id == post_id))
    if post_id != 1:
        raise HTTPException(status_code=404, detail="Post not found.")
    return PostOut(id=1, title="Hello FastAPI", author_id=1)


@blog_router.post("/", status_code=status.HTTP_201_CREATED, response_model=PostOut)
async def create_post(
    title: str,
    current_user: ActiveUser,               # must be logged in AND active
    db: DBSession,
) -> PostOut:
    """Create a post. Requires an active authenticated user."""
    logger.info("User %d creating post: %s", current_user.id, title)
    # Real: session.add(Post(title=title, author_id=current_user.id))
    return PostOut(id=99, title=title, author_id=current_user.id)


@blog_router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: int,
    _admin: UserOut = Depends(require_admin),  # underscore: we only care it passes
    db: DBSession = Depends(get_db),
) -> None:
    """Delete a post. Admin only — RequireRole("admin") enforces this."""
    logger.info("Admin deleting post %d", post_id)
    # Real: await db.execute(delete(Post).where(Post.id == post_id))


app.include_router(blog_router)
app.include_router(internal_router)


# ===========================================================================
# TESTING WITH DEPENDENCY OVERRIDES
# This section is NOT a real test file — it illustrates the pattern.
# In your test suite (pytest + httpx.AsyncClient), you would do this:
# ===========================================================================

def demonstrate_dependency_override() -> None:
    """
    Shows how to replace get_db with a mock in tests — no production code
    changes needed. Override is scoped to the app object for the test session.
    """
    from unittest.mock import AsyncMock

    mock_session = AsyncMock(spec=FakeAsyncSession)

    # Override the dependency — all routes that Depend(get_db) now get mock_session
    app.dependency_overrides[get_db] = lambda: mock_session

    # Run your test here with httpx.AsyncClient(app=app, base_url="http://test")
    # ...

    # Clean up — restore real dependency after test
    app.dependency_overrides.clear()


# ===========================================================================
# ENTRY POINT
# ===========================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("L02_dependency_injection:app", host="0.0.0.0", port=8001, reload=True)
