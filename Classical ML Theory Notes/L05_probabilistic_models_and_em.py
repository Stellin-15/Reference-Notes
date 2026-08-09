"""
WHAT: Naive Bayes derived from Bayes' theorem plus a conditional-
      independence assumption, and the Expectation-Maximization (EM)
      algorithm derived as coordinate ascent on a likelihood lower bound
      -- applied concretely to fitting Gaussian Mixture Models.
WHY:  Naive Bayes "works surprisingly well despite an obviously false
      assumption" is a common observation stated without explanation of
      WHY the false assumption hurts less than it should. EM is usually
      presented as "alternate E-step and M-step" without justifying why
      that alternation is guaranteed to improve the likelihood every
      iteration. Both gaps close once you see the actual math.
LEVEL: Foundational.

PREREQUISITE: Data Science Fundamentals Notes L01 (Bayes' theorem);
L01 of this domain (bias-variance framing, referenced for why Naive
Bayes' bias doesn't always hurt).
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — NAIVE BAYES: BAYES' THEOREM + A DELIBERATELY FALSE
# INDEPENDENCE ASSUMPTION
# ============================================================================
#
# Goal: classify x = (x_1, ..., x_p) into class y by picking the y that
# maximizes the posterior P(y | x). By Bayes' theorem:
#
#   P(y | x) = P(x | y) * P(y) / P(x)
#
# P(x) doesn't depend on y, so for CLASSIFICATION (picking the argmax y)
# you can drop it:
#   y_hat = argmax_y  P(x | y) * P(y)
#
# The hard part is P(x | y) = P(x_1, ..., x_p | y) -- the joint
# distribution of p features given the class. Estimating this directly
# needs exponentially many parameters as p grows (for binary features,
# 2^p - 1 free parameters per class) -- utterly infeasible to estimate
# from any real dataset once p is more than a handful.
#
# THE "NAIVE" ASSUMPTION: assume features are CONDITIONALLY INDEPENDENT
# given the class:
#   P(x_1, ..., x_p | y) = prod_j P(x_j | y)
#
# This collapses the joint into a product of p one-dimensional
# distributions, each trivially estimable from data (e.g. count word
# frequencies per class for text, or fit a 1D Gaussian per feature per
# class for continuous data). The final classifier:
#   y_hat = argmax_y  P(y) * prod_j P(x_j | y)
#
# WHY THIS ASSUMPTION IS OBVIOUSLY FALSE IN PRACTICE: in a spam
# classifier, the words "free" and "prize" are NOT conditionally
# independent given class=spam -- they co-occur far more than chance,
# because spam emails follow templates. Naive Bayes' assumption is wrong
# by construction, not as an approximation that happens to hold.
#
# WHY IT OFTEN STILL WORKS WELL FOR CLASSIFICATION ANYWAY (the actual
# argument, not "it just does"): classification only needs P(y|x) to
# produce the CORRECT ARGMAX across y, not an accurate estimate of the
# actual probability VALUE. Domingos & Pazzani's classic result: Naive
# Bayes can be the Bayes-optimal classifier (get the argmax exactly right
# on every input) even when its independence assumption is badly violated,
# as long as the DEPENDENCE STRUCTURE among features affects all classes
# SIMILARLY (e.g. if "free" and "prize" co-occurring inflates the
# estimated P(x|spam) by roughly the same relative factor it would
# inflate P(x|not-spam) if the same correlation happened to appear
# there). What breaks Naive Bayes is not correlation per se, but
# correlation that differs across classes in a way that flips the
# argmax -- which happens less often than "the independence assumption is
# false" alone would suggest. Put in L01's language: the independence
# assumption gives Naive Bayes strong, structural BIAS (it can never
# represent the true joint distribution), but that bias frequently doesn't
# translate into ARGMAX errors, and its variance is extremely low (only p
# one-dimensional distributions to estimate, so it needs very little data
# per parameter) -- a favorable bias-variance tradeoff specifically for
# the classification task, even though it's a poor DENSITY ESTIMATOR of
# P(x|y) itself.

def gaussian_naive_bayes_fit(X, y):
    """Estimate P(y) and, per class/per feature, a 1D Gaussian P(x_j|y) --
    the continuous-feature version of Naive Bayes."""
    classes = np.unique(y)
    priors, means, vars_ = {}, {}, {}
    for c in classes:
        Xc = X[y == c]
        priors[c] = len(Xc) / len(X)
        means[c] = Xc.mean(axis=0)
        vars_[c] = Xc.var(axis=0) + 1e-9  # epsilon avoids divide-by-zero
    return classes, priors, means, vars_


def gaussian_naive_bayes_predict(X, classes, priors, means, vars_):
    def log_gaussian(x, mean, var):
        return -0.5 * np.log(2 * np.pi * var) - (x - mean) ** 2 / (2 * var)

    preds = []
    for x in X:
        # Work in LOG space and sum, rather than multiplying raw
        # probabilities -- multiplying many small probabilities underflows
        # to 0.0 in floating point long before you have many features;
        # this is a real production bug, not a theoretical nicety.
        log_scores = {
            c: np.log(priors[c]) + log_gaussian(x, means[c], vars_[c]).sum()
            for c in classes
        }
        preds.append(max(log_scores, key=log_scores.get))
    return np.array(preds)


# ============================================================================
# CONCEPT #2 — GAUSSIAN MIXTURE MODELS AND THE EM ALGORITHM
# ============================================================================
#
# A Gaussian Mixture Model (GMM) assumes data is generated by K Gaussians,
# each with a mixing weight pi_k, mean mu_k, covariance Sigma_k:
#   P(x) = sum_k pi_k * N(x; mu_k, Sigma_k)
#
# If you KNEW which Gaussian generated each point (a latent/hidden label
# z_i in {1..K}), fitting would be trivial: partition the data by z_i,
# compute the mean/covariance of each partition, count proportions for
# pi_k. The problem: z_i is UNOBSERVED. This is a "chicken and egg"
# problem -- to assign points to clusters you'd want to know the cluster
# parameters, but to estimate cluster parameters you'd want to know the
# assignments.
#
# EM (Expectation-Maximization) breaks the cycle by ALTERNATING:
#   E-STEP: given the CURRENT parameters (pi, mu, Sigma), compute the
#           POSTERIOR PROBABILITY that each point belongs to each cluster
#           -- a "soft" assignment, gamma_{ik} = P(z_i=k | x_i, current params),
#           via Bayes' theorem:
#             gamma_{ik} = pi_k * N(x_i; mu_k, Sigma_k)  /  sum_j pi_j * N(x_i; mu_j, Sigma_j)
#   M-STEP: given these soft assignments (treated as fixed), re-estimate
#           the parameters that MAXIMIZE the expected complete-data log-
#           likelihood -- which, for a Gaussian mixture, has closed-form
#           updates that look exactly like "weighted mean/covariance,
#           weighted by gamma_{ik}":
#             pi_k  = (1/n) * sum_i gamma_{ik}
#             mu_k  = sum_i gamma_{ik}*x_i / sum_i gamma_{ik}
#             Sigma_k = sum_i gamma_{ik}*(x_i-mu_k)(x_i-mu_k)^T / sum_i gamma_{ik}
#
# WHY THIS IS GUARANTEED TO NEVER DECREASE THE LIKELIHOOD (the fact that
# makes EM more than "a plausible-sounding heuristic"): EM is provably
# coordinate ascent on a LOWER BOUND of the true log-likelihood (derived
# via Jensen's inequality applied to the log of an expectation over z).
# The E-step makes the bound TIGHT at the current parameters (touches the
# true log-likelihood exactly, at that one point); the M-step then
# maximizes that now-tight bound over the parameters. Because the bound
# touches the true likelihood before the M-step and the M-step can only
# increase the bound, the TRUE log-likelihood after the M-step is
# guaranteed >= the true log-likelihood before it. This is a real
# theorem (the ELBO/Evidence Lower BOund argument that also underlies
# variational inference far beyond GMMs) -- not an empirical observation
# that EM "usually" improves things.
#
# WHAT EM DOES NOT GUARANTEE: convergence to the GLOBAL optimum. The
# likelihood surface for a mixture model is non-convex (unlike SVM's dual
# QP or OLS's quadratic loss), so EM can and does get stuck in local
# optima depending on initialization -- this is why production GMM fits
# always run EM from several random restarts and keep the best result by
# final log-likelihood, a direct consequence of this non-convexity rather
# than a defensive habit adopted for no reason.

def gmm_em_fit(X, K, n_iters=100, seed=0):
    """
    From-scratch EM for a Gaussian Mixture Model with diagonal covariance
    (isotropic-per-dimension, for simplicity -- full covariance follows
    the identical E/M-step logic with a full Sigma_k update).
    """
    rng = np.random.default_rng(seed)
    n, d = X.shape

    # Initialize: pick K random points as initial means, unit variance,
    # uniform mixing weights -- a common (if naive) initialization; k-means++
    # style init is standard in production libraries for faster convergence.
    idx = rng.choice(n, K, replace=False)
    means = X[idx].copy()
    variances = np.ones((K, d))
    weights = np.full(K, 1.0 / K)

    log_likelihood_history = []

    for _ in range(n_iters):
        # ---- E-STEP: compute soft assignments gamma[i, k] ----
        log_probs = np.zeros((n, K))
        for k in range(K):
            log_gauss = -0.5 * np.sum(
                np.log(2 * np.pi * variances[k]) + (X - means[k]) ** 2 / variances[k], axis=1
            )
            log_probs[:, k] = np.log(weights[k] + 1e-12) + log_gauss
        # log-sum-exp trick for numerical stability (avoids overflow/underflow
        # when exponentiating -- another real production concern, not just
        # theoretical hygiene, exactly like the log-space trick in Naive Bayes).
        max_log = log_probs.max(axis=1, keepdims=True)
        log_norm = max_log + np.log(np.sum(np.exp(log_probs - max_log), axis=1, keepdims=True))
        log_gamma = log_probs - log_norm
        gamma = np.exp(log_gamma)  # shape (n, K), rows sum to 1

        log_likelihood_history.append(log_norm.sum())

        # ---- M-STEP: re-estimate parameters from soft assignments ----
        Nk = gamma.sum(axis=0)  # "effective" number of points per cluster
        weights = Nk / n
        means = (gamma.T @ X) / Nk[:, None]
        for k in range(K):
            diff = X - means[k]
            variances[k] = (gamma[:, k][:, None] * diff ** 2).sum(axis=0) / Nk[k] + 1e-6

    return weights, means, variances, log_likelihood_history


# ============================================================================
# CONCEPT #3 — GMM VS K-MEANS: K-MEANS IS A SPECIAL-CASE, HARD-ASSIGNMENT
# LIMIT OF EM
# ============================================================================
#
# k-means is often taught as a totally separate algorithm from GMM/EM. It
# isn't -- it's the limiting case of GMM's EM as you (a) force all
# clusters to have equal, isotropic, SHARED covariance (a single scalar
# variance for every cluster, every dimension) and (b) take the variance
# to zero. As variance -> 0, the soft E-step assignments gamma_{ik}
# become increasingly peaked -- in the limit, each point gets assigned
# with probability 1 to whichever cluster mean is nearest (in Euclidean
# distance) and 0 to all others: exactly k-means' HARD assignment rule.
# The M-step under hard assignment reduces exactly to "recompute each
# cluster's mean as the average of its assigned points" -- exactly
# k-means' update rule. This is why k-means inherits EM's core theoretical
# properties (monotonic decrease of the within-cluster sum-of-squares
# objective each iteration; convergence to a local, not necessarily
# global, optimum requiring multiple random restarts) for the exact same
# underlying reason GMM does -- it's the same algorithm with the
# covariance structure constrained to a degenerate special case, not a
# coincidentally similar but separate technique.


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A fraud-detection team wants to (a) flag transactions and (b) discover
# unlabeled fraud "types" for investigators to review. This splits cleanly
# along this lesson's two techniques:
#   - GAUSSIAN NAIVE BAYES as a fast, low-variance FIRST-PASS filter: with
#     very little labeled fraud data (fraud is rare -- classic class
#     imbalance), Naive Bayes' low-variance/low-data-requirement property
#     from Concept #1 lets it produce a usable baseline where a high-
#     capacity model would overfit the sparse positive class. It won't be
#     the final model, but it's cheap to stand up and hard to badly
#     overfit even with very few examples of the minority class.
#   - GMM (unsupervised) run on transaction feature vectors to discover
#     natural clusters -- some clusters will correspond to legitimate
#     spending patterns, others may isolate anomalous groups worth
#     investigator attention. Crucially, report the SOFT assignment
#     probabilities (gamma_ik), not a forced hard cluster label -- a
#     transaction that's genuinely ambiguous between "slightly unusual
#     but legitimate" and "a new fraud pattern" should show up with
#     gamma close to 0.5 across two clusters, which is actionable
#     information a k-means hard label would silently discard.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Computing Naive Bayes' product of probabilities in linear (not log)
#    space. With even 50-100 features, prod_j P(x_j|y) underflows to
#    exactly 0.0 in float64 long before you'd expect, silently breaking
#    the argmax comparison (all classes tie at 0.0). Always sum log-
#    probabilities, as gaussian_naive_bayes_predict does above.
# 2. Running EM/GMM from a single random initialization and trusting the
#    result. Because the likelihood surface is non-convex (Concept #2),
#    a single run can land in an arbitrarily bad local optimum -- always
#    run multiple restarts (5-10 is typical) and keep the highest final
#    log-likelihood.
# 3. Using k-means when clusters plausibly have very different sizes,
#    shapes, or densities, without checking that assumption. Because
#    k-means is EM's degenerate equal-isotropic-covariance special case
#    (Concept #3), it structurally CANNOT represent elongated or
#    differently-sized clusters well -- it will force roughly spherical,
#    similarly-sized partitions regardless of the true cluster geometry.
#    If clusters plausibly differ in shape/size, use full-covariance GMM
#    (or DBSCAN/HDBSCAN, outside this lesson's scope) instead.
# 4. Interpreting a fitted GMM's components as literal, ground-truth
#    subpopulations. EM finds A local optimum of the likelihood for the
#    NUMBER of components K you chose -- it does not discover the "true"
#    K, and re-running with K+1 or K-1 will produce a differently-shaped
#    (and possibly equally plausible) answer. Use a model-selection
#    criterion (BIC/AIC, penalizing higher K) rather than treating your
#    initial K choice as ground truth.


if __name__ == "__main__":
    print("=" * 70)
    print("GAUSSIAN NAIVE BAYES on a simple 2-class, 2-feature problem")
    print("=" * 70)
    rng = np.random.default_rng(0)
    X0 = rng.normal(loc=[0, 0], scale=1.0, size=(100, 2))
    X1 = rng.normal(loc=[3, 3], scale=1.0, size=(100, 2))
    X = np.vstack([X0, X1])
    y = np.array([0] * 100 + [1] * 100)
    classes, priors, means, vars_ = gaussian_naive_bayes_fit(X, y)
    preds = gaussian_naive_bayes_predict(X, classes, priors, means, vars_)
    accuracy = (preds == y).mean()
    print(f"Training accuracy: {accuracy:.3f}  (well-separated Gaussians -> should be high")
    print("despite the independence assumption being exactly TRUE here by construction --")
    print("this dataset doesn't test robustness to violated independence, just correctness.)")

    print("\n" + "=" * 70)
    print("GMM VIA EM: log-likelihood should increase monotonically every iteration")
    print("=" * 70)
    X_mix = np.vstack([
        rng.normal(loc=[0, 0], size=(80, 2)),
        rng.normal(loc=[5, 5], size=(80, 2)),
        rng.normal(loc=[0, 5], size=(80, 2)),
    ])
    weights, means, variances, ll_history = gmm_em_fit(X_mix, K=3, n_iters=30, seed=1)
    diffs = np.diff(ll_history)
    print(f"Log-likelihood at iter 0:  {ll_history[0]:.2f}")
    print(f"Log-likelihood at iter 29: {ll_history[-1]:.2f}")
    print(f"All iteration-to-iteration changes non-negative (monotonic increase)? "
          f"{np.all(diffs >= -1e-6)}")
    print("-> This is the ELBO/Jensen's-inequality guarantee from Concept #2,")
    print("   verified numerically: EM never makes the likelihood worse.")
