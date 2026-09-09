# Full-Stack & Frontend Essentials — Principal Engineer Deep Dive

Companion to the existing lessons. Narrative depth, then a comprehensive
common-to-uncommon tool reference across the modern frontend/full-stack landscape.


## Rendering Strategies: CSR, SSR, SSG, ISR

**Beyond the lesson**: These aren't just "React features" — they're
different answers to the SAME tradeoff (time-to-first-byte vs
interactivity vs infrastructure cost). CSR (Client-Side Rendering) ships a
near-empty HTML shell and lets JS render everything — worst initial load/
SEO, simplest infra (just a CDN for static files). SSR (Server-Side
Rendering) renders full HTML per-request on a server — good SEO/fast
first paint, but needs a running server (not just a CDN) and adds
per-request compute cost. SSG (Static Site Generation) pre-renders every
page at BUILD time — fastest possible serving (pure CDN, no server compute
per request) but content can only update on a rebuild. ISR (Incremental
Static Regeneration, Next.js's contribution) lets a statically generated
page be regenerated in the background after a set interval — getting SSG's
serving speed with content that isn't fully frozen at build time.

**Worked example**: React Server Components (RSC, Next.js App Router) push
this further — components can run ENTIRELY on the server (fetching data,
rendering to HTML, sending zero JS to the client for that component) while
OTHER components on the same page are Client Components that hydrate
normally — a genuinely new mental model where "is this server or client"
is a per-COMPONENT decision, not a whole-page/whole-app one.

**Interview Q&A**:
- *Q: When would SSG be the wrong choice even for a marketing site?* A: When content changes frequently and per-user-personalized (A/B test variants, geo-based pricing) — SSG bakes ONE version at build time; that use case needs SSR or edge middleware doing request-time logic, not a page frozen until the next deploy.


## State Management Evolution

**Beyond the lesson**: Redux's "one global store, dispatch actions,
reducers compute new state" model solved a real problem (prop-drilling,
inconsistent state across a large app) but at a real BOILERPLATE cost —
the industry's subsequent evolution (Context API for simpler cases,
Zustand/Jotai for less-ceremony global state, React Query/TanStack Query
for SERVER state specifically) reflects a genuine insight: most "global
state" in a real app is actually CACHED SERVER DATA (fetched from an API),
not truly client-only state, and treating it as such (with automatic
caching, refetching, and invalidation) eliminates most of what Redux
required manual reducer code to handle.

**Interview Q&A**:
- *Q: Why has "server state" become its own category, separate from client state management?* A: Server state has fundamentally different needs — it can go STALE (someone else changed the data), needs refetching/caching/invalidation logic, and is asynchronous by nature; client-only state (a form's current input, a modal's open/closed state) has none of those concerns — tools like React Query specifically target the former, leaving simple client state to `useState`/Zustand/Context.


## COMPREHENSIVE TOOL & PRACTICE REFERENCE — COMMON TO UNCOMMON

### Frameworks & meta-frameworks
- **React** (+ **Next.js**) — still the dominant combination; Next.js's
  App Router (RSC-based) is the current default for new projects.
- **Vue** (+ **Nuxt**) — the leading React alternative, generally
  considered gentler learning curve, strong in parts of Europe/Asia's job markets.
- **Svelte** (+ **SvelteKit**) — compiles away the framework at build
  time (no virtual DOM runtime overhead) — smaller bundle sizes, growing adoption.
- **SolidJS** — fine-grained reactivity without a virtual DOM, often
  benchmarked as one of the fastest frontend frameworks — smaller
  ecosystem, more niche but respected for raw performance.
- **Astro** — "islands architecture": ships zero JS by default, hydrates
  only the specific interactive components that need it — the modern
  answer for content-heavy sites (blogs, docs) that don't need a full SPA.
- **HTMX** — a genuinely different philosophy: extend HTML itself with
  attributes that fetch/swap server-rendered HTML fragments, skipping
  client-side frameworks/JSON APIs entirely for many interactions — a real,
  growing "you might not need React" movement, particularly paired with
  Django/Rails-style server-rendered backends.

### Build tooling
- **Vite** — the modern default build tool/dev server, replaced
  Create React App/Webpack-heavy setups for most new projects due to its
  much faster dev-server start (native ES modules, no full bundle needed for dev).
- **Turbopack** (Next.js's own, Rust-based) — Vercel's answer to even
  faster builds specifically within the Next.js ecosystem.
- **esbuild / SWC** — the Go/Rust-based compilers underneath most modern
  build tools, replacing Babel for most transpilation work due to
  dramatically faster compile speed.

### Styling
- **Tailwind CSS** — utility-first CSS, now the dominant styling approach
  in new projects — trades "separate CSS files" for composable utility
  classes directly in markup.
- **CSS Modules / styled-components / vanilla-extract** — component-
  scoped CSS approaches; styled-components' runtime CSS-in-JS cost is part
  of why vanilla-extract (zero-runtime, build-time CSS-in-JS) has gained
  traction as a performance-conscious alternative.
- **shadcn/ui** — not a component LIBRARY but a copy-paste-into-your-repo
  component collection built on Radix UI + Tailwind — a genuinely different
  distribution model (you own and can modify the code, versus importing an
  opaque dependency) that's become extremely popular.

### Web performance & Core Web Vitals
- **LCP (Largest Contentful Paint), INP (Interaction to Next Paint,
  replaced FID), CLS (Cumulative Layout Shift)** — Google's Core Web
  Vitals, directly affecting SEO ranking, not just UX — a real business
  metric, not just an engineering nicety.
- **Lighthouse / WebPageTest** — the standard tools for measuring these; CI
  integration (Lighthouse CI) catches performance regressions before merge.
- **Bundle analysis** (webpack-bundle-analyzer, source-map-explorer) —
  identifying what's actually bloating a JS bundle, a real recurring
  performance-debugging task.

### Testing (frontend-specific)
- **Testing Library** (React/Vue/etc. Testing Library) — the dominant
  philosophy: test components the way a USER interacts with them (query by
  visible text/role, not implementation details like internal state) —
  explicitly designed to make tests resilient to refactors.
- **Playwright / Cypress** — E2E testing (see Testing & QA Engineering
  Notes for the deep version) — Playwright's multi-browser, auto-waiting
  model has become the more common modern default over Cypress for new projects.
- **Storybook** — isolated component development/documentation/visual
  testing — lets a component be built and tested independent of the full
  app it lives in, and increasingly used for visual regression testing (Chromatic).


## NICHE BUT REAL

- **Micro-frontends** — splitting a large frontend into independently
  deployable pieces owned by different teams (Module Federation being the
  most common mechanism) — solves organizational scaling at the cost of
  real complexity (shared dependency versioning, consistent UX across
  independently-built pieces) — a genuine "only reach for this at real organizational scale" pattern.
- **Progressive Web Apps (PWAs)** — service workers for offline
  support/caching, installable-to-homescreen manifests — less hyped than a
  few years ago but still the correct answer for specific offline-first use cases.
- **WebAssembly (WASM) in the frontend** — running non-JS code (Rust, C++,
  Go) in the browser at near-native speed — used for CPU-heavy tasks
  (image/video editing, CAD, games) where JS performance genuinely isn't
  enough, a real and growing niche rather than a novelty.
- **Accessibility (a11y) tooling** — axe-core, Lighthouse's a11y audit,
  and semantic HTML/ARIA attribute discipline are increasingly a LEGAL
  requirement (ADA lawsuits over inaccessible sites are real and growing)
  as well as a UX one — see the new Web Performance & Accessibility domain
  for the full treatment.
- **Edge middleware** (Next.js Middleware, Cloudflare Workers) — running
  logic (auth checks, A/B test bucketing, redirects) at the CDN edge
  BEFORE a request reaches origin — see Edge Computing Notes deep dive for
  the underlying platform mechanics.
