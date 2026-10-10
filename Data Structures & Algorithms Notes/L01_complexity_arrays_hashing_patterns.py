"""
============================================================
L01: Complexity Analysis, Arrays & Strings, Hashing Patterns
============================================================
WHAT: CLRS Part I (Foundations: growth of functions, asymptotic
      notation, recurrences & the master theorem) plus the array/
      string pattern families every algorithms course and
      interview-prep catalogue teaches first: two pointers,
      sliding window (fixed & variable), prefix sums & difference
      arrays, hashing for O(1) lookup (frequency maps, complement
      lookup, grouping by canonical key), Kadane's algorithm,
      in-place array manipulation, and matrix traversal.
WHY:  Most "medium" problems are an O(n²) brute force that one of
      these patterns turns into O(n). Being able to state and
      PROVE complexity (not just guess it) is what separates a
      senior answer from a junior one.
LEVEL: Foundation
RUN:   python L01_complexity_arrays_hashing_patterns.py   (self-checking with asserts)
SOURCE: Cormen, Leiserson, Rivest, Stein — "Introduction to Algorithms"
        4th ed. (CLRS) ch. 1-4; Sedgewick & Wayne "Algorithms" 4th ed. §1.4;
        Python time-complexity wiki (wiki.python.org/moin/TimeComplexity)
============================================================

CONCEPT OVERVIEW:
    Asymptotic notation describes growth as n → ∞:
      O(g)  upper bound   f ≤ c·g eventually
      Ω(g)  lower bound   f ≥ c·g eventually
      Θ(g)  tight bound   both
    Analyse WORST case unless stated; AVERAGE case needs an input
    distribution; AMORTISED cost averages over a sequence of ops
    (L08). Space complexity counts extra memory (incl. recursion stack).

PRODUCTION USE CASE:
    Real-time trading analytics: max profit window, rolling
    averages, duplicate-order detection and anomaly windows over a
    price stream — each a sliding-window / prefix-sum / hashing
    pattern running in O(n).

COMMON MISTAKES:
    1. Hidden O(n) inside a loop: `x in list`, list.pop(0),
       string concatenation in a loop, slicing (copies!).
    2. Dropping the cost of sorting (n log n) when "just sorting first".
    3. Sliding window on arrays with negative numbers for "sum ≥ k"
       — the shrink condition isn't monotonic; use prefix sums + deque.
    4. Off-by-one in window bounds — use half-open [left, right).
    5. Using a mutable list as a dict key — hash a tuple/frozenset.
"""

from __future__ import annotations

import math
import random
import time
from bisect import bisect_left
from collections import Counter, defaultdict, deque
from itertools import accumulate


# ============================================================
# SECTION 1: COMPLEXITY — growth, recurrences, master theorem
# ============================================================
# Common classes: O(1) < O(log n) < O(√n) < O(n) < O(n log n) < O(n²) < O(2ⁿ) < O(n!)
# Rough budget at ~10⁸ simple ops/second (C-ish; Python is ~30-100x slower):
#   n ≤ 10       → O(n!) ok         n ≤ 20  → O(2ⁿ)
#   n ≤ 500      → O(n³)            n ≤ 5000 → O(n²)
#   n ≤ 10⁶      → O(n log n)       n ≤ 10⁸  → O(n)
#
# MASTER THEOREM for T(n) = a·T(n/b) + f(n), with c* = log_b(a):
#   Case 1: f(n) = O(n^(c*-ε))           → T(n) = Θ(n^c*)          (leaves dominate)
#   Case 2: f(n) = Θ(n^c* · logᵏ n)      → T(n) = Θ(n^c* · logᵏ⁺¹ n)
#   Case 3: f(n) = Ω(n^(c*+ε)) + regularity → T(n) = Θ(f(n))       (root dominates)
# Examples:
#   binary search  T(n)=T(n/2)+1     a=1,b=2,c*=0, f=Θ(1)=Θ(n⁰)  → case 2 → Θ(log n)
#   merge sort     T(n)=2T(n/2)+n    c*=1, f=Θ(n)               → case 2 → Θ(n log n)
#   Karatsuba      T(n)=3T(n/2)+n    c*=log₂3≈1.585, f=O(n¹)    → case 1 → Θ(n^1.585)
#   Strassen       T(n)=7T(n/2)+n²   c*=log₂7≈2.807             → case 1 → Θ(n^2.807)

def master_theorem(a: int, b: int, f_exponent: float) -> str:
    """Classify T(n)=a·T(n/b)+Θ(n^f_exponent) (polynomial f only)."""
    c = math.log(a, b)

    def poly(e: float) -> str:
        return "1" if math.isclose(e, 0) else "n" if math.isclose(e, 1) else f"n^{e:.3g}"

    if math.isclose(f_exponent, c):                       # case 2
        return "Θ(log n)" if math.isclose(c, 0) else f"Θ({poly(c)} log n)"
    return f"Θ({poly(c)})" if f_exponent < c else f"Θ({poly(f_exponent)})"   # case 1 / case 3


def empirical_order(fn, sizes) -> float:
    """Estimate the exponent k in T(n) ~ n^k from the log-log slope of timings."""
    times = []
    for n in sizes:
        data = list(range(n))
        random.Random(0).shuffle(data)                 # sorted input would hit Timsort's O(n) fast path
        t0 = time.perf_counter()
        fn(data)
        times.append(time.perf_counter() - t0)
    return math.log(times[-1] / times[0]) / math.log(sizes[-1] / sizes[0])


# Python built-in costs worth memorising (CPython):
#   list: index O(1), append O(1)*, pop() O(1), pop(0)/insert(0) O(n), `in` O(n), slice O(k)
#   dict/set: get/set/`in`/del O(1) avg (O(n) worst on adversarial collisions)
#   deque: append/appendleft/pop/popleft O(1), index O(n)
#   heapq: push/pop O(log n), heapify O(n)        str: concat in a loop O(n²) → use ''.join
#   sorted/list.sort: O(n log n) Timsort, O(n) on already-sorted runs


# ============================================================
# SECTION 2: TWO POINTERS
# ============================================================
def pair_with_sum_sorted(nums: list[int], target: int) -> tuple[int, int] | None:
    """Opposite-direction pointers on SORTED input: O(n) time, O(1) space."""
    lo, hi = 0, len(nums) - 1
    while lo < hi:
        s = nums[lo] + nums[hi]
        if s == target:
            return lo, hi
        if s < target:
            lo += 1          # need a bigger sum
        else:
            hi -= 1          # need a smaller sum
    return None


def three_sum(nums: list[int]) -> list[tuple[int, int, int]]:
    """All unique triplets summing to 0: sort + two pointers per anchor → O(n²)."""
    nums = sorted(nums)
    out = []
    for i in range(len(nums) - 2):
        if i and nums[i] == nums[i - 1]:
            continue                                      # skip duplicate anchors
        lo, hi = i + 1, len(nums) - 1
        while lo < hi:
            s = nums[i] + nums[lo] + nums[hi]
            if s == 0:
                out.append((nums[i], nums[lo], nums[hi]))
                lo += 1
                while lo < hi and nums[lo] == nums[lo - 1]:
                    lo += 1                               # skip duplicate seconds
                hi -= 1
            elif s < 0:
                lo += 1
            else:
                hi -= 1
    return out


def remove_duplicates_in_place(nums: list[int]) -> int:
    """Same-direction (slow/fast) pointers on sorted input; returns new length."""
    if not nums:
        return 0
    write = 1
    for read in range(1, len(nums)):
        if nums[read] != nums[write - 1]:
            nums[write] = nums[read]
            write += 1
    return write


def max_water_container(heights: list[int]) -> int:
    """Move the SHORTER wall inward — the taller can't improve area with a narrower width."""
    lo, hi, best = 0, len(heights) - 1, 0
    while lo < hi:
        best = max(best, (hi - lo) * min(heights[lo], heights[hi]))
        if heights[lo] < heights[hi]:
            lo += 1
        else:
            hi -= 1
    return best


# ============================================================
# SECTION 3: SLIDING WINDOW
# ============================================================
def max_sum_fixed_window(nums: list[int], k: int) -> int:
    """Fixed size: add the entering element, subtract the leaving one. O(n)."""
    window = sum(nums[:k])
    best = window
    for i in range(k, len(nums)):
        window += nums[i] - nums[i - k]
        best = max(best, window)
    return best


def longest_unique_substring(s: str) -> int:
    """Variable window: expand right; when invalid, shrink left. Each index moves ≤ 2 times → O(n)."""
    last_seen: dict[str, int] = {}
    left = best = 0
    for right, ch in enumerate(s):
        if ch in last_seen and last_seen[ch] >= left:
            left = last_seen[ch] + 1                      # jump past the previous occurrence
        last_seen[ch] = right
        best = max(best, right - left + 1)
    return best


def min_window_covering(s: str, t: str) -> str:
    """Smallest substring of s containing all chars of t (with multiplicity). O(|s| + |t|)."""
    need = Counter(t)
    missing = len(t)
    left = 0
    best = (math.inf, 0, 0)
    for right, ch in enumerate(s, 1):                     # window is s[left:right]
        if need[ch] > 0:
            missing -= 1
        need[ch] -= 1
        if missing == 0:                                  # valid: shrink from the left
            while need[s[left]] < 0:
                need[s[left]] += 1
                left += 1
            if right - left < best[0]:
                best = (right - left, left, right)
            need[s[left]] += 1                            # break validity, move on
            missing += 1
            left += 1
    return s[best[1]:best[2]] if best[0] != math.inf else ""


def sliding_window_max(nums: list[int], k: int) -> list[int]:
    """Monotonic deque of indices (values decreasing): each index pushed/popped once → O(n)."""
    dq: deque[int] = deque()
    out = []
    for i, x in enumerate(nums):
        while dq and nums[dq[-1]] <= x:
            dq.pop()                                      # smaller values can never be a future max
        dq.append(i)
        if dq[0] <= i - k:
            dq.popleft()                                  # left the window
        if i >= k - 1:
            out.append(nums[dq[0]])
    return out


# ============================================================
# SECTION 4: PREFIX SUMS & DIFFERENCE ARRAYS
# ============================================================
class PrefixSum:
    """O(n) build, O(1) range-sum queries: sum(nums[i:j]) = p[j] - p[i]."""

    def __init__(self, nums: list[int]):
        self.p = [0, *accumulate(nums)]

    def range_sum(self, i: int, j: int) -> int:     # half-open [i, j)
        return self.p[j] - self.p[i]


def subarrays_summing_to_k(nums: list[int], k: int) -> int:
    """Count subarrays with sum k (negatives allowed): prefix sums + hash of seen prefixes. O(n)."""
    seen = Counter({0: 1})
    running = count = 0
    for x in nums:
        running += x
        count += seen[running - k]                        # earlier prefix p with running - p = k
        seen[running] += 1
    return count


def apply_range_increments(n: int, updates: list[tuple[int, int, int]]) -> list[int]:
    """Difference array: each [l, r] += v in O(1), materialise in O(n)."""
    diff = [0] * (n + 1)
    for l, r, v in updates:
        diff[l] += v
        diff[r + 1] -= v
    return list(accumulate(diff))[:n]


class PrefixSum2D:
    """Matrix region sums in O(1) via inclusion–exclusion."""

    def __init__(self, grid: list[list[int]]):
        rows, cols = len(grid), len(grid[0])
        self.p = [[0] * (cols + 1) for _ in range(rows + 1)]
        for r in range(rows):
            for c in range(cols):
                self.p[r + 1][c + 1] = grid[r][c] + self.p[r][c + 1] + self.p[r + 1][c] - self.p[r][c]

    def region(self, r1: int, c1: int, r2: int, c2: int) -> int:   # inclusive corners
        p = self.p
        return p[r2 + 1][c2 + 1] - p[r1][c2 + 1] - p[r2 + 1][c1] + p[r1][c1]


# ============================================================
# SECTION 5: HASHING PATTERNS
# ============================================================
def two_sum(nums: list[int], target: int) -> tuple[int, int] | None:
    """Complement lookup: one pass, O(n) time / O(n) space (vs O(n²) brute force)."""
    index_of: dict[int, int] = {}
    for i, x in enumerate(nums):
        if target - x in index_of:
            return index_of[target - x], i
        index_of[x] = i
    return None


def group_anagrams(words: list[str]) -> list[list[str]]:
    """Group by a CANONICAL KEY (sorted letters, or a 26-count tuple for O(L) keys)."""
    groups: defaultdict[tuple[int, ...], list[str]] = defaultdict(list)
    for w in words:
        counts = [0] * 26
        for ch in w:
            counts[ord(ch) - 97] += 1
        groups[tuple(counts)].append(w)                   # tuples are hashable; lists are not
    return list(groups.values())


def longest_consecutive_run(nums: list[int]) -> int:
    """O(n): only start counting from numbers that begin a run (x-1 not in set)."""
    s = set(nums)
    best = 0
    for x in s:
        if x - 1 not in s:
            length = 1
            while x + length in s:
                length += 1
            best = max(best, length)
    return best


def top_k_frequent(nums: list[int], k: int) -> list[int]:
    """Bucket sort by frequency: O(n), beats the O(n log k) heap for this case."""
    buckets: list[list[int]] = [[] for _ in range(len(nums) + 1)]
    for x, c in Counter(nums).items():
        buckets[c].append(x)
    out = []
    for c in range(len(buckets) - 1, 0, -1):
        out.extend(buckets[c])
        if len(out) >= k:
            return out[:k]
    return out


# ============================================================
# SECTION 6: KADANE, IN-PLACE TRICKS, MATRICES
# ============================================================
def max_subarray(nums: list[int]) -> tuple[int, int, int]:
    """Kadane: best sum ending here = max(x, best_ending_prev + x). Returns (sum, start, end)."""
    best = (nums[0], 0, 0)
    cur, start = nums[0], 0
    for i in range(1, len(nums)):
        if cur < 0:
            cur, start = nums[i], i                       # restarting beats extending a negative prefix
        else:
            cur += nums[i]
        if cur > best[0]:
            best = (cur, start, i)
    return best


def max_profit_one_trade(prices: list[int]) -> int:
    """Track min-so-far: classic stock problem, a Kadane cousin. O(n)."""
    lowest, best = math.inf, 0
    for p in prices:
        lowest = min(lowest, p)
        best = max(best, p - lowest)
    return best


def product_except_self(nums: list[int]) -> list[int]:
    """Left products × right products, no division, O(1) extra space besides output."""
    out = [1] * len(nums)
    left = 1
    for i, x in enumerate(nums):
        out[i] = left
        left *= x
    right = 1
    for i in range(len(nums) - 1, -1, -1):
        out[i] *= right
        right *= nums[i]
    return out


def rotate_in_place(nums: list[int], k: int) -> None:
    """Rotate right by k with three reversals: O(n) time, O(1) space."""
    def rev(i: int, j: int) -> None:
        while i < j:
            nums[i], nums[j] = nums[j], nums[i]
            i, j = i + 1, j - 1
    n = len(nums)
    k %= n
    rev(0, n - 1); rev(0, k - 1); rev(k, n - 1)


def spiral_order(m: list[list[int]]) -> list[int]:
    out = []
    top, bottom, left, right = 0, len(m) - 1, 0, len(m[0]) - 1
    while top <= bottom and left <= right:
        out += [m[top][c] for c in range(left, right + 1)]; top += 1
        out += [m[r][right] for r in range(top, bottom + 1)]; right -= 1
        if top <= bottom:
            out += [m[bottom][c] for c in range(right, left - 1, -1)]; bottom -= 1
        if left <= right:
            out += [m[r][left] for r in range(bottom, top - 1, -1)]; left += 1
    return out


def rotate_matrix_90(m: list[list[int]]) -> None:
    """Transpose then reverse each row = clockwise rotation, in place."""
    n = len(m)
    for i in range(n):
        for j in range(i + 1, n):
            m[i][j], m[j][i] = m[j][i], m[i][j]
    for row in m:
        row.reverse()


# ============================================================
# SECTION 7: END-TO-END — PRICE-STREAM ANALYTICS
# ============================================================
def price_stream_report(prices: list[int], window: int, spike_pct: float) -> dict:
    ps = PrefixSum(prices)
    rolling_avg = [ps.range_sum(i - window + 1, i + 1) / window for i in range(window - 1, len(prices))]
    rolling_max = sliding_window_max(prices, window)
    spikes = [i for i in range(window, len(prices)) if prices[i] > rolling_avg[i - window] * (1 + spike_pct)]
    returns = [b - a for a, b in zip(prices, prices[1:])]
    gain, s, e = max_subarray(returns)
    return {
        "best_single_trade": max_profit_one_trade(prices),
        "best_run": (gain, s, e + 1),                     # buy at s, sell at e+1
        "rolling_avg_last": round(rolling_avg[-1], 2),
        "rolling_max_last": rolling_max[-1],
        "spike_indices": spikes,
    }


def _tests() -> None:
    print("== complexity")
    for a, b, f, name in [(1, 2, 0, "binary search"), (2, 2, 1, "merge sort"), (3, 2, 1, "Karatsuba"), (7, 2, 2, "Strassen"), (2, 2, 2, "T=2T(n/2)+n²")]:
        print(f"   {name:<14} → {master_theorem(a, b, f)}")
    k_sort = empirical_order(sorted, [200_000, 1_600_000])
    # For n log n over an 8x size range, the expected slope is 1 + log(8)/log(n) ≈ 1.15,
    # plus cache-miss effects at large n — so ~1.1-1.5 is "n log n", ~2 would be quadratic.
    print(f"   empirical exponent of sorted() on shuffled data: ≈{k_sort:.2f} (n log n → ~1.1-1.5; n² → ~2)")

    print("== two pointers")
    assert pair_with_sum_sorted([1, 3, 4, 6, 8, 11], 10) == (2, 3)   # 4 + 6
    assert three_sum([-1, 0, 1, 2, -1, -4]) == [(-1, -1, 2), (-1, 0, 1)]
    arr = [1, 1, 2, 2, 2, 3, 5, 5]
    n = remove_duplicates_in_place(arr)
    assert arr[:n] == [1, 2, 3, 5]
    assert max_water_container([1, 8, 6, 2, 5, 4, 8, 3, 7]) == 49
    print("   pair-sum, 3sum, dedupe, container: ok")

    print("== sliding window")
    assert max_sum_fixed_window([2, 1, 5, 1, 3, 2], 3) == 9
    assert longest_unique_substring("abcabcbb") == 3 and longest_unique_substring("pwwkew") == 3
    assert min_window_covering("ADOBECODEBANC", "ABC") == "BANC"
    assert sliding_window_max([1, 3, -1, -3, 5, 3, 6, 7], 3) == [3, 3, 5, 5, 6, 7]
    print("   fixed, variable, min-cover, monotonic-deque max: ok")

    print("== prefix sums")
    assert PrefixSum([3, 1, 4, 1, 5]).range_sum(1, 4) == 6
    assert subarrays_summing_to_k([1, 2, 3, -3, 3], 3) == 5
    assert apply_range_increments(5, [(1, 3, 2), (2, 4, 3), (0, 2, -2)]) == [-2, 0, 3, 5, 3]
    g = PrefixSum2D([[3, 0, 1], [5, 6, 3], [1, 2, 0]])
    assert g.region(1, 1, 2, 2) == 11
    print("   1D, subarray-sum-k with negatives, difference array, 2D region: ok")

    print("== hashing")
    assert two_sum([2, 7, 11, 15], 9) == (0, 1)
    assert sorted(map(sorted, group_anagrams(["eat", "tea", "tan", "ate", "nat", "bat"]))) == [["ate", "eat", "tea"], ["bat"], ["nat", "tan"]]
    assert longest_consecutive_run([100, 4, 200, 1, 3, 2]) == 4
    assert top_k_frequent([1, 1, 1, 2, 2, 3], 2) == [1, 2]
    print("   two-sum, anagrams, consecutive run, top-k buckets: ok")

    print("== kadane & in-place")
    assert max_subarray([-2, 1, -3, 4, -1, 2, 1, -5, 4]) == (6, 3, 6)
    assert product_except_self([1, 2, 3, 4]) == [24, 12, 8, 6]
    r = [1, 2, 3, 4, 5, 6, 7]; rotate_in_place(r, 3); assert r == [5, 6, 7, 1, 2, 3, 4]
    assert spiral_order([[1, 2, 3], [4, 5, 6], [7, 8, 9]]) == [1, 2, 3, 6, 9, 8, 7, 4, 5]
    m = [[1, 2], [3, 4]]; rotate_matrix_90(m); assert m == [[3, 1], [4, 2]]
    print("   kadane, product-except-self, rotations, spiral: ok")

    # Randomised cross-check of an O(n) algorithm against brute force.
    rng = random.Random(42)
    for _ in range(300):
        nums = [rng.randint(-5, 5) for _ in range(rng.randint(1, 12))]
        k = rng.randint(-5, 5)
        brute = sum(1 for i in range(len(nums)) for j in range(i + 1, len(nums) + 1) if sum(nums[i:j]) == k)
        assert subarrays_summing_to_k(nums, k) == brute
    print("   randomised check vs brute force (300 cases): ok")

    print("== end-to-end: price stream")
    rng = random.Random(7)
    prices = [100]
    for i in range(59):
        prices.append(max(1, prices[-1] + rng.randint(-3, 3) + (12 if i == 40 else 0)))
    report = price_stream_report(prices, window=5, spike_pct=0.08)
    for k_, v in report.items():
        print(f"   {k_}: {v}")
    assert 41 in report["spike_indices"]


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")   # Windows consoles default to cp1252
    _tests()
