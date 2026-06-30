#!/usr/bin/env bash
# ============================================================
# L08: High Availability Architecture for Millions of Users
# ============================================================
# WHAT: Design patterns, AWS services, and CLI examples for
#       building systems that remain available and performant
#       under extreme load, AZ failures, region outages, DDoS
#       attacks, and traffic spikes.
# WHY:  At scale, failure is inevitable. HA architecture means
#       individual component failures don't cause user-visible
#       downtime. The goal: eliminate single points of failure,
#       detect faults automatically, and recover without human
#       intervention.
# LEVEL: Advanced
# ============================================================
# CONCEPT OVERVIEW:
#   High availability = redundancy + health monitoring + automatic
#   failover. You design for failure by asking: "what happens if
#   THIS component fails right now?" If the answer is "the whole
#   system goes down," that component needs redundancy.
#   HA tiers: 99.9% (8.7h downtime/year), 99.99% (52min/year),
#   99.999% (5min/year — five nines, very expensive to achieve).
#
# PRODUCTION USE CASE:
#   Social platform with 1M DAU. Peak traffic: 3x baseline
#   (sporting events, news breaks). Requirements: 99.99% uptime,
#   <200ms p99 latency, survive regional outage, <5min RTO.
#   Solution: multi-AZ deployment in primary region, multi-region
#   active-active with Global Accelerator, DynamoDB Global Tables,
#   CloudFront CDN, WAF + Shield, ASG with predictive scaling.
#
# COMMON MISTAKES:
#   - Single NAT Gateway (AZ-level failure takes down private subnets).
#   - RDS in single AZ (one AZ failure = database outage).
#   - Hardcoded IPs instead of DNS names (can't failover easily).
#   - No circuit breaker (downstream outage cascades to your service).
#   - Scaling policy triggers AFTER CPU already at 100% (too late).
#   - No DLQ on async queues (messages silently lost on failure).
#   - Not testing failover in production (chaos engineering neglected).
#   - WAF protecting only some entry points (CDN bypassed by direct ALB access).
# ============================================================

set -euo pipefail

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
PRIMARY_REGION="us-east-1"
SECONDARY_REGION="us-west-2"

# ============================================================
# SECTION 1: Multi-AZ Deployment
# ============================================================
# WHAT: Deploying redundant instances of every component across
#       multiple Availability Zones. An AZ is a physically separate
#       data center within a region (different power, cooling, networking).
#       AZ failure is not rare — plan for it.
#
# COMPONENTS AND THEIR MULTI-AZ STRATEGY:
#
#   ALB (Application Load Balancer):
#     - Multi-AZ by default when you specify subnets in 2+ AZs.
#     - If AZ-A fails, ALB routes only to targets in AZ-B and AZ-C.
#     - "Cross-zone load balancing" distributes evenly across ALL
#       instances regardless of AZ (default ON for ALB).
#
#   Auto Scaling Group (ASG):
#     - Specify subnets in 3 AZs. ASG balances instances across AZs.
#     - "Rebalancing": if AZ-A recovers, ASG gradually moves instances back.
#     - Min/Max/Desired: design Min for 2 AZs, Desired for 3.
#       Example: Min=2 (survives 1 AZ failure), Desired=6 (2 per AZ).
#
#   RDS Multi-AZ:
#     - Synchronous replication to standby in different AZ.
#     - Automatic failover: ~60-120 seconds for DNS to update.
#     - Standby is NOT readable (only Aurora Multi-AZ has readable replicas).
#     - Use RDS Multi-AZ for all production databases. +Cost ~2x single AZ.
#
#   ElastiCache (Redis):
#     - Cluster mode disabled: one primary + 1-5 replicas across AZs.
#       Reads can go to replicas. Failover: ~30s (replica promoted).
#     - Cluster mode enabled: data sharded across multiple node groups.
#       Each shard has primary + replica in different AZs.
#
#   EKS:
#     - Node groups spread across 3 AZs (use topologySpreadConstraints).
#     - Control plane is AWS-managed, already multi-AZ.
#     - Pod disruption budgets (PDB) prevent all pods from being
#       unavailable simultaneously during AZ drain.
# ============================================================

# ASG across 3 AZs with health checks
LAUNCH_TEMPLATE_ID=$(aws ec2 create-launch-template \
  --launch-template-name "prod-app-lt" \
  --version-description "v1" \
  --launch-template-data '{
    "ImageId": "ami-0c02fb55956c7d316",
    "InstanceType": "m6i.large",
    "IamInstanceProfile": {"Name": "AppInstanceProfile"},
    "SecurityGroupIds": ["sg-appserver"],
    "UserData": "'"$(base64 -w0 << 'USERDATA'
#!/bin/bash
yum update -y
aws s3 cp s3://my-app-bucket/app.tar.gz /opt/app/
cd /opt/app && tar xzf app.tar.gz
systemctl start myapp
USERDATA
)"'",
    "TagSpecifications": [{
      "ResourceType": "instance",
      "Tags": [{"Key":"Name","Value":"prod-app"},{"Key":"Environment","Value":"prod"}]
    }],
    "MetadataOptions": {
      "HttpTokens": "required",
      "HttpPutResponseHopLimit": 1
    }
  }' \
  --query 'LaunchTemplate.LaunchTemplateId' --output text)

# Create ASG — uses instance weights to prioritize m6i.large but fall back to m5.large
aws autoscaling create-auto-scaling-group \
  --auto-scaling-group-name "prod-app-asg" \
  --launch-template "LaunchTemplateId=${LAUNCH_TEMPLATE_ID},Version=1" \
  --vpc-zone-identifier "subnet-app-1a,subnet-app-1b,subnet-app-1c" \
  --min-size 3 \
  --max-size 30 \
  --desired-capacity 6 \
  --health-check-type ELB \
  --health-check-grace-period 300 \
  --target-group-arns "arn:aws:elasticloadbalancing:us-east-1:${ACCOUNT_ID}:targetgroup/prod-app-tg/abc123" \
  --default-cooldown 300 \
  --tags "Key=Environment,Value=prod,PropagateAtLaunch=true"

# Enable instance refresh for zero-downtime deployments
aws autoscaling start-instance-refresh \
  --auto-scaling-group-name "prod-app-asg" \
  --preferences '{
    "MinHealthyPercentage": 90,
    "InstanceWarmup": 300,
    "CheckpointPercentages": [20, 50, 100],
    "CheckpointDelay": 600
  }'

# ============================================================
# SECTION 2: Auto Scaling Policies
# ============================================================
# WHAT: Policies that automatically adjust capacity based on demand.
#       Never run at 100% or 0% utilization — find the right balance.
#
# THREE TYPES OF SCALING POLICIES:
#
#   TARGET TRACKING (simplest, recommended):
#     Set a target metric (e.g., 60% CPU). ASG automatically adds/removes
#     instances to maintain that target. AWS handles the math.
#     Why 60% CPU and not 80%? You need headroom to absorb a spike
#     while new instances are launching (takes 2-5 min).
#     Also use: RequestCountPerTarget (requests/instance), custom metrics.
#
#   STEP SCALING (custom thresholds):
#     "If CPU 70-90%, add 2 instances. If CPU >90%, add 5."
#     More control than target tracking. Use for uneven scaling needs.
#
#   SCHEDULED SCALING:
#     Pre-scale before known events: product launches, sporting events,
#     Monday morning work rush. Set desired capacity at specific times.
#     Example: every Monday 8AM EST, set desired=20. 6PM, set desired=6.
#
#   PREDICTIVE SCALING (ML-based):
#     Analyzes historical patterns (daily/weekly cycles) and pre-scales
#     proactively before load arrives. Combine with reactive for best results.
#     Training period: 14 days of data needed.
# ============================================================

# Target tracking — maintain 60% average CPU
aws autoscaling put-scaling-policy \
  --auto-scaling-group-name "prod-app-asg" \
  --policy-name "cpu-target-tracking" \
  --policy-type TargetTrackingScaling \
  --target-tracking-configuration '{
    "PredefinedMetricSpecification": {
      "PredefinedMetricType": "ASGAverageCPUUtilization"
    },
    "TargetValue": 60.0,
    "ScaleInCooldown": 300,
    "ScaleOutCooldown": 60
  }'

# Track requests per instance (better for web apps than CPU)
aws autoscaling put-scaling-policy \
  --auto-scaling-group-name "prod-app-asg" \
  --policy-name "request-count-tracking" \
  --policy-type TargetTrackingScaling \
  --target-tracking-configuration '{
    "PredefinedMetricSpecification": {
      "PredefinedMetricType": "ALBRequestCountPerTarget",
      "ResourceLabel": "app/prod-alb/abc123/targetgroup/prod-app-tg/def456"
    },
    "TargetValue": 1000.0
  }'

# Scheduled scale-up before Monday morning traffic (cron in UTC)
aws autoscaling put-scheduled-update-group-action \
  --auto-scaling-group-name "prod-app-asg" \
  --scheduled-action-name "monday-morning-scale-up" \
  --recurrence "0 12 * * MON" \
  --desired-capacity 12 \
  --min-size 6

# Predictive scaling — learn from 2 weeks of historical data
aws autoscaling put-scaling-policy \
  --auto-scaling-group-name "prod-app-asg" \
  --policy-name "predictive-scaling" \
  --policy-type PredictiveScaling \
  --predictive-scaling-configuration '{
    "MetricSpecifications": [{
      "TargetValue": 60.0,
      "PredefinedMetricPairSpecification": {
        "PredefinedMetricType": "ASGCPUUtilization"
      }
    }],
    "Mode": "ForecastAndScale",
    "SchedulingBufferTime": 300
  }'

# ============================================================
# SECTION 3: Multi-Region Active-Active
# ============================================================
# WHAT: Run your full application stack in multiple AWS regions
#       simultaneously. Users are routed to the closest region.
#       If a region fails, traffic is automatically rerouted.
#
# COMPONENTS:
#
#   Global Accelerator:
#     - Anycast IPs (two static IPs for your whole app).
#     - Routes users to closest healthy region using AWS global backbone.
#     - Faster than Route 53 failover: <30s for endpoint failure detection.
#     - Consistent routing: same user always goes to same region (sticky sessions).
#     - Protects against DDoS (absorbs at edge).
#     - Cost: $0.025/hr per accelerator + $0.01/GB.
#     - Use over Route 53 latency routing when: you need fast failover,
#       static IPs, or gaming/VoIP (UDP support).
#
#   DynamoDB Global Tables:
#     - Active-active multi-region replication.
#     - Each region can read AND write.
#     - Conflict resolution: last-writer-wins.
#     - Replication lag: <1 second for most writes.
#     - Cost: higher than single-region (replicated write units charged).
#
#   Aurora Global Database:
#     - Primary region: read/write. Up to 5 secondary regions: read-only.
#     - Replication lag: <1 second.
#     - Failover: promote secondary to primary in <1 minute.
#     - Use for: relational data that needs global read performance
#       and fast regional failover.
#
#   CloudFront:
#     - CDN at 400+ edge locations globally.
#     - Cache static assets (JS, CSS, images) close to users.
#     - Can also proxy dynamic content (reduces TCP connection overhead).
#     - Origin failover: primary origin → secondary if primary fails.
# ============================================================

# Global Accelerator for multi-region routing
ACCELERATOR_ARN=$(aws globalaccelerator create-accelerator \
  --name "prod-global-accelerator" \
  --ip-address-type IPV4 \
  --enabled \
  --region us-east-1 \
  --query 'Accelerator.AcceleratorArn' --output text)

# Listener for HTTPS
LISTENER_ARN=$(aws globalaccelerator create-listener \
  --accelerator-arn "$ACCELERATOR_ARN" \
  --protocol TCP \
  --port-ranges '[{"FromPort":443,"ToPort":443}]' \
  --client-affinity SOURCE_IP \
  --region us-east-1 \
  --query 'Listener.ListenerArn' --output text)

# Endpoint groups — one per region, with traffic dial and health checks
# Primary region (us-east-1) gets 100% traffic normally
aws globalaccelerator create-endpoint-group \
  --listener-arn "$LISTENER_ARN" \
  --endpoint-group-region "$PRIMARY_REGION" \
  --traffic-dial-percentage 100 \
  --health-check-path "/health" \
  --health-check-interval-seconds 10 \
  --threshold-count 2 \
  --endpoint-configurations \
    "EndpointId=arn:aws:elasticloadbalancing:us-east-1:${ACCOUNT_ID}:loadbalancer/app/prod-alb/abc123,Weight=100" \
  --region us-east-1

# Secondary region (us-west-2) — Global Accelerator routes here if primary fails
aws globalaccelerator create-endpoint-group \
  --listener-arn "$LISTENER_ARN" \
  --endpoint-group-region "$SECONDARY_REGION" \
  --traffic-dial-percentage 100 \
  --health-check-path "/health" \
  --health-check-interval-seconds 10 \
  --threshold-count 2 \
  --endpoint-configurations \
    "EndpointId=arn:aws:elasticloadbalancing:us-west-2:${ACCOUNT_ID}:loadbalancer/app/prod-alb-west/def456,Weight=100" \
  --region us-east-1

# Create DynamoDB Global Table (add secondary region to existing table)
aws dynamodb create-global-table \
  --global-table-name "orders" \
  --replication-group \
    "[{\"RegionName\":\"${PRIMARY_REGION}\"},{\"RegionName\":\"${SECONDARY_REGION}\"}]" \
  --region "$PRIMARY_REGION"

# Or update an existing table to add a replica region
# aws dynamodb update-table \
#   --table-name orders \
#   --replica-updates '[{"Create":{"RegionName":"us-west-2"}}]' \
#   --region us-east-1

# ============================================================
# SECTION 4: Multi-Region Active-Passive (DR)
# ============================================================
# WHAT: One region is active (handles all traffic). Another is
#       the standby (warm or cold). On failure, promote standby.
#
# DR TIERS AND THEIR COSTS:
#
#   Cold Standby (Backup & Restore):
#     RTO: hours. RPO: hours. Cheapest.
#     Restore from S3 backups. Start new instances. Reconfigure.
#     Use for: non-critical workloads, dev/test DR.
#
#   Warm Standby:
#     RTO: 10-30 min. RPO: minutes. Moderate cost.
#     Secondary region has scaled-down infrastructure running.
#     On failover: scale up ASG, promote DB, update Route 53.
#     Use for: production with moderate criticality.
#
#   Hot Standby (Pilot Light is similar):
#     RTO: <5 min. RPO: <1 min. Most expensive.
#     Full infrastructure in secondary region. Data replicated.
#     Failover = update DNS. No scaling needed.
#     Use for: mission-critical, SLA ≥99.99%.
#
# RTO: Recovery Time Objective — how long can you be down.
# RPO: Recovery Point Objective — how much data loss is acceptable.
# These are business requirements from SLA, not technical choices.
# ============================================================

# RDS cross-region read replica (promote to primary on failover)
# This runs in the secondary region
aws rds create-db-instance-read-replica \
  --db-instance-identifier "orders-db-replica-west" \
  --source-db-instance-identifier \
    "arn:aws:rds:${PRIMARY_REGION}:${ACCOUNT_ID}:db:orders-db-primary" \
  --db-instance-class db.r6g.large \
  --region "$SECONDARY_REGION" \
  --availability-zone "${SECONDARY_REGION}a" \
  --no-auto-minor-version-upgrade

# Route 53 failover routing (automatic DNS-based failover)
# Primary record health-checked. On failure, Route 53 uses secondary.
aws route53 change-resource-record-sets \
  --hosted-zone-id "Z1234EXAMPLE" \
  --change-batch '{
    "Changes": [
      {
        "Action": "CREATE",
        "ResourceRecordSet": {
          "Name": "api.example.com",
          "Type": "A",
          "SetIdentifier": "primary-us-east-1",
          "Failover": "PRIMARY",
          "AliasTarget": {
            "HostedZoneId": "Z35SXDOTRQ7X7K",
            "DNSName": "prod-alb.us-east-1.elb.amazonaws.com",
            "EvaluateTargetHealth": true
          },
          "HealthCheckId": "HEALTHCHECK_ID_PRIMARY"
        }
      },
      {
        "Action": "CREATE",
        "ResourceRecordSet": {
          "Name": "api.example.com",
          "Type": "A",
          "SetIdentifier": "secondary-us-west-2",
          "Failover": "SECONDARY",
          "AliasTarget": {
            "HostedZoneId": "Z35SXDOTRQ7X7K",
            "DNSName": "prod-alb.us-west-2.elb.amazonaws.com",
            "EvaluateTargetHealth": true
          }
        }
      }
    ]
  }'

# ============================================================
# SECTION 5: DDoS Protection and WAF
# ============================================================
# WHAT: Multi-layer defense against Distributed Denial of Service
#       attacks (volumetric floods) and application-layer attacks
#       (SQLi, XSS, bot abuse, credential stuffing).
#
# AWS SHIELD:
#   Shield Standard (FREE, automatic):
#     - Protects against common network/transport layer attacks.
#     - SYN floods, UDP reflection, DNS amplification.
#     - Applied to: ELB, CloudFront, Global Accelerator, Route 53.
#     - No action required — enabled for every AWS account.
#
#   Shield Advanced ($3,000/month, 1-year commitment):
#     - 24/7 AWS DDoS Response Team (DRT) assistance.
#     - Attack diagnostics and cost protection (billing credit
#       for AWS resource scaling during an attack).
#     - Near real-time attack visibility in CloudWatch.
#     - L7 (HTTP) attack mitigation via WAF integration.
#     - Protection for: EC2, ELB, CloudFront, Route 53, Global Accelerator.
#     - Use for: high-profile targets, compliance requirements, when
#       the business risk of DDoS exceeds $3k/month.
#
# AWS WAF (Web Application Firewall):
#   Rules inspect HTTP(S) requests at Layer 7:
#   - Managed Rule Groups: maintained by AWS or Partners.
#     * AWSManagedRulesCommonRuleSet: OWASP Top 10 protections.
#     * AWSManagedRulesSQLiRuleSet: SQL injection.
#     * AWSManagedRulesKnownBadInputsRuleSet: Log4j, SSRF, XSS.
#   - Rate-based rules: block IPs exceeding N requests per 5 minutes.
#   - Custom rules: whitelist/blacklist IPs, geo-block, header inspection.
#   - Deploy on: CloudFront, ALB, API Gateway, AppSync, Cognito.
#
# COST: WAF costs $5/month per WebACL + $1/M requests + $1/rule/month.
#       Managed rule groups: $20/month each.
#
# ARCHITECTURE: CloudFront → WAF → ALB → EC2.
#   This is critical: WAF on CloudFront means attacks are blocked at
#   edge, never reaching your ALB or EC2. Put WAF at the outermost layer.
#   ALSO: block direct access to ALB by IP (use header-based check to
#   ensure requests came through CloudFront, not direct to ALB IP).
#
# GCP: Cloud Armor — WAF + DDoS protection. Adaptive protection (ML).
# Azure: Azure DDoS Protection Standard + Azure WAF on Front Door/App GW.
# ============================================================

# Create a WAF WebACL for CloudFront (must be in us-east-1 for CF)
WEBACL_ARN=$(aws wafv2 create-web-acl \
  --name "prod-webacl" \
  --scope CLOUDFRONT \
  --region us-east-1 \
  --default-action '{"Allow":{}}' \
  --visibility-config '{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"prod-webacl"}' \
  --rules '[
    {
      "Name": "AWSManagedRulesCommonRuleSet",
      "Priority": 1,
      "OverrideAction": {"None": {}},
      "Statement": {
        "ManagedRuleGroupStatement": {
          "VendorName": "AWS",
          "Name": "AWSManagedRulesCommonRuleSet"
        }
      },
      "VisibilityConfig": {
        "SampledRequestsEnabled": true,
        "CloudWatchMetricsEnabled": true,
        "MetricName": "CommonRuleSet"
      }
    },
    {
      "Name": "AWSManagedRulesSQLiRuleSet",
      "Priority": 2,
      "OverrideAction": {"None": {}},
      "Statement": {
        "ManagedRuleGroupStatement": {
          "VendorName": "AWS",
          "Name": "AWSManagedRulesSQLiRuleSet"
        }
      },
      "VisibilityConfig": {
        "SampledRequestsEnabled": true,
        "CloudWatchMetricsEnabled": true,
        "MetricName": "SQLiRuleSet"
      }
    },
    {
      "Name": "RateBasedRule",
      "Priority": 3,
      "Action": {"Block": {}},
      "Statement": {
        "RateBasedStatement": {
          "Limit": 2000,
          "AggregateKeyType": "IP"
        }
      },
      "VisibilityConfig": {
        "SampledRequestsEnabled": true,
        "CloudWatchMetricsEnabled": true,
        "MetricName": "RateBasedRule"
      }
    }
  ]' \
  --query 'Summary.ARN' --output text)

echo "WAF WebACL: $WEBACL_ARN"

# ============================================================
# SECTION 6: Circuit Breaker Pattern
# ============================================================
# WHAT: Detect when a downstream service is failing and "open
#       the circuit" — fail fast instead of waiting for timeouts.
#       Prevents cascading failures from propagating.
#
# THREE STATES:
#   CLOSED (normal): requests flow through. Track error rate.
#   OPEN (tripped):  requests fail immediately (no call to downstream).
#                    Return cached response or graceful degradation.
#                    After timeout, try HALF-OPEN.
#   HALF-OPEN:       let a few test requests through. If they succeed,
#                    return to CLOSED. If they fail, back to OPEN.
#
# WHY IT MATTERS:
#   Without circuit breaker: your app waits 30s for each timeout,
#   thread pool fills up waiting, cascading failure hits all your services.
#   With circuit breaker: fail in <1ms, return cached data, alert on-call.
#
# IMPLEMENTATION OPTIONS ON AWS:
#   - App Mesh (AWS service mesh): configure retries and circuit breaking
#     in Envoy proxy sidecars. No code changes required.
#   - AWS App Mesh with virtual services and routes.
#   - Hystrix / Resilience4j in application code (Java).
#   - Polly in .NET applications.
#   - Custom implementation in your service using DynamoDB/ElastiCache
#     to track error counts.
#   - API Gateway integration timeouts and retries.
#
# RELATED: Bulkhead pattern — isolate resources for each dependency.
#   If you share one thread pool for calls to ServiceA and ServiceB,
#   ServiceA slowness can starve ServiceB calls. Use separate pools.
# ============================================================

# App Mesh circuit breaker configuration (in mesh virtual node config)
cat > /tmp/circuit-breaker-config.json << 'MESH'
{
  "spec": {
    "listeners": [{
      "portMapping": {"port": 8080, "protocol": "http"},
      "outlierDetection": {
        "baseEjectionDuration": {"value": 30, "unit": "s"},
        "interval": {"value": 10, "unit": "s"},
        "maxEjectionPercent": 50,
        "maxServerErrors": 5
      },
      "connectionPool": {
        "http": {
          "maxConnections": 1024,
          "maxPendingRequests": 1024
        }
      }
    }],
    "serviceDiscovery": {
      "awsCloudMap": {
        "namespaceName": "prod.local",
        "serviceName": "orders"
      }
    }
  }
}
MESH

# ============================================================
# SECTION 7: Graceful Degradation Patterns
# ============================================================
# WHAT: When non-critical services fail, serve a degraded but
#       functional response rather than returning an error.
#       Never fail completely when partial functionality is possible.
#
# PATTERNS:
#
#   Cached Fallback:
#     ElastiCache stores the last good response.
#     If origin is down, serve stale cache with "cached" header.
#     TTL should match your data freshness requirements.
#
#   Default Response:
#     Recommendation service down → show bestsellers list.
#     Price service down → show "price unavailable."
#     Search service down → show categories.
#
#   Feature Flags:
#     Toggle features off during incidents without deploying.
#     AWS AppConfig for feature flags with validation and rollback.
#     LaunchDarkly or Optimizely for more advanced targeting.
#
#   Shedding Load:
#     Under extreme load, reject low-priority requests.
#     Keep accepting high-priority (paying users, checkout).
#     Return 503 with Retry-After header for shed requests.
#
# IMPLEMENTATION: All logic in application code or API Gateway.
# Key: define priority tiers of functionality before an incident happens.
# ============================================================

# AWS AppConfig for feature flags
aws appconfig create-application --name "orders-app"

aws appconfig create-environment \
  --application-id "APP_ID" \
  --name "prod" \
  --monitors '[{
    "AlarmArn": "arn:aws:cloudwatch:us-east-1:'"$ACCOUNT_ID"':alarm:HighErrorRate",
    "AlarmRoleArn": "arn:aws:iam::'"$ACCOUNT_ID"':role/AppConfigRole"
  }]'

# Feature flag configuration
aws appconfig create-configuration-profile \
  --application-id "APP_ID" \
  --name "feature-flags" \
  --location-uri "hosted" \
  --type "AWS.AppConfig.FeatureFlags"

# ============================================================
# SECTION 8: Cost Estimation for 1M Users/Day
# ============================================================
# CONTEXT: Architecture sizing estimate for a production system
#          serving 1 million users per day, 10 req/user average.
#
# TRAFFIC MATH:
#   1M users × 10 req/user = 10M requests/day
#   10M / 86,400 seconds = ~116 req/s average
#   Peak (3× average during business hours) = ~350 req/s
#   Burst (viral event, 10×) = ~1,160 req/s
#
# CAPACITY SIZING:
#   Each m6i.large EC2 handles ~100-200 req/s (app-dependent).
#   For 350 req/s peak: 3-4 instances minimum.
#   With HA (min 1 per AZ × 3 AZs): 3 minimum.
#   Target 60% utilization → need 6 instances at peak.
#   ASG: min=3, desired=6, max=24 (handles 10× spike).
#
# MONTHLY COST ESTIMATE (us-east-1, 2024 pricing, ~730 hr/month):
#   EC2 (avg 6× m6i.large @ $0.096/hr):  $420/month
#   ALB ($0.008/hr + LCU):                $16/month
#   RDS Multi-AZ (db.r6g.large):          $260/month
#   ElastiCache (cache.r6g.large):        $150/month
#   NAT Gateways (3× @ $0.045/hr):       $100/month
#   Data transfer out (100GB/day):        $270/month
#   Route 53 (hosted zone + queries):      $10/month
#   CloudFront (cache hit 80%, 1TB/mo):   $85/month
#   WAF (1× WebACL + rules + requests):   $30/month
#   CloudWatch logs/metrics:               $20/month
#   ─────────────────────────────────────────────────
#   ESTIMATED TOTAL:                    ~$1,361/month
#   Per user:                        $0.00136/user/month
#   (Most cost reduction from: reserved instances, Savings Plans,
#    caching hit ratio improvements, Graviton2 instances.)
#
# RESERVED INSTANCES / SAVINGS PLANS:
#   1-year Compute Savings Plan: ~40% discount on EC2 and Lambda.
#   3-year Reserved DB Instance: ~60% discount on RDS.
#   Same 1M users/day with 1-yr commitments: ~$900/month.
# ============================================================

echo "# Architecture cost estimates logged above in comments"
echo "# Review and adjust based on actual traffic patterns"

# ============================================================
# SECTION 9: Chaos Engineering
# ============================================================
# WHAT: Intentionally inject failures into a production system
#       to verify that it actually handles them as designed.
#       "If we don't test failure, we're assuming it won't happen."
#
# NETFLIX CHAOS MONKEY PRINCIPLES:
#   1. Define "steady state" — what does normal look like? (metrics)
#   2. Hypothesize the system maintains steady state during failures.
#   3. Inject failures: kill instances, block AZ, introduce latency.
#   4. Observe: does the system recover? How long? What metrics spike?
#   5. Run in production, not just staging (staging ≠ prod at scale).
#
# AWS FAULT INJECTION SIMULATOR (FIS):
#   - Managed chaos engineering service.
#   - Actions: terminate EC2, throttle API calls, inject CPU stress,
#     kill ECS tasks, disrupt network connectivity, fail over RDS,
#     inject latency into pod-to-pod communication (EKS).
#   - Stop conditions: if CloudWatch alarm fires, FIS stops the experiment.
#   - Integrated with SSM, CloudWatch, X-Ray.
#
# RUNBOOK FOR AZ FAILURE (document this before the incident):
#   1. CloudWatch detects increased errors in AZ-A.
#   2. ALB health checks fail → ALB stops routing to AZ-A targets.
#   3. ASG detects unhealthy instances → launches replacements in AZ-B, AZ-C.
#   4. RDS Multi-AZ detects primary failure → promotes standby (~60-120s).
#   5. ElastiCache cluster → promotes replica in AZ-B or AZ-C.
#   6. Route 53 health checks update → no change needed (ALB handles routing).
#   7. PagerDuty alert to on-call. Verify all above happened automatically.
#   8. Capacity: ASG may be over-capacity in 2 AZs. Monitor costs.
#   9. AZ-A recovery → ASG rebalances, database shard returns to AZ-A.
# ============================================================

# FIS experiment template — terminate 1/3 of EC2 instances in AZ-A
cat > /tmp/fis-experiment.json << 'FIS'
{
  "description": "Simulate AZ failure — terminate all instances in us-east-1a",
  "targets": {
    "az-a-instances": {
      "resourceType": "aws:ec2:instance",
      "resourceTags": {"Environment": "prod"},
      "filters": [{
        "path": "Placement.AvailabilityZone",
        "values": ["us-east-1a"]
      }],
      "selectionMode": "PERCENT(33)"
    }
  },
  "actions": {
    "terminate-az-a-instances": {
      "actionId": "aws:ec2:terminate-instances",
      "targets": {"Instances": "az-a-instances"}
    }
  },
  "stopConditions": [{
    "source": "aws:cloudwatch:alarm",
    "value": "arn:aws:cloudwatch:us-east-1:ACCOUNT:alarm:ErrorRateHigh"
  }],
  "roleArn": "arn:aws:iam::ACCOUNT:role/FISExperimentRole"
}
FIS

aws fis create-experiment-template \
  --cli-input-json file:///tmp/fis-experiment.json \
  --tags '{"Name":"AZ-A-Failure-Simulation","Environment":"prod"}'

# ============================================================
# SECTION 10: Infrastructure as Code
# ============================================================
# WHAT: Define ALL infrastructure in version-controlled code.
#       No clicking in the console for production changes. Ever.
#
# OPTIONS:
#
#   Terraform (HashiCorp):
#     - Multi-cloud (AWS, GCP, Azure, Kubernetes, many providers).
#     - HCL (HashiCorp Configuration Language) — readable, not code.
#     - State file tracks what exists. Remote state in S3 + DynamoDB lock.
#     - Plan (dry run) before apply. Modules for reuse.
#     - Use for: multi-cloud or teams already on Terraform.
#
#   CloudFormation:
#     - AWS-native. YAML or JSON. Tight integration with AWS services.
#     - Stack: a unit of resources managed together.
#     - Change sets: preview changes before deploying.
#     - No separate state file (AWS tracks state internally).
#     - Use for: AWS-only organizations, tight AWS service integration.
#
#   CDK (Cloud Development Kit):
#     - Write Python/TypeScript/Java/Go and CDK generates CloudFormation.
#     - Higher-level abstractions (constructs) that encode best practices.
#     - L1 = raw CloudFormation, L2 = sensible defaults, L3 = patterns.
#     - Use for: teams who prefer programming languages over config files.
#
# ALWAYS:
#   - IaC in version control (git).
#   - Code review for every infrastructure change.
#   - Separate environments (dev/staging/prod) as separate stacks.
#   - Never modify production manually — drift detection will find it.
# ============================================================

# Example: Deploy the entire 3-tier architecture with CDK
# (conceptual — actual CDK is Python/TypeScript code, not shell)
# cdk bootstrap aws://ACCOUNT_ID/us-east-1
# cdk deploy ProdVpcStack ProdDatabaseStack ProdAppStack --require-approval never

# Terraform equivalent:
# terraform init
# terraform plan -var-file=prod.tfvars -out=prod.plan
# terraform apply prod.plan

echo "High availability architecture configured."
echo "Primary region:   $PRIMARY_REGION"
echo "Secondary region: $SECONDARY_REGION"
echo "Global Accelerator: $ACCELERATOR_ARN"
echo ""
echo "Key SLAs targeted:"
echo "  Availability:  99.99% (52 min downtime/year)"
echo "  RTO:           <5 minutes (automated failover)"
echo "  RPO:           <60 seconds (DynamoDB Global Tables)"
echo "  Latency p99:   <200ms (CloudFront + Global Accelerator)"
