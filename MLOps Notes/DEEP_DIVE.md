# MLOps — Principal Engineer Deep Dive

Companion to L01-L13. Narrative depth, then a comprehensive common-to-
uncommon reference.


## Training-Serving Skew — The Recurring Root Cause

**Beyond the lesson**: A huge fraction of "the model works great in
notebooks but fails in production" incidents trace to training-serving
skew — the training pipeline and the serving pipeline compute the SAME
feature slightly differently (a rolling average computed over a
different window, a null-handling rule that differs, a categorical
encoding that silently treats an unseen category differently at
inference than it did during training's fit step). This is EXACTLY the
problem feature stores exist to solve (see Feature Stores & Modern Data
Lake deep dive) by defining feature logic ONCE — but even without a full
feature store, the discipline of literally sharing the SAME
transformation CODE (not just the same intent) between training and
serving pipelines is the actual fix, and its absence is the actual root cause.

**Worked example**: A model trained on data where a `country` categorical
feature was one-hot-encoded based on the TRAINING set's observed
categories; in production, a request arrives with a country that never
appeared in training data — if the serving pipeline's encoding logic
wasn't built to handle unseen categories explicitly (falling back to an
"unknown" bucket, matching exactly how the training pipeline was
configured to handle rare categories), the model receives a malformed or
zero-vector encoding it was never trained to handle, silently degrading that prediction.

**Interview Q&A**:
- *Q: A model's production accuracy dropped gradually over 3 months with no code deploy in that window. What's your first hypothesis?* A: Data/concept drift (see Classical ML Theory deep dive's precise distinction) — the input distribution or the input-output relationship has shifted since training; monitoring the live FEATURE distributions against the training distribution (not just overall accuracy, which lags and requires ground-truth labels that may arrive late) is the standard early-detection approach.


## CI/CD for ML — What's Actually Different From Regular Software CI/CD

**Beyond the lesson**: Regular CI/CD tests CODE; ML CI/CD must ALSO
validate DATA and MODEL QUALITY, which regular software testing has no
equivalent for. A model-CI pipeline typically runs: data validation
(schema/distribution checks, see Data Engineering deep dive's Great
Expectations coverage), training (reproducible, versioned), evaluation
against a held-out set with an explicit QUALITY GATE (block promotion if
accuracy/fairness metrics regress below a threshold), and often a SHADOW
or CANARY deployment phase (the new model runs alongside the current
production model on real traffic, its predictions logged but not served,
compared before fully promoting it) — this shadow-testing step has no
direct analogue in typical application CI/CD, because "does this model
actually perform well on REAL current traffic" can't be fully verified by offline test-set evaluation alone.

**Interview Q&A**:
- *Q: Why is a canary/shadow deployment phase specifically more important for ML models than for typical application code changes?* A: An application code change's correctness is largely deterministic and testable offline; a model's real-world performance depends on the CURRENT production data distribution, which can differ from the offline evaluation set in ways that are hard to fully anticipate — shadow testing validates against ACTUAL current traffic before any user is affected, catching distribution-related issues offline testing alone would miss.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Model registries & versioning
- **MLflow Model Registry** — the dominant open-source model registry,
  tracking model versions, stage transitions (staging → production →
  archived), and lineage back to the exact training run/data/code that produced each version.
- **Model + data + code versioning together** — DVC (Data Version
  Control) versions large datasets/model artifacts alongside Git-tracked
  code, since Git alone handles code well but poorly handles large binary
  data/model files — genuinely necessary for full experiment REPRODUCIBILITY (can you rebuild exactly this model from exactly this data + code + config, months later).

### Deployment patterns specific to ML
- **A/B testing for models** — genuinely more subtle than typical feature
  A/B tests, since model quality metrics (accuracy, revenue impact) often
  need LARGER sample sizes and LONGER observation windows to reach
  statistical significance than simpler UI/feature A/B tests.
- **Champion/challenger pattern** — running a new "challenger" model
  alongside the current "champion" in production, gradually shifting
  traffic based on observed performance — a formalized, ongoing version
  of the canary-deployment idea specifically for continuously-retrained model systems.
- **Multi-armed bandit deployment** — instead of a fixed A/B split,
  dynamically shift traffic toward the better-performing model AS
  evidence accumulates, reducing the "cost" of running an inferior
  variant for the full test duration — a genuinely more sample-efficient
  alternative to fixed-split A/B testing for model rollout specifically.

### Model monitoring beyond basic metrics
- **Evidently AI / WhyLabs / Arize** — dedicated ML observability
  platforms tracking feature drift, prediction drift, and model
  performance degradation over time — the ML-specific counterpart to
  general application observability tooling (see Observability Notes
  deep dive), purpose-built for statistical-distribution-shift detection
  that generic APM tools don't natively provide.
- **Fairness/bias monitoring** — tracking model performance/predictions
  SEPARATELY across demographic subgroups in production, not just in a
  one-time pre-deployment fairness audit — a real, ongoing operational
  practice at companies with regulatory or ethical fairness commitments,
  since a model that was fair at training time can drift toward
  disparate performance across groups as the underlying population/data shifts.

### Feature/model lineage & governance
- **Model cards** — standardized documentation (intended use, training
  data characteristics, known limitations, evaluation results across
  subgroups) accompanying a deployed model — increasingly an expected
  artifact, especially at companies with formal AI governance/compliance
  requirements (see Compliance & Governance deep dive).


## NICHE BUT REAL

- **Cold-start model deployment** — a genuinely tricky operational
  problem: how does a NEWLY deployed model handle traffic before it has
  any real production feedback/monitoring baseline established — often
  addressed via an extended shadow period specifically calibrated longer
  than a routine redeploy would need.
- **Retraining triggers, precisely** — scheduled (retrain every week
  regardless), performance-triggered (retrain when a monitored metric
  crosses a threshold), or data-volume-triggered (retrain once N new
  labeled examples accumulate) — the choice has real cost/freshness
  tradeoffs, and many mature MLOps setups combine multiple trigger types
  rather than relying on just a fixed schedule.
- **Feedback loops & their failure modes** — a recommendation model
  trained on historical CLICK data that then INFLUENCES what gets shown
  (and therefore what gets clicked next) creates a self-reinforcing
  feedback loop that can silently narrow/bias what the model ever learns
  from — a genuinely subtle, real production ML-systems failure mode
  distinct from ordinary drift, requiring deliberate exploration
  (occasionally showing non-optimal recommendations) to break the loop and gather unbiased signal.
- **Model rollback complexity beyond a simple version pointer flip** —
  rolling back a model version is easy; rolling back any FEATURE STORE
  schema changes or downstream systems that already adapted to the new
  model's output format/behavior is often the actually hard part of a
  bad-deployment recovery, a real operational complexity beyond naive "just redeploy the old model" thinking.
