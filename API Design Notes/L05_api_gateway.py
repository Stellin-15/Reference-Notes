# =============================================================================
# WHAT: API Gateway Patterns — Kong, AWS API Gateway, NGINX, BFF
# WHY:  An API gateway is the single entry point for all client traffic.
#       It centralizes cross-cutting concerns (auth, rate limiting, routing,
#       TLS termination, observability) so individual services don't repeat them.
#       Without a gateway every microservice re-implements auth, logging, and
#       rate limiting — inconsistently.
# LEVEL: Intermediate → Advanced
# =============================================================================
#
# CONCEPT OVERVIEW
# ----------------
# Gateway patterns:
#   Edge Gateway    — single gateway for all clients (mobile, web, third-party)
#   BFF             — Backend for Frontend: dedicated gateway per client type
#   Micro-gateway   — lightweight gateway co-located with each service (sidecar)
#
# Core responsibilities:
#   Routing          — match URL/header/method → upstream service
#   Auth             — validate JWT / API key before hitting services
#   Rate limiting    — per-client, per-route quotas
#   TLS termination  — accept HTTPS, forward HTTP internally
#   Observability    — access logs, metrics, distributed tracing
#   Transformation   — rewrite request/response headers and bodies
#   Circuit breaking — stop forwarding to a failing upstream
#
# PRODUCTION USE CASE
# -------------------
# A fintech platform puts Kong in front of: Payments API, KYC API, Accounts API.
# Kong validates JWTs, enforces rate limits, logs every request to Datadog,
# and does mTLS to each upstream. The mobile BFF aggregates 3 service calls
# into one response. On AWS, API Gateway handles 1M+ requests/day with Lambda
# backends — zero servers to manage.
#
# COMMON MISTAKES
# ---------------
# 1. Putting business logic in the gateway (routing decisions based on DB state)
# 2. Not using mTLS between gateway and services → internal traffic unencrypted
# 3. Single gateway as a monolith → becomes a bottleneck and deployment choke point
# 4. Rate limiting at the application layer instead of at the gateway
# 5. Forgetting to propagate trace headers (X-Request-Id) through the gateway
# 6. Over-broad CORS config (*) that lets any origin call your API
# =============================================================================

# ---------------------------------------------------------------------------
# Standard library
# ---------------------------------------------------------------------------
import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urlencode

# ---------------------------------------------------------------------------
# Third-party — pip install fastapi uvicorn httpx pyjwt boto3
# ---------------------------------------------------------------------------
import httpx                        # Async HTTP client for request forwarding
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import jwt                          # pip install pyjwt[cryptography]

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# =============================================================================
# PART 1 — GATEWAY PATTERN COMPARISON
# =============================================================================

GATEWAY_PATTERNS = {
    "Edge Gateway": {
        "description": "One gateway in front of all services, all client types",
        "pros": [
            "Simple topology — one place to manage auth, rate limits, routing",
            "Fewer moving parts in small teams",
        ],
        "cons": [
            "One-size-fits-all response shapes don't suit mobile vs web",
            "Becomes a bottleneck if not horizontally scaled",
            "All teams wait on one team to change the gateway",
        ],
        "tools": ["Kong", "AWS API Gateway", "NGINX", "Envoy", "Traefik"],
    },
    "BFF (Backend for Frontend)": {
        "description": "Dedicated gateway per client type (mobile-bff, web-bff, partner-bff)",
        "pros": [
            "Mobile BFF returns minimal payloads optimized for bandwidth",
            "Web BFF aggregates multiple service calls into one response",
            "Each BFF team moves independently",
        ],
        "cons": [
            "More services to deploy and maintain",
            "Risk of duplicating gateway logic across BFFs",
        ],
        "tools": ["FastAPI BFF", "GraphQL gateway", "Next.js API routes"],
    },
    "Micro-gateway / Sidecar": {
        "description": "Lightweight proxy co-located with each service (service mesh)",
        "pros": [
            "mTLS between all services automatically",
            "Per-service routing and observability without code changes",
        ],
        "cons": [
            "Adds latency (extra hop per call)",
            "Operational complexity of managing the mesh (Istio is famously complex)",
        ],
        "tools": ["Envoy (Istio/Linkerd sidecar)", "NGINX Unit"],
    },
}


# =============================================================================
# PART 2 — KONG DECLARATIVE CONFIGURATION (deck)
# =============================================================================
# Kong can be configured via the Admin API or declaratively with deck.
# Declarative config is GitOps-friendly — version controlled and auditable.
# =============================================================================

# CLI commands for Kong administration
CMD_KONG_VALIDATE = "deck file validate kong.yaml"
CMD_KONG_DIFF = "deck gateway diff --kong-addr http://localhost:8001"
CMD_KONG_SYNC = "deck gateway sync kong.yaml --kong-addr http://localhost:8001"
CMD_KONG_DUMP = "deck gateway dump --kong-addr http://localhost:8001 -o kong-backup.yaml"

# Complete Kong declarative config (deck format)
KONG_DECLARATIVE_CONFIG = {
    "_format_version": "3.0",        # deck format version, not Kong version
    "_transform": True,               # Let deck resolve $refs

    "services": [
        {
            "name": "orders-service",
            "url": "http://orders-svc:8080",   # Upstream service URL (internal DNS)
            "connect_timeout": 5000,            # ms to establish TCP connection
            "read_timeout": 30000,              # ms to wait for upstream response
            "write_timeout": 30000,             # ms to wait for upstream to accept body
            "retries": 2,                       # Retry count on upstream failure
        },
        {
            "name": "users-service",
            "url": "http://users-svc:8080",
            "connect_timeout": 3000,
            "read_timeout": 10000,
            "write_timeout": 10000,
        },
    ],

    "routes": [
        {
            "name": "orders-route",
            "service": {"name": "orders-service"},
            "paths": ["/v2/orders"],            # Incoming path to match
            "methods": ["GET", "POST"],
            "strip_path": False,                # Keep /v2 when forwarding
            "preserve_host": False,             # Don't forward Host header
        },
        {
            "name": "users-route",
            "service": {"name": "users-service"},
            "paths": ["/v2/users"],
            "methods": ["GET", "PUT", "PATCH"],
        },
    ],

    "plugins": [
        # ── JWT validation ────────────────────────────────────────────────────
        {
            "name": "jwt",
            "config": {
                "key_claim_name": "kid",         # JWT header field that identifies the key
                "claims_to_verify": ["exp"],      # Verify expiration
                "maximum_expiration": 3600,       # Reject tokens valid for > 1 hour
                "header_names": ["Authorization"],
                "uri_param_names": [],            # Don't accept JWT in query params
            },
        },
        # ── Rate limiting ─────────────────────────────────────────────────────
        {
            "name": "rate-limiting",
            "route": {"name": "orders-route"},   # Apply only to orders endpoint
            "config": {
                "minute": 100,                    # Max 100 requests per minute per consumer
                "hour": 1000,
                "policy": "redis",                # Store counters in Redis (required for multi-node)
                "redis": {
                    "host": "redis",
                    "port": 6379,
                    "database": 0,
                },
                "limit_by": "consumer",           # consumer | ip | credential
                "fault_tolerant": True,           # Allow requests if Redis is down
            },
        },
        # ── CORS ──────────────────────────────────────────────────────────────
        {
            "name": "cors",
            "config": {
                "origins": [
                    "https://app.example.com",
                    "https://admin.example.com",
                ],
                # DO NOT use "*" in production — it allows any origin
                "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                "headers": ["Authorization", "Content-Type", "X-Request-Id"],
                "exposed_headers": ["X-Rate-Limit-Remaining"],
                "credentials": True,              # Allow cookies with CORS
                "max_age": 3600,                  # Preflight cache duration
            },
        },
        # ── Request transformer ───────────────────────────────────────────────
        {
            "name": "request-transformer",
            "config": {
                # Add headers to every forwarded request
                "add": {
                    "headers": [
                        "X-Gateway-Version:kong-3.6",
                        "X-Internal:true",
                    ],
                },
                # Remove headers you don't want upstream to see
                "remove": {
                    "headers": ["Authorization"],  # Strip auth; gateway already validated it
                },
            },
        },
        # ── Proxy cache ───────────────────────────────────────────────────────
        {
            "name": "proxy-cache",
            "config": {
                "response_code": [200, 301, 404],    # Cache these status codes
                "request_method": ["GET", "HEAD"],   # Only cache idempotent methods
                "content_type": ["application/json"],
                "cache_ttl": 300,                    # Cache for 5 minutes
                "strategy": "memory",                # memory | redis
            },
        },
    ],

    "consumers": [
        {
            "username": "mobile-app",
            "tags": ["client:mobile"],
        },
        {
            "username": "partner-api",
            "tags": ["client:partner", "tier:premium"],
        },
    ],
}


# =============================================================================
# PART 3 — AWS API GATEWAY (HTTP API — cheaper, lower latency than REST API)
# =============================================================================
# Three types:
#   REST API     — full feature set (usage plans, API keys, request validation)
#   HTTP API     — 70% cheaper, lower latency; missing some REST API features
#   WebSocket    — persistent connections with route expressions
# =============================================================================

CMD_SAM_DEPLOY = "sam build && sam deploy --guided"
CMD_CDK_SYNTH = "cdk synth"

# CloudFormation / SAM template snippet (shown as Python dict for reference)
AWS_HTTP_API_TEMPLATE: dict[str, Any] = {
    "Type": "AWS::Serverless::HttpApi",
    "Properties": {
        "StageName": "prod",
        # CORS at the API Gateway layer — before Lambda is invoked
        "CorsConfiguration": {
            "AllowOrigins": ["https://app.example.com"],
            "AllowHeaders": ["Authorization", "Content-Type"],
            "AllowMethods": ["GET", "POST", "OPTIONS"],
            "MaxAge": 600,
        },
        # Custom domain
        "Domain": {
            "DomainName": "api.example.com",
            "CertificateArn": "arn:aws:acm:us-east-1:123456789012:certificate/abc",
        },
        # JWT authorizer — validates tokens WITHOUT a Lambda
        "Auth": {
            "DefaultAuthorizer": "JwtAuth",
            "Authorizers": {
                "JwtAuth": {
                    "JwtConfiguration": {
                        "issuer": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_xyz",
                        "audience": ["https://api.example.com"],
                    },
                    "IdentitySource": "$request.header.Authorization",
                }
            },
        },
    },
}

# Lambda proxy integration event shape (what API Gateway sends to Lambda)
LAMBDA_PROXY_EVENT_EXAMPLE = {
    "version": "2.0",                   # Payload format version
    "routeKey": "POST /v2/orders",
    "rawPath": "/v2/orders",
    "rawQueryString": "dry_run=true",
    "headers": {
        "content-type": "application/json",
        "authorization": "Bearer eyJ...",
        "x-forwarded-for": "1.2.3.4",  # Original client IP (NOT the gateway IP)
    },
    "requestContext": {
        "accountId": "123456789012",
        "apiId": "abc123",
        "domainName": "api.example.com",
        "http": {
            "method": "POST",
            "path": "/v2/orders",
            "sourceIp": "1.2.3.4",
            "userAgent": "Mozilla/5.0",
        },
        "requestId": "req-abc-123",
        "routeKey": "POST /v2/orders",
        "stage": "prod",
        "time": "01/Jan/2024:00:00:00 +0000",
        "timeEpoch": 1704067200000,
    },
    "body": '{"customer_id": 42}',
    "isBase64Encoded": False,
}

# Lambda response format (what Lambda returns to API Gateway)
LAMBDA_PROXY_RESPONSE_EXAMPLE = {
    "statusCode": 201,
    "headers": {
        "Content-Type": "application/json",
        "Location": "/v2/orders/ORD-001",
    },
    "body": json.dumps({"order_id": "ORD-001", "status": "pending"}),
    "isBase64Encoded": False,
}


def lambda_handler(event: dict, context: Any) -> dict:
    """
    Example Lambda function serving as an HTTP API backend.
    'event' is the proxy integration payload shown above.
    'context' has: function_name, aws_request_id, memory_limit_in_mb, etc.
    """
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"]

    logger.info(
        "Request %s %s from IP %s",
        method,
        path,
        event["requestContext"]["http"]["sourceIp"],
    )

    if method == "POST" and path == "/v2/orders":
        body = json.loads(event.get("body") or "{}")
        # ... process order ...
        return {
            "statusCode": 201,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"order_id": "ORD-NEW", "status": "pending"}),
        }

    return {
        "statusCode": 404,
        "body": json.dumps({"code": "NOT_FOUND", "message": f"Route {path} not found"}),
    }


# =============================================================================
# PART 4 — CUSTOM LAMBDA AUTHORIZER (API Gateway)
# =============================================================================
# A Lambda authorizer validates credentials before the backend Lambda runs.
# Returns an IAM policy document allowing or denying the request.
# Use for: custom JWT validation, API key lookup in DB, OAuth introspection.
# =============================================================================

def lambda_authorizer_handler(event: dict, context: Any) -> dict:
    """
    TOKEN type authorizer: receives the Authorization header value.
    REQUEST type authorizer: receives the full request (headers, query params).
    Returns an IAM policy (allow/deny) + optional context dict.
    """
    token = event.get("authorizationToken", "").replace("Bearer ", "")
    method_arn = event["methodArn"]  # e.g., "arn:aws:execute-api:..."

    try:
        # Decode and validate JWT
        payload = jwt.decode(
            token,
            key="your-secret-key",        # In prod: fetch from Secrets Manager
            algorithms=["RS256"],
            options={"verify_exp": True},
        )
        principal_id = payload["sub"]
        effect = "Allow"
    except jwt.ExpiredSignatureError:
        effect = "Deny"
        principal_id = "unauthorized"
    except jwt.InvalidTokenError:
        # Raising an exception with message "Unauthorized" returns 401
        raise Exception("Unauthorized")

    return {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": method_arn,
                }
            ],
        },
        # Context is passed to the backend Lambda in event["requestContext"]["authorizer"]
        "context": {
            "user_id": principal_id,
            "scopes": " ".join(payload.get("scope", "").split()) if effect == "Allow" else "",
        },
        "usageIdentifierKey": token,   # For usage plan tracking (REST API only)
    }


# =============================================================================
# PART 5 — PYTHON BFF (BACKEND FOR FRONTEND) IMPLEMENTATION
# =============================================================================
# A BFF aggregates calls to multiple upstream services and returns a
# single, client-optimized response. Written in FastAPI here.
# =============================================================================

# Upstream service URLs (in prod: from env vars or service discovery)
USERS_SERVICE_URL = "http://users-svc:8080"
ORDERS_SERVICE_URL = "http://orders-svc:8080"
CATALOG_SERVICE_URL = "http://catalog-svc:8080"

bff_app = FastAPI(title="Mobile BFF")

# Add gateway-level CORS (BFF handles this for mobile clients)
bff_app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://mobile.example.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@bff_app.middleware("http")
async def propagate_trace_headers(request: Request, call_next: Callable) -> Response:
    """
    Middleware: propagate X-Request-Id through every outgoing upstream call.
    This is critical for distributed tracing — Datadog, Jaeger, Zipkin all
    use this header to correlate spans across services.
    """
    # Generate or carry through the request ID
    request_id = request.headers.get("X-Request-Id") or f"req-{int(time.time())}"

    # Store in request state so route handlers can access it
    request.state.request_id = request_id

    response = await call_next(request)
    # Echo it back so the client can correlate their logs with server logs
    response.headers["X-Request-Id"] = request_id
    return response


@bff_app.get("/mobile/v1/home-feed")
async def mobile_home_feed(
    request: Request,
    authorization: str = Header(...),
) -> dict:
    """
    Mobile home screen: aggregates user profile + recent orders + promotions
    in ONE request instead of 3. Reduces mobile round trips and battery usage.
    """
    headers = {
        "Authorization": authorization,
        "X-Request-Id": request.state.request_id,
        "X-Source": "mobile-bff",              # Identify the caller for upstream logs
    }

    async with httpx.AsyncClient(timeout=5.0) as client:
        # Fire all three upstream calls concurrently with asyncio.gather
        import asyncio
        user_task = client.get(f"{USERS_SERVICE_URL}/v2/me", headers=headers)
        orders_task = client.get(
            f"{ORDERS_SERVICE_URL}/v2/orders",
            headers=headers,
            params={"limit": 3, "status": "active"},  # Mobile only needs 3 active orders
        )
        promo_task = client.get(f"{CATALOG_SERVICE_URL}/v2/promotions", headers=headers)

        # Wait for all three responses concurrently
        user_resp, orders_resp, promo_resp = await asyncio.gather(
            user_task, orders_task, promo_task,
            return_exceptions=True,  # Don't cancel others if one fails
        )

    # Handle partial failures gracefully
    user_data = (
        user_resp.json() if not isinstance(user_resp, Exception) and user_resp.status_code == 200
        else {}
    )
    orders_data = (
        orders_resp.json() if not isinstance(orders_resp, Exception) and orders_resp.status_code == 200
        else []
    )
    promo_data = (
        promo_resp.json() if not isinstance(promo_resp, Exception) and promo_resp.status_code == 200
        else []
    )

    # Return mobile-optimized shape — only fields the mobile UI actually uses
    return {
        "user": {
            "name": user_data.get("name", ""),
            "avatar_url": user_data.get("avatar_url", ""),
        },
        "active_orders": orders_data,
        "promotions": promo_data[:2],  # Mobile only shows 2 promos
        "_meta": {
            "request_id": request.state.request_id,
            "generated_at": int(time.time()),
        },
    }


# =============================================================================
# PART 6 — REQUEST ROUTING AND PATH REWRITING
# =============================================================================
# Gateway rewrites /api/v2/orders → /v2/orders before forwarding.
# Useful when internal services use different path conventions.
# =============================================================================

ROUTING_RULES: list[dict] = [
    {
        "match": {"path_prefix": "/api/v2/orders", "method": "GET"},
        "upstream": "http://orders-svc:8080",
        "rewrite_path": "/v2/orders",   # Strip /api prefix before forwarding
        "add_headers": {"X-Internal": "true"},
        "remove_headers": ["X-Forwarded-For"],  # Strip IP before reaching service
    },
    {
        "match": {"path_prefix": "/api/v2/users", "host": "admin.example.com"},
        "upstream": "http://admin-users-svc:8080",  # Different service for admin host
        "rewrite_path": "/v2/users",
        "require_header": {"X-Admin-Token": None},  # Must have this header
    },
]


async def route_request(
    path: str,
    method: str,
    headers: dict[str, str],
    body: Optional[bytes] = None,
) -> httpx.Response:
    """
    Simple rule-based router. In production: use Kong, NGINX, or Envoy
    rather than implementing your own. This demonstrates the concepts.
    """
    for rule in ROUTING_RULES:
        match = rule["match"]

        # Check path prefix
        if not path.startswith(match["path_prefix"]):
            continue

        # Check method filter if specified
        if "method" in match and method != match["method"]:
            continue

        # Check host filter if specified
        if "host" in match and headers.get("host") != match["host"]:
            continue

        # Rewrite path
        new_path = path.replace(match["path_prefix"], rule["rewrite_path"], 1)
        upstream_url = f"{rule['upstream']}{new_path}"

        # Merge headers: original + gateway additions
        forwarded_headers = {**headers, **rule.get("add_headers", {})}
        for h in rule.get("remove_headers", []):
            forwarded_headers.pop(h, None)

        async with httpx.AsyncClient(timeout=10.0) as client:
            return await client.request(
                method=method,
                url=upstream_url,
                headers=forwarded_headers,
                content=body,
            )

    raise HTTPException(status_code=404, detail=f"No route matched {method} {path}")


# =============================================================================
# PART 7 — CIRCUIT BREAKER AT GATEWAY LAYER
# =============================================================================
# A circuit breaker stops forwarding traffic to a failing upstream,
# allowing it to recover without being hammered by retries.
# States: CLOSED (normal) → OPEN (failing, reject all) → HALF-OPEN (testing)
# =============================================================================

from enum import Enum as PyEnum


class CircuitState(PyEnum):
    CLOSED = "closed"         # Normal operation; all requests forwarded
    OPEN = "open"             # Upstream failing; reject all requests immediately
    HALF_OPEN = "half_open"   # Sending a test request to check recovery


@dataclass
class CircuitBreaker:
    """
    Simple circuit breaker for a single upstream service.
    In production use: circuitbreaker library, or build it into Kong/Envoy.
    """
    name: str
    failure_threshold: int = 5       # Open circuit after this many consecutive failures
    recovery_timeout: float = 30.0   # Seconds to wait before trying HALF_OPEN
    success_threshold: int = 2       # Consecutive successes needed to close from HALF_OPEN

    state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    failure_count: int = field(default=0, init=False)
    success_count: int = field(default=0, init=False)
    last_failure_time: float = field(default=0.0, init=False)

    def call_allowed(self) -> bool:
        """Returns True if the circuit allows this call through."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has elapsed
            if time.monotonic() - self.last_failure_time >= self.recovery_timeout:
                logger.info("Circuit %s: OPEN → HALF_OPEN (trying recovery)", self.name)
                self.state = CircuitState.HALF_OPEN
                return True
            return False  # Still open — reject immediately

        # HALF_OPEN: allow exactly one test request through
        return True

    def record_success(self) -> None:
        """Called when an upstream call succeeds."""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                logger.info("Circuit %s: HALF_OPEN → CLOSED (recovered)", self.name)
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
        else:
            self.failure_count = 0  # Reset consecutive failures on success

    def record_failure(self) -> None:
        """Called when an upstream call fails."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()

        if self.state == CircuitState.HALF_OPEN:
            logger.warning("Circuit %s: HALF_OPEN → OPEN (still failing)", self.name)
            self.state = CircuitState.OPEN
            self.success_count = 0

        elif self.failure_count >= self.failure_threshold:
            logger.warning(
                "Circuit %s: CLOSED → OPEN after %d failures",
                self.name,
                self.failure_count,
            )
            self.state = CircuitState.OPEN


# =============================================================================
# PART 8 — JWT VALIDATION AT THE GATEWAY LAYER
# =============================================================================
# The gateway validates JWTs centrally so individual services don't need to.
# Services trust the gateway and read claims from injected headers.
# =============================================================================

# RS256 public key (in prod: fetched from JWKS endpoint and cached)
JWKS_URL = "https://auth.example.com/.well-known/jwks.json"

async def fetch_jwks(jwks_url: str) -> dict:
    """Fetch and cache JWKS (JSON Web Key Set) from the identity provider."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(jwks_url)
        resp.raise_for_status()
        return resp.json()


def validate_jwt_gateway(
    token: str,
    public_key: str,
    required_audience: str,
    required_issuer: str,
) -> dict:
    """
    Validate a JWT at the gateway layer. Returns decoded claims on success.
    Raises HTTPException on any validation failure.
    """
    try:
        payload = jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],              # Reject HS256 (symmetric — anyone can forge)
            audience=required_audience,        # Reject tokens for other services
            issuer=required_issuer,
            options={
                "verify_exp": True,            # Reject expired tokens
                "verify_iat": True,            # Reject tokens issued in the future
                "require": ["sub", "exp", "iat", "aud", "iss"],
            },
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidAudienceError:
        raise HTTPException(status_code=401, detail="Token audience mismatch")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


# Headers injected by the gateway AFTER JWT validation
# Downstream services read these instead of re-validating the JWT
INJECTED_HEADERS_AFTER_JWT = {
    "X-User-Id": "payload['sub']",           # User's unique identifier
    "X-User-Email": "payload['email']",
    "X-User-Scopes": "' '.join(payload.get('scope', '').split())",
    "X-Auth-Validated": "true",              # Flag: gateway already validated auth
}


# =============================================================================
# PART 9 — NGINX AS API GATEWAY
# =============================================================================
# NGINX config shown as Python string. In production: use nginx.conf files.
# NGINX is simpler than Kong; use it when you don't need plugin ecosystems.
# =============================================================================

NGINX_GATEWAY_CONFIG = """
# /etc/nginx/conf.d/api-gateway.conf

upstream orders_backend {
    least_conn;                        # Route to the server with fewest connections
    server orders-svc-1:8080;
    server orders-svc-2:8080;
    keepalive 32;                      # Keep 32 connections open to upstreams
}

upstream users_backend {
    server users-svc:8080;
    keepalive 16;
}

# Rate limiting zone: 10MB shared memory, 10 requests/second per IP
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

server {
    listen 443 ssl http2;
    server_name api.example.com;

    # TLS termination at the gateway
    ssl_certificate     /etc/ssl/api.example.com.crt;
    ssl_certificate_key /etc/ssl/api.example.com.key;
    ssl_protocols       TLSv1.2 TLSv1.3;  # Disable TLS 1.0 and 1.1
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;

    location /v2/orders {
        # Apply rate limit; allow burst of 20 requests before returning 429
        limit_req zone=api_limit burst=20 nodelay;
        limit_req_status 429;

        # Path rewrite: /v2/orders → /v2/orders (no change here)
        # To strip a prefix: rewrite ^/api(/.*) $1 break;
        proxy_pass http://orders_backend;

        # Forward client IP to upstream
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Host $host;

        # Inject gateway identity header
        proxy_set_header X-Gateway "nginx-1.24";

        # Timeouts for upstream communication
        proxy_connect_timeout 3s;
        proxy_read_timeout 30s;
        proxy_send_timeout 10s;
    }

    location /v2/users {
        limit_req zone=api_limit burst=10 nodelay;
        proxy_pass http://users_backend;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Host $host;
    }

    # Health check endpoint — does NOT proxy to upstream
    location /health {
        access_log off;                # Don't log health checks (noisy)
        return 200 '{"status": "ok"}';
        add_header Content-Type application/json;
    }
}
"""


# =============================================================================
# PART 10 — mTLS BETWEEN GATEWAY AND SERVICES
# =============================================================================
# The internet sees HTTPS from clients to the gateway.
# Internally, the gateway uses mTLS so services verify the gateway's identity
# AND the gateway verifies each service's identity. Stops rogue internal calls.
# =============================================================================

CMD_GENERATE_CA = "openssl genrsa -out ca.key 4096 && openssl req -new -x509 -days 3650 -key ca.key -out ca.crt"
CMD_GENERATE_SERVICE_CERT = (
    "openssl genrsa -out orders-svc.key 2048 && "
    "openssl req -new -key orders-svc.key -out orders-svc.csr && "
    "openssl x509 -req -days 365 -in orders-svc.csr -CA ca.crt -CAkey ca.key -out orders-svc.crt"
)


def create_mtls_client(
    client_cert_path: str,
    client_key_path: str,
    ca_cert_path: str,
) -> httpx.AsyncClient:
    """
    Create an httpx client that presents a client certificate to upstreams.
    The gateway uses this client to call internal services over mTLS.
    """
    return httpx.AsyncClient(
        # Present our certificate to the upstream (client auth)
        cert=(client_cert_path, client_key_path),
        # Verify the upstream's certificate against our internal CA
        verify=ca_cert_path,
        timeout=10.0,
    )


# =============================================================================
# PART 11 — GATEWAY ANTI-PATTERNS
# =============================================================================

GATEWAY_ANTI_PATTERNS = {
    "Business logic in the gateway": (
        "Gateway decides routing based on DB state (e.g., if user is premium, route to "
        "premium-service). This couples the gateway to domain knowledge. Instead: route "
        "uniformly; let the service decide what 'premium' means."
    ),
    "Aggregation that requires transactions": (
        "Gateway calls 3 services and tries to rollback on failure. Gateways don't "
        "participate in distributed transactions. Use a Saga pattern in a service instead."
    ),
    "Fat gateway with team ownership problems": (
        "One team owns the gateway; all other teams open PRs to it for every route change. "
        "Gateway becomes a bottleneck. Solution: self-service config via CRDs (Kubernetes "
        "Ingress) or declarative GitOps (Kong deck)."
    ),
    "Trusting downstream headers": (
        "Service reads X-User-Id header but doesn't verify it came from the gateway. "
        "A compromised service can forge X-User-Id for any other service. "
        "Solution: mTLS between gateway and services so service knows who sent the header."
    ),
    "No circuit breaker": (
        "Upstream is slow → gateway holds connections open → connection pool exhausted "
        "→ gateway itself crashes. Always add a circuit breaker and timeout."
    ),
}


# =============================================================================
# DEMO BLOCK
# =============================================================================
if __name__ == "__main__":
    import uvicorn

    print("API Gateway reference file. BFF server endpoints:")
    print("  Mobile home feed → GET http://localhost:8000/mobile/v1/home-feed")
    print()

    # Show circuit breaker state machine
    cb = CircuitBreaker(name="orders-svc", failure_threshold=3, recovery_timeout=10.0)
    print(f"Circuit breaker initial state: {cb.state.value}")

    for i in range(4):
        cb.record_failure()
        print(f"  After failure {i+1}: {cb.state.value}, call_allowed={cb.call_allowed()}")

    print(f"\nKong sync command:\n  {CMD_KONG_SYNC}")
    print(f"\nAWS Lambda deploy:\n  {CMD_SAM_DEPLOY}")

    uvicorn.run(bff_app, host="0.0.0.0", port=8000)
