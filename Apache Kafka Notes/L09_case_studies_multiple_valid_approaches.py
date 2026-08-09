"""
WHAT: Four realistic event-streaming problems, each solved with THREE
      genuinely different, individually defensible approaches drawn from
      L01-L08 -- with an explicit comparison table and reasoning for why
      each answer is valid under different constraints.
WHY:  "How should this be partitioned/how should this consumer group be
      structured" is usually malformed without knowing the actual
      ordering requirements, throughput, and failure-tolerance needs --
      L01-L08 gave you the primitives; this lesson is about choosing
      between them under real constraints.
LEVEL: Capstone -- read after L01-L08.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L08's concepts.
"""

# ============================================================================
# CASE STUDY 1 — PARTITIONING STRATEGY FOR AN ORDER-EVENTS TOPIC (NEEDS
# PER-CUSTOMER ORDERING, HIGH THROUGHPUT, 500+ PARTITIONS EVENTUALLY)
# ============================================================================
#
# SETUP: an `order-events` topic carries create/update/cancel events per
# order; the business requires all events for a given CUSTOMER to be
# processed in the order they occurred, while the topic overall needs to
# scale to very high throughput.
#
# ------------------------------------------------------------------------
# APPROACH A: Key by `order_id` (L04)
# ------------------------------------------------------------------------
#   WHY VALID: per L04, keying determines partition assignment, and
#   Kafka guarantees ordering WITHIN a partition -- keying by order_id
#   guarantees all events for the SAME order land on the same partition,
#   processed in order, which is a natural, low-friction choice since
#   each event naturally carries its own order_id.
#   COST: does NOT satisfy the actual stated requirement -- a customer
#   with MULTIPLE orders can have their orders' events land on DIFFERENT
#   partitions (different order_ids hash differently), and consumers
#   processing different partitions in parallel offer NO guarantee about
#   the relative ordering of two different orders' events, even from the
#   SAME customer -- this key choice solves a different, narrower
#   ordering problem than the one stated.
#
# ------------------------------------------------------------------------
# APPROACH B: Key by `customer_id` (L04)
# ------------------------------------------------------------------------
#   WHY VALID: directly satisfies the stated requirement -- per L04's
#   partitioning discussion, keying by customer_id guarantees ALL of a
#   given customer's order events land on the same partition, hence
#   process in the order they were produced, exactly the correctness
#   property the business asked for.
#   COST: creates a real SKEW risk -- if some customers place vastly
#   more orders than others (a common, realistic distribution), their
#   partition receives disproportionately more traffic than others,
#   potentially creating a "hot partition" that limits the effective
#   parallelism the topic's overall partition count would otherwise
#   provide, directly relevant to this case study's stated "500+
#   partitions eventually" throughput goal.
#
# ------------------------------------------------------------------------
# APPROACH C: Key by `customer_id`, but pre-aggregate/batch a heavy
# customer's events at the PRODUCER before publishing, or apply a
# separate high-volume-customer sharding scheme (e.g. append a bucket
# suffix to the key for known high-volume accounts specifically)
# ------------------------------------------------------------------------
#   WHY VALID: preserves B's correctness guarantee for the vast majority
#   of (normal-volume) customers while specifically mitigating the skew
#   risk for the small number of KNOWN high-volume outliers -- a targeted
#   fix for the specific problem B has, rather than abandoning B's
#   correctness property wholesale.
#   COST: genuinely more complex to implement and reason about --
#   requires identifying which customers are "high volume" (a moving
#   target requiring monitoring/re-evaluation over time) and a bucketing
#   scheme that STILL preserves ordering WITHIN each bucket, which is a
#   nontrivial correctness property to maintain correctly as the
#   business's usage patterns evolve.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Satisfies per-customer ordering? | Skew risk | Implementation complexity |
#   |----------|--------------------------------------|---------------|---------------------------------|
#   | A: key by order_id | No | Low | Lowest |
#   | B: key by customer_id | Yes | Real, for high-volume customers | Low |
#   | C: customer_id + high-volume sharding | Yes | Mitigated | Highest |
#   B is the correct default answer given the stated requirement; C is
#   the right escalation specifically once skew from a known set of
#   high-volume customers is MEASURED to actually be a throughput
#   problem, not applied preemptively before that's confirmed.


# ============================================================================
# CASE STUDY 2 — CONSUMER GROUP DESIGN FOR A NOTIFICATION SERVICE (MUST
# NEVER DOUBLE-SEND, MUST NOT DROP NOTIFICATIONS ON CONSUMER CRASH)
# ============================================================================
#
# SETUP: a service consumes `user-events` and sends push notifications;
# double-sending a notification is a visible user-facing bug, and
# dropping one silently loses a real business event.
#
# ------------------------------------------------------------------------
# APPROACH A: Auto-commit offsets (`enable.auto.commit=true`), default
# consumer group behavior (L03)
# ------------------------------------------------------------------------
#   WHY VALID: simplest possible consumer code -- no manual offset
#   management, Kafka periodically commits progress automatically, fine
#   for a LOW-STAKES consumer where an occasional duplicate or dropped
#   message is an acceptable, non-critical cost.
#   COST: per L03/L05, auto-commit can commit an offset for a message
#   the consumer hasn't actually FINISHED processing yet (if a commit
#   happens to fire between receiving and fully processing a batch) --
#   a crash in that window means the message is never reprocessed
#   (silently dropped), directly violating this case study's "must not
#   drop" requirement; auto-commit can also cause reprocessing
#   (duplicates) after a rebalance, violating "must never double-send."
#
# ------------------------------------------------------------------------
# APPROACH B: Manual offset commits AFTER successful processing, PLUS
# an idempotent "already sent?" check against a dedup store (e.g. Redis)
# keyed by notification ID before actually sending (L03, L05)
# ------------------------------------------------------------------------
#   WHY VALID: manual commit-after-processing directly fixes A's
#   silent-drop risk (a crash before commit means the message WILL be
#   reprocessed on restart, per L05's at-least-once semantics) -- and
#   the idempotency check specifically handles the resulting DUPLICATE
#   delivery (Kafka's at-least-once guarantee means reprocessing after a
#   crash-before-commit is EXPECTED, not a bug) by ensuring a
#   reprocessed message doesn't cause a second real-world side effect
#   (an actual duplicate push notification).
#   COST: the dedup store is now a SEPARATE point of failure and
#   consistency concern -- if the dedup check succeeds but the ACTUAL
#   send fails (or vice versa, non-atomically), you can still get a
#   drop or duplicate at the boundary between "check dedup" and "send
#   notification," a real, narrower race window that needs its own
#   careful handling (e.g. marking dedup state only AFTER confirmed send).
#
# ------------------------------------------------------------------------
# APPROACH C: A transactional/exactly-once consumer-producer chain
# (Kafka transactions, L05) where the notification service both
# consumes AND produces a "notification-sent" record atomically
# ------------------------------------------------------------------------
#   WHY VALID: per L05, Kafka's transactional API can atomically commit
#   BOTH the consumer offset AND any produced output (here, a durable
#   "notification-sent" audit record) as a single unit -- the strongest
#   built-in guarantee Kafka itself offers, avoiding B's separate-dedup-
#   store consistency gap entirely, since offset advancement and the
#   "did we actually do this" record are transactionally linked.
#   COST: exactly-once semantics apply to KAFKA-TO-KAFKA data flow --
#   the actual EXTERNAL side effect (sending a push notification via a
#   third-party push service) is OUTSIDE Kafka's transactional boundary
#   entirely; this approach guarantees the notification-sent RECORD is
#   exactly-once, but the actual push-notification API call itself still
#   needs its own idempotency handling (often still requiring something
#   like B's dedup check at the actual external call site) -- exactly-
#   once Kafka semantics don't automatically extend to non-Kafka side
#   effects.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Drop risk | Duplicate risk | Complexity | Solves the EXTERNAL side-effect problem? |
#   |----------|---------------|---------------------|----------------|------------------------------------------------|
#   | A: auto-commit | Real | Real | Lowest | No |
#   | B: manual commit + dedup store | Low (small race window) | Low (small race window) | Medium | Partially (needs careful ordering) |
#   | C: Kafka transactions | None (for the Kafka record) | None (for the Kafka record) | Highest | No (external call still needs its own idempotency) |
#   The honest conclusion: NONE of the three alone fully solves "never
#   double-send a real push notification" -- that requires idempotency
#   at the ACTUAL external send call regardless of which Kafka-level
#   approach is used; B or C reduce the Kafka-side risk substantially,
#   but the external-API idempotency work is still required either way.


# ============================================================================
# CASE STUDY 3 — SCHEMA EVOLUTION FOR A LONG-LIVED, WIDELY-CONSUMED TOPIC
# ============================================================================
#
# SETUP: a `user-profile-updated` topic is consumed by a dozen different
# teams' services; a new field needs to be added, and some older
# consumers won't be updated to handle it immediately.
#
# ------------------------------------------------------------------------
# APPROACH A: Add the new field as OPTIONAL, with a sensible default,
# using Avro + Schema Registry with BACKWARD compatibility mode (L06)
# ------------------------------------------------------------------------
#   WHY VALID: per L06, BACKWARD compatibility means new messages
#   (with the new field) can still be read by consumers using the OLD
#   schema (they simply ignore the unknown field) -- old, unupdated
#   consumers keep working with zero changes required on their end,
#   directly addressing this case study's "some consumers won't be
#   updated immediately" constraint.
#   COST: "backward compatible" specifically protects OLD consumers
#   reading NEW data -- it does NOT, by itself, guarantee anything about
#   NEW consumers reading OLD (pre-change) historical data still sitting
#   in the topic if retention is long, which may separately need
#   FORWARD or FULL compatibility mode depending on whether new
#   consumers must also correctly process old, field-less messages.
#
# ------------------------------------------------------------------------
# APPROACH B: Publish the new field on an entirely NEW topic
# (`user-profile-updated-v2`), let both topics run in parallel, migrate
# consumers over time
# ------------------------------------------------------------------------
#   WHY VALID: completely sidesteps schema-compatibility-mode subtleties
#   -- no consumer is ever surprised by a schema it wasn't explicitly
#   built to handle, since each topic has one stable schema throughout
#   its life; genuinely the safest option when the change is large
#   enough that "just add an optional field" doesn't cleanly capture the
#   actual semantic change being made.
#   COST: every one of the dozen consuming teams must actively migrate
#   to the new topic on their own schedule -- a real, ongoing
#   coordination burden across many teams, and running two topics in
#   parallel (with related, overlapping data) creates its own
#   consistency/duplication-of-effort questions during the transition
#   period, likely for a nontrivial span of time given a dozen
#   independent teams' differing migration timelines.
#
# ------------------------------------------------------------------------
# APPROACH C: A' -- add the field as optional (as in A) but ALSO
# proactively notify all consuming teams and set an internal deadline
# after which schema compatibility mode is tightened to FULL, forcing
# eventual explicit acknowledgment
# ------------------------------------------------------------------------
#   WHY VALID: gets A's low-friction immediate rollout while avoiding
#   the RISK that "backward compatible, so no one needs to do anything"
#   quietly becomes "no one ever actually updates their consumer to
#   properly USE or even acknowledge the new field," which can leave a
#   schema evolving indefinitely without any consuming team's explicit
#   sign-off -- a real, common organizational failure mode pure schema-
#   registry technical compatibility doesn't prevent by itself.
#   COST: requires genuine ORGANIZATIONAL process (tracking which teams
#   have acknowledged/migrated, enforcing a deadline) on top of the
#   purely technical schema-registry mechanism -- a real coordination
#   cost, though a smaller one than B's full topic-migration burden.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Immediate consumer disruption | Coordination burden | Risk of indefinite schema drift |
#   |----------|------------------------------------|---------------------------|---------------------------------------|
#   | A: optional field, BACKWARD mode | None | Low | Real (no forcing function) |
#   | B: new parallel topic | None (until migration) | Highest (full migration per team) | Low (each topic stays simple) |
#   | C: A + tracked deadline | None | Medium | Mitigated |
#   For most additive, genuinely optional changes, A (or C, for
#   important fields that need eventual universal adoption) is the
#   standard, low-friction answer; B is reserved for changes substantial
#   enough that "optional field" doesn't honestly describe the actual
#   semantic shift being made.


# ============================================================================
# CASE STUDY 4 — KAFKA VS. AN ALTERNATIVE FOR A MODERATE-THROUGHPUT,
# LATENCY-SENSITIVE INTERNAL EVENT BUS
# ============================================================================
#
# SETUP: a new internal service needs to publish/subscribe to events at
# a few thousand messages/second, with sub-10ms delivery latency
# preferred, and the team has no existing Kafka operational experience.
#
# ------------------------------------------------------------------------
# APPROACH A: Deploy Kafka (L01, L08) for this new use case
# ------------------------------------------------------------------------
#   WHY VALID: if the organization ALREADY runs Kafka at scale elsewhere
#   (shared operational expertise, existing monitoring/tooling, L08),
#   adding one more topic to an already-operated cluster has a much
#   lower MARGINAL cost than this case study's "no existing experience"
#   framing suggests in isolation -- reuse of existing infrastructure is
#   a real, common justification even when a lighter-weight tool would
#   suffice in a vacuum.
#   COST: taken at face value (genuinely NO existing Kafka experience,
#   per this case study's stated setup), standing up and operating a new
#   Kafka cluster (ZooKeeper/KRaft, broker sizing, partition/replication
#   tuning, L08) is substantial operational overhead for a moderate-
#   throughput use case that may not need Kafka's durability/scale
#   guarantees at all.
#
# ------------------------------------------------------------------------
# APPROACH B: NATS JetStream (Event-Driven & Real-Time AI Systems Notes)
# ------------------------------------------------------------------------
#   WHY VALID: per Event-Driven & Real-Time AI Systems Notes L03's
#   direct NATS-vs-Kafka framework, NATS offers dramatically lower
#   operational overhead (a single lightweight binary, minimal
#   configuration) and lower typical latency than Kafka for moderate
#   throughput -- a strong match for this case study's stated latency
#   preference and lack of existing operational investment in Kafka
#   specifically.
#   COST: per that same comparison, NATS JetStream has a genuinely lower
#   PROVEN throughput ceiling than Kafka at extreme scale, and a smaller
#   surrounding ecosystem (fewer third-party connectors, less
#   battle-tested tooling for very large deployments) -- a real risk if
#   this "moderate throughput" use case is likely to grow substantially
#   beyond its current few-thousand-messages/second scale.
#
# ------------------------------------------------------------------------
# APPROACH C: A managed Kafka service (e.g. Confluent Cloud, AWS MSK)
# rather than self-hosting either Kafka or NATS
# ------------------------------------------------------------------------
#   WHY VALID: gets Kafka's ecosystem, durability guarantees, and long-
#   term throughput headroom WITHOUT this case study's stated "no
#   existing Kafka operational experience" cost being a blocker at all --
#   the managed provider absorbs cluster operations, letting the team
#   use Kafka's client APIs/semantics without needing to build that
#   operational expertise from scratch immediately.
#   COST: real, ongoing MONETARY cost that scales with usage in a way
#   self-hosted infrastructure (sunk hardware/ops cost) doesn't
#   necessarily track the same way -- and the team still needs to learn
#   Kafka's CLIENT-side concepts (partitioning, consumer groups,
#   offsets) even if cluster operations are outsourced, so this doesn't
#   eliminate all the learning-curve cost, only the operational-
#   infrastructure portion of it.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Operational overhead | Latency fit | Long-term scale headroom | Cost model |
#   |----------|---------------------------|-----------------|--------------------------------|----------------|
#   | A: self-hosted Kafka | Highest (new to the team) | Good | Highest | Infrastructure/ops cost |
#   | B: NATS JetStream | Lowest | Best | Lower ceiling | Infrastructure/ops cost (lighter) |
#   | C: managed Kafka | Medium (client-side learning only) | Good | Highest | Ongoing service cost |
#   Given this case study's SPECIFIC stated constraints (moderate
#   throughput, latency-sensitive, no existing Kafka experience), B is
#   the strongest default per Event-Driven & Real-Time AI Systems Notes'
#   own decision framework; A only wins if there's a concrete, near-term
#   expectation of outgrowing NATS's throughput ceiling that justifies
#   paying the operational-learning cost now rather than later.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
