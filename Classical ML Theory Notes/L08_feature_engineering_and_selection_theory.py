"""
WHAT: Mutual information as the general-purpose feature-relevance measure
      (a strict superset of correlation), the curse of dimensionality
      derived quantitatively (not just asserted), and why L1 sparsity
      (from L02) is one of several distinct approaches to feature
      selection, each with a different failure mode.
WHY:  "Correlation only catches linear relationships, use mutual
      information for nonlinear ones" is usually stated without showing
      WHY. "High dimensions are bad" is usually illustrated with hand-
      waving about hypercubes. This lesson derives both from their actual
      definitions, and gives a decision framework for filter/wrapper/
      embedded feature selection instead of defaulting to whichever one
      a tutorial happened to use.
LEVEL: Foundational -- closes out the Classical ML Theory track's
       lesson sequence before the case-studies capstone.

PREREQUISITE: L02 (L1 regularization as embedded feature selection);
Data Science Fundamentals Notes L01 (entropy, from the probability
lesson) underlies mutual information below.
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — MUTUAL INFORMATION: WHY IT CATCHES RELATIONSHIPS
# CORRELATION PROVABLY CANNOT
# ============================================================================
#
# PEARSON CORRELATION measures the strength of a LINEAR relationship:
#   corr(X,Y) = Cov(X,Y) / (std(X)*std(Y))
# By construction, it is a summary of a single number (the best-fit
# line's slope, rescaled) -- it can be EXACTLY ZERO for variables that are
# perfectly, deterministically related, if that relationship is nonlinear
# and symmetric enough that positive and negative deviations cancel in
# the covariance sum. The canonical example: Y = X^2 with X symmetric
# around 0 (e.g. X ~ Uniform(-1,1)). Y is a DETERMINISTIC function of X
# (perfect relationship, zero noise) yet Cov(X,Y) = E[X*X^2] - E[X]*E[X^2]
# = E[X^3] - 0 = 0 (X^3 is an odd function, integrates to 0 over a
# symmetric interval). Correlation reports ZERO for a perfect relationship
# -- not "weak," literally zero. This is not an edge case to be wary of;
# it's a structural blind spot of any linear-relationship-only measure.
#
# MUTUAL INFORMATION is defined directly from entropy (Data Science
# Fundamentals Notes L01 / this domain's L03) with NO linearity assumption
# baked in at all:
#   I(X;Y) = H(X) - H(X|Y) = H(Y) - H(Y|X)
#          = sum_x sum_y  P(x,y) * log( P(x,y) / (P(x)*P(y)) )
# Read it as: "how much does knowing Y reduce my uncertainty about X" (or
# symmetrically, Y about X). I(X;Y) = 0 IF AND ONLY IF X and Y are fully
# INDEPENDENT (P(x,y) = P(x)*P(y) for all x,y, making every term in the
# sum zero) -- not "linearly unrelated," but genuinely, distributionally
# independent. For the Y=X^2 example above, X and Y are obviously NOT
# independent (knowing X tells you Y EXACTLY), so I(X;Y) is large and
# positive, correctly flagging the relationship correlation missed
# entirely. This is why mutual information (or its normalized cousins) is
# the standard filter-based feature-relevance score when you can't assume
# linearity upfront -- it is measuring the RIGHT quantity (statistical
# dependence in general), of which linear correlation is a special case
# that only detects a subset of possible dependencies.

def mutual_information_discrete(x, y, bins=10):
    """
    Estimates I(X;Y) for continuous data by discretizing into bins and
    computing the discrete-entropy formula directly -- the standard
    "binning" estimator (histogram-based MI). Production code typically
    uses sklearn.feature_selection.mutual_info_regression/classif, which
    uses a more sample-efficient k-nearest-neighbor estimator (Kraskov et
    al.), but the binning estimator here makes the underlying definition
    fully explicit rather than hidden inside a library call.
    """
    x_binned = np.digitize(x, np.histogram(x, bins=bins)[1][1:-1])
    y_binned = np.digitize(y, np.histogram(y, bins=bins)[1][1:-1])
    joint = np.zeros((bins + 1, bins + 1))
    for xb, yb in zip(x_binned, y_binned):
        joint[xb, yb] += 1
    joint /= joint.sum()
    px = joint.sum(axis=1, keepdims=True)
    py = joint.sum(axis=0, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        term = joint * np.log(joint / (px * py))
    return np.nansum(np.where(joint > 0, term, 0.0))


def pearson_correlation(x, y):
    return np.corrcoef(x, y)[0, 1]


# ============================================================================
# CONCEPT #2 — THE CURSE OF DIMENSIONALITY, QUANTIFIED (not just asserted)
# ============================================================================
#
# Three separate, derivable facts, each independently explaining why
# "just add more features" degrades many algorithms:
#
#   FACT 1 -- VOLUME CONCENTRATES NEAR THE SURFACE. Consider a unit
#   hypercube [0,1]^d and an inscribed "shell" of thickness epsilon near
#   the boundary. The fraction of the cube's volume OUTSIDE this shell
#   (i.e. the "core") is (1-epsilon)^d. As d grows, (1-epsilon)^d -> 0
#   for any fixed epsilon > 0 -- almost ALL the volume of a high-
#   dimensional cube lives within an arbitrarily thin shell near its
#   surface. Concretely: with epsilon=0.05 (a shell 5% of the way in from
#   each face) and d=1, 95% of the volume is "core." At d=100,
#   (0.95)^100 ≈ 0.6%, meaning 99.4% of the volume is in that thin shell.
#   Points sampled uniformly in high dimensions are, almost surely, near
#   an edge/corner -- "the middle" of a high-dimensional space is
#   essentially empty of data.
#
#   FACT 2 -- DISTANCES CONCENTRATE (nearest and farthest neighbor
#   distances become nearly equal). For many common distributions, as
#   d -> infinity, the ratio (max_distance - min_distance) / min_distance
#   -> 0 -- every point becomes ROUGHLY equidistant from every other
#   point. This directly breaks any algorithm relying on "nearby points
#   are meaningfully more similar than far points" -- k-NN, kernel
#   methods with a fixed bandwidth, and density-based clustering all
#   degrade because the core notion of "near" stops discriminating.
#
#   FACT 3 -- SAMPLE DENSITY COLLAPSES EXPONENTIALLY. To maintain the
#   same DENSITY of data points per unit volume as dimension grows, the
#   number of samples needed grows EXPONENTIALLY in d. Equivalently: a
#   fixed sample size n that densely covers a low-dimensional space
#   becomes vanishingly sparse in a high-dimensional one -- this is the
#   direct link back to L01's VC-dimension/PAC bound: capacity (here,
#   effectively driven by dimensionality) needs proportionally more data
#   to achieve the same generalization guarantee, and that "proportional"
#   relationship is exponential in naive high-dimensional settings unless
#   the data has EXPLOITABLE LOW-DIMENSIONAL STRUCTURE (a manifold, sparse
#   support, strong feature correlation) that a good feature-engineering
#   or dimensionality-reduction step (L06's PCA) can uncover and exploit.

def demonstrate_distance_concentration(dims_list, n_points=1000, seed=0):
    """
    For increasing dimensionality, measure the ratio
    (max_pairwise_distance - min_pairwise_distance) / min_pairwise_distance
    on points drawn uniformly at random -- Fact 2, made numerically
    concrete instead of asserted.
    """
    rng = np.random.default_rng(seed)
    results = {}
    for d in dims_list:
        X = rng.uniform(size=(n_points, d))
        # Distances from a single fixed query point to all others is
        # enough to illustrate the concentration effect and is far
        # cheaper than the full pairwise matrix.
        query = rng.uniform(size=d)
        dists = np.linalg.norm(X - query, axis=1)
        ratio = (dists.max() - dists.min()) / dists.min()
        results[d] = ratio
    return results


# ============================================================================
# CONCEPT #3 — THREE DISTINCT FAMILIES OF FEATURE SELECTION, AND WHEN EACH
# ONE'S FAILURE MODE ACTUALLY BITES
# ============================================================================
#
# FILTER METHODS (e.g. rank features by mutual information or correlation
# with y, keep the top-k): score each feature INDEPENDENTLY of any
# specific model, before training. FAST (no repeated model training) and
# MODEL-AGNOSTIC (the ranking transfers across different downstream
# models). FAILURE MODE: entirely blind to feature INTERACTIONS -- two
# individually-useless features can be jointly highly predictive (the
# canonical example is XOR: neither X1 nor X2 alone correlates or shares
# mutual information with y=XOR(X1,X2) beyond chance, yet the PAIR
# determines y exactly). A filter method will discard both, because it
# never evaluates them together.
#
# WRAPPER METHODS (e.g. forward selection, backward elimination, RFE --
# Recursive Feature Elimination): repeatedly train an actual model on
# candidate feature SUBSETS and keep whichever subset performs best on
# validation data. Because it evaluates subsets (not single features in
# isolation), it CAN catch interactions filter methods miss. FAILURE
# MODE: combinatorially expensive (evaluating all subsets is 2^p; even
# greedy forward/backward search is O(p^2) model-training runs) and prone
# to overfitting the SELECTION process itself to the validation set if
# that same validation set is reused for final model evaluation --
# effectively a form of the multiple-comparisons problem (Data Science
# Fundamentals Notes L02) applied to feature-subset choices instead of
# hypotheses.
#
# EMBEDDED METHODS (e.g. L1/lasso from L02, or tree-based feature
# importance from L03): feature selection happens AS A BYPRODUCT of
# fitting the model itself (lasso's optimization naturally zeroes out
# some coefficients; a tree's splits naturally ignore uninformative
# features). Cheaper than wrapper methods (one training run, not many)
# and CAN capture some interactions (a tree's later splits are
# conditioned on earlier ones, so tree-based importance implicitly
# reflects some interaction structure). FAILURE MODE: the selection is
# entangled with and biased by that SPECIFIC model class's inductive
# bias (L01's No Free Lunch point, again) -- lasso's grouping-effect
# instability (L02) is exactly this failure mode: which correlated
# feature gets "selected" depends on lasso's specific penalty geometry,
# not a model-agnostic notion of relevance.
#
# THE DECISION RULE THIS IMPLIES: use filter methods for a fast first
# pass on very high-dimensional data (thousands+ of candidate features,
# where wrapper methods are computationally infeasible) specifically to
# discard OBVIOUSLY irrelevant features, never as the final word if
# interactions are plausible. Use wrapper methods when the feature count
# is moderate (tens, not thousands) and interactions are suspected. Use
# embedded methods as a practical default when you're fitting the
# eventual production model anyway and want selection "for free," while
# remaining aware that the selected set is a property of THAT model
# class, not an absolute ranking of feature importance.

def xor_interaction_demo(n=2000, seed=0):
    """Confirms Concept #3's XOR claim numerically: neither individual
    feature correlates with y, but the pair determines y exactly."""
    rng = np.random.default_rng(seed)
    x1 = rng.integers(0, 2, n).astype(float)
    x2 = rng.integers(0, 2, n).astype(float)
    y = (x1.astype(int) ^ x2.astype(int)).astype(float)  # XOR
    corr_x1 = pearson_correlation(x1, y)
    corr_x2 = pearson_correlation(x2, y)
    # A perfect classifier from the PAIR: y is deterministic given (x1,x2)
    perfect_rule_accuracy = np.mean(((x1.astype(int) ^ x2.astype(int))) == y.astype(int))
    return corr_x1, corr_x2, perfect_rule_accuracy


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A credit-underwriting model starts with 800 raw signals (demographic,
# behavioral, bureau data). The feature-selection pipeline correctly
# applies all three families from Concept #3 in sequence, not as
# competing alternatives:
#   1. FILTER first: compute mutual information between each of the 800
#      features and the default label, drop the bottom ~500 that show
#      near-zero MI with y -- fast, and safe as a coarse first pass
#      because truly irrelevant features (e.g. an internal database ID)
#      are exceedingly unlikely to be part of a meaningful interaction
#      that a filter would wrongly discard.
#   2. EMBEDDED next: fit lasso/gradient-boosting on the remaining ~300
#      features, use the natural sparsity/importance ranking to narrow to
#      ~50 -- cheap because you're fitting a model you likely wanted
#      anyway, and can be validated against the filter step's independent
#      ranking (large disagreement between the two is itself a signal
#      worth investigating, not just noise to average away).
#   3. WRAPPER last, only on the final ~50: because the remaining
#      candidate set is small enough for the O(p^2) cost of backward
#      elimination or RFE to be tractable, and by this stage the team
#      needs the final feature LIST to be small and auditable (compliance
#      requirement: every feature in a credit model typically needs an
#      individually-documented business justification) -- a goal a
#      one-shot embedded selection doesn't guarantee as cleanly as
#      explicit, inspectable subset comparison does.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Using Pearson correlation as the only feature-relevance check and
#    discarding features with near-zero correlation. Per Concept #1, this
#    provably misses purely nonlinear relationships -- always sanity-check
#    with mutual information (or at minimum a scatter plot/binned mean
#    plot) before discarding a feature a domain expert believes should
#    matter.
# 2. Performing feature selection (of any kind) on the FULL dataset
#    before splitting into train/validation/test. This leaks label
#    information from the validation/test folds into the selection
#    process, inflating the apparent value of selected features -- the
#    fix is identical in spirit to preventing training-serving skew:
#    fit the selector ONLY on the training fold, exactly as you would
#    with a StandardScaler or any other fitted preprocessing step.
# 3. Assuming "the curse of dimensionality" means "always reduce
#    dimensions." Deep learning routinely operates in extremely high
#    (thousands to millions)-dimensional spaces successfully -- the curse
#    specifically bites algorithms that rely on RAW EUCLIDEAN DISTANCE or
#    DENSITY in the ORIGINAL feature space (k-NN, kernel methods with a
#    fixed bandwidth, plain clustering). High-capacity models that learn
#    their own lower-dimensional useful representations (trees splitting
#    on informative thresholds, neural nets learning embeddings) are far
#    less directly harmed by raw dimensionality, though they still need
#    proportionally more data as capacity grows (L01's PAC bound still
#    applies, just not via the distance-concentration mechanism
#    specifically).
# 4. Trusting a single wrapper-method run's chosen subset without
#    accounting for the multiple-comparisons problem described in
#    Concept #3. If you evaluated 200 candidate subsets against the same
#    validation set, the best-looking one is likely to look better than
#    it truly is purely from selection bias -- confirm the final choice
#    on a genuinely held-out test set never touched during selection.


if __name__ == "__main__":
    rng = np.random.default_rng(0)

    print("=" * 70)
    print("CONCEPT #1: correlation is exactly zero for a perfect Y=X^2 relationship")
    print("=" * 70)
    x = rng.uniform(-1, 1, 5000)
    y = x ** 2
    print(f"Pearson correlation(X, X^2):  {pearson_correlation(x, y):.5f}  (near zero)")
    print(f"Mutual information(X, X^2):   {mutual_information_discrete(x, y, bins=15):.5f}  (large, positive)")
    print("-> A deterministic, perfect relationship that correlation entirely misses,")
    print("   correctly flagged by mutual information.")

    print("\n" + "=" * 70)
    print("CONCEPT #2: distance concentration as dimensionality grows")
    print("=" * 70)
    ratios = demonstrate_distance_concentration([2, 10, 50, 200, 1000])
    for d, r in ratios.items():
        print(f"  dims={d:>5}:  (max-min)/min distance ratio = {r:.4f}")
    print("-> This ratio should shrink toward 0 as dimensionality grows --")
    print("   'nearest' and 'farthest' neighbor become nearly indistinguishable.")

    print("\n" + "=" * 70)
    print("CONCEPT #3: filter methods miss XOR-style feature interactions")
    print("=" * 70)
    c1, c2, acc = xor_interaction_demo()
    print(f"corr(x1, y): {c1:.4f}   corr(x2, y): {c2:.4f}   (both near zero individually)")
    print(f"Accuracy of the rule y=XOR(x1,x2), using BOTH features together: {acc:.4f}")
    print("-> A filter method ranking by individual correlation would discard both")
    print("   features, despite the pair determining y perfectly.")
