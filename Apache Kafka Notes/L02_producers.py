# ============================================================
# L02: Kafka Producers — Durability, Throughput & Exactly-Once
# ============================================================
# WHAT: A Kafka producer is a client that publishes records to topics.
#       The producer library handles batching, compression, retries,
#       partitioning, and delivery guarantees internally.
#       confluent-kafka-python is the official Confluent Python client,
#       wrapping the high-performance librdkafka C library.
#
# WHY:  Producer configuration is where you make the fundamental tradeoff
#       between throughput, latency, and durability. Getting this wrong
#       means either data loss or terrible performance.
#
# LEVEL: Foundations → Advanced
# ============================================================
# CONCEPT OVERVIEW:
#
#   RECORD LIFECYCLE:
#   1. Producer.produce() → record enters in-memory batch buffer
#   2. Batch accumulates until linger.ms OR batch.size reached
#   3. Batch compressed and sent to leader broker
#   4. Broker writes to its log and replicates to followers
#   5. Broker sends ack back to producer (based on acks setting)
#   6. Delivery callback fires (success or error)
#
#   ACKS SETTING (the most critical producer config):
#   acks=0  : Fire-and-forget. No ack waited for. Highest throughput,
#             but messages can be lost if broker crashes. Use only for
#             metrics/logs where loss is acceptable.
#   acks=1  : Leader ack only. Message written to leader's log. Leader
#             crash before follower replication = data loss. Good default.
#   acks=all: All ISR replicas must acknowledge. Zero data loss (with
#             min.insync.replicas). Lowest throughput. Use for financial
#             data, orders, payments.
#
# PRODUCTION USE CASE:
#   Stripe: payment events with acks=all, enable.idempotence=True,
#           transactions for exactly-once. Kafka throughput: 10M events/sec
#           with batching + compression.
#
# COMMON MISTAKES:
#   1. Not calling poll() or flush() — callbacks never fire, queue fills up.
#   2. acks=1 with no idempotence — producer retries can cause duplicates.
#   3. Not handling delivery errors in callback — silent data loss.
#   4. Setting linger.ms=0 — disables batching, terrible throughput.
#   5. Synchronous sends in a loop — 100x slower than async.
# ============================================================

from confluent_kafka import Producer, KafkaError, KafkaException
import json
import time
import uuid
from typing import Optional, Callable

# ============================================================
# SECTION 1: Producer Configuration Reference
# ============================================================
# Every config has a tradeoff. Understand the tradeoff, then choose.

PRODUCER_CONFIG_REFERENCE = {
    # --- Connection ---
    "bootstrap.servers": "localhost:9092",  # Comma-separated broker list.
                                             # Only needs 2-3 for discovery;
                                             # client learns full cluster.

    # --- Durability: THE MOST IMPORTANT CONFIG ---
    # acks=0: no ack (fire-and-forget, max throughput, data loss possible)
    # acks=1: leader ack only (default, balanced)
    # acks=-1 or 'all': all ISR acks (zero loss, slowest)
    "acks": "all",

    # --- Batching: controls throughput vs latency ---
    # linger.ms: wait up to N ms to accumulate a batch before sending.
    # 0 = send immediately (low latency, low throughput)
    # 5 = wait 5ms to batch records together (higher throughput)
    # 100 = aggressive batching, higher latency, best throughput
    "linger.ms": 5,

    # batch.size: max bytes per batch per partition.
    # 16384 = 16KB default. Increase to 1MB for high-throughput producers.
    "batch.size": 1048576,  # 1 MB

    # --- Compression: always use in production ---
    # 'none': no compression (default) — wastes network/disk
    # 'gzip': good ratio, high CPU — avoid in latency-sensitive paths
    # 'snappy': balanced CPU/ratio — general purpose
    # 'lz4': low CPU, lower ratio — best for high-throughput producers
    # 'zstd': best ratio, moderate CPU — use for cold storage topics
    "compression.type": "lz4",

    # --- Retries and reliability ---
    # retries: retry failed sends (network issues, leader election, etc.)
    "retries": 2147483647,  # Effectively infinite — let delivery.timeout handle it

    # delivery.timeout.ms: total time from produce() to ack/failure.
    # Must be >= request.timeout.ms + linger.ms
    "delivery.timeout.ms": 120000,  # 2 minutes

    # request.timeout.ms: timeout for a single broker request
    "request.timeout.ms": 30000,  # 30 seconds

    # --- Ordering under retries ---
    # max.in.flight.requests.per.connection: concurrent unacked requests.
    # If retries > 0 AND this > 1, retried batch can overtake a later batch
    # causing out-of-order delivery.
    # Solution: set to 1 (but hurts throughput) OR use enable.idempotence.
    "max.in.flight.requests.per.connection": 5,  # Safe with idempotence=True

    # --- Idempotence: prevents duplicates on retry ---
    # When True: producer gets a unique ID (PID) and sequence numbers.
    # Broker deduplicates retries. Requires acks=all, retries>0, inflight<=5.
    "enable.idempotence": True,

    # --- Buffer ---
    # queue.buffering.max.messages: max records in send buffer
    "queue.buffering.max.messages": 1000000,

    # queue.buffering.max.kbytes: max bytes in send buffer (default 1GB)
    "queue.buffering.max.kbytes": 1048576,  # 1 GB

    # --- Message size ---
    # message.max.bytes: max single message size (must match broker config)
    "message.max.bytes": 1048576,  # 1 MB; broker default is also 1MB
}


# ============================================================
# SECTION 2: Basic Async Producer (production standard)
# ============================================================
# Async is the RIGHT way to use Kafka producers.
# Call produce() → it buffers the record → returns immediately.
# poll() triggers callbacks for completed sends.

def create_producer(config: dict) -> Producer:
    """
    Factory function for creating a configured Kafka producer.
    Centralise producer creation so config changes propagate everywhere.
    """
    return Producer(config)


def delivery_callback(err: Optional[KafkaError], msg) -> None:
    """
    Delivery callback — fires for EVERY message after ack or failure.
    This is the ONLY reliable way to know if a message was delivered.

    IMPORTANT: This runs in the producer's internal thread during poll().
    Keep it fast — no blocking I/O, no heavy computation.
    Log errors to a structured logger; emit metrics to Prometheus.
    """
    if err is not None:
        # Delivery failed — what to do here depends on your SLA:
        # Option A: Log + send to DLQ (dead letter queue)
        # Option B: Raise exception (will crash the producer loop)
        # Option C: Increment error counter + alert
        print(f"[DELIVERY FAILED] topic={msg.topic()} "
              f"partition={msg.partition()} "
              f"offset={msg.offset()} "
              f"error={err.str()} "
              f"retriable={err.retriable()}")
    else:
        # Delivery confirmed — message is durably stored in Kafka.
        # msg.offset() is the actual offset assigned by the broker.
        print(f"[DELIVERED] topic={msg.topic()} "
              f"partition={msg.partition()} "
              f"offset={msg.offset()} "
              f"latency={msg.latency():.3f}s")


def produce_async(producer: Producer, topic: str, key: str, value: dict) -> None:
    """
    Non-blocking produce. Returns immediately after buffering.
    poll(0) processes any pending callbacks without blocking.
    """
    try:
        producer.produce(
            topic=topic,
            key=key.encode("utf-8"),            # Keys are bytes
            value=json.dumps(value).encode("utf-8"),  # Values are bytes
            callback=delivery_callback,          # Called after ack/fail
        )
        # poll(0) = non-blocking callback drain.
        # Call after every produce() or in a batch loop.
        # Without this, callbacks queue up forever.
        producer.poll(0)
    except BufferError:
        # Internal queue is full (queue.buffering.max.messages exceeded).
        # This means we're producing faster than the broker can consume.
        # Strategy: wait for queue to drain, then retry.
        print("[BACKPRESSURE] Internal queue full — waiting for drain...")
        producer.poll(1)   # Wait up to 1s for callbacks to drain buffer
        # Retry after drain
        producer.produce(
            topic=topic,
            key=key.encode("utf-8"),
            value=json.dumps(value).encode("utf-8"),
            callback=delivery_callback,
        )


# ============================================================
# SECTION 3: Synchronous Producer (for debugging, not production)
# ============================================================
# Synchronous = produce() then immediately flush() before continuing.
# This gives you immediate feedback but kills throughput.
# Use synchronous sends ONLY when you need guaranteed ordering
# confirmation per-message, e.g. in DB write-ahead log replication.

def produce_sync(producer: Producer, topic: str, key: str, value: dict) -> None:
    """
    Synchronous send: blocks until broker acknowledges.
    ~10x-100x slower than async. Use only when you must confirm
    each individual message before proceeding.
    """
    producer.produce(
        topic=topic,
        key=key.encode("utf-8"),
        value=json.dumps(value).encode("utf-8"),
        callback=delivery_callback,
    )
    # flush() blocks until ALL buffered messages are delivered or fail.
    # timeout=-1 means wait forever; use a reasonable timeout in production.
    remaining = producer.flush(timeout=10)
    if remaining > 0:
        raise RuntimeError(f"Failed to deliver {remaining} messages within timeout")


# ============================================================
# SECTION 4: Partitioning Strategies
# ============================================================
# Partitioning determines WHERE (which partition) a record goes.
# This controls: ordering, load distribution, and consumer assignment.

# --- Strategy 1: Round-Robin (no key) ---
# Records without a key are distributed round-robin across partitions.
# Best for: metrics, logs where ordering doesn't matter.
# Downside: related events may land in different partitions (no ordering).
def produce_round_robin(producer: Producer, topic: str, value: dict) -> None:
    producer.produce(
        topic=topic,
        key=None,                               # No key = round-robin
        value=json.dumps(value).encode("utf-8"),
        callback=delivery_callback,
    )
    producer.poll(0)


# --- Strategy 2: Key-Based Partitioning (most common in production) ---
# hash(key) % num_partitions → deterministic partition assignment.
# All records with the SAME key go to the SAME partition.
# Guarantees ordering for that key (e.g., all events for user_123).
# Best for: user activity, order state machines, device telemetry.
def produce_keyed(producer: Producer, topic: str, user_id: str, event: dict) -> None:
    producer.produce(
        topic=topic,
        key=user_id.encode("utf-8"),            # All user_id events → same partition
        value=json.dumps(event).encode("utf-8"),
        callback=delivery_callback,
    )
    producer.poll(0)


# --- Strategy 3: Explicit Partition (advanced, use rarely) ---
# Force a specific partition. Useful for testing, admin tasks.
# Bypasses the partitioner — you take full responsibility for distribution.
def produce_to_partition(producer: Producer, topic: str,
                          partition: int, value: dict) -> None:
    producer.produce(
        topic=topic,
        partition=partition,                    # Explicit partition number
        value=json.dumps(value).encode("utf-8"),
        callback=delivery_callback,
    )
    producer.poll(0)


# --- Strategy 4: Custom Partitioner ---
# For advanced routing: VIP users to dedicated partitions, geo-routing, etc.
def custom_partitioner(key: bytes, num_partitions: int) -> int:
    """
    Example: route 'premium' users to partition 0 (dedicated fast consumer),
    all others spread across remaining partitions.
    Implements the partitioner callable expected by confluent-kafka.
    """
    if key and key.startswith(b"premium_"):
        return 0   # Dedicated high-priority partition
    # Consistent hash for other keys
    return (hash(key) & 0x7FFFFFFF) % (num_partitions - 1) + 1


# ============================================================
# SECTION 5: Idempotent Producer — Prevents Duplicate Records
# ============================================================
# Problem: Producer sends a batch → network timeout → producer retries →
#          broker already wrote it → now you have DUPLICATES.
#
# Solution: enable.idempotence=True
#   - Broker assigns producer a PID (Producer ID)
#   - Each record gets a monotonic sequence number
#   - Broker rejects duplicate sequence numbers from same PID
#   - Result: exactly-once at the producer level (per partition)
#
# Requirements: acks=all, retries>0, max.in.flight<=5
# Cost: minimal — just sequence number tracking overhead

IDEMPOTENT_PRODUCER_CONFIG = {
    "bootstrap.servers": "localhost:9092",
    "enable.idempotence": True,          # Enables sequence numbers + dedup
    "acks": "all",                        # Required for idempotence
    "retries": 2147483647,               # Required for idempotence
    "max.in.flight.requests.per.connection": 5,  # Max allowed with idempotence
    "linger.ms": 5,
    "batch.size": 1048576,
    "compression.type": "lz4",
}


# ============================================================
# SECTION 6: Transactional Producer — Exactly-Once Semantics
# ============================================================
# Idempotence prevents duplicate records per partition.
# Transactions extend this across MULTIPLE partitions and topics.
# Use when: writing to multiple topics atomically, or combining
#           Kafka consumer + producer (consume-transform-produce).
#
# Exactly-once semantics (EOS):
#   1. Producer begins a transaction
#   2. Produces records to multiple topics/partitions
#   3. Commits the transaction atomically
#   4. On failure: aborts — consumers with read_committed never see aborted records
#
# Use case: stream processing — read from input topic, transform,
#           write to output topic, commit offsets — all atomically.

TRANSACTIONAL_PRODUCER_CONFIG = {
    "bootstrap.servers": "localhost:9092",
    "enable.idempotence": True,           # Required for transactions
    "acks": "all",                         # Required for transactions
    "retries": 2147483647,
    "max.in.flight.requests.per.connection": 5,
    # transactional.id: unique string per producer instance.
    # If two producers have the same ID, the older one is fenced.
    # Use a stable ID (not random) so recovery works after crash.
    "transactional.id": "payment-processor-v1",
    "transaction.timeout.ms": 60000,       # Abort if not committed in 60s
}


def transactional_produce_example():
    """
    Atomic produce across two topics.
    Either BOTH writes succeed or NEITHER is visible to consumers.
    This is the foundation of stream processing correctness.
    """
    producer = Producer(TRANSACTIONAL_PRODUCER_CONFIG)

    # MUST call init_transactions() once before any transactions.
    # This registers the transactional.id with the broker's transaction
    # coordinator and fences any previous zombie producers with the same ID.
    producer.init_transactions()

    try:
        # Step 1: Begin atomic transaction
        producer.begin_transaction()

        # Step 2: Produce to multiple topics — both are part of same transaction
        order_event = {"order_id": "ord_123", "status": "confirmed", "amount": 99.99}
        audit_event = {"order_id": "ord_123", "action": "order_confirmed", "ts": time.time()}

        producer.produce(
            topic="order-state",
            key=b"ord_123",
            value=json.dumps(order_event).encode("utf-8"),
        )
        producer.produce(
            topic="audit-log",
            key=b"ord_123",
            value=json.dumps(audit_event).encode("utf-8"),
        )

        # Step 3: Commit — both writes become visible to read_committed consumers
        producer.commit_transaction()
        print("Transaction committed — both records visible atomically")

    except KafkaException as e:
        # Step 3 (failure path): Abort — broker discards both records.
        # Consumers with isolation.level=read_committed never see aborted records.
        print(f"Transaction failed: {e} — aborting")
        producer.abort_transaction()
    finally:
        # flush() ensures all in-flight requests complete before exit
        producer.flush(timeout=30)


# ============================================================
# SECTION 7: High-Throughput Producer Loop
# ============================================================
# Production pattern for sustained high-throughput ingestion.
# Target: millions of messages/sec with minimal CPU overhead.

def high_throughput_producer(topic: str, num_messages: int = 1_000_000):
    """
    Optimized for throughput: large batches, compression, async callbacks.
    Measures actual throughput and reports every 100k messages.
    """
    config = {
        "bootstrap.servers": "localhost:9092",
        "enable.idempotence": True,
        "acks": "all",
        "linger.ms": 100,              # Wait 100ms to fill large batches
        "batch.size": 1048576,          # 1MB batches
        "compression.type": "lz4",     # Fast compression
        "queue.buffering.max.kbytes": 1048576,  # 1GB buffer
        "retries": 2147483647,
        "max.in.flight.requests.per.connection": 5,
    }

    producer = Producer(config)
    stats = {"sent": 0, "errors": 0, "start": time.time()}

    def cb(err, msg):
        if err:
            stats["errors"] += 1
        else:
            stats["sent"] += 1
            if stats["sent"] % 100_000 == 0:
                elapsed = time.time() - stats["start"]
                rate = stats["sent"] / elapsed
                print(f"[THROUGHPUT] {stats['sent']:,} msgs | {rate:,.0f} msgs/sec")

    print(f"Producing {num_messages:,} messages to '{topic}'...")
    for i in range(num_messages):
        payload = {
            "event_id": str(uuid.uuid4()),
            "user_id": f"user_{i % 10000}",      # 10k unique users
            "event_type": "page_view",
            "ts": time.time(),
            "sequence": i,
        }
        produce_async(producer, topic, f"user_{i % 10000}", payload)

    # Final flush — wait for all buffered messages to deliver
    print("Flushing remaining messages...")
    remaining = producer.flush(timeout=60)
    if remaining > 0:
        print(f"WARNING: {remaining} messages failed to deliver!")

    elapsed = time.time() - stats["start"]
    print(f"\nFinal stats:")
    print(f"  Sent:    {stats['sent']:,} messages")
    print(f"  Errors:  {stats['errors']:,} messages")
    print(f"  Time:    {elapsed:.2f}s")
    print(f"  Rate:    {stats['sent']/elapsed:,.0f} msgs/sec")


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    # Example 1: Basic async producer
    config = {
        "bootstrap.servers": "localhost:9092",
        "enable.idempotence": True,
        "acks": "all",
        "linger.ms": 5,
        "batch.size": 1048576,
        "compression.type": "lz4",
        "retries": 2147483647,
        "max.in.flight.requests.per.connection": 5,
    }
    producer = create_producer(config)

    # Produce 10 async keyed messages
    for i in range(10):
        event = {
            "event_id": str(uuid.uuid4()),
            "user_id": f"user_{i}",
            "event_type": "login",
            "ts": time.time(),
        }
        produce_keyed(producer, "user-events", f"user_{i}", event)

    # Always flush before exiting — unflushed messages are LOST.
    producer.flush(timeout=30)

    # Example 2: Transaction
    transactional_produce_example()
