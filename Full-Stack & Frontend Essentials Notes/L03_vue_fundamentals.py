# ============================================================
# L03: Vue Fundamentals — Composition API, Reactivity
# ============================================================
# WHAT: Vue 3's Composition API — `ref`/`reactive` for state, `computed`
#       for derived values, `watch`/`watchEffect` for side effects — and
#       how Vue's REACTIVITY MODEL differs fundamentally from React's
#       re-render-and-diff approach from L01-L02.
# WHY: React (L01-L02) and Vue are the two dominant frontend frameworks
#      you'll encounter across real job postings and codebases — Vue's
#      genuinely different underlying model (fine-grained reactivity vs
#      React's virtual-DOM re-rendering) is worth understanding on its
#      own terms, not just as "React with different syntax."
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
VUE'S REACTIVITY MODEL is FUNDAMENTALLY different from React's: Vue uses
FINE-GRAINED, DEPENDENCY-TRACKED reactivity — when you read a `reactive`
or `ref` value inside a template or a `computed`/`watchEffect`, Vue
automatically TRACKS that dependency, and when the underlying value
LATER changes, Vue knows EXACTLY which parts of the UI depend on it and
updates ONLY those, without needing to re-run the entire component
function and diff a virtual DOM tree (React's approach, L01-L02). This
is a genuinely different mental model: React re-renders a COMPONENT
FUNCTION and reconciles the result; Vue tracks INDIVIDUAL VALUE
dependencies and updates the SPECIFIC DOM nodes that depend on them directly.

`ref()` wraps a PRIMITIVE value (a number, string, boolean) in a
reactive object — you must access/modify it via `.value` in JavaScript
code (though Vue's template syntax automatically "unwraps" this, so you
write just `count` in the template, not `count.value`). `reactive()`
wraps an OBJECT, making its PROPERTIES reactive directly (no `.value`
needed, since you're accessing object properties, not a wrapped primitive).

`computed()` defines a DERIVED value that automatically RECOMPUTES only
when its underlying reactive DEPENDENCIES change — and, importantly, is
CACHED between those changes (accessing it multiple times without any
dependency changing returns the cached value, not recomputing every
time) — directly analogous to what a React developer might reach for
`useMemo` to achieve, but automatic/implicit in Vue rather than requiring
an explicit dependency array.

`watch()` and `watchEffect()` are Vue's side-effect mechanisms
(analogous to React's `useEffect`, L01) — `watch()` explicitly specifies
WHICH reactive source to watch and runs a callback when it changes
(similar to `useEffect` with a specific dependency array); `watchEffect()`
AUTOMATICALLY tracks whatever reactive values its callback function
actually reads, re-running whenever ANY of them change, without you
manually declaring a dependency list at all — a genuine ergonomic
difference from React's requirement to explicitly and correctly list every dependency.

PRODUCTION USE CASE:
A dashboard displaying a computed "total agent cost this month" value
(derived from a reactive array of individual agent-run cost records)
uses Vue's `computed()` — the value automatically, efficiently
recalculates ONLY when the underlying cost records array actually
changes, and Vue's fine-grained reactivity updates ONLY the specific DOM
text node displaying that total, without re-rendering the entire
dashboard component the way a naive React implementation without
`useMemo` might require re-running the whole render function for.

COMMON MISTAKES:
- Forgetting `.value` when accessing/modifying a `ref()` in JavaScript
  code (outside the template, where auto-unwrapping doesn't apply) —
  a common, easy-to-make error for developers coming from React, where
  there's no equivalent wrapper-object access pattern.
- Using `reactive()` on a value that gets ENTIRELY REPLACED (rather than
  having its properties mutated) — reactive's tracking is tied to the
  SPECIFIC object reference; replacing it entirely (`state =
  newObject`) loses reactivity unless you mutate the EXISTING reactive
  object's properties instead, or use `ref()` for values that are
  naturally reassigned wholesale.
- Using `watchEffect()` when you actually need PRECISE control over
  WHICH dependency triggers the callback (e.g. you read multiple
  reactive values in the callback but only want it to re-run when ONE
  specific one changes) — `watch()`'s explicit source specification is
  the right tool for that precision; `watchEffect()`'s automatic
  tracking of EVERYTHING it reads can trigger more often than intended.
"""

import textwrap


# ------------------------------------------------------------------
# 1. ref and reactive — the two core reactivity primitives
# ------------------------------------------------------------------
REF_AND_REACTIVE_EXAMPLE = textwrap.dedent("""\
    <script setup>
    import { ref, reactive } from 'vue';

    // ref() for a PRIMITIVE value — accessed/modified via .value in JS
    const count = ref(0);
    function increment() {
      count.value++;   // MUST use .value here, in script code
    }

    // reactive() for an OBJECT — properties are directly reactive, no .value
    const user = reactive({ name: 'Priya', role: 'admin' });
    function promoteUser() {
      user.role = 'superadmin';   // direct property mutation IS tracked
    }
    </script>

    <template>
      <!-- In the TEMPLATE, ref values are AUTOMATICALLY unwrapped —
           write `count`, not `count.value` -->
      <p>Count: {{ count }}</p>
      <button @click="increment">Increment</button>
      <p>{{ user.name }} ({{ user.role }})</p>
    </template>
""")

# ------------------------------------------------------------------
# 2. computed — cached, automatically-recalculating derived values
# ------------------------------------------------------------------
COMPUTED_EXAMPLE = textwrap.dedent("""\
    <script setup>
    import { ref, computed } from 'vue';

    const agentRuns = ref([
      { id: 1, cost: 0.42 },
      { id: 2, cost: 1.15 },
    ]);

    // totalCost AUTOMATICALLY recalculates ONLY when agentRuns.value
    // changes — and is CACHED (accessing it repeatedly without a
    // dependency change returns the cached result, no recomputation).
    const totalCost = computed(() =>
      agentRuns.value.reduce((sum, run) => sum + run.cost, 0)
    );
    </script>

    <template>
      <p>Total cost: ${{ totalCost.toFixed(2) }}</p>
    </template>
""")

# ------------------------------------------------------------------
# 3. watch vs watchEffect — explicit vs automatic dependency tracking
# ------------------------------------------------------------------
WATCH_EXAMPLES = textwrap.dedent("""\
    <script setup>
    import { ref, watch, watchEffect } from 'vue';

    const conversationId = ref('conv_1');
    const messages = ref([]);

    // watch(): EXPLICITLY specifies the source (conversationId) — the
    // callback runs ONLY when THIS specific value changes, analogous to
    // React's useEffect with a specific dependency array [conversationId].
    watch(conversationId, (newId, oldId) => {
      console.log(`Switching from ${oldId} to ${newId}`);
      connectToConversation(newId);
    });

    // watchEffect(): AUTOMATICALLY tracks EVERY reactive value the
    // callback reads — re-runs whenever ANY of them change, without an
    // explicit dependency list (unlike React, where an incomplete
    // dependency array is a common bug source, L01).
    watchEffect(() => {
      console.log(`Conversation ${conversationId.value} has ${messages.value.length} messages`);
      // automatically re-runs if EITHER conversationId OR messages changes
    });
    </script>
""")

# ------------------------------------------------------------------
# 4. Vue's reactivity vs React's re-render model — the core distinction
# ------------------------------------------------------------------
REACTIVITY_MODEL_COMPARISON = {
    "React (L01-L02)": "Re-renders the ENTIRE component FUNCTION on "
        "state change, then diffs a virtual DOM tree to determine "
        "minimal actual DOM updates — a coarser-grained model requiring "
        "explicit optimization (useMemo, React.memo) for fine-grained control.",
    "Vue": "Tracks INDIVIDUAL reactive value dependencies directly, "
        "updating ONLY the specific DOM nodes/computed values that "
        "depend on a changed value — fine-grained by DEFAULT, without "
        "needing explicit memoization in most cases.",
}


if __name__ == "__main__":
    print(REF_AND_REACTIVE_EXAMPLE)
    print(COMPUTED_EXAMPLE)
    print(WATCH_EXAMPLES)
    print("=== Reactivity model comparison ===")
    for framework, note in REACTIVITY_MODEL_COMPARISON.items():
        print(f"{framework}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A real-time agent-monitoring dashboard built in Vue uses `watchEffect`
to automatically re-establish a WebSocket subscription whenever EITHER
the selected agent ID OR a date-range filter changes — Vue's automatic
dependency tracking means the developer never has to remember to add a
new value to a dependency array (unlike the equivalent React
`useEffect`, L01) when a THIRD filter is later added to the dashboard —
the `watchEffect` callback automatically picks up the new dependency
simply by reading it, with zero risk of the "stale closure from a
missing dependency" bug class React's explicit-array model is prone to.
"""
