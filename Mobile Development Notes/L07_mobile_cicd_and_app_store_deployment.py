# ============================================================
# L07: Mobile CI/CD and App Store Deployment
# ============================================================
# WHAT: How mobile app deployment genuinely differs from web/backend
#       deployment (this repo's CICD Notes) — code signing, app store
#       REVIEW PROCESSES (a human/automated gatekeeper outside your
#       control), staged rollouts, and over-the-air update limitations.
# WHY: This repo's CICD Notes covers general CI/CD deeply, but mobile
#      deployment has genuinely unique constraints (you don't control
#      the "production environment" the way you do with your own
#      servers) that deserve dedicated coverage.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
CODE SIGNING is a MANDATORY step unique to mobile deployment: both iOS
and Android require every app to be CRYPTOGRAPHICALLY SIGNED with a
developer certificate/key before it can be installed on a device or
submitted to an app store — this proves the app's authenticity and
integrity (it hasn't been tampered with since signing) — LOSING your
signing key/certificate is a genuinely serious operational problem: for
Android specifically, losing your app's original signing key means you
can NEVER again publish an update to that SAME app listing (a new key
produces what the Play Store treats as a different app) — this is a
uniquely severe, mobile-specific "key management" risk with no real
equivalent in typical web deployment.

APP STORE REVIEW is a fundamental, structural difference from web
deployment: pushing a new version of a WEB application is entirely
under your own control and can be instantaneous — pushing a new MOBILE
app version requires SUBMISSION to Apple's App Store or Google's Play
Store, where it undergoes a REVIEW PROCESS (automated AND, for Apple
specifically, often human review) that can take HOURS TO DAYS and can
REJECT your submission for policy violations, bugs, or even
subjective UX judgment calls — this means your mobile release
TIMELINE is NOT entirely within your own control, a genuinely
important planning consideration absent from typical backend/web deployment.

STAGED ROLLOUTS mitigate the risk of a bad release reaching ALL users
simultaneously: both app stores support releasing an update to a SMALL
PERCENTAGE of users first (e.g. 5%), monitoring crash rates/reviews,
then GRADUALLY increasing the rollout percentage if metrics look
healthy — or HALTING the rollout entirely if a serious issue is
detected — this is conceptually similar to this repo's CICD Notes'
canary deployment pattern, applied specifically within the constraints
of app-store-mediated distribution (you can't simply "roll back" a
mobile release the way you can revert a web deployment; you can only
halt further rollout of the BAD version and expedite review of a FIXED version).

OVER-THE-AIR (OTA) UPDATES (tools like CodePush for React Native, or
Flutter's equivalent mechanisms) let you push JAVASCRIPT/DART code
changes DIRECTLY to already-installed apps, BYPASSING the app store
review process entirely for SPECIFIC KINDS of changes — but this comes
with a genuinely important LIMITATION: OTA updates can typically only
update the JS/Dart application logic layer, NOT native code changes
(new native modules, changed permissions, updated native dependencies)
— both Apple and Google's policies also place restrictions on what
kinds of changes are permissible via OTA specifically to prevent
apps from using this mechanism to circumvent review entirely for
substantive functionality changes — understanding this boundary is
important for planning what CAN be hot-fixed without a store
resubmission vs what genuinely requires going through review again.

PRODUCTION USE CASE:
A mobile team discovers a critical bug (a crash affecting a common user
flow) shortly after a full release — for a REACT NATIVE app, if the bug
is in JavaScript logic (not native code), an OTA update can push a fix
to already-installed apps within minutes, without waiting for app store
review; for a bug in NATIVE code, or for a native iOS/Android app
without OTA capability, the team must submit an emergency fix through
the NORMAL app store review process (potentially expedited, but still
subject to review timelines) — the SAME underlying bug requiring
genuinely different remediation timelines depending on where the fix lives.

COMMON MISTAKES:
- Losing or failing to securely back up an app's SIGNING KEY/certificate
  — for Android specifically, this can PERMANENTLY prevent future
  updates to an existing app listing, a catastrophic and irreversible
  operational failure that proper key management (secure backup,
  restricted access) directly prevents.
- Planning a mobile release timeline as if it were fully within the
  team's own control (like a typical web deployment) — app store review
  timelines are NOT guaranteed, and a launch date tightly coupled to a
  marketing event needs BUFFER time for potential review delays or rejections.
- Assuming OTA update mechanisms can fix ANY bug — a bug in native code,
  or a change requiring new permissions/native dependencies, genuinely
  requires a full app store resubmission regardless of OTA tooling
  availability; conflating these two remediation paths leads to
  incorrect incident-response time estimates during a real production issue.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Code signing — a mobile-specific, high-stakes requirement
# ------------------------------------------------------------------
CODE_SIGNING_ILLUSTRATION = textwrap.dedent("""\
    Code signing requirement (both platforms):

    Your app bundle -> SIGNED with your developer certificate/key -> App Store

    iOS: managed via Apple Developer certificates + provisioning profiles
    Android: managed via a keystore file (.jks/.keystore) + signing key

    CRITICAL: for Android, losing the ORIGINAL signing key means you can
    NEVER publish an update to that SAME app listing again — Google Play
    treats an app signed with a DIFFERENT key as a DIFFERENT app entirely.
    Secure, redundant backup of signing keys is a NON-NEGOTIABLE operational practice.
""")

# ------------------------------------------------------------------
# 2. Staged rollout — mitigating bad-release risk
# ------------------------------------------------------------------
def staged_rollout_plan():
    stages = [
        {"percentage": 5, "duration_hours": 24, "action": "Monitor crash rate and reviews closely"},
        {"percentage": 20, "duration_hours": 24, "action": "Continue monitoring, expand if healthy"},
        {"percentage": 50, "duration_hours": 48, "action": "Broader exposure, still monitoring"},
        {"percentage": 100, "duration_hours": 0, "action": "Full rollout, ongoing monitoring continues"},
    ]
    print("Staged rollout plan (halting/rolling back is only possible")
    print("by PAUSING further rollout, not reverting already-installed versions):\n")
    for stage in stages:
        print(f"  {stage['percentage']}% of users: {stage['action']} "
              f"(hold for ~{stage['duration_hours']}h before advancing)")


# ------------------------------------------------------------------
# 3. OTA updates — what they CAN and CANNOT fix
# ------------------------------------------------------------------
def can_ota_update_fix(bug_type: str) -> str:
    ota_fixable = {
        "javascript_logic_bug": True,
        "styling_issue": True,
        "api_endpoint_change": True,
        "native_module_bug": False,
        "new_permission_required": False,
        "native_dependency_upgrade": False,
    }
    fixable = ota_fixable.get(bug_type, False)
    return ("Can be OTA-updated within minutes, no app store review needed"
            if fixable else
            "Requires a FULL app store resubmission and review — no OTA shortcut available")


def ota_capability_demo():
    print("\nWhat OTA updates CAN and CANNOT fix:\n")
    for bug_type in ["javascript_logic_bug", "native_module_bug", "new_permission_required"]:
        result = can_ota_update_fix(bug_type)
        print(f"  {bug_type}: {result}")


if __name__ == "__main__":
    print(CODE_SIGNING_ILLUSTRATION)
    staged_rollout_plan()
    ota_capability_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A React Native team ships a release with a critical crash caused by a
JavaScript logic bug (a null reference in a checkout flow) — rather than
waiting the typical 24-48 hours for an emergency app store resubmission
to be reviewed and approved, they push a CodePush OTA update that fixes
the JS logic directly, reaching most active users within minutes — the
SAME team, when a LATER bug required adding a new native permission
(camera access for a new feature), had NO such shortcut available and
had to go through the FULL app store review process, illustrating
concretely why understanding this OTA/native boundary matters for
realistic incident-response planning.
"""
