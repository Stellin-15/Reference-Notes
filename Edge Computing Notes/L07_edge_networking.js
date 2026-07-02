// ============================================================
// L07: Edge Networking Fundamentals
// ============================================================
// WHAT: The network-layer mechanisms (anycast, BGP, HTTP/3, smart routing)
//       that make edge platforms fast and resilient at a physical-network
//       level, below the application code you write.
// WHY:  Understanding WHY 1.1.1.1 resolves to "the nearest" Cloudflare PoP,
//       or why HTTP/3 avoids head-of-line blocking, explains latency and
//       failover behavior you'll otherwise treat as unexplainable magic.
// LEVEL: Advanced
// ============================================================

/*
CONCEPT OVERVIEW:
Anycast means many physically distinct servers around the world all
ANNOUNCE the same IP address via BGP. Internet routers naturally route a
client's packet to whichever announcing location is topologically
"closest" (fewest BGP hops) — no DNS geolocation trickery needed, and
failover is automatic: if a PoP goes down, it stops announcing the route
and traffic seamlessly reroutes to the next-closest PoP within the normal
BGP convergence time.

HTTP/3 (built on QUIC, over UDP instead of TCP) solves head-of-line
blocking at the TRANSPORT layer: in HTTP/2 over TCP, one lost packet stalls
ALL multiplexed streams on that connection (TCP guarantees in-order
delivery of the whole byte stream). QUIC multiplexes streams independently
at the protocol level, so a lost packet only stalls the one stream it
belonged to.

PRODUCTION USE CASE:
A CDN's Argo Smart Routing (Cloudflare's term; other providers have
equivalents) continuously measures real-world latency across its private
backbone between PoPs and origin, and routes edge-to-origin traffic over
the fastest measured path — which is frequently NOT the "shortest"
geographic path, because public internet congestion varies by time of day
and peering relationships.

COMMON MISTAKES:
  - Assuming anycast means "the closest PoP by geographic distance" — it's
    closest by BGP path cost, which can differ significantly from
    physical distance depending on peering.
  - Not enabling HTTP/3 and assuming HTTP/2 is "good enough" — on lossy
    networks (mobile, congested Wi-Fi), QUIC's per-stream loss recovery is
    a measurable, not marginal, latency win.
  - Terminating TLS at the edge but running plaintext HTTP to origin over
    the public internet instead of a private backbone/tunnel — undoes much
    of the edge's security value.
*/

// ------------------------------------------------------------------
// 1. Anycast and BGP — the physical routing layer
// ------------------------------------------------------------------
const ANYCAST_NOTES = `
Every edge PoP runs a BGP speaker announcing the SAME prefix (e.g.
1.1.1.0/24). A client's ISP router receives this announcement from
multiple upstream paths and picks the path with the lowest BGP path cost
(roughly: fewest AS hops, though real route selection considers local
preference, MED, and other BGP attributes too). This is why "traceroute
to 1.1.1.1" from Tokyo and from London show completely different paths
terminating at DIFFERENT physical servers, despite both querying the
exact same IP address — anycast makes "nearest" a property of the routing
table, not a DNS lookup.
`;

// ------------------------------------------------------------------
// 2. HTTP/2 vs HTTP/3 (QUIC)
// ------------------------------------------------------------------
const HTTP_VERSION_COMPARISON = {
  "HTTP/1.1": "One request in flight per TCP connection (browsers open "
    + "6+ parallel connections to work around this) — no real "
    + "multiplexing.",
  "HTTP/2": "Multiplexes many streams over ONE TCP connection — solves "
    + "HTTP/1.1's connection-count problem, but a single lost TCP packet "
    + "still stalls EVERY stream on that connection (TCP's in-order "
    + "delivery guarantee applies to the whole connection, not per-stream).",
  "HTTP/3 (QUIC)": "Multiplexes streams over UDP with per-stream loss "
    + "recovery — a lost packet only blocks the one stream it belongs to. "
    + "Also supports 0-RTT connection resumption (skip the TLS+TCP "
    + "handshake round trip entirely for a previously-visited server) and "
    + "CONNECTION MIGRATION (a mobile client switching from Wi-Fi to "
    + "cellular keeps the same QUIC connection alive via a connection ID, "
    + "instead of TCP forcing a fresh handshake).",
};

// ------------------------------------------------------------------
// 3. Early Hints (103) — preloading before the final response
// ------------------------------------------------------------------
const EARLY_HINTS_EXAMPLE = `
// Origin is slow to compute the full response (e.g. a 300ms DB query),
// but already knows which CSS/JS assets the eventual page will need.
// It sends a 103 Early Hints response IMMEDIATELY, letting the browser
// start fetching those assets in parallel WHILE origin is still
// computing the real 200 response — assets are often already cached
// locally by the time the HTML itself arrives.

HTTP/1.1 103 Early Hints
Link: </styles/main.css>; rel=preload; as=style
Link: </scripts/app.js>; rel=preload; as=script

... (300ms later) ...

HTTP/1.1 200 OK
Content-Type: text/html
<html>...</html>
`;

// ------------------------------------------------------------------
// 4. Origin shield — collapsing origin requests
// ------------------------------------------------------------------
const ORIGIN_SHIELD_NOTES = `
Without a shield: 200 edge PoPs each independently miss cache and hit
origin directly on a cold cache — origin sees 200 simultaneous requests
for the same resource. With a shield PoP designated as a single
intermediate layer: all 200 edge PoPs route their origin-bound MISSES
through the shield first; the shield deduplicates (request collapsing,
see L05) and origin sees just ONE request. This trades a small amount of
extra latency on cache misses (one extra hop) for a large reduction in
origin load — worth it for high-fanout, expensive-to-generate content.
`;

// ------------------------------------------------------------------
// 5. Smart routing / private backbone
// ------------------------------------------------------------------
const SMART_ROUTING_NOTES = `
Public internet paths between two points are NOT always the fastest
available route — BGP optimizes for path cost/policy, not measured
latency, and congestion varies by time of day. CDN providers with their
own private backbone (dedicated fiber/leased lines between their own
PoPs) can route edge-to-origin traffic over this private network instead
of the public internet, using real-time latency measurements to pick the
actual fastest path — this is what "Argo Smart Routing" (Cloudflare) or
similar features from other CDNs provide, often measured as a 10-30%
latency improvement over the default public-internet path.
`;

// ------------------------------------------------------------------
// 6. WebSocket and gRPC proxying at the edge
// ------------------------------------------------------------------
const PROTOCOL_PROXYING_NOTES = {
  websocket: "Requires the edge to hold a long-lived, stateful connection "
    + "per client rather than the typical stateless request/response model "
    + "— edge platforms increasingly support this (Durable Objects on "
    + "Cloudflare are explicitly designed for stateful WebSocket handling "
    + "with hibernation to reduce idle cost).",
  grpc: "Requires HTTP/2 (gRPC's transport). Edge proxying of gRPC works, "
    + "but many edge FUNCTION runtimes (as opposed to plain reverse-proxy "
    + "CDN layers) have limited/no native gRPC server support — typically "
    + "gRPC edge use is 'edge as a transparent proxy', not 'gRPC logic "
    + "running inside the edge isolate itself'.",
};

// ------------------------------------------------------------------
// 7. Edge DNS — GeoDNS and health-check failover
// ------------------------------------------------------------------
const EDGE_DNS_NOTES = `
GeoDNS resolves a hostname to DIFFERENT IPs based on the resolver's
geographic location — a coarser-grained alternative to anycast, useful
when you need per-region ROUTING LOGIC (e.g. EU users must hit an
EU-only origin for data-residency reasons) rather than pure
latency-nearest routing. Combined with active health checks, GeoDNS can
also fail a region's traffic over to a healthy region's IP if that
region's health check starts failing — DNS-based failover has a floor on
reaction time set by DNS TTL (can't react faster than clients re-resolve),
unlike anycast's near-instant BGP-level failover.
`;

module.exports = {
  ANYCAST_NOTES,
  HTTP_VERSION_COMPARISON,
  EARLY_HINTS_EXAMPLE,
  ORIGIN_SHIELD_NOTES,
  SMART_ROUTING_NOTES,
  PROTOCOL_PROXYING_NOTES,
  EDGE_DNS_NOTES,
};

/*
TRADING/PRODUCTION CONTEXT EXAMPLE:
A trading platform's web client streams live quotes over a WebSocket
proxied through the edge. During a regional network disruption, anycast
BGP withdrawal reroutes new connections to the next-nearest healthy PoP
within seconds — far faster than a DNS-TTL-bound failover would allow —
while existing WebSocket connections to the affected PoP are dropped and
the client's reconnect logic re-establishes against the now-healthy
anycast address transparently.
*/
