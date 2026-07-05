# ============================================================
# L23: Agent Observability and Evaluation — LangSmith, Langfuse, Arize
#      Phoenix, W&B Weave, TruLens, Ragas, Promptfoo, Helicone
# ============================================================
# WHAT: How to actually SEE what a multi-step agent did (tracing every
#       LLM call, tool call, and intermediate reasoning step), and how
#       to systematically EVALUATE whether it's working — using the
#       dedicated tracing/eval tooling built specifically for LLM
#       applications, since traditional APM tooling wasn't designed for
#       this shape of system.
# WHY: An agent that "usually seems to work" is not observable or
#      evaluable in any rigorous sense — Phase 3-5's frameworks all
#      produce genuinely complex execution traces (multiple LLM calls,
#      tool calls, retries, branching), and without dedicated tracing
#      you cannot debug a bad outcome, and without dedicated evaluation
#      you cannot detect a REGRESSION when you change a prompt or swap a model.
# LEVEL: Advanced (Phase 6 of 7)
# ============================================================

"""
CONCEPT OVERVIEW:
TRACING an agent means capturing the FULL execution tree of one request:
every LLM call (with its exact prompt and response), every tool call
(with arguments and results), the timing of each step, and — critically
— the NESTING/CAUSALITY between them (which LLM call led to which tool
call, which tool result fed into which subsequent LLM call). This is
DIFFERENT from traditional application tracing/APM (this repo's
Observability Notes domain covers general distributed tracing) because
the unit of interest is a semantically meaningful LLM interaction (a
prompt, a completion, a tool decision), not just a generic function call
— LANGSMITH (LangChain/LangGraph's native tracing platform), LANGFUSE
(open-source, framework-agnostic LLM tracing), ARIZE PHOENIX (open-
source, strong on embedding/retrieval-specific visualization for RAG
debugging), and W&B WEAVE (Weights & Biases' LLM-specific tracing,
integrated with their broader ML experiment tracking) all provide this
LLM-native tracing view.

EVALUATION is the SYSTEMATIC measurement of whether an agent/RAG system
is actually working, as opposed to spot-checking a handful of outputs by
eye. RAGAS (introduced in L04 for RAG-specific metrics — faithfulness,
context precision/recall, answer relevance) extends naturally to
agent evaluation too. TRULENS provides a broader "feedback function"
framework — configurable, often LLM-based evaluators that score
arbitrary aspects of an agent's output (groundedness, relevance, custom
business-specific criteria) systematically across many runs, not just
individually inspected examples. PROMPTFOO is specifically built for
PROMPT/AGENT REGRESSION TESTING — define a set of test cases (input,
expected properties of the output) and run them automatically against
every prompt or model change, catching regressions BEFORE deployment
rather than discovering them from production complaints, directly
analogous to a unit test suite but for prompt/agent behavior.

HELICONE is positioned more as an LLM-API-usage OBSERVABILITY/PROXY
layer — sitting between your application and the LLM provider's API,
capturing cost, latency, and usage patterns across every call
transparently, useful specifically for the operational/cost-monitoring
angle (which this repo's Observability Notes and FinOps content covers
in general terms, applied here specifically to LLM API spend).

PRODUCTION USE CASE:
A team debugging "why did the agent give a wrong answer to this specific
customer" opens the LangSmith/Langfuse trace for that exact request and
sees, step by step: the initial user message, the agent's first tool
call (a database lookup that returned an outdated cached result), the
subsequent LLM call reasoning from that stale data, and the final
(wrong) answer — root-causing the issue to a caching bug in ONE specific
tool, in minutes, versus trying to reproduce and guess at the failure
from the final output alone.

COMMON MISTAKES:
- Relying only on manually spot-checking agent outputs ("looks fine to
  me") instead of systematic evaluation (Ragas/TruLens/Promptfoo) run
  against a representative test set — this misses SYSTEMATIC issues that
  don't show up in the small, often cherry-picked sample of examples a
  human happens to manually review.
- Adding tracing only AFTER a production incident forces the question
  "what did the agent actually do" — tracing should be instrumented from
  the start of any agent build with real users, not retrofitted reactively
  once debugging without it becomes painful enough to justify the effort.
- Not running regression tests (Promptfoo-style) before deploying a
  prompt or model change — an agent that worked well yesterday can
  silently regress after a seemingly minor prompt tweak or a model
  version upgrade, and without automated regression testing this is
  discovered from user complaints rather than caught before deployment.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Tracing — LangSmith and Langfuse
# ------------------------------------------------------------------
LANGSMITH_EXAMPLE = textwrap.dedent("""\
    import os
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = "..."

    # With tracing enabled, EVERY LangGraph/LangChain execution (every
    # LLM call, tool call, and their nesting/timing) is automatically
    # captured and viewable in LangSmith's UI as a full execution tree —
    # zero additional code needed beyond setting these environment variables.

    result = rag_chain.invoke("How do I request a refund?")
    # -> a full trace is now viewable: retriever call -> formatted
    #    context -> prompt construction -> model call -> parsed output,
    #    each with exact inputs/outputs/timing.
""")

LANGFUSE_EXAMPLE = textwrap.dedent("""\
    from langfuse.decorators import observe

    # Langfuse is FRAMEWORK-AGNOSTIC — works whether you're using
    # LangGraph, CrewAI, a raw OpenAI call, or a fully custom agent loop,
    # unlike LangSmith's tighter (though not exclusive) LangChain focus.
    @observe()
    def run_agent(user_query: str) -> str:
        thought = generate_thought(user_query)
        tool_result = execute_tool(thought)
        return generate_final_answer(tool_result)

    # Each @observe()-decorated function call and its nested calls
    # become part of one trace, viewable in Langfuse's dashboard.
""")

# ------------------------------------------------------------------
# 2. Evaluation — Ragas, TruLens, Promptfoo
# ------------------------------------------------------------------
RAGAS_AGENT_EVAL_EXAMPLE = textwrap.dedent("""\
    from ragas import evaluate
    from ragas.metrics import faithfulness, answer_relevancy, context_precision
    from datasets import Dataset

    eval_dataset = Dataset.from_dict({
        "question": ["How long does a refund take?"],
        "answer": ["Refunds are processed within 5 business days."],
        "contexts": [["Refunds are processed within 5 business days of approval."]],
        "ground_truth": ["5 business days"],
    })

    results = evaluate(eval_dataset, metrics=[faithfulness, answer_relevancy, context_precision])
    print(results)   # a scored report across your ENTIRE eval set, not one example
""")

TRULENS_EXAMPLE = textwrap.dedent("""\
    from trulens_eval import TruChain, Feedback
    from trulens_eval.feedback.provider import OpenAI as TruOpenAI

    provider = TruOpenAI()
    groundedness = Feedback(provider.groundedness_measure_with_cot_reasons)
    relevance = Feedback(provider.relevance).on_input_output()

    # Wraps your EXISTING chain/agent with automatic feedback scoring on
    # every real invocation — evaluation happens continuously on live
    # traffic, not just a fixed offline test set.
    tru_recorder = TruChain(rag_chain, feedbacks=[groundedness, relevance])
    with tru_recorder as recording:
        rag_chain.invoke("How do I request a refund?")
""")

PROMPTFOO_EXAMPLE = textwrap.dedent("""\
    # promptfooconfig.yaml — a regression test SUITE for prompts/agents
    prompts:
      - "prompts/support_agent_v2.txt"
    providers:
      - openai:gpt-4o
    tests:
      - vars: {question: "How long does a refund take?"}
        assert:
          - type: contains
            value: "5 business days"
          - type: llm-rubric
            value: "The answer is polite and does not make up information not in context"
      - vars: {question: "What is your CEO's home address?"}
        assert:
          - type: not-contains
            value: "address"   # should refuse, not attempt to answer

    # Run: promptfoo eval
    # This suite runs AUTOMATICALLY on every prompt/model change — a CI
    # gate for agent behavior, directly analogous to a unit test suite,
    # catching regressions before they reach production.
""")

# ------------------------------------------------------------------
# 3. Helicone — LLM API usage/cost observability
# ------------------------------------------------------------------
HELICONE_EXAMPLE = textwrap.dedent("""\
    from openai import OpenAI

    client = OpenAI(
        base_url="https://oai.hconeai.com/v1",   # proxy through Helicone
        default_headers={"Helicone-Auth": "Bearer ..."},
    )
    # Every call now transparently logs cost, latency, and token usage to
    # Helicone's dashboard — no per-call code change needed beyond the
    # base_url/header configuration, useful specifically for tracking
    # LLM API spend/usage patterns across an entire application.
""")

# ------------------------------------------------------------------
# 4. Tooling landscape summary
# ------------------------------------------------------------------
OBSERVABILITY_TOOL_LANDSCAPE = {
    "LangSmith": "LangChain/LangGraph-native tracing, deep integration.",
    "Langfuse": "Open-source, framework-agnostic LLM tracing.",
    "Arize Phoenix": "Open-source, strong RAG/embedding-specific visualization.",
    "W&B Weave": "LLM tracing integrated with Weights & Biases' broader "
        "ML experiment tracking.",
    "TruLens": "Continuous feedback-function-based evaluation on live traffic.",
    "Ragas": "RAG-specific metrics (faithfulness, precision/recall) run "
        "against an offline eval dataset.",
    "Promptfoo": "Prompt/agent regression testing — a CI-style test "
        "suite for LLM behavior.",
    "Helicone": "LLM API usage/cost observability via a transparent proxy.",
}


if __name__ == "__main__":
    print(LANGSMITH_EXAMPLE)
    print(LANGFUSE_EXAMPLE)
    print(RAGAS_AGENT_EVAL_EXAMPLE)
    print(TRULENS_EXAMPLE)
    print(PROMPTFOO_EXAMPLE)
    print(HELICONE_EXAMPLE)

    print("=== Observability/evaluation tool landscape ===")
    for tool, note in OBSERVABILITY_TOOL_LANDSCAPE.items():
        print(f"{tool}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A team maintains a Promptfoo regression suite of 200 test cases covering
their support agent's core behaviors (correct refund policy answers,
appropriate refusals for out-of-scope questions, tone requirements) —
every prompt change or model upgrade runs against this suite in CI
before deployment, catching a regression where a new model version
started being measurably LESS willing to escalate genuinely urgent
issues to a human, a subtle behavioral shift that manual spot-checking
of a handful of example conversations had completely missed before the
regression suite caught it automatically.
"""
