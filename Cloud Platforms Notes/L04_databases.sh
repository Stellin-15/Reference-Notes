#!/usr/bin/env bash
# ============================================================
# L04: Cloud Database Services
# ============================================================
# WHAT: A reference guide and AWS CLI walkthrough covering the
#       major managed database services across AWS, GCP, and Azure.
#       Includes architecture decisions, trade-off analysis,
#       and real CLI commands to provision an Aurora Postgres stack.
# WHY:  Choosing the wrong database for a workload is expensive to fix.
#       Managed services eliminate operational overhead (patching,
#       backups, HA) but each has a different sweet spot. Knowing
#       WHEN to use Aurora vs DynamoDB vs Redshift is as important
#       as knowing HOW to use them.
# LEVEL: Advanced
# ============================================================
# CONCEPT OVERVIEW:
#   Cloud databases fall into four categories:
#     1. Relational (OLTP): Aurora, RDS, Cloud SQL, Azure SQL
#        → transactional workloads, ACID guarantees, complex queries
#     2. In-memory cache: ElastiCache Redis, Memorystore
#        → sub-millisecond reads, ephemeral data, leaderboards, sessions
#     3. NoSQL KV/Document: DynamoDB, Firestore, Cosmos DB
#        → massive scale, simple access patterns, flexible schema
#     4. Analytical (OLAP): Redshift, BigQuery, Azure Synapse
#        → aggregate queries over billions of rows, columnar storage
#
# PRODUCTION USE CASE:
#   Multi-tier application:
#     App servers → RDS Proxy → Aurora Postgres (primary writes)
#                             → Aurora Replica   (heavy read queries)
#     App servers → ElastiCache Redis (session store, query cache)
#     ETL pipeline → Redshift (analytics, BI dashboards)
#     IoT events  → DynamoDB (high-volume, simple KV, no joins)
#
# COMMON MISTAKES:
#   1. Not using RDS Proxy with Lambda → each invocation opens a new
#      DB connection, exhausting Postgres connection limit (default 100).
#   2. Using DynamoDB for workloads with unpredictable access patterns
#      that require table scans → full scan reads every item, costs are huge.
#   3. Setting Multi-AZ but reading from the standby → standby is NOT
#      readable. It's only for failover. Use read replicas for read scaling.
#   4. Not setting connect_timeout on the app side → Aurora Multi-AZ failover
#      takes ~60s. Without timeout the app hangs silently for minutes.
#   5. inferSchema on Redshift COPY → always define schema explicitly.

set -euo pipefail

# ── Helper: pretty section header ────────────────────────────
section() { echo; echo "═══════════════════════════════════════════"; echo "  $1"; echo "═══════════════════════════════════════════"; }

# ══════════════════════════════════════════════════════════════
# SECTION 1: Amazon RDS (Managed Relational Database)
# ══════════════════════════════════════════════════════════════
# RDS supports: PostgreSQL, MySQL, MariaDB, Oracle, SQL Server.
# What RDS MANAGES FOR YOU (you don't do any of this):
#   - Automated daily snapshots (configurable 1-35 day retention)
#   - Minor version patching (with maintenance window)
#   - Multi-AZ standby management (auto-failover in ~60s)
#   - Storage auto-scaling (set max threshold)
#   - Enhanced Monitoring, Performance Insights
#   - Encryption at rest (KMS) and in transit (TLS)
#
# What YOU STILL MANAGE:
#   - Schema design and migrations (Alembic, Flyway)
#   - Query performance and indexing (EXPLAIN ANALYZE)
#   - Connection pooling (PgBouncer, RDS Proxy)
#   - Application-level retry logic

section "RDS CONCEPTS"

# ── RDS Multi-AZ: High Availability ──────────────────────────
# Multi-AZ maintains a SYNCHRONOUS standby in a different
# Availability Zone. Every write is committed to BOTH primary
# AND standby before acknowledging success (RPO ≈ 0 seconds).
#
# Failover flow:
#   1. Primary instance fails (hardware, AZ outage, OS crash).
#   2. RDS detects failure (30-60s health check cycle).
#   3. DNS CNAME of the endpoint is flipped to the standby.
#   4. Standby is promoted to primary (reads/writes restored).
#   Total: typically ~60 seconds.
#
# ⚠ CRITICAL: The standby is NOT readable during normal operation.
#   It exists ONLY for failover. Using it as a read endpoint is a
#   common misconception. For read scaling, use Read Replicas.
#
# Application requirement:
#   Set connect_timeout=15 in your connection string.
#   Without it, a failover leaves the app hanging silently.
echo "Multi-AZ: synchronous standby, ~60s failover, NOT readable"

# ── RDS Read Replicas: Read Scaling ──────────────────────────
# Read replicas use ASYNCHRONOUS replication from the primary.
# Lag: typically < 100ms on lightly loaded primary.
# Use read replicas for:
#   - Heavy analytical queries that would slow down OLTP primary.
#   - Reporting workloads that can tolerate slight data lag.
#   - Cross-region read latency reduction.
#   - Aurora: up to 15 read replicas per cluster (vs 5 for standard RDS).
#
# Read replicas can be promoted to standalone primary in DR.
# (Aurora: promotion is near-instant; standard RDS: takes minutes.)
echo "Read replicas: async replication, lag < 100ms typically"

# ── Create RDS PostgreSQL (basic, non-Aurora example) ────────
# Use this for smaller workloads or non-Aurora engine requirements.
section "CREATE RDS POSTGRES INSTANCE"

: <<'COMMENT'
# Prerequisite: subnet group (RDS must live in a VPC).
aws rds create-db-subnet-group \
    --db-subnet-group-name myapp-subnet-group \
    --db-subnet-group-description "Subnets for myapp RDS" \
    --subnet-ids subnet-aaa111 subnet-bbb222 subnet-ccc333

# Create RDS Postgres in Multi-AZ with encrypted storage.
# --multi-az: synchronous standby (HA, automatic failover).
# --allocated-storage / --max-allocated-storage: auto-scales up to max.
# --storage-encrypted: AES-256 via KMS CMK.
# --backup-retention-period: automated snapshots kept for 7 days.
# --enable-performance-insights: query-level performance metrics (free tier).
aws rds create-db-instance \
    --db-instance-identifier myapp-postgres \
    --db-instance-class db.r6g.xlarge \
    --engine postgres \
    --engine-version 15.4 \
    --master-username appuser \
    --master-user-password "${DB_MASTER_PASSWORD}" \
    --db-name myapp \
    --db-subnet-group-name myapp-subnet-group \
    --vpc-security-group-ids sg-xxxxxxxx \
    --multi-az \
    --allocated-storage 100 \
    --max-allocated-storage 500 \
    --storage-type gp3 \
    --storage-encrypted \
    --backup-retention-period 7 \
    --preferred-backup-window "03:00-04:00" \
    --preferred-maintenance-window "Mon:04:00-Mon:05:00" \
    --enable-performance-insights \
    --performance-insights-retention-period 7 \
    --deletion-protection
COMMENT

echo "RDS Postgres create command shown in comments above"

# ══════════════════════════════════════════════════════════════
# SECTION 2: Amazon Aurora — Next-Generation Managed Postgres/MySQL
# ══════════════════════════════════════════════════════════════
# Aurora is AWS's cloud-native relational database.
# Wire-compatible with Postgres and MySQL (drop-in for most apps).
#
# Key architectural differences from standard RDS:
#
# 1. STORAGE: 6-way replication across 3 AZs.
#    Every write goes to 6 storage nodes (2 per AZ) in parallel.
#    Aurora acknowledges the write when 4 of 6 nodes confirm (quorum).
#    This means: can lose an entire AZ AND one node in another AZ
#    with zero data loss and the cluster still running.
#    Storage auto-scales: starts at 10GB, grows to 128TB automatically.
#    No downtime, no pre-provisioning. You pay only for what you use.
#
# 2. THROUGHPUT: 5x MySQL, 3x Postgres (vs standard RDS).
#    Writes go to shared storage directly; no replication log shipping.
#    Reads go to the nearest storage node (lower latency).
#
# 3. REPLICAS: Up to 15 Aurora Replicas share the same storage volume.
#    Replica promotion to primary is INSTANT (no log replay needed).
#    Standard RDS replicas: need to replay binary log (takes minutes).
#
# 4. AURORA SERVERLESS v2:
#    Compute (ACU = Aurora Capacity Unit) scales up/down automatically.
#    Range: 0.5 ACU (dev) to 128 ACU (large prod).
#    Billing: per ACU-second (pay for what you consume, per second).
#    Use case: variable or unpredictable workloads (SaaS multi-tenant).
#    Minimum 0.5 ACU = always warm, sub-second scale-up.
#
# 5. AURORA GLOBAL DATABASE:
#    Primary region + up to 5 secondary (read) regions.
#    Cross-region replication lag < 1 second.
#    Disaster recovery: promote a secondary to primary in < 1 minute.
#    Also used for: local reads in each region (reduced latency for global users).

section "CREATE AURORA POSTGRES CLUSTER"

: <<'COMMENT'
# Step 1: Create the Aurora cluster (shared storage layer).
# The cluster is separate from instances; instances connect to shared storage.
# --engine aurora-postgresql: Postgres wire-compatible Aurora.
# --serverlessv2-scaling-configuration: enable Serverless v2 for instances.
# --backup-retention-period 14: 14 days of automated backups.
# --enable-cloudwatch-logs-exports: ship postgres/upgrade logs to CloudWatch.
aws rds create-db-cluster \
    --db-cluster-identifier myapp-aurora-cluster \
    --engine aurora-postgresql \
    --engine-version 15.4 \
    --master-username appuser \
    --master-user-password "${AURORA_MASTER_PASSWORD}" \
    --database-name myapp \
    --db-subnet-group-name myapp-subnet-group \
    --vpc-security-group-ids sg-xxxxxxxx \
    --backup-retention-period 14 \
    --preferred-backup-window "02:00-03:00" \
    --storage-encrypted \
    --serverlessv2-scaling-configuration MinCapacity=0.5,MaxCapacity=32 \
    --enable-cloudwatch-logs-exports postgresql upgrade \
    --deletion-protection

# Step 2: Add the primary (writer) instance to the cluster.
# --db-instance-class db.serverless: uses Serverless v2 (ACU-based billing).
# Change to db.r7g.xlarge for fixed provisioned compute.
# Availability zone: explicitly set for primary placement.
aws rds create-db-instance \
    --db-instance-identifier myapp-aurora-writer \
    --db-cluster-identifier myapp-aurora-cluster \
    --db-instance-class db.serverless \
    --engine aurora-postgresql \
    --availability-zone us-east-1a \
    --enable-performance-insights \
    --performance-insights-retention-period 7

# Step 3: Wait for the writer instance to be available.
echo "Waiting for writer instance to become available..."
aws rds wait db-instance-available \
    --db-instance-identifier myapp-aurora-writer

# Step 4: Add a read replica (reader) instance.
# Reader instances share the same storage — no lag in data visibility.
# Place in a different AZ for HA (if writer AZ fails, reader continues).
aws rds create-db-instance \
    --db-instance-identifier myapp-aurora-reader-1 \
    --db-cluster-identifier myapp-aurora-cluster \
    --db-instance-class db.serverless \
    --engine aurora-postgresql \
    --availability-zone us-east-1b \
    --enable-performance-insights

# Get the cluster endpoints:
# Writer endpoint: always points to the current primary writer.
# Reader endpoint: load-balances across all reader instances.
aws rds describe-db-clusters \
    --db-cluster-identifier myapp-aurora-cluster \
    --query 'DBClusters[0].{Writer:Endpoint,Reader:ReaderEndpoint}'
COMMENT

echo "Aurora cluster creation commands shown in comments above"

# ══════════════════════════════════════════════════════════════
# SECTION 3: RDS Proxy — Connection Pooling for Lambda and Serverless
# ══════════════════════════════════════════════════════════════
# Problem without RDS Proxy:
#   Lambda function: each invocation opens a new Postgres connection.
#   Under load: 500 concurrent Lambdas = 500 simultaneous DB connections.
#   Postgres default max_connections ≈ 100.
#   Result: "FATAL: remaining connection slots are reserved" → 500 errors.
#
# RDS Proxy solution:
#   - Proxy sits between app/Lambda and the DB.
#   - Maintains a connection pool to the DB (10-20 persistent connections).
#   - 500 Lambda connections → proxy → 15 DB connections (multiplexed).
#   - Failover behavior: proxy holds application connections during Aurora
#     failover. DB reconnects transparently. App sees ~0 connection errors
#     instead of a 60s outage.
#
# Cost: ~$0.015/vCPU-hour proxied. Worth it for Lambda workloads.
# Not needed for: long-lived app servers that use PgBouncer locally.

section "CREATE RDS PROXY"

: <<'COMMENT'
# RDS Proxy requires an IAM role to access the DB secret in Secrets Manager.
# The secret stores the DB credentials; the proxy fetches them automatically
# and rotates without restarting (IAM auth or Secrets Manager rotation).

# Create the Proxy pointing at the Aurora cluster.
# --require-tls: all connections to the proxy must use TLS (enforce encryption).
# --idle-client-timeout: close client connections idle for 30 min (free up slots).
# --connection-pool-config: tune the pool size for your workload.
aws rds create-db-proxy \
    --db-proxy-name myapp-proxy \
    --engine-family POSTGRESQL \
    --auth '[{"AuthScheme":"SECRETS","SecretArn":"arn:aws:secretsmanager:us-east-1:123456789:secret:myapp-db-secret","IAMAuth":"DISABLED"}]' \
    --role-arn arn:aws:iam::123456789:role/rds-proxy-role \
    --vpc-subnet-ids subnet-aaa111 subnet-bbb222 \
    --vpc-security-group-ids sg-xxxxxxxx \
    --require-tls \
    --idle-client-timeout 1800  # 30 minutes

# Register the Aurora cluster as the proxy target.
aws rds register-db-proxy-targets \
    --db-proxy-name myapp-proxy \
    --db-cluster-identifiers myapp-aurora-cluster

# Get the proxy endpoint (use this in your app's DATABASE_URL instead of cluster endpoint).
aws rds describe-db-proxies \
    --db-proxy-name myapp-proxy \
    --query 'DBProxies[0].Endpoint'
COMMENT

echo "RDS Proxy creation commands shown in comments above"

# ══════════════════════════════════════════════════════════════
# SECTION 4: ElastiCache Redis — In-Memory Cache
# ══════════════════════════════════════════════════════════════
# Redis is an in-memory key-value store with sub-millisecond latency.
# Managed by ElastiCache (AWS), Memorystore (GCP), Azure Cache for Redis.
#
# USE CASES:
#   - Session store: store user sessions (TTL-based auto-expiry).
#   - Query cache: cache expensive DB query results (set TTL = acceptable lag).
#   - Rate limiting: INCR key + EXPIRE = atomic counter with TTL.
#   - Leaderboards: sorted sets (ZADD/ZRANK) for ranking.
#   - Pub/Sub: lightweight message passing between services.
#   - Distributed lock: SET key value NX PX 30000 (lock for 30s).
#
# CLUSTER MODE (ElastiCache):
#   - Sharding: data is split across multiple shard nodes (horizontal scale).
#   - Each shard has a primary + up to 5 replicas.
#   - Supports 500+ GB datasets spread across 90 shards.
#   - Slots: 16384 hash slots distributed evenly across shards.
#   - Multi-key commands restricted to keys in the same slot (use hash tags: {user:1}).
#
# PERSISTENCE (Redis at-rest data durability):
#   - AOF (Append-Only File): logs every write command. Higher durability,
#     more disk I/O. Replayable on restart. Good for: session store.
#   - RDB (snapshot): periodic dump of the dataset. Faster restart,
#     risk of data loss between snapshots. Good for: pure cache (loss OK).
#   - For pure cache (data in DB anyway): persistence off = fastest.
#
# NO persistence needed if Redis is just a cache (DB is the source of truth).

section "CREATE ELASTICACHE REDIS CLUSTER"

: <<'COMMENT'
# Create a Redis replication group (primary + 1 replica per shard).
# --cluster-mode-enabled: horizontal sharding (scale beyond single node memory).
# --num-node-groups: number of shards.
# --replicas-per-node-group: replicas per shard (HA).
# --cache-node-type: r7g.large = 13.07GB RAM, optimized for Redis.
# --at-rest-encryption-enabled: encrypt data at rest (KMS).
# --transit-encryption-enabled: enforce TLS between app and Redis.
aws elasticache create-replication-group \
    --replication-group-id myapp-redis \
    --replication-group-description "myapp session and cache store" \
    --cache-node-type cache.r7g.large \
    --engine redis \
    --engine-version 7.0 \
    --num-node-groups 3 \
    --replicas-per-node-group 1 \
    --cache-subnet-group-name myapp-cache-subnet-group \
    --security-group-ids sg-xxxxxxxx \
    --at-rest-encryption-enabled \
    --transit-encryption-enabled \
    --auth-token "${REDIS_AUTH_TOKEN}" \
    --automatic-failover-enabled \
    --snapshot-retention-limit 3  # 3 daily RDB snapshots
COMMENT

echo "ElastiCache Redis creation shown in comments above"

# ══════════════════════════════════════════════════════════════
# SECTION 5: DynamoDB — Serverless NoSQL at Any Scale
# ══════════════════════════════════════════════════════════════
# DynamoDB is a fully managed, serverless NoSQL database.
# Characteristics:
#   - Unlimited horizontal scale (AWS manages partitioning).
#   - Single-digit millisecond latency at ANY scale.
#   - Serverless: no instances to manage or resize.
#   - Highly durable: data replicated across 3 AZs automatically.
#
# DATA MODEL — the most important thing to understand:
#   Every table has:
#     - Partition key (PK / hash key): required. Determines which partition
#       stores the item. All items with the same PK are on the same partition.
#     - Sort key (SK / range key): optional. Within a partition, items are
#       sorted by SK. Enables range queries (SK BETWEEN, begins_with).
#   Primary key = PK alone, or PK + SK (composite).
#
#   ⚠ ACCESS PATTERNS MUST BE DESIGNED UPFRONT:
#     DynamoDB is NOT flexible like Postgres. You cannot run arbitrary queries.
#     You can only query by PK (exact match) + optional SK (range/prefix).
#     Design your table for the queries your app needs, not around entities.
#     Read: "The DynamoDB Book" by Alex DeBrie for single-table design.
#
# INDEXES:
#   GSI (Global Secondary Index):
#     - Defines a new PK + optional SK for alternate access patterns.
#     - Separate throughput (independent read/write capacity).
#     - Eventually consistent reads (not strongly consistent).
#     - Max 20 GSIs per table.
#     - Example: table PK=userId, GSI PK=email → look up user by email.
#
#   LSI (Local Secondary Index):
#     - Same PK as the table, different SK.
#     - Shares throughput with the table (not separate).
#     - Strongly consistent reads supported.
#     - Must be created at table creation time (cannot add later).
#     - Max 5 LSIs per table.
#
# BILLING MODES:
#   On-demand: pay per request ($1.25/million writes, $0.25/million reads).
#     Best for: new tables with unknown traffic, spiky workloads, dev/staging.
#     No capacity planning needed.
#   Provisioned: set read/write capacity units (RCU/WCU) in advance.
#     ~70% cheaper than on-demand for steady, predictable traffic.
#     Use auto-scaling to adjust capacity automatically within bounds.

section "CREATE DYNAMODB TABLE"

: <<'COMMENT'
# Create a table for storing user sessions.
# PK: user_id, SK: session_id (composite key → one user can have many sessions).
# On-demand billing: good starting point, switch to provisioned when traffic stabilizes.
# TTL attribute: DynamoDB automatically deletes items when expires_at < now.
aws dynamodb create-table \
    --table-name UserSessions \
    --attribute-definitions \
        AttributeName=user_id,AttributeType=S \
        AttributeName=session_id,AttributeType=S \
        AttributeName=device_type,AttributeType=S \
    --key-schema \
        AttributeName=user_id,KeyType=HASH \
        AttributeName=session_id,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --global-secondary-indexes '[
        {
            "IndexName": "DeviceTypeIndex",
            "KeySchema": [
                {"AttributeName": "device_type", "KeyType": "HASH"},
                {"AttributeName": "user_id",     "KeyType": "RANGE"}
            ],
            "Projection": {"ProjectionType": "ALL"}
        }
    ]' \
    --sse-specification Enabled=true \
    --tags Key=Environment,Value=production

# Enable TTL: DynamoDB scans for items where expires_at < epoch seconds now,
# and deletes them asynchronously (within 48h of expiry). No cost for TTL deletes.
aws dynamodb update-time-to-live \
    --table-name UserSessions \
    --time-to-live-specification Enabled=true,AttributeName=expires_at
COMMENT

echo "DynamoDB table creation shown in comments above"

# ══════════════════════════════════════════════════════════════
# SECTION 6: Amazon Redshift — Columnar Data Warehouse
# ══════════════════════════════════════════════════════════════
# Redshift is a petabyte-scale columnar data warehouse.
# Columnar storage: data is stored column-by-column (not row-by-row).
# For analytics (SELECT avg(price) FROM orders):
#   - Only the "price" column is read from disk (not entire rows).
#   - Columns compress well (same data type, run-length encoding).
#   - Result: 10x less I/O than row-oriented databases for aggregations.
#
# CLUSTER OPTIONS:
#   Provisioned (RA3 nodes):
#     - Fixed cluster of nodes. RA3: compute and storage are separate.
#     - Storage auto-scales via S3 (Redshift Managed Storage).
#     - Good for: predictable, heavy analytical workloads (BI teams).
#   Serverless:
#     - No cluster to manage. Pay per RPU (Redshift Processing Unit) per second.
#     - Scales to 0 when idle. Good for: infrequent or bursty analytics.
#
# DATA LOADING:
#   COPY from S3: the recommended way to bulk-load data.
#   Parallel: each Redshift node reads its slice of S3 files concurrently.
#   COPY is 100x faster than INSERT row by row.
#
# REDSHIFT SPECTRUM:
#   Query data directly in S3 (Parquet, CSV, JSON) without loading into Redshift.
#   Creates external tables pointing to S3 paths.
#   Pay per TB scanned (like Athena).
#   Use for: joining Redshift data with raw S3 data lake.
#
# DISTRIBUTION STYLES (how data is split across nodes):
#   KEY distribution: rows with the same key go to the same node.
#     Use for: large fact tables joined on a specific key (avoids data movement).
#   ALL distribution: entire table is copied to every node.
#     Use for: small dimension tables joined frequently (no shuffle needed).
#   EVEN distribution: rows are distributed in round-robin fashion.
#     Use for: large tables with no clear join key, or staging tables.

section "REDSHIFT SETUP"

: <<'COMMENT'
# Create a Redshift Serverless namespace and workgroup.
# No nodes to manage; capacity scales automatically.
aws redshift-serverless create-namespace \
    --namespace-name myapp-analytics \
    --admin-username admin \
    --admin-user-password "${REDSHIFT_PASSWORD}" \
    --db-name analytics \
    --iam-roles arn:aws:iam::123456789:role/redshift-s3-role

aws redshift-serverless create-workgroup \
    --workgroup-name myapp-analytics-wg \
    --namespace-name myapp-analytics \
    --base-capacity 32 \
    --security-group-ids sg-xxxxxxxx \
    --subnet-ids subnet-aaa111 subnet-bbb222

# Example COPY command (run inside Redshift, not from CLI):
# COPY orders FROM 's3://mybucket/orders/2024/12/'
# IAM_ROLE 'arn:aws:iam::123456789:role/redshift-s3-role'
# FORMAT AS PARQUET
# REGION 'us-east-1';
COMMENT

echo "Redshift Serverless creation shown in comments above"

# ══════════════════════════════════════════════════════════════
# SECTION 7: GCP AND AZURE EQUIVALENTS
# ══════════════════════════════════════════════════════════════
section "CLOUD DATABASE EQUIVALENTS"

cat << 'EOF'
╔══════════════════════════╦══════════════════════════╦═══════════════════════════╗
║ AWS                      ║ GCP                      ║ Azure                     ║
╠══════════════════════════╬══════════════════════════╬═══════════════════════════╣
║ RDS (Postgres/MySQL)     ║ Cloud SQL                ║ Azure Database for Pg/My  ║
╠══════════════════════════╬══════════════════════════╬═══════════════════════════╣
║ Aurora (Postgres/MySQL)  ║ AlloyDB                  ║ Azure SQL Hyperscale      ║
╠══════════════════════════╬══════════════════════════╬═══════════════════════════╣
║ Cloud Spanner            ║ Cloud Spanner            ║ (no direct equivalent)    ║
║ (global, horizontal SQL) ║ globally consistent SQL  ║                           ║
╠══════════════════════════╬══════════════════════════╬═══════════════════════════╣
║ DynamoDB (NoSQL KV)      ║ Firestore                ║ Cosmos DB (multi-model)   ║
╠══════════════════════════╬══════════════════════════╬═══════════════════════════╣
║ ElastiCache Redis        ║ Memorystore (Redis)      ║ Azure Cache for Redis     ║
╠══════════════════════════╬══════════════════════════╬═══════════════════════════╣
║ Redshift                 ║ BigQuery                 ║ Azure Synapse Analytics   ║
╚══════════════════════════╩══════════════════════════╩═══════════════════════════╝

GCP-specific notes:
  Cloud Spanner: the only globally distributed, strongly consistent, horizontally
    scalable relational database. No other managed offering matches it.
    Use for: financial transactions, inventory systems needing global consistency.
    Cost: expensive (~$0.90/node-hour). Not for small workloads.

  BigQuery: serverless, pay per TB scanned. No cluster management. Scales to
    petabytes automatically. External tables query GCS (like Redshift Spectrum).
    Streaming inserts: ~$0.01/200MB. Batch loads from GCS: free.

  Firestore: document store (JSON-like). Native mode = globally distributed.
    Strongly consistent within a document, eventually consistent across documents.
    Good for: mobile apps, real-time sync, user-facing CRUD.

Azure-specific notes:
  Cosmos DB: multi-model (document, KV, graph, table, Cassandra API).
    SLA: 99.999% availability. Global distribution with multi-master writes.
    Consistency levels: strong → bounded-staleness → session → consistent-prefix → eventual.
    Pricing: by RU (Request Unit) = normalized compute cost per operation.
EOF

# ══════════════════════════════════════════════════════════════
# SECTION 8: DECISION GUIDE — WHEN TO USE WHAT
# ══════════════════════════════════════════════════════════════
section "WHEN TO USE WHICH DATABASE"

cat << 'EOF'
USE Aurora Postgres WHEN:
  ✓ Main application database (OLTP, ACID transactions)
  ✓ Complex queries with JOINs, aggregations, subqueries
  ✓ You need the flexibility to evolve queries over time
  ✓ Team knows SQL well
  ✓ < 128TB of data
  Example: order management, user accounts, inventory, billing

USE ElastiCache Redis WHEN:
  ✓ Caching expensive DB query results (set TTL)
  ✓ User session storage (fast auth lookup)
  ✓ Rate limiting (INCR + EXPIRE is atomic)
  ✓ Leaderboards (sorted sets)
  ✓ Data fits in RAM (otherwise costs explode)
  Example: session store, API response cache, rate limiter

USE DynamoDB WHEN:
  ✓ Very high throughput KV or simple access patterns
  ✓ Data volume > 128TB (Aurora limit)
  ✓ Fully serverless (no capacity planning)
  ✓ Known, stable access patterns (designed upfront)
  ✓ IoT telemetry, gaming state, user profiles, shopping cart
  ✗ NOT for: complex queries, ad-hoc analytics, lots of JOINs

USE Redshift / BigQuery WHEN:
  ✓ Analytical queries over millions/billions of rows
  ✓ Business intelligence and reporting dashboards
  ✓ Data older than 90 days (move from Aurora → Redshift)
  ✓ Joining multiple large datasets for reporting
  ✗ NOT for: OLTP, point lookups, <1s latency requirements

USE RDS Proxy WHEN:
  ✓ Lambda functions connecting to Aurora/RDS
  ✓ Application creates many short-lived DB connections
  ✓ You want faster failover (proxy buffers connections)
  ✓ IAM auth to the database (no password management)
EOF

section "COMPLETE ARCHITECTURE EXAMPLE"

cat << 'EOF'
  ┌─────────────────────────────────────────────────────────┐
  │  MULTI-TIER APPLICATION ARCHITECTURE                    │
  │                                                         │
  │  [Load Balancer]                                        │
  │       │                                                 │
  │  [App Servers / Lambda]                                 │
  │       │              │              │                   │
  │  [RDS Proxy]    [ElastiCache   [DynamoDB]               │
  │       │          Redis]         (IoT/gaming)            │
  │  [Aurora Cluster]                                       │
  │   Writer │ Reader   (OLTP: orders, users, products)     │
  │           │                                             │
  │  [Nightly ETL → S3 → Redshift]                          │
  │                 (analytics, BI, reports)                │
  └─────────────────────────────────────────────────────────┘

  Connection flow for a web request:
    User → ALB → App Server
      → RDS Proxy → Aurora Writer (writes)
      → RDS Proxy → Aurora Reader (complex reads)
      → ElastiCache Redis (session auth check, cache hit)
      → DynamoDB (user profile, shopping cart)

  Connection flow for analytics:
    Scheduler → Glue ETL
      → Read Aurora Reader (last 24h data)
      → Write Parquet to S3
      → Redshift COPY from S3
      → QuickSight / Tableau reads Redshift
EOF

echo ""
echo "Script complete. All sections covered."
echo "Run individual AWS CLI commands from the COMMENT blocks above."
echo "Ensure AWS CLI v2 is installed and configured: aws configure"
