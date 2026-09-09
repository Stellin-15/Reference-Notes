# Go — Principal Engineer Deep Dive

Companion to the existing lessons. Narrative depth, then a comprehensive
common-to-uncommon reference.


## Goroutines & the Scheduler, Beyond "Lightweight Threads"

**Beyond the lesson**: A goroutine starts with a tiny (2KB) stack that
GROWS dynamically as needed (unlike an OS thread's fixed, much larger
stack, typically 1-8MB) — this is the actual mechanical reason you can
spawn hundreds of thousands of goroutines where a comparable number of OS
threads would exhaust memory. The Go runtime's scheduler (M:N — many
goroutines mapped onto a smaller number of OS threads) multiplexes
goroutines onto threads, and critically, it's a COOPERATIVE scheduler at
the goroutine level with preemption points at function calls, channel
operations, and (since Go 1.14) even in tight loops via signal-based
async preemption — a goroutine that blocks on I/O yields its thread to
another ready goroutine automatically, which is the actual foundation of "goroutines are cheap for I/O-bound concurrency."

**Worked example**: `GOMAXPROCS` controls how many OS threads can execute
Go code SIMULTANEOUSLY (defaults to the number of CPU cores) — this is
the real lever for CPU-bound parallelism; spawning 10,000 goroutines
doing pure CPU work on a 4-core machine still only gets 4 running at once,
the rest queue — a genuinely common point of confusion for engineers
assuming goroutines alone grant unlimited parallelism.

**Interview Q&A**:
- *Q: A goroutine leak caused a service's memory to grow unbounded over days. What's the most likely cause?* A: A goroutine blocked forever waiting on a channel that will never receive a value/never be closed — unlike a memory leak from an unreferenced object (which a GC eventually reclaims), a goroutine blocked on a channel operation is never cleaned up by the garbage collector because it's still technically "live," just permanently stuck — `pprof`'s goroutine profile is the standard diagnostic tool for finding exactly this.


## Channels & the "Don't Communicate by Sharing Memory" Philosophy

**Beyond the lesson**: Go's concurrency motto ("Do not communicate by
sharing memory; instead, share memory by communicating") is a genuinely
different mental model from mutex-guarded shared state — a channel passes
OWNERSHIP of data between goroutines, so only ONE goroutine ever has
access to a given piece of data at a time, by construction, rather than by
disciplined locking convention. This doesn't mean mutexes are wrong in Go
(the standard library's `sync.Mutex` is used constantly for genuinely
shared state like a cache) — it means channels are the IDIOMATIC default
for goroutine coordination/pipeline-style data flow specifically.

**Worked example**: The `select` statement is what makes channels
compose into real concurrent control flow — waiting on MULTIPLE channels
simultaneously, proceeding with whichever becomes ready first (with an
optional `default` case for non-blocking behavior, or a `time.After`
channel for timeouts) — this single construct is the foundation of
virtually every non-trivial Go concurrency pattern (worker pools, fan-in/
fan-out, graceful shutdown via a `done` channel).

**Interview Q&A**:
- *Q: Buffered vs unbuffered channels — what's the actual behavioral difference?* A: An unbuffered channel send BLOCKS until a receiver is ready (synchronous handoff, a genuine synchronization point); a buffered channel send only blocks once the buffer is FULL, allowing the sender to proceed without an immediately-ready receiver — choosing buffer size isn't just a performance tweak, it changes the actual synchronization semantics of your program.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Standard tooling
- **`go build`/`go test`/`go vet`** — the built-in toolchain; `go vet`
  catches real bugs (suspicious `Printf` format strings, unreachable
  code) as part of normal CI, not just style.
- **`pprof`** — the standard profiler (CPU, memory, goroutine, block,
  mutex profiles) built directly into the standard library
  (`net/http/pprof` for live production profiling over HTTP) — genuinely
  one of Go's strongest built-in production-debugging capabilities compared to many other languages.
- **`golangci-lint`** — the dominant meta-linter, aggregating dozens of
  individual linters into one CI-friendly tool.
- **`race` detector** (`go test -race`, `go run -race`) — instruments the
  binary to catch data races at runtime during testing — a genuinely
  effective, commonly-used tool given Go's easy concurrency primitives make races easy to accidentally introduce.

### Frameworks & libraries
- **net/http (standard library)** — genuinely production-capable on its
  own without a framework, unlike many languages; many production Go
  services use it directly with minimal routing helpers rather than a
  full framework.
- **Gin / Echo / Fiber** — the dominant web frameworks when more routing/
  middleware convenience is wanted beyond the standard library alone.
- **gRPC-Go** — Go is one of the most common languages for gRPC service
  implementations (see API Design deep dive) — genuinely first-class
  tooling/codegen support given Go's origins at Google alongside gRPC/Protobuf itself.
- **sqlx / sqlc / ent** — database access approaches: `sqlx` (thin
  extensions over `database/sql`), `sqlc` (generates type-safe Go code
  FROM SQL queries, compile-time-checked), `ent` (a full code-generated
  ORM/graph-based entity framework) — reflecting Go's general cultural
  preference for explicit, generated code over runtime-reflection-heavy ORMs.

### Deployment & ecosystem fit
- **Single static binary compilation** — Go compiles to a single,
  statically-linked binary with no runtime dependency (no JVM, no Python
  interpreter needed on the target) — the specific reason Go became the
  dominant language for CLI tools and cloud-native infrastructure (Docker,
  Kubernetes, Terraform, Prometheus are ALL written in Go) — trivial to
  distribute and containerize with minimal image size (`FROM scratch` base images are common).
- **Cross-compilation** — `GOOS=linux GOARCH=arm64 go build` compiles a
  binary for a completely different OS/architecture with zero extra
  tooling — a genuinely underappreciated built-in capability most
  languages need substantial extra tooling to match.


## NICHE BUT REAL

- **Generics (Go 1.18+)** — a genuinely late addition (Go famously
  launched without them) — type parameters now let you write
  `func Map[T, U any](s []T, f func(T) U) []U` generically, but the Go
  team deliberately kept the feature simpler/more restrictive than
  Rust's/C++'s generics by design philosophy, worth knowing as a real, deliberate language-design tradeoff.
- **Structural typing via interfaces** — Go interfaces are satisfied
  IMPLICITLY (a type satisfies an interface just by having the right
  methods, no explicit `implements` declaration) — this enables genuinely
  decoupled design (a package can define an interface for what it NEEDS
  without the implementing type even knowing that interface exists) —
  a real, distinctive Go design philosophy versus explicit-interface languages.
- **Escape analysis** — the Go compiler decides whether a variable can be
  stack-allocated (fast, automatically freed on function return) or must
  ESCAPE to the heap (if a pointer to it outlives the function) — `go
  build -gcflags="-m"` reveals these decisions, a real tool for
  performance-sensitive code trying to minimize GC pressure by keeping allocations on the stack.
- **Context propagation (`context.Context`)** — the idiomatic mechanism
  for carrying deadlines, cancellation signals, and request-scoped values
  across API boundaries and goroutines — deeply embedded in the standard
  library's own APIs (`http.Request.Context()`), and a real, common
  interview topic around correct cancellation propagation in concurrent Go services.
