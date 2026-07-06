# ============================================================
# L04: EVM Internals and Gas — Why Smart Contract Execution Costs Money
# ============================================================
# WHAT: The Ethereum Virtual Machine (EVM) — the sandboxed execution
#       environment EVERY Ethereum node runs to process smart contracts
#       — and GAS, the mechanism that makes computational cost an
#       explicit, metered, and PAID resource, unlike almost any traditional computing environment.
# WHY: L03 introduced smart contracts and mentioned gas briefly. This
#      lesson goes deep on WHY gas exists and HOW it works — a genuinely
#      unusual computing model that directly shapes how smart contract
#      code must be written.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
THE EVM (Ethereum Virtual Machine) is a SANDBOXED, DETERMINISTIC
execution environment — every single Ethereum node in the ENTIRE
network runs the SAME EVM bytecode for a given contract call and MUST
arrive at the EXACT SAME result, which is what allows the network to
reach consensus (L02) on the outcome of contract execution. This
determinism requirement rules out anything genuinely non-deterministic
in contract code (no real random numbers, no direct network calls, no
system clock access) — smart contracts can ONLY interact with data
that's ALREADY part of the deterministic blockchain state, a
significant and deliberate constraint compared to normal application code.

GAS is Ethereum's mechanism for pricing COMPUTATION explicitly: every
single EVM operation (adding two numbers, storing a value, calling
another contract) has a FIXED GAS COST, reflecting its relative
computational/storage expense — a transaction specifies a GAS LIMIT
(the maximum gas the sender is willing to have consumed) and a GAS
PRICE (how much the sender is willing to pay per unit of gas, in the
network's native currency) — if execution consumes MORE gas than the
specified limit before completing, the ENTIRE transaction is REVERTED
(all its state changes undone) but the gas ALREADY CONSUMED is still
paid to the network (as compensation for the computational work
miners/validators already performed) — this is a GENUINELY UNUSUAL
failure mode compared to typical application code, where "running out
of resources" doesn't typically cost you money for the failed attempt.

WHY THIS EXISTS: gas serves TWO purposes simultaneously — it prevents
DENIAL-OF-SERVICE attacks (an infinite loop or maliciously expensive
computation would otherwise let ONE bad actor consume unlimited network
resources for free, since EVERY node must execute it) by making
computation an explicit, paid resource; and it provides an economic
incentive for miners/validators to include transactions (they collect
the gas fees as compensation for their computational/verification work).

STORAGE OPERATIONS ARE DISPROPORTIONATELY EXPENSIVE compared to
computation, and this shapes idiomatic Solidity code: writing to
persistent contract STORAGE (which every node must permanently retain)
costs vastly more gas than performing arithmetic or using temporary
MEMORY (which exists only during the transaction's execution and
doesn't need to be permanently stored by every node) — experienced
Solidity developers specifically optimize for MINIMIZING storage writes
and using memory/temporary variables wherever the logic allows, a
performance consideration with NO real equivalent in typical
application programming (where memory vs disk cost differences rarely
influence code structure this directly).

PRODUCTION USE CASE:
A decentralized exchange contract carefully minimizes the number of
separate STORAGE WRITES per trade (e.g. batching balance updates rather
than writing to storage multiple times within one function), because
EVERY storage write directly and substantially increases the gas cost
EVERY user pays to execute a trade — a genuinely direct, user-facing
cost consequence of implementation choices that, in a traditional
backend application, would only affect the OPERATOR's own infrastructure
costs, not each individual user's out-of-pocket transaction cost.

COMMON MISTAKES:
- Writing Solidity code as if storage and memory have comparable cost
  (as they effectively do in most traditional programming) — this
  produces contracts with needlessly high gas costs, directly and
  visibly costing every user who interacts with the contract more money per transaction.
- Not setting an appropriate GAS LIMIT for a transaction — too low a
  limit causes the transaction to FAIL (reverting all changes) while
  STILL consuming the gas that was used before hitting the limit,
  wasting real money on a failed transaction; too high a limit doesn't
  cause OVERPAYMENT (unused gas is refunded) but may mask a bug that
  would have failed faster with a tighter limit.
- Assuming smart contract code can access external, real-world data
  (current stock prices, weather data, random numbers from an external
  source) directly — the EVM's determinism requirement means this data
  must be brought ON-CHAIN via a specific mechanism (an "oracle," a
  topic beyond this domain's scope but important to know exists) rather
  than a normal, direct API call the way typical application code would use.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Gas cost illustration — different operations, different costs
# ------------------------------------------------------------------
GAS_COST_TABLE = {
    "ADD (simple arithmetic)": 3,
    "MLOAD/MSTORE (memory read/write)": 3,
    "SLOAD (read from persistent storage)": 2100,
    "SSTORE (write to persistent storage, new slot)": 20000,
    "CALL (calling another contract)": 2600,
}


def gas_cost_illustration():
    print("Illustrative EVM operation gas costs (approximate, simplified):\n")
    for operation, cost in GAS_COST_TABLE.items():
        print(f"  {operation}: {cost} gas")
    print(f"\n  -> A single STORAGE WRITE (SSTORE) costs roughly "
          f"{GAS_COST_TABLE['SSTORE (write to persistent storage, new slot)'] // GAS_COST_TABLE['ADD (simple arithmetic)']}x "
          f"a simple arithmetic operation — this dramatic cost asymmetry")
    print("     is exactly why idiomatic Solidity code minimizes storage writes.")


# ------------------------------------------------------------------
# 2. Gas limit and out-of-gas failure — illustrated
# ------------------------------------------------------------------
def simulate_transaction_execution(gas_limit: int, operations: list[tuple[str, int]]) -> dict:
    gas_consumed = 0
    for operation_name, cost in operations:
        gas_consumed += cost
        if gas_consumed > gas_limit:
            return {
                "status": "REVERTED (out of gas)",
                "gas_consumed_before_failure": gas_consumed - cost + cost,  # still consumed, not refunded
                "operations_completed": operations.index((operation_name, cost)),
            }
    return {"status": "SUCCESS", "gas_consumed": gas_consumed}


def out_of_gas_demo():
    operations = [
        ("SLOAD balance", 2100),
        ("compute new balance", 3),
        ("SSTORE new balance", 20000),
        ("CALL external transfer", 2600),
    ]

    print("\nTransaction with a gas limit of 25000:")
    result = simulate_transaction_execution(gas_limit=25000, operations=operations)
    print(f"  Result: {result}")
    print("  -> Even though the transaction FAILED and all its state changes")
    print("     were REVERTED, the gas already consumed is STILL PAID —")
    print("     a genuinely unusual 'you pay even on failure' cost model.")

    print("\nSame transaction with an adequate gas limit of 30000:")
    result = simulate_transaction_execution(gas_limit=30000, operations=operations)
    print(f"  Result: {result}")


if __name__ == "__main__":
    gas_cost_illustration()
    out_of_gas_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
During periods of high Ethereum network congestion (many transactions
competing for limited block space), gas PRICES (how much users are
willing to pay per unit of gas) rise substantially as users compete to
have their transactions prioritized — a decentralized application's
users can experience transaction costs ranging from a few cents to
tens of dollars for the IDENTICAL contract interaction, purely based on
current network demand — a genuinely different cost dynamic than
traditional cloud infrastructure, where compute costs are typically
fixed/predictable rather than fluctuating based on a shared, contested,
public resource's real-time demand.
"""
