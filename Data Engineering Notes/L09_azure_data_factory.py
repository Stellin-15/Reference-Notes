# ============================================================
# L09: Azure Data Factory — Pipelines, Linked Services, Data Flows
# ============================================================
# WHAT: ADF's core building blocks — pipelines, linked services (
#       connection definitions), datasets, triggers, Mapping Data Flows
#       (ADF's visual, Spark-backed transformation engine), and
#       integration runtimes (where execution actually happens).
# WHY: ADF is Azure's native orchestration/ETL service — the direct
#      Azure-ecosystem equivalent of pieces of both Airflow (orchestration)
#      and Databricks (Data Flows run on managed Spark under the hood),
#      and it's frequently the default choice for organizations already
#      committed to Azure.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
A PIPELINE is ADF's unit of orchestration — a collection of ACTIVITIES
(individual steps: copy data, run a stored procedure, trigger a
Databricks notebook, run a Data Flow) connected by dependencies, directly
analogous to an Airflow DAG's tasks, but authored primarily through
ADF's visual designer (JSON underneath) rather than Python code.

A LINKED SERVICE defines HOW to connect to an external system (a
connection string, credentials, often via Azure Key Vault reference
rather than a plaintext secret) — conceptually equivalent to an Airflow
Connection. A DATASET defines WHAT specific data within that connected
system to read/write (a specific table, file path, or container) — the
dataset REFERENCES a linked service rather than duplicating its
connection details.

A TRIGGER determines WHEN a pipeline runs: a SCHEDULE trigger (cron-like,
recurring), a TUMBLING WINDOW trigger (fixed-size, non-overlapping time
windows with built-in dependency/retry semantics between consecutive
windows — useful for strictly sequential incremental processing), or an
EVENT trigger (fires when a file lands in Blob Storage, similar in spirit
to Airflow's S3KeySensor or Databricks' Auto Loader, but push-based rather
than poll-based).

MAPPING DATA FLOWS is ADF's visual data transformation designer — you
build a transformation graph (source -> filter -> join -> aggregate ->
sink) visually, and ADF compiles it down to run on a managed, ephemeral
Spark cluster under the hood. This is ADF's answer to "I need real
transformation logic, not just data movement," without requiring you to
write Spark code directly (though a Databricks Notebook activity remains
available within an ADF pipeline for when you DO want to write Spark/
Python code directly).

An INTEGRATION RUNTIME (IR) is the actual COMPUTE infrastructure that
executes activities. AZURE IR (fully managed, serverless, default choice)
runs in Microsoft's cloud. SELF-HOSTED IR runs on YOUR infrastructure
(on-premises or in a private VNet) — required when a pipeline needs to
reach data sources not reachable from the public internet (an on-prem
SQL Server behind a corporate firewall, for example).

PRODUCTION USE CASE:
An organization migrating on-premises SQL Server data into Azure Synapse
uses a Self-Hosted Integration Runtime (installed on a VM inside the
corporate network) to securely bridge ADF's cloud-based orchestration
with data that's never been exposed to the public internet — the Azure IR
alone could not reach that data source at all.

COMMON MISTAKES:
- Using a Self-Hosted IR for cloud-to-cloud data movement where the fully
  managed Azure IR would work fine — this adds unnecessary operational
  overhead (patching, scaling, monitoring a VM you now own) for no benefit.
- Storing connection credentials directly in a Linked Service definition
  instead of referencing Azure Key Vault — this scatters secrets across
  pipeline definitions instead of centralizing rotation/access control.
- Building complex, branching transformation logic entirely with the
  visual Data Flow designer past the point where it remains readable —
  at a certain complexity, a Databricks Notebook activity with actual
  code is often more maintainable than a very large visual data flow graph.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Pipeline, activity, linked service, dataset — the object model
# ------------------------------------------------------------------
ADF_OBJECT_MODEL = textwrap.dedent("""\
    // Linked Service — HOW to connect (references Key Vault, never a
    // plaintext secret in the definition itself)
    {
      "name": "AzureSqlLinkedService",
      "type": "AzureSqlDatabase",
      "typeProperties": {
        "connectionString": "Server=tcp:myserver.database.windows.net;Database=orders;",
        "password": {
          "type": "AzureKeyVaultSecret",
          "store": {"referenceName": "MyKeyVault", "type": "LinkedServiceReference"},
          "secretName": "sql-orders-password"
        }
      }
    }

    // Dataset — WHAT specific data, referencing the linked service above
    {
      "name": "OrdersTableDataset",
      "type": "AzureSqlTable",
      "linkedServiceName": {"referenceName": "AzureSqlLinkedService", "type": "LinkedServiceReference"},
      "typeProperties": {"tableName": "dbo.Orders"}
    }

    // Pipeline — activities and their dependencies, analogous to an
    // Airflow DAG's task graph
    {
      "name": "DailyOrdersPipeline",
      "activities": [
        {
          "name": "CopyOrdersToBlob",
          "type": "Copy",
          "inputs": [{"referenceName": "OrdersTableDataset", "type": "DatasetReference"}],
          "outputs": [{"referenceName": "OrdersBlobDataset", "type": "DatasetReference"}]
        },
        {
          "name": "TransformWithDataFlow",
          "type": "ExecuteDataFlow",
          "dependsOn": [{"activity": "CopyOrdersToBlob", "dependencyConditions": ["Succeeded"]}],
          "typeProperties": {"dataflow": {"referenceName": "OrdersTransformFlow", "type": "DataFlowReference"}}
        }
      ]
    }
""")

# ------------------------------------------------------------------
# 2. Triggers — schedule, tumbling window, event
# ------------------------------------------------------------------
TRIGGER_TYPES = {
    "Schedule trigger": "Cron-like recurring schedule — the direct "
        "equivalent of an Airflow DAG's `schedule` parameter.",
    "Tumbling window trigger": "Fixed-size, sequential, NON-OVERLAPPING "
        "time windows, with built-in dependency semantics between "
        "consecutive windows (window N+1 can be configured to wait for "
        "window N's success) and automatic retry per window — well-suited "
        "to strictly sequential incremental processing where order matters.",
    "Event-based trigger": "Fires in response to a Blob Storage event "
        "(a file created/deleted) — PUSH-based via Azure Event Grid, "
        "conceptually similar to Databricks Auto Loader's file-"
        "notification mechanism (L06) rather than a polling sensor "
        "(contrast with Airflow's S3KeySensor, L03, which polls).",
}

# ------------------------------------------------------------------
# 3. Mapping Data Flows — visual, Spark-backed transformation
# ------------------------------------------------------------------
DATA_FLOW_NOTE = textwrap.dedent("""\
    A Mapping Data Flow is authored visually (source -> derived column ->
    filter -> aggregate -> sink, connected as a graph) but COMPILES to
    run on a managed, ephemeral Spark cluster when the pipeline executes
    — you get Spark's distributed processing power without writing Spark
    code directly. Under the hood, ADF spins up a Data Flow-specific
    Integration Runtime (a temporary Spark cluster) for the duration of
    execution, then tears it down — directly analogous to Databricks'
    Job Cluster pattern (L06): pay only for the compute actually used.

    Debugging: ADF's "Data Flow Debug" mode keeps a small warm cluster
    running during interactive development so you can preview
    transformation results cell-by-cell without a full cold-start cluster
    spin-up on every test iteration — a real time-saver during authoring,
    but remember to turn debug mode OFF when not actively developing,
    since the debug cluster itself incurs cost while running.
""")

# ------------------------------------------------------------------
# 4. Integration Runtimes — where execution actually happens
# ------------------------------------------------------------------
IR_COMPARISON = {
    "Azure IR": "Fully managed, serverless, runs in Microsoft's cloud. "
        "The default choice — zero infrastructure to maintain.",
    "Self-Hosted IR": "Runs on YOUR infrastructure (on-prem or in a "
        "private VNet) — required when a pipeline needs to reach data "
        "sources not exposed to the public internet.",
    "Azure-SSIS IR": "A specialized IR for organizations migrating "
        "existing SQL Server Integration Services (SSIS) packages to "
        "Azure without needing a full rewrite — runs legacy SSIS "
        "packages within ADF's orchestration.",
}


if __name__ == "__main__":
    print(ADF_OBJECT_MODEL)
    print("=== Trigger types ===")
    for trigger, desc in TRIGGER_TYPES.items():
        print(f"{trigger}: {desc}\n")
    print(DATA_FLOW_NOTE)
    print("=== Integration Runtime comparison ===")
    for ir, desc in IR_COMPARISON.items():
        print(f"{ir}: {desc}")

"""
PRODUCTION CONTEXT EXAMPLE:
A healthcare organization's ADF pipeline uses a Self-Hosted Integration
Runtime (installed on a VM inside their private network) to extract data
from an on-premises Epic EHR database that's never been exposed to the
public internet, transforms it with a Mapping Data Flow (avoiding the
need for a separate Databricks workspace purely for this transformation),
and lands the result in Azure Synapse — with an event-based trigger
kicking off downstream reporting pipelines the moment the transformed
file lands, all orchestrated within one ADF pipeline without external
tooling.
"""
