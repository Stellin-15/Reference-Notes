# ============================================================
# L01: Observability Fundamentals
# ============================================================
# WHAT: The three pillars of observability (logs, metrics, traces),
#       four golden signals, SLI/SLO/SLA framework, error budgets,
#       high cardinality, and request correlation.
# WHY:  You cannot fix what you cannot see. Observability lets you
#       understand the internal state of a system from its external
#       outputs — essential for debugging distributed systems where
#       no single engineer can hold the whole state in their head.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    Observability is the property of a system that makes it possible
    to understand its internal state by examining its outputs.
    The three pillars are complementary — you need all three:

    LOGS    → What happened and when? Contextual, structured events.
              Queryable but expensive at high volume.

    METRICS → How is the system performing right now and over time?
              Numeric, aggregatable, cheap to store, cheap to query.
              Cannot tell you WHY, only THAT something is wrong.

    TRACES  → Where did this request spend its time?
              Request flow across services. Expensive to collect,
              sample to manage volume.

PRODUCTION USE CASE:
    P99 latency spike alert fires at 2am.
    1. Metrics: latency histogram shows spike in /checkout endpoint
    2. Logs: filter by time window + endpoint → find "DB timeout" errors
    3. Traces: find a trace_id from the logs → see full request breakdown
       → DB query "SELECT * FROM inventory" taking 8s (missing index)
    Without all three pillars: step would be impossible or take hours.

COMMON MISTAKES:
    1. Monitoring ≠ Observability — monitoring watches KNOWN failure modes.
       Observability lets you debug UNKNOWN failures from first principles.
    2. Alerting on causes (CPU 80%) instead of symptoms (error rate 1%)
       → too many alerts, low signal-to-noise ratio → alert fatigue
    3. Not propagating request_id across service boundaries
       → impossible to trace a request end-to-end
    4. Logging at DEBUG level in production → log volume overwhelms storage
    5. Not distinguishing success latency from error latency in SLIs
       (errors complete fast — including them deflates P99 artifically)
    6. No runbooks for alerts → on-call doesn't know what to do at 2am
"""

import json
import time
import uuid
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from contextvars import ContextVar


# ============================================================
# SECTION 1: THE THREE PILLARS
# ============================================================

# ---- PILLAR 1: STRUCTURED LOGS ----
# Logs answer: "What happened, in what context?"
# Key properties:
#   - Structured (JSON) — not free-form text. Queryable.
#   - Every log line has: timestamp, level, service, request_id, message
#   - Include business context: user_id, order_id, endpoint
#   - Include correlation: trace_id, span_id (link to traces)
#
# Log levels and when to use each:
#   DEBUG   : verbose internal state (NEVER in production by default)
#   INFO    : normal significant events (request received, payment processed)
#   WARNING : unexpected but recoverable (retry attempt, deprecated API used)
#   ERROR   : failure requiring attention (DB query failed, 3rd party timeout)
#   CRITICAL: system-level failure requiring immediate response

# Context variable for request correlation — propagates through async calls
request_context: ContextVar[dict] = ContextVar('request_context', default={})


class StructuredLogger:
    """
    Wrapper around Python's logging that enforces structured JSON output.
    In production: use structlog or python-json-logger library.
    Key: every log line is a JSON object — parseable by Datadog, Loki, CloudWatch.
    """

    def __init__(self, service_name: str):
        self._service = service_name
        # Configure underlying logger
        self._logger = logging.getLogger(service_name)
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(handler)
        self._logger.setLevel(logging.DEBUG)

    def _build_entry(self, level: str, message: str, **kwargs) -> dict:
        """
        Build a structured log entry.
        Always includes: timestamp, level, service, request correlation.
        Caller adds: message + any context fields.
        """
        ctx = request_context.get({})
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": level,
            "service": self._service,
            "message": message,
            # Correlation fields — ALWAYS include if available
            "request_id": ctx.get("request_id"),
            "trace_id": ctx.get("trace_id"),
            "span_id": ctx.get("span_id"),
            "user_id": ctx.get("user_id"),
        }
        # Remove None values (cleaner JSON, smaller payload)
        entry = {k: v for k, v in entry.items() if v is not None}
        # Merge caller-provided fields
        entry.update(kwargs)
        return entry

    def info(self, message: str, **kwargs):
        entry = self._build_entry("INFO", message, **kwargs)
        self._logger.info(json.dumps(entry))

    def warning(self, message: str, **kwargs):
        entry = self._build_entry("WARNING", message, **kwargs)
        self._logger.warning(json.dumps(entry))

    def error(self, message: str, **kwargs):
        entry = self._build_entry("ERROR", message, **kwargs)
        self._logger.error(json.dumps(entry))

    def debug(self, message: str, **kwargs):
        # Only emit debug if debug mode is enabled (env var or config)
        entry = self._build_entry("DEBUG", message, **kwargs)
        self._logger.debug(json.dumps(entry))


# Example: what a structured log entry looks like
EXAMPLE_LOG_ENTRIES = [
    # Request received
    {
        "timestamp": "2024-01-15T14:23:45.123Z",
        "level": "INFO",
        "service": "checkout-service",
        "message": "Request received",
        "request_id": "req_7f3a9b2c",      # ties together all logs in one request
        "trace_id": "4bf92f3577b34da6",     # ties together traces + logs
        "span_id": "00f067aa0ba902b7",
        "user_id": "user_abc123",
        "method": "POST",
        "path": "/api/checkout",
        "remote_ip": "10.0.1.45",
    },
    # Business event — what happened
    {
        "timestamp": "2024-01-15T14:23:45.890Z",
        "level": "INFO",
        "service": "checkout-service",
        "message": "Payment processed",
        "request_id": "req_7f3a9b2c",
        "trace_id": "4bf92f3577b34da6",
        "user_id": "user_abc123",
        "order_id": "ord_9871",
        "amount_cents": 4999,
        "currency": "USD",
        "payment_provider": "stripe",
        "stripe_charge_id": "ch_3OXxx",
        "duration_ms": 342,
    },
    # Error with context
    {
        "timestamp": "2024-01-15T14:23:46.200Z",
        "level": "ERROR",
        "service": "inventory-service",
        "message": "DB query timeout",
        "request_id": "req_7f3a9b2c",
        "trace_id": "4bf92f3577b34da6",
        "query": "SELECT * FROM inventory WHERE product_id = ?",
        "duration_ms": 5001,
        "db_host": "postgres-primary.internal",
        "error_type": "QueryTimeout",
        "stack_trace": "...",  # only on ERROR and above
    },
]


# ---- PILLAR 2: METRICS ----
# See L02 for full Prometheus details. Overview here.
#
# Metrics answer: "Is the system behaving normally right now?"
# Key properties:
#   - Numeric: counters, gauges, histograms, summaries
#   - Aggregatable: sum across instances, avg over time
#   - Low cardinality: labels must have bounded values
#   - Time-series: values indexed by timestamp
#
# What NOT to do with metrics:
#   - Never label with user_id, request_id, URL path with IDs
#   - These create millions of time series → Prometheus OOM
#   - Use logs/traces for high-cardinality filtering

class MetricType(Enum):
    COUNTER   = "counter"    # monotonically increasing (requests_total)
    GAUGE     = "gauge"      # can go up or down (active_connections)
    HISTOGRAM = "histogram"  # observe distribution (request_duration)
    SUMMARY   = "summary"    # client-side quantiles (avoid — not aggregatable)


@dataclass
class MetricDefinition:
    """Documents what metric to collect and why."""
    name: str
    type: MetricType
    description: str
    labels: list[str]       # MUST be low-cardinality
    unit: str
    alert_threshold: Optional[str]


# Standard metrics every REST API service should expose
REST_API_METRICS: list[MetricDefinition] = [
    MetricDefinition(
        name="http_requests_total",
        type=MetricType.COUNTER,
        description="Total HTTP requests received",
        labels=["method", "endpoint", "status_code"],
        unit="requests",
        alert_threshold="rate > 5% errors",
    ),
    MetricDefinition(
        name="http_request_duration_seconds",
        type=MetricType.HISTOGRAM,
        description="HTTP request duration in seconds",
        labels=["method", "endpoint"],
        unit="seconds",
        # Histogram buckets: 1ms, 5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 5s
        alert_threshold="P99 > 0.2s",
    ),
    MetricDefinition(
        name="http_active_requests",
        type=MetricType.GAUGE,
        description="Currently processing requests",
        labels=["endpoint"],
        unit="requests",
        alert_threshold="per endpoint > 1000",
    ),
    MetricDefinition(
        name="db_pool_connections_active",
        type=MetricType.GAUGE,
        description="Active DB connections in pool",
        labels=["pool_name"],
        unit="connections",
        alert_threshold="> 80% of pool_size",
    ),
    MetricDefinition(
        name="cache_hit_total",
        type=MetricType.COUNTER,
        description="Cache hits (use rate() for hit rate)",
        labels=["cache_name", "result"],  # result: hit | miss
        unit="operations",
        alert_threshold="hit rate < 70%",
    ),
    MetricDefinition(
        name="queue_depth",
        type=MetricType.GAUGE,
        description="Messages waiting in queue",
        labels=["queue_name"],
        unit="messages",
        alert_threshold="> 10000 for > 5 minutes",
    ),
]


# ---- PILLAR 3: TRACES ----
# See L03 for full OpenTelemetry details. Overview here.
#
# Traces answer: "Where in the system did this request spend time?"
# Key properties:
#   - Trace = tree of spans across services
#   - Span = one unit of work (start/end time, service, operation)
#   - Context propagation: trace_id passes in HTTP headers across services
#
# Trace sampling: can't record every trace at scale
#   - 1% sampling at 10K req/s = 100 traces/s — plenty for analysis
#   - Always sample: error responses, slow requests (> P99)
#   - Never sample: health check endpoints

EXAMPLE_TRACE = {
    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
    "spans": [
        {
            "span_id": "00f067aa0ba902b7",
            "parent_span_id": None,          # root span
            "service": "api-gateway",
            "operation": "POST /checkout",
            "start_time": "2024-01-15T14:23:45.100Z",
            "end_time": "2024-01-15T14:23:46.350Z",
            "duration_ms": 1250,
            "status": "OK",
            "attributes": {
                "http.method": "POST",
                "http.url": "/checkout",
                "http.status_code": 200,
                "user.id": "user_abc123",
            }
        },
        {
            "span_id": "a2fb4a1d1a96d312",
            "parent_span_id": "00f067aa0ba902b7",  # child of root
            "service": "checkout-service",
            "operation": "validate_cart",
            "start_time": "2024-01-15T14:23:45.200Z",
            "end_time": "2024-01-15T14:23:45.350Z",
            "duration_ms": 150,
            "status": "OK",
        },
        {
            "span_id": "b9c7a1e2d5f08934",
            "parent_span_id": "00f067aa0ba902b7",
            "service": "inventory-service",
            "operation": "check_stock",
            "start_time": "2024-01-15T14:23:45.360Z",
            "end_time": "2024-01-15T14:23:46.362Z",  # <- THE SLOW PART
            "duration_ms": 1002,                      # DB query timeout!
            "status": "ERROR",
            "attributes": {
                "db.statement": "SELECT * FROM inventory WHERE product_id = ?",
                "db.type": "postgresql",
                "error.message": "Query timeout after 1000ms",
            }
        },
    ]
}


# ============================================================
# SECTION 2: FOUR GOLDEN SIGNALS
# ============================================================
# Google SRE book: any service can be monitored with 4 signals.
# These cover the user experience completely.
# Alert on these signals, not on infrastructure metrics.

@dataclass
class GoldenSignal:
    """Definition of a golden signal for a service."""
    name: str
    description: str
    metric_name: str
    promql: str          # How to compute from raw metrics
    alert_condition: str
    notes: str


FOUR_GOLDEN_SIGNALS = [
    GoldenSignal(
        name="Latency",
        description="Time to serve a request. CRITICAL: track success and error separately. "
                    "Errors that fail fast (5ms 500 response) can inflate your success P99 "
                    "by masking the actual slow requests you should be optimizing.",
        metric_name="http_request_duration_seconds",
        promql="""
            # P99 latency for successful requests only
            histogram_quantile(0.99,
                sum(rate(http_request_duration_seconds_bucket{status_code!~"5.."}[5m]))
                by (le, endpoint)
            )
        """,
        alert_condition="P99 > 200ms for > 5 minutes",
        notes="Separate SLOs per endpoint if they have very different latency profiles.",
    ),
    GoldenSignal(
        name="Traffic",
        description="How much demand is on the system. QPS, requests/s, "
                    "messages/s for queues. Used to: detect traffic spikes, "
                    "capacity planning, correlate with latency changes.",
        metric_name="http_requests_total",
        promql="""
            # Requests per second by endpoint
            sum(rate(http_requests_total[5m])) by (endpoint)
        """,
        alert_condition="QPS drops to 0 (service is down) or spike > 10x baseline",
        notes="Low traffic alert is often more important than high traffic.",
    ),
    GoldenSignal(
        name="Errors",
        description="Rate of requests that fail. Include: HTTP 5xx, HTTP 4xx "
                    "(for business logic errors like failed payments), timeouts, "
                    "and internal business errors (even if returned as 200 OK).",
        metric_name="http_requests_total",
        promql="""
            # Error rate as fraction of total traffic
            sum(rate(http_requests_total{status_code=~"5.."}[5m]))
            /
            sum(rate(http_requests_total[5m]))
        """,
        alert_condition="Error rate > 1% for > 2 minutes",
        notes="5xx = server errors (your fault). 4xx = client errors (usually not your fault, "
              "except 429 rate limit which may indicate abuse or misconfiguration).",
    ),
    GoldenSignal(
        name="Saturation",
        description="How full is the service? CPU%, memory%, queue depth, "
                    "DB connection pool utilization. Saturation predicts future "
                    "problems: 80% CPU is a warning, 95% means trouble soon.",
        metric_name="Various (cpu_usage, memory_bytes, db_pool_active, queue_depth)",
        promql="""
            # DB connection pool saturation (%)
            db_pool_connections_active / db_pool_connections_max * 100

            # Queue saturation: how many minutes of backlog?
            queue_depth / rate(queue_messages_consumed_total[5m]) / 60
        """,
        alert_condition="DB pool > 80% utilized. Queue depth growing for > 10 minutes.",
        notes="Saturation metrics are leading indicators — they warn before user impact.",
    ),
]


# ============================================================
# SECTION 3: SLI / SLO / SLA FRAMEWORK
# ============================================================

class SLIType(Enum):
    AVAILABILITY = "availability"   # fraction of successful requests
    LATENCY      = "latency"        # fraction of requests within threshold
    THROUGHPUT   = "throughput"     # requests processed per time unit
    CORRECTNESS  = "correctness"    # fraction of correct responses


@dataclass
class SLI:
    """
    Service Level Indicator: actual measured value.
    SLI = good_events / total_events over a time window.

    Good event definition is CRITICAL to get right:
      - Is a 200 with wrong data "good"? (correctness SLI needed)
      - Is a 200 in 10s "good"? (latency threshold needed)
      - Should health check requests count? (usually NO)
    """
    name: str
    description: str
    sli_type: SLIType
    # PromQL that computes the ratio of good events (0.0 to 1.0)
    promql_good_events: str
    promql_total_events: str


@dataclass
class SLO:
    """
    Service Level Objective: the internal target.
    Set by engineering + product. NOT public.
    Should be BELOW the SLA to have a buffer.
    """
    sli: SLI
    target: float           # e.g., 0.999 = 99.9%
    window_days: int        # rolling window: 30 days
    error_budget_minutes: float = field(init=False)

    def __post_init__(self):
        # Error budget: time the service is ALLOWED to be "bad"
        # 99.9% SLO over 30 days = 0.1% of 30 days = 43.2 minutes
        total_minutes = self.window_days * 24 * 60
        allowed_error_fraction = 1 - self.target
        self.error_budget_minutes = total_minutes * allowed_error_fraction


@dataclass
class SLA:
    """
    Service Level Agreement: the LEGAL/external contract.
    More lenient than SLO (gives internal buffer).
    Violation means financial penalties (credits, refunds).
    """
    slo: SLO
    target: float           # SLA target (e.g., 0.99 = 99% — below SLO of 99.9%)
    penalty: str            # "10% monthly credit per hour of violation"


def calculate_error_budget(
    slo_target: float,
    window_days: int,
    current_error_rate: float,
) -> dict:
    """
    Calculate error budget status.
    Returns remaining budget and burn rate.
    """
    total_minutes = window_days * 24 * 60

    # Total allowed error time in the window
    allowed_error_minutes = total_minutes * (1 - slo_target)

    # Actual errors so far (simplified: assume error_rate is uniform)
    # Real: query Prometheus for actual error count over window
    actual_error_minutes = total_minutes * current_error_rate

    remaining_minutes = allowed_error_minutes - actual_error_minutes
    remaining_percent = (remaining_minutes / allowed_error_minutes) * 100

    # Burn rate: how fast is budget being consumed?
    # 1.0x = exactly on pace to use all budget by window end
    # 14x over 1h = critical (burns 14 hours of budget per hour)
    burn_rate = current_error_rate / (1 - slo_target)

    # Time until budget exhausted at current burn rate
    if burn_rate > 0 and remaining_minutes > 0:
        minutes_until_exhaustion = remaining_minutes / burn_rate
    else:
        minutes_until_exhaustion = float('inf')

    return {
        "slo_target_percent": slo_target * 100,
        "window_days": window_days,
        "allowed_error_minutes": round(allowed_error_minutes, 2),
        "actual_error_minutes": round(actual_error_minutes, 2),
        "remaining_error_budget_minutes": round(remaining_minutes, 2),
        "remaining_budget_percent": round(remaining_percent, 1),
        "current_error_rate": current_error_rate,
        "burn_rate": round(burn_rate, 2),
        "minutes_until_exhaustion": round(minutes_until_exhaustion, 1),
        "status": (
            "CRITICAL (page now)" if burn_rate >= 14 else
            "WARNING (investigate)" if burn_rate >= 6 else
            "HEALTHY"
        ),
        "recommended_action": (
            "Page on-call immediately" if burn_rate >= 14 else
            "Create incident ticket, investigate within 1 hour" if burn_rate >= 6 else
            "No action needed"
        ),
    }


# ============================================================
# SECTION 4: HIGH CARDINALITY
# ============================================================
# Cardinality: number of unique values a label can take.
# Prometheus stores one time series per unique label combination.
# High cardinality = many unique label values = many time series.
#
# DANGER ZONE:
#   labels with user_id (millions of users = millions of series)
#   labels with request_id (one per request = billions of series)
#   labels with URL (unparameterized: /users/123, /users/456, ...)
#
# Each Prometheus time series uses ~3KB RAM.
# 1M series = 3GB RAM. 10M series = 30GB → OOM → Prometheus dies.
#
# RULE: metrics for AGGREGATED view. Logs/traces for per-entity debugging.
#   Want to know error rate per user? → Use logs (filter by user_id)
#   Want to know error rate overall? → Use metrics

CARDINALITY_EXAMPLES = {
    # WRONG: url label with full path includes user IDs
    "BAD_url_label": {
        "metric": 'http_requests_total{url="/users/123"}',
        "problem": "One time series per unique URL → millions of series",
        "fix": "Normalize: /users/123 → /users/{user_id}",
    },
    # WRONG: labeling with individual user
    "BAD_user_label": {
        "metric": 'checkout_total{user_id="abc123"}',
        "problem": "1 series per user × 1M users = 1M time series",
        "fix": "Remove user_id label. Use logs to debug per-user issues.",
    },
    # CORRECT: bounded labels only
    "GOOD_labels": {
        "metric": 'http_requests_total{method="POST", endpoint="/users/{id}", status_code="200"}',
        "cardinality": "5 methods × 20 endpoints × 10 status codes = 1000 series",
        "note": "Manageable. Stays constant regardless of user count.",
    },
    # HIGH CARDINALITY IS OK for: logs (full-text indexed separately)
    "LOGS_high_cardinality": {
        "log_field": '{"user_id": "abc123", "order_id": "ord_987", "trace_id": "4bf9..."}',
        "why_ok": "Logs are stored as events, not as time series. "
                  "Queried by text search, not by label index.",
    },
}


# ============================================================
# SECTION 5: REQUEST CORRELATION
# ============================================================
# Every distributed request must carry an ID that ties together:
#   - All log lines from that request (even across services)
#   - All spans in the trace
#   - Related metrics (via exemplars)
#
# Propagation mechanism:
#   - HTTP header: X-Request-ID (your own) + traceparent (W3C standard)
#   - Set at API Gateway / entry point
#   - Each downstream service reads from headers, passes to its calls
#   - Python: use contextvars to propagate without explicit passing

class RequestCorrelationMiddleware:
    """
    ASGI/WSGI middleware that assigns request_id and sets up trace context.
    Typically implemented in the API gateway or as framework middleware.
    """

    def __init__(self, app):
        self._app = app

    def __call__(self, scope, receive, send):
        """FastAPI/Starlette ASGI interface."""
        # Extract or generate request ID
        headers = dict(scope.get("headers", []))

        # Check if caller passed an existing request ID (service-to-service)
        request_id = (
            headers.get(b"x-request-id", b"").decode()
            or str(uuid.uuid4())
        )

        # Extract W3C trace context (OpenTelemetry propagates this)
        traceparent = headers.get(b"traceparent", b"").decode()
        trace_id, span_id = self._parse_traceparent(traceparent)

        # Store in context variable — available to all code in this request
        ctx_token = request_context.set({
            "request_id": request_id,
            "trace_id": trace_id,
            "span_id": span_id,
        })

        # Add correlation IDs to response headers
        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message["headers"].extend([
                    (b"x-request-id", request_id.encode()),
                    (b"x-trace-id", (trace_id or "").encode()),
                ])
            await send(message)

        try:
            return self._app(scope, receive, send_with_headers)
        finally:
            request_context.reset(ctx_token)

    def _parse_traceparent(self, header: str) -> tuple[Optional[str], Optional[str]]:
        """
        Parse W3C traceparent header format:
        00-{trace_id}-{parent_span_id}-{flags}
        Example: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
        """
        if not header or header.count("-") != 3:
            return None, None
        parts = header.split("-")
        return parts[1], parts[2]  # trace_id, parent_span_id


# ============================================================
# SECTION 6: OBSERVABILITY CHECKLIST FOR A REST API ENDPOINT
# ============================================================
# This is the MINIMUM viable observability for each endpoint.
# Use as a checklist when building or reviewing new services.

def observability_checklist(endpoint: str) -> dict:
    """
    Returns the observability checklist for a given REST endpoint.
    Every endpoint should have all items checked.
    """
    return {
        "endpoint": endpoint,
        "metrics": [
            f"http_requests_total{{endpoint='{endpoint}'}} — increment on every response",
            f"http_request_duration_seconds{{endpoint='{endpoint}'}} — observe duration",
            f"http_active_requests{{endpoint='{endpoint}'}} — gauge: +1 on start, -1 on end",
        ],
        "logs": [
            "INFO on request received: method, path, user_id, request_id",
            "INFO on request completed: status_code, duration_ms, response_size",
            "WARNING on retry attempt: which downstream, attempt number, error",
            "ERROR on failure: full error, stack_trace, upstream context",
            "All logs MUST include: request_id, trace_id, user_id (if available)",
        ],
        "traces": [
            "Root span per request (auto-instrumented by OTel if using FastAPI)",
            "Child span per DB query (auto-instrumented by OTel SQLAlchemy plugin)",
            "Child span per external HTTP call (auto-instrumented by OTel httpx plugin)",
            "Custom span for business logic > 100ms (manual instrumentation)",
            "Record exception on any span that fails",
            "Set span attributes: user.id, order.id, etc. for searchability",
        ],
        "alerts": [
            f"Error rate > 1% for {endpoint} for > 2 minutes",
            f"P99 latency > 500ms for {endpoint} for > 5 minutes",
            "No traffic to endpoint for > 5 minutes (possible deployment issue)",
        ],
        "dashboards": [
            "QPS over time (with error/success breakdown)",
            "Latency P50/P95/P99 over time",
            "Error count and error rate over time",
            "Top errors by type (from log aggregation)",
        ],
    }


# ============================================================
# SECTION 7: REFERENCE NUMBERS (what "good" looks like)
# ============================================================

PRODUCTION_TARGETS = {
    "Web API (general)": {
        "availability": "99.9% (43.8 min downtime/month)",
        "latency_p50": "< 50ms",
        "latency_p99": "< 200ms",
        "error_rate": "< 0.1%",
    },
    "User-facing checkout": {
        "availability": "99.99% (4.4 min downtime/month)",
        "latency_p99": "< 500ms (payment calls add latency)",
        "error_rate": "< 0.01% (payment failures are catastrophic)",
    },
    "Background jobs / async": {
        "availability": "99.5% (3.6h downtime/month)",
        "latency": "Not applicable (async)",
        "throughput": "Must keep up with queue depth growth rate",
    },
    "Database": {
        "query_p99": "< 10ms for simple queries, < 100ms for complex",
        "pool_utilization": "< 70% (headroom for traffic spikes)",
        "replication_lag": "< 1s for sync, < 10s for async",
    },
    "Cache (Redis)": {
        "hit_rate": "> 90% (if below, reconsider cache strategy)",
        "latency": "< 1ms (if higher, Redis may be overloaded)",
        "memory_utilization": "< 80% (prevent eviction of hot data)",
    },
}


# ============================================================
# DEMO
# ============================================================

def run_demo():
    print("=" * 60)
    print("OBSERVABILITY FUNDAMENTALS DEMO")
    print("=" * 60)

    # Set up request context (normally done by middleware)
    request_context.set({
        "request_id": "req_" + uuid.uuid4().hex[:8],
        "trace_id": uuid.uuid4().hex,
        "user_id": "user_abc123",
    })

    # Structured logging demo
    logger = StructuredLogger("checkout-service")
    print("\n--- Structured Log Output ---")
    logger.info("Payment processed",
                order_id="ord_9871",
                amount_cents=4999,
                duration_ms=342)
    logger.error("Downstream timeout",
                 downstream="inventory-service",
                 timeout_ms=5000)

    # Error budget calculation
    print("\n--- Error Budget Analysis ---")
    scenarios = [
        (0.999, 30, 0.001),   # exactly on SLO target
        (0.999, 30, 0.002),   # 2x the allowed error rate
        (0.999, 30, 0.014),   # 14x burn rate — critical
    ]
    for slo, window, error_rate in scenarios:
        budget = calculate_error_budget(slo, window, error_rate)
        print(f"\n  SLO: {slo*100:.1f}%, error_rate: {error_rate*100:.3f}%")
        print(f"  Remaining budget: {budget['remaining_error_budget_minutes']:.1f}min "
              f"({budget['remaining_budget_percent']}%)")
        print(f"  Burn rate: {budget['burn_rate']}x → {budget['status']}")

    # Observability checklist
    print("\n--- Checklist for POST /checkout ---")
    checklist = observability_checklist("POST /checkout")
    for category, items in checklist.items():
        if category == "endpoint":
            continue
        print(f"\n  {category.upper()}:")
        if isinstance(items, list):
            for item in items[:2]:  # Show first 2 items
                print(f"    ✓ {item[:70]}...")
        else:
            print(f"    {items}")


if __name__ == "__main__":
    run_demo()
