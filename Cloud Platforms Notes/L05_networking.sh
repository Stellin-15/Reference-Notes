#!/usr/bin/env bash
# ============================================================
# L05: Cloud Networking
# ============================================================
# WHAT: Complete guide to cloud networking concepts — VPCs,
#       subnets, gateways, security, DNS, load balancers, and
#       hybrid connectivity — with AWS CLI examples and
#       Azure/GCP equivalents in comments.
# WHY:  Networking is the foundation of every cloud deployment.
#       Misconfigurations here cause outages, data exposure, or
#       latency. A senior engineer designs the network before
#       writing any application code.
# LEVEL: Advanced
# ============================================================
# CONCEPT OVERVIEW:
#   Cloud networking lets you define an isolated virtual network
#   (VPC/VNet) and control exactly how traffic flows — between
#   subnets, to the internet, to on-prem, and between services.
#   Everything builds on IP addressing (CIDR), routing tables,
#   and firewall rules that mirror physical data-center concepts
#   but managed via APIs.
#
# PRODUCTION USE CASE:
#   A three-tier web app (load balancer → app servers → database)
#   uses public subnets for the ALB, private subnets for EC2/EKS,
#   and isolated private subnets for RDS — with NAT Gateways,
#   Security Groups, and Route 53 health checks for failover.
#
# COMMON MISTAKES:
#   - Putting databases in public subnets (exposure risk).
#   - Using a single NAT Gateway (single point of failure — one
#     per AZ for HA).
#   - Opening 0.0.0.0/0 on SSH/RDP to Security Groups.
#   - Overlapping CIDR blocks between VPCs you later need to peer.
#   - Forgetting that NACLs are STATELESS — you need both inbound
#     AND outbound rules for a connection to work.
# ============================================================

set -euo pipefail

# ── Variables ────────────────────────────────────────────────
REGION="us-east-1"
AZ_A="us-east-1a"
AZ_B="us-east-1b"
AZ_C="us-east-1c"

# ============================================================
# SECTION 1: VPC (Virtual Private Cloud)
# ============================================================
# WHAT: Your logically isolated network in the cloud.
#       Think of it as your own private data-center network
#       hosted on AWS infrastructure.
#
# CIDR block basics:
#   10.0.0.0/16  → 65,536 IPs  (most common for a VPC)
#   10.0.0.0/24  → 256 IPs     (typical subnet)
#   /16 = 16 bits fixed, 16 bits flexible → 2^16 = 65536 hosts
#
# AWS specifics:
#   - One DEFAULT VPC per region (172.31.0.0/16), created automatically.
#   - Default VPC has public subnets in every AZ — convenient for
#     getting started, but never use for production.
#   - Max 5 VPCs per region (soft limit, can request increase).
#   - IPv6 supported (dual-stack).
#
# GCP equivalent:  VPC (but GCP VPCs are GLOBAL — one VPC spans
#                  all regions; subnets are regional).
# Azure equivalent: VNet (Virtual Network) — regional, like AWS VPC.
# ============================================================

# Create a VPC with a /16 CIDR — gives you 65,536 IPs to subdivide
VPC_ID=$(aws ec2 create-vpc \
  --cidr-block 10.0.0.0/16 \
  --region "$REGION" \
  --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=prod-vpc},{Key=Environment,Value=production}]' \
  --query 'Vpc.VpcId' \
  --output text)

echo "Created VPC: $VPC_ID"

# Enable DNS hostname resolution inside the VPC — required for
# RDS endpoint names and other AWS service DNS to resolve.
aws ec2 modify-vpc-attribute \
  --vpc-id "$VPC_ID" \
  --enable-dns-hostnames

# ============================================================
# SECTION 2: Subnets — Subdividing Your VPC
# ============================================================
# WHAT: A subnet is a range of IPs within your VPC CIDR.
#       Resources (EC2, RDS, Lambda ENIs) live in subnets.
#       A subnet resides in exactly ONE Availability Zone.
#
# Public subnet:  Has a route to an Internet Gateway (IGW).
#                 Resources can get public IPs and be reached
#                 from the internet.
#
# Private subnet: No route to IGW. Resources have only private IPs.
#                 Can reach internet OUTBOUND via NAT Gateway.
#                 Databases, app servers — never directly exposed.
#
# 3-TIER ARCHITECTURE (best practice for production):
#   Tier 1 — Public subnets:       ALB / NLB (load balancers)
#   Tier 2 — Private app subnets:  EC2 / EKS worker nodes
#   Tier 3 — Private data subnets: RDS, ElastiCache, OpenSearch
#   Deploy each tier across 3 AZs for high availability.
#
# AWS reserves 5 IPs per subnet:
#   .0  = network address
#   .1  = VPC router
#   .2  = DNS server
#   .3  = reserved for future use
#   .255 = broadcast (not used in AWS but still reserved)
#   So a /24 gives you 256 - 5 = 251 usable IPs.
#
# GCP: Subnets are regional (span all AZs in that region).
# Azure: Subnets span the entire VNet (no AZ binding by default).
# ============================================================

# --- Public subnets (one per AZ) — for load balancers ---
# /24 = 256 IPs each. Using .0.x, .1.x, .2.x for public.
PUB_SUBNET_A=$(aws ec2 create-subnet \
  --vpc-id "$VPC_ID" \
  --cidr-block 10.0.0.0/24 \
  --availability-zone "$AZ_A" \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=public-1a},{Key=Tier,Value=public}]' \
  --query 'Subnet.SubnetId' --output text)

PUB_SUBNET_B=$(aws ec2 create-subnet \
  --vpc-id "$VPC_ID" \
  --cidr-block 10.0.1.0/24 \
  --availability-zone "$AZ_B" \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=public-1b},{Key=Tier,Value=public}]' \
  --query 'Subnet.SubnetId' --output text)

PUB_SUBNET_C=$(aws ec2 create-subnet \
  --vpc-id "$VPC_ID" \
  --cidr-block 10.0.2.0/24 \
  --availability-zone "$AZ_C" \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=public-1c},{Key=Tier,Value=public}]' \
  --query 'Subnet.SubnetId' --output text)

# --- Private app subnets — EC2 / EKS worker nodes ---
# Using 10.0.10.x, .11.x, .12.x block
APP_SUBNET_A=$(aws ec2 create-subnet \
  --vpc-id "$VPC_ID" \
  --cidr-block 10.0.10.0/24 \
  --availability-zone "$AZ_A" \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=app-1a},{Key=Tier,Value=private-app}]' \
  --query 'Subnet.SubnetId' --output text)

APP_SUBNET_B=$(aws ec2 create-subnet \
  --vpc-id "$VPC_ID" \
  --cidr-block 10.0.11.0/24 \
  --availability-zone "$AZ_B" \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=app-1b},{Key=Tier,Value=private-app}]' \
  --query 'Subnet.SubnetId' --output text)

APP_SUBNET_C=$(aws ec2 create-subnet \
  --vpc-id "$VPC_ID" \
  --cidr-block 10.0.12.0/24 \
  --availability-zone "$AZ_C" \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=app-1c},{Key=Tier,Value=private-app}]' \
  --query 'Subnet.SubnetId' --output text)

# --- Private data subnets — RDS, ElastiCache, OpenSearch ---
# Using 10.0.20.x, .21.x, .22.x block — most restricted tier
DATA_SUBNET_A=$(aws ec2 create-subnet \
  --vpc-id "$VPC_ID" \
  --cidr-block 10.0.20.0/24 \
  --availability-zone "$AZ_A" \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=data-1a},{Key=Tier,Value=private-data}]' \
  --query 'Subnet.SubnetId' --output text)

echo "Created all 3-tier subnets across 3 AZs"

# ============================================================
# SECTION 3: Internet Gateway (IGW)
# ============================================================
# WHAT: Allows traffic between your VPC and the public internet.
#       Horizontally scaled, redundant, highly available.
#       Only ONE IGW per VPC.
#
# HOW it makes a subnet "public":
#   1. Attach IGW to VPC.
#   2. Add a route: 0.0.0.0/0 → IGW in the route table.
#   3. Associate that route table with the subnet.
#   4. Enable auto-assign public IPs on the subnet (optional).
#
# GCP equivalent: Cloud Router + Cloud NAT (GCP subnets are
#                 private by default; internet access requires
#                 explicit configuration).
# Azure equivalent: Internet route is in the default route table
#                   automatically; an Internet Gateway is implicit.
# ============================================================

# Create and attach the IGW
IGW_ID=$(aws ec2 create-internet-gateway \
  --tag-specifications 'ResourceType=internet-gateway,Tags=[{Key=Name,Value=prod-igw}]' \
  --query 'InternetGateway.InternetGatewayId' --output text)

aws ec2 attach-internet-gateway \
  --internet-gateway-id "$IGW_ID" \
  --vpc-id "$VPC_ID"

# Create a PUBLIC route table and add the default route to IGW
PUB_RT=$(aws ec2 create-route-table \
  --vpc-id "$VPC_ID" \
  --tag-specifications 'ResourceType=route-table,Tags=[{Key=Name,Value=public-rt}]' \
  --query 'RouteTable.RouteTableId' --output text)

# 0.0.0.0/0 means "all traffic not matching a more specific route"
aws ec2 create-route \
  --route-table-id "$PUB_RT" \
  --destination-cidr-block 0.0.0.0/0 \
  --gateway-id "$IGW_ID"

# Associate public subnets with the public route table
for SUBNET in "$PUB_SUBNET_A" "$PUB_SUBNET_B" "$PUB_SUBNET_C"; do
  aws ec2 associate-route-table \
    --route-table-id "$PUB_RT" \
    --subnet-id "$SUBNET"
done

# ============================================================
# SECTION 4: NAT Gateway — Private Subnet Internet Access
# ============================================================
# WHAT: Allows instances in PRIVATE subnets to initiate outbound
#       connections to the internet (OS updates, API calls, package
#       downloads) WITHOUT being directly reachable from the internet.
#       NAT = Network Address Translation.
#
# WHY NAT Gateway vs NAT Instance:
#   NAT Gateway: managed, highly available WITHIN an AZ, scales to
#                45 Gbps, no patching needed.
#   NAT Instance: EC2 you manage yourself. Cheaper but single point
#                 of failure. Legacy approach.
#
# COST CONSIDERATION (put in budget estimates):
#   NAT Gateway costs $0.045/hr PLUS $0.045/GB processed.
#   One NAT Gateway = ~$32.40/month before data transfer.
#   For HA, you need ONE NAT GATEWAY PER AZ → 3x cost = ~$97/month.
#   This is necessary because if your AZ-A NAT Gateway is in AZ-A
#   and AZ-B goes down, routing private subnet traffic cross-AZ
#   to AZ-A NAT adds latency AND cross-AZ data transfer cost.
#
# GCP equivalent: Cloud NAT — regional, managed, no per-AZ setup.
# Azure equivalent: NAT Gateway or Azure Firewall with SNAT.
# ============================================================

# Each NAT Gateway needs an Elastic IP (public IP that doesn't change)
EIP_A=$(aws ec2 allocate-address --domain vpc --query 'AllocationId' --output text)
EIP_B=$(aws ec2 allocate-address --domain vpc --query 'AllocationId' --output text)
EIP_C=$(aws ec2 allocate-address --domain vpc --query 'AllocationId' --output text)

# NAT Gateways go in PUBLIC subnets (they need internet access themselves)
NAT_A=$(aws ec2 create-nat-gateway \
  --subnet-id "$PUB_SUBNET_A" \
  --allocation-id "$EIP_A" \
  --tag-specifications 'ResourceType=natgateway,Tags=[{Key=Name,Value=nat-1a}]' \
  --query 'NatGateway.NatGatewayId' --output text)

NAT_B=$(aws ec2 create-nat-gateway \
  --subnet-id "$PUB_SUBNET_B" \
  --allocation-id "$EIP_B" \
  --tag-specifications 'ResourceType=natgateway,Tags=[{Key=Name,Value=nat-1b}]' \
  --query 'NatGateway.NatGatewayId' --output text)

# Wait for NAT Gateways to become available (~60 seconds)
echo "Waiting for NAT Gateways to become available..."
aws ec2 wait nat-gateway-available --nat-gateway-ids "$NAT_A" "$NAT_B"

# Each private route table routes 0.0.0.0/0 to its LOCAL AZ NAT Gateway
# This keeps traffic within the same AZ → no cross-AZ charges
PRIV_RT_A=$(aws ec2 create-route-table --vpc-id "$VPC_ID" \
  --tag-specifications 'ResourceType=route-table,Tags=[{Key=Name,Value=private-rt-1a}]' \
  --query 'RouteTable.RouteTableId' --output text)

aws ec2 create-route \
  --route-table-id "$PRIV_RT_A" \
  --destination-cidr-block 0.0.0.0/0 \
  --nat-gateway-id "$NAT_A"

aws ec2 associate-route-table --route-table-id "$PRIV_RT_A" --subnet-id "$APP_SUBNET_A"
aws ec2 associate-route-table --route-table-id "$PRIV_RT_A" --subnet-id "$DATA_SUBNET_A"

# ============================================================
# SECTION 5: Security Groups — Instance-Level Firewall
# ============================================================
# WHAT: Virtual firewall for individual instances/services.
#       Applied at the ENI (Elastic Network Interface) level.
#
# KEY PROPERTIES:
#   STATEFUL: If you allow inbound port 443, the response traffic
#             is automatically allowed outbound — no explicit rule needed.
#   ALLOW ONLY: You can only create ALLOW rules. There is no DENY.
#               Everything not explicitly allowed is implicitly denied.
#   CHAINED: Security groups can reference OTHER security groups as
#            the source. Example: allow traffic from the ALB security
#            group on port 8080 — don't use IPs.
#
# GCP equivalent: Firewall Rules (VPC-level, but can target by tag or
#                 service account — more flexible in some ways).
# Azure equivalent: NSG (Network Security Group) — attached to NIC or
#                   subnet. Has both allow and deny rules.
# ============================================================

# ALB Security Group — accepts HTTPS from anywhere
ALB_SG=$(aws ec2 create-security-group \
  --group-name "prod-alb-sg" \
  --description "Security group for Application Load Balancer" \
  --vpc-id "$VPC_ID" \
  --query 'GroupId' --output text)

aws ec2 authorize-security-group-ingress \
  --group-id "$ALB_SG" \
  --protocol tcp --port 443 --cidr 0.0.0.0/0

aws ec2 authorize-security-group-ingress \
  --group-id "$ALB_SG" \
  --protocol tcp --port 80 --cidr 0.0.0.0/0

# App Server Security Group — only accepts traffic FROM the ALB
# This is the key pattern: reference SG, not IP ranges.
# If the ALB scales to 10 instances, all their IPs are automatically
# covered because we reference the SG, not individual IPs.
APP_SG=$(aws ec2 create-security-group \
  --group-name "prod-app-sg" \
  --description "App servers — only allow traffic from ALB" \
  --vpc-id "$VPC_ID" \
  --query 'GroupId' --output text)

aws ec2 authorize-security-group-ingress \
  --group-id "$APP_SG" \
  --protocol tcp --port 8080 \
  --source-group "$ALB_SG"  # Reference the ALB security group, not a CIDR

# RDS Security Group — only accepts MySQL from app servers
RDS_SG=$(aws ec2 create-security-group \
  --group-name "prod-rds-sg" \
  --description "RDS — only allow traffic from app servers" \
  --vpc-id "$VPC_ID" \
  --query 'GroupId' --output text)

aws ec2 authorize-security-group-ingress \
  --group-id "$RDS_SG" \
  --protocol tcp --port 3306 \
  --source-group "$APP_SG"

# ============================================================
# SECTION 6: NACLs — Subnet-Level Firewall
# ============================================================
# WHAT: Network Access Control Lists. Stateless firewall rules
#       at the SUBNET level (not instance level like SGs).
#
# KEY DIFFERENCES from Security Groups:
#   STATELESS: Return traffic must be explicitly allowed.
#              If you allow inbound port 443, you must also
#              allow outbound ephemeral ports (1024-65535) for
#              the response to get back.
#   ALLOW + DENY: You can explicitly DENY traffic.
#   ORDERED: Rules evaluated lowest number first. First match wins.
#            Always add a final DENY ALL (rule number 32767) — AWS
#            adds this automatically.
#   APPLIED TO ALL instances in the subnet.
#
# WHEN TO USE: Rarely. SGs handle 99% of cases. Use NACLs for:
#   - Explicitly blocking a known malicious IP range.
#   - Additional defense-in-depth layer.
#   - Subnet-level isolation without modifying instance SGs.
#
# GCP equivalent: Firewall Rules with deny action (network-level).
# Azure equivalent: NSG with deny rules.
# ============================================================

# Create NACL for the data subnet — extra protection for databases
DATA_NACL=$(aws ec2 create-network-acl \
  --vpc-id "$VPC_ID" \
  --tag-specifications 'ResourceType=network-acl,Tags=[{Key=Name,Value=data-nacl}]' \
  --query 'NetworkAcl.NetworkAclId' --output text)

# INBOUND: Allow MySQL (3306) from app subnet range only
aws ec2 create-network-acl-entry \
  --network-acl-id "$DATA_NACL" \
  --ingress \
  --rule-number 100 \
  --protocol tcp \
  --port-range From=3306,To=3306 \
  --cidr-block 10.0.10.0/22 \
  --rule-action allow

# INBOUND: Deny all other traffic (explicit, belt-and-suspenders)
aws ec2 create-network-acl-entry \
  --network-acl-id "$DATA_NACL" \
  --ingress \
  --rule-number 32766 \
  --protocol -1 \
  --cidr-block 0.0.0.0/0 \
  --rule-action deny

# OUTBOUND: Allow ephemeral ports back to app servers (STATELESS — needed!)
# Ephemeral ports: TCP client chooses a random high port for responses
aws ec2 create-network-acl-entry \
  --network-acl-id "$DATA_NACL" \
  --egress \
  --rule-number 100 \
  --protocol tcp \
  --port-range From=1024,To=65535 \
  --cidr-block 10.0.10.0/22 \
  --rule-action allow

# ============================================================
# SECTION 7: VPC Peering and Transit Gateway
# ============================================================
# WHAT: Ways to connect multiple VPCs together.
#
# VPC PEERING:
#   - Direct 1-to-1 connection between two VPCs.
#   - Can be same account or cross-account, same or cross-region.
#   - NOT TRANSITIVE: If A peers B, and B peers C,
#     A cannot reach C via B. You must create A-C peering separately.
#   - No bandwidth limits. No additional hop latency.
#   - Use case: small number of VPCs (2-5).
#
# TRANSIT GATEWAY (TGW):
#   - Hub-and-spoke model: all VPCs connect to the TGW.
#   - TRANSITIVE ROUTING: VPCs can reach each other through TGW.
#   - Connects: VPCs, on-prem (via VPN or Direct Connect), other TGWs.
#   - Supports up to 5,000 VPC attachments.
#   - Cost: $0.05/hr per attachment + $0.02/GB.
#   - Use case: large number of VPCs, on-prem connectivity, hub network.
#
# GCP equivalent: VPC Peering (no transitive), or Shared VPC (one host
#                 VPC shared across multiple projects).
# Azure equivalent: VNet Peering, Virtual WAN (like Transit Gateway).
# ============================================================

# Create a VPC Peering connection between prod and dev VPCs
DEV_VPC_ID="vpc-0dev1234example"  # existing dev VPC

PEERING_ID=$(aws ec2 create-vpc-peering-connection \
  --vpc-id "$VPC_ID" \
  --peer-vpc-id "$DEV_VPC_ID" \
  --peer-region "$REGION" \
  --query 'VpcPeeringConnection.VpcPeeringConnectionId' --output text)

# Must accept from the other side (or same account can auto-accept)
aws ec2 accept-vpc-peering-connection \
  --vpc-peering-connection-id "$PEERING_ID"

# Add routes to enable traffic (peering creates the tunnel but you
# still need routing table entries on BOTH sides)
aws ec2 create-route \
  --route-table-id "$PRIV_RT_A" \
  --destination-cidr-block 10.1.0.0/16 \   # dev VPC CIDR
  --vpc-peering-connection-id "$PEERING_ID"

# Transit Gateway — for large-scale multi-VPC connectivity
TGW_ID=$(aws ec2 create-transit-gateway \
  --description "Central hub for all prod VPCs" \
  --options "DefaultRouteTableAssociation=enable,DefaultRouteTablePropagation=enable" \
  --query 'TransitGateway.TransitGatewayId' --output text)

# Attach VPC to Transit Gateway (one attachment per VPC)
aws ec2 create-transit-gateway-vpc-attachment \
  --transit-gateway-id "$TGW_ID" \
  --vpc-id "$VPC_ID" \
  --subnet-ids "$APP_SUBNET_A" "$APP_SUBNET_B" "$APP_SUBNET_C"

# ============================================================
# SECTION 8: PrivateLink — Private Access to AWS Services
# ============================================================
# WHAT: Access AWS services (S3, DynamoDB, SQS, KMS, etc.) or
#       third-party SaaS services WITHOUT traffic leaving your VPC
#       and going over the internet.
#
# TWO TYPES of VPC Endpoints:
#
#   INTERFACE ENDPOINT:
#     - Creates an ENI (Elastic Network Interface) with a private IP
#       in your subnet.
#     - Traffic to the service goes through this private ENI.
#     - Supported services: KMS, SQS, SNS, CloudWatch, Secrets Manager,
#       ECR, API Gateway, Lambda, and 100+ more.
#     - Cost: $0.01/hr per AZ + $0.01/GB.
#
#   GATEWAY ENDPOINT:
#     - Free. No ENI. Works by modifying your route table.
#     - Only for S3 and DynamoDB.
#     - Adds a prefix list route to your route table.
#     - Use this ALWAYS for S3/DynamoDB in private subnets.
#
# WHY it matters:
#   - Security: traffic never crosses the internet.
#   - Performance: lower latency, no NAT Gateway data transfer cost.
#   - Compliance: keeps regulated data in private network.
#
# GCP: Private Service Connect, Private Google Access.
# Azure: Private Endpoint, Private Link Service.
# ============================================================

# S3 Gateway Endpoint — FREE, no data transfer cost through NAT Gateway
# This one change can save hundreds of dollars/month if you transfer
# large amounts of data to S3 from private subnets
aws ec2 create-vpc-endpoint \
  --vpc-id "$VPC_ID" \
  --service-name "com.amazonaws.${REGION}.s3" \
  --route-table-ids "$PRIV_RT_A"  \
  --vpc-endpoint-type Gateway

# KMS Interface Endpoint — encrypt/decrypt calls stay private
aws ec2 create-vpc-endpoint \
  --vpc-id "$VPC_ID" \
  --service-name "com.amazonaws.${REGION}.kms" \
  --vpc-endpoint-type Interface \
  --subnet-ids "$APP_SUBNET_A" "$APP_SUBNET_B" \
  --security-group-ids "$APP_SG" \
  --private-dns-enabled  # requests to kms.us-east-1.amazonaws.com resolve to private IP

# ============================================================
# SECTION 9: Route 53 — DNS and Routing Policies
# ============================================================
# WHAT: AWS managed DNS service. Global (not regional).
#       Routing policies determine WHICH record to return
#       when multiple records exist for the same domain.
#
# ROUTING POLICIES:
#   SIMPLE:        Return one record. No health checks. Basic.
#   WEIGHTED:      Route X% to endpoint A, Y% to B.
#                  Use case: A/B testing, gradual migration (canary).
#                  E.g.: 90% traffic to v1, 10% to v2.
#   LATENCY:       Route to the region with lowest latency for the
#                  requester. AWS measures actual latency, not geography.
#                  Use case: multi-region apps for lowest response time.
#   FAILOVER:      Primary record served normally. If health check fails,
#                  Route 53 automatically serves the secondary record.
#                  Use case: active-passive disaster recovery.
#   GEOLOCATION:   Route based on the geographic location of the user.
#                  Continent → Country → State granularity.
#                  Use case: serve localized content, data residency.
#   GEOPROXIMITY:  Like Geolocation but with bias adjustments.
#                  Shift traffic to/from a region by changing bias value.
#                  Requires Route 53 Traffic Flow.
#   MULTI-VALUE:   Return up to 8 healthy records (chosen randomly).
#                  Client-side load balancing. NOT a replacement for ALB.
#                  Use case: simple redundancy without a real LB.
#
# HEALTH CHECKS:
#   Route 53 health checkers (15+ global locations) probe your endpoint.
#   Combined with Failover routing = automatic regional failover.
#   Health check → CloudWatch alarm → SNS alert to on-call engineer.
#
# GCP: Cloud DNS — routing policies added more recently.
# Azure: Azure DNS + Azure Traffic Manager (routing policies).
# ============================================================

# Create a health check for the primary region endpoint
HEALTH_CHECK_ID=$(aws route53 create-health-check \
  --caller-reference "$(date +%s)" \
  --health-check-config '{
    "Type": "HTTPS",
    "FullyQualifiedDomainName": "api.example.com",
    "Port": 443,
    "ResourcePath": "/health",
    "RequestInterval": 30,
    "FailureThreshold": 3
  }' \
  --query 'HealthCheck.Id' --output text)

# Create failover DNS records — primary (us-east-1), secondary (us-west-2)
# When the health check fails, Route 53 automatically switches to secondary
# This is how you get sub-minute RTO for regional failover

# Primary record — must have health check attached
aws route53 change-resource-record-sets \
  --hosted-zone-id "Z1234EXAMPLE" \
  --change-batch '{
    "Changes": [{
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "api.example.com",
        "Type": "A",
        "SetIdentifier": "primary-us-east-1",
        "Failover": "PRIMARY",
        "AliasTarget": {
          "HostedZoneId": "Z35SXDOTRQ7X7K",
          "DNSName": "prod-alb-123456.us-east-1.elb.amazonaws.com",
          "EvaluateTargetHealth": true
        },
        "HealthCheckId": "'"$HEALTH_CHECK_ID"'"
      }
    }]
  }'

# Weighted routing example: 90/10 canary deployment
# aws route53 change-resource-record-sets \
#   --hosted-zone-id "Z1234EXAMPLE" \
#   --change-batch '{
#     "Changes": [
#       {
#         "Action": "CREATE",
#         "ResourceRecordSet": {
#           "Name": "api.example.com",
#           "Type": "A",
#           "SetIdentifier": "v1-stable",
#           "Weight": 90,
#           "AliasTarget": { ... v1 ALB ... }
#         }
#       },
#       {
#         "Action": "CREATE",
#         "ResourceRecordSet": {
#           "Name": "api.example.com",
#           "Type": "A",
#           "SetIdentifier": "v2-canary",
#           "Weight": 10,
#           "AliasTarget": { ... v2 ALB ... }
#         }
#       }
#     ]
#   }'

# ============================================================
# SECTION 10: Load Balancers
# ============================================================
# WHAT: Distribute incoming traffic across multiple targets
#       (EC2, ECS tasks, Lambda, IP addresses).
#
# THREE TYPES in AWS:
#
# ALB (Application Load Balancer) — Layer 7:
#   - HTTP/HTTPS aware. Can route based on URL path, host header,
#     query string, HTTP method.
#   - Supports WebSocket and HTTP/2.
#   - Returns fixed response, redirects (HTTP→HTTPS).
#   - Target groups: EC2, ECS, Lambda, IP.
#   - Use case: web apps, microservices, REST APIs.
#   - Cannot assign static IP (DNS name changes).
#
# NLB (Network Load Balancer) — Layer 4:
#   - TCP/UDP/TLS. Ultra-low latency (microseconds).
#   - Handles millions of connections per second.
#   - Preserves client source IP (ALB replaces it with ALB IP).
#   - Has a static IP per AZ (important for whitelisting).
#   - Use case: HFT trading, gaming, VoIP, IoT, anything needing
#     raw TCP performance or static IPs.
#
# GWLB (Gateway Load Balancer) — Layer 3:
#   - For inline traffic inspection appliances (firewalls, IDS/IPS).
#   - Traffic flows through GWLB to your firewall fleet, then to destination.
#   - Uses GENEVE protocol. Transparent to the application.
#   - Use case: Palo Alto, Fortinet, or custom security appliances in VPC.
#
# GCP: Cloud Load Balancing — global Anycast, HTTP(S) LB, TCP proxy,
#       UDP LB, Internal LB. Premium Tier uses Google's global network.
# Azure: Azure Load Balancer (L4), Application Gateway (L7, + WAF),
#        Azure Front Door (global, CDN + WAF + LB).
# ============================================================

# Create an Application Load Balancer
ALB_ARN=$(aws elbv2 create-load-balancer \
  --name "prod-alb" \
  --subnets "$PUB_SUBNET_A" "$PUB_SUBNET_B" "$PUB_SUBNET_C" \
  --security-groups "$ALB_SG" \
  --scheme internet-facing \
  --type application \
  --ip-address-type ipv4 \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text)

# Target group — EC2 instances that the ALB will route to
TG_ARN=$(aws elbv2 create-target-group \
  --name "prod-app-tg" \
  --protocol HTTP --port 8080 \
  --vpc-id "$VPC_ID" \
  --health-check-path "/health" \
  --health-check-interval-seconds 30 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 3 \
  --query 'TargetGroups[0].TargetGroupArn' --output text)

# HTTPS Listener — requires an ACM certificate
# aws elbv2 create-listener \
#   --load-balancer-arn "$ALB_ARN" \
#   --protocol HTTPS --port 443 \
#   --certificates CertificateArn=arn:aws:acm:us-east-1:123:certificate/abc \
#   --default-actions Type=forward,TargetGroupArn="$TG_ARN"

# Path-based routing: /api/* → API target group, /* → frontend target group
# aws elbv2 create-rule \
#   --listener-arn "$LISTENER_ARN" \
#   --priority 100 \
#   --conditions '[{"Field":"path-pattern","Values":["/api/*"]}]' \
#   --actions '[{"Type":"forward","TargetGroupArn":"'"$API_TG_ARN"'"}]'

# ============================================================
# SECTION 11: Direct Connect / ExpressRoute / Cloud Interconnect
# ============================================================
# WHAT: Dedicated private physical connection from your on-premises
#       data center to the cloud provider's network. NOT internet-based.
#
# WHY over VPN:
#   - Consistent bandwidth (1Gbps to 100Gbps connections).
#   - Consistent latency (not subject to internet congestion).
#   - Lower data transfer pricing (vs internet egress).
#   - Required for: regulatory compliance, real-time financial data,
#     large-volume data migration, hybrid workloads.
#
# AWS Direct Connect:
#   - Connect at an AWS Direct Connect location (colocation facility).
#   - Dedicated connection: 1G/10G/100G (you own the port).
#   - Hosted connection: via partner, 50Mbps to 10Gbps.
#   - Link to VPC via Virtual Private Gateway or Transit Gateway.
#   - For HA: two Direct Connect connections from different providers.
#   - Backup: Site-to-Site VPN as failover (much lower bandwidth but
#     provides connectivity if Direct Connect circuit fails).
#
# GCP: Cloud Interconnect — Dedicated (10G/100G) or Partner Interconnect.
# Azure: ExpressRoute — 50Mbps to 100Gbps. ExpressRoute Global Reach
#        lets you connect on-prem locations through Azure backbone.
#
# COST NOTE: Direct Connect pricing = port hour + data transfer out.
#   10Gbps dedicated port: ~$1,620/month. Partner hosted varies.
# ============================================================

# VPN as backup to Direct Connect (or standalone hybrid connectivity)
# VPN goes encrypted over internet — not Direct Connect quality but free setup
# aws ec2 create-customer-gateway \
#   --type ipsec.1 \
#   --public-ip "203.0.113.1" \    # your on-prem router public IP
#   --bgp-asn 65000

# aws ec2 create-vpn-gateway \
#   --type ipsec.1 \
#   --amazon-side-asn 64512

# aws ec2 create-vpn-connection \
#   --type ipsec.1 \
#   --customer-gateway-id "$CGW_ID" \
#   --vpn-gateway-id "$VGW_ID" \
#   --options '{"StaticRoutesOnly":false}'   # false = use BGP for dynamic routing

echo "Networking setup complete."
echo "VPC: $VPC_ID"
echo "ALB: $ALB_ARN"
echo "NAT Gateways: $NAT_A (AZ-A), $NAT_B (AZ-B)"
echo ""
echo "REMINDER: NAT Gateways cost ~\$0.045/hr each. Remember to"
echo "delete unused NAT Gateways in non-production environments."
