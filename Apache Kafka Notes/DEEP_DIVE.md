# Apache Kafka — Principal Engineer Deep Dive

Companion to L01-L08. Narrative depth, then a comprehensive common-to-
uncommon reference.


## Partitions, Offsets & Ordering, Precisely

**Beyond the lesson**: Kafka guarantees ordering ONLY within a single
partition — messages across DIFFERENT partitions have no ordering
guarantee relative to each other at all. This is the single most
misunderstood Kafka fact in interviews: "does Kafka guarantee message
order" has the answer "only per-partition, and only if you're using the
SAME key so related messages land on the same partition" — a producer
sending order-related events without a consistent partition key can have
them processed wildly out of order across partitions/consumers.

**Worked example**: Consumer group rebalancing — when a consumer joins or
leaves a group, partitions are REASSIGNED across the remaining consumers
(a "stop the world" rebalance in older cooperative-sticky-less versions,
briefly pausing all consumption group-wide). Modern Kafka's cooperative
rebalancing protocol (`CooperativeStickyAssignor`) minimizes this by only
reassigning the SPECIFIC partitions that need to move, letting unaffected
consumers keep processing — a real, measurable production improvement for
large consumer groups that used to see multi-second full-group pauses on every scaling event.

**Interview Q&A**:
- *Q: Why would a consumer process the same message twice even with `enable.auto.commit=false` and explicit commits?* A: If a consumer processes a message, THEN crashes before committing the offset, the next consumer (or the same one on restart) re-reads from the last COMMITTED offset — reprocessing the already-handled message. This is exactly why Kafka gives "at-least-once" delivery by default, and why idempotent consumer logic (see section below) is the application's responsibility, not Kafka's.


## Exactly-Once Semantics, In Depth

**Beyond the lesson**: "Exactly-once" in Kafka is achieved through the
COMBINATION of idempotent producers (each message gets a sequence number;
the broker deduplicates retries of the SAME message automatically) and
transactional writes (a producer can atomically write to multiple
partitions AND commit consumer offsets as one transaction, so a
consume-transform-produce pipeline either fully commits or fully rolls
back). This is genuinely subtle — "exactly-once" doesn't mean the network
never retries; it means retries are deduplicated and multi-partition
writes are atomic, which together produce the observed exactly-once effect end-to-end.

**Interview Q&A**:
- *Q: Your consumer writes processed data to a database, THEN commits the Kafka offset. What failure mode remains even with idempotent producers/transactions enabled on the Kafka side?* A: The dual-write problem — if the DB write succeeds but the process crashes before the offset commit, the message gets reprocessed on restart, potentially double-writing to the DB (Kafka's exactly-once guarantees don't extend to an EXTERNAL system it isn't transactionally coordinated with) — the fix is either an idempotent DB write (upsert on a unique key) or the Kafka Connect/transactional outbox pattern that ties both together.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Kafka ecosystem components
- **Kafka Connect** — a framework for source/sink connectors (pull data
  IN from a database via CDC, push data OUT to Elasticsearch/S3) without
  hand-writing producer/consumer code for every integration — the standard
  way most companies actually get data into/out of Kafka at the edges.
- **Kafka Streams** — a Java library for stream processing DIRECTLY
  against Kafka topics (no separate cluster like Spark/Flink needs) —
  chosen when the processing logic is simple enough not to warrant a
  separate stream-processing cluster.
- **ksqlDB** — SQL-like queries directly over Kafka streams — lets
  analysts/less Kafka-native engineers express stream transformations
  without writing Java/Kafka Streams code.
- **Schema Registry** — centralizes and enforces Avro/Protobuf/JSON Schema
  contracts for topics, with compatibility modes (backward/forward/full)
  preventing a producer from shipping a schema change that breaks existing
  consumers — a real, common production safeguard.

### Alternatives & when they win
- **RabbitMQ** — traditional message BROKER (not a log) — better fit for
  complex ROUTING (topic/header-based exchanges) and per-message
  acknowledgment patterns; weaker fit for Kafka's core strength (replaying
  historical data, massive sustained throughput).
- **Pulsar** — a genuine Kafka alternative with a fundamentally different
  architecture (separates compute/serving from storage via BookKeeper),
  offering native multi-tenancy and tiered storage more natively than Kafka's bolt-on equivalents.
- **AWS Kinesis / Managed Kafka (MSK)** — see Cloud Platforms deep dive;
  managed alternatives trading operational simplicity for less
  flexibility/ecosystem breadth than self-hosted Kafka.
- **Redpanda** — a Kafka-API-compatible rewrite in C++ (no ZooKeeper/JVM
  dependency at all), aimed at significantly lower latency and simpler
  operations — a real, growing production alternative for teams wanting
  Kafka's ecosystem compatibility without the JVM operational overhead.

### Operational deep cuts
- **ZooKeeper vs KRaft** — Kafka historically depended on ZooKeeper for
  cluster metadata/coordination; KRaft (Kafka's own Raft-based consensus,
  now the default in modern versions) removes that external dependency
  entirely — a major, relatively recent architectural shift worth knowing by name.
- **Retention & compaction**: time/size-based retention deletes old
  segments; LOG COMPACTION instead keeps only the LATEST value per key
  forever — used for topics representing current STATE (like a changelog
  of "current value per user") rather than an event history.
- **Consumer lag monitoring** — the single most important Kafka
  operational metric: how far behind a consumer group is from the latest
  produced offset — a growing lag under steady traffic is the earliest
  reliable signal of a struggling/undersized consumer before anything else visibly breaks.


## NICHE BUT REAL

- **The transactional outbox pattern** — instead of a service writing to
  its own database AND publishing to Kafka as two separate operations
  (risking exactly the dual-write problem above in reverse), it writes the
  event to an "outbox" table in the SAME database transaction as the
  business write, and a separate process (Debezium via CDC, or a polling
  publisher) reliably relays outbox rows to Kafka — solving dual-write
  atomicity without needing distributed transactions across two different systems.
- **Tiered storage** — offloading OLDER Kafka segments to cheap object
  storage (S3) while keeping recent data on fast local disk — lets
  retention periods stretch to months/years without proportionally scaling
  expensive broker disk, a relatively recent but increasingly standard
  feature (native in newer Kafka versions, always-available in Pulsar/Redpanda's architectures).
- **Static membership** — a consumer group feature letting a consumer
  rejoin with the SAME identity after a brief restart (deploy, pod
  restart) WITHOUT triggering a full rebalance — meaningfully reduces
  rebalance churn in Kubernetes-deployed Kafka consumer fleets that restart frequently during normal rolling deploys.
- **Multi-datacenter replication** (MirrorMaker 2) — asynchronously
  replicates topics across geographically separate Kafka clusters for
  disaster recovery or geo-local producer/consumer latency — a real,
  non-trivial operational undertaking with its own offset-translation subtleties across clusters.
