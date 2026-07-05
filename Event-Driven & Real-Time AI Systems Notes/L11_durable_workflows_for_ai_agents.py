# ============================================================
# L11: Durable Workflows for AI Agents
# ============================================================
# WHAT: Combining agent orchestration (this repo's Agentic AI & RAG
#       Notes — LangGraph, CrewAI, AutoGen) with durable execution
#       (Hatchet, L04; Temporal) so long-running, multi-step agent tasks
#       survive process restarts, deployments, and transient failures
#       without losing progress.
# WHY: An agent performing a genuinely long-running task (a multi-hour
#      research task, a workflow waiting on human approval for DAYS) is
#      vulnerable to the SAME durability problem L04 introduced for
#      general background tasks — but agent-specific state (conversation
#      history, intermediate tool results, reasoning trace) makes this
#      MORE valuable to get right, since losing it means re-doing
#      potentially expensive LLM calls, not just re-running cheap logic.
# LEVEL: Advanced (final lesson before the capstone)
# ============================================================

"""
CONCEPT OVERVIEW:
Agentic AI & RAG Notes L13 covered LangGraph's OWN built-in persistence/
checkpointing — which handles durability WITHIN LangGraph's specific
execution model. This lesson covers the BROADER pattern of wrapping
agent execution in a GENERAL-PURPOSE durable execution engine (Hatchet,
L04, or Temporal) — relevant when an agent framework's own persistence
isn't sufficient (e.g. orchestrating MULTIPLE different agent frameworks
or non-agent tasks together in one durable workflow) or when an
organization has already standardized on a specific durable-execution
engine for ALL its background/async work and wants agent tasks to fit
that same operational model rather than introducing a second, framework-
specific persistence mechanism.

The KEY property a durable execution engine adds beyond an agent
framework's own state management: SURVIVING THE WORKER PROCESS ITSELF
DYING — not just "the agent's reasoning loop paused for a human-in-the-
loop step" (which LangGraph's checkpointing already handles), but "the
entire process running the agent crashed, was redeployed, or the
underlying infrastructure was rescheduled" — a genuinely different and
stronger guarantee, achieved by persisting agent state to durable storage
OUTSIDE the process's own memory, at each meaningful step.

COST OF LOST PROGRESS is the specific argument for why this matters MORE
for agent workflows than generic background tasks: a typical background
task retried from scratch might cost cents of compute. An agent task
that's made 15 expensive LLM calls (each with real, non-trivial cost and
latency) before failing needs to RESUME from step 15, not restart from
step 1 — re-running 14 already-successful, already-PAID-FOR LLM calls
purely because the 15th step crashed is a direct, avoidable cost, not
just an inconvenience.

PRODUCTION USE CASE:
A research agent tasked with "analyze these 50 documents and produce a
synthesized report" makes many sequential LLM calls (one per document
analysis, then a final synthesis call) over a run that might take 20+
minutes — wrapping this in a durable execution engine means a mid-run
worker crash (a deployment, an infrastructure hiccup) resumes from
whichever document it had reached, rather than re-analyzing all 50
documents (and re-incurring the LLM cost for each) from scratch.

COMMON MISTAKES:
- Assuming an agent framework's own state management (e.g. LangGraph's
  checkpointing) automatically provides the SAME guarantee as a
  dedicated durable execution engine — LangGraph's checkpointing is
  genuinely useful and DOES survive some failure modes, but combining it
  with a broader durable execution wrapper is a deliberate choice for
  organizations needing the stronger cross-process-crash guarantee or
  wanting one consistent durability model across agent AND non-agent tasks.
- Not persisting INTERMEDIATE, expensive results (each LLM call's output)
  as the agent progresses, and only persisting the FINAL result — this
  means a crash partway through still loses all the expensive
  intermediate work, defeating the purpose of adding durability at all.
- Wrapping every trivial, short-lived agent interaction in heavyweight
  durable execution machinery when a simple, in-memory agent loop (this
  repo's Agentic AI & RAG Notes L12) would suffice — durable execution's
  overhead is justified for genuinely long-running or high-cost agent
  tasks, not a universal default for every agent interaction regardless
  of duration/cost.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Wrapping a multi-step agent task in a Hatchet durable workflow
# ------------------------------------------------------------------
DURABLE_AGENT_WORKFLOW_EXAMPLE = textwrap.dedent("""\
    from hatchet_sdk import Hatchet

    hatchet = Hatchet()

    @hatchet.task(name="analyze-document", retries=3, timeout="60s")
    def analyze_document(context):
        doc = context.workflow_input()["document"]
        # An expensive LLM call — this is exactly the kind of
        # already-paid-for work that should NOT need to be redone if a
        # LATER step in the overall workflow fails.
        analysis = llm_analyze(doc)
        return {"document_id": doc["id"], "analysis": analysis}

    @hatchet.task(name="synthesize-report", retries=2, timeout="120s")
    def synthesize_report(context):
        all_analyses = context.parent_outputs()   # results from EVERY
                                                     # already-completed
                                                     # analyze_document task
        report = llm_synthesize(all_analyses)
        return {"report": report}

    @hatchet.workflow(name="research-agent-workflow")
    def research_agent_workflow(context):
        documents = context.workflow_input()["documents"]

        # Each document's analysis is an INDEPENDENT, individually-
        # durable task — a crash affecting analyze_document #37 out of
        # 50 does NOT require re-running #1-36, which have already
        # succeeded and had their results durably persisted.
        analysis_tasks = [
            context.spawn_workflow("analyze-document", {"document": doc})
            for doc in documents
        ]
        analyses = context.wait_for_all(analysis_tasks)

        report_task = context.spawn_workflow("synthesize-report", {"analyses": analyses})
        return context.wait_for(report_task)
""")

# ------------------------------------------------------------------
# 2. Illustrating the cost-of-lost-progress argument concretely
# ------------------------------------------------------------------
def estimate_cost_of_restart_from_scratch(
    completed_steps: int, total_steps: int, cost_per_llm_call: float,
) -> dict:
    """A concrete illustration of WHY durability matters more for agent
    workflows than cheap background tasks — the WASTED cost of restarting
    from step 1 instead of resuming from the last completed step."""
    wasted_calls = completed_steps
    wasted_cost = wasted_calls * cost_per_llm_call
    return {
        "completed_before_crash": completed_steps,
        "total_steps": total_steps,
        "wasted_llm_calls_if_restarted_from_scratch": wasted_calls,
        "wasted_cost_usd": round(wasted_cost, 2),
        "cost_saved_by_resuming_from_checkpoint": round(wasted_cost, 2),
    }


# ------------------------------------------------------------------
# 3. LangGraph's own checkpointing vs a broader durable execution wrapper
# ------------------------------------------------------------------
WHEN_TO_LAYER_DURABLE_EXECUTION = {
    "LangGraph checkpointing alone is often sufficient when": "the agent "
        "workflow lives ENTIRELY within LangGraph, and the organization "
        "doesn't need a SINGLE unified durability model spanning agent "
        "and non-agent tasks together.",
    "Layering Hatchet/Temporal underneath is worth it when": "orchestrating "
        "MULTIPLE different agent frameworks (or agent + non-agent tasks) "
        "in one durable workflow, or when standardizing on ONE durable-"
        "execution operational model organization-wide rather than a "
        "framework-specific persistence mechanism per team.",
}


if __name__ == "__main__":
    print(DURABLE_AGENT_WORKFLOW_EXAMPLE)

    print("Cost of losing progress on a crash at step 37 of 50:")
    result = estimate_cost_of_restart_from_scratch(
        completed_steps=37, total_steps=50, cost_per_llm_call=0.15,
    )
    for k, v in result.items():
        print(f"  {k}: {v}")

    print("\n=== When to layer durable execution under agent orchestration ===")
    for scenario, note in WHEN_TO_LAYER_DURABLE_EXECUTION.items():
        print(f"{scenario}:\n  {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A research-agent platform processing large document sets wraps its
per-document analysis in individually-durable Hatchet tasks — during a
routine deployment that restarted worker processes mid-run on a 200-
document analysis job, the workflow resumed from document #143 rather
than restarting from #1, saving the cost and latency of 142 already-
completed (and already-paid-for) LLM analysis calls — exactly the
concrete saving `estimate_cost_of_restart_from_scratch()` quantifies,
turned from a hypothetical into an actual measured deployment-day outcome.
"""
