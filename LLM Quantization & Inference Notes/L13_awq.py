# ============================================================
# L13: AWQ — Activation-Aware Weight Quantization (Lin et al., 2023)
# ============================================================
# WHAT: A from-scratch implementation of AWQ's core idea — instead of
#       compensating for quantization error AFTER the fact (GPTQ's
#       approach), AWQ PROTECTS a small fraction of "salient" weights
#       BEFORE quantizing, by rescaling channels so those weights survive
#       low-bit rounding with much less error, using ONLY activation
#       statistics (no backward pass, no Hessian).
# WHY (RESEARCH): AWQ and GPTQ represent two genuinely different research
#      philosophies for the same problem — this lesson is where you learn
#      to compare methods on their DESIGN PHILOSOPHY, not just their
#      benchmark numbers, which is exactly the skill needed to write a
#      good related-work section yourself.
# LEVEL: Advanced (Phase 4 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
AWQ's starting observation: not all weights matter equally for a layer's
output — a small percentage (often ~1%) of weight CHANNELS correspond to
activation channels with consistently LARGE magnitude, and these
"salient" weight channels contribute disproportionately to the layer's
output. Protecting these salient weights from quantization error matters
far more than protecting the rest.

AWQ's method does NOT keep salient weights at higher precision (a
"mixed-precision" approach, which complicates hardware kernels) — instead
it exploits a mathematical trick: for a linear layer y = Wx, you can
rescale by any per-channel factor s WITHOUT changing the output:
    y = Wx = (W * s) * (x / s)
If you SCALE UP the weight channels corresponding to salient activations
(multiply by s > 1) and correspondingly SCALE DOWN those activation
channels (divide by s), the salient weight values become numerically
LARGER RELATIVE to the quantization step size — meaning proportionally
LESS relative rounding error for those specific weights — while
mathematically the layer's output is UNCHANGED (the activation-side
division exactly cancels the weight-side multiplication).

Critically, AWQ determines saliency and the optimal scaling factor `s`
using ONLY activation magnitude statistics from a calibration set — NO
backward pass, no Hessian computation. This makes it noticeably CHEAPER
to run than GPTQ, and it generalizes better across different calibration
sets in the paper's own ablations (less prone to "overfitting" to the
specific calibration data, since it only needs coarse magnitude
statistics, not fine-grained per-weight second-order information).

PRODUCTION/RESEARCH USE CASE:
AWQ is widely used specifically because of its speed advantage (no
Hessian computation, no expensive layer-by-layer sequential optimization)
— quantizing a large model with AWQ is often meaningfully faster than
with GPTQ, which matters a lot if you're iterating on quantization
hyperparameters as part of a research process.

COMMON MISTAKES:
- Forgetting to apply the CORRESPONDING inverse scale to the activations
  at inference time — if you only scale the weights and never divide the
  activations, you've silently changed the layer's mathematical function,
  not just its numerical behavior.
- Choosing the scaling factor based on WEIGHT magnitude instead of
  ACTIVATION magnitude — AWQ's entire premise is that channel importance
  is determined by how large the ACTIVATIONS flowing through that channel
  are, not by how large the weights themselves happen to be.
- Applying a single global scale instead of a PER-CHANNEL scale — the
  entire point is that DIFFERENT channels need different amounts of
  protection; a global scale degenerates to doing nothing useful.
"""

import torch


# ------------------------------------------------------------------
# 1. Identifying salient channels from activation statistics
# ------------------------------------------------------------------
def compute_channel_saliency(calibration_activations: torch.Tensor) -> torch.Tensor:
    """
    A simple, representative saliency signal: the AVERAGE MAGNITUDE of
    each input channel across the calibration set. AWQ's actual paper
    uses this exact quantity (average activation magnitude per channel)
    as its saliency proxy — the key finding being that this simple,
    CHEAP-TO-COMPUTE statistic correlates strongly with which weight
    channels matter most for output quality, without needing anything
    more expensive.
    """
    # calibration_activations: (num_samples, in_features)
    return calibration_activations.abs().mean(dim=0)  # shape (in_features,)


# ------------------------------------------------------------------
# 2. Computing the per-channel scaling factor
# ------------------------------------------------------------------
def compute_awq_scales(saliency: torch.Tensor, alpha: float = 0.5) -> torch.Tensor:
    """
    AWQ searches over a grid of `alpha` values (the paper does a small
    grid search per layer) for the scale exponent that best balances
    protecting salient channels against not over-scaling non-salient
    ones — this simplified version fixes alpha as an argument to make the
    core formula visible: scale = saliency^alpha, normalized so the
    scaling doesn't systematically inflate or deflate overall weight
    magnitude (which would itself interact badly with the OUTER
    per-tensor/per-channel scale chosen during actual quantization).
    """
    scales = saliency.pow(alpha)
    # Normalize so the scale factors have a geometric mean of 1 — this
    # keeps the OVERALL weight magnitude roughly unchanged, so the
    # quantization scale computed downstream isn't itself distorted by
    # this rescaling step.
    scales = scales / scales.log().mean().exp()
    return scales.clamp(min=1e-4)  # avoid divide-by-zero for near-silent channels


# ------------------------------------------------------------------
# 3. Applying the scale-equivalent transform (the "free lunch" trick)
# ------------------------------------------------------------------
def apply_awq_scaling(weight: torch.Tensor, activations: torch.Tensor,
                        scales: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """
    weight: (out_features, in_features)
    activations: (num_samples, in_features)
    scales: (in_features,) — one scale per INPUT channel

    Returns the RESCALED weight (ready to be quantized with much smaller
    relative error on salient channels) and the RESCALED activations
    (which must be used at actual inference time to keep the layer's
    output mathematically identical).
    """
    # y = W @ x = (W * s) @ (x / s) — scale UP the weight columns
    # corresponding to salient channels, scale DOWN the matching
    # activation columns by the exact same factor.
    scaled_weight = weight * scales.unsqueeze(0)      # broadcast over out_features
    scaled_activations = activations / scales.unsqueeze(0)
    return scaled_weight, scaled_activations


def quantize_symmetric(x: torch.Tensor, num_bits: int, dim: int) -> torch.Tensor:
    qmax = 2 ** (num_bits - 1) - 1
    scale = x.abs().amax(dim=dim, keepdim=True) / qmax
    scale = scale.clamp(min=1e-8)
    return (x / scale).round().clamp(-qmax, qmax) * scale


# ------------------------------------------------------------------
# 4. Full comparison: AWQ-style rescale-then-quantize vs plain quantize
# ------------------------------------------------------------------
def compare_awq_vs_plain_quantization():
    torch.manual_seed(0)
    in_features, out_features = 64, 16
    weight = torch.randn(out_features, in_features) * 0.05

    # Construct calibration activations where a FEW channels have
    # systematically larger magnitude — this is the realistic pattern
    # AWQ's paper documents in real LLM activations (a small number of
    # "hub" channels with outsized magnitude across almost all inputs).
    calibration_activations = torch.randn(200, in_features) * 0.1
    salient_channels = [3, 17, 40]
    calibration_activations[:, salient_channels] *= 20

    test_activations = torch.randn(20, in_features) * 0.1
    test_activations[:, salient_channels] *= 20
    true_output = test_activations @ weight.T

    # --- Plain quantization, no rescaling ---
    plain_quantized_weight = quantize_symmetric(weight, num_bits=4, dim=1)
    plain_output = test_activations @ plain_quantized_weight.T
    plain_error = (true_output - plain_output).pow(2).mean().item()

    # --- AWQ-style: rescale based on saliency, quantize, then use
    #     rescaled activations at "inference" time ---
    saliency = compute_channel_saliency(calibration_activations)
    scales = compute_awq_scales(saliency, alpha=0.5)
    scaled_weight, _ = apply_awq_scaling(weight, calibration_activations, scales)
    scaled_weight_quantized = quantize_symmetric(scaled_weight, num_bits=4, dim=1)

    # At "inference," scale the ACTUAL test activations down by the same
    # factor before feeding them to the rescaled-and-quantized weight —
    # this is the step that keeps the transform mathematically exact.
    scaled_test_activations = test_activations / scales.unsqueeze(0)
    awq_output = scaled_test_activations @ scaled_weight_quantized.T
    awq_error = (true_output - awq_output).pow(2).mean().item()

    print(f"Plain 4-bit quantization output MSE: {plain_error:.6f}")
    print(f"AWQ-style 4-bit quantization output MSE: {awq_error:.6f}")
    print(f"AWQ improvement: {(1 - awq_error / plain_error) * 100:.1f}% lower error")
    # AWQ wins here specifically BECAUSE the salient channels' weight
    # values are now numerically larger (post-rescale) relative to the
    # 4-bit quantization step size, so their rounding error shrinks in
    # relative terms — while the mathematical output is preserved exactly
    # (up to the quantization error itself) by the compensating
    # activation-side division.


if __name__ == "__main__":
    compare_awq_vs_plain_quantization()

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
When comparing AWQ against GPTQ on the SAME model and bit-width, you'll
often find AWQ is faster to PRODUCE a quantized checkpoint (no Hessian,
no sequential column loop) while GPTQ sometimes edges out slightly better
final accuracy on some benchmarks (because it does full second-order
error compensation rather than a coarser magnitude-based heuristic) — a
genuinely interesting open research question is characterizing exactly
WHEN each method's tradeoff wins, which is precisely the kind of
comparative study (methodology, not just running someone else's code)
that becomes a real paper contribution.
"""
