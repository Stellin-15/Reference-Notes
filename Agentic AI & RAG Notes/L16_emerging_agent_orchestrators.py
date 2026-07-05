# ============================================================
# L16: Emerging Agent Orchestrators — LlamaIndex Workflows, AWS Strands,
#      CAMEL, and Agno
# ============================================================
# WHAT: A survey of four additional agent orchestration approaches, each
#       adding something distinct beyond LangGraph/CrewAI/AutoGen —
#       LlamaIndex Workflows (event-driven steps built on the retrieval
#       framework from L06), AWS Strands Agents (AWS's model-driven,
#       code-first agent SDK), CAMEL (agents that generate and refine
#       their OWN role/task definitions), and Agno (a lightweight,
#       performance-focused agent framework).
# WHY: The agent-framework landscape moves fast, and no single framework
#      from L13-L15 fits every need — knowing what these four add lets
#      you recognize when a specific problem shape calls for one of
#      them rather than defaulting to whichever framework you learned first.
# LEVEL: Advanced (Phase 3 of 7)
# ============================================================

"""
CONCEPT OVERVIEW:
LLAMAINDEX WORKFLOWS extends the RAG-focused LlamaIndex framework (L06)
into general agent orchestration — an EVENT-DRIVEN model where STEPS
(decorated Python functions) consume specific event TYPES and emit new
events, and the workflow engine routes events to whichever step declares
it can handle them. This is architecturally distinct from LangGraph's
explicit node/edge graph: instead of declaring "node A connects to node
B," you declare "step A emits event type X" and "step B consumes event
type X" — the routing is inferred from event types rather than explicit
edges, which can scale to complex workflows with less boilerplate edge-
wiring, at the cost of the routing logic being less immediately visible
than an explicit graph diagram.

AWS STRANDS AGENTS is AWS's code-first agent SDK, emphasizing a
MODEL-DRIVEN approach — you give the agent a model, a set of tools, and
a prompt, and lean heavily on the underlying LLM's own reasoning to
drive the agent loop (similar in spirit to L12's ReAct pattern) rather
than hand-coding explicit control flow — positioned as a lighter-weight
alternative to heavier graph/workflow frameworks specifically for teams
already in the AWS ecosystem wanting tight Bedrock integration (see
L18's AWS Bedrock Agents coverage for the closely-related, more
fully-managed AWS offering).

CAMEL (Communicative Agents for "Mind" Exploration of Large Language
Model Society) explores a genuinely different idea: instead of a human
designing each agent's role and task upfront (as in CrewAI, L14), CAMEL
uses a ROLE-PLAYING framework where agents can be given a broad task and
made to COLLABORATIVELY REFINE their own role definitions and sub-tasks
through conversation — originally a research framework studying
emergent multi-agent behavior, now also used as a practical library for
scenarios where you want agents to decompose a broad, underspecified
task more autonomously than a rigidly pre-defined CrewAI crew would.

AGNO (formerly Phidata) is a LIGHTWEIGHT, performance-focused agent
framework emphasizing FAST agent instantiation and a smaller runtime
footprint than heavier frameworks — appealing when you need to spin up
many agents cheaply (e.g. one agent per user session in a high-
concurrency application) where a framework's own overhead per agent
instance becomes a real, measurable cost at scale.

PRODUCTION USE CASE:
A high-concurrency customer-facing application instantiating a fresh
agent per user session evaluates Agno specifically because its
lightweight instantiation overhead matters at the scale of thousands of
concurrent sessions, where a heavier framework's per-agent memory/startup
cost would compound into a real infrastructure cost difference.

COMMON MISTAKES:
- Adopting CAMEL's autonomous role-refinement approach for a task where
  the roles and workflow are actually well-understood upfront — a
  CrewAI-style pre-defined crew is simpler, more predictable, and more
  debuggable when you already know exactly what roles are needed.
- Choosing a framework based on it being "the newest" rather than
  matching its actual differentiator to your problem — LlamaIndex
  Workflows' event-driven model is genuinely valuable for complex,
  branching workflows with many possible paths, but is unnecessary
  overhead for a simple, linear task.
- Not evaluating actual per-agent overhead/instantiation cost for
  high-concurrency use cases until a production scaling problem forces
  a late framework migration — if you know you'll run many concurrent
  agent instances, this is worth benchmarking BEFORE committing to a
  heavier framework.
"""

import textwrap


# ------------------------------------------------------------------
# 1. LlamaIndex Workflows — event-driven steps
# ------------------------------------------------------------------
LLAMAINDEX_WORKFLOWS_EXAMPLE = textwrap.dedent("""\
    from llama_index.core.workflow import Workflow, step, Event, StartEvent, StopEvent

    class RetrievalCompleteEvent(Event):
        context: str

    class ResearchWorkflow(Workflow):
        @step
        async def retrieve(self, ev: StartEvent) -> RetrievalCompleteEvent:
            context = await self.retriever.aretrieve(ev.query)
            return RetrievalCompleteEvent(context=context)

        @step
        async def generate(self, ev: RetrievalCompleteEvent) -> StopEvent:
            # This step is invoked AUTOMATICALLY because it declares it
            # consumes RetrievalCompleteEvent — there's no explicit
            # "connect retrieve to generate" edge to write, unlike
            # LangGraph's add_edge() calls; the routing is inferred from
            # the declared event TYPES each step consumes/produces.
            answer = await self.llm.acomplete(f"Context: {ev.context}\\nAnswer:")
            return StopEvent(result=answer)

    workflow = ResearchWorkflow()
    result = await workflow.run(query="How do I request a refund?")
""")

# ------------------------------------------------------------------
# 2. AWS Strands Agents — model-driven, code-first
# ------------------------------------------------------------------
STRANDS_EXAMPLE = textwrap.dedent("""\
    from strands import Agent
    from strands.tools import tool

    @tool
    def get_weather(city: str) -> str:
        return lookup_weather(city)

    agent = Agent(
        model="anthropic.claude-opus-4-5",   # via Amazon Bedrock
        tools=[get_weather],
        system_prompt="You are a helpful assistant.",
    )

    # Leans on the MODEL's own reasoning to drive the loop (L12's ReAct
    # pattern) rather than explicit graph/workflow code — a lighter-
    # weight authoring experience for straightforward tool-using agents.
    response = agent("What's the weather in Tokyo?")
""")

# ------------------------------------------------------------------
# 3. CAMEL — collaborative role/task refinement
# ------------------------------------------------------------------
CAMEL_CONCEPT_NOTE = textwrap.dedent("""\
    from camel.societies import RolePlaying

    # Instead of YOU pre-defining exact roles (CrewAI's approach), CAMEL
    # can generate/refine role definitions from a broad task description
    # — the "AI User" and "AI Assistant" roles negotiate and decompose
    # the task collaboratively through their own conversation.
    role_play_session = RolePlaying(
        assistant_role_name="Python Programmer",
        user_role_name="Stock Trader",
        task_prompt="Develop a trading bot for the stock market",
    )
    # The two agents converse, with the "user" agent issuing instructions
    # and the "assistant" agent responding/executing — CAMEL's research
    # origin was studying HOW such role-playing conversations naturally
    # decompose a broad task, which is also directly useful as a
    # practical technique for underspecified tasks.
""")

# ------------------------------------------------------------------
# 4. Agno — lightweight, performance-focused
# ------------------------------------------------------------------
AGNO_EXAMPLE = textwrap.dedent("""\
    from agno.agent import Agent
    from agno.models.openai import OpenAIChat

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[get_weather],
        markdown=True,
    )
    agent.print_response("What's the weather in Tokyo?")

    # Agno's differentiator isn't a new orchestration PARADIGM (it's
    # broadly similar in shape to Strands/simple LangChain agents) —
    # it's ENGINEERING FOCUS on fast instantiation and low per-agent
    # overhead, which matters specifically at high concurrency (many
    # agent instances spun up per request/session) where framework
    # overhead becomes a measurable infrastructure cost.
""")

# ------------------------------------------------------------------
# 5. What each framework adds — quick reference
# ------------------------------------------------------------------
DIFFERENTIATOR_SUMMARY = {
    "LlamaIndex Workflows": "Event-driven step routing — scales well "
        "for complex, many-branch workflows without explicit edge-wiring.",
    "AWS Strands Agents": "Lightweight, model-driven, code-first — tight "
        "Bedrock integration for AWS-native teams.",
    "CAMEL": "Agents collaboratively refine their OWN roles/sub-tasks — "
        "suited to broad, underspecified tasks rather than pre-defined workflows.",
    "Agno": "Engineering focus on fast instantiation/low overhead — "
        "matters at high-concurrency, many-agents-per-request scale.",
}


if __name__ == "__main__":
    print(LLAMAINDEX_WORKFLOWS_EXAMPLE)
    print(STRANDS_EXAMPLE)
    print(CAMEL_CONCEPT_NOTE)
    print(AGNO_EXAMPLE)
    print("=== Differentiator summary ===")
    for framework, note in DIFFERENTIATOR_SUMMARY.items():
        print(f"{framework}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A research lab prototyping novel multi-agent collaboration patterns
uses CAMEL specifically to study how agents decompose an underspecified
task ("design an experiment to test hypothesis X") without pre-defined
roles — while a SEPARATE production team building a high-concurrency,
per-user-session support bot evaluates Agno specifically for its low
per-agent instantiation overhead at their expected scale of tens of
thousands of concurrent sessions, a concern that never arises in the
research lab's low-concurrency experimentation context.
"""
