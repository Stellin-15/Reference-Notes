# ============================================================
# L04: TCP/IP Deep Dive
# ============================================================
# WHAT: How TCP actually establishes a reliable connection over an
#       unreliable network — the three-way handshake, sequence numbers
#       and acknowledgments for reliability, and sliding-window flow
#       control — the mechanisms underneath "just open a socket."
# WHY: This repo's DevOps & SRE Practices Notes L05 and System Design
#      Case Studies Notes cover networking at the application/
#      infrastructure level. This lesson goes one level deeper — the
#      actual TCP mechanics that make a "reliable" connection possible
#      over a fundamentally unreliable IP network.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
IP (Internet Protocol) itself provides NO reliability guarantee
whatsoever — an IP packet ("datagram") might be LOST, DUPLICATED, or
arrive OUT OF ORDER relative to other packets, and IP alone does
nothing to detect or correct any of this (directly connecting to this
repo's Distributed Systems Theory Notes L01's "the network is
reliable" fallacy) — TCP is built ON TOP of IP specifically to provide
a reliable, ordered, connection-oriented abstraction despite this unreliable foundation.

THE THREE-WAY HANDSHAKE establishes a TCP connection before any actual
data is sent: the client sends a SYN (synchronize) packet with an
initial random SEQUENCE NUMBER; the server responds with a SYN-ACK
(acknowledging the client's SYN, while also sending its OWN initial
sequence number); the client responds with a final ACK — after this
three-step exchange, BOTH sides have agreed on starting sequence
numbers and confirmed the OTHER side is actually reachable and
responsive, before any application data is exchanged — this handshake
is exactly WHY establishing a NEW TCP connection has real, unavoidable
latency cost (at minimum, one full round trip) BEFORE any actual data can be sent.

SEQUENCE NUMBERS AND ACKNOWLEDGMENTS provide TCP's core reliability
guarantee: every byte sent is assigned a sequence number; the receiver
sends ACKNOWLEDGMENTS indicating which sequence numbers it has
successfully received — if the sender doesn't receive an
acknowledgment within an expected timeframe, it RETRANSMITS the
unacknowledged data, assuming it was lost — sequence numbers ALSO let
the receiver correctly REORDER packets that arrive out of order
(since IP alone provides no ordering guarantee) before delivering them
to the application in the correct order — the application layer NEVER
sees out-of-order or duplicate data; TCP handles this entirely transparently underneath.

SLIDING WINDOW FLOW CONTROL prevents a FAST SENDER from overwhelming a
SLOWER RECEIVER: the receiver advertises a WINDOW SIZE (how much
additional data it's currently willing to buffer/receive) as part of
every acknowledgment — the sender is only permitted to have this much
UNACKNOWLEDGED data "in flight" at any time, dynamically adjusting as
the receiver's advertised window changes (e.g. shrinking if the
receiving application is processing data slowly, growing again once it
catches up) — this is DISTINCT FROM (though related to) CONGESTION
CONTROL, which addresses NETWORK-level congestion rather than
receiver-side buffer capacity specifically (this repo's System Design
Case Studies Notes L03 covered a related, delay-based congestion
control approach for real-time media specifically, built on similar underlying principles).

TCP'S CONNECTION-ORIENTED, RELIABLE MODEL VS UDP'S CONNECTIONLESS,
UNRELIABLE MODEL is a genuinely important design choice for application
protocols: UDP provides NONE of TCP's reliability/ordering machinery
(no handshake, no retransmission, no ordering guarantee) — this makes
it FASTER and lower-overhead, at the cost of the application needing to
handle any reliability requirements itself, if any are needed at all —
this repo's System Design Case Studies Notes L03 covered exactly why
real-time media specifically uses UDP rather than TCP: a late,
retransmitted video frame is USELESS by the time it arrives, making
TCP's guaranteed-delivery behavior actively counterproductive for that specific use case.

PRODUCTION USE CASE:
A mobile app experiences noticeably higher latency on its FIRST request
to a new server compared to SUBSEQUENT requests over the SAME
connection — this is directly explained by TCP's handshake cost: the
first request pays for a full three-way handshake round trip (plus,
for HTTPS, an additional TLS handshake round trip) before any data
flows, while subsequent requests reuse the ALREADY-ESTABLISHED
connection (via HTTP keep-alive) and skip this setup cost entirely —
directly motivating connection-reuse/pooling as a genuine, measurable performance optimization.

COMMON MISTAKES:
- Establishing a NEW TCP connection for every individual request rather
  than reusing an existing one (HTTP keep-alive/connection pooling) —
  this pays the full handshake cost repeatedly, a real and avoidable
  latency tax, especially significant for high-latency network paths
  (e.g. mobile networks, cross-region requests).
- Choosing UDP for a use case that genuinely needs reliable, ordered
  delivery without implementing that reliability at the application
  layer — UDP's speed advantage comes SPECIFICALLY from omitting TCP's
  reliability machinery; using UDP for data that actually needs
  guaranteed, ordered delivery requires either reimplementing similar
  logic yourself or reconsidering whether TCP is actually the better
  fit for that specific use case.
- Assuming TCP's reliability guarantee means a `send()` call
  succeeding guarantees the DATA WAS ACTUALLY RECEIVED and PROCESSED
  by the remote application — TCP guarantees ordered, complete delivery
  to the RECEIVING OS's network stack; it says nothing about whether
  the receiving APPLICATION successfully processed that data, a
  distinction directly relevant to this repo's Distributed Systems
  Theory Notes L01's partial-failure discussion.
"""

import textwrap


# ------------------------------------------------------------------
# 1. The three-way handshake, illustrated step by step
# ------------------------------------------------------------------
THREE_WAY_HANDSHAKE = textwrap.dedent("""\
    Client                                          Server

      | ---- SYN (seq=X) ------------------------>  |
      |                                              |
      | <--- SYN-ACK (seq=Y, ack=X+1) ------------   |
      |                                              |
      | ---- ACK (ack=Y+1) ----------------------->  |
      |                                              |
      | <====== connection established =========>   |
      |                                              |
      | ---- actual application data ------------->  |

    This handshake costs AT LEAST one full round trip before ANY
    application data can be sent — directly explaining why a brand-new
    connection's first request is measurably slower than subsequent
    requests over an already-established, reused connection.
""")

# ------------------------------------------------------------------
# 2. Sequence numbers and reordering, simulated
# ------------------------------------------------------------------
def simulate_out_of_order_reassembly(received_packets: list[dict]) -> list[str]:
    # Packets arrive with sequence numbers, possibly OUT OF ORDER —
    # TCP reassembles them in the CORRECT order before delivery to the application
    sorted_packets = sorted(received_packets, key=lambda p: p["sequence_number"])
    return [p["data"] for p in sorted_packets]


def sequence_number_demo():
    print(THREE_WAY_HANDSHAKE)

    # Simulating packets arriving OUT OF ORDER (a realistic IP-level occurrence)
    received_out_of_order = [
        {"sequence_number": 3, "data": "World"},
        {"sequence_number": 1, "data": "Hello"},
        {"sequence_number": 2, "data": ", "},
        {"sequence_number": 4, "data": "!"},
    ]
    print("Packets arrived at the network layer in this ORDER:")
    print(f"  {[p['data'] for p in received_out_of_order]}")

    reassembled = simulate_out_of_order_reassembly(received_out_of_order)
    print(f"\nTCP reassembles using sequence numbers -> delivered to application as:")
    print(f"  {''.join(reassembled)}")
    print("  -> The APPLICATION never sees the out-of-order arrival at all —")
    print("     TCP's sequence-number-based reassembly handles this transparently.")


# ------------------------------------------------------------------
# 3. Sliding window flow control, illustrated
# ------------------------------------------------------------------
def sliding_window_demo():
    print("\nSliding window flow control:\n")
    scenarios = [
        {"receiver_state": "buffer mostly empty, processing fast", "advertised_window": 65536},
        {"receiver_state": "buffer filling up, processing slowly", "advertised_window": 4096},
        {"receiver_state": "buffer full", "advertised_window": 0},
    ]
    for s in scenarios:
        print(f"  Receiver state: {s['receiver_state']}")
        print(f"    Advertised window: {s['advertised_window']} bytes -> "
              f"sender may have at most this much UNACKNOWLEDGED data in flight\n")
    print("  -> A window of 0 tells the sender to PAUSE entirely until the")
    print("     receiver's buffer frees up and it advertises a larger window again —")
    print("     this is how a slow receiver prevents a fast sender from overwhelming it.")


if __name__ == "__main__":
    sequence_number_demo()
    sliding_window_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
An API gateway serving high-traffic mobile clients configures HTTP
keep-alive with connection pooling specifically to avoid paying TCP's
(and, for HTTPS, TLS's) handshake cost on every single request — mobile
networks in particular have relatively high round-trip latency compared
to wired connections, making handshake avoidance a measurably
significant performance optimization; monitoring shows p50 latency for
requests over REUSED connections is often several times lower than for
requests requiring a fresh connection setup, a direct, quantifiable
consequence of this lesson's three-way handshake mechanics.
"""
