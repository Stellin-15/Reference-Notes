# =============================================================================
# WHAT: Alerting and SLOs — SLI/SLO/SLA/error budget framework, burn rate alerts,
#       multi-window alerting, Alertmanager routing, alert fatigue prevention,
#       dead man's switches, and Grafana dashboard design principles.
# WHY:  Metrics and traces are useless if nobody is paged when things break.
#       But bad alerting causes alert fatigue — engineers ignore all alerts.
#       SLOs give you a principled framework for alerting on what users experience.
# LEVEL: Intermediate-Advanced — assumes Prometheus knowledge (see L01).
# =============================================================================

# ── CONCEPT OVERVIEW ─────────────────────────────────────────────────────────
#
# SLI / SLO / SLA / ERROR BUDGET — the hierarchy
#
#   SLI (Service Level Indicator):
#     The actual measured metric. A ratio, rate, or quantile.
#     "Availability = successful_requests / total_requests"
#     "Latency = fraction of requests completing in < 200ms"
#
#   SLO (Service Level Objective):
#     The target value for an SLI, over a rolling window.
#     "Availability SLO: 99.9% over a rolling 30-day window"
#     "Latency SLO: 99% of requests < 200ms over 30 days"
#     Defined internally. Violation is an engineering problem, not a contract breach.
#
#   SLA (Service Level Agreement):
#     A legal/contractual commitment to customers. Usually weaker than SLO.
#     "SLA: 99.5% availability" (while internal SLO is 99.9%)
#     The gap between SLO and SLA is your safety buffer.
#     Violating SLA → refunds, penalties, customer churn.
#
#   Error Budget:
#     The allowed downtime/failures before the SLO is violated.
#     Budget = 1 - SLO target
#     For 99.9% availability SLO over 30 days:
#       Error budget = 0.1% × 30 days × 24h × 60min = 43.2 minutes/month
#     Budget is shared: planned deployments, incidents, experiments all consume it.
#     When budget is exhausted → freeze new deployments, focus on reliability.
#
# ── PRODUCTION USE CASE ──────────────────────────────────────────────────────
#   A payment API has a 99.95% availability SLO. Error budget = 21.6 min/month.
#   A deployment introduced a bug: 0.5% error rate for 40 minutes.
#   Budget consumed: ~60% of the monthly budget in one incident.
#   Burn rate alert fires at 14x (budget exhausted in 2 hours if rate continues).
#   On-call rolls back the deployment within 8 minutes. Monthly budget survives.
#
# ── COMMON MISTAKES ──────────────────────────────────────────────────────────
#   1. Alerting on causes not symptoms ("CPU > 80%" instead of "error rate > 1%")
#   2. Alerting on everything — alert fatigue → engineers stop responding
#   3. Too-short alert windows → flapping alerts (fire/resolve/fire every 2 min)
#   4. No runbook link in alerts → engineer has to remember what to do at 3am
#   5. Missing "for" clause → alerts fire on a single bad data point
#   6. SLO target too high (99.999%) for a system that can't achieve it
#   7. No dead man's switch → alerting pipeline failure goes undetected
#   8. Not silencing alerts during maintenance → paging the on-call unnecessarily
# =============================================================================

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
from datetime import timedelta


# =============================================================================
# SECTION 1: SLI DEFINITIONS — what to measure
# =============================================================================
#
# Well-chosen SLIs directly reflect user experience.
# Google SRE Book suggests these SLI categories for web services:
#
#   Availability:  is the service responding?
#     SLI = good_requests / total_requests
#     "Good" = non-5xx HTTP responses
#     (4xx are not errors — they're valid rejections of bad client requests)
#
#   Latency:       is the service responding fast enough?
#     SLI = requests completing in < threshold / total_requests
#     Measure at multiple percentiles: p50, p90, p99, p99.9
#     Use histograms (L01) — never use averages (averages hide tail latency)
#
#   Throughput:    can the service handle the load?
#     SLI = bytes_served / bytes_requested (for CDN/storage)
#     Or: successful_jobs / total_jobs (for batch systems)
#
#   Quality/Freshness (data pipelines):
#     SLI = fraction of data processed within target latency
#     "95% of events processed within 60 seconds of ingestion"

class SLIType(Enum):
    AVAILABILITY = "availability"
    LATENCY = "latency"
    THROUGHPUT = "throughput"
    FRESHNESS = "freshness"


@dataclass
class SLI:
    """Defines a Service Level Indicator."""
    name: str
    type: SLIType
    description: str
    promql_numerator: str           # PromQL for "good" events
    promql_denominator: str         # PromQL for total events
    # For latency SLIs, the threshold (e.g., 0.2 for 200ms) is baked into the numerator query


# SLI definitions for a payment API service
PAYMENT_API_SLIS: List[SLI] = [

    SLI(
        name="payment_api_availability",
        type=SLIType.AVAILABILITY,
        description="Fraction of API requests that succeed (non-5xx)",
        # Count non-server-error responses as "good"
        promql_numerator="""
            sum(rate(http_requests_total{
                service="payment-api",
                status_code!~"5.."
            }[5m]))
        """,
        # Total is all requests
        promql_denominator="""
            sum(rate(http_requests_total{
                service="payment-api"
            }[5m]))
        """,
    ),

    SLI(
        name="payment_api_latency_p99",
        type=SLIType.LATENCY,
        description="Fraction of requests completing in < 200ms (p99 target)",
        # Count requests completing within 200ms as "good"
        # The le="0.2" bucket in a histogram counts all observations <= 0.2s
        promql_numerator="""
            sum(rate(http_request_duration_seconds_bucket{
                service="payment-api",
                le="0.2"
            }[5m]))
        """,
        promql_denominator="""
            sum(rate(http_request_duration_seconds_count{
                service="payment-api"
            }[5m]))
        """,
    ),
]


# =============================================================================
# SECTION 2: SLO DEFINITIONS AND ERROR BUDGET CALCULATION
# =============================================================================

@dataclass
class SLO:
    """Defines a Service Level Objective."""
    name: str
    sli: SLI
    target: float                   # 0.999 = 99.9%
    window_days: int = 30           # rolling window (28 or 30 days is typical)

    @property
    def error_budget_ratio(self) -> float:
        """Error budget as a fraction: 1 - target."""
        return 1.0 - self.target

    @property
    def error_budget_minutes(self) -> float:
        """Total allowed downtime in minutes over the window."""
        return self.error_budget_ratio * self.window_days * 24 * 60

    @property
    def error_budget_seconds(self) -> float:
        """Total allowed downtime in seconds over the window."""
        return self.error_budget_minutes * 60

    def budget_remaining(self, current_error_rate: float) -> float:
        """
        Calculate remaining error budget fraction given a current error rate.
        current_error_rate: observed bad event rate (e.g., 0.002 = 0.2% errors)
        Returns: 0.0 (exhausted) to 1.0 (full budget remaining)
        """
        # Simplified: assume error rate was at current_error_rate for the full window
        consumed = current_error_rate / self.error_budget_ratio
        return max(0.0, 1.0 - consumed)

    def burn_rate(self, current_error_rate: float) -> float:
        """
        Burn rate: how fast the error budget is being consumed relative to normal.
        burn_rate = 1.0 → consuming budget at exactly the SLO-allowed pace.
        burn_rate = 10.0 → consuming budget 10x faster than allowed.
        burn_rate > (window_hours / alert_window_hours) → budget exhausted before window ends.
        """
        if self.error_budget_ratio == 0:
            return float("inf")
        return current_error_rate / self.error_budget_ratio


# Define SLOs for the payment API
AVAILABILITY_SLO = SLO(
    name="payment_api_availability_slo",
    sli=PAYMENT_API_SLIS[0],
    target=0.9995,                  # 99.95% availability
    window_days=30,
)

LATENCY_SLO = SLO(
    name="payment_api_latency_slo",
    sli=PAYMENT_API_SLIS[1],
    target=0.990,                   # 99.0% of requests < 200ms
    window_days=30,
)


def print_slo_budget_analysis(slo: SLO):
    """Print error budget analysis for a given SLO."""
    print(f"\n{'='*60}")
    print(f"SLO: {slo.name}")
    print(f"Target: {slo.target * 100:.3f}%  |  Window: {slo.window_days} days")
    print(f"Error budget: {slo.error_budget_ratio * 100:.4f}%")
    print(f"             = {slo.error_budget_minutes:.1f} minutes allowed downtime")
    print(f"             = {slo.error_budget_seconds:.0f} seconds")

    # Show burn rates at different error rates
    print("\nBurn rate analysis:")
    test_error_rates = [
        (0.0001, "0.01% error rate (10x below budget)"),
        (slo.error_budget_ratio, "Exactly at budget rate"),
        (slo.error_budget_ratio * 5, "5x burn rate"),
        (slo.error_budget_ratio * 14.4, "14.4x burn rate (2hr exhaustion)"),
    ]
    for rate, label in test_error_rates:
        burn = slo.burn_rate(rate)
        hours_to_exhaust = (slo.window_days * 24) / burn if burn > 0 else float("inf")
        print(f"  {label}")
        print(f"    → Burn rate: {burn:.1f}x | Hours to exhaust budget: {hours_to_exhaust:.1f}h")


# =============================================================================
# SECTION 3: MULTI-WINDOW MULTI-BURN-RATE ALERTING
# =============================================================================
#
# THE PROBLEM with simple "error rate > X% for Y minutes" alerts:
#   Too sensitive: fires on a brief spike, causes alert fatigue.
#   Too slow: a slow leak (2x burn rate) exhausts budget in 15 days undetected.
#
# GOOGLE SRE BOOK SOLUTION: Multi-window, multi-burn-rate alerting.
#
# Two alert types per SLO:
#   Page (wake someone up): high burn rate, fast detection, short window.
#   Ticket (fix during business hours): low burn rate, slow detection, long window.
#
# Recommended burn rate thresholds (for a 30-day window):
#   ┌─────────────────────────┬─────────────┬──────────────┬──────────┐
#   │ Alert                   │ Burn Rate   │ Window       │ Budget   │
#   │                         │             │              │ Consumed │
#   ├─────────────────────────┼─────────────┼──────────────┼──────────┤
#   │ Page (critical)         │ 14.4x       │ 1h           │ 2% in 1h │
#   │ Page (critical confirm) │ 14.4x       │ 5m           │ (dual)   │
#   ├─────────────────────────┼─────────────┼──────────────┼──────────┤
#   │ Page (warning)          │ 6x          │ 6h           │ 5%       │
#   │ Page (warning confirm)  │ 6x          │ 30m          │ (dual)   │
#   ├─────────────────────────┼─────────────┼──────────────┼──────────┤
#   │ Ticket (slow burn)      │ 3x          │ 3 days (72h) │ 10%      │
#   │ Ticket (slow confirm)   │ 3x          │ 6h           │ (dual)   │
#   ├─────────────────────────┼─────────────┼──────────────┼──────────┤
#   │ Ticket (very slow)      │ 1x          │ 3 days       │ 10%      │
#   └─────────────────────────┴─────────────┴──────────────┴──────────┘
#
# DUAL WINDOW: require BOTH a long window AND a short window to both exceed
#              the burn rate threshold. This prevents brief spikes from firing
#              a page while still detecting sustained problems quickly.

@dataclass
class BurnRateAlert:
    """Defines a burn rate alert for an SLO."""
    name: str
    slo: SLO
    burn_rate_threshold: float      # e.g., 14.4 = budget exhausted in 2 hours
    long_window: str                # e.g., "1h" — main detection window
    short_window: str               # e.g., "5m" — confirmation window (dual-window)
    severity: str                   # "page" | "ticket"
    description: str = ""

    def to_promql_alert(self) -> str:
        """Generate the PromQL expression for this burn rate alert."""
        slo = self.slo
        threshold = slo.error_budget_ratio * self.burn_rate_threshold

        # Error rate over long window AND short window must both exceed threshold
        # This is the dual-window approach
        return f"""
# Burn rate alert: {self.name}
# Fires if burn rate exceeds {self.burn_rate_threshold}x for both windows
(
  1 - (
    sum(rate({slo.sli.promql_numerator.strip().split(chr(10))[0].strip()}[{self.long_window}]))
    / sum(rate({slo.sli.promql_denominator.strip().split(chr(10))[0].strip()}[{self.long_window}]))
  ) > ({threshold:.6f})
)
AND
(
  1 - (
    sum(rate({slo.sli.promql_numerator.strip().split(chr(10))[0].strip()}[{self.short_window}]))
    / sum(rate({slo.sli.promql_denominator.strip().split(chr(10))[0].strip()}[{self.short_window}]))
  ) > ({threshold:.6f})
)
        """.strip()


MULTI_WINDOW_ALERTS_YAML = """
# Prometheus alerting rules — multi-window multi-burn-rate SLO alerts
# For a 99.95% availability SLO (error budget = 0.05% = 0.0005)

groups:
  - name: payment_api_slo_alerts
    rules:

      # ── CRITICAL (PAGE) — 14.4x burn rate ────────────────────────────────
      # Budget exhausted in 2 hours if this continues.
      # Threshold: 14.4 * 0.0005 = 0.0072 (0.72% error rate)
      - alert: PaymentAPIAvailabilityCritical
        expr: |
          (
            (1 - (
              sum(rate(http_requests_total{service="payment-api",status_code!~"5.."}[1h]))
              / sum(rate(http_requests_total{service="payment-api"}[1h]))
            )) > 0.0072
          )
          AND
          (
            (1 - (
              sum(rate(http_requests_total{service="payment-api",status_code!~"5.."}[5m]))
              / sum(rate(http_requests_total{service="payment-api"}[5m]))
            )) > 0.0072
          )
        for: 2m                            # brief stability check (short since windows do most work)
        labels:
          severity: critical
          slo: payment_api_availability
          burn_rate: "14.4x"
          team: payments
        annotations:
          summary: "Payment API burning error budget at 14.4x — budget exhausted in ~2 hours"
          description: |
            Error rate is {{ $value | humanizePercentage }} over the past hour.
            At this rate, the 30-day error budget will be exhausted in approximately 2 hours.
          runbook_url: "https://runbooks.internal/payment-api-availability"
          dashboard_url: "https://grafana.internal/d/payment-api-slo"

      # ── WARNING (PAGE) — 6x burn rate ────────────────────────────────────
      # Budget exhausted in 5 days if this continues.
      # Threshold: 6 * 0.0005 = 0.003 (0.3% error rate)
      - alert: PaymentAPIAvailabilityWarning
        expr: |
          (
            (1 - (
              sum(rate(http_requests_total{service="payment-api",status_code!~"5.."}[6h]))
              / sum(rate(http_requests_total{service="payment-api"}[6h]))
            )) > 0.003
          )
          AND
          (
            (1 - (
              sum(rate(http_requests_total{service="payment-api",status_code!~"5.."}[30m]))
              / sum(rate(http_requests_total{service="payment-api"}[30m]))
            )) > 0.003
          )
        for: 15m
        labels:
          severity: warning
          slo: payment_api_availability
          burn_rate: "6x"
          team: payments
        annotations:
          summary: "Payment API burning error budget at 6x — budget exhausted in ~5 days"
          runbook_url: "https://runbooks.internal/payment-api-availability"

      # ── TICKET (SLOW BURN) — 1x burn rate ────────────────────────────────
      # At exactly the SLO target violation rate; needs investigation this week.
      # Threshold: 1 * 0.0005 = 0.0005 (0.05% error rate — exactly the SLO threshold)
      - alert: PaymentAPIAvailabilitySlowBurn
        expr: |
          (
            (1 - (
              sum(rate(http_requests_total{service="payment-api",status_code!~"5.."}[72h]))
              / sum(rate(http_requests_total{service="payment-api"}[72h]))
            )) > 0.0005
          )
          AND
          (
            (1 - (
              sum(rate(http_requests_total{service="payment-api",status_code!~"5.."}[6h]))
              / sum(rate(http_requests_total{service="payment-api"}[6h]))
            )) > 0.0005
          )
        for: 0m                            # no extra wait — windows already provide stability
        labels:
          severity: info                   # creates a ticket, doesn't page
          slo: payment_api_availability
          burn_rate: "1x"
          team: payments
        annotations:
          summary: "Payment API SLO at risk — slow burn consuming error budget"
          runbook_url: "https://runbooks.internal/payment-api-availability"
"""


# =============================================================================
# SECTION 4: PROMETHEUS ALERTMANAGER — routing and deduplication
# =============================================================================
#
# Alertmanager receives firing alerts from Prometheus and:
#   1. GROUPS: merges similar alerts into one notification (reduces noise)
#   2. ROUTES: sends alerts to the right receiver (team, channel, tool)
#   3. INHIBITS: suppresses less-severe alerts when a parent alert is firing
#      (e.g., don't alert on individual service failures if the whole DC is down)
#   4. SILENCES: temporarily suppress alerts (during maintenance windows)
#
# Alert lifecycle in Alertmanager:
#   Received → Grouped → Routed → Inhibition check → Silence check → Sent
#
# group_wait:     how long to wait for more alerts before sending first notification
#                 (gives time for related alerts to arrive together)
# group_interval: how long to wait before sending a new notification for ongoing alerts
# repeat_interval: how long to wait before re-notifying if alert is still firing
#                  (prevents constant paging; 4h means re-page every 4 hours)

ALERTMANAGER_CONFIG_YAML = """
# alertmanager.yml

global:
  resolve_timeout: 5m               # mark alert as resolved if Prometheus stops sending it
  slack_api_url: "https://hooks.slack.com/services/..."  # global Slack webhook

route:
  # Default receiver for alerts with no specific route match
  receiver: "slack-general"
  group_by: ["alertname", "service", "team"]  # group alerts with same labels
  group_wait: 30s                   # wait 30s before sending first alert (batch similar ones)
  group_interval: 5m                # wait 5m between groups of new alerts
  repeat_interval: 4h               # re-notify every 4h if still firing

  routes:
    # Critical payment alerts → PagerDuty (wakes someone up)
    - match:
        severity: critical
        team: payments
      receiver: "pagerduty-payments"
      group_wait: 10s               # faster for critical
      repeat_interval: 30m          # re-page more often for critical

    # Warning alerts → Slack #alerts-payments channel
    - match:
        severity: warning
        team: payments
      receiver: "slack-payments"
      repeat_interval: 12h

    # Info/ticket alerts → create Jira ticket (via webhook)
    - match:
        severity: info
      receiver: "jira-ticketing"
      repeat_interval: 24h

    # Dead man's switch — always routes to watchdog receiver
    - match:
        alertname: "Watchdog"
      receiver: "deadmanssnitch"
      repeat_interval: 1m           # must fire every minute or Snitch alerts

receivers:
  - name: "pagerduty-payments"
    pagerduty_configs:
      - routing_key: "<PAGERDUTY_INTEGRATION_KEY>"
        description: "{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}"
        details:
          runbook: "{{ (index .Alerts 0).Annotations.runbook_url }}"
          firing: "{{ .Alerts | len }} alert(s) firing"

  - name: "slack-payments"
    slack_configs:
      - channel: "#alerts-payments"
        username: "Alertmanager"
        icon_emoji: ":fire:"
        title: "{{ .GroupLabels.alertname }} — {{ .Status | toUpper }}"
        text: |
          {{ range .Alerts }}
          *Alert:* {{ .Annotations.summary }}
          *Severity:* {{ .Labels.severity }}
          *Runbook:* {{ .Annotations.runbook_url }}
          {{ end }}
        send_resolved: true         # also notify when alert resolves

  - name: "slack-general"
    slack_configs:
      - channel: "#alerts-general"
        send_resolved: true

  - name: "deadmanssnitch"
    webhook_configs:
      - url: "https://nosnch.in/YOUR_SNITCH_ID"  # Dead Man's Snitch URL

  - name: "jira-ticketing"
    webhook_configs:
      - url: "https://jira-bridge.internal/alertmanager"

inhibit_rules:
  # If the entire cluster is down, suppress individual service alerts
  # (Avoids 50 simultaneous pages when a DC loses power)
  - source_match:
      alertname: "ClusterDown"
    target_match_re:
      alertname: ".*"            # suppress ALL other alerts
    equal: ["cluster"]           # only inhibit alerts in the same cluster

  # If critical fires, suppress warning for the same service
  - source_match:
      severity: "critical"
    target_match:
      severity: "warning"
    equal: ["service", "team"]   # same service and team

  # If warning fires, suppress info for the same service
  - source_match:
      severity: "warning"
    target_match:
      severity: "info"
    equal: ["service"]
"""


# =============================================================================
# SECTION 5: DEAD MAN'S SWITCH — detecting alerting pipeline failures
# =============================================================================
#
# Problem: if Prometheus itself fails, Alertmanager fails, or the network
#          between them breaks — no alerts fire. The service could be completely
#          down and nobody is paged.
#
# Solution: Dead Man's Switch (also called Watchdog alert).
#   1. Add a Prometheus alert that is ALWAYS FIRING ("Watchdog"):
#        - alert: Watchdog
#          expr: vector(1)       # always true
#          for: 0m
#          labels: {severity: none}
#          annotations: {summary: "Alertmanager Watchdog — always firing"}
#
#   2. Route "Watchdog" to a dead man's snitch service (e.g., Dead Man's Snitch,
#      healthchecks.io, PagerDuty's "Heartbeat" feature).
#
#   3. The snitch service expects a regular ping (every 1 minute).
#      If the ping stops → snitch fires an alert/page via an independent channel.
#
# This catches: Prometheus crash, Alertmanager crash, network partition,
#               misconfigured routes that drop all alerts silently.

WATCHDOG_ALERT_YAML = """
groups:
  - name: watchdog
    rules:
      # This alert is always firing. It serves as a heartbeat.
      # Route it to deadmanssnitch receiver in Alertmanager.
      # If this alert ever STOPS firing, the snitch service will alert you.
      - alert: Watchdog
        expr: vector(1)            # always evaluates to 1 (always true)
        for: 0m                    # fire immediately, no pending period
        labels:
          severity: none           # won't match any routing that uses severity
        annotations:
          summary: "Alertmanager Watchdog — always firing"
          description: |
            This alert is always firing. It is used to verify that the entire
            alerting pipeline (Prometheus → Alertmanager → receivers) is operational.
            If this alert stops firing in Dead Man's Snitch, investigate immediately.
"""


# =============================================================================
# SECTION 6: ALERT FATIGUE — symptoms and remedies
# =============================================================================
#
# Alert fatigue symptoms:
#   - On-call engineers silence alerts without investigating
#   - MTTR (Mean Time To Resolution) is high despite high alert volume
#   - Alerts fire and auto-resolve before anyone looks at them
#   - Multiple alerts firing for the same root cause simultaneously
#   - Engineers "expect" certain alerts to fire and mentally filter them
#
# Root causes and fixes:
#
#   Too many alerts:
#     Fix: Audit all alerts. If it doesn't require immediate action → delete or ticket.
#          "If an alert wakes someone up but they always check → false alarm → delete it."
#
#   Noisy alerts (frequent false positives):
#     Fix: Increase 'for' duration. Use longer windows. Use burn rate instead of thresholds.
#
#   Alerts on causes not symptoms:
#     Fix: "CPU > 90%" is a cause. "Error rate > 1%" is a symptom. Alert on symptoms.
#     Exception: some causes (disk full, certificate expiring) have no symptom until it's too late.
#
#   Missing inhibition rules:
#     Fix: If alert A implies alert B, inhibit B when A fires.
#
#   No runbooks:
#     Fix: Every alert must link to a runbook explaining: what is it, why does it fire,
#          what to check first, how to resolve it, escalation path.
#
#   Alerting during known maintenance:
#     Fix: Create Alertmanager silences for planned maintenance windows.
#          Automate silence creation in your CI/CD pipeline.

def create_alertmanager_silence_example():
    """Example: programmatically create a silence via Alertmanager API."""
    import json

    silence_payload = {
        "matchers": [
            {"name": "service", "value": "payment-api", "isRegex": False},
            {"name": "severity", "value": "(warning|info)", "isRegex": True},
        ],
        "startsAt": "2026-01-20T02:00:00Z",     # maintenance window start
        "endsAt":   "2026-01-20T04:00:00Z",     # maintenance window end
        "createdBy": "deploy-bot",
        "comment":  "Planned maintenance: database migration v2.1",
    }

    # In practice: requests.post("http://alertmanager:9093/api/v2/silences", json=silence_payload)
    print("Silence payload:")
    print(json.dumps(silence_payload, indent=2))
    print("\n# Create via amtool CLI:")
    print('amtool silence add --alertmanager.url=http://alertmanager:9093 \\')
    print('  service="payment-api" \\')
    print('  --comment="Planned maintenance" \\')
    print('  --duration=2h')


# =============================================================================
# SECTION 7: ALERTING ON SYMPTOMS, NOT CAUSES — the golden signals
# =============================================================================
#
# Google SRE Book: Four Golden Signals (better than USE for user-facing services)
#
#   1. Latency   — time to service a request (distinguish success vs error latency)
#   2. Traffic   — demand on the system (requests/second, transactions/second)
#   3. Errors    — rate of failing requests (explicit 5xx; implicit wrong content)
#   4. Saturation — how "full" your service is; performance usually degrades before 100%
#
# Alert on symptoms (user impact) not causes (internal state):
#
#   SYMPTOM (good): "Error rate > 1% for 5 minutes"
#   CAUSE (bad):    "CPU usage > 85%"  ← CPU can be high without user impact
#
#   SYMPTOM (good): "p99 latency > 500ms for 10 minutes"
#   CAUSE (bad):    "Garbage collection pause > 500ms"  ← may not affect users
#
#   CAUSE alert that's justified: "TLS certificate expires in 3 days"
#   (There's no symptom until the cert expires and all requests fail)

GOLDEN_SIGNALS_ALERTS_YAML = """
groups:
  - name: golden_signals
    rules:

      # 1. LATENCY — p99 > 500ms
      - alert: HighP99Latency
        expr: |
          histogram_quantile(0.99,
            sum by (service, le) (
              rate(http_request_duration_seconds_bucket[10m])
            )
          ) > 0.5
        for: 10m
        labels:
          severity: warning
          signal: latency
        annotations:
          summary: "{{ $labels.service }} p99 latency {{ $value | humanizeDuration }}"
          runbook_url: "https://runbooks.internal/high-latency"

      # 2. TRAFFIC — sudden 50% drop in request rate (possible upstream outage)
      - alert: TrafficDropped
        expr: |
          (
            sum by (service) (rate(http_requests_total[5m]))
            /
            sum by (service) (rate(http_requests_total[30m] offset 5m))
          ) < 0.5
        for: 5m
        labels:
          severity: warning
          signal: traffic
        annotations:
          summary: "{{ $labels.service }} traffic dropped > 50%"
          runbook_url: "https://runbooks.internal/traffic-drop"

      # 3. ERRORS — using burn rate (from Section 3)
      # (See MULTI_WINDOW_ALERTS_YAML above for full burn rate alerts)

      # 4. SATURATION — connection pool nearly exhausted
      - alert: DBConnectionPoolSaturated
        expr: |
          (
            db_connections_active / db_connections_total
          ) > 0.9
        for: 5m
        labels:
          severity: warning
          signal: saturation
        annotations:
          summary: "DB connection pool {{ $labels.pool }} is {{ $value | humanizePercentage }} full"
          runbook_url: "https://runbooks.internal/db-saturation"

      # PROACTIVE CAUSE alert — TLS cert expiry (no symptom until it's too late)
      - alert: TLSCertificateExpiringSoon
        expr: |
          (probe_ssl_earliest_cert_expiry - time()) / 86400 < 14
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "TLS certificate for {{ $labels.instance }} expires in {{ $value | humanizeDuration }}"
          runbook_url: "https://runbooks.internal/cert-rotation"
"""


# =============================================================================
# SECTION 8: GRAFANA DASHBOARD DESIGN — golden signals + USE + SLO panels
# =============================================================================
#
# Grafana dashboard anatomy for a production service:
#
# ROW 1 — SERVICE HEALTH (golden signals, top of dashboard)
#   Panel 1: Request Rate (req/s) — rate(http_requests_total[5m])
#   Panel 2: Error Rate (%)       — ratio of 5xx to total
#   Panel 3: p50 / p95 / p99 latency (ms) — histogram_quantile
#   Panel 4: Apdex score          — (satisfied + tolerating/2) / total
#
# ROW 2 — SLO STATUS
#   Panel 5: Availability SLI    — gauge showing current % vs SLO target
#   Panel 6: Error Budget        — gauge showing % remaining (red when < 20%)
#   Panel 7: Burn Rate (1h / 6h) — stat panel showing current burn rate
#
# ROW 3 — RESOURCE SATURATION (USE method)
#   Panel 8:  CPU utilization
#   Panel 9:  Memory usage
#   Panel 10: DB connection pool utilization
#   Panel 11: Network I/O
#
# ROW 4 — DEPENDENCIES
#   Panel 12: Downstream service error rates
#   Panel 13: DB query latency p99
#   Panel 14: Cache hit rate
#   Panel 15: Message queue depth
#
# PANEL DESIGN PRINCIPLES:
#   - Use stat panels (big number) for current SLO status — instantly readable
#   - Use time-series for trends (last 24h / 7d) — show patterns
#   - Color thresholds: green/yellow/red tied to SLO values, not arbitrary numbers
#   - Consistent time ranges across all panels (use Grafana dashboard variable)
#   - Link panels to runbooks and trace queries (Tempo exemplar integration)
#   - Add annotations for deployments — vertical lines on graphs show when code changed
#
# EXEMPLARS (Prometheus + Grafana Tempo integration):
#   Prometheus stores trace_id alongside metric samples as "exemplars".
#   Grafana shows a diamond ◆ on the graph at the exemplar timestamp.
#   Click the diamond → jump to the specific trace in Tempo.
#   This connects "the p99 latency spike at 14:23" to an actual trace.
#   Enable in Prometheus: --enable-feature=exemplar-storage

GRAFANA_DASHBOARD_JSON_SNIPPET = """
// Grafana panel JSON for Error Budget gauge
// (simplified — real JSON is generated by terraform-grafana or Grafonnet)
{
  "type": "gauge",
  "title": "Error Budget Remaining",
  "fieldConfig": {
    "defaults": {
      "unit": "percentunit",
      "min": 0,
      "max": 1,
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {"color": "red",    "value": 0},     // 0-20%: critical
          {"color": "yellow", "value": 0.2},   // 20-50%: warning
          {"color": "green",  "value": 0.5}    // 50-100%: healthy
        ]
      }
    }
  },
  "targets": [{
    "expr": "1 - (\\n  sum(increase(http_errors_total{service=\\"payment-api\\"}[30d]))\\n  / sum(increase(http_requests_total{service=\\"payment-api\\"}[30d]))\\n) / 0.0005",
    "legendFormat": "Budget Remaining"
  }]
}
"""


# =============================================================================
# SECTION 9: RUNBOOK TEMPLATE — what to include
# =============================================================================
#
# Every alert must have a runbook. Runbooks prevent 3am confusion.
# Minimum required sections:

RUNBOOK_TEMPLATE = """
# Runbook: PaymentAPIAvailabilityCritical

## What is this alert?
The Payment API error rate has exceeded 0.72% over the past hour (14.4x burn rate).
At this rate, the monthly error budget will be exhausted in approximately 2 hours.

## Why does it matter?
- Users are experiencing payment failures.
- 1% of 10,000 req/min = 100 failed payments/minute.
- Continued failures risk SLO violation and SLA penalty.

## Immediate actions (< 5 minutes)
1. Check the error rate graph: [link to Grafana dashboard]
2. Check recent deployments: `kubectl rollout history deploy/payment-api`
3. If a bad deploy: `kubectl rollout undo deploy/payment-api`
4. Check downstream dependencies:
   - Stripe API status: https://status.stripe.com
   - Database: check `db_connections_active` gauge in Grafana

## Diagnostic queries
```promql
# What's the current error rate by endpoint?
sum by (endpoint) (rate(http_errors_total{service="payment-api"}[5m]))
  / sum by (endpoint) (rate(http_requests_total{service="payment-api"}[5m]))

# What error types are occurring?
sum by (error_type) (rate(http_errors_total{service="payment-api"}[5m]))
```

## Escalation
- After 10 minutes without resolution: page the payments team lead.
- After 30 minutes: page engineering director and start incident bridge.
- Incident channel: #incident-payments
- Incident commander rotation: [link to PagerDuty schedule]

## Related alerts
- PaymentAPILatencyCritical: high latency may co-occur with errors
- StripeAPIAvailability: if Stripe is down, error rate will be 100%

## Post-incident
- File incident report within 24 hours using template: [link]
- Add to weekly error budget review.
"""


# =============================================================================
# SECTION 10: DEMONSTRATION
# =============================================================================

def main():
    """Print error budget analysis and simulate burn rate calculations."""
    print("=== SLO Error Budget Analysis ===")
    print_slo_budget_analysis(AVAILABILITY_SLO)
    print_slo_budget_analysis(LATENCY_SLO)

    print("\n=== Burn Rate Simulation ===")
    # Simulate different error scenarios for the availability SLO
    scenarios = [
        (0.0001,  "Normal day — 0.01% errors"),
        (0.0010,  "Minor incident — 0.1% errors"),
        (0.0036,  "Significant incident — 0.36% errors (6x burn rate)"),
        (0.0072,  "Major incident — 0.72% errors (14.4x burn rate)"),
        (0.0100,  "Severe outage — 1% errors (20x burn rate)"),
    ]

    target = AVAILABILITY_SLO.target
    budget = AVAILABILITY_SLO.error_budget_ratio

    for error_rate, label in scenarios:
        burn = AVAILABILITY_SLO.burn_rate(error_rate)
        hours_to_exhaust = (30 * 24) / burn            # 30-day window in hours
        budget_remaining = AVAILABILITY_SLO.budget_remaining(
            error_rate * 30 * 24 / (30 * 24)           # simplified: 1 hour at this rate
        )

        print(f"\n  {label}")
        print(f"    Error rate: {error_rate*100:.3f}%  |  Burn rate: {burn:.1f}x")
        print(f"    Budget exhausted in: {hours_to_exhaust:.0f} hours ({hours_to_exhaust/24:.1f} days)")

    print("\n=== Alertmanager Silence Example ===")
    create_alertmanager_silence_example()

    print("\n=== Alert Configuration Reference ===")
    print("See MULTI_WINDOW_ALERTS_YAML for full burn rate alert rules.")
    print("See ALERTMANAGER_CONFIG_YAML for routing and receiver config.")
    print("See GOLDEN_SIGNALS_ALERTS_YAML for latency/traffic/saturation alerts.")
    print("See WATCHDOG_ALERT_YAML for dead man's switch configuration.")

    print("\n=== Key Thresholds Reference (30-day window, 99.95% SLO) ===")
    slo_target = 0.9995
    error_budget = 1 - slo_target
    print(f"Error budget per month: {error_budget*100:.4f}% = {error_budget*30*24*60:.1f} minutes")
    burn_rates = [(14.4, "1h", "2h"),  (6.0, "6h", "5 days"),  (3.0, "72h", "10 days")]
    for br, window, exhaustion in burn_rates:
        threshold = error_budget * br
        print(f"  {br}x burn rate (window={window}): error_rate > {threshold*100:.4f}%"
              f"  → budget exhausted in {exhaustion}")


if __name__ == "__main__":
    main()
