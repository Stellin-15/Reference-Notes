# ============================================================
# L01: Probability Fundamentals for Machine Learning
# ============================================================
# WHAT: The probability concepts underlying most of ML — probability
#       distributions, Bayes' theorem, conditional probability, and
#       expectation/variance — built from first principles.
# WHY: Every ML model this repo covers (from ML Frameworks Notes'
#      scikit-learn/XGBoost/PyTorch through the LLM Quantization Notes'
#      probabilistic sampling) rests on probability theory. This is the
#      mathematical foundation lesson the rest of this domain and much
#      of the repo's ML content assumes.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
A PROBABILITY DISTRIBUTION describes how likely each possible outcome
of a random variable is. DISCRETE distributions (a finite/countable set
of outcomes, e.g. a coin flip, a die roll) assign a probability to EACH
specific outcome (summing to 1 across all outcomes). CONTINUOUS
distributions (outcomes over a continuous range, e.g. a person's
height) use a PROBABILITY DENSITY FUNCTION (PDF) instead — the
probability of any EXACT single value is technically zero; probabilities
are computed over RANGES (the area under the PDF curve between two
values). The NORMAL (Gaussian) distribution is the most common
continuous distribution in ML — many natural phenomena, and
critically, TRAINED NEURAL NETWORK WEIGHTS (this repo's LLM
Quantization & Inference Notes L16 builds NF4 quantization directly on
this observation), are approximately normally distributed.

CONDITIONAL PROBABILITY, written P(A|B), is "the probability of A, GIVEN
that B has already happened" — a fundamentally different quantity than
the unconditional P(A). BAYES' THEOREM relates conditional
probabilities in both directions:
    P(A|B) = P(B|A) * P(A) / P(B)
This lets you INVERT a conditional probability you know into one you
actually need — e.g. given "the probability of a positive test result
GIVEN you have a disease" (often known from clinical trials), Bayes'
theorem computes "the probability you HAVE the disease GIVEN a positive
test result" (what you actually want to know), which are NOT the same
quantity and can differ dramatically, especially for RARE conditions
(a classic, important result called the "base rate fallacy" — even a
highly accurate test can have a surprisingly low probability of a true
positive if the underlying condition is rare).

EXPECTATION (the mean of a distribution, E[X]) and VARIANCE (how spread
out values are around that mean, Var(X) = E[(X - E[X])^2]) are the two
most fundamental SUMMARY STATISTICS of a distribution — directly
underlying concepts like the "expected value" of a loss function in ML
training, and connecting directly to L03's descriptive statistics.

PRODUCTION USE CASE:
A fraud-detection system's alert has a 95% TRUE POSITIVE RATE (catches
95% of actual fraud) and a 2% FALSE POSITIVE RATE (flags 2% of
legitimate transactions incorrectly) — but if only 0.1% of ALL
transactions are actually fraudulent (a realistic, low base rate),
Bayes' theorem reveals that a transaction FLAGGED by this alert is STILL
more likely to be a FALSE POSITIVE than actual fraud — a
counterintuitive, important result directly informing how aggressively
to act on a single alert (e.g. requiring additional verification rather
than auto-blocking) versus how the system's overall accuracy figures
might naively suggest.

COMMON MISTAKES:
- Confusing P(A|B) with P(B|A) — these are GENERALLY DIFFERENT
  quantities (the "prosecutor's fallacy" in legal contexts, the same
  underlying error as misreading a diagnostic test's implications) — a
  test being accurate does NOT mean a positive result is highly likely
  to be a true positive, without accounting for the base rate via Bayes' theorem.
- Ignoring the BASE RATE (the prior probability of the condition/event
  BEFORE any evidence) when interpreting a conditional probability —
  this is EXACTLY the error the fraud-detection example above
  illustrates, and it's a genuinely common, costly misinterpretation in practice.
- Treating expectation (the mean) as sufficient to describe a
  distribution without considering variance — two distributions with
  IDENTICAL means can have wildly different variances (a low-risk,
  consistent outcome vs a high-risk, volatile one), a distinction that
  matters enormously for decision-making under uncertainty.
"""

import math
import random


# ------------------------------------------------------------------
# 1. Discrete vs continuous distributions
# ------------------------------------------------------------------
def discrete_die_distribution() -> dict[int, float]:
    return {face: 1 / 6 for face in range(1, 7)}


def normal_pdf(x: float, mean: float = 0, std: float = 1) -> float:
    """The Gaussian probability DENSITY function — note this is NOT a
    probability itself (it can exceed 1 for narrow distributions);
    probability comes from the AREA under this curve over a range."""
    return (1 / (std * math.sqrt(2 * math.pi))) * math.exp(-0.5 * ((x - mean) / std) ** 2)


def distribution_demo():
    die = discrete_die_distribution()
    print(f"Discrete (die roll): P(roll=3) = {die[3]:.3f}, sums to {sum(die.values()):.3f}")

    print("\nContinuous (standard normal) PDF values (NOT probabilities themselves):")
    for x in [-2, -1, 0, 1, 2]:
        print(f"  PDF(x={x}) = {normal_pdf(x):.4f}")


# ------------------------------------------------------------------
# 2. Bayes' theorem — the base rate fallacy, concretely
# ------------------------------------------------------------------
def bayes_theorem(p_b_given_a: float, p_a: float, p_b: float) -> float:
    """P(A|B) = P(B|A) * P(A) / P(B)"""
    return (p_b_given_a * p_a) / p_b


def fraud_detection_base_rate_demo():
    true_positive_rate = 0.95    # P(flagged | actually fraud)
    false_positive_rate = 0.02   # P(flagged | actually legitimate)
    base_rate_fraud = 0.001       # P(fraud) — only 0.1% of transactions

    # P(flagged) = P(flagged|fraud)*P(fraud) + P(flagged|legit)*P(legit)
    p_flagged = (true_positive_rate * base_rate_fraud +
                 false_positive_rate * (1 - base_rate_fraud))

    p_fraud_given_flagged = bayes_theorem(true_positive_rate, base_rate_fraud, p_flagged)

    print(f"Test accuracy figures: {true_positive_rate:.0%} true positive rate, "
          f"{false_positive_rate:.0%} false positive rate")
    print(f"Base rate of actual fraud: {base_rate_fraud:.1%}")
    print(f"P(actually fraud | flagged) = {p_fraud_given_flagged:.1%}")
    print(f"  -> DESPITE a 95% accurate test, a FLAGGED transaction is "
          f"still fraud only {p_fraud_given_flagged:.1%} of the time — "
          f"because genuine fraud is so RARE, false positives from the "
          f"much larger pool of legitimate transactions dominate.")


# ------------------------------------------------------------------
# 3. Expectation and variance
# ------------------------------------------------------------------
def expectation(values: list[float], probabilities: list[float]) -> float:
    return sum(v * p for v, p in zip(values, probabilities))


def variance(values: list[float], probabilities: list[float]) -> float:
    mean = expectation(values, probabilities)
    return sum(p * (v - mean) ** 2 for v, p in zip(values, probabilities))


def expectation_variance_demo():
    # Two "investments" with the SAME expected value but different variance
    safe_outcomes, safe_probs = [100, 100], [0.5, 0.5]         # always exactly 100
    risky_outcomes, risky_probs = [0, 200], [0.5, 0.5]          # 0 or 200, each 50%

    print(f"Safe option:  E[X]={expectation(safe_outcomes, safe_probs):.1f}, "
          f"Var(X)={variance(safe_outcomes, safe_probs):.1f}")
    print(f"Risky option: E[X]={expectation(risky_outcomes, risky_probs):.1f}, "
          f"Var(X)={variance(risky_outcomes, risky_probs):.1f}")
    print("  -> IDENTICAL expected value, WILDLY different variance — "
          "expectation alone never tells the full story of a distribution's risk/spread.")


if __name__ == "__main__":
    distribution_demo()
    print()
    fraud_detection_base_rate_demo()
    print()
    expectation_variance_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A medical screening program initially auto-refers every patient with a
positive test result for expensive, invasive follow-up testing — after
a Bayes'-theorem-informed analysis (exactly like the fraud-detection
demo above) reveals that, given the condition's low base rate, a
positive result is FAR more often a false positive than a true one, the
program redesigns its protocol to use the positive result as a trigger
for a CHEAPER, second-stage confirmatory test first — directly reducing
unnecessary invasive procedures while still catching genuine cases,
a real, consequential decision informed by correctly applying Bayes'
theorem rather than naively trusting the test's headline accuracy figure.
"""
