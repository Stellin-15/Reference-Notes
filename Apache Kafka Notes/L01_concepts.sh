#!/usr/bin/env bash
# ============================================================
# L01: Kafka Core Concepts — Distributed Commit Log
# ============================================================
# WHAT: Apache Kafka is a distributed, fault-tolerant, high-throughput
#       event streaming platform. It is NOT a traditional message queue.
#       It is a DISTRIBUTED COMMIT LOG — an append-only, ordered, durable
#       sequence of records that consumers can read from at any offset.
#
# WHY:  Traditional queues (RabbitMQ, SQS) delete messages after delivery.
#       Kafka RETAINS messages for a configurable period (days/weeks/forever).
#       This enables: replay, auditing, multiple independent consumers, and
#       temporal decoupling between producers and consumers.
#
# LEVEL: Foundations
# ============================================================
# CONCEPT OVERVIEW:
#
#   TOPIC      — A named, ordered, durable stream of records. Think of it
#                as a table in a database that only supports appends.
#                e.g., "user-events", "order-created", "payment-processed"
#
#   PARTITION  — A topic is split into N partitions. Each partition is an
#                independent, ordered, immutable log. Partitions are the
#                unit of parallelism in Kafka. More partitions = more
#                throughput but more overhead.
#
#   OFFSET     — An integer position within a partition. Every record has
#                a unique offset. Consumers track their position by storing
#                the last-read offset. Offset 0 is the oldest record.
#
#   BROKER     — A Kafka server node. A cluster has 3+ brokers for HA.
#                Each broker holds a subset of partitions. One broker is
#                the "controller" that manages metadata.
#
#   LEADER     — Each partition has exactly one leader broker that handles
#                all reads and writes for that partition.
#
#   FOLLOWER   — Replica brokers that replicate from the leader.
#                They serve reads only when configured to do so.
#
#   ISR        — In-Sync Replicas. Followers that are caught up with the
#                leader within replica.lag.time.max.ms. Only ISR members
#                can become the new leader on failover.
#
#   REPLICATION FACTOR — How many copies of each partition exist across
#                brokers. RF=3 means 1 leader + 2 followers. Survives
#                loss of 2 brokers before data loss (with acks=all).
#
#   PRODUCER   — Client that appends records to topics. Producers choose
#                which partition to write to (round-robin or key-based).
#
#   CONSUMER   — Client that reads records from topics. Consumers track
#                their own offsets — Kafka does NOT push to consumers.
#                Consumers PULL at their own pace.
#
#   CONSUMER GROUP — N consumers sharing the work of reading a topic.
#                Each partition is assigned to exactly ONE consumer in
#                the group. Enables horizontal scaling of consumption.
#
#   ZOOKEEPER  — Legacy coordination service (Kafka < 3.0). Manages
#                broker metadata, leader election, ACLs.
#
#   KRAFT      — KRaft = Kafka Raft. Kafka 3.x+ replaces ZooKeeper with
#                an internal Raft consensus protocol. Simpler to operate.
#
# PRODUCTION USE CASE:
#   Uber: trip events → Kafka → real-time surge pricing, fraud detection,
#         driver dispatch, analytics — all from the SAME stream, independently.
#   LinkedIn (Kafka's origin): activity tracking, metrics pipeline, ~7 trillion
#         messages/day. Replay lets new consumers process historical data.
#
# COMMON MISTAKES:
#   1. Treating Kafka like RabbitMQ — deleting messages after processing.
#      Kafka retains by design; multiple systems can consume independently.
#   2. Too few partitions — you can INCREASE but NEVER DECREASE partitions.
#      Key-based ordering breaks when you increase partitions later.
#      Plan capacity upfront.
#   3. Ignoring replication factor in dev — always RF=3 in production.
#   4. ZooKeeper in new deployments — use KRaft mode for Kafka 3.3+.
# ============================================================

# ============================================================
# KAFKA vs. ALTERNATIVES
# ============================================================
# RabbitMQ:
#   - Traditional queue, AMQP protocol, complex routing (exchanges/bindings)
#   - Messages deleted after ACK — no replay
#   - Best for: task queues, RPC, complex routing logic
#   - Throughput: ~50k msgs/sec per node
#
# Amazon SQS:
#   - Managed queue, at-least-once, 14-day max retention
#   - No consumer groups, no ordering (FIFO queues have limits)
#   - Best for: simple decoupling in AWS, serverless
#
# Apache Kafka:
#   - Distributed log, replay, long retention (forever with tiered storage)
#   - Ordered within partition, consumer groups, stream processing
#   - Best for: event sourcing, CDC, stream processing, audit logs
#   - Throughput: millions of msgs/sec per cluster
#
# Apache Pulsar:
#   - Kafka alternative with separate compute/storage (BookKeeper)
#   - Multi-tenancy built-in, geo-replication native
#   - Growing ecosystem but smaller than Kafka's

# ============================================================
# DOCKER-COMPOSE: Single-node Kafka Cluster (KRaft mode, Kafka 3.6)
# ============================================================
# Save as docker-compose.yml and run: docker-compose up -d
cat << 'DOCKER_COMPOSE_EOF'
# docker-compose.yml
version: '3.8'
services:
  kafka:
    image: confluentinc/cp-kafka:7.6.0
    hostname: kafka
    container_name: kafka
    ports:
      - "9092:9092"      # External client port
      - "9093:9093"      # Controller port (KRaft)
      - "9101:9101"      # JMX metrics port
    environment:
      # KRaft mode — no ZooKeeper required
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: 'broker,controller'   # Combined mode for dev
      KAFKA_CONTROLLER_QUORUM_VOTERS: '1@kafka:9093'

      # Listeners: PLAINTEXT for clients, CONTROLLER for Raft
      KAFKA_LISTENERS: 'PLAINTEXT://kafka:29092,CONTROLLER://kafka:9093,PLAINTEXT_HOST://0.0.0.0:9092'
      KAFKA_ADVERTISED_LISTENERS: 'PLAINTEXT://kafka:29092,PLAINTEXT_HOST://localhost:9092'
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: 'CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT'
      KAFKA_CONTROLLER_LISTENER_NAMES: 'CONTROLLER'
      KAFKA_INTER_BROKER_LISTENER_NAME: 'PLAINTEXT'

      # Replication — use RF=3 in production; RF=1 only for dev
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 1

      # Retention: 7 days default
      KAFKA_LOG_RETENTION_HOURS: 168
      KAFKA_LOG_SEGMENT_BYTES: 1073741824   # 1 GB per segment file

      # JMX for monitoring (Grafana/JMX Exporter)
      KAFKA_JMX_PORT: 9101
      KAFKA_JMX_HOSTNAME: localhost

      # Auto-create topics — disable in production!
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: 'false'

      # Generate cluster ID (run once: kafka-storage random-uuid)
      CLUSTER_ID: 'MkU3OEVBNTcwNTJENDM2Qk'

  # Schema Registry — required for Avro/Protobuf in production
  schema-registry:
    image: confluentinc/cp-schema-registry:7.6.0
    hostname: schema-registry
    container_name: schema-registry
    depends_on:
      - kafka
    ports:
      - "8081:8081"
    environment:
      SCHEMA_REGISTRY_HOST_NAME: schema-registry
      SCHEMA_REGISTRY_KAFKASTORE_BOOTSTRAP_SERVERS: 'kafka:29092'
      SCHEMA_REGISTRY_LISTENERS: http://0.0.0.0:8081

  # Kafka UI — web dashboard for browsing topics and messages
  kafka-ui:
    image: provectuslabs/kafka-ui:latest
    container_name: kafka-ui
    depends_on:
      - kafka
      - schema-registry
    ports:
      - "8080:8080"
    environment:
      KAFKA_CLUSTERS_0_NAME: local
      KAFKA_CLUSTERS_0_BOOTSTRAPSERVERS: kafka:29092
      KAFKA_CLUSTERS_0_SCHEMAREGISTRY: http://schema-registry:8081
DOCKER_COMPOSE_EOF


# ============================================================
# SECTION 1: kafka-topics.sh — Topic Administration
# ============================================================
# kafka-topics.sh is the CLI tool for managing topics.
# In Docker: docker exec -it kafka kafka-topics

# --- Create a topic ---
# --replication-factor 1  : Only 1 copy (dev only! Use 3 in production)
# --partitions 6          : 6 partitions = 6 parallel consumers max
# --config retention.ms   : Keep messages for 7 days (604800000 ms)
kafka-topics.sh \
  --bootstrap-server localhost:9092 \
  --create \
  --topic user-events \
  --partitions 6 \
  --replication-factor 1 \
  --config retention.ms=604800000 \
  --config cleanup.policy=delete      # 'delete' or 'compact' or 'delete,compact'

# --- Describe a topic (shows partition leaders, ISR, replicas) ---
# Output shows which broker is leader for each partition.
# If ISR != Replicas, followers are lagging — investigate immediately.
kafka-topics.sh \
  --bootstrap-server localhost:9092 \
  --describe \
  --topic user-events

# Expected output format:
# Topic: user-events  TopicId: abc123  PartitionCount: 6  ReplicationFactor: 1
# Topic: user-events  Partition: 0  Leader: 1  Replicas: 1  Isr: 1
# Topic: user-events  Partition: 1  Leader: 1  Replicas: 1  Isr: 1

# --- List all topics ---
kafka-topics.sh \
  --bootstrap-server localhost:9092 \
  --list

# --- Delete a topic (irreversible — data is gone) ---
# delete.topic.enable must be true in broker config (default true in Kafka 2+)
kafka-topics.sh \
  --bootstrap-server localhost:9092 \
  --delete \
  --topic user-events

# --- Alter topic configuration (e.g., increase retention) ---
# You can increase partitions but NEVER decrease them.
kafka-topics.sh \
  --bootstrap-server localhost:9092 \
  --alter \
  --topic user-events \
  --partitions 12   # Scale out partitions — ordering by key changes!

# Update config at runtime (no restart needed)
kafka-configs.sh \
  --bootstrap-server localhost:9092 \
  --entity-type topics \
  --entity-name user-events \
  --alter \
  --add-config retention.ms=86400000   # Change to 1 day


# ============================================================
# SECTION 2: kafka-console-producer.sh — Manual Test Producer
# ============================================================
# For testing, debugging, and quick verification.
# In production, use the confluent-kafka Python/Java library.

# --- Basic producer: type messages, press Enter to send ---
# Each line becomes one Kafka record.
kafka-console-producer.sh \
  --bootstrap-server localhost:9092 \
  --topic user-events

# --- Producer with key (key:value format separated by ':') ---
# key.separator=:  means ":" splits key from value
# parse.key=true   means the first field IS the key (used for partitioning)
# Same key always goes to same partition — order guaranteed per key.
kafka-console-producer.sh \
  --bootstrap-server localhost:9092 \
  --topic user-events \
  --property key.separator=: \
  --property parse.key=true
# Input:  user123:{"event":"click","page":"/home"}
# Key=user123, Value={"event":"click","page":"/home"}

# --- Producer with acks=all (durability mode) ---
# acks=all: wait for ALL ISR replicas to acknowledge before returning
# This is the safest mode — use in production for critical data
kafka-console-producer.sh \
  --bootstrap-server localhost:9092 \
  --topic user-events \
  --producer-property acks=all \
  --producer-property retries=3


# ============================================================
# SECTION 3: kafka-console-consumer.sh — Manual Test Consumer
# ============================================================

# --- Read from LATEST (only new messages arriving now) ---
kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic user-events

# --- Read from BEGINNING (replay all historical messages) ---
# This is Kafka's superpower vs. RabbitMQ — you can always go back.
kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic user-events \
  --from-beginning

# --- Read with consumer group (enables offset tracking) ---
# Run multiple times with same group-id: each consumer gets different partitions
# Run with different group-id: independent consumption, own offset tracking
kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic user-events \
  --group my-consumer-group \
  --from-beginning

# --- Print key and value (separated by TAB) ---
kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic user-events \
  --from-beginning \
  --property print.key=true \
  --property key.separator="\t"   # Tab-separated key\tvalue output

# --- Read from a specific partition and offset ---
# Useful for debugging: "show me what's at partition 2, offset 1000"
kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic user-events \
  --partition 2 \
  --offset 1000 \
  --max-messages 10   # Read exactly 10 messages then exit


# ============================================================
# SECTION 4: Consumer Group Management
# ============================================================

# --- List all consumer groups ---
kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 \
  --list

# --- Describe a consumer group (shows LAG per partition) ---
# LAG = (Latest Offset) - (Consumer Offset)
# LAG > 0 means consumers are behind — critical metric to monitor!
kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 \
  --group my-consumer-group \
  --describe

# Output columns:
# GROUP            TOPIC        PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG  CONSUMER-ID
# my-consumer-group user-events  0          1000            1050            50   consumer-1
# my-consumer-group user-events  1          2000            2000            0    consumer-2

# --- Reset offsets (replay from beginning) ---
# WARNING: This repositions the consumer group — use with caution!
# --to-earliest : reset to offset 0 (replay everything)
# --to-latest   : reset to end (skip all existing messages)
# --to-offset N : reset to specific offset N
# --to-datetime : reset to specific timestamp
kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 \
  --group my-consumer-group \
  --topic user-events \
  --reset-offsets \
  --to-earliest \
  --execute   # Without --execute, it's a dry run (safe to test!)


# ============================================================
# SECTION 5: kafka-console-producer performance test
# ============================================================
# Measure how fast your cluster can ingest messages

kafka-producer-perf-test.sh \
  --topic user-events \
  --num-records 1000000 \
  --record-size 1024 \
  --throughput -1 \   # -1 = no rate limit (max speed)
  --producer-props bootstrap.servers=localhost:9092 acks=1

# Output: 1000000 records sent, 250000 records/sec, latency avg 4ms, max 50ms

kafka-consumer-perf-test.sh \
  --bootstrap-server localhost:9092 \
  --topic user-events \
  --messages 1000000 \
  --group perf-test-group
