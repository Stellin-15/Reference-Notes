# ============================================================
# L01: The LLM Provider Landscape — Hosted APIs, Open Weights, Local Serving
# ============================================================
# WHAT: A practical map of where the actual "brain" behind any RAG/agent
#       system comes from — hosted API providers (OpenAI, Anthropic,
#       Google, Cohere), open-weight model families (Meta Llama, Mistral),
#       the distribution hub for open models (Hugging Face), and local/
#       self-hosted serving options (Ollama, vLLM).
# WHY: Every framework in this domain (LangChain, LlamaIndex, CrewAI,
#      AutoGen, etc.) is a LAYER ON TOP of one of these — before learning
#      any framework, you need to know what you're actually choosing
#      between when a framework asks "which model/provider do you want
#      to use," and why that choice has real cost/latency/privacy
#      tradeoffs.
# LEVEL: Foundation (Phase 1 of 7 — Foundations)
# ============================================================

"""
CONCEPT OVERVIEW:
HOSTED API PROVIDERS run the model for you — you send a request over
HTTPS, they run inference on their own infrastructure, and you pay per
token. OpenAI (GPT-4/GPT-4o family), Anthropic (Claude family), Google
(Gemini family), and Cohere (Command family) are the major players. You
never see or control the model weights; you get an API surface (usually
similar across providers: a messages array in, a completion out) and a
managed, scaled, updated model. Tradeoff: zero infrastructure to run
yourself, but ongoing per-token cost, data leaves your infrastructure
(a real consideration for regulated/sensitive data), and you're
dependent on the provider's uptime/pricing/deprecation schedule.

OPEN-WEIGHT MODELS (Meta's Llama family, Mistral AI's models) publish
their actual trained weights — you can download and run them yourself.
This doesn't mean "free to run" (you still need real GPU compute), but
it means you control WHERE inference happens (your own infrastructure,
on-prem, air-gapped if needed), can fine-tune the weights yourself
(directly connecting to this repo's `LLM Quantization & Inference Notes`
domain, which covers building/fine-tuning/quantizing exactly these kinds
of models from scratch), and are not dependent on any single company's
API staying available or unchanged.

HUGGING FACE is the dominant DISTRIBUTION HUB for open-weight models
(and datasets, and a `transformers` Python library for running them) —
not itself a model, but the place most open-weight models (Llama,
Mistral, and thousands of fine-tuned variants) are actually hosted and
downloaded from, plus a hosted Inference API/Inference Endpoints service
if you want hosted-API convenience for an open-weight model without
self-hosting.

LOCAL/SELF-HOSTED SERVING is HOW you actually run an open-weight model
once downloaded. OLLAMA wraps model serving in a simple, single-binary,
developer-friendly CLI/API — the easiest on-ramp for running a model
locally on a laptop or a single machine, deliberately optimized for ease
of use over maximum throughput. VLLM is a production-grade, high-
throughput inference SERVER built for serving many concurrent requests
efficiently at scale (continuous batching, PagedAttention — covered in
full technical depth in `LLM Quantization & Inference Notes` L20-L22) —
the choice for a real production deployment serving many users, not a
single-developer local setup.

PRODUCTION USE CASE:
A startup prototypes a RAG chatbot using OpenAI's API (fastest to get
working, no infrastructure to manage) while proving out the product.
Once the product has real usage and cost/latency/data-residency concerns
matter, they migrate the same application (with minimal code change,
since most frameworks abstract the provider behind a common interface)
to a self-hosted Llama or Mistral model served via vLLM on their own
GPU infrastructure — trading a per-token API bill for fixed infrastructure
cost and full data control.

COMMON MISTAKES:
- Assuming "open-weight" means "free to run" — you still need real,
  often expensive GPU compute; the savings versus a hosted API only
  materialize at meaningful, sustained request volume, not for
  occasional/low-volume use.
- Choosing Ollama for a production, multi-user serving workload — it's
  built for developer convenience and local/single-user use, not the
  concurrent-request throughput vLLM is specifically engineered for.
- Hard-coding a specific provider's API shape directly into application
  logic instead of using a framework's provider-abstraction layer (see
  L05's LangChain coverage) — this makes later switching providers (for
  cost, capability, or compliance reasons) far more expensive than it
  needs to be.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Hosted API providers — calling each with roughly the same shape
# ------------------------------------------------------------------
HOSTED_PROVIDER_COMPARISON = {
    "OpenAI (GPT-4o, GPT-4, GPT-3.5)": "The most widely integrated API "
        "across frameworks; strong general-purpose and function-calling "
        "support; the de facto default most tutorials/frameworks target first.",
    "Anthropic (Claude family)": "Strong at long-context reasoning and "
        "following detailed instructions; a distinct API shape "
        "(messages + system parameter) that frameworks abstract over.",
    "Google (Gemini family)": "Deep integration with Google Cloud/Vertex "
        "AI; strong native multimodal (text+image+video) support.",
    "Cohere (Command family)": "Historically strong at retrieval/embedding "
        "use cases specifically (see L02) alongside general chat completion.",
}

OPENAI_STYLE_CALL = textwrap.dedent("""\
    from openai import OpenAI
    client = OpenAI(api_key="...")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Summarize this document."}],
    )
""")

ANTHROPIC_STYLE_CALL = textwrap.dedent("""\
    import anthropic
    client = anthropic.Anthropic(api_key="...")
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": "Summarize this document."}],
    )
    # Note the SHAPE DIFFERENCE from OpenAI's call (max_tokens is
    # required, no top-level "system" role inside messages — it's a
    # separate parameter) — exactly the kind of provider-specific
    # difference a framework's abstraction layer (L05) exists to hide.
""")

# ------------------------------------------------------------------
# 2. Open-weight models and Hugging Face
# ------------------------------------------------------------------
OPEN_WEIGHT_LANDSCAPE = {
    "Meta Llama family": "One of the most widely fine-tuned/adapted open "
        "base model families — extensive community tooling built around it.",
    "Mistral AI models": "Known for strong performance-per-parameter "
        "efficiency; also offers a hosted API (La Plateforme) alongside "
        "open-weight releases, straddling both categories.",
    "Hugging Face": "NOT a model — the dominant hub for downloading open "
        "model weights, datasets, and the `transformers` library for "
        "running them; also offers Inference Endpoints for hosted-API-"
        "style convenience on top of open models.",
}

HUGGINGFACE_DOWNLOAD_EXAMPLE = textwrap.dedent("""\
    from transformers import AutoModelForCausalLM, AutoTokenizer
    model = AutoModelForCausalLM.from_pretrained("mistralai/Mistral-7B-v0.1")
    tokenizer = AutoTokenizer.from_pretrained("mistralai/Mistral-7B-v0.1")
    # Weights are downloaded from Hugging Face's hub and run LOCALLY —
    # you now own the entire inference stack, for better (control,
    # privacy, no per-token cost past compute) and worse (you own
    # scaling/serving, covered next).
""")

# ------------------------------------------------------------------
# 3. Local/self-hosted serving: Ollama vs vLLM
# ------------------------------------------------------------------
OLLAMA_VS_VLLM = {
    "Ollama": "Single-binary, extremely low-friction local model serving "
        "— `ollama run llama3` and you have a local API in seconds. "
        "Optimized for developer convenience and single-user/local use, "
        "NOT for serving many concurrent production users efficiently.",
    "vLLM": "A production-grade inference server built around continuous "
        "batching and PagedAttention (memory-efficient KV cache "
        "management — see `LLM Quantization & Inference Notes` L20-L22 "
        "for the full technical mechanism) specifically to serve MANY "
        "concurrent requests with high throughput — the choice for real "
        "production deployment, not local development.",
}

OLLAMA_EXAMPLE = textwrap.dedent("""\
    # Terminal:
    ollama run llama3.1

    # Python, via Ollama's local API:
    import requests
    response = requests.post("http://localhost:11434/api/generate", json={
        "model": "llama3.1",
        "prompt": "Summarize this document.",
    })
""")

VLLM_EXAMPLE = textwrap.dedent("""\
    # Launch a production-grade OpenAI-COMPATIBLE server — note this
    # means existing OpenAI-client code (from OPENAI_STYLE_CALL above)
    # works against a self-hosted vLLM server with just a base_url change.
    # vllm serve mistralai/Mistral-7B-Instruct-v0.2

    from openai import OpenAI
    client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")
    response = client.chat.completions.create(
        model="mistralai/Mistral-7B-Instruct-v0.2",
        messages=[{"role": "user", "content": "Summarize this document."}],
    )
""")

# ------------------------------------------------------------------
# 4. Choosing between hosted, open-weight-local, and open-weight-vLLM
# ------------------------------------------------------------------
DECISION_FACTORS = [
    "Data sensitivity/compliance: must data ever leave your "
    "infrastructure? If not, hosted APIs are disqualified regardless of "
    "convenience — open-weight + self-hosted (Ollama for dev, vLLM for "
    "production) is the only option.",
    "Request volume and latency requirements: low/occasional volume "
    "favors hosted APIs (no infrastructure to maintain); high, sustained "
    "volume increasingly favors self-hosting on vLLM once the "
    "infrastructure cost is amortized against per-token API savings.",
    "Need for fine-tuning/customization: hosted providers offer LIMITED "
    "fine-tuning APIs for some models; full control over training data "
    "and technique requires open weights (see `LLM Quantization & "
    "Inference Notes` for the full fine-tuning/quantization pipeline).",
    "Team's infrastructure maturity: self-hosting via vLLM requires real "
    "GPU infrastructure and operational expertise; hosted APIs trade "
    "that operational burden for ongoing per-token cost.",
]


if __name__ == "__main__":
    print("=== Hosted API providers ===")
    for provider, note in HOSTED_PROVIDER_COMPARISON.items():
        print(f"{provider}: {note}\n")

    print(OPENAI_STYLE_CALL)
    print(ANTHROPIC_STYLE_CALL)

    print("=== Open-weight landscape ===")
    for name, note in OPEN_WEIGHT_LANDSCAPE.items():
        print(f"{name}: {note}\n")

    print(HUGGINGFACE_DOWNLOAD_EXAMPLE)

    print("=== Ollama vs vLLM ===")
    for tool, note in OLLAMA_VS_VLLM.items():
        print(f"{tool}: {note}\n")

    print(OLLAMA_EXAMPLE)
    print(VLLM_EXAMPLE)

    print("Decision factors:")
    for factor in DECISION_FACTORS:
        print(f"  - {factor}")

"""
PRODUCTION CONTEXT EXAMPLE:
A healthcare RAG application handling patient records cannot send data
to any third-party hosted API under its compliance requirements — it
runs an open-weight Llama model entirely on-prem, using Ollama during
development (fast iteration, single developer) and switching to vLLM for
the production deployment (serving dozens of concurrent clinician
queries with acceptable latency) — the SAME model weights, two different
serving layers matched to two different stages of the same project.
"""
