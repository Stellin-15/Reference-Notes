# ============================================================
# L09: Quantization Mathematics — Scale, Zero-Point, and Error
# ============================================================
# WHAT: The actual math of mapping a real-valued tensor to a low-bit
#       integer representation and back: scale factors, zero-points,
#       symmetric vs asymmetric quantization, and how to measure
#       quantization error rigorously.
# WHY: Every quantization METHOD you'll study in Phase 4 (GPTQ, AWQ,
#      SmoothQuant, GGUF) is a different strategy for CHOOSING the scale
#      factors and handling outliers — but they all reduce to this exact
#      underlying math. Get this lesson solid and every subsequent paper
#      becomes "which specific variant of this," not new math each time.
# LEVEL: Core (Phase 3 of 8 — Quantization Fundamentals)
# ============================================================

"""
CONCEPT OVERVIEW:
Quantization maps a real number x to an integer q via:
    q = round(x / scale) + zero_point
And dequantizes back via:
    x_approx = (q - zero_point) * scale

SYMMETRIC quantization fixes zero_point = 0 — the real value 0.0 always
maps EXACTLY to integer 0, and the representable range is symmetric
around zero ([-max_val, +max_val]). This is simpler and is what's almost
always used for WEIGHTS, whose distributions are typically roughly
zero-centered.

ASYMMETRIC quantization allows zero_point != 0, letting the quantization
range shift to match a non-zero-centered distribution — this is common
for ACTIVATIONS after a ReLU (which are always >= 0, so a symmetric range
would waste half the integer range representing negative numbers that
never occur).

The SCALE factor is the single most important choice: scale = range / (2^bits - 1).
A scale that's too large wastes precision (many values round to the
same integer); too small and OUTLIERS clip (saturate at the min/max
representable integer), which is often WORSE than rounding error because
clipping introduces a large, biased error rather than small, ~zero-mean
rounding noise.

PRODUCTION/RESEARCH USE CASE:
When reproducing a paper's reported "quantization error" numbers, you
MUST use the exact same error metric they used — MSE (mean squared
error) penalizes large individual errors much more than MAE (mean
absolute error), so two papers reporting "lower error" might not even be
optimizing for the same thing. This lesson's error-measurement code is
the actual instrument you'll use to verify a quantization scheme you
implement in Phase 4 works as claimed, before trusting any downstream
task-accuracy number.

COMMON MISTAKES:
- Using symmetric quantization on a distribution that isn't zero-centered
  (e.g. post-ReLU activations) — this wastes half your integer range on
  negative values that never occur, effectively halving your usable
  precision for no reason.
- Computing quantization error on RANDOM data instead of REAL
  weight/activation distributions — quantization error behavior is highly
  distribution-dependent; a scheme that looks fine on a uniform random
  tensor can fail badly on the actual heavy-tailed distributions LLM
  weights/activations exhibit.
- Forgetting to CLAMP after rounding — `round(x/scale)` can produce a
  value outside the representable integer range for outliers; without an
  explicit clamp, this "wraps around" or produces an invalid value
  depending on the integer type, a silent correctness bug.
"""

import math


# ------------------------------------------------------------------
# 1. Symmetric quantization
# ------------------------------------------------------------------
def symmetric_quantize(values: list[float], num_bits: int) -> tuple[list[int], float]:
    """
    Maps values into the range [-(2^(bits-1)-1), 2^(bits-1)-1], e.g. for
    INT8: [-127, 127] (NOT -128 to 127 — many implementations sacrifice
    one representable value to keep the range perfectly symmetric,
    simplifying dequantization at negligible cost).
    """
    qmax = 2 ** (num_bits - 1) - 1
    max_abs = max(abs(v) for v in values)
    scale = max_abs / qmax if max_abs > 0 else 1.0

    quantized = [max(-qmax, min(qmax, round(v / scale))) for v in values]
    return quantized, scale


def symmetric_dequantize(quantized: list[int], scale: float) -> list[float]:
    return [q * scale for q in quantized]


# ------------------------------------------------------------------
# 2. Asymmetric quantization
# ------------------------------------------------------------------
def asymmetric_quantize(values: list[float], num_bits: int) -> tuple[list[int], float, int]:
    """
    Maps [min(values), max(values)] onto [0, 2^bits - 1]. The zero_point
    is chosen so that the REAL value 0.0 maps to an EXACT integer — this
    matters because operations like zero-padding rely on 0.0 being
    representable WITHOUT rounding error (an approximate zero would
    silently corrupt padding-dependent computations).
    """
    qmax = 2 ** num_bits - 1
    v_min, v_max = min(values), max(values)
    scale = (v_max - v_min) / qmax if v_max > v_min else 1.0
    zero_point = round(-v_min / scale)
    zero_point = max(0, min(qmax, zero_point))  # clamp into valid integer range

    quantized = [max(0, min(qmax, round(v / scale) + zero_point)) for v in values]
    return quantized, scale, zero_point


def asymmetric_dequantize(quantized: list[int], scale: float, zero_point: int) -> list[float]:
    return [(q - zero_point) * scale for q in quantized]


# ------------------------------------------------------------------
# 3. Measuring quantization error rigorously
# ------------------------------------------------------------------
def mse(original: list[float], reconstructed: list[float]) -> float:
    return sum((o - r) ** 2 for o, r in zip(original, reconstructed)) / len(original)


def mae(original: list[float], reconstructed: list[float]) -> float:
    return sum(abs(o - r) for o, r in zip(original, reconstructed)) / len(original)


def signal_to_quantization_noise_ratio(original: list[float], reconstructed: list[float]) -> float:
    """
    SQNR, in dB: 10 * log10(signal_power / noise_power). This is the
    standard metric in the quantization LITERATURE (borrowed from signal
    processing) for reporting how much "information" survives
    quantization relative to the error introduced — higher is better,
    and it's scale-invariant in a way raw MSE is not, making it more
    comparable across tensors of very different magnitude.
    """
    signal_power = sum(o ** 2 for o in original) / len(original)
    noise_power = mse(original, reconstructed)
    if noise_power == 0:
        return float("inf")
    return 10 * math.log10(signal_power / noise_power)


# ------------------------------------------------------------------
# 4. Clipping vs rounding error — the actual tradeoff, demonstrated
# ------------------------------------------------------------------
def demonstrate_clipping_vs_rounding_tradeoff():
    """
    Simulates a weight distribution with a FEW outliers and compares two
    scale choices: one that covers the full range (no clipping, but
    coarser rounding for the bulk of values) vs one that clips outliers
    (finer rounding for the bulk, but the outliers are badly distorted).
    This demonstrates WHY outlier-aware methods (Phase 4) exist at all —
    the "just widen the scale" default is not free.
    """
    import random
    random.seed(0)
    # Mostly small values, a few large outliers — mimics a real weight
    # column's distribution shape.
    values = [random.gauss(0, 0.02) for _ in range(95)] + [1.5, -1.4, 1.6, -1.3, 1.55]

    # Option A: scale to cover EVERYTHING (no clipping)
    q_full, scale_full = symmetric_quantize(values, num_bits=8)
    dq_full = symmetric_dequantize(q_full, scale_full)

    # Option B: scale to the 95th percentile, deliberately clipping outliers
    sorted_abs = sorted(abs(v) for v in values)
    p95 = sorted_abs[int(0.95 * len(sorted_abs))]
    scale_clip = p95 / 127
    q_clip = [max(-127, min(127, round(v / scale_clip))) for v in values]
    dq_clip = symmetric_dequantize(q_clip, scale_clip)

    print(f"Full-range scale:  {scale_full:.6f}  MSE={mse(values, dq_full):.6f}  "
          f"SQNR={signal_to_quantization_noise_ratio(values, dq_full):.2f} dB")
    print(f"Clipped scale:     {scale_clip:.6f}  MSE={mse(values, dq_clip):.6f}  "
          f"SQNR={signal_to_quantization_noise_ratio(values, dq_clip):.2f} dB")
    # Which wins depends on whether the DOWNSTREAM task cares more about
    # the bulk of small values being precise, or the outliers being
    # preserved — there is no universally correct answer, which is
    # exactly why Phase 4 covers several different strategies rather
    # than one "solved" method.


if __name__ == "__main__":
    values = [0.02, -0.5, 0.3, -0.01, 0.15, -0.22, 0.4]
    q, scale = symmetric_quantize(values, num_bits=8)
    dq = symmetric_dequantize(q, scale)
    print("Symmetric INT8:")
    print("  quantized:", q)
    print("  dequantized:", [round(v, 4) for v in dq])
    print(f"  MSE={mse(values, dq):.6f}  SQNR={signal_to_quantization_noise_ratio(values, dq):.2f} dB")

    print()
    relu_output = [0.0, 0.0, 1.2, 0.5, 0.0, 2.8, 0.1]
    q2, scale2, zp2 = asymmetric_quantize(relu_output, num_bits=8)
    dq2 = asymmetric_dequantize(q2, scale2, zp2)
    print("Asymmetric UINT8 (post-ReLU activations):")
    print("  quantized:", q2, " zero_point:", zp2)
    print("  dequantized:", [round(v, 4) for v in dq2])

    print()
    demonstrate_clipping_vs_rounding_tradeoff()

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
Every quantization paper's ablation table (e.g. "symmetric vs asymmetric,"
"per-tensor vs per-channel") is directly measuring the tradeoffs shown in
`demonstrate_clipping_vs_rounding_tradeoff()`. When you implement GPTQ in
Phase 4 and it reports "average bits" and a perplexity number, you are
looking at exactly the SQNR-style tradeoff computed here, just measured
via downstream task performance instead of raw signal error — the two are
correlated but not identical, which is itself a subtlety worth
understanding before trusting either metric alone.
"""
