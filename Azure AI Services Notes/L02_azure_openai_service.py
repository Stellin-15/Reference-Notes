# ============================================================
# L02: Azure OpenAI Service — Deployments, Content Filtering, Quota
# ============================================================
# WHAT: Calling GPT-4.1/GPT-4o/GPT-4o-mini and embedding models through
#       Azure OpenAI Service specifically — the API surface differences
#       from raw OpenAI, content filtering, provisioned throughput, and
#       the centralized-gateway pattern enterprises route through it.
# WHY: LLM Frameworks Notes L01 covers the OpenAI API generically. This
#      lesson covers what's DIFFERENT when that same API is fronted by
#      Azure: deployment-based routing, Azure's content safety layer
#      wrapping every call, and the throughput/quota model that governs
#      cost and rate limits at enterprise scale.
# LEVEL: Core (Lesson 2 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
The Azure OpenAI API is intentionally close to the OpenAI API (chat
completions, embeddings, same message schema) so client code ports with
minimal changes — but three things are structurally different:

1. YOU CALL A DEPLOYMENT, NOT A MODEL
   The `model` parameter in a chat completion call is actually the
   DEPLOYMENT NAME you created in L01, not "gpt-4o" directly. This is a
   feature, not a limitation — it lets platform teams pin a deployment
   to a specific model version and swap it without every caller
   changing code.

2. EVERY REQUEST/RESPONSE PASSES THROUGH AZURE CONTENT SAFETY
   Azure OpenAI wraps every prompt AND every completion in a content
   filter — categories: hate, sexual, violence, self-harm — each scored
   on a severity scale, plus jailbreak/prompt-injection detection. A
   filtered request raises an error with a `content_filter` finish
   reason rather than silently returning nothing. This is NOT optional
   on standard deployments (only specific approved use cases can
   request modified filtering), and it means error handling must
   distinguish "filtered" from "failed" from "rate limited."

3. TWO CAPACITY MODELS: STANDARD vs PROVISIONED THROUGHPUT (PTU)
   - Standard: pay-per-token, shared capacity, quota measured in
     Tokens-Per-Minute (TPM) per deployment — the default, good for
     variable/bursty load.
   - Provisioned Throughput Units (PTU): reserved, dedicated capacity
     you pay for whether you use it or not — predictable latency, no
     "noisy neighbor" throttling, the right choice for latency-SLA'd
     production workloads at sustained volume (e.g. a customer-facing
     chat feature with a P99 latency commitment).
   A production architecture often mixes both: PTU for guaranteed
   baseline load, Standard as a "spillover" deployment for burst
   traffic — covered as a routing pattern in L08.

MODEL FAMILY: GPT-4.1, GPT-4o, GPT-4o-mini
--------------------------------------------
- GPT-4o: multimodal (text+vision+audio-adjacent), strong general
  reasoning, the default "workhorse" for most enterprise use cases.
- GPT-4o-mini: much cheaper/faster, weaker reasoning — the right choice
  for high-volume, low-complexity tasks (classification, extraction,
  simple summarization) where GPT-4o would be paying for capability you
  don't need.
- GPT-4.1: a later-generation model with a longer context window and
  improved instruction-following, particularly for coding/agentic
  tool-use tasks — the trend across model families (Azure's included) is
  toward "route by task complexity," not one model for everything, a
  pattern already covered generically in Event-Driven & Real-Time AI
  Systems Notes L07 (multi-model LLM routing) and revisited Azure-
  specifically in L07 of this domain.

THE "AI HUB GATEWAY" PATTERN
------------------------------
Large enterprises virtually never let application teams call an Azure
OpenAI resource directly. Instead, all traffic routes through a
CENTRALIZED GATEWAY (built on Azure API Management, or a purpose-built
service) that sits in front of one or more Azure OpenAI resources and
is responsible for: authentication/authorization per calling app,
per-app rate limiting and quota allocation (so one noisy app can't
starve others of the shared TPM budget), usage/cost attribution back to
business units, centralized logging for audit and observability, and
model/deployment ROUTING (e.g. sending a request tagged "high-priority"
to a PTU deployment and everything else to Standard). This is exactly
the pattern referenced by job descriptions mentioning routing LLM calls
"through a centralized AI Hub gateway for governance, observability,
and capacity management" — L07 builds this pattern end to end.

PRODUCTION USE CASE:
A customer support summarization feature uses GPT-4o-mini (cheap, fast,
good enough for extractive summarization) behind the AI Hub gateway,
with the gateway routing to a PTU deployment during business hours (for
latency SLA) and falling back to Standard capacity overnight. Content
filter results are logged (not just enforced) so the platform team can
tune thresholds and investigate false-positive filtering complaints
from support agents.

COMMON MISTAKES:
- Not handling the `content_filter` finish reason as a distinct case
  from a normal completion or an API error — a filtered response still
  returns HTTP 200 in some cases with partial content, and naive code
  treats it as a successful, complete answer.
- Sizing Standard-tier TPM quota for average load instead of peak load,
  causing 429 rate-limit errors during traffic spikes — PTU exists
  specifically to solve this for latency-sensitive paths.
- Using GPT-4o for every task regardless of complexity — the single
  biggest avoidable Azure OpenAI cost driver in enterprise deployments
  is not routing simple tasks to a cheaper/smaller model.
- Retrying a content-filtered request with the exact same prompt,
  assuming it was a transient failure — a filtered prompt will be
  filtered again; the retry logic needs to distinguish filter errors
  (don't naively retry) from rate-limit/timeout errors (do retry with
  backoff).
- Letting every application team provision and call their own Azure
  OpenAI resource directly instead of a shared, gatewayed resource —
  fragments quota and makes org-wide cost/usage visibility impossible.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Basic chat completion call — deployment name, not model name
# ------------------------------------------------------------------
BASIC_CALL_EXAMPLE = textwrap.dedent("""\
    from openai import AzureOpenAI

    client = AzureOpenAI(
        azure_endpoint="https://aoai-platform-prod.openai.azure.com/",
        api_key="...",              # or azure_ad_token_provider, see L01
        api_version="2024-10-21",
    )

    response = client.chat.completions.create(
        model="gpt4o-mini-chat",    # DEPLOYMENT name (L01), not "gpt-4o-mini"
        messages=[
            {"role": "system", "content": "You summarize support tickets in 2 sentences."},
            {"role": "user", "content": ticket_text},
        ],
        max_tokens=200,
        temperature=0.2,
    )

    choice = response.choices[0]
    if choice.finish_reason == "content_filter":
        # Distinct code path -- NOT a normal completion, NOT a naive-retry case.
        log_filtered_request(ticket_text, choice)
        return FALLBACK_MESSAGE
    return choice.message.content
""")

# ------------------------------------------------------------------
# 2. Reading content filter results explicitly (not just the finish reason)
# ------------------------------------------------------------------
CONTENT_FILTER_INSPECTION_EXAMPLE = textwrap.dedent("""\
    # Azure attaches a `content_filter_results` block to both the prompt
    # and the completion -- inspect it directly for severity, rather than
    # only reacting to a filtered finish_reason.
    prompt_filter = response.prompt_filter_results[0]["content_filter_results"]
    completion_filter = response.choices[0].content_filter_results

    for category in ("hate", "self_harm", "sexual", "violence"):
        severity = completion_filter.get(category, {}).get("severity")
        if severity in ("medium", "high"):
            audit_log.warning(f"{category} flagged at {severity} severity")

    jailbreak = prompt_filter.get("jailbreak", {})
    if jailbreak.get("detected"):
        # Directly relevant to Agentic AI & RAG Notes L22 (AI agent security) --
        # a jailbreak flag on the PROMPT is a signal worth alerting on, not
        # just silently blocking.
        security_alert("jailbreak_attempt", prompt=ticket_text)
""")

# ------------------------------------------------------------------
# 3. Standard vs PTU deployment routing (simplified gateway logic)
# ------------------------------------------------------------------
CAPACITY_ROUTING_EXAMPLE = textwrap.dedent("""\
    def choose_deployment(request_priority: str, current_ptu_load: float) -> str:
        # PTU: reserved capacity, guaranteed latency -- reserve it for the
        # traffic that actually has an SLA commitment.
        if request_priority == "high" and current_ptu_load < 0.9:
            return "gpt4o-ptu-prod"
        # Standard: shared, pay-per-token, elastic -- everything else,
        # including PTU spillover once the reserved capacity saturates.
        return "gpt4o-mini-standard"

    deployment = choose_deployment(request.priority, ptu_metrics.current_utilization())
    response = client.chat.completions.create(model=deployment, messages=request.messages)
""")

MODEL_SELECTION_GUIDE = {
    "gpt-4o-mini": "High-volume, low-complexity: classification, extraction, simple summaries",
    "gpt-4o": "General-purpose reasoning, multimodal input, the default workhorse",
    "gpt-4.1": "Long-context, coding/agentic tool-use, complex multi-step instruction-following",
}


if __name__ == "__main__":
    print(BASIC_CALL_EXAMPLE)
    print(CONTENT_FILTER_INSPECTION_EXAMPLE)
    print(CAPACITY_ROUTING_EXAMPLE)
    print("=== Model selection guide ===")
    for model, note in MODEL_SELECTION_GUIDE.items():
        print(f"{model}: {note}")

"""
PRODUCTION CONTEXT EXAMPLE:
A bank's call-center analytics pipeline routes call transcripts through
GPT-4o-mini for sentiment/intent tagging (cheap, high volume, simple
task) but escalates flagged "high-risk complaint" transcripts to GPT-4o
on a PTU deployment for a more nuanced compliance-review summary --
content filter severities on every call are logged to the same
observability pipeline as latency and token counts (L08), so a spike in
"self_harm" or "violence" severity flags becomes an alertable signal for
the fraud/risk team, not just a silently-blocked request.
"""
