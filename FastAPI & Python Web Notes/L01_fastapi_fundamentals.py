# ============================================================
# L01: FastAPI Fundamentals
# ============================================================
# WHAT: FastAPI is an ASGI (Asynchronous Server Gateway Interface) web
#       framework for Python. It is async-first, built on Starlette
#       (the ASGI toolkit) and Pydantic (data validation). It auto-
#       generates OpenAPI (Swagger) and ReDoc documentation. Benchmarks
#       consistently place it at the same throughput level as Node.js and
#       Go for IO-bound workloads — the fastest Python web framework.
#
# WHY:  When you need a production-grade Python API that is fast, safe,
#       and self-documenting. Type annotations are not decoration here —
#       they drive validation, serialization, and the generated schema.
#       You write less code, get fewer runtime surprises, and clients get
#       accurate docs automatically.
#
# LEVEL: Foundation
# ============================================================
"""
CONCEPT OVERVIEW:
    FastAPI translates Python type hints into:
      1. Request validation  — wrong type = automatic 422 Unprocessable Entity
      2. Response filtering  — response_model strips undeclared fields
      3. OpenAPI schema      — /docs and /redoc are always in sync with code
    Routing is declarative: decorators (@app.get, @app.post, ...) map HTTP
    verbs + paths to functions. Routers let you split the app into modules.
    Lifespan context manages startup/shutdown. Middleware wraps every request.

PRODUCTION USE CASE:
    Microservice that exposes a User CRUD API consumed by a React frontend
    and a mobile app. The frontend team reads /docs; the OpenAPI JSON is
    imported into Postman. Passwords are never in any response because
    response_model excludes them. Background tasks send welcome emails
    without delaying the 201 response.

COMMON MISTAKES:
    1. Putting heavy work (ML inference, file conversion) in a background
       task — it blocks the event loop if the function is sync. Use Celery.
    2. Using response_model on PATCH and including every field — use
       response_model_exclude_unset=True or the client always sees nulls.
    3. Returning 200 for resource creation instead of 201. Use
       status.HTTP_201_CREATED or callers cannot reliably detect creates.
    4. Forgetting CORS in dev — the browser blocks requests from localhost
       to a different port. Add CORSMiddleware early.
    5. @app.on_event("startup") is deprecated since FastAPI 0.93 — use the
       lifespan context manager instead.
"""

from __future__ import annotations

import uuid
import time
import logging
from contextlib import asynccontextmanager
from typing import Optional, List, Any

# FastAPI core
from fastapi import (
    FastAPI, APIRouter, Depends, HTTPException, BackgroundTasks,
    UploadFile, File, Request, Response, status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

# Pydantic v2 — ships with FastAPI
from pydantic import BaseModel, EmailStr, Field, field_validator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simulated in-memory "database" — replace with SQLAlchemy in production
# ---------------------------------------------------------------------------
FAKE_DB: dict[int, dict] = {}
_id_counter = 0


def _next_id() -> int:
    global _id_counter
    _id_counter += 1
    return _id_counter


# ===========================================================================
# PYDANTIC MODELS
# Pydantic converts, validates, and serialises. Field() adds constraints.
# ===========================================================================

class UserCreate(BaseModel):
    """Schema for incoming POST /users body. Pydantic validates all fields."""
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr                          # validated format, not just str
    age: int = Field(ge=0, le=150)           # ge=greater-or-equal, le=less-or-equal
    password: str = Field(..., min_length=8) # never returned — filtered by response_model

    @field_validator("name")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        # Strip leading/trailing spaces before storing — common oversight
        return v.strip()


class UserPatch(BaseModel):
    """All fields optional so client sends only what changed (PATCH semantics)."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    age: Optional[int] = Field(default=None, ge=0, le=150)
    active: Optional[bool] = None


class UserResponse(BaseModel):
    """Public user shape. `password` is NOT here — it will never leak."""
    id: int
    name: str
    email: EmailStr
    age: int
    active: bool = True

    # Pydantic v2: model_config replaces class Config
    model_config = {"from_attributes": True}  # lets us build from ORM objects


# ===========================================================================
# LIFESPAN — replaces deprecated @app.on_event("startup/shutdown")
# Everything before `yield` runs at startup; after yield runs at shutdown.
# ===========================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    logger.info("Starting up: initialising DB pool, loading config...")
    # In production: create_async_engine(...), connect Redis, warm ML model
    app.state.db_pool = "fake_pool"          # placeholder; real = asyncpg pool
    yield
    # --- SHUTDOWN ---
    logger.info("Shutting down: closing DB pool, flushing caches...")
    # In production: await pool.close(), await redis.close()
    app.state.db_pool = None


# ===========================================================================
# APP INSTANCE
# lifespan= is the modern way to hook startup/shutdown logic.
# ===========================================================================

app = FastAPI(
    title="User Service",
    description="Demonstrates FastAPI fundamentals — CRUD, routers, middleware.",
    version="1.0.0",
    lifespan=lifespan,                       # pass the async context manager
)

# ===========================================================================
# CORS MIDDLEWARE
# Must be added BEFORE any route definitions so it wraps every request.
# In production: replace "*" with your actual frontend origin.
# ===========================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://app.example.com", "http://localhost:3000"],
    allow_credentials=True,                  # needed for cookies / auth headers
    allow_methods=["*"],                     # GET, POST, PUT, PATCH, DELETE, OPTIONS
    allow_headers=["*"],                     # Authorization, Content-Type, etc.
)

# ===========================================================================
# TIMING MIDDLEWARE
# Middleware wraps every request. Order: outermost middleware runs first on
# the way in and last on the way out. Add X-Process-Time for observability.
# ===========================================================================

@app.middleware("http")
async def add_process_time_header(request: Request, call_next) -> Response:
    start_time = time.perf_counter()          # high-resolution timer
    response = await call_next(request)       # run the actual route handler
    duration_ms = (time.perf_counter() - start_time) * 1000
    response.headers["X-Process-Time"] = f"{duration_ms:.2f}ms"
    return response


# ===========================================================================
# CUSTOM EXCEPTION HANDLER
# Override FastAPI's default 422 to always return a consistent error shape.
# ===========================================================================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # FastAPI's default is fine, but this lets you rename fields / add context
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "validation_error",
            "detail": exc.errors(),          # list of {loc, msg, type} dicts
        },
    )


# ===========================================================================
# BACKGROUND TASK HELPER
# Runs AFTER the response is sent to the client — good for non-critical IO.
# Do NOT use for: CPU-heavy work, tasks that must succeed, tasks > ~5 seconds.
# ===========================================================================

def send_welcome_email(email: str, name: str) -> None:
    """Simulated email send. In production: call SendGrid / SES SDK."""
    logger.info("Sending welcome email to %s <%s>", name, email)
    # time.sleep(2) would happen here — that is why this runs in background


# ===========================================================================
# ROUTER — organise by domain, not by HTTP verb
# prefix="/users" means every route here is automatically /users/...
# tags=["users"] groups them under one section in /docs
# ===========================================================================

router = APIRouter(prefix="/users", tags=["users"])


# ---------------------------------------------------------------------------
# POST /users — create a user
# status_code=201 — use named constant, not a magic number
# response_model=UserResponse — Pydantic strips `password` automatically
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,     # 201 Created, not 200 OK
    summary="Create a new user",
)
async def create_user(
    user_in: UserCreate,                     # body — Pydantic validates JSON
    background_tasks: BackgroundTasks,       # injected by FastAPI
) -> UserResponse:
    # Check for duplicate email — production: query DB with UNIQUE constraint
    for existing in FAKE_DB.values():
        if existing["email"] == user_in.email:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email {user_in.email} is already registered.",
            )

    user_id = _next_id()
    record = {
        "id": user_id,
        "name": user_in.name,
        "email": user_in.email,
        "age": user_in.age,
        "password_hash": f"bcrypt_hash_of_{user_in.password}",  # never returned
        "active": True,
    }
    FAKE_DB[user_id] = record

    # Schedule email AFTER response — client gets 201 immediately
    background_tasks.add_task(send_welcome_email, user_in.email, user_in.name)

    # response_model=UserResponse filters out password_hash here
    return UserResponse(**record)


# ---------------------------------------------------------------------------
# GET /users — list users with pagination via query parameters
# Query params are function arguments with defaults — no decorator needed
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=List[UserResponse],
    summary="List users with pagination",
)
async def list_users(
    skip: int = 0,                           # offset — default 0
    limit: int = 100,                        # page size — default 100
    active: Optional[bool] = None,           # None = no filter; True/False = filter
) -> List[UserResponse]:
    users = list(FAKE_DB.values())
    if active is not None:
        # Optional filter — only apply when caller explicitly passes ?active=true
        users = [u for u in users if u["active"] == active]
    return [UserResponse(**u) for u in users[skip : skip + limit]]


# ---------------------------------------------------------------------------
# GET /users/{user_id} — fetch one user
# Path parameter: {user_id} in the URL is captured and type-checked as int
# FastAPI returns 422 automatically if user_id is not a valid integer
# ---------------------------------------------------------------------------

@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get a single user",
)
async def get_user(user_id: int) -> UserResponse:
    # user_id is already an int — FastAPI coerced and validated it
    user = FAKE_DB.get(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found.",
        )
    return UserResponse(**user)


# ---------------------------------------------------------------------------
# PATCH /users/{user_id} — partial update
# response_model_exclude_unset=True: only return fields the handler set,
# not the entire model with defaults. Prevents confusing null-filled responses.
# ---------------------------------------------------------------------------

@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    response_model_exclude_unset=True,       # key for PATCH — omit unset fields
    summary="Partially update a user",
)
async def patch_user(user_id: int, patch: UserPatch) -> UserResponse:
    user = FAKE_DB.get(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    # model_dump(exclude_unset=True) only includes fields the client actually sent
    updates = patch.model_dump(exclude_unset=True)
    user.update(updates)                     # apply only what changed
    FAKE_DB[user_id] = user
    return UserResponse(**user)


# ---------------------------------------------------------------------------
# DELETE /users/{user_id} — delete a user
# 204 No Content: success, no body. FastAPI handles the empty response.
# ---------------------------------------------------------------------------

@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user",
)
async def delete_user(user_id: int) -> None:
    if user_id not in FAKE_DB:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    del FAKE_DB[user_id]
    # 204 = no body — return None, FastAPI sends empty response


# ===========================================================================
# FILE UPLOAD EXAMPLE
# UploadFile is a SpooledTemporaryFile — streams efficiently.
# Always check content_type, never trust the filename extension alone.
# ===========================================================================

upload_router = APIRouter(prefix="/files", tags=["files"])

@upload_router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_file(file: UploadFile = File(...)) -> dict[str, Any]:
    # Validate MIME type — do not trust file.filename extension
    allowed_types = {"image/jpeg", "image/png", "application/pdf"}
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File type {file.content_type} not allowed.",
        )

    # Read in chunks to avoid loading large files into memory all at once
    contents = b""
    chunk_size = 1024 * 64                   # 64 KB chunks
    while chunk := await file.read(chunk_size):
        contents += chunk
        if len(contents) > 10 * 1024 * 1024:  # 10 MB hard limit
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File exceeds 10 MB limit.",
            )

    return {
        "filename": file.filename,
        "content_type": file.content_type,
        "size_bytes": len(contents),
        "file_id": str(uuid.uuid4()),        # real: store to S3, return key
    }


# ===========================================================================
# REGISTER ROUTERS ON THE APP
# All /users/* routes come from `router`.
# All /files/* routes come from `upload_router`.
# ===========================================================================

app.include_router(router)
app.include_router(upload_router)


# ===========================================================================
# ROOT HEALTH CHECK — not in any router, lives at app level
# ===========================================================================

@app.get("/", tags=["health"])
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "user-service", "version": "1.0.0"}


# ===========================================================================
# ENTRY POINT
# In production: gunicorn -w 1 -k uvicorn.workers.UvicornWorker main:app
# -w 1 because async handles concurrency; multiple processes for CPU use
# ===========================================================================

if __name__ == "__main__":
    import uvicorn
    # reload=True restarts on file change — development only, never prod
    uvicorn.run("L01_fastapi_fundamentals:app", host="0.0.0.0", port=8000, reload=True)
