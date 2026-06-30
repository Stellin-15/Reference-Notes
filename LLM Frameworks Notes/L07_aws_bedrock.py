# ============================================================
# L07: AWS Bedrock — Production LLM on Managed Infrastructure
# ============================================================
# WHAT: AWS Bedrock is a fully managed API that gives access
#       to foundation models from Anthropic (Claude), Amazon
#       (Titan), Meta (Llama 3.x), Mistral, Cohere, and AI21
#       — all via a single AWS service endpoint. No GPUs to
#       manage, no model weights to download.
# WHY:  Enterprise LLM deployment requires compliance, IAM
#       auth, VPC isolation, and native AWS observability.
#       Bedrock provides all four out of the box. No data
#       leaves AWS — satisfies HIPAA, SOC2, and GDPR controls
#       that a direct API key to a third-party provider cannot.
# LEVEL: Advanced / Architect
# ============================================================
"""
CONCEPT OVERVIEW:
    AWS Bedrock exposes two core APIs:
      - invoke_model        : single request/response (legacy)
      - converse            : unified multi-model API (preferred)
      - converse_stream     : streaming version of converse
      - retrieve            : Knowledge Base RAG query
      - retrieve_and_generate: full managed RAG response

    Authentication is IAM, not API keys:
      - Dev : AWS SSO / named profile (~/.aws/credentials)
      - Prod: IAM role attached to the EC2/ECS/Lambda resource
              (instance profile — no credential files on disk)

    Key compliance posture:
      - Data stays in your AWS region / VPC
      - CloudTrail logs every model invocation automatically
      - Bedrock Guardrails: PII detection, content filters,
        topic blocking — applied before prompt reaches model

PRODUCTION USE CASE:
    Enterprise customer-service bot for an insurance company:
      - Claude 3.5 Sonnet via Bedrock (HIPAA eligible)
      - Knowledge Base backed by S3 (policy documents) +
        OpenSearch Serverless vector store
      - Guardrails: PII redaction, competitor blocking,
        violence/hate content filtering
      - CloudWatch metrics: latency P99, token throughput
      - VPC endpoint: traffic never touches public internet
      - Provisioned Throughput for peak hours (9am-5pm EST)

COMMON MISTAKES:
    1. Using invoke_model per model — switch to converse API,
       it works identically across ALL Bedrock models.
    2. Hardcoding AWS access keys in code. Use IAM roles.
       Rotate immediately if leaked; keys in git = breach.
    3. Not handling ThrottlingException. All on-demand models
       have per-minute token limits. Implement exponential
       backoff with jitter from the first day.
    4. Skipping Guardrails for user-facing apps. One PII leak
       or hate-speech response destroys enterprise trust.
    5. Forgetting to enable model access in Bedrock console
       before first call. Each model requires explicit opt-in
       per region in the Bedrock Model Access page.
"""

# ── Imports ──────────────────────────────────────────────────
# pip install boto3 botocore

import boto3
import botocore
import json
import time
import base64
import random
import logging
from typing import Generator, Optional
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 1. CLIENT SETUP
# ═══════════════════════════════════════════════════════════════

def get_bedrock_client(region: str = "us-east-1") -> boto3.client:
    """
    Create the bedrock-runtime client.
    In prod: IAM role attached to compute resource — no keys.
    In dev : AWS SSO profile (aws sso login --profile dev).
    """
    # boto3 automatically resolves credentials in this order:
    #   1. Env vars (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY) — avoid in prod
    #   2. ~/.aws/credentials named profile
    #   3. ECS/EC2 instance profile (IAM role) — preferred in prod
    client = boto3.client(
        "bedrock-runtime",
        region_name=region,
        # config: retry + timeout settings
        config=botocore.config.Config(
            connect_timeout=10,          # seconds to establish TCP connection
            read_timeout=60,             # seconds to wait for first byte of response
            retries={
                "max_attempts": 3,       # total attempts including first
                "mode": "adaptive",      # adaptive respects Retry-After headers
            },
        ),
    )
    logger.info(f"Bedrock client created for region: {region}")
    return client


# ═══════════════════════════════════════════════════════════════
# 2. INVOKE MODEL (legacy — model-specific payload format)
# ═══════════════════════════════════════════════════════════════

def invoke_model_claude(
    client: boto3.client,
    text: str,
    model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
) -> str:
    """
    invoke_model: lower-level API, payload format differs per model.
    Claude requires anthropic_version field.
    Prefer converse API (Section 3) for new code.
    """
    # Claude-specific payload structure (Anthropic Messages format)
    payload = {
        "anthropic_version": "bedrock-2023-05-31",  # required by Anthropic on Bedrock
        "max_tokens": 1024,
        "messages": [
            {"role": "user", "content": text},
        ],
    }

    try:
        response = client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(payload),
        )
    except client.exceptions.ValidationException as e:
        logger.error(f"Payload validation failed: {e}")
        raise

    # response['body'] is a StreamingBody — must .read() to get bytes
    body = json.loads(response["body"].read())

    # Claude returns content as list of blocks; text is in first block
    answer = body["content"][0]["text"]
    input_tokens = body["usage"]["input_tokens"]
    output_tokens = body["usage"]["output_tokens"]

    logger.info(f"Tokens — in: {input_tokens}, out: {output_tokens}")
    return answer


# ═══════════════════════════════════════════════════════════════
# 3. CONVERSE API (unified — use this for all new code)
# ═══════════════════════════════════════════════════════════════

def converse(
    client: boto3.client,
    text: str,
    system_prompt: str = "You are a helpful assistant.",
    model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
    max_tokens: int = 1024,
    temperature: float = 0.7,
) -> dict:
    """
    Converse API: unified interface for ANY Bedrock model.
    Same code works for Claude, Titan, Llama, Mistral, Cohere.
    Returns structured dict with answer + usage metadata.
    """
    response = client.converse(
        modelId=model_id,
        # messages: list of turns; role must alternate user/assistant
        messages=[
            {
                "role": "user",
                "content": [{"text": text}],   # content is a list of blocks
            }
        ],
        # system: top-level field, not inside messages
        system=[{"text": system_prompt}],
        # inferenceConfig: universal across all models
        inferenceConfig={
            "maxTokens": max_tokens,
            "temperature": temperature,
            "topP": 0.9,
        },
    )

    # stopReason: "end_turn" (normal), "max_tokens", "tool_use"
    stop_reason = response["stopReason"]
    answer = response["output"]["message"]["content"][0]["text"]

    # usage: available from all models via converse API
    usage = response["usage"]
    logger.info(
        f"Model: {model_id} | stop: {stop_reason} | "
        f"in: {usage['inputTokens']} | out: {usage['outputTokens']}"
    )
    return {
        "answer": answer,
        "stop_reason": stop_reason,
        "input_tokens": usage["inputTokens"],
        "output_tokens": usage["outputTokens"],
        "total_tokens": usage["totalTokens"],
    }


# ═══════════════════════════════════════════════════════════════
# 4. STREAMING (critical for UX — first token < 1s)
# ═══════════════════════════════════════════════════════════════

def converse_stream(
    client: boto3.client,
    text: str,
    system_prompt: str = "You are a helpful assistant.",
    model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
) -> Generator[str, None, None]:
    """
    Streaming: yield text chunks as they arrive from the model.
    Critical for chat UX — without streaming, users see blank
    screen for 5-30s then full response dumps at once.
    With streaming, first chunk arrives in ~300ms.
    """
    response = client.converse_stream(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": text}]}],
        system=[{"text": system_prompt}],
        inferenceConfig={"maxTokens": 1024, "temperature": 0.7},
    )

    # EventStream: iterate over server-sent events
    stream = response.get("stream")
    for event in stream:
        # contentBlockDelta: contains actual text token(s)
        if "contentBlockDelta" in event:
            delta = event["contentBlockDelta"]["delta"]
            if "text" in delta:
                yield delta["text"]   # yield each token chunk to caller

        # messageStop: final event with stopReason and usage
        elif "messageStop" in event:
            stop_reason = event["messageStop"]["stopReason"]
            logger.info(f"Stream ended — stopReason: {stop_reason}")

        # metadata: contains usage stats (sent after messageStop)
        elif "metadata" in event:
            usage = event["metadata"].get("usage", {})
            logger.info(
                f"Stream usage — in: {usage.get('inputTokens', '?')}, "
                f"out: {usage.get('outputTokens', '?')}"
            )


def print_streaming_response(client: boto3.client, question: str):
    """Demonstrate streaming by printing tokens as they arrive."""
    print(f"\nStreaming response to: {question}")
    print("-" * 60)
    full_response = ""
    for chunk in converse_stream(client, question):
        print(chunk, end="", flush=True)  # flush=True ensures immediate display
        full_response += chunk
    print("\n" + "-" * 60)
    return full_response


# ═══════════════════════════════════════════════════════════════
# 5. TOOL USE WITH CONVERSE
# ═══════════════════════════════════════════════════════════════

def converse_with_tools(
    client: boto3.client,
    user_question: str,
    model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
) -> str:
    """
    Tool use (function calling) via converse API.
    Pattern: send tools definition -> model returns toolUse block
    -> execute the function -> send toolResult -> get final answer.
    Loop until model returns end_turn (no more tool calls).
    """
    # Define available tools with JSON Schema for parameters
    tool_config = {
        "tools": [
            {
                "toolSpec": {
                    "name": "get_policy_details",
                    "description": "Retrieve insurance policy details by policy number.",
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "policy_number": {
                                    "type": "string",
                                    "description": "The policy number (e.g. POL-12345)",
                                },
                                "field": {
                                    "type": "string",
                                    "description": "Specific field to retrieve: coverage, premium, deductible",
                                    "enum": ["coverage", "premium", "deductible"],
                                },
                            },
                            "required": ["policy_number"],
                        }
                    },
                }
            }
        ]
    }

    messages = [
        {"role": "user", "content": [{"text": user_question}]}
    ]

    # Agentic loop: run until model stops requesting tools
    max_iterations = 5   # guard against infinite loops in production
    for iteration in range(max_iterations):
        response = client.converse(
            modelId=model_id,
            messages=messages,
            system=[{"text": "You are an insurance assistant. Use tools to look up policy info."}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0},
            toolConfig=tool_config,
        )

        stop_reason = response["stopReason"]
        assistant_message = response["output"]["message"]
        messages.append(assistant_message)  # add assistant turn to history

        if stop_reason == "end_turn":
            # Model finished — extract final text response
            for block in assistant_message["content"]:
                if "text" in block:
                    return block["text"]

        elif stop_reason == "tool_use":
            # Model is requesting tool execution
            tool_results = []
            for block in assistant_message["content"]:
                if "toolUse" in block:
                    tool_call = block["toolUse"]
                    tool_name = tool_call["name"]
                    tool_input = tool_call["toolUseId"]

                    # Execute the actual function (stub here — real DB call in prod)
                    result = _execute_tool(tool_name, tool_call["input"])
                    logger.info(f"Tool executed: {tool_name} -> {result}")

                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tool_call["toolUseId"],
                            "content": [{"text": json.dumps(result)}],
                            "status": "success",
                        }
                    })

            # Send tool results back to model as user turn
            messages.append({"role": "user", "content": tool_results})

    return "Max tool iterations reached — unable to complete request."


def _execute_tool(tool_name: str, tool_input: dict) -> dict:
    """Stub: simulate database lookup for tool call results."""
    if tool_name == "get_policy_details":
        policy_number = tool_input.get("policy_number", "UNKNOWN")
        field = tool_input.get("field", "all")
        # In production this queries a real database
        mock_data = {
            "policy_number": policy_number,
            "coverage": "$500,000 liability, $100,000 property",
            "premium": "$1,200/year",
            "deductible": "$2,500",
        }
        return {k: v for k, v in mock_data.items() if field == "all" or k == field}
    return {"error": f"Unknown tool: {tool_name}"}


# ═══════════════════════════════════════════════════════════════
# 6. VISION — MULTIMODAL IMAGE INPUT
# ═══════════════════════════════════════════════════════════════

def converse_with_image(
    client: boto3.client,
    image_path: str,
    question: str,
    model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
) -> str:
    """
    Multimodal: send image + text together.
    Content block uses 'image' type with bytes source.
    Supported formats: jpeg, png, gif, webp.
    """
    # Read image file as bytes
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    # Determine format from extension
    ext = image_path.rsplit(".", 1)[-1].lower()
    fmt_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp"}
    image_format = fmt_map.get(ext, "jpeg")

    response = client.converse(
        modelId=model_id,
        messages=[
            {
                "role": "user",
                "content": [
                    # Image block first, then the question text
                    {
                        "image": {
                            "format": image_format,
                            "source": {"bytes": image_bytes},  # raw bytes, not base64
                        }
                    },
                    {"text": question},
                ],
            }
        ],
        inferenceConfig={"maxTokens": 1024, "temperature": 0.3},
    )
    return response["output"]["message"]["content"][0]["text"]


# ═══════════════════════════════════════════════════════════════
# 7. KNOWLEDGE BASES — MANAGED RAG
# ═══════════════════════════════════════════════════════════════

def query_knowledge_base(
    kb_id: str,
    question: str,
    region: str = "us-east-1",
    top_k: int = 5,
) -> dict:
    """
    Bedrock Knowledge Bases: fully managed RAG.
    Setup (one-time, in AWS console or Terraform):
      1. Create KB → choose data source (S3 bucket)
      2. Choose embeddings (Titan Embeddings G1 — Text)
      3. Choose vector store (OpenSearch Serverless or Aurora pgvector)
      4. Sync data source → Bedrock chunks, embeds, indexes docs
    Then query with retrieve() or retrieve_and_generate().
    """
    # bedrock-agent-runtime is a separate client from bedrock-runtime
    agent_runtime = boto3.client("bedrock-agent-runtime", region_name=region)

    # retrieve(): returns relevant chunks WITHOUT generating a response
    # Use this when you want to inject chunks into your own prompt
    retrieve_response = agent_runtime.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": question},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": top_k,         # how many chunks to return
                "overrideSearchType": "HYBRID",   # HYBRID = semantic + keyword
            }
        },
    )

    retrieved_results = retrieve_response["retrievalResults"]
    logger.info(f"Retrieved {len(retrieved_results)} chunks from Knowledge Base.")

    # retrieve_and_generate(): full managed RAG — retrieves AND generates answer
    rag_response = agent_runtime.retrieve_and_generate(
        input={"text": question},
        retrieveAndGenerateConfiguration={
            "type": "KNOWLEDGE_BASE",
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": kb_id,
                "modelArn": f"arn:aws:bedrock:{region}::foundation-model/"
                            "anthropic.claude-3-5-sonnet-20241022-v2:0",
                "retrievalConfiguration": {
                    "vectorSearchConfiguration": {"numberOfResults": top_k}
                },
            },
        },
    )

    answer = rag_response["output"]["text"]
    citations = rag_response.get("citations", [])   # source documents used

    return {
        "answer": answer,
        "retrieved_chunks": len(retrieved_results),
        "citations": [
            {
                "text": c["generatedResponsePart"]["textResponsePart"]["text"],
                "sources": [r["location"] for r in c.get("retrievedReferences", [])],
            }
            for c in citations
        ],
    }


# ═══════════════════════════════════════════════════════════════
# 8. GUARDRAILS
# ═══════════════════════════════════════════════════════════════

def apply_guardrail(
    client: boto3.client,
    text: str,
    guardrail_id: str,
    guardrail_version: str = "DRAFT",
) -> dict:
    """
    Guardrails independently filter content before or after LLM.
    Use apply_guardrail() to test; attach guardrailIdentifier param
    to converse() calls to apply automatically in production.

    Guardrail capabilities (configured in AWS console):
      - Content filters : block violence/hate/sexual content (0-100%)
      - PII detection   : detect + REDACT/BLOCK SSN, email, phone, etc.
      - Topic blocking  : "never discuss competitor products"
      - Word filters    : custom blocked words/phrases
      - Grounding check : ensure answer is grounded in KB sources
    """
    response = client.apply_guardrail(
        guardrailIdentifier=guardrail_id,
        guardrailVersion=guardrail_version,
        source="INPUT",   # INPUT for user prompt, OUTPUT for model response
        content=[{"text": {"text": text}}],
    )

    action = response["action"]               # "NONE" or "GUARDRAIL_INTERVENED"
    outputs = response.get("outputs", [])
    assessments = response.get("assessments", [])

    if action == "GUARDRAIL_INTERVENED":
        logger.warning(f"Guardrail intervened on input text.")
        # Log assessments for audit trail
        for assessment in assessments:
            if "topicPolicy" in assessment:
                for topic in assessment["topicPolicy"]["topics"]:
                    logger.warning(f"  Blocked topic: {topic['name']} ({topic['action']})")
            if "contentPolicy" in assessment:
                for filter_ in assessment["contentPolicy"]["filters"]:
                    logger.warning(f"  Content filter: {filter_['type']} confidence={filter_['confidence']}")

    return {"action": action, "safe": action == "NONE"}


# ═══════════════════════════════════════════════════════════════
# 9. ERROR HANDLING AND RETRY WITH BACKOFF
# ═══════════════════════════════════════════════════════════════

def converse_with_retry(
    client: boto3.client,
    text: str,
    model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
    max_retries: int = 5,
) -> dict:
    """
    Production-grade error handling for all Bedrock API calls.
    Bedrock exceptions to handle:
      ThrottlingException         — too many requests, backoff+retry
      ModelErrorException         — model itself errored, log+alert
      ServiceQuotaExceededException — hit account quota, request increase
      ValidationException         — bad request payload, do NOT retry
      ModelNotReadyException      — model loading, brief retry
    """
    base_delay = 1.0   # starting backoff delay in seconds

    for attempt in range(max_retries):
        try:
            result = converse(client, text, model_id=model_id)
            return result

        except client.exceptions.ThrottlingException as e:
            # Rate limited — exponential backoff with random jitter
            if attempt == max_retries - 1:
                logger.error("Max retries exceeded for ThrottlingException.")
                raise
            # jitter: random factor prevents thundering herd on retry
            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            logger.warning(f"Throttled. Retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(delay)

        except client.exceptions.ModelErrorException as e:
            # Model internal error — retry once, then alert
            logger.error(f"Model error on attempt {attempt + 1}: {e}")
            if attempt == 0:
                time.sleep(2)
                continue
            raise   # escalate after first retry

        except client.exceptions.ServiceQuotaExceededException as e:
            # Account-level quota — no point retrying, need quota increase
            logger.critical(f"Service quota exceeded: {e}. Request limit increase in AWS console.")
            raise

        except client.exceptions.ValidationException as e:
            # Bad request — do NOT retry, the same request will always fail
            logger.error(f"Validation error (do not retry): {e}")
            raise

        except Exception as e:
            logger.error(f"Unexpected error: {type(e).__name__}: {e}")
            raise

    raise RuntimeError("converse_with_retry exhausted all attempts.")


# ═══════════════════════════════════════════════════════════════
# 10. CONVERSATION HISTORY (multi-turn)
# ═══════════════════════════════════════════════════════════════

@dataclass
class BedrockConversation:
    """
    Manages multi-turn conversation state for the Converse API.
    Keeps full message history in memory; for long sessions,
    summarise or truncate old turns to stay within context window.
    """
    client: boto3.client
    model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    system_prompt: str = "You are a helpful customer service assistant."
    messages: list = field(default_factory=list)
    max_history_turns: int = 20   # keep last N turns; older turns dropped

    def chat(self, user_text: str) -> str:
        """Send a user message and get a response, maintaining history."""
        # Append user turn
        self.messages.append(
            {"role": "user", "content": [{"text": user_text}]}
        )

        # Trim history if too long (keep system prompt separate)
        if len(self.messages) > self.max_history_turns * 2:
            # Remove oldest 2 messages (1 user + 1 assistant turn)
            self.messages = self.messages[2:]
            logger.info("Trimmed conversation history — oldest turn removed.")

        response = self.client.converse(
            modelId=self.model_id,
            messages=self.messages,
            system=[{"text": self.system_prompt}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0.7},
        )

        assistant_message = response["output"]["message"]
        self.messages.append(assistant_message)   # save assistant turn

        answer = assistant_message["content"][0]["text"]
        return answer

    def reset(self):
        """Clear conversation history to start fresh."""
        self.messages = []
        logger.info("Conversation history cleared.")


# ═══════════════════════════════════════════════════════════════
# 11. FULL PRODUCTION: CUSTOMER SERVICE BOT
# ═══════════════════════════════════════════════════════════════

def production_customer_service_demo():
    """
    Full production customer service bot demonstrating:
      - Converse API with system prompt
      - Streaming for UX
      - Tool use for policy lookups
      - Guardrails for PII + competitor blocking
      - Error handling with retry
      - Conversation history management
      - Cost tracking per request

    Architecture:
      User Message
        -> Guardrail (INPUT) — block PII, competitor mentions
        -> ConverseStream — streaming response with tools
        -> Guardrail (OUTPUT) — redact PII in response
        -> CloudWatch metric: latency, tokens, cost
    """
    print("=" * 60)
    print("PRODUCTION CUSTOMER SERVICE BOT — AWS BEDROCK")
    print("=" * 60)

    # Client setup (uses default credential chain)
    client = get_bedrock_client(region="us-east-1")

    # Simulate conversation session
    session = BedrockConversation(
        client=client,
        model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
        system_prompt=(
            "You are a helpful insurance customer service agent. "
            "Use the get_policy_details tool to look up policy information. "
            "Never reveal other customers' policy details. "
            "If asked about competitors, politely redirect to our services."
        ),
        max_history_turns=10,
    )

    # Simulate Q&A turns
    test_questions = [
        "Hi, I'd like to know my premium for policy POL-98765.",
        "What's the deductible on that same policy?",
        "Can you explain what liability coverage means?",
    ]

    total_cost_usd = 0.0
    # Claude 3.5 Sonnet pricing (approximate, verify in AWS console)
    COST_PER_1K_INPUT = 0.003   # $0.003 per 1K input tokens
    COST_PER_1K_OUTPUT = 0.015  # $0.015 per 1K output tokens

    for i, question in enumerate(test_questions, 1):
        print(f"\n[Turn {i}] User: {question}")
        start_time = time.time()

        try:
            # In real prod: apply guardrail to INPUT first
            # guardrail_check = apply_guardrail(client, question, "your-guardrail-id")
            # if not guardrail_check["safe"]:
            #     print("  [BLOCKED] Input violated guardrail policy.")
            #     continue

            # For demo: use non-streaming converse with retry
            result = converse_with_retry(
                client=client,
                text=question,
                model_id=session.model_id,
            )

            latency_ms = (time.time() - start_time) * 1000

            # Calculate cost for this request
            request_cost = (
                (result["input_tokens"] / 1000) * COST_PER_1K_INPUT +
                (result["output_tokens"] / 1000) * COST_PER_1K_OUTPUT
            )
            total_cost_usd += request_cost

            print(f"  Assistant: {result['answer'][:200]}...")
            print(f"  Latency  : {latency_ms:.0f}ms")
            print(f"  Tokens   : {result['input_tokens']} in / {result['output_tokens']} out")
            print(f"  Cost     : ${request_cost:.5f}")

        except Exception as e:
            logger.error(f"Request failed: {e}")
            print(f"  [ERROR] {e}")

    print(f"\n{'='*60}")
    print(f"Session complete. Total cost: ${total_cost_usd:.4f}")
    print(f"{'='*60}")


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("AWS Bedrock L07 — Architecture Summary")
    print("=" * 60)
    print("""
Bedrock Model Roster:
  anthropic.claude-3-5-sonnet-20241022-v2:0  — best quality
  anthropic.claude-3-haiku-20240307-v1:0     — fastest/cheapest
  meta.llama3-70b-instruct-v1:0              — open weight option
  amazon.titan-text-premier-v1:0             — AWS native
  mistral.mistral-large-2402-v1:0            — EU data residency

API Hierarchy (newest to oldest):
  converse / converse_stream    — unified, use for all new code
  invoke_model                  — legacy, model-specific payload

Auth in Production:
  IAM Role (instance profile)   — EC2/ECS/Lambda: automatic
  AWS SSO profile               — developer workstations
  NEVER hardcode access keys    — immediate rotation if leaked

Key Services Used:
  bedrock-runtime               — model invocation
  bedrock-agent-runtime         — Knowledge Base RAG queries
  bedrock                       — management (create KB, agents)

Compliance:
  HIPAA  — eligible with BAA signed with AWS
  SOC2   — inherited from AWS infrastructure
  GDPR   — data stays in your chosen AWS region

Provisioned Throughput vs On-Demand:
  On-demand    — pay per token, limited TPS, good for dev/low traffic
  Provisioned  — buy model units, guaranteed TPS, no per-token cost
  Breakeven    — ~60% sustained utilization favors provisioned
""")
    print("Set AWS credentials to run live demos.")
    print("Run production_customer_service_demo() for full pipeline.")
