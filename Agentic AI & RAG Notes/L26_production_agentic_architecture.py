# ============================================================
# L26: Production Agentic Architecture — Full Reference System
# ============================================================
# WHAT: A capstone lesson wiring together every layer from L01-L25 into
#       ONE coherent, production reference architecture — RAG, agents,
#       MCP, memory, observability, and security, composed as an actual
#       working system rather than isolated concepts.
# WHY: Every prior lesson covered one piece. Real production systems are
#      INTEGRATED — this lesson is where you see how the LLM layer, RAG
#      layer, agent orchestration, tool integration (MCP), memory,
#      guardrails, and observability all fit together end to end.
# LEVEL: Capstone (Phase 7 of 7 — final lesson)
# ============================================================

"""
CONCEPT OVERVIEW:
A production agentic system, assembled from this domain's pieces:

  1. FOUNDATION LAYER (L01-L03): a chosen LLM (hosted or self-hosted via
     vLLM), an embedding model, and a vector database — the substrate
     everything else builds on.
  2. RAG LAYER (L04-L11): document ingestion (with layout-aware parsing
     for real documents, L09), chunking, retrieval, and reranking —
     giving the agent access to your organization's actual knowledge,
     not just the model's training-time knowledge.
  3. AGENT ORCHESTRATION LAYER (L12-L18): a chosen orchestration
     paradigm (graph/team/conversation/event-driven) implementing the
     agent loop, with human-in-the-loop checkpoints for consequential
     actions.
  4. TOOL INTEGRATION LAYER (L19, L21): tools exposed via MCP servers
     (reusable across any agent framework), with well-designed schemas
     and tool-selection strategies at scale.
  5. MEMORY LAYER (L20): short-term conversation buffers plus long-term,
     retrieved (not dumped) memory for cross-session personalization/context.
  6. SECURITY LAYER (L22): sandboxed tools, guardrails against prompt
     injection, PII redaction, and restricted outbound paths preventing
     data exfiltration.
  7. OBSERVABILITY LAYER (L23): full tracing of every LLM/tool call, plus
     systematic evaluation (Ragas/TruLens/Promptfoo) catching regressions
     before they reach users.
  8. AUTOMATION LAYER (L24): wiring agent decisions into real-world
     actions, tiered by consequence (fully automated for low-stakes,
     human-approved for high-stakes).

This is not a rigid template — L25's decision framework determines which
SPECIFIC tool fills each layer for a given project's constraints — but
the LAYERS themselves, and how they connect, are the stable architectural
pattern most production agentic systems converge on regardless of which
specific tools occupy each layer.

PRODUCTION USE CASE:
See the full reference architecture and end-to-end request trace below
— this is the shape a mature, production-grade agentic system takes,
whether built on a fully self-hosted, compliance-driven stack (L25's
healthcare example) or a fast-moving, hosted-API-first stack (L25's
startup example) — the LAYERS and their responsibilities remain the
same even as the specific tool in each layer changes.

COMMON MISTAKES:
- Building the RAG/agent layers first and treating security/
  observability as an afterthought bolted on before launch — every
  lesson from L22-L23 is far cheaper to build in from the start than to
  retrofit onto a system already handling real user traffic.
- Skipping the memory layer entirely for a system that would clearly
  benefit from cross-session context, because it feels like a "nice to
  have" — for many real use cases (personal assistants, ongoing support
  relationships), memory is closer to a core requirement than an
  optional enhancement.
- Treating this architecture as one-size-fits-all rather than adapting
  layer boundaries and tool choices to the specific project's answers to
  L25's five high-leverage questions — the RIGHT architecture is this
  shape, populated with the RIGHT tools for your specific constraints,
  not a fixed prescription to copy verbatim.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Full reference architecture diagram
# ------------------------------------------------------------------
REFERENCE_ARCHITECTURE = r"""
    User Request
         |
         v
    +---------------------+
    | Security: input      |  <- PII redaction (Presidio), prompt
    | sanitization (L22)   |     injection screening (Lakera/Prompt Security)
    +----------+-----------+
               |
               v
    +---------------------+     +----------------------+
    | Memory: retrieve      |<--->| Long-term memory store |
    | relevant context (L20)|    | (Mem0/Zep + Chroma/Neo4j)|
    +----------+-----------+     +----------------------+
               |
               v
    +---------------------+     +----------------------+
    | Agent Orchestrator    |<--->| RAG Layer (L04-L11)   |
    | (LangGraph/CrewAI/    |     | Vector DB (L03) +      |
    |  AutoGen, L13-L17)    |     | reranking              |
    +----------+-----------+     +----------------------+
               |
               v
    +---------------------+     +----------------------+
    | Tool calls via MCP     |<--->| MCP Servers (L19):     |
    | (L19, L21)             |     | GitHub/Slack/DB/       |
    +----------+-----------+     | Filesystem/custom       |
               |                  +----------------------+
               v
    +---------------------+
    | Human-in-the-loop     |  <- for consequential actions only
    | checkpoint (L13, L24) |     (LangGraph interrupt / Temporal wait)
    +----------+-----------+
               |
               v
    +---------------------+     +----------------------+
    | Automation execution   |<--->| n8n/Zapier/Temporal   |
    | (L24)                  |     | (L24)                 |
    +----------+-----------+     +----------------------+
               |
               v
         Final Response
               |
               v
    +-------------------------------------------+
    | Observability (L23): LangSmith/Langfuse traces, |
    | Ragas/TruLens evaluation, Promptfoo regression   |
    | tests run continuously against this whole flow   |
    +-------------------------------------------+
"""

# ------------------------------------------------------------------
# 2. A concrete end-to-end request trace
# ------------------------------------------------------------------
END_TO_END_TRACE_EXAMPLE = textwrap.dedent("""\
    Request: "I need a refund for order ORD-88213, and remind me I'm
              vegetarian for next time I ask about food delivery."

    1. [Security, L22] Input scanned for injection patterns — clean.
    2. [Memory, L20] Retrieve relevant memories for this user — finds
       none relevant to THIS specific request (refund), but the second
       clause triggers a memory WRITE, not a read.
    3. [Agent, L13] LangGraph agent reasons: this needs a tool call to
       check order eligibility, THEN a memory-write action.
    4. [Tools via MCP, L19/L21] Calls "get_order_status" (via an MCP
       server wrapping the order database) — order is refund-eligible.
    5. [Human-in-the-loop, L13] Refund amount ($45) is BELOW the
       auto-approval threshold — proceeds without human review.
    6. [Automation, L24] Executes the refund via a Temporal workflow
       activity, durably — survives any infra hiccup mid-execution.
    7. [Memory, L20] Extracts and stores "user is vegetarian" as a new
       long-term semantic memory for this user.
    8. Final response generated: "Your refund for order ORD-88213 has
       been processed. I'll remember you're vegetarian for future
       food-related questions."
    9. [Observability, L23] The FULL trace above (every step, exact
       tool arguments/results, timing) is captured in Langfuse; this
       exact scenario exists as a Promptfoo regression test case,
       re-run automatically before any future prompt/model change.
""")

# ------------------------------------------------------------------
# 3. Layer responsibilities, summarized
# ------------------------------------------------------------------
LAYER_RESPONSIBILITIES = {
    "Foundation (L01-L03)": "Model, embeddings, vector storage — the substrate.",
    "RAG (L04-L11)": "Grounding the agent in your organization's actual knowledge.",
    "Agent orchestration (L12-L18)": "Multi-step reasoning and tool-use decisions.",
    "Tool integration (L19, L21)": "Reusable, well-described, protocol-standardized capabilities.",
    "Memory (L20)": "Cross-session context and personalization.",
    "Security (L22)": "Defense against injection, sandboxing, exfiltration prevention.",
    "Observability (L23)": "Tracing and systematic evaluation, catching regressions.",
    "Automation (L24)": "Turning agent decisions into real-world, tiered-by-risk actions.",
}


if __name__ == "__main__":
    print(REFERENCE_ARCHITECTURE)
    print(END_TO_END_TRACE_EXAMPLE)
    print("=== Layer responsibilities ===")
    for layer, responsibility in LAYER_RESPONSIBILITIES.items():
        print(f"{layer}: {responsibility}")

"""
FINAL CONTEXT:
The measure of having internalized this entire domain isn't "I can name
every tool in the ecosystem map" — it's being able to look at a NEW
project requirement, run L25's five questions, and confidently populate
every layer of THIS architecture with a specific, justified tool choice
— then know exactly which earlier lesson to revisit for the implementation
details of whichever layer you're building next. This folder is meant
to function as a working reference during that actual build, not a
one-time read-through.
"""
