# LLM Frameworks — Principal Engineer Deep Dive

Companion to the existing lessons. Distinct from LLM Core Theory Notes
(mechanism) and Agentic AI & RAG Notes (orchestration) — this is the
API/framework USAGE layer. Narrative depth, then a comprehensive
common-to-uncommon reference.


## Prompt Engineering as a Real Engineering Discipline

**Beyond the lesson**: Effective prompting isn't folklore — specific
techniques have measurable, reproducible effects and real failure modes:
**Chain-of-Thought (CoT) prompting** (asking a model to "think step by
step") measurably improves performance on multi-step reasoning tasks
because it lets the model allocate more effective COMPUTATION to the
problem (each generated reasoning token is additional forward-pass
compute the model gets to use before committing to a final answer) —
this is a genuinely mechanistic explanation, not just "it thinks more
carefully" hand-waving. **Few-shot prompting** works by giving the model
IN-CONTEXT examples of the exact input-output pattern desired, which is
functionally a form of on-the-fly task specification without any weight updates at all.

**Worked example**: Structured output enforcement (JSON mode, function
calling schemas) works via CONSTRAINED DECODING at the API/serving
layer — the model's next-token sampling is restricted at each step to
only tokens that keep the output valid against a grammar/schema (a
JSON-schema-aware token mask), not merely "the model was asked nicely to
output JSON and usually complies" — this distinction matters because
constrained decoding GUARANTEES schema validity structurally, while a
prompt-only approach can still occasionally produce malformed output.

**Interview Q&A**:
- *Q: Why does adding "Let's think step by step" sometimes HURT performance on simple factual questions?* A: For questions the model already "knows" directly, forcing an intermediate reasoning chain adds unnecessary generation steps where the model can introduce an incorrect assumption or hallucinated intermediate fact that then propagates into a wrong final answer — CoT specifically helps when the task genuinely benefits from decomposition, not universally.


## Fine-Tuning vs RAG vs Prompt Engineering — The Real Decision Framework

**Beyond the lesson**: This is one of the most commonly mis-answered
LLM-systems interview questions, and the actual decision criterion is
about WHERE the needed information/behavior lives: prompt engineering
(including few-shot examples) is right when the model already has the
underlying knowledge/capability and just needs better ELICITATION;
RAG (see Agentic AI & RAG Notes) is right when the model needs access to
information that's EXTERNAL, frequently CHANGING, or too large to fit in
a prompt — fine-tuning is right specifically when you need to change the
model's BEHAVIOR/STYLE/FORMAT consistently (not facts — fine-tuning is a
notoriously unreliable way to teach a model new facts, since it can't
reliably "add" specific facts without risking catastrophic forgetting of
other knowledge) — most production systems that need "custom knowledge"
actually need RAG, not fine-tuning, a genuinely common real-world
architectural mistake worth being able to explain precisely.

**Interview Q&A**:
- *Q: A company wants their support chatbot to always respond in their specific brand voice AND know their current product catalog. What combination of techniques applies?* A: Fine-tuning (or a well-crafted system prompt) for the consistent BRAND VOICE/STYLE, and RAG for the CURRENT product catalog (which changes frequently and is too large/dynamic to bake into weights or a static prompt) — a real, common production pattern combining both for the reasons each technique specifically fits.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Fine-tuning techniques, precisely differentiated
- **Full fine-tuning** — updates ALL model weights, most expressive but
  requires the most compute/memory and risks catastrophic forgetting most severely.
- **LoRA (Low-Rank Adaptation)** — freezes the original weights and
  trains small, LOW-RANK adapter matrices injected into specific layers —
  dramatically fewer trainable parameters, and multiple LoRA adapters can
  be swapped/combined at inference time for different tasks without
  needing separate full model copies.
- **QLoRA** — combines LoRA with quantizing the base model to 4-bit
  precision during fine-tuning (see LLM Quantization & Inference Notes)
  — lets you fine-tune genuinely large models on a single consumer/
  prosumer GPU, a real, significant democratization of fine-tuning access.
- **Instruction tuning / SFT (Supervised Fine-Tuning)** — training on
  (instruction, response) pairs specifically to make a base (raw
  next-token-prediction) model follow instructions conversationally —
  the step between a raw pretrained model and a usable "chat" model,
  before any RLHF/DPO preference tuning is even applied.

### Provider APIs & platform-specific tooling
- **OpenAI API / Anthropic API** — the dominant first-party LLM APIs;
  function/tool calling, structured outputs (JSON mode), and vision
  input are now table-stakes features across both.
- **Hugging Face `transformers` / `datasets` / `accelerate`** — the
  dominant open-source library ecosystem for loading, fine-tuning, and
  running open-weight models — genuinely the de facto standard interface
  even when the underlying model comes from many different research groups/companies.
- **Ollama / LM Studio** — the dominant tools for running open-weight
  LLMs LOCALLY (on a laptop/workstation) with minimal setup — genuinely
  popular for local development/privacy-sensitive use cases without
  needing cloud API calls at all.

### Evaluation frameworks for LLM applications
- See AI Agent & Automation Tooling Notes section 5 for the full
  RAGAS/promptfoo/DeepEval treatment — worth cross-referencing here
  since evaluating a raw LLM API integration and evaluating a full agent
  pipeline share much of the same tooling.
- **LLM-as-judge** — using a strong model to EVALUATE another model's
  outputs against a rubric — a genuinely common, pragmatic evaluation
  technique, with well-documented biases worth knowing (position bias —
  favoring whichever answer appears first; verbosity bias — favoring
  longer answers regardless of actual quality) that a rigorous eval setup must account for.


## NICHE BUT REAL

- **Prompt injection as a structural vulnerability** — see LLM Core
  Theory Notes L07; worth reiterating here at the framework-usage level:
  ANY framework that concatenates untrusted external content (retrieved
  documents, tool outputs, user-uploaded files) into the same context
  window as system instructions is exposed to this, regardless of which
  specific API/framework is used — it's a property of the underlying
  attention mechanism treating all context as equally "instructable," not a framework-specific bug to patch.
- **Context window economics** — providers price and rate-limit
  differently by context length; a naive RAG implementation that stuffs
  maximum-context-window's-worth of retrieved documents into every call
  can be dramatically more expensive AND slower than a well-tuned
  retrieval step that returns fewer, more relevant chunks — a real,
  common cost-optimization lever many teams miss initially.
- **Model routing/cascading in production** — calling a cheap, fast model
  first, and only escalating to an expensive, capable model when the
  cheap model's confidence is low or the task is flagged as complex — a
  real, increasingly common production cost-optimization pattern (see
  Event-Driven & Real-Time AI Systems deep dive's cost-based routing coverage).
- **Prompt caching** (a first-party feature in several major provider
  APIs) — caching the KV-state of a REPEATED prompt prefix (a long system
  prompt, a large retrieved-document context) across multiple calls,
  dramatically reducing both cost and latency for the cached portion —
  genuinely significant for production systems with a large, mostly-
  static prompt prefix and only a small varying user-query suffix per call.
