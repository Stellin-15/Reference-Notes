# Feature Stores & Modern Data Lake — Principal Engineer Deep Dive

Companion to the existing lessons. Narrative depth, then a comprehensive
common-to-uncommon reference.


## The Training/Serving Skew Problem — Why Feature Stores Exist

**Beyond the lesson**: Feature stores solve one specific, expensive
production ML problem: a model trained on features computed in BATCH
(Spark job over historical data, days of lag acceptable) needs those SAME
features computed in REAL TIME at inference (a live API request, single-
digit milliseconds) — and if the batch and real-time computation logic
DRIFT even slightly (a subtly different rolling-window definition, a
different null-handling rule), the model silently sees different feature
distributions at serving time than it was trained on, degrading accuracy
in a way that's genuinely hard to detect without dedicated monitoring.

**Worked example**: The offline/online store split, concretely — the
OFFLINE store (a data warehouse/lake, cheap, high-latency, used for
training-time feature retrieval over historical data) and the ONLINE store
(Redis/DynamoDB/ScyllaDB, expensive per-GB but sub-millisecond, used for
real-time serving) are kept in sync by the SAME feature transformation
logic, defined ONCE in the feature store's framework (Feast, Tecton), and
materialized to both stores — this single-definition guarantee is the
entire value proposition; without it, you're back to hand-syncing two
separate implementations of "customer's average order value over 30 days."

**Interview Q&A**:
- *Q: Why not just query the production database directly for features at inference time instead of a separate online store?* A: Latency and load isolation — a production OLTP database isn't optimized for the specific access pattern feature serving needs (fetch many pre-computed features by entity ID, very fast, at high concurrent volume), and hammering it with inference traffic risks degrading the actual application's normal database performance; a dedicated online store is purpose-built for this read pattern and isolates the blast radius.


## Point-in-Time Correctness — The Subtle Bug Feature Stores Prevent

**Beyond the lesson**: The single most dangerous, hardest-to-detect bug in
ML feature engineering is DATA LEAKAGE via point-in-time incorrectness —
computing a feature using information that wouldn't have actually been
available at the historical moment you're training against (e.g. "customer's
total lifetime spend" computed using ALL their orders, including ones that
happened AFTER the training example's timestamp) — this makes a model look
suspiciously accurate in training/backtesting and then perform far worse
in real production, because the "future information" it was accidentally
trained on simply doesn't exist yet at real inference time.

**Worked example**: A feature store's point-in-time JOIN specifically
solves this — when building a training dataset, it retrieves each
feature's value AS OF the exact timestamp of each training example, not
the feature's CURRENT/latest value — Feast's `get_historical_features`
and Tecton's equivalent are built entirely around enforcing this correctly
by default, something a naive hand-written SQL join between a labels table
and a features table gets wrong constantly unless explicitly engineered for.

**Interview Q&A**:
- *Q: A fraud-detection model performs great in backtesting but poorly in production. Point-in-time correctness is suspect — what specifically would you check?* A: Whether any feature (e.g. "account's total flagged transactions") was computed using the FULL historical dataset rather than only transactions that occurred BEFORE each training example's timestamp — if a fraud flag from the future leaked into a feature for a past example, the model learned a signal that simply won't exist at real serving time.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Feature store platforms
- **Feast** — the dominant open-source feature store, cloud-agnostic,
  bring-your-own offline/online store backends.
- **Tecton** — commercial, more managed/complete (built-in
  transformation pipelines, monitoring, streaming feature support) — chosen by teams wanting less operational assembly than Feast requires.
- **Databricks Feature Store / SageMaker Feature Store / Vertex AI Feature
  Store** — cloud-platform-native options, simplest when already fully
  committed to that platform's broader ML ecosystem.

### Modern data lake table formats
- **Delta Lake** (Databricks-originated, now open) — ACID transactions
  on top of object storage/Parquet, time travel, schema enforcement/evolution.
- **Apache Iceberg** — similar goals, increasingly favored for its more
  open, engine-agnostic design (works cleanly across Spark, Trino, Flink,
  not tied to one vendor's ecosystem the way Delta historically was more closely tied to Databricks).
- **Apache Hudi** — similar table-format category, historically stronger
  on UPSERT-heavy/streaming ingestion use cases specifically.
- **Trino** (formerly PrestoSQL) — a distributed SQL query engine that can
  query across MULTIPLE data sources (S3/Delta/Iceberg, MySQL, Kafka) in
  one federated query — the "query everything without moving it first"
  layer commonly paired with lakehouse table formats.

### Online store backends
- **ScyllaDB** — chosen for feature serving specifically for its very low
  p99 latency at high write throughput (see NoSQL deep dive) — a common
  choice for feature stores at real scale beyond what Redis alone comfortably handles.
- **DynamoDB / Redis** — simpler, sufficient online-store choices for
  moderate-scale feature-serving needs.


## NICHE BUT REAL

- **Streaming feature computation** — features computed continuously from
  a Kafka stream (e.g. "transactions in the last 5 minutes") rather than
  batch-recomputed periodically — needed for genuinely real-time features
  (fraud detection can't wait for an hourly batch job) and a meaningfully
  more complex engineering problem than batch feature pipelines.
- **Feature monitoring/drift detection** — tracking whether a feature's
  PRODUCTION distribution has drifted from its TRAINING distribution over
  time (a real, silent model-degradation cause distinct from the code bug
  of training/serving skew above) — tools like Evidently AI or a feature
  store's own built-in monitoring exist specifically for this.
- **Entity resolution across feature groups** — joining features about
  the "same" real-world entity (a customer) that were computed by
  DIFFERENT teams using slightly different entity IDs/keys — a genuine
  organizational-scale data-lake problem, not just a technical one.
- **Feature reuse economics** — the actual organizational ROI argument
  for a feature store: without one, every ML team independently
  re-implements "customer's 30-day rolling average spend" with subtly
  different bugs; a shared feature store turns that into a reusable,
  tested, ONCE-implemented asset — worth articulating this business case
  explicitly in a platform/staff-engineer-level interview.
