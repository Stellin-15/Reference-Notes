"""
WHAT: Four realistic statistical/EDA problems, each solved with THREE
      genuinely different, individually defensible approaches drawn from
      L01-L09 -- with an explicit comparison table and reasoning for why
      each answer is valid under different constraints. Distinct from
      L09's capstone (one full EDA-to-communication workflow) -- this
      lesson is about the decision process across competing options for
      a single problem, not one worked walkthrough.
WHY:  "Which test/which visualization/how to handle outliers" are all
      questions L01-L09 gave you real tools for, not one universal
      answer -- this lesson is about the decision process under real
      data and audience constraints.
LEVEL: Capstone -- read after L01-L09.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L09's concepts.
"""

# ============================================================================
# CASE STUDY 1 — TESTING WHETHER A NEW WEBSITE DESIGN INCREASES
# CONVERSION RATE
# ============================================================================
#
# SETUP: an A/B test comparing old vs. new website design's conversion
# rate (a binary outcome per visitor); the team needs to determine
# whether an observed difference is real.
#
# ------------------------------------------------------------------------
# APPROACH A: A two-proportion z-test comparing conversion rates
# directly (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, this is the textbook-standard test for exactly
#   this situation -- comparing two independent proportions (conversion
#   rate is a proportion: conversions/visitors) -- well-understood,
#   fast to compute, and appropriate given the Central Limit Theorem
#   makes the normal approximation reasonable at typical A/B test
#   sample sizes (hundreds to thousands of visitors per arm).
#   COST: per L02's own hypothesis-testing caveats, a single p-value
#   from one test run tells you NOTHING about effect size or practical
#   significance -- a statistically significant 0.1 percentage-point
#   conversion lift with a huge sample size could be real but
#   practically meaningless to the business, a distinction the raw
#   z-test result alone doesn't communicate.
#
# ------------------------------------------------------------------------
# APPROACH B: A two-proportion z-test PLUS an explicit confidence
# interval on the DIFFERENCE in conversion rates, reported alongside the
# p-value (L02)
# ------------------------------------------------------------------------
#   WHY VALID: directly addresses A's gap -- per L02, a confidence
#   interval on the effect size (e.g. "new design increases conversion
#   by 0.3 to 1.8 percentage points, 95% CI") tells stakeholders both
#   WHETHER an effect likely exists AND how large it plausibly is,
#   letting the business judge practical significance themselves rather
#   than inferring it from a bare p-value.
#   COST: still assumes a SINGLE, one-shot test evaluated once at a
#   predetermined sample size -- if the team is tempted to check results
#   repeatedly as data accumulates and stop "when it looks significant"
#   (a very common real-world practice), this violates the test's
#   underlying assumptions and inflates the true false-positive rate,
#   a distinct problem neither the p-value nor the CI alone protects
#   against.
#
# ------------------------------------------------------------------------
# APPROACH C: Sequential testing / a pre-registered stopping rule (a
# more advanced extension of L02's hypothesis-testing framework,
# directly covered in MLOps Notes L09's online-experimentation
# discussion) -- explicitly plan for continuous monitoring with
# statistically valid early-stopping boundaries
# ------------------------------------------------------------------------
#   WHY VALID: directly solves B's "peeking" problem -- per MLOps Notes
#   L09, sequential testing methods are specifically designed to allow
#   valid continuous monitoring and early stopping without inflating
#   false-positive rates, matching how teams ACTUALLY want to run A/B
#   tests in practice (watching results as they come in, not waiting
#   blindly for a fixed sample size).
#   COST: genuinely more complex to set up and explain to non-
#   statistical stakeholders than a standard fixed-sample z-test --
#   requires deciding on stopping boundaries/rules BEFORE the test
#   starts (a real, disciplined pre-commitment many teams skip under
#   time pressure), and if that discipline slips, the statistical
#   validity guarantee this approach provides is compromised anyway.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Communicates effect size | Protects against "peeking" | Setup/explanation complexity |
#   |----------|-------------------------------|-----------------------------------|------------------------------------|
#   | A: z-test, p-value only | No | No | Lowest |
#   | B: z-test + confidence interval | Yes | No | Low |
#   | C: sequential testing | Yes | Yes | Highest |
#   B is a strong, practical default for a genuinely one-shot,
#   fixed-sample-size test; C is the correct answer specifically once a
#   team acknowledges (honestly) that they WILL look at results before
#   the planned sample size is reached, which in practice is most teams,
#   most of the time.


# ============================================================================
# CASE STUDY 2 — HANDLING OUTLIERS IN A DATASET OF CUSTOMER ORDER VALUES
# BEFORE COMPUTING SUMMARY STATISTICS FOR A REPORT
# ============================================================================
#
# SETUP: an order-value dataset has a small number of extremely large
# orders (legitimate bulk/enterprise purchases, not data errors) mixed
# with the typical range of individual consumer orders.
#
# ------------------------------------------------------------------------
# APPROACH A: Remove the outliers before computing summary statistics
# (e.g. drop anything beyond 3 standard deviations from the mean, L03)
# ------------------------------------------------------------------------
#   WHY VALID: per L03, extreme values can badly distort the MEAN
#   specifically (a single very large order can shift the average
#   noticeably) -- removing them can make reported statistics more
#   representative of "typical" order behavior, which may be exactly
#   what a report about consumer purchasing patterns needs.
#   COST: per L03's own framing, these are stated to be LEGITIMATE
#   enterprise orders, not data errors -- removing real, valid data
#   points to make a statistic "look cleaner" is a form of silently
#   discarding true information, and if the report's actual purpose
#   includes understanding TOTAL revenue or the full customer base
#   (including enterprise accounts), deleting them produces a
#   systematically misleading, not just simplified, picture.
#
# ------------------------------------------------------------------------
# APPROACH B: Keep all data, but report the MEDIAN (and IQR) instead of
# the mean (and standard deviation) as the primary summary statistic
# (L03)
# ------------------------------------------------------------------------
#   WHY VALID: per L03, the median is inherently ROBUST to extreme
#   values (a few very large orders barely move the median at all,
#   unlike the mean) -- this preserves ALL the real data (unlike A)
#   while still reporting a "typical value" statistic that isn't
#   distorted by the enterprise orders, directly targeting the actual
#   statistical property (mean's outlier-sensitivity) causing the
#   original problem.
#   COST: the median alone doesn't communicate the TOTAL scale/spread
#   of the data, including the genuinely large enterprise orders that
#   ARE part of the real business -- if stakeholders care about total
#   revenue or the full distribution's tail (a common, legitimate
#   business question), median-only reporting can create its own kind
#   of misleading impression by omission, just a different one than A's.
#
# ------------------------------------------------------------------------
# APPROACH C: Segment the analysis explicitly -- report statistics
# SEPARATELY for "consumer" orders and "enterprise" orders (defined by
# an actual business-meaningful threshold or account type, not just a
# statistical outlier cutoff), rather than trying to summarize both
# populations with one number
# ------------------------------------------------------------------------
#   WHY VALID: per L03's broader point that "outliers" are sometimes
#   evidence of a GENUINELY DIFFERENT underlying population/process
#   mixed into one dataset -- if enterprise and consumer orders really
#   are two distinct business phenomena with different typical values,
#   treating them as one distribution to be "fixed" (A or B) is itself
#   the wrong framing; segmenting preserves and clearly communicates
#   BOTH populations' true characteristics rather than compressing them
#   into one potentially-misleading number.
#   COST: requires having (or being able to construct) a genuine,
#   business-meaningful way to distinguish the two segments -- if the
#   line between "large consumer order" and "small enterprise order" is
#   genuinely blurry or unavailable in the data, this clean segmentation
#   may not be cleanly achievable, and even when it is, the report now
#   needs to communicate TWO sets of statistics instead of one, a real
#   added complexity for the report's audience to absorb.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Preserves all real data | Represents "typical" value well | Represents true business scale/mix |
#   |----------|-------------------------------|---------------------------------------|-------------------------------------------|
#   | A: remove outliers | No | Yes (but at the cost of dropped data) | No |
#   | B: median instead of mean | Yes | Yes | Partially (loses tail info) |
#   | C: segment consumer vs enterprise | Yes | Yes, per segment | Best |
#   C is the strongest answer specifically because this case study's
#   setup states the "outliers" are a genuinely distinct, legitimate
#   population (not errors) -- A should essentially never be the answer
#   here; B is a reasonable simpler fallback if segmenting isn't
#   practically achievable with the available data.


# ============================================================================
# CASE STUDY 3 — CHOOSING A VISUALIZATION FOR COMPARING SALES ACROSS 15
# PRODUCT CATEGORIES OVER 12 MONTHS
# ============================================================================
#
# SETUP: a dashboard needs to show how 15 product categories' monthly
# sales have trended over the past year -- both overall patterns and
# individual category detail matter to different viewers.
#
# ------------------------------------------------------------------------
# APPROACH A: A single line chart with all 15 categories plotted as
# separate lines (L06)
# ------------------------------------------------------------------------
#   WHY VALID: shows every category's exact trend simultaneously in one
#   view, technically complete -- no information is hidden or aggregated
#   away, and for a viewer who genuinely wants to compare two or three
#   SPECIFIC categories' trends against each other, having them all on
#   one chart makes direct visual comparison possible.
#   COST: per L06/L08's chart-junk and readability discussion, 15
#   distinct lines on one chart is a well-documented readability
#   failure -- overlapping lines, an unusably crowded legend, and
#   colors that become hard to distinguish well before 15 categories
#   (most color palettes struggle to remain distinguishable much past
#   8-10 categories) make this chart genuinely hard to actually read,
#   despite being technically complete.
#
# ------------------------------------------------------------------------
# APPROACH B: A small-multiples layout (L08) -- 15 small, individual
# line charts (one per category), arranged in a grid, all sharing the
# same y-axis scale
# ------------------------------------------------------------------------
#   WHY VALID: per L08's chart-type-selection discussion, small
#   multiples directly solve A's overcrowding problem -- each category
#   gets its OWN clear, uncluttered trend line, and the shared y-axis
#   scale (an important, easy-to-get-wrong detail, per L08's honest-axes
#   principle) still allows valid visual comparison of MAGNITUDE across
#   categories, not just shape.
#   COST: takes up meaningfully more visual/screen space than a single
#   chart, and per-category DIRECT comparison (e.g. "exactly how did
#   category 3 compare to category 7 in March") is somewhat harder when
#   they're not on the same axes, requiring the viewer's eye to jump
#   between two separate small charts rather than reading one shared
#   plot directly.
#
# ------------------------------------------------------------------------
# APPROACH C: An interactive dashboard (Tableau, L07) where all 15
# categories are shown in an overview (e.g. a heatmap of category x
# month, or a stacked/grouped view), with click-to-filter/drill-down
# into individual category detail
# ------------------------------------------------------------------------
#   WHY VALID: per L07's BI-vs-code-based-plotting discussion, this
#   directly serves this case study's TWO stated audiences (overall
#   pattern viewers AND individual-category-detail viewers) with ONE
#   artifact rather than needing to choose between A and B's fixed
#   tradeoffs -- a summary view for the big picture, with interactive
#   drill-down for anyone who wants a specific category's full detail.
#   COST: per L07, requires BI tooling/infrastructure (not just a
#   static chart export) and a genuine design/build investment in the
#   interactive experience -- appropriate for a persistent, recurring
#   dashboard viewed by many people repeatedly, but real overkill for a
#   one-off report or presentation that a static chart (A or B) would
#   serve perfectly well and far more cheaply.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Readability at 15 categories | Serves both stated audiences | Effort/tooling required |
#   |----------|-----------------------------------|-------------------------------------|--------------------------------|
#   | A: single line chart, all categories | Poor | Partially (favors direct comparison) | Lowest |
#   | B: small multiples | Good | Partially (favors individual detail) | Low |
#   | C: interactive BI dashboard | Best (via drill-down) | Best | Highest |
#   For a RECURRING, widely-viewed dashboard, C is the strongest fit
#   given the stated dual-audience need; for a one-off static report or
#   slide, B is the better default over A, specifically because A's
#   15-line overcrowding problem is severe enough to disqualify it in
#   most realistic cases at this category count.


# ============================================================================
# CASE STUDY 4 — INVESTIGATING A SURPRISING CORRELATION FOUND DURING EDA
# ============================================================================
#
# SETUP: exploratory analysis reveals a strong correlation between
# employees' commute distance and their performance review scores --
# genuinely surprising, and the team needs to decide how to handle/
# report this finding.
#
# ------------------------------------------------------------------------
# APPROACH A: Report the correlation as found, with a strong "correlation
# is not causation" caveat attached (L03)
# ------------------------------------------------------------------------
#   WHY VALID: per L03, transparently reporting a genuinely surprising
#   finding (with the standard, appropriate caveat) respects the
#   integrity of the exploratory analysis -- suppressing a real,
#   statistically notable pattern because it's uncomfortable or hard to
#   explain isn't good practice either.
#   COST: per L03's own correlation-vs-causation discussion, a bare
#   caveat is often INSUFFICIENT to prevent readers from drawing an
#   unwarranted causal conclusion anyway ("commute distance affects
#   performance" is a much more memorable, actionable-sounding takeaway
#   than "these two things happen to correlate for reasons we haven't
#   investigated") -- the caveat is necessary but often not sufficient
#   protection against misinterpretation, especially by an audience
#   without a statistics background.
#
# ------------------------------------------------------------------------
# APPROACH B: Actively investigate plausible CONFOUNDING variables
# before reporting anything (L03's correlation-vs-causation framework)
# -- e.g. does commute distance correlate with tenure, department, or
# seniority, any of which might independently explain BOTH commute
# distance and performance scores
# ------------------------------------------------------------------------
#   WHY VALID: per L03, this is the substantively correct next
#   scientific step -- rather than just caveating an unexplained
#   correlation, actually looking for a plausible confounder (e.g. maybe
#   senior employees both live farther out, having settled down with
#   families, AND score higher due to tenure/experience, with commute
#   distance itself doing no causal work at all) can often explain the
#   surprising pattern, turning an alarming finding into an understood,
#   correctly-attributed one.
#   COST: genuinely more analytical work, and even a thorough confounder
#   search doesn't PROVE the absence of causation, only makes a
#   candidate confounding explanation more or less plausible -- this
#   process can also fail to find a satisfying confounder while still
#   not proving genuine causation, leaving the team in a genuinely
#   ambiguous position that requires honest communication of that
#   ambiguity, not a false sense of closure either way.
#
# ------------------------------------------------------------------------
# APPROACH C: Treat the finding as PURELY exploratory and NOT report it
# externally at all until (or unless) it can be validated with a properly
# designed follow-up study specifically built to isolate this
# relationship
# ------------------------------------------------------------------------
#   WHY VALID: per L03's broader point about exploratory analysis
#   generating HYPOTHESES rather than confirmed conclusions, a single
#   surprising EDA correlation is exactly the kind of finding that's
#   appropriate to treat as "worth investigating further," not yet
#   "worth acting on or publicizing" -- especially for a finding this
#   sensitive (touching employee performance evaluation), where a
#   premature, poorly-caveated report could cause real, unwarranted
#   organizational concern or worse, unwarranted policy changes.
#   COST: a real, deliberately-designed follow-up study takes
#   significant additional time and effort to actually execute, and
#   during that time, a genuinely real and actionable pattern (if it IS
#   causal) goes uninvestigated and unaddressed -- appropriate caution,
#   but caution has a real opportunity cost if the underlying issue
#   turns out to be genuine and important.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Risk of causal misinterpretation by readers | Analytical rigor | Speed to actionable answer |
#   |----------|----------------------------------------------------|------------------------|-----------------------------------|
#   | A: report with caveat | Real, even with caveat | Lowest | Fastest |
#   | B: investigate confounders first | Lower (better-informed reporting) | Higher | Medium |
#   | C: treat as hypothesis-only, pursue a real follow-up study | Lowest (nothing premature reported) | Highest (eventually) | Slowest |
#   For a finding this sensitive (employee performance), B is the
#   strongest immediate next step (genuinely try to explain it before
#   reporting further), escalating to C specifically if the finding
#   survives confounder investigation and still looks potentially
#   important enough to justify real follow-up investment; A alone,
#   without B's investigative step first, is the weakest of the three
#   for a finding with this much potential for misinterpretation and
#   real organizational consequence.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
