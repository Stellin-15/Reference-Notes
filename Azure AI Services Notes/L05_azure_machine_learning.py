# ============================================================
# L05: Azure Machine Learning — Workspaces, Pipelines, Endpoints, Registry
# ============================================================
# WHAT: Azure ML as the platform for training, tracking, and deploying
#       CUSTOM models — workspaces, compute clusters, pipeline
#       orchestration, the model registry, and managed online endpoints
#       — as distinct from calling a pre-trained foundation model via
#       Azure OpenAI (L02).
# WHY: MLOps Notes covers the discipline generically (MLflow, Feast,
#      model registries, drift monitoring) with provider-agnostic
#      examples. This lesson is "MLOps Notes, but specifically how it's
#      done on Azure ML" — the concrete service names and APIs an Azure
#      AI Engineer role expects.
# LEVEL: Core (Lesson 5 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
Azure OpenAI (L02) gives you access to models Microsoft/OpenAI already
trained. Azure Machine Learning is for when you need to train, fine-
tune, or deploy YOUR OWN model — a custom classifier, a fine-tuned
smaller model, a traditional ML pipeline (fraud detection, credit
scoring) — and need the full lifecycle: experiment tracking, versioned
artifacts, reproducible training, and managed deployment.

WORKSPACE: the top-level container
--------------------------------------
An Azure ML WORKSPACE is the project-level container — it holds
COMPUTE (clusters/instances), DATASTORES (references to Blob/ADLS
storage, not the data itself), registered DATA ASSETS and MODELS,
EXPERIMENTS (grouped training runs), and ENDPOINTS. Everything else in
this lesson lives inside one workspace, analogous to how everything in
L01's resource hierarchy lives inside a resource group.

COMPUTE: instances vs clusters
------------------------------------
- Compute INSTANCE: a single, always-on (or start/stop) VM for
  interactive development — the Azure ML equivalent of a notebook
  server, used for exploration, not production training.
- Compute CLUSTER: an auto-scaling pool of nodes (scales to zero when
  idle) for actual training jobs — you submit a job, the cluster spins
  up nodes to run it, then scales back down. This is what a production
  training pipeline targets, never a compute instance.

EXPERIMENT TRACKING: MLflow-compatible
-------------------------------------------
Azure ML's tracking is MLflow-COMPATIBLE — the same `mlflow.log_metric`,
`mlflow.log_param`, `mlflow.log_model` calls used in MLOps Notes L02
work against an Azure ML workspace as the tracking backend, with the
Azure ML Studio UI as the run-comparison surface instead of a
self-hosted MLflow server. This means teams already using MLflow
locally don't need new tooling, just a different tracking URI.

PIPELINES: reproducible, versioned training DAGs
-------------------------------------------------------
An Azure ML PIPELINE is a DAG of COMPONENTS (each a versioned,
reusable step — e.g. "preprocess," "train," "evaluate") with typed
inputs/outputs, directly analogous to the orchestration patterns in
MLOps Notes L04 (Kubeflow Pipelines, Metaflow) but Azure-native.
Pipelines are what makes training REPRODUCIBLE — the exact code
version, environment (a versioned Docker/conda spec), and data version
used for a given model are all captured, so "which exact code produced
model v17" is always answerable.

MODEL REGISTRY & DEPLOYMENT: managed online endpoints
------------------------------------------------------------
Trained models are REGISTERED (versioned, with lineage back to the
training run and pipeline that produced them — directly parallel to
MLOps Notes L07's model registry concepts) and then deployed to a
MANAGED ONLINE ENDPOINT — a REST endpoint Azure ML provisions,
autoscales, and monitors, supporting BLUE/GREEN traffic splitting
between deployments (e.g. 90% to the current production model, 10% to
a challenger) for safe rollout — the same canary/shadow deployment
patterns covered generically in MLOps Notes L12, expressed as Azure ML
deployment configuration rather than custom infrastructure.

AZURE ML vs AZURE DATABRICKS: when each wins
--------------------------------------------------
Both can train models, which causes real confusion. Azure Databricks
(mentioned in this domain's job market and covered for its Spark/Delta
Lake strengths in Data Engineering Notes L05-L06) is the right choice
when the workload is fundamentally DATA-ENGINEERING-heavy — large-scale
Spark transformations, feature computation over huge datasets, where
model training is one step at the end of a big data pipeline. Azure ML
is the right choice when the workload is ML-LIFECYCLE-heavy — many
training experiments, hyperparameter sweeps, a need for a first-class
model registry and managed inference endpoints — even against smaller
datasets. Many production architectures use BOTH: Databricks for
feature engineering at scale, Azure ML for experiment tracking, the
registry, and endpoint deployment of the resulting model.

PRODUCTION USE CASE:
A fraud-detection model is trained via an Azure ML pipeline (fetch
features prepared upstream by an Azure Databricks job -> train
XGBoost -> evaluate against a held-out set -> register if it beats the
current production model's AUC), deployed to a managed online endpoint
with a 95/5 blue/green split against the incumbent model, monitored via
Azure Monitor for latency and prediction-distribution drift (L08), and
promoted to 100% traffic only after a defined observation window with
no degradation.

COMMON MISTAKES:
- Running production training jobs on a compute INSTANCE instead of a
  CLUSTER — instances aren't designed for unattended, scheduled,
  reproducible training and don't autoscale to zero cost when idle.
- Deploying a model to an endpoint without going through the registry —
  skipping registration loses the lineage link back to the exact
  training run/data/code version that produced it, which is exactly the
  audit trail regulated deployments require.
- Confusing Azure ML and Azure Databricks as competing products rather
  than complementary ones — the common production pattern chains them,
  it doesn't pick one exclusively.
- Deploying straight to 100% traffic instead of a blue/green or
  shadow rollout — skips the safety net MLOps Notes L12 covers in
  depth, and Azure ML's endpoint traffic-splitting makes this nearly
  free to do correctly.
- Not versioning the training ENVIRONMENT (the Docker/conda spec)
  alongside the code and data — "works on my compute instance" drift
  between training and deployment environments reintroduces the
  training-serving skew problem MLOps Notes L01/L06 warn about.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Workspace + compute cluster (auto-scaling, not an always-on instance)
# ------------------------------------------------------------------
COMPUTE_CLUSTER_EXAMPLE = textwrap.dedent("""\
    from azure.ai.ml import MLClient
    from azure.ai.ml.entities import AmlCompute
    from azure.identity import DefaultAzureCredential

    ml_client = MLClient(
        DefaultAzureCredential(), subscription_id, resource_group, workspace_name
    )

    cluster = AmlCompute(
        name="train-cluster",
        size="Standard_DS3_v2",
        min_instances=0,      # scales to ZERO when idle -- no idle cost
        max_instances=4,
        idle_time_before_scale_down=300,
    )
    ml_client.compute.begin_create_or_update(cluster).result()
""")

# ------------------------------------------------------------------
# 2. MLflow-compatible experiment tracking against an Azure ML workspace
# ------------------------------------------------------------------
MLFLOW_TRACKING_EXAMPLE = textwrap.dedent("""\
    import mlflow

    mlflow.set_tracking_uri(ml_client.workspaces.get(workspace_name).mlflow_tracking_uri)
    mlflow.set_experiment("fraud-detection-v2")

    with mlflow.start_run():
        model = train_xgboost(X_train, y_train, **hyperparams)
        mlflow.log_params(hyperparams)
        mlflow.log_metric("val_auc", evaluate(model, X_val, y_val))
        mlflow.sklearn.log_model(model, artifact_path="model")
        # Same mlflow.* API as MLOps Notes L02 -- Azure ML is the
        # tracking BACKEND, not a different tracking API.
""")

# ------------------------------------------------------------------
# 3. Register a model with lineage, deploy to a blue/green endpoint
# ------------------------------------------------------------------
REGISTER_AND_DEPLOY_EXAMPLE = textwrap.dedent("""\
    from azure.ai.ml.entities import Model, ManagedOnlineEndpoint, ManagedOnlineDeployment

    registered_model = ml_client.models.create_or_update(
        Model(
            path=f"runs:/{run_id}/model",   # lineage back to the exact training run
            name="fraud-detector",
            version="17",
        )
    )

    endpoint = ManagedOnlineEndpoint(name="fraud-detector-endpoint")
    ml_client.online_endpoints.begin_create_or_update(endpoint).result()

    challenger_deployment = ManagedOnlineDeployment(
        name="challenger-v17",
        endpoint_name="fraud-detector-endpoint",
        model=registered_model.id,
        instance_type="Standard_DS3_v2",
        instance_count=2,
    )
    ml_client.online_deployments.begin_create_or_update(challenger_deployment).result()

    # 95% incumbent, 5% challenger -- observe before promoting further,
    # same canary discipline as MLOps Notes L12.
    endpoint.traffic = {"incumbent-v16": 95, "challenger-v17": 5}
    ml_client.online_endpoints.begin_create_or_update(endpoint).result()
""")

AZURE_ML_VS_DATABRICKS = {
    "Large-scale Spark feature engineering": "Azure Databricks",
    "Hyperparameter sweeps, experiment comparison": "Azure ML",
    "Model registry with training-run lineage": "Azure ML",
    "Delta Lake ETL feeding a training set": "Azure Databricks",
    "Managed inference endpoint with traffic splitting": "Azure ML",
}


if __name__ == "__main__":
    print(COMPUTE_CLUSTER_EXAMPLE)
    print(MLFLOW_TRACKING_EXAMPLE)
    print(REGISTER_AND_DEPLOY_EXAMPLE)
    print("=== Azure ML vs Azure Databricks ===")
    for task, tool in AZURE_ML_VS_DATABRICKS.items():
        print(f"{task}: {tool}")

"""
PRODUCTION CONTEXT EXAMPLE:
A bank's fraud-detection platform runs feature engineering as a
scheduled Azure Databricks job writing to Delta Lake, then an Azure ML
pipeline picks up the resulting feature table, runs a hyperparameter
sweep, registers the best model with full lineage back to the exact
Databricks job run and Azure ML training run that produced it, and
deploys it behind a managed online endpoint with a 5% canary split --
promoted to 100% only after a week of monitored precision/recall
parity with the incumbent model, per the risk team's model-governance
sign-off process.
"""
