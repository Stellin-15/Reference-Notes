# ============================================================
# L03: Kafka Consumers — Offsets, Groups, Rebalancing & Reliability
# ============================================================
# WHAT: A Kafka consumer reads records from topics by pulling from brokers.
#       Consumers track their position using offsets stored in the internal
#       __consumer_offsets topic. Consumer groups enable parallel consumption.
#
# WHY:  Consumer semantics (when to commit offsets) directly determine
#       whether your system is at-most-once, at-least-once, or exactly-once.
#       Most production systems target at-least-once + idempotent processing.
#
# LEVEL: Foundations → Advanced
# ============================================================
# CONCEPT OVERVIEW:
#
#   PULL MODEL: Consumers pull from Kafka at their own pace.
#     Kafka does NOT push to consumers. This means consumers control
#     their own backpressure naturally — a slow consumer doesn't crash Kafka.
#
#   CONSUMER GROUP:
#     - Multiple consumers with the same group.id share a topic's partitions.
#     - Each partition is consumed by EXACTLY ONE consumer in the group.
#     - Partition count = max useful consumers in a group (extras sit idle).
#     - Different groups are completely independent — each has its own offsets.
#     - Example: topic with 6 partitions, group of 3 consumers = 2 parts each.
#
#   OFFSET COMMIT SEMANTICS:
#     At-most-once:  commit BEFORE processing → if crash, processed record
#                    is "skipped" (offset advanced past it). Messages lost.
#     At-least-once: commit AFTER processing → if crash before commit,
#                    record is re-processed on restart. Duplicates possible.
#     Exactly-once:  transactional consumer+producer OR idempotent processing.
#
#   REBALANCING:
#     Triggered when: consumer joins/leaves group, new partitions added,
#     or consumer misses a heartbeat (session.timeout.ms).
#     During rebalance: ALL consumers stop processing (stop-the-world).
#     Cooperative rebalancing (Kafka 2.4+) avoids full stop-the-world.
#
# PRODUCTION USE CASE:
#   Netflix: video playback events → consumer group with 50 consumers
#   processing 10M events/sec for real-time recommendation updates.
#   Lag monitoring via Burrow alerts when any group exceeds 50k lag.
#
# COMMON MISTAKES:
#   1. Committing before processing (at-most-once = silent data loss).
#   2. Not handling partition revocation in rebalance listener — committing
#      offsets for partitions you no longer own corrupts another consumer's state.
#   3. session.timeout.ms too low → constant rebalances under load.
#   4. max.poll.interval.ms too low → consumer kicked out if processing is slow.
#   5. Calling commit() inside a database transaction — they're not atomic.
# ============================================================

from confluent_kafka import Consumer, TopicPartition, KafkaError, KafkaException, OFFSET_BEGINNING, OFFSET_END
import json
import time
import signal
import logging
from typing import List, Optional, Dict, Callable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ============================================================
# SECTION 1: Consumer Configuration Reference
# ============================================================

CONSUMER_CONFIG_REFERENCE = {
    # --- Connection ---
    "bootstrap.servers": "localhost:9092",

    # --- Group identity ---
    # group.id: All consumers with the same group.id share partitions.
    # Use meaningful names: "payment-processor", "analytics-pipeline-v2"
    "group.id": "my-consumer-group",

    # --- Offset reset: what to do when no committed offset exists ---
    # "earliest": start from offset 0 (replay all history)
    # "latest": start from newest records (skip history)
    # This only applies the FIRST TIME a group reads a topic (no prior commit).
    "auto.offset.reset": "earliest",

    # --- Auto-commit: convenience vs. control ---
    # True: library automatically commits every auto.commit.interval.ms
    #       Risk: commits offsets for records not yet fully processed.
    #       Use ONLY if your processing is idempotent and loss is acceptable.
    # False: YOU control exactly when offsets are committed.
    #        This is the production standard for reliable processing.
    "enable.auto.commit": False,

    # Only relevant if enable.auto.commit=True:
    "auto.commit.interval.ms": 5000,  # Commit every 5 seconds

    # --- Heartbeat and session management ---
    # heartbeat.interval.ms: how often consumer sends heartbeat to coordinator.
    #   Must be < session.timeout.ms / 3.
    "heartbeat.interval.ms": 3000,

    # session.timeout.ms: if no heartbeat for this long, consumer is presumed dead.
    #   Too low: false rebalances under GC pauses or load spikes.
    #   Too high: slow detection of dead consumers = longer rebalance.
    #   Broker range: [group.min.session.timeout.ms, group.max.session.timeout.ms]
    "session.timeout.ms": 45000,

    # max.poll.interval.ms: max time between poll() calls before consumer
    #   is considered dead. Your processing must complete within this window.
    #   If you need more time, increase this or process smaller batches.
    "max.poll.interval.ms": 300000,   # 5 minutes — increase for slow processing

    # --- Fetch tuning ---
    # fetch.min.bytes: broker waits until this many bytes available before responding.
    #   Reduces fetch calls; increases latency slightly. Good for throughput.
    "fetch.min.bytes": 1,             # Default: respond immediately (low latency)

    # fetch.max.wait.ms: max time broker waits to fill fetch.min.bytes.
    "fetch.max.wait.ms": 500,

    # max.partition.fetch.bytes: max bytes per partition per fetch request.
    "max.partition.fetch.bytes": 1048576,  # 1 MB per partition

    # max.poll.records: max records returned per poll() call.
    #   Lower = more frequent commits, less reprocessing on restart.
    #   Higher = better throughput, longer processing windows.
    "max.poll.records": 500,

    # --- Isolation for exactly-once consumers ---
    # read_committed: only read messages from committed transactions.
    #   Hides records from aborted transactions and uncommitted ones.
    # read_uncommitted (default): read all records including aborted transactions.
    "isolation.level": "read_committed",

    # --- Rebalance protocol ---
    # "cooperative-sticky": new protocol — minimal partition movement,
    #   no stop-the-world. Use for Kafka 2.4+ (confluent-kafka >= 1.6).
    # "eager" (default): all partitions revoked, then reassigned. Stop-the-world.
    "partition.assignment.strategy": "cooperative-sticky",
}


# ============================================================
# SECTION 2: subscribe() vs assign() — Two Modes of Consumption
# ============================================================

def subscribe_mode_example():
    """
    subscribe() — Dynamic group membership (production standard).

    The broker's group coordinator assigns partitions to consumers.
    Partitions are rebalanced automatically when group membership changes.
    Use this for normal application consumers.
    """
    consumer = Consumer({
        "bootstrap.servers": "localhost:9092",
        "group.id": "analytics-group",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "partition.assignment.strategy": "cooperative-sticky",
    })
    # Subscribe to one or more topics (regex also supported)
    consumer.subscribe(["user-events", "order-events"])
    # Or with regex: consumer.subscribe(['^user-.*'])  # All user-* topics
    return consumer


def assign_mode_example():
    """
    assign() — Manual/static partition assignment.

    Bypasses the group coordinator entirely.
    No rebalancing, no group membership.
    Use for: admin tools, replay jobs, specific partition processing,
             testing, or when you need deterministic partition assignment.
    """
    consumer = Consumer({
        "bootstrap.servers": "localhost:9092",
        # group.id still needed for offset storage, even with assign()
        "group.id": "replay-job-2024-01-15",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    # Manually assign specific partitions (no group coordinator involved)
    partitions = [
        TopicPartition("user-events", 0),   # Topic, partition number
        TopicPartition("user-events", 1),
        TopicPartition("user-events", 2),
    ]
    consumer.assign(partitions)
    return consumer


# ============================================================
# SECTION 3: Core Poll Loop with Manual Offset Commit
# ============================================================
# This is the production-standard consumer pattern.
# Process records THEN commit offsets (at-least-once semantics).

class KafkaConsumerService:
    """
    Production-grade consumer with:
    - Manual offset commits (at-least-once)
    - Graceful shutdown on SIGINT/SIGTERM
    - Error handling and DLQ routing
    - Lag monitoring
    """

    def __init__(self, config: dict, topics: List[str],
                 processor: Callable, dlq_topic: Optional[str] = None):
        self.consumer = Consumer(config)
        self.topics = topics
        self.processor = processor
        self.dlq_topic = dlq_topic
        self._running = True

        # Graceful shutdown: catch signals
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        log.info(f"Received signal {signum} — initiating graceful shutdown")
        self._running = False

    def run(self):
        """Main consumer loop."""
        self.consumer.subscribe(
            self.topics,
            on_assign=self._on_assign,       # Called after rebalance
            on_revoke=self._on_revoke,       # Called BEFORE partitions taken away
            on_lost=self._on_lost,           # Called when partitions lost (crash)
        )

        log.info(f"Consumer started, subscribed to: {self.topics}")

        try:
            while self._running:
                # poll() fetches up to max.poll.records records.
                # timeout=1.0: block up to 1 second if no messages available.
                # This drives heartbeats and rebalances — MUST be called regularly.
                msg = self.consumer.poll(timeout=1.0)

                if msg is None:
                    # No message available within timeout — normal, keep polling
                    continue

                if msg.error():
                    self._handle_error(msg.error())
                    continue

                # Process the message
                self._process_message(msg)

        except Exception as e:
            log.error(f"Unexpected error in consumer loop: {e}", exc_info=True)
            raise
        finally:
            # Always close() — commits final offsets and leaves group cleanly
            log.info("Closing consumer...")
            self.consumer.close()   # This triggers a final rebalance (cooperative)

    def _process_message(self, msg):
        """
        Process one message. Commit offset AFTER successful processing.
        This is at-least-once: if processing fails before commit, message
        will be re-delivered on next poll after a restart.
        """
        topic = msg.topic()
        partition = msg.partition()
        offset = msg.offset()
        key = msg.key().decode("utf-8") if msg.key() else None
        value = msg.value()

        try:
            # Deserialize
            payload = json.loads(value.decode("utf-8"))

            log.debug(f"Processing: topic={topic} partition={partition} "
                      f"offset={offset} key={key}")

            # Call the actual business logic processor
            self.processor(key, payload, topic, partition, offset)

            # Commit AFTER successful processing (at-least-once)
            # store_offsets() marks offset for commit; actual commit on next poll.
            # This is more efficient than committing every single message.
            self.consumer.store_offsets(msg)

        except json.JSONDecodeError as e:
            # Poison pill: malformed JSON — cannot be processed, send to DLQ
            log.error(f"Malformed message at {topic}:{partition}:{offset}: {e}")
            if self.dlq_topic:
                self._send_to_dlq(msg, str(e))
            # Still commit offset — don't get stuck on unparseable messages
            self.consumer.store_offsets(msg)

        except Exception as e:
            # Processing error — log, optionally DLQ, decide whether to commit
            log.error(f"Processing failed at {topic}:{partition}:{offset}: {e}",
                      exc_info=True)
            # Strategy A: Retry N times then DLQ (shown below)
            # Strategy B: Commit and move on (at-most-once for this message)
            # Strategy C: Don't commit — message will be reprocessed (careful!)
            if self.dlq_topic:
                self._send_to_dlq(msg, str(e))
                self.consumer.store_offsets(msg)  # Move past the bad message
            # else: don't commit — let it be reprocessed

    def _handle_error(self, error: KafkaError):
        """Handle partition-level errors from poll()."""
        if error.code() == KafkaError.UNKNOWN_TOPIC_OR_PART:
            log.warning(f"Topic or partition unknown: {error}")
        elif error.code() == KafkaError._PARTITION_EOF:
            # Reached end of partition — informational, not an error
            # Only seen if enable.partition.eof=True in config
            log.debug("Reached end of partition")
        elif error.fatal():
            # Fatal error: unrecoverable, must restart consumer
            raise KafkaException(error)
        else:
            log.warning(f"Consumer error: {error}")

    def _send_to_dlq(self, msg, reason: str):
        """
        Dead Letter Queue: send unprocessable messages to a separate topic.
        DLQ messages include original payload + error metadata.
        A separate DLQ consumer can alert, investigate, or replay.
        """
        from confluent_kafka import Producer
        # In production: inject DLQ producer via dependency injection
        dlq_producer = Producer({"bootstrap.servers": "localhost:9092"})
        dlq_record = {
            "original_topic": msg.topic(),
            "original_partition": msg.partition(),
            "original_offset": msg.offset(),
            "original_key": msg.key().decode() if msg.key() else None,
            "original_value": msg.value().decode("utf-8", errors="replace"),
            "error_reason": reason,
            "failed_at": time.time(),
        }
        dlq_producer.produce(
            topic=self.dlq_topic,
            key=msg.key(),
            value=json.dumps(dlq_record).encode("utf-8"),
        )
        dlq_producer.flush(timeout=5)
        log.warning(f"Sent message to DLQ: {self.dlq_topic}")

    def _on_assign(self, consumer, partitions):
        """
        Called after partitions are assigned during rebalance.
        Use this to: initialize state for new partitions, load DB state,
        set up per-partition metrics counters.
        """
        log.info(f"Partitions ASSIGNED: {[(p.topic, p.partition) for p in partitions]}")
        # Optional: seek to specific offsets on assignment
        # for p in partitions:
        #     p.offset = OFFSET_BEGINNING  # Replay from start
        # consumer.assign(partitions)

    def _on_revoke(self, consumer, partitions):
        """
        Called BEFORE partitions are taken away during rebalance.
        THIS IS THE CRITICAL MOMENT: commit offsets for the partitions
        being revoked, or another consumer may reprocess them.

        With cooperative rebalancing: only revoked partitions are affected.
        With eager rebalancing: ALL partitions are revoked.
        """
        log.info(f"Partitions REVOKED: {[(p.topic, p.partition) for p in partitions]}")
        # Commit offsets synchronously before yielding partitions
        try:
            consumer.commit(asynchronous=False)
            log.info("Committed offsets before partition revocation")
        except Exception as e:
            log.error(f"Failed to commit during revocation: {e}")

    def _on_lost(self, consumer, partitions):
        """
        Called when partitions are lost due to crash/timeout (not clean revoke).
        In this case, another consumer may have already taken over — don't commit!
        Just clean up local state.
        """
        log.warning(f"Partitions LOST: {[(p.topic, p.partition) for p in partitions]}")
        # Do NOT commit here — offsets may have been taken over by another consumer


# ============================================================
# SECTION 4: Offset Management Patterns
# ============================================================

def manual_sync_commit_example():
    """
    Commit every N messages synchronously.
    Slowest but most reliable — guaranteed commit before proceeding.
    Use when you can't afford to reprocess any messages.
    """
    consumer = Consumer({
        "bootstrap.servers": "localhost:9092",
        "group.id": "sync-commit-group",
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
    })
    consumer.subscribe(["user-events"])
    batch_size = 100
    count = 0
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None or msg.error():
                continue
            process_message(msg)
            count += 1
            if count % batch_size == 0:
                # Commit all offsets synchronously (blocks until broker confirms)
                consumer.commit(asynchronous=False)
                log.info(f"Committed after {count} messages")
    finally:
        consumer.close()


def manual_async_commit_example():
    """
    Commit asynchronously — fire-and-forget commit.
    Higher throughput than sync commit.
    Risk: if commit fails silently, duplicates on restart.
    Use when: throughput matters and duplicates are acceptable (idempotent processing).
    """
    def commit_callback(err, partitions):
        if err:
            log.error(f"Async commit failed: {err}")
        else:
            log.debug(f"Async commit succeeded: {partitions}")

    consumer = Consumer({
        "bootstrap.servers": "localhost:9092",
        "group.id": "async-commit-group",
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
    })
    consumer.subscribe(["user-events"])
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None or msg.error():
                continue
            process_message(msg)
            # store_offsets() marks offset internally; committed on next poll or explicit commit
            consumer.store_offsets(msg)
            # Commit async — broker confirms asynchronously via callback
            consumer.commit(asynchronous=True, callback=commit_callback)
    finally:
        consumer.commit(asynchronous=False)  # Final sync commit on exit
        consumer.close()


# ============================================================
# SECTION 5: Seeking to Specific Offsets
# ============================================================
# Kafka's superpower: replay any historical data from any point.
# Useful for: replaying after a bug fix, backfilling new systems,
#             debugging specific time windows.

def seek_to_beginning_example():
    """Replay all messages from the start of the topic."""
    consumer = Consumer({
        "bootstrap.servers": "localhost:9092",
        "group.id": "replay-group",
        "enable.auto.commit": False,
    })
    consumer.assign([
        TopicPartition("user-events", 0, OFFSET_BEGINNING),  # Start from offset 0
        TopicPartition("user-events", 1, OFFSET_BEGINNING),
    ])
    return consumer


def seek_to_timestamp_example(target_timestamp_ms: int):
    """
    Seek to the first offset at or after a given timestamp.
    Essential for time-based replay: "reprocess all events from midnight".
    """
    consumer = Consumer({
        "bootstrap.servers": "localhost:9092",
        "group.id": "timestamp-seek-group",
        "enable.auto.commit": False,
    })
    # First, assign all partitions (use assign not subscribe for explicit seeking)
    partitions = [
        TopicPartition("user-events", 0, target_timestamp_ms),  # Timestamp as offset
        TopicPartition("user-events", 1, target_timestamp_ms),
    ]
    # offsets_for_times() converts timestamps to actual offsets
    partitions_with_offsets = consumer.offsets_for_times(partitions, timeout=10)
    consumer.assign(partitions_with_offsets)
    log.info(f"Seeking to timestamp {target_timestamp_ms}ms: "
             f"{[(p.partition, p.offset) for p in partitions_with_offsets]}")
    return consumer


# ============================================================
# SECTION 6: Consumer Lag Monitoring
# ============================================================
# Lag = (Log End Offset) - (Consumer Committed Offset)
# Lag > 0 means consumer is behind.
# Growing lag = consumer can't keep up = scale out or optimize.
# Tools: kafka-consumer-groups.sh, Burrow (LinkedIn), Grafana+JMX Exporter

def get_consumer_lag(consumer: Consumer, topic: str) -> Dict[int, int]:
    """
    Calculate current lag per partition.
    Compare committed offsets against log-end offsets.
    Returns: {partition_id: lag_count}
    """
    partitions = consumer.assignment()
    if not partitions:
        return {}

    # Get committed offsets (where this group has read to)
    committed = consumer.committed(partitions, timeout=10)

    # Get high watermark (log end offset) for each partition
    lag = {}
    for tp in committed:
        # watermark_offsets returns (low, high) — high is the next offset to be written
        low, high = consumer.get_watermark_offsets(tp, timeout=10)
        committed_offset = tp.offset if tp.offset >= 0 else 0
        lag[tp.partition] = max(0, high - committed_offset)
        log.info(f"Partition {tp.partition}: committed={committed_offset} "
                 f"high_watermark={high} lag={lag[tp.partition]}")
    return lag


# ============================================================
# SECTION 7: Batch Processing Consumer
# ============================================================
# Instead of processing one message at a time, collect a batch
# and process together. Much more efficient for DB bulk inserts,
# API batch calls, or in-memory aggregations.

def batch_consumer_example(batch_size: int = 1000, batch_timeout: float = 5.0):
    """
    Collect records into batches, process as unit, then commit.
    Ideal for: bulk DB inserts, batched API calls, mini-aggregations.
    commit() covers all offsets in the batch atomically.
    """
    consumer = Consumer({
        "bootstrap.servers": "localhost:9092",
        "group.id": "batch-processor",
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
        "max.poll.records": 1000,      # Fetch up to 1000 records per poll
    })
    consumer.subscribe(["user-events"])

    try:
        while True:
            batch = []
            batch_start = time.time()

            # Collect records until batch_size reached or batch_timeout elapsed
            while len(batch) < batch_size:
                elapsed = time.time() - batch_start
                remaining_timeout = max(0, batch_timeout - elapsed)
                if remaining_timeout <= 0:
                    break

                msg = consumer.poll(timeout=remaining_timeout)
                if msg and not msg.error():
                    batch.append(msg)

            if not batch:
                continue

            # Process entire batch (e.g., bulk DB insert)
            process_batch(batch)

            # Commit all offsets in the batch at once
            consumer.commit(asynchronous=False)
            log.info(f"Processed and committed batch of {len(batch)} records")

    finally:
        consumer.close()


# ============================================================
# Placeholder processing functions
# ============================================================

def process_message(msg):
    """Placeholder business logic."""
    payload = json.loads(msg.value().decode("utf-8"))
    log.debug(f"Processing: {payload}")


def process_batch(messages):
    """Placeholder batch processor — e.g., bulk insert to DB."""
    log.info(f"Bulk processing {len(messages)} records")


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    def my_processor(key, payload, topic, partition, offset):
        """Application-specific processing logic."""
        log.info(f"Processing event: key={key} event_type={payload.get('event_type')}")
        # e.g., update user activity model, write to DB, call API

    service = KafkaConsumerService(
        config={
            "bootstrap.servers": "localhost:9092",
            "group.id": "user-event-processor-v1",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
            "isolation.level": "read_committed",
            "partition.assignment.strategy": "cooperative-sticky",
            "session.timeout.ms": 45000,
            "max.poll.interval.ms": 300000,
            "max.poll.records": 500,
        },
        topics=["user-events"],
        processor=my_processor,
        dlq_topic="user-events-dlq",
    )
    service.run()
