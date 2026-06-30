# ============================================================
# L03: Feature Stores
# ============================================================
# WHAT: A feature store is a centralized data platform for defining,
#       computing, storing, and serving ML features. It acts as the
#       interface between raw data (owned by data engineers) and model
#       training/serving (owned by ML engineers and data scientists).
#
# WHY:  Without a feature store, every team recomputes features differently.
#       The fraud team computes "avg_transaction_amount_30d" one way for
#       training and a slightly different way at serving time. The result:
#       training-serving skew — models perform well in training but poorly
#       in production. Feature stores eliminate this by making feature
#       logic the single source of truth for both contexts.
#
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    A feature store solves two fundamental ML infrastructure problems:
    1. TRAINING-SERVING CONSISTENCY: Same feature computation code runs
       both in batch (for training) and real-time (for serving), eliminating skew.
    2. FEATURE REUSE: Feature "user_30d_purchase_count" computed for one model
       is immediately available to all other models that need it, preventing
       redundant computation and inconsistent definitions.

    The store has two physical components:
    - OFFLINE STORE: Historical features (months/years) in a data warehouse
      (BigQuery, Redshift, S3+Parquet). Used for training dataset generation.
    - ONLINE STORE: Latest feature values in a low-latency key-value store
      (Redis, DynamoDB, Cassandra). Used for real-time inference (<10ms).

PRODUCTION USE CASE:
    A credit card company has 15 ML models: fraud detection, credit limit
    recommendations, payment default prediction, merchant categorization.
    All need similar user features: spending patterns, transaction history,
    behavioral signals. Without a feature store: 15 teams compute them
    differently. With a feature store: define "user_features" once, use
    everywhere. Models improve because they share the best feature definitions.

COMMON MISTAKES:
    - Using the feature store only for training, not for serving. This defeats
      the purpose — you still have training-serving skew from a different path.
    - Not implementing point-in-time correct joins. Using the user's current
      feature values for a historical training event leaks future information
      (the most dangerous form of data leakage in production ML).
    - Over-materializing features. Not every feature needs to be precomputed.
      Low-cardinality, cheap-to-compute features can be computed on-the-fly.
    - Ignoring feature monitoring. The feature store is upstream of the model.
      A drift in features silently degrades all downstream models.
"""

# FEAST: Open-source feature store — the reference implementation
# Install: pip install feast[redis,gcp,aws]
# Docs: https://docs.feast.dev/

from datetime import timedelta, datetime
from typing import List, Dict, Optional, Any
import pandas as pd
import numpy as np


# ============================================================
# SECTION 1: FEAST CORE CONCEPTS
# ============================================================
# Feast has five fundamental objects:
#   1. Entity       — the "key" that identifies a subject (user, merchant, product)
#   2. DataSource   — where raw data lives (BigQuery, S3, Spark, etc.)
#   3. FeatureView  — feature definitions + data source + metadata
#   4. FeatureService — a named set of features for a specific model
#   5. Feature Store — the root object tying everything together

"""
FEAST FEATURE DEFINITIONS (feature_repo/features.py):

from feast import (
    Entity, FeatureView, FeatureService, Feature, FileSource, BigQuerySource
)
from feast.types import Float32, Float64, Int64, String, Bool
from feast.value_type import ValueType
from datetime import timedelta

# ── 1. ENTITIES ─────────────────────────────────────────────────────────
# An Entity represents the "who" or "what" a feature describes.
# It's the join key: feature values are always relative to an entity.
# IMPORTANT: Entity joins in training use entity + timestamp for point-in-time correctness.

user = Entity(
    name="user_id",
    value_type=ValueType.STRING,
    description="Unique user identifier across all ML features",
    tags={"team": "platform", "pii": "false"},
)

merchant = Entity(
    name="merchant_id",
    value_type=ValueType.STRING,
    description="Merchant receiving payment",
)

# ── 2. DATA SOURCES ─────────────────────────────────────────────────────
# Where raw feature data lives. Feast reads from here to materialize to offline/online stores.

# File source (development / simple pipelines)
user_stats_source = FileSource(
    path="s3://company-features/user_stats/",
    event_timestamp_column="timestamp",  # When this feature value was computed/valid
    created_timestamp_column="created_at",  # When it was written to storage
    file_format=ParquetFormat(),
)

# BigQuery source (GCP production)
user_transactions_source = BigQuerySource(
    table="project.features.user_transaction_features",
    event_timestamp_column="feature_timestamp",
    created_timestamp_column="ingestion_timestamp",
)

# Kafka source (streaming features — real-time updates)
# fraud_signal_source = KafkaSource(
#     name="fraud_signals",
#     kafka_bootstrap_servers="kafka:9092",
#     topic="user-fraud-signals",
#     event_timestamp_column="event_time",
#     batch_source=user_stats_source,  # Fallback for materialization
#     message_format=AvroFormat(schema_json=AVRO_SCHEMA),
# )

# ── 3. FEATURE VIEWS ────────────────────────────────────────────────────
# A FeatureView is a GROUP of related features computed from ONE data source
# for ONE or more entities. The TTL defines how long feature values remain valid.

user_transaction_features_view = FeatureView(
    name="user_transaction_features",    # Unique name in the feature store
    entities=[user],                     # Which entity these features belong to
    ttl=timedelta(days=30),             # Time-to-live: after 30 days, features are stale
                                         # Longer TTL = more storage but higher staleness tolerance
    schema=[
        # Feature definitions with types and documentation
        Feature(name="transaction_count_7d", dtype=Int64,
                description="Number of transactions in the last 7 days"),
        Feature(name="transaction_count_30d", dtype=Int64,
                description="Number of transactions in the last 30 days"),
        Feature(name="avg_transaction_amount_7d", dtype=Float64,
                description="Average transaction amount (USD) in the last 7 days"),
        Feature(name="avg_transaction_amount_30d", dtype=Float64,
                description="Average transaction amount (USD) in the last 30 days"),
        Feature(name="max_transaction_amount_7d", dtype=Float64,
                description="Maximum single transaction amount in the last 7 days"),
        Feature(name="unique_merchants_30d", dtype=Int64,
                description="Distinct merchants transacted with in 30 days"),
        Feature(name="international_transaction_ratio_30d", dtype=Float32,
                description="Fraction of transactions that were international in 30 days"),
        Feature(name="night_transaction_ratio_7d", dtype=Float32,
                description="Fraction of transactions occurring between 11pm-5am"),
    ],
    source=user_transactions_source,
    tags={
        "team": "fraud-ml",
        "domain": "transaction",
        "sensitivity": "high",  # For governance: features involving PII-adjacent data
    },
    online=True,   # Materialize to online store (Redis) for real-time serving
    offline=True,  # Materialize to offline store for training dataset generation
)

user_profile_features_view = FeatureView(
    name="user_profile_features",
    entities=[user],
    ttl=timedelta(days=90),  # Profile features change slowly — longer TTL
    schema=[
        Feature(name="account_age_days", dtype=Int64,
                description="Days since account creation"),
        Feature(name="verified_email", dtype=Bool,
                description="Whether user has a verified email address"),
        Feature(name="credit_score_bucket", dtype=String,
                description="Credit score bucket: poor/fair/good/excellent"),
        Feature(name="lifetime_transaction_count", dtype=Int64),
        Feature(name="lifetime_transaction_volume_usd", dtype=Float64),
        Feature(name="chargeback_count_lifetime", dtype=Int64,
                description="Total chargebacks initiated by this user"),
    ],
    source=FileSource(path="s3://company-features/user_profiles/", ...),
    online=True,
    offline=True,
)

# ── 4. FEATURE SERVICES ─────────────────────────────────────────────────
# A FeatureService defines the EXACT features a specific model uses.
# Version-controls the feature set per model — critical for reproducibility.
# When the model is retrained, pin to the same FeatureService definition.

fraud_detection_feature_service = FeatureService(
    name="fraud_detection_v2",   # Versioned name — create a new service when features change
    features=[
        # Reference specific features from feature views
        user_transaction_features_view[
            ["transaction_count_7d", "transaction_count_30d",
             "avg_transaction_amount_7d", "avg_transaction_amount_30d",
             "max_transaction_amount_7d", "international_transaction_ratio_30d",
             "night_transaction_ratio_7d"]
        ],
        user_profile_features_view[
            ["account_age_days", "verified_email", "chargeback_count_lifetime"]
        ],
    ],
    description="Features for fraud detection model v2 (improved transaction features)",
    tags={"model": "fraud-detector", "model_version": "v2"},
)
"""


# ============================================================
# SECTION 2: FEAST WORKFLOWS
# ============================================================

class FeatureStoreWorkflows:
    """
    Demonstrates the three key workflows with a feature store:
    1. Materialize: populate online/offline stores from data sources
    2. Get training data: generate point-in-time correct training dataset
    3. Get online features: low-latency feature retrieval at serving time
    """

    def __init__(self, feature_store_repo_path: str = "./feature_repo"):
        """
        The FeatureStore object is the client.
        It reads config from feature_store.yaml in the repo.
        """
        # In practice:
        # from feast import FeatureStore
        # self.store = FeatureStore(repo_path=feature_store_repo_path)
        self.repo_path = feature_store_repo_path

    def materialize_features(self, start_date: datetime, end_date: datetime):
        """
        MATERIALIZE: Compute features from data sources and write them to
        the offline store (S3/BigQuery) and online store (Redis).

        This is typically run on a schedule (hourly, daily) by Airflow or
        a dedicated materialization job. Fresh data in source → triggers
        materialization → online store updated → serving uses fresh features.

        ARCHITECTURE: Who triggers materialization?
          Option A: Time-based: Airflow DAG runs feast materialize every hour
          Option B: Event-based: New data partition arrives → triggers pipeline
          Option C: Streaming: Kafka → Feast streaming ingestion → online store
        """
        print(f"Materializing features from {start_date} to {end_date}")

        # feast materialize:  fills the offline + online stores
        # self.store.materialize(
        #     start_date=start_date,
        #     end_date=end_date,
        # )

        # feast materialize_incremental: more efficient — only materializes
        # features after the latest materialized timestamp
        # self.store.materialize_incremental(end_date=end_date)

        print("Materialization complete. Online store is up-to-date.")

    def get_training_dataset(
        self,
        entity_df: pd.DataFrame,
        feature_service_name: str = "fraud_detection_v2"
    ) -> pd.DataFrame:
        """
        HISTORICAL RETRIEVAL for training dataset generation.

        entity_df: DataFrame with entity columns (user_id) + event_timestamp.
        The event_timestamp is the PREDICTION TIME — the moment when the model
        would have been asked to make a prediction in a historical scenario.

        CRITICAL CONCEPT: POINT-IN-TIME CORRECT JOINS
        ──────────────────────────────────────────────
        For each training example (user_id, event_timestamp), Feast retrieves
        the feature values as they existed JUST BEFORE the event_timestamp.

        Example:
          Training event: user "alice" made a transaction at 2024-03-15 14:30:00
          Feature needed: "avg_transaction_amount_30d" for alice
          Feast returns: the value computed from Alice's transactions up to 14:30:00
          NOT: the current value (which would leak future transactions into training)

        This prevents the most dangerous form of data leakage in ML:
        accidentally using future information to predict past events.

        Without point-in-time joins, training AUC appears great but production
        performance is terrible because the model learned from future data.
        """
        # entity_df format:
        # | user_id | event_timestamp        | label |
        # |---------|------------------------|-------|
        # | u_001   | 2024-03-15 14:30:00   | 1     |
        # | u_001   | 2024-03-17 09:15:00   | 0     |
        # | u_002   | 2024-03-15 11:00:00   | 1     |

        print(f"Generating training dataset for {len(entity_df)} events")
        print(f"Using feature service: {feature_service_name}")

        # Feast performs the point-in-time correct join:
        # training_df = self.store.get_historical_features(
        #     entity_df=entity_df,
        #     features=self.store.get_feature_service(feature_service_name),
        # ).to_df()

        # Result: entity_df with feature columns appended (point-in-time correct)
        # | user_id | event_timestamp | label | transaction_count_7d | avg_tx_amount_7d | ...
        # The feature values are as of the event_timestamp for each row.

        # Simulate output for illustration
        training_df = entity_df.copy()
        training_df["transaction_count_7d"] = np.random.randint(0, 50, len(entity_df))
        training_df["avg_transaction_amount_7d"] = np.random.uniform(10, 500, len(entity_df))
        return training_df

    def get_online_features(
        self,
        entity_ids: List[str],
        feature_service_name: str = "fraud_detection_v2"
    ) -> Dict[str, List[Any]]:
        """
        ONLINE RETRIEVAL for real-time inference.

        Returns the LATEST materialized feature values for given entity IDs.
        This is called in the serving path — must be fast (<10ms).

        Redis is the typical online store: O(1) key lookup,
        sub-millisecond latency, scales horizontally.

        The returned feature values are the same features that were used
        in training — this is the key guarantee of the feature store.
        """
        print(f"Fetching online features for {len(entity_ids)} users")

        # feature_vector = self.store.get_online_features(
        #     features=self.store.get_feature_service(feature_service_name),
        #     entity_rows=[{"user_id": uid} for uid in entity_ids],
        # ).to_dict()

        # Simulated return for illustration
        feature_vector = {
            "user_id": entity_ids,
            "transaction_count_7d": [12, 3, 45],
            "avg_transaction_amount_7d": [145.50, 23.00, 890.25],
            "account_age_days": [365, 30, 1200],
        }
        return feature_vector


# ============================================================
# SECTION 3: POINT-IN-TIME CORRECT JOINS — DEEP DIVE
# ============================================================
# This is the most conceptually important concept in feature engineering for ML.
# Data leakage from incorrect temporal joins is a leading cause of "my model works
# in training but fails in production."

def demonstrate_point_in_time_join_importance():
    """
    Illustrates why naive joins on entity ID alone leak future information.
    """
    # SCENARIO: Fraud detection
    # We have transactions (training events) and daily user stats (features).
    # We want: for each transaction, what were the user's stats at that moment?

    # Training events (the labels we're predicting)
    transactions = pd.DataFrame({
        "user_id": ["u1", "u1", "u2"],
        "transaction_time": pd.to_datetime([
            "2024-01-15 10:00:00",   # u1's first transaction
            "2024-01-20 15:00:00",   # u1's second transaction (5 days later)
            "2024-01-15 09:00:00",   # u2's transaction
        ]),
        "is_fraud": [0, 1, 0],
    })

    # Daily feature snapshots (computed each day at midnight)
    user_stats = pd.DataFrame({
        "user_id": ["u1", "u1", "u1", "u2", "u2"],
        "stats_date": pd.to_datetime([
            "2024-01-10",  # u1 stats before first tx
            "2024-01-15",  # u1 stats on day of first tx (computed after midnight)
            "2024-01-20",  # u1 stats on day of second tx
            "2024-01-10",  # u2 stats
            "2024-01-15",  # u2 stats
        ]),
        "tx_count_7d": [5, 6, 15, 3, 4],   # Note: u1's 7d count jumps from 6 to 15
    })

    # ── WRONG WAY: Simple join on user_id ────────────────────────────────
    # This joins the LATEST stats regardless of transaction time.
    # u1's second transaction (fraudulent) gets stats from 2024-01-20: tx_count=15
    # But u1's FIRST transaction also gets tx_count=15 (from the future!)
    # → Data leakage: first transaction "knows" about future behavior
    wrong_join = pd.merge(
        transactions,
        user_stats.sort_values("stats_date").groupby("user_id").last().reset_index(),
        on="user_id",
        how="left"
    )
    print("WRONG (leaks future data):")
    print(wrong_join[["user_id", "transaction_time", "is_fraud", "tx_count_7d"]])
    # u1's tx at 2024-01-15 shows tx_count_7d=15 (computed on 2024-01-20 — in the future!)

    # ── RIGHT WAY: Point-in-time join ────────────────────────────────────
    # For each transaction, find the LATEST stats BEFORE the transaction time.
    # This is what a feature store handles automatically.
    def point_in_time_join(events_df, features_df, event_time_col, feature_time_col):
        """
        For each event, retrieve the latest feature values
        that existed BEFORE the event occurred.
        """
        results = []
        for _, event in events_df.iterrows():
            # Get all feature rows for this entity before the event time
            relevant_features = features_df[
                (features_df["user_id"] == event["user_id"]) &
                (features_df[feature_time_col] <= event[event_time_col])
            ]
            if len(relevant_features) > 0:
                # Take the MOST RECENT feature snapshot before the event
                latest_features = relevant_features.sort_values(feature_time_col).iloc[-1]
                row = event.to_dict()
                row.update({"tx_count_7d": latest_features["tx_count_7d"]})
            else:
                row = event.to_dict()
                row.update({"tx_count_7d": None})  # No feature data before this event
            results.append(row)
        return pd.DataFrame(results)

    correct_join = point_in_time_join(
        transactions, user_stats,
        "transaction_time", "stats_date"
    )
    print("\nCORRECT (point-in-time):")
    print(correct_join[["user_id", "transaction_time", "is_fraud", "tx_count_7d"]])
    # u1's tx at 2024-01-15 correctly shows tx_count_7d=6 (computed on 2024-01-15)
    # u1's tx at 2024-01-20 shows tx_count_7d=15 (the correct, non-leaking value)


# ============================================================
# SECTION 4: OFFLINE vs ONLINE STORE ARCHITECTURE
# ============================================================

feature_store_architecture = {
    "Offline_Store": {
        "purpose": "Historical feature values for training dataset generation",
        "latency": "Seconds to minutes (batch retrieval)",
        "storage_technology": {
            "options": ["BigQuery (GCP)", "Redshift (AWS)", "Snowflake", "S3+Parquet", "Hive"],
            "recommendation": "BigQuery or Redshift for production scale",
        },
        "data_format": "Columnar (Parquet, ORC) for efficient range scans",
        "access_pattern": "Range queries: give me all feature values for user X between date A and B",
        "data_volume": "Months to years of history — TBs to PBs",
        "typical_query_time": "10 seconds to 5 minutes for million-row joins",
    },
    "Online_Store": {
        "purpose": "Latest feature values for real-time inference",
        "latency": "1-10ms (key-value lookup)",
        "storage_technology": {
            "options": ["Redis", "DynamoDB", "Cassandra", "Bigtable", "ScyllaDB"],
            "recommendation": "Redis for <10ms SLA; DynamoDB for serverless/auto-scale",
        },
        "data_format": "Key-value: entity_id → {feature_name: value}",
        "access_pattern": "Point lookup: give me current features for user X",
        "data_volume": "Only LATEST values — much smaller than offline store",
        "typical_query_time": "1-5ms with Redis (in-memory, O(1))",
    },
    "Data_Flow": """
    Data Sources (DB, Kafka, S3)
           ↓
    [Materialization Pipeline]  ←── Scheduled job (Airflow/cron)
           ↓              ↓
    Offline Store       Online Store
    (BigQuery)          (Redis)
           ↓              ↓
    Training Jobs    Serving APIs
    (get historical  (get latest
     features)        features)
    """,
    "Materialization_Strategies": {
        "batch": "Compute features on schedule (hourly/daily). Good for slow-moving features.",
        "streaming": "Kafka → Flink/Spark Streaming → online store. Real-time features.",
        "on_demand": "Compute feature at request time (not precomputed). Good for request-context features.",
    }
}


# ============================================================
# SECTION 5: FEAST FEATURE STORE SETUP (FULL EXAMPLE)
# ============================================================

def demonstrate_feast_workflow():
    """
    End-to-end Feast workflow: define → apply → materialize → retrieve.

    FILESYSTEM STRUCTURE of a Feast feature repository:
    feature_repo/
    ├── feature_store.yaml      # Configuration (project name, stores, registry)
    ├── features.py             # Feature definitions (entities, views, services)
    ├── data/                   # Sample data for development
    └── test_workflow.py        # Integration tests for feature definitions
    """

    # feature_store.yaml content:
    feature_store_yaml = """
    project: fraud-ml
    registry: s3://company-feast/registry.db    # Where metadata is stored
    provider: aws                               # Cloud provider
    online_store:
      type: redis
      connection_string: redis://redis.internal:6379
    offline_store:
      type: bigquery                            # For GCP
      dataset: feast_offline_store              # BigQuery dataset
    entity_key_serialization_version: 2
    """

    # CLI COMMANDS for a Feast workflow:
    workflow_commands = {
        "1_init": "feast init my_feature_repo",
        "2_apply": "feast apply",
        # apply: reads feature definitions from Python files, validates them,
        # and registers them in the feature registry (metadata store).
        # Does NOT compute or write feature data.

        "3_materialize": "feast materialize 2024-01-01T00:00:00 2024-12-31T00:00:00",
        # materialize: reads from data sources (BigQuery/S3) and writes feature values
        # to both offline (BigQuery) and online (Redis) stores.

        "4_serve": "feast serve",
        # Starts a local feature server for development testing.

        "5_ui": "feast ui",
        # Opens the Feast web UI showing all features, services, lineage.
    }

    print("Feast workflow commands:")
    for step, cmd in workflow_commands.items():
        print(f"  {step}: {cmd}")

    # PYTHON API for retrieval in serving:
    retrieval_example = """
    from feast import FeatureStore

    # In your serving application (FastAPI, Flask, etc.)
    store = FeatureStore(repo_path="./feature_repo")

    # Called for each prediction request
    def get_features_for_prediction(user_id: str) -> dict:
        feature_vector = store.get_online_features(
            features=[
                "user_transaction_features:transaction_count_7d",
                "user_transaction_features:avg_transaction_amount_7d",
                "user_profile_features:account_age_days",
                "user_profile_features:chargeback_count_lifetime",
            ],
            entity_rows=[{"user_id": user_id}],
        ).to_dict()
        return feature_vector
    """
    print(retrieval_example)


# ============================================================
# SECTION 6: ENTERPRISE FEATURE STORE COMPARISON
# ============================================================

feature_store_comparison = {
    "Feast": {
        "type": "Open-source",
        "cost": "Free (infra costs only)",
        "strengths": [
            "Full control over infrastructure",
            "Good community and documentation",
            "Supports many backends (Redis, BigQuery, Redshift, S3)",
            "Python-native, easy to integrate with existing ML stack",
        ],
        "weaknesses": [
            "Operational overhead: you manage Redis, registry, materialization jobs",
            "No built-in UI beyond basic web dashboard",
            "Streaming support requires additional setup (Kafka + Spark)",
        ],
        "best_for": "Teams with strong engineering resources, multi-cloud, cost-sensitive",
    },
    "Tecton": {
        "type": "Managed SaaS (enterprise)",
        "cost": "Expensive ($100k+/year)",
        "strengths": [
            "Production-ready out of the box",
            "Excellent streaming feature support (sub-second freshness)",
            "Built-in monitoring, alerting, lineage",
            "Strong compliance features (SOC2, GDPR)",
            "Customer success team for onboarding",
        ],
        "weaknesses": [
            "Vendor lock-in",
            "High cost for small teams",
            "Less control over internals",
        ],
        "best_for": "Enterprises needing streaming features, compliance, and managed infra",
    },
    "Hopsworks": {
        "type": "Open-source + managed option",
        "cost": "Free OSS, paid managed",
        "strengths": [
            "Full ML platform: feature store + model registry + serving",
            "Very strong feature group versioning",
            "Good streaming support via Kafka integration",
            "On-prem deployment possible",
        ],
        "weaknesses": [
            "Heavier stack to deploy and maintain",
            "Smaller community than Feast",
        ],
        "best_for": "Teams wanting integrated platform, on-prem requirements",
    },
    "Databricks_Feature_Store": {
        "type": "Managed (Databricks/Unity Catalog)",
        "cost": "Included in Databricks contract",
        "strengths": [
            "Native integration with Databricks notebooks, MLflow, Delta Lake",
            "Unity Catalog for governance, lineage, access control",
            "Excellent for Spark-based feature computation",
            "Point-in-time joins via Delta time travel",
        ],
        "weaknesses": [
            "Databricks lock-in",
            "Online serving less mature than Tecton/Feast+Redis",
        ],
        "best_for": "Databricks shops; teams already using Delta Lake",
    },
    "Vertex_AI_Feature_Store": {
        "type": "Managed (GCP)",
        "cost": "Pay-per-use GCP pricing",
        "strengths": [
            "Fully managed on GCP",
            "Native BigQuery integration",
            "Bigtable-backed online store (very scalable)",
            "Integrated with Vertex AI Pipelines and Model Registry",
        ],
        "weaknesses": [
            "GCP lock-in",
            "Pricing can be complex at scale",
        ],
        "best_for": "GCP-native teams using Vertex AI for the full ML platform",
    }
}


# ============================================================
# SECTION 7: FEATURE MONITORING IN THE FEATURE STORE
# ============================================================
# The feature store is also the right place to detect data drift
# because it sees ALL features for ALL models in one place.

class FeatureMonitoring:
    """
    Monitor feature distributions to detect data quality issues and drift.
    Problems caught here before they reach models prevent silent degradation.
    """

    def compute_feature_statistics(self, feature_df: pd.DataFrame) -> Dict:
        """
        Compute baseline statistics for features at training time.
        These are stored as the "expected distribution" for production comparison.
        """
        stats = {}
        for col in feature_df.select_dtypes(include=[np.number]).columns:
            stats[col] = {
                "mean": float(feature_df[col].mean()),
                "std": float(feature_df[col].std()),
                "min": float(feature_df[col].min()),
                "max": float(feature_df[col].max()),
                "p25": float(feature_df[col].quantile(0.25)),
                "p50": float(feature_df[col].quantile(0.50)),
                "p75": float(feature_df[col].quantile(0.75)),
                "p95": float(feature_df[col].quantile(0.95)),
                "null_fraction": float(feature_df[col].isna().mean()),
            }
        return stats

    def detect_feature_drift(
        self,
        baseline_stats: Dict,
        current_df: pd.DataFrame,
        psi_threshold: float = 0.2
    ) -> Dict:
        """
        Population Stability Index (PSI) for detecting feature drift.

        PSI = Σ (Actual% - Expected%) × ln(Actual% / Expected%)
        PSI < 0.1:  No significant drift — model should perform similarly
        PSI 0.1-0.2: Moderate drift — investigate and monitor closely
        PSI > 0.2:  Significant drift — consider retraining
        """
        drift_report = {}
        for feature, baseline in baseline_stats.items():
            if feature not in current_df.columns:
                drift_report[feature] = {"status": "MISSING_FEATURE", "psi": None}
                continue

            current_values = current_df[feature].dropna()
            baseline_mean = baseline["mean"]
            baseline_std = baseline["std"]

            # PSI using percentile buckets
            current_mean = float(current_values.mean())
            current_std = float(current_values.std())

            # Simple Z-score check for mean shift (proxy for PSI in this demo)
            if baseline_std > 0:
                z_score = abs(current_mean - baseline_mean) / baseline_std
            else:
                z_score = 0.0

            # Null fraction drift
            current_null_frac = float(current_df[feature].isna().mean())
            null_drift = abs(current_null_frac - baseline["null_fraction"])

            status = "OK"
            if z_score > 3.0 or null_drift > 0.1:
                status = "DRIFT_DETECTED"
            elif z_score > 1.5 or null_drift > 0.05:
                status = "MONITOR_CLOSELY"

            drift_report[feature] = {
                "status": status,
                "baseline_mean": baseline_mean,
                "current_mean": current_mean,
                "mean_z_score": round(z_score, 3),
                "baseline_null_frac": baseline["null_fraction"],
                "current_null_frac": current_null_frac,
                "null_drift": round(null_drift, 4),
            }

        return drift_report

    def alert_on_feature_issues(self, drift_report: Dict):
        """
        In production: send to PagerDuty/Slack when critical features drift.
        Feature drift often precedes model performance degradation by hours/days.
        Early detection gives time to diagnose and retrain before users are affected.
        """
        critical_features = []
        monitor_features = []

        for feature, report in drift_report.items():
            if report.get("status") == "DRIFT_DETECTED":
                critical_features.append(feature)
            elif report.get("status") == "MONITOR_CLOSELY":
                monitor_features.append(feature)

        if critical_features:
            print(f"ALERT: Significant drift detected in: {critical_features}")
            # send_pagerduty_alert(...)
        if monitor_features:
            print(f"WARNING: Monitor these features: {monitor_features}")


# ============================================================
# SECTION 8: FEATURE ENGINEERING PATTERNS
# ============================================================

class FeatureEngineeringPatterns:
    """
    Common patterns for building production-quality features.
    These patterns must be implemented identically in offline (training)
    and online (serving) paths — the feature store enforces this.
    """

    def lag_features(self, df: pd.DataFrame, entity_col: str,
                     value_col: str, lags: List[int]) -> pd.DataFrame:
        """
        Lag features: value of a metric at N periods ago.
        Essential for time series models. Must be computed with respect to
        prediction time (not current time) for training data.
        """
        df = df.sort_values([entity_col, "timestamp"])
        for lag in lags:
            df[f"{value_col}_lag_{lag}"] = df.groupby(entity_col)[value_col].shift(lag)
        return df

    def rolling_window_features(self, df: pd.DataFrame, entity_col: str,
                                 value_col: str, windows: List[int]) -> pd.DataFrame:
        """
        Rolling statistics: mean/std/max/min over a window.
        CRITICAL: Use shift(1) so the window excludes the current event.
        Not shifting causes leakage (current event included in its own feature).
        """
        df = df.sort_values([entity_col, "timestamp"])
        for window in windows:
            rolling = df.groupby(entity_col)[value_col].rolling(window, min_periods=1)
            # shift(1) excludes the current row — prevents leakage
            df[f"{value_col}_mean_{window}d"] = rolling.mean().values
            df[f"{value_col}_std_{window}d"] = rolling.std().values
            df[f"{value_col}_max_{window}d"] = rolling.max().values
        return df

    def cyclical_encoding(self, df: pd.DataFrame, col: str, period: int) -> pd.DataFrame:
        """
        Encode cyclical features (hour of day, day of week, month) as sin/cos.
        Why: linear encoding makes hour 23 and hour 0 appear maximally different,
        but they are actually adjacent (23:59 → 00:00 transition).
        Sin/cos encoding preserves cyclical relationships.
        """
        df[f"{col}_sin"] = np.sin(2 * np.pi * df[col] / period)
        df[f"{col}_cos"] = np.cos(2 * np.pi * df[col] / period)
        return df

    def target_encoding(self, train_df: pd.DataFrame, test_df: pd.DataFrame,
                        cat_col: str, target_col: str,
                        n_folds: int = 5, smoothing: float = 10.0) -> pd.DataFrame:
        """
        Target encoding: replace categorical value with mean target rate.
        Use cross-validation to prevent leakage (each fold uses other folds' statistics).
        Smoothing prevents overfitting on rare categories.

        smoothed_encoding = (n * category_mean + smoothing * global_mean) / (n + smoothing)
        """
        global_mean = train_df[target_col].mean()
        category_stats = train_df.groupby(cat_col)[target_col].agg(["mean", "count"])
        smoothed = (
            (category_stats["count"] * category_stats["mean"] + smoothing * global_mean) /
            (category_stats["count"] + smoothing)
        )
        encoding_map = smoothed.to_dict()
        test_df[f"{cat_col}_target_encoded"] = (
            test_df[cat_col].map(encoding_map).fillna(global_mean)
        )
        return test_df


# ============================================================
# ARCHITECT'S TAKE: WHEN AND HOW TO BUILD A FEATURE STORE
# ============================================================
# The feature store is NOT the first thing to build. Common mistake:
# spending 3 months building a feature store before you have 2 models
# in production that share any features.
#
# BUILD A FEATURE STORE WHEN:
#   - You have 3+ models that share common features (spending patterns, user history)
#   - You've been burned by training-serving skew in production
#   - Your data science team wastes time recomputing features others have computed
#   - You need consistent feature definitions across teams
#
# START WITH:
#   1. A shared feature computation library (Python package) — shared code, not infrastructure
#   2. Add experiment tracking (MLflow) to see which features matter most
#   3. Then add a feature store when the above reveals duplication and skew problems
#
# THE CORE ARCHITECTURE DECISION:
# Online serving path: API call → feature store (Redis lookup) → model inference
# This lookup adds latency. Budget 5ms for feature retrieval from Redis in your SLA.
# If your model SLA is 10ms total, you cannot afford a feature store on the hot path.
# Solution: compute features at ingestion time (precompute, not on-demand).
