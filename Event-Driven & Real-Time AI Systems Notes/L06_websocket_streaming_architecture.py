# ============================================================
# L06: WebSocket Streaming Architecture — Real-Time Delivery to Clients
# ============================================================
# WHAT: How to expose a backend event stream (L01-L05) to actual
#       front-end/external clients via WebSockets — connection
#       lifecycle, JWT-based service-to-service auth for streaming
#       endpoints, and backpressure handling when a client can't keep up.
# WHY: Everything in L01-L05 happens SERVER-SIDE, between backend
#       systems. At some point, a real-time signal needs to reach an
#       actual user's browser/app — a dashboard updating live, a chat
#       response streaming token by token. WebSockets are the standard
#       mechanism for that last hop, and they introduce their own
#       distinct architectural concerns.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
A WEBSOCKET is a PERSISTENT, BIDIRECTIONAL connection between a client
and server, established via an HTTP "upgrade" handshake — unlike a
normal HTTP request/response (open connection, get one response, close),
a WebSocket connection stays OPEN, and either side can send messages to
the other at any time without a new request. This is what makes it
suitable for pushing real-time server-side events (L01-L05's event bus
activity, or streaming LLM tokens) to a client WITHOUT the client
needing to repeatedly poll "is there anything new yet?"

CONNECTION LIFECYCLE matters architecturally: a WebSocket server must
track WHICH client connections are subscribed to WHICH streams (e.g.
"this connection wants updates for customer_id=cust_1's dashboard"),
handle CLIENT DISCONNECTS gracefully (cleaning up subscriptions,
distinct from a slow-but-connected client), and handle RECONNECTION
(a client's network drops briefly — on reconnect, does it need to
"catch up" on missed messages, or is only "from now on" acceptable for
this use case? This connects directly to L02's JetStream replay
capability if the underlying event source supports it).

JWT SERVICE-TO-SERVICE (S2S) AUTH for a streaming endpoint has a subtlety
plain REST auth doesn't: a WebSocket connection is LONG-LIVED (potentially
open for hours), so the SAME token-expiry problem from Feature Stores &
Modern Data Lake Notes L11 (long-running kernel sessions) applies here —
a JWT with a short TTL, valid at connection time, may EXPIRE while the
connection is still open. Handling this requires either a
periodic RE-AUTHENTICATION message over the same connection, or a
deliberate connection-lifetime cap shorter than the token's TTL (forcing
periodic reconnection with a fresh token) — an unhandled expired-token
long-lived connection is a real security gap (a connection that should
no longer be authorized keeps receiving data).

BACKPRESSURE is the problem of a SLOW client (a mobile app on a poor
connection, a browser tab that's been backgrounded) not being able to
consume messages as fast as the server is producing them — without
handling this, the server's OUTBOUND buffer for that connection grows
unboundedly, risking memory exhaustion. Common mitigations: bounded
per-connection queues (drop or coalesce messages once a queue fills,
rather than growing it unboundedly), or explicit flow-control protocols
where the client acknowledges receipt before more is sent.

PRODUCTION USE CASE:
A real-time AI support-agent interface streams the agent's response
token-by-token over a WebSocket as it's generated (rather than waiting
for the full response and sending it in one HTTP response) — giving the
user immediate visual feedback that the system is working, with the
connection's JWT re-validated periodically since a single support
conversation session can genuinely last many minutes.

COMMON MISTAKES:
- Not handling client disconnection cleanup — a WebSocket server that
  doesn't detect and clean up dead/disconnected client subscriptions
  leaks memory/resources over time as the count of "zombie" tracked
  subscriptions grows.
- Issuing a long-lived, broadly-scoped JWT at WebSocket connection time
  specifically to avoid dealing with mid-connection expiry, instead of
  implementing genuine re-authentication or connection-lifetime capping
  — this is the same anti-pattern flagged in Feature Stores & Modern
  Data Lake Notes L11 for long-running kernels, now applied to streaming
  endpoints: a long-lived credential sitting in an open connection for
  hours is a real, avoidable security exposure.
- Growing a per-connection outbound message queue unboundedly for a slow
  client instead of implementing bounded queues with an explicit drop/
  coalesce policy — under real-world network conditions (mobile clients,
  intermittent connectivity), an unbounded queue for even a small number
  of persistently slow clients can exhaust server memory.
"""

import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timedelta


# ------------------------------------------------------------------
# 1. A minimal WebSocket server with subscription tracking (FastAPI-style)
# ------------------------------------------------------------------
WEBSOCKET_SERVER_EXAMPLE = textwrap.dedent("""\
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect

    app = FastAPI()
    active_connections: dict[str, WebSocket] = {}   # customer_id -> connection

    @app.websocket("/events/stream")
    async def stream_events(websocket: WebSocket):
        await websocket.accept()
        auth_message = await websocket.receive_json()
        customer_id = validate_jwt_and_extract_customer_id(auth_message["token"])
        active_connections[customer_id] = websocket

        try:
            while True:
                # In practice, this task subscribes to the event bus
                # (L01-L02) for events relevant to THIS customer, and
                # forwards matching ones over the WebSocket as they arrive.
                event = await get_next_relevant_event(customer_id)
                await websocket.send_json(event)
        except WebSocketDisconnect:
            # CRITICAL cleanup — without this, a disconnected client's
            # subscription tracking leaks indefinitely.
            del active_connections[customer_id]
""")

# ------------------------------------------------------------------
# 2. JWT re-authentication for long-lived connections
# ------------------------------------------------------------------
@dataclass
class ConnectionAuthState:
    customer_id: str
    token_expires_at: datetime
    reauth_grace_period: timedelta = timedelta(minutes=2)

    def needs_reauth(self, now: datetime) -> bool:
        return now >= (self.token_expires_at - self.reauth_grace_period)


REAUTH_PATTERN_EXAMPLE = textwrap.dedent("""\
    async def stream_with_reauth(websocket, initial_token):
        auth_state = decode_token_expiry(initial_token)

        while True:
            now = datetime.now()
            if auth_state.needs_reauth(now):
                # Send a REAUTH REQUIRED message over the SAME open
                # connection, requiring the client to send a fresh token
                # before the server continues forwarding events — this
                # is the direct analogue of Feature Stores & Modern Data
                # Lake Notes L11's TokenRefresher, applied to a
                # client-facing streaming connection instead of a
                # backend kernel session.
                await websocket.send_json({"type": "reauth_required"})
                new_token_msg = await websocket.receive_json()
                auth_state = decode_token_expiry(new_token_msg["token"])

            event = await get_next_relevant_event(auth_state.customer_id)
            await websocket.send_json(event)
""")

# ------------------------------------------------------------------
# 3. Backpressure — bounded queues with an explicit drop policy
# ------------------------------------------------------------------
class BoundedConnectionQueue:
    """
    A bounded per-connection outbound queue — protects the server from a
    single slow client causing unbounded memory growth, at the cost of
    that specific slow client missing some messages (an explicit,
    deliberate tradeoff, not an accidental resource leak).
    """

    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.queue: list[dict] = []
        self.dropped_count = 0

    def enqueue(self, message: dict):
        if len(self.queue) >= self.max_size:
            # DROP the OLDEST message to make room — a "keep most recent"
            # policy, appropriate for real-time dashboards where a stale
            # update is less useful than a fresh one; a different use
            # case (e.g. financial transaction events) might instead
            # choose to drop the connection entirely rather than silently
            # lose any message.
            self.queue.pop(0)
            self.dropped_count += 1
        self.queue.append(message)

    def drain(self) -> list[dict]:
        drained, self.queue = self.queue, []
        return drained


def backpressure_demo():
    queue = BoundedConnectionQueue(max_size=3)
    for i in range(6):
        queue.enqueue({"seq": i, "data": f"event_{i}"})
    print(f"Queue after 6 rapid messages, max_size=3: {queue.queue}")
    print(f"Dropped count: {queue.dropped_count}  (client only sees the most recent 3)")


if __name__ == "__main__":
    print(WEBSOCKET_SERVER_EXAMPLE)
    print(REAUTH_PATTERN_EXAMPLE)
    print("--- Backpressure demo ---")
    backpressure_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A real-time AI support-agent interface streams responses over WebSocket
with a periodic reauth check (a support session commonly running 10-15
minutes, longer than many short-lived access tokens' TTL) and a bounded
per-connection queue with a "keep most recent" drop policy for dashboard-
style status updates (where an intermediate status update becoming stale
is acceptable) — while the actual conversational token stream uses a
SEPARATE, unbounded-but-monitored channel, since dropping tokens from an
in-progress AI response would be a correctness bug, not an acceptable
tradeoff, illustrating that backpressure POLICY should be chosen per
message TYPE, not applied uniformly across an entire connection.
"""
