# ============================================================
# L24: Wiring Agents into Real Automation — n8n, Zapier, Make, Power
#      Automate, Temporal, Prefect, Kestra, Pipedream
# ============================================================
# WHAT: How agents connect to real-world AUTOMATION platforms — no-code/
#       low-code workflow builders (n8n, Zapier, Make, Microsoft Power
#       Automate, Pipedream) versus code-first workflow orchestrators
#       (Temporal, Prefect, Kestra) — and human-in-the-loop approval
#       patterns for agent-triggered actions.
# WHY: An agent that can only respond in a chat window has limited
#      real-world impact. Wiring an agent's decisions into actual
#      automation (send an email, update a CRM record, trigger a
#      deployment) is what turns "an agent that talks" into "an agent
#      that DOES things" — and that step introduces its own distinct
#      platform landscape and design considerations.
# LEVEL: Advanced (Phase 6 of 7 — final security/observability/automation lesson)
# ============================================================

"""
CONCEPT OVERVIEW:
NO-CODE/LOW-CODE AUTOMATION PLATFORMS (n8n, Zapier, Make, Microsoft
Power Automate, Pipedream) let you build multi-step automation workflows
visually, connecting hundreds of pre-built app integrations (Slack,
Gmail, Salesforce, etc.) with minimal custom code — increasingly, these
platforms add native AI/LLM STEPS directly into their visual workflow
builders, letting a business user wire "an LLM call happens here,
routing to different branches based on its output" without writing
orchestration code. N8N is open-source and self-hostable (appealing for
data-residency/control reasons); ZAPIER and MAKE are the most widely
adopted commercial SaaS options with the largest integration catalogs;
MICROSOFT POWER AUTOMATE is Microsoft's equivalent, deeply integrated
with the Microsoft 365/Azure ecosystem; PIPEDREAM leans more
developer-friendly, letting you drop into actual code within an
otherwise visual workflow when a pre-built integration doesn't cover
your exact need.

CODE-FIRST WORKFLOW ORCHESTRATORS (TEMPORAL, PREFECT, KESTRA) target a
different need: durable, reliable execution of LONG-RUNNING, complex
workflows with strong guarantees around retries, state persistence, and
failure recovery — genuinely different engineering concerns than a
no-code platform's visual simplicity. TEMPORAL specifically guarantees
WORKFLOW DURABILITY — a workflow's state survives process crashes,
deployments, even the underlying worker process being killed mid-
execution, and automatically resumes from exactly where it left off,
which matters enormously for a long-running agent task (e.g. a multi-
day approval process) that must not silently lose progress on an
infrastructure hiccup. PREFECT (which also appears in this repo's Data
Engineering Notes as a general orchestrator) and KESTRA offer similar
durable-workflow guarantees with different authoring models and
ecosystem positioning. (Apache Airflow, covered in depth in this
repo's Data Engineering Notes, is the closely related general-purpose
orchestrator most relevant when agent automation needs to interoperate
with existing DATA pipeline infrastructure specifically.)

HUMAN-IN-THE-LOOP APPROVAL is often the correct pattern for agent-
triggered automation with real consequences (sending an external email,
executing a financial transaction, deploying code) — directly connecting
to L13's LangGraph interrupt/checkpoint pattern: the agent proposes an
action, the automation workflow PAUSES for explicit human approval
(via a Slack message with approve/reject buttons, an email link, a
dashboard), and only executes the actual side-effecting action after
approval, with the workflow's durable state ensuring the pause can last
minutes or days without losing progress.

PRODUCTION USE CASE:
A sales-operations team wires an agent's lead-qualification decisions
into an n8n workflow: the agent analyzes an incoming lead and proposes a
qualification score and next action, n8n routes HIGH-CONFIDENCE
decisions directly into automatically updating the CRM and notifying the
sales rep via Slack, while LOW-CONFIDENCE or high-value decisions are
routed to a human-in-the-loop approval step (a Slack message with
approve/reject buttons) before any CRM update happens — a tiered
automation design where automation handles the routine cases and humans
review the ambiguous/high-stakes ones.

COMMON MISTAKES:
- Choosing a no-code platform for a workflow that genuinely needs
  Temporal-style durability guarantees (a multi-day process that must
  survive infrastructure failures without losing state) — most no-code
  platforms aren't built for that durability model, and discovering this
  gap after a production incident loses in-progress workflow state is a
  costly way to learn it.
- Automating agent-triggered actions with REAL consequences (financial,
  irreversible, externally visible) with NO human-in-the-loop checkpoint
  at all — this is the automation-layer analogue of L22's security
  concerns: an agent making a mistake (or being successfully
  manipulated via prompt injection) with unchecked automation access has
  a much larger and more consequential blast radius than one requiring
  human approval for consequential actions.
- Using a heavyweight code-first orchestrator (Temporal) for a simple,
  low-stakes automation a no-code platform would handle in minutes —
  matching tool weight to actual need applies here just as much as
  anywhere else in this domain.
"""

import textwrap


# ------------------------------------------------------------------
# 1. No-code/low-code platforms with native AI steps
# ------------------------------------------------------------------
N8N_WORKFLOW_SKETCH = textwrap.dedent("""\
    n8n workflow (visual, JSON-representable):

      [Webhook: new lead] --> [AI Agent node: qualify lead]
                                    |
                          (branch on agent's confidence score)
                              /                    \\
                 [confidence > 0.8]          [confidence <= 0.8]
                        |                            |
              [Update CRM directly]      [Slack: approve/reject buttons]
              [Notify sales rep]                     |
                                          (wait for human response)
                                                      |
                                          [If approved: Update CRM]

    # n8n's native "AI Agent" node lets a non-engineer wire an LLM call
    # with tool access directly into this visual workflow — no custom
    # orchestration code needed for the routing logic itself.
""")

ZAPIER_AI_STEP_NOTE = (
    "Zapier's 'AI by Zapier' steps let a Zap (their automation unit) "
    "include an LLM call as one step in an otherwise no-code workflow — "
    "e.g. 'when a new support ticket arrives, use AI to classify its "
    "urgency, then branch the rest of the Zap based on that "
    "classification' — the same LLM-in-the-loop pattern as n8n's AI "
    "Agent node, within Zapier's much larger pre-built integration catalog."
)

# ------------------------------------------------------------------
# 2. Code-first durable orchestration — Temporal
# ------------------------------------------------------------------
TEMPORAL_WORKFLOW_EXAMPLE = textwrap.dedent("""\
    from temporalio import workflow, activity
    from datetime import timedelta

    @activity.defn
    async def run_agent_analysis(lead_data: dict) -> dict:
        return await agent.analyze(lead_data)   # your agent from Phase 3-5

    @activity.defn
    async def wait_for_human_approval(proposal: dict) -> bool:
        # Sends a Slack message with approve/reject buttons and BLOCKS
        # until a response — Temporal's durability guarantee means this
        # can wait for HOURS or DAYS, surviving worker restarts/
        # deployments, without losing the workflow's accumulated state.
        return await slack_approval_flow(proposal)

    @workflow.defn
    class LeadQualificationWorkflow:
        @workflow.run
        async def run(self, lead_data: dict) -> str:
            analysis = await workflow.execute_activity(
                run_agent_analysis, lead_data, start_to_close_timeout=timedelta(minutes=5),
            )
            if analysis["confidence"] > 0.8:
                return await workflow.execute_activity(update_crm, analysis)
            approved = await workflow.execute_activity(
                wait_for_human_approval, analysis,
                start_to_close_timeout=timedelta(days=3),   # a LONG wait,
            )                                                 # durably handled
            if approved:
                return await workflow.execute_activity(update_crm, analysis)
            return "Lead rejected by human reviewer"
""")

# ------------------------------------------------------------------
# 3. Human-in-the-loop approval — the recurring safety pattern
# ------------------------------------------------------------------
HUMAN_IN_LOOP_PRINCIPLE = textwrap.dedent("""\
    The same principle from L13 (LangGraph interrupts) and L22 (security
    defense in depth) applies at the AUTOMATION layer: any agent-
    triggered action with REAL, hard-to-reverse consequences should have
    an explicit human checkpoint, UNLESS the action's blast radius is
    small enough that automatic execution's speed benefit outweighs the
    risk of an occasional wrong automated decision.

    A practical tiering approach:
      - LOW-STAKES, REVERSIBLE (e.g. tagging a support ticket, sending an
        internal Slack notification): fully automate.
      - MODERATE-STAKES (e.g. updating a CRM record, drafting but not
        sending an email): automate with logging/audit trail, spot-check
        periodically.
      - HIGH-STAKES, HARD-TO-REVERSE (e.g. sending an external
        communication, processing a payment, deploying code): require
        explicit human approval before execution, every time.
""")

# ------------------------------------------------------------------
# 4. Platform comparison
# ------------------------------------------------------------------
AUTOMATION_PLATFORM_COMPARISON = {
    "n8n": "Open-source, self-hostable, native AI Agent nodes — good "
        "control/data-residency, moderate integration catalog.",
    "Zapier": "Largest commercial integration catalog, AI steps "
        "available, fully managed SaaS.",
    "Make (formerly Integromat)": "Similar positioning to Zapier, often "
        "preferred for more complex branching/visual workflow logic.",
    "Microsoft Power Automate": "Deep Microsoft 365/Azure integration — "
        "the natural choice for Microsoft-ecosystem organizations.",
    "Pipedream": "More developer-friendly — drop into real code within "
        "an otherwise visual workflow when needed.",
    "Temporal": "Code-first, DURABLE workflow execution — survives "
        "crashes/restarts, ideal for long-running, high-reliability "
        "agent-triggered processes.",
    "Prefect": "Code-first, Python-native orchestration (also covered "
        "in Data Engineering Notes) — durable workflows with a Pythonic "
        "authoring experience.",
    "Kestra": "Code-first (YAML-based) orchestration with a strong "
        "focus on declarative workflow definitions and built-in scheduling.",
}


if __name__ == "__main__":
    print(N8N_WORKFLOW_SKETCH)
    print(ZAPIER_AI_STEP_NOTE)
    print()
    print(TEMPORAL_WORKFLOW_EXAMPLE)
    print(HUMAN_IN_LOOP_PRINCIPLE)

    print("=== Automation platform comparison ===")
    for platform, note in AUTOMATION_PLATFORM_COMPARISON.items():
        print(f"{platform}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
An e-commerce company automates customer refund requests end to end
using Temporal: an agent analyzes each request and drafts a decision;
refunds under $50 (low-stakes, easily reversible) execute automatically
via a payment API activity; refunds over $50 durably wait (potentially
for days, surviving any infrastructure restarts) for a human finance
reviewer's approval via a Slack-integrated approval step before the
payment activity ever executes — the SAME workflow definition handling
both the fully-automated and human-gated paths, with Temporal's
durability guarantee ensuring no in-progress high-value refund decision
is ever silently lost to a service restart.
"""
