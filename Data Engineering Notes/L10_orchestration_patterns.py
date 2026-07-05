# ============================================================
# L10: Choosing an Orchestrator — Airflow vs ADF vs Databricks Workflows vs Dagster/Prefect
# ============================================================
# WHAT: A direct, practical comparison of the major orchestration tools
#       covered so far (Airflow, Databricks Workflows, Azure Data
#       Factory) plus two more modern alternatives (Dagster, Prefect),
#       and a framework for choosing between them — plus how they
#       compose when a real organization uses more than one.
# WHY: Every prior lesson taught ONE tool in isolation. Real
#      organizations often run MULTIPLE orchestrators simultaneously
#      (e.g. Airflow for cross-system coordination, Databricks Workflows
#      for pipelines entirely within Databricks) — knowing when to reach
#      for which, and how they hand off to each other, is a genuine
#      architectural decision, not just tool trivia.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
All of these tools solve the SAME core problem (define a DAG of
dependent tasks, schedule/trigger it, retry failures, alert on
problems) — they differ in AUTHORING MODEL, ECOSYSTEM INTEGRATION, and
EXECUTION LOCALITY:

- AIRFLOW: Python-code-first, huge open-source provider ecosystem
  (hundreds of pre-built operators for external systems), cloud-agnostic
  — the default choice for CROSS-SYSTEM orchestration (touching many
  different tools/clouds from one place).
- AZURE DATA FACTORY: Visual-designer-first (JSON underneath), deeply
  integrated with the Azure ecosystem — the natural choice when your
  stack is Azure-centric and/or your team prefers low-code pipeline
  authoring.
- DATABRICKS WORKFLOWS: Native to Databricks, zero extra infrastructure
  if you're already running Databricks — the natural choice for
  orchestration ENTIRELY within Databricks (notebooks, DLT pipelines,
  Databricks SQL), less suited to orchestrating systems outside Databricks.
- DAGSTER: Python-code-first like Airflow, but built around explicit
  SOFTWARE-DEFINED ASSETS (you declare the DATA ASSETS a pipeline
  produces, not just the tasks that run) — gives stronger data lineage
  and testability out of the box, at the cost of a steeper conceptual
  model than Airflow's simpler "just tasks" approach.
- PREFECT: Python-code-first, emphasizes a more "just decorate your
  existing Python functions" DEVELOPER EXPERIENCE than Airflow's more
  rigid DAG-definition model — often chosen by teams who find Airflow's
  authoring model heavier than they need, especially for smaller/simpler
  pipeline fleets.

PRODUCTION USE CASE:
A real mid-size data platform commonly runs Airflow as the TOP-LEVEL
orchestrator (kicking off and sequencing work across Snowflake, an
external vendor API, and Databricks) while Databricks Workflows/DLT
pipelines handle orchestration ENTIRELY WITHIN Databricks for
transformation-heavy stages — Airflow triggers a Databricks job via the
`DatabricksSubmitRunOperator` and waits for its completion before
proceeding to the next cross-system step, rather than trying to force
one tool to do everything.

COMMON MISTAKES:
- Picking an orchestrator based on "what's most popular" rather than
  what matches your team's authoring preference (code vs visual) and
  ecosystem needs (cross-system vs single-platform) — Airflow's
  popularity doesn't make it the right choice for a team fully committed
  to Databricks with no cross-system orchestration needs.
- Trying to force ONE orchestrator to do everything when a natural
  boundary exists — e.g. reimplementing Databricks-native DLT pipeline
  logic as a long chain of individual Airflow tasks instead of letting
  Airflow simply TRIGGER the DLT pipeline as one step and move on.
- Underestimating the migration cost of switching orchestrators later —
  hundreds of existing DAGs represent real sunk engineering investment;
  "the new tool is slightly nicer" is rarely sufficient justification for
  a full migration once a platform has meaningful production DAG count.
"""

from dataclasses import dataclass


# ------------------------------------------------------------------
# 1. Comparison matrix
# ------------------------------------------------------------------
@dataclass
class OrchestratorProfile:
    name: str
    authoring_model: str
    best_fit: str
    weaker_fit: str


ORCHESTRATOR_PROFILES = [
    OrchestratorProfile(
        "Apache Airflow",
        "Python code (classic operators or TaskFlow API)",
        "Cross-system orchestration; huge ecosystem of pre-built provider "
        "operators; cloud-agnostic teams",
        "Very simple, single-platform pipelines where its authoring "
        "overhead isn't repaid",
    ),
    OrchestratorProfile(
        "Azure Data Factory",
        "Visual designer (JSON underneath)",
        "Azure-centric organizations; teams preferring low-code authoring; "
        "on-prem-to-Azure data movement (via Self-Hosted IR)",
        "Complex branching logic that becomes unreadable as a visual "
        "graph; non-Azure-centric stacks",
    ),
    OrchestratorProfile(
        "Databricks Workflows / DLT",
        "Notebook/task-based (Workflows) or declarative decorators (DLT)",
        "Orchestration entirely WITHIN Databricks; teams already "
        "Spark-centric; wanting built-in data quality enforcement (DLT)",
        "Orchestrating systems outside Databricks without an external "
        "coordinator",
    ),
    OrchestratorProfile(
        "Dagster",
        "Python code, asset-centric (software-defined assets)",
        "Teams wanting strong data lineage/testability built into the "
        "orchestration layer itself, not bolted on separately",
        "Teams wanting the simplest possible mental model — the "
        "asset-centric abstraction is a real additional concept to learn",
    ),
    OrchestratorProfile(
        "Prefect",
        "Python code, decorator-based ('just decorate your functions')",
        "Teams who find Airflow's DAG-authoring model heavier than "
        "needed; smaller pipeline fleets; rapid iteration",
        "Very large-scale deployments where Airflow's ecosystem maturity "
        "and provider library breadth matter more than authoring ergonomics",
    ),
]


def print_comparison():
    for p in ORCHESTRATOR_PROFILES:
        print(f"{p.name}")
        print(f"  authoring: {p.authoring_model}")
        print(f"  best fit:  {p.best_fit}")
        print(f"  weaker fit: {p.weaker_fit}\n")


# ------------------------------------------------------------------
# 2. Cross-tool handoff — Airflow triggering a Databricks job
# ------------------------------------------------------------------
import textwrap

CROSS_TOOL_HANDOFF_EXAMPLE = textwrap.dedent("""\
    from airflow.providers.databricks.operators.databricks import DatabricksSubmitRunOperator

    with DAG(dag_id="cross_system_pipeline", schedule="@daily", ...) as dag:

        fetch_from_vendor_api = PythonOperator(
            task_id="fetch_vendor_data",
            python_callable=fetch_and_stage_vendor_data,
        )

        # Airflow TRIGGERS a Databricks job and WAITS for its completion —
        # the actual transformation logic lives natively in Databricks
        # (potentially as a DLT pipeline, L06), while Airflow's job is
        # purely to sequence "vendor data staged" -> "Databricks
        # transforms it" -> "next cross-system step."
        run_databricks_transform = DatabricksSubmitRunOperator(
            task_id="run_databricks_transform",
            databricks_conn_id="databricks_default",
            existing_cluster_id="{{ var.value.etl_cluster_id }}",
            notebook_task={"notebook_path": "/pipelines/transform_orders"},
        )

        load_to_snowflake = SnowflakeOperator(
            task_id="load_to_snowflake",
            sql="COPY INTO analytics.orders FROM @databricks_output_stage",
        )

        fetch_from_vendor_api >> run_databricks_transform >> load_to_snowflake

    # Airflow never reimplements the Databricks transformation logic — it
    # just orchestrates WHEN each system's own native capability runs,
    # relative to the others.
""")

# ------------------------------------------------------------------
# 3. A decision framework
# ------------------------------------------------------------------
DECISION_QUESTIONS = [
    "Does this pipeline touch MULTIPLE distinct platforms/clouds, or "
    "does it live entirely within one platform (e.g. entirely Databricks, "
    "entirely Snowflake)? Multi-platform favors a general orchestrator "
    "(Airflow/Dagster/Prefect); single-platform favors that platform's "
    "native orchestrator (Databricks Workflows, Snowflake Tasks from L08).",
    "Does the team prefer writing Python code, or a visual/low-code "
    "authoring experience? This alone often rules out ADF (visual-first) "
    "or the Python-code tools, respectively.",
    "Do you need strong, built-in data LINEAGE and asset-level testing as "
    "a first-class orchestration concept, not bolted on separately? "
    "This favors Dagster's asset-centric model specifically.",
    "Is your organization already deeply invested in one cloud "
    "(Azure/AWS/GCP)? Native integration depth (ADF for Azure, Airflow's "
    "AWS provider maturity, etc.) is a real, practical factor.",
    "How large is your EXISTING pipeline fleet, if any? Migration cost is "
    "real and often underestimated — a marginal ergonomics improvement "
    "rarely justifies rewriting hundreds of production DAGs.",
]


if __name__ == "__main__":
    print_comparison()
    print(CROSS_TOOL_HANDOFF_EXAMPLE)
    print("Decision framework questions:")
    for i, q in enumerate(DECISION_QUESTIONS, 1):
        print(f"  {i}. {q}")

"""
PRODUCTION CONTEXT EXAMPLE:
A fintech company runs Airflow as its top-level orchestrator (coordinating
data flowing from 6 different vendor APIs, a Snowflake warehouse, and a
Databricks workspace used for ML feature engineering), while the
Databricks-internal feature engineering pipeline itself is defined as a
Databricks Workflow with DLT-managed data quality checks — Airflow
triggers that Workflow and waits for completion, but has no visibility
into (and doesn't need to reimplement) the DLT pipeline's internal
task graph. This layered approach — a general orchestrator for
cross-system sequencing, native orchestration for within-platform work
— is the realistic production pattern most organizations converge on.
"""
