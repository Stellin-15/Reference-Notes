"""
WHAT: Linear and logistic regression derived from first principles —
      Ordinary Least Squares as Maximum Likelihood Estimation, and
      L1/L2/Elastic-Net regularization as Maximum A Posteriori estimation
      with an explicit prior.
WHY:  "Just call .fit()" hides that OLS, ridge, lasso, and logistic
      regression are all the SAME optimization skeleton (minimize
      negative log-likelihood + optional penalty) wearing different
      likelihood/prior choices. Once you see the skeleton, you stop
      memorizing "ridge shrinks weights, lasso zeroes them out" as a fact
      and start DERIVING it from the shape of the L1 vs L2 penalty.
LEVEL: Foundational (builds on L01's bias-variance framing).

PREREQUISITE: L01_statistical_learning_foundations.py (bias-variance,
VC-dimension framing of "capacity"). Data Science Fundamentals Notes L01-L02
(Bayes' theorem, MLE) if you haven't derived MLE before.
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — OLS IS MAXIMUM LIKELIHOOD ESTIMATION UNDER A GAUSSIAN-NOISE
# ASSUMPTION (not just "the formula that minimizes squared error")
# ============================================================================
#
# Assume y_i = x_i^T beta + eps_i, with eps_i ~ N(0, sigma^2) i.i.d.
#
# The likelihood of observing the data given beta is:
#   L(beta) = prod_i  (1/sqrt(2*pi*sigma^2)) * exp( -(y_i - x_i^T beta)^2 / (2*sigma^2) )
#
# Take the log (monotonic transform, same argmax):
#   log L(beta) = -n/2 * log(2*pi*sigma^2) - (1/(2*sigma^2)) * sum_i (y_i - x_i^T beta)^2
#
# The first term doesn't depend on beta. Maximizing log L(beta) over beta is
# therefore IDENTICAL to minimizing sum_i (y_i - x_i^T beta)^2 — the ordinary
# least-squares objective. This is not a coincidence or an analogy: squared-
# error loss falls straight out of assuming Gaussian noise. If your noise is
# NOT Gaussian (e.g. heavy-tailed, like financial returns), squared-error
# loss is the wrong MLE and you should derive the correct one from the
# actual noise distribution (Laplace noise -> L1/MAE loss; this is why
# MAE is the "robust to outliers" loss — it's the correct likelihood for
# fatter-tailed noise, not an ad-hoc trick).
#
# CLOSED-FORM SOLUTION (the normal equations):
#   Minimize J(beta) = ||y - X*beta||^2 over beta.
#   dJ/dbeta = -2*X^T*(y - X*beta) = 0
#   => X^T*X*beta = X^T*y
#   => beta_hat = (X^T*X)^-1 * X^T*y      (assuming X^T*X is invertible)
#
# WHEN X^T*X IS NOT INVERTIBLE (or is near-singular): this happens when
# features are collinear (redundant) or when n < p (more features than
# rows). This is not a numerical inconvenience to "just add jitter" —
# it's the formal way of saying INFINITELY MANY beta vectors fit the
# training data equally well, i.e. the problem is under-determined. This
# is EXACTLY the situation ridge regression is built to fix (see below):
# regularization doesn't just help with overfitting, it makes an
# otherwise ill-posed problem well-posed.

def ols_normal_equations(X, y):
    """Direct implementation of beta_hat = (X^T X)^-1 X^T y."""
    XtX = X.T @ X
    Xty = X.T @ y
    return np.linalg.solve(XtX, Xty)  # solve() is more numerically stable
                                       # than explicitly computing the
                                       # inverse and multiplying -- never
                                       # write np.linalg.inv(XtX) @ Xty in
                                       # production code.


# ----------------------------------------------------------------------------
# CONCEPT #2 — RIDGE REGRESSION (L2) IS MAP ESTIMATION WITH A GAUSSIAN PRIOR
# ----------------------------------------------------------------------------
#
# Bayes' theorem: posterior(beta | data) proportional to likelihood(data | beta) * prior(beta)
#
# Put a zero-mean Gaussian prior on the weights: beta_j ~ N(0, tau^2) i.i.d.
# This encodes the modeling belief "large weights are a priori less likely
# than small weights" -- BEFORE seeing any data.
#
#   log posterior(beta) = log likelihood(beta) + log prior(beta) + const
#                        = [-(1/(2*sigma^2)) * sum_i(y_i - x_i^T beta)^2]
#                        + [-(1/(2*tau^2)) * sum_j beta_j^2]
#                        + const
#
# Maximizing the posterior (MAP estimation) is equivalent to minimizing:
#   J_ridge(beta) = sum_i (y_i - x_i^T beta)^2  +  lambda * sum_j beta_j^2
#   where lambda = sigma^2 / tau^2
#
# THIS IS EXACTLY THE RIDGE REGRESSION OBJECTIVE. lambda is not an arbitrary
# tuning knob -- it is literally the RATIO of noise variance to prior
# variance. A small tau (strong belief that weights are near zero) gives a
# large lambda (strong shrinkage). This is the precise, derivable reason
# ridge "shrinks weights toward zero": it is imposing a Gaussian belief
# that they SHOULD be near zero, and trading off that belief against what
# the data says, in exactly the proportion the noise/prior variances imply.
#
# CLOSED FORM: J_ridge is still quadratic in beta, so it still has a
# closed-form solution:
#   beta_hat_ridge = (X^T*X + lambda*I)^-1 * X^T*y
#
# NOTICE: adding lambda*I to X^T*X before inverting is EXACTLY what fixes
# the non-invertibility problem from Concept #1 -- X^T*X + lambda*I is
# provably invertible for any lambda > 0, even when X^T*X alone is
# singular. This is why ridge is the standard fix for multicollinearity,
# not a separate technique that happens to also help with that.

def ridge_regression(X, y, lam):
    n_features = X.shape[1]
    XtX_reg = X.T @ X + lam * np.eye(n_features)
    Xty = X.T @ y
    return np.linalg.solve(XtX_reg, Xty)


# ----------------------------------------------------------------------------
# CONCEPT #3 — LASSO (L1) IS MAP ESTIMATION WITH A LAPLACE PRIOR, AND *WHY*
# L1 PRODUCES EXACT ZEROS BUT L2 DOESN'T
# ----------------------------------------------------------------------------
#
# Swap the prior to a Laplace (double-exponential) distribution:
#   p(beta_j) = (1/2b) * exp(-|beta_j|/b)
#
# Following the same MAP derivation as Concept #2:
#   J_lasso(beta) = sum_i (y_i - x_i^T beta)^2  +  lambda * sum_j |beta_j|
#
# THIS IS THE LASSO OBJECTIVE. Same derivation pattern, different prior
# shape -- and that shape difference is the entire reason L1 and L2 behave
# so differently in practice.
#
# WHY L1 ZEROES OUT COEFFICIENTS AND L2 DOESN'T (the geometric argument,
# not just "L1 is known to be sparse"):
#
#   Think of the regularized problem as: minimize the least-squares loss
#   subject to a budget constraint on the penalty term (Lagrangian duality
#   makes "minimize loss + lambda*penalty" equivalent to "minimize loss
#   subject to penalty <= t" for a corresponding t).
#
#   - The L2 constraint region {beta : sum beta_j^2 <= t} is a SPHERE (a
#     ball with a smooth boundary, no corners).
#   - The L1 constraint region {beta : sum |beta_j| <= t} is a DIAMOND
#     (a cross-polytope with SHARP CORNERS sitting exactly on the
#     coordinate axes, i.e. exactly where some beta_j = 0).
#
#   The unconstrained least-squares solution defines elliptical contours
#   of the loss function. The constrained solution is the point where the
#   smallest such ellipse touches the constraint region's boundary.
#
#   - For the L2 sphere: because the boundary is smooth everywhere, the
#     touching point generically has ALL coordinates nonzero -- there's
#     nothing special about the axes.
#   - For the L1 diamond: because probability mass concentrates at the
#     CORNERS (the sharp vertices sit exactly on the axes), the ellipse is
#     very likely to first touch the diamond AT a corner, i.e. at a point
#     where one or more beta_j is EXACTLY zero.
#
#   This is a purely geometric fact about the shape of the two penalty
#   regions -- it holds regardless of the specific dataset, which is why
#   "L1 gives sparsity, L2 doesn't" is a structural property of the
#   penalty, not a coincidence of any one MLE problem.
#
# PRACTICAL CONSEQUENCE: lasso performs embedded FEATURE SELECTION (the
# zeroed-out coefficients are dropped from the model entirely) while ridge
# performs shrinkage without selection (all features stay in the model,
# just downweighted). Elastic Net (alpha*L1 + (1-alpha)*L2) exists
# specifically because pure lasso behaves erratically with groups of
# correlated features (it tends to arbitrarily pick ONE from a correlated
# group and zero the rest, which is unstable across resamples), while
# adding an L2 component encourages correlated features to be selected
# or shrunk TOGETHER (the "grouping effect").
#
# NO CLOSED FORM FOR LASSO: because |beta_j| is not differentiable at
# beta_j=0, there's no normal-equations solution. Lasso is solved
# iteratively -- coordinate descent (below) is the standard approach,
# because each 1D subproblem in a coordinate-descent sweep DOES have a
# closed form: the "soft-thresholding operator."

def soft_threshold(rho, lam):
    """
    The 1D solution to: minimize (1/2)*(z - rho)^2 + lam*|z| over z.
    Derived by casing on the sign of z (the |z| term isn't differentiable
    at 0, so you solve each branch and check which is consistent):
      if rho >  lam: z* = rho - lam
      if rho < -lam: z* = rho + lam
      else:          z* = 0          <-- this branch is WHY sparsity happens
    This single function is the computational engine of lasso coordinate
    descent below.
    """
    if rho > lam:
        return rho - lam
    elif rho < -lam:
        return rho + lam
    else:
        return 0.0


def lasso_coordinate_descent(X, y, lam, n_iters=200, tol=1e-8):
    """
    Coordinate descent for lasso: at each step, fix every beta_j except
    one, solve that 1D subproblem exactly via soft-thresholding, and
    sweep across all coordinates repeatedly until convergence. This
    converges because the lasso objective is convex (sum of a convex
    smooth loss + a convex, if non-smooth, penalty), even though no
    single global closed form exists.
    """
    n, p = X.shape
    beta = np.zeros(p)
    # Precompute column norms once -- reused every sweep.
    col_norm_sq = (X ** 2).sum(axis=0)

    for _ in range(n_iters):
        beta_old = beta.copy()
        for j in range(p):
            # Residual excluding feature j's current contribution.
            residual = y - X @ beta + X[:, j] * beta[j]
            rho = X[:, j] @ residual
            if col_norm_sq[j] == 0:
                beta[j] = 0.0
                continue
            beta[j] = soft_threshold(rho, lam * n) / col_norm_sq[j]
        if np.max(np.abs(beta - beta_old)) < tol:
            break
    return beta


# ----------------------------------------------------------------------------
# CONCEPT #4 — LOGISTIC REGRESSION: WHY THE SIGMOID + LOG-LOSS COMBINATION
# IS NOT ARBITRARY
# ----------------------------------------------------------------------------
#
# For binary classification, y in {0, 1}, model P(y=1 | x) = sigma(x^T beta)
# where sigma(z) = 1 / (1 + exp(-z)).
#
# WHY THE SIGMOID SPECIFICALLY (not, say, clipping a linear function to
# [0,1]): the sigmoid is the inverse of the LOGIT / LOG-ODDS function:
#   logit(p) = log( p / (1-p) )
# Modeling logit(P(y=1|x)) = x^T beta -- i.e. assuming LOG-ODDS is linear
# in the features, not probability itself -- is what makes sigmoid the
# correct link function. It also guarantees the output is squashed into
# (0,1) automatically, unlike clipped linear regression, which produces
# nonsensical flat regions where the gradient is exactly zero.
#
# THE LIKELIHOOD -- Bernoulli, not Gaussian:
#   P(y_i | x_i) = sigma(x_i^T beta)^{y_i} * (1-sigma(x_i^T beta))^{1-y_i}
#
# Negative log-likelihood (the loss you actually minimize):
#   NLL(beta) = -sum_i [ y_i*log(sigma(x_i^T beta)) + (1-y_i)*log(1-sigma(x_i^T beta)) ]
#
# THIS IS BINARY CROSS-ENTROPY -- again, not a separately-invented loss
# function, but exactly what falls out of doing MLE under a Bernoulli
# assumption, the same way squared error fell out of a Gaussian assumption.
# Cross-entropy loss in a neural net's final layer (see Deep Learning
# Theory Notes) is this same derivation, generalized from Bernoulli to
# Categorical/softmax.
#
# NO CLOSED FORM: unlike OLS, NLL(beta) has no closed-form minimizer --
# setting the gradient to zero produces a transcendental equation in beta
# (because sigma is nonlinear). This is why logistic regression is fit
# with iterative optimization (gradient descent, or Newton's method /
# IRLS -- Iteratively Reweighted Least Squares -- which sklearn's default
# solvers use because NLL is convex, guaranteeing Newton's method
# converges to the global optimum, not just a local one).

def logistic_regression_gradient_descent(X, y, lr=0.1, n_iters=1000, lam=0.0):
    """
    beta is fit by gradient descent on NLL + optional L2 penalty
    (lam * ||beta||^2), i.e. this doubles as "ridge logistic regression."
    The gradient of NLL has a famously clean closed form -- worth deriving
    once: d(NLL)/d(beta) = X^T (sigma(X beta) - y). It looks IDENTICAL in
    form to OLS's gradient X^T(X*beta - y) with sigma(X*beta) standing in
    for the linear prediction -- this is a general pattern across the
    exponential-family / GLM framework (Generalized Linear Models), not a
    coincidence specific to logistic regression.
    """
    n, p = X.shape
    beta = np.zeros(p)
    for _ in range(n_iters):
        z = X @ beta
        p_hat = 1.0 / (1.0 + np.exp(-z))
        grad = X.T @ (p_hat - y) / n + lam * beta
        beta -= lr * grad
    return beta


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A pricing model at a marketplace uses 40 features, several of which are
# near-duplicates (e.g. "seller_rating_30d" and "seller_rating_90d" are
# correlated at 0.94). Three legitimate, DIFFERENT modeling choices exist,
# and picking the right one is a direct application of this lesson:
#
#   1. Ridge if the GOAL is prediction accuracy and you want to keep all
#      40 signals (near-duplicate features aren't a problem for ridge's
#      objective -- the L2 penalty handles the resulting non-invertibility
#      of X^T*X gracefully, spreading weight across the correlated pair
#      roughly evenly rather than blowing up).
#   2. Lasso if the GOAL is a small, auditable feature set (e.g. a
#      regulator wants to know exactly which 8 signals drive the price,
#      not "all 40 with tiny weights"). Warn stakeholders explicitly:
#      lasso will pick ONE of the two correlated rating features somewhat
#      arbitrarily and zero the other -- don't over-interpret "we dropped
#      seller_rating_90d, so it doesn't matter" as a causal claim.
#   3. Elastic Net if you want sparsity AND stability under the correlated-
#      feature situation -- it will tend to keep or drop BOTH correlated
#      ratings together rather than picking one arbitrarily, at the cost
#      of a second hyperparameter (alpha, the L1/L2 mix) to tune.
#
# All three are "correct" -- the right choice depends on whether the
# business need is raw predictive accuracy, interpretability/auditability,
# or stability of the selected feature set across retraining runs. This
# framing (not "which algorithm is best" but "which objective matches the
# actual business constraint") is exactly the No Free Lunch lesson from L01
# applied concretely.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Regularizing the intercept/bias term. The MAP derivation above puts a
#    prior on the SLOPE coefficients because "small slopes" is a
#    reasonable prior belief; there's no equivalent reason to believe the
#    intercept should be near zero (that would mean "I believe the
#    baseline outcome, before any features, is near zero," which is
#    usually just false). Production libraries exclude the intercept from
#    the penalty by convention -- if you hand-roll ridge/lasso, remember
#    to do the same, or you'll bias predictions toward zero for no
#    principled reason.
# 2. Forgetting to standardize features before regularizing. lambda *
#    sum(beta_j^2) penalizes EVERY beta_j by the same lambda regardless of
#    that feature's scale. If feature A is in dollars (range 0-100,000)
#    and feature B is a 0-1 flag, A's coefficient will naturally be tiny
#    and B's naturally large just from unit scale -- so the SAME lambda
#    penalizes them wildly unevenly, in a way that has nothing to do with
#    which feature is actually more/less important. Standardize (zero
#    mean, unit variance) first, always.
# 3. Treating lasso's selected features as a causal or stability claim.
#    Because of the grouping-effect issue above, which specific feature
#    lasso zeros out among a correlated cluster can flip between
#    otherwise-similar training runs (different random seeds, slightly
#    different data slices). "Lasso selected feature X" is evidence X is
#    IN a predictive cluster, not evidence X specifically (versus its
#    correlated siblings) is what matters.
# 4. Using accuracy-maximizing lambda chosen by cross-validation as if it
#    were the "correct" prior strength in some absolute sense. lambda is a
#    hyperparameter tuned to minimize validation error on THIS dataset;
#    it is not a rediscovery of the "true" sigma^2/tau^2 ratio from nature.
#    Don't over-interpret a well-tuned lambda as telling you something
#    about the real-world noise level.


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    n, p = 200, 5
    X = rng.normal(size=(n, p))
    true_beta = np.array([3.0, -2.0, 0.0, 0.0, 1.5])  # 2 of 5 truly irrelevant
    y = X @ true_beta + rng.normal(scale=1.0, size=n)

    print("True beta:      ", true_beta)
    print("OLS beta:       ", np.round(ols_normal_equations(X, y), 3))
    print("Ridge beta(l=5):", np.round(ridge_regression(X, y, lam=5.0), 3))
    print("Lasso beta(l=.3):", np.round(lasso_coordinate_descent(X, y, lam=0.3), 3))
    # Expected: OLS gets closest to true_beta in raw magnitude (unbiased),
    # ridge shrinks all 5 coefficients toward 0 without zeroing any, lasso
    # drives the two truly-zero coefficients (indices 2 and 3) to EXACTLY
    # 0.0 while leaving the three real ones nonzero -- the sparsity claim
    # from Concept #3, verified numerically rather than just asserted.

    print("\nLogistic regression on a linearly-separable-ish toy problem:")
    y_bin = (X @ true_beta + rng.normal(scale=1.0, size=n) > 0).astype(float)
    beta_logit = logistic_regression_gradient_descent(X, y_bin, lr=0.5, n_iters=2000)
    print("Logistic beta:  ", np.round(beta_logit, 3))
    # Sign pattern should track true_beta's sign pattern for the genuinely
    # informative features (positive for 0 and 4, negative for 1). Indices
    # 2,3 (truly irrelevant) will be noticeably SMALLER than 0,1,4 but not
    # exactly zero -- this is unregularized logistic regression (lam=0), so
    # there's no L1 term forcing exact sparsity the way lasso did above;
    # add lam>0 to this same function to see them shrink further. Overall
    # magnitudes aren't comparable to the linear-regression beta either --
    # logistic coefficients live on the log-odds scale, not the raw-y scale.
