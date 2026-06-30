"""
============================================================
L05: Kafka Reliability Patterns in Python
============================================================
WHAT: Delivery semantics (at-most-once, at-least-once,
      exactly-once), idempotent and transactional producers,
      poison pill handling, dead letter queues, and graceful
      consumer shutdown — all using confluent-kafka-python.
WHY:  Kafka is durable, but "durable" does not mean "correct."
      Without the right combination of producer and consumer
      settings, you will silently lose messages or process them
      multiple times — both unacceptable in financial, inventory,
      or audit-trail systems.
LEVEL: Advanced
============================================================
CONCEPT OVERVIEW:
  THREE DELIVERY SEMANTICS:

  1. AT-MOST-ONCE:
     Producer: acks=0 (fire-and-forget, no retry).
     Consumer: commit offset BEFORE processing message.
     Result: messages can be LOST (producer fire-and-forget,
     or consumer crashed after commit but before processing).
     Use when: loss is acceptable, latency must be minimal.
     Example: click tracking, non-critical metrics.

  2. AT-LEAST-ONCE (default for most systems):
     Producer: acks=all, retries > 0.
     Consumer: commit offset AFTER processing message.
     Result: on crash/retry, the same message is processed
     MORE THAN ONCE. Consumer must be idempotent.
     Use when: no loss allowed, duplicates are manageable.
     Example: log aggregation, event sourcing.

  3. EXACTLY-ONCE (EOS — Exactly-Once Semantics):
     Producer: enable.idempotence=True + transactional.id.
     Consumer: isolation.level=read_committed.
     Result: each message is delivered exactly once to each
     consumer group. Zero duplicates, zero loss.
     Use when: financial transactions, inventory updates.
     NOTE: EOS guarantees only the Kafka delivery pipeline.
     If your consumer writes to a DB, the DB write also needs
     to be idempotent (DB doesn't know about Kafka EOS).

PRODUCTION USE CASE:
  Payment processing: each payment event must be processed
  exactly once. Duplicate processing = double charge. Missed
  processing = unprocessed payment. Both are catastrophic.
  Solution: EOS producer + transactional consumer + idempotent
  DB upsert (ON CONFLICT DO NOTHING with payment_id).

COMMON MISTAKES:
  - Committing offsets before processing (at-most-once risk).
  - Not enabling idempotence (duplicates on network retry).
  - Using transactional.id without isolation.level=read_committed
    on the consumer (you'll read uncommitted/aborted messages).
  - Infinite retry loops on poison pills (consumer falls behind
    forever; partition offset never advances).
  - Not calling consumer.close() on shutdown (offsets lost,
    next consumer re-processes committed messages or skips some).
============================================================
"""

import json
import logging
import time
import signal
import sys
from typing import Optional, Dict, Any

from confluent_kafka import (
    Producer, Consumer, KafkaError, KafkaException,
    TopicPartition, OFFSET_BEGINNING
)
from confluent_kafka.admin import AdminClient, NewTopic

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)
log = logging.getLogger(__name__)


# ============================================================
# SECTION 1: IDEMPOTENT PRODUCER
# ============================================================
# The idempotent producer prevents DUPLICATE WRITES caused by
# network retries. Without idempotence:
#   1. Producer sends message to broker.
#   2. Broker writes message, sends ACK.
#   3. ACK is lost (network blip).
#   4. Producer retries → broker writes AGAIN → duplicate.
#
# With idempotence:
#   1. Kafka assigns the producer a unique PID (Producer ID).
#   2. Each message gets a sequence number per partition.
#   3. Broker tracks (PID, partition, sequence) tuples.
#   4. On retry, broker sees it already wrote this (PID, seq) → skip.
#   5. Producer receives ACK as if it was the first write.
#
# REQUIREMENTS:
#   - acks must be 'all' (idempotence needs all replicas to ack)
#   - retries must be > 0 (idempotence needs retries to deduplicate)
#   - max.in.flight.requests.per.connection must be <= 5
#   Setting enable.idempotence=True enforces all of these automatically.
#
# COST: slightly higher latency (waits for all ISR acks). Worth it.

def create_idempotent_producer(bootstrap_servers: str) -> Producer:
    """
    Create a producer with idempotence enabled.
    This is the MINIMUM safe configuration for production.
    """
    config = {
        # ----- Connection -----
        'bootstrap.servers': bootstrap_servers,

        # ----- Idempotence -----
        # This single flag sets:
        #   acks=all, retries=MAX_INT,
        #   max.in.flight.requests.per.connection=5
        'enable.idempotence': True,

        # ----- Batching / Throughput -----
        # Wait up to 5ms to accumulate messages into a batch.
        # Larger batches = better compression + fewer requests.
        # Trade-off: adds 5ms of artificial latency.
        'linger.ms': 5,

        # Max batch size per partition (bytes).
        'batch.size': 65536,   # 64KB

        # ----- Compression -----
        # lz4 is fast with decent compression ratio.
        # snappy is also common. gzip has best ratio but slowest.
        'compression.type': 'lz4',

        # ----- Serialization -----
        # We use JSON here. In production: use Avro + Schema Registry
        # (see L06_schema_registry.py) for schema enforcement.
        'key.serializer': lambda k, ctx: k.encode('utf-8') if k else None,
        'value.serializer': lambda v, ctx: json.dumps(v).encode('utf-8'),
    }
    return Producer(config)


def delivery_report(err, msg):
    """
    Callback invoked by Producer.poll() after each message delivery
    (or failure). This is how you know if a message was actually written.

    WHY: The producer is async. produce() enqueues the message locally.
    The actual network send happens in a background thread. This callback
    is the only reliable signal of success or failure.
    """
    if err is not None:
        log.error(
            "Message delivery FAILED | topic=%s partition=%d offset=%d error=%s",
            msg.topic(), msg.partition(), msg.offset(), err
        )
        # In production: send to a retry queue, increment error counter,
        # alert if error rate exceeds threshold.
    else:
        log.debug(
            "Message delivered | topic=%s partition=%d offset=%d",
            msg.topic(), msg.partition(), msg.offset()
        )


def produce_order_event(producer: Producer, order_id: str, event: Dict[str, Any]):
    """Produce a single order event with the order_id as key."""
    try:
        producer.produce(
            topic='orders',
            key=order_id,           # determines partition (all events for this
                                    # order go to the same partition → ordered)
            value=event,
            callback=delivery_report
        )
        # poll() triggers callbacks for messages that have been
        # acknowledged (or failed). Timeout=0: non-blocking check.
        # Call regularly to drain the delivery report queue.
        producer.poll(0)

    except BufferError:
        # Internal queue is full: too many messages in flight.
        # This means the broker is slower than our produce rate.
        # Block until there's room, then retry.
        log.warning("Producer queue full, flushing before retry")
        producer.flush()   # blocks until all queued messages are delivered
        # Then retry:
        producer.produce(topic='orders', key=order_id, value=event,
                         callback=delivery_report)


# ============================================================
# SECTION 2: TRANSACTIONAL PRODUCER (EXACTLY-ONCE)
# ============================================================
# Transactions group multiple produces (possibly to multiple
# topics/partitions) into an ATOMIC unit. Either ALL messages
# in the transaction are visible to read_committed consumers,
# or NONE are (if aborted).
#
# Use cases:
#   - Read-process-write: consume from topic A, process, produce
#     to topic B — all in one atomic transaction. Offsets for
#     the consumed messages are also committed transactionally.
#   - Fan-out: produce to multiple topics atomically.
#
# transactional.id:
#   Must be UNIQUE per producer instance (not per message).
#   If a producer with the same transactional.id starts while
#   another is running, it fences (kills) the old one.
#   This prevents zombie producers from committing stale transactions.
#   Use a stable ID derived from the service instance: e.g., "payments-worker-1".

def create_transactional_producer(bootstrap_servers: str, transactional_id: str) -> Producer:
    """
    Create a transactional producer for exactly-once semantics.
    transactional_id must be unique per producer instance.
    """
    config = {
        'bootstrap.servers': bootstrap_servers,
        'enable.idempotence': True,   # required for transactions
        'transactional.id': transactional_id,
        # transaction.timeout.ms: how long the broker waits for the
        # producer to commit or abort before it auto-aborts.
        # Must be > max processing time of your transaction.
        'transaction.timeout.ms': 60000,   # 60 seconds
        'compression.type': 'lz4',
    }
    producer = Producer(config)
    # MUST call init_transactions() once before any transaction.
    # Registers this producer with the broker and recovers any
    # incomplete transactions from a previous run.
    producer.init_transactions()
    return producer


def transactional_produce_example(producer: Producer):
    """
    Demonstrates atomic multi-topic produce with transactions.
    If anything fails, abort_transaction() rolls back all writes.
    """
    try:
        producer.begin_transaction()

        # These two produce calls are ATOMIC.
        # If we abort, consumers with read_committed see neither.
        producer.produce('payments', key='pay_001', value={'amount': 99.99, 'status': 'processed'})
        producer.produce('order-status', key='ord_001', value={'status': 'paid'})

        # commit_transaction() flushes all messages and marks the
        # transaction as committed on the broker.
        producer.commit_transaction()
        log.info("Transaction committed successfully")

    except KafkaException as e:
        log.error("Transaction failed, aborting: %s", e)
        # abort_transaction() marks the transaction as aborted.
        # read_committed consumers will never see these messages.
        producer.abort_transaction()
        raise


# ============================================================
# SECTION 3: RELIABLE CONSUMER
# ============================================================
# AT-LEAST-ONCE consumer pattern:
#   1. Poll messages.
#   2. PROCESS each message (write to DB, call API, etc.).
#   3. COMMIT offset AFTER processing.
#
# If the consumer crashes between step 2 and 3, it re-processes
# the message on restart. This is why processing must be idempotent.
#
# Auto-commit (enable.auto.commit=True) commits on a schedule
# (auto.commit.interval.ms). This is at-most-once if the consumer
# crashes after commit but before processing, or at-least-once if
# it crashes before commit. The schedule doesn't align with your
# processing, so the semantics are unpredictable. Disable it.

def create_reliable_consumer(bootstrap_servers: str, group_id: str,
                              exactly_once: bool = False) -> Consumer:
    """
    Create a consumer with reliable at-least-once semantics.
    Set exactly_once=True to enable read_committed isolation.
    """
    config = {
        'bootstrap.servers': bootstrap_servers,
        'group.id': group_id,

        # DISABLE auto-commit. We will commit manually after processing.
        # This is critical for at-least-once semantics.
        'enable.auto.commit': False,

        # auto.offset.reset: what to do when there's no committed offset
        # for this consumer group (first run, or offset expired).
        # 'earliest': start from the beginning of the topic.
        # 'latest': start from new messages only.
        # For payment processing: 'earliest' to never miss anything.
        'auto.offset.reset': 'earliest',

        # isolation.level: CRITICAL for exactly-once.
        # read_committed: consumer ONLY sees messages from committed
        # transactions. Aborted transaction messages are invisible.
        # read_uncommitted (default): sees all messages including those
        # from aborted transactions — defeats EOS guarantees.
        'isolation.level': 'read_committed' if exactly_once else 'read_uncommitted',

        # fetch.min.bytes: minimum data to fetch per request.
        # Reduces network overhead when messages are small and sparse.
        'fetch.min.bytes': 1024,

        # max.poll.interval.ms: max time between poll() calls before
        # the broker considers this consumer dead and triggers a rebalance.
        # Set higher than your max processing time.
        'max.poll.interval.ms': 300000,  # 5 minutes
    }
    return Consumer(config)


# ============================================================
# SECTION 4: POISON PILL HANDLING AND DEAD LETTER QUEUE
# ============================================================
# A POISON PILL is a message that always causes processing to
# fail (corrupt JSON, schema mismatch, triggers a bug in your code).
# Without handling: consumer retries forever, the partition offset
# NEVER advances, all messages behind the poison pill are blocked.
#
# STRATEGY:
#   1. Try to process the message.
#   2. On failure, retry up to MAX_RETRIES times.
#   3. After MAX_RETRIES, send message to Dead Letter Queue (DLQ).
#   4. Commit the offset and move on.
#
# DLQ MESSAGE FORMAT:
#   Include enough context to debug: original topic, partition,
#   offset, key, value, error message, timestamp, service name.
#   Store this in Kafka message headers.

MAX_RETRIES = 3
DLQ_TOPIC = "orders.dlq"


def send_to_dlq(producer: Producer, original_msg, error: Exception):
    """
    Send a failed message to the Dead Letter Queue with diagnostic headers.
    The DLQ is a regular Kafka topic consumed by a monitoring/alerting service.
    """
    headers = {
        'original.topic': original_msg.topic().encode(),
        'original.partition': str(original_msg.partition()).encode(),
        'original.offset': str(original_msg.offset()).encode(),
        'original.key': original_msg.key() or b'',
        'error.message': str(error).encode(),
        'error.timestamp': str(int(time.time() * 1000)).encode(),
        'failed.service': b'order-processor',
        'failed.at': time.strftime('%Y-%m-%dT%H:%M:%SZ').encode(),
    }
    producer.produce(
        topic=DLQ_TOPIC,
        key=original_msg.key(),
        value=original_msg.value(),
        headers=list(headers.items()),
        callback=delivery_report,
    )
    producer.flush()
    log.warning(
        "Message sent to DLQ | original_topic=%s partition=%d offset=%d error=%s",
        original_msg.topic(), original_msg.partition(),
        original_msg.offset(), error
    )


def process_order_message(msg_value: Dict[str, Any]) -> None:
    """
    Simulate order processing. Raises on failure.
    In production: write to DB, call downstream APIs, etc.
    """
    if 'order_id' not in msg_value:
        raise ValueError(f"Missing order_id field: {msg_value}")
    # ... actual processing logic ...
    log.info("Processed order: %s", msg_value.get('order_id'))


# ============================================================
# SECTION 5: GRACEFUL SHUTDOWN
# ============================================================
# On SIGTERM/SIGINT (from Docker, Kubernetes, systemd):
#   1. Stop polling new messages.
#   2. Finish processing the current message.
#   3. Call consumer.close():
#      - Commits any pending offsets.
#      - Sends LeaveGroup request to broker.
#      - Broker triggers an immediate rebalance (not waiting for
#        session.timeout.ms). Other consumers pick up the partitions
#        quickly instead of waiting for the timeout.
#   4. If using a transactional producer: commit or abort current
#      transaction before exiting.

class GracefulShutdown:
    """Signal handler that sets a flag to stop the consumer loop cleanly."""
    def __init__(self):
        self.shutdown_requested = False
        signal.signal(signal.SIGTERM, self._request_shutdown)
        signal.signal(signal.SIGINT, self._request_shutdown)

    def _request_shutdown(self, signum, frame):
        log.info("Shutdown signal received (signal %d), draining...", signum)
        self.shutdown_requested = True


# ============================================================
# SECTION 6: FULL EXAMPLE — PAYMENT PROCESSOR WITH EOS + DLQ
# ============================================================

def run_payment_consumer(bootstrap_servers: str):
    """
    Production-grade payment consumer demonstrating:
    - Exactly-once semantics (read_committed isolation)
    - Poison pill handling with DLQ
    - Manual offset commit after processing
    - Graceful shutdown on SIGTERM
    - Idempotent consumer logic (DB upsert by payment_id)
    """
    shutdown = GracefulShutdown()

    consumer = create_reliable_consumer(
        bootstrap_servers=bootstrap_servers,
        group_id='payment-processor-v1',
        exactly_once=True,   # read_committed: skip aborted transactions
    )

    # Idempotent producer for DLQ: use its own transactional.id
    dlq_producer = create_idempotent_producer(bootstrap_servers)

    consumer.subscribe(['payments'])
    log.info("Payment consumer started, subscribed to 'payments'")

    try:
        while not shutdown.shutdown_requested:
            # poll() blocks for up to 1 second waiting for messages.
            # Returns None if no messages available in that window.
            msg = consumer.poll(timeout=1.0)

            if msg is None:
                continue   # no message, loop and check shutdown flag

            if msg.error():
                # PARTITION_EOF: reached end of partition (not an error).
                # This is informational — the consumer is caught up.
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    log.debug("Reached end of partition %d at offset %d",
                              msg.partition(), msg.offset())
                else:
                    # Real error: broker down, auth failure, etc.
                    raise KafkaException(msg.error())
                continue

            # Parse message
            try:
                value = json.loads(msg.value().decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                log.error("Unparseable message at offset %d: %s", msg.offset(), e)
                send_to_dlq(dlq_producer, msg, e)
                # Commit this bad message so we don't re-consume it forever.
                consumer.commit(message=msg)
                continue

            # Retry loop for processing failures
            last_error: Optional[Exception] = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    process_order_message(value)
                    last_error = None
                    break   # success — exit retry loop
                except Exception as e:
                    last_error = e
                    log.warning(
                        "Processing attempt %d/%d failed | offset=%d error=%s",
                        attempt, MAX_RETRIES, msg.offset(), e
                    )
                    if attempt < MAX_RETRIES:
                        time.sleep(2 ** attempt)   # exponential backoff: 2s, 4s

            if last_error is not None:
                # All retries exhausted → this is a poison pill.
                # Send to DLQ and move on. The DLQ team investigates.
                send_to_dlq(dlq_producer, msg, last_error)

            # CRITICAL: Commit offset ONLY after processing (and DLQ if needed).
            # If we crash here, we re-process this message. That's why
            # process_order_message must be idempotent (DB upsert by payment_id).
            consumer.commit(message=msg)
            # message=msg commits the offset of THIS specific message.
            # (offset+1 is stored, meaning "next message to fetch starts here")

    except KafkaException as e:
        log.error("Fatal Kafka error: %s", e)
        sys.exit(1)
    finally:
        # ALWAYS close the consumer, even on exception.
        # close() commits pending offsets and sends LeaveGroup.
        log.info("Closing consumer...")
        consumer.close()
        log.info("Consumer closed cleanly.")


# ============================================================
# SECTION 7: CIRCUIT BREAKER FOR DOWNSTREAM DEPENDENCIES
# ============================================================
# If the database is down, processing messages and committing
# offsets would mark them "done" even though they weren't saved.
# Instead: STOP consuming (don't commit) until the DB recovers.
# The consumer group lag grows, but NO data is lost.
# When the DB recovers, the consumer resumes from the last
# committed offset and processes the backlog.
#
# This is a simple circuit breaker:

class CircuitBreaker:
    """
    Tracks downstream dependency health. Opens (breaks) after
    consecutive failures; allows test calls after cool-down.
    When open: consumer pauses. When closed: normal operation.
    """
    def __init__(self, failure_threshold: int = 5, cooldown_seconds: int = 30):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.open_since: Optional[float] = None

    @property
    def is_open(self) -> bool:
        if self.open_since is None:
            return False
        if time.time() - self.open_since > self.cooldown_seconds:
            # Cool-down expired: allow one test request through.
            log.info("Circuit breaker: cool-down expired, allowing test request")
            self.open_since = None
            self.failure_count = 0
            return False
        return True

    def record_success(self):
        self.failure_count = 0
        self.open_since = None

    def record_failure(self):
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            if self.open_since is None:
                log.warning("Circuit breaker OPENED after %d failures", self.failure_count)
                self.open_since = time.time()


if __name__ == '__main__':
    BOOTSTRAP_SERVERS = 'localhost:9092'
    run_payment_consumer(BOOTSTRAP_SERVERS)
