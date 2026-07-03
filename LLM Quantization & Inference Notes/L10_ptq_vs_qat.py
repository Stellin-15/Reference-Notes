# ============================================================
# L10: Post-Training Quantization (PTQ) vs Quantization-Aware Training (QAT)
# ============================================================
# WHAT: The two fundamental strategies for producing a quantized model —
#       quantize an already-trained model with no further training (PTQ),
#       vs simulate quantization DURING training so the model adapts to
#       it (QAT) — implemented as real, runnable code for both.
# WHY: Nearly every LLM quantization method you'll read about in Phase 4
#      (GPTQ, AWQ, GGUF/K-quants) is PTQ — this is not a coincidence, and
#      understanding WHY PTQ dominates for LLMs specifically (as opposed
#      to smaller vision models, where QAT is common) is itself a real
#      research-level insight.
# LEVEL: Core (Phase 3 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
PTQ takes a fully-trained FP16/BF16 model and converts its weights (and
optionally activations) to low precision using ONLY the math from L09 —
no gradient updates, no retraining. It's fast (minutes to hours) and
requires no training infrastructure or labeled data (at most a small
CALIBRATION set to measure activation ranges — covered in L11).

QAT inserts "fake quantization" nodes into the model's forward pass DURING
training: weights/activations are quantized then immediately dequantized
(round-trip through low precision, but stored/computed in full precision)
so the FORWARD pass sees quantization error, while the BACKWARD pass uses
a Straight-Through Estimator (STE) — since the true gradient of a `round()`
function is zero almost everywhere (useless for training), STE simply
pretends round() has gradient 1, passing the upstream gradient straight
through unchanged. This lets the model's weights ADJUST during training to
compensate for quantization error, generally achieving better final
accuracy than PTQ at the same bit-width — at the cost of needing a full
training pipeline, labeled data, and much more compute/time.

Why PTQ dominates for LLMs specifically: LLM pretraining is already
enormously expensive (weeks on large clusters) — running QAT means
essentially re-running a meaningful fraction of that expensive process,
which is often not economically justified when a good PTQ method (Phase 4)
can get within a small percentage of QAT's quality at a tiny fraction of
the cost. QAT remains more common for smaller models (vision, mobile)
where the retraining cost is comparatively trivial.

PRODUCTION/RESEARCH USE CASE:
When you read a quantization paper's related-work section, "PTQ method"
vs "QAT method" is one of the FIRST classifications made, because it
determines the entire evaluation protocol (does the paper need training
infrastructure and data, or just a pretrained checkpoint and a small
calibration set).

COMMON MISTAKES:
- Implementing the Straight-Through Estimator incorrectly — a common bug
  is forgetting to clip the "pretend gradient" to only pass through where
  the input was actually WITHIN the quantization range (values that were
  clipped/saturated should NOT receive a pass-through gradient, since a
  small change to a saturated input doesn't change the quantized output
  at all).
- Assuming QAT is strictly better than PTQ — for LARGE models with
  GOOD PTQ methods, the accuracy gap is often small enough that QAT's
  extra cost isn't justified; this is an empirical question to actually
  measure, not something to assume from vision-model intuition.
- Applying fake-quantization only to WEIGHTS during QAT while deploying
  with activations ALSO quantized — QAT must simulate the EXACT
  deployment quantization scheme (which tensors, which bit-width, which
  granularity) or the trained model won't actually be adapted to real
  deployment conditions.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


# ------------------------------------------------------------------
# 1. PTQ — quantize an already-trained linear layer, no further training
# ------------------------------------------------------------------
def ptq_quantize_linear(layer: nn.Linear, num_bits: int = 8) -> tuple[torch.Tensor, torch.Tensor]:
    """
    Per-output-channel symmetric quantization of a Linear layer's weight
    — PER-CHANNEL (one scale per output row) rather than per-tensor
    (one scale for the whole matrix) is the standard choice for weights,
    since different output channels can have very different value ranges;
    a single global scale would force a suboptimal compromise across all
    of them (directly connects to the outlier discussion in L09).
    """
    W = layer.weight.data  # shape (out_features, in_features)
    qmax = 2 ** (num_bits - 1) - 1

    # One scale PER ROW (per output channel) — computed independently.
    scales = W.abs().amax(dim=1, keepdim=True) / qmax
    scales = scales.clamp(min=1e-8)  # avoid divide-by-zero for an all-zero row

    W_int = (W / scales).round().clamp(-qmax, qmax)
    return W_int, scales


def ptq_dequantize_linear(W_int: torch.Tensor, scales: torch.Tensor) -> torch.Tensor:
    return W_int * scales


# ------------------------------------------------------------------
# 2. QAT — fake quantization with a Straight-Through Estimator
# ------------------------------------------------------------------
class FakeQuantizeSTE(torch.autograd.Function):
    """
    Forward: actually round-trips through the quantization grid (the
    model FEELS the real quantization error in its forward pass).
    Backward: pretends the whole operation was the identity function,
    EXCEPT it zeroes the gradient for any input that was clipped/
    saturated — a saturated value's output doesn't change with small
    input perturbations, so passing gradient through there would be a
    lie the optimizer would (harmlessly, but pointlessly) act on.
    """

    @staticmethod
    def forward(ctx, x: torch.Tensor, scale: torch.Tensor, qmax: int):
        x_int = (x / scale).round().clamp(-qmax, qmax)
        x_dequant = x_int * scale
        # Save a mask of which elements were NOT clipped, for backward.
        ctx.save_for_backward((x / scale).abs() <= qmax)
        return x_dequant

    @staticmethod
    def backward(ctx, grad_output):
        (not_clipped,) = ctx.saved_tensors
        # Straight-through: pass grad_output through unchanged, EXCEPT
        # zero it out wherever the forward pass clipped the value.
        grad_input = grad_output * not_clipped
        return grad_input, None, None


def fake_quantize(x: torch.Tensor, num_bits: int = 8) -> torch.Tensor:
    qmax = 2 ** (num_bits - 1) - 1
    scale = x.detach().abs().amax() / qmax
    scale = scale.clamp(min=1e-8)
    return FakeQuantizeSTE.apply(x, scale, qmax)


class QATLinear(nn.Module):
    """
    A Linear layer that fake-quantizes its WEIGHT on every forward pass
    during training — the model's gradients naturally push weights toward
    values that survive quantization well, because the loss the optimizer
    sees is computed using the ALREADY-QUANTIZED weight.
    """

    def __init__(self, in_features: int, out_features: int, num_bits: int = 8):
        super().__init__()
        self.weight = nn.Parameter(torch.randn(out_features, in_features) * 0.02)
        self.num_bits = num_bits

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Fake-quantize the FULL-PRECISION weight on every call — this
        # weight tensor itself remains FP32/BF16 and continues to receive
        # normal gradient updates; only the VALUE FED to the matmul has
        # been round-tripped through the quantization grid.
        fake_quant_weight = fake_quantize(self.weight, self.num_bits)
        return F.linear(x, fake_quant_weight)


# ------------------------------------------------------------------
# 3. Side-by-side comparison: does QAT actually recover accuracy PTQ loses?
# ------------------------------------------------------------------
def compare_ptq_vs_qat_on_toy_task():
    """
    A deliberately tiny, fast experiment: fit a linear regression task,
    then compare (a) quantizing the FINAL trained weight post-hoc (PTQ)
    vs (b) training WITH fake-quantization from the start (QAT), at a
    punishingly low 3-bit precision to make the effect visible on a toy
    problem in a few dozen steps.
    """
    torch.manual_seed(0)
    X = torch.randn(200, 10)
    true_w = torch.randn(10, 1)
    y = X @ true_w + 0.01 * torch.randn(200, 1)

    # --- PTQ path: train normally, quantize at the very end ---
    w_ptq = nn.Parameter(torch.randn(10, 1) * 0.1)
    opt = torch.optim.Adam([w_ptq], lr=0.05)
    for _ in range(200):
        loss = F.mse_loss(X @ w_ptq, y)
        loss.backward()
        opt.step()
        opt.zero_grad()
    qmax = 2 ** (3 - 1) - 1  # 3-bit
    scale = w_ptq.detach().abs().max() / qmax
    w_ptq_quantized = (w_ptq.detach() / scale).round().clamp(-qmax, qmax) * scale
    ptq_loss = F.mse_loss(X @ w_ptq_quantized, y).item()

    # --- QAT path: fake-quantize the weight on every training step ---
    w_qat = nn.Parameter(torch.randn(10, 1) * 0.1)
    opt = torch.optim.Adam([w_qat], lr=0.05)
    for _ in range(200):
        fq_w = fake_quantize(w_qat, num_bits=3)
        loss = F.mse_loss(X @ fq_w, y)
        loss.backward()
        opt.step()
        opt.zero_grad()
    final_fq_w = fake_quantize(w_qat, num_bits=3).detach()
    qat_loss = F.mse_loss(X @ final_fq_w, y).item()

    print(f"PTQ (train FP32, quantize after): quantized-weight loss = {ptq_loss:.6f}")
    print(f"QAT (fake-quantize during training): quantized-weight loss = {qat_loss:.6f}")
    # QAT typically wins at this aggressive bit-width because the
    # optimizer had the CHANCE to steer weights toward values that round
    # cleanly — PTQ's weights were optimized with NO knowledge that
    # quantization was coming.


if __name__ == "__main__":
    torch.manual_seed(0)
    layer = nn.Linear(8, 4, bias=False)
    W_int, scales = ptq_quantize_linear(layer, num_bits=8)
    W_reconstructed = ptq_dequantize_linear(W_int, scales)
    error = (layer.weight.data - W_reconstructed).abs().mean().item()
    print(f"PTQ per-channel INT8 mean abs error: {error:.6f}")

    print()
    compare_ptq_vs_qat_on_toy_task()

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
GPTQ and AWQ (Phase 4) are BOTH pure PTQ methods — they never touch a
gradient or a training loop, which is exactly why they can quantize a
70B-parameter model in a couple of GPU-hours instead of the weeks a QAT
retraining run would require. Understanding the PTQ/QAT distinction here
is what lets you correctly categorize any NEW quantization paper you read
in five seconds, just from its evaluation setup.
"""
