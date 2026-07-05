# ============================================================
# L19: Fan-Out on Write vs Fan-Out on Read — How Social Feeds Actually Scale
# ============================================================
# WHAT: The single most important architectural decision behind any
#       social media feed (Twitter/X, Instagram, Facebook) — WHEN a
#       new post gets distributed to followers' feeds: immediately at
#       post-time (fan-out on write) or computed on demand when a
#       follower opens the app (fan-out on read) — and why large
#       platforms use BOTH, selectively.
# WHY: This generalizes beyond Reddit specifically — Reddit itself is
#      subreddit-subscription-based (closer to fan-out on read per
#      subreddit), but this fan-out problem is THE defining scaling
#      challenge across essentially every social feed product.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
FAN-OUT ON WRITE (push model): when a user posts, the system IMMEDIATELY
writes that post into EVERY follower's precomputed feed/timeline (often
stored as a per-user list of post IDs, e.g. in Redis — this repo's Redis
& Caching Notes covers this pattern). Reading a feed becomes TRIVIALLY
FAST (just fetch the current user's precomputed list) since all the
distribution work happened upfront, at post time — but the WRITE cost
scales with the poster's FOLLOWER COUNT: a user with 50 million followers
posting once means 50 million individual feed-list writes, all
triggered by ONE action.

FAN-OUT ON READ (pull model): a post is simply stored once; a user's
feed is COMPUTED ON DEMAND when they open the app, by querying "what have
everyone I follow posted recently" and merging/ranking the results at
READ time. This makes WRITES trivially cheap (one post, one write,
regardless of follower count) but makes READS potentially expensive —
computing a feed for a user following thousands of accounts requires
querying and merging content from all of them at that moment.

THE CELEBRITY PROBLEM is why pure fan-out-on-write breaks down at scale:
a celebrity account with tens of millions of followers would trigger tens
of millions of feed-list writes on every single post — this is a genuine,
well-documented scaling challenge (publicly discussed by Twitter/X
engineering) that makes PURE fan-out-on-write infeasible for
high-follower-count accounts specifically, even though it works well for
the "normal" user with a few hundred followers.

HYBRID APPROACH (what large platforms actually use): fan-out ON WRITE for
NORMAL users (most accounts have modest follower counts, making the
write cost manageable, and users benefit from instant feed reads), but
fan-out ON READ (or a special-cased, separate path) for HIGH-FOLLOWER-
COUNT accounts specifically — a follower's feed is then assembled by
COMBINING their precomputed (fan-out-on-write) feed with a live,
on-demand check of any celebrity accounts they follow, merged together
at read time. This hybrid captures fan-out-on-write's fast-read benefit
for the common case while avoiding its catastrophic write amplification
for the rare, high-follower-count case.

PRODUCTION USE CASE:
A social media platform uses fan-out on write for the vast majority of
users (each post triggers writes to a few hundred followers' feeds — a
manageable cost), but a celebrity account with 80 million followers is
flagged for a SEPARATE path: their posts are NOT pushed to every
follower's feed individually; instead, each follower's feed-read
operation separately checks "has this celebrity posted recently" and
merges that in at READ time — avoiding an 80-million-write cascade
triggered by a single post.

COMMON MISTAKES:
- Implementing PURE fan-out on write without a special case for
  high-follower-count accounts — this is the exact celebrity problem;
  a platform that grows to include even a FEW very-high-follower
  accounts can face a severe, sudden write-amplification problem if this
  isn't anticipated architecturally from early on.
- Implementing PURE fan-out on read without any precomputation — this
  makes EVERY feed load expensive (querying and merging potentially
  thousands of followed accounts' recent posts on every single app open),
  a poor tradeoff for the overwhelmingly common case of a normal user
  with a normal, bounded following list.
- Treating this as a ONE-TIME architectural decision made once and never
  revisited — as a platform grows and its distribution of follower counts
  shifts (more accounts crossing into "celebrity" territory over time),
  the THRESHOLD for which approach applies to which accounts may need
  to be re-tuned.
"""

from collections import defaultdict


# ------------------------------------------------------------------
# 1. Fan-out on write — precomputed feeds, fast reads, expensive writes
# ------------------------------------------------------------------
class FanOutOnWriteFeed:
    def __init__(self):
        self.follower_map: dict[str, list[str]] = {}   # user_id -> list of follower_ids
        self.precomputed_feeds: dict[str, list[str]] = defaultdict(list)

    def follow(self, follower_id: str, followed_id: str):
        self.follower_map.setdefault(followed_id, []).append(follower_id)

    def post(self, author_id: str, post_id: str):
        followers = self.follower_map.get(author_id, [])
        for follower_id in followers:
            # EVERY follower's feed gets an immediate write — cost scales
            # directly with follower count
            self.precomputed_feeds[follower_id].insert(0, post_id)
        return len(followers)   # number of writes this single post triggered

    def read_feed(self, user_id: str) -> list[str]:
        return self.precomputed_feeds[user_id]   # trivially fast — already computed


def fanout_on_write_demo():
    feed_system = FanOutOnWriteFeed()
    feed_system.follow("alice", "bob")
    feed_system.follow("charlie", "bob")

    writes_triggered = feed_system.post("bob", "post_1")
    print(f"Bob (2 followers) posts once -> {writes_triggered} feed writes triggered")
    print(f"Alice's feed: {feed_system.read_feed('alice')}")

    # Now simulate a "celebrity" with a huge follower count
    for i in range(50000):
        feed_system.follow(f"fan_{i}", "celebrity")
    writes_triggered = feed_system.post("celebrity", "celeb_post_1")
    print(f"\nCelebrity (50,000 followers) posts once -> "
          f"{writes_triggered:,} feed writes triggered")
    print("  -> This is the 'celebrity problem' — ONE action, tens of")
    print("     thousands of writes. At real platform scale (tens of")
    print("     MILLIONS of followers), this becomes a genuine bottleneck.")


# ------------------------------------------------------------------
# 2. Hybrid approach — write fan-out for normal users, read fan-out for celebrities
# ------------------------------------------------------------------
class HybridFeedSystem:
    CELEBRITY_THRESHOLD = 10_000

    def __init__(self):
        self.follower_map: dict[str, list[str]] = {}
        self.following_map: dict[str, list[str]] = defaultdict(list)
        self.precomputed_feeds: dict[str, list[str]] = defaultdict(list)
        self.celebrity_posts: dict[str, list[str]] = defaultdict(list)

    def follow(self, follower_id: str, followed_id: str):
        self.follower_map.setdefault(followed_id, []).append(follower_id)
        self.following_map[follower_id].append(followed_id)

    def is_celebrity(self, user_id: str) -> bool:
        return len(self.follower_map.get(user_id, [])) >= self.CELEBRITY_THRESHOLD

    def post(self, author_id: str, post_id: str):
        if self.is_celebrity(author_id):
            # Fan-out on READ: just store the post once, no per-follower writes
            self.celebrity_posts[author_id].insert(0, post_id)
            return 0
        else:
            followers = self.follower_map.get(author_id, [])
            for follower_id in followers:
                self.precomputed_feeds[follower_id].insert(0, post_id)
            return len(followers)

    def read_feed(self, user_id: str) -> list[str]:
        # Combine the PRECOMPUTED (fan-out-on-write) feed with a LIVE
        # check of any celebrities this user follows
        feed = list(self.precomputed_feeds[user_id])
        for followed_id in self.following_map[user_id]:
            if self.is_celebrity(followed_id):
                feed = self.celebrity_posts[followed_id][:5] + feed   # merge in recent celeb posts
        return feed


def hybrid_demo():
    system = HybridFeedSystem()
    system.follow("alice", "bob")
    for i in range(15000):
        system.follow(f"fan_{i}", "celebrity")
    system.follow("alice", "celebrity")   # alice follows BOTH a normal user and a celebrity

    writes_for_bob = system.post("bob", "bob_post_1")
    writes_for_celeb = system.post("celebrity", "celeb_post_1")

    print(f"\nHybrid system: Bob's post triggered {writes_for_bob} writes")
    print(f"Celebrity's post triggered {writes_for_celeb} writes (merged at READ time instead)")
    print(f"Alice's merged feed: {system.read_feed('alice')}")
    print("  -> Alice's feed correctly includes BOTH posts, combining a")
    print("     precomputed write-time feed with a live read-time merge —")
    print("     avoiding the celebrity write-amplification problem entirely.")


if __name__ == "__main__":
    fanout_on_write_demo()
    hybrid_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
Twitter/X's publicly-documented feed architecture uses fan-out on write
for the vast majority of accounts, but explicitly special-cases very-
high-follower-count accounts to avoid the celebrity write-amplification
problem — a regular user's feed is a blend of their own precomputed
timeline (built from normal accounts they follow) merged, at read time,
with live checks against any celebrity accounts they follow — this
hybrid is directly why the platform can support both "instant feed
loads for typical users" and "accounts with 100+ million followers"
simultaneously without either use case degrading the other.
"""
