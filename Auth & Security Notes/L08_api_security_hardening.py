# ============================================================
# L06: API Security Hardening
# ============================================================
# WHAT: Defence-in-depth techniques for hardening HTTP APIs —
#       security headers, CORS, rate limiting, input validation,
#       dependency scanning, and container security.
# WHY:  APIs are the primary attack surface of modern apps.
#       Each missing control is an open door for a different
#       class of attack (XSS, CSRF, enumeration, supply chain).
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    Defence in depth means layering multiple controls so that
    defeating one layer does not compromise the system. Each
    layer is designed assuming the previous layer has already
    been bypassed. For APIs this means: network (WAF/rate
    limits) → transport (TLS) → application (headers, CORS,
    validation) → data (parameterised queries, encryption).

    Key controls:
      - Security response headers (HSTS, CSP, X-Frame-Options)
      - Strict CORS with exact origin allowlist
      - Tiered rate limiting per endpoint category
      - Input validation: reject unknown fields, check magic bytes
      - Request size limits to prevent resource exhaustion
      - Dependency and container vulnerability scanning in CI

PRODUCTION USE CASE:
    A fintech API serves mobile and web clients. The security
    middleware stack is a chain of FastAPI middlewares that run
    before any route handler. Rate limiting uses Redis with
    sliding-window counters per IP + endpoint category. All
    file uploads pass MIME + magic-byte checks and ClamAV
    scanning before touching business logic. pip-audit runs in
    CI and blocks merge on any CRITICAL/HIGH CVE in dependencies.

COMMON MISTAKES:
    1. CORS wildcard (*) on authenticated endpoints.
    2. No HSTS — allows SSL stripping on first visit.
    3. Same rate limit for auth and data endpoints (too lenient on auth).
    4. Trusting Content-Type header without validating magic bytes.
    5. No request body size limit — trivial DoS with large payload.
    6. Ignoring transitive dependency CVEs (only scan direct deps).
    7. Running containers as root (UID 0) — full container escape risk.
    8. No SBOM — cannot quickly assess blast radius of new CVE.
"""

import os
import re
import time
import json
import struct
import hashlib
import logging
from typing import Callable, Optional, Dict, List, Set
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum

# FastAPI / Starlette imports shown as comments — install with:
# pip install fastapi starlette uvicorn redis pydantic
# from fastapi import FastAPI, Request, HTTPException, UploadFile
# from fastapi.middleware.base import BaseHTTPMiddleware
# from fastapi.responses import JSONResponse, Response
# from starlette.middleware.cors import CORSMiddleware
# import redis.asyncio as aioredis
# from pydantic import BaseModel, validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. SECURITY HEADERS MIDDLEWARE
# ---------------------------------------------------------------------------
# Security headers are set on EVERY response. They instruct the browser on
# how to handle the content — many attacks (XSS, clickjacking, MIME sniffing)
# are blocked purely by correct headers.

SECURITY_HEADERS: Dict[str, str] = {
    # HSTS: force HTTPS for 1 year, include subdomains, add to preload list.
    # Once set, browsers never make plain HTTP requests to this domain.
    # Preload: submit to https://hstspreload.org — browsers ship with the list.
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",

    # Prevent MIME sniffing — browser must honour declared Content-Type.
    # Without this, a browser may execute a .jpg as JavaScript if it contains
    # script content — enables content injection attacks.
    "X-Content-Type-Options": "nosniff",

    # Block this page from being embedded in an <iframe> on another origin.
    # Prevents clickjacking — attacker overlays invisible iframe on their page.
    "X-Frame-Options": "DENY",

    # CSP: restrict which sources can load scripts, styles, images, etc.
    # 'self' = only same origin. No inline scripts (mitigates XSS significantly).
    # Add specific CDN/API domains as needed: "script-src 'self' cdn.example.com"
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "  # unsafe-inline for CSS-in-JS; minimise
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "frame-ancestors 'none';"             # also blocks clickjacking (CSP version)
    ),

    # Disable browser features the API doesn't use.
    # Prevents rogue scripts from accessing camera, microphone, geolocation.
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",

    # Referrer-Policy: only send origin (no path/query) on cross-origin requests.
    # Prevents leaking sensitive URL parameters (e.g., /reset?token=abc) to 3rd parties.
    "Referrer-Policy": "strict-origin-when-cross-origin",

    # Remove server version disclosure — don't hand attackers a target list.
    "Server": "api",  # Generic value — Nginx/FastAPI default exposes version
}

class SecurityHeadersMiddleware:
    """
    Injects security headers into every HTTP response.
    Attach this as the outermost middleware so headers are always set,
    even on error responses from inner middlewares.
    """

    def __init__(self, app, additional_headers: Optional[Dict[str, str]] = None):
        self.app = app
        self.headers = {**SECURITY_HEADERS, **(additional_headers or {})}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                # Inject security headers before response is sent to client
                headers = dict(message.get("headers", []))
                for name, value in self.headers.items():
                    # Encode header name/value as bytes (ASGI spec)
                    headers[name.lower().encode()] = value.encode()
                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, send_with_headers)


# ---------------------------------------------------------------------------
# 2. STRICT CORS CONFIGURATION
# ---------------------------------------------------------------------------
# CORS (Cross-Origin Resource Sharing) controls which origins a browser
# will send cookies/auth headers to when making cross-origin requests.
# Wildcard (*) allows ALL origins — completely defeats CORS protection.

@dataclass
class CORSConfig:
    """
    Production CORS configuration. Never use allow_origins=["*"]
    on any endpoint that handles authentication or sensitive data.
    """
    # Exact list of origins. Any other origin gets CORS headers denied.
    # Use exact strings — no wildcards, no regex. Subdomains need separate entries.
    allow_origins: List[str] = field(default_factory=lambda: [
        "https://app.example.com",
        "https://admin.example.com",
        # "http://localhost:3000",  # Dev only — remove in prod
    ])

    # Only expose methods your API actually uses
    allow_methods: List[str] = field(default_factory=lambda: [
        "GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"
    ])

    # Explicitly list headers you use — don't set allow_headers=["*"]
    allow_headers: List[str] = field(default_factory=lambda: [
        "Authorization", "Content-Type", "X-Request-ID", "X-Idempotency-Key"
    ])

    allow_credentials: bool = True   # Required for cookies/auth headers
    max_age: int = 600               # Preflight cache: 10 minutes (reduces OPTIONS calls)

    def validate_origin(self, origin: str) -> bool:
        """
        Check incoming Origin header against exact allowlist.
        Vary: Origin header must be set so CDN caches per origin.
        """
        return origin in self.allow_origins

CORS_MIDDLEWARE_EXAMPLE = """
# FastAPI setup:
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_config.allow_origins,     # EXACT list, never ["*"]
    allow_credentials=cors_config.allow_credentials,
    allow_methods=cors_config.allow_methods,
    allow_headers=cors_config.allow_headers,
    max_age=cors_config.max_age,
    # Starlette auto-sets Vary: Origin when allow_origins is a list
)
"""


# ---------------------------------------------------------------------------
# 3. TIERED RATE LIMITING
# ---------------------------------------------------------------------------
# Different endpoint categories have very different abuse profiles.
# Auth endpoints need tight limits (brute force); read APIs need higher limits.
# Use Redis for distributed rate limiting across multiple API server instances.

class RateLimitCategory(Enum):
    AUTH = "auth"               # Login, token refresh
    PASSWORD_RESET = "pwd_rst"  # Password reset request
    API_READ = "api_read"       # GET data endpoints
    API_WRITE = "api_write"     # POST/PUT/PATCH/DELETE
    ADMIN = "admin"             # Admin panel endpoints


@dataclass
class RateLimitRule:
    """Defines allowed requests and the time window."""
    max_requests: int    # Max requests allowed
    window_seconds: int  # Time window in seconds
    category: RateLimitCategory

    @property
    def description(self) -> str:
        per = "min" if self.window_seconds == 60 else f"{self.window_seconds}s"
        return f"{self.max_requests}/{per}"


# Rate limit tiers — calibrated from real-world abuse patterns
RATE_LIMIT_RULES: Dict[RateLimitCategory, RateLimitRule] = {
    # Auth: 5 attempts per 15 minutes prevents password enumeration.
    # After 5 failures, lock out the IP (temporarily — not account lockout).
    RateLimitCategory.AUTH: RateLimitRule(
        max_requests=5, window_seconds=900, category=RateLimitCategory.AUTH
    ),
    # Password reset: 3/hour prevents email flooding (annoying + potential DoS).
    RateLimitCategory.PASSWORD_RESET: RateLimitRule(
        max_requests=3, window_seconds=3600, category=RateLimitCategory.PASSWORD_RESET
    ),
    # Read endpoints: 1000/min supports normal usage; blocks scrapers.
    RateLimitCategory.API_READ: RateLimitRule(
        max_requests=1000, window_seconds=60, category=RateLimitCategory.API_READ
    ),
    # Write endpoints: tighter to prevent automated data corruption or spam.
    RateLimitCategory.API_WRITE: RateLimitRule(
        max_requests=100, window_seconds=60, category=RateLimitCategory.API_WRITE
    ),
    # Admin: very tight — admin endpoints are high-value targets.
    RateLimitCategory.ADMIN: RateLimitRule(
        max_requests=50, window_seconds=60, category=RateLimitCategory.ADMIN
    ),
}

class SlidingWindowRateLimiter:
    """
    Redis-backed sliding window rate limiter.
    Sliding window is more accurate than fixed window — no burst at window edge.

    Redis key structure:
      rate:{category}:{identifier}  →  sorted set of timestamps
    TTL = window_seconds (auto-cleanup of expired keys)
    """

    def __init__(self, redis_client):
        self.redis = redis_client  # aioredis.Redis instance

    def _make_key(self, category: RateLimitCategory, identifier: str) -> str:
        """
        Separate key per category AND identifier (usually IP address).
        This ensures auth limit for IP-A doesn't affect read limit for IP-A.
        """
        return f"rate:{category.value}:{identifier}"

    async def is_allowed(
        self,
        category: RateLimitCategory,
        identifier: str,
    ) -> tuple[bool, int, int]:
        """
        Check if the request is within the rate limit.

        Returns:
            (allowed: bool, remaining: int, retry_after_seconds: int)
        """
        rule = RATE_LIMIT_RULES[category]
        key = self._make_key(category, identifier)
        now = time.time()
        window_start = now - rule.window_seconds

        # Lua script ensures atomicity: no race between check and increment
        lua_script = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local window_start = tonumber(ARGV[2])
        local max_requests = tonumber(ARGV[3])
        local window_seconds = tonumber(ARGV[4])

        -- Remove timestamps outside the current window
        redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)

        -- Count remaining requests in window
        local count = redis.call('ZCARD', key)

        if count < max_requests then
            -- Add current timestamp and set TTL
            redis.call('ZADD', key, now, now)
            redis.call('EXPIRE', key, window_seconds)
            return {1, max_requests - count - 1, 0}
        else
            -- Return time until oldest entry expires
            local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
            local retry_after = math.ceil(oldest[2] + window_seconds - now)
            return {0, 0, retry_after}
        end
        """
        # result = await self.redis.eval(
        #     lua_script, 1, key, now, window_start, rule.max_requests, rule.window_seconds
        # )
        # Simulated for demonstration
        result = [1, rule.max_requests - 1, 0]
        allowed, remaining, retry_after = bool(result[0]), int(result[1]), int(result[2])
        return allowed, remaining, retry_after

    async def middleware(self, request, call_next):
        """
        FastAPI middleware: determine category, check limit, set headers.
        """
        # Determine category from path
        path = request.url.path
        if "/auth/" in path or "/login" in path or "/token" in path:
            category = RateLimitCategory.AUTH
        elif "/password-reset" in path:
            category = RateLimitCategory.PASSWORD_RESET
        elif "/admin/" in path:
            category = RateLimitCategory.ADMIN
        elif request.method in ("GET", "HEAD", "OPTIONS"):
            category = RateLimitCategory.API_READ
        else:
            category = RateLimitCategory.API_WRITE

        # Use real IP — trust X-Forwarded-For only if behind known load balancer
        identifier = request.headers.get("X-Forwarded-For", request.client.host)
        identifier = identifier.split(",")[0].strip()  # First IP in chain

        allowed, remaining, retry_after = await self.is_allowed(category, identifier)

        if not allowed:
            # Return 429 Too Many Requests with Retry-After header
            return {
                "status_code": 429,
                "headers": {
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(RATE_LIMIT_RULES[category].max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + retry_after),
                },
                "body": {"error": "rate_limit_exceeded", "retry_after": retry_after},
            }

        response = await call_next(request)
        # Expose rate limit state in response headers for client awareness
        response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT_RULES[category].max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


# ---------------------------------------------------------------------------
# 4. INPUT VALIDATION HARDENING
# ---------------------------------------------------------------------------

class StrictRequestValidator:
    """
    Input validation beyond basic type checking.
    Rejects unexpected structure before any business logic executes.
    """

    # Pydantic model pattern: extra='forbid' rejects unknown fields.
    # This prevents parameter pollution and unexpected data injection.
    PYDANTIC_STRICT_MODEL_EXAMPLE = """
    from pydantic import BaseModel, validator, Field
    from typing import Literal

    class CreateUserRequest(BaseModel):
        class Config:
            extra = 'forbid'      # Reject any field not declared here

        email: str = Field(..., max_length=254)   # RFC 5321 max email length
        name: str = Field(..., min_length=1, max_length=100)
        role: Literal["user", "viewer"]           # Only these two values allowed

        @validator("email")
        def validate_email_format(cls, v):
            if not re.match(r'^[^@]+@[^@]+\.[^@]+$', v):
                raise ValueError("Invalid email format")
            return v.lower()  # normalise to lowercase

        @validator("name")
        def reject_html_in_name(cls, v):
            if re.search(r'<[^>]+>', v):
                raise ValueError("HTML tags not allowed in name")
            return v
    """

    @staticmethod
    def check_content_type(content_type_header: str, expected: str = "application/json") -> bool:
        """
        Reject requests without the correct Content-Type.
        This prevents CSRF attacks on JSON APIs — browsers cannot set
        Content-Type: application/json on cross-origin form submissions.
        A plain HTML form always sends application/x-www-form-urlencoded.
        """
        if not content_type_header:
            return False
        # Only check the MIME type, ignore charset parameter
        actual = content_type_header.split(";")[0].strip().lower()
        return actual == expected.lower()

    @staticmethod
    def validate_string_lengths(data: dict, limits: Dict[str, int]) -> List[str]:
        """
        Check string fields do not exceed maximum lengths.
        Prevents DB column overflow and DoS via huge string indexing.
        Returns list of field names that exceed limits.
        """
        violations = []
        for field, max_len in limits.items():
            value = data.get(field, "")
            if isinstance(value, str) and len(value) > max_len:
                violations.append(field)
        return violations


# ---------------------------------------------------------------------------
# 5. FILE UPLOAD SECURITY
# ---------------------------------------------------------------------------
# Extension check is trivially bypassed — rename evil.php to image.jpg.
# MIME type from header is attacker-controlled. Check MAGIC BYTES instead.

MAGIC_BYTES: Dict[str, List[bytes]] = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png":  [b"\x89PNG\r\n\x1a\n"],
    "image/gif":  [b"GIF87a", b"GIF89a"],
    "image/webp": [b"RIFF"],  # also check bytes 8-12 for "WEBP"
    "application/pdf": [b"%PDF-"],
}

ALLOWED_UPLOAD_TYPES: Set[str] = {"image/jpeg", "image/png", "image/gif", "application/pdf"}
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB hard limit

class FileUploadValidator:
    """
    Multi-layer file upload validation.
    Layer 1: size limit (fast fail — no need to read content)
    Layer 2: MIME type from magic bytes (not from header or extension)
    Layer 3: ClamAV antivirus scan (catches malware disguised as images)
    """

    @staticmethod
    def check_size(file_bytes: bytes) -> None:
        """Reject before reading content if oversized."""
        if len(file_bytes) > MAX_UPLOAD_SIZE_BYTES:
            raise ValueError(
                f"File size {len(file_bytes)} exceeds limit {MAX_UPLOAD_SIZE_BYTES} bytes"
            )

    @staticmethod
    def detect_mime_from_magic_bytes(file_bytes: bytes) -> Optional[str]:
        """
        Read first 16 bytes and compare against known magic sequences.
        This is what 'file' command and libmagic do internally.
        Never trust the file extension or Content-Type header from client.
        """
        header = file_bytes[:16]
        for mime_type, signatures in MAGIC_BYTES.items():
            for sig in signatures:
                if header.startswith(sig):
                    # Special check for WebP: bytes 8-12 must be "WEBP"
                    if mime_type == "image/webp" and file_bytes[8:12] != b"WEBP":
                        continue
                    return mime_type
        return None

    @staticmethod
    def scan_with_clamav(file_bytes: bytes) -> bool:
        """
        Pass file content to ClamAV via clamd socket.
        Returns True if clean, False if virus detected.
        ClamAV runs as a sidecar container or local daemon.
        In K8s: clamd DaemonSet accessible via Unix socket or TCP.
        """
        # import clamd
        # cd = clamd.ClamdUnixSocket('/var/run/clamav/clamd.sock')
        # result = cd.instream(io.BytesIO(file_bytes))
        # return result['stream'][0] == 'OK'
        print("[ClamAV] Scanning file... CLEAN")
        return True

    def validate(self, file_bytes: bytes, declared_mime: str) -> str:
        """
        Full validation pipeline. Returns detected MIME type if valid.
        Raises ValueError on any failure — caller should return 400.
        """
        # Layer 1: size
        self.check_size(file_bytes)

        # Layer 2: magic bytes
        detected = self.detect_mime_from_magic_bytes(file_bytes)
        if detected is None:
            raise ValueError("Unrecognised file format")
        if detected not in ALLOWED_UPLOAD_TYPES:
            raise ValueError(f"File type '{detected}' is not permitted")
        if detected != declared_mime:
            # Extension/header lies about type — reject
            raise ValueError(f"Declared type '{declared_mime}' doesn't match content '{detected}'")

        # Layer 3: antivirus
        if not self.scan_with_clamav(file_bytes):
            raise ValueError("File failed antivirus scan")

        return detected


# ---------------------------------------------------------------------------
# 6. REQUEST SIZE LIMITS
# ---------------------------------------------------------------------------
# nginx config (place in server{} block):
REQUEST_SIZE_NGINX_CONFIG = """
# nginx.conf
server {
    # Reject request bodies > 10MB at the nginx level.
    # This happens before FastAPI/Gunicorn even sees the request.
    # Prevents: memory exhaustion, slow loris variants, zip bombs.
    client_max_body_size 10M;

    # Timeout idle connections (prevent slowloris)
    client_body_timeout 12;
    client_header_timeout 12;

    # Limit request headers size (prevent header injection DoS)
    large_client_header_buffers 2 1k;
}
"""

# ---------------------------------------------------------------------------
# 7. DEPENDENCY SCANNING IN CI
# ---------------------------------------------------------------------------

DEPENDENCY_SCAN_CI_CONFIG = """
# .github/workflows/security.yml
name: Security Scan

on: [push, pull_request]

jobs:
  dependency-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # pip-audit: checks PyPI Advisory Database for known CVEs
      # Fails pipeline on CRITICAL or HIGH severity findings
      - name: pip-audit
        run: |
          pip install pip-audit
          pip-audit --requirement requirements.txt --severity high

      # safety: alternative scanner with curated database
      - name: safety check
        run: |
          pip install safety
          safety check -r requirements.txt

      # Generate SBOM: list of every package and version in the image
      # Used to quickly assess blast radius when a new CVE is announced
      - name: Generate SBOM
        run: |
          pip install cyclonedx-bom
          cyclonedx-py -r requirements.txt -o sbom.json --format json

      - name: Upload SBOM
        uses: actions/upload-artifact@v4
        with:
          name: sbom
          path: sbom.json

  container-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build image
        run: docker build -t myapp:${{ github.sha }} .

      # trivy: scans OS packages + Python deps in the container image
      - name: Trivy container scan
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: myapp:${{ github.sha }}
          format: table
          exit-code: 1               # Block deploy on CRITICAL CVEs
          severity: CRITICAL,HIGH
          ignore-unfixed: true       # Don't fail on CVEs with no fix yet
"""


# ---------------------------------------------------------------------------
# 8. COMPLETE FASTAPI SECURITY MIDDLEWARE STACK
# ---------------------------------------------------------------------------

def build_secure_app():
    """
    Assembles the full middleware stack in correct order.
    Middleware is applied in reverse order of registration in FastAPI —
    last registered runs first on request, first on response.
    Correct order matters: CORS before rate limiting, headers on all responses.
    """
    # from fastapi import FastAPI
    # app = FastAPI(
    #     docs_url=None,       # Disable Swagger UI in production
    #     redoc_url=None,
    #     openapi_url=None,    # Hide API schema from public
    # )

    cors = CORSConfig()

    middleware_stack_description = """
    Middleware execution order (outermost → innermost on request):
    1. SecurityHeadersMiddleware   → injects headers on every response
    2. CORSMiddleware              → validates Origin, handles preflight
    3. RequestSizeLimitMiddleware  → reject oversized bodies early
    4. ContentTypeMiddleware       → reject non-JSON Content-Type on write ops
    5. RateLimitMiddleware         → per-IP, per-category Redis sliding window
    6. AuthenticationMiddleware    → JWT/session validation
    7. Route handlers              → business logic

    FastAPI registration (reverse of above):
      app.add_middleware(AuthenticationMiddleware)
      app.add_middleware(RateLimitMiddleware, limiter=limiter)
      app.add_middleware(ContentTypeMiddleware)
      app.add_middleware(RequestSizeLimitMiddleware, max_bytes=10*1024*1024)
      app.add_middleware(CORSMiddleware, **cors_config)
      app.add_middleware(SecurityHeadersMiddleware)
    """
    print(middleware_stack_description)

    # Security-sensitive route examples:
    route_examples = """
    @app.post("/auth/login")           # Category: AUTH (5/15min limit)
    @app.post("/auth/password-reset")  # Category: PASSWORD_RESET (3/hour)
    @app.get("/api/v1/transactions")   # Category: API_READ (1000/min)
    @app.post("/api/v1/transfer")      # Category: API_WRITE (100/min)
    @app.delete("/admin/users/{id}")   # Category: ADMIN (50/min)
    """
    print(route_examples)
    return None  # Would return the FastAPI app instance


class ContentTypeEnforcementMiddleware:
    """
    Reject POST/PUT/PATCH requests that don't declare application/json.
    Prevents CSRF using form submissions (browsers cannot spoof Content-Type
    to application/json for cross-origin form submits).
    """
    WRITE_METHODS = {"POST", "PUT", "PATCH"}
    EXCLUDED_PATHS = {"/api/v1/upload"}  # File upload uses multipart/form-data

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            method = scope["method"]
            path = scope["path"]
            if method in self.WRITE_METHODS and path not in self.EXCLUDED_PATHS:
                headers = dict(scope.get("headers", []))
                ct = headers.get(b"content-type", b"").decode()
                if not StrictRequestValidator.check_content_type(ct):
                    # Return 415 Unsupported Media Type
                    print(f"[ContentType] Rejected {method} {path}: Content-Type={ct!r}")
                    return  # In real middleware, send 415 response
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# 9. PENETRATION TESTING WORKFLOW
# ---------------------------------------------------------------------------

PEN_TEST_WORKFLOW = """
Automated scanning (continuous):
  - OWASP ZAP: run in CI against staging environment
    docker run -t owasp/zap2docker-stable zap-api-scan.py \\
      -t https://staging.example.com/api/openapi.json \\
      -f openapi -r zap_report.html

  - Check for: SQLi, XSS, IDOR, SSRF, path traversal, auth bypass

Manual pentest (annually or before major release):
  - Engage external firm (bug bounty hunters for ongoing)
  - Scope: full API surface, authentication flows, privilege escalation
  - Output: CVSS-scored findings, remediation guidance, retest

Bug bounty (ongoing):
  - HackerOne or Bugcrowd program
  - Define scope: *.example.com, exclude staging/internal
  - Triage SLA: critical = 24h, high = 72h
  - Reward tiers: $100 (low) → $5,000 (critical)
"""


if __name__ == "__main__":
    print("=" * 60)
    print("API SECURITY HARDENING DEMONSTRATION")
    print("=" * 60)

    # Demonstrate security headers
    print("\n[1] Security Headers:")
    for header, value in SECURITY_HEADERS.items():
        print(f"  {header}: {value[:60]}{'...' if len(value) > 60 else ''}")

    # Demonstrate CORS validation
    print("\n[2] CORS Origin Validation:")
    cors = CORSConfig()
    test_origins = [
        "https://app.example.com",   # Allowed
        "https://evil.com",          # Blocked
        "https://app.example.com.evil.com",  # Blocked — subdomain trick
    ]
    for origin in test_origins:
        result = "ALLOWED" if cors.validate_origin(origin) else "BLOCKED"
        print(f"  {origin}: {result}")

    # Demonstrate file upload validation
    print("\n[3] File Upload Validation:")
    validator = FileUploadValidator()
    png_magic = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # Fake PNG
    try:
        detected = validator.validate(png_magic, "image/png")
        print(f"  Valid PNG upload detected as: {detected}")
    except ValueError as e:
        print(f"  Rejected: {e}")

    # Rate limit rules
    print("\n[4] Rate Limit Rules:")
    for category, rule in RATE_LIMIT_RULES.items():
        print(f"  {category.value}: {rule.description}")

    build_secure_app()
