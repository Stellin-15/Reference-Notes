# ============================================================
# L04: LangChain Agents and Tool Use
# ============================================================
# WHAT: Agents let an LLM decide — at runtime — which tool to
#       call, with what arguments, and what to do with the result.
#       The loop continues until the LLM decides it has enough
#       information to produce a final answer.
# WHY:  Static chains handle fixed workflows. Agents handle open-
#       ended tasks where the steps depend on intermediate results:
#       "Is order 4821 eligible for a refund?" may require looking
#       up the order, checking eligibility rules, and querying the
#       refund policy — in that order, dynamically.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    ReAct pattern (Reason + Act):
      Thought: I need to look up order 4821 first.
      Action: lookup_order_status(order_id="4821")
      Observation: Order delivered 3 days ago, item: AirPods Pro
      Thought: Now check if AirPods Pro is refund-eligible.
      Action: check_refund_eligibility(item="AirPods Pro", days_since=3)
      Observation: Eligible — within 30-day window.
      Thought: I have enough info. Final answer: Yes, eligible.
      Final Answer: Order 4821 (AirPods Pro) is eligible for refund.

    The LLM never executes code. It outputs a structured "tool call"
    (JSON), the executor runs the real function, appends the result
    back to the conversation, and the LLM continues reasoning.

PRODUCTION USE CASE:
    Customer support agent for an e-commerce platform. Four tools:
    search knowledge base, lookup order status, check refund
    eligibility, create support ticket. Agent handles 80% of tier-1
    tickets automatically; escalates the rest via create_ticket.
    Memory keeps conversation context across multi-turn chats.
    Human-in-the-loop gate prevents agents from issuing refunds >$500.

COMMON MISTAKES:
    1. Vague tool docstrings: the LLM reads the docstring to decide
       whether to use the tool. Vague = wrong tool selected.
       Bad:  "Gets order info."
       Good: "Lookup order by ID. Returns status (shipped/delivered/
              cancelled), items, estimated delivery, tracking number."
    2. No max_iterations: agent loops forever on ambiguous tasks.
       Always set max_iterations=10 (or lower for cost control).
    3. Dangerous tools: never give agents shell exec, production DB
       writes, or unrestricted file system access.
    4. Ignoring intermediate steps: return_intermediate_steps=True
       lets you audit exactly what the agent did for each answer.
    5. Wrong agent type: OPENAI_TOOLS uses native function calling
       (reliable JSON). ZERO_SHOT_REACT uses text parsing (brittle).
       Use OPENAI_TOOLS or LCEL for anything production-facing.
    6. No error handling: tool failures crash the agent. Wrap tool
       logic in try/except and return a structured error string.
"""

# ── Imports ──────────────────────────────────────────────────
# pip install langchain langchain-openai langchain-community

from typing import Optional, List, Dict, Any
import json
import re

# Core LangChain agent infrastructure
from langchain.agents import AgentExecutor, initialize_agent, AgentType
from langchain.agents import create_openai_tools_agent
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# LLM
from langchain_openai import ChatOpenAI

# Memory — three options with different token/context trade-offs
from langchain.memory import (
    ConversationBufferMemory,         # stores ALL history (safe for short convos)
    ConversationBufferWindowMemory,   # stores last K turns (bounded token use)
    ConversationSummaryMemory,        # LLM summarizes old turns (token-efficient)
)

# Messages for LCEL-style agents
from langchain_core.messages import HumanMessage, AIMessage


# ── 1. TOOL DEFINITIONS ───────────────────────────────────────
# The @tool decorator converts a plain function into a LangChain Tool.
# The docstring IS the tool description — the LLM reads it verbatim
# to decide whether to invoke this tool. Write it like an API doc.

@tool
def search_knowledge_base(query: str) -> str:
    """
    Search the company knowledge base for policies, FAQs, and procedures.
    Use this for questions about return policies, shipping times, product
    specs, warranty information, or any general company information.
    Input: natural language query string.
    Returns: relevant policy text or 'No results found' if nothing matches.
    """
    # In production: call your vector DB or Elasticsearch here
    # This stub returns canned responses for demonstration
    knowledge = {
        "return policy": "Items can be returned within 30 days of delivery. "
                         "Electronics must be unopened. Refund processed in 3-5 business days.",
        "shipping": "Standard shipping: 5-7 days ($4.99). Express: 2 days ($12.99). "
                    "Free on orders over $50.",
        "warranty": "All electronics carry a 1-year manufacturer warranty. "
                    "Extended warranty available at checkout.",
    }
    # Simple keyword match — replace with real RAG retrieval in prod
    for key, value in knowledge.items():
        if key in query.lower():
            return value
    return "No relevant policy found. Please contact support@company.com."


@tool
def lookup_order_status(order_id: str) -> str:
    """
    Lookup the current status of a customer order by order ID.
    Use this when the customer provides an order number and asks about
    delivery status, tracking, or what items are in their order.
    Input: order_id as a string (e.g., '4821', 'ORD-4821').
    Returns: JSON string with status, items, delivery date, tracking number.
    Returns error message if order not found.
    """
    # Strip non-numeric prefix if customer writes "ORD-4821"
    clean_id = re.sub(r"[^\d]", "", order_id)

    # In production: query your orders database
    mock_orders = {
        "4821": {
            "status": "delivered",
            "items": ["AirPods Pro (x1)"],
            "delivered_date": "2026-06-27",
            "days_since_delivery": 3,
            "tracking": "1Z999AA10123456784",
            "total": 249.00,
        },
        "9002": {
            "status": "shipped",
            "items": ["MacBook Air M3 (x1)", "USB-C Hub (x1)"],
            "estimated_delivery": "2026-07-02",
            "tracking": "1Z999AA10987654321",
            "total": 1399.00,
        },
    }

    if clean_id not in mock_orders:
        return f"Order {order_id} not found. Please verify the order number."

    order = mock_orders[clean_id]
    return json.dumps(order, indent=2)  # return structured data as string


@tool
def check_refund_eligibility(order_id: str, reason: str = "not specified") -> str:
    """
    Check whether an order is eligible for a refund based on company policy.
    Use this AFTER lookup_order_status confirms the order exists and is delivered.
    Do NOT call this without first knowing the order details.
    Input: order_id (string), reason for refund request (string, optional).
    Returns: eligibility status, refund amount if eligible, next steps.
    """
    # In production: call your refund eligibility service
    # Simplified rules: delivered within 30 days → eligible
    mock_orders = {
        "4821": {"days_since_delivery": 3, "total": 249.00, "item": "AirPods Pro"},
        "9002": {"days_since_delivery": None, "total": 1399.00, "item": "MacBook Air M3"},
    }

    clean_id = re.sub(r"[^\d]", "", order_id)
    if clean_id not in mock_orders:
        return f"Cannot check eligibility — order {order_id} not found."

    order = mock_orders[clean_id]

    if order["days_since_delivery"] is None:
        return "Order has not been delivered yet. Refund requests require delivery first."

    if order["days_since_delivery"] <= 30:
        # Flag large refunds for human review (security gate)
        if order["total"] > 500:
            return (
                f"Order {order_id} is ELIGIBLE for refund of ${order['total']:.2f}. "
                f"However, refunds over $500 require manager approval. "
                f"A ticket will be created for human review."
            )
        return (
            f"Order {order_id} ({order['item']}) is ELIGIBLE for a full refund "
            f"of ${order['total']:.2f}. Reason logged: {reason}. "
            f"Refund will be processed in 3-5 business days."
        )
    else:
        return (
            f"Order {order_id} is NOT eligible for refund. "
            f"Delivered {order['days_since_delivery']} days ago — outside 30-day window."
        )


@tool
def create_support_ticket(
    customer_issue: str,
    priority: str = "medium",
    customer_email: str = "",
) -> str:
    """
    Create a support ticket for issues that cannot be resolved automatically.
    Use this when: (1) the customer's issue falls outside policy, (2) the
    customer is frustrated after 2+ failed resolution attempts, (3) a refund
    requires manager approval, or (4) the customer explicitly asks for human help.
    Input: customer_issue (description string), priority ('low'/'medium'/'high'),
           customer_email (string, optional).
    Returns: ticket ID and estimated response time.
    """
    import random
    ticket_id = f"TKT-{random.randint(10000, 99999)}"

    # In production: POST to your ticketing system (Zendesk, Freshdesk, Jira)
    response_times = {"low": "48 hours", "medium": "24 hours", "high": "4 hours"}
    eta = response_times.get(priority, "24 hours")

    print(f"[TICKET SYSTEM] Creating ticket: {ticket_id}")
    print(f"  Priority: {priority} | ETA: {eta}")
    print(f"  Issue: {customer_issue[:100]}")

    return (
        f"Support ticket {ticket_id} created (priority: {priority}). "
        f"A human agent will respond within {eta}. "
        f"Reference this ticket ID in future communications."
    )


# ── 2. AGENT SETUP (OPENAI_TOOLS — recommended for production) ─

def build_support_agent(openai_api_key: str, memory_type: str = "window"):
    """
    Build a customer support agent using OpenAI's native function calling.

    OPENAI_TOOLS agent type:
      - Uses GPT's built-in function calling (not text parsing)
      - Produces valid JSON tool calls reliably
      - Handles parallel tool calls in one LLM turn (GPT-4o feature)
      - Far more reliable than ZERO_SHOT_REACT for production
    """
    llm = ChatOpenAI(
        model="gpt-4o",
        temperature=0,          # deterministic: customers expect consistent answers
        api_key=openai_api_key,
    )

    tools = [
        search_knowledge_base,
        lookup_order_status,
        check_refund_eligibility,
        create_support_ticket,
    ]

    # Choose memory strategy based on conversation length expectations
    if memory_type == "buffer":
        # Stores every message — fine for short sessions, expensive for long ones
        memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True,   # return Message objects, not a string
        )
    elif memory_type == "window":
        # Keeps last 10 human+AI turns — bounded token cost, good recall
        memory = ConversationBufferWindowMemory(
            k=10,                   # number of TURNS (each turn = 1 human + 1 AI)
            memory_key="chat_history",
            return_messages=True,
        )
    elif memory_type == "summary":
        # LLM summarizes old turns when buffer grows — best for long sessions
        memory = ConversationSummaryMemory(
            llm=llm,                # uses same LLM to generate summaries
            memory_key="chat_history",
            return_messages=True,
        )

    # initialize_agent is the classic API — still widely used and well-tested
    agent_executor = initialize_agent(
        tools=tools,
        llm=llm,
        agent=AgentType.OPENAI_TOOLS,
        memory=memory,
        verbose=True,                       # prints each thought/action/observation
        max_iterations=10,                  # hard stop — prevents runaway loops
        early_stopping_method="force",      # after max_iterations, force a final answer
        handle_parsing_errors=True,         # recover from malformed LLM outputs
        return_intermediate_steps=True,     # include full thought chain in response
    )

    return agent_executor


# ── 3. MODERN LCEL AGENT (create_openai_tools_agent) ─────────

def build_lcel_agent(openai_api_key: str):
    """
    The modern LCEL-based agent pattern (LangChain 0.2+).
    More composable and inspectable than initialize_agent.
    Recommended for new projects.

    Flow: prompt | llm.bind_tools(tools) → parse tool calls
          → execute tools → append results → loop back to llm
    """
    llm = ChatOpenAI(model="gpt-4o", temperature=0, api_key=openai_api_key)

    tools = [
        search_knowledge_base,
        lookup_order_status,
        check_refund_eligibility,
        create_support_ticket,
    ]

    # System prompt defines agent persona and behavior constraints
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a helpful customer support agent for ShopEasy. "
         "Always look up order details before making refund decisions. "
         "Create a support ticket if you cannot resolve the issue in 3 tool calls. "
         "Be concise and empathetic."),
        MessagesPlaceholder(variable_name="chat_history"),  # memory slot
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),  # tool call history
    ])

    # create_openai_tools_agent returns a Runnable (not an executor)
    agent = create_openai_tools_agent(llm, tools, prompt)

    # AgentExecutor manages the ReAct loop around the agent Runnable
    executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        max_iterations=10,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )

    return executor


# ── 4. MULTI-AGENT SUPERVISOR PATTERN ────────────────────────

class SupervisorRouter:
    """
    Routes incoming tasks to specialist sub-agents.
    Each specialist has a focused set of tools and a narrow system prompt.
    The supervisor (an LLM call) decides which specialist handles the task.

    Specialists:
      research_agent: web_search, search_knowledge_base
      data_agent:     run_sql, generate_chart
      support_agent:  lookup_order, check_refund, create_ticket
      writer_agent:   no tools — pure LLM generation
    """

    def __init__(self, openai_api_key: str):
        self.llm = ChatOpenAI(model="gpt-4o", temperature=0, api_key=openai_api_key)
        self.support_agent = build_support_agent(openai_api_key)

    def route(self, user_message: str) -> str:
        """Classify the message and dispatch to the right specialist."""
        # Quick classification call — cheap, fast
        classification_prompt = f"""Classify this customer message into one category:
        - ORDER: about a specific order, delivery, or refund
        - POLICY: general questions about company policies
        - ESCALATE: angry customer or complex complaint

        Message: {user_message}
        Respond with only the category name."""

        category = self.llm.invoke(classification_prompt).content.strip()
        print(f"[SUPERVISOR] Routed to: {category}")

        if category in ("ORDER", "ESCALATE"):
            # Full agent with tools for order/refund workflows
            result = self.support_agent.invoke({"input": user_message})
            return result["output"]
        else:
            # Policy questions → simple RAG without agent overhead
            result = self.llm.invoke(
                f"Answer this customer question about our policies: {user_message}"
            )
            return result.content


# ── 5. ESCALATION LOGIC ───────────────────────────────────────

class SupportSession:
    """
    Tracks a customer conversation and escalates automatically
    after repeated failures — mimics real Tier-1 → Tier-2 escalation.
    """

    def __init__(self, agent_executor: AgentExecutor, max_failed_turns: int = 3):
        self.agent = agent_executor
        self.max_failed = max_failed_turns
        self.failed_turns = 0       # count turns where agent couldn't resolve
        self.conversation_log = []  # full transcript for ticket context

    def chat(self, user_message: str) -> str:
        self.conversation_log.append(f"Customer: {user_message}")

        # Auto-escalate if too many unresolved turns
        if self.failed_turns >= self.max_failed:
            ticket_result = create_support_ticket.invoke({
                "customer_issue": f"Unresolved after {self.failed_turns} attempts. "
                                  f"Last message: {user_message}",
                "priority": "high",
            })
            return f"I'm connecting you with a human agent. {ticket_result}"

        result = self.agent.invoke({"input": user_message})
        response = result["output"]
        self.conversation_log.append(f"Agent: {response}")

        # Detect failure signals in the response (customize for your domain)
        failure_signals = ["I'm sorry", "cannot", "unable", "don't have access"]
        if any(signal.lower() in response.lower() for signal in failure_signals):
            self.failed_turns += 1

        return response


# ── 6. FULL DEMO ──────────────────────────────────────────────

def run_support_demo(openai_api_key: str):
    """
    Simulate a multi-turn customer support conversation.
    The agent autonomously decides which tools to call at each turn.
    """
    print("=== Customer Support Agent Demo ===\n")

    agent = build_support_agent(openai_api_key, memory_type="window")
    session = SupportSession(agent, max_failed_turns=3)

    # Turn 1: General policy question — agent uses search_knowledge_base
    print("Turn 1: General question")
    resp = session.chat("What's your return policy?")
    print(f"Agent: {resp}\n")

    # Turn 2: Order lookup — agent uses lookup_order_status
    print("Turn 2: Order inquiry")
    resp = session.chat("I want to check order 4821")
    print(f"Agent: {resp}\n")

    # Turn 3: Refund — agent chains lookup_order_status → check_refund_eligibility
    print("Turn 3: Refund request")
    resp = session.chat("I'd like a refund for order 4821. The sound quality is poor.")
    print(f"Agent: {resp}\n")

    # Turn 4: Memory test — agent recalls order 4821 from prior turn
    print("Turn 4: Follow-up (tests memory)")
    resp = session.chat("How long will the refund take?")
    print(f"Agent: {resp}\n")

    print("=== Intermediate Steps (Audit Trail) ===")
    # In production: log these to your observability platform (LangSmith, Datadog)


if __name__ == "__main__":
    # Replace with your actual key or set OPENAI_API_KEY env var
    import os
    api_key = os.getenv("OPENAI_API_KEY", "sk-placeholder")

    # Show tool schema (what the LLM sees)
    print("=== Tool Descriptions (LLM sees these) ===")
    for t in [search_knowledge_base, lookup_order_status,
              check_refund_eligibility, create_support_ticket]:
        print(f"\nTool: {t.name}")
        print(f"Description: {t.description[:120]}...")

    # Run demo with real key
    # run_support_demo(api_key)
