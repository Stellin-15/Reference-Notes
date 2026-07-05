# ============================================================
# L12: Music Recommendation Systems — How Spotify Builds "Discover Weekly"
# ============================================================
# WHAT: The core recommendation-system techniques behind personalized
#       music discovery — collaborative filtering, content-based
#       filtering, and how they're combined, plus the specific
#       "cold start" problem for new/unpopular tracks.
# WHY: This repo's ML Frameworks Notes and Data Science Fundamentals
#      Notes cover the underlying math (vectors, similarity, matrix
#      factorization) in the abstract — this lesson applies it to a
#      concrete, well-known product feature end to end.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
COLLABORATIVE FILTERING recommends based on the PATTERN OF WHO LISTENS TO
WHAT, without needing to understand the content itself: "users who
listened to track A also frequently listened to track B" — MATRIX
FACTORIZATION (this repo's Data Science Fundamentals Notes L05 covers the
underlying linear algebra) is a common implementation: represent the
user-track listening matrix (millions of users × millions of tracks,
overwhelmingly SPARSE — most users haven't listened to most tracks) as
the product of two much SMALLER matrices (user embeddings × track
embeddings) — a user's predicted affinity for a track becomes the DOT
PRODUCT (Data Science Fundamentals Notes L05) of that user's and that
track's learned embedding vectors.

CONTENT-BASED FILTERING recommends based on the ACTUAL AUDIO/METADATA
CHARACTERISTICS of tracks — audio features (tempo, energy, acousticness,
danceability — extracted via audio signal processing) and metadata
(genre, artist, era) let the system recommend tracks SIMILAR in
CHARACTER to what a user already likes, even for tracks with very little
listening history to learn a collaborative signal from. This is what
solves collaborative filtering's fundamental weakness.

THE COLD START PROBLEM is collaborative filtering's core limitation: a
BRAND NEW track has NO listening history yet, so "users who listened to
this also listened to..." has no data to work with — content-based
filtering (audio/metadata similarity to already-popular, already-
understood tracks) is what lets a genuinely new release get recommended
to a relevant audience from day one, before it's accumulated enough
plays for collaborative signals to kick in. A similar cold-start problem
exists for BRAND NEW USERS (no listening history at all) — commonly
addressed with an onboarding flow (asking new users to pick a few
favorite artists/genres) that provides an initial signal before
sufficient organic listening history accumulates.

HYBRID SYSTEMS combine both approaches, typically weighting collaborative
signals more heavily for well-established tracks/users (where that data
is rich and reliable) and content-based signals more heavily for new
tracks/users (where collaborative data is sparse or absent) — Spotify's
actual recommendation stack (as described in public engineering
writeups) combines collaborative filtering, audio content analysis
(via CNN-based audio feature extraction), and NLP analysis of text
associated with tracks (blog posts, playlist titles/descriptions
mentioning them) as additional signals beyond pure listening-pattern data.

PRODUCTION USE CASE:
Spotify's "Discover Weekly" playlist for an individual user is generated
by combining: collaborative filtering signals from users with similar
listening taste (using matrix-factorization-derived embeddings),
content-based similarity to tracks the user has already favorited (using
audio feature vectors), and diversity constraints (avoiding recommending
20 nearly-identical tracks even if they'd all individually score well) —
regenerated weekly as a batch job rather than computed in real time on
every app open, since listening-history-derived recommendations don't
need to reflect changes more frequently than that for this specific feature.

COMMON MISTAKES:
- Relying purely on collaborative filtering without a content-based
  fallback — this systematically UNDER-RECOMMENDS new and niche content,
  since collaborative signals require accumulated listening history that
  new/niche tracks haven't had time or exposure to build up.
- Optimizing purely for PREDICTED LISTENING PROBABILITY without a
  diversity constraint — a naive top-N recommendation can produce a
  playlist of 20 nearly-identical tracks (all by the same artist, all
  the same sub-genre) that technically each score well individually but
  produce a poor, repetitive overall listening experience.
- Treating the cold-start problem as solved once a system has SOME
  fallback (e.g. "just recommend generically popular tracks to new
  users") — a generic popularity-based fallback is a poor substitute for
  genuinely using WHATEVER signal is actually available (onboarding
  genre/artist selections, audio content similarity) even in the earliest
  moments of a new user's or new track's lifecycle.
"""

import math


# ------------------------------------------------------------------
# 1. Collaborative filtering via matrix factorization (simplified)
# ------------------------------------------------------------------
def dot_product(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def collaborative_filtering_demo():
    # Simplified learned embeddings (in reality, learned via gradient
    # descent on observed listening data — Data Science Fundamentals
    # Notes L04's optimization fundamentals underlie this training process)
    user_embeddings = {
        "alice": [0.9, 0.1, 0.7],   # high affinity for dims 1 and 3 (e.g. "energetic", "pop")
        "bob": [0.1, 0.9, 0.2],     # high affinity for dim 2 (e.g. "acoustic")
    }
    track_embeddings = {
        "upbeat_pop_song": [0.85, 0.15, 0.75],
        "acoustic_ballad": [0.15, 0.85, 0.25],
    }

    for user, u_vec in user_embeddings.items():
        print(f"{user}'s predicted affinity:")
        for track, t_vec in track_embeddings.items():
            affinity = dot_product(u_vec, t_vec)
            print(f"  {track}: {affinity:.2f}")
        print()


# ------------------------------------------------------------------
# 2. Content-based filtering — audio feature similarity
# ------------------------------------------------------------------
def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = dot_product(a, b)
    mag_a = math.sqrt(sum(x ** 2 for x in a))
    mag_b = math.sqrt(sum(x ** 2 for x in b))
    return dot / (mag_a * mag_b)


def content_based_cold_start_demo():
    # Audio feature vectors: [tempo(normalized), energy, acousticness]
    brand_new_track = {"name": "New Release (0 plays)", "features": [0.8, 0.75, 0.1]}
    catalog = {
        "established_upbeat_hit": [0.82, 0.7, 0.15],   # very similar audio profile
        "established_acoustic_hit": [0.2, 0.3, 0.9],   # very different audio profile
    }

    print(f"Brand new track with ZERO listening history: '{brand_new_track['name']}'")
    print("Collaborative filtering has NO signal for it yet — falling back")
    print("to CONTENT-BASED similarity against already-understood tracks:\n")
    for track_name, features in catalog.items():
        similarity = cosine_similarity(brand_new_track["features"], features)
        print(f"  Audio similarity to '{track_name}': {similarity:.3f}")
    print("\n  -> The new track can be recommended to fans of the audio-similar")
    print("     established hit IMMEDIATELY, without waiting for its own")
    print("     listening history to accumulate.")


# ------------------------------------------------------------------
# 3. Diversity-aware re-ranking
# ------------------------------------------------------------------
def diversity_aware_selection(candidates: list[dict], max_per_artist: int = 1) -> list[dict]:
    selected = []
    artist_counts: dict[str, int] = {}
    # Assumes candidates are already sorted by predicted affinity, descending
    for track in candidates:
        artist = track["artist"]
        if artist_counts.get(artist, 0) < max_per_artist:
            selected.append(track)
            artist_counts[artist] = artist_counts.get(artist, 0) + 1
    return selected


def diversity_demo():
    ranked_candidates = [
        {"track": "Song A", "artist": "Artist X", "score": 0.95},
        {"track": "Song B", "artist": "Artist X", "score": 0.93},   # same artist as A
        {"track": "Song C", "artist": "Artist Y", "score": 0.90},
        {"track": "Song D", "artist": "Artist X", "score": 0.88},   # same artist again
        {"track": "Song E", "artist": "Artist Z", "score": 0.85},
    ]
    final_playlist = diversity_aware_selection(ranked_candidates, max_per_artist=1)
    print("Without diversity constraint, top-3 by raw score would be all Artist X songs.")
    print(f"With a max-1-per-artist constraint: {[t['track'] for t in final_playlist]}")


if __name__ == "__main__":
    collaborative_filtering_demo()
    content_based_cold_start_demo()
    print()
    diversity_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
An independent artist releases a new single with zero prior listening
history — Spotify's recommendation system uses CONTENT-BASED audio
feature similarity (tempo, energy, instrumentation) to surface it to
listeners who've engaged heavily with audio-similar, already-popular
tracks, generating early plays; once those initial plays accumulate,
COLLABORATIVE FILTERING signals (who ELSE who listened to this also
listens to) kick in and progressively take over as the dominant
recommendation signal — a smooth handoff between the two techniques that
solves the cold-start problem without ever requiring a separate,
manually-triggered "promote new content" mechanism.
"""
