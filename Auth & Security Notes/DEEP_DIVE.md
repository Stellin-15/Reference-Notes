# Auth & Security — Principal Engineer Deep Dive

Companion to the existing L01-L0n lessons. Two-part: narrative depth on
core topics, then a comprehensive common-to-uncommon tool/concept reference.


## Authentication Protocols: OAuth2, OIDC, SAML

**Beyond the lesson**: OAuth2 is an AUTHORIZATION protocol, not
authentication — it was never designed to answer "who is this user," only
"what is this token allowed to do." OIDC (OpenID Connect) is a thin
identity layer BUILT ON TOP of OAuth2 specifically to add authentication
back in (the ID token, a signed JWT with user identity claims, versus
OAuth2's access token, which is just an opaque authorization credential).
Conflating the two is one of the most common real security-review findings
— an app trusting an OAuth2 access token AS IF it proves identity, when the
access token was never meant to carry that guarantee.

**Worked example**: The Authorization Code flow with PKCE (Proof Key for
Code Exchange) — now the standard for ANY public client (mobile app, SPA),
not just mobile as originally designed. A random `code_verifier` is
generated client-side, its hash (`code_challenge`) sent with the initial
auth request; the actual `code_verifier` is only sent when exchanging the
authorization code for tokens — this defeats authorization-code
interception attacks because an attacker who steals the code alone can't
complete the exchange without the verifier that only the legitimate client generated.

**Tradeoff table**:
| Protocol | Solves | Common use |
|---|---|---|
| OAuth2 | Delegated authorization (app X can access resource Y on my behalf) | "Login with Google" granting calendar access |
| OIDC | Authentication (who is this user) | SSO login flows |
| SAML | XML-based enterprise SSO, older | Legacy enterprise IdPs (Okta, ADFS), still common in large orgs |

**Interview Q&A**:
- *Q: Why shouldn't you use an OAuth2 access token to identify a user in your own API?* A: An access token's audience/scope was issued for a SPECIFIC resource server and says nothing verified about identity — the correct pattern is validating the OIDC ID token's signature and claims, or exchanging the access token for user info via the provider's userinfo endpoint.


## Session Management & Token Handling

**Beyond the lesson**: Storing a JWT in localStorage is a common, real XSS
exposure — any injected script can read localStorage and exfiltrate the
token; an httpOnly, Secure, SameSite cookie CANNOT be read by JavaScript at
all, closing that exact exfiltration path (at the cost of needing CSRF
protection instead, since cookies auto-attach to requests).

**Worked example**: Refresh token rotation — issuing a NEW refresh token
every time one is used, and invalidating the old one, so a stolen refresh
token that gets used by an attacker AND the legitimate user creates a
detectable "reuse of an already-rotated token" signal the backend can
respond to by revoking the entire token family immediately.

**Interview Q&A**:
- *Q: Access token vs refresh token — why two tokens instead of one long-lived one?* A: Access tokens are short-lived (minutes) and sent with every request, so a leak has a small blast-radius window; refresh tokens are long-lived but sent RARELY (only to refresh) and can be stored/rotated more carefully — splitting the two lets you optimize each for its actual exposure risk.


## Password Storage & Cryptographic Hashing

**Beyond the lesson**: bcrypt/scrypt/Argon2 are deliberately SLOW —
that's the entire point. A fast hash (SHA-256 alone) lets an attacker with
a stolen hash database try billions of guesses per second on commodity GPU
hardware; a deliberately slow, memory-hard function (Argon2id specifically)
makes large-scale offline cracking computationally/economically infeasible
even after a breach, by design.

**Interview Q&A**:
- *Q: Why is Argon2id generally preferred over bcrypt for new systems?* A: Argon2 is memory-hard (requires significant RAM per hash attempt, not just CPU time), which specifically defeats GPU/ASIC-based cracking that can parallelize CPU-bound bcrypt attempts far more cheaply than memory-bound ones.


## COMPREHENSIVE TOOL & CONCEPT REFERENCE — COMMON TO UNCOMMON

### Identity providers & SSO in the real world
- **Okta / Azure AD (Entra ID) / Auth0 / Ping Identity** — the dominant
  commercial identity providers; most companies buy one rather than
  building auth from scratch, specifically to offload the compliance/
  security burden of correctly implementing OAuth2/OIDC/SAML/MFA.
- **Keycloak** — the dominant open-source, self-hostable alternative when
  a company needs full control (data residency, cost at extreme scale) instead of a SaaS IdP.
- **SCIM** (System for Cross-domain Identity Management) — the standard
  protocol for automatically provisioning/deprovisioning user accounts
  across systems when someone joins/leaves a company — the unglamorous but
  critical piece that actually removes access on offboarding, at scale,
  without manual IT tickets.

### MFA & modern authentication
- **TOTP** (Time-based One-Time Password, Google Authenticator-style) —
  the most common MFA factor; vulnerable to phishing (a fake login page
  can relay a stolen TOTP code in real time).
- **WebAuthn / FIDO2 / Passkeys** — phishing-RESISTANT by design: the
  cryptographic challenge is bound to the origin domain, so a credential
  simply won't work on a look-alike phishing site — this is the direction
  the entire industry is moving, and increasingly a real interview topic.
- **Push-based MFA** (Duo, Okta Verify) — simpler UX than TOTP, but
  vulnerable to "MFA fatigue" attacks (spam approval requests until a
  tired user accidentally taps approve) — a real, named attack class behind
  several major 2022-2023 breaches.

### Secrets management
- **HashiCorp Vault** — dynamic, short-lived credentials, encryption-as-a-
  service, the most feature-complete self-hosted option (see CICD Notes section 10).
- **Cloud-native**: AWS Secrets Manager, Azure Key Vault, GCP Secret
  Manager — simpler, sufficient for most companies not needing Vault's
  dynamic-secrets machinery.
- **SOPS / sealed-secrets** — encrypting secrets so they're safe to commit
  to Git (see CICD Notes section 10 / Kubernetes Notes for sealed-secrets specifically).

### Application security testing categories
- **SAST** (Static Application Security Testing) — Semgrep, SonarQube,
  CodeQL — scans source code for known-vulnerable patterns WITHOUT running it.
- **DAST** (Dynamic Application Security Testing) — OWASP ZAP, Burp Suite
  Enterprise — scans a RUNNING application by actually attacking it.
- **SCA** (Software Composition Analysis) — Snyk, Dependabot, `npm audit` —
  scans dependencies for known CVEs (ties to CICD Notes section 13).
- **IAST** (Interactive AST) — instruments a running app during real test
  execution to catch vulnerabilities SAST/DAST alone miss — less common,
  found mostly in larger security-mature orgs.

### Network & infrastructure security
- **Zero Trust Architecture** — "never trust, always verify," every
  request authenticated/authorized regardless of network location — the
  named successor to the old perimeter-firewall model; concretely
  implemented via mTLS everywhere (service mesh) + strict IAM, not a single product.
- **WAF** (Web Application Firewall) and **DDoS protection** (Cloudflare,
  AWS Shield) — see Cloud Platforms deep dive for the cloud-native tooling side.
- **CSPM** (Cloud Security Posture Management) — Wiz, Orca, Prisma Cloud —
  continuously scans cloud accounts for misconfigurations at a scale/depth
  beyond native tools like AWS Config alone; one of the fastest-growing
  security-tooling categories in the current market.

### Compliance-adjacent (see also new Compliance & Governance domain)
- **SOC2 / ISO 27001 / PCI-DSS / HIPAA** — the compliance frameworks that
  directly shape engineering decisions (encryption at rest, access logging,
  data retention) — worth recognizing by name even without owning compliance directly.
- **Data Loss Prevention (DLP)** tooling — scans outbound traffic/storage
  for sensitive data patterns (credit card numbers, SSNs) leaving controlled boundaries.


## NICHE BUT REAL

- **Confused deputy problem** — a service with legitimate elevated
  privileges gets tricked into performing an action on behalf of an
  attacker who couldn't do it directly (classic SSRF-to-cloud-metadata is
  one instance of this general pattern — see Ethical Hacking Notes section 14).
- **JWT algorithm confusion attacks** — see Ethical Hacking Notes section
  18 for the RS256/HS256 key-confusion attack in full.
- **Timing attacks on comparison functions** — a naive `==` string
  comparison of a secret/token leaks timing information about how many
  characters matched before failing; constant-time comparison functions
  (`hmac.compare_digest` in Python, `crypto.timingSafeEqual` in Node) exist specifically to prevent this.
- **Supply chain attacks via typosquatting** — malicious packages named
  almost identically to popular ones (`reqeusts` vs `requests`) — a real,
  recurring npm/PyPI attack vector, part of why SCA tooling and lockfile
  integrity checks matter beyond just "known CVE" scanning.
- **Security champions programs** — embedding a security-trained engineer
  WITHIN each product team (rather than centralizing all security review in
  one bottlenecked team) — the organizational-scaling answer once a
  security team can no longer review every PR/design doc directly.
