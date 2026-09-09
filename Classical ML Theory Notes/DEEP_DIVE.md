# Classical ML Theory — Principal Engineer Deep Dive

Companion to L01-L10. Narrative depth, then a comprehensive common-to-
uncommon reference bridging theory to production ML engineering practice.


## Bias-Variance in Production, Not Just Theory

**Beyond the lesson**: The bias-variance decomposition is usually taught
as pure math (see L01), but the PRODUCTION consequence is what actually
matters day to day: a high-bias (underfit) model fails consistently and
predictably on both train and test data — genuinely easy to diagnose. A
high-variance (overfit) model can look GREAT in offline evaluation
(cross-validation on historical data) and still fail in production if the
production data distribution shifts even slightly from what it memorized
— this is exactly why "great CV score, bad production performance" is
one of the most common real ML-engineering incidents, and why monitoring
LIVE prediction distributions (not just re-checking the offline metric
periodically) is a genuinely necessary production practice, not paranoia.

**Interview Q&A**:
- *Q: A model has 99% training accuracy and 65% validation accuracy. What's your first hypothesis and what do you check?* A: Classic high-variance overfitting — check if regularization strength is too low, if the model is too complex relative to the dataset size (a deep tree/many features on a small dataset), or if there's DATA LEAKAGE between train/validation splits (a subtler cause that mimics overfitting's symptoms but has a completely different fix — split correctness, not model complexity).


## Why Gradient Boosting Still Wins on Tabular Data

**Beyond the lesson**: Despite deep learning's dominance in vision/NLP,
gradient-boosted trees (XGBoost/LightGBM/CatBoost) remain the practical
default for structured/tabular business data (fraud detection, churn
prediction, credit scoring) at most companies — and the REASON is worth
knowing precisely, not just accepting as folklore: tabular data typically
has heterogeneous feature types, meaningful missing-value patterns, and
relatively few training examples compared to image/text datasets — trees
naturally handle mixed feature types and missingness without extensive
preprocessing, and don't need the massive data volumes deep learning
architectures are designed to exploit. Boosting's actual mechanism —
each new tree fits the RESIDUAL error of the ensemble so far, formalized
as gradient descent in FUNCTION space rather than parameter space — gives
a principled way to keep reducing bias iteratively while boosting's
learning-rate/shrinkage hyperparameter controls the variance tradeoff explicitly.

**Interview Q&A**:
- *Q: When would you reach for a neural network over XGBoost for a tabular business problem?* A: When there's genuinely massive data volume (millions+ rows), when features have meaningful SEQUENTIAL/temporal structure a tree can't naturally exploit (better handled by recurrent/attention architectures), or when you need to jointly learn from tabular data alongside images/text in one model — for a "clean" tabular problem with moderate data, XGBoost remains the pragmatic default most practitioners reach for first.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Model evaluation beyond accuracy
- **Precision/Recall/F1, and WHY accuracy fails under imbalance** — a
  99%-accurate fraud model that just predicts "not fraud" always is
  useless; precision-recall tradeoffs (and the PR-AUC curve specifically,
  more informative than ROC-AUC under severe class imbalance) are the
  real production evaluation standard for imbalanced problems.
- **Calibration** — does a model's predicted probability of 0.7 actually
  correspond to a 70% real-world frequency? A model can have great
  discrimination (correctly RANKING positive vs negative cases) while
  being poorly CALIBRATED (its probability outputs are systematically
  over/under-confident) — Platt scaling and isotonic regression are the
  standard post-hoc calibration fixes, genuinely necessary whenever a
  downstream system actually uses the probability VALUE (not just a threshold), e.g. risk-based pricing.

### Feature engineering & selection in practice
- **Mutual information vs correlation** — correlation only captures
  LINEAR relationships; mutual information captures ANY statistical
  dependency (including non-linear ones) — a feature with zero linear
  correlation to the target can still be highly predictive, and
  correlation-only feature selection will silently discard it.
- **SHAP values** — the dominant modern approach for model
  explainability, grounded in cooperative game theory (Shapley values) —
  attributes each feature's CONTRIBUTION to a specific prediction in a
  mathematically principled, consistent way, distinct from simpler (and
  less rigorous) feature-importance metrics like tree split counts.

### Classical algorithms still genuinely used in production
- **Logistic regression** — still the right default for many problems
  needing genuine interpretability/regulatory explainability (credit
  scoring, insurance underwriting) where "why did the model decide this"
  needs a simple, auditable answer a black-box model can't provide as cleanly.
- **k-means & hierarchical clustering** — still the practical default for
  customer segmentation/exploratory analysis, despite deep-learning-based
  clustering approaches existing — simplicity and interpretability of
  cluster centers usually wins for business-facing segmentation work.
- **Isolation Forest / One-Class SVM** — classical, still-competitive
  anomaly-detection algorithms, often outperforming more complex
  approaches for tabular anomaly detection specifically because anomalies
  are (by definition) rare — deep learning's data-hunger works against it here.


## NICHE BUT REAL

- **Concept drift vs data drift, precisely distinguished** — data drift
  is the INPUT distribution changing (customers' ages shifting over time);
  concept drift is the RELATIONSHIP between inputs and the target changing
  (the same customer profile that predicted "will churn" a year ago no
  longer does, because market conditions changed) — the fix for the first
  is often just monitoring; the fix for the second REQUIRES retraining,
  since the model's learned mapping is now genuinely wrong, not just stale.
- **The curse of dimensionality, quantified** — as feature count grows,
  the volume of the feature space grows exponentially, meaning any fixed
  amount of training data becomes exponentially SPARSER relative to that
  space — this is the actual mathematical reason "just add more features"
  degrades model performance past a point, not merely a vague intuition.
- **Weak supervision & programmatic labeling** — using heuristic rules/
  existing models to generate NOISY labels at scale (Snorkel-style
  frameworks) when hand-labeling enough data is prohibitively expensive —
  a real, increasingly common production technique bridging classical
  supervised learning theory with the practical reality of limited labeled data.
- **No Free Lunch theorem, applied** — no single algorithm dominates
  across ALL possible problems — the practical, production consequence
  is that "just try XGBoost, logistic regression, AND a simple baseline,
  compare on YOUR actual data" beats assuming any algorithm is universally best based on reputation alone.
