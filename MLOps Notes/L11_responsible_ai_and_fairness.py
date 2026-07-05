# ============================================================
# L11: Responsible AI — Fairness Metrics, Model Cards, Explainability
# ============================================================
# WHAT: Quantitative fairness metrics for detecting bias across
#       demographic groups, MODEL CARDS as a standardized documentation
#       artifact, and explainability techniques (SHAP/LIME) for
#       understanding WHY a model made a specific prediction — the audit
#       trail and measurement tools responsible AI practice runs on.
# WHY: L10's behavioral tests catch SPECIFIC, hand-crafted failure
#      cases. This lesson covers SYSTEMATIC, quantitative fairness
#      measurement across an entire population, plus the documentation
#      and explainability practices that make a model's behavior
#      auditable — increasingly a regulatory, not just ethical, requirement.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
FAIRNESS METRICS quantify whether a model's predictions/errors are
distributed EQUITABLY across demographic groups — there is NO single
universal "fairness" metric; different, mathematically INCOMPATIBLE
definitions capture different notions of fairness, and choosing which
one(s) matter is a genuine, context-dependent decision, not a purely
technical one. DEMOGRAPHIC PARITY requires the POSITIVE PREDICTION RATE
to be equal across groups (e.g. the loan-approval rate should be similar
for every demographic group) — appropriate when equal OUTCOME rates are
the goal, but can conflict with actual creditworthiness differences
between groups if those exist for legitimate reasons. EQUALIZED ODDS
requires the TRUE POSITIVE RATE and FALSE POSITIVE RATE to be equal
across groups (a stronger, more nuanced standard than demographic
parity — it allows different overall approval rates IF they reflect
genuinely different underlying qualification rates, but requires the
model's ACCURACY to be equally good for every group). These two
definitions can be MATHEMATICALLY INCOMPATIBLE to satisfy
simultaneously except in special cases — a real, well-documented result
in the fairness literature, meaning "just satisfy all fairness metrics"
isn't always achievable; a deliberate choice of WHICH definition matters
most for the specific use case is required.

A MODEL CARD is a standardized documentation artifact (originating from
a Google Research paper, now a common industry practice) accompanying a
model, covering: intended use cases (and explicitly, unintended/
out-of-scope uses), the training data's provenance and known
limitations, performance broken down BY DEMOGRAPHIC SUBGROUP (not just
aggregate), and known failure modes/ethical considerations — existing
specifically so anyone deciding whether to USE a model (a downstream
team, an auditor, a regulator) has the information needed to judge its
appropriateness for THEIR specific use case, rather than trusting an
aggregate accuracy number as sufficient evidence of general fitness.

EXPLAINABILITY techniques answer "why did the model make THIS specific
prediction for THIS specific input" — SHAP (SHapley Additive
exPlanations, based on game-theoretic Shapley values) and LIME (Local
Interpretable Model-agnostic Explanations, which approximates a complex
model's LOCAL behavior around one specific prediction with a simpler,
interpretable model) are the two most widely used approaches. This
matters for BOTH debugging (understanding why a model behaves
unexpectedly on a specific case) and for regulatory/audit requirements
increasingly requiring "the right to an explanation" for automated
decisions affecting individuals (loan denials, hiring decisions).

PRODUCTION USE CASE:
A loan-approval model's fairness audit computes demographic parity AND
equalized odds across groups, finding the model satisfies equalized odds
reasonably well (similar accuracy for every group) but shows a
meaningful demographic parity gap — the team's documented decision (in
the model card) is that equalized odds is the appropriate standard for
THIS use case (equal accuracy, not necessarily equal approval RATES,
given that approval should track actual creditworthiness), a deliberate,
documented choice rather than an unexamined default.

COMMON MISTAKES:
- Assuming a SINGLE fairness metric is "the" definition of fairness and
  optimizing for it without understanding WHICH notion of fairness it
  captures, or that other reasonable definitions might conflict with it
  — this is a genuine, well-documented mathematical reality (the
  fairness-metric incompatibility result), not a implementation detail to work around.
- Publishing only AGGREGATE model performance (overall accuracy) without
  a subgroup breakdown — a model can have excellent aggregate accuracy
  while performing meaningfully worse for a specific demographic
  subgroup, invisible without the disaggregated view a model card requires.
- Treating explainability tools (SHAP/LIME) as producing a definitive,
  ground-truth explanation of model "reasoning" — both are
  APPROXIMATIONS with their own assumptions/limitations, useful for
  investigation and hypothesis generation, not as unquestionable proof
  of exactly why a model behaved a certain way.
"""

from dataclasses import dataclass


# ------------------------------------------------------------------
# 1. Fairness metrics — demographic parity and equalized odds
# ------------------------------------------------------------------
@dataclass
class GroupPredictions:
    group_name: str
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int

    @property
    def total(self) -> int:
        return self.true_positives + self.false_positives + self.true_negatives + self.false_negatives

    @property
    def positive_prediction_rate(self) -> float:
        """Fraction of this group that received a POSITIVE prediction —
        the quantity DEMOGRAPHIC PARITY compares across groups."""
        return (self.true_positives + self.false_positives) / self.total

    @property
    def true_positive_rate(self) -> float:
        """Of those who ACTUALLY deserve a positive outcome, what
        fraction got one — one of the two rates EQUALIZED ODDS compares."""
        actual_positives = self.true_positives + self.false_negatives
        return self.true_positives / actual_positives if actual_positives else 0

    @property
    def false_positive_rate(self) -> float:
        """The OTHER rate equalized odds compares."""
        actual_negatives = self.false_positives + self.true_negatives
        return self.false_positives / actual_negatives if actual_negatives else 0


def demographic_parity_gap(groups: list[GroupPredictions]) -> float:
    rates = [g.positive_prediction_rate for g in groups]
    return max(rates) - min(rates)


def equalized_odds_gap(groups: list[GroupPredictions]) -> dict:
    tpr_gap = max(g.true_positive_rate for g in groups) - min(g.true_positive_rate for g in groups)
    fpr_gap = max(g.false_positive_rate for g in groups) - min(g.false_positive_rate for g in groups)
    return {"tpr_gap": tpr_gap, "fpr_gap": fpr_gap}


def fairness_audit_demo():
    group_a = GroupPredictions("Group A", true_positives=180, false_positives=20,
                                 true_negatives=750, false_negatives=50)
    group_b = GroupPredictions("Group B", true_positives=90, false_positives=15,
                                 true_negatives=800, false_negatives=95)

    for g in (group_a, group_b):
        print(f"  {g.group_name}: positive_rate={g.positive_prediction_rate:.2%}, "
              f"TPR={g.true_positive_rate:.2%}, FPR={g.false_positive_rate:.2%}")

    print(f"\n  Demographic parity gap: {demographic_parity_gap([group_a, group_b]):.2%}")
    eo_gap = equalized_odds_gap([group_a, group_b])
    print(f"  Equalized odds gap: TPR gap={eo_gap['tpr_gap']:.2%}, "
          f"FPR gap={eo_gap['fpr_gap']:.2%}")
    print("  -> these gaps capture DIFFERENT notions of fairness, and a "
          "model can satisfy one reasonably well while showing a gap on "
          "the other — a deliberate, documented choice of which matters "
          "most for THIS use case is required, not an assumption that "
          "one metric alone tells the whole story.")


# ------------------------------------------------------------------
# 2. A model card template
# ------------------------------------------------------------------
MODEL_CARD_TEMPLATE = """
# Model Card: loan_approval_v3

## Intended Use
- Screening loan applications for a preliminary approval recommendation
- NOT intended for: final approval decisions without human review;
  use in jurisdictions with different regulatory requirements than
  the training data's origin

## Training Data
- Source: 5 years of historical loan applications from [region]
- Known limitation: training data reflects historical approval patterns,
  which may encode past biases in human decision-making

## Performance (disaggregated by subgroup, NOT just aggregate)
| Subgroup      | Accuracy | TPR   | FPR   |
|---------------|----------|-------|-------|
| Overall       | 91.2%    | 82.1% | 4.3%  |
| Group A       | 92.5%    | 85.7% | 3.9%  |
| Group B       | 89.1%    | 76.2% | 5.1%  |

## Fairness Analysis
- Demographic parity gap: 8.3% (see fairness_audit_demo() for methodology)
- Equalized odds gap: TPR gap 9.5%, FPR gap 1.2%
- Documented decision: equalized odds prioritized for this use case,
  given [specific business/legal justification]

## Known Failure Modes
- See L10's behavioral test suite results for specific invariance/
  directional test failures identified during evaluation

## Explainability
- SHAP values available per-prediction via [internal tool link] for
  audit/appeal purposes
"""

# ------------------------------------------------------------------
# 3. Explainability — SHAP-style feature attribution (simplified)
# ------------------------------------------------------------------
def simplified_shap_style_attribution(
    prediction_fn, base_input: dict, feature_names: list[str],
) -> dict[str, float]:
    """
    A SIMPLIFIED illustration of the SHAP concept: measure each
    feature's MARGINAL CONTRIBUTION by comparing the prediction WITH vs
    WITHOUT that feature (replaced by a baseline/average value) — real
    SHAP computes this more rigorously via Shapley values averaged
    across all possible feature orderings, but this captures the core
    idea of feature-level attribution for a SPECIFIC prediction.
    """
    baseline_input = {name: 0 for name in feature_names}
    full_prediction = prediction_fn(base_input)
    baseline_prediction = prediction_fn(baseline_input)

    attributions = {}
    for feature in feature_names:
        without_feature = {**base_input, feature: 0}
        prediction_without = prediction_fn(without_feature)
        attributions[feature] = full_prediction - prediction_without
    return attributions


def explainability_demo():
    def toy_credit_score_model(inputs: dict) -> float:
        return inputs.get("income", 0) * 0.001 + inputs.get("years_employed", 0) * 5

    inputs = {"income": 60000, "years_employed": 8}
    attributions = simplified_shap_style_attribution(
        toy_credit_score_model, inputs, feature_names=["income", "years_employed"],
    )
    print(f"Full prediction: {toy_credit_score_model(inputs):.1f}")
    for feature, contribution in attributions.items():
        print(f"  '{feature}' contributed approximately {contribution:.1f} to this prediction")


if __name__ == "__main__":
    print("--- Fairness audit ---")
    fairness_audit_demo()

    print("\n--- Model card ---")
    print(MODEL_CARD_TEMPLATE)

    print("--- Explainability (simplified SHAP-style attribution) ---")
    explainability_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A regulated financial institution's model governance process requires
BOTH a completed model card AND a documented fairness-metric choice
(with business/legal justification) before ANY model reaches production
— during a regulatory audit, the model card's disaggregated performance
table and the documented reasoning for prioritizing equalized odds over
demographic parity serve as the primary evidence the institution's model
development process meets its fair-lending obligations, turning
"responsible AI" from an abstract principle into a concrete, auditable
artifact produced as a normal part of the deployment pipeline.
"""
