# Cloud Platforms — Principal Engineer Deep Dive

Companion to L01-L08. Each section maps to a lesson topic and pushes past
what a lesson has room for: niche tooling, real production tradeoffs,
worked examples, and interview-grade explanations.


## L01 — Concepts: Regions, AZs, Shared Responsibility

**Beyond the lesson**: "Shared responsibility" isn't one line, it's a
sliding scale by service model. For EC2/IaaS, you own the OS, patching,
and network ACLs; AWS owns the hypervisor and physical security. For
RDS/PaaS, AWS also owns OS patching and backups; you own schema, queries,
and IAM. For a fully managed service like DynamoDB, you own only data and
access policy. Auditors (SOC2/PCI) ask exactly which model applies per
service — getting it wrong is a real compliance finding, not a technicality.

**Worked example**: A team assumes AWS "handles security" for their
self-managed EC2-hosted Postgres and skips patching for 8 months. The 2019
CVE that let attackers pivot from a web app to root wasn't AWS's
responsibility to patch — it was the guest OS, squarely on the customer side
of the line. Compare that to the same team using RDS Postgres: AWS handles
that exact OS-level patch automatically, and the customer's actual
responsibility shrinks to schema/query/IAM — the SAME database engine, a
completely different risk surface depending on which service model wraps it.

**Tradeoff table**:
| Model | You own | Provider owns |
|---|---|---|
| IaaS (EC2) | OS, patching, app, data, network config | Hypervisor, physical, host network |
| PaaS (RDS) | Schema, queries, IAM, data | OS, patching, backups, HA failover |
| Managed/Serverless (DynamoDB, Lambda) | Data, access policy, code | Everything else |

**Interview Q&A**:
- *Q: Your RDS instance was breached via a SQL injection. Whose fault, AWS's or yours?* A: Yours — SQLi is an application-layer flaw; shared responsibility puts app code, queries, and IAM squarely on the customer regardless of service model.
- *Q: Why do multi-AZ deployments matter more than multi-region for most workloads?* A: AZs are physically separate datacenters within a region with independent power/cooling but low-latency links between them — multi-AZ buys real fault tolerance for a fraction of multi-region's latency/consistency complexity; multi-region is reserved for disaster recovery or genuine global-latency requirements.


## L02 — Compute: EC2, ASGs, Spot, EKS, Lambda

**Beyond the lesson**: Spot instance interruption isn't random — AWS
reclaims spot capacity when on-demand demand rises for that instance type/AZ,
and gives a 2-minute warning via the instance metadata endpoint before
termination. Production spot usage means POLLING that warning
(`http://169.254.169.254/latest/meta-data/spot/instance-action`) and draining
gracefully, not just hoping the workload is stateless.

**Worked example**: A batch-processing fleet on spot instances that doesn't
poll the interruption warning loses in-flight work every reclaim, quietly
inflating job-retry costs until someone notices the pattern in CloudWatch.
The fix: a sidecar process polling the metadata endpoint every 5 seconds,
checkpointing work to S3, and deregistering from the load balancer the
moment a warning appears — turning an abrupt kill into a graceful drain.

**Pitfalls**: Mixing instance types in one Auto Scaling Group without
weighted capacity can cause uneven load distribution if the types have very
different vCPU/memory ratios — ASGs balance by INSTANCE COUNT by default,
not by actual capacity, unless you configure attribute-based instance
selection.

**Tradeoff table**:
| Compute option | Best for | Weak point |
|---|---|---|
| EC2 on-demand | Predictable, stateful, long-running | Most expensive per hour |
| Spot | Stateless, interruptible, batch/CI | Can be reclaimed anytime |
| EKS (managed K8s nodes) | Container workloads needing K8s ecosystem | Control-plane cost + K8s operational overhead |
| Lambda | Event-driven, short bursts, unpredictable traffic | 15-min max duration, cold starts, vendor lock-in |

**Interview Q&A**:
- *Q: When would you choose Fargate over self-managed EKS worker nodes?* A: When you want to eliminate node-level patching/capacity planning entirely and your workload's per-pod resource needs are predictable — you pay a premium per vCPU/memory-hour but remove an entire operational surface (AMI updates, node draining, cluster autoscaler tuning).


## L03 — Storage: S3, EBS, EFS

**Beyond the lesson**: S3 storage class transitions aren't just "cheaper
storage" — Glacier retrieval has THREE speed tiers (Expedited ~1-5 min,
Standard ~3-5 hours, Bulk ~5-12 hours) each with different cost, and a
lifecycle policy that transitions objects too aggressively can create a
nasty surprise when an "archived" object is needed urgently and retrieval
takes half a day.

**Worked example**: A compliance-retention bucket set to transition to
Glacier Deep Archive at 30 days looked like a clean cost win — until an
active legal hold required retrieving specific objects within 24 hours, and
Deep Archive's standard retrieval tier takes up to 48 hours. The lesson:
lifecycle policies need to be designed against actual retrieval SLAs, not
just cost-per-GB.

**Pitfalls**: EBS volumes are AZ-locked — a snapshot can be copied to
another AZ/region, but the live volume cannot simply "move." Forgetting
this during an AZ failure means restoring from snapshot, not failing over
instantly (this is precisely why stateful workloads needing true HA use
EFS/managed databases with cross-AZ replication instead of raw EBS).

**Interview Q&A**:
- *Q: EFS vs EBS vs S3 — pick one for a shared config directory read by 50 containers simultaneously.* A: EFS — it's the only one of the three supporting ReadWriteMany concurrent mounts across multiple hosts/AZs natively; EBS is single-attach (mostly) and S3 isn't a POSIX filesystem at all.


## L04 — Databases: RDS/Aurora, ElastiCache, DynamoDB, Redshift

**Beyond the lesson**: Aurora's real differentiator over vanilla RDS
Postgres/MySQL isn't just "AWS-managed" — its storage layer is a distributed,
log-structured system replicated across 3 AZs at the STORAGE level (6 copies),
so a failover promotes a replica in seconds without waiting for the replica
to catch up on WAL replay the way standard RDS replication does.

**Worked example**: DynamoDB's single-table design pattern — instead of
normalized tables, one table stores multiple entity types distinguished by
a composite sort key (`USER#123`, `ORDER#456#ITEM#789`), because DynamoDB
has no server-side JOIN — the access pattern must be baked into the key
design UP FRONT, the opposite of relational modeling where queries adapt
to a normalized schema after the fact.

**Tradeoff table**:
| Database | Consistency model | Best fit |
|---|---|---|
| Aurora | Strong (single writer, read replicas eventually consistent unless using reader endpoint carefully) | Relational workloads needing SQL + HA |
| DynamoDB | Tunable (eventually consistent reads by default, strongly consistent optional) | Massive scale, known access patterns, low-latency KV/wide-column |
| ElastiCache (Redis) | Depends on config (single-node strong, cluster mode has replication lag) | Caching, session store, rate limiting |
| Redshift | Strong within a query, eventually consistent for concurrent writes at scale | OLAP/analytics, not transactional workloads |

**Interview Q&A**:
- *Q: Why does RDS Proxy exist if RDS already handles connections?* A: Lambda's execution model spins up many short-lived concurrent invocations, each opening its own DB connection — this can exhaust a database's max-connections limit in seconds under load; RDS Proxy pools and multiplexes connections so the DATABASE sees a stable, small connection count regardless of Lambda concurrency.


## L05 — Networking: VPC, Subnets, NAT, VPN, CloudFront

**Beyond the lesson**: A NAT Gateway is a per-AZ, metered, managed resource
billed per-GB processed — at real scale (multi-TB egress through NAT for,
say, container image pulls), NAT Gateway costs can rival or exceed the
compute it's supporting. VPC Endpoints (Gateway endpoints for S3/DynamoDB,
free; Interface endpoints for other services, hourly + per-GB but usually
still cheaper than NAT for high-volume traffic) route that traffic privately
without ever touching a NAT Gateway or the public internet.

**Worked example**: A team's monthly AWS bill had a mysterious few-thousand-
dollar NAT Gateway line item traced to every container instance pulling
images from ECR through a NAT Gateway instead of a private VPC endpoint —
adding an ECR interface endpoint eliminated that entire cost line, plus
reduced pull latency since traffic no longer left the VPC at all.

**Pitfalls**: A "private" subnet with a route to a NAT Gateway is NOT the
same isolation level as one with NO internet route at all — "private" in
AWS terminology means "no direct inbound from the internet," not "cannot
reach out." A genuinely internet-isolated subnet needs VPC endpoints for
every AWS service it needs to reach, and no NAT route at all.

**Interview Q&A**:
- *Q: Design connectivity between an on-prem datacenter and a VPC for a workload needing consistent sub-10ms latency, no internet dependency.* A: Direct Connect (dedicated physical link, predictable latency/bandwidth, no internet path) over a Site-to-Site VPN (which tunnels over the public internet and inherits its latency variance) — VPN as a backup path for DX, not the primary for latency-sensitive traffic.


## L06 — IAM & Security: Roles, OIDC, SCPs, GuardDuty, KMS

**Beyond the lesson**: The IAM policy evaluation order that trips people up:
an explicit DENY always wins over any ALLOW, no matter how many policies
grant access, and by default everything is implicitly denied unless an
ALLOW exists somewhere in the union of identity-based + resource-based +
SCP + permission boundary policies. Debugging "why can't this role do X"
means checking all four layers, not just the role's attached policy.

**Worked example**: A Lambda function using OIDC federation to assume an AWS
role instead of a static access key — the CI pipeline presents a short-lived
JWT identity token from its own provider (GitHub Actions, GitLab), AWS's
STS validates it against a configured trust policy, and issues temporary
credentials scoped to exactly what that role can do — no long-lived secret
ever exists to leak, rotate, or accidentally commit to a repo (see CICD
Notes section 1 for the GitHub Actions side of this exact pattern).

**Tradeoff table**:
| Security control | Scope | Enforced by |
|---|---|---|
| IAM policy | Per-identity or per-resource | IAM itself |
| SCP (Service Control Policy) | Entire AWS Organization/OU | Organizations — cannot be overridden by any account-level IAM policy |
| Permission boundary | Caps what an identity's OWN policies can grant, even if broader | IAM, per-role/user |
| KMS key policy | Who can use/manage a specific encryption key | KMS |

**Interview Q&A**:
- *Q: A developer has AdministratorAccess in IAM but still can't launch instances in a specific region. Why?* A: An SCP at the Organization level almost certainly denies that region — SCPs set a hard ceiling no identity-level policy, however permissive, can exceed.


## L07 — Serverless: Lambda, API Gateway, EventBridge, SQS/SNS, Step Functions

**Beyond the lesson**: Lambda cold starts aren't uniform — a Python/Node
function with a small deployment package might cold-start in under 200ms,
while a JVM-based function with a large dependency tree can take multiple
seconds, directly shaping architecture decisions (provisioned concurrency
for latency-sensitive JVM Lambdas is common precisely because of this gap).

**Worked example**: SQS vs SNS vs EventBridge, concretely: SQS is a queue
(one consumer processes each message, ideal for work distribution/decoupling
a producer from a slower consumer); SNS is pub/sub fan-out (every subscriber
gets every message, no queuing/retry built in by itself — usually paired
WITH SQS per-subscriber for durability); EventBridge adds content-based
routing rules on top of pub/sub (route this event to Lambda A if
`detail.type == "order.created"`, to Lambda B if `"order.cancelled"`) —
the "if/else router" layer the other two lack natively.

**Interview Q&A**:
- *Q: A Step Functions state machine's Lambda step needs to retry on throttling but not on validation errors. How?* A: Per-error-type Retry/Catch blocks — Step Functions lets each state define which specific error names get retried (with backoff) versus immediately routed to a Catch/fallback state, rather than one blanket retry policy for all failures.


## L08 — High Availability: Multi-AZ, Multi-Region, Route 53, Chaos Engineering

**Beyond the lesson**: Route 53 failover routing needs REAL health checks
against the actual application (not just "is the instance up") — a health
check hitting `/health` that only checks the web server process, not its
database connection, will happily route traffic to a backend that's up but
can't actually serve requests, defeating the entire point of the failover config.

**Worked example**: A genuine multi-region active-passive DR architecture:
Aurora Global Database replicates asynchronously to a secondary region
(typically <1s lag), Route 53 health-checks the primary region's endpoint,
and on failure, a failover routing policy shifts DNS to the secondary
region's endpoint — recovery time is bounded by DNS TTL propagation (set
low, e.g. 60s, specifically for this) plus the manual/automated promotion
of the secondary Aurora cluster to a standalone writer.

**Interview Q&A**:
- *Q: Why is "multi-region active-active" so much harder than "multi-AZ" for a stateful service?* A: AZs within a region share a fast, low-latency backbone, so synchronous replication is cheap enough for strong consistency; cross-region links have real speed-of-light latency (tens to hundreds of ms), forcing a choice between synchronous replication (slow writes) or eventual consistency (conflict resolution complexity) — there is no free equivalent of AZ-level synchronous replication at region scale.


## COMPREHENSIVE TOOL & SERVICE REFERENCE — COMMON TO UNCOMMON

Everything above mapped to lessons; this section is broader company-usage
coverage, AWS-first with Azure/GCP equivalents named throughout since almost
every job posting expects at least passing multi-cloud fluency.

### Compute, beyond EC2/Lambda
- **ECS** (AWS's own container orchestrator, simpler than EKS, no K8s
  knowledge needed) vs **Fargate** (serverless compute for ECS/EKS, no node
  management at all) — a huge fraction of companies run ECS+Fargate
  specifically to avoid EKS's Kubernetes operational overhead entirely.
- **Cloud Run** (GCP) / **Azure Container Apps** — the GCP/Azure equivalents
  of "serverless containers," scale-to-zero, pay-per-request.
- **Batch computing**: AWS Batch, Azure Batch — managed job scheduling over
  a pool of compute for large parallel workloads (genomics, rendering,
  financial simulation) without hand-building a scheduler.
- **App Engine** (GCP) / **Elastic Beanstalk** (AWS) / **App Service**
  (Azure) — PaaS "just deploy code" platforms, less common at scale but
  still common for internal tools and smaller companies wanting minimal ops.

### Storage & data transfer beyond S3/EBS/EFS
- **Azure Blob Storage** / **GCS** — the direct S3 equivalents; access
  tiers work almost identically (Hot/Cool/Archive vs Standard/IA/Glacier).
- **AWS Snowball/Snowcone** / **Azure Data Box** — physical appliances for
  migrating petabytes of data where network transfer would take too long
  or cost too much — genuinely still used for large on-prem-to-cloud migrations.
- **AWS DataSync** / **Azure File Sync** — managed, scheduled data transfer
  and sync between on-prem and cloud storage, used heavily in migration projects.
- **FSx** (AWS) — managed Windows File Server, Lustre (HPC), NetApp ONTAP —
  used when a workload needs a SPECIFIC filesystem protocol EFS doesn't cover.

### Networking, beyond VPC/NAT/CloudFront
- **Transit Gateway** (AWS) / **Virtual WAN** (Azure) — hub-and-spoke
  routing across MANY VPCs/VNets without a full mesh of manual peering
  connections — the standard answer once an org has more than ~5 VPCs to interconnect.
- **PrivateLink** (AWS) / **Private Endpoint** (Azure) — expose a service
  privately to other VPCs/accounts without traversing the public internet
  OR needing full VPC peering — the mechanism behind most SaaS vendors'
  "connect privately to our service" offering.
- **WAF** (Web Application Firewall) — AWS WAF, Azure Front Door WAF,
  Cloudflare — rule-based filtering (SQLi/XSS signatures, rate limiting,
  geo-blocking) sitting in front of a public-facing app, distinct from a
  security group (which is IP/port level, not payload-aware).
- **Global Accelerator** (AWS) — routes traffic over AWS's private backbone
  to the nearest healthy endpoint, used for latency-sensitive global apps
  that need more than DNS-based routing alone provides.

### Cloud-native security & governance tooling
- **AWS Security Hub** / **Azure Defender for Cloud** / **GCP Security
  Command Center** — centralized aggregation of findings from GuardDuty,
  Inspector, config compliance checks, etc. into one pane of glass.
- **AWS Config** / **Azure Policy** — continuous compliance-as-code:
  define a rule ("all S3 buckets must have encryption enabled") and get
  flagged (or auto-remediated) the moment a resource drifts from it.
- **Secrets Manager** (AWS) / **Key Vault** (Azure) / **Secret Manager**
  (GCP) — managed secret storage with automatic rotation support, the
  cloud-native alternative to self-hosting Vault when you don't need Vault's
  dynamic-secrets/multi-cloud flexibility.
- **AWS Organizations SCPs / Azure Management Groups + Policy** — the
  org-wide guardrail layer (see L06) — every large company's account/
  subscription structure is built around these from day one, not bolted on later.

### Hybrid & multi-cloud
- **AWS Outposts** / **Azure Arc** / **Google Anthos** — extend the cloud
  provider's control plane and APIs INTO your own datacenter hardware —
  used by regulated industries (banking, government) needing cloud tooling
  but data residency/latency requirements that rule out pure public cloud.
- **VMware Cloud on AWS** — still genuinely common in large enterprises
  mid-migration, running existing VMware workloads on AWS hardware without
  a full re-architecture.

### Managed data/streaming services
- **MSK** (AWS Managed Kafka) / **Event Hubs** (Azure) / **Pub/Sub** (GCP) —
  managed alternatives to self-hosting Kafka (see Apache Kafka Notes) —
  MSK is Kafka-API-compatible; Event Hubs and Pub/Sub have their own APIs
  with Kafka-compatibility shims.
- **Kinesis** (AWS) — real-time streaming, positioned as AWS's "simpler
  than Kafka, fully managed" option, commonly chosen when a team doesn't
  need Kafka's full ecosystem (Kafka Streams, Connect) and wants zero ops.
- **Glue** (AWS) / **Data Factory** (Azure) — managed ETL orchestration,
  covered more deeply in Data Engineering Notes; worth knowing they're
  cloud-native alternatives to self-hosted Airflow.

### Cost management & FinOps tooling
- **Cost Explorer + Cost Anomaly Detection** (AWS), **Cost Management +
  Billing** (Azure) — native cost visibility; most companies past a certain
  size layer a THIRD-PARTY FinOps tool (CloudHealth, Cloudability, Vantage,
  or the open-source OpenCost for Kubernetes cost allocation) on top for
  cross-account/cross-cloud rollups the native tools don't do well.
- **Spot Instance advisors / Compute Optimizer** — AWS-native rightsizing
  recommendations; a genuinely underused free tool most cost-audits find
  immediate savings from on the first pass.

### Migration & modernization
- **AWS Migration Hub / Application Discovery Service** — inventories
  on-prem workloads and dependencies before a migration project starts —
  the "know what you actually have" step most failed migrations skipped.
- **Strangler fig pattern** (architecture, not AWS-specific) — the standard
  approach to migrating a monolith to cloud/microservices incrementally:
  route traffic for one function at a time to a new service behind a
  facade, until the old system has nothing left routing to it.


## NICHE BUT REAL

- **AWS Well-Architected Framework reviews** — a formal audit process
  (Operational Excellence, Security, Reliability, Performance, Cost, Sustainability
  pillars) that many enterprises require before a workload goes to production;
  knowing the six pillars by name is a real interview signal.
- **Savings Plans vs Reserved Instances** — Savings Plans commit to a $/hour
  spend across ANY instance family/region (more flexible); RIs commit to a
  SPECIFIC instance type/region (less flexible, sometimes marginally cheaper) —
  most modern FinOps guidance favors Savings Plans for exactly that flexibility.
- **AWS Control Tower / Landing Zone** — the standard way large orgs bootstrap
  a multi-account AWS Organization with baseline SCPs, logging, and account
  vending already wired up, instead of hand-rolling account structure.
- **Cross-account IAM role assumption** (`sts:AssumeRole` across account
  boundaries) — the mechanism behind almost every multi-account security
  tooling setup (a central security account's GuardDuty/Security Hub reading
  findings from dozens of workload accounts via assumed roles).
- **Graviton (ARM) instances** — often 20-40% better price/performance for
  compatible workloads; the real blocker is usually a dependency without an
  ARM build, not a fundamental compatibility issue.
- **VPC Flow Logs + Athena** — querying raw network flow logs with SQL for
  incident investigation ("what talked to this compromised IP, and when") —
  a genuinely common first step in a real cloud security incident response.
- **FinOps as a discipline** — cost allocation tags, anomaly detection
  (Cost Explorer/Cost Anomaly Detection), and showback/chargeback models are
  now a distinct job function at scale, not just "check the billing dashboard."
