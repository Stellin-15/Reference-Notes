# =============================================================================
# WHAT: Security Architecture — Defense in Depth, Zero Trust, Supply Chain,
#       Container Security, Threat Modeling, and Incident Response
# WHY:  Writing secure individual functions is necessary but not sufficient.
#       You need an architecture that remains secure when any single control
#       fails. Understanding the full stack — from STRIDE threat models to
#       SOC 2 audits — separates junior from senior backend engineers.
# LEVEL: Advanced
# =============================================================================

# CONCEPT OVERVIEW
# ----------------
# Security architecture is the design of overlapping controls such that:
#   - A single failure does not cause a breach (defense in depth)
#   - No implicit trust is granted to any network segment or identity (zero trust)
#   - The blast radius of a compromise is bounded by least privilege
#   - Threats are identified systematically before code is written (STRIDE)
#   - The software supply chain is verifiable (SBOM, Sigstore, SLSA)
#
# Layers of defense (perimeter → data):
#   Layer 1: Perimeter  — WAF, DDoS protection, CDN, IP allowlists
#   Layer 2: Network    — VPC, security groups, network policies, TLS
#   Layer 3: Host       — OS hardening, seccomp, AppArmor, non-root
#   Layer 4: Application — input validation, AuthN/AuthZ, rate limiting
#   Layer 5: Data       — encryption at rest, RLS, field-level encryption

# PRODUCTION USE CASE
# -------------------
# SaaS platform handling PII and payment data, pursuing SOC 2 Type II.
# Every architectural decision is made against a STRIDE threat model.
# CI pipeline runs SBOM generation, container scanning, and dependency audit.
# Incidents trigger a playbook that bounds damage within 15 minutes.

# COMMON MISTAKES
# ---------------
# 1. Treating security as a final "security review" step instead of
#    integrating it from the design phase (shift left).
# 2. Relying solely on perimeter security (VPN = secure) — zero trust fixes this.
# 3. Ignoring supply chain: your app is only as secure as its dependencies.
# 4. Running containers as root in production.
# 5. Skipping threat modeling — you can't defend against threats you haven't named.
# 6. No incident response plan — the breach itself causes less damage than the chaos.

import os
import json
import time
import hashlib
import logging
import subprocess
import enum
from dataclasses import dataclass, field
from typing import Any

# Third-party (install as needed):
# pip install pip-audit bandit safety cryptography

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# =============================================================================
# SECTION 1: Defense in Depth
# =============================================================================

DEFENSE_IN_DEPTH = """
Defense in Depth — Layered Controls:

  LAYER 1: PERIMETER
    - CloudFlare / AWS Shield — DDoS mitigation
    - WAF (Web Application Firewall) — block SQLi, XSS, path traversal
    - IP allowlisting for admin endpoints (/admin/* only from VPN range)
    - Rate limiting at the edge (e.g., 100 req/s per IP)
    - Geographic restrictions where legally appropriate

  LAYER 2: NETWORK
    - VPC with private subnets (DB, cache — no direct internet access)
    - Security groups: least-privilege ingress (only known ports/sources)
    - Kubernetes NetworkPolicy: deny-all default, explicit allow
    - TLS everywhere (mTLS for service-to-service, TLS 1.3 externally)
    - VPN for operator access to production (not SSH from the internet)

  LAYER 3: HOST / RUNTIME
    - Container: non-root user, read-only root filesystem
    - seccomp: whitelist system calls, block ptrace/mount/etc.
    - AppArmor / SELinux: MAC policy restricts file access by process
    - Immutable infrastructure: no SSH in prod; replace, don't patch
    - Host-based intrusion detection (Falco, AWS GuardDuty)

  LAYER 4: APPLICATION
    - Input validation (type, length, format, business rules)
    - Parameterized queries (never string interpolation in SQL)
    - Authentication (MFA required for privileged actions)
    - Authorization (RBAC/ABAC at every resource, not just endpoints)
    - Rate limiting per user/IP/API key
    - CORS, CSP, security headers

  LAYER 5: DATA
    - Encryption at rest (AES-256-GCM, cloud KMS-managed keys)
    - Encryption in transit (TLS 1.3)
    - Row-level security in PostgreSQL
    - Field-level encryption for PII (SSN, card numbers)
    - Data minimization: don't store what you don't need
    - Backups encrypted, tested for restore, off-site

Each layer fails independently. A WAF bypass doesn't defeat AuthZ.
A compromised pod doesn't read another tenant's encrypted DB rows.
"""

print(DEFENSE_IN_DEPTH)


# =============================================================================
# SECTION 2: Zero-Trust Model
# =============================================================================

ZERO_TRUST_PRINCIPLES = """
Zero Trust: "Never Trust, Always Verify, Assume Breach"

Traditional perimeter model (broken):
  "Anything inside the VPN is trusted."
  -> A single compromised internal machine owns everything.

Zero-trust principles:
  1. Verify explicitly    — authenticate and authorize every request,
                            regardless of network origin.
  2. Least privilege      — every identity (user, service, pod) gets the
                            minimum access needed for the task.
  3. Assume breach        — design for "the attacker is already inside."
                            Segment, log, and alert accordingly.

Implementation:
  Identity Provider (Okta, Auth0, AWS IAM)
    Every human and service has a unique, auditable identity.

  Policy Engine (OPA, AWS IAM, Google IAP)
    Every request is evaluated: who, what, resource, context.

  Service Mesh mTLS (Istio)
    Every pod-to-pod call is authenticated via SPIFFE identity.

  Device Posture (MDM, Kolide, CrowdStrike)
    Human access requires a managed, compliant device.

  Continuous Monitoring
    Anomaly detection on auth patterns, API calls, egress.
"""

print("\n=== Zero Trust ===")
print(ZERO_TRUST_PRINCIPLES)


# =============================================================================
# SECTION 3: Security Headers
# =============================================================================

def build_security_headers(
    csp_policy: dict[str, list[str]] | None = None,
    hsts_max_age: int = 31536000,
) -> dict[str, str]:
    """
    Build a complete set of security HTTP response headers.
    Add these via middleware on every response.

    Args:
        csp_policy:   Content Security Policy directives.
        hsts_max_age: HSTS max-age in seconds (1 year default).
    """
    # Default restrictive CSP — customize per application
    default_csp = {
        "default-src":  ["'self'"],
        "script-src":   ["'self'"],           # no inline scripts, no eval
        "style-src":    ["'self'", "'unsafe-inline'"],  # often needed for CSS-in-JS
        "img-src":      ["'self'", "data:", "https:"],
        "font-src":     ["'self'"],
        "connect-src":  ["'self'"],           # XHR/fetch destinations
        "frame-src":    ["'none'"],           # prevent clickjacking via iframe
        "object-src":   ["'none'"],           # no Flash, no plugins
        "base-uri":     ["'self'"],           # prevent base tag injection
        "form-action":  ["'self'"],           # where forms can submit
        "upgrade-insecure-requests": [],      # browser upgrades http:// to https://
    }

    policy = csp_policy or default_csp

    # Serialize CSP dict to header string
    csp_str = "; ".join(
        f"{directive} {' '.join(sources)}" if sources else directive
        for directive, sources in policy.items()
    )

    return {
        # Content Security Policy — mitigates XSS by restricting resource origins
        "Content-Security-Policy": csp_str,

        # Prevent browsers from MIME-sniffing responses (e.g., treating text/plain as JS)
        "X-Content-Type-Options": "nosniff",

        # Clickjacking protection — also set CSP frame-ancestors
        "X-Frame-Options": "DENY",

        # Reflected XSS filter in old browsers (superseded by CSP but harmless)
        "X-XSS-Protection": "1; mode=block",

        # HSTS — force HTTPS for 1 year, including subdomains
        "Strict-Transport-Security": f"max-age={hsts_max_age}; includeSubDomains; preload",

        # Control Referer header sent to other origins
        "Referrer-Policy": "strict-origin-when-cross-origin",

        # Restrict browser features accessible to this page
        "Permissions-Policy": (
            "camera=(), "          # deny camera access
            "microphone=(), "      # deny mic access
            "geolocation=(), "     # deny location
            "payment=(self), "     # payment API only on same origin
            "usb=()"               # deny USB device access
        ),

        # Remove server fingerprint info
        "Server": "app",

        # Prevent caching of sensitive pages
        "Cache-Control": "no-store",
    }


print("=== Security Headers ===")
headers = build_security_headers()
for name, value in headers.items():
    print(f"  {name}: {value[:80]}{'...' if len(value) > 80 else ''}")


# Starlette/FastAPI middleware for security headers
SECURITY_HEADERS_MIDDLEWARE = '''
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import FastAPI

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, headers: dict[str, str]):
        super().__init__(app)
        self._headers = headers

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for name, value in self._headers.items():
            response.headers[name] = value
        return response

app = FastAPI()
app.add_middleware(SecurityHeadersMiddleware, headers=build_security_headers())
'''

print(SECURITY_HEADERS_MIDDLEWARE)


# =============================================================================
# SECTION 4: Supply Chain Security — SBOM, Sigstore, SLSA
# =============================================================================

SUPPLY_CHAIN_NOTES = """
Supply Chain Security — the "Log4Shell problem":
  Your application's attack surface includes ALL of its dependencies.
  A vulnerability in a transitive dep can compromise your entire system.

SBOM (Software Bill of Materials):
  A machine-readable inventory of every component in your software.
  Formats: CycloneDX (JSON/XML), SPDX (ISO standard).

  Generate for Python:
    pip install cyclonedx-bom
    cyclonedx-py poetry -o sbom.json   # from poetry.lock
    cyclonedx-py pip -r requirements.txt -o sbom.json

  Generate for containers:
    syft <image>:<tag> -o cyclonedx-json > sbom.json
    trivy image --format cyclonedx <image>:<tag>

  WHY: SBOM lets you answer "are we affected by CVE-2024-XXXX?" instantly
       without manually checking every dependency.

Sigstore / cosign — Container Image Signing:
  Prevents "image poisoning" — an attacker replacing your image in the registry.

  Sign after CI build (keyless signing via OIDC):
    cosign sign --yes <registry>/<image>@<digest>

  Verify before deploy:
    cosign verify --certificate-identity <ci-oidc-subject> \\
                  --certificate-oidc-issuer https://token.actions.githubusercontent.com \\
                  <registry>/<image>@<digest>

  Kubernetes admission webhook (Sigstore Policy Controller):
    Rejects unsigned or untrusted images at deploy time.

SLSA Framework (Supply-chain Levels for Software Artifacts):
  Levels 1-4 of build provenance guarantees:
    L1: Signed provenance (who built it, from what source)
    L2: Hosted build service (GitHub Actions, not a laptop)
    L3: Hardened build (isolated, ephemeral build environment)
    L4: Two-party review of all changes (very high bar)

  For most teams: SLSA L2 (GitHub Actions + Sigstore) is the target.
"""

print("\n=== Supply Chain Security ===")
print(SUPPLY_CHAIN_NOTES)


# =============================================================================
# SECTION 5: Container Security
# =============================================================================

SECURE_DOCKERFILE = """
# Secure Dockerfile patterns:

# 1. Multi-stage build — final image contains no build tools or source code
FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS final

# 2. Non-root user — never run as UID 0 in production
#    Attacker who escapes the app can't write to /etc or install packages
RUN groupadd --gid 1001 appgroup && \\
    useradd --uid 1001 --gid appgroup --no-create-home appuser

# 3. Only copy what's needed — no .git, tests, dev configs
COPY --from=builder /install /usr/local
COPY --chown=appuser:appgroup src/ /app/

WORKDIR /app

# 4. Drop capabilities before switching user
# (Use Kubernetes securityContext for fine-grained capability control)

USER appuser     # switch to non-root before CMD

# 5. Read-only root filesystem (enforce in K8s securityContext)
# In K8s: securityContext.readOnlyRootFilesystem: true

EXPOSE 8080
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
"""

CONTAINER_SECURITY_K8S = """
# Kubernetes Pod Security Context — hardened configuration
apiVersion: v1
kind: Pod
spec:
  securityContext:
    runAsNonRoot: true           # admission controller rejects root containers
    runAsUser: 1001
    runAsGroup: 1001
    fsGroup: 1001                # volume files owned by this GID
    seccompProfile:
      type: RuntimeDefault       # Docker default seccomp profile (blocks ~300 syscalls)

  containers:
    - name: app
      image: registry.example.com/app:v1.2.3@sha256:abc...   # pinned digest!
      securityContext:
        allowPrivilegeEscalation: false   # no sudo, no setuid binaries
        readOnlyRootFilesystem: true       # attacker cannot write to disk
        privileged: false                  # no host namespace access
        capabilities:
          drop: ["ALL"]                    # drop all Linux capabilities
          add: ["NET_BIND_SERVICE"]        # add back only what's needed (port <1024)
      resources:
        limits:
          cpu: "500m"
          memory: "256Mi"
        requests:
          cpu: "100m"
          memory: "128Mi"
      volumeMounts:
        - name: tmp
          mountPath: /tmp           # writable tmp (since root fs is read-only)
        - name: app-logs
          mountPath: /var/log/app

  volumes:
    - name: tmp
      emptyDir: {}                  # ephemeral, not persisted
    - name: app-logs
      emptyDir: {}

  # Do NOT mount the service account token if the app doesn't use K8s API
  automountServiceAccountToken: false
"""

print("\n=== Container Security ===")
print("Key controls:")
print("  - Non-root user (UID 1001)")
print("  - readOnlyRootFilesystem: true")
print("  - allowPrivilegeEscalation: false")
print("  - capabilities: drop ALL")
print("  - seccomp: RuntimeDefault")
print("  - Pinned image digest (not :latest)")
print("\nFull Dockerfile example in SECURE_DOCKERFILE string.")
print("Full K8s spec example in CONTAINER_SECURITY_K8S string.")


# =============================================================================
# SECTION 6: Dependency Audit Pipeline
# =============================================================================

DEPENDENCY_AUDIT = """
Dependency audit in CI (GitHub Actions example):

  # .github/workflows/security.yml
  - name: pip-audit (CVE scan)
    run: |
      pip install pip-audit
      pip-audit --requirement requirements.txt --format json --output audit.json
      # Fail CI if any HIGH or CRITICAL CVEs
      pip-audit --requirement requirements.txt --fail-on HIGH

  - name: Bandit (static analysis for Python security issues)
    run: |
      pip install bandit
      bandit -r src/ -ll -f json -o bandit-report.json
      # -ll = report LOW and above; remove -ll to fail on any finding

  - name: Trivy (container image vulnerability scan)
    run: |
      trivy image --exit-code 1 --severity HIGH,CRITICAL \\
        --format sarif --output trivy.sarif \\
        ${{ env.IMAGE }}

  - name: Upload SARIF to GitHub Code Scanning
    uses: github/codeql-action/upload-sarif@v2
    with:
      sarif_file: trivy.sarif   # appears in Security tab

Automation:
  Dependabot (GitHub): automatically opens PRs for outdated/vulnerable deps.
  Renovate: similar, more configurable (groups deps, schedules updates).
  pip-audit in pre-commit: blocks commits that introduce known-vulnerable deps.
"""

print("\n=== Dependency Audit Pipeline ===")
print(DEPENDENCY_AUDIT)


def parse_pip_audit_output(audit_json: str) -> list[dict[str, Any]]:
    """
    Parse pip-audit JSON output and return findings.
    Use in CI to fail the build on critical vulnerabilities.
    Integrate with a Slack webhook to notify the security channel.
    """
    try:
        data = json.loads(audit_json)
    except json.JSONDecodeError:
        return []

    findings = []
    for dep in data.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            findings.append({
                "package": dep.get("name"),
                "version": dep.get("version"),
                "vuln_id": vuln.get("id"),         # e.g. "PYSEC-2023-999"
                "description": vuln.get("description", "")[:120],
                "fix_versions": vuln.get("fix_versions", []),
            })
    return findings


# =============================================================================
# SECTION 7: Threat Modeling — STRIDE
# =============================================================================

class STRIDEThreat(enum.Enum):
    """
    STRIDE: Microsoft's threat categorization framework.
    Each letter maps to a category of security threat.
    Use this during design reviews — before any code is written.
    """
    SPOOFING               = "S"   # Attacker pretends to be another identity
    TAMPERING              = "T"   # Attacker modifies data or code
    REPUDIATION            = "R"   # User denies performing an action
    INFORMATION_DISCLOSURE = "I"   # Data exposed to unauthorized parties
    DENIAL_OF_SERVICE      = "D"   # Service made unavailable
    ELEVATION_OF_PRIVILEGE = "E"   # Gaining permissions beyond what's granted


@dataclass
class Threat:
    """
    A single identified threat in a threat model.
    Product of a threat modeling session (usually 2-4 hours with the team).
    Use a data-flow diagram (DFD) to enumerate all components and trust boundaries,
    then apply STRIDE to each element.
    """
    id: str                        # e.g. "T-001"
    category: STRIDEThreat
    component: str                 # which part of the system
    description: str               # what the attacker does
    likelihood: int                # 1-5 (1 = very unlikely, 5 = very likely)
    impact: int                    # 1-5 (1 = minor, 5 = catastrophic)
    mitigations: list[str]         # controls that reduce likelihood or impact
    status: str = "open"           # "open" | "mitigated" | "accepted"

    @property
    def risk_score(self) -> int:
        """Risk = likelihood × impact (1–25). Prioritize high scores first."""
        return self.likelihood * self.impact


# Example threat model for a payment API
PAYMENT_API_THREATS = [
    Threat(
        id="T-001",
        category=STRIDEThreat.SPOOFING,
        component="API Gateway",
        description="Attacker replays a stolen JWT to impersonate a user",
        likelihood=3, impact=5,
        mitigations=[
            "Short JWT expiry (15 minutes)",
            "Refresh token rotation (single-use)",
            "jti (JWT ID) claim stored and checked for replay",
            "Bind JWT to client IP or device fingerprint (DPoP)",
        ],
    ),
    Threat(
        id="T-002",
        category=STRIDEThreat.TAMPERING,
        component="Order Service",
        description="Attacker modifies the price field in a request body",
        likelihood=4, impact=5,
        mitigations=[
            "Server always re-fetches price from product catalog",
            "Never trust client-supplied prices",
            "Signed order objects verified with HMAC before processing",
        ],
    ),
    Threat(
        id="T-003",
        category=STRIDEThreat.INFORMATION_DISCLOSURE,
        component="Error Responses",
        description="Stack traces in API errors reveal DB schema and internal paths",
        likelihood=4, impact=2,
        mitigations=[
            "Generic error messages in production (no stack traces in response)",
            "Error details in structured logs only, routed to Sentry",
            "Error IDs in response body (correlate to internal log entry)",
        ],
    ),
    Threat(
        id="T-004",
        category=STRIDEThreat.DENIAL_OF_SERVICE,
        component="Payment Endpoint",
        description="Attacker floods payment endpoint exhausting DB connections",
        likelihood=3, impact=4,
        mitigations=[
            "Rate limit: 5 payment attempts per user per minute",
            "Global rate limit: 1000 req/s at CDN (CloudFlare)",
            "Circuit breaker on DB connection pool (fail open with 503)",
            "CAPTCHA after 3 consecutive failed attempts",
        ],
    ),
    Threat(
        id="T-005",
        category=STRIDEThreat.ELEVATION_OF_PRIVILEGE,
        component="Admin API",
        description="IDOR: attacker changes user_id in request to access another user's data",
        likelihood=3, impact=5,
        mitigations=[
            "Always derive user_id from authenticated JWT, never from request body",
            "Row-level security in PostgreSQL as second enforcement layer",
            "Automated IDOR tests in CI (user A cannot read user B's resources)",
        ],
    ),
    Threat(
        id="T-006",
        category=STRIDEThreat.REPUDIATION,
        component="Payment Service",
        description="User denies initiating a charge; no audit trail to prove otherwise",
        likelihood=2, impact=4,
        mitigations=[
            "Immutable audit log with actor ID, timestamp, IP, and action",
            "Signed audit events (HMAC or asymmetric signature)",
            "Idempotency keys stored with each request for replay prevention",
        ],
    ),
]

print("\n=== STRIDE Threat Model ===")
sorted_threats = sorted(PAYMENT_API_THREATS, key=lambda t: t.risk_score, reverse=True)
for t in sorted_threats:
    print(
        f"[{t.id}] {t.category.name:<25} "
        f"Risk={t.risk_score:2d} ({t.likelihood}x{t.impact}) "
        f"— {t.description[:55]}"
    )
    print(f"         Mitigations: {t.mitigations[0][:70]}")


# =============================================================================
# SECTION 8: Penetration Testing Basics
# =============================================================================

PENTEST_NOTES = """
Penetration Testing Phases:

  1. RECONNAISSANCE (passive)
     - OSINT: LinkedIn, job postings, GitHub, Shodan, censys.io
     - DNS enumeration: subdomains, MX records, SPF/DKIM
     - Tools: amass, subfinder, theHarvester, shodan

  2. SCANNING (active)
     - Port scanning: nmap -sV -A target.example.com
     - Web app fingerprinting: whatweb, wappalyzer
     - Directory bruteforce: ffuf, gobuster, dirsearch
     - Tools: nmap, masscan, nikto

  3. EXPLOITATION
     - OWASP ZAP: automated DAST web app scanner
       zap-cli quick-scan --self-contained -u https://api.example.com
     - Burp Suite: intercept, modify, replay HTTP requests
       Use Repeater for manual testing, Scanner for automated DAST
     - SQLmap: automated SQL injection testing
     - Metasploit: exploit framework (only in authorized scope!)

  4. POST-EXPLOITATION (within authorized scope only)
     - Privilege escalation: linpeas, winpeas
     - Lateral movement: BloodHound for AD path analysis
     - Data exfiltration test: can attacker reach PII stores?

  5. REPORTING
     - Executive summary (risk, business impact)
     - Technical findings with CVSS severity score
     - Reproducible steps and evidence screenshots
     - Remediation recommendations with priority ordering

For backend engineers day-to-day:
  Run OWASP ZAP in CI as a DAST job against staging.
  Use Burp Suite Community in development to understand your API surface.
  Engage external pentesters annually (required for SOC 2).
"""

print("\n=== Penetration Testing ===")
print(PENTEST_NOTES)

# OWASP ZAP CI integration
OWASP_ZAP_CI = """
# GitHub Actions: OWASP ZAP DAST scan against staging
- name: OWASP ZAP API Scan
  uses: zaproxy/action-api-scan@v0.7.0
  with:
    target: "https://staging.api.example.com/openapi.json"
    rules_file_name: ".zap/rules.tsv"   # suppress known false positives
    fail_action: true                   # fail CI on HIGH/MEDIUM findings
    cmd_options: "-a"                   # include all HTTP methods
"""
print(OWASP_ZAP_CI)


# =============================================================================
# SECTION 9: Incident Response Playbook
# =============================================================================

@dataclass
class IncidentSeverity:
    """Severity tiers for incident classification."""
    level: int           # 1 (critical) -> 4 (low)
    label: str
    response_time: str
    examples: list[str]


SEVERITY_TIERS = [
    IncidentSeverity(1, "CRITICAL", "15 minutes", [
        "Active data breach (PII/payment data confirmed exfiltrated)",
        "Ransomware / cryptolocker active in environment",
        "Complete service outage affecting all users",
        "Compromised production credentials being actively used",
    ]),
    IncidentSeverity(2, "HIGH", "1 hour", [
        "Suspected unauthorized access (not yet confirmed breach)",
        "Partial outage affecting >25% of users",
        "Vulnerable dependency actively exploited in the wild",
    ]),
    IncidentSeverity(3, "MEDIUM", "4 hours", [
        "Vulnerability discovered internally, not yet exploited",
        "Anomalous access patterns (possible account takeover)",
        "Failed DDoS mitigated by CDN, no user impact",
    ]),
    IncidentSeverity(4, "LOW", "Next business day", [
        "Dependency CVE with no known public exploit",
        "Misconfigured security header found in scan",
        "Single failed auth event from unexpected geography",
    ]),
]

INCIDENT_PLAYBOOK = """
INCIDENT RESPONSE PLAYBOOK (Sev-1: Data Breach)

PHASE 1: DETECT & ALERT (0-15 min)
  [ ] Alert triggers in PagerDuty / OpsGenie
  [ ] On-call engineer acknowledges within SLA
  [ ] Open war-room (Slack #incident-YYYY-MM-DD or Zoom bridge)
  [ ] Assign roles:
        Incident Commander  — coordinates, makes decisions
        Tech Lead           — investigates and executes
        Comms Lead          — internal and external communication
  [ ] Open incident ticket; all actions recorded in real time

PHASE 2: CONTAIN (15 min - 2 hr)
  [ ] Identify affected systems and scope of exposure
  [ ] Revoke compromised credentials IMMEDIATELY
        API keys, DB passwords, session tokens, IAM keys
  [ ] Block attacker IP(s) at WAF/CDN level
  [ ] Isolate affected workloads (tighten NetworkPolicy, scale to 0)
  [ ] Preserve evidence: snapshot disk images, copy logs to cold storage
      !! DO NOT wipe or restart affected systems until forensics complete !!

PHASE 3: ERADICATE (2-8 hr)
  [ ] Identify root cause (how did attacker get in? what did they access?)
  [ ] Remove all malicious access paths (backdoors, added IAM users, etc.)
  [ ] Patch or disable the vulnerable component
  [ ] Re-image affected hosts (immutable infra: replace pods, not patch)
  [ ] Confirm attacker IOCs (indicators of compromise) are gone

PHASE 4: RECOVER (8-24 hr)
  [ ] Deploy patched, clean infrastructure from verified pipeline
  [ ] Restore data from backup verified clean (test restore integrity)
  [ ] Re-enable services incrementally with enhanced monitoring
  [ ] Verify attacker no longer has access (check all credential stores)
  [ ] Communicate status to stakeholders

PHASE 5: POST-INCIDENT (within 72 hr)
  [ ] Blameless post-mortem with 5-Whys root cause analysis
  [ ] Action items with named owners and due dates (Jira tickets)
  [ ] Update threat model with the newly discovered attack vector
  [ ] Regulatory notification if required:
        GDPR: 72 hours to supervisory authority
        HIPAA: 60 days (if >500 individuals)
        PCI-DSS: immediately to card brands
  [ ] Notify affected users if PII was exposed
  [ ] Update cyber insurance claim

Contacts (fill in for your org):
  Legal:             breach notification obligations
  PR/Comms:          external messaging review
  C-suite:           escalation path for Sev-1
  Cyber insurance:   open claim immediately for Sev-1
"""

print("\n=== Incident Response Playbook ===")
print(INCIDENT_PLAYBOOK)


# =============================================================================
# SECTION 10: SOC 2 Type II — Relevance for Backend Engineers
# =============================================================================

SOC2_NOTES = """
SOC 2 Type II — What Backend Engineers Actually Need to Know:

SOC 2 is an audit framework by AICPA covering five Trust Service Criteria:
  CC: Common Criteria (Security)   — the one almost everyone cares about
  A:  Availability
  PI: Processing Integrity
  C:  Confidentiality
  P:  Privacy

Type I: point-in-time assessment ("your controls look good on paper")
Type II: 6-12 month audit period ("your controls worked consistently over time")

Controls YOU are responsible for implementing:

  ACCESS CONTROL
  [ ] MFA enforced for all human access to production
  [ ] Least-privilege IAM roles (no wildcard * policies in prod)
  [ ] Access reviews quarterly (remove stale accounts/permissions)
  [ ] Off-boarding checklist (revoke within 24 hours of departure)

  CHANGE MANAGEMENT
  [ ] All changes via PR + code review (no direct commits to main)
  [ ] CI/CD pipeline gates (tests + security scan must pass)
  [ ] Separate environments: dev / staging / production
  [ ] Feature flags for rollback without full redeployment

  LOGGING & MONITORING
  [ ] Centralized audit logs (CloudWatch, Datadog) — immutable, 12 months
  [ ] Alerts on: failed logins, privilege escalation, IAM changes, unusual egress
  [ ] All authorization decisions and sensitive data access logged

  VULNERABILITY MANAGEMENT
  [ ] Dependency audit in CI (pip-audit, npm audit, trivy)
  [ ] Patch HIGH/CRITICAL CVEs within 30 days (CRITICAL within 7)
  [ ] Annual penetration test by external firm
  [ ] Security awareness training for all engineers annually

  ENCRYPTION
  [ ] Data at rest: AES-256 (cloud KMS or equivalent)
  [ ] Data in transit: TLS 1.2+ (preferably 1.3)
  [ ] Key management: rotation policy documented and enforced

  INCIDENT RESPONSE
  [ ] Written IR plan tested at least annually (tabletop exercise)
  [ ] Breach notification process documented with regulatory deadlines

As an engineer, you'll interact with SOC 2 via:
  - Evidence gathering (screenshots, log exports, policy documents)
  - Control questionnaires ("how do you enforce MFA?")
  - Audit log exports on auditor request
  - Remediation of control gaps the auditor identifies
"""

print("\n=== SOC 2 Type II ===")
print(SOC2_NOTES)


# =============================================================================
# SECTION 11: Pre-Launch Security Checklist
# =============================================================================

@dataclass
class SecurityChecklistItem:
    category: str
    item: str
    critical: bool = False   # must-have before launch vs. nice-to-have


PRE_LAUNCH_CHECKLIST = [
    # Authentication
    SecurityChecklistItem("AuthN", "Passwords hashed with bcrypt/argon2 (not MD5/SHA1)", critical=True),
    SecurityChecklistItem("AuthN", "MFA available for all users, required for admins", critical=True),
    SecurityChecklistItem("AuthN", "JWT expiry <= 15 minutes with refresh token rotation", critical=True),
    SecurityChecklistItem("AuthN", "Account lockout after N consecutive failed attempts", critical=True),

    # Authorization
    SecurityChecklistItem("AuthZ", "All API endpoints carry authorization checks", critical=True),
    SecurityChecklistItem("AuthZ", "IDOR tested: user A cannot access user B's data", critical=True),
    SecurityChecklistItem("AuthZ", "Admin endpoints require admin role + MFA step-up", critical=True),
    SecurityChecklistItem("AuthZ", "Row-level security in PostgreSQL for tenant isolation", critical=False),

    # Transport
    SecurityChecklistItem("TLS",  "HTTPS enforced everywhere (HTTP redirects to HTTPS)", critical=True),
    SecurityChecklistItem("TLS",  "HSTS header set (max-age >= 6 months)", critical=True),
    SecurityChecklistItem("TLS",  "TLS 1.2 minimum, 1.3 preferred, 1.0/1.1 disabled", critical=True),
    SecurityChecklistItem("TLS",  "Certificate auto-renewal configured and tested", critical=True),

    # Inputs
    SecurityChecklistItem("Input", "All DB queries use parameterized statements", critical=True),
    SecurityChecklistItem("Input", "File uploads: MIME validation, size limits, AV scan", critical=True),
    SecurityChecklistItem("Input", "No user input reflected without HTML escaping (XSS)", critical=True),

    # Headers
    SecurityChecklistItem("Headers", "CSP, X-Content-Type-Options, X-Frame-Options set", critical=True),
    SecurityChecklistItem("Headers", "Server header redacted (no framework/version leak)", critical=False),
    SecurityChecklistItem("Headers", "Permissions-Policy restricts camera/mic/geolocation", critical=False),

    # Secrets
    SecurityChecklistItem("Secrets", "No secrets committed to git (gitleaks scan clean)", critical=True),
    SecurityChecklistItem("Secrets", "Secrets in Vault/AWS SM, not baked into Docker image", critical=True),
    SecurityChecklistItem("Secrets", "Secret rotation policy documented with TTL", critical=False),

    # Supply Chain
    SecurityChecklistItem("Supply", "pip-audit / npm audit runs in CI with failure threshold", critical=True),
    SecurityChecklistItem("Supply", "Container image scanned with trivy (no CRITICAL CVEs)", critical=True),
    SecurityChecklistItem("Supply", "Base image pinned to specific digest (not :latest)", critical=False),
    SecurityChecklistItem("Supply", "SBOM generated and stored for each release", critical=False),

    # Logging
    SecurityChecklistItem("Logging", "Auth events (success + failure) written to audit log", critical=True),
    SecurityChecklistItem("Logging", "No secrets or PII in application logs", critical=True),
    SecurityChecklistItem("Logging", "Audit logs retained 12 months, immutable storage", critical=False),
]

print("\n=== Pre-Launch Security Checklist ===")
critical_items = [c for c in PRE_LAUNCH_CHECKLIST if c.critical]
improve_items  = [c for c in PRE_LAUNCH_CHECKLIST if not c.critical]

print(f"\nCRITICAL ({len(critical_items)} items — must pass before launch):")
for item in critical_items:
    print(f"  [ ] [{item.category:8}] {item.item}")

print(f"\nIMPROVE ({len(improve_items)} items — address within 90 days):")
for item in improve_items:
    print(f"  [ ] [{item.category:8}] {item.item}")


# =============================================================================
# SUMMARY
# =============================================================================
print("\n" + "=" * 65)
print("SECURITY ARCHITECTURE SUMMARY")
print("=" * 65)
print("Defense in Depth : 5 layers perimeter -> data; any one can fail safely")
print("Zero Trust       : verify every request; assume breach; least privilege")
print("Security Headers : CSP, HSTS, X-Frame, Referrer, Permissions-Policy")
print("Supply Chain     : SBOM + Sigstore signing + SLSA L2 in CI")
print("Containers       : non-root, read-only FS, drop ALL caps, seccomp")
print("Dep Audit        : pip-audit + bandit + trivy in every CI run")
print("STRIDE           : name threats before writing code, then mitigate")
print("Pentest          : ZAP in CI + annual external penetration test")
print("Incident         : Detect -> Contain -> Eradicate -> Recover -> Postmortem")
print("SOC 2 Type II    : MFA, access review, audit logs, patch SLAs, IR plan")
