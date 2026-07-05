# ============================================================
# L08: Data Visualization Best Practices — Design, Honesty, Accessibility
# ============================================================
# WHAT: The design principles that separate a genuinely informative
#       chart from a technically-correct-but-misleading or hard-to-read
#       one — chart-type selection discipline, avoiding visual
#       distortion, color/accessibility, and honest axis choices.
# WHY: L06 and L07 covered the TOOLS (Matplotlib/Seaborn/Tableau); this
#      lesson covers the JUDGMENT that determines whether a chart built
#      with those tools actually communicates truthfully and clearly —
#      a skill independent of, and more important than, tool syntax.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
TRUNCATED Y-AXES are the single most common way a technically-accurate
chart MISLEADS: starting a bar chart's y-axis at, say, 90 instead of 0
makes a genuinely small difference (91 vs 93) LOOK like a dramatic one
visually — bar charts in particular should almost always start at zero
BECAUSE bar length is the primary visual cue readers use to judge
magnitude, and a non-zero baseline directly distorts that cue. Line
charts are more defensible with a non-zero baseline when the goal is
showing RELATIVE change/trend rather than absolute magnitude — but this
distinction must be made INTENTIONALLY, not accidentally.

CHART-JUNK is unnecessary visual decoration (3D effects on a bar chart,
excessive gridlines, decorative background images) that adds VISUAL
NOISE without adding INFORMATION — Edward Tufte's principle of
maximizing the "data-ink ratio" (the proportion of a chart's ink/pixels
that actually convey information) is the guiding heuristic: every visual
element should earn its place by communicating something, or be removed.

COLOR CHOICE has both an accessibility and a communication dimension:
roughly 8% of men have some form of color blindness (most commonly
red-green), so a chart relying on red-vs-green as its ONLY
distinguishing signal (a very common default, e.g. "red = bad, green =
good") is genuinely illegible to a meaningful fraction of viewers —
colorblind-safe palettes (blue/orange is a common safe substitute) avoid
this. Separately, using a SEQUENTIAL color scale (light-to-dark, one
hue) for ORDERED/continuous data vs a QUALITATIVE color scale (distinct
hues, no implied order) for CATEGORICAL data respects what the color
encoding actually represents — using a rainbow/qualitative palette for
continuous data implies false discrete boundaries that don't exist in
the underlying data.

CHART TYPE MISUSE (extending L06's chart-selection guidance): a PIE
CHART with many thin slices is notoriously hard for viewers to compare
accurately (human perception is much better at judging LENGTH — a bar
chart — than judging ANGLE/area — a pie slice); a 3D chart of any kind
distorts the perceived proportions of the very data it's meant to show
accurately, for purely decorative benefit.

PRODUCTION USE CASE:
A quarterly business review deck initially shows revenue growth on a
bar chart with a y-axis starting at $8M (not $0), visually exaggerating
a genuine but modest 5% quarter-over-quarter increase into what LOOKS
like a dramatic jump — after a stakeholder catches the truncated axis
and asks for the honest version starting at $0, the "dramatic" growth
visually shrinks to its accurate, still-positive-but-modest size — a
real, recurring failure mode this best-practices discipline specifically guards against.

COMMON MISTAKES:
- Truncating a bar chart's y-axis to make small differences look large —
  covered above; this is likely the single most common visualization
  malpractice, whether intentional (to oversell a result) or accidental
  (a plotting library's auto-scaling default).
- Using red/green as the ONLY distinguishing encoding on a chart,
  excluding colorblind viewers from correctly reading it — use texture,
  labels, or a colorblind-safe palette (blue/orange) as well or instead.
- Choosing a pie chart to compare many (more than ~4-5) categories, or
  categories with similar-sized slices — human perception reliably
  underperforms at comparing angles/areas compared to comparing bar
  lengths for the same underlying data.
"""

import textwrap


# ------------------------------------------------------------------
# 1. The truncated y-axis distortion, illustrated numerically
# ------------------------------------------------------------------
def truncated_axis_demo():
    quarterly_revenue = {"Q1": 9.1, "Q2": 9.4, "Q3": 9.6, "Q4": 9.55}  # in millions

    actual_growth_pct = (quarterly_revenue["Q4"] - quarterly_revenue["Q1"]) / quarterly_revenue["Q1"] * 100
    print(f"Actual Q1->Q4 growth: {actual_growth_pct:.1f}%  (genuinely modest)")

    print("\nBar chart starting y-axis at $0 (honest):")
    for q, rev in quarterly_revenue.items():
        bar = "#" * int(rev * 5)
        print(f"  {q}: {bar} ${rev}M")

    print("\nBar chart starting y-axis at $9.0M (misleading — same data):")
    for q, rev in quarterly_revenue.items():
        bar = "#" * int((rev - 9.0) * 80)   # exaggerated scale from a truncated baseline
        print(f"  {q}: {bar} ${rev}M")

    print("\n  -> IDENTICAL underlying data — the truncated-axis version "
          "visually implies a dramatic difference between quarters that "
          "the honest, zero-baseline version correctly shows as modest.")


# ------------------------------------------------------------------
# 2. Data-ink ratio principle
# ------------------------------------------------------------------
DATA_INK_PRINCIPLE = textwrap.dedent("""\
    Tufte's "data-ink ratio": (ink used to show DATA) / (total ink used)

    Chart-junk to remove or question before publishing any chart:
      - 3D effects on 2D data (bars, pies) — distorts perceived proportions
        for zero informational benefit
      - Heavy background gridlines competing visually with the data itself
      - Redundant legends when direct labeling would be clearer
      - Decorative images/textures with no data-encoding purpose

    Every remaining visual element should answer: "what information
    does this specifically communicate?" — if the honest answer is
    "none, it just looks nice," remove it.
""")

# ------------------------------------------------------------------
# 3. Colorblind-safe and semantically appropriate color choices
# ------------------------------------------------------------------
COLOR_GUIDANCE = textwrap.dedent("""\
    Color palette selection by DATA TYPE:

    SEQUENTIAL data (ordered, e.g. temperature, revenue tiers):
      Use a single-hue, light-to-dark scale (e.g. matplotlib 'Blues').
      A rainbow palette here implies false discrete category boundaries.

    DIVERGING data (a meaningful midpoint, e.g. profit/loss, correlation
    -1 to +1):
      Use a two-hue scale meeting at a neutral midpoint color
      (e.g. matplotlib 'coolwarm' or 'RdBu') — the SAME palette used in
      L06's correlation heatmap example, chosen deliberately because
      correlation has a meaningful zero midpoint.

    CATEGORICAL data (no order, e.g. product names, regions):
      Use a QUALITATIVE palette of visually distinct hues — NOT a
      sequential scale, which would falsely imply an ordering.

    ACCESSIBILITY: avoid red-green as the ONLY distinguishing signal
    (affects ~8% of men with red-green color blindness) — favor
    blue/orange, or add a secondary encoding (pattern, direct labeling,
    icon) alongside color so the chart remains legible without relying
    on color perception alone.
""")


if __name__ == "__main__":
    truncated_axis_demo()
    print()
    print(DATA_INK_PRINCIPLE)
    print(COLOR_GUIDANCE)

"""
PRODUCTION CONTEXT EXAMPLE:
A data science team's internal style guide for dashboards (built with
L06/L07's tools) mandates: bar charts always start at zero, diverging
color scales are used for any signed metric (profit/loss, model-score
deltas), and no dashboard relies on red-vs-green as its sole
pass/fail signal — a real policy adopted after a stakeholder incident
where a truncated-axis chart in an earlier report led to an
overstated impression of a marketing campaign's actual (much more
modest) impact, prompting the team to formalize these best practices
as a mandatory pre-publication checklist rather than relying on
individual analyst judgment alone.
"""
