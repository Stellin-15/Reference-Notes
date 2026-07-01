# ============================================================
# L01: REST Principles
# ============================================================
# WHAT: REST (Representational State Transfer) is an architectural
#       style for designing networked APIs using HTTP conventions.
#       It is NOT a protocol — it is a set of constraints and
#       guidelines that, when followed, produce predictable,
#       scalable, and interoperable web services.
# WHY:  REST is the dominant API style for public and internal
#       web services. Understanding its principles prevents design
#       mistakes that become expensive to fix after clients exist.
# LEVEL: Foundation
# ============================================================
"""
CONCEPT OVERVIEW:
    REST was defined by Roy Fielding in his 2000 dissertation.
    Six constraints: client-server separation, statelessness,
    cacheability, uniform interface, layered system, and optional
    code-on-demand. In practice, "RESTful" APIs focus on:
    - Resources identified by URLs (nouns, not verbs)
    - HTTP verbs expressing the action (GET/POST/PUT/PATCH/DELETE)
    - Stateless requests (each request carries all needed context)
    - Standard status codes communicating outcome
    - Consistent error response shapes

PRODUCTION USE CASE:
    Every public API (Stripe, GitHub, Twilio, Shopify) follows REST
    conventions. Internal microservices use REST for human-readable
    debugging, browser compatibility, and universal client support.
    A well-designed REST API can be consumed without reading docs.

COMMON MISTAKES:
    - Using verbs in URLs: /getUser, /createOrder, /deleteAccount
    - Returning 200 OK with {"success": false} in the body
    - Using GET for state-changing operations (breaks caching/safety)
    - Ignoring idempotency — retrying POST creates duplicates
    - Returning HTML error pages from an API endpoint
    - Inconsistent error shapes across endpoints
    - Nesting resources too deeply: /users/1/orders/2/items/3/reviews
"""

# ─────────────────────────────────────────────────────────────
# SECTION 1: Resources — Nouns, Not Verbs
# ─────────────────────────────────────────────────────────────

# BAD: verb-based URLs encode the action in the path
BAD_URLS = [
    "GET  /getUser",
    "POST /createUser",
    "POST /deleteUser",
    "GET  /fetchAllOrders",
    "POST /updateUserEmail",
]

# GOOD: noun-based URLs identify the resource; HTTP verb = action
GOOD_URLS = [
    "GET    /users          # list all users",
    "POST   /users          # create a new user",
    "GET    /users/{id}     # fetch one user",
    "PUT    /users/{id}     # replace a user",
    "PATCH  /users/{id}     # partially update a user",
    "DELETE /users/{id}     # delete a user",
]

# Use PLURAL nouns for collections
# /users  not  /user
# /orders not  /order
# /products not /product

# Nested resources express relationships — keep depth ≤ 2
NESTED_URLS = [
    "GET  /users/{user_id}/orders          # orders belonging to user",
    "POST /users/{user_id}/orders          # create order for user",
    "GET  /users/{user_id}/orders/{id}     # specific order of user",
]

# Use IDs (opaque, stable) not names (mutable, non-unique) in paths
# GOOD: /users/8f3d2a   BAD: /users/john-doe  (name can change)

# ─────────────────────────────────────────────────────────────
# SECTION 2: HTTP Verbs and Their Semantics
# ─────────────────────────────────────────────────────────────

HTTP_VERB_SEMANTICS = {
    "GET": {
        "purpose": "Read / retrieve a resource or collection",
        "idempotent": True,   # Same result no matter how many times called
        "safe": True,          # Does NOT modify state — safe to call freely
        "body": "None",        # GET requests must not have a body
        "example": "GET /users/123  → returns user 123",
    },
    "POST": {
        "purpose": "Create a new resource OR trigger an action",
        "idempotent": False,  # Two identical POSTs create two resources
        "safe": False,
        "body": "JSON payload with new resource data",
        "example": "POST /users  → creates user, returns 201 + Location",
    },
    "PUT": {
        "purpose": "Replace a resource entirely (full update)",
        "idempotent": True,   # Putting the same data twice = same result
        "safe": False,
        "body": "Complete representation of the resource",
        "example": "PUT /users/123  → replace all fields of user 123",
        "note": "If any field is omitted, it is nulled/deleted",
    },
    "PATCH": {
        "purpose": "Partial update — only send fields that change",
        "idempotent": "Depends on implementation",
        "safe": False,
        "body": "Only the fields being updated",
        "example": "PATCH /users/123  → update only email, leave rest",
    },
    "DELETE": {
        "purpose": "Remove a resource",
        "idempotent": True,   # Deleting an already-deleted resource = same state
        "safe": False,
        "body": "None",
        "example": "DELETE /users/123  → delete user 123",
    },
}

# ─────────────────────────────────────────────────────────────
# SECTION 3: HTTP Status Codes — Use Them Correctly
# ─────────────────────────────────────────────────────────────

STATUS_CODES = {
    # 2xx — Success
    200: "OK — general success, used for GET and PATCH responses",
    201: "Created — resource was successfully created (POST). Include Location header",
    204: "No Content — success with no body (DELETE, PUT when not returning resource)",

    # 3xx — Redirection
    301: "Moved Permanently — URL has changed, update bookmarks",
    304: "Not Modified — used with ETags for caching (conditional GET)",

    # 4xx — Client Errors (the CLIENT did something wrong)
    400: "Bad Request — malformed JSON, missing required field, wrong type",
    401: "Unauthorized — not authenticated (no token, expired token, invalid token)",
    403: "Forbidden — authenticated BUT not authorized for this resource/action",
    404: "Not Found — resource does not exist (or you're hiding its existence)",
    405: "Method Not Allowed — trying DELETE on a read-only resource",
    409: "Conflict — duplicate resource (email already exists), state conflict",
    410: "Gone — resource permanently deleted (use 404 if unsure)",
    422: "Unprocessable Entity — valid JSON but fails business validation",
    429: "Too Many Requests — rate limit exceeded. Include Retry-After header",

    # 5xx — Server Errors (the SERVER failed, not the client)
    500: "Internal Server Error — unexpected exception, bug in code",
    502: "Bad Gateway — upstream service failed",
    503: "Service Unavailable — temporarily down, maintenance mode",
    504: "Gateway Timeout — upstream did not respond in time",
}

# Key distinction: 401 vs 403
# 401: "I don't know who you are — please authenticate"
# 403: "I know exactly who you are — you're not allowed to do this"

# Key distinction: 400 vs 422
# 400: "I can't even parse/understand your request"
# 422: "I understood it, but the data doesn't pass validation rules"

# ─────────────────────────────────────────────────────────────
# SECTION 4: Error Response Format — Always Return JSON
# ─────────────────────────────────────────────────────────────

# APIs must NEVER return HTML error pages (default web framework behavior)
# Every error must be a structured JSON object that clients can parse

# Standard error envelope
ERROR_RESPONSE_STRUCTURE = {
    "error": {
        "code": "USER_NOT_FOUND",           # Machine-readable, stable identifier
        "message": "User 123 was not found", # Human-readable explanation
        "details": [                          # Optional: field-level validation errors
            {
                "field": "email",
                "issue": "must be a valid email address",
                "value": "not-an-email",
            }
        ],
        "request_id": "req_abc123xyz",       # Trace ID — correlate with server logs
        "documentation_url": "https://api.example.com/docs/errors#USER_NOT_FOUND",
    }
}

# FastAPI example — return structured errors, never let the framework
# auto-generate HTML 500 pages or validation error dumps
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Any
import uuid

app = FastAPI(title="User API", version="1.0.0")


# Override FastAPI's default validation error handler
# Without this, validation errors return Pydantic's raw format
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Reformat Pydantic validation errors into our standard shape
    details = []
    for error in exc.errors():
        details.append({
            "field": ".".join(str(loc) for loc in error["loc"][1:]),  # skip 'body'
            "issue": error["msg"],
            "value": error.get("input"),
        })
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": details,
                "request_id": request.headers.get("X-Request-ID", str(uuid.uuid4())),
            }
        },
    )


# Custom HTTP exception handler — consistent format for all 4xx/5xx
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.detail.get("code", "HTTP_ERROR") if isinstance(exc.detail, dict) else "HTTP_ERROR",
                "message": exc.detail.get("message", str(exc.detail)) if isinstance(exc.detail, dict) else str(exc.detail),
                "request_id": request.headers.get("X-Request-ID", str(uuid.uuid4())),
            }
        },
    )


# ─────────────────────────────────────────────────────────────
# SECTION 5: Idempotency
# ─────────────────────────────────────────────────────────────

# Idempotent = calling N times has same effect as calling once
# CRITICAL for retry logic in distributed systems (networks fail)

# GET /users/123 → always returns same user (or 404), no side effects
# PUT /users/123 with same body → user is in same state after retry
# DELETE /users/123 → user gone after first call; second call = 404 but state unchanged
# POST /users → creates a NEW user EACH time — NOT idempotent

# Idempotency-Key header: make POST idempotent for critical operations (payments)
# Client generates unique key (UUID) per logical operation
# Server stores key in Redis: "idempotency:{key}" → response
# If key seen before: return cached response without reprocessing

IDEMPOTENCY_EXAMPLE = """
POST /payments
Headers:
    Idempotency-Key: a4b8c3d2-1234-5678-9abc-def012345678
    Content-Type: application/json

Body: {"amount": 5000, "currency": "usd", "recipient": "user_456"}

Server behavior:
  1. Check Redis: "idempotency:a4b8..." → not found → process payment
  2. Store response in Redis with TTL 24h
  3. Return 201 Created

If client retries (network failure):
  1. Check Redis: "idempotency:a4b8..." → FOUND → return cached 201
  2. Payment NOT charged twice
"""

# ─────────────────────────────────────────────────────────────
# SECTION 6: Filtering, Sorting, and Pagination
# ─────────────────────────────────────────────────────────────

# All via query parameters — never in the request body for GET
# GET /users?status=active&role=admin&sort=created_at&order=desc&limit=20&cursor=abc

class UserListParams(BaseModel):
    # Filtering — narrow the result set
    status: Optional[str] = None         # GET /users?status=active
    role: Optional[str] = None           # GET /users?role=admin
    search: Optional[str] = None         # GET /users?search=john (name/email search)

    # Sorting — default to newest first
    sort: str = Field(default="created_at", description="Field to sort by")
    order: str = Field(default="desc", pattern="^(asc|desc)$")

    # Pagination — cursor-based preferred over offset for large datasets
    # Cursor pagination: stable even when data is inserted/deleted during iteration
    # Offset pagination: page 2 shifts if items added to page 1
    limit: int = Field(default=20, ge=1, le=100)  # Cap at 100 to protect server
    cursor: Optional[str] = None         # Opaque cursor (encoded last item's sort value)


# Paginated response envelope — always include metadata
PAGINATED_RESPONSE = {
    "data": [
        {"id": "user_001", "name": "Alice", "email": "alice@example.com"},
        {"id": "user_002", "name": "Bob", "email": "bob@example.com"},
    ],
    "meta": {
        "total": 847,        # Total matching records (expensive — skip for large datasets)
        "count": 20,         # Items in this response
        "limit": 20,
        "cursor": "eyJpZCI6InVzZXJfMDIwIn0=",  # Base64 encoded cursor for next page
    },
    "links": {
        "self": "/users?limit=20&cursor=eyJpZCI6InVzZXJfMDAxIn0=",
        "next": "/users?limit=20&cursor=eyJpZCI6InVzZXJfMDIwIn0=",
        "prev": None,        # None if on first page
    },
}

# ─────────────────────────────────────────────────────────────
# SECTION 7: Content Negotiation
# ─────────────────────────────────────────────────────────────

# Accept header — client tells server what format it can handle
# Server responds in that format (or 406 Not Acceptable)

CONTENT_NEGOTIATION = {
    "request_headers": {
        "Accept": "application/json",            # Client wants JSON
        "Content-Type": "application/json",      # Client is SENDING JSON
        "Accept-Language": "en-US",             # Locale for error messages
        "Accept-Encoding": "gzip, deflate, br", # Compression support
    },
    "response_headers": {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Encoding": "gzip",              # If compressed
        "Vary": "Accept, Accept-Encoding",       # Cache key includes these headers
    },
}

# ─────────────────────────────────────────────────────────────
# SECTION 8: Real-World User + Order API Design
# ─────────────────────────────────────────────────────────────

# Full URL map for a user + order system
API_URL_MAP = """
USERS
─────────────────────────────────────────────────
GET    /users                    List users (paginated, filterable)
POST   /users                    Create user → 201 + Location: /users/{id}
GET    /users/{id}               Get user by ID → 200 or 404
PUT    /users/{id}               Replace user → 200 or 404
PATCH  /users/{id}               Partial update → 200 or 404
DELETE /users/{id}               Delete user → 204 or 404

ORDERS (nested under user)
─────────────────────────────────────────────────
GET    /users/{uid}/orders       List orders for user
POST   /users/{uid}/orders       Create order for user → 201
GET    /users/{uid}/orders/{id}  Get specific order
PATCH  /users/{uid}/orders/{id}  Update order (e.g., cancel)
DELETE /users/{uid}/orders/{id}  Delete order → 204

ORDER ITEMS (keep flat if depth would be > 2)
─────────────────────────────────────────────────
GET    /orders/{id}/items        List items in an order
POST   /orders/{id}/items        Add item to order

SEARCH (cross-resource, can't nest cleanly)
─────────────────────────────────────────────────
GET    /search?q=...&type=users,orders   Global search

ACTIONS (non-CRUD verbs — use sub-resources)
─────────────────────────────────────────────────
POST   /users/{id}/deactivate    Deactivate account (action as sub-resource)
POST   /orders/{id}/cancel       Cancel order
POST   /orders/{id}/refund       Issue refund
POST   /payments/{id}/capture    Capture authorized payment
"""

# Pydantic models for a user — explicit, validated, documented
class CreateUserRequest(BaseModel):
    email: EmailStr = Field(..., description="User's email — must be unique")
    name: str = Field(..., min_length=1, max_length=100)
    role: str = Field(default="viewer", pattern="^(admin|editor|viewer)$")


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    created_at: str
    # NEVER include: password_hash, internal flags, PII not needed by client


class CreateOrderRequest(BaseModel):
    items: List[dict] = Field(..., min_length=1)  # At least one item
    shipping_address_id: str
    coupon_code: Optional[str] = None


# Example endpoint showing all REST principles together
@app.post(
    "/users/{user_id}/orders",
    status_code=201,               # 201 Created, not 200
    summary="Create an order for a user",
)
async def create_order(
    user_id: str,
    payload: CreateOrderRequest,
    request: Request,
):
    # Step 1: Verify user exists — 404 if not
    # user = db.get_user(user_id)
    # if not user: raise HTTPException(404, {"code": "USER_NOT_FOUND", ...})

    # Step 2: Check idempotency key to prevent duplicate orders
    idempotency_key = request.headers.get("Idempotency-Key")
    # if idempotency_key: check Redis; return cached if found

    # Step 3: Validate business rules (items in stock, address valid, etc.)
    # Raise 422 with details if validation fails

    # Step 4: Create order in DB
    order_id = "order_" + str(uuid.uuid4())[:8]

    # Step 5: Return 201 with Location header pointing to new resource
    response_data = {"id": order_id, "user_id": user_id, "status": "pending"}

    return JSONResponse(
        status_code=201,
        content={"data": response_data},
        headers={
            "Location": f"/users/{user_id}/orders/{order_id}",  # Clients can follow this
        },
    )


# ─────────────────────────────────────────────────────────────
# SECTION 9: HATEOAS (Bonus — Rarely Implemented, Good to Know)
# ─────────────────────────────────────────────────────────────

# HATEOAS = Hypermedia As The Engine Of Application State
# Responses include links to all valid next actions
# Client navigates API by following links, not hard-coding URLs
# Rarely implemented in practice — most APIs just document their URLs

HATEOAS_RESPONSE_EXAMPLE = {
    "data": {
        "id": "order_abc123",
        "status": "pending",
        "total": 4999,
    },
    "_links": {
        "self": {"href": "/orders/order_abc123", "method": "GET"},
        "cancel": {"href": "/orders/order_abc123/cancel", "method": "POST"},
        "pay": {"href": "/orders/order_abc123/payment", "method": "POST"},
        "user": {"href": "/users/user_456", "method": "GET"},
    },
    # Client reads _links to know what actions are available in this state
    # Once paid, "pay" link disappears; "refund" link appears
}
