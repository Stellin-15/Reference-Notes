// WHAT: Four realistic edge-computing problems, each solved with THREE
//       genuinely different, individually defensible approaches drawn
//       from L01-L08 -- with an explicit comparison table and reasoning
//       for why each answer is valid under different constraints.
// WHY:  "Edge or origin," "WASM or JS," "how much AI inference belongs
//       at the edge" are all questions L01-L08 gave you real tools for,
//       not one universal answer -- this lesson is about the decision
//       process under real latency and compute-constraint tradeoffs.
// LEVEL: Capstone -- read after L01-L08.
//
// This file is reference material, not meant to run top-to-bottom.
// Before checking each comparison table, try reconstructing it yourself
// using only L01-L08's concepts.

// ============================================================================
// CASE STUDY 1 -- WHERE TO RUN PERSONALIZATION LOGIC FOR A GLOBAL
// E-COMMERCE SITE (EDGE VS. ORIGIN)
// ============================================================================
//
// SETUP: a product listing page needs to be personalized per visitor
// (e.g. reordering products based on browsing history) -- deciding
// whether this logic runs at the edge (close to the user) or at a
// centralized origin server.
//
// ----------------------------------------------------------------------
// APPROACH A: Run personalization entirely at the ORIGIN (traditional
// centralized backend)
// ----------------------------------------------------------------------
//   WHY VALID: origin servers have full, direct access to the complete
//   user history/database and can run arbitrarily complex
//   personalization logic without edge runtime constraints (L01-L02's
//   discussion of edge compute limitations -- restricted APIs, execution
//   time limits, smaller memory budgets than a full server) -- the
//   right choice when personalization logic is genuinely complex or
//   needs data too large/sensitive to replicate to the edge.
//   COST: per L01, every personalized page load pays the FULL round-
//   trip latency to a (likely distant, for many global users) origin
//   server -- directly working against the core latency benefit edge
//   computing exists to provide, especially costly for users
//   geographically far from the origin.
//
// ----------------------------------------------------------------------
// APPROACH B: Run personalization entirely at the EDGE (Cloudflare
// Workers, L02) using a locally-replicated/cached subset of user data
// ----------------------------------------------------------------------
//   WHY VALID: per L02, edge compute runs geographically close to the
//   user, directly minimizing latency for the personalization
//   computation itself -- appropriate when personalization logic is
//   simple enough to fit edge runtime constraints and the needed data
//   (e.g. a lightweight browsing-history summary) can be reasonably
//   replicated/cached at edge locations.
//   COST: per L01-L02, edge runtimes have real constraints -- limited
//   execution time, restricted API surface (not a full Node.js/Python
//   environment), and keeping edge-replicated data FRESH relative to
//   the origin's source of truth is a real, ongoing synchronization
//   challenge (L05's edge-caching discussion) -- genuinely complex
//   personalization logic or data needs may simply not fit these
//   constraints.
//
// ----------------------------------------------------------------------
// APPROACH C: A hybrid -- the origin computes and periodically pushes a
// lightweight, pre-computed "personalization profile" for each user to
// the edge (or the edge fetches it, cached with a reasonable TTL,
// L05), with the EDGE applying that lightweight profile to reorder/
// filter content in the actual request path
// ----------------------------------------------------------------------
//   WHY VALID: per L02 combined with L05's caching strategies, this
//   splits the problem correctly -- the COMPUTATIONALLY HEAVY,
//   data-intensive profile-building happens at the origin (where full
//   resources and data access exist, no edge constraints), while the
//   LATENCY-SENSITIVE, lightweight application of that profile to a
//   specific page render happens at the edge (fast, close to the
//   user) -- getting both A's computational flexibility and B's latency
//   benefit for the parts of the problem each is actually suited to.
//   COST: per L05, the edge-cached profile is, by construction,
//   somewhat STALE relative to the user's most recent activity (bound
//   by however frequently it's refreshed) -- a real, deliberate
//   freshness-for-latency tradeoff, and this architecture requires
//   building and maintaining the profile-push/fetch pipeline itself,
//   genuine additional complexity beyond either pure A or pure B.
//
// COMPARISON TABLE (Case Study 1):
//   | Approach | Latency | Personalization richness/freshness | Architectural complexity |
//   |----------|-------------|------------------------------------------|---------------------------------|
//   | A: origin only | Worst | Best (full data, full compute) | Lowest |
//   | B: edge only | Best | Limited by edge constraints | Medium |
//   | C: origin computes, edge applies | Good | Good, with bounded staleness | Highest |
//   C is the strongest answer for a genuinely global site with
//   real personalization complexity -- pure B is right only when
//   personalization needs are simple enough to fit edge constraints
//   entirely; pure A remains reasonable when personalization logic
//   is too complex/data-hungry for any edge-based approach.

// ============================================================================
// CASE STUDY 2 -- CHOOSING BETWEEN JAVASCRIPT AND WEBASSEMBLY FOR AN
// EDGE COMPUTE FUNCTION
// ============================================================================
//
// SETUP: an edge function needs to perform image resizing/transformation
// on the fly -- deciding on JS vs. WASM (L03).
//
// ----------------------------------------------------------------------
// APPROACH A: Plain JavaScript, using whatever image-processing
// capability the edge runtime's JS environment provides
// ----------------------------------------------------------------------
//   WHY VALID: per L01-L03, simplest to write and deploy if the edge
//   platform's JS environment has adequate built-in or library support
//   for the needed image operations -- no additional build/compile step
//   (compiling to WASM), fastest development iteration.
//   COST: per L03, JavaScript's performance for genuinely CPU-intensive
//   numeric/pixel-level work (image transformation is a classic example)
//   is typically meaningfully worse than a compiled language -- for a
//   latency-sensitive edge function, this performance gap can directly
//   undercut edge computing's core latency-reduction value proposition.
//
// ----------------------------------------------------------------------
// APPROACH B: WebAssembly (L03) -- compile image-processing logic
// (e.g. written in Rust or C++) to WASM, run it within the edge
// function
// ----------------------------------------------------------------------
//   WHY VALID: per L03, WASM executes near-native speed for CPU-
//   intensive work like image processing, directly closing A's
//   performance gap -- the standard answer when an edge function's
//   bottleneck is genuinely computational, not I/O-bound.
//   COST: per L03, introduces a real additional build pipeline
//   (compiling Rust/C++ to WASM) and a genuinely steeper development/
//   debugging workflow than plain JS -- WASM's sandboxed execution
//   model also has its own constraints (e.g. interacting with the host
//   environment's APIs requires explicit bindings) that add real
//   integration complexity beyond A's more direct JS-native access to
//   the platform's APIs.
//
// ----------------------------------------------------------------------
// APPROACH C: JS for the request-handling/orchestration logic (parsing
// the request, deciding what transformation is needed, interacting with
// platform APIs), calling into a WASM module SPECIFICALLY for the
// CPU-intensive pixel-transformation inner loop
// ----------------------------------------------------------------------
//   WHY VALID: per L03, this captures B's performance benefit
//   specifically where it matters (the actual CPU-bound transformation
//   work) while keeping A's simpler, more direct JS-native code for
//   everything else (request parsing, platform API calls) that doesn't
//   need WASM's performance and would otherwise add unnecessary
//   FFI-boundary complexity if pushed into WASM too.
//   COST: requires correctly identifying and drawing the boundary
//   between "goes in JS" and "goes in WASM" -- real architectural
//   design work, and crossing the JS/WASM boundary itself has some
//   overhead (data marshaling between the two environments) that,
//   for a poorly-drawn boundary (too many small back-and-forth calls),
//   could partially offset the performance benefit WASM was adopted
//   for in the first place.
//
// COMPARISON TABLE (Case Study 2):
//   | Approach | Performance for CPU-intensive work | Development complexity | Platform API integration ease |
//   |----------|------------------------------------------|------------------------------|--------------------------------------|
//   | A: plain JS | Weakest | Lowest | Best (native) |
//   | B: full WASM | Best | Highest | Weaker (needs explicit bindings) |
//   | C: JS orchestration + WASM for the hot path | Best, for the hot path specifically | Medium | Good (JS handles platform integration) |
//   C is the strongest answer for most real edge functions with a
//   MIXED workload (some I/O/orchestration, some genuine CPU-bound
//   work) -- pure B is justified when nearly the entire function is
//   CPU-bound; pure A remains fine when the actual performance
//   requirement is modest enough that JS's overhead doesn't matter.

// ============================================================================
// CASE STUDY 3 -- DEPLOYING AN AI MODEL FOR EDGE INFERENCE (L04)
// ============================================================================
//
// SETUP: a product wants low-latency AI inference (e.g. content
// moderation on user-submitted text) as close to the user as possible.
//
// ----------------------------------------------------------------------
// APPROACH A: Run the full, unmodified model at a centralized inference
// endpoint (not at the edge at all), called from the edge function
// ----------------------------------------------------------------------
//   WHY VALID: per L04, avoids ALL edge-inference constraints entirely
//   -- full model capability, no need to shrink/quantize the model to
//   fit edge resource limits, appropriate when the model is large/
//   complex and edge-deployment isn't practically feasible.
//   COST: per L04, every inference call pays a real network round-trip
//   to the centralized endpoint -- directly reintroducing the latency
//   this use case explicitly wants to avoid (LLM Core Theory Notes/LLM
//   Quantization & Inference Notes' inference-latency discussions apply
//   here too), a real tension with the stated "as close to the user as
//   possible" goal.
//
// ----------------------------------------------------------------------
// APPROACH B: Deploy a QUANTIZED, smaller version of the model directly
// at the edge (L04, connecting to LLM Quantization & Inference Notes'
// quantization techniques)
// ----------------------------------------------------------------------
//   WHY VALID: per L04, running inference directly at the edge
//   eliminates A's network round-trip entirely -- the lowest possible
//   inference latency, and quantization (shrinking the model's
//   precision/size) is specifically the standard technique for fitting
//   a model within edge compute/memory constraints.
//   COST: per L04 and LLM Quantization & Inference Notes' accuracy-vs-
//   size tradeoff discussion, quantization/shrinking a model
//   necessarily trades away SOME accuracy relative to the full model --
//   for content moderation specifically, a less accurate model means a
//   real, measurable increase in false positives/negatives, a genuine
//   product-quality cost that must be weighed against the latency
//   benefit.
//
// ----------------------------------------------------------------------
// APPROACH C: B for a FAST, first-pass filter at the edge (catching
// clearly obvious cases with the smaller model), falling back to A's
// full centralized model ONLY for genuinely ambiguous/borderline cases
// the edge model flags as uncertain
// ----------------------------------------------------------------------
//   WHY VALID: per L04, this directly balances B's latency benefit
//   against B's accuracy cost -- the common case (clearly acceptable or
//   clearly unacceptable content) gets B's fast, edge-local answer,
//   while the harder, ambiguous cases (where the smaller model's
//   accuracy loss matters most) get escalated to the full-accuracy
//   centralized model, paying A's latency cost only when it's actually
//   needed for a correct decision.
//   COST: requires the edge model to correctly SELF-ASSESS its own
//   confidence/uncertainty (to know when to escalate) -- a real,
//   nontrivial modeling requirement itself, and the WORST-CASE latency
//   (for escalated cases) is now potentially WORSE than A alone (edge
//   inference time PLUS the full round-trip to the centralized model),
//   a real cost for exactly the hardest, most ambiguous cases.
//
// COMPARISON TABLE (Case Study 3):
//   | Approach | Typical-case latency | Accuracy | Worst-case latency |
//   |----------|---------------------------|--------------|---------------------------|
//   | A: centralized only | Worst, uniformly | Best | Same as typical (uniform) |
//   | B: edge-only, quantized | Best, uniformly | Reduced | Same as typical (uniform) |
//   | C: edge first-pass + centralized escalation | Best, for most cases | Best, where it matters most | Worse than A for escalated cases |
//   C is the strongest answer when the cost of an accuracy mistake is
//   genuinely severe (content moderation is a good example) and most
//   real cases are NOT ambiguous; B alone is right when speed
//   uniformly matters more than squeezing out maximum accuracy on hard
//   cases; A alone remains appropriate when edge deployment simply
//   isn't feasible for the model in question at all.

// ============================================================================
// CASE STUDY 4 -- SECURING AN EDGE FUNCTION THAT HANDLES USER
// AUTHENTICATION TOKENS
// ============================================================================
//
// SETUP: an edge function needs to validate a user's auth token before
// routing a request onward -- deciding on the security architecture
// (L06).
//
// ----------------------------------------------------------------------
// APPROACH A: Forward every request to the origin for token validation,
// with the edge function doing no validation itself
// ----------------------------------------------------------------------
//   WHY VALID: per L06, keeps ALL authentication logic and secrets
//   (validation keys, session lookups) centralized at the origin --
//   simplest security model, no secrets/validation logic distributed
//   across many edge locations to keep in sync or secure.
//   COST: per L01/L06, this defeats much of the LATENCY benefit of
//   having an edge function in the request path at all for THIS
//   specific concern -- every request still pays the full origin round-
//   trip for the auth check, even if other parts of the request
//   handling genuinely benefit from edge execution.
//
// ----------------------------------------------------------------------
// APPROACH B: Validate stateless tokens (e.g. JWTs, Auth & Security
// Notes L02) directly AT THE EDGE, using a public key distributed to
// edge locations (no secret key material needed at the edge, only the
// PUBLIC verification key)
// ----------------------------------------------------------------------
//   WHY VALID: per L06 combined with Auth & Security Notes L02, JWT
//   signature verification only requires the PUBLIC key (for asymmetric
//   signing schemes), which is safe to distribute to every edge
//   location without exposing the actual signing secret -- the edge
//   function can validate token authenticity and claims entirely
//   locally, with zero origin round-trip for the common case.
//   COST: per Auth & Security Notes L02's JWT-revocation discussion,
//   stateless tokens can't be instantly revoked -- an edge function
//   validating purely via signature has no way to know a token was
//   revoked at the origin (e.g. a user logged out, or an admin
//   forcibly terminated access) until the token naturally expires,
//   the same fundamental tradeoff Auth & Security Notes' Case Study 1
//   covers in more depth.
//
// ----------------------------------------------------------------------
// APPROACH C: B, combined with a short-lived, edge-CACHED revocation
// list (L05's edge-caching techniques) -- the edge periodically pulls a
// small, bounded list of recently-revoked token IDs, checked as a fast
// local lookup alongside the signature verification
// ----------------------------------------------------------------------
//   WHY VALID: per L05-L06, this directly narrows B's revocation gap --
//   the edge still validates most requests entirely locally (fast), but
//   also checks against a small, frequently-refreshed revocation list,
//   catching MOST revocations within a bounded, short window rather
//   than only at natural token expiry.
//   COST: per L05, the revocation list itself has a refresh interval --
//   a REVOKED token used within that refresh window still passes edge
//   validation (a bounded, but real, gap, smaller than B's full-
//   expiry-window gap but not zero) -- and maintaining/distributing
//   this list to every edge location is real, additional
//   infrastructure beyond B's simpler pure-signature-verification
//   approach.
//
// COMPARISON TABLE (Case Study 4):
//   | Approach | Latency for the common case | Revocation responsiveness | Secrets distributed to the edge |
//   |----------|-----------------------------------|---------------------------------|----------------------------------------|
//   | A: origin validates everything | Worst | Best (instant, centralized) | None |
//   | B: edge validates via public key | Best | Worst (bound by token expiry) | Public key only (safe) |
//   | C: B + cached revocation list | Best, for the common case | Good, bounded by refresh interval | Public key + revocation list |
//   C is the strongest practical answer for most production systems --
//   A is justified specifically when instant revocation is a hard
//   security requirement that outweighs the latency cost; B alone is
//   fine when the token's natural (short) expiry already bounds
//   revocation risk to an acceptable window.

function main() {
    // This file is reference material -- see the WHAT/WHY header and the
    // four case studies above. Nothing to execute.
}
