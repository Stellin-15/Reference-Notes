# =============================================================================
# WHAT:  Production API design patterns, governance, and a full design checklist
# WHY:   Shipping an API is making a long-term contract with your consumers.
#        Mistakes made at design time (offset pagination, no idempotency keys,
#        no versioning) are extremely expensive to fix after launch.
# LEVEL: Advanced (assumes REST/HTTP fundamentals, some system design background)
# =============================================================================

# CONCEPT OVERVIEW
# ----------------
# This file is a production API design field guide covering:
#   - Idempotency keys for safe mutation retries
#   - Cursor-based pagination (why offset pagination breaks at scale)
#   - Bulk endpoints to reduce round-trips
#   - Async operations (202 + polling / webhooks)
#   - Field selection and sparse fieldsets
#   - Request ID propagation for distributed tracing
#   - HATEOAS and hypermedia (when it helps)
#   - API contract testing (Pact, Dredd)
#   - API governance (Spectral linting, style guides)
#   - Traffic shaping: canary rollouts, feature flags
#   - Deprecation workflow
#   - SDK generation from OpenAPI
#   - Internal vs public API design differences
#   - Full production API design checklist

# PRODUCTION USE CASE
# -------------------
# A B2B SaaS platform with a public API used by hundreds of enterprise customers,
# a partner API for channel integrations, and internal APIs consumed by frontend
# teams. All three have different design constraints.

# COMMON MISTAKES
# ---------------
# 1. Using offset pagination beyond page 1000 — full table scans, unstable pages
# 2. Mutations without idempotency keys — clients can't safely retry on timeout
# 3. 200 OK with {"success": false} in body — use proper HTTP status codes
# 4. No request IDs — impossible to correlate logs across microservices
# 5. Breaking changes in "minor" versions — consumers break silently
# 6. Returning all fields always — mobile clients pay for bandwidth they ignore
# 7. Synchronous long-running operations (>5s) — client timeouts, no progress visibility
# 8. HATEOAS everywhere — over-engineering that few clients actually use

import hashlib
import json
import logging
import time
import uuid
from base64 import b64encode, b64decode
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# SECTION 1 — IDEMPOTENCY KEYS FOR MUTATIONS
# =============================================================================
# WHY: Clients retry on timeout, network errors, and unknown failures.
#      Without idempotency, a retry could create duplicate payments, orders, etc.
#      With an idempotency key, the second call returns the cached result of the first.
#
# RULE: Every state-mutating endpoint (POST, PATCH, DELETE) that could fail
#       mid-flight MUST support Idempotency-Key header.
#
# PATTERN:
#   1. Client generates a UUID and sends it in Idempotency-Key header
#   2. Server checks cache: if key seen before → return cached response
#   3. If not seen: process request → cache response with key
#   4. Cache entry expires after 24 hours (enough to cover all retry windows)

@dataclass
class IdempotentResponse:
    """Cached response for an idempotency key."""
    key: str
    status_code: int
    response_body: Dict[str, Any]
    created_at: float         # Unix timestamp
    expires_at: float         # Unix timestamp (24 hours from creation)
    request_fingerprint: str  # Hash of request body to detect conflicting retries


class IdempotencyKeyStore:
    """
    Stores idempotency key → response mappings.
    Production: backed by Redis with 24-hour TTL.
    Key format: idempotent:{api_key}:{idempotency_key} — scope per API key to prevent
    cross-tenant collisions (two customers might generate the same UUID by chance).
    """
    def __init__(self):
        self._store: Dict[str, IdempotentResponse] = {}  # Redis in production

    def get(self, api_key: str, idempotency_key: str) -> Optional[IdempotentResponse]:
        """Return cached response if key exists and has not expired."""
        store_key = f"{api_key}:{idempotency_key}"
        cached = self._store.get(store_key)
        if cached and time.time() < cached.expires_at:
            return cached
        return None

    def store(
        self,
        api_key: str,
        idempotency_key: str,
        status_code: int,
        body: Dict[str, Any],
        request_fingerprint: str,
        ttl_seconds: int = 86400,  # 24 hours
    ) -> None:
        now = time.time()
        store_key = f"{api_key}:{idempotency_key}"
        self._store[store_key] = IdempotentResponse(
            key=idempotency_key,
            status_code=status_code,
            response_body=body,
            created_at=now,
            expires_at=now + ttl_seconds,
            request_fingerprint=request_fingerprint,
        )


def idempotent_mutation(
    request_body: Dict[str, Any],
    idempotency_key: Optional[str],
    api_key: str,
    store: IdempotencyKeyStore,
    handler: Callable,
) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
    """
    Wraps a mutation handler with idempotency logic.
    Returns (status_code, body, extra_headers).
    """
    headers: Dict[str, str] = {}

    if not idempotency_key:
        # If client didn't send a key, process normally (no dedup guarantee)
        status, body = handler(request_body)
        return status, body, headers

    # Fingerprint the request body to detect conflicting retries
    # (same key, different body = client bug or attack)
    fingerprint = hashlib.sha256(
        json.dumps(request_body, sort_keys=True).encode()
    ).hexdigest()

    cached = store.get(api_key, idempotency_key)
    if cached:
        if cached.request_fingerprint != fingerprint:
            # CONFLICT: same idempotency key but different body
            return 422, {
                "error": {
                    "type": "idempotency_key_reuse",
                    "message": (
                        "This Idempotency-Key was used with a different request body. "
                        "Generate a new key for each distinct operation."
                    ),
                }
            }, {}

        # Cache hit — return the original response, unchanged
        headers["Idempotent-Replayed"] = "true"  # Signal to client it's a replay
        logger.info("Idempotency cache hit for key=%s", idempotency_key)
        return cached.status_code, cached.response_body, headers

    # First time seeing this key — process the request
    status, body = handler(request_body)

    # Only cache successful responses (don't cache validation errors)
    if status < 500:
        store.store(api_key, idempotency_key, status, body, fingerprint)

    return status, body, headers


# =============================================================================
# SECTION 2 — CURSOR-BASED PAGINATION (why offset is broken at scale)
# =============================================================================
# OFFSET PAGINATION problem: SELECT * FROM orders OFFSET 10000 LIMIT 20
#   → Database must scan 10,020 rows to return 20. Slow at large offsets.
#   → Rows inserted during pagination cause items to shift — you miss or duplicate rows.
#   → Not safe for parallel consumption.
#
# CURSOR PAGINATION: encode the position of the last item seen.
#   → Constant-time lookup: WHERE id > :cursor_id LIMIT 20
#   → Stable: new rows don't affect the cursor position
#   → Opaque: cursor format is an implementation detail (can change without API break)

@dataclass
class Page:
    """Generic paginated response wrapper."""
    data: List[Dict[str, Any]]
    has_more: bool
    next_cursor: Optional[str]   # None means no more pages
    prev_cursor: Optional[str]   # For bidirectional pagination


def encode_cursor(row_id: str, created_at: str) -> str:
    """
    Encode cursor as opaque base64 string.
    Opaque = clients treat it as a black box, don't construct it themselves.
    Encoding both id AND created_at allows sorting by time with tie-breaking by id.
    """
    payload = json.dumps({"id": row_id, "created_at": created_at})
    # b64encode makes it URL-safe and hides the internal format from clients
    return b64encode(payload.encode()).decode()


def decode_cursor(cursor: str) -> Optional[Dict[str, str]]:
    """Decode cursor back to internal values. Returns None if invalid/tampered."""
    try:
        payload = b64decode(cursor.encode()).decode()
        return json.loads(payload)
    except Exception:
        return None  # Invalid cursor — treat as first page


def paginate_query(
    items: List[Dict[str, Any]],  # All items (simulating a DB query result)
    cursor: Optional[str],
    limit: int = 20,
    max_limit: int = 100,         # Cap limit to prevent abuse
) -> Page:
    """
    Simulate cursor-based pagination over a list.
    In production: cursor values become SQL WHERE clauses.
    Example SQL:
      WHERE (created_at, id) < (:cursor_time, :cursor_id)
      ORDER BY created_at DESC, id DESC
      LIMIT :limit + 1
    The +1 trick: fetch one extra to determine has_more without a COUNT query.
    """
    limit = min(limit, max_limit)  # Never allow clients to request unlimited results

    # Find starting position from cursor
    start_index = 0
    if cursor:
        decoded = decode_cursor(cursor)
        if decoded:
            # Find the item AFTER the cursor position
            for i, item in enumerate(items):
                if item.get("id") == decoded.get("id"):
                    start_index = i + 1
                    break

    # Fetch one extra item to determine if there are more pages
    page_items = items[start_index : start_index + limit + 1]
    has_more = len(page_items) > limit
    page_items = page_items[:limit]  # Drop the extra item from the actual response

    # Build next cursor from the last item in the current page
    next_cursor = None
    if has_more and page_items:
        last = page_items[-1]
        next_cursor = encode_cursor(last["id"], last.get("created_at", ""))

    # Build prev cursor for backwards navigation (from first item of current page)
    prev_cursor = None
    if start_index > 0 and page_items:
        first = page_items[0]
        prev_cursor = encode_cursor(first["id"], first.get("created_at", ""))

    return Page(
        data=page_items,
        has_more=has_more,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
    )


# =============================================================================
# SECTION 3 — BULK ENDPOINTS
# =============================================================================
# WHY: N sequential API calls = N round-trips. Mobile clients on high-latency
#      connections suffer badly. Bulk endpoints collapse N calls into 1.
#
# DESIGN RULES:
#   - Return per-item status so partial failures are visible
#   - Use HTTP 207 Multi-Status for mixed results
#   - Cap bulk size (e.g., max 100 items) to bound resource consumption
#   - Validate ALL items before processing ANY — fail-fast vs. partial commit
#   - Document atomicity guarantee: all-or-nothing vs. best-effort

@dataclass
class BulkItemResult:
    """Result of processing one item in a bulk operation."""
    index: int              # Position in the input array (for correlation)
    id: Optional[str]       # ID of created/updated resource (on success)
    status: int             # HTTP status code for this item
    error: Optional[Dict]   # Error details if status >= 400


def bulk_create(items: List[Dict[str, Any]], max_items: int = 100) -> Tuple[int, Dict]:
    """
    Process multiple creates in one request.
    Returns 207 Multi-Status with per-item results.
    """
    if len(items) > max_items:
        return 400, {
            "error": {
                "type": "bulk_limit_exceeded",
                "message": f"Maximum {max_items} items per bulk request. Got {len(items)}.",
            }
        }

    results = []
    any_success = False
    any_failure = False

    for index, item in enumerate(items):
        # Validate each item (simplified — real validation would be schema-based)
        if not item.get("name"):
            results.append(BulkItemResult(
                index=index, id=None, status=422,
                error={"field": "name", "message": "name is required"},
            ))
            any_failure = True
        else:
            # Simulate successful creation
            new_id = f"obj_{uuid.uuid4().hex[:8]}"
            results.append(BulkItemResult(index=index, id=new_id, status=201, error=None))
            any_success = True

    # 207 Multi-Status = mixed results. Use 200 if all succeeded, 422 if all failed.
    if any_success and any_failure:
        http_status = 207
    elif any_failure:
        http_status = 422
    else:
        http_status = 200

    return http_status, {
        "results": [asdict(r) for r in results],
        "summary": {
            "total": len(items),
            "succeeded": sum(1 for r in results if r.status < 400),
            "failed": sum(1 for r in results if r.status >= 400),
        },
    }


# =============================================================================
# SECTION 4 — ASYNC OPERATIONS (202 + Polling / Webhooks)
# =============================================================================
# WHY: Long-running operations (>5 seconds) should not block HTTP connections.
#      Client timeouts, load balancer timeouts, and mobile sleep modes will
#      interrupt synchronous long-polls. Use async with status polling or webhooks.
#
# PATTERN:
#   POST /reports      → 202 Accepted + {job_id, status_url}
#   GET  /jobs/{id}    → 200 {status: "running"|"completed"|"failed", result_url}
#   GET  /results/{id} → 200 {data: ...} (only after status=completed)

class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AsyncJob:
    """Represents a long-running async operation."""
    job_id: str
    status: JobStatus
    created_at: str
    updated_at: str
    progress_percent: int = 0
    result_url: Optional[str] = None   # Where to fetch results when completed
    error: Optional[Dict] = None
    estimated_completion: Optional[str] = None  # ISO 8601 duration; helps clients decide when to poll


def create_async_job(operation: str, params: Dict[str, Any]) -> Tuple[int, Dict]:
    """
    Accept a long-running request and return immediately with a job reference.
    The actual work happens in a background queue (Celery, SQS, Cloud Tasks, etc.)
    """
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    job = AsyncJob(
        job_id=job_id,
        status=JobStatus.QUEUED,
        created_at=now,
        updated_at=now,
        estimated_completion="PT2M",  # ISO 8601 duration: 2 minutes
    )

    # In production: enqueue to task queue here
    # celery_task.delay(job_id=job_id, operation=operation, params=params)

    return 202, {
        "job_id": job_id,
        "status": job.status,
        "created_at": job.created_at,
        # Tell client exactly where to poll — discoverable URL, not hardcoded by client
        "status_url": f"/v1/jobs/{job_id}",
        "estimated_completion": job.estimated_completion,
        # Recommend polling interval; also set as Retry-After HTTP header
        "poll_interval_seconds": 5,
    }


# =============================================================================
# SECTION 5 — FIELD SELECTION AND SPARSE FIELDSETS
# =============================================================================
# WHY: A User object might have 50 fields. A mobile list view needs 5.
#      Sending all 50 wastes bandwidth, increases parse time, and may leak
#      fields a consumer should not see.
#
# ?fields=id,name,email  → return only those three fields
# ?expand=address,orders → include nested related objects (opposite of sparse)
#
# This is simpler than GraphQL and works over standard REST without new tooling.

def apply_field_selection(
    obj: Dict[str, Any],
    fields_param: Optional[str],        # Comma-separated field names from query param
    always_include: Optional[Set[str]] = None,  # Fields always returned (e.g., "id")
) -> Dict[str, Any]:
    """
    Filter a response object to only the requested fields.
    Dot-notation support for nested fields (e.g., "address.city") is possible
    but adds complexity — implement only if consumers explicitly need it.
    """
    if not fields_param:
        return obj  # No filtering requested — return everything

    requested = {f.strip() for f in fields_param.split(",") if f.strip()}
    required = always_include or {"id"}  # Always include primary key for identification
    fields_to_include = requested | required

    return {k: v for k, v in obj.items() if k in fields_to_include}


def apply_expansion(
    obj: Dict[str, Any],
    expand_param: Optional[str],
    expand_handlers: Dict[str, Callable],  # Map of field_name → loader function
) -> Dict[str, Any]:
    """
    Expand nested related resources inline on request.
    ?expand=orders,address fetches and embeds those resources.
    Without expand: return {order_ids: ["ord_1", "ord_2"]} (references only).
    With ?expand=orders: return {orders: [{id: "ord_1", ...}, ...]} (full objects).
    """
    if not expand_param:
        return obj

    result = dict(obj)
    requested = {e.strip() for e in expand_param.split(",") if e.strip()}

    for field_name in requested:
        if field_name in expand_handlers:
            result[field_name] = expand_handlers[field_name](obj)
        # Silently ignore unknown expansion fields — lenient consumer approach

    return result


# =============================================================================
# SECTION 6 — REQUEST ID PROPAGATION (X-Request-ID)
# =============================================================================
# WHY: When a request touches 5 microservices, debugging requires correlating
#      logs across all of them. A single request ID that propagates through
#      every hop makes this possible in seconds instead of hours.
#
# CONVENTION:
#   - Client MAY send X-Request-ID (for their own correlation tracking)
#   - Server ALWAYS returns X-Request-ID (generates one if client didn't send)
#   - Every internal service call includes X-Request-ID in downstream headers
#   - Logs always include request_id as a structured field (not free-text)

def ensure_request_id(incoming_id: Optional[str]) -> str:
    """
    Return the client's request ID if provided and safe, otherwise generate one.
    Format: req_{timestamp_hex}_{random_hex} — human-sortable and globally unique.
    """
    if incoming_id and len(incoming_id) <= 128:  # Bound length to prevent log injection
        return incoming_id
    # Generate a new ID: hex timestamp prefix makes logs sortable chronologically
    timestamp_hex = format(int(time.time() * 1000), "x")
    random_suffix = uuid.uuid4().hex[:12]
    return f"req_{timestamp_hex}_{random_suffix}"


@dataclass
class RequestContext:
    """
    Carries per-request metadata through the call stack.
    Pass this object (or inject via middleware) to every function that makes
    downstream calls so it can propagate the request_id automatically.
    """
    request_id: str
    api_key: Optional[str]
    user_id: Optional[str]
    start_time: float = field(default_factory=time.time)

    def downstream_headers(self) -> Dict[str, str]:
        """Headers to include when calling any downstream microservice."""
        return {
            "X-Request-ID": self.request_id,
            "X-Forwarded-For-User": self.user_id or "",
        }

    def elapsed_ms(self) -> float:
        """How long since this request started — for performance logging."""
        return (time.time() - self.start_time) * 1000


# =============================================================================
# SECTION 7 — HATEOAS AND HYPERMEDIA
# =============================================================================
# HATEOAS: Hypermedia As The Engine Of Application State.
# The idea: responses include links to valid next actions, so clients discover
# the API dynamically rather than hard-coding URLs.
#
# WHEN IT HELPS:
#   - Generic API browsers / explorers (HAL Browser, etc.)
#   - When URL structure changes frequently
#   - Self-documenting APIs consumed by dynamic clients
#
# WHEN IT'S OVERENGINEERING:
#   - You control both server and client (internal API)
#   - Clients are generated from OpenAPI (they know all the URLs already)
#   - You have a stable URL structure (then just don't change the URLs)
#   - Mobile SDK or tightly-coupled single-page app
#
# Formats: HAL (application/hal+json), JSON:API, Siren, Collection+JSON

def add_hateoas_links(
    resource: Dict[str, Any],
    resource_type: str,
    resource_id: str,
) -> Dict[str, Any]:
    """
    Add _links to a resource following HAL (Hypertext Application Language) spec.
    Links are state-dependent — only include actions valid in the current state.
    """
    base_url = "/v1"
    links: Dict[str, Any] = {
        "self": {"href": f"{base_url}/{resource_type}s/{resource_id}"},
    }

    # Add context-specific links based on resource state
    if resource_type == "order":
        status = resource.get("status")
        if status == "pending":
            links["cancel"] = {"href": f"{base_url}/orders/{resource_id}/cancel", "method": "POST"}
            links["pay"] = {"href": f"{base_url}/orders/{resource_id}/pay", "method": "POST"}
        elif status == "paid":
            links["refund"] = {"href": f"{base_url}/orders/{resource_id}/refund", "method": "POST"}
            links["shipments"] = {"href": f"{base_url}/orders/{resource_id}/shipments"}

    return {**resource, "_links": links}


# =============================================================================
# SECTION 8 — API CONTRACT TESTING (Pact, Dredd)
# =============================================================================
# WHY: Integration tests catch bugs at deployment time. Contract tests catch them
#      at development time — before the breaking change even merges to main.
#
# CONSUMER-DRIVEN CONTRACTS (CDC):
#   Consumer (your client app) writes a "pact" describing what it needs:
#     - Which endpoints it calls
#     - What request shape it sends
#     - What response fields it USES (not the full schema — only what it reads)
#   Provider (your API) verifies the pact against its actual implementation.
#   If the provider breaks a field the consumer uses → CI fails immediately.
#
# TOOLS:
#   Pact:  https://pact.io — consumer-driven, best for microservices
#   Dredd: https://dredd.org — API description (OpenAPI/Blueprint) → live test
#   Prism: https://stoplight.io/open-source/prism — mock server from OpenAPI spec

# Example: Pact contract written by the consumer (mobile app team)
PACT_CONTRACT_EXAMPLE = {
    "consumer": {"name": "mobile-app"},
    "provider": {"name": "users-api"},
    "interactions": [
        {
            "description": "Get user by ID",
            "request": {
                "method": "GET",
                "path": "/v1/users/usr_123",
                "headers": {"Authorization": "Bearer <token>"},
            },
            "response": {
                "status": 200,
                "body": {
                    # ONLY the fields the consumer actually reads
                    # Not the full user schema — this scopes the contract precisely
                    # Provider can add fields freely; removing these breaks the contract
                    "id": "usr_123",
                    "name": "Alice",
                    "email": "alice@example.com",
                },
                # Matchers: type-check instead of value-match (avoids brittle fixtures)
                # "matchingRules": {"$.body.id": {"match": "type"}}
            },
        }
    ],
}


# =============================================================================
# SECTION 9 — API GOVERNANCE (Spectral Linting, Style Guides)
# =============================================================================
# WHY: APIs designed by different teams diverge in naming, pagination, error
#      formats, and versioning strategy. Governance enforces consistency at
#      the OpenAPI spec level, before code is written.
#
# SPECTRAL: https://stoplight.io/open-source/spectral
#   Lints OpenAPI/AsyncAPI specs against custom ruleset files.
#   Run in CI: spectral lint openapi.yaml --ruleset .spectral.yaml
#
# Example Spectral ruleset (.spectral.yaml):

SPECTRAL_RULESET_EXAMPLE = """
extends: spectral:oas         # Start from official OpenAPI ruleset
rules:
  # Enforce consistent error response shape across all endpoints
  error-response-shape:
    description: Error responses must have an 'error' object with 'type' and 'message'
    given: "$.paths..responses[?(@property >= '400')]"
    severity: error
    then:
      field: content.application/json.schema.properties.error.properties
      function: schema
      functionOptions:
        schema:
          required: [type, message]

  # All endpoints must have operationId (required for SDK generation)
  operation-id-required:
    given: "$.paths.*[get,post,put,patch,delete]"
    severity: error
    then:
      field: operationId
      function: truthy

  # Pagination responses must include next_cursor and has_more (not page/total)
  cursor-pagination-only:
    description: "Use cursor pagination, not offset/page-number pagination"
    given: "$.paths..responses[?(@property == '200')].content.application/json.schema.properties"
    severity: warn
    then:
      field: page
      function: falsy  # 'page' field presence signals offset pagination
"""


# =============================================================================
# SECTION 10 — TRAFFIC SHAPING: CANARY ROLLOUTS AND FEATURE FLAGS
# =============================================================================
# CANARY: Route a small % of traffic to the new API version before full rollout.
#   Catch bugs that weren't caught in staging (real traffic, real data patterns).
#   Gradually increase % as confidence grows: 1% → 5% → 25% → 100%
#
# FEATURE FLAGS IN APIs: Gate new behavior behind a flag so you can ship code
#   without activating it. Toggle per-customer, per-tier, or globally.
#   Enables: gradual rollout, instant rollback, A/B testing, beta programs.

class FeatureFlags:
    """
    Minimal feature flag implementation for API behavior gating.
    Production: use LaunchDarkly, Unleash, Statsig, or GrowthBook.
    """
    def __init__(self):
        # Map of flag_name → set of enabled identifiers (or "__all__" for global)
        self._flags: Dict[str, Set[str]] = {}

    def enable_for(self, flag: str, identifier: str) -> None:
        """Enable a flag for a specific API key, user ID, or org ID."""
        if flag not in self._flags:
            self._flags[flag] = set()
        self._flags[flag].add(identifier)

    def enable_globally(self, flag: str) -> None:
        """Enable a flag for all consumers. Use after canary validates it."""
        self._flags[flag] = {"__all__"}

    def is_enabled(self, flag: str, identifier: str) -> bool:
        """Check if a flag is enabled for the given identifier."""
        enabled_set = self._flags.get(flag, set())
        return "__all__" in enabled_set or identifier in enabled_set


def canary_router(request_api_key: str, canary_percentage: int = 10) -> str:
    """
    Route a request to 'canary' or 'stable' based on a hash of the API key.
    Hash-based routing ensures the SAME client always hits the same version —
    avoids confusing behavior where the same client gets different responses
    on consecutive requests (random routing would cause this).
    """
    # SHA-256 hash of the key, converted to integer, modulo 100 → bucket 0-99
    key_hash = int(hashlib.sha256(request_api_key.encode()).hexdigest(), 16) % 100
    return "canary" if key_hash < canary_percentage else "stable"


# =============================================================================
# SECTION 11 — API DEPRECATION WORKFLOW
# =============================================================================
# WHY: Removing API features without warning breaks consumer integrations.
#      A structured deprecation gives consumers time to migrate.
#
# RECOMMENDED TIMELINE:
#   T+0:   Announce deprecation. Add Deprecation + Sunset headers.
#           Stop accepting NEW consumers on deprecated endpoint.
#   T+3mo: Send deprecation warnings in API responses (header + body field).
#   T+6mo: Sunset. Return 410 Gone for all calls to deprecated endpoint.
#   T+9mo: Remove code and monitoring (after all traffic has ceased).
#
# HTTP HEADERS (RFC 8594):
#   Deprecation: Sat, 01 Jun 2024 00:00:00 GMT  ← announcement date
#   Sunset:      Sat, 01 Dec 2024 00:00:00 GMT  ← removal date
#   Link:        <https://docs.example.com/migration>; rel="successor-version"

def add_deprecation_headers(
    headers: Dict[str, str],
    deprecation_date: str,   # RFC 7231 HTTP date format
    sunset_date: str,        # RFC 7231 HTTP date format
    migration_url: str,
) -> Dict[str, str]:
    """
    Add deprecation notice headers to any response from a deprecated endpoint.
    Monitoring tools and SDK clients can detect and alert on these headers.
    """
    return {
        **headers,
        "Deprecation": deprecation_date,
        "Sunset": sunset_date,
        # rel="successor-version" is the standard link relation for the replacement
        "Link": f'<{migration_url}>; rel="successor-version"',
        # Warning 299 is a general-purpose warning for API consumers
        "Warning": f'299 - "This endpoint is deprecated. See {migration_url}"',
    }


# =============================================================================
# SECTION 12 — SDK GENERATION FROM OPENAPI
# =============================================================================
# openapi-generator generates client SDKs in 50+ languages from your OpenAPI spec.
#
# Docker command to generate a Python SDK:
#   docker run openapitools/openapi-generator-cli generate \
#     -i openapi.yaml \
#     -g python \
#     -o ./sdk/python \
#     --additional-properties=packageName=myapi_client,projectName=myapi-python
#
# DESIGN YOUR API FOR SDK GENERATION:
#   - Every operation MUST have a unique operationId → becomes the method name
#   - Use $ref schemas (not inline) → generated as typed model classes
#   - Tag operations consistently → tags become SDK module/namespace names
#   - Avoid bare oneOf/anyOf at top level → complex for generators to handle
#   - Provide request body examples → appear in SDK docstrings

OPENAPI_OPERATION_EXAMPLE = {
    # Good operationId: verb + resource noun, camelCase, globally unique
    "operationId": "createPayment",
    "summary": "Create a new payment",
    "description": "Initiates a payment. Supports idempotency via Idempotency-Key header.",
    "tags": ["Payments"],              # → sdk.payments.create_payment() in Python SDK
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/CreatePaymentRequest"},
                "example": {           # Required for good SDK documentation
                    "amount_cents": 9900,
                    "currency": "USD",
                    "customer_id": "cus_123",
                },
            }
        },
    },
    "responses": {
        "201": {"$ref": "#/components/responses/PaymentCreated"},
        "400": {"$ref": "#/components/responses/BadRequest"},
        "422": {"$ref": "#/components/responses/UnprocessableEntity"},
        "429": {"$ref": "#/components/responses/RateLimited"},
    },
    "x-idempotency-key": True,  # Custom extension: signal to SDK to add helper
}


# =============================================================================
# SECTION 13 — INTERNAL API vs PUBLIC API DESIGN DIFFERENCES
# =============================================================================
#
# | Concern            | Internal API              | Public API                   |
# |--------------------|---------------------------|------------------------------|
# | Versioning         | Coordinate deploys        | Maintain forever (semver)    |
# | Auth               | mTLS or service tokens    | OAuth 2.0 / API keys         |
# | Error messages     | Detailed (verbose OK)     | Safe (never expose internals)|
# | Breaking changes   | Fine with migration       | NEVER (or major version bump)|
# | Rate limiting      | Per-service SLO quotas    | Per-customer billing tiers   |
# | Documentation      | Minimal (code is doc)     | Full (tutorials, examples)   |
# | Pagination         | Offset OK for small sets  | Always cursor-based          |
# | Schema strictness  | Lenient (trusted callers) | Strict (validate everything) |
# | Idempotency        | Desirable                 | Required for all mutations   |
# | SLA                | Best effort               | Contractual (99.9%+)         |
# | Consumer contracts | Pact in CI                | OpenAPI + Dredd in CI        |
#
# KEY PRINCIPLE: Internal APIs become public eventually. Design them right first.
# The refactor cost of "adding idempotency later" to a public API is enormous.


# =============================================================================
# SECTION 14 — FULL PRODUCTION API DESIGN REVIEW CHECKLIST
# =============================================================================
# Use this before launching any new API endpoint to production.
# Each item represents a hard lesson from real production incidents.

PRODUCTION_API_DESIGN_CHECKLIST = """
=== PRODUCTION API DESIGN CHECKLIST ===

[ ] FUNDAMENTALS
    [ ] HTTP method matches semantics
        (GET=safe+idempotent, POST=create, PUT=replace, PATCH=partial, DELETE=remove)
    [ ] Status codes are correct
        (201=created, 200=updated/read, 204=delete with no body, 202=accepted async)
    [ ] No 200 OK with {"success": false} — use appropriate 4xx/5xx
    [ ] Versioning strategy defined (URL path /v1/ preferred for discoverability)
    [ ] URL uses nouns, not verbs (/payments, not /createPayment)
    [ ] Plural resource names (/users, not /user)

[ ] REQUEST DESIGN
    [ ] Idempotency-Key supported on all state-mutating endpoints (POST, PATCH, DELETE)
    [ ] Request body validated against JSON Schema with field-level 422 errors
    [ ] Path parameters validated (UUID format, numeric range, slug characters)
    [ ] Query parameters have documented defaults and documented max values
    [ ] Request size limits enforced (reject giant JSON before parsing)
    [ ] File uploads use multipart/form-data, not base64-in-JSON

[ ] RESPONSE DESIGN
    [ ] X-Request-ID returned on every response (generated if not provided)
    [ ] Error body follows consistent shape: {error: {type, message, code, details[]}}
    [ ] Error type is a stable string code, not a human message (messages change)
    [ ] Successful responses use resource-named keys, not generic "data"
    [ ] Timestamps are ISO-8601 UTC (not Unix timestamps, not local time)
    [ ] Monetary values in smallest currency unit (cents) — never floats
    [ ] Enums are string values, not integers (safe to add new values)
    [ ] Nullable vs. absent fields: document which means what

[ ] PAGINATION
    [ ] Cursor-based pagination for any collection that could exceed 1000 items
    [ ] Response shape: {data: [], next_cursor, has_more} — not page/total_count
    [ ] limit parameter has a maximum cap (e.g., 100)
    [ ] limit parameter has a sensible default (e.g., 20)
    [ ] Cursor is opaque base64 (clients must not construct or parse it)

[ ] PERFORMANCE
    [ ] Long-running operations (>5s) return 202 + {job_id, status_url}
    [ ] Bulk endpoints available where clients would naturally batch
    [ ] Field selection (?fields=) supported for large resource objects
    [ ] Expand parameter (?expand=) to avoid N+1 client round-trips
    [ ] Response compression enabled (gzip/br via Accept-Encoding)
    [ ] ETag / Last-Modified on cacheable GET responses (conditional requests)

[ ] SECURITY
    [ ] Authentication required on all non-public endpoints
    [ ] Authorization checked at object level (tenant isolation)
    [ ] Rate limiting applied at IP + API key + endpoint dimensions
    [ ] Sensitive data (credentials, PII) never in response bodies or logs
    [ ] CORS policy defined (allow only expected origins for browser APIs)
    [ ] Input fields size-bounded (prevent multi-MB string fields)

[ ] OBSERVABILITY
    [ ] X-Request-ID propagated to all downstream service calls
    [ ] Structured logs include: request_id, api_key, user_id, endpoint, status, duration_ms
    [ ] Metrics emitted per endpoint: count, error_rate, p50/p95/p99 latency
    [ ] 4xx errors logged at WARN (client errors, not our bug)
    [ ] 5xx errors logged at ERROR with full stack trace
    [ ] Slow requests (>500ms) flagged in logs for alerting

[ ] API LIFECYCLE
    [ ] Deprecation headers on deprecated endpoints (Deprecation, Sunset, Link)
    [ ] Changelog maintained for all breaking and notable non-breaking changes
    [ ] Semantic versioning followed: breaking change = major version increment
    [ ] Mock server available for consumer parallel development (from OpenAPI)
    [ ] Contract tests run in CI (Pact for microservices, Dredd for public)

[ ] DOCUMENTATION (PUBLIC API)
    [ ] OpenAPI spec kept in sync with implementation (spec-first preferred)
    [ ] Every operation has: operationId, summary, description, tags
    [ ] Every parameter documented: type, format, constraints, example
    [ ] Every error response documented with example body
    [ ] At least one code example per endpoint (auto-generated from SDK)
    [ ] Rate limits documented per endpoint and per tier
    [ ] Idempotency-Key usage documented with runnable code example
    [ ] Webhook signature verification documented with code example

[ ] SDK AND TOOLING
    [ ] operationId on all operations (required for SDK method naming)
    [ ] All schemas defined as $ref in components (not inline)
    [ ] SDK generated from spec and tested against real API in CI
    [ ] SDK published to package registries (PyPI, npm, Maven, etc.)
    [ ] Spectral linting runs on OpenAPI spec in CI (zero errors required)

[ ] INTERNAL vs PUBLIC DECISION
    [ ] If public: security review completed before launch
    [ ] If public: SLA defined, measured, and dashboarded
    [ ] If public: breaking change policy published to consumers
    [ ] If internal: still passes this checklist (they go public)
"""


# =============================================================================
# SECTION 15 — DEMONSTRATION
# =============================================================================

def run_demo():
    """Show key patterns from this file in action."""
    print("=== Production API Design Patterns Demo ===\n")

    # 1. Idempotency
    print("--- Idempotency Keys ---")
    store = IdempotencyKeyStore()

    def create_order_handler(body: Dict) -> Tuple[int, Dict]:
        """Simulates an order creation handler."""
        order_id = f"ord_{uuid.uuid4().hex[:8]}"
        return 201, {"id": order_id, "status": "created", "amount": body.get("amount")}

    body = {"amount": 9900, "currency": "USD"}
    idempotency_key = f"idem_{uuid.uuid4().hex}"

    status1, resp1, hdrs1 = idempotent_mutation(body, idempotency_key, "key_abc", store, create_order_handler)
    status2, resp2, hdrs2 = idempotent_mutation(body, idempotency_key, "key_abc", store, create_order_handler)

    print(f"  First call:  status={status1}, order={resp1.get('id')}")
    print(f"  Retry call:  status={status2}, order={resp2.get('id')}, replayed={hdrs2.get('Idempotent-Replayed')}")
    assert resp1["id"] == resp2["id"], "Idempotency broken — different IDs returned!"
    print("  IDs match — idempotency working correctly\n")

    # 2. Cursor pagination
    print("--- Cursor Pagination ---")
    all_items = [
        {"id": f"item_{i:04d}", "name": f"Item {i}", "created_at": f"2024-01-{(i % 28) + 1:02d}T00:00:00Z"}
        for i in range(1, 51)  # 50 items total
    ]
    page1 = paginate_query(all_items, cursor=None, limit=10)
    page2 = paginate_query(all_items, cursor=page1.next_cursor, limit=10)

    print(f"  Page 1: {len(page1.data)} items, has_more={page1.has_more}")
    print(f"  Page 2: {len(page2.data)} items, has_more={page2.has_more}")
    print(f"  Cursor: {page1.next_cursor[:24]}...\n")

    # 3. Field selection
    print("--- Field Selection ---")
    full_user = {
        "id": "usr_123", "name": "Alice", "email": "alice@example.com",
        "phone": "+15551234567", "address": {"city": "NYC"},
        "created_at": "2024-01-01T00:00:00Z",
        "internal_score": 42,            # Should not be exposed to consumers
        "stripe_customer_id": "cus_xyz", # Sensitive internal reference
    }
    sparse = apply_field_selection(full_user, "name,email", always_include={"id"})
    print(f"  Full object: {len(full_user)} fields")
    print(f"  ?fields=name,email: {sparse}\n")

    # 4. Bulk endpoint
    print("--- Bulk Create (207 Multi-Status) ---")
    items_to_create = [
        {"name": "Widget A", "price": 100},
        {"name": "", "price": 200},          # Missing name — will fail validation
        {"name": "Widget C", "price": 300},
    ]
    status, bulk_response = bulk_create(items_to_create)
    print(f"  HTTP {status}")
    print(f"  Summary: {bulk_response['summary']}\n")

    # 5. Feature flags + canary routing
    print("--- Feature Flags ---")
    flags = FeatureFlags()
    flags.enable_for("new_checkout_flow", "key_premium_001")
    print(f"  Premium key: {flags.is_enabled('new_checkout_flow', 'key_premium_001')}")
    print(f"  Free key:    {flags.is_enabled('new_checkout_flow', 'key_free_002')}\n")

    print("--- Canary Router (10% → canary) ---")
    for test_key in ["key_aaa", "key_bbb", "key_ccc", "key_ddd", "key_eee"]:
        route = canary_router(test_key, canary_percentage=10)
        print(f"  {test_key} → {route}")

    # 6. Request ID
    print("\n--- Request ID ---")
    incoming_id = None  # Client didn't send one
    req_id = ensure_request_id(incoming_id)
    ctx = RequestContext(request_id=req_id, api_key="key_abc", user_id="usr_123")
    print(f"  Generated request ID: {req_id}")
    print(f"  Downstream headers: {ctx.downstream_headers()}\n")

    # 7. Deprecation headers
    print("--- Deprecation Headers ---")
    dep_headers = add_deprecation_headers(
        headers={},
        deprecation_date="Sat, 01 Jun 2024 00:00:00 GMT",
        sunset_date="Sat, 01 Dec 2024 00:00:00 GMT",
        migration_url="https://docs.example.com/v2/migration",
    )
    for k, v in dep_headers.items():
        print(f"  {k}: {v[:60]}")

    print("\n--- Design Checklist Preview ---")
    print(PRODUCTION_API_DESIGN_CHECKLIST.split("\n")[:12])
    print("  ... (full checklist in PRODUCTION_API_DESIGN_CHECKLIST constant)")


if __name__ == "__main__":
    run_demo()
