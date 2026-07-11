# ============================================================
# L08: Production Architecture & Responsible AI on Azure — Capstone
# ============================================================
# WHAT: Capstone — a full reference architecture wiring together L01-L07
#       (gateway, Azure OpenAI, Search, Agent Service) with production
#       concerns specific to regulated Azure AI deployments: Responsible
#       AI evaluation (accuracy, hallucination, bias, latency), Azure
#       Content Safety, observability via Azure Monitor/App Insights,
#       and CI/CD for AI workloads.
# WHY: This is the lesson that answers "how do all these Azure AI
#      pieces become one production system a bank's model-governance
#      board will actually approve" — the evaluation/compliance layer
#      is what separates a working prototype from something deployable
#      in a regulated enterprise.
# LEVEL: Architect (Lesson 8 of 8 — Capstone)
# ============================================================

"""
CONCEPT OVERVIEW:

MODEL EVALUATION: accuracy, hallucination, bias, latency, throughput
--------------------------------------------------------------------------
Azure AI Foundry ships built-in EVALUATION tooling (the `azure-ai-
evaluation` SDK) covering the metric categories a Responsible AI
sign-off requires:
  - ACCURACY/QUALITY: groundedness (does the answer stay faithful to
    retrieved context — the RAG-specific check), relevance, coherence,
    fluency — each scored by an LLM-as-judge evaluator, a technique
    covered generically in Agentic AI & RAG Notes L23 (agent
    observability and evaluation).
  - HALLUCINATION DETECTION: specifically the groundedness metric
    applied to RAG outputs — flags claims in the answer NOT supported
    by the retrieved chunks (L04), which is what "hallucination" means
    operationally for a RAG system, as distinct from a base model just
    being wrong about world knowledge.
  - BIAS: fairness evaluators checking for disparate output quality or
    sentiment across protected attributes in the input — directly
    parallel to MLOps Notes L11's demographic parity/equalized odds
    concepts, applied to generative outputs rather than classifier
    predictions.
  - LATENCY & THROUGHPUT: p50/p95/p99 response time and tokens/sec,
    tracked per deployment (Standard vs PTU, L02) since this is exactly
    what PTU capacity exists to guarantee.
These evaluators run BOTH offline (against a curated test set, gating a
deployment before go-live) and online (sampled against live traffic,
continuously) — the same offline/online evaluation split covered
generically in MLOps Notes L09/L10.

AZURE AI CONTENT SAFETY: a dedicated moderation layer
------------------------------------------------------------
Beyond the content filtering built into every Azure OpenAI call (L02),
Azure AI Content Safety is a STANDALONE service for moderating content
that DIDN'T come from an LLM call — user-uploaded images, user-typed
messages before they even reach a prompt, or content from third-party
sources being ingested into a RAG index (L04). It also provides PROMPT
SHIELDS specifically for detecting jailbreak/prompt-injection attempts
embedded in user input or in RETRIEVED DOCUMENTS (an "indirect prompt
injection" — malicious instructions hidden inside a document that gets
retrieved and fed to the model as context) — a threat model covered
generically in Agentic AI & RAG Notes L22, made concrete here as a
specific Azure API to call on every retrieved chunk before it enters a
prompt, not just on the user's own message.

OBSERVABILITY: Azure Monitor + Application Insights for AI workloads
-------------------------------------------------------------------------
The AI Hub gateway's logging (L07) typically lands in AZURE MONITOR /
APPLICATION INSIGHTS — the same platform used for general application
observability (Observability Notes), extended with AI-specific signals:
token usage per request (cost), content-filter trigger rates (safety),
groundedness/evaluation scores sampled on live traffic (quality
regression detection), and latency broken down by deployment tier.
DISTRIBUTED TRACING (Observability Notes L05) matters especially for
agentic systems (L07) — a single user request can fan out into
multiple tool calls and model calls, and a trace ties them all together
under one request ID so a slow or failed agent run can be diagnosed
step by step rather than as an opaque black box.

CI/CD FOR AI WORKLOADS: prompts and evaluations as versioned artifacts
------------------------------------------------------------------------------
Production AI CI/CD on Azure extends the patterns in CICD Notes with
AI-specific gates: PROMPT TEMPLATES are versioned in source control
(not edited live in a portal), and a pipeline stage runs the OFFLINE
EVALUATION SUITE (the accuracy/groundedness/bias checks above) against
a new prompt version or model deployment BEFORE it can be promoted —
exactly the same "tests gate the deploy" discipline as CICD Notes L03,
with LLM evaluation scores standing in for unit-test pass/fail. A
prompt or model version that regresses groundedness or spikes bias
scores fails the pipeline the same way a broken unit test would.

RESPONSIBLE AI GOVERNANCE: the organizational layer
------------------------------------------------------------
Underneath the tooling sits an organizational process: a MODEL CARD
(MLOps Notes L11) documenting intended use, known limitations, and
evaluation results for each deployed prompt/model configuration; a
GOVERNANCE BOARD sign-off gate before a new AI feature reaches
regulated customer-facing use; and a clear map of WHICH regulatory
framework applies (banking model-risk-management requirements are
generally stricter than a generic SaaS product's) — the reason
"understanding of AI governance, model risk, data privacy... in a
regulated banking environment" appears as an explicit job requirement
rather than boilerplate.

PRODUCTION USE CASE — FULL REFERENCE ARCHITECTURE:
A bank's customer-service AI feature: user request -> AI Hub gateway
(L07: auth, rate limit, PII check) -> retrieved context from Azure AI
Search (L04, filtered by the user's access) -> Content Safety Prompt
Shields scan on retrieved chunks (indirect-injection check) -> Azure
OpenAI completion (L02, with its own content filter) -> groundedness
evaluator sampled on a percentage of live responses -> response
returned to user, with the full trace (gateway decision, retrieved
chunks, model call, evaluation score) logged to Application Insights
under one request ID. A monthly job re-runs the full offline evaluation
suite against the production prompt/model configuration and reports
drift in accuracy/bias/groundedness to the governance board.

COMMON MISTAKES:
- Treating Azure's built-in per-call content filter (L02) as sufficient
  moderation for content that never passes through an LLM call at all
  (user uploads, ingested documents) — that path needs Content Safety
  called directly.
- Running RAG groundedness evaluation only offline, before launch, and
  never sampling it against live traffic — retrieval quality and
  document corpus drift over time, and an offline-only check misses
  that drift entirely.
- Not applying Prompt Shields to RETRIEVED content, only to the user's
  own message — indirect prompt injection via a poisoned document in
  the search index is a distinct, often-missed attack surface from
  direct user-typed injection.
- Editing prompt templates directly in a portal/production config
  instead of versioning them in source control with an evaluation gate
  in the CI/CD pipeline — loses the ability to review, roll back, or
  A/B a prompt change with the same rigor as a code change.
- Skipping the model-card/governance-board process for an "internal
  tool" that later becomes customer-facing without ever going back
  through sign-off — governance debt that surfaces at the worst time,
  during an actual audit.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Offline evaluation gating a deployment (groundedness, bias, latency)
# ------------------------------------------------------------------
OFFLINE_EVALUATION_EXAMPLE = textwrap.dedent("""\
    from azure.ai.evaluation import GroundednessEvaluator, FluencyEvaluator, evaluate

    result = evaluate(
        data="eval_test_set.jsonl",     # curated Q/A + retrieved-context pairs
        evaluators={
            "groundedness": GroundednessEvaluator(model_config=judge_model_config),
            "fluency": FluencyEvaluator(model_config=judge_model_config),
        },
    )

    # CI/CD GATE: block promotion if quality regresses below threshold --
    # same "tests gate the deploy" discipline as CICD Notes L03, with
    # evaluation scores standing in for pass/fail unit tests.
    if result.metrics["groundedness.mean"] < 4.0:   # scored 1-5
        raise DeploymentBlocked("Groundedness regression -- promotion blocked")
""")

# ------------------------------------------------------------------
# 2. Content Safety Prompt Shields on RETRIEVED content, not just user input
# ------------------------------------------------------------------
PROMPT_SHIELDS_EXAMPLE = textwrap.dedent("""\
    from azure.ai.contentsafety import ContentSafetyClient

    client = ContentSafetyClient(endpoint=endpoint, credential=credential)

    retrieved_chunks = azure_ai_search_query(user_question)   # from L04

    for chunk in retrieved_chunks:
        shield_result = client.shield_prompt(
            user_prompt=user_question, documents=[chunk.content]
        )
        if shield_result.documents_analysis[0].attack_detected:
            # Indirect prompt injection hidden IN a retrieved document --
            # a distinct threat from the user's own message being malicious.
            audit_log.warning(f"Indirect injection detected in chunk {chunk.id}")
            retrieved_chunks.remove(chunk)
""")

# ------------------------------------------------------------------
# 3. Distributed trace tying gateway -> retrieval -> model -> eval together
# ------------------------------------------------------------------
DISTRIBUTED_TRACE_EXAMPLE = textwrap.dedent("""\
    from opentelemetry import trace

    tracer = trace.get_tracer("customer-service-agent")

    with tracer.start_as_current_span("handle_customer_request") as span:
        span.set_attribute("app_id", app_id)
        with tracer.start_as_current_span("gateway_checks"):
            gateway.enforce_policy(request)             # L07
        with tracer.start_as_current_span("retrieval"):
            chunks = azure_ai_search_query(request)      # L04
        with tracer.start_as_current_span("model_call"):
            response = call_azure_openai(chunks, request) # L02
        with tracer.start_as_current_span("groundedness_eval"):
            score = sample_evaluate_groundedness(response, chunks)  # this lesson
        span.set_attribute("groundedness_score", score)
    # One request ID ties every step together in Application Insights --
    # a failed or slow agent run is diagnosable step-by-step, not opaque.
""")

RESPONSIBLE_AI_METRIC_MAP = {
    "Accuracy / quality": "Groundedness, relevance, coherence, fluency evaluators",
    "Hallucination": "Groundedness score specifically, applied to RAG outputs",
    "Bias": "Fairness evaluators across protected attributes (parallels MLOps L11)",
    "Latency / throughput": "p50/p95/p99 + tokens/sec per deployment tier (L02)",
    "Direct prompt injection": "Content Safety Prompt Shields on user input",
    "Indirect prompt injection": "Prompt Shields applied to RETRIEVED documents",
}


if __name__ == "__main__":
    print(OFFLINE_EVALUATION_EXAMPLE)
    print(PROMPT_SHIELDS_EXAMPLE)
    print(DISTRIBUTED_TRACE_EXAMPLE)
    print("=== Responsible AI metric map ===")
    for concern, approach in RESPONSIBLE_AI_METRIC_MAP.items():
        print(f"{concern}: {approach}")

"""
PRODUCTION CONTEXT EXAMPLE:
A bank's customer-service AI feature ships only after its model card
(intended use, evaluation results, known limitations) clears the AI
governance board, its prompt templates are versioned in source control
with a CI/CD gate that blocks promotion on groundedness regression, its
retrieved search results pass through Content Safety Prompt Shields
before ever reaching a model prompt, and every request's full trace --
gateway decision through evaluation score -- lands in Application
Insights under one request ID, so a governance audit can reconstruct
exactly what happened on any individual customer interaction, not just
aggregate metrics.
"""
