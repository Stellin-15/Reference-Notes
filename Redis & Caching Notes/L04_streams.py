# ============================================================
# L04: Redis Streams
# ============================================================
# WHAT: Redis Streams — a persistent, ordered log of messages
#       with consumer groups, acknowledgment, and replay support.
# WHY:  Streams solve the durability gap in Pub/Sub: messages
#       survive subscriber downtime, can be replayed, and multiple
#       independent consumer groups can each process every message.
#       This makes Redis Streams a lightweight Kafka alternative
#       for moderate throughput requirements (< ~100K msgs/s).
# LEVEL: Intermediate
# ============================================================
"""
CONCEPT OVERVIEW:
    A Redis Stream is an append-only log. Each entry has an
    auto-generated ID in the form <millisecondsTimestamp>-<sequence>,
    e.g. "1704067200000-0". Entries are maps of field-value pairs.

    Consumer Groups allow multiple logical consumers to independently
    process the same stream:
      - Within a group, each message is delivered to exactly one
        consumer (competing consumers / load balancing).
      - Between groups, every group sees every message independently.
        This is the key difference from a plain queue.

    Acknowledgment (XACK) marks a message as processed. Unacknowledged
    messages remain in the PEL (Pending Entry List). If a consumer
    crashes without acknowledging, XPENDING reveals the stuck messages
    and XCLAIM lets another consumer take them over.

    Dead Letter Queue (DLQ): after N failed delivery attempts, a
    message should be moved to a separate DLQ stream for human review
    rather than retried forever.

    Streams vs Pub/Sub:
      Pub/Sub  → ephemeral, fire-and-forget, no persistence, no groups
      Streams  → persistent, acknowledgment, consumer groups, replayable
    Use Pub/Sub for live notifications; Streams for reliable event pipelines.

PRODUCTION USE CASE:
    Order processing pipeline at an e-commerce company:
      - Order service XADDs an "order_placed" event to the stream.
      - Fulfillment group: XREADGROUP → pick and pack → XACK.
      - Analytics group: XREADGROUP → write to data warehouse → XACK.
      Both groups process independently at their own pace.
      XCLAIM handles worker crashes (order gets stuck in PEL → another
      worker claims it after 30s idle time).
      MAXLEN ~ 1000000 keeps the stream from growing unbounded.
      A DLQ stream receives any order that failed 3 delivery attempts.

COMMON MISTAKES:
    1. Not using MKSTREAM on XGROUP CREATE — fails if the stream does
       not exist yet. Always pass MKSTREAM.
    2. Using "0" instead of ">" in XREADGROUP — "0" re-reads the PEL
       (unacknowledged messages), not new messages. Use ">" for new.
    3. Never calling XACK — all messages pile up in the PEL, XPENDING
       grows without bound and memory fills up.
    4. Forgetting to XCLAIM stuck messages — a crashed consumer leaves
       its messages unprocessed indefinitely.
    5. Not trimming the stream — an untrimmed stream grows forever.
       Use MAXLEN ~ (approximate trim) on XADD or schedule XTRIM.
    6. No DLQ strategy — a poison-pill message (one that always fails
       processing) will be retried forever, blocking the consumer.
    7. Blocking XREADGROUP with a timeout but ignoring the empty
       result — the consumer busy-loops and wastes CPU.
"""

import time
import uuid
import random
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


# ============================================================
# MINIMAL STREAM SIMULATION
# ============================================================
# In production every method maps to the redis-py call shown in
# the docstring. The simulation uses Python dicts and lists to
# model the stream state without a real Redis server.
# ============================================================

@dataclass
class StreamEntry:
    """One entry in a Redis Stream. ID format: <ms>-<seq>"""
    entry_id: str
    data: dict[str, str]


@dataclass
class PendingEntry:
    """An entry delivered to a consumer but not yet acknowledged."""
    entry_id: str
    consumer: str
    delivered_at: float
    delivery_count: int = 1


class FakeStream:
    """
    In-memory simulation of a Redis Stream with consumer group support.
    All method signatures mirror the redis-py API.
    """

    def __init__(self, name: str):
        self.name = name
        self._entries: list[StreamEntry] = []          # The ordered log
        self._groups: dict[str, dict] = {}             # group_name -> group state
        self._seq_counter: int = 0                     # Monotonic sequence
        self._lock = threading.Lock()

    # ----------------------------------------------------------
    # XADD: Append an entry to the stream
    # redis-py: r.xadd("mystream", {"field": "value"}, maxlen=100000, approximate=True)
    # ----------------------------------------------------------
    def xadd(
        self,
        data: dict[str, str],
        entry_id: str = "*",           # "*" = auto-generate
        maxlen: Optional[int] = None,  # Trim to approximate length
    ) -> str:
        """
        XADD stream [MAXLEN ~ maxlen] * field1 val1 field2 val2 ...
        Returns the auto-generated entry ID.

        The ID format <ms>-<seq> guarantees strict ordering.
        Using "*" lets Redis generate the ID (always prefer this).
        """
        with self._lock:
            ms = int(time.time() * 1000)
            self._seq_counter += 1
            new_id = f"{ms}-{self._seq_counter}" if entry_id == "*" else entry_id
            self._entries.append(StreamEntry(new_id, dict(data)))

            # MAXLEN ~ trim: approximate trim keeps it fast (O(1) amortized)
            if maxlen and len(self._entries) > maxlen:
                trim_count = len(self._entries) - maxlen
                self._entries = self._entries[trim_count:]   # Remove oldest

            return new_id

    # ----------------------------------------------------------
    # XLEN: Number of entries in the stream
    # redis-py: r.xlen("mystream")
    # ----------------------------------------------------------
    def xlen(self) -> int:
        """XLEN stream  →  number of entries"""
        return len(self._entries)

    # ----------------------------------------------------------
    # XRANGE: Read entries by ID range
    # redis-py: r.xrange("mystream", min="-", max="+")
    #           "-" = smallest possible ID, "+" = largest possible ID
    # ----------------------------------------------------------
    def xrange(self, min_id: str = "-", max_id: str = "+") -> list[StreamEntry]:
        """
        XRANGE stream min max
        Returns entries in ascending ID order.
        Use for replay: XRANGE mystream <last_processed_id> +
        """
        with self._lock:
            if min_id == "-" and max_id == "+":
                return list(self._entries)
            result = []
            for e in self._entries:
                if (min_id == "-" or e.entry_id >= min_id) and \
                   (max_id == "+" or e.entry_id <= max_id):
                    result.append(e)
            return result

    # ----------------------------------------------------------
    # XREAD: Read new entries without a consumer group
    # redis-py: r.xread({"mystream": "0-0"}, count=10, block=1000)
    #   "0-0"   = start from the very beginning
    #   "$"     = start from entries added after XREAD call
    #   block=N = block up to N milliseconds waiting for new entries
    # ----------------------------------------------------------
    def xread(self, last_id: str = "0-0", count: int = 10) -> list[StreamEntry]:
        """
        XREAD COUNT count STREAMS stream last_id
        Stateless read — the application must track last_id itself.
        For stateful consumption with group semantics, use XREADGROUP.
        """
        with self._lock:
            result = []
            for e in self._entries:
                if e.entry_id > last_id:
                    result.append(e)
                if len(result) >= count:
                    break
            return result

    # ----------------------------------------------------------
    # XGROUP CREATE: Create a consumer group
    # redis-py: r.xgroup_create("mystream", "mygroup", "$", mkstream=True)
    #   "$" = start from new messages (ignore history)
    #   "0" = start from beginning (process all existing messages)
    #   mkstream=True = create the stream if it doesn't exist yet
    # ----------------------------------------------------------
    def xgroup_create(self, group: str, start_id: str = "$", mkstream: bool = True):
        """
        XGROUP CREATE stream group start_id [MKSTREAM]
        MKSTREAM is critical in production — without it the command
        fails if the stream hasn't been written to yet.
        """
        with self._lock:
            if group in self._groups:
                return   # Group already exists — idempotent

            # last_delivered_id tracks which messages have been delivered
            if start_id == "$":
                # Start from NOW: only process future messages
                last_id = self._entries[-1].entry_id if self._entries else "0-0"
            else:
                last_id = start_id  # "0" = replay from the beginning

            self._groups[group] = {
                "last_delivered_id": last_id,
                "pel": {},              # Pending Entry List: entry_id -> PendingEntry
                "consumers": set(),
            }
            logging.info("Created consumer group '%s' on stream '%s'", group, self.name)

    # ----------------------------------------------------------
    # XREADGROUP: Read new messages as part of a consumer group
    # redis-py:
    #   r.xreadgroup("mygroup", "consumer1", {"mystream": ">"}, count=10, block=1000)
    #   ">" = deliver new undelivered messages (normal operation)
    #   "0" = re-deliver my own unacknowledged messages from the PEL
    # ----------------------------------------------------------
    def xreadgroup(
        self,
        group: str,
        consumer: str,
        count: int = 10,
        start_id: str = ">",   # ">" = new messages; "0" = pending re-delivery
    ) -> list[StreamEntry]:
        """
        XREADGROUP GROUP group consumer COUNT count STREAMS stream >
        Each message is delivered to exactly ONE consumer in the group.
        The message stays in the PEL until XACK is called.
        """
        with self._lock:
            if group not in self._groups:
                raise ValueError(f"Group '{group}' does not exist on stream '{self.name}'")

            g = self._groups[group]
            g["consumers"].add(consumer)
            result = []

            if start_id == ">":
                # Deliver new messages not yet seen by this group
                for e in self._entries:
                    if e.entry_id > g["last_delivered_id"]:
                        g["pel"][e.entry_id] = PendingEntry(
                            entry_id=e.entry_id,
                            consumer=consumer,
                            delivered_at=time.time(),
                        )
                        result.append(e)
                        if len(result) >= count:
                            break
                if result:
                    g["last_delivered_id"] = result[-1].entry_id
            else:
                # Re-deliver messages already in the PEL for this consumer
                for entry_id, pending in g["pel"].items():
                    if pending.consumer == consumer:
                        entry = next((e for e in self._entries if e.entry_id == entry_id), None)
                        if entry:
                            pending.delivery_count += 1
                            result.append(entry)
                        if len(result) >= count:
                            break

            return result

    # ----------------------------------------------------------
    # XACK: Acknowledge successful processing
    # redis-py: r.xack("mystream", "mygroup", entry_id)
    # ----------------------------------------------------------
    def xack(self, group: str, *entry_ids: str) -> int:
        """
        XACK stream group entry_id [entry_id ...]
        Removes the message from the PEL. MUST be called after
        successful processing to prevent the message from being
        re-delivered by XCLAIM.
        Returns the number of acknowledged messages.
        """
        with self._lock:
            if group not in self._groups:
                return 0
            pel = self._groups[group]["pel"]
            count = 0
            for eid in entry_ids:
                if eid in pel:
                    del pel[eid]
                    count += 1
            return count

    # ----------------------------------------------------------
    # XPENDING: Inspect the Pending Entry List
    # redis-py: r.xpending_range("mystream", "mygroup", min="-", max="+", count=10)
    # ----------------------------------------------------------
    def xpending(self, group: str, count: int = 10) -> list[PendingEntry]:
        """
        XPENDING stream group - + count
        Returns unacknowledged messages. Use this to detect stuck consumers
        in a monitoring loop: if PEL grows, a consumer has crashed.
        """
        with self._lock:
            if group not in self._groups:
                return []
            return list(self._groups[group]["pel"].values())[:count]

    # ----------------------------------------------------------
    # XCLAIM: Transfer ownership of a stuck message
    # redis-py: r.xclaim("mystream", "mygroup", "consumer2", min_idle_time, [entry_id])
    # ----------------------------------------------------------
    def xclaim(
        self,
        group: str,
        new_consumer: str,
        min_idle_ms: int,
        entry_ids: list[str],
    ) -> list[StreamEntry]:
        """
        XCLAIM stream group new_consumer min-idle-time entry_id [entry_id ...]
        Takes ownership of messages that have been idle for > min_idle_ms.
        Used by a watchdog process to recover messages from crashed consumers.
        """
        with self._lock:
            if group not in self._groups:
                return []
            pel = self._groups[group]["pel"]
            now = time.time()
            claimed = []

            for eid in entry_ids:
                pending = pel.get(eid)
                if not pending:
                    continue
                idle_ms = (now - pending.delivered_at) * 1000
                if idle_ms >= min_idle_ms:
                    # Reassign ownership
                    pending.consumer = new_consumer
                    pending.delivered_at = now
                    pending.delivery_count += 1
                    entry = next((e for e in self._entries if e.entry_id == eid), None)
                    if entry:
                        claimed.append(entry)
                    logging.warning(
                        "XCLAIM: transferred %s to %s (was idle %.0fms, attempt #%d)",
                        eid, new_consumer, idle_ms, pending.delivery_count,
                    )

            return claimed

    # ----------------------------------------------------------
    # XTRIM: Trim the stream to at most maxlen entries
    # redis-py: r.xtrim("mystream", maxlen=100000, approximate=True)
    # ----------------------------------------------------------
    def xtrim(self, maxlen: int, approximate: bool = True) -> int:
        """
        XTRIM stream MAXLEN [~] maxlen
        The ~ (approximate) flag is strongly recommended in production.
        Exact trimming (without ~) is O(N) and can cause latency spikes.
        Approximate trimming is O(1) amortized — Redis trims in bulk.
        """
        with self._lock:
            if len(self._entries) <= maxlen:
                return 0
            trim_count = len(self._entries) - maxlen
            self._entries = self._entries[trim_count:]
            return trim_count

    # ----------------------------------------------------------
    # XINFO: Monitoring and introspection
    # redis-py: r.xinfo_stream("mystream")
    #           r.xinfo_groups("mystream")
    #           r.xinfo_consumers("mystream", "mygroup")
    # ----------------------------------------------------------
    def xinfo_stream(self) -> dict:
        """XINFO STREAM stream  →  metadata about the stream"""
        with self._lock:
            return {
                "length": len(self._entries),
                "first_entry": self._entries[0].entry_id if self._entries else None,
                "last_entry":  self._entries[-1].entry_id if self._entries else None,
                "groups":      len(self._groups),
            }

    def xinfo_groups(self) -> list[dict]:
        """XINFO GROUPS stream  →  info about each consumer group"""
        with self._lock:
            return [
                {
                    "name":               g_name,
                    "consumers":          len(g_state["consumers"]),
                    "pending":            len(g_state["pel"]),
                    "last_delivered_id":  g_state["last_delivered_id"],
                }
                for g_name, g_state in self._groups.items()
            ]


# ============================================================
# DEAD LETTER QUEUE (DLQ) PATTERN
# ============================================================
# A message that consistently fails processing should NOT be
# retried forever. After MAX_RETRIES attempts:
#   1. XADD the original payload + error info to a DLQ stream.
#   2. XACK the original message to remove it from the PEL.
#   3. Alert on-call / send to Slack for human review.
#
# This pattern prevents a poison-pill message from blocking
# all other messages behind it in the consumer.
# ============================================================

MAX_RETRIES = 3    # Move to DLQ after this many failed delivery attempts

def process_with_dlq(
    entry: StreamEntry,
    pending: PendingEntry,
    main_stream: FakeStream,
    dlq_stream: FakeStream,
    group: str,
    consumer: str,
    process_fn,
) -> bool:
    """
    Process an entry. If it has exceeded MAX_RETRIES, move it to the DLQ
    instead of retrying. Always XACK the original so the PEL stays clean.

    Returns True if processed successfully, False if sent to DLQ.
    """
    if pending.delivery_count > MAX_RETRIES:
        # Message has failed too many times — route to DLQ
        dlq_payload = {
            "original_id":    entry.entry_id,
            "stream":         main_stream.name,
            "group":          group,
            "consumer":       consumer,
            "attempts":       str(pending.delivery_count),
            "error":          "exceeded max retry attempts",
            **entry.data,      # Preserve original payload fields
        }
        dlq_id = dlq_stream.xadd(dlq_payload)
        main_stream.xack(group, entry.entry_id)
        logging.error(
            "DLQ: message %s moved to DLQ as %s after %d attempts",
            entry.entry_id, dlq_id, pending.delivery_count,
        )
        return False

    # Normal processing attempt
    try:
        process_fn(entry.data)
        main_stream.xack(group, entry.entry_id)
        return True
    except Exception as exc:
        # Do NOT XACK on failure — leave in PEL for XCLAIM / retry
        logging.warning("Processing failed for %s: %s", entry.entry_id, exc)
        return False


# ============================================================
# CONSUMER WORKER SIMULATION
# ============================================================
# Models a real consumer: XREADGROUP loop → process → XACK.
# Each worker runs in its own thread (in production, its own process
# or container). The consumer group distributes messages across them.
# ============================================================

class OrderConsumer(threading.Thread):
    """
    A single consumer in a consumer group. Runs a XREADGROUP loop
    indefinitely, processing messages and ACKing on success.
    """

    def __init__(
        self,
        stream: FakeStream,
        dlq: FakeStream,
        group: str,
        consumer_id: str,
        process_fn,
        poll_interval: float = 0.1,
        max_messages: int = 50,   # Stop after this many for demo purposes
    ):
        super().__init__(daemon=True, name=consumer_id)
        self.stream = stream
        self.dlq = dlq
        self.group = group
        self.consumer_id = consumer_id
        self.process_fn = process_fn
        self.poll_interval = poll_interval
        self.max_messages = max_messages
        self.processed = 0
        self.failed = 0
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        """
        Main consumer loop.
        In production: replace polling with blocking XREADGROUP
        by passing block=<timeout_ms> to redis-py.

        redis-py:
            entries = r.xreadgroup(
                self.group, self.consumer_id,
                {self.stream.name: ">"},
                count=10, block=2000    # Block up to 2 seconds for new messages
            )
        """
        logging.info("[%s] Consumer started", self.consumer_id)

        while not self._stop_event.is_set() and self.processed < self.max_messages:
            entries = self.stream.xreadgroup(self.group, self.consumer_id, count=5)

            if not entries:
                # No new messages — short sleep before next poll
                # In production: use block=<ms> instead of sleep
                time.sleep(self.poll_interval)
                continue

            for entry in entries:
                # Retrieve PEL state for DLQ decision
                pending_list = [
                    p for p in self.stream.xpending(self.group)
                    if p.entry_id == entry.entry_id
                ]
                pending = pending_list[0] if pending_list else PendingEntry(
                    entry.entry_id, self.consumer_id, time.time()
                )

                ok = process_with_dlq(
                    entry, pending, self.stream, self.dlq,
                    self.group, self.consumer_id, self.process_fn,
                )
                if ok:
                    self.processed += 1
                else:
                    self.failed += 1

        logging.info(
            "[%s] Consumer finished: %d processed, %d failed/DLQ",
            self.consumer_id, self.processed, self.failed,
        )


# ============================================================
# WATCHDOG: CLAIM STUCK MESSAGES FROM CRASHED CONSUMERS
# ============================================================
# A separate watchdog process polls XPENDING periodically.
# Any message idle for > CLAIM_TIMEOUT_MS is claimed by the
# watchdog and re-queued for processing by a healthy consumer.
# ============================================================

CLAIM_TIMEOUT_MS = 30_000   # Claim messages idle > 30 seconds


def watchdog_reclaim(
    stream: FakeStream,
    group: str,
    rescue_consumer: str = "watchdog",
    min_idle_ms: int = CLAIM_TIMEOUT_MS,
):
    """
    Scan the PEL for messages that have been idle too long and
    claim them on behalf of the rescue consumer.

    In production this runs as a separate low-priority service or
    a scheduled task (e.g., every 60 seconds).

    redis-py:
        pending = r.xpending_range(stream_name, group, "-", "+", count=100)
        for p in pending:
            if p["time_since_delivered"] > min_idle_ms:
                r.xclaim(stream_name, group, rescue_consumer, min_idle_ms, [p["message_id"]])
    """
    pending = stream.xpending(group, count=100)
    stuck = [p for p in pending if (time.time() - p.delivered_at) * 1000 >= min_idle_ms]

    if not stuck:
        return []

    stuck_ids = [p.entry_id for p in stuck]
    claimed = stream.xclaim(group, rescue_consumer, min_idle_ms, stuck_ids)
    logging.warning(
        "Watchdog claimed %d stuck messages for group '%s'",
        len(claimed), group,
    )
    return claimed


# ============================================================
# ORDER PROCESSING PIPELINE — PRODUCTION PATTERN
# ============================================================
# Two consumer groups read the same "orders" stream independently:
#   - "fulfillment" group: picks, packs, ships the order
#   - "analytics" group:   writes order data to the warehouse
#
# Each group processes at its own pace. Neither blocks the other.
# A DLQ stream receives orders that fail MAX_RETRIES times.
# ============================================================

def fulfillment_process(data: dict):
    """Simulate fulfillment work (pick → pack → label)."""
    order_id = data.get("order_id", "?")
    # Simulate occasional transient failures (10% failure rate)
    if random.random() < 0.10:
        raise RuntimeError(f"Fulfillment system unavailable for order {order_id}")
    logging.debug("[fulfillment] Processed order %s", order_id)


def analytics_process(data: dict):
    """Simulate writing order data to an analytics warehouse."""
    order_id = data.get("order_id", "?")
    logging.debug("[analytics]   Recorded order %s", order_id)


# ============================================================
# DEMO
# ============================================================

def run_demo():
    print("\n=== Redis Streams: Order Processing Pipeline Demo ===\n")

    # Create the streams
    order_stream = FakeStream("orders")
    dlq_stream   = FakeStream("orders:dlq")

    # Create consumer groups
    # "0" = start from beginning so both groups see all seeded orders
    order_stream.xgroup_create("fulfillment", start_id="0", mkstream=True)
    order_stream.xgroup_create("analytics",   start_id="0", mkstream=True)

    # Produce 20 order events
    print("Producing 20 order events...")
    for i in range(1, 21):
        entry_id = order_stream.xadd({
            "order_id":    f"ORD-{i:04d}",
            "customer_id": f"CUST-{random.randint(1, 100)}",
            "total":       f"{random.uniform(9.99, 499.99):.2f}",
            "items":       str(random.randint(1, 5)),
            "region":      random.choice(["US-EAST", "EU-WEST", "APAC"]),
        })
        logging.debug("Produced order event: %s", entry_id)

    print(f"Stream length after production: {order_stream.xlen()}")
    info = order_stream.xinfo_stream()
    print(f"Stream info: {info}\n")

    # Start two fulfillment workers and two analytics workers
    fulfillment_workers = [
        OrderConsumer(order_stream, dlq_stream, "fulfillment",
                      f"fulfillment-{i}", fulfillment_process, max_messages=15)
        for i in range(1, 3)
    ]
    analytics_workers = [
        OrderConsumer(order_stream, dlq_stream, "analytics",
                      f"analytics-{i}", analytics_process, max_messages=15)
        for i in range(1, 3)
    ]

    all_workers = fulfillment_workers + analytics_workers
    for w in all_workers:
        w.start()

    # Let workers run
    time.sleep(1.0)

    # Stop workers
    for w in all_workers:
        w.stop()
    for w in all_workers:
        w.join(timeout=3.0)

    print("\n=== Consumer Group Status ===")
    for g in order_stream.xinfo_groups():
        print(f"  Group: {g['name']:<15s}  "
              f"pending={g['pending']}  "
              f"consumers={g['consumers']}  "
              f"last_delivered={g['last_delivered_id']}")

    print("\n=== Worker Results ===")
    for w in fulfillment_workers + analytics_workers:
        print(f"  {w.consumer_id:<20s}  processed={w.processed}  failed={w.failed}")

    print(f"\n=== DLQ Status ===")
    print(f"  Messages in DLQ stream: {dlq_stream.xlen()}")
    if dlq_stream.xlen() > 0:
        dlq_entries = dlq_stream.xrange()
        for e in dlq_entries[:3]:   # Show first 3 DLQ entries
            print(f"  DLQ entry {e.entry_id}: order={e.data.get('order_id')} "
                  f"attempts={e.data.get('attempts')}")

    print("\n=== Stream Trimming ===")
    before_len = order_stream.xlen()
    trimmed = order_stream.xtrim(maxlen=10)
    after_len = order_stream.xlen()
    print(f"  Before trim: {before_len} entries")
    print(f"  Trimmed:     {trimmed} entries removed")
    print(f"  After trim:  {after_len} entries")

    print("\n=== XRANGE Replay Demo ===")
    # Replay all remaining entries (e.g., after a new analytics group is added)
    entries = order_stream.xrange()
    print(f"  Replaying {len(entries)} entries from current stream head:")
    for e in entries[:3]:
        print(f"    [{e.entry_id}] order={e.data.get('order_id')} "
              f"region={e.data.get('region')}")
    if len(entries) > 3:
        print(f"    ... and {len(entries) - 3} more")

    print("\n=== Watchdog XCLAIM Demo ===")
    # Simulate a stuck message by creating a fake old PEL entry
    # (In real usage the watchdog would find this after 30s idle time)
    stuck_stream = FakeStream("test:stuck")
    stuck_stream.xgroup_create("workers", start_id="0")
    stuck_id = stuck_stream.xadd({"job": "resize_image", "url": "s3://bucket/img.jpg"})
    # Deliver to consumer1 (simulates it crashing without ACKing)
    stuck_stream.xreadgroup("workers", "consumer1", count=1)
    # Manually age the pending entry for demo (set delivered_at to 35s ago)
    stuck_stream._groups["workers"]["pel"][stuck_id].delivered_at = time.time() - 35

    reclaimed = watchdog_reclaim(stuck_stream, "workers", min_idle_ms=30_000)
    print(f"  Watchdog reclaimed {len(reclaimed)} stuck message(s)")
    if reclaimed:
        print(f"  Reclaimed: {reclaimed[0].entry_id} → job={reclaimed[0].data.get('job')}")

    print("\n=== Streams vs Pub/Sub Summary ===")
    comparison = [
        ("Persistence",   "Yes — survives restarts",     "No — lost if no subscriber"),
        ("Consumer Groups","Yes — load balanced",          "No — all subscribers get all msgs"),
        ("Acknowledgment", "Yes — XACK",                  "No — fire and forget"),
        ("Replay",        "Yes — XRANGE from any ID",     "No — past messages gone"),
        ("Use Case",      "Order events, pipelines",      "Live notifications, cache signals"),
    ]
    print(f"\n  {'Property':<20s}  {'Streams':<35s}  {'Pub/Sub'}")
    print(f"  {'-'*20}  {'-'*35}  {'-'*35}")
    for prop, streams_val, pubsub_val in comparison:
        print(f"  {prop:<20s}  {streams_val:<35s}  {pubsub_val}")


if __name__ == "__main__":
    run_demo()
