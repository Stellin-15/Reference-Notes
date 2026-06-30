#!/usr/bin/env bash

# ============================================================
# L04: Kafka Partitions and Ordering
# ============================================================
# WHAT: How Kafka partitions data across brokers, how ordering
#       guarantees work (and where they break), and how compacted
#       topics replace traditional databases for some use cases.
# WHY:  Partition count and key design are the most consequential
#       decisions you make when designing a Kafka topic. Getting
#       them wrong means either insufficient throughput, hotspots,
#       or broken ordering guarantees — all in production, under
#       load, when it's hardest to fix.
# LEVEL: Advanced
# ============================================================
# CONCEPT OVERVIEW:
#   A Kafka topic is a LOGICAL stream split into N partitions.
#   Each partition is an ordered, immutable, append-only log
#   stored on ONE broker (the partition leader). Replicas of
#   each partition live on other brokers for fault tolerance.
#
#   PRODUCER: decides which partition to write to (via key hash
#   or custom partitioner). Writes are sequential within a
#   partition, so the partition is the UNIT OF ORDERING.
#
#   CONSUMER: each partition is consumed by at most one consumer
#   in a consumer group at a time. Parallelism = partition count.
#
# PRODUCTION USE CASE:
#   E-commerce order processing: 1 topic, key = order_id.
#   All events for a given order (placed, paid, shipped) land in
#   the same partition in arrival order. Consumers process events
#   per order without needing distributed coordination.
#
# COMMON MISTAKES:
#   - Creating topics with 1 partition: zero parallelism, single
#     broker bottleneck, no consumer group scaling.
#   - Too many partitions: each partition = file handles + ZooKeeper
#     znodes + replication traffic. 10,000+ partitions per broker
#     causes GC pressure and leader election slowness.
#   - Using null keys for events that require ordering: null keys
#     are distributed round-robin, so related events land on
#     different partitions and the ordering guarantee is lost.
#   - Assuming ordering ACROSS partitions: impossible by design.
# ============================================================

# Kafka CLI tools location (adjust to your installation):
KAFKA_HOME="/opt/kafka"
BOOTSTRAP="--bootstrap-server localhost:9092"


# ============================================================
# SECTION 1: HOW MANY PARTITIONS?
# ============================================================
# Formula: target_throughput_MB_per_sec / per_partition_throughput_MB_per_sec
#
# Per-partition throughput depends on:
#   - Disk I/O (sequential writes: typically 200-500 MB/s per disk)
#   - Network bandwidth
#   - Message size
#   - Replication factor overhead
#
# Practical rule of thumb (Confluent recommendation):
#   - Start with 10-30 partitions for most topics.
#   - For high-throughput topics (>1 GB/s): 50-100 partitions.
#   - For low-throughput topics (<10 MB/s): 3-6 partitions.
#   - Match to consumer group size: if you plan max 20 consumers,
#     20 partitions is the sweet spot (1 partition per consumer).
#
# WHY NOT MORE:
#   - Each partition is a directory on disk with .log, .index, .timeindex files.
#   - At 10,000 partitions: millions of file handles. OS limits hit.
#   - During broker failure, leader election runs for EVERY partition.
#     10,000 partitions × election time = slow failover.
#   - Replication traffic: each partition replica requires network I/O.

# Create a topic with 12 partitions, replication factor 3:
${KAFKA_HOME}/bin/kafka-topics.sh \
    ${BOOTSTRAP} \
    --create \
    --topic orders \
    --partitions 12 \            # 12-way parallelism for consumers
    --replication-factor 3 \    # 3 copies: survive 2 broker failures
    --config retention.ms=604800000 \    # keep messages for 7 days
    --config max.message.bytes=1048576   # max 1MB per message

# List all topics:
${KAFKA_HOME}/bin/kafka-topics.sh ${BOOTSTRAP} --list

# Describe a topic (shows partition leaders, replicas, ISR):
${KAFKA_HOME}/bin/kafka-topics.sh ${BOOTSTRAP} --describe --topic orders
# Output:
# Topic: orders  PartitionCount: 12  ReplicationFactor: 3
# Topic: orders  Partition: 0  Leader: 1  Replicas: 1,2,3  Isr: 1,2,3
# Topic: orders  Partition: 1  Leader: 2  Replicas: 2,3,1  Isr: 2,3,1
# ...


# ============================================================
# SECTION 2: KEY-BASED PARTITIONING
# ============================================================
# When a producer sends a message with a KEY, Kafka hashes the
# key to determine the target partition:
#   partition = hash(key) % num_partitions
#
# GUARANTEE: All messages with the SAME KEY always go to the
# SAME PARTITION. Within that partition, they are ordered by
# arrival time (offset). This gives you per-key ordering.
#
# WHY THIS MATTERS:
#   - user_id as key: all events for user 42 are in one partition.
#     A consumer processing partition N handles all events for
#     users that hash to N, in order. No cross-partition joins needed.
#   - order_id as key: all order lifecycle events are ordered.
#   - device_id as key: IoT telemetry streams per device are ordered.
#
# HOTSPOT RISK: If key cardinality is low (e.g., country_code with
# 5 values across 20 partitions), most traffic goes to 5 partitions.
# Fix: composite key (user_id + timestamp) or custom partitioner.

# Produce a message with a key (for testing):
echo "order_1001:{'status':'placed','total':99.99}" | \
${KAFKA_HOME}/bin/kafka-console-producer.sh \
    ${BOOTSTRAP} \
    --topic orders \
    --property "parse.key=true" \
    --property "key.separator=:"

# Consume and show partition + key:
${KAFKA_HOME}/bin/kafka-console-consumer.sh \
    ${BOOTSTRAP} \
    --topic orders \
    --from-beginning \
    --property "print.key=true" \
    --property "print.partition=true" \
    --property "print.offset=true"


# ============================================================
# SECTION 3: PARTITIONERS
# ============================================================
# DEFAULT PARTITIONER (Kafka 2.4+):
#   - If key != null: murmur2 hash of key bytes % num_partitions.
#   - If key == null: STICKY PARTITIONER — batches all null-key
#     messages to the SAME partition until the batch is full or
#     linger.ms expires, then switches to the next partition.
#     Before 2.4, null keys used round-robin (one message per
#     partition per batch = tiny batches = bad throughput).
#
# CUSTOM PARTITIONER (Java, shown as pseudocode):
#   Implement org.apache.kafka.clients.producer.Partitioner:
#
#   class VIPPartitioner implements Partitioner {
#     override fun partition(topic, key, keyBytes, value, cluster): Int {
#       val userId = key as String
#       val numPartitions = cluster.partitionCountForTopic(topic)
#       // VIP users (IDs 1-100) go to partition 0 (dedicated high-priority)
#       if (userId.toInt() <= 100) return 0
#       // Everyone else is distributed across remaining partitions
#       return 1 + (murmur2(keyBytes) % (numPartitions - 1))
#     }
#   }
#
# Use case: SLA-tiered processing. VIP requests go to a dedicated
# partition consumed by a high-priority consumer. Regular traffic
# goes to remaining partitions and regular consumers.


# ============================================================
# SECTION 4: ORDERING GUARANTEES
# ============================================================
# WITHIN A PARTITION: total ordering by offset. Offset 0 was
# written before offset 1. Period. The log is append-only;
# offsets never change.
#
# ACROSS PARTITIONS: NO ordering guarantee. None. Ever.
#
# WHY CROSS-PARTITION ORDERING IS IMPOSSIBLE:
#   - Partitions are on different brokers.
#   - The producer may connect to different brokers in sequence.
#   - Network latency differs per broker.
#   - A batch to partition 0 (broker 1) may arrive AFTER a batch
#     to partition 1 (broker 2) even if it was sent first.
#   - Consumer threads for different partitions run independently.
#
# DESIGN IMPLICATION:
#   If you need event A to be processed before event B, they must
#   share a key so they land on the same partition. You cannot
#   enforce cross-partition ordering at the Kafka level.
#
# SPECIAL CASE — exactly-once with retries:
#   Even within a partition, retries can cause duplicates (producer
#   sent the message, got a network error, retried — broker got it
#   twice). Fix: idempotent producer (enable.idempotence=true).
#   This ensures each message is written EXACTLY ONCE per partition
#   even with retries. See L05_reliability.py.


# ============================================================
# SECTION 5: COMPACTED TOPICS
# ============================================================
# Normal topic retention: delete messages older than X days/bytes.
# Compacted topic retention: keep only the LATEST value for each key.
#
# USE CASES:
#   - User profile store: key=user_id, value=full profile JSON.
#     After compaction, you have the current profile for every user.
#   - Config store: key=setting_name, value=setting_value.
#   - Change Data Capture (CDC): key=row_pk, value=row_data.
#     Consumer always gets the current state of each row.
#   - Kafka Streams table: KTable is backed by a compacted topic.
#
# HOW COMPACTION WORKS:
#   1. Messages written to "dirty" (not-yet-compacted) segment.
#   2. Log Cleaner thread wakes up when dirty ratio threshold hit.
#   3. Cleaner reads dirty segments, builds a map of key→latest-offset.
#   4. Copies messages to new segments, skipping superseded versions.
#   5. Tombstone: send message with key=X, value=null → deletes key.
#      Tombstone is retained for delete.retention.ms (default 24h).
#
# IMPORTANT: Compaction does NOT guarantee only the latest message
# exists in real time. There's a window where old messages still
# exist. Consumers must handle duplicates.

# Create a compacted topic:
${KAFKA_HOME}/bin/kafka-topics.sh \
    ${BOOTSTRAP} \
    --create \
    --topic user-profiles \
    --partitions 6 \
    --replication-factor 3 \
    --config cleanup.policy=compact \
    --config min.insync.replicas=2 \
    --config min.cleanable.dirty.ratio=0.1 \    # clean when 10% of log is dirty
    --config delete.retention.ms=86400000 \      # keep tombstones for 24h
    --config segment.ms=3600000                  # roll new segment every 1h (cleaner needs segments to compact)

# Send a tombstone to delete a key (value must be null):
echo "user_999:" | \
${KAFKA_HOME}/bin/kafka-console-producer.sh \
    ${BOOTSTRAP} \
    --topic user-profiles \
    --property "parse.key=true" \
    --property "key.separator=:" \
    --property "null.marker=\N"
# key=user_999, value=null → this key will be deleted after compaction


# ============================================================
# SECTION 6: ALTER TOPIC CONFIGURATION
# ============================================================
# You can ADD partitions but NEVER reduce them.
# Reducing partitions would require redistributing messages —
# there's no safe way to do this; messages in removed partitions
# would be lost.

# Add partitions (increase from 12 to 20):
${KAFKA_HOME}/bin/kafka-topics.sh \
    ${BOOTSTRAP} \
    --alter \
    --topic orders \
    --partitions 20
# WARNING: Key-based partition assignment CHANGES after this.
# Messages for key X may now go to a different partition than before.
# Existing messages are NOT redistributed. Plan this carefully.

# Alter topic configuration at runtime (no restart needed):
${KAFKA_HOME}/bin/kafka-configs.sh \
    ${BOOTSTRAP} \
    --alter \
    --entity-type topics \
    --entity-name orders \
    --add-config retention.ms=2592000000  # change retention to 30 days

# Alter broker-level default config:
${KAFKA_HOME}/bin/kafka-configs.sh \
    ${BOOTSTRAP} \
    --alter \
    --entity-type brokers \
    --entity-name 1 \
    --add-config log.retention.hours=168  # 7 days for broker 1

# View current topic config (only overrides from broker defaults):
${KAFKA_HOME}/bin/kafka-configs.sh \
    ${BOOTSTRAP} \
    --describe \
    --entity-type topics \
    --entity-name orders


# ============================================================
# SECTION 7: REPLICA ASSIGNMENT AND ISR
# ============================================================
# REPLICA SET: for each partition, a set of brokers holds a copy.
#   - Partition 0: Leader=broker1, Replicas=[broker1, broker2, broker3]
#
# ISR (In-Sync Replicas): replicas that are caught up with the
# leader (within replica.lag.time.max.ms, default 30s).
# If a follower falls behind, it's removed from ISR.
#
# min.insync.replicas (min.isr): minimum ISR size required for
# a producer write to succeed (when acks=all).
# If ISR drops below this, brokers reject writes with
# NotEnoughReplicasException. Prevents acknowledged data loss.
#
# RULE OF THUMB:
#   replication.factor=3, min.insync.replicas=2
#   → tolerates 1 broker failure with no data loss
#   → tolerates 2 broker failures with write unavailability
#     (but data already acknowledged is safe)

# Check under-replicated partitions (sign of trouble):
${KAFKA_HOME}/bin/kafka-topics.sh \
    ${BOOTSTRAP} \
    --describe \
    --under-replicated-partitions
# Non-empty output = urgent: a broker is down or lagging badly.

# Check offline partitions (no leader — reads AND writes fail):
${KAFKA_HOME}/bin/kafka-topics.sh \
    ${BOOTSTRAP} \
    --describe \
    --unavailable-partitions


# ============================================================
# SECTION 8: PARTITION REASSIGNMENT
# ============================================================
# Use cases:
#   - Added new brokers: move some partitions to new brokers to
#     rebalance disk usage and leader load.
#   - Decommission a broker: move its partitions off first.
#   - Fix uneven leader distribution (preferred leader election).

# Generate a reassignment plan (JSON file):
${KAFKA_HOME}/bin/kafka-reassign-partitions.sh \
    ${BOOTSTRAP} \
    --generate \
    --topics-to-move-json-file topics-to-move.json \
    --broker-list "1,2,3,4"    # target broker IDs including new broker 4
# Outputs: current assignment + proposed reassignment JSON.

# Execute the reassignment:
${KAFKA_HOME}/bin/kafka-reassign-partitions.sh \
    ${BOOTSTRAP} \
    --execute \
    --reassignment-json-file reassignment.json \
    --throttle 50000000    # 50 MB/s throttle to avoid flooding replication

# Monitor progress:
${KAFKA_HOME}/bin/kafka-reassign-partitions.sh \
    ${BOOTSTRAP} \
    --verify \
    --reassignment-json-file reassignment.json

# Trigger preferred leader election (makes original leader reclaim
# leadership after a failover, for even distribution):
${KAFKA_HOME}/bin/kafka-leader-election.sh \
    ${BOOTSTRAP} \
    --election-type PREFERRED \
    --all-topic-partitions


# ============================================================
# SECTION 9: REAL-WORLD TOPIC DESIGN — E-COMMERCE ORDER SYSTEM
# ============================================================
# Topics:
#
#   orders (key: order_id)
#     Partitions: 24 (target: 24 concurrent consumers)
#     Retention: 30 days
#     Events: OrderPlaced, OrderPaid, OrderShipped, OrderDelivered
#     ORDERING: all events for one order are in sequence ✓
#
#   inventory-updates (key: product_id)
#     Partitions: 12
#     Retention: 7 days
#     Events: StockReserved, StockReleased
#
#   user-profiles (key: user_id)
#     Partitions: 6
#     Cleanup policy: COMPACT (latest profile per user)
#     Use as reference table in Kafka Streams joins
#
#   payments (key: payment_id)
#     Partitions: 12
#     Retention: 90 days (compliance)
#     min.insync.replicas: 2 (financial data: extra durability)
#     Enable idempotent + transactional producer (see L05)
#
#   order-events-dlq (Dead Letter Queue)
#     Partitions: 3
#     Retention: 14 days
#     For messages that failed processing after N retries

echo "Kafka partitions and ordering reference loaded."
