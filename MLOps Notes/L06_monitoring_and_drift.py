# ============================================================
# L06: ML Monitoring and Drift Detection
# ============================================================
# WHAT: ML monitoring is the practice of continuously measuring the health
#       of a production model — its inputs, outputs, and performance over
#       time. Drift detection identifies when the statistical properties
#       of incoming data or model behavior diverge from the training baseline.
# WHY:  Software either works or it doesn't — you get exceptions. ML models
#       silently degrade. A model trained on January data can perform poorly
#       on December data with zero errors in your logs. Monitoring IS the
#       hardest part of production ML, and the most commonly skipped.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    ML models degrade for two reasons: the world changes (data drift,
    concept drift) or the data pipeline breaks (data quality issues).
    Neither produces exceptions. You must proactively measure the
    distribution of inputs and outputs vs. a known-good baseline
    (usually the training data). Statistical tests quantify whether
    a shift is significant. The key challenge: ground truth (labels)
    arrives hours or days after predictions, so you cannot always
    compute live accuracy.

PRODUCTION USE CASE:
    A credit risk model at a bank: during COVID, consumer spending patterns
    shifted dramatically. The model's input features (spending categories,
    average transaction amount) drifted from the 2019 training distribution.
    PSI spiked above 0.25 on five features within two weeks of lockdowns
    starting. The monitoring system fired a PagerDuty alert; the team
    retrained on 90 days of recent data and restored performance. Without
    drift monitoring, the degradation would have gone unnoticed for months.

COMMON MISTAKES:
    1. Only monitoring system metrics (CPU, latency) and not model metrics
       (prediction distribution, feature distributions, performance).
    2. Using the wrong test — KS test on a highly categorical variable,
       or PSI on a variable with only 3 unique values.
    3. Setting drift alerts too sensitive — 10 alerts per day = alert
       fatigue = alerts ignored. Tune thresholds on historical data.
    4. No ground truth pipeline — if you never join predictions with
       outcomes, you can detect drift but not measure accuracy decay.
    5. Treating all drift equally — drifted features that are NOT in
       the model don't matter. Focus on features with high feature importance.
"""

import numpy as np
import pandas as pd
from scipy import stats
from scipy.spatial.distance import jensenshannon
from typing import Dict, List, Tuple, Optional
import logging
import warnings

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

# ============================================================
# SECTION 1: TYPES OF DRIFT — TAXONOMY
# ============================================================
#
# DATA DRIFT (Covariate Shift):
#   P(X) changes but P(Y|X) stays the same.
#   Example: your fraud model was trained on mostly US transactions.
#   Now 40% of requests come from EU (different spending patterns).
#   The RELATIONSHIP between features and fraud hasn't changed,
#   but the feature DISTRIBUTION has. May or may not hurt performance.
#
# CONCEPT DRIFT:
#   P(Y|X) changes — what the features MEAN for the target has changed.
#   Example: "large transaction" used to signal fraud (2019).
#   Post-COVID, large grocery transactions are normal. Same features,
#   different relationship to fraud. Performance degrades significantly.
#   Hardest to detect without ground truth labels.
#
# LABEL SHIFT (Prior Probability Shift):
#   P(Y) changes but P(X|Y) stays the same.
#   Example: fraud rate drops from 2% to 0.5% after a security crackdown.
#   Same fraud patterns, just less of them. Model's predicted fraud rate
#   stays around 2% — it's systematically over-predicting fraud.
#
# UPSTREAM DATA DRIFT:
#   A data pipeline change alters feature values without changing
#   what they represent. Example: currency changed from USD to EUR
#   in the upstream system — feature values drop by ~10%.
#   This is an engineering bug, not a real-world shift. Looks identical
#   to data drift in metrics — root cause analysis is required.

# ============================================================
# SECTION 2: POPULATION STABILITY INDEX (PSI)
# ============================================================
# PSI is the most widely used drift metric in industry, especially
# in finance. It measures how much the distribution of a variable
# has shifted between a reference (training) and current (production)
# population.
#
# Formula: PSI = Σ (actual_pct_i - expected_pct_i) × ln(actual_pct_i / expected_pct_i)
#   where i = each bucket (typically 10-20 equal-frequency bins from training data)
#
# Interpretation:
#   PSI < 0.10  → No significant change. Model is stable.
#   0.10–0.20   → Moderate change. Monitor closely. Investigate cause.
#   PSI > 0.20  → Significant shift. Investigate. Likely need to retrain.
#
# PSI > 0.25 is commonly the alert threshold for automatic retraining trigger.


def compute_psi(reference: np.ndarray, current: np.ndarray,
                n_bins: int = 10, eps: float = 1e-6) -> float:
    """
    Compute Population Stability Index between reference and current distributions.

    Args:
        reference: 1-D array of values from training/baseline period.
        current:   1-D array of values from current production period.
        n_bins:    Number of bins. 10-20 is standard. More bins = more sensitive.
        eps:       Small value added to avoid log(0). Standard practice.

    Returns:
        PSI value. Higher = more drift.
    """
    # Create bin edges from the REFERENCE distribution (equal-frequency bins)
    # Why equal-frequency (quantile-based)? So each bin has roughly equal
    # expected count, making PSI comparable across variables with different scales.
    quantiles = np.linspace(0, 100, n_bins + 1)
    bin_edges = np.percentile(reference, quantiles)
    bin_edges[0] = -np.inf    # capture all values below min reference
    bin_edges[-1] = np.inf    # capture all values above max reference

    # Count observations per bin (normalize to proportions)
    ref_counts, _ = np.histogram(reference, bins=bin_edges)
    cur_counts, _ = np.histogram(current, bins=bin_edges)

    ref_pct = ref_counts / len(reference)
    cur_pct = cur_counts / len(current)

    # Add epsilon to avoid log(0) or division by zero in empty bins
    ref_pct = np.where(ref_pct == 0, eps, ref_pct)
    cur_pct = np.where(cur_pct == 0, eps, cur_pct)

    # PSI formula
    psi = np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct))
    return float(psi)


def interpret_psi(psi: float) -> str:
    """Return human-readable interpretation of a PSI value."""
    if psi < 0.10:
        return "STABLE (no significant change)"
    elif psi < 0.20:
        return "MODERATE drift — monitor closely"
    else:
        return "SIGNIFICANT drift — investigate and consider retraining"


# ============================================================
# SECTION 3: KOLMOGOROV-SMIRNOV TEST
# ============================================================
# KS test measures the maximum distance between two empirical CDFs.
# Better than PSI for: detecting shape changes (not just mean shifts),
# small samples, and when you don't want to commit to a binning strategy.
# Returns a test statistic and p-value.
# p < 0.05 → distributions are significantly different (reject H0).


def ks_drift_test(reference: np.ndarray, current: np.ndarray,
                  alpha: float = 0.05) -> dict:
    """
    Two-sample Kolmogorov-Smirnov test for distributional equality.

    Args:
        reference: baseline data (training distribution)
        current:   production data (current distribution)
        alpha:     significance level (default 0.05 = 95% confidence)

    Returns:
        dict with statistic, p_value, and whether drift was detected
    """
    statistic, p_value = stats.ks_2samp(reference, current)
    drift_detected = p_value < alpha
    return {
        "test": "Kolmogorov-Smirnov",
        "statistic": float(statistic),
        "p_value": float(p_value),
        "alpha": alpha,
        "drift_detected": drift_detected,
        "interpretation": "Distributions differ significantly" if drift_detected
                          else "No significant difference detected",
    }


# ============================================================
# SECTION 4: CHI-SQUARED TEST (CATEGORICAL VARIABLES)
# ============================================================
# For categorical features: test whether the observed category counts
# match the expected (baseline) proportions.
# H0: observed proportions match expected proportions.
# p < 0.05 → category distribution has significantly shifted.


def chi_squared_drift_test(reference_counts: Dict[str, int],
                           current_counts: Dict[str, int],
                           alpha: float = 0.05) -> dict:
    """
    Chi-squared goodness-of-fit test for categorical drift.

    Args:
        reference_counts: dict of {category: count} from training data
        current_counts:   dict of {category: count} from production data
        alpha: significance level

    Returns:
        dict with test result and interpretation
    """
    # Align categories — both dicts must have same keys
    all_cats = sorted(set(reference_counts) | set(current_counts))
    ref_vals = np.array([reference_counts.get(c, 0) for c in all_cats], dtype=float)
    cur_vals = np.array([current_counts.get(c, 0) for c in all_cats], dtype=float)

    # Normalize reference to expected proportions for current total
    ref_proportions = ref_vals / ref_vals.sum()
    expected = ref_proportions * cur_vals.sum()

    # Chi-squared requires expected >= 5 per cell (merge rare categories if needed)
    statistic, p_value = stats.chisquare(f_obs=cur_vals, f_exp=expected)
    drift_detected = p_value < alpha

    return {
        "test": "Chi-Squared",
        "categories": all_cats,
        "statistic": float(statistic),
        "p_value": float(p_value),
        "drift_detected": drift_detected,
    }


# ============================================================
# SECTION 5: JENSEN-SHANNON DIVERGENCE
# ============================================================
# JS divergence is a symmetric version of KL divergence.
# KL divergence is not symmetric: KL(P||Q) ≠ KL(Q||P).
# JS divergence is always finite and always between 0 and 1 (when using log2).
# 0 = identical distributions, 1 = completely different distributions.
# Works on both continuous (after binning) and discrete distributions.
# scipy returns the SQUARE ROOT of JS divergence (the JS distance).


def js_divergence(reference: np.ndarray, current: np.ndarray,
                  n_bins: int = 20) -> float:
    """
    Jensen-Shannon divergence between reference and current distributions.
    Input arrays are binned into a discrete probability distribution first.

    Returns:
        JS divergence in [0, 1]. > 0.1 generally indicates notable drift.
    """
    # Bin both using the same edges (from reference)
    bin_edges = np.histogram_bin_edges(reference, bins=n_bins)
    ref_hist, _ = np.histogram(reference, bins=bin_edges, density=True)
    cur_hist, _ = np.histogram(current, bins=bin_edges, density=True)

    # Normalize to probability distributions (avoid zero division)
    eps = 1e-10
    ref_prob = (ref_hist + eps) / (ref_hist + eps).sum()
    cur_prob = (cur_hist + eps) / (cur_hist + eps).sum()

    # jensenshannon returns the DISTANCE (sqrt of divergence)
    # Square it to get true JS divergence
    js_distance = jensenshannon(ref_prob, cur_prob, base=2)
    return float(js_distance ** 2)  # JS divergence (not distance)


# ============================================================
# SECTION 6: EVIDENTLY AI — PRODUCTION DRIFT REPORTS
# ============================================================
# Evidently is the leading open-source ML monitoring library.
# Generates reports and test suites for data/model quality.
# Can run as: one-off HTML report, scheduled batch job, or REST API.

# from evidently.report import Report
# from evidently.metric_preset import (
#     DataDriftPreset,        # per-feature drift + dataset-level drift
#     TargetDriftPreset,      # prediction/target distribution drift
#     DataQualityPreset,      # missing values, out-of-range, duplicates
#     ClassificationPreset,   # accuracy, precision, recall, AUC (needs labels)
#     RegressionPreset,       # RMSE, MAE, R2 (needs labels)
# )
# from evidently.test_suite import TestSuite
# from evidently.tests import TestNumberOfDriftedColumns, TestShareOfDriftedColumns
#
# # Reference = training data (baseline)
# # Current   = last 7 days of production data (features logged at serve time)
#
# report = Report(metrics=[
#     DataDriftPreset(drift_share=0.3),    # alert if >30% of columns drift
#     DataQualityPreset(),
# ])
# report.run(reference_data=train_df, current_data=prod_df)
# report.save_html("drift_report_2024_06_01.html")  # viewable in browser
#
# TEST SUITE — returns PASS/FAIL instead of a descriptive report:
# suite = TestSuite(tests=[
#     TestShareOfDriftedColumns(lt=0.3),   # < 30% columns drifted
#     TestNumberOfDriftedColumns(lt=5),    # < 5 columns drifted
# ])
# suite.run(reference_data=train_df, current_data=prod_df)
# result = suite.as_dict()
# if not result["summary"]["all_passed"]:
#     trigger_retraining_pipeline()

# ============================================================
# SECTION 7: PROMETHEUS METRICS FOR ML MONITORING
# ============================================================
# Prometheus is the standard metrics system in K8s. Expose ML-specific
# metrics from your model server. Grafana visualizes them.
# AlertManager fires alerts when thresholds are crossed.

# from prometheus_client import Counter, Histogram, Gauge, start_http_server
#
# # Request counter — broken down by model version and prediction bucket
# prediction_requests = Counter(
#     "model_prediction_requests_total",
#     "Total number of prediction requests",
#     ["model_version", "outcome"],  # outcome: success, error, circuit_open
# )
#
# # Latency histogram — track P50, P95, P99 automatically
# prediction_latency = Histogram(
#     "model_prediction_latency_seconds",
#     "Prediction request latency in seconds",
#     ["model_version"],
#     buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
# )
#
# # Prediction score distribution — track how the model's output shifts
# # Use a Histogram, not a Gauge, to track distribution (not just last value)
# prediction_score = Histogram(
#     "model_prediction_score",
#     "Distribution of prediction scores",
#     ["model_version"],
#     buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
# )
#
# # Feature value histograms — detect drift in real time
# feature_amount = Histogram(
#     "feature_amount_usd",
#     "Distribution of transaction amount feature",
#     buckets=[10, 50, 100, 200, 500, 1000, 5000, 10000],
# )
#
# # Usage in request handler:
# def predict_with_metrics(features, model_version="v1"):
#     with prediction_latency.labels(model_version).time():
#         try:
#             score = model.predict(features)
#             prediction_requests.labels(model_version, "success").inc()
#             prediction_score.labels(model_version).observe(score)
#             feature_amount.observe(features["amount"])
#             return score
#         except Exception as e:
#             prediction_requests.labels(model_version, "error").inc()
#             raise

# ============================================================
# SECTION 8: GROUND TRUTH COLLECTION AND DELAYED LABELS
# ============================================================
# The hardest part of production ML monitoring: you need labels to
# compute accuracy, but labels often arrive AFTER predictions.
#
# PATTERN: Store prediction + request_id + timestamp at serve time.
#          Store ground truth + request_id when it arrives.
#          JOIN on request_id to compute accuracy over a window.
#
# Example for a fraud detection system:
#   At serve time:  predictions_store[request_id] = {score, features, timestamp}
#   After 7 days:   fraud_labels_store[request_id] = {is_fraud, confirmed_at}
#   Daily job:      JOIN predictions with labels where label_age > 7 days
#                   Compute AUC, precision, recall on joined set
#                   If AUC < threshold: trigger alert
#
# LABEL SOURCES BY DOMAIN:
#   Fraud:         chargeback confirmation (7-30 day delay)
#   Recommendations: click/purchase (minutes to hours)
#   Credit risk:   default event (30-90 day delay)
#   Churn:         cancellation event (days to weeks)
#   NLP (spam):    human review or user report (hours to days)

# ============================================================
# SECTION 9: RETRAINING TRIGGERS
# ============================================================
# When to retrain? Four strategies, often used in combination:
#
# 1. TIME-BASED:   Retrain every N days (weekly, monthly).
#    Pros: simple, predictable, easy to schedule.
#    Cons: retrains even when not needed (waste), doesn't react fast enough.
#
# 2. DRIFT-BASED:  PSI > threshold triggers retraining pipeline.
#    Pros: reacts to actual change, not arbitrary schedule.
#    Cons: drift doesn't always cause performance degradation.
#           Feature drift on unimportant features triggers unnecessary runs.
#    Best practice: only trigger on drift of top-N most important features.
#
# 3. PERFORMANCE-BASED: If accuracy/AUC drops below threshold → retrain.
#    Pros: most direct signal (performance is what you care about).
#    Cons: requires labeled data (delayed labels), reactive not proactive.
#
# 4. DATA VOLUME:  Retrain when N new labeled examples accumulate.
#    Pros: ensures training set grows with data.
#    Cons: doesn't account for data quality or distribution shift.
#
# RECOMMENDED: Time-based as a safety net + Drift-based for fast reaction.
#              Add performance-based monitoring as a lagging sanity check.

# ============================================================
# SECTION 10: COMPLETE DAILY DRIFT MONITORING JOB
# ============================================================

class DriftMonitor:
    """
    Runs daily to compare recent production data against training baseline.
    Computes PSI per feature, logs to Prometheus, fires Slack alert if needed.
    Designed to run as an Airflow PythonOperator or Prefect @task.
    """

    PSI_WARN_THRESHOLD = 0.10
    PSI_ALERT_THRESHOLD = 0.20
    PSI_CRITICAL_THRESHOLD = 0.25

    def __init__(self, feature_cols: List[str],
                 important_features: Optional[List[str]] = None):
        """
        Args:
            feature_cols: all feature column names to monitor
            important_features: subset to trigger retraining alerts on.
                If None, all features are considered important.
        """
        self.feature_cols = feature_cols
        self.important_features = important_features or feature_cols

    def run(self, baseline_df: pd.DataFrame, current_df: pd.DataFrame) -> dict:
        """
        Compare current production data to baseline.
        Returns dict of {feature: {psi, ks_p_value, drift_level}}.
        """
        results = {}
        critical_features = []

        for col in self.feature_cols:
            if col not in baseline_df.columns or col not in current_df.columns:
                logger.warning(f"Column {col} not found in data. Skipping.")
                continue

            ref = baseline_df[col].dropna().values
            cur = current_df[col].dropna().values

            if len(ref) < 30 or len(cur) < 30:
                logger.warning(f"Insufficient data for {col}. "
                               f"ref={len(ref)}, cur={len(cur)}")
                continue

            psi = compute_psi(ref, cur)
            ks_result = ks_drift_test(ref, cur)

            drift_level = "OK"
            if psi >= self.PSI_CRITICAL_THRESHOLD:
                drift_level = "CRITICAL"
            elif psi >= self.PSI_ALERT_THRESHOLD:
                drift_level = "ALERT"
            elif psi >= self.PSI_WARN_THRESHOLD:
                drift_level = "WARN"

            results[col] = {
                "psi": round(psi, 4),
                "ks_statistic": round(ks_result["statistic"], 4),
                "ks_p_value": round(ks_result["p_value"], 4),
                "drift_level": drift_level,
                "is_important_feature": col in self.important_features,
            }

            logger.info(
                f"[DRIFT] {col}: PSI={psi:.4f} [{drift_level}], "
                f"KS p={ks_result['p_value']:.4f}"
            )

            if drift_level in ("ALERT", "CRITICAL") and col in self.important_features:
                critical_features.append(col)

        # Summary
        n_drifted = sum(1 for r in results.values() if r["drift_level"] != "OK")
        summary = {
            "total_features": len(results),
            "drifted_features": n_drifted,
            "critical_features": critical_features,
            "should_retrain": len(critical_features) > 0,
            "feature_results": results,
        }

        if summary["should_retrain"]:
            self._fire_alert(critical_features)

        return summary

    def _fire_alert(self, critical_features: List[str]):
        """
        In production: POST to Slack webhook, PagerDuty, or AlertManager.
        Here we log — the actual alert mechanism is configurable.
        """
        msg = (
            f"[ML DRIFT ALERT] Significant drift detected in "
            f"{len(critical_features)} important feature(s): "
            f"{critical_features}. Retraining pipeline triggered."
        )
        logger.critical(msg)
        # In production:
        # requests.post(SLACK_WEBHOOK, json={"text": msg})
        # trigger_retraining_pipeline()


# ============================================================
# DEMONSTRATION
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    rng = np.random.default_rng(seed=42)

    # Simulate baseline (training) data
    baseline = pd.DataFrame({
        "amount": rng.exponential(100, size=5000),
        "hour":   rng.integers(0, 24, size=5000).astype(float),
        "freq_7d": rng.integers(1, 30, size=5000).astype(float),
    })

    # Simulate current data with drift on 'amount' (COVID-like shift)
    drifted_rng = np.random.default_rng(seed=99)
    current = pd.DataFrame({
        "amount": drifted_rng.exponential(350, size=1000),  # 3.5x larger amounts
        "hour":   drifted_rng.integers(0, 24, size=1000).astype(float),  # stable
        "freq_7d": drifted_rng.integers(1, 30, size=1000).astype(float),  # stable
    })

    # PSI per feature
    print("=== PSI Analysis ===")
    for col in ["amount", "hour", "freq_7d"]:
        psi = compute_psi(baseline[col].values, current[col].values)
        print(f"  {col}: PSI={psi:.4f} — {interpret_psi(psi)}")

    # KS test
    print("\n=== KS Test (amount) ===")
    ks = ks_drift_test(baseline["amount"].values, current["amount"].values)
    print(f"  statistic={ks['statistic']:.4f}, p={ks['p_value']:.6f}, "
          f"drift={ks['drift_detected']}")

    # JS divergence
    print("\n=== Jensen-Shannon Divergence (amount) ===")
    js = js_divergence(baseline["amount"].values, current["amount"].values)
    print(f"  JS divergence={js:.4f}")

    # Full monitoring run
    print("\n=== Full Drift Monitor Run ===")
    monitor = DriftMonitor(
        feature_cols=["amount", "hour", "freq_7d"],
        important_features=["amount", "freq_7d"],
    )
    summary = monitor.run(baseline, current)
    print(f"\n  Drifted features: {summary['drifted_features']} / "
          f"{summary['total_features']}")
    print(f"  Should retrain:   {summary['should_retrain']}")
    print(f"  Critical:         {summary['critical_features']}")

# ============================================================
# KEY TAKEAWAYS
# ============================================================
# - ML degrades silently. Monitoring is mandatory, not optional.
# - PSI is the industry standard for continuous feature drift.
#   PSI > 0.20 = significant shift. > 0.25 = trigger retraining.
# - Use KS test for continuous variables (shape-sensitive),
#   chi-squared for categorical variables.
# - Monitor ONLY important features for retraining triggers — drifted
#   low-importance features don't hurt model performance.
# - Ground truth collection is the hardest piece. Build the label
#   pipeline on day one, before you need it in an incident.
# - Combine time-based retraining (safety net) with drift-based
#   retraining (fast reaction) for robust coverage.
