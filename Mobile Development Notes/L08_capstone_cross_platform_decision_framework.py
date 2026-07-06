# ============================================================
# L08: Capstone — The Native vs Cross-Platform Decision Framework
# ============================================================
# WHAT: A capstone lesson synthesizing L01-L07 into a concrete decision
#       framework for choosing native (iOS/Swift, Android/Kotlin) vs
#       cross-platform (React Native, Flutter) for a REAL project, plus
#       the full production architecture (offline-first, CI/CD, app
#       store deployment) any choice ultimately needs.
# WHY: L02-L05 each covered ONE technology option in isolation. The
#      genuinely hard, valuable skill is CHOOSING correctly for a real
#      project's actual constraints — this capstone provides that
#      framework concretely, then wires in L06-L07's production concerns.
# LEVEL: Capstone
# ============================================================

"""
CONCEPT OVERVIEW:
THE DECISION FRAMEWORK, walked through systematically:

  QUESTION 1 — What does the TEAM already know? A team with deep
  existing React/JavaScript expertise (this repo's Full-Stack &
  Frontend Essentials Notes L01-L02) has a natural, low-friction path to
  React Native (L04); a team with NO existing mobile OR JS-adjacent
  expertise starting fresh has a more open choice, where Flutter's
  single, consistent language (Dart) across BOTH platforms may reduce
  onboarding complexity compared to needing separate Swift AND Kotlin expertise for native.

  QUESTION 2 — How much PLATFORM-SPECIFIC depth is genuinely needed?
  An app needing DAY-ONE access to brand-new OS features, deep
  hardware integration, or the absolute best possible performance for
  demanding use cases (complex real-time graphics, professional
  audio/video processing) points toward NATIVE (L02-L03) — an app whose
  core value proposition doesn't hinge on this level of platform-specific
  depth is well-served by cross-platform.

  QUESTION 3 — Does VISUAL CONSISTENCY across platforms matter more than
  PLATFORM-NATIVE FEEL? Per L05, Flutter's "draw everything itself"
  architecture naturally produces IDENTICAL visuals across platforms —
  ideal for a strongly-branded product; React Native's native-component
  approach (L04) more naturally picks up each platform's own idioms —
  ideal for a product wanting to feel maximally "at home" on each platform separately.

  QUESTION 4 — What's the MAINTENANCE BUDGET? Native development means
  maintaining genuinely SEPARATE codebases (L02 and L03) — roughly
  double the ongoing maintenance surface area compared to a single
  cross-platform codebase (L04 or L05) — a real, ongoing cost that
  compounds over a product's lifetime, not just a one-time development cost.

REGARDLESS OF THIS CHOICE, EVERY MOBILE APP NEEDS THE SAME PRODUCTION
FOUNDATION covered in L01, L06, and L07: correct handling of the app
lifecycle (L01) and OS-imposed constraints; offline-first architecture
with local-first storage and sync queues (L06); and a realistic
deployment pipeline accounting for code signing, app store review
timelines, staged rollouts, and the genuine boundary of what OTA updates can and cannot fix (L07).

PRODUCTION USE CASE:
A startup with an existing React web application and a small
engineering team chooses React Native for their new mobile app
specifically to maximize skill/code reuse (Question 1) and because their
product doesn't require deep platform-specific hardware integration
(Question 2) — they build with local-first offline architecture from
day one (L06, avoiding the retrofit cost L01 warned against), and plan
their launch timeline with explicit buffer for app store review (L07),
rather than assuming a web-deployment-style instant release process.

COMMON MISTAKES:
- Making the native vs cross-platform decision based on which
  technology is trending, rather than working through THIS lesson's
  four concrete questions against the actual project's real constraints
  — this repeats the SAME "match tools to constraints, not trends"
  mistake this repo warns against throughout every other domain.
- Treating L01/L06/L07's production concerns (lifecycle handling,
  offline-first, deployment realities) as concerns ONLY for whichever
  specific technology choice was made — these are UNIVERSAL mobile
  development concerns that apply regardless of native vs cross-platform,
  and skipping them for ANY choice produces the same real production risks.
- Treating the native/cross-platform decision as permanently fixed
  once made — while genuinely expensive to reverse (as L01 noted), teams
  DO sometimes migrate (e.g. starting cross-platform for speed, later
  rewriting performance-critical portions natively as native modules,
  L04) — the decision is consequential but not necessarily irreversible
  in a well-architected system.
"""

import textwrap


DECISION_FRAMEWORK_WALKTHROUGH = textwrap.dedent("""\
    Four-question decision framework:

    1. Team's existing skills?
       React/JS team -> React Native (L04)
       No existing mobile/JS skills -> Flutter (single language, L05)
                                        or dedicated native teams (L02-L03)

    2. Platform-specific depth needed?
       Deep hardware/OS integration, cutting-edge features -> Native (L02-L03)
       Standard app capabilities suffice -> Cross-platform (L04-L05)

    3. Visual consistency vs platform-native feel?
       Strong, unified brand identity -> Flutter (L05)
       Feel maximally "at home" per platform -> React Native (L04) or Native

    4. Maintenance budget?
       Can support TWO codebases long-term -> Native is viable (L02-L03)
       Need ONE codebase for cost/team-size reasons -> Cross-platform
""")

PRODUCTION_FOUNDATION_CHECKLIST = {
    "App lifecycle handling (L01)": "Correctly persist state before suspension; never assume indefinite background execution",
    "Offline-first architecture (L06)": "Local-first storage + persistent sync queue, from day one, not retrofitted later",
    "Deployment realism (L07)": "Buffer for app store review timelines; secure signing key backup; understand OTA boundaries",
}


if __name__ == "__main__":
    print(DECISION_FRAMEWORK_WALKTHROUGH)
    print("Universal production foundation, regardless of technology choice:\n")
    for item, requirement in PRODUCTION_FOUNDATION_CHECKLIST.items():
        print(f"  {item}: {requirement}")

"""
FINAL CONTEXT (capstone of this domain):
The measure of having internalized this domain isn't being able to
write a SwiftUI view, a Jetpack Compose widget, or a React Native
component in isolation — it's being able to walk into a NEW mobile
project, work through this capstone's four questions against that
project's REAL constraints (team skills, platform-depth needs, brand
requirements, maintenance budget), arrive at a genuinely justified
native-vs-cross-platform decision, and then build the SAME universal
production foundation (lifecycle-aware, offline-first, realistically
deployed) that every mobile app needs regardless of which specific
technology was chosen — this decision-making skill, not technology
trivia, is what distinguishes a senior mobile engineer's judgment.
"""
