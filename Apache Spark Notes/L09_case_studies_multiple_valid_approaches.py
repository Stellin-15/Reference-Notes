"""
WHAT: Four realistic large-scale data-processing problems, each solved
      with THREE genuinely different, individually defensible Spark
      approaches drawn from L01-L08 -- with an explicit comparison table
      and reasoning for why each answer is valid under different
      constraints.
WHY:  "Should this be a broadcast join or a shuffle join," "RDD or
      DataFrame," "batch or streaming" are all questions L01-L08 gave you
      real tools for, not universal answers to -- this lesson is about
      the decision process under real data-volume and latency
      constraints.
LEVEL: Capstone -- read after L01-L08.

This file is reference material, not meant to run top-to-bottom against
a live cluster. Before checking each comparison table, try reconstructing
it yourself using only L01-L08's concepts.
"""

# ============================================================================
# CASE STUDY 1 — JOINING A 500GB FACT TABLE AGAINST A 50MB DIMENSION
# TABLE
# ============================================================================
#
# SETUP: a nightly job joins a large `transactions` table (500GB) against
# a small `merchant_categories` lookup table (50MB) to enrich each
# transaction with a category label.
#
# ------------------------------------------------------------------------
# APPROACH A: A default DataFrame join (`transactions.join(categories,
# "merchant_id")`), letting Catalyst decide the join strategy (L03, L05)
# ------------------------------------------------------------------------
#   WHY VALID: per L05, Spark's Catalyst optimizer and Adaptive Query
#   Execution (AQE) are specifically designed to detect exactly this
#   size asymmetry AT RUNTIME and automatically choose a broadcast join
#   without any manual hint needed -- for a well-configured, reasonably
#   modern Spark version, "just write the natural join" often already
#   produces the efficient plan.
#   COST: relies on AQE's broadcast-threshold configuration being large
#   enough to cover the 50MB table (the default threshold, `spark.sql.
#   autoBroadcastJoinThreshold`, is typically 10MB by default in many
#   deployments) -- if the cluster's configured threshold is smaller
#   than the actual dimension table size, Catalyst may silently choose
#   an expensive shuffle join instead, and this failure is EASY to miss
#   without explicitly checking the query plan (L05's `EXPLAIN`
#   discussion).
#
# ------------------------------------------------------------------------
# APPROACH B: An explicit broadcast hint (`transactions.join(broadcast
# (categories), "merchant_id")`, L05)
# ------------------------------------------------------------------------
#   WHY VALID: removes any dependence on the broadcast-threshold
#   configuration being correctly set -- the hint directly, explicitly
#   tells Catalyst "broadcast this side, I know it's small," a
#   deterministic, self-documenting choice that doesn't silently
#   degrade if a cluster-wide config default changes later.
#   COST: if the "small" table unexpectedly GROWS over time (a
#   dimension table that was 50MB last year could genuinely grow to
#   several GB as the business adds more categories/merchants), the
#   hint keeps forcing a broadcast join regardless, potentially causing
#   OUT-OF-MEMORY errors on executors once the table is no longer
#   genuinely small enough to broadcast safely -- a hardcoded hint can
#   become actively wrong as data evolves, unlike A's adaptive approach.
#
# ------------------------------------------------------------------------
# APPROACH C: Pre-aggregate/cache the dimension table as a broadcast
# variable ONCE at the start of a longer pipeline (not per-job), reused
# across multiple downstream jobs that all need the same lookup (L02's
# broadcast-variable pattern)
# ------------------------------------------------------------------------
#   WHY VALID: if MULTIPLE jobs in a pipeline (not just this one nightly
#   join) repeatedly need the same small lookup table, broadcasting it
#   ONCE and reusing that broadcast variable across jobs avoids re-
#   shipping/re-broadcasting the same 50MB to every executor for EVERY
#   separate job that needs it -- a genuine efficiency win specifically
#   in a multi-job pipeline context this single-join case study doesn't
#   fully capture on its own.
#   COST: only pays off when there genuinely ARE multiple jobs reusing
#   the same lookup data -- for a single, standalone nightly join (as
#   literally described in this case study's setup), this adds
#   unnecessary pipeline-orchestration complexity relative to B's
#   simpler, self-contained per-job hint, solving a problem this
#   specific setup doesn't actually have.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Correctness robustness | Explicitness | Fits multi-job reuse | Risk if dimension table grows |
#   |----------|------------------------------|-------------------|----------------------------|--------------------------------------|
#   | A: default join, trust AQE | Config-dependent | Low | No | Silent shuffle-join degradation |
#   | B: explicit broadcast hint | High (deterministic) | High | No | OOM risk if table grows unexpectedly |
#   | C: shared broadcast across jobs | High | Medium | Yes | Same growth risk as B |
#   For a single standalone job, B is the clearest, most maintainable
#   default; always pair it with a periodic sanity check on the
#   dimension table's actual size (a simple row-count/size assertion) to
#   catch the "it grew and broadcast is now wrong" risk before it causes
#   an OOM in production.


# ============================================================================
# CASE STUDY 2 — HANDLING SEVERE DATA SKEW IN A GROUP-BY AGGREGATION
# ============================================================================
#
# SETUP: aggregating total spend per customer_id, where a small number of
# "customer" IDs represent aggregated corporate/enterprise accounts with
# orders of magnitude more transactions than typical individual
# customers -- a classic skewed-key scenario.
#
# ------------------------------------------------------------------------
# APPROACH A: A plain `groupBy("customer_id").sum("amount")`, no skew
# handling (L03, L05)
# ------------------------------------------------------------------------
#   WHY VALID: the simplest possible code, and for MOST data
#   distributions (no severe skew), this performs perfectly well -- not
#   every groupBy needs special-case skew handling, and reaching for
#   complexity preemptively without confirmed skew is itself a mistake.
#   COST: per L05's skew discussion, with genuinely severe skew, the
#   partition(s) handling the enterprise-account keys become massively
#   larger than other partitions -- one or a few tasks take dramatically
#   longer than the rest, meaning the JOB's total wall-clock time is
#   effectively bottlenecked by the single slowest, most-skewed
#   partition, wasting most of the cluster's parallelism.
#
# ------------------------------------------------------------------------
# APPROACH B: Salting the skewed keys -- append a random suffix to the
# `customer_id` for the known high-volume keys specifically, aggregate
# in two phases (partial aggregation per salted key, then a final
# aggregation collapsing the salt back off) (L05)
# ------------------------------------------------------------------------
#   WHY VALID: directly breaks up the skewed key's data across MULTIPLE
#   partitions (each salted variant lands in a different partition),
#   restoring parallelism for the aggregation of that key's data
#   specifically, then a cheap final rollup combines the salted partial
#   sums back into the true per-customer total.
#   COST: genuinely more complex code (two aggregation phases, salt-key
#   generation and removal logic) and requires KNOWING in advance which
#   keys are skewed (or computing that via an extra pass over the data)
#   -- salting EVERY key indiscriminately, rather than just the known-
#   skewed ones, adds unnecessary overhead to the (majority) non-skewed
#   keys that didn't need it.
#
# ------------------------------------------------------------------------
# APPROACH C: Enable Adaptive Query Execution's skew-join/skew-
# partition handling (`spark.sql.adaptive.skewJoin.enabled`, related AQE
# settings, L05)
# ------------------------------------------------------------------------
#   WHY VALID: per L05, modern Spark's AQE can automatically DETECT
#   skewed partitions at runtime (based on actual observed partition
#   sizes, not a static guess) and automatically split them into smaller
#   sub-partitions -- getting much of B's benefit with ZERO manual
#   salting code, since Spark handles the detection and splitting
#   itself.
#   COST: requires a sufficiently modern Spark version with AQE properly
#   enabled and tuned (the relevant thresholds/configs need reasonable
#   values for the actual skew severity present) -- and AQE's automatic
#   handling, while often very effective, is a more opaque mechanism
#   than B's fully-manual, fully-inspectable salting logic; when it
#   doesn't fully resolve a particularly severe or unusual skew pattern,
#   debugging WHY requires understanding AQE's internals rather than
#   just reading hand-written salting code.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Handles severe skew? | Code complexity | Requires pre-identifying skewed keys | Debuggability |
#   |----------|----------------------------|----------------------|-------------------------------------------|--------------------|
#   | A: plain groupBy | No | Lowest | N/A | High (simple code) |
#   | B: manual salting | Yes | Highest | Yes | High (fully manual) |
#   | C: AQE skew handling | Usually yes | Lowest (just config) | No | Lower (more opaque) |
#   C is the right first thing to try on a modern Spark version --
#   enable AQE skew handling and re-measure before reaching for B's
#   manual complexity; B remains the right fallback for skew patterns
#   severe or unusual enough that AQE's automatic handling doesn't fully
#   resolve, confirmed via actual measurement, not assumption.


# ============================================================================
# CASE STUDY 3 — CHOOSING BETWEEN RDDS AND DATAFRAMES FOR A CUSTOM,
# NON-STANDARD TRANSFORMATION
# ============================================================================
#
# SETUP: a transformation needs to apply a complex, stateful, per-record
# Python function (not expressible as a simple column expression) to
# every row of a large dataset.
#
# ------------------------------------------------------------------------
# APPROACH A: An RDD `.map()` with the custom Python function (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, RDDs give full, unrestricted access to arbitrary
#   Python logic per record -- if the transformation genuinely can't be
#   expressed as DataFrame column operations or a Pandas UDF (deeply
#   stateful, branching, calling external non-vectorizable logic), RDDs
#   are the most DIRECTLY expressive tool for exactly this kind of
#   arbitrary per-record computation.
#   COST: per L03/L05, RDDs bypass Catalyst's optimizer and Tungsten's
#   memory-management optimizations entirely -- no predicate pushdown,
#   no columnar memory layout benefits, generally meaningfully slower
#   than an equivalent DataFrame-based operation for anything Catalyst
#   COULD have optimized, a real, measurable performance cost paid for
#   RDD's flexibility.
#
# ------------------------------------------------------------------------
# APPROACH B: A DataFrame with a standard (row-at-a-time) Python UDF
# wrapping the custom function (L03)
# ------------------------------------------------------------------------
#   WHY VALID: keeps the data in DataFrame form (retaining Catalyst's
#   optimization for any OTHER operations in the same pipeline before/
#   after the UDF step) while still allowing arbitrary Python logic for
#   the specific transformation that needs it -- a middle ground between
#   A's full flexibility and pure DataFrame operations' optimization
#   benefits.
#   COST: per L03, standard Python UDFs still incur real per-row
#   serialization overhead crossing the JVM-to-Python boundary (Spark's
#   JVM engine calling out to a Python process for each row) -- this
#   overhead is a well-documented, genuine performance cost, and
#   Catalyst can't optimize THROUGH an opaque UDF boundary, limiting
#   optimization even for the surrounding DataFrame operations.
#
# ------------------------------------------------------------------------
# APPROACH C: A Pandas UDF (vectorized UDF, L03) if the custom logic can
# be expressed as an operation over a PANDAS SERIES/DATAFRAME (batches
# of rows at once) rather than one row at a time
# ------------------------------------------------------------------------
#   WHY VALID: per L03, Pandas UDFs process data in BATCHES (using Arrow
#   for efficient JVM-to-Python data transfer) rather than row-by-row,
#   dramatically reducing the serialization overhead approach B pays --
#   often within a small constant factor of native DataFrame operations'
#   performance while still allowing genuinely custom Python/Pandas/
#   NumPy logic.
#   COST: only applies if the custom logic can actually be expressed as
#   a vectorized operation over a batch (a Pandas Series/DataFrame) --
#   if the transformation is INHERENTLY row-at-a-time with complex
#   branching that doesn't vectorize cleanly (the literal premise of
#   this case study's "complex, stateful, per-record function"), forcing
#   it into Pandas UDF form may not be possible without genuinely
#   awkward, hard-to-read code, if it's possible at all.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Performance | Flexibility for arbitrary per-record logic | Catalyst optimization retained |
#   |----------|-----------------|---------------------------------------------------|--------------------------------------|
#   | A: RDD .map() | Worst | Highest | None |
#   | B: row-at-a-time Python UDF | Medium | High | Partial (breaks at UDF boundary) |
#   | C: Pandas UDF (vectorized) | Best (if applicable) | Medium (needs vectorizable logic) | Partial (breaks at UDF boundary) |
#   Try C first if the logic can plausibly be expressed as a batch/
#   vectorized operation; fall back to B if it genuinely can't but still
#   fits a DataFrame pipeline; reach for A only when the logic needs
#   RDD-level flexibility (e.g. genuinely arbitrary, deeply stateful
#   iteration) that even a Pandas UDF can't accommodate.


# ============================================================================
# CASE STUDY 4 — DECIDING BETWEEN BATCH AND STRUCTURED STREAMING FOR A
# NEAR-REAL-TIME REPORTING PIPELINE
# ============================================================================
#
# SETUP: a reporting dashboard currently refreshes from an hourly batch
# job; the business wants "closer to real-time" updates, but the exact
# latency requirement (is 5 minutes fine? does it need to be seconds?)
# is genuinely still being clarified with stakeholders.
#
# ------------------------------------------------------------------------
# APPROACH A: Reduce the batch job's SCHEDULE interval (hourly -> every
# 5 minutes), no architectural change (L01, L08)
# ------------------------------------------------------------------------
#   WHY VALID: the lowest-effort, lowest-risk change -- reuses the
#   EXACT same batch job logic already built, tested, and understood,
#   just triggered more frequently; if 5-minute latency genuinely
#   satisfies the (still-being-clarified) business requirement, this is
#   the simplest possible answer with no new architecture to learn or
#   maintain.
#   COST: batch jobs have real per-run OVERHEAD (Spark session startup,
#   full or incremental data scan planning) that doesn't shrink just
#   because the job runs more often -- running a job every 5 minutes
#   that was designed and tuned for hourly execution can mean the job's
#   overhead becomes a LARGER fraction of each run's total time, and if
#   the requirement later tightens to "seconds," this approach hits a
#   hard architectural ceiling no amount of schedule-tuning can cross.
#
# ------------------------------------------------------------------------
# APPROACH B: Migrate to Spark Structured Streaming (L06) with a
# micro-batch trigger interval matched to the actual latency requirement
# ------------------------------------------------------------------------
#   WHY VALID: per L06, Structured Streaming is purpose-built for
#   exactly this "continuously process new data with a defined latency
#   target" pattern -- a genuinely more natural architectural fit than
#   repeatedly re-running a batch job, with built-in support for
#   watermarks/stateful aggregations (L06) that a batch job would need
#   to hand-reconstruct from scratch (e.g. correctly handling late-
#   arriving data across artificial hourly/5-minute batch boundaries).
#   COST: a genuine architectural migration -- streaming introduces new
#   operational concerns (checkpoint management, exactly-once/at-least-
#   once semantics reasoning, L06) the team needs competence in, real
#   effort that's not justified if the ACTUAL, once-clarified business
#   requirement turns out to be something batch-with-a-shorter-schedule
#   (approach A) could have satisfied all along.
#
# ------------------------------------------------------------------------
# APPROACH C: Delay the architecture decision -- first instrument the
# CURRENT hourly batch pipeline to measure its actual data-freshness lag
# and confirm the PRECISE business requirement with stakeholders before
# committing to either A or B
# ------------------------------------------------------------------------
#   WHY VALID: per this case study's own explicit setup ("the exact
#   latency requirement is genuinely still being clarified"), committing
#   engineering effort to EITHER A or B before that clarification is
#   premature -- getting a precise, numeric latency requirement first is
#   the correct, if less immediately gratifying, next step, avoiding
#   wasted effort building toward the wrong target.
#   COST: doesn't ship any improvement yet -- purely a process/
#   sequencing recommendation, and if stakeholders take a long time to
#   clarify requirements, this approach alone leaves the actual
#   dashboard staleness problem unaddressed in the meantime, a real,
#   if often underweighted, cost of "wait for more information" as a
#   standalone answer.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Effort | Fits a loose ("few minutes") requirement | Fits a tight ("seconds") requirement | Risk of solving the wrong problem |
#   |----------|------------|------------------------------------------------|--------------------------------------------|------------------------------------------|
#   | A: shorter batch schedule | Lowest | Yes | No (hard ceiling) | Low |
#   | B: Structured Streaming | Highest | Yes (over-engineered if requirement is loose) | Yes | High, if requirement was actually loose |
#   | C: clarify requirement first | Lowest (but delays any fix) | N/A | N/A | Lowest (informs A vs B correctly) |
#   The genuinely correct sequencing here is C first (this case study's
#   own setup all but states this directly), THEN A if the clarified
#   requirement is loose, or B specifically once it's confirmed tight
#   enough that A's architectural ceiling would be a real blocker --
#   committing to B before that clarification risks real, avoidable
#   over-engineering.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
