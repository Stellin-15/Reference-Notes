# API Design — Principal Engineer Deep Dive

Companion to the existing lessons. Narrative depth on core topics, then a
comprehensive common-to-uncommon reference.


## REST Maturity & Real-World Pragmatism

**Beyond the lesson**: Roy Fielding's REST dissertation describes HATEOAS
(Hypermedia As The Engine Of Application State — responses include links
telling the client what it can do NEXT) as core to "true" REST — almost no
production API actually implements this (Stripe, GitHub, Twilio's APIs are
all "RESTful" by common industry usage but not HATEOAS-compliant). Knowing
this gap matters for interviews: the pragmatic industry definition of REST
(resource-based URLs, HTTP verbs mapped to CRUD, JSON payloads) and the
academically strict definition are genuinely different things, and
conflating them in a design discussion is a real signal either way depending on the room.

**Worked example**: Idempotency keys for POST requests — a payment API
POST isn't naturally idempotent (retrying creates a duplicate charge); the
fix is a client-generated `Idempotency-Key` header the server stores
against the request's result, so a RETRIED request with the same key
returns the ORIGINAL result instead of re-executing — this exact pattern
(Stripe popularized it) is now expected in any payments-adjacent API design interview.

**Interview Q&A**:
- *Q: PUT vs PATCH vs POST for updating a resource?* A: PUT replaces the entire resource (idempotent — sending the same PUT twice yields the same end state); PATCH applies a partial update (idempotent only if the patch itself is, e.g. "set field X to Y," NOT if it's "increment field X by 1"); POST creates a new resource or triggers a non-idempotent action.


## Versioning Strategies

**Beyond the lesson**: URL versioning (`/v1/users`) is the most visible
and common but the least flexible — every consumer must explicitly migrate.
Header-based versioning (`Accept: application/vnd.myapi.v2+json`) is
cleaner architecturally but harder for developers to discover/debug (it's
invisible in the URL, in browser history, in casual curl testing). Many
mature APIs (Stripe again) instead version by DATE (`Stripe-Version:
2024-06-20`) tied to a specific behavior snapshot, letting them ship
incremental changes without a disruptive major-version bump for every tweak.

**Interview Q&A**:
- *Q: How do you deprecate a v1 API endpoint without breaking existing customers?* A: A `Sunset` HTTP header (RFC 8594) announcing the exact retirement date, a deprecation notice in response headers/docs well in advance, usage analytics identifying which customers still call it (so you can proactively reach out, not just broadcast and hope), and a genuinely long grace period for anything with real external consumers.


## GraphQL vs REST vs gRPC — The Real Tradeoffs

**Beyond the lesson**: GraphQL's headline benefit (client specifies
exactly the fields it needs, no over/under-fetching) has a REAL operational
cost most tutorials skip: the N+1 query problem is WORSE by default in
GraphQL than REST, because a single query resolving nested fields can
trigger a database call PER ITEM in a list unless you implement
DataLoader-style batching explicitly — GraphQL doesn't solve N+1, it just
makes it easier to accidentally create.

**Worked example**: gRPC's real advantage over REST/JSON isn't just
"faster" — it's the SCHEMA CONTRACT. A `.proto` file defines the exact
message shape both client and server compile against; a REST API's
"contract" is usually just documentation (OpenAPI/Swagger helps, but
nothing enforces the server actually matches its own spec) — gRPC makes
client/server drift a COMPILE-TIME error instead of a runtime surprise.

**Tradeoff table**:
| Style | Best fit | Weak point |
|---|---|---|
| REST | Public APIs, broad client compatibility, caching via HTTP semantics | Over/under-fetching, no compile-time contract |
| GraphQL | Complex, nested, client-driven data needs (mobile apps with varying screen needs) | N+1 risk, harder caching (no simple URL-based cache keys), query complexity/cost control needed |
| gRPC | Internal service-to-service, performance-critical, strongly-typed teams | Not browser-native without gRPC-Web, less human-debuggable (binary, not plain JSON) |


## COMPREHENSIVE TOOL & PRACTICE REFERENCE — COMMON TO UNCOMMON

### API specification & documentation
- **OpenAPI (Swagger)** — the near-universal REST API spec format;
  generates docs, client SDKs, and server stubs from one source of truth —
  the modern expectation for any public-facing REST API.
- **AsyncAPI** — OpenAPI's equivalent for EVENT-DRIVEN/async APIs (message
  queues, WebSockets) — a real, growing spec as event-driven architectures spread.
- **Postman / Insomnia** — the dominant API-testing/documentation-sharing
  tools; Postman's collection-sharing and mock-server features are heavily
  used for cross-team API contracts before implementation is even finished.
- **Stoplight / Redocly** — API-design-first tooling: design the OpenAPI
  spec BEFORE writing code, review it as a team artifact, generate mocks
  for frontend teams to build against in parallel.

### API gateways & management
- **Kong / Apigee / AWS API Gateway / Azure API Management** — the
  standard API gateway layer: rate limiting, auth, request/response
  transformation, and analytics centralized in front of many backend
  services rather than reimplemented per-service.
- **Rate limiting algorithms**: token bucket (allows bursts up to a
  capacity, refills steadily — the most common real-world choice), leaky
  bucket (smooths bursts into a steady output rate), fixed/sliding window
  counters (simpler to implement, has edge effects at window boundaries a
  token bucket avoids).

### API testing & contract testing
- **Pact** — consumer-driven contract testing (see Testing & QA Engineering
  Notes) — verifies a provider's API actually satisfies what EVERY consumer
  expects, catching breaking changes before deployment rather than in production.
- **Schemathesis / Dredd** — property-based/spec-driven API testing tools
  that generate test cases directly FROM an OpenAPI spec, catching
  spec-implementation drift automatically.

### Design patterns beyond CRUD
- **Cursor-based pagination** vs **offset pagination** — offset
  (`?page=3&size=20`) is simple but breaks under concurrent inserts (items
  shift between pages, causing skips/duplicates); cursor-based
  (`?after=eyJpZCI6MTIzfQ`) pagination is stable under concurrent writes
  because it's anchored to a specific record, not a numeric position — the
  standard choice for any high-write-volume feed/list endpoint.
- **HTTP caching semantics** — `ETag`/`If-None-Match` (conditional
  requests, 304 Not Modified) and `Cache-Control` directives are genuinely
  underused free performance wins most REST APIs never bother wiring up.
- **Webhooks design** — signature verification (HMAC, see Cryptography
  Notes), retry-with-backoff on the SENDER side, and idempotent processing
  on the RECEIVER side (webhooks WILL be delivered more than once
  eventually) are the three things a "just POST a payload somewhere" naive
  webhook implementation reliably gets wrong first.


## NICHE BUT REAL

- **BFF (Backend For Frontend) pattern** — a dedicated API layer tailored
  to ONE specific client (mobile app vs web app each get their own BFF)
  instead of one generic API serving all clients' differing needs — trades
  some duplication for each client getting exactly the shape of data it needs.
- **API-first / design-first development** — writing the OpenAPI spec and
  getting cross-team sign-off BEFORE implementation starts, specifically so
  frontend and backend teams can build in parallel against a shared, agreed contract.
- **gRPC-Web / gRPC gateway** — bridges gRPC's binary protocol to
  browsers/REST clients that can't speak native gRPC — used when an
  internal gRPC-based architecture needs to expose a REST-compatible edge
  for external or browser clients without a full parallel REST implementation.
- **API monetization/usage-based billing infrastructure** — Stripe
  Billing, Lago, Metronome — increasingly a distinct engineering concern
  for API-first companies charging per-call/per-usage, requiring accurate,
  auditable metering built into the API layer itself.
