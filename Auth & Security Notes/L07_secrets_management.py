# =============================================================================
# WHAT: Secrets Management — storing, rotating, and injecting sensitive values
# WHY:  Leaked credentials are the #1 cause of cloud breaches. Secrets must
#       never be committed to code, baked into images, or left in plain text.
#       Knowing the right tools and patterns is non-negotiable for production.
# LEVEL: Intermediate → Advanced
# =============================================================================

# CONCEPT OVERVIEW
# ----------------
# A "secret" is any value that grants access or proves identity:
#   - API keys (Stripe, SendGrid, Twilio)
#   - Database passwords and connection strings
#   - TLS private keys and certificates
#   - JWT signing keys (symmetric HMAC or asymmetric RSA/EC private key)
#   - OAuth client_id + client_secret pairs
#   - SSH private keys
#   - Encryption keys (AES master keys, KMS CMKs)
#
# The problem: application code needs secrets at runtime, but secrets must
# not live in the codebase, Docker images, or unencrypted config files.
#
# Solutions by maturity level:
#   Level 1 (bad)   — secrets in source code or committed .env files
#   Level 2 (ok)    — environment variables at runtime (12-factor app)
#   Level 3 (good)  — secrets manager (AWS Secrets Manager, GCP Secret Manager)
#   Level 4 (best)  — short-lived dynamic secrets (HashiCorp Vault), rotation,
#                     zero standing access

# PRODUCTION USE CASE
# -------------------
# Kubernetes microservices reading DB credentials from Vault via a sidecar
# agent. Credentials rotate every 1 hour. If a pod is compromised, the
# attacker's window is bounded by the lease TTL.

# COMMON MISTAKES
# ---------------
# 1. Printing secrets in logs ("Connected with password=<secret>")
# 2. Passing secrets as Docker build ARGs — they appear in image history
# 3. Using the same secret across environments (dev secret == prod secret)
# 4. Never rotating secrets — a leaked old key is still valid
# 5. Storing secrets in git-tracked .env files
# 6. Using environment variables in Dockerfiles (ENV instruction bakes them in)
# 7. Not auditing secret access (who read what secret, when)

import os
import base64
import hashlib
import hmac
import json
import time
import logging
import subprocess
from dataclasses import dataclass
from typing import Any

# Third-party (install as needed):
# pip install hvac boto3 cryptography

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# =============================================================================
# SECTION 1: Secret Types and Where They Come From
# =============================================================================

class SecretType:
    """Taxonomy of secret types and their characteristics."""

    # Static long-lived secrets — must be rotated on a schedule
    API_KEY        = "api_key"          # e.g. STRIPE_SECRET_KEY
    DB_PASSWORD    = "db_password"      # e.g. PostgreSQL password
    TLS_PRIVATE_KEY = "tls_private_key" # DER/PEM encoded RSA/EC key
    JWT_SIGNING_KEY = "jwt_signing_key" # HS256 secret or RSA private key
    OAUTH_SECRET   = "oauth_client_secret"

    # Dynamic short-lived secrets — issued on-demand, auto-expire
    DB_DYNAMIC     = "db_dynamic"       # Vault-issued DB credentials (TTL=1h)
    TLS_CERT       = "tls_cert"         # Vault PKI-issued cert (TTL=24h)
    CLOUD_STS      = "cloud_sts_token"  # AWS STS AssumeRole (TTL=15min–12h)


# =============================================================================
# SECTION 2: Anti-Patterns — What NOT To Do
# =============================================================================

# ANTI-PATTERN 1: Hardcoded secrets in source code
# -------------------------------------------------
# BAD:
# DATABASE_URL = "postgresql://user:SUPER_SECRET_PASSWORD@prod-db:5432/mydb"
# STRIPE_KEY   = "sk_live_abc123..."
#
# WHY BAD: Every developer with repo access has prod credentials.
#          Git history is forever — rotating the secret doesn't help.
#          Security scanners (trufflehog, gitleaks) will flag it.


# ANTI-PATTERN 2: .env files committed to git
# -------------------------------------------
# BAD:
# $ cat .env
# DATABASE_URL=postgresql://...
# STRIPE_KEY=sk_live_...
# $ git add .env && git commit -m "add env file"
#
# FIX: Add .env to .gitignore immediately. Use .env.example with fake values.
# Even better: don't use .env in production at all.


# ANTI-PATTERN 3: Secrets baked into Docker images
# -------------------------------------------------
# BAD Dockerfile:
#   ARG DB_PASSWORD
#   ENV DB_PASSWORD=$DB_PASSWORD
#   RUN ./configure --db-password=$DB_PASSWORD
#
# WHY BAD: `docker history <image>` reveals ARG values.
#          Anyone who pulls the image from a registry gets the secret.
#
# FIX: Never put secrets in Dockerfile ARG/ENV or RUN commands.
#      Inject at runtime via volume, environment variable from secret store,
#      or init container.


# ANTI-PATTERN 4: Logging secrets
# --------------------------------
# BAD:
# logger.debug(f"Connecting with DSN: {database_dsn}")   # DSN contains password
# print(f"API key used: {api_key}")
#
# FIX: Log only redacted versions. The pattern below shows how.

def redact_secret(value: str, show_chars: int = 4) -> str:
    """
    Return a redacted version of a secret for logging.
    Shows only the first N characters so you can identify which key it is
    without exposing the secret itself.
    """
    if len(value) <= show_chars:
        return "***"
    return value[:show_chars] + "***"

# Good:
api_key = "sk_live_abc123XYZ"
logger.info("Using API key: %s", redact_secret(api_key))  # logs "sk_l***"


# =============================================================================
# SECTION 3: HashiCorp Vault — The Gold Standard for Dynamic Secrets
# =============================================================================
# Vault is an open-source secrets management platform.
# Key features:
#   KV v2       — versioned key-value secret storage
#   Dynamic     — generates short-lived DB credentials on demand
#   PKI         — issues TLS certificates as a CA
#   Encryption  — "encryption as a service" (no key exposure)
#   Audit       — every secret access is logged

VAULT_USAGE_EXAMPLE = """
# ---- HashiCorp Vault KV v2 (versioned secrets) ----
import hvac

client = hvac.Client(
    url=os.environ["VAULT_ADDR"],           # e.g. http://vault:8200
    token=os.environ["VAULT_TOKEN"],        # or use AppRole / Kubernetes auth
)

# Write a secret (creates a new version, old version retained)
client.secrets.kv.v2.create_or_update_secret(
    path="myapp/database",
    secret={"username": "app_user", "password": "s3cr3t"},
    mount_point="secret",
)

# Read the latest version
response = client.secrets.kv.v2.read_secret_version(
    path="myapp/database",
    mount_point="secret",
)
creds = response["data"]["data"]  # {"username": ..., "password": ...}

# Read a specific historical version (audit trail / rollback)
response = client.secrets.kv.v2.read_secret_version(
    path="myapp/database",
    version=3,
    mount_point="secret",
)
"""

VAULT_DYNAMIC_DB_EXAMPLE = """
# ---- Vault Dynamic Database Secrets (PostgreSQL) ----
# Vault connects to your DB as a superuser and creates a temporary user
# with a TTL. When the lease expires, Vault automatically drops the user.

# Configure the DB secrets engine (done once by ops):
# vault secrets enable database
# vault write database/config/mydb \\
#     plugin_name=postgresql-database-plugin \\
#     connection_url="postgresql://vault_admin:{{password}}@db:5432/prod" \\
#     allowed_roles="app-role"
# vault write database/roles/app-role \\
#     db_name=mydb \\
#     creation_statements="CREATE ROLE {{name}} WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {{name}};" \\
#     default_ttl="1h" \\
#     max_ttl="4h"

# Application reads a fresh credential on startup (or on lease renewal)
import hvac

client = hvac.Client(url=os.environ["VAULT_ADDR"], token=os.environ["VAULT_TOKEN"])
lease = client.secrets.database.generate_credentials(name="app-role")

db_user     = lease["data"]["username"]   # e.g. "v-app-role-AbCdEf"
db_password = lease["data"]["password"]   # auto-generated, complex
lease_id    = lease["lease_id"]           # for renewal
ttl         = lease["lease_duration"]     # seconds until expiry

# Connect to DB with the short-lived credential
import asyncpg
conn = await asyncpg.connect(
    host="db", database="prod",
    user=db_user, password=db_password,
)
# When pod restarts, it gets a different credential. No standing access.
"""

VAULT_PKI_EXAMPLE = """
# ---- Vault PKI — Issue TLS Certs On-Demand ----
# WHY: Short-lived certs (24h TTL) eliminate the need to revoke certs.
#      Rotation is automatic. No cert pinning required.

client = hvac.Client(url=os.environ["VAULT_ADDR"], token=os.environ["VAULT_TOKEN"])

cert_response = client.secrets.pki.generate_certificate(
    name="myapp-role",               # role defines allowed domains, TTL
    common_name="api.internal",
    mount_point="pki",
    extra_params={"ttl": "24h"},
)

tls_cert        = cert_response["data"]["certificate"]      # PEM string
tls_private_key = cert_response["data"]["private_key"]      # PEM string
ca_chain        = cert_response["data"]["ca_chain"]         # list of PEM strings

# Write to tmpfs for the TLS server to read
with open("/run/secrets/tls.crt", "w") as f:
    f.write(tls_cert)
with open("/run/secrets/tls.key", "w") as f:
    f.write(tls_private_key)
"""

print("=== Vault Patterns ===")
print("KV v2: versioned static secrets")
print("Dynamic DB: short-lived PostgreSQL credentials")
print("PKI: TLS cert issuance (24h TTL, auto-rotation)")

# Vault Agent Sidecar pattern (Kubernetes)
VAULT_AGENT_K8S = """
# vault-agent-config.hcl  (ConfigMap mounted into agent sidecar)
auto_auth {
  method "kubernetes" {
    config = {
      role = "myapp"   # Vault role bound to this K8s service account
    }
  }
}

template {
  source      = "/vault/templates/db.ctmpl"
  destination = "/vault/secrets/db.env"  # written to shared emptyDir volume
}

# db.ctmpl — Go template that pulls secret and renders env-var format
{{ with secret "secret/data/myapp/database" }}
DB_USER={{ .Data.data.username }}
DB_PASSWORD={{ .Data.data.password }}
{{ end }}

# App container reads /vault/secrets/db.env at startup.
# Agent re-renders when the secret changes (lease renewal).
"""

print("\n=== Vault Agent Sidecar ===")
print("Agent handles auth + rendering; app reads plain file. No SDK needed.")


# =============================================================================
# SECTION 4: AWS Secrets Manager
# =============================================================================
# WHY: Managed service — no Vault cluster to operate. Native integration with
# RDS, Lambda, IAM. Automatic rotation via Lambda rotation functions.

AWS_SECRETS_EXAMPLE = """
import boto3
import json

def get_secret(secret_name: str, region: str = "us-east-1") -> dict:
    '''
    Retrieve and parse a JSON secret from AWS Secrets Manager.
    IAM policy on the pod's role must allow secretsmanager:GetSecretValue.
    '''
    client = boto3.client("secretsmanager", region_name=region)

    try:
        response = client.get_secret_value(SecretId=secret_name)
    except client.exceptions.ResourceNotFoundException:
        raise ValueError(f"Secret {secret_name!r} not found")

    # Secrets can be a JSON string or a plain string
    secret_str = response.get("SecretString") or base64.b64decode(response["SecretBinary"])
    return json.loads(secret_str)

# Usage:
# creds = get_secret("prod/myapp/database")
# conn = await asyncpg.connect(host=creds["host"], password=creds["password"], ...)
"""

AWS_ROTATION_EXAMPLE = """
# ---- Automatic Rotation via Lambda ----
# AWS calls your Lambda at the rotation interval with four steps:
#   createSecret  — generate new credentials
#   setSecret     — write new credentials to the database
#   testSecret    — verify new credentials work
#   finishSecret  — mark new version as AWSCURRENT

def lambda_handler(event, context):
    arn   = event["SecretId"]
    token = event["ClientRequestToken"]
    step  = event["Step"]

    sm = boto3.client("secretsmanager")

    if step == "createSecret":
        # Generate a new password and store it as AWSPENDING
        new_password = secrets.token_urlsafe(32)
        sm.put_secret_value(
            SecretId=arn, ClientRequestToken=token,
            SecretString=json.dumps({"password": new_password}),
            VersionStages=["AWSPENDING"],
        )

    elif step == "setSecret":
        # Retrieve AWSPENDING and update the database user's password
        pending = json.loads(sm.get_secret_value(
            SecretId=arn, VersionStage="AWSPENDING"
        )["SecretString"])
        # ... ALTER USER app_user WITH PASSWORD %(password)s ...

    elif step == "testSecret":
        # Attempt a DB connection with the new password
        ...

    elif step == "finishSecret":
        # Promote AWSPENDING to AWSCURRENT
        sm.update_secret_version_stage(
            SecretId=arn, VersionStage="AWSCURRENT",
            MoveToVersionId=token,
            RemoveFromVersionId=...,
        )
"""

print("\n=== AWS Secrets Manager ===")
print("Managed rotation via Lambda. IAM controls access. No cluster to run.")


# =============================================================================
# SECTION 5: Kubernetes Secrets — Limitations and Safer Alternatives
# =============================================================================

K8S_SECRET_LIMITATIONS = """
# Kubernetes Secrets are base64-encoded, NOT encrypted by default.
# Anyone with kubectl access to the namespace can read them:
#   kubectl get secret db-password -o jsonpath='{.data.password}' | base64 -d

# ---- Creating a K8s Secret ----
# kubectl create secret generic db-creds \\
#   --from-literal=username=app_user \\
#   --from-literal=password='s3cr3t'

# ---- Using in a Pod ----
# env:
#   - name: DB_PASSWORD
#     valueFrom:
#       secretKeyRef:
#         name: db-creds
#         key: password

# ---- Enabling Encryption at Rest (requires EncryptionConfiguration) ----
# apiVersion: apiserver.config.k8s.io/v1
# kind: EncryptionConfiguration
# resources:
#   - resources: ["secrets"]
#     providers:
#       - aescbc:
#           keys:
#             - name: key1
#               secret: <base64-encoded 32-byte key>
#       - identity: {}   # fallback: unencrypted
"""

EXTERNAL_SECRETS_EXAMPLE = """
# ---- External Secrets Operator (ESO) ----
# ESO syncs secrets FROM Vault/AWS/GCP INTO K8s Secrets automatically.
# WHY: Keeps your source of truth in a proper secrets manager; K8s Secret is
# just a cached copy that ESO rotates.

# ClusterSecretStore (cluster-wide, references Vault)
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: vault-backend
spec:
  provider:
    vault:
      server: "http://vault:8200"
      path: "secret"
      version: "v2"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "myapp"

# ExternalSecret (per-namespace, pulls specific path)
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: db-credentials
spec:
  refreshInterval: 1h              # re-sync period
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: db-credentials           # K8s Secret name created/updated
  data:
    - secretKey: password          # key in K8s Secret
      remoteRef:
        key: myapp/database        # Vault path
        property: password         # field within the secret
"""

SEALED_SECRETS_EXAMPLE = """
# ---- Sealed Secrets (Bitnami) ----
# Encrypts K8s Secrets with a cluster-specific key. Encrypted YAML is safe
# to commit to git. Only the cluster can decrypt it.
#
# Workflow:
#   1. kubeseal --fetch-cert > pub-cert.pem         (one-time, per cluster)
#   2. kubectl create secret generic db-creds \\
#        --from-literal=password=s3cr3t --dry-run=client -o yaml \\
#      | kubeseal --cert pub-cert.pem -o yaml > db-creds-sealed.yaml
#   3. git add db-creds-sealed.yaml && git commit   (safe to commit!)
#   4. kubectl apply -f db-creds-sealed.yaml        (controller decrypts it)
"""

print("\n=== Kubernetes Secrets ===")
print("Base64 ≠ encryption. Use ESO + Vault or Sealed Secrets for production.")


# =============================================================================
# SECTION 6: Secret Rotation Without Downtime — Dual-Read Pattern
# =============================================================================
# WHY: Rotating a secret causes a window where the old secret is invalid but
# some instances still hold the old value. Dual-read eliminates that window.

@dataclass
class RotatingSecret:
    """
    Holds current and previous versions of a secret.
    During rotation, both are valid. After all clients refresh, retire old.
    """
    current: str
    previous: str | None
    rotated_at: float

    def is_valid(self, candidate: str) -> bool:
        """
        Accept either current or previous secret.
        This is the dual-read pattern: during rollout, old tokens still work.
        """
        # Use constant-time comparison to prevent timing attacks
        valid_current  = hmac.compare_digest(candidate, self.current)
        valid_previous = (
            hmac.compare_digest(candidate, self.previous)
            if self.previous else False
        )
        return valid_current or valid_previous


class SecretRotator:
    """
    Simulates a secret rotation workflow.
    In production: coordinate with AWS Secrets Manager rotation or Vault lease renewal.
    """

    def __init__(self, initial_secret: str):
        self._secret = RotatingSecret(
            current=initial_secret,
            previous=None,
            rotated_at=time.time(),
        )

    def rotate(self, new_secret: str) -> None:
        """
        Step 1: Make new secret current, keep old as previous.
        Step 2: Application code (dual-read) accepts both during transition.
        Step 3: After all services reload, retire previous (call retire_previous).
        """
        logger.info(
            "SECRET_ROTATING old_prefix=%s new_prefix=%s",
            redact_secret(self._secret.current),
            redact_secret(new_secret),
        )
        self._secret = RotatingSecret(
            current=new_secret,
            previous=self._secret.current,
            rotated_at=time.time(),
        )

    def retire_previous(self) -> None:
        """Call this after all services have loaded the new secret."""
        self._secret = RotatingSecret(
            current=self._secret.current,
            previous=None,
            rotated_at=self._secret.rotated_at,
        )
        logger.info("SECRET_RETIRED previous version dropped")

    def validate(self, candidate: str) -> bool:
        return self._secret.is_valid(candidate)


print("\n=== Dual-Read Rotation Demo ===")
rotator = SecretRotator("old-api-key-abc")
print("Old key valid?", rotator.validate("old-api-key-abc"))   # True

rotator.rotate("new-api-key-xyz")
print("Old key still valid after rotation?", rotator.validate("old-api-key-abc"))  # True (dual-read)
print("New key valid?", rotator.validate("new-api-key-xyz"))   # True

rotator.retire_previous()
print("Old key valid after retire?", rotator.validate("old-api-key-abc"))   # False
print("New key still valid?",        rotator.validate("new-api-key-xyz"))   # True


# =============================================================================
# SECTION 7: Secret Injection Patterns in Containers
# =============================================================================

INJECTION_PATTERNS = """
# Pattern 1: Environment variable from K8s Secret (simple, common)
# ----------------------------------------------------------------
# env:
#   - name: DB_PASSWORD
#     valueFrom:
#       secretKeyRef: {name: db-creds, key: password}
#
# PRO: Dead simple. Works with any 12-factor app.
# CON: Visible in `kubectl describe pod`. Inherited by child processes.
#      Not suitable for very sensitive secrets.


# Pattern 2: Volume mount (file-based injection)
# -----------------------------------------------
# volumes:
#   - name: vault-secrets
#     emptyDir: {medium: Memory}   # tmpfs: not persisted to disk
# containers:
#   - name: app
#     volumeMounts:
#       - name: vault-secrets
#         mountPath: /run/secrets
#         readOnly: true
#
# App reads /run/secrets/db_password at startup.
# PRO: Not exposed in pod spec. Agent can update file without restart.
# CON: File permissions must be tight (chmod 0400).


# Pattern 3: Init container (pull-once pattern)
# ----------------------------------------------
# initContainers:
#   - name: vault-init
#     image: vault:latest
#     command: ["vault", "kv", "get", "-format=json", "secret/db"]
#     volumeMounts:
#       - name: secrets-vol
#         mountPath: /vault/secrets
#
# Init writes secret to shared emptyDir, then exits.
# Main container reads from that emptyDir.
# PRO: Separation of concerns. Init container has Vault token; app doesn't.
# CON: Secret only refreshed on pod restart.


# Pattern 4: Vault Agent sidecar (best for dynamic secrets)
# ----------------------------------------------------------
# containers:
#   - name: vault-agent
#     image: hashicorp/vault:latest
#     args: ["agent", "-config=/vault/config/agent.hcl"]
#   - name: app
#     ...
# Both share an emptyDir. Agent continuously refreshes secrets and re-renders
# templates. App gets the latest credential transparently.
"""

print("\n=== Injection Patterns ===")
print("emptyDir (tmpfs) + Vault Agent sidecar = best production pattern.")


# =============================================================================
# SECTION 8: Detecting Secret Leaks — git-secrets, trufflehog, gitleaks
# =============================================================================

def scan_for_secrets_demo() -> None:
    """
    Demonstrate CLI tools used to detect leaked secrets in git history.
    In production, run these in pre-commit hooks AND CI pipelines.
    """
    commands = {
        "gitleaks": [
            "gitleaks detect",               # scan working directory
            "gitleaks detect --source=.",    # explicit source
            "gitleaks protect --staged",     # pre-commit: scan staged changes
        ],
        "trufflehog": [
            "trufflehog git file://.",        # scan entire git history
            "trufflehog github --repo=https://github.com/org/repo",
        ],
        "git-secrets": [
            "git secrets --install",         # add hooks to current repo
            "git secrets --register-aws",    # add AWS key patterns
            "git secrets --scan",            # scan all committed files
        ],
        "detect-secrets": [
            "detect-secrets scan > .secrets.baseline",   # generate baseline
            "detect-secrets audit .secrets.baseline",    # review findings
        ],
    }

    print("\n=== Secret Scanning Commands ===")
    for tool, cmds in commands.items():
        print(f"\n[{tool}]")
        for cmd in cmds:
            print(f"  $ {cmd}")


scan_for_secrets_demo()


# =============================================================================
# SECTION 9: Pre-commit Hook to Block Accidental Secret Commits
# =============================================================================

PRE_COMMIT_CONFIG = """
# .pre-commit-config.yaml — add to your repo root
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.2
    hooks:
      - id: gitleaks

  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.4.0
    hooks:
      - id: detect-secrets
        args: ["--baseline", ".secrets.baseline"]

  - repo: https://github.com/awslabs/git-secrets
    rev: master
    hooks:
      - id: git-secrets
"""

print("\n=== Pre-commit Hook Configuration ===")
print(PRE_COMMIT_CONFIG)


# =============================================================================
# SECTION 10: Secret Classification and Lifecycle
# =============================================================================

@dataclass
class SecretMetadata:
    """
    Track the lifecycle of every secret in your system.
    Store this in a CMDB or secrets registry (not the secret itself!).
    """
    secret_name: str
    secret_type: str            # from SecretType
    owner_team: str             # who is responsible for rotation
    environment: str            # "production", "staging", "dev"
    rotation_interval_days: int # how often it must be rotated
    last_rotated: float         # unix timestamp
    expires_at: float | None    # None = no expiry (bad practice for prod)
    in_use_by: list[str]        # services that use this secret

    @property
    def days_since_rotation(self) -> float:
        return (time.time() - self.last_rotated) / 86400

    @property
    def is_overdue(self) -> bool:
        return self.days_since_rotation > self.rotation_interval_days

    def rotation_status(self) -> str:
        remaining = self.rotation_interval_days - self.days_since_rotation
        if remaining < 0:
            return f"OVERDUE by {abs(remaining):.1f} days"
        if remaining < 7:
            return f"ROTATE SOON — {remaining:.1f} days remaining"
        return f"OK — {remaining:.1f} days until rotation"


# Example secret registry
secrets_registry = [
    SecretMetadata(
        secret_name="prod/payments/stripe-key",
        secret_type=SecretType.API_KEY,
        owner_team="payments",
        environment="production",
        rotation_interval_days=90,
        last_rotated=time.time() - 85 * 86400,   # 85 days ago
        expires_at=None,
        in_use_by=["payments-service", "billing-job"],
    ),
    SecretMetadata(
        secret_name="prod/db/master-password",
        secret_type=SecretType.DB_PASSWORD,
        owner_team="platform",
        environment="production",
        rotation_interval_days=30,
        last_rotated=time.time() - 32 * 86400,   # 32 days ago — OVERDUE
        expires_at=None,
        in_use_by=["api-service"],
    ),
]

print("\n=== Secret Rotation Audit ===")
for s in secrets_registry:
    status = s.rotation_status()
    flag = "!!!" if s.is_overdue else ""
    print(f"{flag} {s.secret_name}: {status}")


# =============================================================================
# SECTION 11: Environment Variable Best Practices
# =============================================================================

def load_secrets_from_env(required_keys: list[str]) -> dict[str, str]:
    """
    Load secrets from environment variables with clear error messages.
    WHY: Fail fast at startup rather than getting a cryptic error mid-request.

    In production these env vars are injected by:
      - Kubernetes secretKeyRef
      - AWS ECS Secrets (SSM Parameter Store / Secrets Manager)
      - HashiCorp Vault Agent rendered template
    """
    secrets: dict[str, str] = {}
    missing: list[str] = []

    for key in required_keys:
        value = os.environ.get(key)
        if not value:
            missing.append(key)
        else:
            secrets[key] = value
            logger.info("Loaded secret env var: %s=%s", key, redact_secret(value))

    if missing:
        raise RuntimeError(
            f"Missing required secret environment variables: {missing}. "
            "Ensure they are injected at runtime, not baked into the image."
        )

    return secrets


# Demo (will print warnings since these env vars aren't set in this context)
print("\n=== Environment Variable Loader ===")
try:
    env_secrets = load_secrets_from_env(["DATABASE_URL", "STRIPE_KEY"])
except RuntimeError as e:
    print(f"[expected in demo] {e}")


# =============================================================================
# SUMMARY
# =============================================================================
print("\n=== Secrets Management Summary ===")
print("Anti-patterns : hardcoded secrets, .env in git, secrets in image layers")
print("Vault KV v2   : versioned static secrets, audit log, fine-grained RBAC")
print("Vault Dynamic : DB credentials with 1h TTL — no standing access")
print("Vault PKI     : TLS cert issuance — no cert pinning needed")
print("AWS SM        : managed rotation via Lambda, native RDS integration")
print("K8s Secrets   : base64 only — use ESO or Sealed Secrets for real security")
print("Injection     : prefer volume mounts on tmpfs over plain env vars")
print("Rotation      : dual-read pattern — no downtime, bounded blast radius")
print("Detection     : gitleaks + detect-secrets in pre-commit and CI")
