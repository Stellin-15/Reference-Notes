# ============================================================
# L30: Capstone — Wiring the Full Infrastructure Stack Together
# ============================================================
# WHAT: A capstone lesson combining L21-L29's load balancing, reverse
#       proxy, TLS, resource allocation, and autoscaling lessons into
#       ONE coherent, end-to-end infrastructure architecture — and
#       showing how this same infrastructure layer underlies EVERY
#       earlier case study in this domain (Google Meet, Docs, Spotify,
#       Shazam, Reddit).
# WHY: L01-L20 covered PRODUCT-specific system designs, each of which
#      silently ASSUMED a working infrastructure layer underneath it
#      (server selection, capacity, traffic routing). This capstone
#      makes that assumed layer explicit and complete.
# LEVEL: Capstone
# ============================================================

"""
CONCEPT OVERVIEW:
Tracing a single request through the FULL stack built across L21-L29:

  1. DNS resolves the client to the platform's edge infrastructure.
  2. An L4 LOAD BALANCER (L21) receives the raw connection, distributing
     it across a fleet of L7 proxy instances for maximum throughput.
  3. TLS TERMINATION (L26) happens at this L7 layer — decrypting the
     request, then RE-ENCRYPTING for the internal hop (a zero-trust-
     appropriate choice, per L26's tradeoff discussion).
  4. The REVERSE PROXY (L24), running on something like Envoy (L25 —
     chosen here because backend topology changes constantly), applies
     L7 CONTENT-AWARE ROUTING (L21): parsing the request path/headers to
     determine which backend SERVICE POOL should handle it.
  5. Within that service pool, a SELECTION ALGORITHM (L22) — perhaps
     least-connections for a general API, or consistent hashing for a
     request that needs to hit the same cache-warmed backend — picks the
     SPECIFIC instance to handle this request, filtered to only
     HEALTHY instances per continuous HEALTH CHECKING (L23).
  6. The chosen instance itself is running on a node PLACED there by a
     RESOURCE ALLOCATION/BIN-PACKING decision (L27) balancing cost
     efficiency against fault-tolerance requirements for that specific service.
  7. The overall FLEET SIZE of that service pool is continuously
     adjusted by AUTOSCALING (L28) — reactively, predictively, and/or on
     a schedule, depending on that service's demand pattern.

THIS INFRASTRUCTURE LAYER UNDERLIES EVERY EARLIER CASE STUDY in this
domain, even though none of L01-L20 discussed it explicitly:
  - Google Meet's SFU/TURN server selection (L05) is itself a
    specialized load-balancing decision — routing a participant to the
    least-loaded, geographically-nearest SFU is CONCEPTUALLY the same
    problem as L22's algorithms, applied to stateful media servers
    rather than stateless HTTP backends.
  - Google Docs' signaling/collaboration servers (L06-L10) sit behind
    this SAME kind of load-balanced, health-checked, autoscaled
    infrastructure — a collaboration server crashing needs the same
    health-check-driven failover (L23) as any other backend.
  - Spotify's CDN edge nodes (L11) and Shazam's fingerprint-matching
    servers (L15) both need capacity that SCALES with demand (L28) and
    are PLACED across infrastructure efficiently (L27).
  - Reddit's comment/voting/feed services (L16-L20) are exactly the kind
    of stateless, horizontally-scaled workloads L21-L25's load-balancing
    stack was designed to route traffic across.

None of those earlier lessons needed to explain THIS layer in depth
BECAUSE this capstone (and L21-L29) exists to cover it once, thoroughly,
as the shared infrastructure foundation every product-specific system design sits on top of.

PRODUCTION USE CASE:
See the full request trace above — this is, in outline, the actual
infrastructure architecture a production platform like Google, Spotify,
or Reddit operates, regardless of which specific PRODUCT feature (video
calls, collaborative docs, music streaming, audio fingerprinting, social
feeds) is running on top of it.

COMMON MISTAKES:
- Designing a product-specific system (like any of L01-L20's case
  studies) while treating "the infrastructure just handles traffic
  routing/scaling" as an unexamined given — every one of those product
  designs has REAL infrastructure requirements (SFU selection needs
  geographic+load awareness, collaboration servers need failover, CDN
  edges need autoscaling) that this capstone's layer must actually satisfy.
- Assuming ONE load-balancing algorithm/tool choice serves every service
  in a platform equally well — L22 and L25 both emphasized that
  different services (stateful media servers vs stateless APIs vs
  cache-affinity-sensitive lookups) genuinely warrant DIFFERENT
  algorithm and tool choices within the SAME overall platform.
- Under-investing in the "boring" infrastructure layer (health checks,
  autoscaling, resource allocation) relative to product feature work —
  as this capstone's trace shows, EVERY product feature ultimately
  depends on this layer working correctly; a product feature built on
  top of poorly-configured infrastructure inherits all of that
  infrastructure's reliability problems regardless of how well the feature itself is designed.
"""

import textwrap


FULL_REQUEST_TRACE = textwrap.dedent("""\
    Client request for "https://api.example.com/api/orders/12345"
      |
      v
    [DNS] -> resolves to platform edge IP
      |
      v
    [L4 Load Balancer] (L21) -> distributes raw connections across L7 tier
      |
      v
    [TLS Termination] (L26) -> decrypts, then RE-ENCRYPTS for internal hop
      |
      v
    [Reverse Proxy / Envoy] (L24, L25) -> parses path "/api/orders/*"
      |                                    -> routes to "orders-service-pool"
      v
    [Health-Checked Backend Pool] (L23) -> filters to HEALTHY instances only
      |
      v
    [Selection Algorithm] (L22) -> least-connections picks "orders-instance-7"
      |
      v
    [orders-instance-7] -> running on a node placed via bin-packing (L27),
      |                     within a pool sized by autoscaling (L28)
      v
    Response streams back through the SAME path in reverse
""")

CASE_STUDY_MAPPING = {
    "Google Meet (L01-L05)": "SFU/TURN selection = load balancing applied to stateful media servers",
    "Google Docs (L06-L10)": "Collaboration servers need the SAME health-check-driven failover as any backend",
    "Spotify (L11-L13)": "CDN edges need autoscaling (L28) and efficient placement (L27)",
    "Shazam (L14-L15)": "Fingerprint-matching server pools scale with query volume (L28)",
    "Reddit/Social (L16-L20)": "Comment/voting/feed services are classic horizontally-scaled, load-balanced workloads",
}


if __name__ == "__main__":
    print(FULL_REQUEST_TRACE)
    print("How this infrastructure layer underlies every earlier case study:\n")
    for case_study, connection in CASE_STUDY_MAPPING.items():
        print(f"  {case_study}:")
        print(f"    {connection}\n")

"""
FINAL CONTEXT (capstone of this entire domain):
The measure of having internalized this domain isn't being able to
describe Google Meet's SFU architecture or Reddit's ranking formulas in
isolation — it's recognizing that EVERY one of those product-specific
designs (L01-L20) sits on top of the SAME shared infrastructure
concerns this capstone (and L21-L29) made explicit: routing traffic to
healthy backends, selecting among them intelligently, placing them
efficiently across physical capacity, and scaling that capacity to meet
demand. A senior engineer or architect designing a NEW product feature
should be able to reuse this infrastructure layer's concepts directly,
rather than re-deriving load-balancing or autoscaling logic from
scratch for every new system — this is, in essence, why platform
engineering (this repo's Platform Engineering Notes) exists as its own
discipline: building this layer ONCE, well, so every product team building on top of it doesn't have to.
"""
