# ============================================================
# L01: React Fundamentals — Components, JSX, Hooks
# ============================================================
# WHAT: React's core mental model — building UIs from COMPONENTS, JSX
#       syntax, and the two most important hooks (useState, useEffect)
#       that let function components hold state and perform side effects.
# WHY: Every other domain in this repo is backend/infra/ML — this is
#      the entry point into the FRONTEND half of a full-stack AI
#      product: the actual chat interfaces, dashboards, and agent UIs
#      that consume the APIs/streams the rest of this repo builds.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
React's central idea: a UI is a TREE OF COMPONENTS, each a function that
takes PROPS (inputs, passed down from a parent) and returns a
description of what should be rendered (JSX — an XML-like syntax that
compiles to plain JavaScript function calls). Components are meant to be
COMPOSABLE and REUSABLE — a `Button` component used in ten different
places should behave consistently everywhere, driven purely by the
props it receives.

JSX looks like HTML embedded in JavaScript, but it's actually SYNTACTIC
SUGAR for `React.createElement()` calls — `<div>{name}</div>` compiles
to `React.createElement('div', null, name)`. This matters for
understanding why JSX has rules HTML doesn't (e.g. `className` instead
of `class`, since `class` is a reserved JavaScript keyword) — it's
JavaScript with an HTML-like syntax, not HTML with embedded JavaScript.

`useState` is the hook giving a FUNCTION component the ability to hold
STATE that PERSISTS across re-renders and, when UPDATED, triggers React
to RE-RENDER the component with the new value. This is fundamentally
different from a plain JavaScript variable inside the function — a
plain variable resets to its initial value on every render; `useState`'s
value is preserved by React itself across renders, specifically tied to
THIS component instance.

`useEffect` is the hook for SIDE EFFECTS — anything that reaches outside
React's own rendering (fetching data from an API, subscribing to a
WebSocket, manually manipulating the DOM) — running AFTER React has
updated the DOM for the current render. Its DEPENDENCY ARRAY (the second
argument) controls WHEN it re-runs: an empty array `[]` means "run once,
after the initial render only" (commonly used for one-time data fetching);
omitting the array entirely means "run after EVERY render" (rarely what
you actually want, and a common source of accidental infinite loops if
the effect itself triggers a state update); a populated array `[value]`
means "re-run only when `value` changes between renders."

PRODUCTION USE CASE:
A chat interface component (directly relevant to L09's AI chat UI
lesson) uses `useState` to hold the current list of messages, and
`useEffect` with an empty dependency array to establish a WebSocket
connection (this repo's Event-Driven & Real-Time AI Systems Notes L06
covers the SERVER side of this exact connection) exactly once when the
component mounts, updating the messages state as new messages arrive
over that connection.

COMMON MISTAKES:
- Mutating state DIRECTLY (e.g. `messages.push(newMessage)`) instead of
  using the state-updater function with a NEW array/object
  (`setMessages([...messages, newMessage])`) — React detects state
  changes by REFERENCE comparison for objects/arrays; mutating in place
  doesn't change the reference, so React may not re-render at all,
  producing a UI that silently fails to update.
- Omitting a value from `useEffect`'s dependency array that the effect
  actually USES — this causes the effect to reference a STALE (outdated)
  value from whenever it was last set up, a classic and confusing React
  bug commonly called the "stale closure" problem.
- Fetching data or subscribing to something WITHOUT `useEffect` (directly
  in the component body) — this re-runs the side effect on EVERY
  render, not just when actually needed, often causing runaway API
  calls or duplicate subscriptions.
"""

import textwrap


# ------------------------------------------------------------------
# 1. A minimal component — props and JSX
# ------------------------------------------------------------------
BASIC_COMPONENT_EXAMPLE = textwrap.dedent("""\
    // A component is just a function returning JSX. Props are the
    // function's ARGUMENT — data passed DOWN from whoever renders this component.
    function UserCard({ name, role }) {
      return (
        <div className="user-card">
          <h3>{name}</h3>
          <p>{role}</p>
        </div>
      );
    }

    // Usage — a parent component renders this, passing specific props:
    function App() {
      return (
        <div>
          <UserCard name="Priya" role="Incident Commander" />
          <UserCard name="Sam" role="Technical Lead" />
        </div>
      );
    }
""")

# ------------------------------------------------------------------
# 2. useState — component-local state persisting across renders
# ------------------------------------------------------------------
USESTATE_EXAMPLE = textwrap.dedent("""\
    import { useState } from 'react';

    function Counter() {
      // useState returns [currentValue, updaterFunction] — `count`
      // PERSISTS across re-renders; calling setCount TRIGGERS a re-render.
      const [count, setCount] = useState(0);   // 0 is the INITIAL value

      return (
        <div>
          <p>Count: {count}</p>
          <button onClick={() => setCount(count + 1)}>Increment</button>
        </div>
      );
    }

    // WRONG: mutating state directly doesn't trigger a re-render
    // count = count + 1;   // React never sees this change

    // For state derived from the PREVIOUS state, use the FUNCTIONAL
    // updater form to avoid stale-value bugs when updates queue up:
    setCount(prevCount => prevCount + 1);
""")

# ------------------------------------------------------------------
# 3. useEffect — side effects, with a dependency array
# ------------------------------------------------------------------
USEEFFECT_EXAMPLE = textwrap.dedent("""\
    import { useState, useEffect } from 'react';

    function ChatWindow({ conversationId }) {
      const [messages, setMessages] = useState([]);

      useEffect(() => {
        // Runs ONCE after mount, AND again whenever `conversationId`
        // CHANGES (per the dependency array below) — e.g. switching to
        // a different conversation re-establishes the connection for
        // the NEW conversation.
        const ws = new WebSocket(`wss://api.example.com/chat/${conversationId}`);

        ws.onmessage = (event) => {
          const newMessage = JSON.parse(event.data);
          // Correct: build a NEW array (spread), never mutate in place
          setMessages(prevMessages => [...prevMessages, newMessage]);
        };

        // The RETURNED function is a CLEANUP function — React calls it
        // before the effect re-runs (conversationId changed) or when
        // the component unmounts, closing the OLD connection before
        // opening a new one.
        return () => ws.close();
      }, [conversationId]);   // dependency array — MUST list every
                                // external value the effect reads

      return (
        <div>
          {messages.map(msg => <p key={msg.id}>{msg.text}</p>)}
        </div>
      );
    }
""")


if __name__ == "__main__":
    print(BASIC_COMPONENT_EXAMPLE)
    print(USESTATE_EXAMPLE)
    print(USEEFFECT_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
An AI agent-interaction dashboard (consuming this repo's Agentic AI &
RAG Notes-style backend) uses a `ChatWindow` component structured
exactly as shown above — `useState` holding the accumulating message
list, `useEffect`'s cleanup function ensuring a stale WebSocket
connection is properly closed when the user switches between
conversations, preventing both a resource leak (an orphaned open
connection) and a subtle bug where messages from the OLD conversation
could otherwise continue arriving and appending to the NEW conversation's view.
"""
