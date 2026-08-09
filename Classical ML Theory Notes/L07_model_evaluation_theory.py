"""
WHAT: Why accuracy fails as a metric under class imbalance (a proof, not
      an opinion), the ROC/PR curve tradeoff derived from confusion-matrix
      arithmetic, calibration as a distinct property from discrimination,
      and how to tell whether a model-comparison result is statistically
      meaningful or noise.
WHY:  "Accuracy is misleading for imbalanced data, use F1 or AUC instead"
      is repeated as folklore. This lesson derives EXACTLY how misleading,
      derives the ROC curve point by point from the confusion matrix, and
      gives you the actual statistical test for "is model A really better
      than model B, or did I get lucky with this test split" -- a
      question most practitioners never formally answer.
LEVEL: Foundational.

PREREQUISITE: Data Science Fundamentals Notes L02 (hypothesis testing,
confidence intervals) -- this lesson's statistical-significance section
applies that machinery directly to model comparison.
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — WHY ACCURACY FAILS UNDER CLASS IMBALANCE (a derivation, not
# an assertion)
# ============================================================================
#
# Consider fraud detection: 0.5% of transactions are fraud. A classifier
# that predicts "not fraud" for EVERY transaction, ignoring the input
# entirely, achieves 99.5% accuracy. This isn't a contrived edge case --
# it's the DEFAULT behavior any accuracy-maximizing training process will
# converge toward under enough imbalance, because:
#
#   Accuracy = (TP + TN) / (TP + TN + FP + FN)
#
# When the negative class vastly outnumbers the positive class, TN
# dominates the numerator and denominator alike. A model can drive
# accuracy arbitrarily close to (1 - base_rate_of_positive_class) by
# doing NOTHING useful about the positive class whatsoever -- accuracy
# literally cannot distinguish "a model that ignores the minority class"
# from "a model that's mediocre at the minority class" from "a model
# that's excellent at the minority class," because a change in a handful
# of TP/FN outcomes barely moves a ratio dominated by a much larger TN
# count. This is a MATHEMATICAL property of the accuracy formula under
# imbalance, not a matter of opinion about which metric "feels" better.
#
# THE FIX ISN'T "USE A DIFFERENT SINGLE NUMBER" -- IT'S USE METRICS BUILT
# FROM THE MINORITY-CLASS-RELEVANT CELLS OF THE CONFUSION MATRIX:
#   PRECISION = TP / (TP + FP)   "of everything I flagged as fraud, how
#                                  much actually was fraud" -- ignores TN
#                                  entirely, so it can't be inflated by a
#                                  large negative class.
#   RECALL    = TP / (TP + FN)   "of all actual fraud, how much did I
#                                  catch" -- also ignores TN entirely.
#   F1        = 2*P*R / (P+R)    the harmonic mean of precision/recall --
#                                  harmonic (not arithmetic) mean specifically
#                                  because it heavily penalizes the case
#                                  where one of P or R is very low even if
#                                  the other is very high (arithmetic mean
#                                  of 0.99 and 0.01 is 0.5, misleadingly
#                                  "okay"-looking; harmonic mean of the
#                                  same two numbers is ~0.02, correctly
#                                  reflecting that a model excelling at
#                                  one and failing the other is bad).

def confusion_matrix_metrics(y_true, y_pred):
    tp = np.sum((y_true == 1) & (y_pred == 1))
    tn = np.sum((y_true == 0) & (y_pred == 0))
    fp = np.sum((y_true == 0) & (y_pred == 1))
    fn = np.sum((y_true == 1) & (y_pred == 0))
    accuracy = (tp + tn) / (tp + tn + fp + fn)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {"accuracy": accuracy, "precision": precision, "recall": recall, "f1": f1,
            "tp": tp, "tn": tn, "fp": fp, "fn": fn}


def demonstrate_accuracy_failure(base_rate=0.005, n=100000, seed=0):
    """The 'predict everything negative' classifier under real imbalance --
    computed directly from the confusion matrix definitions above, not
    asserted."""
    rng = np.random.default_rng(seed)
    y_true = (rng.uniform(size=n) < base_rate).astype(int)
    y_pred_lazy = np.zeros(n, dtype=int)  # predicts "not fraud" always
    return confusion_matrix_metrics(y_true, y_pred_lazy)


# ============================================================================
# CONCEPT #2 — THE ROC CURVE, DERIVED FROM SWEEPING A DECISION THRESHOLD
# ============================================================================
#
# Most classifiers output a continuous SCORE (a probability, or a raw
# decision value), and you pick a THRESHOLD t to convert it into a hard
# 0/1 prediction: predict 1 if score >= t. Every choice of t gives a
# different confusion matrix, hence different TPR and FPR:
#   TPR (True Positive Rate, = Recall) = TP / (TP + FN)
#   FPR (False Positive Rate)          = FP / (FP + TN)
#
# The ROC curve is the parametric plot of (FPR(t), TPR(t)) as t sweeps
# from 1 (nothing predicted positive -> FPR=TPR=0) down to 0 (everything
# predicted positive -> FPR=TPR=1). This is a DERIVED object, not an
# independently-defined curve -- every point on it corresponds to an
# actual achievable operating point of your classifier at some threshold.
#
# WHY ROC IS ROBUST TO CLASS IMBALANCE (unlike accuracy, and unlike a
# single precision/recall number at one threshold): TPR is computed
# entirely within the positive class (TP+FN is exactly the total count of
# actual positives), and FPR is computed entirely within the negative
# class (FP+TN is exactly the total count of actual negatives). Neither
# rate depends on the RATIO of positives to negatives in the dataset --
# so ROC curves computed on a 50/50 balanced sample and a 0.5/99.5
# imbalanced sample from the SAME underlying score distribution are
# IDENTICAL. This invariance is a real, provable property (not "ROC
# happens to look okay under imbalance") -- it's the direct algebraic
# consequence of TPR/FPR each being normalized within their own class.
#
# AUC (Area Under the ROC Curve) has a clean probabilistic interpretation
# worth knowing exactly: AUC equals the probability that a RANDOMLY chosen
# positive example receives a higher score than a randomly chosen negative
# example. AUC=0.5 is exactly what a coin-flip/random-score classifier
# achieves (regardless of class balance); AUC=1.0 means perfect separation
# (every positive outscores every negative).
#
# WHY PR (PRECISION-RECALL) CURVES ARE PREFERRED OVER ROC SPECIFICALLY
# UNDER SEVERE IMBALANCE: the exact ROC-invariance property above is a
# problem, not just a feature, when the NEGATIVE class is huge. Because
# FPR = FP/(FP+TN) and TN is enormous, even a large ABSOLUTE number of
# false positives (which could still overwhelm a human review queue in
# absolute terms) produces a tiny FPR and looks fine on an ROC curve. A
# model with 1,000 false positives out of 995,000 true negatives has
# FPR = 0.001 -- looks excellent on ROC -- but PRECISION = TP/(TP+FP)
# directly exposes that 1,000 false alarms might swamp a fraud-review
# team regardless of how small a fraction of the (huge) negative class
# they represent. This is precisely why PR-AUC, not ROC-AUC, is the
# standard reporting metric for severely imbalanced problems like fraud
# or rare-disease screening.

def roc_curve(y_true, scores, thresholds=None):
    if thresholds is None:
        thresholds = np.sort(np.unique(scores))[::-1]
    tpr_list, fpr_list = [], []
    P = np.sum(y_true == 1)
    N = np.sum(y_true == 0)
    for t in thresholds:
        y_pred = (scores >= t).astype(int)
        tp = np.sum((y_true == 1) & (y_pred == 1))
        fp = np.sum((y_true == 0) & (y_pred == 1))
        tpr_list.append(tp / P if P > 0 else 0.0)
        fpr_list.append(fp / N if N > 0 else 0.0)
    return np.array(fpr_list), np.array(tpr_list)


def auc_trapezoidal(fpr, tpr):
    # Sort by FPR ascending so the trapezoidal rule integrates left-to-right.
    order = np.argsort(fpr)
    trapezoid = getattr(np, "trapezoid", np.trapz)  # numpy >=2.0 renamed trapz
    return trapezoid(tpr[order], fpr[order])


# ============================================================================
# CONCEPT #3 — CALIBRATION IS A DIFFERENT PROPERTY FROM DISCRIMINATION
# (AUC can be excellent while calibration is terrible)
# ============================================================================
#
# DISCRIMINATION (what AUC measures): can the model RANK positives above
# negatives correctly? A model is well-discriminating if, whenever it
# should, it assigns a higher score to actual positives than actual
# negatives -- regardless of whether those scores mean anything as
# PROBABILITIES.
#
# CALIBRATION (a separate property AUC says nothing about): if the model
# outputs "0.7" for a group of examples, do approximately 70% of THOSE
# examples actually belong to the positive class? A model can have
# PERFECT AUC (ranks every positive above every negative) while being
# badly calibrated -- e.g. it might output 0.99 for every true positive
# and 0.51 for every true negative. Ranking is perfect (AUC=1.0), but the
# 0.51 score is a wildly overconfident estimate of that example's true
# ~0% probability of being positive.
#
# WHY THIS MATTERS OPERATIONALLY: any downstream system that uses the
# model's score AS a probability -- e.g. "flag for manual review if
# P(fraud) > 0.8," or "compute expected loss = P(default) * loan_amount"
# -- is silently broken if the model is well-ranked but poorly calibrated,
# even though every accuracy/AUC/F1 metric might look excellent. This is
# a classic gap between "the model looks great on the dashboard" and "the
# model is unsafe to use the way the business is using it."
#
# WHY IT HAPPENS: many high-capacity models (gradient boosting with many
# rounds, deep neural nets) are trained to minimize a RANKING-relevant
# loss (log-loss/cross-entropy still technically rewards calibration in
# theory, but with enough model capacity and enough rounds, the model can
# overfit the loss toward extreme, overconfident scores that still rank
# correctly, especially on the training data) -- discrimination and
# calibration are optimized for the SAME loss function but are not the
# same property of the fitted function, and standard training doesn't
# guarantee calibration survives model complexity/overfitting.
#
# THE STANDARD DIAGNOSTIC: a RELIABILITY DIAGRAM / calibration curve --
# bucket predictions by score, plot the bucket's average predicted score
# against its ACTUAL observed positive rate. A perfectly calibrated model
# lies exactly on the y=x diagonal. THE FIX: Platt scaling (fit a 1D
# logistic regression from raw score to true label, exactly as mentioned
# for SVM in L04) or isotonic regression, as a POST-HOC calibration layer
# on top of an already-well-discriminating model.

def calibration_curve(y_true, scores, n_bins=10):
    bin_edges = np.linspace(0, 1, n_bins + 1)
    bin_idx = np.digitize(scores, bin_edges[1:-1])
    mean_predicted, observed_rate = [], []
    for b in range(n_bins):
        mask = bin_idx == b
        if mask.sum() == 0:
            continue
        mean_predicted.append(scores[mask].mean())
        observed_rate.append(y_true[mask].mean())
    return np.array(mean_predicted), np.array(observed_rate)


# ============================================================================
# CONCEPT #4 — IS MODEL A ACTUALLY BETTER THAN MODEL B, OR IS THAT NOISE?
# ============================================================================
#
# Model A scores 0.842 AUC on the test set; Model B scores 0.839. Is A
# better? Most practitioners just pick the higher number. That's wrong
# whenever the test set is finite -- both numbers are ESTIMATES of the
# true generalization AUC, each with sampling variance, and 0.842 vs
# 0.839 on (say) a 2,000-row test set is very plausibly noise.
#
# THE CORRECT APPROACH -- treat this as exactly the hypothesis-testing
# problem from Data Science Fundamentals Notes L02, applied to PAIRED
# per-example predictions (paired because both models are scored on the
# SAME test examples, which lets you use a more powerful paired test than
# treating the two AUC estimates as independent):
#
#   1. BOOTSTRAP CONFIDENCE INTERVALS: resample the test set (with
#      replacement) B times (e.g. B=1000), recompute BOTH models' AUC on
#      each resample, and look at the distribution of (AUC_A - AUC_B)
#      across resamples. If the 95% interval of that DIFFERENCE excludes
#      zero, you have evidence the difference is real, not noise -- if it
#      straddles zero, you cannot conclude A is better than B from this
#      test set.
#   2. McNEMAR'S TEST (for a single accuracy-style comparison at one
#      threshold): specifically compares the two models' DISAGREEMENTS
#      (cases where A was right and B was wrong, vs. the reverse) using a
#      chi-squared statistic -- more statistically appropriate than
#      comparing two accuracy numbers independently, because it directly
#      targets the paired-disagreement structure rather than treating the
#      two accuracies as unrelated random variables.
#
# THE PRINCIPLED HABIT THIS BUILDS: NEVER report "Model A: 0.842, Model B:
# 0.839, A wins" as a bare fact. Report it with an uncertainty estimate
# (bootstrap CI on the difference), and explicitly say "not statistically
# distinguishable at this sample size" when that's the honest conclusion
# -- a small, unglamorous habit that separates a rigorous practitioner
# from one pattern-matching on whichever number happens to be higher.

def bootstrap_auc_difference(y_true, scores_a, scores_b, n_boot=1000, seed=0):
    rng = np.random.default_rng(seed)
    n = len(y_true)
    diffs = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        yt, sa, sb = y_true[idx], scores_a[idx], scores_b[idx]
        if len(np.unique(yt)) < 2:
            continue  # a resample with only one class present has no ROC
        fpr_a, tpr_a = roc_curve(yt, sa)
        fpr_b, tpr_b = roc_curve(yt, sb)
        diffs.append(auc_trapezoidal(fpr_a, tpr_a) - auc_trapezoidal(fpr_b, tpr_b))
    diffs = np.array(diffs)
    ci_low, ci_high = np.percentile(diffs, [2.5, 97.5])
    return diffs.mean(), ci_low, ci_high


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A recommendation-ranking model retrains weekly and gets A/B tested
# against the incumbent. Three of this lesson's concepts fire in sequence
# on a single incident: the new model shows 99.7% "click-prediction
# accuracy" (Concept #1's trap -- click rate is naturally low/imbalanced,
# so this number is nearly meaningless on its own); switching to PR-AUC
# reveals the new model is genuinely better at ranking likely-clicked
# items above unlikely ones (Concept #2); but a reliability diagram shows
# its predicted click probabilities are badly overconfident (Concept #3)
# -- which matters because the ranking score feeds a downstream expected-
# revenue calculation that multiplies P(click) by bid value, so miscali-
# bration directly corrupts a dollar figure the business uses, even though
# the RANKING itself is fine. The fix is Platt-scaling the new model's
# output before it reaches the revenue calculation, not retraining from
# scratch. Finally, before fully rolling out, bootstrap the AUC difference
# (Concept #4) between old and new models on the A/B test's held-out
# traffic to confirm the improvement isn't within noise before committing
# engineering effort to the swap.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Reporting a single accuracy number for an imbalanced problem without
#    also reporting the base rate. "94% accuracy" is meaningless without
#    knowing whether the majority class alone is 50% or 94% of the data
#    -- per Concept #1, the naive baseline to beat is (1 - minority rate),
#    not 50%.
# 2. Using ROC-AUC as the headline metric for a severely imbalanced
#    problem (positive rate under ~5%) instead of PR-AUC. Per Concept #2,
#    ROC's class-balance invariance is exactly what makes it INSENSITIVE
#    to the false-positive volume that actually matters operationally
#    under imbalance.
# 3. Assuming a high-AUC model's raw scores are usable as probabilities
#    without checking calibration (Concept #3). This especially bites
#    when the score feeds ANY downstream arithmetic (expected value,
#    thresholded alerting with a specific target precision, risk-weighted
#    decisions) rather than just being used for ranking/sorting.
# 4. Picking a "winning" model based on a single point estimate from one
#    test-set evaluation, with no uncertainty quantification (Concept #4)
#    -- especially dangerous with small test sets or when re-running
#    "which model wins" weekly on shifting data, where noise alone can
#    flip the apparent winner run to run.


if __name__ == "__main__":
    print("=" * 70)
    print("CONCEPT #1: accuracy of a 'predict nothing is fraud' classifier")
    print("=" * 70)
    m = demonstrate_accuracy_failure(base_rate=0.005, n=100000)
    print(f"Accuracy:  {m['accuracy']:.4f}   (looks excellent!)")
    print(f"Precision: {m['precision']:.4f}   Recall: {m['recall']:.4f}   F1: {m['f1']:.4f}")
    print("-> Precision/recall/F1 are all 0.0 -- correctly exposing that this")
    print("   'excellent' 99.5% accuracy model catches ZERO fraud.")

    print("\n" + "=" * 70)
    print("CONCEPT #2: ROC-AUC probabilistic interpretation, verified directly")
    print("=" * 70)
    rng = np.random.default_rng(0)
    n = 2000
    y_true = (rng.uniform(size=n) < 0.3).astype(int)
    scores = y_true * rng.normal(1.5, 1, n) + (1 - y_true) * rng.normal(0, 1, n)
    fpr, tpr = roc_curve(y_true, scores)
    auc = auc_trapezoidal(fpr, tpr)
    # Direct Monte Carlo estimate of "P(random positive scores higher than
    # random negative)" to confirm it matches the trapezoidal AUC.
    pos_scores = scores[y_true == 1]
    neg_scores = scores[y_true == 0]
    mc_estimate = np.mean(rng.choice(pos_scores, 5000) > rng.choice(neg_scores, 5000))
    print(f"AUC via trapezoidal ROC integration: {auc:.4f}")
    print(f"AUC via P(random positive > random negative), Monte Carlo: {mc_estimate:.4f}")
    print("-> These should closely agree, confirming AUC's probabilistic meaning.")

    print("\n" + "=" * 70)
    print("CONCEPT #4: bootstrap confidence interval on an AUC difference")
    print("=" * 70)
    scores_b = scores + rng.normal(0, 0.3, n)  # a very similar, barely-different model
    mean_diff, lo, hi = bootstrap_auc_difference(y_true, scores, scores_b, n_boot=300)
    print(f"Mean AUC(A) - AUC(B): {mean_diff:.4f}")
    print(f"95% bootstrap CI: [{lo:.4f}, {hi:.4f}]")
    print(f"Interval excludes 0 (statistically distinguishable)? {not (lo <= 0 <= hi)}")
