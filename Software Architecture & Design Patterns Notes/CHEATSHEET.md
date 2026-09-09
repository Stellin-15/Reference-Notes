# Software Architecture & Design Patterns — In-Depth Reference

The single biggest gap in most engineering education: DDD, CQRS, event
sourcing, microservices-vs-monolith tradeoffs, and the classic GoF
patterns — the vocabulary and mental models principal engineers use to
discuss system structure.


## 1. DOMAIN-DRIVEN DESIGN (DDD)

DDD's core insight: software structure should mirror the BUSINESS DOMAIN,
using the domain experts' own vocabulary (the "ubiquitous language"), not
a generic CRUD-and-tables model imposed from outside.

- **Bounded Context** — a boundary within which a specific domain model
  and vocabulary apply consistently — the word "Customer" might mean
  something different in the Billing context (has a payment method, a
  balance) than in the Support context (has a ticket history, a
  satisfaction score) — DDD says this is FINE and expected, not a
  modeling inconsistency to eliminate; each bounded context gets its own model.
- **Aggregate** — a cluster of objects treated as one consistency unit,
  with a single Aggregate Root controlling access — an Order aggregate
  might contain OrderLineItems, but external code should never modify a
  line item directly, only through the Order root, which enforces
  invariants (e.g. "total must equal sum of line items") on every change.
- **Entities vs Value Objects** — an Entity has a persistent IDENTITY
  (two Customers with the same name are still different customers,
  tracked by ID); a Value Object is defined entirely by its ATTRIBUTES
  (two `Money(10, "USD")` objects are interchangeable, no identity to track).

```
Bounded contexts map directly onto microservice boundaries in most
mature microservices architectures — the classic mistake is drawing
service boundaries around DATABASE TABLES instead of bounded contexts,
producing services that are technically separate but still tightly
coupled because they don't respect a real domain boundary.
```


## 2. CQRS (Command Query Responsibility Segregation)

Separates the WRITE model (commands — mutate state, enforce business
rules/invariants) from the READ model (queries — optimized purely for
fast retrieval, often denormalized). The key insight: a write model
optimized for correctness/invariant enforcement and a read model
optimized for query performance often want GENUINELY different shapes —
CQRS lets each be optimized independently instead of compromising both
to fit one shared model.

```
Write side: Order aggregate enforces "can't ship before payment confirmed"
Read side: OrderSummaryView — a denormalized, pre-joined table optimized
           purely for the "show my order history" screen's exact query shape

The two are kept in sync via events (see Event Sourcing below) or a
simple projection/materialized-view update on every write.
```

**When NOT to use CQRS**: for a simple CRUD application with no genuine
read/write model divergence, CQRS adds real complexity (two models to
maintain, eventual-consistency lag between them) for no corresponding
benefit — a real, common architecture-astronaut mistake is reaching for
CQRS by default rather than when the read/write shapes genuinely diverge.


## 3. EVENT SOURCING

Instead of storing current STATE (a row that gets overwritten on update),
store every STATE-CHANGING EVENT that ever happened, and derive current
state by replaying events. The account balance isn't a column — it's
computed by replaying every Deposited/Withdrawn event for that account.

**Why this is genuinely powerful**: full audit trail for free (every
change is preserved, not just the final state), the ability to
reconstruct state AS OF any point in time, and natural pairing with CQRS
(events ARE the write model; read-model projections are built by
consuming those same events). **Why it's genuinely hard**: event schema
evolution over time (an old event format must remain replayable forever,
or you need explicit upcasting logic), and replaying a very long event
history to reconstruct current state requires SNAPSHOTTING optimization
for practical performance at scale.


## 4. MICROSERVICES VS MONOLITH — THE REAL DECISION FRAMEWORK

The honest, most common principal-engineer answer: **start with a
well-structured monolith**, and split into microservices when a SPECIFIC,
observed pain point demands it (independent team scaling, genuinely
different deployment cadences per component, or a component with
fundamentally different resource/scaling profiles) — not by default,
and not because microservices are trendy. Martin Fowler's "MonolithFirst"
essay captures this precisely: premature microservices decomposition
before understanding your actual domain boundaries (see DDD's bounded
contexts above) tends to produce a "distributed monolith" — all of
microservices' operational complexity (network calls, eventual
consistency, deployment coordination) with none of its supposed benefits, because the service boundaries don't align with real domain boundaries.

**The Strangler Fig pattern** (see Cloud Platforms deep dive's migration
section) is the standard, low-risk path from monolith to microservices —
incrementally routing individual capabilities to new services behind a
facade, rather than a risky big-bang rewrite.


## 5. CLASSIC PATTERNS (GoF) STILL GENUINELY USED

- **Repository pattern** — abstracts data access behind an interface,
  letting business logic remain ignorant of whether data comes from
  Postgres, an API, or a cache — the standard pattern underneath most ORMs' higher-level abstractions.
- **Factory pattern** — encapsulates object creation logic, especially
  useful when creation involves genuine complexity/conditionals (which
  concrete class to instantiate based on config/input).
- **Observer pattern** — the conceptual ancestor of pub/sub and reactive
  programming (see Event-Driven & Real-Time AI Systems deep dive) — a
  subject notifies registered observers of state changes.
- **Strategy pattern** — encapsulates interchangeable ALGORITHMS behind a
  common interface (different pricing strategies, different sorting
  algorithms) selected at runtime — genuinely useful whenever "which
  specific implementation to use" is itself a business/configuration decision.
- **Dependency Injection** — not strictly a GoF pattern but the most
  pervasive modern pattern for achieving testable, loosely-coupled code
  (see FastAPI, Java/Spring, and C#/.NET deep dives for framework-native
  implementations of this same underlying idea).


## 6. NICHE BUT REAL

- **Hexagonal / Clean Architecture ("Ports and Adapters")** — structures
  an application with business logic at the CENTER, completely ignorant
  of infrastructure details (database, web framework, external APIs),
  which are plugged in via "adapters" implementing "ports" (interfaces)
  the core defines — makes business logic testable without any real
  infrastructure and swappable (change databases without touching business logic) — a real, disciplined structuring approach beyond ad-hoc layering.
- **Anti-corruption layer** — a translation layer specifically protecting
  your domain model from being polluted/distorted by an external
  system's (or legacy system's) different, incompatible model — lets you
  integrate with a messy external API without letting its modeling
  decisions leak into your own clean domain model.
- **Saga pattern** (see Event-Driven & Real-Time AI Systems deep dive) —
  the distributed-transaction-alternative pattern for coordinating
  multi-service business transactions with compensating actions.
- **The "big ball of mud" anti-pattern** — a genuinely named, common
  failure mode: a system with no discernible architecture at all,
  accreted through years of expedient changes with no enforced
  boundaries — worth knowing by name as the failure state good architecture actively guards against.
