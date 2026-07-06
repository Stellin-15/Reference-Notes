# ============================================================
# L05: dApp Architecture — How Frontends Actually Talk to Smart Contracts
# ============================================================
# WHAT: The full architecture of a decentralized application (dApp) —
#       how a normal web frontend (this repo's Full-Stack & Frontend
#       Essentials Notes) connects to a user's wallet, reads/writes
#       blockchain state, and why dApps still typically rely on
#       CENTRALIZED infrastructure for parts of their stack.
# WHY: L01-L04 covered the blockchain/smart-contract layer in isolation.
#      A real dApp needs a FRONTEND users actually interact with — this
#      lesson bridges this domain's blockchain concepts to this repo's
#      existing frontend coverage.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
A DAPP'S FRONTEND is, architecturally, mostly a NORMAL web application
(built with React or similar — this repo's Full-Stack & Frontend
Essentials Notes L01) — the genuinely NEW piece is a WALLET CONNECTION
(L06 covers wallets in depth): the frontend uses a library (commonly
ethers.js or web3.js) to connect to the user's browser-based wallet
extension (e.g. MetaMask), which acts as the bridge between the web
page and the user's actual blockchain account/private key — the
frontend NEVER has direct access to the user's private key; it only
REQUESTS that the wallet sign and submit transactions on the user's behalf.

READING BLOCKCHAIN STATE (calling a smart contract's `view` function,
L03) is RELATIVELY CHEAP and requires no gas — a dApp frontend can
query contract state frequently, similar in spirit to a normal API
GET request, though typically via a NODE PROVIDER (a service like
Infura or Alchemy that runs Ethereum nodes and provides API access to
them) rather than the frontend running its own full blockchain node
directly — running a full node yourself is possible but
resource-intensive, so most dApps rely on these THIRD-PARTY node
providers as infrastructure, an important, often-overlooked
CENTRALIZATION point in an otherwise "decentralized" application's actual architecture.

WRITING BLOCKCHAIN STATE (calling a NON-view function, L03) requires the
USER to explicitly APPROVE and pay for the transaction via their wallet
— the frontend CONSTRUCTS the transaction (which function to call, what
arguments to pass) and hands it to the wallet, which shows the user a
confirmation prompt (including the estimated gas cost, L04) — the user
must actively approve before anything is submitted to the network — this
is a FUNDAMENTALLY different interaction pattern than a normal web
app's "click a button, the backend just does it" flow, and requires
UI/UX design that clearly communicates this multi-step,
user-confirmation-required process, including handling the REAL
possibility that a transaction takes noticeable time (waiting for
block inclusion and confirmations, L02) rather than resolving instantly.

WHY MOST DAPPS AREN'T "FULLY DECENTRALIZED" IN PRACTICE: beyond relying
on centralized node providers (as noted above), most dApp frontends are
STILL hosted on traditional centralized infrastructure (a normal web
server or CDN, this repo's System Design Case Studies Notes' infra
lessons) — the SMART CONTRACT logic and the resulting on-chain state are
genuinely decentralized (per L01-L02's guarantees), but the WEBSITE
serving the frontend code, and often the off-chain data/APIs the
frontend also relies on for a good user experience (search, notifications,
analytics), are typically conventional, centralized infrastructure —
understanding this distinction (decentralized WHAT, specifically) is
important for accurately reasoning about a dApp's actual trust/failure
model, rather than assuming "it's a dApp" means every layer is decentralized.

PRODUCTION USE CASE:
A decentralized exchange (DEX) frontend, built as a normal React
application (Full-Stack & Frontend Essentials Notes L01) and hosted on a
standard CDN, connects to a user's MetaMask wallet to let them approve
and submit trade transactions — the ACTUAL trade execution and resulting
balance changes are genuinely decentralized (governed by immutable
smart contract logic, L03, verified by the whole network, L02) — but if
the DEX's own frontend hosting infrastructure goes down, or their
chosen node provider (Infura/Alchemy) has an outage, users may be
unable to INTERACT with the underlying smart contract at all through
that specific frontend, even though the smart contract and its data remain fully intact and unaffected on-chain.

COMMON MISTAKES:
- Assuming a dApp is "fully decentralized" simply because it interacts
  with a blockchain — the FRONTEND hosting, NODE PROVIDER
  infrastructure, and often supplementary off-chain services remain
  real, centralized points of potential failure or control, distinct
  from the genuinely decentralized smart contract layer itself.
- Designing dApp UX as if blockchain writes complete INSTANTLY, the way
  a typical API call does — failing to account for the REAL wait time
  (block inclusion, confirmations) and REQUIRED user wallet interaction
  produces a confusing, seemingly-broken user experience for anyone
  expecting typical web-app response times.
- Having the frontend attempt to handle a user's PRIVATE KEY directly,
  rather than delegating ALL signing operations to the user's wallet —
  this is both a severe security anti-pattern (private key exposure)
  and unnecessary, since the wallet-connection architecture exists
  specifically to avoid the frontend ever needing direct private key access.
"""

import textwrap


DAPP_ARCHITECTURE_DIAGRAM = textwrap.dedent("""\
    Full dApp architecture, end to end:

    [User's browser: React frontend, Full-Stack & Frontend Essentials Notes L01]
                    |
                    v
    [Wallet extension (MetaMask)] <- holds the user's private key,
                    |                NEVER exposed to the frontend directly
                    v
    [Node provider (Infura/Alchemy)] <- a REAL, often-overlooked
                    |                   centralization point
                    v
    [Ethereum network: smart contract execution, L03-L04]
                    |
                    v
    [Blockchain state, verified by the whole network, L01-L02]

    The frontend's OWN hosting (a normal web server/CDN) is ALSO
    typically centralized — the genuinely decentralized part is
    specifically the SMART CONTRACT layer and resulting on-chain state.
""")

WALLET_INTERACTION_EXAMPLE = textwrap.dedent("""\
    // Simplified ethers.js example — connecting to a user's wallet
    // and calling a smart contract function

    import { ethers } from 'ethers';

    async function connectWallet() {
      // Requests the user's PERMISSION to connect — the frontend never
      // sees or handles the actual private key at any point
      const provider = new ethers.BrowserProvider(window.ethereum);
      const signer = await provider.getSigner();
      return signer;
    }

    async function checkBalance(contract) {
      // A VIEW function call — free, no gas cost, no user confirmation needed
      const balance = await contract.getBalance(userAddress);
      return balance;
    }

    async function withdrawFunds(contract, amount) {
      // A NON-VIEW function call — the wallet will show the user a
      // confirmation prompt with estimated gas cost BEFORE anything
      // is submitted; this call doesn't resolve until the user approves
      // AND the transaction is mined/confirmed (can take real, noticeable time)
      const tx = await contract.withdraw(amount);
      await tx.wait();   // waits for on-chain confirmation
      console.log('Withdrawal confirmed on-chain');
    }
""")


if __name__ == "__main__":
    print(DAPP_ARCHITECTURE_DIAGRAM)
    print(WALLET_INTERACTION_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
During a widely-publicized Infura outage in 2020, numerous dApps
(including MetaMask itself, which relied on Infura by default) became
effectively UNUSABLE for many users — even though the underlying smart
contracts and blockchain state were entirely unaffected and fully
functional — a stark, real-world demonstration that a dApp's actual
resilience depends on its FULL stack (frontend hosting, node provider,
wallet infrastructure), not merely on the genuine decentralization of
its smart contract layer, directly illustrating this lesson's core distinction.
"""
