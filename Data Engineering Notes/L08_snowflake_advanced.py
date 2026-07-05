# ============================================================
# L08: Advanced Snowflake — Streams & Tasks, Snowpark, Sharing, RBAC
# ============================================================
# WHAT: Streams & Tasks (Snowflake-native CDC and scheduled SQL
#       execution), Snowpark (running Python/Java/Scala directly inside
#       Snowflake's compute), Secure Data Sharing (zero-copy data sharing
#       between accounts), and role-based access control.
# WHY: L07 covered Snowflake's core architecture; this lesson covers the
#      features that let you build FULL pipelines and data products
#      natively inside Snowflake, without needing to move data out to
#      Airflow/Spark for every transformation or ingestion step.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
A STREAM tracks row-level CHANGES (inserts/updates/deletes) to a table
since the last time the stream was consumed — Snowflake's native
equivalent of the CDC concept from L02, but implemented internally rather
than via an external tool like Debezium. A TASK is a scheduled (or
triggered) unit of SQL execution — combining a Stream with a Task lets
you build an entirely SQL-native incremental pipeline: a Task runs on a
schedule, checks if its upstream Stream has new data, and if so,
processes just the changes — this is Snowflake's built-in alternative to
orchestrating incremental loads via an external tool like Airflow.

SNOWPARK lets you write Python (or Java/Scala) code that executes
DIRECTLY inside Snowflake's compute, operating on Snowflake DataFrames
that are lazily translated into SQL under the hood — this means Python-
based transformation logic runs where the data already lives, without
extracting it out to an external Python/Spark environment first (the
same "compute close to storage" principle behind ELT, L01, now available
for Python specifically, not just SQL).

SECURE DATA SHARING lets one Snowflake account grant another account
LIVE, READ-ONLY access to specific tables/views — WITHOUT copying any
data. The consuming account queries the SAME underlying storage the
provider account owns; there's no ETL, no data duplication, and updates
on the provider side are immediately visible to consumers. This is a
fundamentally different data-distribution model than "export a file and
send it" or building a dedicated API.

RBAC (Role-Based Access Control): Snowflake's permission model is
entirely role-based — permissions are granted to ROLES, and roles are
granted to USERS (or to other roles, forming a role hierarchy). A user's
EFFECTIVE permissions are the union of every role granted to them,
directly or through the hierarchy — designing a clean role hierarchy
(rather than granting permissions directly to individual users) is what
makes permission management maintainable at any real organizational scale.

PRODUCTION USE CASE:
A Stream+Task pipeline incrementally maintains a Silver-layer table:
whenever new rows land in a raw Bronze table, the Stream captures exactly
which rows changed, and a Task (scheduled every 5 minutes) processes only
those changed rows into the Silver table — a fully SQL-native incremental
pipeline requiring no external orchestrator for this specific
transformation step.

COMMON MISTAKES:
- Forgetting that consuming a Stream (querying it inside a Task's
  transaction) ADVANCES its offset — if the Task's transaction fails
  AFTER reading the Stream but before committing the write, the changes
  are correctly NOT lost (Snowflake only advances the stream offset on a
  successful transaction commit), but building custom Stream-consumption
  logic that doesn't respect this transactional boundary can lose changes.
- Building an entire external ETL pipeline to physically copy data
  between two Snowflake accounts owned by the same organization when
  Secure Data Sharing would provide live, zero-copy access with far less
  operational overhead and no data-freshness lag.
- Granting permissions directly to individual USERS instead of through
  ROLES — this doesn't scale, makes onboarding/offboarding error-prone,
  and makes it much harder to audit "what can this person actually access
  and why" months later.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Streams & Tasks — SQL-native incremental CDC pipelines
# ------------------------------------------------------------------
STREAMS_AND_TASKS_EXAMPLE = textwrap.dedent("""\
    -- A Stream tracks every change to raw.orders since it was last consumed.
    CREATE STREAM raw_orders_stream ON TABLE raw.orders;

    -- A Task runs on a schedule, processing only what the Stream reports
    -- as changed since the last successful run.
    CREATE TASK process_order_changes
      WAREHOUSE = etl_warehouse
      SCHEDULE = '5 MINUTE'
    AS
      MERGE INTO analytics.orders AS target
      USING raw_orders_stream AS source
      ON target.order_id = source.order_id
      WHEN MATCHED AND source.METADATA$ACTION = 'DELETE' THEN DELETE
      WHEN MATCHED THEN UPDATE SET total_usd = source.total_usd
      WHEN NOT MATCHED AND source.METADATA$ACTION = 'INSERT' THEN
        INSERT (order_id, total_usd) VALUES (source.order_id, source.total_usd);

    -- METADATA$ACTION on a stream row tells you whether it was an
    -- INSERT, UPDATE, or DELETE at the source — the Stream's built-in
    -- equivalent of the ChangeEvent.change_type field from L02's CDC lesson.

    ALTER TASK process_order_changes RESUME;  -- tasks are created suspended by default
""")

# ------------------------------------------------------------------
# 2. Snowpark — Python execution inside Snowflake's compute
# ------------------------------------------------------------------
SNOWPARK_EXAMPLE = textwrap.dedent("""\
    from snowflake.snowpark import Session
    from snowflake.snowpark.functions import col, sum as sf_sum

    session = Session.builder.configs(connection_params).create()

    # This LOOKS like a pandas/PySpark-style DataFrame API, but every
    # operation is LAZILY translated into SQL and executed inside
    # Snowflake's own compute — no data is pulled out to a separate
    # Python process until you explicitly materialize a result
    # (e.g. .collect() or .to_pandas()).
    orders_df = session.table("raw.orders")
    daily_totals = (
        orders_df
        .filter(col("amount_cents") > 0)
        .group_by("order_date")
        .agg(sf_sum("amount_cents").alias("total_cents"))
    )
    daily_totals.write.save_as_table("analytics.daily_totals", mode="overwrite")

    # A Snowpark UDF: custom Python logic, still executed INSIDE
    # Snowflake's compute when called from SQL or another Snowpark job —
    # this is what lets you bring genuinely custom transformation logic
    # (e.g. a fuzzy-matching function) into an ELT pipeline without an
    # external Python service.
    from snowflake.snowpark.functions import udf
    @udf(name="normalize_phone", replace=True)
    def normalize_phone(raw: str) -> str:
        return "".join(c for c in raw if c.isdigit())
""")

# ------------------------------------------------------------------
# 3. Secure Data Sharing — zero-copy cross-account access
# ------------------------------------------------------------------
DATA_SHARING_EXAMPLE = textwrap.dedent("""\
    -- Provider account: create a share and grant access to specific objects.
    CREATE SHARE partner_orders_share;
    GRANT USAGE ON DATABASE analytics_db TO SHARE partner_orders_share;
    GRANT SELECT ON TABLE analytics_db.public.orders_summary
      TO SHARE partner_orders_share;
    ALTER SHARE partner_orders_share ADD ACCOUNTS = ('partner_account_id');

    -- Consumer account: create a database FROM the share — this is a
    -- LIVE reference to the provider's data, not a copy. Querying it
    -- always reflects the provider's current data, with zero ETL and
    -- zero data-freshness lag on the sharing mechanism itself.
    CREATE DATABASE shared_orders FROM SHARE provider_account.partner_orders_share;
    SELECT * FROM shared_orders.public.orders_summary;
""")

# ------------------------------------------------------------------
# 4. RBAC — role hierarchy design
# ------------------------------------------------------------------
RBAC_HIERARCHY_EXAMPLE = textwrap.dedent("""\
    -- A role hierarchy: permissions flow UP through GRANT ROLE TO ROLE.
    CREATE ROLE analyst_read_only;
    GRANT SELECT ON ALL TABLES IN SCHEMA analytics.public TO ROLE analyst_read_only;

    CREATE ROLE senior_analyst;
    GRANT ROLE analyst_read_only TO ROLE senior_analyst;  -- inherits read access
    GRANT CREATE TABLE ON SCHEMA analytics.scratch TO ROLE senior_analyst;

    -- Users are granted ROLES, never permissions directly:
    GRANT ROLE senior_analyst TO USER jane_doe;

    -- Auditing "what can jane_doe do" is now a role-hierarchy question,
    -- not a search across possibly hundreds of individually-granted
    -- permissions — this is the entire point of RBAC over direct grants.
    SHOW GRANTS TO USER jane_doe;
""")


if __name__ == "__main__":
    print(STREAMS_AND_TASKS_EXAMPLE)
    print(SNOWPARK_EXAMPLE)
    print(DATA_SHARING_EXAMPLE)
    print(RBAC_HIERARCHY_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A data vendor sells access to a curated dataset via Secure Data Sharing
instead of building a REST API or shipping nightly file exports — each
customer account gets a live, read-only share, the vendor updates the
underlying table continuously, and every customer's queries reflect the
latest data instantly with zero additional data-movement infrastructure
on either side; combined with Streams & Tasks maintaining the shared
table incrementally and a role hierarchy scoping exactly which internal
teams can modify the shared data versus only read it, this covers the
full lifecycle from ingestion to external distribution using only
Snowflake-native features.
"""
