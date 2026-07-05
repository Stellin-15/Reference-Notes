# ============================================================
# L11: Data Quality Testing, Lineage, and Pipeline Observability
# ============================================================
# WHAT: Automated data quality testing (Great Expectations-style
#       assertions, dbt tests), data lineage (tracking where data came
#       from and what depends on it), and pipeline monitoring/alerting —
#       the practices that catch broken data BEFORE it reaches a
#       dashboard or a downstream ML model.
# WHY: Every pipeline built in L01-L10 can run "successfully" (no
#      exceptions, no failed tasks) while still producing WRONG data — a
#      silently dropped join, a schema drift auto-accepted into a numeric
#      field that should have failed, a source system's outage that
#      loaded zero rows without erroring. Data quality practices catch
#      exactly this class of "technically succeeded, actually broken" failure.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
DATA QUALITY TESTING means writing explicit, automated ASSERTIONS about
what your data should look like — not just "did the pipeline run without
throwing an exception," but "does `order_id` have zero nulls," "is
`amount_usd` always non-negative," "did we load roughly the expected
ROW COUNT compared to yesterday" (a volume/freshness check). Tools like
Great Expectations define these as reusable, versioned "Expectations";
dbt's built-in test framework (`not_null`, `unique`, `relationships`,
plus custom SQL-based tests) does the same for dbt-managed transformations.

DATA LINEAGE tracks, for any given table/column, WHERE its data came from
(upstream sources and transformations) and WHAT depends on it downstream
(which dashboards, models, or other tables would break if this one
changed or broke). This answers two different but related questions:
"if I change this column, what might I break?" (forward/downstream
lineage) and "why does this number look wrong — where did it actually
come from?" (backward/upstream lineage, essential for root-causing a
data quality incident quickly).

PIPELINE OBSERVABILITY (distinct from data QUALITY, though related)
means monitoring the PIPELINES THEMSELVES: are they running on schedule,
how long do they take (and is that changing over time — a slow creep in
runtime is often an early warning sign before an outright failure),
and freshness (how stale is the data right now relative to when it
should have last updated) — this is the data-pipeline-specific analogue
of the general observability principles covered in this repo's
Observability Notes domain (metrics/logs/traces), applied specifically to
data freshness/volume/schema rather than application request latency.

PRODUCTION USE CASE:
A pipeline's row count check flags that today's load brought in 40% fewer
rows than the trailing 7-day average — before anyone notices a downstream
dashboard looking "a bit low," the automated check fires an alert,
someone investigates, and discovers a source API silently changed its
pagination behavior, causing most rows to be missed on extraction. The
pipeline itself never threw an exception — the DATA QUALITY check is what
caught a real, otherwise-silent problem.

COMMON MISTAKES:
- Only testing for TECHNICAL success (task didn't fail, no exception
  thrown) and never testing the DATA ITSELF — this misses the entire
  class of "ran fine, produced garbage" failures, which are often more
  damaging than an outright crash because nobody's alerted to investigate.
- Writing data quality checks that are too rigid for natural variance
  (e.g. failing on ANY row-count difference from yesterday) instead of a
  reasonable statistical bound (e.g. flag if outside 3 standard
  deviations from the trailing average) — over-rigid checks train people
  to ignore alerts, which defeats the entire purpose.
- Having lineage information that lives only in people's heads or a
  stale wiki diagram instead of being derived automatically from the
  actual pipeline/transformation code — manually-maintained lineage
  documentation drifts out of sync with reality almost immediately.
"""

import statistics
from dataclasses import dataclass


# ------------------------------------------------------------------
# 1. Data quality assertions — Great Expectations-style
# ------------------------------------------------------------------
@dataclass
class ExpectationResult:
    expectation: str
    passed: bool
    detail: str


def expect_column_values_not_null(rows: list[dict], column: str) -> ExpectationResult:
    null_count = sum(1 for r in rows if r.get(column) is None)
    passed = null_count == 0
    return ExpectationResult(
        f"expect_column_values_to_not_be_null({column})",
        passed,
        f"{null_count} null value(s) found" if not passed else "all values present",
    )


def expect_column_values_in_range(rows: list[dict], column: str,
                                     min_val: float, max_val: float) -> ExpectationResult:
    violations = [r[column] for r in rows if not (min_val <= r.get(column, min_val) <= max_val)]
    passed = len(violations) == 0
    return ExpectationResult(
        f"expect_column_values_to_be_between({column}, {min_val}, {max_val})",
        passed,
        f"{len(violations)} value(s) out of range: {violations[:5]}" if not passed else "all in range",
    )


def expect_row_count_within_bounds(current_count: int, historical_counts: list[int],
                                      std_devs: float = 3.0) -> ExpectationResult:
    """
    A STATISTICAL bound rather than an exact-match check — this is the
    difference between a check that survives normal day-to-day variance
    and one that trains everyone to ignore alerts because it fires
    constantly on harmless fluctuation.
    """
    mean = statistics.mean(historical_counts)
    stdev = statistics.stdev(historical_counts) if len(historical_counts) > 1 else 0
    lower_bound = mean - std_devs * stdev
    upper_bound = mean + std_devs * stdev
    passed = lower_bound <= current_count <= upper_bound
    return ExpectationResult(
        "expect_row_count_within_historical_bounds",
        passed,
        f"count={current_count}, expected range=[{lower_bound:.0f}, {upper_bound:.0f}] "
        f"(based on {len(historical_counts)}-day trailing average)",
    )


# ------------------------------------------------------------------
# 2. dbt-style tests — the SQL-native equivalent
# ------------------------------------------------------------------
DBT_TEST_EXAMPLE = """
# dbt schema.yml — declarative tests attached directly to model columns
models:
  - name: orders
    columns:
      - name: order_id
        tests:
          - unique                 # no duplicate order_ids
          - not_null                # every row must have one
      - name: customer_id
        tests:
          - not_null
          - relationships:          # referential integrity check
              to: ref('customers')
              field: customer_id
      - name: amount_usd
        tests:
          - dbt_utils.accepted_range:   # a common third-party dbt-utils test
              min_value: 0
              max_value: 1000000

# `dbt test` runs ALL of these automatically as part of the pipeline,
# failing the run (or just warning, depending on severity config) if any
# assertion fails — tests live NEXT TO the transformation logic they
# validate, not in a separate, easily-forgotten location.
"""

# ------------------------------------------------------------------
# 3. Data lineage — a minimal lineage graph
# ------------------------------------------------------------------
@dataclass
class LineageNode:
    name: str
    upstream: list[str]


LINEAGE_GRAPH = {
    "raw.orders": LineageNode("raw.orders", upstream=[]),
    "silver.orders_cleaned": LineageNode("silver.orders_cleaned", upstream=["raw.orders"]),
    "gold.daily_revenue": LineageNode("gold.daily_revenue", upstream=["silver.orders_cleaned"]),
    "dashboard.executive_summary": LineageNode("dashboard.executive_summary", upstream=["gold.daily_revenue"]),
}


def find_downstream_impact(graph: dict[str, LineageNode], changed_node: str) -> list[str]:
    """
    Answers 'if I change/break this table, what else is affected' — the
    forward-lineage question you need answered BEFORE making a change,
    not discovered afterward when a dashboard breaks.
    """
    impacted = []
    for name, node in graph.items():
        if changed_node in node.upstream or any(
            changed_node in graph[u].upstream for u in node.upstream if u in graph
        ):
            impacted.append(name)
    return impacted


def find_upstream_lineage(graph: dict[str, LineageNode], node_name: str, visited=None) -> list[str]:
    """Answers 'where did this data actually come from' — root-causing a
    data quality incident by walking backward through the lineage graph."""
    if visited is None:
        visited = set()
    if node_name not in graph or node_name in visited:
        return []
    visited.add(node_name)
    upstream = graph[node_name].upstream
    result = list(upstream)
    for u in upstream:
        result.extend(find_upstream_lineage(graph, u, visited))
    return result


# ------------------------------------------------------------------
# 4. Pipeline observability — freshness and runtime trend monitoring
# ------------------------------------------------------------------
def check_data_freshness(last_updated_minutes_ago: float, sla_minutes: float) -> ExpectationResult:
    passed = last_updated_minutes_ago <= sla_minutes
    return ExpectationResult(
        "expect_data_freshness_within_sla",
        passed,
        f"last updated {last_updated_minutes_ago:.0f} min ago (SLA: {sla_minutes} min)",
    )


def detect_runtime_trend(historical_runtimes_seconds: list[float]) -> str:
    """A slow, steady creep in pipeline runtime is often an early warning
    sign of a growing data volume or a degrading query plan — worth
    surfacing as its own signal, separate from outright pipeline failure."""
    if len(historical_runtimes_seconds) < 5:
        return "insufficient history"
    recent_avg = statistics.mean(historical_runtimes_seconds[-3:])
    older_avg = statistics.mean(historical_runtimes_seconds[:-3])
    if recent_avg > older_avg * 1.5:
        return f"WARNING: runtime trending up ({older_avg:.0f}s -> {recent_avg:.0f}s)"
    return "runtime stable"


if __name__ == "__main__":
    rows = [
        {"order_id": "o1", "amount_usd": 25.99},
        {"order_id": "o2", "amount_usd": -5.00},   # a violation
        {"order_id": None, "amount_usd": 10.00},    # a violation
    ]
    print(expect_column_values_not_null(rows, "order_id"))
    print(expect_column_values_in_range(rows, "amount_usd", 0, 100000))
    print(expect_row_count_within_bounds(current_count=3000, historical_counts=[5000, 5200, 4900, 5100, 5050]))

    print("\n--- Lineage ---")
    print("Downstream impact of changing raw.orders:", find_downstream_impact(LINEAGE_GRAPH, "raw.orders"))
    print("Upstream lineage of dashboard.executive_summary:",
          find_upstream_lineage(LINEAGE_GRAPH, "dashboard.executive_summary"))

    print("\n--- Observability ---")
    print(check_data_freshness(last_updated_minutes_ago=45, sla_minutes=60))
    print(detect_runtime_trend([120, 118, 125, 130, 180, 210]))

"""
PRODUCTION CONTEXT EXAMPLE:
A pipeline's row-count check (using a statistical bound, not an exact
match) fires when a source API's pagination silently breaks and only 60%
of expected rows load — the on-call engineer uses the lineage graph to
identify the 4 downstream dashboards and 1 ML feature pipeline affected,
scopes the incident's blast radius in minutes instead of manually tracing
dependencies, and the automated freshness check on the ML feature table
independently confirms it's now stale, triggering a hold on that day's
model predictions until the data is corrected and reprocessed.
"""
