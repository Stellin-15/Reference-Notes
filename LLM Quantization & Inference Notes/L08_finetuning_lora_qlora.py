# ============================================================
# L08: Fine-Tuning — Full FT, LoRA, and QLoRA Derived From Scratch
# ============================================================
# WHAT: Full fine-tuning's memory cost breakdown, LoRA's low-rank
#       adaptation trick derived mathematically, and QLoRA (LoRA on top
#       of a QUANTIZED frozen base model) — the direct bridge between
#       "training" (Phase 2) and "quantization" (Phase 3).
# WHY: QLoRA is the single technique that makes both of your stated goals
#      concrete at once: it's a genuine research contribution (published
#      at NeurIPS) AND it's the exact reason a consumer GPU can fine-tune
#      a 70B model at all. This lesson is the hinge of the whole curriculum.
# LEVEL: Intermediate (Phase 2 of 8 — final lesson before quantization)
# ============================================================

"""
CONCEPT OVERVIEW:
Full fine-tuning updates EVERY parameter, which means AdamW (L06) must
store a first AND second moment estimate for every parameter — for a 7B
model in FP16 weights (14GB) plus FP32 AdamW states (2 * 4 bytes *
7B = 56GB) plus gradients (14GB), full fine-tuning needs on the order of
84GB+ just for optimizer state, before activations — completely infeasible
on a single consumer GPU.

LoRA (Low-Rank Adaptation) freezes the ORIGINAL weight matrix W entirely
and instead learns a small ADDITIVE update: W' = W + BA, where B is
(d_out x r) and A is (r x d_in), with r (the "rank") MUCH smaller than
d_in/d_out — often 8, 16, or 64 versus a hidden dimension of thousands.
The key insight (empirically validated, not just assumed) is that the
WEIGHT UPDATE needed to adapt a pretrained model to a new task has low
"intrinsic rank" — you don't need a full-rank update to capture most of
the useful adaptation. Since W is frozen, you only need optimizer state
for A and B — a tiny fraction of the original parameter count.

QLoRA extends this one step further: the FROZEN base model W is stored in
4-bit quantized form (NF4 — a data type introduced specifically for this
paper, covered in depth in Phase 4), and ONLY the small LoRA matrices A/B
are trained in full precision (typically BF16). This is what lets you
fine-tune a 65B-parameter model on a single 48GB GPU — the frozen weights
take ~1/4 the memory of FP16, and the trainable parameters are a tiny
fraction of the total.

PRODUCTION/RESEARCH USE CASE:
Every "fine-tune this model on your data with limited GPU memory" workflow
you'll ever run uses exactly this technique. Understanding it here — the
actual matrix decomposition math, not just calling a `peft` library
function — is what lets you later design your OWN parameter-efficient
fine-tuning variant if your research takes you there.

COMMON MISTAKES:
- Setting LoRA rank `r` too high "to be safe" — this defeats much of the
  memory savings and, past a certain point, doesn't meaningfully improve
  task performance (the whole premise is that the useful update IS low-
  rank; an oversized r just wastes memory approximating something already
  well-approximated by a smaller r).
- Forgetting that during INFERENCE, `B @ A` can be MERGED back into W
  (W_merged = W + BA) — after merging, there's zero extra inference
  latency from having used LoRA at all, an important production detail.
- Confusing "quantizing the frozen base model" (QLoRA's actual technique)
  with "quantizing the LoRA adapters themselves" — QLoRA specifically
  keeps A/B in higher precision because they're being actively trained;
  quantizing weights under active gradient updates without care
  reintroduces exactly the QAT complexity from Phase 3.
"""

import torch
import torch.nn as nn


# ------------------------------------------------------------------
# 1. Memory cost comparison — full fine-tuning vs LoRA vs QLoRA
# ------------------------------------------------------------------
def full_finetune_memory_gb(num_params: int) -> dict:
    # Weights (FP16) + gradients (FP16) + AdamW moments (FP32 x2)
    weights = num_params * 2
    gradients = num_params * 2
    optimizer_states = num_params * 4 * 2   # m and v, both FP32
    total = weights + gradients + optimizer_states
    return {"weights_gb": weights / 1e9, "gradients_gb": gradients / 1e9,
            "optimizer_gb": optimizer_states / 1e9, "total_gb": total / 1e9}


def lora_memory_gb(num_params: int, trainable_params: int) -> dict:
    # Frozen base weights (FP16, no gradient, no optimizer state) +
    # LoRA A/B weights (FP16) + their gradients + their AdamW states.
    frozen_weights = num_params * 2
    lora_weights = trainable_params * 2
    lora_gradients = trainable_params * 2
    lora_optimizer = trainable_params * 4 * 2
    total = frozen_weights + lora_weights + lora_gradients + lora_optimizer
    return {"frozen_weights_gb": frozen_weights / 1e9,
            "lora_overhead_gb": (lora_weights + lora_gradients + lora_optimizer) / 1e9,
            "total_gb": total / 1e9}


def qlora_memory_gb(num_params: int, trainable_params: int) -> dict:
    # Frozen base weights in 4-bit (0.5 bytes/param) instead of FP16.
    frozen_weights = num_params * 0.5
    lora_weights = trainable_params * 2
    lora_gradients = trainable_params * 2
    lora_optimizer = trainable_params * 4 * 2
    total = frozen_weights + lora_weights + lora_gradients + lora_optimizer
    return {"frozen_weights_gb": frozen_weights / 1e9,
            "lora_overhead_gb": (lora_weights + lora_gradients + lora_optimizer) / 1e9,
            "total_gb": total / 1e9}


def compare_finetuning_memory():
    num_params = 7_000_000_000       # a 7B model
    trainable = 20_000_000            # typical LoRA trainable param count (~0.3%)

    full = full_finetune_memory_gb(num_params)
    lora = lora_memory_gb(num_params, trainable)
    qlora = qlora_memory_gb(num_params, trainable)

    print(f"Full fine-tune: {full['total_gb']:.1f} GB total "
          f"(weights={full['weights_gb']:.1f}, grads={full['gradients_gb']:.1f}, "
          f"optimizer={full['optimizer_gb']:.1f})")
    print(f"LoRA:           {lora['total_gb']:.1f} GB total "
          f"(frozen={lora['frozen_weights_gb']:.1f}, lora_overhead={lora['lora_overhead_gb']:.2f})")
    print(f"QLoRA:          {qlora['total_gb']:.1f} GB total "
          f"(frozen={qlora['frozen_weights_gb']:.1f}, lora_overhead={qlora['lora_overhead_gb']:.2f})")
    # QLoRA's frozen weights alone are smaller than LoRA's LoRA-only
    # OVERHEAD magnitude comparison makes clear why QLoRA is the technique
    # that actually fits large models on consumer hardware.


# ------------------------------------------------------------------
# 2. LoRA layer implementation
# ------------------------------------------------------------------
class LoRALinear(nn.Module):
    """
    Wraps a frozen base Linear layer with a trainable low-rank update.
    Forward pass: y = x @ W^T + (alpha/r) * x @ A^T @ B^T
    """

    def __init__(self, base_layer: nn.Linear, rank: int, alpha: float = 16.0):
        super().__init__()
        self.base_layer = base_layer
        for p in self.base_layer.parameters():
            p.requires_grad = False   # FREEZE the original weight entirely

        d_out, d_in = base_layer.weight.shape
        self.rank = rank
        self.scaling = alpha / rank   # scales the LoRA contribution

        # A is initialized with small random values (Kaiming-like); B is
        # initialized to EXACTLY ZERO. This ensures that at the start of
        # training, B @ A = 0, so the LoRA-augmented model is IDENTICAL
        # to the original frozen model — training starts from the
        # pretrained behavior, not a randomly perturbed one.
        self.lora_A = nn.Parameter(torch.randn(rank, d_in) * 0.01)
        self.lora_B = nn.Parameter(torch.zeros(d_out, rank))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        base_out = self.base_layer(x)                          # frozen path
        lora_out = (x @ self.lora_A.T) @ self.lora_B.T          # low-rank path
        return base_out + self.scaling * lora_out

    def merge_into_base(self):
        """
        Folds the LoRA update directly into the base weight — after this,
        inference has ZERO extra cost from having used LoRA at all. This
        is the standard "export a fine-tuned model" step in production.
        """
        with torch.no_grad():
            delta_w = self.scaling * (self.lora_B @ self.lora_A)
            self.base_layer.weight.add_(delta_w)


def count_trainable_vs_frozen(model: nn.Module):
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    frozen = sum(p.numel() for p in model.parameters() if not p.requires_grad)
    print(f"trainable params: {trainable:,}  ({100 * trainable / (trainable + frozen):.3f}% of total)")
    print(f"frozen params:    {frozen:,}")


if __name__ == "__main__":
    compare_finetuning_memory()
    print()

    torch.manual_seed(0)
    base = nn.Linear(4096, 4096, bias=False)
    lora_layer = LoRALinear(base, rank=16, alpha=32)

    x = torch.randn(2, 10, 4096)
    out_before_merge = lora_layer(x)

    count_trainable_vs_frozen(lora_layer)

    # Verify merging preserves the forward pass output exactly (up to
    # floating point rounding) — this is the correctness property that
    # makes "train with LoRA, merge for deployment" a safe workflow.
    lora_layer.merge_into_base()
    out_after_merge = lora_layer.base_layer(x)
    max_diff = (out_before_merge - out_after_merge).abs().max().item()
    print(f"max difference after merge: {max_diff:.2e}  (should be ~0)")

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
In Phase 4, when you implement NF4 (QLoRA's custom 4-bit data type), you
will literally be building the `frozen_weights` quantization scheme used
in `qlora_memory_gb()` above — the memory arithmetic here is not a
simplification for teaching purposes, it is the actual constraint that
motivated the paper's authors to design a NEW 4-bit format instead of
reusing an existing INT4 scheme, because NF4 is specifically tuned to the
near-Gaussian distribution of pretrained transformer weights.
"""
