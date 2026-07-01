# =============================================================================
# WHAT: Distributed Tracing — trace anatomy, OpenTelemetry Python SDK,
#       context propagation, sampling strategies, Jaeger/Tempo, span attributes,
#       baggage, and trace visualization concepts.
# WHY:  In a microservices architecture, a single user request touches dozens of
#       services. When something is slow, you need to pinpoint WHICH service and
#       WHICH operation caused the latency. Distributed tracing is the only tool
#       that answers this question with precision.
# LEVEL: Intermediate-Advanced — assumes familiarity with microservices and HTTP.
# =============================================================================

# ── CONCEPT OVERVIEW ─────────────────────────────────────────────────────────
#
# TRACE ANATOMY
#
#   Trace: the complete journey of a single request through the system.
#   Span:  a single unit of work (one HTTP call, one DB query, one function).
#
#   A trace is a tree of spans:
#
#   [Trace: trace_id=abc123]
#   └── [Span: api-gateway  GET /checkout      0ms ─────────────────── 450ms]
#       ├── [Span: orders-service  create_order 10ms ──────── 200ms]
#       │   ├── [Span: postgres  INSERT orders   20ms ─ 50ms]
#       │   └── [Span: redis  SET order:lock     55ms ─ 65ms]
#       └── [Span: payment-service  charge       210ms ─────────── 440ms]
#           └── [Span: stripe-api  POST /charges  220ms ──────── 430ms]
#
#   The waterfall view shows parallelism and the critical path immediately.
#   In this trace, the critical path is: api-gateway → payment-service → stripe-api.
#   That's where optimization effort should go.
#
# SPAN CONTEXT: what gets propagated between services
#   - trace_id:   globally unique ID for the entire trace (128-bit)
#   - span_id:    unique ID for this specific span (64-bit)
#   - trace_flags: sampling decision (sampled=1, not sampled=0)
#   - trace_state: vendor-specific key-value pairs
#
# W3C TRACEPARENT HEADER FORMAT:
#   traceparent: 00-{trace_id}-{parent_span_id}-{trace_flags}
#   Example:
#   traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
#                ^^ ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ ^^^^^^^^^^^^^^^^ ^^
#                ver trace_id (32 hex chars = 128 bit) parent_span_id  flags(01=sampled)
#
# ── PRODUCTION USE CASE ──────────────────────────────────────────────────────
#   Checkout latency spiked from p99=200ms to p99=2000ms. Traces in Jaeger/Tempo
#   immediately show that the inventory-service span is now 1800ms, and the
#   child span "db_query: SELECT inventory WHERE ..." is responsible. The missing
#   index on the inventory table is identified and added in 10 minutes.
#   Without tracing, this would require log correlation across 5 services.
#
# ── COMMON MISTAKES ──────────────────────────────────────────────────────────
#   1. Not propagating trace headers between services (breaks the trace tree)
#   2. Creating too many spans (per-row DB spans in a loop) → storage explosion
#   3. Missing span.set_status(ERROR) on exceptions → spans look successful
#   4. Using head-based 1% sampling → missing rare errors in low-traffic paths
#   5. Not setting meaningful span names → "HTTP POST" tells you nothing
#   6. Storing PII in span attributes (same rules as logging apply)
#   7. Forgetting span.end() — always use context managers or try/finally
# =============================================================================

import time
import random
import json
from typing import Optional, Dict, Any, Generator
from contextlib import contextmanager

# OpenTelemetry Python SDK
# pip install opentelemetry-api opentelemetry-sdk
# pip install opentelemetry-exporter-otlp-proto-grpc
# pip install opentelemetry-instrumentation-fastapi
# pip install opentelemetry-instrumentation-requests
# pip install opentelemetry-instrumentation-sqlalchemy

from opentelemetry import trace, baggage, context
from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,       # production: batches spans and exports asynchronously
    ConsoleSpanExporter,      # development: prints spans to stdout
    SimpleSpanProcessor,      # development only: exports synchronously (slow)
)
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_ON,                # sample 100% of traces (dev/debug)
    ALWAYS_OFF,               # sample 0% (disable tracing)
    TraceIdRatioBased,        # sample X% based on trace_id hash (head-based)
    ParentBased,              # respect parent's sampling decision
)
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import (
    Span,
    SpanKind,                 # SERVER, CLIENT, INTERNAL, PRODUCER, CONSUMER
    StatusCode,               # OK, ERROR, UNSET
    NonRecordingSpan,
)
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry import propagate
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION


# =============================================================================
# SECTION 1: PROVIDER SETUP — configure once at service startup
# =============================================================================
#
# TracerProvider is the central registry for all tracers in a process.
# In a multi-process system, each process has its own TracerProvider.
# The global tracer provider is set via trace.set_tracer_provider().

def setup_tracing(
    service_name: str,
    service_version: str,
    otlp_endpoint: str = "http://localhost:4317",  # default OTLP gRPC port
    sample_rate: float = 1.0,                       # 1.0 = 100% sampling
) -> trace.Tracer:
    """
    Configure OpenTelemetry tracing for a service.
    Call once at application startup, before serving any requests.
    Returns a Tracer that can be used throughout the application.
    """

    # Resource describes the entity producing telemetry (your service)
    # These attributes appear on every span from this process
    resource = Resource.create({
        SERVICE_NAME: service_name,                # required: "orders-service"
        SERVICE_VERSION: service_version,          # "1.2.3"
        "deployment.environment": "production",    # "production" | "staging" | "dev"
        "host.name": "pod-xyz-123",                # from env var in production
        "k8s.namespace.name": "payments",          # Kubernetes namespace
        "k8s.pod.name": "orders-api-7d9b4c-xyz",  # Kubernetes pod name
    })

    # Sampling: controls what fraction of traces are recorded.
    # ParentBased: respect the parent's sampling decision (received via header).
    #   If parent is sampled → sample this service too.
    #   If no parent → apply the root sampler (TraceIdRatioBased here).
    # This ensures a trace is either fully sampled or fully not sampled,
    # preventing "broken traces" where only some services have spans.
    sampler = ParentBased(root=TraceIdRatioBased(sample_rate))

    # Create the provider
    provider = TracerProvider(resource=resource, sampler=sampler)

    # ── Exporters: where spans are sent ──────────────────────────────────────
    # OTLP (OpenTelemetry Protocol) gRPC: sends to Jaeger, Grafana Tempo, etc.
    otlp_exporter = OTLPSpanExporter(
        endpoint=otlp_endpoint,                    # gRPC endpoint of your backend
        # In production, add TLS and auth:
        # credentials=grpc.ssl_channel_credentials(),
        # headers={"Authorization": f"Bearer {token}"},
    )

    # BatchSpanProcessor: collects spans in memory, exports in batches.
    # Never use SimpleSpanProcessor in production — it blocks the request thread.
    batch_processor = BatchSpanProcessor(
        span_exporter=otlp_exporter,
        max_queue_size=2048,                       # max spans in memory before dropping
        max_export_batch_size=512,                 # spans per export batch
        export_timeout_millis=30_000,              # timeout per export call
        schedule_delay_millis=5_000,               # export every 5 seconds
    )

    provider.add_span_processor(batch_processor)

    # Also print to console in dev (comment out in production)
    # provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    # Set as the global tracer provider — must be done before any get_tracer() calls
    trace.set_tracer_provider(provider)

    # Configure context propagators: how trace context travels in HTTP headers.
    # TraceContext = W3C traceparent header
    # W3CBaggagePropagator = W3C baggage header (cross-service key-value data)
    propagate.set_global_textmap(
        CompositePropagator([
            TraceContextTextMapPropagator(),       # handles traceparent header
            W3CBaggagePropagator(),                # handles baggage header
        ])
    )

    # Get a tracer for this service — use __name__ in modules
    tracer = trace.get_tracer(service_name, service_version)
    return tracer


# =============================================================================
# SECTION 2: SPAN KINDS — semantic meaning of each span
# =============================================================================
#
# SpanKind tells backends how to represent and analyze the span:
#
#   SERVER:   receives a request (your API endpoint handler)
#   CLIENT:   makes a request to an external service (HTTP call, DB query)
#   INTERNAL: internal operation (a function call, business logic step)
#   PRODUCER: sends a message to a queue (Kafka produce, SQS send)
#   CONSUMER: receives a message from a queue (Kafka consume, SQS receive)
#
# Kind matters for UI rendering:
#   SERVER spans are shown as request entry points in Jaeger's service graph.
#   CLIENT spans show dependencies between services.
#
# Naming conventions:
#   SERVER spans:  "{HTTP method} {route template}"     e.g., "GET /api/orders/{id}"
#   CLIENT spans:  "{HTTP method}"                      e.g., "GET"
#   DB CLIENT:     "{db.system} {operation} {table}"    e.g., "postgresql select orders"
#   INTERNAL:      "{module}.{function}"                e.g., "orders.validate_items"


# =============================================================================
# SECTION 3: MANUAL INSTRUMENTATION — creating and enriching spans
# =============================================================================

# Get the global tracer (after setup_tracing() has been called)
# In practice this would be at module level, after startup
_tracer: Optional[trace.Tracer] = None


def get_tracer() -> trace.Tracer:
    """Get the global tracer (fallback to no-op if not initialized)."""
    global _tracer
    if _tracer is None:
        # Returns a no-op tracer that doesn't record anything
        _tracer = trace.get_tracer("orders-service", "0.0.0")
    return _tracer


def process_order_with_tracing(order_id: str, user_id: str) -> Dict[str, Any]:
    """
    Demonstrate manual span creation, attributes, events, and error handling.
    This would be the handler for POST /api/v1/orders.
    """
    tracer = get_tracer()

    # SpanKind.SERVER: this is the entry point receiving a request
    with tracer.start_as_current_span(
        name="POST /api/v1/orders",               # span name: method + route template
        kind=SpanKind.SERVER,
    ) as root_span:

        # ── Span Attributes: key-value metadata about this operation ──────────
        # Use OpenTelemetry semantic conventions where possible:
        # https://opentelemetry.io/docs/specs/semconv/
        root_span.set_attribute("http.method", "POST")
        root_span.set_attribute("http.route", "/api/v1/orders")
        root_span.set_attribute("http.scheme", "https")
        root_span.set_attribute("http.target", "/api/v1/orders")
        root_span.set_attribute("net.peer.ip", "10.0.0.1")

        # Business-specific attributes (safe, non-PII)
        root_span.set_attribute("order.id", order_id)
        root_span.set_attribute("order.user_id_hash", _hash_id(user_id))

        # ── Child span: validate order ─────────────────────────────────────────
        with tracer.start_as_current_span(
            "orders.validate_items",
            kind=SpanKind.INTERNAL,               # internal = no network call
        ) as validate_span:
            validate_span.set_attribute("order.item_count", 3)

            # Span Events: point-in-time annotations within a span.
            # Like logs, but attached to a specific span and timestamp.
            validate_span.add_event(
                name="validation_rule_applied",
                attributes={
                    "rule": "inventory_check",
                    "result": "passed",
                    "items_checked": 3,
                },
            )

            time.sleep(0.01)                      # simulated validation work

        # ── Child span: database insert ────────────────────────────────────────
        with tracer.start_as_current_span(
            "postgresql insert orders",           # semantic: db.system + operation + table
            kind=SpanKind.CLIENT,                 # CLIENT: we're calling an external DB
        ) as db_span:
            # Database semantic conventions
            db_span.set_attribute("db.system", "postgresql")
            db_span.set_attribute("db.name", "orders_db")
            db_span.set_attribute("db.operation", "INSERT")
            db_span.set_attribute("db.sql.table", "orders")
            # NEVER put full SQL with user data in attributes — use parameterized form
            db_span.set_attribute(
                "db.statement",
                "INSERT INTO orders (id, user_id, status) VALUES ($1, $2, $3)",
            )
            db_span.set_attribute("net.peer.name", "postgres.internal")
            db_span.set_attribute("net.peer.port", 5432)

            time.sleep(random.uniform(0.005, 0.030))  # simulated DB latency

        # ── Child span: call payment service (remote HTTP call) ────────────────
        try:
            payment_result = call_payment_service(
                order_id=order_id,
                amount_cents=9999,
            )
        except Exception as e:
            # CRITICAL: record the error on the span so it shows as failed in Jaeger
            root_span.record_exception(e)          # adds exception as a span event
            root_span.set_status(
                StatusCode.ERROR,
                description=f"Payment failed: {type(e).__name__}",
            )
            root_span.set_attribute("http.status_code", 502)
            raise

        # Set successful status and HTTP response code
        root_span.set_status(StatusCode.OK)
        root_span.set_attribute("http.status_code", 201)
        root_span.set_attribute("order.status", "confirmed")

        return {"order_id": order_id, "status": "confirmed"}


def call_payment_service(order_id: str, amount_cents: int) -> Dict[str, Any]:
    """
    Simulate making an outbound HTTP call to the payment service.
    Demonstrates context propagation via HTTP headers.
    """
    tracer = get_tracer()

    # SpanKind.CLIENT: we are making an outbound HTTP request
    with tracer.start_as_current_span(
        "POST",                                   # HTTP client spans use method name
        kind=SpanKind.CLIENT,
    ) as client_span:
        client_span.set_attribute("http.method", "POST")
        client_span.set_attribute("http.url", "http://payment-service/v1/charges")
        client_span.set_attribute("net.peer.name", "payment-service")
        client_span.set_attribute("net.peer.port", 8080)
        client_span.set_attribute("order.id", order_id)
        client_span.set_attribute("payment.amount_cents", amount_cents)

        # ── Context Propagation: inject trace context into outgoing headers ────
        # This is what makes distributed tracing "distributed".
        # The payment service reads these headers and creates a child span.
        headers: Dict[str, str] = {}
        propagate.inject(headers)                 # adds traceparent (and baggage) headers
        # headers is now: {"traceparent": "00-abc123...-def456...-01"}
        # Pass these headers in your actual HTTP client:
        # requests.post(url, headers=headers, json=payload)

        # Simulate the HTTP call
        time.sleep(random.uniform(0.050, 0.200))

        # Simulate occasional payment failure
        if random.random() < 0.05:
            raise ConnectionError("Payment service timeout")

        response_status = 200
        client_span.set_attribute("http.status_code", response_status)

        if response_status >= 400:
            client_span.set_status(StatusCode.ERROR, "HTTP error from payment service")
        else:
            client_span.set_status(StatusCode.OK)

        return {"charge_id": "ch_abc123", "status": "succeeded"}


# =============================================================================
# SECTION 4: CONTEXT PROPAGATION — receiving trace context from upstream
# =============================================================================
#
# When your service receives an HTTP request, extract the trace context
# from the incoming headers to continue the trace from the upstream caller.

def handle_incoming_request(incoming_headers: Dict[str, str]) -> context.Context:
    """
    Extract W3C trace context from incoming HTTP request headers.
    This creates a context that makes any spans you create children of
    the upstream span (even if that span lives in a different service/process).
    """
    # extract() reads traceparent and baggage headers and returns a Context
    ctx = propagate.extract(carrier=incoming_headers)
    return ctx


def payment_service_handler(incoming_headers: Dict[str, str], order_id: str):
    """
    Example: payment service receives a request from orders service.
    The span created here will be a child of the orders service span.
    """
    tracer = get_tracer()

    # Extract context from headers so this span is linked to the calling trace
    ctx = handle_incoming_request(incoming_headers)

    # Pass the context explicitly — this span becomes a child of the upstream span
    with tracer.start_as_current_span(
        "POST /v1/charges",
        context=ctx,                              # link to parent trace
        kind=SpanKind.SERVER,
    ) as span:
        span.set_attribute("http.method", "POST")
        span.set_attribute("http.route", "/v1/charges")
        span.set_attribute("order.id", order_id)

        # Now call Stripe API — this creates another child span
        time.sleep(0.15)                          # simulated Stripe API call
        span.set_status(StatusCode.OK)
        span.set_attribute("http.status_code", 200)


# =============================================================================
# SECTION 5: BAGGAGE — propagating cross-service key-value data
# =============================================================================
#
# Baggage is key-value data attached to a trace context and propagated
# to ALL downstream services via the W3C baggage header.
#
# USE CASES:
#   - Tenant ID for multi-tenant services (route to correct data partition)
#   - Feature flag values (A/B test cohort carried through the trace)
#   - User tier ("premium", "standard") for downstream routing decisions
#
# IMPORTANT: Baggage adds HTTP header bytes to every request.
#   Keep values small and the number of keys small (<5).
#   Baggage is NOT for large data (use a cache or DB for that).
#   Baggage IS visible to all services — don't put PII or secrets in it.
#
# DIFFERENCE FROM SPAN ATTRIBUTES:
#   Attributes: stored only in the current span (not propagated downstream)
#   Baggage:    propagated to all downstream services (but not stored in spans)

def set_baggage_for_request(tenant_id: str, user_tier: str) -> context.Context:
    """Set baggage values that will propagate to all downstream services."""
    ctx = context.get_current()

    # Each baggage.set() returns a new context (immutable)
    ctx = baggage.set_baggage("tenant.id", tenant_id, context=ctx)
    ctx = baggage.set_baggage("user.tier", user_tier, context=ctx)
    ctx = baggage.set_baggage("experiment.cohort", "B", context=ctx)

    return ctx


def read_baggage_in_downstream_service() -> Dict[str, Optional[str]]:
    """Read baggage values in a downstream service."""
    return {
        "tenant_id": baggage.get_baggage("tenant.id"),
        "user_tier": baggage.get_baggage("user.tier"),
        "experiment_cohort": baggage.get_baggage("experiment.cohort"),
    }


# =============================================================================
# SECTION 6: SAMPLING STRATEGIES
# =============================================================================
#
# Head-based sampling: decision made at the START of a trace (at the root span).
#   Pros: simple, low overhead, no buffering needed.
#   Cons: can't sample based on outcome (error, latency) — decided before those are known.
#
#   1. Always On (100%):      every trace recorded. Use in dev/staging.
#                             NEVER in production at high traffic — storage cost.
#
#   2. TraceIdRatioBased:     deterministic sampling by hashing trace_id.
#                             sample_rate=0.01 → 1% of traces.
#                             Same trace_id always makes the same decision.
#
#   3. Rate-Limited:          max N traces per second (opentelemetry-sdk-contrib).
#                             Prevents burst traffic from filling trace storage.
#
#   4. ParentBased:           respects the parent's sampling decision.
#                             Critical for consistent traces across services.
#                             Always combine with a root sampler.
#
# Tail-based sampling: decision made AFTER the trace completes.
#   Collector (e.g., OpenTelemetry Collector) buffers all spans, waits for trace to finish,
#   then decides: keep if error, keep if p99 > threshold, sample rest at 1%.
#   Pros: can always keep all errors and slow traces. Best of both worlds.
#   Cons: requires buffering (memory cost), more complex collector configuration.
#   Implementation: OpenTelemetry Collector with tail_sampling processor.

SAMPLING_EXAMPLES = {
    "dev_always_on": """
        sampler = ALWAYS_ON
        # Records 100% of traces. Fine for dev, never for high-traffic production.
    """,

    "production_1_percent": """
        sampler = ParentBased(root=TraceIdRatioBased(0.01))
        # Records 1% of root traces. Respects parent's decision for child services.
        # Problem: if a critical endpoint has 10 req/min, you might see 0 traces.
    """,

    "otel_collector_tail_sampling_config": """
        # OpenTelemetry Collector config (collector.yaml)
        processors:
          tail_sampling:
            decision_wait: 10s        # wait up to 10s for all spans to arrive
            num_traces: 50000         # buffer up to 50k traces
            expected_new_traces_per_sec: 100
            policies:
              # Policy 1: always keep traces with errors
              - name: errors-policy
                type: status_code
                status_code: {status_codes: [ERROR]}

              # Policy 2: always keep slow traces (> 500ms)
              - name: slow-traces-policy
                type: latency
                latency: {threshold_ms: 500}

              # Policy 3: sample 1% of everything else
              - name: probabilistic-policy
                type: probabilistic
                probabilistic: {sampling_percentage: 1}
    """,
}


# =============================================================================
# SECTION 7: AUTOMATIC INSTRUMENTATION
# =============================================================================
#
# OpenTelemetry provides auto-instrumentation libraries that patch popular
# frameworks/libraries to create spans automatically.
#
# FASTAPI (HTTP server): opentelemetry-instrumentation-fastapi
#   Creates a SERVER span for every incoming request automatically.
#   Extracts trace context from incoming headers.
#   Sets http.method, http.route, http.status_code attributes.
#
# REQUESTS (HTTP client): opentelemetry-instrumentation-requests
#   Creates a CLIENT span for every outbound requests.get()/post() call.
#   Injects traceparent header into outgoing requests automatically.
#
# SQLALCHEMY (database): opentelemetry-instrumentation-sqlalchemy
#   Creates a CLIENT span for every SQL query execution.
#   Captures db.system, db.statement, db.name attributes.
#
# REDIS: opentelemetry-instrumentation-redis
#   Creates CLIENT spans for Redis commands.
#
# PSYCOPG2: opentelemetry-instrumentation-psycopg2
#   Spans for PostgreSQL queries via psycopg2 driver.

FASTAPI_AUTO_INSTRUMENTATION_EXAMPLE = """
# In your FastAPI app startup:

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

app = FastAPI()

# Instrument FastAPI — auto-creates SERVER spans for all routes
FastAPIInstrumentor.instrument_app(
    app,
    excluded_urls="health,metrics",    # don't trace health check endpoints
    http_capture_headers_server_request=["X-Request-ID"],  # capture custom headers
)

# Instrument outbound HTTP calls (requests library)
RequestsInstrumentor().instrument()

# Instrument SQLAlchemy — requires engine reference
from sqlalchemy import create_engine
engine = create_engine("postgresql://...")
SQLAlchemyInstrumentor().instrument(engine=engine, enable_commenter=True)

# Now ALL requests through FastAPI, requests, and SQLAlchemy produce spans.
# You only need to add manual spans for your own business logic.
"""


# =============================================================================
# SECTION 8: TRACING BACKENDS — Jaeger and Grafana Tempo
# =============================================================================
#
# JAEGER (CNCF project, open source):
#   - UI: waterfall view, DAG service map, JSON trace inspection
#   - Storage backends: memory (dev), Cassandra, Elasticsearch, BadgerDB
#   - Receives via: OTLP gRPC/HTTP, Jaeger native protocol (legacy), Zipkin
#   - Jaeger Query: UI at http://localhost:16686
#   - Run locally: docker run -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one
#
# GRAFANA TEMPO (Grafana Labs, open source):
#   - Designed for Grafana — deeply integrated with Prometheus + Loki
#   - Stores traces in object storage (S3/GCS/Azure Blob) — very cheap at scale
#   - TraceQL: query language for filtering spans by attributes, duration, status
#   - Exemplars: link from a Prometheus metric data point to a specific trace
#     (e.g., click a spike in the latency graph → jump to a trace from that second)
#   - Integrates with Grafana dashboards: "Explore traces" alongside metrics/logs
#
# ZIPKIN (older, still used):
#   - Simpler, less feature-rich than Jaeger
#   - OTel can export to Zipkin format via opentelemetry-exporter-zipkin
#
# Choosing a backend:
#   Jaeger:  you want a dedicated tracing UI, no Grafana dependency
#   Tempo:   you already use Prometheus + Grafana; want unified observability
#   Datadog/New Relic/Honeycomb: commercial, managed, more features

TEMPO_TRACEQL_EXAMPLES = {
    # Find all traces with errors in the orders service
    "errors_in_service": """
        {resource.service.name="orders-service" && status=error}
    """,

    # Find slow traces: root span > 1 second
    "slow_traces": """
        {duration > 1s}
    """,

    # Find traces for a specific order ID (span attribute search)
    "specific_order": """
        {span.order.id="ord_789xyz"}
    """,

    # Find all DB queries > 100ms
    "slow_db_queries": """
        {span.db.system="postgresql" && duration > 100ms}
    """,

    # Aggregate: p99 latency grouped by service
    "p99_per_service_traceql": """
        | select(duration)
        | by(resource.service.name)
        | quantile(0.99, duration)
    """,
}


# =============================================================================
# SECTION 9: SPAN ATTRIBUTES REFERENCE — semantic conventions
# =============================================================================
#
# OpenTelemetry defines standard attribute names to enable consistent tooling.
# Always use these over custom names where they apply.

SEMANTIC_ATTRIBUTE_REFERENCE = {
    # HTTP Server (incoming requests)
    "http.method": "GET",                         # HTTP method
    "http.route": "/api/orders/{id}",             # route template (not filled URL)
    "http.target": "/api/orders/123?foo=bar",     # actual request URI
    "http.status_code": 200,                      # response status code
    "http.scheme": "https",                       # http or https
    "net.peer.ip": "10.0.0.1",                    # client IP

    # HTTP Client (outgoing requests)
    "http.url": "https://api.stripe.com/v1/charges",  # full URL
    "net.peer.name": "api.stripe.com",            # hostname of remote

    # Database
    "db.system": "postgresql",                    # mysql | redis | mongodb | etc.
    "db.name": "orders_db",                       # database name
    "db.operation": "SELECT",                     # SELECT | INSERT | UPDATE | DELETE
    "db.sql.table": "orders",                     # primary table
    "db.statement": "SELECT * FROM orders WHERE id=$1",  # parameterized SQL

    # Messaging (Kafka, SQS, RabbitMQ)
    "messaging.system": "kafka",                  # kafka | rabbitmq | aws_sqs
    "messaging.destination": "orders.created",   # topic or queue name
    "messaging.operation": "publish",             # publish | receive | process

    # Error
    "exception.type": "ConnectionError",          # exception class name
    "exception.message": "Connection refused",    # exception message
    "exception.stacktrace": "Traceback (most recent...",  # full stack trace

    # Service identity (from Resource, but sometimes set on spans too)
    "service.name": "orders-service",
    "service.version": "1.2.3",
}


# =============================================================================
# SECTION 10: TRACE VISUALIZATION — reading a waterfall view
# =============================================================================
#
# WATERFALL VIEW in Jaeger/Tempo:
#   Each row is a span. The horizontal bar shows start time and duration.
#   Child spans are indented under parent spans.
#
# CRITICAL PATH ANALYSIS:
#   The critical path is the chain of spans that determines the total trace duration.
#   Any span NOT on the critical path can be optimized without reducing total latency.
#
#   To find the critical path:
#   1. Start from the root span.
#   2. At each level, the critical child is the one that ends last.
#   3. Follow the last-ending child recursively.
#
# COMMON PATTERNS TO LOOK FOR:
#   - Sequential where parallel is possible: N spans one after another that could run concurrently
#   - Large gaps: time between spans where the parent is not in any child (CPU/lock contention)
#   - Unexpectedly deep DB spans: N+1 query problem
#   - Repeated retry spans: exponential backoff visible as multiple CLIENT spans
#   - One outlier span: one slow DB query in an otherwise fast trace


def _hash_id(value: str) -> str:
    """Hash an ID for safe inclusion in trace attributes."""
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()[:16]


# =============================================================================
# SECTION 11: DEMONSTRATION (without a running backend)
# =============================================================================

def main():
    """Demonstrate tracing setup and span creation with console output."""
    print("=== OpenTelemetry Distributed Tracing Demo ===\n")

    # Setup with console exporter (prints to stdout instead of sending to Jaeger)
    resource = Resource.create({
        SERVICE_NAME: "orders-service",
        SERVICE_VERSION: "1.0.0",
        "deployment.environment": "demo",
    })

    provider = TracerProvider(resource=resource, sampler=ALWAYS_ON)
    # Print spans to console for demonstration
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)

    global _tracer
    _tracer = trace.get_tracer("orders-service", "1.0.0")

    propagate.set_global_textmap(
        CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()])
    )

    print("Processing order with distributed tracing...")
    print("(Each span will be printed to console as it completes)\n")

    try:
        result = process_order_with_tracing(
            order_id="ord_demo_001",
            user_id="user_42",
        )
        print(f"\nOrder result: {result}")
    except Exception as e:
        print(f"\nOrder failed: {e}")

    print("\nIn production, spans would be exported to Jaeger/Tempo instead.")
    print("View traces at: http://localhost:16686 (Jaeger UI)")

    print("\nTailored PromQL + TraceQL queries:")
    for name, query in TEMPO_TRACEQL_EXAMPLES.items():
        print(f"  {name}: {query.strip()}")


if __name__ == "__main__":
    main()
