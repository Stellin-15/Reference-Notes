# =============================================================================
# WHAT: Chaos engineering — principles, fault injection patterns, Python chaos
#       libraries (chaostoolkit), steady-state hypothesis, blast-radius control,
#       Kubernetes fault injection (LitmusChaos/Chaos Mesh), and CI integration.
# WHY:  Failures are inevitable in distributed systems.  Chaos engineering finds
#       weaknesses BEFORE customers do, validates circuit breakers, and builds
#       team confidence in incident response — all in a controlled way.
# LEVEL: Intermediate → Advanced
# =============================================================================

# ---------------------------------------------------------------------------
# CONCEPT OVERVIEW
# ---------------------------------------------------------------------------
# Chaos Engineering (CE) is the discipline of experimenting on a system to
# build confidence in its ability to withstand turbulent conditions.
#
# The Netflix approach (Chaos Monkey, Simian Army) popularised the idea of
# randomly terminating production instances to prove that the system survives.
# Modern CE is more structured:
#
#   1. Define the STEADY STATE — a measurable, normal baseline (e.g., p99 < 200ms,
#      error rate < 0.1 %).
#   2. Hypothesise that the system STAYS in steady state during a fault.
#   3. Introduce the fault (latency, kill a pod, fill a disk…).
#   4. Measure whether the hypothesis HOLDS.
#   5. Roll back and analyse. Fix the weakness. Re-run to validate.
#
# Blast radius control is non-negotiable:
#   - Start in staging/pre-prod.
#   - Use feature flags / kill switches.
#   - Target a small % of traffic or a single replica.
#   - Set automatic rollback triggers.
#   - Always have a human on call during the experiment.
#
# Three layers of fault injection:
#   Application layer:  exception injection, slow response simulation
#   OS/network layer:   tc netem (Linux traffic control), iptables rules
#   Infrastructure:     kill pods, drain nodes, throttle CPUs (cgroups)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# PRODUCTION USE CASE
# ---------------------------------------------------------------------------
# An e-commerce checkout service depends on:
#   - Payment gateway (Stripe)
#   - Inventory service
#   - Recommendation engine
#
# Chaos experiments:
#   Exp-1: Inject 500ms latency into Stripe calls → validates circuit breaker opens.
#   Exp-2: Kill inventory service replicas → validates graceful degradation + retry.
#   Exp-3: Memory pressure on recommendation engine → validates it doesn't cascade.
#   Exp-4: Disk full on logging sidecar → validates app keeps serving (log drop OK).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# COMMON MISTAKES
# ---------------------------------------------------------------------------
# 1. Running chaos experiments without a rollback plan → production outage.
# 2. Skipping the steady-state hypothesis — no hypothesis = no proof of anything.
# 3. Injecting faults into shared infrastructure without alerting adjacent teams.
# 4. Only running chaos in staging — production has unique traffic patterns.
# 5. Not automating chaos in CI — the experiment becomes a one-off novelty.
# 6. Injecting multiple faults simultaneously before understanding single-fault behaviour.
# 7. Testing without observability in place — you won't know if the hypothesis held.
# 8. Chaos without chaos-engineering-as-code → experiments drift, results not reproducible.
# ---------------------------------------------------------------------------

# ── Standard library ────────────────────────────────────────────────────────
import os
import time
import random
import signal
import socket
import threading
import subprocess
import logging
import json
import functools
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Optional, List, Dict, Any, Tuple
from enum import Enum

# ── Third-party: chaos ───────────────────────────────────────────────────────
# pip install chaostoolkit chaostoolkit-lib
# Docs: https://chaostoolkit.org/

# ── Third-party: HTTP ────────────────────────────────────────────────────────
# pip install requests

logger = logging.getLogger(__name__)


# =============================================================================
# SECTION 1 — Steady-State Hypothesis: the foundation of every experiment
# =============================================================================

@dataclass
class SteadyStateProbe:
    """
    A probe measures one aspect of the system's normal behaviour.
    All probes must return True for the system to be in steady state.
    """
    name: str
    tolerance: Any           # expected value or callable returning bool
    probe_fn: Callable       # zero-argument function returning a measurement

    def run(self) -> Tuple[bool, Any]:
        """Execute the probe and check against tolerance."""
        try:
            measurement = self.probe_fn()
            if callable(self.tolerance):
                passed = self.tolerance(measurement)
            else:
                passed = (measurement == self.tolerance)
            return passed, measurement
        except Exception as exc:
            logger.error("Probe '%s' raised: %s", self.name, exc)
            return False, None


@dataclass
class SteadyStateHypothesis:
    """
    Encapsulates all probes that define "normal" for an experiment.
    Run BEFORE injecting faults (to confirm baseline) and AFTER (to verify recovery).
    """
    title: str
    probes: List[SteadyStateProbe] = field(default_factory=list)

    def verify(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Returns (all_passed, results_dict).
        If any probe fails, the hypothesis is rejected.
        """
        results = {}
        all_passed = True
        for probe in self.probes:
            passed, measurement = probe.run()
            results[probe.name] = {"passed": passed, "measurement": measurement}
            if not passed:
                all_passed = False
                logger.warning(
                    "Steady state probe FAILED: %s — measured %s",
                    probe.name,
                    measurement,
                )
        return all_passed, results


# =============================================================================
# SECTION 2 — Fault injectors: application layer
# =============================================================================

class FaultType(str, Enum):
    LATENCY = "latency"
    EXCEPTION = "exception"
    TIMEOUT = "timeout"
    MEMORY_PRESSURE = "memory_pressure"
    CPU_BURN = "cpu_burn"
    DISK_FILL = "disk_fill"


@dataclass
class FaultConfig:
    fault_type: FaultType
    probability: float = 1.0      # 0.0–1.0; 0.1 = inject on 10% of calls
    latency_ms: float = 500.0     # for LATENCY faults
    exception_class: type = Exception
    exception_message: str = "Chaos fault injected"
    duration_s: float = 30.0      # how long the fault runs


class FaultInjector:
    """
    Middleware / decorator that injects faults into function calls.
    Toggle faults at runtime via the enabled flag or an environment variable.
    This is the application-layer injection pattern (no OS privileges needed).
    """

    def __init__(self, config: FaultConfig):
        self.config = config
        # Kill switch: set CHAOS_ENABLED=false to disable all injections.
        self._globally_enabled = os.getenv("CHAOS_ENABLED", "false").lower() == "true"

    @property
    def should_inject(self) -> bool:
        if not self._globally_enabled:
            return False
        return random.random() < self.config.probability

    def inject(self, func: Callable) -> Callable:
        """Decorator that wraps a function with fault injection."""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if self.should_inject:
                fault = self.config.fault_type

                if fault == FaultType.LATENCY:
                    # Simulate upstream slowness — connection established but data delayed.
                    jitter = random.uniform(0, self.config.latency_ms * 0.2)
                    sleep_s = (self.config.latency_ms + jitter) / 1000
                    logger.warning("CHAOS: injecting %.0f ms latency into %s",
                                   self.config.latency_ms, func.__qualname__)
                    time.sleep(sleep_s)

                elif fault == FaultType.EXCEPTION:
                    logger.warning("CHAOS: raising %s in %s",
                                   self.config.exception_class.__name__, func.__qualname__)
                    raise self.config.exception_class(self.config.exception_message)

                elif fault == FaultType.TIMEOUT:
                    # Simulate a timeout by sleeping past any reasonable deadline.
                    logger.warning("CHAOS: simulating timeout in %s", func.__qualname__)
                    time.sleep(60)   # caller's timeout should trigger first

            return func(*args, **kwargs)
        return wrapper


# Concrete fault injectors for different dependencies.
stripe_latency_fault = FaultInjector(
    FaultConfig(
        fault_type=FaultType.LATENCY,
        probability=0.3,          # inject on 30% of calls to Stripe
        latency_ms=800.0,
    )
)

inventory_failure_fault = FaultInjector(
    FaultConfig(
        fault_type=FaultType.EXCEPTION,
        probability=0.5,
        exception_class=ConnectionError,
        exception_message="Inventory service unavailable (chaos fault)",
    )
)


# =============================================================================
# SECTION 3 — Circuit breaker validation through chaos
# =============================================================================

class CircuitBreaker:
    """
    Three-state circuit breaker: CLOSED → OPEN → HALF_OPEN → CLOSED.
    Chaos experiments should validate that:
      1. The breaker OPENS after N consecutive failures.
      2. Requests FAST-FAIL while the breaker is OPEN (no waiting for timeout).
      3. The breaker HALF-OPENs after the recovery timeout and lets one probe through.
      4. Successful probe → CLOSED; failed probe → OPEN again.
    """

    class State(str, Enum):
        CLOSED = "closed"      # normal: calls pass through
        OPEN = "open"          # failing: calls fast-fail immediately
        HALF_OPEN = "half_open"  # recovery: one probe call allowed

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_s: float = 30.0,
        name: str = "default",
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self.name = name
        self._state = self.State.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = threading.Lock()

    @property
    def state(self) -> "CircuitBreaker.State":
        return self._state

    def call(self, func: Callable, *args, **kwargs):
        """
        Wrap a function call with circuit-breaker logic.
        Raises CircuitBreakerOpenError immediately if the circuit is OPEN.
        """
        with self._lock:
            if self._state == self.State.OPEN:
                elapsed = time.monotonic() - (self._last_failure_time or 0)
                if elapsed >= self.recovery_timeout_s:
                    # Transition to HALF_OPEN: let one probe through.
                    self._state = self.State.HALF_OPEN
                    logger.info("CircuitBreaker[%s] → HALF_OPEN", self.name)
                else:
                    # Still within recovery window — fast-fail.
                    raise RuntimeError(
                        f"CircuitBreaker[{self.name}] is OPEN — fast fail "
                        f"(retry in {self.recovery_timeout_s - elapsed:.1f}s)"
                    )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            if self._state == self.State.HALF_OPEN:
                self._state = self.State.CLOSED
                logger.info("CircuitBreaker[%s] → CLOSED (recovered)", self.name)

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self.failure_threshold or self._state == self.State.HALF_OPEN:
                self._state = self.State.OPEN
                logger.warning(
                    "CircuitBreaker[%s] → OPEN after %d failures",
                    self.name,
                    self._failure_count,
                )


# =============================================================================
# SECTION 4 — Memory pressure fault injection
# =============================================================================

@contextmanager
def inject_memory_pressure(target_mb: int = 256, duration_s: float = 30.0):
    """
    Allocate a large buffer to simulate a memory-constrained environment.
    Validates that services degrade gracefully (shedding load, not crashing).

    WARNING: On systems with limited RAM + no swap, this can cause OOM kills.
    Always test in a controlled environment with cgroup memory limits.
    """
    logger.warning("CHAOS: allocating %d MB memory pressure for %.0f s", target_mb, duration_s)
    # Pre-allocate and touch the memory so the OS actually commits pages.
    pressure = bytearray(target_mb * 1024 * 1024)
    # Touch every page to force physical allocation (avoid copy-on-write).
    for i in range(0, len(pressure), 4096):
        pressure[i] = 0xFF
    try:
        yield pressure
    finally:
        del pressure   # release the allocation
        logger.info("CHAOS: memory pressure released")


# =============================================================================
# SECTION 5 — Network chaos via Linux tc netem (OS layer)
# =============================================================================

class NetworkChaos:
    """
    Uses Linux `tc netem` to inject network faults at the kernel level.
    This affects ALL processes on the interface — far more realistic than
    application-layer injection.

    Requires: root/sudo OR CAP_NET_ADMIN capability (e.g., in a privileged container).
    Interface: typically 'eth0' in containers, 'ens3' on VMs.

    Always run cleanup() in a finally block — stale tc rules survive process restarts.
    """

    def __init__(self, interface: str = "eth0"):
        self.interface = interface
        self._active = False

    def inject_latency(self, latency_ms: int = 100, jitter_ms: int = 10) -> None:
        """Add latency + jitter to all outgoing packets on the interface."""
        cmd = [
            "tc", "qdisc", "add", "dev", self.interface,
            "root", "netem",
            "delay", f"{latency_ms}ms", f"{jitter_ms}ms",
            "distribution", "normal",  # realistic bell-curve jitter
        ]
        self._run(cmd)
        self._active = True
        logger.warning("CHAOS: %d ms ±%d ms latency on %s", latency_ms, jitter_ms, self.interface)

    def inject_packet_loss(self, loss_pct: float = 5.0) -> None:
        """Drop loss_pct% of packets — simulates flaky network."""
        cmd = [
            "tc", "qdisc", "add", "dev", self.interface,
            "root", "netem",
            "loss", f"{loss_pct}%",
        ]
        self._run(cmd)
        self._active = True
        logger.warning("CHAOS: %.1f%% packet loss on %s", loss_pct, self.interface)

    def inject_bandwidth_limit(self, rate_kbps: int = 1000) -> None:
        """Throttle bandwidth to rate_kbps — simulates degraded WAN link."""
        # tbf (token bucket filter) for bandwidth; netem for latency.
        cmd = [
            "tc", "qdisc", "add", "dev", self.interface,
            "root", "tbf",
            "rate", f"{rate_kbps}kbit",
            "burst", "32kbit",
            "latency", "400ms",
        ]
        self._run(cmd)
        self._active = True
        logger.warning("CHAOS: bandwidth limited to %d kbps on %s", rate_kbps, self.interface)

    def cleanup(self) -> None:
        """Remove ALL tc rules from the interface. Always call this on exit."""
        if self._active:
            cmd = ["tc", "qdisc", "del", "dev", self.interface, "root"]
            self._run(cmd, check=False)   # don't raise if already clean
            self._active = False
            logger.info("CHAOS: network rules cleared on %s", self.interface)

    def _run(self, cmd: List[str], check: bool = True) -> None:
        logger.debug("Running: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise RuntimeError(f"tc command failed: {result.stderr.strip()}")


@contextmanager
def network_chaos(interface: str = "eth0", **fault_kwargs):
    """
    Context manager that ensures network chaos is cleaned up on exit.
    Usage:
        with network_chaos(interface="eth0", latency_ms=200, jitter_ms=20):
            run_load_test()
    """
    chaos = NetworkChaos(interface)
    fault_type = next((k for k in fault_kwargs if k in
                       ["latency_ms", "loss_pct", "rate_kbps"]), None)
    try:
        if "latency_ms" in fault_kwargs:
            chaos.inject_latency(**{k: v for k, v in fault_kwargs.items()
                                     if k in ["latency_ms", "jitter_ms"]})
        elif "loss_pct" in fault_kwargs:
            chaos.inject_packet_loss(fault_kwargs["loss_pct"])
        elif "rate_kbps" in fault_kwargs:
            chaos.inject_bandwidth_limit(fault_kwargs["rate_kbps"])
        yield chaos
    finally:
        chaos.cleanup()


# =============================================================================
# SECTION 6 — CPU throttling fault
# =============================================================================

class CPUBurner:
    """
    Spin up threads that consume CPU cycles to simulate CPU contention.
    Validates that services handle CPU throttling without cascading failures.
    In Kubernetes this is equivalent to setting CPU limits lower than requests.
    """

    def __init__(self, num_threads: int = 2, duration_s: float = 30.0):
        self.num_threads = num_threads
        self.duration_s = duration_s
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []

    def start(self) -> None:
        logger.warning("CHAOS: starting %d CPU burn threads for %.0f s",
                        self.num_threads, self.duration_s)
        for i in range(self.num_threads):
            t = threading.Thread(
                target=self._burn,
                name=f"cpu-burn-{i}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)

        # Auto-stop after duration.
        threading.Timer(self.duration_s, self.stop).start()

    def stop(self) -> None:
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=2.0)
        logger.info("CHAOS: CPU burn stopped")

    def _burn(self) -> None:
        """Spin on pure Python arithmetic — bypasses GIL via tight loop."""
        while not self._stop_event.is_set():
            _ = sum(i * i for i in range(10_000))   # busy-wait calculation


# =============================================================================
# SECTION 7 — ChaosToolkit experiment as Python dict (JSON format)
# =============================================================================

CHAOSTOOLKIT_EXPERIMENT = {
    "version": "1.0.0",
    "title": "System survives Stripe API latency spike",
    "description": (
        "Validate that the checkout service circuit breaker opens "
        "and returns a graceful degraded response when Stripe latency exceeds 1s."
    ),
    "tags": ["payment", "circuit-breaker", "latency"],
    "configuration": {
        "service_url": {"type": "env", "key": "CHECKOUT_SERVICE_URL",
                        "default": "http://localhost:8080"},
    },
    "steady-state-hypothesis": {
        "title": "Checkout service is healthy",
        "probes": [
            {
                "type": "probe",
                "name": "service_is_up",
                "tolerance": 200,
                "provider": {
                    "type": "http",
                    "url": "${service_url}/health",
                    "timeout": 3,
                    "expected_status": 200,
                },
            },
            {
                "type": "probe",
                "name": "error_rate_below_threshold",
                "tolerance": True,   # probe function returns bool
                "provider": {
                    "type": "python",
                    "module": "chaos_probes",   # your probes module
                    "func": "error_rate_below_one_percent",
                },
            },
        ],
    },
    "method": [
        {
            "type": "action",
            "name": "inject_stripe_latency",
            "provider": {
                "type": "python",
                "module": "chaos_actions",
                "func": "inject_latency",
                "arguments": {"target": "stripe_client", "latency_ms": 1200},
            },
        },
        {
            "type": "probe",
            "name": "checkout_still_responds",
            "provider": {
                "type": "http",
                "url": "${service_url}/checkout",
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": '{"cart_id": "test-123"}',
                "timeout": 5,
            },
            "tolerance": {
                "type": "range",
                "range": [200, 503],   # accept both success and graceful error
            },
        },
    ],
    "rollbacks": [
        {
            "type": "action",
            "name": "remove_stripe_latency",
            "provider": {
                "type": "python",
                "module": "chaos_actions",
                "func": "remove_latency",
                "arguments": {"target": "stripe_client"},
            },
        },
    ],
}


def save_experiment_json(path: str = "/tmp/experiment.json") -> None:
    """Write the experiment definition to disk for chaostoolkit CLI."""
    with open(path, "w") as f:
        json.dump(CHAOSTOOLKIT_EXPERIMENT, f, indent=2)
    logger.info("Experiment written to %s — run: chaos run %s", path, path)


# =============================================================================
# SECTION 8 — Game Day planning template
# =============================================================================

GAME_DAY_TEMPLATE = """
# Game Day Plan — {title}
Date: {date}
Facilitator: {facilitator}
On-call: {oncall}

## Participants
- SRE team lead
- Service owner
- Infrastructure engineer
- Product representative (to observe)

## System Under Test
Service: {service}
Environment: STAGING (never production for first run)
Traffic: synthetic load at 50% of peak

## Pre-flight Checklist
- [ ] Monitoring dashboards open for all participants
- [ ] Runbook for the service reviewed
- [ ] Rollback procedure documented and tested
- [ ] Blast radius scoped (single replica, feature-flagged users)
- [ ] Stakeholders notified via #chaos-engineering Slack channel
- [ ] Incident bridge open (but muted — this is not an incident yet)

## Steady-State Probes
- HTTP /health returns 200 in < 100 ms
- Error rate < 0.1% (measured via Prometheus: rate(http_requests_total{status=~"5.."}[1m]))
- p99 latency < 200 ms

## Experiments (in order of increasing blast radius)
1. Single dependency failure (low risk)
2. Increased latency to downstream (medium risk)
3. Total dependency outage (high risk — abort if steady state breaks in step 1)

## Abort Criteria
- Any probe fails in steady-state verification before fault injection
- p99 > 2s sustained for > 30 s
- Error rate > 5%
- On-call engineer cannot reach rollback in < 2 min

## Post-Game Day
- Document all findings in Confluence
- File Jira tickets for weaknesses discovered
- Schedule re-run after fixes are deployed
"""


# =============================================================================
# SECTION 9 — Kubernetes fault injection: LitmusChaos / Chaos Mesh manifests
# =============================================================================

LITMUS_POD_DELETE_EXPERIMENT = """
# LitmusChaos: pod-delete experiment
# Deletes random pods in the target deployment to validate self-healing.
# kubectl apply -f this file, then observe the ChaosResult resource.

apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: checkout-pod-delete
  namespace: checkout
spec:
  appinfo:
    appns: checkout
    applabel: "app=checkout-service"
    appkind: deployment
  engineState: active
  chaosServiceAccount: litmus-admin
  experiments:
    - name: pod-delete
      spec:
        components:
          env:
            - name: TOTAL_CHAOS_DURATION   # total experiment run time
              value: "60"
            - name: CHAOS_INTERVAL          # seconds between pod deletions
              value: "10"
            - name: FORCE                   # use SIGKILL vs graceful shutdown
              value: "false"
            - name: PODS_AFFECTED_PERC      # percentage of pods to delete
              value: "50"                   # blast-radius: only half the replicas
"""

CHAOS_MESH_NETWORK_DELAY = """
# Chaos Mesh: NetworkChaos — inject latency between services
# Apply this to a namespace to add 300ms delay to traffic from checkout → inventory.

apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: inventory-latency
  namespace: checkout
spec:
  action: delay
  mode: all                   # target all matching pods
  selector:
    namespaces: [checkout]
    labelSelectors:
      app: checkout-service
  delay:
    latency: "300ms"
    correlation: "25"         # correlation between successive delays (%)
    jitter: "50ms"            # random jitter ± 50ms
  direction: to               # inject on egress (to inventory service)
  target:
    selector:
      namespaces: [inventory]
      labelSelectors:
        app: inventory-service
    mode: all
  duration: "60s"             # auto-clean after 60 seconds
"""


# =============================================================================
# SECTION 10 — Dependency failure simulation with retry and fallback
# =============================================================================

class DependencySimulator:
    """
    Simulates a flaky dependency (HTTP service, DB, queue) for unit/integration
    testing of retry logic and fallback behaviour.
    """

    def __init__(
        self,
        failure_rate: float = 0.3,
        latency_p50_ms: float = 50,
        latency_p99_ms: float = 500,
    ):
        self.failure_rate = failure_rate
        self.latency_p50 = latency_p50_ms
        self.latency_p99 = latency_p99_ms
        self.call_count = 0
        self.failure_count = 0

    def call(self, endpoint: str, payload: dict) -> dict:
        """
        Simulates an HTTP call with realistic failure distribution.
        Raises ConnectionError on simulated failures.
        """
        self.call_count += 1

        # Simulate latency from a log-normal distribution (realistic for HTTP).
        latency_ms = random.lognormvariate(
            mu=3.9,      # ≈ ln(50) → median ~50ms
            sigma=0.8,   # variance gives long tail to ~500ms p99
        )
        time.sleep(min(latency_ms, self.latency_p99) / 1000)

        if random.random() < self.failure_rate:
            self.failure_count += 1
            raise ConnectionError(f"Simulated failure for {endpoint} (fault #{self.failure_count})")

        return {"status": "ok", "endpoint": endpoint, "latency_ms": round(latency_ms, 1)}

    def stats(self) -> dict:
        return {
            "total_calls": self.call_count,
            "failures": self.failure_count,
            "failure_rate_actual": (
                self.failure_count / self.call_count if self.call_count else 0
            ),
        }


def retry_with_backoff(
    func: Callable,
    max_attempts: int = 3,
    base_delay_s: float = 0.1,
    max_delay_s: float = 5.0,
    exceptions: tuple = (ConnectionError, TimeoutError),
):
    """
    Exponential backoff with full jitter — the preferred retry strategy.
    Full jitter avoids thundering herd when all clients retry simultaneously.

    Chaos test: combine with DependencySimulator(failure_rate=0.5) and
    verify that all requests eventually succeed within max_attempts.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except exceptions as exc:
            if attempt == max_attempts:
                logger.error("All %d retry attempts exhausted: %s", max_attempts, exc)
                raise
            # Full jitter: sleep random value in [0, min(cap, base * 2^attempt)]
            cap = min(max_delay_s, base_delay_s * (2 ** attempt))
            sleep_s = random.uniform(0, cap)
            logger.warning(
                "Attempt %d/%d failed (%s), retrying in %.2f s",
                attempt, max_attempts, exc, sleep_s,
            )
            time.sleep(sleep_s)


# =============================================================================
# SECTION 11 — Chaos experiments in CI
# =============================================================================

CHAOS_CI_PIPELINE = """
# .github/workflows/chaos.yml — Run chaos experiments as part of CI
# Trigger: pull requests to main, or nightly scheduled run.

name: Chaos Tests
on:
  schedule:
    - cron: '0 2 * * *'   # nightly at 02:00 UTC
  workflow_dispatch:        # manual trigger

jobs:
  chaos:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Start services (docker-compose)
        run: docker-compose -f docker-compose.test.yml up -d
        # Includes: app, mock stripe, mock inventory, prometheus, grafana

      - name: Wait for services to be healthy
        run: |
          for i in $(seq 1 30); do
            curl -sf http://localhost:8080/health && break || sleep 2
          done

      - name: Install chaostoolkit
        run: pip install chaostoolkit chaostoolkit-lib

      - name: Verify steady state (pre-experiment)
        run: chaos verify experiment.json

      - name: Run chaos experiment (latency injection)
        run: chaos run experiments/stripe-latency.json
        # Fails CI if steady-state hypothesis is violated post-fault

      - name: Run chaos experiment (dependency failure)
        run: chaos run experiments/inventory-failure.json

      - name: Collect and archive results
        if: always()
        run: |
          cp chaos-report-*.json artifacts/
          docker-compose logs > artifacts/service-logs.txt
        # Upload to artifact store for debugging

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: chaos-results
          path: artifacts/
"""


# =============================================================================
# SECTION 12 — Full experiment runner
# =============================================================================

@dataclass
class ChaosExperiment:
    """
    Orchestrates a complete chaos engineering experiment:
    1. Verify steady state before fault.
    2. Inject fault.
    3. Run workload during fault.
    4. Verify steady state after fault.
    5. Rollback.
    6. Report.
    """
    name: str
    hypothesis: SteadyStateHypothesis
    fault_inject: Callable       # zero-arg function that activates the fault
    fault_rollback: Callable     # zero-arg function that removes the fault
    workload: Callable           # zero-arg function to run during the fault
    fault_duration_s: float = 30.0

    def run(self) -> Dict[str, Any]:
        report = {"experiment": self.name, "result": "unknown", "probes": {}}

        # Step 1: verify the system is in a good baseline state.
        logger.info("[%s] Verifying steady state (pre-fault)…", self.name)
        pre_ok, pre_results = self.hypothesis.verify()
        report["probes"]["pre_fault"] = pre_results
        if not pre_ok:
            report["result"] = "ABORTED (pre-fault baseline violated)"
            logger.error("[%s] Aborting — baseline not met.", self.name)
            return report

        # Step 2: inject fault.
        logger.warning("[%s] Injecting fault…", self.name)
        try:
            self.fault_inject()
        except Exception as exc:
            report["result"] = f"ABORTED (fault injection failed: {exc})"
            return report

        # Step 3: run workload WHILE fault is active.
        try:
            logger.info("[%s] Running workload for %.0f s…", self.name, self.fault_duration_s)
            self.workload()
            time.sleep(self.fault_duration_s)
        finally:
            # Step 4: always rollback, even if workload crashed.
            logger.info("[%s] Rolling back fault…", self.name)
            try:
                self.fault_rollback()
            except Exception as exc:
                logger.error("[%s] Rollback failed: %s — MANUAL INTERVENTION NEEDED", self.name, exc)

        # Step 5: verify hypothesis holds after rollback.
        time.sleep(5)   # brief stabilisation window
        logger.info("[%s] Verifying steady state (post-fault)…", self.name)
        post_ok, post_results = self.hypothesis.verify()
        report["probes"]["post_fault"] = post_results
        report["result"] = "PASSED" if post_ok else "FAILED (hypothesis violated)"

        logger.info("[%s] Experiment result: %s", self.name, report["result"])
        return report


# =============================================================================
# DEMO
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    # ── 1. Demonstrate circuit breaker with fault injection ──────────────────
    print("\n=== Circuit Breaker Validation ===")
    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout_s=5.0, name="inventory")
    dep = DependencySimulator(failure_rate=0.8)   # very flaky dependency

    for i in range(10):
        try:
            result = breaker.call(dep.call, "/inventory/check", {"sku": "ABC"})
            print(f"  Call {i+1}: OK — {result}")
        except RuntimeError as exc:
            print(f"  Call {i+1}: FAST-FAIL — {exc}")
        except ConnectionError as exc:
            print(f"  Call {i+1}: DEP ERROR — {exc}")
        time.sleep(0.5)

    print("Dep stats:", dep.stats())

    # ── 2. Retry with backoff ────────────────────────────────────────────────
    print("\n=== Retry with Exponential Backoff ===")
    dep2 = DependencySimulator(failure_rate=0.6)
    for call_num in range(3):
        try:
            result = retry_with_backoff(
                lambda: dep2.call("/payment/charge", {"amount": 99}),
                max_attempts=4,
                base_delay_s=0.05,
            )
            print(f"  Request {call_num+1}: SUCCESS after retries")
        except ConnectionError:
            print(f"  Request {call_num+1}: EXHAUSTED retries")

    # ── 3. Memory pressure ───────────────────────────────────────────────────
    print("\n=== Memory Pressure (50 MB for 2 s) ===")
    with inject_memory_pressure(target_mb=50, duration_s=2.0):
        time.sleep(2.0)
    print("  Memory pressure released OK")

    # ── 4. Full experiment run ───────────────────────────────────────────────
    print("\n=== Full Chaos Experiment ===")

    call_log: List[str] = []
    fault_active = threading.Event()

    def _probe_service_up():
        return True   # mock: real probe would HTTP GET /health

    def _probe_error_rate():
        return len([c for c in call_log if c == "error"]) / max(len(call_log), 1) < 0.5

    hypothesis = SteadyStateHypothesis(
        title="Service handles dependency failures gracefully",
        probes=[
            SteadyStateProbe("service_up", True, _probe_service_up),
            SteadyStateProbe("error_rate_below_50pct", True, _probe_error_rate),
        ],
    )

    sim = DependencySimulator(failure_rate=0.0)   # healthy initially

    def inject():
        sim.failure_rate = 0.7   # fault: 70% failure rate
        fault_active.set()

    def rollback():
        sim.failure_rate = 0.0   # restore
        fault_active.clear()

    def workload():
        for _ in range(10):
            try:
                sim.call("/api/data", {})
                call_log.append("ok")
            except ConnectionError:
                call_log.append("error")

    experiment = ChaosExperiment(
        name="dependency-failure-70pct",
        hypothesis=hypothesis,
        fault_inject=inject,
        fault_rollback=rollback,
        workload=workload,
        fault_duration_s=1.0,
    )

    report = experiment.run()
    print("Experiment report:", json.dumps(report, indent=2))
