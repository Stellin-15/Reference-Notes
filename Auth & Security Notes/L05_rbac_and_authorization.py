# =============================================================================
# WHAT: Role-Based, Attribute-Based, and Relationship-Based Access Control
# WHY:  Authorization is the #1 source of privilege escalation bugs. Knowing
#       how to model, enforce, and audit access decisions at every layer —
#       from API endpoints to database rows — is essential for any production
#       backend or platform engineering role.
# LEVEL: Intermediate → Advanced
# =============================================================================

# CONCEPT OVERVIEW
# ----------------
# Authorization answers "can subject X perform action Y on resource Z?"
#
# Three dominant models:
#   RBAC  — permissions grouped into roles, users assigned roles.
#           Simple, well-understood, great for most SaaS products.
#   ABAC  — policies evaluate attributes of user, resource, and environment.
#           Very expressive; powers AWS IAM, GCP IAM, XACML.
#   ReBAC — permissions derived from relationships in a graph.
#           Powers Google Zanzibar (Docs, Drive, YouTube), Okta FGA.
#
# Policy engines: Python Casbin, Open Policy Agent (OPA / Rego).
# Enforcement points: API middleware, DB row-level security, service mesh.

# PRODUCTION USE CASE
# -------------------
# Multi-tenant SaaS: a user can be OWNER of org A, VIEWER of org B.
# Within an org, they have EDITOR on project X, no access to project Y.
# Row-level security ensures they never read another tenant's DB rows even
# if the application layer has a bug.

# COMMON MISTAKES
# ---------------
# 1. Checking role strings in business logic ("if role == 'admin'") instead
#    of checking specific permissions — violates single-responsibility and
#    makes refactoring painful.
# 2. Forgetting to re-check authorization after a role change (cache the
#    decision, not the role assignment).
# 3. Trusting user-supplied tenant_id in queries without server-side enforcement.
# 4. Conflating authentication (who are you?) with authorization (what can you do?).
# 5. Not logging authorization denials — you lose visibility into attacks.

import enum
import time
import logging
import json
from dataclasses import dataclass, field
from typing import Any
from functools import wraps

# Third-party (install: pip install casbin httpx fastapi)
# import casbin           # policy enforcement
# import httpx            # OPA HTTP API calls
# from fastapi import FastAPI, Depends, HTTPException, status
# from fastapi.security import OAuth2PasswordBearer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# =============================================================================
# SECTION 1: RBAC — Role-Based Access Control
# =============================================================================

class Permission(enum.Enum):
    """Fine-grained permissions. Prefer verbs on resources over generic 'read/write'."""
    USERS_READ        = "users:read"
    USERS_WRITE       = "users:write"
    USERS_DELETE      = "users:delete"
    BILLING_READ      = "billing:read"
    BILLING_WRITE     = "billing:write"
    REPORTS_READ      = "reports:read"
    REPORTS_EXPORT    = "reports:export"
    ADMIN_IMPERSONATE = "admin:impersonate"
    SETTINGS_WRITE    = "settings:write"


@dataclass
class Role:
    """
    A role is a named collection of permissions.
    WHY: bundling permissions into roles reduces the operational surface —
    you grant roles to users, not individual permissions.
    """
    name: str
    permissions: set[Permission] = field(default_factory=set)
    # Parent roles whose permissions are inherited (role hierarchy)
    parents: list["Role"] = field(default_factory=list)

    def effective_permissions(self) -> set[Permission]:
        """
        Recursively collect permissions from this role and all ancestors.
        This models role hierarchy: ADMIN inherits from EDITOR inherits from VIEWER.
        """
        result = set(self.permissions)
        for parent in self.parents:
            # Recursion handles arbitrary depth hierarchies
            result |= parent.effective_permissions()
        return result


# Define the role hierarchy
VIEWER_ROLE = Role(
    name="viewer",
    permissions={Permission.USERS_READ, Permission.REPORTS_READ},
)

EDITOR_ROLE = Role(
    name="editor",
    permissions={Permission.USERS_WRITE, Permission.REPORTS_EXPORT},
    parents=[VIEWER_ROLE],   # editors inherit all viewer permissions
)

BILLING_ROLE = Role(
    name="billing",
    permissions={Permission.BILLING_READ, Permission.BILLING_WRITE},
    parents=[VIEWER_ROLE],
)

ADMIN_ROLE = Role(
    name="admin",
    permissions={
        Permission.USERS_DELETE,
        Permission.ADMIN_IMPERSONATE,
        Permission.SETTINGS_WRITE,
    },
    parents=[EDITOR_ROLE, BILLING_ROLE],  # multiple inheritance is fine
)

ROLE_REGISTRY: dict[str, Role] = {
    "viewer":  VIEWER_ROLE,
    "editor":  EDITOR_ROLE,
    "billing": BILLING_ROLE,
    "admin":   ADMIN_ROLE,
}


@dataclass
class User:
    id: str
    email: str
    roles: list[str] = field(default_factory=list)  # role names


def user_has_permission(user: User, permission: Permission) -> bool:
    """
    Check whether a user holds a specific permission through any of their roles.
    WHY: callers check permissions, not role names. This decouples application
    logic from the role naming scheme.
    """
    for role_name in user.roles:
        role = ROLE_REGISTRY.get(role_name)
        if role and permission in role.effective_permissions():
            return True
    return False


def require_permission(permission: Permission):
    """
    Decorator for protecting functions with a permission check.
    Useful outside of web frameworks (e.g., CLI tools, background jobs).
    """
    def decorator(func):
        @wraps(func)
        def wrapper(user: User, *args, **kwargs):
            if not user_has_permission(user, permission):
                # Always log denials — they indicate probing or misconfiguration
                logger.warning(
                    "AUTHZ_DENIED user=%s permission=%s",
                    user.id, permission.value
                )
                raise PermissionError(
                    f"User {user.id} lacks permission {permission.value}"
                )
            logger.info("AUTHZ_GRANTED user=%s permission=%s", user.id, permission.value)
            return func(user, *args, **kwargs)
        return wrapper
    return decorator


@require_permission(Permission.USERS_DELETE)
def delete_user(actor: User, target_user_id: str) -> None:
    """Only users with USERS_DELETE permission can call this."""
    print(f"{actor.id} deleted user {target_user_id}")


# Demo
alice = User(id="alice", email="alice@example.com", roles=["admin"])
bob   = User(id="bob",   email="bob@example.com",   roles=["viewer"])

print("=== RBAC Demo ===")
print(f"Alice effective perms: {[p.value for p in ROLE_REGISTRY['admin'].effective_permissions()]}")

try:
    delete_user(alice, "user-999")   # succeeds
    delete_user(bob,   "user-999")   # raises PermissionError
except PermissionError as e:
    print(f"Denied: {e}")


# =============================================================================
# SECTION 2: ABAC — Attribute-Based Access Control
# =============================================================================
# WHY ABAC: RBAC cannot express "users can only edit their own documents" or
# "access is allowed only from corporate IP during business hours."

@dataclass
class ABACContext:
    """
    The full context passed to a policy evaluation.
    Attribute categories:
      subject    — who is making the request (user attributes)
      resource   — what is being accessed
      action     — what operation is being performed
      environment — time, IP, device trust, MFA status
    """
    subject: dict[str, Any]      # e.g. {"id": "u1", "department": "engineering", "clearance": 2}
    resource: dict[str, Any]     # e.g. {"type": "document", "owner": "u1", "classification": "secret"}
    action: str                  # e.g. "read", "write", "delete"
    environment: dict[str, Any]  # e.g. {"ip": "10.0.0.5", "hour": 14, "mfa": True}


def evaluate_abac_policy(ctx: ABACContext) -> tuple[bool, str]:
    """
    Pure-Python ABAC policy evaluator.
    In production, replace this with OPA (Section 4) or AWS IAM condition keys.

    Returns (allowed: bool, reason: str).
    """
    # Policy 1: Only owners can delete their own resources
    if ctx.action == "delete":
        if ctx.resource.get("owner") != ctx.subject.get("id"):
            return False, "only resource owner can delete"

    # Policy 2: Secret documents require clearance level >= 3
    if ctx.resource.get("classification") == "secret":
        if ctx.subject.get("clearance", 0) < 3:
            return False, "insufficient clearance for secret document"

    # Policy 3: Write operations require MFA
    if ctx.action == "write":
        if not ctx.environment.get("mfa", False):
            return False, "write operations require MFA"

    # Policy 4: Restrict access to business hours (9–18 UTC) for non-admins
    if ctx.subject.get("role") != "admin":
        hour = ctx.environment.get("hour", 12)
        if not (9 <= hour < 18):
            return False, "access outside business hours denied for non-admin"

    return True, "allowed"


ctx_allowed = ABACContext(
    subject={"id": "u1", "role": "editor", "clearance": 1},
    resource={"type": "document", "owner": "u1", "classification": "public"},
    action="write",
    environment={"ip": "10.0.0.5", "hour": 14, "mfa": True},
)

ctx_denied = ABACContext(
    subject={"id": "u2", "role": "editor", "clearance": 1},
    resource={"type": "document", "owner": "u1", "classification": "public"},
    action="delete",         # u2 is not the owner
    environment={"ip": "10.0.0.5", "hour": 14, "mfa": True},
)

print("\n=== ABAC Demo ===")
print("Allowed?", evaluate_abac_policy(ctx_allowed))
print("Denied? ", evaluate_abac_policy(ctx_denied))


# =============================================================================
# SECTION 3: Python Casbin — Policy Enforcement Engine
# =============================================================================
# Casbin separates model (HOW policies work) from policy (WHAT is allowed).
# WHY: externalize access control so non-engineers can audit/change rules.

CASBIN_MODEL_CONF = """
# model.conf — RBAC with domain (tenant) support
[request_definition]
r = sub, dom, obj, act

[policy_definition]
p = sub, dom, obj, act

[role_definition]
g = _, _, _          # user, role, domain (tenant)

[policy_effect]
e = some(where (p.eft == allow))

[matchers]
m = g(r.sub, p.sub, r.dom) && r.dom == p.dom && r.obj == p.obj && r.act == p.act
"""

# policy.csv — stored in DB or git-managed flat file
CASBIN_POLICY_CSV = """
# role definitions: user alice has admin role in tenant org1
g, alice, admin, org1
g, bob,   viewer, org1
g, carol, editor, org2

# permission definitions: role, domain, resource, action
p, admin,  org1, /api/users, DELETE
p, editor, org1, /api/users, GET
p, editor, org1, /api/users, POST
p, viewer, org1, /api/users, GET
p, editor, org2, /api/reports, GET
"""

# Usage with real Casbin (uncomment when casbin is installed):
#
# import casbin
# e = casbin.Enforcer("model.conf", "policy.csv")
#
# # Check: can alice DELETE /api/users in org1?
# allowed = e.enforce("alice", "org1", "/api/users", "DELETE")
# assert allowed == True
#
# # Check: can bob DELETE /api/users in org1?
# allowed = e.enforce("bob", "org1", "/api/users", "DELETE")
# assert allowed == False
#
# # Add a role assignment at runtime (persists to adapter)
# e.add_role_for_user_in_domain("dave", "editor", "org1")
# e.save_policy()

print("\n=== Casbin Policy (textual) ===")
print("Model stored in model.conf, policy in policy.csv or a DB adapter.")
print("Call e.enforce(sub, dom, obj, act) at every request.")


# =============================================================================
# SECTION 4: ReBAC — Relationship-Based Access Control (Google Zanzibar)
# =============================================================================
# WHY: RBAC/ABAC can't elegantly express "user can view doc because they are
# a member of a group that has viewer on a folder that contains the doc."
# Zanzibar models this as a directed graph of tuples.

@dataclass(frozen=True)
class Tuple:
    """
    A Zanzibar-style relation tuple: object#relation@user_or_userset.

    Examples:
      group:eng#member@user:alice        alice is a member of group eng
      doc:readme#viewer@group:eng#member  eng members are viewers of readme
      doc:readme#owner@user:bob           bob owns readme
    """
    object_type: str    # e.g. "doc", "group", "folder"
    object_id: str      # e.g. "readme"
    relation: str       # e.g. "viewer", "member", "owner"
    subject_type: str   # e.g. "user", "group"
    subject_id: str     # e.g. "alice"
    subject_relation: str | None = None  # e.g. "member" (userset reference)


class ReBAC:
    """
    Minimal Zanzibar-inspired check engine.
    Production: use OpenFGA (open source Zanzibar), Permify, or SpiceDB.
    """

    def __init__(self):
        self._tuples: list[Tuple] = []

    def write(self, t: Tuple) -> None:
        """Add a relationship tuple."""
        self._tuples.append(t)

    def check(
        self,
        obj_type: str,
        obj_id: str,
        relation: str,
        subj_type: str,
        subj_id: str,
        _depth: int = 0,
    ) -> bool:
        """
        Recursive check: does (subj_type:subj_id) have `relation` on obj_type:obj_id?
        Handles direct tuples and userset expansion (group membership).
        """
        if _depth > 10:
            # Guard against cycles in misconfigured policies
            return False

        for t in self._tuples:
            if t.object_type != obj_type or t.object_id != obj_id or t.relation != relation:
                continue

            # Direct match: user:alice#viewer@doc:readme
            if t.subject_type == subj_type and t.subject_id == subj_id and t.subject_relation is None:
                return True

            # Userset expansion: group:eng#member is a viewer → check alice is member of eng
            if t.subject_relation is not None:
                if self.check(
                    t.subject_type, t.subject_id, t.subject_relation,
                    subj_type, subj_id,
                    _depth + 1,
                ):
                    return True

        return False


rebac = ReBAC()

# Alice is a member of group:eng
rebac.write(Tuple("group", "eng", "member", "user", "alice"))

# group:eng#member are viewers of doc:api-spec
rebac.write(Tuple("doc", "api-spec", "viewer", "group", "eng", "member"))

# Bob directly owns doc:api-spec
rebac.write(Tuple("doc", "api-spec", "owner", "user", "bob"))

print("\n=== ReBAC Demo ===")
# Alice inherits viewer through group membership
print("alice viewer on api-spec:", rebac.check("doc", "api-spec", "viewer", "user", "alice"))
# Bob is owner, not listed as viewer — owner != viewer unless policy says so
print("bob   viewer on api-spec:", rebac.check("doc", "api-spec", "viewer", "user", "bob"))
print("bob   owner  on api-spec:", rebac.check("doc", "api-spec", "owner",  "user", "bob"))
# Carol has no relation at all
print("carol viewer on api-spec:", rebac.check("doc", "api-spec", "viewer", "user", "carol"))


# =============================================================================
# SECTION 5: OPA (Open Policy Agent) — Rego Policies via HTTP API
# =============================================================================
# WHY OPA: language-agnostic, decoupled policy service. Runs as a sidecar or
# central service. Policies are version-controlled Rego files.

OPA_REGO_EXAMPLE = """
# policy.rego
package authz

import future.keywords.if

# Default deny — explicit allow is safer than default allow
default allow := false

# Allow if the user has the required role for the action
allow if {
    role := data.roles[input.user][_]           # look up user's roles
    perm := data.role_permissions[role][_]      # look up role's permissions
    perm == input.action                        # permission matches requested action
}

# Allow owners to perform any action on their own resources
allow if {
    input.resource.owner == input.user
}

# Deny access outside business hours for non-admins
deny_hours if {
    not "admin" in data.roles[input.user]
    hour := time.clock(time.now_ns())[0]
    hour < 9
}

deny_hours if {
    not "admin" in data.roles[input.user]
    hour := time.clock(time.now_ns())[0]
    hour >= 18
}
"""

# OPA HTTP API client
def opa_check(
    opa_url: str,
    policy_path: str,
    input_data: dict[str, Any],
) -> bool:
    """
    Ask OPA whether an action is allowed.

    Args:
        opa_url:     base URL of the OPA server, e.g. "http://opa:8181"
        policy_path: Rego package path, e.g. "authz/allow"
        input_data:  the 'input' document sent to OPA

    WHY separate input from policy: keeps auth logic out of application code.
    The application just assembles facts; OPA decides.
    """
    # Uncomment to use real OPA:
    # import httpx
    # response = httpx.post(
    #     f"{opa_url}/v1/data/{policy_path.replace('.', '/')}",
    #     json={"input": input_data},
    #     timeout=0.5,   # authorization latency budget is tight
    # )
    # response.raise_for_status()
    # return response.json().get("result", False)

    # Simulated for this reference:
    print(f"[OPA] Would POST to {opa_url}/v1/data/{policy_path}")
    print(f"[OPA] Input: {json.dumps(input_data, indent=2)}")
    return True   # placeholder

print("\n=== OPA Demo ===")
opa_check(
    opa_url="http://opa:8181",
    policy_path="authz/allow",
    input_data={
        "user": "alice",
        "action": "users:delete",
        "resource": {"type": "user", "owner": "bob"},
    },
)


# =============================================================================
# SECTION 6: FastAPI Permission Dependency Injection
# =============================================================================
# WHY: FastAPI's Depends() system lets you compose authentication + authorization
# cleanly. Each endpoint declares what it needs; the framework wires it up.

FASTAPI_EXAMPLE = '''
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

app = FastAPI()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Decode JWT, look up user. Raises 401 if invalid."""
    payload = decode_jwt(token)            # your JWT library
    user = db.get_user(payload["sub"])
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    return user

def require(permission: Permission):
    """
    Returns a FastAPI dependency that checks a specific permission.
    Usage: Depends(require(Permission.USERS_DELETE))
    """
    def dependency(user: User = Depends(get_current_user)) -> User:
        if not user_has_permission(user, permission):
            logger.warning("AUTHZ_DENIED user=%s perm=%s", user.id, permission.value)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission.value}",
            )
        logger.info("AUTHZ_GRANTED user=%s perm=%s", user.id, permission.value)
        return user
    return dependency

@app.delete("/users/{user_id}")
async def delete_user_endpoint(
    user_id: str,
    actor: User = Depends(require(Permission.USERS_DELETE)),  # 403 if lacking
):
    """
    Only reachable if the actor has USERS_DELETE.
    The permission check happens before this function body runs.
    """
    ...
'''

print("\n=== FastAPI Dependency Pattern ===")
print("See FASTAPI_EXAMPLE string above for full pattern.")


# =============================================================================
# SECTION 7: Row-Level Security (RLS) in PostgreSQL
# =============================================================================
# WHY RLS: even if the application has a bug that skips tenant filtering,
# the database enforces isolation. Defense in depth.

RLS_SQL = """
-- Enable RLS on the documents table
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

-- Force RLS even for table owner (prevents accidental bypass)
ALTER TABLE documents FORCE ROW LEVEL SECURITY;

-- Policy: users can only see rows belonging to their tenant
-- app.current_tenant is set by the application on each connection:
--   SET LOCAL app.current_tenant = 'org1';
CREATE POLICY tenant_isolation ON documents
    USING (tenant_id = current_setting('app.current_tenant'));

-- Policy: users can only update their own rows
CREATE POLICY own_rows_update ON documents
    FOR UPDATE
    USING (created_by = current_setting('app.current_user_id'));

-- In Python (with psycopg2 / asyncpg):
-- async with pool.acquire() as conn:
--     await conn.execute("SET LOCAL app.current_tenant = $1", tenant_id)
--     await conn.execute("SET LOCAL app.current_user_id = $1", user_id)
--     rows = await conn.fetch("SELECT * FROM documents")  # RLS applied!
"""

print("\n=== PostgreSQL RLS ===")
print(RLS_SQL)


# =============================================================================
# SECTION 8: Scope-Based Authorization (OAuth2 Scopes for APIs)
# =============================================================================
# WHY: OAuth2 scopes are the standard mechanism for delegated, limited access.
# A user grants a third-party app only the scopes it needs, not full account access.

@dataclass
class TokenClaims:
    """Decoded JWT/OAuth2 access token claims."""
    sub: str           # subject (user ID)
    scopes: list[str]  # e.g. ["users:read", "billing:read"]
    exp: float         # expiration unix timestamp


def require_scope(required_scope: str):
    """
    Decorator that enforces a specific OAuth2 scope is present in the token.
    Use this for API-to-API authorization where callers are services/apps,
    not end users.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(claims: TokenClaims, *args, **kwargs):
            if required_scope not in claims.scopes:
                logger.warning(
                    "SCOPE_DENIED sub=%s required=%s present=%s",
                    claims.sub, required_scope, claims.scopes,
                )
                raise PermissionError(f"Missing scope: {required_scope}")
            return func(claims, *args, **kwargs)
        return wrapper
    return decorator


@require_scope("billing:read")
def get_invoice(claims: TokenClaims, invoice_id: str) -> dict:
    return {"invoice_id": invoice_id, "amount": 100}


print("\n=== OAuth2 Scope Demo ===")
claims_ok    = TokenClaims(sub="svc-acct", scopes=["billing:read", "users:read"], exp=time.time() + 3600)
claims_bad   = TokenClaims(sub="svc-acct", scopes=["users:read"], exp=time.time() + 3600)

print(get_invoice(claims_ok, "inv-001"))
try:
    get_invoice(claims_bad, "inv-001")
except PermissionError as e:
    print(f"Denied: {e}")


# =============================================================================
# SECTION 9: Permission Delegation
# =============================================================================
# WHY: Users sometimes need to share access without giving up their own.
# Delegation creates a scoped, time-limited grant from one user to another.

@dataclass
class DelegationGrant:
    """
    A delegated permission: grantor gives grantee a subset of their permissions.
    Constraints: cannot grant more than you have, must expire.
    """
    grant_id: str
    grantor_id: str
    grantee_id: str
    permissions: set[Permission]
    expires_at: float         # unix timestamp
    resource_filter: str | None = None  # optional: limit to specific resource


class DelegationStore:
    def __init__(self):
        self._grants: list[DelegationGrant] = []

    def create_grant(
        self,
        grantor: User,
        grantee_id: str,
        permissions: set[Permission],
        ttl_seconds: int = 3600,
        resource_filter: str | None = None,
    ) -> DelegationGrant:
        # Prevent privilege escalation: grantor can only delegate what they have
        grantor_perms = set()
        for role_name in grantor.roles:
            role = ROLE_REGISTRY.get(role_name)
            if role:
                grantor_perms |= role.effective_permissions()

        illegal = permissions - grantor_perms
        if illegal:
            raise PermissionError(
                f"Cannot delegate permissions you don't have: {illegal}"
            )

        grant = DelegationGrant(
            grant_id=f"grant-{int(time.time())}",
            grantor_id=grantor.id,
            grantee_id=grantee_id,
            permissions=permissions,
            expires_at=time.time() + ttl_seconds,
            resource_filter=resource_filter,
        )
        self._grants.append(grant)
        logger.info(
            "DELEGATION_CREATED grantor=%s grantee=%s perms=%s ttl=%ds",
            grantor.id, grantee_id,
            [p.value for p in permissions], ttl_seconds,
        )
        return grant

    def effective_delegated_permissions(self, user_id: str) -> set[Permission]:
        """Return all non-expired delegated permissions for a user."""
        now = time.time()
        result: set[Permission] = set()
        for grant in self._grants:
            if grant.grantee_id == user_id and grant.expires_at > now:
                result |= grant.permissions
        return result


delegation_store = DelegationStore()

print("\n=== Delegation Demo ===")
# Alice (admin) delegates billing:read to bob temporarily
grant = delegation_store.create_grant(
    grantor=alice,
    grantee_id="bob",
    permissions={Permission.BILLING_READ},
    ttl_seconds=600,
)
delegated = delegation_store.effective_delegated_permissions("bob")
print(f"Bob's delegated perms: {[p.value for p in delegated]}")


# =============================================================================
# SECTION 10: Audit Logging for Authorization Decisions
# =============================================================================
# WHY: Audit logs are required for SOC 2, PCI-DSS, HIPAA. They also help
# debug access issues and detect insider threats.

@dataclass
class AuditEvent:
    timestamp: float
    event_type: str          # "AUTHZ_GRANTED" | "AUTHZ_DENIED" | "DELEGATION_CREATED"
    actor_id: str
    action: str
    resource: str
    decision: str            # "allow" | "deny"
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


class AuditLogger:
    """
    Structured audit logger. In production:
    - Write to append-only storage (CloudWatch, Datadog, Splunk)
    - Never allow audit logs to be deleted by application accounts
    - Include correlation ID from the original request
    """

    def log(self, event: AuditEvent) -> None:
        # Structured JSON makes logs queryable in any log aggregator
        record = {
            "ts": event.timestamp,
            "event": event.event_type,
            "actor": event.actor_id,
            "action": event.action,
            "resource": event.resource,
            "decision": event.decision,
            "reason": event.reason,
            **event.metadata,
        }
        # Use a dedicated audit logger, not the application logger,
        # so you can route it to separate, tamper-evident storage.
        logger.info("AUDIT %s", json.dumps(record))


audit = AuditLogger()

audit.log(AuditEvent(
    timestamp=time.time(),
    event_type="AUTHZ_DENIED",
    actor_id="bob",
    action="users:delete",
    resource="/api/users/carol",
    decision="deny",
    reason="missing_permission",
    metadata={"ip": "192.168.1.10", "request_id": "req-abc123"},
))

print("\n=== Audit Logging Demo (see log output above) ===")
print("Authorization architecture summary:")
print("  RBAC   -> roles + hierarchy, best for most SaaS")
print("  ABAC   -> attribute policies, best for fine-grained rules")
print("  ReBAC  -> graph relationships, best for sharing/collaboration")
print("  Casbin -> embeddable policy engine for any model")
print("  OPA    -> language-agnostic policy-as-code sidecar")
print("  RLS    -> database-level tenant isolation (defense in depth)")
print("  Scopes -> delegated API access (OAuth2 third-party apps)")
