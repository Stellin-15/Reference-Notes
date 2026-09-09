# Rust — Principal Engineer Deep Dive

Companion to the existing lessons. Narrative depth, then a comprehensive
common-to-uncommon reference.


## The Borrow Checker — What It's Actually Proving

**Beyond the lesson**: The borrow checker isn't an arbitrary restriction —
it's statically proving, at COMPILE time, the exact class of bugs that
cost C++ engineers entire careers of debugging: use-after-free, double-
free, data races, and iterator invalidation. Its core rule (at any point,
either ONE mutable reference OR any number of IMMUTABLE references to a
value, never both) is precisely the condition under which a data race is
*impossible* — if only one piece of code can mutate a value at a time, and
nothing else can even READ it while that's happening, there's no window
for two threads to race on it. This is why "fearless concurrency" is
Rust's actual, earned marketing claim, not hype: entire categories of
concurrency bugs are ruled out before the program ever runs, not caught later by a sanitizer or in production.

**Worked example**: Lifetimes (`'a`) aren't controlling HOW LONG something
lives — the programmer/scope already determines that; lifetimes are
ANNOTATIONS that let the borrow checker verify a reference doesn't
outlive the data it points to, expressed at function-signature boundaries
where the compiler can't infer it automatically. A function returning a
reference tied to one of its input lifetimes (`fn longest<'a>(x: &'a str,
y: &'a str) -> &'a str`) is telling the compiler "the returned reference's
validity is constrained by whichever input goes out of scope first" —
purely a compile-time bookkeeping annotation, zero runtime cost.

**Interview Q&A**:
- *Q: Why does Rust need both `Rc<T>` and `Arc<T>`?* A: `Rc` (Reference Counted) is single-threaded, using a plain (non-atomic) counter for speed; `Arc` (Atomically Reference Counted) uses atomic operations for the counter, safe to share across threads at a real but small performance cost — the compiler actually ENFORCES this: attempting to send an `Rc` across a thread boundary is a compile error, not a runtime race, because `Rc` doesn't implement the `Send` trait.


## Ownership & Zero-Cost Abstractions

**Beyond the lesson**: "Zero-cost abstraction" is a specific, provable
claim, not marketing fluff — Rust's iterator chains (`.map().filter().sum()`)
compile down to essentially the SAME machine code as a hand-written
for-loop, because the compiler can fully inline and optimize the
abstraction away at compile time; you get the readability of functional-
style code with NO runtime overhead versus writing the loop by hand. This
is fundamentally different from, say, Python's list comprehensions, which
still carry real interpreter overhead regardless of how they're written.

**Interview Q&A**:
- *Q: `Box<T>` vs `Rc<T>` vs `Arc<T>` — when does each matter?* A: `Box` is single ownership, heap-allocated, no counting overhead — used simply to put a value on the heap (recursive types, trait objects) with exactly ONE owner; `Rc`/`Arc` allow MULTIPLE owners via reference counting, needed whenever genuinely shared ownership (not just borrowing) is the actual requirement — reaching for `Rc`/`Arc` when a simple borrow (`&T`) would suffice is a common "coming from garbage-collected languages" over-defensive habit.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Async ecosystem
- **Tokio** — the dominant async runtime, near-universal for async Rust
  in production; provides the actual executor/reactor that `async`/`.await`
  syntax needs to run on (Rust's `async` is runtime-agnostic by design — the language provides the syntax, Tokio provides the engine).
- **async-std** — an alternative runtime with a std-library-mirroring
  API, less commonly chosen than Tokio in new production code today.
- **Hyper / Axum / Actix-web** — the dominant web frameworks; Axum (built
  on Tokio + Hyper, from the Tokio team) has become a very common modern
  default for new services; Actix-web historically led on raw benchmark
  throughput; Rocket prioritizes developer ergonomics over either.

### Systems programming use cases
- **Rust for CLI tools** — ripgrep, fd, bat, exa — a genuinely dominant
  niche where Rust CLI tools have measurably displaced older C/Go
  equivalents on raw speed + memory safety + easy cross-compilation.
- **Rust for WebAssembly** — `wasm-pack`/`wasm-bindgen` compile Rust to
  WASM for browser or edge-function use (see Full-Stack deep dive's WASM
  section) — a real, growing production use case beyond systems programming alone.
- **Rust in the Linux kernel** — an actively ongoing, real initiative
  (accepted for select kernel modules/drivers) — worth knowing exists as a
  significant vote of confidence in Rust's memory-safety guarantees even
  for the most safety-critical, historically C-only codebase in existence.

### Error handling ecosystem
- **`Result<T, E>` + `?` operator** — the core pattern (see existing
  lessons); `anyhow` (quick, flexible error handling for applications,
  less type-precise) vs `thiserror` (deriving precise, structured custom
  error enums for LIBRARIES that need callers to match on specific error
  variants) — a genuinely important, commonly-asked distinction in Rust interviews.

### Traits & generics depth
- **Trait objects (`dyn Trait`) vs generics (`impl Trait`/`<T: Trait>`)**
  — generics are monomorphized (a separate compiled copy per concrete
  type, zero runtime dispatch cost, but larger binary size); trait objects
  use dynamic dispatch via a vtable (one compiled version, smaller binary,
  small but real runtime indirection cost) — the classic "static vs
  dynamic polymorphism" tradeoff, made explicit and chosen deliberately in Rust rather than hidden by the language.


## NICHE BUT REAL

- **`unsafe` Rust, precisely** — `unsafe` doesn't disable the borrow
  checker or turn off safety checks broadly; it unlocks a SPECIFIC small
  set of operations (raw pointer dereferencing, calling FFI functions,
  implementing certain unsafe traits) that the compiler can't verify are
  safe on its own — the programmer takes on the burden of proving safety
  manually for just that scoped operation, not the whole program.
- **Pinning (`Pin<T>`)** — a real, subtle mechanism needed for
  self-referential async state machines (a generated `Future` that holds a
  reference to its own field) — genuinely one of the more conceptually
  difficult corners of async Rust, worth knowing exists even if rarely
  hand-written directly (mostly encountered when implementing custom Futures).
- **Const generics** — using compile-time constant VALUES (not just
  types) as generic parameters (`[T; N]` where N is a const generic) —
  enables fixed-size-array-based APIs that are both flexible and fully
  monomorphized/zero-cost, an area that's matured significantly in recent Rust editions.
- **The `Send`/`Sync` marker traits** — auto-implemented by the compiler
  based on a type's contents, encoding "safe to move to another thread"
  (`Send`) and "safe to share a reference across threads" (`Sync`) as
  actual TYPE-SYSTEM properties the compiler checks — this is the
  mechanism underneath the earlier `Rc`/`Arc` compile-time-enforced distinction.
