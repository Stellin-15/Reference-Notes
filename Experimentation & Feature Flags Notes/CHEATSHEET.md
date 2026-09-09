# Experimentation & Feature Flags — In-Depth Reference

Decoupling deploy from release, and the statistics behind trusting an
A/B test result — the product-engineering discipline sitting between
DevOps deployment mechanics and Data Science statistical rigor.


## 1. FEATURE FLAGS — THE DEPLOY/RELEASE DECOUPLING

A feature flag lets code ship to production DARK (deployed but inactive)
and be turned on independently, gradually, or per-segment — this
decoupling is the actual point: DEPLOYMENT (code reaches production
servers) and RELEASE (users can actually see/use the feature) become two
separate events, letting you deploy continuously without every deploy
being a release, and roll back a bad FEATURE instantly (flip a flag) without needing a full code rollback/redeploy.

```javascript
// Typical feature-flag SDK usage
if (flags.isEnabled('new-checkout-flow', { userId: user.id })) {
  return renderNewCheckout();
}
return renderOldCheckout();
```

**Flag types, precisely distinguished**:
- **Release flags** — temporary, removed once a feature is fully rolled out.
- **Ops flags** — kill switches for operational control (disable a
  degraded feature under load) — often LONG-LIVED, kept permanently as an emergency lever.
- **Experiment flags** — control A/B test variant assignment.
- **Permission flags** — gate features by plan/entitlement (a paid-tier feature) — permanent, business-logic-driven.

**Flag debt** — a real, common organizational problem: release flags that
are never cleaned up after full rollout accumulate as permanent
technical debt, eventually making the codebase's actual behavior hard to
reason about (dozens of stale flags nobody's sure are still checked
anywhere meaningfully) — disciplined flag lifecycle management
(mandatory cleanup after full rollout, flag expiration alerts) is a real, necessary practice, not bureaucratic overhead.


## 2. A/B TESTING STATISTICS — DOING IT RIGHT

See Data Science Fundamentals deep dive for the full p-value/hypothesis-
testing treatment — the experimentation-platform-specific concerns:

- **Sample size calculation BEFORE running the test** — determined by
  the minimum effect size you care about detecting, your desired
  statistical power (typically 80%), and baseline conversion rate —
  running a test without this calculation risks either wasting time on
  an underpowered test that can never reach significance, or stopping
  early on noise that looks significant by chance.
- **Novelty effects & primacy effects** — users often react differently
  to something simply because it's NEW (novelty effect, inflating
  early results) or resist a change simply because it's unfamiliar
  (primacy effect, deflating early results) — both fade over time,
  which is why experienced experimentation teams run tests long enough
  to see past this initial-reaction period, not just until "significance" first appears.
- **Guardrail metrics** — tracking metrics you're NOT trying to improve
  (page load time, error rate) alongside your primary success metric,
  specifically to catch a change that improves the target metric while
  quietly degrading something else — a genuinely important practice
  many naive A/B testing setups skip.


## 3. ROLLOUT STRATEGIES

- **Percentage rollout** — gradually increasing the % of traffic exposed
  to a new feature (1% → 10% → 50% → 100%), watching guardrail metrics
  at each stage before proceeding — the standard risk-mitigation pattern for any non-trivial change.
- **Ring deployment / dogfooding** — internal employees first, then a
  small beta cohort, then general availability — catches obvious issues
  with a low-stakes audience before wider exposure.
- **Targeting rules** — rolling out by user segment (geography, plan
  tier, account age) rather than random percentage, when the feature is
  specifically relevant to (or riskier for) a particular segment.


## 4. NICHE BUT REAL

- **Flag evaluation performance** — client-side flag evaluation
  (LaunchDarkly/similar SDKs cache flag rules locally, evaluating without
  a network call per check) versus a naive "call an API for every flag
  check" implementation — the LATENCY difference is significant at
  scale, and understanding WHY SDKs are architected around local
  evaluation with background rule syncing (not per-request API calls) is
  a real infrastructure-design signal.
- **Multi-armed bandits vs fixed-split A/B tests** (see Data Science
  Fundamentals deep dive) — a real, more sample-efficient alternative
  when you want to MINIMIZE the cost of running an inferior variant
  during the test itself, rather than accepting a fixed 50/50 split for the full test duration.
- **Sequential testing / always-valid p-values** — statistical methods
  specifically designed to let you monitor a test's results CONTINUOUSLY
  without inflating the false-positive rate the way naive "peek and stop
  early" behavior does with standard fixed-sample-size hypothesis testing
  — a genuinely more sophisticated, increasingly adopted approach for
  teams that want to stop tests early when a clear winner emerges, correctly.
- **Feature flag as a circuit breaker** — using an "ops flag" to
  instantly disable a feature that's causing production issues is
  functionally similar to (and often faster than) the circuit-breaker
  resilience pattern (see System Design deep dive) — worth recognizing
  feature flags as a genuine operational RELIABILITY tool, not purely a product-experimentation one.
- **Interaction effects between concurrent experiments** — running many
  simultaneous experiments risks two flags/tests interacting in
  unexpected ways (a UI experiment and a pricing experiment both
  targeting the same checkout flow) — mature experimentation platforms
  implement mutual-exclusion groups or explicit interaction monitoring specifically to catch this.
