# =============================================================================
# WHAT: Logging Best Practices — structured logging, JSON format, Python logging
#       module internals, structlog, correlation IDs, log aggregation, sampling,
#       PII avoidance, retention policies, contextvars, Fluentd/Filebeat.
# WHY:  Logs are the primary debugging tool when metrics alert you to a problem.
#       Unstructured logs are unsearchable at scale. Structured JSON logs enable
#       Elasticsearch queries, Loki LogQL, and automated alerting on log patterns.
# LEVEL: Intermediate — assumes Python familiarity; production context.
# =============================================================================

# ── CONCEPT OVERVIEW ─────────────────────────────────────────────────────────
#
# UNSTRUCTURED vs STRUCTURED LOGGING
#
#   Unstructured (bad at scale):
#     "2026-01-15 10:23:41 ERROR Failed to process order 12345 for user 67890"
#     → To extract order_id, you need fragile regex. Impossible to aggregate.
#
#   Structured JSON (good):
#     {"timestamp":"2026-01-15T10:23:41Z","level":"error","event":"order_failed",
#      "order_id":"12345","user_id":"67890","latency_ms":142,"service":"orders"}
#     → Every field is directly queryable. No parsing needed by log aggregators.
#
# LOG AGGREGATION STACKS
#   ELK Stack: Filebeat → Logstash → Elasticsearch → Kibana
#     Best for: complex transformation, search-heavy workloads, full-text search
#   PLG Stack: Promtail/Fluentd → Loki → Grafana
#     Best for: Prometheus shops, label-based filtering, cheaper storage
#     Loki indexes only labels, not content → much cheaper than Elasticsearch
#
# ── PRODUCTION USE CASE ──────────────────────────────────────────────────────
#   A checkout API processes 50,000 orders/hour. Every request logs a JSON
#   object with correlation_id, user_id (hashed), order_id, latency, and
#   payment_provider response code. When a spike in payment failures occurs,
#   the on-call engineer queries Kibana/Loki by correlation_id to trace the
#   exact sequence of events across 6 microservices in under 2 minutes.
#
# ── COMMON MISTAKES ──────────────────────────────────────────────────────────
#   1. Logging PII (names, emails, credit card numbers, SSNs) → GDPR/CCPA risk
#   2. Logging secrets (API keys, passwords, tokens) → security breach
#   3. Using print() instead of logging → no levels, no handlers, no context
#   4. Not using structured format → regex-based parsing breaks on edge cases
#   5. Over-logging at DEBUG in production → disk/storage cost, noise
#   6. Under-logging → can't reconstruct what happened after an incident
#   7. Not propagating correlation IDs → impossible to trace a request across services
#   8. Logging inside tight loops (e.g., per item in a 1M-row batch) → I/O bottleneck
# =============================================================================

import logging
import logging.handlers
import json
import sys
import uuid
import time
import hashlib
import random
from contextvars import ContextVar
from typing import Optional, Any, Dict
from functools import wraps
from datetime import datetime, timezone

# structlog: structured logging library that wraps the standard logging module
# pip install structlog
import structlog

# python-json-logger: makes standard logging emit JSON
# pip install python-json-logger
from pythonjsonlogger import jsonlogger


# =============================================================================
# SECTION 1: LOG LEVELS — when to use each
# =============================================================================
#
# Python log levels (numeric values, higher = more severe):
#   DEBUG    (10): Detailed diagnostic info. Only in development/troubleshooting.
#                  "Entering function X with args Y"
#                  "Cache hit for key user:1234"
#                  "SQL query: SELECT * FROM orders WHERE ..."
#
#   INFO     (20): Confirmation that things work normally. Operational events.
#                  "Server started on port 8080"
#                  "User 1234 logged in"
#                  "Order #5678 created successfully"
#                  "Scheduled job started: daily_report"
#
#   WARNING  (30): Something unexpected happened, but the service recovered.
#                  "Retry 2/3 for payment provider X"
#                  "Cache miss rate above 80% — check Redis"
#                  "Config value X not set, using default Y"
#                  "Deprecated API endpoint called"
#
#   ERROR    (40): An operation failed. Service is partially impaired.
#                  "Failed to charge order #5678: gateway timeout"
#                  "Database connection lost, reconnecting"
#                  "Failed to send email to user after 3 retries"
#                  Always include exception info: logger.error("...", exc_info=True)
#
#   CRITICAL (50): Service cannot function. Immediate human attention required.
#                  "Cannot connect to primary database after 10 retries"
#                  "Disk full — unable to write logs"
#                  "Configuration missing required key SECRET_KEY"
#                  (Usually triggers an alert directly, not just logging)
#
# PRODUCTION CONVENTION:
#   - Set root logger to WARNING or INFO in production
#   - Set specific loggers to DEBUG only during incidents via feature flags
#   - Never leave DEBUG globally on in production (too verbose, too expensive)


# =============================================================================
# SECTION 2: STANDARD PYTHON LOGGING MODULE ARCHITECTURE
# =============================================================================
#
# Logger hierarchy: root → "myapp" → "myapp.orders" → "myapp.orders.payment"
#   Child loggers propagate to parent by default (propagate=True).
#   If root logger has a handler, all child loggers also use it unless overridden.
#
# Key objects:
#   Logger    → what you call in code (logger.info, logger.error)
#   Handler   → where logs go (StreamHandler=stdout, FileHandler=file, etc.)
#   Formatter → how log records are formatted (plain text or JSON)
#   Filter    → conditionally suppress or enrich records


def setup_standard_logging() -> logging.Logger:
    """Configure standard Python logging with JSON output."""

    # Get (or create) a named logger — always use __name__ in modules
    # This creates "myapp.orders" which inherits from "myapp" which inherits from root
    logger = logging.getLogger("myapp.orders")
    logger.setLevel(logging.DEBUG)                  # logger accepts all levels

    # ── StreamHandler: write to stdout (preferred for containers/Kubernetes) ──
    # Containers log to stdout; the container runtime or log agent collects it.
    # Do NOT write to files in containers — logs get lost when container restarts.
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)           # handler filters to INFO+

    # ── JSON Formatter using python-json-logger ────────────────────────────
    # Fields: timestamp, level, name (logger name), message, plus any extra fields
    json_formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",              # ISO 8601 UTC timestamps
    )
    stream_handler.setFormatter(json_formatter)

    # ── RotatingFileHandler: keep last N files of max size (for non-container) ──
    # file_handler = logging.handlers.RotatingFileHandler(
    #     filename="/var/log/myapp/orders.log",
    #     maxBytes=100 * 1024 * 1024,               # 100 MB per file
    #     backupCount=5,                            # keep 5 rotated files
    #     encoding="utf-8",
    # )

    # ── TimedRotatingFileHandler: rotate daily, keep 30 days ──────────────────
    # timed_handler = logging.handlers.TimedRotatingFileHandler(
    #     filename="/var/log/myapp/orders.log",
    #     when="midnight",                          # rotate at midnight UTC
    #     interval=1,
    #     backupCount=30,                           # 30-day retention
    #     utc=True,
    # )

    logger.addHandler(stream_handler)
    logger.propagate = False                        # don't double-log to root

    return logger


# =============================================================================
# SECTION 3: CORRELATION IDs — linking logs across services
# =============================================================================
#
# A correlation ID (also called request ID, trace ID) is a unique identifier
# generated at the request boundary (API gateway or first service) and
# propagated to every downstream service via HTTP headers.
#
# Every log line for a single user request includes the same correlation_id,
# allowing you to reconstruct the full request timeline across all services.
#
# Standard headers used:
#   X-Request-ID        (common custom header)
#   X-Correlation-ID    (another common variant)
#   traceparent         (W3C TraceContext — also used by OpenTelemetry)
#
# Python contextvars: thread-safe, async-safe storage for request-scoped data.
# Unlike threading.local(), ContextVar works correctly with asyncio.

# Module-level ContextVar — each async task / thread has its own value
correlation_id_var: ContextVar[Optional[str]] = ContextVar(
    "correlation_id", default=None
)
user_id_var: ContextVar[Optional[str]] = ContextVar(
    "user_id", default=None
)


def get_correlation_id() -> str:
    """Get the current correlation ID, generating one if not set."""
    cid = correlation_id_var.get()
    if cid is None:
        cid = str(uuid.uuid4())                    # generate a new UUID v4
        correlation_id_var.set(cid)
    return cid


def set_request_context(correlation_id: str, user_id: Optional[str] = None):
    """Set request-scoped context at the beginning of each request handler."""
    correlation_id_var.set(correlation_id)
    if user_id:
        user_id_var.set(user_id)


# =============================================================================
# SECTION 4: CUSTOM LOGGING FILTER — inject correlation ID into every record
# =============================================================================
#
# A Filter can mutate log records before they reach handlers.
# This is the cleanest way to add correlation_id to every log line
# without passing it explicitly to every logger.info() call.

class CorrelationIDFilter(logging.Filter):
    """Injects correlation_id and user_id from context into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Attach context variables to the log record
        record.correlation_id = get_correlation_id()
        record.user_id = user_id_var.get() or "anonymous"
        record.service = "orders-service"          # static: name of this service
        record.environment = "production"          # could read from env var
        return True                                # True = don't suppress the record


# =============================================================================
# SECTION 5: STRUCTLOG — structured logging done right
# =============================================================================
#
# structlog processes log records as Python dicts until the final render step.
# This means you can add/remove/transform fields at any processing stage.
# It composites with the standard logging module (stdlib integration).

def configure_structlog():
    """Configure structlog for production JSON output."""

    structlog.configure(
        processors=[
            # Add log level name to the event dict
            structlog.stdlib.add_log_level,

            # Add logger name
            structlog.stdlib.add_logger_name,

            # Add ISO 8601 UTC timestamp
            structlog.processors.TimeStamper(fmt="iso", utc=True),

            # Render exception info as a structured dict (not a traceback string)
            structlog.processors.format_exc_info,

            # Add call site info (file, line number) — useful in development
            # structlog.processors.CallsiteParameterAdder(
            #     [structlog.processors.CallsiteParameter.FILENAME,
            #      structlog.processors.CallsiteParameter.LINENO]
            # ),

            # Inject correlation_id from ContextVar into every event
            _inject_context_processor,

            # Final step: render the event dict as a JSON string
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,  # use stdlib log levels
        context_class=dict,                          # store context as plain dict
        logger_factory=structlog.stdlib.LoggerFactory(),  # use stdlib under the hood
        cache_logger_on_first_use=True,              # performance: cache after first use
    )


def _inject_context_processor(logger, method, event_dict: Dict) -> Dict:
    """structlog processor: inject request context into every log event."""
    event_dict["correlation_id"] = get_correlation_id()
    event_dict["user_id"] = user_id_var.get() or "anonymous"
    event_dict["service"] = "orders-service"
    return event_dict


def get_structlog_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger with a bound name."""
    return structlog.get_logger(name)


# =============================================================================
# SECTION 6: PII AND SECRETS — what NOT to log
# =============================================================================
#
# NEVER LOG:
#   - Full credit card numbers (PCI DSS violation)
#   - CVV codes
#   - Social Security Numbers / National IDs
#   - Passwords (even hashed) — hash is also sensitive
#   - API keys, tokens, secret keys, private keys
#   - Full OAuth tokens or JWT payloads (may contain sensitive claims)
#   - Unmasked email addresses (GDPR/CCPA: email is PII)
#   - Full names + other identifiers combined (de-anonymization risk)
#   - Raw request/response bodies without scrubbing (may contain any of the above)
#
# SAFE ALTERNATIVES:
#   - User IDs (internal opaque IDs, not emails)
#   - Hashed user identifiers (for correlation without re-identification)
#   - Card last-4 digits only ("**** **** **** 4242")
#   - Redacted field markers: {"email": "[REDACTED]", "card": "****4242"}
#   - Boolean presence flags: {"has_payment_method": true}

def hash_pii(value: str) -> str:
    """One-way hash a PII value for safe logging (correlation without exposure)."""
    # SHA-256 is sufficient for log correlation — not for cryptographic purposes
    # Add a fixed salt from env var to prevent rainbow table attacks
    salt = "log_salt_change_me_in_production"
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:16]  # 16 chars enough


def sanitize_payment_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Scrub sensitive fields from a payment payload before logging."""
    safe = dict(data)                              # shallow copy, don't mutate original

    # Mask card number — keep last 4 digits only
    if "card_number" in safe:
        card = str(safe["card_number"])
        safe["card_number"] = f"****{card[-4:]}" if len(card) >= 4 else "****"

    # Remove CVV entirely — no partial masking, just delete it
    safe.pop("cvv", None)
    safe.pop("cvv2", None)
    safe.pop("cvc", None)

    # Hash email for correlation without exposure
    if "email" in safe:
        safe["email_hash"] = hash_pii(safe["email"])
        del safe["email"]                          # remove original email

    # Redact any field with "password", "secret", "token", "key" in its name
    for key in list(safe.keys()):
        if any(word in key.lower() for word in ["password", "secret", "token", "api_key"]):
            safe[key] = "[REDACTED]"

    return safe


# =============================================================================
# SECTION 7: LOG SAMPLING — managing high-volume services
# =============================================================================
#
# Problem: A service handling 100,000 req/s logging every request = 8.6 billion
#          log lines per day. Storage and indexing cost is prohibitive.
#
# Solution: Sample logs — only record a fraction of normal traffic.
#   - Log ALL errors (100% sampling for errors and warnings)
#   - Log ALL slow requests (latency > threshold)
#   - Sample INFO/DEBUG logs (1–10% for normal requests)
#   - Always log requests for specific users/orders (deterministic sampling)
#
# Sampling strategies:
#   1. Head-based (random):  decide at request start. Simple but loses rare errors.
#   2. Tail-based:           buffer first, decide after request completes.
#                            Log 100% of errors, 1% of successes. Needs infrastructure.
#   3. Deterministic:        hash(request_id) % 100 < rate. Same request always sampled.

class SamplingLogger:
    """Logger wrapper that applies sampling to reduce volume."""

    def __init__(self, base_logger: logging.Logger, sample_rate: float = 0.01):
        """
        Args:
            base_logger: The underlying Python logger.
            sample_rate: Fraction of INFO logs to actually emit (0.01 = 1%).
                         Errors and Warnings are always emitted.
        """
        self._logger = base_logger
        self._sample_rate = sample_rate

    def info(self, msg: str, **kwargs):
        """Log INFO only for sampled fraction of requests."""
        # Deterministic sampling: hash correlation_id so same request always sampled
        cid = get_correlation_id()
        sample_bucket = int(hashlib.md5(cid.encode()).hexdigest(), 16) % 100
        threshold = int(self._sample_rate * 100)

        if sample_bucket < threshold:              # only log if within sample rate
            self._logger.info(msg, extra=kwargs)

    def warning(self, msg: str, **kwargs):
        """Always log warnings — never sample them away."""
        self._logger.warning(msg, extra=kwargs)

    def error(self, msg: str, **kwargs):
        """Always log errors — never sample them away."""
        self._logger.error(msg, extra=kwargs, exc_info=True)

    def critical(self, msg: str, **kwargs):
        """Always log critical — never sample them away."""
        self._logger.critical(msg, extra=kwargs, exc_info=True)


# =============================================================================
# SECTION 8: CONTEXTUAL LOGGING — bound loggers with request context
# =============================================================================
#
# Pattern: bind context at request start, use the bound logger throughout.
# This avoids passing correlation_id explicitly to every function call.

def process_order(order_id: str, user_id: str) -> Dict[str, Any]:
    """Example function showing contextual logging with structlog bound logger."""

    # Generate or inherit correlation ID from HTTP header (simulated here)
    correlation_id = str(uuid.uuid4())
    set_request_context(correlation_id=correlation_id, user_id=hash_pii(user_id))

    # Bind context to logger — all subsequent log calls include these fields
    log = structlog.get_logger("orders").bind(
        correlation_id=correlation_id,
        order_id=order_id,
        user_id_hash=hash_pii(user_id),           # safe to log: hashed
    )

    log.info("order_processing_started")          # event name as first arg, not f-string

    start_time = time.time()

    try:
        # Simulate order validation
        log.debug("order_validation_started", items_count=3)
        time.sleep(0.01)                          # simulated validation
        log.debug("order_validation_completed", validation_ms=10)

        # Simulate payment processing
        log.info("payment_processing_started", payment_provider="stripe")
        time.sleep(0.05)                          # simulated payment

        if random.random() < 0.1:                 # 10% payment failure
            raise ConnectionError("Stripe gateway timeout")

        log.info(
            "payment_processing_completed",
            payment_provider="stripe",
            amount_cents=9999,
            currency="USD",
        )

        duration_ms = (time.time() - start_time) * 1000

        # Log the final event with all relevant fields — one comprehensive log line
        log.info(
            "order_processing_completed",
            duration_ms=round(duration_ms, 2),
            status="success",
        )

        return {"order_id": order_id, "status": "created"}

    except ConnectionError as e:
        duration_ms = (time.time() - start_time) * 1000

        # Log with exc_info — structlog captures exception automatically
        log.error(
            "order_processing_failed",
            duration_ms=round(duration_ms, 2),
            error=str(e),                         # error message (no PII here)
            error_type=type(e).__name__,
            payment_provider="stripe",
            exc_info=True,                        # include full traceback in JSON
        )
        raise


# =============================================================================
# SECTION 9: LOG AGGREGATION — Fluentd and Filebeat config concepts
# =============================================================================
#
# Fluentd / Fluent Bit (log shipper):
#   - Reads logs from files, containers, or stdin
#   - Parses, transforms, buffers, and forwards to destinations
#   - Common destinations: Elasticsearch, Loki, S3, Datadog, Splunk
#
# Filebeat (Elastic's lightweight log shipper):
#   - Monitors files/directories for new log lines
#   - Ships to Logstash or directly to Elasticsearch
#   - Very low CPU/memory footprint
#
# Kubernetes log collection pattern:
#   Each node runs a Fluentd/Fluent Bit DaemonSet.
#   Reads /var/log/containers/*.log (container stdout/stderr).
#   Enriches with Kubernetes metadata (pod name, namespace, labels).
#   Ships to centralized Elasticsearch/Loki cluster.

FLUENTD_CONFIG_EXAMPLE = """
# fluent.conf — ship JSON logs from /var/log/app to Elasticsearch

<source>
  @type tail
  path /var/log/app/*.log
  pos_file /var/log/td-agent/app.log.pos   # tracks position to resume after restart
  tag app.orders
  <parse>
    @type json                              # parse each line as JSON
    time_key timestamp                     # which field is the timestamp
    time_format %Y-%m-%dT%H:%M:%SZ
  </parse>
</source>

# Add Kubernetes metadata (when running as DaemonSet)
<filter app.**>
  @type record_transformer
  <record>
    hostname ${hostname}
    environment production
  </record>
</filter>

# Sample: only send 10% of DEBUG-level logs
<filter app.**>
  @type grep
  <exclude>
    key level
    pattern /^debug$/
  </exclude>
</filter>

<match app.**>
  @type elasticsearch
  host elasticsearch.logging.svc.cluster.local
  port 9200
  index_name app-logs-%Y.%m.%d   # daily index rotation
  <buffer>
    @type file
    path /var/log/fluentd-buffers/app
    flush_interval 5s              # send every 5 seconds
    retry_max_times 10
    chunk_limit_size 8MB
  </buffer>
</match>
"""

# LOG RETENTION POLICIES
# How long to keep logs (balance cost vs. compliance requirements):
#
#   DEBUG logs:     1–3 days   (high volume, low value long-term)
#   INFO logs:      7–30 days  (operational; enough for recent incidents)
#   WARNING logs:   90 days    (anomalies; useful for trend analysis)
#   ERROR logs:     1 year     (incident investigation, compliance)
#   CRITICAL logs:  7 years    (compliance, audit trails — check your jurisdiction)
#   Security/auth:  7 years    (SOC2, PCI DSS, HIPAA may require longer)
#
# Implementation options:
#   Elasticsearch ILM (Index Lifecycle Management): auto-delete old indices
#   Loki compactor: configured retention per label/stream
#   S3 lifecycle rules: move to Glacier after 30 days, delete after 365


# =============================================================================
# SECTION 10: LOGGING DECORATOR — automatic function entry/exit logging
# =============================================================================

def log_execution(logger_name: str = "myapp", level: str = "debug"):
    """
    Decorator that logs function entry, exit, duration, and exceptions.
    Use sparingly — adds noise. Best for critical business operations.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            log = structlog.get_logger(logger_name)

            # Sanitize kwargs to avoid logging secrets passed as keyword args
            safe_kwargs = {
                k: "[REDACTED]" if any(word in k.lower()
                    for word in ["password", "secret", "token", "key"])
                else v
                for k, v in kwargs.items()
            }

            log.debug(
                f"{func.__name__}_started",
                function=func.__name__,
                kwargs=safe_kwargs,
            )

            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed_ms = (time.perf_counter() - start) * 1000

                log.debug(
                    f"{func.__name__}_completed",
                    function=func.__name__,
                    duration_ms=round(elapsed_ms, 2),
                )
                return result

            except Exception as e:
                elapsed_ms = (time.perf_counter() - start) * 1000

                log.error(
                    f"{func.__name__}_failed",
                    function=func.__name__,
                    duration_ms=round(elapsed_ms, 2),
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True,
                )
                raise

        return wrapper
    return decorator


@log_execution(logger_name="myapp.payment", level="info")
def charge_payment(order_id: str, amount_cents: int) -> Dict[str, Any]:
    """Simulate a payment charge — decorated with logging."""
    time.sleep(0.02)                              # simulated Stripe API call
    return {"charge_id": "ch_abc123", "status": "succeeded"}


# =============================================================================
# SECTION 11: WHAT GOOD STRUCTURED LOGS LOOK LIKE
# =============================================================================

GOOD_LOG_EXAMPLES = [
    # INFO: request completed
    {
        "timestamp": "2026-01-15T10:23:41Z",
        "level": "info",
        "event": "http_request_completed",
        "service": "orders-api",
        "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
        "method": "POST",
        "path": "/api/v1/orders",
        "status_code": 201,
        "duration_ms": 142.3,
        "user_id_hash": "a4f82b3c1d9e",         # hashed, not raw
        "order_id": "ord_789xyz",
    },

    # ERROR: downstream failure with full context
    {
        "timestamp": "2026-01-15T10:23:45Z",
        "level": "error",
        "event": "payment_provider_failure",
        "service": "orders-api",
        "correlation_id": "550e8400-e29b-41d4-a716-446655440001",
        "order_id": "ord_790abc",
        "payment_provider": "stripe",
        "error_type": "ConnectionError",
        "error": "Gateway timeout after 30s",
        "attempt": 2,
        "max_attempts": 3,
        "exc_info": "Traceback (most recent call last):\n  ...",
    },

    # WARNING: degraded state, not failure
    {
        "timestamp": "2026-01-15T10:24:00Z",
        "level": "warning",
        "event": "cache_miss_rate_high",
        "service": "orders-api",
        "cache_name": "product_catalog",
        "miss_rate_pct": 87.3,                   # current miss rate
        "threshold_pct": 50.0,                   # what triggered the warning
        "recommendation": "Check Redis connection pool or increase cache TTL",
    },
]


# =============================================================================
# SECTION 12: DEMONSTRATION
# =============================================================================

def main():
    """Run demonstrations of all logging patterns."""
    print("=== Standard Python Logging ===")
    logger = setup_standard_logging()
    logger.info("Service started", extra={"port": 8080, "env": "production"})
    logger.warning("Config missing, using default", extra={"key": "TIMEOUT_MS", "default": 5000})

    print("\n=== structlog Demo ===")
    configure_structlog()
    set_request_context(correlation_id=str(uuid.uuid4()), user_id="user_42")

    try:
        result = process_order(order_id="ord_001", user_id="user_42")
        print(f"Order result: {result}")
    except Exception as e:
        print(f"Order failed (expected in demo): {e}")

    print("\n=== PII Sanitization ===")
    raw_payment = {
        "card_number": "4111111111111111",
        "cvv": "123",
        "email": "john.doe@example.com",
        "amount": 9999,
        "api_key": "sk_live_super_secret",
    }
    safe_payment = sanitize_payment_data(raw_payment)
    print(f"Safe to log: {json.dumps(safe_payment, indent=2)}")

    print("\n=== Decorated Function ===")
    try:
        charge_payment(order_id="ord_001", amount_cents=9999)
    except Exception:
        pass


if __name__ == "__main__":
    main()
