# ============================================================
# L18: The Vendor Agent SDK Landscape — OpenAI Agents SDK, LangChain
#      Agents, PydanticAI, Semantic Kernel, Google ADK, AWS Bedrock
#      Agents, Azure AI Foundry Agent Service
# ============================================================
# WHAT: A survey of PROVIDER/VENDOR-NATIVE agent-building SDKs — distinct
#       from the orchestration frameworks in Phase 3 (LangGraph, CrewAI,
#       AutoGen) in that these are built and maintained by the model/
#       cloud providers themselves, often with tighter integration to
#       that provider's specific model, hosting, and observability stack.
# WHY: Phase 3's frameworks are largely PROVIDER-AGNOSTIC (LangGraph
#      works with any LLM). This phase covers the alternative: building
#      directly against a specific vendor's own agent primitives — a
#      real, distinct choice with different lock-in, integration depth,
#      and managed-hosting tradeoffs.
# LEVEL: Advanced (Phase 4 of 7 — Vendor Agent SDKs)
# ============================================================

"""
CONCEPT OVERVIEW:
The distinction from Phase 3: LangGraph, CrewAI, and AutoGen are
INDEPENDENT, provider-agnostic frameworks — you plug in whichever LLM
provider you want. The SDKs in this lesson are built BY a specific
model/cloud provider, FOR their own ecosystem — trading some
provider-agnosticism for tighter integration (native tool-calling
conventions, built-in hosting/observability, often lower friction for
teams already committed to that provider).

OPENAI AGENTS SDK: OpenAI's own lightweight agent-building library —
built around simple "Agent" objects with instructions and tools,
explicit HANDOFFS between agents (one agent can hand off a conversation
to another, specialized agent — a distinct, lighter-weight multi-agent
primitive than CrewAI's roles or AutoGen's conversations), and built-in
tracing for debugging agent runs, tightly coupled to OpenAI's own models
and the Responses API.

LANGCHAIN AGENTS: LangChain's own (provider-agnostic) agent abstraction
— predates LangGraph as LangChain's original agent-building approach
(`AgentExecutor` running a ReAct-style loop), still used for simpler
agent needs where LangGraph's full graph flexibility isn't required.

PYDANTICAI: Built by the team behind the Pydantic data-validation
library — brings STRONG TYPE VALIDATION to agent outputs and tool
inputs/outputs specifically (structured outputs are Pydantic models,
validated automatically), appealing to teams who want the same rigor
Pydantic brings to API development applied to agent-building.

SEMANTIC KERNEL: Microsoft's open-source, provider-agnostic SDK
(distinct from Microsoft Agent Framework, L15, though from the same
company) with strong support for MULTIPLE PROGRAMMING LANGUAGES (C#,
Python, Java) beyond the Python-first norm of most other frameworks in
this domain — relevant for enterprises with existing .NET/Java investment
wanting agent capabilities without a full Python migration.

GOOGLE ADK (Agent Development Kit): Google's agent-building framework,
with native integration into Vertex AI and Gemini models — Google's
equivalent positioning to OpenAI's Agents SDK, for teams building
specifically on Google Cloud's AI stack.

AWS BEDROCK AGENTS: A FULLY MANAGED agent service on AWS — you configure
an agent (instructions, action groups mapping to Lambda functions,
knowledge bases for RAG) largely through AWS console/API configuration
rather than writing an agent LOOP yourself; AWS handles the underlying
orchestration. This is meaningfully different from the code-first SDKs
above — closer to a managed PRODUCT than a library you import.

AZURE AI FOUNDRY AGENT SERVICE: Azure's analogous managed agent hosting
service — configure agents against Azure OpenAI models with built-in
tool/knowledge integration, positioned similarly to Bedrock Agents as a
managed alternative to self-orchestrated code.

PRODUCTION USE CASE:
A team already deeply invested in AWS (Lambda, existing knowledge bases
in OpenSearch, IAM-based access control) builds their support agent on
AWS Bedrock Agents specifically to avoid re-implementing orchestration,
auth, and observability that the managed service provides out of the
box — accepting AWS lock-in as a reasonable tradeoff given their
existing infrastructure commitment.

COMMON MISTAKES:
- Choosing a vendor-native SDK for provider-agnosticism reasons when the
  team is NOT actually committed to that provider — the whole point of
  these SDKs is tighter integration in exchange for some lock-in; if you
  might switch model providers later, a framework from Phase 3
  (LangGraph/CrewAI) is the better-hedged choice.
- Assuming a managed service (Bedrock Agents, Azure AI Foundry) gives
  you the SAME fine-grained control as a code-first SDK — managed
  services trade control for operational simplicity; a task needing
  precise custom orchestration logic might not fit the managed
  configuration model well.
- Ignoring PydanticAI specifically when structured, validated tool
  inputs/outputs are a genuine requirement (e.g. an agent that MUST
  return a strictly-typed JSON object for a downstream system) — other
  frameworks CAN enforce this too, but PydanticAI's validation is a
  first-class, less bolted-on feature.
"""

import textwrap


# ------------------------------------------------------------------
# 1. OpenAI Agents SDK — handoffs between specialized agents
# ------------------------------------------------------------------
OPENAI_AGENTS_SDK_EXAMPLE = textwrap.dedent("""\
    from agents import Agent, Runner

    billing_agent = Agent(
        name="Billing Agent",
        instructions="Handle billing and refund questions.",
        tools=[process_refund_tool],
    )

    triage_agent = Agent(
        name="Triage Agent",
        instructions="Route the user to the right specialized agent.",
        handoffs=[billing_agent],   # a lightweight multi-agent primitive:
                                      # this agent can HAND OFF the
                                      # conversation to billing_agent when
                                      # appropriate, distinct from
                                      # CrewAI's task-based delegation or
                                      # AutoGen's group-chat manager.
    )

    result = Runner.run_sync(triage_agent, "I need a refund for my order")
    # Built-in tracing captures the full handoff/tool-call sequence for
    # debugging, viewable via OpenAI's tracing dashboard.
""")

# ------------------------------------------------------------------
# 2. PydanticAI — validated, typed agent outputs
# ------------------------------------------------------------------
PYDANTICAI_EXAMPLE = textwrap.dedent("""\
    from pydantic import BaseModel
    from pydantic_ai import Agent

    class RefundDecision(BaseModel):
        approved: bool
        amount_usd: float
        reason: str

    agent = Agent(
        "openai:gpt-4o",
        result_type=RefundDecision,   # the agent's output is VALIDATED
                                        # against this schema automatically
                                        # — a malformed/incomplete LLM
                                        # response raises a validation
                                        # error rather than silently
                                        # passing through unstructured text.
    )

    result = agent.run_sync("Should I approve a refund for order #12345?")
    decision: RefundDecision = result.data   # guaranteed to match the schema
""")

# ------------------------------------------------------------------
# 3. AWS Bedrock Agents — a managed service, not a code-first library
# ------------------------------------------------------------------
BEDROCK_AGENTS_NOTE = textwrap.dedent("""\
    AWS Bedrock Agents are configured largely through AWS's console/API,
    not written as agent-loop code:

      1. Define the agent's instructions and underlying Bedrock model.
      2. Define ACTION GROUPS — each maps agent-callable actions to a
         Lambda function (the actual tool implementation) via an OpenAPI
         schema describing the action's parameters.
      3. Attach KNOWLEDGE BASES — Bedrock-managed RAG (L03-L04's pattern)
         over your documents, integrated automatically into the agent's
         reasoning without you wiring retrieval code yourself.

    boto3 invocation (calling an ALREADY-CONFIGURED agent):
        import boto3
        client = boto3.client("bedrock-agent-runtime")
        response = client.invoke_agent(
            agentId="AGENT_ID", agentAliasId="ALIAS_ID",
            sessionId="session-1", inputText="I need a refund",
        )
    # AWS handles the underlying orchestration loop, tool-calling
    # mechanics, and RAG retrieval — you configure WHAT the agent can do,
    # not HOW the loop mechanically executes.
""")

# ------------------------------------------------------------------
# 4. Semantic Kernel — multi-language, provider-agnostic
# ------------------------------------------------------------------
SEMANTIC_KERNEL_NOTE = textwrap.dedent("""\
    from semantic_kernel import Kernel
    from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion

    kernel = Kernel()
    kernel.add_service(OpenAIChatCompletion(ai_model_id="gpt-4o", api_key="..."))

    # Semantic Kernel's PLUGIN model is conceptually similar to "tools"
    # in other frameworks, but its distinguishing feature is genuine
    # multi-language parity — the SAME conceptual API exists in C# and
    # Java, not just Python, relevant for enterprises with substantial
    # non-Python codebases wanting agent capabilities without a full
    # rewrite into Python.
""")

# ------------------------------------------------------------------
# 5. Landscape summary
# ------------------------------------------------------------------
SDK_LANDSCAPE_SUMMARY = {
    "OpenAI Agents SDK": "Lightweight, OpenAI-native, handoff-based multi-agent primitive, built-in tracing.",
    "LangChain Agents": "LangChain's original (pre-LangGraph) provider-agnostic ReAct-style agent executor.",
    "PydanticAI": "Strong typed/validated structured outputs as a first-class feature.",
    "Semantic Kernel": "Microsoft, provider-agnostic, genuine multi-language (C#/Java/Python) parity.",
    "Google ADK": "Google-native, tight Vertex AI/Gemini integration.",
    "AWS Bedrock Agents": "Fully managed AWS service — configure via console/API, not a code-first loop.",
    "Azure AI Foundry Agent Service": "Azure's managed analogue to Bedrock Agents, for Azure OpenAI models.",
}


if __name__ == "__main__":
    print(OPENAI_AGENTS_SDK_EXAMPLE)
    print(PYDANTICAI_EXAMPLE)
    print(BEDROCK_AGENTS_NOTE)
    print(SEMANTIC_KERNEL_NOTE)
    print("=== SDK landscape summary ===")
    for sdk, note in SDK_LANDSCAPE_SUMMARY.items():
        print(f"{sdk}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
An insurance company's claims-processing agent MUST return a strictly-
typed decision object (approved: bool, payout_amount: float, denial_reason:
Optional[str]) that feeds directly into a downstream payment system with
zero tolerance for malformed output — they choose PydanticAI specifically
because its validation is enforced at the framework level (a malformed
LLM response raises an exception before ever reaching the payment
system), rather than relying on manually parsing and validating a more
loosely-typed agent framework's raw text output themselves.
"""
