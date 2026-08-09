"""
WHAT: Four realistic ML-platform/deployment problems, each solved with
      THREE genuinely different, individually defensible approaches
      drawn from L01-L12 -- with an explicit comparison table and
      reasoning for why each answer is valid under different
      constraints.
WHY:  "Shadow deploy or canary," "retrain on a schedule or on drift
      detection," "which serving pattern" are all questions L01-L12 gave
      you real tools for, not one universal answer -- this lesson is
      about the decision process under real risk and operational
      maturity constraints.
LEVEL: Capstone -- read after L01-L12.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L12's concepts.
"""

# ============================================================================
# CASE STUDY 1 — DEPLOYING A NEW MODEL VERSION FOR A HIGH-STAKES
# CREDIT-DECISIONING SYSTEM
# ============================================================================
#
# SETUP: a retrained credit-risk model needs to replace the current
# production model; a bad model directly affects real lending decisions,
# so deployment risk tolerance is very low.
#
# ------------------------------------------------------------------------
# APPROACH A: Canary deployment -- route a small percentage of real
# traffic to the new model, monitor key metrics, gradually increase
# (L07, L12)
# ------------------------------------------------------------------------
#   WHY VALID: per L07/L12, canary deployment catches a genuinely broken
#   new model while it's only affecting a small fraction of real
#   decisions, with automated rollback on metric degradation -- the
#   standard, well-established pattern for exactly this risk profile.
#   COST: the canary's small traffic slice STILL makes real credit
#   decisions on real applicants during the evaluation window -- for a
#   domain this sensitive, even a SMALL number of wrongly-denied (or
#   wrongly-approved) real applicants during canary evaluation is a
#   genuine, real-world cost, not a purely hypothetical risk.
#
# ------------------------------------------------------------------------
# APPROACH B: Shadow deployment (L12) -- the new model scores every
# real request IN PARALLEL with the current production model, but its
# scores are NEVER used for actual decisions, only logged and compared
# ------------------------------------------------------------------------
#   WHY VALID: per L12, this directly solves A's "canary still makes
#   real decisions" problem -- the new model's behavior is fully
#   observed against real production traffic with ZERO risk of it
#   actually affecting any real credit decision, since its output is
#   pure observation, never used for the live decision.
#   COST: per L12, shadow deployment CANNOT observe how the new model's
#   decisions would have affected DOWNSTREAM outcomes (e.g. did an
#   applicant the new model would have approved but the old model denied
#   actually turn out to be a good credit risk) -- it only compares the
#   two models' immediate SCORES, not their real-world consequences,
#   since only the production model's decisions actually happened.
#
# ------------------------------------------------------------------------
# APPROACH C: Champion-challenger with a HELD-OUT historical backtest
# FIRST (evaluate the new model against a large historical dataset with
# KNOWN outcomes, L12), THEN shadow deployment (B), THEN canary (A) --
# all three used in sequence, not as alternatives
# ------------------------------------------------------------------------
#   WHY VALID: per L12's layered-deployment philosophy, combines all
#   three techniques' strengths in the right ORDER -- historical
#   backtesting validates the model against KNOWN real outcomes (closing
#   shadow deployment's "we don't know the downstream consequence" gap)
#   before any live exposure at all, shadow deployment then confirms
#   real-time behavioral consistency with zero live-decision risk, and
#   ONLY THEN does canary introduce the minimum necessary live exposure
#   to validate genuinely live-only factors (real-time latency, live
#   data-pipeline correctness) that neither backtest nor shadow can
#   fully replicate.
#   COST: by far the SLOWEST path to full deployment of the three --
#   each stage takes real time to gather sufficient data/confidence
#   before progressing to the next, a real time-to-value cost that must
#   be weighed against the domain's genuinely high stakes justifying it.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Live-decision risk during evaluation | Validates real-world downstream outcomes | Time to full deployment |
#   |----------|--------------------------------------------|-------------------------------------------------|--------------------------------|
#   | A: canary only | Real (small scale) | Partially (via live outcomes) | Medium |
#   | B: shadow only | None | No (scores only, not outcomes) | Fast (no live risk gating pace) |
#   | C: backtest -> shadow -> canary | Minimal, staged | Yes (backtest specifically) | Slowest |
#   Given this case study's explicit "very low risk tolerance," C is the
#   appropriate answer -- for a domain this consequential, the extra
#   time cost of the full staged approach is a reasonable, deliberate
#   tradeoff, not excessive caution.


# ============================================================================
# CASE STUDY 2 — CHOOSING A RETRAINING TRIGGER STRATEGY
# ============================================================================
#
# SETUP: a recommendation model's performance can degrade as user
# behavior/catalog shifts over time; the team needs to decide when to
# retrain.
#
# ------------------------------------------------------------------------
# APPROACH A: A fixed schedule -- retrain every week, regardless of
# measured performance (L06, L07)
# ------------------------------------------------------------------------
#   WHY VALID: simple, predictable, and easy to operationalize (a
#   standard scheduled pipeline, L04) -- no monitoring infrastructure
#   required to TRIGGER retraining, and for a domain where the
#   underlying data distribution genuinely does drift steadily and
#   predictably, a fixed cadence may line up reasonably well with actual
#   need without requiring more sophisticated drift detection.
#   COST: per L06, this is either WASTEFUL (retraining when nothing has
#   meaningfully drifted, burning real compute cost for no benefit) or
#   INSUFFICIENT (a sudden, unexpected shift happening mid-week leaves
#   the model stale for the rest of that week, un-triggered by the fixed
#   schedule) -- a fixed schedule doesn't actually respond to the real
#   underlying signal (has the data actually drifted) at all.
#
# ------------------------------------------------------------------------
# APPROACH B: Drift-triggered retraining -- monitor input/output
# distributions (PSI, KS tests, L06) and trigger retraining automatically
# when drift crosses a defined threshold
# ------------------------------------------------------------------------
#   WHY VALID: per L06, this directly targets the ACTUAL underlying
#   reason retraining is needed (genuine distributional change) rather
#   than a proxy (elapsed time) -- avoids A's waste (no retraining
#   during stable periods) while responding faster to genuine, sudden
#   shifts than a weekly schedule would.
#   COST: per L06, drift METRICS don't always correlate perfectly with
#   actual PERFORMANCE degradation -- a model can remain accurate
#   despite some input drift (if the drifted region isn't decision-
#   relevant) or can degrade meaningfully WITHOUT triggering a drift
#   alert (if the drift is subtle but happens to affect a
#   disproportionately important decision boundary) -- drift is a
#   useful PROXY signal, not a perfect one.
#
# ------------------------------------------------------------------------
# APPROACH C: Performance-triggered retraining -- directly monitor the
# model's actual live performance metric (e.g. click-through rate
# relative to a baseline/control, via ongoing online experimentation,
# L09) and trigger retraining when that metric itself degrades
# ------------------------------------------------------------------------
#   WHY VALID: per L09, this targets the metric that ACTUALLY matters
#   (real business/model performance) rather than B's proxy signal --
#   directly closes the "drift doesn't always mean degraded performance"
#   gap by measuring the real thing.
#   COST: per L09, GENUINE performance measurement for something like a
#   recommendation system often requires either ground-truth labels that
#   arrive with real delay (did the user actually engage with the
#   recommendation, measurable only after the fact) or a live A/B-test-
#   style comparison against a control -- meaning this signal is
#   inherently SLOWER to detect a problem than B's more immediate
#   distributional drift check, a real detection-latency tradeoff for
#   its improved accuracy.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Responds to genuine need | Detection speed | Compute efficiency |
#   |----------|--------------------------------|----------------------|---------------------------|
#   | A: fixed schedule | No (proxy: elapsed time) | N/A (fixed cadence) | Wasteful or insufficient |
#   | B: drift-triggered | Partially (proxy: distribution) | Fast | Good |
#   | C: performance-triggered | Best (direct measurement) | Slower (waits for outcome signal) | Good |
#   The strongest production answer combines B and C: use B's faster
#   drift signal as an EARLY WARNING/investigation trigger, confirmed
#   or overridden by C's slower-but-more-direct performance signal --
#   using each for what it's genuinely best at rather than picking only
#   one.


# ============================================================================
# CASE STUDY 3 — CHOOSING A MODEL SERVING PATTERN FOR A LATENCY-CRITICAL,
# HIGH-THROUGHPUT INFERENCE WORKLOAD
# ============================================================================
#
# SETUP: an image-classification model needs to serve thousands of
# requests/second with a strict p99 latency budget.
#
# ------------------------------------------------------------------------
# APPROACH A: A simple FastAPI wrapper around the model, one request at
# a time (L05)
# ------------------------------------------------------------------------
#   WHY VALID: per L05, the simplest possible serving setup -- fastest
#   to build, easiest to debug, and for MODEST throughput requirements
#   this can genuinely be sufficient without needing specialized serving
#   infrastructure at all.
#   COST: per L05, processing one request at a time means each request
#   pays the FULL per-inference GPU cost individually, with no
#   opportunity to amortize fixed overhead across multiple requests --
#   at "thousands of requests/second," this almost certainly can't hit
#   the stated throughput/latency targets without a large, expensive
#   fleet of instances running this inefficient pattern.
#
# ------------------------------------------------------------------------
# APPROACH B: Dynamic batching (L05) -- accumulate multiple incoming
# requests into a single batched inference call, within a bounded wait
# window
# ------------------------------------------------------------------------
#   WHY VALID: per L05, batching amortizes GPU inference overhead across
#   multiple requests, dramatically improving throughput-per-GPU
#   relative to A -- directly targets the stated high-throughput
#   requirement, and is a standard, well-understood technique
#   implementable within a custom serving layer.
#   COST: per L05, batching introduces a genuine LATENCY tradeoff -- a
#   request may need to wait (up to the batching window's max wait time)
#   for enough other requests to accumulate before the batch fires,
#   directly working against a strict p99 LATENCY budget if the batching
#   window isn't tuned carefully relative to that budget; getting this
#   tuning right requires real experimentation, not a one-size-fits-all
#   default.
#
# ------------------------------------------------------------------------
# APPROACH C: A dedicated, purpose-built inference server (NVIDIA
# Triton, L05) with dynamic batching, model concurrency, and hardware-
# specific optimizations built in
# ------------------------------------------------------------------------
#   WHY VALID: per L05, Triton provides B's dynamic batching benefit
#   PLUS additional production-grade features (multi-model serving,
#   concurrent model execution on the same GPU, framework-agnostic
#   support, built-in metrics) that a hand-rolled FastAPI+batching layer
#   would need to build from scratch -- the strongest throughput/latency
#   combination of the three for a workload genuinely at this scale,
#   with meaningfully less custom code to build and maintain than
#   replicating its features manually.
#   COST: per L05, adopting Triton is real additional infrastructure and
#   a genuine learning curve (its configuration model, deployment
#   patterns) beyond a simple FastAPI service -- appropriate specifically
#   once throughput/latency requirements are demanding enough to justify
#   it, not a default for every model-serving need regardless of scale.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Throughput per GPU | Latency predictability | Setup/operational complexity |
#   |----------|--------------------------|------------------------------|-------------------------------------|
#   | A: simple FastAPI, no batching | Lowest | Best (no batching wait) | Lowest |
#   | B: FastAPI + custom dynamic batching | Good | Requires careful tuning | Medium |
#   | C: Triton | Best | Good, with mature tuning options | Highest |
#   Given "thousands of requests/second" with a strict latency budget,
#   C is the strongest fit -- A is disqualified by the stated throughput
#   requirement, and B is a reasonable middle ground specifically for a
#   team not yet ready to adopt Triton's operational complexity but
#   still needing more than A provides.


# ============================================================================
# CASE STUDY 4 — RESPONDING TO A DETECTED FAIRNESS/BIAS ISSUE IN A
# DEPLOYED MODEL
# ============================================================================
#
# SETUP: a fairness audit (L11) reveals a deployed hiring-recommendation
# model shows a statistically significant disparity in recommendation
# rates across a protected demographic group.
#
# ------------------------------------------------------------------------
# APPROACH A: Remove the model feature(s) most correlated with the
# protected attribute and retrain
# ------------------------------------------------------------------------
#   WHY VALID: per L11, this is an intuitive, direct-seeming response --
#   if a feature correlates strongly with the protected attribute,
#   removing it seems like it should reduce the disparity.
#   COST: per L11's fairness discussion, this is a well-documented,
#   often INEFFECTIVE fix -- "fairness through unawareness" frequently
#   fails because OTHER features can jointly serve as effective PROXIES
#   for the removed protected-correlated feature (e.g. zip code proxying
#   for race even after an explicit race-correlated feature is removed),
#   meaning the disparity can persist largely unchanged despite removing
#   the seemingly-obvious culprit feature.
#
# ------------------------------------------------------------------------
# APPROACH B: Apply a post-processing fairness constraint (L11) --
# adjust the model's decision threshold DIFFERENTLY per demographic
# group to explicitly equalize a chosen fairness metric (e.g. equalized
# odds or demographic parity)
# ------------------------------------------------------------------------
#   WHY VALID: per L11, this directly targets the MEASURED disparity
#   itself rather than hoping a feature-removal indirectly fixes it --
#   a mathematically explicit, auditable intervention with a clearly
#   demonstrable effect on the specific fairness metric being optimized
#   for.
#   COST: per L11, different fairness metrics (demographic parity vs.
#   equalized odds vs. others) can be MUTUALLY INCOMPATIBLE to satisfy
#   simultaneously (a well-known result in fairness ML) -- choosing
#   WHICH metric to enforce is itself a real, consequential, values-
#   laden decision that the technical fix alone doesn't resolve, and
#   applying different thresholds per demographic group can itself raise
#   separate legal/policy questions depending on jurisdiction and
#   context that need real legal/policy input, not just an engineering
#   decision.
#
# ------------------------------------------------------------------------
# APPROACH C: Treat this as requiring an ORGANIZATIONAL response, not
# purely a technical one -- pause the model's use for actual hiring
# decisions, convene legal/HR/ethics stakeholders to determine the
# appropriate fairness definition/remediation BEFORE any technical fix
# is deployed, informed by L11's fairness-metric options but not decided
# by engineering alone
# ------------------------------------------------------------------------
#   WHY VALID: per L11's own point that fairness definitions involve
#   genuine value judgments (which fairness metric is "right" for THIS
#   use case is not a purely technical question), a hiring-decision
#   context specifically carries real legal (anti-discrimination law)
#   and ethical stakes that shouldn't be resolved by an engineering
#   team's unilateral technical choice -- pausing until the RIGHT
#   stakeholders weigh in is the most responsible response to a finding
#   this consequential.
#   COST: pausing model use has real, immediate operational impact
#   (hiring decisions that were being assisted by the model now need an
#   alternative process) and cross-functional alignment takes genuinely
#   longer than an engineering team unilaterally shipping a technical
#   fix -- a real velocity cost, though one this case study's stakes
#   (hiring, legal exposure) likely justify.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Likely effectiveness | Addresses the value-judgment question | Speed |
#   |----------|---------------------------|--------------------------------------------|-----------|
#   | A: remove correlated feature | Often ineffective (proxies persist) | No | Fast |
#   | B: post-processing fairness constraint | Effective for the CHOSEN metric | No (engineering picks the metric) | Medium |
#   | C: pause + cross-functional decision, then B | Effective, and properly authorized | Yes | Slowest |
#   For a hiring-decision context specifically, C (leading to an
#   informed version of B) is the responsible answer -- A alone should
#   generally be considered insufficient on its own, and B alone,
#   without C's stakeholder input on WHICH fairness definition applies,
#   risks an engineering team making a legally/ethically consequential
#   decision it isn't positioned to make unilaterally.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
