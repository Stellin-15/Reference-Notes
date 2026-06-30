# ============================================================
# L01: Python Internals
# ============================================================
# WHAT: How CPython actually works under the hood — memory model,
#       GIL, bytecode, reference counting, object interning,
#       dunder methods, and the gc module.
# WHY:  Senior engineers diagnose performance bottlenecks,
#       memory leaks, and concurrency bugs by understanding
#       what the interpreter is doing. You cannot optimize
#       what you do not understand.
# LEVEL: Foundations → Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
    CPython is the reference implementation of Python. Your .py files
    are compiled to bytecode (.pyc), which the CPython virtual machine
    executes. Understanding this pipeline lets you reason about
    performance, identity, and memory at a systems level.

PRODUCTION USE CASE:
    - Diagnosing why two objects that "look equal" are not the same
    - Understanding why multithreaded Python does not scale on CPU
    - Preventing memory leaks in long-running services
    - Optimizing hot paths by understanding object overhead

COMMON MISTAKES:
    - Using `is` instead of `==` for value comparison
    - Assuming threads speed up CPU-bound work in CPython
    - Forgetting that circular references require the gc module
    - Not knowing that small ints and interned strings are singletons
"""

import sys
import gc
import dis
import ctypes
from typing import Any

# ============================================================
# SECTION 1: id() and Object Identity
# ============================================================
# WHAT: id() returns the memory address of an object in CPython.
# WHY:  Understanding identity vs equality is foundational.
#       Bugs caused by `is` vs `==` confusion are common in code review.

x = 1000
y = 1000

print("=== Identity vs Equality ===")
print(f"x == y  : {x == y}")    # True  — same value
print(f"x is y  : {x is y}")    # False (usually) — different objects
print(f"id(x)   : {id(x)}")
print(f"id(y)   : {id(y)}")

# Small integer interning: CPython caches integers -5 to 256.
# This is a CPython implementation detail, NOT a language guarantee.
a = 256
b = 256
print(f"\nSmall int interning (256): a is b = {a is b}")  # True

c = 257
d = 257
print(f"Large int (257): c is d = {c is d}")  # False in most contexts

# ============================================================
# SECTION 2: String Interning
# ============================================================
# WHAT: CPython interns string literals that look like identifiers
#       (alphanumeric, no spaces). You can force interning via sys.intern().
# WHY:  Interned strings allow O(1) identity comparison instead of
#       O(n) character-by-character comparison. Critical in dictionaries.
# COMMON MISTAKE: Assuming ALL strings are interned — they are not.

s1 = "hello_world"   # interned automatically (looks like identifier)
s2 = "hello_world"
print("\n=== String Interning ===")
print(f"'hello_world' is interned: {s1 is s2}")  # True

s3 = "hello world"   # NOT interned (has a space)
s4 = "hello world"
print(f"'hello world' is interned: {s3 is s4}")  # False (implementation detail)

# Force interning for performance-critical lookup keys
s5 = sys.intern("hello world")
s6 = sys.intern("hello world")
print(f"sys.intern('hello world'): {s5 is s6}")  # True

# ============================================================
# SECTION 3: Reference Counting
# ============================================================
# WHAT: Every Python object has a reference count. When it hits 0,
#       the object is deallocated immediately.
# WHY:  CPython's primary memory management strategy. Understanding
#       this lets you reason about WHEN objects are freed, which
#       matters for file handles, DB connections, locks, etc.
# COMMON MISTAKE: Holding references in module-level lists/caches
#       accidentally prevents garbage collection.

print("\n=== Reference Counting ===")

class Tracked:
    def __init__(self, name):
        self.name = name
        print(f"  [{self.name}] created")
    def __del__(self):
        # __del__ is called when refcount hits 0
        # WARNING: __del__ is unreliable — do not use for critical cleanup.
        # Use context managers (__enter__/__exit__) instead.
        print(f"  [{self.name}] destroyed")

obj = Tracked("alpha")
print(f"  refcount of obj: {sys.getrefcount(obj)}")  # +1 for getrefcount arg
ref2 = obj
print(f"  refcount after alias: {sys.getrefcount(obj)}")
del ref2
print(f"  refcount after del ref2: {sys.getrefcount(obj)}")
del obj  # refcount → 0, __del__ fires immediately

# ============================================================
# SECTION 4: Circular References and the GC Module
# ============================================================
# WHAT: Reference counting cannot detect cycles. The gc module
#       runs a cyclic garbage collector to handle this.
# WHY:  Long-running servers (web apps, background workers) can
#       accumulate memory from cycles if gc is not understood.
# PRODUCTION PATTERN: Disable gc in performance-critical services
#       (Instagram does this) and call gc.collect() manually at
#       safe points (between requests).

print("\n=== Circular References ===")

class Node:
    def __init__(self, val):
        self.val = val
        self.next = None  # will form a cycle

a = Node(1)
b = Node(2)
a.next = b
b.next = a  # cycle: a → b → a

# gc tracks these "generation 0" objects
print(f"gc enabled: {gc.isenabled()}")
print(f"gc counts (gen0, gen1, gen2): {gc.get_count()}")

# Force collection
collected = gc.collect()
print(f"Objects collected: {collected}")

# Disable gc for raw speed (Instagram engineering pattern):
# gc.disable()
# ... process request ...
# gc.collect()   # manual cleanup at request end

# ============================================================
# SECTION 5: The GIL (Global Interpreter Lock)
# ============================================================
# WHAT: A mutex in CPython that ensures only ONE thread executes
#       Python bytecode at a time.
# WHY:  Protects CPython's reference counting from race conditions.
#       Means CPU-bound multithreaded Python does NOT scale with cores.
# PRODUCTION IMPACT:
#   - I/O-bound work: threads work fine (GIL released during I/O)
#   - CPU-bound work: use multiprocessing or C extensions (NumPy releases GIL)
# COMMON MISTAKE: Writing a "parallel" CPU computation with threads
#       and wondering why it's slower than single-threaded.

import threading
import time

def cpu_bound(n):
    """Simulate CPU-bound work."""
    total = 0
    for i in range(n):
        total += i * i
    return total

print("\n=== GIL Impact Demo ===")
N = 5_000_000

start = time.perf_counter()
cpu_bound(N)
cpu_bound(N)
single_elapsed = time.perf_counter() - start

start = time.perf_counter()
t1 = threading.Thread(target=cpu_bound, args=(N,))
t2 = threading.Thread(target=cpu_bound, args=(N,))
t1.start(); t2.start()
t1.join();  t2.join()
threaded_elapsed = time.perf_counter() - start

print(f"  Sequential  : {single_elapsed:.3f}s")
print(f"  2 Threads   : {threaded_elapsed:.3f}s")
print(f"  → Threads are {'SLOWER' if threaded_elapsed > single_elapsed else 'faster'} (GIL contention)")

# ============================================================
# SECTION 6: Bytecode and dis Module
# ============================================================
# WHAT: Python source is compiled to bytecode — a stack-based
#       instruction set for the CPython VM.
# WHY:  Understanding bytecode helps you write faster code and
#       understand what "simple" Python expressions actually cost.

print("\n=== Bytecode Inspection ===")

def add(a, b):
    return a + b

print("Bytecode for add(a, b):")
dis.dis(add)

# ============================================================
# SECTION 7: __dunder__ Methods (Data Model)
# ============================================================
# WHAT: Special methods that Python calls implicitly for operators,
#       built-in functions, and protocol participation.
# WHY:  Implementing the data model makes your objects behave
#       like built-ins — they work with len(), in, for, +, [], etc.
# PRODUCTION PATTERN: ORM models, vector math classes, custom
#       containers all rely on __dunder__ methods.

print("\n=== Python Data Model ===")

class Vector:
    """2D vector with full data model support."""

    __slots__ = ('x', 'y')  # see Section 8 for slots

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y

    def __repr__(self):
        # __repr__: unambiguous developer representation
        return f"Vector({self.x!r}, {self.y!r})"

    def __str__(self):
        # __str__: human-friendly representation
        return f"({self.x}, {self.y})"

    def __add__(self, other: "Vector") -> "Vector":
        # Called by `v1 + v2`
        return Vector(self.x + other.x, self.y + other.y)

    def __mul__(self, scalar: float) -> "Vector":
        # Called by `v * 3`
        return Vector(self.x * scalar, self.y * scalar)

    def __rmul__(self, scalar: float) -> "Vector":
        # Called by `3 * v` — Python tries __mul__ first, then __rmul__
        return self.__mul__(scalar)

    def __abs__(self) -> float:
        # Called by abs(v)
        return (self.x**2 + self.y**2) ** 0.5

    def __bool__(self) -> bool:
        # Called by bool(v), `if v:`
        return bool(abs(self))

    def __eq__(self, other: Any) -> bool:
        # MUST implement __hash__ if you implement __eq__
        if not isinstance(other, Vector):
            return NotImplemented
        return self.x == other.x and self.y == other.y

    def __hash__(self):
        # Needed to use Vector as dict key or set member
        return hash((self.x, self.y))

    def __len__(self):
        # Vectors are always 2D
        return 2

    def __getitem__(self, index: int) -> float:
        # Allows: v[0], v[1], unpacking: x, y = v
        return (self.x, self.y)[index]

v1 = Vector(3, 4)
v2 = Vector(1, 2)
print(f"  v1          : {v1}")
print(f"  repr(v1)    : {repr(v1)}")
print(f"  v1 + v2     : {v1 + v2}")
print(f"  v1 * 2      : {v1 * 2}")
print(f"  3 * v1      : {3 * v1}")
print(f"  abs(v1)     : {abs(v1)}")
print(f"  bool(v1)    : {bool(v1)}")
print(f"  v1[0], v1[1]: {v1[0]}, {v1[1]}")
x, y = v1          # uses __getitem__
print(f"  unpacked    : x={x}, y={y}")

# ============================================================
# SECTION 8: __slots__ for Memory Efficiency
# ============================================================
# WHAT: By default, each instance has a __dict__ (a hash map)
#       for attribute storage. __slots__ replaces this with a
#       fixed-size array, saving 40-60% memory per instance.
# WHY:  If you create millions of objects (e.g., graph nodes,
#       time series data points), __slots__ dramatically reduces
#       memory pressure and improves cache locality.
# COMMON MISTAKE: Forgetting __slots__ in subclasses reintroduces __dict__.

import sys

class WithDict:
    def __init__(self, x, y):
        self.x = x
        self.y = y

class WithSlots:
    __slots__ = ('x', 'y')
    def __init__(self, x, y):
        self.x = x
        self.y = y

d = WithDict(1, 2)
s = WithSlots(1, 2)
print("\n=== __slots__ Memory Comparison ===")
print(f"  WithDict instance size  : {sys.getsizeof(d)} bytes (+ dict overhead)")
print(f"  WithSlots instance size : {sys.getsizeof(s)} bytes")
print(f"  WithDict has __dict__   : {hasattr(d, '__dict__')}")
print(f"  WithSlots has __dict__  : {hasattr(s, '__dict__')}")

# ============================================================
# SECTION 9: Object Memory Layout
# ============================================================
# WHAT: Every Python object has a header: ob_refcnt (reference count)
#       and ob_type (pointer to type object). This is visible via ctypes.
# WHY:  Explains why even a simple `int` costs 28 bytes in CPython.

print("\n=== Object Sizes ===")
for obj in [True, 1, 1.0, "a", b"a", [], {}, set(), ()]:
    print(f"  {type(obj).__name__:12} {repr(obj):8} → {sys.getsizeof(obj)} bytes")

# ============================================================
# SUMMARY: Key Takeaways for Senior Engineers
# ============================================================
print("\n=== Key Takeaways ===")
print("""
  1. Use `==` for value comparison, `is` only for None/True/False/singletons
  2. CPython threads do NOT parallelize CPU-bound work (GIL)
  3. Reference counting is immediate; cyclic GC is periodic
  4. __del__ is unreliable — use context managers for resource cleanup
  5. __slots__ saves 40-60% memory for high-volume object creation
  6. sys.intern() speeds up repeated string key lookups
  7. dis.dis() reveals what your code actually costs
  8. Implement the full data model to make objects first-class citizens
""")
