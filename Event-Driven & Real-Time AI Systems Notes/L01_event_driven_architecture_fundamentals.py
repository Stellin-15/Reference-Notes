# ============================================================
# L01: Event-Driven Architecture Fundamentals
# ============================================================
# WHAT: The core event-driven pattern — producers emit events, an
#       event bus/broker distributes them, consumers react — versus
#       batch and request-response models, plus the practical question
#       of choosing EVENT GRANULARITY (what counts as "one event").
# WHY: Every lesson in this domain (NATS, Hatchet, real-time triggers,
#      multi-model routing) builds on this pattern. Before comparing
#      specific message brokers, you need a clear model of WHAT problem
#      event-driven architecture solves and when it's the right choice
#      at all.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
BATCH processing (this repo's Data Engineering Notes covers Airflow-
orchestrated batch pipelines extensively) runs on a SCHEDULE — data
accumulates, then a job processes everything accumulated since the last
run. This is simple and efficient for high-throughput, latency-tolerant
work, but introduces LATENCY BY DESIGN: something that happened just
after a batch run started won't be processed until the NEXT scheduled run.

REQUEST-RESPONSE (a typical REST API call) processes ONE unit of work
immediately, synchronously, with the caller waiting for a direct answer
— low latency for that one request, but couples the caller's own latency
to however long the work takes, and doesn't naturally support "notify
many interested parties when something happens" (a REST endpoint has one
caller per call, not a fan-out to arbitrary subscribers).

EVENT-DRIVEN architecture sits between these: a PRODUCER emits an EVENT
(a fact: "something happened," e.g. `stage_changed`, `deposit_confirmed`)
onto an EVENT BUS/BROKER, WITHOUT knowing or caring who (if anyone) is
listening. Any number of CONSUMERS can SUBSCRIBE to relevant event types
and react independently, asynchronously, at their own pace. This
decouples producers from consumers entirely (a producer can be deployed,
scaled, or modified without needing consumers to change, as long as the
event's SHAPE stays stable) and naturally supports both LOW-LATENCY
reaction (a consumer processes an event within milliseconds of it being
emitted, unlike batch's schedule-bound delay) and FAN-OUT (many
independent consumers reacting to the same event for different purposes).

EVENT GRANULARITY is a genuine design decision, not a given: should
"a customer's deposit was confirmed" be ONE event, or should it be
decomposed into "payment_received" + "balance_updated" + "notification_
queued" as three separate, more granular events? Finer granularity gives
consumers more precise subscription options (a consumer only interested
in payment status doesn't need to filter out balance-update noise) at
the cost of more event TYPES to define, document, and keep backward-
compatible over time. Coarser granularity is simpler to reason about
initially but can force consumers to subscribe to (and filter out
irrelevant parts of) a "kitchen sink" event they only partially care about.

PRODUCTION USE CASE:
A trigger-evaluation platform for a business's growth/marketing
workflows needs to react to customer lifecycle events (a stage change, a
confirmed deposit, a computed feature update, a detected anomaly) within
minutes, not on a nightly batch schedule — but ALSO needs multiple
independent downstream systems (a marketing-automation trigger evaluator,
an analytics pipeline, a fraud-monitoring system) to each react to the
SAME underlying events for entirely different purposes, without any of
them needing to know about or coordinate with the others — this is
precisely the shape event-driven architecture, not batch or pure
request-response, is built to serve.

COMMON MISTAKES:
- Defaulting to event-driven architecture for EVERYTHING, including
  workloads that are genuinely fine as scheduled batch jobs — event-
  driven systems add real operational complexity (a broker to run, event
  schema versioning, harder end-to-end debugging across async
  boundaries); reach for it when LATENCY or DECOUPLING genuinely matter,
  not as a default architectural style.
- Choosing event granularity too coarse, forcing every consumer to parse
  and filter a large, multi-purpose event payload for the small slice
  they actually need — this couples unrelated concerns into one event
  type, and changing ANY part of that payload risks breaking EVERY
  consumer, even ones that never used the changed field.
- Choosing event granularity too fine without a real need — decomposing
  a single logical business event into many tightly-coupled, always-
  co-occurring smaller events multiplies the number of event types to
  maintain without a corresponding benefit, since no consumer actually
  wants just one of them independently of the others.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


# ------------------------------------------------------------------
# 1. Batch vs request-response vs event-driven — the same task, three ways
# ------------------------------------------------------------------
def batch_approach(deposits_since_last_run: list[dict]) -> list[str]:
    """Runs on a SCHEDULE — a deposit made right after this batch starts
    waits until the NEXT scheduled run to be processed."""
    return [f"processed deposit {d['id']} (batch, scheduled run)" for d in deposits_since_last_run]


def request_response_approach(deposit: dict) -> str:
    """Processes ONE deposit synchronously — low latency for THIS
    caller, but no natural way to notify OTHER interested systems."""
    return f"processed deposit {deposit['id']} (synchronous, one caller waiting)"


@dataclass
class Event:
    event_type: str
    payload: dict
    timestamp: datetime = field(default_factory=datetime.now)


class SimpleEventBus:
    """A minimal illustration of the decoupled producer/consumer
    relationship — the producer emitting an event has NO knowledge of
    which (if any) consumers are subscribed."""

    def __init__(self):
        self.subscribers: dict[str, list] = {}

    def subscribe(self, event_type: str, handler):
        self.subscribers.setdefault(event_type, []).append(handler)

    def publish(self, event: Event):
        for handler in self.subscribers.get(event.event_type, []):
            handler(event)   # each subscriber reacts independently, at its own pace


def event_driven_approach_demo():
    bus = SimpleEventBus()

    # THREE independent consumers, each subscribing for a DIFFERENT
    # reason — none of them know about each other, and none of them
    # required the producer (below) to be aware they exist.
    bus.subscribe("deposit_confirmed", lambda e: print(f"  [marketing] evaluate triggers for {e.payload['customer_id']}"))
    bus.subscribe("deposit_confirmed", lambda e: print(f"  [analytics] record deposit event {e.payload}"))
    bus.subscribe("deposit_confirmed", lambda e: print(f"  [fraud] check deposit velocity for {e.payload['customer_id']}"))

    # The producer just emits a FACT — it doesn't call marketing,
    # analytics, or fraud systems directly, and doesn't need to know
    # they exist at all.
    bus.publish(Event("deposit_confirmed", {"customer_id": "cust_1", "amount": 500.0}))


# ------------------------------------------------------------------
# 2. Event granularity — a real design decision, illustrated
# ------------------------------------------------------------------
class CoarseEventType(Enum):
    DEPOSIT_PROCESSED = "deposit_processed"   # ONE event covering multiple sub-facts


class FineEventTypes(Enum):
    PAYMENT_RECEIVED = "payment_received"
    BALANCE_UPDATED = "balance_updated"
    NOTIFICATION_QUEUED = "notification_queued"


def coarse_granularity_example():
    """A consumer only interested in PAYMENT status must still receive
    (and filter out) balance/notification details it doesn't need."""
    event = Event(CoarseEventType.DEPOSIT_PROCESSED.value, {
        "payment_status": "received", "new_balance": 1500.0, "notification_sent": True,
    })
    print(f"  Coarse event payload (consumer must filter): {event.payload}")


def fine_granularity_example():
    """Three separate event types — a payment-status-only consumer
    subscribes to JUST payment_received, receiving a focused payload."""
    events = [
        Event(FineEventTypes.PAYMENT_RECEIVED.value, {"payment_status": "received"}),
        Event(FineEventTypes.BALANCE_UPDATED.value, {"new_balance": 1500.0}),
        Event(FineEventTypes.NOTIFICATION_QUEUED.value, {"notification_sent": True}),
    ]
    for e in events:
        print(f"  Fine-grained event '{e.event_type}': {e.payload}")


if __name__ == "__main__":
    print("=== Batch approach ===")
    for result in batch_approach([{"id": "d1"}, {"id": "d2"}]):
        print(f"  {result}")

    print("\n=== Request-response approach ===")
    print(f"  {request_response_approach({'id': 'd3'})}")

    print("\n=== Event-driven approach — fan-out to 3 independent consumers ===")
    event_driven_approach_demo()

    print("\n=== Granularity comparison ===")
    coarse_granularity_example()
    fine_granularity_example()

"""
PRODUCTION CONTEXT EXAMPLE:
A growth platform's trigger-evaluation system defines a handful of
specific, well-scoped event types (`stage_changed`, `deposit_confirmed`,
`feature_change`, `anomaly`, `external`) rather than one giant
"customer_activity" event — this granularity choice lets a marketing-
automation consumer subscribe ONLY to `stage_changed` and `deposit_
confirmed` (the events actually relevant to trigger evaluation) while a
separate fraud-monitoring consumer subscribes to `anomaly` and `deposit_
confirmed`, each receiving a focused, relevant event stream rather than
filtering a monolithic activity feed — the specific granularity decision
this lesson's L01-L02 examples illustrate, applied to a real production
event taxonomy.
"""
