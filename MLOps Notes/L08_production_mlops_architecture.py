# ============================================================
# L08: Production MLOps Architecture
# ============================================================
# WHAT: The complete system architecture for running machine learning
#       in production at scale — from data ingestion through model
#       training, registry, serving, monitoring, and governance.
#       This is the "big picture" that ties together every other lesson
#       in this series into one coherent platform.
# WHY:  Individual components (pipeline, serving, monitoring) only
#       deliver value when they are connected. A monitoring system that
#       cannot trigger retraining is useless. A registry that doesn't
#       connect to serving is a filing cabinet. The architecture is what
#       makes them a platform — self-healing, self-improving, auditable.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    A production ML platform is a layered system. Each layer has clear
    responsibilities and clean interfaces to adjacent layers. The goal
    is SELF-SERVICE: a data scientist should be able to define a model,
    push code, and have the platform handle training, evaluation,
    registration, serving, monitoring, and retraining — without manual
    ops intervention for the common path. The platform team builds and
    maintains the layers; the ML team uses them.

PRODUCTION USE CASE:
    A recommendation system for an e-commerce platform processes
    2M user events per day. Data flows: Kafka → Spark Streaming →
    Feature Store (Feast + Redis). Training: nightly Airflow DAG →
    Spark feature extraction → XGBoost training on SageMaker →
    MLflow evaluation → registry promotion → Triton serving (500 RPS).
    Monitoring: Prometheus/Grafana for latency, Evidently batch job
    for feature drift, PagerDuty alerts. Weekly retrain + ad-hoc
    triggers on PSI breach. Total team: 4 (2 DS, 1 MLE, 1 data eng).

COMMON MISTAKES:
    1. Building a custom platform from scratch instead of composing
       best-of-breed open-source tools (MLflow, Prefect, Evidently).
       The plumbing takes 80% of the effort and provides 0% of the ML value.
    2. Treating training and serving as separate concerns owned by
       separate teams with no shared interfaces. Features computed in
       training must match features computed at serve time exactly.
    3. No cost controls on training compute — a single errant hyperparameter
       sweep can burn thousands of dollars overnight.
    4. Skipping the governance layer — no audit trail, no RBAC, no data
       lineage. Impossible to comply with GDPR, SOC2, or banking regulations.
    5. Building for one model, not for a platform. The 10th model should
       be easier to deploy than the first, not equally hard.
"""

import logging
import time
import threading
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta
import numpy as np

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1: THE FULL ML PLATFORM STACK (LAYER DIAGRAM)
# ============================================================
#
# ╔══════════════════════════════════════════════════════════════╗
# ║                  GOVERNANCE LAYER                            ║
# ║  Data Lineage (OpenLineage) │ Audit Logs │ RBAC │ Docs       ║
# ╠══════════════════════════════════════════════════════════════╣
# ║                  MONITORING LAYER                            ║
# ║  Prometheus + Grafana │ Evidently drift │ ELK/Loki logs      ║
# ║  PagerDuty alerts     │ Ground truth pipeline                ║
# ╠══════════════════════════════════════════════════════════════╣
# ║                  SERVING LAYER                               ║
# ║  Triton / TorchServe / FastAPI │ API Gateway (Kong/Envoy)    ║
# ║  Online Feature Store (Redis/Feast) │ Canary routing         ║
# ╠══════════════════════════════════════════════════════════════╣
# ║                  REGISTRY LAYER                              ║
# ║  MLflow Model Registry │ Model artifacts (S3/GCS)            ║
# ║  Model lineage graph   │ Approval workflows                  ║
# ╠══════════════════════════════════════════════════════════════╣
# ║                  TRAINING LAYER                              ║
# ║  Compute: K8s / SageMaker / Databricks                       ║
# ║  Orchestration: Airflow / Prefect / Kubeflow                 ║
# ║  Experiment Tracking: MLflow / W&B / Neptune                 ║
# ║  HPO: Optuna / Ray Tune / SageMaker HP Tuning                ║
# ╠══════════════════════════════════════════════════════════════╣
# ║                  DATA LAYER                                  ║
# ║  Data Lake: S3 / GCS / ADLS        │ Catalog: Glue/Unity     ║
# ║  Feature Store: Feast / Tecton     │ Label Store             ║
# ║  Streaming: Kafka / Kinesis        │ Data Quality: GE        ║
# ╚══════════════════════════════════════════════════════════════╝
#
# Interfaces between layers:
#   Data → Training:   Feature Store SDK (read offline features)
#   Training → Registry: MLflow log_model() API
#   Registry → Serving: Load model by alias/stage from registry
#   Serving → Monitoring: Prometheus metrics + prediction logs to S3
#   Monitoring → Training: Drift alert → trigger retraining DAG


# ============================================================
# SECTION 2: CI/CD FOR ML (DIFFERENT FROM SOFTWARE CI/CD)
# ============================================================
# Software CI/CD: code changes → tests → build → deploy artifact.
# ML CI/CD: code changes → tests → RETRAIN → evaluate → deploy MODEL.
#           Data changes → RETRAIN → evaluate → deploy MODEL.
#           Drift alert  → RETRAIN → evaluate → deploy MODEL.
# The artifact is NOT the code — it's the trained model.
# Three triggers, one pipeline:

# ────────────────────────────────────────────────────────────
# TRIGGER 1: CODE CHANGE (git push → CI pipeline)
# ────────────────────────────────────────────────────────────
# Stage 1: lint (ruff, black, mypy)
# Stage 2: unit tests (pytest — mock model, fast)
# Stage 3: integration tests (train on 1% sample data, evaluate)
#           → if metrics regress vs baseline: FAIL, stop.
# Stage 4: full retrain on complete dataset (SageMaker/K8s job)
# Stage 5: evaluate vs current champion in registry
#           → if new model AUC < champion AUC: FAIL, notify team.
# Stage 6: register new model to Staging in MLflow registry
# Stage 7: deploy to staging environment
# Stage 8: integration tests against staging endpoint
# Stage 9: MANUAL GATE — ML engineer + PM review and approve
# Stage 10: blue/green or canary deploy to production
# Stage 11: smoke test production endpoint
# Stage 12: monitor for 24h → auto-complete rollout or rollback

# ────────────────────────────────────────────────────────────
# TRIGGER 2: DATA CHANGE (new data arrives)
# ────────────────────────────────────────────────────────────
# Detect new data: Airflow schedule or S3 event notification
# Run data validation (Great Expectations)
#   → if data quality fails: halt, alert data engineering team
# Trigger retraining pipeline (same as stages 4-12 above)
# Notify team of new model candidate

# ────────────────────────────────────────────────────────────
# TRIGGER 3: MODEL DECAY (monitoring detects drift/degradation)
# ────────────────────────────────────────────────────────────
# Evidently batch job: PSI > 0.25 on important feature
# OR: Performance monitoring: AUC < 0.85 on labeled window
# → Trigger retraining pipeline
# → If still degraded after retrain: escalate to human (PagerDuty)
#
# WHY SEPARATE FROM CODE CHANGE TRIGGER:
#   Data-triggered retraining uses the same model code (no code change).
#   It only updates the training data window (e.g., retrain on last 90 days).
#   The evaluation gate is: new model > current production model.

# ============================================================
# SECTION 3: INFRASTRUCTURE AS CODE FOR ML
# ============================================================
# Treat ALL ML infrastructure as code — version controlled, reviewed,
# and applied automatically. Three layers of IaC in an ML platform:

# TERRAFORM (cloud resources):
#   - S3 buckets: raw data, processed features, model artifacts
#   - SageMaker domain + user profiles
#   - EKS cluster (for Kubeflow/Airflow/model serving)
#   - RDS PostgreSQL (MLflow backend store)
#   - ElastiCache Redis (online feature store)
#   - IAM roles and policies (least privilege per service)
#   - VPC, subnets, security groups
#
# resource "aws_s3_bucket" "mlflow_artifacts" {
#   bucket = "company-mlflow-artifacts-${var.environment}"
#   lifecycle { prevent_destroy = true }  # never accidentally delete
# }
# resource "aws_db_instance" "mlflow_db" {
#   engine = "postgres"
#   instance_class = "db.t3.medium"
#   allocated_storage = 100
#   deletion_protection = true
# }

# KUBERNETES MANIFESTS (for model serving):
#   Deployment (model server pods, rolling update strategy)
#   Service (ClusterIP for internal, LoadBalancer for external)
#   HorizontalPodAutoscaler (scale on CPU/GPU utilization)
#   PodDisruptionBudget (ensure minimum pods available during upgrade)
#   ConfigMap (model serving config, env vars)
#
# Example HPA for model serving:
# apiVersion: autoscaling/v2
# kind: HorizontalPodAutoscaler
# spec:
#   scaleTargetRef:
#     kind: Deployment
#     name: fraud-model-server
#   minReplicas: 3      # never scale below 3 for availability
#   maxReplicas: 20
#   metrics:
#   - type: Resource
#     resource:
#       name: cpu
#       target:
#         type: Utilization
#         averageUtilization: 60   # scale when avg CPU > 60%

# HELM CHARTS (packaged K8s applications):
#   helm install mlflow mlflow/mlflow \
#     --set backendStore.postgres.host=$POSTGRES_HOST \
#     --set artifactRoot=s3://company-mlflow-artifacts/prod
#
# ARGOCD (GitOps):
#   Model serving manifests live in a git repo.
#   ArgoCD watches the repo and automatically syncs changes to K8s.
#   Deploying a new model version = update image tag in git → ArgoCD applies.
#   Rollback = git revert → ArgoCD applies the previous manifest.

# ============================================================
# SECTION 4: COST OPTIMIZATION
# ============================================================
# ML compute is expensive. Unconstrained, a team can spend $50K+/month
# on a single model's training and serving infrastructure.
# Cost optimization at each layer:

# TRAINING COMPUTE:
#   Spot/Preemptible instances: 70% savings vs on-demand.
#   Risk: instance can be terminated mid-training.
#   Solution: checkpoint every N epochs to S3. Resume from checkpoint.
#
#   # PyTorch checkpoint pattern:
#   # if step % checkpoint_interval == 0:
#   #     torch.save({
#   #         "epoch": epoch,
#   #         "model_state_dict": model.state_dict(),
#   #         "optimizer_state_dict": optimizer.state_dict(),
#   #         "loss": current_loss,
#   #     }, f"s3://bucket/checkpoints/model_step_{step}.pt")
#   # On restart: load latest checkpoint and resume from that step.
#
#   Experiment pruning: kill bad HPO trials early (Optuna + Hyperband).
#   Don't run 100 trials to completion — stop bottom 50% after 10 epochs.
#
#   Right-sizing: train profiling job first. If GPU utilization is <30%,
#   the model is CPU-bound — use cheaper CPU instance.

# SERVING COMPUTE:
#   Reserved instances for baseline load (30-50% savings).
#   Spot for burst handling (with graceful drain on termination).
#   Multi-model serving: pack multiple small models on one GPU.
#   Triton concurrent model execution: 4 fraud models on one A10G.
#   Model compression: 4-bit quantization = 4x smaller = smaller instance.
#
#   Cost formula:
#     Monthly serving cost = (instance_cost/hr × 24 × 30) × n_instances
#     + (n_requests × cost_per_request)  ← for managed endpoints
#
#   Optimization: reduce n_instances via batching + caching.
#   Cache predictions for (user_id, context) with 5-minute TTL.
#   Reduces inference calls by 30-60% for repeat users.

# HPO COST CONTROL:
#   Set maximum trials: optuna.create_study(..., n_trials=50)
#   Set maximum time: study.optimize(objective, timeout=3600)  # 1 hour max
#   Set per-trial budget: stop trial if not showing improvement by epoch 5
#   Use cheap proxy metrics early: train on 10% of data for trial selection,
#   then train the winner on 100%.

# ============================================================
# SECTION 5: SCALING FROM 1 MODEL TO 100 MODELS
# ============================================================
# The difference between 1 model and 100 models is PLATFORM THINKING.
# The 10th model should take 1 day to deploy, not 3 weeks.

# THE PLATFORM APPROACH:
#   1. Build templates (not one-off solutions)
#      - Training pipeline template (Cookiecutter or internal CLI)
#      - Serving template (Helm chart or Terraform module)
#      - Monitoring template (auto-generated Grafana dashboard)
#   2. Self-service: data scientist runs `mlops new-project fraud_v3`
#      → gets a repo with training pipeline, serving config, monitoring
#      → pushes code → platform handles the rest
#   3. Standardize interfaces:
#      - All models accept the same request format (or have schema-validated wrappers)
#      - All models expose /health and /ready
#      - All models push metrics to same Prometheus instance
#   4. Model catalog: internal web UI showing all models in prod,
#      their performance, owners, last retrain date, serving load.
#      The single pane of glass for the ML platform.

# ROLES CLEARLY DEFINED (avoid "everyone does everything" chaos):
#
# DATA SCIENTIST:
#   - Owns: feature engineering, model architecture, evaluation strategy
#   - Uses: Feature Store (read), Experiment Tracking, HPO tools
#   - Does NOT need to: write Dockerfiles, configure K8s, manage infra
#
# ML ENGINEER:
#   - Owns: training pipeline, serving infrastructure, model optimization
#   - Uses: training templates, model registry, serving templates
#   - Bridges: data scientist's model code → production system
#
# DATA ENGINEER:
#   - Owns: data pipelines, feature engineering at scale, data quality
#   - Uses: Spark/dbt, Feature Store (write), data catalog
#   - Ensures: training-serving skew is zero (same features in both)
#
# PLATFORM / MLOPS ENGINEER:
#   - Owns: Kubernetes cluster, CI/CD, the ML platform itself
#   - Builds: the templates, the self-service tools, the observability
#   - Ensures: the platform is reliable, cost-efficient, and improving

# ============================================================
# SECTION 6: FULL ARCHITECTURE — RECOMMENDATION SYSTEM
# ============================================================
#
# ARCHITECTURE DIAGRAM (text):
#
#  ┌─────────────┐    ┌──────────────┐    ┌─────────────────┐
#  │ User Events  │───▶│ Kafka Topic  │───▶│ Spark Streaming  │
#  │ (clicks,     │    │ (events)     │    │ (feature compute) │
#  │  views,      │    └──────────────┘    └────────┬────────┘
#  │  purchases)  │                                 │
#  └─────────────┘                                  ▼
#                                          ┌─────────────────┐
#                                          │  Feature Store   │
#                                          │  (Feast + Redis) │
#                                          │  - user_features │
#                                          │  - item_features │
#                                          └────────┬─────────┘
#                                                   │
#                    ┌──────────────────────────────┤
#                    │ Training Path                 │ Serving Path
#                    ▼                              ▼
#           ┌────────────────┐            ┌─────────────────┐
#           │ Airflow DAG    │            │  API Gateway     │
#           │ (daily 02:00)  │            │  (Kong/Envoy)    │
#           └───────┬────────┘            └────────┬─────────┘
#                   │                              │
#                   ▼                              ▼
#           ┌────────────────┐            ┌─────────────────┐
#           │ Spark Feature  │            │  FastAPI/Triton  │
#           │ Extraction     │            │  Model Server   │
#           │ (EMR / GLUE)   │            │  (K8s, 3 pods)  │
#           └───────┬────────┘            └────────┬─────────┘
#                   │                              │
#                   ▼                              │ (fetch features)
#           ┌────────────────┐                    │
#           │ XGBoost Train  │◀───────────────────┘
#           │ (SageMaker)    │            ┌─────────────────┐
#           └───────┬────────┘            │  Redis Feature  │
#                   │                     │  Cache (<10ms)  │
#                   ▼                     └─────────────────┘
#           ┌────────────────┐
#           │ Evaluate       │            ┌─────────────────┐
#           │ AUC > 0.87?    │            │  Prometheus      │
#           └───────┬────────┘            │  + Grafana       │
#                   │                     │  (latency, drift)│
#                   ▼                     └────────┬─────────┘
#           ┌────────────────┐                     │
#           │ MLflow Registry│◀────────────────────┘
#           │ (register if   │       (metrics feed back)
#           │  passes gate)  │
#           └───────┬────────┘
#                   │
#                   ▼
#           ┌────────────────┐
#           │ ArgoCD Deploy  │
#           │ (GitOps →      │
#           │  K8s update)   │
#           └────────────────┘
#
# TRAFFIC FLOW (serving path, per request):
#   1. Client → API Gateway → FastAPI (~2ms overhead)
#   2. FastAPI validates request schema (Pydantic) (~1ms)
#   3. Fetch user features from Redis: user_history, preferences (~8ms)
#   4. gRPC call to Triton inference server (~25ms on GPU with batching)
#   5. Postprocess: rank top-10 items, apply business rules (~5ms)
#   6. Return recommendations (~2ms serialization)
#   Total P50: ~43ms, P99: ~75ms (within 100ms SLA)

# ============================================================
# SECTION 7: INCIDENT RESPONSE FOR ML
# ============================================================
# ML incidents are different from software incidents:
# - No stack trace pointing to the bug
# - May have been degrading for days before detection
# - Root cause could be data, code, infrastructure, OR the world
# - "Fix" might be rollback OR retrain, not a code patch
#
# ML INCIDENT RESPONSE CHECKLIST:
#
# STEP 1: DETECT (automated → PagerDuty fires)
#   Sources: monitoring alert (PSI, AUC, latency), user report,
#            business metric anomaly (revenue drop, CTR drop)
#
# STEP 2: TRIAGE (first 15 minutes)
#   □ Is the serving infrastructure broken? (latency spike, error rate)
#     → Check Grafana: serving latency, error rate, pod health
#   □ Is the data pipeline broken? (null features, wrong schema)
#     → Check feature store freshness timestamps
#     → Check upstream data pipeline status (Airflow/Prefect UI)
#   □ Is the model drifted? (predictions changed, PSI alert)
#     → Check drift dashboard: which features are drifted
#     → Check prediction distribution: did it shift suddenly?
#   □ Was there a recent code or config deploy?
#     → Check ArgoCD deployment history: any change in last 24h?
#
# STEP 3: IMMEDIATE MITIGATION (first 30 minutes)
#   If serving is broken:     → rollback to previous Docker image (ArgoCD)
#   If model is misbehaving:  → rollback to previous champion model version
#     (MLflow registry: transition archived version back to Production)
#   If data pipeline is broken: → serve from cache or return default predictions
#   Rollback SLA: < 10 minutes for model rollback, < 20 min for infra rollback
#
# STEP 4: ROOT CAUSE INVESTIGATION (next few hours)
#   □ Reproduce the issue in staging with the same data
#   □ Check data pipeline lineage (OpenLineage: which upstream table changed?)
#   □ Check feature store: are features being computed correctly?
#   □ Review recent model training runs: did evaluation miss something?
#   □ Check if feature engineering differs between training and serving
#     (training-serving skew — the most insidious ML bug)
#
# STEP 5: FIX AND VERIFY
#   If drift: retrain with recent data, evaluate, promote via normal workflow
#   If data bug: fix upstream pipeline, validate data, retrain
#   If code bug: fix, unit test, integration test, deploy via CI/CD
#   If serving bug: fix config, redeploy, load test before promoting
#
# STEP 6: POST-MORTEM (within 5 business days)
#   □ Timeline: when did degradation start, when detected, when fixed?
#   □ Impact: how many users affected? What business metric impact?
#   □ Root cause (5 Whys)
#   □ Detection: why wasn't this caught sooner? What monitoring gap?
#   □ Action items: specific improvements to monitoring, testing, process

# ============================================================
# SECTION 8: TRAINING-SERVING SKEW — THE MOST DANGEROUS BUG
# ============================================================
# Training-serving skew: the model sees DIFFERENT features at serve time
# than it saw during training. Silent and catastrophic.
#
# CAUSES:
#   1. Feature engineering reimplemented differently in the serving stack
#      (trained with log1p(amount), serving uses raw amount)
#   2. Data types differ (float64 in training, float32 in serving)
#   3. Missing value handling differs (fillna(0) in training,
#      nulls passed through at serving time)
#   4. Feature ordering differs (model reads column 2 as "hour",
#      but serving sends "hour" as column 3)
#   5. Temporal features computed with different time zones
#
# SOLUTIONS:
#   A. USE A FEATURE STORE: Feast/Tecton ensure offline (training) and
#      online (serving) features are computed by the SAME code.
#      No reimplementation = no skew.
#   B. SAVE PREPROCESSING IN THE MODEL ARTIFACT: sklearn Pipeline() wraps
#      scaler + encoder + model in one object. Serving loads one artifact.
#      No separate preprocessing to re-implement.
#   C. VALIDATION: at serving time, log a sample of input features.
#      Daily job compares serving features vs training feature distribution.
#      PSI alert if they diverge — may indicate skew or drift.
#   D. INTEGRATION TESTS: use saved training feature vectors as test fixtures
#      for the serving endpoint. If model output changes, test fails.

# ============================================================
# SECTION 9: PLATFORM COMPONENTS REFERENCE TABLE
# ============================================================
# (Use this when making technology choices for a new ML platform)
#
# CATEGORY          OPEN SOURCE             MANAGED / CLOUD
# ─────────────────────────────────────────────────────────────────
# Orchestration     Airflow, Prefect,       MWAA (AWS), Cloud
#                   Dagster, Metaflow       Composer (GCP)
# Experiment Track  MLflow, Neptune         W&B, Comet ML
# Feature Store     Feast                   Tecton, SageMaker FS,
#                                           Vertex Feature Store
# Model Registry    MLflow Registry         SageMaker Registry,
#                                           Vertex Model Registry
# Serving           FastAPI, TorchServe,    SageMaker Endpoints,
#                   Triton, BentoML         Vertex AI Endpoints
# Pipeline (K8s)    Kubeflow Pipelines      Vertex AI Pipelines
# Monitoring        Evidently, Whylogs      Arize, Fiddler, Aporia
# Infrastructure    Terraform, Helm,        AWS CloudFormation,
#                   ArgoCD                  GCP Deployment Manager
# HPO               Optuna, Ray Tune        SageMaker HP Tuning
# Data Versioning   DVC, Delta Lake         LakeFormation
# Data Quality      Great Expectations,     Monte Carlo,
#                   Pandera                 Bigeye
# ─────────────────────────────────────────────────────────────────
# RECOMMENDATION: Start with MLflow + Prefect + Evidently + FastAPI.
#   Open source, well-supported, can run locally. Migrate to managed
#   services when the operational overhead of self-hosting exceeds
#   the cost difference.

# ============================================================
# SECTION 10: MINIMAL VIABLE ML PLATFORM (MVP)
# ============================================================
# For a team of 2-5 starting from scratch, build this first:
# (Don't build the full platform on day one — you'll never ship models)


class MinimalMLPlatform:
    """
    Demonstrates the MVP ML platform: just enough to be production-grade
    without over-engineering. This is what you build in month 1-3.
    Later layers (feature store, advanced monitoring) are added as needed.

    MVP Components:
      - MLflow for experiment tracking + model registry
      - Prefect for pipeline orchestration
      - FastAPI for model serving
      - Prometheus + Grafana for monitoring
      - GitHub Actions for CI/CD

    This class is a CONCEPTUAL example — each method represents
    a real component that would be a separate service in production.
    """

    def __init__(self):
        self.registered_models: Dict[str, dict] = {}  # model store (sim)
        self.production_model: Optional[dict] = None
        self.metrics_buffer: List[dict] = []
        self._lock = threading.Lock()

    # ── Training pipeline (runs on schedule or on data change) ──

    def training_pipeline(self, config: dict) -> Optional[dict]:
        """
        Orchestrated by Prefect (@flow with @task steps).
        Steps: load_data → validate → features → train → evaluate → register.
        Returns model metadata if registered, None if below threshold.
        """
        logger.info(f"Training pipeline started with config={config}")
        rng = np.random.default_rng(42)
        n = 1000

        # Simulate training
        X = rng.standard_normal((n, 3))
        y = (rng.uniform(size=n) < 0.1).astype(int)

        # Simulate evaluation
        auc = rng.uniform(0.80, 0.95)
        passed_gate = auc >= config.get("auc_threshold", 0.85)

        if not passed_gate:
            logger.warning(f"AUC {auc:.4f} below threshold. Not registering.")
            return None

        model_metadata = {
            "model_id": f"model_{int(time.time())}",
            "auc": auc,
            "config": config,
            "trained_at": datetime.utcnow().isoformat(),
            "stage": "Staging",
        }
        with self._lock:
            self.registered_models[model_metadata["model_id"]] = model_metadata

        logger.info(f"Registered: {model_metadata['model_id']}, AUC={auc:.4f}")
        return model_metadata

    # ── Model serving (FastAPI in production) ──

    def predict(self, features: np.ndarray) -> dict:
        """
        The /predict endpoint. Loads champion model from registry.
        In production: loaded once at startup via lifespan event.
        """
        with self._lock:
            if self.production_model is None:
                return {"error": "no_model_in_production", "prediction": 0.5}

        # Simulate inference
        score = float(np.random.uniform(0, 1))
        latency_ms = float(np.random.uniform(10, 50))

        # Record metric (Prometheus in production)
        self.metrics_buffer.append({
            "timestamp": time.time(),
            "latency_ms": latency_ms,
            "score": score,
            "model_id": self.production_model["model_id"],
        })
        return {"prediction": score, "latency_ms": latency_ms}

    # ── Registry + promotion ──

    def promote_to_production(self, model_id: str, approved_by: str):
        """
        Promote a model from Staging to Production.
        Archives the current Production model first.
        In production: calls MLflow client.transition_model_version_stage().
        """
        with self._lock:
            if model_id not in self.registered_models:
                raise ValueError(f"Model {model_id} not found in registry")

            # Archive current production model
            if self.production_model:
                old_id = self.production_model["model_id"]
                self.registered_models[old_id]["stage"] = "Archived"
                logger.info(f"Archived previous production model: {old_id}")

            # Promote new model
            self.registered_models[model_id]["stage"] = "Production"
            self.registered_models[model_id]["approved_by"] = approved_by
            self.registered_models[model_id]["promoted_at"] = (
                datetime.utcnow().isoformat()
            )
            self.production_model = self.registered_models[model_id]
            logger.info(
                f"Promoted {model_id} to Production. Approved by {approved_by}"
            )

    # ── Monitoring ──

    def drift_check(self, baseline_scores: np.ndarray) -> dict:
        """
        Compare recent prediction scores vs baseline distribution.
        Simplified drift check on model outputs (proxy for feature drift).
        In production: Evidently DataDriftPreset on all input features.
        """
        if len(self.metrics_buffer) < 50:
            return {"status": "insufficient_data", "n_predictions": len(self.metrics_buffer)}

        recent_scores = np.array([m["score"] for m in self.metrics_buffer[-200:]])
        mean_delta = abs(recent_scores.mean() - baseline_scores.mean())
        drift_detected = mean_delta > 0.15  # simplified threshold

        return {
            "baseline_mean": float(baseline_scores.mean()),
            "current_mean":  float(recent_scores.mean()),
            "mean_delta":    float(mean_delta),
            "drift_detected": drift_detected,
            "n_recent_predictions": len(recent_scores),
        }

    # ── Incident response: rollback ──

    def rollback_to_previous(self) -> Optional[dict]:
        """
        Find the most recently archived model and promote it.
        In production: MLflow transition Archived → Production.
        Target: < 10 minute rollback time.
        """
        with self._lock:
            archived = [
                m for m in self.registered_models.values()
                if m["stage"] == "Archived"
            ]
            if not archived:
                logger.error("No archived models available for rollback!")
                return None

            # Most recently archived model
            prev = max(archived, key=lambda m: m.get("promoted_at", ""))
            prev["stage"] = "Production"
            self.production_model = prev
            logger.warning(
                f"ROLLBACK: restored {prev['model_id']} to Production"
            )
            return prev


# ============================================================
# DEMONSTRATION — end-to-end MVP platform workflow
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    platform = MinimalMLPlatform()

    # 1. Train and register model v1
    print("=== Training Pipeline: Run 1 ===")
    model_v1 = platform.training_pipeline({
        "n_estimators": 100, "max_depth": 4, "auc_threshold": 0.75
    })
    if model_v1:
        platform.promote_to_production(model_v1["model_id"], approved_by="alice")
        print(f"Production: {model_v1['model_id']}, AUC={model_v1['auc']:.4f}")

    # 2. Serve some predictions
    print("\n=== Serving 10 predictions ===")
    for i in range(10):
        result = platform.predict(np.random.standard_normal(3))
    print(f"Predictions served. Buffer size: {len(platform.metrics_buffer)}")

    # 3. Train model v2
    print("\n=== Training Pipeline: Run 2 ===")
    model_v2 = platform.training_pipeline({
        "n_estimators": 200, "max_depth": 5, "auc_threshold": 0.75
    })
    if model_v2:
        platform.promote_to_production(model_v2["model_id"], approved_by="alice")
        print(f"New Production: {model_v2['model_id']}, AUC={model_v2['auc']:.4f}")

    # 4. Drift check
    print("\n=== Drift Check ===")
    baseline = np.random.uniform(0.1, 0.4, size=200)
    drift_result = platform.drift_check(baseline)
    print(f"Drift result: {drift_result}")

    # 5. Rollback demo
    print("\n=== Rollback Demo ===")
    prev = platform.rollback_to_previous()
    if prev:
        print(f"Rolled back to: {prev['model_id']}")

    # 6. Registry summary
    print("\n=== Registry State ===")
    for mid, meta in platform.registered_models.items():
        print(f"  {mid[:25]} | stage={meta['stage']:<12} | AUC={meta['auc']:.4f}")

# ============================================================
# KEY TAKEAWAYS
# ============================================================
# - The platform stack has six layers. Each layer has one owner
#   and clean interfaces to adjacent layers.
# - ML CI/CD has three triggers: code change, data change, drift alert.
#   All three lead to the same retraining + evaluation + deploy pipeline.
# - Use IaC for everything: Terraform (cloud), Helm (K8s), ArgoCD (GitOps).
#   "Click-ops" infrastructure is untraceable and unreproducible.
# - Cost optimization: spot instances for training (70% savings),
#   reserved for serving, HPO with early stopping, model compression.
# - Scale from 1→100 models via platform thinking: templates, self-service,
#   standardized interfaces. The 10th model should be 10x easier than the 1st.
# - Training-serving skew is the most dangerous silent bug. Use a feature
#   store or save preprocessing inside the model artifact to prevent it.
# - Incident response is a practiced skill: have the checklist ready,
#   know how to rollback in under 10 minutes, do post-mortems.
