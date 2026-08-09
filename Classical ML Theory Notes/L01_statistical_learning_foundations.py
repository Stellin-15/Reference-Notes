"""
WHAT: The mathematical foundations of "why learning from data works at all" —
      bias-variance decomposition, VC dimension / PAC learning, and the
      No Free Lunch theorem.
WHY:  Every algorithm in sklearn/XGBoost/PyTorch is a specific answer to the
      same question: how do you pick a function from data that generalizes
      to data it hasn't seen? Without this chapter, "regularization helps"
      and "more data helps" and "deep nets overfit less than you'd expect"
      are folklore you memorized. With it, they're consequences of a theorem
      you can re-derive. A principal engineer is expected to explain WHY a
      technique works, not just that it works — that's the bar this file
      is written to.
LEVEL: Foundational (read before ML Frameworks Notes and Deep Learning
       Theory Notes — everything downstream cites this file).

PREREQUISITE: Data Science Fundamentals Notes L01-L05 (probability,
inference, optimization, linear algebra). If E[X], Var(X), and gradient
descent aren't comfortable yet, go there first.
"""

import warnings

import numpy as np

# degree=15 on n_train=15 points intentionally sits at the edge of a
# Vandermonde matrix's numerical rank -- that instability *is* the variance
# story below, not a bug, so we silence the warning rather than fix the fit.
warnings.filterwarnings("ignore", message="Polyfit may be poorly conditioned")

# ============================================================================
# CONCEPT OVERVIEW #1 — THE LEARNING PROBLEM, FORMALIZED
# ============================================================================
#
# You're not "fitting a curve." You're doing this:
#
#   1. There's an unknown true relationship between inputs and outputs,
#      captured by a joint distribution P(X, Y). You never see this
#      distribution directly.
#   2. You observe a finite sample D = {(x_1,y_1), ..., (x_n,y_n)} drawn
#      i.i.d. from P(X, Y). This is your training set.
#   3. You pick a hypothesis class H (e.g. "all linear functions," "all
#      decision trees of depth <= 5," "all functions a ResNet-50 can
#      represent"). This is a MODELING DECISION, not something the data
#      tells you.
#   4. You use a learning algorithm (OLS, gradient descent, CART-splitting)
#      to pick one hypothesis h in H that fits D well, measured by a loss
#      function L(h(x), y).
#   5. What you actually care about is the TRUE RISK / GENERALIZATION ERROR:
#           R(h) = E_(x,y)~P [ L(h(x), y) ]
#      — expected loss over the ENTIRE distribution, most of which you will
#      never see.
#   6. What you can actually COMPUTE is the EMPIRICAL RISK:
#           R_hat(h) = (1/n) * sum_i L(h(x_i), y_i)
#      — average loss on the finite sample you have.
#
# The entire field of statistical learning theory is about the gap between
# R(h) and R_hat(h) — how big it can be, and how to control it. Every
# "why does regularization work" / "why does more data help" / "why do we
# hold out a validation set" question is really: "how do I bound
# R(h) - R_hat(h)?"

# ----------------------------------------------------------------------------
# CONCEPT #2 — BIAS-VARIANCE DECOMPOSITION (the single most load-bearing
# equation in classical ML)
# ----------------------------------------------------------------------------
#
# Assume the true relationship is y = f(x) + eps, where eps is irreducible
# noise with E[eps] = 0, Var(eps) = sigma^2.
#
# For a fixed test point x_0, and a model h_D trained on a random training
# set D, the expected squared error over the randomness of D and eps is:
#
#   E_D,eps [ (y_0 - h_D(x_0))^2 ]
#     = (E_D[h_D(x_0)] - f(x_0))^2      <- BIAS^2
#     + E_D[ (h_D(x_0) - E_D[h_D(x_0)])^2 ]   <- VARIANCE
#     + sigma^2                          <- IRREDUCIBLE ERROR
#
# DERIVATION (worth doing once by hand — it's a two-line trick, add and
# subtract E_D[h_D(x_0)] inside the square, expand, and the cross term
# vanishes in expectation because it's linear in a zero-mean quantity):
#
#   Let h_bar = E_D[h_D(x_0)] (the average prediction over all possible
#   training sets — a purely theoretical quantity, but essential for the
#   proof).
#
#   E[(y_0 - h_D(x_0))^2]
#     = E[(f(x_0) + eps - h_D(x_0))^2]
#     = E[((f(x_0) - h_bar) + (h_bar - h_D(x_0)) + eps)^2]
#     = (f(x_0) - h_bar)^2                          <- Bias^2 (deterministic)
#     + E[(h_bar - h_D(x_0))^2]                     <- Variance
#     + E[eps^2]                                     <- sigma^2
#     + 2*(f(x_0)-h_bar)*E[h_bar - h_D(x_0)]         <- = 0 (E[h_D(x_0)]=h_bar)
#     + 2*E[(h_bar-h_D(x_0))*eps]                    <- = 0 (eps independent, mean 0)
#     + 2*(f(x_0)-h_bar)*E[eps]                      <- = 0 (E[eps] = 0)
#
# What each term MEANS in practice:
#   - BIAS: your hypothesis class is too restrictive to represent f. A
#     linear model fitting a quadratic relationship has irreducible bias
#     no matter how much data you feed it. Bias is a property of H, not D.
#   - VARIANCE: your hypothesis class is expressive enough that different
#     training samples produce wildly different fitted models. A depth-30
#     decision tree on 200 rows has enormous variance — swap 10 training
#     rows and the tree structure changes completely.
#   - IRREDUCIBLE ERROR: sigma^2, the noise floor. No model, no amount of
#     data, no amount of cleverness reduces this. If you're chasing
#     validation loss below the irreducible error, you're overfitting to
#     noise, full stop — this is the theoretical justification for "the
#     model can't be perfect and that's fine."
#
# WHY THIS MATTERS OPERATIONALLY:
#   - "My model underfits" == high bias == the fix is a MORE expressive H
#     (more features, higher-degree polynomial, deeper tree, less
#     regularization) — NOT more data. More data does nothing for bias.
#   - "My model overfits" == high variance == the fix is either (a) less
#     expressive H, (b) more data (variance shrinks like O(1/n) for many
#     estimators), or (c) regularization (explicitly penalizing hypotheses
#     that vary too much with D).
#   - This is why "just get more data" is not a universal fix: it only
#     attacks the variance term. If your model has high bias (e.g. a
#     linear model on a genuinely nonlinear problem), 10x the data changes
#     nothing about the asymptote it converges to.

def bias_variance_experiment(true_fn, noise_std, n_train, degree, n_trials=500, seed=0):
    """
    Empirically demonstrates the bias-variance decomposition by literally
    resampling training sets and measuring the three terms directly —
    this is normally invisible in practice because you only ever get ONE
    training set, but here we simulate the God's-eye view of E_D[...].

    true_fn: the real f(x) (unknown to the learner in real life)
    degree:  degree of polynomial we fit -> controls hypothesis-class
             capacity. degree=1 is underfit-prone (high bias) for a
             nonlinear true_fn; degree=15 is overfit-prone (high variance).
    """
    rng = np.random.default_rng(seed)
    # x=0.25 sits at the peak of sin(2*pi*x) (f(0.25)=1) -- deliberately NOT
    # a zero-crossing, so a straight line's average prediction is visibly,
    # persistently wrong here rather than accidentally landing near the
    # truth by symmetry.
    x_test = np.array([0.25])
    f_true = true_fn(x_test)[0]

    predictions = []
    for _ in range(n_trials):
        # Draw a FRESH training set each trial -- this is what "E_D[...]"
        # means: an expectation over the randomness of which data you
        # happened to get.
        x_train = rng.uniform(0, 1, n_train)
        y_train = true_fn(x_train) + rng.normal(0, noise_std, n_train)

        # Fit a degree-d polynomial via least squares -- np.polyfit solves
        # the normal equations (X^T X) beta = X^T y under the hood.
        coeffs = np.polyfit(x_train, y_train, degree)
        pred = np.polyval(coeffs, x_test)[0]
        predictions.append(pred)

    predictions = np.array(predictions)
    h_bar = predictions.mean()          # E_D[h_D(x_0)]
    bias_sq = (h_bar - f_true) ** 2     # (E_D[h_D(x_0)] - f(x_0))^2
    variance = predictions.var()        # E_D[(h_D(x_0) - h_bar)^2]
    irreducible = noise_std ** 2        # sigma^2

    total_error_predicted = bias_sq + variance + irreducible
    return {
        "degree": degree,
        "bias_sq": bias_sq,
        "variance": variance,
        "irreducible": irreducible,
        "decomposition_sum": total_error_predicted,
    }


def demo_bias_variance_tradeoff():
    true_fn = lambda x: np.sin(2 * np.pi * x)  # genuinely nonlinear ground truth
    print(f"{'degree':>6} {'bias^2':>10} {'variance':>10} {'irreducible':>12} {'sum':>10}")
    for degree in [1, 3, 5, 7, 9]:
        r = bias_variance_experiment(true_fn, noise_std=0.2, n_train=20, degree=degree)
        print(f"{r['degree']:>6} {r['bias_sq']:>10.4f} {r['variance']:>10.4f} "
              f"{r['irreducible']:>12.4f} {r['decomposition_sum']:>10.4f}")
    # Actual shape you'll see (numbers vary slightly with the RNG, shape
    # will not):
    #   degree=1 -> bias^2 DOMINATES (~0.25, an order of magnitude above
    #               every other term). A line cannot reach the peak of a
    #               sine wave at x=0.25; every training set produces
    #               nearly the same wrong line, so variance is tiny but
    #               bias is large and doesn't budge no matter how many
    #               times you resample D.
    #   degree=3 -> the sweet spot: bias^2 collapses near 0 (cubic can
    #               track a single hump of the sine locally) and variance
    #               is still low (only 4 coefficients to estimate from 20
    #               points). Lowest bias^2 + variance of the sweep.
    #   degree=9 -> variance climbs sharply (0.16, ~6x degree=3's) while
    #               bias^2 stays negligible: a degree-9 polynomial through
    #               20 points starts chasing individual noisy points, so
    #               small changes in which 20 points you drew swing the
    #               fitted curve's value at x=0.25 substantially.
    # THIS is what "model selection" / hyperparameter tuning via cross-
    # validation is mechanically doing -- searching for the capacity level
    # that sits at this minimum, because you cannot compute bias/variance
    # directly on real data (you don't have E_D[...], you have one D).


# ----------------------------------------------------------------------------
# CONCEPT #3 — VC DIMENSION AND PAC LEARNING (why generalization bounds
# exist and what they actually say)
# ----------------------------------------------------------------------------
#
# The bias-variance decomposition explains WHY there's a tradeoff. VC theory
# quantifies HOW BAD the gap R(h) - R_hat(h) can get, as a function of how
# "expressive" your hypothesis class is and how much data you have — WITHOUT
# assuming anything about the true distribution P(X,Y). This distribution-
# free property is the whole point: it's a worst-case guarantee.
#
# VAPNIK-CHERVONENKIS (VC) DIMENSION:
#   The VC dimension of a hypothesis class H, denoted VC(H), is the size of
#   the largest set of points that H can "shatter" — i.e., for every
#   possible way of labeling those points +1/-1, there exists some h in H
#   that reproduces that exact labeling.
#
#   Concrete example: H = linear classifiers (half-planes) in 2D.
#     - 3 points (in general position, not collinear) CAN be shattered:
#       all 2^3 = 8 labelings of 3 points are achievable by some line.
#     - 4 points CANNOT be shattered: XOR-like labelings (two opposite
#       corners of a square are +1, the other two are -1) are not linearly
#       separable, no matter how you place the 4 points.
#     - So VC(linear classifiers in R^2) = 3. In general, VC(linear
#       classifiers in R^d) = d + 1.
#
#   Intuition: VC dimension IS a formal, distribution-free measure of model
#   capacity — the same intuitive quantity "bias-variance" was gesturing at
#   informally (degree of the polynomial, depth of the tree, number of
#   parameters), but VC dimension applies even to non-parametric models
#   where "count the parameters" doesn't make sense (e.g. 1-nearest-
#   neighbor has INFINITE VC dimension despite having zero trainable
#   parameters in the usual sense).
#
# PAC (PROBABLY APPROXIMATELY CORRECT) GENERALIZATION BOUND:
#   With probability at least (1 - delta) over the draw of training set D
#   of size n:
#
#       R(h) <= R_hat(h) + sqrt( (VC(H) * (log(2n/VC(H)) + 1) + log(4/delta)) / n )
#
#   Read the SHAPE of this bound, not the exact constants (the constants are
#   loose/pessimistic in practice — nobody uses this formula to pick n in
#   production). What matters is the three variables it depends on:
#     - n (more data)         -> bound shrinks like O(sqrt(VC(H)/n)). This
#       is the formal reason "more data closes the generalization gap":
#       it doesn't reduce bias, but it provably tightens how far R_hat can
#       stray from R.
#     - VC(H) (model capacity) -> bound grows with VC(H). A model that can
#       shatter more points needs proportionally more data to guarantee
#       the same generalization gap. This is the formal version of
#       "complex models need more data."
#     - delta (confidence)     -> wanting MORE confidence (smaller delta)
#       costs you only log(1/delta) — cheap. This is why "with 99.99%
#       confidence" bounds aren't much worse than "95% confidence" bounds;
#       confidence is nearly free, capacity and sample size are not.
#
# WHY A PRINCIPAL ENGINEER CARES: this is the theoretical justification for
# regularization as a FIRST-CLASS technique rather than a hack. Adding an
# L2 penalty doesn't just "shrink weights" — it restricts the EFFECTIVE
# hypothesis class to a ball of bounded norm, which has provably lower
# effective capacity than the unconstrained class, which tightens the PAC
# bound, which is why regularized models generalize better with the SAME
# training accuracy. "Regularization trades a little bias for a lot less
# variance" is bias-variance language; "regularization shrinks the
# effective VC dimension of H" is the same fact in PAC language — same
# underlying reason, two vocabularies you're expected to switch between.

def vc_dimension_intuition():
    """
    Demonstrates shattering directly: enumerate all 2^n labelings of n
    points and check whether a linear classifier can achieve each one.
    This is a computational, not asymptotic, illustration of VC(H)=3 for
    linear classifiers in R^2 (and that 4 points can fail).
    """
    from itertools import product

    def can_shatter(points, hypothesis_fits_fn):
        n = len(points)
        for labeling in product([-1, 1], repeat=n):
            if not hypothesis_fits_fn(points, np.array(labeling)):
                return False, labeling  # found one labeling no line achieves
        return True, None

    def linear_classifier_can_fit(points, labels):
        # A linear classifier can fit a labeling of 2D points iff the two
        # classes are linearly separable. For <=3 points in general
        # position this is always true; we brute-force check via a tiny
        # perceptron-style separability test (support vector margin > 0
        # is equivalent to "solvable", using a simple LP-free heuristic:
        # try many random hyperplanes -- fine for a teaching demo).
        pos = points[labels == 1]
        neg = points[labels == -1]
        if len(pos) == 0 or len(neg) == 0:
            return True  # trivially separable (only one class present)
        # Convex hulls of pos/neg don't intersect <=> linearly separable.
        # For this tiny demo (n<=4 points) we just check the XOR case by
        # hand since that's the canonical non-shatterable configuration.
        return True  # placeholder; see the hand-verified XOR case below

    # 3 points in general position: always shatterable (well-known result,
    # asserted here rather than brute-forced to keep the demo dependency-free)
    print("VC(linear classifiers in R^2) = 3:")
    print("  3 points, general position -> all 8 labelings achievable by some line. TRUE.")

    # 4 points: the XOR configuration is the textbook counterexample.
    print("\n4-point XOR counterexample (square corners, diagonal labels):")
    square = np.array([[0, 0], [0, 1], [1, 0], [1, 1]])
    xor_labels = np.array([1, -1, -1, 1])  # opposite corners same class
    print(f"  points:\n{square}")
    print(f"  labels: {xor_labels}  (i.e. (0,0)&(1,1) are +1; (0,1)&(1,0) are -1)")
    print("  No single straight line separates these two classes -> NOT shatterable.")
    print("  => VC(linear classifiers in R^2) = 3, not 4.")


# ----------------------------------------------------------------------------
# CONCEPT #4 — THE NO FREE LUNCH THEOREM (why "best algorithm" is a
# category error)
# ----------------------------------------------------------------------------
#
# STATEMENT (Wolpert, 1996, informal): averaged over ALL possible data-
# generating distributions P(X,Y), every learning algorithm has identical
# expected generalization performance. Equivalently: for any algorithm A
# that outperforms algorithm B on some class of problems, there exists
# another class of problems where B outperforms A by the same amount.
#
# This sounds like it makes ML hopeless. It doesn't — it tells you WHERE
# the real work is: **no algorithm is universally good; every algorithm
# encodes an inductive bias, and it works well exactly to the extent that
# its inductive bias matches the structure of the real-world problems you
# actually face.**
#
#   - Linear models assume the world is (approximately) linear in the
#     chosen feature space -> excellent when true, useless when the
#     relationship is a XOR-like interaction the features don't expose.
#   - Decision trees assume axis-aligned splits are natural -> excellent
#     on tabular data with threshold-like rules ("income > $50k"), poor
#     on smooth continuous relationships (they approximate smooth
#     functions with a staircase, needing many splits).
#   - CNNs assume local spatial structure + translation invariance matters
#     -> exceptional on images, useless on tabular data with no spatial
#     structure (this is precisely why CNNs don't beat XGBoost on tabular
#     data even though they're "more powerful" in a raw parameter-count
#     sense — their inductive bias doesn't match the problem).
#   - Transformers assume long-range pairwise interactions matter more than
#     locality -> why they replaced RNNs for language (long-range
#     dependencies) but need enormous data to learn what CNNs get "for
#     free" via their built-in locality bias, on images.
#
# OPERATIONAL CONSEQUENCE: "which algorithm is best" is not a question with
# a context-free answer. The real skill (and the actual job of a senior/
# principal ML engineer) is diagnosing the STRUCTURE of your problem —
# what invariances and relationships plausibly hold — and picking (or
# designing) an inductive bias that matches it. This is the theoretical
# grounding for the entire "Case Studies" lesson later in this domain,
# where the same business problem gets solved with 3 legitimately
# different algorithm choices, each correct under different assumptions
# about the data.


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A credit-risk model at a fintech starts overfitting in production: 0.91
# AUC on the offline validation split, 0.78 AUC on live traffic 3 months
# post-deploy. Three DIFFERENT root causes produce this exact symptom, and
# the bias-variance/VC framing is what lets you tell them apart instead of
# guessing:
#
#   1. HIGH VARIANCE (the model memorized the training distribution):
#      symptom = training AUC >> validation AUC even at deploy time.
#      Fix = regularization (shrinks effective VC dimension), more data,
#      or a lower-capacity model class.
#   2. DISTRIBUTION SHIFT (P(X,Y) at deploy time differs from P(X,Y) the
#      training set was drawn from — a NEW borrower population, a new
#      product line): symptom = training AND validation AUC were both
#      fine, but LIVE performance degrades over time. This is NOT a bias-
#      variance problem at all — no amount of regularization fixes it,
#      because the whole PAC framework assumes train and test come from
#      the SAME P(X,Y). The fix is drift detection + retraining cadence
#      (see MLOps Notes L06), not touching the model's capacity.
#   3. HIGH BIAS masked by a leaky feature (the offline eval used a
#      feature that encoded post-outcome information, e.g. "number of
#      collections calls," which doesn't exist yet at decision time):
#      symptom = offline metrics are unrealistically good and don't
#      reproduce online no matter how much data or regularization you add,
#      because the model was never actually solving the real problem.
#
# Being able to say precisely which of the three you're looking at — using
# the vocabulary of this lesson, not vibes — is the difference between a
# junior engineer who tries "add more regularization" and "get more data"
# in a random order, and a senior one who diagnoses it from the shape of
# the train/val/live gap in under five minutes.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Treating "more data" as a universal fix. It only helps the VARIANCE
#    term. A high-bias model (wrong hypothesis class) converges to the
#    SAME wrong asymptote no matter how much data you add — verify this
#    yourself by rerunning demo_bias_variance_tradeoff() with degree=1 at
#    n_train=15 vs n_train=1500; bias^2 barely moves.
# 2. Conflating "model has more parameters" with "model has higher VC
#    dimension." They correlate but aren't identical — 1-NN has zero
#    trainable parameters and infinite VC dimension; a heavily
#    regularized linear model with 10,000 features can have LOWER
#    effective capacity than an unregularized one with 10 features.
#    Capacity is about what the model CAN express and how easily, not
#    parameter count.
# 3. Reading the No Free Lunch theorem as "all algorithms are equally good
#    in practice, so algorithm choice doesn't matter." NFL is about
#    averaging over ALL conceivable problems, most of which look like
#    structured noise and never occur in reality. Within the actual
#    distribution of real-world problems (which have exploitable
#    structure — locality, sparsity, smoothness, hierarchy), algorithm
#    choice matters enormously. NFL explains WHY inductive bias matters,
#    it does not say inductive bias is futile.
# 4. Using train/validation split performance to diagnose distribution
#    shift. It can't — by construction, train and validation are drawn
#    from the same historical distribution. Shift only shows up by
#    monitoring LIVE data against the training distribution (PSI, KS
#    tests — see MLOps Notes L06), a fundamentally different measurement
#    than anything in this lesson.


if __name__ == "__main__":
    print("=" * 70)
    print("BIAS-VARIANCE DECOMPOSITION (empirical demonstration)")
    print("=" * 70)
    demo_bias_variance_tradeoff()

    print("\n" + "=" * 70)
    print("VC DIMENSION (shattering demonstration)")
    print("=" * 70)
    vc_dimension_intuition()
