# =============================================================================
# WHAT: OAuth2 and OpenID Connect (OIDC)
# WHY:  OAuth2 is the industry standard for delegated authorization — "let
#       app X access my data on service Y without giving X my password."
#       OIDC adds authentication on top of OAuth2. Understanding the full
#       flow prevents security mistakes like CSRF via missing state, or
#       trusting an unverified ID token.
# LEVEL: Intermediate-to-Advanced
# =============================================================================

# ── CONCEPT OVERVIEW ──────────────────────────────────────────────────────────
# OAuth2 (RFC 6749) defines four roles:
#   Resource Owner  — the user who owns the data
#   Client          — the app requesting access (your app)
#   Authorization Server (AS) — issues tokens (Google, Auth0, Keycloak)
#   Resource Server (RS)      — hosts the protected API (Google Drive API, etc.)
#
# OAuth2 is an AUTHORIZATION framework (access delegation).
# OIDC (OpenID Connect) adds AUTHENTICATION on top using an ID Token.
#
# Grant types (flows):
#   Authorization Code + PKCE  — For web apps and mobile. Most secure.
#   Client Credentials         — Machine-to-machine (M2M). No user involved.
#   Device Code                — For devices with no browser (smart TV, CLI).
#   Implicit                   — DEPRECATED. Do not use.
#   Resource Owner Password    — DEPRECATED. Do not use.

# ── PRODUCTION USE CASE ───────────────────────────────────────────────────────
# A SPA (React) + FastAPI backend that lets users "Login with Google."
# The SPA initiates Authorization Code + PKCE. The backend exchanges the code,
# validates the ID token, creates a session, and issues its own access token.
# For internal microservices: Client Credentials flow to call each other.

# ── COMMON MISTAKES ───────────────────────────────────────────────────────────
# 1. Missing state parameter → CSRF attack on the redirect endpoint.
# 2. Not validating the ID token (signature, iss, aud, exp) before trusting it.
# 3. Using implicit flow (tokens in URL fragment → logged in browser history).
# 4. Storing access tokens in localStorage (XSS risk).
# 5. Not implementing PKCE for public clients (native apps, SPAs).
# 6. Confusing scope (access permissions) with claims (token data).
# 7. Using access tokens as ID tokens — they are different objects!

# =============================================================================
# IMPORTS
# =============================================================================

import os           # Environment variables for client secrets
import json         # JSON parsing for discovery documents and responses
import base64       # Base64url encoding for PKCE
import hashlib      # SHA-256 for PKCE code_challenge
import secrets      # Cryptographic randomness for state and code_verifier
import time         # Token expiry calculations
import urllib.parse # URL encoding for redirect construction

# Third-party — install via:
# pip install requests authlib PyJWT cryptography python-jose[cryptography]
import requests                    # HTTP client for token exchange calls
from authlib.integrations.requests_client import OAuth2Session  # OAuth2 client
import jwt                         # PyJWT for ID token validation

# For Keycloak / Auth0 integration:
# pip install python-keycloak auth0-python


# =============================================================================
# SECTION 1: OAUTH2 ROLES AND TERMINOLOGY
# =============================================================================

# Illustrative configuration — replace with real values from your IdP dashboard
OAUTH2_CONFIG = {
    # Authorization Server (Identity Provider) endpoints
    "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
    "token_endpoint": "https://oauth2.googleapis.com/token",
    "userinfo_endpoint": "https://www.googleapis.com/oauth2/v3/userinfo",
    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
    "issuer": "https://accounts.google.com",

    # Your application (the Client)
    "client_id": os.environ.get("GOOGLE_CLIENT_ID", "YOUR_CLIENT_ID"),
    "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", "YOUR_CLIENT_SECRET"),
    "redirect_uri": "https://yourapp.com/auth/callback",

    # What permissions you're requesting
    "scopes": ["openid", "email", "profile"],   # "openid" triggers OIDC mode
}


# =============================================================================
# SECTION 2: PKCE — PROOF KEY FOR CODE EXCHANGE (RFC 7636)
# =============================================================================

# PKCE solves the authorization code interception attack for public clients
# (mobile apps, SPAs, CLIs) that cannot keep a client_secret confidential.
#
# Flow:
#   1. Client generates a random code_verifier (43-128 chars, high entropy).
#   2. Client computes code_challenge = BASE64URL(SHA256(code_verifier)).
#   3. Client sends code_challenge in the authorization request.
#   4. AS stores code_challenge, issues authorization code.
#   5. Client sends code + code_verifier in the token request.
#   6. AS recomputes SHA256(code_verifier) and compares to stored challenge.
#   7. Only the original client (who knew the verifier) can exchange the code.
#
# Even if an attacker intercepts the authorization code, they cannot exchange
# it without the code_verifier — which was never transmitted.

def generate_pkce_pair() -> dict:
    """
    Generate a PKCE code_verifier + code_challenge pair.
    Store the verifier server-side (or in session) until the callback.
    Send the challenge to the authorization server.
    """
    # code_verifier: cryptographically random, 43-128 characters from [A-Z a-z 0-9 - . _ ~]
    # secrets.token_urlsafe(96) → 128-char base64url string (well within 43-128 range)
    code_verifier = secrets.token_urlsafe(96)

    # code_challenge = BASE64URL(SHA256(ASCII(code_verifier)))
    # S256 method is required — "plain" method provides no security benefit
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()

    # base64url encode (no padding)
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    return {
        "code_verifier": code_verifier,       # Keep secret — present at token exchange
        "code_challenge": code_challenge,     # Send to AS in authorization request
        "code_challenge_method": "S256",      # Always use S256, never "plain"
    }


# =============================================================================
# SECTION 3: AUTHORIZATION CODE + PKCE FLOW (FULL EXAMPLE)
# =============================================================================

def build_authorization_url(
    client_id: str,
    redirect_uri: str,
    scopes: list,
    authorization_endpoint: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
) -> tuple:
    """
    Build the URL to redirect the user to for authorization.
    Returns (url, state) — store state in session for CSRF validation.

    The state parameter is critical: it ties the authorization response
    to the specific browser session that initiated the request, preventing
    CSRF attacks where an attacker tricks a user into authorizing their
    (attacker's) code.
    """
    # state: cryptographically random, opaque string — stored in session cookie
    # Must be verified when the AS redirects back to your callback URL
    state = secrets.token_urlsafe(32)

    params = {
        "response_type": "code",              # Authorization Code flow
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),            # Space-separated scope string
        "state": state,                       # CSRF protection token
        "code_challenge": code_challenge,     # PKCE challenge
        "code_challenge_method": code_challenge_method,
        "access_type": "offline",             # Request refresh token (Google-specific)
        "prompt": "consent",                  # Force consent screen (for refresh tokens)
    }

    # Build URL: authorization_endpoint + "?" + urlencode(params)
    url = authorization_endpoint + "?" + urllib.parse.urlencode(params)
    return url, state


def exchange_code_for_tokens(
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
    token_endpoint: str,
) -> dict:
    """
    Exchange the authorization code for access + ID + refresh tokens.
    This happens on your BACKEND (server-side) — never in the browser.
    code_verifier proves you are the same client that initiated the flow.
    """
    data = {
        "grant_type": "authorization_code",
        "code": code,                     # The code received in the callback
        "redirect_uri": redirect_uri,     # Must exactly match the original redirect_uri
        "client_id": client_id,
        "client_secret": client_secret,   # For confidential clients (web backends)
        "code_verifier": code_verifier,   # PKCE: proves this is the original client
    }

    response = requests.post(
        token_endpoint,
        data=data,
        headers={"Accept": "application/json"},
        timeout=10,    # Always set a timeout — don't hang on network issues
    )
    response.raise_for_status()    # Raise on 4xx/5xx HTTP errors
    tokens = response.json()

    # Expected response fields:
    # tokens["access_token"]  — short-lived, for API calls
    # tokens["id_token"]      — JWT with user identity claims (OIDC only)
    # tokens["refresh_token"] — long-lived, for getting new access tokens
    # tokens["expires_in"]    — access token TTL in seconds
    # tokens["token_type"]    — "Bearer"

    return tokens


def handle_oauth_callback(
    received_state: str,
    stored_state: str,
    code: str,
    code_verifier: str,
    config: dict,
) -> dict:
    """
    Full callback handler — validates state, exchanges code, validates ID token.
    This is the function you call in your /auth/callback route handler.
    """
    # Step 1: Validate state parameter (CSRF check)
    # Use constant-time comparison — timing side-channel is unlikely here,
    # but it's good practice for all security-sensitive comparisons.
    import hmac
    if not hmac.compare_digest(received_state, stored_state):
        raise ValueError("State mismatch — possible CSRF attack. Rejecting.")

    # Step 2: Exchange code for tokens
    tokens = exchange_code_for_tokens(
        code=code,
        code_verifier=code_verifier,
        redirect_uri=config["redirect_uri"],
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        token_endpoint=config["token_endpoint"],
    )

    # Step 3: Validate the ID token (CRITICAL — do not skip)
    id_token = tokens.get("id_token")
    if not id_token:
        raise ValueError("No ID token received — is 'openid' in scopes?")

    user_info = validate_id_token(
        id_token=id_token,
        client_id=config["client_id"],
        issuer=config["issuer"],
        jwks_uri=config["jwks_uri"],
    )

    return {
        "user": user_info,
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
    }


# =============================================================================
# SECTION 4: OPENID CONNECT — ID TOKEN VALIDATION
# =============================================================================

# The ID token is a JWT issued by the Authorization Server that contains
# claims ABOUT THE USER (not about what the user is allowed to do).
#
# Required ID token claims (OIDC Core spec):
#   iss  — issuer (must match config)
#   sub  — subject (stable unique user identifier, NOT email)
#   aud  — audience (must contain your client_id)
#   exp  — expiry
#   iat  — issued at
#
# Additional claims from profile/email scopes:
#   email, email_verified, name, picture, locale, etc.
#
# CRITICAL: The ID token signature must be verified against the AS's public
# key (fetched from jwks_uri). Never trust claims before signature verification.

def fetch_jwks(jwks_uri: str) -> dict:
    """
    Fetch the JSON Web Key Set from the Authorization Server.
    In production: cache this response (it rarely changes), but refresh
    when you encounter a kid that's not in your cached JWKS.
    """
    response = requests.get(jwks_uri, timeout=10)
    response.raise_for_status()
    return response.json()    # {"keys": [...]}


def validate_id_token(
    id_token: str,
    client_id: str,
    issuer: str,
    jwks_uri: str,
) -> dict:
    """
    Validate an OIDC ID token:
      1. Fetch JWKS (public keys) from the Authorization Server.
      2. Verify the signature using the matching public key (by kid).
      3. Validate iss, aud, exp, iat claims.
      4. Return validated claims — safe to use after this point.
    """
    # Fetch the public keys from the AS
    jwks = fetch_jwks(jwks_uri)

    # PyJWT's PyJWKClient fetches and caches JWKS, selects key by kid header
    from jwt import PyJWKClient
    jwks_client = PyJWKClient(jwks_uri)
    signing_key = jwks_client.get_signing_key_from_jwt(id_token)

    # Validate and decode the ID token
    claims = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256", "ES256"],    # What Google and most IdPs use
        audience=client_id,               # aud must equal our client_id
        issuer=issuer,                    # iss must match IdP's issuer URL
        options={
            "verify_exp": True,           # Reject expired tokens
            "require": ["iss", "sub", "aud", "exp", "iat"],  # Require these claims
        },
    )

    # Additional OIDC-specific check: email_verified
    if "email" in claims and not claims.get("email_verified", False):
        # The IdP has not verified this email address.
        # Depending on your use case, you may want to reject or flag this.
        print("[WARN] User email is not verified by the IdP")

    return claims


# =============================================================================
# SECTION 5: CLIENT CREDENTIALS FLOW (MACHINE-TO-MACHINE)
# =============================================================================

# Used when service A needs to call service B directly, without a user involved.
# Service A authenticates to the AS using its own client_id + client_secret.
# The AS issues an access token representing service A (not a user).
#
# No PKCE needed — the client_secret IS the proof of identity.
# The client_secret must be kept confidential (use a secrets manager).

def get_m2m_access_token(
    token_endpoint: str,
    client_id: str,
    client_secret: str,
    scope: str = "api.read api.write",
) -> dict:
    """
    Acquire an access token for machine-to-machine authentication.
    Call this once, cache the token until near-expiry, then re-fetch.
    """
    response = requests.post(
        token_endpoint,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,   # Confidential — from secrets manager
            "scope": scope,                    # Requested permissions
        },
        timeout=10,
    )
    response.raise_for_status()
    token_data = response.json()

    # Cache this token — re-use until (expires_in - buffer) seconds
    # Buffer: refresh 60 seconds before actual expiry to avoid race conditions
    token_data["expires_at"] = time.time() + token_data.get("expires_in", 3600) - 60

    return token_data


class M2MTokenCache:
    """
    Simple cache for Client Credentials tokens.
    In production: use Redis for multi-instance deployments.
    """

    def __init__(self):
        self._token = None      # Cached token string
        self._expires_at = 0    # When to refresh (with buffer)

    def get_token(
        self,
        token_endpoint: str,
        client_id: str,
        client_secret: str,
        scope: str,
    ) -> str:
        # Check if cached token is still valid
        if self._token and time.time() < self._expires_at:
            return self._token    # Return cached token

        # Fetch new token
        token_data = get_m2m_access_token(
            token_endpoint, client_id, client_secret, scope
        )
        self._token = token_data["access_token"]
        self._expires_at = token_data["expires_at"]
        return self._token


# =============================================================================
# SECTION 6: DEVICE CODE FLOW (BROWSERLESS DEVICES)
# =============================================================================

# Used for: CLI tools, smart TVs, IoT devices, gaming consoles.
# The device cannot open a browser, so it shows the user a URL and code
# to enter on another device (phone/laptop). The device polls for completion.
#
# Flow:
#   1. Device requests device_code and user_code from AS.
#   2. Device displays: "Go to https://example.com/activate and enter: XXXX-YYYY"
#   3. Device polls the token endpoint every interval seconds.
#   4. User opens the URL on their phone, logs in, enters the user_code.
#   5. AS starts returning access_token on the next poll.

def initiate_device_flow(
    device_authorization_endpoint: str,
    client_id: str,
    scope: str = "openid profile",
) -> dict:
    """
    Start a device authorization flow. Returns device_code, user_code,
    verification_uri, expires_in, and polling interval.
    """
    response = requests.post(
        device_authorization_endpoint,
        data={"client_id": client_id, "scope": scope},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()
    # Returns:
    # {
    #   "device_code": "...",
    #   "user_code": "XXXX-YYYY",
    #   "verification_uri": "https://example.com/activate",
    #   "expires_in": 1800,
    #   "interval": 5           ← polling interval in seconds
    # }


def poll_for_device_token(
    token_endpoint: str,
    client_id: str,
    device_code: str,
    interval: int = 5,
) -> dict:
    """
    Poll the token endpoint until the user completes authorization.
    Respect the interval — polling too fast causes authorization_pending errors.
    """
    while True:
        time.sleep(interval)   # Wait between polls — respect AS rate limiting

        response = requests.post(
            token_endpoint,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": client_id,
                "device_code": device_code,
            },
            timeout=10,
        )
        data = response.json()

        if "access_token" in data:
            return data    # User authorized — we have our token

        error = data.get("error")
        if error == "authorization_pending":
            continue    # User hasn't approved yet — keep waiting
        elif error == "slow_down":
            interval += 5    # AS is asking us to back off
            continue
        elif error == "expired_token":
            raise ValueError("Device code expired. Restart the flow.")
        elif error == "access_denied":
            raise ValueError("User denied authorization.")
        else:
            raise ValueError(f"Unexpected error: {error}")


# =============================================================================
# SECTION 7: OIDC DISCOVERY DOCUMENT
# =============================================================================

# Every OIDC-compliant AS publishes a discovery document at:
# {issuer}/.well-known/openid-configuration
#
# This document contains ALL endpoint URLs, supported algorithms, scopes,
# and claims. Your app should fetch this at startup instead of hardcoding URLs.

def fetch_oidc_discovery(issuer: str) -> dict:
    """
    Fetch the OIDC discovery document for an Authorization Server.
    Cache this document — it rarely changes (check every few hours).
    """
    # Standard path defined in OpenID Connect Discovery 1.0
    discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    response = requests.get(discovery_url, timeout=10)
    response.raise_for_status()
    config = response.json()

    # Key fields to extract:
    endpoints = {
        "issuer": config["issuer"],
        "authorization_endpoint": config["authorization_endpoint"],
        "token_endpoint": config["token_endpoint"],
        "userinfo_endpoint": config.get("userinfo_endpoint"),
        "jwks_uri": config["jwks_uri"],
        "end_session_endpoint": config.get("end_session_endpoint"),   # Logout
        "introspection_endpoint": config.get("introspection_endpoint"),
        "supported_scopes": config.get("scopes_supported", []),
        "supported_claims": config.get("claims_supported", []),
        "supported_algs": config.get("id_token_signing_alg_values_supported", []),
    }
    return endpoints


# =============================================================================
# SECTION 8: SCOPE vs CLAIMS — IMPORTANT DISTINCTION
# =============================================================================

# Scope: what the CLIENT is requesting permission to access.
#   Example: "openid email profile" → client wants user's email and profile data.
#   Scopes are presented to the user on the consent screen.
#   Scopes determine what the access token can do (API permissions).
#
# Claims: data fields returned in the ID token or from the UserInfo endpoint.
#   Example: {"email": "alice@gmail.com", "name": "Alice", "sub": "12345"}
#   Requesting the "email" scope results in the "email" and "email_verified"
#   claims being included in the token.
#
# Scope → Claims mapping (Google):
#   "openid"   → sub, iss, aud, exp, iat
#   "email"    → email, email_verified
#   "profile"  → name, given_name, family_name, picture, locale

SCOPE_TO_CLAIMS_MAP = {
    "openid": ["sub", "iss", "aud", "exp", "iat"],
    "email": ["email", "email_verified"],
    "profile": ["name", "given_name", "family_name", "picture", "locale"],
    "address": ["address"],
    "phone": ["phone_number", "phone_number_verified"],
}


# =============================================================================
# SECTION 9: TOKEN INTROSPECTION (RFC 7662)
# =============================================================================

# Introspection: a resource server (your API) validates an opaque access token
# by calling the AS's introspection endpoint. The AS returns whether the token
# is active and its associated metadata.
#
# Use when:
#   - Tokens are opaque (not JWTs) and you can't validate locally.
#   - You need real-time revocation checking (not cached JWTs).
#
# Downside: adds network latency per request. Cache results for short periods.

def introspect_token(
    token: str,
    introspection_endpoint: str,
    client_id: str,
    client_secret: str,
) -> dict:
    """
    Validate an opaque access token by asking the Authorization Server.
    Returns the token metadata if active, raises ValueError if inactive.
    """
    response = requests.post(
        introspection_endpoint,
        data={"token": token, "token_type_hint": "access_token"},
        auth=(client_id, client_secret),    # HTTP Basic auth to authenticate the RS
        timeout=10,
    )
    response.raise_for_status()
    result = response.json()

    if not result.get("active", False):
        raise ValueError("Token is not active (expired, revoked, or invalid)")

    # Result contains: sub, scope, exp, iat, client_id, username, etc.
    return result


# =============================================================================
# SECTION 10: KEYCLOAK INTEGRATION OVERVIEW
# =============================================================================

# Keycloak is a self-hosted open-source Identity Provider (IdP).
# Key concepts:
#   Realm     — isolated namespace (one per environment or tenant)
#   Client    — your application registration
#   User Federation — sync users from LDAP/Active Directory
#   Client Scopes — reusable scope+claims bundles
#   Roles     — Keycloak assigns roles as claims in tokens
#
# Keycloak OIDC endpoints (replace {realm} with your realm name):
#   Discovery: https://keycloak.example.com/auth/realms/{realm}/.well-known/openid-configuration
#   Authorization: https://keycloak.example.com/auth/realms/{realm}/protocol/openid-connect/auth
#   Token: https://keycloak.example.com/auth/realms/{realm}/protocol/openid-connect/token
#   JWKS: https://keycloak.example.com/auth/realms/{realm}/protocol/openid-connect/certs
#   Logout: https://keycloak.example.com/auth/realms/{realm}/protocol/openid-connect/logout

KEYCLOAK_CONFIG_EXAMPLE = {
    "server_url": "https://keycloak.example.com/auth",
    "realm": "myrealm",
    "client_id": "my-backend-api",
    "client_secret": os.environ.get("KEYCLOAK_CLIENT_SECRET", ""),
    # Keycloak adds a "realm_access" claim with roles:
    # {"realm_access": {"roles": ["admin", "user"]}}
    # And "resource_access" for client-specific roles:
    # {"resource_access": {"my-backend-api": {"roles": ["api-user"]}}}
}


def extract_keycloak_roles(id_token_claims: dict, client_id: str) -> list:
    """
    Extract roles from a Keycloak ID token.
    Realm roles are in realm_access.roles.
    Client-specific roles are in resource_access.<client_id>.roles.
    """
    realm_roles = id_token_claims.get("realm_access", {}).get("roles", [])
    client_roles = (
        id_token_claims
        .get("resource_access", {})
        .get(client_id, {})
        .get("roles", [])
    )
    # Combine both role sets — caller decides which to use for authorization
    return list(set(realm_roles + client_roles))


# =============================================================================
# SECTION 11: TOKEN STORAGE SECURITY (CLIENT-SIDE)
# =============================================================================

# Access token storage tradeoffs:
#
# Memory only (JS variable in SPA):
#   + Cannot be stolen by XSS (not in DOM/storage)
#   + Lost on page refresh — forces re-auth or silent refresh
#   - Requires refresh token to regenerate on reload
#
# httpOnly, Secure, SameSite=Strict cookie (RECOMMENDED for web):
#   + XSS cannot read it (httpOnly)
#   + Sent automatically, no JS handling needed
#   + SameSite prevents CSRF
#   - Must implement CSRF token for state-changing requests if SameSite=Lax
#
# localStorage:
#   - XSS can read it → token theft
#   - AVOID for sensitive tokens
#
# Refresh token: ALWAYS in httpOnly cookie, NEVER in localStorage.

STORAGE_RECOMMENDATION = """
Recommended pattern for SPAs:
  - Access token: in-memory JS variable (request on page load via silent refresh)
  - Refresh token: httpOnly cookie with Secure + SameSite=Strict
  - At page load: POST /auth/refresh (cookie sent automatically)
  - Backend: validates cookie refresh token, issues new access token in response body
  - SPA stores access token in memory, includes it as Authorization: Bearer header
"""


# =============================================================================
# DEMONSTRATION RUNNER
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("L03 — OAuth2 and OIDC Demo")
    print("=" * 60)

    print("\n--- PKCE Pair Generation ---")
    pkce = generate_pkce_pair()
    print(f"code_verifier (first 20 chars): {pkce['code_verifier'][:20]}...")
    print(f"code_challenge: {pkce['code_challenge'][:20]}...")
    print(f"method: {pkce['code_challenge_method']}")

    print("\n--- Build Authorization URL ---")
    auth_url, state = build_authorization_url(
        client_id="YOUR_CLIENT_ID",
        redirect_uri="https://yourapp.com/auth/callback",
        scopes=["openid", "email", "profile"],
        authorization_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        code_challenge=pkce["code_challenge"],
    )
    print(f"State: {state[:20]}...")
    print(f"Auth URL (first 80 chars): {auth_url[:80]}...")

    print("\n--- Scope to Claims Mapping ---")
    for scope, claims in SCOPE_TO_CLAIMS_MAP.items():
        print(f"  {scope!r:10} → {claims}")

    print("\n--- Token Storage Recommendation ---")
    print(STORAGE_RECOMMENDATION)

    print("\n--- OIDC Discovery (example URL) ---")
    print("Would fetch: https://accounts.google.com/.well-known/openid-configuration")
    print("Contains all endpoints, supported algorithms, scopes, claims")

    print("\n--- Keycloak Role Extraction ---")
    mock_keycloak_claims = {
        "sub": "user-123",
        "realm_access": {"roles": ["user", "admin"]},
        "resource_access": {
            "my-backend-api": {"roles": ["api-user", "report-viewer"]}
        },
    }
    roles = extract_keycloak_roles(mock_keycloak_claims, "my-backend-api")
    print(f"Extracted roles: {roles}")
