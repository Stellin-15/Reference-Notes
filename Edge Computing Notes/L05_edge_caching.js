// ============================================================
// L05: Edge Caching Strategies
// ============================================================
// WHAT: Storing response bodies at edge PoPs so repeat requests never hit
//       origin, controlled via HTTP caching headers and CDN-specific
//       extensions (surrogate keys, ESI).
// WHY:  Origin offload is the single biggest lever for both latency (a
//       cache HIT never leaves the edge) and cost (fewer origin compute
//       cycles, less egress bandwidth from origin).
// LEVEL: Intermediate
// ============================================================

/*
CONCEPT OVERVIEW:
Edge caching decisions are driven by standard HTTP Cache-Control directives
PLUS CDN-specific extensions for invalidation that HTTP itself doesn't
define (there's no standard "purge this specific cached entry" HTTP verb).

The core tension: cache TOO aggressively and you serve stale data; cache
TOO conservatively and origin gets hammered. `stale-while-revalidate` is
the modern answer — serve the stale cached response immediately (fast),
while asynchronously refreshing it in the background for the NEXT request.

PRODUCTION USE CASE:
A product-catalog API sets `Cache-Control: public, max-age=60,
stale-while-revalidate=300`. Under normal traffic, 99% of requests are
edge cache hits at effectively 0ms added latency. When a product's price
changes, the origin publishes an event that triggers a surrogate-key purge
for that specific product's cache entries — WITHOUT invalidating the
other 999,999 unrelated cached product pages.

COMMON MISTAKES:
  - Setting `Vary: User-Agent` (or any high-cardinality header) — this
    multiplies cache entries per unique header value, collapsing your hit
    ratio toward zero because almost every request has a unique UA string.
  - No cache-stampede protection: max-age expires, and 500 simultaneous
    requests all miss and hit origin simultaneously — see "request
    collapsing" below.
  - Caching authenticated/personalized responses with `public` instead of
    `private` — leaks one user's data to another user hitting the same
    cache key.
*/

// ------------------------------------------------------------------
// 1. Cache-Control directives — the full toolbox
// ------------------------------------------------------------------
const CACHE_CONTROL_DIRECTIVES = {
  "max-age=N": "Fresh for N seconds from response generation — applies to "
    + "both browser AND edge caches unless overridden by s-maxage.",
  "s-maxage=N": "Fresh for N seconds, but ONLY for shared (CDN/proxy) "
    + "caches — lets you cache longer at the edge than in the user's "
    + "browser, e.g. `max-age=0, s-maxage=3600`.",
  "stale-while-revalidate=N": "After max-age expires, serve the stale "
    + "response immediately for up to N more seconds WHILE fetching a "
    + "fresh copy in the background — the user never waits on a slow "
    + "origin round trip.",
  "stale-if-error=N": "If origin is down/erroring, serve the stale cached "
    + "response for up to N seconds instead of propagating the error — a "
    + "cheap resilience win for free.",
  "no-store": "Never cache anywhere, not even briefly — for genuinely "
    + "sensitive/unique responses (e.g. a one-time payment confirmation).",
  "no-cache": "Misleadingly named — CAN be cached, but must be "
    + "revalidated (conditional request, ETag/If-None-Match) with origin "
    + "before being served. Not the same as no-store.",
  "private": "Cacheable only in the end user's own browser, never in a "
    + "shared/CDN cache — required for personalized/authenticated responses.",
  "public": "Explicitly cacheable by shared caches even for responses that "
    + "would otherwise be considered private-by-default (e.g. with an "
    + "Authorization header present).",
};

// ------------------------------------------------------------------
// 2. Vary header — the cardinality trap
// ------------------------------------------------------------------
const VARY_HEADER_NOTES = `
"Vary: Accept-Encoding" is safe and common (br/gzip/identity — a handful
of values). "Vary: Accept-Language" is usually fine (dozens of locales,
bounded). "Vary: User-Agent" or "Vary: Cookie" is almost always a mistake
— thousands of distinct UA strings or per-session cookies mean the cache
key becomes effectively unique per request, and your cache HIT ratio
collapses to near 0% while still paying the cache infrastructure's
overhead. If you need per-locale caching, normalize to a small, bounded
custom header ("X-Locale: en-US") set by an earlier edge rule instead of
varying on the raw client header.
`;

// ------------------------------------------------------------------
// 3. Surrogate keys / cache tags — targeted invalidation
// ------------------------------------------------------------------
const SURROGATE_KEYS_EXAMPLE = `
// Origin response includes a tag identifying everything this response
// depends on — lets you purge precisely, not "purge everything" or
// "purge by exact URL only".
HTTP/1.1 200 OK
Cache-Control: public, max-age=3600
Surrogate-Key: product-1234 category-shoes catalog-v2

// Later, when product 1234's price changes, purge ONLY that tag —
// every cached URL that included "product-1234" in its Surrogate-Key
// is invalidated, e.g. the product page, a category listing snippet,
// and a search-result card, without touching unrelated cached pages.
curl -X POST https://api.cdn-provider.com/purge \\
  -H "Authorization: Bearer $CDN_TOKEN" \\
  -d '{"tags": ["product-1234"]}'
`;

// ------------------------------------------------------------------
// 4. Cache stampede protection — request collapsing
// ------------------------------------------------------------------
const REQUEST_COLLAPSING_NOTES = `
When a cached entry expires and 500 concurrent requests arrive for the
same URL, a naive edge would forward all 500 to origin simultaneously
("thundering herd"). Request collapsing means the edge PoP recognizes
"I already have an in-flight origin request for this exact cache key" and
queues the other 499 requests to be satisfied by the SAME origin
response once it returns — origin sees 1 request, not 500. Most major
CDNs (Cloudflare, Fastly, Akamai) do this automatically; verify it's
enabled rather than assuming it, since it's not guaranteed by the HTTP
spec itself.
`;

// ------------------------------------------------------------------
// 5. Edge-Side Includes (ESI) — partial page caching
// ------------------------------------------------------------------
const ESI_EXAMPLE = `
<!-- The static shell (nav, footer) is cached for hours; the personalized
     fragment is fetched fresh (or from a much shorter-TTL cache) on
     every request — the CDN assembles both at the edge before responding. -->
<html>
  <body>
    <esi:include src="/fragments/nav" />           <!-- cached 1 hour -->
    <div id="content"> ... mostly-static page ... </div>
    <esi:include src="/fragments/cart-summary" />  <!-- cached 0s, per-user -->
  </body>
</html>
`;

// ------------------------------------------------------------------
// 6. Cache-aside at edge with a KV store
// ------------------------------------------------------------------
const EDGE_CACHE_ASIDE = `
export default {
  async fetch(request, env) {
    const key = new URL(request.url).pathname;

    // 1. Check edge KV first (near-0ms read, eventually consistent)
    const cached = await env.PAGE_CACHE.get(key, "json");
    if (cached) return Response.json(cached);

    // 2. Miss — fetch from origin
    const originResponse = await fetch(`https://origin.internal${key}`);
    const data = await originResponse.json();

    // 3. Populate cache for next request, with a TTL
    await env.PAGE_CACHE.put(key, JSON.stringify(data), { expirationTtl: 60 });
    return Response.json(data);
  },
};
`;

// ------------------------------------------------------------------
// 7. Cache analytics — the metric that actually matters
// ------------------------------------------------------------------
const CACHE_ANALYTICS_NOTES = {
  hit_ratio: "cache HITs / total requests — the primary health metric. A "
    + "drop usually means a Vary-header cardinality problem or a TTL "
    + "regression, not 'more traffic'.",
  stale_ratio: "% of responses served from stale-while-revalidate — a high "
    + "number can mean origin is too slow to keep up with the "
    + "revalidation window, not necessarily a problem on its own.",
  origin_offload: "1 - (origin requests / total requests) — the business "
    + "metric that maps directly to origin compute cost savings.",
};

module.exports = {
  CACHE_CONTROL_DIRECTIVES,
  VARY_HEADER_NOTES,
  SURROGATE_KEYS_EXAMPLE,
  REQUEST_COLLAPSING_NOTES,
  ESI_EXAMPLE,
  EDGE_CACHE_ASIDE,
  CACHE_ANALYTICS_NOTES,
};

/*
TRADING/PRODUCTION CONTEXT EXAMPLE:
A market-data API serving delayed (15-minute) quotes sets
`Cache-Control: public, max-age=5, stale-while-revalidate=30` — tight
enough that data is never more than 5 seconds stale from the edge's
perspective, but with SWR absorbing traffic spikes around market open
without a stampede on origin. Real-time (sub-second) quote endpoints set
`no-store` entirely — caching those would be a correctness bug, not a
performance win.
*/
