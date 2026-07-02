# =============================================================================
# WHAT: OpenTelemetry (OTel) deep dive — SDK architecture, signal types,
#       Collector pipeline, auto/manual instrumentation, semantic conventions,
#       and migration from OpenTracing/OpenCensus.
# WHY:  OTel is the CNCF-standard, vendor-neutral observability framework.
#       It replaces every proprietary SDK with a single unified API so you can
#       switch backends (Jaeger → Tempo, Prometheus → Datadog) without touching
#       application code.
# LEVEL: Intermediate → Advanced (assumes basic Python + Docker familiarity)
# =============================================================================

# ---------------------------------------------------------------------------
# CONCEPT OVERVIEW
# ---------------------------------------------------------------------------
# OpenTelemetry defines THREE signal types that share a single data model:
#
#   Traces   — distributed call graphs (spans with parent/child links)
#   Metrics  — numeric measurements aggregated over time (counter, gauge, histogram)
#   Logs     — structured event records correlated to traces via trace_id/span_id
#
# The OTel specification lives at opentelemetry.io/spec.  Every language SDK
# implements it identically so concepts learned here apply to Go, Java, etc.
#
# Key layering:
#   API   → stable interfaces your app calls  (opentelemetry-api package)
#   SDK   → concrete implementations          (opentelemetry-sdk package)
#   Instrumentation libs → auto-patch popular frameworks
#   Collector → agent/gateway that receives, processes, and exports telemetry
#
# OTLP (OpenTelemetry Protocol) is the canonical wire format over gRPC or HTTP.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# PRODUCTION USE CASE
# ---------------------------------------------------------------------------
# A FastAPI microservice that:
#   1. Auto-instruments HTTP requests, SQLAlchemy, and Redis calls.
#   2. Emits custom business metrics (orders_processed, checkout_latency).
#   3. Ships everything via OTLP to a local OTel Collector which fan-outs to
#      Tempo (traces), Prometheus remote-write (metrics), and Loki (logs).
#   4. Uses W3C TraceContext propagation so traces cross service boundaries.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# COMMON MISTAKES
# ---------------------------------------------------------------------------
# 1. Calling SDK-only classes from the API layer — always import from
#    opentelemetry.trace / opentelemetry.metrics (API), not from sdk.trace.
# 2. Not setting a Resource — dashboards show "unknown_service" everywhere.
# 3. Using the default NoopTracerProvider in production because you forgot to
#    call TracerProvider.set_global() / set_meter_provider().
# 4. Creating a new tracer/meter on every request instead of once at startup.
# 5. Recording high-cardinality labels (user_id, request_id) on metrics —
#    causes Prometheus to OOM with millions of time series.
# 6. Ignoring context propagation — every async task / thread needs
#    contextvars.copy_context() so the active span isn't lost.
# 7. Exporting directly from the SDK to a backend in production — always use
#    the Collector as a buffer/retry layer.
# ---------------------------------------------------------------------------

# ── Standard library ────────────────────────────────────────────────────────
import logging
import time
import random
import os

# ── OTel API (stable, ship in production code) ───────────────────────────────
from opentelemetry import trace, metrics, baggage, context
from opentelemetry.trace import SpanKind, StatusCode, NonRecordingSpan
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

# ── OTel SDK (configure once at startup / in the service entrypoint) ─────────
from opentelemetry.sdk.trace import TracerProvider, SynchronousMultiSpanProcessor
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.trace.sampling import (
    ParentBased,          # respect upstream sampler decisions
    TraceIdRatioBased,    # sample N % of root spans
    ALWAYS_ON,
    ALWAYS_OFF,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    PeriodicExportingMetricReader,
    ConsoleMetricExporter,
)
from opentelemetry.sdk.logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk.logs.export import BatchLogRecordProcessor, ConsoleLogExporter
from opentelemetry.sdk.resources import (
    Resource,
    SERVICE_NAME,
    SERVICE_VERSION,
    DEPLOYMENT_ENVIRONMENT,
    OTELResourceDetector,   # reads OTEL_* env vars automatically
)

# ── OTLP exporters (gRPC variant) ────────────────────────────────────────────
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

# ── Semantic conventions (attribute name constants) ───────────────────────────
from opentelemetry.semconv.trace import SpanAttributes  # HTTP_METHOD, DB_STATEMENT …
from opentelemetry.semconv.resource import ResourceAttributes

# ── Propagators ──────────────────────────────────────────────────────────────
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.baggage.propagation import W3CBaggagePropagator

# ── Auto-instrumentation bootstrap (used in __main__ guard below) ─────────────
# pip install opentelemetry-instrumentation-fastapi
#             opentelemetry-instrumentation-sqlalchemy
#             opentelemetry-instrumentation-redis
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor

logger = logging.getLogger(__name__)


# =============================================================================
# SECTION 1 — Resource: identity of the instrumented entity
# =============================================================================

def build_resource() -> Resource:
    """
    A Resource describes WHAT is producing telemetry.
    OTel merges the programmatic resource with environment-detected ones
    (OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES env vars).
    """
    programmatic = Resource.create(
        {
            SERVICE_NAME: "checkout-service",        # shown in every backend UI
            SERVICE_VERSION: "2.4.1",                # correlate alerts to deploys
            DEPLOYMENT_ENVIRONMENT: os.getenv("ENV", "production"),
            "team": "platform",                      # custom attribute — useful for routing
            "region": os.getenv("AWS_REGION", "us-east-1"),
        }
    )
    # OTELResourceDetector reads OTEL_* env vars set by the orchestrator.
    env_detected = OTELResourceDetector().detect()
    # merge() is left-biased: programmatic wins on key conflicts
    return programmatic.merge(env_detected)


# =============================================================================
# SECTION 2 — Tracing pipeline setup
# =============================================================================

def setup_tracing(resource: Resource) -> trace.TracerProvider:
    """
    Configure and install the global TracerProvider.

    Sampling strategy: ParentBased(root=TraceIdRatioBased(0.1))
      - If a parent span already exists and was sampled → keep sampling.
      - If we are the root → sample 10 % of traffic.
    Never use ALWAYS_ON in high-throughput services — cost explodes.
    """
    sampler = ParentBased(root=TraceIdRatioBased(sample_rate=0.10))

    provider = TracerProvider(resource=resource, sampler=sampler)

    # --- OTLP exporter (production) ------------------------------------------
    # The Collector endpoint is usually localhost:4317 when running as a sidecar.
    otlp_exporter = OTLPSpanExporter(
        endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
        insecure=True,   # TLS off for sidecar; terminate TLS at Collector instead
    )
    # BatchSpanProcessor: buffers spans in memory and sends in batches.
    # max_queue_size=2048, max_export_batch_size=512, schedule_delay=5000ms defaults.
    provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

    # --- Console exporter (dev / debug only) ---------------------------------
    if os.getenv("OTEL_DEV_MODE"):
        provider.add_span_processor(
            BatchSpanProcessor(ConsoleSpanExporter())   # pretty-prints to stdout
        )

    # Install as global default so opentelemetry.trace.get_tracer() works anywhere.
    trace.set_tracer_provider(provider)
    return provider


# =============================================================================
# SECTION 3 — Metrics pipeline setup
# =============================================================================

def setup_metrics(resource: Resource) -> metrics.MeterProvider:
    """
    OTel Metrics data model: Instruments → Measurements → Aggregations → Export.

    Instrument types:
      Counter          — monotonically increasing (request count, bytes sent)
      UpDownCounter    — can go up and down (queue depth, active connections)
      Histogram        — latency distributions; converted to Prometheus histograms
      ObservableGauge  — callback-based, polled at export time (memory usage)
    """
    otlp_metric_exporter = OTLPMetricExporter(
        endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
        insecure=True,
    )
    # PeriodicExportingMetricReader pushes metrics every export_interval_millis.
    # Default 60 s; lower for SLO-critical dashboards.
    reader = PeriodicExportingMetricReader(
        otlp_metric_exporter,
        export_interval_millis=15_000,   # 15-second scrape equivalent
    )
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    return provider


# =============================================================================
# SECTION 4 — Logs pipeline setup (OTel Logs Bridge API)
# =============================================================================

def setup_logging(resource: Resource) -> None:
    """
    OTel Log Bridge API does NOT replace the Python logging module.
    It *bridges* existing log records so they carry trace_id / span_id and
    are shipped via OTLP alongside traces — enabling "logs in context" in Grafana.

    Steps:
      1. Create LoggerProvider with OTLP exporter.
      2. Attach OTel LoggingHandler to the root Python logger.
      3. All existing log.info / log.error calls are automatically enriched.
    """
    log_provider = LoggerProvider(resource=resource)
    otlp_log_exporter = OTLPLogExporter(
        endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
        insecure=True,
    )
    log_provider.add_log_record_processor(BatchLogRecordProcessor(otlp_log_exporter))

    # Attach to root logger — any library that uses logging is now correlated.
    otel_handler = LoggingHandler(level=logging.DEBUG, logger_provider=log_provider)
    logging.getLogger().addHandler(otel_handler)
    logging.getLogger().setLevel(logging.INFO)


# =============================================================================
# SECTION 5 — Propagation: crossing service boundaries
# =============================================================================

def setup_propagation() -> None:
    """
    Propagators inject/extract trace context into/from carrier dicts (HTTP headers).

    W3C TraceContext  → standard 'traceparent' / 'tracestate' headers (prefer this)
    W3C Baggage       → ships key-value pairs alongside the trace
    B3                → legacy header from Zipkin (use only for backward compat)

    The global propagator is used automatically by auto-instrumentation libs.
    """
    from opentelemetry.propagators.b3 import B3SingleFormat   # pip install …-b3
    composite = CompositePropagator(
        [
            TraceContextTextMapPropagator(),  # W3C traceparent
            W3CBaggagePropagator(),           # W3C baggage
            B3SingleFormat(),                 # backward compat with old services
        ]
    )
    from opentelemetry import propagate
    propagate.set_global_textmap(composite)


# =============================================================================
# SECTION 6 — Manual instrumentation: spans
# =============================================================================

# Get a tracer once at module level.  The name should be the library/module name,
# not the service name (the service name is in the Resource).
tracer = trace.get_tracer("checkout.service", schema_url="https://opentelemetry.io/schemas/1.24.0")


def process_order(order_id: str, user_id: str, amount: float) -> dict:
    """
    Manual span creation showing all common patterns:
    attributes, events, links, status, and nested spans.
    """
    # Start a SERVER span — this is the entry point of a server-side operation.
    with tracer.start_as_current_span(
        "process_order",
        kind=SpanKind.SERVER,             # SERVER = received request from upstream
    ) as span:
        # --- Semantic convention attributes (use constants, not raw strings) ---
        span.set_attribute(SpanAttributes.HTTP_METHOD, "POST")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/orders")
        span.set_attribute("order.id", order_id)          # custom attribute
        span.set_attribute("order.amount", amount)
        # NEVER set user_id as a metric label but it is fine on a span —
        # spans are indexed, not aggregated.
        span.set_attribute("user.id", user_id)

        # Span events = timestamped log-like annotations inside a span.
        span.add_event(
            "order_received",
            attributes={"queue.depth": 42},
        )

        try:
            result = _validate_and_charge(order_id, amount)
            span.set_status(StatusCode.OK)           # explicitly mark success
            return result
        except ValueError as exc:
            # Record the exception as a span event with stack trace.
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR, description=str(exc))
            raise


def _validate_and_charge(order_id: str, amount: float) -> dict:
    """Nested span — automatically becomes a child of the current span."""
    with tracer.start_as_current_span(
        "validate_and_charge",
        kind=SpanKind.INTERNAL,
    ) as span:
        span.set_attribute("payment.gateway", "stripe")
        span.set_attribute("order.amount_cents", int(amount * 100))

        # Simulate DB call with its own child span.
        _db_query(order_id)

        # Simulate latency.
        time.sleep(random.uniform(0.01, 0.05))
        return {"order_id": order_id, "status": "charged"}


def _db_query(order_id: str) -> None:
    """
    DB span following semantic conventions for databases.
    SpanKind.CLIENT = this service is making an outgoing call.
    """
    with tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as span:
        span.set_attribute(SpanAttributes.DB_SYSTEM, "postgresql")
        span.set_attribute(SpanAttributes.DB_NAME, "orders")
        # Parameterize queries — never put user data in DB_STATEMENT.
        span.set_attribute(SpanAttributes.DB_STATEMENT, "SELECT * FROM orders WHERE id = $1")
        span.set_attribute(SpanAttributes.DB_OPERATION, "SELECT")
        span.set_attribute("db.rows_returned", 1)
        time.sleep(random.uniform(0.002, 0.010))   # simulated query time


# =============================================================================
# SECTION 7 — Manual instrumentation: metrics
# =============================================================================

# Meter is created once at module level.
meter = metrics.get_meter("checkout.service")

# Counter: total orders processed — always goes up.
orders_counter = meter.create_counter(
    name="orders.processed",
    unit="1",                      # dimensionless count
    description="Total number of orders processed successfully",
)

# Histogram: end-to-end latency with explicit bucket boundaries.
checkout_latency = meter.create_histogram(
    name="checkout.duration",
    unit="ms",
    description="End-to-end checkout latency in milliseconds",
)

# UpDownCounter: how many orders are currently in flight.
orders_in_flight = meter.create_up_down_counter(
    name="orders.in_flight",
    unit="1",
    description="Number of orders currently being processed",
)

# ObservableGauge: polled at export time — no explicit record() calls needed.
def _observe_queue_depth(options):
    """Called by the SDK on each metrics export cycle."""
    depth = random.randint(0, 200)   # replace with real queue.qsize() call
    yield metrics.Observation(depth, {"queue": "orders"})

meter.create_observable_gauge(
    name="orders.queue.depth",
    callbacks=[_observe_queue_depth],
    unit="1",
    description="Current depth of the orders processing queue",
)


def record_checkout(status: str, latency_ms: float, payment_method: str) -> None:
    """
    Record metrics.  Labels (attributes) must be LOW cardinality — only values
    from a small, bounded set.  Good: status, payment_method.  Bad: user_id.
    """
    attrs = {
        "status": status,                       # "success" | "failure" | "timeout"
        "payment.method": payment_method,       # "card" | "paypal" | "crypto"
    }
    orders_counter.add(1, attrs)               # increment by 1
    checkout_latency.record(latency_ms, attrs) # observe a single data point


# =============================================================================
# SECTION 8 — Context propagation across HTTP (manual)
# =============================================================================

def make_http_call_with_propagation(url: str, payload: dict) -> None:
    """
    When calling a downstream service manually (not via auto-instrumented lib),
    inject the current trace context into the outgoing HTTP headers.
    """
    import urllib.request, json

    headers: dict = {}
    # inject() reads the active span from contextvars and writes traceparent header.
    from opentelemetry import propagate
    propagate.inject(headers)   # headers now contains 'traceparent' and 'baggage'

    with tracer.start_as_current_span("http.client.call", kind=SpanKind.CLIENT) as span:
        span.set_attribute(SpanAttributes.HTTP_URL, url)
        span.set_attribute(SpanAttributes.HTTP_METHOD, "POST")

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers=headers,           # downstream service can extract span context
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, resp.status)
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR)
            raise


# =============================================================================
# SECTION 9 — Auto-instrumentation
# =============================================================================

def configure_auto_instrumentation(app) -> None:
    """
    Auto-instrumentation patches popular libraries at import time.
    Each call to instrument() installs OTel interceptors that:
      - Create spans for every incoming/outgoing request automatically.
      - Attach semantic convention attributes (url, method, status_code, etc.).
      - Propagate context through the call chain.

    Call AFTER set_tracer_provider() and BEFORE the app starts serving requests.
    """
    # Instruments all FastAPI routes with server spans.
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="health,readyz",   # skip liveness/readiness probes
        server_request_hook=_request_hook,
    )

    # Instruments SQLAlchemy — captures every SQL query as a child span.
    SQLAlchemyInstrumentor().instrument(
        enable_commenter=True,   # appends /*traceparent=...*/ comment to SQL
    )

    # Instruments redis-py — captures GET/SET/DEL operations.
    RedisInstrumentor().instrument()


def _request_hook(span: trace.Span, scope: dict) -> None:
    """
    Custom hook called by FastAPIInstrumentor for each request.
    Enrich spans with business context that the library cannot infer.
    """
    if span and span.is_recording():
        # Add tenant ID from a custom header — critical for multi-tenant SaaS.
        tenant_id = scope.get("headers", {}).get("x-tenant-id", "unknown")
        span.set_attribute("tenant.id", tenant_id)


# =============================================================================
# SECTION 10 — OTel Collector configuration (reference YAML, not Python)
# =============================================================================

COLLECTOR_CONFIG_YAML = """
# otel-collector-config.yaml
# Run: docker run -v $(pwd)/config.yaml:/etc/otelcol/config.yaml otel/opentelemetry-collector

receivers:
  otlp:                          # accept OTLP from SDKs
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317  # gRPC port (default)
      http:
        endpoint: 0.0.0.0:4318  # HTTP/JSON port
  prometheus:                    # scrape Prometheus targets
    config:
      scrape_configs:
        - job_name: 'app-metrics'
          static_configs:
            - targets: ['app:8080']

processors:
  batch:                         # batch before export — reduces connections
    timeout: 1s
    send_batch_size: 1024
  memory_limiter:                # prevent Collector OOM
    check_interval: 1s
    limit_mib: 400
  resource:                      # add/override resource attributes
    attributes:
      - key: environment
        value: production
        action: upsert
  filter/drop_health:            # drop noisy health-check spans
    traces:
      span:
        - 'attributes["http.route"] == "/health"'
  attributes/redact:             # scrub PII before export
    actions:
      - key: http.request.header.authorization
        action: delete

exporters:
  otlp/tempo:                    # send traces to Grafana Tempo
    endpoint: tempo:4317
    tls: {insecure: true}
  prometheusremotewrite:         # send metrics to Thanos
    endpoint: http://thanos-receive:10908/api/v1/receive
  loki:                          # send logs to Grafana Loki
    endpoint: http://loki:3100/loki/api/v1/push

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, filter/drop_health, batch]
      exporters: [otlp/tempo]
    metrics:
      receivers: [otlp, prometheus]
      processors: [memory_limiter, resource, batch]
      exporters: [prometheusremotewrite]
    logs:
      receivers: [otlp]
      processors: [memory_limiter, attributes/redact, batch]
      exporters: [loki]
"""


# =============================================================================
# SECTION 11 — Grafana Alloy as Collector replacement
# =============================================================================

ALLOY_CONFIG_RIVER = """
// Grafana Alloy config (River syntax) — replacement for OTel Collector
// Alloy is a programmable, Prometheus-native pipeline with OTel compatibility.

otelcol.receiver.otlp "default" {
  grpc { endpoint = "0.0.0.0:4317" }
  output {
    traces  = [otelcol.processor.batch.default.input]
    metrics = [otelcol.processor.batch.default.input]
    logs    = [otelcol.processor.batch.default.input]
  }
}

otelcol.processor.batch "default" {
  output {
    traces  = [otelcol.exporter.otlp.tempo.input]
    metrics = [prometheus.remote_write.thanos.receiver]
    logs    = [loki.write.default.receiver]
  }
}

// Traces → Tempo
otelcol.exporter.otlp "tempo" {
  client { endpoint = "tempo:4317" }
}

// Metrics → Thanos via remote_write
prometheus.remote_write "thanos" {
  endpoint { url = "http://thanos:10908/api/v1/receive" }
}
"""


# =============================================================================
# SECTION 12 — Migrating from OpenTracing / OpenCensus
# =============================================================================

def migration_shim_example():
    """
    OTel provides compatibility shims for OpenTracing and OpenCensus.

    OpenTracing shim (pip install opentelemetry-shim-opentracing):
      - Wrap the OTel TracerProvider as an OpenTracing Tracer.
      - Old code calls opentracing.tracer.start_span() which creates OTel spans.
      - Remove shim library by library as you migrate each module.

    OpenCensus shim (pip install opentelemetry-shim-opencensus):
      - opencensus.trace.tracer.Tracer backed by OTel under the hood.
      - opencensus metrics → OTel metrics bridge.

    Migration strategy:
      1. Install OTel SDK + shim alongside existing tracing library.
      2. Configure OTel TracerProvider (Section 2 above).
      3. Shim makes old library calls produce OTel spans.
      4. Migrate individual modules to native OTel API over several sprints.
      5. Remove shim once all code uses opentelemetry.trace directly.
    """
    # OpenTracing shim example (code shown for illustration — requires shim pkg).
    try:
        from opentelemetry.shim.opentracing_shim import create_tracer
        import opentracing
        # Legacy code continues to work, spans go to OTel backend.
        ot_tracer = create_tracer(trace.get_tracer_provider())
        opentracing.tracer = ot_tracer
        with ot_tracer.start_active_span("legacy_span") as scope:
            scope.span.set_tag("legacy.tag", "value")   # maps to OTel attribute
    except ImportError:
        logger.info("OpenTracing shim not installed — skipping migration example")


# =============================================================================
# SECTION 13 — Baggage: cross-cutting key-value propagation
# =============================================================================

def set_and_read_baggage():
    """
    Baggage travels alongside the trace context through all service hops.
    Use for low-cardinality, non-secret business context (tenant_id, feature_flag).
    NEVER put PII or secrets in baggage — it is visible in headers.
    """
    # Set baggage in the current context.
    ctx = baggage.set_baggage("tenant.id", "acme-corp")
    ctx = baggage.set_baggage("feature.flag", "new_checkout_v2", context=ctx)

    # Attach the enriched context to the current execution.
    token = context.attach(ctx)
    try:
        # Downstream auto-instrumented HTTP calls propagate baggage headers automatically.
        tenant = baggage.get_baggage("tenant.id")
        logger.info("Processing request for tenant %s", tenant)
    finally:
        context.detach(token)   # always detach to avoid context leaks in thread pools


# =============================================================================
# SECTION 14 — Full initialization entry point
# =============================================================================

def initialize_observability() -> None:
    """
    Call this ONCE at application startup, before creating the WSGI/ASGI app.
    Order matters: Resource → Tracing → Metrics → Logging → Propagation.
    """
    resource = build_resource()
    setup_tracing(resource)
    setup_metrics(resource)
    setup_logging(resource)
    setup_propagation()
    logger.info(
        "OpenTelemetry initialized",
        extra={
            "service": "checkout-service",
            "otel.collector": os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317"),
        },
    )


# =============================================================================
# DEMO — run standalone to see console output
# =============================================================================

if __name__ == "__main__":
    # Use console exporters for local testing (no Collector needed).
    resource = build_resource()

    provider = TracerProvider(resource=resource, sampler=ALWAYS_ON)
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)

    reader = PeriodicExportingMetricReader(ConsoleMetricExporter(), export_interval_millis=5_000)
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))

    logging.basicConfig(level=logging.INFO)

    # Re-get tracer/meter after providers are installed.
    tracer = trace.get_tracer("checkout.service")
    meter = metrics.get_meter("checkout.service")
    orders_counter = meter.create_counter("orders.processed", unit="1")
    checkout_latency = meter.create_histogram("checkout.duration", unit="ms")

    # Simulate 5 orders flowing through the system.
    for i in range(5):
        start = time.perf_counter()
        try:
            result = process_order(f"order-{i:04d}", f"user-{i}", round(random.uniform(10, 500), 2))
            elapsed_ms = (time.perf_counter() - start) * 1000
            record_checkout("success", elapsed_ms, "card")
            logger.info("Order processed: %s", result)
        except Exception as exc:
            logger.error("Order failed: %s", exc)

    time.sleep(6)   # wait for metric export cycle
    trace.get_tracer_provider().shutdown()
    metrics.get_meter_provider().shutdown()
