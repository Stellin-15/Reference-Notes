# ============================================================
# L06: Apache Iceberg — Open Table Format Internals
# ============================================================
# WHAT: How Iceberg actually implements ACID transactions, schema
#       evolution, partition evolution, and time travel on top of plain
#       files in object storage — and how it compares to Delta Lake
#       (already covered in Data Engineering Notes) and Apache Hudi.
# WHY: Trino (L05) needs a TABLE FORMAT to know how to interpret a
#      directory of Parquet files as a proper, transactional TABLE —
#      Iceberg is the dominant open, engine-agnostic format for this
#      (unlike Delta Lake, which originated Databricks-specific, though
#      now more broadly supported), and it's what the Trino+Iceberg
#      lakehouse pattern in L07 is built on.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
An open TABLE FORMAT solves a specific problem plain files don't: a
directory of Parquet files has no built-in concept of "this table's
current state," "which files belong to which version," or "what's this
table's schema right now" — Iceberg adds a METADATA LAYER on top of the
data files that provides exactly these guarantees, making a directory of
files behave like a real, transactional, versioned table.

Iceberg's metadata is a HIERARCHY of files: a METADATA FILE (JSON)
describes the table's schema, partition spec, and points to the CURRENT
SNAPSHOT. A SNAPSHOT represents the table's state at one point in time —
it points to a MANIFEST LIST, which lists MANIFEST FILES, each of which
lists the actual DATA FILES (Parquet/ORC/Avro) that make up that
snapshot. Every write operation (insert, update, delete, schema change)
creates a NEW snapshot — the OLD snapshot's data files are NOT
immediately deleted, which is what makes TIME TRAVEL possible: querying
"the table as of snapshot N" just means reading the manifest chain for
that specific historical snapshot.

SCHEMA EVOLUTION (adding/renaming/dropping/reordering columns, or
widening a column's type) is handled by Iceberg tracking columns by a
STABLE INTERNAL ID, not by name or position — renaming a column just
updates the metadata's name-to-ID mapping; the underlying Parquet files
never need to be rewritten. This is a meaningfully different (and safer)
mechanism than table formats that identify columns by name/position,
where a rename can silently misalign old data files against a new schema.

PARTITION EVOLUTION solves a real operational problem: if a table was
originally partitioned by `month` and later needs to be partitioned by
`day` (finer-grained, as data volume grows), Iceberg lets you change the
partition spec GOING FORWARD without rewriting historical data files —
old data stays under the old partition scheme, new data uses the new
scheme, and Iceberg's query planning transparently handles both when
scanning across the boundary. Traditional Hive-style partitioning
requires a full table rewrite to change partitioning at all.

TIME TRAVEL, as introduced above, is a direct consequence of the
snapshot model — `SELECT * FROM table FOR VERSION AS OF <snapshot_id>`
or `FOR TIMESTAMP AS OF <time>` reads a specific historical snapshot's
manifest chain, giving you the table exactly as it existed then, without
needing a separate backup/versioning system.

COMPARISON TO DELTA LAKE (Databricks Notes' L05-L06 coverage) AND HUDI:
Delta Lake uses a similar snapshot-based transaction LOG concept
(`_delta_log/*.json`) but originated as (and remains most deeply
integrated with) Databricks' own ecosystem, though it's now more broadly
engine-compatible than at its start. Iceberg was designed from the start
to be ENGINE-AGNOSTIC (Trino, Spark, Flink, and others all have
first-class Iceberg support) and has historically had stronger
partition-evolution support. Apache Hudi optimizes specifically for
FREQUENT, INCREMENTAL UPSERTS (near-real-time ingestion pipelines with
lots of small updates) with its own indexing strategy, at some cost to
the large-batch analytical query performance Iceberg/Delta typically
optimize for. None of the three is universally "best" — the choice
depends on your engine ecosystem and write pattern (batch-heavy vs
upsert-heavy).

PRODUCTION USE CASE:
A feature platform's raw transaction table, originally partitioned by
month, grows to the point where MONTHLY partitions are too coarse
(queries scanning a whole month's data when they only need one day's
worth) — the team evolves the partition spec to DAILY going forward,
without a disruptive full-table rewrite, and historical queries spanning
the transition boundary continue to work correctly because Iceberg's
query planner is aware of both partition schemes.

COMMON MISTAKES:
- Choosing a table format based on "what everyone uses" rather than your
  actual ENGINE ecosystem and write pattern — a team using primarily
  Spark within Databricks likely has good reasons to default to Delta
  Lake; a team building Trino-centric federated queries (L05) across
  multiple engines likely benefits more from Iceberg's engine-agnostic design.
- Never running maintenance operations (compaction of small files,
  expiring old snapshots) — Iceberg's snapshot model means old data
  files accumulate over time unless explicitly cleaned up, and many
  small files from frequent writes hurt query performance until compacted.
- Assuming partition evolution rewrites historical data — it does NOT;
  understanding that old and new partition schemes coexist is important
  for reasoning about query performance across the transition boundary.
"""

import textwrap


# ------------------------------------------------------------------
# 1. The metadata hierarchy
# ------------------------------------------------------------------
METADATA_HIERARCHY_NOTE = textwrap.dedent("""\
    metadata/v3.metadata.json          <- current metadata file: schema,
                                            partition spec, points to...
        -> snapshot (id: 5821...)      <- the CURRENT snapshot
            -> manifest-list-5821.avro <- lists manifest files for this snapshot
                -> manifest-001.avro   <- lists actual data files + stats
                    -> data/part-001.parquet
                    -> data/part-002.parquet
                -> manifest-002.avro
                    -> data/part-003.parquet

    Every INSERT/UPDATE/DELETE/schema-change creates a NEW metadata file
    pointing to a NEW snapshot — old snapshots (and the data files they
    reference) remain until explicitly expired, which is exactly what
    makes time travel and rollback possible.
""")

# ------------------------------------------------------------------
# 2. Schema evolution — safe because columns are tracked by stable ID
# ------------------------------------------------------------------
SCHEMA_EVOLUTION_EXAMPLE = textwrap.dedent("""\
    -- Renaming a column is a METADATA-ONLY operation — no data files
    -- are rewritten, because Iceberg tracks the column by its stable
    -- internal ID, not by name.
    ALTER TABLE iceberg.lake.transactions RENAME COLUMN amt TO amount;

    -- Adding a new column, similarly, doesn't require rewriting
    -- existing files — old files simply don't have a value for the new
    -- column (read as NULL) until they're eventually rewritten by
    -- normal compaction/updates.
    ALTER TABLE iceberg.lake.transactions ADD COLUMN currency VARCHAR;

    -- Widening a type (e.g. int -> long) is also metadata-only and safe;
    -- NARROWING a type is NOT allowed, since it could lose data silently.
""")

# ------------------------------------------------------------------
# 3. Partition evolution
# ------------------------------------------------------------------
PARTITION_EVOLUTION_EXAMPLE = textwrap.dedent("""\
    -- Table originally partitioned by month:
    CREATE TABLE iceberg.lake.transactions (
        transaction_id BIGINT, customer_id BIGINT, amount DECIMAL(10,2),
        transaction_date DATE
    ) WITH (partitioning = ARRAY['month(transaction_date)']);

    -- Later, evolve to daily partitioning GOING FORWARD — historical
    -- data stays under the old monthly scheme; only NEW data uses the
    -- new daily scheme. No rewrite of existing files.
    ALTER TABLE iceberg.lake.transactions
    SET PROPERTIES partitioning = ARRAY['day(transaction_date)'];

    -- A query spanning both old (monthly) and new (daily) partitioned
    -- data works transparently — Trino's query planner understands
    -- both partition schemes and prunes correctly against each.
""")

# ------------------------------------------------------------------
# 4. Time travel
# ------------------------------------------------------------------
TIME_TRAVEL_EXAMPLE = textwrap.dedent("""\
    -- Query a specific historical snapshot by ID:
    SELECT * FROM iceberg.lake.transactions FOR VERSION AS OF 5821750162268575000;

    -- Or by timestamp — Iceberg finds the snapshot that was current at that time:
    SELECT * FROM iceberg.lake.transactions FOR TIMESTAMP AS OF TIMESTAMP '2026-01-01 00:00:00';

    -- Inspect the full snapshot history:
    SELECT * FROM iceberg.lake."transactions$snapshots";

    -- ROLLBACK the table to a previous snapshot (e.g. after a bad load):
    CALL iceberg.system.rollback_to_snapshot('lake', 'transactions', 5821750162268575000);
""")

# ------------------------------------------------------------------
# 5. Iceberg vs Delta Lake vs Hudi
# ------------------------------------------------------------------
TABLE_FORMAT_COMPARISON = {
    "Apache Iceberg": "Engine-agnostic by design (Trino/Spark/Flink all "
        "first-class), strong partition evolution, snapshot-based ACID "
        "and time travel.",
    "Delta Lake": "Originated in and remains most deeply integrated "
        "with Databricks (see Data Engineering Notes L05-L06); "
        "transaction-log-based ACID, broadly compatible but historically "
        "Spark/Databricks-centric.",
    "Apache Hudi": "Optimized specifically for FREQUENT, INCREMENTAL "
        "UPSERTS (near-real-time ingestion) via its own indexing "
        "strategy — a different write-pattern optimization target than "
        "Iceberg/Delta's typical batch-heavy analytical focus.",
}


if __name__ == "__main__":
    print(METADATA_HIERARCHY_NOTE)
    print(SCHEMA_EVOLUTION_EXAMPLE)
    print(PARTITION_EVOLUTION_EXAMPLE)
    print(TIME_TRAVEL_EXAMPLE)
    print("=== Table format comparison ===")
    for fmt, note in TABLE_FORMAT_COMPARISON.items():
        print(f"{fmt}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A feature platform spanning both an on-prem Hadoop deployment and cloud
infrastructure standardizes on Iceberg specifically for its
engine-agnostic guarantee — the SAME Iceberg tables are queried by Trino
(for federated feature-computation queries, L05), by Spark (for
heavier batch transformation jobs), and eventually by Flink (for a
planned streaming-features initiative) — a Databricks-centric team on a
single-engine Spark stack might reasonably have chosen Delta Lake
instead for the same underlying transactional guarantees, tighter-woven
into that specific ecosystem.
"""
