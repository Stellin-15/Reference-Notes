# ============================================================
# L03: Smart Contracts with Solidity
# ============================================================
# WHAT: What a "smart contract" actually is — self-executing code
#       deployed permanently on a blockchain — Solidity's core syntax
#       for writing them, and the fundamentally different execution
#       environment they run in compared to normal application code.
# WHY: L01-L02 covered the blockchain's data structure and consensus
#      mechanism. Smart contracts are what turned blockchains from
#      "a ledger for transferring currency" into a general-purpose,
#      decentralized COMPUTING platform — this is the foundation for
#      L04-L06's dApp/wallet coverage.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
A SMART CONTRACT is CODE deployed to a blockchain (most commonly
associated with Ethereum and Solidity, though other platforms/languages
exist) that EXECUTES AUTOMATICALLY when called, with its EXECUTION
RESULT itself becoming part of the blockchain's permanent, tamper-
evident record (L01) — critically, once deployed, a smart contract's
CODE is, by default, IMMUTABLE — it cannot be silently modified the way
a traditional server's backend code can be updated, which is BOTH a
genuine trust/transparency benefit (users can verify the exact logic
governing a contract will never secretly change) AND a genuine risk (a
bug deployed to production is, by default, PERMANENT, unless the
contract was specifically designed with an upgrade mechanism in advance).

SOLIDITY is the dominant smart contract language for Ethereum (and
Ethereum-compatible chains) — syntactically similar to JavaScript/C-like
languages, but with concepts specific to its execution environment: a
`contract` is roughly analogous to a class; STATE VARIABLES persist
PERMANENTLY on the blockchain (unlike normal in-memory variables,
every state change is a real, costly blockchain transaction); FUNCTIONS
can be marked `view` (read-only, doesn't modify state, free to call) or
NON-view (modifies state, costs "gas" — L04 covers this in depth) —
this view/non-view distinction has NO real equivalent in typical
application programming, where reads and writes usually have
comparable, negligible individual cost.

THE EXECUTION ENVIRONMENT IS GENUINELY DIFFERENT from normal server-side
code: smart contract code runs on the ETHEREUM VIRTUAL MACHINE (EVM,
covered in depth in L04) — EVERY node in the ENTIRE network
INDEPENDENTLY EXECUTES every smart contract call to verify its result,
rather than a single server executing it once — this is WHY smart
contract execution costs real money (gas, L04) proportional to
computational complexity: you're not paying for one server's compute
time, you're effectively paying for THOUSANDS of independent nodes worldwide to each execute the same code.

REENTRANCY AND OTHER SMART-CONTRACT-SPECIFIC VULNERABILITY CLASSES
(covered in depth in L08) exist BECAUSE of this unusual execution model
— the most famous historical example, the 2016 "DAO hack," exploited a
REENTRANCY bug: a malicious contract could call BACK INTO a vulnerable
contract's withdrawal function BEFORE that function had finished
updating the caller's balance, draining funds repeatedly in a single
transaction — this specific vulnerability class has NO direct
equivalent in typical single-threaded application code, and understanding
it requires understanding smart contracts' unique call/execution model specifically.

PRODUCTION USE CASE:
A decentralized lending protocol's smart contract holds users' deposited
funds and AUTOMATICALLY calculates and pays interest, processes loan
collateral, and executes liquidations — ALL according to code logic that
was PUBLICLY VISIBLE and VERIFIED before any user deposited funds,
providing a genuinely different trust model than a traditional bank
(where you must trust the institution's internal, non-public systems
and processes) — but this same immutability means a bug in the deployed
contract logic cannot be silently patched the way a traditional bank's
backend software could be, a real, structural risk tradeoff.

COMMON MISTAKES:
- Assuming a deployed smart contract can be updated/patched like normal
  application code — by DEFAULT, it cannot; contracts needing future
  upgradeability must be DELIBERATELY designed with an upgrade pattern
  (e.g. a proxy contract architecture) from the START, which adds real
  complexity and its own security considerations.
- Writing smart contract code without considering its GAS COST (L04) —
  since every operation costs real money proportional to computational
  complexity, inefficient code patterns that would be a minor concern
  in normal application development are a genuine, direct financial cost
  for smart contracts specifically.
- Deploying financially significant smart contract code without a
  thorough SECURITY AUDIT — given the permanent, immutable nature of
  deployed code and the direct financial stakes involved, vulnerability
  classes like reentrancy (L08) have caused real, substantial financial
  losses in production, making security review a genuinely higher-stakes
  practice here than in most typical application development.
"""

import textwrap


# ------------------------------------------------------------------
# 1. A basic Solidity smart contract — state, view vs non-view functions
# ------------------------------------------------------------------
SIMPLE_CONTRACT_EXAMPLE = textwrap.dedent("""\
    // SPDX-License-Identifier: MIT
    pragma solidity ^0.8.0;

    contract SimpleBank {
        // STATE VARIABLES — persisted PERMANENTLY on the blockchain,
        // unlike normal in-memory application variables
        mapping(address => uint256) private balances;
        address public owner;

        constructor() {
            owner = msg.sender;   // the account that deployed this contract
        }

        // A VIEW function — read-only, does NOT modify state, FREE to call
        function getBalance(address account) public view returns (uint256) {
            return balances[account];
        }

        // A NON-VIEW function — modifies state, costs GAS (L04) to execute
        function deposit() public payable {
            balances[msg.sender] += msg.value;
        }

        function withdraw(uint256 amount) public {
            require(balances[msg.sender] >= amount, "Insufficient balance");
            balances[msg.sender] -= amount;
            payable(msg.sender).transfer(amount);
        }
    }

    // Once DEPLOYED, this exact code (and its logic) is PERMANENT and
    // PUBLICLY VERIFIABLE — no silent server-side update is possible,
    // unlike a traditional backend application.
""")

# ------------------------------------------------------------------
# 2. Illustrating immutability — deployed code cannot silently change
# ------------------------------------------------------------------
def immutability_illustration():
    print("Traditional server-side code deployment:")
    print("  Deploy v1 -> discover bug -> silently push v2 -> users never")
    print("  need to know the code changed underneath them\n")

    print("Smart contract deployment (WITHOUT an upgrade pattern):")
    print("  Deploy v1 to blockchain address 0xABC... -> discover bug ->")
    print("  CANNOT modify the code at 0xABC... -> must deploy an ENTIRELY")
    print("  NEW contract at a DIFFERENT address, and separately convince")
    print("  users/other contracts to migrate to it")
    print("\n  -> This is EXACTLY why upgradeable-contract patterns (proxy")
    print("     architectures) are deliberately designed in ADVANCE for")
    print("     contracts expecting to need future changes — retrofitting")
    print("     upgradeability after deployment is not possible.")


if __name__ == "__main__":
    print(SIMPLE_CONTRACT_EXAMPLE)
    immutability_illustration()

"""
PRODUCTION CONTEXT EXAMPLE:
The 2016 "DAO" (Decentralized Autonomous Organization) hack exploited a
reentrancy vulnerability in a smart contract holding roughly $50 million
worth of ETH at the time — the vulnerable contract's withdrawal function
sent funds BEFORE updating the caller's recorded balance, letting a
malicious contract recursively call back into the withdrawal function
repeatedly before the balance update ever took effect — the IMMUTABLE
nature of the deployed contract meant the bug could not be simply
patched; Ethereum's community ultimately executed a highly controversial
network-level "hard fork" to reverse the theft's effects — an
extraordinary, one-time response specifically because normal
software-patching approaches were structurally unavailable for a
deployed, immutable smart contract.
"""
