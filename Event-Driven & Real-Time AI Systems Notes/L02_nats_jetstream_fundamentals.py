# ============================================================
# L02: NATS and JetStream Fundamentals
# ============================================================
# WHAT: NATS core pub/sub messaging, and JetStream — NATS's persistence
#       layer adding durable streams, consumers, and at-least-once
#       delivery guarantees on top of NATS's simple, extremely
#       lightweight core protocol.
# WHY: L01 established WHY event-driven architecture matters. NATS is
#      one of the two dominant open-source messaging systems for
#      actually implementing it (alongside Kafka, already covered deeply
#      in this repo's Apache Kafka Notes) — and it makes different
#      design tradeoffs specifically suited to lower-operational-
#      overhead, moderate-throughput use cases (L03 covers the explicit
#      comparison).
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
NATS CORE is deliberately minimal: publishers send messages to a
SUBJECT (a hierarchical, dot-separated string like `orders.created` or
`customer.*.deposit`), and subscribers subscribe to subjects (including
WILDCARD patterns — `*` matches one token, `>` matches one-or-more
trailing tokens). Core NATS messaging is FIRE-AND-FORGET — if no
subscriber is currently listening when a message is published, that
message is simply lost; there's no persistence or replay in core NATS
by design. This simplicity is exactly what makes core NATS extremely
fast and operationally lightweight — it's not a lesser Kafka, it's a
DIFFERENT tool optimized for a different point on the durability/
simplicity tradeoff curve.

JETSTREAM is NATS's PERSISTENCE layer, added on top of core NATS,
providing exactly the durability guarantees core NATS deliberately
omits: a STREAM captures and stores messages published to one or more
subjects (with configurable retention: by count, by age, or by total
size), and a CONSUMER reads from a stream with an explicit,
trackable position (an "ack floor") — supporting AT-LEAST-ONCE delivery
(a consumer that crashes before acknowledging a message will re-receive
it on restart) and message REPLAY (a new consumer can start from the
BEGINNING of a stream's retained history, not just from "now," which
core NATS's fire-and-forget model cannot do at all).

SUBJECT DESIGN matters in NATS the same way partition-key design matters
in ScyllaDB (Feature Stores & Modern Data Lake Notes L08) or topic/
partition design matters in Kafka — a well-designed subject hierarchy
(e.g. `orders.<region>.<status>`) lets consumers subscribe with
wildcards at exactly the granularity they need (`orders.us-east.*` for
one region's orders regardless of status, or `orders.*.failed` for
failed orders across all regions) without needing separate topics per
combination.

PRODUCTION USE CASE:
A real-time trigger-evaluation platform (L05 covers building this in
depth) publishes events to subjects like `stage_changed`, `deposit_
confirmed`, `feature_change`, `anomaly`, and `external` — using
JetStream (not core NATS) specifically because trigger evaluation MUST
NOT silently miss an event (at-least-once delivery is required for
correctness), and because a newly-deployed trigger-evaluation consumer
needs to be able to catch up on recent history (replay) rather than only
seeing events from the moment it started.

COMMON MISTAKES:
- Using core NATS (fire-and-forget) for a use case that genuinely needs
  durability/replay, then being surprised when messages are silently
  lost during a consumer restart or deployment — this is CORE NATS
  working exactly as designed, not a bug; the fix is using JetStream,
  not "core NATS with extra reliability code bolted on."
- Designing an overly flat subject hierarchy (one subject per message
  type with no further structure) that forces consumers needing a
  SUBSET of a type (e.g. "only orders from one region") to subscribe
  broadly and filter client-side, instead of a hierarchical subject
  design that lets wildcard subscriptions express that filtering
  natively at the broker level.
- Configuring a JetStream stream's retention policy without considering
  actual consumer catch-up needs — a stream retaining only 1 hour of
  history won't help a newly-deployed consumer that needs to replay the
  last 24 hours to build correct state.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Core NATS — subjects, wildcards, fire-and-forget pub/sub
# ------------------------------------------------------------------
CORE_NATS_EXAMPLE = textwrap.dedent("""\
    import asyncio
    import nats

    async def publisher():
        nc = await nats.connect("nats://localhost:4222")
        await nc.publish("orders.us-east.created", b'{"order_id": "o1"}')
        await nc.close()

    async def subscriber():
        nc = await nats.connect("nats://localhost:4222")

        # "*" matches exactly ONE token — this subscribes to orders
        # created in ANY region, but NOT to e.g. "orders.us-east.updated".
        sub = await nc.subscribe("orders.*.created")
        async for msg in sub.messages:
            print(f"received: {msg.subject} -> {msg.data}")

        # ">" matches one-or-more TRAILING tokens — this subscribes to
        # EVERYTHING under "orders." regardless of depth.
        sub_all = await nc.subscribe("orders.>")

    # CRITICAL core-NATS property: if subscriber() isn't running/
    # connected WHEN publisher() sends a message, that message is
    # PERMANENTLY LOST — core NATS has no storage, no replay. This is
    # by design, not a limitation to work around within core NATS itself.
""")

# ------------------------------------------------------------------
# 2. JetStream — durable streams and consumers
# ------------------------------------------------------------------
JETSTREAM_STREAM_SETUP = textwrap.dedent("""\
    import nats
    from nats.js.api import StreamConfig, RetentionPolicy

    async def setup_stream():
        nc = await nats.connect("nats://localhost:4222")
        js = nc.jetstream()

        # A STREAM captures messages published to matching subjects and
        # PERSISTS them according to the retention policy — unlike core
        # NATS, a message published here is NOT lost if no consumer is
        # currently listening.
        await js.add_stream(StreamConfig(
            name="CUSTOMER_EVENTS",
            subjects=["stage_changed", "deposit_confirmed", "feature_change",
                      "anomaly", "external"],
            retention=RetentionPolicy.LIMITS,
            max_age=7 * 24 * 60 * 60,   # retain 7 days of history, in seconds
        ))
""")

JETSTREAM_CONSUMER_EXAMPLE = textwrap.dedent("""\
    async def consume_with_ack():
        nc = await nats.connect("nats://localhost:4222")
        js = nc.jetstream()

        # A DURABLE consumer — NATS tracks this consumer's position
        # (ack floor) across restarts; a crash before acknowledging a
        # message means that message is RE-DELIVERED on restart
        # (at-least-once delivery), unlike core NATS's fire-and-forget.
        sub = await js.pull_subscribe("deposit_confirmed", durable="trigger-evaluator")

        while True:
            msgs = await sub.fetch(batch=10, timeout=5)
            for msg in msgs:
                process_event(msg.data)
                await msg.ack()   # explicit acknowledgment advances this
                                    # consumer's tracked position

    # A NEWLY DEPLOYED consumer with the same durable name RESUMES from
    # its last acknowledged position — or, for a genuinely new consumer
    # name, can start from the BEGINNING of the stream's retained
    # history (replay), neither of which core NATS supports at all.
""")

# ------------------------------------------------------------------
# 3. Subject design — hierarchical, wildcard-friendly
# ------------------------------------------------------------------
SUBJECT_DESIGN_GUIDANCE = textwrap.dedent("""\
    GOOD subject design (hierarchical, supports targeted wildcards):
        orders.us-east.created
        orders.us-east.failed
        orders.eu-west.created

        Subscribing to "orders.us-east.*" gets ALL us-east order events
        regardless of status. Subscribing to "orders.*.failed" gets
        FAILED orders across every region. Both are natural, broker-
        level filters — no client-side filtering code needed.

    WORSE subject design (flat, forces client-side filtering):
        order_events   <- everything, undifferentiated

        Every consumer must subscribe to the ENTIRE firehose and filter
        by inspecting each message's payload themselves — the broker
        provides no help narrowing the subscription to what's actually needed.
""")


if __name__ == "__main__":
    print(CORE_NATS_EXAMPLE)
    print(JETSTREAM_STREAM_SETUP)
    print(JETSTREAM_CONSUMER_EXAMPLE)
    print(SUBJECT_DESIGN_GUIDANCE)

"""
PRODUCTION CONTEXT EXAMPLE:
A real-time trigger-evaluation platform runs a JetStream stream with 5
subjects (stage_changed, deposit_confirmed, feature_change, anomaly,
external) and a durable consumer per downstream integration (marketing
automation, fraud monitoring, analytics) — each consumer independently
tracks its own ack position, so a deployment/restart of the fraud-
monitoring consumer never causes it to miss events (JetStream redelivers
anything unacknowledged) and never affects the marketing-automation
consumer's independent position at all — the durability and isolation
core NATS's fire-and-forget model could not provide.
"""
