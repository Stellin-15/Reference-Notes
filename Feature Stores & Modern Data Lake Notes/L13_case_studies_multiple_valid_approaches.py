"""
WHAT: Four realistic feature-platform problems, each solved with THREE
      genuinely different, individually defensible approaches drawn
      from L01-L12 -- with an explicit comparison table and reasoning
      for why each answer is valid under different constraints.
WHY:  "Redis or ScyllaDB for the online store," "Feast or a hand-rolled
      pipeline," "how to enforce point-in-time correctness" are all
      questions L01-L12 gave you real tools for, not one universal
      answer -- this lesson is about the decision process under real
      latency and team-maturity constraints.
LEVEL: Capstone -- read after L01-L12.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L12's concepts.
"""

# ============================================================================
# CASE STUDY 1 — CHOOSING AN ONLINE FEATURE STORE FOR A REAL-TIME
# RECOMMENDATION SYSTEM
# ============================================================================
#
# SETUP: a recommendation service needs sub-10ms feature lookups at
# inference time, serving a mix of a FEW hundred "hot" features per user
# (recently updated, frequently read) and MANY thousands of "bulk"
# features (item embeddings, less frequently updated, large total
# volume).
#
# ------------------------------------------------------------------------
# APPROACH A: Redis alone for everything (L08)
# ------------------------------------------------------------------------
#   WHY VALID: per L08, Redis's in-memory design gives the lowest
#   possible latency for ANY feature lookup, hot or bulk -- the
#   simplest possible architecture (one system, one access pattern) if
#   the TOTAL feature volume (hot + bulk combined) comfortably fits in
#   memory within budget.
#   COST: per L08, keeping ALL bulk features (thousands of item
#   embeddings, potentially large in aggregate) in expensive in-memory
#   storage is a real, direct cost -- Redis memory is priced at a
#   premium relative to disk-backed storage, and much of the bulk
#   feature volume may be read far less frequently than hot features,
#   making it an inefficient use of the most expensive storage tier
#   for data that doesn't need that tier's latency.
#
# ------------------------------------------------------------------------
# APPROACH B: ScyllaDB alone for everything (L08)
# ------------------------------------------------------------------------
#   WHY VALID: per L08, ScyllaDB's wide-column, disk-backed (with
#   caching) architecture handles LARGE data volumes far more cost-
#   effectively than an all-in-memory approach, and its latency, while
#   higher than pure Redis, is still generally fast enough for many
#   real-time serving needs -- a more cost-efficient default if the
#   bulk feature volume dominates and the latency requirement isn't
#   quite as extreme as "every single lookup must be sub-millisecond."
#   COST: per L08, ScyllaDB's per-lookup latency, while good, is
#   typically higher than Redis's pure in-memory access -- for the
#   HOT, frequently-accessed features specifically, this "good enough
#   for most things" latency may not comfortably clear a tight overall
#   p99 budget once you account for looking up MANY hot features per
#   inference request.
#
# ------------------------------------------------------------------------
# APPROACH C: The Redis (hot) + ScyllaDB (bulk) hybrid pattern (L08)
# ------------------------------------------------------------------------
#   WHY VALID: per L08, this directly matches EACH feature tier to the
#   storage system best suited to its actual access pattern -- hot,
#   latency-critical, frequently-updated features get Redis's speed;
#   large-volume, less latency-critical bulk features get ScyllaDB's
#   cost-effective scale -- avoiding both A's overspend on bulk data and
#   B's latency risk on hot data.
#   COST: per L08, this is the most architecturally complex of the
#   three -- TWO systems to operate, monitor, and keep correctly synced
#   with the offline feature pipeline, and requires explicit,
#   maintained logic classifying which features belong in which tier (a
#   real, ongoing categorization decision as new features are added,
#   not a one-time setup task).
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Latency for hot features | Cost efficiency for bulk features | Operational complexity |
#   |----------|-------------------------------|------------------------------------------|------------------------------|
#   | A: Redis only | Best | Poor (expensive at scale) | Lowest |
#   | B: ScyllaDB only | Good, not best | Good | Lowest |
#   | C: Redis + ScyllaDB hybrid | Best | Good | Highest |
#   Given this case study's EXPLICIT bimodal access pattern (few hot,
#   many bulk), C is the architecturally correct answer, per L08's own
#   framing -- A or B alone are reasonable simplifications only when the
#   actual feature set doesn't genuinely have this bimodal shape.


# ============================================================================
# CASE STUDY 2 — DECIDING WHETHER TO ADOPT FEAST OR BUILD A CUSTOM
# FEATURE PIPELINE
# ============================================================================
#
# SETUP: a team building their first production feature platform is
# deciding between adopting Feast (L03) or building custom offline/
# online feature pipelines in-house.
#
# ------------------------------------------------------------------------
# APPROACH A: Adopt Feast (L03) as the feature store framework
# ------------------------------------------------------------------------
#   WHY VALID: per L03, Feast provides battle-tested implementations of
#   genuinely hard problems -- point-in-time-correct joins (L04),
#   feature-view/entity abstractions, and materialization pipelines --
#   getting a team most of the way to a working feature platform without
#   needing to correctly re-derive these subtle correctness properties
#   from scratch.
#   COST: per L03, Feast imposes its OWN opinionated abstractions
#   (feature views, entities, feature services) that the team's data
#   model and pipelines need to conform to -- a real constraint if the
#   team's actual needs don't map cleanly onto Feast's assumptions, and
#   adopting any framework means depending on its release cadence,
#   community support, and specific limitations rather than having full
#   control.
#
# ------------------------------------------------------------------------
# APPROACH B: Build a custom pipeline in-house
# ------------------------------------------------------------------------
#   WHY VALID: full control over every design decision, no framework
#   constraints or dependencies, and can be tailored EXACTLY to the
#   team's specific needs without working around a framework's
#   assumptions -- appropriate if the team's requirements are genuinely
#   unusual enough that Feast's abstractions would be a poor fit.
#   COST: per L04's point-in-time-join lesson specifically, correctly
#   implementing point-in-time correctness FROM SCRATCH is a genuinely
#   subtle problem with well-documented, easy-to-introduce label-leakage
#   bugs -- a team building this themselves is re-deriving (and risking
#   re-making the mistakes in) a problem that mature tooling has already
#   solved, a real, avoidable correctness risk on top of the raw
#   engineering time cost.
#
# ------------------------------------------------------------------------
# APPROACH C: Adopt Feast for the parts of the problem it solves well
# (point-in-time joins, the offline/online abstraction), but build
# CUSTOM integration/glue code for the team's specific, non-standard
# data sources or serving requirements that don't fit Feast's built-in
# connectors
# ------------------------------------------------------------------------
#   WHY VALID: per L03's own framing of feature stores as a THREE-TIER
#   architecture, this captures A's correctness benefits for the
#   genuinely hard, well-solved sub-problems while retaining B's
#   flexibility specifically where the team's needs are actually
#   unusual -- most real production feature platforms end up doing
#   SOME version of this, using a framework as a foundation rather than
#   an all-or-nothing choice.
#   COST: requires clearly understanding WHERE Feast's abstractions end
#   and custom code begins -- a real architectural design decision that,
#   done poorly, can result in a confusing hybrid that's harder to
#   understand than either a pure framework adoption or a pure custom
#   build would have been on their own.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Correctness risk (point-in-time joins) | Flexibility for unusual needs | Time to first working system |
#   |----------|-----------------------------------------------|-------------------------------------|-------------------------------------|
#   | A: pure Feast | Lowest | Lowest | Fastest |
#   | B: pure custom | Highest | Highest | Slowest |
#   | C: Feast + custom glue | Low | High | Medium |
#   C is the strongest default for most teams -- adopt Feast for the
#   subtle, well-solved correctness-critical pieces, and reserve custom
#   engineering effort specifically for the genuinely non-standard parts
#   of the problem, rather than re-deriving solved problems (B) or
#   forcing every requirement into a framework's assumptions (pure A).


# ============================================================================
# CASE STUDY 3 — DESIGNING THE QUERY LAYER FOR AN ANALYTICS TEAM THAT
# NEEDS TO JOIN DATA ACROSS THE DATA LAKE AND SEVERAL OPERATIONAL
# DATABASES
# ============================================================================
#
# SETUP: analysts routinely need to join Iceberg tables in the data lake
# (L06) against data still living in operational Postgres/MySQL
# databases, currently done via slow, manual data exports.
#
# ------------------------------------------------------------------------
# APPROACH A: ETL all operational data into the lake first (Data
# Engineering Notes), then analysts query only the lake
# ------------------------------------------------------------------------
#   WHY VALID: consolidates all analytical querying into ONE system
#   (the lake), avoiding the need for a federated query engine at all --
#   simpler mental model, and the lake's storage/query characteristics
#   (columnar, optimized for analytics) are generally better suited to
#   analytical workloads than querying live operational databases
#   directly would be anyway.
#   COST: introduces real latency between when data changes in the
#   operational database and when it's reflected in the lake (an ETL
#   pipeline lag) -- for analysis genuinely needing NEAR-REAL-TIME
#   operational data, this staleness is a real limitation, and building/
#   maintaining ETL pipelines for every operational data source the
#   analytics team might ever need is real, ongoing engineering
#   investment.
#
# ------------------------------------------------------------------------
# APPROACH B: Trino as a federated query engine (L05, L07), querying
# the lake AND the operational databases directly, live, without
# pre-copying data
# ------------------------------------------------------------------------
#   WHY VALID: per L05/L07, Trino's connector architecture is
#   specifically designed for exactly this -- federated queries joining
#   across genuinely different underlying systems (Iceberg tables,
#   Postgres, MySQL) in a single SQL query, with no ETL lag since it
#   queries the LIVE operational databases directly.
#   COST: per L05/L07, federated queries against LIVE operational
#   databases put real query load directly on those databases --
#   analysts running large ad hoc queries can compete for resources with
#   the operational database's actual production workload, a real
#   risk requiring careful resource governance (e.g. read replicas
#   dedicated to analytical query load, not the primary operational
#   database) to avoid impacting production systems.
#
# ------------------------------------------------------------------------
# APPROACH C: A hybrid -- Trino federation (B) for AD HOC, exploratory
# analyst queries, but STILL maintain an ETL pipeline (A) for any
# report/dashboard that runs FREQUENTLY or at high query volume,
# materializing those specific results into the lake rather than
# re-querying operational databases live every time
# ------------------------------------------------------------------------
#   WHY VALID: matches each query PATTERN to the approach best suited to
#   it -- ad hoc, low-frequency exploratory queries get B's flexibility
#   and freshness without needing dedicated ETL pipelines built for
#   every possible question in advance; frequently-run, predictable
#   queries get A's benefit of not repeatedly hitting operational
#   databases live, protecting them from a recurring, foreseeable load
#   source.
#   COST: requires ongoing judgment about which queries/dashboards have
#   crossed the threshold from "occasional ad hoc" to "frequent enough
#   to warrant a dedicated ETL pipeline" -- a real, recurring
#   operational decision, and maintaining both a federation layer AND
#   ETL pipelines is more total infrastructure than either approach
#   alone.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Data freshness | Operational-database load risk | Engineering investment |
#   |----------|--------------------|--------------------------------------|-------------------------------|
#   | A: ETL everything first | Stale (pipeline lag) | None (queries the lake, not operational DBs) | High (many pipelines) |
#   | B: Trino federation everywhere | Live | Real, needs governance | Lower (one query layer) |
#   | C: federation for ad hoc, ETL for frequent | Mixed, appropriately | Managed (frequent queries offloaded) | Medium |
#   C is the strongest answer for a team with a GENUINE mix of ad hoc
#   exploration and recurring reporting needs (the realistic common
#   case); B alone is reasonable for a smaller team/dataset where
#   operational-database load risk is easily managed; A alone is
#   defensible specifically when NO analytical need is latency-
#   sensitive enough to justify federation's added complexity.


# ============================================================================
# CASE STUDY 4 — TRACKING LINEAGE FOR A FEATURE SUSPECTED OF CONTAINING
# PII
# ============================================================================
#
# SETUP: a compliance review flags that a feature (`avg_transaction_
# location_precision`) MIGHT be derived, indirectly, from PII (precise
# geolocation data) -- the team needs to determine which MODELS depend
# on this feature and assess the actual exposure.
#
# ------------------------------------------------------------------------
# APPROACH A: Manually trace the feature's derivation and usage by
# searching code/pipeline definitions
# ------------------------------------------------------------------------
#   WHY VALID: requires no additional tooling investment -- if the
#   organization has relatively few features/models and reasonably
#   well-organized code, a manual grep/code-review-based trace can
#   genuinely be completed in a reasonable amount of time.
#   COST: per L09's lineage discussion, manual tracing is fundamentally
#   NOT SCALABLE and prone to missing indirect/transitive dependencies
#   -- a feature derived from this one, used by a model the compliance
#   team doesn't think to check, is exactly the kind of dependency a
#   manual search is likely to miss, a real, serious risk for a
#   compliance-driven investigation specifically, where missing a
#   dependency has real regulatory consequences.
#
# ------------------------------------------------------------------------
# APPROACH B: Query an automated feature/model LINEAGE GRAPH (L09) --
# if the organization already maintains one, directly query "which
# models depend on this feature, transitively"
# ------------------------------------------------------------------------
#   WHY VALID: per L09, this is EXACTLY the use case lineage graphs are
#   built for -- a proper lineage graph captures TRANSITIVE dependencies
#   automatically (a model depending on a feature derived FROM this
#   feature is captured, not just direct dependents), giving a
#   comprehensive, auditable answer in a fraction of the time a manual
#   trace would take, with much lower risk of missing something.
#   COST: per L09, this only works if the organization ALREADY invested
#   in building and maintaining accurate lineage tracking BEFORE this
#   compliance question arose -- if no lineage graph exists (or an
#   existing one is incomplete/stale), this approach isn't actually
#   available as a fast option right now, and building one FROM SCRATCH
#   specifically to answer this one urgent question is a large, not-
#   fast undertaking.
#
# ------------------------------------------------------------------------
# APPROACH C: Treat this incident as the forcing function to invest in
# lineage tooling GOING FORWARD (build/adopt L09's lineage-graph
# infrastructure now), while handling THIS SPECIFIC urgent compliance
# question via the best available manual/partial-automated tracing (A,
# supplemented by whatever partial tooling exists)
# ------------------------------------------------------------------------
#   WHY VALID: acknowledges the honest reality that B may not be
#   available YET (per its own cost above) while still directly
#   addressing the ROOT gap this incident revealed (no systematic
#   lineage tracking existed at all) -- pragmatic for the immediate
#   question, forward-looking for preventing the NEXT version of this
#   same problem.
#   COST: doesn't fully solve THIS incident's urgent question with B's
#   speed/completeness -- the immediate compliance investigation still
#   carries A's manual-tracing risk of missing a transitive dependency,
#   an honest, real limitation this approach doesn't eliminate, only
#   partially mitigates while building toward a better future state.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Completeness for THIS urgent question | Speed | Prevents future recurrence |
#   |----------|---------------------------------------------|-----------|-----------------------------------|
#   | A: manual trace | Lower (misses transitive deps) | Medium | No |
#   | B: query existing lineage graph | Highest | Fastest | N/A (already solved) |
#   | C: manual trace now + invest in lineage tooling going forward | Same as A, for now | Medium | Yes |
#   If B is genuinely available (lineage tooling already exists), it's
#   unambiguously the right answer; if it doesn't exist yet (the more
#   common real situation), C is the honest, responsible answer -- doing
#   the best available manual investigation now while treating the gap
#   this incident revealed as a genuine priority to fix, not just
#   surviving this one incident and moving on unchanged.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
