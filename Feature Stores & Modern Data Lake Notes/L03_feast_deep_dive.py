# ============================================================
# L03: Feast Deep Dive — Feature Views, Entities, Feature Services
# ============================================================
# WHAT: Feast's actual object model — Entities, Feature Views, Data
#       Sources, and Feature Services — and how they implement the
#       three-tier architecture from L02 as a real, open-source,
#       installable framework.
# WHY: L01-L02 covered feature store CONCEPTS and architecture in the
#      abstract. Feast is the most widely-adopted open-source
#      implementation of those concepts — this lesson maps the abstract
#      architecture onto Feast's concrete API so you can actually build
#      with it, not just understand the theory.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
An ENTITY in Feast represents the "thing" features are computed ABOUT —
a customer, a product, a transaction — identified by a join key (e.g.
`customer_id`). Entities are the KEY every feature lookup and PIT join
is performed against.

A DATA SOURCE tells Feast WHERE raw data lives (a table in a
warehouse/lakehouse — directly the Tier 1 output from L02) and which
COLUMN represents the event timestamp — this timestamp column is what
makes point-in-time-correct joins (L04) possible at all; Feast needs to
know, for every row, WHEN that row's data became true/available.

A FEATURE VIEW is Feast's version of L02's "feature definition" — it
declares: which Entity the features are about, which Data Source to
compute from, the list of individual features (name + type), and a TTL
(how "stale" a feature value is allowed to be before Feast considers it
invalid for a lookup — protecting against silently serving very old
data as if it were current). Feature Views are what gets REGISTERED
into Feast's registry (L02's Tier 2 concept, concretely implemented).

A FEATURE SERVICE groups MULTIPLE Feature Views together into the
specific bundle a single model actually needs — e.g. a fraud model's
Feature Service might combine features from a "customer_features" View
and a "transaction_features" View into one logical request, so the
model-serving code requests "give me the fraud_model_v2 feature service's
values for this entity" rather than manually listing every individual
feature view it depends on.

MATERIALIZATION is the Feast CLI/SDK operation that implements L02's
Tier 3 concept concretely: `feast materialize` reads Feature View
definitions, computes current values from the offline store, and writes
them into whichever online store backend is configured (Redis,
DynamoDB, or a custom plugin for something like ScyllaDB, L08).

PRODUCTION USE CASE:
A fraud-detection model's serving code calls
`store.get_online_features(features=fraud_feature_service, entity_rows=[{"transaction_id": "txn_123"}])`
— ONE call retrieving every feature the model needs, sourced from
potentially several different Feature Views, without the serving code
needing to know which underlying tables or Views each feature actually
comes from — that indirection is exactly what makes it safe for the
platform team to REORGANIZE Feature Views later without breaking every
model's serving code.

COMMON MISTAKES:
- Setting a Feature View's TTL too loosely (or not at all) — this can
  let Feast serve a feature value that's far staler than the model's
  training data ever saw, a subtle production-only failure mode distinct
  from training-serving skew but with a similar symptom (degraded
  real-world accuracy vs offline validation).
- Defining one giant Feature View covering unrelated features instead of
  grouping features by their NATURAL computation/refresh boundary —
  this couples unrelated features' materialization schedules together
  unnecessarily (a feature needing hourly refresh forces an unrelated,
  slow-changing feature in the same View to also refresh hourly).
- Bypassing Feature Services and having model-serving code query
  individual Feature Views directly — this reintroduces tight coupling
  between model code and the registry's internal organization, the
  exact problem Feature Services exist to decouple.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Entities, Data Sources, and Feature Views
# ------------------------------------------------------------------
FEAST_DEFINITIONS_EXAMPLE = textwrap.dedent("""\
    # feature_repo/definitions.py

    from feast import Entity, FeatureView, Field, FileSource
    from feast.types import Float32, Int64
    from datetime import timedelta

    # The ENTITY — features are computed ABOUT a customer, keyed by customer_id.
    customer = Entity(name="customer", join_keys=["customer_id"])

    # The DATA SOURCE — points at Tier 1's landed raw/aggregated data,
    # with the event_timestamp_column telling Feast WHEN each row's
    # values became true (essential for PIT correctness, L04).
    transaction_source = FileSource(
        path="s3://feature-repo/transaction_features.parquet",
        event_timestamp_column="event_timestamp",
    )

    # The FEATURE VIEW — a named, versioned definition (L02's Tier 2
    # concept) of specific features computed from that source.
    transaction_features = FeatureView(
        name="transaction_features",
        entities=[customer],
        ttl=timedelta(days=1),   # a value older than 1 day is considered
                                   # STALE and Feast will not silently
                                   # serve it as if it were current
        schema=[
            Field(name="avg_transaction_7d", dtype=Float32),
            Field(name="transaction_count_30d", dtype=Int64),
        ],
        source=transaction_source,
    )
""")

# ------------------------------------------------------------------
# 2. Feature Services — grouping views for a specific model
# ------------------------------------------------------------------
FEATURE_SERVICE_EXAMPLE = textwrap.dedent("""\
    from feast import FeatureService

    # Bundles features from MULTIPLE Feature Views into what ONE model
    # actually needs — model-serving code depends on this Service, not
    # on the individual underlying Views directly.
    fraud_model_v2_service = FeatureService(
        name="fraud_model_v2",
        features=[
            transaction_features[["avg_transaction_7d", "transaction_count_30d"]],
            customer_features[["days_since_signup", "account_risk_score"]],
        ],
    )
""")

# ------------------------------------------------------------------
# 3. Materialization — implementing Tier 3
# ------------------------------------------------------------------
MATERIALIZATION_COMMANDS = textwrap.dedent("""\
    # Materialize feature values from the offline store into the online
    # store for a specific historical range (e.g. backfilling):
    feast materialize 2026-01-01T00:00:00 2026-01-08T00:00:00

    # Materialize everything up to NOW — the typical scheduled/recurring
    # operation (run via Airflow/cron on each Feature View's own
    # appropriate cadence, per L02's independent-scheduling principle):
    feast materialize-incremental $(date -u +%Y-%m-%dT%H:%M:%S)
""")

# ------------------------------------------------------------------
# 4. Retrieving features — offline (training) vs online (serving)
# ------------------------------------------------------------------
OFFLINE_RETRIEVAL_EXAMPLE = textwrap.dedent("""\
    from feast import FeatureStore
    import pandas as pd

    store = FeatureStore(repo_path="feature_repo/")

    # entity_df provides the (entity_id, timestamp) pairs to join
    # against, POINT-IN-TIME CORRECTLY (L04) — this is Feast's
    # implementation of L02's "request a training dataset" SDK call.
    entity_df = pd.DataFrame({
        "customer_id": ["cust_1", "cust_2"],
        "event_timestamp": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")],
    })

    training_df = store.get_historical_features(
        entity_df=entity_df,
        features=["transaction_features:avg_transaction_7d",
                  "transaction_features:transaction_count_30d"],
    ).to_df()
""")

ONLINE_RETRIEVAL_EXAMPLE = textwrap.dedent("""\
    # The Tier 3 (online, low-latency) retrieval path — used at actual
    # inference time, querying the FeatureService for the CURRENT
    # values, not a historical point-in-time.
    online_features = store.get_online_features(
        features=fraud_model_v2_service,
        entity_rows=[{"customer_id": "cust_1"}],
    ).to_dict()
""")


if __name__ == "__main__":
    print(FEAST_DEFINITIONS_EXAMPLE)
    print(FEATURE_SERVICE_EXAMPLE)
    print(MATERIALIZATION_COMMANDS)
    print(OFFLINE_RETRIEVAL_EXAMPLE)
    print(ONLINE_RETRIEVAL_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A platform team migrates a fraud model from directly querying two
separate Feature Views to querying a single FeatureService bundling
both — six months later, the team reorganizes `transaction_features`
into two smaller, independently-refreshed Views (splitting a slow-
changing feature from a fast-changing one) with zero changes required to
the fraud model's serving code, because the model was never coupled to
the underlying Views' organization in the first place — exactly the
decoupling benefit Feature Services are designed to provide.
"""
