# ============================================================
# L02: Statistical Inference — Sampling, Confidence Intervals, Hypothesis Testing
# ============================================================
# WHAT: How to draw conclusions about a POPULATION from a SAMPLE —
#       sampling distributions, confidence intervals, hypothesis testing,
#       p-values, and the Central Limit Theorem underlying all of it.
# WHY: This repo's MLOps Notes L09 (online experimentation/A-B testing)
#      already applies hypothesis testing to production experiments —
#      this lesson builds the STATISTICAL FOUNDATION that lesson assumed,
#      from first principles.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
A SAMPLE is a subset of data drawn from a larger POPULATION — since
measuring an entire population is usually infeasible (surveying every
user, testing every possible input), inference lets us draw conclusions
about the population from a sample, WITH QUANTIFIED UNCERTAINTY.

The CENTRAL LIMIT THEOREM (CLT) is the single most important result
underlying almost all classical statistical inference: it states that
the distribution of SAMPLE MEANS (repeatedly draw a sample, compute its
mean, repeat many times) approaches a NORMAL distribution as sample size
grows — REGARDLESS of the shape of the underlying population
distribution. This is what justifies using normal-distribution-based
methods (confidence intervals, many hypothesis tests) even when the
underlying data itself is NOT normally distributed.

A CONFIDENCE INTERVAL (CI) is a RANGE of plausible values for a
population parameter (e.g. the true mean), computed from a sample, with
an associated CONFIDENCE LEVEL (e.g. 95%). Critically, a 95% CI does
NOT mean "there's a 95% probability the true value is in this range" —
it means "if we repeated this sampling process many times, 95% of the
resulting intervals would contain the true value." This distinction is
subtle but genuinely important for correct interpretation.

HYPOTHESIS TESTING formalizes "is this observed difference real, or
could it plausibly be due to random chance alone?" via a NULL HYPOTHESIS
(H0: "no real effect/difference exists") and computing a P-VALUE (the
probability of observing a result AT LEAST as extreme as what was
observed, IF the null hypothesis were actually true). A small p-value
(conventionally < 0.05) suggests the observed result is UNLIKELY under
the null hypothesis, leading to REJECTING H0 — but critically, a p-value
is NOT "the probability the null hypothesis is true," a very common and
important misinterpretation.

PRODUCTION USE CASE:
A/B testing a new checkout flow (this repo's MLOps Notes L09 covers the
production experimentation platform) measures conversion rate on a
SAMPLE of users in each variant — statistical inference (a
confidence interval on the DIFFERENCE in conversion rates, a hypothesis
test's p-value) determines whether an observed 2% lift is a REAL effect
worth rolling out broadly, or plausibly just random noise from the
particular sample of users who happened to see each variant.

COMMON MISTAKES:
- Misinterpreting a p-value as "the probability the null hypothesis is
  true" — it is NOT; it's the probability of the observed data (or more
  extreme) GIVEN the null hypothesis is true, a subtly but importantly
  different conditional probability (directly connecting back to L01's
  P(A|B) vs P(B|A) distinction).
- Misinterpreting a 95% confidence interval as "95% probability the true
  value is in this specific range" — the correct interpretation is about
  the LONG-RUN behavior of the interval-construction PROCEDURE, not a
  probability statement about this one specific interval.
- "P-hacking" — repeatedly testing/peeking at results and stopping as
  soon as p < 0.05 is reached — this INFLATES the true false-positive
  rate far above the nominal 5%, exactly the "peeking problem" this
  repo's MLOps Notes L09 covers in the online-experimentation context.
"""

import math
import random
import statistics


# ------------------------------------------------------------------
# 1. The Central Limit Theorem, demonstrated empirically
# ------------------------------------------------------------------
def central_limit_theorem_demo():
    random.seed(42)
    # The UNDERLYING population is NOT normal — it's heavily skewed
    # (an exponential distribution, e.g. modeling "time between events")
    population_sample = [random.expovariate(1.0) for _ in range(100_000)]

    # Repeatedly draw SMALL samples and compute each sample's mean
    sample_means = []
    for _ in range(1000):
        small_sample = random.sample(population_sample, 30)
        sample_means.append(statistics.mean(small_sample))

    print(f"Underlying population: skewed (exponential), NOT normal")
    print(f"Population mean: {statistics.mean(population_sample):.3f}")
    print(f"Distribution of 1000 SAMPLE MEANS (each from n=30):")
    print(f"  Mean of sample means: {statistics.mean(sample_means):.3f}")
    print(f"  This distribution of MEANS is approximately NORMAL "
          f"(the CLT in action) even though individual observations are NOT.")


# ------------------------------------------------------------------
# 2. Confidence interval for a sample mean
# ------------------------------------------------------------------
def confidence_interval(sample: list[float], confidence: float = 0.95) -> tuple[float, float]:
    n = len(sample)
    mean = statistics.mean(sample)
    std_err = statistics.stdev(sample) / math.sqrt(n)   # standard error of the mean
    # Using 1.96 as the approximate z-score for a 95% CI (large-sample approximation)
    z = 1.96 if confidence == 0.95 else 2.576   # 99% CI uses ~2.576
    margin = z * std_err
    return (mean - margin, mean + margin)


def confidence_interval_demo():
    random.seed(1)
    sample = [random.gauss(50, 10) for _ in range(200)]   # simulated survey responses
    lower, upper = confidence_interval(sample)
    print(f"Sample mean: {statistics.mean(sample):.2f}")
    print(f"95% CI: ({lower:.2f}, {upper:.2f})")
    print("  -> Correct interpretation: IF we repeated this sampling "
          "process many times, 95% of such intervals would contain the "
          "TRUE population mean — NOT 'there's a 95% chance the true "
          "mean is in THIS specific interval.'")


# ------------------------------------------------------------------
# 3. Hypothesis testing — a simple two-sample test
# ------------------------------------------------------------------
def two_sample_t_test_statistic(sample_a: list[float], sample_b: list[float]) -> float:
    """A simplified two-sample t-statistic (Welch's approximation)."""
    mean_a, mean_b = statistics.mean(sample_a), statistics.mean(sample_b)
    var_a, var_b = statistics.variance(sample_a), statistics.variance(sample_b)
    n_a, n_b = len(sample_a), len(sample_b)
    pooled_se = math.sqrt(var_a / n_a + var_b / n_b)
    return (mean_a - mean_b) / pooled_se


def ab_test_demo():
    random.seed(7)
    # Control: existing checkout flow. Treatment: new checkout flow.
    control_conversions = [random.gauss(0.10, 0.02) for _ in range(500)]
    treatment_conversions = [random.gauss(0.12, 0.02) for _ in range(500)]  # a real 2% lift

    t_stat = two_sample_t_test_statistic(treatment_conversions, control_conversions)
    print(f"Control mean conversion: {statistics.mean(control_conversions):.3f}")
    print(f"Treatment mean conversion: {statistics.mean(treatment_conversions):.3f}")
    print(f"t-statistic: {t_stat:.2f}")
    print(f"  -> A t-statistic this large (roughly |t| > 2) suggests the "
          f"observed difference is UNLIKELY to be due to random sampling "
          f"noise alone — evidence AGAINST the null hypothesis of 'no real difference.'")
    print("  -> IMPORTANT: this p-value is NOT 'the probability H0 is "
          "true' — it's 'the probability of seeing a difference this "
          "large or larger, IF H0 (no real difference) were actually true.'")


if __name__ == "__main__":
    central_limit_theorem_demo()
    print()
    confidence_interval_demo()
    print()
    ab_test_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
An experimentation platform (this repo's MLOps Notes L09) that lets
product teams launch A/B tests enforces a MINIMUM sample size and a
FIXED analysis time (rather than allowing teams to "peek" at results
daily and stop as soon as significance is reached) — directly because
the platform's statisticians know that repeated peeking, without a
correction like sequential testing, inflates the true false-positive
rate far above the intended 5%, turning what looks like a rigorous
statistical process into one that reliably ships false "wins."
"""
