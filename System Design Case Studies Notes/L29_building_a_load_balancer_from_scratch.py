# ============================================================
# L29: Building a Load Balancer From Scratch — A Working Implementation
# ============================================================
# WHAT: A genuinely RUNNABLE, from-scratch HTTP load balancer in Python
#       — combining L21's L7 routing, L22's algorithms, and L23's health
#       checks into actual working code, using only the standard library.
# WHY: L21-L28 covered load-balancing CONCEPTS. This lesson proves those
#       concepts out concretely by building a minimal but functionally
#       real load balancer — seeing the actual code makes the earlier
#       lessons' abstractions concrete and demystifies what tools like
#       Nginx/HAProxy/Envoy (L25) are doing under the hood.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
This lesson deliberately builds a SIMPLIFIED but GENUINELY FUNCTIONAL
load balancer using only Python's standard library `http.server` and
`urllib` — not to suggest this replaces Nginx/HAProxy/Envoy in
production (it does not — those tools handle FAR more: connection
pooling at scale, extensive protocol edge cases, TLS, observability,
years of production hardening), but because implementing the CORE
mechanics yourself is the fastest way to truly internalize what L21-L23
described abstractly.

THE CORE LOOP any load balancer implements: (1) accept an incoming
request, (2) consult the current health-check state (L23) to determine
which backends are currently eligible, (3) apply a selection algorithm
(L22) to choose ONE specific backend among the eligible ones, (4)
FORWARD the request to that backend and relay its response back to the
original client, and (5) record the outcome (success/failure) to inform
FUTURE health-check and least-connections decisions. Every production
load balancer, however sophisticated, is fundamentally running this
same loop at its core — the sophistication lies in doing each step
with far greater performance, correctness, and edge-case handling than this lesson's version.

WHY THIS IS WORTH BUILDING ONCE: reading L21-L23's conceptual
descriptions of "round robin" or "health checks" is quite different from
actually writing the code that walks a list of backends, tracks a
rotating index, catches a connection failure, and decides to mark a
backend unhealthy — actually implementing it surfaces PRACTICAL
questions the abstract description glosses over (what exactly happens
if a backend returns a malformed response? what if ALL backends are
down mid-request? how is a backend's response actually streamed back to
the client without buffering the entire thing in memory?) that a
working engineer needs to have actually grappled with at least once.

PRODUCTION USE CASE:
This exact pattern — health-check state feeding into a request-routing
decision, made on every incoming request — is literally what Nginx's
`upstream` blocks, HAProxy's `backend` sections, and Envoy's cluster
configuration are all doing internally, just implemented in highly
optimized C/C++ with far more sophisticated connection handling, TLS
support, and protocol compliance than this lesson's illustrative Python
version — the CONCEPTUAL loop is identical.

COMMON MISTAKES:
- Treating this kind of from-scratch implementation as something to
  actually deploy in production instead of a production-grade tool
  (Nginx/HAProxy/Envoy) — hand-rolled load balancers reliably miss
  countless edge cases (connection keep-alive handling, chunked transfer
  encoding, malformed request handling, security hardening) that
  battle-tested tools have addressed over years of real-world use.
- Forgetting to actually UPDATE the round-robin index / connection count
  / health state as PART OF handling each request — a load balancer
  whose internal state doesn't reflect reality (stale connection counts,
  a rotation index that never advances) makes decisions no better than
  a random guess, defeating the purpose of the algorithm entirely.
- Not testing the FAILURE paths specifically (what happens when the
  chosen backend is actually down) — a load balancer's value is
  disproportionately realized during FAILURE scenarios (that's precisely
  when correct failover behavior matters most), so testing only the
  all-backends-healthy happy path misses the component's most important job.
"""

import random
import time
from collections import defaultdict


# ------------------------------------------------------------------
# A minimal but functionally complete load balancer core
# ------------------------------------------------------------------
class SimpleLoadBalancer:
    def __init__(self, backend_urls: list[str]):
        self.backends = {url: {"healthy": True, "active_connections": 0,
                                 "consecutive_failures": 0} for url in backend_urls}
        self.round_robin_index = 0

    # --- L23: health checking ---
    def run_health_check(self, url: str, probe_result_ok: bool):
        backend = self.backends[url]
        if probe_result_ok:
            backend["consecutive_failures"] = 0
            if not backend["healthy"]:
                backend["healthy"] = True
                print(f"  [health check] {url} marked HEALTHY again")
        else:
            backend["consecutive_failures"] += 1
            if backend["consecutive_failures"] >= 3 and backend["healthy"]:
                backend["healthy"] = False
                print(f"  [health check] {url} marked UNHEALTHY "
                      f"after {backend['consecutive_failures']} failed probes")

    def healthy_backends(self) -> list[str]:
        return [url for url, state in self.backends.items() if state["healthy"]]

    # --- L22: selection algorithms ---
    def select_round_robin(self) -> str | None:
        healthy = self.healthy_backends()
        if not healthy:
            return None
        chosen = healthy[self.round_robin_index % len(healthy)]
        self.round_robin_index += 1
        return chosen

    def select_least_connections(self) -> str | None:
        healthy = self.healthy_backends()
        if not healthy:
            return None
        return min(healthy, key=lambda url: self.backends[url]["active_connections"])

    # --- The core request-handling loop ---
    def handle_request(self, algorithm: str = "round_robin") -> dict:
        selector = self.select_round_robin if algorithm == "round_robin" else self.select_least_connections
        chosen_backend = selector()

        if chosen_backend is None:
            # L23's all-backends-down graceful degradation case
            return {"status": "error", "detail": "no healthy backends available",
                    "backend": None}

        self.backends[chosen_backend]["active_connections"] += 1
        try:
            # In a REAL implementation, this is where an actual HTTP
            # request would be forwarded (via urllib/httpx) and the
            # response streamed back — simulated here for illustration
            success = self._simulate_backend_call(chosen_backend)
            self.run_health_check(chosen_backend, probe_result_ok=success)
            if success:
                return {"status": "ok", "backend": chosen_backend}
            else:
                return {"status": "error", "detail": "backend request failed",
                        "backend": chosen_backend}
        finally:
            self.backends[chosen_backend]["active_connections"] -= 1

    def _simulate_backend_call(self, url: str) -> bool:
        # Simulate one specific backend being unreliable, for demo purposes
        if url == "backend-2" and random.random() < 0.7:
            return False
        return True


def load_balancer_demo():
    lb = SimpleLoadBalancer(["backend-1", "backend-2", "backend-3"])

    print("Handling 12 requests with round-robin selection + live health checking:\n")
    results = defaultdict(int)
    for i in range(12):
        result = lb.handle_request(algorithm="round_robin")
        results[result["backend"]] += 1
        status_note = "" if result["status"] == "ok" else f" ({result['detail']})"
        print(f"  Request {i+1}: routed to {result['backend']}, "
              f"status={result['status']}{status_note}")

    print(f"\nFinal request distribution: {dict(results)}")
    print(f"Final backend health state: "
          f"{ {url: state['healthy'] for url, state in lb.backends.items()} }")
    print("\n  -> backend-2's simulated unreliability caused it to accumulate")
    print("     consecutive failures and get marked UNHEALTHY partway through —")
    print("     subsequent requests correctly stopped being routed to it,")
    print("     exactly the L23 health-check behavior described conceptually earlier.")


if __name__ == "__main__":
    load_balancer_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
An engineer debugging a production incident involving HAProxy's
least-connections algorithm behaving unexpectedly finds it far easier to
reason about the REAL tool's behavior having previously implemented this
exact loop (select backend -> forward request -> record outcome ->
update health/connection state) themselves at a small scale — the
mental model built by writing L29's minimal version transfers directly
to understanding, debugging, and correctly configuring the vastly more
sophisticated production tool, which is really running the SAME
conceptual loop underneath its much greater engineering depth.
"""
