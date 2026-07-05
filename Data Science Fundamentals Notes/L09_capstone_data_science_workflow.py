# ============================================================
# L09: Capstone — The End-to-End Data Science Workflow
# ============================================================
# WHAT: A capstone lesson wiring L01-L08's probability, inference, EDA,
#       optimization, linear algebra, and visualization concepts into
#       ONE coherent data science workflow, from raw data to a
#       validated, communicated conclusion.
# WHY: Each prior lesson covered one mathematical/visualization tool in
#      isolation. A real data science investigation moves through ALL of
#      them in sequence — this capstone shows how, and connects each
#      stage back to where the rest of this repo (ML Frameworks Notes,
#      MLOps Notes) picks up once a model is ready to build/deploy.
# LEVEL: Capstone
# ============================================================

"""
CONCEPT OVERVIEW:
A real data science investigation, start to finish, moves through
distinct stages — each covered by an earlier lesson in this domain:

  1. FRAME THE QUESTION: what decision does this analysis actually
     inform? (e.g. "should we roll out this new checkout flow?")
  2. EDA (L03, L06): summarize and VISUALIZE the raw data first — catch
     data-quality issues (outliers, skew, missing values) BEFORE they
     silently corrupt every downstream step.
  3. PROBABILITY/INFERENCE (L01, L02): frame the actual question as a
     testable hypothesis; understand what a confidence interval or
     p-value from this data can and cannot honestly claim.
  4. MODELING (L04, L05): if a predictive model is needed, optimization
     (gradient descent) finds its parameters; linear algebra
     (vectors/matrices) is the mathematical substrate every model
     operation runs on — this is where this domain hands off directly
     to this repo's ML Frameworks Notes for the actual model-building tools.
  5. COMMUNICATE THE RESULT (L06-L08): a stakeholder-facing chart or BI
     dashboard, built with HONEST design choices (L08) — the analysis is
     worthless if it's not correctly understood by the people making the
     actual decision.
  6. PRODUCTIONIZE (handoff to MLOps Notes, DevOps & SRE Practices
     Notes): if the analysis becomes a recurring model/pipeline, this
     repo's MLOps Notes covers deployment, monitoring, and the online
     experimentation (A/B testing, built on THIS domain's L02
     statistical-inference foundation) needed to validate it in production.

This domain's role in the wider repo: it's the MATHEMATICAL FOUNDATION
underneath ML Frameworks Notes' model-building tools, MLOps Notes'
experimentation platform, and Agentic AI & RAG Notes' embedding/
similarity operations — each of those domains USES these concepts
without re-deriving them, exactly as this capstone's end-to-end trace shows.

PRODUCTION USE CASE:
See the full worked trace below — a realistic "should we launch this
feature" investigation using every stage of this workflow, from raw
data through a stakeholder-facing recommendation.

COMMON MISTAKES:
- Jumping straight to modeling (stage 4) without EDA (stage 2) first —
  a model trained on data with an unnoticed outlier-driven skew, or a
  data-entry error, will confidently produce WRONG results that look
  no different from a model trained on clean data, until it fails in production.
- Treating a statistically significant result (stage 3) as automatically
  meaning "ship it" without considering PRACTICAL significance — a
  genuinely real but tiny effect (a p<0.05 result showing a 0.01%
  conversion lift) may not be worth the engineering cost of shipping it,
  a business judgment stage 3's statistics alone cannot make.
- Building a technically sound analysis (stages 1-4) but communicating
  it (stage 5) with a misleading chart (L08) — a stakeholder acting on a
  visually-distorted takeaway makes a WORSE decision than if the
  analysis had never been done at all, since they now have false confidence.
"""

import math
import random
import statistics
import textwrap


# ------------------------------------------------------------------
# 1. A full worked example, stage by stage
# ------------------------------------------------------------------
def stage_1_frame_the_question():
    print("STAGE 1 — Frame the question:")
    print("  'Does the new checkout flow (Variant B) increase conversion")
    print("   rate enough to justify replacing the current flow (Variant A)?'")


def stage_2_eda(control: list[float], treatment: list[float]):
    print("\nSTAGE 2 — EDA (L03, L06):")
    print(f"  Variant A (control):   mean={statistics.mean(control):.4f}, "
          f"stdev={statistics.stdev(control):.4f}")
    print(f"  Variant B (treatment): mean={statistics.mean(treatment):.4f}, "
          f"stdev={statistics.stdev(treatment):.4f}")
    print("  -> (In a real investigation: histogram each variant's daily")
    print("     conversion rate here to check for skew/outliers BEFORE")
    print("     trusting the summary statistics above, per L03/L06.)")


def stage_3_inference(control: list[float], treatment: list[float]):
    print("\nSTAGE 3 — Statistical inference (L01, L02):")
    mean_a, mean_b = statistics.mean(control), statistics.mean(treatment)
    var_a, var_b = statistics.variance(control), statistics.variance(treatment)
    n_a, n_b = len(control), len(treatment)
    pooled_se = math.sqrt(var_a / n_a + var_b / n_b)
    t_stat = (mean_b - mean_a) / pooled_se
    lift_pct = (mean_b - mean_a) / mean_a * 100

    print(f"  Observed lift: {lift_pct:+.2f}%")
    print(f"  t-statistic: {t_stat:.2f}")
    significant = abs(t_stat) > 1.96
    print(f"  Statistically significant (|t| > 1.96): {significant}")
    print("  -> Per L02: this p-value/t-stat tells us how LIKELY this")
    print("     result is under 'no real difference' (H0) — it does NOT")
    print("     by itself say whether a lift this size is worth shipping.")
    return significant, lift_pct


def stage_4_modeling_handoff():
    print("\nSTAGE 4 — Modeling (L04, L05) — handoff point:")
    print("  If this analysis extends into a PREDICTIVE model (e.g.")
    print("  'which USER SEGMENTS respond best to Variant B'), gradient")
    print("  descent (L04) and matrix operations (L05) are the engine")
    print("  under EVERY model this repo's ML Frameworks Notes would")
    print("  build for that — this domain hands off there directly.")


def stage_5_communicate(significant: bool, lift_pct: float):
    print("\nSTAGE 5 — Communicate the result (L06-L08):")
    honest_chart = textwrap.dedent(f"""\
        Conversion Rate by Variant (y-axis starting at 0%, per L08):
          Variant A: {'#' * 20}
          Variant B: {'#' * int(20 * (1 + lift_pct/100))}
        Observed lift: {lift_pct:+.2f}%  (statistically significant: {significant})
    """)
    print(honest_chart)
    print("  -> An HONEST chart (zero-baseline, per L08) presented to")
    print("     stakeholders alongside the statistical caveat from Stage 3 —")
    print("     NOT a truncated-axis chart exaggerating a modest real effect.")


def stage_6_productionize_handoff():
    print("STAGE 6 — Productionize — handoff point:")
    print("  If Variant B ships, this repo's MLOps Notes L09 (online")
    print("  experimentation) covers running this SAME kind of test as a")
    print("  continuously monitored production experiment, and DevOps &")
    print("  SRE Practices Notes covers the incident/monitoring practices")
    print("  for the system once it's live.")


if __name__ == "__main__":
    random.seed(42)
    control_data = [random.gauss(0.10, 0.015) for _ in range(300)]
    treatment_data = [random.gauss(0.115, 0.015) for _ in range(300)]

    stage_1_frame_the_question()
    stage_2_eda(control_data, treatment_data)
    is_significant, observed_lift = stage_3_inference(control_data, treatment_data)
    stage_4_modeling_handoff()
    stage_5_communicate(is_significant, observed_lift)
    print()
    stage_6_productionize_handoff()

"""
FINAL CONTEXT:
The measure of having internalized this domain isn't reciting formulas
for Bayes' theorem or gradient descent in isolation — it's being able to
walk into a genuine "should we do X" business question, correctly frame
it as a testable hypothesis, catch data problems before they silently
corrupt the analysis, apply the right statistical test HONESTLY
(understanding exactly what its result does and doesn't claim), and
communicate the conclusion in a chart that informs rather than misleads
— then know precisely which of this repo's other domains (ML Frameworks
Notes for modeling, MLOps Notes for production experimentation, DevOps &
SRE Practices Notes for operating the resulting system) to move into
next. This domain is the mathematical and analytical foundation the rest
of the repo's ML/data engineering domains all build on top of.
"""
