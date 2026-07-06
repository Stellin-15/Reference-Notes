# ============================================================
# L06: Wallets and Key Management
# ============================================================
# WHAT: What a crypto "wallet" actually is (it doesn't store coins — it
#       stores KEYS), public/private key cryptography as it applies to
#       blockchain accounts, seed phrases, and the genuinely severe,
#       irreversible consequences of key mismanagement.
# WHY: L05 mentioned wallets as the bridge between a dApp frontend and a
#      user's blockchain account. This lesson covers what a wallet
#      actually IS and why key management is such a uniquely
#      high-stakes concern in this domain specifically.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
A WALLET DOES NOT "STORE" CRYPTOCURRENCY — this is a common and
important misconception: the actual balance/ownership record lives
ENTIRELY on the blockchain itself (as blockchain state, L01) — a wallet
stores your PRIVATE KEY, a piece of cryptographic secret data that
proves you have the AUTHORITY to sign transactions moving funds
associated with your PUBLIC ADDRESS (derived mathematically from that
private key). This distinction matters enormously: "losing your wallet"
doesn't mean your funds disappeared from the blockchain — it means
you've lost the ONLY key capable of proving ownership and authorizing
future transactions, which for all practical purposes makes those funds
PERMANENTLY, IRRECOVERABLY inaccessible, since there's no central
authority to reset a "forgotten password" the way a traditional bank account has.

PUBLIC/PRIVATE KEY CRYPTOGRAPHY underlies this entire system: a PRIVATE
KEY is a large random number kept SECRET; the corresponding PUBLIC KEY
(and from it, the public ADDRESS) is mathematically DERIVED from the
private key via a ONE-WAY function (computationally easy in one
direction, computationally infeasible to reverse) — this lets anyone
VERIFY that a transaction was legitimately signed by the holder of a
specific private key (by checking the signature against the public
key) WITHOUT that person ever revealing their actual private key.

SEED PHRASES (typically 12 or 24 common English words, following the
BIP-39 standard) are a HUMAN-READABLE, more easily-backed-up encoding of
the underlying cryptographic randomness that a private key (and,
via hierarchical deterministic derivation, potentially MANY private
keys/accounts) is generated FROM — this is why seed phrases are treated
with EXTREME security sensitivity: anyone who obtains your seed phrase
can regenerate your PRIVATE KEYS and control every account derived from
it, completely independent of your original wallet software or device
— this is fundamentally different from a traditional password, which
is typically tied to a specific service's own authentication system
that CAN be reset by that service if compromised.

HOT WALLETS VS COLD WALLETS represent a genuine security/convenience
tradeoff: a HOT WALLET (a browser extension like MetaMask, a mobile
app) keeps private keys accessible on an INTERNET-CONNECTED device,
convenient for frequent use but exposed to online attack vectors
(malware, phishing, compromised devices); a COLD WALLET (a dedicated
hardware device, or even a private key generated and stored entirely
offline) keeps keys COMPLETELY OFFLINE, dramatically reducing remote
attack exposure at the cost of convenience — a common practical pattern
is using a hot wallet for smaller, frequently-used amounts and a cold
wallet for larger, long-term holdings, directly mirroring the "don't
carry your life savings in your physical wallet" intuition from traditional finance.

PRODUCTION USE CASE:
A cryptocurrency exchange stores the VAST MAJORITY of user funds in
COLD STORAGE (offline, air-gapped systems, often requiring MULTIPLE
authorized personnel to physically access and approve a withdrawal) —
keeping only a small operational "hot wallet" balance online to serve
routine, immediate withdrawal requests — this architecture directly
limits the maximum possible loss from a successful online attack to
whatever fraction of total funds the hot wallet holds, rather than
exposing the exchange's ENTIRE holdings to online attack vectors simultaneously.

COMMON MISTAKES:
- Storing a seed phrase digitally (in a text file, a photo, a password
  manager not specifically designed and secured for this purpose,
  or especially in cloud storage/email) — this creates a real online
  attack surface for what's meant to be an OFFLINE-ONLY secret; standard
  practice is writing it down physically and storing it securely
  offline, precisely BECAUSE of this risk.
- Sharing a seed phrase with ANYONE, under ANY circumstances, including
  someone claiming to be "support staff" from a wallet provider or
  exchange — NO legitimate service will ever need or ask for your seed
  phrase; this specific social-engineering attack vector is one of the
  most common ways users lose funds, and no legitimate reason to share it ever exists.
- Treating a "forgot my private key/seed phrase" situation as
  recoverable the way a forgotten traditional password is — there is
  NO central authority capable of resetting blockchain account access;
  this loss is, for all practical purposes, PERMANENT, a fundamentally
  different failure mode than nearly any traditional account-recovery scenario.
"""

import hashlib
import secrets


# ------------------------------------------------------------------
# 1. Illustrating public/private key derivation (simplified, NOT cryptographically real)
# ------------------------------------------------------------------
def generate_illustrative_keypair() -> tuple[str, str]:
    """A SIMPLIFIED illustration only — real blockchain wallets use
    elliptic curve cryptography (secp256k1 for Bitcoin/Ethereum), NOT
    this simple hash-based stand-in. Never use this for anything real."""
    private_key = secrets.token_hex(32)   # a large, random secret
    # The public key is DERIVED from the private key via a one-way function —
    # illustrated here with a simple hash (NOT how real EC cryptography works,
    # but captures the "easy one direction, infeasible to reverse" property)
    public_key = hashlib.sha256(private_key.encode()).hexdigest()
    return private_key, public_key


def keypair_demo():
    private_key, public_key = generate_illustrative_keypair()
    print(f"Private key (KEEP SECRET, never share): {private_key[:16]}...")
    print(f"Public key/address (safe to share publicly): {public_key[:16]}...")
    print("\n  -> The public key is derived FROM the private key, but this")
    print("     derivation is computationally infeasible to REVERSE —")
    print("     you cannot recover a private key from its public key alone.")


# ------------------------------------------------------------------
# 2. Hot wallet vs cold wallet risk model
# ------------------------------------------------------------------
def wallet_strategy_illustration():
    print("\nHot wallet vs cold wallet — a practical exchange strategy:\n")
    total_funds = 100_000_000   # illustrative total exchange holdings
    hot_wallet_pct = 0.02       # only 2% kept in online "operational" hot wallet
    hot_wallet_amount = total_funds * hot_wallet_pct
    cold_storage_amount = total_funds - hot_wallet_amount

    print(f"  Total funds: ${total_funds:,}")
    print(f"  Hot wallet (online, convenient, attack-exposed): ${hot_wallet_amount:,.0f} ({hot_wallet_pct:.0%})")
    print(f"  Cold storage (offline, air-gapped, multi-person approval): ${cold_storage_amount:,.0f} ({1-hot_wallet_pct:.0%})")
    print("\n  -> Even a WORST-CASE successful hot-wallet compromise limits")
    print(f"     losses to ${hot_wallet_amount:,.0f}, not the full ${total_funds:,} —")
    print("     a direct, deliberate risk-limiting architecture decision.")


if __name__ == "__main__":
    keypair_demo()
    wallet_strategy_illustration()

"""
PRODUCTION CONTEXT EXAMPLE:
A widely-reported pattern in cryptocurrency losses involves users
falling for phishing sites that closely mimic a legitimate wallet
provider's interface, tricking them into entering their seed phrase —
the moment this happens, the attacker can regenerate the user's private
keys and drain funds, with NO recovery mechanism available since
blockchain transactions (once confirmed, per L02) are irreversible and
there is no central authority to intervene — this is why legitimate
wallet software and educational materials consistently emphasize
NEVER entering a seed phrase anywhere except the original, trusted
wallet application itself, and treat any request for it as an
immediate, unambiguous red flag.
"""
