"""
WHAT: Why random weight initialization scale matters quantitatively
      (Xavier/Glorot and He initialization derived from variance-
      preservation across layers), and BatchNorm/LayerNorm derived from
      the internal covariate shift problem they were built to address.
WHY:  "Initialize weights randomly, but not too big or too small" and
      "BatchNorm normalizes activations" are both usually left
      unquantified. This lesson derives the EXACT variance-scaling
      formula that keeps signal from exploding or vanishing purely from
      initialization, and shows precisely what BatchNorm/LayerNorm
      compute and why they differ in which axis they normalize over.
LEVEL: Foundational.

PREREQUISITE: L01 (backprop -- this lesson explains why bad
initialization makes backprop's gradients vanish/explode before training
even starts); L02 (optimizers -- normalization changes the loss surface
optimizers navigate).
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — WHY INITIALIZATION SCALE MATTERS: VARIANCE PROPAGATION
# THROUGH LAYERS
# ============================================================================
#
# Consider a linear layer z = W*x, with W's entries drawn i.i.d. from a
# distribution with mean 0 and variance Var(w), and x's entries i.i.d.
# with variance Var(x) (and independent of W). For a single output
# z_j = sum_{i=1}^{n} w_ji * x_i (n = number of inputs to this layer):
#
#   Var(z_j) = Var(sum_i w_ji*x_i)
#            = sum_i Var(w_ji*x_i)                    (independent terms sum)
#            = sum_i [ Var(w_ji)*Var(x_i) + Var(w_ji)*E[x_i]^2 + E[w_ji]^2*Var(x_i) ]
#            = n * Var(w) * Var(x)                     (E[w]=0 kills two terms)
#
# THIS IS THE ENTIRE DERIVATION THAT MOTIVATES XAVIER/GLOROT
# INITIALIZATION. If you want Var(z) = Var(x) -- i.e. the SIGNAL VARIANCE
# is preserved as it passes through the layer, neither shrinking toward
# zero nor blowing up -- you need:
#   n * Var(w) = 1   =>   Var(w) = 1/n
#
# Do this at EVERY layer of a deep network and the forward-pass activation
# variance stays roughly constant layer to layer instead of compounding
# multiplicatively (if each layer scales variance by a factor c != 1,
# after L layers the variance has scaled by c^L -- exponential in depth,
# meaning even a small per-layer mismatch becomes catastrophic vanishing
# or exploding activations in a genuinely deep network).
#
# XAVIER/GLOROT INITIALIZATION additionally accounts for the BACKWARD
# pass -- the same variance-preservation argument applies to gradients
# flowing backward through W^T, which depends on n_out (fan-out) rather
# than n_in (fan-in). Xavier's standard compromise, balancing both
# forward and backward variance preservation:
#   Var(w) = 2 / (n_in + n_out)
# implemented in practice as sampling from Uniform(-limit, limit) with
# limit = sqrt(6/(n_in+n_out)), whose variance works out to exactly this
# target.

def xavier_init(n_in, n_out, rng):
    limit = np.sqrt(6.0 / (n_in + n_out))
    return rng.uniform(-limit, limit, size=(n_in, n_out))


# ============================================================================
# CONCEPT #2 — HE INITIALIZATION: WHY RELU NEEDS A DIFFERENT CONSTANT
# ============================================================================
#
# Xavier's derivation implicitly assumes the activation function
# preserves variance roughly symmetrically (a reasonable approximation
# for tanh/sigmoid near zero). ReLU breaks this assumption structurally:
# ReLU(z) = max(0, z) zeroes out ROUGHLY HALF the activations (every
# negative input), which -- for a zero-mean, symmetric input distribution
# -- cuts the OUTPUT variance of the activation in half relative to the
# input variance:
#   Var(ReLU(z)) ≈ (1/2) * Var(z)      (exact for z ~ N(0, sigma^2))
#
# If you used Xavier's Var(w)=1/n with a ReLU network, EVERY layer would
# multiply the running signal variance by an extra factor of ~0.5 on top
# of whatever the linear part contributes -- across many layers, this
# compounds into vanishing activations even though Xavier was specifically
# designed to prevent exactly that failure mode (Concept #1), just under
# a wrong assumption about the nonlinearity.
#
# HE INITIALIZATION corrects for this directly: to compensate for ReLU's
# variance-halving, DOUBLE the per-layer weight variance relative to
# Xavier's forward-only formula:
#   Var(w) = 2/n_in
# so that AFTER the ReLU's roughly-50% variance cut, the net effect
# across the linear+ReLU layer still preserves variance overall:
#   Var(z) = n*Var(w)*Var(x) = n*(2/n)*Var(x) = 2*Var(x)
#   Var(ReLU(z)) ≈ (1/2)*2*Var(x) = Var(x)      <-- preserved, as desired
#
# This is a clean, derivable example of WHY initialization scheme choice
# should match activation function choice -- it isn't a stylistic
# preference (He init "just works better for ReLU nets" in practice
# because of this specific, quantifiable variance-compensation
# mechanism), and using Xavier init with ReLU (or vice versa) is a real,
# identifiable source of training instability in a from-scratch network,
# not an inconsequential mismatch.

def he_init(n_in, n_out, rng):
    std = np.sqrt(2.0 / n_in)
    return rng.normal(0, std, size=(n_in, n_out))


def demonstrate_variance_propagation(init_fn, activation, n_layers=20, width=256, seed=0):
    """
    Propagates a random signal through n_layers of (linear + activation),
    tracking the activation variance layer by layer -- makes Concepts
    #1-#2's variance-preservation claim (or failure) directly observable.
    """
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 1, size=(1000, width))  # 1000 "samples," width features
    variances = [x.var()]
    for _ in range(n_layers):
        W = init_fn(width, width, rng)
        z = x @ W
        x = activation(z)
        variances.append(x.var())
    return variances


def relu(z):
    return np.maximum(0, z)


def tanh(z):
    return np.tanh(z)


# ============================================================================
# CONCEPT #3 — INTERNAL COVARIATE SHIFT AND WHAT BATCHNORM ACTUALLY
# NORMALIZES
# ============================================================================
#
# Even with good initialization, as TRAINING proceeds, every layer's
# input distribution keeps shifting because every layer BEFORE it is
# simultaneously updating its own weights -- layer 5's effective "input
# distribution" changes every single gradient step, because layers 1-4's
# parameters (which produce that input) are changing too. This is
# INTERNAL COVARIATE SHIFT: each layer is perpetually trying to fit a
# moving target, which slows convergence and forces the use of smaller,
# more conservative learning rates than would otherwise be needed.
#
# (NOTE: the ORIGINAL internal-covariate-shift explanation for WHY
# BatchNorm helps has been empirically challenged by later research --
# Santurkar et al. 2018 showed BatchNorm's benefit correlates more
# strongly with SMOOTHING THE LOSS LANDSCAPE (making the loss surface's
# Lipschitz constant and gradient predictability better-behaved) than
# with reducing covariate shift per se, measured directly. Both
# explanations point to the same practical prescription -- normalize
# intermediate activations -- but a rigorous answer should note the
# mechanism is still an active research question, not a fully settled
# one, rather than presenting internal-covariate-shift as unquestionably
# proven.)
#
# BATCHNORM'S ACTUAL COMPUTATION: for each feature/channel, normalize
# across the BATCH dimension:
#   mu_B = mean of this feature across the current mini-batch
#   sigma_B^2 = variance of this feature across the current mini-batch
#   x_hat = (x - mu_B) / sqrt(sigma_B^2 + epsilon)
#   y = gamma*x_hat + beta          <-- LEARNED scale/shift, restoring
#                                        the network's ability to
#                                        represent the OPTIMAL (not
#                                        necessarily zero-mean-unit-
#                                        variance) activation
#                                        distribution if that's actually
#                                        what minimizes the loss
#
# WHY gamma/beta ARE NECESSARY, NOT OPTIONAL: pure normalization forces
# every feature to zero-mean-unit-variance REGARDLESS of whether that's
# actually useful for the downstream layers -- this could actively
# destroy useful information a layer had learned to encode in its
# activation SCALE (e.g. "large positive activation = strong signal").
# gamma and beta are additional LEARNABLE parameters that let the network
# recover any distribution it needs, including undoing the normalization
# entirely if that's what training decides is optimal (gamma=sqrt(sigma_B^2
# +eps), beta=mu_B recovers the original, unnormalized x exactly) -- so
# BatchNorm never strictly reduces the network's expressive power, it
# only changes the OPTIMIZATION LANDSCAPE the network has to search.

def batchnorm_forward(x, gamma, beta, eps=1e-5):
    """x: shape (batch_size, n_features). Normalizes each FEATURE across
    the BATCH dimension (axis=0) -- the batch-dependence is the whole
    point (Concept #3) and also the whole problem (Concept #4)."""
    mu = x.mean(axis=0, keepdims=True)
    var = x.var(axis=0, keepdims=True)
    x_hat = (x - mu) / np.sqrt(var + eps)
    return gamma * x_hat + beta


# ============================================================================
# CONCEPT #4 — WHY LAYERNORM EXISTS: BATCHNORM'S BATCH-SIZE DEPENDENCE
# BREAKS DOWN FOR SEQUENCES AND SMALL BATCHES
# ============================================================================
#
# BatchNorm's statistics (mu_B, sigma_B^2) are computed ACROSS THE BATCH
# for each feature -- this creates two real, structural problems:
#
#   1. SMALL-BATCH INSTABILITY: with very small batch sizes (e.g. batch
#      size 1-4, common when memory-constrained, e.g. training very large
#      models or high-resolution images), the batch statistics themselves
#      become extremely noisy estimates of the TRUE population mean/
#      variance -- BatchNorm's normalization can inject nearly as much
#      noise as it removes, hurting rather than helping training.
#   2. VARIABLE-LENGTH SEQUENCES: for RNNs/Transformers processing
#      sequences of different lengths within a batch, "normalize across
#      the batch, per timestep" is awkward -- different sequences
#      contribute different amounts of valid (non-padding) data at each
#      timestep position, and at INFERENCE time with a batch size of 1
#      (a single request), there's no "batch" to compute statistics over
#      at all, requiring separately-tracked running statistics that can
#      behave inconsistently between train and inference modes.
#
# LAYERNORM sidesteps both by normalizing across the FEATURE dimension
# INSTEAD of the batch dimension -- for EACH INDIVIDUAL EXAMPLE
# independently:
#   mu_i = mean across all features of example i
#   sigma_i^2 = variance across all features of example i
#   (normalize example i using ONLY its own features, not other
#   examples in the batch)
#
# Because LayerNorm's statistics depend only on a SINGLE example's own
# features, it is completely independent of batch size (works identically
# whether batch size is 1 or 1024) and independent of other examples in
# the batch -- exactly the property needed for variable-length sequence
# processing and small/batch-size-1 inference. THIS IS PRECISELY WHY
# TRANSFORMERS (LLM Core Theory Notes) UNIVERSALLY USE LAYERNORM, NOT
# BATCHNORM: sequence models with variable lengths and frequent single-
# example inference make BatchNorm's batch-dependence a genuine
# liability, not merely a stylistic difference between two equally-good
# options.

def layernorm_forward(x, gamma, beta, eps=1e-5):
    """x: shape (batch_size, n_features). Normalizes each EXAMPLE's own
    features (axis=1) -- no dependence on other examples in the batch,
    unlike batchnorm_forward above."""
    mu = x.mean(axis=1, keepdims=True)
    var = x.var(axis=1, keepdims=True)
    x_hat = (x - mu) / np.sqrt(var + eps)
    return gamma * x_hat + beta


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A team porting a working image classifier (trained with BatchNorm, batch
# size 256) to a memory-constrained edge-deployment fine-tuning setup
# (batch size 2, due to hardware limits) sees validation accuracy collapse
# after fine-tuning, despite an identical architecture and near-identical
# hyperparameters. Per Concept #4, this is close to a textbook BatchNorm
# small-batch-instability symptom -- with batch size 2, the running batch
# statistics are extremely noisy per-step estimates, actively corrupting
# the signal BatchNorm is supposed to stabilize. Two standard, evidence-
# based fixes follow directly from this lesson rather than blind
# hyperparameter search: (a) switch to GroupNorm (normalizes across a
# fixed-size group of channels per example, independent of batch size --
# structurally similar in spirit to LayerNorm's batch-independence, but
# tuned for convolutional/vision architectures specifically) or (b)
# freeze the pretrained BatchNorm running statistics entirely during
# fine-tuning (use the STATISTICS learned during the original large-batch
# training, only update gamma/beta) -- both directly target the
# identified mechanism (unreliable small-batch statistics), rather than
# generic remedies like "just lower the learning rate," which wouldn't
# address the actual root cause.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Using Xavier initialization with ReLU activations. Per Concept #2,
#    Xavier's derivation doesn't account for ReLU's ~50% variance
#    reduction, and networks initialized this way commonly show measurably
#    slower convergence or vanishing activations in deep ReLU networks --
#    use He initialization for ReLU/Leaky-ReLU-family activations.
# 2. Treating gamma/beta as unnecessary "extra parameters to prune."
#    Per Concept #3, they're what preserves BatchNorm/LayerNorm's ability
#    to represent the network's originally-intended (possibly non-
#    normalized) activation distribution -- removing them can measurably
#    hurt final accuracy, not just add negligible parameter overhead.
# 3. Using BatchNorm with very small batch sizes (roughly <8, though the
#    exact threshold is architecture/task dependent) without considering
#    GroupNorm or LayerNorm alternatives (Concept #4) -- a well-documented
#    failure mode, not a rare edge case.
# 4. Forgetting that BatchNorm behaves DIFFERENTLY at train time (uses
#    current-batch statistics) vs inference time (uses accumulated
#    running statistics from training, since a single inference request
#    often has no "batch" to compute fresh statistics from). Forgetting
#    to call a framework's `model.eval()` (or equivalent) before inference
#    silently leaves BatchNorm in training mode, corrupting predictions
#    with train-time batch-dependent statistics — a very common, very
#    real bug, not a theoretical footnote.


if __name__ == "__main__":
    print("=" * 70)
    print("CONCEPT #2: Xavier vs He init, with a ReLU network (20 layers)")
    print("=" * 70)
    var_xavier_relu = demonstrate_variance_propagation(xavier_init, relu, n_layers=20)
    var_he_relu = demonstrate_variance_propagation(he_init, relu, n_layers=20)
    print(f"Xavier+ReLU variance -- layer 0: {var_xavier_relu[0]:.4f}, "
          f"layer 10: {var_xavier_relu[10]:.6f}, layer 20: {var_xavier_relu[20]:.8f}")
    print(f"He+ReLU variance     -- layer 0: {var_he_relu[0]:.4f}, "
          f"layer 10: {var_he_relu[10]:.4f}, layer 20: {var_he_relu[20]:.4f}")
    print("-> Xavier+ReLU's variance should visibly decay toward zero across")
    print("   layers (vanishing activations); He+ReLU's should stay roughly")
    print("   stable near 1.0 throughout -- the exact failure Concept #2 predicts.")

    print("\n" + "=" * 70)
    print("CONCEPT #3/#4: BatchNorm vs LayerNorm -- what each normalizes over")
    print("=" * 70)
    rng = np.random.default_rng(0)
    # Deliberately skewed batch: different examples have very different
    # overall activation scales (simulating real heterogeneous inputs).
    x = rng.normal(0, 1, size=(4, 6)) * np.array([[1], [5], [0.2], [10]])
    gamma_bn, beta_bn = np.ones((1, 6)), np.zeros((1, 6))
    bn_out = batchnorm_forward(x, gamma_bn, beta_bn)
    ln_out = layernorm_forward(x, gamma_bn, beta_bn)
    print(f"Input per-example std (row-wise): {np.round(x.std(axis=1), 3)}")
    print(f"BatchNorm output per-FEATURE mean (should be ~0): "
          f"{np.round(bn_out.mean(axis=0), 6)}")
    print(f"LayerNorm output per-EXAMPLE mean (should be ~0): "
          f"{np.round(ln_out.mean(axis=1), 6)}")
    print("-> BatchNorm zeroes the mean down each COLUMN (across examples);")
    print("   LayerNorm zeroes the mean across each ROW (within one example) --")
    print("   confirming they normalize over genuinely different axes.")
