#!/usr/bin/env bash
# WHAT: Four realistic cloud-architecture problems, each solved with
#       THREE genuinely different, individually defensible approaches
#       drawn from L01-L08 -- with an explicit comparison table and
#       reasoning for why each answer is valid under different
#       constraints.
# WHY:  "Lambda or EC2/EKS," "single-region or multi-region," "which
#       database" are all questions L01-L08 gave you real tools for, not
#       one universal answer -- this lesson is about the decision
#       process under real cost, latency, and reliability constraints.
# LEVEL: Capstone -- read after L01-L08.
#
# This file is reference material -- not meant to be executed. Before
# checking each comparison table, try reconstructing it yourself using
# only L01-L08's concepts.

: <<'CASE_STUDY_1'
============================================================================
CASE STUDY 1 -- COMPUTE CHOICE FOR A NEW, UNPREDICTABLE-TRAFFIC API
SERVICE
============================================================================

SETUP: a new API service has genuinely unknown traffic patterns (a new
product, no historical data) -- could be near-zero for months or could
suddenly need to handle significant load.

----------------------------------------------------------------------
APPROACH A: AWS Lambda + API Gateway (L02, L07)
----------------------------------------------------------------------
  WHY VALID: per L07, Lambda's pay-per-invocation pricing means a
  near-zero-traffic period costs NEAR-ZERO dollars -- directly matches
  this case study's core uncertainty (will this even get meaningful
  traffic at all) without committing to any fixed infrastructure spend
  upfront, and scales automatically to sudden spikes with no manual
  capacity planning.
  COST: per L02/L07, Lambda has real constraints -- execution time
  limits, cold-start latency (especially for less frequently invoked
  functions, or larger deployment packages), and at SUSTAINED HIGH
  volume, per-invocation pricing can become more expensive than
  provisioned compute -- a real ceiling if the service does end up
  needing significant, steady traffic.

----------------------------------------------------------------------
APPROACH B: EC2 with an Auto Scaling Group (L02), starting small (e.g.
one t3.small instance, minimum)
----------------------------------------------------------------------
  WHY VALID: avoids Lambda's execution-time/cold-start constraints
  entirely, and ASG's scaling policy means the fixed BASELINE cost is
  low (one small instance) while still having a path to scale if
  traffic grows -- a defensible middle ground for a team more
  comfortable with traditional server-based architecture than a fully
  serverless one.
  COST: even the SMALLEST always-on instance costs something every
  single hour, 24/7, REGARDLESS of whether it receives any traffic at
  all -- for a genuinely near-zero-traffic period (a real possibility
  per this case study's stated uncertainty), this is real, ongoing
  spend Lambda's pay-per-invocation model would have avoided entirely.

----------------------------------------------------------------------
APPROACH C: EKS/containers (L02) from day one, sized generously for
anticipated future growth
----------------------------------------------------------------------
  WHY VALID: if the team is confident this service WILL eventually need
  significant, sustained scale and wants to avoid a later migration
  (e.g. from Lambda to containers) once that growth actually happens,
  building on container/Kubernetes infrastructure from the start avoids
  that future re-architecture cost.
  COST: given this case study's EXPLICIT stated uncertainty ("could be
  near-zero for months"), committing to EKS's real baseline
  operational complexity and cost (control plane, node group
  management, per Kubernetes Notes) for a service that might not need
  it for a long time (or ever) is very likely premature -- optimizing
  for a scale the team doesn't yet know it will reach, at real cost
  paid starting immediately.

COMPARISON TABLE (Case Study 1):
  | Approach | Cost at near-zero traffic | Cost at high sustained traffic | Migration cost if traffic grows significantly |
  |----------|--------------------------------|--------------------------------------|-------------------------------------------------------|
  | A: Lambda | Near-zero | Can become expensive | Real (eventual migration to B/C if sustained-high) |
  | B: EC2 + ASG, small baseline | Low but nonzero | Reasonable, scales | Lower (ASG already scales up) |
  | C: EKS from day one | Highest | Reasonable, scales | None (already built for scale) |
  Given the case study's explicit uncertainty, A is the strongest
  starting point -- it's specifically optimized for "we don't know if
  this will get traffic," and migrating off Lambda LATER, once real
  traffic data justifies it, is a known, well-trodden path, not a
  novel problem to solve preemptively.
CASE_STUDY_1

: <<'CASE_STUDY_2'
============================================================================
CASE STUDY 2 -- DATABASE CHOICE FOR A NEW FEATURE STORING USER
NOTIFICATION PREFERENCES
============================================================================

SETUP: a straightforward feature -- store per-user notification
preferences (a handful of boolean/enum fields), read far more often than
written, moderate scale (a few million users).

----------------------------------------------------------------------
APPROACH A: RDS/Aurora (relational, L04)
----------------------------------------------------------------------
  WHY VALID: per L04, if the rest of the application's data already
  lives in a relational database, adding this feature as a new table in
  the SAME database avoids introducing a new data store for a feature
  this simple -- one less system to operate, monitor, and back up,
  genuinely valuable when a relational model fits the data cleanly
  (it does here: simple, well-structured per-user fields).
  COST: if this table experiences very high READ volume (plausible,
  given "read far more often than written" and millions of users each
  potentially checking preferences on every notification-sending
  decision), it adds load to the SAME database instance serving the
  rest of the application's relational workload -- a real resource-
  contention risk if not carefully isolated (e.g. via a read replica),
  a cost specific to sharing infrastructure with unrelated workloads.
--
APPROACH B: DynamoDB (L04)
----------------------------------------------------------------------
  WHY VALID: per L04, DynamoDB's single-digit-millisecond latency at
  scale and pay-per-request (or provisioned) pricing suit a high-read,
  simple-key-lookup pattern ("get preferences for user X") extremely
  well, and it's fully decoupled from any relational database's
  resource contention concerns -- a genuinely strong fit for exactly
  this access pattern.
  COST: introduces a SEPARATE data store into the architecture purely
  for this one, relatively simple feature -- if the rest of the
  application doesn't already use DynamoDB, this adds a new technology
  to the team's operational surface (IAM permissions, monitoring,
  on-call familiarity) for a feature that, taken alone, doesn't
  strictly NEED DynamoDB's specific strengths at "a few million users"
  scale (well within what a well-indexed relational table can serve
  comfortably too).
--
APPROACH C: ElastiCache (Redis, L04) as a read-through cache in front
of whichever primary store (A or B) holds the actual data
----------------------------------------------------------------------
  WHY VALID: per L04, given the STATED "read far more often than
  written" pattern, caching is a direct, well-targeted fit -- most
  reads get served from an in-memory cache at very low latency, and the
  primary store (wherever it lives) only needs to handle actual writes
  plus cache misses, reducing load on whichever system A or B provides
  as the source of truth.
  COST: doesn't actually answer "where does the data PERSIST" at all
  -- this is an ADDITION on top of A or B, not a replacement for
  either, and introduces real cache-invalidation complexity (when a
  user updates their preferences, the cache entry must be correctly
  invalidated/updated, a well-known source of subtle bugs if not
  handled carefully) for a feature whose read pattern (checking
  notification preferences) may not actually be latency-critical
  enough to justify this added complexity.

COMPARISON TABLE (Case Study 2):
  | Approach | Operational simplicity (if already using the tech) | Fit for the stated access pattern | Added complexity |
  |----------|-----------------------------------------------------------|------------------------------------------|------------------------|
  | A: RDS/Aurora (existing relational DB) | Highest, if already relational | Good | Lowest |
  | B: DynamoDB | Lowest, if not already used elsewhere | Best (purpose-fit) | Medium (new system) |
  | C: cache in front of A or B | N/A (an addition, not alternative) | Best for read latency specifically | Real (invalidation logic) |
  For a feature this simple, at this scale, A (reusing existing
  relational infrastructure) is usually the right default UNLESS the
  application already predominantly uses DynamoDB elsewhere (in which
  case B is the more consistent choice); C is worth adding specifically
  once read latency/load is MEASURED to actually be a problem, not
  preemptively for a feature this modest in scale.
CASE_STUDY_2

: <<'CASE_STUDY_3'
============================================================================
CASE STUDY 3 -- MULTI-REGION STRATEGY FOR DISASTER RECOVERY
============================================================================

SETUP: a company wants to improve its disaster-recovery posture beyond
"single region, hope AWS doesn't have a regional outage" -- deciding how
far to take multi-region investment (L08).

----------------------------------------------------------------------
APPROACH A: Backup-and-restore -- regular backups stored in a SECOND
region, restored manually/via automation only if the primary region
actually fails (L08)
----------------------------------------------------------------------
  WHY VALID: per L08, the lowest-cost, simplest form of multi-region
  DR -- no ongoing infrastructure running in the second region at all
  between backups, appropriate for workloads that can tolerate real
  DOWNTIME (hours, not seconds) during a genuine regional failure,
  which is a legitimate business tradeoff for many non-critical systems.
  COST: recovery time (RTO) is real and substantial -- restoring from
  backup and standing up infrastructure in the second region from
  scratch takes meaningful time, during which the service is fully
  down; only appropriate if the business has explicitly accepted that
  RTO, not assumed it away.

----------------------------------------------------------------------
APPROACH B: Pilot light -- minimal, always-on core infrastructure in
the second region (e.g. a database replica kept in sync), scaled up
quickly only during an actual failover (L08)
----------------------------------------------------------------------
  WHY VALID: per L08, this meaningfully reduces RTO relative to A (the
  core data is already replicated and ready; only compute needs to
  scale up during an actual event) while keeping ONGOING cost much
  lower than a fully active second region, a real middle-ground
  tradeoff between A's cheap-but-slow and C's fast-but-expensive
  extremes.
  COST: still requires a real failover PROCESS (scaling up compute,
  redirecting traffic, L08's Route 53 failover discussion) that takes
  some nonzero time and must be tested/rehearsed to actually work when
  needed -- an untested pilot-light setup that's never been drilled is
  a common, real failure mode (discovering the failover process doesn't
  actually work correctly only during a genuine crisis).

----------------------------------------------------------------------
APPROACH C: Active-active -- both regions fully running, serving live
traffic simultaneously, with automatic failover (L08)
----------------------------------------------------------------------
  WHY VALID: per L08, this provides the STRONGEST DR posture -- near-
  zero RTO (the second region is ALREADY serving live traffic, so a
  regional failure just means routing shifts away from the failed
  region, not standing anything up from scratch) and, as a side
  benefit, can improve normal-operation latency for geographically
  distributed users.
  COST: per L08, active-active is the MOST expensive and architecturally
  complex option by a wide margin -- running full production capacity
  in BOTH regions continuously, plus solving genuinely hard cross-region
  data-consistency problems (Distributed Systems Theory Notes) for any
  workload that needs strongly consistent writes across both regions --
  a large, ongoing investment that needs to be justified by genuinely
  severe downtime-cost/compliance requirements, not adopted by default.

COMPARISON TABLE (Case Study 3):
  | Approach | RTO | Ongoing cost | Architectural complexity |
  |----------|---------|------------------|--------------------------------|
  | A: backup-and-restore | Hours+ | Lowest | Lowest |
  | B: pilot light | Minutes | Medium | Medium |
  | C: active-active | Seconds/near-zero | Highest | Highest |
  The correct choice is DIRECTLY a function of what RTO the business
  has actually decided it needs (and can justify the cost of) -- this
  is fundamentally a business-risk-tolerance decision the engineering
  team should get an explicit, informed answer to, not default to the
  "safest-sounding" option (C) without confirming the cost is actually
  warranted by real requirements.
CASE_STUDY_3

: <<'CASE_STUDY_4'
============================================================================
CASE STUDY 4 -- IAM PERMISSION STRATEGY FOR A GROWING ENGINEERING TEAM
============================================================================

SETUP: a company growing from 10 to 50 engineers currently gives every
engineer broad, similar IAM permissions (set up when the team was small
and trust was high) -- deciding how to evolve this as the team grows
(L06).

----------------------------------------------------------------------
APPROACH A: Keep broad permissions for everyone -- it's worked so far,
and tightening it is disruptive
----------------------------------------------------------------------
  WHY VALID: zero migration effort, and for a team that still has a
  strong trust culture and hasn't experienced a real incident from
  over-broad permissions, "if it isn't broken, don't fix it" has some
  real, if limited, merit -- avoiding unnecessary process overhead for
  its own sake is a legitimate value.
  COST: per L06's least-privilege discussion, broad permissions at 50
  people is a MEANINGFULLY larger blast radius than at 10 -- a single
  compromised engineer credential (phishing, a leaked API key) now
  grants an attacker access proportional to "everything a broad IAM
  policy allows," not just what that person's ACTUAL job requires; the
  risk scales with headcount even if nothing else about the
  organization has changed.
--
APPROACH B: Role-based access control -- define IAM roles matching
actual job functions (e.g. "backend engineer," "data engineer," "on-
call responder"), assign engineers to roles rather than granting
individual broad permissions (L06)
----------------------------------------------------------------------
  WHY VALID: per L06, this directly implements least-privilege at an
  organizationally SCALABLE level -- permissions are defined once per
  ROLE (not per individual), and onboarding/offboarding/role changes
  become a matter of role reassignment rather than auditing and
  rewriting individual policies each time, a real, durable fix for a
  GROWING team specifically.
  COST: requires real upfront work to actually DEFINE the roles
  correctly (what does a "backend engineer" genuinely need access to,
  and does that differ from what they've been ASSUMING they need
  because they've always had broader access) -- a genuine, sometimes
  contentious organizational exercise, and overly-narrow roles can
  create real friction/slowdowns if an engineer legitimately needs
  occasional access outside their defined role.
--
APPROACH C: Just-in-time (JIT) elevated access -- baseline permissions
stay minimal for everyone, engineers REQUEST and receive temporary,
time-boxed elevated access for specific tasks (e.g. via an approval
workflow), rather than holding broad standing permissions at all
----------------------------------------------------------------------
  WHY VALID: represents the STRONGEST least-privilege posture of the
  three -- no one holds broad standing access even within a role,
  meaning a compromised credential's blast radius is bounded to
  whatever narrow baseline access exists at that moment, and every
  elevated-access grant is time-boxed and (if the approval workflow
  logs it) auditable.
  COST: real, ongoing FRICTION for legitimate work -- every task
  needing elevated access requires a request/approval round-trip,
  which can meaningfully slow down urgent work (e.g. an on-call
  engineer needing production access DURING an active incident,
  precisely when speed matters most) unless the JIT system itself has
  a fast-tracked emergency-access path specifically designed for that
  case -- a real, additional piece of process design this approach
  requires to not become counterproductive during incidents.

COMPARISON TABLE (Case Study 4):
  | Approach | Blast radius if compromised | Onboarding/scaling friction | Day-to-day work friction |
  |----------|-----------------------------------|------------------------------------|--------------------------------|
  | A: keep broad permissions | Largest, growing with headcount | None | None |
  | B: role-based access control | Reduced, per-role | Low, once roles are defined | Low-medium |
  | C: just-in-time elevated access | Smallest | Medium (approval workflow to build) | Highest, unless incident-path is fast-tracked |
  B is the standard, proportionate answer for a team at THIS growth
  stage (10 to 50); C is the right escalation specifically for
  organizations with genuinely elevated compliance/security
  requirements where B's role-level granularity still isn't tight
  enough, and is rarely justified purely by headcount growth alone
  without an accompanying compliance driver.
CASE_STUDY_4

echo "This file is reference material -- see the WHAT/WHY header and the"
echo "four case studies in the heredoc blocks above (not meant to be run)."
