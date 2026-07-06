# ============================================================
# L04: React Native — Cross-Platform Mobile with JavaScript/React
# ============================================================
# WHAT: How React Native lets a SINGLE React-based codebase target both
#       iOS and Android — the bridge/native-module architecture that
#       makes this possible, and where it genuinely shines vs where it
#       falls short of native performance/fidelity.
# WHY: L02-L03 covered NATIVE development (separate codebases per
#      platform). React Native is the first of two CROSS-PLATFORM
#      options (Flutter, L05, is the other) — and specifically the
#      natural choice for teams already skilled in React (this repo's
#      Full-Stack & Frontend Essentials Notes L01-L02).
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
REACT NATIVE lets you write UI components using REACT'S component model
and JSX syntax (this repo's Full-Stack & Frontend Essentials Notes L01)
— but CRITICALLY, these components render to REAL, NATIVE platform UI
elements (an actual native `UIView` on iOS, an actual native `View` on
Android), NOT a web view rendering HTML/CSS — this is the key
architectural distinction from earlier "hybrid" mobile frameworks
(like Cordova/PhoneGap) that rendered a web page inside a native
wrapper; React Native components become GENUINE native UI, which is
what gives it meaningfully better performance and platform look-and-feel
fidelity than those older hybrid approaches.

THE BRIDGE (in React Native's original architecture) is the mechanism
connecting your JAVASCRIPT code (running in a JS engine) to the NATIVE
platform code that actually renders UI and accesses device
capabilities — JavaScript and native code run in SEPARATE
threads/environments, communicating via ASYNCHRONOUS, SERIALIZED
messages across this bridge. This architecture has a genuine
PERFORMANCE IMPLICATION: high-frequency communication across the bridge
(e.g. rapidly updating an animation's properties every frame) can
become a bottleneck, since every bridge crossing has real serialization
overhead — this is a well-known, actively-being-addressed limitation
(React Native's newer "Fabric" architecture and JSI - JavaScript
Interface - reduce this overhead by allowing more DIRECT communication),
but understanding the bridge concept explains WHY certain performance
patterns (like keeping animations on the "native" side via libraries
like Reanimated) matter specifically in React Native.

NATIVE MODULES let you write PLATFORM-SPECIFIC native code (Swift/
Objective-C for iOS, Kotlin/Java for Android) and EXPOSE it to your
JavaScript code as a callable module — this is the escape hatch for
accessing platform capabilities React Native's built-in components
don't cover, or for genuinely performance-critical code paths that
benefit from running natively rather than through the bridge — a
production React Native app frequently ends up with SOME native module
code, not purely JavaScript, especially as it needs deeper
platform-specific integration.

WHERE REACT NATIVE GENUINELY SHINES vs FALLS SHORT: it shines for teams
with EXISTING React/JavaScript expertise (direct skill transfer, per
L01's team-fit consideration), for apps where "good enough" native feel
across both platforms with a SINGLE codebase is the priority, and for
apps that share substantial business logic with an existing React web
app. It falls short for apps needing CUTTING-EDGE, day-one access to
brand-new OS features (native SDKs typically get platform-specific
features first, with cross-platform framework support following later),
or apps with extremely demanding, complex custom animations/graphics
where bridge overhead (even with newer architecture improvements)
remains a genuine performance consideration.

PRODUCTION USE CASE:
A company with an EXISTING, mature React-based web application (using
the same design system, business logic, and API layer this repo's
Full-Stack & Frontend Essentials Notes covers) builds a companion
mobile app in React Native specifically to REUSE a substantial portion
of their existing React component logic and their team's existing
JavaScript/React expertise, rather than building and maintaining two
entirely separate native codebases with a different team's skillset for each.

COMMON MISTAKES:
- Choosing React Native purely because "it's JavaScript" without
  evaluating whether the app's actual performance/platform-fidelity
  requirements are compatible with its architecture — an app requiring
  extremely demanding real-time graphics/animation may be a poor fit
  regardless of team skill-set familiarity.
- Performing high-frequency, performance-critical operations (complex
  animations, real-time data visualization) through the STANDARD bridge
  path without using performance-oriented libraries (like Reanimated,
  which moves animation logic to run natively) specifically designed to
  avoid the bridge's serialization overhead for these use cases.
- Assuming "cross-platform" means ZERO platform-specific code will ever
  be needed — most real React Native apps end up with SOME
  platform-specific branches or native modules for capabilities or
  polish the shared codebase alone doesn't fully cover; budgeting for
  this reality, rather than assuming a perfectly unified codebase, avoids unrealistic project planning.
"""

import textwrap


# ------------------------------------------------------------------
# 1. React Native component — real native UI, React's component model
# ------------------------------------------------------------------
REACT_NATIVE_COMPONENT_EXAMPLE = textwrap.dedent("""\
    // Looks like React (Full-Stack & Frontend Essentials Notes L01),
    // but <View> and <Text> render to REAL NATIVE UI elements,
    // not HTML divs/spans in a web view
    import { View, Text, Button, StyleSheet } from 'react-native';
    import { useState } from 'react';

    function ProductDetailScreen({ product }) {
      const [quantity, setQuantity] = useState(1);

      return (
        <View style={styles.container}>
          <Text style={styles.title}>{product.name}</Text>
          <Text>Quantity: {quantity}</Text>
          <Button title="+" onPress={() => setQuantity(quantity + 1)} />
          <Button title="Add to Cart" onPress={() => addToCart(product, quantity)} />
        </View>
      );
    }

    const styles = StyleSheet.create({
      container: { padding: 16 },
      title: { fontSize: 20, fontWeight: 'bold' },
    });
    // This EXACT component code produces a real native iOS view AND a
    // real native Android view — the SAME source, two native UIs.
""")

# ------------------------------------------------------------------
# 2. The bridge architecture and its performance implication
# ------------------------------------------------------------------
BRIDGE_ARCHITECTURE_ILLUSTRATION = textwrap.dedent("""\
    JavaScript thread                    Native (UI) thread
    (your React components,       <--->  (actual rendering,
     business logic)              BRIDGE  device APIs)
                                  (async,
                                  serialized
                                  messages)

    Each bridge crossing has REAL serialization overhead — fine for
    typical UI updates (button taps, list scrolling), but a genuine
    consideration for HIGH-FREQUENCY updates (60fps animations),
    which is why performance-oriented libraries move that specific
    work to run more DIRECTLY on the native side, minimizing bridge crossings.
""")

# ------------------------------------------------------------------
# 3. Native module — escape hatch for platform-specific capability
# ------------------------------------------------------------------
NATIVE_MODULE_EXAMPLE = textwrap.dedent("""\
    // Swift (iOS native module), exposing a native capability to JS:
    @objc(BiometricAuth)
    class BiometricAuth: NSObject {
      @objc func authenticate(_ resolve: @escaping RCTPromiseResolveBlock,
                                rejecter reject: @escaping RCTPromiseRejectBlock) {
        // ... real Face ID / Touch ID native implementation ...
        resolve(true)
      }
    }

    // JavaScript side, calling this native module like a normal async function:
    import { NativeModules } from 'react-native';
    const { BiometricAuth } = NativeModules;

    async function loginWithBiometrics() {
      const success = await BiometricAuth.authenticate();
      if (success) { navigateToHomeScreen(); }
    }
    // React Native's built-in components don't cover Face ID directly —
    // a native module bridges this platform-specific capability into JS.
""")


if __name__ == "__main__":
    print(REACT_NATIVE_COMPONENT_EXAMPLE)
    print(BRIDGE_ARCHITECTURE_ILLUSTRATION)
    print(NATIVE_MODULE_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
Meta (React Native's creator) uses it extensively across its own apps
specifically because of the enormous existing React/JavaScript
engineering talent pool internally — teams can move between web (React)
and mobile (React Native) codebases with substantial skill transfer,
while native modules handle the specific platform capabilities
(camera access, biometric auth, deep OS integrations) that the shared
JavaScript codebase alone doesn't cover — a genuine, large-scale
production validation of the tradeoffs this lesson describes.
"""
