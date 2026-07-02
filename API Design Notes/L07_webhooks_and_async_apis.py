# ============================================================
# L06: Webhooks and Async APIs
# ============================================================
# WHAT: Event-driven delivery (server pushes to client HTTP endpoint),
#       async operation patterns (202 + polling/callback), idempotency,
#       and pagination strategies for production APIs.
# WHY:  Polling wastes resources; webhooks push events instantly.
#       Long operations need async patterns — holding connections open
#       for minutes is untenable. Idempotency prevents duplicate charges.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    Webhooks invert the request/response model: your server POSTs to the
    client's registered URL when events occur (payment.completed,
    user.created, order.shipped). Delivery is at-least-once — retries on
    failure mean clients must handle duplicates (idempotency). Payloads are
    signed with HMAC-SHA256 so clients can verify authenticity.

    Async APIs: when an operation takes > a few seconds (PDF generation,
    video encoding, bulk export), return 202 Accepted immediately with a
    task_id. Client polls GET /tasks/{id} or receives a webhook callback.

    Idempotency keys let clients safely retry without double-processing.
    Client generates a UUID, sends in Idempotency-Key header. Server caches
    result for 24h and returns it on duplicate requests.

PRODUCTION USE CASE:
    Stripe uses all three patterns: webhooks for payment events, async for
    payouts/disputes, idempotency keys mandatory for charge creation. GitHub
    webhooks notify CI systems on push events. Twilio webhooks for SMS
    status. AWS SNS + SQS for durable async event delivery at scale.

COMMON MISTAKES:
    - Not verifying webhook signature — anyone can send fake events.
    - Doing heavy work synchronously in webhook handler — must return 200
      within 5s or sender marks delivery failed.
    - No retry logic — transient failures mean missed events.
    - Exposing unbounded lists — always paginate.
    - Using offset pagination on high-traffic feeds — O(n) DB cost; use cursors.
    - Not logging webhook deliveries — impossible to debug without logs.
"""

import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlencode

# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    """
    Typed event catalogue.
    Clients subscribe to specific events — not all events.
    This reduces noise and respects bandwidth.
    """
    PAYMENT_COMPLETED  = "payment.completed"
    PAYMENT_FAILED     = "payment.failed"
    USER_CREATED       = "user.created"
    USER_DELETED       = "user.deleted"
    ORDER_SHIPPED      = "order.shipped"
    SUBSCRIPTION_RENEWED = "subscription.renewed"


@dataclass
class WebhookRegistration:
    """
    Persisted per customer in DB.
    secret is never returned to client after creation — store hashed or
    encrypted at rest, but need plaintext for HMAC signing (use envelope
    encryption with KMS in production).
    """
    id: str
    customer_id: str
    url: str                       # Client's HTTPS endpoint
    secret: str                    # Used to sign payloads (HMAC key)
    subscribed_events: List[EventType]  # Selective subscription
    active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    failure_count: int = 0         # Consecutive failures — disable after threshold


@dataclass
class WebhookDelivery:
    """
    Delivery log entry — persisted to DB.
    Provides auditability and enables manual retry from dashboard.
    """
    id: str
    webhook_id: str
    event_type: EventType
    event_id: str                  # Idempotency key for the event itself
    payload: Dict[str, Any]
    attempt: int                   # 1-5
    status_code: Optional[int]
    response_body: Optional[str]
    delivered_at: Optional[datetime]
    next_retry_at: Optional[datetime]
    success: bool = False


# ---------------------------------------------------------------------------
# Signature utilities
# ---------------------------------------------------------------------------

class WebhookSigner:
    """
    HMAC-SHA256 payload signing.

    WHY SIGNING MATTERS:
        Without signature verification, anyone who knows your webhook URL
        can send fake events (payment.completed for a payment that never
        happened). HMAC ties the payload to the shared secret — only your
        server and the customer's server know it.

    STRIPE'S APPROACH:
        Stripe includes a timestamp in the signed data to prevent replay
        attacks: signature = HMAC(secret, f"{timestamp}.{body}").
        Clients reject events where timestamp is > 5 minutes old.
    """

    @staticmethod
    def sign(secret: str, body: bytes, timestamp: Optional[int] = None) -> str:
        """
        Generate X-Signature-256 header value.

        Including timestamp in signed data prevents replay attacks —
        an attacker can't re-send a captured webhook payload later
        because the timestamp will be stale.
        """
        ts = timestamp or int(time.time())
        # Signed string: "v1:{timestamp}:{body}"
        signed_string = f"v1:{ts}:".encode() + body
        mac = hmac.new(
            secret.encode("utf-8"),
            signed_string,
            hashlib.sha256
        ).hexdigest()
        # Header format: "t={timestamp},v1={signature}"
        # Allows multiple signatures during key rotation
        return f"t={ts},v1={mac}"

    @staticmethod
    def verify(secret: str, body: bytes, signature_header: str,
               max_age_seconds: int = 300) -> bool:
        """
        Verify webhook signature from X-Signature-256 header.

        TIMING ATTACK PREVENTION:
            Use hmac.compare_digest() — NOT == operator.
            == short-circuits on first mismatch, leaking timing info
            that attackers can use to brute-force secrets.

        Args:
            secret: Webhook secret for this registration.
            body: Raw request body bytes (before any parsing).
            signature_header: Full header value "t=...,v1=...".
            max_age_seconds: Reject events older than this (replay protection).

        Returns:
            True if signature is valid and event is fresh.
        """
        try:
            parts = dict(p.split("=", 1) for p in signature_header.split(","))
            timestamp = int(parts["t"])
            received_sig = parts["v1"]
        except (KeyError, ValueError):
            return False  # Malformed header

        # Reject stale events (replay attack protection)
        age = int(time.time()) - timestamp
        if age > max_age_seconds:
            return False

        # Recompute expected signature
        signed_string = f"v1:{timestamp}:".encode() + body
        expected_mac = hmac.new(
            secret.encode("utf-8"),
            signed_string,
            hashlib.sha256
        ).hexdigest()

        # Constant-time comparison — immune to timing attacks
        return hmac.compare_digest(expected_mac, received_sig)


# ---------------------------------------------------------------------------
# Webhook delivery engine with retry
# ---------------------------------------------------------------------------

class WebhookDeliveryEngine:
    """
    Handles dispatch with exponential backoff retry.

    RETRY SCHEDULE:
        Attempt 1: immediate
        Attempt 2: 1s delay
        Attempt 3: 2s delay
        Attempt 4: 4s delay
        Attempt 5: 8s delay (max — discard after 5 failures)

    In production this runs as a background worker (Celery, RQ, or
    a dedicated async worker), not in the web process.

    AT-LEAST-ONCE DELIVERY:
        We retry on failure, so clients MAY receive duplicates. This is
        intentional — better to deliver twice than miss. Clients handle
        duplicates using the event_id (idempotency key per event).
    """

    # Retry delays in seconds: attempt index 0 = first retry
    RETRY_DELAYS = [1, 2, 4, 8]

    def __init__(self, http_client=None):
        # In production: httpx.AsyncClient with timeout=10
        self._http = http_client
        self._deliveries: List[WebhookDelivery] = []  # Simulating DB

    def build_payload(self, event_type: EventType, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Standard envelope for all webhook payloads.

        event_id enables idempotency on client side — store processed
        event_ids, skip if already seen.
        """
        return {
            "event_id": str(uuid.uuid4()),    # Unique per event
            "event_type": event_type.value,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "api_version": "2024-01",         # Version the payload schema
            "data": data,
        }

    def deliver(self, registration: WebhookRegistration,
                event_type: EventType, data: Dict[str, Any]) -> WebhookDelivery:
        """
        Deliver webhook with retry logic.

        IMPORTANT: In production, this entire method runs in a background
        job queue (Celery beat, RQ, or cloud task queue). The API endpoint
        that triggered the event returns immediately — it just enqueues
        the delivery job.
        """
        if not registration.active:
            raise ValueError(f"Webhook {registration.id} is inactive")

        if event_type not in registration.subscribed_events:
            raise ValueError(f"Webhook not subscribed to {event_type}")

        payload = self.build_payload(event_type, data)
        body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = WebhookSigner.sign(registration.secret, body_bytes)

        headers = {
            "Content-Type": "application/json",
            "X-Signature-256": signature,
            "X-Webhook-ID": registration.id,
            "X-Event-ID": payload["event_id"],
            "User-Agent": "MyApp-Webhooks/1.0",
        }

        delivery = WebhookDelivery(
            id=str(uuid.uuid4()),
            webhook_id=registration.id,
            event_type=event_type,
            event_id=payload["event_id"],
            payload=payload,
            attempt=0,
            status_code=None,
            response_body=None,
            delivered_at=None,
            next_retry_at=None,
        )

        # Attempt delivery with retry
        for attempt in range(1, 6):  # Up to 5 attempts
            delivery.attempt = attempt
            print(f"[Webhook] Attempt {attempt}/5 → {registration.url}")

            # Simulate HTTP POST (in production: await httpx.post(...))
            status_code, response_body = self._simulate_http_post(
                registration.url, body_bytes, headers
            )

            delivery.status_code = status_code
            delivery.response_body = response_body

            if 200 <= status_code < 300:
                # Success — log and return
                delivery.success = True
                delivery.delivered_at = datetime.utcnow()
                print(f"[Webhook] Delivered successfully (attempt {attempt})")
                self._deliveries.append(delivery)
                return delivery

            # Failed — schedule retry if attempts remain
            print(f"[Webhook] Failed with {status_code}")
            if attempt < 5:
                delay = self.RETRY_DELAYS[attempt - 1]
                delivery.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
                print(f"[Webhook] Retrying in {delay}s...")
                time.sleep(delay)  # In production: use job queue scheduling

        # All attempts exhausted — mark registration as degraded
        registration.failure_count += 1
        if registration.failure_count >= 10:
            registration.active = False
            print(f"[Webhook] Disabled {registration.id} after 10 consecutive failures")

        self._deliveries.append(delivery)
        return delivery

    def _simulate_http_post(self, url: str, body: bytes,
                             headers: Dict[str, str]) -> tuple[int, str]:
        """Simulate HTTP response — replace with real HTTP client."""
        # Simulate 80% success rate for demo
        import random
        if random.random() < 0.8:
            return 200, '{"received": true}'
        return 500, '{"error": "internal server error"}'

    def get_delivery_log(self, webhook_id: str) -> List[WebhookDelivery]:
        """Fetch delivery history for dashboard display."""
        return [d for d in self._deliveries if d.webhook_id == webhook_id]


# ---------------------------------------------------------------------------
# Async API pattern: 202 Accepted + polling
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    DONE       = "done"
    FAILED     = "failed"


@dataclass
class AsyncTask:
    """
    Represents a long-running operation (report export, video encoding).
    Returned immediately with 202 Accepted. Client polls GET /tasks/{id}.
    """
    id: str
    operation: str
    status: TaskStatus
    progress: int = 0          # 0-100 percentage
    result_url: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    def to_api_response(self) -> Dict[str, Any]:
        """Serialize for API response — client polls this shape."""
        return {
            "task_id": self.id,
            "status": self.status.value,
            "progress": self.progress,
            "result_url": self.result_url,
            "error": self.error,
            "created_at": self.created_at.isoformat() + "Z",
            "completed_at": self.completed_at.isoformat() + "Z" if self.completed_at else None,
            # Inform client when to poll next
            "_links": {
                "self": f"/tasks/{self.id}",
                "poll_after_seconds": 5 if self.status == TaskStatus.PROCESSING else None,
            }
        }


class AsyncTaskManager:
    """
    Manages async tasks for long-running operations.

    API FLOW:
        POST /exports         → 202 Accepted, body: {task_id: "abc123"}
                                Header: Location: /tasks/abc123
        GET /tasks/abc123     → {status: "processing", progress: 45}
        GET /tasks/abc123     → {status: "done", result_url: "https://..."}

    WHY 202 NOT 200:
        202 Accepted means "request accepted for processing, not yet complete".
        Semantically correct for async work. Include Location header pointing
        to the polling endpoint.
    """

    def __init__(self):
        self._tasks: Dict[str, AsyncTask] = {}

    def create_task(self, operation: str) -> AsyncTask:
        """Create and persist a new async task. Returns immediately."""
        task = AsyncTask(
            id=str(uuid.uuid4()),
            operation=operation,
            status=TaskStatus.PENDING,
        )
        self._tasks[task.id] = task
        print(f"[AsyncAPI] Task {task.id} created for '{operation}'")
        return task

    def get_task(self, task_id: str) -> Optional[AsyncTask]:
        """GET /tasks/{id} handler — client polls this."""
        return self._tasks.get(task_id)

    def update_progress(self, task_id: str, progress: int,
                        result_url: Optional[str] = None) -> None:
        """Background worker calls this as operation proceeds."""
        task = self._tasks.get(task_id)
        if not task:
            return
        task.progress = progress
        if progress >= 100 and result_url:
            task.status = TaskStatus.DONE
            task.result_url = result_url
            task.completed_at = datetime.utcnow()
        else:
            task.status = TaskStatus.PROCESSING

    def fail_task(self, task_id: str, error: str) -> None:
        """Mark task as failed — client sees error on next poll."""
        task = self._tasks.get(task_id)
        if task:
            task.status = TaskStatus.FAILED
            task.error = error
            task.completed_at = datetime.utcnow()


# ---------------------------------------------------------------------------
# Idempotency key middleware
# ---------------------------------------------------------------------------

class IdempotencyStore:
    """
    Prevents duplicate processing of non-idempotent POST requests.

    CLIENT USAGE:
        POST /payments
        Headers:
            Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
        (Client generates UUID, stores it, retries with SAME key on failure)

    SERVER BEHAVIOUR:
        First request:  process + store result (key → response, TTL 24h)
        Duplicate:      return cached result immediately, no processing

    STORAGE:
        Redis with TTL=86400 (24h) in production.
        Key format: idempotency:{customer_id}:{idempotency_key}
        (Namespaced by customer to prevent cross-customer collision)

    WHERE IT'S REQUIRED:
        - Payment creation (Stripe requires it)
        - Order creation
        - Any POST that creates resources or charges money
        Non-idempotent by nature = need idempotency key support.
    """

    def __init__(self):
        # Simulating Redis with TTL: {key: (response, expires_at)}
        self._store: Dict[str, tuple[Dict, datetime]] = {}
        self.TTL_HOURS = 24

    def _make_key(self, customer_id: str, idempotency_key: str) -> str:
        return f"idempotency:{customer_id}:{idempotency_key}"

    def get_cached_response(self, customer_id: str,
                             idempotency_key: str) -> Optional[Dict[str, Any]]:
        """Return cached response if key was used before (and not expired)."""
        key = self._make_key(customer_id, idempotency_key)
        if key in self._store:
            response, expires_at = self._store[key]
            if datetime.utcnow() < expires_at:
                print(f"[Idempotency] Cache hit for key {idempotency_key}")
                return response
            # Expired — remove and treat as fresh
            del self._store[key]
        return None

    def store_response(self, customer_id: str, idempotency_key: str,
                        response: Dict[str, Any]) -> None:
        """Cache the response after successful processing."""
        key = self._make_key(customer_id, idempotency_key)
        expires_at = datetime.utcnow() + timedelta(hours=self.TTL_HOURS)
        self._store[key] = (response, expires_at)
        print(f"[Idempotency] Stored response for key {idempotency_key} (TTL {self.TTL_HOURS}h)")


# ---------------------------------------------------------------------------
# Pagination: cursor vs offset
# ---------------------------------------------------------------------------

class PaginationStrategy:
    """
    Cursor pagination for feeds; offset for admin UIs.

    CURSOR PAGINATION:
        SQL: WHERE id > {cursor} ORDER BY id LIMIT {page_size}
        Always O(1) — DB uses index seek, no offset scan.
        Stable under inserts/deletes — no items missed or duplicated.
        CANNOT jump to arbitrary page — only next/prev.
        Use for: activity feeds, event streams, mobile infinite scroll.

    OFFSET PAGINATION:
        SQL: SELECT ... LIMIT {size} OFFSET {page * size}
        O(n) at high pages — DB scans and discards offset rows.
        Supports "go to page 50 of 200" UI.
        Unstable: new inserts shift pages, causing duplicates/gaps.
        Use for: admin UIs, analytics dashboards, when total count matters.

    NEVER return unbounded lists:
        GET /users  →  must have a LIMIT. Default 20, max 100.
        Without limits: a customer with 10M orders breaks your API.
    """

    @staticmethod
    def cursor_page(items: List[Dict], cursor: Optional[str],
                    page_size: int = 20) -> Dict[str, Any]:
        """
        Simulate cursor-based pagination response.
        In real SQL: WHERE id > cursor ORDER BY id LIMIT page_size + 1
        (Fetch one extra to detect if next page exists)
        """
        # Simulate filtering by cursor
        if cursor:
            items = [i for i in items if i["id"] > cursor]

        # Fetch one extra to check if more pages exist
        has_more = len(items) > page_size
        page_items = items[:page_size]
        next_cursor = page_items[-1]["id"] if has_more and page_items else None

        return {
            "data": page_items,
            "pagination": {
                "cursor": next_cursor,
                "has_more": has_more,
                "page_size": page_size,
            }
        }

    @staticmethod
    def offset_page(items: List[Dict], page: int,
                    page_size: int = 20) -> Dict[str, Any]:
        """
        Offset pagination — suitable for admin UIs where total is displayed.
        Expensive at high page numbers in real DB.
        """
        total = len(items)
        start = page * page_size
        page_items = items[start:start + page_size]
        total_pages = (total + page_size - 1) // page_size

        return {
            "data": page_items,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total,
                "total_pages": total_pages,
                "has_next": page < total_pages - 1,
                "has_prev": page > 0,
            }
        }


# ---------------------------------------------------------------------------
# Client verification example
# ---------------------------------------------------------------------------

def example_client_webhook_handler(request_body: bytes,
                                   signature_header: str,
                                   webhook_secret: str) -> Dict[str, Any]:
    """
    Example: how your customer's server should handle incoming webhooks.

    CRITICAL RULES:
        1. Verify signature FIRST — reject if invalid (return 403).
        2. Return 200 immediately — do heavy work async (Celery task).
        3. Use event_id to deduplicate (store in DB, skip if seen).
        4. Never expose signature verification errors to attacker —
           always return generic 400/403.

    WHAT NOT TO DO:
        - Parse JSON before verifying signature (parsing is processing work)
        - Return 500 on processing errors (sender will retry — good)
        - Return 200 even if verification fails (silent security hole)
    """
    # Step 1: Verify signature (BEFORE parsing body)
    if not WebhookSigner.verify(webhook_secret, request_body, signature_header):
        # Return 403 — do not process unverified events
        return {"status": 403, "error": "Invalid signature"}

    # Step 2: Parse event
    try:
        event = json.loads(request_body)
    except json.JSONDecodeError:
        return {"status": 400, "error": "Invalid JSON"}

    event_id = event.get("event_id")
    event_type = event.get("event_type")

    # Step 3: Check idempotency (simulate DB lookup)
    already_processed = False  # Replace with: db.event_ids.exists(event_id)
    if already_processed:
        return {"status": 200, "message": "Already processed"}  # Idempotent 200

    # Step 4: Enqueue for async processing — return 200 IMMEDIATELY
    print(f"[Client] Received event {event_type} (id={event_id}) — enqueuing...")
    # celery_task.delay(event)  # Real async dispatch

    # Step 5: Return 200 within 5 seconds (before sender times out)
    return {"status": 200, "received": True}


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("WEBHOOK SYSTEM DEMO")
    print("=" * 60)

    # 1. Register a webhook
    registration = WebhookRegistration(
        id=str(uuid.uuid4()),
        customer_id="cust_123",
        url="https://example.com/webhooks",
        secret=secrets.token_hex(32),
        subscribed_events=[EventType.PAYMENT_COMPLETED, EventType.ORDER_SHIPPED],
    )
    print(f"\nRegistered webhook: {registration.id}")
    print(f"Secret (show once): {registration.secret[:8]}...")

    # 2. Sign a payload manually
    payload = {"order_id": "ord_456", "amount": 9900}
    body = json.dumps(payload).encode()
    sig = WebhookSigner.sign(registration.secret, body)
    print(f"\nSignature header: {sig[:40]}...")
    valid = WebhookSigner.verify(registration.secret, body, sig)
    print(f"Signature valid: {valid}")

    # 3. Async task pattern
    print("\n--- ASYNC API ---")
    task_mgr = AsyncTaskManager()
    task = task_mgr.create_task("export_monthly_report")
    print(f"202 Accepted: task_id={task.id}")
    print(f"Location: /tasks/{task.id}")

    task_mgr.update_progress(task.id, 50)
    print(f"Poll result: {task_mgr.get_task(task.id).to_api_response()['status']}")
    task_mgr.update_progress(task.id, 100, result_url="https://cdn.example.com/report.pdf")
    print(f"Poll result: {task_mgr.get_task(task.id).to_api_response()['status']}")

    # 4. Idempotency
    print("\n--- IDEMPOTENCY ---")
    store = IdempotencyStore()
    idem_key = str(uuid.uuid4())
    # First request — process and cache
    response = {"payment_id": "pay_789", "status": "captured", "amount": 9900}
    store.store_response("cust_123", idem_key, response)
    # Duplicate request — return cached
    cached = store.get_cached_response("cust_123", idem_key)
    print(f"Cached response (duplicate): {cached}")

    # 5. Pagination
    print("\n--- PAGINATION ---")
    all_items = [{"id": f"{i:04d}", "name": f"Item {i}"} for i in range(1, 55)]
    cursor_result = PaginationStrategy.cursor_page(all_items, cursor=None, page_size=20)
    print(f"Cursor page 1: {len(cursor_result['data'])} items, "
          f"next_cursor={cursor_result['pagination']['cursor']}, "
          f"has_more={cursor_result['pagination']['has_more']}")

    offset_result = PaginationStrategy.offset_page(all_items, page=2, page_size=20)
    print(f"Offset page 3: {len(offset_result['data'])} items, "
          f"total={offset_result['pagination']['total_items']}")


if __name__ == "__main__":
    main()
