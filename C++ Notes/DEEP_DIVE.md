# C++ — Principal Engineer Deep Dive

Companion to L01-L65 (HFT/systems-programming track). Narrative depth on
the topics that separate senior from principal-level C++, then a
comprehensive common-to-uncommon reference.


## Move Semantics & Rule of 5, Beyond the Basics

**Beyond the lesson**: Move semantics exist to solve one specific,
expensive problem — copying a large object (a `vector<Order>` with
millions of entries) when the SOURCE is about to be destroyed anyway is
pure waste; a move just steals the source's internal pointer and
nulls it out, O(1) regardless of size. The subtlety most engineers miss:
`std::move` doesn't actually MOVE anything — it's just a cast to an rvalue
reference, TELLING the compiler "you may treat this as movable" — the
actual work happens in the move constructor/assignment operator you
defined (or the compiler generated). Forgetting `noexcept` on a move
constructor is a real, subtle production bug: `std::vector` will fall back
to COPYING elements during a reallocation if the move constructor isn't
marked `noexcept` (because it can't guarantee exception safety otherwise),
silently defeating the entire performance point of having written one.

**Worked example**: Perfect forwarding (`template<typename T> void
wrapper(T&& arg) { target(std::forward<T>(arg)); }`) exists because a
universal reference (`T&&` in a template context) can bind to EITHER an
lvalue or rvalue, but simply passing `arg` onward would always pass it as
an lvalue (function parameters are always lvalues inside the function body,
regardless of how they were called) — `std::forward` restores the
original value category, letting a generic wrapper function forward a
move exactly as efficiently as calling the target directly.

**Interview Q&A**:
- *Q: Why might `std::move`-ing a `const` object silently do nothing useful?* A: A `const T&&` bound via `std::move` still can't be moved from — the move constructor's signature (`T(T&&)`) requires a non-const rvalue reference; the compiler falls back to the COPY constructor for a const object, silently defeating the move — `std::move` on a const object compiles fine but doesn't do what the name implies.


## Memory Ordering & Lock-Free Programming, In Depth

**Beyond the lesson**: `std::atomic` operations take a memory ORDER
parameter (`memory_order_relaxed`, `acquire`, `release`, `seq_cst`) that
most tutorials gloss over as "just use the default" — but the default
(`seq_cst`, sequentially consistent) is also the SLOWEST, because it
forces a full memory fence on every operation. In a genuinely
latency-critical hot path (an HFT order book), `memory_order_acquire`/
`memory_order_release` pairs let you get away with a much cheaper fence
ONLY at the specific points where cross-thread visibility actually
matters, while `memory_order_relaxed` (no ordering guarantee at all, just
atomicity) is correct for counters where you only care about the final
value, never the ordering relative to other operations.

**Worked example**: The classic SPSC (Single-Producer-Single-Consumer)
lock-free queue pattern — the producer writes data, THEN atomically stores
the new write-index with `memory_order_release`; the consumer loads the
write-index with `memory_order_acquire` and only THEN reads the data —
this acquire/release PAIR guarantees the consumer never sees the updated
index before the actual data write is visible to it, without needing a
full mutex lock at all.

**Interview Q&A**:
- *Q: Why is `memory_order_relaxed` dangerous for a "ready" flag guarding access to other data?* A: Relaxed ordering guarantees atomicity of that ONE variable but makes no promise about the VISIBILITY ORDER of other memory operations relative to it — another thread could observe the flag as `true` while still seeing STALE (pre-write) values of the data it's supposed to guard, exactly the race condition acquire/release semantics exist to prevent.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Modern C++ standards, what actually changed
- **C++11** — move semantics, lambdas, `auto`, smart pointers — the single
  biggest modernization leap; pre-C++11 code is a genuinely different
  language in practice.
- **C++14/17** — structured bindings, `std::optional`/`variant`, fold
  expressions, `if constexpr` — incremental but real quality-of-life and
  compile-time-programming improvements.
- **C++20** — Concepts (constrain templates with readable, checkable
  requirements instead of cryptic SFINAE errors), Ranges (composable,
  lazy view-based algorithms), Coroutines (`co_await`/`co_yield` for
  async code without callback hell) — a genuinely significant modernization wave.
- **C++23** — `std::expected` (a `Result<T, E>`-style error type without
  exceptions), `std::mdspan` (multi-dimensional array views) — incremental
  but real for error-handling and numerical code respectively.

### Build systems & tooling
- **CMake** — the near-universal cross-platform build system for modern
  C++ projects; understanding `target_link_libraries`/generator
  expressions is table-stakes for any real C++ role.
- **Conan / vcpkg** — the dominant C++ package managers, solving the
  historically painful "how do I even get a dependency" problem that C++
  famously lacked a good answer to for decades.
- **Bazel** — used at larger scale (see CI/CD deep dive's monorepo
  section), especially in companies running C++ alongside other languages in one build graph.

### Profiling & debugging
- **perf** (Linux) — sampling profiler, the standard first tool for "where
  is time actually going" in a C++ hot path.
- **Valgrind** (`memcheck`) — catches memory errors (use-after-free,
  uninitialized reads) at real but significant runtime cost — usually run
  in CI/dedicated debugging sessions, not production.
- **AddressSanitizer (ASan) / UndefinedBehaviorSanitizer (UBSan)** —
  compile-time-instrumented sanitizers, much faster than Valgrind, the
  modern default for catching memory bugs and undefined behavior in CI.
- **ThreadSanitizer (TSan)** — specifically for detecting data races in
  multithreaded code — genuinely difficult to catch any other way given
  races are often non-deterministic/timing-dependent.

### Concurrency primitives beyond mutex/atomic
- **`std::jthread`** (C++20) — a `std::thread` that automatically joins
  on destruction and supports cooperative cancellation via
  `std::stop_token` — fixes `std::thread`'s historically error-prone
  "forgot to join, program terminates" footgun.
- **Coroutines for async I/O** — C++20 coroutines let async code read
  like sequential code (`co_await` a future) without manual callback
  chaining — increasingly used in modern async networking libraries.


## NICHE BUT REAL

- **Undefined Behavior (UB) as a compiler OPTIMIZATION license, not just a
  bug** — signed integer overflow, dereferencing a null pointer, and
  similar UB aren't just "risky" — the compiler is LEGALLY ALLOWED to
  assume UB never happens and optimize accordingly, sometimes eliminating
  code you expected to run (an "impossible" branch based on UB can be
  deleted entirely) — a genuinely surprising, real source of "why did this
  code that looked fine start crashing after a compiler upgrade" incidents.
- **Placement new & custom allocators** — constructing an object at a
  SPECIFIC, pre-allocated memory address (`new (ptr) T(args)`) — the
  mechanism underneath memory pools/arenas used to avoid malloc/free
  overhead entirely in latency-critical hot paths (see the HFT-focused
  L44 lesson for the concrete memory-pool pattern).
- **Cache-line false sharing** — two unrelated atomic variables that
  happen to share a CPU cache line can cause massive, invisible
  performance degradation when accessed by different threads on different
  cores (every write invalidates the other core's cache line) — fixed by
  explicit padding to align each variable to its own cache line, a real
  and often-missed multithreaded-performance bug class.
- **Compile-time reflection (C++26 direction)** and **`std::mdspan`/
  SIMD-friendly numerical code (C++23's `std::simd` proposal work)** —
  worth knowing the LANGUAGE ITSELF is still actively evolving specifically
  toward better compile-time metaprogramming and numerical/HPC ergonomics,
  a genuinely live area even in a "mature" language.
