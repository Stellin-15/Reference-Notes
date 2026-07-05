# ============================================================
# L07: Distributed Locking and Leader Election in Practice
# ============================================================
# WHAT: How to implement a mutual-exclusion LOCK across MULTIPLE
#       machines (not just threads on one machine) using a consensus-
#       backed coordination service — and the genuinely subtle failure
#       modes (the "GC pause problem") that make this harder than it
#       first appears.
# WHY: L02-L03 covered consensus abstractly. This lesson covers the
#      most common PRACTICAL application of it — distributed locks and
#      leader election, as implemented by real tools (ZooKeeper, etcd,
#      Consul) that most engineers will actually use rather than build
#      consensus algorithms from scratch.
# LEVEL: Advanced (capstone-adjacent)
# ============================================================

"""
CONCEPT OVERVIEW:
A DISTRIBUTED LOCK generalizes a single-machine mutex to coordinate
access across MULTIPLE machines — e.g. ensuring only ONE instance of a
horizontally-scaled cron job actually runs a specific scheduled task at
a time, even though multiple instances are all capable of triggering it.
Rather than implementing consensus (L02-L03) from scratch, real systems
use an existing CONSENSUS-BACKED COORDINATION SERVICE (ZooKeeper, etcd,
Consul — all themselves built on Paxos or Raft) as the source of truth
for "who currently holds the lock."

THE BASIC PROTOCOL: a client attempts to create a specific, well-known
KEY/NODE in the coordination service (e.g. `/locks/my-job`) — the
coordination service guarantees ONLY ONE client can successfully create
it (using its underlying consensus mechanism), making creation success
equivalent to "I now hold the lock." The lock is typically associated
with a SESSION/LEASE that expires if the holding client stops sending
heartbeats (e.g. due to a crash or network partition), automatically
releasing the lock so another client can acquire it — this TIME-BOUND
lease is what prevents a crashed lock-holder from holding the lock forever.

THE "GC PAUSE" PROBLEM (or more generally, the "process pause" problem)
is a genuinely subtle, often-overlooked failure mode: a client holding a
distributed lock might experience a LONG PAUSE (a garbage collection
pause in a managed-runtime language, being swapped out by the OS
scheduler, a temporary network partition) that EXCEEDS the lock's lease
duration — the coordination service, having received no heartbeat,
correctly expires the lease and grants the lock to ANOTHER client — but
the FIRST client, once it resumes from its pause, has NO WAY of knowing
its lock was revoked, and may continue performing actions AS IF it still
held the lock, now genuinely CONCURRENTLY with the second client that
legitimately acquired it — a serious correctness violation of the
mutual-exclusion guarantee the lock was supposed to provide.

FENCING TOKENS are the standard fix for the GC pause problem: every time
the lock is granted, the coordination service issues a MONOTONICALLY
INCREASING fencing token (a simple counter) along with it. The client
must include this token with every subsequent operation it performs
while believing it holds the lock — the RESOURCE being protected
(a database, a storage system) is responsible for REJECTING any
operation that arrives with an OLDER fencing token than one it has
already seen — this means even if the paused client resumes and
attempts to act, its stale, low-numbered token gets rejected by the
protected resource itself, providing a genuine safety guarantee that
the lock service's expiration mechanism ALONE cannot provide.

LEADER ELECTION (a lock held "forever," effectively, re-acquired
continuously by the current leader) uses the SAME underlying mechanism —
"leader" is simply "whoever currently holds a specific, well-known lock
key," with the SAME lease-based expiration and re-election on leader
failure that L03's Raft leader election handles internally, but
exposed here as a general-purpose PRIMITIVE any application can use for
its OWN leader-election needs without implementing Raft/Paxos itself.

PRODUCTION USE CASE:
A Kubernetes-based platform runs multiple replicas of a controller
process for redundancy, but only ONE replica should actively perform a
specific reconciliation action at a time — the replicas use Kubernetes'
built-in "lease" resource (itself backed by etcd's Raft consensus, L03)
to elect a leader; if the current leader replica experiences a long GC
pause exceeding the lease duration, the lease expires and another
replica becomes leader, while the ORIGINAL replica's subsequent write
attempts (using its now-stale fencing token/resource version) are
correctly rejected by the underlying storage layer, preventing the
serious bug of two replicas simultaneously believing they're the sole active leader.

COMMON MISTAKES:
- Implementing a distributed lock WITHOUT a lease/timeout mechanism — a
  client that crashes while holding the lock would then hold it FOREVER,
  permanently blocking every other client, a severe availability failure
  from what should be a routine, recoverable crash.
- Implementing lease-based expiration WITHOUT fencing tokens — this is
  EXACTLY the GC pause problem: the lock service correctly reassigns the
  lock after expiration, but the ORIGINAL, paused holder has no
  mechanism preventing it from continuing to act as if it still held
  the lock, a genuine correctness bug that's easy to overlook until it
  causes a real incident.
- Assuming "the lock service says I hold the lock" is sufficient
  assurance for protecting a critical resource — the PROTECTED RESOURCE
  itself must ALSO validate fencing tokens; relying purely on the lock
  holder's own good behavior (rather than having the resource enforce
  token freshness) reintroduces the exact vulnerability fencing tokens exist to close.
"""

import time


# ------------------------------------------------------------------
# 1. A basic lease-based distributed lock (conceptual, single-process simulation)
# ------------------------------------------------------------------
class DistributedLockService:
    def __init__(self, lease_duration_seconds: float = 10.0):
        self.lease_duration = lease_duration_seconds
        self.current_holder = None
        self.lease_expires_at = 0
        self.fencing_token_counter = 0

    def try_acquire(self, client_id: str, now: float) -> int | None:
        if self.current_holder is None or now >= self.lease_expires_at:
            self.current_holder = client_id
            self.lease_expires_at = now + self.lease_duration
            self.fencing_token_counter += 1
            return self.fencing_token_counter   # the NEW, higher fencing token
        return None   # lock already held by someone else, lease not expired

    def heartbeat(self, client_id: str, now: float) -> bool:
        if self.current_holder == client_id:
            self.lease_expires_at = now + self.lease_duration
            return True
        return False


class FencedResource:
    """The PROTECTED resource — enforces fencing tokens independently
    of the lock service, which is what actually closes the GC-pause gap."""
    def __init__(self):
        self.highest_token_seen = 0

    def write(self, fencing_token: int, data: str) -> bool:
        if fencing_token < self.highest_token_seen:
            print(f"    REJECTED write with stale fencing token {fencing_token} "
                  f"(highest seen: {self.highest_token_seen})")
            return False
        self.highest_token_seen = fencing_token
        print(f"    ACCEPTED write with fencing token {fencing_token}: '{data}'")
        return True


def gc_pause_and_fencing_demo():
    lock_service = DistributedLockService(lease_duration_seconds=5.0)
    resource = FencedResource()

    print("Client A acquires the lock:")
    token_a = lock_service.try_acquire("client-A", now=0)
    print(f"  Client A got fencing token: {token_a}")

    print("\nClient A experiences a long GC pause (exceeds the 5s lease)...")
    print("Meanwhile, the lease expires and Client B acquires the lock:")
    token_b = lock_service.try_acquire("client-B", now=10)
    print(f"  Client B got fencing token: {token_b}")

    print("\nClient B performs a legitimate write:")
    resource.write(token_b, "Client B's update")

    print("\nClient A resumes from its GC pause, UNAWARE its lock was revoked,")
    print("and attempts to write using its now-STALE fencing token:")
    resource.write(token_a, "Client A's stale, dangerous update")

    print("\n  -> The RESOURCE ITSELF rejected Client A's stale write, even")
    print("     though Client A still (incorrectly) believes it holds the lock —")
    print("     this is EXACTLY what fencing tokens are for: the lock service's")
    print("     expiration alone cannot prevent this without the resource's own enforcement.")


if __name__ == "__main__":
    gc_pause_and_fencing_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A distributed job scheduler running multiple replicas for high
availability uses etcd's lease/lock primitives (backed by Raft, L03) to
ensure only one replica actively dispatches scheduled jobs at a time —
after a real incident where a replica's multi-second GC pause caused it
to briefly continue dispatching jobs even after another replica had
already taken over leadership (a duplicate-job-execution bug), the team
added fencing tokens to the job-dispatch storage layer specifically —
directly closing the gap that lease expiration ALONE had failed to
prevent, exactly as this lesson's simulation demonstrates.
"""
