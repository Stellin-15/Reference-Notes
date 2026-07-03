# ============================================================
# L25: Capstone — Designing Your Own Quantization/Inference Tool
# ============================================================
# WHAT: A concrete design template and staged roadmap for building your
#       OWN project — whether that's a novel quantization method, an
#       inference-engine contribution, or a standalone tool — using
#       every technique from L01-L24 as building blocks.
# WHY: This curriculum's stated goal was never "learn facts about
#      quantization" — it was "build the knowledge to write papers AND
#      build something that makes AI easier to run on hardware." This
#      lesson is where those two threads converge into an actual project
#      plan, not just a reading list you finished.
# LEVEL: Capstone (Phase 8 of 8 — apply everything)
# ============================================================

"""
CONCEPT OVERVIEW:
A well-scoped capstone project has FOUR things a vague one lacks:
  1. A crisp PROBLEM STATEMENT (one sentence, one measurable outcome).
  2. A DEPENDENCY MAP onto skills you actually have (from this
     curriculum) — no hidden "and then I'll figure out CUDA" steps.
  3. A STAGED plan with a genuinely useful MINIMUM version at every
     stage — not "80% done and unusable," but "stage 1 alone is already
     worth having."
  4. An honest EVALUATION plan decided BEFORE you start building, not
     invented after to justify whatever you happened to build (this is
     the single most common way otherwise-good projects produce
     unconvincing results).

Below are three concrete, realistically-scoped project templates,
directly assembled from techniques across this curriculum. Pick one,
adapt it, or use the STRUCTURE to design your own — the structure matters
more than which exact project you choose.

PROJECT TEMPLATE A — "Quantization-error characterization" (leans research):
  Problem: How does quantization error (measured via L09's SQNR) compound
  across N sequential reasoning steps, for GPTQ (L12) vs AWQ (L13) at
  matched bit-width?
  Stage 1 (useful alone): A reusable benchmark harness that runs a
  multi-step reasoning eval on a model at multiple quantization configs,
  logging per-step error metrics — even without novel findings yet, this
  harness itself is a shareable artifact.
  Stage 2: Run it across 2-3 model sizes, GPTQ vs AWQ, 3-8 bit-widths.
  Stage 3: Statistical analysis (L23) — is there a real, significant
  trend, or is it noise? Write up per L24, regardless of which way it goes.

PROJECT TEMPLATE B — "A fused kernel contribution" (leans systems):
  Problem: llama.cpp/vLLM lacks (or has an unoptimized version of) a
  specific quantization format's fused kernel for a specific hardware
  target you have access to.
  Stage 1 (useful alone): A correct-but-unoptimized Triton (L18)
  implementation, verified against a reference (L18's pattern) — this
  alone is a working proof of concept you can share.
  Stage 2: Profile against the roofline model (L17), identify the actual
  bottleneck, optimize (tune block sizes, consider dropping to raw CUDA
  per L19 if warranted).
  Stage 3: Benchmark against the existing baseline kernel, on real
  hardware, with multiple seeds/runs (L23). If it's a genuine
  improvement, open a PR against the real project (L22).

PROJECT TEMPLATE C — "A new lightweight quantization scheme" (leans both):
  Problem: Design a quantization scheme for a SPECIFIC constraint gap you
  identify (e.g. a granularity/overhead tradeoff point, per L11, that
  existing schemes don't target well for a particular model family/size).
  Stage 1 (useful alone): The scheme's math (L09-style), implemented and
  validated on synthetic data with known ground truth.
  Stage 2: Applied to a real model's weights, compared against GPTQ/AWQ/
  GGUF (L12-L15) at matched effective bit-width (L15's "effective bits"
  accounting — compare fairly, not nominal-bit-count-to-nominal-bit-count).
  Stage 3: A fused kernel (L18) implementing it efficiently, benchmarked
  end-to-end (not just weight-error metrics — actual inference latency).

PRODUCTION/RESEARCH USE CASE:
Whichever template you pick, the SAME evaluation discipline applies:
decide your success metric and baseline BEFORE building, run enough
trials to trust your numbers (L23), and write up honestly including
what didn't work (L24) — a project executed with this discipline is
valuable regardless of whether the headline result is a clean win.

COMMON MISTAKES:
- Starting Stage 2 or 3 work before Stage 1 is genuinely SOLID (verified
  correct, not just "seems to run") — errors compound, and debugging a
  Stage 3 result that's wrong because of an undetected Stage 1 bug wastes
  far more time than a rigorous Stage 1 checkpoint would have cost.
- Picking a project scope that depends on hardware/compute you don't
  actually have access to — re-scope to something a single consumer GPU
  can genuinely execute end-to-end, per this curriculum's explicit target.
- Treating the capstone as the END of learning rather than the FIRST of
  many projects — the real skill this curriculum builds is the ability
  to scope, execute, and honestly evaluate the NEXT project too.
"""

from dataclasses import dataclass, field


# ------------------------------------------------------------------
# 1. A project design template you can literally fill in
# ------------------------------------------------------------------
@dataclass
class ProjectStage:
    name: str
    deliverable: str            # what exists and is useful after this stage
    depends_on_lessons: list[str] = field(default_factory=list)
    success_criteria: str = ""


@dataclass
class ProjectPlan:
    problem_statement: str      # one precise, measurable sentence
    baseline: str                 # what you're comparing against
    stages: list[ProjectStage]
    evaluation_plan: str          # decided BEFORE building anything


def example_project_plan() -> ProjectPlan:
    return ProjectPlan(
        problem_statement=(
            "Does quantization error (SQNR) compound super-linearly, "
            "linearly, or sub-linearly across sequential reasoning steps, "
            "comparing GPTQ vs AWQ at matched 4-bit effective precision, "
            "on a 1-3B parameter open model?"
        ),
        baseline="Full-precision (BF16) model's per-step reasoning accuracy",
        stages=[
            ProjectStage(
                name="Stage 1: Benchmark harness",
                deliverable="A reusable script: load a model, quantize it "
                             "(GPTQ/AWQ/RTN), run a multi-step reasoning "
                             "eval, log per-step correctness AND per-layer "
                             "SQNR (L09).",
                depends_on_lessons=["L09", "L12", "L13", "L23"],
                success_criteria="Runs end-to-end on at least one model, "
                                  "output is a clean, inspectable log file.",
            ),
            ProjectStage(
                name="Stage 2: Sweep",
                deliverable="Results across 2-3 model sizes, GPTQ vs AWQ, "
                             "3-8 bit precision, with multiple calibration "
                             "seeds per configuration.",
                depends_on_lessons=["L07", "L11", "L23"],
                success_criteria="Enough runs per config to compute a "
                                  "confidence interval (L23), not single "
                                  "point estimates.",
            ),
            ProjectStage(
                name="Stage 3: Analysis and writeup",
                deliverable="A fitted trend (L07-style power-law fit if "
                             "applicable) describing HOW error compounds, "
                             "plus an honest writeup per L24's structure.",
                depends_on_lessons=["L07", "L24"],
                success_criteria="A specific, falsifiable claim stated in "
                                  "the abstract, with the evidence for it "
                                  "shown with uncertainty, and honest "
                                  "limitations stated.",
            ),
        ],
        evaluation_plan=(
            "Primary metric: task accuracy at each reasoning step, "
            "compared to full-precision baseline, with 95% CI across >=5 "
            "calibration seeds per (method, bit-width, model size) combo. "
            "Secondary metric: per-layer SQNR, to check whether error "
            "trends correlate with the accuracy trend or diverge from it "
            "(itself a potentially interesting finding either way)."
        ),
    )


def print_project_plan(plan: ProjectPlan):
    print(f"PROBLEM: {plan.problem_statement}\n")
    print(f"BASELINE: {plan.baseline}\n")
    for stage in plan.stages:
        print(f"--- {stage.name} ---")
        print(f"  deliverable: {stage.deliverable}")
        print(f"  builds on: {', '.join(stage.depends_on_lessons)}")
        print(f"  success criteria: {stage.success_criteria}\n")
    print(f"EVALUATION PLAN (decided up front): {plan.evaluation_plan}")


# ------------------------------------------------------------------
# 2. A full curriculum recap — what you now have the tools to do
# ------------------------------------------------------------------
CURRICULUM_RECAP = {
    "Phase 1 (L01-L03)": "Tensors, autograd, numerics, attention — the "
        "irreducible foundation everything else assumes.",
    "Phase 2 (L04-L08)": "A full transformer built and trained from "
        "scratch, plus scaling laws and LoRA/QLoRA — you can now build "
        "and adapt a real (small-scale) LLM yourself.",
    "Phase 3 (L09-L11)": "The exact math of quantization, PTQ vs QAT, and "
        "calibration/granularity tradeoffs — the vocabulary and tools "
        "every quantization paper assumes you already have.",
    "Phase 4 (L12-L16)": "GPTQ, AWQ, SmoothQuant/LLM.int8(), GGUF/K-quants, "
        "and NF4/sub-4-bit — four major published methods reproduced "
        "from scratch, plus a map of what's still genuinely open.",
    "Phase 5 (L17-L19)": "GPU memory hierarchy, a real fused Triton "
        "kernel, and enough CUDA to read production kernel code — the "
        "systems skill that turns quantization theory into measured speedup.",
    "Phase 6 (L20-L22)": "KV cache, PagedAttention, continuous batching, "
        "speculative decoding, and how vLLM/llama.cpp are actually built "
        "— the serving-system context your own tooling would fit into.",
    "Phase 7 (L23-L24)": "How to read papers skeptically, reproduce "
        "results with real statistical rigor, and structure/publish your "
        "own contribution.",
    "Phase 8 (L25)": "This lesson — turning all of the above into an "
        "actual, scoped, executable project.",
}


if __name__ == "__main__":
    print("=== Curriculum recap ===\n")
    for phase, summary in CURRICULUM_RECAP.items():
        print(f"{phase}: {summary}\n")

    print("=== Example filled-in project plan ===\n")
    print_project_plan(example_project_plan())

"""
FINAL CONTEXT:
The honest measure of this curriculum's success is not "I read all 25
lessons" — it's "I can now design, scope, execute, and honestly evaluate
a project like the one templated above, and I understand precisely which
prior lesson each design decision draws on." If a specific lesson's
concept doesn't click during your own project work, that lesson's file
is still here, with runnable code, to revisit — this folder is meant to
function as a working reference you come back to during the ACTUAL
project, not just a one-time read-through.
"""
