# =============================================================================
# WHAT: Kafka Streams, Faust (Python), and ksqlDB — Stream Processing Concepts
# WHY:  Real-time event processing is the core value of Kafka. Understanding
#       stateless vs stateful processing, windowing, joins, and when to use
#       Kafka Streams vs Flink vs Spark is required for architect-level work.
# LEVEL: Senior / Architect
# =============================================================================

# =============================================================================
# CONCEPT OVERVIEW
# =============================================================================
# Kafka is a distributed log. By itself it just stores and delivers events.
# Stream processing frameworks sit on top and let you:
#   - Transform events (stateless): filter, map, enrich
#   - Aggregate events (stateful): count, sum, join, window
#
# Two fundamental processing models:
#   1. EVENT-BY-EVENT (true streaming): each event processed as it arrives.
#      Latency: milliseconds. No batching. Used in Kafka Streams, Faust, Flink.
#   2. MICRO-BATCH: accumulate events for N seconds, process as a batch.
#      Latency: seconds. Used in Spark Structured Streaming.
#      Higher throughput but higher latency. Not true streaming.
#
# Kafka Streams is a Java library (not a separate cluster).
# Faust is the Python equivalent — same concepts, different syntax.
# ksqlDB is SQL on top of Kafka Streams — for ops teams and quick prototypes.
# =============================================================================

# =============================================================================
# PRODUCTION USE CASE
# =============================================================================
# Real-time fraud detection at a payment processor:
#   - Source: payments topic (millions of events/sec)
#   - Stateless filter: drop test/dummy transactions
#   - Stateful aggregation: count transactions per user per 1-minute window
#   - Alert: if count > 10 in 1 minute, emit to fraud-alerts topic
#   - Join: enrich alert with user profile from KTable
#   - Sink: fraud-alerts topic consumed by risk engine and notification service
# =============================================================================

# =============================================================================
# COMMON MISTAKES
# =============================================================================
# 1. Treating Kafka Streams as a separate cluster — it runs IN your app process.
# 2. Using stateful ops without understanding changelog topic overhead.
# 3. Ignoring time semantics: event time vs processing time.
#    - Event time: when event actually happened (in the event payload).
#    - Processing time: when Kafka receives/processes it.
#    - Use event time for correctness; processing time is easier but wrong.
# 4. Windowing without handling late-arriving events (grace periods).
# 5. Not sizing RocksDB (local state store) disk appropriately.
# 6. Using ksqlDB for complex business logic — it's for simple/medium queries.
# =============================================================================

import asyncio
import faust
from datetime import datetime, timedelta
from typing import AsyncIterable

# =============================================================================
# SECTION 1: FAUST APP SETUP
# =============================================================================
# Faust app = the equivalent of a Kafka Streams application.
# One app per service. The app manages:
#   - Kafka consumer/producer connections
#   - State stores (RocksDB-backed tables)
#   - Agent coroutines (stream processors)
#   - Web server for REST API and health checks

app = faust.App(
    # Unique app ID — used as consumer group ID and changelog topic prefix.
    # If you change this, you lose all existing state. Treat like a DB name.
    id='payment-stream-processor',

    # Kafka broker address.
    # In production: comma-separated list of all brokers for resilience.
    broker='kafka://localhost:9092',

    # State directory: where RocksDB stores local state.
    # Must be fast storage (SSD). Size = cardinality × value_size × 2.
    # Default: /var/faust/data — override in production.
    store='rocksdb://',

    # Topic replication factor for changelog topics.
    # Set to 3 in production. Must be <= number of brokers.
    topic_replication_factor=3,

    # How often to commit offsets. Lower = more durable, higher overhead.
    # Default 3 seconds is usually fine.
    stream_wait_empty=False,
)

# =============================================================================
# SECTION 2: TOPIC DEFINITIONS
# =============================================================================
# Define topics with explicit schema. Faust uses codecs for serialization.
# JSON is easiest for dev. Use Avro + Schema Registry in production for:
#   - Schema evolution guarantees
#   - Smaller payloads than JSON
#   - Compile-time type checking

# Faust Record = typed schema definition. Like a dataclass with serialization.
class PaymentEvent(faust.Record, serializer='json'):
    """
    Represents a single payment event from the payments topic.
    In production this would come from Schema Registry as Avro.
    """
    payment_id: str
    user_id: str
    amount: float
    currency: str
    merchant_id: str
    timestamp: float          # Unix epoch. Always use event time, not wall clock.
    status: str               # 'pending', 'completed', 'failed'
    country_code: str

class UserProfile(faust.Record, serializer='json'):
    """User profile data — typically loaded from a database CDC stream."""
    user_id: str
    email: str
    risk_tier: str            # 'low', 'medium', 'high'
    account_age_days: int
    kyc_verified: bool

class FraudAlert(faust.Record, serializer='json'):
    """Emitted when fraud pattern is detected."""
    user_id: str
    transaction_count: int
    window_start: float
    window_end: float
    risk_score: float
    triggered_rule: str

# Topic declarations with explicit partitioning.
# Partition count should match expected parallelism (number of app instances).
# Rule of thumb: partitions >= max expected consumer instances.
payments_topic = app.topic(
    'payments.billing.transaction.created',
    value_type=PaymentEvent,
    partitions=24,            # 24 partitions = up to 24 parallel processors
)

user_profiles_topic = app.topic(
    'identity.users.profile.updated',
    value_type=UserProfile,
    partitions=24,
)

fraud_alerts_topic = app.topic(
    'risk.fraud.alert.triggered',
    value_type=FraudAlert,
    partitions=24,
)

# =============================================================================
# SECTION 3: STATELESS OPERATIONS
# =============================================================================
# Stateless = no memory of past events. Each event processed independently.
# Characteristics:
#   - No state store required
#   - Horizontally scalable (any instance can handle any event)
#   - Extremely low latency (microseconds added)
#   - Examples: filter, map, flatMap, branch
#
# These are equivalent to KStream.filter(), KStream.map() in Kafka Streams Java.

def is_valid_payment(event: PaymentEvent) -> bool:
    """
    STATELESS FILTER: Drop events we don't want to process.
    No knowledge of previous events required.
    In Kafka Streams Java: stream.filter((key, value) -> value.getAmount() > 0)
    """
    return (
        event.amount > 0                    # No zero-amount transactions
        and event.status == 'completed'     # Only process completed payments
        and event.currency in {'USD', 'EUR', 'GBP'}  # Only supported currencies
    )

def enrich_with_metadata(event: PaymentEvent) -> dict:
    """
    STATELESS MAP: Transform event into enriched form.
    One input → one output. Pure function.
    In Kafka Streams Java: stream.mapValues(value -> transform(value))
    """
    return {
        'payment_id': event.payment_id,
        'user_id': event.user_id,
        'amount_usd': convert_to_usd(event.amount, event.currency),
        'hour_of_day': datetime.fromtimestamp(event.timestamp).hour,
        'is_weekend': datetime.fromtimestamp(event.timestamp).weekday() >= 5,
        'merchant_id': event.merchant_id,
        'timestamp': event.timestamp,
    }

def convert_to_usd(amount: float, currency: str) -> float:
    """Naive currency conversion. In production: call FX rate table (KTable join)."""
    rates = {'USD': 1.0, 'EUR': 1.08, 'GBP': 1.27}
    return amount * rates.get(currency, 1.0)

# =============================================================================
# SECTION 4: FAUST TABLES (STATEFUL STORAGE)
# =============================================================================
# Faust Table = KTable in Kafka Streams.
# Backed by RocksDB locally. Changes written to changelog topic in Kafka.
# On restart, replays changelog topic to rebuild state. This is state recovery.
#
# WHY changelog topics are critical:
#   - RocksDB is local to each instance (in-memory + disk)
#   - If instance dies, state would be lost
#   - Kafka Streams/Faust writes every state change to a changelog Kafka topic
#   - New instance replays the changelog to reconstruct state
#   - This is why stateful apps need enough disk for both data + changelog replay
#
# Table keys are partitioned identically to the source topic.
# This is why repartitioning (groupBy) is expensive — requires a new topic.

# Simple counter table: user_id → transaction count in current window
user_transaction_counts = app.Table(
    'user-transaction-counts',   # Changelog topic: payment-stream-processor-user-transaction-counts-changelog
    default=int,                  # Default value for new keys = 0
    partitions=24,                # Must match source topic partitions
    # help='Counts transactions per user per minute for fraud detection'
)

# Complex value table: user_id → user profile (for stream-table join)
user_profiles_table = app.Table(
    'user-profiles',
    default=lambda: None,         # Default for unknown users = None
    partitions=24,
)

# =============================================================================
# SECTION 5: WINDOWING
# =============================================================================
# Windowing groups events by time boundary for aggregations.
# Critical concept: without windowing, aggregations accumulate forever.
#
# THREE WINDOW TYPES:
#
# 1. TUMBLING WINDOW: Fixed-size, non-overlapping.
#    |--1min--|--1min--|--1min--|
#    Each event belongs to exactly ONE window.
#    Use case: "transactions per minute" — each minute counted separately.
#
# 2. HOPPING WINDOW: Fixed-size, overlapping (slides).
#    |--1min--|
#       |--1min--|
#          |--1min--|
#    Each event may belong to MULTIPLE windows.
#    Use case: "moving average over last minute, updated every 30 seconds".
#    More CPU/memory than tumbling (multiple window states per event).
#
# 3. SESSION WINDOW: Gap-based, variable size.
#    Groups events with less than N minutes between them.
#    |event--event--event|  [5min gap]  |event--event|
#    Each group = one session.
#    Use case: user activity sessions, clickstream analysis.
#    Hardest to implement: session boundaries not known until gap is detected.

# =============================================================================
# SECTION 6: STATEFUL AGENTS — FRAUD DETECTION
# =============================================================================
# Agent = async generator that consumes from a topic.
# Equivalent to KStream processor in Kafka Streams.
# One agent per partition runs on each instance. Faust assigns partitions
# automatically via consumer group protocol.

@app.agent(payments_topic)
async def detect_fraud(payments: AsyncIterable[PaymentEvent]):
    """
    STATEFUL STREAM PROCESSING: Count transactions per user per tumbling window.
    Emits fraud alert if count exceeds threshold.

    Flow:
      payments topic → filter → count per user (tumbling 1-min window) → alert

    This agent runs continuously, processing one event at a time.
    'async for event in payments' suspends when no events are available,
    allowing the event loop to do other work (non-blocking).
    """
    async for event in payments.filter(is_valid_payment):
        # WINDOWING: Use tumbling window of 60 seconds.
        # Faust windowing: table.hopping/tumbling/session
        # The window automatically segregates keys by time bucket.

        # Get current minute's bucket start time (floor to minute).
        # This is our window key — all events in same minute share same count.
        window_start = int(event.timestamp // 60) * 60
        window_key = f"{event.user_id}:{window_start}"

        # Increment count in stateful table.
        # This write goes to: RocksDB locally + changelog topic in Kafka.
        user_transaction_counts[window_key] += 1
        current_count = user_transaction_counts[window_key]

        # FRAUD RULE: More than 10 transactions in 1-minute window.
        # In production: multiple rules (velocity, amount spike, geo-anomaly).
        if current_count > 10:
            # Look up user profile for risk context (stream-table join).
            profile = user_profiles_table.get(event.user_id)
            risk_tier = profile.risk_tier if profile else 'unknown'

            # Calculate simple risk score. In production: ML model inference.
            risk_score = min(1.0, current_count / 50.0)

            # Emit alert to output topic.
            # This is a produce operation — async, non-blocking.
            alert = FraudAlert(
                user_id=event.user_id,
                transaction_count=current_count,
                window_start=float(window_start),
                window_end=float(window_start + 60),
                risk_score=risk_score,
                triggered_rule=f'velocity_check:count>{10}:tier={risk_tier}',
            )
            await fraud_alerts_topic.send(key=event.user_id, value=alert)

# =============================================================================
# SECTION 7: STREAM-TABLE JOIN
# =============================================================================
# Join a real-time stream with a materialized table.
# Stream: new events arriving continuously.
# Table: current state (last-write-wins per key). Like a slowly-changing dim.
#
# In Kafka Streams Java:
#   KStream<String, Payment> payments = builder.stream("payments");
#   KTable<String, UserProfile> profiles = builder.table("user-profiles");
#   KStream<String, EnrichedPayment> enriched = payments.join(profiles, ...)
#
# Critical requirement: stream and table must be CO-PARTITIONED.
# Same number of partitions, same partitioning scheme (same key, same partitioner).
# If not co-partitioned, you must repartition first (expensive: new topic).

@app.agent(payments_topic)
async def enrich_payments(payments: AsyncIterable[PaymentEvent]):
    """
    Stream-table join: enrich each payment event with user profile data.
    The table (user_profiles_table) is populated by a separate agent below.
    Both topics must use user_id as the key and have same partition count.
    """
    async for event in payments:
        # Table lookup by key — O(1) local RocksDB read. No network call.
        # This is why co-partitioning matters: profile must be on same instance.
        profile = user_profiles_table.get(event.user_id)

        if profile and not profile.kyc_verified:
            # Business rule: block transactions from unverified accounts > $500
            if event.amount > 500:
                # Emit to a blocked-transactions topic.
                # (omitted for brevity)
                pass

@app.agent(user_profiles_topic)
async def update_user_profiles(profiles: AsyncIterable[UserProfile]):
    """
    Populate the user_profiles KTable from CDC stream.
    This pattern: one agent writes to table, another reads from it.
    The table acts as a shared materialized view.
    """
    async for profile in profiles:
        # Upsert into local table. Written to changelog topic for durability.
        user_profiles_table[profile.user_id] = profile

# =============================================================================
# SECTION 8: KSQLDB — SQL INTERFACE TO KAFKA STREAMS
# =============================================================================
# ksqlDB lets you write SQL instead of code for stream processing.
# Runs on a separate cluster of ksqlDB servers (still uses Kafka Streams underneath).
# Good for: ops teams, quick prototyping, simple aggregations, ETL pipelines.
# Avoid for: complex business logic, ML integration, tight latency requirements.
#
# TWO QUERY TYPES:
#   PUSH QUERY (EMIT CHANGES): Continuous, real-time. Like a subscription.
#     Runs forever, emits rows as they change. For dashboards, alerts.
#   PULL QUERY: Point-in-time snapshot. Like a SELECT on a DB.
#     Returns current state immediately. For request-response patterns.

KSQLDB_EXAMPLES = """
-- ==========================================================================
-- KSQLDB SETUP: Register stream on existing Kafka topic
-- ==========================================================================
-- CREATE STREAM does NOT create a new topic — it registers a schema on an
-- existing topic so ksqlDB knows how to deserialize it.
-- WITH (KAFKA_TOPIC=...) must reference an existing topic.

CREATE STREAM payments_stream (
    payment_id VARCHAR KEY,      -- KEY = Kafka message key (used for partitioning)
    user_id    VARCHAR,
    amount     DOUBLE,
    currency   VARCHAR,
    merchant_id VARCHAR,
    status     VARCHAR,
    event_time BIGINT            -- Unix timestamp in milliseconds
) WITH (
    KAFKA_TOPIC='payments.billing.transaction.created',
    VALUE_FORMAT='AVRO',         -- Or JSON, PROTOBUF. AVRO requires Schema Registry.
    TIMESTAMP='event_time'       -- Tell ksqlDB to use event time, not ingestion time.
                                 -- Critical for correct windowed aggregations.
);

-- ==========================================================================
-- KSQLDB: CREATE TABLE (materialized view)
-- ==========================================================================
-- CREATE TABLE creates a KTable — current state per key.
-- Backed by an internal changelog topic.

CREATE TABLE user_risk_profiles (
    user_id VARCHAR PRIMARY KEY,
    risk_tier VARCHAR,
    kyc_verified BOOLEAN
) WITH (
    KAFKA_TOPIC='identity.users.profile.updated',
    VALUE_FORMAT='AVRO'
);

-- ==========================================================================
-- KSQLDB: REAL-TIME FRAUD DETECTION — TUMBLING WINDOW AGGREGATION
-- ==========================================================================
-- This is the most important ksqlDB pattern for fraud/anomaly detection.
-- WINDOW TUMBLING (SIZE 1 MINUTE): non-overlapping 1-minute windows.
-- EMIT CHANGES: push query — runs forever, emits new results as windows close.
-- HAVING COUNT(*) > 10: threshold filter applied to aggregated result.
--
-- HOW IT WORKS INTERNALLY:
--   1. ksqlDB buffers events by user_id within each 1-minute window.
--   2. At window close (or as events arrive), evaluates HAVING clause.
--   3. Emits row to output whenever count crosses threshold.
--   4. Results written to a new internal Kafka topic automatically.

CREATE TABLE fraud_velocity_alerts AS
    SELECT
        user_id,
        COUNT(*)                           AS transaction_count,
        SUM(amount)                        AS total_amount,
        WINDOWSTART                        AS window_start_ms,
        WINDOWEND                          AS window_end_ms,
        LATEST_BY_OFFSET(merchant_id)      AS last_merchant
    FROM payments_stream
    WHERE status = 'completed'
    WINDOW TUMBLING (
        SIZE 1 MINUTE,
        GRACE PERIOD 10 SECONDS           -- Accept late events up to 10s after window closes.
                                          -- Without grace period, late events are dropped.
    )
    GROUP BY user_id
    HAVING COUNT(*) > 10                  -- Fraud threshold: >10 txns/min
    EMIT CHANGES;                         -- Push query: continuous output stream.

-- ==========================================================================
-- KSQLDB: STREAM-TABLE JOIN (enrich stream with lookup data)
-- ==========================================================================
-- Join the real-time payment stream with the user risk profiles table.
-- Each payment is enriched with the user's current risk tier.
-- Table side is the "right" side — looked up per event.

CREATE STREAM enriched_payments AS
    SELECT
        p.payment_id,
        p.user_id,
        p.amount,
        p.currency,
        u.risk_tier,
        u.kyc_verified
    FROM payments_stream p
    LEFT JOIN user_risk_profiles u ON p.user_id = u.user_id
    EMIT CHANGES;

-- ==========================================================================
-- KSQLDB: HOPPING WINDOW — Moving 5-minute average, updated every 1 minute
-- ==========================================================================
-- HOPPING: window SIZE > ADVANCE BY → overlapping windows.
-- Each event counted in multiple windows.
-- Result: "average transaction amount over last 5 minutes" updated every minute.

SELECT
    user_id,
    AVG(amount)    AS avg_amount_5min,
    COUNT(*)       AS txn_count_5min,
    WINDOWSTART    AS window_start
FROM payments_stream
WINDOW HOPPING (
    SIZE 5 MINUTES,
    ADVANCE BY 1 MINUTE
)
GROUP BY user_id
EMIT CHANGES;

-- ==========================================================================
-- KSQLDB: PULL QUERY — point-in-time state lookup
-- ==========================================================================
-- Unlike push queries (EMIT CHANGES), pull queries return immediately.
-- Used in request-response patterns (e.g., API checks user's fraud status).
-- Only works on materialized tables (not streams).

SELECT user_id, transaction_count, window_start_ms
FROM fraud_velocity_alerts
WHERE user_id = 'user-12345';
"""

# =============================================================================
# SECTION 9: WHEN TO USE WHAT — FRAMEWORK COMPARISON
# =============================================================================
FRAMEWORK_COMPARISON = """
FRAMEWORK SELECTION GUIDE (commit this to memory):

┌─────────────────────┬──────────────────┬────────────────────┬──────────────────────┐
│ Criterion           │ Kafka Streams/   │ Spark Structured   │ Apache Flink         │
│                     │ Faust            │ Streaming          │                      │
├─────────────────────┼──────────────────┼────────────────────┼──────────────────────┤
│ Processing model    │ True streaming   │ Micro-batch        │ True streaming       │
│ Latency             │ Milliseconds     │ Seconds            │ Milliseconds         │
│ Separate cluster    │ NO (runs in app) │ YES (Spark cluster)│ YES (Flink cluster)  │
│ Operational cost    │ Low              │ High               │ High                 │
│ Exactly-once        │ Yes              │ Yes                │ Yes (best support)   │
│ Complex state       │ Medium           │ Medium             │ Excellent            │
│ Event time handling │ Good             │ Good               │ Excellent            │
│ SQL support         │ ksqlDB           │ Spark SQL          │ Flink SQL            │
│ ML integration      │ Limited          │ MLlib / Spark ML   │ Limited              │
│ Best for            │ Microservice     │ Large-scale ETL,   │ Complex event        │
│                     │ stream processing│ existing Spark     │ processing, CEP,     │
│                     │ Low latency APIs │ infrastructure     │ high-throughput      │
├─────────────────────┼──────────────────┼────────────────────┼──────────────────────┤
│ Choose when         │ • Your app IS    │ • Already on Spark │ • Need best-in-class │
│                     │   the processor  │ • Batch + stream   │   exactly-once       │
│                     │ • < 10k events/s │   same codebase    │ • Complex windowing  │
│                     │ • No infra budget│ • > 100k events/s  │ • Event-time         │
│                     │ • Python service │   with ML          │   processing         │
└─────────────────────┴──────────────────┴────────────────────┴──────────────────────┘

RULE OF THUMB:
  - Building a microservice that processes Kafka events? → Faust (Python) / Kafka Streams (Java)
  - Need SQL interface for ops team? → ksqlDB
  - Massive scale + existing Spark? → Spark Structured Streaming
  - Complex stateful processing, highest correctness guarantees? → Flink
"""

# =============================================================================
# SECTION 10: RUNNING THE FAUST APP
# =============================================================================
# Start command: python L07_kafka_streams_and_ksql.py worker -l info
#
# Faust worker starts:
#   1. Connects to Kafka as consumer group member
#   2. Gets partition assignment via group protocol
#   3. Opens RocksDB for each assigned partition's state
#   4. Starts agent coroutines for assigned partitions
#   5. Starts internal web server (default port 6066) for monitoring
#
# Scaling: run multiple workers. Faust rebalances partitions automatically.
# Max parallelism = number of partitions (one consumer per partition max).

if __name__ == '__main__':
    app.main()
