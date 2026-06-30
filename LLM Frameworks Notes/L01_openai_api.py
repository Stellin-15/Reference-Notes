# ============================================================
# L01: OpenAI API Fundamentals
# ============================================================
# WHAT: Complete reference for the OpenAI Python client library —
#       how to call models, count tokens, handle errors, use tools,
#       embed text, send images, and build production-safe wrappers.
# WHY:  OpenAI's API is the industry baseline. Every other LLM
#       ecosystem (Anthropic, Bedrock, LangChain) either mirrors or
#       reacts to OpenAI's design. Mastering it unlocks the mental
#       model for all others.
# LEVEL: Foundations
# ============================================================
"""
CONCEPT OVERVIEW:
    The OpenAI API is a stateless HTTP service. You send a list of
    messages (the conversation so far) and receive the model's next
    message. The "intelligence" lives entirely on OpenAI's servers;
    your job is to craft the right inputs and safely consume outputs.

    Key insight: every call is independent. The API has NO memory of
    previous calls. You must re-send the full conversation history
    on every request. This is expensive (tokens cost money) but simple.

PRODUCTION USE CASE:
    Customer support copilot: system prompt encodes your product rules,
    user turns contain the customer question, assistant turns contain
    previous responses. On each new message, re-send the last N turns
    to stay within the context window while preserving coherence.

COMMON MISTAKES:
    - Logging the full request/response including api_key in env vars
      (keys end up in log aggregators — rotate immediately if this happens)
    - Not handling RateLimitError with exponential backoff (causes cascading
      failures under load)
    - Setting temperature=1.0 for tasks that need determinism (classification,
      extraction, JSON output) — use temperature=0
    - Forgetting that max_tokens caps OUTPUT tokens, not total. Prompt +
      output must fit in context window.
    - Counting tokens incorrectly for cost estimation (always use tiktoken,
      never estimate by word count)
"""

import os
import base64
import time
import json
from typing import Iterator

# openai SDK: pip install openai
# tiktoken: pip install tiktoken
# tenacity: pip install tenacity
from openai import OpenAI, RateLimitError, APIConnectionError, AuthenticationError
import tiktoken
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


# ============================================================
# SECTION 1: CLIENT INITIALIZATION
# ============================================================

# NEVER hard-code API keys. Always read from environment.
# In production, use a secret manager (AWS Secrets Manager,
# HashiCorp Vault, GCP Secret Manager).
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),  # Required
    timeout=30.0,                               # Seconds before request times out
    max_retries=0,                              # We handle retries ourselves (see tenacity below)
)

# Organization ID: if your key belongs to multiple orgs, specify which.
# client = OpenAI(api_key=..., organization="org-xxx")

# Azure OpenAI: same SDK, different base URL + api version
# client = AzureOpenAI(
#     azure_endpoint="https://YOUR-RESOURCE.openai.azure.com/",
#     api_key=os.environ["AZURE_OPENAI_KEY"],
#     api_version="2024-02-01",
# )


# ============================================================
# SECTION 2: MODEL SELECTION GUIDE
# ============================================================

# GPT-4o:          Best quality, multimodal (text+image). Use for complex reasoning,
#                  nuanced writing, vision tasks. ~$5/1M input, $15/1M output tokens.
# GPT-4o-mini:     ~95% of GPT-4o quality at ~10x lower cost. Use for most tasks.
#                  $0.15/1M input, $0.60/1M output.
# o1:              "Reasoning" model — thinks step by step internally (hidden chain of
#                  thought). No system prompt (merged into user). Slower but much better
#                  at math, logic, code. ~$15/1M input, $60/1M output.
# o3-mini:         Faster, cheaper reasoning model. Best for coding and STEM.
# gpt-3.5-turbo:   Legacy. Superseded by gpt-4o-mini for cost and quality.

MODELS = {
    "best_quality":    "gpt-4o",
    "best_value":      "gpt-4o-mini",
    "best_reasoning":  "o1",
    "fast_reasoning":  "o3-mini",
}


# ============================================================
# SECTION 3: BASIC CHAT COMPLETION
# ============================================================

def basic_chat_example():
    """
    Minimal example: send system + user message, receive assistant reply.
    The 'messages' list IS the conversation. Order matters.
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",

        messages=[
            # SYSTEM role: sets the AI's persona, constraints, and instructions.
            # The LLM is trained to treat this as "high authority" instructions.
            # NOT visible to end users in your UI (but IS sent to OpenAI's API).
            {
                "role": "system",
                "content": (
                    "You are a financial analyst assistant. "
                    "Always cite the source of any statistic you mention. "
                    "If you don't know something, say 'I don't have reliable data on that.' "
                    "Return answers in plain text, not markdown."
                )
            },
            # USER role: the human's message.
            {
                "role": "user",
                "content": "What was Apple's revenue in Q3 2024?"
            },
        ],

        # TEMPERATURE: Controls randomness.
        # 0.0 = fully deterministic (same input → same output, mostly)
        # 0.7 = good balance for creative tasks
        # 1.0 = very creative/random, often incoherent for structured tasks
        # Rule: use 0 for extraction/classification/JSON, 0.3-0.7 for writing
        temperature=0.0,

        # MAX_TOKENS: Maximum number of tokens in the OUTPUT (not total).
        # If the model wants to say more but hits this limit, it truncates MID-SENTENCE.
        # Always set this to prevent runaway responses. For most chat: 512-2048.
        max_tokens=512,

        # TOP_P: Alternative to temperature. Nucleus sampling.
        # Only sample from the top P probability mass.
        # Convention: set temperature OR top_p, not both.
        top_p=1.0,

        # FREQUENCY_PENALTY: Penalizes tokens that have appeared frequently in output.
        # Range: -2.0 to 2.0. Positive = less repetition. Use 0.1-0.5 for long outputs.
        frequency_penalty=0.0,

        # PRESENCE_PENALTY: Penalizes tokens that have appeared at all (even once).
        # Encourages the model to cover new topics. Range: -2.0 to 2.0.
        presence_penalty=0.0,

        # STOP SEQUENCES: The model stops generating when it hits one of these strings.
        # Useful for structured outputs where you know where the content ends.
        # Example: stop=["###", "\n\n\n"]
        stop=None,
    )

    # Response object structure:
    # response.id                          — unique completion ID
    # response.model                       — actual model used
    # response.choices[0].message.content  — the text
    # response.choices[0].finish_reason    — "stop" (natural end), "length" (hit max_tokens),
    #                                        "tool_calls", "content_filter"
    # response.usage.prompt_tokens         — tokens in your input
    # response.usage.completion_tokens     — tokens in model output
    # response.usage.total_tokens          — sum

    text = response.choices[0].message.content
    finish_reason = response.choices[0].finish_reason

    if finish_reason == "length":
        # Output was truncated! Increase max_tokens or summarize the prompt.
        print("WARNING: Response was truncated. Increase max_tokens.")

    return text, response.usage


# ============================================================
# SECTION 4: FEW-SHOT PROMPTING
# ============================================================

def few_shot_sentiment_classifier(text: str) -> str:
    """
    Few-shot: provide examples of input→output in the messages list.
    The model learns the pattern from examples rather than explicit instructions.
    More reliable than just describing the task, especially for edge cases.
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "Classify the sentiment of the following text as POSITIVE, NEGATIVE, or NEUTRAL. Return only the label, nothing else."
            },
            # FEW-SHOT EXAMPLES: alternating user/assistant turns
            {"role": "user",      "content": "I love this product! Works perfectly."},
            {"role": "assistant", "content": "POSITIVE"},
            {"role": "user",      "content": "Terrible experience. Would not recommend."},
            {"role": "assistant", "content": "NEGATIVE"},
            {"role": "user",      "content": "The package arrived on Tuesday."},
            {"role": "assistant", "content": "NEUTRAL"},
            # ACTUAL QUERY: the real input comes last
            {"role": "user", "content": text},
        ],
    )
    return response.choices[0].message.content.strip()


# ============================================================
# SECTION 5: STREAMING RESPONSES
# ============================================================

def stream_response(prompt: str) -> Iterator[str]:
    """
    Streaming: receive tokens as they are generated instead of waiting
    for the full response. Critical for good UX in chat applications —
    users see text appearing immediately rather than waiting 5-10 seconds.

    Internally, OpenAI sends Server-Sent Events (SSE). The SDK
    wraps this into a Python iterator of chunk objects.
    """
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        stream=True,   # <-- Enable streaming
        max_tokens=1024,
    )

    # Each chunk contains a delta (the new tokens since last chunk)
    for chunk in stream:
        delta = chunk.choices[0].delta

        # delta.content is None for the first chunk (role announcement)
        # and the last chunk (finish signal)
        if delta.content is not None:
            yield delta.content  # Yield each token fragment

    # Usage stats are NOT available in streaming mode by default.
    # Pass stream_options={"include_usage": True} to get them in the final chunk.


def print_streaming():
    """Print a streamed response to terminal in real time."""
    print("Assistant: ", end="", flush=True)
    for token in stream_response("Explain quantum entanglement in 3 sentences."):
        print(token, end="", flush=True)
    print()  # newline after completion


# ============================================================
# SECTION 6: TOKEN COUNTING WITH TIKTOKEN
# ============================================================
# WHAT: Count tokens BEFORE making an API call.
# WHY:  - Avoid hitting context window limits (causes APIError)
#       - Estimate cost before spending money
#       - Decide whether to summarize/truncate the prompt

def count_tokens(messages: list[dict], model: str = "gpt-4o-mini") -> int:
    """
    Count the number of tokens that would be consumed by a messages list.
    Uses tiktoken, OpenAI's official tokenizer.

    Token boundaries differ from words: "don't" = 2 tokens, "ChatGPT" = 3.
    Always count with tiktoken, never estimate.
    """
    # cl100k_base: encoding used by gpt-4, gpt-4o, gpt-3.5-turbo, text-embedding-*
    # o200k_base:  encoding used by gpt-4o (newer versions) and o1/o3
    encoding = tiktoken.encoding_for_model(model)

    tokens_per_message = 3  # Every message has overhead: <|im_start|>role\ncontent<|im_end|>
    tokens_per_name = 1     # If a name field is present

    total_tokens = 0
    for message in messages:
        total_tokens += tokens_per_message
        for key, value in message.items():
            if isinstance(value, str):
                total_tokens += len(encoding.encode(value))
            if key == "name":
                total_tokens += tokens_per_name

    total_tokens += 3  # Every reply is primed with <|im_start|>assistant
    return total_tokens


def estimate_cost(prompt_tokens: int, completion_tokens: int, model: str = "gpt-4o-mini") -> float:
    """
    Estimate cost in USD for a single API call.
    Prices as of mid-2025 — always verify at platform.openai.com/pricing.
    """
    # Prices per 1 MILLION tokens (USD)
    pricing = {
        "gpt-4o":          {"input": 5.00,  "output": 15.00},
        "gpt-4o-mini":     {"input": 0.15,  "output": 0.60},
        "o1":              {"input": 15.00, "output": 60.00},
        "o3-mini":         {"input": 1.10,  "output": 4.40},
    }

    if model not in pricing:
        raise ValueError(f"Unknown model for pricing: {model}")

    rates = pricing[model]
    cost = (prompt_tokens / 1_000_000) * rates["input"] + \
           (completion_tokens / 1_000_000) * rates["output"]
    return cost


# ============================================================
# SECTION 7: ERROR HANDLING AND RETRY LOGIC
# ============================================================

# tenacity: declarative retry decorator
# wait_exponential: 1s, 2s, 4s, 8s... up to max_wait
# stop_after_attempt: give up after N total tries
@retry(
    retry=retry_if_exception_type(RateLimitError),
    wait=wait_exponential(multiplier=1, min=1, max=60),
    stop=stop_after_attempt(5),
    reraise=True,   # Re-raise after all attempts exhausted
)
def call_with_retry(messages: list[dict], model: str = "gpt-4o-mini") -> str:
    """
    Production-safe API call with automatic retry on rate limits.

    Error types and when they occur:
    - RateLimitError (429):   Too many requests or tokens per minute. Retry with backoff.
    - APIConnectionError:     Network issue. Retry immediately (usually transient).
    - AuthenticationError:    Bad API key. DO NOT retry — fix the key.
    - BadRequestError (400):  Invalid request (too many tokens, bad params). Fix the request.
    - InternalServerError:    OpenAI-side issue. Retry with backoff.
    - APITimeoutError:        Request took too long. Retry or increase timeout.
    """
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,
            max_tokens=512,
        )
        return response.choices[0].message.content

    except AuthenticationError as e:
        # CRITICAL: bad API key. Alert immediately, do NOT retry.
        # In production: page on-call, block further API calls to avoid lockout.
        raise RuntimeError(f"API key invalid or revoked: {e}") from e

    except APIConnectionError:
        # Network error — safe to retry
        time.sleep(1)
        raise  # Re-raise so tenacity can retry

    # RateLimitError is handled by @retry decorator automatically


# ============================================================
# SECTION 8: FUNCTION CALLING / TOOL USE
# ============================================================
# WHAT: Define "tools" (functions) that the LLM can decide to call.
#       The API returns a structured tool_call instead of plain text.
#       YOU execute the function, then send the result back.
# WHY:  Lets LLMs interact with the real world (search, databases, APIs)
#       in a structured, parseable way — not by generating Python code
#       or hallucinating results.

def function_calling_example():
    """
    Two-step flow:
    1. Send messages + tool definitions → model returns tool_call with arguments
    2. Execute the function → send result back → model uses it to answer
    """

    # TOOL DEFINITION: JSON Schema format
    # The description is CRITICAL — the model reads it to decide when to use the tool.
    # Be specific, include edge cases and what NOT to call it for.
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_stock_price",
                "description": (
                    "Get the current stock price for a publicly traded company. "
                    "Use this when the user asks about a stock price, market cap, or ticker. "
                    "Do NOT use for cryptocurrencies."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "description": "Stock ticker symbol, e.g. 'AAPL', 'MSFT', 'NVDA'"
                        },
                        "currency": {
                            "type": "string",
                            "enum": ["USD", "EUR", "GBP"],
                            "description": "Currency for the price. Defaults to USD.",
                        }
                    },
                    "required": ["ticker"],  # 'currency' is optional
                }
            }
        }
    ]

    messages = [
        {"role": "user", "content": "What's the current price of Tesla stock?"}
    ]

    # STEP 1: Send to model with tools
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        tools=tools,
        # tool_choice options:
        # "auto"     — model decides whether to call a tool (default)
        # "none"     — never call tools (just generate text)
        # "required" — MUST call a tool
        # {"type": "function", "function": {"name": "get_stock_price"}} — force specific tool
        tool_choice="auto",
    )

    assistant_message = response.choices[0].message
    finish_reason = response.choices[0].finish_reason

    if finish_reason == "tool_calls":
        # Model decided to call a tool
        tool_call = assistant_message.tool_calls[0]  # Could be multiple
        function_name = tool_call.function.name       # "get_stock_price"
        arguments = json.loads(tool_call.function.arguments)  # {"ticker": "TSLA"}

        print(f"Model wants to call: {function_name}({arguments})")

        # STEP 2: Execute the function (your code, your database, your API)
        # In production: look up function_name in a registry, validate arguments,
        # execute with timeout, handle exceptions
        result = _execute_tool(function_name, arguments)

        # STEP 3: Send tool result back to model
        messages.append(assistant_message)  # Add the tool_call message
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,   # Must match the call that triggered it
            "content": json.dumps(result),   # Always JSON string
        })

        # STEP 4: Get the final natural language answer
        final_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
        )
        return final_response.choices[0].message.content

    else:
        # Model answered directly without calling a tool
        return assistant_message.content


def _execute_tool(name: str, args: dict) -> dict:
    """Stub: replace with actual function dispatch in production."""
    if name == "get_stock_price":
        # In reality: call a financial data API
        return {"ticker": args["ticker"], "price": 248.50, "currency": "USD"}
    raise ValueError(f"Unknown tool: {name}")


# ============================================================
# SECTION 9: STRUCTURED OUTPUT
# ============================================================

def get_structured_output_json_mode() -> dict:
    """
    JSON Mode: guarantees the model returns valid JSON.
    Does NOT guarantee the JSON has the fields you want.
    Always specify the schema in the prompt.
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        response_format={"type": "json_object"},  # Enable JSON mode
        messages=[
            {
                "role": "system",
                # MUST describe the JSON structure in the prompt when using json_object
                "content": (
                    "Extract the key information from the user's text. "
                    "Return JSON with exactly these fields: "
                    '{"name": string, "age": integer | null, "location": string | null}'
                )
            },
            {
                "role": "user",
                "content": "Hi, I'm Sarah, 32, from Austin Texas."
            }
        ],
    )
    return json.loads(response.choices[0].message.content)


def get_structured_output_schema(text: str) -> dict:
    """
    Structured Output with JSON Schema (GPT-4o and later).
    Guarantees the response matches your exact schema — field names, types, everything.
    More reliable than json_object mode.
    """
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "person_extraction",
            "strict": True,  # Strict mode: must match schema exactly
            "schema": {
                "type": "object",
                "properties": {
                    "name":     {"type": "string"},
                    "age":      {"type": ["integer", "null"]},
                    "location": {"type": ["string", "null"]},
                    "email":    {"type": ["string", "null"]},
                },
                "required": ["name", "age", "location", "email"],
                "additionalProperties": False,  # Required for strict=True
            }
        }
    }

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        response_format=schema,
        messages=[
            {"role": "system", "content": "Extract person information from the text."},
            {"role": "user",   "content": text},
        ],
    )
    return json.loads(response.choices[0].message.content)


# ============================================================
# SECTION 10: EMBEDDINGS
# ============================================================
# WHAT: Convert text into a dense numerical vector (list of floats).
#       Similar texts have similar vectors (high cosine similarity).
# WHY:  Power semantic search, RAG retrieval, clustering, anomaly detection.
# MODELS:
#   text-embedding-3-small: 1536 dims, $0.02/1M tokens. Best value for most use cases.
#   text-embedding-3-large: 3072 dims, $0.13/1M tokens. Higher accuracy, more expensive.
#   text-embedding-ada-002:  legacy, 1536 dims. Superseded by v3.

def embed_text(text: str) -> list[float]:
    """Convert a single string to an embedding vector."""
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
        # encoding_format: "float" (default) or "base64" (smaller JSON, decode client-side)
        encoding_format="float",
        # dimensions: optionally reduce dims (e.g., 512) — lower cost storage,
        # slightly lower accuracy. Only supported by v3 models.
        # dimensions=512,
    )
    return response.data[0].embedding  # List of 1536 floats


def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Batch embed multiple texts in a single API call.
    Much more efficient than calling embed_text() in a loop.
    Max batch size: 2048 strings. Max input tokens per call: ~8192 total.
    """
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    # Response.data is ordered the same as input
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """
    Compute cosine similarity between two embedding vectors.
    Range: -1 (opposite) to 1 (identical). > 0.85 is usually "similar".
    In production: use numpy for speed, or let the vector DB handle this.
    """
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = sum(a * a for a in vec1) ** 0.5
    norm2 = sum(b * b for b in vec2) ** 0.5
    return dot / (norm1 * norm2)


# ============================================================
# SECTION 11: VISION / IMAGE INPUT
# ============================================================
# WHAT: Send images alongside text. Model can describe, analyze, extract text.
# WHY:  Invoice processing, screenshot analysis, document parsing,
#       medical image Q&A, e-commerce product analysis.
# SUPPORTED MODELS: gpt-4o, gpt-4o-mini (NOT o1/o3)

def analyze_image_from_file(image_path: str, question: str) -> str:
    """
    Send a local image to GPT-4o for analysis.
    Image is base64-encoded and embedded directly in the request.
    Max image size: 20MB. Supported formats: PNG, JPEG, WEBP, GIF.
    """
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    # Detect media type from extension (production: use python-magic for robustness)
    ext = image_path.rsplit(".", 1)[-1].lower()
    media_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                  "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": [
                    # Text part of the message
                    {"type": "text", "text": question},
                    # Image part — base64 encoded
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_data}",
                            # detail: "low" (85 tokens, 512x512 thumbnail),
                            #         "high" (expensive, full resolution tiles),
                            #         "auto" (default, model decides)
                            "detail": "auto",
                        }
                    }
                ]
            }
        ],
    )
    return response.choices[0].message.content


def analyze_image_from_url(image_url: str, question: str) -> str:
    """
    Alternatively, pass a publicly accessible URL.
    OpenAI fetches the image server-side. Faster for large images.
    URL must be publicly accessible (no auth required).
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ]
            }
        ],
    )
    return response.choices[0].message.content


# ============================================================
# SECTION 12: PRODUCTION BEST PRACTICES
# ============================================================

class ProductionLLMClient:
    """
    A production-hardened wrapper around the OpenAI client.
    Adds: logging, cost tracking, input validation, output validation.
    """

    def __init__(self, model: str = "gpt-4o-mini", max_budget_usd: float = 10.0):
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=30.0)
        self.model = model
        self.max_budget_usd = max_budget_usd
        self.total_cost_usd = 0.0
        self.total_calls = 0

    @retry(
        retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        stop=stop_after_attempt(5),
    )
    def complete(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> str:
        """
        Safe completion with budget guard, logging, and output validation.
        """

        # 1. BUDGET GUARD: Stop before exceeding budget
        if self.total_cost_usd >= self.max_budget_usd:
            raise RuntimeError(
                f"Budget exceeded: spent ${self.total_cost_usd:.4f} of ${self.max_budget_usd}"
            )

        # 2. INPUT VALIDATION: Never trust external content in system prompt position
        #    Prompt injection: attacker puts "Ignore previous instructions" in user content.
        #    Defense: keep system prompt and user content strictly separated.
        #    Never f-string user content into the system prompt string.
        if len(user_message) > 50_000:
            raise ValueError("User message exceeds safe length limit")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ]

        # 3. TOKEN BUDGET CHECK: Fail fast before API call
        prompt_tokens = count_tokens(messages, self.model)
        context_limits = {"gpt-4o": 128_000, "gpt-4o-mini": 128_000, "o1": 128_000}
        limit = context_limits.get(self.model, 128_000)
        if prompt_tokens + max_tokens > limit:
            raise ValueError(
                f"Prompt ({prompt_tokens} tokens) + max_tokens ({max_tokens}) "
                f"exceeds context window ({limit})"
            )

        # 4. API CALL
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # 5. LOG USAGE (in production: send to your observability platform)
        usage = response.usage
        call_cost = estimate_cost(usage.prompt_tokens, usage.completion_tokens, self.model)
        self.total_cost_usd += call_cost
        self.total_calls += 1

        # In production: log to LangSmith / Helicone / your own DB
        log_entry = {
            "call_id": response.id,
            "model": self.model,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "cost_usd": call_cost,
            "finish_reason": response.choices[0].finish_reason,
            # NEVER log the actual prompt/response content if it contains PII
        }
        print(f"[LLM] {log_entry}")  # Replace with proper logger

        # 6. OUTPUT VALIDATION
        content = response.choices[0].message.content
        if response.choices[0].finish_reason == "content_filter":
            raise ValueError("Response blocked by content filter")
        if not content or len(content.strip()) == 0:
            raise ValueError("Empty response from model")

        return content

    def get_usage_summary(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "avg_cost_per_call": round(self.total_cost_usd / max(self.total_calls, 1), 6),
        }


# ============================================================
# SECTION 13: CONVERSATION MANAGEMENT (MULTI-TURN)
# ============================================================

class ConversationManager:
    """
    Manages a multi-turn conversation with automatic context window management.
    Key insight: as conversation grows, older messages must be dropped or summarized
    to stay within token limits.
    """

    def __init__(self, system_prompt: str, model: str = "gpt-4o-mini", max_tokens: int = 100_000):
        self.system_prompt = system_prompt
        self.model = model
        self.max_context_tokens = max_tokens
        self.history: list[dict] = []

    def chat(self, user_message: str) -> str:
        """Send a message and receive a reply, maintaining history."""
        self.history.append({"role": "user", "content": user_message})

        # Trim history if we're approaching context limit
        self._trim_history()

        messages = [{"role": "system", "content": self.system_prompt}] + self.history

        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
            max_tokens=512,
        )

        assistant_reply = response.choices[0].message.content
        self.history.append({"role": "assistant", "content": assistant_reply})
        return assistant_reply

    def _trim_history(self):
        """
        Drop oldest messages when approaching context limit.
        Strategy: always keep the most recent N turns.
        Alternative: summarize old turns (see L04 memory strategies).
        """
        while True:
            messages = [{"role": "system", "content": self.system_prompt}] + self.history
            if count_tokens(messages, self.model) < self.max_context_tokens - 1024:
                break
            # Remove the oldest user+assistant pair (keep conversation coherent)
            if len(self.history) >= 2:
                self.history.pop(0)  # Remove oldest user message
                self.history.pop(0)  # Remove oldest assistant message
            else:
                break  # Can't trim further


# ============================================================
# QUICK REFERENCE
# ============================================================
"""
CHEAT SHEET:

  Basic call:
    response = client.chat.completions.create(model=..., messages=[...])
    text = response.choices[0].message.content

  Streaming:
    for chunk in client.chat.completions.create(..., stream=True):
        print(chunk.choices[0].delta.content or "", end="")

  Token count:
    enc = tiktoken.encoding_for_model("gpt-4o-mini")
    n = len(enc.encode(text))

  Embed text:
    vec = client.embeddings.create(model="text-embedding-3-small", input=text).data[0].embedding

  Tool call flow:
    1. Pass tools=[ {...schema...} ] to create()
    2. If finish_reason=="tool_calls": parse tool_call.function.arguments
    3. Execute function, append {role:"tool", tool_call_id:..., content:result}
    4. Call create() again to get final answer

  Structured output:
    response_format={"type": "json_object"}  # valid JSON, no schema enforcement
    response_format={"type": "json_schema", "json_schema": {...}}  # strict schema

  Key env vars:
    OPENAI_API_KEY       — required
    OPENAI_ORG_ID        — optional, for multi-org accounts
    OPENAI_BASE_URL      — optional, for proxies/Azure

  Never:
    - Log api_key
    - Put user content in system prompt string (injection risk)
    - Ignore finish_reason == "length" (truncated output)
    - Use max_retries>0 on the client AND tenacity (double retry)
"""
