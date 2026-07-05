# ============================================================
# L02: SFU vs MCU Architecture — How Group Video Calls Actually Scale
# ============================================================
# WHAT: The two fundamentally different server architectures for GROUP
#       (more than 2-person) video calls — the Selective Forwarding Unit
#       (SFU) and the Multipoint Control Unit (MCU) — and why nearly every
#       modern product (Google Meet, Zoom) uses an SFU.
# WHY: L01 covered PEER-TO-PEER connections, which work for a 1:1 call —
#      but peer-to-peer breaks down catastrophically for GROUP calls (a
#      pure mesh would require every participant to upload their video
#      N-1 times, to every other participant) — this lesson covers the
#      actual server architecture that makes group video calls feasible.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
A pure PEER-TO-PEER MESH for a group call (every participant connects
directly to every other participant, as in L01) has a critical scaling
flaw: each participant must UPLOAD their own video stream separately to
EVERY other participant — for a 10-person call, each participant uploads
their video 9 TIMES simultaneously. Given typical home upload bandwidth
is far more constrained than download bandwidth, this makes mesh
architecture infeasible beyond roughly 3-4 participants.

An SFU (Selective Forwarding Unit) solves this: each participant uploads
their video stream ONCE, to a central server — the SFU then FORWARDS
(without re-encoding) that stream to every other participant who needs
it. This changes the upload burden from O(N) per participant to O(1) —
each participant uploads once, regardless of call size — while the SFU
itself absorbs the fan-out cost. Critically, the SFU does NOT decode or
re-encode media (a CPU-expensive operation) — it operates on encrypted
packets, forwarding them as-is, which is why SFUs can handle enormous
numbers of concurrent streams on modest server hardware relative to
what an MCU would require.

An MCU (Multipoint Control Unit) takes a different approach: it DECODES
every participant's incoming stream, COMPOSITES them into a single
combined video (e.g. a grid layout), then RE-ENCODES and sends ONE
combined stream to each participant. This is dramatically more
CPU-INTENSIVE (real-time video decode/composite/encode for every
participant, at scale) but has one genuine advantage: it works for very
low-bandwidth or low-power client devices, since the client only ever
receives ONE stream to decode, rather than needing to decode N separate
incoming streams as an SFU-based client does.

SIMULCAST is the technique that makes SFU-based calls work well across
participants with wildly different bandwidth/device capabilities: each
sender encodes and uploads MULTIPLE QUALITY VERSIONS of their own video
simultaneously (e.g. 1080p, 480p, 180p) — the SFU then selects WHICH
version to forward to each individual receiver based on THAT receiver's
available bandwidth, without needing to re-encode anything itself (this
connects directly to L03's adaptive bitrate coverage).

PRODUCTION USE CASE:
Google Meet uses an SFU architecture: each participant uploads one
simulcast-encoded stream; the SFU forwards the appropriate quality layer
to each receiver based on that receiver's measured bandwidth and how many
participants they're currently viewing (a participant viewing a 20-person
grid receives lower-resolution streams per tile than one in a 1:1 call,
even for the SAME sender) — this per-receiver, per-stream quality
selection is only possible because the SFU is doing selective FORWARDING,
not re-encoding, keeping its own CPU cost low even at very high concurrent-call volume.

COMMON MISTAKES:
- Choosing an MCU architecture by default without considering its CPU
  cost — MCUs require dedicated transcoding hardware (or heavy CPU/GPU
  resources) that scales roughly LINEARLY with concurrent participants
  needing composited streams, a dramatically more expensive
  infrastructure profile than an SFU serving the same call volume.
- Building a pure mesh architecture (no server component at all) assuming
  it will "scale fine since it's peer-to-peer" — this fails specifically
  because of UPLOAD bandwidth, not download bandwidth, a distinction
  engineers unfamiliar with asymmetric home internet connections often miss.
- Implementing simulcast on the SENDER side without the SFU-side logic to
  actually SELECT the right layer per receiver — simulcast's value is
  entirely in the SFU's ability to forward DIFFERENT layers to different
  receivers; sending multiple layers without smart per-receiver selection
  wastes upload bandwidth for no benefit.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Bandwidth cost comparison: mesh vs SFU vs MCU
# ------------------------------------------------------------------
def bandwidth_comparison(num_participants: int, stream_mbps: float = 2.0):
    print(f"Group call with {num_participants} participants, "
          f"{stream_mbps} Mbps per video stream:\n")

    # MESH: each participant uploads to every OTHER participant separately
    mesh_upload_per_participant = stream_mbps * (num_participants - 1)
    print(f"  MESH (peer-to-peer, no server):")
    print(f"    Upload per participant: {mesh_upload_per_participant:.1f} Mbps "
          f"(uploads the SAME stream {num_participants - 1} times)")
    print(f"    -> Infeasible beyond ~3-4 participants for typical home upload speeds.")

    # SFU: each participant uploads ONCE to the server; server fans out
    sfu_upload_per_participant = stream_mbps
    sfu_server_total_bandwidth = stream_mbps * num_participants * (num_participants - 1)
    print(f"\n  SFU (selective forwarding):")
    print(f"    Upload per participant: {sfu_upload_per_participant:.1f} Mbps "
          f"(uploads ONCE, regardless of call size)")
    print(f"    Server total bandwidth (fan-out): ~{sfu_server_total_bandwidth:.1f} Mbps "
          f"(the SFU absorbs this, not any individual participant)")

    # MCU: each participant uploads once; server does CPU-heavy decode/composite/encode
    print(f"\n  MCU (composite + re-encode):")
    print(f"    Upload per participant: {stream_mbps:.1f} Mbps (same as SFU)")
    print(f"    Server CPU cost: HIGH — decodes {num_participants} streams, composites, "
          f"re-encodes {num_participants} personalized composite streams IN REAL TIME")
    print(f"    Client benefit: receives only ONE stream to decode (helps low-power devices)")


# ------------------------------------------------------------------
# 2. Simulcast — adapting stream quality per receiver
# ------------------------------------------------------------------
SIMULCAST_EXPLANATION = textwrap.dedent("""\
    Simulcast: the SENDER encodes multiple quality layers simultaneously:

      Layer 0 (high):   1080p @ 2.5 Mbps
      Layer 1 (medium):  480p @ 0.8 Mbps
      Layer 2 (low):     180p @ 0.15 Mbps

    The SFU picks WHICH layer to forward to each receiver, independently,
    based on that receiver's own bandwidth/rendering needs:

      Receiver A (1:1 view, good bandwidth)      -> gets Layer 0 (1080p)
      Receiver B (20-person grid, small tiles)   -> gets Layer 2 (180p)
      Receiver C (mobile, constrained bandwidth) -> gets Layer 1 (480p)

    Critically: the SFU does NOT re-encode to produce these differences —
    it simply forwards the ALREADY-ENCODED layer that best fits each
    receiver, which is why this scales without adding CPU cost to the SFU.
""")


if __name__ == "__main__":
    bandwidth_comparison(num_participants=10)
    print()
    print(SIMULCAST_EXPLANATION)

"""
PRODUCTION CONTEXT EXAMPLE:
During a 50-person Google Meet call, a participant on a train with
fluctuating 4G bandwidth automatically receives lower-resolution simulcast
layers for every other participant's video, while participants on stable
office WiFi continue receiving high-resolution layers — the SFU makes
this per-receiver decision continuously and independently, with NO
impact on the SENDING participants' own upload behavior or quality,
which is exactly the scaling property that makes SFU-based architecture
the industry-standard choice for group video products at this scale.
"""
