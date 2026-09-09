# FastAPI & Python Web — Principal Engineer Deep Dive

Companion to the existing lessons. Narrative depth, then a comprehensive
common-to-uncommon tool reference.


## ASGI vs WSGI — Why FastAPI Exists

**Beyond the lesson**: Flask/Django (classic) run on WSGI, a SYNCHRONOUS
interface — one worker thread/process handles one request at a time, fully
blocking on I/O (a slow database call blocks that entire worker). FastAPI
runs on ASGI, which supports `async def` handlers — a single worker can
handle THOUSANDS of concurrent I/O-bound requests by yielding control
during an `await` (a DB call, an HTTP call to another service) instead of
blocking a whole OS thread per request. This is the actual mechanical
reason FastAPI benchmarks so much higher for I/O-heavy workloads — it's
not "faster Python," it's a fundamentally different concurrency model for
the exact class of work most web APIs do (waiting on network I/O).

**Worked example**: Mixing sync and async code incorrectly is THE most
common FastAPI production mistake — calling a blocking synchronous
function (a non-async DB driver, `requests.get()` instead of `httpx`)
inside an `async def` endpoint blocks the ENTIRE event loop, not just that
one request — every other concurrent request on that worker stalls too.
FastAPI's `run_in_threadpool` (or just declaring the endpoint `def` instead
of `async def`, which FastAPI automatically runs in a thread pool) is the
correct escape hatch for unavoidably-blocking calls.

**Interview Q&A**:
- *Q: You have a CPU-bound task (image processing) in a FastAPI endpoint. Should it be async?* A: No — async helps I/O-bound concurrency by yielding during waits; a CPU-bound task blocks the event loop regardless of `async`/`await` because there's no I/O wait to yield during. Offload it to a background worker (Celery/RQ) or a process pool, don't just mark the endpoint async and hope.


## Pydantic & Dependency Injection

**Beyond the lesson**: Pydantic isn't just "type hints that validate" — it's
doing real WORK at request-boundary time: parsing raw JSON, coercing types,
running custom validators, and generating the OpenAPI schema automatically
from the SAME model definitions used for validation — one source of truth
instead of hand-maintained docs drifting from actual validation logic.

**Worked example**: FastAPI's dependency injection (`Depends()`) solves the
"how do I share a DB session/auth check across many endpoints without
copy-pasting" problem cleanly — a dependency function runs once per
request, its result is injected into any handler that declares it, and
FastAPI automatically handles cleanup (via generator-based dependencies
with `yield`) even when the request fails partway through — closing a
connection reliably without manual try/finally scattered across every endpoint.

**Interview Q&A**:
- *Q: Pydantic v1 vs v2 — what actually changed and why does it matter?* A: v2's validation core was rewritten in Rust (`pydantic-core`), giving a 5-50x validation speedup — for a high-throughput API where request validation happens on every single call, this is a genuinely significant real-world performance difference, not a minor version bump.


## COMPREHENSIVE TOOL & PRACTICE REFERENCE — COMMON TO UNCOMMON

### Python web frameworks, precisely differentiated
- **Django** — full-featured "batteries included" (ORM, admin panel, auth,
  forms) — the choice when you want a complete, opinionated framework and
  don't want to assemble one from parts; the admin panel alone is a huge
  time-saver for internal tools.
- **Flask** — minimal, unopinionated, add exactly what you need — still
  common for smaller services/APIs where Django's scope is overkill.
- **FastAPI** — async-first, type-hint-driven, automatic OpenAPI docs — the
  modern default for new API-first Python services.
- **Django REST Framework (DRF)** — the standard way to build APIs ON TOP
  of Django when you need Django's ORM/admin but a proper REST API layer.
- **Litestar** — a newer, also-async, arguably even more modern
  alternative to FastAPI gaining traction — worth knowing exists even if less common than FastAPI currently.

### ASGI servers & deployment
- **Uvicorn** — the standard ASGI server, usually run under **Gunicorn**
  with the `uvicorn.workers.UvicornWorker` class for production
  (Gunicorn handles process management/restarts, Uvicorn handles the async serving).
- **Hypercorn** — an alternative ASGI server supporting HTTP/2 and
  WebSockets more completely in some configurations.

### ORMs & database access
- **SQLAlchemy** (+ **SQLAlchemy 2.0's** async support) — the dominant
  Python ORM, works with both Flask and FastAPI; the 2.0 rewrite added
  first-class async session support specifically for ASGI frameworks.
- **Django ORM** — Django's own built-in ORM, tightly coupled to the framework, not usable standalone.
- **Tortoise ORM** — an async-native ORM built specifically for
  async frameworks, an alternative to bolting async support onto SQLAlchemy.
- **asyncpg / aiomysql** — the raw async database DRIVERS underneath
  async ORMs — worth knowing the ORM isn't what makes queries async, the driver is.

### Background jobs & task queues
- **Celery** — the long-standing standard for Python background task
  queues, backed by Redis/RabbitMQ as the broker — used for anything too
  slow to run inline in a request (sending emails, processing uploads, ML inference).
- **RQ (Redis Queue)** — simpler than Celery, Redis-only, chosen when
  Celery's flexibility isn't needed and simplicity is preferred.
- **Arq** — an async-native task queue built specifically to pair with
  FastAPI's async model rather than Celery's traditionally sync worker model.

### Testing
- **pytest** + **httpx** (or FastAPI's own `TestClient`) — the standard
  combination for testing FastAPI endpoints, including async test support via `pytest-asyncio`.
- **factory_boy** — test data factories (see Testing & QA Engineering
  Notes) commonly paired with SQLAlchemy models for realistic test fixtures.

### API gateway / production hardening
- **Starlette** — the ASGI toolkit FastAPI is actually BUILT ON — worth
  knowing FastAPI is a layer of conveniences (validation, docs, DI) on top
  of Starlette's lower-level ASGI primitives, not a from-scratch framework.
- **slowapi** — rate limiting for FastAPI, since it isn't built in natively.


## NICHE BUT REAL

- **WebSockets in FastAPI** — first-class support (`@app.websocket`) for
  bidirectional real-time connections, commonly paired with a pub/sub
  backend (Redis pub/sub) to broadcast messages across multiple FastAPI
  worker processes, since WebSocket connections are pinned to whichever
  worker process accepted them.
- **GraphQL on FastAPI** (Strawberry, Ariadne) — running a GraphQL layer
  alongside or instead of REST endpoints within the same FastAPI app,
  increasingly common for APIs needing both styles for different consumers.
- **Server-Sent Events (SSE)** — a simpler alternative to WebSockets for
  one-way server-to-client streaming (used heavily for streaming LLM token
  responses — see Agentic AI & RAG Notes) — FastAPI supports this via
  `StreamingResponse` without needing full WebSocket infrastructure.
- **GIL-aware scaling** — even with async I/O concurrency, Python's Global
  Interpreter Lock still means true CPU-bound PARALLELISM needs multiple
  PROCESSES (Gunicorn's worker count), not just more async concurrency
  within one process — a real, frequently-misunderstood distinction in
  production capacity planning for Python services.
