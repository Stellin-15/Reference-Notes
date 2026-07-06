# ============================================================
# L01: Mobile Development Fundamentals and the Platform Landscape
# ============================================================
# WHAT: The foundational constraints that make mobile development
#       genuinely different from web/backend development — the app
#       lifecycle, offline-first expectations, battery/resource
#       constraints, and the native vs cross-platform landscape overview.
# WHY: This repo's Full-Stack & Frontend Essentials Notes covers web
#      frontend (React/Vue) in depth, but mobile has fundamentally
#      DIFFERENT constraints (app store review, background execution
#      limits, offline expectations) this new domain covers specifically.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
THE APP LIFECYCLE is the single most important conceptual difference
from web development: a mobile app is NOT simply "running" or "not
running" — it moves through distinct states (foreground/active,
background, suspended, terminated) that the OPERATING SYSTEM controls,
NOT the app itself. An app can be SUSPENDED (frozen in memory, no CPU
time) or even TERMINATED entirely by the OS to reclaim memory for other
apps, WITHOUT any warning to the app — code that assumes "my app will
keep running in the background to finish this task" is a fundamentally
incorrect mental model; mobile platforms give apps only LIMITED,
EXPLICITLY-REQUESTED background execution time for specific purposes
(finishing a network request, playing audio), not indefinite background operation.

OFFLINE-FIRST IS AN EXPECTATION, NOT AN EDGE CASE: unlike a typical web
app (which can reasonably assume a mostly-continuous internet
connection), mobile users routinely experience spotty connectivity
(subway tunnels, elevators, rural areas, airplane mode) — well-designed
mobile apps are built OFFLINE-FIRST from the start (this repo's System
Design Case Studies Notes L09 covered offline-first sync for
collaborative editing specifically; mobile apps face this same
challenge more broadly and more routinely) — local data persistence and
graceful degradation when network calls fail are DEFAULT-EXPECTED
behaviors, not optional enhancements.

BATTERY AND RESOURCE CONSTRAINTS shape mobile architecture decisions in
ways web development rarely needs to consider: excessive background
network polling, unnecessarily precise GPS location tracking, or
inefficient rendering directly and measurably drains a USER'S PHYSICAL
BATTERY — both Android and iOS actively MONITOR and can THROTTLE or
FLAG apps that consume excessive battery/resources, and app store review
processes (particularly Apple's) can reject apps for excessive background
resource usage — this creates a genuine engineering constraint (be
resource-efficient) with real, visible consequences (poor App Store
rating, review rejection) that most backend/web development doesn't face directly.

THE NATIVE VS CROSS-PLATFORM LANDSCAPE: NATIVE development (Swift/
SwiftUI for iOS, L02; Kotlin/Jetpack Compose for Android, L03) uses each
platform's OWN language and UI framework, giving full access to
platform-specific capabilities and typically the BEST possible
performance/platform-idiom fit, at the cost of maintaining TWO
completely separate codebases. CROSS-PLATFORM frameworks (React Native,
L04; Flutter, L05) let you write ONE codebase targeting BOTH platforms,
trading some platform-specific fidelity/performance for significantly
reduced development and maintenance cost — this tradeoff (covered in
depth across L02-L05, with a decision framework in L08) is the single
most consequential architectural decision in mobile development, made
ONCE at a project's start and genuinely expensive to reverse later.

PRODUCTION USE CASE:
A messaging app must correctly handle: the user receiving a message
while the app is BACKGROUNDED (requiring a push notification, since the
app itself isn't actively running code to detect this); the user losing
network connectivity mid-conversation (requiring locally-queued,
not-yet-sent messages that retry once connectivity resumes); and
minimizing battery drain from its real-time connection (requiring
efficient use of platform-provided background execution APIs rather
than naive continuous polling) — three DIFFERENT mobile-specific
constraints that a web-based chat application's architecture wouldn't need to address in the same way.

COMMON MISTAKES:
- Assuming an app can rely on continuous, indefinite background execution
  for anything beyond what the platform explicitly permits — this
  causes real-world reliability bugs (background sync silently stopping)
  that only manifest once the OS actually suspends/terminates the app, a
  failure mode easy to miss during development (where an app is often
  kept in the foreground) but common in real usage.
- Treating offline handling as a "nice to have" enhancement added later,
  rather than a foundational architectural decision made from the
  start — retrofitting offline-first behavior into an app built
  assuming constant connectivity is substantially more disruptive than
  designing for it from day one.
- Choosing native vs cross-platform based on hype/trend rather than the
  actual project's needs (team's existing skills, required platform-
  specific feature depth, budget for maintaining two codebases) — L08's
  capstone covers this decision framework in depth, but the underlying
  principle here is the same one this repo applies throughout: match
  tools to actual constraints, not trends.
"""

import textwrap


# ------------------------------------------------------------------
# 1. The app lifecycle states
# ------------------------------------------------------------------
APP_LIFECYCLE_DIAGRAM = textwrap.dedent("""\
    Mobile app lifecycle (simplified, applies conceptually to both platforms):

        [Not Running] --launch--> [Foreground/Active]
                                        |
                          user backgrounds the app
                                        v
                                  [Background]
                          (LIMITED time for specific tasks:
                           finishing a network call, playing audio)
                                        |
                          background time expires, OR
                          OS needs memory for other apps
                                        v
                                  [Suspended]
                          (frozen in memory, ZERO CPU time,
                           can be silently TERMINATED at any moment)
                                        |
                                        v
                                [Terminated]
                          (app must be relaunched from scratch;
                           NO warning is guaranteed before this happens)
""")

# ------------------------------------------------------------------
# 2. Offline-first design pattern, illustrated
# ------------------------------------------------------------------
def send_message_offline_first(message: str, is_online: bool, local_queue: list[str]) -> str:
    # ALWAYS persist locally FIRST, regardless of connectivity —
    # this is the "offline-first" principle: the local write is the
    # SOURCE OF TRUTH for the user's own action, synced when possible
    local_queue.append(message)

    if is_online:
        # Attempt to sync immediately, but the message is ALREADY safe
        # locally even if this network call fails
        local_queue.remove(message)
        return f"Message sent immediately: '{message}'"
    else:
        return f"Message queued locally (offline): '{message}' -- will retry once connectivity resumes"


def offline_first_demo():
    print(APP_LIFECYCLE_DIAGRAM)
    local_queue = []

    result1 = send_message_offline_first("Hey, running late!", is_online=True, local_queue=local_queue)
    print(result1)

    result2 = send_message_offline_first("Are you there?", is_online=False, local_queue=local_queue)
    print(result2)
    print(f"  Local queue after both attempts: {local_queue}")
    print("  -> The offline message was NEVER lost — it's safely persisted")
    print("     locally, ready to retry the moment connectivity resumes,")
    print("     rather than the user's action simply failing silently.")


# ------------------------------------------------------------------
# 3. Native vs cross-platform decision factors (previewed, L08 goes deep)
# ------------------------------------------------------------------
DECISION_FACTORS_PREVIEW = textwrap.dedent("""\
    Native (Swift/SwiftUI, Kotlin/Compose) vs Cross-platform (React
    Native, Flutter) — key factors this domain builds toward (L08's capstone):

      - Team's EXISTING skills (web/JS team -> React Native fits better;
        dedicated iOS/Android teams -> native may be a natural fit)
      - How much PLATFORM-SPECIFIC capability is genuinely needed
        (deep hardware integration, latest OS features on day one)
      - Budget/timeline for maintaining ONE codebase vs TWO
      - Performance requirements (native has an edge for animation-heavy,
        performance-critical apps; cross-platform has closed much of this gap)
""")


if __name__ == "__main__":
    offline_first_demo()
    print(DECISION_FACTORS_PREVIEW)

"""
PRODUCTION CONTEXT EXAMPLE:
A note-taking app correctly handles a user writing extensive notes
during a flight with no connectivity (offline-first local persistence,
per this lesson's demo), syncing seamlessly once landed and reconnected
— while ALSO correctly handling the OS suspending the app mid-flight if
the user switches to another app for an extended period, requiring the
note-taking app to properly persist its in-progress state BEFORE
suspension (since it cannot assume it will simply resume execution
later without interruption) — both mobile-specific constraints this
lesson introduces, and which L02-L07 cover the platform-specific implementation details for.
"""
