# =============================================================================
# WHAT: Authentication Fundamentals — Password Hashing, MFA, Sessions
# WHY:  Authentication is the first line of defense. Understanding WHY certain
#       algorithms are required (not just that they are) prevents catastrophic
#       mistakes like storing MD5 passwords or rolling your own crypto.
# LEVEL: Intermediate-to-Advanced (assumes Python basics, HTTP familiarity)
# =============================================================================

# ── CONCEPT OVERVIEW ──────────────────────────────────────────────────────────
# Authentication answers the question: "Who are you?"
# It is distinct from Authorization ("What are you allowed to do?").
#
# Core problem: passwords must be stored such that:
#   1. A correct password can be verified at login time.
#   2. A database breach does NOT expose the original passwords.
#   3. Offline dictionary attacks are made computationally expensive.
#
# Solution: use a slow, salted, one-way hash (bcrypt / argon2id).
#
# Modern auth stack layers:
#   Password (something you know)
#   + TOTP / hardware key (something you have)
#   + Passkeys / WebAuthn (something you are / possess cryptographically)
#   + Session management (keeps you authenticated across requests)

# ── PRODUCTION USE CASE ───────────────────────────────────────────────────────
# A Django/FastAPI web app where users register with email + password,
# optionally enable 2-FA via an authenticator app (Google Authenticator,
# Authy), and maintain state across requests using server-side sessions
# stored in Redis with a signed, HttpOnly, Secure cookie.

# ── COMMON MISTAKES ───────────────────────────────────────────────────────────
# 1. Using MD5 or SHA-256 directly — they are FAST, designed for data
#    integrity, not password storage. Millions of hashes/second = attacker wins.
# 2. Forgetting salts — identical passwords produce identical hashes, enabling
#    rainbow table lookups across your entire user table at once.
# 3. Using == for hash comparison — leaks timing information.
# 4. Hardcoding TOTP secrets in source code.
# 5. Setting session cookies without HttpOnly/Secure/SameSite flags.
# 6. No account lockout → brute force / credential stuffing possible.

# =============================================================================
# IMPORTS
# =============================================================================

import hmac          # Standard library — provides constant-time comparison
import hashlib       # Standard library — SHA family (do NOT use for passwords)
import secrets       # Standard library — cryptographically secure random bytes
import os            # Standard library — environment variables, urandom
import time          # Standard library — sleep for lockout demonstration
import base64        # Standard library — encoding for backup codes / QR data
import io            # Standard library — in-memory byte buffers

# Third-party — install via: pip install passlib[bcrypt] argon2-cffi pyotp qrcode
from passlib.context import CryptContext   # Unified hashing context (recommended)
from passlib.hash import bcrypt            # bcrypt implementation
from argon2 import PasswordHasher         # argon2-cffi: argon2id implementation
from argon2.exceptions import VerifyMismatchError, VerificationError
import pyotp                               # TOTP / HOTP per RFC 6238 / 4226
import qrcode                              # QR code generation for TOTP enrollment


# =============================================================================
# SECTION 1: WHY NOT MD5 / SHA-256 FOR PASSWORDS
# =============================================================================

def demonstrate_why_fast_hashes_are_dangerous():
    """
    Show the raw speed of SHA-256 vs the intentional slowness of bcrypt.
    Fast hashes are fine for data integrity; they are catastrophic for passwords.
    """
    password = b"hunter2"

    # SHA-256: designed to be fast — billions of hashes/second on a GPU.
    # An attacker with a $300 GPU can try billions of candidates per second.
    sha256_hash = hashlib.sha256(password).hexdigest()
    print(f"SHA-256 (WRONG for passwords): {sha256_hash}")

    # MD5: even faster, AND has known collision vulnerabilities.
    md5_hash = hashlib.md5(password).hexdigest()
    print(f"MD5 (NEVER use): {md5_hash}")

    # Notice: run this function twice with the same password — you get the
    # SAME output. No salt means rainbow tables work: pre-compute hashes
    # for the 10 million most common passwords once, then look them up
    # against every hash in a breached database instantly.
    print(
        "\nFATAL FLAW: SHA-256('hunter2') is always identical.\n"
        "One rainbow table cracks your entire user database."
    )


# =============================================================================
# SECTION 2: BCRYPT — SALTED, ADAPTIVE, WORK-FACTOR BASED
# =============================================================================

# Why bcrypt?
#   - Automatically generates and embeds a random salt per hash.
#   - "Cost factor" (work factor) controls how slow the hash is.
#   - Cost 12 ≈ ~250 ms on modern hardware — acceptable for login,
#     devastating for offline attack (attacker can only try ~4/sec per core).
#   - Cost can be raised over time as hardware improves (re-hash on next login).
#
# Format of a bcrypt hash string:
#   $2b$12$<22-char-salt><31-char-hash>
#    ↑   ↑
#  version  cost factor (rounds = 2^12 = 4096 iterations)

# Use passlib's CryptContext for a clean, future-proof API.
# Listing multiple schemes allows gradual migration (deprecated → new).
pwd_context = CryptContext(
    schemes=["bcrypt"],          # The active scheme for NEW hashes
    deprecated="auto",           # Automatically mark old schemes as deprecated
    bcrypt__rounds=12,           # Cost factor: 2^12 iterations (adjust if login > 500 ms)
)


def hash_password_bcrypt(plaintext: str) -> str:
    """
    Hash a plaintext password. Returns an opaque string safe to store in DB.
    The salt is embedded in the returned string — do NOT store it separately.
    """
    # pwd_context.hash() calls bcrypt under the hood, generates a fresh
    # cryptographically random 128-bit salt for each call automatically.
    hashed = pwd_context.hash(plaintext)
    return hashed


def verify_password_bcrypt(plaintext: str, hashed: str) -> bool:
    """
    Verify a plaintext against a stored bcrypt hash.
    Returns True if correct. NEVER compare with ==.

    Also returns whether a rehash is needed (cost factor was upgraded).
    """
    # verify_and_update() uses constant-time comparison internally.
    # It also detects if the stored hash used a deprecated scheme or
    # lower cost factor, signaling you should rehash on next login.
    valid, new_hash = pwd_context.verify_and_update(plaintext, hashed)

    if new_hash:
        # The stored hash used an old/weaker cost factor.
        # Generate a new hash and update the database record NOW
        # (while the user is authenticated and we have the plaintext).
        print(f"[INFO] Rehashing password with new cost factor: {new_hash[:20]}...")
        # In real code: db.update_user_password(user_id, new_hash)

    return valid


# =============================================================================
# SECTION 3: ARGON2ID — WINNER OF THE PASSWORD HASHING COMPETITION (PHC)
# =============================================================================

# Argon2 won the Password Hashing Competition in 2015. Three variants:
#   argon2d  — maximizes resistance to GPU attacks (vulnerable to side-channel)
#   argon2i  — side-channel resistant (used in password managers)
#   argon2id — HYBRID: recommended for most use cases (NIST SP 800-63B)
#
# Why argon2id is superior to bcrypt:
#   - MEMORY-HARD: requires a configurable amount of RAM. GPUs have limited
#     memory bandwidth — forcing 64 MB of RAM per hash makes GPU parallelism
#     impractical. bcrypt is NOT memory-hard.
#   - Configurable parallelism: can use multiple CPU threads per hash.
#   - Designed for modern hardware; bcrypt predates 64-bit CPUs.
#
# Parameters (tune so hash takes ~300-500 ms on your server):
#   time_cost   — number of iterations (like bcrypt rounds)
#   memory_cost — RAM in kibibytes (64 MB = 65536 KiB)
#   parallelism — number of parallel threads

ph = PasswordHasher(
    time_cost=3,         # 3 iterations
    memory_cost=65536,   # 64 MiB of RAM required per hash attempt
    parallelism=2,       # Use 2 threads
    hash_len=32,         # Output hash length in bytes
    salt_len=16,         # Salt length in bytes (automatically generated)
    encoding="utf-8",    # String encoding
)


def hash_password_argon2(plaintext: str) -> str:
    """
    Hash password using argon2id. Returns a PHC-format string:
    $argon2id$v=19$m=65536,t=3,p=2$<base64-salt>$<base64-hash>
    """
    return ph.hash(plaintext)    # Salt is auto-generated per call


def verify_password_argon2(plaintext: str, hashed: str) -> bool:
    """
    Verify plaintext against argon2id hash. Returns True if correct.
    Raises VerifyMismatchError on failure (do NOT expose this to users).
    """
    try:
        ph.verify(hashed, plaintext)   # Raises on mismatch

        # Check if the hash needs rehashing (parameters were upgraded)
        if ph.check_needs_rehash(hashed):
            new_hash = ph.hash(plaintext)
            print("[INFO] Argon2 rehash needed. New hash stored.")
            # db.update_user_password(user_id, new_hash)

        return True

    except VerifyMismatchError:
        return False      # Wrong password — do NOT log the attempted password
    except VerificationError:
        return False      # Hash is malformed / incompatible


# =============================================================================
# SECTION 4: SALTING — WHY IT DEFEATS RAINBOW TABLES
# =============================================================================

def demonstrate_salting():
    """
    Show that two hashes of the same password are always DIFFERENT due to
    random salting. This defeats pre-computed rainbow tables completely.
    """
    password = "password123"

    hash1 = hash_password_argon2(password)
    hash2 = hash_password_argon2(password)

    # These will be completely different strings despite identical input.
    print(f"Hash 1: {hash1[:50]}...")
    print(f"Hash 2: {hash2[:50]}...")
    print(f"Are they equal? {hash1 == hash2}")  # Always False

    # Rainbow table attack: "I pre-computed hash('password123') = X.
    # If I see X in the database, I know the password."
    #
    # With salting: hash('password123' + random_salt) varies every time.
    # The attacker would need a separate rainbow table for every possible salt
    # value — computationally infeasible (2^128 possible salts).


# =============================================================================
# SECTION 5: TIMING ATTACKS AND CONSTANT-TIME COMPARISON
# =============================================================================

# A timing attack exploits the fact that string comparison (==) returns False
# as soon as the FIRST differing byte is found. If an attacker can measure
# response time precisely, they can infer character-by-character matches.
#
# Example: checking if a submitted API key matches the real one:
#   "AAAA..." vs "XAAA..." — returns immediately (first char differs)
#   "XAAA..." vs "XXXX..." — returns after 3 chars match
# By measuring tiny time differences, the attacker reconstructs the secret.

def unsafe_comparison(user_input: str, real_secret: str) -> bool:
    """
    VULNERABLE: Regular string comparison leaks timing information.
    DO NOT use for secrets, tokens, or hashes.
    """
    return user_input == real_secret    # Short-circuits on first mismatch


def safe_comparison(user_input: str, real_secret: str) -> bool:
    """
    SAFE: hmac.compare_digest compares ALL bytes in constant time regardless
    of where the first mismatch occurs. Timing is identical for all inputs
    of the same length, eliminating the timing side-channel.
    """
    # Encode to bytes first — compare_digest works on bytes or str
    a = user_input.encode("utf-8")
    b = real_secret.encode("utf-8")
    return hmac.compare_digest(a, b)    # Always examines every byte


# =============================================================================
# SECTION 6: TOTP — TIME-BASED ONE-TIME PASSWORDS (RFC 6238)
# =============================================================================

# TOTP Algorithm:
#   1. Share a secret key between server and authenticator app during setup.
#   2. Both parties compute HMAC-SHA1(secret, floor(unix_time / 30)).
#   3. Truncate to a 6-digit code. Code changes every 30 seconds.
#   4. At login, server computes the same code and compares. No network needed.
#
# Why it's secure: attacker needs BOTH the password AND physical access
# to the authenticator device (phone). Phishing a password alone is useless.

def generate_totp_secret() -> str:
    """
    Generate a cryptographically random base32 secret for TOTP.
    This is shared ONCE during enrollment. Store it encrypted in the DB.
    """
    # pyotp.random_base32() uses os.urandom() internally — cryptographically secure.
    # Length 32 characters = 160 bits of entropy.
    secret = pyotp.random_base32()
    return secret


def get_totp_uri(secret: str, username: str, issuer: str = "MyApp") -> str:
    """
    Generate the otpauth:// URI used to provision authenticator apps via QR code.
    Format: otpauth://totp/ISSUER:USERNAME?secret=SECRET&issuer=ISSUER
    """
    totp = pyotp.TOTP(secret)
    # provisioning_uri creates the standard URI that Google Authenticator,
    # Authy, and 1Password all understand.
    uri = totp.provisioning_uri(name=username, issuer_name=issuer)
    return uri


def generate_qr_code(totp_uri: str) -> bytes:
    """
    Generate a PNG QR code image from the otpauth:// URI.
    Returns raw PNG bytes to send as HTTP response or embed in page.
    """
    qr = qrcode.QRCode(
        version=1,                          # QR version (auto-scaled)
        error_correction=qrcode.constants.ERROR_CORRECT_L,  # Low error correction (smaller)
        box_size=10,                        # Pixels per box
        border=4,                           # Quiet zone border width
    )
    qr.add_data(totp_uri)
    qr.make(fit=True)                      # Auto-fit data to QR version

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()               # Raw PNG bytes


def verify_totp(secret: str, user_submitted_code: str, valid_window: int = 1) -> bool:
    """
    Verify a TOTP code submitted by the user.

    valid_window=1 allows 1 step before/after current time (±30 seconds)
    to account for clock drift between server and authenticator device.
    Do NOT set valid_window > 1 in production — it weakens the guarantee.
    """
    totp = pyotp.TOTP(secret)
    # verify() does constant-time comparison internally.
    # valid_window=1 checks current_code, previous_code, and next_code.
    return totp.verify(user_submitted_code, valid_window=valid_window)


def generate_backup_codes(count: int = 8) -> list:
    """
    Generate one-time-use backup codes for account recovery when the
    authenticator device is lost. Store HASHED versions in the DB,
    not plaintext (treat like passwords).

    Format: XXXX-XXXX-XXXX (12 hex characters, human-readable groups)
    """
    codes = []
    for _ in range(count):
        # secrets.token_hex(6) = 6 random bytes = 12 hex chars = 48 bits entropy
        raw = secrets.token_hex(6).upper()
        # Group into readable chunks: "A1B2-C3D4-E5F6" style
        formatted = f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}"
        codes.append(formatted)

    # IMPORTANT: Show codes to user ONCE. Then hash and store hashed versions.
    # On use: verify submitted code against stored hash, then DELETE the hash
    # (each code is single-use only).
    return codes


# =============================================================================
# SECTION 7: WEBAUTHN / PASSKEYS OVERVIEW
# =============================================================================

# WebAuthn (Web Authentication API, W3C + FIDO2) is the future of auth:
#
#   Registration flow:
#     1. Server sends a challenge (random bytes) to the browser.
#     2. Browser asks the authenticator (TouchID, FaceID, YubiKey, phone).
#     3. Authenticator generates a NEW keypair scoped to this origin.
#     4. Public key + signed challenge sent to server. Server stores public key.
#     5. Private key NEVER leaves the device.
#
#   Authentication flow:
#     1. Server sends a challenge.
#     2. Authenticator signs the challenge with the stored private key.
#     3. Server verifies signature using the stored public key.
#
# Why passkeys are superior:
#   - Immune to phishing (keys are scoped to exact origin — no cross-site use)
#   - No shared secret that can be breached from the server
#   - No password to intercept, guess, or reuse
#   - Biometric is local to device, never sent over network
#
# Python library: py_webauthn (pip install webauthn)
# Note: Full WebAuthn implementation is lengthy; see py_webauthn docs for
# complete registration/authentication flows. The concepts above are the key.

WEBAUTHN_NOTES = """
Key WebAuthn concepts:
  - Relying Party (RP): your server/app
  - Authenticator: device (platform) or security key (roaming)
  - Credential ID: unique identifier for the public key stored server-side
  - User verification: biometric/PIN checked locally (UV flag must be True)
  - Attestation: proof the authenticator is a genuine FIDO device (optional)
  - Challenge: server-generated random bytes, prevents replay attacks
"""


# =============================================================================
# SECTION 8: SESSION-BASED AUTHENTICATION
# =============================================================================

# Session auth flow:
#   1. User submits credentials.
#   2. Server verifies password hash.
#   3. Server creates a session: generates a random session ID, stores
#      user data in server-side storage (DB/Redis) keyed by session ID.
#   4. Server sends session ID to browser via a Set-Cookie header.
#   5. Browser sends cookie automatically on every subsequent request.
#   6. Server looks up session ID → retrieves user data → authorizes request.
#
# Cookie flags (ALL must be set in production):
#   HttpOnly  — cookie inaccessible to JavaScript (prevents XSS theft)
#   Secure    — cookie only sent over HTTPS (prevents network interception)
#   SameSite=Strict — cookie not sent on cross-site requests (prevents CSRF)
#   Max-Age   — expiry prevents indefinite session persistence

def generate_session_id() -> str:
    """
    Generate a cryptographically random session ID.
    Must be at least 128 bits (16 bytes) of entropy.
    secrets.token_urlsafe(32) gives 256 bits — well above threshold.
    """
    # token_urlsafe uses os.urandom() and base64url-encodes the result.
    # The output is URL-safe: no +, /, or = characters.
    return secrets.token_urlsafe(32)    # 32 bytes → 43-char base64url string


# Simulated in-memory session store (use Redis in production)
_session_store: dict = {}


def create_session(user_id: int, user_data: dict) -> str:
    """
    Create a new session. Returns session ID to set as cookie value.
    In production: store in Redis with TTL, not in-process dict.
    """
    session_id = generate_session_id()

    # Session fixation prevention: ALWAYS generate a NEW session ID after
    # authentication. If attacker planted a known session ID (via URL param
    # or cookie injection), a new ID invalidates their planted value.
    # NEVER reuse a pre-authentication session ID post-login.

    _session_store[session_id] = {
        "user_id": user_id,
        "data": user_data,
        "created_at": time.time(),         # Track session creation time
        "last_active": time.time(),        # Track inactivity for auto-expiry
    }
    return session_id


def get_session(session_id: str) -> dict:
    """
    Retrieve session data. Returns None if session doesn't exist or expired.
    """
    session = _session_store.get(session_id)
    if session is None:
        return None     # Session not found — treat as unauthenticated

    # Check absolute session age (e.g., max 8 hours regardless of activity)
    if time.time() - session["created_at"] > 8 * 3600:
        del _session_store[session_id]    # Expire the session
        return None

    # Check inactivity timeout (e.g., 30 minutes of no requests)
    if time.time() - session["last_active"] > 30 * 60:
        del _session_store[session_id]    # Expire idle session
        return None

    session["last_active"] = time.time()   # Refresh activity timestamp
    return session


def destroy_session(session_id: str) -> None:
    """
    Invalidate a session on logout. Must also clear the cookie client-side
    by setting Set-Cookie: session_id=; Max-Age=0; HttpOnly; Secure; SameSite=Strict
    """
    _session_store.pop(session_id, None)   # Remove from store (ignore if missing)


# Cookie header to set in HTTP response (Flask/FastAPI/Django example):
#   response.set_cookie(
#       key="session_id",
#       value=session_id,
#       httponly=True,          # No JS access
#       secure=True,            # HTTPS only
#       samesite="Strict",      # No cross-site sending
#       max_age=8 * 3600,       # 8 hours
#       path="/",               # Accessible across all paths
#   )


# =============================================================================
# SECTION 9: ACCOUNT LOCKOUT AND CREDENTIAL STUFFING DEFENSE
# =============================================================================

# Credential stuffing: attacker uses breached username:password combos
# (from other sites) and tries them against your login. Effective because
# ~65% of people reuse passwords.
#
# Defenses:
#   1. Account lockout (slow attackers, alert users)
#   2. Rate limiting by IP (covers distributed attacks)
#   3. CAPTCHA after N failures (slows automated scripts)
#   4. Breached password check (Have I Been Pwned API)
#   5. Device fingerprinting + anomaly detection

# Simple in-memory lockout tracker (use Redis + TTL in production)
_failed_attempts: dict = {}

LOCKOUT_THRESHOLD = 5      # Lock after this many failures
LOCKOUT_WINDOW = 300       # Seconds — count failures within this window (5 min)
LOCKOUT_DURATION = 900     # Seconds — lock lasts this long (15 min)
_lockout_until: dict = {}  # username → lockout expiry timestamp


def record_failed_login(username: str) -> bool:
    """
    Record a failed login attempt. Returns True if account is now locked.
    Call this AFTER verifying the password fails.
    """
    now = time.time()

    # Clean up old attempts outside the rolling window
    attempts = _failed_attempts.get(username, [])
    attempts = [t for t in attempts if now - t < LOCKOUT_WINDOW]  # Keep recent only
    attempts.append(now)                      # Record this failure
    _failed_attempts[username] = attempts

    if len(attempts) >= LOCKOUT_THRESHOLD:
        # Lock the account
        _lockout_until[username] = now + LOCKOUT_DURATION
        print(f"[SECURITY] Account '{username}' locked for {LOCKOUT_DURATION}s")
        return True    # Locked

    return False   # Not yet locked


def is_account_locked(username: str) -> bool:
    """
    Check if an account is currently locked. Call BEFORE password verification
    to avoid unnecessary hashing work AND to prevent timing oracle.
    """
    lockout_time = _lockout_until.get(username)
    if lockout_time is None:
        return False                           # Never locked
    if time.time() > lockout_time:
        # Lockout has expired — clean up
        del _lockout_until[username]
        _failed_attempts.pop(username, None)
        return False
    return True                                # Still locked


def check_breached_password(password: str) -> bool:
    """
    Check if a password appears in the Have I Been Pwned (HIBP) database
    using the k-Anonymity API — the full password is NEVER sent to HIBP.

    Flow:
      1. SHA-1 hash the password locally.
      2. Send only the first 5 hex characters to HIBP API.
      3. HIBP returns all hashes starting with those 5 chars.
      4. Check locally if our full hash appears in the response.

    This preserves privacy: HIBP never learns the password or full hash.
    """
    # SHA-1 is fine here — we're using it as a lookup key, not for security.
    sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix = sha1[:5]       # Send only first 5 chars
    suffix = sha1[5:]       # Keep the rest for local comparison

    # In real code:
    # import requests
    # response = requests.get(f"https://api.pwnedpasswords.com/range/{prefix}")
    # breached = any(line.split(":")[0] == suffix for line in response.text.splitlines())
    print(f"[HIBP] Would query: https://api.pwnedpasswords.com/range/{prefix}")
    print(f"[HIBP] Would check response for suffix: {suffix}")
    print("[HIBP] If suffix found, reject the password and prompt for a different one")
    return False    # Placeholder — real impl returns True if found in breach list


# =============================================================================
# DEMONSTRATION RUNNER
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("L01 — Authentication Fundamentals Demo")
    print("=" * 60)

    print("\n--- Why Fast Hashes Are Dangerous ---")
    demonstrate_why_fast_hashes_are_dangerous()

    print("\n--- Bcrypt Hashing ---")
    h = hash_password_bcrypt("mySecurePassword!")
    print(f"Hash: {h}")
    print(f"Verify correct: {verify_password_bcrypt('mySecurePassword!', h)}")
    print(f"Verify wrong:   {verify_password_bcrypt('wrongpassword', h)}")

    print("\n--- Argon2id Hashing ---")
    h2 = hash_password_argon2("mySecurePassword!")
    print(f"Hash: {h2[:60]}...")
    print(f"Verify correct: {verify_password_argon2('mySecurePassword!', h2)}")
    print(f"Verify wrong:   {verify_password_argon2('wrongpassword', h2)}")

    print("\n--- Salting Demonstration ---")
    demonstrate_salting()

    print("\n--- TOTP Flow ---")
    secret = generate_totp_secret()
    print(f"TOTP Secret: {secret}")
    uri = get_totp_uri(secret, "alice@example.com", "MyApp")
    print(f"OTP URI: {uri[:60]}...")
    current_code = pyotp.TOTP(secret).now()    # What the app would show
    print(f"Current TOTP code: {current_code}")
    print(f"Verify code: {verify_totp(secret, current_code)}")

    print("\n--- Backup Codes ---")
    codes = generate_backup_codes(4)
    for code in codes:
        print(f"  {code}")

    print("\n--- Account Lockout ---")
    for i in range(6):
        locked = record_failed_login("alice@example.com")
        print(f"  Attempt {i+1}: locked={locked}")
    print(f"Is locked: {is_account_locked('alice@example.com')}")

    print("\n--- Breached Password Check ---")
    check_breached_password("password123")
