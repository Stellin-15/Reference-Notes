# ============================================================
# L03: XGBoost — Zero to Production
# ============================================================
# WHAT: XGBoost (eXtreme Gradient Boosting) is a gradient
#       boosted tree framework with built-in L1/L2 regularization,
#       histogram-based approximate split finding, native missing
#       value handling, GPU support, and a sklearn-compatible API.
# WHY:  XGBoost wins more Kaggle tabular competitions than any
#       other single model. On structured/tabular data it usually
#       outperforms random forests, classical boosting, and shallow
#       NNs — combining bias reduction (boosting) with variance
#       control (regularization + subsampling).
# LEVEL: Intermediate
# ============================================================
"""
CONCEPT OVERVIEW:
    Gradient boosting builds trees SEQUENTIALLY. Each tree fits
    the negative gradient (residual) of the loss from the current
    ensemble. XGBoost extends this with: second-order Taylor
    expansion of the loss for more accurate gradient steps; L1
    and L2 penalties on leaf weights; column and row subsampling
    to decorrelate trees; and histogram-based approximate split
    finding that scales to large datasets. The result is a highly
    regularized, fast, accurate algorithm.

PRODUCTION USE CASE:
    House price prediction: raw tabular features → DMatrix →
    XGBoost with early stopping (val MSE as monitor) → SHAP
    waterfall plots for individual predictions → joblib serialization
    → ONNX export for low-latency serving.

COMMON MISTAKES:
    1. Imputing NaN before feeding to XGBoost — XGBoost learns
       the optimal direction for missing values; imputation
       replaces signal with noise.
    2. Setting learning_rate=0.3 (old default) with few trees —
       better to use 0.05-0.1 with many trees + early stopping.
    3. Not using scale_pos_weight for imbalanced targets — the
       model will almost always predict the majority class.
    4. Ignoring colsample_bytree — leaving it at 1.0 means no
       feature subsampling; trees become too correlated.
    5. Overfitting on the eval set by watching it too long with
       large early_stopping_rounds — use ~50 rounds max.
"""

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split, KFold, cross_val_score
from sklearn.metrics import mean_squared_error, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
import joblib

# ============================================================
# SECTION 1: What XGBoost Is — The Algorithm
# ============================================================
# Standard gradient boosting:
#   F_0(x) = initial prediction (e.g., mean of y)
#   For m = 1, 2, ..., M:
#     r_i = -dL/dF (negative gradient = pseudo-residual)
#     Fit tree h_m to {(x_i, r_i)}
#     F_m(x) = F_{m-1}(x) + learning_rate * h_m(x)
#
# XGBoost improvements:
#   1. Uses SECOND-order gradients (hessian) for more accurate
#      leaf weight computation. Minimizes the exact quadratic
#      approximation of the loss, not just the gradient.
#   2. L1 penalty (reg_alpha) on leaf weights — drives some to 0.
#   3. L2 penalty (reg_lambda) on leaf weights — shrinks all.
#   4. gamma (min_split_loss) — prune splits that don't reduce
#      the regularized objective by at least gamma.
#   5. Approximate split finding via feature histograms —
#      instead of checking every unique value, bin into
#      ~256 buckets. Much faster on large datasets.
#   6. Column subsampling (colsample_bytree, colsample_bylevel).
#   7. Row subsampling (subsample) — bootstrap-like.
#   8. Native sparse matrix support — zero values skipped.
#   9. Native missing value handling — learns split direction.
#
# Why XGBoost beats Random Forest on tabular:
#   RF only reduces VARIANCE (averaging diverse trees).
#   Boosting reduces BIAS (corrects systematic errors).
#   On structured data with engineered features, bias is often
#   the bottleneck → boosting wins.

# ============================================================
# SECTION 2: DMatrix — XGBoost's Internal Data Format
# ============================================================
# DMatrix is XGBoost's optimized data container. Benefits:
#   - Preserves sparsity (skips zeros in memory)
#   - Handles NaN natively (no imputation needed)
#   - Stores sample weights alongside features
#   - Faster than converting from pandas every training call
#
# Always create DMatrix from your data ONCE and reuse.
# For sklearn API (XGBClassifier), DMatrix is created internally.

def create_dmatrix(X_train, y_train, X_val=None, y_val=None,
                   sample_weights=None):
    """
    Wrap numpy arrays or DataFrames in DMatrix.
    missing=np.nan tells XGBoost what value represents missing.
    """
    dtrain = xgb.DMatrix(
        X_train,
        label=y_train,
        missing=np.nan,          # treat NaN as missing (learns direction)
        weight=sample_weights,   # per-sample weights for imbalance
        feature_names=list(X_train.columns) if hasattr(X_train, 'columns') else None,
    )
    if X_val is not None:
        dval = xgb.DMatrix(X_val, label=y_val, missing=np.nan,
                           feature_names=list(X_val.columns) if hasattr(X_val, 'columns') else None)
        return dtrain, dval
    return dtrain

# ============================================================
# SECTION 3: Hyperparameter Reference — Every Parameter Explained
# ============================================================
# This is the most important section. Know what each knob does
# BEFORE tuning — otherwise you're guessing in 10D space.

XGB_PARAMS_CLASSIFICATION = {
    # --- Ensemble size + learning rate ---
    'n_estimators': 500,
    # Number of trees. More trees + lower lr = better generalization.
    # Set high; use early stopping to find the right count.

    'learning_rate': 0.05,
    # Step size for each tree's contribution (eta).
    # 0.05-0.1 with early stopping gives good generalization.
    # Lower lr → need more trees → slower but often better.

    # --- Tree structure ---
    'max_depth': 6,
    # Depth of each tree. 3-8 is typical. Deeper = more complex
    # = more overfit risk. Start at 6, tune down if overfitting.

    'min_child_weight': 1,
    # Minimum sum of instance weights (hessian) in a leaf.
    # Higher = fewer splits = more regularization.
    # Increase if overfitting on small/noisy data. Range: 1-10.

    'gamma': 0.0,
    # Minimum loss reduction required to make a split (min_split_loss).
    # 0 = no constraint. Higher = more conservative trees.
    # Start at 0, increase if overfitting. Range: 0-5.

    # --- Subsampling ---
    'subsample': 0.8,
    # Fraction of training rows sampled per tree.
    # Like bootstrap in RF but without replacement.
    # 0.8 reduces variance without much bias increase. Range: 0.5-1.0.

    'colsample_bytree': 0.8,
    # Fraction of features sampled per tree (like RF's max_features).
    # Decorrelates trees. 0.8 is a good default. Range: 0.5-1.0.

    'colsample_bylevel': 1.0,
    # Fraction of features sampled per level (depth) within a tree.
    # Additional subsampling on top of colsample_bytree.

    # --- Regularization ---
    'reg_alpha': 0.0,
    # L1 regularization on leaf weights. Sparse weights.
    # Useful for high-dimensional data with many irrelevant features.
    # Range: 0-10. Start at 0, tune up if overfitting.

    'reg_lambda': 1.0,
    # L2 regularization on leaf weights (default=1). Shrinks weights.
    # Prevents any single leaf from having a huge weight.
    # Range: 0-10. XGBoost's default L2 already helps a lot.

    # --- Imbalanced classes ---
    'scale_pos_weight': 1,
    # For binary classification: set to neg_count / pos_count.
    # E.g., 990 negatives + 10 positives → scale_pos_weight=99.
    # Equivalent to class_weight='balanced' in sklearn.

    # --- Objective and metric ---
    'objective': 'binary:logistic',
    # 'binary:logistic'  → binary classification, outputs probability
    # 'multi:softmax'    → multiclass, outputs class label
    # 'multi:softprob'   → multiclass, outputs probability per class
    # 'reg:squarederror' → regression (MSE)
    # 'reg:absoluteerror'→ regression (MAE)

    'eval_metric': 'auc',
    # Metric tracked during training for early stopping.
    # 'auc' for classification, 'rmse' for regression.
    # Multiple metrics: ['auc', 'logloss']

    # --- Compute ---
    'device': 'cpu',
    # 'cpu': default. 'cuda': GPU (requires CUDA).
    # Or use tree_method='gpu_hist' for older XGBoost versions.
    # GPU gives 10-50x speedup on large datasets.

    'n_jobs': -1,
    # Number of parallel threads. -1 = use all cores.
    # Only applies to CPU training.

    'seed': 42,
}

XGB_PARAMS_REGRESSION = {
    'n_estimators': 500,
    'learning_rate': 0.05,
    'max_depth': 6,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'min_child_weight': 3,
    'reg_alpha': 0.1,
    'reg_lambda': 1.0,
    'objective': 'reg:squarederror',
    'eval_metric': 'rmse',
    'device': 'cpu',
    'n_jobs': -1,
    'seed': 42,
}

# ============================================================
# SECTION 4: Sklearn API — XGBClassifier and XGBRegressor
# ============================================================
# XGBClassifier wraps XGBoost in the sklearn estimator API.
# Supports: Pipeline, GridSearchCV, cross_val_score.
# Early stopping: pass eval_set and early_stopping_rounds to fit().
# NOTE: early_stopping_rounds is now a constructor argument (XGBoost 2.0).

def build_xgb_classifier(neg_count, pos_count):
    """Build an XGBClassifier with sensible production defaults."""
    spw = neg_count / pos_count  # scale_pos_weight for imbalance
    return xgb.XGBClassifier(
        n_estimators=1000,       # set high; early stopping will cut it
        learning_rate=0.05,
        max_depth=6,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=1,
        gamma=0.0,
        reg_alpha=0.0,
        reg_lambda=1.0,
        scale_pos_weight=spw,    # handle class imbalance
        objective='binary:logistic',
        eval_metric='auc',
        early_stopping_rounds=50,  # stop if AUC doesn't improve for 50 rounds
        device='cpu',
        n_jobs=-1,
        random_state=42,
        verbosity=1,
    )

# ============================================================
# SECTION 5: Early Stopping
# ============================================================
# Early stopping monitors a validation metric and stops training
# when it doesn't improve for N consecutive rounds.
#
# Why it matters:
#   - Prevents overfitting without manual tuning of n_estimators.
#   - The validation metric plateaus when the model has learned
#     everything generalizable; more trees only memorize noise.
#
# Workflow:
#   1. Set n_estimators high (500-1000).
#   2. Pass eval_set=[(X_val, y_val)] to fit().
#   3. Set early_stopping_rounds=50.
#   4. After training: model.best_iteration gives optimal n_estimators.
#   5. Retrain on FULL train+val data with n_estimators=best_iteration.

def train_with_early_stopping(X_train, y_train, X_val, y_val,
                               neg_count, pos_count):
    model = build_xgb_classifier(neg_count, pos_count)
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],   # monitor on validation set
        verbose=100,                   # print every 100 rounds
    )
    print(f"Best iteration: {model.best_iteration}")
    print(f"Best AUC: {model.best_score:.4f}")
    return model

# ============================================================
# SECTION 6: Missing Values — Do NOT Impute
# ============================================================
# XGBoost handles NaN natively. At each split, samples with
# missing values are sent to a DEFAULT direction. XGBoost learns
# this direction during training by trying both sides and keeping
# whichever reduces the objective more.
#
# This is BETTER than imputation because:
#   - Imputing inserts a made-up value into a learned split.
#   - "Missingness" itself is often predictive (e.g., missing
#     income might correlate with being self-employed).
#   - XGBoost exploits the signal in missingness directly.
#
# Exception: when you use XGBoost inside a sklearn Pipeline that
# has other steps requiring non-NaN inputs, impute AFTER those
# steps but before XGBoost — or just let XGBoost handle NaN alone.

# ============================================================
# SECTION 7: Categorical Features (XGBoost 1.7+)
# ============================================================
# Native categoricals: no OHE needed. XGBoost partitions
# categories into groups (like CatBoost), much better than
# ordinal encoding for high-cardinality features.
# Requires: enable_categorical=True + pandas Categorical dtype.

def prepare_categoricals(df, cat_cols):
    """Convert string columns to pandas Categorical for XGBoost."""
    df = df.copy()
    for col in cat_cols:
        df[col] = df[col].astype('category')
    return df

# model = XGBClassifier(enable_categorical=True, tree_method='hist')
# model.fit(df_with_cat_columns, y)

# ============================================================
# SECTION 8: Feature Importance
# ============================================================
# XGBoost provides three importance types via get_score():
#   'weight': number of times feature is used in splits.
#     Simple count — biased toward features used frequently.
#   'gain': average gain in objective per split on this feature.
#     Most informative built-in metric. Use as default.
#   'cover': average number of samples covered per split.
#     Useful for understanding feature reach.
#
# All three have bias toward high-cardinality features.
# SHAP (shap.TreeExplainer) is the gold standard.

def get_xgb_feature_importance(model, importance_type='gain'):
    """Return sorted feature importance dictionary."""
    booster = model.get_booster()
    scores = booster.get_score(importance_type=importance_type)
    # Sort by importance descending
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_scores

# SHAP (most reliable):
# import shap
# explainer = shap.TreeExplainer(model)
# shap_values = explainer(X_test)
# shap.summary_plot(shap_values, X_test)      # global importance
# shap.waterfall_plot(shap_values[0])          # single prediction explanation

# ============================================================
# SECTION 9: Monotone Constraints
# ============================================================
# Enforce domain knowledge: some features should ONLY increase
# or ONLY decrease the prediction. Prevents the model from
# learning spurious reversals that would be wrong in production.
#
# monotone_constraints: dict mapping feature name → direction:
#   +1: feature can only INCREASE predictions
#    0: no constraint
#   -1: feature can only DECREASE predictions
#
# Real examples:
#   - Credit model: higher income → higher credit limit (+1)
#   - Insurance: more claims history → higher risk (+1)
#   - Churn: longer tenure → lower churn probability (-1)
#
# Required in regulated industries (fair lending, insurance
# underwriting) where the model must be monotonically sensible.

MONOTONE_CONSTRAINTS_EXAMPLE = {
    'income': 1,          # higher income → higher credit limit
    'years_employed': 1,  # more stable employment → higher limit
    'num_defaults': -1,   # more defaults → lower credit limit
    'debt_ratio': -1,     # higher debt → lower credit limit
}

# model = XGBClassifier(
#     monotone_constraints=MONOTONE_CONSTRAINTS_EXAMPLE,
#     ...
# )

# ============================================================
# SECTION 10: LightGBM vs XGBoost — Comparison
# ============================================================
# XGBoost:
#   Growth strategy: LEVEL-WISE (expand all nodes at current depth)
#     → more conservative, less overfit risk on small data.
#   Ecosystem: most mature, best docs, widest deployment.
#   Missing values: native, excellent.
#   Monotone constraints: excellent support.
#
# LightGBM:
#   Growth strategy: LEAF-WISE (expand the leaf with highest gain)
#     → more accurate per tree but can overfit; mitigate with
#     num_leaves, min_data_in_leaf.
#   Speed: faster training, less memory (histogram implementation).
#   Large datasets: scales better (distributed training via MPI).
#   Categoricals: excellent native support.
#
# In practice: try both, compare on your validation set.
# LightGBM often wins on large datasets (>1M rows).
# XGBoost often more stable on smaller datasets.

# ============================================================
# SECTION 11: When XGBoost Beats Neural Networks
# ============================================================
# XGBoost (or LightGBM) outperforms NNs when:
#   - Tabular data, < 1M rows, features are hand-engineered
#   - Need interpretability (SHAP explains every prediction)
#   - Limited compute (no GPU, small team, fast iteration)
#   - Feature interactions are local and sparse (trees capture this)
#   - You need calibrated predictions with monotone constraints
#
# NNs win when:
#   - Raw images, audio, text (unstructured inputs)
#   - Very large tabular data (>1M rows) with dense interactions
#   - Transfer learning from pretrained models is applicable
#   - Embedding learning for high-cardinality IDs (user/item)

# ============================================================
# SECTION 12: End-to-End House Price Example
# ============================================================

def run_house_price_demo(df: pd.DataFrame, target_col='price'):
    """
    Regression demo: house price prediction.
    Features: mix of numeric and categorical columns.
    Strategy: DMatrix + early stopping + SHAP + save.
    """
    cat_cols = [c for c in df.columns if df[c].dtype == 'object']
    num_cols = [c for c in df.columns if c not in cat_cols + [target_col]]

    # Convert categoricals for native XGBoost handling
    df = prepare_categoricals(df, cat_cols)

    X = df.drop(columns=[target_col])
    y = df[target_col].values

    # Split (DO NOT stratify — regression target is continuous)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42,
    )
    X_train, X_val, y_train, y_val = train_test_split(
        X_train, y_train, test_size=0.15, random_state=42,
    )

    # Build and train model with early stopping on RMSE
    model = xgb.XGBRegressor(
        n_estimators=1000,
        learning_rate=0.05,
        max_depth=6,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=3,
        reg_alpha=0.1,
        reg_lambda=1.0,
        objective='reg:squarederror',
        eval_metric='rmse',
        early_stopping_rounds=50,
        enable_categorical=True,
        tree_method='hist',
        device='cpu',
        n_jobs=-1,
        random_state=42,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=100,
    )

    # Evaluate on test set
    y_pred = model.predict(X_test)
    rmse = mean_squared_error(y_test, y_pred, squared=False)
    print(f"Test RMSE: {rmse:.2f}")
    print(f"Best iteration: {model.best_iteration}")

    # Feature importance (gain)
    importance = get_xgb_feature_importance(model, importance_type='gain')
    print("\nTop 10 features by gain:")
    for feat, score in importance[:10]:
        print(f"  {feat}: {score:.4f}")

    # Save model
    joblib.dump({'model': model, 'features': list(X.columns)},
                'house_price_xgb.joblib')

    # ONNX export for serving (see L08 for full workflow)
    # from skl2onnx import convert_sklearn  # for sklearn wrappers
    # XGBoost has native ONNX via: model.save_model('model.json')
    # then load with onnxmltools or directly with onnxruntime via
    # the XGBoost ONNX converter.
    model.save_model('house_price_xgb.json')  # portable JSON format
    print("Saved model.json (XGBoost native, portable)")

    return model


# ============================================================
# SECTION 13: GPU Training
# ============================================================
# For large datasets (>100k rows), GPU can give 10-50x speedup.
#
# XGBoost 2.0+ syntax:
#   device='cuda'  (or 'cuda:0' for specific GPU)
#
# Older XGBoost:
#   tree_method='gpu_hist'
#
# Requirements: CUDA-capable GPU, CUDA toolkit installed,
# xgboost built with GPU support (pip install xgboost provides it).
#
# Check GPU availability:
# import subprocess
# result = subprocess.run(['nvidia-smi'], capture_output=True)
# has_gpu = result.returncode == 0

GPU_PARAMS = {
    **XGB_PARAMS_CLASSIFICATION,
    'device': 'cuda',        # XGBoost 2.0+
    'tree_method': 'hist',   # always use hist with GPU
}
# model = xgb.XGBClassifier(**GPU_PARAMS)
