# ============================================================
# L08: Frontend-Backend Integration — REST Consumption, WebSockets, Streaming
# ============================================================
# WHAT: How a React/Vue frontend (L01-L03) actually CONSUMES a backend
#       API (FastAPI/Django/Express, L04-L05) — REST calls with proper
#       loading/error states, WebSocket connections from the frontend
#       side, and consuming STREAMING responses (Server-Sent Events)
#       specifically for real-time/AI-generated content.
# WHY: L01-L07 each covered one side of the stack in isolation. This is
#      where they connect — and the connection point (network calls,
#      real-time updates, streaming text) is where a surprising amount
#      of real frontend engineering complexity actually lives.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
CONSUMING A REST API from the frontend requires handling THREE states
EVERY network call can be in: LOADING (the request is in flight — the UI
should show SOMETHING, not appear frozen), SUCCESS (data arrived,
render it), and ERROR (the request failed — network error, a 4xx/5xx
response — the UI should show an actionable error, not silently fail or
crash). A common, genuinely important UX principle: NEVER leave the UI
in an ambiguous state where the user can't tell if something is loading,
succeeded, or failed.

WEBSOCKET CONNECTIONS from the frontend (the client side of what this
repo's Event-Driven & Real-Time AI Systems Notes L06 covers from the
SERVER side) require handling: CONNECTION LIFECYCLE (establishing,
detecting disconnection, RECONNECTING with backoff on failure — a
network blip shouldn't require the user to manually refresh the page),
and MESSAGE HANDLING (parsing incoming messages and updating UI state,
per L01's useState/useEffect pattern).

SERVER-SENT EVENTS (SSE) are the standard mechanism for STREAMING
responses from server to client over a SINGLE, LONG-LIVED HTTP
connection — critically important for AI applications specifically,
since an LLM's response is generated TOKEN BY TOKEN, and SSE lets the
frontend display each token AS IT ARRIVES (a "typing" effect) rather
than waiting for the ENTIRE response to complete before showing
anything — a meaningfully better perceived-latency experience for
exactly the kind of AI chat interface L09 builds on this foundation.
SSE is SIMPLER than a full WebSocket for this specific ONE-DIRECTIONAL
(server-to-client only) streaming use case — no need for the
bidirectional complexity a chat's OUTGOING messages (client-to-server)
would still use a normal POST request for.

PRODUCTION USE CASE:
An AI-powered search interface shows a LOADING SPINNER while the initial
search request is in flight, then SWITCHES to consuming a Server-Sent
Events stream as the AI-generated summary of results streams in token
by token, updating the displayed text incrementally — giving the user
immediate visual feedback (loading, then streaming text appearing) at
every stage, rather than one long, ambiguous wait followed by a sudden
full-response appearance.

COMMON MISTAKES:
- Not handling the ERROR state of a network request at all — a failed
  API call that's silently ignored leaves the user staring at a UI that
  never updates, with no indication anything went wrong or why.
- Establishing a WebSocket connection with NO reconnection logic — a
  brief network interruption (switching WiFi networks, a mobile
  connection blip) permanently breaks the real-time feature until the
  user manually refreshes, a poor experience a simple exponential-
  backoff reconnection strategy avoids.
- Using a full WebSocket connection for a genuinely ONE-DIRECTIONAL
  streaming need (server pushing data, client never sending anything
  back over that same connection) when Server-Sent Events would be
  simpler to implement and reason about for that specific pattern.
"""

import textwrap


# ------------------------------------------------------------------
# 1. REST consumption with proper loading/error states (React)
# ------------------------------------------------------------------
REST_CONSUMPTION_EXAMPLE = textwrap.dedent("""\
    import { useState, useEffect } from 'react';

    function AgentList() {
      const [agents, setAgents] = useState(null);
      const [loading, setLoading] = useState(true);
      const [error, setError] = useState(null);

      useEffect(() => {
        setLoading(true);
        fetch('/api/agents')
          .then(res => {
            if (!res.ok) throw new Error(`Request failed: ${res.status}`);
            return res.json();
          })
          .then(data => setAgents(data))
          .catch(err => setError(err.message))
          .finally(() => setLoading(false));
      }, []);

      // ALWAYS handle all three states explicitly — never leave the UI
      // in an ambiguous "nothing happened" state:
      if (loading) return <Spinner />;
      if (error) return <ErrorBanner message={error} />;
      return (
        <ul>{agents.map(a => <li key={a.id}>{a.name}</li>)}</ul>
      );
    }
""")

# ------------------------------------------------------------------
# 2. WebSocket connection with reconnection logic
# ------------------------------------------------------------------
WEBSOCKET_RECONNECT_EXAMPLE = textwrap.dedent("""\
    import { useEffect, useRef, useState } from 'react';

    function useReconnectingWebSocket(url) {
      const [messages, setMessages] = useState([]);
      const reconnectAttempts = useRef(0);

      useEffect(() => {
        let ws;

        function connect() {
          ws = new WebSocket(url);

          ws.onopen = () => {
            reconnectAttempts.current = 0;   // reset on successful connect
          };

          ws.onmessage = (event) => {
            setMessages(prev => [...prev, JSON.parse(event.data)]);
          };

          ws.onclose = () => {
            // EXPONENTIAL BACKOFF reconnection — avoids hammering the
            // server with reconnect attempts if it's genuinely down,
            // while still recovering automatically from a brief blip.
            const delay = Math.min(1000 * 2 ** reconnectAttempts.current, 30000);
            reconnectAttempts.current++;
            setTimeout(connect, delay);
          };
        }

        connect();
        return () => ws.close();   // cleanup on unmount (L01's pattern)
      }, [url]);

      return messages;
    }
""")

# ------------------------------------------------------------------
# 3. Server-Sent Events — consuming a streaming AI response
# ------------------------------------------------------------------
SSE_CONSUMPTION_EXAMPLE = textwrap.dedent("""\
    import { useState } from 'react';

    function StreamingResponse() {
      const [text, setText] = useState('');

      async function handleAsk(question) {
        setText('');   // clear previous response
        const response = await fetch('/api/ask', {
          method: 'POST',
          body: JSON.stringify({ question }),
          headers: { 'Content-Type': 'application/json' },
        });

        // Reading a streaming response body token-by-token — this is
        // what makes AI chat interfaces feel responsive: text APPEARS
        // incrementally, not all at once after a long wait.
        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value);
          setText(prev => prev + chunk);   // append each incoming chunk
        }
      }

      return <p>{text}</p>;
    }

    // The BACKEND side (FastAPI, this repo's FastAPI Notes L06) yields
    // chunks via a StreamingResponse as the LLM generates each token —
    # the frontend code above is what CONSUMES that stream on the other end.
""")

SSE_NATIVE_EXAMPLE = textwrap.dedent("""\
    // For a SIMPLER, standardized streaming format, the native EventSource
    // API handles Server-Sent Events (a specific, well-defined protocol
    // built on top of a streaming HTTP response) with built-in automatic
    // reconnection — no manual reconnect logic needed, unlike raw WebSockets:
    const eventSource = new EventSource('/api/notifications/stream');
    eventSource.onmessage = (event) => {
      const notification = JSON.parse(event.data);
      handleNewNotification(notification);
    };
    // EventSource automatically reconnects on connection loss, using the
    // browser's own built-in retry logic — genuinely simpler than L08's
    // manual WebSocket reconnection pattern, for this ONE-DIRECTIONAL use case.
""")


if __name__ == "__main__":
    print(REST_CONSUMPTION_EXAMPLE)
    print(WEBSOCKET_RECONNECT_EXAMPLE)
    print(SSE_CONSUMPTION_EXAMPLE)
    print(SSE_NATIVE_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
An AI research-assistant interface uses a fetch-based streaming reader
(per SSE_CONSUMPTION_EXAMPLE) to display an LLM's response token-by-
token as it's generated, a WebSocket WITH reconnection logic for a
SEPARATE live "agent status" sidebar (bidirectional — the frontend also
sends commands like "pause this agent run" over the same connection),
and standard REST calls with explicit loading/error states for
everything else (fetching conversation history, user settings) — three
DIFFERENT integration patterns, each chosen deliberately for its
specific data-flow shape rather than one pattern applied uniformly everywhere.
"""
