# ============================================================
# L08: DSPy — Declarative, Programmatic Prompting and Prompt Optimization
# ============================================================
# WHAT: DSPy's fundamentally different approach to building LLM
#       pipelines — instead of hand-writing prompt strings, you declare
#       SIGNATURES (input/output specifications) and MODULES (reusable
#       prompting strategies), then let an OPTIMIZER automatically
#       search for/compile the actual prompt wording and few-shot
#       examples that work best.
# WHY: Every framework so far (LangChain, LlamaIndex, Haystack) still
#      requires YOU to hand-write and iteratively tune prompt strings.
#      DSPy treats prompt engineering as an OPTIMIZATION PROBLEM the
#      framework solves for you, given a metric to optimize against —
#      a genuinely different paradigm worth understanding even if you
#      don't use DSPy for every project.
# LEVEL: Advanced (Phase 2 of 7)
# ============================================================

"""
CONCEPT OVERVIEW:
A SIGNATURE declares WHAT a step should do in terms of typed inputs and
outputs (e.g. "given `context` and `question`, produce `answer`") —
WITHOUT specifying the actual prompt wording. This is the key conceptual
shift: you describe the TASK, not the PROMPT.

A MODULE implements a PROMPTING STRATEGY for a signature — `dspy.Predict`
does simple single-shot prompting; `dspy.ChainOfThought` automatically
adds "let's think step by step"-style reasoning before the final answer;
`dspy.ReAct` implements the ReAct reasoning-and-acting pattern (covered
in depth in Phase 3's agent lessons) as a reusable module. You compose
modules into a pipeline (a Python class with a `forward()` method calling
several modules in sequence) much like composing PyTorch neural network
layers — DSPy's design is explicitly inspired by PyTorch's `nn.Module` pattern.

The OPTIMIZER (formerly called "teleprompter") is DSPy's signature
contribution: given your pipeline, a small labeled dataset, and a METRIC
function (e.g. "does the generated answer match the expected answer"),
an optimizer like `BootstrapFewShot` or `MIPROv2` automatically searches
for the best FEW-SHOT EXAMPLES and/or prompt phrasing to include —
effectively COMPILING your declarative pipeline into a concrete, tuned
prompt, analogous to how a compiler optimizes code without you manually
tuning the assembly output. This is fundamentally different from manual
prompt engineering: instead of you iterating on prompt wording by hand
based on intuition, the optimizer searches systematically against your
actual metric.

PRODUCTION USE CASE:
A RAG pipeline's answer-generation step is declared as a DSPy signature
and Chain-of-Thought module; running `BootstrapFewShot` against 50
labeled (question, correct-answer) pairs automatically discovers which
few-shot examples, included in the compiled prompt, maximize answer
accuracy on a held-out validation set — a systematic search replacing
what would otherwise be days of manual prompt-wording trial and error.

COMMON MISTAKES:
- Treating DSPy as "just another prompting framework" and hand-writing
  prompts anyway instead of leveraging its optimizer — this discards
  DSPy's actual value proposition and just adds an unfamiliar
  abstraction layer with no corresponding benefit.
- Running an optimizer without a genuinely representative metric/labeled
  dataset — the optimizer can only be as good as what you're optimizing
  FOR; a poorly-chosen metric (e.g. exact string match when semantic
  correctness with different wording should count) produces a compiled
  prompt optimized for the wrong thing.
- Expecting DSPy's optimization to substitute for having a clear task
  DEFINITION (the signature) — a vague or poorly-specified signature
  gives the optimizer little useful structure to search within,
  regardless of how much labeled data you provide.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Signatures — declaring WHAT, not HOW
# ------------------------------------------------------------------
SIGNATURE_EXAMPLE = textwrap.dedent("""\
    import dspy

    # A signature declares typed inputs/outputs with brief field
    # descriptions — NOT the actual prompt wording. DSPy generates and
    # later OPTIMIZES the actual prompt from this specification.
    class AnswerFromContext(dspy.Signature):
        \"\"\"Answer the question using only the provided context.\"\"\"
        context: str = dspy.InputField(desc="retrieved passages relevant to the question")
        question: str = dspy.InputField()
        answer: str = dspy.OutputField(desc="a concise, grounded answer")
""")

# ------------------------------------------------------------------
# 2. Modules — reusable prompting strategies over a signature
# ------------------------------------------------------------------
MODULE_EXAMPLE = textwrap.dedent("""\
    # dspy.Predict: simple, single-shot prompting for the signature.
    basic_qa = dspy.Predict(AnswerFromContext)

    # dspy.ChainOfThought: AUTOMATICALLY inserts step-by-step reasoning
    # before the final answer field — you didn't have to hand-write
    # "let's think step by step" into a prompt string; the module
    # implements this strategy generically for ANY signature.
    reasoning_qa = dspy.ChainOfThought(AnswerFromContext)

    result = reasoning_qa(context=retrieved_context, question="How long does a refund take?")
    print(result.answer)          # the final answer
    print(result.reasoning)       # the intermediate reasoning steps, inspectable
""")

# ------------------------------------------------------------------
# 3. Composing modules into a full RAG pipeline (PyTorch-nn.Module-style)
# ------------------------------------------------------------------
DSPY_RAG_PIPELINE = textwrap.dedent("""\
    class RAGPipeline(dspy.Module):
        def __init__(self, retriever):
            super().__init__()
            self.retriever = retriever
            self.generate_answer = dspy.ChainOfThought(AnswerFromContext)

        def forward(self, question):
            retrieved = self.retriever(question)   # your L03/L04 retrieval logic
            prediction = self.generate_answer(context=retrieved, question=question)
            return prediction

    pipeline = RAGPipeline(retriever=my_vector_retriever)
    result = pipeline(question="How do I request a refund?")
""")

# ------------------------------------------------------------------
# 4. Optimizers — compiling a tuned pipeline from labeled examples
# ------------------------------------------------------------------
OPTIMIZER_EXAMPLE = textwrap.dedent("""\
    from dspy.teleprompt import BootstrapFewShot

    def answer_correctness_metric(example, prediction, trace=None):
        # YOUR definition of "good" — the optimizer searches for whatever
        # maximizes THIS function, so its quality is bounded by how well
        # this metric actually captures what "correct" means for your task.
        return example.answer.lower() in prediction.answer.lower()

    labeled_examples = [
        dspy.Example(question="How long does a refund take?",
                       answer="5 business days").with_inputs("question"),
        # ... more labeled (question, correct_answer) pairs ...
    ]

    optimizer = BootstrapFewShot(metric=answer_correctness_metric)
    compiled_pipeline = optimizer.compile(RAGPipeline(retriever=my_vector_retriever),
                                            trainset=labeled_examples)

    # `compiled_pipeline` now has AUTOMATICALLY DISCOVERED few-shot
    # examples baked into its prompting strategy — chosen specifically
    # because they improved the metric on your labeled data, not because
    # a human guessed they'd help.
    result = compiled_pipeline(question="What's the shipping time?")
""")

# ------------------------------------------------------------------
# 5. DSPy vs hand-written prompting — the paradigm difference
# ------------------------------------------------------------------
PARADIGM_COMPARISON = {
    "Hand-written prompting (LangChain/LlamaIndex/Haystack default style)":
        "You write the exact prompt string, including few-shot examples "
        "if any, and iterate by hand based on intuition/manual testing.",
    "DSPy": "You declare WHAT the task needs (signature) and WHICH "
        "reasoning strategy to apply (module); an optimizer SEARCHES for "
        "the prompt wording/few-shot examples that actually maximize "
        "your chosen metric on labeled data — a systematic, data-driven "
        "process replacing manual iteration.",
}


if __name__ == "__main__":
    print(SIGNATURE_EXAMPLE)
    print(MODULE_EXAMPLE)
    print(DSPY_RAG_PIPELINE)
    print(OPTIMIZER_EXAMPLE)
    print("=== Paradigm comparison ===")
    for approach, note in PARADIGM_COMPARISON.items():
        print(f"{approach}:\n  {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A customer support RAG pipeline's manually-hand-tuned prompt achieves 78%
answer accuracy on a held-out evaluation set after a week of manual
iteration. Rewriting the same pipeline in DSPy (a signature + Chain-of-
Thought module) and running `BootstrapFewShot` against the SAME
evaluation set's labeled examples discovers a different set of few-shot
examples than the team had manually chosen, improving accuracy to 85% in
under an hour of compute time — the systematic search finding a better
solution than manual intuition had, specifically because it was
optimizing directly against the actual measured metric rather than a
human's guess about what would generalize well.
"""
