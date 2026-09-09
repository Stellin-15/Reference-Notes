# Mobile Development — Principal Engineer Deep Dive

Companion to the existing lessons (iOS/Swift, Android/Kotlin, React
Native, Flutter). Narrative depth, then a comprehensive common-to-
uncommon reference.


## Native vs Cross-Platform — The Real Tradeoff

**Beyond the lesson**: "Cross-platform is slower than native" is an
oversimplification that hasn't been fully true for years — the REAL
tradeoff is architectural. Flutter compiles to native ARM code (via
Dart's AOT compiler) and renders its OWN UI via Skia/Impeller, not the
platform's native widgets — genuinely fast, but visually/behaviorally
must actively work to match each platform's native look-and-feel
conventions. React Native (pre-New Architecture) historically bridged to
ACTUAL native components via an async JS bridge — slower for
high-frequency UI updates, but truly native widgets underneath. React
Native's New Architecture (JSI - JavaScript Interface, replacing the old
bridge) removed much of that async-bridge overhead, closing the gap
significantly — a real, recent architectural shift worth knowing about
specifically for any React Native interview.

**Worked example**: The "why does my React Native list scroll janky with
1000 items" performance question almost always traces to NOT using
`FlatList`/`FlashList` (which virtualize — only render visible items) and
instead mapping a huge array directly to `View` components — rendering
1000 native views simultaneously regardless of scroll position, a real,
common performance bug distinct from any bridge-overhead discussion entirely.

**Interview Q&A**:
- *Q: When would you choose fully native (separate Swift + Kotlin codebases) over any cross-platform framework?* A: When the app is deeply platform-integrated (heavy use of platform-specific APIs/hardware, like ARKit/Core ML on iOS or specific Android system integrations), when perf-critical UI (games, camera-heavy apps) needs the absolute lowest-level control, or when the org has separate, well-resourced iOS/Android teams where cross-platform's main benefit (one team, one codebase) doesn't actually apply.


## Mobile-Specific Performance & Battery Constraints

**Beyond the lesson**: Mobile engineering has TWO constraints web/backend
engineering mostly doesn't: battery and thermal budget. A background
location-tracking feature polling GPS every second will drain a battery
in hours and is EXACTLY the kind of thing app-store review guidelines
(and OS-level background execution limits — iOS's Background App
Refresh restrictions, Android's Doze mode) actively fight against — the
correct pattern is significant-location-change APIs or geofencing
(hardware-assisted, much lower power) instead of continuous active
polling, a genuinely different mental model than "just call the API more often."

**Interview Q&A**:
- *Q: An app is flagged by users for draining battery quickly. Beyond obvious CPU-heavy code, what mobile-specific culprits should you check?* A: Wake locks held longer than necessary (preventing the device from sleeping), excessive background network activity (batch/defer non-urgent network calls instead of many small ones — each radio wake-up has a real fixed energy cost regardless of payload size), and GPS/sensor polling frequency higher than the feature actually needs.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Cross-platform framework landscape
- **Flutter** — Dart, own rendering engine, strong for pixel-perfect
  custom UI, backed by Google, mature and widely production-proven.
- **React Native** — JS/TypeScript, New Architecture (JSI/Fabric) closing
  the native-bridge performance gap significantly, huge ecosystem given
  React's web-development overlap in hiring pool.
- **Kotlin Multiplatform (KMP)** — SHARE business logic (not UI) across
  iOS/Android while keeping fully native UI on each platform — a
  genuinely different philosophy (native UI, shared logic) from Flutter/RN's
  "shared UI too" approach, gaining real traction especially at companies wanting native UI fidelity without duplicating business logic.
- **.NET MAUI** — Microsoft's cross-platform framework, chosen mainly by
  shops already invested in C#/.NET tooling.

### Native platform-specific depth
- **SwiftUI vs UIKit** (iOS) — SwiftUI is Apple's newer declarative UI
  framework (similar philosophy to React); UIKit remains the imperative,
  more mature/battle-tested option still used heavily in large existing
  codebases and for capabilities SwiftUI hasn't fully matured to cover yet.
- **Jetpack Compose vs traditional Views** (Android) — the same
  declarative-vs-imperative shift on Android's side; Compose is now
  Google's recommended default for new Android UI development.
- **Combine/async-await (iOS) and Kotlin Coroutines/Flow (Android)** —
  the modern async/reactive programming primitives on each platform,
  replacing older callback-heavy or RxSwift/RxJava-based patterns for most new code.

### App distribution & CI/CD for mobile
- **Fastlane** — the dominant automation tool for building, signing, and
  publishing to the App Store/Play Store — genuinely essential given how
  manual/error-prone mobile release processes are without it.
- **CodePush (App Center) / Expo Updates** — over-the-air JS bundle
  updates for React Native/Expo apps, letting JS-layer bug fixes ship
  WITHOUT a full app-store review cycle — a real, distinctive
  cross-platform-framework advantage native apps structurally can't match
  (native binary changes always require store review).
- **TestFlight / Play Console internal testing tracks** — the standard
  beta-distribution mechanisms before a public release.

### Mobile-specific testing & quality
- **XCUITest / Espresso** — the native UI testing frameworks per platform.
- **Detox** — the dominant E2E testing framework specifically for React
  Native, designed around React Native's async rendering to avoid the
  flakiness generic Selenium-style automation suffers on mobile.
- **Crashlytics / Sentry** — mobile crash reporting — genuinely essential
  given the fragmentation of real-world device/OS-version combinations no
  test matrix can fully cover before release.


## NICHE BUT REAL

- **Deep linking & universal links** — opening a specific in-app screen
  directly from a web URL/notification, with real platform-specific setup
  (Apple App Site Association files, Android App Links verification) —
  a genuinely fiddly, commonly-underestimated integration point in
  real mobile app work.
- **App thinning / bundle size optimization** — App Store's "app
  thinning" delivers only the resources needed for a specific device
  (right image resolution, right architecture slice); Android's App
  Bundles do similar dynamic delivery — both a real, ongoing engineering
  concern as apps accumulate assets/dependencies over time and bundle size directly affects install conversion rates.
- **Accessibility on mobile (VoiceOver/TalkBack)** — screen-reader support
  requires explicit semantic labeling (accessibility labels/hints) beyond
  what visual-only development naturally produces — increasingly a
  compliance requirement (see Web Performance & Accessibility domain),
  not just a nice-to-have, on mobile just as much as web.
- **Offline-first architecture** — mobile apps need to gracefully handle
  intermittent/no connectivity as the DEFAULT expectation, not an edge
  case — local persistence (SQLite/Realm/WatermelonDB) with sync-on-
  reconnect logic, often via CRDT-style conflict resolution (see
  Distributed Systems Theory deep dive) when the same data was edited offline on multiple devices.
