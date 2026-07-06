# ============================================================
# L02: iOS Development with Swift and SwiftUI
# ============================================================
# WHAT: Swift's core language features relevant to app development
#       (optionals, value vs reference types) and SwiftUI's declarative,
#       reactive UI model — Apple's modern native iOS development stack.
# WHY: L01 covered mobile fundamentals generally. This lesson covers
#      NATIVE iOS development specifically — one half of the native vs
#      cross-platform decision this domain builds toward (L08).
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
OPTIONALS are Swift's built-in mechanism for making the ABSENCE of a
value an explicit, compiler-enforced part of a variable's TYPE — a
variable of type `String` is GUARANTEED to hold an actual string value;
a variable of type `String?` (optional String) might hold a string OR
`nil`, and the compiler FORCES you to explicitly handle the `nil` case
before using the value (via optional binding `if let`, or the `??`
nil-coalescing operator) — this eliminates an ENTIRE CLASS of null-
pointer-style crashes at COMPILE TIME rather than discovering them at
runtime, a genuinely significant safety improvement over languages
where any reference can silently be null without the type system reflecting this.

VALUE TYPES (structs) VS REFERENCE TYPES (classes) is a distinction
Swift treats as more central than many languages: a STRUCT is COPIED
whenever assigned to a new variable or passed to a function (each copy
is independent — modifying one doesn't affect the other), while a CLASS
is a REFERENCE (assignment creates another pointer to the SAME
underlying object — modifying it through one reference is visible
through the other) — SwiftUI's data model LEANS HEAVILY on value types
(structs) for its VIEW STRUCTS specifically, since predictable,
independent copies make reasoning about UI state changes simpler and
prevent an entire class of "who else might be holding a reference to
this and mutating it unexpectedly" bugs.

SWIFTUI'S DECLARATIVE MODEL: rather than IMPERATIVELY describing HOW to
update the UI (the older UIKit approach: "find this label, set its text
to X"), SwiftUI has you DECLARE WHAT the UI should look like AS A
FUNCTION OF THE CURRENT STATE — when the underlying state changes,
SwiftUI AUTOMATICALLY re-renders the affected parts of the UI to match
— this is CONCEPTUALLY IDENTICAL to React's declarative model (this
repo's Full-Stack & Frontend Essentials Notes L01), just applied to
native iOS UI rather than the web DOM — a genuinely useful mental-model
bridge for anyone coming from React specifically.

STATE MANAGEMENT PROPERTY WRAPPERS (`@State`, `@Binding`,
`@ObservedObject`, `@EnvironmentObject`) parallel React's state-
management escalation ladder (Full-Stack & Frontend Essentials Notes
L02: local state -> Context -> global store): `@State` for
view-local state; `@Binding` for passing a MUTABLE reference to a
parent's state down to a child view; `@ObservedObject`/`@StateObject`
for shared, more complex state objects; `@EnvironmentObject` for
app-wide state accessible without explicit prop-drilling through every
intermediate view — the SAME underlying "escalate only as needed"
principle this repo has applied throughout its frontend content applies directly here.

PRODUCTION USE CASE:
A native iOS shopping app uses `@State` for a product-detail view's
local "quantity selector" state, `@ObservedObject` for a shared
"shopping cart" object that multiple different views need to read and
modify, and `@EnvironmentObject` for app-wide user authentication
state accessible from any view without manually passing it down through
every intermediate screen — a direct structural parallel to how a React
app might use local state, a shared store (Zustand/Redux), and Context respectively.

COMMON MISTAKES:
- Force-unwrapping optionals (`value!`) as a habit rather than properly
  handling the `nil` case — this reintroduces exactly the runtime-crash
  risk optionals exist to prevent at compile time; a force-unwrap on a
  `nil` value crashes the app immediately and unconditionally.
- Confusing struct (value type) and class (reference type) semantics —
  assuming a struct assigned to a new variable shares state with the
  original (it doesn't; it's an independent copy) is a common source of
  "my mutation isn't showing up where I expected" bugs for developers
  coming from reference-type-only languages.
- Overusing `@EnvironmentObject`/global state for data that's genuinely
  local to one view or view hierarchy — mirroring the SAME mistake this
  repo's Full-Stack & Frontend Essentials Notes L02 warns against for
  React: escalating state management prematurely adds complexity
  without a corresponding benefit for data that didn't need to be shared that broadly.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Optionals — compile-time-enforced nil handling
# ------------------------------------------------------------------
OPTIONALS_EXAMPLE = textwrap.dedent("""\
    // A variable that MIGHT be nil — the '?' makes this explicit in the TYPE
    var username: String? = fetchUsernameFromServer()

    // The compiler FORCES handling the nil case before use:
    if let actualUsername = username {
        print("Welcome, \\(actualUsername)!")
    } else {
        print("No username set")
    }

    // Or using nil-coalescing for a default value:
    let displayName = username ?? "Guest"

    // DANGEROUS (but sometimes seen): force-unwrapping crashes if nil
    // let crashRisk = username!   // AVOID unless truly certain it's non-nil
""")

# ------------------------------------------------------------------
# 2. Value types (struct) vs reference types (class)
# ------------------------------------------------------------------
VALUE_VS_REFERENCE_EXAMPLE = textwrap.dedent("""\
    struct Point {   // VALUE type — copied on assignment
        var x: Int
        var y: Int
    }

    var pointA = Point(x: 1, y: 2)
    var pointB = pointA          // pointB is an INDEPENDENT COPY
    pointB.x = 99
    print(pointA.x)              // still 1 — pointA was NOT affected

    class Counter {   // REFERENCE type — shared on assignment
        var count = 0
    }

    let counterA = Counter()
    let counterB = counterA      // counterB points to the SAME object
    counterB.count = 99
    print(counterA.count)        // 99 — counterA WAS affected, same underlying object
""")

# ------------------------------------------------------------------
# 3. SwiftUI's declarative, state-driven view model
# ------------------------------------------------------------------
SWIFTUI_EXAMPLE = textwrap.dedent("""\
    struct ProductDetailView: View {
        @State private var quantity = 1              // view-local state
        @ObservedObject var cart: ShoppingCart        // shared object, multiple views
        @EnvironmentObject var authState: AuthState   // app-wide, no manual prop-drilling

        var body: some View {
            VStack {
                Text("Quantity: \\(quantity)")
                Stepper("", value: $quantity, in: 1...10)
                // '$quantity' creates a BINDING — a mutable reference the
                // Stepper can write back through, updating @State directly

                Button("Add to Cart") {
                    cart.addItem(quantity: quantity)
                    // Changing 'cart' automatically re-renders ANY view
                    // observing it — no manual "update the UI" call needed,
                    // exactly like React's declarative re-render model
                }
            }
        }
    }
""")


if __name__ == "__main__":
    print(OPTIONALS_EXAMPLE)
    print(VALUE_VS_REFERENCE_EXAMPLE)
    print(SWIFTUI_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A native iOS banking app relies heavily on Swift's optional type system
for account balance data fetched from a network call — a balance that
FAILS to load is represented as `nil` (an explicit, type-checked
absence), forcing every part of the UI that displays a balance to
EXPLICITLY handle the "not yet loaded" or "failed to load" case at
compile time — this is a direct, meaningful safety benefit specifically
relevant for a financial app, where silently displaying a stale or
incorrect balance due to an unhandled null case would be a genuinely serious bug.
"""
