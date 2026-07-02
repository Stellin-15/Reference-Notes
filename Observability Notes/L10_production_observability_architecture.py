# =============================================================================
# WHAT: Full production observability stack design — metrics/logging/tracing
#       pipelines, Grafana as unified frontend, multi-tenancy, cost control,
#       on-call workflow, SRE runbook template, blameless post-mortem process,
#       and observability-driven development.
# WHY:  Individual tools (Prometheus, Loki, Tempo) are only useful when wired
#       together with a coherent architecture, clear ownership, and a repeatable
#       on-call process.  This file is the "everything fits together" capstone.
# LEVEL: Advanced (assumes familiarity with L05–L07)
# =============================================================================

# ---------------------------------------------------------------------------
# CONCEPT OVERVIEW
# ---------------------------------------------------------------------------
# The three pillars of observability — metrics, logs, traces — are only
# powerful when they are CORRELATED.  A complete observability stack:
#
#   Metrics  → Prometheus (scrape) → Thanos (long-term, multi-cluster) → Grafana
#   Logs     → Application → Fluent Bit (agent) → Kafka (buffer) → Logstash
#                → Elasticsearch → Grafana/Kibana
#   Traces   → OTel SDK → OTel Collector → Grafana Tempo → Grafana
#
#   Correlation is the secret sauce:
#     - Every log line carries trace_id + span_id (OTel log bridge).
#     - Every Prometheus metric series carries job + instance labels that match
#       Kubernetes pod labels, linking metrics to pod logs.
#     - Grafana Explore links a Tempo trace to the Loki logs from the same
#       time window and service automatically (via derived fields / data links).
#
# Total Cost of Ownership is the hardest part to control at scale:
#   - Metrics cardinality (high-value labels × values) drives Prometheus memory.
#   - Log volume (verbosity × throughput × retention) drives storage costs.
#   - Trace storage (spans × sampling rate × retention) — sample aggressively.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# PRODUCTION USE CASE
# ---------------------------------------------------------------------------
# A SaaS platform with 50+ microservices, 3 AWS regions, multi-tenant.
# Requirements:
#   - 13-month metric retention (for YoY comparisons and billing audits).
#   - 30-day log retention in hot storage; 1 year in cold (S3 Glacier).
#   - Trace retention: 7 days (enough for incident investigation).
#   - Per-tenant metric isolation (each tenant sees only their data in Grafana).
#   - SLO alerting: 99.9% uptime per service, p99 < 500ms.
#   - On-call rotation: PagerDuty → Slack → runbook link.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# COMMON MISTAKES
# ---------------------------------------------------------------------------
# 1. No alerting on SLO burn rate (only on raw error rate) — burn-rate alerts
#    give you time to react before the SLO window is exhausted.
# 2. Retaining raw logs indefinitely — costs explode; use tiered storage.
# 3. Scraping Prometheus every 15 s with 10k series per pod → OOM.
# 4. Sending ALL traces to the backend — sample tail-based, not head-based.
# 5. No runbooks linked from alerts — on-call engineers waste time in panic.
# 6. Blameful post-mortems → engineers hide incidents → systemic issues persist.
# 7. Observability as an afterthought — instrument BEFORE the feature ships.
# 8. Not testing dashboards in chaos experiments (they break too).
# 9. Alert fatigue: too many low-quality alerts → on-call ignores everything.
# 10. No end-to-end trace from browser → backend — blind to frontend latency.
# ---------------------------------------------------------------------------

# ── Standard library ────────────────────────────────────────────────────────
import os
import time
import logging
import json
import hashlib
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
from datetime import datetime, timedelta

# ── OTel (instrumentation layer — see L05 for full setup) ────────────────────
from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource, SERVICE_NAME

# ── Third-party ──────────────────────────────────────────────────────────────
# pip install prometheus_client pydantic

logger = logging.getLogger(__name__)


# =============================================================================
# SECTION 1 — ASCII Reference Architecture
# =============================================================================

ARCHITECTURE_DIAGRAM = r"""
╔══════════════════════════════════════════════════════════════════════════════╗
║          PRODUCTION OBSERVABILITY REFERENCE ARCHITECTURE                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
  │  Service A   │   │  Service B   │   │  Service C   │   ← Microservices
  │  OTel SDK    │   │  OTel SDK    │   │  OTel SDK    │     (Python/Go/Java)
  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
         │ OTLP gRPC         │                   │
         ▼                   ▼                   ▼
  ┌────────────────────────────────────────────────────┐
  │             OTel Collector (Daemonset)              │  ← Per-node agent
  │   Receivers: otlp, prometheus scrape               │
  │   Processors: batch, memory_limiter, tail-sample   │
  │   Exporters: → Tempo (traces)                      │
  │              → Prometheus remote-write (metrics)   │
  │              → Loki (logs)                         │
  └────────┬────────────────┬────────────────┬─────────┘
           │                │                │
     TRACES▼          METRICS▼          LOGS ▼
  ┌────────────┐   ┌──────────────┐   ┌────────────────┐
  │   Grafana  │   │  Prometheus  │   │   Fluent Bit   │
  │   Tempo    │   │  (short-term │   │   (DaemonSet)  │
  │  (object   │   │   2 weeks)   │   │   tail + parse │
  │  storage)  │   └──────┬───────┘   └───────┬────────┘
  └──────┬─────┘          │remote_write        │push logs
         │                ▼                   ▼
         │        ┌──────────────┐   ┌────────────────┐
         │        │    Thanos    │   │     Kafka      │
         │        │  Receive     │   │  (log buffer,  │
         │        │  Store       │   │   survives     │
         │        │  Compact     │   │   Logstash     │
         │        │  (S3, 13mo)  │   │   restarts)    │
         │        └──────┬───────┘   └───────┬────────┘
         │               │                   │
         │        METRICS▼             LOGS  ▼
         │        ┌────────────────────────────────────┐
         │        │      Logstash / OpenSearch          │
         │        │  (parse, enrich, index logs)        │
         │        │  hot: 30 days  cold: S3 Glacier 1yr │
         │        └────────────────┬───────────────────┘
         │                         │
         ▼                         ▼
  ┌───────────────────────────────────────────────────────┐
  │                     GRAFANA                           │
  │  Datasources: Tempo | Thanos | Loki | Elasticsearch  │
  │  Features: Correlate traces ↔ logs ↔ metrics         │
  │            SLO dashboards    Alerting → PagerDuty     │
  │            Multi-tenant RBAC  Unified Explore         │
  └───────────────────────────────────────────────────────┘

COST CONTROL LAYER (cross-cutting):
  Metrics:  cardinality guard (drop series > 10k labels)
  Logs:     Fluent Bit sampling (drop DEBUG in prod, keep ERROR always)
  Traces:   tail-based sampling (keep 100% of errors, 1% of success)
"""

print(ARCHITECTURE_DIAGRAM)  # visible when running this file


# =============================================================================
# SECTION 2 — Prometheus metrics pipeline with cardinality guard
# =============================================================================

try:
    from prometheus_client import (
        Counter, Histogram, Gauge, Summary,
        CollectorRegistry, push_to_gateway,
        REGISTRY, generate_latest, CONTENT_TYPE_LATEST,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client not installed — metric examples are illustrative")


class CardinalityGuard:
    """
    Enforces a maximum number of unique label value combinations per metric.
    High cardinality (e.g., user_id label with millions of users) causes
    Prometheus to OOM and makes queries slow.

    Strategy: track label combos seen; if a new combo arrives beyond the limit,
    replace the offending label value with "__overflow__" and alert.
    """

    def __init__(self, max_series: int = 1000, metric_name: str = "unknown"):
        self.max_series = max_series
        self.metric_name = metric_name
        self._seen: set = set()
        self._overflows: int = 0
        self._lock = threading.Lock()

    def sanitize_labels(self, labels: Dict[str, str]) -> Dict[str, str]:
        """
        Check if this label combination is within cardinality budget.
        If over budget, replace high-cardinality values with __overflow__.
        """
        key = hashlib.md5(json.dumps(labels, sort_keys=True).encode()).hexdigest()
        with self._lock:
            if key in self._seen:
                return labels   # known combo — allow through

            if len(self._seen) >= self.max_series:
                self._overflows += 1
                if self._overflows == 1 or self._overflows % 100 == 0:
                    logger.error(
                        "Cardinality limit hit for metric '%s' (%d overflow events). "
                        "Check for high-cardinality labels.",
                        self.metric_name,
                        self._overflows,
                    )
                # Return sanitized labels to avoid blowing up the metric.
                return {k: ("__overflow__" if v not in ("success", "error", "timeout")
                            else v) for k, v in labels.items()}

            self._seen.add(key)
            return labels


# Example: a correctly scoped metric with cardinality protection.
if PROMETHEUS_AVAILABLE:
    REQUEST_LATENCY = Histogram(
        "http_request_duration_seconds",
        "HTTP request latency in seconds",
        labelnames=["method", "route", "status_class"],  # status_class not status_code!
        # status_class = "2xx" / "4xx" / "5xx" — only 3 values, not 500+.
        buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    )
    ACTIVE_REQUESTS = Gauge(
        "http_active_requests",
        "Currently in-flight HTTP requests",
        labelnames=["route"],
    )
    ERROR_TOTAL = Counter(
        "errors_total",
        "Total errors by type and component",
        labelnames=["error_type", "component"],
    )

    latency_guard = CardinalityGuard(max_series=500, metric_name="http_request_duration_seconds")


def record_request(method: str, route: str, status_code: int, duration_s: float) -> None:
    """Record an HTTP request with cardinality-safe labels."""
    if not PROMETHEUS_AVAILABLE:
        return
    status_class = f"{status_code // 100}xx"   # 200 → "2xx", 503 → "5xx"
    labels = latency_guard.sanitize_labels(
        {"method": method, "route": route, "status_class": status_class}
    )
    REQUEST_LATENCY.labels(**labels).observe(duration_s)


# =============================================================================
# SECTION 3 — Logging pipeline: Fluent Bit → Kafka → Logstash → Elasticsearch
# =============================================================================

FLUENTBIT_CONFIG = """
# fluent-bit.conf — DaemonSet configuration
# Deployed as a Kubernetes DaemonSet; one agent per node tails all pod logs.

[SERVICE]
    Flush         5        # flush every 5 seconds
    Daemon        Off
    Log_Level     info
    HTTP_Server   On       # expose /metrics for Prometheus scraping
    HTTP_Listen   0.0.0.0
    HTTP_Port     2020

# Read all container logs from the node.
[INPUT]
    Name              tail
    Tag               kube.*
    Path              /var/log/containers/*.log
    Parser            docker
    DB                /var/log/flb_kube.db    # persist offsets across restarts
    Mem_Buf_Limit     50MB
    Skip_Long_Lines   On
    Refresh_Interval  10

# Parse Kubernetes metadata (namespace, pod name, container name, labels).
[FILTER]
    Name                kubernetes
    Match               kube.*
    Kube_URL            https://kubernetes.default.svc:443
    Kube_CA_File        /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
    Kube_Token_File     /var/run/secrets/kubernetes.io/serviceaccount/token
    Merge_Log           On        # parse nested JSON log messages
    Keep_Log            Off       # remove raw 'log' field after parsing
    Annotations         Off       # don't index pod annotations (noisy)
    Labels              On        # include pod labels for tenant routing

# SAMPLING: drop DEBUG/INFO logs in production (reduce volume 90%+).
# Keep ERROR/CRITICAL always.  Adjust OTEL_LOG_LEVEL at the app level.
[FILTER]
    Name    grep
    Match   kube.*
    Exclude level DEBUG
    Exclude level INFO

# Add environment metadata to every log record.
[FILTER]
    Name    record_modifier
    Match   kube.*
    Record  cluster_name production-us-east-1
    Record  environment  production

# Route to Kafka for buffering and fan-out.
[OUTPUT]
    Name         kafka
    Match        kube.*
    Brokers      kafka-0.kafka:9092,kafka-1.kafka:9092,kafka-2.kafka:9092
    Topics       platform.logs
    rdkafka.socket.keepalive.enable  true
    rdkafka.log.connection.close     false
"""

LOGSTASH_PIPELINE = """
# logstash.conf — consumes from Kafka, enriches, ships to Elasticsearch.

input {
  kafka {
    bootstrap_servers => "kafka-0.kafka:9092,kafka-1.kafka:9092"
    topics            => ["platform.logs"]
    group_id          => "logstash-consumers"
    consumer_threads  => 4
    codec             => "json"
    auto_offset_reset => "earliest"
  }
}

filter {
  # Parse trace_id / span_id from OTel-instrumented Python logs.
  if [trace_id] {
    mutate {
      add_field => { "[@metadata][has_trace]" => true }
    }
  }

  # Derive tenant_id from the Kubernetes namespace label (multi-tenant routing).
  if [kubernetes][labels][tenant] {
    mutate {
      copy => { "[kubernetes][labels][tenant]" => "tenant_id" }
    }
  }

  # Truncate log messages > 10 KB to prevent Elasticsearch mapping explosions.
  if [message] and [message] =~ /.{10240}/ {
    mutate {
      gsub => ["message", "(?<=.{10240}).*", " ...[TRUNCATED]"]
    }
  }

  # Geo-IP lookup for client IPs in access logs.
  if [client_ip] {
    geoip {
      source => "client_ip"
      target => "geoip"
      fields => ["country_name", "city_name", "latitude", "longitude"]
    }
  }
}

output {
  elasticsearch {
    hosts            => ["https://elasticsearch:9200"]
    index            => "logs-%{tenant_id}-%{+YYYY.MM.dd}"
    # ILM policy: hot (SSD, 30d) → warm (HDD, 6mo) → cold (S3, 1yr) → delete
    ilm_enabled      => true
    ilm_policy       => "platform-logs-policy"
    user             => "${ES_USER}"
    password         => "${ES_PASSWORD}"
  }
}
"""


# =============================================================================
# SECTION 4 — Tracing pipeline: OTel SDK → Collector → Tempo
# =============================================================================

TEMPO_CONFIG = """
# tempo.yaml — Grafana Tempo configuration (simplified)
# Tempo stores traces as objects in S3/GCS — dramatically cheaper than Elasticsearch.

server:
  http_listen_port: 3200

distributor:
  receivers:                    # same as OTel Collector exporters
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317

ingester:
  max_block_duration: 5m        # flush to object storage every 5 min

compactor:
  compaction:
    block_retention: 168h       # 7 days of trace retention

storage:
  trace:
    backend: s3
    s3:
      bucket:   traces-production
      endpoint: s3.amazonaws.com
    wal:
      path: /var/tempo/wal      # write-ahead log on fast local disk

# Tail-based sampling (in the OTel Collector, NOT Tempo):
# Keep 100% of error traces.  Sample 1% of success traces.
# This is configured in the Collector's tail_sampling processor (see L05).
"""

OTEL_COLLECTOR_TAIL_SAMPLING = """
# Tail-based sampling processor config for OTel Collector.
# Tail sampling makes decisions AFTER seeing the full trace (vs head sampling
# which decides at the first span).  This allows "always keep error traces".

processors:
  tail_sampling:
    decision_wait: 10s           # wait up to 10s for all spans to arrive
    num_traces: 100000           # in-memory buffer for 100k concurrent traces
    expected_new_traces_per_sec: 1000
    policies:
      - name: errors-policy
        type: status_code
        status_code: {status_codes: [ERROR]}   # keep ALL error traces
      - name: slow-traces-policy
        type: latency
        latency: {threshold_ms: 1000}          # keep ALL traces > 1s
      - name: probabilistic-policy
        type: probabilistic
        probabilistic: {sampling_percentage: 1}  # keep 1% of everything else
"""


# =============================================================================
# SECTION 5 — Multi-tenancy in observability
# =============================================================================

class TenantContext:
    """
    Multi-tenant observability requires isolating data so:
      - Tenant A cannot query Tenant B's metrics/logs/traces.
      - Cost allocation is per-tenant.
      - Retention policies can differ by tenant tier.

    Implementation patterns:
      Metrics:  Thanos + Cortex support per-tenant namespaces.
                Each Prometheus instance has external_labels: {tenant: "acme"}.
      Logs:     Elasticsearch index-per-tenant (logs-acme-2024.01.01).
                Loki uses tenant_id as the stream label + RBAC in Grafana.
      Traces:   Tempo multi-tenancy via X-Scope-OrgID header.
    """

    _local = threading.local()

    @classmethod
    def set(cls, tenant_id: str) -> None:
        cls._local.tenant_id = tenant_id

    @classmethod
    def get(cls) -> str:
        return getattr(cls._local, "tenant_id", "unknown")

    @classmethod
    @contextmanager
    def scope(cls, tenant_id: str):
        """Set tenant context for the duration of a request."""
        old = cls.get()
        cls.set(tenant_id)
        try:
            yield
        finally:
            cls.set(old)


def add_tenant_to_headers(headers: dict) -> dict:
    """
    Inject tenant ID into outgoing OTLP / Loki / Tempo requests.
    Tempo uses X-Scope-OrgID; Loki and Thanos use the same convention.
    """
    tenant = TenantContext.get()
    if tenant and tenant != "unknown":
        headers["X-Scope-OrgID"] = tenant    # Tempo/Cortex/Loki header
        headers["X-Tenant-ID"] = tenant      # custom propagation to downstream
    return headers


# =============================================================================
# SECTION 6 — SLO alerting: burn rate (multi-window, multi-burn-rate)
# =============================================================================

SLO_ALERTS_PROMETHEUS = """
# Prometheus alerting rules implementing the Google SRE book's
# multi-window, multi-burn-rate alerting strategy.
#
# SLO: 99.9% of requests succeed (error budget = 0.1% = 432 min/month).
# Burn rates:
#   14.4× burn → budget exhausted in 5d  → PAGE immediately (critical)
#    6×  burn → budget exhausted in 5d  → PAGE (high)
#    3×  burn → budget exhausted in 10d → TICKET (warning)
#    1×  burn → budget exhausted in 30d → INFORMATIONAL

groups:
  - name: slo_checkout
    rules:
      # Fast burn: 1h and 5m windows both above 14.4× burn rate → critical page.
      - alert: CheckoutHighErrorBurnRate
        expr: |
          (
            sum(rate(http_request_errors_total{service="checkout"}[1h]))
            / sum(rate(http_requests_total{service="checkout"}[1h]))
          ) > 14.4 * 0.001
          and
          (
            sum(rate(http_request_errors_total{service="checkout"}[5m]))
            / sum(rate(http_requests_total{service="checkout"}[5m]))
          ) > 14.4 * 0.001
        for: 2m
        labels:
          severity: critical
          team: checkout
        annotations:
          summary: "High error burn rate for checkout service"
          description: "Burning through error budget at 14.4x rate. Budget exhausted in ~5d."
          runbook_url: "https://runbooks.internal/checkout/high-error-rate"
          dashboard_url: "https://grafana.internal/d/checkout-slo"

      # Slow burn: 6h and 30m windows both above 6× burn rate → page.
      - alert: CheckoutMediumErrorBurnRate
        expr: |
          (
            sum(rate(http_request_errors_total{service="checkout"}[6h]))
            / sum(rate(http_requests_total{service="checkout"}[6h]))
          ) > 6 * 0.001
          and
          (
            sum(rate(http_request_errors_total{service="checkout"}[30m]))
            / sum(rate(http_requests_total{service="checkout"}[30m]))
          ) > 6 * 0.001
        for: 15m
        labels:
          severity: warning
          team: checkout
        annotations:
          summary: "Elevated error burn rate for checkout service"
          runbook_url: "https://runbooks.internal/checkout/high-error-rate"
"""


# =============================================================================
# SECTION 7 — On-call workflow
# =============================================================================

@dataclass
class Incident:
    """
    Structured incident record.  Created when an alert pages.
    Drives the on-call workflow: triage → mitigate → resolve → post-mortem.
    """
    id: str
    title: str
    severity: str              # SEV-1 (all hands) / SEV-2 (on-call) / SEV-3 (ticket)
    service: str
    alert_name: str
    started_at: datetime
    resolved_at: Optional[datetime] = None
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    mitigation_steps: List[str] = field(default_factory=list)
    root_cause: Optional[str] = None
    impacted_users: int = 0

    def add_event(self, description: str, author: str = "system") -> None:
        """Append a timestamped event to the incident timeline."""
        self.timeline.append({
            "timestamp": datetime.utcnow().isoformat(),
            "author": author,
            "description": description,
        })
        logger.info("[Incident %s] %s: %s", self.id, author, description)

    def resolve(self, root_cause: str, author: str = "on-call") -> None:
        self.resolved_at = datetime.utcnow()
        self.root_cause = root_cause
        self.add_event(f"Incident resolved. Root cause: {root_cause}", author)

    @property
    def duration_minutes(self) -> Optional[float]:
        if self.resolved_at:
            return (self.resolved_at - self.started_at).total_seconds() / 60
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "severity": self.severity,
            "service": self.service,
            "started_at": self.started_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "duration_minutes": self.duration_minutes,
            "root_cause": self.root_cause,
            "impacted_users": self.impacted_users,
            "timeline": self.timeline,
        }


ON_CALL_WORKFLOW = """
ON-CALL WORKFLOW (alert → fix, in under 30 minutes for SEV-2)
═══════════════════════════════════════════════════════════════

1. ALERT FIRES (PagerDuty → Slack #incidents)
   - Alert title should answer: "What broke?" (not "High CPU")
   - Runbook link in alert body: click immediately, don't improvise
   - Acknowledge within 5 min (SLA) to show the system you're on it

2. ASSESS (2 min)
   - Open the linked Grafana dashboard
   - Check: is this real? (Not a flapping alert from a deploy)
   - Check: what is the blast radius? (# users affected, which regions)
   - Declare severity: SEV-1 (revenue/safety) / SEV-2 (degraded) / SEV-3 (no user impact)
   - SEV-1: open Zoom bridge, page backup, notify VP

3. TRIAGE (5 min)
   - Grafana Explore: paste the trace_id from the alert into Tempo
   - Look for red spans (errors) in the trace waterfall
   - Click the error span → Loki logs for that span's time window
   - Check: which dependency is failing? (Stripe? DB? Cache?)
   - Check: did anything deploy recently? (CI/CD deploy timestamp on Grafana)

4. MITIGATE (10 min — fix symptoms, not root cause)
   - Roll back the deploy if the issue correlates with a recent deployment
   - Scale up the affected service if it is CPU/memory constrained
   - Enable feature flag to disable the broken feature path
   - Redirect traffic away from the affected region (DNS failover)
   - DOCUMENT EVERY ACTION in the incident Slack thread (timestamps!)

5. RESOLVE (verify, then close)
   - Confirm error rate is back below SLO threshold for 5 min
   - Confirm p99 is back below SLO threshold
   - Post: "Resolved at HH:MM UTC — root cause: [1 sentence]"
   - Schedule post-mortem within 48 hours

6. POST-MORTEM (see Section 8)
"""


# =============================================================================
# SECTION 8 — Blameless post-mortem process
# =============================================================================

@dataclass
class PostMortem:
    """
    Blameless post-mortem template.
    The goal is systemic improvement, not individual blame.
    Systems that encourage blame → engineers hide problems → worse reliability.
    """
    incident_id: str
    title: str
    date: datetime
    author: str
    participants: List[str]
    severity: str
    duration_minutes: float
    impact_description: str
    timeline: List[Dict[str, str]]     # [{"time": "...", "event": "..."}]
    contributing_factors: List[str]    # What made this possible?
    root_causes: List[str]             # 5-Whys conclusion
    action_items: List[Dict[str, str]] # [{"action": "...", "owner": "...", "due": "..."}]
    what_went_well: List[str]
    what_went_poorly: List[str]

    def five_whys(self, initial_problem: str) -> List[str]:
        """
        Iterative prompt for 5-Whys analysis.
        In practice this is facilitated by a human; here we just show the structure.

        5-Whys example:
          Problem:  Checkout error rate spiked to 15%.
          Why 1:    The payment service returned 503.
          Why 2:    The payment service was out of DB connections.
          Why 3:    The connection pool was exhausted by a slow query.
          Why 4:    A new index was missing after a schema migration.
          Why 5:    The migration was not tested against production data volume.
          Fix:      Add production-scale migration tests to CI.
        """
        return [
            f"Problem: {initial_problem}",
            "Why 1: [fill in — what immediately caused the problem?]",
            "Why 2: [fill in — what caused Why 1?]",
            "Why 3: [fill in — what caused Why 2?]",
            "Why 4: [fill in — what caused Why 3?]",
            "Why 5 (root): [fill in — what systemic condition allowed this chain?]",
        ]

    def render_markdown(self) -> str:
        """Render the post-mortem as a Confluence/GitHub Markdown document."""
        lines = [
            f"# Post-Mortem: {self.title}",
            f"**Incident**: {self.incident_id} | **Date**: {self.date.strftime('%Y-%m-%d')}",
            f"**Severity**: {self.severity} | **Duration**: {self.duration_minutes:.0f} min",
            f"**Author**: {self.author} | **Participants**: {', '.join(self.participants)}",
            "",
            "## Impact",
            self.impact_description,
            "",
            "## Timeline",
        ]
        for entry in self.timeline:
            lines.append(f"- **{entry.get('time', '?')}** — {entry.get('event', '')}")
        lines += [
            "",
            "## Root Causes (5-Whys)",
        ]
        for rc in self.root_causes:
            lines.append(f"- {rc}")
        lines += [
            "",
            "## Contributing Factors",
        ]
        for cf in self.contributing_factors:
            lines.append(f"- {cf}")
        lines += [
            "",
            "## What Went Well",
        ]
        for w in self.what_went_well:
            lines.append(f"- {w}")
        lines += [
            "",
            "## What Went Poorly",
        ]
        for w in self.what_went_poorly:
            lines.append(f"- {w}")
        lines += [
            "",
            "## Action Items",
            "| Action | Owner | Due |",
            "|--------|-------|-----|",
        ]
        for item in self.action_items:
            lines.append(f"| {item['action']} | {item['owner']} | {item['due']} |")
        return "\n".join(lines)


# =============================================================================
# SECTION 9 — SRE runbook template
# =============================================================================

RUNBOOK_TEMPLATE = """
# RUNBOOK: {alert_name}
Service:    {service}
Severity:   {severity}
Dashboard:  {dashboard_url}
Playbook:   {confluence_url}
On-call:    #sre-oncall Slack | PagerDuty escalation policy: {pd_policy}

## What does this alert mean?
{description}

## Immediate checks (do in order, stop when you find the cause)
1. [ ] Is this a false positive? Check if a deploy happened in the last 15 min.
       → kubectl rollout history deploy/{service}
2. [ ] Is the service up?
       → kubectl get pods -n {namespace} -l app={service}
3. [ ] Are the pods restarting (OOMKilled / CrashLoopBackOff)?
       → kubectl describe pod <name> -n {namespace}
4. [ ] Is the dependent DB/cache/queue healthy?
       → Grafana: {dependency_dashboard_url}
5. [ ] Is there a recent spike in traffic (DDoS, viral event)?
       → Grafana: {traffic_dashboard_url}

## Likely causes and fixes
### Cause A: Memory leak → OOMKilled
   Fix: Increase memory limit temporarily, deploy fix within 24h.
   Command: kubectl set resources deploy/{service} --limits memory=2Gi

### Cause B: DB connection pool exhausted
   Fix: Restart the service to reset connections, then investigate slow queries.
   Command: kubectl rollout restart deploy/{service}

### Cause C: Upstream dependency down (circuit breaker should fire)
   Fix: Wait for dependency recovery; circuit breaker will auto-reset in 30s.
   Escalate: Page the {dependency_team} team if down > 5 min.

## Escalation path
   1. On-call engineer (this runbook)
   2. Team lead: {team_lead_slack}
   3. Director: {director_slack} (SEV-1 only)

## Rollback procedure
   kubectl rollout undo deploy/{service} -n {namespace}
   # Verify: watch kubectl rollout status deploy/{service}

## Post-incident
   File post-mortem if duration > 30 min or impacted users > 100.
"""


# =============================================================================
# SECTION 10 — Observability-driven development checklist
# =============================================================================

OBSERVABILITY_DRIVEN_DEV_CHECKLIST = """
OBSERVABILITY-DRIVEN DEVELOPMENT (ODD) — Pre-merge checklist
══════════════════════════════════════════════════════════════
Every feature PR must satisfy these before it ships to production.

Tracing:
  [ ] New code paths have spans with semantic convention attributes.
  [ ] External calls (HTTP, DB, queue) are wrapped in CLIENT spans.
  [ ] Error paths call span.record_exception() and set StatusCode.ERROR.
  [ ] Span attribute names match opentelemetry-specification/semantic_conventions.

Metrics:
  [ ] New counters / histograms created with descriptive unit and description.
  [ ] No user_id, request_id, or other unbounded values used as label values.
  [ ] Latency histogram uses standard buckets (0.005 → 5.0 s).
  [ ] A Grafana panel for the new metric exists in the service dashboard.

Logging:
  [ ] New log statements use structured fields, not f-strings in the message.
  [ ] DEBUG logs include enough context to reproduce the event.
  [ ] ERROR logs include the exception + correlation IDs (trace_id).
  [ ] No PII (email, credit card, SSN) logged at any level.

Alerting:
  [ ] A Prometheus alerting rule exists for any new SLO-relevant metric.
  [ ] Alert annotation includes runbook_url and dashboard_url.
  [ ] Alert has been tested in staging (alerts fire as expected).

Documentation:
  [ ] Runbook updated if the new feature introduces new failure modes.
  [ ] CHANGELOG.md updated with observability changes.
  [ ] The on-call team was briefed on the new feature's failure modes.
"""


# =============================================================================
# SECTION 11 — Cost control strategies
# =============================================================================

class ObservabilityCostController:
    """
    Enforce policies that prevent runaway observability costs:
      - Metric cardinality budget enforcement
      - Dynamic log sampling based on error rate
      - Trace budget enforcement via reservoir sampling
    """

    def __init__(
        self,
        max_metric_series: int = 50_000,
        trace_budget_per_minute: int = 5_000,
    ):
        self.max_metric_series = max_metric_series
        self.trace_budget_per_minute = trace_budget_per_minute
        self._trace_count = 0
        self._window_start = time.monotonic()
        self._lock = threading.Lock()

    def should_sample_trace(self, is_error: bool = False) -> bool:
        """
        Budget-based trace sampling.
        Errors are always sampled.
        Success traces are dropped when the per-minute budget is exceeded.
        """
        if is_error:
            return True   # always capture errors — they are the most valuable

        with self._lock:
            now = time.monotonic()
            if (now - self._window_start) >= 60:
                # Reset the budget window.
                self._trace_count = 0
                self._window_start = now

            if self._trace_count >= self.trace_budget_per_minute:
                return False   # budget exhausted — drop this trace

            self._trace_count += 1
            return True

    @staticmethod
    def log_sample_rate(error_rate_pct: float) -> float:
        """
        Dynamic log sampling: reduce volume when the system is healthy,
        increase it when errors are occurring.

        error_rate_pct  → sample_rate
        < 0.1 %         → 1 % (quiet, healthy)
        0.1 – 1 %       → 10 %
        > 1 %           → 100 % (incident in progress — capture everything)
        """
        if error_rate_pct < 0.1:
            return 0.01
        elif error_rate_pct < 1.0:
            return 0.10
        else:
            return 1.0


# =============================================================================
# SECTION 12 — Grafana unified frontend: datasource linking
# =============================================================================

GRAFANA_DATASOURCE_CONFIG = """
# grafana/provisioning/datasources/datasources.yaml
# Configures all four datasources and wires up trace→log correlation.

apiVersion: 1
datasources:
  - name: Thanos
    type: prometheus
    url: http://thanos-query:9090
    isDefault: true
    jsonData:
      timeInterval: 15s          # must match Prometheus scrape_interval

  - name: Loki
    type: loki
    url: http://loki:3100
    jsonData:
      derivedFields:
        # When a log line contains a traceID field, make it a link to Tempo.
        - name: TraceID
          matcherRegex: '"trace_id":"(\\w+)"'
          url: '$${__value.raw}'
          datasourceUid: tempo    # opens the trace in Tempo on click

  - name: Tempo
    uid: tempo
    type: tempo
    url: http://tempo:3200
    jsonData:
      tracesToLogs:              # link from a span to its logs in Loki
        datasourceUid: loki
        filterByTraceID: true
        filterBySpanID: true
        spanStartTimeShift: '-1m'
        spanEndTimeShift: '1m'
      serviceMap:                # show service dependency map
        datasourceUid: Thanos    # pull service graph from Prometheus
      search:
        hide: false
      nodeGraph:
        enabled: true

  - name: Elasticsearch
    type: elasticsearch
    url: https://elasticsearch:9200
    jsonData:
      index: "logs-*"
      timeField: "@timestamp"
      logMessageField: message
      logLevelField: level
"""


# =============================================================================
# SECTION 13 — Thanos long-term storage configuration
# =============================================================================

THANOS_CONFIG = """
# thanos-store.yaml — object storage configuration
# Thanos Store Gateway serves historical data (> 2 weeks) from S3.
# Combines with short-term Prometheus data for seamless long-term queries.

type: S3
config:
  bucket:             prometheus-metrics-production
  endpoint:           s3.amazonaws.com
  region:             us-east-1
  access_key:         ${AWS_ACCESS_KEY_ID}
  secret_key:         ${AWS_SECRET_ACCESS_KEY}
  # SSE-S3 encryption for compliance.
  sse_config:
    type: SSE-S3

# Thanos Compact: downsampling saves query cost on long-range queries.
# Raw:  15s resolution → 2 weeks
# 5m:   5-min downsampled → 1 month
# 1h:   1-hour downsampled → 13 months (YoY comparisons)
compactor:
  block_sync_concurrency: 20
  downsampling:
    disable: false
  retention:
    resolution_raw:  336h    # 2 weeks
    resolution_5m:   744h    # 31 days
    resolution_1h:   8760h   # 1 year
"""


# =============================================================================
# SECTION 14 — Demo: instrument a mock request pipeline end-to-end
# =============================================================================

def setup_demo_providers():
    """Set up minimal OTel providers for demo output."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader

    resource = Resource.create({SERVICE_NAME: "checkout-service", "env": "demo"})
    tp = TracerProvider(resource=resource, sampler=ALWAYS_ON)
    tp.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(tp)

    mp = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(ConsoleMetricExporter(),
                                                      export_interval_millis=3000)]
    )
    metrics.set_meter_provider(mp)
    return tp, mp


class ObservableRequestHandler:
    """
    A fully observable request handler demonstrating the complete observability
    stack: trace span + metric recording + structured log + tenant context.
    """

    def __init__(self):
        self.tracer = trace.get_tracer("checkout.handler")
        self.meter = metrics.get_meter("checkout.handler")
        self.request_counter = self.meter.create_counter(
            "requests.total", unit="1", description="Total requests handled"
        )
        self.latency_hist = self.meter.create_histogram(
            "request.duration", unit="ms", description="Request latency"
        )
        self.cost_controller = ObservabilityCostController(trace_budget_per_minute=100)

    def handle(self, method: str, path: str, tenant_id: str, body: dict) -> dict:
        """Handle a single request with full observability."""
        import random

        start = time.perf_counter()
        status = "success"

        with TenantContext.scope(tenant_id):
            # Decide whether to sample this trace.
            is_error_request = random.random() < 0.1
            should_sample = self.cost_controller.should_sample_trace(is_error_request)

            with self.tracer.start_as_current_span(
                f"{method} {path}",
                kind=trace.SpanKind.SERVER,
            ) as span:
                span.set_attribute("http.method", method)
                span.set_attribute("http.route", path)
                span.set_attribute("tenant.id", tenant_id)
                span.set_attribute("trace.sampled", should_sample)

                # Simulate processing.
                time.sleep(random.uniform(0.01, 0.08))

                if is_error_request:
                    exc = ValueError("Simulated payment validation error")
                    span.record_exception(exc)
                    span.set_status(trace.StatusCode.ERROR)
                    status = "error"
                    logger.error(
                        "Request failed",
                        extra={
                            "http.method": method,
                            "http.route": path,
                            "tenant.id": tenant_id,
                            "error": str(exc),
                        },
                    )
                else:
                    span.set_status(trace.StatusCode.OK)
                    logger.info(
                        "Request completed",
                        extra={"http.method": method, "http.route": path, "tenant.id": tenant_id},
                    )

        elapsed_ms = (time.perf_counter() - start) * 1000
        self.request_counter.add(1, {"method": method, "route": path, "status": status})
        self.latency_hist.record(elapsed_ms, {"route": path})

        return {"status": status, "latency_ms": round(elapsed_ms, 2), "tenant": tenant_id}


if __name__ == "__main__":
    import random

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    print(ARCHITECTURE_DIAGRAM)

    # Set up minimal OTel providers (console output for demo).
    tp, mp = setup_demo_providers()

    handler = ObservableRequestHandler()

    tenants = ["acme", "globex", "initech"]
    routes = ["/checkout", "/cart/add", "/cart/remove", "/orders"]

    print("\n=== Simulating 20 requests across 3 tenants ===\n")
    results = []
    for i in range(20):
        result = handler.handle(
            method="POST" if "checkout" in (r := random.choice(routes)) else "GET",
            path=r,
            tenant_id=random.choice(tenants),
            body={"item_id": f"SKU-{random.randint(1000, 9999)}"},
        )
        results.append(result)
        time.sleep(0.05)

    errors = sum(1 for r in results if r["status"] == "error")
    avg_ms = sum(r["latency_ms"] for r in results) / len(results)
    print(f"\nSummary: {len(results)} requests, {errors} errors, avg {avg_ms:.1f} ms")

    print("\n=== Post-Mortem example ===")
    pm = PostMortem(
        incident_id="INC-2024-0042",
        title="Checkout error rate spike due to missing DB index",
        date=datetime(2024, 6, 15, 14, 30),
        author="sre-oncall",
        participants=["alice", "bob", "carol"],
        severity="SEV-2",
        duration_minutes=47.0,
        impact_description="15% of checkout requests returned 503 for 47 minutes. ~1,200 users affected.",
        timeline=[
            {"time": "14:30", "event": "Alert fired: CheckoutHighErrorBurnRate"},
            {"time": "14:32", "event": "On-call acknowledged alert"},
            {"time": "14:38", "event": "Root cause identified: missing index on orders.user_id"},
            {"time": "15:17", "event": "Index created, error rate back to baseline"},
        ],
        root_causes=["Schema migration deployed without production-scale index"],
        contributing_factors=[
            "CI environment uses a small dataset that masks index performance issues",
            "No automated slow-query alerting in place",
        ],
        action_items=[
            {"action": "Add production-scale migration test to CI", "owner": "alice", "due": "2024-06-22"},
            {"action": "Add slow query Prometheus alert", "owner": "bob", "due": "2024-06-20"},
        ],
        what_went_well=["Circuit breaker prevented full cascade", "On-call response time < 2 min"],
        what_went_poorly=["Missing runbook for DB index issues", "Alert had no dashboard link"],
    )
    print(pm.render_markdown())

    # Wait for metric export.
    time.sleep(4)
    tp.shutdown()
    mp.shutdown()
