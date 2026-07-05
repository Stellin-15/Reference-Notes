# ============================================================
# L09: Event-Driven ML CI/CD — Registry-Triggered Canary and Rollback
# ============================================================
# WHAT: Wiring model deployment to EVENTS emitted by a model registry
#       (an alias change: "this model version is now `champion`") rather
#       than a manually-triggered deployment pipeline — canary rollout
#       and automatic rollback driven by those same events.
# WHY: This repo's MLOps Notes covers MLflow's registry and CI/CD for ML
#      generally. This lesson applies THIS domain's event-driven
#      architecture (L01-L05) specifically to the model-deployment
#      problem — turning "a data scientist updated a model alias" into
#      an automated, monitored, safely-rolled-back deployment, with zero
#      manual deployment steps.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
A MODEL REGISTRY (MLflow's, covered in this repo's MLOps Notes) tracks
model versions and lets you assign human-meaningful ALIASES (e.g.
`champion`, `challenger`) to specific versions — moving the `champion`
alias from version 3 to version 4 is the ACT of "promoting" a new model
to production, conceptually. An EVENT-DRIVEN CI/CD pipeline for ML
listens for exactly this alias-change EVENT (the registry emits it, or
a lightweight poller/webhook detects the change and publishes it onto
the event bus, L01-L02) and REACTS by automatically kicking off a
deployment — no human manually runs a deployment script; the alias
change itself IS the deployment trigger.

CANARY ROLLOUT, triggered by this event, means the newly-promoted model
version initially receives only a SMALL PERCENTAGE of production
traffic (e.g. 5%), with the previous `champion` version still serving
the remaining 95% — this limits the BLAST RADIUS of a bad model
promotion to a small fraction of real traffic while the new version's
actual production behavior is monitored.

AUTOMATIC ROLLBACK closes the loop: a monitoring process watches the
canary version's KEY METRICS (error rate, latency, and ideally
model-quality proxies like prediction-distribution drift) DURING the
canary period — if metrics degrade beyond a defined threshold, the
system AUTOMATICALLY reverts the alias back to the previous champion
version and routes 100% of traffic back to it, WITHOUT waiting for a
human to notice and manually intervene. Only if the canary period
completes with healthy metrics does the new version's traffic
percentage ramp up to 100%.

PRODUCTION USE CASE:
A data scientist updates the `champion` alias in the model registry to
point at a newly-trained fraud-detection model version. This alias
change emits an event; an event-driven CI/CD pipeline picks it up,
deploys the new version to receive 5% of live traffic, and monitors its
error rate and prediction latency for 30 minutes — during this window,
the new version's error rate spikes well above the previous version's
baseline (perhaps due to a subtle feature-computation bug not caught in
offline validation), triggering AUTOMATIC rollback to the previous
champion before the bad model ever affects more than 5% of real
production traffic, and well before any human needed to notice and react
manually.

COMMON MISTAKES:
- Triggering full (100%) traffic cutover immediately on an alias change
  instead of a gradual canary ramp — this maximizes the blast radius of
  any undetected issue with the new model, exactly the opposite of what
  canary rollout is meant to limit.
- Monitoring only INFRASTRUCTURE metrics (error rate, latency) during
  canary, without any MODEL-QUALITY-specific signal (prediction
  distribution shift, a proxy for actual accuracy degradation) — a model
  that returns fast, error-free, but SYSTEMATICALLY WRONG predictions
  can pass infrastructure-only health checks while still being a bad
  promotion that infrastructure metrics alone would never catch.
- Requiring a HUMAN to manually initiate rollback after being alerted,
  instead of automatic rollback — the entire latency advantage of
  event-driven, automated deployment is undermined if the SAFETY
  mechanism (rollback) still depends on a human noticing an alert and
  acting quickly enough.
"""

import textwrap
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


# ------------------------------------------------------------------
# 1. The registry alias-change event that triggers everything
# ------------------------------------------------------------------
@dataclass
class AliasChangeEvent:
    model_name: str
    alias: str
    new_version: int
    previous_version: int
    timestamp: datetime


REGISTRY_WEBHOOK_EXAMPLE = textwrap.dedent("""\
    # MLflow can be configured to fire a webhook on registry events —
    # this webhook receiver publishes the event onto the shared event
    # bus (NATS JetStream, L02), unifying ML-deployment events with
    # every other event type this domain covers.
    from fastapi import FastAPI, Request

    app = FastAPI()

    @app.post("/mlflow-webhook")
    async def handle_registry_event(request: Request):
        payload = await request.json()
        if payload["event_type"] == "MODEL_VERSION_ALIAS_CREATED":
            event = AliasChangeEvent(
                model_name=payload["model_name"], alias=payload["alias"],
                new_version=payload["version"], previous_version=payload["previous_version"],
                timestamp=datetime.now(),
            )
            await publish_to_event_bus("model_alias_changed", event)
""")

# ------------------------------------------------------------------
# 2. Canary rollout state machine
# ------------------------------------------------------------------
class CanaryState(Enum):
    RAMPING = "ramping"
    HEALTHY_FULL_ROLLOUT = "healthy_full_rollout"
    ROLLED_BACK = "rolled_back"


@dataclass
class CanaryDeployment:
    model_name: str
    canary_version: int
    stable_version: int
    canary_traffic_pct: int = 5
    state: CanaryState = CanaryState.RAMPING
    started_at: datetime = None


@dataclass
class HealthMetrics:
    error_rate: float
    p99_latency_ms: float
    prediction_drift_score: float   # a proxy signal for model-quality degradation


def evaluate_canary_health(metrics: HealthMetrics, baseline: HealthMetrics) -> bool:
    """
    Checks BOTH infrastructure health (error rate, latency) AND a
    model-quality proxy (prediction drift) — a canary that's fast and
    error-free but producing a badly-shifted prediction distribution
    should still fail this check, since infra metrics alone can't catch
    a systematically-wrong-but-technically-healthy model.
    """
    error_rate_ok = metrics.error_rate <= baseline.error_rate * 1.5
    latency_ok = metrics.p99_latency_ms <= baseline.p99_latency_ms * 1.3
    drift_ok = metrics.prediction_drift_score <= 0.15   # a fixed, task-specific threshold
    return error_rate_ok and latency_ok and drift_ok


def process_canary_step(deployment: CanaryDeployment, current_metrics: HealthMetrics,
                          baseline_metrics: HealthMetrics) -> CanaryDeployment:
    if not evaluate_canary_health(current_metrics, baseline_metrics):
        deployment.state = CanaryState.ROLLED_BACK
        print(f"  ROLLBACK: canary version {deployment.canary_version} failed health "
              f"check — reverting 100% traffic to stable version {deployment.stable_version}")
        return deployment

    if deployment.canary_traffic_pct >= 100:
        deployment.state = CanaryState.HEALTHY_FULL_ROLLOUT
        print(f"  PROMOTED: version {deployment.canary_version} is now serving 100% of traffic")
    else:
        deployment.canary_traffic_pct = min(100, deployment.canary_traffic_pct * 2)
        print(f"  RAMPING: canary healthy, increasing traffic to {deployment.canary_traffic_pct}%")

    return deployment


# ------------------------------------------------------------------
# 3. Full event-driven flow, simulated end to end
# ------------------------------------------------------------------
def simulate_deployment_flow(canary_will_fail: bool):
    deployment = CanaryDeployment(model_name="fraud_detector", canary_version=4, stable_version=3,
                                    started_at=datetime.now())
    baseline = HealthMetrics(error_rate=0.01, p99_latency_ms=120, prediction_drift_score=0.05)

    print(f"\n--- Simulating deployment (canary_will_fail={canary_will_fail}) ---")
    for step in range(4):
        if canary_will_fail and step == 1:
            current = HealthMetrics(error_rate=0.08, p99_latency_ms=130, prediction_drift_score=0.05)
        else:
            current = HealthMetrics(error_rate=0.011, p99_latency_ms=118, prediction_drift_score=0.04)

        deployment = process_canary_step(deployment, current, baseline)
        if deployment.state in (CanaryState.ROLLED_BACK, CanaryState.HEALTHY_FULL_ROLLOUT):
            break

    print(f"  Final state: {deployment.state.value}")


if __name__ == "__main__":
    print(REGISTRY_WEBHOOK_EXAMPLE)
    simulate_deployment_flow(canary_will_fail=False)
    simulate_deployment_flow(canary_will_fail=True)

"""
PRODUCTION CONTEXT EXAMPLE:
A fraud-detection model's promotion (a data scientist moving the
`champion` alias to a new version) automatically triggers a canary
rollout via this event-driven pipeline — during the canary window, the
prediction-drift signal (not error rate or latency, which stayed normal)
flags the new version's fraud-score distribution shifting meaningfully
away from the training-time baseline, triggering automatic rollback
before the new version ever received more than 10% of production
traffic — a production incident (a subtly miscalibrated model silently
approving fraudulent transactions) contained and reverted automatically,
without a human needing to notice and manually intervene during the
critical early window.
"""
