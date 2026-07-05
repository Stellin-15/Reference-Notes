# ============================================================
# L01: Feature Store Fundamentals — Why They Exist, Training-Serving Skew
# ============================================================
# WHAT: The core problem a feature store solves — keeping the features
#       a model was TRAINED on consistent with the features it sees at
#       INFERENCE time — via the offline/online store split and
#       point-in-time correctness.
# WHY: This repo's MLOps Notes L03 introduces Feast at a survey level.
#      This domain goes deeper into the actual ARCHITECTURE production
#      feature platforms use (the three-tier model in L02, Trino+Iceberg
#      in L05-L07, ScyllaDB+Redis in L08) — this lesson is the
#      foundational "why" everything else in the domain builds on.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
TRAINING-SERVING SKEW is the specific, damaging bug class a feature
store exists to prevent: a model is trained on features computed one way
(e.g. a batch Spark job computing "average order value over the last 30
days" from a data warehouse), but at INFERENCE time, a different code
path computes a SIMILAR but not IDENTICAL feature (e.g. a real-time
service computing the same logical feature from a live cache, with a
subtly different time window or null-handling rule) — the model's
predictions degrade because what it's fed at serving time doesn't match
what it learned from during training, even though nobody explicitly
"changed" the model.

A feature store's core architectural answer: define each feature's
computation logic ONCE, and generate BOTH the training data (a historical,
point-in-time-correct view for building training sets) and the serving
data (a low-latency, current-value view for real-time inference) FROM
THAT SAME DEFINITION — eliminating the two-separate-code-paths problem
that causes skew in the first place.

This requires TWO physically different stores, because training and
serving have incompatible performance requirements:
  - OFFLINE STORE: optimized for large-volume, point-in-time-correct
    historical queries (building a training set spanning months of
    history) — typically a data warehouse/lakehouse (Trino+Iceberg,
    Snowflake, BigQuery), where query latency of seconds is fine.
  - ONLINE STORE: optimized for single-key, low-latency lookups (serving
    ONE prediction request needs the CURRENT feature value in
    milliseconds) — typically Redis, DynamoDB, or (at higher scale)
    ScyllaDB (L08), where a multi-second warehouse query would be
    unacceptable.

POINT-IN-TIME (PIT) CORRECTNESS is the specific guarantee that makes
training data trustworthy: when building a training example for "will
this customer churn, as of March 1st," the features used must reflect
ONLY information that was ACTUALLY AVAILABLE as of March 1st — not
future information that happens to be in the warehouse now. Getting this
wrong (using a feature value that was only computed/updated AFTER the
training example's timestamp) is called LABEL LEAKAGE, and it silently
inflates offline model accuracy while the model performs far worse in
production, where that "future" information genuinely isn't available
yet. L04 covers PIT joins in full implementation depth.

PRODUCTION USE CASE:
A fraud-detection model trained on "average transaction amount over the
last 7 days" computed via a nightly batch job achieves 94% offline
accuracy — but in production, a REAL-TIME feature-computation service
uses a slightly different 7-day window (calendar days vs rolling 168
hours) and handles a customer's first-ever transaction differently (null
vs zero) than the training pipeline did. The mismatch between these two
independently-written implementations of "the same" feature is
classic training-serving skew, and it's exactly what a feature store's
single-definition-two-views architecture is built to prevent.

COMMON MISTAKES:
- Writing feature computation logic TWICE — once for batch/training,
  once for real-time/serving — instead of defining it once and deriving
  both views from that single definition; this duplication is the
  direct, structural cause of most training-serving skew incidents.
- Building a training set by joining "current" feature values (a single
  warehouse snapshot) to historical labels, instead of a genuinely
  point-in-time-correct join — this silently leaks future information
  into every training example that predates the snapshot.
- Assuming a feature store is only about the ONLINE serving layer — the
  OFFLINE, point-in-time-correct historical view is equally core to what
  makes a feature store different from "just a cache in front of a database."
"""

from dataclasses import dataclass
from datetime import datetime, timedelta


# ------------------------------------------------------------------
# 1. Illustrating training-serving skew concretely
# ------------------------------------------------------------------
@dataclass
class Transaction:
    customer_id: str
    amount: float
    timestamp: datetime


def batch_compute_avg_transaction_7d(transactions: list[Transaction], as_of: datetime) -> float | None:
    """
    The TRAINING-TIME feature computation — a batch job scanning a
    warehouse table, using a CALENDAR-DAY window.
    """
    window_start = as_of - timedelta(days=7)
    relevant = [t.amount for t in transactions if window_start <= t.timestamp < as_of]
    return sum(relevant) / len(relevant) if relevant else None   # None for no history


def realtime_compute_avg_transaction_7d(transactions: list[Transaction], as_of: datetime) -> float:
    """
    A DIFFERENT, independently-written SERVING-TIME implementation of
    "the same" feature — uses a ROLLING 168-HOUR window (subtly
    different from calendar days near boundaries) and defaults to 0.0
    instead of None for a customer with no history. Small differences,
    but they mean the model sees DIFFERENT distributions of this
    "same" feature at training vs serving time.
    """
    window_start = as_of - timedelta(hours=168)
    relevant = [t.amount for t in transactions if window_start <= t.timestamp < as_of]
    return sum(relevant) / len(relevant) if relevant else 0.0   # 0.0, not None — a real discrepancy


def demonstrate_skew():
    now = datetime(2026, 1, 8, 0, 0, 0)
    transactions = [
        Transaction("cust_1", 100.0, datetime(2026, 1, 1, 0, 0, 0)),  # exactly at the 7-day boundary
        Transaction("cust_1", 200.0, datetime(2026, 1, 5, 0, 0, 0)),
    ]
    batch_value = batch_compute_avg_transaction_7d(transactions, now)
    realtime_value = realtime_compute_avg_transaction_7d(transactions, now)
    print(f"Batch (training-time) computed value:    {batch_value}")
    print(f"Real-time (serving-time) computed value: {realtime_value}")
    print("These SHOULD be identical (same logical feature) but the "
          "independently-written window/null-handling logic diverges — "
          "exactly the bug class a feature store's single-definition "
          "architecture is built to eliminate.")


# ------------------------------------------------------------------
# 2. A single feature DEFINITION generating both views (the fix)
# ------------------------------------------------------------------
@dataclass
class FeatureDefinition:
    """
    ONE definition of a feature's computation logic — both the offline
    (training) and online (serving) views are derived from calling THIS
    same function, eliminating the two-implementations problem entirely.
    """
    name: str
    window: timedelta
    aggregation: str  # "avg", "sum", "count", etc.

    def compute(self, transactions: list[Transaction], as_of: datetime) -> float | None:
        window_start = as_of - self.window
        relevant = [t.amount for t in transactions if window_start <= t.timestamp < as_of]
        if not relevant:
            return None   # ONE consistent null-handling rule, used everywhere
        if self.aggregation == "avg":
            return sum(relevant) / len(relevant)
        elif self.aggregation == "sum":
            return sum(relevant)
        raise ValueError(f"Unknown aggregation: {self.aggregation}")


def unified_definition_demo():
    feature_def = FeatureDefinition("avg_transaction_7d", timedelta(days=7), "avg")
    transactions = [
        Transaction("cust_1", 100.0, datetime(2026, 1, 1, 0, 0, 0)),
        Transaction("cust_1", 200.0, datetime(2026, 1, 5, 0, 0, 0)),
    ]
    now = datetime(2026, 1, 8, 0, 0, 0)

    # Both "training-time" (historical batch call) and "serving-time"
    # (real-time call) use the EXACT SAME compute() method — there is
    # structurally no way for them to diverge, because there's only one
    # implementation.
    training_value = feature_def.compute(transactions, as_of=now)
    serving_value = feature_def.compute(transactions, as_of=now)
    print(f"Unified definition — training value: {training_value}, serving value: {serving_value}")
    print("Identical by construction, not by discipline/luck.")


# ------------------------------------------------------------------
# 3. Offline vs online store — why TWO physical stores are needed
# ------------------------------------------------------------------
STORE_REQUIREMENTS_COMPARISON = {
    "Offline store (training)": {
        "query_pattern": "Large-volume, point-in-time-correct historical joins "
                          "(build a training set spanning months of history)",
        "latency_tolerance": "Seconds to minutes per query is acceptable",
        "typical_tech": "Data warehouse/lakehouse (Trino+Iceberg, Snowflake, BigQuery)",
    },
    "Online store (serving)": {
        "query_pattern": "Single-key lookup: 'give me customer X's CURRENT "
                          "feature values' for one live prediction request",
        "latency_tolerance": "Single-digit milliseconds — a slow lookup here "
                              "directly adds to end-user-facing request latency",
        "typical_tech": "Redis, DynamoDB, or ScyllaDB at higher throughput/"
                         "storage scale (L08)",
    },
}


if __name__ == "__main__":
    demonstrate_skew()
    print()
    unified_definition_demo()
    print()
    for store, requirements in STORE_REQUIREMENTS_COMPARISON.items():
        print(f"{store}:")
        for k, v in requirements.items():
            print(f"  {k}: {v}")
        print()

"""
PRODUCTION CONTEXT EXAMPLE:
A platform team migrating from ad-hoc, per-team feature computation
(each ML team writing their own batch AND real-time feature code) to a
centralized feature store measures training-serving skew directly by
comparing offline-computed vs online-computed values for the SAME
feature, SAME entity, SAME timestamp across a sample of production
requests — catching exactly the kind of window/null-handling divergence
shown in `demonstrate_skew()` before it silently degrades a model in
production, and eliminating the discrepancy class entirely once every
team's features are defined once (per `unified_definition_demo()`'s
pattern) rather than twice.
"""
