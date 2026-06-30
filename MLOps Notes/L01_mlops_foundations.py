# ============================================================
# L01: MLOps Foundations
# ============================================================
# WHAT: MLOps (Machine Learning Operations) is the discipline of applying
#       DevOps principles — automation, CI/CD, monitoring, collaboration —
#       to the full machine learning lifecycle. It bridges the gap between
#       data science (experimentation) and software engineering (production).
#
# WHY:  Without MLOps, 87% of ML models never reach production (Gartner).
#       Even those that do degrade silently, are unreproducible, and cost
#       enormous manual effort to maintain. MLOps is the engineering system
#       that makes ML reliable, scalable, and sustainable at enterprise scale.
#
# LEVEL: Foundations
# ============================================================
"""
CONCEPT OVERVIEW:
    MLOps combines practices from DevOps, DataOps, and ModelOps to create
    a systematic approach to building, deploying, and maintaining ML systems.
    It treats models as living artifacts that must be continuously monitored,
    retrained, and governed — not as static software deliverables.

PRODUCTION USE CASE:
    A recommendation engine at a streaming platform: millions of users, model
    trained on watch history, deployed to 10 regions, retrained daily, monitored
    for drift when new content is added. Without MLOps, this is impossible to
    maintain with a small team. With MLOps, a 5-person team can run it reliably.

COMMON MISTAKES:
    - Treating MLOps as a tool purchase rather than a cultural and process shift.
    - Skipping MLOps investment at "small scale" and then facing impossible
      migration debt when the system grows.
    - Over-engineering MLOps for a single model that runs monthly. Match
      investment to actual operational complexity.
    - Neglecting data versioning — if you can't reproduce the training data,
      you can't reproduce the model, no matter how good your code versioning is.
"""


# ============================================================
# SECTION 1: WHY ML IS DIFFERENT FROM TRADITIONAL SOFTWARE
# ============================================================
# Traditional software: deterministic, input → output defined by code.
# ML systems: behavior defined by data + code + hyperparameters.
# This introduces unique failure modes that DevOps alone cannot address.

# THE FOUR HIDDEN TECHNICAL DEBT PROBLEMS IN ML (Sculley et al., 2015 Google paper):
# 1. ENTANGLEMENT: Change input features → behavior of ALL features changes (CACE: Change
#    Anything, Change Everything). Unlike software, you can't isolate changes easily.
# 2. CORRECTION CASCADES: Model A feeds Model B. Error in A silently corrupts B.
# 3. UNDECLARED CONSUMERS: Other teams start depending on your model's outputs
#    (predictions) without telling you. You change the model → they break.
# 4. DATA DEPENDENCIES: Legacy pipelines, upstream schema changes, and undocumented
#    data sources create fragile systems that are worse than code dependencies.

# KEY DIFFERENCES requiring MLOps:
differences_ml_vs_software = {
    "reproducibility": {
        "software": "Same code + same input = same output (deterministic)",
        "ml": "Same code + same data + same seed = same model... maybe. "
              "GPU non-determinism, framework versions, OS differences all matter.",
        "mlops_solution": "Containerization (Docker), seed management, environment pinning"
    },
    "data_dependencies": {
        "software": "Input/output schemas are explicitly defined",
        "ml": "Model quality depends on data quality, distribution, and volume. "
              "Silent schema drift in upstream databases breaks training silently.",
        "mlops_solution": "Great Expectations, data contracts, schema validation in pipelines"
    },
    "non_determinism": {
        "software": "Same code = same behavior",
        "ml": "Training is stochastic. Two runs produce different models. "
              "Which one went to production? What were its exact metrics?",
        "mlops_solution": "Experiment tracking (MLflow, W&B), model registry with metadata"
    },
    "model_decay": {
        "software": "Software doesn't degrade unless you change it",
        "ml": "World changes → data distribution shifts → model accuracy decays "
              "without any code or data changes in your system. Invisible failure.",
        "mlops_solution": "Continuous monitoring, drift detection, automated retraining"
    },
    "experiment_management": {
        "software": "Code review captures all relevant changes",
        "ml": "Hyperparameter tuning generates hundreds of experiments. "
              "Which params produced which metric? Which dataset version was used?",
        "mlops_solution": "Experiment tracking with full parameter/metric/artifact logging"
    },
    "evaluation_complexity": {
        "software": "Unit tests pass or fail",
        "ml": "Model evaluation requires business metric alignment, fairness checks, "
              "sliced performance (does it work for minority groups?), A/B tests.",
        "mlops_solution": "Model evaluation pipelines with multiple metric thresholds"
    }
}


# ============================================================
# SECTION 2: THE ML LIFECYCLE
# ============================================================
# Unlike the software SDLC which is largely linear, the ML lifecycle is cyclical.
# Models are never "done" — they require continuous monitoring and retraining.

ml_lifecycle_stages = [
    {
        "stage": "1. Problem Definition",
        "activities": [
            "Translate business problem to ML problem type (classification, regression, ranking...)",
            "Define success metrics (offline: AUC, RMSE; online: CTR, revenue, retention)",
            "Assess feasibility: do we have data? Is the signal strong enough?",
            "Define SLAs: latency, throughput, availability requirements",
        ],
        "key_outputs": ["ML problem statement", "Success metric definitions", "Data availability assessment"],
        "common_mistake": "Skipping feasibility. Teams spend 6 months building a model for a "
                         "problem where the signal-to-noise ratio is fundamentally too low.",
    },
    {
        "stage": "2. Data Collection and Labeling",
        "activities": [
            "Identify data sources: databases, logs, external APIs, third-party datasets",
            "Data labeling: human annotation (Scale AI, Labelbox), programmatic labeling (Snorkel)",
            "Data quality assessment: duplicates, nulls, schema consistency",
            "Legal/compliance check: PII, GDPR, data retention policies",
        ],
        "key_outputs": ["Raw dataset", "Label schema", "Data quality report"],
        "common_mistake": "Collecting data first, asking about labels later. Label schema "
                         "design is a modeling decision — it must align with the ML objective.",
    },
    {
        "stage": "3. Exploratory Data Analysis (EDA)",
        "activities": [
            "Distribution analysis of features and target",
            "Correlation analysis, feature importance proxies",
            "Identify class imbalance, outliers, temporal patterns",
            "Understand missingness patterns (MCAR, MAR, MNAR — matters for imputation strategy)",
        ],
        "key_outputs": ["EDA notebook", "Feature selection candidates", "Data cleaning decisions"],
        "common_mistake": "Skipping EDA and going straight to modeling. EDA reveals data "
                         "issues that invalidate the entire modeling effort if caught late.",
    },
    {
        "stage": "4. Feature Engineering",
        "activities": [
            "Transform raw data into model-ready features",
            "Categorical encoding (one-hot, target encoding, embeddings)",
            "Numerical transformations (log, Box-Cox, StandardScaler)",
            "Time-based features: lag features, rolling statistics, cyclical encoding",
            "Feature selection to reduce dimensionality and training time",
        ],
        "key_outputs": ["Feature pipeline code", "Feature documentation", "Training dataset"],
        "common_mistake": "Feature logic in ad-hoc notebooks, not versioned code. "
                         "Production serving uses different feature logic → training-serving skew.",
    },
    {
        "stage": "5. Model Training and Experimentation",
        "activities": [
            "Baseline model first (simple rules, logistic regression)",
            "Systematic experiment tracking of all runs",
            "Hyperparameter optimization (grid search, Bayesian, random search)",
            "Cross-validation strategy aligned with deployment scenario",
        ],
        "key_outputs": ["Trained model artifact", "Experiment tracking records", "Model card"],
        "common_mistake": "Jumping to complex models before establishing a strong baseline. "
                         "A gradient boosted tree often beats a neural network on tabular data.",
    },
    {
        "stage": "6. Model Evaluation",
        "activities": [
            "Offline evaluation on held-out test set (never touched during experimentation)",
            "Sliced evaluation: performance by user segment, geographic region, time period",
            "Fairness/bias analysis across protected attributes",
            "Behavioral testing: directional tests, invariance tests, minimum functionality tests",
            "Comparison against current production model (challenger vs champion)",
        ],
        "key_outputs": ["Evaluation report", "Model card", "Go/no-go decision"],
        "common_mistake": "Evaluating only on aggregate metrics. A model with 95% accuracy "
                         "that completely fails on a minority subgroup is not production-ready.",
    },
    {
        "stage": "7. Model Deployment",
        "activities": [
            "Containerize model + inference code",
            "Set up API (REST or gRPC) with health checks",
            "Configure auto-scaling, load balancing",
            "Staged rollout: canary → shadow → blue/green → full traffic",
        ],
        "key_outputs": ["Serving infrastructure", "API documentation", "Deployment runbook"],
        "common_mistake": "Deploying without a rollback plan. Always have the previous model "
                         "version staged and ready to serve within minutes.",
    },
    {
        "stage": "8. Monitoring and Observability",
        "activities": [
            "Monitor prediction distribution and input feature distributions",
            "Track business metrics (conversion, revenue) correlated with model changes",
            "Monitor infrastructure metrics (latency, error rate, throughput)",
            "Collect ground truth labels when available",
        ],
        "key_outputs": ["Monitoring dashboards", "Alert rules", "Drift detection reports"],
        "common_mistake": "Only monitoring infrastructure (latency, uptime). Model accuracy "
                         "can silently decay while the server responds perfectly fine.",
    },
    {
        "stage": "9. Retraining and Continuous Improvement",
        "activities": [
            "Trigger retraining based on drift detection, schedule, or performance thresholds",
            "Re-run full training pipeline with new data",
            "Evaluate challenger model vs current champion",
            "Promote challenger if it wins evaluation (gated deployment)",
        ],
        "key_outputs": ["Updated model version", "Retraining pipeline", "Promotion decision"],
        "common_mistake": "Manual retraining triggered by developer intuition. This is "
                         "too slow, inconsistent, and doesn't scale past 5 models.",
    }
]


# ============================================================
# SECTION 3: CRISP-DM PROCESS MODEL
# ============================================================
# Cross-Industry Standard Process for Data Mining — the foundational methodology.
# Despite being from 1999, it remains the most widely used ML process framework.
# MLOps extends it with engineering practices for production deployment.

crisp_dm = {
    "1_business_understanding": {
        "what": "Understand the business objective and translate to ML problem",
        "questions": [
            "What decision does this model inform?",
            "What's the cost of a false positive vs false negative?",
            "What baseline are we beating (human, rules, naive model)?",
            "How will the model output be consumed (API, batch report, embedded)?",
        ]
    },
    "2_data_understanding": {
        "what": "Explore and document the available data",
        "questions": [
            "What data is available, where does it live, who owns it?",
            "What is the data quality (completeness, accuracy, timeliness)?",
            "Is there enough data for the problem complexity?",
            "Are there obvious confounders or biases?",
        ]
    },
    "3_data_preparation": {
        "what": "Build the analytical dataset from raw sources",
        "activities": [
            "Join datasets, create aggregations",
            "Handle missing values (impute, drop, flag)",
            "Encode categoricals, normalize numericals",
            "Create training/validation/test splits (respect time boundaries for temporal data)",
        ]
    },
    "4_modeling": {
        "what": "Select and train ML algorithms",
        "activities": [
            "Algorithm selection based on problem type, data size, interpretability needs",
            "Hyperparameter tuning",
            "Ensemble methods (bagging, boosting, stacking)",
            "Feature importance and model introspection",
        ]
    },
    "5_evaluation": {
        "what": "Assess model against business success criteria",
        "key_principle": "Offline metrics must correlate with online business metrics. "
                        "AUC improving by 0.01 is meaningless if it doesn't move conversion rate.",
    },
    "6_deployment": {
        "what": "Move model into production environment",
        "key_principle": "Deployment is the beginning, not the end. "
                        "The model's operational life is usually much longer than development.",
    }
}


# ============================================================
# SECTION 4: MLOPS MATURITY LEVELS
# ============================================================
# Google's framework for assessing and improving ML engineering maturity.
# Most organizations start at Level 0. Production-grade systems need Level 1 minimum.
# Level 2 is aspirational for most, but essential for high-velocity ML teams.

mlops_maturity_levels = {
    "Level_0_Manual": {
        "description": "Manual, script-driven, research-oriented ML process",
        "characteristics": [
            "Data scientists work in Jupyter notebooks",
            "Training is a manual, ad-hoc process",
            "Model is exported as a file and handed to engineering",
            "No experiment tracking — compare by looking at printouts",
            "Deployment is rare (months between updates)",
            "No monitoring beyond basic infrastructure health",
        ],
        "when_acceptable": "Early-stage startups, proof-of-concept projects, single model with rare retraining",
        "pain_points": [
            "Reproducibility: 'which notebook produced the model in production?'",
            "Knowledge transfer: model is in a data scientist's head",
            "Slow iteration: manual steps bottleneck improvements",
        ],
        "signals_you_need_to_level_up": [
            "Model in production > 3 months",
            "Team > 2 data scientists",
            "Business depends on model accuracy",
            "You've ever asked 'what exactly is in production?'",
        ]
    },
    "Level_1_Automated_Training": {
        "description": "ML pipeline automation with training workflow orchestration",
        "characteristics": [
            "Training pipeline is automated and reproducible",
            "Experiment tracking (MLflow, W&B) for all runs",
            "Feature store for consistent feature computation",
            "Automated model validation before deployment",
            "Model registry for versioning and stage management",
            "Basic monitoring: prediction volume, latency, feature drift",
            "Retraining is automated but deployment is still manual approval",
        ],
        "what_you_gain": [
            "Can retrain models quickly when data drift detected",
            "Anyone on the team can reproduce any historical model",
            "New data scientists can run experiments without tribal knowledge",
        ],
        "investment_required": "1-2 MLOps engineers, 2-4 months initial setup",
        "when_to_target": "Team with 3+ models in production, multiple data scientists",
    },
    "Level_2_Automated_CICD": {
        "description": "Full CI/CD for ML: automated training, evaluation, and deployment",
        "characteristics": [
            "Code commit triggers automated training pipeline",
            "Evaluation gates: new model must beat champion by threshold",
            "Automated deployment to staging with integration tests",
            "Progressive rollout: canary deployment with automatic promotion/rollback",
            "Continuous monitoring with automated retraining triggers",
            "Full lineage: data version + code version + config → model → deployment",
            "A/B testing infrastructure for online model evaluation",
        ],
        "what_you_gain": [
            "Data scientists push code, not models — engineering handles the rest",
            "Dozens of model updates per week with full safety guarantees",
            "Model degradation auto-detected and auto-remediated",
        ],
        "investment_required": "Dedicated MLOps team (3-5 engineers), 6-12 months",
        "when_to_target": "Platform teams serving many models, high-frequency update needs",
    }
}


# ============================================================
# SECTION 5: THE THREE PILLARS OF MLOPS
# ============================================================

three_pillars = {
    "People": {
        "roles": {
            "Data_Scientist": {
                "focus": "Model development, feature engineering, evaluation",
                "skills": "Statistics, ML algorithms, Python, domain knowledge",
                "mlops_responsibility": "Write production-quality training code, "
                                       "define evaluation metrics, document model cards"
            },
            "ML_Engineer": {
                "focus": "Training pipelines, model serving, feature pipelines",
                "skills": "Software engineering, ML frameworks, Docker, cloud platforms",
                "mlops_responsibility": "Build and maintain ML pipelines, serving infrastructure"
            },
            "MLOps_Engineer": {
                "focus": "ML platform, infrastructure, CI/CD for ML",
                "skills": "DevOps, Kubernetes, Terraform, ML systems design",
                "mlops_responsibility": "Build the platform that DS and ML engineers use"
            },
            "Data_Engineer": {
                "focus": "Data pipelines, data lake, feature computation at scale",
                "skills": "Spark, dbt, Kafka, Airflow, SQL, cloud data warehouses",
                "mlops_responsibility": "Provide reliable, versioned, documented data"
            }
        },
        "cultural_requirements": [
            "Shared ownership of model in production (not just data scientist's job)",
            "Blameless postmortems for model failures",
            "Documentation as first-class citizen (model cards, data cards)",
            "Experimentation culture: failure is expected, learning is required",
        ]
    },
    "Process": {
        "key_processes": {
            "Model_Review": "PR-like review for model changes: metrics, fairness, data validation",
            "Change_Management": "Staged rollouts with automated and manual gates",
            "Incident_Management": "On-call rotation for ML systems, runbooks for common failures",
            "Experiment_Protocol": "Hypothesis-driven experiments with documented learnings",
            "Retraining_Policy": "Defined triggers, frequency, and approval process for retraining",
        }
    },
    "Technology": {
        "tool_categories": {
            "Data_Management": ["DVC", "Delta Lake", "Apache Iceberg", "Great Expectations"],
            "Feature_Engineering": ["Feast", "Tecton", "Hopsworks", "Databricks Feature Store"],
            "Experiment_Tracking": ["MLflow", "Weights & Biases", "Comet ML", "Neptune"],
            "Pipeline_Orchestration": ["Kubeflow", "Airflow", "Prefect", "Dagster", "Metaflow"],
            "Model_Registry": ["MLflow Model Registry", "SageMaker Model Registry", "Vertex AI Model Registry"],
            "Model_Serving": ["TorchServe", "Triton", "BentoML", "Seldon Core", "KServe"],
            "Monitoring": ["Evidently AI", "WhyLabs", "Arize AI", "Fiddler", "Prometheus+Grafana"],
            "Training_Compute": ["SageMaker", "Vertex AI Training", "Databricks", "Ray Train"],
        }
    }
}


# ============================================================
# SECTION 6: TOOLS LANDSCAPE
# ============================================================
# The ML tooling ecosystem is vast and evolving rapidly. Key platforms to know:

tools_landscape = {
    "MLflow": {
        "type": "Open-source, self-hosted",
        "strengths": [
            "Experiment tracking, model registry, model serving in one package",
            "Framework-agnostic: works with sklearn, PyTorch, TF, XGBoost, etc.",
            "Large community, battle-tested at Databricks scale",
            "Free to self-host, managed via Databricks MLflow",
        ],
        "weaknesses": [
            "Feature store not included",
            "Pipeline orchestration not included (needs Airflow/Kubeflow)",
            "UI is functional but not beautiful",
        ],
        "best_for": "Teams wanting open-source flexibility, Databricks shops",
    },
    "Kubeflow": {
        "type": "Open-source, Kubernetes-native",
        "strengths": [
            "Full ML platform: notebooks, pipelines, training operators, serving (KServe)",
            "Kubernetes-native: scales with your K8s cluster",
            "Strong community from Google",
        ],
        "weaknesses": [
            "Steep learning curve: requires deep K8s expertise",
            "Complex to install and maintain",
            "Not suitable for small teams",
        ],
        "best_for": "Platform teams with K8s expertise building internal ML platforms",
    },
    "Metaflow": {
        "type": "Open-source (Netflix), Python-first",
        "strengths": [
            "Designed by data scientists, for data scientists",
            "Seamless local → cloud scaling",
            "Simple Python decorator API",
            "Excellent versioning story",
        ],
        "weaknesses": [
            "More DS workflow tool than full MLOps platform",
            "Limited serving story",
        ],
        "best_for": "Data science teams wanting structured, versioned workflows",
    },
    "Vertex_AI": {
        "type": "Managed (Google Cloud)",
        "strengths": [
            "Fully managed: no infrastructure to maintain",
            "Integrated with GCP: BigQuery, GCS, Cloud Run",
            "AutoML, custom training, feature store, model registry all unified",
            "Excellent for Google Cloud shops",
        ],
        "weaknesses": [
            "GCP vendor lock-in",
            "Can be expensive at scale",
            "Less flexibility than self-hosted",
        ],
        "best_for": "Teams on GCP wanting managed MLOps without infrastructure burden",
    },
    "SageMaker": {
        "type": "Managed (AWS)",
        "strengths": [
            "Mature, feature-complete ML platform",
            "Deep AWS integration (S3, ECR, CloudWatch, IAM)",
            "SageMaker Studio as IDE, Pipelines for orchestration",
            "Strong enterprise adoption",
        ],
        "weaknesses": [
            "AWS vendor lock-in",
            "Complex pricing",
            "Can feel heavyweight for simple use cases",
        ],
        "best_for": "Teams on AWS wanting a managed end-to-end ML platform",
    },
    "Azure_ML": {
        "type": "Managed (Microsoft Azure)",
        "strengths": [
            "Strong enterprise governance and RBAC",
            "MLflow integration built-in",
            "Azure DevOps integration for CI/CD",
            "Responsible AI toolkit built-in",
        ],
        "weaknesses": [
            "Azure lock-in",
            "UI can lag behind AWS/GCP in polish",
        ],
        "best_for": "Enterprise teams on Azure, especially Microsoft shops",
    }
}


# ============================================================
# SECTION 7: WHEN TO INVEST IN MLOPS (AND WHEN NOT TO)
# ============================================================
# MLOps is not free. Know when the investment is justified.

when_to_invest = {
    "Invest_heavily_when": [
        "Multiple models in production (3+) and growing",
        "Models need frequent retraining (daily, weekly)",
        "Business outcomes directly tied to model performance",
        "Multiple teams (DS, MLE, DE) working on the same systems",
        "Regulatory requirements (financial services, healthcare, insurance)",
        "High-traffic serving (millions of predictions/day)",
        "Model failures have significant business or safety consequences",
    ],
    "Light_investment_when": [
        "1-2 models that are retrained rarely (monthly/quarterly)",
        "Small team (1-2 data scientists) with low model churn",
        "Models are internal tools with low business criticality",
        "Early experimentation phase — still proving model value",
    ],
    "Probably_overkill_when": [
        "One-off analysis or report (not a live model)",
        "Research prototype that may never go to production",
        "Batch job that runs once per quarter",
        "Team is exploring whether ML is even the right solution",
    ],
    "Rule_of_thumb": (
        "If your model going down for 4 hours would require a management escalation, "
        "you need MLOps. If nobody would notice, you probably don't."
    )
}


# ============================================================
# SECTION 8: KEY PAIN POINTS MLOPS SOLVES
# ============================================================

pain_points_and_solutions = {
    "Reproducibility": {
        "pain": "Cannot reproduce the model that is currently in production. "
               "The data scientist who built it left. The notebook was overwritten.",
        "solution": "Experiment tracking (log all params, metrics, data version) + "
                   "Docker containers (pin environment) + DVC (version data) + "
                   "model registry (store artifact with full lineage).",
        "production_impact": "Critical for debugging, audits, and regulatory compliance"
    },
    "Training_Serving_Skew": {
        "pain": "Model performs well in training but poorly in production. "
               "Feature computation in training notebook ≠ feature computation in serving API.",
        "solution": "Feature store: same feature definitions used for both training "
                   "(batch) and serving (online). One source of truth for feature logic.",
        "production_impact": "Silent accuracy degradation that is very hard to debug without FP"
    },
    "Model_Decay": {
        "pain": "Model deployed 6 months ago now performs worse because the world changed. "
               "No monitoring → no detection → degraded user experience.",
        "solution": "Data drift monitoring (PSI, KS test) + prediction monitoring + "
                   "ground truth collection + automated retraining triggers.",
        "production_impact": "Revenue loss, user churn, or safety issues depending on domain"
    },
    "Scalability": {
        "pain": "5 models are manageable manually. 50 models require a platform.",
        "solution": "Standardized pipeline templates, model registry with automated promotion, "
                   "self-service tooling for data scientists.",
        "production_impact": "Without platform thinking, growth is bottlenecked by MLOps engineering capacity"
    },
    "Collaboration": {
        "pain": "Data scientists work in silos. No visibility into what others are doing. "
               "Duplicate experiments, conflicting model versions.",
        "solution": "Shared experiment tracking server, model registry with ownership, "
                   "standardized evaluation protocols.",
        "production_impact": "Teams can build on each other's work instead of starting from scratch"
    }
}


# ============================================================
# ARCHITECT'S TAKE: THE FUNDAMENTAL INSIGHT
# ============================================================
# ML systems fail in ways that software systems don't:
#   - Silently (no exceptions, just wrong predictions)
#   - Gradually (performance decays over weeks, not instantly)
#   - Mysteriously (cause is data, not code, so logs don't help)
#
# MLOps is the discipline of making invisible failures visible,
# making gradual decay detectable, and making mysterious causes traceable.
#
# The core loop every production ML system must support:
#
#   DATA → FEATURES → TRAIN → EVALUATE → REGISTER → DEPLOY
#     ↑                                                  |
#     |                                                  ↓
#     └─────────── RETRAIN ← ALERT ← MONITOR ←──────────┘
#
# Every component in this loop needs to be:
#   - Automated (not dependent on a human remembering to do it)
#   - Versioned (every state is preserved and reproducible)
#   - Monitored (health is continuously observable)
#   - Tested (correctness is verified before production)
#
# Build the loop, build the system. Everything else is tooling.
