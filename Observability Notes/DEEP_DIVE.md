# Observability — Principal Engineer Deep Dive

Companion to the existing lessons. Niche tooling, tradeoffs, worked
examples, and interview-grade depth beyond the core material.


## The Three Pillars: Metrics, Logs, Traces

**Beyond the lesson**: The three pillars aren't independent — the real
power is CORRELATION between them. A metric shows latency spiked at 14:32;
that alone tells you nothing about why. A trace from that exact window
shows WHICH service in the call chain caused it. A log from that specific
trace ID shows the actual error message/stack trace. Modern observability
platforms (Honeycomb, Datadog, Grafana with Loki+Tempo+Mimir) are built
around exemplars — a metric data point carrying a linked trace ID — so you
can jump from "the spike" directly to "the specific slow trace" in one click,
instead of manually correlating timestamps across three separate tools.

**Worked example**: OpenTelemetry (OTel) as the vendor-neutral instrumentation
layer — instrument code ONCE with the OTel SDK, and route the resulting
metrics/logs/traces to ANY backend (Datadog, New Relic, self-hosted
Prometheus+Jaeger) via an OTel Collector, without re-instrumenting when you
switch vendors. This is the single biggest shift in observability tooling
over the last few years — before OTel, switching monitoring vendors meant
ripping out and reinstalling vendor-specific SDKs across every service.

**Interview Q&A**:
- *Q: You have great metrics dashboards but still can't diagnose a specific slow request. What's missing?* A: Distributed tracing — metrics tell you THAT something's slow in aggregate; only a trace shows the actual path a single request took through your services and where time was spent within it.


## Structured Logging & Log Levels

**Beyond the lesson**: Structured (JSON) logging isn't a style preference —
it's what makes logs QUERYABLE at scale. `log.error("failed for user 123")`
requires regex/string-matching to find every failure for a user; a
structured `log.error("request failed", user_id=123, error_code="TIMEOUT")`
lets you query `error_code:TIMEOUT AND user_id:123` directly, and aggregate
by any field across millions of log lines instantly.

**Pitfalls**: Logging at INFO level for every request in a high-throughput
service is a classic self-inflicted cost/performance problem — log volume
scales with traffic, and at real scale, verbose logging can itself become a
meaningful fraction of infrastructure spend (ingestion + storage costs in
tools like Datadog/Splunk are often priced per-GB-ingested). Sampling
(logging only a % of successful requests, always logging errors/slow
requests) is standard practice at scale, not a corner cut.

**Interview Q&A**:
- *Q: How do you avoid drowning in logs during an incident with 10,000 requests/sec?* A: Correlate via a request/trace ID injected at the edge and propagated through every service — during an incident you filter by that ID (or by error rate/latency outliers) rather than reading raw log volume; log sampling for the "boring" successful path plus 100% capture of errors/slow-path requests.


## Metrics & Time-Series: Prometheus, Cardinality

**Beyond the lesson**: Cardinality explosion is THE production incident
class unique to metrics systems — a Prometheus metric labeled with
`user_id` (potentially millions of distinct values) creates a separate
time series PER unique label combination; a metric that seemed fine in
testing can silently multiply into millions of series in production and
take down the metrics backend itself (out-of-memory on the Prometheus
server) — high-cardinality dimensions belong in TRACES/LOGS, not metric labels.

**Worked example**: The RED method (Rate, Errors, Duration) for request-
driven services, and the USE method (Utilization, Saturation, Errors) for
resource-driven components (CPU, disk, queues) — two different but
complementary frameworks for deciding WHAT to actually dashboard, instead
of the common failure mode of dashboards with 40 panels nobody looks at
because none of them map to an actual "is the system healthy" question.

**Interview Q&A**:
- *Q: A team wants to add `customer_email` as a Prometheus label for per-customer dashboards. What do you tell them?* A: Don't — that's unbounded cardinality (grows forever as customers are added) and will eventually take down the metrics backend; use a lower-cardinality customer TIER or PLAN label for metrics, and reserve the actual email for logs/traces where per-record cardinality is expected and handled differently.


## Alerting Design

**Beyond the lesson**: A good alert answers three questions on its own,
without the on-call engineer needing to dig: what's broken, what's the
user impact, and what's the first diagnostic step (often a runbook link).
An alert that just says "CPU > 90%" forces the responder to reconstruct
context that the alert itself could have included — symptom-based alerting
(alert on USER-FACING impact: error rate, latency) is preferred over
cause-based alerting (CPU, memory) precisely because high CPU that ISN'T
affecting users shouldn't page anyone at 3am.

**Interview Q&A**:
- *Q: Symptom-based vs cause-based alerting — which should page a human?* A: Symptom-based (error rate, latency, availability) should page — it directly reflects user impact; cause-based signals (CPU, memory, disk) are valuable for DASHBOARDS and root-cause investigation but paging on them alone causes alert fatigue from transient spikes that never actually affected users.


## NICHE BUT REAL

- **Honeycomb / high-cardinality event-based observability** — a different
  philosophy from traditional metrics: store raw, high-cardinality EVENTS
  (not pre-aggregated time series) and let engineers ask arbitrary
  exploratory questions after the fact ("show me every slow request WHERE
  user_id=X AND region=eu AND feature_flag=Y enabled") — a query pattern
  pre-aggregated metrics fundamentally cannot answer after the fact.
- **eBPF-based observability** (Pixie, Cilium Hubble) — captures
  metrics/traces at the KERNEL level without any application code changes
  or SDK instrumentation at all — see eBPF Notes for the underlying
  mechanism; valuable specifically when you can't modify the application
  (legacy/third-party services) but still need visibility into its behavior.
- **Synthetic monitoring** — scripted, scheduled fake user journeys
  (log in, add to cart, checkout) run continuously from external locations,
  catching outages BEFORE real users report them and validating from
  outside your own infrastructure (catches DNS/CDN/edge issues real-user
  monitoring inside your stack would miss).
- **Real User Monitoring (RUM)** — actual browser/client-side telemetry
  from real user sessions (page load time, JS errors, Core Web Vitals) —
  the complement to synthetic monitoring: RUM shows what real users
  actually experienced; synthetic shows a controlled, repeatable baseline.
- **SLO burn-rate alerting** — instead of alerting on a raw threshold,
  alert on the RATE at which an error budget is being consumed (e.g. "at
  this rate we'll exhaust the monthly error budget in 2 hours") — catches
  fast-burning incidents early while tolerating brief, low-impact blips
  that a naive threshold alert would fire on unnecessarily.
- **Continuous profiling** (Pyroscope, Parca) — always-on, low-overhead
  CPU/memory profiling in production (not just during a manual debugging
  session) so a performance regression can be diagnosed against historical
  profile data instead of needing to reproduce the issue live.
