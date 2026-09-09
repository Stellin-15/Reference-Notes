# Data Warehousing & BI — In-Depth Reference

The analytics-engineering and business-intelligence layer sitting on top
of the warehouses covered in Data Engineering Notes — dimensional
modeling, the modern semantic layer, and the BI tools that actually put
numbers in front of decision-makers.


## 1. DIMENSIONAL MODELING (KIMBALL METHODOLOGY)

The dominant approach for structuring analytics data — separate FACT
tables (measurable events: a sale, a click, a shipment — numeric, high
volume) from DIMENSION tables (descriptive context: customer, product,
date — attributes you filter/group by).

**Star schema**: one fact table surrounded by denormalized dimension
tables, each joined directly — optimized for QUERY SIMPLICITY and speed
(fewer joins) at the cost of some redundancy.

```sql
-- Fact table: grain = one row per order line item
CREATE TABLE fact_sales (
  date_key INT REFERENCES dim_date(date_key),
  customer_key INT REFERENCES dim_customer(customer_key),
  product_key INT REFERENCES dim_product(product_key),
  quantity INT,
  revenue DECIMAL
);
-- Dimension table: denormalized, wide, descriptive
CREATE TABLE dim_customer (
  customer_key INT PRIMARY KEY,
  customer_name TEXT,
  region TEXT,
  segment TEXT
);
```

**Snowflake schema**: dimensions further normalized into sub-dimensions
(e.g. `dim_product` referencing a separate `dim_category`) — reduces
redundancy, but adds joins — generally the star schema wins in practice
for BI-query performance, which is why "star schema" is the more commonly
cited default despite "snowflake" ironically sharing this domain's cloud-warehouse name.

**Grain** — the single most important, most-often-skipped modeling
decision: explicitly defining what ONE ROW of a fact table represents
(one order? one line item? one daily aggregate?) BEFORE building
anything — getting grain wrong is the root cause of most "why don't these
two dashboards' numbers match" incidents.


## 2. SLOWLY CHANGING DIMENSIONS (SCD), IN PRACTICE

- **Type 1** — overwrite the old value, no history kept. Simple, but "what
  was this customer's segment last quarter" becomes unanswerable.
- **Type 2** — insert a NEW row on change, with `effective_date`/
  `end_date` (or a `is_current` flag) — preserves full history, the
  standard choice when historical accuracy in reports matters (which it
  usually does for anything customer/pricing/org-structure related).
- **Type 3** — add a new COLUMN for the previous value (`previous_segment`)
  — limited to one level of history, rarely used except for very specific,
  narrow "just the last value" needs.

```sql
-- SCD Type 2 pattern
UPDATE dim_customer SET end_date = CURRENT_DATE, is_current = FALSE
WHERE customer_id = 123 AND is_current = TRUE;
INSERT INTO dim_customer (customer_id, segment, effective_date, end_date, is_current)
VALUES (123, 'Enterprise', CURRENT_DATE, NULL, TRUE);
```


## 3. THE SEMANTIC LAYER

The layer defining business metrics ONCE (what "revenue" or "active user"
actually MEANS, as a formula) so every downstream tool/dashboard/analyst
uses the SAME definition instead of each BI tool re-deriving it slightly
differently — solving the classic "marketing's dashboard says 10,000
users, product's says 9,400, both are technically right by their own
undocumented definition" problem.

- **dbt Semantic Layer / MetricFlow** — define metrics as code alongside
  dbt models, queryable consistently across any connected BI tool.
- **Cube / LookML (Looker's own)** — similar goal, a modeling layer
  between the raw warehouse tables and the BI tool's visual layer.


## 4. BI TOOLS, COMPARED

| Tool | Model | Best fit |
|---|---|---|
| **Looker** | Git-versioned LookML modeling layer + exploration UI | Enterprises wanting a governed, single source of truth for metrics |
| **Tableau** | Powerful, analyst-driven visual exploration | Deep ad-hoc visual analysis, less code-first |
| **Power BI** | Tight Microsoft/Excel ecosystem integration | Microsoft-stack-heavy enterprises |
| **Metabase** | Open-source, simple, fast to set up | Smaller teams wanting self-serve BI without heavy licensing cost |
| **Superset** | Open-source (Apache), SQL-lab + dashboarding | Teams wanting open-source at larger scale than Metabase comfortably handles |

**Self-service BI's real tradeoff**: giving business users direct query/
dashboard-building access (Looker Explores, Tableau's drag-and-drop)
democratizes access to data but multiplies the "everyone defines revenue
slightly differently" risk WITHOUT a semantic layer enforcing consistent
metric definitions underneath it — the semantic layer and self-service BI
are meant to be adopted together, not as alternatives to each other.


## 5. NICHE BUT REAL

- **OLAP cubes** — pre-aggregated, multi-dimensional data structures
  (older technology: SSAS, Essbase) letting users "slice and dice" fast
  without hitting the underlying warehouse per query — largely superseded
  by modern columnar warehouses' raw query speed plus a semantic layer,
  but still found in legacy enterprise BI stacks.
- **Embedded analytics** — BI dashboards embedded directly INTO a
  product's own UI (not a separate BI tool) for end-CUSTOMERS to see their
  own data — a distinct product-engineering discipline (Looker embedded
  SDK, Tableau embedded, or a custom-built dashboard using a charting
  library) from internal-facing BI.
- **Metric drift / dashboard sprawl** — a well-known organizational
  failure mode where hundreds of ungoverned dashboards accumulate, many
  duplicating or subtly contradicting each other — the specific problem
  data governance and semantic-layer adoption exist to prevent, worth
  naming directly in a senior-level interview about data platform maturity.
- **Composable CDP (Customer Data Platform)** — building customer-profile
  unification directly in the warehouse (via reverse ETL, see Data
  Engineering deep dive) instead of a separate CDP product holding its own
  copy of customer data — a real, actively debated modern-data-stack
  architectural trend as of the current market.
