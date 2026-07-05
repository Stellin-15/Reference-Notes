# ============================================================
# L05: Scaling Group Calls — SFU Cascading and TURN Relay Capacity Planning
# ============================================================
# WHAT: How a single SFU's capacity limits are overcome for VERY large
#       calls (SFU cascading across multiple servers/regions), and how
#       to actually capacity-plan TURN relay infrastructure — the two
#       hardest INFRASTRUCTURE-SCALE problems in a real video platform.
# WHY: L01-L04 covered a single call's mechanics. A production platform
#      (Google Meet) must serve MILLIONS of concurrent calls across
#      global regions — this lesson is the capstone connecting L01-L04's
#      single-call mechanics to actual platform-scale architecture.
# LEVEL: Advanced (capstone of this case study)
# ============================================================

"""
CONCEPT OVERVIEW:
A SINGLE SFU instance has a finite capacity — CPU for packet forwarding
and encryption, and NETWORK BANDWIDTH for fan-out (L02's math: bandwidth
scales roughly with participants × streams). For very large calls
(100+ participants, or a broadcast-style "webinar" with thousands of
viewers), a SINGLE SFU instance becomes a bottleneck regardless of the
underlying server's raw specs — the fix is SFU CASCADING: multiple SFU
instances, each handling a SUBSET of participants, relay streams to EACH
OTHER (not directly to every individual remote participant), forming a
tree or mesh of SFUs that collectively serve the full participant count.

GEOGRAPHIC SFU PLACEMENT matters independently of raw capacity: a
participant in Tokyo and a participant in London both connecting to a
single US-based SFU adds unavoidable ROUND-TRIP LATENCY from
geographic distance (physics — the speed of light through fiber sets a
hard floor) — production platforms place SFU instances in MULTIPLE
regions, with participants connecting to their NEAREST SFU, and SFUs
relaying cross-region traffic to each other over optimized backbone
links (typically lower-latency/more-reliable than the general internet
path a participant's own connection would take).

TURN RELAY CAPACITY PLANNING (extending L01's introduction) is a genuine
COST-MODELING challenge: unlike an SFU (which primarily needs CPU for
forwarding), a TURN server's cost is almost PURE BANDWIDTH — it relays
the FULL media stream for every connection using it, for the ENTIRE call
duration. Given L01's observation that a meaningful fraction of real
connections require TURN (often 10-20%+ depending on network
conditions), a platform must provision TURN bandwidth as a function of:
(concurrent calls) × (fraction needing relay) × (average call
bitrate) × (average call duration) — this can represent a
SURPRISINGLY LARGE fraction of total infrastructure cost for a
video platform, often underestimated by teams new to WebRTC-scale operations.

LOAD-BASED SFU/TURN SELECTION: a production system doesn't statically
assign a participant to a fixed server — a SIGNALING/ORCHESTRATION layer
selects the least-loaded, geographically-nearest available SFU (and, if
needed, TURN server) at call-join time, and MONITORS ongoing load to
avoid routing new participants to an already-saturated instance — this
is architecturally similar to L21-L23's general load-balancing concepts,
applied specifically to stateful, long-lived media connections rather than
short-lived HTTP requests.

PRODUCTION USE CASE:
A 500-person Google Meet "webinar" (a small number of presenters, a large
number of view-only attendees) uses SFU cascading: presenters' streams
are forwarded to a small number of "distribution" SFUs, which in turn
each serve a subset of the 500 viewers — no single SFU instance ever
needs to fan out to all 500 viewers directly, keeping any one instance's
bandwidth requirement within normal operating limits, while the overall
system serves the full audience.

COMMON MISTAKES:
- Assuming a single, powerful SFU server can scale a call to arbitrary
  size just by adding more CPU/bandwidth to that one machine — at some
  point, a single instance's NETWORK INTERFACE bandwidth becomes the hard
  ceiling, regardless of CPU headroom; cascading (multiple instances)
  is required past this point, not a bigger single machine.
- Under-provisioning TURN relay capacity because it's treated as a rare
  fallback path — as covered in L01 and reinforced here, TURN usage is a
  MEASURABLE, PREDICTABLE percentage of real-world traffic that must be
  capacity-planned as a CORE cost, not an edge case.
- Statically assigning participants to servers by simple round-robin
  without considering GEOGRAPHIC proximity or CURRENT load — this can
  route a Tokyo-based participant to an already-saturated US SFU purely
  because it's "next in rotation," creating both unnecessary latency AND
  uneven load distribution simultaneously.
"""

import textwrap


# ------------------------------------------------------------------
# 1. SFU cascading topology, illustrated
# ------------------------------------------------------------------
CASCADING_TOPOLOGY = textwrap.dedent("""\
    Single SFU (bottlenecks past ~hundreds of participants):

        [Presenter] --> [SFU] --> fans out directly to ALL viewers
                                   (bandwidth = viewers x streams;
                                    hits network interface ceiling)

    Cascaded SFUs (scales to thousands):

        [Presenter] --> [SFU-1 (ingest)]
                              |
              +---------------+---------------+
              v               v               v
        [SFU-2 (US-East)] [SFU-3 (EU)]  [SFU-4 (Asia)]
              |                |               |
         (100 viewers)   (150 viewers)   (200 viewers)

    Each regional SFU only needs to fan out to ITS OWN subset of
    viewers — SFU-1 forwards ONE copy of each stream to each regional
    SFU, not one copy per INDIVIDUAL remote viewer, keeping SFU-1's own
    bandwidth requirement proportional to the NUMBER OF REGIONS, not
    the total viewer count.
""")

# ------------------------------------------------------------------
# 2. TURN capacity planning — a concrete cost model
# ------------------------------------------------------------------
def turn_capacity_planning(
    concurrent_calls: int,
    turn_fraction: float = 0.15,
    avg_bitrate_mbps: float = 1.5,
    avg_call_minutes: float = 30,
):
    calls_needing_turn = concurrent_calls * turn_fraction
    peak_turn_bandwidth_mbps = calls_needing_turn * avg_bitrate_mbps * 2  # both directions relayed
    total_turn_data_gb_per_hour = (calls_needing_turn * avg_bitrate_mbps * 2 * 60) / 8 / 1000

    print(f"Capacity planning for {concurrent_calls:,} concurrent calls:")
    print(f"  Calls requiring TURN relay ({turn_fraction:.0%}): {calls_needing_turn:,.0f}")
    print(f"  Peak TURN bandwidth needed: {peak_turn_bandwidth_mbps:,.0f} Mbps")
    print(f"  TURN data relayed per hour: ~{total_turn_data_gb_per_hour:,.0f} GB")
    print("  -> This bandwidth is 100% a direct infrastructure cost, unlike")
    print("     an SFU's CPU-bound forwarding cost — TURN's cost model is")
    print("     almost pure bandwidth, making it disproportionately")
    print("     expensive relative to its (correctly) 'fallback' role in the architecture.")


# ------------------------------------------------------------------
# 3. Geographic and load-aware server selection
# ------------------------------------------------------------------
def select_best_sfu(participant_region: str, sfu_pool: list[dict]) -> dict:
    # Filter to SFUs with available capacity, then prefer the closest region,
    # then the least loaded among equally-close candidates
    available = [s for s in sfu_pool if s["current_load_pct"] < 85]
    same_region = [s for s in available if s["region"] == participant_region]
    candidates = same_region if same_region else available
    return min(candidates, key=lambda s: s["current_load_pct"])


def sfu_selection_demo():
    sfu_pool = [
        {"id": "sfu-us-east-1", "region": "us-east", "current_load_pct": 40},
        {"id": "sfu-us-east-2", "region": "us-east", "current_load_pct": 92},  # saturated
        {"id": "sfu-eu-west-1", "region": "eu-west", "current_load_pct": 55},
        {"id": "sfu-ap-south-1", "region": "ap-south", "current_load_pct": 30},
    ]
    for participant_region in ["us-east", "ap-south", "sa-east"]:  # last one has no local SFU
        chosen = select_best_sfu(participant_region, sfu_pool)
        print(f"Participant in {participant_region} -> routed to {chosen['id']} "
              f"(region={chosen['region']}, load={chosen['current_load_pct']}%)")


if __name__ == "__main__":
    print(CASCADING_TOPOLOGY)
    turn_capacity_planning(concurrent_calls=100_000)
    print()
    sfu_selection_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
Google Meet's global infrastructure routes a new call's participants to
their geographically nearest, least-loaded SFU instance at join time,
cascades SFUs across regions for large calls so no single instance's
network interface becomes a bottleneck, and maintains TURN relay
capacity sized as a percentage of total concurrent call volume (not a
rare-case afterthought) — three architectural decisions that, together,
let a single video-calling PRODUCT actually operate at the scale of
millions of simultaneous global calls, built entirely on top of the
per-call mechanics covered in L01-L04.
"""
