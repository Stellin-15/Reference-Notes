# ============================================================
# L04: Screen Sharing and Media Renegotiation
# ============================================================
# WHAT: How a live call adds/changes media streams mid-call — starting
#       screen share, switching cameras, muting/unmuting — without
#       tearing down and re-establishing the entire connection.
# WHY: L01-L03 covered establishing and maintaining ONE call's media
#      flow. Real usage constantly CHANGES what's being sent mid-call
#      (a presenter starts sharing their screen 10 minutes in) — this
#      lesson covers the renegotiation mechanics that make that possible
#      without disrupting the existing audio/video.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
A live call's set of media streams (audio, camera video, screen share)
is NOT fixed at connection time — WebRTC supports RENEGOTIATION: adding,
removing, or changing a media track triggers a NEW offer/answer exchange
(reusing L01's signaling mechanism) over the EXISTING peer connection,
rather than tearing down and rebuilding the whole connection from
scratch. This matters enormously for user experience — starting a screen
share should not cause a brief audio/video interruption for other
participants, which a full reconnection would risk.

SCREEN SHARE AS A SEPARATE TRACK: technically, screen sharing is just
another VIDEO TRACK — captured from the OS's screen-capture API instead
of a camera — added to the same peer connection alongside the existing
camera track. A key practical difference: screen-share content
(text, UI, slides) benefits from being encoded differently than
camera video — screen content is often mostly STATIC with occasional
large changes (a slide transition) rather than continuously varying
(a face on camera), so encoders typically apply a DIFFERENT bitrate/
frame-rate profile (lower frame rate, sharper detail preservation) for
screen-share tracks specifically — encoding both the same way wastes
bandwidth on smooth motion a screen share rarely has, while under-serving the sharp text/UI detail it usually does have.

SIMULTANEOUS CAMERA + SCREEN SHARE requires the SFU (L02) to handle an
ADDITIONAL stream per participant who's sharing — this directly
increases the SFU's total fan-out bandwidth for that call, since
now potentially TWO video streams per sharing participant need
forwarding to every viewer, a real capacity-planning consideration for
a video platform (a call where every participant shares simultaneously,
while rare, is a genuine worst case an SFU's capacity planning must
account for, not just the common one-screen-share-at-a-time case).

MUTE/UNMUTE, in a well-designed system, does NOT tear down the audio
track at all — it simply STOPS SENDING data on the existing track
(or sends a "muted" signal) while keeping the connection/track itself
alive, so unmuting is instantaneous rather than requiring a fresh
renegotiation round trip each time — a meaningful latency difference for a
feature used as frequently as mute/unmute is in every call.

PRODUCTION USE CASE:
A Google Meet presenter clicks "share screen" 15 minutes into a call —
their client captures the screen as a new video track, triggers a
renegotiation (a new SDP offer describing the updated set of tracks) sent
through the EXISTING signaling connection, and the SFU begins forwarding
this new track to viewers who request it — all while the presenter's
camera and audio tracks continue flowing UNINTERRUPTED throughout this
entire process, because renegotiation only affects the specific track being added.

COMMON MISTAKES:
- Tearing down and re-establishing the entire peer connection just to add
  a screen-share track — this is unnecessary (renegotiation exists
  specifically to avoid this) and causes a visible/audible glitch for all
  participants as audio/video are briefly interrupted during full reconnection.
- Encoding screen-share content with the SAME bitrate/frame-rate profile
  as camera video — screen content's different characteristics
  (mostly-static, sharp text/UI) are poorly served by an encoder profile
  tuned for continuously-varying camera video, producing either wasted
  bandwidth or blurry, hard-to-read shared text.
- Implementing mute by tearing down the audio track entirely rather than
  simply pausing data flow on the existing track — this adds unnecessary
  renegotiation latency to one of the most frequently used actions in any call.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Renegotiation flow when adding a screen-share track
# ------------------------------------------------------------------
RENEGOTIATION_FLOW = textwrap.dedent("""\
    Existing call state: [audio track, camera video track] — connection ESTABLISHED

    1. Presenter clicks "Share Screen"
       -> Browser's screen-capture API returns a new MediaStreamTrack

    2. Presenter's WebRTC client adds this track to the EXISTING
       RTCPeerConnection (does NOT create a new connection)

    3. This track addition triggers the "negotiationneeded" event ->
       client creates a NEW SDP offer describing the UPDATED set of
       tracks: [audio, camera video, screen-share video]

    4. This new offer is sent through the SAME signaling WebSocket (L01)
       used for the original connection — no new signaling channel needed

    5. The SFU/remote peer responds with a matching answer

    6. The screen-share track begins flowing — audio and camera video
       tracks are UNAFFECTED throughout this entire process; there is
       no interruption to what's already working.

    Result: [audio, camera video, screen-share video] — all flowing,
    added incrementally without ever tearing down the connection.
""")

# ------------------------------------------------------------------
# 2. Encoding profile differences: camera vs screen share
# ------------------------------------------------------------------
def encoding_profile_comparison():
    profiles = {
        "Camera video": {
            "typical_content": "Continuously varying (face, motion, lighting)",
            "frame_rate": "30 fps (smooth motion matters)",
            "priority": "Motion smoothness over per-frame sharpness",
        },
        "Screen share": {
            "typical_content": "Mostly static (slides, text, UI) with occasional big changes",
            "frame_rate": "5-15 fps (motion smoothness rarely matters)",
            "priority": "Sharp detail/text legibility over frame rate",
        },
    }
    for track_type, profile in profiles.items():
        print(f"{track_type}:")
        for key, value in profile.items():
            print(f"  {key}: {value}")
        print()


# ------------------------------------------------------------------
# 3. SFU fan-out cost when screen share adds a second stream
# ------------------------------------------------------------------
def sfu_capacity_with_screen_share(num_viewers: int, camera_mbps: float, screen_mbps: float):
    normal_fanout = camera_mbps * num_viewers
    with_screen_share_fanout = (camera_mbps + screen_mbps) * num_viewers
    print(f"SFU fan-out for {num_viewers} viewers of ONE presenter:")
    print(f"  Camera only: {normal_fanout:.1f} Mbps")
    print(f"  Camera + screen share: {with_screen_share_fanout:.1f} Mbps "
          f"(+{(with_screen_share_fanout / normal_fanout - 1) * 100:.0f}%)")
    print("  -> Capacity planning must account for the WORST realistic case "
          "(e.g. multiple simultaneous screen-shares in a large call), not "
          "just the common single-presenter case.")


if __name__ == "__main__":
    print(RENEGOTIATION_FLOW)
    encoding_profile_comparison()
    sfu_capacity_with_screen_share(num_viewers=50, camera_mbps=1.5, screen_mbps=2.0)

"""
PRODUCTION CONTEXT EXAMPLE:
A 50-person Google Meet call has its presenter share their screen while
keeping their camera on ("picture-in-picture" style) — the renegotiation
adds the screen-share track without interrupting the ongoing audio/video,
the SFU begins forwarding a THIRD stream (audio, camera, screen) to all
50 viewers, and the screen-share track is encoded with a lower frame
rate but higher detail-preservation profile than the camera track — a
viewer sees smooth video of the presenter's face alongside sharp,
readable shared slides, with the underlying network/encoding decisions
tuned separately for each stream's actual content characteristics.
"""
