# =============================================================================
# WHAT: Application Performance Monitoring (APM) and continuous profiling —
#       py-spy, Pyroscope, tracemalloc, memray, cProfile, line_profiler,
#       network/DB tracking, RUM vs synthetic, custom perf counters, and
#       performance regression detection.
# WHY:  Metrics and traces tell you THAT something is slow.  Profiling tells
#       you WHERE the CPU cycles and memory allocations actually go — essential
#       for fixing p99 latency spikes, memory leaks, and query storms.
# LEVEL: Intermediate → Advanced
# =============================================================================

# ---------------------------------------------------------------------------
# CONCEPT OVERVIEW
# ---------------------------------------------------------------------------
# APM = the practice of continuously measuring application behavior in production
# so that performance regressions surface before customers report them.
#
# Three complementary lenses:
#   1. CPU profiling   — which functions consume the most CPU time?
#   2. Memory profiling — which call sites allocate the most memory?
#   3. I/O profiling   — where does the process block on network/disk/DB?
#
# Profiling taxonomy:
#   Deterministic (instrumentation-based): records EVERY call — accurate but
#     high overhead (10–50%). Use only in dev/staging.
#   Statistical (sampling): interrupts the process at N Hz and records a stack
#     snapshot — ~1–5% overhead, safe in production.
#
# Tools by category:
#   CPU sampling:     py-spy (out-of-process), Pyroscope SDK (in-process)
#   CPU deterministic: cProfile (stdlib), line_profiler (line granularity)
#   Memory sampling:  memray (low overhead, production-safe mode)
#   Memory tracking:  tracemalloc (stdlib, snapshot-diff approach)
#   Continuous APM:   Datadog APM, New Relic, Elastic APM (all use sampling)
#   DB:               slow query logs, sqlalchemy event listeners
#   Network:          socket-level hooks, DNS timing via getaddrinfo wrapping
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# PRODUCTION USE CASE
# ---------------------------------------------------------------------------
# An ML inference service (FastAPI + PyTorch) hitting p99 > 2 s SLO.
# Investigation path:
#   1. py-spy top — confirms the model forward pass + tokenisation are hot spots.
#   2. memray — finds a numpy array allocated per-token never freed (leak).
#   3. cProfile report — reveals a slow regex inside preprocessing.
#   4. SQLAlchemy event listener — catches 47 N+1 queries per request.
#   5. Pyroscope continuous profiling — deployed post-fix to catch regressions.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# COMMON MISTAKES
# ---------------------------------------------------------------------------
# 1. Running cProfile in production — deterministic overhead is too high.
# 2. Profiling a "toy" workload — always profile under realistic concurrency.
# 3. Interpreting flame graphs top-down instead of bottom-up (wide base = hot).
# 4. Forgetting to account for GC pauses when measuring CPU time.
# 5. Using time.time() for perf measurement — use time.perf_counter() instead.
# 6. Trusting average latency; always look at p95/p99 for user-facing impact.
# 7. N+1 queries: querying inside a loop without noticing — always log query count.
# 8. Not establishing a baseline before optimisation — "faster than what?".
# 9. Memory leak diagnosis stopped at "RSS growing" without malloc-level evidence.
# 10. Shipping profiling overhead to production without a kill-switch toggle.
# ---------------------------------------------------------------------------

# ── Standard library ────────────────────────────────────────────────────────
import cProfile
import pstats
import io
import tracemalloc
import time
import random
import statistics
import functools
import logging
import os
import gc
import socket
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Optional, List, Dict, Any

# ── Third-party: profiling ────────────────────────────────────────────────────
# pip install pyroscope-io memray line-profiler

# ── Third-party: APM SDKs ────────────────────────────────────────────────────
# pip install ddtrace elastic-apm newrelic

# ── Third-party: database / web ──────────────────────────────────────────────
# pip install sqlalchemy

logger = logging.getLogger(__name__)


# =============================================================================
# SECTION 1 — cProfile: deterministic CPU profiling (dev/staging only)
# =============================================================================

@contextmanager
def cprofile_section(sort_key: str = "cumulative", top_n: int = 20):
    """
    Context manager that profiles a code block and prints the top N functions
    sorted by cumulative time (total time including callees).

    Sort options: 'cumulative', 'tottime' (self only), 'calls', 'pcalls'.
    Use 'tottime' to find CPU-bound hot spots.
    Use 'cumulative' to find slow call chains.
    """
    pr = cProfile.Profile()
    pr.enable()
    try:
        yield pr
    finally:
        pr.disable()
        stream = io.StringIO()
        ps = pstats.Stats(pr, stream=stream)
        ps.strip_dirs()                          # shorten file paths
        ps.sort_stats(sort_key)
        ps.print_stats(top_n)
        print(stream.getvalue())


def demo_cprofile():
    """Example: profile a CPU-bound data-processing function."""

    def process_records(n: int) -> list:
        """Simulate a data pipeline with a hidden inefficiency."""
        results = []
        for i in range(n):
            # Inefficiency: sorting inside loop instead of once outside.
            data = sorted(range(1000), reverse=i % 2 == 0)
            results.append(sum(data))
        return results

    with cprofile_section(sort_key="tottime", top_n=10):
        process_records(500)   # profile 500 iterations


# =============================================================================
# SECTION 2 — line_profiler: line-by-line CPU breakdown
# =============================================================================

def profile_line_by_line(func: Callable) -> None:
    """
    line_profiler wraps a function and reports % time per line.
    Much more granular than cProfile but requires @profile decorator OR
    the kernprof CLI runner: kernprof -l -v script.py

    Usage from code (no kernprof):
        from line_profiler import LineProfiler
        lp = LineProfiler()
        lp.add_function(my_func)
        lp_wrapper = lp(my_func)
        lp_wrapper(*args)
        lp.print_stats()
    """
    try:
        from line_profiler import LineProfiler
    except ImportError:
        logger.warning("line_profiler not installed. pip install line-profiler")
        return

    lp = LineProfiler()
    lp.add_function(func)
    lp_wrapper = lp(func)

    # Run the function with dummy args (replace with real args in practice).
    try:
        lp_wrapper()
    except TypeError:
        pass   # function may require args not supplied in this demo

    buf = io.StringIO()
    lp.print_stats(stream=buf)
    print(buf.getvalue())


# =============================================================================
# SECTION 3 — tracemalloc: memory allocation tracking (stdlib)
# =============================================================================

def demo_tracemalloc():
    """
    tracemalloc takes memory snapshots and computes the diff to find allocations.
    Identifies the CALL SITE (file + line) that allocated memory, not just the
    object type — critical for pinpointing leaks.

    Overhead: ~5–30% depending on nframes (stack depth captured).
    Not safe for long-running production use; use memray instead.
    """
    tracemalloc.start(nframes=10)   # capture 10 stack frames per allocation
    snapshot1 = tracemalloc.take_snapshot()

    # --- Simulate a memory-leaking operation -----------------------------------
    _global_cache = []   # objects appended here are never freed
    for _ in range(10_000):
        _global_cache.append(bytearray(1024))   # 1 KB per item = 10 MB total

    snapshot2 = tracemalloc.take_snapshot()

    # Filter to only our code (exclude stdlib internals).
    filters = [
        tracemalloc.Filter(inclusive=True, filename_pattern="*apm_and_profiling*"),
    ]
    top_stats = snapshot2.compare_to(snapshot1, "lineno", cumulative=True)

    print("=== tracemalloc top memory differences ===")
    for stat in top_stats[:10]:
        print(stat)

    tracemalloc.stop()   # always stop to free tracing overhead


# =============================================================================
# SECTION 4 — memray: production-grade memory profiling
# =============================================================================

MEMRAY_USAGE = """
memray is a low-overhead memory profiler that hooks into CPython's allocator.
It records every malloc/free with a stack trace and produces flame graph HTML reports.

CLI usage (tracks a full script run):
    memray run -o output.bin my_script.py
    memray flamegraph output.bin          # generates flamegraph.html
    memray summary output.bin             # tabular summary
    memray stats output.bin               # peak memory, allocations

Programmatic API (track a section):
    import memray
    with memray.Tracker("output.bin"):
        run_expensive_function()

Production (live reporting mode — minimal overhead):
    memray run --live my_server.py        # real-time TUI in terminal

Filtering:
    memray flamegraph --temporal output.bin   # time-ordered view
    memray flamegraph --leaks output.bin      # only unreachable allocations

Common findings:
    - PyTorch tensor caching not cleared between requests
    - Pandas DataFrame copies created by chained indexing
    - Logging formatters allocating large strings on every record
"""


def demo_memray_api():
    """Show programmatic memray usage."""
    try:
        import memray
        output_file = "/tmp/memray_demo.bin"
        with memray.Tracker(output_file):
            # Track this block — all allocations recorded with stack traces.
            data = [bytearray(1024) for _ in range(5_000)]  # 5 MB allocation
            del data
        logger.info("memray output written to %s — run `memray flamegraph %s`",
                    output_file, output_file)
    except ImportError:
        logger.warning("memray not installed. pip install memray")


# =============================================================================
# SECTION 5 — py-spy: out-of-process CPU sampling
# =============================================================================

PYSPY_USAGE = """
py-spy attaches to a RUNNING process without any code changes.
It reads the CPython interpreter state from /proc/<pid>/mem (Linux) or
via ptrace (macOS) to reconstruct the Python call stack.

Key commands:
    py-spy top --pid 1234              # live htop-style CPU view
    py-spy record -o profile.svg --pid 1234 --duration 30
                                       # 30s flame graph SVG
    py-spy dump --pid 1234             # one-shot stack dump (good for deadlock diagnosis)

Flags:
    --rate 100      # samples per second (default 100; lower for less overhead)
    --subprocesses  # include child processes
    --threads       # show all threads separately
    --idle          # include threads sleeping in I/O (useful for I/O-bound apps)
    --nonblocking   # never blocks the process (safe for prod but may miss GIL-held frames)

Production workflow:
    1. Alert fires: p99 > SLO threshold.
    2. SSH to pod/instance.
    3. py-spy top --pid $(pgrep -f gunicorn) --rate 50
    4. Immediately see which function is hot without redeploying.
    5. py-spy record for 60 s to capture a flame graph.
    6. Share SVG with team for async analysis.
"""


# =============================================================================
# SECTION 6 — Pyroscope: continuous profiling in production
# =============================================================================

def setup_pyroscope(app_name: str = "inference-service") -> None:
    """
    Pyroscope continuously samples CPU (and optionally memory) at low overhead
    and ships profiles to a Pyroscope server (OSS or Grafana Cloud).

    Profiles are stored as flame graphs queryable by time range, labels, and
    compared across deploys — this is the production-safe replacement for py-spy.

    Label strategy: always include version + environment so you can diff
    "before deploy" vs "after deploy" flame graphs.
    """
    try:
        import pyroscope
    except ImportError:
        logger.warning("pyroscope-io not installed. pip install pyroscope-io")
        return

    pyroscope.configure(
        application_name=app_name,
        server_address=os.getenv("PYROSCOPE_SERVER", "http://localhost:4040"),
        # Labels become dimensions for filtering — keep cardinality low.
        tags={
            "version": os.getenv("APP_VERSION", "unknown"),
            "env": os.getenv("ENV", "production"),
            "region": os.getenv("AWS_REGION", "us-east-1"),
        },
        # sample_rate: Hz of sampling.  100 Hz = ~0.5% CPU overhead.
        # Lower to 50 Hz for very CPU-bound services.
        sample_rate=100,
        detect_subprocesses=False,   # True only if using multiprocessing
        oncpu=True,                  # CPU profiling (default on)
        gil_only=False,              # False = include threads blocked in C extensions
    )
    logger.info("Pyroscope continuous profiling active → %s",
                os.getenv("PYROSCOPE_SERVER", "http://localhost:4040"))


@contextmanager
def pyroscope_tag_context(**tags):
    """
    Tag a code block so its profiling data is filterable in Pyroscope UI.
    Use for: endpoint name, job type, model version, tenant tier.

    Example:
        with pyroscope_tag_context(endpoint="/predict", model="gpt2"):
            result = model.generate(inputs)
    """
    try:
        import pyroscope
        with pyroscope.tag_wrapper(tags):
            yield
    except ImportError:
        yield   # no-op if pyroscope not installed — code still runs


# =============================================================================
# SECTION 7 — Network profiling: DNS timing + connection tracking
# =============================================================================

@dataclass
class DNSResult:
    hostname: str
    resolved_ip: str
    resolution_time_ms: float
    cached: bool = False


def time_dns_resolution(hostname: str) -> DNSResult:
    """
    DNS slowness is a common hidden latency source, especially in Kubernetes
    where ndots=5 causes multiple DNS lookups per hostname.

    Mitigation:
      - Use fully-qualified domain names (hostname.namespace.svc.cluster.local.)
        to avoid the search domain fallback loop.
      - Enable DNS caching in the pod (dnsConfig.ndots=2 in PodSpec).
      - Monitor dns_lookup_duration_ms as a custom metric.
    """
    start = time.perf_counter()
    try:
        info = socket.getaddrinfo(hostname, None, socket.AF_INET)
        elapsed = (time.perf_counter() - start) * 1000
        ip = info[0][4][0] if info else "unknown"
        return DNSResult(hostname=hostname, resolved_ip=ip, resolution_time_ms=round(elapsed, 2))
    except socket.gaierror as exc:
        elapsed = (time.perf_counter() - start) * 1000
        logger.error("DNS resolution failed for %s after %.1f ms: %s", hostname, elapsed, exc)
        return DNSResult(hostname=hostname, resolved_ip="", resolution_time_ms=elapsed)


@dataclass
class ConnectionMetrics:
    target: str
    connect_time_ms: float
    tls_handshake_ms: float
    total_ms: float


def time_tcp_connect(host: str, port: int, timeout: float = 5.0) -> ConnectionMetrics:
    """
    Measure TCP connection establishment time separately from request time.
    High connect_time → routing/firewall issue.
    High tls_handshake → certificate chain too long or server CPU-bound.
    """
    t0 = time.perf_counter()
    sock = socket.create_connection((host, port), timeout=timeout)
    connect_ms = (time.perf_counter() - t0) * 1000

    # TLS handshake (if applicable — wrap socket).
    tls_ms = 0.0
    try:
        import ssl
        t1 = time.perf_counter()
        ctx = ssl.create_default_context()
        tls_sock = ctx.wrap_socket(sock, server_hostname=host)
        tls_ms = (time.perf_counter() - t1) * 1000
        tls_sock.close()
    except ssl.SSLError:
        sock.close()

    total_ms = connect_ms + tls_ms
    return ConnectionMetrics(
        target=f"{host}:{port}",
        connect_time_ms=round(connect_ms, 2),
        tls_handshake_ms=round(tls_ms, 2),
        total_ms=round(total_ms, 2),
    )


# =============================================================================
# SECTION 8 — Database query tracking: N+1 detection
# =============================================================================

class QueryTracker:
    """
    Thread-local query counter to detect N+1 query patterns.
    Attach to SQLAlchemy event hooks (see below) to count queries per request.

    N+1 pattern: 1 query fetches N parent rows, then N queries fetch child rows.
    Solution: use joinedload() or selectinload() in SQLAlchemy to batch.
    """

    def __init__(self, warn_threshold: int = 10):
        self._local = threading.local()
        self.warn_threshold = warn_threshold

    @property
    def count(self) -> int:
        return getattr(self._local, "count", 0)

    def increment(self) -> None:
        self._local.count = self.count + 1
        if self.count == self.warn_threshold:
            logger.warning(
                "N+1 ALERT: %d queries in this request — check for missing eager loads",
                self.count,
            )

    def reset(self) -> None:
        self._local.count = 0

    @contextmanager
    def track(self):
        """Use as a context manager per request."""
        self.reset()
        yield self
        final = self.count
        if final > self.warn_threshold:
            logger.error("Request completed with %d queries — potential N+1", final)
        else:
            logger.debug("Request completed with %d queries", final)


query_tracker = QueryTracker(warn_threshold=10)


def attach_sqlalchemy_listeners(engine) -> None:
    """
    SQLAlchemy event hooks give us query count, slow query logging,
    and query text — all without modifying ORM code.
    """
    from sqlalchemy import event

    @event.listens_for(engine, "before_cursor_execute")
    def before_execute(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("query_start_time", []).append(time.perf_counter())
        query_tracker.increment()

    @event.listens_for(engine, "after_cursor_execute")
    def after_execute(conn, cursor, statement, parameters, context, executemany):
        total_ms = (time.perf_counter() - conn.info["query_start_time"].pop(-1)) * 1000
        if total_ms > 200:   # slow query threshold in ms
            # Log full statement for slow queries; be careful with PII in params.
            logger.warning(
                "Slow query %.1f ms: %.200s",   # truncate at 200 chars for safety
                total_ms,
                statement,
            )


# =============================================================================
# SECTION 9 — Custom performance counters
# =============================================================================

@dataclass
class LatencyHistogram:
    """
    Lightweight in-process latency histogram for custom instrumentation.
    Use when you need per-code-path percentiles without an external metrics system.
    """
    name: str
    buckets_ms: List[float] = field(default_factory=lambda: [1, 5, 10, 50, 100, 250, 500, 1000])
    _samples: List[float] = field(default_factory=list, repr=False)

    def record(self, value_ms: float) -> None:
        self._samples.append(value_ms)

    def percentile(self, p: float) -> float:
        """Return the p-th percentile (0–100) of recorded samples."""
        if not self._samples:
            return 0.0
        sorted_samples = sorted(self._samples)
        idx = int(len(sorted_samples) * p / 100)
        return sorted_samples[min(idx, len(sorted_samples) - 1)]

    def report(self) -> Dict[str, float]:
        if not self._samples:
            return {}
        return {
            "count": len(self._samples),
            "mean_ms": round(statistics.mean(self._samples), 2),
            "p50_ms": round(self.percentile(50), 2),
            "p95_ms": round(self.percentile(95), 2),
            "p99_ms": round(self.percentile(99), 2),
            "max_ms": round(max(self._samples), 2),
        }

    def reset(self) -> None:
        self._samples.clear()


def perf_counter(histogram: Optional[LatencyHistogram] = None):
    """
    Decorator factory that measures and records function execution time.
    Optionally feeds into a LatencyHistogram for percentile tracking.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()   # monotonic, high-resolution clock
            try:
                return func(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                if histogram:
                    histogram.record(elapsed_ms)
                logger.debug("%s took %.2f ms", func.__qualname__, elapsed_ms)
        return wrapper
    return decorator


# Instantiate a shared histogram for the inference endpoint.
inference_latency = LatencyHistogram("inference.latency")


@perf_counter(histogram=inference_latency)
def mock_model_inference(input_tokens: int) -> str:
    """Simulate ML model inference with variable latency."""
    time.sleep(random.uniform(0.005, 0.1) * (input_tokens / 100))
    return "generated_output"


# =============================================================================
# SECTION 10 — Real User Monitoring vs Synthetic Monitoring
# =============================================================================

RUM_VS_SYNTHETIC = """
Real User Monitoring (RUM):
  - Collects performance data from ACTUAL users' browsers/apps.
  - Captures: Core Web Vitals (LCP, FID/INP, CLS), page load time, JS errors.
  - Tools: Grafana Faro, Datadog RUM, Sentry Performance, Google CrUX.
  - Strengths: shows real geographic/device distribution of latency.
  - Weakness: no data until users visit; noisy due to device/network variety.

  Python backend for RUM:
    - Inject a snippet into HTML responses that ships events to a collector.
    - Correlate browser trace_id with backend trace_id for end-to-end traces.

Synthetic Monitoring:
  - Scheduled scripts that simulate user flows from fixed probe locations.
  - Catches regressions before real users experience them.
  - Tools: Grafana k6 Cloud, Datadog Synthetics, Checkly, Pingdom.
  - Strengths: deterministic baseline, catches issues at 3 AM.
  - Weakness: cannot capture real device/network conditions.

  k6 synthetic example (JavaScript, run from CI or cloud):
    import http from 'k6/http';
    import { check } from 'k6';
    export default function () {
      const res = http.get('https://api.example.com/health');
      check(res, { 'status 200': (r) => r.status === 200 });
    }

Decision: Run BOTH.
  Synthetic → SLO alerting on known user journeys.
  RUM       → discovery of unexpected latency in the wild.
"""


# =============================================================================
# SECTION 11 — APM tool integration snippets
# =============================================================================

def setup_datadog_apm() -> None:
    """
    Datadog APM uses ddtrace which patches popular frameworks at import time.
    Production: use `ddtrace-run python app.py` CLI instead of inline setup —
    it guarantees patches apply before any framework code runs.

    Manual setup shown here for reference only.
    """
    try:
        import ddtrace
        from ddtrace import tracer as dd_tracer
        from ddtrace import patch_all

        # patch_all() instruments requests, sqlalchemy, redis, celery, etc.
        patch_all(requests=True, sqlalchemy=True, redis=True, logging=True)

        dd_tracer.configure(
            hostname=os.getenv("DD_AGENT_HOST", "localhost"),
            port=int(os.getenv("DD_TRACE_AGENT_PORT", "8126")),
            analytics_enabled=True,   # enables APM → App Analytics in Datadog UI
        )
        logger.info("Datadog APM initialized")
    except ImportError:
        logger.warning("ddtrace not installed")


def setup_elastic_apm() -> None:
    """
    Elastic APM agent auto-instruments Flask, Django, FastAPI (via ASGI middleware).
    Sends traces to Elasticsearch APM server.
    """
    try:
        import elasticapm
        from elasticapm import Client

        client = Client(
            service_name=os.getenv("ELASTIC_APM_SERVICE_NAME", "checkout-service"),
            server_url=os.getenv("ELASTIC_APM_SERVER_URL", "http://localhost:8200"),
            environment=os.getenv("ENV", "production"),
            secret_token=os.getenv("ELASTIC_APM_SECRET_TOKEN", ""),
        )
        elasticapm.instrument()   # patches stdlib + popular frameworks
        logger.info("Elastic APM initialized")
    except ImportError:
        logger.warning("elastic-apm not installed")


# =============================================================================
# SECTION 12 — Profiling in production: low-overhead sampling strategy
# =============================================================================

class AdaptiveSamplingProfiler:
    """
    Runs py-spy-style stack sampling in a background thread at configurable Hz.
    Designed for production use where a full profiler is too expensive.

    This is a simplified illustration.  In real deployments use py-spy or
    Pyroscope which handle GIL, signal safety, and native frames correctly.
    """

    def __init__(self, sample_rate_hz: int = 50, max_samples: int = 1000):
        self.sample_rate_hz = sample_rate_hz
        self.interval = 1.0 / sample_rate_hz
        self.max_samples = max_samples
        self._samples: List[str] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._sample_loop,
            daemon=True,             # daemon=True so it doesn't block process exit
            name="adaptive-profiler",
        )
        self._thread.start()
        logger.info("Adaptive profiler started at %d Hz", self.sample_rate_hz)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _sample_loop(self) -> None:
        import sys
        while self._running and len(self._samples) < self.max_samples:
            # Snapshot all Python frames across all threads.
            frames = sys._current_frames()
            sample_lines = []
            for tid, frame in frames.items():
                location = f"{frame.f_code.co_filename}:{frame.f_lineno}:{frame.f_code.co_name}"
                sample_lines.append(f"thread={tid} {location}")
            self._samples.append(";".join(sample_lines))
            time.sleep(self.interval)

    def top_functions(self, top_n: int = 10) -> List[tuple]:
        """Return top N (function, hit_count) pairs from samples."""
        from collections import Counter
        all_frames = []
        for sample in self._samples:
            all_frames.extend(sample.split(";"))
        return Counter(all_frames).most_common(top_n)


# =============================================================================
# SECTION 13 — Performance baselines and regression detection
# =============================================================================

@dataclass
class PerformanceBaseline:
    """
    Store and compare performance baselines so CI can catch regressions.
    Commit baseline.json to the repo and update it when optimisations land.
    """
    function_name: str
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float

    def compare(self, current: LatencyHistogram, regression_threshold_pct: float = 20.0) -> bool:
        """
        Return True if current performance is within threshold of baseline.
        A 20% p99 regression triggers a CI failure.
        """
        report = current.report()
        if not report:
            return True   # no data — skip check

        p99_current = report["p99_ms"]
        p99_delta_pct = ((p99_current - self.p99_ms) / self.p99_ms) * 100

        if p99_delta_pct > regression_threshold_pct:
            logger.error(
                "PERF REGRESSION: %s p99 %.1f ms vs baseline %.1f ms (%.1f%% worse)",
                self.function_name,
                p99_current,
                self.p99_ms,
                p99_delta_pct,
            )
            return False

        logger.info(
            "Perf OK: %s p99 %.1f ms vs baseline %.1f ms (delta %.1f%%)",
            self.function_name,
            p99_current,
            self.p99_ms,
            p99_delta_pct,
        )
        return True


# =============================================================================
# SECTION 14 — GC profiling: understanding garbage collection pauses
# =============================================================================

def profile_gc_impact(func: Callable, iterations: int = 100) -> Dict[str, Any]:
    """
    Measure GC collection counts and time before/after a function.
    GC pauses are a common cause of p99 spikes in Python services.

    Mitigations:
      - gc.disable() for latency-critical paths + explicit gc.collect() in idle.
      - Use __slots__ in hot-path classes to reduce per-object overhead.
      - Avoid reference cycles in long-lived objects.
      - Consider PyPy or GraalPy for GC-heavy workloads.
    """
    gc.collect()   # start with a clean slate
    gc_before = gc.get_count()
    gc_stats_before = gc.get_stats()

    latencies = []
    for _ in range(iterations):
        start = time.perf_counter()
        func()
        latencies.append((time.perf_counter() - start) * 1000)

    gc_after = gc.get_count()
    gc_stats_after = gc.get_stats()

    collections_gen0 = gc_stats_after[0]["collections"] - gc_stats_before[0]["collections"]
    collections_gen1 = gc_stats_after[1]["collections"] - gc_stats_before[1]["collections"]

    return {
        "iterations": iterations,
        "mean_ms": round(statistics.mean(latencies), 2),
        "p99_ms": round(sorted(latencies)[int(iterations * 0.99)], 2),
        "gc_collections_gen0": collections_gen0,
        "gc_collections_gen1": collections_gen1,
        "gc_objects_before": sum(gc_before),
        "gc_objects_after": sum(gc_after),
    }


# =============================================================================
# DEMO
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s %(message)s")

    print("\n=== 1. cProfile section ===")
    with cprofile_section(top_n=5):
        [sorted(range(500)) for _ in range(200)]

    print("\n=== 2. tracemalloc ===")
    demo_tracemalloc()

    print("\n=== 3. Custom latency histogram ===")
    for _ in range(50):
        mock_model_inference(random.randint(50, 500))
    print(inference_latency.report())

    print("\n=== 4. DNS timing ===")
    dns = time_dns_resolution("example.com")
    print(f"DNS: {dns.hostname} → {dns.resolved_ip} in {dns.resolution_time_ms} ms")

    print("\n=== 5. Adaptive sampler ===")
    profiler = AdaptiveSamplingProfiler(sample_rate_hz=200, max_samples=50)
    profiler.start()
    time.sleep(0.5)   # let it collect samples
    profiler.stop()
    top = profiler.top_functions(5)
    print("Top sampled frames:", top[:3])

    print("\n=== 6. GC profiling ===")

    def workload():
        return [{"key": i, "value": list(range(10))} for i in range(100)]

    gc_report = profile_gc_impact(workload, iterations=50)
    print("GC report:", gc_report)

    print("\n=== 7. Regression check ===")
    baseline = PerformanceBaseline(
        function_name="mock_model_inference",
        p50_ms=20.0, p95_ms=80.0, p99_ms=100.0, max_ms=150.0,
    )
    ok = baseline.compare(inference_latency, regression_threshold_pct=20.0)
    print("Regression check passed:", ok)
