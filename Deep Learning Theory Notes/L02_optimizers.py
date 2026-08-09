"""
WHAT: SGD, Momentum, RMSProp, and Adam derived as successive refinements
      to plain gradient descent -- each addressing a specific, nameable
      failure mode of its predecessor, not an arbitrary "try this instead"
      progression.
WHY:  "Adam combines momentum and RMSProp" is a true one-liner that
      explains nothing about WHY that combination works or what problem
      each half solves. This lesson derives each optimizer's update rule
      from the specific pathology it fixes, using a concrete loss surface
      (a narrow ravine) where you can SEE plain SGD fail and each upgrade
      progressively fix it.
LEVEL: Foundational.

PREREQUISITE: L01 (backprop -- optimizers consume the gradients backprop
computes); Classical ML Theory Notes L01 (bias-variance, referenced for
why Adam's faster convergence isn't a free lunch).
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — PLAIN SGD AND ITS SPECIFIC FAILURE MODE: ILL-CONDITIONED
# (RAVINE-SHAPED) LOSS SURFACES
# ============================================================================
#
# Plain (stochastic) gradient descent: theta <- theta - lr * grad(theta).
# Consider a loss surface shaped like a narrow ravine -- steep in one
# direction, shallow in another (this happens whenever the Hessian's
# eigenvalues differ a lot in magnitude across directions, i.e. the
# problem is ILL-CONDITIONED; a classic real-world source is unstandard-
# ized features with very different scales, per Classical ML Theory
# Notes L02's regularization-scaling discussion, or just deep networks'
# naturally very different gradient magnitudes across layers/directions).
#
# On a ravine, a SINGLE learning rate must satisfy two conflicting
# demands: large enough to make progress along the shallow direction
# (small gradient there), small enough not to overshoot/oscillate along
# the steep direction (large gradient there). Any fixed lr that's stable
# for the steep direction is painfully slow along the shallow one, and
# any lr fast enough for the shallow direction causes the steep direction
# to OSCILLATE back and forth across the ravine walls rather than
# smoothly descending -- wasting most of each step's movement on
# zig-zagging rather than net progress toward the minimum.

def ravine_loss(xy):
    """f(x,y) = x^2 + 25*y^2 -- steep in y (coefficient 25), shallow in x
    (coefficient 1). A textbook ill-conditioned quadratic ravine."""
    x, y = xy
    return x ** 2 + 25 * y ** 2


def ravine_grad(xy):
    x, y = xy
    return np.array([2 * x, 50 * y])


def plain_sgd(grad_fn, start, lr, n_steps):
    theta = np.array(start, dtype=float)
    path = [theta.copy()]
    for _ in range(n_steps):
        theta = theta - lr * grad_fn(theta)
        path.append(theta.copy())
    return np.array(path)


# ============================================================================
# CONCEPT #2 — MOMENTUM: DAMPING OSCILLATION BY ACCUMULATING A "VELOCITY"
# ============================================================================
#
# Momentum maintains an exponential moving average of past gradients (a
# velocity vector v), and updates theta using v instead of the raw
# gradient:
#   v <- beta*v + (1-beta)*grad(theta)      (or, in a common convention,
#                                            v <- beta*v + grad(theta),
#                                            with lr absorbing the scale)
#   theta <- theta - lr*v
#
# WHY THIS SPECIFICALLY FIXES THE RAVINE PROBLEM: along the STEEP
# direction, successive gradients OSCILLATE in sign (overshoot right,
# then left, then right...) -- averaging them (via the exponential moving
# average) causes these opposite-sign contributions to PARTIALLY CANCEL,
# damping the oscillation. Along the SHALLOW direction, successive
# gradients point in a CONSISTENT direction (steady progress, no sign
# flips) -- averaging them REINFORCES/ACCUMULATES rather than cancels,
# so the effective step size in that direction actually GROWS over
# iterations (a "rolling start" effect, exactly the physical momentum
# analogy the name is chosen for). Net effect: net movement toward the
# minimum accelerates precisely in the direction that most needs it,
# while the wasteful oscillation gets damped -- a solution derived
# directly from the failure mode's SIGN STRUCTURE, not just "add
# smoothing because it sounds reasonable."

def momentum_sgd(grad_fn, start, lr, beta, n_steps):
    theta = np.array(start, dtype=float)
    v = np.zeros_like(theta)
    path = [theta.copy()]
    for _ in range(n_steps):
        g = grad_fn(theta)
        v = beta * v + (1 - beta) * g
        theta = theta - lr * v
        path.append(theta.copy())
    return np.array(path)


# ============================================================================
# CONCEPT #3 — RMSPROP: PER-PARAMETER ADAPTIVE LEARNING RATES (fixing a
# DIFFERENT failure mode -- differing gradient MAGNITUDES across
# parameters, not just sign oscillation)
# ============================================================================
#
# Momentum smooths the DIRECTION of movement but still applies the SAME
# scalar learning rate to every parameter. On the ravine, the y-direction
# still needs a fundamentally SMALLER effective step size than x
# (because its gradient magnitude, ~50y, is intrinsically ~25x larger
# than x's, ~2x) -- momentum alone doesn't rescale per-direction, it only
# smooths the accumulated direction.
#
# RMSProp maintains a per-parameter exponential moving average of SQUARED
# gradients (a running estimate of each parameter's typical gradient
# MAGNITUDE, ignoring sign), then divides the (raw or momentum-averaged)
# gradient by the square root of this running average:
#   s <- gamma*s + (1-gamma)*grad(theta)^2      (elementwise square)
#   theta <- theta - lr * grad(theta) / (sqrt(s) + epsilon)
#
# WHY THIS FIXES THE MAGNITUDE-DISPARITY PROBLEM: a parameter whose
# gradients are consistently LARGE (steep direction, large s) gets its
# effective step size SHRUNK (dividing by a large sqrt(s)); a parameter
# whose gradients are consistently SMALL (shallow direction, small s)
# gets its effective step size correspondingly GROWN (dividing by a
# small sqrt(s)) -- automatically normalizing each parameter's step to a
# roughly comparable scale, REGARDLESS of that direction's intrinsic
# gradient magnitude. This is a genuinely different mechanism from
# momentum (per-direction RESCALING vs. per-direction SMOOTHING), which
# is exactly why combining both (Concept #4) addresses two independent
# failure modes rather than redundantly re-solving the same one.

def rmsprop(grad_fn, start, lr, gamma, n_steps, eps=1e-8):
    theta = np.array(start, dtype=float)
    s = np.zeros_like(theta)
    path = [theta.copy()]
    for _ in range(n_steps):
        g = grad_fn(theta)
        s = gamma * s + (1 - gamma) * g ** 2
        theta = theta - lr * g / (np.sqrt(s) + eps)
        path.append(theta.copy())
    return np.array(path)


# ============================================================================
# CONCEPT #4 — ADAM: MOMENTUM'S DIRECTIONAL SMOOTHING + RMSPROP'S
# PER-PARAMETER RESCALING, PLUS BIAS CORRECTION
# ============================================================================
#
# Adam (Adaptive Moment Estimation) maintains BOTH moving averages:
#   m <- beta1*m + (1-beta1)*grad(theta)          (first moment: like momentum's v)
#   s <- beta2*s + (1-beta2)*grad(theta)^2         (second moment: like RMSProp's s)
#
# BIAS CORRECTION -- a detail usually glossed over, but mechanically
# necessary: m and s are initialized to ZERO, and an exponential moving
# average initialized at zero is systematically BIASED TOWARD ZERO in
# its early iterations (a moving average that starts at 0 needs several
# steps before it "catches up" to the true running average, especially
# with beta1/beta2 close to 1, which weight recent-and-past history
# heavily). Adam corrects for this explicitly:
#   m_hat = m / (1 - beta1^t)
#   s_hat = s / (1 - beta2^t)
# where t is the current step number. As t grows, beta1^t and beta2^t
# shrink toward 0, so the correction factor shrinks toward 1 -- the
# correction matters most in EARLY training (exactly when the zero-
# initialization bias is worst) and fades out naturally as training
# proceeds, without needing a separate schedule.
#
# FINAL UPDATE:
#   theta <- theta - lr * m_hat / (sqrt(s_hat) + epsilon)
#
# This directly combines Concept #2's directional smoothing (via m_hat)
# with Concept #3's per-parameter magnitude rescaling (via s_hat) -- Adam
# isn't "yet another optimizer variant," it's the specific combination of
# two INDEPENDENT fixes for two INDEPENDENT failure modes of plain SGD,
# plus a bias-correction detail that matters primarily in early training.
#
# WHY ADAM'S FASTER CONVERGENCE ISN'T A FREE LUNCH (tying back to
# Classical ML Theory Notes L01's bias-variance framing): Adam's adaptive
# per-parameter step sizes can cause it to converge to a SHARPER minimum
# of the training loss than plain SGD with momentum would -- and there is
# real, published empirical evidence (not universal, but well-documented)
# that sharper minima can generalize WORSE than the flatter minima SGD
# tends to find, particularly on some vision benchmarks. This is why
# "Adam trains faster" and "Adam generalizes at least as well as SGD" are
# NOT the same claim -- many production computer-vision pipelines still
# default to SGD+momentum (sometimes with a carefully-tuned learning-rate
# schedule) specifically for its generalization properties, accepting
# slower/more finicky convergence, while Adam dominates in domains (like
# transformer/LLM pretraining, this repo's LLM Core Theory Notes) where
# training speed and stability at massive scale outweigh Adam's
# generalization-gap risk.

def adam(grad_fn, start, lr, beta1, beta2, n_steps, eps=1e-8):
    theta = np.array(start, dtype=float)
    m = np.zeros_like(theta)
    s = np.zeros_like(theta)
    path = [theta.copy()]
    for t in range(1, n_steps + 1):
        g = grad_fn(theta)
        m = beta1 * m + (1 - beta1) * g
        s = beta2 * s + (1 - beta2) * g ** 2
        m_hat = m / (1 - beta1 ** t)   # bias correction
        s_hat = s / (1 - beta2 ** t)
        theta = theta - lr * m_hat / (np.sqrt(s_hat) + eps)
        path.append(theta.copy())
    return np.array(path)


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A team fine-tuning a pretrained vision model observes that switching
# their optimizer from Adam (used for the original pretraining) to
# SGD+momentum for the fine-tuning phase measurably improves validation
# accuracy, despite Adam converging faster on the fine-tuning LOSS during
# training. This is a direct, real instance of Concept #4's "faster
# convergence isn't a free lunch" point -- the correct diagnostic
# response is NOT to assume a bug, but to check a LEARNING CURVE showing
# train vs. validation loss for both optimizers: if Adam's train loss is
# lower but validation loss is higher than SGD+momentum's, that's
# consistent with published sharp-vs-flat-minima findings, and the
# practical fix (switch optimizers for fine-tuning, or add explicit
# regularization/weight-decay tuning specifically for Adam) is a direct,
# evidence-based consequence of this lesson's Concept #4, not a matter of
# guessing at hyperparameters.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Treating Adam as a strictly-better replacement for SGD+momentum in
#    every setting. Per Concept #4, this is an empirically contested
#    claim specifically around generalization, not a settled fact --
#    always validate the CHOICE of optimizer against a held-out metric,
#    not just training-loss convergence speed.
# 2. Implementing Adam without bias correction ("it barely matters").
#    Skipping it specifically distorts the FIRST FEW iterations of
#    training (systematically underestimating both moments, since they
#    start at zero) -- for short training runs or very sensitive early-
#    training dynamics (common in fine-tuning with few steps), this can
#    matter substantially, not negligibly.
# 3. Using a single global learning rate across momentum/RMSProp/Adam
#    hyperparameter defaults without considering they interact. Momentum
#    (beta1) close to 1 means slow adaptation to gradient direction
#    CHANGES -- combined with a learning rate tuned assuming a less
#    "sluggish" optimizer, this can cause the optimizer to overshoot a
#    minimum it's approaching from a now-stale direction estimate.
#    Optimizer hyperparameters are not independent knobs to tune one at
#    a time in isolation.
# 4. Assuming a ravine-shaped loss surface (this lesson's toy example) is
#    an unrealistic contrivance. Real deep network loss landscapes are
#    routinely, severely ill-conditioned (very different curvature in
#    different directions) -- this is precisely WHY these optimizers
#    exist and matter in practice, not a simplified toy that doesn't
#    generalize to real training.


if __name__ == "__main__":
    start = [-4.0, 1.0]
    n_steps = 60

    print("=" * 70)
    print("PLAIN SGD on a ravine: watch y oscillate while x crawls")
    print("=" * 70)
    # lr=0.025 makes the y-update multiplier (1 - lr*50) = -0.25: each step
    # OVERSHOOTS past zero and flips sign, decaying slowly -- real
    # oscillation, not the lr=0.02 knife-edge that happens to zero out y
    # in exactly one step (multiplier exactly 0) and looks deceptively clean.
    path_sgd = plain_sgd(ravine_grad, start, lr=0.025, n_steps=n_steps)
    print(f"Start:  {path_sgd[0]}")
    print(f"Step 10: {np.round(path_sgd[10], 4)}")
    print(f"Step 30: {np.round(path_sgd[30], 4)}")
    print(f"Final:  {np.round(path_sgd[-1], 4)}   (target: [0,0])")
    y_sign_changes = np.sum(np.diff(np.sign(path_sgd[:, 1])) != 0)
    print(f"Number of sign changes in y (oscillation count): {y_sign_changes}")

    print("\n" + "=" * 70)
    print("MOMENTUM on the same ravine: fewer oscillations, more net progress")
    print("=" * 70)
    path_mom = momentum_sgd(ravine_grad, start, lr=0.02, beta=0.9, n_steps=n_steps)
    print(f"Final:  {np.round(path_mom[-1], 4)}")
    y_sign_changes_mom = np.sum(np.diff(np.sign(path_mom[:, 1])) != 0)
    print(f"Number of sign changes in y (oscillation count): {y_sign_changes_mom}")
    print(f"Distance to origin -- SGD: {np.linalg.norm(path_sgd[-1]):.4f}, "
          f"Momentum: {np.linalg.norm(path_mom[-1]):.4f}")

    print("\n" + "=" * 70)
    print("ADAM on the same ravine: fast, stable convergence via both mechanisms")
    print("=" * 70)
    path_adam = adam(ravine_grad, start, lr=0.3, beta1=0.9, beta2=0.999, n_steps=n_steps)
    print(f"Final:  {np.round(path_adam[-1], 4)}")
    print(f"Distance to origin -- Adam: {np.linalg.norm(path_adam[-1]):.6f}")
    print("-> Adam should reach the origin fastest and most directly of the three,")
    print("   combining momentum's directional smoothing with per-parameter rescaling.")
