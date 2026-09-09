# Data Engineering — Principal Engineer Deep Dive

Companion to L01-L12. Narrative depth, then a comprehensive common-to-
uncommon reference across the modern data stack.


## ETL vs ELT — Why the Order Flipped

**Beyond the lesson**: ETL (Transform BEFORE loading) made sense when
storage was expensive and compute was the scarce resource that needed to
run once, carefully, before data landed anywhere. Cloud data warehouses
(Snowflake/BigQuery/Redshift) flipped this: storage is now cheap and
warehouse compute is fast/elastic, so ELT (load RAW data first, transform
INSIDE the warehouse using its own compute) became dominant — you keep the
raw data forever (re-transformable if requirements change) and leverage
the warehouse's own massively parallel compute for transformation instead
of a separate transformation cluster.

**Worked example**: dbt (data build tool) is the concrete embodiment of
the ELT shift — it doesn't extract or load anything; it ONLY transforms,
writing SQL `SELECT` statements as modular, testable, version-controlled
"models" that dbt compiles into the correct dependency-ordered sequence of
`CREATE TABLE AS`/`CREATE VIEW AS` statements run directly in the
warehouse — transformation logic finally got the same software-engineering
rigor (testing, version control, documentation, CI) that application code has had for years.

**Interview Q&A**:
- *Q: When would you still choose ETL over ELT today?* A: When the raw data itself is sensitive and shouldn't ever land in the warehouse un-redacted (PII that must be masked/tokenized BEFORE storage for compliance reasons), or when the source system's extraction is genuinely expensive/rate-limited enough that pre-filtering before load meaningfully reduces cost — ELT's "load everything raw" default assumption doesn't hold in either case.


## Idempotency & Incremental Loading

**Beyond the lesson**: A pipeline that isn't idempotent (re-running it
produces DUPLICATE or inconsistent results, not the same result) is a
silent time bomb — the FIRST time a job needs to be re-run (after a
failure, for a backfill, for a bug fix) is exactly when a non-idempotent
design causes real damage, usually discovered as duplicate row counts
weeks later, not immediately. The fix is designing every load as either a
full REPLACE of a partition/date range, or an UPSERT keyed on a natural
unique identifier — never a blind `INSERT` that assumes "this only runs once, ever."

**Worked example**: Incremental loading by watermark — tracking the
MAX(updated_at) successfully processed so far, and on the next run only
pulling rows with `updated_at > last_watermark` — simple and effective,
but has a real edge case: if a source row is updated with a timestamp
EARLIER than the current watermark (clock skew, backfilled corrections),
it's silently missed forever. CDC (Change Data Capture, via Debezium
reading the database's own write-ahead log) sidesteps this entirely by
capturing every change as it happens, rather than relying on a
timestamp column's correctness.

**Interview Q&A**:
- *Q: A backfill for the last 90 days needs to re-run a daily pipeline. What breaks if the pipeline isn't idempotent?* A: Re-running each day's job appends duplicate rows for days that already succeeded partially or fully before the backfill was needed — the fix requires the pipeline to DELETE-then-INSERT (or MERGE/upsert) per partition, so re-running any given day's load is safe regardless of how many times it's retried.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Orchestration
- **Airflow** — the long-standing standard (see L03-L04); DAGs as Python
  code, a rich operator ecosystem, but historically criticized for
  scheduler overhead and awkward dynamic/parameterized DAG generation —
  the TaskFlow API (L04) addressed much of the awkward syntax.
- **Dagster** — a newer orchestrator with a strong emphasis on
  data-ASSET-centric thinking (define what data assets exist and their
  dependencies, not just task order) and built-in testing/typing —
  increasingly chosen for greenfield modern-data-stack projects.
- **Prefect** — similar niche to Dagster, emphasizes a more Pythonic,
  less DSL-heavy authoring experience than classic Airflow.
- **Mage** — a newer, notebook-friendly orchestrator gaining traction
  specifically for a friendlier developer experience building/debugging pipelines interactively.

### Modern data stack components
- **Fivetran / Airbyte** — managed (Fivetran) and open-source (Airbyte)
  EXTRACT connectors — hundreds of pre-built source connectors (Salesforce,
  Stripe, Postgres CDC) so teams stop hand-writing API integration code for
  common SaaS sources.
- **dbt** — the transformation layer (see above) — dbt Core (open-source
  CLI) vs dbt Cloud (managed, adds scheduling/CI/docs hosting).
- **Great Expectations / dbt tests / Soda** — data quality/validation
  frameworks — asserting "this column should never be null," "this value
  should be within range," as CODE that fails a pipeline run loudly instead
  of silently shipping bad data downstream.
- **Monte Carlo / Metaplane** — data OBSERVABILITY platforms (distinct
  from data quality TESTING) — automatically detect anomalies (a table's
  row count suddenly dropped 90%, a column's null rate spiked) without
  needing every possible check hand-written in advance.

### Data lineage & cataloging
- **DataHub / Amundsen / Atlan** — data catalogs — answer "where does this
  column's data actually come from" and "what would break if I changed
  this table" across an entire organization's pipelines — increasingly
  essential once a company has hundreds of interdependent tables/dashboards.
- **OpenLineage** — an open standard for capturing lineage metadata across
  DIFFERENT tools (Airflow, Spark, dbt) into one consistent format, rather
  than each tool tracking lineage in its own incompatible way.

### Warehouse & lakehouse platforms
- Covered in L05-L09 (Databricks, Snowflake, ADF) — worth cross-
  referencing the new Data Warehousing & BI domain for the analytics-
  engineering/BI-tool layer that sits ON TOP of these warehouses.
- **BigQuery** (GCP) — the remaining major cloud warehouse not covered in
  the core lessons — serverless, pay-per-query pricing model distinct from
  Snowflake/Redshift's provisioned-warehouse model.


## NICHE BUT REAL

- **The medallion architecture** (Bronze/Silver/Gold layers) — raw
  ingested data (Bronze) progressively cleaned/validated (Silver) and
  aggregated into business-ready models (Gold) — the near-universal
  mental model for organizing a modern lakehouse, referenced constantly in
  Databricks-adjacent job postings and interviews.
- **Slowly Changing Dimensions (SCD)** — Type 1 (overwrite, no history),
  Type 2 (new row per change, full history preserved with effective-date
  columns), Type 3 (limited history via extra columns) — a classic data-
  modeling decision every analytics-engineering role eventually has to make explicitly.
- **Data contracts** — an emerging practice formalizing the schema/SLA a
  data-producing team commits to for a downstream consuming team (similar
  spirit to API contracts, see API Design deep dive) — aimed at preventing
  "upstream team changed a column type and broke twelve downstream
  dashboards with zero warning," a genuinely common real incident class in
  large data organizations.
- **Reverse ETL** — pushing TRANSFORMED warehouse data BACK OUT into
  operational SaaS tools (Salesforce, HubSpot, marketing platforms) —
  Census/Hightouch are the dominant tools — a real, distinct pipeline
  direction beyond the traditional "sources -> warehouse -> BI" flow.
