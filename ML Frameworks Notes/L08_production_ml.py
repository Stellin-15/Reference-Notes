# ============================================================
# L08: Production ML Patterns
# ============================================================
# WHAT: The full lifecycle of taking an ML model from a Jupyter
#       notebook to a reliable production system: training-serving
#       skew prevention, model versioning, serialization formats,
#       ONNX export + quantization, serving architectures, A/B
#       testing, shadow deployment, drift monitoring, SHAP
#       explanations, and retraining pipelines.
# WHY:  90% of ML projects fail not because the model is bad,
#       but because of infrastructure and process failures:
#       silent data bugs, untested serving code, no monitoring,
#       no retraining plan. This file is the blueprint for
#       avoiding all of those.
# LEVEL: Advanced / Production
# ============================================================
"""
CONCEPT OVERVIEW:
    A model that's accurate on a validation set is a starting
    point, not a product. Getting to production requires:
    (1) ensuring training and serving compute features identically,
    (2) versioning every artifact and every experiment,
    (3) exporting to a format that's fast and framework-agnostic,
    (4) serving with latency guarantees and monitoring,
    (5) detecting when the world changes and the model degrades,
    (6) retraining automatically when it does.

PRODUCTION USE CASE:
    Full ML lifecycle: credit risk model. Features engineered in
    Python functions shared between training pipeline and REST
    API. Trained with XGBoost. Exported to ONNX. Quantized to
    int8. Served with FastAPI + dynamic batching. A/B tested
    against previous model. Monitored for PSI drift on 10 features.
    Auto-retrained weekly or on PSI > 0.2.

COMMON MISTAKES:
    1. Training-serving skew: rewriting feature logic in the
       serving layer "for speed" — guaranteed silent divergence.
    2. Serializing full model object (pickle) instead of weights —
       breaks on Python/library version changes.
    3. Not verifying ONNX output matches PyTorch output (np.allclose
       with atol=1e-5 — floating point differences exist).
    4. Loading the model inside the request handler instead of at
       startup — 500-2000ms cold-start latency per request.
    5. Monitoring prediction distribution instead of feature
       distribution — feature drift is the CAUSE, prediction
       drift is the SYMPTOM. Monitor both, but features first.
"""

import numpy as np
import pandas as pd
from pathlib import Path
import json
import time
import hashlib
from datetime import datetime
from typing import Any, Optional

# ============================================================
# SECTION 1: Training-Serving Skew — The #1 Silent Killer
# ============================================================
# Training-serving skew: the model trains on feature X computed
# one way, but at serving time X is computed differently.
#
# Real examples:
#   - Training: avg_spend = mean(last 7 purchases)
#     Serving:  avg_spend = today's_purchase (forgot the 7-day window)
#   - Training: age = floor((today - dob).days / 365)
#     Serving:  age = (today - dob).years  (different on leap years)
#   - Training: normalize by full dataset mean
#     Serving:  normalize by a different snapshot's mean
#
# Fix: THE ONLY SAFE APPROACH is to share the same Python code
# (function, module, or feature store query) between training
# and serving. Never reimplement feature logic.

class FeatureComputer:
    """
    A class whose methods compute features.
    IMPORT THIS SAME CLASS in both:
      - training/feature_engineering.py
      - serving/api.py
    Never duplicate the logic elsewhere.
    """

    @staticmethod
    def compute_avg_spend_7d(transaction_df: pd.DataFrame, user_id: int,
                              reference_date: pd.Timestamp) -> float:
        """7-day average spend. Used in both training and serving."""
        window = transaction_df[
            (transaction_df['user_id'] == user_id) &
            (transaction_df['date'] >= reference_date - pd.Timedelta(days=7)) &
            (transaction_df['date'] < reference_date)
        ]
        return window['amount'].mean() if len(window) > 0 else 0.0

    @staticmethod
    def compute_days_since_last_login(events_df: pd.DataFrame, user_id: int,
                                       reference_date: pd.Timestamp) -> int:
        """Days since last login event. Shared between pipeline and API."""
        logins = events_df[
            (events_df['user_id'] == user_id) &
            (events_df['event_type'] == 'login') &
            (events_df['date'] < reference_date)
        ]['date']
        if len(logins) == 0:
            return 999  # sentinel for "never logged in"
        return (reference_date - logins.max()).days

    @staticmethod
    def build_feature_vector(user_id: int, transaction_df: pd.DataFrame,
                              events_df: pd.DataFrame,
                              reference_date: pd.Timestamp) -> dict:
        """Returns a dict of ALL features for one user at one point in time."""
        return {
            'avg_spend_7d': FeatureComputer.compute_avg_spend_7d(
                transaction_df, user_id, reference_date),
            'days_since_last_login': FeatureComputer.compute_days_since_last_login(
                events_df, user_id, reference_date),
            # ... add all other features here
        }

# ============================================================
# SECTION 2: Model Versioning
# ============================================================
# Every model artifact must be uniquely identifiable. You must
# be able to answer: "What data trained this model? What code?
# What hyperparameters? What did it score?"
#
# Version string components:
#   model_name: human-readable (e.g., "credit_risk_xgb")
#   version: semantic (major.minor.patch) or date-based
#   git_sha: exact code state at training time
#   dataset_version: hash or date range of training data
#   training_date: when the model was trained
#   metrics: hold-out performance (ROC-AUC, PR-AUC, etc.)
#
# MLflow Model Registry: tracks all of the above. Stages:
#   Staging → QA testing → Production → Archived.
# Never deploy without a registry entry.

def build_model_metadata(model_name: str, version: str,
                          git_sha: str, metrics: dict,
                          dataset_info: dict,
                          hyperparams: dict) -> dict:
    return {
        'model_name': model_name,
        'version': version,
        'git_sha': git_sha,
        'training_date': datetime.utcnow().isoformat() + 'Z',
        'dataset': dataset_info,   # {'start': '2024-01-01', 'end': '2025-01-01', 'n_rows': 1000000}
        'metrics': metrics,         # {'roc_auc': 0.87, 'pr_auc': 0.63}
        'hyperparams': hyperparams,
        'feature_names': [],        # list of column names in order
        'sklearn_version': '',
        'python_version': '',
    }

def save_model_with_metadata(model_artifact: Any, metadata: dict,
                              output_dir: str) -> Path:
    """Save model artifact + metadata as a self-describing bundle."""
    import joblib
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Save model weights/artifact
    model_path = output_path / 'model.joblib'
    joblib.dump(model_artifact, model_path)

    # Save metadata as human-readable JSON alongside the model
    meta_path = output_path / 'metadata.json'
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    # Compute hash of model file for integrity checking
    with open(model_path, 'rb') as f:
        md5 = hashlib.md5(f.read()).hexdigest()
    metadata['model_md5'] = md5

    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"Model saved to {output_path}")
    return output_path

# ============================================================
# SECTION 3: Batch vs Online Inference
# ============================================================
# Batch inference:
#   - Run predictions on ALL users/items once (nightly cron).
#   - Store (entity_id → score) in a database.
#   - At request time: DB lookup only. Latency: < 5ms.
#   - Drawbacks: stale (hours old), no real-time signals.
#   - Use when: recommendations, churn scores, risk tiers.
#
# Online inference:
#   - Request arrives → compute features → model.predict() → respond.
#   - Fresh prediction using current signals.
#   - Drawbacks: must be FAST (< 100ms total budget, typically
#     < 20ms for model alone), must scale under load.
#   - Use when: fraud detection (can't be stale), pricing,
#     dynamic ranking, real-time personalization.
#
# Hybrid: precompute slow features offline (store in Redis),
#   merge with fast real-time features at request time,
#   then predict online. Best of both worlds.

# ============================================================
# SECTION 4: Serialization Formats
# ============================================================
# pickle:
#   - AVOID. Version-sensitive (Python + library version must match).
#   - Security risk: arbitrary code execution (RCE) on load.
#   - Only use when no other option exists.
#
# joblib:
#   - Best for sklearn pipelines + NumPy arrays.
#   - Compress=3 is good balance of size and speed.
#   - Still Python-version sensitive but no RCE risk.
#
# torch.save(model.state_dict()):
#   - Save WEIGHTS ONLY, not the class definition.
#   - Requires the model class to be importable at load time.
#   - Portable between PyTorch versions (mostly).
#
# ONNX:
#   - Open Neural Network Exchange. Cross-framework, cross-language.
#   - Load with onnxruntime in any language (Python, C++, Java, Go).
#   - Runtime-optimized: 2-5x faster than PyTorch CPU.
#   - Production standard for deploying PyTorch/sklearn models.
#
# TF SavedModel:
#   - TensorFlow's portable format. Includes computation graph.
#   - Use only if you're in the TF ecosystem.
#
# MLflow model format:
#   - Wrapper around any of the above + conda.yaml for environment.
#   - Tracked in MLflow registry. First-class CI/CD integration.

# ============================================================
# SECTION 5: ONNX Export from PyTorch
# ============================================================
# ONNX export: trace the model with a dummy input to build the
# computation graph, then serialize that graph to disk.
#
# opset_version: ONNX operator version. Use 17 (current stable).
# dynamic_axes: allows variable batch size at runtime.
#   Without this, the model is compiled for exactly the dummy
#   input's batch size — useless for production.
#
# VERIFICATION: always compare PyTorch and ONNX outputs.
# Floating point ops differ slightly across backends.
# atol=1e-5 is typical tolerance; warn if max diff > 1e-3.

def export_pytorch_to_onnx(model, dummy_input: 'torch.Tensor',
                             output_path: str,
                             input_names=None, output_names=None):
    """
    Export PyTorch model to ONNX format.
    dummy_input: a representative input tensor (batch_size doesn't matter).
    """
    import torch
    model.eval()  # CRITICAL: must be eval mode for correct BN/Dropout

    input_names  = input_names  or ['input']
    output_names = output_names or ['output']

    torch.onnx.export(
        model,
        dummy_input,
        output_path,
        export_params=True,       # store trained weights in ONNX file
        opset_version=17,         # ONNX opset; 17 is current stable
        do_constant_folding=True, # optimize constant expressions at export
        input_names=input_names,
        output_names=output_names,
        dynamic_axes={
            input_names[0]:  {0: 'batch_size'},   # variable batch dimension
            output_names[0]: {0: 'batch_size'},
        },
    )
    print(f"ONNX model exported to {output_path}")


def verify_onnx_vs_pytorch(pytorch_model, onnx_path: str,
                             test_input: 'torch.Tensor',
                             atol: float = 1e-5):
    """Verify ONNX output matches PyTorch output within tolerance."""
    import torch
    import onnxruntime as ort

    # PyTorch inference
    pytorch_model.eval()
    with torch.no_grad():
        torch_out = pytorch_model(test_input).numpy()

    # ONNX Runtime inference
    sess = ort.InferenceSession(
        onnx_path,
        providers=['CUDAExecutionProvider', 'CPUExecutionProvider'],
    )
    ort_out = sess.run(None, {'input': test_input.numpy()})[0]

    max_diff = np.max(np.abs(torch_out - ort_out))
    print(f"Max output difference: {max_diff:.2e}")
    assert max_diff < atol, f"ONNX output diverges! max_diff={max_diff:.2e}"
    print("ONNX verification passed.")
    return max_diff


# ONNX export from sklearn (via skl2onnx):
def export_sklearn_to_onnx(sklearn_pipeline, n_features: int, output_path: str):
    """
    Export a fitted sklearn pipeline to ONNX.
    Requires: pip install skl2onnx
    """
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType

    initial_type = [('float_input', FloatTensorType([None, n_features]))]
    onnx_model = convert_sklearn(sklearn_pipeline, initial_types=initial_type)

    with open(output_path, 'wb') as f:
        f.write(onnx_model.SerializeToString())
    print(f"sklearn ONNX model exported to {output_path}")

# ============================================================
# SECTION 6: Model Quantization
# ============================================================
# Quantization: convert float32 weights to int8 (or int4).
# Result: model is 4x smaller, 2-4x faster, uses less memory.
# Accuracy loss: typically < 1% on classification, < 0.5% MSE
# on regression. Test carefully on your task before deploying.
#
# Types:
#   Post-Training Quantization (PTQ): quantize after training.
#     - Dynamic: weights int8, activations float32. Very fast.
#     - Static: weights + activations int8. Requires calibration data.
#   Quantization-Aware Training (QAT): simulate quantization noise
#     during training. Best accuracy but more complex.
#
# In practice: start with dynamic quantization. If accuracy is
# acceptable, ship it. Static quantization only if dynamic isn't fast enough.

def quantize_pytorch_dynamic(model, output_path: str):
    """
    Dynamic post-training quantization. Linear layers quantized to int8.
    Requires no calibration data. Activations remain float32.
    """
    import torch
    quantized_model = torch.quantization.quantize_dynamic(
        model,
        {torch.nn.Linear},     # quantize Linear layers (most params)
        dtype=torch.qint8,     # int8 weights
    )
    torch.save(quantized_model.state_dict(), output_path)
    print(f"Quantized model saved to {output_path}")
    return quantized_model


def quantize_onnx(input_onnx_path: str, output_onnx_path: str):
    """
    Quantize an ONNX model to int8 using ONNX Runtime.
    Result: ~4x smaller, ~2x faster on CPU.
    """
    from onnxruntime.quantization import quantize_dynamic, QuantType
    quantize_dynamic(
        model_input=input_onnx_path,
        model_output=output_onnx_path,
        weight_type=QuantType.QInt8,
    )
    print(f"Quantized ONNX saved to {output_onnx_path}")

# ============================================================
# SECTION 7: Serving Architecture
# ============================================================
# FastAPI + model:
#   Load model at STARTUP (lifespan event), not per request.
#   Async endpoints + threadpool for CPU-bound inference.
#   Add: request validation (pydantic), response schema, logging.
#   Scale with: Gunicorn + Uvicorn workers. 1 worker per CPU core.
#   Suitable for: < 100 RPS, single model, small team.

FASTAPI_SERVING_TEMPLATE = '''
from contextlib import asynccontextmanager
from fastapi import FastAPI
import onnxruntime as ort
import numpy as np
from concurrent.futures import ThreadPoolExecutor

# Global state — loaded once at startup
ort_session = None
executor = ThreadPoolExecutor(max_workers=4)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP: load model once (not per request!)
    global ort_session
    ort_session = ort.InferenceSession(
        "model_quantized.onnx",
        providers=["CPUExecutionProvider"],
    )
    yield
    # SHUTDOWN: cleanup if needed

app = FastAPI(lifespan=lifespan)

@app.post("/predict")
async def predict(request: PredictRequest):
    # Compute features using shared FeatureComputer (no skew!)
    features = FeatureComputer.build_feature_vector(...)
    X = np.array([list(features.values())], dtype=np.float32)

    # Offload CPU-bound inference to thread pool
    import asyncio
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        executor,
        lambda: ort_session.run(None, {"input": X})[0]
    )
    return {"score": float(result[0, 0])}
'''

# TorchServe:
#   PyTorch's official multi-model serving system.
#   Dynamic batching: waits up to 50ms to collect requests,
#     then runs them as a single batch. Huge throughput gain
#     because GPU/ONNX parallelism is maximized.
#   Supports: model versioning, A/B, metrics endpoint.
#
# Triton Inference Server (NVIDIA):
#   Highest throughput and lowest latency.
#   Supports: PyTorch, ONNX, TensorRT, TF, XGBoost.
#   GPU + CPU backends. Dynamic batching. Ensemble pipelines.
#   HTTP + gRPC APIs. Prometheus metrics built-in.
#   Use when: high QPS (>1000 RPS), GPU required, max performance.

# ============================================================
# SECTION 8: A/B Testing
# ============================================================
# A/B test: route a fraction of live traffic to model_v2.
# Track the BUSINESS metric (CTR, conversion rate, revenue),
# not just model metrics (AUC doesn't prove business value).
#
# Steps:
#   1. Define primary metric (e.g., loan approval revenue).
#   2. Calculate required sample size: use power analysis.
#      power=0.8, alpha=0.05, expected effect size.
#   3. Route X% of users to treatment (model_v2), rest to control.
#   4. Log: user_id, timestamp, model_version, prediction, outcome.
#   5. After minimum sample size: test significance.

def required_sample_size(baseline_rate: float, min_effect: float,
                          alpha: float = 0.05, power: float = 0.8) -> int:
    """
    Estimate sample size per arm for a proportion A/B test.
    baseline_rate: control group success rate (e.g., 0.05 = 5% CTR)
    min_effect: minimum detectable absolute change (e.g., 0.005 = 0.5%)
    """
    from scipy import stats
    treatment_rate = baseline_rate + min_effect
    p_bar = (baseline_rate + treatment_rate) / 2

    z_alpha = stats.norm.ppf(1 - alpha / 2)  # two-sided
    z_beta  = stats.norm.ppf(power)

    n = (
        (z_alpha * np.sqrt(2 * p_bar * (1 - p_bar)) +
         z_beta  * np.sqrt(baseline_rate * (1 - baseline_rate) +
                           treatment_rate * (1 - treatment_rate))) ** 2
        / (min_effect ** 2)
    )
    return int(np.ceil(n))


def run_ab_significance_test(control_successes: int, control_n: int,
                               treatment_successes: int, treatment_n: int,
                               alpha: float = 0.05) -> dict:
    """Chi-squared test for A/B test on a binary outcome metric."""
    from scipy.stats import chi2_contingency

    contingency_table = [
        [control_successes,   control_n   - control_successes],
        [treatment_successes, treatment_n - treatment_successes],
    ]
    chi2, p_value, dof, _ = chi2_contingency(contingency_table)

    control_rate   = control_successes   / control_n
    treatment_rate = treatment_successes / treatment_n
    lift           = (treatment_rate - control_rate) / control_rate

    return {
        'control_rate':   control_rate,
        'treatment_rate': treatment_rate,
        'lift':           lift,
        'p_value':        p_value,
        'significant':    p_value < alpha,
    }

# ============================================================
# SECTION 9: Shadow Deployment
# ============================================================
# Shadow deployment: new model runs in parallel with old model.
# Old model's predictions are served to users.
# New model's predictions are LOGGED BUT NOT SERVED.
# Compare prediction distributions offline before go-live.
# Zero risk to users. Best practice for high-stakes models.
#
# Implementation: middleware layer that:
#   1. Calls model_v1 → return response immediately.
#   2. Asynchronously calls model_v2 → log output to DB.
#   3. Analyst compares v1 vs v2 distributions daily.

class ShadowPredictor:
    """
    Routes requests to both old and new models.
    Serves old model's predictions; logs new model's for comparison.
    """
    def __init__(self, production_model, shadow_model, logger=None):
        self.production = production_model
        self.shadow = shadow_model
        self.logger = logger or (lambda x: None)

    def predict(self, X: np.ndarray, request_id: str) -> np.ndarray:
        # Always serve production model
        prod_pred = self.production.predict(X)

        # Fire shadow prediction asynchronously (don't slow down response)
        import threading
        def shadow_call():
            try:
                shadow_pred = self.shadow.predict(X)
                self.logger({
                    'request_id': request_id,
                    'timestamp': datetime.utcnow().isoformat(),
                    'prod_pred': prod_pred.tolist(),
                    'shadow_pred': shadow_pred.tolist(),
                })
            except Exception as e:
                pass  # never let shadow failures affect production

        threading.Thread(target=shadow_call, daemon=True).start()
        return prod_pred

# ============================================================
# SECTION 10: Drift Monitoring — PSI and Concept Drift
# ============================================================
# Data drift: input feature distribution shifts over time.
#   Cause: seasonality, population change, data pipeline bug.
#   Detection: Population Stability Index (PSI) per feature.
#
# PSI formula:
#   For each bin i: PSI_i = (actual% - expected%) * ln(actual% / expected%)
#   Total PSI = sum of PSI_i
#   PSI < 0.1:  stable (no action needed)
#   PSI 0.1-0.2: moderate shift (investigate)
#   PSI > 0.2:  major shift (retrain or alert)
#
# Concept drift: relationship between features and target changes.
#   Requires ground truth labels (often delayed by days/weeks).
#   Detection: monitor model performance on recent labeled data.
#
# Prediction drift: model's output distribution shifts.
#   Easier to detect (no labels needed). Symptom of data drift.
#   Monitor: mean score, score histogram, percentiles (p10, p50, p90).

def compute_psi(expected: np.ndarray, actual: np.ndarray,
                 n_bins: int = 10, epsilon: float = 1e-8) -> float:
    """
    Compute Population Stability Index between expected and actual distributions.
    expected: reference distribution (training data).
    actual:   current distribution (live data).
    Returns scalar PSI value.
    """
    # Bin edges from expected distribution
    bins = np.percentile(expected, np.linspace(0, 100, n_bins + 1))
    bins[0]  -= epsilon  # include min value
    bins[-1] += epsilon  # include max value

    expected_counts = np.histogram(expected, bins=bins)[0]
    actual_counts   = np.histogram(actual,   bins=bins)[0]

    expected_pct = expected_counts / len(expected) + epsilon
    actual_pct   = actual_counts   / len(actual)   + epsilon

    psi = np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct))
    return float(psi)


def monitor_all_features(X_train: pd.DataFrame, X_live: pd.DataFrame,
                           numeric_cols: list) -> dict:
    """Compute PSI for all numeric features. Alert on high values."""
    results = {}
    for col in numeric_cols:
        psi = compute_psi(
            X_train[col].dropna().values,
            X_live[col].dropna().values,
        )
        status = 'stable' if psi < 0.1 else ('warning' if psi < 0.2 else 'alert')
        results[col] = {'psi': psi, 'status': status}
        if status == 'alert':
            print(f"ALERT: {col} PSI={psi:.3f} — major drift detected!")
    return results

# ============================================================
# SECTION 11: SHAP Values — Explainability
# ============================================================
# SHAP (SHapley Additive exPlanations): each prediction is
# explained as a sum of feature contributions.
# Grounded in game theory (Shapley values from cooperative game theory).
#
# Properties:
#   - Consistent: if a feature's true importance increases, SHAP
#     value for that feature never decreases.
#   - Locally accurate: base_value + sum(shap_values) = prediction.
#   - Handles correlated features better than permutation importance.
#
# Explainers:
#   TreeExplainer: for tree models (XGB, LightGBM, RF).
#     Fast (polynomial time). Most accurate for trees.
#   LinearExplainer: for linear models (LR, Ridge, Lasso).
#     Closed-form. Fast.
#   DeepExplainer: for neural networks. Uses DeepLIFT algorithm.
#   KernelExplainer: model-agnostic. Slow. Use as last resort.
#
# When SHAP is REQUIRED (not optional):
#   - Regulated industries: EU AI Act, fair lending (ECOA/FCRA),
#     insurance (state regulations), healthcare (FDA guidance).
#   - Customer-facing explanations: "why was my loan denied?"
#   - Debugging: "why does the model score this customer so high?"

def explain_predictions_shap(model, X: pd.DataFrame, n_background=100):
    """
    Generate SHAP explanations for XGBoost/sklearn tree model.
    Returns shap_values matrix of shape (n_samples, n_features).
    """
    import shap

    # TreeExplainer: exact SHAP values for tree models, very fast
    explainer = shap.TreeExplainer(
        model,
        feature_perturbation='tree_path_dependent',  # handles missing values
    )

    # shap_values: (n_samples, n_features)
    shap_values = explainer(X)
    return shap_values


def explain_single_prediction(shap_values, idx: int, feature_names: list):
    """Print the SHAP explanation for one prediction."""
    import shap
    # Waterfall plot: shows base value + each feature's +/- contribution
    # shap.waterfall_plot(shap_values[idx])

    vals = shap_values[idx].values
    ranked = sorted(zip(feature_names, vals), key=lambda x: abs(x[1]), reverse=True)
    print(f"Base value: {shap_values[idx].base_values:.4f}")
    print(f"Prediction: {shap_values[idx].base_values + vals.sum():.4f}")
    print("\nTop contributing features:")
    for feat, val in ranked[:10]:
        direction = '+' if val > 0 else '-'
        print(f"  {direction}{abs(val):.4f}  {feat}")

# ============================================================
# SECTION 12: Retraining Triggers
# ============================================================
# Three retraining strategies (from simplest to most complex):
#
# 1. Scheduled: retrain on a fixed cadence (weekly, monthly).
#    Simple, predictable. Doesn't adapt to sudden changes.
#    Good baseline for stable domains.
#
# 2. Drift-detected: PSI > 0.2 on a key feature triggers
#    a retraining job. Responds to actual data changes.
#    Requires robust drift monitoring pipeline.
#
# 3. Performance-degraded: if model accuracy on recent labeled
#    data drops below threshold, alert + retrain.
#    Most accurate signal but requires fresh labels (delayed).
#
# Full retraining pipeline steps:
#   trigger → load_new_data → feature_engineering →
#   train → evaluate_on_holdout → if_better: register →
#   deploy_to_staging → A/B_test → promote_to_production

def should_retrain(psi_results: dict, psi_threshold: float = 0.2,
                   performance_metric: Optional[float] = None,
                   performance_threshold: Optional[float] = None) -> tuple:
    """
    Decide whether to trigger retraining.
    Returns (should_retrain: bool, reason: str).
    """
    # Check drift
    high_drift_features = [
        col for col, v in psi_results.items() if v['psi'] >= psi_threshold
    ]
    if high_drift_features:
        return True, f"Drift alert on: {high_drift_features}"

    # Check performance (if labels available)
    if performance_metric is not None and performance_threshold is not None:
        if performance_metric < performance_threshold:
            return True, f"Performance dropped: {performance_metric:.4f} < {performance_threshold}"

    return False, "No retraining needed"

# ============================================================
# SECTION 13: Full ML Lifecycle Summary
# ============================================================
# Stage 1: Problem definition
#   - Define primary business metric (not just ML metric).
#   - Collect labeled data. Define ground truth carefully.
#   - Baseline: random, rule-based, or simple heuristic.
#
# Stage 2: Feature engineering
#   - Write feature logic in shared FeatureComputer class.
#   - Unit test every feature computation function.
#   - Store feature statistics from training for monitoring.
#
# Stage 3: Training + evaluation
#   - Train on data with time cutoff (no future leakage).
#   - Cross-validate on held-out time window.
#   - Log experiment: hyperparams, metrics, artifacts → MLflow.
#
# Stage 4: Export + optimize
#   - ONNX export with dynamic axes.
#   - Dynamic quantization to int8.
#   - Verify: torch vs ONNX output np.allclose(atol=1e-5).
#
# Stage 5: Serving
#   - FastAPI loads ONNX at startup.
#   - Shadow deployment: run new model in parallel for 1 week.
#   - Compare prediction distributions vs production.
#
# Stage 6: A/B test
#   - Route 10% traffic to new model.
#   - Power analysis: required sample size for desired effect size.
#   - Run until significance. Ship or rollback.
#
# Stage 7: Monitoring
#   - PSI on every input feature, daily.
#   - Prediction distribution (mean, p10, p50, p90), daily.
#   - Performance metrics on labeled slice, weekly.
#   - Alert: PSI > 0.2 or performance drop > 5%.
#
# Stage 8: Retraining
#   - Triggered by drift or performance degradation.
#   - Automatic pipeline: fetch data → train → evaluate →
#     if AUC > production model: register + deploy to staging.
#   - Requires human sign-off before production promotion
#     (or full auto for high-frequency, low-stakes models).

LIFECYCLE_CHECKLIST = {
    'training': [
        'feature logic in shared module (no skew)',
        'time-aware train/val split',
        'cross-validation results logged',
        'hyperparams logged to MLflow',
        'model metadata: git_sha + dataset_version + metrics',
    ],
    'export': [
        'ONNX exported with dynamic_axes',
        'quantized to int8',
        'ONNX output verified vs PyTorch (atol=1e-5)',
        'model registered in MLflow registry',
    ],
    'serving': [
        'model loaded at startup (not per request)',
        'request validation (pydantic schema)',
        'response includes prediction + model_version',
        'latency logged per request (p50, p95, p99)',
        'shadow deployment before A/B',
    ],
    'monitoring': [
        'PSI computed daily on all input features',
        'prediction distribution logged daily',
        'alert rules configured (PSI > 0.2)',
        'SHAP explanations available for auditing',
    ],
    'retraining': [
        'retrain triggers defined (drift + schedule + performance)',
        'retrain pipeline automated (not manual)',
        'hold-out evaluation before promoting',
        'rollback procedure documented and tested',
    ],
}
