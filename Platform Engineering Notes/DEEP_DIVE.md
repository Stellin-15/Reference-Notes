# Platform Engineering — Principal Engineer Deep Dive

Companion to the existing L01-L0n lessons. Adds niche tooling, tradeoffs,
worked examples, and interview-grade depth on top of the core lessons.


## Internal Developer Platforms (IDPs)

**Beyond the lesson**: The core measurable goal of an IDP isn't "self-service"
as an abstract good — it's reducing COGNITIVE LOAD per deploy. A platform
succeeds when a developer can ship a new service without personally
understanding Kubernetes networking, IAM, or Terraform modules — the
platform absorbs that complexity behind a golden path. A platform that just
adds a UI on top of the same raw complexity (still requires understanding
every underlying knob) has built a dashboard, not a platform.

**Worked example**: **Backstage** (Spotify's open-sourced IDP framework) as
the dominant reference implementation — a software catalog (every service,
who owns it, what it depends on) plus a template engine (scaffold a new
service from a golden-path template that already wires up CI, monitoring,
and on-call ownership correctly on day one) plus a plugin system for
surfacing other tools (CI status, cost, security scan results) in one place.

**Pitfalls**: Building a platform team before establishing WHICH golden
paths actually reduce toil (versus guessing) is the most common platform-
engineering failure — a platform nobody's forced to use, that doesn't
demonstrably save time over the status quo, gets bypassed, and the team
that built it becomes an unfunded mandate nobody respects.

**Interview Q&A**:
- *Q: How do you measure whether a platform investment is paying off?* A: Lead time for a new service to reach production (golden path vs the old manual way), % of services actually using the golden path vs bypassing it, and support-ticket volume to the platform team over time — a successful platform's support load should trend DOWN as self-service improves, not up.


## Platform-as-a-Product Mindset

**Beyond the lesson**: Treating the platform team's OTHER ENGINEERS as
customers (not just internal infrastructure) means the platform needs a
roadmap, a feedback loop, and something like a changelog — the same
product-management discipline external-facing products get, which most
infra teams historically skipped and paid for in adoption failure.

**Interview Q&A**:
- *Q: A platform team ships a new CI template nobody adopts. What went wrong, most likely?* A: No migration path/incentive for EXISTING services, and no clear win articulated for the team choosing to adopt it — "we built it" isn't the same as "we made switching worth the cost," and platform adoption almost always needs an active migration push, not a passive announcement.


## Golden Paths & Paved Roads

**Worked example**: A golden path for "new backend service" that
pre-wires: a service-catalog entry, a CI pipeline with the org's standard
test/scan/deploy stages, a default set of dashboards/alerts (RED metrics:
Rate, Errors, Duration) already configured before the first line of
business logic is written, and correct on-call routing from day one — the
entire point being that "boring, correctly-operated service" is the DEFAULT,
not something a team has to remember to bolt on later.

**Interview Q&A**:
- *Q: Should a golden path be mandatory or optional?* A: Optional but heavily incentivized — mandate breeds resentment and workaround culture; a golden path that's genuinely faster/easier than going it alone gets adopted voluntarily, and teams with a real, justified reason to deviate (unusual latency/compliance needs) should be able to, with the platform team aware of and supporting that exception.


## Platform Reliability & Multi-Tenancy

**Beyond the lesson**: A shared platform (e.g. one Kubernetes cluster
serving 40 teams) has a MULTI-TENANCY problem the platform team owns that
individual teams never had to think about: noisy-neighbor resource
contention, blast-radius containment (one team's bad deploy shouldn't be
able to exhaust cluster-wide resources), and namespace-level RBAC/network
policy so teams can't accidentally (or maliciously) reach each other's workloads.

**Interview Q&A**:
- *Q: One team's misconfigured job is starving the shared cluster's resources. How do you prevent recurrence structurally, not just fix this incident?* A: ResourceQuotas and LimitRanges per namespace enforced by the platform (not left to team discipline), PodDisruptionBudgets and priority classes so critical workloads are protected, and admission-control policies (OPA/Kyverno — see Kubernetes Notes section 19) requiring resource requests/limits on every deployed workload by default.


## COMPREHENSIVE TOOL & PRACTICE REFERENCE — COMMON TO UNCOMMON

### Service catalogs & software templates
- **Backstage** (Spotify, now CNCF) — the dominant open-source IDP
  framework; plugins ecosystem covers CI status, cost, security scanning,
  TechDocs (docs-as-code rendered inside the catalog).
- **Port / Cortex / OpsLevel** — commercial SaaS alternatives to
  self-hosting Backstage, trading customization for faster time-to-value
  and less platform-team maintenance burden.
- **Service scorecards** — a common pattern layered on top of any catalog:
  automatically score each service against org standards (has on-call
  defined? has a runbook? meets test-coverage threshold?) and surface gaps
  visibly — turns "best practices" from a wiki page into an enforced,
  visible metric per team.

### Infrastructure abstraction layers
- **Crossplane** — Kubernetes-native cloud resource provisioning (see
  Cloud Platforms cluster) — the platform-engineering use case specifically
  is exposing a SIMPLIFIED custom resource ("give me a database") that
  Crossplane translates into the full underlying cloud resource graph,
  hiding Terraform-level complexity from product teams entirely.
- **Terraform modules as a platform product** — versioned, tested,
  centrally-maintained modules (`module "vpc"`, `module "eks-cluster"`)
  that product teams consume rather than writing raw provider resources —
  the IaC-specific version of a golden path.
- **Humanitec / kratix** — platform orchestration tools specifically aimed
  at defining and enforcing golden paths across many services/environments declaratively.

### Environment management
- **Ephemeral/preview environments** (per-PR environments spun up
  automatically, e.g. via Vercel/Netlify for frontend, or custom K8s
  namespace-per-PR setups for backend) — lets reviewers click through a
  REAL running version of a change instead of reading a diff alone.
- **Environment-as-a-service platforms** (Qovery, Ambassador Labs' tools) —
  commercial products specifically automating the "spin up a full-stack
  preview environment per branch" pattern above.

### Developer experience (DX) measurement
- **DORA + SPACE frameworks** — DORA (deploy frequency, lead time, change
  failure rate, MTTR) measures delivery performance; SPACE (Satisfaction,
  Performance, Activity, Communication, Efficiency) is the broader,
  more holistic developer-productivity framework increasingly used
  alongside DORA because DORA alone can't capture things like developer
  satisfaction or focus-time fragmentation.
- **Local development parity tools** — Tilt, Skaffold, DevSpace — sync
  local code changes into a real Kubernetes dev environment automatically,
  solving the "works differently locally vs in the cluster" platform pain point.


## NICHE BUT REAL

- **Platform engineering vs DevOps vs SRE, precisely**: DevOps is a
  cultural philosophy (devs own their ops); SRE is a specific discipline
  applying software-engineering rigor to operations (error budgets, toil
  reduction); Platform Engineering is the organizational answer to "not
  every dev team should have to reinvent DevOps/SRE practices themselves" —
  a dedicated team builds the paved road so product teams inherit good
  practices by default rather than each rediscovering them.
- **Crossplane** — extends the Kubernetes API to provision and manage CLOUD
  infrastructure (an RDS instance, an S3 bucket) as native K8s custom
  resources, letting a platform team expose infrastructure provisioning
  through the same API/RBAC/GitOps model as application workloads.
- **Score** (score.dev) — an open specification for describing a
  workload's platform-agnostic requirements (what it needs: a database, an
  endpoint, env vars) separately from HOW any given platform provisions
  them — aimed at making workload definitions portable across different
  underlying platform implementations.
- **Platform team topology (Team Topologies framework)** — platform teams
  are explicitly modeled as one of four fundamental team types (alongside
  stream-aligned, enabling, and complicated-subsystem teams), with a defined
  interaction mode (X-as-a-Service) specifically to avoid becoming an
  unplanned bottleneck between product teams and infrastructure.
- **Developer experience (DX) metrics** — increasingly measured formally
  (DX surveys, time-to-first-commit for new hires, deploy frequency per
  team) rather than assumed; a platform team without DX metrics is flying blind.
