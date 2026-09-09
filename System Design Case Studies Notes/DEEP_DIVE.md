# System Design Case Studies — Principal Engineer Deep Dive

Companion to the existing 30+ deep-dive lessons. Rather than duplicate
those worked examples, this file adds cross-cutting analysis techniques
and a comprehensive reference for approaching NOVEL case studies not
already covered by name.


## The Real Skill Being Tested: Requirement Clarification, Not Memorized Architecture

**Beyond the lesson**: The single biggest differentiator between a
senior and principal-level system design interview performance isn't
knowing more architecture patterns — it's asking the RIGHT clarifying
questions before designing anything. "Design Google Docs" is
underspecified until you've established: how many concurrent editors per
document (2 vs 200 changes the conflict-resolution architecture
entirely), whether offline editing needs to be supported (forces CRDT-
style conflict resolution, see Distributed Systems Theory deep dive, vs a
simpler locking approach), and what latency users actually need to see
others' edits (100ms feels "live"; 2 seconds feels "syncing," a
materially different architecture). A candidate who dives into
architecture without extracting these constraints first is optimizing
for the wrong problem, however elegant the resulting design looks in isolation.

**Interview Q&A**:
- *Q: An interviewer says "design a system like Spotify" with no further detail. What are your first 2-3 questions?* A: What's the core feature being tested (streaming playback? recommendation? social sharing?) — "design Spotify" is really several different systems; what scale (10K users vs 100M) — determines whether sharding/caching/CDN decisions are even relevant yet; and what's explicitly OUT of scope — establishing boundaries prevents spending the limited interview time on a tangential subsystem.


## Multiple Valid Answers — Why the Existing Case Studies Show 3 Approaches Each

**Beyond the lesson**: The existing case-study lessons deliberately present
multiple defensible architecture choices per problem — this reflects a
genuine truth about system design that's easy to lose sight of while
studying: there is rarely ONE correct answer, and a strong interview
performance is measured by whether you can articulate the TRADEOFFS
between reasonable alternatives, not whether you land on some "canonical"
solution. An interviewer probing "why not use approach X instead" isn't
necessarily signaling your answer was wrong — they're often testing
whether you understand WHY you chose your approach over the alternative,
which requires genuinely understanding both options' tradeoffs, not just defending your first instinct.

**Interview Q&A**:
- *Q: You proposed Kafka for an event pipeline and the interviewer asks "why not RabbitMQ?" Is this a signal you chose wrong?* A: Not necessarily — treat it as an invitation to articulate the tradeoff (see Message Queues & Brokers deep dive: Kafka for replay/high-throughput/log-based consumption, RabbitMQ for complex routing/simpler queue semantics) — a confident, specific comparison ("Kafka because we need consumer replay for reprocessing, which RabbitMQ's consume-and-delete model doesn't support") is a stronger answer than either defensiveness or immediately abandoning your choice.


## COMPREHENSIVE REFERENCE — A FRAMEWORK FOR NOVEL CASE STUDIES

### The standard interview structure, and why each step exists
1. **Clarify requirements & scope** (functional + non-functional) — see
   above; skipping this is the most common, most costly mistake.
2. **Capacity estimation** (see System Design deep dive) — surfaces which
   decisions are actually scale-forced.
3. **High-level architecture** — draw the major components and data flow
   BEFORE drilling into any one piece — resist the urge to over-detail
   the first component you think of.
4. **Deep dive on 1-2 components** the interviewer steers toward (or that
   you identify as most interesting/risky) — this is where most of the
   interview's actual signal comes from, not the high-level sketch.
5. **Address bottlenecks/failure modes explicitly** — a design that's
   never stress-tested against "what if this component goes down" or
   "what if traffic 10x's" is incomplete.
6. **Discuss tradeoffs of alternatives considered** — demonstrates
   breadth of knowledge and honest self-assessment of the chosen design's weaknesses.

### Common case-study archetypes and their DEFINING design tension
- **Social feed / timeline systems** (Twitter/Instagram-style) — the
  fan-out-on-write vs fan-out-on-read tension: precomputing every
  follower's feed on each post (fast reads, expensive for
  celebrity-scale follower counts) vs computing a feed on-demand at read
  time (cheap writes, slower reads) — most real systems use a HYBRID
  (fan-out-on-write for most users, fan-out-on-read for celebrity accounts specifically).
- **Rate limiters** — token bucket vs sliding window vs fixed window
  (see Networking Notes deep dive's rate-limiting coverage) — the
  defining tension is burst tolerance vs implementation/memory simplicity.
- **URL shorteners / ID generation** — the defining tension is
  collision-avoidance vs coordination overhead: a centralized counter is
  simple but a single point of failure/bottleneck; distributed ID
  generation (Snowflake-style, embedding a timestamp + machine ID +
  sequence number) avoids central coordination at the cost of slightly larger IDs.
- **Chat/messaging systems** — the defining tension is delivery
  guarantee vs latency: at-most-once (fast, can lose messages) vs
  at-least-once with deduplication (safer, more complex) vs true
  exactly-once (hardest, see Apache Kafka deep dive's exactly-once discussion).
- **Search/autocomplete systems** — the defining tension is index
  freshness vs query latency (see Search Engines deep dive) — a
  precomputed trie/index is blazing fast to query but needs a
  refresh strategy as underlying data changes.


## NICHE BUT REAL

- **The "back-of-the-napkin" numbers worth memorizing** — 1 million
  requests/day ≈ 12 requests/second average (a genuinely useful
  quick-conversion constant); a single modern server can typically handle
  low-thousands of QPS for simple requests; SSD read latency ~0.1ms vs
  network round-trip within a datacenter ~0.5ms vs cross-region ~50-150ms
  — having these orders-of-magnitude numbers memorized (not exact, just
  the right ORDER of magnitude) makes capacity estimation dramatically faster and more credible in an interview.
- **Whiteboard/diagramming discipline** — labeling data flow DIRECTION
  and PROTOCOL (sync HTTP vs async queue) explicitly on a system diagram,
  not just boxes and unlabeled arrows — a small habit that measurably
  improves how clearly a design communicates, and one experienced interviewers specifically notice.
- **Explicitly stating assumptions out loud** — "I'm assuming eventual
  consistency is acceptable here because X" turns a silent design choice
  into a discussable, defensible decision point — a real, learnable
  interview technique distinct from just knowing more architecture patterns.
