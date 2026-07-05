# ============================================================
# L05: Building a Real-Time Trigger Evaluation System
# ============================================================
# WHAT: Combining L01-L04 into an actual "Trigger Hub"-style event bus —
#       subject-stream design for a real business domain, the trigger-
#       evaluation loop itself, and the concrete before/after of moving
#       a pipeline from batch (hours) to real-time (sub-5-minute) latency.
# WHY: This is where the event-driven fundamentals (L01), NATS/JetStream
#      (L02-L03), and durable execution (L04) combine into the specific,
#      recognizable system pattern behind marketing-automation and
#      lifecycle-messaging platforms — "when X happens to a customer,
#      evaluate whether any business rule should fire, and if so, act."
# LEVEL: Intermediate/Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
A TRIGGER is a business rule of the shape "WHEN this type of event
happens, IF this condition holds, THEN take this action" — e.g. "when a
customer's deposit is confirmed, if their lifetime deposit total just
crossed $10,000, send a VIP-tier welcome message." A TRIGGER HUB is the
platform component responsible for: receiving relevant events, evaluating
them against EVERY currently-active trigger definition, and dispatching
the actions of any triggers whose conditions matched.

The architecture combines everything from L01-L04: an EVENT BUS (NATS
JetStream, L02) with a small number of well-designed SUBJECTS (L01's
granularity discussion, applied concretely: `stage_changed`, `deposit_
confirmed`, `feature_change`, `anomaly`, `external` — five subjects
covering the actual event TYPES the business cares about, not one
per possible trigger). A DURABLE CONSUMER reads from these subjects and,
for each event, uses a DURABLE EXECUTION ENGINE (Hatchet, L04) to FAN OUT
evaluation across every currently-active trigger definition in parallel
— each trigger's evaluation is independently retriable, so one
misbehaving trigger's evaluation logic failing doesn't block or fail the
evaluation of any other trigger for that same event.

The BATCH-TO-REAL-TIME TRANSFORMATION this architecture enables is
concrete and measurable: a BATCH-BASED trigger system (nightly job scans
all events from the last 24 hours, evaluates every trigger against all
of them) has LATENCY BOUNDED BY THE BATCH SCHEDULE — a customer's
deposit that crosses a VIP threshold at 9am doesn't trigger a welcome
message until the next batch run, potentially many hours later. The
EVENT-DRIVEN architecture described here evaluates that SAME trigger
within seconds of the event being published, bounded only by the event
bus's delivery latency plus the trigger-evaluation task's own execution
time — a genuine, measurable shift from hours to sub-5-minute (often
sub-second) reaction time.

PRODUCTION USE CASE:
A growth-marketing platform's Trigger Hub processes customer lifecycle
events across 5 subject types, evaluating them against dozens of
active, business-team-defined trigger rules — a stage-change event
(e.g. "trial" -> "paying customer") is evaluated against every active
trigger within seconds, dispatching a personalized onboarding sequence
almost immediately after the actual stage transition, rather than the
batch-based alternative's multi-hour delay, directly improving the
timeliness (and therefore effectiveness) of lifecycle marketing messaging.

COMMON MISTAKES:
- Evaluating EVERY trigger against EVERY event type indiscriminately,
  instead of first filtering triggers to only those RELEVANT to the
  incoming event's type — this wastes compute evaluating, say, a
  deposit-related trigger against a stage-change event it could never
  possibly match, at scale becoming a real, avoidable cost.
- Not making trigger evaluation IDEMPOTENT — if a durable execution
  engine retries a trigger evaluation (L04) after a transient failure,
  and that evaluation's ACTION (e.g. "send a message") isn't idempotent,
  a retry can cause the same customer to receive the same message twice.
- Coupling trigger DEFINITION changes (business teams editing rules) too
  tightly to the deployed evaluation code — a well-designed system lets
  business/marketing teams define/edit triggers via a UI or config,
  without requiring an engineering deployment for every new trigger rule.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta


# ------------------------------------------------------------------
# 1. Trigger definitions — data, not code, so non-engineers can define them
# ------------------------------------------------------------------
@dataclass
class TriggerDefinition:
    trigger_id: str
    event_type: str            # which subject this trigger cares about
    condition: str               # a simple expression evaluated against the event payload
    action: str                   # what to do if the condition matches
    active: bool = True


class TriggerRegistry:
    def __init__(self):
        self.triggers: list[TriggerDefinition] = []

    def register(self, trigger: TriggerDefinition):
        self.triggers.append(trigger)

    def relevant_triggers(self, event_type: str) -> list[TriggerDefinition]:
        """
        FILTERS to only triggers relevant to this event's TYPE before
        any evaluation happens — avoids wastefully evaluating a deposit-
        related trigger against a stage-change event, for example.
        """
        return [t for t in self.triggers if t.active and t.event_type == event_type]


# ------------------------------------------------------------------
# 2. Trigger evaluation — fanned out, individually safe to retry
# ------------------------------------------------------------------
@dataclass
class LifecycleEvent:
    event_type: str
    customer_id: str
    payload: dict
    timestamp: datetime = field(default_factory=datetime.now)


def evaluate_condition(condition: str, payload: dict) -> bool:
    """A simplified condition evaluator — a real system would use a safe,
    sandboxed expression language, not raw eval(), for user-authored
    business rules."""
    if condition == "lifetime_deposit_crosses_10000":
        return payload.get("lifetime_total", 0) >= 10000 and payload.get("previous_total", 0) < 10000
    return False


def dispatch_action(action: str, customer_id: str, seen_actions: set[tuple]) -> str:
    """
    IDEMPOTENT dispatch: tracks (customer_id, action) pairs already
    dispatched for this event, so a RETRY of this evaluation (per L04's
    durable execution) doesn't send a duplicate message to the customer.
    """
    key = (customer_id, action)
    if key in seen_actions:
        return f"SKIPPED (already dispatched): {action} for {customer_id}"
    seen_actions.add(key)
    return f"DISPATCHED: {action} for {customer_id}"


def evaluate_event_against_all_triggers(
    event: LifecycleEvent, registry: TriggerRegistry, seen_actions: set[tuple],
) -> list[str]:
    """
    The FAN-OUT evaluation loop — conceptually what a Hatchet workflow
    (L04) would parallelize across many independent tasks in production;
    shown here as a sequential loop to keep the evaluation LOGIC visible
    without requiring a running Hatchet/NATS deployment for this illustration.
    """
    results = []
    relevant = registry.relevant_triggers(event.event_type)
    for trigger in relevant:
        matched = evaluate_condition(trigger.condition, event.payload)
        if matched:
            result = dispatch_action(trigger.action, event.customer_id, seen_actions)
            results.append(result)
    return results


# ------------------------------------------------------------------
# 3. Batch vs real-time latency, made concrete
# ------------------------------------------------------------------
def simulate_batch_latency(event_time: datetime, batch_schedule_hour: int) -> timedelta:
    """A batch job runs once per day at a fixed hour — latency is the
    gap between the event and the NEXT scheduled run."""
    next_run = event_time.replace(hour=batch_schedule_hour, minute=0, second=0, microsecond=0)
    if next_run <= event_time:
        next_run += timedelta(days=1)
    return next_run - event_time


def simulate_realtime_latency(event_bus_delivery_ms: int, evaluation_duration_ms: int) -> timedelta:
    """Real-time latency is bounded by delivery + evaluation time, not a schedule."""
    return timedelta(milliseconds=event_bus_delivery_ms + evaluation_duration_ms)


if __name__ == "__main__":
    registry = TriggerRegistry()
    registry.register(TriggerDefinition(
        "vip_welcome", event_type="deposit_confirmed",
        condition="lifetime_deposit_crosses_10000",
        action="send_vip_welcome_message",
    ))
    registry.register(TriggerDefinition(
        "onboarding_sequence", event_type="stage_changed",
        condition="became_paying_customer", action="start_onboarding_sequence",
    ))

    event = LifecycleEvent(
        "deposit_confirmed", "cust_1",
        {"lifetime_total": 10500, "previous_total": 9800},
    )

    seen_actions: set[tuple] = set()
    print("First evaluation (should dispatch):")
    for result in evaluate_event_against_all_triggers(event, registry, seen_actions):
        print(f"  {result}")

    print("\nRetried evaluation (per L04 durability — should be idempotent, no duplicate send):")
    for result in evaluate_event_against_all_triggers(event, registry, seen_actions):
        print(f"  {result}")

    print("\n--- Batch vs real-time latency comparison ---")
    event_time = datetime(2026, 1, 15, 9, 0, 0)   # a deposit at 9am
    batch_latency = simulate_batch_latency(event_time, batch_schedule_hour=2)   # 2am nightly batch
    realtime_latency = simulate_realtime_latency(event_bus_delivery_ms=50, evaluation_duration_ms=800)

    print(f"  Batch approach: {batch_latency} until next scheduled run")
    print(f"  Real-time approach: {realtime_latency} total end-to-end latency")

"""
PRODUCTION CONTEXT EXAMPLE:
A platform's migration from a nightly batch trigger-evaluation job to
this event-driven architecture (5 well-designed subjects on NATS
JetStream, Hatchet-based fanned-out evaluation, idempotent action
dispatch) took trigger evaluation from "next business day, on average"
to "under 5 minutes end to end" — a change that directly improved
lifecycle-marketing message relevance (a VIP welcome message sent within
minutes of crossing the threshold, rather than a day later when the
moment's context has faded), measured as the platform's own explicit
before/after latency metric.
"""
