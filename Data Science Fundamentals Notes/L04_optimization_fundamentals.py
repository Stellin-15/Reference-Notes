# ============================================================
# L04: Optimization Fundamentals — Gradient Descent and Beyond
# ============================================================
# WHAT: The mathematical optimization concepts underlying HOW machine
#       learning models actually learn — gradient descent, convexity,
#       learning rate tradeoffs, and common optimizer variants.
# WHY: This repo's ML Frameworks Notes and GPU Computing & Distributed
#      Training Notes both use terms like "gradient descent," "learning
#      rate," and "Adam optimizer" extensively, treating them as known —
#      this lesson builds the underlying mathematical intuition those
#      lessons assume.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
OPTIMIZATION, in the ML context, means finding the model PARAMETERS
(weights) that MINIMIZE a LOSS FUNCTION (a measure of how wrong the
model's predictions are). GRADIENT DESCENT is the workhorse algorithm:
compute the GRADIENT (the direction of steepest INCREASE) of the loss
function with respect to the parameters, then step the parameters in the
OPPOSITE direction (steepest decrease) — repeating until the loss
stops meaningfully decreasing.

The LEARNING RATE controls STEP SIZE in each gradient descent update — a
fundamental tradeoff: TOO LARGE a learning rate can cause the
optimization to OVERSHOOT the minimum, oscillating or diverging
entirely; TOO SMALL a learning rate converges reliably but painfully
slowly, potentially getting stuck making negligible progress within a
practical training time budget. This single hyperparameter is one of
the most consequential tuning choices in training any model.

A function is CONVEX if it has exactly ONE minimum (no other "valleys"
to get trapped in) — gradient descent is GUARANTEED to find the true
global minimum for a convex loss function (e.g. linear regression's
mean-squared-error loss). Most REAL neural network loss functions are
NON-convex (many local minima, saddle points) — gradient descent on
these is only guaranteed to find A local minimum, not necessarily the
best possible one, though empirically, for large neural networks, most
local minima found in practice tend to generalize reasonably well
regardless.

STOCHASTIC GRADIENT DESCENT (SGD) computes the gradient on a small
random MINI-BATCH of data rather than the entire dataset each step —
trading some gradient-estimate NOISE for dramatically faster iteration
(this repo's GPU Computing & Distributed Training Notes L04 builds
directly on this: mini-batches are what get distributed across multiple
GPUs). MOMENTUM (accumulating a running average of past gradients)
smooths out this noise and helps push through small local irregularities
in the loss surface. ADAM (Adaptive Moment Estimation) combines momentum
with PER-PARAMETER adaptive learning rates, and is the most commonly
used optimizer for training deep neural networks in practice today.

PRODUCTION USE CASE:
Training a large language model (this repo's LLM Quantization &
Inference Notes' broader context) uses Adam (or a variant like AdamW)
with a LEARNING RATE SCHEDULE — starting with a "warmup" period of small
learning rates (avoiding destabilizing large early updates before the
model has learned anything reasonable), then a larger rate for the bulk
of training, then DECAYING the rate toward the end (allowing the
optimization to settle precisely into a good minimum rather than
continuing to oscillate around it at a fixed step size).

COMMON MISTAKES:
- Setting a fixed, high learning rate for the ENTIRE training run — this
  frequently prevents the model from CONVERGING precisely at the end of
  training, even if it learns quickly early on; a decaying learning-rate
  schedule (or Adam's adaptive behavior) addresses this directly.
- Assuming gradient descent finding SOME minimum for a non-convex loss
  function means it found the GLOBAL minimum — for neural networks this
  is not guaranteed, though in practice it's less catastrophic than it
  sounds (see the CONCEPT OVERVIEW's note on local minima generalizing well).
- Confusing "the loss decreased on the TRAINING batch" with "the model
  is actually getting better" — without also monitoring a held-out
  validation set's loss, a model can be OVERFITTING (memorizing training
  data specifics rather than learning generalizable patterns) while
  training loss keeps improving.
"""

import random


# ------------------------------------------------------------------
# 1. Gradient descent on a simple convex function
# ------------------------------------------------------------------
def loss_function(x: float) -> float:
    """A simple convex function: (x - 3)^2, minimized at x=3."""
    return (x - 3) ** 2


def gradient(x: float) -> float:
    """The derivative of (x-3)^2 is 2(x-3) — the direction of steepest increase."""
    return 2 * (x - 3)


def gradient_descent_demo(learning_rate: float, steps: int = 20) -> list[float]:
    x = 0.0   # arbitrary starting point
    history = [x]
    for _ in range(steps):
        grad = gradient(x)
        x = x - learning_rate * grad   # step OPPOSITE the gradient direction
        history.append(x)
    return history


def learning_rate_comparison_demo():
    print("Gradient descent toward the minimum of (x-3)^2, from x=0:\n")

    for lr, label in [(0.05, "too small"), (0.5, "well-tuned"), (1.1, "too large")]:
        history = gradient_descent_demo(learning_rate=lr, steps=10)
        final_x = history[-1]
        final_loss = loss_function(final_x)
        print(f"  Learning rate {lr} ({label}): "
              f"x after 10 steps = {final_x:.3f}, loss = {final_loss:.3f}")

    print("\n  -> Too small: barely moved after 10 steps (slow convergence).")
    print("  -> Well-tuned: converges close to the true minimum (x=3).")
    print("  -> Too large: OVERSHOOTS and OSCILLATES, potentially diverging further.")


# ------------------------------------------------------------------
# 2. Stochastic gradient descent with mini-batches (conceptual)
# ------------------------------------------------------------------
def sgd_with_momentum_demo():
    random.seed(0)
    x = 0.0
    velocity = 0.0
    momentum_coefficient = 0.9
    learning_rate = 0.1

    history = [x]
    for step in range(15):
        # Simulate NOISE from computing the gradient on a random mini-batch
        # rather than the full dataset (a small random perturbation added):
        noisy_gradient = gradient(x) + random.uniform(-0.5, 0.5)

        # Momentum: blend the new noisy gradient with the PAST accumulated velocity,
        # smoothing out the mini-batch noise rather than reacting to every fluctuation.
        velocity = momentum_coefficient * velocity + learning_rate * noisy_gradient
        x = x - velocity
        history.append(x)

    print(f"SGD + momentum final x after 15 noisy steps: {history[-1]:.3f} (target: 3.0)")
    print("  -> Momentum smooths past the per-step gradient noise inherent "
          "to mini-batch estimation, converging more reliably than raw "
          "noisy gradient steps would.")


if __name__ == "__main__":
    learning_rate_comparison_demo()
    print()
    sgd_with_momentum_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A team training a deep neural network observes training loss decreasing
steadily but validation loss WORSENING after epoch 10 — a classic
overfitting signature independent of the optimizer's convergence
behavior. Separately, an earlier run using a fixed, high learning rate
throughout training showed the LOSS OSCILLATING near the end rather than
settling — switching to a learning-rate schedule (Adam with a cosine
decay) resolved the oscillation, letting the model converge more
precisely into a lower-loss minimum in the training's final phase — two
DIFFERENT problems (overfitting vs optimizer convergence) that a team
unfamiliar with these fundamentals could easily conflate.
"""
