"""
WHAT: Four realistic observability problems, each solved with THREE
      genuinely different, individually defensible approaches drawn from
      L01-L10 -- with an explicit comparison table and reasoning for why
      each answer is valid under different constraints.
WHY:  "Metrics or traces for this problem," "how aggressive should
      alerting be," "sampling strategy" are all questions L01-L10 gave
      you real tools for, not one universal answer -- this lesson is
      about the decision process under real cost and signal-quality
      constraints.
LEVEL: Capstone -- read after L01-L10.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L10's concepts.
"""

# ============================================================================
# CASE STUDY 1 — DIAGNOSING INTERMITTENT HIGH LATENCY IN A MICROSERVICES
# CALL CHAIN
# ============================================================================
#
# SETUP: a request path spans 6 microservices; p99 latency occasionally
# spikes, but which SPECIFIC service causes any given spike is unclear.
#
# ------------------------------------------------------------------------
# APPROACH A: Add more detailed METRICS (per-service latency
# histograms) to each service (L02-L03)
# ------------------------------------------------------------------------
#   WHY VALID: per L02-L03, metrics are cheap to collect and store at
#   high volume, and per-service latency histograms directly show WHICH
#   service's latency distribution has a heavy tail -- a reasonable
#   first diagnostic layer, and metrics infrastructure the team likely
#   already has for other purposes.
#   COST: per L03/L05, aggregate per-service metrics tell you WHICH
#   service is slow on average or in aggregate, but not WHICH SPECIFIC
#   REQUEST was slow, or how that slowness propagated through the
#   6-service chain for any ONE problematic request -- for a genuinely
#   intermittent issue, correlating "service B was slow around 2pm" with
#   "which SPECIFIC user request triggered it and why" from metrics
#   alone is difficult.
#
# ------------------------------------------------------------------------
# APPROACH B: Distributed tracing (L05) -- instrument the full request
# path with trace context propagated across all 6 services
# ------------------------------------------------------------------------
#   WHY VALID: per L05, distributed tracing is SPECIFICALLY built for
#   exactly this problem -- a single trace shows the EXACT path, timing,
#   and dependency structure of one specific slow request across all 6
#   services, directly answering "which service, in THIS specific slow
#   request, contributed the most latency."
#   COST: per L05, full tracing of every request has real storage/
#   processing cost at high traffic volume -- most production tracing
#   setups use SAMPLING (only trace a fraction of requests), which
#   means a genuinely rare, intermittent latency spike might occur on a
#   request that WASN'T sampled/traced, leaving no trace data for that
#   specific slow instance to examine.
#
# ------------------------------------------------------------------------
# APPROACH C: B, combined with TAIL-BASED sampling (L05/L07's
# OpenTelemetry discussion) -- rather than sampling a random fixed
# percentage of ALL requests, make the sampling DECISION after seeing
# the full trace's characteristics, specifically retaining traces for
# requests that turned out to be slow (or errored), even if most
# "normal" requests are discarded
# ------------------------------------------------------------------------
#   WHY VALID: per L07's OpenTelemetry/sampling discussion, tail-based
#   sampling directly addresses B's "the slow request might not have
#   been sampled" gap -- by deferring the sampling decision until the
#   full trace's outcome (including its actual latency) is known, it can
#   deliberately KEEP traces for exactly the slow/anomalous requests
#   that matter most for this investigation, while still discarding most
#   routine, fast requests to control storage cost.
#   COST: per L07, tail-based sampling requires buffering/holding
#   complete trace data until the sampling decision can be made (since
#   you don't know if a trace will turn out to be "interesting" until
#   it's finished) -- real, additional infrastructure complexity (a
#   collector layer capable of this buffering) compared to B's simpler
#   head-based (decide-at-the-start) sampling.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Pinpoints the specific slow service in a specific request | Captures rare/intermittent slow requests | Infrastructure complexity |
#   |----------|--------------------------------------------------------------------|-------------------------------------------------|----------------------------------|
#   | A: per-service metrics | No (aggregate only) | N/A (always collecting) | Lowest |
#   | B: distributed tracing, head-based sampling | Yes, if the slow request was sampled | Poor (may miss the rare event) | Medium |
#   | C: tracing + tail-based sampling | Yes | Good (biased toward capturing anomalies) | Highest |
#   A remains valuable as a first, cheap signal ("which service's
#   aggregate latency looks off"); C is the strongest answer for
#   actually catching and diagnosing a genuinely intermittent, hard-to-
#   reproduce issue, justifying its added complexity specifically for
#   this diagnostic need.


# ============================================================================
# CASE STUDY 2 — DESIGNING ALERTING FOR AN SLO (L06)
# ============================================================================
#
# SETUP: a service has a 99.9% availability SLO; deciding how alerting
# should fire when the error budget is being consumed.
#
# ------------------------------------------------------------------------
# APPROACH A: Alert immediately on ANY error, regardless of rate
# ------------------------------------------------------------------------
#   WHY VALID: guarantees no error goes unnoticed -- maximal
#   sensitivity, appropriate ONLY for a system with an extremely strict
#   near-100% requirement where literally any error is unacceptable and
#   worth immediate human attention.
#   COST: per L06, for a 99.9% SLO (which explicitly BUDGETS for some
#   errors — roughly 43 minutes of downtime/errors per month is within
#   budget), alerting on every single error massively over-alerts
#   relative to what actually threatens the SLO -- a severe, well-
#   documented cause of alert fatigue (L11's DevOps & SRE Practices
#   Notes discussion), where genuinely important alerts get lost among
#   noise.
#
# ------------------------------------------------------------------------
# APPROACH B: Alert only when the error RATE over a fixed window (e.g.
# the last 5 minutes) exceeds a threshold consistent with burning the
# error budget too fast (L06)
# ------------------------------------------------------------------------
#   WHY VALID: per L06, this directly ties alerting to the ACTUAL SLO
#   commitment -- only fires when errors are occurring fast enough to
#   genuinely threaten the monthly budget, filtering out the "occasional
#   error within budget" noise A generates.
#   COST: per L06, a FIXED short window can both fire on brief, self-
#   resolving blips (a 2-minute error spike that recovers on its own
#   might still cross a 5-minute-window threshold, causing an
#   unnecessary page) AND fail to catch a SLOW, sustained burn (an error
#   rate just under the threshold, sustained for hours, silently
#   consuming the whole month's budget without ever crossing the
#   window's trigger point).
#
# ------------------------------------------------------------------------
# APPROACH C: Multi-window, multi-burn-rate alerting (L06) -- alert on
# a FAST burn rate over a SHORT window (catches severe, urgent issues
# quickly) AND a SLOWER burn rate over a LONGER window (catches
# sustained, slow-burning issues that a short window alone would miss),
# as two DIFFERENT alert severities
# ------------------------------------------------------------------------
#   WHY VALID: per L06, this is the industry-standard, well-established
#   pattern (popularized by Google's SRE practices) specifically
#   designed to address BOTH of B's gaps simultaneously -- a genuinely
#   severe issue triggers the fast-burn, short-window alert quickly
#   (urgent paging), while a slow, sustained issue that a short window
#   would miss still triggers the slow-burn, long-window alert (lower
#   urgency, but still catches it before the whole budget is silently
#   exhausted).
#   COST: per L06, genuinely more configuration complexity than a
#   single-window threshold -- multiple burn-rate/window combinations to
#   define and tune, and getting the SPECIFIC thresholds right (what
#   counts as "fast" vs "slow" burn for THIS service's actual traffic
#   pattern) requires real, iterative tuning against the service's
#   observed behavior, not a one-size-fits-all default.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Alert fatigue risk | Catches fast, severe issues | Catches slow, sustained budget burn |
#   |----------|-------------------------|-----------------------------------|--------------------------------------------|
#   | A: alert on any error | Severe | Yes (over-alerts) | Yes (over-alerts) |
#   | B: single-window burn-rate threshold | Real (blip-triggered) | Partially | No (can miss slow burns) |
#   | C: multi-window, multi-burn-rate | Low, if well-tuned | Yes | Yes |
#   C is the strong, well-established production standard specifically
#   because it addresses both failure modes B leaves open; A should
#   essentially never be the answer for a service with an explicit,
#   budget-aware SLO like this one.


# ============================================================================
# CASE STUDY 3 — MANAGING LOG VOLUME/COST FOR A HIGH-TRAFFIC SERVICE
# ============================================================================
#
# SETUP: a service's structured logging (L04) has grown to a genuinely
# significant storage/ingestion cost as traffic scaled; the team needs
# to reduce cost without losing the ability to debug production issues.
#
# ------------------------------------------------------------------------
# APPROACH A: Reduce log volume by raising the minimum log LEVEL (e.g.
# stop logging at INFO, only log WARN and above) (L04)
# ------------------------------------------------------------------------
#   WHY VALID: the simplest possible cost lever -- directly and
#   immediately reduces log volume by dropping an entire verbosity tier,
#   no new infrastructure needed.
#   COST: per L04, this is a blunt, UNIFORM cut -- it removes INFO-level
#   context for EVERY request, including the (unknown in advance) small
#   subset that will later turn out to be relevant to some future
#   debugging investigation; when an incident occurs, the team may find
#   they no longer have the INFO-level breadcrumbs that would have
#   helped diagnose it, discovered only after the fact when it's too
#   late to have logged differently.
#
# ------------------------------------------------------------------------
# APPROACH B: Sample logs -- keep only a percentage of INFO-level log
# lines (e.g. 10%), keep 100% of WARN/ERROR (L04)
# ------------------------------------------------------------------------
#   WHY VALID: per L04, reduces cost while still preserving SOME INFO-
#   level visibility (useful for aggregate pattern analysis, e.g. "what
#   does typical request volume/shape look like") and, critically,
#   keeps ALL error/warning logs at full fidelity, where debugging value
#   is highest -- a more targeted cut than A's uniform level-based
#   removal.
#   COST: per L04, for debugging a SPECIFIC user's reported issue (not a
#   general error), the relevant INFO-level context for THAT exact
#   request has only a 10% chance of having been sampled/kept -- sampling
#   is a poor fit when debugging needs are tied to a SPECIFIC, known
#   request rather than aggregate pattern visibility.
#
# ------------------------------------------------------------------------
# APPROACH C: Keep full-fidelity logging, but tier storage -- recent
# logs (e.g. last 7 days) in fast, more expensive storage/indexing;
# older logs moved to cheap, cold storage (still retrievable, but
# slower to query and not actively indexed for fast search) (L04,
# adjacent to Cloud Platforms Notes' storage-tiering discussion)
# ------------------------------------------------------------------------
#   WHY VALID: recognizes that log VALUE is highly time-skewed -- the
#   vast majority of debugging investigations happen within days of an
#   event, not months later -- so this preserves FULL fidelity (unlike A
#   or B) for the period where logs are actually mostly used, while
#   still capturing real cost savings by moving older, rarely-accessed
#   logs to cheaper storage rather than deleting or degrading them.
#   COST: doesn't reduce INGESTION cost at all (every log line is still
#   fully written at full fidelity initially) -- only reduces long-term
#   STORAGE cost; if the actual cost driver is ingestion/indexing volume
#   (not long-term storage), this approach doesn't address that specific
#   cost component the way A or B directly would.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Reduces ingestion cost | Reduces long-term storage cost | Preserves debugging value for a specific request |
#   |----------|------------------------------|--------------------------------------|-----------------------------------------------------------|
#   | A: raise log level | Yes | Yes | Poor (INFO context gone entirely) |
#   | B: sample INFO logs | Yes | Yes | Poor (10% chance the specific request was kept) |
#   | C: tiered storage, full fidelity | No | Yes | Best (full fidelity while recent) |
#   If the cost driver is genuinely INGESTION volume, some combination
#   of A/B is necessary; if it's primarily long-term STORAGE cost, C
#   preserves far more debugging value for the same savings -- correctly
#   diagnosing WHICH cost component is actually the problem (via the
#   observability platform's own cost breakdown) should precede picking
#   a fix, rather than assuming.


# ============================================================================
# CASE STUDY 4 — DECIDING WHAT TO INSTRUMENT FIRST FOR A NEW SERVICE
# WITH LIMITED TIME BEFORE LAUNCH
# ============================================================================
#
# SETUP: a new service launches soon; the team has limited time to add
# observability instrumentation before launch and needs to prioritize.
#
# ------------------------------------------------------------------------
# APPROACH A: Prioritize comprehensive LOGGING first (L04) -- log
# everything reasonably loggable, defer metrics/tracing
# ------------------------------------------------------------------------
#   WHY VALID: logging is generally the fastest to add (often just
#   structured log statements at existing code points) and provides
#   broad, if less structured, visibility into what the service is
#   doing -- a reasonable "get SOME visibility fast" first move.
#   COST: per L02-L03/L06's golden-signals framing, logs alone are poor
#   for ANSWERING "is the service healthy right now" at a glance --
#   there's no natural aggregate view of latency/error-rate/traffic
#   from raw logs without additional processing, meaning on-call
#   engineers have no quick health dashboard, only a firehose to search
#   through reactively after being alerted some OTHER way.
#
# ------------------------------------------------------------------------
# APPROACH B: Prioritize the FOUR GOLDEN SIGNALS as metrics first (L01-
# L03) -- latency, traffic, errors, saturation -- with basic alerting on
# SLO-relevant thresholds, defer detailed tracing/logging
# ------------------------------------------------------------------------
#   WHY VALID: per L01-L03/L06, this gets the team the MINIMUM viable
#   "is the service healthy" signal and the ability to be PAGED when
#   it isn't -- arguably the single highest-leverage instrumentation
#   investment for a NEW service, since knowing something is wrong
#   (even without full diagnostic depth yet) is the prerequisite for
#   everything else.
#   COST: per L05, once alerted that something IS wrong, golden-signal
#   metrics alone often don't tell you WHY -- without any tracing/
#   detailed logging yet in place, diagnosing the ROOT CAUSE of an
#   incident in this brand-new service could be genuinely harder than
#   it needs to be, right at launch when unknowns are highest.
#
# ------------------------------------------------------------------------
# APPROACH C: A minimal version of ALL THREE pillars (L01) -- basic
# golden-signal metrics AND basic structured logging AND basic request
# tracing, each at a "good enough for launch" depth rather than fully
# comprehensive in any one pillar
# ------------------------------------------------------------------------
#   WHY VALID: per L01's three-pillars framing, each pillar answers a
#   genuinely DIFFERENT question (metrics: is it healthy; logs: what
#   happened; traces: where in the request path did it happen) -- for a
#   NEW, unproven service where the team doesn't yet know what kinds of
#   issues will actually arise, having SOME visibility into all three
#   dimensions is more robust than deep investment in only one,
#   hedging against not yet knowing which pillar will matter most for
#   this specific service's actual failure modes.
#   COST: "a minimal version of everything" means NONE of the three
#   pillars gets the depth a full, focused investment (per B alone, or
#   A alone) would provide -- if time is TRULY limited, spreading effort
#   across three pillars at shallow depth each risks all three being
#   somewhat inadequate rather than at least ONE being genuinely solid.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Time to "is it healthy" visibility | Time to root-cause diagnostic depth | Risk of shallow coverage everywhere |
#   |----------|-------------------------------------------|-------------------------------------------|-------------------------------------------|
#   | A: logging first | Poor (no aggregate health view) | Medium (searchable, but unstructured across dimensions) | N/A (one pillar, done reasonably) |
#   | B: golden-signal metrics first | Best | Poor (no "why" without more) | N/A (one pillar, done reasonably) |
#   | C: minimal version of all three | Medium | Medium | Real |
#   B is the strongest SINGLE-pillar priority for a brand-new,
#   unlaunched service specifically because "know something is wrong"
#   is the prerequisite for everything else that follows; C is
#   defensible when genuinely enough time exists for a competent
#   minimal pass at all three, but shouldn't be chosen if it means B's
#   critical alerting capability ends up rushed or incomplete at launch.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
