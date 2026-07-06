# ============================================================
# L05: Flutter — Cross-Platform Mobile with Dart and a Custom Rendering Engine
# ============================================================
# WHAT: How Flutter takes a FUNDAMENTALLY DIFFERENT architectural
#       approach than React Native (L04) to cross-platform development —
#       compiling to native code and rendering EVERY pixel itself via
#       its own engine, rather than bridging to native UI components.
# WHY: L04 covered React Native's bridge-to-native-components approach.
#      Flutter represents the OTHER major cross-platform strategy, with
#      genuinely different tradeoffs — this lesson covers those
#      differences concretely, completing this domain's cross-platform coverage.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
FLUTTER'S CORE ARCHITECTURAL DIFFERENCE FROM REACT NATIVE: rather than
mapping your UI code to REAL native platform components (React Native's
approach, L04), Flutter renders EVERY SINGLE PIXEL ITSELF using its own
high-performance rendering engine (Skia, and more recently Impeller) —
Flutter draws its own buttons, text, and UI elements directly onto a
canvas, rather than asking the OS to render a native button widget. This
means Flutter UI looks IDENTICAL across iOS and Android by default
(since Flutter is drawing everything itself, not delegating to each
platform's own native rendering) — a deliberate design tradeoff:
PERFECT visual consistency across platforms, at the cost of NOT
automatically inheriting each platform's native look-and-feel/
accessibility behaviors the way React Native's native-component
approach does more naturally.

DART, Flutter's programming language, COMPILES TO NATIVE MACHINE CODE
(via Ahead-of-Time compilation for release builds) — this is a
DIFFERENT execution model than React Native's JavaScript running in a
JS engine communicating across a bridge (L04) — Flutter code runs as
compiled native code directly, which AVOIDS the bridge-crossing
overhead concern L04 discussed entirely, since there's no separate
JavaScript runtime/bridge architecture involved at all — this is a
genuine, structural performance advantage for consistently smooth,
high-frame-rate UI, independent of any specific optimization library.

THE WIDGET TREE is Flutter's EVERYTHING-IS-A-WIDGET philosophy: not
just visible UI elements, but PADDING, ALIGNMENT, and even
ANIMATIONS are all represented as WIDGETS composed together in a tree —
this is DECLARATIVE (the same underlying philosophy as SwiftUI, L02;
Jetpack Compose, L03; and React, Full-Stack & Frontend Essentials Notes
L01) but taken to a more extreme, uniform degree — everything, without
exception, is a widget, composed via nesting, with NO separate
"styling system" distinct from the widget composition itself.

STATE MANAGEMENT in Flutter follows the SAME "escalate only as needed"
principle this repo has emphasized throughout (Full-Stack & Frontend
Essentials Notes L02, SwiftUI L02, Jetpack Compose L03): `setState()`
for simple, widget-local state; the Provider package or Riverpod for
shared state across a larger portion of the widget tree, similar in
spirit to React's Context/Zustand escalation path — the SPECIFIC
package names differ, but the underlying architectural principle (don't
reach for global state management until local state genuinely isn't sufficient) is identical.

WHEN FLUTTER'S APPROACH IS THE BETTER FIT vs REACT NATIVE'S: Flutter's
"draw everything itself" approach tends to produce MORE CONSISTENT
performance for complex, custom UI/animations (since it's not bridging
to native components with their own varying rendering characteristics
per platform), and pixel-perfect cross-platform visual consistency IS a
deliberate goal for some products (a strongly branded app wanting
identical visuals everywhere) — but products wanting to feel MAXIMALLY
NATIVE/idiomatic on each platform specifically (matching each platform's
own conventions rather than a unified custom look) may find React
Native's native-component approach a more natural fit for that specific goal.

PRODUCTION USE CASE:
Google's own Google Pay and Google Ads apps, along with numerous other
companies prioritizing pixel-perfect brand consistency across platforms
(e.g. many apps built by design-forward companies), choose Flutter
specifically because their design system requires IDENTICAL visual
presentation on iOS and Android — a goal Flutter's "render everything
itself" architecture achieves naturally, without the platform-specific
visual variance React Native's native-component bridging can introduce.

COMMON MISTAKES:
- Assuming Flutter apps automatically get each platform's native
  look-and-feel "for free" — since Flutter draws its OWN UI rather than
  using native components, achieving platform-idiomatic appearance
  (if desired) requires DELIBERATE design work (Flutter does provide
  both "Material" and "Cupertino" widget sets to help with this), not automatic inheritance.
- Choosing Flutter primarily because "Dart is easy to learn" without
  weighing the team's EXISTING skill investment — a team with deep React
  expertise may find React Native's more direct skill transfer
  outweighs Dart's genuine but comparatively modest learning-curve advantage.
- Assuming Flutter's compiled, bridge-free architecture makes ALL
  performance considerations moot — while it avoids React Native's
  SPECIFIC bridge-crossing overhead, genuinely complex custom rendering/
  animation logic still has real computational cost that needs the same
  general performance discipline any rendering-heavy application requires.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Flutter's widget tree — everything is a widget, composed
# ------------------------------------------------------------------
FLUTTER_WIDGET_TREE_EXAMPLE = textwrap.dedent("""\
    // Dart/Flutter — notice even PADDING and ALIGNMENT are widgets,
    // composed via nesting, not a separate CSS-like styling system
    class ProductDetailScreen extends StatefulWidget {
      final Product product;
      const ProductDetailScreen({required this.product});

      @override
      State<ProductDetailScreen> createState() => _ProductDetailScreenState();
    }

    class _ProductDetailScreenState extends State<ProductDetailScreen> {
      int quantity = 1;

      @override
      Widget build(BuildContext context) {
        return Padding(
          padding: const EdgeInsets.all(16.0),   // padding is itself a WIDGET
          child: Column(
            children: [
              Text(widget.product.name, style: TextStyle(fontSize: 20)),
              Text('Quantity: $quantity'),
              ElevatedButton(
                onPressed: () => setState(() => quantity++),
                // setState() triggers Flutter to re-render (repaint)
                // this widget and its descendants — the SAME declarative
                // "state changes -> automatic re-render" model as
                // SwiftUI/Compose/React, just implemented via Flutter's own engine
                child: Text('+'),
              ),
            ],
          ),
        );
      }
    }
""")

# ------------------------------------------------------------------
# 2. Rendering architecture comparison
# ------------------------------------------------------------------
RENDERING_ARCHITECTURE_COMPARISON = textwrap.dedent("""\
    React Native (L04):
      Your code -> JS engine -> BRIDGE -> Native platform components
      (Button, TextView) rendered by iOS/Android's OWN rendering system

    Flutter:
      Your code (Dart) -> compiled to native machine code -> Flutter's
      OWN rendering engine (Skia/Impeller) draws EVERY pixel directly
      No bridge, no delegation to platform-native UI components at all

    Practical consequence:
      React Native UI can pick up subtle PLATFORM-SPECIFIC rendering
      differences (since it's using REAL native components on each
      platform); Flutter UI looks IDENTICAL across platforms by default
      (since Flutter draws everything itself, uniformly) — a deliberate
      tradeoff, not an accident of implementation.
""")


if __name__ == "__main__":
    print(FLUTTER_WIDGET_TREE_EXAMPLE)
    print(RENDERING_ARCHITECTURE_COMPARISON)

"""
PRODUCTION CONTEXT EXAMPLE:
A fintech company building a strongly-branded mobile app across both
iOS and Android chooses Flutter specifically because their design
system mandates PIXEL-IDENTICAL visual presentation regardless of
platform (custom fonts, custom-drawn charts, consistent animation
timing) — achieving this level of cross-platform visual consistency
with React Native would require fighting against each platform's native
rendering differences at every turn, while Flutter's "draw everything
itself" architecture provides this consistency as a natural, structural
consequence of how it fundamentally works, rather than something requiring constant additional effort to maintain.
"""
