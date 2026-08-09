"""
WHAT: Support Vector Machines derived from margin maximization through
      Lagrangian duality, and the kernel trick derived from Mercer's
      theorem.
WHY:  "SVM finds the maximum-margin hyperplane" and "the kernel trick lets
      you work in infinite-dimensional feature spaces for free" are both
      true and both usually stated without derivation. This lesson derives
      the dual problem (the actual thing solvers optimize) from the primal,
      shows exactly WHERE the kernel trick enters the math, and explains
      why SVM predictions depend only on a small "support" subset of the
      training data -- a structural fact, not a naming convention.
LEVEL: Foundational.

PREREQUISITE: L02 (regularization, since soft-margin SVM's C parameter
plays the same bias-variance role as lambda did there); comfort with
Lagrange multipliers helps but isn't assumed -- the derivation is walked
through.
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — THE HARD-MARGIN PRIMAL: MAXIMIZE THE MARGIN, NOT JUST
# SEPARATE THE CLASSES
# ============================================================================
#
# Given linearly separable data {(x_i, y_i)}, y_i in {-1, +1}, MANY
# hyperplanes w^T*x + b = 0 separate the classes. SVM's central idea:
# among all separating hyperplanes, pick the one that maximizes the
# distance to the NEAREST point of either class -- the MARGIN.
#
# The (signed) distance from point x_i to the hyperplane is
# (w^T*x_i + b) / ||w||. For a correctly classified point, y_i*(w^T*x_i+b)
# > 0. We can always RESCALE w and b (the hyperplane w^T*x+b=0 is
# unchanged by scaling both by any positive constant) so that the closest
# points satisfy y_i*(w^T*x_i + b) = 1 exactly -- this is a normalization
# choice, not an additional assumption. Under this normalization, the
# margin (distance from the hyperplane to the nearest point) is exactly
# 1/||w||.
#
# So "maximize the margin" becomes "minimize ||w||" (equivalently,
# minimize (1/2)||w||^2, squared and scaled purely for calculus
# convenience -- same minimizer), subject to every point being correctly
# classified with margin >= 1:
#
#   PRIMAL:  minimize_{w,b}  (1/2) ||w||^2
#            subject to      y_i * (w^T x_i + b) >= 1   for all i
#
# This is a convex quadratic program with linear constraints -- convex
# means any local minimum found is guaranteed GLOBAL, which is a real
# advantage SVM has over, say, neural network training.

# ============================================================================
# CONCEPT #2 — LAGRANGIAN DUALITY: WHY WE SOLVE A DIFFERENT-LOOKING
# "DUAL" PROBLEM INSTEAD
# ============================================================================
#
# Introduce a Lagrange multiplier alpha_i >= 0 for each constraint. The
# Lagrangian:
#   L(w,b,alpha) = (1/2)||w||^2 - sum_i alpha_i * [y_i*(w^T x_i + b) - 1]
#
# At the optimum, taking derivatives w.r.t. the PRIMAL variables and
# setting them to zero (the stationarity conditions of KKT):
#   dL/dw = 0  =>  w = sum_i alpha_i * y_i * x_i          ***
#   dL/db = 0  =>  sum_i alpha_i * y_i = 0
#
# Substitute (***) back into L to eliminate w and b entirely, leaving a
# problem purely in terms of the alpha_i -- the DUAL PROBLEM:
#
#   DUAL:  maximize_{alpha}  sum_i alpha_i  -  (1/2) sum_i sum_j alpha_i * alpha_j * y_i * y_j * (x_i . x_j)
#          subject to         alpha_i >= 0,  sum_i alpha_i * y_i = 0
#
# THREE THINGS THIS DERIVATION BUYS YOU, and why anyone bothers:
#
#   1. THE DUAL DEPENDS ON THE DATA ONLY THROUGH DOT PRODUCTS x_i . x_j.
#      This is the single most important structural fact in this lesson
#      -- it's the doorway the kernel trick walks through (Concept #3).
#
#   2. KKT COMPLEMENTARY SLACKNESS: at the optimum, for every i, either
#      alpha_i = 0 OR the constraint is tight (y_i*(w^T x_i+b) = 1, i.e.
#      x_i sits EXACTLY on the margin boundary). Points strictly outside
#      the margin (correctly classified with room to spare) necessarily
#      have alpha_i = 0. Combined with w = sum_i alpha_i*y_i*x_i from
#      (***), this means w -- and therefore every prediction the model
#      ever makes -- is a weighted combination of ONLY the points with
#      alpha_i != 0. These are the SUPPORT VECTORS. This is not a naming
#      choice; it's a mathematical consequence of duality that most of
#      the training set is provably irrelevant to the final decision
#      boundary once you've solved the optimization.
#
#   3. Predicting a new point only requires computing dot products of
#      that point against the (typically small) set of support vectors,
#      not against the whole training set -- computationally cheaper at
#      inference time than the primal formulation would naively suggest.

def svm_prediction(x_new, support_vectors, support_labels, alphas, b):
    """f(x) = sign( sum_i alpha_i * y_i * (x_i . x) + b ) -- note this
    depends ONLY on dot products between x and the support vectors, the
    structural fact Concept #2 derives and Concept #3 exploits."""
    decision = sum(
        a * y * np.dot(sv, x_new)
        for sv, y, a in zip(support_vectors, support_labels, alphas)
    ) + b
    return np.sign(decision)


# ============================================================================
# CONCEPT #3 — THE KERNEL TRICK: REPLACE THE DOT PRODUCT, GET A NONLINEAR
# CLASSIFIER FOR FREE
# ============================================================================
#
# The dual problem and the prediction rule both depend on the data ONLY
# through the dot product x_i . x_j (or x_i . x for a new point). Suppose
# you wanted to fit a hyperplane not in the ORIGINAL feature space, but in
# some transformed space phi(x) that makes a nonlinearly-separable problem
# linearly separable (e.g. phi(x) = (x1, x2, x1^2, x2^2, x1*x2) turns a
# circular decision boundary in 2D into a LINEAR one in 5D). Everywhere
# the dual/prediction formulas use x_i . x_j, substitute phi(x_i) . phi(x_j).
#
# THE TRICK: for many useful choices of phi, there's a function
# K(x_i, x_j) = phi(x_i) . phi(x_j) that can be computed WITHOUT ever
# constructing phi(x) explicitly -- often because phi maps into a much
# higher (sometimes infinite) dimensional space, but the inner product in
# that space collapses to something cheap in the original space.
#
# WORKED EXAMPLE -- the polynomial kernel K(x,z) = (x.z + c)^d. Expand
# (x.z+c)^2 for 2D x=(x1,x2), z=(z1,z2), c=1, by hand: you'll find it
# equals phi(x).phi(z) for
#   phi(x) = (x1^2, x2^2, sqrt(2)*x1*x2, sqrt(2)*x1, sqrt(2)*x2, 1)
# -- a 6-dimensional feature map -- yet K(x,z) itself costs O(d) to
# compute directly from x and z, never touching the 6D vectors. For the
# RBF/Gaussian kernel K(x,z) = exp(-gamma*||x-z||^2), the implied phi is
# genuinely INFINITE-dimensional (it's the feature map of every possible
# polynomial degree, in the right proportions) -- fitting a hyperplane
# there is not something you could do by explicitly building phi(x), yet
# the dual problem, kernelized, is exactly as cheap to solve as the linear
# case, because you never need phi -- only K.
#
# MERCER'S THEOREM (the condition that makes this legitimate, not just a
# computational shortcut you hope works): a symmetric function K(x,z) is a
# valid kernel -- i.e. THERE EXISTS some phi with K(x,z)=phi(x).phi(z) --
# if and only if K is POSITIVE SEMI-DEFINITE: for any finite set of points
# x_1..x_n, the Gram matrix [K(x_i,x_j)]_{ij} is PSD (all eigenvalues
# >= 0). This is the formal guarantee that swapping in K doesn't silently
# break convexity of the dual QP -- you're still solving a well-posed
# convex problem, just implicitly in a different (possibly infinite-
# dimensional) space. This is WHY you can't just invent an arbitrary
# "similarity function" and call it a kernel -- it has to satisfy Mercer's
# PSD condition or the whole optimization guarantee (global optimum) falls
# apart.

def rbf_kernel(X1, X2, gamma):
    """K(x,z) = exp(-gamma*||x-z||^2) -- the implied feature map phi is
    infinite-dimensional; this function computes the inner product in
    that space in O(d) time per pair, never constructing phi."""
    sq_dists = (
        np.sum(X1 ** 2, axis=1)[:, None]
        + np.sum(X2 ** 2, axis=1)[None, :]
        - 2 * X1 @ X2.T
    )
    return np.exp(-gamma * sq_dists)


def polynomial_kernel(X1, X2, degree, c=1.0):
    return (X1 @ X2.T + c) ** degree


def verify_kernel_equals_explicit_dot_product():
    """
    Confirms K(x,z) = phi(x).phi(z) for the degree-2 polynomial kernel by
    constructing phi EXPLICITLY and comparing to the kernel shortcut --
    demonstrating Concept #3's claim numerically rather than asserting it.
    """
    rng = np.random.default_rng(0)
    x = rng.normal(size=2)
    z = rng.normal(size=2)

    def phi(v):
        x1, x2 = v
        return np.array([x1 ** 2, x2 ** 2, np.sqrt(2) * x1 * x2, np.sqrt(2) * x1, np.sqrt(2) * x2, 1.0])

    explicit_dot = np.dot(phi(x), phi(z))
    kernel_shortcut = (np.dot(x, z) + 1.0) ** 2
    return explicit_dot, kernel_shortcut


# ============================================================================
# CONCEPT #4 — SOFT-MARGIN SVM: WHY C IS A BIAS-VARIANCE KNOB, EXACTLY
# LIKE LAMBDA IN L02
# ============================================================================
#
# Real data usually isn't perfectly separable (by any finite-degree kernel,
# without wild overfitting). Soft-margin SVM introduces slack variables
# xi_i >= 0, allowing a point to violate its margin constraint by xi_i:
#
#   PRIMAL:  minimize_{w,b,xi}  (1/2)||w||^2  +  C * sum_i xi_i
#            subject to  y_i*(w^T x_i + b) >= 1 - xi_i,   xi_i >= 0
#
# Read this exactly the way you read ridge regression's objective in L02:
# it's "minimize a MARGIN-WIDTH penalty (analogous to the regularization
# term) PLUS C times a MISCLASSIFICATION/violation penalty (analogous to
# the data-fit term)." C plays the role of 1/lambda:
#   - LARGE C: heavily penalize margin violations -> prioritize fitting
#     the training data closely -> narrower margin, more support vectors
#     hugging individual training points -> HIGH VARIANCE, LOW BIAS
#     (can overfit, same failure mode as tiny lambda in ridge).
#   - SMALL C: tolerate margin violations cheaply -> prioritize a wide,
#     simple margin -> fewer support vectors, smoother boundary -> LOW
#     VARIANCE, HIGH BIAS (can underfit, same failure mode as huge
#     lambda in ridge).
# This is the SAME bias-variance knob from L01/L02, wearing a different
# hyperparameter name -- tuning C via cross-validation is mechanically
# identical in purpose to tuning lambda, even though the two objectives
# look superficially unrelated.


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A document-classification system (a few thousand labeled support
# tickets, high-dimensional bag-of-words/TF-IDF features) is a classic
# case where SVM legitimately competes with logistic regression and
# gradient boosting -- and the choice is derivable from this lesson, not
# arbitrary:
#   - High-dimensional, SPARSE, and (near-)linearly-separable-after-
#     TF-IDF text data is exactly the regime linear SVM (or an RBF kernel
#     with small gamma) tends to shine: the max-margin objective handles
#     high-dimensional sparse spaces gracefully, and because prediction
#     depends only on support vectors (Concept #2), inference stays cheap
#     even with a huge vocabulary.
#   - If the SAME dataset is small (a few hundred labeled tickets, not
#     thousands), prefer logistic regression with L2 -- with too little
#     data, SVM's margin estimate is itself high-variance (few points
#     to pin down "the margin"), and logistic regression's probabilistic
#     output (calibrated P(y=1|x), unlike raw SVM's uncalibrated distance-
#     to-hyperplane score) is directly useful for triage thresholds.
#   - If ticket volume is huge (millions) and features are tabular/mixed
#     (not just bag-of-words), gradient boosting (L03) usually wins on
#     raw accuracy -- kernelized SVM's training cost scales poorly
#     (O(n^2) to O(n^3) in the number of training points, since the dual
#     QP involves an n x n Gram matrix), making it impractical at that
#     scale regardless of accuracy.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Feeding unscaled features into an SVM. The margin/distance
#    computation is scale-sensitive in the same way ridge's penalty was
#    (L02, mistake #2) -- a feature ranging 0-100,000 will dominate the
#    dot product (and therefore the kernel) versus a 0-1 feature, for
#    reasons having nothing to do with actual predictive relevance.
#    Always standardize before fitting.
# 2. Treating SVM's raw decision value (distance to the hyperplane) as a
#    calibrated probability. It isn't one -- there's no likelihood model
#    underneath it the way there is for logistic regression (Concept #4,
#    L02). If you need P(y=1|x), either use Platt scaling (fit a logistic
#    regression on top of the SVM's decision values, a documented and
#    fairly standard post-hoc calibration step) or just use logistic
#    regression / gradient boosting directly if probabilities are the
#    actual deliverable.
# 3. Using an RBF kernel by default without considering training-time
#    cost. Because kernelized SVM training is O(n^2)-O(n^3) in dataset
#    size, "just use RBF, it's more flexible" silently becomes
#    intractable well before you hit the dataset sizes gradient boosting
#    or neural nets handle routinely. Check n before reaching for a
#    nonlinear kernel.
# 4. Forgetting that Mercer's theorem is a real constraint, not a
#    formality. A hand-rolled "similarity score" between two examples
#    (e.g. some domain-specific heuristic distance) is NOT automatically
#    a valid kernel -- if its Gram matrix isn't PSD, the dual QP loses its
#    convexity guarantee and solvers can converge to nonsense. Verify PSD-
#    ness (or stick to known-valid kernels: linear, polynomial, RBF,
#    sigmoid-with-caveats) before plugging a custom similarity function
#    into an SVM.


if __name__ == "__main__":
    print("=" * 70)
    print("KERNEL TRICK: explicit feature map vs kernel shortcut")
    print("=" * 70)
    explicit, shortcut = verify_kernel_equals_explicit_dot_product()
    print(f"phi(x).phi(z) computed explicitly:  {explicit:.6f}")
    print(f"(x.z + 1)^2 computed via kernel:     {shortcut:.6f}")
    print("-> Identical (up to floating point), confirming K(x,z)=phi(x).phi(z)")
    print("   without ever materializing the 6-dimensional phi(x) vector.")

    print("\n" + "=" * 70)
    print("RBF KERNEL: Gram matrix is symmetric PSD (Mercer's theorem check)")
    print("=" * 70)
    rng = np.random.default_rng(1)
    X = rng.normal(size=(6, 3))
    K = rbf_kernel(X, X, gamma=0.5)
    eigvals = np.linalg.eigvalsh(K)
    print(f"Gram matrix eigenvalues: {np.round(eigvals, 4)}")
    print(f"All eigenvalues >= 0 (PSD)? {np.all(eigvals >= -1e-8)}")
    print("-> This is Mercer's theorem verified on a concrete Gram matrix --")
    print("   the formal condition that makes RBF a legitimate kernel.")
