# ============================================================
# L10: Mixed Precision Training at Scale — Loss Scaling, Numerical Stability
# ============================================================
# WHAT: FP16/BF16 training in DISTRIBUTED settings specifically — loss
#       scaling to prevent gradient underflow, and the numerical
#       stability considerations that become MORE complex once gradients
#       are being averaged (AllReduce, L07) across many GPUs.
# WHY: This repo's LLM Quantization & Inference Notes L02/L06 covered
#      FP16/BF16 representation and basic mixed-precision training
#      single-GPU. This lesson covers what CHANGES when mixed precision
#      meets DISTRIBUTED training — loss scaling interacts with gradient
#      synchronization in ways that matter for correctness at scale.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
RECAP (from LLM Quantization & Inference Notes L02): FP16 has a narrow
EXPONENT range compared to FP32/BF16 — small gradient values can
UNDERFLOW to exactly zero in FP16 representation, silently destroying
gradient information. LOSS SCALING fixes this: multiply the loss by a
large constant (e.g. 1024 or higher) BEFORE calling `.backward()`,
which proportionally scales up EVERY gradient throughout the network
(since gradients are computed via the chain rule, scaling the loss
scales every gradient by the same factor) — pushing small gradients up
and out of FP16's underflow range — then DIVIDE the gradients back down
by that same factor AFTER backward(), before the optimizer step, so the
actual parameter update magnitude is correct.

DYNAMIC LOSS SCALING (used by PyTorch's `torch.cuda.amp.GradScaler`)
automatically ADJUSTS the scale factor during training: it starts with
a large scale, and if it ever detects an INF/NaN in the gradients
(indicating the scale was too aggressive, causing OVERFLOW instead of
preventing underflow), it SKIPS that optimizer step and reduces the
scale factor — conversely, if many consecutive steps pass without
overflow, it periodically INCREASES the scale, seeking the largest scale
that doesn't cause overflow (maximizing protection against underflow
without the destabilizing effect of overflow).

IN A DISTRIBUTED (multi-GPU) SETTING, this interacts directly with
gradient AllReduce (L07): the standard, correct order of operations is
(1) each GPU computes its LOCAL, scaled gradients, (2) AllReduce
averages the SCALED gradients across GPUs (still scaled — the scale
factor cancels out identically on every GPU since it's a shared
constant, so averaging scaled gradients gives the same relative result
as averaging unscaled ones would), (3) THEN unscale (divide by the
scale factor) and check for inf/NaN, (4) apply the optimizer step. A
subtle but important detail: with DYNAMIC loss scaling, ALL GPUs must
AGREE on whether an overflow occurred (since they all need to either
skip or apply the SAME optimizer step to remain synchronized) — this
requires an additional small communication step (an AllReduce or
similar) specifically to synchronize the overflow-detection FLAG across
GPUs, not just the gradients themselves; PyTorch's `GradScaler` handles
this automatically when used correctly with DDP, but understanding that
this additional synchronization exists explains certain distributed-
training-specific edge cases.

BF16, as covered in LLM Quantization & Inference Notes L02, has FP32's
full EXPONENT RANGE — meaning BF16 training generally does NOT need loss
scaling at all (the underflow problem loss scaling solves is specific to
FP16's narrow exponent range) — this is a major practical reason BF16
has become the more common default for large-scale distributed training
specifically: one less numerically-fragile mechanism (dynamic loss
scaling, with its overflow-detection synchronization complexity) to
reason about at scale.

PRODUCTION USE CASE:
A large distributed training run using FP16 mixed precision
occasionally experiences a training step with NaN loss — GradScaler's
automatic overflow detection catches this, skips that specific
optimizer step (across ALL GPUs synchronously, thanks to the shared
overflow flag), reduces the scale factor, and training continues without
manual intervention — the SAME run, switched to BF16, never encounters
this failure mode at all, since BF16's wider exponent range doesn't need
the aggressive up-scaling that creates the overflow risk in the first place.

COMMON MISTAKES:
- Using STATIC (fixed) loss scaling instead of PyTorch's dynamic
  GradScaler — a fixed scale that's too small doesn't sufficiently
  address underflow; too large, and it causes overflow on some steps
  with no automatic recovery mechanism.
- Not understanding that in distributed training, the overflow-detection
  DECISION must be SYNCHRONIZED across all GPUs — implementing custom
  mixed-precision logic without this synchronization can cause GPUs to
  diverge (some skip a step, others don't), silently corrupting the
  "every GPU has an identical model" invariant data parallelism depends on.
- Defaulting to FP16 for new large-scale training work when BF16 is
  available and appropriate — BF16's simpler numerical story (no loss
  scaling needed at all, in most cases) is a genuine operational
  simplification at scale, not just a marginal preference.
"""

import torch
import textwrap


# ------------------------------------------------------------------
# 1. Loss scaling, illustrated with real PyTorch AMP
# ------------------------------------------------------------------
AMP_TRAINING_LOOP_EXAMPLE = textwrap.dedent("""\
    import torch
    from torch.cuda.amp import autocast, GradScaler

    model = MyModel().cuda()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-4)
    scaler = GradScaler()   # DYNAMIC loss scaling, auto-adjusting

    for batch in dataloader:
        optimizer.zero_grad()

        with autocast():   # runs the forward pass in FP16 where safe,
                             # FP32 where numerically necessary
            output = model(batch)
            loss = compute_loss(output)

        scaler.scale(loss).backward()   # SCALES the loss before backward()
                                           # — every gradient is proportionally
                                           # scaled up too, preventing FP16 underflow

        scaler.unscale_(optimizer)   # divides gradients back down before
                                       # the optimizer sees them
        # (GradScaler internally checks for inf/NaN at this point)

        scaler.step(optimizer)   # applies the optimizer step ONLY if no
                                   # overflow was detected; SKIPS it otherwise
        scaler.update()           # adjusts the scale factor for next time —
                                   # increases if stable, decreases after an overflow
""")

# ------------------------------------------------------------------
# 2. Dynamic scale adjustment logic, simplified illustration
# ------------------------------------------------------------------
class SimplifiedDynamicScaler:
    """A simplified reimplementation of GradScaler's core adaptive logic,
    for illustrating the mechanism explicitly."""

    def __init__(self, initial_scale: float = 2**16, growth_factor: float = 2.0,
                 backoff_factor: float = 0.5, growth_interval: int = 2000):
        self.scale = initial_scale
        self.growth_factor = growth_factor
        self.backoff_factor = backoff_factor
        self.growth_interval = growth_interval
        self.steps_since_last_overflow = 0

    def check_overflow_and_update(self, gradients_had_inf_or_nan: bool):
        if gradients_had_inf_or_nan:
            self.scale *= self.backoff_factor   # scale was TOO aggressive — reduce it
            self.steps_since_last_overflow = 0
            return False   # signal: SKIP this optimizer step
        else:
            self.steps_since_last_overflow += 1
            if self.steps_since_last_overflow >= self.growth_interval:
                self.scale *= self.growth_factor   # stable for a while — try a larger scale
                self.steps_since_last_overflow = 0
            return True   # signal: proceed with this optimizer step


def dynamic_scaling_demo():
    scaler = SimplifiedDynamicScaler(initial_scale=1024, growth_interval=3)
    overflow_pattern = [False, False, False, True, False, False, False]

    for step, had_overflow in enumerate(overflow_pattern):
        proceed = scaler.check_overflow_and_update(had_overflow)
        action = "SKIP step (overflow detected)" if not proceed else "apply step"
        print(f"  step {step}: overflow={had_overflow} -> {action}, "
              f"scale now {scaler.scale:.0f}")


# ------------------------------------------------------------------
# 3. Distributed synchronization of the overflow flag
# ------------------------------------------------------------------
DISTRIBUTED_OVERFLOW_SYNC_NOTE = textwrap.dedent("""\
    In a multi-GPU setting, if GPU 3's gradients overflow but GPU 0-2's
    don't, ALL GPUs must still make the SAME decision (skip or proceed)
    — otherwise GPU 3 skips the optimizer step while GPUs 0-2 apply it,
    and the models silently DIVERGE (breaking data parallelism's core
    invariant that every replica stays identical).

    PyTorch's GradScaler, used correctly with DistributedDataParallel,
    handles this by checking for inf/NaN AFTER the gradient AllReduce
    (L07) has already happened — since an inf/NaN in ANY GPU's local
    gradient PROPAGATES through the AllReduce sum to EVERY GPU's result,
    every GPU sees the SAME (now inf/NaN-containing) averaged gradient,
    and therefore reaches the SAME skip/proceed decision independently,
    without needing an EXTRA explicit synchronization step for the flag
    itself — a subtle but important correctness property of the AllReduce-
    then-check ordering.
""")


if __name__ == "__main__":
    print(AMP_TRAINING_LOOP_EXAMPLE)
    print("--- Dynamic scale adjustment demo ---")
    dynamic_scaling_demo()
    print()
    print(DISTRIBUTED_OVERFLOW_SYNC_NOTE)

"""
PRODUCTION CONTEXT EXAMPLE:
A large-scale distributed training run using FP16 with GradScaler
occasionally logs "step skipped due to overflow" a few times per epoch
— a normal, expected part of dynamic loss scaling's adaptive behavior,
not a bug — while the team's OTHER training run, using BF16 for a newer
model, never logs any skipped steps at all, a direct, observable
consequence of BF16's wider exponent range simply not needing the
aggressive up-scaling that creates FP16's occasional overflow risk.
"""
