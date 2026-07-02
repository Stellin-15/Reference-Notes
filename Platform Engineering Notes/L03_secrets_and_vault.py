# ============================================================
# L03: Secrets Management — HashiCorp Vault
# ============================================================
# WHAT: A centralized system for storing, generating, and revoking secrets
#       (DB creds, API keys, TLS certs) with fine-grained access policies.
# WHY (PRODUCTION): Static secrets in .env files or environment variables
#       leak (git history, CI logs, container image layers) and never
#       rotate. Vault issues short-lived, dynamically generated secrets
#       that expire automatically — a compromised credential is only
#       useful for minutes, not years.
# LEVEL: Senior backend / platform / security engineer
# ============================================================

"""
CONCEPT OVERVIEW:
Vault sits between applications and the actual credential stores (databases,
cloud IAM, PKI). Instead of a service reading a hardcoded DB password, it
authenticates to Vault (proving its identity via Kubernetes service account,
AWS IAM role, etc.) and requests a *lease* on a secret. Vault generates a
brand-new, unique credential on demand and automatically revokes it when the
lease expires.

Architecture: core (request routing) -> barrier (encrypted storage layer,
sealed/unsealed via Shamir secret sharing) -> secrets engines (KV, database,
PKI, AWS...) -> auth methods (how callers prove identity) -> audit devices
(tamper-evident log of every secret access).

PRODUCTION USE CASE:
A payments service needs Postgres credentials. Instead of a static
`DATABASE_URL` env var, it authenticates to Vault using its Kubernetes
service account token, requests `database/creds/billing-readwrite`, and gets
back a username/password pair with a 1-hour TTL. Vault created that Postgres
role on the fly and will DROP it automatically when the lease expires or is
revoked. If the credential leaks in a log, it's useless within the hour.

COMMON MISTAKES:
- Using Vault only as a fancy KV store (static secrets) and never adopting
  dynamic secrets — you get the operational overhead without the main
  security benefit.
- Not automating unseal (manual Shamir unseal after every restart is an
  outage waiting to happen — use auto-unseal via cloud KMS).
- Overly broad policies (`path "secret/*" { capabilities = ["read"] }`)
  that defeat the purpose of per-service least privilege.
"""

import textwrap

# ------------------------------------------------------------------
# 1. Secrets engines
# ------------------------------------------------------------------
SECRETS_ENGINES = {
    "kv-v2": "Versioned static key-value store. Soft-delete + version history. "
             "Use for things that genuinely can't be dynamic (a third-party API key).",
    "database": "Generates short-lived DB credentials on demand (Postgres, MySQL, "
                "MongoDB...). Vault owns a privileged admin connection and creates "
                "throwaway roles per lease.",
    "pki": "Acts as an internal Certificate Authority — issues short-lived TLS "
           "certs on request instead of managing a manual cert lifecycle.",
    "aws": "Generates temporary IAM credentials (STS tokens or IAM user keys) "
           "scoped to a specific policy, with automatic expiry.",
    "transit": "Encryption-as-a-service — apps send plaintext to Vault, get "
               "ciphertext back, without ever handling the encryption key "
               "themselves ('encryption as a service' pattern).",
}

# ------------------------------------------------------------------
# 2. Dynamic database secrets — the flagship feature
# ------------------------------------------------------------------
DYNAMIC_DB_SECRETS_SETUP = textwrap.dedent("""\
    # Step 1: enable the database secrets engine
    vault secrets enable database

    # Step 2: configure Vault with a privileged connection to Postgres.
    # Vault uses THIS connection to create/drop the short-lived roles below.
    vault write database/config/billing-postgres \\
        plugin_name=postgresql-database-plugin \\
        connection_url="postgresql://{{username}}:{{password}}@billing-db:5432/billing" \\
        allowed_roles="billing-readwrite,billing-readonly" \\
        username="vault-admin" \\
        password="<rotated-via-vault-itself>"

    # Step 3: define a role — the SQL Vault runs to CREATE a lease-scoped user
    vault write database/roles/billing-readwrite \\
        db_name=billing-postgres \\
        creation_statements="CREATE ROLE \\"{{name}}\\" WITH LOGIN PASSWORD '{{password}}' \\
            VALID UNTIL '{{expiration}}'; \\
            GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO \\"{{name}}\\";" \\
        default_ttl="1h" \\
        max_ttl="24h"

    # Step 4 (application side): request a credential
    vault read database/creds/billing-readwrite
    # -> username: v-approle-billing-rea-XXXXXXXXXXXX
    #    password: A1a-<random>
    #    lease_id: database/creds/billing-readwrite/abcd1234
    #    lease_duration: 3600
    # Vault auto-revokes (DROPs the role) when the lease expires unless renewed.
""")

# ------------------------------------------------------------------
# 3. Auth methods — how services prove identity to Vault
# ------------------------------------------------------------------
AUTH_METHODS = textwrap.dedent("""\
    # Kubernetes auth — the standard for services running in K8s.
    # Vault validates the pod's service account JWT against the K8s API.
    vault auth enable kubernetes
    vault write auth/kubernetes/config \\
        kubernetes_host="https://kubernetes.default.svc"

    vault write auth/kubernetes/role/billing-service \\
        bound_service_account_names=billing-service \\
        bound_service_account_namespaces=payments \\
        policies=billing-service-policy \\
        ttl=1h

    # From inside the pod, the app reads its own SA token and logs in:
    # vault write auth/kubernetes/login role=billing-service jwt=@/var/run/secrets/.../token

    # AppRole — for CI/CD pipelines or non-K8s workloads. RoleID is
    # semi-public (like a username); SecretID is the actual secret,
    # distributed out-of-band (e.g. injected as a masked CI variable).
    vault auth enable approle
    vault write auth/approle/role/ci-pipeline \\
        token_policies="ci-deploy-policy" \\
        token_ttl=15m \\
        secret_id_ttl=10m
""")

# ------------------------------------------------------------------
# 4. Policies (HCL ACLs) — least-privilege access
# ------------------------------------------------------------------
VAULT_POLICY_EXAMPLE = textwrap.dedent("""\
    # billing-service-policy.hcl
    # Only allow reading dynamic DB creds for this one role — nothing else.
    path "database/creds/billing-readwrite" {
      capabilities = ["read"]
    }

    # Allow reading (not writing/listing) one specific KV secret.
    path "secret/data/billing-service/stripe-api-key" {
      capabilities = ["read"]
    }

    # Explicitly NOT granting "list" on secret/* — prevents this service
    # from enumerating every other team's secret paths.
""")

# ------------------------------------------------------------------
# 5. Vault Agent — sidecar injection pattern
# ------------------------------------------------------------------
# Vault Agent handles auth + secret fetching + renewal OUTSIDE the app
# process, writing rendered secrets to a shared volume/file the app reads.
# This means the application code never talks to the Vault API directly.
VAULT_AGENT_TEMPLATE = textwrap.dedent("""\
    # vault-agent-config.hcl
    auto_auth {
      method "kubernetes" {
        mount_path = "auth/kubernetes"
        config = { role = "billing-service" }
      }
      sink "file" {
        config = { path = "/vault/token" }
      }
    }

    template {
      source      = "/vault/templates/db-creds.tpl"
      destination = "/vault/secrets/db-creds.env"
      # re-renders automatically before the lease expires (renewal happens
      # transparently — the app just re-reads the file periodically)
    }
""")

# ------------------------------------------------------------------
# 6. Response wrapping — single-use secret bootstrap
# ------------------------------------------------------------------
# Used to hand a secret to a process (e.g. a CI job) through an
# untrusted channel: Vault wraps the response in a one-time-use token.
# If it's intercepted and unwrapped by an attacker first, the real
# recipient's unwrap call fails — signaling compromise immediately.
RESPONSE_WRAPPING_NOTE = (
    "vault write -wrap-ttl=60s auth/approle/role/ci-pipeline/secret-id\n"
    "# -> returns a wrapping_token, not the secret itself\n"
    "# CI job unwraps it: vault unwrap <wrapping_token>\n"
    "# If already unwrapped once, the second unwrap call errors — tamper detection."
)

# ------------------------------------------------------------------
# 7. Seal/unseal and HA
# ------------------------------------------------------------------
SEAL_AND_HA = textwrap.dedent("""\
    # On startup, Vault's storage is ENCRYPTED (sealed). It needs a quorum
    # of Shamir key shares (e.g. 3 of 5) to reconstruct the master key and
    # unseal. Manual unseal after every pod restart is an operational
    # nightmare in Kubernetes — use auto-unseal via a cloud KMS instead:

    seal "awskms" {
      region     = "us-east-1"
      kms_key_id = "alias/vault-unseal-key"
    }
    # Vault now unseals itself automatically using KMS to decrypt the
    # master key, no human intervention required on restart.

    # HA storage backend: Integrated Storage (Raft) is the modern default —
    # no external Consul cluster needed. Vault nodes form a Raft cluster,
    # elect a leader, and replicate the encrypted data automatically.
    storage "raft" {
      path    = "/vault/data"
      node_id = "vault-1"
    }
""")

if __name__ == "__main__":
    print("Secrets engines available:")
    for name, desc in SECRETS_ENGINES.items():
        print(f"  {name}: {desc}")

"""
TRADING/PRODUCTION CONTEXT EXAMPLE:
An order-execution service needs credentials for the exchange's FIX gateway
and the internal risk database. Both are dynamic Vault leases with 15-minute
TTLs, fetched via Vault Agent sidecar and injected as files, never as env
vars (env vars leak into process listings and crash dumps). If the pod is
compromised, the attacker's window to abuse the credential is bounded to the
remaining lease time — after which Vault revokes it and the attacker is
locked out without anyone manually rotating anything.
"""
