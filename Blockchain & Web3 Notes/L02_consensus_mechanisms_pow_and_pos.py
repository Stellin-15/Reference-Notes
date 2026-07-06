# ============================================================
# L02: Consensus Mechanisms — Proof of Work and Proof of Stake
# ============================================================
# WHAT: How a decentralized, UNTRUSTED network of participants agrees
#       on ONE canonical blockchain — Proof of Work (Bitcoin's original
#       mechanism) and Proof of Stake (Ethereum's current mechanism),
#       and the genuinely different security/resource models each relies on.
# WHY: L01 covered how hash-chaining makes tampering DETECTABLE within
#      one copy of a chain. This lesson covers the actual mechanism
#      that resolves DISAGREEMENTS between different participants'
#      copies — the harder problem L01 explicitly left open.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
THE DOUBLE-SPEND PROBLEM is exactly what blockchain consensus must
solve: in a decentralized digital currency with no central bank, what
stops someone from spending the SAME coin twice by broadcasting two
conflicting transactions to different parts of the network
simultaneously? Without a trusted central authority to simply reject
the second spend, the network needs a way to agree on which of the two
conflicting transactions happened "first" — and to make it
GENUINELY EXPENSIVE for any single participant to unilaterally decide
this in their own favor.

PROOF OF WORK (PoW), Bitcoin's original mechanism, requires participants
("miners") to solve a COMPUTATIONALLY EXPENSIVE puzzle (finding a value,
called a "nonce," such that the block's hash meets a specific
difficulty target — e.g. starting with a certain number of zeros) before
their proposed block is accepted by the network — this puzzle is
DELIBERATELY hard to SOLVE but TRIVIALLY EASY to VERIFY once solved
(recomputing one hash to check it meets the target). The SECURITY
GUARANTEE: to successfully rewrite history (double-spend), an attacker
would need to REDO the computational work for every subsequent block
FASTER than the rest of the network combined can extend the REAL
chain — this becomes exponentially harder the more blocks have been
added since the transaction in question (this is WHY exchanges
typically wait for multiple "confirmations" before considering a
Bitcoin transaction final). PoW's well-known downside: it consumes
ENORMOUS amounts of real-world electricity, since the security model is
literally built on making attacks prohibitively expensive via genuine computational cost.

PROOF OF STAKE (PoS), Ethereum's current mechanism (since "The Merge"),
replaces computational work with ECONOMIC STAKE: participants
("validators") lock up a significant amount of the network's own
cryptocurrency as collateral, and are RANDOMLY SELECTED (weighted by
stake size) to propose and validate new blocks — the security guarantee
shifts from "attacking requires more computing power than everyone
else combined" to "attacking requires acquiring and risking losing an
enormous amount of staked cryptocurrency" — validators caught acting
maliciously (proposing conflicting blocks, validating invalid
transactions) have their staked funds "SLASHED" (partially or fully
destroyed) as an economic penalty. PoS's key advantage over PoW: it
uses DRAMATICALLY less energy, since there's no computational race — the
security model relies on economic incentive/penalty rather than raw computational cost.

WHY THIS RELATES TO THIS REPO'S CONSENSUS COVERAGE (Distributed Systems
Theory Notes L02-L03): both PoW and PoS solve the SAME abstract problem
(agreement among distributed participants) that Paxos/Raft solve, but
under a FUNDAMENTALLY HARDER threat model — Paxos/Raft assume
participants might CRASH but won't actively LIE or attempt to
manipulate the protocol for personal gain (a "crash fault tolerant"
model); blockchain consensus must tolerate a certain fraction of
ACTIVELY MALICIOUS, incentive-driven participants (a "Byzantine fault
tolerant" model, named after the Byzantine Generals Problem) — this
distinction is exactly why blockchain consensus mechanisms look so
different from and are more resource-intensive than Raft/Paxos, despite
solving conceptually related problems.

PRODUCTION USE CASE:
When a Bitcoin transaction is included in a newly-mined block, exchanges
and merchants typically wait for several additional blocks to be
mined ON TOP of it ("confirmations") before considering the payment
final — this is a direct, practical response to PoW's probabilistic
security model: the more blocks added after a transaction, the more
computational work an attacker would need to REDO to reverse it,
making reversal exponentially less likely (though never mathematically impossible) with each additional confirmation.

COMMON MISTAKES:
- Treating blockchain transaction finality as INSTANT and ABSOLUTE the
  moment a transaction appears in a block — PoW-based chains
  specifically provide only PROBABILISTIC finality that strengthens
  with additional confirmations, not an instant, absolute guarantee.
- Assuming Proof of Stake is "less secure" than Proof of Work simply
  because it doesn't consume as much energy — PoS's security model is
  GENUINELY DIFFERENT (economic slashing risk vs computational cost),
  not merely a weaker version of the same idea; comparing them requires
  understanding what EACH mechanism's threat model and incentive
  structure actually protects against.
- Confusing blockchain consensus (Byzantine fault tolerant, handling
  actively malicious participants) with this repo's Distributed
  Systems Theory Notes' Paxos/Raft consensus (crash fault tolerant,
  assuming honest-but-possibly-failing participants) — these solve
  related problems under GENUINELY different threat models, which
  directly explains why their mechanisms and resource costs differ so substantially.
"""

import hashlib


# ------------------------------------------------------------------
# 1. Proof of Work — finding a nonce that meets a difficulty target
# ------------------------------------------------------------------
def mine_block(block_data: str, difficulty: int) -> tuple[int, str]:
    target_prefix = "0" * difficulty
    nonce = 0
    while True:
        candidate = f"{block_data}{nonce}"
        hash_result = hashlib.sha256(candidate.encode()).hexdigest()
        if hash_result.startswith(target_prefix):
            return nonce, hash_result
        nonce += 1


def proof_of_work_demo():
    print("Proof of Work — mining (finding a valid nonce):\n")
    for difficulty in [3, 5]:
        nonce, block_hash = mine_block("block_data_example", difficulty)
        print(f"  Difficulty {difficulty} (hash must start with "
              f"{'0' * difficulty}): found nonce={nonce} after {nonce+1} attempts")
        print(f"    Resulting hash: {block_hash}")
    print("\n  -> Higher difficulty requires EXPONENTIALLY more attempts to")
    print("     find a valid nonce — this is the 'computationally expensive")
    print("     to solve, trivial to verify' asymmetry PoW's security relies on.")


# ------------------------------------------------------------------
# 2. Proof of Stake — weighted random validator selection + slashing
# ------------------------------------------------------------------
import random


def select_validator(validators: dict[str, float]) -> str:
    total_stake = sum(validators.values())
    pick = random.uniform(0, total_stake)
    cumulative = 0
    for validator, stake in validators.items():
        cumulative += stake
        if pick <= cumulative:
            return validator
    return list(validators.keys())[-1]


def proof_of_stake_demo():
    random.seed(42)
    validators = {"validator_A": 1000, "validator_B": 500, "validator_C": 100}

    print("\nProof of Stake — weighted random validator selection:\n")
    selections: dict[str, int] = {v: 0 for v in validators}
    for _ in range(1000):
        chosen = select_validator(validators)
        selections[chosen] += 1

    for validator, stake in validators.items():
        expected_pct = stake / sum(validators.values()) * 100
        actual_pct = selections[validator] / 10
        print(f"  {validator} (stake={stake}): expected ~{expected_pct:.1f}% of "
              f"selections, got {actual_pct:.1f}%")

    print("\nSlashing — the economic penalty for malicious behavior:")
    print("  validator_A proposes TWO conflicting blocks (double-signing)")
    print("  -> Network detects this and SLASHES a significant portion of")
    print("     validator_A's staked funds — the economic deterrent that")
    print("     replaces PoW's computational cost as the security mechanism.")


if __name__ == "__main__":
    proof_of_work_demo()
    proof_of_stake_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
Ethereum's 2022 transition from Proof of Work to Proof of Stake ("The
Merge") reduced the network's total energy consumption by over 99%,
replacing PoW's "miners competing via computational work" security
model with PoS's "validators risking staked ETH" model — this was a
genuinely significant, closely-watched engineering achievement
specifically because it required changing the network's FUNDAMENTAL
consensus/security mechanism while the network was live and carrying
substantial real economic value, without any interruption or loss of
the tamper-evidence guarantees L01 covers.
"""
