// ============================================================
// L06: Security at the Edge
// ============================================================
// WHAT: Enforcing WAF rules, bot detection, auth validation, and DDoS
//       mitigation at the edge PoP — before malicious/invalid traffic ever
//       reaches origin infrastructure.
// WHY:  Every request blocked at the edge is a request your origin never
//       has to spend CPU, DB connections, or bandwidth on. It's also the
//       only place you can absorb a volumetric DDoS attack — origin
//       capacity is always finite; a global edge network's aggregate
//       capacity is orders of magnitude larger.
// LEVEL: Advanced
// ============================================================

/*
CONCEPT OVERVIEW:
Edge security operates on a "fail fast, fail cheap" principle: cheap checks
(IP reputation, rate limits) run first and reject obviously-bad traffic
before expensive checks (JWT signature verification, WAF rule evaluation)
even execute. This layered filtering is what lets a single edge PoP absorb
attack traffic that would instantly overwhelm an origin server.

JWT validation AT THE EDGE (rather than forwarding every request to origin
to validate) is a key latency optimization — the edge has the issuer's
public key (JWKS) cached locally and can verify a signature without any
network call, rejecting invalid tokens in microseconds.

PRODUCTION USE CASE:
A public API gateway validates JWT signatures at the edge for every
request. Requests with invalid/expired/missing tokens are rejected with a
401 at the edge — origin never even sees them, meaning a credential-
stuffing attack against the login endpoint doesn't consume origin database
connections trying (and failing) auth checks 10,000 times a second.

COMMON MISTAKES:
  - Validating JWT signature at the edge but not checking `exp`/`nbf`
    claims — signature validity alone doesn't mean the token is still
    valid in time.
  - Relying solely on IP-based rate limiting — attackers rotate through
    thousands of residential proxy IPs; combine with behavioral/fingerprint
    signals.
  - Treating edge WAF rules as "set and forget" — false positive rates
    need monitoring; an overly aggressive rule can block legitimate traffic
    (a common cause of mysterious "some users can't log in" incidents).
*/

// ------------------------------------------------------------------
// 1. WAF rules — pattern matching malicious requests
// ------------------------------------------------------------------
const WAF_RULE_EXAMPLES = `
// Conceptual WAF rule set (syntax varies by provider — Cloudflare/AWS WAF/etc.)

// OWASP Core Rule Set (CRS) — a maintained, community rule set catching
// common attack patterns: SQLi signatures, XSS payloads, path traversal.
// Deployed as a managed ruleset, not hand-written per-app.
rule "block-sqli-crs" {
  managed_ruleset = "owasp-crs-3.3"
  action = "block"
  sensitivity = "medium"   // higher sensitivity = more false positives
}

// Custom rule: rate limit by IP on a sensitive endpoint
rule "rate-limit-login" {
  match = { path = "/api/login", method = "POST" }
  rate_limit = { requests = 5, period_seconds = 60, action = "challenge" }
}

// Geo-blocking: reject traffic from regions with no legitimate user base
rule "geo-block" {
  match = { country = ["KP", "IR"] }  // example — actual list depends on business need
  action = "block"
}

// Block by User-Agent pattern (known bad scanners/scrapers)
rule "block-known-scanners" {
  match = { user_agent_regex = "(sqlmap|nikto|nmap)" }
  action = "block"
}
`;

// ------------------------------------------------------------------
// 2. DDoS mitigation — volumetric vs L7
// ------------------------------------------------------------------
const DDOS_MITIGATION_NOTES = {
  volumetric: "Overwhelm bandwidth/connection capacity (UDP floods, "
    + "SYN floods, amplification attacks). Mitigated by the CDN's sheer "
    + "aggregate network capacity absorbing the traffic BEFORE it reaches "
    + "any single origin's finite pipe — this is largely infrastructure "
    + "scale, not clever filtering.",
  layer7: "Application-layer floods that look like legitimate HTTP traffic "
    + "(e.g. repeatedly hitting an expensive search endpoint). Requires "
    + "behavioral analysis, not just packet-rate limiting — this is where "
    + "bot management and rate limiting rules (below) do the real work.",
};

// ------------------------------------------------------------------
// 3. Bot management
// ------------------------------------------------------------------
const BOT_MANAGEMENT_TECHNIQUES = {
  js_challenge: "Serve a JS snippet that must execute and return a token "
    + "before the real request is allowed — headless/non-browser bots "
    + "typically can't execute it, filtering out the cheapest bot tier.",
  captcha: "Escalation from JS challenge for suspicious-but-not-certain "
    + "traffic — higher friction, reserved for borderline cases to avoid "
    + "annoying legitimate users.",
  fingerprinting: "TLS fingerprint (JA3), HTTP header ordering, and "
    + "browser API surface consistency checks — distinguishes real "
    + "browsers from scripted clients even when the UA string is spoofed "
    + "to look legitimate.",
  behavioral_scoring: "Mouse movement entropy, request timing patterns, "
    + "navigation sequence — a composite score rather than a single "
    + "binary signal, reducing false positives vs any single check alone.",
};

// ------------------------------------------------------------------
// 4. JWT validation at the edge (no origin round trip)
// ------------------------------------------------------------------
const EDGE_JWT_VALIDATION = `
import { jwtVerify, createRemoteJWKSet } from "jose";

// JWKS is fetched once and cached in the isolate/KV — subsequent
// validations use the cached public key with zero network calls.
const JWKS = createRemoteJWKSet(new URL("https://auth.internal/.well-known/jwks.json"));

export default {
  async fetch(request) {
    const authHeader = request.headers.get("Authorization");
    if (!authHeader?.startsWith("Bearer ")) {
      return new Response("Unauthorized", { status: 401 });
    }
    const token = authHeader.slice(7);

    try {
      // Verifies signature AND standard claims (exp, nbf) in one call —
      // this whole block executes in microseconds with a cached JWKS,
      // rejecting invalid tokens before any origin request is made.
      const { payload } = await jwtVerify(token, JWKS, {
        issuer: "https://auth.internal",
        audience: "api.myorg.com",
      });
      // Forward the validated claims to origin via a trusted header —
      // origin trusts this because it only ever receives edge-validated
      // traffic (network policy blocks direct origin access).
      const forwarded = new Request(request);
      forwarded.headers.set("X-Verified-Sub", payload.sub);
      return fetch(forwarded);
    } catch {
      return new Response("Unauthorized", { status: 401 });
    }
  },
};
`;

// ------------------------------------------------------------------
// 5. mTLS at the edge — client certificate authentication
// ------------------------------------------------------------------
const MTLS_AT_EDGE_NOTES = `
For B2B/partner APIs (not end-user browser traffic), the edge can require
a client TLS certificate as the authentication mechanism itself — the TLS
handshake fails before any HTTP request is even processed if the client
doesn't present a certificate signed by a trusted CA. This is stronger
than a bearer token (no token to leak/replay) but requires certificate
distribution/rotation tooling on the partner's side, so it's typically
reserved for high-trust, low-cardinality integrations (a handful of
partners), not general public API auth.
`;

// ------------------------------------------------------------------
// 6. Signed URLs and cookies for private content
// ------------------------------------------------------------------
const SIGNED_URL_EXAMPLE = `
// Origin generates a time-limited, HMAC-signed URL for private content —
// the EDGE validates the signature and expiry without any origin call,
// serving the cached asset only if the signature checks out.
//   https://cdn.myorg.com/reports/q3.pdf?expires=1735689600&sig=<hmac>
//
// Edge-side pseudocode:
//   const expectedSig = hmacSha256(secret, path + expires);
//   if (sig !== expectedSig || Date.now()/1000 > expires) return 403;
//   return servedFromCache();  // signature valid — serve the cached object
`;

module.exports = {
  WAF_RULE_EXAMPLES,
  DDOS_MITIGATION_NOTES,
  BOT_MANAGEMENT_TECHNIQUES,
  EDGE_JWT_VALIDATION,
  MTLS_AT_EDGE_NOTES,
  SIGNED_URL_EXAMPLE,
};

/*
TRADING/PRODUCTION CONTEXT EXAMPLE:
A brokerage's public quote API validates JWTs at the edge and applies a
per-API-key rate limit (edge-enforced, not origin-enforced) so a client
integration bug that accidentally loops on a request can never take down
the shared origin for every other customer — the offending key gets
throttled at the edge within milliseconds of exceeding its quota, entirely
isolated from the rest of the platform's traffic.
*/
