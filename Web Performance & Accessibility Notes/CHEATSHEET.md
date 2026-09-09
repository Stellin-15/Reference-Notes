# Web Performance & Accessibility — In-Depth Reference

Core Web Vitals in depth, and accessibility as both a legal requirement
and a genuine engineering discipline — the two topics Full-Stack &
Frontend Essentials Notes only touches briefly.


## 1. CORE WEB VITALS, PRECISELY

- **LCP (Largest Contentful Paint)** — time until the largest visible
  element (usually a hero image or heading) renders — target under 2.5s.
  Common fixes: preload critical images/fonts, avoid render-blocking
  resources, use a CDN (see Networking/Edge Computing deep dives).
- **INP (Interaction to Next Paint)** — replaced FID (First Input Delay)
  as the official metric — measures responsiveness across the ENTIRE
  page lifecycle (not just the first interaction) — target under 200ms.
  Long JavaScript tasks blocking the main thread are the primary
  culprit; breaking up long tasks (or moving work off the main thread
  via Web Workers) is the standard fix.
- **CLS (Cumulative Layout Shift)** — measures visual stability —
  unexpected layout shifts (an image loading without a reserved size,
  pushing content down after the user started reading) — target under
  0.1. Fixed by explicit width/height attributes (or `aspect-ratio` CSS)
  on images/embeds, and reserving space for dynamically-loaded content (ads, async-loaded widgets) upfront.

**Why these specific three metrics** — Google chose them because they
map to genuinely distinct, user-perceivable dimensions of "good
performance" (loading speed, interactivity, visual stability) rather
than a single composite score that could mask a bad experience in one
dimension while looking fine in aggregate — and because they directly
affect SEO ranking, they're a real business metric, not purely an engineering nicety.


## 2. PERFORMANCE OPTIMIZATION TECHNIQUES, ORGANIZED BY LEVER

- **Reduce what's shipped**: code splitting (load only what's needed for
  the current route/view), tree shaking (eliminate unused code at build
  time), image optimization (modern formats — WebP/AVIF — and responsive
  `srcset` sizing).
- **Reduce what blocks rendering**: critical CSS inlining, deferring
  non-critical JS (`defer`/`async` attributes), font-loading strategies
  (`font-display: swap` to avoid invisible-text-while-loading).
- **Cache aggressively**: HTTP caching headers (see Networking deep
  dive), service-worker-based offline caching (PWAs, see Full-Stack deep
  dive), CDN edge caching for static assets.
- **Reduce server response time**: server-side rendering optimization,
  database query optimization (see SQL deep dive), edge functions for
  latency-sensitive logic (see Edge Computing deep dive).


## 3. ACCESSIBILITY (a11y) — WCAG & PRACTICAL IMPLEMENTATION

**WCAG (Web Content Accessibility Guidelines)** — the standard,
organized around 4 principles (POUR): Perceivable, Operable,
Understandable, Robust — with three conformance levels (A, AA, AAA); AA
is the practical, commonly-required standard (and increasingly a LEGAL
requirement — ADA lawsuits over inaccessible websites are real and growing in volume).

**Semantic HTML is the foundation** — using `<button>` instead of a
`<div onClick>`, `<nav>`/`<main>`/`<article>` instead of generic `<div>`s
— gives screen readers and assistive technology the structural
information they need FOR FREE, before any ARIA attribute is even
considered — the most common real accessibility mistake is reaching for
ARIA attributes to patch over non-semantic markup, when using the right
semantic element in the first place would have needed no patching at all.

```html
<!-- Wrong: no semantic meaning, no keyboard accessibility, no screen-reader affordance -->
<div onclick="submit()">Submit</div>

<!-- Right: native keyboard support, screen-reader announces role/state automatically -->
<button type="submit">Submit</button>

<!-- ARIA only where semantic HTML genuinely can't express the pattern -->
<div role="tablist" aria-label="Settings sections">
  <button role="tab" aria-selected="true" aria-controls="panel-1">General</button>
</div>
```

**Keyboard navigation** — every interactive element must be reachable and
operable via keyboard alone (Tab, Enter, Space, arrow keys as
appropriate) — a genuinely common real bug is a custom dropdown/modal
that works with a mouse but traps or loses keyboard focus entirely, making it unusable for keyboard-only or screen-reader users.

**Color contrast** — WCAG AA requires a minimum contrast ratio (4.5:1 for
normal text, 3:1 for large text) between text and background — a real,
objectively testable requirement (contrast checker tools give a pass/
fail answer), not a subjective design opinion.


## 4. TESTING & TOOLING

- **axe-core / axe DevTools** — the dominant automated accessibility
  testing library, catchable via CI integration — catches a genuine
  subset of issues (missing alt text, contrast failures, missing form
  labels) automatically, but automated tools can only catch roughly 30-
  40% of real WCAG issues — MANUAL testing (actual keyboard navigation,
  actual screen reader testing with VoiceOver/NVDA/JAWS) remains necessary for genuine coverage.
- **Lighthouse** — bundles both performance AND accessibility audits in
  one tool, commonly run in CI (Lighthouse CI) to catch regressions on every PR.
- **WebPageTest** — deeper, more configurable performance testing
  (multiple real device/network conditions) than Lighthouse's single-run model.


## 5. NICHE BUT REAL

- **Screen reader testing specifics** — VoiceOver (Mac/iOS, built in),
  NVDA (Windows, free/open-source), JAWS (Windows, the historical
  enterprise standard) — genuinely different in their exact behavior/
  quirks, meaning testing with only ONE screen reader can miss
  issues specific to another's implementation.
- **Reduced motion preferences** (`prefers-reduced-motion` media query)
  — respecting a user's OS-level setting to minimize animations —
  matters for both accessibility (vestibular disorders can be triggered
  by excessive motion) and is a real, easy-to-implement, often-skipped consideration.
- **Focus management in single-page apps** — client-side routing (no
  full page reload) means screen readers don't get the natural
  "new page loaded" announcement a traditional page navigation provides
  — SPAs must explicitly manage focus and ARIA live-region announcements
  on route changes, a genuinely common accessibility gap specific to
  modern JS-framework-based sites that traditional server-rendered sites don't have to solve for.
- **Performance budgets** — setting explicit, CI-enforced limits (max
  bundle size, max LCP) that FAIL a build if exceeded — turns performance
  from an occasionally-audited concern into a continuously-enforced one,
  the same "shift left" philosophy security/quality gates apply (see CI/CD deep dive).
- **INP's replacement of FID, and why it matters more** — FID only
  measured the delay before the FIRST interaction's response began; INP
  measures responsiveness across ALL interactions throughout the page's
  lifetime, catching a page that's fast to first-respond but becomes
  janky after several interactions (a real, common pattern FID entirely missed) — worth knowing this metric evolution by name.
