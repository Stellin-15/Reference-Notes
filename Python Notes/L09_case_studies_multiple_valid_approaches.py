"""
WHAT: Four realistic Python engineering problems, each solved with THREE
      genuinely different, individually defensible approaches drawn from
      L01-L08 -- with an explicit comparison table and reasoning for why
      each answer is valid under different constraints, in the same
      spirit as this repo's theory-domain capstones.
WHY:  "Which is the Pythonic way to do X" is often a malformed question
      once real constraints (CPU-bound vs I/O-bound, GIL contention,
      memory footprint, team skill level) enter the picture -- L01-L08
      each gave you a technique; this lesson is about choosing between
      them under pressure, and being able to name the cost of whichever
      one you pick.
LEVEL: Capstone -- read after L01-L08.

This file, like the theory-domain capstones it mirrors, is not meant to
be executed top-to-bottom as a program -- it's reference material. Before
checking each comparison table, try reconstructing it yourself using only
L01-L08's concepts.
"""

# ============================================================================
# CASE STUDY 1 — SPEEDING UP A CPU-BOUND DATA-TRANSFORMATION PIPELINE
# ============================================================================
#
# SETUP: a batch job transforms 50 million rows of nested JSON records
# (parsing, validation, reshaping) -- currently single-threaded, taking
# 40 minutes, and needs to run under 10 minutes without a rewrite in
# another language.
#
# ------------------------------------------------------------------------
# APPROACH A: `multiprocessing.Pool` to parallelize across CPU cores (L05)
# ------------------------------------------------------------------------
#   WHY VALID: this work is CPU-bound (parsing/validating/reshaping, not
#   waiting on I/O) -- per L01's GIL discussion, `threading` cannot give
#   genuine CPU parallelism for this workload (only one thread executes
#   Python bytecode at a time), while `multiprocessing` sidesteps the GIL
#   entirely by using separate OS processes, each with its own
#   interpreter, giving real multi-core speedup for exactly this kind of
#   workload.
#   COST: each worker process needs its OWN copy of whatever data it
#   operates on -- large shared read-only data structures either get
#   expensively re-pickled/copied per worker (unless explicitly shared via
#   `multiprocessing.shared_memory` or a read-only fork-inherited object
#   on POSIX systems) or duplicated in memory N times across N workers,
#   a real, sometimes disqualifying memory cost for large datasets.
#
# ------------------------------------------------------------------------
# APPROACH B: Rewrite the hot transformation logic using NumPy vectorized
# operations (L06), avoiding the per-row Python loop entirely
# ------------------------------------------------------------------------
#   WHY VALID: per L06, the real cost of pure-Python per-row loops is
#   CPython's per-bytecode-instruction interpretive overhead, paid once
#   per row -- NumPy pushes the actual loop down into compiled C code
#   operating on contiguous memory, which for operations that map onto
#   vectorized array operations can be 10-100x faster than either A or C
#   without needing multiple processes/cores at all.
#   COST: not every transformation maps cleanly onto vectorized array
#   operations -- deeply nested, conditional, per-record JSON reshaping
#   logic (this case study's actual workload) may need substantial,
#   non-trivial re-engineering to express as array operations, and some
#   logic (arbitrary branching per record) genuinely resists
#   vectorization without contorting the code into something much harder
#   to read and maintain.
#
# ------------------------------------------------------------------------
# APPROACH C: `concurrent.futures.ProcessPoolExecutor` combined with
# chunked, streaming I/O (L05, L06) -- processes work in bounded batches
# rather than loading all 50M rows into memory at once
# ------------------------------------------------------------------------
#   WHY VALID: combines A's genuine multi-core parallelism with explicit
#   memory-footprint control -- reads/processes/writes in bounded chunks,
#   avoiding both "load 50M rows into RAM at once" and A's "N full
#   in-memory copies across N workers" problems simultaneously, a real
#   engineering answer when the dataset is too large to comfortably fit
#   in memory multiple times over.
#   COST: the most implementation complexity of the three -- chunking
#   logic, worker-pool result aggregation, and (if the transformation
#   has any cross-row dependencies, e.g. deduplication) careful handling
#   of state across chunk boundaries, versus A's comparatively simple
#   "just parallelize the whole dataset" or B's "just vectorize" approach.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Speedup mechanism | Memory footprint | Engineering effort | Fits arbitrary per-row logic? |
#   |----------|----------------------|----------------------|--------------------------|------------------------------------|
#   | A: multiprocessing.Pool | True multi-core parallelism | High (N copies) | Low | Yes |
#   | B: NumPy vectorization | Eliminates interpreter overhead | Low | Medium-high (rewrite needed) | Only if vectorizable |
#   | C: chunked ProcessPoolExecutor | Multi-core + bounded memory | Bounded/tunable | Highest | Yes |
#   If the transformation logic is genuinely vectorizable, B alone often
#   beats A or C outright with the least total effort; if it isn't
#   (arbitrary branching per record, as stated in this setup), the choice
#   is between A's simplicity and C's memory discipline, decided by
#   whether the dataset actually fits in memory N times over.


# ============================================================================
# CASE STUDY 2 — DESIGNING A PLUGIN SYSTEM FOR A DATA-VALIDATION LIBRARY
# ============================================================================
#
# SETUP: a library needs to let users register custom validation rules
# (some shipped built-in, most written by end users) that get applied to
# records in a configurable order, with some rules depending on the
# results of others.
#
# ------------------------------------------------------------------------
# APPROACH A: An abstract base class (L04) that users subclass, with an
# abstract `validate()` method
# ------------------------------------------------------------------------
#   WHY VALID: `abc.ABC` (L04) gives a clear, IDE-discoverable contract
#   (the ABC's abstract methods document exactly what a user must
#   implement) and lets the library enforce at CLASS-DEFINITION time
#   (not just at call time) that required methods are actually
#   implemented -- catching a whole class of "forgot to implement
#   validate()" bugs earlier than duck typing would.
#   COST: forces every custom rule to be a class, even for genuinely
#   trivial, stateless one-line validation logic, where the ceremony of
#   defining a subclass is disproportionate to the actual logic being
#   expressed -- a real ergonomics cost for the common case of simple
#   rules.
#
# ------------------------------------------------------------------------
# APPROACH B: `typing.Protocol` (L04) -- structural typing, no required
# inheritance
# ------------------------------------------------------------------------
#   WHY VALID: per L04's Protocol discussion, users can pass ANY object
#   with a matching `validate()` method/signature, including plain
#   functions wrapped in a small adapter, existing classes not written
#   with this library in mind, or genuinely ad hoc objects -- much lower
#   friction for simple use cases, and static type checkers (mypy) can
#   still verify conformance without runtime inheritance.
#   COST: loses ABC's runtime enforcement -- a malformed plugin (wrong
#   method name, wrong signature) only fails at the point it's actually
#   CALLED, not at registration/definition time, meaning a bug can lurk
#   undetected until a specific code path exercises the malformed
#   plugin, a real debugging-experience cost relative to A's earlier
#   failure.
#
# ------------------------------------------------------------------------
# APPROACH C: A decorator-based registry (`@register_rule`, using
# closures/decorators from L03) mapping plain functions to rule names,
# with dependency declared via decorator arguments
# ------------------------------------------------------------------------
#   WHY VALID: the LOWEST-friction option for the common case -- a rule
#   author writes a plain function, decorates it, done, no class
#   ceremony at all -- and a central registry (L03's closure-based
#   pattern) can double as the natural place to encode and validate
#   inter-rule DEPENDENCY ordering (this case study's stated requirement)
#   before any rule runs, something neither A nor B directly addresses.
#   COST: rules-as-plain-functions lose the natural place to hold PER-
#   RULE STATE across calls that a class instance would provide for free
#   (L04) -- a rule needing to accumulate state across multiple records
#   (e.g. "flag if this is the third duplicate seen") needs an explicit
#   workaround (a closure-captured mutable cell, or an external state
#   dict keyed by rule name), more awkward than a stateful object would be.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Friction for simple rules | Early-failure detection | Natural fit for stateful rules | Natural fit for dependency ordering |
#   |----------|--------------------------------|------------------------------|-------------------------------------|-------------------------------------------|
#   | A: ABC subclassing | High | Best (definition-time) | Best | Medium (needs extra metadata) |
#   | B: Protocol, structural typing | Medium | Weak (call-time only) | Good | Medium |
#   | C: decorator + function registry | Lowest | Weak (call-time only) | Weakest (needs workaround) | Best (registry is the natural home) |
#   A hybrid is common in real libraries: C's decorator/registry pattern
#   as the primary user-facing API, built on top of A's ABC internally
#   for the library's OWN built-in rules where the extra rigor is cheap
#   to apply.


# ============================================================================
# CASE STUDY 3 — MANAGING SHARED CONFIGURATION STATE ACROSS A LARGE
# CODEBASE
# ============================================================================
#
# SETUP: a mid-sized application (many modules) needs access to
# configuration (API keys, feature flags, environment settings) in dozens
# of places, loaded once at startup from environment variables/a config
# file.
#
# ------------------------------------------------------------------------
# APPROACH A: A module-level singleton -- a plain module with module-
# level variables, imported wherever needed
# ------------------------------------------------------------------------
#   WHY VALID: Python modules are ALREADY singletons by import-system
#   design (a module is loaded once, cached in `sys.modules`, and every
#   subsequent `import` returns the SAME module object) -- this is the
#   simplest possible mechanism, requiring no design pattern ceremony
#   (L08) at all, just ordinary imports.
#   COST: genuinely difficult to test in isolation -- since the config
#   is process-global module state, tests that need DIFFERENT config
#   values (e.g. testing feature-flag-on vs. feature-flag-off behavior)
#   must carefully save/mutate/restore module attributes around each
#   test, a real, easy-to-get-wrong source of test pollution/ordering
#   bugs if not disciplined about it.
#
# ------------------------------------------------------------------------
# APPROACH B: An explicit Singleton design pattern class (L08) with a
# `get_instance()` classmethod
# ------------------------------------------------------------------------
#   WHY VALID: makes the "there is exactly one config object" intent
#   EXPLICIT in the code (versus A's implicit reliance on how Python's
#   import system happens to work) and centralizes lazy-initialization
#   logic (only load config on first access, not at import time) more
#   cleanly than scattering initialization code across a module's top
#   level.
#   COST: per L08's classic critique of the Singleton pattern, it's
#   frequently criticized as a thinly-disguised global variable with
#   extra ceremony -- and shares approach A's core testing difficulty
#   (a true singleton actively resists having multiple independent
#   instances for parallel test isolation) without meaningfully solving
#   that problem, just relocating it behind a class interface.
#
# ------------------------------------------------------------------------
# APPROACH C: Dependency Injection (L08) -- config is loaded once at
# startup and explicitly passed into every component/function that needs
# it, never accessed via global/singleton lookup
# ------------------------------------------------------------------------
#   WHY VALID: directly solves both A and B's testing problem -- since
#   config is an explicit PARAMETER, tests can trivially construct and
#   pass in whatever config value a specific test needs, with zero risk
#   of cross-test state pollution, and dependencies a function/class
#   actually uses are visible in its signature rather than hidden inside
#   its implementation (a real readability/maintainability win at scale,
#   per L08's DI discussion).
#   COST: "config threading" -- every function/class along a call chain
#   that eventually needs config, even if only to pass it further down,
#   must accept it as a parameter/constructor argument -- a real,
#   sometimes tedious wiring cost that grows with codebase depth, which
#   is exactly the complaint DI critics raise about deeply-layered
#   codebases without a DI framework/container to automate the wiring.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Testability | Explicitness of dependencies | Wiring/plumbing cost |
#   |----------|-----------------|------------------------------------|----------------------------|
#   | A: module-level singleton | Poor | Low (implicit, hidden) | None |
#   | B: Singleton class pattern | Poor | Medium | Low |
#   | C: dependency injection | Best | Highest | Highest (scales with call-graph depth) |
#   For a codebase where correctness-critical automated testing matters a
#   lot, C's upfront wiring cost is usually worth paying; for a smaller
#   script/tool where thorough test isolation isn't a priority, A's
#   simplicity is a perfectly reasonable, common choice.


# ============================================================================
# CASE STUDY 4 — HANDLING A HIGH-VOLUME OF CONCURRENT NETWORK REQUESTS
# ============================================================================
#
# SETUP: a service needs to make ~5,000 outbound HTTP calls to a third-
# party API (rate-limited, per-call latency ~200ms dominated by network
# wait, not local CPU work) as part of a scheduled batch job that should
# complete in under 2 minutes.
#
# ------------------------------------------------------------------------
# APPROACH A: `asyncio` with `aiohttp` (L05)
# ------------------------------------------------------------------------
#   WHY VALID: this workload is I/O-bound (waiting on network responses,
#   not doing CPU work) -- per L01/L05's GIL discussion, this is EXACTLY
#   the case where the GIL is a non-issue (a thread/task blocked on
#   network I/O releases the GIL while waiting), and `asyncio`'s single-
#   threaded event loop can have thousands of requests "in flight"
#   concurrently with minimal per-request overhead (no OS thread stack
#   allocated per request, unlike threading).
#   COST: requires the ENTIRE call chain touching these requests to be
#   written in async style (`async`/`await` throughout, L05) -- calling
#   ANY blocking, synchronous library function from within an async
#   function silently blocks the WHOLE event loop for every concurrent
#   task, a real, easy-to-introduce correctness/performance bug if the
#   codebase mixes sync and async code carelessly.
#
# ------------------------------------------------------------------------
# APPROACH B: `concurrent.futures.ThreadPoolExecutor` with the synchronous
# `requests` library (L05)
# ------------------------------------------------------------------------
#   WHY VALID: per L01's GIL discussion, threads blocked on network I/O
#   (via the synchronous `requests` library, which releases the GIL
#   during the actual blocking socket call) still achieve genuine
#   concurrency for I/O-bound work DESPITE the GIL -- and this approach
#   requires NO async rewrite of the calling code, letting existing
#   synchronous code/libraries be reused directly, a real integration-
#   simplicity win if the surrounding codebase is entirely synchronous.
#   COST: each thread carries real OS-level overhead (its own stack,
#   scheduler bookkeeping) -- comfortably scales to hundreds of
#   concurrent threads but becomes noticeably less efficient than
#   asyncio's lighter-weight tasks at the scale of many thousands of
#   truly simultaneous in-flight requests, and thread-pool sizing itself
#   becomes a real tuning knob (too few threads underutilizes available
#   concurrency; too many adds scheduling overhead).
#
# ------------------------------------------------------------------------
# APPROACH C: `multiprocessing` with a synchronous HTTP client, one
# process per worker
# ------------------------------------------------------------------------
#   WHY VALID: would work correctness-wise (each process makes its own
#   blocking calls), and sidesteps any GIL consideration entirely by
#   definition (separate interpreters) -- occasionally a defensible
#   choice if the SAME batch job also needs to do genuinely CPU-heavy
#   post-processing on each response (e.g. parsing/transforming a large
#   payload) that would benefit from true multi-core parallelism anyway,
#   combining both needs in one mechanism.
#   COST: for a PURELY I/O-bound workload with no meaningful per-response
#   CPU work, this is generally the WRONG tool -- process creation/
#   teardown overhead and inter-process communication cost are entirely
#   unnecessary expenses when neither the GIL nor CPU parallelism is
#   actually the bottleneck being addressed; this approach solves a
#   problem (CPU contention) this specific case study doesn't have.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Concurrency mechanism | Codebase integration cost | Scales to 1000s of concurrent calls? | Right tool for pure I/O-bound work? |
#   |----------|----------------------------|--------------------------------|--------------------------------------------|--------------------------------------------|
#   | A: asyncio + aiohttp | Event loop, cooperative | High (async rewrite needed) | Best | Yes |
#   | B: ThreadPoolExecutor + requests | OS threads | Low (sync code reused) | Good, less efficient at extreme scale | Yes |
#   | C: multiprocessing | OS processes | Medium | Poor (high per-worker overhead) | No -- wrong tool here |
#   For this specific case study (5,000 calls, 2-minute budget, dominated
#   by network wait), A or B both comfortably meet the requirement; the
#   deciding factor is usually whether the surrounding codebase is
#   already async (favors A) or synchronous (favors B avoiding a costly
#   rewrite), not raw throughput -- both clear the stated bar.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above. There is no executable demonstration")
    print("in this capstone lesson, matching this repo's other capstones.")
