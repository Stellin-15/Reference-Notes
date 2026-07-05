# ============================================================
# L13: LangGraph Deep Dive — StateGraph, Cycles, Persistence, Human-in-the-Loop
# ============================================================
# WHAT: LangGraph's core abstraction — a StateGraph of NODES (functions)
#       and EDGES (including CONDITIONAL edges and CYCLES, which
#       distinguish it from a simple linear chain), built-in persistence/
#       checkpointing, and human-in-the-loop interrupts.
# WHY: L12 showed a hand-rolled agent loop. LangGraph is the most widely
#      used framework for building that loop as an explicit, inspectable
#      GRAPH rather than an implicit while-loop in code — its support
#      for CYCLES (a node can route back to an earlier node) and
#      PERSISTENCE (resuming a long-running agent's state after a
#      restart) address real production needs L12's minimal loop doesn't.
# LEVEL: Advanced (Phase 3 of 7)
# ============================================================

"""
CONCEPT OVERVIEW:
A LangGraph STATEGRAPH is defined by: a SHARED STATE (a typed structure
every node reads from and writes to — e.g. a message history, a set of
scratch variables), NODES (Python functions that take the current state
and return updates to it), and EDGES connecting nodes (defining execution
order). Unlike LangChain's LCEL (L05), which composes a linear/DAG chain,
LangGraph EXPLICITLY supports CYCLES — a node can route back to a
PREVIOUS node, which is exactly what an agent loop (L12's Thought ->
Action -> Observation -> repeat) requires and a strictly-DAG chain cannot
express.

CONDITIONAL EDGES let the graph's execution path depend on the current
STATE — a router function inspects the state after a node runs and
decides which node to go to next (e.g. "if the LLM's last message
includes a tool call, go to the tool-execution node; otherwise, end").
This conditional routing IS how LangGraph implements the ReAct-style
loop from L12 as an explicit graph structure instead of a hand-written
while loop.

PERSISTENCE/CHECKPOINTING: LangGraph can automatically save the graph's
state after each node executes (to memory, a database, or another
backend) — meaning a long-running agent can be PAUSED and RESUMED later
(across a process restart, or intentionally for human review) without
losing its accumulated state. This directly enables HUMAN-IN-THE-LOOP
workflows: the graph can be configured to INTERRUPT before a specific
node (e.g. before actually executing a potentially destructive tool
call), wait for human approval, and then resume exactly where it left off.

PRODUCTION USE CASE:
A customer-service agent's graph includes a conditional edge: after
generating a proposed refund action, the graph interrupts and waits for
human approval before actually executing the refund tool — because the
graph's state is checkpointed, this can be an ASYNCHRONOUS wait (hours,
even days, for a human reviewer) without the agent process needing to
stay running the whole time; when approved, the graph resumes from
exactly the checkpointed state.

COMMON MISTAKES:
- Building a genuinely CYCLIC agent loop using LCEL's linear chain
  composition (L05) instead of LangGraph — LCEL is not designed to
  express "go back to an earlier step based on a condition," and forcing
  it to do so produces awkward, hard-to-maintain code; LangGraph exists
  specifically for this pattern.
- Not setting a recursion/iteration limit on the graph — since cycles are
  a first-class feature, an ill-defined conditional edge can create an
  infinite loop; LangGraph supports a `recursion_limit` specifically to
  guard against this, directly analogous to L12's max_steps safeguard.
- Assuming state persists automatically without explicitly configuring a
  checkpointer — persistence is an OPT-IN feature (you attach a
  checkpointer, e.g. backed by SQLite or Postgres, to the compiled
  graph); without one, state exists only in memory for the duration of
  a single `invoke()` call.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Defining state, nodes, and a cyclic graph
# ------------------------------------------------------------------
LANGGRAPH_BASIC_EXAMPLE = textwrap.dedent("""\
    from typing import TypedDict, Annotated
    from langgraph.graph import StateGraph, END
    from langgraph.graph.message import add_messages

    class AgentState(TypedDict):
        # `add_messages` is a REDUCER — instead of each node OVERWRITING
        # the messages list, new messages are APPENDED to it. This is
        # how LangGraph accumulates conversation/reasoning history
        # across the graph's execution automatically.
        messages: Annotated[list, add_messages]

    def call_model(state: AgentState) -> dict:
        # A real node calls an LLM with the current message history and
        # returns its response as a state UPDATE (merged via the reducer).
        response = llm.invoke(state["messages"])
        return {"messages": [response]}

    def call_tool(state: AgentState) -> dict:
        last_message = state["messages"][-1]
        result = execute_tool(last_message.tool_calls[0])
        return {"messages": [result]}

    def should_continue(state: AgentState) -> str:
        # A CONDITIONAL EDGE function — inspects state, returns the NAME
        # of the next node to route to. This is the mechanism that turns
        # a graph into a LOOP: routing back to "agent" creates the cycle.
        last_message = state["messages"][-1]
        return "tools" if last_message.tool_calls else END

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", call_tool)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")   # THE cycle: after using a tool, go
                                         # back to the agent node to decide
                                         # what to do next — exactly L12's
                                         # ReAct loop, expressed as a graph edge.

    app = graph.compile()
    result = app.invoke({"messages": [("user", "What's the weather in Tokyo in Fahrenheit?")]})
""")

# ------------------------------------------------------------------
# 2. Persistence/checkpointing
# ------------------------------------------------------------------
CHECKPOINTING_EXAMPLE = textwrap.dedent("""\
    from langgraph.checkpoint.sqlite import SqliteSaver

    checkpointer = SqliteSaver.from_conn_string("agent_state.db")
    app = graph.compile(checkpointer=checkpointer)

    # A `thread_id` identifies ONE specific conversation/task's state —
    # resuming later with the SAME thread_id continues exactly where the
    # graph left off, even across a process restart, because the state
    # was persisted to SQLite (or Postgres/Redis in production) rather
    # than only kept in memory.
    config = {"configurable": {"thread_id": "customer_123_session_1"}}
    result = app.invoke({"messages": [("user", "I need a refund")]}, config=config)

    # ... process restarts, hours pass ...

    result = app.invoke({"messages": [("user", "Any update?")]}, config=config)
    # This call sees the FULL accumulated message history from before
    # the restart, because it was checkpointed under the same thread_id.
""")

# ------------------------------------------------------------------
# 3. Human-in-the-loop interrupts
# ------------------------------------------------------------------
HUMAN_IN_THE_LOOP_EXAMPLE = textwrap.dedent("""\
    # Compile the graph with an INTERRUPT configured before a specific
    # node — execution PAUSES there, persisting state, until explicitly
    # resumed.
    app = graph.compile(checkpointer=checkpointer, interrupt_before=["execute_refund"])

    result = app.invoke({"messages": [("user", "I need a refund")]}, config=config)
    # Execution stops BEFORE "execute_refund" runs — the proposed action
    # is visible in the current state for a human to review, and NOTHING
    # destructive has happened yet.

    # ... a human reviews the proposed refund and approves it ...

    # Resuming with `None` as input continues the graph from exactly
    # where it paused, now actually executing the approved action.
    result = app.invoke(None, config=config)
""")

# ------------------------------------------------------------------
# 4. LangGraph vs a hand-rolled loop (L12) vs LCEL (L05)
# ------------------------------------------------------------------
COMPARISON = {
    "Hand-rolled Python loop (L12)": "Full control, zero framework "
        "overhead, but you build persistence/interrupts/state management "
        "yourself from scratch for anything beyond a toy example.",
    "LangChain LCEL (L05)": "Great for LINEAR/DAG composition (retrieve "
        "-> prompt -> generate) — not designed to express cycles; "
        "forcing an agent loop into LCEL is awkward.",
    "LangGraph": "Explicit support for cycles, conditional routing, "
        "built-in persistence, and human-in-the-loop interrupts — the "
        "natural choice once an agent needs to loop, pause, or resume "
        "across time, which most real production agents eventually do.",
}


if __name__ == "__main__":
    print(LANGGRAPH_BASIC_EXAMPLE)
    print(CHECKPOINTING_EXAMPLE)
    print(HUMAN_IN_THE_LOOP_EXAMPLE)
    print("=== Comparison ===")
    for approach, note in COMPARISON.items():
        print(f"{approach}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A financial-approval agent proposes wire transfers above a threshold
amount, then LangGraph interrupts execution before the actual transfer
tool call — the state is checkpointed to Postgres, and a compliance
officer reviews and approves (or rejects) the proposed transfer, possibly
hours later and from an entirely separate review interface querying the
same checkpoint database — when approved, the SAME graph execution
resumes and completes the transfer, with the full reasoning trail
(every Thought/Action/Observation from L12's pattern) preserved in the
checkpointed state for audit purposes.
"""
