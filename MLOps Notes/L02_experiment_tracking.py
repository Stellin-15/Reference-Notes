# ============================================================
# L02: Experiment Tracking
# ============================================================
# WHAT: Experiment tracking is the systematic logging of every ML run —
#       hyperparameters, metrics, artifacts, environment — so that any
#       experiment can be understood, reproduced, and compared retrospectively.
#       Think of it as "git for model training runs."
#
# WHY:  Without tracking, ML experimentation is unscientific. You cannot
#       know which hyperparameters produced the best model, whether today's
#       run is better than last week's, or what training data produced the
#       model currently in production. Tracking turns chaos into a searchable,
#       reproducible audit trail.
#
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    Experiment tracking captures the complete context of a training run:
    the inputs (parameters, data version, code version), the process
    (training duration, hardware), and the outputs (metrics, model artifact,
    visualizations). A good tracking system lets you answer "why does the
    model in production behave the way it does?" months after training.

PRODUCTION USE CASE:
    A fraud detection team runs 200 experiments over 2 months tuning an
    XGBoost model. The champion model (AUC=0.94) needs to be retrained
    6 months later after data drift. With MLflow tracking, they can retrieve
    the exact parameters, data version, and feature list from the original
    run and reproduce it exactly — then apply the same config to new data.
    Without tracking: "nobody remembers how we built this model."

COMMON MISTAKES:
    - Logging only the final metric. Log metrics at every epoch/iteration
      so you can diagnose training curves (overfitting, underfitting, instability).
    - Not logging the data version. The model is only reproducible if you
      know exactly which data it was trained on.
    - Forgetting to log preprocessing parameters (scaler mean/std, encoder
      categories). These are hyperparameters that affect inference.
    - Using print() instead of a tracking system. Prints disappear; tracked
      metrics are searchable and comparable across hundreds of runs.
"""

import mlflow
import mlflow.sklearn
import mlflow.pytorch
import mlflow.xgboost
from mlflow.tracking import MlflowClient
from mlflow.models.signature import infer_signature
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score, roc_auc_score, f1_score,
    confusion_matrix, classification_report
)
import matplotlib.pyplot as plt
import os


# ============================================================
# SECTION 1: MLFLOW CORE CONCEPTS
# ============================================================
# MLflow has four core components:
#   1. Tracking   — log and query experiments
#   2. Projects   — package ML code for reproducibility
#   3. Models     — standard model format for deployment
#   4. Registry   — centralized model store with lifecycle management
#
# The tracking component is the most fundamental — start here.

# EXPERIMENTS organize runs.
# Think of an experiment as a project or question you're investigating.
# Example: "fraud-detection-v2-feature-engineering" is one experiment.
# Each attempt within it is a "run."
#
# RUNS are individual training executions within an experiment.
# Each run has a unique run_id and captures everything about that execution.


def setup_mlflow_tracking():
    """
    Configure where MLflow stores data. Two options:
      1. Local file system (default) — good for development
      2. Remote tracking server — required for teams, CI/CD, production

    For production: deploy MLflow server with PostgreSQL backend and S3 artifact store.
    Docker: docker pull ghcr.io/mlflow/mlflow
    """
    # Option 1: Local tracking (development only)
    # mlflow.set_tracking_uri("./mlruns")  # stores in current directory

    # Option 2: Remote MLflow tracking server (production)
    # mlflow.set_tracking_uri("http://mlflow-server:5000")

    # Option 3: Databricks managed MLflow
    # mlflow.set_tracking_uri("databricks")

    # Option 4: AWS-hosted with S3 artifacts
    # mlflow.set_tracking_uri("http://mlflow.internal.company.com")
    # MLFLOW_S3_ENDPOINT_URL and AWS credentials set as env vars

    # For this example: local tracking
    mlflow.set_tracking_uri("./mlruns")

    # EXPERIMENT: Container for related runs
    # set_experiment creates it if it doesn't exist.
    # Name should be descriptive: project + version + what you're testing
    experiment_name = "fraud-detection-gradient-boosting"
    mlflow.set_experiment(experiment_name)

    print(f"Tracking URI: {mlflow.get_tracking_uri()}")
    print(f"Active experiment: {experiment_name}")


# ============================================================
# SECTION 2: CORE TRACKING API
# ============================================================

def train_with_mlflow_tracking(X_train, y_train, X_test, y_test,
                                n_estimators=100, learning_rate=0.1,
                                max_depth=3, data_version="v1.2"):
    """
    Complete example of MLflow tracking during a training run.
    Every parameter, metric, and artifact is logged for full reproducibility.
    """

    # mlflow.start_run() creates a new run in the active experiment.
    # Use as context manager so run is properly ended even if an exception occurs.
    # run_name: human-readable label (searchable in UI)
    # tags: key-value metadata for filtering/searching runs
    with mlflow.start_run(
        run_name=f"gbt_lr{learning_rate}_depth{max_depth}",
        tags={
            "team": "fraud-ml",
            "data_version": data_version,
            "model_type": "gradient_boosting",
            "environment": "development",
            # Link to experiment config in version control
            "config_commit": os.environ.get("GIT_COMMIT", "unknown"),
        }
    ) as run:

        # ── STEP 1: LOG PARAMETERS ──────────────────────────────────────
        # Parameters are INPUTS to the training process.
        # They are immutable after being logged — they define the run.
        # Log ALL parameters that affect model behavior, including:
        #   - Model hyperparameters
        #   - Preprocessing parameters
        #   - Training configuration

        # log_param: single key-value pair
        mlflow.log_param("n_estimators", n_estimators)
        mlflow.log_param("learning_rate", learning_rate)
        mlflow.log_param("max_depth", max_depth)
        mlflow.log_param("data_version", data_version)
        mlflow.log_param("train_size", len(X_train))
        mlflow.log_param("test_size", len(X_test))
        mlflow.log_param("n_features", X_train.shape[1])
        mlflow.log_param("class_balance_train", y_train.mean())  # important for imbalanced data

        # log_params: dictionary of parameters (more efficient for many params)
        # mlflow.log_params({"param1": val1, "param2": val2, ...})

        # ── STEP 2: TRAIN MODEL ─────────────────────────────────────────
        model = GradientBoostingClassifier(
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            max_depth=max_depth,
            random_state=42,  # ALWAYS set for reproducibility
            verbose=0
        )

        # Log staged training metrics (training curve) for each 10 trees added.
        # This reveals: does the model converge? Is it overfitting?
        staged_auc_train = []
        staged_auc_test = []

        # partial_fit equivalent for GBT: use warm_start pattern
        # Here we fit incrementally to capture training curves
        for i, n_trees in enumerate(range(10, n_estimators + 1, 10)):
            temp_model = GradientBoostingClassifier(
                n_estimators=n_trees,
                learning_rate=learning_rate,
                max_depth=max_depth,
                random_state=42
            )
            temp_model.fit(X_train, y_train)
            auc_train = roc_auc_score(y_train, temp_model.predict_proba(X_train)[:, 1])
            auc_test = roc_auc_score(y_test, temp_model.predict_proba(X_test)[:, 1])
            staged_auc_train.append(auc_train)
            staged_auc_test.append(auc_test)

            # log_metric with step parameter: enables time-series view in MLflow UI
            # Use this for training curves, not just final metrics
            mlflow.log_metric("train_auc", auc_train, step=n_trees)
            mlflow.log_metric("test_auc", auc_test, step=n_trees)

        # Final full model
        model.fit(X_train, y_train)

        # ── STEP 3: LOG METRICS ─────────────────────────────────────────
        # Metrics are OUTPUTS of the training process.
        # Log the complete evaluation picture, not just the headline metric.

        y_pred = model.predict(X_test)
        y_pred_proba = model.predict_proba(X_test)[:, 1]

        final_metrics = {
            "accuracy": accuracy_score(y_test, y_pred),
            "roc_auc": roc_auc_score(y_test, y_pred_proba),
            "f1_score": f1_score(y_test, y_pred),
            "f1_macro": f1_score(y_test, y_pred, average="macro"),
            # Also track calibration: how well do predicted probabilities match actual rates
            # High AUC + poor calibration → ranking is fine, but probabilities are wrong
        }

        # log_metrics: log dict of metrics at once
        mlflow.log_metrics(final_metrics)

        print(f"Run {run.info.run_id}")
        print(f"  AUC: {final_metrics['roc_auc']:.4f}")
        print(f"  F1:  {final_metrics['f1_score']:.4f}")

        # ── STEP 4: LOG ARTIFACTS ────────────────────────────────────────
        # Artifacts are FILES produced during training.
        # Examples: model files, plots, reports, feature importance CSVs.
        # Stored in artifact store (local filesystem or S3/GCS/Azure Blob).

        # 4a. Confusion matrix plot
        cm = confusion_matrix(y_test, y_pred)
        fig, ax = plt.subplots(figsize=(6, 5))
        im = ax.imshow(cm, cmap="Blues")
        plt.colorbar(im)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("Actual")
        ax.set_title(f"Confusion Matrix — AUC: {final_metrics['roc_auc']:.4f}")
        # Add text annotations
        for i in range(cm.shape[0]):
            for j in range(cm.shape[1]):
                ax.text(j, i, str(cm[i, j]), ha="center", va="center", color="black")
        plt.tight_layout()
        # log_figure: save matplotlib figure directly (preferred over saving to disk first)
        mlflow.log_figure(fig, "confusion_matrix.png")
        plt.close(fig)

        # 4b. Feature importance as artifact (CSV for downstream analysis)
        feature_names = [f"feature_{i}" for i in range(X_train.shape[1])]
        fi_df = pd.DataFrame({
            "feature": feature_names,
            "importance": model.feature_importances_
        }).sort_values("importance", ascending=False)

        fi_path = "/tmp/feature_importance.csv"
        fi_df.to_csv(fi_path, index=False)
        # log_artifact: upload file to artifact store
        # artifact_path: subdirectory within the run's artifact directory
        mlflow.log_artifact(fi_path, artifact_path="analysis")

        # 4c. Training curve plot
        fig2, ax2 = plt.subplots(figsize=(8, 5))
        tree_counts = list(range(10, n_estimators + 1, 10))
        ax2.plot(tree_counts, staged_auc_train, label="Train AUC", color="blue")
        ax2.plot(tree_counts, staged_auc_test, label="Test AUC", color="orange")
        ax2.set_xlabel("Number of Trees")
        ax2.set_ylabel("AUC")
        ax2.set_title("Training Curve — AUC vs Number of Trees")
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        mlflow.log_figure(fig2, "training_curve.png")
        plt.close(fig2)

        # 4d. Classification report as text artifact
        report = classification_report(y_test, y_pred)
        mlflow.log_text(report, "classification_report.txt")

        # 4e. Log dataset info (critical for reproducibility)
        # In MLflow 2.x+ there is mlflow.log_input() for dataset tracking
        # For compatibility, we log dataset metadata as params/tags
        mlflow.set_tag("train_data_shape", str(X_train.shape))
        mlflow.set_tag("test_data_shape", str(X_test.shape))

        # ── STEP 5: LOG THE MODEL ────────────────────────────────────────
        # mlflow.sklearn.log_model: saves model in MLflow's standard format.
        # Benefits over pickle:
        #   - Includes metadata (MLflow version, Python version, dependencies)
        #   - Can be loaded with mlflow.pyfunc.load_model (framework-agnostic)
        #   - Directly deployable to MLflow serving, SageMaker, AzureML, etc.

        # infer_signature: captures input/output schema from training data.
        # This is logged with the model and used for:
        #   - Input validation at serving time
        #   - Documentation in Model Registry
        signature = infer_signature(X_train, model.predict_proba(X_train))

        # Example input: sample of training data for documentation/testing
        input_example = X_train[:5]

        mlflow.sklearn.log_model(
            sk_model=model,
            artifact_path="model",              # Directory name in artifacts
            signature=signature,                # Input/output schema
            input_example=input_example,        # Sample input for the model card
            registered_model_name=None,         # Set to register directly (see Section 4)
        )

        # Return run_id for reference (e.g., to register model from this run)
        return run.info.run_id, final_metrics


# ============================================================
# SECTION 3: AUTO-LOGGING
# ============================================================
# Auto-logging intercepts framework calls and logs parameters/metrics automatically.
# No manual mlflow.log_param() calls needed. Saves boilerplate for standard training.
# CAVEAT: Auto-logging logs EVERYTHING. Custom business metrics still need manual logging.

def demo_autologging_sklearn():
    """
    mlflow.sklearn.autolog() automatically captures:
      - Estimator class and all hyperparameters
      - Training metrics (accuracy, AUC for classifiers)
      - Training time
      - Feature importances (for tree-based models)
      - Model signature (if training data provided)
    """
    # Enable before training — must be called before fit()
    mlflow.sklearn.autolog(
        log_input_examples=True,    # Log sample input for documentation
        log_model_signatures=True,  # Infer and log input/output schema
        log_models=True,            # Save model artifact
        log_datasets=False,         # Log dataset info (experimental)
        silent=False,               # Print what's being logged
        max_tuning_runs=5,          # For cross-val: log top N runs
    )

    with mlflow.start_run(run_name="autolog_demo"):
        model = GradientBoostingClassifier(n_estimators=100, learning_rate=0.1)
        # AUTO-LOGGED: n_estimators, learning_rate, max_depth, and all other params
        # AUTO-LOGGED: training_accuracy, training_roc_auc, training_f1 (after fit)
        # AUTO-LOGGED: model artifact with signature
        X_dummy = np.random.randn(1000, 10)
        y_dummy = (X_dummy[:, 0] > 0).astype(int)
        model.fit(X_dummy, y_dummy)
        # AUTO-LOGGED: all metrics are captured by the autolog hook


def demo_autologging_pytorch():
    """
    mlflow.pytorch.autolog() captures:
      - Loss at each epoch (train + validation)
      - Model architecture summary
      - Optimizer parameters (learning rate, weight decay)
      - Model artifact
    """
    mlflow.pytorch.autolog(
        log_every_n_epoch=1,    # Log metrics every epoch (reduce for long training)
        log_models=True,        # Save model checkpoint as artifact
        disable=False,
        silent=False,
    )
    # Usage: just call trainer.fit() inside mlflow.start_run() block
    # The autolog hook intercepts pytorch-lightning Trainer or your custom loop


def demo_autologging_xgboost():
    """
    mlflow.xgboost.autolog() captures:
      - All XGBoost training parameters
      - Train/eval metrics at each round
      - Feature importance (gain, cover, weight)
      - Model artifact
    """
    mlflow.xgboost.autolog(
        importance_types=["gain", "cover"],  # Which feature importance types to log
        log_input_examples=False,
        log_model_signatures=True,
    )
    # Note: also works with LightGBM via mlflow.lightgbm.autolog()


# ============================================================
# SECTION 4: MLFLOW MODEL REGISTRY
# ============================================================
# The Model Registry is the production-facing component.
# It provides:
#   - Versioned model storage linked to training runs
#   - Stage transitions with optional approval workflows
#   - Annotations (description, tags) for model governance
#   - API for programmatic model promotion in CI/CD

def register_model_to_registry(run_id: str, model_name: str = "fraud-detector"):
    """
    Register a model from a training run to the Model Registry.
    This is the bridge between experimentation and production deployment.

    Registration creates a ModelVersion entry linked to the run_id.
    The model artifact is copied to the registry's storage location.
    """
    client = MlflowClient()

    # Option 1: Register from mlflow.log_model (at training time)
    # mlflow.sklearn.log_model(..., registered_model_name="fraud-detector")

    # Option 2: Register after the run (more control, common in CI/CD)
    # Construct the artifact URI: runs:/<run_id>/<artifact_path>
    model_uri = f"runs:/{run_id}/model"

    # Register — creates the model name if it doesn't exist
    model_version = mlflow.register_model(
        model_uri=model_uri,
        name=model_name,
        tags={"registered_by": "ci-pipeline", "validation": "pending"}
    )

    version_number = model_version.version
    print(f"Registered model '{model_name}' version {version_number}")
    print(f"  Status: {model_version.status}")  # PENDING_REGISTRATION → READY

    return version_number


def manage_model_stages(model_name: str, version: int):
    """
    Model versions move through stages:
      None (just registered) → Staging → Production → Archived

    WORKFLOW:
      1. CI/CD registers new version (stage: None)
      2. Automated validation job promotes to Staging if metrics pass
      3. Human review (or automated integration test) promotes to Production
      4. Old Production version is Archived (never deleted — audit trail)

    Note: MLflow 2.9+ deprecates stages in favor of aliases (more flexible).
    Aliases example: set "production" alias on any version, multiple aliases per model.
    """
    client = MlflowClient()

    # Add description explaining what this version does
    client.update_model_version(
        name=model_name,
        version=str(version),
        description=(
            f"GBT model retrained on data v1.2. "
            f"AUC improved from 0.91 to 0.94 on holdout test set. "
            f"Latency: <10ms p99 on AWS ml.m5.xlarge."
        )
    )

    # Transition to Staging: automated evaluation passed
    client.transition_model_version_stage(
        name=model_name,
        version=str(version),
        stage="Staging",
        archive_existing_versions=False  # Don't archive previous Staging version yet
    )
    print(f"Version {version} promoted to Staging")

    # After integration tests pass: promote to Production
    # This is gated by manual approval or automated evaluation
    client.transition_model_version_stage(
        name=model_name,
        version=str(version),
        stage="Production",
        archive_existing_versions=True   # Archive previous Production version
    )
    print(f"Version {version} promoted to Production")
    print(f"Previous Production version archived automatically")

    # MLflow 2.9+ ALIASES (preferred over stages):
    # client.set_registered_model_alias(model_name, "production", str(version))
    # client.set_registered_model_alias(model_name, "champion", str(version))
    # Load by alias: mlflow.pyfunc.load_model(f"models:/{model_name}@production")


def load_production_model(model_name: str):
    """
    Load the current Production model for inference or evaluation.
    This is how serving applications reference models — by name and stage,
    not by hardcoded run_id or file path.
    """
    # Load by stage — always gets the current Production version
    model_uri = f"models:/{model_name}/Production"
    model = mlflow.pyfunc.load_model(model_uri)

    # Alternative: load specific version (deterministic, good for testing)
    # model = mlflow.pyfunc.load_model(f"models:/{model_name}/3")

    # Alternative: load by alias (MLflow 2.9+)
    # model = mlflow.pyfunc.load_model(f"models:/{model_name}@production")

    return model


def compare_model_versions(model_name: str):
    """
    Retrieve all registered versions and compare metrics.
    Useful for deciding which version to promote.
    """
    client = MlflowClient()

    # Get all versions of this model
    versions = client.search_model_versions(f"name='{model_name}'")

    comparison_data = []
    for v in versions:
        # Each version is linked to a training run via run_id
        run = client.get_run(v.run_id)
        metrics = run.data.metrics
        params = run.data.params
        comparison_data.append({
            "version": v.version,
            "stage": v.current_stage,
            "roc_auc": metrics.get("roc_auc", "N/A"),
            "f1_score": metrics.get("f1_score", "N/A"),
            "n_estimators": params.get("n_estimators", "N/A"),
            "learning_rate": params.get("learning_rate", "N/A"),
            "created_at": pd.Timestamp(v.creation_timestamp, unit="ms").isoformat(),
        })

    df = pd.DataFrame(comparison_data).sort_values("roc_auc", ascending=False)
    print("\nModel Version Comparison:")
    print(df.to_string(index=False))
    return df


# ============================================================
# SECTION 5: COMPARING RUNS PROGRAMMATICALLY
# ============================================================
# Don't just use the UI. Query runs in code for automated champion selection.

def find_best_run(experiment_name: str, metric: str = "roc_auc",
                  higher_is_better: bool = True):
    """
    Programmatically find the best run in an experiment.
    Used in CI/CD pipelines to decide whether to promote a new model.
    """
    client = MlflowClient()

    # Get experiment by name
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        raise ValueError(f"Experiment '{experiment_name}' not found")

    # Search runs with filters
    # Syntax: SQL-like filter string
    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        filter_string="tags.environment = 'development'",  # Only finished runs
        run_view_type=mlflow.entities.ViewType.ACTIVE_ONLY,
        max_results=100,
        order_by=[f"metrics.{metric} {'DESC' if higher_is_better else 'ASC'}"],
    )

    if not runs:
        raise ValueError("No runs found")

    best_run = runs[0]
    print(f"Best run: {best_run.info.run_id}")
    print(f"  {metric}: {best_run.data.metrics.get(metric, 'N/A'):.4f}")
    print(f"  Params: {best_run.data.params}")

    return best_run


# ============================================================
# SECTION 6: WEIGHTS & BIASES (W&B)
# ============================================================
# W&B is a commercial alternative to MLflow with superior visualization,
# collaboration features, and built-in hyperparameter sweep infrastructure.
# MLflow is self-hosted and more flexible; W&B is easier to get started with.

"""
WEIGHTS & BIASES QUICKSTART (conceptual — requires wandb package and API key):

import wandb

# Initialize a run — creates a new run in your W&B project
wandb.init(
    project="fraud-detection",          # Groups related experiments
    name="gbt-lr0.1-depth3",           # Human-readable run name
    config={                            # All hyperparameters (equivalent to log_param)
        "n_estimators": 100,
        "learning_rate": 0.1,
        "max_depth": 3,
        "data_version": "v1.2",
    },
    tags=["gradient-boosting", "v2-features"],
    notes="Testing new fraud features from payments team",
)

# Log metrics during training (equivalent to mlflow.log_metric with step)
for epoch in range(100):
    train_loss = train_one_epoch(model, train_loader)
    val_loss = evaluate(model, val_loader)
    wandb.log({
        "train_loss": train_loss,
        "val_loss": val_loss,
        "epoch": epoch,
        "learning_rate": scheduler.get_last_lr()[0],  # Track LR schedule
    })

# Watch model gradients and weights — unique W&B feature
# Logs gradient histograms, weight distributions per layer per step
# CRITICAL for diagnosing vanishing/exploding gradients in deep networks
wandb.watch(
    model,
    log="all",          # "gradients", "parameters", "all"
    log_freq=100,       # How often to log (steps)
    log_graph=True,     # Log model computation graph
)

# Log images/tables/plots
wandb.log({
    "confusion_matrix": wandb.plot.confusion_matrix(
        preds=y_pred, y_true=y_test, class_names=["not_fraud", "fraud"]
    ),
    "feature_importance": wandb.Table(
        data=fi_df.values.tolist(),
        columns=["feature", "importance"]
    ),
})

# Finish the run
wandb.finish()
"""

# W&B SWEEPS: Hyperparameter optimization built into W&B
# More powerful than manual grid search — uses Bayesian optimization or Hyperband
"""
SWEEP CONFIGURATION:
sweep_config = {
    "method": "bayes",          # "grid", "random", or "bayes" (Bayesian optimization)
    "metric": {
        "name": "val_auc",
        "goal": "maximize"
    },
    "parameters": {
        "learning_rate": {
            "distribution": "log_uniform_values",  # Log scale for LR
            "min": 0.001,
            "max": 0.3
        },
        "n_estimators": {
            "values": [50, 100, 200, 500]           # Discrete choices
        },
        "max_depth": {
            "values": [2, 3, 4, 5, 6]
        },
        "subsample": {
            "distribution": "uniform",
            "min": 0.5,
            "max": 1.0
        }
    },
    "early_terminate": {          # Stop underperforming runs early
        "type": "hyperband",
        "min_iter": 10,
        "s": 2
    }
}

# Initialize sweep (creates it on W&B server, returns sweep_id)
sweep_id = wandb.sweep(sweep_config, project="fraud-detection")

# Training function that W&B calls with each hyperparameter combination
def sweep_train():
    with wandb.init() as run:
        cfg = wandb.config  # W&B injects the hyperparameters for this trial
        model = GradientBoostingClassifier(
            n_estimators=cfg.n_estimators,
            learning_rate=cfg.learning_rate,
            max_depth=cfg.max_depth,
        )
        model.fit(X_train, y_train)
        auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
        wandb.log({"val_auc": auc})

# Launch N parallel agents (can run on multiple machines)
wandb.agent(sweep_id, function=sweep_train, count=50)
# W&B automatically runs Bayesian optimization across the 50 trials
# and surfaces the best hyperparameter combinations
"""


# ============================================================
# SECTION 7: BEST PRACTICES FOR PRODUCTION TRACKING
# ============================================================

tracking_best_practices = {
    "always_log": [
        "All hyperparameters (not just the ones you're tuning)",
        "Data version / data hash",
        "Git commit SHA of training code",
        "Python/framework versions (environment info)",
        "Training duration and hardware used",
        "Metrics on BOTH train and validation (reveals overfitting)",
        "Metrics at regular intervals (training curves, not just final value)",
        "The model artifact itself (not just metrics)",
        "Input schema (feature names, types, expected ranges)",
    ],
    "tagging_strategy": {
        "purpose": "Tags make runs filterable and searchable in large experiments",
        "recommended_tags": {
            "team": "Which team owns this model",
            "model_type": "gradient_boosting / neural_network / etc",
            "data_version": "v1.2 / 2024-Q1 / etc",
            "feature_set": "v3-fraud-features",
            "environment": "development / staging / production",
            "status": "experimental / validated / deprecated",
            "git_commit": "SHA of code that produced this run",
        }
    },
    "artifact_strategy": {
        "always_store": ["Trained model", "Preprocessing pipeline (scaler, encoder)"],
        "store_for_debugging": ["Confusion matrices", "Feature importances", "Training curves"],
        "store_for_analysis": ["Predictions on test set (for error analysis)", "SHAP values"],
        "store_for_documentation": ["Classification report", "Model card", "Dataset stats"],
    },
    "naming_conventions": {
        "experiments": "Use descriptive names: '{project}-{version}-{what-you're-testing}'",
        "runs": "Encode key params: 'gbt_lr0.1_depth3_features-v2'",
        "model_names": "Use hyphenated slugs: 'fraud-detector', 'churn-predictor'",
    },
    "run_nesting": (
        "Nested runs (parent/child) are useful for hyperparameter sweeps: "
        "Parent run = sweep configuration, Child runs = individual trials. "
        "mlflow.start_run(nested=True) inside an existing run context."
    )
}

# ============================================================
# PUTTING IT TOGETHER: PRODUCTION TRAINING LOOP
# ============================================================

def production_training_run(
    X_train, y_train, X_val, y_val, X_test, y_test,
    hyperparams: dict, data_version: str, feature_set: str
):
    """
    Production-grade training function with complete MLflow tracking.
    This is the template for any training job in a CI/CD pipeline.

    Returns: (run_id, metrics) for downstream pipeline steps (registration, evaluation).
    """
    setup_mlflow_tracking()

    with mlflow.start_run(
        run_name=f"{hyperparams.get('model_type','model')}_{data_version}",
        tags={
            "data_version": data_version,
            "feature_set": feature_set,
            "git_commit": os.environ.get("GIT_SHA", "local"),
            "triggered_by": os.environ.get("TRIGGER", "manual"),
            "environment": os.environ.get("ENVIRONMENT", "development"),
        }
    ) as run:
        # Log all hyperparameters
        mlflow.log_params(hyperparams)

        # Train
        model = GradientBoostingClassifier(**{
            k: v for k, v in hyperparams.items()
            if k in ["n_estimators", "learning_rate", "max_depth"]
        })
        model.fit(X_train, y_train)

        # Evaluate on all splits
        for split_name, X_split, y_split in [
            ("train", X_train, y_train),
            ("val", X_val, y_val),
            ("test", X_test, y_test),
        ]:
            y_pred = model.predict(X_split)
            y_proba = model.predict_proba(X_split)[:, 1]
            mlflow.log_metrics({
                f"{split_name}_auc": roc_auc_score(y_split, y_proba),
                f"{split_name}_f1": f1_score(y_split, y_pred),
                f"{split_name}_accuracy": accuracy_score(y_split, y_pred),
            })

        # Log model
        signature = infer_signature(X_train, model.predict(X_train))
        mlflow.sklearn.log_model(model, "model", signature=signature)

        # Key business metrics (the ones the promotion gate checks)
        test_auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
        test_f1 = f1_score(y_test, model.predict(X_test))

        return run.info.run_id, {"test_auc": test_auc, "test_f1": test_f1}


# ARCHITECT'S NOTE ON TRACKING STRATEGY:
# ─────────────────────────────────────────────────────────────
# Tracking data is only valuable if it's queryable and comparable.
# Three rules for effective experiment tracking at scale:
#
# 1. STANDARDIZE what you log. Teams use inconsistent metric names
#    ("auc" vs "roc_auc" vs "val_auc") → comparisons break across teams.
#    Create a company-wide metrics dictionary and enforce it.
#
# 2. AUTOMATE the comparison. CI/CD pipelines should programmatically
#    query MLflow to decide "is this new model better than production?"
#    Do not rely on humans eyeballing the UI before each deployment.
#
# 3. KEEP ARTIFACTS. Disk is cheap. Models from 6 months ago are
#    priceless when you need to debug a production incident, respond
#    to a regulator, or roll back after a bad update.
