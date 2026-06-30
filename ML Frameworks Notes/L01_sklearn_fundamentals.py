# ============================================================
# L01: Scikit-learn Fundamentals
# ============================================================
# WHAT: The core API and data conventions that underpin every
#       sklearn estimator: fit/predict/transform, the Pipeline
#       abstraction, preprocessing, encoding, imputation,
#       feature selection, splitting, cross-validation,
#       metrics, and model persistence.
# WHY:  Scikit-learn is the industry standard for tabular ML.
#       Understanding its conventions lets you swap models,
#       prevent data leakage, and ship reproducible pipelines
#       without rewriting preprocessing logic every project.
# LEVEL: Foundations
# ============================================================
"""
CONCEPT OVERVIEW:
    Sklearn is built around one idea: every estimator has the
    same interface. That uniformity makes it trivially easy to
    replace a LogisticRegression with a RandomForest, wrap
    both in a Pipeline, tune hyperparameters with GridSearch,
    and serialize the whole thing with one joblib call.

PRODUCTION USE CASE:
    Customer churn prediction: raw CSV with numeric + categorical
    columns → ColumnTransformer (impute, scale, encode) →
    LogisticRegression → StratifiedKFold cross-validation →
    ROC-AUC metric → joblib save. The same Pipeline object
    handles both training and serving; you never hand-roll
    preprocessing at inference time.

COMMON MISTAKES:
    1. Fitting the scaler on ALL data before splitting (data
       leakage — test statistics bleed into the scaler).
    2. Using LabelEncoder on features (creates fake ordinal
       relationships; use OneHotEncoder in a Pipeline).
    3. Ignoring class imbalance — accuracy is misleading; use
       ROC-AUC or average_precision_score.
    4. Not using stratify=y in train_test_split for classif.
    5. Saving the model without saving the feature name list —
       column order changes at serving time cause silent bugs.
"""

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import (
    StandardScaler, MinMaxScaler, RobustScaler,
    OneHotEncoder, OrdinalEncoder, LabelEncoder,
)
from sklearn.impute import SimpleImputer, KNNImputer
from sklearn.feature_selection import (
    SelectKBest, f_classif, RFE, SelectFromModel,
    VarianceThreshold,
)
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import (
    train_test_split, KFold, StratifiedKFold, cross_val_score,
)
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score,
    f1_score, roc_auc_score, average_precision_score,
    mean_squared_error, mean_absolute_error, r2_score,
)
import joblib

# ============================================================
# SECTION 1: The Estimator API
# ============================================================
# Every sklearn object shares the same three-method contract:
#   fit(X, y)         — learn parameters from training data
#   predict(X)        — apply learned parameters to new data
#   transform(X)      — transformers only: convert features
#   fit_transform(X)  — convenience: fit then transform
#
# This uniformity is not cosmetic. It means any model can
# slot into a Pipeline without special-casing. A Pipeline is
# itself an estimator, so you can nest pipelines, grid-search
# the whole thing, and cross-validate it in one call.

# ============================================================
# SECTION 2: Data Format Convention
# ============================================================
# X must be 2D: shape [n_samples, n_features]
# y must be 1D: shape [n_samples]
# Violating this causes cryptic "matmul dimension mismatch"
# or "bad input shape" errors. Always assert shapes first.

def validate_shapes(X, y):
    """Guard against shape mistakes before fitting."""
    assert X.ndim == 2, f"X must be 2D, got shape {X.shape}"
    assert y.ndim == 1, f"y must be 1D, got shape {y.shape}"
    assert X.shape[0] == y.shape[0], "n_samples mismatch"
    print(f"X: {X.shape}  y: {y.shape}")  # always print!

# ============================================================
# SECTION 3: Scalers — when and which
# ============================================================
# Rule of thumb:
#   Linear models (LR, SVM), KNN, NNs → NEED scaling.
#     Unscaled: a feature with range [0, 100000] dominates
#     a feature with range [0, 1], biasing gradient steps.
#   Tree models (RF, XGB, LGBM) → DO NOT need scaling.
#     They split on thresholds, so the absolute scale doesn't
#     change the split quality — only the threshold changes.

# StandardScaler: subtract mean, divide by std → mean=0, std=1
# Best for: normally distributed features, linear models.
# Sensitive to outliers (outliers inflate std, compress rest).
std_scaler = StandardScaler()

# MinMaxScaler: scale to [0, 1] via (x - min)/(max - min)
# Best for: neural networks, when you need bounded outputs.
# Very sensitive to outliers (one extreme pulls everything).
mm_scaler = MinMaxScaler(feature_range=(0, 1))

# RobustScaler: subtract median, divide by IQR (Q75 - Q25)
# Best for: data with significant outliers you can't remove.
# Outlier-robust because IQR ignores extreme values.
rb_scaler = RobustScaler(quantile_range=(25.0, 75.0))

# ============================================================
# SECTION 4: Encoders for Categorical Features
# ============================================================
# Categorical features must be converted to numbers.
# The encoding strategy depends on whether the feature has order.

# OneHotEncoder: creates a binary column per category.
# Use for NOMINAL categories (no natural order):
#   city, product_type, browser_name.
# handle_unknown='ignore' → unseen categories → all zeros.
# sparse_output=False → return dense array (easier to work with).
ohe = OneHotEncoder(handle_unknown='ignore', sparse_output=False)

# OrdinalEncoder: maps each category to an integer 0, 1, 2...
# Use for ORDINAL categories (natural order exists):
#   education_level: high_school < bachelor < master < phd.
# Pass explicit categories to enforce the correct ordering.
ord_enc = OrdinalEncoder(
    categories=[['high_school', 'bachelor', 'master', 'phd']],
    handle_unknown='use_encoded_value',
    unknown_value=-1,
)

# LabelEncoder: ONLY for the target y (NOT features).
# Encodes 'cat','dog' → 0,1. If used on a feature with 3+
# classes it creates a false ordinal relationship the model
# will try to exploit (e.g. 'dog'=2 > 'bird'=1 > 'cat'=0).
le = LabelEncoder()  # use: y_encoded = le.fit_transform(y)

# pd.get_dummies() vs OneHotEncoder:
# get_dummies(): works on DataFrames, simple, but does NOT
#   fit/transform — it can't be stored in a Pipeline. Test
#   set may get different columns if categories differ.
# OneHotEncoder in Pipeline: learns categories from training
#   data at fit time, applies same columns at transform time.
#   Always use OHE in production pipelines.

# ============================================================
# SECTION 5: Imputers for Missing Values
# ============================================================
# Never drop rows with NaN at training time without a plan
# for serving (where you can't just "drop" a request).
# Impute with the same strategy in training and serving.

# SimpleImputer strategies:
#   'mean'          — best for normally distributed numerics
#   'median'        — best for skewed numerics (income, price)
#   'most_frequent' — best for categoricals
#   'constant'      — fills with fill_value (e.g., 0 or 'MISSING')
mean_imputer   = SimpleImputer(strategy='mean')
median_imputer = SimpleImputer(strategy='median')
cat_imputer    = SimpleImputer(strategy='most_frequent')
const_imputer  = SimpleImputer(strategy='constant', fill_value=0)

# KNNImputer: finds k nearest neighbors (by non-missing features),
# fills missing value with their weighted mean. More accurate than
# simple imputers but much slower — O(n^2). Use on small datasets.
knn_imputer = KNNImputer(n_neighbors=5, weights='uniform')

# IterativeImputer (experimental): models each feature as a
# function of all others, iterates until convergence.
# Most accurate, slowest. Enable with: from sklearn.experimental
# import enable_iterative_imputer; from sklearn.impute import it.

# ============================================================
# SECTION 6: Pipeline — the core abstraction
# ============================================================
# Pipeline chains steps: each step's output is the next step's
# input. The last step can be any estimator (not just transformer).
#
# CRITICAL: Pipeline.fit() fits ALL steps on training data.
#   The scaler sees ONLY training data → no leakage.
# Pipeline.predict() applies fitted transformers then predicts.
#
# Without Pipeline, a common bug is: fit scaler on X_all,
# then split → test statistics contaminate training.

numeric_features = ['age', 'income', 'credit_score']
categorical_features = ['city', 'plan_type']

# Pipeline for numeric columns: impute median, then scale
numeric_pipeline = Pipeline([
    ('imputer', SimpleImputer(strategy='median')),
    ('scaler', StandardScaler()),
])

# Pipeline for categorical columns: impute most_frequent, then OHE
categorical_pipeline = Pipeline([
    ('imputer', SimpleImputer(strategy='most_frequent')),
    ('encoder', OneHotEncoder(handle_unknown='ignore', sparse_output=False)),
])

# ColumnTransformer: apply different pipelines to different columns
# remainder='drop'        → discard all other columns (default)
# remainder='passthrough' → keep other columns as-is
preprocessor = ColumnTransformer(
    transformers=[
        ('num', numeric_pipeline, numeric_features),
        ('cat', categorical_pipeline, categorical_features),
    ],
    remainder='drop',
)

# Full pipeline: preprocessing → classifier
full_pipeline = Pipeline([
    ('preprocessor', preprocessor),
    ('classifier', LogisticRegression(
        C=1.0,
        solver='lbfgs',
        max_iter=1000,
        class_weight='balanced',  # handles class imbalance
        random_state=42,
    )),
])

# ============================================================
# SECTION 7: Feature Selection
# ============================================================
# More features ≠ better model. Irrelevant features add noise,
# slow training, hurt interpretability, and can cause overfitting.

# SelectKBest: univariate test — measure each feature's
# relationship to y independently. f_classif (ANOVA F-test) for
# continuous features + categorical target. Fast, but misses
# interaction effects.
kbest = SelectKBest(score_func=f_classif, k=20)

# RFE (Recursive Feature Elimination): fits model, removes
# weakest feature (lowest importance), repeats. Slower but
# accounts for feature interactions via the model.
rfe = RFE(
    estimator=LogisticRegression(max_iter=500),
    n_features_to_select=10,
    step=1,
)

# SelectFromModel: keep features whose importance exceeds threshold.
# threshold='median' → keep top half. 'mean' → above-average only.
sfm = SelectFromModel(
    estimator=RandomForestClassifier(n_estimators=100, random_state=42),
    threshold='median',
)

# VarianceThreshold: remove features with near-zero variance.
# Features that are constant (or near-constant) carry no info.
# threshold=0.01 removes features where >99% of values are the same.
vt = VarianceThreshold(threshold=0.01)

# ============================================================
# SECTION 8: Train/Test Split
# ============================================================
# test_size=0.2 → 80/20 split, standard for moderate datasets.
# random_state=42 → reproducibility; always set it.
# stratify=y → preserves class ratio in both splits.
#   Without stratify: random split may put all rare positives
#   in the training set. Always use for classification.

def demo_split(X, y):
    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=0.2,
        random_state=42,
        stratify=y,         # CRITICAL for classification
    )
    print(f"Train: {X_train.shape}, Test: {X_test.shape}")
    print(f"Train positive rate: {y_train.mean():.3f}")
    print(f"Test positive rate:  {y_test.mean():.3f}")
    return X_train, X_test, y_train, y_test

# ============================================================
# SECTION 9: Cross-Validation
# ============================================================
# A single train/test split has high variance — the model may
# look good or bad depending purely on which rows ended up in
# the test set. Cross-validation averages over k different splits.
#
# KFold: splits data into k equal folds. Rotate through: each
#   fold serves as test set once, rest are training. k=5 is
#   the standard (good bias-variance tradeoff).
# StratifiedKFold: like KFold but preserves class ratio in each
#   fold. ALWAYS use for classification tasks.

def demo_cv(pipeline, X, y):
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(
        pipeline, X, y,
        cv=cv,
        scoring='roc_auc',  # threshold-independent, good for imbalanced
        n_jobs=-1,           # parallelize over CPU cores
    )
    print(f"CV ROC-AUC: {scores.mean():.4f} ± {scores.std():.4f}")
    return scores

# ============================================================
# SECTION 10: Evaluation Metrics
# ============================================================
# Classification:
#   accuracy_score       → misleading for imbalanced data
#   precision_score      → TP / (TP + FP) — "of predicted pos, how many right?"
#   recall_score         → TP / (TP + FN) — "of actual pos, how many found?"
#   f1_score             → harmonic mean of precision + recall
#   roc_auc_score        → area under ROC curve, threshold-independent
#                          0.5 = random, 1.0 = perfect
#   average_precision_score → area under Precision-Recall curve.
#                          Better than ROC-AUC for heavily imbalanced.
#
# Regression:
#   mean_squared_error(y, yhat, squared=False) → RMSE (same units as y)
#   mean_absolute_error  → MAE (less sensitive to outliers than MSE)
#   r2_score             → 1.0 perfect, 0.0 = predicting mean, <0 = worse

def evaluate_classifier(y_true, y_pred, y_prob):
    """Print a full classification scorecard."""
    print(f"Accuracy:           {accuracy_score(y_true, y_pred):.4f}")
    print(f"Precision:          {precision_score(y_true, y_pred):.4f}")
    print(f"Recall:             {recall_score(y_true, y_pred):.4f}")
    print(f"F1:                 {f1_score(y_true, y_pred):.4f}")
    print(f"ROC-AUC:            {roc_auc_score(y_true, y_prob):.4f}")
    print(f"Avg Precision (PR): {average_precision_score(y_true, y_prob):.4f}")

# ============================================================
# SECTION 11: Saving and Loading
# ============================================================
# joblib is preferred over pickle for sklearn models because:
#   - Faster for large NumPy arrays (uses memory-mapped files)
#   - Pickle is slower and has no safety advantages here
# Save the ENTIRE pipeline — not just the model. The scaler
# and encoder states are part of the artifact.
#
# Always save alongside the model:
#   - feature_names: list of columns expected at inference
#   - schema: dtype for each column
#   - version: git SHA or semantic version
#   - metrics: the evaluation scores achieved on hold-out data

def save_model(pipeline, feature_names, metrics, path='model.joblib'):
    artifact = {
        'pipeline': pipeline,
        'feature_names': feature_names,
        'metrics': metrics,
        'sklearn_version': '1.4.0',  # pin version
    }
    joblib.dump(artifact, path, compress=3)
    print(f"Saved to {path}")

def load_model(path='model.joblib'):
    artifact = joblib.load(path)
    return artifact['pipeline'], artifact['feature_names']

# ============================================================
# SECTION 12: When Sklearn vs Deep Learning
# ============================================================
# Use sklearn when:
#   - Tabular data with < 1M rows
#   - Interpretability required (LR coefficients, RF importances)
#   - Limited compute (laptop, no GPU)
#   - Small team, fast iteration needed
#   - Baseline before committing to DL complexity
#
# Use deep learning when:
#   - Images, audio, raw text (unstructured inputs)
#   - Tabular data > 1M rows with complex feature interactions
#   - Transfer learning from pretrained models
#   - Sequence/time-series with long-range dependencies

# ============================================================
# SECTION 13: End-to-End Customer Churn Example
# ============================================================

def build_churn_pipeline():
    """
    Full churn prediction pipeline: ColumnTransformer →
    LogisticRegression. Demonstrates all concepts above in
    a realistic workflow.
    """
    num_cols = ['tenure_months', 'monthly_charges', 'total_charges']
    cat_cols = ['contract_type', 'payment_method', 'internet_service']

    num_pipe = Pipeline([
        ('imputer', SimpleImputer(strategy='median')),
        ('scaler', StandardScaler()),
    ])
    cat_pipe = Pipeline([
        ('imputer', SimpleImputer(strategy='most_frequent')),
        ('encoder', OneHotEncoder(handle_unknown='ignore', sparse_output=False)),
    ])

    ct = ColumnTransformer([
        ('num', num_pipe, num_cols),
        ('cat', cat_pipe, cat_cols),
    ])

    pipe = Pipeline([
        ('preprocessor', ct),
        ('classifier', LogisticRegression(
            C=0.1,                   # moderate regularization
            solver='lbfgs',
            max_iter=1000,
            class_weight='balanced', # churn is rare → upweight positives
            random_state=42,
        )),
    ])
    return pipe


def run_churn_demo(df: pd.DataFrame):
    """
    df must contain columns: tenure_months, monthly_charges,
    total_charges, contract_type, payment_method,
    internet_service, churn (0/1 target).
    """
    X = df.drop(columns=['churn'])
    y = df['churn'].values

    validate_shapes(X.values, y)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y,
    )

    pipeline = build_churn_pipeline()

    # Cross-validate on training data (never touch test set here)
    cv_scores = cross_val_score(
        pipeline, X_train, y_train,
        cv=StratifiedKFold(5, shuffle=True, random_state=42),
        scoring='roc_auc',
        n_jobs=-1,
    )
    print(f"CV ROC-AUC: {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")

    # Fit on full training set, evaluate on test set
    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)
    y_prob = pipeline.predict_proba(X_test)[:, 1]
    evaluate_classifier(y_test, y_pred, y_prob)

    # Save artifact
    save_model(
        pipeline,
        feature_names=list(X.columns),
        metrics={'roc_auc_cv': cv_scores.mean()},
        path='churn_model.joblib',
    )
    return pipeline


# Usage:
# df = pd.read_csv('telco_churn.csv')
# pipeline = run_churn_demo(df)
