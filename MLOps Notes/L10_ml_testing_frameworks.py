# ============================================================
# L10: ML Testing Frameworks — Data Validation and Model Behavioral Tests
# ============================================================
# WHAT: Testing strategies SPECIFIC to ML systems, beyond standard
#       software unit tests — data validation (schema/distribution
#       checks on inputs), and MODEL BEHAVIORAL testing (invariance
#       tests, directional expectation tests, minimum functionality
#       tests) that verify a model's REASONING, not just its aggregate accuracy.
# WHY: A model can pass its offline accuracy metric while still failing
#      in ways aggregate accuracy alone would never reveal — behavioral
#      testing (borrowed from NLP's CheckList methodology, generalizable
#      to any ML model) is specifically designed to catch these,
#      complementing (not replacing) the data-quality testing this
#      repo's Data Engineering Notes L11 covers for pipelines generally.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
STANDARD SOFTWARE UNIT TESTS check "does this function return the
correct output for this input" — deterministic, exact-match assertions.
ML models are fundamentally PROBABILISTIC and their "correctness" is
usually evaluated in aggregate (accuracy, F1, AUC over a whole test
set) — this aggregate framing can HIDE serious, specific failure modes:
a model with 95% overall accuracy might be making systematically WRONG
predictions for a specific, important subgroup, or relying on a
spurious correlation that won't hold in production. ML testing
frameworks exist specifically to catch this class of problem that
aggregate metrics alone cannot.

DATA VALIDATION (extending this repo's Data Engineering Notes L11's
general data-quality concepts, applied specifically at the ML
train/serve boundary) checks that INCOMING data (both training data and
live inference inputs) matches expected SCHEMA (correct types, no
unexpected nulls in required fields) and expected DISTRIBUTION (values
fall within historically-observed ranges — a sudden distribution shift
in an input feature, even if schematically valid, can indicate an
upstream data problem or a genuine real-world shift the model wasn't
trained to handle).

MODEL BEHAVIORAL TESTING evaluates the model's REASONING through
targeted, hand-crafted test cases, in three main categories: an
INVARIANCE TEST checks that a MEANINGLESS change to input shouldn't
change the output (e.g. a sentiment model's prediction shouldn't flip
just because a person's NAME in the text changes from "John" to
"Maria" — if it does, that's evidence of a spurious, potentially biased
correlation the model learned). A DIRECTIONAL EXPECTATION TEST checks
that a MEANINGFUL change to input should change the output in a KNOWN
DIRECTION (e.g. a house-price model's prediction should INCREASE, not
decrease, when square footage increases with everything else held
constant — if it doesn't, the model has learned something structurally
wrong). A MINIMUM FUNCTIONALITY TEST checks simple, unambiguous cases a
competent model should obviously get right (e.g. "I love this product"
should score clearly positive) — a surprisingly effective, simple
sanity check that a model with a subtle training/serving bug can
actually fail despite a respectable aggregate accuracy score.

PRODUCTION USE CASE:
A loan-approval model passes its 91% aggregate accuracy target in
offline validation, but a behavioral test suite reveals an INVARIANCE
FAILURE: changing only the applicant's ZIP code (holding income, credit
score, and every other feature constant) changes the approval decision
for a meaningful fraction of test cases — a red flag for the model
having learned a proxy for a protected characteristic via geography,
caught by a targeted behavioral test that the aggregate accuracy metric
gave zero indication of.

COMMON MISTAKES:
- Relying ENTIRELY on aggregate accuracy/F1/AUC as the sole quality gate
  before deployment, with no targeted behavioral test suite — this
  misses systematic, subgroup-specific, or spurious-correlation failure
  modes that aggregate metrics are mathematically incapable of surfacing.
- Writing invariance/directional tests as one-off, ad-hoc checks run
  manually before a big launch, instead of maintaining them as a
  PERMANENT, automated test suite run on EVERY model retraining —
  behavioral regressions can be reintroduced by a later retraining just
  as easily as the first training run introduced them.
- Validating data schema/types at ingestion but never validating
  DISTRIBUTION — a schematically valid but distributionally shifted
  input (e.g. a feature's typical range shifting due to an upstream
  change) can silently degrade model quality without triggering any
  schema-based validation check.
"""

from dataclasses import dataclass
from typing import Callable


# ------------------------------------------------------------------
# 1. Data validation — schema AND distribution checks
# ------------------------------------------------------------------
@dataclass
class FeatureSchema:
    name: str
    dtype: type
    required: bool
    expected_min: float | None = None
    expected_max: float | None = None


def validate_schema(record: dict, schema: list[FeatureSchema]) -> list[str]:
    errors = []
    for field in schema:
        if field.name not in record:
            if field.required:
                errors.append(f"missing required field: {field.name}")
            continue
        value = record[field.name]
        if not isinstance(value, field.dtype):
            errors.append(f"{field.name}: expected {field.dtype.__name__}, got {type(value).__name__}")
    return errors


def validate_distribution(record: dict, schema: list[FeatureSchema]) -> list[str]:
    """Distinct from schema validity — a value can be the CORRECT TYPE
    but still fall OUTSIDE the historically-observed range, a signal
    worth flagging even though it's not a hard schema violation."""
    warnings = []
    for field in schema:
        if field.name not in record or field.expected_min is None:
            continue
        value = record[field.name]
        if not (field.expected_min <= value <= field.expected_max):
            warnings.append(f"{field.name}={value} is outside expected range "
                             f"[{field.expected_min}, {field.expected_max}]")
    return warnings


# ------------------------------------------------------------------
# 2. Invariance testing — a meaningless change should not change the output
# ------------------------------------------------------------------
def toy_sentiment_model(text: str) -> str:
    """A deliberately flawed toy model for illustration — reacts to
    a NAME it shouldn't care about, simulating a real spurious-
    correlation bug a behavioral test is designed to catch."""
    positive_words = {"love", "great", "excellent", "amazing"}
    words = set(text.lower().split())
    if "maria" in words:   # THE bug — an irrelevant name affecting output
        return "neutral"
    return "positive" if words & positive_words else "neutral"


def run_invariance_test(model_fn: Callable[[str], str], base_text: str,
                          perturbations: list[str]) -> list[tuple[str, str, bool]]:
    """
    Checks that swapping an IRRELEVANT detail (here, a name) does NOT
    change the model's prediction — any change flags a potential
    spurious correlation.
    """
    base_prediction = model_fn(base_text)
    results = []
    for perturbed_text in perturbations:
        perturbed_prediction = model_fn(perturbed_text)
        passed = perturbed_prediction == base_prediction
        results.append((perturbed_text, perturbed_prediction, passed))
    return results


def invariance_test_demo():
    base = "John says this product is amazing"
    perturbations = [
        "Maria says this product is amazing",   # only the name changed
        "Alex says this product is amazing",
    ]
    results = run_invariance_test(toy_sentiment_model, base, perturbations)
    print(f"Base text prediction: '{toy_sentiment_model(base)}'")
    for text, prediction, passed in results:
        status = "PASS" if passed else "FAIL (spurious correlation detected)"
        print(f"  '{text}' -> '{prediction}'  [{status}]")


# ------------------------------------------------------------------
# 3. Directional expectation testing
# ------------------------------------------------------------------
def toy_house_price_model(square_footage: float, bedrooms: int) -> float:
    return square_footage * 150 + bedrooms * 5000


def run_directional_test(model_fn: Callable, base_input: dict, changed_field: str,
                           new_value, expected_direction: str) -> bool:
    base_price = model_fn(**base_input)
    changed_input = {**base_input, changed_field: new_value}
    new_price = model_fn(**changed_input)

    if expected_direction == "increase":
        return new_price > base_price
    return new_price < base_price


def directional_test_demo():
    base_input = {"square_footage": 1500, "bedrooms": 3}
    passed = run_directional_test(
        toy_house_price_model, base_input, changed_field="square_footage",
        new_value=2000, expected_direction="increase",
    )
    print(f"Directional test — increasing square footage should increase "
          f"predicted price: {'PASS' if passed else 'FAIL'}")


# ------------------------------------------------------------------
# 4. Minimum functionality tests — obvious cases a model must get right
# ------------------------------------------------------------------
MINIMUM_FUNCTIONALITY_CASES = [
    ("I love this product", "positive"),
    ("This is the worst experience I've ever had", "negative"),
    ("The package arrived on time", "neutral"),
]


def run_minimum_functionality_tests(model_fn: Callable[[str], str],
                                       cases: list[tuple[str, str]]) -> list[bool]:
    return [model_fn(text) == expected for text, expected in cases]


if __name__ == "__main__":
    schema = [
        FeatureSchema("age", int, required=True, expected_min=18, expected_max=100),
        FeatureSchema("income", float, required=True, expected_min=0, expected_max=1_000_000),
    ]

    print("--- Data validation ---")
    record = {"age": 35, "income": 2_500_000.0}   # income out of expected range
    print("Schema errors:", validate_schema(record, schema))
    print("Distribution warnings:", validate_distribution(record, schema))

    print("\n--- Invariance test ---")
    invariance_test_demo()

    print("\n--- Directional expectation test ---")
    directional_test_demo()

    print("\n--- Minimum functionality tests ---")
    results = run_minimum_functionality_tests(
        lambda t: "positive" if "love" in t.lower() else ("negative" if "worst" in t.lower() else "neutral"),
        MINIMUM_FUNCTIONALITY_CASES,
    )
    print(f"Passed {sum(results)}/{len(results)} minimum functionality cases")

"""
PRODUCTION CONTEXT EXAMPLE:
A hiring-screening model passes its aggregate accuracy target, but an
invariance test suite (swapping candidate names between commonly
male-associated and female-associated names, holding every qualification
field constant) reveals the model's output changes for a measurable
fraction of test cases — a finding that would NEVER surface from
aggregate accuracy alone, prompting the team to investigate and retrain
before deployment, precisely the failure class behavioral testing exists
to catch and aggregate metrics are structurally blind to.
"""
