# ============================================================
# L23: Health Checks and Failover — Keeping a Load Balancer's View of Reality Accurate
# ============================================================
# WHAT: How a load balancer knows WHICH backend servers are actually
#       healthy enough to receive traffic — active vs passive health
#       checks, failure thresholds, and the failover mechanics that
#       remove/restore backends automatically.
# WHY: L21-L22 covered WHERE and HOW a load balancer routes traffic
#      assuming all backends are healthy. In reality, backends fail
#      constantly (crashes, overload, deployments) — this lesson covers
#      how the load balancer's routing decisions stay CORRECT despite that.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
ACTIVE HEALTH CHECKS have the load balancer PROACTIVELY send periodic
probe requests (commonly a lightweight HTTP GET to a dedicated
`/health` endpoint) to each backend, independent of real user traffic —
a backend that fails to respond correctly (wrong status code, timeout,
connection refused) within a configured number of consecutive checks is
marked UNHEALTHY and removed from the routing pool. This catches failures
even during LOW-TRAFFIC periods, when passive checks (below) might not
generate enough real requests to detect a problem quickly.

PASSIVE HEALTH CHECKS observe the OUTCOME of REAL user traffic already
being sent to a backend — if a backend's real requests start failing
(error responses, timeouts) at an elevated rate, it's marked unhealthy
based on this OBSERVED behavior, without any separate probe traffic.
This has zero additional overhead (no extra probe requests) but,
critically, provides NO signal during low-traffic periods, and the
FIRST few real users hitting a newly-failing backend experience the
failure before it's detected and removed — production systems commonly
use BOTH active and passive checks together, gaining active checks'
early detection during quiet periods and passive checks' zero-overhead
confirmation during active traffic.

FAILURE THRESHOLDS (not marking a backend unhealthy after a SINGLE
failed check) exist specifically to avoid FLAPPING — a backend that
fails one health check due to a brief, transient blip (a momentary GC
pause, a single dropped packet) shouldn't be yanked from rotation only
to immediately need re-adding — a threshold like "3 consecutive failures"
filters out this noise while still reacting reasonably quickly to a
GENUINE, sustained failure. The SAME threshold logic applies in reverse
for RECOVERY: a backend typically needs several consecutive SUCCESSFUL
health checks before being trusted enough to receive live traffic again,
avoiding prematurely sending real users to a backend that's still
unstable/restarting.

GRACEFUL DEGRADATION when ALL backends in a pool are unhealthy is a
genuine edge case worth designing for explicitly: rather than the load
balancer simply failing every request with no useful information, a
well-designed system can fall back to a CACHED/STALE response, a
DEGRADED-BUT-FUNCTIONAL response (skip a non-critical feature), or at
minimum a clear, informative error rather than an opaque timeout — the
"what happens when literally everything is down" case is easy to
overlook during design but genuinely happens during severe incidents.

PRODUCTION USE CASE:
A backend server experiences a memory leak that gradually degrades its
response times over several hours before eventually causing it to stop
responding to requests entirely — ACTIVE health checks detect this
GRADUAL degradation (rising response latency/timeout rate on the
dedicated health endpoint) and can trigger an ALERT and eventually
remove the backend from rotation well before it fails completely, while
PASSIVE checks simultaneously confirm elevated real-traffic error rates
from the same backend, providing corroborating evidence rather than
relying on either signal alone.

COMMON MISTAKES:
- Marking a backend unhealthy after a SINGLE failed health check — this
  causes unnecessary "flapping" (rapidly removing and re-adding backends)
  in response to brief, transient blips that don't actually indicate a
  genuine, sustained problem.
- Relying ONLY on passive health checks — this provides no early-warning
  signal during low-traffic periods, and the first real users hitting a
  newly-broken backend become the unwitting "detectors" of the failure.
- Not requiring a RECOVERY threshold before restoring a backend to the
  live pool — sending traffic back to a backend after just ONE successful
  health check risks the backend still being unstable (e.g. mid-restart,
  cache still cold) and immediately failing again under real load.
"""

import time
from collections import deque


# ------------------------------------------------------------------
# 1. Active health checking with failure/recovery thresholds
# ------------------------------------------------------------------
class HealthCheckedBackend:
    def __init__(self, name: str, failure_threshold: int = 3, recovery_threshold: int = 2):
        self.name = name
        self.healthy = True
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.failure_threshold = failure_threshold
        self.recovery_threshold = recovery_threshold

    def record_check_result(self, success: bool):
        if success:
            self.consecutive_successes += 1
            self.consecutive_failures = 0
            if not self.healthy and self.consecutive_successes >= self.recovery_threshold:
                self.healthy = True
                print(f"  [{self.name}] RECOVERED after "
                      f"{self.consecutive_successes} consecutive successful checks")
        else:
            self.consecutive_failures += 1
            self.consecutive_successes = 0
            if self.healthy and self.consecutive_failures >= self.failure_threshold:
                self.healthy = False
                print(f"  [{self.name}] MARKED UNHEALTHY after "
                      f"{self.consecutive_failures} consecutive failed checks")


def health_check_threshold_demo():
    backend = HealthCheckedBackend("backend-1", failure_threshold=3, recovery_threshold=2)

    print("Simulating a single transient blip (should NOT trigger removal):")
    backend.record_check_result(success=True)
    backend.record_check_result(success=False)   # one blip
    backend.record_check_result(success=True)
    print(f"  Backend still healthy: {backend.healthy} (correctly ignored the single blip)\n")

    print("Simulating a SUSTAINED failure (should trigger removal after threshold):")
    for _ in range(3):
        backend.record_check_result(success=False)
    print(f"  Backend healthy: {backend.healthy}\n")

    print("Simulating recovery (should require 2 consecutive successes):")
    backend.record_check_result(success=True)
    print(f"  Backend healthy after 1 success: {backend.healthy}")
    backend.record_check_result(success=True)
    print(f"  Backend healthy after 2 successes: {backend.healthy}")


# ------------------------------------------------------------------
# 2. Combining active and passive signals
# ------------------------------------------------------------------
def combined_health_signal_demo():
    print("\nCombined active + passive health signal:")
    print("  Active check (dedicated /health probe): PASSING")
    print("  Passive signal (real traffic error rate): 40% of last 20 requests failed")
    print("  -> Even though the DEDICATED health endpoint reports healthy,")
    print("     the REAL traffic failure rate is a strong independent")
    print("     signal something is wrong (e.g. the health endpoint itself")
    print("     doesn't exercise the same code path real users hit) —")
    print("     a robust system weighs BOTH signals rather than trusting")
    print("     the active check alone.")


# ------------------------------------------------------------------
# 3. All-backends-down graceful degradation
# ------------------------------------------------------------------
def select_backend_with_fallback(backends: list[HealthCheckedBackend]) -> str:
    healthy_backends = [b for b in backends if b.healthy]
    if healthy_backends:
        return healthy_backends[0].name
    print("  ALL backends unhealthy — falling back to degraded response")
    print("  (cached/stale data or a clear error) rather than an opaque timeout.")
    return "DEGRADED_FALLBACK_RESPONSE"


if __name__ == "__main__":
    health_check_threshold_demo()
    combined_health_signal_demo()

    print("\nAll-backends-down scenario:")
    all_down_backends = [HealthCheckedBackend(f"backend-{i}") for i in range(3)]
    for b in all_down_backends:
        b.healthy = False
    result = select_backend_with_fallback(all_down_backends)
    print(f"  Result: {result}")

"""
PRODUCTION CONTEXT EXAMPLE:
During a rolling deployment, each backend instance is briefly restarted
one at a time — the load balancer's active health checks detect each
instance going down (failing checks immediately after restart begins)
and remove it from rotation, then require several consecutive
successful checks (confirming the newly-deployed code is actually
serving correctly, not just that the process has started) before
routing live traffic back to it — this recovery threshold specifically
prevents sending real user requests to an instance that's technically
running but still warming up caches or finishing initialization.
"""
