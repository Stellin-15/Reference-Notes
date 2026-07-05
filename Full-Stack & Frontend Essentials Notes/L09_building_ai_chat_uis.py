# ============================================================
# L09: Building AI Chat UIs — Streaming, Optimistic Updates, Tool-Call Display
# ============================================================
# WHAT: The specific UI patterns real AI chat/agent interfaces need
#       beyond a generic chat app — optimistic message rendering,
#       displaying an agent's intermediate reasoning/tool calls (not
#       just its final answer), and handling the genuinely different
#       states an AI response can be in (streaming, tool-calling, done, errored).
# WHY: L01-L08 built the general frontend/integration toolkit. This
#      lesson applies it SPECIFICALLY to the AI chat/agent interface
#      pattern that's become one of the most common real frontend
#      engineering tasks — directly consuming the agent systems this
#      repo's Agentic AI & RAG Notes domain builds on the backend.
# LEVEL: Advanced (capstone-adjacent)
# ============================================================

"""
CONCEPT OVERVIEW:
OPTIMISTIC UPDATES render the USER'S OWN message IMMEDIATELY upon
sending, BEFORE the backend has confirmed receipt — the alternative
(waiting for a server round-trip before showing the user's own message)
introduces a perceptible, unnecessary delay for something that will
almost always succeed. This requires a REVERT strategy for the rare
case the send actually fails (marking the message as "failed to send,"
with a retry option) — the UI optimistically ASSUMES success but must
gracefully HANDLE the exception.

AGENT INTERMEDIATE STATE DISPLAY is what distinguishes a genuine AGENT
interface from a simple CHATBOT interface: this repo's Agentic AI & RAG
Notes L12 covered the agent LOOP (Thought -> Action -> Observation) — a
well-designed agent UI SURFACES this intermediate reasoning to the user
(e.g. "Searching the knowledge base...", "Calling the refund API...")
rather than showing ONLY a final answer after an opaque, possibly
lengthy delay. This serves both a UX purpose (the user understands
what's happening, reducing perceived wait time and building trust) and
a DEBUGGING purpose (a user or developer can see WHERE in the agent's
process something went wrong, directly connecting to this repo's
Agentic AI & RAG Notes L23's observability/tracing coverage, now surfaced
end-user-facing rather than only in a backend trace viewer).

RESPONSE STATE MODELING: a real AI response is NOT simply "loading" or
"done" (L08's basic REST pattern) — it moves through genuinely distinct
states: STREAMING (tokens arriving), possibly PAUSED FOR A TOOL CALL
(the agent is executing a tool, no new text tokens arriving during that
window), RESUMING (text continues after the tool result), and finally
COMPLETE or ERRORED. Modeling these states EXPLICITLY (rather than a
generic boolean `isLoading`) lets the UI render each phase
appropriately — a "thinking" indicator during a tool call is a
meaningfully different UI state than "generating text," even though
BOTH might naively map to "loading" in a less carefully modeled interface.

PRODUCTION USE CASE:
A customer-support AI agent interface shows the user's message
immediately (optimistic update), then displays "Looking up your order
details..." while the agent's backend executes an order-lookup tool
call (this repo's Agentic AI & RAG Notes L21's tool-use pattern,
visible end-user-facing), followed by the agent's streamed final
response — a user staring at a generic spinner for the ENTIRE duration
(order lookup + response generation combined) would reasonably assume
the system is frozen or broken; the phase-by-phase status display
communicates genuine progress throughout.

COMMON MISTAKES:
- Showing ONLY a generic loading spinner for an agent's ENTIRE
  multi-step process (tool calls, reasoning, generation combined) —
  users have no way to distinguish "still thinking, this is normal" from
  "this looks frozen, something's wrong," a real trust/UX cost for
  agent interactions that can genuinely take many seconds across multiple steps.
- Implementing optimistic message rendering WITHOUT a failure-handling/
  retry path — if the optimistic assumption of success is wrong (a
  real network failure), the UI must gracefully show this and let the
  user retry, not silently lose the message or leave it in permanent limbo.
- Modeling agent response state as a single boolean (`isLoading`)
  instead of an explicit set of named states (streaming, tool-calling,
  complete, errored) — this makes it structurally difficult to render
  the DIFFERENT UI treatments each actual state deserves.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Optimistic message rendering with failure handling
# ------------------------------------------------------------------
OPTIMISTIC_UPDATE_EXAMPLE = textwrap.dedent("""\
    import { useState } from 'react';

    function ChatInput({ onMessageSent }) {
      const [messages, setMessages] = useState([]);

      async function sendMessage(text) {
        const tempId = crypto.randomUUID();
        // OPTIMISTIC: render the message IMMEDIATELY, marked "sending"
        setMessages(prev => [...prev, { id: tempId, text, status: 'sending' }]);

        try {
          const response = await fetch('/api/messages', {
            method: 'POST',
            body: JSON.stringify({ text }),
          });
          if (!response.ok) throw new Error('Send failed');
          const saved = await response.json();

          // Success: replace the temp message with the CONFIRMED one
          setMessages(prev => prev.map(m =>
            m.id === tempId ? { ...saved, status: 'sent' } : m
          ));
        } catch {
          // FAILURE: mark the message as failed, offering retry — do
          // NOT silently remove it or leave it stuck as "sending" forever.
          setMessages(prev => prev.map(m =>
            m.id === tempId ? { ...m, status: 'failed' } : m
          ));
        }
      }

      return (
        <div>
          {messages.map(m => (
            <div key={m.id} className={`message message--${m.status}`}>
              {m.text}
              {m.status === 'failed' && <button onClick={() => sendMessage(m.text)}>Retry</button>}
            </div>
          ))}
        </div>
      );
    }
""")

# ------------------------------------------------------------------
# 2. Explicit response state modeling — beyond a boolean isLoading
# ------------------------------------------------------------------
RESPONSE_STATE_MODEL_EXAMPLE = textwrap.dedent("""\
    // An explicit, named state model — NOT a single boolean — lets the
    // UI render each distinct PHASE of an agent's response appropriately.
    const ResponseState = {
      IDLE: 'idle',
      STREAMING_TEXT: 'streaming_text',
      CALLING_TOOL: 'calling_tool',     // a DISTINCT state from streaming text
      COMPLETE: 'complete',
      ERROR: 'error',
    };

    function AgentResponse({ conversationId }) {
      const [state, setState] = useState(ResponseState.IDLE);
      const [text, setText] = useState('');
      const [currentTool, setCurrentTool] = useState(null);

      // (streaming connection setup per L08's SSE pattern, dispatching
      // to setState/setText/setCurrentTool based on each incoming event's type)

      if (state === ResponseState.CALLING_TOOL) {
        return <ToolCallIndicator tool={currentTool} />;   // e.g. "Looking up order..."
      }
      if (state === ResponseState.STREAMING_TEXT) {
        return <StreamingText text={text} showCursor={true} />;   // a "typing" cursor effect
      }
      if (state === ResponseState.ERROR) {
        return <ErrorMessage retry={() => retryRequest(conversationId)} />;
      }
      return <StreamingText text={text} showCursor={false} />;   // COMPLETE state
    }
""")

# ------------------------------------------------------------------
# 3. Displaying agent tool-call/reasoning trace to the user
# ------------------------------------------------------------------
TOOL_CALL_DISPLAY_EXAMPLE = textwrap.dedent("""\
    // The backend (Agentic AI & RAG Notes L21's ReAct loop) emits
    // structured events over the SSE/WebSocket stream (L08) describing
    // each step, not just the final text — the frontend renders these
    // as an inline, collapsible "reasoning trace":

    function AgentStepIndicator({ step }) {
      switch (step.type) {
        case 'thought':
          return <div className="step step--thought">🤔 {step.content}</div>;
        case 'tool_call':
          return <div className="step step--tool">🔧 Calling {step.toolName}...</div>;
        case 'tool_result':
          return <div className="step step--result">✓ Got result from {step.toolName}</div>;
        case 'final_answer':
          return <div className="step step--answer">{step.content}</div>;
        default:
          return null;
      }
    }

    // Users can see EXACTLY what the agent is doing at each moment —
    // both a genuine UX improvement (perceived responsiveness, trust)
    // and a debugging aid (a user reporting "it gave a wrong answer"
    // can point to the SPECIFIC step that went wrong).
""")


if __name__ == "__main__":
    print(OPTIMISTIC_UPDATE_EXAMPLE)
    print(RESPONSE_STATE_MODEL_EXAMPLE)
    print(TOOL_CALL_DISPLAY_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A customer-support AI agent's chat UI displays the user's question
optimistically, then a live sequence of status indicators ("Searching
knowledge base...", "Checking order status...", "Drafting response...")
as the backend's agent loop (Agentic AI & RAG Notes L12) progresses
through its actual Thought/Action/Observation steps, finally streaming
the answer token-by-token — user research on this interface found
perceived wait-time satisfaction improved substantially compared to an
earlier version showing only a generic spinner for the SAME actual
backend latency, purely from making the agent's real progress visible.
"""
