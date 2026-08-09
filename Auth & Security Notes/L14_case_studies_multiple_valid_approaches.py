"""
WHAT: Four realistic authentication/authorization/security-architecture
      problems, each solved with THREE genuinely different, individually
      defensible approaches drawn from L01-L13 -- with an explicit
      comparison table and reasoning for why each answer is valid under
      different constraints.
WHY:  "Session or JWT," "RBAC or ABAC," "which secrets-management tier"
      are all questions L01-L13 gave you real tools for, not one
      universal answer -- this lesson is about the decision process
      under real threat-model and operational constraints.
LEVEL: Capstone -- read after L01-L13.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L13's concepts.
"""

# ============================================================================
# CASE STUDY 1 — CHOOSING BETWEEN SESSION-BASED AND JWT-BASED
# AUTHENTICATION
# ============================================================================
#
# SETUP: a new web application needs to authenticate users; deciding
# between traditional server-side sessions and JWT-based stateless auth
# (L01-L02).
#
# ------------------------------------------------------------------------
# APPROACH A: Traditional server-side sessions (a session ID cookie,
# session data stored server-side, e.g. in Redis) (L01)
# ------------------------------------------------------------------------
#   WHY VALID: per L01, sessions can be REVOKED instantly and completely
#   -- deleting the server-side session record immediately invalidates
#   it, a genuinely strong, simple security property (e.g. for "log out
#   everywhere" or an admin forcibly terminating a compromised
#   account's access).
#   COST: per L01, requires a shared, available session store (Redis or
#   similar) that every server instance can reach -- a real,
#   additional infrastructure dependency and a potential bottleneck/
#   single point of failure if not itself made highly available.
#
# ------------------------------------------------------------------------
# APPROACH B: Stateless JWTs (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, JWTs carry their own claims and are
#   cryptographically self-verifying -- no shared session store needed
#   at all, any server instance can independently verify a token, a
#   genuine simplicity/scalability advantage for a horizontally-scaled,
#   stateless architecture.
#   COST: per L02, JWTs CANNOT be instantly revoked by design -- once
#   issued, a JWT remains valid until it naturally expires, since
#   there's no central store to delete a record from; a compromised
#   token (or an account that needs immediate access termination)
#   remains usable until expiry unless additional infrastructure
#   (a revocation/deny-list, which reintroduces a shared, checked state
#   store, partially undoing JWT's core statelessness benefit) is
#   layered on top.
#
# ------------------------------------------------------------------------
# APPROACH C: Short-lived JWTs (e.g. 5-15 minute expiry) PLUS a
# separate, longer-lived REFRESH token that IS checked against a
# server-side store on each refresh (L02-L03)
# ------------------------------------------------------------------------
#   WHY VALID: per L02-L03, this directly balances A and B's tradeoff --
#   the short-lived JWT gives most requests B's stateless-verification
#   speed/scalability benefit, while the refresh token's server-side
#   check gives A's revocability property, just checked less frequently
#   (only on refresh, not on every single request) -- revoking the
#   refresh token means the compromised session stops being renewable
#   within, at worst, one short JWT expiry window.
#   COST: per L02-L03, genuinely more implementation complexity than
#   either A or B alone -- two token types to manage, a refresh flow to
#   implement correctly (including handling refresh-token rotation/
#   reuse-detection for security), and the SHORT JWT expiry window still
#   means a compromised token remains usable for up to that window's
#   duration, not instantly revoked the way A's session deletion is.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Instant revocability | Stateless scalability | Implementation complexity |
#   |----------|---------------------------|-----------------------------|----------------------------------|
#   | A: server-side sessions | Best | Worst (needs shared store) | Lowest |
#   | B: pure JWT | Worst | Best | Low |
#   | C: short-lived JWT + refresh token | Good (bounded delay) | Good (most requests are stateless) | Highest |
#   C is the strong, well-established modern default balancing both
#   concerns; A remains the right choice when instant, guaranteed
#   revocation is a hard security requirement (not just a nice-to-have);
#   B alone is appropriate mainly for lower-stakes, short-lived-by-
#   nature use cases where revocation delay is a genuinely acceptable
#   risk.


# ============================================================================
# CASE STUDY 2 — AUTHORIZATION MODEL FOR A B2B SAAS PRODUCT WITH
# INCREASINGLY COMPLEX PERMISSION NEEDS
# ============================================================================
#
# SETUP: a product started with simple roles (admin/member) but customers
# now want finer-grained permissions (e.g. "can view invoices but not
# edit them," "can manage users in department X only") (L05).
#
# ------------------------------------------------------------------------
# APPROACH A: Add more, finer-grained ROLES (e.g.
# "invoice_viewer," "department_x_admin") (L05)
# ------------------------------------------------------------------------
#   WHY VALID: per L05, extends the EXISTING RBAC model the team
#   already has, no architectural change needed -- straightforward to
#   understand (each user has a set of named roles, each role has
#   defined permissions) and easy to reason about for a moderate number
#   of distinct permission combinations.
#   COST: per L05, RBAC's role-explosion problem -- as genuinely
#   distinct permission COMBINATIONS grow (which department, which
#   resource type, which action, potentially multiplying together), the
#   number of distinct ROLES needed to represent every combination grows
#   combinatorially, becoming unwieldy to manage (hundreds of narrow,
#   overlapping roles) well before the underlying permission LOGIC is
#   actually that complex.
#
# ------------------------------------------------------------------------
# APPROACH B: Switch to Attribute-Based Access Control (ABAC) (L05) --
# permissions expressed as rules over ATTRIBUTES (user's department,
# resource's owner, action type) rather than fixed named roles
# ------------------------------------------------------------------------
#   WHY VALID: per L05, ABAC directly solves A's role-explosion problem
#   -- a single rule like "allow EDIT if user.department ==
#   resource.department" can express what would otherwise require many
#   separate department-specific roles, scaling much better as the
#   number of genuinely distinct attribute combinations grows.
#   COST: per L05, ABAC rules are genuinely harder to AUDIT and reason
#   about than RBAC's simple "list this user's roles, look up each
#   role's permissions" model -- understanding exactly what a user CAN
#   do requires evaluating potentially many attribute-based rules
#   against their current context, a real increase in system complexity
#   and a harder "explain why this user was denied access" debugging
#   story.
#
# ------------------------------------------------------------------------
# APPROACH C: A hybrid -- keep RBAC (A) for the COARSE, stable
# permission tiers (admin vs. member) that rarely change and are easy to
# reason about, layer ABAC-style attribute rules (B) ONLY for the
# specific, genuinely fine-grained/contextual permissions (department-
# scoping, resource-ownership checks) that RBAC handles poorly
# ------------------------------------------------------------------------
#   WHY VALID: per L05's own framing of RBAC/ABAC as complementary (not
#   strictly competing) models, this uses each mechanism where it's
#   genuinely strongest -- RBAC's simplicity for the stable, coarse
#   tiers most permission checks actually need, ABAC's flexibility
#   reserved specifically for the contextual, fine-grained cases that
#   would cause RBAC's role explosion.
#   COST: requires maintaining and correctly reasoning about TWO
#   authorization mechanisms simultaneously -- real, ongoing complexity
#   in knowing which permission checks go through which system, and a
#   genuine risk of the "which mechanism handles this specific
#   permission" boundary becoming unclear or inconsistently applied
#   over time without disciplined documentation/convention.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Handles growing permission complexity | Auditability | Migration effort from existing RBAC |
#   |----------|--------------------------------------------|-------------------|--------------------------------------------|
#   | A: more granular roles | Poorly (role explosion) | Best | None |
#   | B: full ABAC migration | Well | Harder | Highest (full rewrite) |
#   | C: RBAC + targeted ABAC for specific cases | Well | Medium | Medium (additive, not a full rewrite) |
#   C is the strongest pragmatic answer for a team with an EXISTING RBAC
#   system experiencing SOME (not universal) fine-grained permission
#   needs -- a full B migration is justified only once ABAC-style needs
#   have become the norm across most of the permission surface, not the
#   exception.


# ============================================================================
# CASE STUDY 3 — SECRETS MANAGEMENT TIER FOR A GROWING STARTUP
# ============================================================================
#
# SETUP: a startup currently stores API keys/database credentials as
# environment variables set manually per environment; deciding whether
# and how far to formalize secrets management as the team grows (L06-L07).
#
# ------------------------------------------------------------------------
# APPROACH A: Keep environment variables, but formalize the process
# (a documented runbook, `.env.example` templates, consistent naming)
# ------------------------------------------------------------------------
#   WHY VALID: per L06, for a genuinely small team/infrastructure
#   footprint, this addresses the most common failure mode (undocumented,
#   inconsistent manual secret-setting) without introducing new
#   infrastructure at all -- proportionate to a small scale.
#   COST: per L06-L07, still has NO centralized audit trail (who
#   accessed which secret, when), no automated rotation capability, and
#   secrets remain manually copy-pasted between engineers/environments
#   -- real, growing risk as team size and the number of environments/
#   services increases.
#
# ------------------------------------------------------------------------
# APPROACH B: Adopt a dedicated secrets manager (Vault, AWS Secrets
# Manager, or similar) (L06-L07)
# ------------------------------------------------------------------------
#   WHY VALID: per L06-L07, provides centralized storage, access
#   control, audit logging, and automated rotation capability -- a
#   genuine, substantial security posture improvement over scattered
#   environment variables, the standard answer once secret sprawl and
#   audit/compliance needs become real.
#   COST: per L06-L07, real infrastructure to deploy/operate (or a real
#   ongoing service cost for a managed option) and a genuine migration
#   effort to move every existing secret and every consuming service
#   over -- disproportionate overhead for a very early-stage startup
#   with a handful of secrets and no compliance driver yet.
#
# ------------------------------------------------------------------------
# APPROACH C: Start with A (formalized env-var discipline), with an
# EXPLICIT, planned trigger to migrate to B (e.g. "when we hit N
# engineers," "when we need SOC 2 compliance," "when we have our first
# security incident involving a leaked credential") rather than either
# adopting B prematurely or never revisiting the decision
# ------------------------------------------------------------------------
#   WHY VALID: per L06-L07's own framing of secrets management maturity
#   as a SCALING concern, this explicitly sequences the investment to
#   match actual, confirmed need rather than guessing -- avoids B's
#   premature-overhead risk while avoiding the OPPOSITE risk (never
#   revisiting A's real, growing limitations until a painful incident
#   forces the issue reactively).
#   COST: requires the team to actually SET and HONOR the trigger --
#   without genuine follow-through, this sequencing can quietly become
#   "we never got around to migrating," accumulating A's real, growing
#   risk indefinitely; the plan only has value if it's genuinely acted
#   on when the trigger condition is met, not just stated as an
#   intention.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Security posture | Audit/compliance readiness | Fits a very early-stage team |
#   |----------|----------------------|-----------------------------------|-------------------------------------|
#   | A: formalized env vars | Baseline | Poor | Well |
#   | B: dedicated secrets manager | Strong | Good | Poorly (premature overhead) |
#   | C: A now, explicit trigger to migrate to B | Baseline, improving on schedule | Poor until migration | Well |
#   C is the strongest answer for a genuinely early-stage team -- the
#   key discipline is actually defining and honoring the migration
#   trigger, not just deferring the decision indefinitely under the
#   banner of "we'll do it later."


# ============================================================================
# CASE STUDY 4 — SECURING SERVICE-TO-SERVICE COMMUNICATION IN A
# MICROSERVICES ARCHITECTURE
# ============================================================================
#
# SETUP: a growing microservices architecture currently has services
# communicating over plain HTTP within a private VPC, relying on network
# isolation alone; deciding whether/how to add stronger service-to-
# service authentication (L09-L10).
#
# ------------------------------------------------------------------------
# APPROACH A: Rely on network-level isolation alone (VPC/security
# groups) -- no application-layer service authentication
# ------------------------------------------------------------------------
#   WHY VALID: per L09, if the network boundary is genuinely well-
#   configured and trusted (a private VPC with tightly-scoped security
#   groups, no untrusted workloads ever running inside the boundary),
#   this provides real protection against EXTERNAL attackers with
#   meaningfully less implementation overhead than application-layer
#   auth.
#   COST: per L10's zero-trust framing, network-level isolation provides
#   NO protection against a compromised service WITHIN the boundary --
#   if any one service is compromised (a dependency vulnerability, a
#   supply-chain attack), it can freely communicate with every other
#   service inside the same network boundary with no additional
#   authentication check at all, a real, well-documented "flat network"
#   risk.
#
# ------------------------------------------------------------------------
# APPROACH B: mTLS (mutual TLS) between all services (L10)
# ------------------------------------------------------------------------
#   WHY VALID: per L10, mTLS ensures every service-to-service connection
#   is BOTH encrypted AND mutually authenticated (each side verifies the
#   other's certificate) -- directly closes A's "compromised service can
#   talk to anything" gap, since a service without a valid certificate
#   (or a certificate identifying it as a role that shouldn't have
#   access) cannot establish connections at all.
#   COST: per L10, real certificate-management complexity -- issuing,
#   rotating, and revoking certificates for every service, typically
#   requiring a service mesh (Kubernetes Notes' related discussion) or
#   dedicated PKI infrastructure to manage at scale, a genuine
#   operational investment beyond A's "just configure network rules"
#   simplicity.
#
# ------------------------------------------------------------------------
# APPROACH C: A service mesh (e.g. Istio/Linkerd, building on
# Kubernetes Notes) providing mTLS (B) AUTOMATICALLY via sidecar
# injection, without requiring each individual service's own code to
# implement TLS/certificate handling directly
# ------------------------------------------------------------------------
#   WHY VALID: per L10 combined with Kubernetes Notes' service-mesh
#   discussion, this gets B's security benefit while removing B's
#   biggest practical adoption barrier -- individual application code
#   doesn't need to change AT ALL; the mesh's sidecar proxies transparently
#   handle mTLS for every service's traffic, making org-wide adoption
#   far more achievable than requiring every team to implement
#   certificate handling in their own service code.
#   COST: per Kubernetes Notes, adopting a service mesh is itself a
#   genuine, nontrivial infrastructure investment (sidecar proxy
#   overhead per pod, mesh control-plane operational complexity, a real
#   learning curve) -- justified specifically once the NUMBER of
#   services is large enough that per-service manual mTLS
#   implementation (B alone) would be genuinely impractical to roll out
#   and maintain consistently across every team/service.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Protects against a compromised internal service | Per-service code changes required | Operational investment |
#   |----------|--------------------------------------------------------|------------------------------------------|------------------------------|
#   | A: network isolation only | No | None | Lowest |
#   | B: manual per-service mTLS | Yes | Real (every service) | Medium |
#   | C: service mesh with automatic mTLS | Yes | None | Highest (mesh infrastructure) |
#   For a small number of services, B is achievable without a full mesh;
#   C is the strongest answer once the service count is large enough
#   that consistent manual mTLS adoption across every team becomes the
#   actual bottleneck, not the mTLS concept itself; A alone is
#   increasingly hard to justify once "assume breach" / zero-trust
#   thinking (L10) is taken seriously as a real threat model.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
