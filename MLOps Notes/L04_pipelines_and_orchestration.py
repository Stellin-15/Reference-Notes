# ============================================================
# L04: ML Pipelines and Orchestration
# ============================================================
# WHAT: A pipeline is a sequence of reproducible, parameterized steps
#       that transform raw data into a deployed model (training pipeline)
#       or that apply a trained model to new data (inference pipeline).
#       Both must be versioned, testable, and reproducible.
# WHY:  Without pipelines you have a Jupyter notebook that "only works
#       on my machine." Pipelines are the engineering backbone of MLOps —
#       they make ML reproducible, automatable, and production-grade.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    An ML pipeline replaces ad-hoc notebook workflows with a structured
    graph of steps. Each step has explicit inputs, outputs, and parameters.
    The pipeline engine handles scheduling, retries, dependency resolution,
    and logging. Two pipeline families exist: training pipelines (data →
    model) and inference pipelines (request → prediction). Both are
    first-class citizens in MLOps — inference bugs are just as dangerous
    as training bugs.

PRODUCTION USE CASE:
    A fintech company runs a daily fraud detection retraining pipeline:
    Airflow triggers at 02:00 UTC → pulls last 30 days of transactions
    (feature engineering via Spark) → trains XGBoost model → evaluates
    on held-out set → if AUC > 0.87 registers to MLflow → triggers
    K8s rolling deploy. The whole thing is parameterized, retried on
    failure, and every step emits metrics to Grafana.

COMMON MISTAKES:
    1. Passing large data through XCom / task parameters — use a data
       store (S3, GCS) and pass only paths/URIs between steps.
    2. No idempotency — re-running a failed pipeline appends duplicate
       data or trains on wrong dataset. Every step should be safe to retry.
    3. Hardcoding hyperparameters or dataset paths inside pipeline code
       instead of accepting them as run-time parameters.
    4. No versioning of the pipeline itself — you lose track of which
       code produced which model.
    5. Skipping data validation — a broken upstream feed silently poisons
       the next model without a validation step to catch it.
"""

# ============================================================
# SECTION 1: WHAT MAKES A GOOD PIPELINE
# ============================================================

# Five properties every ML pipeline must have:
#
# 1. PARAMETERIZED  — experiment config (hyperparams, dataset version,
#                     date range) passed at run-time, not hardcoded.
# 2. VERSIONED      — git SHA of code + data version tracked per run.
# 3. IDEMPOTENT     — safe to re-run without producing duplicate results.
# 4. OBSERVABLE     — every step emits logs + metrics; failures are loud.
# 5. TESTABLE       — each component can be unit-tested independently.

# ============================================================
# SECTION 2: APACHE AIRFLOW FOR ML
# ============================================================
# Airflow is a general-purpose workflow scheduler that has become common
# in data/ML teams. It models pipelines as DAGs (Directed Acyclic Graphs).
# Strengths: mature ecosystem, excellent scheduling, retries, SLAs,
# dependency management. Weaknesses: not ML-aware, local dev is painful,
# XCom (inter-task communication) breaks down with large data.

from datetime import datetime, timedelta

# --- Airflow DAG example ---
# (import block — these run in an Airflow environment)
#
# from airflow import DAG
# from airflow.operators.python import PythonOperator
# from airflow.operators.bash import BashOperator
# from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator

# default_args control retry behaviour for every task in the DAG
default_args_example = {
    "owner": "ml-team",
    "retries": 2,                          # retry failed tasks twice
    "retry_delay": timedelta(minutes=5),   # wait 5 min between retries
    "email_on_failure": True,
    "email": ["ml-alerts@company.com"],
}

# XCom: Airflow's mechanism for passing small metadata between tasks.
# Push: task_instance.xcom_push(key="model_path", value="s3://bucket/model.pkl")
# Pull: ti.xcom_pull(task_ids="train_model", key="model_path")
# RULE: Only pass small values (paths, metrics, flags). Never pass DataFrames.

# Typical ML DAG task sequence:
#   feature_engineering (SparkSubmitOperator — runs Spark on EMR/Dataproc)
#     → train      (PythonOperator — calls training script)
#       → evaluate (PythonOperator — computes metrics, pushes to XCom)
#         → gate   (BranchPythonOperator — skip deploy if AUC < threshold)
#           → register_model
#             → trigger_deploy (BashOperator or TriggerDagRunOperator)

# ============================================================
# SECTION 3: METAFLOW (NETFLIX)
# ============================================================
# Metaflow was built BY data scientists FOR data scientists. It wraps
# Python classes with decorators that handle execution, versioning,
# and resumability. No YAML, no DAG configuration files — your flow
# IS the pipeline definition.

# Key advantages:
#   - Automatic versioning of code AND data artifacts per run
#   - Resume from any failed step without re-running completed steps
#   - Local execution → cloud execution (AWS Batch / K8s) with one flag
#   - @card decorator generates automatic HTML documentation for each step
#   - @conda / @pypi per-step dependency isolation

# from metaflow import FlowSpec, step, conda, card, Parameter, current

# class FraudDetectionFlow(FlowSpec):
#     """End-to-end training pipeline for fraud detection."""
#
#     # Parameters are passed at run time:
#     #   python flow.py run --test_size 0.2 --model_type xgboost
#     test_size = Parameter("test_size", default=0.2)
#     model_type = Parameter("model_type", default="xgboost")
#
#     @step
#     def start(self):
#         """Entry point — validate parameters and load config."""
#         print(f"Starting run {current.run_id}")
#         self.next(self.load_data)
#
#     @conda(libraries={"pandas": "2.0.0", "boto3": "1.26.0"})
#     @card   # generates a visual HTML card for this step in the Metaflow UI
#     @step
#     def load_data(self):
#         """Load raw data. Metaflow snapshots self.df as a versioned artifact."""
#         import pandas as pd
#         self.df = pd.read_parquet("s3://bucket/data/transactions.parquet")
#         self.next(self.feature_engineering)
#
#     @step
#     def feature_engineering(self):
#         """Transform raw features. Output self.X_train, self.X_test, etc."""
#         # ... feature logic ...
#         self.next(self.train)
#
#     @step
#     def train(self):
#         """Train model. self.model is a versioned artifact after this step."""
#         # ... training logic ...
#         self.next(self.evaluate)
#
#     @step
#     def evaluate(self):
#         self.auc = 0.91  # computed from actual evaluation
#         self.next(self.end)
#
#     @step
#     def end(self):
#         print(f"Run complete. AUC={self.auc:.4f}")
#
# Resuming after step 'train' fails:
#   python flow.py resume train
# This skips load_data and feature_engineering, re-runs only from train.

# ============================================================
# SECTION 4: KUBEFLOW PIPELINES (KFP)
# ============================================================
# Kubeflow Pipelines is Kubernetes-native. Each pipeline component runs
# inside a Docker container. This gives total environment isolation —
# your feature engineering step can use Python 3.8 + Spark while your
# training step uses Python 3.11 + PyTorch. The trade-off: more ops
# overhead. Vertex AI Pipelines is the fully-managed equivalent on GCP.

# import kfp
# from kfp import dsl
# from kfp.components import func_to_container_op

# @dsl.component(base_image="python:3.11", packages_to_install=["scikit-learn"])
# def train_component(
#     data_path: str,           # inputs are typed
#     model_output_path: Output[Model],   # outputs declared as Output[T]
#     n_estimators: int = 100,
# ):
#     """This function runs in a Docker container on K8s."""
#     from sklearn.ensemble import RandomForestClassifier
#     import joblib, pandas as pd
#     X_train = pd.read_parquet(data_path)
#     model = RandomForestClassifier(n_estimators=n_estimators)
#     # ... fit, save ...
#     joblib.dump(model, model_output_path.path)
#
# @dsl.pipeline(name="fraud-detection-pipeline")
# def fraud_pipeline(data_gcs_path: str, n_estimators: int = 100):
#     feat_task = feature_engineering_component(data_path=data_gcs_path)
#     train_task = train_component(
#         data_path=feat_task.outputs["output_path"],
#         n_estimators=n_estimators,
#     )
#     # Each task can set resource limits for its K8s pod:
#     train_task.set_memory_request("8Gi").set_cpu_request("4")
#
# KFP UI shows: run history, artifacts per step, metrics graphs, lineage.
# Reusable components can be shared via component YAML — published to a
# component registry and imported by other teams.

# ============================================================
# SECTION 5: SAGEMAKER PIPELINES (AWS)
# ============================================================
# Fully managed, no K8s to run. Tight integration with the SageMaker
# ecosystem: Feature Store, Experiments, Model Registry, Clarify.

# from sagemaker.workflow.pipeline import Pipeline
# from sagemaker.workflow.steps import ProcessingStep, TrainingStep, ConditionStep
# from sagemaker.workflow.conditions import ConditionGreaterThanOrEqualTo
# from sagemaker.workflow.parameters import ParameterFloat

# threshold = ParameterFloat(name="AucThreshold", default_value=0.85)
#
# step_process = ProcessingStep(...)     # feature engineering — runs on managed compute
# step_train   = TrainingStep(...)       # training job — SageMaker Training
# step_eval    = ProcessingStep(...)     # evaluation — computes metrics, writes JSON
#
# # Condition step: only register the model if AUC >= threshold
# cond = ConditionStep(
#     name="CheckAUC",
#     conditions=[ConditionGreaterThanOrEqualTo(
#         left=JsonGet(step_name=step_eval.name, property_file="evaluation.json",
#                      json_path="metrics.auc.value"),
#         right=threshold,
#     )],
#     if_steps=[step_register],   # promote to model registry
#     else_steps=[step_fail],     # fail pipeline visibly
# )

# ============================================================
# SECTION 6: PREFECT AND DAGSTER
# ============================================================

# PREFECT — modern Airflow alternative. Pure Python, no YAML.
# Tasks are regular Python functions with @task decorator.
# Flows are @flow decorated functions that call tasks.
# Easy local → Prefect Cloud transition. Dynamic DAGs supported.

# from prefect import flow, task
# from prefect.tasks import task_input_hash
# from datetime import timedelta

# @task(
#     retries=3,
#     retry_delay_seconds=60,
#     cache_key_fn=task_input_hash,       # cache result — skip if input unchanged
#     cache_expiration=timedelta(hours=1),
# )
# def load_data(date: str) -> pd.DataFrame:
#     return pd.read_parquet(f"s3://bucket/data/{date}.parquet")
#
# @task
# def validate_data(df: pd.DataFrame) -> pd.DataFrame:
#     assert df["label"].notna().all(), "Labels contain nulls"
#     assert len(df) > 10_000, f"Too few rows: {len(df)}"
#     return df
#
# @task
# def train_model(df: pd.DataFrame, params: dict) -> str:
#     # ... train, save, return artifact path ...
#     return "s3://bucket/models/model_20240601.pkl"
#
# @flow(name="fraud-training-pipeline")
# def training_pipeline(date: str, params: dict):
#     df = load_data(date)
#     df = validate_data(df)          # automatically uses result from load_data
#     model_path = train_model(df, params)
#     return model_path
#
# # Run locally:  training_pipeline(date="2024-06-01", params={"n_estimators": 200})
# # Deploy to cloud: prefect deploy → schedule via Prefect UI

# DAGSTER — asset-centric. Instead of "run this task," you declare
# "this asset should exist." Dagster figures out what to run to produce it.
# Strong typing between assets. Best-in-class lineage tracking.
# Trade-off: steeper learning curve, more opinionated.

# from dagster import asset, AssetIn
#
# @asset
# def raw_transactions() -> pd.DataFrame:
#     return pd.read_parquet("s3://bucket/raw/")
#
# @asset(ins={"raw_transactions": AssetIn()})
# def features(raw_transactions: pd.DataFrame) -> pd.DataFrame:
#     return engineer_features(raw_transactions)
#
# @asset(ins={"features": AssetIn()})
# def trained_model(features: pd.DataFrame) -> dict:
#     return {"auc": 0.91, "path": "s3://bucket/models/latest.pkl"}
#
# Dagster UI shows the asset graph — who depends on what,
# when each asset was last materialized, data quality checks.

# ============================================================
# SECTION 7: PIPELINE COMPONENT RESPONSIBILITIES
# ============================================================
# Each pipeline step should have ONE clear responsibility.
# Standard training pipeline steps:
#
#  Step 1: DATA INGESTION
#    - Pull raw data from source systems
#    - Record dataset version (git SHA of data pipeline, DVC hash, or
#      snapshot timestamp) as a run artifact
#
#  Step 2: DATA VALIDATION (Great Expectations, Deepchecks, Pandera)
#    - Schema validation: expected columns, types, value ranges
#    - Statistical validation: distribution checks vs baseline
#    - FAIL LOUDLY if data is bad — do not proceed to training
#
#  Step 3: FEATURE ENGINEERING
#    - Apply transformations: encode categoricals, scale numerics, etc.
#    - Store feature schema (column names + types) as artifact
#    - Output: train/val/test split on a versioned path
#
#  Step 4: TRAINING
#    - Accept hyperparameters as inputs (not hardcoded)
#    - Log all metrics + params to experiment tracker (MLflow/W&B)
#    - Save model artifact to cloud storage
#
#  Step 5: EVALUATION
#    - Compute hold-out metrics (AUC, F1, RMSE, etc.)
#    - Compare vs current production model (champion/challenger logic)
#    - GATE: if new model doesn't beat threshold → stop, do not register
#
#  Step 6: MODEL REGISTRATION (conditional on step 5 gate)
#    - Register model to registry with all metadata
#    - Link training run → model version (lineage)
#
#  Step 7: DEPLOYMENT TRIGGER
#    - Kick off deploy pipeline (separate concern)
#    - Blue/green or canary rollout
#    - Smoke test the deployed endpoint

# ============================================================
# SECTION 8: COMPLETE PREFECT TRAINING PIPELINE EXAMPLE
# ============================================================

import pandas as pd
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
import joblib
import logging

logger = logging.getLogger(__name__)


# --- Standalone implementations (no Prefect dependency) ---
# In production these would have @task decorators and @flow wrapper.

def load_data(date: str, data_path: str = "data/transactions.parquet") -> pd.DataFrame:
    """
    Load raw transaction data for a given date.
    Records the exact file path so the run is reproducible.
    In production: reads from S3/GCS, logs path to MLflow run.
    """
    logger.info(f"Loading data for date={date} from {data_path}")
    # Simulated — in production: pd.read_parquet(f"s3://bucket/data/{date}.parquet")
    rng = np.random.default_rng(seed=42)
    n = 5000
    df = pd.DataFrame({
        "amount": rng.exponential(scale=100, size=n),
        "hour":   rng.integers(0, 24, size=n),
        "freq_7d": rng.integers(1, 50, size=n),
        "label":  rng.integers(0, 2, size=n),  # 0=legit, 1=fraud
    })
    return df


def validate_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Assert data quality contracts before training.
    Raises ValueError if any check fails — pipeline stops here,
    not silently produces a garbage model.
    """
    required_cols = {"amount", "hour", "freq_7d", "label"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")
    if df["label"].isna().any():
        raise ValueError("Labels contain null values")
    if len(df) < 1000:
        raise ValueError(f"Insufficient data: only {len(df)} rows")
    logger.info(f"Data validation passed. Rows={len(df)}, "
                f"fraud_rate={df['label'].mean():.3f}")
    return df


def feature_engineering(df: pd.DataFrame) -> tuple:
    """
    Produce the final feature matrix and labels.
    The feature list is explicit — no 'select *' magic.
    This function should be the source of truth for feature names.
    """
    feature_cols = ["amount", "hour", "freq_7d"]
    X = df[feature_cols].values.astype(np.float32)
    y = df["label"].values
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    logger.info(f"Feature engineering done. Train={len(X_train)}, Test={len(X_test)}")
    return X_train, X_test, y_train, y_test, feature_cols


def train_model(X_train, y_train, params: dict):
    """
    Train model with given hyperparameters.
    Params are an explicit argument — logged to experiment tracker.
    """
    model = GradientBoostingClassifier(**params, random_state=42)
    model.fit(X_train, y_train)
    logger.info(f"Training complete with params={params}")
    return model


def evaluate_model(model, X_test, y_test, threshold: float = 0.85) -> dict:
    """
    Evaluate model and apply promotion gate.
    Returns metrics dict. Raises if below threshold — prevents
    a degraded model from reaching the registry.
    """
    y_prob = model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_prob)
    metrics = {"auc": auc, "threshold": threshold, "passed_gate": auc >= threshold}
    logger.info(f"Evaluation metrics: {metrics}")
    if auc < threshold:
        raise ValueError(
            f"Model AUC {auc:.4f} below threshold {threshold}. Not registering."
        )
    return metrics


def register_if_better(model, metrics: dict, model_name: str, run_id: str):
    """
    Register model to MLflow registry if it passed the evaluation gate.
    In production: mlflow.sklearn.log_model(..., registered_model_name=model_name)
    Also stores: training metrics, git SHA, data version, feature schema.
    """
    logger.info(
        f"Registering model '{model_name}' (run_id={run_id}, "
        f"AUC={metrics['auc']:.4f}) to registry."
    )
    # Simulate save
    joblib.dump(model, f"/tmp/{model_name}_v{run_id}.pkl")
    return f"/tmp/{model_name}_v{run_id}.pkl"


def run_training_pipeline(date: str, params: dict, model_name: str = "fraud_detector"):
    """
    Orchestrates the full training pipeline.
    In production each step is a @task; this function is a @flow.
    The @flow decorator in Prefect handles:
      - Automatic retry on step failure
      - Run history and status in Prefect Cloud UI
      - Passing results between tasks as futures
    """
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info(f"Starting training pipeline run_id={run_id}, date={date}")

    df = load_data(date)
    df = validate_data(df)
    X_train, X_test, y_train, y_test, feature_cols = feature_engineering(df)
    model = train_model(X_train, y_train, params)
    metrics = evaluate_model(model, X_test, y_test)
    model_path = register_if_better(model, metrics, model_name, run_id)

    logger.info(f"Pipeline complete. Model saved to {model_path}")
    return {"run_id": run_id, "metrics": metrics, "model_path": model_path}


# ============================================================
# DEMONSTRATION
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    config = {
        "date": "2024-06-01",
        "params": {"n_estimators": 150, "max_depth": 4, "learning_rate": 0.1},
        "model_name": "fraud_detector",
    }

    result = run_training_pipeline(
        date=config["date"],
        params=config["params"],
        model_name=config["model_name"],
    )
    print(f"\nPipeline result: {result}")

# ============================================================
# KEY TAKEAWAYS
# ============================================================
# - Choose orchestrator based on team: Metaflow (data scientists),
#   Airflow (data engineers), Kubeflow (K8s shops), SageMaker (AWS-native),
#   Prefect/Dagster (modern Python-first teams).
# - Always validate data BEFORE training — fail loudly, fail early.
# - Pass paths (not data) between steps. Store artifacts in object storage.
# - Parameterize everything. Run parameters are experiment config inputs.
# - Gate model registration on evaluation metrics — never auto-register
#   a model that didn't beat the baseline.
