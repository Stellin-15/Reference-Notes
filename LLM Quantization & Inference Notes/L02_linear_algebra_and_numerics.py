# ============================================================
# L02: Linear Algebra and Numerical Representation for LLMs
# ============================================================
# WHAT: The matrix operations that dominate LLM compute cost (matmul,
#       the FLOP/byte accounting behind them), and how floating-point
#       numbers are actually represented in memory (FP32/FP16/BF16) —
#       the direct prerequisite for understanding quantization.
# WHY (RESEARCH + SYSTEMS): You cannot design or reason about a
#       quantization scheme without knowing exactly what bits you're
#       discarding and why certain values (outliers, near-zero weights)
#       cause more damage than others when represented with fewer bits.
# LEVEL: Foundation (Phase 1 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
An LLM's forward pass is, compute-wise, almost entirely matrix
multiplications (attention projections, MLP up/down projections). The
COST of a matmul is measured in FLOPs (floating point operations) — a
(m,k) x (k,n) matmul costs roughly 2*m*k*n FLOPs. But on modern GPUs,
LLM inference is usually NOT compute-bound — it's MEMORY-BANDWIDTH-bound:
loading the weight matrix from GPU memory into the compute units takes
longer than doing the actual multiply-adds once they're loaded. This
single fact is THE reason quantization gives real speedups: a 4-bit
weight is 1/4 the bytes to move, even if the arithmetic itself still
happens in higher precision after a fast dequantize step.

Floating point representation: a float is sign + exponent + mantissa.
FP32 (1+8+23 bits) has huge dynamic range and precision. FP16 (1+5+10)
has the SAME precision budget cut in half — its exponent range is much
smaller, which is why FP16 training can overflow/underflow more than
BF16. BF16 (1+8+7) keeps FP32's exponent range (same dynamic range, no
overflow surprises) but drops mantissa precision — this specific tradeoff
is why BF16 became the default for LLM training.

PRODUCTION/RESEARCH USE CASE:
Every quantization paper you'll read in Phase 4 starts from this exact
memory-bandwidth argument to justify why quantization helps, and every
number-format choice (why K-quants use block-wise 4-bit with FP16 scale
factors, why GPTQ needs FP16 activations even with INT4 weights) traces
back to the exponent/mantissa tradeoffs covered here.

COMMON MISTAKES:
- Assuming quantization speeds up inference because "less math" — the
  actual mechanism (for memory-bound workloads) is less DATA MOVEMENT,
  not fewer FLOPs. Compute-bound workloads (large batch, prefill) see a
  different, smaller benefit purely from faster low-precision arithmetic.
- Not accounting for OUTLIERS when reasoning about quantization error —
  LLM activations famously have a small number of channels with values
  orders of magnitude larger than the rest (this exact observation is the
  basis of LLM.int8() and SmoothQuant, covered in Phase 4).
- Confusing "more bits of mantissa" with "more useful precision" — near
  zero, floating point has enormous relative precision; far from zero,
  much less. This non-uniformity is why naive linear (INT) quantization
  of a Gaussian-ish weight distribution wastes representational capacity
  on values that barely occur.
"""

import struct
from dataclasses import dataclass

# ------------------------------------------------------------------
# 1. FLOP and memory-bandwidth accounting for a matmul
# ------------------------------------------------------------------
@dataclass
class MatmulCost:
    m: int  # rows of A
    k: int  # shared dimension
    n: int  # cols of B

    def flops(self) -> int:
        # Each output element requires k multiplies + k-1 adds ~ 2k FLOPs.
        # Total: m*n output elements * 2k FLOPs each.
        return 2 * self.m * self.k * self.n

    def bytes_moved(self, dtype_bytes: int) -> int:
        # Bytes for reading A (m*k), B (k*n), writing C (m*n) — the
        # SIMPLIFIED bandwidth cost ignoring cache reuse/tiling, but
        # enough to illustrate the compute-vs-bandwidth ratio.
        return dtype_bytes * (self.m * self.k + self.k * self.n + self.m * self.n)

    def arithmetic_intensity(self, dtype_bytes: int) -> float:
        """
        FLOPs per byte moved. Compare this to the GPU's own FLOPs/byte
        ratio (compute throughput / memory bandwidth) to determine if a
        given matmul shape is compute-bound or memory-bound. LLM
        inference at BATCH SIZE 1 (the common single-user case) has very
        LOW arithmetic intensity — this is precisely why it's memory-
        bandwidth-bound and why quantization (fewer bytes to move) helps
        so much more than it would for, say, training with huge batches.
        """
        return self.flops() / self.bytes_moved(dtype_bytes)


def why_batch_size_matters():
    """
    Single-token decode (batch=1) vs a large prefill/batch — same total
    weight size, wildly different arithmetic intensity.
    """
    # Decode: m=1 (one token), k=n=4096 (typical hidden dim) — B (the
    # weight matrix) totally dominates the byte count vs the tiny A.
    decode = MatmulCost(m=1, k=4096, n=4096)
    # Prefill: m=512 (512 tokens processed at once), same weight matrix.
    prefill = MatmulCost(m=512, k=4096, n=4096)

    print(f"Decode  (m=1):   AI = {decode.arithmetic_intensity(2):.2f} FLOPs/byte (FP16)")
    print(f"Prefill (m=512): AI = {prefill.arithmetic_intensity(2):.2f} FLOPs/byte (FP16)")
    # Prefill's arithmetic intensity is ~512x higher — the SAME weight
    # bytes are reused across 512 tokens instead of just 1, which is why
    # prefill is closer to compute-bound and decode is starkly memory-
    # bound. Quantization's biggest win is specifically on the decode path.


# ------------------------------------------------------------------
# 2. Floating point anatomy — sign, exponent, mantissa
# ------------------------------------------------------------------
def decompose_fp32(x: float) -> dict:
    """
    Unpacks a Python float's IEEE-754 FP32 representation into its
    three fields. This is the exact bit layout every quantization scheme
    either preserves (for scale factors) or discards (for weights).
    """
    packed = struct.pack(">f", x)          # big-endian 4-byte FP32
    bits = struct.unpack(">I", packed)[0]  # reinterpret as uint32

    sign = (bits >> 31) & 0x1
    exponent = (bits >> 23) & 0xFF          # 8 bits, biased by 127
    mantissa = bits & 0x7FFFFF              # 23 bits, implicit leading 1

    return {
        "sign": sign,
        "exponent_raw": exponent,
        "exponent_unbiased": exponent - 127,
        "mantissa": mantissa,
        "mantissa_binary": format(mantissa, "023b"),
    }


FORMAT_SPECS = {
    #           sign  exp  mantissa  notes
    "FP32":  (1, 8, 23, "Full range and precision. ~7 decimal digits."),
    "FP16":  (1, 5, 10, "Half the memory of FP32. Narrow exponent range "
                        "(max ~65504) — CAN OVERFLOW during training with "
                        "large activations, a classic FP16 training bug."),
    "BF16":  (1, 8, 7,  "Same exponent range as FP32 (no overflow surprise), "
                        "less mantissa precision. The default for LLM "
                        "training because range matters more than precision "
                        "for gradient/activation magnitudes."),
    "FP8_E4M3": (1, 4, 3, "4-bit exponent, 3-bit mantissa. Emerging inference "
                          "format on H100-class hardware — very narrow "
                          "range, needs careful per-tensor scaling."),
    "INT8":  (1, 0, 7,  "Not floating point at all — a fixed-point integer "
                        "requiring an explicit SCALE factor (stored "
                        "separately) to map back to real values. This is "
                        "the foundation of Phase 3's quantization schemes."),
}


# ------------------------------------------------------------------
# 3. Why naive linear quantization struggles with outliers
# ------------------------------------------------------------------
def demonstrate_outlier_problem():
    """
    A tiny illustration of why a SINGLE outlier value forces the
    quantization scale to stretch, wasting precision on every other
    (much smaller) value — the exact motivating observation behind
    LLM.int8()'s mixed-precision decomposition and SmoothQuant's
    activation-smoothing trick (both covered in Phase 4).
    """
    values = [0.02, -0.01, 0.03, 0.015, -0.02, 6.4]  # 6.4 is an outlier
    # Standard symmetric INT8 quantization: scale = max(abs(values)) / 127
    scale = max(abs(v) for v in values) / 127
    quantized = [round(v / scale) for v in values]
    dequantized = [q * scale for q in quantized]

    print(f"scale = {scale:.6f}")
    for orig, dq in zip(values, dequantized):
        err = abs(orig - dq)
        print(f"  original={orig:+.4f}  dequantized={dq:+.4f}  abs_error={err:.4f}")
    # Notice: the small values (0.02, -0.01, ...) suffer LARGE RELATIVE
    # error because the scale was forced wide by the single outlier 6.4.
    # This single demonstration is the entire motivation for every
    # "outlier-aware" quantization method you'll study in Phase 4.


if __name__ == "__main__":
    why_batch_size_matters()
    print()
    print("FP32 decomposition of 3.14:", decompose_fp32(3.14))
    print()
    demonstrate_outlier_problem()

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
When you implement AWQ in Phase 4, you'll compute a per-channel scaling
factor specifically to REDUCE the outlier problem demonstrated above
before quantizing — activation channels with large magnitude get their
corresponding weight channels scaled DOWN (and the activation scaled UP
correspondingly, preserving the mathematical result) so the quantization
range isn't dominated by a few outlier channels. None of that makes sense
without first seeing the raw outlier-forces-wide-scale problem in isolation,
which is exactly what `demonstrate_outlier_problem()` shows.
"""
