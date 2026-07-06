# ============================================================
# L01: Blockchain Fundamentals — Blocks, Hashing, and the Chain
# ============================================================
# WHAT: The core data structure underlying every blockchain — how
#       cryptographic hashing links blocks together into an
#       effectively TAMPER-EVIDENT chain, and why this specific
#       property is the foundational building block everything else in
#       this domain builds on.
# WHY: This repo's Distributed Systems Theory Notes covers consensus
#      (Paxos/Raft) for TRUSTED, permissioned clusters. Blockchain
#      solves a related but genuinely different problem: achieving
#      agreement among UNTRUSTED, potentially adversarial participants
#      with no central authority — this domain covers that different problem space.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
A CRYPTOGRAPHIC HASH FUNCTION (e.g. SHA-256) takes ARBITRARY input data
and produces a FIXED-SIZE, DETERMINISTIC output (the "hash") with three
critical properties: the SAME input always produces the SAME hash
(determinism); it's COMPUTATIONALLY INFEASIBLE to find TWO different
inputs producing the SAME hash (collision resistance); and even a
TINY change to the input (a single flipped bit) produces a COMPLETELY
DIFFERENT, unpredictable hash (the "avalanche effect") — this LAST
property is exactly what makes blockchain's tamper-evidence work: you
CANNOT modify data and produce a hash that "looks close enough" to the original.

A BLOCK bundles a set of transactions/data TOGETHER WITH the HASH OF
THE PREVIOUS BLOCK — this is the crucial link that forms "the chain":
block N contains, as part of its own data, the hash of block N-1 — which
means block N's OWN hash is computed FROM data that includes block
N-1's hash. If ANYONE tries to modify data in an EARLIER block (block
N-1), that block's hash CHANGES (per the avalanche effect above) —
but block N still references the OLD hash of block N-1, so the chain
is now BROKEN/INVALID at that point — and this INVALIDATES every
subsequent block as well, since EACH one references the previous
block's hash, cascading forward through the entire chain. This is
WHY tampering with historical blockchain data is "tamper-evident":
it doesn't PREVENT tampering technically, but it makes tampering
IMMEDIATELY DETECTABLE by anyone who re-verifies the chain's hash links.

WHY THIS ALONE ISN'T SUFFICIENT FOR A DISTRIBUTED SYSTEM: hash-chaining
alone only protects a SINGLE COPY of the chain from undetected
tampering — it says nothing about which of MULTIPLE, potentially
conflicting copies of a chain (held by different participants) should
be considered the "real" one, especially when participants don't
trust each other and there's no central authority to simply decide —
THIS is the genuinely hard problem CONSENSUS MECHANISMS (L02) solve:
getting a decentralized network of MUTUALLY UNTRUSTING participants to
agree on ONE canonical version of the chain, which is a fundamentally
harder variant of the consensus problem this repo's Distributed
Systems Theory Notes L02-L03 covered for TRUSTED clusters (Paxos/Raft
explicitly assume nodes are not maliciously lying, only potentially
crash-failing — blockchain consensus must handle actively adversarial
participants, a strictly harder problem).

A MERKLE TREE is the specific data structure blockchains typically use
to efficiently summarize ALL of a block's transactions into a SINGLE
hash (the "Merkle root"): transactions are hashed in pairs, those
pair-hashes are hashed in pairs again, repeating until a single root
hash remains — this lets you PROVE a specific transaction is included
in a block by providing only a SMALL number of intermediate hashes
(a "Merkle proof"), rather than needing the ENTIRE block's transaction
list, a genuinely efficient verification mechanism for light clients that don't store full blockchain data.

PRODUCTION USE CASE:
Bitcoin's blockchain lets anyone independently VERIFY the ENTIRE
transaction history is unaltered by re-computing hash links from the
very first block ("genesis block") forward — if even a single historical
transaction were altered, every subsequent block's hash-chain
verification would fail immediately, making the tampering
mathematically detectable by any participant, without requiring trust
in any central authority to simply assert the data hasn't been changed.

COMMON MISTAKES:
- Believing blockchain "prevents" tampering — it does NOT prevent
  someone from attempting to modify historical data; it makes such
  tampering IMMEDIATELY, MATHEMATICALLY DETECTABLE by anyone re-verifying
  the chain, which is a meaningfully different (and more precise) guarantee.
- Conflating "hash chaining makes tampering detectable" with "the
  network has agreed on which chain is canonical" — these are TWO
  SEPARATE mechanisms; hash-chaining alone doesn't resolve disagreements
  between different participants' copies of the chain, which is
  specifically what consensus mechanisms (L02) exist to do.
- Assuming blockchain solves the SAME problem as this repo's
  Distributed Systems Theory Notes' consensus algorithms (Paxos/Raft) —
  those assume a TRUSTED, permissioned set of nodes; blockchain
  consensus mechanisms are specifically designed for UNTRUSTED,
  potentially adversarial, permissionless participation — a strictly harder and differently-shaped problem.
"""

import hashlib
import json


# ------------------------------------------------------------------
# 1. A minimal blockchain — hash-linked blocks, tamper detection
# ------------------------------------------------------------------
def compute_hash(block_data: dict) -> str:
    block_string = json.dumps(block_data, sort_keys=True)
    return hashlib.sha256(block_string.encode()).hexdigest()


class Block:
    def __init__(self, index: int, transactions: list[str], previous_hash: str):
        self.index = index
        self.transactions = transactions
        self.previous_hash = previous_hash
        self.hash = compute_hash({
            "index": index, "transactions": transactions, "previous_hash": previous_hash
        })


def build_chain_demo():
    genesis = Block(0, ["genesis block"], previous_hash="0" * 64)
    block1 = Block(1, ["Alice pays Bob 5 coins"], previous_hash=genesis.hash)
    block2 = Block(2, ["Bob pays Charlie 2 coins"], previous_hash=block1.hash)

    chain = [genesis, block1, block2]
    print("Original chain:")
    for block in chain:
        print(f"  Block {block.index}: hash={block.hash[:16]}..., "
              f"previous_hash={block.previous_hash[:16]}...")
    return chain


def verify_chain(chain: list[Block]) -> bool:
    for i in range(1, len(chain)):
        current, previous = chain[i], chain[i - 1]
        if current.previous_hash != previous.hash:
            print(f"  INVALID at block {current.index}: "
                  f"expected previous_hash={previous.hash[:16]}..., "
                  f"but block references {current.previous_hash[:16]}...")
            return False
        # Also re-verify the block's OWN hash matches its actual content
        recomputed = compute_hash({
            "index": current.index, "transactions": current.transactions,
            "previous_hash": current.previous_hash,
        })
        if recomputed != current.hash:
            print(f"  INVALID at block {current.index}: content has been TAMPERED WITH")
            return False
    return True


def tampering_detection_demo():
    chain = build_chain_demo()

    print(f"\nVerifying original chain: {'VALID' if verify_chain(chain) else 'INVALID'}")

    print("\nAn attacker tampers with block 1's transaction data:")
    chain[1].transactions = ["Alice pays Bob 500 coins"]   # tampered!
    # Note: the attacker did NOT recompute block 1's hash to match this change

    print(f"Verifying TAMPERED chain: {'VALID' if verify_chain(chain) else 'INVALID'}")
    print("\n  -> The tampering was IMMEDIATELY detected — this is what")
    print("     'tamper-evident' means: the attack isn't PREVENTED, but")
    print("     it's mathematically impossible to hide from verification.")


if __name__ == "__main__":
    tampering_detection_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A blockchain-based supply chain tracking system lets any participant
(a retailer, an auditor, a regulator) independently verify that a
product's recorded chain of custody hasn't been altered after the fact
— by re-computing hash links from the product's original entry point
forward, any party can detect tampering WITHOUT needing to trust the
original recording party or any central intermediary — a genuinely
useful property distinct from a traditional centralized database, where
verifying "this record hasn't been silently altered" fundamentally
requires trusting whoever controls that central database.
"""
