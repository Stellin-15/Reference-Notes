# ============================================================
# L21: Load Balancing Fundamentals — Layer 4 vs Layer 7
# ============================================================
# WHAT: The foundational distinction in load balancer design — Layer 4
#       (transport-layer, TCP/UDP-level) vs Layer 7 (application-layer,
#       HTTP-aware) load balancing — and the real tradeoffs between them.
# WHY: This starts the infrastructure-building-blocks track referenced
#      throughout this domain's earlier case studies (SFU/TURN selection
#      in L05, server selection generally). Understanding load balancing
#      at the RIGHT layer is foundational to nearly every distributed
#      system, not specific to any one of the earlier case studies.
# LEVEL: Foundation (of this infra track)
# ============================================================

"""
CONCEPT OVERVIEW:
The OSI model's LAYER 4 (Transport Layer, TCP/UDP) and LAYER 7
(Application Layer, HTTP/gRPC/etc.) each offer a fundamentally different
level of VISIBILITY into the traffic being load-balanced, which directly
determines what routing decisions are possible.

L4 LOAD BALANCING operates purely on IP addresses and TCP/UDP port
numbers — it does NOT parse or understand the actual application data
inside the connection at all. This makes it EXTREMELY FAST (minimal
per-packet processing overhead) and PROTOCOL-AGNOSTIC (works identically
for HTTP, database connections, custom TCP protocols, anything) — but it
can only route based on connection-level information: which backend
server should THIS ENTIRE TCP CONNECTION go to, decided once at
connection-establishment time, with no ability to make DIFFERENT
routing decisions for different requests WITHIN that same connection.

L7 LOAD BALANCING operates by actually PARSING the application-layer
protocol (typically HTTP) — this unlocks routing decisions based on
REQUEST CONTENT: the URL path (`/api/v1/*` to one backend pool, `/static/*`
to another), HTTP headers (route based on a custom header, or route
mobile vs desktop user-agents differently), or cookies (session
affinity/sticky sessions). Critically, an L7 load balancer can make a
DIFFERENT routing decision for EACH individual HTTP request, even
multiple requests over the SAME underlying persistent connection (HTTP
keep-alive/HTTP2 multiplexing) — something L4 fundamentally cannot do,
since it never looks inside the connection's data at all. This
capability comes at the cost of MORE PER-REQUEST PROCESSING overhead
(parsing HTTP headers, TLS termination — L26 — is also commonly done
here) than L4's much simpler packet forwarding.

CHOOSING BETWEEN THEM: L4 is the right choice when you need MAXIMUM
throughput/minimum latency and don't need content-aware routing (e.g.
balancing raw database connections, or a non-HTTP TCP protocol); L7 is
necessary whenever routing decisions need to depend on the REQUEST
ITSELF (path-based microservice routing, A/B testing via headers,
canary releases routing a percentage of traffic based on request
attributes). Many REAL production architectures use BOTH in combination
— an L4 load balancer distributing traffic across MULTIPLE L7 load
balancer instances (which then make the content-aware routing decisions),
gaining L4's raw throughput at the outer layer with L7's routing
intelligence at the inner layer.

PRODUCTION USE CASE:
An API platform uses an L4 load balancer at the network edge to
distribute raw TCP connections across a pool of L7 load balancer/reverse
proxy instances (L24) purely for RAW THROUGHPUT and DDoS-absorption
capacity — each of those L7 instances then inspects the actual HTTP
request path and routes `/api/orders/*` to the orders microservice pool
and `/api/users/*` to the users microservice pool, a routing decision
the outer L4 layer is structurally incapable of making.

COMMON MISTAKES:
- Using an L7 load balancer for a workload with NO content-aware routing
  need (e.g. balancing raw database connections) — this adds unnecessary
  per-connection processing overhead for a capability (HTTP-aware
  routing) that will never actually be used.
- Assuming L4 load balancing can implement path-based routing — this is
  a category error; L4 genuinely cannot see inside the connection's data
  at all, so ANY requirement involving "route based on what the request
  actually contains" mandates L7 (or a combination, as described above).
- Not considering that L7 processing (HTTP parsing, often TLS
  termination) adds real CPU cost per request — at very high request
  volumes, this can become a genuine capacity-planning consideration
  distinct from, and in addition to, the backend application servers' own load.
"""

import textwrap


# ------------------------------------------------------------------
# 1. L4 load balancing — connection-level, protocol-agnostic
# ------------------------------------------------------------------
def l4_load_balancing_demo():
    print("L4 (Transport Layer) load balancing:")
    print("  Decision made ONCE per TCP connection, based ONLY on:")
    print("    - Source/destination IP address")
    print("    - Source/destination port")
    print("  The load balancer NEVER parses what's actually being sent —")
    print("  it could be HTTP, a database wire protocol, or anything else.")
    print()
    print("  Example: a new TCP connection arrives ->")
    print("    L4 LB picks backend 'server-3' via round robin (L22) ->")
    print("    ALL packets for this connection's lifetime go to server-3,")
    print("    regardless of what requests are later sent over it.")


# ------------------------------------------------------------------
# 2. L7 load balancing — request-aware, content-based routing
# ------------------------------------------------------------------
def l7_route_request(http_path: str, http_headers: dict) -> str:
    # This is only possible because an L7 load balancer actually PARSES
    # the HTTP request — an L4 load balancer has no concept of "path" at all
    if http_path.startswith("/api/orders"):
        return "orders-service-pool"
    elif http_path.startswith("/api/users"):
        return "users-service-pool"
    elif http_headers.get("X-Canary") == "true":
        return "canary-release-pool"
    else:
        return "default-pool"


def l7_load_balancing_demo():
    print("\nL7 (Application Layer) load balancing:")
    requests = [
        {"path": "/api/orders/12345", "headers": {}},
        {"path": "/api/users/me", "headers": {}},
        {"path": "/api/orders/999", "headers": {"X-Canary": "true"}},
        {"path": "/health", "headers": {}},
    ]
    for req in requests:
        backend = l7_route_request(req["path"], req["headers"])
        print(f"  Request to '{req['path']}' (headers={req['headers']}) "
              f"-> routed to '{backend}'")
    print("\n  -> Each request can route DIFFERENTLY, even over the SAME")
    print("     persistent connection — impossible for a pure L4 load balancer.")


# ------------------------------------------------------------------
# 3. Combined architecture — L4 outer, L7 inner
# ------------------------------------------------------------------
COMBINED_ARCHITECTURE = textwrap.dedent("""\
    Client
      |
      v
    [L4 Load Balancer]  <- maximizes raw throughput, absorbs connection volume
      |
      +----------------+----------------+
      v                v                v
    [L7 LB instance 1] [L7 LB instance 2] [L7 LB instance 3]
      |  (each parses HTTP, routes by path/header — L24/L25)
      v
    [Backend service pools, chosen per-request]

    The L4 layer doesn't need to understand HTTP AT ALL — it just needs
    to distribute raw connections across the L7 tier efficiently. The
    L7 tier then does the actual content-aware routing work.
""")


if __name__ == "__main__":
    l4_load_balancing_demo()
    l7_load_balancing_demo()
    print()
    print(COMBINED_ARCHITECTURE)

"""
PRODUCTION CONTEXT EXAMPLE:
A large e-commerce platform places a cloud provider's L4 network load
balancer (e.g. AWS Network Load Balancer — this repo's Cloud Platforms
Notes covers this service) at its edge for maximum raw throughput and
built-in DDoS absorption, distributing connections across a fleet of
Envoy (L25) instances acting as the L7 layer — Envoy then makes the
ACTUAL routing decisions (which microservice handles this specific
request path, which canary percentage of traffic gets the new version)
that the outer L4 layer is structurally unable to make, combining both
layers' respective strengths in one architecture.
"""
