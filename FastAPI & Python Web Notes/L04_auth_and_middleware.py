# ============================================================
# L04: Authentication and Middleware in FastAPI
# ============================================================
# WHAT: JWT-based authentication (access + refresh token pattern), password
#       hashing with bcrypt via passlib, role-based access control, and
#       production middleware patterns: request IDs, timing, rate limiting,
#       and security headers. Also covers API key auth for M2M scenarios.
#
# WHY:  Auth is the most security-critical part of any API. One mistake —
#       storing plain passwords, putting secrets in localStorage, skipping
#       token expiry — can compromise all users. Middleware handles concerns
#       that apply to every request (tracing, throttling, headers) without
#       polluting route handlers with cross-cutting logic.
#
# LEVEL: Intermediate → Production
# ============================================================
"""
CONCEPT OVERVIEW:
    JWT (JSON Web Token) flow:
        POST /auth/token  →  verify credentials  →  issue access + refresh tokens
        GET  /protected   →  extract Bearer token  →  decode  →  serve request
        POST /auth/refresh →  validate refresh token  →  issue new access token

    Access token: short-lived (15 min), stored in memory (JS variable).
    Refresh token: long-lived (7 days), stored in httpOnly cookie (JS cannot
    read it — XSS-proof). The refresh endpoint issues a new access token when
    the old one expires.

    Middleware execution order (LIFO — last added = outermost):
        add_middleware(Security)  → runs last inbound, first outbound
        add_middleware(Timing)    → wraps inside Security
        add_middleware(RequestID) → innermost wrapper
    Think of it as nested layers around every request.

PRODUCTION USE CASE:
    SaaS API where the frontend (React) stores the access token in memory
    and the refresh token in an httpOnly cookie. The rate limiter allows
    5 login attempts per minute per IP — brute-force protection. All
    responses include HSTS and CSP headers. Every log line includes the
    request ID for distributed tracing with Datadog / Grafana.

COMMON MISTAKES:
    1. Storing access tokens in localStorage — XSS can steal them. Use
       memory (JS variable) for access tokens and httpOnly cookies for
       refresh tokens.
    2. Not setting token expiry (exp claim) — tokens live forever if the
       secret leaks.
    3. Using MD5 or SHA-256 to hash passwords — both are fast, which makes
       brute force trivial. Use bcrypt (intentionally slow, salted).
    4. Returning 401 vs 403: 401 = "I don't know who you are" (no/bad token).
       403 = "I know who you are but you don't have permission" (wrong role).
    5. Not including WWW-Authenticate: Bearer in 401 responses — required
       by RFC 6750; some clients (OAuth2 libraries) depend on it.
    6. Rate limiting only at the application level — a DDoS can still exhaust
       connections before middleware runs. Always also use a reverse proxy
       (nginx, Cloudflare) for IP-level limiting.
"""

from __future__ import annotations

import uuid
import time
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional, Any

# FastAPI
from fastapi import (
    FastAPI, APIRouter, Depends, HTTPException, Request, Response,
    status, Cookie,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm, APIKeyHeader

# Pydantic
from pydantic import BaseModel, EmailStr, Field

# JWT — pip install python-jose[cryptography]
from jose import JWTError, jwt

# Password hashing — pip install passlib[bcrypt]
from passlib.context import CryptContext

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===========================================================================
# CONFIGURATION
# In production: load from environment variables, never hardcode secrets.
# SECRET_KEY must be >= 32 random bytes. Generate with:
#   python -c "import secrets; print(secrets.token_hex(32))"
# ===========================================================================

SECRET_KEY = "CHANGE_ME_IN_PRODUCTION_use_secrets_token_hex_32_characters_minimum"
ALGORITHM = "HS256"                         # HMAC-SHA256 — symmetric, fast, standard
ACCESS_TOKEN_TTL_MINUTES = 15               # short-lived — limits damage if leaked
REFRESH_TOKEN_TTL_DAYS = 7                  # long-lived — stored in httpOnly cookie

REFRESH_COOKIE_NAME = "refresh_token"       # cookie name — consistent everywhere


# ===========================================================================
# PASSWORD HASHING
# CryptContext wraps multiple schemes; bcrypt is the current best practice.
# bcrypt intentionally uses multiple rounds of slow hashing to resist brute force.
# deprecated="auto" lets you migrate to a newer scheme later without user action.
# ===========================================================================

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Hash a plain-text password. Never store the plain text."""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Compare plain text against stored hash. Safe against timing attacks."""
    return pwd_context.verify(plain, hashed)


# ===========================================================================
# IN-MEMORY STORES (replace with PostgreSQL + Redis in production)
# ===========================================================================

# Simulated user table: email → user record
USERS: dict[str, dict] = {
    "alice@example.com": {
        "id": 1,
        "email": "alice@example.com",
        "name": "Alice",
        "hashed_password": hash_password("Secret123!"),
        "role": "admin",
        "is_active": True,
    },
    "bob@example.com": {
        "id": 2,
        "email": "bob@example.com",
        "name": "Bob",
        "hashed_password": hash_password("Password456!"),
        "role": "user",
        "is_active": True,
    },
}

# Revoked refresh tokens (real: Redis set with TTL matching token TTL)
REVOKED_REFRESH_TOKENS: set[str] = set()

# Rate limit store: IP → list of request timestamps (real: Redis sliding window)
RATE_LIMIT_STORE: dict[str, list[float]] = {}

# Valid API keys for M2M auth (real: DB table or Redis set)
VALID_API_KEYS: set[str] = {"service-key-abc123", "worker-key-xyz789"}


# ===========================================================================
# PYDANTIC SCHEMAS
# ===========================================================================

class UserRegister(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8, description="Min 8 chars")


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    is_active: bool


class TokenResponse(BaseModel):
    """Returned from POST /auth/token. Access token in body; refresh in cookie."""
    access_token: str
    token_type: str = "bearer"              # RFC 6750 — always "bearer"
    expires_in: int = ACCESS_TOKEN_TTL_MINUTES * 60  # seconds (for client JS)


# ===========================================================================
# JWT UTILITIES
# ===========================================================================

def create_access_token(subject: str, extra_claims: dict | None = None) -> str:
    """
    Issue a signed JWT access token.
    `sub` (subject) is the standard claim for user identity — use user ID or email.
    `exp` must always be set — missing exp = token never expires.
    `iat` (issued-at) is optional but useful for debugging.
    """
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES)
    payload = {
        "sub": subject,                     # who the token is about
        "exp": expires,                     # expiry — jose validates this automatically
        "iat": now,                         # issued-at
        "type": "access",                   # custom claim — lets us reject refresh tokens here
        **(extra_claims or {}),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(subject: str) -> str:
    """Issue a longer-lived refresh token. Stored in httpOnly cookie, not JS."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=REFRESH_TOKEN_TTL_DAYS)
    payload = {
        "sub": subject,
        "exp": expires,
        "iat": now,
        "type": "refresh",                  # distinct type — rejected by access-token checks
        "jti": str(uuid.uuid4()),           # JWT ID — unique per token, used for revocation
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str, expected_type: str) -> dict:
    """
    Decode and validate a JWT. Raises HTTPException on any failure.
    jose automatically validates: signature, expiry (exp), not-before (nbf).
    We additionally validate the `type` claim to prevent token substitution
    (using a refresh token where an access token is expected).
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},  # RFC 6750 — required in 401
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        # Covers: invalid signature, expired token, malformed JWT
        raise credentials_exception

    if payload.get("type") != expected_type:
        # Prevent using a refresh token as an access token (and vice versa)
        raise credentials_exception

    return payload


# ===========================================================================
# AUTH DEPENDENCIES
# ===========================================================================

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserOut:
    """
    Core auth dependency: extract Bearer token → decode → lookup user.
    Every protected route declares: current_user: UserOut = Depends(get_current_user)
    """
    payload = decode_token(token, expected_type="access")
    email: Optional[str] = payload.get("sub")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = USERS.get(email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return UserOut(**{k: v for k, v in user.items() if k != "hashed_password"})


async def require_active(current_user: UserOut = Depends(get_current_user)) -> UserOut:
    """Reject deactivated accounts. Chain: get_current_user → require_active."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated.",
        )
    return current_user


def require_role(role: str):
    """
    Parameterised dependency factory for role-based access control.
    Usage: Depends(require_role("admin"))
    Returns a dependency function — FastAPI calls it per request.
    """
    async def _check(current_user: UserOut = Depends(require_active)) -> UserOut:
        if current_user.role != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,  # 403 NOT 401 — we know who they are
                detail=f"Role '{role}' required. Your role: '{current_user.role}'.",
            )
        return current_user
    return _check


# ===========================================================================
# API KEY DEPENDENCY — machine-to-machine (no user context)
# ===========================================================================

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: Optional[str] = Depends(api_key_header)) -> str:
    if not api_key or api_key not in VALID_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key.",
        )
    return api_key


# ===========================================================================
# RATE LIMITER HELPER — sliding window algorithm
# Real implementation: use Redis with ZADD/ZRANGEBYSCORE for atomicity.
# This in-memory version is per-process only — doesn't work across workers.
# ===========================================================================

def check_rate_limit(ip: str, max_requests: int = 5, window_seconds: int = 60) -> None:
    """
    Sliding window rate limiter. Raises 429 if IP exceeds max_requests
    within the last window_seconds.
    Production: use `slowapi` library or Redis ZADD/ZRANGEBYSCORE.
    """
    now = time.time()
    window_start = now - window_seconds

    # Clean old timestamps outside the window
    timestamps = RATE_LIMIT_STORE.get(ip, [])
    timestamps = [t for t in timestamps if t > window_start]

    if len(timestamps) >= max_requests:
        # Calculate when the oldest request in window expires
        retry_after = int(timestamps[0] + window_seconds - now) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests. Retry after {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},  # RFC 6585
        )

    timestamps.append(now)
    RATE_LIMIT_STORE[ip] = timestamps


# ===========================================================================
# APP + MIDDLEWARE
# ===========================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Auth service starting up.")
    yield
    logger.info("Auth service shutting down.")


app = FastAPI(title="Auth Service", lifespan=lifespan)

# CORS — must be added before other middleware and routes
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://app.example.com", "http://localhost:3000"],
    allow_credentials=True,                 # needed for cookies (refresh token)
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Middleware 1: Request ID -----------------------------------------------
# UUID per request → attach to request.state → log in every handler.
# Also added to response header for correlation in client-side error reporting.

@app.middleware("http")
async def request_id_middleware(request: Request, call_next) -> Response:
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id   # accessible in route handlers
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id  # client can log this
    return response


# --- Middleware 2: Timing --------------------------------------------------
# Measures wall-clock time for the route handler + all inner middleware.
# Surface as Prometheus gauge in production: histogram_observe(duration).

@app.middleware("http")
async def timing_middleware(request: Request, call_next) -> Response:
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Process-Time"] = f"{duration_ms:.2f}ms"
    logger.info(
        "req_id=%s method=%s path=%s status=%d duration=%.2fms",
        getattr(request.state, "request_id", "?"),
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


# --- Middleware 3: Security Headers ----------------------------------------
# These headers defend against common browser-based attacks.
# Apply to every response — no per-route configuration needed.

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"     # no MIME sniffing
    response.headers["X-Frame-Options"] = "DENY"               # no iframe embedding
    response.headers["X-XSS-Protection"] = "1; mode=block"     # legacy browsers
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"                   # HTTPS only for 1 year
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; frame-ancestors 'none'"            # basic CSP
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ===========================================================================
# AUTH ROUTER
# ===========================================================================

auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(data: UserRegister) -> UserOut:
    """
    Create a new user account.
    Password is hashed immediately — plain text never touches the DB.
    """
    if data.email in USERS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered.",
        )

    # hash_password uses bcrypt — intentionally slow to resist offline brute force
    user_id = len(USERS) + 1
    USERS[data.email] = {
        "id": user_id,
        "email": data.email,
        "name": data.name,
        "hashed_password": hash_password(data.password),  # NEVER store plain text
        "role": "user",
        "is_active": True,
    }
    return UserOut(**{k: v for k, v in USERS[data.email].items() if k != "hashed_password"})


@auth_router.post("/token", response_model=TokenResponse)
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),  # parses form: username + password
) -> TokenResponse:
    """
    Issue access + refresh tokens.
    OAuth2PasswordRequestForm expects form-encoded body (not JSON) because
    the OAuth2 spec requires application/x-www-form-urlencoded for token endpoints.
    Fields: username (email in our case), password.
    """
    # Rate limit: max 5 login attempts per minute per IP — brute force protection
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip, max_requests=5, window_seconds=60)

    user = USERS.get(form_data.username)    # form_data.username = the email field
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated.",
        )

    # Issue tokens
    access_token = create_access_token(subject=user["email"], extra_claims={"role": user["role"]})
    refresh_token = create_refresh_token(subject=user["email"])

    # Refresh token goes into httpOnly cookie — JS cannot read it (XSS-proof)
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,                      # JS cannot access this cookie
        secure=True,                        # only sent over HTTPS
        samesite="lax",                     # CSRF protection for same-site requests
        max_age=REFRESH_TOKEN_TTL_DAYS * 86400,
        path="/auth/refresh",               # cookie only sent to this path
    )

    # Access token in JSON body — client stores in memory (NOT localStorage)
    return TokenResponse(access_token=access_token)


@auth_router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> TokenResponse:
    """
    Exchange a valid refresh token (from httpOnly cookie) for a new access token.
    Cookie(alias=...) reads the cookie by name — FastAPI handles this automatically.
    """
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token cookie missing.",
        )

    # Check if token was explicitly revoked (logout)
    if refresh_token in REVOKED_REFRESH_TOKENS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked. Please log in again.",
        )

    payload = decode_token(refresh_token, expected_type="refresh")
    email = payload.get("sub")
    if not email or email not in USERS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject.")

    user = USERS[email]
    new_access_token = create_access_token(
        subject=email,
        extra_claims={"role": user["role"]},
    )

    return TokenResponse(access_token=new_access_token)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> None:
    """
    Revoke the refresh token and clear the cookie.
    Access tokens cannot be revoked (stateless JWT) — they expire naturally.
    For immediate access token invalidation: use short TTL + token blocklist in Redis.
    """
    if refresh_token:
        REVOKED_REFRESH_TOKENS.add(refresh_token)   # real: SADD revoked_tokens token EX ttl

    # Clear the cookie by setting max_age=0
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path="/auth/refresh",
        secure=True,
        httponly=True,
        samesite="lax",
    )


@auth_router.get("/me", response_model=UserOut)
async def get_me(current_user: UserOut = Depends(require_active)) -> UserOut:
    """Return the currently authenticated user's profile."""
    return current_user


# ===========================================================================
# PROTECTED ROUTES EXAMPLE
# ===========================================================================

protected_router = APIRouter(prefix="/protected", tags=["protected"])


@protected_router.get("/dashboard")
async def user_dashboard(current_user: UserOut = Depends(require_active)) -> dict:
    """Any active logged-in user can access this."""
    return {"message": f"Welcome, {current_user.name}!", "role": current_user.role}


@protected_router.get("/admin/users")
async def admin_list_users(
    _admin: UserOut = Depends(require_role("admin")),  # 403 if not admin
) -> list[UserOut]:
    """Admin only — returns all users. Regular users get 403."""
    return [
        UserOut(**{k: v for k, v in u.items() if k != "hashed_password"})
        for u in USERS.values()
    ]


@protected_router.get("/internal/health")
async def internal_health(
    _key: str = Depends(verify_api_key),   # M2M — API key instead of JWT
) -> dict[str, Any]:
    """Machine-to-machine endpoint. Requires X-API-Key header, not a user token."""
    return {
        "status": "healthy",
        "user_count": len(USERS),
        "revoked_tokens": len(REVOKED_REFRESH_TOKENS),
    }


# ===========================================================================
# REGISTER ROUTERS
# ===========================================================================

app.include_router(auth_router)
app.include_router(protected_router)


@app.get("/", tags=["health"])
async def root() -> dict[str, str]:
    return {"service": "auth-service", "status": "ok"}


# ===========================================================================
# ENTRY POINT
# ===========================================================================

if __name__ == "__main__":
    import uvicorn
    # In production: use gunicorn + UvicornWorker, SSL termination at reverse proxy
    uvicorn.run("L04_auth_and_middleware:app", host="0.0.0.0", port=8003, reload=True)
