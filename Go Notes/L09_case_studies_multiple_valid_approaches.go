// WHAT: Four realistic Go backend-service problems, each solved with
//       THREE genuinely different, individually defensible approaches
//       drawn from L01-L08 -- with an explicit comparison table and
//       reasoning for why each answer is valid under different
//       constraints.
// WHY:  "Channels or a mutex," "goroutine-per-request or a worker pool,"
//       "how to structure errors" are all questions L01-L08 gave you
//       real tools for, not one universal answer -- this lesson is
//       about the decision process under real concurrency and
//       reliability constraints.
// LEVEL: Capstone -- read after L01-L08.
//
// This file is reference material -- not meant to compile into a
// meaningful program beyond a trivial main(). Before checking each
// comparison table, try reconstructing it yourself using only L01-L08's
// concepts.
//
// ============================================================================
// CASE STUDY 1 -- LIMITING CONCURRENT WORK WHEN PROCESSING A LARGE BATCH
// OF INCOMING JOBS
// ============================================================================
//
// SETUP: a service receives a batch of 10,000 jobs to process; each job
// involves a network call to a downstream service that can only
// comfortably handle ~50 concurrent requests.
//
// ----------------------------------------------------------------------
// APPROACH A: Launch a goroutine per job (10,000 goroutines), no
// concurrency limiting at all (L02)
// ----------------------------------------------------------------------
//   WHY VALID: per L02, goroutines are genuinely cheap (a few KB of
//   stack each, growable) -- 10,000 goroutines is not, by itself, a
//   memory problem the way 10,000 OS threads would be; simplest
//   possible code, just launch and `sync.WaitGroup` to wait for
//   completion.
//   COST: per L02, this completely ignores the STATED downstream
//   constraint (only ~50 concurrent requests comfortably handled) --
//   all 10,000 goroutines would attempt their network calls
//   near-simultaneously, almost certainly overwhelming the downstream
//   service regardless of how cheap the goroutines themselves are to
//   create; the problem here isn't goroutine cost, it's uncontrolled
//   concurrent DOWNSTREAM load.
//
// ----------------------------------------------------------------------
// APPROACH B: A buffered channel used as a semaphore, limiting
// concurrent in-flight jobs to 50 (L02, L37-equivalent concurrency
// patterns)
// ----------------------------------------------------------------------
//   WHY VALID: per L02, a buffered channel of capacity 50 is a
//   standard, idiomatic Go pattern for exactly this -- each goroutine
//   sends to the channel before starting its network call (blocking if
//   50 are already in flight) and receives/frees a slot when done,
//   directly enforcing the downstream concurrency limit while still
//   processing jobs as fast as that limit allows.
//   COST: per L02, this is a purely LOCAL concurrency limit -- it
//   correctly bounds how many concurrent calls THIS SERVICE INSTANCE
//   makes, but if the service is horizontally scaled (multiple
//   instances each independently running this same batch processor),
//   the downstream service could still see up to 50 x N_instances
//   concurrent requests, since each instance's local semaphore has no
//   visibility into other instances' concurrent load.
//
// ----------------------------------------------------------------------
// APPROACH C: B's local semaphore pattern, PLUS a shared, distributed
// rate limiter (e.g. Redis-based, echoing Distributed Systems Theory
// Notes/System Design Case Studies Notes' rate-limiting discussions) if
// this service genuinely runs as multiple instances
// ----------------------------------------------------------------------
//   WHY VALID: directly addresses B's multi-instance gap -- a shared,
//   centrally-enforced limit ensures the TOTAL concurrent load on the
//   downstream service across ALL instances stays within its stated
//   capacity, not just per-instance.
//   COST: real, added infrastructure dependency and network round-trip
//   cost per job to coordinate with the shared limiter -- genuinely
//   unnecessary complexity if the service only ever runs as a single
//   instance, where B's simpler, purely local semaphore already fully
//   solves the problem.
//
// COMPARISON TABLE (Case Study 1):
//   | Approach | Respects downstream limit | Fits multi-instance deployment | Complexity |
//   |----------|--------------------------------|---------------------------------------|----------------|
//   | A: unlimited goroutines | No | N/A (already broken) | Lowest |
//   | B: local channel semaphore | Yes, per instance | No (limit multiplies with instance count) | Low |
//   | C: B + distributed shared limiter | Yes, fleet-wide | Yes | Highest |
//   B is the correct minimum answer regardless of deployment topology;
//   C is required specifically once this service runs as more than one
//   instance and the downstream limit is a hard, fleet-wide constraint,
//   not a soft, per-instance guideline.
//
// ============================================================================
// CASE STUDY 2 -- CHOOSING BETWEEN CHANNELS AND A MUTEX FOR SHARED
// COUNTER STATE
// ============================================================================
//
// SETUP: multiple goroutines need to increment a shared request counter
// concurrently.
//
// ----------------------------------------------------------------------
// APPROACH A: A `sync.Mutex` protecting a plain `int` counter (L36-
// equivalent, L02)
// ----------------------------------------------------------------------
//   WHY VALID: for PURELY protecting a simple shared value with no
//   associated coordination/communication logic, a mutex is the most
//   direct, minimal-overhead tool -- lock, increment, unlock, exactly
//   matching the "protect shared mutable state" shape of this problem.
//   COST: requires the DISCIPLINE of remembering to lock/unlock
//   correctly around every access (though `defer mu.Unlock()`
//   mitigates much of this risk in idiomatic Go) -- a real, if modest,
//   ongoing correctness responsibility at every call site touching the
//   counter.
//
// ----------------------------------------------------------------------
// APPROACH B: A dedicated goroutine owning the counter, other
// goroutines send increment requests via a channel (the "share memory
// by communicating" idiom)
// ----------------------------------------------------------------------
//   WHY VALID: follows Go's own idiomatic philosophy ("don't communicate
//   by sharing memory; share memory by communicating") -- no explicit
//   lock/unlock discipline needed anywhere, since only ONE goroutine
//   ever touches the counter directly, eliminating the mutex-discipline
//   risk from A entirely by construction.
//   COST: genuinely more code and conceptual overhead for a task this
//   simple -- a dedicated goroutine, a channel, and a select loop for
//   what a mutex handles in three lines; for a PURE, simple counter
//   increment (no other coordination logic involved), this is real,
//   arguably unnecessary ceremony.
//
// ----------------------------------------------------------------------
// APPROACH C: `sync/atomic`'s atomic increment operations (e.g.
// `atomic.AddInt64`), no mutex or channel at all
// ----------------------------------------------------------------------
//   WHY VALID: for the SPECIFIC, narrow case of a simple numeric
//   counter (not a more complex shared data structure), atomic
//   operations provide the lowest-overhead, lock-free correctness
//   guarantee of the three -- no lock contention at all, and simpler
//   code than either A or B for this specific narrow use case.
//   COST: `sync/atomic` only cleanly covers simple scalar
//   operations (increment, compare-and-swap on a single value) -- it
//   does NOT generalize to protecting a more complex shared data
//   structure (multiple related fields that need to change together
//   atomically), where A's mutex or B's channel-owned-state pattern
//   would be necessary instead; correct only because this specific case
//   study is a single scalar counter, not a broader guarantee.
//
// COMPARISON TABLE (Case Study 2):
//   | Approach | Code simplicity for THIS case | Idiomatic Go philosophy fit | Generalizes to more complex shared state |
//   |----------|------------------------------------|------------------------------------|--------------------------------------------------|
//   | A: mutex | Simple | Acceptable, common | Yes |
//   | B: channel-owned state | More verbose | Best (canonical Go idiom) | Yes |
//   | C: sync/atomic | Simplest | N/A (different mechanism) | No (scalar-only) |
//   For a plain scalar counter specifically, C is the most direct,
//   lowest-overhead correct answer; A or B become the right tools the
//   moment the shared state grows beyond a single atomic-operation-
//   compatible scalar.
//
// ============================================================================
// CASE STUDY 3 -- ERROR HANDLING STRATEGY FOR A MULTI-STEP DATA
// PIPELINE FUNCTION
// ============================================================================
//
// SETUP: a function performs several sequential steps (fetch, validate,
// transform, save), and needs to communicate WHICH step failed and why,
// to both logs and the calling code.
//
// ----------------------------------------------------------------------
// APPROACH A: Plain `error` returns with `fmt.Errorf("step failed: %w",
// err)` wrapping at each step (L01)
// ----------------------------------------------------------------------
//   WHY VALID: per L01, this is idiomatic, standard-library-only Go
//   error handling -- `%w` wrapping preserves the underlying error for
//   `errors.Is`/`errors.As` inspection by callers, while adding
//   context at each step, with zero external dependencies.
//   COST: per L01, the error MESSAGE STRING is the primary carrier of
//   context -- programmatically distinguishing "which specific step
//   failed" beyond string inspection (e.g. for metrics/alerting broken
//   down by failure step) requires either fragile string parsing or
//   defining custom sentinel/typed errors per step, which this minimal
//   approach doesn't provide out of the box.
//
// ----------------------------------------------------------------------
// APPROACH B: Custom, typed error structs per step (e.g. `FetchError`,
// `ValidationError`, each implementing the `error` interface with
// structured fields) (L01, L07's error-wrapping discussion)
// ----------------------------------------------------------------------
//   WHY VALID: per L07, structured, typed errors let calling code (and
//   logging/metrics infrastructure) programmatically distinguish and
//   handle different failure types precisely (`errors.As(err,
//   &validationErr)`), with structured fields (e.g. which validation
//   rule failed) rather than relying on string content -- directly
//   solves A's "distinguishing failure types requires string parsing"
//   gap.
//   COST: real, additional code -- a distinct type per failure
//   category, and every call site that wants to leverage this needs to
//   use `errors.As` correctly rather than simpler string-based or
//   direct-comparison checks; for a function where callers genuinely
//   only ever care "did it fail, yes or no, log the message," this is
//   more structure than the actual need justifies.
//
// ----------------------------------------------------------------------
// APPROACH C: A, but with each step ALSO emitting a structured log
// line (not just returning an error) at the moment of failure,
// including step name and relevant context as structured fields
// (Observability Notes-adjacent), keeping the RETURNED error simple
// (A's approach) while pushing rich, structured failure detail into
// observability tooling instead of the error type system
// ----------------------------------------------------------------------
//   WHY VALID: separates two genuinely different concerns -- "what does
//   the CALLING CODE need to programmatically branch on" (often, in
//   practice, just "did it fail," which A's simple error handles fine)
//   versus "what does an ENGINEER debugging a production incident need
//   to see" (rich, structured context, which is often better served by
//   structured logs/traces than by the error return value itself,
//   since observability tooling is generally better at aggregating/
//   querying/alerting on structured logs than error types are).
//   COST: if calling code GENUINELY does need to branch programmatically
//   on the specific failure type (not just observe it after the fact
//   via logs), this approach doesn't provide that -- B's typed errors
//   remain necessary specifically for that use case; C optimizes for
//   the "humans debugging via observability tooling" case, which isn't
//   always the actual need.
//
// COMPARISON TABLE (Case Study 3):
//   | Approach | Programmatic failure-type distinction | Debugging via logs/observability | Code overhead |
//   |----------|----------------------------------------------|-----------------------------------------|--------------------|
//   | A: wrapped plain errors | Weak (string-based only) | Weak, unless logged separately | Lowest |
//   | B: typed error structs | Strong | Depends on separate logging | Medium |
//   | C: A + structured logging per step | Weak (same as A) | Strong | Low-medium |
//   Choose B if calling code genuinely needs to branch on failure type;
//   choose C if the real need is rich debugging context for humans, not
//   programmatic branching; many real systems combine B (for the few
//   failure types callers genuinely handle differently) with C's
//   structured logging (for the debugging context) rather than treating
//   them as mutually exclusive.
//
// ============================================================================
// CASE STUDY 4 -- GRACEFUL SHUTDOWN FOR AN HTTP SERVER WITH IN-FLIGHT
// REQUESTS
// ============================================================================
//
// SETUP: a service receives a SIGTERM (e.g. during a Kubernetes rolling
// deploy) and needs to stop accepting new requests while letting
// in-flight requests complete, within a bounded time.
//
// ----------------------------------------------------------------------
// APPROACH A: Exit immediately on SIGTERM, no graceful handling
// ----------------------------------------------------------------------
//   WHY VALID: simplest possible code (or rather, no code at all --
//   Go's default SIGTERM behavior is immediate process termination) --
//   arguably acceptable for a genuinely stateless, idempotent-request
//   service where an abruptly terminated in-flight request is
//   automatically, harmlessly retried by the client or a load balancer.
//   COST: per L08's graceful-shutdown discussion, this DROPS every
//   in-flight request at the moment of termination -- for any request
//   that isn't trivially safe to retry (a partially-completed multi-
//   step operation, a non-idempotent write), this causes real, direct
//   user-facing failures on every single deploy, a serious, avoidable
//   reliability cost.
//
// ----------------------------------------------------------------------
// APPROACH B: `http.Server.Shutdown()` with a bounded context timeout
// (L08)
// ----------------------------------------------------------------------
//   WHY VALID: per L08, this is Go's standard, built-in graceful-
//   shutdown mechanism -- stops accepting NEW connections immediately
//   while letting in-flight requests complete, up to a bounded timeout,
//   directly solving A's dropped-request problem with a small,
//   idiomatic amount of code.
//   COST: per L08, the bounded timeout means a genuinely LONG-RUNNING
//   in-flight request (longer than the shutdown timeout) still gets
//   forcibly terminated -- the timeout must be chosen thoughtfully
//   relative to the service's actual request-duration distribution,
//   and a too-short timeout in a deploy pipeline (the orchestrator
//   forcibly kills the process before `Shutdown()` finishes) can still
//   silently drop requests despite the graceful-shutdown code being
//   present and correct.
//
// ----------------------------------------------------------------------
// APPROACH C: B, PLUS explicit READINESS PROBE integration (L02 of
// Kubernetes Notes) -- on receiving SIGTERM, immediately fail the
// readiness probe (so the orchestrator stops routing NEW traffic to
// this pod) BEFORE calling `Shutdown()`, giving the load balancer time
// to notice and redirect traffic away, in addition to B's connection-
// draining behavior
// ----------------------------------------------------------------------
//   WHY VALID: per Kubernetes Notes L02, this closes a real, common gap
//   in B alone -- there's typically a brief window between a pod
//   receiving SIGTERM and the load balancer/service mesh actually
//   noticing and stopping new traffic routing to it; failing the
//   readiness probe FIRST gives that propagation delay a head start,
//   reducing the number of NEW requests that arrive during the
//   shutdown window in the first place, complementing B's handling of
//   requests that DO still arrive.
//   COST: requires coordinated design across the application (readiness
//   probe logic) AND the deployment platform (Kubernetes readiness
//   probe configuration, termination grace period settings) -- more
//   moving parts to get right than B's purely in-process fix, and only
//   fully effective if the orchestrator's termination grace period is
//   ALSO configured generously enough to accommodate both the probe-
//   propagation delay and B's own shutdown timeout.
//
// COMPARISON TABLE (Case Study 4):
//   | Approach | Drops in-flight requests | Reduces new requests arriving during shutdown | Coordination required |
//   |----------|-------------------------------|------------------------------------------------------|------------------------------|
//   | A: immediate exit | Yes, always | No | None |
//   | B: Shutdown() with timeout | Only if longer than timeout | No | Low (in-process only) |
//   | C: B + readiness-probe-first | Only if longer than timeout | Yes | Medium (app + orchestrator config) |
//   B is close to a mandatory baseline for any non-trivial service; C
//   is the stronger, more complete answer specifically in a Kubernetes
//   (or similar orchestrator-managed) deployment, where the
//   probe-propagation gap is a real, well-documented source of dropped
//   requests during rolling deploys even with B correctly implemented.

package main

func main() {
	// This file is reference material -- see the WHAT/WHY header and the
	// four case studies in the comments above. Nothing to execute.
}
