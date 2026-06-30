# ============================================================
# L03: Advanced Functions
# ============================================================
# WHAT: Closures, decorators (with/without args, stacking),
#       functools utilities, generators, send()/throw(),
#       and context managers via contextlib.
# WHY:  These are the tools that make Python code composable,
#       DRY, and lazy. Generators underpin async I/O, pipelines,
#       and streaming parsers. Decorators are the backbone of
#       frameworks (Flask routes, pytest fixtures, retry logic).
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
    Functions in Python are first-class objects — they can be
    stored, passed, returned, and decorated. Mastering closures
    and decorators lets you separate cross-cutting concerns
    (auth, logging, caching, rate-limiting) from business logic.
    Generators provide lazy evaluation, enabling processing of
    datasets that don't fit in memory.

PRODUCTION USE CASE:
    - Decorators: auth middleware, retry logic, rate limiting,
      request tracing, schema validation
    - Generators: streaming ETL pipelines, lazy file parsing,
      infinite sequences, memory-efficient data processing
    - lru_cache: memoize expensive DB/API calls
    - contextmanager: temporary config, DB transactions, file locks

COMMON MISTAKES:
    - Forgetting functools.wraps — breaks introspection
    - Mutable default arguments (the classic Python gotcha)
    - Consuming a generator twice (it's exhausted after first pass)
    - Not using send() when a generator needs to be a coroutine
    - Confusing generator functions with regular functions
"""

import time
import functools
import contextlib
from functools import lru_cache, wraps, partial, reduce
from typing import Callable, TypeVar, Any, Generator, Iterator

F = TypeVar('F', bound=Callable[..., Any])

# ============================================================
# SECTION 1: Closures
# ============================================================
# WHAT: A closure is a function that captures variables from
#       its enclosing scope. The captured variables live in a
#       "cell" object attached to the function.
# WHY:  Closures are how decorators, partial application, and
#       factory functions work. Understanding them prevents bugs.
# COMMON MISTAKE: The "late binding" gotcha in loops.

print("=== Closures ===")

def make_multiplier(factor: float) -> Callable[[float], float]:
    """Factory function — returns a closure over `factor`."""
    def multiply(value: float) -> float:
        return value * factor   # `factor` is captured from outer scope
    return multiply

double = make_multiplier(2)
triple = make_multiplier(3)
print(f"  double(5) = {double(5)}")
print(f"  triple(5) = {triple(5)}")
print(f"  closure vars: {double.__closure__[0].cell_contents}")  # 2

# COMMON MISTAKE: Loop closure late binding
# All lambdas capture the SAME variable `i`, not the value at creation.
bad_funcs  = [lambda x: x * i for i in range(5)]   # WRONG
good_funcs = [lambda x, i=i: x * i for i in range(5)]  # CORRECT (default arg)

print(f"  bad  (all same i=4): {[f(1) for f in bad_funcs]}")   # [4,4,4,4,4]
print(f"  good (captured i)  : {[f(1) for f in good_funcs]}")  # [0,1,2,3,4]

# ============================================================
# SECTION 2: Decorators — No Arguments
# ============================================================
# WHAT: A decorator is a callable that takes a function and
#       returns a replacement function. It is syntactic sugar
#       for: func = decorator(func)
# WHY:  Separates cross-cutting concerns from business logic.
# CRITICAL: Always use @functools.wraps to preserve metadata.

print("\n=== Basic Decorator ===")

def timer(func: F) -> F:
    """Decorator: log how long a function takes."""
    @wraps(func)           # copies __name__, __doc__, __annotations__
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        print(f"  [{func.__name__}] took {elapsed*1000:.2f}ms")
        return result
    return wrapper  # type: ignore

@timer
def expensive_query(user_id: int) -> dict:
    """Fetch user from database (simulated)."""
    time.sleep(0.05)
    return {"id": user_id, "name": "Alice"}

result = expensive_query(42)
print(f"  result: {result}")
print(f"  name preserved: {expensive_query.__name__}")  # 'expensive_query', not 'wrapper'

# ============================================================
# SECTION 3: Decorators WITH Arguments
# ============================================================
# WHAT: A decorator factory — a function that returns a decorator.
#       Three levels of nesting: factory → decorator → wrapper.
# WHY:  Parameterized decorators (retry(max_attempts=3),
#       rate_limit(rps=100)) are standard in production.

print("\n=== Decorator with Arguments ===")

def retry(max_attempts: int = 3, delay: float = 0.1, exceptions=(Exception,)):
    """Decorator factory: retry a function on failure."""
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    print(f"  [{func.__name__}] attempt {attempt} failed: {e}")
                    if attempt < max_attempts:
                        time.sleep(delay)
            raise last_exc  # re-raise after exhausting attempts
        return wrapper  # type: ignore
    return decorator

attempt_count = 0

@retry(max_attempts=3, delay=0.0, exceptions=(ValueError,))
def flaky_service() -> str:
    """Simulates a service that fails twice then succeeds."""
    global attempt_count
    attempt_count += 1
    if attempt_count < 3:
        raise ValueError("Service unavailable")
    return "OK"

print(f"  Result: {flaky_service()}")
attempt_count = 0  # reset for reuse

# ============================================================
# SECTION 4: Stacking Decorators
# ============================================================
# WHAT: Multiple decorators are applied bottom-up.
#       @A @B def f → f = A(B(f))
# WHY:  Compose orthogonal concerns: retry + timing + logging.

def log_call(func: F) -> F:
    @wraps(func)
    def wrapper(*args, **kwargs):
        print(f"  CALL: {func.__name__}({args}, {kwargs})")
        result = func(*args, **kwargs)
        print(f"  RETURN: {result}")
        return result
    return wrapper  # type: ignore

@timer           # applied second (outer)
@log_call        # applied first (inner)
def add(a: int, b: int) -> int:
    return a + b

print("\n=== Stacked Decorators ===")
add(3, 4)

# ============================================================
# SECTION 5: functools.lru_cache — Memoization
# ============================================================
# WHAT: Caches function results keyed by arguments.
#       Thread-safe, uses an LRU eviction strategy.
# WHY:  Eliminates redundant DB/API calls, speeds up recursion.
# COMMON MISTAKE: Caching functions with mutable arguments
#       (list, dict) — they are not hashable and will TypeError.

print("\n=== lru_cache ===")

@lru_cache(maxsize=128)
def fibonacci(n: int) -> int:
    """Exponential without cache → O(n) with cache."""
    if n < 2:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

print(f"  fib(35) = {fibonacci(35)}")
print(f"  cache info: {fibonacci.cache_info()}")
fibonacci.cache_clear()   # clear cache (e.g., between test runs)

# Production: cache DB lookup for duration of request
@lru_cache(maxsize=1024)
def get_user_permissions(user_id: int) -> frozenset:
    """Simulated DB query — cached per user_id."""
    # In production: session.query(Permission).filter_by(user_id=user_id)
    return frozenset(["read", "write"] if user_id == 1 else ["read"])

print(f"  permissions(1): {get_user_permissions(1)}")

# ============================================================
# SECTION 6: functools.partial — Partial Application
# ============================================================
# WHAT: Creates a new callable with some arguments pre-filled.
# WHY:  Adapts generic functions to specific use cases without
#       writing new wrapper functions.

print("\n=== functools.partial ===")

def send_email(to: str, subject: str, body: str, from_addr: str = "noreply@example.com"):
    print(f"  Email: {from_addr} → {to} | {subject}")

# Pre-fill `from_addr` for all notifications from this service
send_notification = partial(send_email, from_addr="notifications@myapp.com")
send_notification(to="user@example.com", subject="Your order shipped", body="...")

# Adapting int() for different bases
hex_to_int = partial(int, base=16)
bin_to_int = partial(int, base=2)
print(f"  hex 'ff'   = {hex_to_int('ff')}")
print(f"  bin '1010' = {bin_to_int('1010')}")

# ============================================================
# SECTION 7: Generators and yield
# ============================================================
# WHAT: A generator function uses `yield` to produce a sequence
#       of values lazily — one at a time, on demand.
# WHY:  Memory-efficient. A generator reading a 100GB log file
#       uses O(1) memory. A list comprehension uses O(n).
# COMMON MISTAKE: Trying to iterate a generator twice — it's
#       exhausted after the first pass.

print("\n=== Generators ===")

def read_large_file(filepath: str) -> Iterator[str]:
    """Read a file line-by-line without loading it all into memory."""
    # In production: this handles 100GB log files efficiently
    with open(filepath, 'r', errors='replace') as f:
        for line in f:
            yield line.rstrip('\n')

def csv_parser(filepath: str) -> Iterator[dict]:
    """Lazily parse CSV rows as dicts."""
    lines = read_large_file(filepath)
    headers = next(lines).split(',')    # first line is headers
    for line in lines:
        values = line.split(',')
        yield dict(zip(headers, values))

# Generator pipeline: compose generators for streaming ETL
def integers() -> Iterator[int]:
    n = 0
    while True:           # infinite generator — pull-based
        yield n
        n += 1

def take(n: int, iterable) -> list:
    return [next(iter(iterable)) for _ in range(n)]

# Demonstrate: filter and map over infinite stream
evens = (x for x in integers() if x % 2 == 0)  # generator expression
first_5_evens = [next(evens) for _ in range(5)]
print(f"  first 5 evens: {first_5_evens}")

# Generator expression vs list comprehension memory
import sys
list_comp = [x**2 for x in range(100_000)]   # eagerly computes all
gen_expr  = (x**2 for x in range(100_000))   # lazy, computes on demand
print(f"  list comp memory: {sys.getsizeof(list_comp):,} bytes")
print(f"  gen expr  memory: {sys.getsizeof(gen_expr)} bytes")

# ============================================================
# SECTION 8: Generator send() and throw()
# ============================================================
# WHAT: Generators are also coroutines. You can send values INTO
#       a generator via send() and inject exceptions via throw().
# WHY:  This is how Python's asyncio was originally built.
#       Useful for building stateful pipelines and parsers.

print("\n=== Generator send() and throw() ===")

def running_average() -> Generator[float, float, str]:
    """Coroutine: receives numbers, yields running average."""
    total = 0.0
    count = 0
    value = yield 0.0   # first yield: prime the generator
    while value is not None:
        total += value
        count += 1
        value = yield total / count    # send result, wait for next
    return f"done after {count} values"

avg = running_average()
next(avg)              # prime: advance to first yield
print(f"  avg after 10: {avg.send(10):.2f}")
print(f"  avg after 20: {avg.send(20):.2f}")
print(f"  avg after 30: {avg.send(30):.2f}")
try:
    avg.throw(GeneratorExit)  # signal shutdown
except (GeneratorExit, StopIteration):
    pass

# ============================================================
# SECTION 9: contextlib and @contextmanager
# ============================================================
# WHAT: contextlib.contextmanager turns a generator into a
#       context manager (with statement). Everything before
#       yield is __enter__, everything after is __exit__.
# WHY:  Simpler than writing a full class with __enter__/__exit__.
# PRODUCTION PATTERN: DB transactions, temporary files,
#       mock patches, timing blocks, lock acquisition.

print("\n=== contextlib.contextmanager ===")

@contextlib.contextmanager
def timer_ctx(label: str):
    """Context manager: time a block of code."""
    start = time.perf_counter()
    try:
        yield   # control passes to the `with` block here
    finally:
        # finally guarantees cleanup even if an exception occurs
        elapsed = time.perf_counter() - start
        print(f"  [{label}] {elapsed*1000:.2f}ms")

with timer_ctx("sorting 10k elements"):
    sorted(range(10_000, 0, -1))

# Simulate database transaction
@contextlib.contextmanager
def db_transaction(connection_name: str):
    """Wraps DB operations in a transaction with rollback on error."""
    print(f"  BEGIN TRANSACTION ({connection_name})")
    try:
        yield {"conn": connection_name}   # yield the connection
        print(f"  COMMIT ({connection_name})")
    except Exception as e:
        print(f"  ROLLBACK ({connection_name}) due to: {e}")
        raise

with db_transaction("primary_db") as conn:
    print(f"  Inserting via {conn['conn']}...")

# contextlib.suppress — silence specific exceptions
with contextlib.suppress(FileNotFoundError):
    open("nonexistent_file.txt")   # silently ignored

# contextlib.ExitStack — dynamic context managers
print("\n=== contextlib.ExitStack ===")
def open_multiple_files(paths: list) -> list:
    """Open multiple files and ensure all are closed."""
    with contextlib.ExitStack() as stack:
        files = []
        for path in paths:
            try:
                f = stack.enter_context(open(path, 'r'))
                files.append(f)
            except FileNotFoundError:
                pass
        # All opened files are closed when ExitStack exits
        return [f.name for f in files]

print(f"  ExitStack example demonstrated (no actual files needed)")

# ============================================================
# SECTION 10: functools.reduce
# ============================================================
# WHAT: Applies a function cumulatively to a sequence.
#       reduce(f, [a,b,c,d]) = f(f(f(a,b),c),d)
# WHY:  Useful for fold operations: product, pipeline composition.
# NOTE: Often a loop is more readable — use reduce judiciously.

print("\n=== functools.reduce ===")

# Product of a list
from operator import mul
nums = [1, 2, 3, 4, 5]
product = reduce(mul, nums, 1)
print(f"  product of {nums} = {product}")

# Compose functions: (f ∘ g ∘ h)(x) = f(g(h(x)))
def compose(*funcs: Callable) -> Callable:
    """Right-to-left function composition."""
    return reduce(lambda f, g: lambda x: f(g(x)), funcs)

normalize = compose(str.strip, str.lower, lambda s: s.replace("-", "_"))
print(f"  normalize('  Hello-World  '): {normalize('  Hello-World  ')}")
