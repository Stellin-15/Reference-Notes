# =============================================================================
# WHAT: Redis Pub/Sub — Publisher/Subscriber messaging, pattern subscriptions,
#       keyspace notifications, and fan-out architecture
# WHY:  Pub/Sub decouples producers from consumers. Any number of subscribers
#       receive messages published to a channel without the publisher knowing
#       who (or how many) are listening. Perfect for real-time broadcast.
# LEVEL: Intermediate → Advanced
# =============================================================================
#
# CONCEPT OVERVIEW
# ----------------
# Redis Pub/Sub is a fire-and-forget messaging primitive. A publisher sends a
# message to a CHANNEL. Every client currently subscribed to that channel
# receives a copy. Messages are NOT stored — if no subscriber is listening when
# a message is published, the message is lost forever.
#
# Key commands:
#   SUBSCRIBE   channel [channel ...]   — listen to exact channel names
#   UNSUBSCRIBE [channel ...]           — stop listening (all if omitted)
#   PUBLISH     channel message         — send message; returns subscriber count
#   PSUBSCRIBE  pattern [pattern ...]   — glob-style pattern subscription
#   PUNSUBSCRIBE [pattern ...]          — stop pattern subscription
#   PUBSUB CHANNELS [pattern]           — list active channels
#   PUBSUB NUMSUB [channel ...]         — subscriber count per channel
#   PUBSUB NUMPAT                       — number of active pattern subscriptions
#
# PRODUCTION USE CASE
# -------------------
# Scenario: Multi-region e-commerce platform
#   - Order service publishes to "orders:new" when an order is placed
#   - Inventory service subscribes to decrement stock counts
#   - Notification service subscribes to send email/SMS
#   - Analytics service subscribes to update dashboards
#   All three receive the same message simultaneously — fan-out at zero cost.
#
# COMMON MISTAKES
# ---------------
# 1. Expecting message persistence: Pub/Sub has NONE. Use Streams (L04) if you
#    need replay, backpressure, or consumer groups.
# 2. Blocking the main thread: pubsub.listen() is a blocking generator. Always
#    run it in a background thread (shown below).
# 3. Using a subscribed connection for regular commands: once you call
#    SUBSCRIBE, that connection enters subscribe mode — you cannot issue GET,
#    SET, etc. on it. Use a separate connection for regular work.
# 4. Ignoring connection drops: the background thread needs reconnect logic;
#    a broken TCP connection silently stops delivering messages.
# 5. Pattern explosion: PSUBSCRIBE news:* on a busy instance with thousands of
#    channels is O(N) per published message — can spike CPU.
# =============================================================================

import redis
import threading
import time
import json
import logging
import signal
import sys
from typing import Callable, Optional, Dict, Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s: %(message)s"
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection setup — Pub/Sub uses a dedicated connection object, not a pool
# ---------------------------------------------------------------------------

# Standard client for publishing and admin commands
r = redis.Redis(
    host="localhost",
    port=6379,
    db=0,
    decode_responses=True,   # return str, not bytes
    socket_connect_timeout=5,
    socket_timeout=5,
)

# ---------------------------------------------------------------------------
# SECTION 1: Basic SUBSCRIBE / PUBLISH
# ---------------------------------------------------------------------------

def basic_publish_example():
    """
    Demonstrate PUBLISH from the publisher side.
    PUBLISH returns the number of clients that received the message.
    A return value of 0 means nobody was listening — message is gone.
    """
    channel = "chat:general"
    message = json.dumps({          # serialize payload to JSON string
        "user": "alice",
        "text": "Hello, world!",
        "ts": time.time(),
    })

    # PUBLISH is a simple O(N) operation where N = subscriber + pattern count
    receiver_count = r.publish(channel, message)
    log.info("Published to '%s', received by %d subscriber(s)", channel, receiver_count)
    return receiver_count


def basic_subscribe_example(channels: list, handler: Callable, run_seconds: float = 10):
    """
    Subscribe to exact channel names and process messages for a limited time.
    In production the loop runs indefinitely; we add a timeout for the demo.

    :param channels:    list of channel name strings
    :param handler:     callable(channel, data) invoked for each message
    :param run_seconds: how long to listen before unsubscribing
    """
    # Create a PubSub object — this borrows a connection from the pool
    # and holds it exclusively for subscribe/listen
    pubsub = r.pubsub(ignore_subscribe_messages=True)
    # ignore_subscribe_messages=True suppresses the confirmation messages
    # Redis sends when SUBSCRIBE/UNSUBSCRIBE succeeds — less noise in handler

    pubsub.subscribe(*channels)     # send SUBSCRIBE for each channel
    log.info("Subscribed to channels: %s", channels)

    deadline = time.time() + run_seconds
    for message in pubsub.listen():
        # message is a dict: {"type": "message", "channel": "...", "data": "..."}
        if message["type"] == "message":
            handler(message["channel"], message["data"])

        if time.time() >= deadline:
            break   # exit the blocking loop

    pubsub.unsubscribe()            # send UNSUBSCRIBE for all channels
    pubsub.close()                  # release the underlying connection
    log.info("Unsubscribed and closed")


# ---------------------------------------------------------------------------
# SECTION 2: Background thread listener (production pattern)
# ---------------------------------------------------------------------------

class RedisPubSubListener:
    """
    Production-ready Pub/Sub listener that runs in a daemon background thread.

    Why a background thread?
      - pubsub.listen() blocks indefinitely waiting for the next message.
      - Running it in a thread lets the main application stay responsive.
      - The thread is daemon=True so it dies when the main process exits.

    Reconnect logic:
      - Network drops or Redis restarts will raise a ConnectionError.
      - The run loop catches this and reconnects with exponential backoff.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        channels: list = None,
        patterns: list = None,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 30.0,
    ):
        self._r = redis_client
        self._channels = channels or []
        self._patterns = patterns or []
        self._reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        self._handlers: Dict[str, Callable] = {}   # channel/pattern → handler
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._pubsub: Optional[redis.client.PubSub] = None

    def register_handler(self, channel_or_pattern: str, handler: Callable):
        """Map a channel name or pattern to a handler function."""
        self._handlers[channel_or_pattern] = handler

    def _dispatch(self, message: dict):
        """Route an incoming message to the correct handler."""
        channel = message.get("channel", "")
        data = message.get("data", "")

        # Try exact channel match first, then fall back to registered patterns
        handler = self._handlers.get(channel)
        if handler is None:
            # Check pattern handlers (message type is "pmessage" for patterns)
            pattern = message.get("pattern", "")
            handler = self._handlers.get(pattern)

        if handler:
            try:
                handler(channel, data)
            except Exception:
                log.exception("Handler raised for channel '%s'", channel)
        else:
            log.debug("No handler for channel '%s'", channel)

    def _subscribe_all(self, pubsub: redis.client.PubSub):
        """Issue SUBSCRIBE and PSUBSCRIBE for all registered channels."""
        if self._channels:
            pubsub.subscribe(*self._channels)
        if self._patterns:
            pubsub.psubscribe(*self._patterns)   # PSUBSCRIBE for glob patterns

    def _run(self):
        """Main loop — reconnects automatically on connection failure."""
        delay = self._reconnect_delay

        while self._running:
            try:
                self._pubsub = self._r.pubsub(ignore_subscribe_messages=True)
                self._subscribe_all(self._pubsub)
                delay = self._reconnect_delay   # reset backoff on success
                log.info("PubSub listener connected")

                for message in self._pubsub.listen():
                    if not self._running:
                        break
                    msg_type = message.get("type", "")
                    if msg_type in ("message", "pmessage"):
                        self._dispatch(message)

            except redis.ConnectionError as exc:
                if not self._running:
                    break
                log.warning("PubSub connection lost (%s). Reconnecting in %.1fs", exc, delay)
                time.sleep(delay)
                delay = min(delay * 2, self._max_reconnect_delay)  # exponential backoff

            except Exception:
                log.exception("Unexpected error in PubSub listener")
                time.sleep(delay)

            finally:
                if self._pubsub:
                    try:
                        self._pubsub.close()
                    except Exception:
                        pass

    def start(self):
        """Start the background listener thread."""
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            name="PubSubListener",
            daemon=True,            # daemon thread exits when main thread exits
        )
        self._thread.start()
        log.info("PubSub listener thread started")

    def stop(self):
        """Gracefully stop the listener thread."""
        self._running = False
        if self._pubsub:
            try:
                self._pubsub.unsubscribe()  # wake the blocking listen() call
                self._pubsub.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=5)
        log.info("PubSub listener stopped")


# ---------------------------------------------------------------------------
# SECTION 3: Pattern subscriptions (PSUBSCRIBE)
# ---------------------------------------------------------------------------

def pattern_subscription_demo():
    """
    PSUBSCRIBE accepts glob-style patterns:
      ?     matches exactly one character
      *     matches any number of characters
      [ae]  matches 'a' or 'e'

    Use case: subscribe to ALL chat rooms with a single PSUBSCRIBE chat:*
    instead of subscribing to each room individually.

    Caveat: every PUBLISH to ANY channel is checked against ALL active patterns
    — O(P) per publish where P = number of pattern subscriptions. Keep P small.
    """
    pubsub = r.pubsub(ignore_subscribe_messages=True)

    # Subscribe to all channels matching "orders:*"
    pubsub.psubscribe("orders:*")
    log.info("Pattern subscribed to orders:*")

    # In a real app this would be a background thread
    # Here we listen briefly to show message type differences
    deadline = time.time() + 5
    for message in pubsub.listen():
        if time.time() >= deadline:
            break

        if message["type"] == "pmessage":
            # pmessage has an extra "pattern" key showing which pattern matched
            log.info(
                "Pattern=%s  Channel=%s  Data=%s",
                message["pattern"],
                message["channel"],
                message["data"],
            )

    pubsub.punsubscribe("orders:*")    # PUNSUBSCRIBE to remove the pattern
    pubsub.close()


# ---------------------------------------------------------------------------
# SECTION 4: Keyspace notifications — subscribe to Redis internal events
# ---------------------------------------------------------------------------
#
# Redis can publish notifications for internal events:
#   K  — keyspace events  (__keyspace@<db>__:<key>)
#   E  — keyevent events  (__keyevent@<db>__:<event>)
#   g  — generic commands (DEL, EXPIRE, RENAME …)
#   $  — string commands
#   l  — list commands
#   s  — set commands
#   z  — sorted set commands
#   h  — hash commands
#   x  — expired events (keys that just expired)
#   d  — module key type events
#   t  — stream commands
#   A  — alias for "g$lszxdt"
#
# Example: to receive notifications when any key expires:
#   CONFIG SET notify-keyspace-events "Ex"
#   PSUBSCRIBE __keyevent@0__:expired
# ---------------------------------------------------------------------------

def enable_keyspace_notifications(events: str = "Ex"):
    """
    Enable keyspace notifications at runtime.

    :param events: event flags string, e.g. "Ex" = generic + expired
    WARNING: Keyspace notifications add CPU overhead because Redis must publish
    an event for EVERY matching operation. Enable only the flags you need.
    """
    # CONFIG SET changes the running config — no restart required
    r.config_set("notify-keyspace-events", events)
    log.info("Keyspace notifications enabled: %s", events)


def ttl_expiry_listener(db: int = 0, run_seconds: float = 30):
    """
    Listen for key expiry events — fires when a key's TTL reaches zero.

    Practical use case: session expiry → auto-logout user, invalidate cache
    entry in other layers, trigger cleanup jobs.

    Channel: __keyevent@<db>__:expired
      - message["channel"] = "__keyevent@0__:expired"
      - message["data"]    = the KEY that just expired (not its former value)

    IMPORTANT: You get the key name, NOT the value — the value is gone by the
    time Redis publishes the event. If you need the value, use a shadow key or
    Streams instead.
    """
    enable_keyspace_notifications("Ex")

    pubsub = r.pubsub(ignore_subscribe_messages=True)
    expired_channel = f"__keyevent@{db}__:expired"
    pubsub.subscribe(expired_channel)
    log.info("Listening for expiry events on db %d", db)

    deadline = time.time() + run_seconds
    for message in pubsub.listen():
        if time.time() >= deadline:
            break
        if message["type"] == "message":
            expired_key = message["data"]
            log.info("Key expired: %s", expired_key)
            # Trigger downstream action here, e.g.:
            # invalidate_l1_cache(expired_key)
            # notify_user_session_ended(expired_key)

    pubsub.unsubscribe()
    pubsub.close()


# ---------------------------------------------------------------------------
# SECTION 5: Practical patterns
# ---------------------------------------------------------------------------

class ChatRoom:
    """
    Simple chat room backed by Redis Pub/Sub.

    Fan-out: when alice publishes to "chat:lobby", every connected user
    (regardless of server instance) instantly receives the message.
    This is the canonical Pub/Sub use case.

    Limitation: users who join AFTER a message was sent never see it.
    For message history, combine with a Redis List or Stream for recent msgs.
    """

    def __init__(self, redis_client: redis.Redis, room: str, username: str):
        self._r = redis_client
        self._channel = f"chat:{room}"      # e.g. "chat:lobby"
        self._username = username
        self._listener = RedisPubSubListener(redis_client, channels=[self._channel])
        self._listener.register_handler(self._channel, self._on_message)

    def _on_message(self, channel: str, raw: str):
        """Callback invoked for every message received on the room channel."""
        try:
            payload = json.loads(raw)       # deserialize JSON payload
            print(f"[{payload['user']}] {payload['text']}")
        except (json.JSONDecodeError, KeyError) as exc:
            log.warning("Malformed message on %s: %s (%s)", channel, raw, exc)

    def connect(self):
        self._listener.start()
        self.send(f"{self._username} joined the room")

    def send(self, text: str):
        payload = json.dumps({
            "user": self._username,
            "text": text,
            "ts": time.time(),
        })
        self._r.publish(self._channel, payload)

    def disconnect(self):
        self.send(f"{self._username} left the room")
        self._listener.stop()


def cache_invalidation_broadcast(cache_key: str):
    """
    Broadcast a cache invalidation signal to all application servers.

    Problem: In a multi-server setup, server A updates a DB record and
    invalidates its local L1 cache. But servers B and C still serve stale
    data from THEIR L1 caches.

    Solution: PUBLISH to "cache:invalidate" so all servers clear their local
    copy of the key. Each server runs a subscriber that listens on this channel
    and calls its local cache's delete() on receipt.
    """
    channel = "cache:invalidate"
    r.publish(channel, cache_key)
    log.info("Broadcast invalidation for key: %s", cache_key)


def live_notification_fan_out(user_ids: list, event: dict):
    """
    Push a real-time notification to multiple users simultaneously.

    Each user has a personal channel "notifications:<user_id>".
    Their WebSocket/SSE connection subscribes to that channel.
    This function publishes to each user's channel.

    For broadcasting to ALL users, use a single "notifications:broadcast"
    channel — one PUBLISH reaches everyone.
    """
    payload = json.dumps(event)
    pipeline = r.pipeline(transaction=False)    # use pipeline for efficiency
    for uid in user_ids:
        channel = f"notifications:{uid}"
        pipeline.publish(channel, payload)      # queue each PUBLISH

    results = pipeline.execute()                # send all in one round-trip
    log.info(
        "Notified %d user(s), received by totals: %s",
        len(user_ids),
        results,
    )


# ---------------------------------------------------------------------------
# SECTION 6: Introspection — PUBSUB commands
# ---------------------------------------------------------------------------

def pubsub_introspection():
    """
    Admin commands to inspect the Pub/Sub state of the server.
    Useful in dashboards, health checks, and debugging.
    """
    # PUBSUB CHANNELS — list all active channels with at least one subscriber
    # Optional glob pattern to filter results
    active_channels = r.pubsub_channels("*")
    log.info("Active channels: %s", active_channels)

    # PUBSUB NUMSUB — subscriber count for specific channels
    if active_channels:
        counts = r.pubsub_numsub(*active_channels)
        # Returns dict {channel: count}
        log.info("Subscriber counts: %s", counts)

    # PUBSUB NUMPAT — total number of active PSUBSCRIBE patterns
    pattern_count = r.pubsub_numpat()
    log.info("Active pattern subscriptions: %d", pattern_count)


# ---------------------------------------------------------------------------
# SECTION 7: Comparison — Pub/Sub vs Streams vs Lists for messaging
# ---------------------------------------------------------------------------
#
# ┌─────────────────────┬────────────────────┬──────────────────┬────────────────────┐
# │ Feature             │ Pub/Sub            │ Streams (L04)    │ Lists (BLPOP)      │
# ├─────────────────────┼────────────────────┼──────────────────┼────────────────────┤
# │ Message persistence │ NONE (fire&forget) │ Yes (log-based)  │ Yes (until popped) │
# │ Fan-out             │ Yes (N consumers)  │ Consumer groups  │ No (1 consumer)    │
# │ Replay / history    │ No                 │ Yes (by ID)      │ No                 │
# │ Backpressure        │ No                 │ MAXLEN trimming  │ Bounded list       │
# │ Acknowledgement     │ No                 │ XACK             │ No                 │
# │ Late subscribers    │ Miss old msgs      │ Catch up via ID  │ Depends on timing  │
# │ Consumer groups     │ No                 │ Yes              │ No                 │
# │ Latency             │ Lowest (~0.1ms)    │ Very low (~0.2ms)│ Low (~0.5ms)       │
# │ Use when            │ Real-time, lossy   │ Reliable queue   │ Simple task queue  │
# │                     │ broadcast OK       │ exactly-once     │ single consumer    │
# └─────────────────────┴────────────────────┴──────────────────┴────────────────────┘
#
# Decision guide:
#   "I need real-time broadcast, can tolerate loss"  → Pub/Sub
#   "I need guaranteed delivery + consumer groups"   → Streams
#   "I need a simple FIFO queue, one consumer"       → List + BLPOP
#
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# SECTION 8: Graceful shutdown with signal handling
# ---------------------------------------------------------------------------

_listener_instance: Optional[RedisPubSubListener] = None

def _handle_shutdown(signum, frame):
    """SIGINT / SIGTERM handler — stop the listener cleanly."""
    log.info("Shutdown signal received")
    if _listener_instance:
        _listener_instance.stop()
    sys.exit(0)


def run_production_subscriber():
    """
    Entry point for a long-running subscriber process.
    Registers signal handlers so CTRL-C / systemd stop() work cleanly.
    """
    global _listener_instance

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    listener = RedisPubSubListener(
        redis_client=r,
        channels=["orders:new", "cache:invalidate"],
        patterns=["notifications:*"],
    )

    # Register per-channel handlers
    def on_new_order(channel: str, data: str):
        order = json.loads(data)
        log.info("New order: %s", order.get("order_id"))

    def on_cache_invalidate(channel: str, data: str):
        log.info("Cache invalidate: %s", data)
        # local_cache.delete(data)

    def on_notification(channel: str, data: str):
        user_id = channel.split(":")[-1]   # extract user ID from channel name
        log.info("Notification for user %s: %s", user_id, data)

    listener.register_handler("orders:new", on_new_order)
    listener.register_handler("cache:invalidate", on_cache_invalidate)
    listener.register_handler("notifications:*", on_notification)

    _listener_instance = listener
    listener.start()

    # Keep the main thread alive — the listener runs in the background thread
    log.info("Subscriber running. Press Ctrl+C to stop.")
    while True:
        time.sleep(1)


# ---------------------------------------------------------------------------
# SECTION 9: Quick smoke test
# ---------------------------------------------------------------------------

def smoke_test():
    """
    Minimal end-to-end test: start a subscriber, publish a message, verify receipt.
    Run this to confirm your Redis instance and redis-py install are working.
    """
    received = []

    def handler(channel: str, data: str):
        received.append((channel, data))

    listener = RedisPubSubListener(r, channels=["test:smoke"])
    listener.register_handler("test:smoke", handler)
    listener.start()

    time.sleep(0.2)                         # allow subscribe to complete

    r.publish("test:smoke", "ping")
    time.sleep(0.3)                         # allow message to be delivered

    listener.stop()

    assert len(received) == 1, f"Expected 1 message, got {len(received)}"
    assert received[0] == ("test:smoke", "ping"), f"Unexpected: {received[0]}"
    log.info("Smoke test PASSED: %s", received)


if __name__ == "__main__":
    smoke_test()
    # To run the long-lived subscriber process instead:
    # run_production_subscriber()
