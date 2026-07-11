# ============================================================
# L07: Azure Agentic Stack — AI Foundry Agent Service & the AI Hub Gateway
# ============================================================
# WHAT: Building agentic systems specifically on Azure — the AI Foundry
#       Agent Service (Azure's managed agent-hosting platform), and the
#       CENTRALIZED AI HUB GATEWAY pattern enterprises put in front of
#       every LLM/agent call for governance, observability, and
#       capacity management.
# WHY: Agentic AI & RAG Notes (L12-L26) covers agent concepts, tool use,
#      memory, and multi-agent patterns generically/framework-by-
#      framework. This lesson is "how those concepts get deployed and
#      governed specifically on Azure," which is what an Azure-shop job
#      posting actually means by "orchestration across enterprise
#      systems using a centralized AI Hub gateway."
# LEVEL: Advanced (Lesson 7 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
Two Azure-specific pieces complete the agentic picture beyond the
generic frameworks (LangGraph, CrewAI, Semantic Kernel/L06): a managed
HOSTING platform for agents (AI Foundry Agent Service), and a
GOVERNANCE layer in front of every model/agent call (the AI Hub
gateway pattern) that most enterprise Azure AI deployments require
before anything reaches production.

AZURE AI FOUNDRY AGENT SERVICE
------------------------------------
A managed platform (part of Azure AI Foundry, introduced in L01) for
BUILDING and HOSTING agents without operating your own orchestration
infrastructure. It provides, as first-class managed capabilities:
  - THREAD-based conversation state (persisted conversation history
    managed by the service, not your application database)
  - Built-in TOOL integrations (code interpreter in a sandboxed
    environment, file search backed by vector stores, and Azure AI
    Search integration for RAG-grounded agents, L04)
  - Native connections to Azure OpenAI models (L02) as the agent's
    reasoning engine
  - Enterprise auth/networking (VNet integration, managed identity)
    inherited from the surrounding Azure AI Foundry project
The trade-off versus self-hosting a LangGraph/CrewAI agent (Agentic AI
& RAG Notes L13/L14) on your own compute: less infrastructure to
operate and built-in enterprise auth/networking, at the cost of less
control over the exact orchestration logic and being tied to Azure's
tool/hosting model — the same generic "managed platform vs
self-hosted framework" trade-off that recurs throughout this whole
notes library (e.g. Kafka managed services vs self-hosted, MLOps Notes
L04's pipeline orchestrator choices), applied to agents specifically.

THE AI HUB GATEWAY PATTERN, IN FULL
------------------------------------------
L02 introduced this pattern for Azure OpenAI calls specifically; here
it's the general architecture for ALL LLM/agent traffic in a large
organization. A centralized gateway (built on Azure API Management, or
a custom service) sits between every calling application and the
underlying Azure OpenAI resources/Agent Service deployments, and is
responsible for:

  1. AUTHENTICATION & AUTHORIZATION per calling application — each app
     gets its own identity and scoped permissions, never a shared key.
  2. RATE LIMITING & QUOTA ALLOCATION — the shared Tokens-Per-Minute
     budget (L02) is divided per application so one team's traffic
     spike can't starve another's production workload.
  3. USAGE & COST ATTRIBUTION — every call is tagged back to the
     calling application/business unit, so the platform team can answer
     "what did the fraud-detection feature cost us in tokens this
     month" without per-app instrumentation.
  4. MODEL/DEPLOYMENT ROUTING — requests get routed to the appropriate
     deployment (Standard vs PTU, L02; or even across regions/model
     providers for resilience) based on priority, cost policy, or
     failover need.
  5. CENTRALIZED OBSERVABILITY — every prompt, completion, content-
     filter result, latency, and token count flows through ONE logging
     pipeline (feeding the observability practices in L08), rather than
     each application team building its own.
  6. GOVERNANCE ENFORCEMENT — a single point to enforce organization-
     wide policy (e.g. "no PII may be sent to a model outside this
     region," or "code-execution tool calls require this additional
     approval step") without trusting every application team to
     reimplement the same checks correctly.

This is exactly the pattern referenced by job postings describing LLM
calls "routed through a centralized AI Hub gateway for governance,
observability, and capacity management" — it is an ARCHITECTURE
pattern, not a single named Azure product; different organizations
build it on Azure API Management, a custom FastAPI service (FastAPI &
Python Web Notes), or increasingly Azure AI Foundry's own built-in
project-level governance features.

AGENT ORCHESTRATION ACROSS ENTERPRISE SYSTEMS
------------------------------------------------------
"Orchestration across enterprise systems" in a job description means
an agent's TOOLS are calls into real internal systems — a core banking
API, a CRM, an internal knowledge base (via Azure AI Search, L04) —
not just web search or a calculator. This raises the stakes on the
tool-use security concerns covered generically in Agentic AI & RAG
Notes L22 (AI agent security): a tool that can actually move money or
modify a customer record needs human-in-the-loop approval gates
(Agentic AI & RAG Notes L13's interrupt pattern, or Semantic Kernel's
inspectable plan objects, L06) before execution — never a fully
autonomous agent with unreviewed write access to production systems in
a regulated environment.

PRODUCTION USE CASE:
A bank builds a customer-service agent on Azure AI Foundry Agent
Service with tools for account lookup (read-only, auto-approved) and
dispute filing (a write action, requiring a human-in-the-loop approval
step before execution). All calls — including the agent's internal
reasoning calls to Azure OpenAI — route through the bank's AI Hub
gateway, which enforces per-app rate limits, logs every tool
invocation for audit, and would block (at the gateway level) any
attempt to route a request containing detected PII (via the Language
Service's PII detection, L03) to a model deployment outside the
bank's approved data-residency region.

COMMON MISTAKES:
- Giving an agent WRITE-capable tools (transactions, record updates)
  with full autonomy in a regulated environment, without a human-in-
  the-loop approval gate for that specific tool class — the single most
  common agentic-AI compliance failure mode in banking/financial
  deployments.
- Letting individual application teams call Azure OpenAI/Agent Service
  directly, bypassing the AI Hub gateway "just this once" for a
  prototype that then ships to production without ever adding the
  governance layer back in.
- Choosing to self-host a full LangGraph/CrewAI orchestration stack
  when Azure AI Foundry Agent Service's managed thread state and
  built-in tool integrations would have covered the requirement with
  far less operational surface to maintain.
- Treating "AI Hub gateway" as a specific Azure product to go provision
  — it's an architecture pattern the team builds (typically on Azure
  API Management), not a checkbox to enable.
- Not logging tool CALLS (not just model completions) through the
  gateway/observability pipeline — for agentic systems, "what tool did
  the agent invoke, with what arguments" is often the more important
  audit signal than the model's raw text output.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Azure AI Foundry Agent Service — thread-based agent with tools
# ------------------------------------------------------------------
AGENT_SERVICE_EXAMPLE = textwrap.dedent("""\
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    project_client = AIProjectClient.from_connection_string(
        credential=DefaultAzureCredential(), conn_str=project_connection_string
    )

    agent = project_client.agents.create_agent(
        model="gpt4o-mini-chat",           # the L01/L02 deployment name
        name="customer-service-agent",
        instructions="Help customers with account questions. Escalate disputes for approval.",
        tools=[account_lookup_tool, file_dispute_tool],   # write tool needs approval, below
    )

    thread = project_client.agents.create_thread()   # SERVICE-managed conversation state
    project_client.agents.create_message(thread.id, role="user", content=customer_question)
    run = project_client.agents.create_run(thread.id, agent.id)
""")

# ------------------------------------------------------------------
# 2. Human-in-the-loop gate on a WRITE-capable tool
# ------------------------------------------------------------------
HUMAN_IN_THE_LOOP_TOOL_EXAMPLE = textwrap.dedent("""\
    def file_dispute_tool(account_id: str, amount: float, reason: str) -> str:
        # A WRITE action -- never auto-execute in a regulated environment.
        approval_request = submit_for_human_approval(
            action="file_dispute", account_id=account_id, amount=amount, reason=reason
        )
        if not approval_request.wait_for_approval(timeout_s=300):
            return "Dispute requires manager approval -- request submitted, pending review."
        return core_banking_api.file_dispute(account_id, amount, reason)

    # account_lookup_tool, by contrast, is READ-ONLY and auto-approved --
    # the tool's write/read status, not the agent's "trustworthiness,"
    # is what decides whether a human gate is required.
""")

# ------------------------------------------------------------------
# 3. AI Hub gateway: routing + governance enforcement (simplified)
# ------------------------------------------------------------------
AI_HUB_GATEWAY_EXAMPLE = textwrap.dedent("""\
    class AIHubGateway:
        def route_request(self, app_id: str, request: LLMRequest) -> LLMResponse:
            self._enforce_rate_limit(app_id)                     # per-app TPM budget
            if self._contains_pii(request.prompt):                # Language Service, L03
                self._block_or_redact(request, app_id)             # governance enforcement
            deployment = self._select_deployment(request.priority) # Standard vs PTU, L02
            response = self._call_azure_openai(deployment, request)
            self._log_for_observability(app_id, request, response) # feeds L08's monitoring
            self._attribute_cost(app_id, response.usage.total_tokens)
            return response
""")

GATEWAY_RESPONSIBILITIES = {
    "Auth/authz per app": "Managed identity + RBAC (L01), never a shared key",
    "Rate limiting": "Per-app slice of the shared TPM quota (L02)",
    "Cost attribution": "Every call tagged back to calling app/business unit",
    "Deployment routing": "Standard vs PTU, or cross-region failover",
    "Observability": "One logging pipeline feeding L08's monitoring",
    "Governance": "PII/region policy enforcement in one place, not per-app",
}


if __name__ == "__main__":
    print(AGENT_SERVICE_EXAMPLE)
    print(HUMAN_IN_THE_LOOP_TOOL_EXAMPLE)
    print(AI_HUB_GATEWAY_EXAMPLE)
    print("=== AI Hub gateway responsibilities ===")
    for responsibility, note in GATEWAY_RESPONSIBILITIES.items():
        print(f"{responsibility}: {note}")

"""
PRODUCTION CONTEXT EXAMPLE:
A bank's customer-service agent, built on Azure AI Foundry Agent
Service, has a read-only account-lookup tool that executes immediately
and a dispute-filing tool that always pauses for human approval before
touching the core banking API -- every model call the agent makes,
plus every tool invocation with its arguments, passes through the
bank's AI Hub gateway, which blocks any request containing detected
account-number PII from being routed to a model deployment outside the
bank's approved region, and tags token usage back to the customer-
service product line for monthly cost reporting.
"""
