#!/usr/bin/env bash
# =============================================================================
# WHAT: Cloud Storage Services — S3, EBS, EFS, CloudFront, and equivalents
# WHY:  Storage is permanent. Getting storage wrong = data loss, sky-high bills,
#       or compliance violations. The right storage class can cut costs by 80%.
#       The right CDN can reduce latency from 200ms to 5ms for global users.
# LEVEL: Senior / Architect — production systems at scale
# =============================================================================
#
# CONCEPT OVERVIEW
# ----------------
# Three types of cloud storage:
#   Object Storage (S3):    Flat namespace of objects (key=value). Infinite scale.
#                           Not a filesystem. Accessed via HTTP API. Cheap at scale.
#   Block Storage (EBS):    Virtual disk attached to a VM. Like a hard drive.
#                           POSIX filesystem. Low latency. Tied to one EC2 (usually).
#   File Storage (EFS):     Network filesystem (NFS). Mount to many EC2s simultaneously.
#                           Higher latency than EBS. For shared data.
#
# PRODUCTION USE CASE
# -------------------
# Media platform: user uploads go to S3 (object storage). Video processing reads from
# EBS (fast NVMe for ffmpeg). Processed videos stored in S3 Glacier (archival).
# Thumbnails and manifests served via CloudFront (CDN, ~5ms globally).
# EC2 instances share a config directory via EFS (shared filesystem).
#
# COMMON MISTAKES
# ---------------
# - Public S3 buckets with sensitive data (use Block Public Access, enable it org-wide)
# - Using S3 Standard for data accessed once a month (pay 10x vs IA)
# - Not enabling versioning (can't recover from accidental delete/overwrite)
# - Downloading full S3 files to filter them (use S3 Select for SQL filtering)
# - No lifecycle rules (old data accumulates, costs grow forever)
# - Cross-AZ data transfer overlooked (EC2 to EBS in different AZ = $0.01/GB + latency)
# =============================================================================

set -euo pipefail

# =============================================================================
# S3 FUNDAMENTALS
# =============================================================================
# S3 (Simple Storage Service) = object storage.
# Key concepts:
#   Bucket:     Container for objects. Name is globally unique across ALL AWS accounts.
#               Bucket name becomes part of the URL: bucket.s3.amazonaws.com
#   Object:     A file + metadata. Max 5TB per object (use multipart upload > 100MB).
#               Key = the "path" (actually a flat namespace, / is just a convention).
#   Versioning: Each PUT creates a new version. DELETE adds delete marker (recoverable).
#   ACL:        Legacy access control. DEPRECATED — use bucket policies and IAM instead.
#
# S3 durability: 11 nines (99.999999999%) — data replicated across 3+ AZs by default.
# S3 is NOT a filesystem: no atomic rename, no directory listing is instant, eventual consistency.
# S3 IS strongly consistent (as of December 2020): PUT then GET returns the new value.

echo "=== S3 Bucket Creation with Best Practices ==="
BUCKET_NAME="myapp-data-$(date +%Y%m%d)"
REGION="us-east-1"

# Create bucket
aws s3api create-bucket \
    --bucket "$BUCKET_NAME" \
    --region "$REGION" 2>/dev/null || echo "(requires AWS CLI)"

# Block ALL public access (defense in depth — even if policy allows public, block it)
# PRODUCTION: Enable this at the AWS ORGANIZATION level so no bucket can ever be public
aws s3api put-public-access-block \
    --bucket "$BUCKET_NAME" \
    --public-access-block-configuration \
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" \
    2>/dev/null || echo "(requires AWS CLI)"

# Enable versioning (recover from accidental deletes and overwrites)
aws s3api put-bucket-versioning \
    --bucket "$BUCKET_NAME" \
    --versioning-configuration Status=Enabled \
    2>/dev/null || echo "(requires AWS CLI)"

# Enable server-side encryption (AES-256 or KMS)
# KMS: audit trail of every decrypt, can revoke access by disabling key
aws s3api put-bucket-encryption \
    --bucket "$BUCKET_NAME" \
    --server-side-encryption-configuration '{
        "Rules": [{
            "ApplyServerSideEncryptionByDefault": {
                "SSEAlgorithm": "aws:kms",
                "KMSMasterKeyID": "arn:aws:kms:us-east-1:123456789:key/abc123"
            },
            "BucketKeyEnabled": true
        }]
    }' 2>/dev/null || echo "(requires AWS CLI)"
# BucketKeyEnabled: reduces KMS API calls by generating a bucket-level key
# This can save 99% of KMS costs for S3-heavy workloads

# =============================================================================
# S3 STORAGE CLASSES: Matching access frequency to cost
# =============================================================================
# S3 STANDARD:
#   Durability: 11 nines. Availability: 99.99%.
#   Price: $0.023/GB/month (us-east-1)
#   Use for: frequently accessed data, unpredictable access, < 30 days old
#
# S3 STANDARD-IA (Infrequent Access):
#   Same durability/availability. Same latency as Standard.
#   Price: $0.0125/GB/month + $0.01/GB retrieval fee
#   Minimum storage duration: 30 days
#   Use for: backups, DR files, data accessed monthly
#   NOT for: data deleted before 30 days (charged for full 30)
#
# S3 ONE ZONE-IA:
#   Stored in single AZ only. 20% cheaper than Standard-IA.
#   Price: $0.01/GB/month
#   Use for: data you can recreate if AZ fails (thumbnails, transcoded videos)
#   NOT for: primary backups or data you can't afford to lose
#
# S3 GLACIER INSTANT RETRIEVAL:
#   Archive storage. Millisecond retrieval (no restore wait).
#   Price: $0.004/GB/month + $0.03/GB retrieval
#   Minimum storage duration: 90 days
#   Use for: data accessed 1-2 times per year, compliance archives
#
# S3 GLACIER FLEXIBLE RETRIEVAL (formerly S3 Glacier):
#   Price: $0.0036/GB/month
#   Retrieval times: Expedited (1-5 min, expensive), Standard (3-5 hours), Bulk (5-12 hours)
#   Use for: backup archives, rarely needed compliance data
#
# S3 GLACIER DEEP ARCHIVE:
#   Cheapest storage in AWS. Price: $0.00099/GB/month
#   Retrieval: Standard 12 hours, Bulk 48 hours
#   Minimum duration: 180 days
#   Use for: 7-year compliance archives, cold backups, regulatory retention
#   Example: 10TB for 7 years = ~$835 total (vs $19,320 in Standard)
#
# S3 INTELLIGENT-TIERING:
#   Automatically moves objects between tiers based on access patterns.
#   No retrieval fees. Small monitoring fee ($0.0025/1000 objects).
#   Perfect for: data with unpredictable access patterns.
#   How it works: monitor access → if not accessed in 30 days → move to IA tier
#                 → 90 days → move to Archive Instant tier (if enabled)

# =============================================================================
# S3 LIFECYCLE RULES: Automate storage class transitions
# =============================================================================
# Real-world log storage policy:
#   - Fresh logs (0-30 days): Standard (fast access for debugging)
#   - Recent logs (30-90 days): Standard-IA (cheaper, still accessible)
#   - Old logs (90-365 days): Glacier Flexible (rarely needed)
#   - Ancient logs (365+ days): Delete (compliance period over)

echo ""
echo "=== S3 Lifecycle Policy — Log Storage ==="
aws s3api put-bucket-lifecycle-configuration \
    --bucket "$BUCKET_NAME" \
    --lifecycle-configuration '{
        "Rules": [
            {
                "ID": "log-tiering",
                "Status": "Enabled",
                "Filter": {"Prefix": "logs/"},
                "Transitions": [
                    {
                        "Days": 30,
                        "StorageClass": "STANDARD_IA"
                    },
                    {
                        "Days": 90,
                        "StorageClass": "GLACIER"
                    }
                ],
                "Expiration": {
                    "Days": 365
                },
                "NoncurrentVersionTransitions": [
                    {
                        "NoncurrentDays": 30,
                        "StorageClass": "GLACIER"
                    }
                ],
                "NoncurrentVersionExpiration": {
                    "NoncurrentDays": 90
                }
            },
            {
                "ID": "incomplete-multipart-cleanup",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},
                "AbortIncompleteMultipartUpload": {
                    "DaysAfterInitiation": 7
                }
            }
        ]
    }' 2>/dev/null || echo "(requires AWS CLI)"
# NOTE: AbortIncompleteMultipartUpload is CRITICAL.
# Incomplete multipart uploads accumulate and cost money. Clean them up.

# =============================================================================
# PRESIGNED URLS: Secure temporary access
# =============================================================================
# Problem: user wants to upload a 500MB video directly to S3.
# Bad solution: route through your API server (bandwidth costs, latency, your server load).
# Good solution: presigned URL — API server generates a time-limited URL.
#                User uploads directly to S3. Your server never touches the data.
#
# Presigned GET: temporary download link (e.g., 15-minute expiry for dashboard reports)
# Presigned PUT: allow upload to a specific S3 key (e.g., user avatar upload)
# NEVER share actual S3 credentials. Presigned URLs = scoped, time-limited, auditable.

echo ""
echo "=== Generate Presigned URL ==="
# PUT presigned URL (for client-side upload)
aws s3 presign s3://"$BUCKET_NAME"/uploads/user-123/video.mp4 \
    --expires-in 3600 2>/dev/null || echo "(requires AWS CLI)"
# URL is valid for 3600 seconds (1 hour). After that, 403 Access Denied.

# For multipart uploads (> 100MB): use presigned multipart upload URLs
# Each part gets its own presigned URL. Client uploads parts in parallel.
# S3 assembles the parts. Max throughput: ~150MB/s per upload.

# =============================================================================
# S3 EVENT NOTIFICATIONS: Event-driven architecture
# =============================================================================
# S3 can trigger Lambda, SQS, or SNS when objects are created/deleted.
# Common patterns:
#   Image upload → S3 event → Lambda → generate thumbnails → store in S3
#   Log file uploaded → S3 event → Lambda → parse and load into Redshift
#   Object deleted → S3 event → SQS → audit log system

echo ""
echo "=== S3 Event Notification Configuration ==="
aws s3api put-bucket-notification-configuration \
    --bucket "$BUCKET_NAME" \
    --notification-configuration '{
        "LambdaFunctionConfigurations": [
            {
                "LambdaFunctionArn": "arn:aws:lambda:us-east-1:123:function:process-upload",
                "Events": ["s3:ObjectCreated:*"],
                "Filter": {
                    "Key": {
                        "FilterRules": [
                            {"Name": "prefix", "Value": "uploads/"},
                            {"Name": "suffix", "Value": ".mp4"}
                        ]
                    }
                }
            }
        ]
    }' 2>/dev/null || echo "(requires AWS CLI)"

# =============================================================================
# S3 REPLICATION
# =============================================================================
# CRR (Cross-Region Replication):
#   Async replication to a bucket in another region.
#   Use for: DR (replica in different region), compliance (data in EU must stay in EU),
#            latency reduction (serve from closest region).
#   RPO: typically < 15 minutes.
#
# SRR (Same-Region Replication):
#   Replication within the same region.
#   Use for: log aggregation (all env logs → one bucket), test/prod sync.

# =============================================================================
# S3 SELECT: Query-in-place to reduce data transfer
# =============================================================================
# Instead of downloading a 1GB CSV, run a SQL query and get only matching rows.
# Supports: CSV, JSON, Parquet. S3 does the filtering, you pay for data scanned.
# Cost reduction: 80% less data transferred = 80% cheaper + 80% faster for filtered queries.

echo ""
echo "=== S3 Select Example ==="
aws s3api select-object-content \
    --bucket "$BUCKET_NAME" \
    --key "data/events-2026-06.csv" \
    --expression "SELECT * FROM S3Object s WHERE s.event_type = 'purchase'" \
    --expression-type SQL \
    --input-serialization '{"CSV": {"FileHeaderInfo": "USE"}}' \
    --output-serialization '{"CSV": {}}' \
    /dev/stdout 2>/dev/null || echo "(requires AWS CLI + S3 object)"

# =============================================================================
# EBS: BLOCK STORAGE
# =============================================================================
# EBS = virtual disk attached to an EC2 instance. Like an SSD in the cloud.
# Characteristics:
#   - Attached to ONE EC2 instance at a time (io2 supports multi-attach to up to 16)
#   - Stays persistent when EC2 stops (unlike instance store)
#   - Can create snapshots to S3 (incremental, can share/copy across regions)
#   - Network-attached: small latency vs physical disk (~0.1-0.5ms)
#
# EBS VOLUME TYPES:
#   gp3 (General Purpose SSD, default):
#     3,000 IOPS baseline + 125 MB/s baseline (independently configurable, unlike gp2)
#     Scale: up to 16,000 IOPS and 1,000 MB/s
#     Price: $0.08/GB/month + $0.005/provisioned IOPS above 3,000
#     Use for: most workloads, OS volumes, app servers, moderate DB
#
#   io2 Block Express (Provisioned IOPS SSD, high performance):
#     Up to 256,000 IOPS and 4,000 MB/s per volume
#     For large databases: Oracle RAC, SQL Server, large Postgres instances
#     Price: $0.125/GB/month + $0.065/IOPS/month (expensive — use only when needed)
#
#   st1 (Throughput Optimized HDD):
#     Low IOPS, high throughput (500 MB/s max). Sequential access.
#     Good for: data warehouses, log processing, big data Hadoop
#     Price: $0.045/GB/month (cheap for high-volume sequential reads)
#
#   sc1 (Cold HDD):
#     Lowest cost EBS. 250 MB/s max. Infrequently accessed.
#     Good for: cold backups that need to remain on block storage

echo ""
echo "=== Create gp3 EBS Volume ==="
aws ec2 create-volume \
    --volume-type gp3 \
    --size 100 \
    --availability-zone us-east-1a \
    --iops 6000 \
    --throughput 250 \
    --encrypted \
    --kms-key-id arn:aws:kms:us-east-1:123456789:key/abc123 \
    --tag-specifications 'ResourceType=volume,Tags=[{Key=Name,Value=api-data}]' \
    2>/dev/null || echo "(requires AWS CLI)"

# Snapshot (incremental backup):
aws ec2 create-snapshot \
    --volume-id vol-0123456789abcdef0 \
    --description "Daily backup $(date +%Y-%m-%d)" \
    2>/dev/null || echo "(requires AWS CLI)"

# =============================================================================
# EFS: ELASTIC FILE SYSTEM (Shared NFS)
# =============================================================================
# EFS = managed NFS that can be mounted simultaneously on many EC2 instances.
# Use when: multiple EC2s need to read/write the same files concurrently.
# Example: Jenkins build agents sharing a workspace, shared ML model directory.
#
# EFS vs EBS comparison:
#   EFS: Multi-mount, serverless scaling, higher latency (~1-3ms), more expensive/GB
#   EBS: Single-mount (usually), provisioned, lower latency (~0.1ms), cheaper/GB for block storage
#
# EFS Performance Modes:
#   General Purpose: Default. < 7,000 IOPS. Best latency.
#   Max I/O:         Unlimited IOPS. Higher latency. For parallel HPC workloads.
#
# EFS Throughput Modes:
#   Elastic (default): Scales automatically. Pay for what you use.
#   Provisioned:       Guarantee throughput. For predictable, high-throughput workloads.

echo ""
echo "=== Create EFS and Mount Target ==="
EFS_ID=$(aws efs create-file-system \
    --performance-mode generalPurpose \
    --throughput-mode elastic \
    --encrypted \
    --tags Key=Name,Value=shared-model-storage \
    --query 'FileSystemId' --output text 2>/dev/null) || EFS_ID="fs-example"

# Mount target in each AZ where EC2s exist (one per AZ)
aws efs create-mount-target \
    --file-system-id "$EFS_ID" \
    --subnet-id subnet-aaa \
    --security-groups sg-efs-access \
    2>/dev/null || echo "(requires AWS CLI)"

# Mount EFS on EC2 (using Amazon EFS utils for encryption in transit):
# sudo mount -t efs -o tls,iam fs-0123456789abcdef0:/ /mnt/efs

# =============================================================================
# CLOUDFRONT CDN: Edge caching for global performance
# =============================================================================
# CloudFront = AWS's CDN. 450+ edge locations (Points of Presence) globally.
# When a user in Tokyo requests your US-hosted image:
#   Without CDN:   Request crosses the Pacific → 150ms latency
#   With CloudFront: First request = cache miss, goes to origin → edge caches it.
#                  Subsequent requests from Tokyo: served from Tokyo PoP → 5-10ms.
#
# What to cache:
#   ✅ Static assets (JS, CSS, images, fonts, videos)
#   ✅ API responses that are the same for many users (product catalog, public listings)
#   ❌ User-specific responses (shopping cart, user profile)
#   ❌ Frequently updated data without proper cache-control headers
#
# CACHE CONTROL headers (set on your origin):
#   Cache-Control: max-age=31536000, immutable
#     → Cache for 1 year. For versioned assets (bundle.abc123.js).
#   Cache-Control: max-age=0, must-revalidate
#     → Don't cache. For user-specific data.
#   Cache-Control: s-maxage=300
#     → Cache at CDN for 5 minutes, browser handles independently.
#
# CACHE INVALIDATION:
#   aws cloudfront create-invalidation --distribution-id E1ABC --paths "/*"
#   Cost: first 1,000 paths/month free, then $0.005/path
#   Better: use versioned URLs (bundle.abc123.js) → no invalidation needed.
#
# LAMBDA@EDGE: Run code at CloudFront PoPs
#   Use for: A/B testing at edge, auth header injection, URL rewriting, geo-based routing.
#   Limits: 128MB memory, 5-second timeout for viewer triggers.

echo ""
echo "=== CloudFront Distribution for S3 Static Site ==="
aws cloudfront create-distribution \
    --distribution-config '{
        "Origins": {
            "Items": [{
                "Id": "S3Origin",
                "DomainName": "'"$BUCKET_NAME"'.s3.amazonaws.com",
                "S3OriginConfig": {"OriginAccessIdentity": ""}
            }],
            "Quantity": 1
        },
        "DefaultCacheBehavior": {
            "TargetOriginId": "S3Origin",
            "ViewerProtocolPolicy": "redirect-to-https",
            "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6",
            "Compress": true
        },
        "Enabled": true,
        "Comment": "Static asset CDN",
        "PriceClass": "PriceClass_All",
        "HttpVersion": "http2and3"
    }' 2>/dev/null || echo "(requires AWS CLI)"

# =============================================================================
# GCS vs AZURE BLOB: Equivalent services
# =============================================================================
# GCS (Google Cloud Storage):
#   Classes: Standard / Nearline (30-day min) / Coldline (90-day min) / Archive (365-day min)
#   Multi-regional: data replicated across multiple regions (US, EU, ASIA)
#   Dual-regional: two specific regions for lower latency than multi-regional
#   HMAC keys: S3-compatible API — useful for tools built for S3
#   Cloud CDN: equivalent to CloudFront but fewer PoPs (~150 globally)
#
# Azure Blob Storage:
#   Tiers: Hot / Cool / Cold / Archive
#   Hot: equivalent to S3 Standard
#   Cool: equivalent to Standard-IA (30-day min)
#   Archive: equivalent to Glacier (must "rehydrate" before reading, hours wait)
#   Azure CDN / Azure Front Door: equivalent to CloudFront
#   Front Door: global HTTP load balancer + CDN + WAF in one

# =============================================================================
# DATA TRANSFER COSTS: The hidden bill
# =============================================================================
# This is where many teams get surprised by their cloud bill.
#
# AWS DATA TRANSFER PRICING (approximate, varies by region/tier):
#   Internet → AWS (inbound):    FREE
#   AWS → Internet (outbound):   $0.09/GB (first 10TB/month, us-east-1)
#   Between AZs in same region:  $0.01/GB each way ($0.02/GB round trip)
#   Between regions:             $0.02/GB (us-east-1 to eu-west-1)
#   Within same AZ:              FREE (same AZ, same VPC)
#   CloudFront → Internet:       $0.0085/GB (cheaper than direct S3 egress)
#
# DESIGN IMPLICATIONS:
#   1. Put EC2 and RDS in the SAME AZ if they communicate heavily.
#      AZ failure = handled by your app. Paying $0.02/GB cross-AZ is real money.
#   2. Use CloudFront in front of S3 — egress from CloudFront is cheaper than direct S3.
#   3. Compress everything — paying $0.09/GB for uncompressed logs = waste.
#   4. S3 Transfer Acceleration: uses CloudFront edge for fast uploads from global users.
#      Worth it for large uploads from users far from your S3 region.
#
# EXAMPLE COST CALCULATION:
#   10 million users, each downloading 1MB of assets/day:
#   Daily egress: 10TB. Monthly: 300TB.
#   Direct S3: 300TB × $0.09 = $27,000/month
#   Via CloudFront: 300TB × $0.0085 = $2,550/month
#   Savings: $24,450/month = $293,400/year. CDN is not optional at this scale.
