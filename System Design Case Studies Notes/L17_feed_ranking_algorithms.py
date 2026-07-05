# ============================================================
# L17: Feed Ranking Algorithms — How "Hot," "Best," and "Top" Actually Work
# ============================================================
# WHAT: The actual mathematical formulas behind Reddit's ranking
#       algorithms — "Hot" (time-decayed popularity), "Best" (a
#       confidence-interval-based score using the actual vote COUNT, not
#       just the ratio), and "Top" (raw score) — and why each exists as
#       a DISTINCT option rather than one "best" ranking.
# WHY: L16 covered STORING comments; this lesson covers the actual
#      ALGORITHM that decides what order to show them (or posts) in —
#      arguably the single most consequential piece of product logic
#      in a content-ranking platform.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
"HOT" ranking combines a post's SCORE (upvotes minus downvotes) with its
AGE, such that a post's rank naturally DECAYS over time even without new
votes — Reddit's actual published "hot" formula takes roughly the form:
  hot_score = log10(max(|score|, 1)) * sign(score) + (seconds_since_epoch / 45000)
The LOGARITHM of the score means the DIFFERENCE between 10 and 100 votes
matters much more than the difference between 1,000 and 1,090 votes —
early votes have an outsized impact on ranking relative to later ones at
the same absolute vote count, which is DELIBERATE: it lets genuinely
good NEW content compete for visibility against older content that's
merely accumulated a larger absolute vote count over more time. The time
term ensures that, all else equal, a NEWER post ranks higher than an
otherwise-identical older post — this is what makes a "hot" feed feel
fresh rather than permanently dominated by whatever got popular first.

"BEST" (or "Confidence" — Reddit's actual name for this ranking)
addresses a specific flaw in naively ranking by UPVOTE RATIO alone: a
comment with 1 upvote and 0 downvotes (100% ratio) would rank ABOVE a
comment with 999 upvotes and 1 downvote (99.9% ratio) under pure-ratio
ranking — clearly wrong, since the second comment has vastly more
evidence supporting its quality. Reddit's "Best" algorithm instead
computes a WILSON SCORE CONFIDENCE INTERVAL LOWER BOUND on the "true"
upvote proportion — a statistical technique (connecting directly to this
repo's Data Science Fundamentals Notes L02 statistical inference) that
accounts for SAMPLE SIZE: with few votes, the confidence interval is
WIDE (so even a 100% ratio's LOWER bound is modest), while with many
votes, the interval NARROWS (so a high ratio with many votes gets a
justifiably high, confident score) — this single change fixes the
small-sample-size ranking problem entirely.

"TOP" ranking is simply RAW SCORE (or score within a specific time
window — "top today," "top this week") with NO time decay — appropriate
specifically for a user who wants to see the MOST validated content
overall, rather than what's currently freshly popular; this is why
platforms offer it as a genuinely DIFFERENT, separate sort option rather
than trying to have one universal ranking serve every use case.

WHY MULTIPLE RANKING OPTIONS EXIST AT ALL: "Hot," "Best," and "Top" serve
GENUINELY DIFFERENT user intents (what's currently active/interesting vs
what's most reliably high-quality vs what's the all-time best) — a
single ranking algorithm cannot serve all three intents well
simultaneously, which is why offering multiple, clearly-differentiated
sort options is a deliberate product decision, not redundancy.

PRODUCTION USE CASE:
A comment posted 2 minutes ago with 3 upvotes and 0 downvotes appears
ABOVE a comment posted 2 hours ago with 45 upvotes and 2 downvotes under
"New" sort (obviously, by definition), BELOW it under "Top" (raw score:
3 vs 43), but the RELATIVE ordering under "Best" specifically depends on
the Wilson score calculation weighing the OLDER comment's much larger
sample size (47 total votes) against its slightly lower ratio,
typically still ranking it above the newer comment's high-ratio-but-tiny-sample score.

COMMON MISTAKES:
- Ranking purely by UPVOTE RATIO/PERCENTAGE — this systematically
  over-ranks content with very few total votes (a 1-upvote, 0-downvote
  comment isn't more reliably "good" than a 999-upvote, 1-downvote
  comment, despite having a higher raw ratio) — the Wilson score
  interval specifically corrects for this by accounting for sample size.
- Using a LINEAR (not logarithmic) score in a time-decay ranking formula
  — this would let raw vote-count differences (1000 vs 1090 votes)
  dominate the ranking as much as smaller, often more meaningful early
  differences (10 vs 100 votes), working against the goal of letting
  fresh, genuinely good content compete for visibility.
- Offering only ONE ranking algorithm and assuming it satisfies every
  user need — "what's hot right now" and "what's the best content ever
  posted here" are legitimately different questions that deserve
  different, clearly-labeled ranking options rather than a single
  compromise formula trying to serve both.
"""

import math
import time


# ------------------------------------------------------------------
# 1. "Hot" ranking — time-decayed, log-scaled score
# ------------------------------------------------------------------
def hot_score(upvotes: int, downvotes: int, posted_timestamp: float) -> float:
    score = upvotes - downvotes
    order = math.log10(max(abs(score), 1))
    sign = 1 if score > 0 else (-1 if score < 0 else 0)
    seconds_since_epoch = posted_timestamp
    return round(sign * order + seconds_since_epoch / 45000, 7)


def hot_ranking_demo():
    now = time.time()
    posts = [
        {"name": "New post, few votes", "upvotes": 15, "downvotes": 2,
         "posted": now - 300},               # posted 5 minutes ago
        {"name": "Old post, many votes", "upvotes": 3000, "downvotes": 400,
         "posted": now - 86400 * 3},          # posted 3 days ago
    ]
    for post in posts:
        score = hot_score(post["upvotes"], post["downvotes"], post["posted"])
        print(f"  {post['name']}: hot_score={score:.2f}")
    print("  -> The LOGARITHM means the new post's smaller vote count still")
    print("     competes meaningfully against the old post's much larger")
    print("     absolute count, while the TIME term still favors freshness.")


# ------------------------------------------------------------------
# 2. "Best" ranking — Wilson score confidence interval lower bound
# ------------------------------------------------------------------
def wilson_score_lower_bound(upvotes: int, downvotes: int, z: float = 1.96) -> float:
    n = upvotes + downvotes
    if n == 0:
        return 0.0
    p_hat = upvotes / n
    # The Wilson score interval's LOWER bound — this repo's Data Science
    # Fundamentals Notes L02 covers the confidence-interval math this builds on
    numerator = p_hat + z * z / (2 * n) - z * math.sqrt(
        (p_hat * (1 - p_hat) + z * z / (4 * n)) / n
    )
    denominator = 1 + z * z / n
    return numerator / denominator


def best_ranking_demo():
    comments = [
        {"name": "Tiny sample, perfect ratio", "upvotes": 1, "downvotes": 0},
        {"name": "Large sample, near-perfect ratio", "upvotes": 999, "downvotes": 1},
    ]
    print("\nRaw upvote ratio vs Wilson score lower bound ('Best' ranking):")
    for c in comments:
        ratio = c["upvotes"] / (c["upvotes"] + c["downvotes"])
        wilson = wilson_score_lower_bound(c["upvotes"], c["downvotes"])
        print(f"  {c['name']}: raw ratio={ratio:.3f}, Wilson lower bound={wilson:.3f}")
    print("  -> Raw ratio ranks the TINY sample above the LARGE sample —")
    print("     clearly wrong. The Wilson score correctly ranks the large,")
    print("     well-evidenced sample HIGHER despite its marginally lower ratio.")


if __name__ == "__main__":
    hot_ranking_demo()
    best_ranking_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A brand-new, genuinely insightful comment posted minutes ago with only 4
upvotes competes for visibility on "Best" sort against a mediocre
comment from hours earlier sitting at 40 upvotes/8 downvotes — the
Wilson score calculation correctly weighs the older comment's larger,
more statistically confident sample against the newer comment's tiny
sample size, typically keeping the well-evidenced older comment ranked
higher UNLESS the newer comment's ratio is dramatically better — this
exact tension (fresh content vs well-evidenced content) is why Reddit
maintains "Hot," "Best," and "Top" as genuinely separate ranking modes
rather than trying to collapse them into one universal score.
"""
