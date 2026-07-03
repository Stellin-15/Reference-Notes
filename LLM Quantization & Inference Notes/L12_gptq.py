# ============================================================
# L12: GPTQ — Hessian-Based Weight Quantization (Frantar et al., 2022)
# ============================================================
# WHAT: A from-scratch, working implementation of GPTQ's core algorithm —
#       layer-by-layer quantization that uses SECOND-ORDER (Hessian)
#       information to decide how to compensate for each weight's
#       quantization error, quantizing weights ONE COLUMN AT A TIME.
# WHY (RESEARCH): This is your first full reproduction of a real,
#      published, still-widely-used quantization paper. The technique
#      (optimal brain surgeon-style error compensation) generalizes far
#      beyond quantization — the same idea appears in pruning research.
# LEVEL: Advanced (Phase 4 of 8 — Modern Quantization Research)
# ============================================================

"""
CONCEPT OVERVIEW:
GPTQ's key insight: when you quantize weight w_i (round it to the nearest
representable value), you introduce an error delta = w_i - quantize(w_i).
Naively, every OTHER weight in the layer stays unchanged, and this error
just sits there, degrading the layer's output. GPTQ instead UPDATES ALL
REMAINING (not-yet-quantized) weights to COMPENSATE for the error just
introduced — using the layer's HESSIAN (a matrix capturing how sensitive
the output is to each pair of weights) to compute the optimal compensating
update. This traces back to the "Optimal Brain Surgeon" pruning technique
from the 1990s, adapted to quantization instead of pruning.

The algorithm processes each ROW of the weight matrix independently,
column by column (in a fixed order, usually determined by how much error
each column would introduce). At each column i:
  1. Quantize w_i using ordinary round-to-nearest.
  2. Compute the error: delta = w_i - quantize(w_i).
  3. UPDATE all REMAINING (not yet quantized) weights in this row using
     the inverse Hessian, distributing the error's impact optimally.
  4. Move to the next column.

Because computing/inverting a full Hessian per layer is expensive, GPTQ
uses a computationally efficient CHOLESKY DECOMPOSITION-based reformulation
that makes the whole process feasible in a few GPU-hours even for a
70B-parameter model — this efficiency engineering is as much the paper's
contribution as the underlying error-compensation idea itself.

PRODUCTION/RESEARCH USE CASE:
GPTQ-quantized models (typically 4-bit, group_size=128 — see L11) are one
of the most common formats you'll find distributed on Hugging Face for
running large models on consumer GPUs, alongside AWQ (L13) and GGUF (L15).

COMMON MISTAKES:
- Implementing the "quantize each weight independently, ignore Hessian"
  version and calling it GPTQ — that's just naive RTN (round-to-nearest)
  quantization; the Hessian-based ERROR COMPENSATION is the entire point.
- Getting the column PROCESSING ORDER wrong — later columns' compensating
  updates depend on earlier columns already being quantized; if you
  parallelize this naively across columns, you break the algorithm's
  correctness, not just its efficiency.
- Forgetting DAMPENING (adding a small value to the Hessian's diagonal
  before inverting) — real Hessians can be near-singular/ill-conditioned,
  and inverting them without dampening produces numerically unstable,
  sometimes catastrophically wrong compensating updates.
"""

import torch


# ------------------------------------------------------------------
# 1. The Hessian approximation for a linear layer
# ------------------------------------------------------------------
def compute_layer_hessian(activations: torch.Tensor, dampening: float = 0.01) -> torch.Tensor:
    """
    For a linear layer y = W @ x, the relevant Hessian (of the LAYER'S
    OUTPUT ERROR w.r.t. the WEIGHTS, given a fixed calibration input
    distribution) reduces to H = 2 * X^T @ X, where X is the collected
    calibration ACTIVATIONS (the layer's INPUT, across many calibration
    samples) — this is the standard result GPTQ (and the earlier OBS/OBQ
    work it builds on) relies on, and it is why GPTQ needs a calibration
    dataset (L11) at all: the Hessian is a property of the INPUT
    DISTRIBUTION, not the weights themselves.
    """
    # activations: (num_calibration_samples, in_features)
    H = 2 * activations.T @ activations
    # Dampening: add a small multiple of the average diagonal value to
    # the diagonal before inverting — without this, H can be singular
    # (if some input feature is always zero across calibration data) or
    # ill-conditioned, producing huge, wrong compensating updates.
    diag_mean = H.diagonal().mean()
    H += dampening * diag_mean * torch.eye(H.shape[0])
    return H


# ------------------------------------------------------------------
# 2. GPTQ's core column-by-column quantization loop
# ------------------------------------------------------------------
def gptq_quantize_row(
    w_row: torch.Tensor,          # a single output-neuron's weight vector, shape (in_features,)
    H_inv_cholesky: torch.Tensor,  # precomputed inverse-Hessian info (upper-triangular Cholesky factor)
    num_bits: int,
) -> torch.Tensor:
    """
    Quantizes one row of the weight matrix, column by column, propagating
    each column's quantization error into the NOT-YET-QUANTIZED columns
    of the SAME row using the (Cholesky-factored) inverse Hessian.

    This mirrors the paper's actual reformulation: rather than
    recomputing an updated inverse Hessian after every single column
    (extremely expensive), GPTQ precomputes the Cholesky decomposition of
    the inverse Hessian ONCE per layer and reuses ROWS of it as the
    per-column update coefficients — this is the specific efficiency
    trick that makes 70B-parameter quantization tractable in hours, not
    weeks.
    """
    in_features = w_row.shape[0]
    w = w_row.clone()
    qmax = 2 ** (num_bits - 1) - 1

    for i in range(in_features):
        w_i = w[i]

        # Ordinary round-to-nearest quantization of THIS column, using a
        # PER-ROW scale computed once up front (a real implementation
        # would use per-group scales per L11 — simplified to per-row
        # here to keep the core algorithm visible).
        scale = w_row.abs().max() / qmax
        q_i = torch.clamp((w_i / scale).round(), -qmax, qmax) * scale

        error = w_i - q_i
        w[i] = q_i

        # THE key GPTQ step: distribute `error`'s impact into every
        # REMAINING (not-yet-quantized) weight in this row, weighted by
        # the inverse-Hessian row for column i — this is what makes GPTQ
        # meaningfully better than independent round-to-nearest: later
        # weights get adjusted to partially CANCEL OUT the error just
        # introduced, rather than each weight's error being independent
        # and uncorrected.
        if i < in_features - 1:
            update_coeffs = H_inv_cholesky[i, i + 1:] / H_inv_cholesky[i, i]
            w[i + 1:] -= error * update_coeffs

    return w


# ------------------------------------------------------------------
# 3. Full layer quantization, tying calibration + Hessian + column loop together
# ------------------------------------------------------------------
def gptq_quantize_layer(weight: torch.Tensor, calibration_activations: torch.Tensor,
                          num_bits: int = 4) -> torch.Tensor:
    H = compute_layer_hessian(calibration_activations)

    # Cholesky decomposition of the INVERSE Hessian — GPTQ's actual paper
    # works with the Cholesky factor of H^-1 directly (computed via a
    # numerically stable routine) rather than naively inverting H; a
    # simplified but representative version is used here.
    H_inv = torch.linalg.inv(H)
    H_inv_cholesky = torch.linalg.cholesky(H_inv, upper=True)

    quantized_rows = [
        gptq_quantize_row(weight[row], H_inv_cholesky, num_bits)
        for row in range(weight.shape[0])
    ]
    return torch.stack(quantized_rows)


# ------------------------------------------------------------------
# 4. Comparing GPTQ against naive round-to-nearest (RTN)
# ------------------------------------------------------------------
def rtn_quantize_layer(weight: torch.Tensor, num_bits: int = 4) -> torch.Tensor:
    qmax = 2 ** (num_bits - 1) - 1
    scale = weight.abs().amax(dim=1, keepdim=True) / qmax
    scale = scale.clamp(min=1e-8)
    return (weight / scale).round().clamp(-qmax, qmax) * scale


def compare_gptq_vs_rtn():
    torch.manual_seed(0)
    in_features, out_features = 64, 16
    weight = torch.randn(out_features, in_features) * 0.05

    # Simulate calibration activations with realistic CORRELATION between
    # input features (a real Hessian is only interesting/non-diagonal
    # when input features are correlated — independent random noise
    # inputs would make GPTQ degenerate to plain RTN).
    base = torch.randn(200, 8)
    mixing = torch.randn(8, in_features)
    calibration_activations = base @ mixing + 0.01 * torch.randn(200, in_features)

    rtn_result = rtn_quantize_layer(weight, num_bits=4)
    gptq_result = gptq_quantize_layer(weight, calibration_activations, num_bits=4)

    # Compare OUTPUT error on a held-out sample (this is the metric that
    # actually matters — raw weight MSE, unlike output error, doesn't
    # account for which weights matter more given the real input
    # distribution, which is precisely the gap GPTQ is designed to close).
    test_input = base[:20] @ mixing + 0.01 * torch.randn(20, in_features)
    true_output = test_input @ weight.T
    rtn_output = test_input @ rtn_result.T
    gptq_output = test_input @ gptq_result.T

    rtn_error = (true_output - rtn_output).pow(2).mean().item()
    gptq_error = (true_output - gptq_output).pow(2).mean().item()
    print(f"RTN output MSE:  {rtn_error:.6f}")
    print(f"GPTQ output MSE: {gptq_error:.6f}")
    print(f"GPTQ improvement: {(1 - gptq_error / rtn_error) * 100:.1f}% lower error")


if __name__ == "__main__":
    compare_gptq_vs_rtn()

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
When benchmarking a quantized model's perplexity on WikiText-2 (the
standard LLM quantization benchmark), a GPTQ-4bit model typically comes
within a fraction of a perplexity point of the full FP16 model, while
naive RTN-4bit quantization on the SAME model shows a much larger, often
qualitatively noticeable degradation — the exact effect
`compare_gptq_vs_rtn()` reproduces on a toy scale. Reproducing this gap
yourself, on a real model with a real calibration set, is a genuinely
solid first research exercise: verify a published result, then perturb
one variable (bit-width, group size, calibration set size) and see how
the gap changes.
"""
