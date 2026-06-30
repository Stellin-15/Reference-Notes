#!/usr/bin/env bash
# =============================================================================
# WHAT: Cloud Computing Fundamentals and Architecture Concepts
# WHY:  Cloud is the default infrastructure for modern software. Understanding
#       the models, trade-offs, and provider differences is table stakes for
#       any architect designing systems that serve millions of users.
# LEVEL: Senior / Architect — production systems at scale
# =============================================================================
#
# CONCEPT OVERVIEW
# ----------------
# Cloud computing = renting compute, storage, networking, and managed services
# from a provider (AWS, GCP, Azure) instead of buying and operating your own hardware.
#
# The promise: infinite scale, pay-per-use, global reach, no hardware operations.
# The reality: complexity shifts from hardware management to cloud service expertise.
#
# PRODUCTION USE CASE
# -------------------
# A startup launches on AWS. At 100 users: EC2 + RDS. At 100k users: add load balancer,
# multi-AZ, CDN. At 10M users: multi-region, global database, service mesh.
# Cloud makes this growth possible without buying data centers.
#
# COMMON MISTAKES
# ---------------
# - Single-AZ deployment (AZ outage = full downtime)
# - Lift-and-shift without using managed services (pay cloud prices, get no cloud benefits)
# - Ignoring egress costs (can be 30-40% of AWS bill for data-heavy apps)
# - No tagging strategy (can't track costs by team/service without tags)
# - Over-engineering for scale you don't have (YAGNI applies to cloud too)
# =============================================================================

set -euo pipefail

# =============================================================================
# SERVICE MODELS: IaaS vs PaaS vs SaaS
# =============================================================================
# The "cloud stack" — how much YOU manage vs how much the PROVIDER manages.
#
# IaaS — Infrastructure as a Service
#   Provider manages: Physical hardware, networking, hypervisor
#   YOU manage:       OS, runtime, middleware, application, data
#   Example:          AWS EC2, GCP Compute Engine, Azure VMs
#   Good for:         Full control, custom OS config, legacy apps
#   Bad for:          Small teams (too much operational burden)
#
# PaaS — Platform as a Service
#   Provider manages: Hardware + OS + runtime + middleware
#   YOU manage:       Application code + data
#   Example:          AWS Elastic Beanstalk, GCP App Engine, Azure App Service
#                     AWS Lambda (serverless = extreme PaaS), GCP Cloud Run
#   Good for:         Developer productivity, rapid iteration
#   Bad for:          Highly custom runtime requirements
#
# SaaS — Software as a Service
#   Provider manages: Everything (hardware through application)
#   YOU manage:       Configuration and your data within the SaaS
#   Example:          Gmail, Salesforce, GitHub, Datadog, Snowflake
#   Good for:         Commodity software (email, CRM, monitoring)
#   Bad for:          Core competitive differentiators (don't outsource your product)
#
# SHARED RESPONSIBILITY MODEL (critical for security compliance):
#   The provider is responsible for "security OF the cloud" (hardware, hypervisor, network).
#   YOU are responsible for "security IN the cloud" (your data, IAM, encryption, patching OS).
#
# Key implication: AWS will not patch your EC2 instances. AWS WILL patch RDS instances.
# RDS = PaaS for databases. EC2 = IaaS. Choose managed services to reduce your burden.

echo "=== Service Models ==="
echo "IaaS (EC2): you own OS, runtime, app"
echo "PaaS (Lambda/Cloud Run): you own only app code"
echo "SaaS (RDS, ElastiCache): you own configuration and data"
echo ""

# =============================================================================
# REGIONS AND AVAILABILITY ZONES
# =============================================================================
# Region:
#   A geographic area containing multiple data centers.
#   Examples: us-east-1 (N. Virginia), eu-west-1 (Ireland), ap-southeast-1 (Singapore)
#   AWS: 33 regions. GCP: 40+ regions. Azure: 60+ regions (includes Azure Gov, China).
#   Data residency laws (GDPR, SOC2): choose region where you can legally store user data.
#   Latency: pick region closest to users OR nearest to other services you depend on.
#
# Availability Zone (AZ):
#   An isolated datacenter (or cluster of datacenters) within a region.
#   Each region has 2-6 AZs (typically 3).
#   Isolated: separate power, cooling, networking. AZ failure ≠ region failure.
#   Examples: us-east-1a, us-east-1b, us-east-1c
#
# MINIMUM HA ARCHITECTURE: deploy across 3 AZs.
#   - One AZ fails (hardware failure, power, networking issue)
#   - Remaining 2 AZs absorb traffic
#   - Services continue at reduced capacity
#   - Cost: ~33% more resources (must run at 150% of peak in 2 AZs to absorb 1 AZ loss)
#
# Edge Locations: 550+ Points of Presence for CloudFront CDN.
#   Cache content at the edge, close to users. Not the same as AZs.

echo "=== Regions and AZs ==="
# List AWS regions
# aws ec2 describe-regions --query 'Regions[*].RegionName' --output table

# Check which AZs are available in current region
aws ec2 describe-availability-zones \
    --region us-east-1 \
    --query 'AvailabilityZones[*].{Name:ZoneName,State:State}' \
    --output table

# =============================================================================
# GLOBAL vs REGIONAL SERVICES
# =============================================================================
# GLOBAL services (single namespace, available everywhere):
#   AWS IAM:        Users, roles, policies are global
#   AWS Route 53:   DNS is global
#   AWS CloudFront: CDN edge network is global
#   AWS S3:         Bucket NAMES are global (but data lives in one region)
#
# REGIONAL services (must create separately in each region you use):
#   AWS EC2:        Instances exist in one region/AZ
#   AWS VPC:        Network is regional
#   AWS RDS:        Databases are regional (Multi-AZ = within one region)
#   AWS EKS:        Kubernetes cluster is regional
#   AWS Lambda:     Functions are regional (deploy same function per region for multi-region)
#
# WHY THIS MATTERS:
#   - For multi-region disaster recovery: you must replicate regional resources
#   - IAM role created in us-east-1 works in eu-west-1 (global)
#   - RDS in us-east-1 does NOT automatically exist in eu-west-1

# =============================================================================
# AWS vs GCP vs AZURE: SERVICE COMPARISON TABLE
# =============================================================================
# Service Category     | AWS                    | GCP                    | Azure
# ---------------------|------------------------|------------------------|-------------------------
# Virtual Machines     | EC2                    | Compute Engine (GCE)   | Azure VMs
# VM Scale Sets        | Auto Scaling Groups    | Managed Instance Groups | VM Scale Sets (VMSS)
# Kubernetes (managed) | EKS                    | GKE                    | AKS
# Serverless Compute   | Lambda                 | Cloud Functions        | Azure Functions
# Serverless Containers| Fargate / App Runner   | Cloud Run              | Azure Container Apps
# Object Storage       | S3                     | Cloud Storage (GCS)    | Azure Blob Storage
# Block Storage        | EBS                    | Persistent Disk        | Azure Managed Disks
# File Storage         | EFS (NFS)              | Filestore              | Azure Files
# Relational DB        | RDS, Aurora            | Cloud SQL              | Azure SQL, Cosmos DB
# NoSQL DB             | DynamoDB               | Firestore, Bigtable    | Cosmos DB
# In-Memory Cache      | ElastiCache (Redis)    | Memorystore            | Azure Cache for Redis
# Data Warehouse       | Redshift               | BigQuery               | Azure Synapse Analytics
# Data Lake            | S3 + Athena + Glue     | Cloud Storage + BigQuery| Azure Data Lake + Synapse
# ML/AI Platform       | SageMaker              | Vertex AI              | Azure Machine Learning
# CDN                  | CloudFront             | Cloud CDN              | Azure CDN / Front Door
# DNS                  | Route 53               | Cloud DNS              | Azure DNS
# Load Balancer        | ALB/NLB/CLB            | Cloud Load Balancing   | Azure Load Balancer / App GW
# VPN                  | Site-to-Site VPN / DX  | Cloud VPN / Interconnect| ExpressRoute / VPN GW
# Identity (IAM)       | IAM                    | IAM + Workload Identity | Azure Active Directory / RBAC
# Secret Management    | Secrets Manager / SSM  | Secret Manager         | Azure Key Vault
# Monitoring/Metrics   | CloudWatch             | Cloud Monitoring       | Azure Monitor
# Logging              | CloudWatch Logs        | Cloud Logging          | Log Analytics (Azure Monitor)
# Message Queue        | SQS                    | Pub/Sub                | Service Bus / Storage Queues
# Event Streaming      | Kinesis, MSK (Kafka)   | Pub/Sub, Dataflow      | Event Hubs, Event Grid
# Container Registry   | ECR                    | Artifact Registry      | Azure Container Registry (ACR)
# CI/CD                | CodePipeline/CodeBuild | Cloud Build            | Azure DevOps / GitHub Actions
# Infrastructure as Code| CloudFormation        | Deployment Manager     | ARM Templates / Bicep
# Service Mesh         | App Mesh               | Anthos Service Mesh    | Azure Service Fabric

echo ""
echo "=== Cloud Provider Comparison ==="
echo "AWS:   Broadest service catalog, largest ecosystem, best documentation"
echo "GCP:   Best for ML/AI (TPUs, Vertex), strongest Kubernetes (GKE Autopilot)"
echo "Azure: Best for Microsoft/Windows shops, enterprise licensing, Active Directory"
echo ""

# =============================================================================
# CLOUD-NATIVE vs LIFT-AND-SHIFT
# =============================================================================
# LIFT-AND-SHIFT: Move existing on-prem workload to cloud with minimal changes.
#   - Take VMware VM → run same software on EC2
#   - Get: reliability improvements, maybe faster hardware
#   - Miss: managed services, auto-scaling, serverless, PaaS benefits
#   - Cost: often MORE expensive than on-prem (EC2 < bare metal per core)
#   - Value: migration speed. Good first step, not a destination.
#
# CLOUD-NATIVE: Design for cloud from the ground up (or refactor to use it).
#   - Use managed services: RDS instead of Postgres on EC2, ElastiCache not Redis on EC2
#   - Use auto-scaling: ASGs, Lambda, Fargate — pay for actual load
#   - Use ephemeral compute: containers, spot instances — design for failures
#   - Use managed observability: CloudWatch, Datadog instead of running Prometheus yourself
#   - 12-factor app principles: config from environment, stateless processes, disposable
#
# ECONOMIC REALITY:
#   Cloud-native: ~40-60% lower infrastructure cost at scale vs lift-and-shift
#   Reason: managed services = no ops overhead, auto-scaling = no over-provisioning
#   Counter-example: At extreme scale (Netflix, Dropbox), owning hardware is cheaper.
#   Rule of thumb: cloud-native wins until ~$5M/year cloud spend.

# =============================================================================
# AWS WELL-ARCHITECTED FRAMEWORK
# =============================================================================
# 6 pillars for evaluating cloud architecture quality:
#
# 1. OPERATIONAL EXCELLENCE
#    - Automate operations (IaC, CI/CD)
#    - Make frequent, small changes (not big bang deploys)
#    - Anticipate failure (run game days, chaos engineering)
#    - Learn from failure (blameless post-mortems)
#
# 2. SECURITY
#    - Implement a strong identity foundation (least privilege IAM)
#    - Enable traceability (CloudTrail, GuardDuty)
#    - Apply security at all layers (VPC, SG, WAF, encryption)
#    - Protect data in transit and at rest (TLS, KMS)
#    - Keep people away from data (automation > human access)
#
# 3. RELIABILITY
#    - Automatically recover from failure (health checks, ASG, Multi-AZ)
#    - Test recovery procedures (chaos engineering, DR drills)
#    - Scale horizontally to increase availability
#    - Stop guessing capacity (auto-scaling)
#    - Manage change in automation (IaC not console clicks)
#
# 4. PERFORMANCE EFFICIENCY
#    - Use advanced technologies as managed services
#    - Go global in minutes (CloudFront, multi-region)
#    - Use serverless architectures where appropriate
#    - Experiment more often (cloud makes testing easy)
#    - Mechanical sympathy (understand the technology you use)
#
# 5. COST OPTIMIZATION
#    - Adopt a consumption model (pay for what you use)
#    - Measure overall efficiency (cost per request, not total cost)
#    - Stop spending on undifferentiated heavy lifting
#    - Analyze and attribute expenditure (tag everything)
#    - Use managed services to reduce cost of ownership
#
# 6. SUSTAINABILITY
#    - Understand your impact (carbon footprint tools)
#    - Maximize utilization (right-sizing, not idle resources)
#    - Anticipate and adopt new, more efficient offerings
#    - Use managed services (AWS optimizes energy at scale better than you can)

# GCP equivalent: Google Cloud Architecture Framework (same 6 pillars, different names)
# Azure equivalent: Azure Well-Architected Framework (5 pillars)

# =============================================================================
# CapEx vs OpEx
# =============================================================================
# CapEx (Capital Expenditure): Buy hardware upfront. Depreciate over 3-5 years.
#   - On-premises data center: buy servers ($5-20k each), networking, power, cooling
#   - Predictable cost if load is predictable
#   - YOU bear the risk of over/under-provisioning
#   - Finance: CapEx appears on balance sheet, depreciated
#
# OpEx (Operational Expenditure): Pay monthly as you go.
#   - Cloud: pay per hour/second of EC2, per GB of S3, per invocation of Lambda
#   - Finance: OpEx is immediate expense (hits P&L monthly)
#   - Benefit: no upfront cost, scale instantly, stop paying when done
#   - Risk: costs can spike with usage spikes if no budget alerts
#
# HYBRID: Reserved Instances/Savings Plans = 1-3 year commitment = CapEx-like deal on cloud
#   Best of both: cloud flexibility, but with pricing commitment for baseline load.

echo ""
echo "=== Cost Management Commands ==="
# Check current month's costs by service
aws ce get-cost-and-usage \
    --time-period Start=2026-06-01,End=2026-06-30 \
    --granularity MONTHLY \
    --metrics "BlendedCost" \
    --group-by Type=DIMENSION,Key=SERVICE \
    --query 'ResultsByTime[0].Groups[*].{Service:Keys[0],Cost:Metrics.BlendedCost.Amount}' \
    --output table 2>/dev/null || echo "(requires AWS CLI configured)"

# =============================================================================
# WHEN TO USE WHICH CLOUD: Decision Framework
# =============================================================================
# DEFAULT CHOICE: AWS
#   Reason: Largest service catalog (200+ services), most third-party integrations,
#   most engineers know it, largest community, most documentation, most Terraform modules.
#   If you have no other constraints: AWS is the safe, boring, correct choice.
#
# CHOOSE GCP IF:
#   - ML/AI is core to your product (Vertex AI, TPUs, BigQuery ML are industry-leading)
#   - You need the best managed Kubernetes (GKE Autopilot is genuinely superior)
#   - BigQuery is your primary data warehouse (significantly cheaper than Redshift for analytics)
#   - You have a Google Workspace + GSuite organization
#
# CHOOSE AZURE IF:
#   - You're a Microsoft enterprise (Office 365, Active Directory, Windows workloads)
#   - You have Microsoft licensing (Azure Hybrid Benefit = huge discount for Windows Server SQL)
#   - Your team is .NET/C# (Azure has best .NET tooling)
#   - Government/defense (Azure Government, highest compliance certifications)
#
# MULTI-CLOUD: Often more marketing than reality.
#   Legitimate uses: regulatory requirement, M&A (acquired company uses different cloud),
#   best-of-breed per workload, negotiation leverage.
#   Cost: 2x the operational expertise, 2x the Terraform modules to maintain.
#   Advice: avoid unless you have a specific reason. Pick one and go deep.

echo ""
echo "=== Architecture Decision: New Startup Cloud Choice ==="
echo "Recommendation: AWS (us-east-1 default)"
echo "Rationale:"
echo "  - Largest talent pool: most engineers know AWS"
echo "  - Broadest free tier for initial development"
echo "  - Best startup credits program (AWS Activate: up to $100k)"
echo "  - Route 53 + CloudFront + ALB + RDS = production-ready in days"
echo "  - Terraform AWS provider is most mature and documented"
echo ""
echo "Starting stack:"
echo "  Compute:  ECS Fargate (serverless containers, no node management)"
echo "  Database: Aurora Serverless v2 (scales to zero at low usage)"
echo "  Cache:    ElastiCache Serverless Redis"
echo "  Storage:  S3 + CloudFront"
echo "  DNS:      Route 53"
echo "  Secrets:  AWS Secrets Manager"
echo "  Monitor:  CloudWatch + Grafana Cloud (free tier)"
