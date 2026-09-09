# System Design — Principal Engineer Deep Dive

Companion to the existing lessons. Narrative depth, then a comprehensive
common-to-uncommon reference synthesizing patterns from across the repo.


## Capacity Estimation — The Skill That Separates Senior From Principal

**Beyond the lesson**: Back-of-envelope capacity estimation isn't about
getting an exactly correct number — it's about identifying WHICH
dimension (storage, bandwidth, QPS, compute) will actually be the
bottleneck BEFORE committing to an architecture. A genuinely useful
estimation exercise: for a URL shortener serving 100M requests/day, that's
roughly 1,150 QPS average — but the design-relevant number is PEAK QPS
(often 5-10x average for a global product with regional traffic peaks),
and the actual bottleneck question isn't "can we handle 1,150 QPS" (any
reasonable web server can) — it's "can our DATABASE handle that read
volume with acceptable latency," which immediately points toward caching
(see Redis & Caching deep dive) as a near-certain requirement, derived
from the numbers rather than assumed by convention.

**Interview Q&A**:
- *Q: You're designing a system and the interviewer asks for capacity estimates. What's the actual PURPOSE of this exercise, beyond producing a number?* A: To surface which architectural decisions are actually FORCED by scale (do we need sharding? caching? a CDN?) versus which are premature optimization for a scale that may never materialize — the numbers justify the design choices that follow, and a design that doesn't reference back to its own capacity estimate at decision points is missing the actual point of doing the estimation at all.


## CAP, Consistency & the Real Design Conversation

**Beyond the lesson**: Bringing up "CAP theorem" in a system design
interview without applying it to the SPECIFIC component being discussed
is a common, weak answer — the strong answer identifies WHICH part of
the system needs which guarantee: a payment ledger needs strong
consistency (see SQL Notes deep dive's isolation-levels discussion) and
would rather be unavailable than inconsistent; a social media "like
count" can tolerate eventual consistency (a slightly stale count is
fine) in exchange for availability and low latency — the skill is
mapping consistency requirements to SPECIFIC subsystems, not applying one
blanket consistency philosophy to an entire system design.

**Interview Q&A**:
- *Q: You're designing a ride-sharing app's driver-location system. Does it need strong consistency?* A: No — a driver's location shown to nearby riders can tolerate a few seconds of staleness (eventual consistency, likely via a fast in-memory geospatial store updated on a short interval) — trading strict consistency for availability/low latency here is the right call, in contrast to the SAME app's payment/fare-calculation subsystem, which absolutely needs strong consistency.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Core scaling patterns, when each actually applies
- **Vertical vs horizontal scaling** — vertical (bigger machine) is
  simpler but hits a hard ceiling and a single point of failure; horizontal
  (more machines) scales further but requires the application to actually
  be STATELESS (or externalize state) to distribute load correctly.
- **Caching layers** (see Redis & Caching deep dive) — the single highest-
  leverage, most commonly reached-for scaling technique, precisely
  because most real workloads are read-heavy with a long tail of hot data.
- **Database sharding** — horizontal partitioning by a shard key; the
  hardest-to-reverse scaling decision in most systems (re-sharding later
  is genuinely painful), which is why shard-key choice deserves
  disproportionate design-interview attention versus other, more reversible decisions.
- **CDN & edge caching** (see Networking and Edge Computing deep dives) —
  the first lever for anything serving static or cacheable content
  globally, before considering any backend architectural change at all.

### Communication patterns between services
- **Synchronous (REST/gRPC) vs asynchronous (message queue/event)** —
  synchronous is simpler to reason about but couples the CALLER's
  availability to the CALLEE's; async decouples availability at the cost
  of eventual-consistency complexity and harder end-to-end debugging (see
  Message Queues & Brokers and Event-Driven & Real-Time AI Systems deep dives).
- **Service mesh** (see Kubernetes deep dive) — once a system has enough
  services that cross-cutting concerns (retries, mTLS, observability)
  become repetitive to implement per-service, a mesh centralizes them —
  a genuinely scale-dependent decision, not a default for every microservices system.

### Reliability patterns
- **Circuit breakers** — stop calling a failing downstream dependency
  after repeated failures, failing FAST instead of piling up slow,
  eventually-timing-out requests that can cascade into resource
  exhaustion upstream — a real, essential pattern for any system with
  synchronous dependencies on other services.
- **Bulkheads** — isolating resources (thread pools, connection pools) per
  downstream dependency so ONE failing dependency can't exhaust resources
  needed by calls to OTHER, healthy dependencies — the resilience-
  engineering equivalent of a ship's watertight compartments, literally the pattern's namesake.
- **Idempotency keys** (see API Design deep dive) — essential for any
  retry-safe distributed operation, since network partitions/timeouts
  make "did that request actually succeed" genuinely ambiguous without them.

### Data modeling & storage selection
- Cross-reference SQL, NoSQL & Specialized Databases, and Search Engines
  deep dives — the actual system-design skill is matching each
  subsystem's ACCESS PATTERN to the right storage technology, not
  defaulting to "one database for everything" or conversely
  over-engineering with too many specialized stores before scale actually demands it.


## NICHE BUT REAL

- **The "boring technology" principle** — a real, named engineering
  philosophy (articulated by Dan McKinley) arguing that a team has a
  limited budget of "innovation tokens" — choosing well-understood,
  battle-tested technology for MOST of a system frees up that budget for
  the few components that genuinely need something novel — a real,
  legitimate counter-argument to reflexively reaching for the newest
  tool in every system design discussion.
- **Read-your-writes consistency** — a specific, useful middle-ground
  consistency guarantee: a user always sees their OWN writes immediately
  (even under an otherwise eventually-consistent system), just not
  necessarily other users' writes instantly — solves the common "I just
  posted a comment and it's not showing up" UX complaint without needing full strong consistency system-wide.
- **Backpressure as a first-class design concern** — designing explicitly
  for what happens when a downstream system can't keep up (queue growth,
  load shedding, graceful degradation) rather than assuming infinite
  downstream capacity — a genuinely distinguishing mark of a mature system
  design versus one that only considers the happy path at expected load.
- **Design for observability from the start** — a system design that
  doesn't address HOW you'll know it's working correctly in production
  (see Observability Notes deep dive) is incomplete regardless of how
  elegant its scaling story is — increasingly, interviewers explicitly probe for this as a signal of production-readiness thinking.
