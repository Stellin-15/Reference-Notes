# ============================================================
# L07: Scaling Laws — Why Model Size, Data, and Compute Trade Off
# ============================================================
# WHAT: The empirical power-law relationships (Kaplan et al. 2020,
#       Chinchilla/Hoffmann et al. 2022) between model size, dataset
#       size, compute budget, and achievable loss — and how to actually
#       read/reproduce a scaling-law plot yourself.
# WHY (RESEARCH): This is the first genuinely "research paper" lesson in
#      the curriculum — scaling laws are THE example of empirical science
#      done well in ML: fit a functional form to swept experiments, then
#      use it to make PREDICTIONS you can verify. This is the exact
#      research methodology you'll need in Phase 7 to publish anything.
# LEVEL: Intermediate (Phase 2 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
A "scaling law" is an empirical finding that loss L, as a function of
model parameters N, dataset tokens D, or compute C, follows an approximate
power law: L(N) ≈ (N_c / N)^alpha_N, and similarly for D and C. Plotted
on a LOG-LOG axis, a power law is a STRAIGHT LINE — this is why every
scaling-law paper's key figure is a log-log plot; if the points fall on a
line, you've found (or at least strongly suggested) a power-law relationship.

The Kaplan et al. (2020) scaling laws suggested that for a FIXED compute
budget, you should scale model size much faster than dataset size — this
led directly to very large, undertrained models like GPT-3.

The Chinchilla paper (Hoffmann et al., 2022) re-ran the analysis more
carefully and found the OPPOSITE conclusion was closer to optimal: for a
fixed compute budget, model size and dataset size should scale
APPROXIMATELY EQUALLY. This single correction changed how the entire
field trains large models — "Chinchilla-optimal" became the standard
target ratio (roughly 20 tokens of training data per parameter).

PRODUCTION/RESEARCH USE CASE:
When you write your own paper on a novel quantization method (Phase 7),
you'll likely need to argue something like "quantization error scales
predictably with X" — the METHODOLOGY here (sweep a variable across
multiple orders of magnitude, plot log-log, fit a power law, check
residuals) is directly transferable to characterizing how quantization
error behaves as a function of bit-width, model size, or calibration
set size.

COMMON MISTAKES:
- Fitting a power law to too NARROW a range of the swept variable — power
  laws are most convincing (and most likely to actually be a real
  underlying law, not curve-fitting noise) when they hold across several
  orders of magnitude, not just a 2x range.
- Confusing "compute-optimal" (the best loss for a FIXED compute budget)
  with "inference-optimal" — Chinchilla's original result optimizes
  TRAINING compute only. If you'll run the model billions of times at
  inference, it's often worth training a SMALLER model on MORE data than
  Chinchilla-optimal would suggest, since inference cost dominates total
  lifetime cost — a distinction that directly affects real deployment
  decisions and is a common source of confusion when people cite
  "Chinchilla-optimal" as if it were a universal rule.
- Ignoring that scaling laws are EMPIRICAL FITS, not physical laws — they
  can and do break down outside the regime they were measured in (very
  small or very large scales, different data distributions).
"""

import math


# ------------------------------------------------------------------
# 1. The Chinchilla-style parametric loss model
# ------------------------------------------------------------------
def chinchilla_loss(N: float, D: float,
                     E: float = 1.69, A: float = 406.4, B: float = 410.7,
                     alpha: float = 0.34, beta: float = 0.28) -> float:
    """
    L(N, D) = E + A/N^alpha + B/D^beta

    - E: the IRREDUCIBLE loss — the entropy of natural language itself;
      no amount of scale drives loss below this floor.
    - A/N^alpha: the loss reduction from more PARAMETERS.
    - B/D^beta: the loss reduction from more TRAINING DATA (tokens).

    (Constants shown are the paper's fitted values, in nats — this
    function reproduces the actual published Chinchilla formula so you
    can explore its predictions directly.)
    """
    return E + A / (N ** alpha) + B / (D ** beta)


# ------------------------------------------------------------------
# 2. Compute-optimal allocation — given a compute budget, what N and D?
# ------------------------------------------------------------------
def compute_optimal_allocation(compute_budget_flops: float) -> tuple[float, float]:
    """
    Approximates Chinchilla's headline result: for a fixed compute
    budget C (in FLOPs), the loss-minimizing (N, D) pair scales such
    that N and D grow at roughly the SAME RATE as C increases — in
    practice this comes out to approximately N ≈ D / 20 (i.e. ~20
    training tokens per parameter), a ratio you'll see cited constantly
    in model cards and papers.

    C ≈ 6 * N * D is the standard approximation for training FLOPs
    (forward + backward pass cost, ignoring optimizer overhead) — this
    itself is worth knowing since it's used everywhere to back-compute
    training cost from (N, D) or vice versa.
    """
    # Solve C = 6*N*D subject to the empirical optimal ratio D ≈ 20*N:
    #   C = 6*N*(20*N) = 120*N^2  =>  N = sqrt(C/120)
    N_optimal = math.sqrt(compute_budget_flops / 120)
    D_optimal = 20 * N_optimal
    return N_optimal, D_optimal


# ------------------------------------------------------------------
# 3. Fitting a power law to synthetic swept data — the actual research skill
# ------------------------------------------------------------------
def fit_power_law_log_log(x_values: list[float], y_values: list[float]) -> tuple[float, float]:
    """
    Given swept (x, y) pairs believed to follow y = a * x^b, fits `a` and
    `b` via LINEAR regression on the LOG-LOG transformed data:
        log(y) = log(a) + b * log(x)
    This is exactly the "take logs, fit a line" technique underlying
    every scaling-law figure — implemented here with plain least squares
    so the mechanism is fully visible, not hidden behind a library call.
    """
    log_x = [math.log(x) for x in x_values]
    log_y = [math.log(y) for y in y_values]
    n = len(log_x)

    mean_x = sum(log_x) / n
    mean_y = sum(log_y) / n

    numerator = sum((lx - mean_x) * (ly - mean_y) for lx, ly in zip(log_x, log_y))
    denominator = sum((lx - mean_x) ** 2 for lx in log_x)
    b = numerator / denominator          # the power-law EXPONENT
    log_a = mean_y - b * mean_x
    a = math.exp(log_a)                   # the power-law COEFFICIENT
    return a, b


def demo_power_law_fit():
    # Synthetic "loss vs model size" sweep following L(N) = 500 * N^-0.3,
    # with a bit of noise — mimics what a real scaling-law experiment's
    # raw data points look like before fitting.
    import random
    random.seed(0)
    true_a, true_b = 500.0, -0.3
    N_values = [1e6, 3e6, 1e7, 3e7, 1e8, 3e8, 1e9]
    L_values = [true_a * (N ** true_b) * (1 + random.uniform(-0.02, 0.02))
                for N in N_values]

    fitted_a, fitted_b = fit_power_law_log_log(N_values, L_values)
    print(f"true:    a={true_a:.2f}  b={true_b:.4f}")
    print(f"fitted:  a={fitted_a:.2f}  b={fitted_b:.4f}")
    # A good fit recovers `b` (the exponent) very closely — the exponent
    # is the scientifically meaningful number (it tells you the RATE of
    # returns to scale), while `a` is mostly a units/offset artifact.


if __name__ == "__main__":
    print("Chinchilla loss at various (N, D):")
    for N, D in [(1e9, 2e10), (7e9, 1.4e11), (70e9, 1.4e12)]:
        loss = chinchilla_loss(N, D)
        print(f"  N={N:.0e}  D={D:.0e}  ->  loss={loss:.4f} nats")

    print("\nCompute-optimal allocation for a few compute budgets:")
    for flops in (1e21, 1e22, 1e23):
        N_opt, D_opt = compute_optimal_allocation(flops)
        print(f"  C={flops:.0e} FLOPs  ->  N*={N_opt:.2e} params  D*={D_opt:.2e} tokens")

    print()
    demo_power_law_fit()

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
A recent line of quantization research explicitly asks "how does the
LOSS-OPTIMAL bit-width change as model size grows?" — framed as a
scaling-law question in exactly this style: sweep model size at several
fixed bit-widths, plot the resulting loss curves, and see whether
lower-bit-width models become relatively MORE or LESS competitive as
scale increases. Being able to design and execute that exact experiment
(and fit/interpret the resulting curves) is the direct payoff of this
lesson, and it is genuinely publishable-paper-shaped work if you carry it
through rigorously.
"""
