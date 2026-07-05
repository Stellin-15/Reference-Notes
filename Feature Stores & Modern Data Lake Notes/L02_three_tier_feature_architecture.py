# ============================================================
# L02: The Three-Tier Feature Management Architecture
# ============================================================
# WHAT: A layered architecture pattern used by production feature
#       platforms — Tier 1 (raw ingestion), Tier 2 (Feature Management
#       API + SDK), Tier 3 (online serving) — and why separating these
#       concerns into distinct tiers, rather than one monolithic system,
#       is what lets a platform scale to many teams/models.
# WHY: L01 established WHY a feature store needs an offline/online
#      split. This lesson covers the fuller architecture real platform
#      teams build around that split — the layer that lets HUNDREDS of
#      data scientists register and consume features without stepping
#      on each other or the platform team becoming a bottleneck.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
TIER 1 (RAW INGESTION) is responsible for getting raw event/transaction
data INTO the platform's storage layer, reliably and with minimal
transformation — this is the CDC/streaming/batch ingestion layer covered
in this repo's Data Engineering Notes (L02's CDC, Airflow/Databricks
pipelines), feeding into the lakehouse layer (Trino+Iceberg, L05-L07) or
a streaming platform (Kafka). Tier 1's job ends once raw data is
reliably landed — it does NOT compute features itself.

TIER 2 (FEATURE MANAGEMENT API + SDK) is where FEATURE DEFINITIONS live
— a registry of named, versioned feature computation logic (matching
L01's "define once" principle), exposed via an SDK that data scientists
use to: (a) DEFINE a new feature (declaring its computation, source
data, and refresh schedule), (b) DISCOVER existing features other teams
have already built (avoiding duplicate work), and (c) REQUEST a training
dataset (a point-in-time-correct join of specified features against a
set of entity/timestamp pairs). This tier is the actual PRODUCT
data scientists interact with day to day — its API/SDK design quality
directly determines how usable the whole platform feels.

TIER 3 (ONLINE SERVING) is the low-latency lookup layer L01 introduced —
but architecturally, it's fed by a MATERIALIZATION process that reads
Tier 2's feature definitions, computes CURRENT values, and writes them
into the online store (Redis/ScyllaDB, L08) on a schedule (or
continuously, for streaming features) — Tier 3 itself is "dumb" (a fast
key-value lookup); all the actual computation intelligence lives in
Tier 2's definitions, materialized on a schedule Tier 3 just serves.

This separation matters because each tier has a DIFFERENT owner and
DIFFERENT scaling concerns: Tier 1 is owned by data engineering (scales
with raw data volume), Tier 2 is owned by the platform/ML-infra team
(scales with the NUMBER OF FEATURES and TEAMS using the platform), and
Tier 3 is owned by SRE/infra (scales with INFERENCE REQUEST VOLUME) — a
monolithic, un-layered system conflates these concerns and makes it much
harder to scale or operate any one of them independently.

PRODUCTION USE CASE:
A new ML team wants to build a churn model. Instead of writing custom
ETL AND a custom low-latency serving path from scratch, they: query
Tier 2's SDK to discover 6 relevant features ALREADY defined by other
teams (avoiding duplicate feature engineering entirely), define 2 new
features specific to their use case (registered once, in Tier 2, with
Tier 1's raw data as the source), and their model's real-time serving
path simply queries Tier 3 for the current values of all 8 features by
customer ID — the team never touches raw ingestion pipelines or online
store infrastructure directly.

COMMON MISTAKES:
- Building Tier 2's feature registry without genuine DISCOVERABILITY
  (search, tagging, ownership metadata) — this defeats the "avoid
  duplicate feature engineering across teams" benefit, since a feature
  that exists but can't be found gets reimplemented anyway.
- Letting Tier 3 (online serving) perform its OWN feature computation
  logic independently of Tier 2's definitions — this reintroduces
  exactly the training-serving skew risk from L01 that the whole
  architecture exists to prevent.
- Coupling Tier 1's raw ingestion schedule directly to Tier 3's
  materialization schedule when they have genuinely different latency
  requirements (e.g. raw data lands hourly, but a specific feature needs
  minute-level freshness) — these should be independently schedulable,
  not forced into lockstep.
"""

from dataclasses import dataclass, field
from datetime import datetime


# ------------------------------------------------------------------
# 1. Tier 2 — the Feature Management API/SDK, as a minimal illustration
# ------------------------------------------------------------------
@dataclass
class FeatureRegistryEntry:
    name: str
    owner_team: str
    description: str
    source_table: str          # points at Tier 1's landed raw data
    computation_logic: str      # a reference to the actual compute function/SQL
    tags: list[str] = field(default_factory=list)


class FeatureRegistry:
    """
    Tier 2's core: a searchable, versioned registry of feature
    DEFINITIONS — not the feature VALUES themselves (those live in the
    offline/online stores, L01) but the metadata describing how each
    feature is computed and who owns it.
    """

    def __init__(self):
        self.features: dict[str, FeatureRegistryEntry] = {}

    def register(self, entry: FeatureRegistryEntry):
        if entry.name in self.features:
            raise ValueError(f"Feature '{entry.name}' already registered by "
                              f"{self.features[entry.name].owner_team} — "
                              f"use discover() to find it instead of re-defining.")
        self.features[entry.name] = entry

    def discover(self, tag: str | None = None, keyword: str | None = None) -> list[FeatureRegistryEntry]:
        """
        DISCOVERABILITY is the whole point of centralizing Tier 2 — a
        new team should find EXISTING relevant features before writing
        duplicate ones, which requires genuine search, not just a flat
        unsearchable list.
        """
        results = list(self.features.values())
        if tag:
            results = [f for f in results if tag in f.tags]
        if keyword:
            results = [f for f in results if keyword.lower() in f.description.lower()
                       or keyword.lower() in f.name.lower()]
        return results


# ------------------------------------------------------------------
# 2. Requesting a point-in-time-correct training dataset via the SDK
# ------------------------------------------------------------------
@dataclass
class EntityTimestampPair:
    entity_id: str
    timestamp: datetime
    label: float | None = None   # the training label, if building a training set


def request_training_dataset(
    registry: FeatureRegistry,
    feature_names: list[str],
    entity_timestamps: list[EntityTimestampPair],
) -> list[dict]:
    """
    THE core Tier 2 SDK call a data scientist makes: 'give me these N
    features, point-in-time-correct, for these entity/timestamp pairs.'
    The actual PIT join logic (L04) happens behind this call — the data
    scientist never writes a manual join against the offline store themselves.
    """
    rows = []
    for pair in entity_timestamps:
        row = {"entity_id": pair.entity_id, "timestamp": pair.timestamp, "label": pair.label}
        for name in feature_names:
            if name not in registry.features:
                raise KeyError(f"Feature '{name}' not found in registry — check discover() first")
            # A real implementation performs the actual PIT-correct
            # lookup against the offline store here (L04); this
            # illustration returns a placeholder to keep the SDK
            # CONTRACT visible without requiring a real offline store.
            row[name] = f"<value of {name} as of {pair.timestamp}>"
        rows.append(row)
    return rows


# ------------------------------------------------------------------
# 3. Tier 3 — materialization feeding the online store
# ------------------------------------------------------------------
MATERIALIZATION_NOTE = (
    "A materialization job reads Tier 2's feature DEFINITIONS, computes "
    "CURRENT values for every entity, and writes them into the Tier 3 "
    "online store (Redis/ScyllaDB, L08) — scheduled independently per "
    "feature based on its actual freshness requirement (some features "
    "materialize hourly; others, fed by a streaming source, materialize "
    "continuously). Tier 3 ITSELF performs no computation — it is a "
    "fast key-value lookup layer that always reflects whatever the last "
    "materialization run wrote, which is precisely why it can guarantee "
    "millisecond-latency reads: there is no computation happening on "
    "the read path at all."
)


def print_tier_ownership_model():
    tiers = {
        "Tier 1 (Raw Ingestion)": ("Data Engineering", "Raw data volume/throughput"),
        "Tier 2 (Feature Management API/SDK)": ("Platform/ML-Infra", "Number of features and teams onboarded"),
        "Tier 3 (Online Serving)": ("SRE/Infra", "Inference request volume/latency"),
    }
    for tier, (owner, scaling_concern) in tiers.items():
        print(f"{tier}")
        print(f"  owned by: {owner}")
        print(f"  scales with: {scaling_concern}\n")


if __name__ == "__main__":
    registry = FeatureRegistry()
    registry.register(FeatureRegistryEntry(
        name="avg_transaction_7d", owner_team="payments-ml",
        description="Average transaction amount over trailing 7 days",
        source_table="raw.transactions", computation_logic="see feature_defs/avg_transaction_7d.py",
        tags=["payments", "fraud"],
    ))
    registry.register(FeatureRegistryEntry(
        name="days_since_signup", owner_team="growth-ml",
        description="Number of days since account creation",
        source_table="raw.accounts", computation_logic="see feature_defs/days_since_signup.py",
        tags=["growth", "churn"],
    ))

    print("Discovering existing fraud-related features:")
    for f in registry.discover(tag="fraud"):
        print(f"  {f.name} (owned by {f.owner_team})")

    print("\nRequesting a training dataset via the Tier 2 SDK:")
    pairs = [EntityTimestampPair("cust_1", datetime(2026, 1, 1), label=1.0)]
    dataset = request_training_dataset(registry, ["avg_transaction_7d"], pairs)
    for row in dataset:
        print(f"  {row}")

    print(f"\n{MATERIALIZATION_NOTE}\n")
    print_tier_ownership_model()

"""
PRODUCTION CONTEXT EXAMPLE:
A platform supporting 1,500+ monthly active data scientists across many
independent ML teams relies entirely on Tier 2's discoverability to
avoid feature-engineering duplication at that scale — without a
searchable registry, the same "average transaction amount" feature
would likely be independently reimplemented (with subtly different
logic, reintroducing L01's skew risk) by every team that needs it,
rather than discovered and reused once from a central, well-tagged
registry entry.
"""
