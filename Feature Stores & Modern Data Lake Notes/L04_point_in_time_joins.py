# ============================================================
# L04: Point-in-Time Joins — Implementation, Leakage Bugs, Measuring Skew
# ============================================================
# WHAT: How to actually IMPLEMENT a point-in-time-correct join (not just
#       understand the concept from L01), the specific bug patterns that
#       cause label leakage, and how a team concretely measures and
#       drives DOWN training-serving skew (e.g. the 3.1% -> 0.4%
#       reduction referenced in real production case studies).
# WHY: L01 introduced PIT correctness conceptually. This is the lesson
#      where you build the actual join logic — the single most common
#      place feature-store implementations get subtly wrong, since a
#      buggy PIT join LOOKS correct (code runs, produces a dataframe)
#      while silently leaking future information.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
A point-in-time-correct join answers: "for entity E at timestamp T, what
was the MOST RECENT feature value that had ALREADY BEEN COMPUTED as of
T" — critically, "as of T" means the feature computation's OWN timestamp
must be <= T, not that the row simply exists in the table. A naive join
(join entity_df to the feature table on entity_id alone, or using the
feature table's LATEST value regardless of the requested timestamp)
silently uses information that wouldn't have actually been available at
that historical point — this is LABEL LEAKAGE, and it's the most common,
most damaging bug in home-grown feature-retrieval code.

The correct algorithm, conceptually: for each (entity_id, timestamp)
pair in the entity_df, find the feature table row with the SAME
entity_id and the LARGEST feature_timestamp that is STILL <= the
requested timestamp — this is naturally expressed as an AS-OF JOIN (a
join type some SQL engines, including Trino via specific window
functions, support somewhat directly; otherwise implemented via a window
function ranking candidate rows per entity and taking the top one).

A second correctness dimension: FEATURE VALIDITY WINDOW (Feast's TTL
from L03) — even the "most recent value <= T" might be TOO OLD to be
meaningfully "known" at T (e.g. a feature that's supposed to refresh
hourly, but a materialization job failed for 3 days) — a rigorous PIT
join should also EXCLUDE feature values older than the TTL, treating
them as missing (null) rather than silently serving stale data as if it
were fresh.

MEASURING TRAINING-SERVING SKEW concretely (not just conceptually)
means: for a sample of REAL production inference requests, log both (a)
the online-store feature value actually used for that prediction, and
(b) what the offline store's PIT join would have computed for that exact
entity/timestamp — then compute the distribution of DIFFERENCES between
(a) and (b) across many samples. A meaningful skew-reduction initiative
(e.g. going from 3.1% average discrepancy to 0.4%) is the result of
finding and fixing the SPECIFIC divergent logic (a different window
definition, a different null-handling rule, a materialization lag) this
measurement surfaces — it's an iterative, measured process, not a
one-time fix.

PRODUCTION USE CASE:
A team building a training set for "predict churn 30 days out" naively
joins each customer's LATEST known feature values (queried from today's
warehouse state) to historical labels from 6 months ago — every training
example silently uses feature values that reflect information from
TODAY, not from 6 months ago when the prediction would actually need to
be made. The model's offline validation accuracy looks great (because it's
effectively cheating, seeing the future), and its real production
accuracy is much worse — a PIT-correct join, re-run to rebuild the
training set, closes this gap and produces an offline accuracy that
actually reflects real deployment performance.

COMMON MISTAKES:
- Joining a feature table's CURRENT/LATEST snapshot to historical labels
  instead of a genuinely PIT-correct join — this is the single most
  common and most severe form of label leakage, and it's easy to write
  by accident with a naive `pd.merge()` or `JOIN` that doesn't account
  for time at all.
- Using `<=` vs `<` inconsistently at the training/serving boundary — if
  a feature computed AT EXACTLY the prediction timestamp is included in
  training but the serving path only sees features computed STRICTLY
  BEFORE that instant (or vice versa), this is a small but real and
  measurable source of skew.
- Not accounting for TTL/staleness in the PIT join — finding the
  "most recent value <= T" without checking it's not ALSO too stale to
  be a valid signal silently accepts arbitrarily old data as if it were
  fresh, a distinct failure mode from leakage but similarly damaging.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta


# ------------------------------------------------------------------
# 1. The WRONG way — naive join using "latest known value"
# ------------------------------------------------------------------
@dataclass
class FeatureRow:
    entity_id: str
    feature_timestamp: datetime   # WHEN this value was computed/became true
    value: float


def naive_leaky_join(entity_id: str, feature_rows: list[FeatureRow]) -> float | None:
    """
    THE BUG: returns the LATEST value regardless of what timestamp the
    training example actually needs — silently leaks any future
    information present in the feature table.
    """
    candidates = [r for r in feature_rows if r.entity_id == entity_id]
    if not candidates:
        return None
    latest = max(candidates, key=lambda r: r.feature_timestamp)
    return latest.value


# ------------------------------------------------------------------
# 2. The CORRECT way — a genuine point-in-time-correct join
# ------------------------------------------------------------------
def point_in_time_correct_join(
    entity_id: str, as_of: datetime, feature_rows: list[FeatureRow],
    ttl: timedelta | None = None,
) -> float | None:
    """
    Finds the MOST RECENT feature value whose feature_timestamp is
    <= as_of (never using information from AFTER the requested point in
    time), and additionally excludes values older than `ttl` if
    provided — treating stale values as missing rather than silently
    serving them as current.
    """
    candidates = [
        r for r in feature_rows
        if r.entity_id == entity_id and r.feature_timestamp <= as_of
    ]
    if ttl is not None:
        candidates = [r for r in candidates if (as_of - r.feature_timestamp) <= ttl]

    if not candidates:
        return None
    most_recent = max(candidates, key=lambda r: r.feature_timestamp)
    return most_recent.value


def demonstrate_leakage_bug():
    feature_rows = [
        FeatureRow("cust_1", datetime(2026, 1, 1), 100.0),
        FeatureRow("cust_1", datetime(2026, 6, 1), 500.0),   # a MUCH later, "future" value
    ]
    training_example_timestamp = datetime(2026, 1, 15)   # a label from mid-January

    leaky_value = naive_leaky_join("cust_1", feature_rows)
    correct_value = point_in_time_correct_join("cust_1", training_example_timestamp, feature_rows)

    print(f"Naive join (LEAKY): {leaky_value}  <- this is the JUNE value, "
          f"impossible to have known in January")
    print(f"PIT-correct join:   {correct_value}  <- correctly uses only "
          f"the January value, the only one that existed by the training "
          f"example's timestamp")


def demonstrate_ttl_staleness():
    feature_rows = [
        FeatureRow("cust_1", datetime(2026, 1, 1), 100.0),   # 10 days stale relative to as_of below
    ]
    as_of = datetime(2026, 1, 11)

    no_ttl = point_in_time_correct_join("cust_1", as_of, feature_rows, ttl=None)
    with_ttl = point_in_time_correct_join("cust_1", as_of, feature_rows, ttl=timedelta(days=1))

    print(f"\nWithout TTL check: {no_ttl}  <- silently serves a 10-day-old value")
    print(f"With 1-day TTL:    {with_ttl}  <- correctly treated as missing (too stale)")


# ------------------------------------------------------------------
# 3. Measuring skew — comparing offline PIT vs online store values
# ------------------------------------------------------------------
@dataclass
class SkewSample:
    entity_id: str
    online_value: float     # what the online store actually served for a real prediction
    offline_pit_value: float  # what a PIT-correct offline join computes for the same instant


def measure_skew(samples: list[SkewSample]) -> dict:
    diffs = [abs(s.online_value - s.offline_pit_value) for s in samples]
    avg_pct_diff = sum(
        abs(s.online_value - s.offline_pit_value) / max(abs(s.offline_pit_value), 1e-9)
        for s in samples
    ) / len(samples) * 100
    return {
        "num_samples": len(samples),
        "mean_absolute_diff": sum(diffs) / len(diffs),
        "mean_percent_diff": avg_pct_diff,
    }


def skew_measurement_demo():
    # A sample reflecting REDUCED skew after fixing a divergent window
    # definition — a realistic before/after a remediation, mirroring a
    # measured skew-reduction initiative.
    before_fix = [
        SkewSample("cust_1", online_value=105.2, offline_pit_value=100.0),
        SkewSample("cust_2", online_value=98.1, offline_pit_value=95.0),
    ]
    after_fix = [
        SkewSample("cust_1", online_value=100.3, offline_pit_value=100.0),
        SkewSample("cust_2", online_value=95.2, offline_pit_value=95.0),
    ]
    print("\nSkew measurement, before fix:", measure_skew(before_fix))
    print("Skew measurement, after fix: ", measure_skew(after_fix))


if __name__ == "__main__":
    demonstrate_leakage_bug()
    demonstrate_ttl_staleness()
    skew_measurement_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A platform team drives a measured training-serving skew reduction (e.g.
from a 3.1% average discrepancy to 0.4%) by systematically sampling
production inference requests, comparing each one's actual online-store
feature value against what a PIT-correct offline join computes for the
same entity/timestamp, and iterating on the SPECIFIC divergent logic
each round of measurement surfaces — this is not a single one-time fix,
but exactly the kind of ongoing, measured discipline that separates a
feature platform's marketing claim of "consistent features" from an
actually-verified guarantee.
"""
