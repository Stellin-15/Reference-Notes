# ============================================================
# L23: Reading Papers Critically and Reproducing Results Honestly
# ============================================================
# WHAT: A concrete methodology for reading a quantization/systems paper
#       (what to extract, what to be skeptical of), plus a real,
#       runnable statistical framework for reproducing a claimed result
#       and knowing whether your reproduction actually agrees or not.
# WHY (RESEARCH): Nearly every quantization paper you'll cite in your own
#      work needs to be reproduced (fully or partially) to build on
#      confidently — "the paper reports X" is not the same epistemic
#      status as "I reproduced X and it held." This lesson is the
#      methodological backbone for Phase 4's papers and your own future work.
# LEVEL: Research Methods (Phase 7 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
Reading a paper CRITICALLY means extracting, in order:
  1. The CLAIM — stated precisely, not the marketing summary. "Our
     method achieves near-lossless 4-bit quantization" is not precise;
     "perplexity increases by <0.5 on WikiText-2 for LLaMA-7B at 4-bit"
     is precise and checkable.
  2. The EVALUATION PROTOCOL — exactly which benchmark, dataset split,
     model, calibration set size/composition, and metric. Two papers
     both claiming "4-bit, near-lossless" on different protocols are NOT
     directly comparable, even if their headline numbers look similar.
  3. The BASELINE — what exactly is the comparison point? A paper
     beating a WEAK baseline (e.g. an outdated or poorly-tuned prior
     method) is a much less impressive result than beating a strong,
     well-tuned one — check whether the baseline numbers match what
     OTHER papers report for the same baseline method.
  4. WHAT'S NOT SHOWN — ablations the paper conspicuously doesn't run,
     bit-widths/model sizes it doesn't test, failure cases mentioned only
     briefly in an appendix. This is often where a paper's real
     limitations live.

REPRODUCING a result rigorously means: (a) matching the evaluation
protocol as closely as possible, (b) running enough trials/seeds to
distinguish a real effect from noise, (c) reporting your reproduction's
UNCERTAINTY (not just a single number), and (d) being honest when your
reproduction DISAGREES — a failed reproduction is itself a valuable,
reportable finding, not a personal failure to hide.

PRODUCTION/RESEARCH USE CASE:
Before building on any quantization method in your own work (Phase 8's
capstone, or a future paper), reproduce its CORE claimed result on a
model/setup you control. This catches: (a) implementation details the
paper glossed over, (b) whether the effect generalizes beyond the
paper's specific tested model, and (c) genuine bugs in your own
implementation, before they contaminate anything built on top.

COMMON MISTAKES:
- Comparing your single-run reproduction number against the paper's
  reported number and declaring "close enough" or "doesn't match"
  without any notion of statistical significance — a difference of 0.3
  perplexity points might be well within normal run-to-run noise, or
  might be a real, meaningful gap, and you cannot tell which without
  actually measuring variance across multiple runs/seeds.
- Cherry-picking the calibration set or evaluation subset to make your
  reproduction match — if your numbers only agree on a SPECIFIC subset
  you happened to choose, that's a red flag, not a successful
  reproduction.
- Reproducing a paper's TABLE NUMBERS without reproducing its
  METHODOLOGY — e.g. getting a similar final perplexity through a
  DIFFERENT quantization procedure than the one described doesn't
  actually validate the paper's specific technical claim.
"""

import math
import random


# ------------------------------------------------------------------
# 1. A paper-reading extraction template — fill this in for every paper
# ------------------------------------------------------------------
PAPER_EXTRACTION_TEMPLATE = {
    "claim": "e.g. '4-bit weight-only quantization with group_size=128 "
             "achieves <0.3 perplexity increase on WikiText-2 for models "
             "7B-70B parameters'",
    "evaluation_protocol": "exact dataset, split, model checkpoints, "
                            "calibration set size/source, metric definition",
    "baseline_comparison": "what method(s) is this compared against, and "
                            "do those baseline numbers match OTHER papers' "
                            "reports for the same baseline",
    "compute_cost_reported": "how expensive is the method itself to run "
                              "(quantization time, memory during "
                              "quantization) — often under-reported "
                              "relative to inference-time benefits",
    "what_is_not_tested": "bit-widths, model families, task types, or "
                           "scales the paper does NOT evaluate — read the "
                           "limitations section AND infer from what's "
                           "simply absent from tables",
    "reproducibility_artifacts": "is code/checkpoints released? does the "
                                  "paper specify EVERY hyperparameter "
                                  "needed to reproduce, or are some left "
                                  "implicit/default-assumed",
}


# ------------------------------------------------------------------
# 2. Statistical rigor for comparing your reproduction against a claim
# ------------------------------------------------------------------
def run_multiple_seeds(experiment_fn, num_seeds: int = 5) -> list[float]:
    """
    Runs an experiment function across multiple random seeds — the bare
    minimum for distinguishing a real effect from noise. A single run
    tells you almost nothing about how reliable that number is.
    """
    results = []
    for seed in range(num_seeds):
        random.seed(seed)
        results.append(experiment_fn(seed))
    return results


def mean_and_confidence_interval(values: list[float], confidence: float = 0.95) -> tuple[float, float]:
    """
    Returns (mean, half-width of the confidence interval) using a
    t-distribution approximation for small samples — this is the actual
    number you should report, not a bare mean, whenever you have fewer
    than ~30 samples (essentially always true for expensive LLM
    experiments, where each run might cost real GPU-hours).
    """
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1) if n > 1 else 0.0
    std_err = math.sqrt(variance / n) if n > 1 else 0.0

    # Approximate t-critical values for common small sample sizes at 95%
    # confidence — a real implementation would use scipy.stats.t.ppf;
    # this table covers the common case without an external dependency.
    t_table_95 = {2: 12.71, 3: 4.30, 4: 3.18, 5: 2.78, 10: 2.26, 30: 2.04}
    t_crit = min((t_table_95[k] for k in sorted(t_table_95) if k >= n), default=1.96)

    margin = t_crit * std_err
    return mean, margin


def is_reproduction_consistent(
    your_mean: float, your_margin: float,
    paper_reported_value: float,
) -> bool:
    """
    A simple, honest consistency check: does the paper's reported value
    fall WITHIN your confidence interval? If not, either (a) your
    reproduction has a real bug/methodology mismatch worth investigating,
    or (b) the paper's result doesn't generalize to your specific setup
    — BOTH are worth reporting, not hiding.
    """
    return abs(your_mean - paper_reported_value) <= your_margin


# ------------------------------------------------------------------
# 3. A worked example: "reproducing" a toy quantization-error claim
# ------------------------------------------------------------------
def toy_quantization_experiment(seed: int) -> float:
    """Simulates measuring quantization MSE with run-to-run variance
    (e.g. from different random calibration subsets)."""
    random.seed(seed)
    values = [random.gauss(0, 0.02) for _ in range(1000)]
    qmax = 7
    scale = max(abs(v) for v in values) / qmax
    quantized = [round(v / scale) * scale for v in values]
    mse = sum((v - q) ** 2 for v, q in zip(values, quantized)) / len(values)
    return mse


def reproduction_worked_example():
    claimed_mse = 0.0000031  # a hypothetical "paper-reported" value

    results = run_multiple_seeds(toy_quantization_experiment, num_seeds=10)
    mean, margin = mean_and_confidence_interval(results, confidence=0.95)

    print(f"Your reproduction: {mean:.7f} +/- {margin:.7f} (95% CI)")
    print(f"Paper's reported value: {claimed_mse:.7f}")
    consistent = is_reproduction_consistent(mean, margin, claimed_mse)
    print(f"Consistent with paper's claim: {consistent}")

    if not consistent:
        print("  -> Worth investigating: different random seed handling? "
              "different calibration data distribution? an actual "
              "implementation discrepancy? Report this gap explicitly "
              "rather than silently adjusting your method until numbers "
              "match — the DISCREPANCY ITSELF may be the interesting finding.")


if __name__ == "__main__":
    print("=== Paper extraction template ===")
    for field_name, description in PAPER_EXTRACTION_TEMPLATE.items():
        print(f"  {field_name}: {description}")

    print("\n=== Worked reproduction example ===")
    reproduction_worked_example()

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
When you reproduce GPTQ's core claim from L12 on a real model, run it
across at least 3-5 different calibration set SAMPLES (not just different
random seeds for the quantization math, but genuinely different subsets
of calibration text) and report the perplexity CONFIDENCE INTERVAL, not a
single number — this is exactly the standard a peer reviewer would expect
if you cited GPTQ's numbers as a baseline in your own paper's comparison
table, and building this habit now, on reproductions, makes it automatic
when it matters for original work.
"""
