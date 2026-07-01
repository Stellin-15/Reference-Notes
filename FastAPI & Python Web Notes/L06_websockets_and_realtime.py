# ============================================================
# L06: WebSockets and Real-Time Communication
# ============================================================
# WHAT: Full-duplex persistent connections, SSE, long polling,
#       Redis pub/sub for multi-instance broadcast, and auth.
# WHY:  REST is request/response — useless for live chat, price
#       feeds, collaborative editing. WebSocket keeps the pipe
#       open. Redis pub/sub solves the multi-pod fan-out problem.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    HTTP is stateless and half-duplex; the client must always
    initiate. WebSocket upgrades an HTTP connection to a
    persistent, full-duplex TCP channel. The server can push
    at any time. When you scale to multiple FastAPI processes
    (multiple pods / workers), each process only knows about
    its own in-memory connections — so a message arriving on
    pod-1 cannot reach clients connected to pod-2 unless you
    broadcast through a shared bus. Redis pub/sub is that bus:
    every pod subscribes to the same Redis channel; when one
    pod publishes, all pods receive and fan out to their local
    sockets.

    SSE (Server-Sent Events) is simpler: one-way server→client
    push over plain HTTP, automatic reconnect built into the
    browser, works through any proxy. Use it for dashboards,
    activity feeds, progress bars.

    Long polling is the fallback for environments where WebSocket
    is blocked (corporate proxies). Hold the HTTP request open,
    respond when an event arrives or after ~30 s, client
    immediately re-requests.

PRODUCTION USE CASE:
    Chat service: users join rooms, messages broadcast to the
    room, delivered to every connected instance via Redis.
    Disconnects clean up the room membership. Message history
    stored in a Redis list (LPUSH / LRANGE). Product price feed:
    SSE from market data service — browser EventSource handles
    reconnection transparently.

COMMON MISTAKES:
    1. Forgetting try/except WebSocketDisconnect — unhandled
       disconnect leaves a stale WebSocket in the room set
       forever, broadcast raises RuntimeError on a closed socket.
    2. No ping/pong keepalive — load balancers idle-close TCP
       after 60-180 s of silence; zombie sockets accumulate.
    3. Putting auth token in WebSocket headers — the browser
       WebSocket API only sends cookies and the Upgrade headers;
       custom headers are silently dropped. Use ?token= query
       param or validate in the first message payload.
    4. Using a plain asyncio.Queue for broadcast in a multi-
       worker (multi-process) setup — queues are in-process;
       they don't cross process boundaries.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

import redis.asyncio as aioredis
from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis client — shared across the process, created once at startup
# ---------------------------------------------------------------------------
redis_client: aioredis.Redis  # module-level; initialized in lifespan


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: open resources before serving, close after."""
    global redis_client
    # Decode responses=True so we get str back, not bytes
    redis_client = aioredis.from_url(
        "redis://localhost:6379", decode_responses=True
    )
    # Start the Redis subscriber loop in the background
    asyncio.create_task(redis_subscriber_loop())
    yield  # ← server runs while we're here
    await redis_client.aclose()


app = FastAPI(lifespan=lifespan)


# ===========================================================================
# CONNECTION MANAGER
# Room-aware, in-process registry of live WebSocket connections.
# Each FastAPI instance has its own; Redis glues instances together.
# ===========================================================================
class ConnectionManager:
    def __init__(self) -> None:
        # Global set of every active WebSocket (for broadcast-all)
        self.active: set[WebSocket] = set()
        # Room registry: room_id → set of WebSockets in that room
        self.rooms: dict[str, set[WebSocket]] = {}

    async def connect(self, ws: WebSocket, room_id: str) -> None:
        """Accept the WebSocket handshake and register in a room."""
        await ws.accept()
        self.active.add(ws)
        # setdefault avoids a KeyError on first join
        self.rooms.setdefault(room_id, set()).add(ws)
        logger.info("Client joined room=%s", room_id)

    def disconnect(self, ws: WebSocket, room_id: str) -> None:
        """Remove WebSocket from all registries (no await needed — no IO)."""
        self.active.discard(ws)
        room = self.rooms.get(room_id)
        if room:
            room.discard(ws)
            if not room:  # prune empty room to avoid memory leak
                del self.rooms[room_id]

    async def send_personal(self, message: str, ws: WebSocket) -> None:
        """Send a text frame to a single connection."""
        await ws.send_text(message)

    async def broadcast_room(self, message: str, room_id: str) -> None:
        """Fan-out to every socket in a room on THIS instance."""
        dead: set[WebSocket] = set()
        for ws in self.rooms.get(room_id, set()):
            try:
                await ws.send_text(message)
            except Exception:
                # Socket died between our check and the send — mark for removal
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws, room_id)


manager = ConnectionManager()


# ===========================================================================
# REDIS PUB/SUB BRIDGE
# When a message is published to channel "chat:{room_id}" by any pod,
# every pod's subscriber receives it and fans out to local sockets.
# This is the key to horizontal scaling of WebSocket servers.
# ===========================================================================
CHANNEL_PREFIX = "chat:"  # Redis channel namespace


async def redis_subscriber_loop() -> None:
    """
    Long-lived coroutine: subscribe to all chat channels and relay
    incoming Redis messages to local WebSocket connections.
    Runs for the lifetime of the process.
    """
    pubsub = redis_client.pubsub()
    # psubscribe uses glob — subscribes to chat:* (all rooms)
    await pubsub.psubscribe(f"{CHANNEL_PREFIX}*")
    logger.info("Redis pub/sub subscriber started")

    async for raw in pubsub.listen():
        # pubsub.listen() yields {"type": ..., "channel": ..., "data": ...}
        if raw["type"] != "pmessage":
            continue  # skip subscribe-confirmation frames
        # channel looks like b"chat:room42" → strip prefix to get room_id
        channel: str = raw["channel"]
        room_id = channel.removeprefix(CHANNEL_PREFIX)
        data: str = raw["data"]
        # Fan out to local sockets; other pods handle their own
        await manager.broadcast_room(data, room_id)


async def publish_to_room(room_id: str, message: dict) -> None:
    """
    Publish a message to a Redis channel so ALL pods broadcast it.
    Call this instead of manager.broadcast_room() when you want
    cross-pod delivery.
    """
    await redis_client.publish(
        f"{CHANNEL_PREFIX}{room_id}",
        json.dumps(message),  # serialize once; every pod deserializes
    )


# ===========================================================================
# KEEPALIVE — prevents zombie connections
# Load balancers (AWS ALB, nginx) close idle TCP connections after
# 60–180 s. Send a ping every 30 s; if the client is gone, the
# send raises an exception and we clean up.
# ===========================================================================
async def keepalive(ws: WebSocket, room_id: str) -> None:
    """Ping the client every 30 s to keep the TCP connection alive."""
    try:
        while True:
            await asyncio.sleep(30)
            # WebSocket protocol-level ping (not a text frame)
            await ws.send_text(json.dumps({"type": "ping"}))
    except Exception:
        # Client disconnected or errored; clean up
        manager.disconnect(ws, room_id)


# ===========================================================================
# WEBSOCKET ENDPOINT — Chat room
# ===========================================================================
@app.websocket("/ws/{room_id}")
async def websocket_room(
    websocket: WebSocket,
    room_id: str,
    # Token in query param because browser WebSocket API cannot set headers
    token: Optional[str] = Query(default=None),
):
    """
    Chat room WebSocket endpoint.
    URL: ws://host/ws/room42?token=<jwt>

    Flow:
      1. Validate token (reject before accept to avoid partial upgrade)
      2. Accept + register
      3. Spawn keepalive task
      4. Read loop: receive message, publish to Redis (fan-out to all pods)
      5. On disconnect: cancel keepalive, deregister
    """
    # --- 1. Auth before accept --- #
    if not token or not _validate_token(token):
        # Close with 4001 (custom code in 4000-4999 range for app errors)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # --- 2. Accept and register in room --- #
    await manager.connect(websocket, room_id)

    # --- 3. Keepalive task (cancel it when the loop ends) --- #
    ping_task = asyncio.create_task(keepalive(websocket, room_id))

    # Notify the room that someone joined (via Redis so all pods see it)
    await publish_to_room(room_id, {"type": "system", "text": "User joined"})

    try:
        # --- 4. Receive loop --- #
        while True:
            # receive_text() suspends here until a frame arrives
            raw = await websocket.receive_text()
            payload = json.loads(raw)

            if payload.get("type") == "pong":
                continue  # client acknowledging our ping — ignore

            # Build canonical message and push to Redis → all pods
            msg = {
                "type": "message",
                "room": room_id,
                "text": payload.get("text", ""),
            }
            # Persist last 100 messages in a Redis list (LPUSH + LTRIM)
            await redis_client.lpush(f"history:{room_id}", json.dumps(msg))
            await redis_client.ltrim(f"history:{room_id}", 0, 99)

            await publish_to_room(room_id, msg)

    except WebSocketDisconnect:
        # --- 5. Cleanup --- #
        # This is the normal exit path — client closed the tab / navigated away
        ping_task.cancel()
        manager.disconnect(websocket, room_id)
        await publish_to_room(room_id, {"type": "system", "text": "User left"})
        logger.info("Client disconnected from room=%s", room_id)


def _validate_token(token: str) -> bool:
    """Stub: validate JWT or opaque session token. Replace with real logic."""
    return token == "secret"  # noqa: S105 (demo only)


# ===========================================================================
# SERVER-SENT EVENTS (SSE)
# Simpler than WebSocket for one-way server→client push.
# Browser uses: const es = new EventSource("/stream/prices");
#               es.onmessage = e => console.log(JSON.parse(e.data));
# Automatic reconnect with Last-Event-ID is built into the browser.
# ===========================================================================
@app.get("/stream/prices")
async def price_stream():
    """
    SSE endpoint for live price updates.
    Returns a chunked HTTP response with Content-Type: text/event-stream.
    Each chunk must follow the SSE wire format: "data: ...\n\n"
    """
    async def event_generator():
        """Yield SSE frames; subscribe to Redis for price events."""
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("prices")
        try:
            async for raw in pubsub.listen():
                if raw["type"] != "message":
                    continue
                # SSE format: "data: <payload>\n\n"
                # Two newlines terminate the event; one newline separates fields
                yield f"data: {raw['data']}\n\n"
        finally:
            await pubsub.unsubscribe("prices")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            # Disable nginx/CDN buffering — must reach client immediately
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )


# ===========================================================================
# LONG POLLING
# Holds the request open until an event arrives or 30 s elapse.
# Works through ALL HTTP proxies (no protocol upgrade needed).
# Use as WebSocket fallback in hostile network environments.
# ===========================================================================
_long_poll_events: dict[str, asyncio.Event] = {}
_long_poll_data: dict[str, str] = {}


@app.get("/poll/{client_id}")
async def long_poll(client_id: str):
    """
    Long-polling endpoint. Client calls this, request hangs until
    an event is available (up to 30 s), then immediately re-calls.
    """
    event = _long_poll_events.setdefault(client_id, asyncio.Event())
    try:
        # wait_for raises asyncio.TimeoutError after 30 s — return empty
        await asyncio.wait_for(event.wait(), timeout=30.0)
        data = _long_poll_data.pop(client_id, None)
        event.clear()  # reset for the next poll cycle
        return {"data": data}
    except asyncio.TimeoutError:
        return {"data": None}  # client re-polls immediately


@app.post("/push/{client_id}")
async def push_event(client_id: str, payload: dict):
    """Internal: push data to a waiting long-poll client."""
    _long_poll_data[client_id] = json.dumps(payload)
    event = _long_poll_events.get(client_id)
    if event:
        event.set()  # unblocks the waiting long_poll coroutine
    return {"ok": True}


# ===========================================================================
# HISTORY ENDPOINT — return last N messages from Redis list
# ===========================================================================
@app.get("/rooms/{room_id}/history")
async def room_history(room_id: str, limit: int = 20):
    """Fetch the last `limit` messages stored in Redis for a room."""
    # LRANGE 0 limit-1: Redis list is newest-first (LPUSH)
    raw_messages = await redis_client.lrange(f"history:{room_id}", 0, limit - 1)
    return {"messages": [json.loads(m) for m in raw_messages]}
