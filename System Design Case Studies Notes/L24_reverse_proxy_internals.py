# ============================================================
# L24: Reverse Proxy Internals — What a Reverse Proxy Actually Does
# ============================================================
# WHAT: The concrete responsibilities a reverse proxy handles beyond
#       simple load balancing — request/response transformation, header
#       manipulation, caching, and how it differs from a FORWARD proxy
#       (a genuinely common point of confusion).
# WHY: L21-L23 covered load balancing decisions in the abstract. A
#      REVERSE PROXY is the concrete piece of software that typically
#      IMPLEMENTS those decisions in production (alongside several
#      other responsibilities this lesson covers).
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
A REVERSE PROXY sits IN FRONT OF one or more backend servers, receiving
requests on the SERVERS' behalf and forwarding them to an appropriate
backend — from the CLIENT's perspective, they're talking to the reverse
proxy itself; they have no direct visibility into which actual backend
server handled their request. This is the OPPOSITE of a FORWARD PROXY,
which sits in front of CLIENTS, forwarding their requests to the wider
internet on THEIR behalf (e.g. a corporate network's outbound proxy) —
a genuinely common point of confusion, since both are "proxies" but
serve opposite roles and opposite audiences (protecting/managing
servers vs protecting/managing clients).

BEYOND LOAD BALANCING (L21-L23), a reverse proxy commonly handles
several OTHER responsibilities in one place: REQUEST/RESPONSE HEADER
MANIPULATION (adding `X-Forwarded-For` to preserve the original client
IP, which backends behind the proxy would otherwise only ever see as the
proxy's own IP; stripping internal/sensitive headers before forwarding
externally); SSL/TLS TERMINATION (L26 covers this in depth — decrypting
HTTPS traffic once at the proxy rather than requiring every backend
instance to handle TLS individually); RESPONSE CACHING (caching
frequently-requested, cacheable responses at the proxy layer itself,
serving them without ever forwarding the request to a backend at all);
and REQUEST BUFFERING/RESPONSE BUFFERING (absorbing a slow client's
upload or a slow backend's response so slow, individual connections
don't tie up backend server resources for longer than necessary).

URL REWRITING/PATH MANIPULATION lets a reverse proxy present a DIFFERENT
URL structure externally than what backends actually expose internally
— e.g. external requests to `/api/v2/orders` might be rewritten to
`/orders` before reaching an internal orders service that has no
knowledge of the external API's versioning scheme at all — this
DECOUPLES the external API contract from internal service implementation
details, letting internal services be restructured without breaking
external consumers, as long as the reverse proxy's rewrite rules are
updated accordingly.

WHY A SEPARATE LAYER (rather than each backend application handling all
of this itself): centralizing these cross-cutting concerns (TLS, header
manipulation, caching, load-balancing) in ONE place means individual
backend applications can focus purely on their own business logic,
and operational changes (rotating a TLS certificate, adjusting cache
rules, changing load-balancing algorithm) can be made in ONE place
without redeploying every backend service — a genuine separation-of-concerns benefit.

PRODUCTION USE CASE:
An API gateway (this repo's API Design Notes covers gateway patterns
generally) implemented as a reverse proxy terminates TLS for all
incoming HTTPS traffic, adds an `X-Forwarded-For` header preserving each
client's real IP for backend logging/rate-limiting purposes, rewrites
external `/v2/*` paths to the internal service paths those backends
actually expose, and caches responses for a `/api/popular-products`
endpoint for 60 seconds — all before any request ever reaches an actual
backend application server, which remains entirely unaware any of this happened.

COMMON MISTAKES:
- Confusing forward and reverse proxies conceptually — asking "does this
  proxy protect the client or the server" is the fastest way to
  disambiguate; a reverse proxy protects/manages SERVERS from the
  client's perspective, a forward proxy protects/manages CLIENTS from
  the server's/internet's perspective.
- Forgetting to preserve the original client IP (via `X-Forwarded-For`
  or similar) when a reverse proxy sits in front of backends — without
  this, every backend-side log entry, rate limiter, or geo-based feature
  incorrectly sees every request as originating from the proxy's own IP
  address, breaking any IP-based logic entirely.
- Implementing TLS termination, caching, and load balancing SEPARATELY,
  each as its own layer/hop, when a single reverse proxy tier could
  handle all of them together — this adds unnecessary network hops and
  operational complexity compared to consolidating these cross-cutting
  concerns into one well-configured layer.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Forward proxy vs reverse proxy — the core distinction
# ------------------------------------------------------------------
PROXY_DIRECTION_DIAGRAM = textwrap.dedent("""\
    FORWARD PROXY (protects/manages CLIENTS):

        [Client A] -\\
        [Client B] --> [Forward Proxy] --> [The wider internet]
        [Client C] -/

        The internet sees only the PROXY's identity, not individual
        clients. Clients are typically UNAWARE of exactly which server
        they end up talking to on the other end.

    REVERSE PROXY (protects/manages SERVERS):

        [The wider internet] --> [Reverse Proxy] --\\
                                                       --> [Backend 1]
                                                       --> [Backend 2]
                                                       --> [Backend 3]

        Clients see only the PROXY's identity, not individual backend
        servers. Backends are typically UNAWARE of exactly which
        external client they're serving without help (X-Forwarded-For).
""")

# ------------------------------------------------------------------
# 2. Header manipulation — preserving client identity
# ------------------------------------------------------------------
def simulate_reverse_proxy_request(client_ip: str, original_headers: dict) -> dict:
    forwarded_headers = dict(original_headers)
    # Without this, the backend would only ever see the PROXY's own IP
    # as the apparent request source — breaking IP-based rate limiting,
    # geo features, and audit logging on the backend side
    forwarded_headers["X-Forwarded-For"] = client_ip
    forwarded_headers["X-Forwarded-Proto"] = "https"   # informs backend the ORIGINAL request was HTTPS
    return forwarded_headers


def header_manipulation_demo():
    original_headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    forwarded = simulate_reverse_proxy_request("203.0.113.42", original_headers)
    print("Headers as forwarded to the backend:")
    for key, value in forwarded.items():
        print(f"  {key}: {value}")
    print("  -> Without X-Forwarded-For, the backend would see the PROXY's")
    print("     IP as the request source for every single client.")


# ------------------------------------------------------------------
# 3. URL rewriting — decoupling external and internal paths
# ------------------------------------------------------------------
def rewrite_path(external_path: str, rewrite_rules: dict[str, str]) -> str:
    for external_prefix, internal_prefix in rewrite_rules.items():
        if external_path.startswith(external_prefix):
            return external_path.replace(external_prefix, internal_prefix, 1)
    return external_path


def url_rewriting_demo():
    rules = {
        "/api/v2/orders": "/internal/orders-service",
        "/api/v2/users": "/internal/users-service",
    }
    external_requests = ["/api/v2/orders/12345", "/api/v2/users/me", "/health"]
    print("\nURL rewriting (external path -> internal backend path):")
    for path in external_requests:
        rewritten = rewrite_path(path, rules)
        print(f"  {path} -> {rewritten}")
    print("  -> External API consumers never see or depend on internal")
    print("     service naming/structure, which can change independently.")


if __name__ == "__main__":
    print(PROXY_DIRECTION_DIAGRAM)
    header_manipulation_demo()
    url_rewriting_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A company's public API is served through a reverse proxy that terminates
TLS, rewrites externally-versioned paths (`/api/v2/*`) to whatever
internal service names/paths actually exist THIS MONTH, adds
`X-Forwarded-For` so backend rate-limiting correctly tracks individual
external clients rather than the proxy's own IP, and caches a handful of
genuinely cacheable, high-traffic endpoints — when the internal team
later restructures which microservice owns the "orders" domain, they
update the proxy's rewrite rules in ONE place, with zero impact on
external API consumers who never see or depend on that internal detail at all.
"""
