# ============================================================
# L03: Async FastAPI with SQLAlchemy 2.0 and PostgreSQL
# ============================================================
# WHAT: Async IO in FastAPI — using SQLAlchemy 2.0's async engine with
#       asyncpg, Redis caching with redis.asyncio, and httpx for outbound
#       HTTP calls. Covers the N+1 query problem, Alembic migrations, and
#       connection pool configuration. Everything that touches the network
#       is non-blocking — the event loop handles thousands of concurrent
#       requests on a single thread.
#
# WHY:  A synchronous DB call blocks the thread — the entire server pauses
#       for that request. With async, while one request waits for Postgres,
#       the event loop processes a hundred other requests. This is why a
#       single uvicorn worker can handle far more concurrent users than a
#       sync Django/Flask worker of the same hardware.
#
# LEVEL: Intermediate
# ============================================================
"""
CONCEPT OVERVIEW:
    Python's asyncio event loop is single-threaded. Async functions use
    `await` to yield control back to the loop while waiting for IO. The
    loop then runs another coroutine that is ready. As long as you never
    call a blocking function (time.sleep, requests.get, a sync DB driver),
    the loop stays responsive.

    SQLAlchemy 2.0 introduces:
      - create_async_engine()   — wraps asyncpg, returns a non-blocking engine
      - AsyncSession            — all queries are coroutines (await required)
      - select() syntax         — replaces the old session.query() API entirely
      - async_sessionmaker()    — factory for creating sessions

    The key mental model:
        async def handler():
            async with AsyncSession(engine) as session:
                result = await session.execute(select(User).where(User.id == 1))
                user = result.scalar_one_or_none()

PRODUCTION USE CASE:
    High-traffic news API: 50k RPM, 200 concurrent DB connections pooled
    across workers. Redis caches hot articles for 60 seconds. httpx fetches
    external content enrichment. Alembic handles all schema changes — no
    manual ALTER TABLE ever touches production.

COMMON MISTAKES:
    1. Using `requests` (sync HTTP) in an async route — blocks the event
       loop. Always use `httpx.AsyncClient` or `aiohttp` instead.
    2. Forgetting `await` before session.execute() — no error, but the
       coroutine is never scheduled and you get a coroutine object back.
    3. N+1 queries: loading a list of users and then accessing user.posts
       in a loop triggers one DB round-trip per user. Fix: eager load with
       selectinload() at query time.
    4. Not closing the httpx.AsyncClient — each request that creates a
       new client spawns connection overhead. Create once at startup, reuse.
    5. Running sync Alembic migrations against the async engine directly —
       Alembic needs a sync connection for its internal tracking tables.
       Use run_sync() in env.py.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator, Any

# ---- SQLAlchemy 2.0 async --------------------------------------------------
from sqlalchemy import String, Integer, Boolean, ForeignKey, Text, select, delete
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncAttrs,        # mixin that makes relationship access async-safe
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship,
    selectinload,      # eager-loads relationships in a second SELECT (avoids N+1)
    joinedload,        # eager-loads via JOIN — use for *-to-one only
)

# ---- FastAPI ---------------------------------------------------------------
from fastapi import FastAPI, APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ---- Redis async client ----------------------------------------------------
# pip install redis[asyncio]  (redis >= 4.2)
try:
    import redis.asyncio as aioredis          # official async support in redis-py
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False                   # gracefully skip Redis in demo

# ---- Async HTTP client ------------------------------------------------------
# pip install httpx
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===========================================================================
# CONFIGURATION
# In production these come from environment variables / Secrets Manager.
# ===========================================================================

DATABASE_URL = "postgresql+asyncpg://user:password@localhost:5432/newsdb"
# asyncpg is the fastest PostgreSQL async driver — pure Python + C extension
# psycopg3 is an alternative: supports both sync and async, closer to DBAPI2

REDIS_URL = "redis://localhost:6379/0"
CACHE_TTL_SECONDS = 60                       # articles cached for 60 seconds

EXTERNAL_API_URL = "https://api.example.com/enrich"  # mock enrichment endpoint


# ===========================================================================
# SQLALCHEMY 2.0 SETUP
# ===========================================================================

# pool_size: connections kept alive in the pool
# max_overflow: extra connections allowed above pool_size (temporarily)
# pool_timeout: seconds to wait for a connection before raising PoolTimeout
# pool_pre_ping: sends "SELECT 1" before each checkout — detects stale connections

engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,          # keep 20 connections alive — tune per CPU core count
    max_overflow=10,       # allow 30 total under burst load
    pool_timeout=30,       # wait 30 s for a free connection before failing
    pool_pre_ping=True,    # detects dropped connections (e.g., after Postgres restart)
    echo=False,            # set True in dev to log all SQL — NEVER in production
)

# async_sessionmaker replaces sessionmaker for async code
# expire_on_commit=False: objects stay usable after commit (important in async)
AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # without this, accessing obj.field after commit hits DB again
    autocommit=False,
    autoflush=False,         # manual flush control — safer in complex transactions
)


# ===========================================================================
# ORM MODELS — SQLAlchemy 2.0 "mapped_column" style
# DeclarativeBase is the new way (replaces declarative_base())
# ===========================================================================

class Base(AsyncAttrs, DeclarativeBase):
    """AsyncAttrs mixin makes lazy-loaded relationships raise an error
    instead of silently triggering a sync DB call in async code."""
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationship — NOT loaded by default. Must be explicitly eager-loaded.
    posts: Mapped[list["Article"]] = relationship("Article", back_populates="author")


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    author: Mapped["User"] = relationship("User", back_populates="posts")


# ===========================================================================
# PYDANTIC SCHEMAS
# ===========================================================================

class ArticleCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    body: str = Field(..., min_length=1)
    author_id: int


class ArticleOut(BaseModel):
    id: int
    title: str
    body: str
    published: bool
    author_id: int
    model_config = {"from_attributes": True}


class ArticleWithAuthor(ArticleOut):
    """Extended response that includes nested author info."""
    author_name: str     # flattened — not returning the full User object


# ===========================================================================
# REDIS + HTTPX CLIENTS — created at startup, shared across all requests
# Creating a new httpx.AsyncClient per request wastes connections and DNS.
# ===========================================================================

redis_client: Optional[Any] = None          # set in lifespan
http_client: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables, Redis connection, and httpx client at startup."""
    global redis_client, http_client

    # --- DB: create tables if they don't exist (dev shortcut) ---
    # In production: use Alembic migrations, never create_all() in prod
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified / created.")

    # --- Redis: single connection pool shared across all requests ---
    if REDIS_AVAILABLE:
        redis_client = aioredis.from_url(
            REDIS_URL,
            encoding="utf-8",               # return str instead of bytes
            decode_responses=True,          # auto-decode all responses to str
            socket_connect_timeout=5,       # fail fast if Redis is unreachable
        )
        logger.info("Redis connection pool ready.")

    # --- httpx: persistent client with connection pooling ---
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(10.0),        # 10 s total timeout (connect + read)
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,   # keep 20 connections warm
        ),
    )
    logger.info("httpx.AsyncClient ready.")

    yield                                   # app runs here

    # --- Shutdown ---
    if redis_client:
        await redis_client.aclose()
    if http_client:
        await http_client.aclose()          # releases all open HTTP connections
    await engine.dispose()                  # return connections to pool, then close pool
    logger.info("All connections closed.")


# ===========================================================================
# DB SESSION DEPENDENCY — async yield pattern
# Opens a session per request, commits on success, rollbacks on exception.
# ===========================================================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()          # commit if no exception was raised
        except Exception:
            await session.rollback()        # rollback if anything failed
            raise


# ===========================================================================
# CACHE HELPERS — Redis get/set abstraction
# Using a prefix avoids key collisions when the cache is shared.
# ===========================================================================

CACHE_PREFIX = "article:"


async def cache_get(key: str) -> Optional[str]:
    """Return cached value or None if missing / Redis unavailable."""
    if not redis_client:
        return None
    try:
        return await redis_client.get(f"{CACHE_PREFIX}{key}")
    except Exception as e:
        logger.warning("Redis GET failed: %s", e)
        return None                         # degrade gracefully — hit the DB


async def cache_set(key: str, value: str, ttl: int = CACHE_TTL_SECONDS) -> None:
    """Store value with TTL. Fire-and-forget — don't fail if Redis is down."""
    if not redis_client:
        return
    try:
        await redis_client.setex(f"{CACHE_PREFIX}{key}", ttl, value)
    except Exception as e:
        logger.warning("Redis SET failed: %s", e)


async def cache_delete(key: str) -> None:
    """Invalidate a single cache entry (call on article update/delete)."""
    if not redis_client:
        return
    await redis_client.delete(f"{CACHE_PREFIX}{key}")


# ===========================================================================
# EXTERNAL API CALL — using httpx.AsyncClient (never use requests in async!)
# requests.get() calls socket.recv() which BLOCKS the event loop thread.
# httpx.AsyncClient.get() suspends the coroutine and yields to the loop.
# ===========================================================================

async def enrich_article(article_id: int) -> dict:
    """Fetch metadata from an external enrichment API."""
    if not http_client:
        return {}
    try:
        response = await http_client.get(
            f"{EXTERNAL_API_URL}/{article_id}",
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()         # raises httpx.HTTPStatusError on 4xx/5xx
        return response.json()
    except httpx.TimeoutException:
        logger.warning("Enrichment API timed out for article %d", article_id)
        return {}
    except httpx.HTTPStatusError as e:
        logger.warning("Enrichment API returned %d for article %d", e.response.status_code, article_id)
        return {}


# ===========================================================================
# DATABASE QUERY FUNCTIONS
# Keep queries out of route handlers — easier to test and reuse.
# ===========================================================================

async def get_article_by_id(session: AsyncSession, article_id: int) -> Optional[Article]:
    """
    Fetch a single article with its author eagerly loaded.
    selectinload: runs a SECOND query to load User records for all returned
    articles — "SELECT * FROM users WHERE id IN (...)".
    This avoids N+1 but produces 2 queries. Use joinedload for *-to-one when
    you always need the related object (produces 1 query with a JOIN).
    """
    result = await session.execute(
        select(Article)
        .where(Article.id == article_id)
        .options(joinedload(Article.author))  # JOIN — fine for single record
    )
    return result.scalar_one_or_none()       # None if not found, Article if found


async def get_articles_paginated(
    session: AsyncSession,
    skip: int = 0,
    limit: int = 20,
    published_only: bool = True,
) -> list[Article]:
    """
    Fetch multiple articles with eager-loaded authors.
    selectinload is preferred over joinedload for collections — joinedload
    on a collection produces a cartesian product, inflating row count.
    """
    stmt = (
        select(Article)
        .options(selectinload(Article.author))  # separate SELECT, no cartesian product
        .offset(skip)
        .limit(limit)
        .order_by(Article.id.desc())
    )
    if published_only:
        stmt = stmt.where(Article.published.is_(True))

    result = await session.execute(stmt)
    return list(result.scalars().all())      # scalars() unwraps the Row wrappers


async def create_article_in_db(
    session: AsyncSession, data: ArticleCreate
) -> Article:
    """Insert a new article. Session.add() stages the object; flush() sends SQL."""
    article = Article(
        title=data.title,
        body=data.body,
        author_id=data.author_id,
        published=False,
    )
    session.add(article)                     # stage the INSERT
    await session.flush()                    # send SQL, populate article.id
    await session.refresh(article)           # reload from DB to get DB-generated defaults
    return article


async def delete_article_from_db(session: AsyncSession, article_id: int) -> bool:
    """Delete an article. Returns True if a row was deleted, False if not found."""
    result = await session.execute(
        delete(Article).where(Article.id == article_id)
    )
    return result.rowcount > 0              # rowcount = number of rows affected


# ===========================================================================
# APP + ROUTES
# ===========================================================================

app = FastAPI(title="News API — Async + PostgreSQL + Redis", lifespan=lifespan)
router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("/", response_model=list[ArticleOut])
async def list_articles(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
) -> list[ArticleOut]:
    """List published articles with pagination. No caching — list changes often."""
    articles = await get_articles_paginated(db, skip=skip, limit=limit)
    return [ArticleOut.model_validate(a) for a in articles]


@router.get("/{article_id}", response_model=ArticleWithAuthor)
async def get_article(
    article_id: int,
    db: AsyncSession = Depends(get_db),
) -> ArticleWithAuthor:
    """
    Fetch one article. Check Redis cache first — avoids DB hit on hot articles.
    Cache-aside pattern:
        1. Check cache.
        2. Cache hit  → return immediately (no DB).
        3. Cache miss → query DB → store in cache → return.
    """
    import json

    # 1. Try cache
    cached = await cache_get(str(article_id))
    if cached:
        logger.info("Cache HIT for article %d", article_id)
        data = json.loads(cached)
        return ArticleWithAuthor(**data)

    # 2. Cache miss — query DB
    logger.info("Cache MISS for article %d — querying DB", article_id)
    article = await get_article_by_id(db, article_id)
    if not article:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found.")

    out = ArticleWithAuthor(
        id=article.id,
        title=article.title,
        body=article.body,
        published=article.published,
        author_id=article.author_id,
        author_name=article.author.name if article.author else "Unknown",
    )

    # 3. Store in cache for next request
    await cache_set(str(article_id), out.model_dump_json())

    return out


@router.post("/", response_model=ArticleOut, status_code=status.HTTP_201_CREATED)
async def create_article(
    data: ArticleCreate,
    db: AsyncSession = Depends(get_db),
) -> ArticleOut:
    """Create an article and optionally call external enrichment API."""
    article = await create_article_in_db(db, data)

    # Call external API concurrently — could also use asyncio.gather() for multiple
    enrichment = await enrich_article(article.id)
    if enrichment:
        logger.info("Enrichment data for article %d: %s", article.id, enrichment)

    return ArticleOut.model_validate(article)


@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_article(
    article_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an article and invalidate its cache entry."""
    deleted = await delete_article_from_db(db, article_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found.")

    # Invalidate cache — stale entry would serve deleted content
    await cache_delete(str(article_id))


app.include_router(router)


# ===========================================================================
# ALEMBIC MIGRATION NOTES (not runnable here — reference for setup)
# ===========================================================================
# 1. pip install alembic
# 2. alembic init alembic         → creates alembic/ directory and alembic.ini
# 3. Edit alembic/env.py:
#
#     from app.models import Base          # import your Base
#     target_metadata = Base.metadata
#
#     # For async engines, env.py needs run_sync:
#     def run_migrations_online():
#         connectable = engine_from_config(...)
#         with connectable.connect() as connection:
#             context.configure(connection=connection, target_metadata=target_metadata)
#             with context.begin_transaction():
#                 context.run_migrations()
#
# 4. alembic revision --autogenerate -m "add articles table"
#    → creates a migration file with upgrade() and downgrade()
# 5. alembic upgrade head
#    → applies all pending migrations to the DB
# 6. NEVER use Base.metadata.create_all() in production — Alembic tracks
#    applied migrations; create_all() does not.
# ===========================================================================


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("L03_async_and_database:app", host="0.0.0.0", port=8002, reload=True)
