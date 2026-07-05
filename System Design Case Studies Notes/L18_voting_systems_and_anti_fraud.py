# ============================================================
# L18: Voting Systems and Anti-Fraud — Making Votes Fast, Consistent, and Honest
# ============================================================
# WHAT: How a voting system handles massive concurrent write volume on a
#       single popular post's vote counter WITHOUT losing votes or
#       double-counting, plus the fraud-detection techniques that
#       prevent vote manipulation (brigading, bot voting).
# WHY: L17 covered the RANKING FORMULAS that consume vote counts. This
#      lesson covers the harder INFRASTRUCTURE problem underneath them:
#      a viral post can receive thousands of votes per SECOND, and the
#      count must remain accurate and resistant to manipulation.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
A NAIVE VOTE COUNTER (a single database row with an integer column,
incremented/decremented directly via `UPDATE posts SET score = score + 1`)
becomes a WRITE HOTSPOT under high concurrent vote volume — thousands of
simultaneous UPDATE statements against the SAME row create severe LOCK
CONTENTION in most relational databases, since each write must wait for
the previous one to release its lock on that row, creating an effective
GLOBAL bottleneck on how fast votes can be recorded for one specific viral post.

EVENT-SOURCED VOTE LOGGING (write each individual vote as an INDEPENDENT
event/row, rather than mutating a shared counter) sidesteps this
bottleneck entirely: each vote is an INSERT into a votes table (or an
append to an event log/stream, this repo's Apache Kafka Notes and
Event-Driven & Real-Time AI Systems Notes cover this general pattern) —
inserts to a table don't contend with each other the way updates to the
SAME row do. The aggregate score is then computed by SUMMING these
events, either on read (fine for moderate volume) or via a periodic/
streaming AGGREGATION job that maintains a cached, eventually-consistent
running total — trading immediate consistency for dramatically higher
write throughput, an acceptable tradeoff since a vote count being
technically a few seconds stale is imperceptible to users.

IDEMPOTENT VOTING (one user, one vote per post) requires the vote record
to be keyed by (user_id, post_id) with a uniqueness constraint — a user's
SECOND click on "upvote" should UPDATE their existing vote record (or
toggle it off) rather than creating a duplicate — this is a correctness
requirement distinct from, but related to, the write-scaling problem above.

BRIGADING AND BOT-VOTE DETECTION is a genuine adversarial problem:
BRIGADING (a coordinated group manipulating a post's votes, often
organized off-platform) and BOT VOTING (automated accounts voting
en masse) both need distinct detection signals: unusually SYNCHRONIZED
voting timing (many votes arriving within an implausibly narrow time
window from otherwise-unrelated accounts), ACCOUNT AGE/HISTORY anomalies
(a burst of votes disproportionately from very-new or previously-
inactive accounts), and IP/DEVICE clustering (many votes from accounts
sharing suspicious network/device fingerprints) — platforms typically
apply VOTE WEIGHT REDUCTION or DELAYED/HIDDEN vote counting for
suspicious patterns rather than outright vote deletion, since false
positives (incorrectly suppressing genuine grassroots enthusiasm) carry
their own real cost.

PRODUCTION USE CASE:
A post goes viral and receives 50,000 votes within 10 minutes — Reddit's
voting infrastructure records each vote as an independent, fast INSERT
event rather than contending on a single shared counter row, while a
separate aggregation process periodically recomputes the post's
displayed score from these events — and simultaneously, anomaly
detection flags an unusual cluster of votes arriving within a
suspiciously narrow few-second window from accounts created the same
day, triggering a vote-weight reduction for that specific cluster while
leaving the post's overwhelming majority of legitimate votes unaffected.

COMMON MISTAKES:
- Using a single mutable counter column updated via UPDATE statements for
  a high-traffic post's vote count — this creates a genuine, measurable
  write bottleneck specifically for the platform's MOST popular (and
  therefore most important to handle well) content.
- Detecting vote fraud ONLY by absolute vote count or ratio anomalies,
  without considering TIMING clustering or account-age signals — a
  coordinated brigading campaign can produce a vote count/ratio that
  looks individually unremarkable while still being a coordinated
  manipulation, distinguishable mainly through timing/account-pattern signals.
- Responding to detected vote manipulation by outright DELETING flagged
  votes silently — this both risks false positives being unrecoverable
  and provides no transparency/appeals path; weight reduction or
  visible flagging is often a more defensible middle ground for a
  system operating at scale with imperfect fraud-detection precision.
"""

import time
from collections import defaultdict


# ------------------------------------------------------------------
# 1. Event-sourced voting — avoiding a hot-row bottleneck
# ------------------------------------------------------------------
class EventSourcedVoteStore:
    def __init__(self):
        self.vote_events: list[dict] = []          # append-only — no shared row to contend on
        self.user_votes: dict[tuple, int] = {}       # (user_id, post_id) -> current vote value

    def cast_vote(self, user_id: str, post_id: str, value: int, timestamp: float):
        key = (user_id, post_id)
        previous_value = self.user_votes.get(key, 0)

        # IDEMPOTENT: a repeated vote from the same user UPDATES their
        # existing vote rather than creating an independent duplicate
        if previous_value == value:
            return   # no-op: clicking upvote twice doesn't double-count

        self.user_votes[key] = value
        # The EVENT itself is an independent append — this is what avoids
        # lock contention on a shared counter under high concurrent volume
        self.vote_events.append({
            "user_id": user_id, "post_id": post_id,
            "delta": value - previous_value, "timestamp": timestamp,
        })

    def current_score(self, post_id: str) -> int:
        return sum(e["delta"] for e in self.vote_events if e["post_id"] == post_id)


def event_sourced_voting_demo():
    store = EventSourcedVoteStore()
    store.cast_vote("user_1", "post_A", value=1, timestamp=time.time())
    store.cast_vote("user_2", "post_A", value=1, timestamp=time.time())
    store.cast_vote("user_1", "post_A", value=1, timestamp=time.time())   # repeat click — no-op
    store.cast_vote("user_3", "post_A", value=-1, timestamp=time.time())

    print(f"Vote events recorded: {len(store.vote_events)}")
    print(f"Current score for post_A: {store.current_score('post_A')}")
    print("  -> Each vote was an independent event append; the repeated")
    print("     click from user_1 correctly did NOT double-count.")


# ------------------------------------------------------------------
# 2. Brigading detection — timing clustering + account age signals
# ------------------------------------------------------------------
def detect_suspicious_vote_cluster(votes: list[dict], time_window_seconds: float = 5.0,
                                    min_cluster_size: int = 5) -> list[dict]:
    votes_sorted = sorted(votes, key=lambda v: v["timestamp"])
    suspicious_clusters = []

    for i in range(len(votes_sorted)):
        window = [v for v in votes_sorted[i:]
                  if v["timestamp"] - votes_sorted[i]["timestamp"] <= time_window_seconds]
        if len(window) >= min_cluster_size:
            new_account_count = sum(1 for v in window if v["account_age_days"] < 1)
            if new_account_count / len(window) > 0.6:   # majority are suspiciously new accounts
                suspicious_clusters.append({
                    "window_start": votes_sorted[i]["timestamp"],
                    "cluster_size": len(window),
                    "new_account_fraction": new_account_count / len(window),
                })
    return suspicious_clusters


def brigading_detection_demo():
    now = time.time()
    votes = (
        # A cluster of votes from very-new accounts, all within 3 seconds
        [{"timestamp": now + i * 0.5, "account_age_days": 0.2} for i in range(6)]
        # Plus normal, organic votes spread over a longer period from established accounts
        + [{"timestamp": now + 100 + i * 30, "account_age_days": 400} for i in range(4)]
    )

    suspicious = detect_suspicious_vote_cluster(votes)
    print(f"\nDetected {len(suspicious)} suspicious vote cluster(s):")
    for cluster in suspicious:
        print(f"  {cluster}")
    print("  -> Flagged based on BOTH timing clustering (many votes in a")
    print("     tiny window) AND account-age anomaly — either signal alone")
    print("     could occur naturally; the COMBINATION is the strong signal.")


if __name__ == "__main__":
    event_sourced_voting_demo()
    brigading_detection_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
During a major news event, a related Reddit post receives an enormous,
GENUINE surge of organic votes within minutes — the event-sourced voting
architecture handles this write volume without the lock contention a
naive shared-counter design would suffer, while the SAME infrastructure
correctly distinguishes this legitimate surge (votes spread across
accounts of all ages, arriving somewhat but not suspiciously
synchronized due to genuinely shared timing of the news event) from an
actual brigading attempt on an unrelated post (a tight vote cluster
disproportionately from newly-created accounts) — the anti-fraud system
must correctly tell these two superficially similar "sudden vote surge" patterns apart.
"""
