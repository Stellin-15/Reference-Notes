# ============================================================
# L14: CrewAI — Role-Based Multi-Agent Orchestration
# ============================================================
# WHAT: CrewAI's Crew/Agent/Task abstraction — modeling a multi-agent
#       system as a TEAM of role-playing agents (each with a defined
#       role, goal, and backstory) collaborating on a set of tasks, with
#       either sequential or hierarchical execution processes.
# WHY: LangGraph (L13) gives you a general-purpose GRAPH for arbitrary
#      control flow. CrewAI takes a more OPINIONATED, higher-level
#      approach specifically for MULTI-AGENT collaboration modeled after
#      how a human team divides work — a different, often faster-to-
#      author abstraction for the specific "multiple specialized agents
#      working together" pattern.
# LEVEL: Advanced (Phase 3 of 7)
# ============================================================

"""
CONCEPT OVERVIEW:
An AGENT in CrewAI is defined by a ROLE ("Senior Research Analyst"), a
GOAL (what it's trying to accomplish), and a BACKSTORY (context that
shapes its behavior/tone in the underlying prompt) — this ROLE-PLAYING
framing is a deliberate prompting strategy: giving an LLM a specific
persona and goal tends to produce more focused, consistent behavior for
that agent's specific responsibility than a generic, unscoped prompt.

A TASK is a specific unit of work assigned to an agent, with a
description and an EXPECTED OUTPUT format. Tasks can depend on the
OUTPUT of previous tasks (a "context" parameter referencing prior tasks'
results), letting one agent's output feed into the next agent's work.

A CREW is the top-level orchestrator — a collection of agents and tasks,
run via a PROCESS: SEQUENTIAL (tasks execute one after another, in
order, each potentially using prior tasks' outputs as context) or
HIERARCHICAL (a MANAGER agent — either a specified agent or an
automatically-created one — dynamically decides which agent handles
which task and in what order, more closely modeling a real team lead
delegating work rather than a fixed, pre-determined task sequence).

This is a MEANINGFULLY DIFFERENT abstraction from LangGraph's explicit
state graph: instead of you designing nodes/edges/conditional routing
yourself, you describe WHO is on the team and WHAT needs to get done,
and CrewAI's process model handles the orchestration mechanics. This
trades some of LangGraph's fine-grained control for a faster, more
declarative authoring experience specifically suited to the "team of
specialized roles collaborating" pattern.

PRODUCTION USE CASE:
A content-creation pipeline defines three CrewAI agents — a "Research
Analyst" (gathers and summarizes source material), a "Content Writer"
(drafts an article from the research), and an "Editor" (reviews and
refines the draft) — run as a SEQUENTIAL process where each agent's
output becomes the next agent's task context, closely modeling how a
real editorial team's workflow actually operates.

COMMON MISTAKES:
- Using CrewAI's hierarchical process when a simple, fixed sequential
  order is all the task actually requires — hierarchical orchestration
  adds a manager agent's own LLM calls and decision-making overhead;
  reach for it specifically when task ROUTING genuinely needs to be
  dynamic, not by default.
- Writing vague or overlapping agent roles/goals — if two agents' roles
  aren't clearly differentiated, the underlying LLM has no strong signal
  for how to behave differently between them, undermining the entire
  point of the role-based framing.
- Not providing clear "expected_output" specifications on tasks — a
  vague task definition produces vague, hard-to-use outputs that the
  NEXT agent in the sequence then has to work with, compounding
  ambiguity through the pipeline.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Defining agents — role, goal, backstory
# ------------------------------------------------------------------
CREWAI_AGENTS_EXAMPLE = textwrap.dedent("""\
    from crewai import Agent, Task, Crew, Process

    researcher = Agent(
        role="Senior Research Analyst",
        goal="Uncover and summarize the latest developments in {topic}",
        backstory=(
            "You work at a leading research firm, known for finding "
            "the most relevant and credible sources quickly and "
            "distilling them into clear, actionable summaries."
        ),
        tools=[web_search_tool],   # tool use, exactly as in L12/L21
        verbose=True,
    )

    writer = Agent(
        role="Content Writer",
        goal="Write an engaging, accurate article based on research findings",
        backstory=(
            "You are a skilled technical writer who transforms dense "
            "research into clear, engaging prose for a general audience."
        ),
    )
""")

# ------------------------------------------------------------------
# 2. Defining tasks — with dependencies via context
# ------------------------------------------------------------------
CREWAI_TASKS_EXAMPLE = textwrap.dedent("""\
    research_task = Task(
        description="Research the latest developments in {topic} and summarize key findings.",
        expected_output="A bullet-point summary of the 5 most important recent developments.",
        agent=researcher,
    )

    writing_task = Task(
        description="Write a 500-word article based on the research findings.",
        expected_output="A polished, engaging 500-word article.",
        agent=writer,
        context=[research_task],   # writer's task receives research_task's
                                     # OUTPUT as part of its own context —
                                     # this is how one agent's work feeds
                                     # the next in a CrewAI pipeline.
    )
""")

# ------------------------------------------------------------------
# 3. Sequential vs hierarchical process
# ------------------------------------------------------------------
SEQUENTIAL_CREW_EXAMPLE = textwrap.dedent("""\
    crew = Crew(
        agents=[researcher, writer],
        tasks=[research_task, writing_task],
        process=Process.sequential,   # fixed order: research_task, then
                                        # writing_task, exactly as listed
    )
    result = crew.kickoff(inputs={"topic": "quantum computing breakthroughs"})
""")

HIERARCHICAL_CREW_EXAMPLE = textwrap.dedent("""\
    crew = Crew(
        agents=[researcher, writer, editor],
        tasks=[research_task, writing_task, editing_task],
        process=Process.hierarchical,   # a MANAGER agent dynamically
        manager_llm=manager_model,       # decides which agent handles
    )                                     # which task and in what order,
    result = crew.kickoff(inputs={"topic": "quantum computing breakthroughs"})
    # Better suited when task ROUTING genuinely can't be fixed in
    # advance — e.g. the manager might route back to the researcher for
    # additional information if the editor flags a factual gap, a
    # dynamic decision a fixed sequential process cannot express.
""")

# ------------------------------------------------------------------
# 4. CrewAI vs LangGraph — different abstractions for different needs
# ------------------------------------------------------------------
COMPARISON = {
    "CrewAI": "Declarative, role-based — describe WHO is on the team and "
        "WHAT they need to do; the process model (sequential/hierarchical) "
        "handles orchestration. Faster to author for team-of-specialists "
        "patterns; less fine-grained control over exact execution flow.",
    "LangGraph": "Explicit, graph-based — you design the exact "
        "nodes/edges/conditional routing yourself. More control (arbitrary "
        "cycles, precise state management, human-in-the-loop interrupts "
        "at any point), more code to author for the same pattern.",
}


if __name__ == "__main__":
    print(CREWAI_AGENTS_EXAMPLE)
    print(CREWAI_TASKS_EXAMPLE)
    print(SEQUENTIAL_CREW_EXAMPLE)
    print(HIERARCHICAL_CREW_EXAMPLE)
    print("=== CrewAI vs LangGraph ===")
    for framework, note in COMPARISON.items():
        print(f"{framework}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A market-research firm's automated report pipeline uses a sequential
CrewAI process with four role-defined agents (Data Gatherer, Analyst,
Writer, Fact-Checker) — the fixed sequence matches their actual editorial
workflow exactly, and CrewAI's role/backstory framing produces
noticeably more consistent, on-tone output per agent than an earlier
prototype using generic, unscoped prompts for the same four
responsibilities within a single large prompt.
"""
