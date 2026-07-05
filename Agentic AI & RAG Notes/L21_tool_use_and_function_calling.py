# ============================================================
# L21: Tool Use and Function Calling — Schemas, Selection, Error Handling
# ============================================================
# WHAT: How an LLM actually decides to call a tool and with what
#       arguments (function calling / tool-use APIs), writing effective
#       tool schemas/descriptions, strategies for tool SELECTION when an
#       agent has many tools available, and handling tool execution errors.
# WHY: Every framework and agent pattern covered in Phase 3-5 depends
#      entirely on tool use working correctly — a badly-described tool,
#      a poorly-designed schema, or unhandled tool errors will degrade
#      or break an agent regardless of how sophisticated its
#      orchestration framework is.
# LEVEL: Advanced (Phase 5 of 7 — final protocol/memory/tools lesson)
# ============================================================

"""
CONCEPT OVERVIEW:
FUNCTION CALLING (the underlying mechanism, regardless of which
framework wraps it) works like this: you describe available tools to
the model as a structured SCHEMA (name, description, parameters with
types) alongside the conversation. The model, when it decides a tool
call would help answer the current request, returns a STRUCTURED
response indicating which tool to call and with what arguments (as
JSON), INSTEAD OF a plain text response. Your application code then
actually EXECUTES that tool call (the model itself never runs the
function — it only decides what to call and with what arguments) and
feeds the result back into the conversation as an observation, exactly
matching L12's ReAct loop mechanics.

TOOL SCHEMA DESIGN matters more than it might seem: the tool's NAME and
DESCRIPTION are the model's ONLY signal for deciding when and how to use
it — a vague description ("get data") gives the model little basis for
choosing correctly between similar tools, while a specific, well-written
one ("get_order_status: retrieve the current shipping status for a
SPECIFIC order ID, use this when the user asks about an order they've
already placed") measurably improves correct tool selection and argument
extraction. PARAMETER descriptions matter too — a parameter named
`id` with no description is more error-prone than one named
`order_id` with a description clarifying its expected format.

TOOL SELECTION becomes a real design problem once an agent has MANY
available tools (dozens or more) — including every tool's full schema in
every prompt wastes context and can genuinely confuse the model about
which tool applies (especially with several similarly-named/-purposed
tools). Common mitigations: GROUPING tools by category and only exposing
the relevant group based on the conversation's apparent topic, or using
a RETRIEVAL step (embedding tool descriptions, L02-L03, and retrieving
only the most relevant few tools for the current query — literally RAG
applied to tool selection instead of documents).

ERROR HANDLING is essential because tool calls WILL fail in production —
a malformed argument the model generated, an external API being down, a
permission error. The tool's error result should be fed back into the
conversation as an OBSERVATION (exactly like a successful result), giving
the model a chance to RECOVER (retry with corrected arguments, try a
different tool, or explain the failure to the user) rather than the
whole agent process crashing on any tool failure.

PRODUCTION USE CASE:
A customer-support agent with 40 available tools (order lookup, refund
processing, shipping tracking, account management, etc.) uses embedding-
based tool RETRIEVAL — for each incoming user message, only the 5-8 most
semantically relevant tools are included in that turn's prompt, keeping
the model focused on plausible options rather than choosing among 40
tool schemas every single turn, most of which are irrelevant to any
given message.

COMMON MISTAKES:
- Writing vague tool names/descriptions ("do_thing", "process") and
  being surprised when the model calls the wrong tool or extracts wrong
  arguments — tool descriptions are effectively PROMPTS in their own
  right and deserve the same care as any other prompt engineering.
- Including EVERY available tool's full schema in every single prompt
  regardless of relevance, once an agent has many tools — this wastes
  context budget and measurably degrades tool-selection accuracy as tool
  count grows past a modest number.
- Letting a tool execution failure crash the entire agent process
  instead of feeding the error back as an observation the model can
  react to — a single external API hiccup shouldn't take down an
  otherwise-working multi-step agent task.
"""

import json
import textwrap
from dataclasses import dataclass
from typing import Callable


# ------------------------------------------------------------------
# 1. Tool schema design — the OpenAI-style function-calling format
# ------------------------------------------------------------------
GOOD_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_order_status",
        "description": (
            "Retrieve the current shipping status for a SPECIFIC order "
            "ID. Use this when the user asks about the status of an "
            "order they have already placed. Do NOT use this to look up "
            "product availability or pricing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The order ID, formatted like 'ORD-12345'.",
                },
            },
            "required": ["order_id"],
        },
    },
}

VAGUE_TOOL_SCHEMA_ANTIPATTERN = {
    "type": "function",
    "function": {
        "name": "get_data",   # ambiguous name
        "description": "Gets data.",   # near-useless description
        "parameters": {
            "type": "object",
            "properties": {"id": {"type": "string"}},   # ambiguous parameter name
            "required": ["id"],
        },
    },
}


def compare_tool_schema_quality():
    print("GOOD schema — specific name, clear usage guidance, described parameter:")
    print(json.dumps(GOOD_TOOL_SCHEMA, indent=2))
    print("\nVAGUE schema — the model has almost nothing to disambiguate on:")
    print(json.dumps(VAGUE_TOOL_SCHEMA_ANTIPATTERN, indent=2))


# ------------------------------------------------------------------
# 2. The full function-calling exchange, end to end
# ------------------------------------------------------------------
FUNCTION_CALLING_EXCHANGE = textwrap.dedent("""\
    from openai import OpenAI
    client = OpenAI()

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "What's the status of order ORD-12345?"}],
        tools=[GOOD_TOOL_SCHEMA],   # the schema, not the function itself —
                                      # the model NEVER executes code directly
    )

    tool_call = response.choices[0].message.tool_calls[0]
    # tool_call.function.name == "get_order_status"
    # tool_call.function.arguments == '{"order_id": "ORD-12345"}'  (a JSON string)

    # YOUR code actually executes the function — the model only DECIDED
    # what to call and with what arguments.
    args = json.loads(tool_call.function.arguments)
    result = get_order_status(**args)

    # Feed the result back as an OBSERVATION for the next model call —
    # exactly L12's ReAct loop mechanics, using the provider's native
    # function-calling format instead of a hand-parsed text convention.
    messages = [
        {"role": "user", "content": "What's the status of order ORD-12345?"},
        response.choices[0].message,
        {"role": "tool", "tool_call_id": tool_call.id, "content": result},
    ]
    final_response = client.chat.completions.create(model="gpt-4o", messages=messages)
""")

# ------------------------------------------------------------------
# 3. Tool selection at scale — embedding-based retrieval
# ------------------------------------------------------------------
@dataclass
class ToolSpec:
    name: str
    description: str


def toy_embed(text: str) -> list[float]:
    """Same illustrative stand-in embedding used elsewhere in this domain."""
    keywords = ["order", "refund", "shipping", "account", "password"]
    return [1.0 if kw in text.lower() else 0.0 for kw in keywords]


def cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def select_relevant_tools(user_message: str, all_tools: list[ToolSpec], top_k: int) -> list[ToolSpec]:
    """
    Instead of including all 40 tool schemas in every prompt, RETRIEVE
    only the most relevant few — literally RAG (L03-L04) applied to tool
    descriptions instead of documents, keeping the model focused and
    the prompt smaller.
    """
    query_emb = toy_embed(user_message)
    scored = [(tool, cosine_sim(query_emb, toy_embed(tool.description))) for tool in all_tools]
    return [t for t, _ in sorted(scored, key=lambda x: x[1], reverse=True)[:top_k]]


# ------------------------------------------------------------------
# 4. Error handling — feeding failures back as observations
# ------------------------------------------------------------------
def execute_tool_safely(tool_func: Callable, **kwargs) -> str:
    """
    Never lets a tool exception crash the whole agent process — the
    error is caught and returned as a STRING OBSERVATION the model can
    react to (retry with corrected arguments, try a different tool, or
    explain the failure to the user), exactly like a successful result
    would be fed back.
    """
    try:
        return str(tool_func(**kwargs))
    except TypeError as e:
        return f"Error: invalid arguments for this tool ({e}). Please check the required parameters."
    except Exception as e:
        return f"Error: the tool failed to execute ({e}). Consider trying a different approach."


def get_order_status(order_id: str) -> str:
    if order_id == "ORD-12345":
        return "Shipped, arriving in 2 days"
    raise ValueError(f"No order found with ID {order_id}")


if __name__ == "__main__":
    compare_tool_schema_quality()
    print()
    print(FUNCTION_CALLING_EXCHANGE)

    print("--- Tool selection at scale ---")
    all_tools = [
        ToolSpec("get_order_status", "Check shipping status for an order"),
        ToolSpec("process_refund", "Process a refund for an order"),
        ToolSpec("reset_password", "Reset a user's account password"),
        ToolSpec("update_shipping_address", "Update the shipping address for an order"),
    ]
    relevant = select_relevant_tools("I need to check where my order is", all_tools, top_k=2)
    print("Selected relevant tools:", [t.name for t in relevant])

    print("\n--- Error handling ---")
    print(execute_tool_safely(get_order_status, order_id="ORD-12345"))
    print(execute_tool_safely(get_order_status, order_id="ORD-99999"))
    print(execute_tool_safely(get_order_status, wrong_param="x"))

"""
PRODUCTION CONTEXT EXAMPLE:
A support agent's tool-calling accuracy improved measurably after a
schema rewrite: renaming a vague "process(action, id)" tool into three
specifically-named, specifically-described tools
(process_refund(order_id), cancel_order(order_id), update_address(order_id,
new_address)) — the model previously called "process" with an ambiguous
"action" string that occasionally didn't match any real backend
operation; the specific, well-described tools eliminated that entire
class of error simply by giving the model unambiguous options to choose
from, with zero change to the underlying agent framework or orchestration logic.
"""
