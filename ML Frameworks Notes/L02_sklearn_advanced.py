# ============================================================
# L02: Advanced Scikit-learn
# ============================================================
# WHAT: Deep-dive into linear models, tree ensembles, feature
#       importance, gradient boosting, ensemble methods,
#       hyperparameter tuning, imbalanced-class strategies,
#       probability calibration, and custom transformers.
# WHY:  The fundamentals get you a working model. Advanced
#       sklearn gets you a competitive, production-worthy one:
#       correct regularization, honest importances, tuned
#       hyperparameters, calibrated probabilities, and a
#       pipeline that handles edge cases at serving time.
# LEVEL: Intermediate
# ============================================================
"""
CONCEPT OVERVIEW:
    sklearn's advanced features compose cleanly with the
    Pipeline/ColumnTransformer system from L01. Each section
    here adds one more knob that makes the difference between
    a proof-of-concept and a model you'd trust in production:
    L1/L2 regularization prevents overfitting; permutation
    importance gives honest feature rankings; calibration
    makes predicted probabilities meaningful; and custom
    transformers let you encode domain logic that fits into
    the same pipeline API.

PRODUCTION USE CASE:
    Stacked ensemble for fraud detection: LR + RF + LightGBM
    as base models feed into a LogisticRegression meta-learner.
    SMOTE is applied inside imblearn Pipeline (training folds
    only). Final scores are probability-calibrated. Full
    evaluation: ROC-AUC, PR-AUC, confusion matrix.

COMMON MISTAKES:
    1. Confusing C and alpha: C=1/lambda (high C = less reg);
       alpha=lambda (high alpha = more reg). They're inverses.
    2. Using sklearn Pipeline with SMOTE — it silently leaks
       synthetic samples into validation folds. Use imblearn
       Pipeline instead.
    3. Trusting feature_importances_ from RF on mixed-cardinality
       data — it's biased toward high-cardinality features.
       Use permutation_importance or SHAP.
    4. Calibrating probabilities on the same fold used for
       training — always hold out a calibration set.
    5. GridSearch over a huge grid instead of RandomizedSearch
       with sensible distributions — random sampling covers
       the space better per unit compute.
"""

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer

# --- Linear Models ---
from sklearn.linear_model import (
    LogisticRegression, Ridge, Lasso, ElasticNet, SGDClassifier,
)

# --- Tree Models ---
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import (
    RandomForestClassifier, ExtraTreesClassifier,
    GradientBoostingClassifier, HistGradientBoostingClassifier,
    VotingClassifier, StackingClassifier, BaggingClassifier,
)

# --- Feature Importance ---
from sklearn.inspection import permutation_importance

# --- Tuning ---
from sklearn.model_selection import (
    GridSearchCV, RandomizedSearchCV, StratifiedKFold,
    cross_val_score,
)

# --- Calibration ---
from sklearn.calibration import CalibratedClassifierCV, calibration_curve

# --- Base classes for custom transformers ---
from sklearn.base import BaseEstimator, TransformerMixin

# --- Metrics ---
from sklearn.metrics import roc_auc_score, average_precision_score

# ============================================================
# SECTION 1: Linear Models — Regularization Explained
# ============================================================
# Regularization adds a penalty to large coefficients,
# reducing overfitting by discouraging the model from relying
# too heavily on any single feature.
#
# LogisticRegression:
#   C = 1 / lambda (INVERSE regularization strength)
#   C=0.001 → very strong regularization → simpler model
#   C=100   → very weak regularization  → can overfit
#   Default C=1.0 is a reasonable starting point.
#
# solver choices:
#   'lbfgs'     — default, limited-memory BFGS. Good for small-
#                 medium datasets, L2 only, numerically stable.
#   'saga'      — stochastic average gradient amended. Scales
#                 to large datasets, supports L1 + ElasticNet.
#   'liblinear' — good for high-dimensional sparse data (text).
#
# class_weight='balanced': automatically sets weights inversely
# proportional to class frequencies. Equivalent to upsampling
# the minority class. Always use for imbalanced classification.

lr_model = LogisticRegression(
    C=1.0,                    # moderate regularization
    solver='lbfgs',
    max_iter=1000,            # increase if convergence warning
    class_weight='balanced',
    random_state=42,
    n_jobs=-1,
)

# SGDClassifier: logistic regression trained with stochastic
# gradient descent. Use for datasets that don't fit in memory
# (partial_fit enables online learning). loss='log_loss' gives
# the same model as LogisticRegression.
sgd_model = SGDClassifier(
    loss='log_loss',   # logistic regression objective
    penalty='l2',      # L2 regularization
    alpha=0.0001,      # regularization strength (note: alpha, not C!)
    max_iter=1000,
    tol=1e-3,
    class_weight='balanced',
    random_state=42,
)

# Ridge: L2 regularization for regression. Shrinks coefficients
# toward zero but rarely to exactly zero. alpha=regularization.
ridge = Ridge(alpha=1.0)

# Lasso: L1 regularization for regression. Drives some
# coefficients to EXACTLY zero → sparse model → implicit
# feature selection. Useful when you believe few features matter.
lasso = Lasso(alpha=0.1, max_iter=5000)

# ElasticNet: L1 + L2 combined. l1_ratio=1.0 is pure Lasso,
# l1_ratio=0.0 is pure Ridge. Mix is useful when groups of
# correlated features exist (Lasso picks one; EN picks all).
enet = ElasticNet(alpha=0.1, l1_ratio=0.5)

# ============================================================
# SECTION 2: Tree Models — Preventing Overfitting
# ============================================================
# A single decision tree will perfectly memorize training data
# (zero training error) unless you constrain it. Key controls:
#
#   max_depth: deepest path from root to leaf.
#     - None = fully grown (overfits).
#     - 3-10 typical. Start at 5, tune from there.
#     - Most impactful hyperparameter for single trees.
#
#   min_samples_leaf: minimum samples required in each leaf.
#     - Prevents tiny leaves that memorize one or two points.
#     - Higher = more regularization.
#     - min_samples_leaf=20 is a safe default.
#
#   class_weight='balanced': same as LR — upweights minority.

single_tree = DecisionTreeClassifier(
    max_depth=5,
    min_samples_leaf=20,
    class_weight='balanced',
    random_state=42,
)

# RandomForestClassifier: bagging (bootstrap aggregating) +
# random feature subsets at each split.
# Why it reduces variance:
#   - Each tree trained on a bootstrapped (resampled) dataset.
#   - Each split considers only sqrt(n_features) features.
#   - Trees are decorrelated → averaging reduces variance.
#
# max_features='sqrt': standard for classification.
# n_jobs=-1: train all trees in parallel on all CPU cores.
# n_estimators=200: more trees = lower variance. Returns diminish
#   after ~200; stop earlier if compute is constrained.

rf = RandomForestClassifier(
    n_estimators=200,
    max_depth=None,       # let trees grow deep; RF controls via ensemble
    max_features='sqrt',  # sqrt(n_features) per split
    min_samples_leaf=5,
    class_weight='balanced',
    n_jobs=-1,
    random_state=42,
)

# ExtraTreesClassifier: like RF but splits are randomly chosen
# (not optimized). Faster training, lower variance than RF, but
# potentially higher bias. Often comparable accuracy with better speed.
et = ExtraTreesClassifier(
    n_estimators=200,
    max_features='sqrt',
    class_weight='balanced',
    n_jobs=-1,
    random_state=42,
)

# ============================================================
# SECTION 3: Feature Importance — Which Measure to Trust
# ============================================================
# model.feature_importances_ (MDI — Mean Decrease Impurity):
#   Measures total impurity reduction from splits on each feature.
#   BIAS: high-cardinality features (many unique values) get
#   artificially high scores because there are more split points.
#   Continuous features are also favored over binary ones.
#
# permutation_importance (better):
#   Shuffle one feature at a time on VALIDATION data.
#   Measure accuracy drop. No cardinality bias because we're
#   measuring actual prediction degradation.
#   Slower but honest. Always validate on held-out set.
#
# SHAP (most reliable, see L08):
#   Game-theory-based attribution. Consistent, locally accurate.
#   Handles correlations. Required for regulated industries.

def get_feature_importance(model, X_val, y_val, feature_names):
    """Compare MDI vs permutation importance."""
    # MDI: fast but biased
    mdi = dict(zip(feature_names, model.feature_importances_))

    # Permutation: slower but honest — uses validation data
    perm = permutation_importance(
        model, X_val, y_val,
        n_repeats=10,        # shuffle each feature 10 times, average
        random_state=42,
        scoring='roc_auc',
        n_jobs=-1,
    )
    perm_scores = dict(zip(feature_names, perm.importances_mean))

    return mdi, perm_scores

# ============================================================
# SECTION 4: Gradient Boosting
# ============================================================
# Gradient boosting: build trees sequentially. Each tree fits the
# RESIDUAL (negative gradient of loss) from all previous trees.
# Unlike bagging (parallel, reduces variance), boosting reduces
# bias — it corrects the mistakes of the previous ensemble.
#
# GradientBoostingClassifier: the original sklearn implementation.
# Slow because it's pure Python and fits trees serially.
# Use only as a reference baseline.

gbc = GradientBoostingClassifier(
    n_estimators=100,
    max_depth=3,
    learning_rate=0.1,
    subsample=0.8,
    random_state=42,
)

# HistGradientBoostingClassifier: sklearn's fast implementation.
# Uses histogram-based split finding (same idea as LightGBM).
# Handles missing values natively — no imputer needed.
# 10-100x faster than GradientBoostingClassifier.
# For production at scale, prefer XGBoost/LightGBM (see L03).

hgbc = HistGradientBoostingClassifier(
    max_iter=300,
    max_depth=6,
    learning_rate=0.05,
    min_samples_leaf=20,
    l2_regularization=0.1,
    random_state=42,
)

# ============================================================
# SECTION 5: Ensemble Methods
# ============================================================
# Ensembling combines multiple base models to reduce variance
# (averaging diverse predictions) or bias (stacking).

# VotingClassifier: combine predictions via majority vote (hard)
# or average predicted probabilities (soft). Soft voting is
# generally better when models are well-calibrated.
def build_voting_ensemble(lr, rf, hgbc):
    return VotingClassifier(
        estimators=[('lr', lr), ('rf', rf), ('hgbc', hgbc)],
        voting='soft',   # average probabilities; requires predict_proba
        n_jobs=-1,
    )

# StackingClassifier: train base models (level-0) with CV,
# use their out-of-fold predictions as features for the
# meta-learner (level-1). More powerful than voting; the
# meta-learner learns which base model to trust per region.
# passthrough=True: also give the original features to meta-learner.
def build_stacking_ensemble(lr, rf, hgbc):
    return StackingClassifier(
        estimators=[('lr', lr), ('rf', rf), ('hgbc', hgbc)],
        final_estimator=LogisticRegression(C=0.1, max_iter=500),
        cv=StratifiedKFold(5, shuffle=True, random_state=42),
        passthrough=False,  # True to also pass raw features to meta-learner
        n_jobs=-1,
    )

# BaggingClassifier: wraps ANY estimator with bootstrap sampling.
# Useful for making high-variance estimators more stable.
bagging_tree = BaggingClassifier(
    estimator=DecisionTreeClassifier(max_depth=5),
    n_estimators=50,
    max_samples=0.8,
    max_features=0.8,
    n_jobs=-1,
    random_state=42,
)

# ============================================================
# SECTION 6: Hyperparameter Tuning
# ============================================================
# Grid search: exhaustive. Evaluates every combination in the
# grid. Good for small search spaces (<100 combinations).
# Double underscore notation: 'stepname__param' accesses the
# parameter of a named step inside a Pipeline.

def grid_search_demo(pipeline, X_train, y_train):
    param_grid = {
        'classifier__C':         [0.01, 0.1, 1, 10, 100],
        'classifier__solver':    ['lbfgs', 'saga'],
        # preprocessor step params follow the same pattern:
        # 'preprocessor__num__scaler__with_mean': [True, False],
    }
    gs = GridSearchCV(
        pipeline,
        param_grid,
        cv=StratifiedKFold(5, shuffle=True, random_state=42),
        scoring='roc_auc',
        n_jobs=-1,
        refit=True,   # refit best model on all training data
        verbose=1,
    )
    gs.fit(X_train, y_train)
    print(f"Best params: {gs.best_params_}")
    print(f"Best CV ROC-AUC: {gs.best_score_:.4f}")
    return gs.best_estimator_

# RandomizedSearchCV: sample n_iter random combinations from
# distributions. Covers hyperparameter space better than grid
# search per unit compute — many params have large "don't care"
# regions that grid search wastes evaluations on.
from scipy.stats import loguniform, randint

def random_search_demo(pipeline, X_train, y_train):
    param_dist = {
        'classifier__C':            loguniform(1e-3, 1e2),
        'classifier__max_iter':     randint(200, 2000),
    }
    rs = RandomizedSearchCV(
        pipeline,
        param_dist,
        n_iter=50,    # evaluate 50 random combinations
        cv=StratifiedKFold(5, shuffle=True, random_state=42),
        scoring='roc_auc',
        n_jobs=-1,
        refit=True,
        random_state=42,
        verbose=1,
    )
    rs.fit(X_train, y_train)
    print(f"Best params: {rs.best_params_}")
    return rs.best_estimator_

# HalvingGridSearchCV (successive halving):
# Start with all combinations on a small budget (few samples).
# Eliminate the bottom half. Double the budget. Repeat.
# Finds good configs faster than full GridSearch.
# from sklearn.model_selection import HalvingGridSearchCV

# Optuna (best for large search spaces):
# Bayesian optimization using Tree Parzen Estimators.
# Prunes bad trials early (like early stopping for tuning).
# Framework-agnostic. Define a trial object, return the metric.
# See: https://optuna.readthedocs.io/

# ============================================================
# SECTION 7: Handling Imbalanced Classes
# ============================================================
# Fraud, churn, disease detection: positive rate often < 5%.
# Accuracy is useless — a classifier that predicts "no fraud"
# 100% of the time gets 99% accuracy. Use PR-AUC or ROC-AUC.
#
# Strategy options (in order of simplicity → power):
#   1. class_weight='balanced' in the model — free, always try first.
#   2. SMOTE: generate synthetic minority samples via interpolation
#      between real minority examples.
#   3. RandomUnderSampler: remove majority samples randomly.
#   4. SMOTETomek: SMOTE + remove borderline samples (Tomek links).
#
# CRITICAL: resampling must only happen on TRAINING folds,
# never on validation folds. Sklearn Pipeline does NOT support
# resampling steps (it doesn't pass through fit/resample).
# Use imbalanced-learn (imblearn) Pipeline instead.

# from imblearn.over_sampling import SMOTE, SMOTETomek
# from imblearn.pipeline import Pipeline as ImbPipeline
#
# imblearn_pipeline = ImbPipeline([
#     ('preprocessor', preprocessor),   # same ColumnTransformer as before
#     ('smote', SMOTE(sampling_strategy=0.5, random_state=42)),
#     ('classifier', rf),
# ])
# cross_val_score(imblearn_pipeline, X_train, y_train, cv=StratifiedKFold(5))

# ============================================================
# SECTION 8: Probability Calibration
# ============================================================
# Many models output scores that are NOT calibrated probabilities:
#   SVM, GBM, RF all produce overconfident or underconfident scores.
# Calibration: if model says 0.7 probability, it should be correct
# 70% of the time. Check this with calibration_curve().
#
# CalibratedClassifierCV methods:
#   'sigmoid' (Platt scaling): fits a logistic function over scores.
#     Best for models that are well-ranked but poorly scaled (SVM).
#   'isotonic': fits a monotone step function. More flexible but
#     requires more data (>1000 calibration examples). For RF/GBM.
#
# cv parameter:
#   cv=5: fit base model in 4 folds, calibrate on 5th, rotate.
#   cv='prefit': model already fit; pass a separate calibration set.
#
# When calibration matters:
#   - Pricing: 70% churn prob → 30% discount offer worth it.
#   - Medical: 80% cancer prob → biopsied, not 60%.
#   - Credit scoring: scores must be monotonically meaningful.

def calibrate_model(base_model, X_train, y_train):
    calibrated = CalibratedClassifierCV(
        estimator=base_model,
        cv=5,              # internal cross-val for calibration
        method='isotonic', # isotonic for ensemble models
    )
    calibrated.fit(X_train, y_train)
    return calibrated

def plot_calibration_check(model, X_test, y_test, n_bins=10):
    """
    Returns fraction_of_positives and mean_predicted_value.
    Perfect calibration: these two arrays should be equal.
    Plot: x=mean_predicted_value, y=fraction_of_positives.
    Diagonal line = perfect calibration.
    """
    y_prob = model.predict_proba(X_test)[:, 1]
    fraction_of_positives, mean_predicted_value = calibration_curve(
        y_test, y_prob, n_bins=n_bins,
    )
    return fraction_of_positives, mean_predicted_value

# ============================================================
# SECTION 9: Custom Transformers
# ============================================================
# Any domain logic that doesn't exist in sklearn can be
# wrapped in a transformer that plugs into Pipeline and
# ColumnTransformer without modification.
#
# Inherit from BOTH BaseEstimator AND TransformerMixin:
#   BaseEstimator: provides get_params() and set_params()
#     needed for GridSearch and clone().
#   TransformerMixin: provides fit_transform() for free.
#
# Rules:
#   fit(X, y=None) must return self.
#   transform(X) must return an array of the same n_samples.
#   fit() must not modify X (no in-place changes).

class LogTransformer(BaseEstimator, TransformerMixin):
    """
    Apply log1p to selected features. Useful for right-skewed
    distributions (income, revenue) to make them more Gaussian.
    log1p(x) = log(1 + x) handles x=0 gracefully.
    """
    def fit(self, X, y=None):
        # Nothing to learn from data — stateless transformer.
        return self

    def transform(self, X):
        return np.log1p(np.abs(X))  # abs to handle negative edge cases

class ClipTransformer(BaseEstimator, TransformerMixin):
    """
    Clip feature values to [lower, upper] quantile range.
    Learned from training data so the same bounds apply
    at serving time.
    """
    def __init__(self, lower_q=0.01, upper_q=0.99):
        self.lower_q = lower_q
        self.upper_q = upper_q

    def fit(self, X, y=None):
        # Learn percentiles from training data
        self.lower_ = np.percentile(X, self.lower_q * 100, axis=0)
        self.upper_ = np.percentile(X, self.upper_q * 100, axis=0)
        return self

    def transform(self, X):
        return np.clip(X, self.lower_, self.upper_)

# Usage in pipeline:
# Pipeline([
#     ('clip', ClipTransformer(lower_q=0.01, upper_q=0.99)),
#     ('log', LogTransformer()),
#     ('scale', StandardScaler()),
#     ('model', LogisticRegression()),
# ])

# ============================================================
# SECTION 10: Full Example — Stacked Fraud Ensemble
# ============================================================

def build_fraud_pipeline(numeric_cols, cat_cols):
    """
    Full stacked ensemble for fraud detection.
    Base models: LR + RF + HistGBM.
    Meta-learner: LogisticRegression.
    Calibrated probabilities.
    """
    # Preprocessor
    num_pipe = Pipeline([
        ('imputer', SimpleImputer(strategy='median')),
        ('scaler', StandardScaler()),
    ])
    cat_pipe = Pipeline([
        ('imputer', SimpleImputer(strategy='most_frequent')),
        ('encoder', OneHotEncoder(handle_unknown='ignore', sparse_output=False)),
    ])
    preprocessor = ColumnTransformer([
        ('num', num_pipe, numeric_cols),
        ('cat', cat_pipe, cat_cols),
    ])

    # Base model 1: Logistic Regression
    lr = LogisticRegression(C=0.1, solver='lbfgs', max_iter=1000,
                            class_weight='balanced', random_state=42)

    # Base model 2: Random Forest
    rf = RandomForestClassifier(n_estimators=200, max_features='sqrt',
                                class_weight='balanced', n_jobs=-1,
                                random_state=42)

    # Base model 3: HistGradientBoosting (fast, handles NaN)
    hgbc = HistGradientBoostingClassifier(max_iter=200, max_depth=5,
                                          learning_rate=0.05,
                                          random_state=42)

    # Stacking ensemble with LR as meta-learner
    stacked = StackingClassifier(
        estimators=[('lr', lr), ('rf', rf), ('hgbc', hgbc)],
        final_estimator=LogisticRegression(C=0.5, max_iter=500),
        cv=StratifiedKFold(5, shuffle=True, random_state=42),
        n_jobs=-1,
    )

    # Wrap in calibration
    calibrated_stacked = CalibratedClassifierCV(
        stacked, cv='prefit', method='isotonic',
    )

    # Full pipeline with preprocessor
    pipeline = Pipeline([
        ('preprocessor', preprocessor),
        ('model', stacked),
    ])

    return pipeline


def evaluate_fraud_model(model, X_test, y_test):
    """Evaluate using fraud-appropriate metrics."""
    y_prob = model.predict_proba(X_test)[:, 1]
    print(f"ROC-AUC:            {roc_auc_score(y_test, y_prob):.4f}")
    print(f"Avg Precision (PR): {average_precision_score(y_test, y_prob):.4f}")
    # Also inspect: precision at top-1% of scores (high-value alert tier)
    threshold = np.percentile(y_prob, 99)
    high_risk = y_prob >= threshold
    print(f"Precision@top1%:    {y_test[high_risk].mean():.4f}")
