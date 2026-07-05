# ============================================================
# L07: Trino + Iceberg — Building an Actual Lakehouse Query Layer
# ============================================================
# WHAT: Combining Trino (L05) and Iceberg (L06) into the actual
#       production pattern feature platforms use — a lakehouse query
#       layer over object storage or on-prem HDFS, including the
#       specific "hybrid on-prem + cloud" pattern common at organizations
#       mid-migration.
# WHY: L05 and L06 covered each piece independently. This lesson is
#      where they combine into the concrete architecture that answers
#      "how does a feature platform actually query years of historical
#      data efficiently, across storage systems, with ACID guarantees."
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
"LAKEHOUSE" describes the combination of (a) cheap, scalable object/
distributed storage (S3, GCS, on-prem HDFS) holding data as open file
formats (Parquet), PLUS (b) a TABLE FORMAT (Iceberg, L06) providing
warehouse-like guarantees (ACID transactions, schema enforcement, time
travel) on top of those files, PLUS (c) a QUERY ENGINE (Trino, L05)
capable of executing SQL against that combination efficiently — no
single piece alone is "the lakehouse"; it's the combination that gives
you a warehouse's transactional/query guarantees at object storage's cost.

The HIVE METASTORE (or a compatible catalog service) is the piece that
CONNECTS Trino to Iceberg tables — it's a metadata service tracking
"this table name maps to this Iceberg metadata location" — Trino's
Iceberg connector queries the metastore to find a table's current
metadata file, then follows Iceberg's own metadata hierarchy (L06) from
there. Some deployments use AWS Glue Catalog or a native Iceberg REST
Catalog instead of a traditional Hive Metastore — functionally similar,
different operational/hosting tradeoffs.

A common REAL-WORLD pattern (matching many organizations' actual
migration state) is a HYBRID deployment: years of historical data sitting
on-prem (often in HDFS, sometimes under an older table format or even
just raw Parquet without Iceberg), with NEWER data landing directly in
cloud object storage as proper Iceberg tables — Trino, configured with
multiple catalogs (L05), can query BOTH in one federated query while a
migration is gradually completed, rather than blocking all feature
computation until every historical byte has been migrated.

PRODUCTION USE CASE:
A feature platform's `transaction_features` computation needs 2 years of
historical transaction data. The most RECENT 6 months live as Iceberg
tables in cloud object storage (the org's target end-state); the OLDER
18 months still live on-prem HDFS (not yet migrated). A single Trino
query, using a Hive connector catalog for the on-prem data and an
Iceberg connector catalog for the cloud data, computes the full 2-year
feature window without waiting for the on-prem migration to complete —
feature computation isn't blocked on migration timelines.

COMMON MISTAKES:
- Assuming a lakehouse pattern REQUIRES cloud storage — the same
  Iceberg+Trino combination works equally well over on-prem HDFS; the
  "cheap distributed storage" requirement doesn't specifically mean
  "cloud," even though cloud object storage is the more common modern
  deployment.
- Not compacting small files regularly in a high-write-frequency
  Iceberg table — frequent small writes (e.g. from streaming ingestion)
  accumulate many small Parquet files over time, and Trino's query
  performance degrades as file count grows without periodic compaction
  merging them into fewer, larger files.
- Querying across a hybrid on-prem/cloud federated setup without
  accounting for the NETWORK LATENCY/BANDWIDTH between the two
  environments — a federated join pulling large volumes of on-prem data
  to combine with cloud data (or vice versa) can be meaningfully slower
  than either system alone, and query patterns should account for this
  during a migration period.
"""

import textwrap


# ------------------------------------------------------------------
# 1. The three-layer lakehouse stack
# ------------------------------------------------------------------
LAKEHOUSE_STACK = {
    "Storage layer": "Object storage (S3/GCS/Azure Blob) or on-prem "
        "HDFS — cheap, scalable, holds data as Parquet files.",
    "Table format layer": "Iceberg (L06) — adds ACID transactions, "
        "schema/partition evolution, and time travel on top of the raw files.",
    "Query engine layer": "Trino (L05) — executes SQL against Iceberg "
        "tables (and, via other connectors, other systems too, enabling "
        "federated queries).",
}

# ------------------------------------------------------------------
# 2. Catalog configuration — connecting Trino to Iceberg via a metastore
# ------------------------------------------------------------------
METASTORE_CATALOG_CONFIG = textwrap.dedent("""\
    # etc/catalog/lake.properties
    connector.name=iceberg
    iceberg.catalog.type=hive_metastore
    hive.metastore.uri=thrift://metastore-host:9083

    # Alternative: AWS Glue as the catalog (common in AWS-native deployments)
    # iceberg.catalog.type=glue
    # hive.metastore.glue.region=us-east-1

    # Alternative: a native Iceberg REST Catalog (increasingly common,
    # engine-agnostic catalog protocol not tied to Hive's original design)
    # iceberg.catalog.type=rest
    # iceberg.rest-catalog.uri=https://catalog.internal/iceberg
""")

# ------------------------------------------------------------------
# 3. A hybrid on-prem + cloud federated query (the realistic mid-migration pattern)
# ------------------------------------------------------------------
HYBRID_QUERY_EXAMPLE = textwrap.dedent("""\
    -- Two catalogs, one query, spanning the migration boundary:
    --   "onprem_hive" — Hive connector, pointed at on-prem HDFS
    --   "cloud_iceberg" — Iceberg connector, pointed at cloud object storage

    WITH combined_transactions AS (
        SELECT customer_id, amount, transaction_date
        FROM onprem_hive.legacy.transactions
        WHERE transaction_date < DATE '2025-07-01'   -- older, not-yet-migrated data

        UNION ALL

        SELECT customer_id, amount, transaction_date
        FROM cloud_iceberg.lake.transactions
        WHERE transaction_date >= DATE '2025-07-01'  -- newer, migrated data
    )
    SELECT customer_id, SUM(amount) AS total_2yr_spend
    FROM combined_transactions
    GROUP BY customer_id;

    -- Feature computation depending on the FULL 2-year window works
    -- correctly and continuously throughout the migration, without
    -- being blocked on the on-prem data being fully moved first.
""")

# ------------------------------------------------------------------
# 4. Table maintenance — compaction and snapshot expiry
# ------------------------------------------------------------------
MAINTENANCE_OPERATIONS = textwrap.dedent("""\
    -- Compact many small files (from frequent small writes) into fewer,
    -- larger ones — directly improves query performance by reducing the
    -- number of files Trino's workers need to open/scan.
    ALTER TABLE cloud_iceberg.lake.transactions EXECUTE optimize;

    -- Expire OLD snapshots no longer needed for time-travel/rollback —
    -- without this, every historical version's data files accumulate
    -- indefinitely, growing storage cost for versions nobody queries anymore.
    ALTER TABLE cloud_iceberg.lake.transactions EXECUTE expire_snapshots(
        retention_threshold => '7d'
    );

    -- Remove orphaned data files (e.g. left over from a failed/aborted
    -- write) that are no longer referenced by any snapshot's manifest.
    ALTER TABLE cloud_iceberg.lake.transactions EXECUTE remove_orphan_files(
        retention_threshold => '3d'
    );
""")


if __name__ == "__main__":
    print("=== The lakehouse stack ===")
    for layer, desc in LAKEHOUSE_STACK.items():
        print(f"{layer}: {desc}\n")

    print(METASTORE_CATALOG_CONFIG)
    print(HYBRID_QUERY_EXAMPLE)
    print(MAINTENANCE_OPERATIONS)

"""
PRODUCTION CONTEXT EXAMPLE:
A platform team migrating from an entirely on-prem Hadoop-based data
warehouse to a cloud lakehouse runs BOTH environments simultaneously for
over a year — Trino's multi-catalog federation lets every feature
computation query span both seamlessly throughout that entire migration
window, and a scheduled maintenance job runs `optimize` and
`expire_snapshots` weekly against the growing set of cloud Iceberg
tables to keep query performance consistent as the migrated data volume
grows, rather than letting file/snapshot accumulation silently degrade
performance over the migration's duration.
"""
