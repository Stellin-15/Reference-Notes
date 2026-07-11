# ============================================================
# L06: Semantic Kernel — Microsoft's Enterprise Agent/Orchestration SDK
# ============================================================
# WHAT: Semantic Kernel's core abstractions — the Kernel, Plugins
#       (functions an LLM can call), Planners, and Memory — Microsoft's
#       own LLM-orchestration framework, positioned as the enterprise/
#       .NET-and-Python-first alternative to LangChain.
# WHY: Agentic AI & RAG Notes covers LangChain, LlamaIndex, LangGraph,
#      CrewAI, and AutoGen/Microsoft Agent Framework (L05, L06, L13,
#      L14, L15) in depth, but not Semantic Kernel specifically —
#      Microsoft's OWN framework, and the one Azure-centric job
#      postings frequently name alongside LangChain/LangGraph as an
#      expected skill.
# LEVEL: Core (Lesson 6 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
Semantic Kernel (SK) is Microsoft's open-source SDK for building LLM
applications — conceptually it occupies the same space as LangChain
(LLM Frameworks Notes L02) but with a distinct design philosophy: SK
treats the LLM as one PLUGGABLE COMPONENT inside an existing
application's architecture, with first-class support for BOTH C#/.NET
and Python from day one (LangChain is Python/JS-first with .NET as a
distant afterthought) — the deciding factor for many enterprises
already standardized on .NET.

THE KERNEL: the central orchestrator
------------------------------------------
The KERNEL is SK's equivalent of LangChain's `Chain`/`Runnable`
composition root — a single object you register PLUGINS, AI SERVICES
(e.g. an Azure OpenAI chat completion service), and MEMORY connectors
into, and then invoke functions or prompts through. Everything SK does
routes through the kernel, which is also where enterprise concerns
(logging, telemetry, content filtering hooks) get centrally wired in —
directly mirroring the "everything through a gateway" theme from L02.

PLUGINS: the SK term for tools/functions
-----------------------------------------------
A SK PLUGIN is a group of related FUNCTIONS the LLM can invoke — the
same concept as LangChain "tools" (LLM Frameworks Notes L04) or
"function calling" generically (Agentic AI & RAG Notes L21), but SK
plugins can be defined two ways:
  - NATIVE FUNCTIONS: plain Python/C# functions decorated with
    `@kernel_function`, with type hints and docstrings that SK uses to
    generate the function-calling schema automatically.
  - SEMANTIC FUNCTIONS: a PROMPT TEMPLATE itself registered as an
    invokable "function" — e.g. a "Summarize" semantic function is just
    a prompt with an `{{$input}}` placeholder, callable exactly like a
    native function and composable with them in the same plugin.
This native+semantic duality is the one genuinely distinctive SK idea:
prompts and code are both first-class, interchangeable "functions" in
the same plugin, whereas in LangChain a prompt template and a tool
function are more separate concepts wired together.

PLANNERS: automatic multi-step orchestration
--------------------------------------------------
A PLANNER takes a natural-language goal and the set of registered
plugins/functions and produces (and can execute) a PLAN — a sequence of
function calls that accomplishes the goal — conceptually similar to a
LangChain/LangGraph agent's ReAct loop (LLM Frameworks Notes L04,
Agentic AI & RAG Notes L12) but expressed as an explicit, inspectable
plan object rather than an interleaved reasoning trace. This makes SK
plans easier to log, review, and constrain before execution — a real
advantage in regulated environments where "show me the exact steps the
agent is about to take before it takes them" is a compliance
requirement, not a nice-to-have.

MEMORY: semantic recall over embeddings
--------------------------------------------
SK's MEMORY abstraction wraps a vector store (Azure AI Search, L04, is
a first-class connector) behind a simple `save_information` /
`search` API — the same RAG-retrieval concept covered generically in
Agentic AI & RAG Notes L02-L04, exposed as a kernel-native primitive so
retrieval can be composed directly into plugins/plans rather than
wired as separate application code.

SEMANTIC KERNEL vs LANGCHAIN vs MICROSOFT AGENT FRAMEWORK
------------------------------------------------------------------
- LangChain/LangGraph (LLM Frameworks Notes L02/L05): the dominant
  open-source, Python/JS-first ecosystem — broadest third-party
  integration surface, largest community.
- Semantic Kernel: the enterprise/.NET-friendly choice, native+semantic
  function duality, planners as inspectable plan objects, deepest
  native integration with Azure AI Foundry and Azure OpenAI specifically.
- Microsoft Agent Framework (Agentic AI & RAG Notes L15): Microsoft's
  NEWER, more explicitly agent-first framework — where SK is a general
  LLM-orchestration SDK that CAN build agents, Agent Framework is
  purpose-built for multi-agent systems from the ground up, and is
  positioned as SK's eventual agent-focused evolution within the
  Microsoft ecosystem (the two are converging, not permanently separate
  products, and Microsoft's own guidance is increasingly steering new
  agent-first projects toward Agent Framework/AI Foundry Agent Service,
  covered in L07, while SK remains relevant for its plugin/kernel
  composition model in non-agentic LLM-orchestration scenarios).

PRODUCTION USE CASE:
A bank's internal support-ticket triage tool uses SK's native+semantic
plugin duality: a native `LookupCustomerAccount` function (calls an
internal REST API) sits in the same plugin as a semantic
`ClassifyTicketUrgency` function (a prompt template), both callable by
a planner that's given the goal "triage this ticket and route it to
the right team" — the planner's resulting plan is logged and reviewed
before execution as part of the bank's AI governance sign-off, directly
satisfying an auditability requirement a looser agent-loop approach
would make harder to demonstrate.

COMMON MISTAKES:
- Treating SK and LangChain as interchangeable and picking whichever is
  more familiar, without weighing the actual deciding factor —
  .NET-native enterprise integration and Azure-first tooling favor SK;
  broadest ecosystem/integration breadth favors LangChain.
- Building a new, primarily agentic (multi-agent, tool-heavy) system on
  bare Semantic Kernel today without evaluating whether Microsoft Agent
  Framework's more purpose-built agent orchestration (L15) is now the
  better-supported path for that specific shape of problem.
- Not inspecting/logging the planner's generated PLAN before execution
  in a regulated context — the inspectable-plan-object advantage over a
  ReAct loop is lost if the plan is executed immediately without a
  review or logging step.
- Mixing native and semantic functions inconsistently across a codebase
  (e.g. reimplementing as native code something that's naturally a
  simple prompt template) instead of using whichever form fits the task
  — the duality is a feature only if both forms are actually used where
  they fit.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Kernel setup with an Azure OpenAI chat service registered
# ------------------------------------------------------------------
KERNEL_SETUP_EXAMPLE = textwrap.dedent("""\
    import semantic_kernel as sk
    from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion

    kernel = sk.Kernel()
    kernel.add_service(
        AzureChatCompletion(
            deployment_name="gpt4o-mini-chat",   # the L01/L02 deployment name
            endpoint="https://aoai-platform-prod.openai.azure.com/",
            api_key=api_key,
        )
    )
""")

# ------------------------------------------------------------------
# 2. A plugin combining a NATIVE function and a SEMANTIC function
# ------------------------------------------------------------------
PLUGIN_DUALITY_EXAMPLE = textwrap.dedent("""\
    from semantic_kernel.functions import kernel_function

    class TicketPlugin:
        @kernel_function(description="Look up a customer account by ID")
        def lookup_customer_account(self, account_id: str) -> str:
            # NATIVE function -- plain Python, type hints become the
            # function-calling schema automatically.
            return internal_api.get_account(account_id)

    kernel.add_plugin(TicketPlugin(), plugin_name="Tickets")

    # SEMANTIC function -- a prompt template registered as a callable
    # "function," composable with the native one above in the same plugin.
    classify_urgency = kernel.add_function(
        plugin_name="Tickets",
        function_name="ClassifyUrgency",
        prompt="Classify this support ticket's urgency as low/medium/high:\\n{{$input}}",
    )
""")

# ------------------------------------------------------------------
# 3. Planner: goal -> inspectable plan -> execute (logged before running)
# ------------------------------------------------------------------
PLANNER_EXAMPLE = textwrap.dedent("""\
    from semantic_kernel.planners import FunctionCallingStepwisePlanner

    planner = FunctionCallingStepwisePlanner(service_id="chat")
    plan_result = await planner.invoke(
        kernel, "Triage ticket #4821 and route it to the right team."
    )

    # The plan's step sequence is INSPECTABLE before/after execution --
    # log it for the bank's AI-governance audit trail, exactly the
    # auditability advantage over an unlogged ReAct loop.
    for step in plan_result.steps:
        audit_log.info(f"Plan step: {step.function_name}({step.parameters})")
""")

FRAMEWORK_CHOICE_GUIDE = {
    "Broadest OSS ecosystem/integrations": "LangChain / LangGraph (LLM Frameworks L02/L05)",
    ".NET-native enterprise app, Azure-first": "Semantic Kernel",
    "Purpose-built multi-agent system, newest Microsoft path": "Microsoft Agent Framework (RAG Notes L15)",
    "Inspectable plan object required for compliance sign-off": "Semantic Kernel planners",
}


if __name__ == "__main__":
    print(KERNEL_SETUP_EXAMPLE)
    print(PLUGIN_DUALITY_EXAMPLE)
    print(PLANNER_EXAMPLE)
    print("=== Framework choice guide ===")
    for scenario, choice in FRAMEWORK_CHOICE_GUIDE.items():
        print(f"{scenario}: {choice}")

"""
PRODUCTION CONTEXT EXAMPLE:
A bank's internal support-ticket triage assistant registers a native
`LookupCustomerAccount` plugin function alongside a semantic
`ClassifyUrgency` prompt function in the same Semantic Kernel plugin,
uses a stepwise planner to produce a plan for "triage and route this
ticket," and logs the full generated plan to the same audit pipeline
used for Azure OpenAI content-filter results (L02) -- so an AI
governance reviewer can see exactly which functions the planner intends
to call, in what order, before the plan executes against a live
customer account.
"""
