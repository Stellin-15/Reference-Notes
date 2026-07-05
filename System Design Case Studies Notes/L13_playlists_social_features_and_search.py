# ============================================================
# L13: Playlists, Social Features, and Search — Capstone of the Spotify Case Study
# ============================================================
# WHAT: How collaborative playlists are stored and synced across
#       multiple editors, how social features (following, activity feeds)
#       are layered on top, and how full-text search over a massive
#       music catalog is actually built.
# WHY: Capstone lesson for the Spotify case study — L11 covered
#      streaming delivery, L12 covered recommendations; this lesson
#      covers the remaining major subsystems (collaborative playlists,
#      social graph, search) that complete the picture.
# LEVEL: Intermediate (capstone of this case study)
# ============================================================

"""
CONCEPT OVERVIEW:
COLLABORATIVE PLAYLISTS (multiple users adding/removing/reordering
tracks in the SAME shared playlist) face a SIMPLER version of the
Google Docs case study's problem (L06-L07): unlike character-level text
editing, playlist operations are naturally COARSER-GRAINED (add track,
remove track, reorder) and less frequently truly CONCURRENT (two people
rarely add a track to the exact same position within the same second) —
this means a simpler LAST-WRITE-WINS or OPERATION-LOG approach (append
each add/remove/reorder as an event, replay in a defined order) is
often sufficient, without needing the full CRDT/OT machinery L06-L07
built for fine-grained concurrent text editing.

PLAYLIST ORDERING under concurrent edits still needs care: representing
track order as a simple integer INDEX (position 1, 2, 3...) means
inserting a track in the middle requires re-indexing every subsequent
track — a common alternative is FRACTIONAL/LEXICAL ORDERING (storing an
order key like a string or float BETWEEN the two neighboring tracks'
keys, e.g. inserting between position "a" and "b" as "am"), letting an
insert happen with a SINGLE new record rather than re-writing every
subsequent track's position — this avoids both the re-indexing cost and
reduces the chance of two concurrent inserts needing to touch the same
records.

THE SOCIAL GRAPH (following artists, other users, seeing friends'
activity) is architecturally a instance of a general FOLLOWER/FOLLOWING
graph — directly connecting to this domain's L19 (fan-out on write vs
read), since "what are my followed friends currently listening to"
faces the exact same fan-out tradeoff as a social media feed.

FULL-TEXT SEARCH over a catalog of tens of millions of tracks/artists/
albums/podcasts needs an INVERTED INDEX (this repo's Full-Stack &
Frontend Essentials Notes L07 covers Elasticsearch's implementation in
depth) — critically, music search has DOMAIN-SPECIFIC needs beyond
generic text search: FUZZY MATCHING for misspelled artist names,
PHONETIC matching (searching "Beyonce" should find "Beyoncé"), and
POPULARITY-WEIGHTED ranking (a search for an ambiguous, short query term
should favor well-known, popular matches over obscure ones with a
technically-closer text match).

PRODUCTION USE CASE:
A group of friends collaboratively builds a road-trip playlist, each
adding tracks from their own phone simultaneously — each addition is
appended as an independent event to the playlist's operation log with a
FRACTIONAL order key, avoiding any need to coordinate/lock the playlist
or re-index existing tracks; meanwhile, search-as-you-type in the app
queries an inverted index that ranks results by a COMBINATION of text
match quality and each track's/artist's overall popularity, so
searching "queen" surfaces the band Queen prominently even though many
other technically-matching, lower-popularity results also exist.

COMMON MISTAKES:
- Applying the FULL complexity of character-level CRDTs/OT (L06-L07) to
  playlist editing, when playlist operations are coarse-grained enough
  that a much simpler operation-log/last-write-wins approach is usually sufficient.
- Representing playlist track order with simple sequential integers,
  requiring an expensive re-index of every subsequent track on every
  single insert — fractional/lexical ordering keys avoid this at the
  cost of periodically needing to REBALANCE keys if many inserts
  accumulate between the same two neighbors over time.
- Building search that ranks PURELY by text-match relevance without any
  popularity signal — for short, ambiguous queries (a common artist name
  that's also a common word), pure text relevance can bury the
  overwhelmingly most-likely-intended result beneath technically-equal
  but far less popular matches.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Fractional ordering for collaborative playlist inserts
# ------------------------------------------------------------------
def midpoint_key(key_before: str, key_after: str) -> str:
    """A simplified lexical midpoint generator (real implementations
    handle edge cases like adjacent keys more robustly)."""
    if not key_after:
        return key_before + "m"   # inserting at the end
    if not key_before:
        return "a" if key_after > "a" else key_after[:-1] + chr(ord(key_after[-1]) - 1)
    # A simplified midpoint: interpolate between the two keys' first characters
    mid_char = chr((ord(key_before[0]) + ord(key_after[0])) // 2)
    if mid_char in (key_before[0], key_after[0]):
        return key_before + "m"   # fallback: append to avoid collision
    return mid_char


def collaborative_playlist_demo():
    playlist = [
        {"track": "Song A", "order_key": "a"},
        {"track": "Song B", "order_key": "c"},
        {"track": "Song C", "order_key": "e"},
    ]
    print("Playlist (ordered by fractional key):")
    for track in playlist:
        print(f"  [{track['order_key']}] {track['track']}")

    # A friend inserts a new track between "Song A" and "Song B" —
    # NO re-indexing of Song B or Song C needed, just ONE new record
    new_key = midpoint_key("a", "c")
    playlist.append({"track": "New Song (inserted)", "order_key": new_key})
    playlist.sort(key=lambda t: t["order_key"])

    print(f"\nAfter a friend inserts a track between Song A and Song B "
          f"(new key='{new_key}'):")
    for track in playlist:
        print(f"  [{track['order_key']}] {track['track']}")
    print("  -> Only ONE new record was written; Song B and Song C's")
    print("     order keys were never touched, unlike integer re-indexing.")


# ------------------------------------------------------------------
# 2. Popularity-weighted search ranking
# ------------------------------------------------------------------
def search_rank(query: str, candidates: list[dict]) -> list[dict]:
    def score(candidate):
        text_match = 1.0 if query.lower() in candidate["name"].lower() else 0.5
        # Combine text match quality with a POPULARITY signal — pure text
        # relevance alone would treat all matching candidates equally
        return text_match * 0.6 + candidate["popularity"] * 0.4

    return sorted(candidates, key=score, reverse=True)


def search_demo():
    candidates = [
        {"name": "Queen (the band)", "popularity": 0.98},
        {"name": "Queen Latifah", "popularity": 0.6},
        {"name": "Drag Queen Anthology (obscure compilation)", "popularity": 0.05},
    ]
    ranked = search_rank("queen", candidates)
    print("Search results for 'queen', ranked by text match + popularity:")
    for r in ranked:
        print(f"  {r['name']} (popularity={r['popularity']})")
    print("  -> The overwhelmingly most-likely-intended result (the band)")
    print("     ranks first, despite all three technically matching the query text equally.")


if __name__ == "__main__":
    collaborative_playlist_demo()
    print()
    search_demo()

"""
FINAL CONTEXT (capstone of the Spotify case study):
The full picture across L11-L13: audio is delivered via popularity-aware
CDN caching and adaptive bitrate streaming (L11); personalized discovery
combines collaborative and content-based signals with a cold-start
fallback (L12); and the remaining product surface — collaborative
playlists (using lightweight fractional ordering rather than L06-L07's
heavier CRDT/OT machinery, since playlist edits are coarser-grained),
social following, and popularity-aware search — completes a system that,
end to end, spans real-time-adjacent delivery infrastructure, ML-driven
personalization, and general distributed-systems data-modeling
techniques, all in service of one product's specific set of user-facing features.
"""
