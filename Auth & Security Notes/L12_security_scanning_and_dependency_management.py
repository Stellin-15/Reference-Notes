# ============================================================
# L12: Security Scanning and Dependency Management — Bandit, Dependabot,
#      Remediating XSS/SSRF/LFI
# ============================================================
# WHAT: Automated Python static application security testing (Bandit),
#       automated dependency vulnerability scanning (Dependabot and the
#       broader SCA — Software Composition Analysis — category), and
#       concrete remediation patterns for XSS, SSRF, and LFI — the
#       specific TOOLING that turns L04's OWASP Top 10 knowledge into
#       an automated, continuous CI/CD gate.
# WHY: L04 covered the OWASP Top 10 conceptually, with vulnerable-code-
#       then-fixed-code examples. This lesson covers the TOOLS that
#       catch these vulnerability classes AUTOMATICALLY, continuously,
#       on every commit — turning security review from a manual,
#       easy-to-skip step into an enforced, automated gate.
# LEVEL: Intermediate/Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
BANDIT is a Python-specific STATIC APPLICATION SECURITY TESTING (SAST)
tool — it scans your Python SOURCE CODE (without running it) for known
insecure patterns: use of `eval()`/`exec()` on untrusted input, hardcoded
passwords/secrets, use of insecure hash functions (MD5/SHA1 for security
purposes), SQL query construction via string formatting (a SQL injection
risk), and use of `subprocess` with `shell=True` (a command injection
risk). Running Bandit as a CI gate (failing the build on high-severity
findings) catches these patterns BEFORE code merges, rather than relying
on a human reviewer noticing them during code review.

DEPENDABOT (and the broader SCA — Software Composition Analysis —
category, which also includes tools like Snyk and Safety) scans your
DEPENDENCIES (third-party libraries your code imports) against known
vulnerability databases (the National Vulnerability Database, GitHub's
own advisory database) and automatically opens pull requests to upgrade
a vulnerable dependency to a patched version. This matters because a
huge fraction of real-world vulnerabilities come from OUTDATED
DEPENDENCIES, not code YOU wrote — Bandit scans your own code; SCA tools
scan the code you're PULLING IN from others.

XSS (Cross-Site Scripting) REMEDIATION, concretely: the fix is
CONTEXT-AWARE OUTPUT ENCODING — escaping user-controlled data based on
WHERE it's being inserted (HTML body, HTML attribute, JavaScript
context, URL) — using a templating engine's AUTO-ESCAPING feature
(Jinja2, Django templates) rather than manually concatenating strings
into HTML, which is exactly how XSS vulnerabilities get introduced in
the first place.

SSRF (Server-Side Request Forgery) REMEDIATION, concretely: validate
that any URL your SERVER fetches on behalf of a user request is NOT
pointing at internal/private network ranges (169.254.x.x for cloud
metadata endpoints, 10.x/172.16.x/192.168.x for private networks,
localhost/127.0.0.1) — an ALLOW-LIST of permitted destination hosts is
more robust than a DENY-LIST of blocked ones, since deny-lists are
easy to bypass with encoding tricks or DNS rebinding.

LFI (Local File Inclusion) REMEDIATION, concretely: NEVER construct a
filesystem path directly from user input without validation — resolve
the requested path to its ABSOLUTE, canonical form (`os.path.realpath`)
and verify it's still WITHIN an expected, allowed base directory before
opening it (directly the same sandboxing pattern covered in this repo's
Agentic AI & RAG Notes L22 for AI agent filesystem tools — LFI is the
classic, pre-AI version of that exact vulnerability class).

PRODUCTION USE CASE:
A CI pipeline runs Bandit on every pull request (failing the build on
high/medium severity findings), Dependabot continuously monitors all
dependencies and auto-opens PRs for vulnerable package upgrades, and a
manual security review focuses on business logic and architecture
concerns Bandit/Dependabot structurally cannot catch (they check for
known PATTERNS, not novel logic flaws) — this layered approach catches
the well-understood vulnerability classes automatically, freeing human
review time for the genuinely novel risks specific to this application.

COMMON MISTAKES:
- Running Bandit/Dependabot but not actually GATING the CI pipeline on
  their findings (e.g. running them as informational-only, never
  failing a build) — this provides visibility without actually
  preventing vulnerable code/dependencies from merging, undermining the
  entire point of automated scanning.
- Using a DENY-LIST approach for SSRF prevention (block known-bad hosts)
  instead of an ALLOW-LIST (only permit known-good hosts) — deny-lists
  are systematically easier to bypass via encoding, redirects, or DNS
  tricks than an allow-list that simply never considers unlisted
  destinations valid in the first place.
- Treating Bandit's findings as automatically correct without triage —
  SAST tools produce real FALSE POSITIVES (e.g. flagging `subprocess`
  usage that's actually safe because the input is fully controlled, not
  user-supplied); a mature process reviews and explicitly suppresses
  confirmed false positives (with a documented reason) rather than
  either blindly trusting or blindly ignoring every finding.
"""

import os
import textwrap


# ------------------------------------------------------------------
# 1. Bandit — Python SAST
# ------------------------------------------------------------------
BANDIT_CI_EXAMPLE = textwrap.dedent("""\
    # .github/workflows/security.yml
    - name: Run Bandit
      run: |
        pip install bandit
        bandit -r ./src -ll -f json -o bandit-report.json
        # -ll: only report MEDIUM and higher severity findings
        # A non-zero exit code (findings present) FAILS the CI job,
        # actually gating the merge, not just reporting.
""")

BANDIT_FINDINGS_EXAMPLE = textwrap.dedent("""\
    # VULNERABLE — Bandit flags this as B602 (subprocess with shell=True)
    import subprocess
    def run_backup(filename):
        subprocess.run(f"tar -czf backup.tar.gz {filename}", shell=True)
        # If `filename` is user-controlled, this is a COMMAND INJECTION
        # vulnerability: filename = "; rm -rf / #" would be catastrophic.

    # FIXED — no shell=True, arguments passed as a list (no shell parsing at all)
    def run_backup_fixed(filename):
        subprocess.run(["tar", "-czf", "backup.tar.gz", filename], shell=False)

    # VULNERABLE — Bandit flags B303 (insecure hash for security purposes)
    import hashlib
    def hash_password(password):
        return hashlib.md5(password.encode()).hexdigest()   # MD5 is broken for this use

    # FIXED — use a purpose-built password hashing algorithm (this repo's
    # Auth & Security Notes L01 covers bcrypt/argon2id in depth)
    from passlib.hash import argon2
    def hash_password_fixed(password):
        return argon2.hash(password)
""")

# ------------------------------------------------------------------
# 2. Dependabot / SCA — dependency vulnerability scanning
# ------------------------------------------------------------------
DEPENDABOT_CONFIG_EXAMPLE = textwrap.dedent("""\
    # .github/dependabot.yml
    version: 2
    updates:
      - package-ecosystem: "pip"
        directory: "/"
        schedule:
          interval: "daily"
        open-pull-requests-limit: 10
        # Dependabot automatically opens a PR bumping a vulnerable
        # dependency to its patched version, with the CVE details in
        # the PR description — reviewed and merged like any other PR,
        # but the DISCOVERY of the vulnerability is fully automated.

    # pip-audit is a lighter-weight, CLI-based alternative for local/CI checks:
    #   pip install pip-audit && pip-audit
    # Scans installed packages against the Python Packaging Advisory
    # Database, reporting known CVEs affecting your exact dependency versions.
""")

# ------------------------------------------------------------------
# 3. XSS remediation — context-aware auto-escaping
# ------------------------------------------------------------------
XSS_REMEDIATION_EXAMPLE = textwrap.dedent("""\
    # VULNERABLE — manual string concatenation into HTML, no escaping
    def render_comment_unsafe(comment_text):
        return f"<div class='comment'>{comment_text}</div>"
        # comment_text = "<script>steal_cookies()</script>" executes in
        # every viewer's browser — classic stored XSS.

    # FIXED — Jinja2's auto-escaping (enabled by default for .html templates)
    from jinja2 import Environment, select_autoescape
    env = Environment(autoescape=select_autoescape(["html"]))
    template = env.from_string("<div class='comment'>{{ comment_text }}</div>")
    safe_output = template.render(comment_text="<script>steal_cookies()</script>")
    # Jinja2 automatically HTML-entity-encodes the input — the script
    # tag renders as inert TEXT, not executable markup.
""")

# ------------------------------------------------------------------
# 4. SSRF remediation — allow-list, not deny-list
# ------------------------------------------------------------------
import ipaddress
from urllib.parse import urlparse

ALLOWED_FETCH_HOSTS = {"api.trusted-partner.com", "cdn.internal-assets.com"}

PRIVATE_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),   # cloud metadata endpoint range
    ipaddress.ip_network("127.0.0.0/8"),
]


def is_safe_fetch_url(url: str) -> bool:
    """ALLOW-LIST approach: only explicitly-approved hosts are fetchable
    at all — an unlisted host is rejected by default, closing off SSRF
    attempts against internal services/cloud metadata endpoints without
    needing to enumerate every possible malicious destination."""
    parsed = urlparse(url)
    if parsed.hostname not in ALLOWED_FETCH_HOSTS:
        return False
    return True


def demonstrate_ssrf_prevention():
    test_urls = [
        "https://api.trusted-partner.com/data",
        "http://169.254.169.254/latest/meta-data/",   # AWS metadata endpoint — a classic SSRF target
        "http://internal-admin-panel.local/",
    ]
    for url in test_urls:
        print(f"  {url}: {'ALLOWED' if is_safe_fetch_url(url) else 'BLOCKED'}")


# ------------------------------------------------------------------
# 5. LFI remediation — canonical path resolution within an allowed base
# ------------------------------------------------------------------
ALLOWED_UPLOAD_DIR = "/var/app/uploads"


def safe_read_uploaded_file(requested_filename: str) -> str:
    """Resolves the requested path to its ABSOLUTE, canonical form and
    verifies it's still WITHIN the allowed base directory — the same
    sandboxing pattern this repo's Agentic AI & RAG Notes L22 applies to
    AI agent filesystem tools, here applied to a classic web-app LFI
    vulnerability."""
    full_path = os.path.realpath(os.path.join(ALLOWED_UPLOAD_DIR, requested_filename))
    if not full_path.startswith(os.path.realpath(ALLOWED_UPLOAD_DIR)):
        raise PermissionError(f"Access outside {ALLOWED_UPLOAD_DIR} denied: {requested_filename}")
    return full_path   # a real implementation would then open() this validated path


def demonstrate_lfi_prevention():
    test_inputs = ["report.pdf", "../../etc/passwd", "subdir/../../secrets.env"]
    for filename in test_inputs:
        try:
            path = safe_read_uploaded_file(filename)
            print(f"  '{filename}' -> ALLOWED: {path}")
        except PermissionError as e:
            print(f"  '{filename}' -> BLOCKED: {e}")


if __name__ == "__main__":
    print(BANDIT_CI_EXAMPLE)
    print(BANDIT_FINDINGS_EXAMPLE)
    print(DEPENDABOT_CONFIG_EXAMPLE)
    print(XSS_REMEDIATION_EXAMPLE)

    print("--- SSRF prevention demo ---")
    demonstrate_ssrf_prevention()

    print("\n--- LFI prevention demo ---")
    demonstrate_lfi_prevention()

"""
PRODUCTION CONTEXT EXAMPLE:
A platform hardening initiative across 6 products runs Bandit and
Dependabot as mandatory CI gates on every repository, remediates a
discovered SSRF vulnerability in a webhook-fetching feature by replacing
its deny-list host check with an explicit allow-list, and fixes an LFI
vulnerability in a document-download endpoint by adding canonical-path
validation against an allowed base directory — reaching a state of zero
outstanding critical vulnerabilities across all 6 products, verified
continuously by the same automated tooling rather than a point-in-time
manual audit that would drift out of date as new code and dependencies
are added.
"""
