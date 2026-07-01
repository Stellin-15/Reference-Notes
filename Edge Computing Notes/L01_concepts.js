// ============================================================
// L01: Edge Computing — Core Concepts
// ============================================================
// WHAT: Run application code at geographically distributed
//       edge nodes, physically close to end users, rather than
//       in a single centralized data center.
// WHY:  Latency is physics. A user in Tokyo hitting a server in
//       Virginia adds ~150ms round-trip before your code even
//       runs. Move the code to Tokyo and that drops to ~5ms.
// LEVEL: Foundation
// ============================================================
/*
CONCEPT OVERVIEW:
  Edge computing is not a single product — it is an architectural
  pattern. Instead of all requests flowing to one region (e.g., us-east-1),
  your code is deployed simultaneously to dozens or hundreds of
  locations worldwide. Requests are served by the node closest to
  the user. The fundamental win is latency reduction, but the model
  also offers resilience (no single point of failure) and the ability
  to make decisions before traffic ever reaches your origin servers.

  The enabling technology for modern edge computing is V8 Isolates,
  pioneered by Cloudflare Workers. Rather than spinning up a full OS
  process or even a container for each request (cold start: 100ms–1s),
  V8 Isolates reuse a single V8 engine process, starting new isolates
  in <1ms. This makes it economically and technically feasible to run
  code on every request at hundreds of locations simultaneously.

PRODUCTION USE CASE:
  A global e-commerce platform uses edge workers for: JWT validation
  (blocks unauthenticated requests before they touch the origin), A/B
  testing (assigns experiment variants without a round trip), geo-based
  product catalog filtering (shows region-appropriate inventory), and
  bot detection (blocks scraping traffic before it consumes origin
  resources). The origin only receives clean, authenticated, enriched
  requests, reducing infrastructure cost by ~60% and improving median
  TTFB from 320ms to 45ms globally.

COMMON MISTAKES:
  1. Trying to run long-lived tasks at edge. CPU limits are 10–50ms.
     Heavy computation, file processing, and ML inference (large models)
     must stay at origin.
  2. Assuming edge = CDN. A CDN caches static files. Edge runs dynamic
     code. Confusing these leads to using edge where a simple cache
     header would suffice, wasting money.
  3. Ignoring data gravity. If your edge worker must query a database
     in a single region to fulfill every request, you have only moved
     the latency — not eliminated it. Edge data solutions (KV, embedded
     SQLite replicas) are required for genuine latency wins.
  4. Using edge for WebSocket-heavy workloads without Durable Objects.
     Standard edge workers are stateless and short-lived — persistent
     connections require a different primitive.
*/

// ============================================================
// SECTION 1: The Latency Problem
// ============================================================

// Speed of light in fiber: approximately 200,000 km/s (66% of c).
// Tokyo → Virginia (Ashburn, us-east-1): ~10,800 km
// Round-trip distance: ~21,600 km
// Pure propagation time: ~108ms
// Add network hops, TLS handshake, OS scheduling: ~150ms typical

// This is before your application code runs a single line.
// For interactive UIs, 100ms is the human perception threshold
// for "lag". At 150ms+ users feel friction even if the code is instant.

const LATENCY_EXAMPLES = {
  // Measurements are approximate real-world P50 values
  tokyoToVirginia: {
    distanceKm: 10800,
    typicalRoundTripMs: 150,
    scenario: "User in Tokyo, origin in us-east-1 (AWS Virginia)",
  },
  tokyoToTokyoEdge: {
    distanceKm: 0, // same datacenter region
    typicalRoundTripMs: 5,
    scenario: "User in Tokyo, Cloudflare edge node in Tokyo",
  },
  londonToLondonEdge: {
    distanceKm: 0,
    typicalRoundTripMs: 3,
    scenario: "User in London, edge node in London (Docklands)",
  },
  improvement: "150ms → 5ms = 30x latency reduction for auth/routing decisions",
};

// ============================================================
// SECTION 2: V8 Isolates — Why Edge Is Now Practical
// ============================================================

// Traditional Lambda / container cold start timeline:
//   - OS boots container/microVM: 50–500ms
//   - Runtime initializes (Node.js): 100–300ms
//   - Application code loads: 50–200ms
//   Total: 200ms–1s before first byte
//
// V8 Isolate cold start:
//   - Single V8 process already running on edge node
//   - New isolate = separate JS heap, <1ms to create
//   - "Cold start" is effectively zero from user perspective
//   - Isolates are sandboxed: no shared memory between requests

// Why Isolates are safe (despite sharing a V8 process):
//   - Each isolate has its own heap (no cross-request memory access)
//   - No file system access by default (WASI-gated)
//   - No arbitrary network (must use fetch() API)
//   - No ability to spawn processes or load native modules

// Memory model comparison:
const RUNTIME_COMPARISON = {
  awsLambda: {
    isolationUnit: "microVM (Firecracker)",
    coldStartMs: "100–500",
    memoryLimitMB: 10240, // 10GB max
    cpuTimeLimitMs: 900000, // 15 minutes
    concurrencyModel: "one request per container instance",
  },
  cloudflareWorker: {
    isolationUnit: "V8 Isolate",
    coldStartMs: "<1",
    memoryLimitMB: 128,
    cpuTimeLimitMs: 50, // 50ms CPU time (not wall time)
    concurrencyModel: "many isolates share one V8 process",
  },
  vercelEdgeFunction: {
    isolationUnit: "V8 Isolate (Cloudflare under the hood)",
    coldStartMs: "<1",
    memoryLimitMB: 128,
    cpuTimeLimitMs: 50,
    concurrencyModel: "same as Cloudflare Workers",
  },
};

// ============================================================
// SECTION 3: Edge Platforms Overview
// ============================================================

// --- Cloudflare Workers ---
// The reference implementation. 275+ cities worldwide.
// Uses V8 isolates. Service Worker API (fetch event handler).
// Ecosystem: KV (key-value store), R2 (object storage, no egress fees),
// D1 (SQLite at edge), Durable Objects (stateful coordination),
// Queues, AI (GPU inference), Vectorize (vector DB).
// Pricing: free tier 100k req/day. Paid: $5/month + usage.
//
// --- Vercel Edge Functions ---
// Next.js-native. Middleware.ts runs at edge before page rendering.
// Powered by Cloudflare Workers runtime under the hood.
// Best for: Next.js apps that need edge auth, A/B testing, geo-routing.
// Limitation: does not expose Cloudflare-specific bindings (KV, D1).
//
// --- Deno Deploy ---
// TypeScript-first edge platform. Deno runtime (not Node.js compatible
// out of the box — uses Deno.serve() and Web APIs). Global distribution.
// Best for: teams already using Deno, TypeScript-native backends.
// No npm packages: use ESM URLs (cdn.jsdelivr.net) or JSR.
//
// --- Fastly Compute ---
// WASM-based runtime (not JS). Write in Rust, AssemblyScript, Go.
// Compiles to WASM, runs in Wasmtime. True polyglot edge.
// Best for: Rust teams, compute-intensive edge logic, non-JS shops.
//
// --- AWS Lambda@Edge ---
// Run Node.js (or Python) at CloudFront edge locations.
// NOT the same as Workers — uses actual Lambda containers, not isolates.
// Cold start: 100ms–500ms. Significant latency vs Workers.
// Only ~30 edge locations (vs Cloudflare's 275+).
// Best for: teams deep in AWS ecosystem who need origin integration.
// Cost: $0.60/million invocations (3x more expensive than Workers).

const PLATFORMS = {
  cloudflareWorkers: {
    runtime: "V8 Isolates",
    locations: 275,
    coldStartMs: "<1",
    primaryLanguage: "JavaScript / TypeScript",
    ecosystem: ["KV", "R2", "D1", "Durable Objects", "AI", "Vectorize"],
    bestFor: "general-purpose edge, complex apps with state",
  },
  vercelEdgeFunctions: {
    runtime: "V8 Isolates (Cloudflare)",
    locations: 275,
    coldStartMs: "<1",
    primaryLanguage: "JavaScript / TypeScript",
    ecosystem: ["Next.js integration", "Vercel KV (Upstash)", "Vercel Blob"],
    bestFor: "Next.js apps, SSR optimization, middleware",
  },
  denoDeploy: {
    runtime: "Deno (V8-based)",
    locations: "~35",
    coldStartMs: "<5",
    primaryLanguage: "TypeScript",
    ecosystem: ["Deno KV", "web-compatible APIs"],
    bestFor: "Deno codebases, TypeScript-first teams",
  },
  fastlyCompute: {
    runtime: "Wasmtime (WASM)",
    locations: 80,
    coldStartMs: "<1",
    primaryLanguage: "Rust / AssemblyScript / Go (compiled to WASM)",
    ecosystem: ["Fastly KV Store", "Config Stores"],
    bestFor: "Rust teams, high-performance non-JS compute",
  },
  awsLambdaAtEdge: {
    runtime: "Node.js / Python (Lambda containers)",
    locations: 30,
    coldStartMs: "100–500",
    primaryLanguage: "Node.js, Python",
    ecosystem: ["Full AWS integration", "IAM", "VPC access"],
    bestFor: "AWS-native teams, VPC access from edge needed",
  },
};

// ============================================================
// SECTION 4: What Edge Is Good For
// ============================================================

// Use Case 1: A/B Testing at Edge
// Problem: Without edge, A/B assignment requires: user → CDN → origin
// → assign variant → set cookie → redirect → CDN → user. Two extra
// round trips. With edge: user → edge → assign variant → rewrite URL
// → serve. Zero extra round trips. Assignment happens in ~1ms.
function edgeABTest(request) {
  // Cookie-based persistence ensures same user sees same variant
  const existingVariant = getCookieValue(request, "ab_variant");
  if (existingVariant) return existingVariant;

  // Deterministic assignment by user ID or random for anonymous users
  const userId = getCookieValue(request, "user_id");
  if (userId) {
    // Hash ensures consistency: same user always gets same variant
    return hashUserId(userId) % 2 === 0 ? "control" : "treatment";
  }

  // Anonymous: 50/50 random split
  return Math.random() < 0.5 ? "control" : "treatment";
}

// Use Case 2: JWT Validation at Edge
// Stops unauthorized requests before they reach origin.
// JWT is self-contained — no DB lookup required to validate.
// Just verify the signature and check expiry.
async function edgeJWTValidation(request) {
  const authHeader = request.headers.get("Authorization");
  if (!authHeader?.startsWith("Bearer ")) {
    // Block immediately — origin never sees this request
    return new Response("Unauthorized", { status: 401 });
  }
  const token = authHeader.slice(7);
  const payload = await verifyJWT(token); // crypto.subtle — no network call
  if (!payload) return new Response("Invalid token", { status: 401 });
  // Forward enriched request to origin with user info in headers
  return fetch(request, {
    headers: {
      ...Object.fromEntries(request.headers),
      "X-User-Id": payload.sub,
      "X-User-Role": payload.role,
    },
  });
}

// Use Case 3: Geo-based Routing
// Route users to region-appropriate content or APIs.
// No origin involvement required for the routing decision.
function geoRoute(request, countryCode) {
  const regionMap = {
    DE: "https://eu.api.example.com",
    FR: "https://eu.api.example.com",
    JP: "https://apac.api.example.com",
    AU: "https://apac.api.example.com",
    US: "https://us.api.example.com",
    CA: "https://us.api.example.com",
  };
  const origin = regionMap[countryCode] || "https://us.api.example.com";
  const url = new URL(request.url);
  url.hostname = new URL(origin).hostname;
  return fetch(new Request(url.toString(), request));
}

// ============================================================
// SECTION 5: What Edge Cannot Do
// ============================================================

const EDGE_LIMITATIONS = {
  cpuTimeLimit: {
    description: "10ms CPU (free) / 50ms CPU (paid) per request",
    implication: "No heavy computation: ML inference, video encoding, complex math",
    workaround: "Offload to origin or use Workers AI (GPU-backed, separate billing)",
  },
  memoryLimit: {
    description: "128MB per isolate",
    implication: "Cannot load large ML models, large in-memory datasets",
    workaround: "Stream data, use KV/R2 for storage, keep hot data small",
  },
  noPersistentConnections: {
    description: "Each request is a fresh isolate (mostly)",
    implication: "No long-lived database connections (traditional connection pools)",
    workaround: "HTTP-based DB APIs (Turso REST, Upstash Redis REST, D1 HTTP)",
  },
  noGPU: {
    description: "Worker isolates run on CPU-only infrastructure",
    implication: "Cannot run GPU-accelerated ML inference natively",
    workaround: "Workers AI routes to Cloudflare's separate GPU infrastructure",
  },
  noFileSystem: {
    description: "Workers have no access to the host file system",
    implication: "Cannot read/write files, run shell commands, use native modules",
    workaround: "R2 for object storage, static assets bundled at deploy time",
  },
  noTraditionalDB: {
    description: "TCP connections to PostgreSQL/MySQL are not supported in isolates",
    implication: "Cannot use pg, mysql2, or similar drivers directly",
    workaround: "D1 (SQLite), Turso (HTTP API), PlanetScale (HTTP), Neon (HTTP driver)",
  },
};

// ============================================================
// SECTION 6: Edge vs CDN — The Important Distinction
// ============================================================

// CDN (Content Delivery Network):
//   - Caches STATIC content (HTML, CSS, JS, images)
//   - Cache key = URL (sometimes + Vary headers)
//   - Cache HIT: serve from edge, never touch origin
//   - Cache MISS: fetch from origin, cache, serve
//   - No code execution — just storage and retrieval
//   - Examples: Cloudflare CDN, Fastly, Akamai, CloudFront (cache layer)
//
// Edge Computing:
//   - Runs DYNAMIC code on every request
//   - Can read/write request/response, call external APIs
//   - Can make routing decisions, validate auth, personalize
//   - May or may not cache — that's up to the code
//   - Examples: Cloudflare Workers, Lambda@Edge, Vercel Edge Functions
//
// Relationship: Edge IS CDN + Compute
//   Cloudflare Workers can serve static assets AND run code.
//   The Cache API in Workers lets you implement custom caching logic.
//   Workers can cache the result of dynamic computation for subsequent requests.

// ============================================================
// SECTION 7: Real Hello World — Cloudflare Worker
// ============================================================

// This is a minimal but realistic Cloudflare Worker that demonstrates:
// 1. The module syntax (preferred over addEventListener)
// 2. Request inspection
// 3. URL parsing for routing
// 4. JSON response construction
// 5. Geo metadata from Cloudflare's request object

// --- wrangler.toml (not JS, shown as comment) ---
// name = "hello-edge"
// main = "src/index.js"
// compatibility_date = "2024-01-01"
// [vars]
// ENVIRONMENT = "production"

export default {
  // The fetch handler is called for every incoming HTTP request.
  // request: Web API Request object
  // env:     bindings (KV namespaces, secrets, env vars, R2 buckets)
  // ctx:     execution context (waitUntil for background tasks)
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const { pathname, searchParams } = url;

    // --- Routing ---
    if (pathname === "/health") {
      return Response.json({ status: "ok", timestamp: Date.now() });
    }

    if (pathname === "/api/hello") {
      const name = searchParams.get("name") || "world";

      // Cloudflare enriches every request with geo data at no cost.
      // This is available on all plans — no extra API calls needed.
      const geo = {
        country: request.cf?.country ?? "unknown",
        city: request.cf?.city ?? "unknown",
        timezone: request.cf?.timezone ?? "unknown",
        // cf.colo = IATA code of the Cloudflare datacenter handling this request
        // tells you WHICH edge node the user was routed to
        edgeNode: request.cf?.colo ?? "unknown",
      };

      // Measure: what is the worker's perceived latency for this computation?
      const startTime = Date.now();
      const message = `Hello, ${name}! You are being served from the ${geo.edgeNode} edge node.`;
      const computeMs = Date.now() - startTime; // will be 0 — this is fast

      return Response.json(
        {
          message,
          geo,
          meta: {
            computeMs,
            // Workers do not have process.env — use env bindings
            environment: env.ENVIRONMENT ?? "development",
          },
        },
        {
          headers: {
            // Cache at CDN layer for 60 seconds — subsequent requests won't run code
            "Cache-Control": "public, max-age=60",
            // CORS for browser clients
            "Access-Control-Allow-Origin": "*",
          },
        }
      );
    }

    // 404 fallthrough
    return new Response("Not Found", { status: 404 });
  },
};

// ============================================================
// SECTION 8: Helper Functions (referenced above, defined here)
// ============================================================

function getCookieValue(request, name) {
  // Parse cookie header manually (no document.cookie at edge)
  const cookieHeader = request.headers.get("Cookie") || "";
  const match = cookieHeader.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return match ? match[1] : null;
}

function hashUserId(userId) {
  // Simple djb2-style hash — deterministic, fast, no crypto needed
  // For production: use crypto.subtle for better distribution
  let hash = 5381;
  for (let i = 0; i < userId.length; i++) {
    hash = (hash * 33) ^ userId.charCodeAt(i);
  }
  return Math.abs(hash);
}

async function verifyJWT(token) {
  // Stub — real implementation in L05_edge_auth_and_security.js
  // Uses crypto.subtle.importKey + verify with RS256 or HS256
  try {
    const [, payloadB64] = token.split(".");
    return JSON.parse(atob(payloadB64));
  } catch {
    return null;
  }
}

// ============================================================
// SECTION 9: Deployment Workflow
// ============================================================

// Install Wrangler (Cloudflare's CLI):
//   npm install -g wrangler
//
// Authenticate:
//   wrangler login
//
// Create new project:
//   wrangler init my-worker
//
// Local development (emulates Workers runtime locally):
//   wrangler dev
//   # → available at http://localhost:8787
//   # Hot-reload on file save
//   # KV, D1, R2 emulated locally via Miniflare
//
// Deploy to production (all 275+ edge locations simultaneously):
//   wrangler deploy
//   # → Deploys in ~10 seconds
//   # → New version live globally in <30 seconds
//
// View live logs (tail logs from production):
//   wrangler tail
//   # → Streams console.log output from live traffic
//
// Roll back to previous version:
//   wrangler rollback

// ============================================================
// KEY TAKEAWAYS
// ============================================================
// 1. Edge = code at the network edge, globally distributed, close to users.
// 2. V8 Isolates enable <1ms cold starts — making edge economically viable.
// 3. Best for: auth, routing, personalization, A/B testing, rate limiting.
// 4. Not for: long compute, large memory, persistent connections, large models.
// 5. Edge IS CDN + compute — you get both caching and code execution.
// 6. Data strategy is the hard part: edge workers need edge-native databases
//    to avoid re-introducing latency through centralized DB queries.
