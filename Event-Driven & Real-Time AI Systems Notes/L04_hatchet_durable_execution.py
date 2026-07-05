# ============================================================
# L04: Hatchet — Durable Workflow/Task Execution
# ============================================================
# WHAT: Hatchet's durable task-execution model — retries, timeouts,
#       fan-out, and workflow orchestration for background/async work —
#       compared against Temporal (Agentic AI & RAG Notes L24) and
#       Celery, the two most common alternatives.
# WHY: An event-driven system (L01-L03) needs somewhere for CONSUMERS to
#       actually run their reaction logic reliably — if a consumer's
#       processing of an event fails partway through, or the whole
#       process crashes, that work needs to be retried/resumed
#       correctly, not silently lost or duplicated. This is exactly the
#       durable-execution problem Hatchet (and Temporal, and Celery)
#       solve, each with different tradeoffs.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
DURABLE EXECUTION means a task/workflow's PROGRESS survives process
crashes, deployments, and infrastructure restarts — if a multi-step task
fails on step 3 of 5, a durable execution engine can RETRY just step 3
(not re-run steps 1-2 unnecessarily) after the underlying issue is
resolved, and if the WORKER process itself crashes mid-task, another
worker can pick up exactly where it left off rather than losing all
progress.

HATCHET is a modern, lighter-weight durable task-execution engine
(compared to Temporal's more heavyweight, deeply state-machine-oriented
model) providing: RETRIES (configurable per-task, with backoff),
TIMEOUTS (a task exceeding its time budget is treated as failed and
retried/escalated), and FAN-OUT (one triggering event spawning many
parallel child tasks — e.g. "process this batch of 1,000 customer
records" fanning out into 1,000 independent, individually-retriable
tasks rather than one big task that fails entirely if ANY single record
fails). Hatchet is commonly deployed alongside an event bus (NATS/Kafka)
specifically as the EXECUTION layer that turns "an event arrived" into
"reliably-executed background work," including work with real-time
latency requirements.

TEMPORAL (covered for AI agent orchestration specifically in this
repo's Agentic AI & RAG Notes L24) takes a more comprehensive approach:
full WORKFLOW-AS-CODE with deterministic replay (the workflow function
itself can be re-executed from its event history to reconstruct exact
state after a crash, a more powerful but more conceptually involved
model than Hatchet's task-centric approach), long-running workflows that
can durably wait for DAYS, and a steeper operational/conceptual learning
curve as a result of that additional power.

CELERY is the older, more established Python-ecosystem task queue —
simpler conceptually (a task queue backed by a broker like Redis/
RabbitMQ, workers pull and execute tasks) but with WEAKER built-in
durability guarantees out of the box (retries and idempotency are
largely the developer's own responsibility to implement correctly,
rather than a first-class engine guarantee) and no native support for
complex multi-step workflow orchestration (chaining/fanning out tasks
requires more manual wiring).

PRODUCTION USE CASE:
A real-time trigger-evaluation platform (L05) uses Hatchet as the
execution layer consuming events from a NATS JetStream subject —
each event triggers a Hatchet workflow that FANS OUT into parallel
tasks (evaluate this event against N active trigger definitions
simultaneously), each individually retriable if a specific trigger's
evaluation logic hits a transient error (e.g. a downstream API timeout)
— without one slow/failing trigger evaluation blocking or failing the
evaluation of all the OTHER triggers for that same event.

COMMON MISTAKES:
- Building custom retry/idempotency logic from scratch on top of a
  simple task queue (Celery) for a use case that genuinely needs strong
  durability guarantees, when a purpose-built durable-execution engine
  (Hatchet/Temporal) would provide those guarantees as a first-class
  feature rather than a hand-rolled, easy-to-get-subtly-wrong reimplementation.
- Choosing Temporal's full workflow-as-code model for a simpler use case
  where Hatchet's more task-centric approach would suffice with less
  conceptual overhead — Temporal's additional power (long-running
  durable waits spanning days, deterministic replay) is genuinely
  valuable for SOME use cases (L24's human-in-the-loop approval
  workflows) but is unneeded complexity for straightforward, short-lived
  background task execution.
- Not designing tasks to be IDEMPOTENT (safe to retry without side-
  effect duplication) even when using a durable-execution engine — the
  engine guarantees a task WILL be retried on failure, but idempotency
  of the task's OWN logic (e.g. "don't double-charge a customer if this
  payment task retries") remains the task author's responsibility.
"""

import textwrap


# ------------------------------------------------------------------
# 1. A basic Hatchet task with retries and timeout
# ------------------------------------------------------------------
HATCHET_TASK_EXAMPLE = textwrap.dedent("""\
    from hatchet_sdk import Hatchet

    hatchet = Hatchet()

    @hatchet.task(
        name="evaluate-trigger",
        retries=3,             # retry up to 3 times on failure
        timeout="30s",          # treat as failed if it exceeds 30 seconds
        backoff_factor=2.0,     # exponential backoff between retries
    )
    def evaluate_trigger(context):
        event = context.workflow_input()
        trigger_id = event["trigger_id"]
        result = evaluate_trigger_condition(trigger_id, event["payload"])
        if result.matched:
            queue_downstream_action(trigger_id, event)
        return {"matched": result.matched}

    # If evaluate_trigger_condition() throws (e.g. a transient downstream
    # timeout), Hatchet automatically retries this SPECIFIC task up to 3
    # times with exponential backoff — the caller/triggering event
    # doesn't need to implement retry logic itself.
""")

# ------------------------------------------------------------------
# 2. Fan-out — one event, many parallel independently-retriable tasks
# ------------------------------------------------------------------
HATCHET_FANOUT_EXAMPLE = textwrap.dedent("""\
    @hatchet.task(name="evaluate-event-against-all-triggers")
    def evaluate_event(context):
        event = context.workflow_input()
        active_trigger_ids = get_active_trigger_ids()

        # FAN-OUT: spawn one independent child task PER trigger — each
        # is retried/monitored SEPARATELY. If trigger #47's evaluation
        # logic hits a transient error, only #47 retries; triggers #1-46
        # and #48+ complete normally, unaffected.
        child_runs = [
            context.spawn_workflow("evaluate-trigger", {
                "trigger_id": trigger_id, "payload": event,
            })
            for trigger_id in active_trigger_ids
        ]

        results = context.wait_for_all(child_runs)
        return {"evaluated": len(results), "matched": sum(1 for r in results if r["matched"])}
""")

# ------------------------------------------------------------------
# 3. Hatchet consuming from an event bus (NATS, L02)
# ------------------------------------------------------------------
EVENT_BUS_INTEGRATION_EXAMPLE = textwrap.dedent("""\
    import asyncio
    import nats

    async def bridge_nats_to_hatchet():
        nc = await nats.connect("nats://localhost:4222")
        js = nc.jetstream()
        sub = await js.pull_subscribe("deposit_confirmed", durable="hatchet-bridge")

        while True:
            msgs = await sub.fetch(batch=10, timeout=5)
            for msg in msgs:
                # Each NATS event TRIGGERS a durable Hatchet workflow run
                # — NATS handles reliable EVENT DELIVERY (L02), Hatchet
                # handles reliable TASK EXECUTION of the reaction to that
                # event — two distinct durability guarantees, composed.
                hatchet.admin.run_workflow("evaluate-event", msg.data)
                await msg.ack()
""")

# ------------------------------------------------------------------
# 4. Hatchet vs Temporal vs Celery
# ------------------------------------------------------------------
DURABLE_EXECUTION_COMPARISON = {
    "Celery": "Simplest conceptually — a task queue over Redis/RabbitMQ. "
        "Retries/idempotency are largely the developer's own "
        "responsibility; no native complex-workflow orchestration.",
    "Hatchet": "Purpose-built durable execution with first-class "
        "retries/timeouts/fan-out as engine guarantees — a lighter-"
        "weight, more task-centric model than Temporal.",
    "Temporal": "Full workflow-as-code with deterministic replay — the "
        "most powerful model (durable waits spanning DAYS, complex "
        "human-in-the-loop patterns, see Agentic AI & RAG Notes L24), "
        "at a steeper conceptual/operational learning curve.",
}


if __name__ == "__main__":
    print(HATCHET_TASK_EXAMPLE)
    print(HATCHET_FANOUT_EXAMPLE)
    print(EVENT_BUS_INTEGRATION_EXAMPLE)
    print("=== Durable execution engine comparison ===")
    for engine, note in DURABLE_EXECUTION_COMPARISON.items():
        print(f"{engine}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A real-time trigger-evaluation platform bridges NATS JetStream events
into Hatchet workflows: each `deposit_confirmed` event fans out into
parallel per-trigger evaluation tasks, individually retried on
transient failures with exponential backoff — during an incident where a
downstream fraud-check API had intermittent 2-second latency spikes,
Hatchet's automatic per-task retry absorbed the transient failures
without any custom retry code, and the platform's end-to-end trigger
evaluation stayed within its sub-5-minute latency target throughout the
incident, with only the SPECIFIC affected tasks retrying rather than the
whole evaluation batch failing.
"""
