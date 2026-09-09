# Event-Driven & Real-Time AI Systems — Principal Engineer Deep Dive

Companion to L01-L12. Narrative depth, then a comprehensive common-to-
uncommon reference.


## Durable Execution — The Concept Underneath Hatchet/Temporal

**Beyond the lesson**: Durable execution solves a problem that looks
simple but is genuinely hard to hand-roll correctly: a multi-step workflow
(charge a card, reserve inventory, send a confirmation email) needs to
SURVIVE a process crash midway through, resuming exactly where it left off
— not from the start (which might double-charge the card) and not
silently losing the remaining steps. Temporal/Hatchet achieve this by
persisting EVERY step's result to durable storage as the workflow
executes; on a crash/restart, the workflow function is literally re-run
from the top, but each previously-completed step's `activity()` call
returns its ALREADY-RECORDED result instantly instead of re-executing —
the workflow code just "sees" a completed step as if it always was, without you writing that resumption logic by hand.

**Worked example**: This exact mechanism is why durable execution is the
right foundation for long-running AGENT tasks (see AI Agent & Automation
Tooling Notes section 9) — an autonomous agent that might run for hours
across many tool calls needs to survive a deploy/crash/restart mid-task
without losing progress or, worse, re-executing an already-completed
irreversible action (like a payment) — wrapping the agent loop in a
durable workflow gives crash-safety "for free" that a plain retry loop cannot.

**Interview Q&A**:
- *Q: Why not just use a database transaction to make a multi-step process atomic instead of durable execution?* A: A database transaction only spans operations WITHIN that database — the moment a step involves an external side effect (charging a payment gateway, calling a third-party API), it can't be rolled back by a DB transaction; durable execution's "record each step, replay on failure" model handles exactly this cross-system, non-transactional multi-step coordination that database ACID guarantees fundamentally can't reach.


## Event Granularity & Schema Design

**Beyond the lesson**: The "how big should one event be" question has a
real, recurring wrong answer: events that are too COARSE-GRAINED
("OrderUpdated" with the entire order object, ambiguous about WHAT
changed) force every consumer to diff the whole object to figure out what
actually happened; events that are too FINE-GRAINED (a separate event per
field change) create an explosion of event types and ordering-dependency
complexity between them. The practical middle ground: model events around
actual BUSINESS FACTS that happened ("OrderShipped," "PaymentFailed"), not
generic CRUD notifications ("OrderUpdated") — a discipline borrowed
directly from event sourcing/DDD (see Software Architecture & Design Patterns domain).

**Interview Q&A**:
- *Q: A downstream consumer needs a field your event doesn't currently include. Do you add it to the existing event, or create a new event type?* A: Depends on whether it represents information ABOUT THE SAME business fact (add it, backward-compatibly, as an optional field) or a genuinely DIFFERENT thing happening (a new event type) — conflating the two leads to events that try to be everything to everyone and become unmaintainable.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Real-time trigger/rules engines
- **Complex Event Processing (CEP)** — systems (Flink CEP, Esper)
  detecting PATTERNS across a stream of events in real time ("alert if 3
  failed logins happen within 60 seconds from the same IP") rather than
  reacting to single events independently — the mechanism underneath most
  real-time fraud/anomaly detection systems.
- **Rules engines** (Drools, or a simpler custom DSL) — externalizing
  business logic as declarative, non-engineer-editable rules rather than
  hardcoded conditionals — common in real-time decisioning systems
  (pricing, eligibility) where business rules change more often than engineering deploy cycles allow for comfortably.

### WebSocket & real-time delivery infrastructure
- **Socket.io / Pusher / Ably** — managed or self-hosted real-time
  message delivery to browsers/mobile clients, handling the reconnection/
  fallback/scaling complexity of raw WebSockets so application teams don't
  reinvent it per project.
- **Server-Sent Events (SSE)** as the simpler alternative — see FastAPI
  deep dive; the right choice specifically for one-way server-to-client
  streaming (LLM token streaming, live status updates) without needing full duplex WebSocket complexity.

### Multi-model LLM routing in production
- **Fallback chains** — if the primary model provider is down/rate-
  limited, automatically retry against a secondary provider — see the AI
  Agent & Automation Tooling deep dive's LiteLLM/Portkey coverage for the concrete gateway tooling.
- **Cost-based routing** — routing a request to a cheaper/faster model for
  simple queries and a more capable (expensive) model only when the
  query's complexity genuinely warrants it — a real production cost-optimization pattern for LLM-heavy products at scale.

### Real-time serving architecture patterns
- **Hybrid fast/slow model serving** — serving a cheap, fast model
  synchronously for the immediate response, while a slower, more thorough
  model processes the same request asynchronously and updates the result
  later if warranted (common in search ranking and fraud
  detection: return SOMETHING instantly, refine it moments later).
- **Latency budgets** — explicitly allocating a fixed millisecond budget
  across each stage of a request's path (10ms feature lookup + 20ms model
  inference + 5ms post-processing = 35ms total) so a latency regression in
  any single stage is immediately attributable, rather than only noticing
  "the whole thing got slower" without knowing where.


## NICHE BUT REAL

- **Saga pattern** — coordinating a multi-step, multi-service business
  transaction (book a flight + hotel + car, where any step failing needs
  to UNDO the previous successful steps via COMPENSATING actions) without
  a distributed transaction — the classic event-driven-architecture answer
  to "ACID transactions don't span microservices."
- **Event replay for debugging/recovery** — because events are persisted
  (in Kafka, or an event store), a bug in a CONSUMER can be fixed and the
  consumer can simply RE-READ historical events from the beginning to
  correct its derived state — a capability that's genuinely impossible in
  a synchronous request/response architecture where the "event" (the
  request) is gone the moment it's handled.
- **Outbox pattern** — see Apache Kafka deep dive's "NICHE BUT REAL"
  section — the concrete mechanism preventing dual-write inconsistency
  between a service's own database and the events it publishes.
- **Backpressure-aware event consumers** — a consumer that's falling
  behind a fast producer needs an explicit strategy (buffer with bounds,
  drop low-priority events, or scale out more consumers) rather than
  silently accumulating unbounded memory/queue depth until it crashes —
  a real, common production incident class in event-driven systems under
  unexpected load spikes.
