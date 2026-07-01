# =============================================================================
# WHAT: JWT and Token-Based Authentication
# WHY:  JWTs are ubiquitous in modern APIs, microservices, and SPAs — but
#       they are also a minefield. Understanding the structure, the attacks,
#       and the correct validation checklist prevents common critical flaws.
# LEVEL: Intermediate-to-Advanced
# =============================================================================

# ── CONCEPT OVERVIEW ──────────────────────────────────────────────────────────
# A JWT (JSON Web Token) is a compact, URL-safe means of representing claims
# between two parties. It looks like: header.payload.signature
#
# Each part is base64url-encoded (NOT base64 — no padding, URL-safe chars).
#
# header:    {"alg": "RS256", "typ": "JWT"}
# payload:   {"sub": "123", "iss": "myapp.com", "exp": 1700000000, ...}
# signature: RSASSA-PKCS1-v1_5(base64url(header) + "." + base64url(payload))
#
# Key insight: the payload is NOT encrypted (unless you use JWE). Anyone can
# decode and read it. The SIGNATURE ensures it hasn't been tampered with.
# Never put secrets or sensitive PII in a JWT payload without encryption.

# ── PRODUCTION USE CASE ───────────────────────────────────────────────────────
# A microservices architecture where an Auth Service issues RS256 JWTs.
# Each downstream service validates the JWT using the Auth Service's PUBLIC key
# (distributed via JWKS endpoint). No service needs the private key or a
# shared secret — they just fetch and cache the public key from the JWKS URL.
# Short-lived access tokens (15 min) + longer-lived refresh tokens (7 days)
# with rotation. Revocation via jti blacklist in Redis.

# ── COMMON MISTAKES ───────────────────────────────────────────────────────────
# 1. alg:none attack — accepting tokens with algorithm "none" (no signature).
# 2. HS256 with weak secrets — brute-forceable if secret is short.
# 3. Missing exp claim — token valid forever if server is compromised.
# 4. Not validating aud (audience) — token for service A accepted by service B.
# 5. Not validating iss (issuer) — accepting tokens from other providers.
# 6. Storing JWTs in localStorage — accessible to XSS attacks.
# 7. Treating the payload as trusted without verifying the signature first.
# 8. Using RS256 but forgetting to validate the kid (key ID) header claim.

# =============================================================================
# IMPORTS
# =============================================================================

import os           # Environment variables for secrets
import time         # Current time for exp/iat/nbf calculations
import json         # JSON encoding/decoding for payload inspection
import base64       # Base64url decoding for manual payload inspection
import secrets      # Generating secure random jti values
import hashlib      # For jti hashing in blacklist

# Third-party — install via: pip install PyJWT cryptography
import jwt                               # PyJWT: encode/decode JWTs
from jwt.exceptions import (
    ExpiredSignatureError,               # Token has expired (exp in past)
    InvalidSignatureError,               # Signature verification failed
    DecodeError,                         # Malformed token structure
    InvalidAudienceError,                # aud claim mismatch
    InvalidIssuerError,                  # iss claim mismatch
    ImmatureSignatureError,              # nbf (not before) in future
    InvalidAlgorithmError,               # Algorithm not in allowed list
)

# For RSA key generation (production: load from file / secrets manager)
from cryptography.hazmat.primitives.asymmetric import rsa, ec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend


# =============================================================================
# SECTION 1: JWT STRUCTURE — DECODE WITHOUT VERIFICATION
# =============================================================================

def inspect_jwt_payload(token: str) -> dict:
    """
    Decode a JWT payload WITHOUT verifying the signature.
    Useful for logging, debugging, or reading the kid/alg header before
    selecting the right verification key.

    WARNING: Never trust decoded claims before signature verification.
    This is read-only inspection, not authentication.
    """
    # A JWT is three base64url segments separated by dots
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Not a valid JWT format — expected header.payload.signature")

    header_b64, payload_b64, signature_b64 = parts

    def b64url_decode(data: str) -> bytes:
        # base64url uses - and _ instead of + and /
        # Python's base64 module needs padding (= chars) added back
        padding = 4 - len(data) % 4
        if padding != 4:
            data += "=" * padding
        return base64.urlsafe_b64decode(data)

    header = json.loads(b64url_decode(header_b64))
    payload = json.loads(b64url_decode(payload_b64))

    print(f"Header:  {json.dumps(header, indent=2)}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    return {"header": header, "payload": payload}


# =============================================================================
# SECTION 2: SIGNING ALGORITHMS — HS256, RS256, ES256
# =============================================================================

# HS256 (HMAC-SHA256) — Symmetric:
#   - Same secret used to SIGN and VERIFY.
#   - Every service that needs to verify must know the secret.
#   - If secret leaks from any service, attacker can forge tokens.
#   - Use only when you control all verifiers (e.g., monolith).
#   - Secret must be at least 256 bits (32 bytes) of entropy.
#
# RS256 (RSA-PKCS1v15-SHA256) — Asymmetric:
#   - Private key signs (only Auth Service has it).
#   - Public key verifies (any service can have it).
#   - Compromise of a downstream service does NOT compromise signing.
#   - Recommended for microservices and third-party integrations.
#   - Key size: minimum 2048-bit RSA, prefer 4096-bit.
#
# ES256 (ECDSA-P256-SHA256) — Asymmetric, smaller:
#   - Same security as RS256 with much smaller keys and signatures.
#   - 256-bit EC key ≈ 3072-bit RSA key in security.
#   - Faster verification. Recommended for resource-constrained environments.

def generate_rsa_keypair():
    """
    Generate a 2048-bit RSA keypair for RS256 JWT signing.
    In production: generate once, store private key in HSM or secrets manager,
    store public key (or JWKS endpoint) for verifiers.
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,    # Standard RSA public exponent
        key_size=2048,            # 2048-bit minimum; 4096-bit for extra margin
        backend=default_backend()
    )
    public_key = private_key.public_key()

    # Serialize to PEM format (text-based, portable)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()  # Encrypt in prod!
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private_pem, public_pem


def generate_ec_keypair():
    """
    Generate a P-256 elliptic curve keypair for ES256 JWT signing.
    Smaller and faster than RSA, same security level.
    """
    private_key = ec.generate_private_key(
        curve=ec.SECP256R1(),     # P-256 curve — NIST approved, widely supported
        backend=default_backend()
    )
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private_pem, public_pem


# =============================================================================
# SECTION 3: STANDARD CLAIMS (REGISTERED CLAIM NAMES)
# =============================================================================

# Defined in RFC 7519. All are OPTIONAL by spec, but iss/sub/exp/iat/jti
# should be present in every production token.
#
# iss (issuer)     — who issued the token (e.g., "https://auth.myapp.com")
# sub (subject)    — who the token is about (e.g., user ID "user-123")
# aud (audience)   — intended recipient(s) (e.g., "api.myapp.com")
# exp (expiration) — Unix timestamp after which token is invalid
# nbf (not before) — Unix timestamp before which token must not be accepted
# iat (issued at)  — Unix timestamp when token was issued
# jti (JWT ID)     — unique identifier for this token; used for revocation

def build_access_token_payload(
    user_id: str,
    roles: list,
    issuer: str,
    audience: str,
    ttl_seconds: int = 900,          # 15 minutes — short-lived access token
) -> dict:
    """
    Build a JWT payload with all recommended claims.
    ttl_seconds=900 (15 min) is the industry standard for access tokens.
    """
    now = int(time.time())
    return {
        "iss": issuer,                        # Must match what verifier expects
        "sub": user_id,                       # User identifier (not email — immutable)
        "aud": audience,                      # Which service this is for
        "exp": now + ttl_seconds,            # Expiry timestamp
        "nbf": now,                           # Not valid before now
        "iat": now,                           # Issued at (for auditing)
        "jti": secrets.token_urlsafe(16),    # Unique ID for revocation tracking
        "roles": roles,                       # Custom claim — authorization data
    }


# =============================================================================
# SECTION 4: CREATING AND VERIFYING TOKENS (HS256 + RS256)
# =============================================================================

# ── HS256 (symmetric) ─────────────────────────────────────────────────────────

HS256_SECRET = os.environ.get(
    "JWT_SECRET",
    "CHANGE-THIS-IN-PRODUCTION-USE-32-PLUS-BYTES"   # Placeholder only
)
# NOTE: In production load from: os.environ["JWT_SECRET"] — never hardcode.
# Minimum recommended: 32 bytes (256 bits) of random data.
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"


def create_hs256_token(payload: dict) -> str:
    """
    Sign a JWT using HS256. Use this only in single-service contexts.
    """
    # PyJWT automatically adds/validates the exp claim during encode.
    token = jwt.encode(
        payload,
        HS256_SECRET,
        algorithm="HS256"    # Explicitly name algorithm — never let it be inferred
    )
    return token    # Returns a string in PyJWT v2+


def verify_hs256_token(token: str) -> dict:
    """
    Verify and decode an HS256 JWT. Raises exceptions on any failure.
    The returned payload is safe to use ONLY if no exception is raised.
    """
    try:
        payload = jwt.decode(
            token,
            HS256_SECRET,
            algorithms=["HS256"],             # Allowlist — NEVER use ["HS256", "none"]
            options={
                "require": ["exp", "iss", "sub", "aud", "jti"],  # Mandate claims
                "verify_exp": True,           # Enforce expiry (default True, be explicit)
            },
            audience="api.myapp.com",         # Must match aud in token
            issuer="https://auth.myapp.com",  # Must match iss in token
        )
        return payload

    except ExpiredSignatureError:
        raise ValueError("Token has expired. Please refresh.")
    except InvalidSignatureError:
        raise ValueError("Token signature is invalid. Possible tampering.")
    except InvalidAudienceError:
        raise ValueError("Token audience does not match this service.")
    except InvalidIssuerError:
        raise ValueError("Token issuer is not trusted.")
    except DecodeError:
        raise ValueError("Token is malformed and cannot be decoded.")
    except ImmatureSignatureError:
        raise ValueError("Token is not yet valid (nbf in future).")


# ── RS256 (asymmetric) ────────────────────────────────────────────────────────

def create_rs256_token(payload: dict, private_key_pem: bytes, kid: str = "v1") -> str:
    """
    Sign a JWT using RS256 with a private RSA key.
    kid (Key ID) header allows verifiers to select the correct public key
    when the issuer rotates keys (JWKS supports multiple keys simultaneously).
    """
    headers = {"kid": kid}    # Include key ID so verifiers know which public key to use
    token = jwt.encode(
        payload,
        private_key_pem,          # The PEM-encoded private key bytes
        algorithm="RS256",
        headers=headers,
    )
    return token


def verify_rs256_token(token: str, public_key_pem: bytes) -> dict:
    """
    Verify an RS256 JWT using the issuer's public key.
    In microservices: fetch public key from JWKS endpoint, cache it,
    and rotate when a new kid appears in incoming tokens.
    """
    payload = jwt.decode(
        token,
        public_key_pem,
        algorithms=["RS256"],              # Never include "HS256" here — different key type
        audience="api.myapp.com",
        issuer="https://auth.myapp.com",
    )
    return payload


# =============================================================================
# SECTION 5: TOKEN VALIDATION CHECKLIST
# =============================================================================

# Every JWT verifier MUST check ALL of the following in order:
#
# 1. Structure: exactly 3 segments separated by dots.
# 2. Algorithm:
#      a. Read alg from header ONLY to select the verification function.
#      b. The alg must be in your explicit allowlist.
#      c. REJECT "none" always — it means no signature, completely insecure.
# 3. Signature: verify cryptographically. If invalid, reject immediately.
# 4. Expiry (exp): current time must be before exp.
# 5. Not Before (nbf): if present, current time must be after nbf.
# 6. Issuer (iss): must exactly match your expected issuer string.
# 7. Audience (aud): must contain your service's identifier.
# 8. Subject (sub): must be a valid, non-empty user/entity identifier.
# 9. JTI revocation: look up jti in blacklist (for logout / token invalidation).

def full_token_validation_checklist(token: str, public_key_pem: bytes) -> dict:
    """
    Demonstrates the complete validation sequence with explicit checks.
    In production use a library that handles steps 3-8 automatically
    (PyJWT does when parameters are correctly configured).
    """
    # Step 1: Check structure
    if token.count(".") != 2:
        raise ValueError("FAIL: Token structure invalid")

    # Step 2a: Read header (unverified) to get algorithm and kid
    unverified = inspect_jwt_payload(token)
    alg = unverified["header"].get("alg", "")
    kid = unverified["header"].get("kid", "")

    # Step 2b: Algorithm allowlist
    ALLOWED_ALGORITHMS = {"RS256", "ES256"}   # NO "HS256" in public key context, NO "none"
    if alg not in ALLOWED_ALGORITHMS:
        raise ValueError(f"FAIL: Algorithm '{alg}' is not allowed")

    # Steps 3-8: PyJWT handles signature, exp, nbf, iss, aud when configured correctly
    payload = jwt.decode(
        token,
        public_key_pem,
        algorithms=list(ALLOWED_ALGORITHMS),
        audience="api.myapp.com",
        issuer="https://auth.myapp.com",
        options={"require": ["exp", "iss", "sub", "aud", "jti", "iat"]},
    )

    # Step 9: JTI blacklist check (revocation)
    jti = payload.get("jti")
    if is_token_revoked(jti):
        raise ValueError(f"FAIL: Token jti={jti} has been revoked")

    print("PASS: All validation checks passed")
    return payload


# =============================================================================
# SECTION 6: TOKEN REVOCATION — JTI BLACKLIST IN REDIS
# =============================================================================

# JWTs are stateless — once issued, they are valid until exp.
# But what if a user logs out, or a token is compromised?
# Two strategies:
#
# Strategy A: Short-lived access tokens (15 min) — accept small window of risk.
#   On logout: just delete the refresh token. Access token expires naturally.
#
# Strategy B: JTI blacklist in Redis.
#   On revocation: store the jti in Redis with TTL = token's remaining lifetime.
#   On every request: check Redis before trusting the payload.
#   Downside: adds a Redis round-trip to every authenticated request.

# Simulated Redis (use redis-py in production)
_revoked_jtis: dict = {}   # jti → expiry timestamp


def revoke_token(jti: str, exp: int) -> None:
    """
    Add a token's jti to the revocation blacklist.
    Set TTL to the token's remaining lifetime — no need to store forever.
    """
    remaining_seconds = max(0, exp - int(time.time()))
    _revoked_jtis[jti] = time.time() + remaining_seconds
    # Redis equivalent: redis_client.setex(f"revoked:{jti}", remaining_seconds, "1")
    print(f"[REVOKE] jti={jti} blacklisted for {remaining_seconds}s")


def is_token_revoked(jti: str) -> bool:
    """
    Check if a jti is in the revocation list.
    Returns True if revoked (deny access), False if clean.
    """
    if jti not in _revoked_jtis:
        return False    # Not in blacklist

    # Clean up expired entries (Redis TTL handles this automatically)
    if time.time() > _revoked_jtis[jti]:
        del _revoked_jtis[jti]
        return False    # Was revoked but token would be expired anyway

    return True   # Actively revoked


# =============================================================================
# SECTION 7: REFRESH TOKEN ROTATION
# =============================================================================

# Refresh token rotation:
#   1. Issue access token (15 min) + refresh token (7 days) on login.
#   2. When access token expires, client sends refresh token.
#   3. Server issues NEW access token + NEW refresh token.
#   4. OLD refresh token is invalidated immediately.
#
# Why rotate: if a refresh token is stolen, using it once invalidates it
# for the attacker when the legitimate user uses it next — server detects
# the reuse and can invalidate the entire token family (refresh token reuse attack).

_refresh_token_store: dict = {}   # token → {user_id, expires_at, family_id}


def issue_token_pair(user_id: str, roles: list) -> dict:
    """
    Issue an access token + refresh token pair on successful login.
    Returns both tokens to the client.
    """
    family_id = secrets.token_urlsafe(16)   # Track token family for reuse detection

    access_payload = build_access_token_payload(
        user_id=user_id,
        roles=roles,
        issuer="https://auth.myapp.com",
        audience="api.myapp.com",
        ttl_seconds=900,    # 15 minutes
    )
    access_token = create_hs256_token(access_payload)  # Simplified; use RS256 in prod

    # Refresh token: opaque random string (NOT a JWT — simpler and revocable)
    refresh_token = secrets.token_urlsafe(32)
    refresh_expiry = time.time() + 7 * 24 * 3600    # 7 days

    _refresh_token_store[refresh_token] = {
        "user_id": user_id,
        "roles": roles,
        "expires_at": refresh_expiry,
        "family_id": family_id,
        "used": False,    # Track if this specific token has been consumed
    }

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": 900,
    }


def rotate_refresh_token(old_refresh_token: str) -> dict:
    """
    Exchange an old refresh token for a new token pair.
    Implements refresh token rotation with reuse detection.
    """
    entry = _refresh_token_store.get(old_refresh_token)

    if entry is None:
        raise ValueError("Refresh token not found")

    if time.time() > entry["expires_at"]:
        del _refresh_token_store[old_refresh_token]
        raise ValueError("Refresh token has expired")

    if entry["used"]:
        # REUSE DETECTED: this token was already exchanged.
        # This might mean a stolen token was used by an attacker.
        # Invalidate ALL tokens in this family (nuclear option — user must re-login).
        print(f"[SECURITY ALERT] Refresh token reuse detected for family {entry['family_id']}")
        _invalidate_token_family(entry["family_id"])
        raise ValueError("Refresh token reuse detected — all sessions invalidated")

    # Mark old token as used BEFORE issuing new one (prevent race conditions)
    entry["used"] = True

    # Issue a new token pair
    new_pair = issue_token_pair(entry["user_id"], entry["roles"])
    return new_pair


def _invalidate_token_family(family_id: str) -> None:
    """Invalidate all refresh tokens belonging to a token family."""
    to_delete = [
        token for token, data in _refresh_token_store.items()
        if data.get("family_id") == family_id
    ]
    for token in to_delete:
        del _refresh_token_store[token]
    print(f"[SECURITY] Invalidated {len(to_delete)} tokens in family {family_id}")


# =============================================================================
# SECTION 8: JWKS — JSON WEB KEY SETS (PUBLIC KEY DISTRIBUTION)
# =============================================================================

# JWKS is the standard way to publish public keys for JWT verification.
# Consumers (microservices, third parties) fetch and cache the JWKS document,
# then use it to verify tokens without contacting the auth server on each request.
#
# JWKS endpoint: GET https://auth.myapp.com/.well-known/jwks.json
# Response format:
# {
#   "keys": [
#     {
#       "kty": "RSA",
#       "use": "sig",
#       "kid": "v1",
#       "n": "<base64url-encoded modulus>",
#       "e": "AQAB"
#     }
#   ]
# }
#
# Key rotation:
#   1. Generate new keypair, assign kid="v2".
#   2. Publish JWKS with BOTH keys (v1 and v2) for transition period.
#   3. Start signing new tokens with v2 key.
#   4. Wait for v1-signed tokens to expire (e.g., 15 min).
#   5. Remove v1 from JWKS.
#
# Libraries that handle JWKS fetching: python-jose, jwcrypto, authlib.

JWKS_EXAMPLE_RESPONSE = {
    "keys": [
        {
            "kty": "RSA",         # Key type
            "use": "sig",         # Use: sig (signature) or enc (encryption)
            "kid": "v1",          # Key ID — matches kid in JWT header
            "alg": "RS256",       # Algorithm this key is used with
            "n": "<base64url-modulus>",   # RSA public key modulus
            "e": "AQAB",          # RSA public exponent (65537 in base64url)
        }
    ]
}


# =============================================================================
# SECTION 9: JWT vs OPAQUE TOKENS — WHEN TO USE EACH
# =============================================================================

# JWT (self-contained):
#   Pros: No server-side state — stateless, scalable, works across services.
#   Pros: Claims embedded — no DB lookup to get user roles, etc.
#   Cons: Cannot revoke before expiry without a blacklist (adds state back).
#   Cons: Payload is readable (use JWE if you need encryption).
#   Cons: Size — larger than opaque tokens (hundreds of bytes).
#   Best for: microservices, API-to-API auth, short-lived access tokens.
#
# Opaque tokens (reference tokens):
#   Pros: Instantly revocable — just delete from DB.
#   Pros: Small size (32-byte random string).
#   Pros: No information leakage in the token itself.
#   Cons: Every validation requires a DB/Redis lookup.
#   Cons: Doesn't work across services without a shared introspection endpoint.
#   Best for: refresh tokens, long-lived sessions, high-security contexts.
#
# Token introspection (RFC 7662): an endpoint that validates an opaque token
# and returns its metadata. Used when services need to validate tokens they
# didn't issue: POST /oauth2/introspect → {"active": true, "sub": "user-123", ...}

TOKEN_STORAGE_SECURITY_TRADEOFFS = """
Where to store tokens (client-side):

localStorage:
  - Accessible to JavaScript → XSS can steal it
  - Persists across browser restarts
  - AVOID for sensitive tokens

sessionStorage:
  - Accessible to JavaScript → XSS can steal it
  - Cleared when tab closes (slightly better)
  - Still avoid for sensitive tokens

httpOnly Cookie (RECOMMENDED for web apps):
  - Inaccessible to JavaScript → XSS cannot steal it
  - Automatically sent with requests to same origin
  - Protect with SameSite=Strict to prevent CSRF
  - Works with refresh token rotation

In-memory (JS variable):
  - Best XSS protection — tab close clears it
  - Lost on page refresh → user must re-authenticate
  - Use for SPAs with short-lived access tokens
  - Store refresh token in httpOnly cookie

Mobile apps:
  - iOS: Keychain
  - Android: Keystore
  - Never store in SharedPreferences (world-readable on rooted devices)
"""


# =============================================================================
# SECTION 10: COMMON JWT ATTACKS AND DEFENSES
# =============================================================================

def demonstrate_alg_none_attack():
    """
    Illustrate the alg:none attack conceptually.
    An attacker modifies the token header to set alg:"none",
    then removes the signature. Vulnerable libraries accept it.

    Defense: ALWAYS pass an explicit algorithms allowlist to your decode function.
    NEVER accept "none" as an algorithm. PyJWT rejects "none" by default.
    """
    # VULNERABLE (never do this):
    # jwt.decode(token, key="", algorithms=["HS256", "none"])
    # jwt.decode(token, options={"verify_signature": False})  # Debug only!

    # SAFE:
    # jwt.decode(token, public_key, algorithms=["RS256"])
    # — algorithms parameter is an allowlist; "none" is never in it.
    print("alg:none attack: always use an explicit algorithms allowlist")
    print("Never include 'none' or leave algorithms unspecified")


def demonstrate_weak_hs256_secret():
    """
    Show why HS256 secrets must be cryptographically random and long.
    Short secrets are brute-forceable offline — attacker only needs the token.
    """
    # VULNERABLE: short, predictable, or human-memorable secrets
    bad_secrets = ["secret", "password", "myapp", "jwt-secret-key"]

    # SAFE: at least 32 bytes (256 bits) of cryptographically random data
    good_secret = secrets.token_hex(32)    # 64 hex chars = 256 bits
    print(f"Good HS256 secret (256-bit random): {good_secret}")
    print(
        "Generate with: python -c \"import secrets; print(secrets.token_hex(32))\"\n"
        "Store in environment variable, never in source code."
    )


# =============================================================================
# DEMONSTRATION RUNNER
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("L02 — JWT and Tokens Demo")
    print("=" * 60)

    print("\n--- RSA Keypair Generation ---")
    private_pem, public_pem = generate_rsa_keypair()
    print(f"Private key: {len(private_pem)} bytes")
    print(f"Public key: {len(public_pem)} bytes")

    print("\n--- Building Token Payload ---")
    payload = build_access_token_payload(
        user_id="user-42",
        roles=["admin", "reader"],
        issuer="https://auth.myapp.com",
        audience="api.myapp.com",
    )
    print(json.dumps(payload, indent=2))

    print("\n--- HS256 Token ---")
    token = create_hs256_token(payload)
    print(f"Token: {token[:60]}...")

    print("\n--- Inspect Payload (without verification) ---")
    inspect_jwt_payload(token)

    print("\n--- Token Pair (Login) ---")
    pair = issue_token_pair("user-42", ["admin"])
    print(f"Access token: {pair['access_token'][:40]}...")
    print(f"Refresh token: {pair['refresh_token'][:20]}...")

    print("\n--- Refresh Token Rotation ---")
    new_pair = rotate_refresh_token(pair["refresh_token"])
    print(f"New access token: {new_pair['access_token'][:40]}...")

    print("\n--- Weak Secret Warning ---")
    demonstrate_weak_hs256_secret()

    print("\n--- alg:none Attack ---")
    demonstrate_alg_none_attack()

    print("\n--- Token Storage Tradeoffs ---")
    print(TOKEN_STORAGE_SECURITY_TRADEOFFS)
