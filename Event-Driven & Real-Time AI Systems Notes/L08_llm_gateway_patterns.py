# ============================================================
# L08: Building an Internal LLM Gateway
# ============================================================
# WHAT: The full internal-service pattern that wraps L07's multi-model
#       routing into an actual GATEWAY every team in an organization
#       calls — per-tenant rate limiting/quotas, unified logging across
#       providers, and centralized secrets management for multiple
#       provider API keys.
# WHY: L07 covered ROUTING logic. A real organization with many teams
#      building LLM features needs a shared, centrally-operated SERVICE
#      implementing that routing ONCE — otherwise every team
#      re-implements routing, rate limiting, and observability
#      independently, with inconsistent quality and duplicated operational burden.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
An LLM GATEWAY is an internal service that every other team's
application calls INSTEAD OF calling LLM providers directly — it owns
provider routing (L07), and additionally: PER-TENANT RATE LIMITING/
QUOTAS (each internal team/product gets a bounded quota of requests or
spend, preventing one team's runaway usage from starving others or
causing an unexpectedly large bill), UNIFIED LOGGING (every request,
regardless of which underlying provider actually served it, is logged
in one consistent format — feeding into the observability tooling this
repo's Agentic AI & RAG Notes L23 covers), and CENTRALIZED SECRETS
MANAGEMENT (provider API keys live in ONE place, rotated/managed by the
platform team, rather than scattered across every consuming team's own
configuration).

PER-TENANT RATE LIMITING/QUOTAS solve a real organizational problem:
without them, ANY team's LLM feature can consume unbounded provider
spend or hit provider-side rate limits that then affect EVERY OTHER
team sharing the same provider account — a gateway enforcing per-tenant
limits (e.g. "team X gets 10,000 requests/day and a $500/day spend cap")
isolates one team's usage pattern from affecting others, the same
isolation principle behind Auth & Security Notes' multi-tenant API
gateway coverage, applied specifically to LLM usage.

UNIFIED LOGGING matters because, without a gateway, observability
(Agentic AI & RAG Notes L23's LangSmith/Langfuse-style tracing) would
need to be independently integrated by every team calling LLM providers
directly — a gateway that logs every request/response/cost/latency ONCE,
centrally, means observability tooling is integrated ONCE at the gateway
layer and automatically covers every team's usage, without each team
needing its own separate instrumentation effort.

CENTRALIZED SECRETS MANAGEMENT means individual application teams never
directly hold provider API keys at all — they authenticate to the
INTERNAL gateway (via a service-to-service auth mechanism, e.g. an
internal API key or mTLS), and the gateway itself holds and uses the
actual provider credentials (ideally sourced from Vault or a similar
secrets manager, this repo's Platform Engineering Notes L03) — this
means rotating a provider's API key is ONE operation (updating the
gateway's own secret) rather than needing every consuming team to update
their own copy of that key.

PRODUCTION USE CASE:
An organization with 15 internal teams building LLM-powered features
routes ALL of them through one internal LLM gateway — each team
authenticates with an internal service token, gets a quota appropriate
to their product's expected usage, and the gateway's centralized
logging gives the platform team a single dashboard showing total LLM
spend broken down by team, provider, and model — a view that would be
essentially impossible to assemble if each team called providers
directly with their own credentials and their own (or no) instrumentation.

COMMON MISTAKES:
- Letting every team acquire and manage their OWN provider API keys
  directly — this scatters secrets across many teams' configurations
  (a real security surface), makes organization-wide spend visibility
  nearly impossible to assemble, and multiplies the blast radius of any
  single leaked key.
- Implementing per-tenant rate limiting as a "nice to have" added later,
  after a runaway usage incident from one team has already affected
  others — this is exactly the kind of isolation control worth building
  in BEFORE the first incident, not reactively after.
- Building the gateway without unified logging from day one — retrofitting
  observability onto a gateway already handling significant production
  traffic, across many already-integrated teams, is considerably more
  disruptive than building the logging layer in from the start.
"""

import textwrap
from dataclasses import dataclass, field
from datetime import date


# ------------------------------------------------------------------
# 1. Per-tenant rate limiting / quotas
# ------------------------------------------------------------------
@dataclass
class TenantQuota:
    tenant_id: str
    daily_request_limit: int
    daily_spend_limit_usd: float


@dataclass
class TenantUsage:
    tenant_id: str
    usage_date: date
    requests_made: int = 0
    spend_usd: float = 0.0


class QuotaEnforcer:
    def __init__(self):
        self.quotas: dict[str, TenantQuota] = {}
        self.usage: dict[tuple[str, date], TenantUsage] = {}

    def set_quota(self, quota: TenantQuota):
        self.quotas[quota.tenant_id] = quota

    def check_and_record(self, tenant_id: str, today: date, estimated_cost: float) -> bool:
        quota = self.quotas.get(tenant_id)
        if quota is None:
            raise ValueError(f"No quota configured for tenant '{tenant_id}'")

        usage = self.usage.setdefault((tenant_id, today), TenantUsage(tenant_id, today))

        if usage.requests_made >= quota.daily_request_limit:
            return False   # request quota exceeded — reject BEFORE calling any provider
        if usage.spend_usd + estimated_cost > quota.daily_spend_limit_usd:
            return False   # spend quota would be exceeded — reject

        usage.requests_made += 1
        usage.spend_usd += estimated_cost
        return True


# ------------------------------------------------------------------
# 2. Unified logging across providers
# ------------------------------------------------------------------
@dataclass
class GatewayLogEntry:
    tenant_id: str
    provider: str
    model: str
    latency_ms: float
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int


class UnifiedLogger:
    """
    ONE consistent log format regardless of which underlying provider
    actually served the request — feeding a single dashboard/observability
    pipeline (Agentic AI & RAG Notes L23) that covers every team's usage
    automatically, without each team integrating tracing themselves.
    """

    def __init__(self):
        self.entries: list[GatewayLogEntry] = []

    def log(self, entry: GatewayLogEntry):
        self.entries.append(entry)

    def spend_by_tenant(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for e in self.entries:
            totals[e.tenant_id] = totals.get(e.tenant_id, 0) + e.cost_usd
        return totals

    def spend_by_provider(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for e in self.entries:
            totals[e.provider] = totals.get(e.provider, 0) + e.cost_usd
        return totals


# ------------------------------------------------------------------
# 3. The gateway, tying quota enforcement + routing + logging together
# ------------------------------------------------------------------
class LLMGateway:
    def __init__(self, quota_enforcer: QuotaEnforcer, logger: UnifiedLogger):
        self.quota_enforcer = quota_enforcer
        self.logger = logger
        # In a real gateway, provider adapters/keys (L07) are loaded from
        # a centralized secrets manager (Platform Engineering Notes L03),
        # never held by the calling team at all.

    def generate(self, tenant_id: str, prompt: str, today: date) -> str:
        estimated_cost = 0.002   # a real implementation estimates from prompt length/model
        allowed = self.quota_enforcer.check_and_record(tenant_id, today, estimated_cost)
        if not allowed:
            raise PermissionError(f"Tenant '{tenant_id}' has exceeded its daily quota")

        # ... actual L07-style routing/generation happens here ...
        result_text = f"<generated response for tenant {tenant_id}>"

        self.logger.log(GatewayLogEntry(
            tenant_id=tenant_id, provider="anthropic", model="claude-opus-4-5",
            latency_ms=850, cost_usd=estimated_cost, prompt_tokens=120, completion_tokens=80,
        ))
        return result_text


SECRETS_MANAGEMENT_NOTE = textwrap.dedent("""\
    The gateway itself is the ONLY component holding real provider API
    keys, sourced from a secrets manager (e.g. HashiCorp Vault — see
    this repo's Platform Engineering Notes L03) rather than static
    config files:

        vault_client = hvac.Client(url="https://vault.internal")
        openai_key = vault_client.secrets.kv.v2.read_secret_version(
            path="llm-gateway/openai-api-key"
        )["data"]["data"]["key"]

    Rotating a compromised or expiring key is now ONE operation (update
    it in Vault; the gateway picks up the new value on its next secret
    refresh) rather than needing every one of 15 consuming teams to
    separately update their own copy of that key.
""")


if __name__ == "__main__":
    enforcer = QuotaEnforcer()
    enforcer.set_quota(TenantQuota("team-support-bot", daily_request_limit=1000, daily_spend_limit_usd=50.0))

    logger = UnifiedLogger()
    gateway = LLMGateway(enforcer, logger)

    today = date(2026, 1, 15)
    for i in range(3):
        gateway.generate("team-support-bot", f"prompt {i}", today)

    print("Unified spend by tenant:", logger.spend_by_tenant())
    print("Unified spend by provider:", logger.spend_by_provider())
    print()
    print(SECRETS_MANAGEMENT_NOTE)

"""
PRODUCTION CONTEXT EXAMPLE:
A platform team operating an internal LLM gateway for 15+ product teams
catches a newly-launched feature's runaway usage (a bug causing it to
retry LLM calls in a tight loop) via the gateway's per-tenant quota
enforcement — that team's requests are rejected once their daily quota
is hit, containing the incident's cost impact to a bounded, known amount
and preventing it from affecting the SHARED provider account's rate
limits for the other 14 teams, who continue operating normally
throughout the incident.
"""
