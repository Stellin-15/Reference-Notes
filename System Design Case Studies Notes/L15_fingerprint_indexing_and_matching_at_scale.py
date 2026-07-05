# ============================================================
# L15: Fingerprint Indexing and Matching at Scale — Capstone of the Shazam Case Study
# ============================================================
# WHAT: How Shazam matches a query clip's fingerprint hashes (L14)
#       against a reference database of tens of millions of songs in
#       near-real-time — the inverted-index structure and the
#       time-offset-histogram voting scheme that confirms a true match.
# WHY: Capstone lesson for the Shazam case study — L14 covered
#      generating a ROBUST fingerprint; this lesson covers making
#      MATCHING that fingerprint against a massive catalog fast and
#      accurate, completing the end-to-end system.
# LEVEL: Advanced (capstone of this case study)
# ============================================================

"""
CONCEPT OVERVIEW:
AN INVERTED INDEX (this repo's Full-Stack & Frontend Essentials Notes L07
covers this same core concept in Elasticsearch's context) is exactly the
right structure for fingerprint matching: instead of comparing a query's
hashes against every song's hashes one by one (which would be far too
slow across tens of millions of songs), a REFERENCE INDEX is built ahead
of time mapping EACH POSSIBLE HASH VALUE to the list of (song ID, time
offset) pairs where that hash occurs across the ENTIRE catalog — a query
hash lookup becomes a fast, direct index lookup ("which songs contain
this exact hash, and at what time offset") rather than a slow
comparison against every song individually.

TIME-OFFSET HISTOGRAM VOTING is the key insight that turns "many
candidate matches" into "one confirmed match": a query clip generates
MANY hashes (L14), and each hash lookup may return MULTIPLE candidate
songs (since a specific hash value isn't necessarily unique to one song)
— for EACH candidate song, the algorithm computes the TIME OFFSET
DIFFERENCE (reference song's time - query clip's time) for every
matching hash. If the query clip is TRULY from that song, ALL of these
offset differences will cluster around the SAME value (the actual
position in the song where the clip started) — while for an unrelated,
coincidentally-matching song, the offset differences will be essentially
RANDOM/scattered. The song with the strongest CLUSTERING (a histogram
of offset differences with one dominant, sharp peak) is the confirmed match.

WHY THIS SCALES: unlike comparing raw audio (computationally expensive
per comparison, and requiring comparison against every candidate), the
inverted-index lookup is O(1)-ish per hash (a direct index lookup), and
the histogram-voting step only needs to process the relatively SMALL
number of candidate songs that share ANY hash with the query — the vast
majority of the catalog (songs sharing ZERO hashes with the query) is
never even considered, which is what makes matching against tens of
millions of songs feasible in a few seconds on modest server hardware.

FALSE POSITIVE REJECTION: a candidate song with only a WEAK, scattered
histogram (no clear dominant peak) despite matching SOME hashes is
correctly rejected as a coincidental match rather than a true one — the
STRENGTH of the histogram's peak (how many hashes support the SAME
consistent time offset, relative to background/noise matches) is the
actual confidence signal, not merely "did any hashes match at all."

PRODUCTION USE CASE:
Shazam receives a query clip's hashes from a user's phone, looks each
hash up in its inverted index, and finds that hash "f1=440|f2=660|dt=2"
(from L14) appears in reference fingerprints for songs A, B, and C — for
each candidate, it computes the offset histogram: song A's matching
hashes all cluster around a consistent offset (STRONG match — CONFIRMED
as the identified song); songs B and C's matching hashes are scattered
across many different offsets (WEAK, coincidental matches — correctly rejected).

COMMON MISTAKES:
- Treating "the query has ANY matching hash with a candidate song" as
  sufficient evidence of a match — with tens of millions of songs and a
  hash space that isn't perfectly collision-free, SOME coincidental hash
  matches against unrelated songs are inevitable; the histogram-voting
  step's CLUSTERING check is what actually distinguishes a true match
  from coincidental noise.
- Building a linear-scan matching system (comparing the query against
  every song's fingerprint sequentially) rather than an inverted index —
  this fundamentally cannot scale to a catalog of tens of millions of
  songs within an acceptable response-time budget for an interactive,
  user-facing feature.
- Not accounting for the fact that a SINGLE hash value can legitimately
  appear in MANY different songs (hash collisions are expected, not a
  bug) — the system's correctness relies on the AGGREGATE clustering
  pattern across many hashes, not on any single hash being uniquely identifying.
"""

from collections import defaultdict


# ------------------------------------------------------------------
# 1. Building the inverted index (offline, ahead of time)
# ------------------------------------------------------------------
def build_reference_index(reference_fingerprints: dict[str, list[dict]]) -> dict:
    """reference_fingerprints: {song_id: [{"hash": ..., "anchor_time": ...}, ...]}"""
    inverted_index = defaultdict(list)
    for song_id, hashes in reference_fingerprints.items():
        for h in hashes:
            inverted_index[h["hash"]].append((song_id, h["anchor_time"]))
    return inverted_index


# ------------------------------------------------------------------
# 2. Matching a query via inverted-index lookup + histogram voting
# ------------------------------------------------------------------
def match_query(query_hashes: list[dict], inverted_index: dict) -> str | None:
    # For each candidate song, track the offset (reference_time - query_time)
    # for every matching hash — this is the raw material for the histogram
    offset_histograms: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    for query_hash_entry in query_hashes:
        query_hash = query_hash_entry["hash"]
        query_time = query_hash_entry["anchor_time"]

        # INVERTED INDEX LOOKUP — fast, direct, not a scan over the whole catalog
        matching_entries = inverted_index.get(query_hash, [])
        for song_id, reference_time in matching_entries:
            offset = reference_time - query_time
            offset_histograms[song_id][offset] += 1

    # Find the song with the STRONGEST single-offset peak (the clustering signal)
    best_song, best_peak_count = None, 0
    for song_id, histogram in offset_histograms.items():
        peak_count = max(histogram.values())
        if peak_count > best_peak_count:
            best_song, best_peak_count = song_id, peak_count

    # Require a MINIMUM peak strength to reject weak/coincidental matches
    MIN_CONFIDENCE_THRESHOLD = 3
    if best_peak_count >= MIN_CONFIDENCE_THRESHOLD:
        return best_song
    return None


def matching_demo():
    # Reference fingerprints for three songs — song_a is the TRUE match;
    # songs b and c share a FEW coincidental hashes but at scattered offsets
    reference_fingerprints = {
        "song_a (true match)": [
            {"hash": "f1=440|f2=660|dt=2", "anchor_time": 50},
            {"hash": "f1=220|f2=440|dt=1", "anchor_time": 51},
            {"hash": "f1=880|f2=990|dt=3", "anchor_time": 53},
        ],
        "song_b (coincidental)": [
            {"hash": "f1=440|f2=660|dt=2", "anchor_time": 12},   # shares ONE hash
        ],
        "song_c (coincidental)": [
            {"hash": "f1=220|f2=440|dt=1", "anchor_time": 200},  # shares ONE hash
        ],
    }
    index = build_reference_index(reference_fingerprints)

    # Query clip's hashes — happens to start at query time 0 (an ARBITRARY
    # point relative to the reference song, which started matching hashes
    # at reference times 50, 51, 53 — a CONSISTENT offset of ~50)
    query_hashes = [
        {"hash": "f1=440|f2=660|dt=2", "anchor_time": 0},
        {"hash": "f1=220|f2=440|dt=1", "anchor_time": 1},
        {"hash": "f1=880|f2=990|dt=3", "anchor_time": 3},
    ]

    result = match_query(query_hashes, index)
    print(f"Query matched to: {result}")
    print("\n  -> song_a's three hashes ALL support the SAME offset (~50),")
    print("     a strong clustering signal. song_b and song_c each only")
    print("     share ONE coincidental hash with NO clustering support —")
    print("     correctly rejected as non-matches despite technically")
    print("     appearing in the inverted index lookup results.")


if __name__ == "__main__":
    matching_demo()

"""
FINAL CONTEXT (capstone of the Shazam case study):
The complete pipeline across L14-L15: a noisy few-second clip is
converted into a sparse, noise-robust set of time-translation-invariant
peak-pair hashes (L14); those hashes are looked up in an inverted index
built ahead of time across tens of millions of reference songs, and a
time-offset histogram-voting scheme distinguishes the one TRUE match
from coincidental hash collisions with other songs (L15) — the entire
system runs in a few seconds on commodity infrastructure specifically
because both steps were designed around the SAME underlying constraint:
avoid ever needing to do expensive, direct comparison against the full catalog.
"""
