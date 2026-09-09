# Identity & Access Management — In-Depth Reference

Dedicated deep dive on IAM/SSO mechanics — Auth & Security Notes covers
this at the application-security level; this file goes deeper into the
protocol internals and enterprise directory/identity infrastructure.


## 1. THE CORE PROTOCOLS, IN FULL

### OAuth2 — Authorization
Four grant types that actually matter in 2026: **Authorization Code + PKCE**
(the only correct choice for any user-facing app, public or confidential),
**Client Credentials** (machine-to-machine, no user involved — a service
authenticating as itself), **Device Code** (TVs/CLIs with no browser —
display a code, user approves on a second device), and **Refresh Token**
(exchanging a refresh token for a new access token without re-authenticating).
The **Implicit** and **Resource Owner Password Credentials** grants are
DEPRECATED — both leaked in ways PKCE and the code flow specifically fix;
seeing either in a modern codebase is a real finding, not a style choice.

```
Authorization Code + PKCE flow:
1. Client generates code_verifier (random), derives code_challenge = SHA256(code_verifier)
2. Client redirects user to /authorize?...&code_challenge=X&code_challenge_method=S256
3. User authenticates at the IdP, IdP redirects back with an authorization `code`
4. Client POSTs to /token with { code, code_verifier } (NOT code_challenge)
5. IdP verifies SHA256(code_verifier) == the code_challenge from step 2, issues tokens
```

### OIDC — Authentication (built on OAuth2)
Adds the **ID Token** (a signed JWT with `sub`, `iss`, `aud`, `exp`, and
identity claims like `email`/`name`) and standardized endpoints:
`/.well-known/openid-configuration` (discovery — tells a client where every
other endpoint lives), `/userinfo` (fetch more claims using an access token).
**Always validate**: signature (against the IdP's published JWKS), `iss`
matches the expected issuer, `aud` matches YOUR client ID, `exp` hasn't
passed. Skipping any of these turns JWT validation into "trust whatever
JSON showed up," a real and recurring vulnerability class.

### SAML 2.0 — XML-based, enterprise legacy but still everywhere
An `<AuthnRequest>` is sent to the IdP; the IdP returns a signed (and
optionally encrypted) `<Response>` containing an `<Assertion>` with the
user's identity and attributes, POSTed back to the Service Provider via a
browser form-post. Still the default in many large enterprises (Okta/ADFS/
PingFederate deployments predating OIDC's rise) — expect to integrate with
it even in an otherwise modern stack, especially in enterprise B2B SaaS
where the CUSTOMER's IdP dictates the protocol, not your preference.

### LDAP — the directory protocol underneath most enterprise IdPs
A hierarchical directory (Distinguished Names like
`cn=jdoe,ou=Engineering,dc=corp,dc=com`) queried via LDAP binds/searches.
Active Directory speaks LDAP (among other protocols) — this is the "actual
database of users/groups" that Okta/Azure AD/SSO layers often sit in front
of or sync from, rather than replace outright, in a large enterprise.


## 2. AUTHORIZATION MODELS

- **RBAC** (Role-Based Access Control) — permissions attached to roles,
  users assigned to roles. Simple, auditable, breaks down when you need
  fine-grained per-resource rules ("edit only YOUR OWN documents").
- **ABAC** (Attribute-Based Access Control) — decisions based on
  attributes of the user, resource, and context (`user.department ==
  resource.department AND time.hour BETWEEN 9 AND 17`) — more expressive,
  harder to audit/reason about at a glance.
- **ReBAC** (Relationship-Based Access Control) — permissions derived from
  RELATIONSHIPS in a graph (Google Zanzibar's model, also Google Docs'
  actual sharing model: "can edit if owner OR explicitly shared with edit
  permission OR member of a group that was shared with") — the model
  behind most modern fine-grained-permission SaaS products; **OpenFGA** and
  **Ory Keto** are open-source Zanzibar-inspired implementations.
- **PBAC/Policy-as-code** — OPA/Rego or Cedar (AWS's policy language,
  used in Amazon Verified Permissions) — express authorization logic as
  reviewable, testable POLICY rather than scattered `if` statements
  throughout application code.


## 3. ENTERPRISE IDENTITY INFRASTRUCTURE

- **Active Directory / Azure AD (Entra ID)** — the dominant enterprise
  directory; on-prem AD historically, Entra ID is Microsoft's cloud-native
  evolution, and most large enterprises run a hybrid of both, synced via
  Azure AD Connect.
- **SCIM provisioning** — automates account creation/update/deactivation
  across every connected app the moment HR marks someone as joined/left —
  the piece that actually closes the "ex-employee still has access" gap
  that manual deprovisioning reliably misses.
- **Just-in-time (JIT) access** — instead of standing elevated permissions,
  a user requests temporary elevated access (with approval/audit trail)
  that auto-expires — dramatically shrinks the attack surface of "an admin
  account that's always privileged," and is a specific, common SOC2/audit
  finding remediation.
- **Privileged Access Management (PAM)** — CyberArk, HashiCorp Boundary —
  vaulting and time-boxing access to the MOST sensitive credentials/systems
  (root database access, production SSH) beyond what general IAM covers.


## 4. NICHE BUT REAL

- **Token binding / DPoP (Demonstrating Proof-of-Possession)** — cryptographically
  binds an access token to the specific client that requested it, so a
  stolen token alone isn't usable by an attacker without also possessing
  the corresponding private key — an emerging mitigation for token theft
  that plain bearer tokens are fundamentally exposed to.
- **Continuous access evaluation** — modern IdPs (Azure AD Conditional
  Access, Okta) can revoke a session in near-real-time (not just at next
  token expiry) when risk signals change — impossible session ID, sign-in
  from an impossible travel location — a meaningfully stronger security posture
  than static token expiry alone provides.
- **Identity federation across organizations** — a partner company's users
  accessing your systems via THEIR OWN IdP, trusted via a federation
  agreement, without ever creating a local account — the mechanism behind
  most B2B SaaS "login with your company SSO" flows.
- **Shadow IT / unmanaged app discovery** — CASB (Cloud Access Security
  Broker) tools discover apps employees are using that were never
  centrally provisioned through SSO at all — a real, ongoing enterprise
  IAM blind spot.
