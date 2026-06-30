# ============================================================
# L07: Model Registry and Versioning
# ============================================================
# WHAT: A model registry is a centralized catalog of trained models
#       with metadata, versioning, lineage, and lifecycle management.
#       It tracks every model that was ever trained — what data produced
#       it, what code produced it, its performance metrics, and its
#       current deployment status. Think of it as GitHub for models.
# WHY:  Without a registry, models are files on someone's laptop or random
#       paths in S3 that nobody remembers. You cannot do A/B testing,
#       rollback, compliance auditing, or reproducibility without knowing
#       exactly which model artifact is in production and how it was made.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    A model registry sits between training (experiment tracking) and
    deployment (serving infrastructure). Models progress through lifecycle
    stages: from a raw training run artifact (None/Staging) to Production
    (actively serving) to Archived (replaced but retained for audit).
    Every transition is logged with who approved it and when.
    The registry also stores the LINEAGE of each model — what dataset,
    what code version, what feature schema, what hyperparameters.

PRODUCTION USE CASE:
    A fraud detection team at a payment processor trains 20+ model
    variants per week (Optuna sweeps). All runs are logged to MLflow.
    An automated evaluation job promotes the best run to Staging if
    AUC > 0.87. A human (ML engineer + risk manager) reviews the Staging
    model, checks feature importance and bias metrics, and approves it
    for Production via the API. The previous Production model is Archived
    (never deleted — compliance requires 5-year retention). Rollback
    (Archived → Production) takes 90 seconds.

COMMON MISTAKES:
    1. Deleting old model versions — you lose rollback capability and
       violate audit requirements. Archive, never delete.
    2. Registering every training run — only register models that passed
       the evaluation gate. The registry should only hold viable candidates.
    3. Missing metadata — a model version without training data version,
       feature schema, or git SHA is not reproducible and not debuggable.
    4. No approval workflow — anyone on the team can push to Production.
       Leads to unreviewed models serving real users.
    5. Conflating experiment tracking with the registry — MLflow Tracking
       (runs) is for experiments; MLflow Registry (registered models) is
       for production candidates. They serve different purposes.
"""

import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, average_precision_score
import joblib

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1: MLFLOW MODEL REGISTRY — CORE CONCEPTS
# ============================================================
# MLflow has two separate systems that work together:
#
# 1. MLflow TRACKING (runs / experiments):
#    - Log parameters, metrics, and artifacts for every training run
#    - Organized into experiments (one per project/feature/team)
#    - Every run gets a unique run_id
#    - This is for DATA SCIENTISTS — for comparing experiments
#
# 2. MLflow MODEL REGISTRY (registered models / versions / stages):
#    - Named models that are production candidates
#    - Each model can have multiple versions (v1, v2, v3, ...)
#    - Versions have lifecycle stages: None → Staging → Production → Archived
#    - This is for ML ENGINEERS — for managing production lifecycle

# LIFECYCLE STAGES (classic MLflow):
#   None      — newly registered, not yet evaluated for production
#   Staging   — evaluated, approved for testing, not yet in production
#   Production — actively serving live traffic
#   Archived  — replaced, kept for audit trail and rollback
#
# NEW: MLflow 2.x introduced ALIASES instead of stages:
#   model.set_registered_model_alias("fraud_detector", "champion", version=5)
#   model.set_registered_model_alias("fraud_detector", "challenger", version=6)
#   Load by alias: mlflow.pyfunc.load_model("models:/fraud_detector@champion")
#   Aliases are more flexible than fixed stage names.

# ============================================================
# SECTION 2: REGISTERING A MODEL — THREE PATTERNS
# ============================================================

# PATTERN 1: Auto-register during a training run (simplest)
#
# with mlflow.start_run(run_name="gbm_v3_optuna_trial_42") as run:
#     mlflow.log_params({"n_estimators": 200, "max_depth": 5, "lr": 0.05})
#     model.fit(X_train, y_train)
#     auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
#     mlflow.log_metric("auc", auc)
#
#     # Register to registry in one line:
#     mlflow.sklearn.log_model(
#         sk_model=model,
#         artifact_path="model",
#         registered_model_name="fraud_detector",  # creates if not exists
#         # Also log input/output signatures (validates schema at serve time):
#         signature=mlflow.models.infer_signature(X_test, model.predict(X_test)),
#     )
#     # This creates version N under "fraud_detector" in the registry,
#     # linked to this run_id so you can trace training → deployment.

# PATTERN 2: Programmatic registration via MlflowClient (more control)
#
# from mlflow.tracking import MlflowClient
# client = MlflowClient()
#
# # Create the registered model (idempotent — does nothing if already exists)
# try:
#     client.create_registered_model(
#         name="fraud_detector",
#         description="XGBoost fraud detection model. Threshold: AUC > 0.87",
#         tags={"team": "risk", "project": "fraud_v2"},
#     )
# except mlflow.exceptions.RestException:
#     pass  # already exists
#
# # Create a new version from an existing run's artifact
# model_version = client.create_model_version(
#     name="fraud_detector",
#     source=f"runs:/{run_id}/model",   # points to artifacts in the run
#     run_id=run_id,
#     description=f"Trained on 2024-06-01 data. AUC={auc:.4f}",
#     tags={"git_sha": git_sha, "data_version": "2024-06-01"},
# )
# version_number = model_version.version
# print(f"Registered as version {version_number}")

# PATTERN 3: Transition stages programmatically
#
# # Promote from None → Staging after automated evaluation passes
# client.transition_model_version_stage(
#     name="fraud_detector",
#     version=version_number,
#     stage="Staging",
#     archive_existing_versions=False,  # don't auto-archive older Staging versions
# )
#
# # Promote from Staging → Production (after human approval)
# client.transition_model_version_stage(
#     name="fraud_detector",
#     version=version_number,
#     stage="Production",
#     archive_existing_versions=True,  # archive the CURRENT Production version
# )

# ============================================================
# SECTION 3: MODEL METADATA — WHAT MUST BE TRACKED
# ============================================================
# Every registered model version must have:
#
# PERFORMANCE METRICS:
#   - Primary metric: AUC, F1, RMSE (whatever drives promotion decision)
#   - Secondary metrics: precision@k, calibration, bias across subgroups
#   - Test set info: holdout date range, size, fraud rate
#
# DATA LINEAGE:
#   - Training dataset version: DVC hash, git SHA of data pipeline,
#     or S3 URI with timestamp. MUST be reproducible.
#   - Feature schema: exact column names + dtypes (critical for serving compatibility)
#   - Label definition: what counts as fraud in this version?
#
# CODE LINEAGE:
#   - Git SHA of training code at time of training
#   - Docker image SHA used for training (if containerized)
#   - Dependency versions: requirements.txt or conda environment hash
#
# TRAINING METADATA:
#   - Hyperparameters (logged automatically by MLflow)
#   - Training start/end time, compute used (GPU type, hours)
#   - Random seed (for reproducibility)
#
# SERVING METADATA:
#   - Input schema: feature names, types, expected ranges
#   - Output schema: prediction format (probability [0,1] vs class label vs rank)
#   - Preprocessing steps required (scaling, encoding) — or note "included in model"


@dataclass
class ModelMetadata:
    """
    Structured metadata for a registered model version.
    In MLflow this lives in tags + description + linked run artifacts.
    This dataclass shows the complete set of metadata you should capture.
    """
    # Identity
    model_name: str
    version: int
    stage: str = "None"  # None | Staging | Production | Archived

    # Performance (from evaluation step)
    auc: float = 0.0
    average_precision: float = 0.0
    threshold_used: float = 0.5  # decision threshold for binary classification
    test_set_size: int = 0
    test_fraud_rate: float = 0.0

    # Data lineage
    training_data_version: str = ""  # DVC hash or S3 URI
    training_start_date: str = ""
    training_end_date: str = ""
    feature_schema: Dict[str, str] = field(default_factory=dict)  # {col: dtype}
    feature_list: List[str] = field(default_factory=list)

    # Code lineage
    git_sha: str = ""
    docker_image: str = ""
    python_version: str = ""
    dependencies_hash: str = ""  # hash of requirements.txt

    # Training metadata
    hyperparameters: Dict = field(default_factory=dict)
    training_duration_minutes: float = 0.0
    training_compute: str = ""  # e.g., "ml.p3.2xlarge"

    # Governance
    registered_by: str = ""
    registered_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    promoted_to_staging_by: str = ""
    promoted_to_production_by: str = ""
    promoted_to_production_at: str = ""
    approval_ticket: str = ""  # JIRA/Linear ticket for the promotion

    def to_dict(self) -> dict:
        """Serialize to dict for storage in MLflow tags or a metadata DB."""
        return {
            "model_name": self.model_name,
            "version": self.version,
            "auc": self.auc,
            "git_sha": self.git_sha,
            "training_data_version": self.training_data_version,
            "feature_list": ",".join(self.feature_list),
            "hyperparameters": json.dumps(self.hyperparameters),
            "approval_ticket": self.approval_ticket,
        }


# ============================================================
# SECTION 4: DVC — DATA VERSION CONTROL
# ============================================================
# DVC is git for large files. Tracks datasets and models in a
# git-compatible way — .dvc pointer files (small, commit to git)
# point to large files stored in remote storage (S3, GCS, Azure).
# Also defines ML pipelines as DAGs for full reproducibility.

# WORKFLOW:
# 1. Initialize DVC in your git repo:
#    dvc init
#    git add .dvc && git commit -m "initialize dvc"
#
# 2. Track a dataset:
#    dvc add data/train.parquet
#    # Creates data/train.parquet.dvc (tiny file — commit this to git)
#    # Adds data/train.parquet to .gitignore (never commit large files)
#    git add data/train.parquet.dvc data/.gitignore
#    git commit -m "add training data v1.0"
#
# 3. Push data to remote:
#    dvc remote add -d s3_remote s3://my-bucket/dvc-storage
#    dvc push   # uploads data/train.parquet to S3
#
# 4. Pull data (on another machine or in CI):
#    git pull && dvc pull   # pulls exactly the data version in the .dvc file
#
# DVC PIPELINES (dvc.yaml) — define reproducible training pipeline:
# stages:
#   prepare:
#     cmd: python src/prepare.py
#     deps:
#       - src/prepare.py
#       - data/raw.parquet
#     outs:
#       - data/prepared.parquet
#   train:
#     cmd: python src/train.py
#     deps:
#       - src/train.py
#       - data/prepared.parquet
#     outs:
#       - models/model.pkl
#     metrics:
#       - metrics.json:
#           cache: false    # commit metrics.json to git (it's small)
#
# dvc repro       → runs only stages where deps have changed
# dvc diff        → shows what data/params changed since last run
# dvc params diff → shows parameter changes (from params.yaml)

# ============================================================
# SECTION 5: SEMANTIC VERSIONING FOR MODELS
# ============================================================
# Software semantic versioning (MAJOR.MINOR.PATCH) adapted for models:
#
# MAJOR (breaking change — requires calling team coordination):
#   - Input schema changes: new required features, removed features
#   - Output format changes: was probability [0,1], now class label {0,1}
#   - Serving API changes: endpoint URL or request schema changed
#   Teams consuming this model's predictions MUST be notified and update.
#
# MINOR (backward-compatible improvement — safe to deploy):
#   - Significantly better performance (AUC went from 0.87 to 0.91)
#   - New optional input features (model still works without them)
#   - Retrained on newer data (same schema, same output format)
#   Can be deployed as a canary with no consumer-side changes.
#
# PATCH (bugfix — hotfix track):
#   - Corrected training bug (wrong label column used)
#   - Retrained after data pipeline fix
#   - Hyperparameter fix for a discovered edge case
#
# Example progression:
#   1.0.0 — initial model, trained on 2023 data
#   1.1.0 — retrained on 2024 data, AUC improved
#   1.2.0 — new optional feature (device_type) added
#   2.0.0 — completely redesigned feature schema (breaking change)
#   2.0.1 — retrained after data pipeline bug fix

# ============================================================
# SECTION 6: A/B TESTING AND SHADOW MODE VIA REGISTRY
# ============================================================

class ModelRouter:
    """
    Routes live traffic between champion (current production) and
    challenger (candidate) model versions loaded from the registry.

    SHADOW MODE: challenger runs in parallel but predictions are logged
                 only, never served. Zero risk experimentation.
    CANARY MODE: challenger serves a fraction of live traffic.
                 Gradually increase fraction as confidence grows.
    """

    def __init__(self, champion_model, challenger_model=None,
                 challenger_fraction: float = 0.0, shadow_mode: bool = False):
        self.champion = champion_model
        self.challenger = challenger_model
        self.challenger_fraction = challenger_fraction
        self.shadow_mode = shadow_mode  # if True, challenger runs but not served

        self._champion_predictions: List[float] = []
        self._challenger_predictions: List[float] = []
        self._n_champion_requests = 0
        self._n_challenger_requests = 0

    def predict(self, features: np.ndarray) -> dict:
        import random
        use_challenger = (
            self.challenger is not None
            and random.random() < self.challenger_fraction
            and not self.shadow_mode
        )

        # Champion prediction (always computed)
        champion_score = float(
            self.champion.predict_proba(features.reshape(1, -1))[0, 1]
        )
        self._champion_predictions.append(champion_score)
        self._n_champion_requests += 1

        # Challenger: run in shadow (always) or canary (if selected)
        challenger_score = None
        if self.challenger is not None:
            challenger_score = float(
                self.challenger.predict_proba(features.reshape(1, -1))[0, 1]
            )
            self._challenger_predictions.append(challenger_score)
            if not self.shadow_mode:
                self._n_challenger_requests += 1

        # In shadow mode: always serve champion prediction
        served_score = champion_score
        served_version = "champion"
        if use_challenger:
            served_score = challenger_score
            served_version = "challenger"

        return {
            "prediction": served_score,
            "model_version": served_version,
            "champion_score": champion_score,
            "challenger_score": challenger_score,  # logged but not served in shadow
        }

    def comparison_stats(self) -> dict:
        """Compare champion vs challenger prediction distributions."""
        if len(self._challenger_predictions) == 0:
            return {"error": "No challenger predictions yet"}

        c_preds = np.array(self._champion_predictions)
        ch_preds = np.array(self._challenger_predictions)
        return {
            "champion_mean_score": float(c_preds.mean()),
            "challenger_mean_score": float(ch_preds.mean()),
            "champion_requests": self._n_champion_requests,
            "challenger_requests": self._n_challenger_requests,
            "score_delta": float(ch_preds.mean() - c_preds.mean()),
        }


# ============================================================
# SECTION 7: GOVERNANCE AND APPROVAL WORKFLOW
# ============================================================
# Who can promote models to Production? In regulated industries
# (finance, healthcare) this requires documented approvals.

class PromotionWorkflow:
    """
    Enforces a promotion approval gate for model registry transitions.
    In production this integrates with Jira/Linear for ticketing
    and Slack for notifications.
    """

    REQUIRED_APPROVERS = {"ml_engineer", "product_manager"}  # both must approve
    REQUIRED_METADATA = {"auc", "git_sha", "training_data_version", "feature_list"}

    def __init__(self):
        self._pending_approvals: Dict[str, set] = {}  # version_key → approvers so far

    def request_promotion(self, model_name: str, version: int,
                          metadata: ModelMetadata,
                          requested_by: str) -> str:
        """
        Start a promotion request. Returns a ticket/request ID.
        Validates that all required metadata is present before allowing.
        """
        meta_dict = metadata.to_dict()
        missing = self.REQUIRED_METADATA - set(meta_dict.keys())
        if missing:
            raise ValueError(f"Missing required metadata: {missing}")
        if metadata.auc < 0.85:
            raise ValueError(
                f"AUC {metadata.auc:.4f} below minimum threshold 0.85. "
                f"Cannot request promotion."
            )
        ticket_id = f"ML-{int(time.time())}"
        version_key = f"{model_name}:v{version}"
        self._pending_approvals[version_key] = set()
        logger.info(
            f"Promotion request {ticket_id} created for {version_key} "
            f"by {requested_by}. Awaiting approvals from: {self.REQUIRED_APPROVERS}"
        )
        return ticket_id

    def approve(self, model_name: str, version: int, approver: str) -> bool:
        """
        Record an approval. Returns True if all required approvals received.
        """
        version_key = f"{model_name}:v{version}"
        if version_key not in self._pending_approvals:
            raise ValueError(f"No pending promotion request for {version_key}")
        if approver not in self.REQUIRED_APPROVERS:
            raise ValueError(f"{approver} is not a valid approver. "
                             f"Valid: {self.REQUIRED_APPROVERS}")
        self._pending_approvals[version_key].add(approver)
        logger.info(f"{approver} approved {version_key}. "
                    f"Approvals: {self._pending_approvals[version_key]}")
        all_approved = self._pending_approvals[version_key] >= self.REQUIRED_APPROVERS
        if all_approved:
            logger.info(f"All approvals received. {version_key} ready for Production.")
        return all_approved


# ============================================================
# SECTION 8: COMPLETE MLFLOW WORKFLOW — FRAUD DETECTION EXAMPLE
# ============================================================

def train_and_register_model(X_train, y_train, X_test, y_test,
                              hyperparams: dict,
                              model_name: str = "fraud_detector",
                              auc_threshold: float = 0.85,
                              git_sha: str = "abc1234",
                              data_version: str = "2024-06-01") -> Optional[ModelMetadata]:
    """
    Full workflow: train → evaluate → register if better than threshold.
    In production the mlflow.* calls are uncommented and real.
    Returns ModelMetadata if registered, None if below threshold.
    """
    # with mlflow.start_run(run_name=f"fraud_{datetime.now():%Y%m%d_%H%M}") as run:
    #     mlflow.log_params(hyperparams)
    #     mlflow.set_tags({"git_sha": git_sha, "data_version": data_version})

    # 1. Train
    model = GradientBoostingClassifier(**hyperparams, random_state=42)
    model.fit(X_train, y_train)

    # 2. Evaluate
    y_prob = model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_prob)
    ap = average_precision_score(y_test, y_prob)

    #     mlflow.log_metrics({"auc": auc, "average_precision": ap})

    # 3. Evaluation gate — only register if above threshold
    if auc < auc_threshold:
        logger.warning(
            f"Model AUC {auc:.4f} below threshold {auc_threshold}. "
            f"Not registering. Run ID: simulated"
        )
        return None

    # 4. Register
    #     mlflow.sklearn.log_model(model, "model",
    #         registered_model_name=model_name,
    #         signature=mlflow.models.infer_signature(X_test, model.predict(X_test)))

    metadata = ModelMetadata(
        model_name=model_name,
        version=1,  # MLflow auto-increments; shown as 1 here for demo
        stage="None",
        auc=auc,
        average_precision=ap,
        test_set_size=len(y_test),
        test_fraud_rate=float(y_test.mean()),
        training_data_version=data_version,
        feature_list=["amount", "hour", "freq_7d"],
        feature_schema={"amount": "float32", "hour": "int32", "freq_7d": "int32"},
        git_sha=git_sha,
        hyperparameters=hyperparams,
        registered_by="ml-pipeline-service-account",
    )
    logger.info(
        f"Model registered: {model_name} v{metadata.version}, "
        f"AUC={auc:.4f}, AP={ap:.4f}"
    )
    return metadata


# ============================================================
# DEMONSTRATION
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    rng = np.random.default_rng(42)
    n = 5000
    X = rng.standard_normal((n, 3)).astype(np.float32)
    y = (rng.uniform(0, 1, n) < 0.08).astype(int)  # 8% fraud rate
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2,
                                                         random_state=42, stratify=y)

    params = {"n_estimators": 200, "max_depth": 4, "learning_rate": 0.05}
    metadata = train_and_register_model(
        X_train, y_train, X_test, y_test,
        hyperparams=params,
        auc_threshold=0.50,  # Low threshold for demo (synthetic data)
    )

    if metadata:
        print(f"\nRegistered model metadata:")
        print(f"  AUC:           {metadata.auc:.4f}")
        print(f"  Avg Precision: {metadata.average_precision:.4f}")
        print(f"  Git SHA:       {metadata.git_sha}")
        print(f"  Features:      {metadata.feature_list}")

        # Demo approval workflow
        workflow = PromotionWorkflow()
        ticket = workflow.request_promotion(
            "fraud_detector", 1, metadata, requested_by="alice@company.com"
        )
        print(f"\nPromotion ticket: {ticket}")
        approved = workflow.approve("fraud_detector", 1, "ml_engineer")
        print(f"After ml_engineer approval: all_approved={approved}")
        approved = workflow.approve("fraud_detector", 1, "product_manager")
        print(f"After product_manager approval: all_approved={approved}")
    else:
        print("Model not registered (below threshold).")

# ============================================================
# KEY TAKEAWAYS
# ============================================================
# - A model registry is NOT optional in production. It is the source
#   of truth for "what model is deployed and why."
# - Archive, never delete. Old versions are your rollback and audit trail.
# - Every version must carry: metrics, git SHA, data version, feature schema.
#   If any of these are missing, the model is not reproducible.
# - DVC provides the data versioning that completes the lineage story.
#   git SHA (code) + DVC hash (data) = fully reproducible model.
# - Enforce an evaluation gate — only register models that beat the baseline.
# - Require documented human approval before Production promotion.
#   Automate everything up to Staging; keep Production promotion human-gated.
