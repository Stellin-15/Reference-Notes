"""
WHAT: Four realistic data-platform problems, each solved with THREE
      genuinely different, individually defensible approaches drawn from
      L01-L12 -- with an explicit comparison table and reasoning for why
      each answer is valid under different constraints.
WHY:  "Airflow or Databricks Workflows," "ETL or ELT," "how to handle
      schema drift" are all questions L01-L12 gave you real tools for,
      not one universal answer -- this lesson is about the decision
      process under real organizational and data-volume constraints.
LEVEL: Capstone -- read after L01-L12.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L12's concepts.
"""

# ============================================================================
# CASE STUDY 1 — ORCHESTRATING A DATA PIPELINE FOR A TEAM WITH NO
# EXISTING ORCHESTRATION TOOLING
# ============================================================================
#
# SETUP: a small data team (3 engineers) needs to orchestrate ~15
# interdependent daily jobs (extract, transform, load, quality checks)
# and currently uses a tangle of cron jobs with no dependency management.
#
# ------------------------------------------------------------------------
# APPROACH A: Apache Airflow (L03, L04), self-hosted
# ------------------------------------------------------------------------
#   WHY VALID: per L03-L04, Airflow is the most widely-adopted, feature-
#   rich open-source orchestrator -- extensive operator ecosystem,
#   strong community support, and TaskFlow API (L04) makes DAG
#   authoring reasonably ergonomic; a defensible default specifically
#   because of how much prior art/documentation/community knowledge
#   exists to lean on.
#   COST: self-hosted Airflow is real, ongoing OPERATIONAL burden for a
#   3-person team -- the scheduler, webserver, metadata database, and
#   worker infrastructure all need to be deployed, monitored, and kept
#   running, a genuine distraction from actual data-pipeline work for a
#   team this small, unless they already have platform/DevOps support.
#
# ------------------------------------------------------------------------
# APPROACH B: A managed orchestration service (e.g. managed Airflow via
# a cloud provider, or Databricks Workflows if already on Databricks,
# L05-L06, L10)
# ------------------------------------------------------------------------
#   WHY VALID: per L10's orchestration-comparison discussion, a managed
#   service eliminates approach A's self-hosting operational burden
#   entirely -- the team gets orchestration capability without needing
#   to run the orchestrator's own infrastructure, letting a small team
#   focus on pipeline logic rather than platform operations.
#   COST: real, ongoing monetary cost that scales with usage, and (per
#   L10) ties the team's orchestration choice to whichever platform
#   they're managed within -- Databricks Workflows specifically is a
#   strong choice ONLY if the team's actual compute is already on
#   Databricks; adopting it purely for orchestration while running
#   compute elsewhere adds an awkward cross-platform dependency instead
#   of solving the actual problem.
#
# ------------------------------------------------------------------------
# APPROACH C: A lighter-weight, code-first orchestrator (Dagster or
# Prefect, mentioned in L10's comparison) rather than Airflow
# ------------------------------------------------------------------------
#   WHY VALID: per L10, these tools are frequently cited as having a
#   gentler learning curve and more Pythonic, testable pipeline
#   definitions than Airflow's DAG model -- for a SMALL team without
#   deep existing Airflow expertise, this lower ramp-up cost is a real,
#   relevant advantage, and self-hosting these tools is often reported
#   as somewhat lighter-weight than a full Airflow deployment.
#   COST: per L10, these tools have a smaller community, less extensive
#   third-party integration ecosystem, and less institutional knowledge
#   available (fewer Stack Overflow answers, less hiring-market
#   familiarity) than Airflow -- a real risk if the team later needs to
#   hire, or needs to integrate with an unusual system that has an
#   Airflow operator but no equivalent for the chosen alternative.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Operational burden | Learning curve | Ecosystem maturity | Cost model |
#   |----------|--------------------------|---------------------|---------------------------|----------------|
#   | A: self-hosted Airflow | Highest | Medium | Highest | Infrastructure cost |
#   | B: managed orchestration | Lowest | Depends on platform | Depends on platform | Service cost |
#   | C: Dagster/Prefect | Medium (lighter self-hosting) | Lowest | Lower | Infrastructure cost (or managed tier) |
#   For a 3-person team with no dedicated platform support, B (if a
#   managed option fits their existing stack) or C (if avoiding vendor
#   lock-in matters more) are both stronger defaults than A -- A becomes
#   the right choice specifically once the team is large enough to
#   absorb self-hosting overhead or has specific integration needs only
#   Airflow's mature ecosystem covers well.


# ============================================================================
# CASE STUDY 2 — HANDLING SCHEMA DRIFT FROM AN UPSTREAM SOURCE SYSTEM
# ============================================================================
#
# SETUP: a pipeline ingests data from an upstream operational database
# the data team doesn't control; upstream engineers occasionally add,
# rename, or change the type of columns without notifying the data team,
# which has broken the pipeline multiple times.
#
# ------------------------------------------------------------------------
# APPROACH A: A STRICT schema contract -- the pipeline explicitly
# defines expected columns/types and FAILS LOUDLY (halts, alerts) on any
# mismatch (L01, L11)
# ------------------------------------------------------------------------
#   WHY VALID: per L11's data-quality discussion, failing loudly and
#   immediately is far better than silently processing malformed/
#   unexpected data and producing corrupted downstream results that
#   might not be noticed for days -- a strict contract makes the
#   ACTUAL problem (upstream changed without telling anyone) immediately
#   visible rather than hidden inside subtly-wrong output.
#   COST: EVERY upstream schema change, even a harmless additive one
#   (a new, unrelated column added), breaks the pipeline and requires
#   an engineer to intervene -- for a source system that changes
#   moderately often, this creates real, recurring interruption/
#   toil, exactly the kind of manual intervention this domain's data-
#   quality tooling (L11) is meant to reduce, not just relocate.
#
# ------------------------------------------------------------------------
# APPROACH B: A permissive, schema-evolution-tolerant ingestion using
# Delta Lake's schema evolution features (`mergeSchema`, L07) --
# automatically accommodate ADDITIVE changes (new columns), still fail
# on genuinely breaking changes (type changes, renames)
# ------------------------------------------------------------------------
#   WHY VALID: per L07, this distinguishes BENIGN schema changes (a new
#   column that doesn't affect existing logic) from BREAKING ones (a
#   type change that could silently corrupt calculations, or a rename
#   that could silently produce nulls where data used to exist) --
#   absorbing the harmless case automatically while still surfacing the
#   genuinely dangerous case, directly reducing A's "every change breaks
#   things" toil while retaining its "dangerous changes get caught"
#   safety property.
#   COST: "additive vs. breaking" isn't always a clean, automatic
#   distinction -- a new column could ALSO represent a meaningful
#   business change worth a human noticing even if it's technically
#   additive/non-breaking (e.g. a new column signals a new upstream
#   feature the data team should probably be modeling downstream) --
#   automatic tolerance can mean a genuinely relevant change goes
#   unnoticed simply because it happened not to break anything
#   mechanically.
#
# ------------------------------------------------------------------------
# APPROACH C: Establish an actual data CONTRACT/agreement with the
# upstream team (a documented, versioned schema, with a notification
# process for changes) -- an organizational fix, not a purely technical
# one (L11's broader data-quality-culture point)
# ------------------------------------------------------------------------
#   WHY VALID: addresses the ROOT CAUSE (upstream changes without
#   communication) rather than building increasingly sophisticated
#   downstream tooling to cope with a communication failure -- if
#   achievable, this is the most durable fix, and per L11's broader
#   point that data quality is as much an organizational practice as a
#   technical one, this is a legitimate, often under-weighted answer.
#   COST: requires organizational buy-in and cooperation from a team
#   (upstream engineering) that the data team may have limited leverage
#   over -- genuinely not always achievable depending on company
#   structure/politics, and even with a contract in place, SOME
#   technical safety net (A or B) is still warranted for the inevitable
#   accidental violation of that contract.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Toil from benign changes | Catches dangerous changes | Addresses root cause | Achievability |
#   |----------|--------------------------------|---------------------------------|----------------------------|--------------------|
#   | A: strict, fail-loud contract | High | Yes | No | Fully within data team's control |
#   | B: Delta schema evolution (additive-tolerant) | Low | Yes (for breaking changes) | No | Fully within data team's control |
#   | C: organizational data contract | Depends on adherence | Depends on adherence | Yes | Requires upstream team cooperation |
#   The strongest real answer combines B (a technical safety net that
#   reduces toil while still catching dangerous changes) with C pursued
#   in parallel (the organizational fix, when achievable) -- B alone
#   without C means the data team keeps reactively coping with
#   upstream's process gap indefinitely; C alone without B leaves no
#   safety net for the inevitable contract violation.


# ============================================================================
# CASE STUDY 3 — DECIDING BETWEEN ETL AND ELT FOR A NEW ANALYTICS
# PIPELINE
# ============================================================================
#
# SETUP: a new pipeline needs to load data from several operational
# systems into a warehouse for BI/analytics use, and the team is
# deciding whether to transform data BEFORE loading (ETL) or load raw
# data and transform inside the warehouse (ELT).
#
# ------------------------------------------------------------------------
# APPROACH A: ETL -- transform in a dedicated processing layer (e.g.
# Spark or Airflow-orchestrated Python) BEFORE loading into the
# warehouse (L01)
# ------------------------------------------------------------------------
#   WHY VALID: per L01, transforming before loading means the warehouse
#   only ever holds clean, business-ready data -- simpler warehouse-side
#   modeling, and sensitive data can be filtered/masked/aggregated
#   BEFORE it ever lands in the warehouse, a real advantage if some
#   source data is sensitive and the warehouse has broader access than
#   is appropriate for raw source data.
#   COST: per L01, transformation logic lives OUTSIDE the warehouse, in
#   a separate processing system that must be operated, and changing a
#   transformation requires re-running the ENTIRE extract-transform-load
#   pipeline (or a substantial part of it) rather than just re-running a
#   warehouse-side query -- a real iteration-speed cost for analysts
#   who want to experiment with different transformation logic.
#
# ------------------------------------------------------------------------
# APPROACH B: ELT -- load raw data directly into the warehouse (e.g.
# Snowflake, L07-L08), transform using warehouse-native SQL/Snowpark
# afterward
# ------------------------------------------------------------------------
#   WHY VALID: per L01/L07-L08, modern cloud warehouses have enough
#   compute power that transformation-in-warehouse is now routinely
#   practical -- raw data is preserved (useful if a transformation bug
#   is later discovered and needs to be re-run against the ORIGINAL
#   data, not a lossy pre-transformed version), and analysts can iterate
#   on transformation SQL directly against warehouse data without
#   needing a separate processing pipeline redeploy for each change.
#   COST: sensitive raw data now lands in the warehouse BEFORE any
#   filtering/masking -- a real access-control/compliance consideration
#   if the warehouse has broader user access than the raw source systems
#   did, requiring the warehouse's OWN access controls (row/column-level
#   security) to correctly restrict access to the raw layer, rather than
#   relying on "the sensitive data was already removed before it got
#   here."
#
# ------------------------------------------------------------------------
# APPROACH C: A hybrid — load raw data into the warehouse (ELT-style),
# but IMMEDIATELY apply masking/filtering transformations to sensitive
# fields as the FIRST warehouse-side step, before any other
# transformation or analyst access, using a layered (e.g. medallion,
# L12) architecture
# ------------------------------------------------------------------------
#   WHY VALID: per L12's medallion-architecture discussion, this
#   captures ELT's iteration-speed and raw-data-preservation benefits
#   (B) while directly addressing B's sensitive-data-exposure concern --
#   a "bronze" (raw, tightly access-restricted) layer holds the truly
#   raw data, with sensitive-field handling applied immediately in the
#   transition to a "silver" layer that's what most analysts actually
#   query, giving both raw-data preservation AND appropriate access
#   boundaries.
#   COST: requires actually DESIGNING and maintaining the layered
#   architecture (L12) correctly, including genuinely restricting
#   bronze-layer access to only those who need it (a real, ongoing
#   access-control discipline, not just a naming convention) -- more
#   architectural upfront design than either pure A or pure B, though
#   this is largely the same design effort L12's medallion pattern
#   already recommends as a general best practice regardless of this
#   specific sensitivity concern.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Iteration speed for transformations | Raw data preserved? | Sensitive-data exposure risk | Architecture complexity |
#   |----------|-------------------------------------------|---------------------------|------------------------------------|--------------------------------|
#   | A: ETL | Slowest | No (only transformed data kept) | Lowest (filtered before landing) | Lowest |
#   | B: pure ELT | Fastest | Yes | Real (raw sensitive data in warehouse) | Low |
#   | C: ELT + medallion layering | Fast (for silver-layer work) | Yes (in restricted bronze layer) | Managed (via bronze access control) | Highest |
#   For any pipeline touching genuinely sensitive source data, C is the
#   strongest modern answer; pure B is reasonable when the source data
#   isn't meaningfully sensitive and raw-data preservation/iteration
#   speed dominate; pure A remains defensible when the transformation
#   logic itself is complex enough to be more naturally expressed in
#   Spark/Python than warehouse SQL.


# ============================================================================
# CASE STUDY 4 — DETECTING AND RESPONDING TO A SILENT DATA-QUALITY
# REGRESSION (NO PIPELINE FAILURE, JUST WRONG NUMBERS)
# ============================================================================
#
# SETUP: a pipeline runs successfully (no errors, no failed tasks) every
# day, but a subtle upstream bug has been silently producing systematically
# wrong values in one column for two weeks before anyone noticed via a
# confused business stakeholder.
#
# ------------------------------------------------------------------------
# APPROACH A: Add explicit data-quality ASSERTIONS to the pipeline (e.g.
# Great Expectations / dbt tests, L11) checking known invariants (value
# ranges, null rates, referential integrity)
# ------------------------------------------------------------------------
#   WHY VALID: per L11, this directly targets EXACTLY this failure mode
#   -- a pipeline that "succeeds" (no exceptions) while producing wrong
#   data is precisely what explicit quality assertions are built to
#   catch, by checking the ACTUAL DATA's properties, not just whether
#   the code ran without crashing.
#   COST: assertions can only catch violations of invariants someone
#   THOUGHT to write a check for -- a genuinely novel failure mode
#   (a subtle miscalculation that still produces "plausible-looking"
#   values within normal ranges) can slip through even a reasonably
#   thorough assertion suite if no one anticipated that specific way
#   the data could go wrong, a real, structural limitation of any
#   assertion-based approach.
#
# ------------------------------------------------------------------------
# APPROACH B: Statistical anomaly detection on pipeline OUTPUT metrics
# over time (e.g. row counts, value distributions, day-over-day
# percentage changes) rather than fixed-threshold assertions (L11)
# ------------------------------------------------------------------------
#   WHY VALID: per L11, this can catch UNANTICIPATED failure modes that
#   fixed assertions miss -- a metric that suddenly deviates
#   significantly from its historical pattern (even if still within
#   some "plausible" absolute range a hand-written assertion might have
#   allowed) gets flagged automatically, without needing someone to have
#   predicted that specific failure mode in advance.
#   COST: statistical anomaly detection needs a genuine HISTORY of
#   normal behavior to compare against (cold-start problem for new
#   pipelines/metrics) and is prone to both false positives (a
#   legitimate, real business change looks like an "anomaly" relative
#   to history) and false negatives (a slow, gradual drift that never
#   looks anomalous DAY-OVER-DAY even though it's cumulatively very
#   wrong by week two) -- exactly the kind of gradual regression this
#   case study describes, which day-over-day anomaly detection can be
#   specifically bad at catching.
#
# ------------------------------------------------------------------------
# APPROACH C: Downstream RECONCILIATION -- periodically cross-check a
# derived/aggregated pipeline output against an independent source of
# truth (e.g. reconcile a computed revenue total against the finance
# team's own independently-maintained figure)
# ------------------------------------------------------------------------
#   WHY VALID: catches errors that are invisible to BOTH A and B if the
#   error is internally self-consistent (passes plausible-range
#   assertions AND doesn't look statistically anomalous relative to its
#   own history, because the bug has been present and consistent since
#   before the monitoring window began) -- an INDEPENDENT source of
#   truth is the only one of the three mechanisms that doesn't rely on
#   properties of the pipeline's own historical output at all.
#   COST: requires an actual independent source of truth to exist and
#   be reliably accessible for reconciliation -- not always available,
#   and building/maintaining the reconciliation process itself is real,
#   additional engineering work; also typically runs on a slower cadence
#   (e.g. weekly/monthly reconciliation) than A/B's per-run checks, so
#   it catches issues LATER even when it does catch them.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Catches anticipated invariant violations | Catches unanticipated anomalies | Catches gradual/long-standing bugs | Detection speed |
#   |----------|-------------------------------------------------|---------------------------------------|-------------------------------------------|----------------------|
#   | A: fixed assertions | Yes | No | No | Fast (per run) |
#   | B: statistical anomaly detection | Partially | Yes | Poor (gradual drift is hard to flag) | Fast (per run) |
#   | C: independent reconciliation | Yes (if the truth source catches it) | Yes | Yes | Slow (periodic) |
#   No single approach alone would have reliably caught THIS case
#   study's specific failure (a two-week-old, self-consistent, subtly-
#   wrong value) -- A and B together form a reasonable automated first
#   line of defense, but C's INDEPENDENT check is what actually catches
#   the class of bug described here, arguing for maintaining at least
#   some periodic reconciliation practice even when automated per-run
#   checks (A, B) are already in place.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
