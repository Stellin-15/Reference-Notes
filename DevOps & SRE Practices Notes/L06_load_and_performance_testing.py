# ============================================================
# L06: Load and Performance Testing — k6, Locust, JMeter
# ============================================================
# WHAT: How to systematically test a system's behavior UNDER LOAD before
#       real users find its breaking point — the three major open-source
#       load testing tools (k6, Locust, JMeter), designing a realistic
#       load test, and interpreting results to find actual bottlenecks.
# WHY: A system that "works fine" under normal, low-traffic manual
#      testing can fail catastrophically under real production load —
#      load testing is how you find that breaking point DELIBERATELY,
#      in a controlled environment, before a real traffic spike finds it
#      for you in production.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
LOAD TESTING simulates MANY concurrent users/requests against a system
to observe its behavior under realistic (or intentionally excessive)
traffic — distinct from functional testing (does the API return the
correct response) which typically tests one request at a time. The goal
is answering questions functional testing cannot: "how many requests per
second can this handle before latency degrades," "what's the FIRST
component to fail under load (the database? a specific service? memory?),"
and "does autoscaling actually kick in fast enough to handle a realistic traffic spike."

k6 is a modern, DEVELOPER-FRIENDLY load testing tool — test scripts are
written in JavaScript, designed to integrate naturally into a CI/CD
pipeline (this repo's CICD Notes) as an automated performance-regression
gate, not just a manual, occasional exercise. LOCUST is Python-based,
letting you define user BEHAVIOR as Python code (useful when load
patterns need genuinely complex, stateful logic that's easier to express
in a full programming language than a DSL). JMETER is the oldest, most
mature of the three — a GUI-based tool (though scriptable/headless too)
with an extensive plugin ecosystem, historically the default choice
before k6/Locust's more developer/CI-friendly approaches gained adoption.

DESIGNING A REALISTIC LOAD TEST means modeling actual user behavior, not
just "hit this one endpoint as fast as possible" — a realistic test
defines multiple DIFFERENT user "journeys" (e.g. 70% of virtual users
browse and occasionally purchase, 20% only browse, 10% are API
integrations hitting a different endpoint pattern entirely), with think-
time (pauses between actions, mimicking real human behavior) and a
RAMP-UP profile (gradually increasing virtual users, rather than
instantly slamming the system with peak load, which tests a
DIFFERENT scenario — a sudden traffic spike — than gradual growth).

INTERPRETING RESULTS means going beyond "did it pass or fail" to
identifying the ACTUAL BOTTLENECK: is latency degrading because of CPU
saturation, database connection pool exhaustion, a downstream API's own
rate limiting, or memory pressure causing GC pauses? Correlating load
test results with the SAME infrastructure metrics covered in this
repo's Observability Notes (CPU, memory, database connection counts,
queue depths) during the test is what turns "it got slow at 500
concurrent users" into an actionable, specific finding ("the database
connection pool was exhausted at 500 concurrent users, and increasing
the pool size resolved it").

PRODUCTION USE CASE:
A team runs a k6 load test in their CI pipeline on every release
candidate, gradually ramping to 2x their historical peak traffic —
before a major marketing campaign expected to drive a large traffic
spike, this same test (run manually at higher, campaign-specific load
levels) reveals the database connection pool would exhaust at roughly
1.5x normal peak, well below the campaign's projected traffic — giving
the team time to increase pool size and re-test BEFORE the campaign
launches, rather than discovering the bottleneck live, under real user traffic.

COMMON MISTAKES:
- Load testing with an UNREALISTIC traffic pattern (e.g. hitting one
  endpoint at maximum possible rate with no think-time or user-journey
  variation) instead of modeling actual expected usage — this can
  surface bottlenecks that would never occur in real traffic while
  MISSING realistic bottlenecks that only appear under a genuinely
  mixed, realistic load pattern.
- Running load tests only ONCE, before a major launch, instead of
  continuously (as an automated CI gate on every release) — a
  performance regression introduced in a later, seemingly-unrelated
  change goes undetected until the NEXT major manual load test, which
  might be months later.
- Interpreting "the test failed at X concurrent users" as the final
  answer without investigating WHICH specific component/resource was
  the actual bottleneck — without that correlation, you don't know
  WHAT to fix, only that something eventually broke.
"""

import textwrap


# ------------------------------------------------------------------
# 1. k6 — JavaScript-based, CI-friendly load testing
# ------------------------------------------------------------------
K6_SCRIPT_EXAMPLE = textwrap.dedent("""\
    // load_test.js
    import http from 'k6/http';
    import { sleep, check } from 'k6';

    export const options = {
      stages: [
        { duration: '2m', target: 100 },   // RAMP UP to 100 virtual users over 2 min
        { duration: '5m', target: 100 },   // SUSTAIN 100 users for 5 min
        { duration: '2m', target: 0 },     // RAMP DOWN
      ],
      thresholds: {
        http_req_duration: ['p(95)<500'],   // FAIL the test if p95 latency
                                              // exceeds 500ms — this is
                                              // what makes k6 usable as an
                                              // automated CI regression gate
        http_req_failed: ['rate<0.01'],     // FAIL if error rate exceeds 1%
      },
    };

    export default function () {
      const res = http.get('https://staging.example.com/api/products');
      check(res, { 'status is 200': (r) => r.status === 200 });
      sleep(1);   // THINK TIME — mimics a real user pausing between actions,
                   // rather than hammering the API with zero delay
    }

    // CI integration: `k6 run load_test.js` exits non-zero if thresholds
    // are violated, failing the pipeline — a genuine automated
    // performance-regression gate, not a manual, occasional exercise.
""")

# ------------------------------------------------------------------
# 2. Locust — Python-based, stateful user behavior
# ------------------------------------------------------------------
LOCUST_SCRIPT_EXAMPLE = textwrap.dedent("""\
    # locustfile.py
    from locust import HttpUser, task, between

    class BrowsingUser(HttpUser):
        wait_time = between(1, 5)   # random think-time between 1-5 seconds

        def on_start(self):
            # Runs ONCE per virtual user at the start — e.g. logging in,
            # establishing session state that persists across this
            # user's subsequent tasks.
            self.client.post("/login", json={"username": "test", "password": "test"})

        @task(7)   # WEIGHT: this task runs 7x more often than weight-1 tasks
        def browse_products(self):
            self.client.get("/api/products")

        @task(1)
        def make_purchase(self):
            self.client.post("/api/purchase", json={"product_id": 123})

    # Run: locust -f locustfile.py --users 500 --spawn-rate 10
    # (500 total virtual users, ramping up at 10 new users/second)
""")

# ------------------------------------------------------------------
# 3. JMeter — the mature, GUI-capable option
# ------------------------------------------------------------------
JMETER_NOTE = textwrap.dedent("""\
    JMeter is configured primarily via its GUI (saved as an XML .jmx
    test plan), though it also runs headless for CI (`jmeter -n -t
    test_plan.jmx -l results.jtl`). Its main differentiators from k6/
    Locust: a MUCH longer history and larger ecosystem of protocol
    plugins (not just HTTP — JDBC, JMS, FTP, and many others), making
    it a common choice when testing non-HTTP protocols or when a team
    already has significant existing JMeter test-plan investment,
    rather than a typical GREENFIELD choice today given k6/Locust's
    more developer/CI-friendly authoring experience.
""")

# ------------------------------------------------------------------
# 4. Designing a realistic mixed load test
# ------------------------------------------------------------------
REALISTIC_LOAD_PROFILE_NOTE = textwrap.dedent("""\
    A realistic load test models MULTIPLE user journeys with proportional
    weights matching real traffic patterns, not one uniform action:

      70% of virtual users: browse products, occasionally view details,
                              rarely purchase (matches typical e-commerce
                              browse-to-purchase conversion patterns)
      20% of virtual users: browse only, never purchase (window shoppers)
      10% of virtual users: API integrations (partners) hitting a
                              DIFFERENT set of endpoints entirely, at a
                              different, often steadier request rate

    Testing with ONLY "hit /api/products as fast as possible" misses
    the REAL bottleneck that might only appear under this realistic MIX
    — e.g. the purchase endpoint's database transaction contention,
    invisible if purchases are never actually exercised in the test.
""")

# ------------------------------------------------------------------
# 5. Correlating results with infrastructure metrics
# ------------------------------------------------------------------
BOTTLENECK_DIAGNOSIS_CHECKLIST = [
    "CPU utilization on application servers — saturated CPU indicates a "
    "compute-bound bottleneck (this repo's LLM Quantization/Observability "
    "Notes cover profiling techniques for finding WHAT is CPU-heavy).",
    "Database connection pool usage/wait time — exhaustion here often "
    "presents as request latency spikes that LOOK like an application "
    "problem but are actually a pool-sizing problem.",
    "Memory usage and garbage collection pause frequency/duration — "
    "particularly relevant for JVM/managed-runtime services under sustained load.",
    "Downstream/third-party API latency and rate-limit responses — a "
    "bottleneck might not be YOUR system at all, but a dependency's own limits.",
    "Queue depths (message queues, background job queues) — a growing, "
    "unbounded queue depth under load indicates consumers can't keep up "
    "with producers at this load level.",
]


if __name__ == "__main__":
    print(K6_SCRIPT_EXAMPLE)
    print(LOCUST_SCRIPT_EXAMPLE)
    print(JMETER_NOTE)
    print(REALISTIC_LOAD_PROFILE_NOTE)
    print("Bottleneck diagnosis checklist (correlate load test results against):")
    for item in BOTTLENECK_DIAGNOSIS_CHECKLIST:
        print(f"  - {item}")

"""
PRODUCTION CONTEXT EXAMPLE:
A team's k6-based CI load test catches a performance regression
introduced by a seemingly-unrelated code change (an added database query
in a hot code path) that pushed p95 latency from 200ms to 650ms under
sustained load — failing the CI pipeline's threshold check and blocking
the merge — a regression that would likely have gone unnoticed in normal
functional testing (which tests correctness, not latency under
concurrent load) until it caused real user-facing slowness in production.
"""
