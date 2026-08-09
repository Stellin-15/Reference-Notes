"""
WHAT: Four realistic business problems, each solved with THREE genuinely
      different, individually defensible approaches drawn from L01-L08 --
      with an explicit comparison table and a reasoned account of WHY
      each answer is valid under different assumptions/constraints, not
      a single "correct" answer.
WHY:  Principal-level ML work is rarely "which algorithm is best" (L01's
      No Free Lunch theorem says that question is usually malformed) --
      it's "which of several valid approaches fits THIS problem's actual
      constraints (data size, interpretability requirement, latency
      budget, label noise, interaction structure)." This lesson is
      deliberately built around the disagreement between defensible
      answers, since that disagreement is the actual skill being tested
      in a principal-engineer interview or a real architecture review.
LEVEL: Capstone for the Classical ML Theory Notes track -- read after
       L01-L08.
"""

# ============================================================================
# CASE STUDY 1 — CREDIT DEFAULT PREDICTION FOR A CONSUMER LENDER
# ============================================================================
#
# SETUP: 2M historical loans, ~4% default rate, 60 candidate features
# (income, credit bureau data, loan terms, behavioral signals). The model
# will (a) score new applications for approval/denial and (b) must be
# explainable per fair-lending regulation (adverse action notices must
# cite specific reasons for denial).
#
# ------------------------------------------------------------------------
# APPROACH A: Regularized logistic regression (L02) with a curated,
# monotonic feature set
# ------------------------------------------------------------------------
#   WHY IT'S VALID: the regulatory constraint (explainable, auditable
#   adverse-action reasons) is BINDING, not a nice-to-have -- per L02's
#   MAP-estimation framing, logistic regression's coefficients have a
#   direct, defensible interpretation (log-odds contribution per unit of
#   a standardized feature), and monotonic-constraint logistic regression
#   (each coefficient's sign is fixed by domain knowledge, e.g. "higher
#   income can never increase default probability, contractually") is
#   straightforward to enforce and explain to a regulator or a rejected
#   applicant in plain language.
#   COST: leaves real accuracy on the table -- genuine nonlinear
#   interactions (e.g. "high income combined with very high existing debt-to-income
#   is worse than either alone") are invisible to a linear model unless
#   hand-engineered as explicit interaction features first.
#
# ------------------------------------------------------------------------
# APPROACH B: Gradient-boosted trees (L03) with SHAP-based post-hoc
# explanations
# ------------------------------------------------------------------------
#   WHY IT'S VALID: if the actual regulatory bar is "give a reason," not
#   specifically "the model must itself be a linear equation," SHAP
#   values (computed per-prediction on top of the trained ensemble) can
#   satisfy adverse-action requirements in practice at many institutions
#   -- and per L03's bias-reduction argument, boosting captures the
#   genuine feature interactions Approach A structurally cannot,
#   typically producing measurably better AUC/PR-AUC (L07).
#   COST: SHAP explanations are LOCAL approximations of a complex
#   function's behavior near one point, not the literal mechanism by
#   which the model computed its score -- legal/compliance teams
#   sometimes (reasonably) push back on "explained via approximation" vs.
#   Approach A's "explained via the actual coefficient." Whether this
#   cost is acceptable is a genuinely institution-specific legal
#   judgment call, not a purely technical one.
#
# ------------------------------------------------------------------------
# APPROACH C: A two-stage system -- gradient boosting for the actual
# accept/deny decision, PLUS a separate, simpler logistic regression
# fit specifically to explain that decision (a "surrogate model")
# ------------------------------------------------------------------------
#   WHY IT'S VALID: decouples "what makes the best decision" from "what
#   explains the decision" -- accepting that these can legitimately be
#   different models (a common enough production pattern that it has a
#   name: model distillation / surrogate explanation). Can get
#   Approach B's accuracy with an explanation model that's structurally
#   as simple as Approach A's.
#   COST: the surrogate's explanation is, by construction, only an
#   APPROXIMATION of the real model's actual reasoning -- there will be
#   cases where the surrogate's stated "reason for denial" doesn't fully
#   match what actually drove the real model's score, a genuine
#   fidelity gap that has to be measured and disclosed, not assumed away.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Expected AUC | Explainability | Regulatory risk | Eng. cost |
#   |----------|-------------|----------------|------------------|-----------|
#   | A: Logistic + monotonic | Lower (misses interactions) | Highest (exact) | Lowest | Low |
#   | B: GBM + SHAP | Higher | Medium (approximate, local) | Medium (institution-dependent) | Medium |
#   | C: GBM + surrogate | Higher | Medium (fidelity-gap risk) | Medium-high (needs fidelity monitoring) | High |
#   ALL THREE ARE DEFENSIBLE; the deciding factor is the institution's
#   specific legal risk tolerance and existing regulatory relationship,
#   which is NOT a question this lesson (or any ML theory) can answer for
#   you -- flagging that explicitly, rather than picking one, is itself
#   the correct principal-engineer move.


# ============================================================================
# CASE STUDY 2 — REAL-TIME FRAUD SCORING AT 5ms P99 LATENCY BUDGET
# ============================================================================
#
# SETUP: payment fraud scoring, must return a score in <5ms P99 including
# network overhead, extremely imbalanced (0.1% fraud rate), label noise
# is real (some fraud is never caught/labeled; some "fraud" flags are
# later reversed as false chargebacks).
#
# ------------------------------------------------------------------------
# APPROACH A: A single shallow (depth <=6) gradient-boosted ensemble
# ------------------------------------------------------------------------
#   WHY VALID: per L03, a shallow, moderate-round boosted ensemble is
#   typically fast enough at inference (a handful of microseconds per
#   tree, trees are shallow) to comfortably clear a 5ms budget, while
#   still capturing real interactions a linear model would miss --
#   evaluate against Approach C below rather than assuming it's obviously
#   best.
#   COST: still needs periodic retraining discipline as fraud patterns
#   drift (L01's distribution-shift point, not a bias-variance problem
#   at all, and NOT something this lesson's tools alone solve).
#
# ------------------------------------------------------------------------
# APPROACH B: Gaussian Naive Bayes (L05) as a first-pass filter, escalate
# ambiguous cases to a slower downstream model
# ------------------------------------------------------------------------
#   WHY VALID: per L05's Concept #1, Naive Bayes needs very little data
#   per parameter (only per-feature 1D distributions), which matters when
#   the POSITIVE class is genuinely tiny (0.1% of 0.1% after any further
#   segmentation) -- and it's essentially the cheapest possible model to
#   evaluate at inference time (a handful of log-probability sums), which
#   matters if the 5ms budget is extremely tight and shared with several
#   other services in the request path.
#   COST: its independence assumption (L05) will genuinely miss
#   correlated-feature fraud signatures common in real fraud rings
#   (coordinated attacks share MANY correlated signals by design) --
#   defensible ONLY as a fast first-pass triage layer, not as the final
#   decision-maker, which is why this approach is paired with escalation
#   rather than proposed as a standalone system.
#
# ------------------------------------------------------------------------
# APPROACH C: Logistic regression (L02) on a hand-engineered, carefully
# validated feature set
# ------------------------------------------------------------------------
#   WHY VALID: given genuine LABEL NOISE (some "fraud" labels will flip
#   after chargeback disputes resolve), a lower-VARIANCE model (L01) is
#   arguably the more robust choice -- logistic regression's low capacity
#   means it's less prone to confidently memorizing noisy labels than a
#   higher-capacity boosted ensemble would be, at the cost of needing
#   real feature-engineering effort up front (interaction terms hand-
#   built, since the model itself won't discover them).
#   COST: that feature-engineering effort is real, ongoing work as fraud
#   patterns evolve -- unlike Approach A, where the model itself adapts
#   its splits to new interaction patterns during each retrain, Approach
#   C requires a human to notice and hand-encode a new interaction.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Latency | Robustness to label noise | Interaction capture | Ongoing eng. burden |
#   |----------|---------|---------------------------|----------------------|----------------------|
#   | A: shallow GBM | Low-medium | Medium | High (automatic) | Medium (retraining) |
#   | B: NB + escalation | Lowest | Medium | Low (independence assumption) | Low |
#   | C: engineered logistic | Low | Highest (low variance) | Manual only | High (feature eng.) |
#   The genuinely correct choice depends on which of {latency, label-noise
#   robustness, engineering bandwidth} is the tightest actual constraint
#   at this specific company -- again, not resolvable in the abstract.


# ============================================================================
# CASE STUDY 3 — CUSTOMER SEGMENTATION FOR A MARKETING TEAM (UNSUPERVISED)
# ============================================================================
#
# SETUP: 500K customers, 40 behavioral/transactional features, no labels
# -- marketing wants "natural" customer segments for targeted campaigns,
# plus a way to visualize the segments in a stakeholder deck.
#
# ------------------------------------------------------------------------
# APPROACH A: k-means (as a special case of GMM/EM, L05/L06) on
# PCA-reduced features
# ------------------------------------------------------------------------
#   WHY VALID: fast, scales to 500K rows easily, and PCA pre-reduction
#   (L06) both speeds up clustering and mitigates some curse-of-
#   dimensionality distance-concentration effects (L08's Concept #2) on
#   the raw 40-dimensional space.
#   COST: k-means' hard, roughly-equal-size, roughly-spherical-cluster
#   assumption (the EM-degenerate-limit argument from L05's Concept #3)
#   may not match real customer segment shapes/sizes -- a "whale"
#   segment of a few thousand very-high-value customers can get absorbed
#   into a larger, more "average" cluster because k-means doesn't
#   naturally represent unequal cluster sizes well.
#
# ------------------------------------------------------------------------
# APPROACH B: Full-covariance Gaussian Mixture Model (L05), soft
# assignments reported directly to marketing
# ------------------------------------------------------------------------
#   WHY VALID: represents elongated/differently-sized clusters that
#   k-means structurally cannot (L05's Concept #3), and the SOFT
#   assignment probabilities are honestly more representative of reality
#   -- most customers aren't purely "one segment," and reporting gamma_ik
#   (L05) lets marketing target a customer with BOTH of their top-2
#   segment campaigns proportionally, rather than forcing an artificial
#   single label.
#   COST: harder to explain to a non-technical marketing stakeholder
#   ("this customer is 60% Segment 2, 40% Segment 4" is a less intuitive
#   deliverable than a clean single label), and EM's non-convex
#   optimization (L05) needs multiple restarts and more compute than
#   k-means for the same data size.
#
# ------------------------------------------------------------------------
# APPROACH C: Hierarchical clustering (L06) with Ward linkage, cut at
# marketing's desired K after inspecting the dendrogram
# ------------------------------------------------------------------------
#   WHY VALID: lets marketing EXPLORE multiple candidate K values from a
#   single clustering run (cut the dendrogram at different heights)
#   rather than committing to K upfront the way k-means/GMM require --
#   valuable when the "right" number of segments is itself an open
#   business question, not a fixed technical parameter.
#   COST: hierarchical clustering's O(n^2 log n)+ cost (L06) makes it
#   impractical to run directly on 500K rows -- in practice this means
#   clustering a representative SAMPLE (or first reducing via k-means
#   into a smaller number of "micro-clusters," then hierarchically
#   clustering those) rather than the full dataset, introducing its own
#   sampling-fidelity question.
#
# VISUALIZATION NOTE (applies to all three): per L06's Concept #4, the
# stakeholder-deck visualization should use UMAP/t-SNE for the 2D plot
# regardless of which clustering algorithm produced the labels -- PCA's
# top-2 components will likely capture too little of a genuinely 40-
# dimensional behavioral space's variance to visually separate segments
# well, and whichever plot is used, inter-cluster DISTANCE on a t-SNE/
# UMAP plot must be explicitly caveated as not quantitatively meaningful
# when presenting to marketing.


# ============================================================================
# CASE STUDY 4 — PREDICTING EQUIPMENT FAILURE FOR PREDICTIVE MAINTENANCE
# ============================================================================
#
# SETUP: sensor time-series from industrial equipment, failures are rare
# (~50 failures/year across 2,000 machines) and EXPENSIVE to miss (a
# missed failure can mean a multi-day production halt), while a false
# alarm costs a technician a few hours of unnecessary inspection.
#
# ------------------------------------------------------------------------
# APPROACH A: Gradient boosting (L03) trained with an asymmetric
# cost-sensitive loss, threshold tuned via the PR curve (L07)
# ------------------------------------------------------------------------
#   WHY VALID: directly encodes the business asymmetry (missed failure
#   >> false alarm cost) into the OPTIMIZATION itself (via class weights
#   or a custom loss), and L07's PR-curve framing is exactly the right
#   evaluation tool given the extreme imbalance -- pick the threshold
#   that hits a target RECALL (e.g. "catch >=95% of real failures") and
#   accept whatever precision that implies, rather than defaulting to a
#   0.5 threshold that's meaningless under this imbalance and this cost
#   structure.
#   COST: with only ~50 positive examples/year, the model has very
#   little genuine signal to learn from -- high risk of overfitting to
#   coincidental patterns in a small positive set (L01's variance
#   concern, sharpened by how few positives exist regardless of total
#   dataset size).
#
# ------------------------------------------------------------------------
# APPROACH B: Unsupervised anomaly detection (a GMM, L05, fit on NORMAL
# operation only, flagging low-likelihood points) instead of a
# supervised classifier
# ------------------------------------------------------------------------
#   WHY VALID: sidesteps the tiny-positive-class problem entirely by
#   never needing failure labels to train on -- fits a density model of
#   "normal," flags departures from it. Can catch NOVEL failure modes
#   that never appeared in the 50 historical labeled failures (a
#   supervised model, per L01's No Free Lunch framing, can only really
#   be expected to recognize patterns similar to what it was trained on).
#   COST: "statistically unusual" and "about to fail" are NOT the same
#   thing -- this approach will flag legitimately rare-but-safe operating
#   conditions (e.g. an unusual but planned high-load test) as anomalies,
#   producing false alarms that don't correspond to any real cost-benefit
#   calibration the way Approach A's explicit threshold tuning does.
#
# ------------------------------------------------------------------------
# APPROACH C: A hybrid -- unsupervised anomaly score (Approach B) as ONE
# engineered feature fed INTO the supervised gradient-boosting model
# (Approach A)
# ------------------------------------------------------------------------
#   WHY VALID: gets the benefit of both -- the anomaly score gives the
#   supervised model a genuinely novel, differently-structured signal
#   beyond raw sensor readings (this is feature engineering in the
#   L08 sense: manufacturing a new, informative feature rather than
#   relying on the base model to discover the same structure from raw
#   inputs alone), while the final decision is still made by a model
#   directly optimized against the true business cost asymmetry.
#   COST: more moving parts to maintain and monitor (two models instead
#   of one), and the anomaly score's OWN drift (the "normal" distribution
#   it was fit on can itself go stale as equipment ages or operating
#   conditions change seasonally) becomes an additional thing that can
#   silently degrade the whole system if unmonitored.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Handles tiny positive class | Catches novel failure modes | Cost-asymmetry aware | Complexity |
#   |----------|------------------------------|-------------------------------|------------------------|------------|
#   | A: cost-sensitive GBM | Poor (overfitting risk) | No | Yes (built-in) | Low |
#   | B: unsupervised anomaly | Yes (no labels needed) | Yes | No (needs manual calibration) | Medium |
#   | C: hybrid | Yes (anomaly feature helps) | Partial | Yes | High |
#   Given the described cost asymmetry (missed failure is severe), most
#   principal engineers would lean toward C in a mature system and A as a
#   fast v1 -- but that lean, not a hard rule, is exactly the kind of
#   judgment call that should be stated explicitly and revisited as real
#   production data on false-alarm cost accumulates.
"""
This lesson intentionally has no runnable code -- its content IS the
comparative reasoning above. Re-read each case study and, before checking
the comparison table, try writing your own table from memory using only
L01-L08's concepts; the goal is to internalize the REASONING PATTERN
(name the actual constraint, map it to a concept from L01-L08, name the
concrete cost of each approach), not to memorize these four specific
answers.
"""
