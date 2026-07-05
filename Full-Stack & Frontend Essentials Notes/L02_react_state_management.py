# ============================================================
# L02: React State Management — Context API, Redux/Zustand, When to Escalate
# ============================================================
# WHAT: What happens when L01's component-local `useState` isn't
#       enough — PROP DRILLING and the problem it causes, the built-in
#       Context API, and external state libraries (Redux, Zustand) —
#       plus, critically, WHEN each level of complexity is actually justified.
# WHY: A real application has state that MANY components need (the
#      current user, a shopping cart, chat session state) — passing it
#      down through props at every level becomes unmanageable, and
#      knowing which state-management tool fits which scale of problem
#      is a genuine, common architectural decision.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
PROP DRILLING is the problem that motivates everything else in this
lesson: if a piece of state lives in a TOP-level component but is
needed by a DEEPLY NESTED child, it must be passed as a prop through
EVERY intermediate component in between — even ones that don't
themselves use that data at all, just forward it along. This becomes a
real maintenance burden as an app grows: adding a new piece of shared
state means touching every intermediate component in the chain, and
refactoring the component tree's shape breaks the prop-passing chain.

THE CONTEXT API is React's BUILT-IN solution: a `Context` lets a
top-level PROVIDER component make a value available to ANY descendant
component that explicitly subscribes via `useContext`, WITHOUT passing
it through every intermediate level's props — solving prop drilling
directly. Context is well-suited to state that's genuinely GLOBAL-ish
but changes INFREQUENTLY (current user/auth state, theme/locale
settings) — because EVERY component consuming a Context re-renders
whenever that Context's value changes, Context becomes a PERFORMANCE
problem for FREQUENTLY-CHANGING state shared across MANY components
(every consumer re-renders on every change, even ones only interested
in a small part of a larger context value).

EXTERNAL STATE LIBRARIES (Redux, Zustand, and others) exist for LARGER-
SCALE, more FREQUENTLY-CHANGING shared state, where Context's re-render-
everything-on-any-change behavior becomes a genuine problem. REDUX is
the older, more STRUCTURED approach — a single global store, state
changes only via explicitly dispatched ACTIONS processed by pure
REDUCER functions, with strong conventions around predictability and
debuggability (time-travel debugging, a clear audit trail of every state
change) at the cost of more BOILERPLATE code per feature. ZUSTAND is a
newer, more MINIMAL alternative — achieving similar global-state
capability with dramatically less boilerplate, using React hooks
directly rather than Redux's provider/connect pattern, at the cost of
less of Redux's opinionated structure for very large, complex applications.

THE ESCALATION DECISION (component state -> Context -> external library)
should be driven by ACTUAL, OBSERVED need, not adopted preemptively —
starting with `useState` for genuinely local state, reaching for Context
only when prop drilling becomes a real, measured problem, and reaching
for Redux/Zustand only when Context's re-render behavior becomes a
measured PERFORMANCE problem, or when a codebase's SCALE genuinely
benefits from a more structured, testable state architecture.

PRODUCTION USE CASE:
An AI chat application starts with `useState` for message list state
(genuinely local to the `ChatWindow` component). As the app grows to
need the CURRENT USER's identity/permissions across many unrelated
components (a header, a settings page, an admin panel), Context is
introduced specifically for that infrequently-changing auth state. Later,
as the app adds a complex, frequently-updating "live agent activity feed"
shared across many components with different rendering needs, the team
migrates THAT specific state to Zustand, since Context would cause every
consumer to re-render on every activity update, regardless of whether
that consumer cared about the specific update.

COMMON MISTAKES:
- Reaching for Redux (or any external library) on a small/early-stage
  application "to be safe," before prop drilling or Context's
  limitations have actually become a REAL, measured problem — this adds
  real complexity/boilerplate cost with no corresponding benefit yet.
- Using Context for FREQUENTLY-CHANGING, PERFORMANCE-SENSITIVE state
  shared across MANY components — every context consumer re-renders on
  every value change, which can cause real, measurable performance
  problems at that specific combination of frequency and consumer count.
- Storing EVERYTHING in global state (Context or Redux/Zustand) rather
  than keeping GENUINELY LOCAL state (a form input's current value, a
  dropdown's open/closed state) in `useState` where it belongs — global
  state that should have been local makes the application harder to
  reason about and can cause unnecessary re-renders across unrelated components.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Prop drilling, illustrated
# ------------------------------------------------------------------
PROP_DRILLING_EXAMPLE = textwrap.dedent("""\
    // `currentUser` must be passed through EVERY intermediate component,
    // even ones (Layout, Sidebar) that never actually USE it themselves
    // — just forward it to whatever eventually needs it.
    function App() {
      const currentUser = { name: "Priya", role: "admin" };
      return <Layout currentUser={currentUser} />;
    }
    function Layout({ currentUser }) {
      return <Sidebar currentUser={currentUser} />;   // just forwarding
    }
    function Sidebar({ currentUser }) {
      return <UserProfile currentUser={currentUser} />;   // finally used HERE
    }
""")

# ------------------------------------------------------------------
# 2. Context API — solving prop drilling for infrequently-changing state
# ------------------------------------------------------------------
CONTEXT_API_EXAMPLE = textwrap.dedent("""\
    import { createContext, useContext } from 'react';

    const UserContext = createContext(null);

    function App() {
      const currentUser = { name: "Priya", role: "admin" };
      return (
        <UserContext.Provider value={currentUser}>
          <Layout />   {/* no need to pass currentUser as a prop AT ALL */}
        </UserContext.Provider>
      );
    }

    function Layout() {
      return <Sidebar />;   // Layout never touches currentUser — no
                              // pass-through needed
    }

    function UserProfile() {
      // ANY descendant can subscribe directly, no matter how deeply
      // nested, WITHOUT the intermediate components knowing/caring.
      const currentUser = useContext(UserContext);
      return <p>{currentUser.name} ({currentUser.role})</p>;
    }

    // CAVEAT: every component calling useContext(UserContext) re-renders
    // whenever the Provider's value CHANGES — fine for auth/theme state
    // that changes rarely; a real performance concern for state that
    // changes frequently and has MANY consumers.
""")

# ------------------------------------------------------------------
# 3. Zustand — minimal external state for frequently-changing, shared state
# ------------------------------------------------------------------
ZUSTAND_EXAMPLE = textwrap.dedent("""\
    import { create } from 'zustand';

    // ONE hook, no Provider component needed, no action/reducer boilerplate.
    const useActivityStore = create((set) => ({
      activities: [],
      addActivity: (activity) => set((state) => ({
        activities: [...state.activities, activity],
      })),
    }));

    // Any component can subscribe to JUST the slice it needs — a
    // component reading ONLY `activities` does NOT re-render when some
    // OTHER, unrelated piece of the store changes, unlike Context's
    // all-consumers-re-render-on-any-change behavior.
    function ActivityFeed() {
      const activities = useActivityStore((state) => state.activities);
      return (
        <ul>{activities.map(a => <li key={a.id}>{a.text}</li>)}</ul>
      );
    }

    function ActivityInput() {
      const addActivity = useActivityStore((state) => state.addActivity);
      return <button onClick={() => addActivity({ id: 1, text: "New event" })}>Add</button>;
    }
""")

# ------------------------------------------------------------------
# 4. Redux — the more structured, boilerplate-heavier alternative
# ------------------------------------------------------------------
REDUX_NOTE = textwrap.dedent("""\
    Redux achieves similar capability to Zustand but with more explicit
    structure: state changes ONLY via dispatched ACTIONS (plain objects
    describing "what happened"), processed by pure REDUCER functions
    (state, action) => newState — this strict pattern gives strong
    debuggability (a complete, replayable log of every state change) and
    testability (reducers are pure functions, trivial to unit test) at
    the cost of meaningfully more boilerplate per feature than Zustand's
    more direct hook-based API. Redux remains the right choice for very
    large applications where that strict structure and tooling ecosystem
    (Redux DevTools' time-travel debugging) pays for its added ceremony.
""")

# ------------------------------------------------------------------
# 5. The escalation decision framework
# ------------------------------------------------------------------
STATE_ESCALATION_GUIDE = {
    "useState (L01)": "Genuinely LOCAL state — a form field, a "
        "dropdown's open state, anything only ONE component (and maybe "
        "its direct children via props) needs.",
    "Context API": "State shared ACROSS the tree but changing "
        "INFREQUENTLY — current user, theme, locale — where prop "
        "drilling is the actual, observed pain point.",
    "Zustand": "Shared state that changes FREQUENTLY and/or has MANY "
        "consumers, where Context's re-render-everything behavior "
        "becomes a measured performance problem, without wanting "
        "Redux's full ceremony.",
    "Redux": "Very large applications benefiting from strict action/"
        "reducer structure, strong debuggability tooling, and an "
        "established team convention already built around it.",
}


if __name__ == "__main__":
    print(PROP_DRILLING_EXAMPLE)
    print(CONTEXT_API_EXAMPLE)
    print(ZUSTAND_EXAMPLE)
    print(REDUX_NOTE)
    print("=== State management escalation guide ===")
    for tool, guidance in STATE_ESCALATION_GUIDE.items():
        print(f"{tool}: {guidance}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
An AI agent-monitoring dashboard starts simple (useState per component),
adds Context for auth/theme once genuine prop-drilling pain appears
across unrelated pages, and later migrates its live, frequently-updating
"active agent runs" feed to Zustand after profiling revealed Context-
based implementation was causing the ENTIRE sidebar to re-render on
every single agent-status update, even for components displaying
completely unrelated agent runs — a concrete, measured performance
problem that justified the escalation, rather than adopting Zustand preemptively.
"""
