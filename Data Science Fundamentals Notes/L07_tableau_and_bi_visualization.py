# ============================================================
# L07: Tableau and Business Intelligence Visualization
# ============================================================
# WHAT: How BI (Business Intelligence) tools like Tableau differ from
#       code-based plotting (L06) — drag-and-drop dashboard building,
#       live data-source connections, and interactive filtering — plus
#       when a BI tool is the right choice vs a Python-based approach.
# WHY: This repo's job-description gap analysis identified Tableau
#      named explicitly in ML engineer job postings alongside Matplotlib/
#      Seaborn — BI tools serve a genuinely DIFFERENT audience (business
#      stakeholders, not data scientists reading a Jupyter notebook) that
#      L06's code-based tools don't address.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
BI (Business Intelligence) TOOLS like Tableau, Power BI, and Looker
serve a fundamentally different PURPOSE than L06's Matplotlib/Seaborn:
they're built for BUSINESS STAKEHOLDERS to explore data INTERACTIVELY
(filtering, drilling down, changing date ranges) WITHOUT writing code —
a sales director exploring a revenue dashboard doesn't want to ask a
data analyst to regenerate a static chart for every new question; a
well-built BI DASHBOARD lets them answer many of their own follow-up
questions directly.

LIVE DATA CONNECTIONS are a defining BI-tool capability: a Tableau
dashboard connects DIRECTLY to a live database/warehouse (this repo's
Snowflake, this repo's Data Engineering Notes) and REFRESHES
automatically on a schedule (or live, for some connection types) —
contrasted with a Matplotlib chart, which is a STATIC snapshot generated
once from whatever data was loaded into the script at that moment, with
no built-in mechanism to stay current.

DASHBOARDS combine multiple visualizations with SHARED INTERACTIVE
FILTERS — selecting "Q3 2026" in one filter control updates EVERY chart
on the dashboard simultaneously, letting a single dashboard serve many
different analytical questions depending on how a viewer interacts with
it, rather than requiring a separate static chart image for each possible question.

WHEN TO USE BI TOOLS VS CODE-BASED PLOTTING: BI tools excel for
RECURRING, business-stakeholder-facing reporting (a weekly sales
dashboard reused by many non-technical viewers) where interactivity and
ease-of-self-service matter more than plotting flexibility. Code-based
tools (L06) excel for ONE-OFF, ANALYST-FACING exploratory work (EDA
during a specific investigation), highly CUSTOM visualizations BI tools
don't support well, and any visualization that needs to be VERSION-
CONTROLLED and reproduced exactly as part of a reproducible analysis
pipeline (a BI dashboard's state lives in the BI tool itself, not in a
git-trackable script).

PRODUCTION USE CASE:
A subscription business builds a Tableau dashboard tracking monthly
recurring revenue (MRR), churn rate, and customer acquisition cost, with
filters for product tier and region — connected LIVE to the company's
Snowflake warehouse (this repo's Data Engineering Notes L07) — executives
check this dashboard weekly, filtering by their own region/tier
interests WITHOUT needing a data analyst to generate a new report for
each specific slice they want to examine.

COMMON MISTAKES:
- Building a BI dashboard for a ONE-OFF analytical question that will
  never be revisited — the overhead of building an interactive dashboard
  (vs a single Python script generating one chart) isn't justified
  unless the visualization will genuinely be reused/explored repeatedly
  by multiple stakeholders.
- Cramming TOO MANY charts/metrics onto a single dashboard "to be
  comprehensive" — an overloaded dashboard with 15 charts competing for
  attention serves viewers WORSE than a focused dashboard highlighting
  the 3-4 metrics that actually matter for the decisions it's meant to support.
- Connecting a dashboard to a LIVE, unoptimized query against a large
  production database rather than a pre-aggregated table/materialized
  view — this can create genuine performance/cost problems (repeatedly
  re-running an expensive query every time any viewer opens the
  dashboard or changes a filter), a concern this repo's Data Engineering
  Notes' data-warehouse-design lessons address from the pipeline side.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Tableau's core building blocks, conceptually
# ------------------------------------------------------------------
TABLEAU_CONCEPTS = textwrap.dedent("""\
    Tableau's core concepts (drag-and-drop, no code required):

    1. DATA SOURCE: connect to a database (Snowflake, PostgreSQL), a
       flat file (CSV, Excel), or a live API — Tableau can REFRESH this
       connection on a schedule (extract) or query LIVE on every interaction.

    2. DIMENSIONS vs MEASURES: Tableau automatically classifies each
       column as a DIMENSION (categorical: region, product name — used
       to group/slice data) or a MEASURE (numeric: revenue, count — used
       to aggregate: sum, average, count).

    3. WORKSHEET: a single chart, built by dragging dimensions/measures
       onto "Rows"/"Columns"/"Color"/"Size" shelves — Tableau infers a
       reasonable chart type automatically, adjustable manually.

    4. DASHBOARD: combines multiple worksheets with SHARED FILTERS —
       clicking a data point in one chart can filter/highlight related
       data in every other chart on the dashboard ("dashboard actions").

    5. CALCULATED FIELDS: formulas for derived metrics not present in
       the raw data (e.g. "Profit Margin = Profit / Revenue"), similar
       in spirit to a derived column in a pandas DataFrame, but defined
       through Tableau's UI rather than code.
""")

# ------------------------------------------------------------------
# 2. Choosing BI vs code-based visualization
# ------------------------------------------------------------------
DECISION_FRAMEWORK = textwrap.dedent("""\
    Use a BI tool (Tableau/Power BI/Looker) when:
      - The audience is NON-TECHNICAL business stakeholders
      - The visualization will be VIEWED REPEATEDLY over time (recurring
        reporting, not a one-off investigation)
      - Viewers need to SELF-SERVE different slices via interactive filters
      - Data needs to stay CURRENT via a live/scheduled-refresh connection

    Use code-based plotting (Matplotlib/Seaborn, L06) when:
      - The audience is technical (data scientists, analysts reading a
        notebook/report alongside code and statistical detail)
      - The visualization is a ONE-OFF exploratory or diagnostic chart
      - The chart needs CUSTOM statistical elements BI tools don't
        support well (a residual plot, a custom significance annotation)
      - REPRODUCIBILITY matters — the chart-generation code should be
        version-controlled and rerun-able as part of an analysis pipeline
""")


if __name__ == "__main__":
    print(TABLEAU_CONCEPTS)
    print(DECISION_FRAMEWORK)

"""
PRODUCTION CONTEXT EXAMPLE:
A data science team investigating a specific model performance
regression uses Matplotlib/Seaborn (L06) to generate one-off residual
plots and a correlation heatmap as part of a Jupyter notebook
investigation — code-based, version-controlled, never needing to be
revisited once the root cause is found. The SAME team also maintains a
Tableau dashboard tracking that model's live production accuracy,
latency, and prediction-volume metrics, refreshed hourly from a
monitoring database, that on-call engineers and product stakeholders
check regularly WITHOUT needing to run any code — two entirely
different visualization needs, each correctly matched to the tool built for it.
"""
