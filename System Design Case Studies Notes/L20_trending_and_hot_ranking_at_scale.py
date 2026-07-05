# ============================================================
# L20: Trending Detection at Scale — Capstone of the Reddit/Social Feed Case Study
# ============================================================
# WHAT: How a platform detects "what's trending RIGHT NOW" across
#       millions of posts/hashtags/topics in near-real-time — sliding
#       time windows, streaming count-based approximation algorithms,
#       and why this is a genuinely different problem from L17's
#       per-post ranking.
# WHY: Capstone lesson for this case study — L16-L19 covered storing,
#      ranking, voting on, and DISTRIBUTING individual pieces of
#      content; this lesson covers the AGGREGATE, cross-content
#      analysis needed for a "Trending" feature.
# LEVEL: Advanced (capstone of this case study)
# ============================================================

"""
CONCEPT OVERVIEW:
TRENDING DETECTION is a DIFFERENT problem from L17's per-post ranking:
"Hot"/"Best" ranks INDIVIDUAL posts against each other; "Trending"
identifies which TOPICS/HASHTAGS/KEYWORDS are experiencing an unusual
SPIKE in mention volume RIGHT NOW, relative to their normal baseline —
a topic mentioned constantly at a stable rate (even a HIGH stable rate)
is NOT trending; a topic that suddenly spikes from near-zero to a
meaningful volume IS trending, even at a much lower absolute volume than
the first topic.

SLIDING TIME WINDOWS are the basic mechanism: rather than counting
mentions over ALL TIME (which would make a sudden recent spike
invisible against a large historical total), trending detection counts
mentions within a RECENT, BOUNDED window (e.g. the last 10 minutes),
continuously sliding that window forward — this naturally makes old
activity "age out" of consideration, surfacing only what's happening NOW.

COMPARING AGAINST A BASELINE is what distinguishes "trending" from
"simply currently popular": a topic's current-window count is compared
against its OWN historical baseline (e.g. its typical count during this
same window length, at this same time of day, on a normal day) — a
topic with 10,000 current mentions that NORMALLY gets 9,500 mentions in
a similar window is NOT trending (it's just consistently popular); a
topic jumping from a normal baseline of 50 to a current 5,000 IS
trending, despite the much smaller absolute number — this relative-spike
comparison, not absolute volume, is the actual trending signal.

APPROXIMATE COUNTING AT SCALE: tracking EXACT mention counts for every
possible topic/hashtag/keyword across a massive, high-volume platform in
real time is a genuinely hard counting problem — PROBABILISTIC DATA
STRUCTURES like COUNT-MIN SKETCH provide approximate counts using
BOUNDED, fixed memory regardless of how many distinct topics exist,
trading small, controlled overcounting error for the ability to track
an effectively unlimited number of distinct keys without memory usage
growing unboundedly — a standard technique in high-volume streaming
analytics systems more broadly (also used in general rate-limiting and
anomaly-detection systems beyond this specific use case).

WHY THIS IS COMPUTED AS A SEPARATE, STREAMING PIPELINE rather than a
direct database query: computing "spike relative to baseline, across
every distinct topic, continuously, in near-real-time" as an on-demand
query against the primary content database would be prohibitively
expensive to run for every user's page load — production systems run
this as a DEDICATED STREAMING AGGREGATION PIPELINE (this repo's Apache
Kafka Notes and Event-Driven & Real-Time AI Systems Notes cover the
general architecture for this class of problem) that continuously
maintains a small, precomputed "currently trending" list, which regular
page loads then simply READ from — decoupling the expensive continuous
computation from the cheap, frequent read path.

PRODUCTION USE CASE:
A major, unexpected news event causes mentions of a specific term to
spike from a baseline of roughly 20 mentions per 10-minute window to over
50,000 within a single window — the platform's streaming trending
pipeline detects this spike (a ~2500x deviation from baseline) within
minutes and surfaces the term on the "Trending" page, while an
unrelated, perpetually-popular general topic (e.g. a major ongoing
sports league) that maintains a STABLE high mention volume every day
never appears on "Trending" specifically because it lacks a meaningful
deviation from ITS OWN normal baseline.

COMMON MISTAKES:
- Ranking "Trending" by ABSOLUTE current volume rather than relative
  deviation from baseline — this surfaces perpetually popular topics
  (which are simply always highly mentioned) rather than genuinely
  NEWLY spiking ones, defeating the actual purpose of a trending feature.
- Computing trending analysis as an expensive on-demand query against
  the live content database on every page load — this doesn't scale to
  a platform's actual read volume; a precomputed, continuously-updated
  streaming pipeline that regular page loads simply READ from is the
  production-appropriate architecture.
- Attempting to track EXACT counts for every possible distinct
  keyword/hashtag at platform scale using a simple hash map — memory
  usage grows unboundedly with the number of distinct terms ever
  mentioned; approximate counting structures (count-min sketch) bound
  memory usage at the cost of small, controlled counting error.
"""

import time
from collections import defaultdict, deque


# ------------------------------------------------------------------
# 1. Sliding time window mention counting
# ------------------------------------------------------------------
class SlidingWindowCounter:
    def __init__(self, window_seconds: float = 600):
        self.window_seconds = window_seconds
        self.mentions: dict[str, deque] = defaultdict(deque)

    def record_mention(self, topic: str, timestamp: float):
        self.mentions[topic].append(timestamp)

    def current_count(self, topic: str, now: float) -> int:
        window = self.mentions[topic]
        # Age out anything outside the current sliding window
        while window and now - window[0] > self.window_seconds:
            window.popleft()
        return len(window)


# ------------------------------------------------------------------
# 2. Spike detection — relative deviation from historical baseline
# ------------------------------------------------------------------
def detect_trending(current_counts: dict[str, int], baseline_counts: dict[str, float],
                     min_absolute_count: int = 20, spike_threshold: float = 5.0) -> list[dict]:
    trending = []
    for topic, current in current_counts.items():
        if current < min_absolute_count:
            continue   # ignore noise — too few mentions to be meaningful either way
        baseline = baseline_counts.get(topic, 1)   # avoid division by zero for brand-new topics
        deviation_ratio = current / baseline
        if deviation_ratio >= spike_threshold:
            trending.append({"topic": topic, "current": current,
                              "baseline": baseline, "deviation": deviation_ratio})
    return sorted(trending, key=lambda t: t["deviation"], reverse=True)


def trending_detection_demo():
    current_window_counts = {
        "#breakingnews": 50000,      # sudden spike
        "#popularsportsleague": 9500,  # consistently popular
        "#nichehobby": 25,             # too rare to matter
    }
    historical_baselines = {
        "#breakingnews": 20,
        "#popularsportsleague": 9200,   # normally ALSO around this level
        "#nichehobby": 22,
    }

    trending = detect_trending(current_window_counts, historical_baselines)
    print("Current mention counts vs historical baselines:")
    for topic in current_window_counts:
        print(f"  {topic}: current={current_window_counts[topic]}, "
              f"baseline={historical_baselines[topic]}")

    print(f"\nDetected as TRENDING (relative spike >= 5x baseline):")
    for t in trending:
        print(f"  {t['topic']}: {t['deviation']:.1f}x baseline")
    print("\n  -> #popularsportsleague has a MUCH higher absolute count than")
    print("     #breakingnews, but is correctly EXCLUDED from trending —")
    print("     it's simply always popular, with no meaningful deviation.")


# ------------------------------------------------------------------
# 3. Count-min sketch — bounded-memory approximate counting (conceptual)
# ------------------------------------------------------------------
def count_min_sketch_explanation():
    print("\nCount-Min Sketch (conceptual, bounded-memory approximate counting):")
    print("  - A fixed-size 2D array of counters + several hash functions")
    print("  - To INCREMENT a topic's count: hash it with EACH hash function,")
    print("    incrementing the corresponding counter in each hash's row")
    print("  - To QUERY a topic's approximate count: take the MINIMUM value")
    print("    across all its hashed positions (this minimizes the impact")
    print("    of hash collisions with OTHER topics)")
    print("  - Memory usage is FIXED regardless of how many distinct topics")
    print("    exist — a critical property for platform-scale streaming")
    print("    analytics, at the cost of small, bounded overcounting error.")


if __name__ == "__main__":
    trending_detection_demo()
    count_min_sketch_explanation()

"""
FINAL CONTEXT (capstone of the Reddit/social feed case study):
The full picture across L16-L20: comments/posts are stored in a
tree-friendly, insert-optimized structure (L16); ranked using formulas
that correctly balance freshness against statistical confidence (L17);
voted on via an event-sourced, fraud-resistant pipeline that scales to
viral write volume (L18); distributed to followers via a hybrid
fan-out strategy that avoids the celebrity write-amplification problem
(L19); and, at the aggregate cross-content level, analyzed by a
dedicated streaming pipeline that surfaces genuine spikes rather than
merely-popular content (L20) — five architecturally DISTINCT problems
that, together, constitute the real system design challenge behind any
large-scale social content platform.
"""
