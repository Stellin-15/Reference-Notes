# ============================================================
# L07: Performance and Caching in FastAPI
# ============================================================
# WHAT: Redis caching, async vs sync trade-offs, N+1 query
#       prevention, GZip compression, cursor pagination, and
#       background task offloading for slow operations.
# WHY:  A naive FastAPI app stalls at ~50 RPS because of N+1
#       queries, uncompressed 200 KB JSON payloads, and missing
#       cache layers. These patterns push you to thousands of
#       RPS without changing hardware.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    FastAPI's async support matters only for IO-bound work.
    Async lets the event loop run other coroutines while THIS
    request is blocked waiting for a DB or HTTP response.
    CPU-bound code (image processing, heavy computation) does
    NOT benefit — it blocks the event loop and makes everything
    slower. For CPU work, use sync endpoints + Uvicorn's thread
    pool, or push work to Celery workers.

    N+1 queries: fetching 100 products and then querying
    categories for each = 101 queries. Always eager-load
    related data with selectinload / joinedload in SQLAlchemy,
    or write a JOIN explicitly.

    Cursor pagination is O(1) regardless of page depth. Offset
    pagination forces PostgreSQL to scan and discard all prior
    rows (OFFSET 10000 = scan 10000 rows). For anything beyond
    page 5-10, cursor pagination is mandatory.

    Response caching: serve the same JSON for 5 minutes from
    Redis instead of hitting PostgreSQL on every request. Layer
    with CDN Cache-Control headers to push caching to the edge.

PRODUCTION USE CASE:
    E-commerce products API: 50 000 SKUs, 2 000 RPS peak.
    Without caching: 2 000 DB queries/s → DB overload.
    With Redis cache (TTL=300 s) and a CDN in front: DB load
    drops to ~10 cache-miss queries/s. GZip cuts payload from
    180 KB to 30 KB. Cursor pagination keeps page-50 latency
    identical to page-1.

COMMON MISTAKES:
    1. Using async for CPU-bound work — blocks the event loop,
       all concurrent requests queue behind it. Use sync def or
       run_in_executor / Celery.
    2. Returning offset-paginated results from feeds — page 100
       at 20 items/page = scan 2000 rows every request. Switch
       to cursor (keyset) pagination.
    3. Caching mutable data without invalidation — product price
       changes but cache serves stale price for TTL duration.
       Design cache keys to include the entity version or use
       short TTLs for volatile fields.
    4. Not measuring before optimising — add profiling middleware
       first, find the actual bottleneck, then fix it. Do not
       add Redis if the real problem is a missing DB index.
"""

import asyncio
import hashlib
import json
import logging
import time
from functools import lru_cache
from typing import Any, AsyncGenerator, Optional

import redis.asyncio as aioredis
from fastapi import BackgroundTasks, Depends, FastAPI, Query, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(title="Products API — Performance Demo")

# ---------------------------------------------------------------------------
# GZip middleware: compresses responses ≥ 1 000 bytes automatically.
# Saves 60-80% on large JSON payloads. Transparent to clients that
# send Accept-Encoding: gzip (every modern browser and HTTP client).
# ---------------------------------------------------------------------------
app.add_middleware(
    GZipMiddleware,
    minimum_size=1000,  # bytes — don't compress tiny payloads (overhead > gain)
)


# ===========================================================================
# REDIS CACHE LAYER
# ===========================================================================
redis_client: aioredis.Redis  # set at startup


@app.on_event("startup")
async def startup() -> None:
    global redis_client
    redis_client = aioredis.from_url("redis://localhost:6379", decode_responses=True)


@app.on_event("shutdown")
async def shutdown() -> None:
    await redis_client.aclose()


async def cache_get(key: str) -> Optional[Any]:
    """Fetch a value from Redis; return None on miss or error."""
    try:
        raw = await redis_client.get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:
        # Never let cache failure crash the request — fall through to DB
        logger.warning("Cache GET error: %s", exc)
        return None


async def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    """Write a value to Redis with an expiry. Fire-and-forget safe."""
    try:
        await redis_client.setex(key, ttl, json.dumps(value))
    except Exception as exc:
        logger.warning("Cache SET error: %s", exc)


async def cache_delete(key: str) -> None:
    """Invalidate a cache key (call on mutation endpoints)."""
    try:
        await redis_client.delete(key)
    except Exception as exc:
        logger.warning("Cache DELETE error: %s", exc)


def make_cache_key(prefix: str, **kwargs) -> str:
    """
    Build a deterministic cache key from prefix + sorted kwargs.
    Hashing avoids cache key injection (e.g. query params with colons).
    """
    payload = json.dumps(kwargs, sort_keys=True)
    digest = hashlib.md5(payload.encode()).hexdigest()[:8]  # noqa: S324 (non-crypto)
    return f"{prefix}:{digest}"


# ===========================================================================
# MODELS
# ===========================================================================
class Product(BaseModel):
    id: int
    name: str
    price: float
    category: str


class ProductsPage(BaseModel):
    items: list[Product]
    next_cursor: Optional[int]  # None means no more pages
    total_hint: Optional[int]   # cheap estimate, not exact count


# ===========================================================================
# PROFILING MIDDLEWARE
# Measure every request. Log anything over 200 ms so you know
# which endpoints need optimisation BEFORE you start guessing.
# ===========================================================================
@app.middleware("http")
async def profiling_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    # Add timing to response header so you can see it in browser DevTools
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
    if elapsed_ms > 200:
        logger.warning(
            "SLOW REQUEST path=%s method=%s duration_ms=%.1f",
            request.url.path,
            request.method,
            elapsed_ms,
        )
    return response


# ===========================================================================
# PRODUCT DETAIL — Redis cache + Cache-Control for CDN
# ===========================================================================
@app.get("/products/{product_id}", response_model=Product)
async def get_product(product_id: int, response: Response):
    """
    Fetch a single product.
    Cache hit path: Redis → return (< 1 ms).
    Cache miss path: DB → write to Redis → return.
    Cache-Control header lets a CDN (Cloudfront, Fastly) cache at edge.
    """
    cache_key = f"product:{product_id}"

    # --- Cache hit --- #
    cached = await cache_get(cache_key)
    if cached:
        response.headers["X-Cache"] = "HIT"
        # CDN can cache for 1 h (public), client for 5 min (max-age)
        response.headers["Cache-Control"] = "public, max-age=300, s-maxage=3600"
        return cached

    # --- Cache miss: query DB --- #
    # Replace with real async DB call (SQLAlchemy async / asyncpg)
    product = await _fetch_product_from_db(product_id)

    # Store in Redis; TTL 300 s (product price changes infrequently)
    await cache_set(cache_key, product.model_dump(), ttl=300)

    response.headers["X-Cache"] = "MISS"
    response.headers["Cache-Control"] = "public, max-age=300, s-maxage=3600"
    return product


@app.put("/products/{product_id}")
async def update_product(product_id: int, data: Product):
    """On write, invalidate the cache so reads see fresh data immediately."""
    await _update_product_in_db(product_id, data)
    await cache_delete(f"product:{product_id}")
    # Also bust the list cache (any page could contain this product)
    # In practice: use cache tags or a version key to bust all list pages
    return {"ok": True}


# ===========================================================================
# CURSOR PAGINATION — O(1) at any page depth
#
# Offset:  SELECT * FROM products LIMIT 20 OFFSET 10000
#          → PostgreSQL scans 10 020 rows, returns 20. Scales linearly.
#
# Cursor:  SELECT * FROM products WHERE id > :cursor ORDER BY id LIMIT 20
#          → PostgreSQL uses the primary-key B-tree, seeks directly.
#          → O(1) regardless of how deep in the feed you are.
# ===========================================================================
@app.get("/products", response_model=ProductsPage)
async def list_products(
    cursor: Optional[int] = Query(default=None, description="Last product ID seen"),
    limit: int = Query(default=20, le=100),
    category: Optional[str] = Query(default=None),
):
    """
    Cursor-paginated product list.
    Pass cursor=<last_id_from_previous_page> to get the next page.
    Omit cursor to start from the beginning.
    """
    cache_key = make_cache_key("products_list", cursor=cursor, limit=limit, cat=category)
    cached = await cache_get(cache_key)
    if cached:
        return cached

    # Build parameterised query — never string-interpolate (SQL injection)
    query = """
        SELECT id, name, price, category
        FROM products
        WHERE (:cursor IS NULL OR id > :cursor)
          AND (:category IS NULL OR category = :category)
        ORDER BY id
        LIMIT :limit
    """
    rows = await _execute_query(query, cursor=cursor, limit=limit, category=category)

    items = [Product(**r) for r in rows]
    # Next cursor is the last item's id; None if fewer results than limit
    next_cursor = items[-1].id if len(items) == limit else None

    page = ProductsPage(items=items, next_cursor=next_cursor, total_hint=None)
    # Short TTL for list pages — new products appear frequently
    await cache_set(cache_key, page.model_dump(), ttl=60)
    return page


# ===========================================================================
# ASYNC vs SYNC — choosing correctly
# ===========================================================================
@app.get("/reports/{report_id}/summary")
async def get_report_summary(report_id: int):
    """
    IO-bound: awaits multiple DB/Redis calls concurrently with gather().
    asyncio.gather runs all coroutines in parallel on the same event loop.
    Faster than sequential awaits when calls are independent.
    """
    # Fetch metadata and stats in parallel — both are pure IO
    metadata, stats = await asyncio.gather(
        _fetch_report_metadata(report_id),
        _fetch_report_stats(report_id),
    )
    return {"metadata": metadata, "stats": stats}


@app.post("/images/resize")
def resize_image_sync(image_url: str):
    """
    CPU-bound: declared as sync def (no async).
    FastAPI runs sync endpoints in a thread pool automatically,
    so they don't block the event loop. Do NOT make this async —
    PIL/numpy work is GIL-bound and yields nothing to the loop.
    """
    # result = _heavy_image_resize(image_url)  # runs in thread pool
    return {"status": "resized"}


# ===========================================================================
# BACKGROUND TASKS — offload slow work, return 202 immediately
#
# Pattern:
#   1. Client: POST /reports/generate  → 202 + task_id
#   2. Worker: Celery task runs async, writes result to Redis
#   3. Client: GET /tasks/{task_id}    → poll until status=done
#
# Use FastAPI BackgroundTasks for lightweight work (< 1 s, no retry).
# Use Celery for anything that needs retries, scheduling, or long duration.
# ===========================================================================
class ReportRequest(BaseModel):
    product_ids: list[int]
    email: str


@app.post("/reports/generate", status_code=202)
async def generate_report(req: ReportRequest, background_tasks: BackgroundTasks):
    """
    Accept report request and return immediately (202 Accepted).
    Heavy work runs after the response is sent.
    """
    import uuid
    task_id = str(uuid.uuid4())
    # FastAPI BackgroundTasks: runs AFTER response is sent to client
    background_tasks.add_task(_build_report_task, task_id, req)
    # Store initial status so /tasks/{id} returns something immediately
    await cache_set(f"task:{task_id}", {"status": "pending"}, ttl=3600)
    return {"task_id": task_id, "status": "pending"}


@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Poll endpoint: client calls this every 2 s until status=done."""
    result = await cache_get(f"task:{task_id}")
    if result is None:
        return {"status": "not_found"}
    return result


async def _build_report_task(task_id: str, req: ReportRequest) -> None:
    """
    Runs in the background after the HTTP response is already sent.
    In production: replace with a Celery task for retry support.
    """
    try:
        await cache_set(f"task:{task_id}", {"status": "running"}, ttl=3600)
        # Simulate slow report generation
        await asyncio.sleep(5)
        report_url = f"https://cdn.example.com/reports/{task_id}.pdf"
        await cache_set(
            f"task:{task_id}",
            {"status": "done", "url": report_url},
            ttl=86400,  # keep result 24 h
        )
    except Exception as exc:
        await cache_set(
            f"task:{task_id}",
            {"status": "error", "detail": str(exc)},
            ttl=3600,
        )


# ===========================================================================
# LAZY STARTUP — avoid loading heavy resources on every request
# Load once on first use, cache in module-level dict.
# ===========================================================================
_model_cache: dict[str, Any] = {}


def get_ml_model(model_name: str) -> Any:
    """
    Load an ML model once and cache it in memory.
    Pattern: check dict → load if missing → return.
    Never reload per-request (300-2000 ms penalty each time).
    """
    if model_name not in _model_cache:
        logger.info("Loading model %s (first request)", model_name)
        # _model_cache[model_name] = load_model(model_name)  # your loader
        _model_cache[model_name] = object()  # placeholder
    return _model_cache[model_name]


# ===========================================================================
# STUBS — replace with real SQLAlchemy / asyncpg implementations
# ===========================================================================
async def _fetch_product_from_db(product_id: int) -> Product:
    await asyncio.sleep(0.01)  # simulate DB round-trip
    return Product(id=product_id, name="Widget", price=9.99, category="tools")


async def _update_product_in_db(product_id: int, data: Product) -> None:
    await asyncio.sleep(0.01)


async def _execute_query(query: str, **params) -> list[dict]:
    await asyncio.sleep(0.01)
    return [
        {"id": i, "name": f"Product {i}", "price": float(i), "category": "tools"}
        for i in range(1, params.get("limit", 20) + 1)
    ]


async def _fetch_report_metadata(report_id: int) -> dict:
    await asyncio.sleep(0.01)
    return {"id": report_id, "name": "Q2 Sales"}


async def _fetch_report_stats(report_id: int) -> dict:
    await asyncio.sleep(0.015)
    return {"rows": 1500, "revenue": 42000.0}
