# ============================================================
# L09: Online Experimentation for ML — A/B Testing, Sequential Testing,
#      Multi-Armed Bandits
# ============================================================
# WHAT: The statistical rigor behind actually MEASURING whether a new
#       model is better than the current one in production — proper A/B
#       test design, sequential testing (peeking problem and its fix),
#       and multi-armed bandits as a dynamic-allocation alternative to
#       fixed-split A/B tests.
# WHY: L07's model registry covers canary/shadow deployment MECHANICS
#      (how to route traffic). This lesson covers the STATISTICS that
#      determine whether a canary's observed difference is a REAL
#      improvement or just noise — a canary rollout without rigorous
#      statistical evaluation can "prove" a worse model is better,
#      or fail to detect a real improvement, purely from bad experimental design.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
A/B TESTING for ML models means routing a RANDOM subset of traffic to
the NEW (challenger) model and the rest to the CURRENT (champion) model,
then comparing a chosen METRIC (click-through rate, conversion,
prediction accuracy against later-observed ground truth) between the
two groups. The statistical rigor required: a PRE-REGISTERED sample
size (calculated from the expected effect size and desired statistical
power, BEFORE running the test — deciding "how much data do we need to
detect this size of difference reliably" in advance, not after seeing
results) and a SIGNIFICANCE THRESHOLD (commonly p < 0.05) applied
EXACTLY ONCE, at the pre-determined sample size.

THE PEEKING PROBLEM is the single most common statistical error in
practice: checking a test's results REPEATEDLY as data accumulates
("let's peek at today's numbers") and stopping AS SOON AS a result looks
significant — this dramatically INFLATES the actual false-positive rate
beyond the nominal 5%, because each additional peek is another chance
for RANDOM noise to cross the significance threshold by pure chance,
even when there's NO real underlying difference. SEQUENTIAL TESTING
methods (e.g. Sequential Probability Ratio Test, or modern approaches
like "always-valid" confidence sequences) are specifically DESIGNED to
allow legitimate continuous monitoring/early stopping WITHOUT inflating
the false-positive rate — the key difference from naive peeking being
that sequential methods use a STATISTICAL FRAMEWORK that accounts for
the repeated-look structure mathematically, rather than pretending each
look is an independent, one-shot test.

MULTI-ARMED BANDITS are a fundamentally different allocation strategy
from a FIXED-SPLIT A/B test: instead of a static 50/50 (or any fixed
ratio) split maintained for the entire test duration, a bandit algorithm
DYNAMICALLY shifts traffic toward whichever variant is CURRENTLY
performing better, based on accumulating evidence — this minimizes the
total "cost" of running the experiment (less traffic wasted on a clearly
worse variant, once evidence accumulates) at the cost of being
statistically MESSIER to analyze after the fact (the traffic split
itself changed based on the data, which complicates classical
significance testing) — bandits are the right choice when the PRIMARY
goal is maximizing performance DURING the experiment itself (e.g.
revenue-critical ranking decisions), while a classical fixed-split A/B
test is the right choice when the PRIMARY goal is a clean, statistically
rigorous LEARNING outcome you'll act on afterward.

PRODUCTION USE CASE:
A recommendation model's A/B test is pre-registered with a required
sample size of 50,000 users per arm (calculated from the expected 2%
lift and desired 80% statistical power) — the team resists the urge to
declare a winner after 3 days when an early, partial look shows a
promising 3% lift, correctly waiting for the full pre-registered sample,
where the effect settles to a genuine, still-positive but smaller 1.2%
lift — the early "3% lift" would have been a classic peeking-inflated
false read had they stopped there.

COMMON MISTAKES:
- Checking A/B test results daily and stopping as soon as they "look
  significant," instead of committing to a pre-registered sample size
  (or using a genuine sequential testing method designed for legitimate
  early stopping) — this is the single most common statistical error in
  practical A/B testing, and it systematically produces false "wins."
- Running a multi-armed bandit when the actual goal is a clean,
  publishable, statistically rigorous comparison for a stakeholder
  decision — the dynamically-shifting allocation makes classical
  significance testing on bandit data considerably more complex to interpret correctly.
- Not accounting for NOVELTY EFFECTS (users reacting to something simply
  because it's NEW/different, not because it's genuinely better) or
  SEASONALITY (running a test entirely within an atypical time period) —
  both can produce a real, measured effect during the test that doesn't
  persist once the "new" model becomes the new normal.
"""

import math
import random
from dataclasses import dataclass


# ------------------------------------------------------------------
# 1. Pre-registering sample size BEFORE running a test
# ------------------------------------------------------------------
def required_sample_size_per_arm(
    baseline_rate: float, minimum_detectable_effect: float,
    alpha: float = 0.05, power: float = 0.8,
) -> int:
    """
    A simplified sample-size calculation for a two-proportion test —
    computed BEFORE the experiment runs, based on the SMALLEST effect
    size worth detecting, not adjusted after seeing early data.
    """
    p1 = baseline_rate
    p2 = baseline_rate + minimum_detectable_effect
    p_bar = (p1 + p2) / 2

    # z-scores for the given alpha (two-sided) and power — hardcoded for
    # the common alpha=0.05, power=0.8 case to avoid a scipy dependency.
    z_alpha = 1.96
    z_beta = 0.84

    numerator = (z_alpha * math.sqrt(2 * p_bar * (1 - p_bar))
                 + z_beta * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    denominator = (p2 - p1) ** 2
    return math.ceil(numerator / denominator)


# ------------------------------------------------------------------
# 2. The peeking problem, demonstrated empirically
# ------------------------------------------------------------------
def simulate_ab_test_no_real_effect(n_per_arm: int, seed: int) -> list[float]:
    """
    Simulates an A/B test where BOTH arms have the EXACT SAME true
    conversion rate (no real effect exists) — used to empirically
    demonstrate how "peeking" inflates false-positive rate even when
    there's genuinely nothing to detect.
    """
    random.seed(seed)
    true_rate = 0.10
    a_conversions, b_conversions = 0, 0
    p_values_over_time = []

    for i in range(1, n_per_arm + 1):
        a_conversions += 1 if random.random() < true_rate else 0
        b_conversions += 1 if random.random() < true_rate else 0

        # A simplified z-test p-value at THIS point in the accumulating data
        p1, p2 = a_conversions / i, b_conversions / i
        p_pool = (a_conversions + b_conversions) / (2 * i)
        se = math.sqrt(2 * p_pool * (1 - p_pool) / i) if p_pool not in (0, 1) else 1e-9
        z = (p2 - p1) / se if se > 0 else 0
        p_value = 2 * (1 - _normal_cdf(abs(z)))
        p_values_over_time.append(p_value)

    return p_values_over_time


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def peeking_problem_demo():
    false_positive_from_peeking = 0
    false_positive_from_fixed_sample = 0
    num_simulations = 200

    for sim in range(num_simulations):
        p_values = simulate_ab_test_no_real_effect(n_per_arm=1000, seed=sim)
        # PEEKING: stop and declare "significant" the FIRST time p < 0.05
        # anywhere along the way — even though there's NO real effect.
        if any(p < 0.05 for p in p_values[100:]):   # start checking after some warmup
            false_positive_from_peeking += 1
        # FIXED SAMPLE: only look ONCE, at the pre-registered final sample size.
        if p_values[-1] < 0.05:
            false_positive_from_fixed_sample += 1

    print(f"False positive rate WITH peeking (checking repeatedly): "
          f"{false_positive_from_peeking / num_simulations:.1%}  "
          f"(should be ~5% if not inflated — peeking inflates it well above that)")
    print(f"False positive rate with a FIXED, single look at pre-registered "
          f"sample size: {false_positive_from_fixed_sample / num_simulations:.1%}  "
          f"(close to the nominal 5%, as intended)")


# ------------------------------------------------------------------
# 3. Multi-armed bandit — dynamic allocation (epsilon-greedy, simplified)
# ------------------------------------------------------------------
@dataclass
class BanditArm:
    name: str
    true_conversion_rate: float   # unknown to the algorithm, used only for simulation
    successes: int = 0
    trials: int = 0

    @property
    def estimated_rate(self) -> float:
        return self.successes / self.trials if self.trials > 0 else 0.5


def epsilon_greedy_bandit(arms: list[BanditArm], num_rounds: int, epsilon: float = 0.1, seed: int = 0):
    random.seed(seed)
    for _ in range(num_rounds):
        if random.random() < epsilon:
            arm = random.choice(arms)   # EXPLORE: pick a random arm
        else:
            arm = max(arms, key=lambda a: a.estimated_rate)   # EXPLOIT: pick the current best

        arm.trials += 1
        if random.random() < arm.true_conversion_rate:
            arm.successes += 1


def bandit_demo():
    arms = [
        BanditArm("champion_model", true_conversion_rate=0.10),
        BanditArm("challenger_model", true_conversion_rate=0.13),   # genuinely better
    ]
    epsilon_greedy_bandit(arms, num_rounds=5000)
    for arm in arms:
        print(f"  {arm.name}: {arm.trials} trials, estimated rate = {arm.estimated_rate:.3f}")
    print("  -> the bandit AUTOMATICALLY shifted more traffic toward the "
          "genuinely better challenger over time, unlike a fixed 50/50 "
          "A/B split that would have kept sending equal traffic to the "
          "worse arm for the entire test duration.")


if __name__ == "__main__":
    n = required_sample_size_per_arm(baseline_rate=0.10, minimum_detectable_effect=0.02)
    print(f"Required sample size per arm to detect a 2pp lift from a 10% "
          f"baseline (80% power, alpha=0.05): {n:,}")

    print("\n--- Peeking problem demonstration ---")
    peeking_problem_demo()

    print("\n--- Multi-armed bandit demonstration ---")
    bandit_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A search-ranking team uses a multi-armed bandit (not a fixed A/B test)
for an ongoing ranking-algorithm comparison specifically because the
revenue cost of sending traffic to a clearly-worse variant matters more
than obtaining a textbook-clean significance test — while a SEPARATE
model-quality initiative (comparing a new fraud-detection model against
the current one) uses a rigorous, pre-registered fixed-sample A/B test
instead, because that decision will be presented to compliance
stakeholders who need a defensible, classically-interpretable
statistical result, not a dynamically-allocated bandit's messier-to-explain output.
"""
