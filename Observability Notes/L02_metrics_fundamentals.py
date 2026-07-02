# =============================================================================
# WHAT: Metrics Fundamentals — Prometheus data model, metric types, PromQL,
#       Python prometheus-client, USE/RED methods, naming conventions.
# WHY:  Metrics are the cheapest observability signal at scale. They give you
#       aggregated numerical insight into system health without the storage cost
#       of logs or traces. Prometheus has become the de-facto standard.
# LEVEL: Intermediate — assumes Python familiarity; no prior Prometheus needed.
# =============================================================================

# ── CONCEPT OVERVIEW ─────────────────────────────────────────────────────────
#
# THE THREE PILLARS OF OBSERVABILITY
#   1. Metrics  — aggregated numerical measurements over time (cheap, fast)
#   2. Logs     — discrete timestamped events with full context (verbose, rich)
#   3. Traces   — end-to-end request flows across services (expensive, precise)
#
# Each pillar answers a different question:
#   Metrics → "Is something wrong right now?" (dashboard, alerting)
#   Logs    → "What exactly happened?"        (debugging)
#   Traces  → "Where in the system is it slow?"(latency attribution)
#
# PROMETHEUS DATA MODEL
#   Every metric is a time series identified by:
#     metric_name{label_key="label_value", ...} value timestamp
#   Example:
#     http_requests_total{method="GET", status="200", service="api"} 42038 1719800000
#
# PROMETHEUS PULL MODEL
#   Prometheus *scrapes* /metrics endpoints at a configured interval (e.g. 15s).
#   This is the opposite of push-based systems (StatsD, InfluxDB telegraf push).
#   Pull advantage: Prometheus detects if a target is down (scrape failure).
#   Push advantage: useful for short-lived jobs (use pushgateway for these).
#
# ── PRODUCTION USE CASE ──────────────────────────────────────────────────────
#   A payment processing API exposes Prometheus metrics. Grafana dashboards
#   show real-time request rate, error rate, and p99 latency. Alertmanager
#   fires PagerDuty when error rate > 1% for 5 minutes. The on-call engineer
#   uses PromQL to drill into which endpoint and which downstream service
#   is responsible, all without touching logs initially.
#
# ── COMMON MISTAKES ──────────────────────────────────────────────────────────
#   1. Using a Gauge where you need a Counter (Gauges can go down, losing info)
#   2. High-cardinality labels (user_id, session_id) → millions of time series
#   3. Not using base units (use seconds, not milliseconds; bytes, not megabytes)
#   4. Missing _total suffix on counters (Prometheus convention)
#   5. Histograms with wrong bucket boundaries → quantile estimates are useless
#   6. rate() on a Gauge — rate() is only valid for Counters
#   7. irate() for alerting — it's too spiky; use rate() with a longer window
# =============================================================================

import time
import random
import threading
from typing import Dict, List

# prometheus_client is the official Python client for Prometheus
# pip install prometheus-client
from prometheus_client import (
    Counter,        # Monotonically increasing counter (requests, errors, bytes)
    Gauge,          # Instantaneous value that can go up or down (queue depth, active connections)
    Histogram,      # Samples observations into configurable buckets (latency, request size)
    Summary,        # Calculates streaming φ-quantiles (similar to Histogram, less flexible)
    start_http_server,  # Starts a background HTTP server exposing /metrics
    push_to_gateway,    # For short-lived jobs: push metrics to Pushgateway
    CollectorRegistry,  # Registry that holds all metrics; default is REGISTRY
    REGISTRY,
    Info,           # Key-value pairs for static metadata (version, build info)
    Enum,           # State machine metric (one of a set of states)
)


# =============================================================================
# SECTION 1: METRIC TYPES
# =============================================================================

# ── Counter ───────────────────────────────────────────────────────────────────
# A Counter only goes up (or resets to zero on process restart).
# Use for: total requests, total errors, total bytes sent, tasks completed.
# NEVER use for: things that can decrease (use Gauge for that).
#
# Naming convention: always end with _total
# Unit suffix: include unit before _total → http_request_duration_seconds_total (wrong)
#              → http_requests_total (correct; duration goes on Histogram, not Counter)

REQUEST_COUNTER = Counter(
    name="http_requests_total",                 # metric name (snake_case)
    documentation="Total HTTP requests received",  # shown in /metrics as HELP
    labelnames=["method", "endpoint", "status_code"],  # dimensions for slicing
)

ERROR_COUNTER = Counter(
    name="http_errors_total",
    documentation="Total HTTP errors by type",
    labelnames=["method", "endpoint", "error_type"],
)

BYTES_SENT_COUNTER = Counter(
    name="http_response_bytes_total",
    documentation="Total bytes sent in HTTP responses",
    labelnames=["endpoint"],
)


# ── Gauge ─────────────────────────────────────────────────────────────────────
# A Gauge can go up or down. It represents a current state/snapshot.
# Use for: queue depth, active connections, memory usage, temperature, in-flight requests.
# Key methods: .set(v), .inc(), .dec(), .set_to_current_time()

ACTIVE_REQUESTS_GAUGE = Gauge(
    name="http_requests_active",
    documentation="Number of HTTP requests currently being processed",
    labelnames=["endpoint"],
)

QUEUE_DEPTH_GAUGE = Gauge(
    name="job_queue_depth",
    documentation="Number of jobs waiting in the processing queue",
    labelnames=["queue_name"],
)

MEMORY_USAGE_GAUGE = Gauge(
    name="process_memory_bytes",
    documentation="Current process memory usage in bytes",
)


# ── Histogram ─────────────────────────────────────────────────────────────────
# Histograms observe values and count them in configurable buckets.
# Expose: _bucket{le="..."}, _count, _sum
# Use for: latency (almost always), request/response size.
# Choose bucket boundaries based on your SLOs. Common for web: .005 .01 .025 .05 .1 .25 .5 1 2.5 5 10
#
# MISTAKE: Default buckets (.005 to 10 seconds) are wrong for many use cases.
#          A database with p99 = 2ms needs buckets like .001 .002 .005 .01 .025
#          A batch job with p99 = 30s needs buckets up to 60+.

REQUEST_LATENCY_HISTOGRAM = Histogram(
    name="http_request_duration_seconds",       # always _seconds for time
    documentation="HTTP request latency in seconds",
    labelnames=["method", "endpoint"],
    buckets=[                                   # define boundaries for your SLO
        0.005, 0.010, 0.025, 0.050,            # < 50ms: fast API responses
        0.100, 0.250, 0.500,                   # < 500ms: acceptable
        1.0, 2.5, 5.0, 10.0,                  # > 1s: degraded
    ],
)

DB_QUERY_LATENCY_HISTOGRAM = Histogram(
    name="db_query_duration_seconds",
    documentation="Database query latency in seconds",
    labelnames=["query_type", "table"],
    buckets=[0.001, 0.002, 0.005, 0.010, 0.025, 0.050, 0.100, 0.500],
)


# ── Summary ───────────────────────────────────────────────────────────────────
# Summary calculates streaming quantiles on the client side.
# Expose: _count, _sum, {quantile="0.5"}, {quantile="0.9"}, {quantile="0.99"}
#
# PREFER Histogram over Summary because:
#   - Histogram quantiles can be aggregated across instances with histogram_quantile()
#   - Summary quantiles CANNOT be aggregated (each instance computes independently)
#   - Histogram lets you change quantiles in PromQL without redeploying
# Use Summary only when: you need exact quantiles for a single-instance service.

RESPONSE_SIZE_SUMMARY = Summary(
    name="http_response_size_bytes",
    documentation="HTTP response size in bytes",
    labelnames=["endpoint"],
)


# ── Info & Enum ───────────────────────────────────────────────────────────────
# Info: expose static key-value metadata as a Gauge{...}=1
# Enum: expose current state from a known set of states

BUILD_INFO = Info(
    name="build",
    documentation="Build information for this service",
)

SERVICE_STATE = Enum(
    name="service_state",
    documentation="Current state of the service",
    states=["starting", "healthy", "degraded", "stopped"],
)


# =============================================================================
# SECTION 2: LABELS / DIMENSIONS — power and danger
# =============================================================================
#
# Labels let you slice and aggregate metrics across dimensions.
# Rule: keep cardinality LOW. Each unique label combination = one time series.
#
# GOOD labels (bounded cardinality):
#   method: GET, POST, PUT, DELETE         (~4 values)
#   status_code: 200, 400, 404, 500        (~10 values)
#   endpoint: /api/v1/users, /api/v1/orders (~50 values)
#   region: us-east-1, eu-west-1           (~5 values)
#
# BAD labels (unbounded cardinality — will OOM Prometheus):
#   user_id:      millions of unique users
#   session_id:   changes per session
#   trace_id:     unique per request
#   ip_address:   unbounded
#
# MISTAKE: labelnames=["user_id"] on a counter touched per request = disaster


def simulate_http_request(method: str, endpoint: str) -> Dict:
    """Simulate processing an HTTP request and record metrics."""

    # Track active requests: increment on entry, decrement on exit
    ACTIVE_REQUESTS_GAUGE.labels(endpoint=endpoint).inc()

    start_time = time.time()   # record wall-clock start for latency calculation

    try:
        # Simulate work with random latency (50–500ms)
        time.sleep(random.uniform(0.05, 0.5))

        # Randomly inject errors (5% error rate)
        if random.random() < 0.05:
            raise ValueError("Simulated upstream timeout")

        status_code = "200"
        response_body = {"status": "ok", "data": [1, 2, 3]}
        response_bytes = 128

        # Record successful request
        REQUEST_COUNTER.labels(
            method=method,
            endpoint=endpoint,
            status_code=status_code,
        ).inc()                                # increment by 1 (default)

        BYTES_SENT_COUNTER.labels(endpoint=endpoint).inc(response_bytes)

        return {"status": status_code, "body": response_body}

    except Exception as e:
        status_code = "500"
        error_type = type(e).__name__

        REQUEST_COUNTER.labels(
            method=method,
            endpoint=endpoint,
            status_code=status_code,
        ).inc()

        ERROR_COUNTER.labels(
            method=method,
            endpoint=endpoint,
            error_type=error_type,
        ).inc()

        return {"status": status_code, "error": str(e)}

    finally:
        elapsed = time.time() - start_time  # total duration in seconds

        # Observe the latency in the histogram — this updates all relevant buckets
        REQUEST_LATENCY_HISTOGRAM.labels(
            method=method,
            endpoint=endpoint,
        ).observe(elapsed)

        # Decrement active request gauge — always in finally so it's not leaked
        ACTIVE_REQUESTS_GAUGE.labels(endpoint=endpoint).dec()


# Context manager pattern for automatic latency tracking
def track_latency_context_manager_example():
    """Histogram and Summary have a .time() context manager."""

    # Using context manager — automatically calls .observe(elapsed) on exit
    with REQUEST_LATENCY_HISTOGRAM.labels(method="GET", endpoint="/health").time():
        time.sleep(0.01)  # simulated work inside the context

    # Equivalent decorator pattern for functions
    # @REQUEST_LATENCY_HISTOGRAM.labels(method="GET", endpoint="/users").time()
    # def get_users(): ...


# =============================================================================
# SECTION 3: PROMQL FUNDAMENTALS
# =============================================================================
#
# PromQL is Prometheus's query language. Key concepts:
#
# INSTANT VECTOR: current value of each time series matching a selector
#   http_requests_total                          → all series
#   http_requests_total{method="GET"}            → filtered
#   http_requests_total{status_code=~"5.."}      → regex match
#   http_requests_total{endpoint!="/health"}     → negative match
#
# RANGE VECTOR: values over a time range (required by rate/irate/increase)
#   http_requests_total[5m]                      → last 5 minutes of data
#
# ── rate() ────────────────────────────────────────────────────────────────────
# rate(counter[window]) → per-second average rate over the window.
# Handles counter resets (process restarts) automatically.
# Use a window of at least 4x the scrape interval (scrape=15s → window>=1m).
# BEST FOR: alerting, dashboards, smooth graphs.
#
#   rate(http_requests_total[5m])
#   → smoothed per-second request rate over last 5 minutes
#
# ── irate() ───────────────────────────────────────────────────────────────────
# irate(counter[window]) → instantaneous rate using last 2 data points only.
# Very responsive but spiky — NOT good for alerting.
# BEST FOR: real-time debugging, short-lived spikes.
#
#   irate(http_requests_total[5m])
#   → per-second rate between the last two scrapes within the 5m window
#
# ── increase() ────────────────────────────────────────────────────────────────
# increase(counter[window]) → total increase over the window (rate * duration).
# Useful for "how many requests in the last hour?"
#
#   increase(http_requests_total[1h])
#   → total requests in the past hour
#
# ── histogram_quantile() ──────────────────────────────────────────────────────
# histogram_quantile(φ, rate(histogram_bucket[window]))
# φ = 0.99 means p99 (99th percentile)
#
#   histogram_quantile(0.99,
#     rate(http_request_duration_seconds_bucket[5m]))
#   → p99 latency over last 5 minutes, per endpoint and method
#
#   histogram_quantile(0.99,
#     sum by (endpoint) (rate(http_request_duration_seconds_bucket[5m])))
#   → p99 latency aggregated across all instances, grouped by endpoint
#
# MISTAKE: Applying histogram_quantile to a Summary's _bucket (Summaries don't
#          have _bucket series, so this silently returns wrong results).
#
# ── Aggregation: by / without ─────────────────────────────────────────────────
# sum by (endpoint) (rate(http_requests_total[5m]))
#   → one series per endpoint, summed across all methods/status_codes
#
# sum without (instance, pod) (rate(http_requests_total[5m]))
#   → remove instance/pod labels, keep all others (useful for cross-pod agg)
#
# Other aggregators: avg, min, max, count, topk, bottomk
#
#   topk(5, sum by (endpoint) (rate(http_requests_total[5m])))
#   → top 5 busiest endpoints by request rate

PROMQL_EXAMPLES = {
    # Error rate as a percentage
    "error_rate_pct": """
        100 * sum(rate(http_errors_total[5m])) by (endpoint)
            / sum(rate(http_requests_total[5m])) by (endpoint)
    """,

    # p99 latency per endpoint (aggregated across all instances)
    "p99_latency": """
        histogram_quantile(0.99,
          sum by (endpoint, le) (
            rate(http_request_duration_seconds_bucket[5m])
          )
        )
    """,

    # Availability (non-5xx / total)
    "availability": """
        sum(rate(http_requests_total{status_code!~"5.."}[5m])) by (service)
            / sum(rate(http_requests_total[5m])) by (service)
    """,

    # Saturation: queue depth > 1000 for more than 2 minutes
    "queue_saturation_alert": """
        job_queue_depth{queue_name="payments"} > 1000
    """,

    # USE Method: Utilization — CPU utilization per instance
    "cpu_utilization": """
        1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))
    """,
}


# =============================================================================
# SECTION 4: RECORDING RULES AND ALERTING RULES
# =============================================================================
#
# Recording rules precompute expensive PromQL queries and store results as new
# time series. This makes dashboards and alerts load fast.
#
# Rule file format (YAML, loaded by Prometheus):
#
# groups:
#   - name: http_recording_rules
#     interval: 30s                          # how often to evaluate
#     rules:
#       - record: job:http_requests:rate5m   # naming: level:metric:operation
#         expr: sum by (job) (rate(http_requests_total[5m]))
#
#       - record: job:http_errors:rate5m
#         expr: sum by (job) (rate(http_errors_total[5m]))
#
#       - record: job:http_error_rate:ratio5m
#         expr: |
#           job:http_errors:rate5m
#             / job:http_requests:rate5m
#
# Alerting rules: evaluated by Prometheus, sent to Alertmanager.
# An alert goes through states: inactive → PENDING → FIRING
#   PENDING: condition is true but hasn't been true for 'for' duration yet
#   FIRING:  condition has been true for the full 'for' duration → sent to Alertmanager
#
# groups:
#   - name: http_alerts
#     rules:
#       - alert: HighErrorRate
#         expr: job:http_error_rate:ratio5m > 0.01   # > 1% error rate
#         for: 5m                                     # must be true for 5 min
#         labels:
#           severity: critical
#           team: backend
#         annotations:
#           summary: "High error rate on {{ $labels.job }}"
#           description: "Error rate is {{ $value | humanizePercentage }}"
#           runbook_url: "https://runbooks.internal/http-errors"

ALERTING_RULES_YAML_EXAMPLE = """
groups:
  - name: api_health
    rules:

      # Alert: error rate > 1% for 5 minutes
      - alert: APIHighErrorRate
        expr: |
          (
            sum by (service) (rate(http_errors_total[5m]))
            / sum by (service) (rate(http_requests_total[5m]))
          ) > 0.01
        for: 5m
        labels:
          severity: page          # used by Alertmanager to route to PagerDuty
          team: platform
        annotations:
          summary: "{{ $labels.service }} error rate {{ $value | humanizePercentage }}"
          runbook_url: "https://runbooks.example.com/api-high-error-rate"

      # Alert: p99 latency > 500ms for 10 minutes
      - alert: APIHighLatency
        expr: |
          histogram_quantile(0.99,
            sum by (service, le) (
              rate(http_request_duration_seconds_bucket[5m])
            )
          ) > 0.5
        for: 10m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "{{ $labels.service }} p99 latency {{ $value | humanizeDuration }}"
          runbook_url: "https://runbooks.example.com/api-high-latency"
"""


# =============================================================================
# SECTION 5: USE METHOD and RED METHOD
# =============================================================================
#
# USE METHOD (Brendan Gregg) — for every RESOURCE:
#   U = Utilization  : % time resource is busy (CPU: 80%, disk: 95%)
#   S = Saturation   : extra work queued because resource is at capacity
#   E = Errors       : error events (disk I/O errors, network packet drops)
#
# Systematic: apply to CPU, memory, disk I/O, network interfaces, databases.
# Helps find RESOURCE BOTTLENECKS (why is the system slow/unavailable?).

def use_method_metrics_setup():
    """Metrics structured around the USE method for a database connection pool."""
    # U — Utilization: connections in use / total connections
    db_connections_active = Gauge(
        "db_connections_active", "Active (in-use) DB connections", ["pool"]
    )
    db_connections_total = Gauge(
        "db_connections_total", "Total DB connections in pool", ["pool"]
    )
    # utilization = db_connections_active / db_connections_total (computed in PromQL)

    # S — Saturation: requests waiting for a connection
    db_connection_wait_queue = Gauge(
        "db_connection_wait_queue_depth",
        "Requests waiting for a DB connection",
        ["pool"],
    )
    db_connection_wait_seconds = Histogram(
        "db_connection_wait_seconds",
        "Time spent waiting for a DB connection",
        ["pool"],
        buckets=[0.001, 0.005, 0.010, 0.050, 0.1, 0.5, 1.0],
    )

    # E — Errors: connection errors, query errors, timeouts
    db_errors_total = Counter(
        "db_errors_total",
        "Total DB errors",
        ["pool", "error_type"],  # error_type: connection_timeout, query_error, etc.
    )
    return (db_connections_active, db_connections_total,
            db_connection_wait_queue, db_connection_wait_seconds, db_errors_total)


#
# RED METHOD (Tom Wilkie) — for every INBOUND REQUEST (microservices):
#   R = Rate     : requests per second
#   E = Errors   : failed requests per second (or error ratio)
#   D = Duration : latency distribution (histogram)
#
# Simpler than USE, more applicable to services than resources.
# These three metrics answer: "Is my service working for users?"
#
# The http_requests_total, http_errors_total, and http_request_duration_seconds
# metrics defined above ARE the RED metrics. Good naming = intent is clear.


# =============================================================================
# SECTION 6: METRICS NAMING CONVENTIONS
# =============================================================================
#
# Prometheus naming conventions (critical for interoperability):
#
# Format:   {namespace}_{subsystem}_{name}_{unit}
#   namespace: service or team prefix (e.g., "payment", "myapp")
#   subsystem: component within the service (e.g., "http", "db", "cache")
#   name:      what is being measured (e.g., "requests", "duration", "errors")
#   unit:      base unit suffix (e.g., "seconds", "bytes", "total")
#
# BASE UNITS (always use these, never milliseconds or megabytes):
#   Time:     _seconds          (not _ms, not _milliseconds)
#   Size:     _bytes            (not _kb, not _megabytes)
#   Count:    _total (Counters) (not _count, not _num)
#   Ratio:    _ratio            (0.0 to 1.0, not percentage)
#   Temp:     _celsius
#
# GOOD names:
#   http_requests_total
#   http_request_duration_seconds
#   process_resident_memory_bytes
#   node_cpu_seconds_total
#   db_connection_pool_size
#
# BAD names:
#   http_request_count           # missing _total suffix on counter
#   request_latency_ms           # wrong unit (ms instead of seconds)
#   mem_usage_mb                 # wrong unit (mb instead of bytes)
#   HTTPRequests                 # camelCase instead of snake_case


GOOD_NAMING_EXAMPLES: List[str] = [
    "http_requests_total",                          # Counter: requests
    "http_request_duration_seconds",               # Histogram: latency
    "http_response_size_bytes",                    # Histogram: size
    "process_resident_memory_bytes",               # Gauge: memory
    "db_connections_active",                       # Gauge: connections
    "cache_hits_total",                            # Counter: cache hits
    "cache_misses_total",                          # Counter: cache misses
    "message_queue_depth",                         # Gauge: queue depth
    "background_job_duration_seconds",             # Histogram: job latency
    "grpc_server_handled_total",                   # Counter (gRPC convention)
]


# =============================================================================
# SECTION 7: PUSH vs PULL MODEL
# =============================================================================
#
# PULL MODEL (Prometheus default):
#   Prometheus scrapes /metrics endpoint of each target.
#   Pros: Prometheus controls scrape rate; dead targets are detected (scrape fails);
#         easier firewall rules (Prometheus initiates connections).
#   Cons: Short-lived jobs finish before scrape; need network access from Prometheus.
#
# PUSH MODEL (Pushgateway):
#   Short-lived jobs (batch scripts, cron jobs) push metrics to Pushgateway,
#   which Prometheus then scrapes. Pushgateway persists last-pushed values.
#   Cons: Pushgateway is a single point of failure; staleness not auto-detected.
#   Use only for: batch jobs, cron jobs, CI/CD pipelines.

def push_batch_job_metrics():
    """Example: push metrics from a short-lived batch job to Pushgateway."""

    # Create a fresh registry so we only push this job's metrics
    registry = CollectorRegistry()

    jobs_processed = Counter(
        "batch_jobs_processed_total",
        "Total jobs processed in this batch run",
        registry=registry,
    )
    batch_duration = Gauge(
        "batch_run_duration_seconds",
        "Duration of the batch run",
        registry=registry,
    )

    start = time.time()
    jobs_processed.inc(1000)                        # simulated: 1000 jobs done
    batch_duration.set(time.time() - start)

    # Push to Pushgateway — grouped by job name
    # push_to_gateway(
    #     gateway="http://pushgateway:9091",
    #     job="daily_report_generator",
    #     registry=registry,
    # )
    print("Would push metrics to Pushgateway (not running in this demo)")


# =============================================================================
# SECTION 8: RUNNING THE METRICS SERVER
# =============================================================================

def main():
    """Start a Prometheus metrics HTTP server and generate synthetic traffic."""

    # Set static build info (will show as build_info{version="1.2.3",...}=1)
    BUILD_INFO.info({
        "version": "1.2.3",
        "commit": "abc123def",
        "build_date": "2026-01-15",
        "go_version": "n/a",  # Python service, not Go
    })

    SERVICE_STATE.state("starting")

    # Start the HTTP server on port 8000; /metrics endpoint available immediately
    # This runs in a daemon thread — it won't block the main thread
    start_http_server(8000)
    print("Metrics server started at http://localhost:8000/metrics")

    SERVICE_STATE.state("healthy")

    endpoints = ["/api/v1/users", "/api/v1/orders", "/api/v1/products"]
    methods = ["GET", "POST", "DELETE"]

    # Simulate ongoing traffic so metrics accumulate
    for i in range(50):
        method = random.choice(methods)
        endpoint = random.choice(endpoints)
        result = simulate_http_request(method, endpoint)

        # Update queue depth gauge with a random value (simulated)
        QUEUE_DEPTH_GAUGE.labels(queue_name="orders").set(random.randint(0, 200))

        if i % 10 == 0:
            print(f"Request {i}: {method} {endpoint} → {result['status']}")

        time.sleep(0.1)                             # throttle simulation

    print("\nDone. Visit http://localhost:8000/metrics to see exported metrics.")
    print("Key metrics to check:")
    print("  http_requests_total")
    print("  http_request_duration_seconds_bucket")
    print("  http_requests_active")


if __name__ == "__main__":
    main()
