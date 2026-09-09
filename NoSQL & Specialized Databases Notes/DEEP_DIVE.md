# NoSQL & Specialized Databases — Principal Engineer Deep Dive

Companion to the existing lessons. Narrative depth, then a comprehensive
common-to-uncommon reference.


## CAP Theorem in Practice, Precisely

**Beyond the lesson**: CAP theorem is routinely oversimplified as "pick 2
of 3" — the more accurate framing (per Eric Brewer's own later clarification):
Partition tolerance is NOT optional for any real distributed system
(networks WILL partition eventually), so the real choice is between
Consistency and Availability SPECIFICALLY DURING a partition — a system
that's CP refuses to serve some requests during a partition to stay
consistent; an AP system stays available but may return stale/conflicting
data during that same window. OUTSIDE of an actual partition, most systems
provide both C and A — the tradeoff only bites during the partition itself.

**Worked example**: DynamoDB's tunable consistency — a strongly consistent
read ALWAYS reflects the most recent write but has higher latency and lower
availability during partition/replica-lag scenarios; an eventually
consistent read (the default) may return slightly stale data but with
lower latency and higher availability — DynamoDB literally lets you choose
per-request, making the CAP tradeoff an explicit application-level decision
rather than a fixed database-wide property.

**Interview Q&A**:
- *Q: Cassandra is often described as "AP." What does that actually mean operationally?* A: During a network partition between nodes, Cassandra continues accepting writes/reads on EITHER side of the partition (availability preserved), accepting the risk of temporarily divergent data that gets reconciled later via mechanisms like read-repair and hinted handoff — it deliberately favors staying up over refusing requests.


## Data Modeling Without Joins

**Beyond the lesson**: The single biggest mental shift moving from
relational to NoSQL modeling: DESIGN FOR YOUR QUERIES FIRST, not for a
normalized entity model. In DynamoDB/Cassandra, you literally cannot do a
server-side JOIN — if your access pattern needs "get a user AND their
recent orders," that data needs to be modeled to be retrievable together
(via a composite key design, or deliberate denormalization) from the
START, not figured out later with a JOIN like you could in Postgres.

**Worked example**: Cassandra's partition key design directly determines
scalability — a partition key with low cardinality (e.g. `country`)
creates HOT PARTITIONS (all data for "US" lands on the same set of nodes,
overloading them) while a well-chosen high-cardinality key (e.g.
`user_id`) spreads data evenly across the cluster — this single modeling
decision is the difference between a cluster that scales linearly and one that doesn't scale at all.

**Interview Q&A**:
- *Q: Why does DynamoDB's single-table design pattern feel so unfamiliar coming from SQL?* A: It inverts the normal design order — instead of modeling entities first and querying later (SQL's flexibility), you must enumerate every ACCESS PATTERN up front and design keys/indexes specifically to satisfy each one, because there's no JOIN to compensate for an access pattern you didn't anticipate.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Key-value & wide-column
- **Redis** — technically an in-memory KV store, covered deeply in Redis &
  Caching Notes; worth knowing it straddles "cache" and "primary NoSQL
  database" depending on persistence config (RDB/AOF).
- **DynamoDB** — AWS-managed, wide-column-ish KV, single-digit-ms latency
  at any scale, the default choice for AWS-native serverless architectures.
- **Cassandra** — self-hosted or via DataStax/Astra DB (managed), the
  standard choice for write-heavy, massively distributed workloads
  (originally built at Facebook for the inbox search problem).
- **ScyllaDB** — a Cassandra-API-compatible rewrite in C++ for
  significantly higher throughput per node — increasingly chosen over
  Cassandra itself for new high-performance deployments (see Feature
  Stores & Modern Data Lake Notes for its ML-feature-store use case).
- **HBase** — Hadoop-ecosystem wide-column store, less common in new
  greenfield projects now but still found in large legacy Hadoop deployments.

### Document databases
- **MongoDB** — the dominant document database; flexible schema, rich
  query language closer to SQL's expressiveness than pure KV stores.
- **Couchbase** — combines document storage with a built-in caching
  layer and strong mobile/edge sync support (Couchbase Mobile/Sync Gateway).
- **Firestore** (GCP) — managed document database with real-time
  listeners built in — heavily used in mobile/web apps needing live data sync out of the box.

### Graph databases
- **Neo4j** — the dominant graph database, Cypher query language; ideal
  for genuinely graph-shaped problems (social networks, fraud-ring
  detection, recommendation engines) where the relationships ARE the
  primary query target, not an afterthought.
- **Amazon Neptune** — AWS-managed graph database, supports both Gremlin
  and openCypher query languages.
- **ArangoDB** — a genuinely multi-model database (document + graph + KV
  in one engine) — a niche but real choice when a team wants graph
  capability without adopting a fully separate specialized database.

### Time-series databases
- **InfluxDB** — the most common purpose-built time-series database;
  optimized write/compression for time-ordered data, purpose-built
  downsampling/retention policies.
- **TimescaleDB** — a Postgres EXTENSION adding time-series
  optimizations (automatic partitioning by time, continuous aggregates) —
  chosen when a team wants time-series performance WITHOUT leaving the
  Postgres/SQL ecosystem entirely.
- **Prometheus's own TSDB** — purpose-built specifically for metrics (see
  Observability Notes) — worth knowing it's a time-series database in its
  own right, not just a monitoring tool bolted onto a generic database.

### Search-oriented
- **Elasticsearch/OpenSearch** — technically a search engine, but used AS
  a primary datastore in some architectures — see the new Search Engines domain for the deep version.

### Vector databases
- Covered in depth in the new AI Agent & Automation Tooling domain
  (Pinecone/Weaviate/Qdrant/Milvus/pgvector) — the newest entrant to the
  "specialized database" category, purpose-built for embedding similarity search.


## NICHE BUT REAL

- **Polyglot persistence** (see L07/L08 in the existing lessons) — most
  real production systems at scale use SEVERAL of the above together (Postgres
  for transactional data, Redis for caching, Elasticsearch for search,
  Cassandra for time-series event data) rather than one database for
  everything — the actual skill is knowing which workload belongs where,
  and building reliable CDC (Change Data Capture) pipelines to keep them in sync.
- **Change Data Capture (Debezium)** — streams row-level changes FROM a
  primary database (Postgres/MySQL) INTO Kafka/other systems in real time,
  the standard mechanism keeping polyglot-persistence systems consistent
  without dual-write bugs (writing to two databases separately, where one write can fail and the other succeed).
- **Multi-region active-active NoSQL** — Cassandra and DynamoDB Global
  Tables both support true multi-region ACTIVE-ACTIVE writes (unlike most
  relational databases' single-writer model) using last-write-wins or
  vector-clock-based conflict resolution — a genuinely different
  consistency model than anything in the relational world.
- **Consistent hashing** — the actual mechanism (used by Cassandra,
  DynamoDB, and most distributed KV stores) determining which node owns
  which data, designed specifically so adding/removing a node only
  reshuffles a SMALL fraction of keys rather than requiring a full
  rehash/rebalance of the entire dataset.
