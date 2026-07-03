# ============================================================
# L06: The Training Loop, AdamW, and Learning Rate Schedules
# ============================================================
# WHAT: A complete, from-scratch training loop for the transformer built
#       in L05: loss computation, AdamW derived from first principles,
#       gradient clipping, LR warmup+decay, and mixed-precision training.
# WHY: Quantization-AWARE training (QAT, Phase 3) and QLoRA fine-tuning
#      (L08) are both just this SAME loop with specific modifications —
#      you can't understand what QAT changes if you don't have the
#      unmodified baseline loop solid first.
# LEVEL: Foundation (Phase 2 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
The training loop is: forward pass -> compute loss -> backward pass
(populate gradients) -> optimizer step (update weights using gradients)
-> zero gradients -> repeat. Everything interesting lives in the details:

AdamW maintains TWO running statistics per parameter: a first moment
(momentum — an exponential moving average of the gradient itself) and a
second moment (an exponential moving average of the SQUARED gradient).
The update divides the momentum by the square root of the second moment,
which gives each parameter its OWN effective learning rate that shrinks
for parameters with consistently large gradients and grows (relatively)
for parameters with small, consistent gradients. "W" in AdamW means
WEIGHT DECAY is applied directly to the weights (decoupled), not folded
into the gradient like the original Adam — this decoupling is what fixed
Adam's poor generalization compared to SGD with weight decay.

Mixed-precision training keeps a MASTER copy of weights in FP32 but does
the forward/backward pass in FP16/BF16 for speed and memory savings —
this is the FIRST place in this curriculum where you're deliberately
running a lower-precision computation while keeping a higher-precision
"ground truth" around, which is conceptually the exact same pattern as
"quantize for inference, but calibrate against the FP32/FP16 original,"
covered in Phase 3.

PRODUCTION/RESEARCH USE CASE:
Loss scaling (multiplying the loss by a large constant before backward,
then dividing gradients by that constant before the optimizer step) exists
specifically because FP16 has a narrow exponent range (see L02) — small
gradients can underflow to exactly zero in FP16 without it. This is the
single most common "my FP16 training doesn't converge" bug, and
understanding it here means you won't be confused later when quantization
schemes need their own analogous scale-factor bookkeeping.

COMMON MISTAKES:
- Forgetting `optimizer.zero_grad()` — gradients ACCUMULATE by default in
  PyTorch (this is even used deliberately for gradient accumulation, see
  below), so skipping this silently corrupts every subsequent step.
- Clipping gradients AFTER the optimizer step instead of before — clipping
  must happen after backward() but before step(), or it does nothing
  useful.
- Using a constant learning rate for the whole training run — LLM
  training is essentially always done with warmup (avoid instability from
  large early updates on randomly initialized weights) followed by decay
  (allow fine convergence later) — see the cosine schedule below.
"""

import math
import torch
import torch.nn as nn


# ------------------------------------------------------------------
# 1. AdamW from scratch (mirrors torch.optim.AdamW's actual update rule)
# ------------------------------------------------------------------
class AdamWFromScratch:
    def __init__(self, params, lr=1e-3, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.01):
        self.params = list(params)
        self.lr = lr
        self.beta1, self.beta2 = betas
        self.eps = eps
        self.weight_decay = weight_decay
        self.t = 0  # timestep, for bias correction
        # First moment (momentum) and second moment (variance) estimates,
        # one pair per parameter tensor, initialized to zero.
        self.m = [torch.zeros_like(p) for p in self.params]
        self.v = [torch.zeros_like(p) for p in self.params]

    @torch.no_grad()
    def step(self):
        self.t += 1
        for i, p in enumerate(self.params):
            if p.grad is None:
                continue
            g = p.grad

            # DECOUPLED weight decay — applied DIRECTLY to the weights,
            # not mixed into the gradient. This is the "W" in AdamW: it
            # means weight decay behaves like true L2 regularization
            # regardless of how Adam's adaptive scaling behaves, which is
            # NOT true of the original Adam's "L2 penalty inside the loss"
            # approach.
            p.mul_(1 - self.lr * self.weight_decay)

            # Update biased first and second moment estimates.
            self.m[i] = self.beta1 * self.m[i] + (1 - self.beta1) * g
            self.v[i] = self.beta2 * self.v[i] + (1 - self.beta2) * g.pow(2)

            # Bias correction: m/v are initialized at zero, so early
            # steps are biased toward zero — this correction compensates,
            # and its effect vanishes as t grows.
            m_hat = self.m[i] / (1 - self.beta1 ** self.t)
            v_hat = self.v[i] / (1 - self.beta2 ** self.t)

            # The actual parameter update: momentum direction, scaled
            # DOWN for dimensions with historically large gradient
            # variance (sqrt(v_hat) in the denominator) — this is what
            # gives every parameter its own adaptive effective step size.
            p.sub_(self.lr * m_hat / (v_hat.sqrt() + self.eps))

    def zero_grad(self):
        for p in self.params:
            if p.grad is not None:
                p.grad = None  # setting to None (not zero_()) avoids an
                                 # unnecessary memory write every step


# ------------------------------------------------------------------
# 2. Learning rate schedule — warmup + cosine decay
# ------------------------------------------------------------------
def cosine_with_warmup_lr(step: int, warmup_steps: int, total_steps: int,
                            max_lr: float, min_lr_ratio: float = 0.1) -> float:
    """
    Phase 1 (warmup): LR ramps LINEARLY from 0 to max_lr. This avoids
    large, destabilizing updates while weights are still near their
    random initialization and gradient estimates are noisy.

    Phase 2 (cosine decay): LR follows a cosine curve down to
    `min_lr_ratio * max_lr`, giving a smooth, monotonic decrease that
    empirically outperforms a hard step-decay for LLM pretraining.
    """
    if step < warmup_steps:
        return max_lr * step / max(1, warmup_steps)

    progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
    progress = min(progress, 1.0)
    cosine_decay = 0.5 * (1 + math.cos(math.pi * progress))
    min_lr = max_lr * min_lr_ratio
    return min_lr + (max_lr - min_lr) * cosine_decay


# ------------------------------------------------------------------
# 3. Gradient clipping — preventing exploding gradients
# ------------------------------------------------------------------
def clip_grad_norm(params, max_norm: float) -> float:
    """
    Computes the GLOBAL norm across ALL parameter gradients combined (not
    per-parameter), and scales every gradient down by the same factor if
    that global norm exceeds max_norm. This must run AFTER backward() and
    BEFORE optimizer.step() — clipping after the step has already been
    applied does nothing.
    """
    grads = [p.grad for p in params if p.grad is not None]
    total_norm = torch.sqrt(sum(g.pow(2).sum() for g in grads))
    clip_coef = max_norm / (total_norm + 1e-6)
    if clip_coef < 1:
        for g in grads:
            g.mul_(clip_coef)
    return total_norm.item()


# ------------------------------------------------------------------
# 4. Mixed precision training loop with gradient accumulation
# ------------------------------------------------------------------
def train_step(model, batch, targets, optimizer, scaler,
               accumulation_steps: int, step_in_accumulation: int):
    """
    A single micro-step of mixed-precision training with gradient
    accumulation — the pattern used to simulate a large effective batch
    size when GPU memory only fits a smaller per-step batch.
    """
    with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
        # BF16 forward/backward (see L02 for why BF16 avoids the FP16
        # overflow problem — this is precisely why most current LLM
        # training uses BF16 autocast and skips loss-scaling entirely,
        # unlike older FP16 mixed-precision recipes that NEEDED a
        # GradScaler to avoid gradient underflow).
        logits = model(batch)
        loss = nn.functional.cross_entropy(
            logits.view(-1, logits.size(-1)), targets.view(-1)
        )
        # Scale the loss DOWN by accumulation_steps so that summing
        # `accumulation_steps` backward() calls produces a gradient
        # equivalent to a single backward() on the full accumulated batch.
        loss = loss / accumulation_steps

    loss.backward()  # gradients ACCUMULATE into .grad across micro-steps

    is_last_micro_step = (step_in_accumulation == accumulation_steps - 1)
    if is_last_micro_step:
        clip_grad_norm(model.parameters(), max_norm=1.0)
        optimizer.step()
        optimizer.zero_grad()

    return loss.item() * accumulation_steps  # un-scale for logging


if __name__ == "__main__":
    torch.manual_seed(0)
    # Tiny sanity check: does AdamWFromScratch actually reduce a toy loss?
    w = torch.nn.Parameter(torch.tensor([3.0, -2.0]))
    target = torch.tensor([0.0, 0.0])
    opt = AdamWFromScratch([w], lr=0.1)

    for step in range(50):
        loss = ((w - target) ** 2).sum()
        loss.backward()
        opt.step()
        opt.zero_grad()
        if step % 10 == 0:
            print(f"step {step:2d}  loss={loss.item():.4f}  w={w.data.tolist()}")

    print("\nLR schedule sample (warmup=10, total=100, max_lr=1e-3):")
    for step in [0, 5, 10, 25, 50, 75, 100]:
        lr = cosine_with_warmup_lr(step, warmup_steps=10, total_steps=100, max_lr=1e-3)
        print(f"  step {step:3d}: lr={lr:.6f}")

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
Quantization-Aware Training (Phase 3) reuses THIS EXACT loop, with one
addition: a "fake quantize" operation is inserted into the forward pass
(round weights/activations to their quantized grid, then immediately
dequantize back to full precision) so the model's gradients "feel" the
effect of quantization error and adjust to compensate — everything else
(AdamW, LR schedule, gradient clipping, mixed precision) is unchanged
from what you just built here.
"""
