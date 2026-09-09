# Data Structures & Algorithms — In-Depth Reference

Interview-prep-focused DSA — patterns over memorized solutions, since
pattern recognition is what actually transfers to a novel problem in an interview.


## 1. BIG-O COMPLEXITY, QUICK REFERENCE

| Structure | Access | Search | Insert | Delete |
|---|---|---|---|---|
| Array | O(1) | O(n) | O(n) | O(n) |
| Linked List | O(n) | O(n) | O(1)* | O(1)* |
| Hash Table | — | O(1) avg | O(1) avg | O(1) avg |
| BST (balanced) | — | O(log n) | O(log n) | O(log n) |
| Heap | — | O(n) | O(log n) | O(log n) |

*O(1) at a known position; O(n) if you must first find the position.

Common complexity classes ranked: O(1) < O(log n) < O(n) < O(n log n) <
O(n²) < O(2ⁿ) < O(n!) — a genuinely useful habit: state the complexity of
your proposed solution BEFORE being asked, it signals you're thinking about it proactively.


## 2. THE PATTERN CATALOG — RECOGNIZE THE SHAPE, NOT THE SPECIFIC PROBLEM

### Two Pointers
Use when: searching pairs/triplets in a SORTED array, or comparing from
both ends. `left`/`right` pointers converge or move based on a condition.
```python
def two_sum_sorted(arr, target):
    left, right = 0, len(arr) - 1
    while left < right:
        s = arr[left] + arr[right]
        if s == target: return [left, right]
        elif s < target: left += 1
        else: right -= 1
```

### Sliding Window
Use when: finding a subarray/substring satisfying a condition
(longest/shortest/max-sum). Grow the window by moving `right`; shrink by
moving `left` when the condition is violated.
```python
def longest_substring_k_distinct(s, k):
    left = 0; char_count = {}; max_len = 0
    for right, char in enumerate(s):
        char_count[char] = char_count.get(char, 0) + 1
        while len(char_count) > k:
            char_count[s[left]] -= 1
            if char_count[s[left]] == 0: del char_count[s[left]]
            left += 1
        max_len = max(max_len, right - left + 1)
    return max_len
```

### Fast & Slow Pointers (Tortoise and Hare)
Use when: cycle detection in a linked list, or finding a middle element
in one pass. Slow moves 1 step, fast moves 2 — if there's a cycle, they must eventually meet.

### BFS/DFS on Trees & Graphs
BFS (queue-based) explores level by level — use for SHORTEST PATH in an
unweighted graph. DFS (stack/recursion-based) explores as deep as
possible first — use for exploring ALL paths, detecting cycles, or
topological sort. **Recognizing which to use**: "shortest"/"minimum
steps" strongly suggests BFS; "all paths"/"any valid arrangement" suggests DFS/backtracking.

### Backtracking
Use when: generating all permutations/combinations/subsets, or
constraint-satisfaction (N-Queens, Sudoku). Try a choice, recurse, UNDO
the choice if it doesn't lead to a solution ("backtrack") — the undo step
is the part beginners forget and the actual defining feature of this pattern.

### Dynamic Programming — the pattern-recognition checklist
1. Can the problem be broken into OVERLAPPING subproblems? (If
   subproblems don't overlap, plain recursion/divide-and-conquer suffices.)
2. Define the state precisely: what does `dp[i]` (or `dp[i][j]`)
   actually represent?
3. Find the recurrence: how does `dp[i]` relate to smaller states?
4. Base cases, then decide top-down (memoization) or bottom-up (tabulation).
```python
# Classic 1D DP: climbing stairs (dp[i] = ways to reach step i)
def climb_stairs(n):
    if n <= 2: return n
    dp = [0] * (n + 1)
    dp[1], dp[2] = 1, 2
    for i in range(3, n + 1):
        dp[i] = dp[i-1] + dp[i-2]
    return dp[n]
```

### Binary Search — beyond "find element in sorted array"
The generalized pattern: binary search works on ANY monotonic condition,
not just sorted arrays — "find the minimum X such that condition(X) is
true" where condition is monotonic (once true, stays true for all larger
X) — a genuinely underused generalization that unlocks many "optimize a
parameter" problems disguised as something else.

### Merge Intervals
Use when: dealing with intervals/ranges (meeting rooms, calendar
conflicts). Sort by start time first — this single step is what makes
the rest of the problem tractable in a single linear pass.

### Union-Find (Disjoint Set)
Use when: grouping elements into connected components incrementally
(detecting cycles in an undirected graph, finding connected components,
Kruskal's MST algorithm). Path compression + union by rank make it
near-O(1) amortized per operation — worth knowing this optimization exists even if not implementing it from scratch under interview time pressure.


## 3. SORTING ALGORITHMS — WHEN EACH ACTUALLY MATTERS

- **Quicksort** — O(n log n) average, O(n²) worst case (mitigated by
  randomized pivot selection) — generally the fastest in-practice
  general-purpose sort due to good cache locality and low constant factor.
- **Mergesort** — O(n log n) guaranteed (no bad worst case), STABLE
  (preserves relative order of equal elements) — the right choice when
  worst-case guarantees or stability matter more than average-case speed.
- **Heapsort** — O(n log n) guaranteed, O(1) extra space (unlike
  mergesort's O(n)) — chosen when memory is genuinely constrained and
  mergesort's extra space isn't acceptable.
- **Why this matters in interviews**: knowing WHY a language's built-in
  sort (`Arrays.sort` in Java for primitives is dual-pivot quicksort; for
  objects it's a stable mergesort/timsort variant) makes different choices for different types is a real depth signal beyond "call .sort()."


## 4. NICHE BUT REAL

- **Trie (prefix tree)** — a tree structure where each path from root
  represents a string prefix — the standard structure behind
  autocomplete/spell-check (see Search Engines deep dive's edge-ngram
  discussion for a related but distinct indexing approach) — O(m) lookup
  where m is the string length, independent of how many strings are stored.
- **Segment trees & Fenwick trees (BIT)** — specialized structures for
  RANGE queries (sum/min/max over a range) with efficient updates — genuinely advanced, but a real differentiator in harder interview problems
  involving frequent range queries on mutable data.
- **Monotonic stack** — a stack maintained in sorted (monotonic) order,
  used for "next greater/smaller element" style problems in O(n) instead
  of the naive O(n²) — a genuinely elegant pattern once recognized, opaque before you've seen it.
- **Bit manipulation tricks** — `n & (n-1)` clears the lowest set bit
  (used to count set bits or check power-of-2 in O(1)); XOR's
  self-canceling property (`a ^ a = 0`) solves "find the single unique
  element" problems in O(n) time, O(1) space — a real, distinct toolkit
  worth having memorized for the specific subset of problems where it applies.
- **Amortized analysis** — why a dynamic array's `append` is called
  O(1) despite occasional O(n) resize operations — the COST of resizing,
  spread across all the O(1) appends between resizes, averages out to
  O(1) per operation — genuinely useful to be able to explain precisely
  when asked "isn't resizing O(n), so how is append O(1)?"
