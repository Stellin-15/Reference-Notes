# ============================================================
# L02: Data Structures and Complexity
# ============================================================
# WHAT: Internals of Python's built-in data structures — how
#       list, dict, set, deque, heapq, defaultdict, Counter,
#       and OrderedDict are implemented, their Big-O costs,
#       and when to use each in production.
# WHY:  The #1 cause of algorithmic slowness in Python services
#       is choosing the wrong data structure. Knowing internals
#       lets you reason about cache behavior, memory, and speed.
# LEVEL: Foundations → Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
    Python's built-ins are implemented in C and highly optimized,
    but they have fundamentally different performance profiles.
    Choosing a list when you need a deque, or a list when you
    need a set, can turn an O(n) system into an O(n²) disaster
    at scale.

PRODUCTION USE CASE:
    - API rate limiters: deque with maxlen (sliding window)
    - Leaderboards: heapq (top-K queries)
    - Cache with eviction order: OrderedDict (LRU cache)
    - Word frequency / analytics: Counter
    - Graph adjacency: defaultdict(set)
    - Fast membership tests on millions of items: set / frozenset

COMMON MISTAKES:
    - Using list.insert(0, x) or list.pop(0) — both are O(n)
    - Using `x in list` for repeated lookups — O(n) per check
    - Assuming dict preserves insertion order in Python < 3.7
    - Using + to concatenate lists in a loop — O(n²) total
    - Not knowing that dict.get() avoids KeyError cleanly
"""

import sys
import time
import heapq
from collections import deque, defaultdict, Counter, OrderedDict
from typing import TypeVar, Iterator

T = TypeVar('T')

# ============================================================
# SECTION 1: list — Dynamic Array
# ============================================================
# WHAT: list is a dynamic array (like C++ vector). It stores a
#       contiguous block of pointers to Python objects.
# GROWTH: When capacity is exceeded, CPython over-allocates by
#         ~12.5% to amortize the cost of resizing.
#
# Big-O summary:
#   Access by index  : O(1)
#   Append           : O(1) amortized  ← use this
#   Pop from end     : O(1)
#   Insert at index i: O(n)            ← shifts all elements right
#   Delete at index i: O(n)
#   Search (x in L) : O(n)
#   Sort             : O(n log n)  — Timsort, stable

print("=== list: Dynamic Array ===")

# Demonstrating over-allocation
lst = []
prev_allocated = 0
print("  n    allocated  (shows over-allocation growth)")
for i in range(20):
    lst.append(i)
    allocated = lst.__sizeof__() // 8  # rough pointer count
    if allocated != prev_allocated:
        print(f"  {i+1:3d}  {allocated} slots")
        prev_allocated = allocated

# PRODUCTION PATTERN: Building large lists — use append or list comp,
# NEVER use + concatenation in a loop (quadratic memory copies).
n = 100_000

start = time.perf_counter()
result = []
for i in range(n):
    result.append(i)          # O(1) amortized each
concat_time = time.perf_counter() - start

print(f"\n  append loop   : {concat_time*1000:.2f}ms for {n} items")

# List comprehension is faster than append loop (built in C)
start = time.perf_counter()
result = [i for i in range(n)]
lc_time = time.perf_counter() - start
print(f"  list comp     : {lc_time*1000:.2f}ms for {n} items")

# ============================================================
# SECTION 2: dict — Hash Map with Open Addressing
# ============================================================
# WHAT: dict uses a hash table. Since Python 3.6+ dicts are compact
#       and ordered by insertion order (CPython impl detail),
#       guaranteed in language spec from Python 3.7+.
#
# Big-O summary:
#   Get/Set/Delete   : O(1) average, O(n) worst (hash collision)
#   Iteration        : O(n)
#   Membership (in)  : O(1) average
#
# INTERNALS: CPython dict uses a "split table" for instance __dict__
# and a "combined table" for general dicts. Hash collisions are
# resolved via open addressing with pseudo-random probing.
#
# COMMON MISTAKE: Mutating a dict while iterating over it raises
# RuntimeError. Use list(d.items()) to snapshot first.

print("\n=== dict: Hash Map ===")

# dict.get() with default avoids KeyError
inventory = {"apples": 5, "bananas": 3}
count = inventory.get("oranges", 0)   # returns 0, no exception
print(f"  oranges in inventory: {count}")

# setdefault — get or set in one atomic step
inventory.setdefault("grapes", 10)
print(f"  after setdefault: {inventory}")

# Merging dicts (Python 3.9+)
defaults = {"timeout": 30, "retries": 3}
overrides = {"timeout": 60}
config = defaults | overrides          # PEP 584 merge operator
print(f"  merged config: {config}")

# Avoid mutation during iteration
d = {"a": 1, "b": 2, "c": 3}
to_delete = [k for k, v in d.items() if v < 2]  # collect first
for k in to_delete:
    del d[k]
print(f"  after filtered delete: {d}")

# dict memory size
d_small = {i: i for i in range(10)}
d_large = {i: i for i in range(1000)}
print(f"  dict with 10 keys  : {sys.getsizeof(d_small)} bytes")
print(f"  dict with 1000 keys: {sys.getsizeof(d_large)} bytes")

# ============================================================
# SECTION 3: set — Hash Set
# ============================================================
# WHAT: An unordered collection of unique, hashable objects.
#       Implemented as a hash table with no values.
#
# Big-O summary:
#   Add / Remove     : O(1) average
#   Membership (in)  : O(1) average  ← KEY ADVANTAGE over list
#   Union            : O(m + n)
#   Intersection     : O(min(m, n))
#   Difference       : O(n)
#
# PRODUCTION PATTERN: Deduplication, fast membership tests,
# computing differences between two large datasets.

print("\n=== set: Hash Set ===")

# Membership: set O(1) vs list O(n)
data = list(range(100_000))
lookup = 99_999
data_set = set(data)

start = time.perf_counter()
for _ in range(1000):
    _ = lookup in data         # O(n) each
list_time = time.perf_counter() - start

start = time.perf_counter()
for _ in range(1000):
    _ = lookup in data_set     # O(1) each
set_time = time.perf_counter() - start

print(f"  list membership (1000x): {list_time*1000:.2f}ms")
print(f"  set  membership (1000x): {set_time*1000:.2f}ms")
print(f"  speedup: {list_time/set_time:.0f}x")

# Set operations: finding active users who are also premium
all_users = {1, 2, 3, 4, 5, 6, 7, 8}
premium   = {2, 4, 6, 8}
active    = {1, 2, 3, 6, 7}
active_premium = premium & active         # intersection
churned        = premium - active         # in premium but not active
print(f"  active premium users: {active_premium}")
print(f"  churned premium users: {churned}")

# frozenset: immutable, hashable set — usable as dict key
permissions = frozenset(["read", "write"])
role_map = {permissions: "editor"}
print(f"  frozenset as dict key: {role_map[permissions]}")

# ============================================================
# SECTION 4: deque — Double-Ended Queue
# ============================================================
# WHAT: collections.deque is a doubly-linked list of fixed-size
#       blocks. Provides O(1) append and pop from BOTH ends.
# WHY:  list.insert(0, x) and list.pop(0) are O(n).
#       deque.appendleft() and deque.popleft() are O(1).
#
# Big-O summary:
#   appendleft / append      : O(1)
#   popleft / pop            : O(1)
#   Access by index          : O(n)  ← weakness vs list
#   rotate                   : O(k)
#
# PRODUCTION PATTERN: Sliding window rate limiter, BFS queue,
#       bounded log/history buffer (maxlen).

print("\n=== deque: Double-Ended Queue ===")

# Sliding window: keep last 5 events
window = deque(maxlen=5)
for i in range(10):
    window.append(i)
    # automatically evicts oldest when maxlen exceeded
print(f"  sliding window (maxlen=5) after 10 appends: {list(window)}")

# BFS using deque
def bfs(graph: dict, start: str) -> list:
    """Breadth-first search — O(V + E)."""
    visited = set()
    queue = deque([start])
    order = []
    while queue:
        node = queue.popleft()    # O(1) — critical for BFS performance
        if node in visited:
            continue
        visited.add(node)
        order.append(node)
        queue.extend(graph.get(node, []))
    return order

graph = {"A": ["B", "C"], "B": ["D"], "C": ["D", "E"], "D": [], "E": []}
print(f"  BFS order: {bfs(graph, 'A')}")

# Performance comparison: deque vs list for left operations
n = 50_000
lst = list(range(n))
dq  = deque(range(n))

start = time.perf_counter()
for _ in range(1000):
    lst.insert(0, 0)    # O(n) — shifts entire list
list_insert_time = time.perf_counter() - start

start = time.perf_counter()
for _ in range(1000):
    dq.appendleft(0)    # O(1)
deque_insert_time = time.perf_counter() - start

print(f"  list.insert(0, x) 1000x: {list_insert_time*1000:.1f}ms")
print(f"  deque.appendleft  1000x: {deque_insert_time*1000:.1f}ms")
print(f"  speedup: {list_insert_time/deque_insert_time:.0f}x")

# ============================================================
# SECTION 5: heapq — Min-Heap
# ============================================================
# WHAT: heapq transforms a list into a binary min-heap.
#       The invariant: heap[k] <= heap[2k+1] and heap[k] <= heap[2k+2]
#
# Big-O summary:
#   heappush    : O(log n)
#   heappop     : O(log n)
#   heapify     : O(n)     ← faster than n pushes
#   nlargest/nsmallest: O(n + k log n)
#
# PRODUCTION PATTERN: Top-K queries, Dijkstra's algorithm,
#       priority queues in task schedulers, merge sorted streams.

print("\n=== heapq: Min-Heap ===")

# Min-heap for task scheduling by priority
tasks = []
heapq.heappush(tasks, (3, "low priority task"))
heapq.heappush(tasks, (1, "urgent task"))
heapq.heappush(tasks, (2, "normal task"))

print("  Processing tasks by priority:")
while tasks:
    priority, task = heapq.heappop(tasks)
    print(f"    priority={priority}: {task}")

# Max-heap: negate values (heapq only provides min-heap)
max_heap = []
for v in [3, 1, 4, 1, 5, 9, 2, 6]:
    heapq.heappush(max_heap, -v)           # negate to simulate max
top = -heapq.heappop(max_heap)
print(f"  Max value via negation: {top}")

# Top-K: find 3 largest without sorting all
scores = [45, 92, 17, 88, 63, 71, 99, 34]
top3 = heapq.nlargest(3, scores)
print(f"  Top 3 scores: {top3}")

# Merge sorted iterators (e.g., merge sorted log files)
stream_a = iter([1, 4, 7])
stream_b = iter([2, 5, 8])
stream_c = iter([3, 6, 9])
merged = list(heapq.merge(stream_a, stream_b, stream_c))
print(f"  Merged streams: {merged}")

# ============================================================
# SECTION 6: defaultdict — Auto-Initializing Dict
# ============================================================
# WHAT: dict subclass that calls a factory when a key is missing.
# WHY:  Eliminates setdefault() boilerplate for grouping/accumulating.
# COMMON MISTAKE: Using defaultdict when you want KeyError on missing
#       keys — it silently creates them instead.

print("\n=== defaultdict ===")

# Group words by first letter — classic use case
words = ["apple", "banana", "avocado", "blueberry", "cherry", "apricot"]
grouped = defaultdict(list)
for word in words:
    grouped[word[0]].append(word)
print(f"  grouped by first letter: {dict(grouped)}")

# Count occurrences (though Counter is better for this)
freq = defaultdict(int)
for word in words:
    freq[word[0]] += 1
print(f"  frequency: {dict(freq)}")

# Graph adjacency list
edges = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]
graph = defaultdict(set)
for u, v in edges:
    graph[u].add(v)
    graph[v].add(u)    # undirected
print(f"  adjacency list: {dict(graph)}")

# ============================================================
# SECTION 7: Counter — Multiset / Frequency Map
# ============================================================
# WHAT: dict subclass optimized for counting. Most common, arithmetic,
#       subtraction all built in.
# WHY:  Word frequency, histogram, inventory management.

print("\n=== Counter ===")

text = "the quick brown fox jumps over the lazy dog the fox"
word_count = Counter(text.split())
print(f"  word_count: {word_count}")
print(f"  most common 3: {word_count.most_common(3)}")

# Arithmetic operations
inventory_a = Counter(apples=5, bananas=3, oranges=2)
inventory_b = Counter(apples=2, bananas=5, grapes=4)

combined  = inventory_a + inventory_b   # sum
diff      = inventory_a - inventory_b   # subtract (drop negatives)
intersect = inventory_a & inventory_b   # min of each
union     = inventory_a | inventory_b   # max of each

print(f"  combined:  {dict(combined)}")
print(f"  diff:      {dict(diff)}")

# ============================================================
# SECTION 8: OrderedDict — Ordered with Move-to-End
# ============================================================
# WHAT: dict subclass with move_to_end() and popitem(last=True/False).
# WHY:  Regular dict is ordered by insertion, but lacks move_to_end().
#       OrderedDict is the classic foundation for LRU cache.
# NOTE: functools.lru_cache is better for caching — use OrderedDict
#       only when you need a manually controlled LRU data structure.

print("\n=== OrderedDict: LRU Cache ===")

class LRUCache:
    """Manual LRU cache using OrderedDict — O(1) get and put."""

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.cache = OrderedDict()

    def get(self, key: int) -> int:
        if key not in self.cache:
            return -1
        self.cache.move_to_end(key)   # mark as recently used
        return self.cache[key]

    def put(self, key: int, value: int) -> None:
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)  # evict least recently used

lru = LRUCache(3)
lru.put(1, "a")
lru.put(2, "b")
lru.put(3, "c")
lru.get(1)        # access 1 → moves to end
lru.put(4, "d")   # evicts 2 (least recently used)
print(f"  LRU state: {dict(lru.cache)}")   # 1, 3, 4 (not 2)

# ============================================================
# SECTION 9: Quick Reference — Choosing the Right Structure
# ============================================================
print("\n=== Choosing the Right Data Structure ===")
print("""
  Need                           → Use
  ─────────────────────────────────────────────────────────
  Ordered sequence, index access → list
  Fast left/right append/pop     → deque
  Membership test (O(1))         → set or dict
  Key-value store                → dict
  Ordered key-value (insert ord) → dict (3.7+) or OrderedDict
  LRU eviction                   → OrderedDict or functools.lru_cache
  Priority / top-K               → heapq
  Auto-initialize on missing key → defaultdict
  Word frequency / multiset      → Counter
  Immutable set (hashable)       → frozenset
  Read-only snapshot of list     → tuple
  Large numeric arrays           → numpy.ndarray (not list!)
  ─────────────────────────────────────────────────────────
""")
