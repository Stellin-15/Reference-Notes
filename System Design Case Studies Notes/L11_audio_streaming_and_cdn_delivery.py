# ============================================================
# L11: Audio Streaming and CDN Delivery — How Spotify Serves Billions of Plays
# ============================================================
# WHAT: How a music-streaming service delivers audio efficiently at
#       massive scale — adaptive-bitrate audio encoding, CDN edge caching,
#       and the specific access-pattern properties (extreme popularity
#       skew) that shape the whole architecture.
# WHY: New case study: Spotify. Unlike L01-L05's REAL-TIME, LOW-LATENCY
#      video problem, audio streaming is a fundamentally different
#      problem — near-zero real-time constraint, but MASSIVE read
#      volume concentrated on a small fraction of content.
# LEVEL: Foundation (of this case study)
# ============================================================

"""
CONCEPT OVERVIEW:
UNLIKE live video (L01-L05), streaming a pre-recorded song has NO
real-time constraint on the SOURCE side — the audio file already exists
in full, encoded once, ahead of time. This fundamentally changes the
architecture: instead of WebRTC's real-time peer connections, audio
streaming is architecturally similar to a CDN-backed FILE DOWNLOAD
problem — the audio file is chunked, cached at edge locations close to
listeners, and streamed progressively (playback starts before the whole
file downloads) rather than requiring the file in full upfront.

EXTREME POPULARITY SKEW (a Zipfian/power-law distribution) is the single
most important access-pattern property shaping this architecture: a
small number of songs (new releases, viral hits) receive a
DISPROPORTIONATE fraction of total plays, while the "long tail" of
millions of less-popular tracks each get relatively few plays. This
directly informs CACHING STRATEGY: the small set of extremely popular
tracks should be cached at EVERY edge location (near-100% cache hit
rate achievable for them), while long-tail content is served more
directly from origin storage, since caching it everywhere would waste
edge cache capacity on content unlikely to be requested again from that
specific location.

ADAPTIVE BITRATE AUDIO (distinct from L03's real-time video adaptive
bitrate, but conceptually related): Spotify encodes each track at
MULTIPLE bitrates/quality levels (e.g. ~24kbps, 96kbps, 160kbps,
320kbps) ahead of time — the CLIENT selects which quality to
request based on its current network conditions and user settings,
switching between them as conditions change during playback, WITHOUT
needing any REAL-TIME re-encoding (since all quality levels were already
pre-encoded, unlike live video's real-time re-encoding needs).

PROGRESSIVE DOWNLOAD / CHUNKED STREAMING: a track is divided into small
CHUNKS (a few seconds each) so playback can begin after downloading just
the FIRST chunk, rather than waiting for the entire file — this is the
audio equivalent of the "buffering" behavior familiar from any streaming
video/audio player, and it's what allows near-instant playback start
even for a multi-minute track.

PRODUCTION USE CASE:
When a new album from a major artist drops, Spotify's CDN infrastructure
PRE-WARMS (proactively caches) the album's audio files at edge locations
globally BEFORE the release goes live, anticipating the predictable
spike in demand — rather than reactively caching only after the first
few requests arrive at each location (which would cause a "cold cache"
performance dip for a release known in advance to receive extreme initial demand).

COMMON MISTAKES:
- Applying a UNIFORM caching strategy across all content regardless of
  popularity — caching every long-tail track at every edge location
  wastes limited edge storage capacity on content with a low probability
  of a repeat request from that specific location, at the direct expense
  of cache space for genuinely popular content.
- Encoding audio at only ONE quality level — this either wastes bandwidth
  for users on constrained connections (forcing a fixed high bitrate) or
  provides poor audio quality for users with ample bandwidth (a fixed low
  bitrate) — multiple pre-encoded quality levels, selected adaptively by
  the client, serve BOTH cases well simultaneously.
- Not pre-warming caches for PREDICTABLE demand spikes (scheduled album
  releases, known-in-advance viral content) — reactive-only caching leads
  to a genuinely worse experience during the highest-value, highest-
  visibility moment (a major release's first hour) precisely when
  performance matters most for user perception.
"""

import random


# ------------------------------------------------------------------
# 1. Popularity skew (Zipfian distribution) and its caching implication
# ------------------------------------------------------------------
def simulate_popularity_skew(num_tracks: int = 10000, num_plays: int = 100000):
    # A Zipfian distribution: track rank r gets roughly proportional to 1/r plays
    random.seed(42)
    ranks = list(range(1, num_tracks + 1))
    weights = [1 / r for r in ranks]
    total_weight = sum(weights)
    play_counts = {r: 0 for r in ranks}

    for _ in range(num_plays):
        # Weighted random choice, approximated via cumulative sampling
        target = random.random() * total_weight
        cumulative = 0
        for r, w in zip(ranks, weights):
            cumulative += w
            if cumulative >= target:
                play_counts[r] += 1
                break

    top_1_pct_count = max(1, num_tracks // 100)
    top_1_pct_plays = sum(play_counts[r] for r in ranks[:top_1_pct_count])
    print(f"Simulated {num_plays:,} plays across {num_tracks:,} tracks:")
    print(f"  Top 1% of tracks ({top_1_pct_count} tracks) received "
          f"{top_1_pct_plays:,} plays ({top_1_pct_plays / num_plays:.1%} of ALL plays)")
    print("  -> This extreme skew is why caching the popular fraction at")
    print("     EVERY edge location captures the vast majority of traffic,")
    print("     while long-tail content doesn't need the same treatment.")


# ------------------------------------------------------------------
# 2. Adaptive bitrate selection based on network conditions
# ------------------------------------------------------------------
def select_bitrate(available_bandwidth_kbps: float) -> str:
    quality_levels = [
        (320, "Very High (320 kbps)"),
        (160, "High (160 kbps)"),
        (96, "Normal (96 kbps)"),
        (24, "Low (24 kbps, data saver)"),
    ]
    # Pick the HIGHEST quality that comfortably fits available bandwidth
    # (leaving headroom to avoid buffering if bandwidth fluctuates slightly)
    safety_margin = 0.8
    for bitrate, label in quality_levels:
        if bitrate <= available_bandwidth_kbps * safety_margin:
            return label
    return "Low (24 kbps, data saver)"   # fallback for very constrained connections


def adaptive_bitrate_demo():
    conditions = {
        "Home WiFi": 2000,
        "4G mobile": 250,
        "Congested 3G": 40,
    }
    for label, bandwidth in conditions.items():
        chosen = select_bitrate(bandwidth)
        print(f"  {label} ({bandwidth} kbps available): selects {chosen}")


# ------------------------------------------------------------------
# 3. Chunked progressive streaming
# ------------------------------------------------------------------
def chunked_streaming_demo():
    track_duration_seconds = 210   # a 3:30 track
    chunk_size_seconds = 5
    num_chunks = track_duration_seconds // chunk_size_seconds

    print(f"Track split into {num_chunks} chunks of {chunk_size_seconds}s each.")
    print("Playback begins after downloading just the FIRST chunk:")
    print(f"  Chunk 1 downloaded -> playback starts immediately")
    print(f"  Chunks 2-{num_chunks} continue downloading IN THE BACKGROUND")
    print(f"  while chunk 1 is already playing — this is why streaming feels")
    print(f"  instant rather than requiring the full {track_duration_seconds}s "
          f"track to download upfront.")


if __name__ == "__main__":
    simulate_popularity_skew()
    print()
    adaptive_bitrate_demo()
    print()
    chunked_streaming_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
Spotify's infrastructure pre-warms CDN edge caches globally ahead of a
major, scheduled album release, encodes the album at multiple bitrates
in advance, and serves it in small chunks so listeners worldwide
experience near-instant playback start the moment the release goes
live — while a niche independent artist's back-catalog track, played
rarely, is served more directly from origin storage without the same
proactive edge-caching investment, an architecture decision directly
driven by the measurable, predictable popularity-skew pattern this
lesson's simulation illustrates.
"""
