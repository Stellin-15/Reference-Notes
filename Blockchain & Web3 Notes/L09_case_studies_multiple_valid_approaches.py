"""
WHAT: Four realistic Web3/blockchain architecture problems, each solved
      with THREE genuinely different, individually defensible approaches
      drawn from L01-L08 -- with an explicit comparison table and
      reasoning for why each answer is valid under different
      constraints.
WHY:  "On-chain or off-chain," "which L2," "how paranoid should key
      management be" are all questions L01-L08 gave you real tools for,
      not one universal answer -- this lesson is about the decision
      process under real cost, trust, and security constraints.
LEVEL: Capstone -- read after L01-L08.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L08's concepts.
"""

# ============================================================================
# CASE STUDY 1 — DECIDING WHAT DATA BELONGS ON-CHAIN VS. OFF-CHAIN FOR A
# DAPP
# ============================================================================
#
# SETUP: a decentralized marketplace dApp needs to store product
# listings (title, description, images) and transaction records --
# deciding what genuinely needs to be on-chain versus off-chain (L04-L05).
#
# ------------------------------------------------------------------------
# APPROACH A: Store everything on-chain (listings, images-as-data,
# transaction history, all of it)
# ------------------------------------------------------------------------
#   WHY VALID: maximizes decentralization and immutability guarantees --
#   every piece of data benefits from the blockchain's tamper-resistance
#   and availability properties, with no reliance on any off-chain
#   system at all.
#   COST: per L04's gas-cost discussion, on-chain storage is EXTREMELY
#   expensive relative to conventional storage -- storing images or
#   lengthy descriptions on-chain costs orders of magnitude more in gas
#   fees than the data is realistically worth, and blockchain storage
#   isn't designed or priced for large binary data at all; this
#   approach is generally economically nonviable for anything beyond
#   small, essential data.
#
# ------------------------------------------------------------------------
# APPROACH B: Store only ESSENTIAL transactional/ownership data on-
# chain (who owns what, transaction records, a content hash), with
# actual content (images, descriptions) stored off-chain (e.g. IPFS or
# a conventional database), referenced by the on-chain hash (L04-L05)
# ------------------------------------------------------------------------
#   WHY VALID: per L04-L05, this directly addresses A's cost problem --
#   only the data that GENUINELY needs blockchain's trust/immutability
#   properties (ownership records, the fact that a listing's content
#   hash was X at a given time) lives on-chain, while bulk content lives
#   in systems designed and priced for bulk storage, with the on-chain
#   hash providing a verifiable link/integrity check against the off-
#   chain content.
#   COST: per L05, this reintroduces a real AVAILABILITY dependency on
#   the off-chain storage system -- if the off-chain content
#   (IPFS node, database) becomes unavailable, the on-chain hash alone
#   proves what the content WAS, but doesn't make the actual content
#   accessible; the dApp's practical usability now depends on that
#   off-chain system's uptime, a real, if often manageable
#   (particularly with IPFS's content-addressed, pinnable design),
#   dependency the pure on-chain approach (A) wouldn't have.
#
# ------------------------------------------------------------------------
# APPROACH C: B, but using a DECENTRALIZED off-chain storage network
# (IPFS with multiple pinning services, or a similar decentralized
# storage solution) rather than a single, centrally-operated database,
# specifically to avoid reintroducing a centralization point for the
# off-chain content
# ------------------------------------------------------------------------
#   WHY VALID: per L05's dApp-architecture discussion, this preserves
#   more of the dApp's overall decentralization ethos than B's
#   "reference a plain centralized database" version -- if content
#   availability shouldn't depend on any single company/server staying
#   online (a genuine value for many Web3 projects), decentralized
#   storage keeps that property for the off-chain layer too, not just
#   the on-chain layer.
#   COST: per L05, decentralized storage networks have their own real
#   operational considerations -- content isn't guaranteed to remain
#   available indefinitely unless actively PINNED by someone (a real,
#   ongoing cost/responsibility, whether the dApp team pays a pinning
#   service or relies on users/community pinning), and retrieval
#   latency/reliability from decentralized storage can be less
#   consistent than a well-operated centralized database or CDN.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Cost | Decentralization of content availability | Practical viability |
#   |----------|----------|--------------------------------------------------|--------------------------|
#   | A: everything on-chain | Prohibitive | N/A (no separation) | Poor, for bulk content |
#   | B: hash on-chain, content in a centralized off-chain store | Low | Low (centralized dependency) | Good |
#   | C: hash on-chain, content in decentralized storage | Low-medium (pinning costs) | High | Good, with pinning discipline |
#   B or C is the correct family of answers regardless; the choice
#   between them is a genuine values/tradeoff decision about how much
#   the project's off-chain layer needs to preserve decentralization
#   versus accepting a simpler, more reliably-available centralized
#   dependency for content that isn't the core trust-critical data
#   anyway.


# ============================================================================
# CASE STUDY 2 — CHOOSING A SCALING APPROACH FOR A DAPP FACING HIGH GAS
# COSTS/CONGESTION ON MAINNET
# ============================================================================
#
# SETUP: a dApp on Ethereum mainnet has become popular enough that user
# transaction costs (gas fees) have become a genuine barrier to adoption
# during periods of network congestion (L04, L07).
#
# ------------------------------------------------------------------------
# APPROACH A: Optimize the smart contract's gas efficiency (L04) --
# reduce storage operations, batch operations where possible, use more
# gas-efficient data types/patterns
# ------------------------------------------------------------------------
#   WHY VALID: per L04, genuine gas-cost analysis often reveals real,
#   fixable inefficiencies (unnecessary storage writes, which are the
#   most expensive EVM operations) -- addressing these directly reduces
#   cost without requiring any architectural change, migration, or new
#   trust assumptions.
#   COST: per L04, gas optimization has a real CEILING -- once a
#   contract is reasonably well-optimized, further gains become
#   marginal, and the FUNDAMENTAL cost of mainnet execution/storage
#   (set by network-wide demand, not this specific contract's
#   efficiency) remains a base cost optimization alone cannot eliminate
#   during genuine network congestion.
#
# ------------------------------------------------------------------------
# APPROACH B: Migrate to a Layer 2 scaling solution (L07) -- e.g. an
# Optimistic or ZK rollup
# ------------------------------------------------------------------------
#   WHY VALID: per L07, L2 solutions execute transactions off the
#   expensive mainnet layer, batching many transactions into
#   cheaper, aggregated mainnet settlements -- directly and
#   substantially reduces per-transaction cost for USERS, the standard
#   answer once gas optimization alone (A) hits its ceiling and
#   genuine scale is the actual problem.
#   COST: per L07, different L2 designs carry different tradeoffs --
#   Optimistic rollups have a genuine WITHDRAWAL DELAY (a challenge
#   period before funds can be safely withdrawn back to mainnet), while
#   ZK rollups have more complex, computationally-intensive proof
#   generation; migrating also means the dApp now depends on the
#   chosen L2's own security model and operational maturity, a real,
#   additional trust/complexity layer beyond mainnet alone.
#
# ------------------------------------------------------------------------
# APPROACH C: A, applied first to confirm genuine optimization has been
# exhausted, THEN B once genuinely justified -- explicitly sequencing
# the two rather than jumping straight to a migration
# ------------------------------------------------------------------------
#   WHY VALID: per L04 and L07 together, this avoids two symmetric
#   mistakes -- assuming gas optimization alone will solve a
#   fundamentally scale-driven cost problem (when A's ceiling is
#   already known to exist), OR jumping straight to a real, disruptive
#   L2 migration before confirming the contract itself isn't just
#   genuinely inefficient in ways A could have fixed more simply and
#   with less migration risk.
#   COST: takes real, sequential time (optimize first, measure, THEN
#   consider migration) rather than moving directly to what might turn
#   out to be the necessary answer anyway -- a deliberate, if sometimes
#   slower, engineering discipline that's the right call specifically
#   when it's not YET clear whether A alone would be sufficient.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Cost reduction ceiling | Migration/trust complexity | Right first step? |
#   |----------|------------------------------|-----------------------------------|--------------------------|
#   | A: gas optimization | Limited | None | Yes, always try first |
#   | B: L2 migration | Substantial | Real (new trust/operational layer) | Only once A's ceiling is confirmed |
#   | C: A first, then B if still needed | Combines both | Deferred until justified | Best sequencing |
#   C is the correct METHODOLOGY regardless of which specific answer
#   (A alone sufficing, or ultimately needing B) turns out to be right
#   for this specific dApp -- the mistake to avoid is skipping the
#   sequencing and jumping straight to either extreme without
#   confirming it's actually necessary.


# ============================================================================
# CASE STUDY 3 — KEY MANAGEMENT STRATEGY FOR A DAPP'S ADMIN/UPGRADE
# CONTROLS
# ============================================================================
#
# SETUP: a smart contract has admin functions (e.g. pausing the contract
# in an emergency, upgrading logic) -- deciding who/what controls the
# private key(s) authorized to call these functions (L06, L08).
#
# ------------------------------------------------------------------------
# APPROACH A: A single Externally Owned Account (EOA) -- one private
# key, held by one person (e.g. the founder), controls all admin
# functions (L06)
# ------------------------------------------------------------------------
#   WHY VALID: per L06, simplest possible setup -- no coordination
#   needed to execute an admin action, fast response in a genuine
#   emergency (no waiting on multiple signers), appropriate ONLY for a
#   very early-stage project with minimal funds/users at stake where
#   the operational simplicity outweighs the concentration-of-trust risk.
#   COST: per L06/L08's security discussion, this is a severe single
#   point of failure -- if that one key is compromised (phishing, a
#   compromised device, the key holder's own malicious action), an
#   attacker gains FULL admin control, and per L08's capstone security
#   discussion, concentrated admin key control is one of the most
#   common, well-documented sources of catastrophic dApp exploits and
#   rug pulls in the real Web3 ecosystem.
#
# ------------------------------------------------------------------------
# APPROACH B: A multi-signature (multisig) wallet (L06) requiring M-of-N
# signers to authorize any admin action (e.g. 3-of-5 known,
# independently-controlled keys)
# ------------------------------------------------------------------------
#   WHY VALID: per L06, directly addresses A's single-point-of-failure
#   risk -- no single compromised key is sufficient to take a
#   malicious admin action, since a threshold of independent signers
#   must agree, the standard, well-established answer for any dApp with
#   real value/users at stake.
#   COST: per L06, genuinely slower to execute an admin action (
#   coordinating M signers takes real time, a real cost specifically in
#   a genuine emergency requiring FAST response, e.g. pausing a contract
#   under active attack) -- and multisig security depends on the
#   signers' keys genuinely being independently controlled and secured;
#   if the "independent" signers are actually all controlled by the
#   same person/team with weak operational separation, much of the
#   real security benefit is illusory.
#
# ------------------------------------------------------------------------
# APPROACH C: B for ROUTINE admin actions (upgrades, parameter changes),
# combined with a SEPARATE, faster (e.g. single-key or lower-threshold)
# EMERGENCY PAUSE mechanism specifically scoped to ONLY halt the
# contract (not upgrade or move funds), accepting a narrower, more
# tightly-scoped trust concentration specifically for the time-critical
# emergency case
# ------------------------------------------------------------------------
#   WHY VALID: per L06/L08, this recognizes that "fast response" and
#   "strong distributed trust" are genuinely in tension, and resolves it
#   by SCOPING where each property is needed -- the emergency pause
#   function is deliberately narrow (it can only STOP the contract, a
#   fail-safe action, not redirect funds or change logic), making a
#   faster, lower-threshold mechanism an acceptable, bounded risk
#   specifically for that narrow capability, while routine, higher-
#   stakes actions still require B's full multisig discipline.
#   COST: requires careful, correct SCOPING of exactly what the fast-
#   path emergency mechanism can and cannot do -- a design mistake that
#   accidentally gives the emergency mechanism MORE power than intended
#   (e.g. it can also drain funds "in an emergency") would reintroduce
#   A's concentrated-trust risk for that broader capability, undermining
#   the whole point of the careful scoping.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Trust concentration risk | Emergency response speed | Appropriate stakes level |
#   |----------|-------------------------------|--------------------------------|--------------------------------|
#   | A: single EOA | Severe | Fastest | Only trivial, low-value early projects |
#   | B: multisig for everything | Low | Slower | Any project with real value at stake |
#   | C: multisig for routine + scoped fast emergency pause | Low, if correctly scoped | Fast, for the pause case specifically | Mature projects with real value AND genuine emergency-response needs |
#   B is the right baseline for essentially any dApp with real value at
#   stake; C is the right refinement once the team has confirmed a
#   genuine need for faster emergency response than B's coordination
#   overhead allows, with the scoping discipline done carefully and
#   correctly.


# ============================================================================
# CASE STUDY 4 — CHOOSING A CONSENSUS MECHANISM CONTEXT FOR A NEW,
# PURPOSE-BUILT BLOCKCHAIN APPLICATION (NOT BUILDING ON AN EXISTING
# CHAIN)
# ============================================================================
#
# SETUP: (a more theoretical/architectural case study) a team is
# designing a purpose-built blockchain for a specific application
# (rather than deploying a smart contract on an existing chain), needing
# to choose a consensus mechanism (L02).
#
# ------------------------------------------------------------------------
# APPROACH A: Proof of Work (PoW) (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, PoW has the longest track record and the
#   strongest, most battle-tested security properties against certain
#   attack classes (e.g. Sybil resistance via genuine computational
#   cost) -- a defensible choice for a chain prioritizing maximum
#   security conservatism over other properties, especially if
#   deliberately avoiding newer, less battle-tested consensus designs.
#   COST: per L02, PoW's real, substantial energy consumption is a
#   well-documented, genuine cost -- both a direct operational expense
#   and, for many organizations/users today, a real reputational/
#   environmental concern that can be a genuine adoption barrier
#   independent of the technology's actual security properties.
#
# ------------------------------------------------------------------------
# APPROACH B: Proof of Stake (PoS) (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, PoS achieves Sybil resistance via economic
#   stake rather than computational work, with dramatically lower
#   energy consumption -- the now-dominant modern choice for new chains
#   (following Ethereum's own PoW-to-PoS transition), avoiding A's
#   energy-cost/reputational concern entirely.
#   COST: per L02, PoS has a genuinely different, still-debated set of
#   security tradeoffs relative to PoW (e.g. different long-range-
#   attack and stake-centralization considerations) -- a real, if more
#   nuanced than "just switch and get the same security for free,"
#   set of tradeoffs the team needs to genuinely understand rather than
#   assume are strictly superior in every respect.
#
# ------------------------------------------------------------------------
# APPROACH C: Don't build a new consensus mechanism (or even a new
# chain) at all -- deploy as a smart-contract application on an
# EXISTING, well-established chain (this domain's more typical dApp
# pattern, L03-L05) rather than taking on consensus-mechanism design as
# part of this project's scope at all
# ------------------------------------------------------------------------
#   WHY VALID: per L02-L05's own framing, designing and BOOTSTRAPPING a
#   genuinely new, secure consensus mechanism and validator network from
#   scratch is an enormous undertaking with its own severe risks (a
#   NEW chain has far less real-world battle-testing and, critically,
#   needs to bootstrap genuine economic security/decentralization,
#   which is very hard to do credibly for a new, unproven network) --
#   for the VAST majority of application ideas, building on an existing,
#   established chain's already-proven consensus/security is the far
#   more practical, lower-risk answer.
#   COST: gives up any control over consensus-level properties (block
#   time, finality guarantees, fee market behavior) -- the application
#   must work within whatever the chosen existing chain provides, a
#   real constraint if the application has genuinely unusual consensus-
#   level requirements a general-purpose existing chain doesn't meet.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Security track record | Energy/operational cost | Practical feasibility for most projects |
#   |----------|----------------------------|-------------------------------|------------------------------------------------|
#   | A: new chain, PoW | Strong, for the mechanism itself | High | Very hard to bootstrap credibly as a NEW chain |
#   | B: new chain, PoS | Newer, still maturing | Low | Very hard to bootstrap credibly as a NEW chain |
#   | C: build on an existing established chain | Inherits the existing chain's proven track record | N/A (not the builder's concern) | Best, for the vast majority of use cases |
#   C is overwhelmingly the right default for most real application
#   ideas -- A/B (building an entirely new chain with its own consensus
#   mechanism) is justified only for the rare case with a genuine,
#   specific, unmet need that no existing chain's consensus design
#   can satisfy, a bar most projects don't actually clear.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
