# ============================================================
# L05: LangGraph — Stateful Multi-Step Workflows
# ============================================================
# WHAT: LangGraph builds workflows as explicit directed graphs:
#       nodes are Python functions, edges define control flow,
#       and a shared State object persists across all nodes.
#       Supports cycles (loops), branching, parallelism,
#       human-in-the-loop pauses, and persistent checkpointing.
# WHY:  Plain LangChain agents are a black box — you can't control
#       the loop, add conditional branches, or pause for human
#       approval. LangGraph makes the workflow explicit, debuggable,
#       and resumable. Critical for production agentic systems.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    Core building blocks:
      StateGraph:  the container — defines state schema and wires nodes
      State:       TypedDict shared across all nodes; reducers merge updates
      Nodes:       plain functions (state: State) -> dict (partial update)
      Edges:       unconditional (A always goes to B)
      Cond. Edges: routing function returns a key → go to that node
      Compile:     graph.compile() → Runnable (invoke / stream / batch)

    Key difference from agents:
      Agent: LLM decides the loop implicitly (opaque)
      LangGraph: YOU define the loop explicitly (transparent, auditable)
      You can add: retry logic, human approval gates, parallel branches,
      per-user memory, and graceful error recovery — all first-class.

PRODUCTION USE CASE:
    Customer support workflow:
      1. classify_intent: billing / technical / refund / other
      2a. retrieve_docs: search knowledge base (for billing/technical)
      2b. check_order: lookup order DB (for refund)
      3. generate_response: LLM drafts answer from retrieved context
      4. human_approval: PAUSE — agent reviews if refund > $500
      5. send_response: deliver answer to customer

    Each customer session has its own thread_id → independent memory.
    Interrupted workflows (human approval) resume exactly where paused.
    Entire history is checkpointed to SQLite for audit trails.

COMMON MISTAKES:
    1. Mutable state: never mutate state in place. Return a new dict
       from each node. The graph merges updates via reducers.
    2. Wrong reducer: default reducer replaces the field. Use
       Annotated[list, add_messages] for message lists (appends).
       Using the wrong reducer causes messages to be overwritten.
    3. Missing END: every path through the graph must reach END.
       A branch that never terminates causes an infinite loop.
    4. Forgetting thread_id: invoke without config={"configurable":
       {"thread_id": "..."}} means no checkpointing — each call
       starts fresh with no memory of prior turns.
    5. Interrupt node name typo: interrupt_before=["submit_refund"]
       must exactly match graph.add_node("submit_refund", ...).
       Typos cause the interrupt to silently not fire.
    6. Streaming after compile: app.stream() yields one dict per node
       per invocation. Each dict is {node_name: state_update}.
       Don't expect the full state — extract the field you need.
"""

# ── Imports ──────────────────────────────────────────────────
# pip install langgraph langchain langchain-openai

from typing import TypedDict, Annotated, List, Optional, Literal
import operator
import json

# LangGraph core
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages    # reducer: appends messages
from langgraph.checkpoint.memory import MemorySaver # in-memory checkpointer (dev)
# from langgraph.checkpoint.sqlite import SqliteSaver  # prod: persists to disk

# LangChain components used inside nodes
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import tool


# ── 1. STATE DEFINITION ───────────────────────────────────────

class AgentState(TypedDict):
    """
    The shared state object passed through every node in the graph.

    Design rules:
      - Every field is optional-ish: nodes only update the fields they own.
      - Use Annotated[list, add_messages] for message lists — this reducer
        APPENDS new messages instead of replacing the entire list.
        Without this, each node would wipe the message history.
      - Scalar fields (str, int, bool) use default replacement (last write wins).
      - 'turns' tracks loop count for safety limits (prevent infinite cycles).
    """
    messages: Annotated[list, add_messages]   # conversation history — append-only
    intent: str                               # classified intent (billing/tech/refund)
    docs: List[str]                           # retrieved knowledge base chunks
    order_info: Optional[dict]                # populated by check_order node
    draft_response: str                       # LLM-generated response before approval
    final_response: str                       # approved/sent response
    needs_human_approval: bool                # flag: True if refund > $500
    turns: int                                # number of reasoning cycles completed
    customer_id: str                          # for multi-user session isolation


# ── 2. NODE FUNCTIONS ─────────────────────────────────────────
# Each node is a plain Python function: (state: AgentState) -> dict
# Return ONLY the fields you're updating — the graph merges the rest.

def classify_intent(state: AgentState) -> dict:
    """
    Node 1: Classify the customer's latest message into an intent category.
    Uses a cheap, fast LLM call (gpt-4o-mini) to route the workflow.
    """
    # Get the most recent human message from the conversation history
    last_message = state["messages"][-1].content

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    classification = llm.invoke([
        SystemMessage(content=(
            "Classify the customer message into exactly one of: "
            "billing, technical, refund, general. "
            "Respond with only the category name, lowercase."
        )),
        HumanMessage(content=last_message),
    ])

    intent = classification.content.strip().lower()
    # Fallback to "general" if model returns something unexpected
    if intent not in ("billing", "technical", "refund", "general"):
        intent = "general"

    print(f"[classify_intent] → intent: {intent}")
    return {"intent": intent, "turns": state.get("turns", 0) + 1}


def retrieve_docs(state: AgentState) -> dict:
    """
    Node 2a: Retrieve relevant knowledge base chunks for billing/technical queries.
    In production: calls your RAG retriever (see L03_rag_systems.py).
    """
    query = state["messages"][-1].content

    # Mock retrieval — replace with real vectorstore.similarity_search(query)
    mock_kb = {
        "billing": [
            "Invoices are sent on the 1st of each month via email.",
            "Payment accepted: Visa, Mastercard, PayPal. ACH takes 3-5 days.",
            "Billing disputes must be raised within 60 days of invoice date.",
        ],
        "technical": [
            "Restart the service: sudo systemctl restart app. Check logs at /var/log/app.",
            "API rate limit: 1000 req/min. Use exponential backoff on 429 responses.",
        ],
        "general": [
            "Support hours: Mon-Fri 9am-6pm EST. Emergency line: 1-800-555-0100.",
        ],
    }

    # Retrieve chunks relevant to this intent (in prod: top-K by cosine similarity)
    intent = state.get("intent", "general")
    docs = mock_kb.get(intent, mock_kb["general"])

    print(f"[retrieve_docs] Retrieved {len(docs)} chunks for intent='{intent}'")
    return {"docs": docs}


def check_order(state: AgentState) -> dict:
    """
    Node 2b: Look up order info from the orders database.
    Only reached for refund-intent messages.
    Extracts order ID from the message using regex.
    """
    import re
    last_message = state["messages"][-1].content

    # Try to extract an order ID (e.g., "order 4821" or "ORD-4821")
    match = re.search(r"\b(?:order\s*#?\s*|ORD-?)(\d{4,})\b", last_message, re.I)
    order_id = match.group(1) if match else None

    if not order_id:
        print("[check_order] No order ID found in message")
        return {"order_info": None}

    # Mock order DB — replace with real DB query
    mock_orders = {
        "4821": {"status": "delivered", "item": "AirPods Pro", "total": 249.00,
                 "days_since_delivery": 3, "eligible_for_refund": True},
        "9002": {"status": "delivered", "item": "MacBook Air M3", "total": 1399.00,
                 "days_since_delivery": 5, "eligible_for_refund": True},
    }

    order = mock_orders.get(order_id)
    print(f"[check_order] Order {order_id}: {order}")
    return {"order_info": order}


def generate_response(state: AgentState) -> dict:
    """
    Node 3: Generate the LLM response using retrieved docs or order info.
    Builds the prompt dynamically based on what upstream nodes populated.
    """
    llm = ChatOpenAI(model="gpt-4o", temperature=0.3)

    # Build context string from whichever upstream node ran
    context_parts = []

    if state.get("docs"):
        # For billing/technical: inject knowledge base chunks
        context_parts.append("Knowledge Base:\n" + "\n".join(f"- {d}" for d in state["docs"]))

    if state.get("order_info"):
        # For refunds: inject order details
        order = state["order_info"]
        context_parts.append(
            f"Order Info: {json.dumps(order, indent=2)}\n"
            f"Refund eligible: {'Yes' if order.get('eligible_for_refund') else 'No'}"
        )

    context = "\n\n".join(context_parts) or "No specific context retrieved."
    customer_message = state["messages"][-1].content

    response = llm.invoke([
        SystemMessage(content=(
            "You are a helpful customer support agent. "
            "Answer based on the context provided. Be concise and empathetic.\n\n"
            f"Context:\n{context}"
        )),
        HumanMessage(content=customer_message),
    ])

    draft = response.content

    # Determine if human approval is needed: refund eligible + over $500 threshold
    needs_approval = False
    order = state.get("order_info") or {}
    if order.get("eligible_for_refund") and order.get("total", 0) > 500:
        needs_approval = True
        print(f"[generate_response] Refund ${order['total']} > $500 → human approval required")

    print(f"[generate_response] Draft: {draft[:80]}...")
    return {
        "draft_response": draft,
        "needs_human_approval": needs_approval,
        # Append AI message to conversation history (add_messages reducer appends)
        "messages": [AIMessage(content=draft)],
    }


def human_approval(state: AgentState) -> dict:
    """
    Node 4: Human-in-the-loop gate for large refunds.
    In a real system this node is INTERRUPTED BEFORE execution —
    the graph pauses here, a human reviews via UI, then resumes.

    compile(interrupt_before=["human_approval"]) causes the graph
    to stop BEFORE entering this node. The state (including draft_response)
    is persisted in the checkpointer. A human reviews and either:
      - Approves:  app.invoke(None, config)  → resumes, runs this node
      - Rejects:   modify state and resume with rejection message
    """
    # When this runs (after human approves), mark it as approved
    print("[human_approval] Refund approved by human agent")
    return {
        "draft_response": state["draft_response"] + "\n\n[Approved by human agent]",
        "needs_human_approval": False,   # clear the flag after approval
    }


def send_response(state: AgentState) -> dict:
    """
    Node 5: Finalize and "send" the response to the customer.
    In production: POST to your messaging platform (Zendesk, Intercom, Slack).
    """
    final = state["draft_response"]
    print(f"\n[send_response] FINAL RESPONSE:\n{final}\n")

    # In production: deliver via API to your customer-facing channel
    return {"final_response": final}


# ── 3. ROUTING FUNCTIONS (for conditional edges) ──────────────

def route_by_intent(state: AgentState) -> Literal["retrieve_docs", "check_order"]:
    """
    Conditional edge function: called after classify_intent.
    Returns the NAME of the next node to execute.
    The string must exactly match a node name added via add_node().
    """
    intent = state.get("intent", "general")

    if intent == "refund":
        return "check_order"       # refund → need order details
    else:
        return "retrieve_docs"     # billing/technical/general → knowledge base


def route_approval(state: AgentState) -> Literal["human_approval", "send_response"]:
    """
    Conditional edge after generate_response:
    Large refunds pause for human review; everything else goes straight to send.
    """
    if state.get("needs_human_approval"):
        return "human_approval"    # pause here (if interrupt_before configured)
    return "send_response"


def should_continue_loop(state: AgentState) -> Literal["generate_response", "__end__"]:
    """
    Example loop guard: if too many turns, force END to prevent infinite cycles.
    Used in ReAct-style graphs where the agent can loop back to try again.
    """
    if state.get("turns", 0) >= 5:
        print("[loop_guard] Max turns reached — forcing END")
        return "__end__"
    return "generate_response"


# ── 4. GRAPH CONSTRUCTION ─────────────────────────────────────

def build_support_graph(with_interrupts: bool = False):
    """
    Assemble the full customer support workflow graph.

    Graph structure:
      START
        ↓
      classify_intent
        ↓ (conditional)
      ┌──────────────────┐
      retrieve_docs   check_order
      └──────┬───────────┘
             ↓
      generate_response
             ↓ (conditional)
      ┌──────────────────┐
      human_approval  send_response
           ↓               ↓
      send_response       END
           ↓
          END
    """
    # StateGraph is parameterized by the state schema
    graph = StateGraph(AgentState)

    # Register nodes: name → function
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("retrieve_docs", retrieve_docs)
    graph.add_node("check_order", check_order)
    graph.add_node("generate_response", generate_response)
    graph.add_node("human_approval", human_approval)
    graph.add_node("send_response", send_response)

    # Set the entry point — first node to run
    graph.set_entry_point("classify_intent")

    # Conditional edge: classify_intent → retrieve_docs OR check_order
    graph.add_conditional_edges(
        "classify_intent",          # source node
        route_by_intent,            # routing function → returns node name
        {
            "retrieve_docs": "retrieve_docs",    # key → destination node
            "check_order": "check_order",
        },
    )

    # Both retrieval branches converge at generate_response
    graph.add_edge("retrieve_docs", "generate_response")
    graph.add_edge("check_order", "generate_response")

    # Conditional edge: generate_response → human_approval OR send_response
    graph.add_conditional_edges(
        "generate_response",
        route_approval,
        {
            "human_approval": "human_approval",
            "send_response": "send_response",
        },
    )

    # After human approval, always send the response
    graph.add_edge("human_approval", "send_response")

    # send_response is terminal — goes to END
    graph.add_edge("send_response", END)

    # Choose checkpointer
    checkpointer = MemorySaver()    # in-memory, resets on restart (dev only)
    # For prod: checkpointer = SqliteSaver.from_conn_string("support.db")

    if with_interrupts:
        # Graph will PAUSE before human_approval — awaits external resume
        return graph.compile(
            checkpointer=checkpointer,
            interrupt_before=["human_approval"],  # must match add_node name exactly
        )
    else:
        return graph.compile(checkpointer=checkpointer)


# ── 5. INVOKE EXAMPLE ─────────────────────────────────────────

def run_single_turn(app, customer_message: str, customer_id: str = "cust_001"):
    """
    Invoke the graph for one customer message.
    thread_id isolates state per customer — each customer gets their own
    checkpointed conversation history.
    """
    # config carries the thread_id — mandatory for checkpointing to work
    config = {"configurable": {"thread_id": customer_id}}

    initial_state = {
        "messages": [HumanMessage(content=customer_message)],
        "intent": "",
        "docs": [],
        "order_info": None,
        "draft_response": "",
        "final_response": "",
        "needs_human_approval": False,
        "turns": 0,
        "customer_id": customer_id,
    }

    # invoke() runs the full graph synchronously and returns final state
    final_state = app.invoke(initial_state, config=config)
    return final_state["final_response"]


# ── 6. STREAMING EXAMPLE ──────────────────────────────────────

def run_with_streaming(app, customer_message: str, customer_id: str = "cust_stream"):
    """
    Stream graph execution: yields one update per node as it completes.
    Use this to show real-time progress in a UI ("Checking your order...").

    Each yielded chunk is: {node_name: {field: value, ...}}
    """
    config = {"configurable": {"thread_id": customer_id}}

    initial_state = {
        "messages": [HumanMessage(content=customer_message)],
        "intent": "",
        "docs": [],
        "order_info": None,
        "draft_response": "",
        "final_response": "",
        "needs_human_approval": False,
        "turns": 0,
        "customer_id": customer_id,
    }

    print(f"\n=== Streaming execution for: '{customer_message}' ===\n")

    for chunk in app.stream(initial_state, config=config):
        # chunk keys are node names; values are the state updates from that node
        for node_name, state_update in chunk.items():
            print(f"[STREAM] Node '{node_name}' completed:")
            # Print non-empty, non-list updates for readability
            for key, val in state_update.items():
                if val and not isinstance(val, list):
                    print(f"  {key}: {str(val)[:80]}")

    print("\n=== Stream complete ===")


# ── 7. HUMAN-IN-THE-LOOP RESUME ──────────────────────────────

def run_with_human_approval(openai_api_key: str = None):
    """
    Demonstrates the full interrupt-and-resume cycle for large refunds.

    Step 1: invoke() — graph runs until it hits interrupt_before=["human_approval"]
    Step 2: Graph is paused; state is saved in checkpointer
    Step 3: Human reviews state["draft_response"] via external UI
    Step 4: invoke(None, config) — resumes from the interrupt point
    """
    app = build_support_graph(with_interrupts=True)
    config = {"configurable": {"thread_id": "refund_session_001"}}

    # Customer asks for refund on a $1399 MacBook (over $500 threshold)
    initial_state = {
        "messages": [HumanMessage(content="I need a refund for order 9002, MacBook Air M3")],
        "intent": "",
        "docs": [],
        "order_info": None,
        "draft_response": "",
        "final_response": "",
        "needs_human_approval": False,
        "turns": 0,
        "customer_id": "cust_highvalue",
    }

    print("=== Step 1: Running until interrupt ===")
    # Graph stops BEFORE human_approval — returns intermediate state
    partial_state = app.invoke(initial_state, config=config)
    print(f"Graph paused. Draft response: {partial_state.get('draft_response', '')[:100]}")

    # ── Human reviews here (simulated) ──
    print("\n=== Step 2: Human reviewing refund of $1399 ===")
    print(f"Pending approval: {partial_state.get('draft_response', '')[:120]}")
    approved = True   # in production: wait for UI button click

    if approved:
        print("\n=== Step 3: Resuming after approval ===")
        # Passing None as state resumes from checkpoint (no state reset)
        final_state = app.invoke(None, config=config)
        print(f"Final response: {final_state.get('final_response', '')}")


# ── 8. REACT LOOP PATTERN ─────────────────────────────────────

def build_react_graph():
    """
    Classic ReAct loop as an explicit LangGraph:
      agent_node: LLM decides → tool call OR final answer
      tools_node: executes the tool call
      Edge: if tool call → tools_node → agent_node (loop)
            if final answer → END

    This is exactly what AgentExecutor does internally, but now
    you can inspect, modify, or break the loop at any point.
    """
    class ReActState(TypedDict):
        messages: Annotated[list, add_messages]

    llm = ChatOpenAI(model="gpt-4o", temperature=0)

    @tool
    def calculator(expression: str) -> str:
        """Evaluate a math expression. Input: '2 + 2 * 10'. Returns the numeric result."""
        try:
            # WARNING: in production, use a safe math parser, not eval()
            result = eval(expression, {"__builtins__": {}}, {})  # noqa: S307
            return str(result)
        except Exception as e:
            return f"Error: {e}"

    tools = [calculator]
    llm_with_tools = llm.bind_tools(tools)   # attaches tool schemas to the LLM

    def agent_node(state: ReActState) -> dict:
        """Agent: call LLM, which may return a tool_call or a final message."""
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}   # add_messages reducer appends this

    def tool_node(state: ReActState) -> dict:
        """Execute all tool calls from the last AI message."""
        from langchain_core.messages import ToolMessage
        last_message = state["messages"][-1]
        tool_results = []

        for tool_call in last_message.tool_calls:
            # Find matching tool and invoke it
            matching = [t for t in tools if t.name == tool_call["name"]]
            if matching:
                result = matching[0].invoke(tool_call["args"])
                tool_results.append(
                    ToolMessage(content=str(result), tool_call_id=tool_call["id"])
                )

        return {"messages": tool_results}

    def should_continue(state: ReActState) -> Literal["tools", "__end__"]:
        """Route: if last message has tool_calls → tools node; else → END."""
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return "__end__"

    graph = StateGraph(ReActState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")

    # Conditional: agent output → tools OR END
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "__end__": END})

    # After tools run, always loop back to agent
    graph.add_edge("tools", "agent")

    return graph.compile()


# ── 9. FULL DEMO ──────────────────────────────────────────────

def run_full_demo():
    """
    Run multiple scenarios through the support graph.
    """
    print("=== LangGraph Customer Support Demo ===\n")

    # Build graph without interrupts for basic demo
    app = build_support_graph(with_interrupts=False)

    # Scenario 1: Billing question → retrieve_docs path
    print("--- Scenario 1: Billing inquiry ---")
    result = run_single_turn(app, "When does my invoice arrive?", "cust_billing_01")
    print(f"Response: {result}\n")

    # Scenario 2: Stream a technical question
    print("--- Scenario 2: Technical issue (streaming) ---")
    run_with_streaming(app, "My API keeps returning 429 errors", "cust_tech_01")

    # Scenario 3: ReAct loop with calculator tool
    print("\n--- Scenario 3: ReAct loop with tool ---")
    react_app = build_react_graph()
    result = react_app.invoke({
        "messages": [HumanMessage(content="What is 847 * 23 + 156?")]
    })
    print(f"ReAct result: {result['messages'][-1].content}")


if __name__ == "__main__":
    run_full_demo()

    # To test human-in-the-loop (requires OPENAI_API_KEY):
    # run_with_human_approval()
