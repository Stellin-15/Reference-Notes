# ============================================================
# L13: API Gateway Multi-Tenant Isolation — Zuplo-Style Patterns
# ============================================================
# WHAT: Enforcing per-tenant authentication boundaries, rate limits, and
#       data isolation at the API GATEWAY layer — using an edge/API
#       gateway platform (Zuplo is a concrete example of this category)
#       to guarantee tenant isolation BEFORE a request ever reaches
#       application code, rather than relying on every backend service
#       to independently enforce it correctly.
# WHY: This repo's API Design Notes L05 covers API gateways generally
#      (Kong, AWS API Gateway) and routing/auth patterns. This lesson
#      focuses specifically on the MULTI-TENANT ISOLATION angle — the
#      security property that Tenant A's requests/data can NEVER be
#      visible to or processed by Tenant B's context, enforced as a
#      centralized, auditable gateway-layer control rather than
#      scattered per-service logic.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
MULTI-TENANT ISOLATION means multiple distinct CUSTOMERS/ORGANIZATIONS
(tenants) share the SAME underlying infrastructure/API, but each
tenant's requests, data, and rate limits are STRICTLY SEGREGATED from
every other tenant's — a bug or misconfiguration should NEVER let Tenant
A see or affect Tenant B's data, even though both are hitting the exact
same API endpoints and backend services.

ENFORCING THIS AT THE GATEWAY LAYER (rather than trusting every backend
service to independently implement correct tenant-scoping logic) is the
core architectural decision this lesson covers: an API gateway
(Zuplo, Kong, AWS API Gateway — the specific product matters less than
the pattern) sits in front of EVERY request, extracts the TENANT
IDENTITY from the authenticated request (typically from a JWT claim or
an API key's associated tenant), and enforces isolation controls BEFORE
the request reaches any backend service — this is a single, centrally-
audited enforcement point, rather than trusting N different backend
services to each correctly implement the same tenant-scoping logic
independently (where a single service with a bug becomes a cross-tenant
data leak).

PER-TENANT RATE LIMITING at the gateway (distinct from L08's per-tenant
LLM-specific quotas in Event-Driven & Real-Time AI Systems Notes, though
the same underlying principle) prevents one tenant's traffic spike
(legitimate or a bug in their own integration) from degrading service
for OTHER tenants sharing the same backend infrastructure — this is
NOISY-NEIGHBOR PROTECTION, a distinct concern from authentication/
authorization but equally important for genuine tenant isolation.

TENANT CONTEXT PROPAGATION is how the gateway communicates the
authenticated tenant's identity to backend services — typically by
injecting a TRUSTED, gateway-signed header (e.g. `X-Tenant-Id`) that
backend services can rely on WITHOUT re-validating the original
authentication themselves (since the gateway already did that), as long
as backend services are configured to ONLY accept traffic that has
passed through the gateway (network policy or mTLS enforcement — this
repo's Kubernetes Notes covers NetworkPolicy for exactly this kind of
"only accept traffic from a specific source" enforcement).

PRODUCTION USE CASE:
A partner-facing API platform serving 100+ enterprise customers routes
ALL traffic through an API gateway that: validates each request's JWT
and extracts the tenant ID, enforces a per-tenant rate limit sized to
that customer's contract tier, injects a trusted `X-Tenant-Id` header
for backend services to scope their database queries by, and logs every
request with its tenant context for centralized auditing — a single
gateway-layer bug fix or policy change (e.g. tightening rate limits)
applies instantly and consistently across every backend service, rather
than requiring N separate services to each be updated correctly.

COMMON MISTAKES:
- Trusting a CLIENT-SUPPLIED tenant identifier (e.g. a tenant_id in the
  request body or an unsigned header) instead of DERIVING tenant
  identity from the authenticated request itself (a validated JWT
  claim) — a client-supplied, unvalidated tenant ID is trivially
  spoofable, letting any authenticated user claim to be ANY tenant simply
  by changing a request parameter.
- Enforcing tenant isolation ONLY at the gateway without ALSO enforcing
  it as a defense-in-depth measure at the DATA layer (e.g. row-level
  security or a mandatory WHERE tenant_id = ? clause in every query,
  directly connecting to the Agentic AI & RAG Notes L11 tenant-scoped
  retriever pattern) — relying on a SINGLE enforcement point means one
  gateway misconfiguration is a complete isolation failure, rather than
  one layer of several independent safeguards.
- Applying uniform rate limits across all tenants regardless of contract
  tier or actual usage patterns — this either under-serves high-volume
  legitimate customers or fails to meaningfully protect against a
  genuinely abusive/buggy low-tier tenant, when per-tenant-tier limits
  would serve both cases correctly.
"""

import textwrap
from dataclasses import dataclass


# ------------------------------------------------------------------
# 1. Extracting trusted tenant identity from an authenticated request
# ------------------------------------------------------------------
GATEWAY_TENANT_EXTRACTION_EXAMPLE = textwrap.dedent("""\
    // Zuplo-style gateway policy (conceptual TypeScript, runs at the edge
    // BEFORE the request reaches any backend service)
    export default async function tenantIsolationPolicy(request, context) {
      const decoded = await context.jwt.verify(request.headers.get("Authorization"));

      // Tenant identity comes from a VALIDATED JWT CLAIM — never from a
      // client-supplied, unsigned request parameter, which would be
      // trivially spoofable.
      const tenantId = decoded.claims["tenant_id"];
      if (!tenantId) {
        return new Response("Unauthorized: missing tenant context", { status: 401 });
      }

      // Inject a TRUSTED header for backend services — they can rely on
      // this without re-validating the original JWT themselves, as long
      // as network policy ensures they ONLY accept traffic from the gateway.
      const forwardedRequest = new Request(request);
      forwardedRequest.headers.set("X-Tenant-Id", tenantId);
      forwardedRequest.headers.set("X-Tenant-Verified", "true");
      return context.forward(forwardedRequest);
    }
""")

# ------------------------------------------------------------------
# 2. Per-tenant rate limiting, sized by contract tier
# ------------------------------------------------------------------
@dataclass
class TenantTier:
    tier_name: str
    requests_per_minute: int


TENANT_TIERS = {
    "enterprise": TenantTier("enterprise", requests_per_minute=10_000),
    "standard": TenantTier("standard", requests_per_minute=1_000),
    "trial": TenantTier("trial", requests_per_minute=100),
}


class GatewayRateLimiter:
    def __init__(self):
        self.tenant_tier_assignment: dict[str, str] = {}
        self.request_counts: dict[str, int] = {}   # simplified — a real gateway uses a sliding window

    def assign_tier(self, tenant_id: str, tier: str):
        self.tenant_tier_assignment[tenant_id] = tier

    def check_and_record(self, tenant_id: str) -> bool:
        tier_name = self.tenant_tier_assignment.get(tenant_id, "trial")
        tier = TENANT_TIERS[tier_name]
        count = self.request_counts.get(tenant_id, 0)

        if count >= tier.requests_per_minute:
            return False   # this tenant's limit is exceeded — reject BEFORE hitting backend services

        self.request_counts[tenant_id] = count + 1
        return True


# ------------------------------------------------------------------
# 3. Defense in depth — gateway isolation PLUS data-layer enforcement
# ------------------------------------------------------------------
DEFENSE_IN_DEPTH_EXAMPLE = textwrap.dedent("""\
    -- Even with gateway-layer isolation, backend services should ALSO
    -- enforce tenant scoping at the DATA layer as an independent safety
    -- net — e.g. PostgreSQL row-level security, so a bug in application
    -- code (forgetting a WHERE clause) can't leak cross-tenant data
    -- even if the gateway's isolation somehow failed.

    ALTER TABLE customer_records ENABLE ROW LEVEL SECURITY;

    CREATE POLICY tenant_isolation_policy ON customer_records
      USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

    -- The application sets this session variable from the TRUSTED
    -- X-Tenant-Id header (injected by the gateway, step 1 above) at the
    -- start of each request:
    --   SET app.current_tenant_id = '<tenant_id from X-Tenant-Id header>';
    -- From this point, EVERY query against customer_records is
    -- automatically scoped to this tenant by PostgreSQL itself,
    -- regardless of whether the application code remembered to add a
    -- WHERE clause — a genuine second, independent layer of defense.
""")

# ------------------------------------------------------------------
# 4. Auditing — centralized, gateway-layer request logging
# ------------------------------------------------------------------
AUDIT_LOGGING_NOTE = (
    "Because every request passes through ONE gateway, tenant-scoped "
    "audit logging is naturally centralized — every request's tenant "
    "ID, endpoint, timestamp, and outcome is logged in ONE place, "
    "rather than needing to aggregate logs from N independently-"
    "instrumented backend services to answer 'what did tenant X do "
    "last week' — directly analogous to Feature Stores & Modern Data "
    "Lake Notes L10's event-ledger pattern, applied here to API request auditing."
)


if __name__ == "__main__":
    print(GATEWAY_TENANT_EXTRACTION_EXAMPLE)

    print("--- Per-tenant rate limiting demo ---")
    limiter = GatewayRateLimiter()
    limiter.assign_tier("acme_corp", "enterprise")
    limiter.assign_tier("small_startup", "trial")

    for i in range(3):
        allowed = limiter.check_and_record("small_startup")
        print(f"  small_startup request {i+1}: {'allowed' if allowed else 'RATE LIMITED'}")

    print(f"\n{DEFENSE_IN_DEPTH_EXAMPLE}")
    print(AUDIT_LOGGING_NOTE)

"""
PRODUCTION CONTEXT EXAMPLE:
A partner API platform's gateway hardening initiative moves tenant
isolation from scattered, per-service logic (each backend service
independently trusting a client-supplied tenant_id) to centralized
gateway enforcement (deriving tenant identity from a validated JWT
claim, injecting a trusted header, and enforcing per-tier rate limits)
PLUS a data-layer row-level-security policy as defense in depth — closing
a real vulnerability class where a single backend service's oversight
(trusting client input for tenant scoping) had been the ONLY thing
preventing a cross-tenant data leak, now backed by two independent,
centrally-managed enforcement layers instead of one easily-missed one.
"""
