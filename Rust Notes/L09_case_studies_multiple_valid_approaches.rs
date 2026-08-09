// WHAT: Four realistic Rust systems-programming problems, each solved
//       with THREE genuinely different, individually defensible
//       approaches drawn from L01-L08 -- with an explicit comparison
//       table and reasoning for why each answer is valid under
//       different constraints.
// WHY:  "Rc<RefCell<>> or redesign the ownership," "async or threads,"
//       "unsafe or a safe-but-slower alternative" are all questions
//       L01-L08 gave you real tools for, not one universal answer --
//       this lesson is about the decision process under real
//       performance and correctness constraints.
// LEVEL: Capstone -- read after L01-L08.
//
// This file is reference material -- not meant to compile into a
// meaningful program beyond a trivial main(). Before checking each
// comparison table, try reconstructing it yourself using only L01-L08's
// concepts.
//
// ============================================================================
// CASE STUDY 1 -- MODELING A GRAPH-LIKE DATA STRUCTURE (NODES THAT
// REFERENCE EACH OTHER, POTENTIALLY CYCLICALLY)
// ============================================================================
//
// SETUP: implementing a simple graph structure where nodes can hold
// references to other nodes, and the reference structure may contain
// cycles (e.g. a doubly-linked structure, or a general graph).
//
// ----------------------------------------------------------------------
// APPROACH A: Fight it out with pure ownership/borrowing (L01) -- try
// to express the graph using plain references and lifetimes
// ----------------------------------------------------------------------
//   WHY VALID: per L01, if the graph's structure genuinely has a single,
//   clear OWNER (e.g. a tree, or a graph that can be represented with a
//   strict ownership hierarchy plus non-owning references pointing
//   "backward" or "sideways"), Rust's borrow checker CAN express this
//   correctly and it's the most idiomatic, zero-overhead approach when
//   it works.
//   COST: per L01, a graph with genuine CYCLES or multiple legitimate
//   owners of the same node fundamentally cannot be expressed with
//   plain ownership and borrowing -- the borrow checker will
//   (correctly) reject attempts to have two nodes each "own" a
//   reference to each other, since Rust's ownership model requires
//   each value to have exactly one owner; this isn't a skill issue,
//   it's the language's core safety guarantee doing its job on a data
//   shape it's not designed to express directly.
//
// ----------------------------------------------------------------------
// APPROACH B: `Rc<RefCell<T>>` (shared ownership with interior
// mutability) (L02-adjacent, standard library patterns)
// ----------------------------------------------------------------------
//   WHY VALID: directly solves A's structural limitation -- `Rc`
//   allows MULTIPLE owners of the same value (reference-counted,
//   deallocated when the last owner drops it) and `RefCell` allows
//   mutation through a shared (non-mutable) reference, checked at
//   RUNTIME instead of compile time -- this combination can express
//   genuinely cyclic, multiply-owned graph structures that plain
//   ownership cannot.
//   COST: `RefCell`'s borrow checking moves from COMPILE time to RUNTIME
//   -- a borrow-rule violation (e.g. attempting to mutably borrow a
//   `RefCell` that's already borrowed) is no longer a compile error,
//   it's a RUNTIME PANIC, giving up one of Rust's core selling points
//   (catching these bugs before the program ever runs) for this
//   specific data structure; and genuine reference CYCLES using `Rc`
//   alone cause a MEMORY LEAK (reference counts never reach zero,
//   since each node in the cycle keeps the next one alive), a real,
//   easy-to-introduce correctness gap.
//
// ----------------------------------------------------------------------
// APPROACH C: B, but using `Weak` references (the standard library's
// non-owning, cycle-breaking reference type) for the "backward" or
// "non-owning" edges in the graph, reserving `Rc` (strong references)
// only for the edges that should keep a node alive
// ----------------------------------------------------------------------
//   WHY VALID: directly fixes B's memory-leak risk -- per standard
//   Rust patterns, deliberately using `Weak` for edges that shouldn't
//   contribute to a node's reference count (e.g. a "parent" pointer in
//   a tree-like graph, where the parent already owns the child via a
//   strong `Rc`, so the child's back-reference to the parent should be
//   `Weak` to avoid a cycle) breaks the reference cycle, allowing
//   proper deallocation once genuinely unreachable.
//   COST: requires the DEVELOPER to correctly identify, upfront, which
//   edges should be strong (`Rc`) versus weak (`Weak`) based on the
//   actual intended ownership semantics of the graph -- getting this
//   analysis wrong (using `Rc` where `Weak` was needed) silently
//   reintroduces B's leak risk, and every access through a `Weak`
//   reference requires an extra `.upgrade()` call (returning an
//   `Option`, since the referenced value might have been dropped),
//   real additional code-site complexity beyond B's simpler (if leak-
//   prone) uniform `Rc` usage.
//
// COMPARISON TABLE (Case Study 1):
//   | Approach | Expresses cyclic/multi-owner structures | Compile-time safety | Memory-leak risk |
//   |----------|------------------------------------------------|---------------------------|------------------------|
//   | A: plain ownership/borrowing | No (rejected by the compiler) | N/A (doesn't apply) | N/A |
//   | B: Rc<RefCell<T>> only | Yes | Reduced (runtime borrow checks) | Real (cycles leak) |
//   | C: B + Weak for non-owning edges | Yes | Reduced (same as B) | Mitigated, if analysis is correct |
//   A is always worth attempting first -- if the structure genuinely
//   doesn't need cycles/shared ownership, it's the strongest, most
//   idiomatic answer; C is the correct, complete fix once B's approach
//   is needed at all, since using B without C's Weak-reference
//   discipline is a well-known, easy-to-hit correctness trap.
//
// ============================================================================
// CASE STUDY 2 -- CHOOSING BETWEEN THREADS AND ASYNC FOR A NETWORK
// SERVICE HANDLING MANY CONCURRENT CONNECTIONS
// ============================================================================
//
// SETUP: building a network service that needs to handle many thousands
// of concurrent, mostly-idle (waiting on I/O) client connections.
//
// ----------------------------------------------------------------------
// APPROACH A: A thread per connection (`std::thread`, L04)
// ----------------------------------------------------------------------
//   WHY VALID: per L04, genuinely simple to reason about -- each
//   connection's handling logic is ordinary, synchronous, sequential
//   code, with no `async`/`await` coloring to propagate through the
//   codebase, appropriate for a MODEST number of concurrent connections
//   where thread overhead isn't yet a real constraint.
//   COST: per L04, OS threads carry real, nontrivial per-thread
//   overhead (memory for each thread's stack, OS scheduler overhead) --
//   at "many thousands" of concurrent connections, this becomes a
//   genuine, serious resource cost, likely exhausting available memory
//   or hitting practical OS thread-count limits well before the
//   stated scale is reached.
//
// ----------------------------------------------------------------------
// APPROACH B: Async with Tokio (L05)
// ----------------------------------------------------------------------
//   WHY VALID: per L05, async tasks are dramatically lighter-weight
//   than OS threads (many thousands of concurrent tasks can be
//   multiplexed onto a small pool of OS threads) -- directly targets
//   this case study's stated scale requirement, the standard answer
//   for exactly this "many mostly-idle connections" workload shape.
//   COST: per L05, async Rust has a genuine, real learning curve
//   (`Future`s, `.await`, pinning, and the "function coloring" problem
//   where async and sync code don't mix trivially) -- meaningfully
//   more conceptual complexity than A's straightforward synchronous
//   code, and a single task that accidentally performs BLOCKING work
//   (a synchronous, long-running call) can stall the entire executor
//   thread it's running on, a real, subtle class of bug async code is
//   specifically prone to that synchronous threaded code isn't.
//
// ----------------------------------------------------------------------
// APPROACH C: A bounded thread POOL (not one thread per connection),
// with each pooled thread handling multiple connections via non-
// blocking I/O primitives directly (lower-level than B's full async
// runtime, closer to a hand-rolled event loop)
// ----------------------------------------------------------------------
//   WHY VALID: avoids A's unbounded thread-count problem while avoiding
//   B's full async-runtime adoption and its associated learning curve
//   -- a middle ground for a team that wants SOME control over
//   concurrency without fully committing to Tokio's async ecosystem and
//   conventions.
//   COST: essentially means hand-building a simplified version of what
//   Tokio (B) already provides, well-tested and optimized -- real,
//   substantial engineering effort to correctly implement non-blocking
//   I/O multiplexing by hand, with a genuine risk of reproducing bugs
//   the mature async ecosystem has already solved; rarely justified
//   compared to just adopting B directly, given how mature and widely
//   used Tokio already is.
//
// COMPARISON TABLE (Case Study 2):
//   | Approach | Scales to thousands of connections | Learning curve | Reinvents existing solved problems |
//   |----------|------------------------------------------|---------------------|-------------------------------------------|
//   | A: thread per connection | No (resource exhaustion) | Lowest | No |
//   | B: async with Tokio | Yes | Highest | No (uses mature tooling) |
//   | C: hand-rolled bounded pool + non-blocking I/O | Yes, with effort | Medium | Yes, substantially |
//   Given this case study's explicit "many thousands of concurrent
//   connections" requirement, B is the strongest, standard answer; A is
//   disqualified at this scale; C is rarely justified given how mature
//   B's ecosystem already is, for the same reason "build your own
//   database" is rarely justified when a good existing one exists.
//
// ============================================================================
// CASE STUDY 3 -- OPTIMIZING A HOT LOOP THAT'S MEASURABLY TOO SLOW
// ============================================================================
//
// SETUP: profiling reveals a specific, hot inner loop (processing a
// large buffer of numeric data) is the dominant cost in a
// performance-critical path.
//
// ----------------------------------------------------------------------
// APPROACH A: Optimize within SAFE Rust -- better data layout (e.g.
// struct-of-arrays instead of array-of-structs), iterator chains that
// the compiler can auto-vectorize, avoiding unnecessary bounds checks
// via well-structured slice patterns (L07)
// ----------------------------------------------------------------------
//   WHY VALID: per L07, safe Rust with good data layout and idiomatic
//   iterator usage often gets VERY close to hand-optimized performance,
//   since LLVM's optimizer can auto-vectorize well-structured safe code
//   effectively -- no `unsafe` risk introduced at all, the strongest
//   first approach to try.
//   COST: per L07, safe Rust's bounds checking on slice/array indexing,
//   while usually optimized away by the compiler when it can prove
//   safety, doesn't ALWAYS get eliminated in every case -- for a
//   genuinely extreme, narrowly-scoped hot loop, there can be a real,
//   measurable gap between what safe Rust achieves and the theoretical
//   hardware maximum.
//
// ----------------------------------------------------------------------
// APPROACH B: Targeted `unsafe` blocks (L07) -- e.g.
// `get_unchecked`/`get_unchecked_mut` to eliminate bounds checks in the
// specific hot loop, after confirming via profiling this is genuinely
// the bottleneck
// ----------------------------------------------------------------------
//   WHY VALID: per L07, `unsafe` gives direct access to eliminate
//   specific, PROVEN-safe-in-context overhead (e.g. bounds checks you
//   can manually verify are always satisfied by the loop's own
//   structure) -- when profiling has confirmed this is the actual
//   bottleneck, a small, carefully-reviewed `unsafe` block can close
//   the last gap A leaves.
//   COST: per L07, `unsafe` code forfeits the compiler's memory-safety
//   guarantees for that specific block -- a mistake in the manual
//   safety reasoning (e.g. the bounds condition isn't actually always
//   true) reintroduces the EXACT class of memory-safety bugs Rust is
//   designed to prevent, undetected by the compiler; every `unsafe`
//   block is a genuine, ongoing code-review and maintenance burden that
//   must be re-verified correct whenever the surrounding code changes.
//
// ----------------------------------------------------------------------
// APPROACH C: A, with SIMD via a well-tested crate/std::simd rather
// than hand-written `unsafe` (a higher-level, still largely safe
// abstraction over vectorized operations)
// ----------------------------------------------------------------------
//   WHY VALID: per L07, explicit SIMD (via a safe or thin-safe-wrapper
//   API) can capture much of B's raw performance benefit for
//   numeric/data-parallel workloads specifically, without hand-writing
//   `unsafe` bounds-check elimination -- appropriate when the hot
//   loop's actual bottleneck is genuinely about exploiting data
//   parallelism (processing multiple elements per instruction), not
//   just bounds-check overhead.
//   COST: SIMD's API (whether `std::simd` or a crate) has its own real
//   learning curve and is only a good fit for computations that
//   genuinely parallelize well across data lanes -- doesn't help for
//   hot loops whose bottleneck is something OTHER than exploitable
//   data parallelism (e.g. genuinely sequential, data-dependent
//   computation), where B's more general bounds-check-elimination
//   approach (or other targeted fixes) may be more directly applicable.
//
// COMPARISON TABLE (Case Study 3):
//   | Approach | Performance ceiling | Memory-safety risk | Fits the actual bottleneck cause |
//   |----------|--------------------------|--------------------------|-------------------------------------------|
//   | A: optimized safe Rust | Good, often close to optimal | None | General |
//   | B: targeted unsafe | Best (if correctly reasoned) | Real, requires careful review | General |
//   | C: explicit SIMD | Best, specifically for data-parallel loops | Low (safe-ish API) | Only for data-parallel-amenable loops |
//   Always try A first and re-profile -- it often closes most or all of
//   the gap; reach for C specifically when the bottleneck is genuinely
//   about exploiting data parallelism; reach for B only after A/C are
//   confirmed insufficient via actual measurement, treating unsafe as a
//   scalpel for a proven, narrow bottleneck, not a default optimization
//   tool.
//
// ============================================================================
// CASE STUDY 4 -- ERROR HANDLING STRATEGY FOR A LIBRARY CRATE VS. AN
// APPLICATION BINARY
// ============================================================================
//
// SETUP: deciding how to structure error types -- comparing the needs
// of a library crate (meant to be used by OTHER code) versus a binary
// application (the final consumer) (L03).
//
// ----------------------------------------------------------------------
// APPROACH A: Use `Box<dyn Error>` everywhere, in both the library and
// the application (L03)
// ----------------------------------------------------------------------
//   WHY VALID: per L03, the simplest possible unified approach -- any
//   error type can be boxed into a trait object, no need to define
//   custom error enums, works everywhere with minimal code.
//   COST: per L03, for a LIBRARY specifically, `Box<dyn Error>` loses
//   type information -- callers of the library CANNOT programmatically
//   match on/distinguish different specific error variants (e.g.
//   "was this a network error or a parse error") without downcasting,
//   an awkward, non-idiomatic pattern; libraries are conventionally
//   expected to expose a specific, matchable error type for their
//   callers' benefit.
//
// ----------------------------------------------------------------------
// APPROACH B: A custom error enum (implementing `std::error::Error`,
// often via the `thiserror` crate) for the LIBRARY specifically,
// `Box<dyn Error>` (or the `anyhow` crate) for the APPLICATION binary
// (L03)
// ----------------------------------------------------------------------
//   WHY VALID: per L03, this matches each error-handling need to its
//   actual consumer -- the library's custom enum gives ITS callers
//   precise, matchable error variants (good library API design,
//   letting calling code handle different failure modes differently),
//   while the application binary (which typically just needs to LOG or
//   DISPLAY an error and exit, not programmatically branch on it) uses
//   the simpler `anyhow`-style approach, avoiding unnecessary ceremony
//   at the final consumption point.
//   COST: requires understanding and applying this distinction
//   correctly -- a genuine, if well-established and widely-documented,
//   Rust ecosystem convention (the `thiserror` for libraries, `anyhow`
//   for applications split) that a developer new to Rust may not know
//   to apply without being told, and mixing the two conventions
//   inconsistently within one codebase can create confusion about
//   which pattern to follow where.
//
// ----------------------------------------------------------------------
// APPROACH C: B, but with the library's error enum ALSO implementing
// `#[non_exhaustive]` (allowing new error variants to be added in
// future library versions without it being a breaking change for
// existing callers' `match` statements)
// ----------------------------------------------------------------------
//   WHY VALID: per L03's API-evolution concerns, this directly
//   addresses a real, forward-looking problem with B alone -- a plain
//   enum's variants are part of its PUBLIC API; adding a new variant
//   later is technically a breaking change for any caller who
//   exhaustively `match`es on it without a catch-all arm.
//   `#[non_exhaustive]` forces callers to include a wildcard arm,
//   preserving the library's ability to add new error variants in
//   future MINOR versions without breaking existing callers' code.
//   COST: forces every consumer of the library's error enum to include
//   a wildcard `_` match arm, even when they'd otherwise want to
//   exhaustively handle every currently-known variant -- a real, if
//   modest, ergonomic cost for callers, accepted specifically in
//   exchange for the library's own future API-evolution flexibility.
//
// COMPARISON TABLE (Case Study 4):
//   | Approach | Caller error-matching precision | Fits library vs. application roles | Future API-evolution flexibility |
//   |----------|--------------------------------------|-------------------------------------------|-------------------------------------------|
//   | A: Box<dyn Error> everywhere | Poor | No distinction made | N/A |
//   | B: custom enum for library, anyhow for app | Best, for the library's callers | Yes, matches Rust ecosystem convention | Poor (adding variants is breaking) |
//   | C: B + #[non_exhaustive] on the library enum | Best | Yes | Good |
//   C is the strongest answer for a library crate genuinely intended
//   for external use and expected to evolve over multiple versions; B
//   without C's non_exhaustive marker is fine for a library that's
//   either internal-only or not expected to add new error variants
//   after its initial design.

fn main() {
    // This file is reference material -- see the WHAT/WHY header and the
    // four case studies in the comments above. Nothing to execute.
}
