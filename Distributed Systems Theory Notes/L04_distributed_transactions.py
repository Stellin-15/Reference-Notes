# ============================================================
# L04: Distributed Transactions — Two-Phase Commit, Three-Phase Commit, and Sagas
# ============================================================
# WHAT: How to make a transaction ATOMIC (all-or-nothing) when it spans
#       MULTIPLE independent nodes/databases — Two-Phase Commit (2PC),
#       its blocking weakness, Three-Phase Commit's partial fix, and why
#       modern systems increasingly favor the Saga pattern instead.
# WHY: This repo's System Design Notes mentions the Saga pattern briefly.
#      This lesson covers the FULL landscape of distributed transaction
#      approaches and their genuine tradeoffs, building on L01-L03's
#      consensus foundations.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
TWO-PHASE COMMIT (2PC) coordinates a transaction across multiple
PARTICIPANTS (each owning a piece of the data, e.g. separate databases)
via a designated COORDINATOR. PHASE 1 (PREPARE): the coordinator asks
every participant "can you commit this transaction?" — each participant
does whatever local work is needed to GUARANTEE it CAN commit if told to
(acquiring locks, writing to a durable log), then replies "yes" (ready)
or "no". PHASE 2 (COMMIT/ABORT): if ALL participants replied "yes," the
coordinator tells everyone to COMMIT; if ANY replied "no" (or timed
out), it tells everyone to ABORT — this guarantees ATOMICITY across
all participants (either everyone commits, or everyone aborts, never a
partial mix).

2PC'S FATAL WEAKNESS — BLOCKING: if the COORDINATOR crashes AFTER
participants have voted "yes" (entered the "prepared" state) but
BEFORE sending the final commit/abort decision, participants are stuck
— they've already promised to commit if told to (holding locks, unable
to unilaterally abort without risking inconsistency with participants
that DID receive a commit instruction before the crash), but they have
NO WAY to know what the coordinator's decision actually was. They must
BLOCK — holding locks, unable to proceed — until the coordinator
recovers, which could take an arbitrarily long time, during which the
affected data remains LOCKED and unusable — a severe availability cost
for what looks like a single coordinator failure.

THREE-PHASE COMMIT (3PC) attempts to fix this by inserting an
additional phase (a "pre-commit" acknowledgment) specifically designed
so participants can safely determine a reasonable default action even if
the coordinator fails at various points — but 3PC still cannot fully
solve the blocking problem under NETWORK PARTITIONS specifically (not
just coordinator crashes) and adds meaningful additional latency (an
extra round trip for every single transaction) — this combination of
"still not perfect" plus "meaningfully slower" is why 3PC saw
comparatively LIMITED real-world adoption despite addressing 2PC's headline weakness.

THE SAGA PATTERN takes a FUNDAMENTALLY DIFFERENT approach, favored by
most modern microservices architectures specifically because it AVOIDS
2PC/3PC's blocking and coordination overhead entirely: rather than one
atomic distributed transaction, a saga is a SEQUENCE of LOCAL
transactions, each with a corresponding, pre-defined COMPENSATING
transaction that can UNDO its effects. If a later step in the sequence
fails, the saga executes the compensating transactions for every
PREVIOUSLY completed step, in reverse order — achieving an
EVENTUALLY-consistent equivalent of atomicity without ever requiring
distributed locks held across a coordinator round trip. This trades 2PC's
STRONG, immediate atomicity guarantee for AVAILABILITY (no blocking) and
requires the application to explicitly define what "undoing" each step
actually means (which isn't always straightforward — sending an email
notification, for instance, cannot be truly "compensated," only followed by a correction).

PRODUCTION USE CASE:
An e-commerce order-placement flow spanning inventory reservation,
payment charging, and shipping-label creation (three separate
microservices/databases) uses a SAGA rather than 2PC: if the
shipping-label service fails after inventory was already reserved and
payment already charged, the saga executes compensating transactions —
refund the payment, release the inventory reservation — in reverse order
— achieving the equivalent of "the whole order either fully succeeds or
is fully rolled back," WITHOUT ever needing a distributed lock held
across all three services simultaneously (which 2PC would require,
introducing exactly the blocking risk this lesson describes).

COMMON MISTAKES:
- Choosing 2PC for a high-availability microservices architecture
  without understanding its blocking failure mode — a single
  coordinator crash can leave participant services holding locks
  indefinitely, a severe and disproportionate availability cost for
  what's often a routine failure (a coordinator process restart).
- Implementing a Saga without genuinely idempotent, safe COMPENSATING
  transactions for every step — a compensating action that isn't
  actually safe to run (e.g. it assumes the original action definitely
  succeeded, when it might have partially failed) can leave the system
  in an inconsistent state precisely during the failure scenario the
  saga was meant to handle correctly.
- Assuming a Saga provides the SAME atomicity guarantee as a true ACID
  distributed transaction — a saga is EVENTUALLY consistent; there is a
  real window during which OTHER parts of the system can observe the
  intermediate, not-yet-fully-committed-or-compensated state, which
  matters for certain consistency-sensitive use cases (financial
  reporting during a mid-flight saga, for instance) and must be
  designed around explicitly, not ignored.
"""

import time


# ------------------------------------------------------------------
# 1. Two-Phase Commit — and its blocking failure mode
# ------------------------------------------------------------------
class Participant:
    def __init__(self, name: str, will_vote_yes: bool = True):
        self.name = name
        self.will_vote_yes = will_vote_yes
        self.state = "idle"

    def prepare(self) -> bool:
        if self.will_vote_yes:
            self.state = "prepared"   # locks held, ready to commit OR abort
            return True
        self.state = "aborted"
        return False

    def commit(self):
        self.state = "committed"

    def abort(self):
        self.state = "aborted"


def two_phase_commit(participants: list[Participant]) -> str:
    # PHASE 1: prepare
    votes = [p.prepare() for p in participants]

    # PHASE 2: commit or abort, based on ALL votes
    if all(votes):
        for p in participants:
            p.commit()
        return "COMMITTED"
    else:
        for p in participants:
            if p.state == "prepared":
                p.abort()
        return "ABORTED"


def two_phase_commit_demo():
    print("2PC — all participants vote yes:")
    participants = [Participant("inventory-db"), Participant("payment-db"), Participant("shipping-db")]
    result = two_phase_commit(participants)
    print(f"  Result: {result}, states: {[(p.name, p.state) for p in participants]}\n")

    print("2PC — one participant votes no:")
    participants = [Participant("inventory-db"), Participant("payment-db", will_vote_yes=False), Participant("shipping-db")]
    result = two_phase_commit(participants)
    print(f"  Result: {result}, states: {[(p.name, p.state) for p in participants]}\n")

    print("2PC's fatal weakness (illustrated, not simulated mechanically):")
    print("  If the COORDINATOR crashes AFTER all participants voted 'yes'")
    print("  but BEFORE sending the final commit/abort decision, every")
    print("  participant is stuck holding locks in the 'prepared' state,")
    print("  unable to proceed until the coordinator recovers.")


# ------------------------------------------------------------------
# 2. Saga pattern — local transactions + compensating actions
# ------------------------------------------------------------------
class SagaStep:
    def __init__(self, name: str, action, compensate, should_fail: bool = False):
        self.name = name
        self.action = action
        self.compensate = compensate
        self.should_fail = should_fail

    def execute(self) -> bool:
        if self.should_fail:
            print(f"    [{self.name}] FAILED")
            return False
        self.action()
        print(f"    [{self.name}] succeeded")
        return True


def run_saga(steps: list[SagaStep]):
    completed_steps = []
    for step in steps:
        success = step.execute()
        if success:
            completed_steps.append(step)
        else:
            print(f"\n  Saga failed at '{step.name}' — running compensating "
                  f"transactions for {len(completed_steps)} completed step(s), in REVERSE order:")
            for completed_step in reversed(completed_steps):
                completed_step.compensate()
                print(f"    [{completed_step.name}] COMPENSATED (undone)")
            return "SAGA_FAILED_AND_COMPENSATED"
    return "SAGA_SUCCEEDED"


def saga_demo():
    print("\nSaga pattern — order placement across 3 services, shipping fails:\n")
    steps = [
        SagaStep("reserve_inventory",
                 action=lambda: None, compensate=lambda: print("      -> releasing reserved inventory")),
        SagaStep("charge_payment",
                 action=lambda: None, compensate=lambda: print("      -> refunding payment")),
        SagaStep("create_shipping_label",
                 action=lambda: None, compensate=lambda: print("      -> (n/a, this step never completed)"),
                 should_fail=True),
    ]
    result = run_saga(steps)
    print(f"\n  Final result: {result}")
    print("  -> No distributed lock was ever held ACROSS all three services")
    print("     simultaneously — each step committed LOCALLY and independently,")
    print("     avoiding 2PC's blocking risk entirely.")


if __name__ == "__main__":
    two_phase_commit_demo()
    saga_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
An early-stage e-commerce platform initially implements order placement
using 2PC across its inventory and payment databases — during a routine
coordinator service deployment, a crash mid-transaction leaves several
in-flight orders' inventory rows LOCKED for over 20 minutes until the
coordinator restarts and recovers its transaction log, a real, customer-
visible incident. The team migrates to a Saga-based design specifically
to eliminate this blocking failure mode — accepting the tradeoff of
eventual (not immediate) consistency and the engineering cost of
defining correct compensating actions for every step, in exchange for
the system remaining available even during a coordinator-equivalent
service's own individual failures.
"""
