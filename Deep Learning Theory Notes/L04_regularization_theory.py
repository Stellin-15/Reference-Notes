"""
WHAT: Dropout derived as approximate ensemble averaging (tying directly
      back to Classical ML Theory Notes L03's bagging variance-reduction
      argument), weight decay's precise (non-)equivalence to L2
      regularization under Adam, and early stopping derived as an
      implicit capacity constraint.
WHY:  "Dropout prevents overfitting by randomly zeroing neurons" doesn't
      say WHY that specific mechanism reduces overfitting, or why "weight
      decay" and "L2 regularization" -- treated as synonyms in most
      tutorials -- are provably NOT the same thing once you're using
      Adam instead of plain SGD, a distinction with real practical
      consequences.
LEVEL: Foundational -- last of the "core mechanics" lessons before this
       domain's architecture-specific lessons (CNN, RNN, attention).

PREREQUISITE: Classical ML Theory Notes L01 (bias-variance), L03
(bagging's variance-reduction mechanism -- dropout's direct analogue);
L02 of this domain (optimizers -- necessary for the weight-decay-vs-L2
distinction under Adam).
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — DROPOUT AS APPROXIMATE BAGGING (a direct structural
# parallel to Classical ML Theory Notes L03)
# ============================================================================
#
# Dropout, at training time, independently zeroes each neuron's
# activation with probability p (a hyperparameter, commonly 0.5 for
# hidden layers), for EVERY forward pass:
#   mask ~ Bernoulli(1-p) per neuron, per forward pass
#   a_dropped = mask * a / (1-p)      <-- "inverted dropout": divide by
#                                          (1-p) at TRAIN time so that
#                                          E[a_dropped] = a, meaning no
#                                          rescaling is needed at
#                                          INFERENCE time
#
# THE DIRECT PARALLEL TO BAGGING (Classical ML Theory Notes L03): each
# forward pass through a dropout-enabled network, with a specific random
# mask, is EQUIVALENT to evaluating a DIFFERENT, thinner sub-network
# (only the non-zeroed neurons participate). Training with dropout is
# therefore approximately equivalent to training an EXPONENTIALLY LARGE
# ENSEMBLE of these thinned sub-networks SIMULTANEOUSLY, with extensive
# weight-sharing across ensemble members (every sub-network shares the
# same underlying weight tensor, just with different neurons masked
# out). At INFERENCE time (dropout disabled, using the full network with
# no masking), you get an approximation of AVERAGING the predictions of
# this whole implicit ensemble -- the same "average many independent
# models" variance-reduction mechanism from L03's bagging derivation,
# but implemented via a single network's stochastic training procedure
# rather than literally training B separate models.
#
# WHY THIS SPECIFICALLY REDUCES OVERFITTING (not just "adds noise"): a
# specific pathology dropout directly targets is CO-ADAPTATION -- neurons
# that only work well in the specific presence of certain OTHER specific
# neurons (a fragile, over-specialized joint pattern memorizing training-
# set idiosyncrasies). Because dropout randomly removes arbitrary subsets
# of neurons on every forward pass, no neuron can reliably depend on any
# specific set of co-workers being present -- each neuron is forced to be
# USEFUL somewhat independently/robustly, which is a direct, mechanistic
# explanation (not just an empirical correlation) for why dropout-trained
# features tend to generalize better.

def dropout_forward(a, p, training, rng):
    if not training or p == 0.0:
        return a
    mask = (rng.uniform(size=a.shape) > p).astype(a.dtype)
    return a * mask / (1 - p)  # inverted dropout: rescale at train time


def demonstrate_dropout_as_implicit_ensemble(n_samples=2000, seed=0):
    """
    Confirms E[dropout output] over many random masks equals the
    UNDROPPED activation -- the "no rescaling needed at inference" claim,
    verified numerically rather than asserted.
    """
    rng = np.random.default_rng(seed)
    a = rng.normal(5.0, 1.0, size=(10,))  # a fixed activation vector
    outputs = np.array([dropout_forward(a, p=0.5, training=True, rng=rng)
                         for _ in range(n_samples)])
    return a, outputs.mean(axis=0)


# ============================================================================
# CONCEPT #2 — WHY WEIGHT DECAY AND L2 REGULARIZATION ARE NOT THE SAME
# THING UNDER ADAM (a genuinely subtle, practically important distinction)
# ============================================================================
#
# UNDER PLAIN SGD, "add an L2 penalty to the loss" and "weight decay"
# (directly shrink weights by a fixed proportion each step, independent
# of the gradient computation) are MATHEMATICALLY IDENTICAL:
#   L2 regularization: L_total = L_data + (lambda/2)*||theta||^2
#     grad of L_total w.r.t. theta = grad(L_data) + lambda*theta
#     SGD update: theta <- theta - lr*(grad(L_data) + lambda*theta)
#                        = theta - lr*grad(L_data) - lr*lambda*theta
#   Weight decay:  theta <- theta - lr*grad(L_data) - lr*lambda*theta
#                                                       (same update, by definition)
# Identical under plain SGD -- this is why the two terms get used
# interchangeably in most intro material, and for SGD-based training that
# conflation is harmless.
#
# UNDER ADAM, THEY DIVERGE. Recall from L02: Adam divides the gradient
# by sqrt(s_hat) (a per-parameter ADAPTIVE scaling based on that
# parameter's recent squared-gradient history). If you implement "L2
# regularization" by adding lambda*theta to the GRADIENT before it enters
# Adam's moment-tracking machinery (the naive, "just add it to the loss"
# approach), the regularization term ITSELF gets divided by sqrt(s_hat)
# along with the data-loss gradient -- meaning parameters with LARGE
# historical gradient magnitude (large s_hat) get PROPORTIONALLY LESS
# regularization pressure than parameters with small gradient history,
# an effect with no principled justification (why should a parameter
# that historically had large gradients need LESS weight decay?).
#
# TRUE WEIGHT DECAY under Adam (the AdamW formulation, Loshchilov & Hutter
# 2017) instead applies the shrinkage term SEPARATELY and directly to the
# weights, AFTER Adam's adaptive gradient step, untouched by the
# adaptive-scaling machinery:
#   theta <- theta - lr*(Adam's adaptive update using ONLY grad(L_data))
#   theta <- theta - lr*lambda*theta        <-- decoupled weight decay,
#                                                applied uniformly,
#                                                independent of s_hat
#
# THIS IS WHY THE OPTIMIZER IS CALLED "AdamW" (Adam with decoupled Weight
# decay) AND IS THE DEFAULT IN VIRTUALLY ALL MODERN TRANSFORMER/LLM
# TRAINING CODE -- it is not a minor implementation detail; the
# Loshchilov-Hutter paper showed the naive L2-as-gradient-penalty
# approach under Adam measurably underperforms AdamW's decoupled version,
# specifically because of this s_hat-interaction distortion.

def adam_with_l2_penalty_naive(grad_fn, theta0, lr, beta1, beta2, lam, n_steps, eps=1e-8):
    """The NAIVE approach: add lambda*theta to the gradient BEFORE it
    enters Adam's moment tracking -- the regularization gets divided by
    sqrt(s_hat) along with the data gradient."""
    theta = np.array(theta0, dtype=float)
    m, s = np.zeros_like(theta), np.zeros_like(theta)
    path = [theta.copy()]
    for t in range(1, n_steps + 1):
        g = grad_fn(theta) + lam * theta  # L2 penalty folded into the gradient
        m = beta1 * m + (1 - beta1) * g
        s = beta2 * s + (1 - beta2) * g ** 2
        m_hat, s_hat = m / (1 - beta1 ** t), s / (1 - beta2 ** t)
        theta = theta - lr * m_hat / (np.sqrt(s_hat) + eps)
        path.append(theta.copy())
    return np.array(path)


def adamw_decoupled(grad_fn, theta0, lr, beta1, beta2, lam, n_steps, eps=1e-8):
    """AdamW: weight decay applied directly and separately, never entering
    the m/s moment-tracking machinery at all."""
    theta = np.array(theta0, dtype=float)
    m, s = np.zeros_like(theta), np.zeros_like(theta)
    path = [theta.copy()]
    for t in range(1, n_steps + 1):
        g = grad_fn(theta)  # NOTE: no lambda*theta folded in here
        m = beta1 * m + (1 - beta1) * g
        s = beta2 * s + (1 - beta2) * g ** 2
        m_hat, s_hat = m / (1 - beta1 ** t), s / (1 - beta2 ** t)
        theta = theta - lr * m_hat / (np.sqrt(s_hat) + eps)
        theta = theta - lr * lam * theta  # decoupled decay, applied directly
        path.append(theta.copy())
    return np.array(path)


# ============================================================================
# CONCEPT #3 — EARLY STOPPING AS AN IMPLICIT CAPACITY CONSTRAINT
# ============================================================================
#
# Early stopping (halt training when validation loss stops improving,
# even if training loss keeps dropping) is often described as "just a
# practical trick," but it has a real theoretical grounding directly
# connected to Classical ML Theory Notes L01's capacity/VC-dimension
# framing:
#
# For many models trained by iterative gradient descent, the EFFECTIVE
# number of distinguishable hypotheses reachable from a fixed
# initialization grows with the number of training steps taken (each
# additional step can, in principle, move theta into a region of
# parameter space representing a function further from the
# initialization's "simple" starting point). Stopping early therefore
# constrains the EFFECTIVE hypothesis class actually being searched to a
# subset of what the FULLY-TRAINED model's class would be -- directly
# analogous to how L2 regularization (Classical ML Theory Notes L02)
# restricts the effective hypothesis class to a norm-bounded region.
# Both mechanisms lower "effective capacity" without changing the
# model's NOMINAL capacity (the raw parameter count / architecture stays
# identical); they differ only in HOW they restrict which hypotheses are
# actually reachable -- one via a penalty term, the other via a training-
# time budget.
#
# THIS IS WHY EARLY STOPPING'S "PATIENCE" HYPERPARAMETER (how many
# non-improving epochs to tolerate before stopping) FUNCTIONS AS A
# BIAS-VARIANCE KNOB, exactly like lambda or C in prior lessons: very
# short patience (stop very early) yields a model closer to its
# initialization -- typically HIGH BIAS (hasn't had enough training to
# fit real structure) but LOW VARIANCE (far from having memorized
# training-set-specific noise); very long/no patience (train until
# training loss plateaus, ignoring validation) risks the opposite,
# LOW BIAS but HIGH VARIANCE (had enough steps to start fitting noise).

def train_with_early_stopping(loss_fn, grad_fn, theta0, lr, val_loss_fn,
                               patience, max_steps=1000):
    theta = np.array(theta0, dtype=float)
    best_val_loss = np.inf
    best_theta = theta.copy()
    steps_without_improvement = 0
    history = {"train_loss": [], "val_loss": []}

    for step in range(max_steps):
        theta = theta - lr * grad_fn(theta)
        train_loss = loss_fn(theta)
        val_loss = val_loss_fn(theta)
        history["train_loss"].append(train_loss)
        history["val_loss"].append(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_theta = theta.copy()
            steps_without_improvement = 0
        else:
            steps_without_improvement += 1
            if steps_without_improvement >= patience:
                break

    return best_theta, history, step + 1


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A team notices their transformer fine-tuning run (using AdamW, correctly)
# generalizes noticeably worse after a well-meaning engineer "simplifies"
# the optimizer config by switching to plain Adam with an L2 term manually
# added to the loss function, believing this is mathematically equivalent
# and slightly more transparent/explicit code. Per Concept #2, this is NOT
# an equivalent refactor -- it silently reintroduces the naive L2-under-
# Adam distortion the AdamW paper specifically fixed, and the measured
# generalization regression is the DIRECT, predictable consequence, not a
# mysterious regression requiring open-ended debugging. The fix is
# reverting to genuinely decoupled weight decay (AdamW's actual update
# rule), not tuning lambda further within the naive formulation.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Applying dropout at INFERENCE time (forgetting to disable it / not
#    calling `model.eval()`). This makes predictions STOCHASTIC (different
#    output for the same input on different calls) and systematically
#    scaled down (since neurons are being randomly zeroed with no
#    compensating averaging over multiple passes) -- a real, common
#    production bug, not a theoretical concern.
# 2. Treating "L2 regularization" and "weight decay" as interchangeable
#    terms when working with Adam/AdamW specifically. Per Concept #2, this
#    conflation is harmless under plain SGD but a measurable source of
#    underperformance under Adam -- always confirm which formulation a
#    given framework's `weight_decay` parameter actually implements
#    (modern PyTorch's `AdamW` implements the correct decoupled version;
#    naively adding an L2 term to a custom loss function under plain
#    `Adam` does not).
# 3. Using dropout probability p=0.5 uniformly across every layer type
#    without considering context. Convolutional layers (this domain's
#    L05) already have far fewer, heavily-shared parameters than fully-
#    connected layers, and typically use much lower dropout rates (or
#    spatial dropout variants) -- applying fully-connected-layer-style
#    heavy dropout can under-utilize an already parameter-efficient
#    architecture.
# 4. Setting early-stopping patience based on a fixed number regardless
#    of how noisy the validation metric is. A very noisy validation
#    signal (e.g. small validation set, high metric variance run-to-run)
#    can trigger early stopping on a random unlucky fluctuation rather
#    than genuine overfitting onset -- patience should be set with
#    reference to the OBSERVED noise level of the validation metric, not
#    a default copied from an unrelated project.


if __name__ == "__main__":
    print("=" * 70)
    print("CONCEPT #1: dropout's expected output equals the undropped activation")
    print("=" * 70)
    original, mean_dropout_output = demonstrate_dropout_as_implicit_ensemble(n_samples=20000)
    print(f"Original activation:            {np.round(original, 4)}")
    print(f"Mean over 20000 dropout masks:   {np.round(mean_dropout_output, 4)}")
    print(f"Close match? {np.allclose(original, mean_dropout_output, atol=0.15)}")
    print("-> Confirms inverted dropout's rescaling makes E[dropout output] =")
    print("   original activation, which is why NO rescaling is needed at inference.")

    print("\n" + "=" * 70)
    print("CONCEPT #2: naive L2-under-Adam vs AdamW's decoupled weight decay")
    print("=" * 70)
    # Two directions with very different DATA-gradient magnitude (a ravine,
    # echoing L02). Adam's own per-parameter normalization equalizes raw
    # step SIZE across both directions regardless of regularization, so
    # comparing final theta directly (or their ratio) is confounded by that
    # normalization -- it doesn't isolate the L2-vs-weight-decay difference.
    # Instead, measure SHRINKAGE relative to each dimension's own lambda=0
    # (unregularized) baseline -- this is what actually isolates how much
    # EACH method's regularization mechanism pulled that dimension toward
    # zero, independent of Adam's separate step-size-equalizing behavior.
    # Minimum of the DATA loss alone sits at theta=[5,5] (not 0), so that
    # "shrinkage toward 0" from regularization is measurable against a
    # meaningfully nonzero baseline, rather than both methods trivially
    # converging to the same near-zero point regularization would produce
    # anyway.
    grad_fn = lambda theta: np.array([2 * (theta[0] - 5), 50 * (theta[1] - 5)])
    kwargs = dict(theta0=[0.0, 0.0], lr=0.05, beta1=0.9, beta2=0.999, n_steps=200)
    baseline = adamw_decoupled(grad_fn, lam=0.0, **kwargs)[-1]   # no regularization
    naive_reg = adam_with_l2_penalty_naive(grad_fn, lam=0.3, **kwargs)[-1]
    adamw_reg = adamw_decoupled(grad_fn, lam=0.3, **kwargs)[-1]

    shrink_naive = 1 - naive_reg / baseline    # fraction pulled toward 0 vs baseline
    shrink_adamw = 1 - adamw_reg / baseline
    print(f"Unregularized (lambda=0) baseline theta: {np.round(baseline, 5)}")
    print(f"Naive L2-under-Adam shrinkage per dim:    {np.round(shrink_naive, 4)}")
    print(f"AdamW decoupled shrinkage per dim:        {np.round(shrink_adamw, 4)}")
    naive_spread = abs(shrink_naive[0] - shrink_naive[1])
    adamw_spread = abs(shrink_adamw[0] - shrink_adamw[1])
    print(f"Spread between the two dims' shrinkage -- naive: {naive_spread:.4f}, "
          f"AdamW: {adamw_spread:.4f}")
    print("-> AdamW's decoupled decay applies the SAME proportional shrinkage")
    print("   to both dimensions (small spread) regardless of their very different")
    print("   data-gradient magnitudes (2x vs 50x); naive L2-under-Adam's shrinkage")
    print("   gets distorted by each dimension's own accumulated s_hat, producing")
    print("   uneven (less principled) shrinkage across the two dimensions.")

    print("\n" + "=" * 70)
    print("CONCEPT #3: early stopping halts before training loss's minimum")
    print("=" * 70)
    # A convex loss whose minimum overfits a noisy "validation" proxy --
    # a small deliberate offset represents the train/val discrepancy that
    # motivates stopping before the training-loss-minimizing step.
    loss_fn = lambda theta: (theta[0] - 5.0) ** 2
    val_loss_fn = lambda theta: (theta[0] - 3.0) ** 2  # "true" optimum is lower
    grad_fn_simple = lambda theta: np.array([2 * (theta[0] - 5.0)])
    best_theta, history, steps_taken = train_with_early_stopping(
        loss_fn, grad_fn_simple, [0.0], lr=0.05, val_loss_fn=val_loss_fn,
        patience=5, max_steps=200)
    print(f"Training halted after {steps_taken} steps (out of 200 allowed)")
    print(f"Best theta by validation loss: {np.round(best_theta, 4)} (val-optimal is 3.0)")
    print(f"Final training loss reached: {history['train_loss'][-1]:.4f} "
          f"(train-optimal would be 0.0 at theta=5.0)")
    print("-> Training stopped well before reaching the TRAINING loss's own")
    print("   minimum, because validation loss started increasing first --")
    print("   exactly the implicit-capacity-constraint mechanism from Concept #3.")
