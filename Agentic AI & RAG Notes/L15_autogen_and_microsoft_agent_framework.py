# ============================================================
# L15: Microsoft AutoGen and Microsoft Agent Framework
# ============================================================
# WHAT: AutoGen's CONVERSATION-CENTRIC multi-agent model — agents that
#       talk to each other in a group chat, including code-execution
#       agents — and Microsoft Agent Framework, Microsoft's newer,
#       more enterprise/production-oriented agent building framework.
# WHY: CrewAI (L14) models multi-agent collaboration as a TEAM with
#      roles and tasks. AutoGen models it as a CONVERSATION between
#      agents — a third distinct paradigm (alongside LangGraph's graph
#      and CrewAI's team) for structuring multi-agent systems, each
#      suited to different problem shapes.
# LEVEL: Advanced (Phase 3 of 7)
# ============================================================

"""
CONCEPT OVERVIEW:
AutoGen's core abstraction is the CONVERSABLE AGENT — an agent that
participates in a conversation by sending and receiving messages, much
like a chat participant. Multiple conversable agents can be placed in a
GROUP CHAT, where a MANAGER (itself often LLM-driven) decides which
agent should "speak" next based on the conversation so far — this
produces emergent, conversation-driven collaboration rather than a
pre-defined task sequence (CrewAI) or an explicitly-designed graph
(LangGraph).

A distinctive AutoGen capability is the CODE-EXECUTOR AGENT — an agent
that can actually WRITE and EXECUTE code (typically in a sandboxed
Docker container) as part of the conversation, with the execution
RESULT fed back into the conversation for other agents (or the same
agent) to react to. This is a particularly natural fit for tasks
genuinely requiring computation/verification (e.g. "write a Python
script to analyze this dataset, run it, and interpret the results" —
the code-executor agent handles the write-and-run step, feeding real
output back to a reasoning agent).

A common, illustrative AutoGen pattern is exactly TWO agents: an
ASSISTANT agent (proposes solutions, writes code) and a USER PROXY agent
(represents the human user, can execute code on the assistant's behalf
and relay results back, and can optionally require actual human input at
configured points) — conversing back and forth until the task is
resolved or a human intervenes.

MICROSOFT AGENT FRAMEWORK is Microsoft's newer, more explicitly
enterprise/production-oriented framework (distinct from AutoGen, though
from the same organization and sharing some underlying concepts) — with
tighter integration into the Azure ecosystem (Azure AI Foundry, covered
alongside other vendor Agent SDKs in L18) and a stronger focus on
production concerns (observability, enterprise auth) from the outset,
positioned as the more production-ready successor path for teams
already invested in the Microsoft/Azure ecosystem, while AutoGen remains
widely used for research and more experimental multi-agent patterns.

PRODUCTION USE CASE:
A data analysis assistant uses AutoGen's Assistant + Code-Executor
pattern: a user asks "what's the correlation between marketing spend and
signups in this dataset," the Assistant agent writes a pandas analysis
script, the Code-Executor agent runs it in a sandboxed container, the
actual numerical result is fed back to the Assistant, which then
interprets it in natural language for the user — genuine computation
happening as part of the conversation, not the LLM guessing at a numeric
answer from training data alone.

COMMON MISTAKES:
- Running a code-executor agent WITHOUT proper sandboxing (e.g. direct
  execution on the host machine instead of an isolated Docker container)
  — an LLM-generated script executing with host-level permissions is a
  genuine security risk, directly connecting to the AI security concerns
  covered in depth in L22.
- Using an unconstrained group chat (letting the manager freely decide
  speaking order with no limits) for a task that actually has a fairly
  predictable structure — this can produce meandering, expensive
  conversations where a CrewAI sequential process or a LangGraph
  explicit flow would reach the same result more predictably and cheaply.
- Choosing AutoGen for a new production build without evaluating whether
  Microsoft Agent Framework's more enterprise-oriented tooling (auth,
  observability integration) better fits actual production requirements
  — the two frameworks solve overlapping problems with different
  maturity/positioning for production use.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Conversable agents and a two-agent conversation
# ------------------------------------------------------------------
AUTOGEN_TWO_AGENT_EXAMPLE = textwrap.dedent("""\
    import autogen

    assistant = autogen.AssistantAgent(
        name="assistant",
        llm_config={"model": "gpt-4o"},
        system_message="You solve tasks by writing Python code when needed.",
    )

    user_proxy = autogen.UserProxyAgent(
        name="user_proxy",
        human_input_mode="NEVER",   # fully automated; "ALWAYS" or "TERMINATE"
                                      # would require actual human input at
                                      # configured points — a human-in-the-loop
                                      # option directly analogous to L13's
                                      # LangGraph interrupts.
        code_execution_config={"work_dir": "coding", "use_docker": True},  # SANDBOXED
    )

    # Kicks off a CONVERSATION — the two agents exchange messages back
    # and forth until the task resolves, not a fixed pre-defined sequence.
    user_proxy.initiate_chat(
        assistant,
        message="What's the correlation between marketing_spend and signups in sales.csv?",
    )
    # Conversation flow: assistant writes a pandas script -> user_proxy
    # EXECUTES it (in the sandboxed Docker container) -> the actual
    # numeric result is sent back to assistant as the next message ->
    # assistant interprets the real result in natural language.
""")

# ------------------------------------------------------------------
# 2. Group chat — a manager deciding who speaks next
# ------------------------------------------------------------------
AUTOGEN_GROUP_CHAT_EXAMPLE = textwrap.dedent("""\
    researcher = autogen.AssistantAgent(name="researcher", llm_config=config)
    coder = autogen.AssistantAgent(name="coder", llm_config=config)
    reviewer = autogen.AssistantAgent(name="reviewer", llm_config=config)

    group_chat = autogen.GroupChat(
        agents=[researcher, coder, reviewer, user_proxy],
        messages=[],
        max_round=15,   # a hard cap, exactly analogous to L12's max_steps
                          # and L13's recursion_limit — required against
                          # an unbounded, potentially never-converging
                          # conversation.
    )
    manager = autogen.GroupChatManager(groupchat=group_chat, llm_config=config)

    # The MANAGER (itself LLM-driven) decides, after each message, which
    # agent speaks next based on the conversation's content — an
    # EMERGENT routing decision, unlike CrewAI's declared sequential/
    # hierarchical process or LangGraph's explicit conditional edges.
    user_proxy.initiate_chat(manager, message="Research and implement a solution for X.")
""")

# ------------------------------------------------------------------
# 3. Microsoft Agent Framework — the enterprise-oriented successor path
# ------------------------------------------------------------------
MAF_POSITIONING_NOTE = textwrap.dedent("""\
    Microsoft Agent Framework shares conceptual DNA with AutoGen (both
    from Microsoft) but is positioned more explicitly for PRODUCTION/
    ENTERPRISE use: tighter native integration with Azure AI Foundry
    (Microsoft's vendor agent-hosting platform, covered alongside other
    provider Agent SDKs in L18), built-in enterprise auth patterns, and
    a stronger observability/tracing story out of the box — where
    AutoGen has historically leaned toward research and rapid
    experimentation with multi-agent conversation patterns.

    A team choosing between them today is choosing between AutoGen's
    more flexible, conversation-first experimentation model and Microsoft
    Agent Framework's more opinionated, production-hardened path — both
    remain actively relevant depending on whether you're prototyping a
    novel multi-agent pattern or building a system for enterprise deployment.
""")

# ------------------------------------------------------------------
# 4. Three multi-agent paradigms, side by side
# ------------------------------------------------------------------
PARADIGM_SUMMARY = {
    "LangGraph (L13)": "Explicit GRAPH — you design nodes/edges/routing yourself.",
    "CrewAI (L14)": "Declarative TEAM — roles/goals/tasks, process model handles routing.",
    "AutoGen": "Emergent CONVERSATION — agents converse; a manager decides "
        "who speaks next based on content.",
}


if __name__ == "__main__":
    print(AUTOGEN_TWO_AGENT_EXAMPLE)
    print(AUTOGEN_GROUP_CHAT_EXAMPLE)
    print(MAF_POSITIONING_NOTE)
    print("=== Three multi-agent paradigms ===")
    for framework, note in PARADIGM_SUMMARY.items():
        print(f"{framework}: {note}")

"""
PRODUCTION CONTEXT EXAMPLE:
A quantitative research team uses AutoGen's Assistant + sandboxed Code-
Executor pattern for exploratory data analysis — an analyst describes a
hypothesis in natural language, the Assistant writes and the Code-
Executor runs actual pandas/statsmodels code against real data in an
isolated container, and the conversation continues iteratively as the
analyst refines the question based on real results — while the SAME
organization's production customer-facing support agent, once it moved
from prototype to a compliance-audited deployment, was rebuilt on
Microsoft Agent Framework specifically for its tighter Azure AD auth
integration and built-in tracing that the audit requirements demanded.
"""
