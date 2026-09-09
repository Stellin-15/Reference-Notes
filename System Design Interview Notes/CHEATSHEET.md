# System Design Interview — In-Depth Reference

Distinct from System Design Notes (architecture theory) and System
Design Case Studies Notes (worked examples) — this file is the
INTERVIEW-FORMAT rubric: how to structure 45 minutes, what interviewers
actually score, and level-specific expectations.


## 1. THE 45-MINUTE STRUCTURE

| Time | Phase | What's actually being evaluated |
|---|---|---|
| 0-5 min | Requirements clarification | Do you ask the RIGHT questions, or dive in blind? |
| 5-10 min | Capacity estimation | Can you translate requirements into numbers that drive design decisions? |
| 10-20 min | High-level design | Can you sketch a coherent architecture before over-detailing one piece? |
| 20-35 min | Deep dive | Real signal lives here — can you go deep on the component that matters? |
| 35-45 min | Bottlenecks, tradeoffs, wrap-up | Do you know your design's weaknesses, not just its strengths? |

**The single most common failure mode**: spending 25 of 45 minutes on
requirements/high-level design, leaving no time for a real deep dive —
interviewers score the DEEP DIVE most heavily, since it's where genuine
technical depth (vs memorized architecture diagrams) actually shows.


## 2. FUNCTIONAL VS NON-FUNCTIONAL REQUIREMENTS — SAY BOTH OUT LOUD

**Functional**: what the system DOES (users can post, follow, view a
feed). **Non-functional**: the qualities it must have (availability,
latency, consistency, scalability) — explicitly stating BOTH categories,
and which non-functional requirements take priority (e.g. "availability
over consistency for this specific feature") demonstrates a level of
rigor many candidates skip by jumping straight to functional requirements alone.


## 3. LEVEL-SPECIFIC EXPECTATIONS

- **Mid-level (L4/senior-adjacent)**: can design a reasonably-scoped
  single system correctly, understands basic tradeoffs (SQL vs NoSQL,
  caching, load balancing) when prompted.
- **Senior**: proactively identifies bottlenecks and tradeoffs without
  prompting, can go genuinely deep on at least one component
  (database schema, caching strategy, a specific algorithm) unprompted.
- **Staff/Principal**: additionally reasons about ORGANIZATIONAL
  constraints (team ownership boundaries, migration paths from an
  existing system, cost tradeoffs, operational/on-call burden of the
  proposed design) — the design isn't evaluated in a vacuum, it's
  evaluated as something a REAL organization would have to build, staff, and operate.


## 4. THE QUESTIONS THAT SEPARATE STRONG FROM WEAK ANSWERS

- "What happens when this component fails?" — a design with no answer
  here is incomplete regardless of how elegant the happy path is.
- "How would you migrate from the current system to this one?" — tests
  whether you're designing in a vacuum or thinking about REAL, incremental delivery.
- "How would you know if this is working correctly in production?" —
  tests observability-mindedness (see Observability deep dive) — a real,
  increasingly common probe.
- "What would you do differently with 10x the scale? With 1/10th the
  scale?" — tests whether your design choices are actually JUSTIFIED by
  the stated scale, or just defaults you'd apply regardless.


## 5. NICHE BUT REAL

- **The "I don't know, but here's how I'd find out" answer** — a
  genuinely strong response to a question outside your specific
  expertise, FAR better than guessing confidently and being wrong, or
  freezing — interviewers are evaluating problem-solving process, not
  encyclopedic knowledge of every possible technology.
- **Explicitly naming assumptions** — "I'm assuming read-heavy traffic
  here, which is why I'm prioritizing caching" turns an implicit choice
  into a stated, defensible one — see System Design Case Studies deep dive for more on this technique.
- **Whiteboard/diagram literacy** — labeling arrows with protocol
  (HTTP/gRPC/async queue) and direction, using consistent notation for
  databases vs services vs caches — small, learnable habits that
  measurably improve communication clarity, a real and coachable skill distinct from raw technical knowledge.
- **Remote interview tooling** — most system design interviews now
  happen via a shared virtual whiteboard (Excalidraw, Miro, or the
  platform's own tool) — genuine fluency with your chosen tool (not
  fumbling with drawing shapes) is worth practicing separately from the
  technical content itself, since visible friction with the TOOL distracts from the actual design signal.
- **Practicing out loud, not just in your head** — system design
  interviews are fundamentally a COMMUNICATION exercise as much as a
  technical one; silently designing a perfect architecture in your head
  and only announcing the final answer scores far worse than narrating
  your reasoning as you go, even if the final design is identical —
  interviewers are scoring your THINKING PROCESS, which is invisible unless verbalized.
