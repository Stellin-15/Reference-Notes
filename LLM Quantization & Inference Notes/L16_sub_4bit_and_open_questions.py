# ============================================================
# L16: Sub-4-Bit Quantization, NF4, and Open Research Questions
# ============================================================
# WHAT: NF4 (QLoRA's custom 4-bit data type, derived from information
#       theory rather than uniform integer quantization), ternary/1-bit
#       weight schemes (BitNet-style), and a survey of what's still
#       genuinely UNSOLVED in this field — the section most directly
#       useful for finding your own paper topic.
# WHY (RESEARCH): This is the "frontier" lesson — everything before this
#      was reproducing established, published, largely-settled techniques.
#      This lesson is deliberately about what's STILL OPEN, because that's
#      where your own research contribution has to live.
# LEVEL: Advanced / Research Frontier (Phase 4 of 8 — final lesson)
# ============================================================

"""
CONCEPT OVERVIEW:
NF4 (NormalFloat4, from the QLoRA paper) is built on an information-
theoretic argument: standard INT4 quantization places its 16 representable
values UNIFORMLY across the value range. But pretrained transformer
weights are empirically very close to a ZERO-CENTERED NORMAL (Gaussian)
distribution — meaning most weight VALUES cluster near zero, and uniform
quantization "wastes" many of its 16 representable levels on the sparsely-
populated tails. NF4 instead places its 16 levels at the QUANTILES of a
standard normal distribution — this means each of the 16 representable
values covers an EQUAL AMOUNT OF PROBABILITY MASS (not equal numeric
range), which is information-theoretically optimal FOR a Gaussian-
distributed input, in the sense of minimizing expected quantization error
under that distribution.

Sub-4-bit and 1-bit/ternary schemes (BitNet, BitNet b1.58) push further:
BitNet b1.58 restricts weights to exactly THREE values: {-1, 0, +1}
(hence "1.58 bits" = log2(3)). Critically, these are usually TRAINED THIS
WAY FROM SCRATCH (a QAT-style approach, not PTQ applied to an existing
model) — because compressing an ALREADY-TRAINED model down to 3 possible
weight values via PTQ loses far too much information; the model needs to
learn to represent its knowledge using only 3 discrete weight values in
the first place.

WHAT'S GENUINELY OPEN (as of this writing, and likely to remain a live
research area):
  - Extreme sub-2-bit PTQ (compressing an already-trained model, not
    training ternary from scratch) still has a large, not-fully-closed
    accuracy gap versus full precision on many tasks.
  - There is no universally agreed-upon THEORY predicting, from a model's
    architecture/training alone, its "quantizability" at a given bit-width
    — current practice is still largely empirical (try it, measure it).
  - Hardware support for genuinely sub-4-bit (2-bit, ternary) matmul
    kernels is immature relative to INT4/INT8 — a method can be
    "algorithmically" sub-4-bit while still being SLOWER in practice than
    a well-optimized INT4 kernel, because the hardware/kernel ecosystem
    hasn't caught up (a systems problem, not just an algorithms problem
    — directly connects to Phase 5).
  - How quantization error compounds across a MULTI-STEP agentic/chain-
    of-thought inference process (rather than single-turn QA, the
    standard benchmark setting) is comparatively under-studied.

PRODUCTION/RESEARCH USE CASE:
This is the lesson where "what should I actually try to publish" starts
to have concrete candidate answers — e.g. characterizing how quantization
error compounds through multi-step reasoning chains is a genuinely
underexplored, well-scoped, and currently-relevant research question you
could pursue with the exact tooling this curriculum builds.

COMMON MISTAKES:
- Treating "fewer bits is strictly better research" — a paper proposing
  a NEW 3-bit scheme that's slower in practice (due to missing kernel
  support) and only marginally more accurate than a well-tuned existing
  4-bit method is not automatically a meaningful contribution; the
  RESEARCH QUESTION has to be well-motivated, not just "smaller number."
- Assuming NF4's Gaussian-quantile placement generalizes to ALL tensors —
  it's specifically motivated by pretrained WEIGHT distributions; applying
  the same fixed quantile grid to activations (which have very different,
  often multi-modal or heavy-tailed distributions) is not automatically
  well-justified without re-deriving the argument.
- Reproducing an existing paper's numbers and stopping there — a
  reproduction alone is valuable practice but is not, by itself, a novel
  contribution; the actual research step is asking "what does this NOT
  explain" or "where does this break" and investigating that.
"""

import math
import torch


# ------------------------------------------------------------------
# 1. NF4 — quantile-based quantization for Gaussian-distributed weights
# ------------------------------------------------------------------
def normal_quantiles(num_levels: int) -> list[float]:
    """
    Computes the quantile positions of a standard normal distribution
    that split it into `num_levels` equal-probability-mass regions,
    returning the MIDPOINT (in probability, mapped back to value space)
    of each region — these become the fixed, non-uniform representable
    values NF4 uses. Uses an inverse-CDF approximation (erfinv) rather
    than depending on scipy, so this stays runnable with just Python/math.
    """
    def norm_inv_cdf(p: float) -> float:
        # Acklam's algorithm approximation for the inverse normal CDF —
        # accurate enough for this illustration; production code would
        # use a vetted implementation (e.g. scipy.stats.norm.ppf).
        return math.sqrt(2) * _erfinv(2 * p - 1)

    def _erfinv(x: float) -> float:
        # A standard rational approximation of the inverse error function.
        a = 0.147
        ln1mx2 = math.log(1 - x ** 2)
        term1 = 2 / (math.pi * a) + ln1mx2 / 2
        term2 = ln1mx2 / a
        return math.copysign(math.sqrt(math.sqrt(term1 ** 2 - term2) - term1), x)

    # Quantile BOUNDARIES splitting probability mass into num_levels
    # equal chunks, then take the midpoint of each chunk in value space.
    boundaries = [i / num_levels for i in range(num_levels + 1)]
    values = []
    for i in range(num_levels):
        mid_p = (boundaries[i] + boundaries[i + 1]) / 2
        mid_p = min(max(mid_p, 1e-6), 1 - 1e-6)  # avoid the infinite tails
        values.append(norm_inv_cdf(mid_p))
    return values


def nf4_quantize(values: torch.Tensor, levels: list[float]) -> torch.Tensor:
    """
    Standard weights are first NORMALIZED to unit variance (matching the
    standard-normal assumption the NF4 levels were derived for), then
    each value is mapped to its NEAREST representable level — a lookup
    against a small fixed table, not a uniform round-to-grid operation.
    """
    std = values.std().clamp(min=1e-8)
    normalized = values / std
    levels_tensor = torch.tensor(levels)

    # Nearest-level lookup: for each value, find the closest of the 16
    # (or however many) fixed levels — implemented as a brute-force
    # distance comparison for clarity (a real kernel would use a much
    # faster bucketed/binary search given the levels are sorted).
    distances = (normalized.unsqueeze(-1) - levels_tensor).abs()
    nearest_idx = distances.argmin(dim=-1)
    quantized = levels_tensor[nearest_idx] * std
    return quantized, nearest_idx


def compare_nf4_vs_uniform_int4():
    torch.manual_seed(0)
    # Genuinely Gaussian-distributed weights, matching NF4's design assumption.
    weights = torch.randn(2000) * 0.02

    nf4_levels = normal_quantiles(16)
    nf4_result, _ = nf4_quantize(weights, nf4_levels)
    nf4_mse = (weights - nf4_result).pow(2).mean().item()

    qmax = 7  # 4-bit symmetric
    scale = weights.abs().max() / qmax
    uniform_result = (weights / scale).round().clamp(-qmax, qmax) * scale
    uniform_mse = (weights - uniform_result).pow(2).mean().item()

    print(f"NF4 (quantile-based) MSE:      {nf4_mse:.8f}")
    print(f"Uniform INT4 MSE:               {uniform_mse:.8f}")
    print(f"NF4 improvement: {(1 - nf4_mse / uniform_mse) * 100:.1f}% lower error "
          f"(on genuinely Gaussian data)")
    # This gap should be REAL but modest for a clean Gaussian — the
    # advantage grows on REAL model weights, which are even MORE
    # concentrated near zero than a plain Gaussian in many trained
    # layers, an empirical claim worth verifying yourself on real
    # checkpoints as a research exercise.


# ------------------------------------------------------------------
# 2. Ternary (BitNet-style) weights — the extreme end of the spectrum
# ------------------------------------------------------------------
def ternary_quantize(weights: torch.Tensor, threshold_ratio: float = 0.5) -> torch.Tensor:
    """
    Maps every weight to exactly one of {-1, 0, +1}, scaled by a single
    learned/computed scale factor. This simplified version (absmean
    thresholding) mirrors BitNet's actual approach: a weight is 0 if its
    magnitude is below `threshold_ratio` times the mean absolute weight,
    otherwise it takes the sign of the original value.
    """
    scale = weights.abs().mean()
    threshold = threshold_ratio * scale
    ternary = torch.zeros_like(weights)
    ternary[weights > threshold] = 1.0
    ternary[weights < -threshold] = -1.0
    return ternary * scale, ternary


def ternary_bits_per_weight() -> float:
    # log2(3) — the information-theoretic minimum bits to distinguish 3
    # equally-likely outcomes; this is where "1.58-bit" comes from.
    return math.log2(3)


if __name__ == "__main__":
    print("Comparing NF4 vs uniform INT4 on Gaussian weights:")
    compare_nf4_vs_uniform_int4()

    print(f"\nTernary weight information content: {ternary_bits_per_weight():.4f} bits/weight")

    torch.manual_seed(0)
    w = torch.randn(1000) * 0.03
    ternary_result, ternary_codes = ternary_quantize(w)
    mse = (w - ternary_result).pow(2).mean().item()
    zero_fraction = (ternary_codes == 0).float().mean().item()
    print(f"Ternary quantization MSE: {mse:.6f}  "
          f"(zero fraction: {zero_fraction:.2%} — sparsity is 'free' compression too)")

    print("\nOpen research questions to consider pursuing:")
    for q in [
        "How does quantization error compound across multi-step agentic/CoT inference?",
        "Can a 'quantizability' metric be predicted from architecture/training curves"
        " BEFORE quantizing, instead of only measured after?",
        "What is the actual measured speedup ceiling for sub-4-bit on CURRENT"
        " consumer GPU kernels, separating algorithmic gains from kernel immaturity?",
        "Do RLHF/instruction-tuned models degrade differently under quantization"
        " than their base pretrained counterparts, and why?",
    ]:
        print(f"  - {q}")

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
A concrete, tractable first paper project matching your stated goals:
take a small (1-3B parameter) open model, quantize it with GPTQ, AWQ, and
NF4 at matched bit-widths, and measure how the accuracy gap between
methods CHANGES as you increase the number of sequential reasoning steps
in a benchmark (e.g. multi-step math word problems) — this is novel
(the "open question" flagged above), reproducible with the exact tooling
built across L09-L16, and small enough in scope to actually finish and
write up, which matters far more for a first paper than picking the most
ambitious possible topic.
"""
