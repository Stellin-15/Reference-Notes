# =============================================================================
# WHAT: Messaging, Event-Driven Architecture, and Distributed Transaction Patterns
# WHY:  Synchronous request/response chains break under load and couple services
#       tightly. Messaging decouples producers from consumers, absorbs traffic
#       spikes, and enables resilient, independently-scalable microservices.
# LEVEL: Intermediate → Advanced (System Design Interview / Production Ready)
# =============================================================================
#
# CONCEPT OVERVIEW:
#   Message Queue       → point-to-point delivery; one consumer processes each message.
#   Event Streaming     → persistent log; multiple consumers replay the same events.
#   RabbitMQ            → broker-based message queue with rich routing via exchanges.
#   Kafka               → distributed commit log; high-throughput event streaming.
#   Delivery Semantics  → at-most-once, at-least-once, exactly-once.
#   Saga Pattern        → distributed transactions without 2PC.
#   Outbox Pattern      → reliable message publishing from within a DB transaction.
#   Idempotency         → safe to process the same message more than once.
#   Back-pressure       → consumer signals producer to slow down when overwhelmed.
#
# PRODUCTION USE CASES:
#   - Uber uses Kafka for real-time location event streaming (billions/day).
#   - Stripe uses RabbitMQ for payment processing job queues.
#   - Amazon uses choreography-based Sagas for order fulfilment across services.
#   - Debezium + Kafka implements the Outbox pattern for CDC (Change Data Capture).
#
# COMMON MISTAKES:
#   1. At-most-once delivery for critical operations (payments, emails) → data loss.
#   2. Not making consumers idempotent → duplicate processing corrupts state.
#   3. Missing dead-letter queue → poison messages block the entire queue forever.
#   4. Implementing Saga rollback logic wrong → partial state left in system.
#   5. Not setting message TTL → queue fills with stale messages during downtime.
#   6. Using a message queue as a database → wrong tool; use event sourcing instead.
# =============================================================================

import time
import uuid
import json
import threading
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Callable, Any
from enum import Enum
from abc import ABC, abstractmethod

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# =============================================================================
# SECTION 1: MESSAGE QUEUE vs EVENT STREAMING
# =============================================================================
# MESSAGE QUEUE (RabbitMQ, SQS, ActiveMQ):
#   - Point-to-point: message is delivered to ONE consumer then deleted.
#   - Good for: task queues, work distribution, job processing.
#   - Consumer group competes for messages (load distribution).
#   - Messages are transient: once acknowledged, they're gone.
#
# EVENT STREAMING (Kafka, Kinesis, Pulsar):
#   - Log-based: events are retained for a configurable period (days/weeks).
#   - Multiple independent consumer groups can each read ALL events.
#   - Good for: event sourcing, audit logs, real-time analytics, stream processing.
#   - Position tracking: consumers track their own offset in the log.
#   - Replay: new consumer groups can reprocess the full history.
#
# CHOOSE MESSAGE QUEUE when: you need work distribution and you don't need replay.
# CHOOSE EVENT STREAMING when: multiple consumers need the same events, or replay matters.

# =============================================================================
# SECTION 2: RABBITMQ CORE CONCEPTS
# =============================================================================
# PRODUCER → EXCHANGE → BINDING → QUEUE → CONSUMER
#
# EXCHANGE TYPES:
#   direct  → route by exact routing_key match.
#             e.g., routing_key="payment.completed" → queue "payments"
#   fanout  → broadcast to ALL bound queues; ignores routing_key.
#             e.g., order placed → notify inventory + email + analytics simultaneously
#   topic   → route by routing_key pattern using * (one word) and # (zero or more words).
#             e.g., "order.#" matches "order.placed", "order.shipped.express"
#   headers → route by message header key/value; more expressive than topic but slower.
#
# DEAD-LETTER QUEUE (DLQ):
#   Messages are moved to DLQ when:
#     - Consumer rejects (nack) without requeue
#     - Message TTL expires
#     - Queue length limit exceeded
#   DLQ enables inspection and reprocessing of failed messages without blocking the main queue.
#
# ACKNOWLEDGEMENT:
#   auto-ack → message deleted as soon as delivered (risky: if consumer crashes, message lost)
#   manual-ack → consumer explicitly acks after processing (safe for critical operations)

class ExchangeType(Enum):
    DIRECT  = "direct"
    FANOUT  = "fanout"
    TOPIC   = "topic"
    HEADERS = "headers"


@dataclass
class Message:
    """Represents a message flowing through the broker."""
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    routing_key: str = ""
    body: Dict[str, Any] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    ttl_seconds: Optional[float] = None      # message expires after this many seconds
    retry_count: int = 0                     # incremented each time the message is requeued
    max_retries: int = 3                     # move to DLQ after this many failures


@dataclass
class Queue:
    """Simulates a RabbitMQ queue."""
    name: str
    is_dlq: bool = False           # if True, this is a dead-letter queue
    dlq_name: Optional[str] = None # name of the DLQ to route failed messages to
    messages: deque = field(default_factory=deque)
    max_length: Optional[int] = None  # drop oldest when exceeded (prevents unbounded growth)


class Exchange:
    """
    Simulates a RabbitMQ exchange with direct, fanout, and topic routing.
    Real RabbitMQ exchanges live in the broker; this is for educational purposes.
    """

    def __init__(self, name: str, exchange_type: ExchangeType):
        self.name = name
        self.exchange_type = exchange_type
        # bindings: routing_key_pattern → list of queue names
        self._bindings: Dict[str, List[str]] = defaultdict(list)
        self._queues: Dict[str, Queue] = {}

    def bind(self, queue: Queue, routing_key: str = ""):
        """Bind a queue to this exchange with an optional routing key."""
        self._queues[queue.name] = queue
        self._bindings[routing_key].append(queue.name)
        logger.debug(f"Bound queue '{queue.name}' to exchange '{self.name}' "
                     f"with key='{routing_key}'")

    def publish(self, message: Message):
        """Route message to bound queues based on exchange type and routing key."""
        target_queues = self._resolve_queues(message.routing_key, message.headers)
        for queue_name in target_queues:
            queue = self._queues.get(queue_name)
            if queue:
                # enforce max_length limit by dropping oldest message
                if queue.max_length and len(queue.messages) >= queue.max_length:
                    dropped = queue.messages.popleft()
                    logger.warning(f"Queue '{queue_name}' full; dropped msg {dropped.message_id}")
                queue.messages.append(message)
                logger.debug(f"Routed msg {message.message_id} → queue '{queue_name}'")

    def _resolve_queues(self, routing_key: str, headers: Dict) -> List[str]:
        """Determine which queues receive this message."""
        if self.exchange_type == ExchangeType.FANOUT:
            # fanout: every bound queue gets the message regardless of routing key
            return [qn for binding_key in self._bindings for qn in self._bindings[binding_key]]

        elif self.exchange_type == ExchangeType.DIRECT:
            # direct: exact match on routing key
            return self._bindings.get(routing_key, [])

        elif self.exchange_type == ExchangeType.TOPIC:
            # topic: wildcard matching — * matches one word, # matches zero or more
            matched = []
            for pattern, queue_names in self._bindings.items():
                if self._topic_match(pattern, routing_key):
                    matched.extend(queue_names)
            return matched

        return []

    @staticmethod
    def _topic_match(pattern: str, routing_key: str) -> bool:
        """
        Match topic routing key against a pattern.
        * → matches exactly one word (dot-separated segment)
        # → matches zero or more words
        EXAMPLE: "order.#" matches "order.placed", "order.shipped.express"
                 "order.*" matches "order.placed" but NOT "order.shipped.express"
        """
        pattern_parts = pattern.split(".")
        key_parts = routing_key.split(".")
        return Exchange._match_parts(pattern_parts, key_parts)

    @staticmethod
    def _match_parts(pattern: List[str], key: List[str]) -> bool:
        if not pattern and not key:
            return True  # both exhausted simultaneously → full match
        if pattern and pattern[0] == "#":
            # # can consume zero or more segments — try both options
            return (Exchange._match_parts(pattern[1:], key) or  # consume zero
                    (bool(key) and Exchange._match_parts(pattern, key[1:])))  # consume one
        if not pattern or not key:
            return False  # one exhausted but not the other → no match
        if pattern[0] == "*" or pattern[0] == key[0]:
            return Exchange._match_parts(pattern[1:], key[1:])  # consume one segment
        return False


class Consumer:
    """
    Simulates a RabbitMQ consumer that polls a queue and processes messages.
    Demonstrates manual acknowledgement and dead-letter queue routing.
    """

    def __init__(
        self,
        queue: Queue,
        handler: Callable[[Message], bool],  # returns True = ack, False = nack
        dlq: Optional[Queue] = None,
    ):
        self.queue = queue
        self.handler = handler
        self.dlq = dlq  # dead-letter queue for failed messages

    def process_one(self) -> bool:
        """
        Consume one message from the queue.
        Manual ack: message is removed from queue only after successful processing.
        On failure: increment retry_count; move to DLQ after max_retries.
        """
        if not self.queue.messages:
            return False  # queue empty

        message = self.queue.messages[0]  # peek (don't remove until ack)

        # check TTL expiry
        if message.ttl_seconds:
            age = time.time() - message.timestamp
            if age > message.ttl_seconds:
                self.queue.messages.popleft()  # discard expired message
                logger.info(f"Message {message.message_id} expired (age={age:.1f}s)")
                return True

        success = self.handler(message)  # call application handler

        if success:
            self.queue.messages.popleft()  # ACK: remove from queue
            logger.info(f"ACK: message {message.message_id} processed")
        else:
            message.retry_count += 1
            if message.retry_count >= message.max_retries:
                self.queue.messages.popleft()  # remove from main queue
                if self.dlq:
                    self.dlq.messages.append(message)  # move to DLQ
                    logger.error(f"DLQ: message {message.message_id} after "
                                 f"{message.retry_count} retries")
                else:
                    logger.error(f"Dropped message {message.message_id} — no DLQ configured!")
            else:
                # leave message in queue for retry (it stays at front)
                logger.warning(f"NACK: message {message.message_id} "
                               f"(retry {message.retry_count}/{message.max_retries})")

        return True


# =============================================================================
# SECTION 3: DELIVERY SEMANTICS
# =============================================================================
# AT-MOST-ONCE: message sent once; if consumer crashes, message is lost.
#   HOW: auto-ack; fire-and-forget; no retry.
#   USE: analytics events where occasional loss is acceptable.
#   RISK: data loss.
#
# AT-LEAST-ONCE: message retried until acknowledged; consumer may receive it multiple times.
#   HOW: manual ack; producer retries on timeout; consumer must be idempotent.
#   USE: emails, payment webhooks, order processing — must not lose messages.
#   RISK: duplicate processing (mitigated by idempotency).
#
# EXACTLY-ONCE: message processed precisely once.
#   HOW: idempotent producers + transactional consumers (Kafka transactions) OR
#        idempotency keys with deduplication at the consumer.
#   USE: financial transactions, inventory deductions.
#   COST: high overhead; often replaced by at-least-once + idempotency in practice.

class DeliverySemantics(Enum):
    AT_MOST_ONCE  = "at_most_once"
    AT_LEAST_ONCE = "at_least_once"
    EXACTLY_ONCE  = "exactly_once"


# =============================================================================
# SECTION 4: MESSAGE ORDERING GUARANTEES
# =============================================================================
# FIFO within a single queue: guaranteed by RabbitMQ and Kafka (per partition).
# GLOBAL ordering: NOT guaranteed when multiple consumers or partitions are used.
#
# KAFKA ORDERING:
#   - All messages with the same partition key go to the same partition.
#   - Within a partition, order is guaranteed.
#   - Across partitions, no ordering guarantee.
#   EXAMPLE: key = order_id ensures all events for one order are in order.
#
# RABBITMQ ORDERING:
#   - Single consumer on a queue → FIFO guaranteed.
#   - Multiple consumers on same queue → ordering is broken (different consumers
#     process messages at different speeds).

class KafkaPartitionRouter:
    """
    Simulates Kafka's key-based partition routing.
    Same key always goes to same partition → ordering guaranteed per key.
    """

    def __init__(self, num_partitions: int):
        self.num_partitions = num_partitions
        # one deque per partition (each partition is an ordered log)
        self._partitions: List[deque] = [deque() for _ in range(num_partitions)]

    def produce(self, key: str, value: Dict) -> int:
        """Produce a message; route to partition deterministically by key hash."""
        partition = hash(key) % self.num_partitions  # same key → same partition
        self._partitions[partition].append({"key": key, "value": value, "offset": len(self._partitions[partition])})
        return partition

    def consume(self, partition: int) -> Optional[Dict]:
        """Consume next message from a specific partition (consumer tracks its offset)."""
        if self._partitions[partition]:
            return self._partitions[partition].popleft()
        return None


# =============================================================================
# SECTION 5: IDEMPOTENCY KEYS
# =============================================================================
# IDEMPOTENCY: processing the same message multiple times has the same effect
# as processing it once. Essential for at-least-once delivery.
#
# IMPLEMENTATION PATTERN:
#   1. Producer attaches a unique idempotency_key to each message (UUID).
#   2. Consumer checks a deduplication store (Redis, DB unique index) before processing.
#   3. If key already exists → skip processing, return cached response.
#   4. If key is new → process, then store key with TTL (typically 24 hours).
#
# PRODUCTION: Stripe requires idempotency keys on all payment API calls.
#             Exactly-once Kafka producers use producer ID + sequence number.

class IdempotencyStore:
    """
    Tracks processed idempotency keys to prevent duplicate message processing.
    In production: Redis with SETNX (set-if-not-exists) and a TTL.
    """

    def __init__(self, ttl_seconds: float = 86400):  # 24-hour window
        self._store: Dict[str, Dict] = {}  # key → {"processed_at": ts, "result": any}
        self.ttl_seconds = ttl_seconds

    def is_duplicate(self, idempotency_key: str) -> bool:
        """Return True if this key was already processed within the TTL window."""
        entry = self._store.get(idempotency_key)
        if not entry:
            return False
        # check if the stored entry has expired
        if time.time() - entry["processed_at"] > self.ttl_seconds:
            del self._store[idempotency_key]  # expired → treat as new
            return False
        return True  # duplicate detected

    def mark_processed(self, idempotency_key: str, result: Any = None):
        """Mark a key as processed and optionally cache the result."""
        self._store[idempotency_key] = {
            "processed_at": time.time(),
            "result": result,
        }

    def get_cached_result(self, idempotency_key: str) -> Optional[Any]:
        """Return the cached result for a duplicate request."""
        entry = self._store.get(idempotency_key)
        return entry["result"] if entry else None


def idempotent_handler(
    message: Message,
    store: IdempotencyStore,
    process_fn: Callable[[Message], Any],
) -> Any:
    """
    Wrap a message handler with idempotency checking.
    Returns cached result for duplicates; calls process_fn for new messages.
    """
    key = message.message_id  # use message_id as idempotency key

    if store.is_duplicate(key):
        logger.info(f"Duplicate message {key} — returning cached result")
        return store.get_cached_result(key)  # return without re-processing

    result = process_fn(message)       # first time — actually process the message
    store.mark_processed(key, result)  # record so future duplicates are skipped
    return result


# =============================================================================
# SECTION 6: EVENT-DRIVEN ARCHITECTURE PATTERNS
# =============================================================================
# Three patterns (Martin Fowler):
#
# 1. EVENT NOTIFICATION:
#    Publisher emits a lightweight event; consumers fetch details if interested.
#    PAYLOAD: just the event type and entity ID.
#    PRO: decoupled; consumers pull only what they need.
#    CON: consumers must call back to source → temporal coupling.
#    USE: "UserCreated" event triggers welcome email service to fetch user details.
#
# 2. EVENT-CARRIED STATE TRANSFER:
#    Event contains all the data consumers need — no need to call back to source.
#    PAYLOAD: full entity snapshot.
#    PRO: fully decoupled; consumers are autonomous.
#    CON: large events; schema changes affect all consumers.
#    USE: "OrderShipped" event carries order, items, address, tracking number.
#
# 3. EVENT SOURCING:
#    Events ARE the source of truth. Current state derived by replay.
#    See L03_databases_at_scale.py for a detailed implementation.

@dataclass
class EventNotification:
    """Pattern 1: minimal event — consumers call back to fetch details."""
    event_type: str      # e.g., "UserCreated"
    entity_id: str       # e.g., user_id = "u-42"
    timestamp: float = field(default_factory=time.time)

@dataclass
class EventCarriedStateTransfer:
    """Pattern 2: self-contained event — consumers need no callbacks."""
    event_type: str
    entity_id: str
    payload: Dict[str, Any]  # full snapshot of the entity at event time
    timestamp: float = field(default_factory=time.time)


# =============================================================================
# SECTION 7: SAGA PATTERN FOR DISTRIBUTED TRANSACTIONS
# =============================================================================
# PROBLEM: an order placement spans multiple services (Inventory, Payment, Shipping).
#          A traditional 2-phase commit (2PC) across services is impractical —
#          it's slow, blocks resources, and services rarely support it.
#
# SAGA: break the distributed transaction into a sequence of local transactions,
#       each with a compensating transaction that undoes its effect on failure.
#
# TWO COORDINATION STYLES:
#
# CHOREOGRAPHY: each service listens for events and publishes its own events.
#   PRO: no central coordinator; highly decoupled; scales well.
#   CON: hard to visualise the overall workflow; debugging is complex.
#   USE: order fulfilment, hotel booking workflows.
#
# ORCHESTRATION: a central Saga Orchestrator tells each service what to do.
#   PRO: workflow is explicit and visible in one place; easier to debug.
#   CON: orchestrator becomes a centralised component (potential bottleneck/SPOF).
#   USE: payment workflows, onboarding flows requiring strict sequencing.

class SagaStep:
    """Represents one local transaction step in a saga."""

    def __init__(
        self,
        name: str,
        execute: Callable[[], bool],      # returns True = success
        compensate: Callable[[], None],   # rollback: undo this step's effect
    ):
        self.name = name
        self.execute = execute
        self.compensate = compensate


class SagaOrchestrator:
    """
    ORCHESTRATION-BASED SAGA: central orchestrator executes steps in order.
    On any failure, all previously completed steps are compensated in reverse order.
    This is the "rollback" equivalent in distributed transactions.

    PRODUCTION: implemented with a workflow engine (Temporal, AWS Step Functions,
                Conductor) that persists saga state so it survives crashes.
    """

    def __init__(self, name: str, steps: List[SagaStep]):
        self.name = name
        self.steps = steps

    def execute(self) -> bool:
        """
        Run all saga steps in order.
        On failure: compensate all completed steps in reverse order (LIFO).
        """
        completed_steps: List[SagaStep] = []  # track for rollback

        for step in self.steps:
            logger.info(f"[Saga: {self.name}] Executing step: {step.name}")
            try:
                success = step.execute()
                if success:
                    completed_steps.append(step)  # record for potential rollback
                else:
                    logger.error(f"[Saga: {self.name}] Step '{step.name}' failed — compensating")
                    self._compensate(completed_steps)
                    return False
            except Exception as e:
                logger.error(f"[Saga: {self.name}] Exception in '{step.name}': {e} — compensating")
                self._compensate(completed_steps)
                return False

        logger.info(f"[Saga: {self.name}] All steps completed successfully")
        return True

    def _compensate(self, completed_steps: List[SagaStep]):
        """Run compensation transactions in reverse order (LIFO)."""
        for step in reversed(completed_steps):  # undo most recent step first
            logger.info(f"[Saga: {self.name}] Compensating: {step.name}")
            try:
                step.compensate()
            except Exception as e:
                # Compensation failures are CRITICAL — require manual intervention
                logger.critical(f"[Saga: {self.name}] Compensation FAILED for '{step.name}': {e}")


class ChoreographySagaService(ABC):
    """
    Base for CHOREOGRAPHY-BASED SAGA participants.
    Each service listens for events, performs its local transaction,
    and emits success/failure events for other services to react to.
    """

    def __init__(self, service_name: str, event_bus: List[Dict]):
        self.service_name = service_name
        self.event_bus = event_bus  # shared list simulating Kafka topic

    def publish(self, event_type: str, payload: Dict):
        """Emit an event to the shared event bus."""
        self.event_bus.append({
            "event_type":  event_type,
            "publisher":   self.service_name,
            "payload":     payload,
            "timestamp":   time.time(),
        })

    @abstractmethod
    def handle_event(self, event: Dict):
        """Process an incoming event and publish follow-up events."""


# =============================================================================
# SECTION 8: OUTBOX PATTERN
# =============================================================================
# PROBLEM: when a service writes to its DB AND publishes a message, these are two
#          separate operations. Either can fail independently:
#          - DB succeeds, message publish fails → event is lost (state diverges)
#          - Message published, DB fails → event published but state not changed
#
# OUTBOX PATTERN: write the event to an "outbox" table in the SAME DB transaction
#                 as the business data. A separate process (relay) reads the outbox
#                 and publishes to the message broker.
#
# GUARANTEES: at-least-once delivery (relay may re-publish on crash; consumer needs idempotency).
# PRODUCTION: Debezium uses CDC (Change Data Capture) on the outbox table for the relay.

@dataclass
class OutboxEntry:
    """One row in the outbox table — stored in the same DB transaction as the business write."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    aggregate_type: str = ""     # e.g., "Order"
    aggregate_id: str = ""       # e.g., order_id
    event_type: str = ""         # e.g., "OrderPlaced"
    payload: str = ""            # JSON-serialised event payload
    published: bool = False      # relay sets this to True after publishing
    created_at: float = field(default_factory=time.time)


class OutboxRepository:
    """
    Simulates the outbox table in PostgreSQL.
    In production, written within the same transaction as the business entity.
    """

    def __init__(self):
        self._outbox: List[OutboxEntry] = []  # in-memory simulation of DB table

    def save_event_in_transaction(self, entry: OutboxEntry, business_write_fn: Callable):
        """
        Atomically: execute business write + append to outbox.
        In production, both happen within a single DB transaction (BEGIN; ... COMMIT).
        """
        business_write_fn()       # e.g., INSERT INTO orders VALUES (...)
        self._outbox.append(entry)  # INSERT INTO outbox VALUES (...) — same transaction
        logger.info(f"Outbox: saved event {entry.event_type} for {entry.aggregate_id}")

    def get_unpublished(self) -> List[OutboxEntry]:
        """Relay: fetch events not yet published to the broker."""
        return [e for e in self._outbox if not e.published]

    def mark_published(self, entry_id: str):
        """Relay: mark an outbox entry as published after successful broker write."""
        for entry in self._outbox:
            if entry.id == entry_id:
                entry.published = True


class OutboxRelay:
    """
    Background process that reads unpublished outbox entries and publishes to broker.
    Runs on a timer (e.g., every 100 ms) or triggered by DB change events (Debezium).
    """

    def __init__(self, repo: OutboxRepository, publish_fn: Callable[[OutboxEntry], None]):
        self.repo = repo
        self.publish_fn = publish_fn

    def poll_and_publish(self):
        """Read unpublished outbox entries, publish to broker, mark as published."""
        pending = self.repo.get_unpublished()
        for entry in pending:
            try:
                self.publish_fn(entry)             # publish to Kafka/RabbitMQ
                self.repo.mark_published(entry.id) # mark only after successful publish
                logger.info(f"Relay: published {entry.event_type} ({entry.id})")
            except Exception as e:
                logger.error(f"Relay: failed to publish {entry.id}: {e} — will retry")
                # do not mark as published — relay will retry on next poll


# =============================================================================
# SECTION 9: BACK-PRESSURE MECHANISMS
# =============================================================================
# BACK-PRESSURE: mechanism for a slow consumer to signal a fast producer to slow down.
# Without back-pressure: producer floods consumer → consumer crashes → messages lost.
#
# MECHANISMS:
#   1. Bounded queues: producer blocks when queue is full (synchronous back-pressure).
#   2. Credit-based flow control: consumer grants credits; producer only sends when it has credit.
#   3. Rate limiting: producer self-throttles based on consumer metrics.
#   4. Reactive Streams: standardised back-pressure protocol in Java/Scala (RxJava, Akka).
#   5. Kafka consumer lag monitoring: auto-scale consumers when lag exceeds threshold.

class BoundedQueue:
    """
    Thread-safe bounded queue implementing blocking back-pressure.
    When full, the producer blocks (or times out) instead of dropping messages.
    PRODUCTION: Java's LinkedBlockingQueue, Python's queue.Queue(maxsize=N).
    """

    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self._queue: deque = deque()
        self._lock = threading.Lock()
        self._not_full = threading.Condition(self._lock)
        self._not_empty = threading.Condition(self._lock)

    def put(self, item: Any, timeout: float = 5.0) -> bool:
        """
        Add item to queue. Blocks if full (back-pressure applied to producer).
        Returns False if timeout expires — producer should back off.
        """
        with self._not_full:
            deadline = time.monotonic() + timeout
            while len(self._queue) >= self.maxsize:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logger.warning("Queue full — back-pressure: producer must slow down")
                    return False  # producer should reduce rate or drop message
                self._not_full.wait(timeout=remaining)  # block until space is available
            self._queue.append(item)
            self._not_empty.notify_all()  # signal waiting consumers
            return True

    def get(self, timeout: float = 5.0) -> Optional[Any]:
        """Remove and return an item. Blocks if queue is empty."""
        with self._not_empty:
            deadline = time.monotonic() + timeout
            while not self._queue:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None  # timeout — no message available
                self._not_empty.wait(timeout=remaining)
            item = self._queue.popleft()
            self._not_full.notify_all()  # signal waiting producers
            return item

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._queue)


# =============================================================================
# SECTION 10: DEMO
# =============================================================================

def demo():
    print("\n" + "="*60)
    print("RABBITMQ EXCHANGE ROUTING DEMO")
    print("="*60)

    # --- Topic Exchange ---
    topic_exchange = Exchange("orders", ExchangeType.TOPIC)
    q_all_orders   = Queue("all-orders")
    q_express      = Queue("express-orders")
    q_international = Queue("international-orders")

    topic_exchange.bind(q_all_orders,      routing_key="order.#")       # all orders
    topic_exchange.bind(q_express,         routing_key="order.*.express")  # any express order
    topic_exchange.bind(q_international,   routing_key="order.international.#")

    msgs = [
        Message(routing_key="order.domestic.standard",   body={"id": 1}),
        Message(routing_key="order.domestic.express",    body={"id": 2}),
        Message(routing_key="order.international.dhl",   body={"id": 3}),
    ]
    for m in msgs:
        topic_exchange.publish(m)

    print(f"\n'all-orders' queue depth: {len(q_all_orders.messages)} (expect 3)")
    print(f"'express-orders' queue depth: {len(q_express.messages)} (expect 1)")
    print(f"'international-orders' queue depth: {len(q_international.messages)} (expect 1)")

    # --- Dead-Letter Queue ---
    print("\n" + "="*60)
    print("DEAD-LETTER QUEUE DEMO")
    print("="*60)

    main_queue = Queue("payments", dlq_name="payments-dlq")
    dlq = Queue("payments-dlq", is_dlq=True)

    msg = Message(body={"amount": 100}, max_retries=2)
    main_queue.messages.append(msg)

    attempt_count = [0]
    def always_fail(m: Message) -> bool:
        attempt_count[0] += 1
        return False  # simulate a failing payment handler

    consumer = Consumer(main_queue, always_fail, dlq=dlq)
    for _ in range(3):   # try enough times to exhaust max_retries
        consumer.process_one()

    print(f"\nMain queue after exhausting retries: {len(main_queue.messages)} messages")
    print(f"DLQ after exhausting retries: {len(dlq.messages)} messages (expect 1)")

    # --- Idempotency ---
    print("\n" + "="*60)
    print("IDEMPOTENCY KEY DEMO")
    print("="*60)

    store = IdempotencyStore()
    results = []

    def charge_payment(m: Message) -> str:
        return f"Charged ${m.body['amount']}"

    m = Message(body={"amount": 99.99})
    for i in range(3):  # simulate message delivered 3 times (at-least-once)
        result = idempotent_handler(m, store, charge_payment)
        results.append(result)
        print(f"  Attempt {i+1}: {result}")
    print("  (only charged once despite 3 deliveries)")

    # --- Saga Orchestrator ---
    print("\n" + "="*60)
    print("SAGA ORCHESTRATOR DEMO")
    print("="*60)

    inventory_reserved = [False]
    payment_charged    = [False]

    def reserve_inventory() -> bool:
        inventory_reserved[0] = True
        print("  Inventory reserved")
        return True

    def release_inventory():
        inventory_reserved[0] = False
        print("  [Compensate] Inventory released")

    def charge_card() -> bool:
        print("  Payment charging ... FAILED (card declined)")
        return False  # simulate payment failure

    def refund_card():
        print("  [Compensate] Payment refunded")

    saga = SagaOrchestrator("PlaceOrder", [
        SagaStep("ReserveInventory", reserve_inventory, release_inventory),
        SagaStep("ChargePayment",    charge_card,       refund_card),
    ])
    result = saga.execute()
    print(f"\n  Saga result: {'SUCCESS' if result else 'FAILED (compensated)'}")
    print(f"  Inventory still reserved: {inventory_reserved[0]} (expect False)")

    print("\nDemo complete.")


if __name__ == "__main__":
    demo()
