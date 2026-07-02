# =============================================================================
# WHAT: TLS, Certificate Management, and Network Security
# WHY:  Unencrypted or improperly configured transport is the foundation of
#       man-in-the-middle attacks, credential theft, and data exfiltration.
#       Every backend engineer must understand TLS, cert chains, mTLS, and
#       network-level controls for service-to-service communication.
# LEVEL: Intermediate → Advanced
# =============================================================================

# CONCEPT OVERVIEW
# ----------------
# TLS (Transport Layer Security) provides:
#   Confidentiality  — AES-GCM or ChaCha20-Poly1305 encryption
#   Integrity        — AEAD (authenticated encryption, detects tampering)
#   Authentication   — X.509 certificates prove server identity
#
# TLS 1.3 (RFC 8446, 2018) — current standard:
#   - 1-RTT handshake (vs 2-RTT in 1.2)
#   - Perfect Forward Secrecy mandatory (ECDHE only)
#   - Removed: RSA key exchange, MD5, SHA-1, RC4, DES, 3DES
#   - 0-RTT session resumption (use with caution — replay risk)
#
# mTLS: both client and server present certificates → mutual authentication.
# Used for service mesh (Istio), internal microservices, zero-trust networks.

# PRODUCTION USE CASE
# -------------------
# Kubernetes cluster with Istio service mesh: every pod-to-pod call uses
# mTLS automatically. Cert-manager issues and rotates certificates from
# Let's Encrypt or an internal CA. Ingress controller terminates TLS from
# the internet; internal traffic is mTLS throughout.

# COMMON MISTAKES
# ---------------
# 1. verify=False in Python requests — disables ALL security guarantees
# 2. Accepting self-signed certs in production without pinning the CA
# 3. TLS 1.0/1.1 still enabled — vulnerable to BEAST, POODLE
# 4. Weak cipher suites (RC4, 3DES, RSA key exchange without PFS)
# 5. Letting certificates expire — monitoring is required
# 6. Not implementing HSTS — allows SSL stripping attacks
# 7. Trusting the system CA store when your app needs a specific internal CA

import ssl
import socket
import hashlib
import datetime
import subprocess
import json
import os
import logging
from dataclasses import dataclass
from typing import Any
from pathlib import Path

# Third-party (install as needed):
# pip install cryptography httpx certifi

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# =============================================================================
# SECTION 1: TLS 1.3 Handshake (Simplified)
# =============================================================================

TLS13_HANDSHAKE_STEPS = """
TLS 1.3 Full Handshake (1-RTT):

Client                                        Server
  |                                              |
  |--- ClientHello --------------------------->  |
  |    - TLS version: 1.3                        |
  |    - Supported cipher suites                 |
  |    - Key share (ECDH ephemeral public key)   |
  |    - Supported groups (X25519, P-256)        |
  |    - SNI (Server Name Indication)            |
  |                                              |
  |<-- ServerHello ----------------------------  |
  |    - Selected cipher suite                   |
  |    - Server's ECDH public key                |
  |    - [Everything below is now encrypted]     |
  |                                              |
  |<-- EncryptedExtensions --------------------  |
  |<-- Certificate (server's X.509 cert chain)   |
  |<-- CertificateVerify (signature over hash)   |
  |<-- Finished (HMAC of handshake transcript)   |
  |                                              |
  |--- Finished (client's HMAC) ------------->  |
  |                                              |
  |=== Symmetric encryption established ======  |
  |    Key derived via HKDF from ECDH secret     |

Key insight: server cert is sent ENCRYPTED in TLS 1.3 (unlike 1.2).
Both sides derive the same session keys without ever sending them.
PFS: if the private key is compromised later, past sessions cannot be decrypted.
"""

print("=== TLS 1.3 Handshake ===")
print(TLS13_HANDSHAKE_STEPS)


# =============================================================================
# SECTION 2: X.509 Certificate Anatomy
# =============================================================================

@dataclass
class CertificateInfo:
    """
    Human-readable representation of X.509 certificate fields.
    Use cryptography library to parse real certs.
    """
    subject_cn: str           # Common Name (legacy — use SAN instead)
    subject_org: str
    san_dns: list[str]        # Subject Alternative Names (what browsers check)
    san_ip: list[str]         # IP SANs for internal services
    issuer_cn: str            # CA that signed this cert
    issuer_org: str
    not_before: datetime.datetime
    not_after: datetime.datetime
    serial_number: str
    key_algorithm: str        # "RSA-2048", "EC-P256", "EC-P384"
    signature_algorithm: str  # "SHA256withRSA", "SHA384withECDSA"
    key_usage: list[str]      # "Digital Signature", "Key Encipherment"
    extended_key_usage: list[str]  # "TLS Web Server Authentication"
    is_ca: bool               # BasicConstraints: CA:TRUE
    subject_key_id: str       # fingerprint of public key
    authority_key_id: str     # fingerprint of issuing CA's public key

    @property
    def days_until_expiry(self) -> int:
        delta = self.not_after - datetime.datetime.utcnow()
        return delta.days

    @property
    def is_expired(self) -> bool:
        return datetime.datetime.utcnow() > self.not_after

    def expiry_status(self) -> str:
        days = self.days_until_expiry
        if days < 0:
            return f"EXPIRED {abs(days)} days ago"
        if days < 14:
            return f"CRITICAL — expires in {days} days"
        if days < 30:
            return f"WARNING — expires in {days} days"
        return f"OK — expires in {days} days"


def inspect_cert_openssl(hostname: str, port: int = 443) -> None:
    """
    Shell out to openssl to inspect a live certificate.
    Useful for debugging cert issues from Python scripts.
    """
    cmd = [
        "openssl", "s_client",
        "-connect", f"{hostname}:{port}",
        "-servername", hostname,    # SNI
        "-showcerts",
    ]
    print(f"\n[openssl] Inspecting {hostname}:{port}")
    print(f"Command: {' '.join(cmd)}")
    # In a real script: subprocess.run(cmd, input=b"", capture_output=True)


def get_cert_info_python(hostname: str, port: int = 443) -> dict[str, Any]:
    """
    Retrieve the server's certificate using Python's ssl module.
    Returns the cert dict from getpeercert().
    """
    # Create a context that validates the cert chain against system CAs
    ctx = ssl.create_default_context()   # loads system CA bundle

    try:
        with socket.create_connection((hostname, port), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as tls_sock:
                # getpeercert() returns None if cert not verified
                cert = tls_sock.getpeercert()
                cipher = tls_sock.cipher()   # (name, protocol, bits)
                version = tls_sock.version() # "TLSv1.3"
                logger.info(
                    "Connected to %s:%d — %s cipher=%s",
                    hostname, port, version, cipher[0]
                )
                return cert or {}
    except ssl.SSLCertVerificationError as e:
        logger.error("Certificate verification failed for %s: %s", hostname, e)
        raise
    except Exception as e:
        logger.warning("Could not connect to %s:%d — %s", hostname, e.__class__.__name__, e)
        return {}


# =============================================================================
# SECTION 3: Certificate Chain Validation
# =============================================================================

CERT_CHAIN_DIAGRAM = """
Certificate Chain (trust hierarchy):

  Root CA (self-signed, in OS/browser trust store)
    └── Intermediate CA (signed by Root CA)
          └── Leaf Certificate (signed by Intermediate, presented by server)

Validation steps:
  1. Server presents leaf cert + intermediate cert(s)
  2. Client checks leaf cert signature using Intermediate CA public key
  3. Client checks intermediate cert signature using Root CA public key
  4. Root CA must be in the client's trusted CA store
  5. Check validity period (not_before < now < not_after)
  6. Check that hostname matches SAN (or CN as fallback)
  7. Check revocation: CRL or OCSP (or OCSP stapling)
  8. Check key usage: serverAuth in extendedKeyUsage

WHY intermediate CAs:
  Root CA private keys are kept OFFLINE (air-gapped HSM).
  Intermediate CAs are online. If an intermediate is compromised,
  it can be revoked without touching the offline root.
"""

print(CERT_CHAIN_DIAGRAM)


# =============================================================================
# SECTION 4: Python ssl Module — SSLContext Configuration
# =============================================================================

def create_secure_client_context(
    ca_bundle: str | None = None,
    client_cert: str | None = None,
    client_key: str | None = None,
) -> ssl.SSLContext:
    """
    Create a hardened SSLContext for outbound connections.

    Args:
        ca_bundle:   Path to custom CA PEM file (for internal CAs).
                     If None, uses the system CA bundle.
        client_cert: Path to client certificate PEM (for mTLS).
        client_key:  Path to client private key PEM (for mTLS).
    """
    # PROTOCOL_TLS_CLIENT enforces:
    #   - Certificate verification (verify_mode = CERT_REQUIRED)
    #   - Hostname checking (check_hostname = True)
    #   - Minimum TLS 1.2 by default (set minimum_version below)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    # Enforce TLS 1.2 minimum; TLS 1.3 will be preferred automatically
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    # ctx.maximum_version = ssl.TLSVersion.TLSv1_3  # optionally restrict

    # Disable weak cipher suites explicitly (defense in depth)
    # OpenSSL cipher string: prefer ECDHE + AES-GCM or ChaCha20
    ctx.set_ciphers(
        "ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20"
        ":!aNULL:!eNULL:!RC4:!3DES:!MD5:!EXP:!PSK:!SRP:!DSS"
    )

    # Load CA bundle (use internal CA for service-to-service)
    if ca_bundle:
        ctx.load_verify_locations(cafile=ca_bundle)
    else:
        ctx.load_default_certs()   # system CA store

    # Load client cert for mTLS (see Section 5)
    if client_cert and client_key:
        ctx.load_cert_chain(certfile=client_cert, keyfile=client_key)

    # DO NOT set ctx.verify_mode = ssl.CERT_NONE — ever.
    # That disables all security. Use CERT_REQUIRED (default in PROTOCOL_TLS_CLIENT).

    return ctx


def create_secure_server_context(
    certfile: str,
    keyfile: str,
    ca_file: str | None = None,
    require_client_cert: bool = False,
) -> ssl.SSLContext:
    """
    Create a hardened SSLContext for a server socket.

    Args:
        certfile:            Server's certificate (PEM, leaf + chain)
        keyfile:             Server's private key (PEM)
        ca_file:             CA for verifying client certs (mTLS)
        require_client_cert: If True, enforce mutual TLS
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)

    # Enable session tickets for TLS 1.2 performance
    # TLS 1.3 has its own session resumption mechanism
    ctx.options |= ssl.OP_NO_COMPRESSION   # CRIME attack mitigation

    if require_client_cert:
        # mTLS: reject clients that don't present a valid cert
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(cafile=ca_file)

    return ctx


print("=== SSL Context Factory ===")
print("create_secure_client_context() and create_secure_server_context() defined.")


# =============================================================================
# SECTION 5: Mutual TLS (mTLS) — Service-to-Service Authentication
# =============================================================================

MTLS_EXPLANATION = """
mTLS: both parties authenticate with X.509 certificates.
WHY: in a microservices architecture, you want to ensure:
  - Service A is really talking to Service B (not a rogue pod)
  - Service B knows the caller is really Service A (not a compromised pod)
  - All traffic is encrypted (even inside the cluster)

Certificate issuance for mTLS:
  1. Each service gets a unique cert with its identity in the SAN:
     SAN: URI:spiffe://cluster.local/ns/default/sa/payments-service
  2. Certs are issued by an internal CA (Vault PKI, cert-manager)
  3. Short TTL (24h–7d) to limit blast radius of a compromised cert
  4. Istio / Linkerd automate all of the above transparently

Python client making an mTLS request:
"""

MTLS_PYTHON_EXAMPLE = """
import httpx

# Both client and server present certificates
client = httpx.Client(
    cert=("/run/secrets/client.crt", "/run/secrets/client.key"),
    verify="/run/secrets/ca.crt",    # internal CA cert for server verification
)

response = client.get("https://payments-service.internal/api/charge")
# If the server rejects our cert, SSLError is raised.
# If we reject the server's cert, SSLError is raised.
# Both sides are authenticated.
"""

print("\n=== mTLS ===")
print(MTLS_EXPLANATION)
print(MTLS_PYTHON_EXAMPLE)


# =============================================================================
# SECTION 6: Let's Encrypt + Certbot + Auto-Renewal
# =============================================================================

LETS_ENCRYPT_COMMANDS = """
# ---- Let's Encrypt via Certbot ----
# Free, automated, DV (domain-validated) certificates.
# WHY: Eliminates cert cost and removes the excuse to skip HTTPS.

# Obtain a cert (standalone mode — temporarily binds port 80)
certbot certonly --standalone -d api.example.com -d www.example.com

# Obtain a cert using DNS challenge (wildcard certs, no port 80 needed)
certbot certonly --dns-cloudflare \\
  --dns-cloudflare-credentials ~/.secrets/cloudflare.ini \\
  -d "*.example.com" -d "example.com"

# Renew all certs (Let's Encrypt certs expire in 90 days)
certbot renew --pre-hook "systemctl stop nginx" \\
              --post-hook "systemctl start nginx"

# Cert files after issuance:
#   /etc/letsencrypt/live/api.example.com/fullchain.pem  (cert + chain)
#   /etc/letsencrypt/live/api.example.com/privkey.pem    (private key)
#   /etc/letsencrypt/live/api.example.com/cert.pem       (cert only)
#   /etc/letsencrypt/live/api.example.com/chain.pem      (intermediate only)

# Automate renewal via cron (certbot renew is idempotent if cert is valid)
# Add to crontab:
# 0 3 * * * certbot renew --quiet --post-hook "nginx -s reload"
"""

print("\n=== Let's Encrypt ===")
print(LETS_ENCRYPT_COMMANDS)


# =============================================================================
# SECTION 7: Certificate Pinning
# =============================================================================

def compute_cert_pin(cert_der: bytes) -> str:
    """
    Compute the SPKI (Subject Public Key Info) pin of a certificate.
    This is the same pin format used by HPKP and modern certificate pinning.

    WHY SPKI pin and not the whole cert: the pin survives cert renewal
    as long as the key pair is reused (which is common for public keys
    on mobile/desktop apps where the key is managed separately).
    """
    # In a real implementation, parse the DER to extract just the SPKI field.
    # Here we hash the entire DER as a simplified demonstration.
    sha256_digest = hashlib.sha256(cert_der).digest()
    return "sha256/" + hashlib.sha256(cert_der).digest().hex()


CERT_PINNING_NOTES = """
Certificate Pinning:
  WHY: Protects against a compromised or malicious CA issuing a cert for
       your domain. Even if a rogue CA is trusted by the OS, the pin rejects
       it because it doesn't match the expected public key.

  HPKP (HTTP Public Key Pinning) — DEPRECATED (RFC 7469):
    - Set via HTTP header: Public-Key-Pins: pin-sha256="..."; max-age=5184000
    - Removed from Chrome and Firefox because misconfiguration = site outage.
    - Do NOT use HPKP.

  Modern alternatives:
    1. CAA DNS records: specify which CAs are allowed to issue certs for your domain.
       example.com. IN CAA 0 issue "letsencrypt.org"
       example.com. IN CAA 0 issuewild ";"   (disallow wildcard)

    2. Certificate Transparency (CT): all certs must be logged in public CT logs.
       Browsers reject certs not in CT. Allows post-issuance detection of rogue certs.
       Monitor: https://crt.sh/?q=example.com

    3. DANE (DNS-based Authentication of Named Entities):
       Pin cert or key in TLSA DNS records. Requires DNSSEC. Less common.

    4. Hard-coded pins in mobile/desktop apps:
       Appropriate when the app controls the cert lifecycle.
       Provide a backup pin to avoid bricking the app on renewal.
"""

print("\n=== Certificate Pinning ===")
print(CERT_PINNING_NOTES)


# =============================================================================
# SECTION 8: Perfect Forward Secrecy and Cipher Suites
# =============================================================================

CIPHER_SUITE_NOTES = """
TLS 1.3 Cipher Suites (the only ones allowed):
  TLS_AES_256_GCM_SHA384          — preferred for high-security
  TLS_AES_128_GCM_SHA256          — good performance/security balance
  TLS_CHACHA20_POLY1305_SHA256    — preferred on mobile (CPU without AES-NI)

TLS 1.2 Cipher Suites (safe subset):
  ECDHE-ECDSA-AES256-GCM-SHA384  — ECDSA cert, ECDHE key exchange, PFS
  ECDHE-RSA-AES256-GCM-SHA384    — RSA cert, ECDHE key exchange, PFS
  ECDHE-RSA-CHACHA20-POLY1305     — good for mobile clients

AVOID in TLS 1.2:
  RSA key exchange (no PFS)       — recorded traffic = decryptable with key
  DHE-RSA (old DH params)         — Logjam vulnerability if params < 2048 bit
  RC4 — broken stream cipher
  3DES — SWEET32 birthday attack (64-bit block cipher)
  NULL ciphers — no encryption!
  EXPORT ciphers — intentionally weakened for 1990s US export law

Perfect Forward Secrecy (PFS):
  In ECDHE key exchange, ephemeral key pairs are generated per session.
  The server's long-term private key is used only for authentication (signature).
  If the server's private key is stolen years later, recorded sessions cannot
  be decrypted — each session's ephemeral key has been discarded.
"""

print("\n=== Cipher Suites and PFS ===")
print(CIPHER_SUITE_NOTES)


# =============================================================================
# SECTION 9: HSTS — HTTP Strict Transport Security
# =============================================================================

HSTS_NOTES = """
HSTS tells browsers: "Always use HTTPS for this domain, even if the user types
http:// or clicks an http:// link."

WHY: Prevents SSL stripping attacks where a MITM downgrades HTTPS to HTTP.

HTTP Response Header:
  Strict-Transport-Security: max-age=31536000; includeSubDomains; preload

Fields:
  max-age=31536000     — 1 year in seconds (minimum for preload list)
  includeSubDomains    — apply HSTS to all subdomains
  preload              — request inclusion in browser preload list (hardcoded HTTPS)

HSTS Preload List:
  Submit at https://hstspreload.org/
  Once in the list, the browser refuses HTTP for your domain even on first visit.
  WARNING: preload is hard to undo — max-age must remain >= 1 year.

Deployment:
  - Add the header from your web server / reverse proxy (nginx, caddy, traefik)
  - Never add HSTS to HTTP responses (the browser ignores it)
  - Start with a short max-age (3600) and extend after validation
"""

print("\n=== HSTS ===")
print(HSTS_NOTES)

# Python/FastAPI middleware example
HSTS_MIDDLEWARE = '''
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

class HSTSMiddleware(BaseHTTPMiddleware):
    """Add HSTS header to every HTTPS response."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        # Only add HSTS on HTTPS connections
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )
        return response

app = FastAPI()
app.add_middleware(HSTSMiddleware)
'''

print(HSTS_MIDDLEWARE)


# =============================================================================
# SECTION 10: TLS in Kubernetes — cert-manager, Ingress TLS, Istio mTLS
# =============================================================================

CERT_MANAGER_YAML = """
# ---- cert-manager: Automated TLS for Kubernetes ----
# Installs as a controller. Issues/renews certs via Let's Encrypt or Vault.

# ClusterIssuer (ACME / Let's Encrypt)
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: ops@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
      - http01:
          ingress:
            class: nginx     # ACME challenge via HTTP-01

# Certificate resource (cert-manager watches this and issues the cert)
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: api-tls
  namespace: default
spec:
  secretName: api-tls-secret      # K8s Secret where cert+key are stored
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - api.example.com
  renewBefore: 720h                # renew 30 days before expiry

# Ingress using the cert
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: api-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  tls:
    - hosts: [api.example.com]
      secretName: api-tls-secret
  rules:
    - host: api.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: {name: api-service, port: {number: 8080}}
"""

ISTIO_MTLS_YAML = """
# ---- Istio: Automatic mTLS for Service Mesh ----
# With Istio installed, all traffic between pods uses mTLS automatically.
# Certs are issued by Istio's CA (istiod) and rotated every 24h.

# Enforce STRICT mTLS (reject plaintext traffic from outside mesh)
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: default
spec:
  mtls:
    mode: STRICT    # PERMISSIVE allows plaintext (migration mode)

# AuthorizationPolicy: only allow payments-service to call billing-service
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: billing-authz
  namespace: default
spec:
  selector:
    matchLabels:
      app: billing-service
  action: ALLOW
  rules:
    - from:
        - source:
            principals:
              # SPIFFE ID of the caller (from its mTLS cert)
              - "cluster.local/ns/default/sa/payments-service"
      to:
        - operation:
            methods: ["POST"]
            paths: ["/api/charge"]
"""

print("\n=== Kubernetes TLS (cert-manager + Istio) ===")
print("See CERT_MANAGER_YAML and ISTIO_MTLS_YAML strings above.")


# =============================================================================
# SECTION 11: Kubernetes Network Policies
# =============================================================================

NETWORK_POLICY_YAML = """
# Best practice: default deny-all, then explicitly allow what is needed.
# WHY: reduces blast radius if a pod is compromised.

# Default deny all ingress + egress in the default namespace
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: default
spec:
  podSelector: {}      # matches all pods
  policyTypes:
    - Ingress
    - Egress

# Allow payments-service to receive traffic only from api-gateway
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-api-to-payments
  namespace: default
spec:
  podSelector:
    matchLabels:
      app: payments-service
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: api-gateway
      ports:
        - protocol: TCP
          port: 8080

# Allow DNS egress for all pods (required for service discovery)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: default
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
"""

print("\n=== Network Policies ===")
print("default-deny-all + explicit allow-list = zero-trust network posture.")


# =============================================================================
# SECTION 12: SSH Key Management Best Practices
# =============================================================================

SSH_BEST_PRACTICES = """
SSH Key Management:

Key Generation:
  # Preferred: Ed25519 (small, fast, secure)
  ssh-keygen -t ed25519 -C "deploy@ci-system" -f ~/.ssh/deploy_ed25519

  # Acceptable: RSA 4096 (wider compatibility)
  ssh-keygen -t rsa -b 4096 -C "user@example.com"

  # Avoid: DSA (broken), RSA-1024 (too short), ECDSA with NIST curves (RNG concerns)

Key Passphrase:
  Always set a passphrase on private keys stored on human laptops.
  Use ssh-agent or 1Password SSH agent to avoid typing it every time.

SSH CA (Certificate Authority):
  # WHY: eliminates the need to distribute individual public keys.
  #      One CA cert on servers; issue user certs with short TTL.

  # Create SSH CA (do this once, keep CA key offline)
  ssh-keygen -t ed25519 -f ssh_ca

  # Sign a user's public key (issue a cert valid for 8 hours)
  ssh-keygen -s ssh_ca \\
    -I "alice@example.com" \\    # key ID (logged on server)
    -n "ec2-user,ubuntu" \\      # authorized principals (usernames)
    -V "+8h" \\                  # validity period
    ~/.ssh/alice_ed25519.pub
  # Creates alice_ed25519-cert.pub

  # Server trusts the CA (instead of individual keys)
  # In /etc/ssh/sshd_config:
  # TrustedUserCAKeys /etc/ssh/ssh_ca.pub

  # User logs in with cert (automatic, transparent)
  ssh -i ~/.ssh/alice_ed25519 -i ~/.ssh/alice_ed25519-cert.pub ec2-user@host

Rotation:
  - User keys: rotate on role change, departure, or suspected compromise
  - Deploy keys: use per-repo keys with read-only access; rotate quarterly
  - CA keys: rotate annually; re-issue all user certs

Audit:
  - Log all SSH logins to a SIEM
  - Use SSH CA with short TTL (8h–24h) so ex-employees auto-lose access
  - Never use shared SSH accounts (one key per human/service)
"""

print("\n=== SSH Key Management ===")
print(SSH_BEST_PRACTICES)


# =============================================================================
# SECTION 13: Certificate Expiry Monitoring
# =============================================================================

def check_cert_expiry(hostname: str, port: int = 443, warn_days: int = 30) -> dict[str, Any]:
    """
    Check certificate expiry for a hostname.
    Run this in a monitoring job; alert when days_remaining < warn_days.
    """
    result: dict[str, Any] = {"hostname": hostname, "port": port, "error": None}

    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((hostname, port), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as tls_sock:
                cert = tls_sock.getpeercert()
                if not cert:
                    result["error"] = "no certificate returned"
                    return result

                # Parse expiry date from cert dict
                not_after_str = cert["notAfter"]   # e.g. "Jun 30 12:00:00 2026 GMT"
                not_after = datetime.datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z")
                days_remaining = (not_after - datetime.datetime.utcnow()).days

                result.update({
                    "not_after": not_after.isoformat(),
                    "days_remaining": days_remaining,
                    "subject": dict(x[0] for x in cert.get("subject", [])),
                    "issuer":  dict(x[0] for x in cert.get("issuer", [])),
                    "san":     [v for _, v in cert.get("subjectAltName", [])],
                    "status": "WARN" if days_remaining < warn_days else "OK",
                })
                if days_remaining < 0:
                    result["status"] = "EXPIRED"

    except ssl.SSLCertVerificationError as e:
        result["error"] = f"SSL verification failed: {e}"
    except (socket.timeout, ConnectionRefusedError) as e:
        result["error"] = f"Connection failed: {e}"
    except Exception as e:
        result["error"] = f"Unexpected: {e.__class__.__name__}: {e}"

    return result


print("\n=== Certificate Expiry Monitoring ===")
# Demonstrate with a real-world call (skipped in offline context)
# result = check_cert_expiry("google.com")
# print(json.dumps(result, indent=2))
print("check_cert_expiry('api.example.com') — run in a cron job every 6h.")
print("Alert when days_remaining < 30. Page when < 7.")

print("\n=== TLS & Network Security Summary ===")
print("TLS 1.3    : mandatory for new services; 1-RTT, PFS, encrypted certs")
print("Ciphers    : AES-256-GCM, ChaCha20-Poly1305 only; disable RC4/3DES")
print("Certs      : SANs not CN; automate with cert-manager or Vault PKI")
print("mTLS       : service-to-service auth; use Istio for transparent injection")
print("HSTS       : max-age >= 1y + includeSubDomains for public services")
print("Pinning    : use CAA DNS + CT monitoring; avoid HPKP")
print("K8s        : cert-manager for ingress TLS; NetworkPolicy deny-all default")
print("SSH        : Ed25519 + SSH CA with short TTL > individual authorized_keys")
