# ============================================================
# L01: WebRTC Fundamentals and Signaling — How Google Meet Establishes a Call
# ============================================================
# WHAT: The mechanics of establishing a real-time peer connection over the
#       internet — ICE candidate gathering, NAT traversal (STUN/TURN), and
#       the SIGNALING SERVER that exchanges connection metadata before any
#       media flows.
# WHY: This repo's System Design Notes covers general distributed-systems
#      fundamentals (CAP theorem, load balancers). Real-time video (Google
#      Meet, Zoom, Discord) is a DIFFERENT class of problem — the actual
#      media never touches your application server at all, which is the
#      single most surprising fact for engineers new to this space.
# LEVEL: Foundation (of this case-study track)
# ============================================================

"""
CONCEPT OVERVIEW:
WebRTC (Web Real-Time Communication) lets two browsers/devices send audio,
video, and data DIRECTLY to each other (peer-to-peer) rather than routing
media through a central server — critical for latency, since a round trip
through a server adds delay that's directly perceptible in a live
conversation. But establishing that direct connection is genuinely hard:
both devices are typically behind NAT (Network Address Translation) and/or
firewalls, meaning neither has a public IP address the other can dial directly.

NAT TRAVERSAL solves this via the ICE (Interactive Connectivity
Establishment) framework, which tries multiple candidate paths:
  1. HOST candidate: the device's own local IP (works only on the same LAN).
  2. SERVER-REFLEXIVE candidate: obtained via a STUN server — a device asks
     "what does my traffic look like from the outside?" and the STUN server
     replies with the public IP:port your NAT assigned you. If BOTH peers'
     NATs allow it, they can now connect directly using these public-facing addresses.
  3. RELAY candidate: if direct connection fails (symmetric NATs, restrictive
     firewalls — common on corporate networks), a TURN server relays the
     media between both peers. This is a genuine LAST RESORT because it
     means the "peer-to-peer" call is now flowing through a third-party
     server, consuming that server's bandwidth for the ENTIRE call
     duration — TURN servers are the most expensive infrastructure
     component in a WebRTC deployment.

SIGNALING is the OUT-OF-BAND exchange of connection metadata (ICE
candidates, session descriptions describing codecs/resolution via SDP —
Session Description Protocol) needed BEFORE peers can connect — WebRTC
deliberately does NOT specify how signaling happens; it just assumes SOME
channel exists. In practice, this is a normal server your application
already controls — a WebSocket connection to your backend — carrying
"here's my offer," "here's my answer," "here's my ICE candidate" messages
between two clients trying to connect. The signaling server ITSELF never
touches audio/video; it only ever exchanges small JSON metadata messages.

PRODUCTION USE CASE:
Google Meet's signaling server accepts a WebSocket connection from each
participant on room join, brokering the SDP offer/answer exchange and ICE
candidates between them — for a 1:1 call, this is all it does; the
signaling server then steps back, and the actual audio/video packets flow
peer-to-peer (or through a TURN relay, if direct connection failed) with
zero further server involvement for that media stream.

COMMON MISTAKES:
- Assuming a direct peer-to-peer connection will ALWAYS succeed — in
  practice, a meaningful percentage of real-world connections (estimates
  commonly cited around 10-20%, varying heavily with corporate/restrictive
  network prevalence) require a TURN relay because both peers are behind
  symmetric NATs or firewalls that block direct UDP traffic entirely — a
  production WebRTC system MUST provision TURN capacity, not treat it as optional.
- Conflating the SIGNALING server with the MEDIA path — a common confusion
  for engineers new to WebRTC is assuming the signaling server (which
  IS a normal, easy-to-scale application server) needs to handle the
  bandwidth of the actual call — it does not; it only ever exchanges tiny
  metadata messages, which is why it scales completely differently than
  the media infrastructure (this domain's L02 covers what handles the actual media at scale).
- Not handling ICE RESTART (re-negotiating connectivity mid-call) —
  networks change (a user's WiFi drops and their phone switches to
  cellular); a robust implementation detects this and re-runs ICE gathering
  rather than simply dropping the call.
"""

import json


# ------------------------------------------------------------------
# 1. ICE candidate types, illustrated
# ------------------------------------------------------------------
def describe_ice_candidates():
    candidates = [
        {"type": "host", "address": "192.168.1.42:54321",
         "note": "Local LAN address — only reachable by devices on the same network"},
        {"type": "srflx", "address": "203.0.113.7:61234",
         "note": "Server-reflexive — the public IP:port a STUN server observed, "
                 "usable if the peer's NAT permits inbound traffic to it"},
        {"type": "relay", "address": "198.51.100.9:3478",
         "note": "TURN relay address — LAST RESORT; all media now flows through "
                 "this third-party server, consuming its bandwidth for the call's duration"},
    ]
    print("ICE gathers ALL of these candidate types in parallel, then tries")
    print("each pair (local candidate x remote candidate) to find one that works:\n")
    for c in candidates:
        print(f"  [{c['type']:>5}] {c['address']}  — {c['note']}")


# ------------------------------------------------------------------
# 2. A minimal signaling message exchange (conceptual)
# ------------------------------------------------------------------
def simulate_signaling_exchange():
    # Peer A creates an "offer" describing its media capabilities (codecs,
    # resolution) and sends it through the signaling server (a WebSocket)
    offer = {
        "type": "offer",
        "sdp": "v=0...(codec/resolution negotiation details)...",
        "from": "peer_a",
        "to": "peer_b",
    }
    print("STEP 1 — Peer A sends OFFER via signaling WebSocket:")
    print(f"  {json.dumps(offer, indent=2)[:120]}...")

    # Peer B responds with a matching "answer"
    answer = {"type": "answer", "sdp": "v=0...(matching SDP)...",
              "from": "peer_b", "to": "peer_a"}
    print("\nSTEP 2 — Peer B replies with ANSWER via the SAME signaling channel:")
    print(f"  {json.dumps(answer, indent=2)[:120]}...")

    # Both sides then exchange ICE candidates as they're discovered
    ice_message = {"type": "ice-candidate",
                    "candidate": "candidate:1 1 UDP 2130706431 192.168.1.42 54321 typ host",
                    "from": "peer_a", "to": "peer_b"}
    print("\nSTEP 3 — Both peers exchange ICE candidates AS THEY'RE DISCOVERED")
    print(f"  (this can happen several times per peer): {ice_message['candidate']}")

    print("\nSTEP 4 — Once a working candidate pair is found, media flows")
    print("  DIRECTLY between peers (or via TURN relay) — the signaling")
    print("  server's job for this connection is now DONE.")


if __name__ == "__main__":
    describe_ice_candidates()
    print()
    simulate_signaling_exchange()

"""
PRODUCTION CONTEXT EXAMPLE:
A Google Meet call between two participants on different corporate
networks fails to establish a direct peer-to-peer connection because
BOTH networks' firewalls block unsolicited inbound UDP — ICE tries every
candidate pair, all direct-connection attempts time out, and the call
falls back to a TURN relay. Google's infrastructure provisions TURN
capacity as a CORE, expected cost center (not a rare fallback) precisely
because this scenario — corporate/restrictive network + corporate/
restrictive network — is common enough in a workplace-communication
product's actual usage pattern that treating TURN as "the exceptional
case" would under-provision for real-world traffic.
"""
