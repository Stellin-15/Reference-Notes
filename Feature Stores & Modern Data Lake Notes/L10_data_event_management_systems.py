# ============================================================
# L10: Data Event Management Systems — The Event Ledger Pattern
# ============================================================
# WHAT: A DEMS/Lasso-style architecture pattern — emitting a structured
#       EVENT on every meaningful read/write across the feature platform
#       (feature registration, materialization, model training, model
#       serving), and building an append-only EVENT LEDGER that becomes
#       the substrate for lineage (L09), drift detection, and SLA analytics.
# WHY: L09's lineage graph, and any drift/SLA monitoring, need
#      ACCURATE, UP-TO-DATE data about what actually happened across the
#      platform. Rather than each consuming system (lineage, monitoring,
#      auditing) independently instrumenting the platform, a SINGLE
#      event ledger — emitted once, consumed many ways — is a far more
#      maintainable architecture.
# LEVEL: Advanced (final lesson before the capstone)
# ============================================================

"""
CONCEPT OVERVIEW:
The core architectural idea: instead of building lineage tracking, drift
detection, and SLA monitoring as THREE SEPARATE instrumentation efforts
(each needing its own hooks scattered through the platform's code), emit
ONE STRUCTURED EVENT STREAM covering every meaningful platform
OPERATION — a feature was registered, a materialization job ran and
wrote N rows, a model was trained using specific features, a model
served a prediction using specific feature values — and let EACH
consuming use case (lineage, drift, SLA, audit) derive its own view from
that SAME underlying event ledger, rather than instrumenting the
platform three separate times.

This is the DEMS/Lasso pattern: an APPEND-ONLY EVENT LEDGER (conceptually
similar to an event-sourcing log) where every event has a consistent
envelope — event type, timestamp, actor (which system/user triggered
it), and a payload specific to that event type. Because it's append-only
and every event is timestamped, the ledger itself becomes a natural
audit trail (compliance-relevant: "prove that this specific access
happened at this specific time") and a natural DATA SOURCE for
downstream analytics — the lineage graph (L09) can be BUILT BY REPLAYING
the ledger's "feature X was defined from source Y" and "model Z was
trained using feature X" events, rather than being separately maintained.

DRIFT DETECTION becomes a ledger-derived analysis: by comparing the
DISTRIBUTION of feature values in "materialization" events over time
(this week's average value of feature X vs last month's), a drift-
detection job can flag when a feature's real-world distribution has
shifted meaningfully — without needing separate instrumentation beyond
what the ledger already captures for other purposes.

SLA ANALYTICS similarly derives from the ledger: "materialization" events
carry a timestamp of when they RAN and (from the Feature View
definition, L03) an expected SCHEDULE — comparing actual event timestamps
against expected schedule reveals SLA violations (a materialization job
that should run hourly but hasn't emitted an event in 6 hours is a
concrete, ledger-derivable signal) automatically, without a separate
monitoring system needing its own instrumentation.

PRODUCTION USE CASE:
A platform-wide incident ("several models' predictions look off since
this morning") is root-caused by querying the event ledger for all
materialization events in the affected time window — revealing that ONE
specific Feature View's materialization job silently failed to run for 6
hours (a clear ledger gap), and that failure's downstream impact is
immediately computable by combining the ledger data with the lineage
graph (L09) built from that same ledger — turning what could be a
multi-hour, multi-team investigation into a query answerable in minutes,
matching the "minutes instead of weeks" outcome a well-built event ledger
enables.

COMMON MISTAKES:
- Building lineage, drift detection, and SLA monitoring as three
  independently-instrumented systems instead of three VIEWS derived from
  one shared event ledger — this triples the instrumentation surface
  area and creates three separate places for tracking to silently drift
  out of sync with the platform's actual behavior.
- Treating the event ledger as purely an operational/debugging tool and
  underestimating its COMPLIANCE value — an append-only, timestamped
  record of every feature/model operation is directly useful evidence
  for audits and regulatory data-access questions, a benefit easy to
  overlook if the ledger is designed with only observability in mind.
- Not designing the event SCHEMA/envelope consistently across event
  types from the start — an inconsistent envelope (different field names
  for "timestamp" or "actor" across different event types) makes
  building general-purpose downstream analytics (which need to query
  ACROSS event types) significantly harder than necessary.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


# ------------------------------------------------------------------
# 1. A consistent event envelope across all event types
# ------------------------------------------------------------------
class EventType(Enum):
    FEATURE_REGISTERED = "feature_registered"
    MATERIALIZATION_RUN = "materialization_run"
    MODEL_TRAINED = "model_trained"
    MODEL_SERVED = "model_served"


@dataclass
class PlatformEvent:
    event_type: EventType
    timestamp: datetime
    actor: str          # which system/user triggered this
    payload: dict = field(default_factory=dict)


class EventLedger:
    """An append-only event ledger — the single instrumentation point
    every downstream use case (lineage, drift, SLA) derives from."""

    def __init__(self):
        self.events: list[PlatformEvent] = []

    def emit(self, event: PlatformEvent):
        self.events.append(event)   # append-only — never mutate/delete past events

    def query(self, event_type: EventType | None = None,
              since: datetime | None = None) -> list[PlatformEvent]:
        results = self.events
        if event_type:
            results = [e for e in results if e.event_type == event_type]
        if since:
            results = [e for e in results if e.timestamp >= since]
        return results


# ------------------------------------------------------------------
# 2. Building lineage (L09) by replaying the ledger
# ------------------------------------------------------------------
def build_lineage_from_ledger(ledger: EventLedger) -> dict[str, list[str]]:
    """
    Rather than lineage being a separately-maintained data structure,
    it's DERIVED by replaying "feature_registered" and "model_trained"
    events — if the ledger is accurate (captured automatically as a
    byproduct of normal operations), the lineage graph is automatically
    accurate too, with no separate maintenance burden.
    """
    dependencies: dict[str, list[str]] = {}

    for event in ledger.query(EventType.FEATURE_REGISTERED):
        feature_name = event.payload["feature_name"]
        source = event.payload["source_table"]
        dependencies.setdefault(feature_name, []).append(source)

    for event in ledger.query(EventType.MODEL_TRAINED):
        model_name = event.payload["model_name"]
        features_used = event.payload["features_used"]
        dependencies.setdefault(model_name, []).extend(features_used)

    return dependencies


# ------------------------------------------------------------------
# 3. Drift detection derived from materialization events
# ------------------------------------------------------------------
def detect_drift_from_ledger(ledger: EventLedger, feature_name: str,
                                recent_window: timedelta, baseline_window: timedelta,
                                now: datetime) -> dict:
    """Compares a feature's average materialized value in a RECENT
    window against an earlier BASELINE window — both views derived from
    the same materialization_run events, no separate drift-specific
    instrumentation required."""
    events = ledger.query(EventType.MATERIALIZATION_RUN, since=now - baseline_window)
    events = [e for e in events if e.payload.get("feature_name") == feature_name]

    recent = [e.payload["avg_value"] for e in events if e.timestamp >= now - recent_window]
    baseline = [e.payload["avg_value"] for e in events if e.timestamp < now - recent_window]

    if not recent or not baseline:
        return {"status": "insufficient_data"}

    recent_avg = sum(recent) / len(recent)
    baseline_avg = sum(baseline) / len(baseline)
    pct_change = abs(recent_avg - baseline_avg) / max(abs(baseline_avg), 1e-9) * 100

    return {
        "feature": feature_name, "baseline_avg": baseline_avg, "recent_avg": recent_avg,
        "pct_change": pct_change, "drift_flagged": pct_change > 20,
    }


# ------------------------------------------------------------------
# 4. SLA violation detection — a gap in expected event cadence
# ------------------------------------------------------------------
def detect_sla_violation(ledger: EventLedger, feature_name: str,
                            expected_interval: timedelta, now: datetime) -> dict:
    events = [e for e in ledger.query(EventType.MATERIALIZATION_RUN)
              if e.payload.get("feature_name") == feature_name]
    if not events:
        return {"status": "never_materialized", "violation": True}

    last_run = max(e.timestamp for e in events)
    time_since_last_run = now - last_run
    return {
        "feature": feature_name, "last_run": last_run,
        "time_since_last_run": time_since_last_run,
        "violation": time_since_last_run > expected_interval * 1.5,   # 50% grace margin
    }


if __name__ == "__main__":
    ledger = EventLedger()
    base_time = datetime(2026, 1, 1)

    ledger.emit(PlatformEvent(EventType.FEATURE_REGISTERED, base_time, "platform-team",
                               {"feature_name": "avg_transaction_7d", "source_table": "raw.transactions"}))
    ledger.emit(PlatformEvent(EventType.MODEL_TRAINED, base_time + timedelta(days=1), "fraud-team",
                               {"model_name": "fraud_detector_v2", "features_used": ["avg_transaction_7d"]}))

    for i in range(5):
        ledger.emit(PlatformEvent(
            EventType.MATERIALIZATION_RUN, base_time + timedelta(hours=i),
            "materialization-job", {"feature_name": "avg_transaction_7d", "avg_value": 100.0 + i * 2},
        ))
    # A later run showing a real distribution shift
    ledger.emit(PlatformEvent(
        EventType.MATERIALIZATION_RUN, base_time + timedelta(hours=10),
        "materialization-job", {"feature_name": "avg_transaction_7d", "avg_value": 180.0},
    ))

    print("Lineage derived from ledger replay:")
    for name, deps in build_lineage_from_ledger(ledger).items():
        print(f"  {name} <- {deps}")

    print("\nDrift detection derived from the same ledger:")
    drift_result = detect_drift_from_ledger(
        ledger, "avg_transaction_7d",
        recent_window=timedelta(hours=2), baseline_window=timedelta(hours=12),
        now=base_time + timedelta(hours=11),
    )
    print(f"  {drift_result}")

    print("\nSLA violation check:")
    sla_result = detect_sla_violation(
        ledger, "avg_transaction_7d",
        expected_interval=timedelta(hours=1),
        now=base_time + timedelta(hours=20),   # a long time after the last recorded run
    )
    print(f"  {sla_result}")

"""
PRODUCTION CONTEXT EXAMPLE:
A platform team investigates why several models' predictions seem off —
querying the event ledger for materialization events in the affected
window reveals one Feature View's job silently stopped emitting events 6
hours ago (an SLA violation the ledger surfaces automatically, per
`detect_sla_violation`), and the lineage view derived from that same
ledger (per `build_lineage_from_ledger`) immediately shows which two
production models depend on that stale feature — root-causing a
platform-wide incident to one specific failed job in minutes, entirely
from data the ledger was already capturing for other purposes.
"""
