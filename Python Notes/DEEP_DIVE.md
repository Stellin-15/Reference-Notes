# Python — Principal Engineer Deep Dive

Companion to L01-L08. Narrative depth, then a comprehensive common-to-
uncommon reference.


## The GIL — What It Actually Constrains

**Beyond the lesson**: The Global Interpreter Lock ensures only ONE thread
executes Python BYTECODE at a time, per process — this is specifically
about protecting CPython's internal reference-counting from races, not a
general "Python can't do concurrency" limitation. I/O-bound threading
still works genuinely well (a thread blocked on `socket.recv()` releases
the GIL, letting another thread run) — the GIL specifically kills CPU-
BOUND parallelism within threads, which is why `multiprocessing` (separate
processes, separate GILs, separate memory) exists as the actual answer to
CPU-bound parallel work, not threading. The **PEP 703 "no-GIL" build**
(officially supported, opt-in starting Python 3.13) is a genuinely
significant, actively-in-progress change to this decades-old constraint —
worth knowing by name as the biggest structural shift in CPython's
concurrency model in its history.

**Worked example**: `asyncio` sidesteps the GIL question entirely for
I/O-bound work by using a SINGLE thread with cooperative multitasking
(same mechanical idea as Go's goroutine scheduler, see Go deep dive) — an
`async def` function yields control at each `await`, letting the event
loop run other coroutines during I/O waits, achieving massive I/O
concurrency without ever needing multiple threads or fighting the GIL at all.

**Interview Q&A**:
- *Q: You have a CPU-bound function you want to parallelize. Why won't `threading` help, and what will?* A: The GIL means only one thread executes Python bytecode at a time regardless of core count — CPU-bound work never releases the GIL to let another thread run; `multiprocessing` (or `concurrent.futures.ProcessPoolExecutor`) spawns separate OS processes each with their OWN interpreter/GIL, achieving true parallel CPU utilization at the cost of inter-process communication overhead (data must be pickled/copied between processes, unlike threads' shared memory).


## Descriptors & the Metaprogramming Layer Underneath Everyday Python

**Beyond the lesson**: `@property`, `@staticmethod`, `@classmethod`, and
even how a plain method lookup on an instance works are ALL implemented
via the DESCRIPTOR protocol (`__get__`/`__set__`/`__delete__`) — this
isn't obscure trivia, it's the actual mechanism underneath one of Python's
most-used everyday features. Understanding descriptors explains genuinely
surprising behavior: why a mutable default class attribute is SHARED
across instances (it's not instance state at all until an instance-level
`__dict__` entry shadows it), and how ORMs like SQLAlchemy/Django implement
`model.field = value` triggering validation/dirty-tracking logic behind
what looks like plain attribute assignment.

**Interview Q&A**:
- *Q: What's the actual difference between `__new__` and `__init__`?* A: `__new__` is the ACTUAL object-creation method (allocates and returns the instance, called on the CLASS); `__init__` merely initializes an already-created instance's state (returns `None`, called on the created instance) — this distinction matters concretely for implementing immutable types or singletons, where you must override `__new__` because by the time `__init__` runs, the object already exists and can't be "un-created."


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Async ecosystem beyond asyncio basics
- **uvloop** — a drop-in, libuv-based replacement for asyncio's default
  event loop, genuinely faster (2-4x on I/O-heavy benchmarks) — a common
  free production performance win for asyncio-based services.
- **anyio** — an abstraction layer working across both `asyncio` and
  `trio` (a structured-concurrency-focused alternative async library) —
  used by libraries (like Starlette/FastAPI's internals) wanting to
  support either backend without duplicating code.
- **Structured concurrency (Trio's contribution)** — a philosophy where
  concurrent tasks are strictly scoped to a parent context (a "nursery")
  that guarantees all child tasks complete or are cancelled before the
  parent scope exits — genuinely different reliability guarantees than
  asyncio's more freewheeling `create_task` model, increasingly influential
  even on asyncio's own evolving APIs.

### Performance tooling beyond cProfile
- **py-spy** — a sampling profiler that can attach to a RUNNING Python
  process (including in production) without any code changes/restart —
  genuinely valuable for diagnosing a live, already-running performance
  issue you can't easily reproduce locally.
- **Cython / Numba** — Cython compiles Python-like code (with optional
  type annotations) to C for real speedups on CPU-bound code; Numba
  JIT-compiles NUMERICAL Python functions (NumPy-heavy code especially)
  at function-call time — both are real, common answers to "Python is too
  slow for this specific hot loop" without a full rewrite in another language.
- **PyPy** — an alternative Python implementation with a JIT compiler,
  genuinely much faster for long-running CPU-bound pure-Python code, at
  the cost of C-extension compatibility gaps that make it impractical for
  many real-world dependency-heavy projects.

### Packaging & environment management
- **Poetry / uv** — modern dependency management + packaging tools; `uv`
  (from the Ruff team, written in Rust) has rapidly become notable for
  being dramatically faster than pip/Poetry at dependency resolution and
  installation, worth knowing as the newest significant tool in this space.
- **pyenv** — Python VERSION management (distinct from virtual
  environments) — lets multiple Python versions coexist on one machine,
  commonly paired with Poetry/uv for full environment isolation.
- **Ruff** — a Rust-based linter/formatter that replaced the combination
  of flake8+isort+black+more for many projects specifically due to being
  10-100x faster — now a very common modern default in Python CI pipelines.

### Type checking
- **mypy / pyright** — static type checkers for Python's optional type
  hints; `pyright` (Microsoft, powers Pylance in VS Code) is generally
  faster and increasingly common; `mypy` remains the more configurable,
  plugin-extensible original — both are now genuinely standard in
  professional Python codebases, not just an academic nicety.


## NICHE BUT REAL

- **`__slots__`** — declaring a fixed set of instance attributes instead
  of the default per-instance `__dict__` — saves real memory at scale
  (millions of instances of a small class) and slightly speeds up
  attribute access, at the cost of losing dynamic attribute assignment
  flexibility — a genuine, measurable production optimization for
  memory-dense object-heavy code.
- **Weak references (`weakref`)** — a reference to an object that does
  NOT keep it alive (doesn't increment its refcount) — used for caches
  and observer patterns where you want to reference something without
  preventing it from being garbage collected once nothing else needs it.
- **Context variables (`contextvars`)** — like `threading.local()` but
  correctly propagates through `asyncio` tasks (thread-locals don't work
  right in async code since many coroutines can share one thread) — the
  mechanism underneath things like request-ID propagation across async call chains.
- **The `__init_subclass__` and metaclass mechanisms** — hooks that run
  when a class is SUBCLASSED or CREATED, respectively — the real
  machinery underneath frameworks that "magically" register/validate
  subclasses (Django models, Pydantic models, plugin systems) without
  explicit registration calls.
