# =============================================================================
# WHAT: OWASP Top 10 (2021) — Vulnerabilities and Fixes in Python
# WHY:  The OWASP Top 10 represents the most critical web application security
#       risks, validated by real-world breach data. Knowing both the vulnerable
#       pattern AND the correct fix is essential for any developer writing
#       production code. Security by recognition beats security by coincidence.
# LEVEL: Intermediate (assumes web app development familiarity)
# =============================================================================

# ── CONCEPT OVERVIEW ──────────────────────────────────────────────────────────
# OWASP Top 10 — 2021 Edition:
#   A01: Broken Access Control       (moved up from #5 — most widespread)
#   A02: Cryptographic Failures      (formerly "Sensitive Data Exposure")
#   A03: Injection                   (SQL, OS command, LDAP, XSS)
#   A04: Insecure Design             (missing rate limits, trust boundaries)
#   A05: Security Misconfiguration   (debug mode, defaults, unnecessary features)
#   A06: Vulnerable and Outdated Components
#   A07: Identification & Auth Failures (formerly "Broken Authentication")
#   A08: Software and Data Integrity Failures (SSRF moved here)
#   A09: Security Logging & Monitoring Failures
#   A10: Server-Side Request Forgery (SSRF)
#
# Each section below shows: VULNERABLE code → SECURE code → explanation.

# ── PRODUCTION USE CASE ───────────────────────────────────────────────────────
# A FastAPI/Flask web application with a PostgreSQL database.
# Most examples use patterns directly applicable to any Python web framework.

# ── COMMON MISTAKES ───────────────────────────────────────────────────────────
# The single most common pattern across ALL 10 items: trusting user input.
# User-controlled data must always be validated, escaped, or denied by default.

# =============================================================================
# IMPORTS
# =============================================================================

import os               # Environment variables
import re               # Regex for input validation
import hmac             # Constant-time comparison
import hashlib          # Hashing utilities (also shows MD5 anti-pattern)
import secrets          # Cryptographic random tokens
import time             # Rate limiting timestamps
import subprocess       # OS command execution (shows safe usage)
import sqlite3          # Database (demonstrates SQL injection)
import logging          # Logging (demonstrates PII anti-pattern)
import urllib.parse     # URL parsing for SSRF validation
import ipaddress        # IP range checking for SSRF allow-list

# Third-party — install via: pip install passlib[bcrypt] requests
from passlib.context import CryptContext


# =============================================================================
# A01: BROKEN ACCESS CONTROL
# =============================================================================
# Most prevalent issue: 94% of tested apps had some form of broken access control.
# Core flaw: the server doesn't verify that the authenticated user is ALLOWED
# to access the requested SPECIFIC resource (not just that they're logged in).
#
# IDOR (Insecure Direct Object Reference): user changes an ID in the URL/body
# to access another user's data. Classic: /api/orders/1234 → /api/orders/1235

# ── VULNERABLE ────────────────────────────────────────────────────────────────

def get_order_VULNERABLE(order_id: int, requesting_user_id: int) -> dict:
    """
    VULNERABLE: Fetches any order by ID without checking ownership.
    User 42 can fetch order belonging to user 99 by guessing the order_id.
    """
    # db.execute returns mock data for illustration
    # The query has NO WHERE clause filtering by the requesting user
    query = f"SELECT * FROM orders WHERE id = {order_id}"
    # result = db.execute(query).fetchone()   # Returns order regardless of owner
    # return result
    return {"id": order_id, "data": "order data — accessible to anyone who guesses id"}


# ── SECURE ────────────────────────────────────────────────────────────────────

def get_order_SECURE(order_id: int, requesting_user_id: int, db) -> dict:
    """
    SECURE: Fetches order only if the requesting user owns it.
    Even if the order_id is guessed, the WHERE clause enforces ownership.
    Authorization check is enforced at the DATA layer, not just the API layer.
    """
    # Parameterized query with ownership check — the database enforces access
    result = db.execute(
        "SELECT * FROM orders WHERE id = ? AND user_id = ?",
        (order_id, requesting_user_id)   # User can only see their own orders
    ).fetchone()

    if result is None:
        # Return the same error whether the order doesn't exist OR belongs to
        # someone else. Don't reveal which — prevents enumeration attacks.
        raise PermissionError("Order not found or access denied")

    return dict(result)


# Additional A01 patterns:

def check_admin_role_SECURE(user: dict, required_role: str) -> bool:
    """
    Always verify role/permission server-side — never trust client claims.
    Never use: if request.headers.get("X-Admin") == "true":
    """
    user_roles = user.get("roles", [])     # Roles from VERIFIED session/JWT
    if required_role not in user_roles:
        raise PermissionError(f"User lacks required role: {required_role}")
    return True


# Directory traversal — another A01 variant
def read_user_file_VULNERABLE(filename: str) -> bytes:
    """VULNERABLE: User can pass ../../etc/passwd to read arbitrary files."""
    path = f"/app/user-uploads/{filename}"
    with open(path, "rb") as f:
        return f.read()


def read_user_file_SECURE(filename: str, base_dir: str = "/app/user-uploads") -> bytes:
    """
    SECURE: Resolve the real path and verify it stays within base_dir.
    os.path.realpath() resolves all symlinks and .. components.
    """
    import os.path
    # Construct and fully resolve the path
    requested_path = os.path.realpath(os.path.join(base_dir, filename))
    real_base = os.path.realpath(base_dir)

    # Ensure the resolved path starts with the base directory
    if not requested_path.startswith(real_base + os.sep):
        raise ValueError("Path traversal attempt detected")

    with open(requested_path, "rb") as f:
        return f.read()


# =============================================================================
# A02: CRYPTOGRAPHIC FAILURES
# =============================================================================
# Formerly called "Sensitive Data Exposure". The root cause is weak or missing
# cryptography, not just data leakage. Key failure modes:
#   - Using MD5/SHA1 for passwords
#   - Transmitting sensitive data over HTTP instead of HTTPS
#   - Weak encryption (DES, RC4, ECB mode AES)
#   - Hardcoded keys or predictable IVs

# ── VULNERABLE ────────────────────────────────────────────────────────────────

def store_password_VULNERABLE(password: str) -> str:
    """
    VULNERABLE: MD5 is a fast, unsalted hash.
    - No salt → rainbow tables crack the entire user table at once.
    - Fast → billions of guesses per second on a GPU.
    - MD5 is cryptographically broken (collision attacks exist).
    """
    return hashlib.md5(password.encode()).hexdigest()   # NEVER do this


def store_password_sha256_VULNERABLE(password: str) -> str:
    """
    VULNERABLE: SHA-256 is better than MD5 but STILL wrong for passwords.
    SHA-256 is designed to be fast for data integrity — that's the problem.
    """
    return hashlib.sha256(password.encode()).hexdigest()  # Still wrong


# ── SECURE ────────────────────────────────────────────────────────────────────

_pwd_ctx = CryptContext(schemes=["bcrypt"], bcrypt__rounds=12)


def store_password_SECURE(password: str) -> str:
    """
    SECURE: bcrypt with cost factor 12.
    - Automatic random salt per hash (embedded in output string).
    - Intentionally slow: ~250 ms per hash on modern hardware.
    - Cost factor can be increased as hardware improves (just re-hash on login).
    """
    return _pwd_ctx.hash(password)    # Salt auto-generated and embedded


def verify_password_SECURE(password: str, stored_hash: str) -> bool:
    """SECURE: Constant-time comparison built into passlib."""
    return _pwd_ctx.verify(password, stored_hash)


# Encryption failure: ECB mode leaks patterns
def demonstrate_ecb_problem():
    """
    ECB (Electronic Codebook) mode encrypts each 16-byte block independently.
    Identical plaintext blocks produce identical ciphertext blocks.
    This leaks data patterns even when the data is "encrypted."
    Always use AES-GCM (authenticated encryption) in production.
    """
    print("ECB mode: identical plaintext blocks → identical ciphertext blocks")
    print("Fix: use AES-256-GCM (provides confidentiality + integrity + authenticity)")
    print("pip install cryptography → from cryptography.hazmat.primitives.ciphers.aead import AESGCM")


# =============================================================================
# A03: INJECTION
# =============================================================================
# Injection occurs when untrusted data is sent to an interpreter as part of
# a command or query. The interpreter cannot distinguish code from data.
#
# Types: SQL injection, OS command injection, LDAP injection, XSS, XXE.

# ── SQL INJECTION — VULNERABLE ────────────────────────────────────────────────

def get_user_SQLI_VULNERABLE(username: str, db) -> dict:
    """
    VULNERABLE: String concatenation in SQL query.
    Attacker input: username = "' OR '1'='1" → returns ALL users.
    Attacker input: username = "'; DROP TABLE users;--" → destroys data.
    """
    query = f"SELECT * FROM users WHERE username = '{username}'"
    # result = db.execute(query).fetchone()
    return {"query": query, "note": "VULNERABLE to SQL injection"}


# ── SQL INJECTION — SECURE ─────────────────────────────────────────────────────

def get_user_SQLI_SECURE(username: str, db) -> dict:
    """
    SECURE: Parameterized query (prepared statement).
    The database driver sends the query structure and data SEPARATELY.
    The database never interprets the data as SQL code.
    This works regardless of what characters the username contains.
    """
    # The ? placeholder is for sqlite3. Use %s for psycopg2, :name for SQLAlchemy.
    result = db.execute(
        "SELECT * FROM users WHERE username = ?",
        (username,)    # Data is passed as parameter — not concatenated into SQL
    ).fetchone()
    return dict(result) if result else {}


# Using an ORM (SQLAlchemy) — parameterization is automatic:
# user = db.query(User).filter(User.username == username).first()
# The ORM NEVER puts raw user input directly into the SQL string.

# ── OS COMMAND INJECTION — VULNERABLE ────────────────────────────────────────

def ping_host_VULNERABLE(hostname: str) -> str:
    """
    VULNERABLE: shell=True with user-supplied input.
    Attacker input: "google.com; rm -rf /"
    subprocess runs: ping google.com; rm -rf /
    The semicolon allows chaining arbitrary commands.
    """
    result = subprocess.run(
        f"ping -c 1 {hostname}",    # User input directly in shell command string
        shell=True,                  # shell=True parses the string through /bin/sh
        capture_output=True,
        text=True,
    )
    return result.stdout


# ── OS COMMAND INJECTION — SECURE ────────────────────────────────────────────

def ping_host_SECURE(hostname: str) -> str:
    """
    SECURE: Pass command as a LIST (no shell interpolation) + validate input.
    When shell=False (default) and command is a list, each element is passed
    as a separate argv argument — the shell never sees the string.
    Semicolons, pipes, and backticks are treated as literal characters.
    """
    # First: validate the hostname is safe — allow only valid hostname characters
    if not re.match(r"^[a-zA-Z0-9.\-]+$", hostname):
        raise ValueError(f"Invalid hostname: {hostname!r}")

    # Maximum length check — prevents extremely long input
    if len(hostname) > 253:
        raise ValueError("Hostname too long")

    result = subprocess.run(
        ["ping", "-c", "1", hostname],   # List form — no shell expansion
        shell=False,                      # Default: do NOT use shell (explicit for clarity)
        capture_output=True,
        text=True,
        timeout=10,                       # Prevent hanging processes
    )
    return result.stdout


# =============================================================================
# A04: INSECURE DESIGN
# =============================================================================
# Design-level flaws that cannot be fixed by just patching code —
# the architecture itself is broken. Examples: no rate limiting on auth,
# missing trust boundaries, business logic flaws.

# ── VULNERABLE: No rate limiting on password reset ────────────────────────────

_reset_attempts: dict = {}    # Shared state for demonstration

def send_password_reset_VULNERABLE(email: str) -> str:
    """
    VULNERABLE: No rate limiting — attacker can flood users with reset emails,
    or enumerate valid emails by timing differences, or brute-force reset codes.
    """
    token = secrets.token_urlsafe(32)
    # db.store_reset_token(email, token)
    # email_service.send(email, token)
    return f"Reset link sent (token: {token[:8]}...)"   # In real code: no token in response


# ── SECURE: Rate limiting on sensitive endpoints ──────────────────────────────

_reset_rate: dict = {}    # email → list of request timestamps

def send_password_reset_SECURE(email: str) -> str:
    """
    SECURE: Rate-limit reset requests per email address.
    Maximum 3 reset emails per hour per email address.
    In production: use Redis + a proper rate limiting library (slowapi, limits).
    """
    now = time.time()
    LIMIT = 3           # Max requests
    WINDOW = 3600       # Per hour (seconds)

    # Clean old timestamps outside the window
    timestamps = [t for t in _reset_rate.get(email, []) if now - t < WINDOW]

    if len(timestamps) >= LIMIT:
        # Return the SAME response as success — do NOT reveal why it failed.
        # Revealing "rate limited" confirms the email is in your system.
        return "If that email exists, a reset link has been sent"

    timestamps.append(now)
    _reset_rate[email] = timestamps

    token = secrets.token_urlsafe(32)
    # db.store_reset_token(email, hashlib.sha256(token.encode()).hexdigest())
    # ^ Hash the token before storage — treat it like a password
    # email_service.send(email, token)
    return "If that email exists, a reset link has been sent"


# =============================================================================
# A05: SECURITY MISCONFIGURATION
# =============================================================================
# Gaps from insecure defaults, unnecessary features, verbose error messages,
# default credentials, debug mode in production.

# ── VULNERABLE ────────────────────────────────────────────────────────────────

FLASK_CONFIG_VULNERABLE = {
    "DEBUG": True,             # Exposes interactive debugger — RCE if public!
    "SECRET_KEY": "dev",       # Predictable — session forgery possible
    "SQLALCHEMY_ECHO": True,   # Logs ALL SQL queries — leaks schema to logs
}


def handle_error_VULNERABLE(e: Exception) -> dict:
    """
    VULNERABLE: Returns full stack trace to the client.
    Exposes: file paths, library versions, database schema, logic clues.
    """
    import traceback
    return {
        "error": str(e),
        "traceback": traceback.format_exc(),   # NEVER expose to users
        "type": type(e).__name__,
    }


# ── SECURE ────────────────────────────────────────────────────────────────────

FLASK_CONFIG_SECURE = {
    "DEBUG": os.environ.get("DEBUG", "false").lower() == "true",   # Default off
    "SECRET_KEY": os.environ.get("SECRET_KEY"),  # From environment / secrets manager
    "SQLALCHEMY_ECHO": False,    # SQL logging off in production
    "SESSION_COOKIE_HTTPONLY": True,
    "SESSION_COOKIE_SECURE": True,
    "SESSION_COOKIE_SAMESITE": "Strict",
}


def handle_error_SECURE(e: Exception, request_id: str) -> dict:
    """
    SECURE: Log full error internally, return a generic message to the client.
    The request_id lets ops correlate the client-reported ID to internal logs.
    """
    import traceback
    # Log full details internally (never returned to client)
    logging.error(
        "Internal error [%s]: %s\n%s",
        request_id,
        str(e),
        traceback.format_exc()
    )
    # Return minimal, non-revealing error to client
    return {
        "error": "An internal error occurred",
        "request_id": request_id,   # Client can quote this to support — not a secret
    }


# =============================================================================
# A06: VULNERABLE AND OUTDATED COMPONENTS
# =============================================================================
# Using libraries with known CVEs puts your app at risk even if your own code
# is perfect. Supply chain attacks are increasing.

DEPENDENCY_SCANNING_NOTES = """
Tools to scan Python dependencies:

1. pip-audit (recommended):
   pip install pip-audit
   pip-audit                          # Scan installed packages
   pip-audit -r requirements.txt     # Scan from requirements file
   pip-audit --fix                    # Auto-upgrade where possible

2. safety:
   pip install safety
   safety check                       # Check against known vulnerability DB
   safety check -r requirements.txt

3. GitHub Dependabot:
   Add .github/dependabot.yml to auto-open PRs for outdated/vulnerable deps

4. Snyk:
   snyk test                          # Checks all installed packages

Best practices:
   - Pin all direct dependencies with exact versions in requirements.txt
   - Use pip-compile (pip-tools) to lock transitive dependencies
   - Run pip-audit in CI/CD pipeline — fail the build on HIGH/CRITICAL CVEs
   - Review changelogs before upgrading (supply chain: malicious maintainer takeover)
   - Use virtual environments — never install packages globally
"""


def check_requirements_for_vulnerabilities():
    """
    Demonstrate how to invoke pip-audit programmatically.
    In CI: run pip-audit --format json and parse the output.
    """
    print("Run in terminal: pip-audit -r requirements.txt")
    print("Or in CI: pip-audit --format json | jq '.vulnerabilities'")
    print("Exit code 1 if vulnerabilities found — use to fail the CI build")


# =============================================================================
# A07: IDENTIFICATION AND AUTHENTICATION FAILURES
# =============================================================================
# Brute force, credential stuffing, weak passwords, missing MFA.
# Solution: lockout + rate limiting + strong password policy.

# ── VULNERABLE: No lockout ────────────────────────────────────────────────────

def login_VULNERABLE(username: str, password: str, db) -> str:
    """
    VULNERABLE: Unlimited login attempts — trivially brute-forceable.
    Attacker can try millions of passwords; no lockout or delay.
    """
    user = db.get_user(username)
    if user and user["password"] == password:    # Also: plaintext comparison, no hash!
        return "logged in"
    return "invalid credentials"


# ── SECURE: Lockout + hashed passwords ───────────────────────────────────────

_login_failures: dict = {}   # username → list of failure timestamps
_locked_until: dict = {}     # username → lockout expiry

def login_SECURE(username: str, password: str, db) -> str:
    """
    SECURE: Check lockout before attempting verification.
    After 5 failures in 10 minutes, lock for 15 minutes.
    Add artificial delay to slow automated attacks even when not locked.
    """
    now = time.time()
    LIMIT = 5
    WINDOW = 600     # 10 minutes
    LOCKOUT = 900    # 15 minutes

    # 1. Check lockout FIRST — before any password verification work
    locked_until = _locked_until.get(username)
    if locked_until and now < locked_until:
        # Fail fast — same response as bad password (don't confirm account exists)
        return "Invalid credentials"

    # 2. Simulate DB lookup and hash verification
    # user = db.get_user(username)
    # valid = user and _pwd_ctx.verify(password, user["password_hash"])
    # For demonstration:
    valid = False    # Placeholder

    if not valid:
        # Record failure
        failures = [t for t in _login_failures.get(username, []) if now - t < WINDOW]
        failures.append(now)
        _login_failures[username] = failures

        if len(failures) >= LIMIT:
            _locked_until[username] = now + LOCKOUT
            logging.warning("Account locked due to repeated failures: %s", username)

        # Add jitter to prevent timing oracle (constant ~100ms regardless of username)
        time.sleep(0.1)
        return "Invalid credentials"

    # 3. Clear failures on successful login
    _login_failures.pop(username, None)
    _locked_until.pop(username, None)
    return "logged in"


# =============================================================================
# A08: SOFTWARE AND DATA INTEGRITY FAILURES / SSRF
# =============================================================================
# SSRF (Server-Side Request Forgery): attacker tricks your server into making
# HTTP requests to internal services (AWS metadata API, Redis, internal APIs).
# Example: user submits https://169.254.169.254/latest/meta-data/
# Your server fetches it and returns AWS IAM credentials to the attacker.

# ── VULNERABLE: No URL validation ────────────────────────────────────────────

def fetch_url_VULNERABLE(user_supplied_url: str) -> str:
    """
    VULNERABLE: Fetches any URL provided by user.
    Attack vectors:
      - http://169.254.169.254/latest/meta-data/ (AWS EC2 metadata)
      - http://10.0.0.1/admin (internal network service)
      - file:///etc/passwd (local file read)
      - http://localhost:6379 (Redis)
    """
    import urllib.request
    response = urllib.request.urlopen(user_supplied_url)    # No validation!
    return response.read().decode()


# ── SECURE: Allowlist approach for SSRF ──────────────────────────────────────

# Define exactly which external hosts/prefixes your app legitimately needs to reach
SSRF_ALLOWED_HOSTS = {
    "api.github.com",
    "api.stripe.com",
    "hooks.slack.com",
}

# IP ranges that are ALWAYS blocked (private/link-local/loopback)
BLOCKED_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),        # RFC 1918 private
    ipaddress.ip_network("172.16.0.0/12"),      # RFC 1918 private
    ipaddress.ip_network("192.168.0.0/16"),     # RFC 1918 private
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local (AWS metadata)
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 private
]


def fetch_url_SECURE(user_supplied_url: str) -> str:
    """
    SECURE: Validate URL against an allowlist before fetching.
    Defense-in-depth approach:
      1. Parse URL and validate scheme
      2. Check hostname against allowlist
      3. Resolve hostname to IP and check against blocked ranges
    """
    import socket
    import urllib.request

    # Parse the URL to inspect components
    parsed = urllib.parse.urlparse(user_supplied_url)

    # 1. Only allow https — no file://, ftp://, gopher://, etc.
    if parsed.scheme not in ("https",):
        raise ValueError(f"URL scheme {parsed.scheme!r} is not allowed")

    # 2. Extract hostname (strip port and brackets for IPv6)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no valid hostname")

    # 3. Check against allowlist of known-good external hosts
    if hostname not in SSRF_ALLOWED_HOSTS:
        raise ValueError(f"Host {hostname!r} is not in the allowed list")

    # 4. Resolve hostname to IP and validate against blocked ranges
    try:
        # getaddrinfo returns list of (family, type, proto, canonname, sockaddr)
        addresses = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise ValueError(f"Cannot resolve hostname: {hostname}")

    for addr_info in addresses:
        ip_str = addr_info[4][0]    # Extract IP string from sockaddr tuple
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        for blocked_range in BLOCKED_IP_RANGES:
            if ip in blocked_range:
                raise ValueError(
                    f"Host {hostname!r} resolves to blocked IP {ip_str} "
                    f"(range: {blocked_range})"
                )

    # 5. Make the request with timeout and redirect limit
    import urllib.request
    response = urllib.request.urlopen(
        user_supplied_url,
        timeout=10    # Prevent hanging on slow/non-responsive internal hosts
    )
    return response.read().decode()


# =============================================================================
# A09: SECURITY LOGGING AND MONITORING FAILURES
# =============================================================================
# Failing to log security events means breaches go undetected for months.
# Logging PII/secrets is equally dangerous — log files become treasure maps.

# ── VULNERABLE: Logging PII ───────────────────────────────────────────────────

def process_payment_VULNERABLE(card_number: str, amount: float, user_email: str):
    """
    VULNERABLE: Logs sensitive data — card number and email in plaintext.
    Log files are often shipped to ElasticSearch, Datadog, Splunk with
    many people having read access. This violates PCI-DSS and GDPR.
    """
    logging.info(f"Processing payment: card={card_number}, email={user_email}, amount={amount}")
    # Also: logging full request bodies, passwords, tokens, SSNs, DOBs


# ── SECURE: Logging without PII ──────────────────────────────────────────────

def process_payment_SECURE(card_number: str, amount: float, user_email: str):
    """
    SECURE: Log what matters for debugging — without sensitive data.
    Use structured logging with a correlation ID, not interpolated strings.
    """
    # Mask card number: show only last 4 digits
    masked_card = f"****-****-****-{card_number[-4:]}" if len(card_number) >= 4 else "****"

    # Hash email for correlation without storing it (reversible with known email)
    email_hash = hashlib.sha256(user_email.encode()).hexdigest()[:12]  # Short prefix

    # Structured log — easy to parse, no PII
    logging.info(
        "payment_processed",
        extra={
            "card_suffix": card_number[-4:],   # Last 4 only — non-sensitive for support
            "amount": amount,
            "user_email_hash": email_hash,      # Correlation token, not plaintext email
            "status": "initiated",
        }
    )


# What SHOULD be logged for security monitoring:
SECURITY_EVENTS_TO_LOG = """
Log these security events (without sensitive data):
  - Authentication attempts (success and failure) + username hash + IP + user-agent
  - Authorization failures (user X tried to access resource Y)
  - Account lockouts
  - Password changes / 2FA changes
  - Admin actions (any CRUD by admin users)
  - Large data exports (pagination going past threshold)
  - Input validation failures (might indicate scanning/fuzzing)
  - Unusual geographic logins

Alert on:
  - N failed logins from same IP in T seconds
  - Login from new country for established user
  - High-value resource access at unusual hours
  - Bulk data access (scraping pattern)
"""


# =============================================================================
# A10: CSRF — CROSS-SITE REQUEST FORGERY
# =============================================================================
# CSRF: an attacker tricks a user's browser into making requests to your app
# on their behalf. Browser automatically includes cookies → attacker gets auth.
#
# Example: user is logged in to bank.com. Attacker hosts:
#   <img src="https://bank.com/transfer?to=attacker&amount=1000">
# Browser fetches the URL, session cookie is sent, transfer executes.
#
# Defenses: SameSite=Strict cookies (modern), CSRF tokens (legacy support).

# ── VULNERABLE: No CSRF protection ───────────────────────────────────────────

def transfer_money_VULNERABLE(to_account: str, amount: float, session_user_id: int):
    """
    VULNERABLE: Any cross-site request can trigger this.
    The browser sends the session cookie automatically — no origin check.
    """
    # db.transfer(from=session_user_id, to=to_account, amount=amount)
    return f"Transferred ${amount} to {to_account}"


# ── SECURE: SameSite cookie + CSRF token ─────────────────────────────────────

# Token storage for CSRF (in production: store in user's session)
_csrf_tokens: dict = {}   # user_id → csrf_token


def generate_csrf_token(user_id: int) -> str:
    """
    Generate a per-user, per-session CSRF token.
    Embed this in every state-changing form as a hidden field or custom header.
    """
    token = secrets.token_urlsafe(32)
    _csrf_tokens[user_id] = token     # Store server-side (in session)
    return token


def validate_csrf_token(user_id: int, submitted_token: str) -> bool:
    """
    Validate that the request includes the correct CSRF token.
    Use constant-time comparison to prevent timing attacks.
    """
    stored_token = _csrf_tokens.get(user_id)
    if not stored_token:
        return False    # No token exists for this user

    # Constant-time comparison — timing oracle prevention
    return hmac.compare_digest(
        stored_token.encode("utf-8"),
        submitted_token.encode("utf-8")
    )


def transfer_money_SECURE(
    to_account: str,
    amount: float,
    session_user_id: int,
    csrf_token: str,           # Submitted via form hidden field or X-CSRF-Token header
):
    """
    SECURE: Validates CSRF token before executing state change.
    Combined with SameSite=Strict cookies, this provides defense-in-depth.

    Cookie configuration (set at login):
      Set-Cookie: session_id=...; HttpOnly; Secure; SameSite=Strict
      SameSite=Strict: browser NEVER sends cookie on cross-site requests → no CSRF.
      SameSite=Lax: sent on top-level navigations only (safe for most cases).
      SameSite=None: disables protection (must have Secure flag).

    For legacy browser support (no SameSite): also use CSRF tokens.
    For APIs (no cookies, using Authorization header): CSRF is N/A.
    """
    if not validate_csrf_token(session_user_id, csrf_token):
        raise PermissionError("Invalid or missing CSRF token")

    # db.transfer(from=session_user_id, to=to_account, amount=amount)
    return f"Transferred ${amount} to {to_account}"


# =============================================================================
# SUMMARY TABLE
# =============================================================================

OWASP_TOP10_SUMMARY = """
OWASP Top 10 (2021) — Quick Reference

A01 Broken Access Control   → Always check ownership in DB query. Default deny.
A02 Cryptographic Failures  → bcrypt/argon2id for passwords. AES-GCM for data.
A03 Injection               → Parameterized queries. subprocess as list, not string.
A04 Insecure Design         → Rate limit sensitive endpoints. Model threats early.
A05 Security Misconfig      → DEBUG=False. Random secret keys. Generic error pages.
A06 Vulnerable Components   → pip-audit in CI. Pin + lock dependencies.
A07 Auth Failures           → Lockout after N failures. Hash passwords. MFA.
A08 SSRF                    → Allow-list external hosts. Block RFC1918 IP ranges.
A09 Logging Failures        → Log security events. Mask PII. Alert on anomalies.
A10 CSRF                    → SameSite=Strict cookies. CSRF tokens for legacy.

Universal rule: Never trust user input. Validate, escape, or deny by default.
"""


# =============================================================================
# DEMONSTRATION RUNNER
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("L04 — OWASP Top 10 Demo")
    print("=" * 60)

    print("\n--- A01: Broken Access Control ---")
    print(get_order_VULNERABLE(1234, requesting_user_id=99))

    print("\n--- A02: Cryptographic Failures ---")
    bad_hash = store_password_VULNERABLE("password123")
    print(f"MD5 (bad): {bad_hash}")
    good_hash = store_password_SECURE("password123")
    print(f"bcrypt (good): {good_hash[:30]}...")

    print("\n--- A03: Injection ---")
    malicious = "'; DROP TABLE users;--"
    vuln_query = f"SELECT * FROM users WHERE username = '{malicious}'"
    safe_query = ("SELECT * FROM users WHERE username = ?", (malicious,))
    print(f"VULNERABLE query: {vuln_query}")
    print(f"SAFE query: {safe_query[0]} params={safe_query[1]}")

    print("\n--- A04: Insecure Design (rate limiting) ---")
    for i in range(5):
        result = send_password_reset_SECURE("user@example.com")
        print(f"  Attempt {i+1}: {result}")

    print("\n--- A05: Security Misconfiguration ---")
    print(f"Vulnerable config DEBUG: {FLASK_CONFIG_VULNERABLE['DEBUG']}")
    print(f"Secure config SECRET_KEY set: {bool(FLASK_CONFIG_SECURE['SECRET_KEY'])}")

    print("\n--- A08: SSRF Validation ---")
    try:
        fetch_url_SECURE("http://169.254.169.254/latest/meta-data/")
    except ValueError as e:
        print(f"BLOCKED: {e}")

    print("\n--- A09: Logging ---")
    process_payment_SECURE("4111111111111234", 99.99, "alice@example.com")

    print("\n--- A10: CSRF Token ---")
    token = generate_csrf_token(user_id=42)
    print(f"CSRF token: {token[:20]}...")
    print(f"Valid: {validate_csrf_token(42, token)}")
    print(f"Tampered: {validate_csrf_token(42, 'badtoken')}")

    print("\n--- OWASP Summary ---")
    print(OWASP_TOP10_SUMMARY)
