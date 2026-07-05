# ============================================================
# L12: Production Feature Platform Architecture — Full Reference System
# ============================================================
# WHAT: A capstone lesson wiring together every piece from L01-L11 into
#       ONE coherent, production feature/data platform — the three-tier
#       architecture, Trino+Iceberg lakehouse, Redis+ScyllaDB hybrid
#       serving, lineage/event-ledger governance, and polymorphic
#       compute, composed end to end.
# WHY: Every prior lesson covered one piece. Real feature platforms are
#      an INTEGRATED system serving many teams simultaneously — this
#      lesson shows how the pieces actually fit together, and traces one
#      concrete request through the full stack.
# LEVEL: Capstone
# ============================================================

"""
CONCEPT OVERVIEW:
A production feature platform, assembled from this domain's pieces:

  1. TIER 1 — RAW INGESTION: CDC/streaming/batch pipelines (this repo's
     Data Engineering Notes) land raw data as Iceberg tables (L06) in a
     lakehouse spanning cloud object storage and/or on-prem HDFS (L07).
  2. TIER 2 — FEATURE MANAGEMENT (L02-L03): a registry (Feast or a
     custom equivalent) where feature DEFINITIONS live, with
     DISCOVERABILITY so teams reuse rather than duplicate features.
     Point-in-time-correct joins (L04) generate training datasets by
     querying the Tier 1 lakehouse via Trino (L05).
  3. TIER 3 — ONLINE SERVING (L08): a materialization process
     periodically computes current feature values and writes them into
     a Redis (hot)/ScyllaDB (bulk) hybrid online store, serving
     millisecond-latency lookups at inference time.
  4. GOVERNANCE LAYER (L09-L10): an event ledger captures every
     meaningful platform operation; lineage (which models depend on
     which features/sources) and drift/SLA analytics are DERIVED from
     that same ledger, not separately instrumented.
  5. COMPUTE LAYER (L11): a polymorphic compute platform (Kernels-as-a-
     Service pattern) lets data scientists run exploratory AND
     production-scale feature-engineering work against whichever backend
     (YARN/K8s/Vertex/Ray) fits the job, through one notebook interface.

This is not a rigid template — a smaller organization might reasonably
skip the ScyllaDB tier (Redis alone, at smaller scale) or the polymorphic
compute layer (a single Kubernetes-based notebook environment, if
there's no legacy on-prem YARN to bridge) — but the TIERS and their
responsibilities are the stable pattern most mature feature platforms
converge on regardless of exact tool choices per tier.

PRODUCTION USE CASE:
See the full reference architecture and end-to-end request trace below
— this is the shape a feature platform serving many concurrent ML teams
at real organizational scale takes, whether built on the exact
technologies named in this domain or reasonable substitutes at each tier
(e.g. DynamoDB instead of ScyllaDB, Delta Lake instead of Iceberg).

COMMON MISTAKES:
- Building Tier 2 (feature management) and Tier 3 (online serving)
  without the governance layer (L09-L10) from day one — lineage/drift/
  SLA tracking retrofitted onto an already-large platform is
  significantly more expensive than designing the event ledger in from
  the start, since it requires going back and instrumenting every
  existing integration point rather than building it in once, upfront.
- Scaling prematurely to the full architecture (ScyllaDB, polymorphic
  multi-backend compute) before the organization's actual scale
  justifies it — a small platform serving a handful of teams is often
  well served by Redis alone and a single compute backend; add
  complexity when actual measured need (not anticipated future need)
  demands it.
- Treating this architecture as one-size-fits-all rather than adapting
  tier boundaries and specific tool choices to the organization's actual
  existing infrastructure investment (e.g. an organization with no
  on-prem Hadoop legacy has no reason to build hybrid on-prem/cloud
  federation, L07's specific pattern, from scratch).
"""

import textwrap


# ------------------------------------------------------------------
# 1. Full reference architecture diagram
# ------------------------------------------------------------------
REFERENCE_ARCHITECTURE = r"""
    Raw Data Sources (Data Engineering Notes: Airflow/Databricks/CDC)
              |
              v
    +--------------------+
    | Tier 1: Ingestion    |  -> lands as Iceberg tables (L06)
    +----------+-----------+
               |
               v
    +--------------------+     +----------------------+
    | Lakehouse (L05-L07)  |<--->| Trino query engine     |
    | Iceberg on S3/HDFS   |     | (federated queries)    |
    +----------+-----------+     +----------------------+
               |
               v
    +--------------------+
    | Tier 2: Feature       |  <- Feast/custom registry (L02-L03)
    | Management API/SDK    |  <- PIT-correct joins (L04)
    +----------+-----------+
               |
        +------+-------+
        |               |
        v               v
    +---------+   +------------------+
    | Training |   | Materialization   |
    | datasets |   | (scheduled)        |
    +---------+   +--------+-----------+
                            |
                            v
                  +--------------------+
                  | Tier 3: Online       |  <- Redis (hot) + ScyllaDB
                  | Serving (L08)         |     (bulk) hybrid
                  +--------------------+
                            ^
                            |
                  +--------------------+
                  | Model serving        |  <- real-time inference
                  | (this repo's MLOps    |
                  |  Notes / model         |
                  |  serving)              |
                  +--------------------+

    Governance (cross-cutting, wraps EVERY tier above):
    +----------------------------------------------------+
    | Event Ledger (L10) -> Lineage graph (L09) ->          |
    | Drift detection + SLA monitoring, all DERIVED from     |
    | the same ledger                                        |
    +----------------------------------------------------+

    Compute (used to BUILD/explore the above):
    +----------------------------------------------------+
    | Polymorphic Compute Platform (L11): one notebook UI,   |
    | routed via ProcessProxy to YARN/K8s/Vertex/Ray          |
    +----------------------------------------------------+
"""

# ------------------------------------------------------------------
# 2. A concrete end-to-end trace: from feature definition to serving
# ------------------------------------------------------------------
END_TO_END_TRACE_EXAMPLE = textwrap.dedent("""\
    Scenario: a new fraud model needs a feature "avg_transaction_7d."

    1. [Compute, L11] A data scientist launches a notebook kernel on a
       YARN backend (large historical data volume needed) via the
       Kernel Gateway, with their auth token propagated through the
       launch chain.

    2. [Tier 2, L02-L03] They query the feature registry (discover())
       and find NO existing feature matches their need — they define
       "avg_transaction_7d" as a new Feature View, sourced from
       raw.transactions.

    3. [Governance, L10] Registering the feature emits a
       FEATURE_REGISTERED event to the ledger.

    4. [Tier 1/Lakehouse, L05-L07] The Feature View's computation runs
       as a Trino query against the Iceberg-backed raw.transactions
       table (spanning both on-prem and cloud storage, if mid-migration).

    5. [Tier 2, L04] Requesting a TRAINING dataset performs a point-in-
       time-correct join against historical labels, producing a
       training set with zero label leakage.

    6. [Governance, L10] Model training emits a MODEL_TRAINED event,
       recording that "fraud_detector_v3" depends on
       "avg_transaction_7d" — this automatically extends the lineage
       graph (L09) with zero separate lineage-maintenance work.

    7. [Tier 3, L08] A scheduled materialization job computes CURRENT
       values of "avg_transaction_7d" for every customer, writing them
       to ScyllaDB (bulk) with active customers also cached in Redis (hot).

    8. [Serving] The deployed fraud_detector_v3 model, at inference
       time, looks up "avg_transaction_7d" from the online store
       (millisecond latency) — the SAME feature definition used at
       training (step 5) and serving (step 8), eliminating training-
       serving skew (L01) by construction.

    9. [Governance, L10] A drift-detection job, running weekly and
       derived from materialization_run events, flags if
       "avg_transaction_7d"'s real-world distribution shifts
       meaningfully — the SAME ledger data serving compliance (lineage),
       operations (SLA), and model-quality (drift) purposes.
""")

# ------------------------------------------------------------------
# 3. Layer responsibilities, summarized
# ------------------------------------------------------------------
LAYER_RESPONSIBILITIES = {
    "Tier 1 (Ingestion)": "Getting raw data reliably into the lakehouse (Iceberg, L06).",
    "Lakehouse (L05-L07)": "Federated, ACID-transactional queryable storage over object storage/HDFS.",
    "Tier 2 (Feature Management)": "Defining features ONCE; serving both training and PIT-correct data.",
    "Tier 3 (Online Serving)": "Millisecond-latency current feature values for real-time inference.",
    "Governance (L09-L10)": "Lineage, drift, and SLA analytics — all derived from one event ledger.",
    "Compute (L11)": "Letting data scientists run any workload against the right-sized backend.",
}


if __name__ == "__main__":
    print(REFERENCE_ARCHITECTURE)
    print(END_TO_END_TRACE_EXAMPLE)
    print("=== Layer responsibilities ===")
    for layer, responsibility in LAYER_RESPONSIBILITIES.items():
        print(f"{layer}: {responsibility}")

"""
FINAL CONTEXT:
The measure of having internalized this domain isn't naming every
technology (Trino, Iceberg, ScyllaDB, Feast) — it's being able to trace,
for a NEW feature request at your own organization, exactly which tier
handles which responsibility, and knowing precisely which earlier lesson
to revisit for the implementation details of whichever tier you're
building or debugging next. This folder is meant to function as a
working reference during that actual build, not a one-time read-through.
"""
