# ============================================================
# L03: Apache Airflow Fundamentals — DAGs, Operators, Scheduling
# ============================================================
# WHAT: Airflow's core abstractions — DAGs (Directed Acyclic Graphs of
#       tasks), operators, the scheduler/executor model, XComs for
#       passing data between tasks, and sensors for waiting on external
#       conditions.
# WHY: Airflow is the most widely deployed open-source orchestrator —
#      understanding its execution model (which is genuinely different
#      from "just run a cron job") is the foundation for everything in
#      L04 (production Airflow) and for comparing it against
#      Databricks Workflows/ADF/Dagster/Prefect in L10.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
A DAG (Directed Acyclic Graph) is a collection of TASKS with defined
UPSTREAM/DOWNSTREAM dependencies — "acyclic" means no task can depend on
itself, directly or transitively (no cycles), which is what makes a
well-defined execution order possible at all. Airflow's scheduler
periodically evaluates every DAG's schedule and creates a DAG RUN — one
concrete execution instance — when a scheduled interval is due.

An OPERATOR defines WHAT a single task actually does (run a Python
function, execute a SQL statement, call an API, run a Bash command).
Airflow ships dozens of operators, and the provider ecosystem
(`apache-airflow-providers-*`) adds hundreds more for specific systems
(Snowflake, Databricks, AWS, GCP, etc.) — writing custom pipeline logic
inside a raw `PythonOperator` is common, but reaching for an existing
provider operator is usually less code and more battle-tested for
talking to a specific external system.

The SCHEDULER continuously parses DAG files, decides when runs are due,
and hands ready tasks to the EXECUTOR, which actually runs them
(LocalExecutor runs tasks as local processes; CeleryExecutor/
KubernetesExecutor distribute tasks across a worker fleet — the choice
affects scalability, not DAG-authoring code).

XCOM ("cross-communication") is Airflow's mechanism for passing SMALL
pieces of data between tasks — a task pushes a value, a downstream task
pulls it. XComs are stored in Airflow's metadata database and are NOT
meant for large data (passing a multi-GB DataFrame via XCom is a classic
anti-pattern — pass a REFERENCE, like an S3 path, instead).

A SENSOR is a special operator that WAITS for a condition to become true
(a file to appear, an external DAG to finish, a database row to exist)
before allowing downstream tasks to proceed — critical for pipelines that
depend on external systems' timing, not just Airflow's own schedule.

PRODUCTION USE CASE:
A daily ETL DAG: a `S3KeySensor` waits for the day's raw file to land,
a `PythonOperator` validates/transforms it, a `SnowflakeOperator` loads
the result, and a final task sends a Slack notification — five tasks
with a clear dependency chain, each independently retriable, each with
its own logs, exactly the operational visibility a raw cron job lacks.

COMMON MISTAKES:
- Passing large datasets through XCom instead of writing to
  intermediate storage (S3/a table) and passing just the location —
  XCom's backing metadata database is not built for large payloads and
  this will eventually cause real performance/reliability problems.
- Writing DAG files with expensive top-level Python code (e.g. a
  database query executed at MODULE IMPORT time, outside any task) — the
  scheduler re-PARSES every DAG file on a short interval, so slow
  top-level code directly slows down the entire scheduler.
- Using sensors in "poke" mode (which occupies a worker slot the entire
  time it's waiting) for long waits, instead of "reschedule" mode (which
  frees the worker slot between checks) — a common cause of worker-pool
  exhaustion in DAGs with many long-running sensors.
"""

import textwrap
from datetime import datetime, timedelta


# ------------------------------------------------------------------
# 1. A minimal, real, runnable Airflow DAG
# ------------------------------------------------------------------
AIRFLOW_DAG_EXAMPLE = textwrap.dedent("""\
    from airflow import DAG
    from airflow.operators.python import PythonOperator
    from airflow.providers.amazon.aws.sensors.s3 import S3KeySensor
    from airflow.providers.snowflake.operators.snowflake import SnowflakeOperator
    from datetime import datetime, timedelta

    default_args = {
        "owner": "data-eng",
        "retries": 3,
        "retry_delay": timedelta(minutes=5),
    }

    with DAG(
        dag_id="daily_orders_pipeline",
        schedule="0 6 * * *",       # cron: every day at 06:00
        start_date=datetime(2026, 1, 1),
        catchup=False,               # don't backfill every day since start_date
        default_args=default_args,
        tags=["orders", "daily"],
    ) as dag:

        # SENSOR: waits for the day's raw file to land in S3 before
        # proceeding — "reschedule" mode frees the worker slot between
        # checks instead of blocking it the whole wait duration.
        wait_for_file = S3KeySensor(
            task_id="wait_for_raw_orders_file",
            bucket_name="raw-data-landing",
            bucket_key="orders/{{ ds }}/orders.csv",  # {{ ds }} = the run's date, templated
            mode="reschedule",
            poke_interval=60,
            timeout=60 * 60 * 4,   # give up after 4 hours
        )

        def validate_and_transform(**context):
            # Real transformation logic would run here. Returning a value
            # from a PythonOperator's callable automatically pushes it to
            # XCom for downstream tasks to pull.
            s3_path = f"s3://raw-data-landing/orders/{context['ds']}/orders.csv"
            # ... validate schema, run transformation ...
            output_path = f"s3://transformed/orders/{context['ds']}/orders.parquet"
            return output_path   # small string -> XCom is the RIGHT use case

        transform = PythonOperator(
            task_id="validate_and_transform",
            python_callable=validate_and_transform,
        )

        load_to_snowflake = SnowflakeOperator(
            task_id="load_to_snowflake",
            snowflake_conn_id="snowflake_default",
            sql=\"\"\"
                COPY INTO analytics.orders
                FROM '{{ ti.xcom_pull(task_ids="validate_and_transform") }}'
                FILE_FORMAT = (TYPE = PARQUET)
            \"\"\",
        )

        # Dependency chain: sensor -> transform -> load. The >> operator
        # is Airflow's DSL for "downstream of" — this single line defines
        # the DAG's entire execution order.
        wait_for_file >> transform >> load_to_snowflake
""")

# ------------------------------------------------------------------
# 2. Operators — categories and when to use each
# ------------------------------------------------------------------
OPERATOR_CATEGORIES = {
    "Action operators": "Do work directly: PythonOperator, BashOperator, "
        "SnowflakeOperator, DatabricksSubmitRunOperator — the vast "
        "majority of real tasks.",
    "Transfer operators": "Move data between two systems: S3ToSnowflakeOperator, "
        "GCSToBigQueryOperator — encode a specific, common data-movement "
        "pattern as one reusable task.",
    "Sensors": "Wait for a condition: S3KeySensor, ExternalTaskSensor "
        "(waits for another DAG/task to finish), SqlSensor.",
    "Deferrable operators/sensors": "A newer Airflow capability — "
        "deferrable sensors release their worker slot ENTIRELY while "
        "waiting (using an async trigger mechanism), even more efficient "
        "than 'reschedule' mode for very long waits.",
}

# ------------------------------------------------------------------
# 3. Scheduler/executor model — what actually runs where
# ------------------------------------------------------------------
EXECUTOR_COMPARISON = {
    "SequentialExecutor": "Runs one task at a time, single process — "
        "development/testing only, never production.",
    "LocalExecutor": "Runs tasks as parallel local processes on the "
        "SAME machine as the scheduler — fine for small deployments, "
        "doesn't scale beyond one machine's resources.",
    "CeleryExecutor": "Distributes tasks across a fleet of Celery worker "
        "processes/machines via a message broker (Redis/RabbitMQ) — the "
        "traditional choice for horizontal scaling.",
    "KubernetesExecutor": "Launches EACH task as its own Kubernetes pod, "
        "with per-task resource isolation and no idle worker fleet to "
        "maintain — the modern default for cloud-native Airflow "
        "deployments (and what managed services like Cloud Composer/MWAA "
        "build on).",
}

# ------------------------------------------------------------------
# 4. XCom — correct vs incorrect usage
# ------------------------------------------------------------------
XCOM_GUIDANCE = textwrap.dedent("""\
    CORRECT: pushing a small value (a file path, a row count, a status
    string, a computed date) that a downstream task needs.

        def extract(**context):
            row_count = run_extraction()
            return row_count   # small int -> auto-pushed to XCom

        def notify(**context):
            count = context["ti"].xcom_pull(task_ids="extract")
            send_slack_message(f"Extracted {count} rows")

    INCORRECT: pushing an entire DataFrame or large JSON blob through
    XCom — this bloats Airflow's metadata database and can cause real
    performance degradation across the WHOLE Airflow instance, not just
    the one DAG doing it.

        def extract(**context):
            df = run_extraction()
            return df.to_dict()  # BAD — write to S3/a table instead and
                                   # push only the LOCATION as a string.
""")


if __name__ == "__main__":
    print(AIRFLOW_DAG_EXAMPLE[:800], "...\n")
    print("=== Operator categories ===")
    for cat, desc in OPERATOR_CATEGORIES.items():
        print(f"{cat}: {desc}\n")
    print("=== Executor comparison ===")
    for ex, desc in EXECUTOR_COMPARISON.items():
        print(f"{ex}: {desc}\n")
    print(XCOM_GUIDANCE)

"""
PRODUCTION CONTEXT EXAMPLE:
A data platform running 200+ DAGs on KubernetesExecutor gets per-task
resource isolation (a memory-hungry Spark-submit task doesn't starve a
lightweight notification task on the same worker) and automatic
scale-to-zero (no idle worker pods when nothing is running) — exactly
the operational property that makes Airflow viable at that scale versus
a fixed-size Celery worker fleet that must be provisioned for peak load
even during idle periods.
"""
