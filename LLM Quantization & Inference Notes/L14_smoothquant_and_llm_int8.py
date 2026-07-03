# ============================================================
# L14: SmoothQuant and LLM.int8() — Activation Quantization Methods
# ============================================================
# WHAT: Two influential methods for quantizing ACTIVATIONS (not just
#       weights) to INT8, enabling faster INT8 matmul instead of just
#       smaller storage: SmoothQuant's outlier-migration trick, and
#       LLM.int8()'s mixed-precision decomposition.
# WHY (RESEARCH): Everything in Phase 4 so far (GPTQ, AWQ) quantizes
#      WEIGHTS ONLY, dequantizing back to FP16 before the matmul — this
#      shrinks memory but does NOT speed up the matmul's arithmetic
#      itself. Quantizing ACTIVATIONS too (W8A8) unlocks actual INT8
#      tensor-core throughput, a genuinely different performance regime.
# LEVEL: Advanced (Phase 4 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
LLM.int8() (Dettmers et al., 2022) made a specific empirical discovery:
LLM activations have a small number of "outlier" FEATURE DIMENSIONS
(consistent across almost all tokens) with values 10-100x larger than
typical — and quantizing THESE specific dimensions to INT8 catastrophically
degrades accuracy, while quantizing everything ELSE to INT8 works fine.
The paper's solution: decompose the matmul into two parts — the small
number of outlier feature dimensions are computed in FP16 (full
precision, exact), and the vast majority of non-outlier dimensions are
computed in INT8 (fast, quantized) — then the two partial results are
summed. This is MIXED-PRECISION at the level of individual matmul columns,
not a single blanket precision choice for the whole tensor.

SmoothQuant (Xiao et al., 2023) takes a different, complementary approach
to the SAME outlier problem: instead of computing outliers separately in
FP16, it MIGRATES the quantization difficulty from activations to
weights. The key insight (using the exact same "y = Wx = (Ws)(x/s)"
rescaling identity as AWQ, L13, but applied in the OPPOSITE direction and
for a different purpose): activations are HARD to quantize because of
outliers, but weights are comparatively EASY (much smoother
distribution). SmoothQuant scales activation channels DOWN (dividing by a
per-channel factor s) and the corresponding weight channels UP
(multiplying by s) — this makes the activations "smoother" (easier to
quantize to INT8) at the cost of making the weights SLIGHTLY less smooth
(but weights had plenty of quantization headroom to spare).

PRODUCTION/RESEARCH USE CASE:
Both methods target the SAME hardware opportunity: modern GPU tensor
cores execute INT8 matmuls at roughly 2x the throughput of FP16 matmuls
(and INT4 at higher still) — but ONLY if BOTH operands (weights AND
activations) are in low precision; a W4A16 scheme (like GPTQ/AWQ as
covered so far) still dequantizes to FP16 before the matmul, so it saves
MEMORY but not MATMUL COMPUTE throughput. W8A8 methods like these unlock
the compute speedup too, which matters most for the COMPUTE-BOUND regime
(large batch/prefill, see L02) rather than the memory-bound decode regime
where weight-only quantization already helps the most.

COMMON MISTAKES:
- Assuming weight-only quantization (GPTQ/AWQ) gives the SAME speedup
  category as activation quantization — they solve DIFFERENT bottlenecks
  (memory bandwidth vs compute throughput), and conflating them leads to
  wrong expectations about where speedup will actually come from.
- Implementing SmoothQuant's migration factor in the wrong DIRECTION
  (scaling activations UP and weights DOWN instead of the reverse) —
  this would make activations HARDER to quantize, the opposite of the
  paper's goal.
- Choosing the outlier THRESHOLD for LLM.int8()'s mixed-decomposition
  arbitrarily rather than based on the actual observed activation
  distribution — too aggressive a threshold pulls too many dimensions
  into the slow FP16 path, eroding the speed benefit; too conservative
  and accuracy suffers.
"""

import torch


# ------------------------------------------------------------------
# 1. LLM.int8() — mixed-precision decomposition
# ------------------------------------------------------------------
def llm_int8_matmul(
    x: torch.Tensor,          # (batch, in_features) — activations
    weight: torch.Tensor,     # (out_features, in_features)
    outlier_threshold: float = 6.0,
) -> torch.Tensor:
    """
    Splits the matmul into an INT8 path (most dimensions) and an FP16
    path (outlier dimensions), then sums the two partial results — the
    exact decomposition from the paper, minus the actual INT8 kernel
    call (using a regular float matmul here to keep the algorithm's
    STRUCTURE visible, since the point is the decomposition logic, not
    beating a real INT8 kernel's speed in a teaching example).
    """
    # Identify outlier feature dimensions: any INPUT column where ANY
    # activation in the batch exceeds the threshold in absolute value.
    is_outlier_col = (x.abs() > outlier_threshold).any(dim=0)   # (in_features,)

    outlier_cols = is_outlier_col.nonzero(as_tuple=True)[0]
    normal_cols = (~is_outlier_col).nonzero(as_tuple=True)[0]

    # --- FP16 path: outlier columns computed at FULL PRECISION ---
    if len(outlier_cols) > 0:
        x_outlier = x[:, outlier_cols]
        w_outlier = weight[:, outlier_cols]
        fp16_result = x_outlier @ w_outlier.T
    else:
        fp16_result = torch.zeros(x.shape[0], weight.shape[0])

    # --- INT8 path: normal columns quantized and computed cheaply ---
    x_normal = x[:, normal_cols]
    w_normal = weight[:, normal_cols]

    x_scale = x_normal.abs().amax(dim=1, keepdim=True) / 127
    x_scale = x_scale.clamp(min=1e-8)
    x_int8 = (x_normal / x_scale).round().clamp(-127, 127)

    w_scale = w_normal.abs().amax(dim=1, keepdim=True) / 127
    w_scale = w_scale.clamp(min=1e-8)
    w_int8 = (w_normal / w_scale).round().clamp(-127, 127)

    # The actual INT8 matmul (here simulated in float; a real kernel
    # would use native INT8 tensor-core instructions), then DEQUANTIZE
    # by multiplying back through both scale factors.
    int8_result = (x_int8 @ w_int8.T) * x_scale * w_scale.T

    print(f"  outlier columns: {len(outlier_cols)}/{x.shape[1]}  "
          f"({100 * len(outlier_cols) / x.shape[1]:.1f}% routed to FP16 path)")

    return fp16_result + int8_result


# ------------------------------------------------------------------
# 2. SmoothQuant — migrating quantization difficulty from activations to weights
# ------------------------------------------------------------------
def compute_smoothquant_scales(
    activation_stats: torch.Tensor,  # per-channel max abs activation, (in_features,)
    weight_stats: torch.Tensor,       # per-channel max abs weight, (in_features,)
    alpha: float = 0.5,
) -> torch.Tensor:
    """
    s_j = max(|X_j|)^alpha / max(|W_j|)^(1-alpha)

    alpha controls the MIGRATION STRENGTH: alpha=0 does nothing (all
    difficulty stays on activations); alpha=1 pushes ALL difficulty onto
    weights. alpha=0.5 (the paper's typical default) balances the two —
    this single hyperparameter is the entire "knob" SmoothQuant exposes,
    and its optimal value is empirically found to vary somewhat by model,
    which is itself worth investigating if you replicate this.
    """
    return (activation_stats.pow(alpha) / weight_stats.pow(1 - alpha)).clamp(min=1e-5)


def apply_smoothquant(
    weight: torch.Tensor, activations: torch.Tensor, scales: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """
    y = Wx = (W * s) @ (x / s) — SAME mathematical identity as AWQ (L13),
    but here `s` is chosen to make ACTIVATIONS smoother (divide by scale)
    at the cost of making WEIGHTS less smooth (multiply by scale) — the
    OPPOSITE intent from AWQ, which protects salient WEIGHT channels.
    Both methods are valid uses of the exact same rescaling trick, aimed
    at different quantization targets (activations here, weights there).
    """
    smoothed_activations = activations / scales.unsqueeze(0)
    smoothed_weight = weight * scales.unsqueeze(0)
    return smoothed_weight, smoothed_activations


def compare_smoothquant_vs_plain_w8a8():
    torch.manual_seed(0)
    in_features, out_features = 64, 16
    weight = torch.randn(out_features, in_features) * 0.05

    activations = torch.randn(200, in_features) * 0.1
    outlier_channels = [5, 22, 50]
    activations[:, outlier_channels] *= 15   # a few large-magnitude channels

    def quantize_int8(x, dim):
        scale = x.abs().amax(dim=dim, keepdim=True) / 127
        scale = scale.clamp(min=1e-8)
        return (x / scale).round().clamp(-127, 127) * scale

    true_output = activations @ weight.T

    # --- Plain W8A8: quantize both, no migration ---
    plain_act_q = quantize_int8(activations, dim=1)
    plain_weight_q = quantize_int8(weight, dim=1)
    plain_output = plain_act_q @ plain_weight_q.T
    plain_error = (true_output - plain_output).pow(2).mean().item()

    # --- SmoothQuant: migrate outlier difficulty to weights first ---
    act_stats = activations.abs().amax(dim=0)
    weight_stats = weight.abs().amax(dim=0)
    scales = compute_smoothquant_scales(act_stats, weight_stats, alpha=0.5)
    smoothed_weight, smoothed_activations = apply_smoothquant(weight, activations, scales)

    smoothed_act_q = quantize_int8(smoothed_activations, dim=1)
    smoothed_weight_q = quantize_int8(smoothed_weight, dim=1)
    smooth_output = smoothed_act_q @ smoothed_weight_q.T
    smooth_error = (true_output - smooth_output).pow(2).mean().item()

    print(f"Plain W8A8 output MSE:       {plain_error:.6f}")
    print(f"SmoothQuant W8A8 output MSE: {smooth_error:.6f}")
    print(f"SmoothQuant improvement: {(1 - smooth_error / plain_error) * 100:.1f}% lower error")


if __name__ == "__main__":
    print("LLM.int8() mixed-precision decomposition:")
    torch.manual_seed(0)
    x = torch.randn(8, 32) * 0.5
    x[:, [3, 15]] *= 20   # inject a couple of outlier feature dimensions
    w = torch.randn(4, 32) * 0.05
    out = llm_int8_matmul(x, w, outlier_threshold=6.0)
    print("  output shape:", out.shape)

    print("\nSmoothQuant vs plain W8A8:")
    compare_smoothquant_vs_plain_w8a8()

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
vLLM and TensorRT-LLM (Phase 6) both support W8A8 quantization inspired
by these exact methods specifically because compute-bound workloads
(long prompts, large batch serving) benefit from real INT8 tensor-core
throughput in a way weight-only INT4 schemes (GPTQ/AWQ) cannot provide —
choosing between W4A16 and W8A8 in a production deployment is a direct,
concrete application of the memory-bound-vs-compute-bound distinction
first introduced back in L02, now with two specific, benchmarkable
techniques to choose between.
"""
