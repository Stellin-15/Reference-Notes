# ============================================================
# L07: API Security and Performance
# ============================================================
# WHAT: Security headers, input validation, injection prevention,
#       SSRF blocking, response compression, ETags, cache headers,
#       and partial responses for production APIs.
# WHY:  Security is not optional — breaches destroy companies.
#       Performance headers cut bandwidth 60-80% with no code changes.
#       These patterns are table stakes for any public API.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    Two concerns that must be designed in from the start, not bolted on:

    SECURITY:
        Browsers and HTTP clients follow headers for security policy.
        HSTS forces HTTPS. CSP prevents XSS. Input validation stops
        injection. SSRF protection prevents attackers from using your
        server as a proxy to reach internal infrastructure.

    PERFORMANCE:
        Compression reduces JSON payloads 60-80%. ETags enable 304
        Not Modified responses (no body transmitted). Cache-Control
        tells CDNs and browsers how long to cache. Partial responses
        (?fields=) let mobile clients fetch only what they render.
        HTTP/2 multiplexing eliminates head-of-line blocking.

PRODUCTION USE CASE:
    Every major API implements these: GitHub API returns ETags on every
    response. Google APIs support ?fields= for partial responses.
    Stripe enforces HTTPS-only via HSTS. Cloudflare terminates TLS and
    applies security headers globally. FastAPI + Pydantic is the industry
    standard for Python input validation.

COMMON MISTAKES:
    - CORS with Access-Control-Allow-Origin: * for credentialed requests
      (cookies/auth headers) — browsers block this, but it signals you
      don't understand CORS.
    - Trusting Content-Type header without re-validating body structure.
    - Returning stack traces in production error responses.
    - Setting no Cache-Control on sensitive endpoints (browsers may cache).
    - SSRF: fetching user-supplied URLs without IP range validation.
    - Mass assignment: writing all request body fields to DB model directly.
    - Skipping ETag on frequently-read, rarely-changed resources.
"""

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional, Set
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------

# Reference implementation of security headers — apply as middleware in your
# framework (FastAPI middleware, Flask after_request, Django middleware class).

SECURITY_HEADERS: Dict[str, str] = {
    # Force HTTPS for 1 year. includeSubDomains covers all subdomains.
    # preload: apply to submit to browser preload lists (permanent — test first).
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",

    # Prevent browsers from MIME-sniffing — serve JS as text/javascript only,
    # never guess content type from file content (blocks polyglot attacks).
    "X-Content-Type-Options": "nosniff",

    # Prevent your page from being embedded in iframes (clickjacking).
    # DENY: no iframes ever. SAMEORIGIN: only from your own domain.
    "X-Frame-Options": "DENY",

    # Content Security Policy: strict mode.
    # default-src 'none': block everything by default.
    # script-src 'self': only scripts from your own origin.
    # APIs that return JSON only (no HTML) should still set CSP — defense in depth.
    "Content-Security-Policy": (
        "default-src 'none'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    ),

    # Set to 0 to disable old IE XSS filter — it caused more problems than
    # it solved (filter bypass attacks). Rely on CSP instead.
    "X-XSS-Protection": "0",

    # Referrer policy: don't leak URL path to third parties.
    "Referrer-Policy": "strict-origin-when-cross-origin",

    # Permissions policy: disable browser features you don't need.
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


def apply_security_headers(response_headers: Dict[str, str]) -> Dict[str, str]:
    """
    Apply all security headers to response.

    In FastAPI:
        @app.middleware("http")
        async def add_security_headers(request, call_next):
            response = await call_next(request)
            for k, v in SECURITY_HEADERS.items():
                response.headers[k] = v
            return response
    """
    headers = dict(response_headers)
    headers.update(SECURITY_HEADERS)
    return headers


# ---------------------------------------------------------------------------
# CORS configuration — restrict allowed origins
# ---------------------------------------------------------------------------

class CORSConfig:
    """
    CORS (Cross-Origin Resource Sharing) controls which origins can call
    your API from a browser.

    CRITICAL RULES:
        1. Never use Access-Control-Allow-Origin: * with credentialed
           requests (cookies, Authorization header). Browsers block it.
        2. Explicitly allowlist known origins — don't echo back the
           Origin header blindly (defeats CORS entirely).
        3. Cache preflight responses (max_age) to reduce OPTIONS requests.
        4. Public APIs (no auth): * is fine. Auth APIs: strict origin list.

    HOW CORS WORKS:
        Browser sends preflight OPTIONS request for cross-origin requests
        with non-simple methods/headers. Server responds with allowed
        origins/methods/headers. Browser then sends actual request.
    """

    def __init__(self, allowed_origins: FrozenSet[str], allow_credentials: bool = True):
        self.allowed_origins = allowed_origins
        self.allow_credentials = allow_credentials
        # Cache preflight for 10 minutes (reduces OPTIONS round trips)
        self.max_age = 600

    def get_cors_headers(self, request_origin: Optional[str]) -> Dict[str, str]:
        """
        Return CORS headers for a given Origin header value.
        Returns empty dict if origin not allowed (browser will block).
        """
        if not request_origin:
            return {}  # Same-origin request — no CORS headers needed

        if request_origin not in self.allowed_origins:
            # Do NOT echo back the origin — just omit the header.
            # Browser will block the request.
            return {}

        headers = {
            # Only allow the specific requesting origin — not *
            "Access-Control-Allow-Origin": request_origin,
            "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type, Idempotency-Key",
            "Access-Control-Max-Age": str(self.max_age),
            # Vary: tells caches this response varies by Origin
            "Vary": "Origin",
        }

        if self.allow_credentials:
            # Required for cookies/auth headers — CANNOT be used with origin: *
            headers["Access-Control-Allow-Credentials"] = "true"

        return headers


# ---------------------------------------------------------------------------
# Input validation with Pydantic-style patterns
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """Raised when input fails validation. Caught at API boundary."""
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


@dataclass
class CreateUserInput:
    """
    Input model for POST /users.

    WHY EXPLICIT INPUT MODELS:
        Never pass request.json directly to your ORM — this is mass
        assignment and lets users set fields like is_admin=True.
        Define exactly what fields are accepted and their constraints.
        Reject unknown fields (extra=forbid in Pydantic).

    VALIDATION LAYERS:
        1. Type validation (is this a string? is this an integer?)
        2. Format validation (valid email? valid UUID?)
        3. Business rules (age >= 18? country in allowed list?)
        4. Sanitization (strip whitespace, normalize email to lowercase)
    """
    email: str
    name: str
    age: Optional[int]
    role: str = "viewer"  # Default — client cannot set role=admin

    # EXPLICITLY NOT ACCEPTED (even if client sends them):
    # is_admin, internal_notes, stripe_customer_id, created_at

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CreateUserInput":
        """
        Parse and validate input. Reject unknown fields.
        In production use Pydantic: class CreateUserInput(BaseModel): ...
        with model_config = ConfigDict(extra='forbid').
        """
        # Only extract known fields — unknown fields are silently dropped
        # (Pydantic with extra='forbid' raises ValidationError on unknowns)
        allowed_fields = {"email", "name", "age", "role"}
        unknown = set(data.keys()) - allowed_fields
        if unknown:
            raise ValidationError("body", f"Unknown fields: {unknown}")

        email = data.get("email", "")
        name = data.get("name", "")
        age = data.get("age")

        # Validate email format
        if not cls._valid_email(email):
            raise ValidationError("email", "Must be a valid email address")

        # Normalize — always lowercase
        email = email.lower().strip()

        # Validate name
        if not name or len(name.strip()) < 2:
            raise ValidationError("name", "Must be at least 2 characters")
        if len(name) > 100:
            raise ValidationError("name", "Must be at most 100 characters")

        # Validate age if provided
        if age is not None:
            if not isinstance(age, int):
                raise ValidationError("age", "Must be an integer")
            if age < 13 or age > 150:
                raise ValidationError("age", "Must be between 13 and 150")

        # Validate role — only allow safe values (prevent privilege escalation)
        allowed_roles = {"viewer", "editor"}  # NOT admin — that requires separate flow
        if data.get("role", "viewer") not in allowed_roles:
            raise ValidationError("role", f"Must be one of: {allowed_roles}")

        return cls(
            email=email,
            name=name.strip(),
            age=age,
            role=data.get("role", "viewer"),
        )

    @staticmethod
    def _valid_email(email: str) -> bool:
        """Simple email format check — use email-validator library in production."""
        pattern = r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email)) and len(email) <= 254


# ---------------------------------------------------------------------------
# Mass assignment protection
# ---------------------------------------------------------------------------

class UserModel:
    """
    Simulates a DB model.

    MASS ASSIGNMENT ATTACK:
        POST /users {"name": "Alice", "is_admin": true, "balance": 99999}
        If you blindly do: user.update(**request.json), the attacker
        just made themselves an admin and gave themselves $1000.

    THE FIX:
        Explicit allowlists for each operation (create, update).
        Never pass request body dict directly to ORM update.
        Pydantic models + SQLAlchemy ORM prevents this by design.
    """

    # Fields that clients can set on create
    WRITABLE_ON_CREATE: FrozenSet[str] = frozenset({"email", "name", "age", "role"})

    # Fields that clients can update (subset — can't change email after create)
    WRITABLE_ON_UPDATE: FrozenSet[str] = frozenset({"name", "age"})

    # Fields that are NEVER client-writable:
    #   is_admin, is_verified, stripe_customer_id, password_hash,
    #   created_at, internal_score, plan_override

    def __init__(self, **kwargs):
        self.id = "user_123"
        self.email = kwargs.get("email")
        self.name = kwargs.get("name")
        self.age = kwargs.get("age")
        self.role = kwargs.get("role", "viewer")
        self.is_admin = False          # Never set from request
        self.is_verified = False       # Only set by email verification flow
        self.stripe_customer_id = None # Only set by payment service

    def safe_update(self, data: Dict[str, Any]) -> List[str]:
        """
        Apply only whitelisted fields from client data.
        Returns list of fields actually updated.
        """
        updated = []
        for field in self.WRITABLE_ON_UPDATE:
            if field in data:
                setattr(self, field, data[field])
                updated.append(field)
        # Unknown fields in data are silently ignored (or raise in strict mode)
        return updated


# ---------------------------------------------------------------------------
# SQL injection prevention patterns
# ---------------------------------------------------------------------------

class SQLInjectionExamples:
    """
    SQL injection: the #1 vulnerability in web applications for 20+ years.

    VULNERABLE: String formatting/concatenation
        query = f"SELECT * FROM users WHERE email = '{email}'"
        email = "' OR '1'='1"  → dumps entire users table
        email = "'; DROP TABLE users; --"  → destroys data

    SAFE: Parameterized queries (ALWAYS)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        The driver sends query and parameters separately — DB never
        interprets parameters as SQL code.

    ORM PREVENTION:
        SQLAlchemy, Django ORM, Prisma always parameterize.
        Only vulnerable if you use text() or raw() with f-strings.
    """

    @staticmethod
    def vulnerable_example(email: str) -> str:
        """NEVER do this. Shown only to illustrate the attack."""
        # An attacker sends: email = "'; DROP TABLE users; --"
        # This executes DROP TABLE users as SQL!
        return f"SELECT * FROM users WHERE email = '{email}'"  # DANGEROUS

    @staticmethod
    def safe_parameterized(email: str) -> tuple:
        """
        Correct approach: parameterized query.
        The ? / %s / :param is replaced by the DB driver, not by string
        formatting — the value is NEVER interpreted as SQL.
        """
        query = "SELECT * FROM users WHERE email = %s"
        params = (email,)
        # cursor.execute(query, params)  ← DB driver handles escaping
        return query, params

    @staticmethod
    def safe_sqlalchemy_example(email: str) -> str:
        """SQLAlchemy ORM — always safe by design."""
        # User.query.filter_by(email=email).first()
        # Translates to: SELECT * FROM users WHERE email = ? with param
        return f"User.query.filter_by(email={email!r}).first()  # Safe — ORM parameterizes"


# ---------------------------------------------------------------------------
# SSRF (Server-Side Request Forgery) prevention
# ---------------------------------------------------------------------------

class SSRFProtection:
    """
    SSRF: User provides a URL, your server fetches it.
    Attacker provides: http://169.254.169.254/latest/meta-data/iam/
    Your server (on EC2) fetches it → returns AWS credentials.
    Attacker now has full AWS access.

    Also targets: Redis (localhost:6379), Elasticsearch (9200),
    internal services (10.0.0.x), admin panels (192.168.x.x).

    DEFENSE:
        1. Allowlist permitted domains (only fetch from known CDNs).
        2. Block all private/reserved IP ranges after DNS resolution.
        3. Disable redirects (redirect could go to private IP).
        4. Set short timeouts.
        5. Run in network-isolated container if fetching user URLs.
    """

    # Private/reserved IP ranges to block
    BLOCKED_NETWORKS = [
        ipaddress.ip_network("10.0.0.0/8"),       # Private class A
        ipaddress.ip_network("172.16.0.0/12"),     # Private class B
        ipaddress.ip_network("192.168.0.0/16"),    # Private class C
        ipaddress.ip_network("127.0.0.0/8"),       # Loopback
        ipaddress.ip_network("169.254.0.0/16"),    # Link-local (AWS metadata!)
        ipaddress.ip_network("::1/128"),           # IPv6 loopback
        ipaddress.ip_network("fc00::/7"),          # IPv6 private
    ]

    # Allowlist of trusted domains (if applicable to your use case)
    ALLOWED_DOMAINS: FrozenSet[str] = frozenset({
        "api.trusted-partner.com",
        "cdn.yourapp.com",
        "webhooks.stripe.com",
    })

    @classmethod
    def validate_url(cls, url: str, use_allowlist: bool = False) -> str:
        """
        Validate a user-supplied URL before fetching.

        Args:
            url: URL provided by user/client.
            use_allowlist: If True, only permit ALLOWED_DOMAINS.

        Returns:
            Validated URL (may be same as input).

        Raises:
            ValueError: If URL is not safe to fetch.
        """
        parsed = urlparse(url)

        # Only allow HTTPS — never HTTP (plaintext) or file:// ftp:// etc.
        if parsed.scheme not in ("https",):
            raise ValueError(f"Only HTTPS URLs allowed, got: {parsed.scheme}://")

        hostname = parsed.hostname
        if not hostname:
            raise ValueError("URL must have a valid hostname")

        # Allowlist check (strictest protection)
        if use_allowlist and hostname not in cls.ALLOWED_DOMAINS:
            raise ValueError(f"Hostname {hostname!r} not in allowed domains")

        # Check if hostname is a raw IP (immediate block)
        try:
            ip = ipaddress.ip_address(hostname)
            cls._block_if_private(ip, hostname)
        except ValueError:
            # Not an IP — DNS name. In production: resolve DNS and check the
            # resolved IP too (DNS rebinding attack prevention).
            # ip = socket.gethostbyname(hostname) → check resolved IP
            pass

        return url

    @classmethod
    def _block_if_private(cls, ip: ipaddress.IPv4Address, hostname: str) -> None:
        """Block if IP is in any private/reserved range."""
        for network in cls.BLOCKED_NETWORKS:
            try:
                if ip in network:
                    raise ValueError(
                        f"URL resolves to private/reserved IP {ip} — "
                        f"SSRF protection blocked request"
                    )
            except TypeError:
                continue  # Mixed IPv4/IPv6 comparison


# ---------------------------------------------------------------------------
# ETag for conditional GET
# ---------------------------------------------------------------------------

class ETagCache:
    """
    ETags enable 304 Not Modified responses — no body sent, massive bandwidth savings.

    FLOW:
        First request:
            GET /users/123
            Response: 200, ETag: "abc123", body: {user data}

        Subsequent request:
            GET /users/123
            Request header: If-None-Match: "abc123"
            Response: 304 Not Modified (no body! client uses cached copy)

    ETAG GENERATION:
        Hash the response body (MD5 or SHA256 of JSON).
        If resource hasn't changed, same JSON → same hash → 304.
        Use weak ETags (W/"...") for semantic equivalence (gzip variants).
        Use strong ETags for exact byte equivalence.

    LAST-MODIFIED alternative:
        Last-Modified: Wed, 21 Oct 2025 07:28:00 GMT
        Client sends: If-Modified-Since: Wed, 21 Oct 2025 07:28:00 GMT
        ETags are more precise (same timestamp, different content possible).
    """

    @staticmethod
    def generate_etag(body: bytes) -> str:
        """
        Generate strong ETag from response body hash.
        Quoted string as required by RFC 7232.
        """
        digest = hashlib.sha256(body).hexdigest()[:16]  # 16 hex chars is plenty
        return f'"{digest}"'

    @staticmethod
    def check_conditional(request_if_none_match: Optional[str],
                          current_etag: str) -> bool:
        """
        Return True if client has current version (should send 304).

        In FastAPI:
            if ETagCache.check_conditional(request.headers.get("if-none-match"), etag):
                return Response(status_code=304, headers={"ETag": etag})
        """
        if not request_if_none_match:
            return False  # No condition — always return full response
        # Handle multiple ETags in If-None-Match: "abc", "def"
        client_etags = [e.strip() for e in request_if_none_match.split(",")]
        return current_etag in client_etags or "*" in client_etags


# ---------------------------------------------------------------------------
# Cache-Control headers
# ---------------------------------------------------------------------------

def cache_control_for_resource(resource_type: str) -> str:
    """
    Cache-Control header values for different resource types.

    DIRECTIVES:
        private:      Only browser can cache (not CDN/proxy) — for user-specific data.
        public:       CDN and browser can cache — for shared resources.
        no-store:     Never cache (sensitive data — 2FA codes, bank balances).
        no-cache:     Cache but always revalidate with server (conditional GET).
        max-age=N:    Cache for N seconds.
        s-maxage=N:   CDN cache duration (overrides max-age for shared caches).
        must-revalidate: After max-age, must revalidate before serving stale.
        stale-while-revalidate=N: Serve stale while fetching fresh in background.
    """
    policies = {
        # User profile: user-specific, cache in browser only for 5 minutes
        "user_profile": "private, max-age=300, must-revalidate",

        # Public product catalog: CDN caches for 10 minutes, browser for 5
        "product_catalog": "public, max-age=300, s-maxage=600, stale-while-revalidate=60",

        # Authentication tokens, passwords, financial data — NEVER cache
        "sensitive": "no-store, no-cache",

        # Static API docs: cache for 1 day
        "api_documentation": "public, max-age=86400, immutable",

        # Health check endpoint: don't cache
        "health_check": "no-store",

        # Paginated list: private, short TTL (data changes frequently)
        "paginated_list": "private, max-age=60",
    }
    return policies.get(resource_type, "private, no-cache")


# ---------------------------------------------------------------------------
# Partial responses (?fields=)
# ---------------------------------------------------------------------------

class PartialResponseFilter:
    """
    Allow clients to request only specific fields — reduces payload size.
    Used by Google APIs, GitHub API, Facebook Graph API.

    CLIENT USAGE:
        GET /users/123?fields=id,name,email
        GET /orders?fields=id,total,status,items.id,items.price

    BENEFITS:
        - Mobile clients: only fetch what they display (saves bandwidth/battery)
        - Reduces JSON parsing cost
        - Hides sensitive fields clients don't need
        - Easier to version (add new fields without breaking clients)

    IMPLEMENTATION:
        Parse ?fields= query param → filter response dict before serializing.
        For nested fields (items.id): use dot notation and recursive filtering.
    """

    @staticmethod
    def filter_fields(data: Dict[str, Any],
                      fields: Optional[str]) -> Dict[str, Any]:
        """
        Filter response to requested fields only.

        Args:
            data: Full response dict.
            fields: Comma-separated field names from ?fields= query param.
                    Supports dot notation for nested: "items.id,items.price"
        """
        if not fields:
            return data  # No filter — return full response

        requested = {f.strip() for f in fields.split(",")}
        return PartialResponseFilter._apply_filter(data, requested)

    @staticmethod
    def _apply_filter(data: Dict[str, Any],
                       fields: Set[str]) -> Dict[str, Any]:
        """Recursively filter dict to requested fields."""
        result = {}
        # Separate top-level fields from nested (items.id → items prefix)
        top_level = {f.split(".")[0] for f in fields}
        nested = {f.split(".")[0]: set() for f in fields if "." in f}
        for f in fields:
            if "." in f:
                parent, child = f.split(".", 1)
                nested[parent].add(child)

        for key in top_level:
            if key not in data:
                continue
            value = data[key]
            if key in nested and isinstance(value, dict):
                # Recursively filter nested object
                result[key] = PartialResponseFilter._apply_filter(
                    value, nested[key]
                )
            elif key in nested and isinstance(value, list):
                # Filter each item in list
                result[key] = [
                    PartialResponseFilter._apply_filter(item, nested[key])
                    if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value

        return result


# ---------------------------------------------------------------------------
# Compression
# ---------------------------------------------------------------------------

def compression_note() -> str:
    """
    Response compression: gzip reduces JSON payloads 60-80%.

    IMPLEMENTATION (FastAPI/Starlette):
        from starlette.middleware.gzip import GZipMiddleware
        app.add_middleware(GZipMiddleware, minimum_size=1000)

    CLIENT SIGNALS:
        Request header: Accept-Encoding: gzip, deflate, br
        Response header: Content-Encoding: gzip
        Brotli (br) compresses better than gzip — use for static assets.

    WHAT TO COMPRESS:
        JSON responses (60-80% savings), HTML, CSS, JS.
        NEVER compress: already-compressed formats (JPEG, PNG, PDF, .gz).

    HTTP/2:
        Enable on nginx: listen 443 ssl http2;
        Multiplexing: multiple requests over single TCP connection.
        Header compression (HPACK): repeated headers compressed across requests.
        Server Push: push CSS/JS before browser requests it.
    """
    return "See nginx/Caddy config for HTTP/2 + gzip setup"


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("API SECURITY & PERFORMANCE DEMO")
    print("=" * 60)

    # 1. Security headers
    print("\n--- SECURITY HEADERS ---")
    response_headers = {"Content-Type": "application/json"}
    secure_headers = apply_security_headers(response_headers)
    for k, v in secure_headers.items():
        print(f"  {k}: {v[:60]}{'...' if len(v) > 60 else ''}")

    # 2. CORS
    print("\n--- CORS ---")
    cors = CORSConfig(
        allowed_origins=frozenset({"https://app.mycompany.com", "https://admin.mycompany.com"}),
        allow_credentials=True,
    )
    cors_headers = cors.get_cors_headers("https://app.mycompany.com")
    print(f"  Access-Control-Allow-Origin: {cors_headers.get('Access-Control-Allow-Origin')}")
    blocked = cors.get_cors_headers("https://evil.com")
    print(f"  Evil origin blocked: {not blocked}")

    # 3. Input validation
    print("\n--- INPUT VALIDATION ---")
    try:
        valid = CreateUserInput.from_dict({
            "email": "Alice@Example.COM",
            "name": "Alice Smith",
            "age": 30,
        })
        print(f"  Valid: email={valid.email}, role={valid.role}")

        # Mass assignment attempt
        CreateUserInput.from_dict({
            "email": "hacker@evil.com",
            "name": "Hacker",
            "is_admin": True,  # Blocked — unknown field
        })
    except ValidationError as e:
        print(f"  Blocked mass assignment: {e}")

    # 4. SSRF
    print("\n--- SSRF PROTECTION ---")
    for url in [
        "https://api.trusted-partner.com/data",
        "http://169.254.169.254/latest/meta-data/",
        "https://10.0.0.1/admin",
    ]:
        try:
            SSRFProtection.validate_url(url)
            print(f"  ALLOWED: {url}")
        except ValueError as e:
            print(f"  BLOCKED: {url[:50]} — {e}")

    # 5. ETags
    print("\n--- ETAG CONDITIONAL GET ---")
    body = json.dumps({"id": "123", "name": "Alice"}).encode()
    etag = ETagCache.generate_etag(body)
    print(f"  ETag: {etag}")
    is_304 = ETagCache.check_conditional(etag, etag)  # Client has same
    print(f"  Client has same version → 304: {is_304}")

    # 6. Partial responses
    print("\n--- PARTIAL RESPONSES ---")
    full_user = {
        "id": "123", "name": "Alice", "email": "alice@ex.com",
        "internal_score": 0.95, "stripe_id": "cus_xxx",
        "address": {"city": "NYC", "zip": "10001"},
    }
    partial = PartialResponseFilter.filter_fields(
        full_user, "id,name,email,address.city"
    )
    print(f"  Full fields: {list(full_user.keys())}")
    print(f"  Partial fields: {list(partial.keys())}, address={partial.get('address')}")

    # 7. Cache-Control
    print("\n--- CACHE-CONTROL ---")
    for rt in ["user_profile", "product_catalog", "sensitive"]:
        print(f"  {rt}: {cache_control_for_resource(rt)}")


if __name__ == "__main__":
    main()
