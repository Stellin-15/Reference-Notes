# ============================================================
# L05: Network Engineering Fundamentals for DevOps/SRE
# ============================================================
# WHAT: The practical networking knowledge a DevOps/SRE engineer needs
#       day to day — DNS resolution and troubleshooting, load balancer
#       types and algorithms, reverse proxies, firewalls/security
#       groups, and VPN/private connectivity concepts.
# WHY: A huge fraction of "is it down" incidents are ACTUALLY networking
#      problems (DNS misconfiguration, a security group rule blocking
#      traffic, a load balancer health check failing) — this is the
#      diagnostic toolkit for that entire failure class, distinct from
#      application-level debugging.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
DNS RESOLUTION is frequently the FIRST thing to check when "the service
is unreachable" — a DNS record pointing at a stale/wrong IP, a TTL
that's too long (causing clients to cache a now-wrong answer for hours
after a change), or DNS propagation delay after a change are all common,
purely-DNS root causes that look identical to "the service itself is
down" from a user's perspective. `dig`/`nslookup` are the standard
diagnostic tools for inspecting exactly what DNS is currently resolving
to, and from which resolver.

A LOAD BALANCER distributes incoming traffic across multiple backend
instances — L4 (transport layer, e.g. AWS NLB) balances based on
IP/port information without inspecting application content, offering
lower latency/overhead; L7 (application layer, e.g. AWS ALB, nginx)
inspects HTTP-level details (path, headers, cookies) enabling
content-based routing (e.g. `/api/*` to one backend pool, `/static/*` to
another) at the cost of more processing per request. HEALTH CHECKS are
what let a load balancer automatically stop routing traffic to an
unhealthy backend instance — a MISCONFIGURED health check (checking the
wrong endpoint, too aggressive a failure threshold) is a common,
subtle cause of intermittent errors that look like application bugs but
are actually the load balancer routing traffic to instances it
shouldn't be.

A REVERSE PROXY (nginx, HAProxy) sits in front of one or more backend
services, forwarding client requests to them — often combining load
balancing with additional responsibilities: TLS TERMINATION (decrypting
HTTPS at the proxy, so backend services handle only plain HTTP
internally, simplifying certificate management to one place), request/
response header manipulation, and caching.

FIREWALLS and CLOUD SECURITY GROUPS control what traffic is
ALLOWED to reach a host/service at all — a security group misconfiguration
(a rule that's too restrictive, blocking legitimate traffic; or one
that's too permissive, exposing something that shouldn't be reachable)
is a frequent, purely-network-layer cause of both "can't connect" incidents
and security exposures. Security groups are typically STATEFUL (an
allowed outbound connection's return traffic is automatically allowed
back in, without needing an explicit inbound rule) — a distinction from
older, stateless firewall/ACL models worth understanding explicitly.

VPNs and PRIVATE CONNECTIVITY (VPC peering, AWS PrivateLink, a site-to-
site VPN) let systems communicate over PRIVATE network paths instead of
the public internet — relevant for both security (sensitive traffic
never traverses the public internet) and sometimes cost/performance
(private connectivity is often faster and cheaper than routing through
public internet gateways).

PRODUCTION USE CASE:
A service reports intermittent 502 errors from its load balancer —
investigation reveals the load balancer's health check is hitting a
`/health` endpoint that itself depends on a slow downstream database
call, occasionally timing out under load and causing the load balancer
to mark HEALTHY instances as unhealthy and stop routing to them
temporarily — a health-check DESIGN problem (the health check should be
a lightweight, fast check, not one that can fail due to unrelated
downstream slowness), diagnosable specifically by understanding how
load balancer health checks actually work.

COMMON MISTAKES:
- Debugging "the site is down" purely at the application layer without
  first checking DNS resolution (`dig`) and basic connectivity
  (`curl -v`, `telnet host port`) — a meaningful fraction of "outages"
  are actually DNS or network-layer issues that never reach the application at all.
- Designing a load balancer health check that depends on SLOW or
  UNRELATED downstream systems — a health check should verify "can this
  instance serve traffic RIGHT NOW," not exercise the entire dependency
  chain, which conflates "this instance is unhealthy" with "a downstream
  system is slow," two genuinely different problems needing different responses.
- Writing overly permissive security group rules ("allow all traffic
  from anywhere") as a quick fix to unblock connectivity during
  debugging, and never tightening them afterward — this is a genuine,
  common security exposure that accumulates exactly the way configuration
  drift (L01) does, if not deliberately reviewed and cleaned up.
"""

import textwrap


# ------------------------------------------------------------------
# 1. DNS diagnostics
# ------------------------------------------------------------------
DNS_DIAGNOSTIC_COMMANDS = textwrap.dedent("""\
    dig example.com                  # what does DNS currently resolve to
    dig example.com +short            # just the IP, no verbose output
    dig example.com @8.8.8.8           # query a SPECIFIC resolver directly
                                         # (bypassing local/cached resolvers)
                                         # — useful for checking if a change
                                         # has propagated globally yet
    dig -x 10.0.1.5                     # REVERSE lookup — IP to hostname

    nslookup example.com                # an older, still-common alternative to dig

    # Checking TTL — a long TTL means clients cache the OLD answer for a
    # long time after you change a record, which is why "I updated DNS
    # but it's still resolving to the old IP" is a common, TTL-caused,
    # NOT-actually-broken symptom.
    dig example.com | grep -A1 "ANSWER SECTION"
""")

# ------------------------------------------------------------------
# 2. Load balancers — L4 vs L7, and health check design
# ------------------------------------------------------------------
LB_TYPE_COMPARISON = {
    "L4 (Network Load Balancer)": "Balances based on IP/port only, no "
        "content inspection — lower latency/overhead, cannot do "
        "content-based routing (e.g. path-based routing).",
    "L7 (Application Load Balancer)": "Inspects HTTP-level details "
        "(path, headers, host) — enables content-based routing, at the "
        "cost of more per-request processing overhead.",
}

HEALTH_CHECK_DESIGN_EXAMPLE = textwrap.dedent("""\
    # BAD health check endpoint — depends on a SLOW, UNRELATED downstream
    # system, conflating "can I serve traffic" with "is my database slow"
    @app.get("/health")
    def bad_health_check():
        db.execute("SELECT COUNT(*) FROM large_table")   # can be slow under load
        return {"status": "ok"}

    # GOOD health check — a LIGHTWEIGHT, fast check of whether THIS
    # instance can serve traffic right now, independent of downstream
    # system performance (a SEPARATE, deeper "readiness" check can exist
    # for genuinely verifying dependencies, but shouldn't be what a load
    # balancer's rapid, frequent health check depends on).
    @app.get("/health")
    def good_health_check():
        return {"status": "ok"}   # no downstream calls — just "is this
                                    # process alive and responsive"
""")

# ------------------------------------------------------------------
# 3. Reverse proxies — TLS termination
# ------------------------------------------------------------------
REVERSE_PROXY_CONFIG_EXAMPLE = textwrap.dedent("""\
    # nginx as a reverse proxy with TLS termination — HTTPS is decrypted
    # HERE, and backend services only ever see plain HTTP internally,
    # centralizing certificate management to ONE place instead of every
    # backend service needing its own TLS setup.
    server {
        listen 443 ssl;
        server_name api.example.com;

        ssl_certificate     /etc/nginx/certs/api.example.com.crt;
        ssl_certificate_key /etc/nginx/certs/api.example.com.key;

        location / {
            proxy_pass http://backend_pool;   # plain HTTP to the backend
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;   # tells the
                                # backend the ORIGINAL request was HTTPS,
                                # even though this internal hop is plain HTTP
        }
    }

    upstream backend_pool {
        server 10.0.1.10:8080;
        server 10.0.1.11:8080;
    }
""")

# ------------------------------------------------------------------
# 4. Firewalls / security groups — stateful rules
# ------------------------------------------------------------------
SECURITY_GROUP_EXAMPLE = textwrap.dedent("""\
    # AWS security group rules (conceptual) — STATEFUL: an outbound
    # connection's RETURN traffic is automatically allowed back in,
    # without needing a matching explicit INBOUND rule for it.

    Inbound rules:
      - Allow TCP 443 from 0.0.0.0/0        (public HTTPS access)
      - Allow TCP 22 from 10.0.0.0/8 ONLY    (SSH restricted to internal network)
      - Allow TCP 5432 from sg-app-servers   (Postgres — ONLY from the app tier's own security group)

    Outbound rules:
      - Allow all traffic to 0.0.0.0/0       (a common, often-too-permissive default)

    # A common real mistake: leaving an overly broad rule (e.g. SSH from
    # 0.0.0.0/0) in place after a debugging session "just to unblock
    # something temporarily," and never tightening it back — an easy,
    # common cause of unnecessary exposure.
""")

# ------------------------------------------------------------------
# 5. Private connectivity
# ------------------------------------------------------------------
PRIVATE_CONNECTIVITY_OPTIONS = {
    "VPC Peering": "Direct, private network connection between two VPCs "
        "— traffic never traverses the public internet.",
    "AWS PrivateLink": "Exposes a SPECIFIC service privately across "
        "VPCs/accounts without full network peering — narrower, more "
        "controlled exposure than full VPC peering.",
    "Site-to-Site VPN": "Encrypted tunnel between an on-prem network and "
        "a cloud VPC — common for hybrid infrastructure bridging "
        "on-prem and cloud resources.",
}


if __name__ == "__main__":
    print(DNS_DIAGNOSTIC_COMMANDS)
    print("=== Load balancer types ===")
    for lb_type, note in LB_TYPE_COMPARISON.items():
        print(f"{lb_type}: {note}\n")
    print(HEALTH_CHECK_DESIGN_EXAMPLE)
    print(REVERSE_PROXY_CONFIG_EXAMPLE)
    print(SECURITY_GROUP_EXAMPLE)
    print("=== Private connectivity options ===")
    for option, note in PRIVATE_CONNECTIVITY_OPTIONS.items():
        print(f"{option}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
An on-call engineer investigating "customers report the API is
unreachable" runs `dig api.example.com` FIRST (confirming DNS resolves
correctly), then `curl -v https://api.example.com/health` (confirming a
TLS handshake and HTTP response actually succeed) BEFORE looking at any
application logs — this two-command network-layer check takes under a
minute and immediately rules out (or confirms) an entire class of DNS/
network/TLS root causes, avoiding wasted time investigating application
code for a problem that turns out to be a stale DNS record from a
recent infrastructure change.
"""
