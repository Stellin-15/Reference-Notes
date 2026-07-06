# ============================================================
# L03: Android Development with Kotlin and Jetpack Compose
# ============================================================
# WHAT: Kotlin's core safety features (null safety, coroutines for async
#       work) and Jetpack Compose's declarative UI model — Google's
#       modern native Android development stack, and its direct parallels to L02's iOS stack.
# WHY: L02 covered native iOS development. This lesson covers native
#      ANDROID development — the other half of the native development
#      landscape, sharing remarkably similar underlying design
#      philosophy despite being a separate ecosystem.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
KOTLIN'S NULL SAFETY is CONCEPTUALLY IDENTICAL to Swift's optionals
(L02), just with different syntax: a type like `String` is
NON-NULLABLE by default (guaranteed to never be null); `String?`
explicitly marks a type as NULLABLE — the compiler enforces handling the
null case (via safe calls `?.`, the Elvis operator `?:` for defaults, or
explicit null checks) before you can use a nullable value in a context
requiring non-null — this is the SAME fundamental insight (make absence
an explicit, compiler-checked part of the type system) implemented in a
different language, directly paralleling why both platforms converged
on this design independently: null-pointer exceptions were historically
one of the most common crash causes on BOTH platforms before this safety mechanism existed.

COROUTINES are Kotlin's approach to ASYNCHRONOUS, non-blocking code —
conceptually similar to JavaScript's async/await (this repo's Full-Stack
& Frontend Essentials Notes L04 covers Node's event loop) or Python's
asyncio, but with Kotlin's own `suspend` function mechanism: a
`suspend` function can PAUSE its execution at an await-like point
(e.g. a network call) WITHOUT blocking the underlying thread, letting
that thread do other work while waiting — critically important for
Android specifically because BLOCKING THE MAIN/UI THREAD (even briefly)
causes the entire app's UI to freeze and become unresponsive, and the
OS will actively kill an app whose main thread is blocked for too long
("Application Not Responding" errors) — coroutines let genuinely
long-running work (network calls, database queries) happen without this risk.

JETPACK COMPOSE'S DECLARATIVE MODEL directly parallels SwiftUI's (L02)
and React's (Full-Stack & Frontend Essentials Notes L01) declarative
approach: rather than imperatively manipulating UI widgets (the older
Android View/XML-layout approach: "find this TextView, call setText()"),
Compose functions DESCRIBE the UI as a function of current STATE, and
Compose automatically RECOMPOSES (re-renders) affected UI when that
state changes — the SAME underlying declarative-UI insight that SwiftUI,
React, AND Compose all independently converged on, strongly suggesting
this is the industry's settled-upon "right" mental model for UI
development generally, not a coincidental similarity across three unrelated ecosystems.

STATE HOISTING is Compose's specific pattern (paralleling SwiftUI's
`@Binding` and React's "lifting state up") for managing shared state:
rather than a child composable function OWNING its own state
internally (making it hard to share/control from a parent), STATE is
"HOISTED" up to the nearest common ancestor that needs to coordinate
it, with the state and a callback to modify it PASSED DOWN to child
composables as parameters — this makes composables more REUSABLE and
TESTABLE (a composable receiving state as parameters, rather than
owning it internally, is trivially testable with different input values).

PRODUCTION USE CASE:
A native Android ride-sharing app uses coroutines to fetch the user's
current trip status from the server WITHOUT blocking the main thread
(keeping the map view smoothly interactive while the network call is in
flight), and Jetpack Compose's declarative model to automatically
update the displayed ETA and driver location on screen the MOMENT the
underlying state updates from that network response — no manual "find
this view and update its text" code required, mirroring exactly how a
React app's UI reacts to state changes.

COMMON MISTAKES:
- Performing long-running work (network calls, disk I/O) directly on
  the main/UI thread rather than in a coroutine (or older
  thread-management mechanisms) — this freezes the UI and risks the OS
  killing the app entirely for being unresponsive, a severe and
  visible failure mode specific to mobile's stricter main-thread responsiveness requirements.
- Using the not-null assertion operator (`!!`) as a habit rather than
  properly handling nullable values — exactly like Swift's force-unwrap
  (L02), this reintroduces the crash risk null safety exists specifically to prevent.
- Having a composable function OWN state internally when it actually
  needs to be shared/coordinated with a parent or sibling composable —
  this makes the composable harder to test and reuse; state hoisting
  (passing state and a callback down as parameters instead) is the idiomatic fix.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Kotlin null safety — the same insight as Swift's optionals
# ------------------------------------------------------------------
NULL_SAFETY_EXAMPLE = textwrap.dedent("""\
    // Non-nullable by default — guaranteed to never be null
    var username: String = "alice"

    // Explicitly nullable — the compiler tracks and enforces this
    var nickname: String? = null

    // Safe call — returns null instead of crashing if nickname is null
    val length = nickname?.length

    // Elvis operator — provide a default for the null case
    val displayName = nickname ?: "Guest"

    // DANGEROUS (mirrors Swift's force-unwrap risk):
    // val crashRisk = nickname!!   // throws NullPointerException if null
""")

# ------------------------------------------------------------------
# 2. Coroutines — non-blocking async work, keeping the UI thread free
# ------------------------------------------------------------------
COROUTINES_EXAMPLE = textwrap.dedent("""\
    // A 'suspend' function can pause without blocking the underlying thread
    suspend fun fetchTripStatus(tripId: String): TripStatus {
        return apiClient.getTripStatus(tripId)   // network call, non-blocking
    }

    // Launched from a coroutine scope tied to the UI's lifecycle:
    viewModelScope.launch {
        val status = fetchTripStatus(currentTripId)
        // Updating a state variable here triggers Compose's automatic
        // recomposition — the UI updates WITHOUT manually finding and
        // updating any specific view, exactly like SwiftUI/React
        tripStatusState.value = status
    }
    // The UI thread remains FREE and responsive throughout the network
    // call — critical to avoid the "Application Not Responding" failure mode
""")

# ------------------------------------------------------------------
# 3. Jetpack Compose — declarative UI + state hoisting
# ------------------------------------------------------------------
COMPOSE_STATE_HOISTING_EXAMPLE = textwrap.dedent("""\
    // WITHOUT state hoisting — the composable OWNS its state internally,
    // making it hard for a parent to observe/control/test
    @Composable
    fun QuantitySelectorBad() {
        var quantity by remember { mutableStateOf(1) }
        Stepper(value = quantity, onValueChange = { quantity = it })
    }

    // WITH state hoisting — state lives in the PARENT, passed down as
    // parameters — the composable is now reusable and trivially testable
    @Composable
    fun QuantitySelector(quantity: Int, onQuantityChange: (Int) -> Unit) {
        Stepper(value = quantity, onValueChange = onQuantityChange)
    }

    @Composable
    fun ProductDetailScreen() {
        var quantity by remember { mutableStateOf(1) }
        QuantitySelector(
            quantity = quantity,
            onQuantityChange = { quantity = it }
        )
        // The PARENT now controls and can coordinate this state with
        // OTHER parts of the screen (e.g. updating a total price display)
    }
""")


if __name__ == "__main__":
    print(NULL_SAFETY_EXAMPLE)
    print(COROUTINES_EXAMPLE)
    print(COMPOSE_STATE_HOISTING_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A native Android banking app uses coroutines to fetch account balances
from multiple backend services CONCURRENTLY (rather than sequentially,
blocking the UI thread for each one in turn), combining the results once
all complete — the UI remains fully responsive throughout, and Kotlin's
null safety ensures every one of these balance values is EXPLICITLY
handled for the "failed to load" case at compile time, directly
mirroring the same safety-critical design consideration L02's iOS
banking app example illustrates on the other native platform.
"""
