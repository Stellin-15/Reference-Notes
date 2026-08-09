"""
WHAT: Decision trees derived from an information-theoretic splitting
      criterion, then the two families of ensembling built on top of
      trees -- bagging (variance reduction) and boosting (bias reduction)
      -- derived from why averaging/sequential-correction works.
WHY:  "Random Forest averages many trees" and "XGBoost fits trees
      sequentially to residuals" are facts you can recite. This lesson
      derives WHY averaging reduces variance (a one-line variance-of-the-
      mean argument) and WHY sequential residual-fitting reduces bias
      (gradient boosting IS gradient descent, in function space), so you
      can predict how each ensemble family will behave on a new problem
      instead of pattern-matching to a past one.
LEVEL: Foundational.

PREREQUISITE: L01 (bias-variance decomposition) -- this entire lesson is
"bagging attacks the variance term, boosting attacks the bias term,"
applied.
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — DECISION TREE SPLITS: WHY ENTROPY/GINI, NOT ACCURACY
# ============================================================================
#
# A decision tree grows by repeatedly picking the (feature, threshold)
# split that most reduces "impurity" in the resulting child nodes. Two
# standard impurity measures for classification, both bounded in [0, 1]
# for the binary case and both 0 exactly at a pure node (all one class):
#
#   ENTROPY:  H(p) = -sum_k p_k * log2(p_k)
#   GINI:     G(p) = 1 - sum_k p_k^2   =  sum_k p_k*(1-p_k)
#
# A split's quality is scored by INFORMATION GAIN:
#   IG = H(parent) - [ (n_left/n)*H(left) + (n_right/n)*H(right) ]
# i.e. impurity before the split minus the (sample-size-weighted) average
# impurity after. The tree-building algorithm (CART / ID3 / C4.5) greedily
# picks, at each node, whichever (feature, threshold) pair maximizes IG.
#
# WHY NOT JUST MAXIMIZE ACCURACY DIRECTLY (0/1 loss) AT EACH SPLIT?
#   Misclassification rate as a splitting criterion is a much WEAKER
#   signal because it's insensitive to how "close" a split gets you to
#   purity. Concretely: consider a parent node that's 50/50, and two
#   candidate splits:
#     Split A: children are (70/30) and (30/70)  -- classification error
#              of each child, if you predict the majority class, is 30%
#              either way.
#     Split B: children are (90/10) and (10/90)  -- classification error
#              is also... 10% either way if you look ONLY at majority-
#              vote accuracy after ONE more split, misclassification rate
#              can be IDENTICAL for splits A and B in the two-class,
#              single-split-lookahead case, even though split B is
#              obviously more useful for building a deeper, more
#              confident tree.
#   Entropy and Gini are STRICTLY CONCAVE functions of p, which makes them
#   sensitive to exactly this kind of "how far toward purity did we get,"
#   not just "did the majority flip." This concavity is also what
#   guarantees information gain is always >= 0 -- a split (in the
#   population/infinite-sample limit) can never INCREASE impurity, which
#   is why greedy top-down tree growth is a sound (if not globally
#   optimal) algorithm: each local decision is provably non-harmful.
#
# ENTROPY VS GINI IN PRACTICE: they almost always pick the same splits
# (their curves over p are nearly identical in shape). Gini is marginally
# cheaper to compute (no log), which is why it's sklearn's/CART's default;
# entropy has a cleaner information-theoretic interpretation (bits of
# information gained) which is why ID3/C4.5 and some textbooks prefer it.
# The choice between them is NOT a meaningful design decision in most
# real projects -- unlike bagging vs boosting, which is.

def entropy(labels):
    _, counts = np.unique(labels, return_counts=True)
    p = counts / counts.sum()
    return -np.sum(p * np.log2(p + 1e-12))


def gini(labels):
    _, counts = np.unique(labels, return_counts=True)
    p = counts / counts.sum()
    return 1.0 - np.sum(p ** 2)


def information_gain(parent_labels, left_labels, right_labels, criterion=entropy):
    n = len(parent_labels)
    weighted_child_impurity = (
        len(left_labels) / n * criterion(left_labels)
        + len(right_labels) / n * criterion(right_labels)
    )
    return criterion(parent_labels) - weighted_child_impurity


# ============================================================================
# CONCEPT #2 — BAGGING: WHY AVERAGING INDEPENDENT MODELS REDUCES VARIANCE
# (the exact mechanism, from L01's decomposition)
# ============================================================================
#
# Recall L01: E[(y-h(x))^2] = bias^2 + variance + sigma^2. A single deep,
# unpruned decision tree has essentially ZERO bias (it can memorize the
# training set exactly) but HUGE variance (resample the training data
# slightly and the tree structure changes dramatically -- trees are
# famously "unstable" estimators).
#
# BAGGING (Bootstrap AGGregatING): train B trees, each on an independent
# bootstrap resample of the training data (sample n rows WITH replacement),
# then average their predictions (regression) or majority-vote (classi-
# fication).
#
# THE VARIANCE-REDUCTION MATH: if you average B i.i.d. random variables,
# each with variance sigma_h^2:
#   Var( (1/B) * sum_b h_b(x) ) = sigma_h^2 / B     <-- IF the h_b are
#                                                        independent
#
# This is the textbook "variance of a sample mean" result, applied to
# model predictions instead of data points. It says variance shrinks
# LINEARLY in 1/B as you add more independently-trained trees -- in the
# limit of infinite independent trees, variance -> 0, leaving only bias
# (which bagging does NOT reduce -- see below) and the irreducible sigma^2.
#
# THE CATCH -- bootstrap resamples are NOT independent (they're drawn from
# the same finite dataset, so they overlap heavily). With PAIRWISE
# CORRELATION rho between trees, the actual formula is:
#   Var(average) = rho*sigma_h^2 + (1-rho)*sigma_h^2/B
# As B -> infinity, this does NOT go to zero -- it converges to
# rho * sigma_h^2, a floor set entirely by how correlated the trees are.
# THIS IS THE EXACT REASON RANDOM FOREST ADDS FEATURE SUBSAMPLING on top
# of bagging: at each split, only consider a random subset of features
# (typically sqrt(p) for classification). This deliberately decorrelates
# the trees further (a strong feature can't dominate every tree's first
# split), pushing rho down, which pushes the variance floor down, which
# is the actual mechanism behind "Random Forest beats plain bagged trees"
# -- not a vague "more randomness is good" but a specific attack on the
# rho term in this formula.
#
# WHAT BAGGING DOES NOT DO: reduce bias. Averaging B copies of a biased
# estimator gives you an average estimator with the SAME bias (bias is
# about E[h(x)] missing f(x); averaging doesn't move the expectation).
# This is why bagging shallow, high-bias trees (e.g. depth-2 stumps) is a
# much worse idea than bagging deep, low-bias/high-variance trees --
# bagging has nothing to offer the bias term, so you want your base
# learner to already have near-zero bias before you apply it.

def bootstrap_sample(X, y, rng):
    n = len(y)
    idx = rng.integers(0, n, size=n)  # sample WITH replacement
    return X[idx], y[idx]


# ============================================================================
# CONCEPT #3 — BOOSTING: GRADIENT BOOSTING IS GRADIENT DESCENT IN FUNCTION
# SPACE (why boosting attacks BIAS, the opposite of bagging)
# ============================================================================
#
# Boosting builds an additive model SEQUENTIALLY:
#   F_0(x) = initial guess (e.g. the mean of y)
#   F_m(x) = F_{m-1}(x) + eta * h_m(x)      for m = 1..M
# where each h_m is a NEW, typically shallow (high-bias, low-variance)
# tree, and eta is the learning rate.
#
# THE KEY DERIVATION -- gradient boosting picks h_m to approximate the
# NEGATIVE GRADIENT of the loss with respect to the CURRENT predictions:
#
#   Think of F as a giant vector of predictions, one per training point:
#   F = (F(x_1), ..., F(x_n)). The training loss L(y, F) is a scalar
#   function of this vector. Ordinary gradient descent on a parameter
#   vector theta does: theta <- theta - eta * dL/dtheta. Gradient
#   boosting does the SAME THING, but treats F itself (not some
#   underlying parameter vector) as the thing being optimized:
#     F_m = F_{m-1} - eta * dL/dF |_{F=F_{m-1}}
#   The "gradient" dL/dF is a vector of per-point residual-like
#   quantities called PSEUDO-RESIDUALS: r_i = -dL(y_i,F(x_i))/dF(x_i).
#   Because F isn't a parametric object you can just subtract a gradient
#   from directly (there's no explicit "F vector" at inference time --
#   only a function you can evaluate), gradient boosting FITS A NEW TREE
#   h_m TO PREDICT the pseudo-residuals r_i, then adds eta*h_m(x) to F.
#   The new tree is a function-space stand-in for "the direction the
#   gradient points," which you can then evaluate at ANY x, not just the
#   n training points -- this is what makes it generalize.
#
# WORKED EXAMPLE -- squared-error loss L(y,F) = (1/2)(y-F)^2:
#   dL/dF = -(y - F)  =>  pseudo-residual r_i = y_i - F(x_i)
#   i.e. for squared-error loss, the pseudo-residual is EXACTLY the
#   ordinary residual, and "fit a tree to the pseudo-residuals" reduces
#   to the intuitive-sounding "fit a tree to what the current model got
#   wrong." For other losses (log-loss for classification, quantile loss,
#   Huber loss), the pseudo-residual formula changes but the mechanism
#   (fit a tree to approximate -dL/dF) is identical -- this is why
#   gradient boosting frameworks (XGBoost, LightGBM, CatBoost) can support
#   ANY differentiable loss function by just plugging in a different
#   gradient (and, for second-order methods like XGBoost, Hessian) formula.
#
# WHY BOOSTING ATTACKS BIAS: each successive tree is explicitly trained to
# correct the CURRENT model's systematic errors (the pseudo-residuals are
# exactly "what F_{m-1} is still getting wrong, on average"). This directly
# reduces the bias term from L01's decomposition -- a boosted ensemble of
# shallow trees can represent relationships far more complex than any
# single shallow tree, driving E[F(x)] toward f(x). The tradeoff: because
# each tree depends on the PREVIOUS tree's errors (a sequential, not
# independent, process), boosting can OVERFIT (increase variance) if run
# for too many rounds M or with too high a learning rate eta -- there is
# no rho-decorrelation mechanism protecting it the way Random Forest's
# feature subsampling protects bagging. This is exactly why early stopping
# (monitor validation loss, stop when it stops improving) is load-bearing
# for boosting in a way it is NOT for bagging -- bagging's variance floor
# means more trees essentially never hurts; boosting's bias-chasing means
# more rounds eventually WILL hurt.

class _RegressionStumpTree:
    """
    A minimal from-scratch CART regression tree (splits chosen by variance
    reduction -- the regression analogue of Concept #1's entropy/Gini for
    classification: minimize sum-of-squared-deviation-from-mean in each
    child, weighted by child size). Kept dependency-free (no sklearn) so
    the weak learner inside gradient boosting below is fully transparent
    rather than a black-box library call.
    """

    def __init__(self, max_depth=2, min_samples_split=4):
        self.max_depth = max_depth
        self.min_samples_split = min_samples_split
        self.tree = None  # nested dict: leaf -> {"value": v}, split -> {...}

    def _sse(self, y):
        return np.sum((y - y.mean()) ** 2) if len(y) > 0 else 0.0

    def _best_split(self, X, y):
        n, p = X.shape
        best = None  # (feature, threshold, gain)
        parent_sse = self._sse(y)
        for j in range(p):
            thresholds = np.unique(X[:, j])
            for t in thresholds[:-1]:  # skip the max value (empty right side)
                left_mask = X[:, j] <= t
                if left_mask.sum() < 1 or (~left_mask).sum() < 1:
                    continue
                child_sse = self._sse(y[left_mask]) + self._sse(y[~left_mask])
                gain = parent_sse - child_sse
                if best is None or gain > best[2]:
                    best = (j, t, gain)
        return best

    def _build(self, X, y, depth):
        if depth >= self.max_depth or len(y) < self.min_samples_split or np.allclose(y, y[0]):
            return {"leaf": True, "value": y.mean()}
        split = self._best_split(X, y)
        if split is None:
            return {"leaf": True, "value": y.mean()}
        j, t, _gain = split
        left_mask = X[:, j] <= t
        return {
            "leaf": False,
            "feature": j,
            "threshold": t,
            "left": self._build(X[left_mask], y[left_mask], depth + 1),
            "right": self._build(X[~left_mask], y[~left_mask], depth + 1),
        }

    def fit(self, X, y):
        self.tree = self._build(X, y, depth=0)
        return self

    def _predict_one(self, x, node):
        if node["leaf"]:
            return node["value"]
        branch = node["left"] if x[node["feature"]] <= node["threshold"] else node["right"]
        return self._predict_one(x, branch)

    def predict(self, X):
        return np.array([self._predict_one(x, self.tree) for x in X])


def gradient_boost_regressor(X, y, n_estimators=50, lr=0.1, max_depth=2):
    """
    From-scratch gradient boosting for squared-error loss, making the
    "fit a tree to the pseudo-residual, add eta*prediction to F" mechanism
    from Concept #3 fully explicit rather than hidden inside a library call.
    """
    F = np.full(shape=y.shape, fill_value=y.mean())  # F_0(x) = mean(y)
    trees = []
    for m in range(n_estimators):
        pseudo_residual = y - F  # dL/dF for squared error, as derived above
        tree = _RegressionStumpTree(max_depth=max_depth).fit(X, pseudo_residual)
        trees.append(tree)
        F = F + lr * tree.predict(X)  # F_m = F_{m-1} + eta * h_m(x)
    return trees, F


def gradient_boost_predict(trees, X, lr, y_train_mean):
    F = np.full(shape=(X.shape[0],), fill_value=y_train_mean)
    for tree in trees:
        F = F + lr * tree.predict(X)
    return F


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A churn model needs to hit a tight latency SLA and gets re-trained
# weekly on a noisy, small (40k row) dataset. Three plausible choices,
# distinguished by this lesson's bias/variance framing:
#
#   1. Random Forest if the training data is noisy/small and you're more
#      worried about VARIANCE (overfitting to this week's particular
#      40k rows) than bias -- RF's variance-reduction mechanism is robust
#      to noisy labels and requires almost no tuning (n_estimators=500,
#      default depth, done) to get a solid baseline.
#   2. Gradient Boosting (XGBoost/LightGBM) if you've confirmed via a
#      learning curve that the current model under-fits (train and
#      validation error are both still high and close together) -- i.e.
#      the problem is BIAS, which only boosting's sequential correction
#      mechanism addresses. Requires more careful tuning (learning rate,
#      n_estimators via early stopping, tree depth) because of the
#      overfitting risk described in Concept #3.
#   3. A shallow single tree (or a handful) if the actual deliverable is
#      an explainable rule set a risk/compliance team must sign off on --
#      neither ensemble is directly inspectable the way one small tree is;
#      this is a case where you deliberately accept WORSE accuracy (higher
#      bias AND variance than an ensemble) because interpretability is the
#      binding constraint, not predictive performance. (SHAP values, per
#      ML Frameworks Notes L03, are the usual compromise: keep the boosted
#      ensemble, attach an explainability layer -- valid when the
#      compliance requirement is "explain this decision," not
#      specifically "the model itself must be a decision tree.")

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Bagging shallow (high-bias) trees expecting the ensemble to fix bias.
#    Per Concept #2, bagging provably does not touch bias -- E[average] has
#    the same bias as E[single tree]. If validation error is dominated by
#    bias (train error is already high), the fix is deeper trees or
#    boosting, not more bagged shallow trees.
# 2. Running gradient boosting for a very large number of rounds "because
#    more is better," the way it's fine to do with Random Forest. Because
#    boosting attacks bias sequentially with no variance-decorrelation
#    mechanism, unlimited rounds WILL start fitting noise in the pseudo-
#    residuals. Always tune n_estimators via early stopping on a held-out
#    validation set, never by just maximizing it.
# 3. Assuming feature importance from a single tree (or even a small
#    forest) is stable/causal. A feature that's importance-ranked #1 in
#    one bootstrap resample can rank much lower in another, especially
#    among correlated features (the same instability issue lasso has, for
#    the same underlying reason -- correlated features "compete" for
#    credit somewhat arbitrarily). Use permutation importance averaged
#    over many resamples, or SHAP values, before making a business claim
#    about which feature "matters most."
# 4. Believing Random Forest "can't overfit" because it's often stated
#    that way. It's APPROXIMATELY true for the variance component (adding
#    trees rarely hurts, per the rho-floor argument), but RF still has
#    whatever bias its base trees have, and can still overfit via other
#    knobs (letting trees grow arbitrarily deep on a small dataset
#    increases rho by making trees more similar in the specific ways that
#    matter, or via leakage in the features themselves) -- "more trees is
#    safe" is not "the model is immune to overfitting."


if __name__ == "__main__":
    rng = np.random.default_rng(0)

    print("=" * 70)
    print("INFORMATION GAIN: comparing two candidate splits")
    print("=" * 70)
    parent = np.array([0] * 10 + [1] * 10)  # 50/50 parent node
    # Split A: children are 70/30 and 30/70 (moderate purity gain)
    leftA = np.array([0] * 7 + [1] * 3)
    rightA = np.array([0] * 3 + [1] * 7)
    # Split B: children are 90/10 and 10/90 (much purer)
    leftB = np.array([0] * 9 + [1] * 1)
    rightB = np.array([0] * 1 + [1] * 9)
    print(f"Split A (70/30, 30/70) information gain: {information_gain(parent, leftA, rightA):.4f}")
    print(f"Split B (90/10, 10/90) information gain: {information_gain(parent, leftB, rightB):.4f}")
    print("-> Split B's gain is higher: entropy is sensitive to HOW pure the")
    print("   children are, not just whether the majority class flipped.")

    print("\n" + "=" * 70)
    print("GRADIENT BOOSTING: pseudo-residuals shrink toward zero as F improves")
    print("=" * 70)
    X = rng.normal(size=(300, 3))
    y = np.sin(X[:, 0]) + 0.5 * X[:, 1] ** 2 - X[:, 2] + rng.normal(scale=0.1, size=300)
    trees, F_final = gradient_boost_regressor(X, y, n_estimators=100, lr=0.1, max_depth=2)
    final_residual = y - F_final
    print(f"Mean|residual| after 1 round would be ~{np.abs(y - y.mean()).mean():.4f} (F_0 = mean(y) only)")
    print(f"Mean|residual| after 100 rounds:        {np.abs(final_residual).mean():.4f}")
    print("-> Each round's tree explicitly targets the current residual, so")
    print("   residual magnitude should monotonically (roughly) shrink as")
    print("   rounds increase -- the bias-reduction mechanism, made visible.")
