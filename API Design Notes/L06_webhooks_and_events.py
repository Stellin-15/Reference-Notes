# =============================================================================
# WHAT:  Webhook fundamentals and event-driven integration patterns
# WHY:   Webhooks are the backbone of real-time integrations between services;
#        understanding them correctly prevents silent data loss, replay attacks,
#        and brittle fan-out architectures.
# LEVEL: Intermediate → Advanced (assumes HTTP and basic crypto knowledge)
# =============================================================================

# CONCEPT OVERVIEW
# ----------------
# A webhook is an outbound HTTP callback: YOUR server POSTs a JSON payload to
# a SUBSCRIBER's URL when something happens in your system. This inverts the
# traditional request/response model — the subscriber does not poll; it listens.
#
# Key mental model:
#   Event source  →  Webhook dispatcher  →  Subscriber endpoint
#
# Polling vs Webhook vs SSE vs WebSocket (decision matrix at bottom of file)

# PRODUCTION USE CASE
# -------------------
# Payment processor (Stripe-style): when a charge succeeds, POST a
# "payment.succeeded" event to every registered subscriber URL.
# The subscriber must acknowledge with HTTP 200 within 5 seconds or the
# dispatcher retries with exponential backoff and eventually dead-letters it.

# COMMON MISTAKES
# ---------------
# 1. Not verifying signatures — any internet actor can POST fake events
# 2. Processing inside the HTTP handler — always enqueue, then process async
# 3. Missing idempotency — retries will re-deliver; your handler must be safe
# 4. Ignoring delivery order — events can arrive out of order under retries
# 5. Storing raw secrets in logs — mask the signing key everywhere

import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import urlencode

import requests  # pip install requests
# Redis would be: import redis  (shown in pseudo-code where needed)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# SECTION 1 — WEBHOOK PAYLOAD DESIGN (Envelope Pattern)
# =============================================================================
# The envelope wraps every event with routing metadata separate from business
# data. This lets consumers route/filter without parsing the inner "data" blob.
# Follows the CloudEvents spec structure (see Section 7 for full CloudEvents).

@dataclass
class WebhookEnvelope:
    """
    Standard envelope for all outbound webhook events.

    Fields mirror Stripe/GitHub conventions so integrators feel at home.
    Every field at the top level is metadata; business data lives in `data`.
    """
    event_id: str          # Globally unique — used for idempotency dedup
    event_type: str        # Dot-notation: "payment.succeeded", "user.deleted"
    created_at: str        # ISO-8601 UTC — always UTC, never local time
    api_version: str       # Let subscribers know which schema to expect
    data: Dict[str, Any]  # The actual business payload for this event type
    # Optional fields subscribers can use for filtering without parsing `data`
    object_type: Optional[str] = None   # e.g. "payment", "subscription"
    object_id: Optional[str] = None     # Primary key of the affected object
    idempotency_key: Optional[str] = None  # Caller-supplied dedup key (mutations)

    @classmethod
    def create(
        cls,
        event_type: str,
        data: Dict[str, Any],
        api_version: str = "2024-01-01",
        object_type: Optional[str] = None,
        object_id: Optional[str] = None,
    ) -> "WebhookEnvelope":
        """Factory that auto-generates event_id and created_at timestamp."""
        return cls(
            event_id=f"evt_{uuid.uuid4().hex}",  # Prefixed IDs are debuggable
            event_type=event_type,
            created_at=datetime.now(timezone.utc).isoformat(),
            api_version=api_version,
            data=data,
            object_type=object_type,
            object_id=object_id,
        )

    def to_json(self) -> str:
        """Serialize to JSON — use this exact bytes for signature computation."""
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)
        # sort_keys=True ensures deterministic serialization for HMAC


# =============================================================================
# SECTION 2 — SIGNATURE VERIFICATION (HMAC-SHA256)
# =============================================================================
# WHY: Without signatures, any attacker who knows your webhook URL can POST
#      fake events. Signatures prove the payload came from YOUR server.
#
# HOW: You share a per-subscriber secret key at registration time.
#      When dispatching: HMAC-SHA256(secret, payload_bytes) → hex digest.
#      Subscriber recomputes the same digest and compares with constant-time
#      comparison to prevent timing attacks.

class WebhookSigner:
    """
    Handles HMAC-SHA256 signing and verification of webhook payloads.
    Mirrors GitHub's X-Hub-Signature-256 convention.
    """
    HEADER_NAME = "X-Hub-Signature-256"
    PREFIX = "sha256="  # Prefix lets subscribers know the algorithm used

    @staticmethod
    def generate_secret() -> str:
        """
        Generate a cryptographically secure random secret for a subscriber.
        32 bytes = 256 bits of entropy — same as GitHub's default.
        """
        return secrets.token_hex(32)  # Returns 64-character hex string

    @staticmethod
    def sign(payload: str, secret: str) -> str:
        """
        Compute HMAC-SHA256 signature of a payload string.

        Args:
            payload: The raw JSON string (not parsed dict — order matters!)
            secret:  Per-subscriber signing secret

        Returns:
            Header value string, e.g. "sha256=abcdef1234..."
        """
        mac = hmac.new(
            key=secret.encode("utf-8"),    # Secret must be bytes
            msg=payload.encode("utf-8"),   # Payload must be bytes
            digestmod=hashlib.sha256,      # Always SHA-256 for modern security
        )
        return f"{WebhookSigner.PREFIX}{mac.hexdigest()}"

    @staticmethod
    def verify(payload: str, secret: str, signature_header: str) -> bool:
        """
        Verify an incoming signature against the expected one.

        CRITICAL: Use hmac.compare_digest — NOT == — to prevent timing attacks.
        A timing attack lets an attacker brute-force the secret by measuring
        how long your comparison takes (early exit leaks information).

        Args:
            payload:          Raw request body as string
            secret:           The subscriber's signing secret you stored
            signature_header: Value of X-Hub-Signature-256 from request headers

        Returns:
            True only if signature is valid
        """
        expected = WebhookSigner.sign(payload, secret)
        # hmac.compare_digest runs in constant time regardless of where mismatch occurs
        return hmac.compare_digest(expected, signature_header)


# Example: how a subscriber's Flask endpoint would verify
def example_flask_receiver_pseudocode():
    """
    Pseudocode showing correct subscriber-side verification.
    In production this would be a real Flask/FastAPI route.
    """
    # from flask import request, abort
    # raw_body = request.get_data(as_text=True)  # Get RAW bytes before any parsing
    # sig_header = request.headers.get("X-Hub-Signature-256", "")
    # subscriber_secret = os.environ["WEBHOOK_SECRET"]

    # if not WebhookSigner.verify(raw_body, subscriber_secret, sig_header):
    #     abort(403, "Invalid signature")  # Reject immediately — do not process

    # event = WebhookEnvelope(**json.loads(raw_body))
    # enqueue_for_async_processing(event)  # Never process synchronously in handler
    # return "", 200  # ACK fast; processing happens out of band
    pass


# =============================================================================
# SECTION 3 — RETRY LOGIC WITH EXPONENTIAL BACKOFF
# =============================================================================
# WHY: Subscribers have downtime, deploys, transient errors. Without retries,
#      events are silently lost. Exponential backoff prevents overwhelming a
#      recovering subscriber.
#
# Standard schedule: 5 min → 30 min → 2 hr (total ~2.5 hours of attempts)

class DeliveryStatus(Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"


@dataclass
class DeliveryAttempt:
    """Record of one delivery attempt for audit/debugging purposes."""
    attempt_number: int
    attempted_at: str
    http_status: Optional[int]
    response_body: Optional[str]
    error_message: Optional[str]
    duration_ms: float


@dataclass
class WebhookDelivery:
    """Tracks the full lifecycle of delivering one event to one subscriber."""
    delivery_id: str
    event_id: str
    subscriber_url: str
    status: DeliveryStatus
    attempts: List[DeliveryAttempt] = field(default_factory=list)
    next_retry_at: Optional[float] = None  # Unix timestamp

    # Retry schedule in seconds: 5 min, 30 min, 2 hours
    RETRY_DELAYS = [300, 1800, 7200]
    MAX_ATTEMPTS = 3


class WebhookDispatcher:
    """
    Handles the mechanics of dispatching a webhook payload to a single
    subscriber URL with retry logic and dead-letter queue fallback.
    """
    # Timeout for subscriber HTTP calls — MUST be short; you hold a thread per call
    REQUEST_TIMEOUT_SECONDS = 10

    def __init__(self, signing_secret: str):
        self.signing_secret = signing_secret  # Per-subscriber secret

    def dispatch(self, envelope: WebhookEnvelope, subscriber_url: str) -> WebhookDelivery:
        """
        Attempt delivery with up to MAX_ATTEMPTS retries.
        In production, each attempt would be a separate async job (Celery, SQS).
        Here shown synchronously for clarity.
        """
        delivery = WebhookDelivery(
            delivery_id=f"del_{uuid.uuid4().hex}",
            event_id=envelope.event_id,
            subscriber_url=subscriber_url,
            status=DeliveryStatus.PENDING,
        )

        payload_json = envelope.to_json()  # Serialize once; reuse across attempts
        signature = WebhookSigner.sign(payload_json, self.signing_secret)

        for attempt_num in range(1, WebhookDelivery.MAX_ATTEMPTS + 1):
            attempt = self._attempt_delivery(
                payload_json=payload_json,
                signature=signature,
                subscriber_url=subscriber_url,
                attempt_number=attempt_num,
            )
            delivery.attempts.append(attempt)

            if attempt.http_status and 200 <= attempt.http_status < 300:
                # HTTP 2xx = success; subscriber acknowledged the event
                delivery.status = DeliveryStatus.DELIVERED
                logger.info(
                    "Delivered event %s to %s on attempt %d",
                    envelope.event_id, subscriber_url, attempt_num
                )
                return delivery

            # Failed — schedule next retry if attempts remain
            if attempt_num < WebhookDelivery.MAX_ATTEMPTS:
                delay = WebhookDelivery.RETRY_DELAYS[attempt_num - 1]
                delivery.next_retry_at = time.time() + delay
                logger.warning(
                    "Delivery attempt %d failed (status=%s), retry in %ds",
                    attempt_num, attempt.http_status, delay
                )
                # In production: enqueue a delayed job instead of blocking sleep
                # celery_task.apply_async(countdown=delay)
                time.sleep(min(delay, 2))  # Shortened for demo — real code uses job queue

        # Exhausted all retries — move to dead letter queue
        delivery.status = DeliveryStatus.DEAD_LETTERED
        self._send_to_dead_letter_queue(delivery, envelope)
        return delivery

    def _attempt_delivery(
        self,
        payload_json: str,
        signature: str,
        subscriber_url: str,
        attempt_number: int,
    ) -> DeliveryAttempt:
        """Execute a single HTTP POST attempt and record the result."""
        start_time = time.time()
        http_status = None
        response_body = None
        error_message = None

        try:
            response = requests.post(
                url=subscriber_url,
                data=payload_json,           # Send raw JSON string, not dict
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": signature,
                    "X-Webhook-ID": f"attempt_{attempt_number}",
                    "User-Agent": "MyApp-Webhooks/1.0",  # Identify yourself
                },
                timeout=self.REQUEST_TIMEOUT_SECONDS,  # NEVER skip this timeout
            )
            http_status = response.status_code
            # Only capture first 500 chars — full bodies could be huge
            response_body = response.text[:500]
        except requests.Timeout:
            error_message = "Request timed out after 10s"
        except requests.ConnectionError as exc:
            error_message = f"Connection error: {exc}"
        except Exception as exc:
            error_message = f"Unexpected error: {exc}"

        duration_ms = (time.time() - start_time) * 1000

        return DeliveryAttempt(
            attempt_number=attempt_number,
            attempted_at=datetime.now(timezone.utc).isoformat(),
            http_status=http_status,
            response_body=response_body,
            error_message=error_message,
            duration_ms=round(duration_ms, 2),
        )

    def _send_to_dead_letter_queue(
        self, delivery: WebhookDelivery, envelope: WebhookEnvelope
    ) -> None:
        """
        Persist permanently failed deliveries for manual inspection/replay.
        In production: write to S3, DynamoDB, or a dedicated DLQ table.
        """
        logger.error(
            "DEAD LETTER: event=%s delivery=%s subscriber=%s after %d attempts",
            envelope.event_id,
            delivery.delivery_id,
            delivery.subscriber_url,
            len(delivery.attempts),
        )
        # Production: store in DLQ for operator review and optional manual replay
        # dead_letter_store.put(delivery_id=delivery.delivery_id, payload=envelope.to_json())


# =============================================================================
# SECTION 4 — IDEMPOTENCY: EVENT DEDUPLICATION
# =============================================================================
# WHY: The dispatcher WILL retry. Subscribers WILL receive duplicates.
#      Your handler must produce the same result if called multiple times
#      with the same event_id (idempotent = safe to repeat).

class IdempotencyStore:
    """
    Track which event_ids have already been processed.
    In production: backed by Redis or a database with TTL.
    """
    def __init__(self):
        # In-memory for demo; use Redis.set(event_id, "1", ex=86400) in prod
        self._seen: Set[str] = set()

    def is_duplicate(self, event_id: str) -> bool:
        """Return True if this event_id was already successfully processed."""
        return event_id in self._seen

    def mark_processed(self, event_id: str) -> None:
        """Record that event_id was successfully processed. Set TTL in Redis."""
        self._seen.add(event_id)
        # Production: redis.set(f"webhook:processed:{event_id}", "1", ex=86400)
        # 24-hour TTL — enough to catch all retries without unbounded growth


def idempotent_handler(envelope: WebhookEnvelope, store: IdempotencyStore) -> bool:
    """
    Template for an idempotent webhook handler.
    Check → Process → Mark pattern is safe even under concurrent delivery.
    For strict correctness under concurrency, use a DB transaction or Redis SET NX.
    """
    if store.is_duplicate(envelope.event_id):
        logger.info("Duplicate event %s — skipping", envelope.event_id)
        return True  # Return success so dispatcher does not retry again

    # Process the event here (update DB, trigger side effects, etc.)
    logger.info("Processing event %s of type %s", envelope.event_id, envelope.event_type)

    store.mark_processed(envelope.event_id)  # Mark AFTER successful processing
    # If your process step fails, event_id is NOT marked — dispatcher will retry
    return True


# =============================================================================
# SECTION 5 — FAN-OUT: ONE EVENT → MULTIPLE SUBSCRIBERS
# =============================================================================
# WHY: Multiple external systems (CRM, analytics, billing) may all need the
#      same event. Fan-out delivers to all of them independently so one slow
#      subscriber does not block others.

@dataclass
class Subscriber:
    """A registered webhook consumer."""
    subscriber_id: str
    url: str
    secret: str                        # Unique per subscriber for security
    event_types: List[str]             # Filter: only receive matching events
    active: bool = True
    failure_count: int = 0             # Track consecutive failures for auto-disable


class FanOutDispatcher:
    """
    Broadcasts one event to all subscribers that opted into that event_type.
    Each delivery is independent — subscriber A's failure does not affect B.
    """
    def __init__(self):
        self._subscribers: List[Subscriber] = []

    def register_subscriber(self, subscriber: Subscriber) -> None:
        self._subscribers.append(subscriber)

    def dispatch_event(self, envelope: WebhookEnvelope) -> Dict[str, DeliveryStatus]:
        """
        Fan out event to all matching subscribers.
        In production: spawn one async job per subscriber (Celery, Lambda, SQS).
        """
        results = {}
        # Filter to subscribers that want this event_type
        matching = [
            s for s in self._subscribers
            if s.active and (
                "*" in s.event_types or envelope.event_type in s.event_types
            )
        ]

        logger.info(
            "Fan-out: event=%s type=%s → %d subscribers",
            envelope.event_id, envelope.event_type, len(matching)
        )

        for subscriber in matching:
            # Each subscriber gets its OWN dispatcher with ITS OWN secret
            dispatcher = WebhookDispatcher(signing_secret=subscriber.secret)
            delivery = dispatcher.dispatch(envelope, subscriber.url)
            results[subscriber.subscriber_id] = delivery.status

            # Auto-disable subscribers with too many failures (circuit breaker)
            if delivery.status == DeliveryStatus.DEAD_LETTERED:
                subscriber.failure_count += 1
                if subscriber.failure_count >= 5:
                    subscriber.active = False
                    logger.warning("Auto-disabled subscriber %s", subscriber.subscriber_id)

        return results


# =============================================================================
# SECTION 6 — WEBHOOK REGISTRATION API
# =============================================================================
# Users register their endpoints via your API, receive a signing secret,
# and optionally filter which event types they care about.

class WebhookRegistry:
    """
    CRUD for subscriber registrations. In production: persist to a database.
    Expose via REST: POST /webhooks, GET /webhooks, DELETE /webhooks/{id}
    """
    def __init__(self):
        self._registrations: Dict[str, Subscriber] = {}

    def register(self, url: str, event_types: List[str]) -> Subscriber:
        """
        Register a new webhook endpoint.
        Returns the Subscriber including the signing secret (show ONCE, like SSH keys).
        """
        subscriber = Subscriber(
            subscriber_id=f"wh_{uuid.uuid4().hex[:12]}",
            url=url,
            secret=WebhookSigner.generate_secret(),  # Generated, never user-supplied
            event_types=event_types,
        )
        self._registrations[subscriber.subscriber_id] = subscriber
        logger.info("Registered webhook %s → %s", subscriber.subscriber_id, url)
        return subscriber

    def deactivate(self, subscriber_id: str) -> bool:
        """Soft-delete: deactivate rather than destroy (preserve audit trail)."""
        if subscriber_id in self._registrations:
            self._registrations[subscriber_id].active = False
            return True
        return False

    def list_active(self) -> List[Subscriber]:
        return [s for s in self._registrations.values() if s.active]


# =============================================================================
# SECTION 7 — CLOUDEVENTS SPEC
# =============================================================================
# CloudEvents is a CNCF standard that normalizes event envelopes across
# providers (AWS EventBridge, GCP Eventarc, Azure Event Grid, Kafka, etc.)
# Using it means integrators only learn one format instead of N proprietary ones.

def to_cloud_event(envelope: WebhookEnvelope, source: str) -> Dict[str, Any]:
    """
    Convert our internal envelope to CloudEvents 1.0 format.
    https://cloudevents.io/

    Mandatory attributes: specversion, id, source, type, datacontenttype
    """
    return {
        "specversion": "1.0",                 # Always "1.0" for CloudEvents v1
        "id": envelope.event_id,              # Globally unique (our evt_ id)
        "source": source,                     # URI of the event origin, e.g. "/payments"
        "type": f"com.myapp.{envelope.event_type}",  # Reverse-DNS prefix convention
        "datacontenttype": "application/json",
        "time": envelope.created_at,          # RFC3339 timestamp
        "dataschema": f"https://myapp.com/schemas/{envelope.event_type}.json",
        "data": envelope.data,                # Business payload unchanged
    }


# =============================================================================
# SECTION 8 — EVENT CATALOG / SCHEMA REGISTRY
# =============================================================================
# Document every event type so subscribers know what to expect.
# In production: host as OpenAPI-style YAML or AsyncAPI spec.

EVENT_CATALOG = {
    "payment.succeeded": {
        "description": "Fired when a payment is successfully captured",
        "schema": {
            "payment_id": "string",
            "amount_cents": "integer",
            "currency": "string (ISO 4217)",
            "customer_id": "string",
        },
        "example": {
            "payment_id": "pay_abc123",
            "amount_cents": 9900,
            "currency": "USD",
            "customer_id": "cus_xyz789",
        },
    },
    "user.deleted": {
        "description": "Fired when a user account is permanently deleted (GDPR)",
        "schema": {
            "user_id": "string",
            "deleted_at": "ISO-8601 datetime",
            "reason": "string enum: user_request | admin | policy_violation",
        },
        "example": {
            "user_id": "usr_111",
            "deleted_at": "2024-06-01T12:00:00Z",
            "reason": "user_request",
        },
    },
}


# =============================================================================
# SECTION 9 — DECISION MATRIX: WEBHOOK vs POLLING vs SSE vs WEBSOCKET
# =============================================================================
#
# | Criterion            | Polling        | Webhook        | SSE            | WebSocket      |
# |----------------------|----------------|----------------|----------------|----------------|
# | Direction            | Client pulls   | Server pushes  | Server pushes  | Bidirectional  |
# | Latency              | High (interval)| Low (~seconds) | Low (~ms)      | Very low (~ms) |
# | Infrastructure       | Simple         | Needs public URL| Simple         | Complex        |
# | Firewall friendly    | Yes            | Needs inbound  | Yes            | Sometimes not  |
# | Ordering guaranteed  | No             | No             | Yes (stream)   | Yes (stream)   |
# | Fan-out              | N/A            | Easy           | Per-connection | Per-connection |
# | Reconnection         | Inherent       | Must retry     | Built-in       | Manual         |
# | Use case             | Simple APIs    | B2B integration| Live dashboards| Chat/gaming    |
#
# CHOOSE WEBHOOK WHEN:
#   - Consumer is another server (not a browser)
#   - Events are infrequent but must be acted on promptly
#   - You need delivery guarantees (retry + DLQ)
#   - Consumers are external (you can't open a WebSocket to their infra)
#
# CHOOSE POLLING WHEN:
#   - Consumer cannot expose a public URL (behind NAT/firewall)
#   - Events are bulk and latency tolerance is high (nightly reports)
#
# CHOOSE SSE WHEN:
#   - Streaming live updates to browsers (charts, feeds, notifications)
#   - Unidirectional server→client is sufficient
#
# CHOOSE WEBSOCKET WHEN:
#   - You need low-latency bidirectional communication (chat, collaborative editing)
#   - Both sides send messages (not just server pushing)


# =============================================================================
# SECTION 10 — DEMONSTRATION
# =============================================================================

def run_demo():
    """End-to-end demonstration of the webhook system."""
    print("=== Webhook System Demo ===\n")

    # 1. Create an event envelope
    envelope = WebhookEnvelope.create(
        event_type="payment.succeeded",
        data={"payment_id": "pay_demo123", "amount_cents": 4999, "currency": "USD"},
        object_type="payment",
        object_id="pay_demo123",
    )
    print(f"Created envelope: {envelope.event_id}")
    print(f"Payload JSON:\n{envelope.to_json()}\n")

    # 2. Sign it
    secret = WebhookSigner.generate_secret()
    signature = WebhookSigner.sign(envelope.to_json(), secret)
    print(f"Signature: {signature[:40]}...\n")

    # 3. Verify it
    valid = WebhookSigner.verify(envelope.to_json(), secret, signature)
    print(f"Signature valid: {valid}")

    # Tamper test — change the payload, signature should fail
    tampered = envelope.to_json().replace("4999", "1")
    invalid = WebhookSigner.verify(tampered, secret, signature)
    print(f"Tampered signature valid: {invalid}\n")  # Should be False

    # 4. Idempotency check
    store = IdempotencyStore()
    idempotent_handler(envelope, store)  # First call — processes
    idempotent_handler(envelope, store)  # Second call — skipped (duplicate)

    # 5. Registry
    registry = WebhookRegistry()
    sub = registry.register("https://example.com/hooks", ["payment.*", "user.deleted"])
    print(f"\nRegistered: {sub.subscriber_id}")
    print(f"Secret (show once): {sub.secret[:16]}...")

    # 6. CloudEvents format
    cloud_event = to_cloud_event(envelope, source="/api/payments")
    print(f"\nCloudEvent type: {cloud_event['type']}")


if __name__ == "__main__":
    run_demo()
