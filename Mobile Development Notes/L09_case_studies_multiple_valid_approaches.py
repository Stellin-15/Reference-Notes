"""
WHAT: Four realistic mobile-development problems, each solved with
      THREE genuinely different, individually defensible approaches
      drawn from L01-L08 -- with an explicit comparison table and
      reasoning for why each answer is valid under different
      constraints. Distinct from L08's capstone (the general native-vs-
      cross-platform decision framework) -- this lesson applies that
      framework to four SPECIFIC concrete scenarios.
WHY:  "Native or cross-platform," "how aggressive should offline support
      be," "how to handle app updates" are all questions L01-L08 gave
      you real tools for, not one universal answer -- this lesson is
      about the decision process under real product and team
      constraints.
LEVEL: Capstone -- read after L01-L08.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L08's concepts.
"""

# ============================================================================
# CASE STUDY 1 — CHOOSING A PLATFORM STRATEGY FOR A NEW STARTUP'S FIRST
# MOBILE APP (SMALL TEAM, NEEDS BOTH IOS AND ANDROID, LIMITED BUDGET)
# ============================================================================
#
# SETUP: a 2-person mobile team needs to ship on both iOS and Android as
# fast as possible, with limited budget for two fully separate native
# codebases.
#
# ------------------------------------------------------------------------
# APPROACH A: Two separate native codebases -- Swift/SwiftUI (L02) and
# Kotlin/Compose (L03)
# ------------------------------------------------------------------------
#   WHY VALID: per L02-L03, native development gives the best possible
#   performance, platform-idiomatic UX, and full, unrestricted access to
#   every platform API on day one -- no cross-platform framework
#   limitations to work around ever.
#   COST: per L08's decision framework, this DIRECTLY doubles
#   engineering effort for a 2-person team with limited budget -- every
#   feature must be built and maintained TWICE, in two different
#   languages/frameworks, a real, substantial cost mismatch with this
#   case study's explicit team-size and budget constraints.
#
# ------------------------------------------------------------------------
# APPROACH B: React Native (L04)
# ------------------------------------------------------------------------
#   WHY VALID: per L04/L08, a SINGLE codebase targets both platforms,
#   directly addressing A's doubled-effort problem -- and if the team
#   already has React/JavaScript expertise (common for a small startup
#   team), this leverages existing skills rather than requiring two new
#   platform-specific skill sets to be learned from scratch.
#   COST: per L04, the bridge architecture (or newer architectures
#   still evolving) introduces real, if generally manageable,
#   performance overhead relative to native, and certain advanced
#   platform-specific features may still require writing native modules
#   -- a real, if usually modest for MOST apps, limitation relative to
#   A's unrestricted native access.
#
# ------------------------------------------------------------------------
# APPROACH C: Flutter (L05)
# ------------------------------------------------------------------------
#   WHY VALID: per L05, Flutter's own rendering engine (Skia/Impeller)
#   gives it more consistent, often better raw performance and pixel-
#   perfect cross-platform UI consistency than React Native's bridge-
#   based approach, while still being a SINGLE codebase for both
#   platforms -- also a strong fit for a small team, with an arguably
#   gentler path to native-feeling performance than React Native.
#   COST: per L05, requires learning Dart specifically, a real, if
#   generally quick-to-learn, new language for a team that doesn't
#   already know it (unlike React Native's reuse of existing JavaScript/
#   React skills for a JS-experienced team) -- and Flutter's own
#   rendering approach means UI doesn't automatically inherit each
#   platform's native look-and-feel updates the way platform-native
#   frameworks do by default.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Engineering effort for a 2-person team | Leverages existing JS/React skills | Native platform-UX fidelity |
#   |----------|------------------------------------------------|-------------------------------------------|-------------------------------------|
#   | A: two native codebases | Highest (disqualifying at this team size) | N/A | Best |
#   | B: React Native | Lowest, if JS-experienced | Yes | Good |
#   | C: Flutter | Low | No (needs learning Dart) | Good, consistent but not platform-default |
#   Given this case study's explicit team-size/budget constraint, A is
#   very likely disqualified; between B and C, the deciding factor is
#   usually the team's EXISTING skill set (React/JS experience favors
#   B) rather than a universal ranking between the two frameworks.


# ============================================================================
# CASE STUDY 2 — DESIGNING OFFLINE SUPPORT FOR A FIELD-SERVICE APP (USED
# BY TECHNICIANS IN AREAS WITH UNRELIABLE CONNECTIVITY)
# ============================================================================
#
# SETUP: technicians use the app to record work orders, often in
# basements/rural areas with poor or no connectivity -- data entered
# offline must sync reliably once connectivity returns.
#
# ------------------------------------------------------------------------
# APPROACH A: Require connectivity for all actions -- show an error and
# block the user if offline
# ------------------------------------------------------------------------
#   WHY VALID: the simplest possible implementation -- no local storage,
#   no sync logic, no conflict resolution to build at all, and for an
#   app where EVERY use case genuinely requires real-time server
#   interaction (rare, but possible), this might be an honest reflection
#   of the app's actual constraints.
#   COST: per L06's offline-first discussion and this case study's
#   EXPLICIT setup (technicians in poor-connectivity areas), this
#   directly fails the app's core, stated use case -- a technician
#   unable to record a completed work order because they're in a
#   basement with no signal is a severe, disqualifying UX failure for
#   this specific application.
#
# ------------------------------------------------------------------------
# APPROACH B: Local-first storage with a sync QUEUE -- all actions are
# saved locally immediately, queued for sync, and sent when connectivity
# returns (L06)
# ------------------------------------------------------------------------
#   WHY VALID: per L06, this is the standard, well-established pattern
#   for exactly this use case -- the technician's experience is
#   identical whether online or offline (everything saves locally,
#   instantly), and the sync queue handles eventual delivery
#   transparently once connectivity returns, directly solving A's
#   disqualifying failure mode.
#   COST: per L06, introduces real CONFLICT RESOLUTION complexity -- if
#   the SAME work order is somehow modified both locally (offline) and
#   on the server (by another technician or a dispatcher) before sync
#   completes, the app needs an explicit, well-designed policy for
#   resolving that conflict, a genuinely hard problem if work orders can
#   legitimately be touched by multiple people.
#
# ------------------------------------------------------------------------
# APPROACH C: B, plus DELTA SYNC (L06) -- rather than syncing entire
# work-order records, sync only the SPECIFIC fields that changed,
# reducing sync payload size and conflict surface
# ------------------------------------------------------------------------
#   WHY VALID: per L06, delta sync directly reduces B's conflict-
#   resolution problem's SCOPE -- if two people modify DIFFERENT fields
#   of the same work order while offline, delta sync can often merge
#   both changes cleanly (no real conflict, since the changes don't
#   overlap), where whole-record syncing would force a much blunter
#   "which entire version wins" decision even when the actual changes
#   didn't conflict at all.
#   COST: per L06, delta sync is genuinely more complex to implement
#   correctly than whole-record sync -- tracking field-level changes,
#   correctly merging non-overlapping deltas, and still needing a
#   FALLBACK conflict-resolution policy for the cases where the SAME
#   field genuinely was changed by two different people offline -- more
#   engineering investment than B alone, justified specifically once
#   B's coarser conflict rate is measured to be a real, frequent
#   problem.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Fits the stated offline use case | Conflict-resolution burden | Implementation complexity |
#   |----------|----------------------------------------|-----------------------------------|----------------------------------|
#   | A: require connectivity | No (disqualifying) | None | Lowest |
#   | B: local-first + sync queue | Yes | Real, whole-record-level | Medium |
#   | C: B + delta sync | Yes | Reduced, field-level | Highest |
#   Given this case study's explicit connectivity constraints, A is
#   disqualified; B is the right starting point, escalating to C
#   specifically once real-world conflict frequency (measured from
#   actual usage) justifies the added delta-sync engineering investment.


# ============================================================================
# CASE STUDY 3 — HANDLING APP UPDATES FOR A FEATURE WITH A CRITICAL BUG
# FIX
# ============================================================================
#
# SETUP: a critical bug is found in a shipped app version, and the team
# needs to get the fix to users as fast as possible (L07).
#
# ------------------------------------------------------------------------
# APPROACH A: A standard app store release (new build, submitted through
# normal App Store/Play Store review) (L07)
# ------------------------------------------------------------------------
#   WHY VALID: per L07, this is the only mechanism that can update
#   NATIVE CODE (not just JavaScript/configuration) -- if the bug fix
#   requires changing genuinely native, compiled code, this is the only
#   valid path regardless of urgency.
#   COST: per L07, app store review takes real time (hours to days,
#   variable and not fully controllable by the team) -- for a genuinely
#   CRITICAL bug, this delay is a real, serious cost, and Apple/Google
#   both offer expedited review processes for critical fixes, but even
#   those aren't instant.
#
# ------------------------------------------------------------------------
# APPROACH B: An Over-The-Air (OTA) update (L07) -- if using React
# Native/similar, push a JavaScript-only update that bypasses app store
# review entirely
# ------------------------------------------------------------------------
#   WHY VALID: per L07, OTA updates can be pushed and take effect
#   almost immediately, without ANY app store review delay -- if the bug
#   is genuinely fixable purely within the JavaScript/React layer (not
#   requiring a native code change), this is dramatically faster than A.
#   COST: per L07, OTA updates are EXPLICITLY restricted by both Apple's
#   and Google's policies to non-native-code changes -- this option
#   simply doesn't exist if the bug requires touching native code, and
#   even where technically available, OTA update mechanisms have their
#   own policy constraints (e.g. Apple's guidelines around what OTA
#   updates may and may not change) that must be respected.
#
# ------------------------------------------------------------------------
# APPROACH C: A feature flag / remote kill-switch (built as a general
# practice BEFORE this incident, not reactively) that can disable the
# buggy feature entirely, server-side, with zero app update needed at all
# ------------------------------------------------------------------------
#   WHY VALID: if this general capability was ALREADY built into the
#   app (a proactive, not reactive, engineering investment), it's the
#   FASTEST possible mitigation of the three -- a server-side toggle
#   takes effect essentially instantly for all users, no store review,
#   no OTA push propagation delay, directly and immediately removing the
#   critical bug's impact by disabling the feature it lives in.
#   COST: only mitigates the SYMPTOM (disables the broken feature) --
#   doesn't actually FIX the underlying bug, which still needs a real
#   code fix via A (or B, if applicable) eventually; and this capability
#   must have been built INTO the app proactively, before this incident
#   -- it's not something the team can retroactively add fast enough to
#   help with THIS specific critical bug if it doesn't already exist.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Speed | Fixes native code bugs | Requires pre-existing infrastructure |
#   |----------|-----------|------------------------------|--------------------------------------------|
#   | A: standard app store release | Slowest | Yes | No |
#   | B: OTA update | Fast | No (JS/config only) | Requires an OTA-capable framework already in use |
#   | C: remote feature flag/kill-switch | Fastest | No (mitigates, doesn't fix) | Yes, must already exist |
#   The strongest REAL-WORLD answer is having C available as a first
#   response (immediate mitigation) while A or B (whichever applies)
#   ships the actual fix in parallel -- this case study is also a
#   direct argument for building feature-flag/kill-switch infrastructure
#   proactively, BEFORE a critical incident makes its absence
#   painfully obvious.


# ============================================================================
# CASE STUDY 4 — DECIDING WHETHER A NEW FEATURE NEEDS A NATIVE MODULE OR
# CAN STAY WITHIN THE CROSS-PLATFORM FRAMEWORK
# ============================================================================
#
# SETUP: a React Native app (already chosen per Case Study 1's reasoning)
# needs to add a new feature using an advanced platform-specific
# capability (e.g. real-time camera processing with platform-specific
# ML acceleration).
#
# ------------------------------------------------------------------------
# APPROACH A: Search for and use an existing, well-maintained community
# React Native library/plugin providing this capability (L04)
# ------------------------------------------------------------------------
#   WHY VALID: per L04, this avoids writing native code entirely if a
#   good library already exists -- the fastest path, and if the library
#   is genuinely well-maintained and widely used, it's already been
#   tested across many other apps' real-world usage.
#   COST: per L04, dependency on a THIRD-PARTY library's maintenance
#   status is a real, ongoing risk -- if the library becomes unmaintained,
#   has a bug the team can't easily work around, or doesn't support a
#   needed platform-specific detail, the team is stuck either living
#   with the gap or eventually needing to build a custom native module
#   anyway, just later and under more time pressure.
#
# ------------------------------------------------------------------------
# APPROACH B: Write a custom native module (L04) specifically for this
# feature, bridging to native Swift/Kotlin code
# ------------------------------------------------------------------------
#   WHY VALID: per L04, this gives full, direct control and access to
#   exactly the platform-specific capability needed, without any third-
#   party dependency risk -- the right answer when no adequate existing
#   library exists, or when the feature is central/critical enough to
#   the product that the team wants direct ownership of its
#   implementation.
#   COST: per L04, requires genuine native development expertise (Swift
#   AND Kotlin, per L02-L03) THIS SPECIFIC React Native team may not
#   have in-house if they chose React Native specifically to avoid
#   needing two native skill sets (echoing Case Study 1's reasoning) --
#   a real skills-gap cost that can undercut part of the original reason
#   React Native was chosen in the first place.
#
# ------------------------------------------------------------------------
# APPROACH C: Prototype the feature as a SEPARATE, small native
# proof-of-concept FIRST (in Swift/Kotlin directly, outside the React
# Native app) to validate the approach and performance characteristics,
# BEFORE committing to building the full native module (B) integrated
# into the app
# ------------------------------------------------------------------------
#   WHY VALID: de-risks B's real commitment -- validates whether the
#   platform-specific capability actually performs and behaves as
#   expected in isolation, before investing in the FULL native-module-
#   plus-React-Native-bridge integration effort, catching fundamental
#   feasibility problems early and cheaply rather than discovering them
#   deep into a larger integration effort.
#   COST: adds real, if usually modest, upfront time before any
#   progress toward the actual shipped feature -- a deliberate,
#   worthwhile slowdown specifically when the feature's feasibility is
#   genuinely uncertain, but unnecessary overhead if the team already
#   has high confidence the approach will work (e.g. from very similar
#   prior experience).
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Speed to a working feature | Long-term dependency risk | Requires native expertise now |
#   |----------|---------------------------------|---------------------------------|--------------------------------------|
#   | A: existing community library | Fastest, if one exists and fits | Real (third-party maintenance) | No |
#   | B: custom native module | Slower | None | Yes |
#   | C: native prototype first, then B | Slowest to ship, but lowest-risk | None | Yes, but validated early |
#   Check A first, since it's the cheapest to try; if no adequate
#   library exists or feasibility is genuinely uncertain, C's validation
#   step before committing to B's full investment is the disciplined,
#   risk-managed answer, especially given this specific team's likely
#   native-skills gap noted in the cost analysis above.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
