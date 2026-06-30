#!/usr/bin/env bash
# =============================================================================
# WHAT: Cloud Compute Services — EC2, Lambda, Containers, Auto Scaling
# WHY:  Compute is the backbone of every cloud workload. Choosing the wrong
#       instance type costs 3x more than necessary. Wrong scaling strategy =
#       outage at peak load or massively over-provisioned idle capacity.
# LEVEL: Senior / Architect — production systems at scale
# =============================================================================
#
# CONCEPT OVERVIEW
# ----------------
# Cloud compute = renting CPU and RAM from a provider.
# The abstraction level varies:
#   VMs (EC2):        You manage OS, patches, runtime. Full control.
#   Containers (ECS/EKS): You manage container, provider manages host OS.
#   Serverless (Lambda): You manage only function code. Provider manages everything.
#
# PRODUCTION USE CASE
# -------------------
# A marketplace platform: API servers on ECS Fargate (auto-scale on request count),
# batch processing on EC2 Spot (70% cost savings for non-critical jobs),
# ML inference on g4dn.xlarge (GPU inference), image resizing on Lambda (event-driven).
# No one compute type fits every workload — use the right tool.
#
# COMMON MISTAKES
# ---------------
# - Using a single large instance instead of many small ones (single point of failure)
# - Using on-demand pricing for stable baseline load (reserved saves 40-60%)
# - Using Spot for stateful workloads without checkpointing (lose work on interruption)
# - Running GPU instances 24/7 for batch ML training (use Spot, train then terminate)
# - Not setting maxUnavailable=0 in rolling deploys (brief capacity drops under load)
# =============================================================================

set -euo pipefail

# =============================================================================
# EC2 INSTANCE TYPE FAMILIES: Choosing the right type
# =============================================================================
# AWS naming convention: [family][generation][optional-modifier].[size]
#   m6i.xlarge:  m=memory-optimized(?), 6=6th gen, i=Intel, xlarge=4 vCPU 16GB
#   c6g.2xlarge: c=compute, 6=6th gen, g=Graviton(ARM), 2xlarge=8 vCPU 16GB
#   r5.8xlarge:  r=memory, 5=5th gen, 8xlarge=32 vCPU 256GB
#
# FAMILY GUIDE:
#
# T-family (Burstable): t3, t3a, t4g
#   CPU credits accumulate at baseline, burst for short periods.
#   Good for: dev/test, low-traffic apps, CI workers
#   Bad for: consistently high CPU workloads (credits deplete, throttled)
#   t3.medium: 2 vCPU, 4GB RAM, ~$0.04/hr
#
# M-family (General Purpose): m5, m6i, m7i, m6g, m7g
#   Balanced CPU/memory. The "default" family.
#   Good for: API servers, web apps, microservices, medium databases
#   m6i.xlarge:  4 vCPU, 16GB, ~$0.19/hr
#   m6i.4xlarge: 16 vCPU, 64GB, ~$0.77/hr
#
# C-family (Compute Optimized): c5, c6i, c7i, c6g, c7g
#   High CPU, lower memory ratio. Best price/perf for CPU-bound.
#   Good for: web frontends, gaming servers, video encoding, HPC, batch
#   c6i.xlarge:  4 vCPU, 8GB, ~$0.17/hr (cheaper than m, less memory)
#
# R-family (Memory Optimized): r5, r6i, r7i, r6g, r7g
#   High memory, moderate CPU. Memory:CPU ratio 2x that of M-family.
#   Good for: large in-memory databases, Redis, Elasticsearch, analytics
#   r6i.2xlarge: 8 vCPU, 64GB, ~$0.50/hr
#
# X-family (Extra Memory): x1, x2
#   Extreme memory (up to 24TB). For SAP HANA, in-memory analytics.
#   x2idn.32xlarge: 128 vCPU, 2048GB RAM, $10.68/hr
#
# P-family (GPU — Training): p3, p4d, p4de, p5
#   NVIDIA GPUs. For ML training, deep learning.
#   p4d.24xlarge: 96 vCPU, 1152GB RAM, 8x A100 40GB GPUs, $32.77/hr
#   p5.48xlarge:  192 vCPU, 2048GB RAM, 8x H100 80GB GPUs, $98.32/hr
#   Use Spot: 70% savings. Save checkpoints every 30 min.
#
# G-family (GPU — Inference): g4dn, g5, g6
#   NVIDIA GPUs, optimized for inference (not training). More cost-effective.
#   g4dn.xlarge: 4 vCPU, 16GB RAM, 1x T4 GPU (16GB), ~$0.52/hr
#   g5.xlarge:   4 vCPU, 16GB RAM, 1x A10G GPU (24GB), ~$1.01/hr
#   Good for: serving ML models in production (image classification, LLMs)
#
# I-family (Storage Optimized): i3, i3en, im4gn, is4gen
#   NVMe SSD local storage. For I/O-intensive databases.
#   i3.large: 2 vCPU, 15GB RAM, 475GB NVMe (~$0.15/hr)
#   WARNING: Instance store is EPHEMERAL — lost on stop/terminate. Use for temp data.
#
# GRAVITON (ARM): m6g, c6g, r6g, t4g, etc.
#   AWS's ARM processors. Built in-house. Up to 40% better price/performance than Intel.
#   Requires ARM-compiled binaries and container images.
#   Check: docker buildx build --platform linux/arm64 (build multi-arch)
#   When to migrate: existing workloads with no x86-specific code. Almost always worth it.

echo "=== List available instance types for current region ==="
aws ec2 describe-instance-types \
    --filters Name=instance-type,Values=m6i.* \
    --query 'InstanceTypes[*].{Type:InstanceType,vCPU:VCpuInfo.DefaultVCpus,RAM:MemoryInfo.SizeInMiB}' \
    --output table 2>/dev/null || echo "(requires AWS CLI)"

# =============================================================================
# EC2 PRICING MODELS
# =============================================================================
# ON-DEMAND: Pay by the second (60s minimum). No commitment.
#   Use for: unpredictable load, dev/test, short-lived workloads.
#   Cost: baseline price. Example: m6i.xlarge = $0.192/hr
#
# RESERVED INSTANCES (RI): 1-year or 3-year commitment.
#   Standard RI:     Commit to specific instance type/region. 40-60% savings.
#   Convertible RI:  Can exchange for different type. 30-40% savings.
#   3-year no upfront: Maximum savings (~60%). For stable baseline loads.
#   Use for: consistent baseline that runs 24/7.
#   IMPORTANT: RIs are a billing discount, not a capacity reservation.
#
# SAVINGS PLANS: More flexible than RIs.
#   Compute Savings Plan: Commit to $/hr of compute, applies across EC2, Fargate, Lambda.
#   EC2 Savings Plan:     Commit to $/hr for a specific instance family in a region.
#   Generally prefer Savings Plans over RIs for flexibility.
#
# SPOT INSTANCES: Bid on unused EC2 capacity. Up to 90% savings.
#   AWS can reclaim with 2-minute warning.
#   Use for: batch jobs, ML training, CI/CD workers, stateless web servers (with care).
#   NOT for: stateful databases, anything that can't tolerate interruption.
#   DESIGN PATTERN: Save checkpoint to S3 every 5 minutes. On interruption, restore from checkpoint.

echo ""
echo "=== Current Spot Prices ==="
aws ec2 describe-spot-price-history \
    --instance-types m6i.xlarge c6i.xlarge \
    --product-descriptions "Linux/UNIX" \
    --start-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --query 'SpotPriceHistory[*].{Type:InstanceType,AZ:AvailabilityZone,Price:SpotPrice}' \
    --output table 2>/dev/null || echo "(requires AWS CLI)"

# =============================================================================
# AUTO SCALING GROUPS (ASG)
# =============================================================================
# ASG = group of EC2 instances that scales in/out automatically.
# Components:
#   Launch Template:  What to launch (AMI, instance type, security groups, user data)
#   ASG:              How many to launch, where, when
#   Scaling Policies: When to scale (CPU > 70%? Add 2 instances)
#   ALB Target Group: Where to route traffic (ASG registers/deregisters here)
#
# SCALING POLICY TYPES:
#   Target Tracking (RECOMMENDED): "Maintain 60% CPU" — ASG calculates scaling automatically
#   Step Scaling:    "If CPU > 70%, add 2. If CPU > 90%, add 4."
#   Scheduled:       "Every Monday 8am, set min to 20 (business hours)"
#   Predictive:      ML predicts load, pre-scales before spike (good for daily patterns)
#
# KEY SETTINGS:
#   MinSize:         Never go below this (e.g., 2 for HA across 2 AZs)
#   MaxSize:         Never exceed this (cost protection, e.g., 50)
#   DesiredCapacity: Current target (ASG adjusts toward this)
#   Cooldown period: After scaling, wait N seconds before next scale action (avoid thrashing)
#
# MULTI-AZ DISTRIBUTION:
#   ASG automatically distributes instances across AZs you specify.
#   Use at least 2 AZs (3 recommended). One AZ fails = others absorb traffic.

echo ""
echo "=== Create Auto Scaling Group ==="
# Step 1: Create Launch Template
aws ec2 create-launch-template \
    --launch-template-name my-api-server \
    --version-description "v1" \
    --launch-template-data '{
        "ImageId": "ami-0abcdef1234567890",
        "InstanceType": "m6i.xlarge",
        "SecurityGroupIds": ["sg-0123456789abcdef0"],
        "IamInstanceProfile": {"Arn": "arn:aws:iam::123456789:instance-profile/api-server-profile"},
        "UserData": "'"$(echo '#!/bin/bash
# User data runs as root on FIRST BOOT ONLY
# Use for: install packages, pull config, start services
yum update -y
yum install -y amazon-cloudwatch-agent
# Pull app config from S3 (never hardcode secrets in user data)
aws s3 cp s3://my-configs/app-config.json /etc/app/config.json
systemctl start my-api-server' | base64)"'",
        "TagSpecifications": [{
            "ResourceType": "instance",
            "Tags": [
                {"Key": "Name", "Value": "api-server"},
                {"Key": "Environment", "Value": "production"},
                {"Key": "Team", "Value": "platform"}
            ]
        }]
    }' 2>/dev/null || echo "(requires AWS CLI)"

# Step 2: Create ASG
aws autoscaling create-auto-scaling-group \
    --auto-scaling-group-name api-server-asg \
    --launch-template LaunchTemplateName=my-api-server,Version='$Latest' \
    --min-size 2 \
    --max-size 20 \
    --desired-capacity 4 \
    --vpc-zone-identifier "subnet-aaa,subnet-bbb,subnet-ccc" \
    --target-group-arns "arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/api-tg/abc123" \
    --health-check-type ELB \
    --health-check-grace-period 300 \
    --tags Key=Environment,Value=production,PropagateAtLaunch=true 2>/dev/null || echo "(requires AWS CLI)"

# Step 3: Target tracking scaling policy (maintain 60% CPU)
aws autoscaling put-scaling-policy \
    --auto-scaling-group-name api-server-asg \
    --policy-name target-tracking-60-cpu \
    --policy-type TargetTrackingScaling \
    --target-tracking-configuration '{
        "PredefinedMetricSpecification": {
            "PredefinedMetricType": "ASGAverageCPUUtilization"
        },
        "TargetValue": 60.0,
        "DisableScaleIn": false
    }' 2>/dev/null || echo "(requires AWS CLI)"

# =============================================================================
# ALB: Application Load Balancer
# =============================================================================
# ALB operates at Layer 7 (HTTP/HTTPS). Routes based on: path, host, headers, query string.
# NLB (Network Load Balancer): Layer 4 (TCP/UDP). For ultra-low latency, millions of requests/sec.
#
# ALB features critical for production:
#   Health checks:           Removes unhealthy instances from rotation automatically
#   Connection draining:     ALB waits for in-flight requests before removing instance
#                            (deregistration delay: default 300s, reduce to 30s for fast deploys)
#   Sticky sessions:         Route same user to same instance (avoid if possible — stateless is better)
#   WAF integration:         Block SQLi, XSS, rate limiting at the load balancer layer
#   Access logs:             Every request logged to S3 (privacy/compliance consideration)

# =============================================================================
# EC2 USER DATA: Bootstrap script
# =============================================================================
# User data = shell script that runs as root on FIRST BOOT ONLY.
# Idempotent design: script may run again if instance is part of ASG and AMI is rebuilt.
# Better approach: use AWS SSM Parameter Store / S3 for config, not hardcoded in user data.
# Best approach: build AMI with Packer (baked dependencies, faster startup).

# =============================================================================
# SERVERLESS COMPUTE OPTIONS
# =============================================================================
# AWS LAMBDA:
#   Event-driven functions. No server management.
#   Limits: 15-minute max execution, 10GB memory, 10GB ephemeral /tmp storage
#   Concurrency: default 1000 concurrent executions per region (request increase for prod)
#   Cold start: first invocation has 100-500ms delay (JVM/Python/Node.js vary)
#   PROVISIONED CONCURRENCY: pre-warm N instances = no cold starts (costs money)
#   Pricing: $0.20/million requests + $0.0000166667/GB-second
#   Use for: S3 triggers, API Gateway backend, EventBridge rules, scheduled tasks
#
# AWS FARGATE:
#   Serverless containers. Runs ECS or EKS pods without managing EC2 nodes.
#   You define: CPU and memory per task. AWS provisions the underlying host.
#   Cost: typically 20-30% more expensive than equivalent EC2, but no node ops overhead.
#   Use for: teams that want containers without cluster node management.
#
# GCP CLOUD RUN:
#   Container-based serverless. Scale to zero. HTTP-triggered.
#   More flexible than Lambda (any container, any language, longer timeouts).
#   Excellent price/performance for HTTP workloads.
#
# AZURE CONTAINER APPS:
#   Kubernetes-based serverless containers. KEDA for event-driven scaling.
#   Good for: Dapr microservices, event-driven workloads.

echo ""
echo "=== Lambda Function Example ==="
# Deploy a Lambda function
aws lambda create-function \
    --function-name process-upload \
    --runtime python3.12 \
    --handler handler.lambda_handler \
    --zip-file fileb://function.zip \
    --role arn:aws:iam::123456789:role/lambda-execution-role \
    --timeout 300 \
    --memory-size 512 \
    --environment Variables='{BUCKET_NAME=my-bucket,LOG_LEVEL=INFO}' \
    --tracing-config Mode=Active 2>/dev/null || echo "(requires AWS CLI + function.zip)"

# =============================================================================
# CONTAINER SERVICES COMPARISON
# =============================================================================
# ECS (Elastic Container Service):
#   AWS-native container orchestrator. Simpler than Kubernetes.
#   Two modes: EC2 launch type (you manage nodes) or Fargate (serverless).
#   Good for: teams new to containers, simple microservices, AWS-native workloads.
#   Task Definition: defines containers, CPU, memory, volumes, IAM role.
#   Service: ensures N tasks are always running, integrates with ALB.
#
# EKS (Elastic Kubernetes Service):
#   Managed Kubernetes. You get a K8s control plane managed by AWS.
#   Nodes: EC2 (self-managed or managed node groups) or Fargate.
#   Good for: teams that know K8s, want portability, have complex networking needs.
#   Managed node groups: ASG-backed EC2 nodes with automatic OS patching.
#
# GKE (Google Kubernetes Engine):
#   Industry-leading managed K8s. First to market with new K8s features.
#   GKE Autopilot: fully managed nodes — you only define pods, GCP manages everything else.
#   Recommended over EKS if you're on GCP. Genuinely better control plane.
#
# AKS (Azure Kubernetes Service):
#   Managed K8s on Azure. Good integration with Azure AD (RBAC), Azure Monitor.
#   Use when: your team is Azure-first, you have Windows containers.

# =============================================================================
# GPU FOR ML: Choosing the right instance
# =============================================================================
# TRAINING (high memory bandwidth, many cores):
#   AWS p4d.24xlarge: 8x NVIDIA A100 40GB, ~$32/hr ($10/hr spot)
#   AWS p5.48xlarge:  8x NVIDIA H100 80GB, ~$98/hr ($25/hr spot)
#   GCP a2-highgpu-8g: 8x A100 40GB, comparable pricing
#   Azure NC-series: A100 GPUs, strong Windows ML stack
#
# INFERENCE (lower latency, fewer cards needed):
#   AWS g4dn.xlarge:  1x T4 GPU, $0.526/hr — best value for inference
#   AWS g5.xlarge:    1x A10G GPU, $1.006/hr — faster for LLM inference
#   AWS inf2.xlarge:  AWS Inferentia2 chip — custom ASIC, best cost for Llama/Stable Diffusion
#
# SPOT FOR TRAINING: Save 60-70% with careful checkpointing
aws ec2 request-spot-instances \
    --spot-price "10.00" \
    --instance-count 1 \
    --type one-time \
    --launch-specification '{
        "ImageId": "ami-deep-learning",
        "InstanceType": "p4d.24xlarge",
        "Placement": {"AvailabilityZone": "us-east-1a"}
    }' 2>/dev/null || echo "(example only — large instance)"

# =============================================================================
# GRAVITON: The ARM case for cost savings
# =============================================================================
# AWS Graviton3 (m7g, c7g, r7g) vs equivalent Intel (m7i, c7i, r7i):
#   Up to 40% better price/performance
#   Lower power consumption (sustainability benefit)
#   Requires: ARM-compiled code and container images
#
# Migration checklist:
#   ✅ Build multi-arch Docker images: docker buildx build --platform linux/amd64,linux/arm64
#   ✅ Check third-party packages support ARM (most do by 2025)
#   ✅ No native x86 assembly code or x86-only libraries
#   ✅ Test on arm64 runner in CI (GitHub Actions supports arm64 runners)
#
# RESULT: ~30-40% reduction in EC2 costs for same workload.
# This is one of the highest-ROI optimizations for EC2-heavy applications.

echo ""
echo "=== Complete ASG Example: API Server with ALB + Spot Fallback ==="
echo "Architecture:"
echo "  - ASG with mixed instances: 50% on-demand m6g (Graviton), 50% Spot m6g"
echo "  - Target tracking: 60% CPU"
echo "  - 3 AZs: us-east-1a, us-east-1b, us-east-1c"
echo "  - ALB health check: /health, 30s interval"
echo "  - Deregistration delay: 30s (fast deploys)"
echo "  - Min: 3 (1 per AZ for HA)"
echo "  - Max: 30 (cost cap)"
echo "  - Spot: m6g.xlarge, m6g.2xlarge, m6i.xlarge (multiple types = more capacity)"
