// ============================================================
// L08: Production Edge Architecture
// ============================================================
// WHAT: The operational concerns of running edge compute as a real
//       production system — multi-CDN resilience, observability,
//       deployment pipelines, cost, and disaster recovery.
// WHY:  Edge platforms are still infrastructure you operate, not magic.
//       A single-CDN dependency IS a single point of failure at the
//       provider level, and "it's just a Worker" doesn't remove the need
//       for CI/CD discipline, tracing, or a DR plan.
// LEVEL: Advanced / Staff
// ============================================================

/*
CONCEPT OVERVIEW:
Production edge architecture treats the edge platform itself as a
dependency with its own failure modes: a CDN provider outage, a bad Worker
deploy causing a global 500, or a data-residency requirement that a
single-provider anycast network can't satisfy. Mature deployments layer
multi-CDN failover, real-user monitoring, and staged rollout on top of the
raw "deploy code to 300 PoPs" capability edge platforms provide.

PRODUCTION USE CASE:
An e-commerce platform runs Cloudflare as primary and Fastly as failover,
with GeoDNS/health-check-based routing between them. A bad Worker deploy
that causes elevated 500s triggers an automatic rollback via a canary
percentage-based deploy (5% of traffic to the new version, auto-rollback
if error rate crosses a threshold within 2 minutes) — the same
canary/rollback discipline you'd apply to a Kubernetes deployment, applied
to edge functions.

COMMON MISTAKES:
  - Deploying edge function changes directly to 100% of global traffic
    with no canary stage — a bug now affects users on every continent
    simultaneously, instead of a contained blast radius.
  - No tracing/correlation ID propagation through the edge layer — when
    debugging a slow request, you can see origin's trace but have no
    visibility into what happened at the edge hop before it.
  - Assuming the CDN provider's uptime SLA IS your uptime — a 99.99%
    provider SLA still permits ~52 minutes of downtime/year; multi-CDN
    is the only way past a single provider's ceiling.
*/

// ------------------------------------------------------------------
// 1. Multi-CDN strategy
// ------------------------------------------------------------------
const MULTI_CDN_NOTES = `
Primary + failover via DNS health checks: a monitoring service polls both
CDN endpoints; if primary's health check fails for N consecutive checks,
DNS is updated (or a GeoDNS/traffic-management layer like NS1/Cedexis
switches) to route new connections to the failover CDN. This has a floor
on reaction time set by DNS TTL — for near-instant failover, some setups
instead run BOTH CDNs simultaneously behind a client-side or edge-side
weighted split, so failover doesn't depend on DNS propagation at all, at
the cost of double-running (and double-paying for) the edge logic
everywhere.
`;

// ------------------------------------------------------------------
// 2. Edge observability
// ------------------------------------------------------------------
const EDGE_OBSERVABILITY = `
export default {
  async fetch(request, env, ctx) {
    const traceId = request.headers.get("X-Trace-Id") ?? crypto.randomUUID();
    const start = Date.now();

    try {
      const response = await handleRequest(request, env);
      // ctx.waitUntil lets you fire-and-forget analytics AFTER the
      // response is already sent to the client — doesn't add latency
      // to the request the user is actually waiting on.
      ctx.waitUntil(logEdgeEvent({
        traceId,
        path: new URL(request.url).pathname,
        status: response.status,
        durationMs: Date.now() - start,
        colo: request.cf?.colo,          // which PoP served this (Cloudflare-specific)
      }));
      response.headers.set("X-Trace-Id", traceId);  // propagate to origin/downstream
      return response;
    } catch (err) {
      ctx.waitUntil(logEdgeEvent({ traceId, error: err.message }));
      throw err;
    }
  },
};

// RUM (Real User Monitoring): a small JS snippet in the served page
// reports actual client-side timing (TTFB, LCP) back to an analytics
// endpoint — this is the ONLY way to see the latency the user actually
// experienced, since edge-side logs can't see client network conditions.
`;

// ------------------------------------------------------------------
// 3. Deployment: CI/CD for edge functions
// ------------------------------------------------------------------
const EDGE_CICD_PIPELINE = `
# .github/workflows/deploy-worker.yml
jobs:
  deploy:
    steps:
      - uses: actions/checkout@v4
      - run: npm test
      - name: Deploy canary (5% traffic)
        run: wrangler deploy --env canary
      - name: Wait and check error rate
        run: ./scripts/check-canary-health.sh   # polls metrics API for 2 min
      - name: Promote to 100%
        if: success()
        run: wrangler deploy --env production
      - name: Auto-rollback on failure
        if: failure()
        run: wrangler rollback --env canary
`;

const TRAFFIC_SPLITTING_NOTE = `
Percentage-based traffic splitting between Worker versions (supported
natively by some edge platforms via "gradual deployments") routes a
configurable % of requests to the new version, with automatic rollback if
error rate/latency regresses beyond a threshold — the same blue-green /
canary discipline as a Kubernetes rollout, just operating on edge isolates
instead of pods.
`;

// ------------------------------------------------------------------
// 4. Cost optimization
// ------------------------------------------------------------------
const EDGE_COST_OPTIMIZATION = {
  cache_hit_ratio_target: "Edge compute is typically billed per-invocation "
    + "— every cache HIT that bypasses the Worker entirely (served "
    + "directly from CDN cache) is compute you never pay for. Track hit "
    + "ratio as a cost metric, not just a latency metric.",
  origin_offload: "Bandwidth cost per GB from ORIGIN is usually far higher "
    + "than edge egress — maximizing cache hit ratio is simultaneously a "
    + "latency win and a direct line-item cost reduction.",
  kv_read_write_asymmetry: "Edge KV stores often price reads far cheaper "
    + "than writes (and writes propagate globally more slowly) — design "
    + "around read-heavy, write-light access patterns; avoid using edge KV "
    + "as a high-write-frequency counter store (use Durable Objects or a "
    + "centralized store for that instead).",
};

// ------------------------------------------------------------------
// 5. Edge-origin private communication
// ------------------------------------------------------------------
const EDGE_ORIGIN_PRIVATE_LINK = `
Instead of the edge calling origin over the public internet (even with
TLS, this exposes origin's IP to the internet, inviting direct-to-origin
DDoS bypassing edge protections entirely), production setups use:
  - A private tunnel (e.g. Cloudflare Tunnel) — origin makes an OUTBOUND
    connection to the edge network; no inbound port is ever open on
    origin's firewall, eliminating direct-to-origin attack surface.
  - Cloud provider PrivateLink/VPC peering — edge platform's compute
    reaches origin over the cloud provider's private backbone, never
    traversing the public internet.
This closes the "edge WAF is great but someone found origin's real IP and
bypassed it entirely" attack class, which is common when origin's IP was
ever exposed (e.g. before the CDN was put in front of it).
`;

// ------------------------------------------------------------------
// 6. Disaster recovery — edge failover when origin is down
// ------------------------------------------------------------------
const EDGE_DR_NOTES = `
Combine stale-if-error (see L05) with a custom edge-rendered error page:
  Cache-Control: public, max-age=60, stale-if-error=86400
means if origin is down for up to 24 hours, the edge keeps serving the
LAST KNOWN GOOD cached response instead of an error — for read-mostly
content (a product catalog, a docs site) this can mean an origin outage
is nearly invisible to users. For write paths (checkout, login) that
can't be served stale, the edge instead serves a custom "we're
experiencing issues" page rather than a raw 502, and can queue writes
(e.g. via a Durable Object or edge queue) to replay once origin recovers.
`;

// ------------------------------------------------------------------
// 7. Compliance — data residency at the edge
// ------------------------------------------------------------------
const DATA_RESIDENCY_NOTES = `
GDPR and similar regulations can require EU user data to never leave EU
infrastructure. Edge platforms increasingly support REGION-PINNED
execution (e.g. Cloudflare's "Regional Services" / jurisdictional
restrictions) — a Worker processing EU user requests can be constrained
to execute ONLY on EU-located PoPs, and edge KV/D1 data can be
region-pinned similarly. This must be explicitly configured; the default
"run everywhere for lowest latency" behavior of most edge platforms is
the OPPOSITE of a data-residency-compliant default.
`;

// ------------------------------------------------------------------
// 8. Full reference architecture
// ------------------------------------------------------------------
const REFERENCE_ARCHITECTURE = `
    Client
      |
      v
  +----------------+     health checks      +----------------+
  |  Primary CDN   |<---------------------->|  Failover CDN  |
  |  (edge Worker) |                        |  (edge Worker) |
  +--------+-------+                        +--------+-------+
           |  Cloudflare Tunnel / PrivateLink        |
           v  (never public internet)                v
                    +------------------------+
                    |   Origin (private VPC) |
                    +------------------------+
    Edge-side: KV (read cache), Durable Objects (stateful), Workers AI
    Observability: RUM (client) + edge access logs + trace-id propagation
                    into origin's distributed tracing
`;

module.exports = {
  MULTI_CDN_NOTES,
  EDGE_OBSERVABILITY,
  EDGE_CICD_PIPELINE,
  TRAFFIC_SPLITTING_NOTE,
  EDGE_COST_OPTIMIZATION,
  EDGE_ORIGIN_PRIVATE_LINK,
  EDGE_DR_NOTES,
  DATA_RESIDENCY_NOTES,
  REFERENCE_ARCHITECTURE,
};

/*
TRADING/PRODUCTION CONTEXT EXAMPLE:
A brokerage's public market-data widget (embedded on partner sites) runs
entirely at the edge with stale-if-error caching — if origin has a brief
outage during a deploy, the widget keeps showing the last known quote
snapshot with an "as of" timestamp rather than breaking visibly on
hundreds of partner sites simultaneously, buying the on-call engineer time
to fix origin without an incident escalating into a partner-facing outage.
*/
