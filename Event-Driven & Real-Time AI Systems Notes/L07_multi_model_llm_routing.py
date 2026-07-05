# ============================================================
# L07: Multi-Model LLM Routing — Claude, GPT, Gemini
# ============================================================
# WHAT: Routing a single application's LLM calls across MULTIPLE
#       providers (Claude/GPT/Gemini) — cost-based routing, fallback
#       chains for reliability, and the provider-abstraction layer that
#       makes swapping/routing between them possible without scattering
#       provider-specific code throughout an application.
# WHY: This repo's Agentic AI & RAG Notes L01 covered the LLM provider
#       LANDSCAPE (what each provider offers). This lesson covers the
#       PRODUCTION ENGINEERING problem of actually using SEVERAL of them
#       simultaneously in one system — for cost, reliability, and
#       capability-matching reasons — which is a distinct, real
#       architecture problem beyond just "pick one provider."
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
A PROVIDER ABSTRACTION LAYER is the foundational piece: application code
calls a UNIFORM internal interface ("generate(prompt, requirements)")
rather than directly calling OpenAI's, Anthropic's, or Google's
SDK-specific APIs — each of which has genuinely different request/
response shapes (Agentic AI & RAG Notes L01 showed this concretely: the
`max_tokens` requirement and message-role handling differ between OpenAI
and Anthropic). The abstraction layer's job is translating the uniform
internal call into each specific provider's actual API shape, so routing
DECISIONS (which provider to use for THIS request) can be made
independently of how each provider is actually called.

COST-BASED ROUTING sends different requests to different providers based
on their TOKEN PRICING and the request's actual requirements — a simple
classification task doesn't need the most expensive, highest-capability
model; routing it to a cheaper, faster model (potentially from a
DIFFERENT provider than your "default" for complex reasoning tasks)
while routing genuinely complex reasoning tasks to a more expensive,
higher-capability model directly reduces average cost per request
without sacrificing quality where it actually matters.

FALLBACK CHAINS address RELIABILITY: if a request to the PRIMARY
provider fails (rate limited, an outage, a timeout), automatically retry
against a SECONDARY provider rather than failing the user-facing request
entirely. This requires the provider abstraction layer to expose
functionally EQUIVALENT capabilities across providers (or gracefully
degrade if the fallback provider lacks a specific capability the primary
had, e.g. a specific function-calling format) — a naive fallback that
assumes IDENTICAL behavior across providers can produce subtly different
(not just slower) results when the fallback path activates.

PRODUCTION USE CASE:
A customer-support platform routes simple FAQ-style queries to a
cheaper, faster model, routes genuinely complex multi-turn reasoning
conversations to a more capable (and more expensive) model, and
maintains a FALLBACK from its primary provider to a secondary provider
specifically for reliability during provider-side outages — during an
actual outage of the primary provider, the fallback chain kept the
support platform functioning with a brief latency/quality blip rather
than a complete outage of the AI-assisted support feature.

COMMON MISTAKES:
- Hard-coding a specific provider's SDK calls directly into application
  business logic instead of behind a provider abstraction layer — this
  makes BOTH cost-based routing and reliability fallback significantly
  more expensive to add later, since every call site needs modification
  rather than one central routing layer.
- Implementing a fallback chain without accounting for CAPABILITY
  DIFFERENCES between providers (e.g. a specific structured-output
  format, or a longer context window the primary supported) — a naive
  fallback assuming perfect interchangeability can produce a
  functionally broken (not just different-quality) response when the
  fallback path activates for a request that genuinely depended on the
  primary's specific capability.
- Routing purely on COST without accounting for LATENCY differences
  between providers/models — the cheapest model for a given task isn't
  automatically the best choice if it's also meaningfully slower, and a
  latency-sensitive use case should weigh both dimensions, not cost alone.
"""

import textwrap
from dataclasses import dataclass
from enum import Enum


# ------------------------------------------------------------------
# 1. Provider abstraction layer — one internal interface, many backends
# ------------------------------------------------------------------
class Provider(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"


@dataclass
class GenerationRequest:
    prompt: str
    complexity: str   # "simple" | "complex" — used for routing decisions
    max_latency_ms: int | None = None


@dataclass
class GenerationResult:
    text: str
    provider_used: Provider
    cost_usd: float


class ProviderAdapter:
    """The interface every provider-specific adapter implements — routing
    logic (below) calls THIS uniform interface, never a provider SDK directly."""

    def generate(self, request: GenerationRequest) -> GenerationResult:
        raise NotImplementedError

    def is_available(self) -> bool:
        raise NotImplementedError


class OpenAIAdapter(ProviderAdapter):
    def generate(self, request: GenerationRequest) -> GenerationResult:
        # Translates the uniform request into OpenAI's specific API shape.
        print(f"  [OpenAI] generating for: '{request.prompt[:40]}...'")
        return GenerationResult(f"<OpenAI response>", Provider.OPENAI, cost_usd=0.002)

    def is_available(self) -> bool:
        return True   # a real implementation checks recent error rate/circuit breaker state


class AnthropicAdapter(ProviderAdapter):
    def generate(self, request: GenerationRequest) -> GenerationResult:
        print(f"  [Anthropic] generating for: '{request.prompt[:40]}...'")
        return GenerationResult(f"<Anthropic response>", Provider.ANTHROPIC, cost_usd=0.003)

    def is_available(self) -> bool:
        return True


class GoogleAdapter(ProviderAdapter):
    def generate(self, request: GenerationRequest) -> GenerationResult:
        print(f"  [Google] generating for: '{request.prompt[:40]}...'")
        return GenerationResult(f"<Gemini response>", Provider.GOOGLE, cost_usd=0.0015)

    def is_available(self) -> bool:
        return True


# ------------------------------------------------------------------
# 2. Cost-based routing
# ------------------------------------------------------------------
class CostBasedRouter:
    def __init__(self):
        self.cheap_provider = GoogleAdapter()      # cheapest, for simple tasks
        self.capable_provider = AnthropicAdapter()  # higher capability, for complex tasks

    def route(self, request: GenerationRequest) -> GenerationResult:
        if request.complexity == "simple":
            return self.cheap_provider.generate(request)
        return self.capable_provider.generate(request)


# ------------------------------------------------------------------
# 3. Fallback chains for reliability
# ------------------------------------------------------------------
class FallbackRouter:
    def __init__(self, providers_in_priority_order: list[ProviderAdapter]):
        self.providers = providers_in_priority_order

    def generate_with_fallback(self, request: GenerationRequest) -> GenerationResult:
        last_error = None
        for provider in self.providers:
            if not provider.is_available():
                continue
            try:
                return provider.generate(request)
            except Exception as e:   # a real implementation catches specific,
                last_error = e        # known-transient exception types
                print(f"  provider failed, falling back: {e}")
                continue
        raise RuntimeError(f"All providers failed. Last error: {last_error}")


class FlakyOpenAIAdapter(OpenAIAdapter):
    """Simulates a primary provider outage for the fallback demo."""
    def generate(self, request: GenerationRequest) -> GenerationResult:
        raise ConnectionError("simulated provider outage")


# ------------------------------------------------------------------
# 4. Real provider-abstraction library pattern (LiteLLM-style)
# ------------------------------------------------------------------
LITELLM_STYLE_EXAMPLE = textwrap.dedent("""\
    # In production, a library like LiteLLM implements this exact
    # abstraction pattern generically, rather than hand-rolled adapters:
    import litellm

    def generate(prompt: str, complexity: str) -> str:
        model = "gemini/gemini-1.5-flash" if complexity == "simple" else "claude-opus-4-5"
        try:
            response = litellm.completion(model=model, messages=[{"role": "user", "content": prompt}])
        except Exception:
            # LiteLLM's router supports declarative fallback lists too —
            # config-driven rather than hand-coded try/except chains.
            response = litellm.completion(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        return response.choices[0].message.content
""")


if __name__ == "__main__":
    router = CostBasedRouter()
    print("Cost-based routing:")
    router.route(GenerationRequest("Classify this ticket as urgent or not", "simple"))
    router.route(GenerationRequest("Analyze this multi-turn negotiation and propose a strategy", "complex"))

    print("\nFallback routing (simulated primary outage):")
    fallback_router = FallbackRouter([FlakyOpenAIAdapter(), AnthropicAdapter()])
    result = fallback_router.generate_with_fallback(GenerationRequest("Summarize this document", "complex"))
    print(f"  final result served by: {result.provider_used}")

    print()
    print(LITELLM_STYLE_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A Gen-AI platform team's multi-model routing sends lightweight
classification/extraction tasks to a cheaper, faster model while routing
complex multi-turn reasoning to a more capable model, with an automatic
fallback chain across providers — during an actual multi-hour outage of
their primary provider, the fallback chain kept the platform's AI
features functioning (with a measured, acceptable latency/cost increase)
rather than a full outage, and the cost-based routing separately reduced
average per-request LLM spend by routing the majority of simple requests
away from the most expensive model.
"""
