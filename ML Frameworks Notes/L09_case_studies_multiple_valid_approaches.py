"""
WHAT: Four realistic ML-framework/production-modeling problems, each
      solved with THREE genuinely different, individually defensible
      approaches drawn from L01-L08 -- with an explicit comparison table
      and reasoning for why each answer is valid under different
      constraints. Distinct from L08's capstone (production-serving
      concerns) -- this lesson is about choosing a MODELING approach
      itself.
WHY:  "sklearn or XGBoost or PyTorch" is exactly as malformed a question
      as everything else in this repo's capstones without knowing data
      size, latency budget, and interpretability needs -- this lesson
      applies Classical ML Theory Notes' No Free Lunch framing to
      concrete framework choices.
LEVEL: Capstone -- read after L01-L08.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L08's concepts.
"""

# ============================================================================
# CASE STUDY 1 — MODELING CHURN PREDICTION FOR A SUBSCRIPTION BUSINESS
# (TABULAR DATA, ~200K ROWS, NEEDS TO BE EXPLAINABLE TO A BUSINESS TEAM)
# ============================================================================
#
# SETUP: predicting which subscribers will churn next month, from ~40
# tabular features (usage metrics, billing history, support tickets);
# the business team wants to understand WHY the model flags a given
# customer, not just get a score.
#
# ------------------------------------------------------------------------
# APPROACH A: Logistic regression with L1 regularization (L01, L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L01-L02, coefficients are DIRECTLY interpretable (a
#   log-odds contribution per feature), and L1's sparsity means the
#   business team sees a SHORT list of the features that actually
#   matter, not all 40 with tiny weights -- the most directly explainable
#   of the three options, with zero post-hoc explanation machinery
#   needed.
#   COST: per Classical ML Theory Notes L02, linear models can't capture
#   genuine feature INTERACTIONS (e.g. "high usage AND recent support
#   tickets" being worse than either alone) without hand-engineering
#   interaction terms explicitly -- likely leaves real predictive
#   accuracy on the table if such interactions exist in churn behavior,
#   which is plausible for this kind of problem.
#
# ------------------------------------------------------------------------
# APPROACH B: XGBoost (L03) with SHAP values (L03) for explanation
# ------------------------------------------------------------------------
#   WHY VALID: per L03, gradient boosting captures feature interactions
#   automatically (no hand-engineering needed) and typically achieves
#   meaningfully higher accuracy than linear models on tabular data of
#   this kind -- SHAP values then provide PER-PREDICTION explanations
#   ("this customer was flagged mainly due to declining usage and a
#   recent billing dispute") that the business team can act on.
#   COST: per Classical ML Theory Notes L09's Case Study 1 discussion,
#   SHAP explanations are LOCAL APPROXIMATIONS of a complex model's
#   behavior, not the literal mechanism -- if the business/compliance
#   context requires "explain the EXACT reason," not "a good
#   approximation of the reason," this is a real, meaningful gap
#   relative to A's exact coefficients.
#
# ------------------------------------------------------------------------
# APPROACH C: A two-stage system -- XGBoost for the actual scoring (best
# accuracy), PLUS a separate, simpler logistic regression trained as a
# surrogate specifically to generate the business-facing explanation
# (L03's production_ml discussion of explainability layers)
# ------------------------------------------------------------------------
#   WHY VALID: gets B's accuracy while giving the business team A's
#   simple, coefficient-based explanation style, IF the surrogate model
#   is a reasonably faithful approximation of the real model's behavior
#   -- decouples "make the best prediction" from "explain the
#   prediction simply," a legitimate, common production pattern.
#   COST: the surrogate's explanation is, by construction, only an
#   approximation of what the REAL (XGBoost) model actually did --
#   there's a genuine FIDELITY GAP to measure and disclose (cases where
#   the surrogate's stated reason doesn't match what actually drove the
#   real model's score), and maintaining two models instead of one is
#   real, ongoing extra engineering overhead.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Expected accuracy | Explanation fidelity | Engineering overhead |
#   |----------|------------------------|----------------------------|----------------------------|
#   | A: L1 logistic regression | Lower (misses interactions) | Highest (exact) | Lowest |
#   | B: XGBoost + SHAP | Higher | Medium (local approximation) | Medium |
#   | C: XGBoost + surrogate explainer | Higher | Medium (fidelity-gap risk, but simpler explanations) | Highest |
#   For most teams, B is the strongest default -- SHAP is well-
#   established and "good approximate explanation with strong accuracy"
#   satisfies most business stakeholders; A remains right if the
#   business's need is genuinely "must be a simple, auditable formula"
#   (e.g. certain regulated contexts); C is a reasonable middle ground
#   when the business team specifically struggles with SHAP's output
#   format and needs simpler coefficient-style explanations instead.


# ============================================================================
# CASE STUDY 2 — DEBUGGING A MODEL THAT PERFORMS WELL IN OFFLINE
# EVALUATION BUT POORLY IN PRODUCTION
# ============================================================================
#
# SETUP: a model scores well on a held-out test set (L01's CV
# discussion) but its real-world production performance is noticeably
# worse -- the team needs to diagnose why.
#
# ------------------------------------------------------------------------
# APPROACH A: Check for TRAINING-SERVING SKEW (L08) -- verify the exact
# same feature computation logic runs in both training and production
# ------------------------------------------------------------------------
#   WHY VALID: per L08, this is one of the MOST common real-world causes
#   of exactly this symptom -- a feature computed slightly differently
#   at training time (e.g. using a batch job with access to future data)
#   versus serving time (a real-time computation with only past data
#   available) can silently make offline evaluation look far better than
#   production ever could genuinely achieve, since the offline eval was
#   evaluating a slightly different, easier problem.
#   COST: skew-checking requires actually tracing through BOTH the
#   training and serving feature pipelines carefully, which can be
#   genuinely tedious for a complex feature set -- and if skew ISN'T
#   the cause, this investigation, while a reasonable first check,
#   doesn't directly point toward the actual root cause.
#
# ------------------------------------------------------------------------
# APPROACH B: Check for DISTRIBUTION SHIFT (Classical ML Theory Notes
# L01) -- compare the production input data's distribution against the
# training data's distribution
# ------------------------------------------------------------------------
#   WHY VALID: per Classical ML Theory Notes L01, if production data
#   genuinely comes from a DIFFERENT distribution than training data
#   (a new user segment, a seasonal shift, a changed upstream data
#   source), NO amount of regularization or model tuning fixes this --
#   it's a fundamentally different problem than overfitting, and
#   confirming/ruling this out early avoids wasting time on
#   regularization-style fixes that wouldn't address a genuine shift.
#   COST: distribution comparison (e.g. via PSI/KS tests, MLOps Notes
#   L06) requires a genuine baseline of what "normal" training-time
#   distribution looked like, saved and comparable -- if that baseline
#   wasn't captured at training time, reconstructing it after the fact
#   is harder, and even a confirmed shift doesn't by itself tell you
#   WHAT changed or how to fix it, just that something did.
#
# ------------------------------------------------------------------------
# APPROACH C: Check for LABEL LEAKAGE in the offline evaluation itself
# (a feature that encoded post-outcome information, making offline
# performance look better than it can ever be in a genuinely fair,
# real-time production setting)
# ------------------------------------------------------------------------
#   WHY VALID: per L01's cross-validation discussion and Classical ML
#   Theory Notes L01's production-use-case discussion, this is a THIRD,
#   distinct possible cause with the SAME symptom -- a feature that's
#   only knowable AFTER the outcome occurred (e.g. "number of support
#   tickets in the 7 days before churning," accidentally including
#   information from the churn event itself) inflates offline metrics
#   in a way that was NEVER achievable in real-time production, since
#   that feature genuinely doesn't exist yet at prediction time in
#   production.
#   COST: leakage can be genuinely subtle and hard to spot by inspection
#   alone -- requires carefully tracing each feature's TIMING (is this
#   value truly knowable at the moment a real-time prediction would be
#   made) rather than just its logical definition, a meticulous, easy-
#   to-rush process under time pressure to "just fix the bug."
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | What it catches | What it misses | Investigation effort |
#   |----------|----------------------|---------------------|----------------------------|
#   | A: training-serving skew check | Feature-computation mismatches | Shift, leakage | Medium |
#   | B: distribution shift check | Genuine population changes | Skew, leakage | Medium |
#   | C: label leakage check | Post-outcome feature contamination | Skew, shift | High (meticulous) |
#   All three are genuinely DIFFERENT, common root causes producing the
#   IDENTICAL symptom -- the correct practice is to check ALL THREE
#   systematically (not stop at the first plausible-sounding one),
#   since assuming the cause without verification risks "fixing" the
#   wrong problem while the real one persists.


# ============================================================================
# CASE STUDY 3 — CHOOSING BETWEEN SCIKIT-LEARN AND PYTORCH FOR A
# STRUCTURED-DATA CLASSIFICATION PROBLEM
# ============================================================================
#
# SETUP: a fraud-classification problem on structured, tabular
# transaction data -- no images, no text, no sequences, just ~60 numeric/
# categorical features.
#
# ------------------------------------------------------------------------
# APPROACH A: scikit-learn's gradient boosting or XGBoost (L01-L03)
# ------------------------------------------------------------------------
#   WHY VALID: per Deep Learning Theory Notes L08's Case Study 4
#   reasoning, tabular data with no inherent spatial/sequential structure
#   is exactly the regime where gradient-boosted trees empirically and
#   consistently match or outperform neural networks, need far less
#   hyperparameter tuning, and train dramatically faster -- the
#   architecturally and empirically justified default for this problem
#   shape.
#   COST: doesn't natively support incremental/online learning as
#   cleanly as some neural approaches, and if the feature set later
#   grows to include less-structured data (raw text notes, images of
#   receipts), trees handle that poorly, requiring a real architecture
#   change at that point.
#
# ------------------------------------------------------------------------
# APPROACH B: A PyTorch MLP (L04-L05)
# ------------------------------------------------------------------------
#   WHY VALID: per Deep Learning Theory Notes L01's backprop foundations,
#   a plain MLP imposes NO structural inductive bias on the tabular
#   features (unlike a CNN's spatial bias, which would be actively
#   wrong here) -- an architecturally honest, unbiased default IF the
#   team specifically wants to stay within a unified PyTorch-based
#   pipeline (e.g. for easier future integration with other neural
#   components).
#   COST: per Classical ML Theory Notes L01's No Free Lunch framing and
#   the empirical track record, MLPs are well-documented to typically
#   underperform gradient boosting specifically on tabular data of this
#   kind, and require meaningfully more hyperparameter tuning
#   (architecture depth/width, learning rate, regularization) to reach
#   comparable performance -- more effort for likely worse results here.
#
# ------------------------------------------------------------------------
# APPROACH C: A tabular-specific deep learning architecture (e.g.
# feature-wise attention/TabNet-style models, mentioned in Deep Learning
# Theory Notes L08's Case Study 4 as an emerging option)
# ------------------------------------------------------------------------
#   WHY VALID: per Deep Learning Theory Notes L08's Case Study 4,
#   attention between features can explicitly model feature
#   INTERACTIONS in a way a plain MLP doesn't naturally do well,
#   narrowing some of B's accuracy gap versus gradient boosting while
#   still being a neural approach.
#   COST: per that same case study, this is a genuinely newer, less
#   battle-tested approach for tabular data than gradient boosting, with
#   real risk of adding substantial architectural/training complexity
#   without a correspondingly reliable accuracy win -- appropriate to
#   test empirically, not to assume superior by analogy to attention's
#   well-established wins in vision/language.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Expected accuracy (empirical track record) | Tuning effort | Fits future non-tabular feature additions |
#   |----------|--------------------------------------------------|--------------------|---------------------------------------------------|
#   | A: gradient boosting | Highest, typically | Lowest | Poorly |
#   | B: PyTorch MLP | Lower, typically | Highest | Better (neural pipeline) |
#   | C: tabular attention architecture | Emerging, uncertain | High | Better (neural pipeline) |
#   A is the strongest empirically-grounded default for this problem
#   shape specifically -- choosing B or C should be justified by a
#   SPECIFIC reason beyond "we prefer neural networks" (e.g. genuine
#   plans to fuse this with other neural components, or a confirmed
#   empirical win from C on this actual dataset), not chosen by default.


# ============================================================================
# CASE STUDY 4 — HANDLING CLASS IMBALANCE IN A RARE-EVENT PREDICTION
# PROBLEM (0.3% POSITIVE RATE)
# ============================================================================
#
# SETUP: predicting a rare equipment-failure event (0.3% positive rate)
# from sensor data -- standard model training on the raw imbalanced
# data produces a model that essentially always predicts "no failure."
#
# ------------------------------------------------------------------------
# APPROACH A: Resample the training data -- oversample the minority
# class (e.g. SMOTE, L02) or undersample the majority class
# ------------------------------------------------------------------------
#   WHY VALID: per L02, this directly addresses the training-time
#   symptom -- rebalancing what the model SEES during training forces
#   it to actually learn to distinguish the minority class rather than
#   trivially predicting the majority class for a low apparent loss.
#   COST: per L02, SMOTE-style synthetic oversampling generates
#   synthetic minority examples via interpolation, which can produce
#   unrealistic synthetic points in regions of feature space that don't
#   correspond to any REAL failure pattern, especially in high
#   dimensions -- and undersampling the majority class discards real
#   data, potentially losing genuine information about what "normal"
#   looks like.
#
# ------------------------------------------------------------------------
# APPROACH B: Keep the data as-is, but use CLASS WEIGHTS in the loss
# function (available in sklearn, XGBoost, and PyTorch alike, L01-L05)
# to penalize minority-class errors more heavily
# ------------------------------------------------------------------------
#   WHY VALID: achieves a similar effect to A (forcing the model to
#   attend to the minority class) WITHOUT altering the actual training
#   data distribution at all -- no synthetic data, no discarded real
#   data, just a reweighted objective, generally the lower-risk, more
#   directly interpretable of the two rebalancing mechanisms.
#   COST: doesn't address any UNDERLYING feature-space sparsity for the
#   minority class -- if there are genuinely too few real examples of
#   the rare event to characterize its feature-space pattern well at
#   all, reweighting the loss doesn't manufacture information the data
#   doesn't contain; it only changes how much the model is penalized
#   for getting the (still-sparse) minority examples wrong.
#
# ------------------------------------------------------------------------
# APPROACH C: Don't rebalance the DATA or LOSS at all -- keep training
# on the natural distribution, but choose the DECISION THRESHOLD
# post-hoc based on the business's actual precision/recall tradeoff
# (Classical ML Theory Notes L07), using the model's raw, well-
# calibrated probability output directly
# ------------------------------------------------------------------------
#   WHY VALID: per Classical ML Theory Notes L07, a model trained on the
#   TRUE distribution (not artificially rebalanced) tends to produce
#   better-CALIBRATED probability estimates than one trained on
#   artificially resampled data -- if the actual downstream need is a
#   well-calibrated failure PROBABILITY (e.g. to feed a cost-based
#   maintenance-scheduling decision), this preserves that property that
#   A/B's rebalancing can distort, and threshold selection directly
#   targets the real business tradeoff rather than an intermediate proxy.
#   COST: if the base rate is severe enough (0.3%, as stated), the model
#   may still struggle to learn the minority class's pattern well AT ALL
#   from natural-distribution training alone, regardless of threshold
#   choice after the fact -- threshold tuning can't manufacture
#   predictive signal the model never learned in the first place; it
#   only chooses where along an ALREADY-LEARNED tradeoff curve to
#   operate.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Preserves real data distribution | Preserves probability calibration | Addresses genuine minority-class sparsity |
#   |----------|----------------------------------------|------------------------------------------|--------------------------------------------------|
#   | A: resampling (SMOTE/undersample) | No | No (distorted) | Partially (synthetic data risk) |
#   | B: class weighting | Yes | Partially better than A | Partially |
#   | C: natural training + threshold tuning | Yes | Best | Not directly (needs adequate real data) |
#   If calibrated probabilities feed a downstream cost-based decision
#   (a common real production need), C is the strongest default; B is a
#   reasonable middle ground when the model genuinely fails to learn
#   ANYTHING about the minority class under natural training; A is
#   worth trying specifically when B/C still underperform and there's
#   reason to believe synthetic examples would plausibly resemble real
#   failure patterns.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
