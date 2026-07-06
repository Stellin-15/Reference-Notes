# ============================================================
# L07: Layer 2 Scaling Solutions — Rollups, Sidechains, and State Channels
# ============================================================
# WHAT: Why base-layer blockchains (Ethereum's "Layer 1") have an
#       inherent THROUGHPUT ceiling, and the main Layer 2 approaches
#       (optimistic rollups, zero-knowledge rollups, state channels)
#       that scale beyond it while still inheriting the base layer's security.
# WHY: L01-L02's consensus mechanisms directly explain WHY blockchain
#      throughput is fundamentally limited (every node must verify
#      everything) — this lesson covers the actual engineering
#      solutions built to work around that limitation.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
THE SCALABILITY PROBLEM stems directly from L01-L02's own security
model: because EVERY node must independently verify EVERY transaction
to maintain the network's trustless security guarantees, the network's
total throughput is fundamentally capped by what a SINGLE, reasonably-
provisioned node can process and verify — this is a direct, structural
consequence of the same design that makes blockchains trustless and
decentralized in the first place; you cannot simply "add more servers"
the way a traditional web service scales, without weakening this core
verification guarantee. Ethereum's Layer 1 historically processed only
around 15-30 transactions per second — a fraction of what centralized
payment networks handle, a genuine, well-known limitation.

OPTIMISTIC ROLLUPS scale by moving MOST computation OFF the base layer
(Layer 1) onto a separate Layer 2 network, which processes transactions
much faster and cheaper, then periodically posts a SUMMARY (a batch of
transaction results) back to Layer 1 — the "optimistic" part: the rollup
ASSUMES these batched results are valid by default, WITHOUT proving it
upfront, but provides a CHALLENGE PERIOD (commonly about a week) during
which anyone can submit a FRAUD PROOF demonstrating a batch was invalid,
which would revert it — this design trades a WITHDRAWAL DELAY (funds
moving back to Layer 1 must wait out the challenge period, in case a
fraud proof is submitted) for significantly higher throughput and lower cost per transaction.

ZERO-KNOWLEDGE (ZK) ROLLUPS take a different, cryptographically stronger
approach: instead of ASSUMING validity and allowing a challenge period,
a ZK rollup generates a CRYPTOGRAPHIC PROOF (a "validity proof") that
MATHEMATICALLY DEMONSTRATES the batch of transactions was processed
correctly, submitted ALONGSIDE the batch itself — Layer 1 can verify
this proof QUICKLY (verifying a ZK proof is computationally cheap, even
though GENERATING it is expensive) without needing to re-execute every
individual transaction, and WITHOUT needing a challenge period at all,
since validity is proven UPFRONT rather than assumed — this means
withdrawals from ZK rollups can be nearly INSTANT (once the proof is
verified) rather than requiring optimistic rollups' week-long challenge
window, at the cost of the more complex cryptography and computational
overhead involved in generating these proofs.

STATE CHANNELS take a THIRD approach for a specific use case (frequent,
repeated transactions between the SAME small set of participants):
participants open a channel by locking funds in a Layer 1 smart
contract, then conduct MANY transactions BETWEEN THEMSELVES entirely
OFF-CHAIN (simply exchanging cryptographically signed messages
directly), with ONLY the channel's OPENING and FINAL CLOSING state
ever actually touching Layer 1 — this is extremely efficient for its
specific use case (e.g. a payment channel between two parties making
many small, frequent payments) but doesn't generalize well to
interactions involving arbitrary, changing sets of participants the way
rollups do.

PRODUCTION USE CASE:
A decentralized exchange deployed on a ZK-rollup-based Layer 2 (e.g.
zkSync or StarkNet) processes thousands of trades per second at a
fraction of Ethereum Layer 1's per-transaction gas cost, while still
inheriting Layer 1's underlying security guarantees — since every
batch of Layer 2 transactions is accompanied by a validity proof
verified on Layer 1, users don't need to trust the Layer 2 operator's
honesty directly; they're protected by the SAME cryptographic and
consensus security (L01-L02) as Layer 1 itself, just with dramatically improved throughput and cost.

COMMON MISTAKES:
- Assuming Layer 2 solutions sacrifice Layer 1's security guarantees
  entirely for speed — both optimistic and ZK rollups are SPECIFICALLY
  designed to inherit Layer 1's security (via fraud proofs or validity
  proofs respectively), a meaningfully different security model than a
  fully independent, separately-secured blockchain (a "sidechain")
  would provide.
- Withdrawing funds from an OPTIMISTIC rollup and being surprised by the
  week-long delay — this challenge period is a DELIBERATE, necessary
  part of the security model (giving time for fraud proofs to be
  submitted), not an arbitrary inconvenience or a bug.
- Choosing a state channel architecture for a use case involving
  frequent changes in WHO is participating (rather than a fixed, small
  set of known participants) — state channels are specifically optimized
  for repeated interaction between a STABLE set of parties; they don't
  generalize well to open, dynamic participation the way rollups do.
"""

import textwrap


LAYER2_ARCHITECTURE_COMPARISON = textwrap.dedent("""\
    Optimistic Rollup:
      Layer 2 processes transactions FAST and CHEAP
      -> Periodically posts a BATCH SUMMARY to Layer 1
      -> ASSUMED valid by default (a "challenge period," ~1 week,
         allows anyone to submit a FRAUD PROOF if something's wrong)
      -> Withdrawal to Layer 1: must wait out the challenge period

    Zero-Knowledge (ZK) Rollup:
      Layer 2 processes transactions FAST and CHEAP
      -> Generates a CRYPTOGRAPHIC VALIDITY PROOF alongside the batch
      -> Layer 1 verifies this proof QUICKLY (cheap to verify, expensive
         to generate) — validity is PROVEN upfront, no assumption needed
      -> Withdrawal to Layer 1: near-INSTANT once the proof is verified

    State Channel:
      Fixed set of participants lock funds in a Layer 1 contract
      -> Conduct MANY transactions OFF-CHAIN, directly between themselves
      -> ONLY the opening and final closing state ever touch Layer 1
      -> Extremely efficient for repeated interaction between KNOWN,
         STABLE parties; doesn't generalize to open/dynamic participation
""")


def throughput_comparison_demo():
    print(LAYER2_ARCHITECTURE_COMPARISON)
    comparisons = [
        {"layer": "Ethereum Layer 1", "tps": 15, "withdrawal_delay": "N/A (native)"},
        {"layer": "Optimistic Rollup", "tps": 2000, "withdrawal_delay": "~7 days (challenge period)"},
        {"layer": "ZK Rollup", "tps": 2000, "withdrawal_delay": "Minutes to hours (proof verification)"},
    ]
    print("Illustrative throughput/withdrawal comparison:\n")
    for c in comparisons:
        print(f"  {c['layer']}: ~{c['tps']} tx/sec, withdrawal delay: {c['withdrawal_delay']}")


if __name__ == "__main__":
    throughput_comparison_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A gaming platform built on a ZK-rollup Layer 2 lets players make
frequent, low-value in-game transactions (item trades, small purchases)
at a cost of fractions of a cent each — a use case that would be
entirely impractical on Ethereum Layer 1 directly, where gas costs for
each individual transaction could easily exceed the transaction's own
value — while still allowing players to withdraw their assets back to
Layer 1 relatively quickly (thanks to ZK rollups' validity-proof-based,
non-optimistic security model) whenever they want stronger, base-layer custody of their holdings.
"""
