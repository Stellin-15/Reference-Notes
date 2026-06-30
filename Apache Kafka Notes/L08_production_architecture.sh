#!/usr/bin/env bash
# =============================================================================
# WHAT: Kafka Production Architecture — Sizing, Tuning, Ops, Security
# WHY:  Running Kafka in production is fundamentally different from dev.
#       Wrong configuration causes data loss, cascading failures, and outages.
#       This file covers every decision an architect must make before go-live.
# LEVEL: Senior / Architect
# =============================================================================

# =============================================================================
# CONCEPT OVERVIEW
# =============================================================================
# Kafka's production story has three dimensions:
#   1. SIZING: How many brokers, partitions, disk, memory, network?
#   2. TUNING: Which config knobs actually matter at scale?
#   3. OPERATIONS: How do you handle failures, upgrades, multi-DC?
#
# Common mistake: copying dev configs to production.
# Dev defaults are wrong for prod. Especially:
#   - replication.factor=1 (dev) → data loss on broker failure
#   - min.insync.replicas=1 (dev) → no write durability guarantee
#   - log.retention.hours=168 (reasonable but must match storage budget)
#   - no security (dev) → open broker, anyone can read/write
# =============================================================================

# =============================================================================
# PRODUCTION USE CASE
# =============================================================================
# E-commerce platform: 500 microservices, 2M events/sec peak, 1KB avg event.
# Requirements:
#   - 99.99% durability (no data loss)
#   - < 10ms producer latency at p99
#   - 7-day retention with S3 tiered storage for 90-day cold access
#   - SOC2 compliance: encryption in transit + at rest, audit logs
#   - Multi-region active-passive for disaster recovery
# =============================================================================

# =============================================================================
# COMMON MISTAKES
# =============================================================================
# 1. Using ZooKeeper in new clusters (deprecated — use KRaft in Kafka 3.3+).
# 2. Putting Kafka on shared storage (NAS/SAN). Must be local SSDs.
# 3. Setting log.flush.interval.ms too low (defeats OS page cache, kills perf).
# 4. Under-sizing page cache (Kafka is an OS page cache machine, not heap).
# 5. Not monitoring consumer lag (lag = the most important Kafka metric).
# 6. Not testing broker failure before going to production.
# 7. Creating too many small topics (each partition has overhead).
# 8. Setting replication factor > number of brokers (impossible to fulfill).
# =============================================================================

set -euo pipefail

echo "=== KAFKA PRODUCTION ARCHITECTURE REFERENCE ==="

# =============================================================================
# SECTION 1: BROKER SIZING CALCULATIONS
# =============================================================================
# Before provisioning, calculate required resources:
#
# THROUGHPUT per broker:
#   - Each broker: ~100-150 MB/s sustained throughput (NVMe SSD, 10GbE).
#   - Account for replication factor: 1GB/s write × RF3 = 3GB/s total disk writes.
#   - Producers write to leader, followers replicate → each byte hits disk 3×.
#
# DISK CAPACITY formula:
#   disk_per_broker = (write_rate_MB_s × retention_seconds × replication_factor)
#                     / num_brokers
#
# Example: 1GB/s write, 7-day retention, RF=3, 6 brokers:
#   = (1000 MB/s × 604800 s × 3) / 6
#   = 302,400,000 MB / 6
#   = ~50 TB per broker (use tiered storage to S3 for anything over 7 days)
#
# MEMORY breakdown:
#   - JVM HEAP: 4-6 GB. More heap = more GC pauses. Kafka is NOT heap-heavy.
#     Most data lives in OS page cache, not heap.
#   - OS PAGE CACHE: This is where Kafka's speed comes from.
#     Kafka reads/writes go to page cache (RAM). OS flushes to disk async.
#     Rule: page cache ≥ working set (data produced in last ~30 minutes).
#     Typical: 32-64 GB RAM per broker, 4-6 GB heap, rest = page cache.
#   - Do NOT run other JVM apps on Kafka brokers (compete for page cache).
#
# NETWORK:
#   - 10 GbE minimum for production. 25 GbE for high-throughput.
#   - Each broker sends AND receives replication traffic simultaneously.
#   - Bandwidth formula: write_rate × (replication_factor + consumer_fanout)
#
# CPU:
#   - Kafka is NOT CPU-bound (unless using SSL — adds ~30% CPU overhead).
#   - 16-32 cores per broker is typical. More cores help with SSL decryption.

calculate_disk_requirement() {
    local write_rate_mb_s="$1"     # MB/s write rate
    local retention_days="$2"      # Retention period in days
    local replication_factor="$3"  # Replication factor (usually 3)
    local num_brokers="$4"         # Number of brokers

    local retention_seconds=$((retention_days * 86400))
    local total_bytes=$(echo "$write_rate_mb_s * $retention_seconds * $replication_factor" | bc)
    local per_broker=$(echo "$total_bytes / $num_brokers / 1024" | bc)

    echo "Write rate: ${write_rate_mb_s} MB/s"
    echo "Retention: ${retention_days} days"
    echo "Replication factor: ${replication_factor}"
    echo "Brokers: ${num_brokers}"
    echo "Required disk per broker: ${per_broker} GB"
    echo "Add 20% headroom: $(echo "$per_broker * 1.2 / 1" | bc) GB"
}

# Example: 500 MB/s write, 7-day retention, RF=3, 6 brokers
# calculate_disk_requirement 500 7 3 6
# Result: ~181 GB per broker (feasible on a single NVMe drive)

# =============================================================================
# SECTION 2: CLUSTER SIZING — NUMBER OF BROKERS
# =============================================================================
# MINIMUM: 3 brokers.
#   - Allows RF=3 (one broker can fail without data loss).
#   - ZooKeeper quorum requires 3 nodes (or 5 for 2-failure tolerance).
#   - KRaft mode also recommends 3+ controller nodes.
#
# PRODUCTION: 5+ brokers.
#   - Allows rolling upgrades without reducing availability.
#   - Distributes partition leadership for better load balance.
#   - Odd numbers matter for ZooKeeper quorum (3, 5, 7).
#     KRaft: even numbers are fine for brokers (controller quorum is separate).
#
# PARTITION COUNT per topic:
#   - Start with: max_expected_consumers × 2 (leave room to scale).
#   - More partitions = more parallelism, but more overhead.
#   - Each partition: ~1MB memory overhead on broker.
#   - 10,000 partitions per broker is a practical limit before performance degrades.
#   - Rule: # partitions = target_throughput_MB_s / throughput_per_partition_MB_s

# =============================================================================
# SECTION 3: KRAFT MODE (KAFKA WITHOUT ZOOKEEPER)
# =============================================================================
# KRaft = Kafka Raft Metadata mode. Kafka 3.3+ production-ready.
# Kafka 4.0: ZooKeeper support REMOVED. All new clusters must use KRaft.
#
# WHY KRaft is better than ZooKeeper mode:
#   1. Eliminates ZooKeeper as a separate system to manage and monitor.
#   2. Faster controller failover: seconds vs 30+ seconds with ZK.
#   3. Supports more partitions: 1M+ partitions in KRaft vs ~200K in ZK.
#   4. Simpler security: one auth system instead of Kafka + ZK security.
#   5. Controller restores metadata from Kafka log (not ZK ephemeral nodes).
#
# KRaft roles:
#   - CONTROLLER: Manages cluster metadata (partition leaders, topic configs).
#     Does NOT serve producer/consumer traffic.
#   - BROKER: Serves client traffic (produce/consume).
#   - COMBINED: Both roles (small clusters only — not recommended for > 10 nodes).
#
# Recommended production layout for KRaft:
#   - 3 dedicated controller nodes (odd number for Raft quorum)
#   - N dedicated broker nodes (scales independently)
#   - Controller nodes: smaller instances (metadata only, not I/O heavy)

generate_kraft_server_properties() {
    local node_id="$1"          # Unique ID for this broker/controller
    local role="$2"             # "broker", "controller", or "controller,broker"
    local cluster_id="$3"       # UUID generated once with kafka-storage.sh
    local log_dir="$4"          # Data directory (must be fast NVMe)

    cat << EOF
# KRaft Mode Configuration — Node ${node_id}
# Role: ${role}

# ====== NODE IDENTITY ======
node.id=${node_id}
process.roles=${role}

# Cluster UUID (generated once: kafka-storage.sh random-uuid)
# ALL nodes in cluster MUST share the same cluster ID.
# cluster.id=${cluster_id}

# ====== CONTROLLER QUORUM ======
# All nodes must know all controller addresses.
# Format: node_id@host:port
controller.quorum.voters=1@controller1:9093,2@controller2:9093,3@controller3:9093

# ====== LISTENERS ======
# PLAINTEXT for internal (dev only). SSL or SASL_SSL for production.
listeners=PLAINTEXT://:9092,CONTROLLER://:9093
advertised.listeners=PLAINTEXT://$(hostname -f):9092
inter.broker.listener.name=PLAINTEXT
controller.listener.names=CONTROLLER

# ====== LOG STORAGE ======
log.dirs=${log_dir}

# ====== REPLICATION ======
# min.insync.replicas: minimum replicas that must acknowledge a write
# before the broker considers it committed (with acks=-1/all on producer).
# Setting this to 2 with RF=3 means: tolerate 1 broker failure.
# Setting this to 3 means: zero tolerance — all must be up to accept writes.
min.insync.replicas=2
default.replication.factor=3

# ====== RETENTION ======
log.retention.hours=168          # 7 days — primary retention
log.retention.bytes=-1           # -1 = no size limit (use time-based)
log.segment.bytes=1073741824     # 1GB segments — balance between compaction and open file handles

# Tiered storage (Kafka 3.6+): offload to S3 after local retention.
# remote.log.storage.system.enable=true
# remote.log.manager.task.interval.ms=30000
EOF
}

# generate_kraft_server_properties 1 "broker" "abc-123" "/data/kafka/logs"

# =============================================================================
# SECTION 4: PERFORMANCE TUNING — CRITICAL KNOBS
# =============================================================================
# Most defaults are fine. These are the ones that actually move the needle.

configure_broker_performance() {
    cat << 'EOF'
# ====== THREAD POOLS ======
# num.network.threads: threads handling network requests.
# Rule: start at 3, increase if you see NetworkProcessorAvgIdlePercent < 30%.
num.network.threads=8

# num.io.threads: threads doing actual disk I/O.
# Rule: 2× num.network.threads, up to 2× number of disks.
num.io.threads=16

# num.replica.fetchers: threads for follower replication per leader broker.
# Increase if replicas lag behind leader (under-replicated partitions alert).
num.replica.fetchers=4

# ====== SOCKET BUFFERS ======
# Increase for high-throughput environments (10GbE+).
# OS must also be configured: sysctl net.core.rmem_max / wmem_max
socket.send.buffer.bytes=1048576       # 1MB send buffer
socket.receive.buffer.bytes=1048576    # 1MB receive buffer
socket.request.max.bytes=104857600     # 100MB max request size

# ====== LOG FLUSHING ======
# LEAVE THESE AT DEFAULT (commented out = OS handles flushing).
# DO NOT set log.flush.interval.ms to a low value.
# WHY: Kafka's durability comes from REPLICATION, not fsync.
# With RF=3 and min.insync.replicas=2, a write is durable even if OS
# hasn't flushed to disk — because it's on 2 different machines.
# Forcing frequent fsync destroys write throughput for no safety benefit.
# log.flush.interval.ms=           # Leave commented = OS default
# log.flush.interval.messages=     # Leave commented = OS default

# ====== MESSAGE SIZE ======
# Increase only if you have large events (e.g., CDC with large rows).
# Large messages hurt performance — prefer chunking at application level.
message.max.bytes=10485760             # 10MB max message size (default 1MB)

# ====== COMPRESSION ======
# Broker-side compression for topics that didn't compress at producer.
# LZ4 is best balance of speed vs compression ratio for Kafka.
# compression.type=lz4               # Per-topic config

# ====== GROUP COORDINATOR ======
# For clusters with many consumer groups (100s+), tune these.
group.initial.rebalance.delay.ms=3000  # Wait 3s before first rebalance
                                        # Allows all consumers to join before
                                        # assigning partitions. Reduces rebalances.
EOF
}

# =============================================================================
# SECTION 5: MULTI-DATACENTER WITH MIRRORMAKER 2
# =============================================================================
# MirrorMaker 2 (MM2) replicates Kafka topics between clusters.
# Built on Kafka Connect framework. Handles offset translation automatically.
#
# ACTIVE-PASSIVE (most common):
#   - Primary cluster: all writes. Consumers read from primary.
#   - Secondary cluster: replica for disaster recovery.
#   - MM2 replicates PRIMARY → SECONDARY continuously.
#   - On failover: consumers redirect to secondary. Offsets translated by MM2.
#   - Topic names on secondary: "primary-cluster.original-topic-name"
#
# ACTIVE-ACTIVE (complex):
#   - Both clusters accept writes from regional users.
#   - MM2 replicates both directions.
#   - Risk: infinite replication loops (MM2 uses cycle detection to prevent).
#   - Topic prefixing: us-east.payments vs eu-west.payments.
#   - Consumer group offset sync: MM2 syncs offsets so failover is seamless.
#
# When to use ACTIVE-ACTIVE:
#   - Geo-distributed writes with strict latency requirements per region.
#   - Regulatory: EU data must stay in EU unless replicated as anonymized copy.
#   - Complex to operate. Most orgs use active-passive unless forced.

configure_mirrormaker2() {
    cat << 'EOF'
# MirrorMaker 2 Configuration (connect-mirror-maker.properties)
# Run as: connect-mirror-maker.sh connect-mirror-maker.properties

# Source and target cluster aliases
clusters = primary, secondary

# Source cluster connection
primary.bootstrap.servers = kafka-primary-1:9092,kafka-primary-2:9092,kafka-primary-3:9092
secondary.bootstrap.servers = kafka-secondary-1:9092,kafka-secondary-2:9092

# Replication direction: primary → secondary
primary->secondary.enabled = true
secondary->primary.enabled = false     # Active-passive: no reverse replication

# Topic whitelist (regex). Replicate everything except internal topics.
primary->secondary.topics = .*
primary->secondary.topics.blacklist = .*\.internal, __.*

# Consumer group offset sync.
# MM2 periodically syncs consumer group offsets from primary to secondary.
# On failover, consumers can start from correct position on secondary.
primary->secondary.sync.group.offsets.enabled = true
primary->secondary.sync.group.offsets.interval.seconds = 60

# Replication factor for replicated topics on secondary.
replication.factor = 3

# How many MirrorMaker tasks (parallel replication workers).
# Set equal to number of source topic partitions / worker instances.
tasks.max = 10

# Offset lag threshold for alerting.
# If MM2 lags > 60 seconds behind primary, something is wrong.
# Monitor: kafka_mirrormaker_record_age_ms metric in Prometheus.
EOF
}

# =============================================================================
# SECTION 6: MONITORING — WHAT TO WATCH
# =============================================================================
# Kafka is opaque without proper monitoring. These are the metrics that matter.

setup_monitoring_checklist() {
    cat << 'EOF'
# ====== TIER 1: PAGE YOUR ON-CALL IMMEDIATELY ======
# These metrics indicate active data loss or unavailability.

# 1. CONSUMER LAG — the most important Kafka metric.
#    Lag = (latest offset in partition) - (consumer's committed offset).
#    Rising lag = consumers can't keep up with producers.
#    Critical lag threshold depends on retention: if lag × msg_rate > retention,
#    consumers will lose messages (offset falls behind retention window).
#    Tool: Burrow (LinkedIn), kafka-consumer-groups.sh, or Prometheus kafka_consumer_group_lag

# 2. UNDER-REPLICATED PARTITIONS (URP)
#    Any partition where ISR < replication factor.
#    Means a broker is down or a follower is falling behind.
#    JMX: kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions
#    Alert threshold: > 0

# 3. OFFLINE PARTITIONS
#    Partitions with no leader elected.
#    Means data is unavailable for reads and writes.
#    JMX: kafka.controller:type=KafkaController,name=OfflinePartitionsCount
#    Alert threshold: > 0 (any offline partition = outage)

# 4. ISR SHRINK RATE
#    Rate at which replicas are removed from ISR (In-Sync Replica set).
#    High ISR shrink = brokers struggling to keep up with replication.
#    JMX: kafka.server:type=ReplicaManager,name=IsrShrinksPerSec

# ====== TIER 2: INVESTIGATE WITHIN 1 HOUR ======

# 5. DISK USAGE
#    Alert at 70% (give time to add storage or clean up before hitting 100%).
#    Kafka does not handle full disks gracefully (becomes unavailable).

# 6. NETWORK BYTES IN/OUT
#    Watch for saturation on 10GbE links.
#    Broker network saturated = producers/consumers experience high latency.

# 7. REQUEST LATENCY (Produce and Fetch)
#    JMX: kafka.network:type=RequestMetrics,name=TotalTimeMs,request=Produce
#    Alert if p99 > 100ms for produce or p99 > 200ms for fetch.

# 8. ACTIVE CONTROLLER COUNT
#    Should always be exactly 1. 0 = no controller (no topic creation/deletion).
#    > 1 = split brain (serious bug condition).
#    JMX: kafka.controller:type=KafkaController,name=ActiveControllerCount

# ====== MONITORING STACK ======
# JMX Exporter → Prometheus → Grafana.
# Use Confluent's kafka-lag-exporter or LinkedIn's Burrow for consumer lag.
# Pre-built Grafana dashboards: grafana.com/grafana/dashboards/7589 (Kafka Overview)

echo "Monitoring reference printed. See comments above."
EOF
}

# =============================================================================
# SECTION 7: SECURITY CONFIGURATION
# =============================================================================
# Production Kafka MUST have:
#   1. Encryption in transit (SSL/TLS): prevents eavesdropping.
#   2. Authentication (SASL): proves identity of clients and brokers.
#   3. Authorization (ACLs): limits what each client can do.
#
# Common auth options:
#   SASL/PLAIN: username/password over TLS. Simple, supported everywhere.
#     Problem: credentials in plaintext in client config files.
#   SASL/SCRAM-SHA-256: password hashing. Credentials stored in ZK/KRaft.
#     Better than PLAIN — no plaintext storage needed.
#   SASL/GSSAPI (Kerberos): enterprise standard. Complex to set up.
#     Use if already have Active Directory / MIT Kerberos infrastructure.
#   SASL/OAUTHBEARER: OAuth 2.0 JWT tokens. Modern, works with cloud IdPs.
#     Best for cloud-native environments (Okta, AWS Cognito, Azure AD).

configure_ssl_sasl() {
    cat << 'EOF'
# Broker: server.properties — SSL + SASL/SCRAM configuration

# ====== SSL (encryption in transit) ======
ssl.keystore.location=/etc/kafka/ssl/kafka.broker.keystore.jks
ssl.keystore.password=<keystore-password>
ssl.key.password=<key-password>
ssl.truststore.location=/etc/kafka/ssl/kafka.broker.truststore.jks
ssl.truststore.password=<truststore-password>

# Require client certificates? Yes for mTLS (mutual TLS).
# mTLS = both server AND client present certificates. Strongest auth.
# ssl.client.auth=required       # mTLS (strongest)
ssl.client.auth=none             # Server-only TLS (clients use SASL for auth)

# Which TLS protocols to allow. Disable TLSv1.0 and TLSv1.1 (insecure).
ssl.enabled.protocols=TLSv1.2,TLSv1.3
ssl.protocol=TLSv1.3

# ====== SASL/SCRAM authentication ======
# SCRAM stores hashed credentials in Kafka's metadata (ZK or KRaft).
# Create user: kafka-configs.sh --alter --add-config 'SCRAM-SHA-256=[password=secret]'
sasl.enabled.mechanisms=SCRAM-SHA-256
sasl.mechanism.inter.broker.protocol=SCRAM-SHA-256

# Listener for SASL_SSL (authenticated + encrypted) clients.
# Separate listener for PLAINTEXT inside VPC (brokers talking to each other).
listeners=SASL_SSL://:9093,PLAINTEXT://:9092
advertised.listeners=SASL_SSL://$(hostname -f):9093,PLAINTEXT://$(hostname -f):9092
inter.broker.listener.name=PLAINTEXT   # Brokers talk to each other on internal PLAINTEXT
                                        # (inside same VPC security group — acceptable)

# JAAS config for broker's own credentials (for inter-broker SASL).
listener.name.sasl_ssl.scram-sha-256.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required \
    username="kafka-broker" \
    password="<broker-internal-password>";

# ====== ACLs (authorization) ======
# Enable ACL authorizer.
authorizer.class.name=org.apache.kafka.metadata.authorizer.StandardAuthorizer
allow.everyone.if.no.acl.found=false    # Default-deny. Explicit allow required.
super.users=User:kafka-admin            # Super users bypass ACL checks.
EOF
}

manage_acls() {
    # Grant a service account read/write access to specific topics.
    # This is least-privilege: the payment service can ONLY access payment topics.
    local BOOTSTRAP="localhost:9093"
    local COMMAND_CONFIG="--command-config /etc/kafka/admin.properties"

    echo "Creating ACLs for payment-service principal..."

    # Allow payment-service to WRITE to the payments topic (producer ACL).
    kafka-acls.sh \
        --bootstrap-server "$BOOTSTRAP" \
        $COMMAND_CONFIG \
        --add \
        --allow-principal "User:payment-service" \
        --operation Write \
        --operation Describe \
        --topic "payments.billing.transaction.created"

    # Allow fraud-detection-service to READ from payments topic (consumer ACL).
    # Also needs group access to manage its consumer group offset.
    kafka-acls.sh \
        --bootstrap-server "$BOOTSTRAP" \
        $COMMAND_CONFIG \
        --add \
        --allow-principal "User:fraud-detection-service" \
        --operation Read \
        --operation Describe \
        --topic "payments.billing.transaction.created"

    kafka-acls.sh \
        --bootstrap-server "$BOOTSTRAP" \
        $COMMAND_CONFIG \
        --add \
        --allow-principal "User:fraud-detection-service" \
        --operation Read \
        --group "fraud-detection-consumer-group"

    echo "ACLs created. Verify with: kafka-acls.sh --list --bootstrap-server $BOOTSTRAP $COMMAND_CONFIG"
}

# =============================================================================
# SECTION 8: KAFKA CONNECT — PRODUCTION PATTERNS
# =============================================================================
# Kafka Connect: framework for building reliable, scalable data pipelines.
# Source connectors: external system → Kafka.
# Sink connectors: Kafka → external system.
# Runs as a cluster of workers. Connectors distributed across workers.

manage_connectors_via_rest_api() {
    local CONNECT_URL="http://localhost:8083"

    echo "=== Creating Debezium MySQL CDC Source Connector ==="
    # Debezium captures every INSERT/UPDATE/DELETE from MySQL binlog.
    # Translates DB changes into Kafka events. Used for event sourcing, CDC, migration.
    # Each table gets its own topic: <server-name>.<database>.<table>
    curl -X POST "$CONNECT_URL/connectors" \
         -H "Content-Type: application/json" \
         -d '{
           "name": "mysql-payments-cdc",
           "config": {
             "connector.class": "io.debezium.connector.mysql.MySqlConnector",
             "database.hostname": "mysql-primary.internal",
             "database.port": "3306",
             "database.user": "debezium",
             "database.password": "${file:/etc/kafka/connect-secrets.properties:mysql.password}",
             "database.server.id": "1",
             "topic.prefix": "mysql-prod",
             "database.include.list": "payments",
             "table.include.list": "payments.transactions,payments.users",
             "schema.history.internal.kafka.topic": "schema-changes.mysql-prod",
             "schema.history.internal.kafka.bootstrap.servers": "kafka1:9092,kafka2:9092",
             "transforms": "unwrap",
             "transforms.unwrap.type": "io.debezium.transforms.ExtractNewRecordState",
             "transforms.unwrap.drop.tombstones": "false"
           }
         }'

    echo ""
    echo "=== Creating S3 Sink Connector (tiered storage / data lake) ==="
    curl -X POST "$CONNECT_URL/connectors" \
         -H "Content-Type: application/json" \
         -d '{
           "name": "s3-payments-sink",
           "config": {
             "connector.class": "io.confluent.connect.s3.S3SinkConnector",
             "tasks.max": "10",
             "topics.regex": "payments\\..*",
             "s3.region": "us-east-1",
             "s3.bucket.name": "company-kafka-archive",
             "s3.part.size": "67108864",
             "flush.size": "100000",
             "rotate.interval.ms": "3600000",
             "storage.class": "io.confluent.connect.s3.storage.S3Storage",
             "format.class": "io.confluent.connect.s3.format.parquet.ParquetFormat",
             "parquet.codec": "snappy",
             "locale": "US",
             "timezone": "UTC",
             "timestamp.extractor": "RecordField",
             "timestamp.field": "event_time"
           }
         }'

    # List all connectors
    echo ""
    echo "=== Active Connectors ==="
    curl -s "$CONNECT_URL/connectors" | python3 -m json.tool

    # Check connector status (should be RUNNING, not FAILED)
    echo "=== Connector Status ==="
    curl -s "$CONNECT_URL/connectors/mysql-payments-cdc/status" | python3 -m json.tool
}

# =============================================================================
# SECTION 9: OPERATIONAL RUNBOOKS
# =============================================================================
# These are the commands you run at 3am when something breaks.

runbook_consumer_group_reset() {
    # SCENARIO: Consumer deployed bad code, processed messages incorrectly.
    # Need to rewind offsets to reprocess from a point in time.
    local GROUP_ID="$1"
    local TOPIC="$2"
    local BOOTSTRAP="localhost:9092"

    echo "=== RUNBOOK: Reset consumer group offsets ==="
    echo "WARNING: Stop all consumers in group before resetting offsets!"
    echo ""

    # View current lag and offsets
    kafka-consumer-groups.sh \
        --bootstrap-server "$BOOTSTRAP" \
        --describe \
        --group "$GROUP_ID"

    echo ""
    echo "=== Reset to earliest offset (reprocess all retained messages) ==="
    # --dry-run first! Always preview before executing.
    kafka-consumer-groups.sh \
        --bootstrap-server "$BOOTSTRAP" \
        --group "$GROUP_ID" \
        --topic "$TOPIC" \
        --reset-offsets \
        --to-earliest \
        --dry-run                    # Remove --dry-run to actually execute

    echo ""
    echo "=== Reset to specific datetime (reprocess from 2025-01-15 00:00 UTC) ==="
    kafka-consumer-groups.sh \
        --bootstrap-server "$BOOTSTRAP" \
        --group "$GROUP_ID" \
        --topic "$TOPIC" \
        --reset-offsets \
        --to-datetime "2025-01-15T00:00:00.000" \
        --dry-run                    # Remove --dry-run to execute

    echo ""
    echo "=== Reset to latest (skip all current backlog) ==="
    kafka-consumer-groups.sh \
        --bootstrap-server "$BOOTSTRAP" \
        --group "$GROUP_ID" \
        --topic "$TOPIC" \
        --reset-offsets \
        --to-latest \
        --dry-run
}

runbook_broker_failure() {
    # SCENARIO: One broker is down. What's the blast radius?
    local BOOTSTRAP="localhost:9092"

    echo "=== RUNBOOK: Broker Failure Assessment ==="

    # Check under-replicated partitions (partitions without full ISR)
    echo "Under-replicated partitions (should be 0 in normal operation):"
    kafka-topics.sh \
        --bootstrap-server "$BOOTSTRAP" \
        --describe \
        --under-replicated-partitions

    # Check offline partitions (NO leader = unavailable)
    echo ""
    echo "Offline partitions (these topics are UNAVAILABLE for reads/writes):"
    kafka-topics.sh \
        --bootstrap-server "$BOOTSTRAP" \
        --describe \
        --unavailable-partitions

    echo ""
    echo "With RF=3 and min.insync.replicas=2:"
    echo "  - 1 broker down: cluster continues, 1 URP per affected partition"
    echo "  - 2 brokers down: writes BLOCKED (only 1 ISR, below min.insync.replicas=2)"
    echo "  - 3 brokers down: complete outage"
    echo ""
    echo "Recovery: Restart failed broker. It will rejoin ISR automatically."
    echo "  Replica catch-up time depends on: lag_size / replication_throttle_rate"
    echo "  Monitor: kafka.server:type=ReplicaFetcherManager,name=MaxLag"
}

# =============================================================================
# SECTION 10: TOPIC NAMING CONVENTIONS AND CAPACITY PLANNING
# =============================================================================

topic_naming_convention() {
    cat << 'EOF'
# TOPIC NAMING CONVENTION: team.service.entity.event
# ====================================================
# Format: <team>.<service>.<entity>.<event-type>
#
# Examples:
#   payments.billing.invoice.created
#   payments.billing.invoice.updated
#   identity.users.profile.updated
#   risk.fraud.alert.triggered
#   inventory.warehouse.stock.depleted
#   orders.checkout.cart.abandoned
#
# WHY this convention matters:
#   1. ACLs can be applied per-prefix: "payments.*" → payment team owns all payment topics
#   2. Mirror rules: replicate "payments.*" to secondary cluster
#   3. S3 sink: partition by team/service in S3 key prefix
#   4. Schema Registry subjects: <topic-name>-value auto-naming works cleanly
#   5. Monitoring: aggregate lag by team prefix
#
# ANTI-PATTERNS (don't do these):
#   - Generic names: "events", "messages", "data" (ambiguous, hard to govern)
#   - CamelCase: paymentCreated (hard to ACL with prefix matching)
#   - Version in topic name: payments-v2 (use Schema Registry for evolution)
#   - Environment in topic name: payments-prod (use separate clusters per env)

# CAPACITY PLANNING WORKSHEET
# ============================
# Given: 1M events/sec, 1KB average event size
#
# Write throughput:
#   1,000,000 events/s × 1,024 bytes = ~1 GB/s raw
#
# With replication factor 3:
#   Disk write rate per cluster = 1 GB/s × 3 = 3 GB/s
#   (leader writes 1×, 2 followers replicate independently)
#
# 7-day retention:
#   3 GB/s × 86,400 s/day × 7 days = ~1.8 PB total cluster storage
#   Across 18 brokers: ~100 TB per broker (use 120TB NVMe JBOD per broker)
#
# With tiered storage (local 24h, S3 for remainder):
#   Local: 3 GB/s × 86,400 s × 1 day = ~260 TB cluster / 18 brokers ≈ 15 TB each
#   S3: handles 6-day overflow (~1.5 PB, cost: ~$34K/month at $0.023/GB)
#
# Network:
#   1 GB/s write × replication factor 3 × 2 (in+out) ≈ 6 GB/s per cluster
#   Across 18 brokers: 333 MB/s per broker
#   Well within 10GbE (1,250 MB/s) per broker
EOF
}

echo "=== Kafka Production Architecture Reference Complete ==="
echo "Run individual functions as needed for operations."
