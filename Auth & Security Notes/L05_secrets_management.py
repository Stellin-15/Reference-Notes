# ============================================================
# L05: Secrets Management
# ============================================================
# WHAT: Strategies and patterns for storing, rotating, and
#       distributing secrets (passwords, API keys, certs)
#       across services without ever committing them to code.
# WHY:  Leaked secrets are the #1 cause of breaches. Git
#       history is permanent — a secret committed once is
#       compromised forever, even after deletion.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    Secrets management covers the full lifecycle of sensitive
    credentials: creation, storage, distribution, rotation,
    and auditing. The goal is zero plaintext secrets in code,
    containers, or logs, while making secrets available to
    legitimate workloads at runtime.

    Key pillars:
      - Centralised storage (Vault, AWS Secrets Manager)
      - Dynamic secrets with short TTLs (limit breach window)
      - Automated rotation (remove human from the loop)
      - Audit logging (who accessed what, when)
      - Secret scanning (catch leaks before they reach prod)

PRODUCTION USE CASE:
    A SaaS platform runs 20 microservices in Kubernetes.
    Each service needs DB credentials, API keys, and TLS
    certs. Secrets are sourced from HashiCorp Vault via the
    K8s External Secrets Operator; DB credentials are dynamic
    (TTL 1 hour); rotation is zero-downtime (both old and new
    credentials valid for 5 minutes during swap). Pre-commit
    hooks and GitHub secret scanning block leaks at source.

COMMON MISTAKES:
    1. Committing .env files — git history is permanent.
    2. Printing secrets in logs ("DB_URL = %s" % secret).
    3. Baking secrets into Docker image layers (ENV/ARG).
    4. Using long-lived static credentials instead of dynamic.
    5. Sharing one secret across all environments (dev==prod).
    6. No rotation — one breach = permanent compromise.
    7. Storing secrets in K8s ConfigMaps (not encrypted at rest).
    8. Relying solely on .gitignore — file can still be added.
"""

import os
import json
import hmac
import hashlib
import logging
import subprocess
import time
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# 1. WHERE SECRETS MUST NOT LIVE
# ---------------------------------------------------------------------------
# The following examples show anti-patterns and why they fail.

# ---- ANTI-PATTERN: hardcoded secret ----------------------------------------
# DB_PASSWORD = "super_secret_123"  # <-- NEVER. Committed to git forever.
# API_KEY = "sk-prod-abc123"        # <-- Even if deleted, git log shows it.

# ---- ANTI-PATTERN: .env file committed to repo -----------------------------
# .env contains:
#   DATABASE_URL=postgres://user:password@prod-db:5432/mydb
# Then someone runs:  git add .env  (even accidentally)
# Now the password is in git history. Force-push cannot fix it — every
# clone, fork, and CI cache already has a copy.

# ---- ANTI-PATTERN: Docker ARG/ENV ------------------------------------------
# Dockerfile:
#   ARG DB_PASSWORD
#   ENV DB_PASSWORD=${DB_PASSWORD}
# Docker bakes every layer into the image. `docker history --no-trunc`
# shows all ENV values in plaintext. Anyone with image pull access sees secrets.

# ---- ANTI-PATTERN: logging secrets ------------------------------------------
# logger.info(f"Connecting with credentials: {db_url}")  # URL has password.
# Logs are often shipped to Datadog, Splunk, Elasticsearch — many readers.

# ---------------------------------------------------------------------------
# 2. WHERE SECRETS BELONG
# ---------------------------------------------------------------------------
# GOOD: environment variables injected at runtime by orchestrator
#   K8s Secret → Pod env var (K8s encrypts at rest if configured)
#   Vault Agent Injector → file on shared volume → app reads file

# GOOD: mounted files from K8s Secret volume
#   volumeMounts:
#     - name: db-creds
#       mountPath: /var/secrets
#       readOnly: true
#   App reads /var/secrets/password at startup, never logs it.

def read_secret_from_file(path: str) -> str:
    """
    Read a secret from a mounted file (K8s Secret volume or Vault Agent).
    Files are preferred over env vars for large secrets (certs, JSON blobs).
    """
    with open(path, "r") as fh:
        return fh.read().strip()  # strip() removes trailing newline from mount

def get_secret_env(name: str) -> str:
    """
    Retrieve a secret from an environment variable.
    Raise clearly if missing — silent None causes confusing downstream errors.
    """
    value = os.environ.get(name)
    if not value:
        # Raise with the variable NAME, never the value (which is empty anyway).
        raise EnvironmentError(
            f"Required secret env var '{name}' is not set. "
            "Ensure the K8s Secret or Vault Agent has populated it."
        )
    return value

# ---------------------------------------------------------------------------
# 3. HASHICORP VAULT — CONCEPTS AND CLIENT PATTERNS
# ---------------------------------------------------------------------------
# Vault is the industry-standard secrets engine. Key engines:
#   - KV (key-value): store static secrets
#   - Database: dynamic credentials (Vault creates a real DB user on demand)
#   - PKI: issue and rotate TLS certificates
#   - Transit: encrypt/decrypt data without exposing keys (Vault as HSM)

@dataclass
class VaultCredential:
    """Represents a dynamic credential issued by Vault with a TTL."""
    username: str
    password: str
    lease_id: str       # Vault lease — renew or revoke via API
    lease_duration: int # seconds until expiry
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def expires_at(self) -> datetime:
        return self.issued_at + timedelta(seconds=self.lease_duration)

    def is_near_expiry(self, threshold_seconds: int = 300) -> bool:
        """
        True if credential expires within threshold_seconds.
        Callers should renew or fetch a new credential before this point.
        Renewing at 80% of TTL is a common rule of thumb.
        """
        remaining = (self.expires_at - datetime.now(timezone.utc)).total_seconds()
        return remaining < threshold_seconds


class VaultClient:
    """
    Minimal Vault client demonstrating the patterns used in production.
    In real code use hvac (pip install hvac) — this shows the HTTP concepts.
    """

    def __init__(self, vault_addr: str, role: str):
        self.vault_addr = vault_addr  # e.g. https://vault.internal:8200
        self.role = role              # K8s auth role bound to this service account
        self._token: Optional[str] = None

    # ---- Authentication: Kubernetes auth method ----------------------------
    # Each Pod has a ServiceAccount JWT at /var/run/secrets/kubernetes.io/serviceaccount/token.
    # Vault verifies the JWT with the K8s API server → issues a Vault token.
    # No static Vault credentials are needed — identity comes from the platform.

    def authenticate_kubernetes(self) -> None:
        """
        Authenticate to Vault using the pod's Kubernetes ServiceAccount token.
        Vault validates the JWT against the K8s API, then issues a Vault token
        scoped to the policies bound to this service's role.
        """
        jwt_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
        try:
            with open(jwt_path) as fh:
                sa_jwt = fh.read().strip()
        except FileNotFoundError:
            # Running locally — fall back to VAULT_TOKEN env var for dev.
            self._token = os.environ.get("VAULT_TOKEN")
            return

        # POST /v1/auth/kubernetes/login
        payload = {"jwt": sa_jwt, "role": self.role}
        # response = requests.post(f"{self.vault_addr}/v1/auth/kubernetes/login", json=payload)
        # self._token = response.json()["auth"]["client_token"]
        print(f"[Vault] Authenticated via K8s ServiceAccount for role '{self.role}'")

    # ---- Dynamic Database Credentials ----------------------------------------
    # Vault connects to the DB with a superuser credential (stored in Vault, not app).
    # On each request, Vault CREATEs a new DB user with a random password and TTL.
    # When the lease expires, Vault DROPs the user automatically.
    # BENEFIT: even if the credential leaks, it expires within TTL (e.g., 1 hour).

    def get_dynamic_db_creds(self, db_role: str) -> VaultCredential:
        """
        Request dynamic DB credentials from Vault's database secrets engine.
        Each call creates a brand-new DB user — never reuse across requests.

        Args:
            db_role: Vault database role, e.g. "payments-readonly"
        Returns:
            VaultCredential with username, password, lease_id, TTL
        """
        # GET /v1/database/creds/{db_role}
        # response = requests.get(
        #     f"{self.vault_addr}/v1/database/creds/{db_role}",
        #     headers={"X-Vault-Token": self._token}
        # )
        # data = response.json()

        # Simulated response for demonstration:
        simulated = {
            "data": {"username": "v-k8s-pay-AbCd1", "password": "A3x!mPq9-Vault"},
            "lease_id": "database/creds/payments-readonly/abc123",
            "lease_duration": 3600,  # 1 hour TTL
        }
        cred = VaultCredential(
            username=simulated["data"]["username"],
            password=simulated["data"]["password"],
            lease_id=simulated["lease_id"],
            lease_duration=simulated["lease_duration"],
        )
        print(f"[Vault] Issued dynamic DB cred: user={cred.username}, TTL={cred.lease_duration}s")
        return cred

    def renew_lease(self, lease_id: str, increment: int = 3600) -> None:
        """
        Renew a Vault lease before it expires.
        Call this at ~80% of TTL to avoid credential disruption.
        PUT /v1/sys/leases/renew
        """
        print(f"[Vault] Renewing lease {lease_id} for {increment}s")

    def revoke_lease(self, lease_id: str) -> None:
        """
        Explicitly revoke a credential when no longer needed.
        Vault drops the DB user immediately — don't wait for TTL.
        PUT /v1/sys/leases/revoke
        """
        print(f"[Vault] Revoking lease {lease_id}")

    # ---- Transit Encryption (Vault as HSM) ------------------------------------
    # App sends plaintext to Vault. Vault encrypts with a named key and returns
    # ciphertext. App stores ciphertext in DB. Keys never leave Vault.
    # Use for: PII fields, PAN data, SSNs stored in database.

    def encrypt(self, key_name: str, plaintext_b64: str) -> str:
        """
        Encrypt data via Vault Transit engine.
        POST /v1/transit/encrypt/{key_name}
        plaintext_b64: base64-encoded plaintext (Vault requirement)
        Returns: vault:v1:<ciphertext>  (version prefix enables key rotation)
        """
        # response = requests.post(
        #     f"{self.vault_addr}/v1/transit/encrypt/{key_name}",
        #     json={"plaintext": plaintext_b64},
        #     headers={"X-Vault-Token": self._token}
        # )
        return f"vault:v1:simulated_ciphertext_for_{plaintext_b64[:8]}"

    def decrypt(self, key_name: str, ciphertext: str) -> str:
        """
        Decrypt data via Vault Transit engine.
        POST /v1/transit/decrypt/{key_name}
        App never sees the encryption key — Vault holds it.
        """
        return "decrypted_plaintext"


# ---------------------------------------------------------------------------
# 4. VAULT AGENT INJECTOR — SIDECAR PATTERN
# ---------------------------------------------------------------------------
# No app code needed for secret injection.
# Vault Agent runs as a sidecar container, authenticates to Vault,
# fetches secrets, writes them to a shared emptyDir volume as files.
# App reads /vault/secrets/db-password — treats it as a regular file.

VAULT_AGENT_ANNOTATION_EXAMPLE = """
# K8s Pod annotation to enable Vault Agent Injector:
metadata:
  annotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/role: "payments-service"
    vault.hashicorp.com/agent-inject-secret-db-password: "database/creds/payments-rw"
    vault.hashicorp.com/agent-inject-template-db-password: |
      {{- with secret "database/creds/payments-rw" -}}
      {{ .Data.password }}
      {{- end }}
# File appears at: /vault/secrets/db-password
# Agent refreshes the file before lease expires (auto-rotation).
"""

# ---------------------------------------------------------------------------
# 5. K8S EXTERNAL SECRETS OPERATOR (ESO)
# ---------------------------------------------------------------------------
# ESO syncs secrets FROM Vault/AWS Secrets Manager/GCP Secret Manager
# INTO native K8s Secrets. App uses normal K8s Secrets (env vars or volumes).
# ESO watches the external store and updates K8s Secret on rotation.

ESO_MANIFEST_EXAMPLE = """
# ExternalSecret CRD — syncs from Vault to K8s Secret:
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: payments-db-creds
  namespace: payments
spec:
  refreshInterval: 1h          # Re-sync every hour (pick up rotated creds)
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: payments-db-secret   # K8s Secret that gets created/updated
  data:
    - secretKey: DB_PASSWORD   # Key in K8s Secret
      remoteRef:
        key: secret/payments/db  # Path in Vault
        property: password
"""

# ---------------------------------------------------------------------------
# 6. AWS SECRETS MANAGER — RDS ROTATION
# ---------------------------------------------------------------------------
# AWS Secrets Manager has built-in rotation for RDS (MySQL, Postgres, Aurora).
# Lambda rotator: creates new password → updates DB user → updates secret.
# App retrieves secret via SDK (no creds needed if using IAM role).

def get_aws_secret(secret_name: str, region: str = "us-east-1") -> dict:
    """
    Retrieve a secret from AWS Secrets Manager using the instance/pod IAM role.
    No AWS_ACCESS_KEY_ID / SECRET needed — role provides identity.
    SDK caches the secret in memory; call with force_refresh for rotation window.
    """
    # import boto3
    # client = boto3.client("secretsmanager", region_name=region)
    # response = client.get_secret_value(SecretId=secret_name)
    # return json.loads(response["SecretString"])
    print(f"[AWS] Fetching secret '{secret_name}' via IAM role (no static creds)")
    return {"username": "app_user", "password": "rotated_password_xyz"}

AWS_ROTATION_CONFIG_EXAMPLE = """
# AWS Console / CloudFormation:
# Secrets Manager → Secret → Rotation → Enable automatic rotation
# Rotation interval: 30 days
# Lambda function: SecretsManagerRDSPostgresRotationSingleUser (built-in)
#
# Rotation steps (AWS handles automatically):
# 1. Create a new password
# 2. Update the DB user's password (ALTER USER ... PASSWORD '...')
# 3. Test the new credentials
# 4. Set new password as the current secret version (AWSCURRENT label)
# 5. Mark old version as AWSPREVIOUS (available for 1 more rotation cycle)
"""

# ---------------------------------------------------------------------------
# 7. ZERO-DOWNTIME ROTATION STRATEGY
# ---------------------------------------------------------------------------
# Problem: rotating DB password causes downtime if app holds old connections.
# Solution: support BOTH old and new credentials during a rotation window.

class ZeroDowntimeRotationStrategy:
    """
    Implements a dual-credential approach for zero-downtime secret rotation.

    Rotation timeline:
      T=0  : New secret created. DB user updated to accept new password.
             Both old AND new passwords valid (DB supports multiple passwords
             or we use a secondary account approach).
      T=0→5min : Rolling restart of app pods — each new pod reads NEW password.
      T=5min : Old password disabled. Rotation complete.
    """

    def __init__(self):
        self.current_version = "v1"
        self.pending_version: Optional[str] = None
        self.rotation_started_at: Optional[datetime] = None
        # Window during which both credentials are valid
        self.rotation_window_seconds = 300  # 5 minutes

    def start_rotation(self, new_version: str) -> None:
        """
        Phase 1: Introduce new credential. Both old and new are valid.
        Trigger rolling restart of application pods.
        """
        self.pending_version = new_version
        self.rotation_started_at = datetime.now(timezone.utc)
        print(f"[Rotation] Started. Current={self.current_version}, "
              f"Pending={new_version}. Window={self.rotation_window_seconds}s")
        print("[Rotation] Both credentials are valid. Trigger rolling restart.")

    def is_in_rotation_window(self) -> bool:
        if not self.rotation_started_at:
            return False
        elapsed = (datetime.now(timezone.utc) - self.rotation_started_at).total_seconds()
        return elapsed < self.rotation_window_seconds

    def complete_rotation(self) -> None:
        """
        Phase 2: All pods restarted and using new credential.
        Revoke old credential.
        """
        if not self.pending_version:
            raise ValueError("No rotation in progress")
        old_version = self.current_version
        self.current_version = self.pending_version
        self.pending_version = None
        self.rotation_started_at = None
        print(f"[Rotation] Complete. Active={self.current_version}. "
              f"Revoking old version={old_version}")

    def validate_credential(self, version: str) -> bool:
        """
        During rotation window, both current and pending are valid.
        Outside window, only current is valid.
        """
        if version == self.current_version:
            return True
        if self.is_in_rotation_window() and version == self.pending_version:
            return True
        return False


# ---------------------------------------------------------------------------
# 8. SECRET SCANNING — GITLEAKS + PRE-COMMIT HOOK
# ---------------------------------------------------------------------------
# Detect secrets BEFORE they reach git history.
# Tools: gitleaks, truffleHog, detect-secrets, GitHub secret scanning.

PRE_COMMIT_HOOK_SCRIPT = """
#!/bin/sh
# .git/hooks/pre-commit
# Install: chmod +x .git/hooks/pre-commit
# Or use pre-commit framework: pip install pre-commit

# Run gitleaks on staged files only (fast scan, not full history)
gitleaks protect --staged --config .gitleaks.toml --no-banner

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Potential secrets detected in staged files!"
    echo "Remove the secret, add to .gitleaks.toml allowlist if false positive."
    echo "Run: gitleaks detect --source . --no-banner  (for full scan)"
    exit 1
fi
"""

GITLEAKS_CONFIG_EXAMPLE = """
# .gitleaks.toml
[extend]
useDefault = true   # includes AWS keys, GCP, Slack tokens, etc.

[[rules]]
id = "custom-internal-token"
description = "Internal API tokens prefixed with corp-"
regex = '''corp-[0-9a-zA-Z]{32}'''
tags = ["api-token", "internal"]

[allowlist]
# Paths to exclude from scanning (test fixtures, etc.)
paths = [
    "tests/fixtures/fake_credentials.py",
]
# Regex patterns that are known false positives
regexes = [
    "EXAMPLE_KEY_DO_NOT_USE",
]
"""

def run_gitleaks_scan(scan_full_history: bool = False) -> bool:
    """
    Run gitleaks programmatically. Returns True if clean, False if secrets found.
    In CI pipeline: fail the build on any finding.
    """
    cmd = ["gitleaks", "detect", "--no-banner", "--exit-code", "1"]
    if not scan_full_history:
        cmd.append("--log-opts=HEAD~1..HEAD")  # Only latest commit

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print("[gitleaks] Scan clean — no secrets detected.")
        return True
    else:
        print("[gitleaks] ALERT: Potential secrets found!")
        print(result.stdout)
        return False


# ---------------------------------------------------------------------------
# 9. ENVIRONMENT-SPECIFIC SECRETS ISOLATION
# ---------------------------------------------------------------------------
# Never share credentials across environments.
# Prod secrets must be inaccessible to dev workloads.

class SecretsEnvironmentPolicy:
    """
    Documents the isolation policy. Not executable logic — drives understanding.

    Vault namespaces:  /dev, /staging, /prod
    AWS accounts:      separate accounts per env (Account Vending Machine)
    IAM:               prod IAM roles not assumable by dev principals
    K8s:               separate clusters or namespaces with RBAC

    Access model:
      Dev engineers: full access to dev secrets, read-only staging, NO prod.
      SRE on-call:   break-glass access to prod (MFA + reason required, audited).
      CI/CD:         separate SA per env; prod SA only on protected branch pipelines.
    """

    ENV_VAULT_PATHS = {
        "dev":     "secret/dev/",
        "staging": "secret/staging/",
        "prod":    "secret/prod/",  # Vault policy: deny to non-prod K8s SA tokens
    }

    @staticmethod
    def get_secret_path(env: str, secret_name: str) -> str:
        base = SecretsEnvironmentPolicy.ENV_VAULT_PATHS.get(env)
        if not base:
            raise ValueError(f"Unknown environment: {env}")
        return f"{base}{secret_name}"


# ---------------------------------------------------------------------------
# 10. COMPLETE WORKFLOW DEMONSTRATION
# ---------------------------------------------------------------------------

def demonstrate_secrets_workflow():
    """
    End-to-end secrets workflow for a payment service pod in K8s.
    Combining Vault dynamic creds, TTL monitoring, and rotation strategy.
    """
    print("=" * 60)
    print("SECRETS MANAGEMENT WORKFLOW DEMO")
    print("=" * 60)

    # Step 1: Authenticate to Vault using K8s ServiceAccount
    vault = VaultClient(
        vault_addr=os.environ.get("VAULT_ADDR", "https://vault.internal:8200"),
        role="payments-service",
    )
    vault.authenticate_kubernetes()

    # Step 2: Get dynamic DB credentials (TTL = 1 hour)
    db_cred = vault.get_dynamic_db_creds("payments-rw")
    print(f"  Username: {db_cred.username}")
    print(f"  Expires:  {db_cred.expires_at.isoformat()}")

    # Step 3: Use credential — connect to DB
    # engine = create_engine(f"postgresql://{db_cred.username}:{db_cred.password}@db:5432/payments")

    # Step 4: Background thread monitors TTL and renews before expiry
    def credential_refresh_loop(cred: VaultCredential, vault_client: VaultClient):
        """Renew or replace credential at 80% of TTL to avoid expiry."""
        while True:
            time.sleep(60)  # Check every minute
            if cred.is_near_expiry(threshold_seconds=720):  # 12 min before 1h TTL
                vault_client.renew_lease(cred.lease_id, increment=3600)
                print("[CredRefresh] Lease renewed.")

    # Step 5: Zero-downtime rotation (triggered by ops team or automated)
    rotation = ZeroDowntimeRotationStrategy()
    rotation.start_rotation(new_version="v2")
    # ... rolling restart of pods happens here ...
    rotation.complete_rotation()

    # Step 6: On shutdown, revoke credential immediately
    vault.revoke_lease(db_cred.lease_id)

    # Step 7: Verify secret scanning is configured
    print("\n[SecretScan] Pre-commit hook: .git/hooks/pre-commit (gitleaks)")
    print("[SecretScan] CI step: gitleaks detect --no-banner --exit-code 1")
    print("[SecretScan] GitHub: secret scanning enabled on all repos (org setting)")

    print("\n[AWS] Fetching RDS password via Secrets Manager + IAM role:")
    secret_data = get_aws_secret("prod/payments/rds")
    print(f"  Retrieved password for user: {secret_data['username']}")


if __name__ == "__main__":
    demonstrate_secrets_workflow()
