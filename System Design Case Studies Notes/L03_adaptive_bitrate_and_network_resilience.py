# ============================================================
# L03: Adaptive Bitrate and Network Resilience in Real-Time Video
# ============================================================
# WHAT: How a video call adapts, in real time, to changing network
#       conditions — congestion control, dynamic quality adjustment, and
#       packet-loss concealment — so a call degrades GRACEFULLY rather
#       than freezing or dropping.
# WHY: L02 covered simulcast (multiple pre-encoded quality layers); this
#      lesson covers the CONTROL LOOP that decides, moment to moment,
#      which layer to use and how to recover from actual packet loss —
#      the mechanism that makes a call usable on an imperfect network at all.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
REAL-TIME video cannot use the same congestion-handling strategy as a
file download: TCP's "retransmit lost packets and wait" behavior is
actively HARMFUL for live video — a retransmitted packet for a video
frame from 500ms ago is USELESS once it finally arrives, because the
call has already moved on. This is why WebRTC media runs over UDP via
RTP (Real-time Transport Protocol) — an occasional lost packet is
simply accepted and worked around, rather than retransmitted and waited for.

CONGESTION CONTROL for real-time media (commonly GCC — Google Congestion
Control, used in WebRTC) continuously ESTIMATES available bandwidth by
watching for early signs of network congestion — specifically, increasing
PACKET ARRIVAL DELAY (packets taking progressively longer to arrive, even
before any are actually lost) is used as an EARLY WARNING signal, letting
the sender reduce its bitrate BEFORE outright packet loss occurs, rather
than reactively backing off only after loss is already happening
(a fundamentally different, more proactive strategy than TCP's
loss-triggered congestion control).

ADAPTIVE BITRATE, built on this bandwidth estimate, adjusts what's
ACTUALLY sent: for simulcast (L02), this means switching WHICH pre-encoded
layer is forwarded; for a single encoder (a 1:1 call without simulcast),
this means the encoder ITSELF dynamically re-targets its output bitrate/
resolution/frame rate in response to the estimate — trading video quality
DOWN gracefully as available bandwidth drops, rather than the connection
simply failing outright.

PACKET LOSS CONCEALMENT handles the packets that DO get lost despite
congestion control: FEC (Forward Error Correction) proactively sends
REDUNDANT data (extra parity packets) alongside the main stream, letting
the receiver RECONSTRUCT a lost packet without needing a retransmission
round trip — at the cost of extra bandwidth for the redundant data. When
FEC isn't enough, JITTER BUFFER + INTERPOLATION strategies smooth over
gaps (holding frames slightly longer, extrapolating audio/video for a
brief gap) rather than freezing/glitching visibly — a small, deliberately
introduced LATENCY (the jitter buffer) trades a slightly delayed
experience for a visibly smoother one.

PRODUCTION USE CASE:
A Google Meet participant's home WiFi experiences transient congestion
(another device starts a large download) — GCC's bandwidth estimator
detects rising packet delay within a few hundred milliseconds and signals
the SFU to switch that participant's incoming video to a lower simulcast
layer, and/or the participant's own outgoing encoder reduces its target
bitrate — the call continues at reduced quality rather than freezing,
and quality recovers automatically once the competing download finishes
and available bandwidth returns.

COMMON MISTAKES:
- Using TCP for real-time media — this is the single most common mistake
  for engineers building real-time systems without WebRTC-specific
  experience; TCP's retransmission and in-order delivery guarantees are
  EXACTLY WRONG for live media, where a late packet is worse than a lost one.
- Reacting to congestion ONLY after outright packet loss occurs, rather
  than using RISING DELAY as an earlier signal — a congestion-control
  algorithm that waits for loss is inherently more reactive/laggy than
  one using delay-based prediction, leading to visibly worse quality
  swings ("quality yo-yo-ing") under fluctuating network conditions.
- Setting a FIXED jitter buffer size regardless of actual observed network
  jitter — too small a buffer causes audible/visible glitches on a jittery
  network; too large a buffer adds unnecessary LATENCY on a stable
  network — an adaptive jitter buffer (sized dynamically based on recently
  observed jitter) is the production-correct approach.
"""

import random


# ------------------------------------------------------------------
# 1. Delay-based congestion signal, simulated
# ------------------------------------------------------------------
def simulate_bandwidth_estimation(packet_delays_ms: list[float]) -> str:
    """A simplified delay-trend detector: rising delay -> reduce bitrate."""
    if len(packet_delays_ms) < 3:
        return "insufficient data"

    recent_trend = packet_delays_ms[-1] - packet_delays_ms[-3]
    if recent_trend > 15:
        return "OVERUSE detected (rising delay) -> REDUCE bitrate proactively"
    elif recent_trend < -15:
        return "UNDERUSE detected (falling delay) -> gradually INCREASE bitrate"
    else:
        return "STABLE -> hold current bitrate"


def congestion_control_demo():
    print("Simulated packet arrival delay over time (ms), and GCC's reaction:\n")
    scenarios = {
        "Stable network": [20, 21, 19, 20, 22, 20],
        "Congestion building (another device starts downloading)": [20, 25, 35, 50, 68, 90],
        "Congestion clearing": [90, 70, 50, 35, 22, 20],
    }
    for label, delays in scenarios.items():
        decision = simulate_bandwidth_estimation(delays)
        print(f"  {label}:")
        print(f"    Delay samples: {delays}")
        print(f"    Decision: {decision}\n")


# ------------------------------------------------------------------
# 2. Forward Error Correction — reconstructing lost packets
# ------------------------------------------------------------------
def simulate_fec_recovery(original_packets: list[str], loss_positions: set[int]):
    # A simplified XOR-based FEC: one parity packet can recover ONE lost
    # packet among the group it protects (real FEC schemes are more
    # sophisticated, protecting against multiple losses per group)
    received = [p if i not in loss_positions else None for i, p in enumerate(original_packets)]
    print(f"Original packets sent: {original_packets}")
    print(f"Received (lost positions marked None): {received}")

    lost_count = received.count(None)
    if lost_count == 0:
        print("  -> No loss; no recovery needed.")
    elif lost_count == 1:
        # A single parity packet (conceptually: XOR of all data packets)
        # can reconstruct exactly ONE missing packet
        recovered_index = received.index(None)
        received[recovered_index] = original_packets[recovered_index]
        print(f"  -> FEC parity packet RECOVERS the single lost packet "
              f"at position {recovered_index}, with NO retransmission round trip.")
    else:
        print(f"  -> {lost_count} packets lost — exceeds this FEC group's "
              f"recovery capacity; the jitter buffer/concealment layer "
              f"must interpolate or accept a brief visible/audible glitch.")


# ------------------------------------------------------------------
# 3. Adaptive jitter buffer sizing
# ------------------------------------------------------------------
def adaptive_jitter_buffer_demo():
    network_conditions = {
        "Stable fiber connection": [5, 6, 5, 7, 5, 6],       # low jitter (ms)
        "Congested WiFi": [10, 45, 15, 60, 20, 50],           # high jitter (ms)
    }
    for label, arrival_jitter_samples in network_conditions.items():
        observed_jitter = max(arrival_jitter_samples) - min(arrival_jitter_samples)
        # A common heuristic: buffer size scales with recently observed jitter,
        # with some safety margin — NOT a fixed constant regardless of conditions
        buffer_size_ms = observed_jitter * 1.5
        print(f"{label}: observed jitter={observed_jitter}ms "
              f"-> adaptive buffer size={buffer_size_ms:.0f}ms")
    print("\n  -> A FIXED buffer sized for the worst case would add unnecessary")
    print("     latency on the stable connection; sizing it ADAPTIVELY per")
    print("     actual observed conditions balances latency against smoothness.")


if __name__ == "__main__":
    congestion_control_demo()
    simulate_fec_recovery(["pkt1", "pkt2", "pkt3", "pkt4"], loss_positions={2})
    print()
    adaptive_jitter_buffer_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A Google Meet call on a train experiences BOTH gradually rising latency
(entering a congested cell tower's coverage) and sudden packet loss
(brief tunnel dead zones) — the SAME call handles both differently:
GCC's delay-based estimator proactively steps DOWN the video bitrate as
latency rises (avoiding an abrupt quality cliff), while FEC recovers
occasional isolated packet losses without any visible glitch, and the
adaptive jitter buffer widens slightly to absorb the increased jitter —
three DIFFERENT resilience mechanisms, each addressing a distinct
failure mode, working together so the human on the call perceives a
"slightly lower quality but still usable" call rather than a frozen or dropped one.
"""
