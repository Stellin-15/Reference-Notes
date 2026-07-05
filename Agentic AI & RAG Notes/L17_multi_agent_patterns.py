# ============================================================
# L17: Multi-Agent Patterns — Choosing a Paradigm, and When Not To
# ============================================================
# WHAT: A direct comparison of the orchestration paradigms from L13-L16
#       (graph-based, role-based team, conversational, event-driven,
#       model-driven, collaborative role-refinement), a decision
#       framework for choosing between them, and — just as importantly
#       — when a SINGLE agent beats any multi-agent architecture at all.
# WHY: L12-L16 each taught one paradigm/framework in isolation. Real
#      projects need to CHOOSE, and the most common real mistake in
#      practice isn't picking the "wrong" framework among good options
#      — it's reaching for ANY multi-agent architecture when a single,
#      well-designed agent (or no agent at all) would have solved the
#      problem more reliably and cheaply.
# LEVEL: Advanced (Phase 3 of 7 — final agentic-frameworks lesson)
# ============================================================

"""
CONCEPT OVERVIEW:
Every framework covered so far solves the SAME underlying problem
(coordinate multiple reasoning/tool-use steps, possibly across multiple
distinct "agents") with a different mental model:

  - GRAPH (LangGraph, L13): explicit nodes/edges, arbitrary cycles,
    fine-grained state control — you design the control flow yourself.
  - TEAM (CrewAI, L14): declared roles/goals/tasks, sequential or
    hierarchical process — you describe WHO does WHAT, not HOW they
    coordinate mechanically.
  - CONVERSATION (AutoGen, L15): agents converse; a manager decides
    speaking order — emergent, less pre-determined coordination.
  - EVENT-DRIVEN (LlamaIndex Workflows, L16): steps react to event
    types; routing is inferred, not explicitly wired.
  - MODEL-DRIVEN (AWS Strands, L16): lean heavily on the underlying
    LLM's own reasoning with minimal explicit control-flow code.
  - COLLABORATIVE ROLE-REFINEMENT (CAMEL, L16): agents negotiate their
    OWN roles/sub-tasks from a broad prompt, rather than pre-defined ones.

The RIGHT choice depends on: how PREDICTABLE the task's structure is (a
known, fixed sequence favors CrewAI's sequential process or a simple
LangGraph chain; a genuinely unpredictable, discovery-driven task favors
AutoGen's emergent conversation or CAMEL's role-refinement); how much
FINE-GRAINED CONTROL you need over exact execution (LangGraph gives the
most; the higher-level frameworks trade control for faster authoring);
and your TEAM'S FAMILIARITY/ecosystem fit (an AWS-committed team
naturally leans toward Strands/Bedrock Agents, L18).

CRITICALLY: single-agent vs multi-agent is a SEPARATE decision from
which multi-agent framework to use, and it's the more consequential one.
Multi-agent architectures add REAL overhead: more LLM calls (cost and
latency), more coordination failure modes (agents talking past each
other, an agent waiting on another that never responds usefully), and
genuinely harder debugging (a wrong final answer could originate from
ANY agent in the chain, not one obvious place). A single, well-prompted
agent with good tools (L12, L21) and a clear, if lengthy, ReAct loop
often outperforms a poorly-decomposed multi-agent system for tasks that
DON'T have a natural, clean division of responsibility.

PRODUCTION USE CASE:
A team initially builds a 4-agent CrewAI pipeline (Researcher, Analyst,
Writer, Editor) for a report-generation task, but after measuring cost
and reliability, discovers a SINGLE agent with a well-structured,
detailed system prompt and the same tools achieves comparable quality at
roughly a quarter of the LLM call cost and with far fewer coordination
failures (the Writer agent occasionally producing output the Editor
agent couldn't parse correctly) — the multi-agent decomposition wasn't
adding value proportional to its cost for this specific, well-understood
task.

COMMON MISTAKES:
- Defaulting to a multi-agent architecture because it feels more
  "sophisticated" or because a task has multiple LOGICAL steps — a task
  having multiple steps doesn't mean it needs multiple AGENTS; a single
  agent working through multiple steps (or even a static pipeline, L04's
  RAG pattern, with no agent at all) is often simpler and more reliable.
- Choosing a highly flexible/emergent paradigm (AutoGen's group chat,
  CAMEL's role-refinement) for a task whose structure is actually well
  understood in advance — this trades away predictability for
  flexibility you don't need, increasing cost and reducing debuggability
  with no corresponding benefit.
- Not measuring actual cost/latency/reliability differences between
  candidate architectures before committing — "single agent vs 4-agent
  crew" is an empirical question answerable by running both on a
  representative task sample, not a decision to make purely by intuition.
"""

from dataclasses import dataclass


# ------------------------------------------------------------------
# 1. Paradigm decision matrix
# ------------------------------------------------------------------
@dataclass
class ParadigmFit:
    paradigm: str
    task_predictability: str    # "fixed" | "somewhat variable" | "highly variable"
    control_needed: str          # "fine-grained" | "moderate" | "minimal"
    good_fit_example: str


PARADIGM_DECISION_MATRIX = [
    ParadigmFit("LangGraph (graph)", "any — cycles/conditions handle variability explicitly",
                "fine-grained", "Human-in-the-loop approval workflows; complex "
                "conditional branching needing precise state control"),
    ParadigmFit("CrewAI (team, sequential)", "fixed", "moderate",
                "A known editorial pipeline: research -> write -> edit, in that order"),
    ParadigmFit("CrewAI (team, hierarchical)", "somewhat variable", "moderate",
                "A team where task ROUTING (not just execution) needs a dynamic decision"),
    ParadigmFit("AutoGen (conversation)", "highly variable", "minimal",
                "Open-ended exploratory analysis with a code-executor agent"),
    ParadigmFit("LlamaIndex Workflows (event-driven)", "somewhat variable", "moderate",
                "Complex, many-branch RAG/agent pipelines with numerous possible paths"),
    ParadigmFit("CAMEL (role-refinement)", "highly variable", "minimal",
                "Broad, underspecified tasks needing autonomous role/sub-task decomposition"),
]


def print_decision_matrix():
    for p in PARADIGM_DECISION_MATRIX:
        print(f"{p.paradigm}")
        print(f"  fits task predictability: {p.task_predictability}")
        print(f"  control needed: {p.control_needed}")
        print(f"  good fit example: {p.good_fit_example}\n")


# ------------------------------------------------------------------
# 2. Single-agent vs multi-agent — the more consequential decision
# ------------------------------------------------------------------
SINGLE_VS_MULTI_AGENT_CHECKLIST = [
    "Does the task have a NATURAL, clean division of responsibility "
    "where each 'agent' would genuinely need a DIFFERENT set of tools, "
    "context, or expertise? If one agent with all the tools could "
    "reasonably do the whole task, that's a signal toward single-agent.",
    "Have you MEASURED (not assumed) that the multi-agent decomposition "
    "actually improves quality enough to justify its added LLM call cost "
    "and latency, versus a single well-prompted agent?",
    "Are coordination failures (one agent misunderstanding another's "
    "output, an agent waiting on a response that doesn't arrive in a "
    "usable form) a real, observed problem in your multi-agent "
    "prototype? If so, that's direct evidence the decomposition is "
    "adding fragility, not just complexity.",
    "Could a STATIC PIPELINE (L04's fixed retrieve-then-generate "
    "pattern, no agent loop at all) solve this task just as well? Not "
    "every LLM application needs agent-level flexibility.",
]


def estimate_cost_comparison(single_agent_calls: int, multi_agent_calls: int,
                                cost_per_call: float) -> dict:
    """A concrete, quantifiable comparison worth actually running before
    committing to a multi-agent architecture."""
    return {
        "single_agent_cost": single_agent_calls * cost_per_call,
        "multi_agent_cost": multi_agent_calls * cost_per_call,
        "multi_agent_overhead_multiplier": multi_agent_calls / single_agent_calls,
    }


if __name__ == "__main__":
    print("=== Paradigm decision matrix ===")
    print_decision_matrix()

    print("=== Single-agent vs multi-agent checklist ===")
    for item in SINGLE_VS_MULTI_AGENT_CHECKLIST:
        print(f"  - {item}")

    print("\n=== A concrete cost comparison worth running ===")
    comparison = estimate_cost_comparison(single_agent_calls=6, multi_agent_calls=22, cost_per_call=0.02)
    for k, v in comparison.items():
        print(f"  {k}: {v}")

"""
PRODUCTION CONTEXT EXAMPLE:
A legal-tech company prototypes a contract-review task with a 5-agent
CrewAI hierarchical crew (Clause Extractor, Risk Analyst, Precedent
Researcher, Summary Writer, Manager) and, in parallel, a single agent
with all five capabilities as tools it can call as needed. After running
both against 50 real contracts, the single-agent version produces
comparably accurate risk flags at roughly a third of the total token
cost and with a much shorter, more debuggable execution trace (one
agent's reasoning history to inspect, not five agents' interleaved
outputs) — the team ships the single-agent version, reserving the
multi-agent architecture's added complexity for a LATER feature where
genuinely parallel, independent sub-investigations (which the
single-agent's sequential tool-calling couldn't parallelize) provide
a real, measured latency benefit.
"""
