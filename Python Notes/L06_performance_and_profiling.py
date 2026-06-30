# ============================================================
# L06: Performance and Profiling in Python
# ============================================================
# WHAT: Techniques to measure, diagnose, and improve Python
#       runtime performance and memory usage.
# WHY:  Python is often "fast enough" — but when it isn't,
#       you need systematic tools to find the bottleneck
#       before you optimize. Blind optimization is wasted effort.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    Performance work follows a strict order: MEASURE first, then
    optimize. The profiling tools below form a hierarchy:
      - cProfile  → which FUNCTION is slow (call-level)
      - line_profiler → which LINE inside that function is slow
      - memory_profiler → which line allocates the most memory
      - timeit    → accurate micro-benchmarks of small snippets

    CPython's performance characteristics differ from C/Java:
      - Function calls are expensive (~100ns overhead each)
      - Attribute lookup chains (obj.a.b.c) add up in tight loops
      - Global variable access is slower than local (bytecode differs)
      - Native extensions (NumPy, etc.) escape the GIL and use SIMD

PRODUCTION USE CASE:
    A log parser processing 500 GB/day of nginx logs was taking
    10 seconds per file. cProfile revealed 80% of time in re.match()
    — the regex was being recompiled on every call inside a loop.
    Moving to a pre-compiled pattern + numpy for aggregation cut
    runtime to 0.3 seconds. Same logic, 33x faster.

COMMON MISTAKES:
    - Optimizing before profiling (fixing the wrong thing)
    - Using time.time() for benchmarks (wall clock, not CPU time)
    - Trusting the mean — p99 latency matters more in production
    - Forgetting that cProfile itself adds overhead (~10-30% slowdown)
    - Using += to build strings in a loop (O(n²) behavior)
"""

import cProfile
import pstats
import io
import timeit
import struct
import functools
from dataclasses import dataclass


# ============================================================
# SECTION 1: cProfile — function-level profiling
# ============================================================
# cProfile is a deterministic profiler built into the stdlib.
# It intercepts every function call/return using C hooks,
# so overhead is low (~10-30%) vs pure-Python profilers.
#
# Two ways to run it:
#   1. Command line: python -m cProfile -s cumulative myscript.py
#   2. Programmatically (shown below) — useful for profiling
#      a specific section of code in production or tests.
#
# KEY COLUMNS in output:
#   ncalls   — number of times the function was called
#   tottime  — time spent IN this function (excluding callees)
#   percall  — tottime / ncalls
#   cumtime  — cumulative time IN this function AND all callees
#   percall  — cumtime / ncalls (rightmost column)
#
# RULE OF THUMB:
#   High tottime → the function itself is the bottleneck
#   High cumtime but low tottime → it calls something slow

def profile_function(func, *args, **kwargs):
    """Run func under cProfile and print top 20 lines by cumtime."""
    pr = cProfile.Profile()
    pr.enable()
    result = func(*args, **kwargs)
    pr.disable()

    # pstats.Stats wraps the profiler data for sorting/printing
    stream = io.StringIO()
    stats = pstats.Stats(pr, stream=stream)
    stats.strip_dirs()                # remove full path noise
    stats.sort_stats('cumulative')    # sort by cumulative time
    stats.print_stats(20)             # top 20 functions
    print(stream.getvalue())
    return result


# ============================================================
# SECTION 2: line_profiler — line-level profiling
# ============================================================
# cProfile tells you WHICH function is slow.
# line_profiler tells you WHICH LINE inside that function.
#
# Install: pip install line_profiler
# Usage:
#   1. Decorate the function with @profile (injected by kernprof)
#   2. Run: kernprof -l -v script.py
#   3. Output shows time per line, % of function time
#
# vs cProfile:
#   cProfile → call graph, overhead ~10-30%
#   line_profiler → line-by-line, overhead ~10x (don't use in prod)
#
# Example (would run with kernprof):
#
# @profile  # kernprof injects this — don't import it
# def slow_function(data):
#     result = []
#     for item in data:          # ← line_profiler shows time here
#         result.append(item**2) # ← and here
#     return result


# ============================================================
# SECTION 3: memory_profiler — memory usage per line
# ============================================================
# Install: pip install memory_profiler
# Usage:
#   @profile (same decorator name, different tool)
#   mprof run script.py   → records memory over time
#   mprof plot            → plot memory usage graph
#
# Key insight: Python's memory allocator retains freed memory
# (doesn't always return to OS). Seeing memory go up in a loop
# often means objects aren't being GC'd (e.g. lingering references).
#
# @profile
# def memory_heavy():
#     big_list = [0] * 10_000_000  # 80 MB spike visible here
#     return sum(big_list)


# ============================================================
# SECTION 4: timeit — accurate micro-benchmarks
# ============================================================
# time.time() is WRONG for benchmarks — it includes OS scheduling
# noise, I/O wait, etc. timeit disables garbage collection during
# the run and repeats many times to get a stable measurement.
#
# timeit.timeit(stmt, setup, number=N) → total time for N runs
# timeit.repeat(stmt, setup, number=N, repeat=R) → list of R totals
#
# ALWAYS use min() of repeat() — not mean(). The minimum represents
# the fastest the code CAN run (no OS interference). The mean is
# polluted by scheduling jitter.

def benchmark_join_vs_concat():
    """
    Demonstrate the string building anti-pattern.
    Python strings are IMMUTABLE. s += x creates a NEW string
    each time, copying all previous content → O(n²) total.
    ''.join(parts) pre-allocates once → O(n).
    """
    n = 10_000

    # WRONG: O(n²) — creates a new string object every iteration
    bad_time = timeit.timeit(
        stmt="""
s = ''
for i in range(n):
    s += str(i)
""",
        globals={'n': n},
        number=100
    )

    # CORRECT: O(n) — collect parts, join once
    good_time = timeit.timeit(
        stmt="""
parts = []
for i in range(n):
    parts.append(str(i))
s = ''.join(parts)
""",
        globals={'n': n},
        number=100
    )

    # Even better: list comprehension (bytecode is slightly more
    # efficient than explicit append loop)
    best_time = timeit.timeit(
        stmt="s = ''.join(str(i) for i in range(n))",
        globals={'n': n},
        number=100
    )

    print(f"String concat (bad): {bad_time:.3f}s")
    print(f"List + join:         {good_time:.3f}s")
    print(f"Generator + join:    {best_time:.3f}s")


# ============================================================
# SECTION 5: Why average is misleading — measure p99
# ============================================================
# In production, a service handling 1000 req/s might have:
#   mean latency: 5ms (looks great!)
#   p99 latency: 500ms (1% of users = 10 users/sec seeing 500ms)
#   p999 latency: 2000ms (timeout territory)
#
# The mean is dragged DOWN by the fast majority.
# The 99th percentile reveals tail latency — what your worst users see.
#
# Rule: SLAs are written in p99/p999, not mean.

import statistics

def analyze_latencies(samples: list[float]) -> dict:
    """Compute latency percentiles from a list of measurements (ms)."""
    sorted_s = sorted(samples)
    n = len(sorted_s)
    def pct(p):
        # Nearest-rank method
        idx = max(0, int(p / 100 * n) - 1)
        return sorted_s[idx]

    return {
        'mean':   statistics.mean(samples),
        'median': statistics.median(samples),
        'p95':    pct(95),
        'p99':    pct(99),
        'p999':   pct(99.9),
        'max':    max(samples),
    }


# ============================================================
# SECTION 6: NumPy vectorization vs Python loops
# ============================================================
# Python loops operate on boxed Python objects (each integer is a
# heap-allocated PyObject with type pointer, ref count, value).
# NumPy operates on contiguous C arrays of raw float64/int64 values
# using SIMD (SSE2/AVX) CPU instructions — no Python overhead per element.
#
# Speedup: typically 10x-100x for numerical work.
# Rule: if you're writing a for loop over numbers, ask "can NumPy do this?"

try:
    import numpy as np

    def sum_comparison():
        """Sum 1 million elements: Python loop vs NumPy."""
        data_py = list(range(1_000_000))
        data_np = np.arange(1_000_000, dtype=np.int64)

        python_time = timeit.timeit(lambda: sum(data_py), number=10)
        numpy_time  = timeit.timeit(lambda: np.sum(data_np), number=10)

        print(f"Python sum: {python_time:.3f}s")
        print(f"NumPy sum:  {numpy_time:.3f}s")
        print(f"Speedup:    {python_time / numpy_time:.0f}x")

except ImportError:
    def sum_comparison():
        print("NumPy not installed — pip install numpy")


# ============================================================
# SECTION 7: List comprehension vs for loop
# ============================================================
# List comprehensions run a tight loop in C inside the CPython
# interpreter. The equivalent for+append loop has per-iteration
# overhead from attribute lookup (list.append) and CALL_FUNCTION
# bytecode. Comprehensions are ~20-40% faster in practice.
#
# Generator expressions (parentheses instead of brackets) are lazy
# — they produce values one at a time instead of materializing the
# whole list. Use them when you only iterate once and don't need
# random access. Saves O(n) memory for large sequences.

def list_vs_generator():
    n = 100_000

    # List comprehension — eager, allocates full list in memory
    list_time = timeit.timeit(
        lambda: [x * x for x in range(n)],
        number=100
    )

    # Generator expression — lazy, O(1) memory, same speed for
    # single-pass consumption (but sum() forces evaluation)
    gen_time = timeit.timeit(
        lambda: sum(x * x for x in range(n)),
        number=100
    )

    print(f"List comprehension: {list_time:.3f}s")
    print(f"Generator + sum:    {gen_time:.3f}s")
    # Note: these are doing slightly different things (building list
    # vs computing sum), but illustrates memory/speed tradeoff.


# ============================================================
# SECTION 8: struct — binary data packing/unpacking
# ============================================================
# struct.pack/unpack converts between Python values and C binary
# format. Essential for:
#   - Parsing network protocols (TCP headers, FIX protocol, Ethernet)
#   - Reading binary file formats (WAV, PNG, ELF, custom HFT formats)
#   - Zero-copy IPC via shared memory
#
# Format strings: '>' = big-endian, '<' = little-endian, '!' = network
#   H = uint16, I = uint32, Q = uint64, f = float32, d = float64
#   c = char, s = char[] (bytes), x = padding byte

# Example: parsing a minimal custom market data tick message
# Format: [sequence:uint32][price:float64][quantity:uint32][flags:uint8]
TICK_FORMAT = '>IdIB'          # big-endian: uint32, float64, uint32, uint8
TICK_SIZE   = struct.calcsize(TICK_FORMAT)  # 17 bytes

def parse_tick(raw_bytes: bytes) -> dict:
    """Unpack a binary market data tick. ~10x faster than text parsing."""
    seq, price, qty, flags = struct.unpack(TICK_FORMAT, raw_bytes)
    return {'seq': seq, 'price': price, 'quantity': qty, 'flags': flags}

def pack_tick(seq: int, price: float, qty: int, flags: int) -> bytes:
    return struct.pack(TICK_FORMAT, seq, price, qty, flags)


# ============================================================
# SECTION 9: memoryview — zero-copy slicing
# ============================================================
# bytes/bytearray slicing creates a COPY of the data.
# memoryview wraps a buffer and provides a view into it — no copy.
# Critical when processing large binary payloads (network packets,
# mmap'd files) where copying would dominate runtime.

def memoryview_demo():
    # Simulating a 1 MB network buffer
    big_buffer = bytearray(1_000_000)
    big_buffer[:4] = b'\x00\x00\x04\x00'   # example header

    # BAD: copies 1MB just to check the first 4 bytes
    # header = big_buffer[:4]

    # GOOD: no copy — view into the same memory
    mv = memoryview(big_buffer)
    header = mv[:4]           # memoryview object, zero copy
    payload = mv[4:1000]      # also zero copy

    # Can still unpack directly from memoryview
    (length,) = struct.unpack('>I', header)
    return length


# ============================================================
# SECTION 10: __slots__ — memory optimization for many instances
# ============================================================
# By default, each Python instance carries a __dict__ (a hash map)
# to store instance attributes. __dict__ overhead: ~200-300 bytes.
# __slots__ replaces the dict with fixed C-level slots.
# Savings: 40-60% per instance when you have millions of them.
#
# COST: instances are no longer dynamic (can't add new attributes).
# USE WHEN: you create millions of small objects (particles, ticks,
# nodes in a graph, rows in a batch processor).

class PointWithDict:
    """Standard class — has __dict__, ~400 bytes per instance."""
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

class PointWithSlots:
    """Slots class — no __dict__, ~56 bytes per instance."""
    __slots__ = ('x', 'y', 'z')   # declare exactly which attrs exist

    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

# Memory comparison (approximate, measured with sys.getsizeof):
# PointWithDict:  56 (object) + 232 (dict) = ~288 bytes
# PointWithSlots: 56 bytes


# ============================================================
# SECTION 11: LOAD_FAST vs LOAD_GLOBAL — local variable speed
# ============================================================
# CPython bytecode has two variable lookup instructions:
#   LOAD_FAST  — local variable, stored in a C array, O(1) direct index
#   LOAD_GLOBAL — must look up in the global dict (hash table lookup)
#
# In a tight loop called millions of times, this difference accumulates.
# Solution: cache global/module-level names as local variables
# at the top of the function.

import math  # module-level: accessed via LOAD_GLOBAL

def slow_sqrt_loop(n):
    """Each math.sqrt call does TWO global lookups: math, then sqrt."""
    result = 0.0
    for i in range(n):
        result += math.sqrt(i)    # LOAD_GLOBAL 'math', LOAD_ATTR 'sqrt'
    return result

def fast_sqrt_loop(n):
    """Cache the function reference locally — single LOAD_FAST per call."""
    sqrt = math.sqrt              # hoist to local variable
    result = 0.0
    for i in range(n):
        result += sqrt(i)         # LOAD_FAST 'sqrt' — faster
    return result


# ============================================================
# SECTION 12: functools.lru_cache — memoization
# ============================================================
# lru_cache stores results of previous calls in an LRU dict.
# Subsequent calls with the same arguments return cached values
# without re-executing the function body.
#
# Parameters:
#   maxsize=128 — cache up to 128 unique argument sets (None = unlimited)
#   typed=True  — treat int 1 and float 1.0 as different keys
#
# WHEN IT HELPS:
#   - Pure functions (no side effects, output determined by input only)
#   - Repeated calls with same arguments (recursive algorithms, config lookup)
#   - Expensive computation (DB queries, API calls — but then use a
#     proper cache like Redis, not lru_cache which is process-local)
#
# WHEN IT HURTS:
#   - Functions called with many unique arguments (cache fills → no hits)
#   - Functions with mutable arguments (unhashable → TypeError)

@functools.lru_cache(maxsize=None)   # unlimited — good for fibonacci
def fib(n: int) -> int:
    """Classic example: without cache, O(2^n). With cache, O(n)."""
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)

# Check cache performance
# fib.cache_info() → CacheInfo(hits=N, misses=M, maxsize=None, currsize=K)


# ============================================================
# SECTION 13: Avoiding attribute lookup in tight loops
# ============================================================
# self.method in a loop → LOAD_FAST self, LOAD_ATTR method, CALL
# Caching the bound method eliminates the LOAD_ATTR each iteration.

class DataProcessor:
    def __init__(self):
        self._results = []

    def process_slow(self, items):
        """Attribute lookup on every iteration."""
        for item in items:
            self._results.append(item * 2)   # LOAD_ATTR 'append' each time

    def process_fast(self, items):
        """Cache append and _results once before the loop."""
        append = self._results.append         # hoist attribute lookup
        for item in items:
            append(item * 2)                  # LOAD_FAST only


# ============================================================
# SECTION 14: Real-world example — log parser optimization
# ============================================================
# BEFORE: 10 seconds per file
# AFTER:  0.3 seconds per file
# HOW:    1. Avoid re.compile() inside loop (was recompiling each line)
#         2. Use named groups (slightly faster extraction than indexing)
#         3. NumPy for aggregation (sum/count) instead of Python loop
#
# This is a real pattern seen in log analytics pipelines.

import re

# BAD: pattern compiled fresh on every call to the function
def parse_log_slow(lines: list[str]) -> dict:
    total_bytes = 0
    count = 0
    for line in lines:
        # re.match compiles the pattern string on EVERY call!
        m = re.match(r'(\S+) \S+ \S+ \[.*?\] ".*?" (\d+) (\d+)', line)
        if m:
            total_bytes += int(m.group(3))
            count += 1
    return {'count': count, 'total_bytes': total_bytes}

# GOOD: compile once at module level (or in __init__)
# The compiled object has a fast C-level search path.
_LOG_PATTERN = re.compile(
    r'(?P<ip>\S+) \S+ \S+ \[.*?\] ".*?" (?P<status>\d+) (?P<bytes>\d+)'
)

def parse_log_fast(lines: list[str]) -> dict:
    """
    ~33x faster version:
    - Regex compiled once (module-level constant)
    - Local alias for the match method (avoid attribute lookup)
    - NumPy for bulk aggregation if data is large enough
    """
    match = _LOG_PATTERN.match   # hoist attribute lookup out of loop
    byte_values = []
    append = byte_values.append  # hoist list.append

    for line in lines:
        m = match(line)
        if m:
            append(int(m.group('bytes')))

    if not byte_values:
        return {'count': 0, 'total_bytes': 0}

    try:
        import numpy as np
        arr = np.array(byte_values, dtype=np.int64)
        return {'count': len(arr), 'total_bytes': int(arr.sum())}
    except ImportError:
        return {'count': len(byte_values), 'total_bytes': sum(byte_values)}


# ============================================================
# QUICK REFERENCE
# ============================================================
# Tool              What it answers               Overhead
# ────────────────────────────────────────────────────────────
# cProfile          Which function is slow?       ~10-30%
# line_profiler     Which LINE in function?       ~10x
# memory_profiler   Which line allocates memory?  ~10x
# timeit            How fast is this snippet?     Accurate
# ────────────────────────────────────────────────────────────
# Optimization      Typical Speedup
# ────────────────────────────────────────────────────────────
# Compiled regex    10-50x (vs re-compiling)
# NumPy vs loop     10-100x
# __slots__         40-60% less memory
# join vs +=        O(n) vs O(n²)
# lru_cache         O(1) vs O(recompute) on cache hit
# ============================================================

if __name__ == '__main__':
    print("=== String Building Benchmark ===")
    benchmark_join_vs_concat()

    print("\n=== NumPy vs Python Sum ===")
    sum_comparison()

    print("\n=== Fibonacci with lru_cache ===")
    print(fib(35))
    print("Cache info:", fib.cache_info())

    print("\n=== Log Parser ===")
    sample_lines = [
        '127.0.0.1 - frank [10/Oct/2000:13:55:36 -0700] "GET /apache HTTP/1.0" 200 2326',
        '192.168.1.1 - - [10/Oct/2000:13:55:36 -0700] "POST /api HTTP/1.1" 200 1024',
    ]
    print(parse_log_fast(sample_lines))
