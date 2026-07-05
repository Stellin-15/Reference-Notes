# ============================================================
# L04: Production Airflow — TaskFlow, Dynamic Mapping, Backfills, SLAs
# ============================================================
# WHAT: The modern TaskFlow API (decorator-based DAG authoring), dynamic
#       task mapping (generating tasks at runtime from a variable-length
#       list), backfilling historical runs correctly, SLA/alerting
#       configuration, and the managed deployment landscape (MWAA,
#       Cloud Composer, Astronomer).
# WHY: L03 covered Airflow's execution model; this lesson covers what
#      separates a demo DAG from one that survives real production
#      operation — variable workloads, historical reprocessing, and
#      being told promptly when something's late or broken.
# LEVEL: Intermediate/Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
The TASKFLOW API (`@dag`/`@task` decorators, Airflow 2.0+) lets you write
DAGs as plain Python functions with automatic XCom wiring — calling one
`@task`-decorated function with the return value of another automatically
creates the dependency AND passes the XCom, eliminating the manual
`>>`/`xcom_pull` boilerplate from L03's classic-operator style. This is
now the RECOMMENDED way to author most DAGs.

DYNAMIC TASK MAPPING solves "I don't know how many tasks I need until
runtime" — e.g. processing one file per item in a list whose length
varies per run. `.expand()` creates one task instance PER ELEMENT of an
input list at runtime, each independently retriable and visible in the
UI, rather than a single task looping internally (which loses per-item
retry granularity and observability).

BACKFILLING is re-running a DAG for HISTORICAL date ranges — e.g. a new
DAG needs to process the last 90 days, or a bug fix needs to reprocess
a specific past week. Airflow's `catchup` parameter and the `airflow dags
backfill` CLI command exist specifically for this — critically, a
DAG must be designed so that its logic for a given `execution_date` is
DETERMINISTIC and doesn't implicitly depend on "now" (e.g. querying
"yesterday" via `datetime.now() - 1 day` instead of using the templated
`{{ ds }}` breaks backfilling, because every backfilled run would
compute the SAME "yesterday" relative to real wall-clock time instead of
its own historical date).

SLAs (Service Level Agreements) let you declare "this task should finish
within N minutes of its scheduled start" — Airflow tracks this and can
trigger alerts (email, Slack via callback) when a task blows past its SLA,
independent of whether the task actually failed (a task that succeeds but
takes 3x longer than usual is often an early signal of a problem, not
something to only notice via an outright failure).

PRODUCTION USE CASE:
Managed Airflow (AWS MWAA, GCP Cloud Composer, Astronomer) exists because
self-hosting Airflow's metadata database, scheduler HA, and worker
infrastructure is real operational overhead most data teams would rather
not own — these platforms handle the underlying infrastructure while you
focus on DAG authoring, at the cost of vendor-specific configuration
quirks (plugin installation, networking to VPC resources) worth knowing
about before choosing one.

COMMON MISTAKES:
- Writing DAG logic that depends on `datetime.now()` instead of the
  run's templated logical date — this makes backfills produce WRONG
  results (every backfilled run computes "today" as the actual current
  date, not its intended historical date).
- Using dynamic task mapping over an unbounded or very large list without
  a cap — thousands of mapped task instances can overwhelm the scheduler
  and metadata database; batch large lists into a bounded number of
  mapped tasks instead of one-task-per-item at extreme scale.
- Setting SLAs on every single task uniformly without considering normal
  variance — overly tight SLAs on tasks with naturally variable runtime
  (e.g. depending on source data volume) generate alert fatigue that
  causes real alerts to be ignored.
"""

import textwrap


# ------------------------------------------------------------------
# 1. TaskFlow API — the modern, decorator-based DAG style
# ------------------------------------------------------------------
TASKFLOW_EXAMPLE = textwrap.dedent("""\
    from airflow.decorators import dag, task
    from datetime import datetime

    @dag(
        schedule="@daily",
        start_date=datetime(2026, 1, 1),
        catchup=False,
    )
    def daily_orders_pipeline():

        @task
        def extract(ds=None) -> str:
            # `ds` is automatically injected by Airflow as the run's
            # LOGICAL date (templated) — NOT datetime.now(). Using this
            # instead of wall-clock time is what makes backfills correct.
            return f"s3://raw/orders/{ds}/orders.csv"

        @task
        def transform(raw_path: str) -> str:
            # Calling transform(extract()) below automatically creates
            # the dependency AND wires the XCom — no manual >> or
            # xcom_pull needed, unlike L03's classic-operator style.
            output_path = raw_path.replace("raw", "transformed").replace(".csv", ".parquet")
            # ... actual transformation logic ...
            return output_path

        @task
        def load(transformed_path: str):
            # ... load transformed_path into the warehouse ...
            print(f"Loaded {transformed_path}")

        load(transform(extract()))

    daily_orders_pipeline()
""")

# ------------------------------------------------------------------
# 2. Dynamic task mapping — one task per runtime-determined item
# ------------------------------------------------------------------
DYNAMIC_MAPPING_EXAMPLE = textwrap.dedent("""\
    from airflow.decorators import dag, task
    from datetime import datetime

    @dag(schedule="@daily", start_date=datetime(2026, 1, 1), catchup=False)
    def process_regional_files():

        @task
        def list_regions_with_data(ds=None) -> list[str]:
            # The number of regions with data TODAY varies run to run —
            # this is exactly the "don't know the task count until
            # runtime" scenario dynamic mapping solves.
            return discover_regions_with_new_data(ds)

        @task
        def process_region(region: str, ds=None):
            # This function's BODY is written for ONE region — .expand()
            # below creates one INDEPENDENT task instance per region,
            # each separately visible/retriable in the Airflow UI.
            process_region_file(region, ds)

        # .expand() is the dynamic task mapping call: creates N task
        # instances at runtime, N = len(list_regions_with_data()'s result).
        process_region.expand(region=list_regions_with_data())

    process_regional_files()
""")

# ------------------------------------------------------------------
# 3. Backfilling correctly — deterministic logical-date usage
# ------------------------------------------------------------------
def wrong_backfill_unsafe_task(execution_date_ignored: str) -> str:
    """WRONG: uses wall-clock 'now' instead of the run's logical date —
    every backfilled run for ANY historical date would compute the SAME
    'yesterday' relative to when the backfill actually executes, not the
    date it's supposed to represent."""
    from datetime import datetime, timedelta
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return f"s3://raw/orders/{yesterday}/orders.csv"   # BUG: ignores its own logical date


def correct_backfill_safe_task(logical_date: str) -> str:
    """CORRECT: uses the run's own logical/execution date, passed in
    (in real Airflow, via the templated `ds` value) — backfilling for
    2026-01-01 through 2026-03-31 correctly produces 90 DIFFERENT paths,
    one per historical date, regardless of when the backfill actually runs."""
    return f"s3://raw/orders/{logical_date}/orders.csv"


BACKFILL_CLI_EXAMPLE = (
    "airflow dags backfill daily_orders_pipeline "
    "--start-date 2026-01-01 --end-date 2026-03-31\n"
    "# Runs the DAG once for EACH day in the range, each with its own\n"
    "# correct logical date — assuming the DAG's tasks are written the\n"
    "# deterministic way shown in correct_backfill_safe_task() above."
)

# ------------------------------------------------------------------
# 4. SLAs and alerting
# ------------------------------------------------------------------
SLA_CONFIG_EXAMPLE = textwrap.dedent("""\
    from datetime import timedelta

    @task(sla=timedelta(minutes=30))
    def load_to_snowflake():
        # If this task hasn't COMPLETED within 30 minutes of the DAG
        # run's scheduled start, Airflow fires an SLA-miss callback —
        # independent of whether the task eventually succeeds. This
        # catches "still running, just slower than usual" as an early
        # signal, not only outright task failures.
        ...

    def sla_miss_callback(dag, task_list, blocking_task_list, slas, blocking_tis):
        send_slack_alert(f"SLA missed for tasks: {task_list}")

    # Registered at the DAG level:
    # @dag(..., sla_miss_callback=sla_miss_callback)
""")

# ------------------------------------------------------------------
# 5. Managed Airflow deployment landscape
# ------------------------------------------------------------------
MANAGED_AIRFLOW_COMPARISON = {
    "AWS MWAA (Managed Workflows for Apache Airflow)": "Fully managed, "
        "runs in your VPC, integrates natively with AWS IAM/S3/other AWS "
        "services — the natural choice if the rest of your stack is AWS.",
    "GCP Cloud Composer": "Built on GKE (Kubernetes) under the hood, "
        "integrates with GCP's IAM/Cloud Storage/BigQuery — the GCP-native "
        "equivalent choice.",
    "Astronomer": "A dedicated Airflow-as-a-service company/platform, "
        "cloud-agnostic — often chosen when you want deep Airflow-specific "
        "tooling/support without being tied to one cloud's ecosystem.",
    "Self-hosted (Helm chart on your own Kubernetes)": "Full control, "
        "no vendor markup, but you own scheduler HA, metadata database "
        "backups/scaling, and upgrade cadence entirely yourself.",
}


if __name__ == "__main__":
    print(TASKFLOW_EXAMPLE)
    print("=" * 60)
    print(DYNAMIC_MAPPING_EXAMPLE[:600], "...\n")

    print("Backfill correctness demo:")
    print("  wrong (ignores logical_date):", wrong_backfill_unsafe_task("2026-01-01"))
    print("  correct (uses logical_date): ", correct_backfill_safe_task("2026-01-01"))
    print("  correct (uses logical_date): ", correct_backfill_safe_task("2026-02-15"))

    print(f"\n{BACKFILL_CLI_EXAMPLE}")
    print(SLA_CONFIG_EXAMPLE)

    print("Managed Airflow options:")
    for platform, note in MANAGED_AIRFLOW_COMPARISON.items():
        print(f"  {platform}: {note}")

"""
PRODUCTION CONTEXT EXAMPLE:
A data team discovers a transformation bug that's been silently
mis-calculating a revenue field for the past 60 days. Because their DAG
was written deterministically (using `{{ ds }}` throughout, never
`datetime.now()`), they fix the bug and run `airflow dags backfill
--start-date <60 days ago> --end-date today`, correctly regenerating
every historical day's output with the fix applied — a DAG that had used
wall-clock time internally would make this kind of retroactive correction
impossible to do correctly via backfill alone.
"""
