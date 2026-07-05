# ============================================================
# L25: Choosing Your Stack — A Decision Framework Across the Full Ecosystem
# ============================================================
# WHAT: A structured decision framework for picking ONE tool per
#       category (LLM provider, RAG framework, agent framework, vector
#       DB, memory, observability, guardrails) given a specific use
#       case — turning the full L01-L24 ecosystem map into an actual,
#       defensible set of choices instead of analysis paralysis.
# WHY: Every individual lesson in this domain covered one category in
#      isolation, often presenting several valid options. A real project
#      needs to actually CHOOSE, quickly and defensibly, and then move
#      on to building — this lesson is the bridge between "I understand
#      the landscape" and "here's what I'm actually using and why."
# LEVEL: Capstone (Phase 7 of 7 — second-to-last lesson)
# ============================================================

"""
CONCEPT OVERVIEW:
The full ecosystem map from this domain has roughly a dozen decision
points, but they're not independent — choices in one category constrain
or strongly influence others. A practical approach is to answer a SMALL
number of HIGH-LEVERAGE questions FIRST, since they narrow the remaining
choices significantly:

1. DATA SENSITIVITY/COMPLIANCE (L01): can data leave your infrastructure
   at all? If NO, this immediately rules out every hosted API/managed
   service across EVERY category (hosted LLMs, managed vector DBs,
   SaaS observability platforms) — you're building on open-weight models
   (L01) self-hosted via vLLM, a self-hostable vector DB (Qdrant, Weaviate,
   Milvus, pgvector — L03), and open-source tracing (Langfuse, Arize
   Phoenix — L23), full stop, before considering any other factor.

2. TASK PREDICTABILITY (L17): is the workflow's structure known in
   advance, or does it need to be discovered/adapted at runtime? This
   determines whether you need an AGENT at all (vs a static RAG
   pipeline, L04) and, if so, which orchestration paradigm (L13-L16)
   fits — a fixed sequence favors CrewAI sequential or a simple
   LangGraph chain; genuine unpredictability favors AutoGen or CAMEL.

3. TEAM COMPOSITION AND EXISTING INVESTMENT: is the team already
   committed to a specific cloud (AWS/Azure/GCP)? This strongly favors
   that cloud's native offerings (Bedrock Agents + Bedrock Guardrails +
   Bedrock KV for AWS; Azure AI Foundry + Azure AI Content Safety for
   Azure) over provider-agnostic alternatives, trading some flexibility
   for integration depth and reduced operational surface area.

4. SCALE AND CONCURRENCY: how many concurrent users/agent instances at
   steady state? Low-to-moderate scale rarely needs to worry about
   per-agent framework overhead (any of L13-L16's frameworks are fine);
   very high concurrency (thousands of simultaneous agent sessions)
   makes lightweight framework overhead (Agno, L16) and inference
   serving efficiency (vLLM, L01; LLM Quantization & Inference Notes)
   genuinely load-bearing decisions, not premature optimization.

5. CUSTOMIZATION NEEDS: does the use case fit an opinionated platform's
   (RAGFlow's, L11; a managed agent service's, L18) built-in patterns, or
   does it need fine-grained control a composable library (LangChain/
   LlamaIndex/LangGraph) provides? This is a real build-vs-buy tradeoff,
   not a "which is objectively better" question.

PRODUCTION USE CASE:
See the two worked examples below — a regulated healthcare RAG system
and a fast-moving startup's customer-support agent — each answering the
five questions above in a DIFFERENT way, landing on genuinely different
(and each individually well-justified) technology stacks.

COMMON MISTAKES:
- Making per-category tool choices INDEPENDENTLY without first answering
  the high-leverage questions (data sensitivity, task predictability,
  cloud commitment) that should constrain and simplify most of the
  remaining choices — this leads to incoherent stacks (e.g. a fully
  self-hosted, air-gapped vector DB paired with a hosted-API-only LLM
  provider that violates the same compliance requirement).
- Treating every choice as equally consequential and spending equal
  analysis time on all of them — the LLM provider and orchestration
  paradigm choices are usually far more consequential (harder to
  change later, affect the most other decisions) than, say, which
  specific observability dashboard to use.
- Choosing based on what's currently most discussed/popular rather than
  the concrete answers to your own project's five questions — popularity
  is weak evidence for fit to YOUR specific constraints.
"""

from dataclasses import dataclass


# ------------------------------------------------------------------
# 1. The five high-leverage questions, as a structured checklist
# ------------------------------------------------------------------
@dataclass
class StackDecision:
    category: str
    choice: str
    reasoning: str


HIGH_LEVERAGE_QUESTIONS = [
    "Can data leave your infrastructure? (compliance/sensitivity)",
    "Is the task's structure known in advance, or discovered at runtime?",
    "Is the team already committed to a specific cloud provider?",
    "What's the expected scale/concurrency at steady state?",
    "Does the use case fit an opinionated platform, or need fine-grained "
    "composability?",
]


# ------------------------------------------------------------------
# 2. Worked example A — a regulated healthcare RAG system
# ------------------------------------------------------------------
def healthcare_rag_stack() -> list[StackDecision]:
    return [
        StackDecision("LLM", "Self-hosted open-weight model (Llama/Mistral) via vLLM",
                       "Data cannot leave infrastructure (HIPAA-adjacent compliance) — "
                       "rules out every hosted API provider (L01)."),
        StackDecision("Embeddings", "Self-hosted Sentence Transformers / BGE",
                       "Same data-residency constraint rules out hosted embedding APIs (L02)."),
        StackDecision("Vector DB", "Qdrant, self-hosted",
                       "Self-hostable, strong filtering (for patient/record-level "
                       "access control), no managed-service data exposure (L03)."),
        StackDecision("RAG framework", "Haystack",
                       "Extractive reader option (L07) satisfies a requirement for "
                       "exact-quote sourcing from clinical documents, not paraphrase."),
        StackDecision("Agent framework", "None — static RAG pipeline",
                       "Task structure is fixed/predictable (retrieve clinical docs, "
                       "answer) — no agent complexity/unpredictability needed (L17)."),
        StackDecision("Security", "Presidio (PII redaction) + on-prem Guardrails AI",
                       "PII detection mandatory; self-hostable guardrail tools only, "
                       "per the same data-residency constraint (L22)."),
        StackDecision("Observability", "Langfuse, self-hosted",
                       "Framework-agnostic, self-hostable — SaaS tracing platforms "
                       "would violate the data-residency constraint (L23)."),
    ]


# ------------------------------------------------------------------
# 3. Worked example B — a fast-moving startup's customer-support agent
# ------------------------------------------------------------------
def startup_support_agent_stack() -> list[StackDecision]:
    return [
        StackDecision("LLM", "OpenAI GPT-4o (hosted API)",
                       "No data-residency constraint; speed of iteration matters "
                       "more than infrastructure control at this stage (L01)."),
        StackDecision("Embeddings", "OpenAI text-embedding-3-small",
                       "Consistent with the hosted-API choice; no self-hosting "
                       "overhead needed at current scale (L02)."),
        StackDecision("Vector DB", "Pinecone (managed)",
                       "Zero infrastructure to manage — matches the team's "
                       "small-team, fast-iteration priorities (L03)."),
        StackDecision("Agent framework", "LangGraph",
                       "Task genuinely needs multi-step tool use (order lookup, "
                       "refund processing) with human-in-the-loop approval for "
                       "refunds over a threshold — LangGraph's interrupts fit "
                       "this exactly (L13)."),
        StackDecision("Memory", "Mem0 + Redis",
                       "Needs cross-session user preference memory without "
                       "building extraction/consolidation logic from scratch (L20)."),
        StackDecision("Security", "Lakera Guard (hosted)",
                       "Fast to integrate, no self-hosting overhead, adequate "
                       "given the lower sensitivity of support-ticket data (L22)."),
        StackDecision("Observability", "LangSmith",
                       "Tight LangGraph integration, fastest path to full "
                       "tracing given the LangGraph choice above (L23)."),
    ]


def print_stack(name: str, decisions: list[StackDecision]):
    print(f"=== {name} ===")
    for d in decisions:
        print(f"  {d.category}: {d.choice}")
        print(f"    reasoning: {d.reasoning}\n")


if __name__ == "__main__":
    print("High-leverage questions to answer FIRST:")
    for i, q in enumerate(HIGH_LEVERAGE_QUESTIONS, 1):
        print(f"  {i}. {q}")
    print()

    print_stack("Healthcare RAG system (regulated, compliance-constrained)",
                 healthcare_rag_stack())
    print_stack("Startup customer-support agent (fast-moving, no compliance constraint)",
                 startup_support_agent_stack())

"""
FINAL CONTEXT:
Notice how DIFFERENT these two stacks are, despite both being legitimate,
well-reasoned choices from the SAME ecosystem map — the healthcare
system's every choice traces back to the data-residency constraint
answered first; the startup's every choice traces back to prioritizing
iteration speed given no such constraint. Neither stack is "the right
one" in the abstract — the five high-leverage questions, answered
HONESTLY for your specific project, are what should drive the choice,
not which tool is most discussed or has the most GitHub stars.
"""
