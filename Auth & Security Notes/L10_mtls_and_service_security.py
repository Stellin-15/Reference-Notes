# ============================================================
# L07: mTLS and Service-to-Service Security
# ============================================================
# WHAT: Mutual TLS, service mesh identity (SPIFFE/SPIRE),
#       JWT service tokens, network policy, and container
#       hardening for zero-trust microservice architectures.
# WHY:  Inside a Kubernetes cluster, services on the same
#       network can call each other directly. Without mTLS
#       and NetworkPolicy, a compromised pod can reach any
#       other service — lateral movement is trivial.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    mTLS (mutual TLS) extends standard TLS by requiring both
    the client and the server to present valid certificates.
    Regular TLS only authenticates the server (browser trusts
    the bank's cert). mTLS authenticates both sides — the
    server knows it's talking to a legitimate peer service,
    not an attacker who gained network access.

    In a service mesh (Istio, Linkerd), mTLS is transparent:
    the sidecar proxy handles cert issuance, rotation, and
    handshake. No app code changes are needed. Every byte of
    service-to-service traffic is encrypted and authenticated.

    SPIFFE (Secure Production Identity Framework For Everyone)
    is the identity standard. Each workload gets a URI-based
    identity: spiffe://trust-domain/ns/namespace/sa/svcaccount.
    SPIRE is the production implementation of SPIFFE.

    JWT service tokens add an application-layer identity check
    on top of mTLS — useful for services not behind a mesh.

PRODUCTION USE CASE:
    An e-commerce platform runs payments-service, orders-service,
    and inventory-service in K8s. Istio enforces STRICT mTLS across
    the mesh. AuthorizationPolicy allows payments-service to call
    orders-service, but inventory-service cannot call payments-service.
    NetworkPolicy provides a second layer of enforcement even if Istio
    misconfiguration occurs. Containers run as UID 1001 with read-only
    root filesystems and all Linux capabilities dropped.

COMMON MISTAKES:
    1. Permissive mTLS mode (only encrypts, doesn't verify client cert).
    2. No AuthorizationPolicy — mTLS encrypts but any service can call any.
    3. Trusting network location instead of service identity.
    4. Certificates with 10-year lifetimes (long breach window).
    5. Running pods as root (UID 0) — trivial container escape.
    6. Writable root filesystem — attacker can modify binaries.
    7. No NetworkPolicy default-deny — allows east-west lateral movement.
    8. JWT service tokens with no expiry (iat without exp).
"""

import os
import time
import json
import base64
import hashlib
import hmac
import struct
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. mTLS CONCEPTS
# ---------------------------------------------------------------------------
# Standard TLS handshake:
#   Client → Server: "I want TLS"
#   Server → Client: "Here's my certificate" (signed by trusted CA)
#   Client verifies the server cert → encrypted channel established
#   Client identity: UNKNOWN. Anyone on the network can connect.

# mTLS handshake (both sides authenticate):
#   Client → Server: "I want TLS, here's MY certificate"
#   Server → Client: "Here's MY certificate. I verify yours."
#   Both sides verify each other's certs against the same CA trust bundle.
#   Result: encrypted channel WHERE BOTH IDENTITIES ARE VERIFIED.

MTLS_OPENSSL_DEMO = """
# Generate a CA (in production this is SPIRE or cert-manager)
openssl genrsa -out ca.key 4096
openssl req -new -x509 -days 365 -key ca.key -out ca.crt \\
  -subj "/CN=internal-ca/O=example.com"

# Generate service certificate (orders-service)
openssl genrsa -out orders.key 2048
openssl req -new -key orders.key -out orders.csr \\
  -subj "/CN=orders-service/O=example.com"
  # SPIFFE URI goes in the SAN: URI:spiffe://example.com/ns/prod/sa/orders
openssl x509 -req -days 90 -in orders.csr -CA ca.crt -CAkey ca.key \\
  -CAcreateserial -out orders.crt

# mTLS Python server (for illustration — Istio sidecar does this automatically)
import ssl
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain('orders.crt', 'orders.key')
context.load_verify_locations('ca.crt')
context.verify_mode = ssl.CERT_REQUIRED  # <-- require client cert
# server = HTTPServer(...); server.socket = context.wrap_socket(...)
"""

# ---------------------------------------------------------------------------
# 2. ISTIO SERVICE MESH — POLICIES
# ---------------------------------------------------------------------------
# Istio injects an Envoy sidecar into each Pod. The sidecar intercepts all
# traffic, handles mTLS automatically, and enforces access policies.
# App code sees plain HTTP — mTLS happens at the sidecar layer.

ISTIO_PEER_AUTHENTICATION = """
# PeerAuthentication: enforce mTLS in the 'prod' namespace.
# STRICT = require client cert. PERMISSIVE = optional (transition mode only).
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: prod
spec:
  mtls:
    mode: STRICT    # Any connection without a valid client cert is dropped
                    # Never leave in PERMISSIVE in production
"""

ISTIO_AUTHORIZATION_POLICY = """
# AuthorizationPolicy: only payments-service can call orders-service.
# mTLS gives us the caller's identity (SPIFFE URI) → policy enforces it.
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: orders-service-policy
  namespace: prod
spec:
  selector:
    matchLabels:
      app: orders-service
  action: ALLOW
  rules:
    - from:
        - source:
            # SPIFFE identity of payments-service pod
            principals:
              - "cluster.local/ns/prod/sa/payments-service"
      to:
        - operation:
            methods: ["POST", "GET"]
            paths: ["/orders/*"]
---
# Default deny: block everything not explicitly allowed above.
# Without this, the ALLOW policy above is additive — other traffic still passes.
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: deny-all
  namespace: prod
spec:
  {}   # Empty spec = deny all (no selector = applies to all workloads)
"""

# ---------------------------------------------------------------------------
# 3. SPIFFE/SPIRE — WORKLOAD IDENTITY
# ---------------------------------------------------------------------------
# SPIFFE URI format: spiffe://<trust-domain>/ns/<namespace>/sa/<service-account>
# Example:           spiffe://example.com/ns/prod/sa/payments-service
#
# SPIRE architecture:
#   SPIRE Server: root of trust, signs SVIDs (certs)
#   SPIRE Agent: runs on each node, attests workload identity (via K8s API),
#                fetches SVID from server, delivers via Unix socket to workload
#   Workload API: SVID rotated every 24h — no manual cert management

@dataclass
class SPIFFEIdentity:
    """Represents a SPIFFE Verifiable Identity Document (SVID)."""
    trust_domain: str       # e.g. "example.com"
    namespace: str          # K8s namespace
    service_account: str    # K8s ServiceAccount name
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    valid_for_hours: int = 24  # Certificates rotate every 24 hours

    @property
    def spiffe_id(self) -> str:
        """The SPIFFE URI — unique identity of this workload."""
        return f"spiffe://{self.trust_domain}/ns/{self.namespace}/sa/{self.service_account}"

    @property
    def expires_at(self) -> datetime:
        return self.issued_at + timedelta(hours=self.valid_for_hours)

    def is_valid(self) -> bool:
        return datetime.now(timezone.utc) < self.expires_at

    def __repr__(self) -> str:
        return (
            f"SPIFFEIdentity(id={self.spiffe_id}, "
            f"expires={self.expires_at.strftime('%Y-%m-%dT%H:%M:%SZ')})"
        )


SPIRE_K8S_CONFIG = """
# SPIRE Agent registering a workload entry:
# (Usually managed by SPIRE Controller Manager automatically)
spire-server entry create \\
  -spiffeID spiffe://example.com/ns/prod/sa/payments-service \\
  -parentID spiffe://example.com/spire/agent/k8s_sat/node-01 \\
  -selector k8s:ns:prod \\
  -selector k8s:sa:payments-service

# Workload receives SVID via /run/spire/sockets/agent.sock (Workload API)
# SVID = X.509 certificate with SPIFFE URI in SAN field
# Auto-rotated every 24h — no manual rotation needed
"""

# ---------------------------------------------------------------------------
# 4. JWT SERVICE TOKENS (APPLICATION-LAYER IDENTITY)
# ---------------------------------------------------------------------------
# Used when services are not in a mesh (e.g., calling an external service
# or a legacy service without Istio sidecar). The calling service signs a
# JWT with its private key. The recipient verifies with the caller's public key.
#
# This is an APPLICATION-layer check ON TOP of mTLS, not instead of it.

class JWTServiceToken:
    """
    Minimal HS256 JWT implementation for service-to-service calls.
    In production use PyJWT (pip install PyJWT) — this shows the mechanics.
    """

    def __init__(self, signing_key: bytes):
        # signing_key: shared secret (for HS256) or private key bytes (for RS256)
        # RS256 preferred: each service has its own key pair, no shared secret
        self.signing_key = signing_key

    def _b64url_encode(self, data: bytes) -> str:
        """URL-safe base64 without padding (JWT standard)."""
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    def _b64url_decode(self, data: str) -> bytes:
        # Add padding back before decoding
        padding = 4 - len(data) % 4
        if padding != 4:
            data += "=" * padding
        return base64.urlsafe_b64decode(data)

    def generate_token(
        self,
        issuer: str,       # Calling service: "payments-service"
        audience: str,     # Target service:  "orders-service"
        ttl_seconds: int = 60,  # Very short TTL — replay window limited to 60s
        extra_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generate a signed JWT for service-to-service authentication.

        Claims:
          iss: identity of the calling service
          aud: intended recipient (recipient rejects tokens for other audiences)
          iat: issued at (Unix timestamp)
          exp: expiry (iat + ttl) — short TTL limits replay attack window
          jti: unique token ID (recipient caches JTIs to detect replay)
        """
        now = int(time.time())
        header = {"alg": "HS256", "typ": "JWT"}  # Use RS256 in prod
        payload: Dict[str, Any] = {
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": now + ttl_seconds,
            "jti": self._generate_jti(),  # Unique per token — replay detection
        }
        if extra_claims:
            payload.update(extra_claims)

        header_b64 = self._b64url_encode(json.dumps(header).encode())
        payload_b64 = self._b64url_encode(json.dumps(payload).encode())
        signing_input = f"{header_b64}.{payload_b64}"

        # HMAC-SHA256 signature
        signature = hmac.new(
            self.signing_key,
            signing_input.encode(),
            hashlib.sha256
        ).digest()
        sig_b64 = self._b64url_encode(signature)

        return f"{signing_input}.{sig_b64}"

    def _generate_jti(self) -> str:
        """Generate a unique token ID (jti) for replay detection."""
        return base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode()

    def verify_token(
        self,
        token: str,
        expected_issuer: str,
        expected_audience: str,
        jti_cache: Optional[set] = None,
    ) -> Dict[str, Any]:
        """
        Verify a service JWT. Raises ValueError on any validation failure.

        Checks:
          1. Signature valid (not tampered)
          2. Not expired (exp claim)
          3. Correct issuer (iss) — who is calling
          4. Correct audience (aud) — intended for this service
          5. JTI not previously seen (replay protection)
        """
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid JWT format")

        header_b64, payload_b64, sig_b64 = parts

        # 1. Verify signature
        signing_input = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(
            self.signing_key,
            signing_input.encode(),
            hashlib.sha256,
        ).digest()
        actual_sig = self._b64url_decode(sig_b64)

        if not hmac.compare_digest(expected_sig, actual_sig):
            raise ValueError("JWT signature verification failed")

        # 2. Decode payload
        payload = json.loads(self._b64url_decode(payload_b64).decode())
        now = int(time.time())

        # 3. Check expiry
        if payload.get("exp", 0) < now:
            raise ValueError(f"JWT expired at {payload.get('exp')}")

        # 4. Check not used before valid time (clock skew tolerance: 5s)
        if payload.get("iat", now) > now + 5:
            raise ValueError("JWT issued in the future — possible clock skew attack")

        # 5. Verify issuer
        if payload.get("iss") != expected_issuer:
            raise ValueError(f"JWT issuer mismatch: expected={expected_issuer}, got={payload.get('iss')}")

        # 6. Verify audience
        aud = payload.get("aud")
        if isinstance(aud, list):
            if expected_audience not in aud:
                raise ValueError(f"JWT audience mismatch: {expected_audience} not in {aud}")
        elif aud != expected_audience:
            raise ValueError(f"JWT audience mismatch: expected={expected_audience}, got={aud}")

        # 7. Replay detection — check JTI not already used
        jti = payload.get("jti")
        if jti_cache is not None:
            if jti in jti_cache:
                raise ValueError(f"JWT replay detected: jti={jti} already used")
            jti_cache.add(jti)  # Cache JTI until token expires (TTL + buffer)

        return payload


# ---------------------------------------------------------------------------
# 5. KUBERNETES NETWORK POLICY
# ---------------------------------------------------------------------------
# NetworkPolicy operates at IP/port level (L3/L4). It is enforced by the
# CNI plugin (Calico, Cilium). Istio AuthorizationPolicy operates at L7.
# BOTH should be configured — defence in depth. If Istio sidecar fails to
# inject into a pod, NetworkPolicy still blocks lateral movement.

NETWORK_POLICY_DEFAULT_DENY = """
# Step 1: Default deny ALL ingress and egress in the namespace.
# Nothing can communicate until explicitly allowed.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: prod
spec:
  podSelector: {}     # Applies to ALL pods in namespace
  policyTypes:
    - Ingress
    - Egress
"""

NETWORK_POLICY_ALLOWLIST = """
# Step 2: Allow specific service-to-service communication.

# orders-service: accepts traffic ONLY from payments-service
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: orders-allow-payments
  namespace: prod
spec:
  podSelector:
    matchLabels:
      app: orders-service     # This policy applies to orders-service pods
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: payments-service  # Only payments-service pods can send traffic
      ports:
        - protocol: TCP
          port: 8080          # Only the service port, not SSH or other ports
---
# payments-service: allow egress to orders-service and Vault only
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: payments-egress
  namespace: prod
spec:
  podSelector:
    matchLabels:
      app: payments-service
  policyTypes:
    - Egress
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: orders-service
      ports:
        - protocol: TCP
          port: 8080
    - to:
        - namespaceSelector:
            matchLabels:
              name: vault
      ports:
        - protocol: TCP
          port: 8200
    # Allow DNS resolution (required for hostname lookups)
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: UDP
          port: 53
"""


# ---------------------------------------------------------------------------
# 6. CONTAINER SECURITY — HARDENING POD SPEC
# ---------------------------------------------------------------------------
# Running as root inside a container is dangerous:
#   - Many container escape CVEs require root privilege inside the container
#   - If app is root and escapes, it has root on the node
# Read-only root filesystem prevents attackers from modifying binaries.

SECURE_POD_SPEC = """
apiVersion: v1
kind: Pod
metadata:
  name: payments-service
  namespace: prod
spec:
  # Pod-level security: no privileged pods, no host network/PID/IPC
  securityContext:
    runAsNonRoot: true         # Reject pod if image runs as root
    runAsUser: 1001            # Specific UID — not 0
    runAsGroup: 1001
    fsGroup: 1001              # Volume mounts owned by this GID
    seccompProfile:
      type: RuntimeDefault     # Block unusual syscalls (reduces kernel attack surface)

  containers:
    - name: payments-service
      image: payments-service:1.2.3
      securityContext:
        allowPrivilegeEscalation: false  # Cannot gain more privs (no setuid binaries)
        readOnlyRootFilesystem: true      # Cannot write to container filesystem
        capabilities:
          drop:
            - ALL              # Drop ALL Linux capabilities by default
          add:
            - NET_BIND_SERVICE # Add back ONLY if binding to port < 1024
                               # Most apps should use port >= 1024 (no caps needed)
        privileged: false      # Never. Full host access.
      resources:
        # Resource limits prevent a compromised pod from consuming all node resources
        limits:
          memory: "512Mi"
          cpu: "500m"
        requests:
          memory: "256Mi"
          cpu: "100m"
      volumeMounts:
        # Writable tmp for app temp files (since root FS is read-only)
        - name: tmp-volume
          mountPath: /tmp
        - name: secrets-volume
          mountPath: /var/secrets
          readOnly: true

  volumes:
    - name: tmp-volume
      emptyDir:
        medium: Memory         # RAM-backed — not persisted to disk
        sizeLimit: 64Mi
    - name: secrets-volume
      secret:
        secretName: payments-secrets
"""


# ---------------------------------------------------------------------------
# 7. SERVICE ACCOUNT TOKEN ROTATION
# ---------------------------------------------------------------------------
# K8s ServiceAccount tokens: short-lived by default (1 hour in K8s 1.24+)
# Bound to the pod's lifetime — revoked when pod terminates.
# Projected volumes: token auto-rotated by kubelet.

SERVICE_ACCOUNT_TOKEN_MOUNT = """
# K8s projected volume: kubelet rotates the token automatically.
# Token is audience-bound (payments-service can only be used with 'payments-api').
volumes:
  - name: sa-token
    projected:
      sources:
        - serviceAccountToken:
            audience: payments-api   # Token only valid for this audience
            expirationSeconds: 3600  # 1-hour TTL; kubelet refreshes at 80%
            path: token
"""


# ---------------------------------------------------------------------------
# 8. COMPLETE DEMONSTRATION
# ---------------------------------------------------------------------------

def demonstrate_service_security():
    """
    Full workflow: mTLS concepts, JWT service auth, and security policies.
    """
    print("=" * 60)
    print("SERVICE SECURITY DEMONSTRATION")
    print("=" * 60)

    # -- SPIFFE Identity --
    print("\n[1] SPIFFE Workload Identity:")
    payments_id = SPIFFEIdentity(
        trust_domain="example.com",
        namespace="prod",
        service_account="payments-service",
    )
    orders_id = SPIFFEIdentity(
        trust_domain="example.com",
        namespace="prod",
        service_account="orders-service",
    )
    print(f"  Payments: {payments_id.spiffe_id}")
    print(f"  Orders:   {orders_id.spiffe_id}")
    print(f"  Payments cert valid: {payments_id.is_valid()}")
    print(f"  Cert expires: {payments_id.expires_at.strftime('%Y-%m-%dT%H:%M:%SZ')}")

    # -- JWT Service Token --
    print("\n[2] JWT Service-to-Service Token:")
    signing_key = os.urandom(32)  # In prod: read from Vault or K8s Secret
    jwt_service = JWTServiceToken(signing_key=signing_key)

    # Payments-service generates a token to call orders-service
    token = jwt_service.generate_token(
        issuer="payments-service",
        audience="orders-service",
        ttl_seconds=60,
        extra_claims={"correlation_id": "req-abc-123"},
    )
    print(f"  Token (truncated): {token[:60]}...")

    # Orders-service verifies the incoming token
    jti_cache: set = set()
    try:
        payload = jwt_service.verify_token(
            token=token,
            expected_issuer="payments-service",
            expected_audience="orders-service",
            jti_cache=jti_cache,
        )
        print(f"  Token verified: iss={payload['iss']}, aud={payload['aud']}")
        print(f"  JTI cached for replay detection: {payload['jti']}")
    except ValueError as e:
        print(f"  Token rejected: {e}")

    # Demonstrate replay detection
    print("\n[3] Replay Attack Detection:")
    try:
        jwt_service.verify_token(token, "payments-service", "orders-service", jti_cache)
        print("  ERROR: Second use should have been rejected!")
    except ValueError as e:
        print(f"  Replay correctly blocked: {e}")

    # Demonstrate wrong audience rejection
    print("\n[4] Wrong Audience Rejection:")
    try:
        jwt_service.verify_token(token, "payments-service", "inventory-service", set())
        print("  ERROR: Wrong audience should have been rejected!")
    except ValueError as e:
        print(f"  Wrong audience blocked: {e}")

    # Summary of K8s policies
    print("\n[5] K8s Policy Summary:")
    policies = [
        ("PeerAuthentication",    "STRICT mTLS across prod namespace"),
        ("AuthorizationPolicy",   "payments-service → orders-service only"),
        ("NetworkPolicy",         "default-deny-all + explicit allowlist"),
        ("PodSecurityContext",    "UID 1001, readOnlyRootFilesystem, drop ALL caps"),
        ("SPIRE",                 "24h cert rotation, automatic, no manual steps"),
    ]
    for name, desc in policies:
        print(f"  {name:<25} {desc}")


if __name__ == "__main__":
    demonstrate_service_security()
