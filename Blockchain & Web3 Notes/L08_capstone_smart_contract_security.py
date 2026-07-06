# ============================================================
# L08: Capstone — Smart Contract Security and Common Exploits
# ============================================================
# WHAT: A capstone lesson covering the most common, historically
#       damaging smart contract vulnerability classes — reentrancy,
#       integer overflow/underflow, and access control failures — tying
#       together L01-L07's blockchain/EVM/gas concepts into WHY these
#       specific vulnerabilities exist and how to defend against them.
# WHY: L03-L04 introduced smart contracts and the EVM's unusual
#      execution model. This capstone shows CONCRETELY how that unusual
#      model creates vulnerability classes with no direct equivalent in
#      typical application security, directly connecting to this
#      repo's Auth & Security Notes' broader security principles.
# LEVEL: Capstone
# ============================================================

"""
CONCEPT OVERVIEW:
REENTRANCY (introduced briefly in L03) is the CLASSIC smart contract
vulnerability, responsible for the 2016 DAO hack and numerous
subsequent exploits: it occurs when a contract makes an EXTERNAL CALL
(e.g. sending funds to another address) BEFORE updating its OWN internal
state to reflect that action — if the external call is to a MALICIOUS
contract, that contract can immediately CALL BACK into the original
function (which hasn't finished executing yet, and whose state
therefore still reflects the PRE-transaction values) — repeating the
withdrawal multiple times before the original function ever gets to
update the balance. The defense is the "CHECKS-EFFECTS-INTERACTIONS"
pattern: perform all CHECKS (validate the request) and EFFECTS (update
internal state) BEFORE any INTERACTIONS (external calls) — ensuring
state is already correctly updated before any opportunity for reentrant
callback exists.

INTEGER OVERFLOW/UNDERFLOW: older Solidity versions (before 0.8.0)
allowed arithmetic operations to silently WRAP AROUND when exceeding a
number type's maximum/minimum value (e.g. subtracting 1 from a `uint256`
holding 0 would wrap around to an enormous positive number instead of
producing a negative result or an error) — this created serious
vulnerabilities where, for example, a balance check like "does the
sender have at least this much" could be BYPASSED by intentionally
triggering an underflow. Solidity 0.8.0+ makes overflow/underflow
REVERT BY DEFAULT (a language-level fix), but understanding this
history explains WHY defensive arithmetic libraries (like OpenZeppelin's
SafeMath, now largely unnecessary but historically essential) were
such a critical, widely-adopted pattern.

ACCESS CONTROL FAILURES occur when a function that SHOULD be restricted
(e.g. only the contract owner should be able to withdraw all funds, or
change a critical parameter) is missing the appropriate PERMISSION
CHECK — given that smart contract code and its CALLABLE FUNCTIONS are
PUBLICLY VISIBLE and callable by anyone by default (unless explicitly
restricted), a missing `onlyOwner`-style modifier on a sensitive
function is a direct, exploitable vulnerability that's often
surprisingly easy to overlook during development but immediately
exploitable once deployed and discovered.

WHY SMART CONTRACT SECURITY IS UNIQUELY HIGH-STAKES (tying back to
L03's immutability and L01's tamper-evidence): a vulnerability
discovered in typical web application code can usually be PATCHED
quickly once identified — a vulnerability in a DEPLOYED, IMMUTABLE
smart contract (L03) CANNOT be silently fixed; by the time it's
discovered, an attacker may have ALREADY exploited it, and the funds
lost are typically UNRECOVERABLE (blockchain transactions are
irreversible, L02) — this combination of "cannot patch after deployment"
and "financial loss is typically permanent and irreversible" is
precisely why smart contract security AUDITS (specialized, thorough
manual + automated review before deployment) are treated as a
non-negotiable, standard practice for any contract handling meaningful value.

PRODUCTION USE CASE:
A DeFi lending protocol undergoes MULTIPLE independent professional
security audits before mainnet deployment, specifically checking for
reentrancy (verifying checks-effects-interactions ordering throughout),
access control (verifying every privileged function has correct
permission restrictions), and arithmetic safety — this is standard
industry practice specifically BECAUSE the combination of immutability
and irreversible financial stakes makes pre-deployment review
dramatically more important than in typical, patchable web application development.

COMMON MISTAKES:
- Making an external call (sending funds, calling another contract)
  BEFORE updating internal state to reflect that action — this is
  EXACTLY the reentrancy vulnerability pattern; the checks-effects-
  interactions ordering exists specifically to eliminate this risk structurally.
- Deploying a contract without an appropriate security audit because
  "the code looks correct" — given the PERMANENT, IRREVERSIBLE
  consequences of a missed vulnerability in this specific domain,
  informal self-review is widely considered insufficient for anything
  handling meaningful financial value, unlike many typical web application contexts.
- Forgetting to add explicit ACCESS CONTROL modifiers to sensitive
  functions — since ALL functions in a smart contract are PUBLICLY
  CALLABLE by default unless explicitly restricted, this is a genuinely
  easy category of mistake to make, and one immediately, permanently exploitable once deployed.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Reentrancy vulnerability and the checks-effects-interactions fix
# ------------------------------------------------------------------
VULNERABLE_REENTRANCY_EXAMPLE = textwrap.dedent("""\
    // VULNERABLE: external call happens BEFORE state update
    contract VulnerableBank {
        mapping(address => uint256) public balances;

        function withdraw(uint256 amount) public {
            require(balances[msg.sender] >= amount, "Insufficient balance");

            // DANGER: sending funds BEFORE updating the balance —
            // if msg.sender is a malicious contract, its fallback
            // function can call withdraw() AGAIN right here, before
            // the line below ever executes, repeating the withdrawal
            (bool success, ) = msg.sender.call{value: amount}("");
            require(success, "Transfer failed");

            balances[msg.sender] -= amount;   // TOO LATE — already reentered
        }
    }

    // FIXED: checks-effects-interactions pattern
    contract SafeBank {
        mapping(address => uint256) public balances;

        function withdraw(uint256 amount) public {
            require(balances[msg.sender] >= amount, "Insufficient balance");  // CHECK

            balances[msg.sender] -= amount;   // EFFECT — state updated FIRST

            (bool success, ) = msg.sender.call{value: amount}("");  // INTERACTION last
            require(success, "Transfer failed");
            // Even if this triggers reentrancy, balances[msg.sender] is
            // ALREADY updated, so a repeated withdraw() call would correctly
            // fail the balance check above
        }
    }
""")

# ------------------------------------------------------------------
# 2. Access control failure
# ------------------------------------------------------------------
ACCESS_CONTROL_EXAMPLE = textwrap.dedent("""\
    // VULNERABLE: no access restriction — ANYONE can call this
    contract VulnerableConfig {
        address public feeCollector;

        function setFeeCollector(address newCollector) public {
            feeCollector = newCollector;   // ANY caller can redirect fees to themselves!
        }
    }

    // FIXED: explicit access control modifier
    contract SafeConfig {
        address public owner;
        address public feeCollector;

        modifier onlyOwner() {
            require(msg.sender == owner, "Not authorized");
            _;
        }

        function setFeeCollector(address newCollector) public onlyOwner {
            feeCollector = newCollector;   // only the OWNER can call this successfully
        }
    }
""")


def security_illustration():
    print(VULNERABLE_REENTRANCY_EXAMPLE)
    print(ACCESS_CONTROL_EXAMPLE)
    print("Checklist any pre-deployment smart contract audit verifies:\n")
    checklist = [
        "Every external call follows checks-effects-interactions ordering",
        "Every privileged/sensitive function has explicit access control",
        "Arithmetic operations are safe from overflow/underflow (Solidity 0.8+ helps, but verify)",
        "No untested, unaudited code paths handle real user funds",
    ]
    for item in checklist:
        print(f"  [ ] {item}")


if __name__ == "__main__":
    security_illustration()

"""
FINAL CONTEXT (capstone of this domain):
The measure of having internalized this domain isn't being able to
write a working Solidity contract in isolation — it's understanding
WHY blockchain's core properties (immutability, L01/L03; consensus-
verified execution, L02; explicit metered computation, L04) create a
security environment where mistakes are dramatically more costly and
permanent than in typical application development, and recognizing the
SPECIFIC vulnerability patterns (reentrancy, access control, arithmetic
safety) this unusual environment makes possible — this connects
directly to this repo's Auth & Security Notes' broader security
principles, applied here to a domain where "patch it later" is
structurally unavailable and the financial stakes of getting it wrong
are immediate and irreversible.
"""
