# ============================================================
# L08: Platform Engineering Maturity Model & Team Topology
# ============================================================
# WHAT: A framework for assessing how self-service vs manual a platform is,
#       and how to structure the team that builds it.
# WHY (PRODUCTION): "We have Kubernetes" is not a maturity level. Without a
#       shared model, platform investment decisions become opinion-driven
#       instead of measured against where the gaps actually are.
# LEVEL: Senior platform engineer, engineering manager, staff+
# ============================================================

"""
CONCEPT OVERVIEW:
Platform maturity is usually assessed per-dimension (provisioning, secrets,
CI/CD, observability, cost, security) rather than as one org-wide score —
a company can be Level 4 on CI/CD and Level 1 on secrets management
simultaneously, and that gap is exactly what the platform roadmap should
target next.

Team Topologies (Skelton & Pais) provides the organizational model: a
platform team exists to reduce COGNITIVE LOAD on stream-aligned (product)
teams, exposing capabilities as a self-service "X-as-a-Service" — not as a
ticket queue.

PRODUCTION USE CASE:
A platform team runs a quarterly maturity self-assessment across 6
dimensions, scoring 1-4 each, and publishes the result alongside the
roadmap: "we're moving Secrets from Level 1 (static, manual rotation) to
Level 3 (Vault dynamic secrets, self-service) this quarter" — turning a vague
"platform work" backlog into a measurable, stakeholder-legible commitment.

COMMON MISTAKES:
- Building capability (Level 2: automated) without self-service (Level 3) —
  the platform team becomes the bottleneck executing automation on behalf
  of others via tickets, instead of automation empowering others directly.
- Treating the platform team as an internal vendor with no product
  management discipline (no roadmap, no backlog, no user feedback loop) —
  it stagnates into "the team that owns Kubernetes" rather than a product.
- Conflating "we built it" with "it's adopted" — maturity must be measured
  by usage, not by capability existing.
"""

from dataclasses import dataclass

# ------------------------------------------------------------------
# 1. The maturity levels
# ------------------------------------------------------------------
MATURITY_LEVELS = {
    0: "Manual / tribal knowledge — everything via ticket or Slack DM to "
       "the one person who knows how.",
    1: "Documented — a runbook exists, but execution is still manual.",
    2: "Automated — a script/pipeline exists, but a platform engineer "
       "still triggers it on someone else's behalf.",
    3: "Self-service — the requesting team can trigger it themselves via a "
       "portal/CLI/PR, with guardrails (policy as code) instead of human "
       "gatekeeping.",
    4: "Measured & optimized — SLOs exist for the platform capability "
       "itself, with continuous feedback driving improvement.",
}

# ------------------------------------------------------------------
# 2. Per-dimension assessment
# ------------------------------------------------------------------
@dataclass
class DimensionScore:
    dimension: str
    level: int
    evidence: str
    next_step: str


CURRENT_ASSESSMENT = [
    DimensionScore("provisioning", 3, "Scaffolder template + Terraform module "
                    "self-service, avg time-to-env is 12 minutes",
                    "add SLO: 95% of provisions complete under 15 min"),
    DimensionScore("secrets", 1, "Static secrets in K8s Secret objects, "
                    "manual rotation via ticket",
                    "roll out Vault dynamic DB creds (see L03)"),
    DimensionScore("ci_cd", 4, "Reusable workflow templates, DORA dashboard "
                    "tracked, deploy frequency alerted on regression",
                    "maintain — this is the model for other dimensions"),
    DimensionScore("observability", 2, "Prometheus+Grafana exist, but "
                    "dashboards are hand-built per team, no golden-signal "
                    "template", "ship a Grafana dashboard scaffolder template"),
]

# ------------------------------------------------------------------
# 3. Platform SLOs — the platform is a product with its own reliability bar
# ------------------------------------------------------------------
PLATFORM_SLOS = {
    "ci_pipeline_availability": "> 99.9% (CI being down blocks every team simultaneously)",
    "time_to_provision_environment": "p95 < 15 minutes",
    "secrets_rotation_success_rate": "> 99.99% (a failed silent rotation is "
        "an outage waiting to happen)",
    "catalog_freshness": "> 95% of services have a catalog-info.yaml updated "
        "within the last 90 days",
}

# ------------------------------------------------------------------
# 4. Team Topologies — platform team's place in the org
# ------------------------------------------------------------------
TEAM_TYPES = {
    "Stream-aligned team": "Owns a business capability end-to-end (e.g. "
        "'checkout'). The majority of engineering org headcount.",
    "Platform team": "Provides internal services (compute, CI/CD, secrets, "
        "observability) that reduce cognitive load for stream-aligned teams. "
        "Interacts via X-as-a-Service, not embedded pairing.",
    "Complicated-subsystem team": "Owns a piece of deep technical complexity "
        "(e.g. a matching engine, a ML training pipeline) that needs "
        "specialist expertise most stream-aligned engineers don't have.",
    "Enabling team": "Temporarily embeds with a stream-aligned team to "
        "level up a specific capability (e.g. helping a team adopt "
        "distributed tracing), then leaves — not a permanent dependency.",
}

INTERACTION_MODES = {
    "X-as-a-Service": "The default, healthy platform-team interaction: "
        "self-service APIs/CLIs/portals, no synchronous coordination needed "
        "per request.",
    "Collaboration": "Temporary, high-bandwidth pairing — used when "
        "building a NEW capability, not for steady-state operation.",
    "Facilitating": "Enabling-team mode — unblocking, teaching, then "
        "stepping back.",
}

# ------------------------------------------------------------------
# 5. Building a product mindset
# ------------------------------------------------------------------
PLATFORM_AS_PRODUCT_PRACTICES = [
    "Maintain a public backlog/roadmap your internal 'customers' (other "
    "engineering teams) can see and comment on — not a black box.",
    "Run an internal NPS survey per quarter: 'how likely are you to "
    "recommend the platform to a peer team' — track the trend, not just "
    "the absolute number.",
    "Track ticket volume to the platform team as a TOIL metric — a rising "
    "trend means self-service adoption is failing, not that the platform "
    "team needs more headcount to keep up with tickets.",
    "Instrument the golden-path templates themselves (scaffolder usage, "
    "CLI command usage) — you can't improve what you can't see used.",
]

# ------------------------------------------------------------------
# 6. Paved road vs golden path — a real distinction
# ------------------------------------------------------------------
PAVED_ROAD_VS_GOLDEN_PATH = (
    "Paved road = the ONLY supported way; going off it means you're on "
    "your own (no platform support). Golden path = the RECOMMENDED, "
    "friction-minimized way, but escape hatches exist for teams with a "
    "real reason to deviate, with an explicit understanding they own the "
    "resulting operational burden. Most mature platform orgs use golden "
    "path — a hard paved road tends to produce shadow infrastructure when "
    "a team's legitimate need doesn't fit the mold."
)

# ------------------------------------------------------------------
# 7. Full reference architecture — the stack this domain builds toward
# ------------------------------------------------------------------
REFERENCE_ARCHITECTURE = r"""
    Developer
        |
        v
   +-----------+       +--------------+       +-------------+
   | Backstage |------>| Scaffolder   |------>| GitHub repo |
   | (catalog, |       | (golden path |       | + CI (GHA)  |
   |  TechDocs)|       |  templates)  |       +------+------+
   +-----------+                                     |
        ^                                            v
        |                                    +---------------+
        |                                    | Terraform     |
        |                                    | (+ Atlantis   |
        |                                    |  GitOps apply)|
        |                                    +-------+-------+
        |                                            v
   +----+------+   mTLS, traffic mgmt      +----------------+
   |  Istio    |<--------------------------| Kubernetes     |
   |  (mesh)   |                           | (workloads)    |
   +-----------+                           +-------+--------+
                                                    |
        +-------------------+-------------+--------+
        v                   v              v
   +---------+        +-----------+   +-----------+
   |  Vault  |        |    OPA    |   | Prometheus|
   | secrets |        | (policy   |   | + Grafana |
   |         |        |  gate)    |   | (metrics) |
   +---------+        +-----------+   +-----------+
"""

if __name__ == "__main__":
    for d in CURRENT_ASSESSMENT:
        print(f"{d.dimension}: L{d.level} -> next: {d.next_step}")
    print(REFERENCE_ARCHITECTURE)

"""
TRADING/PRODUCTION CONTEXT EXAMPLE:
A trading firm's platform team runs a quarterly maturity review and finds
"secrets" stuck at Level 1 while everything else is Level 3+. Because a
compromised static API key is a direct financial risk (unlike, say, a slow
CI pipeline), they reprioritize the roadmap to fast-track Vault dynamic
secrets for exchange-connectivity credentials ahead of a planned
observability upgrade — the maturity model made an otherwise-implicit risk
tradeoff explicit and defensible to leadership.
"""
