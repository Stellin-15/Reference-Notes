// ============================================================
// L02: Cloudflare Workers — Runtime, Bindings, and APIs
// ============================================================
// WHAT: Cloudflare Workers is the most complete edge computing
//       platform: V8 Isolate runtime with a rich ecosystem of
//       bindings (KV, R2, D1, Durable Objects, Queues, AI).
// WHY:  Workers solves the "edge is stateless" problem with
//       purpose-built stateful primitives, making full-stack
//       applications viable entirely at the edge.
// LEVEL: Foundation → Intermediate
// ============================================================
/*
CONCEPT OVERVIEW:
  Workers uses the Service Worker API — a web standard originally
  designed for browser offline caching. The core primitive is the
  fetch event handler, now expressed as export default { fetch() }.
  Every incoming HTTP request triggers this function. The runtime
  provides Web APIs (fetch, crypto, URL, Request, Response,
  ReadableStream) but NOT Node.js built-ins (no fs, no net, no
  process.env — use env bindings instead).

  Bindings are how Workers connect to external resources:
  KV namespaces, R2 buckets, D1 databases, Durable Objects,
  Service bindings, Queues. They are injected into the handler
  as the `env` argument — type-safe in TypeScript.

PRODUCTION USE CASE:
  A SaaS platform API is built entirely on Workers: routing and
  auth middleware validates JWTs at edge, KV caches feature flags
  and session data (TTL-based), D1 stores user records and
  audit logs (SQLite at edge with read replicas), R2 stores user
  uploads (no egress fees), and Queues handle async jobs like
  email sending and webhook delivery. P99 latency: 12ms globally
  (down from 280ms with a centralized Node.js server).

COMMON MISTAKES:
  1. Using KV for write-heavy or strongly consistent data. KV is
     eventually consistent (~60s propagation). Use D1 or Durable
     Objects when you need read-your-writes consistency.
  2. Blocking the event loop with synchronous heavy computation.
     Workers share a V8 process — a tight CPU loop starves other
     isolates. Break CPU work into chunks or offload to origin.
  3. Not using ctx.waitUntil() for fire-and-forget tasks. If you
     await a background operation inside the main response path,
     you delay the response unnecessarily. waitUntil lets the
     response return while the async work continues.
  4. Storing sensitive data in env vars visible in wrangler.toml.
     Use `wrangler secret put SECRET_NAME` — secrets are encrypted
     and not stored in version control.
*/

// ============================================================
// SECTION 1: Worker Module Syntax
// ============================================================

// Modern Workers use ES module syntax (not legacy addEventListener).
// The default export must have a fetch() method.
// TypeScript: import { Env } from './types' for binding types.

export default {
  // request: Web API Request — url, method, headers, body
  // env:     Typed bindings (KV, R2, D1, secrets, vars)
  // ctx:     ExecutionContext — waitUntil(), passThroughOnException()
  async fetch(request, env, ctx) {
    // Route the request — see Section 3 for routing patterns
    return handleRequest(request, env, ctx);
  },

  // Scheduled handler: triggered by cron (configured in wrangler.toml)
  // event.scheduledTime: timestamp of the scheduled trigger
  // event.cron: the cron expression that fired ("0 0 * * *")
  async scheduled(event, env, ctx) {
    ctx.waitUntil(runDailyJob(env));
  },

  // Queue consumer: processes messages from a Cloudflare Queue
  // batch.messages: array of { id, body, timestamp, ack(), retry() }
  async queue(batch, env) {
    for (const message of batch.messages) {
      await processQueueMessage(message.body, env);
      message.ack(); // Acknowledge — removes from queue
      // message.retry() — puts back in queue for retry
    }
  },
};

// ============================================================
// SECTION 2: Request and Response APIs
// ============================================================

async function demonstrateRequestAPIs(request) {
  // --- URL Parsing ---
  const url = new URL(request.url);
  // url.pathname     → "/api/users/123"
  // url.hostname     → "api.example.com"
  // url.searchParams → URLSearchParams instance
  const userId = url.pathname.split("/").pop();
  const format = url.searchParams.get("format") ?? "json";
  const tags = url.searchParams.getAll("tag"); // repeated params: ?tag=a&tag=b

  // --- Reading Request Body ---
  // IMPORTANT: body can only be consumed once. Clone if needed multiple times.
  const clonedRequest = request.clone();

  if (request.headers.get("Content-Type")?.includes("application/json")) {
    const body = await request.json(); // Parses JSON, throws on invalid JSON
    // Use body...
  }

  if (request.headers.get("Content-Type")?.includes("text/")) {
    const text = await request.text(); // Raw string
  }

  if (request.headers.get("Content-Type")?.includes("multipart/form-data")) {
    const formData = await request.formData(); // FormData instance
    const file = formData.get("upload"); // File object
  }

  // --- Request Metadata ---
  const method = request.method; // "GET", "POST", "PUT", "DELETE", etc.
  const headers = Object.fromEntries(request.headers); // headers as plain object
  const authHeader = request.headers.get("Authorization");

  // --- Cloudflare-Specific Properties ---
  // request.cf is Cloudflare's request metadata — available on all plans
  const cf = request.cf ?? {};
  const country = cf.country; // ISO 3166-1 alpha-2: "US", "DE", "JP"
  const city = cf.city; // "London", "Tokyo"
  const region = cf.region; // "California", "Bavaria"
  const timezone = cf.timezone; // "America/Los_Angeles"
  const asn = cf.asn; // Autonomous System Number (identifies ISP)
  const edgeColo = cf.colo; // "LHR", "NRT" — IATA code of serving edge node
  const botScore = cf.botManagementScore; // 0–99: low = likely bot
  const tlsVersion = cf.tlsVersion; // "TLSv1.3"

  // --- Building Responses ---

  // Simple text response
  const textResponse = new Response("Hello, World!", {
    status: 200,
    headers: { "Content-Type": "text/plain" },
  });

  // JSON response (shorthand) — sets Content-Type: application/json automatically
  const jsonResponse = Response.json({ ok: true, data: { userId, format } });

  // JSON with custom status and headers
  const customResponse = Response.json(
    { error: "Not Found" },
    {
      status: 404,
      headers: {
        "Cache-Control": "no-store",
        "X-Request-Id": crypto.randomUUID(),
      },
    }
  );

  // Redirect
  const redirectResponse = Response.redirect("https://example.com", 302);

  return jsonResponse;
}

// ============================================================
// SECTION 3: Routing Patterns
// ============================================================

// Option A: Manual routing (no dependencies, appropriate for small workers)
function manualRouter(request, env, ctx) {
  const url = new URL(request.url);
  const { pathname, method } = { pathname: url.pathname, method: request.method };

  if (method === "GET" && pathname === "/") return handleHome(request, env);
  if (method === "GET" && pathname.startsWith("/api/users/")) return handleGetUser(request, env);
  if (method === "POST" && pathname === "/api/users") return handleCreateUser(request, env);
  if (method === "GET" && pathname === "/health") return Response.json({ ok: true });

  return new Response("Not Found", { status: 404 });
}

// Option B: itty-router (most popular Workers router, ~450 bytes gzipped)
// import { Router } from 'itty-router';
// const router = Router();
// router.get('/api/users/:id', ({ params, env }) => handleGetUser(params.id, env));
// router.post('/api/users', async ({ request, env }) => handleCreateUser(request, env));
// router.all('*', () => new Response('Not Found', { status: 404 }));
// export default { fetch: router.fetch };

// Option C: Hono (more features, Express-like, works on multiple runtimes)
// import { Hono } from 'hono';
// const app = new Hono();
// app.use('*', authMiddleware);
// app.get('/api/users/:id', (c) => c.json({ id: c.req.param('id') }));
// export default app;

// ============================================================
// SECTION 4: KV Store (Workers KV)
// ============================================================

// Workers KV: globally replicated key-value store.
// Key: string (max 512 bytes). Value: string, ArrayBuffer, ReadableStream.
// Max value size: 25MB.
// CONSISTENCY: Eventually consistent. A write may take up to 60 seconds
// to propagate to all edge nodes. Use D1 or Durable Objects for
// strongly consistent data.
// BEST FOR: config, feature flags, session data, rate limit counters
//           with tolerable staleness, cached API responses.

// wrangler.toml configuration:
// [[kv_namespaces]]
// binding = "MY_KV"
// id = "abc123..."
// preview_id = "def456..."  ← for wrangler dev

async function kvExamples(env) {
  const KV = env.MY_KV; // injected binding

  // --- Basic CRUD ---

  // Write a string value
  await KV.put("user:123:name", "Alice");

  // Write with TTL (time-to-live): auto-deletes after N seconds
  await KV.put("session:abc", JSON.stringify({ userId: 123 }), {
    expirationTtl: 3600, // 1 hour
  });

  // Write with absolute expiry (Unix timestamp)
  await KV.put("cache:products", JSON.stringify([]), {
    expiration: Math.floor(Date.now() / 1000) + 3600,
  });

  // Write with metadata (small JSON stored alongside value, free to read)
  await KV.put("file:img1.jpg", imageBuffer, {
    metadata: { mimeType: "image/jpeg", uploadedAt: Date.now() },
  });

  // Read a value
  const name = await KV.get("user:123:name"); // returns string or null
  const session = await KV.get("session:abc", "json"); // parses JSON automatically
  const buffer = await KV.get("file:img1.jpg", "arrayBuffer");
  const stream = await KV.get("large:file", "stream"); // ReadableStream for large values

  // Read with metadata
  const { value, metadata } = await KV.getWithMetadata("file:img1.jpg", "arrayBuffer");

  // Delete
  await KV.delete("session:abc");

  // List keys (with optional prefix filter)
  const { keys, list_complete, cursor } = await KV.list({ prefix: "user:", limit: 100 });
  // keys: [{ name: "user:123:name", expiration?: number, metadata?: any }]
  // list_complete: false if there are more keys (paginate with cursor)

  // --- Pattern: Cache-aside with KV ---
  async function getProductCached(productId, env) {
    const cacheKey = `product:${productId}`;

    // Try KV first (edge-local read, <1ms)
    const cached = await env.MY_KV.get(cacheKey, "json");
    if (cached) return cached;

    // Cache miss: fetch from origin database
    const product = await fetchProductFromDB(productId, env);

    // Populate cache for 5 minutes
    // ctx.waitUntil would be used here in a real handler to not block response
    await env.MY_KV.put(cacheKey, JSON.stringify(product), { expirationTtl: 300 });

    return product;
  }
}

// ============================================================
// SECTION 5: R2 Object Storage
// ============================================================

// R2: S3-compatible object storage with ZERO egress fees.
// This is the key differentiator vs S3 (S3 charges $0.09/GB egress).
// Objects up to 5TB. Strong consistency (unlike KV).
// Accessible via: Workers binding, S3 API, public URLs.

// wrangler.toml:
// [[r2_buckets]]
// binding = "MY_BUCKET"
// bucket_name = "my-bucket-name"

async function r2Examples(request, env) {
  const bucket = env.MY_BUCKET;

  // --- Get object ---
  const object = await bucket.get("images/photo.jpg");
  if (!object) return new Response("Not Found", { status: 404 });

  // Stream the object directly to the response (efficient — no buffering)
  return new Response(object.body, {
    headers: {
      "Content-Type": object.httpMetadata?.contentType ?? "application/octet-stream",
      "Content-Length": object.size.toString(),
      "ETag": object.httpEtag,
      "Cache-Control": "public, max-age=31536000, immutable",
    },
  });
}

async function r2Upload(request, env) {
  const bucket = env.MY_BUCKET;
  const key = `uploads/${crypto.randomUUID()}.jpg`;

  // Put object — body can be ReadableStream, ArrayBuffer, string
  await bucket.put(key, request.body, {
    httpMetadata: {
      contentType: request.headers.get("Content-Type") ?? "application/octet-stream",
    },
    customMetadata: {
      uploadedBy: "user-123",
      uploadedAt: new Date().toISOString(),
    },
  });

  return Response.json({ key, url: `https://assets.example.com/${key}` });
}

// ============================================================
// SECTION 6: D1 Database (SQLite at Edge)
// ============================================================

// D1: Cloudflare's managed SQLite database with edge read replicas.
// Writes go to the primary (single region — strong consistency).
// Reads can be served from replicas near the user (eventual consistency,
// replica lag typically <50ms).
// D1 is NOT a distributed write database. It is a distributed READ database.

// wrangler.toml:
// [[d1_databases]]
// binding = "DB"
// database_name = "my-db"
// database_id = "abc-123-def"

async function d1Examples(env) {
  const db = env.DB;

  // --- Single row query ---
  const user = await db
    .prepare("SELECT id, name, email, role FROM users WHERE id = ?")
    .bind(userId)         // ? placeholders, positional binding, SQL injection safe
    .first();             // Returns first row as object, or null
  // user: { id: 123, name: "Alice", email: "alice@...", role: "admin" }

  // --- Multi-row query ---
  const { results: users } = await db
    .prepare("SELECT * FROM users WHERE role = ? AND active = 1 LIMIT ?")
    .bind("admin", 50)
    .all(); // Returns { results: Row[], success: boolean, meta: {...} }

  // --- Count / scalar ---
  const { count } = await db
    .prepare("SELECT COUNT(*) as count FROM orders WHERE user_id = ?")
    .bind(userId)
    .first();

  // --- Mutations (INSERT, UPDATE, DELETE) ---
  const insertResult = await db
    .prepare("INSERT INTO users (name, email, role, created_at) VALUES (?, ?, ?, ?)")
    .bind("Bob", "bob@example.com", "user", new Date().toISOString())
    .run();
  // insertResult.meta.last_row_id — the newly inserted row ID
  const newUserId = insertResult.meta.last_row_id;

  // --- Transactions (batch) ---
  // batch() executes multiple statements atomically
  const [insertedUser, insertedProfile] = await db.batch([
    db.prepare("INSERT INTO users (name, email) VALUES (?, ?)").bind("Carol", "carol@example.com"),
    db.prepare("INSERT INTO profiles (user_id, bio) VALUES (last_insert_rowid(), ?)").bind("Engineer"),
  ]);

  // --- Raw SQL (for migrations, schema inspection) ---
  await db.exec(`
    CREATE TABLE IF NOT EXISTS audit_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      action TEXT NOT NULL,
      created_at TEXT DEFAULT (datetime('now'))
    )
  `);
}

// ============================================================
// SECTION 7: Durable Objects (Stateful Edge)
// ============================================================

// Durable Objects: single-threaded, globally unique stateful objects.
// Each Durable Object has:
//   - A stable ID (string or auto-generated)
//   - Transactional key-value storage (this.ctx.storage)
//   - Request handling via fetch()
//   - Optional WebSocket handling
// GUARANTEE: For a given ID, only ONE instance runs globally at any time.
// This makes Durable Objects suitable for: rate limiting, real-time
// collaboration, game state, WebSocket rooms, counters.

// --- Durable Object class (deployed alongside the Worker) ---
export class RateLimiter {
  constructor(ctx, env) {
    this.ctx = ctx; // ctx.storage for persistent KV
    this.env = env;
  }

  async fetch(request) {
    const url = new URL(request.url);
    const action = url.pathname.slice(1); // "check" or "reset"

    if (action === "check") {
      return this.checkRateLimit();
    }
    if (action === "reset") {
      await this.ctx.storage.delete("count");
      return Response.json({ reset: true });
    }
    return new Response("Not Found", { status: 404 });
  }

  async checkRateLimit() {
    // Storage reads/writes are transactional and durable (persisted to disk)
    const count = (await this.ctx.storage.get("count")) ?? 0;
    const windowStart = (await this.ctx.storage.get("windowStart")) ?? Date.now();

    // Reset window every 60 seconds
    const now = Date.now();
    if (now - windowStart > 60_000) {
      await this.ctx.storage.put("count", 1);
      await this.ctx.storage.put("windowStart", now);
      return Response.json({ allowed: true, remaining: 99 });
    }

    if (count >= 100) {
      return Response.json({ allowed: false, remaining: 0 }, { status: 429 });
    }

    await this.ctx.storage.put("count", count + 1);
    return Response.json({ allowed: true, remaining: 100 - count - 1 });
  }
}

// --- Using Durable Objects from a Worker ---
async function checkRateLimit(request, env) {
  const ip = request.headers.get("CF-Connecting-IP") ?? "unknown";

  // Get the Durable Object ID for this IP (deterministic — same IP always
  // maps to the same Durable Object instance, globally)
  const id = env.RATE_LIMITER.idFromName(`ip:${ip}`);
  const stub = env.RATE_LIMITER.get(id);

  // Forward a request to the Durable Object
  const result = await stub.fetch("https://do/check");
  const { allowed, remaining } = await result.json();

  if (!allowed) {
    return new Response("Too Many Requests", {
      status: 429,
      headers: { "Retry-After": "60", "X-RateLimit-Remaining": "0" },
    });
  }
  return null; // Proceed with the request
}

// ============================================================
// SECTION 8: Queues (Async Processing)
// ============================================================

// Workers Queues: message queue for async processing at edge.
// Producer sends messages; consumer (another Worker) processes them.
// At-least-once delivery. Auto-retry with exponential backoff.
// Batch processing: consumer receives up to 10 messages at once.

// wrangler.toml:
// [[queues.producers]]
// queue = "my-queue"
// binding = "MY_QUEUE"
//
// [[queues.consumers]]
// queue = "my-queue"
// max_batch_size = 10
// max_batch_timeout = 5  ← wait up to 5s to fill a batch

async function queueProducerExample(env) {
  // Send a single message
  await env.MY_QUEUE.send({ type: "send_email", userId: 123, template: "welcome" });

  // Send multiple messages in one call (more efficient)
  await env.MY_QUEUE.sendBatch([
    { body: { type: "webhook", url: "https://...", payload: {} } },
    { body: { type: "analytics", event: "signup", userId: 123 } },
  ]);
}

// ============================================================
// SECTION 9: Full Example — Edge API with All Primitives
// ============================================================

// A realistic mini-API that uses routing, KV caching, D1, and auth middleware.

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

async function handleRequest(request, env, ctx) {
  // Handle CORS preflight
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  const url = new URL(request.url);

  // Apply auth middleware to protected routes
  if (url.pathname.startsWith("/api/")) {
    const authError = await authMiddleware(request, env);
    if (authError) return addCorsHeaders(authError);
  }

  // Route dispatch
  try {
    let response;
    if (request.method === "GET" && url.pathname.startsWith("/api/products")) {
      response = await handleGetProducts(url, env, ctx);
    } else if (request.method === "GET" && url.pathname.startsWith("/api/users/")) {
      response = await handleGetUser(url, env);
    } else if (request.method === "POST" && url.pathname === "/api/users") {
      response = await handleCreateUser(request, env, ctx);
    } else {
      response = new Response("Not Found", { status: 404 });
    }
    return addCorsHeaders(response);
  } catch (err) {
    console.error("Unhandled error:", err.message, err.stack);
    return addCorsHeaders(Response.json({ error: "Internal Server Error" }, { status: 500 }));
  }
}

function addCorsHeaders(response) {
  const newResponse = new Response(response.body, response);
  Object.entries(CORS_HEADERS).forEach(([k, v]) => newResponse.headers.set(k, v));
  return newResponse;
}

async function authMiddleware(request, env) {
  const token = request.headers.get("Authorization")?.replace("Bearer ", "");
  if (!token) return Response.json({ error: "Missing token" }, { status: 401 });

  // Check token in KV (fast edge lookup — no origin call)
  const session = await env.MY_KV.get(`session:${token}`, "json");
  if (!session) return Response.json({ error: "Invalid token" }, { status: 401 });

  // Attach user info to request headers for downstream handlers
  // (Workers requests are immutable — pass via a context object in real apps)
  return null; // null = auth passed
}

async function handleGetProducts(url, env, ctx) {
  const cacheKey = `products:${url.search}`;

  // Layer 1: Check KV cache (edge-local, <1ms)
  const cached = await env.MY_KV.get(cacheKey, "json");
  if (cached) {
    return Response.json(cached, { headers: { "X-Cache": "HIT" } });
  }

  // Layer 2: Query D1 (SQLite at edge)
  const category = url.searchParams.get("category");
  const query = category
    ? env.DB.prepare("SELECT * FROM products WHERE category = ? LIMIT 50").bind(category)
    : env.DB.prepare("SELECT * FROM products LIMIT 50");

  const { results } = await query.all();

  // Populate KV cache for next request (background — does not delay response)
  ctx.waitUntil(
    env.MY_KV.put(cacheKey, JSON.stringify(results), { expirationTtl: 300 })
  );

  return Response.json(results, { headers: { "X-Cache": "MISS" } });
}

async function handleGetUser(url, env) {
  const id = url.pathname.split("/").pop();
  const user = await env.DB.prepare("SELECT id, name, email FROM users WHERE id = ?")
    .bind(id)
    .first();
  if (!user) return Response.json({ error: "User not found" }, { status: 404 });
  return Response.json(user);
}

async function handleCreateUser(request, env, ctx) {
  const { name, email } = await request.json();
  if (!name || !email) {
    return Response.json({ error: "name and email required" }, { status: 400 });
  }

  const result = await env.DB.prepare(
    "INSERT INTO users (name, email, created_at) VALUES (?, ?, ?)"
  )
    .bind(name, email, new Date().toISOString())
    .run();

  const newUser = { id: result.meta.last_row_id, name, email };

  // Queue a welcome email (non-blocking)
  ctx.waitUntil(env.MY_QUEUE.send({ type: "welcome_email", user: newUser }));

  return Response.json(newUser, { status: 201 });
}

// Stub helpers
async function runDailyJob(env) { /* ... */ }
async function processQueueMessage(body, env) { /* ... */ }
async function fetchProductFromDB(productId, env) { return {}; }
const userId = "123";
