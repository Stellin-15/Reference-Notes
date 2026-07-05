# ============================================================
# L12: Agent Fundamentals — The Loop, Tools, Memory, Planning, ReAct
# ============================================================
# WHAT: What actually makes something an "agent" rather than a static
#       LLM call — the agent LOOP (observe, think, act, repeat), tool
#       use, memory, and the ReAct (Reasoning + Acting) pattern that
#       underlies nearly every agent framework covered in this phase.
# WHY: L01-L11 covered RAG — a single retrieve-then-generate pass. An
#      AGENT is fundamentally different: it can take MULTIPLE steps,
#      decide WHICH actions to take based on intermediate results, and
#      use TOOLS to affect the world or gather more information —
#      understanding this loop is the prerequisite for every framework
#      in the rest of this phase (LangGraph, CrewAI, AutoGen, etc.),
#      which are all different implementations/extensions of it.
# LEVEL: Foundation (Phase 3 of 7 — Agentic AI Orchestration Frameworks)
# ============================================================

"""
CONCEPT OVERVIEW:
A plain LLM call is a SINGLE forward pass: input in, output out, done.
An AGENT wraps the LLM in a LOOP: the LLM's output can include a decision
to USE A TOOL (call a function, search the web, query a database), the
tool's RESULT is fed back into the LLM as new context, and the LLM
decides again what to do next — REPEATING until it decides the task is
complete and produces a final answer. This is what lets an agent handle
multi-step tasks a single RAG-style call cannot ("find the current
weather in Tokyo, then convert the temperature to Fahrenheit, then tell
me if I need a coat" requires two tool calls and reasoning between them).

The REACT PATTERN (Reasoning + Acting, from the paper of the same name)
is the dominant prompting structure underlying this loop: at each step,
the model is prompted to produce a THOUGHT (reasoning about what to do
next, in natural language), an ACTION (which tool to call and with what
arguments), and then receives an OBSERVATION (the tool's result) —
looping Thought -> Action -> Observation until the model produces a
Final Answer instead of another action. Making the reasoning EXPLICIT
(the "Thought" step) measurably improves an agent's ability to handle
complex, multi-step tasks compared to jumping straight to actions
without articulated reasoning.

TOOLS are functions the agent can choose to call — each tool needs a
clear name, description, and parameter schema so the LLM can decide
WHEN and HOW to use it correctly (covered in full depth in L21). MEMORY
(covered in full depth in L20) lets an agent retain context across
multiple turns of a conversation or across the steps of a single task —
without it, an agent would "forget" what it already tried a few steps ago.

An agent is NOT always the right tool: a STATIC PIPELINE (a fixed
sequence of steps, like L04's RAG pipeline) is more predictable, cheaper,
faster, and easier to debug than an agent for tasks with a KNOWN,
fixed structure. Agents earn their added complexity/cost/unpredictability
specifically when the SEQUENCE of steps needed genuinely can't be
determined in advance — it depends on what earlier steps discover.

PRODUCTION USE CASE:
A research assistant agent given "find the three most cited papers on
topic X published in the last year and summarize their key findings"
cannot be solved by a single RAG retrieval — it needs to search, decide
which results are actually the most-cited (possibly requiring another
search for citation counts), retrieve and read each paper, and
synthesize — a genuinely variable number of steps determined by what it
finds along the way, exactly the class of problem an agent loop handles
that a fixed pipeline cannot.

COMMON MISTAKES:
- Reaching for an agent when a static, fixed-sequence pipeline would
  solve the task just as well — agents are slower (multiple LLM calls
  instead of one), more expensive, and less predictable/debuggable;
  "could an if/else pipeline solve this" is worth asking before
  reaching for agent complexity.
- Not giving the model an explicit "Thought" step before each action —
  skipping straight to actions without articulated reasoning measurably
  degrades performance on non-trivial multi-step tasks, per the ReAct
  paper's own ablations.
- Building an agent loop with NO maximum iteration limit — a
  misbehaving or confused agent can loop indefinitely (repeatedly
  calling the same tool, never reaching a final answer), burning cost
  and time; a hard iteration cap with a graceful failure/escalation path
  is a basic production safeguard, not optional.
"""

from dataclasses import dataclass, field
from typing import Callable


# ------------------------------------------------------------------
# 1. A minimal, from-scratch ReAct agent loop
# ------------------------------------------------------------------
@dataclass
class Tool:
    name: str
    description: str
    func: Callable[[str], str]


@dataclass
class AgentStep:
    thought: str
    action: str | None      # tool name, or None if this is the final answer
    action_input: str | None
    observation: str | None = None


class SimpleReActAgent:
    """
    A deliberately minimal illustration of the ReAct loop's mechanics —
    a real framework (LangGraph, L13; CrewAI, L14) provides much more
    (state management, error handling, streaming, persistence) around
    this exact same core loop.
    """

    def __init__(self, tools: list[Tool], llm_call: Callable[[str], AgentStep], max_steps: int = 5):
        self.tools = {t.name: t for t in tools}
        self.llm_call = llm_call   # stands in for a real LLM call, decoupled for testability
        self.max_steps = max_steps

    def run(self, task: str) -> str:
        history: list[AgentStep] = []

        for step_num in range(self.max_steps):
            # In a real implementation, this prompt includes the task,
            # the FULL history of prior thought/action/observation
            # steps, and the available tools' names/descriptions.
            step = self.llm_call(self._build_prompt(task, history))

            if step.action is None:
                # The model decided it has enough information — this IS
                # the final answer, not another tool call.
                return step.thought

            if step.action not in self.tools:
                step.observation = f"Error: unknown tool '{step.action}'"
            else:
                # Execute the chosen tool, feed its result back as the
                # OBSERVATION for the next loop iteration — this feedback
                # is what lets the agent adapt based on what it actually
                # finds, not a pre-determined sequence.
                step.observation = self.tools[step.action].func(step.action_input)

            history.append(step)

        # Hard iteration cap reached — a required safeguard, not
        # optional, against an agent that never converges to a final answer.
        return "Agent reached maximum steps without a final answer."

    def _build_prompt(self, task: str, history: list[AgentStep]) -> str:
        history_text = "\n".join(
            f"Thought: {s.thought}\nAction: {s.action}[{s.action_input}]\nObservation: {s.observation}"
            for s in history
        )
        tool_descriptions = "\n".join(f"- {t.name}: {t.description}" for t in self.tools.values())
        return (
            f"Task: {task}\n\nAvailable tools:\n{tool_descriptions}\n\n"
            f"History:\n{history_text}\n\nWhat is your next Thought/Action, "
            f"or Final Answer if you have enough information?"
        )


# ------------------------------------------------------------------
# 2. A worked example with a fake (deterministic) LLM for illustration
# ------------------------------------------------------------------
def fake_weather_lookup(city: str) -> str:
    return "18 degrees Celsius" if "tokyo" in city.lower() else "unknown"


def celsius_to_fahrenheit(celsius_str: str) -> str:
    celsius = float(celsius_str.split()[0])
    return f"{celsius * 9/5 + 32} degrees Fahrenheit"


def fake_llm_for_demo(prompt: str) -> AgentStep:
    """
    A hand-scripted stand-in for a real LLM call — a real agent would
    call an actual model here; this makes the LOOP MECHANICS runnable
    and inspectable without requiring an API key for this illustration.
    """
    if "Observation: None" in prompt or "History:\n\n" in prompt:
        return AgentStep(
            thought="I need to find Tokyo's current temperature first.",
            action="weather_lookup", action_input="Tokyo",
        )
    elif "18 degrees Celsius" in prompt and "Fahrenheit" not in prompt:
        return AgentStep(
            thought="Now I need to convert 18C to Fahrenheit.",
            action="celsius_to_fahrenheit", action_input="18 degrees Celsius",
        )
    else:
        return AgentStep(
            thought="Tokyo is 18C (64.4F), which is mild — no coat needed.",
            action=None, action_input=None,
        )


if __name__ == "__main__":
    tools = [
        Tool("weather_lookup", "Look up current weather for a city", fake_weather_lookup),
        Tool("celsius_to_fahrenheit", "Convert a Celsius temperature string to Fahrenheit", celsius_to_fahrenheit),
    ]
    agent = SimpleReActAgent(tools, fake_llm_for_demo, max_steps=5)
    result = agent.run("What's the weather in Tokyo in Fahrenheit, and do I need a coat?")
    print("Final answer:", result)

    print("\n=== Static pipeline vs agent — a decision checklist ===")
    for question in [
        "Is the sequence of steps KNOWN in advance, or does it depend on "
        "what earlier steps discover?",
        "Does the task genuinely need to call DIFFERENT tools/take "
        "different actions depending on intermediate results?",
        "Is the added latency/cost/unpredictability of multiple LLM "
        "calls actually justified, versus a single well-designed prompt "
        "or a fixed pipeline?",
    ]:
        print(f"  - {question}")

"""
PRODUCTION CONTEXT EXAMPLE:
A DevOps troubleshooting agent given "why is the checkout service slow"
cannot follow a fixed pipeline — it must decide, based on what it finds,
whether to check recent deploys, query latency metrics, inspect database
connection pool usage, or check for an ongoing incident, potentially
following several of these paths depending on what each reveals. A hard-
coded max_steps limit and explicit Thought logging (visible in the agent's
history) let an on-call engineer both bound the agent's runtime/cost and
audit exactly WHY it investigated the paths it did, rather than trusting
an opaque final answer with no visible reasoning trail.
"""
