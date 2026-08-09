"""
WHAT: Four realistic event-driven/real-time AI system problems, each
      solved with THREE genuinely different, individually defensible
      approaches drawn from L01-L12 -- with an explicit comparison table
      and reasoning for why each answer is valid under different
      constraints.
WHY:  "NATS or Kafka," "durable workflow or hand-rolled retries," and
      "which LLM to route to" are all questions L01-L12 gave you real
      tools for, but not a single universal answer to -- this lesson is
      about the decision process under real constraints.
LEVEL: Capstone -- read after L01-L12.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L12's concepts.
"""

# ============================================================================
# CASE STUDY 1 — CHOOSING A MESSAGE BACKBONE FOR A REAL-TIME FRAUD-ALERT
# PIPELINE
# ============================================================================
#
# SETUP: transaction events need to reach a scoring service and, for
# high-risk transactions, trigger an immediate downstream alert -- p99
# latency from event to alert matters (target: under 50ms), and volume
# is moderate (a few thousand events/second), not Kafka-scale.
#
# ------------------------------------------------------------------------
# APPROACH A: Kafka (Apache Kafka Notes) as the backbone
# ------------------------------------------------------------------------
#   WHY VALID: if the organization already runs fraud/transaction data
#   through Kafka elsewhere (e.g. for downstream analytics or audit
#   logging), reusing that existing pipeline avoids introducing a SECOND
#   messaging system purely for this one alerting path, and Kafka's
#   durability guarantees give a strong audit trail for a domain
#   (fraud) where "can we prove exactly what happened and when" matters.
#   COST: per L03's NATS-vs-Kafka decision framework, Kafka's typical
#   latency profile is generally higher than NATS's for this class of
#   workload, and Kafka's operational overhead is real overhead to carry
#   for a moderate-throughput path if it's ONLY being added for this
#   specific alerting need, not reused from an existing deployment.
#
# ------------------------------------------------------------------------
# APPROACH B: NATS core pub/sub (not JetStream) for the alert path
# specifically (L02, L03)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, core NATS (non-persistent, fire-and-forget
#   pub/sub) is about as low-latency as this category of tooling gets --
#   for the SPECIFIC "get a high-risk transaction to an alerting
#   consumer fast" requirement, this directly targets the stated <50ms
#   goal with minimal overhead.
#   COST: core NATS provides NO persistence/durability by design (L02)
#   -- if the alerting consumer is briefly down, in-flight alert events
#   during that window are simply LOST, not replayed on reconnect -- a
#   real risk specifically for a fraud-alerting use case, where a missed
#   alert has real financial/compliance consequences, not just a
#   degraded user experience.
#
# ------------------------------------------------------------------------
# APPROACH C: NATS JetStream (L02) for the alert path, providing
# persistence/replay while retaining much of core NATS's latency
# advantage over Kafka
# ------------------------------------------------------------------------
#   WHY VALID: directly addresses B's durability gap -- JetStream adds
#   persistence and at-least-once delivery guarantees on top of NATS's
#   pub/sub model, so a consumer outage no longer means silently lost
#   alerts, while still generally beating Kafka's typical latency
#   profile for this class of throughput (per L03's comparison
#   framework) and avoiding Kafka's heavier operational footprint.
#   COST: JetStream's persistence adds SOME latency overhead relative to
#   core NATS's fire-and-forget path (writing to disk before
#   acknowledging costs real time) -- not free, though per L03 typically
#   still favorable relative to Kafka for this throughput range; also
#   still a genuinely different (and for many orgs, less battle-tested
#   at very large scale) operational surface than Kafka if the
#   organization has deep existing Kafka expertise it would otherwise
#   leverage.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Latency fit (<50ms target) | Durability | Operational fit if no existing Kafka |
#   |----------|----------------------------------|----------------|--------------------------------------------|
#   | A: Kafka | Weaker fit | Strong | Poor (new heavy system for a moderate need) |
#   | B: core NATS pub/sub | Best fit | None (real risk here) | Good |
#   | C: NATS JetStream | Good fit | Strong | Good |
#   Given fraud alerting's real cost of a silently dropped event, C is
#   the strongest default; B is only appropriate if the alert path is
#   genuinely best-effort (a secondary/supplementary channel, not the
#   primary compliance-relevant one) and A wins specifically when
#   reusing existing Kafka infrastructure outweighs the latency gap.


# ============================================================================
# CASE STUDY 2 — ORCHESTRATING A MULTI-STEP AI AGENT WORKFLOW THAT CALLS
# THREE EXTERNAL APIS AND MUST SURVIVE A SERVICE RESTART MID-WORKFLOW
# ============================================================================
#
# SETUP: an agent workflow (e.g. "research a topic, draft a report, send
# for review") takes minutes to complete, calls flaky third-party APIs,
# and the current implementation loses all progress if the hosting
# service restarts mid-run (a real, observed problem).
#
# ------------------------------------------------------------------------
# APPROACH A: Hand-rolled retry logic with exponential backoff around
# each API call, workflow state kept in the service's in-memory process
# ------------------------------------------------------------------------
#   WHY VALID: the lowest-friction fix for the FLAKY-API part of the
#   problem specifically -- straightforward to implement, no new
#   infrastructure dependency, and genuinely solves transient API
#   failures that resolve on retry.
#   COST: does NOTHING for the stated "survives a service restart"
#   requirement -- in-memory workflow state is, by definition, lost the
#   moment the process restarts, regardless of how good the retry logic
#   around individual API calls is; this approach solves a real but
#   DIFFERENT problem than the one this case study centers on.
#
# ------------------------------------------------------------------------
# APPROACH B: Persist workflow state to a database after each step,
# with a recovery routine that resumes from the last completed step on
# service startup
# ------------------------------------------------------------------------
#   WHY VALID: directly solves the restart-survival requirement -- an
#   explicit, DIY checkpoint-and-resume mechanism, requiring no new
#   framework/service dependency beyond a database the team likely
#   already operates.
#   COST: this is genuinely hard to get fully correct by hand -- exactly
#   replicating durable-execution semantics (idempotent step re-entry,
#   correctly handling a crash that occurs mid-step rather than cleanly
#   between steps, L04) from scratch is a well-known source of subtle
#   bugs; L04's entire premise is that this specific problem has already
#   been solved well by purpose-built tools, and re-deriving it in-house
#   risks reproducing bugs those tools have already fixed.
#
# ------------------------------------------------------------------------
# APPROACH C: A durable-execution framework (Hatchet, or a Temporal-
# style equivalent, L04) wrapping the entire multi-step workflow
# ------------------------------------------------------------------------
#   WHY VALID: per L04, this is EXACTLY the problem durable execution
#   frameworks are purpose-built to solve -- automatic checkpointing,
#   crash-safe resume, and built-in retry/timeout/fan-out semantics for
#   each step, all handled by a framework specifically designed and
#   tested for this failure mode, rather than reproducing it by hand
#   (approach B's risk).
#   COST: introduces a new infrastructure dependency and a genuine
#   learning curve for the team (L04's own framework-adoption discussion)
#   -- and expressing the workflow in the framework's specific
#   programming model (often requiring workflow code to be written in a
#   particular deterministic style) is real, upfront engineering effort
#   to migrate existing ad hoc workflow code into.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Solves flaky-API retries | Solves restart-survival | Correctness risk | New infra dependency |
#   |----------|-------------------------------|-------------------------------|----------------------|-----------------------------|
#   | A: hand-rolled retries only | Yes | No | Low | None |
#   | B: DIY DB checkpointing | Partially (needs its own retry logic too) | Yes | High (subtle bugs likely) | None (reuses existing DB) |
#   | C: durable-execution framework | Yes (built-in) | Yes (built-in) | Low (battle-tested) | Yes |
#   Given the case study's EXPLICIT restart-survival requirement, A alone
#   is insufficient; C is the recommended answer per L04's own framing
#   specifically because B's "solve it yourself" path is a well-known
#   trap that looks simpler upfront than it proves to be in practice.


# ============================================================================
# CASE STUDY 3 — ROUTING LLM REQUESTS ACROSS MULTIPLE MODEL PROVIDERS FOR
# A CUSTOMER-FACING CHAT PRODUCT
# ============================================================================
#
# SETUP: a chat product wants to balance cost (cheaper models for simple
# queries), quality (stronger models for complex ones), and resilience
# (a provider outage shouldn't take down the whole product).
#
# ------------------------------------------------------------------------
# APPROACH A: Static routing rules -- classify query complexity via
# simple heuristics (query length, keyword matching) and route to a
# fixed cheap-vs-expensive model accordingly (L07)
# ------------------------------------------------------------------------
#   WHY VALID: cheap to build and fully deterministic/debuggable -- a
#   support engineer can look at any routing decision and immediately
#   see exactly WHY it was made, with no model-based classification
#   step that could itself be wrong or need its own monitoring.
#   COST: heuristic complexity classification is genuinely crude --
#   query LENGTH or keyword presence correlates only loosely with actual
#   task difficulty, meaning this approach will systematically
#   misroute some genuinely complex-but-short queries to a cheaper model
#   (quality risk) and some simple-but-verbose queries to an expensive
#   model (unnecessary cost) -- a real, hard-to-eliminate accuracy
#   ceiling on the routing decision itself.
#
# ------------------------------------------------------------------------
# APPROACH B: A learned/LLM-based router -- use a small, fast
# classifier model to predict query complexity/intent, then route based
# on that prediction (L07)
# ------------------------------------------------------------------------
#   WHY VALID: per L07, a purpose-trained (or even a well-prompted small
#   LLM) classifier can capture genuinely more nuanced signals of query
#   complexity than simple heuristics -- generally a real accuracy
#   improvement over A's crude rules, better balancing the cost/quality
#   tradeoff the case study actually cares about.
#   COST: the router itself is now a MODEL that needs monitoring,
#   evaluation, and occasional retraining/re-prompting as query patterns
#   drift over time (LLM Core Theory Notes L07's evaluation-validity
#   concerns apply directly to the router itself, not just the
#   downstream models) -- a new, ongoing maintenance surface A's static
#   rules don't have.
#
# ------------------------------------------------------------------------
# APPROACH C: A cascading/fallback chain (L07, L08) -- always try the
# cheap model first, automatically escalate to a stronger model if the
# cheap model's response fails a confidence/quality check, with
# automatic provider-level failover built into the SAME chain for
# resilience
# ------------------------------------------------------------------------
#   WHY VALID: directly addresses the case study's THIRD stated goal
#   (resilience to provider outages) in the SAME mechanism as the cost/
#   quality tradeoff -- per L07-L08, a well-designed fallback chain
#   handles "model returned a low-confidence/malformed response" and
#   "provider is down" as instances of the SAME underlying escalation
#   logic, rather than needing separate routing (A or B) and separate
#   resilience mechanisms bolted on independently.
#   COST: cheap-first cascading means genuinely complex queries pay the
#   LATENCY cost of the cheap model failing FIRST before escalating --
#   a real, structural latency tax on exactly the complex queries that
#   most need the strong model's response fastest, a tradeoff A/B (which
#   route directly to the right model upfront, when their classification
#   is correct) don't have.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Routing accuracy | Handles provider outages? | Latency for complex queries | Maintenance overhead |
#   |----------|-----------------------|--------------------------------|------------------------------------|----------------------------|
#   | A: static heuristic rules | Lowest | Not natively (separate mechanism needed) | Good (direct routing) | Lowest |
#   | B: learned classifier router | Better | Not natively (separate mechanism needed) | Good (direct routing) | Medium (router upkeep) |
#   | C: cascading fallback chain | Good (self-correcting) | Yes (built-in) | Worse (pays cheap-model-fail cost first) | Medium |
#   Production systems often combine B and C: a learned router for the
#   INITIAL cost/quality routing decision, wrapped in C's cascading
#   fallback structure specifically for resilience -- using each
#   approach for the part of the problem it's genuinely best suited to.


# ============================================================================
# CASE STUDY 4 — HANDLING BACKPRESSURE ON A WEBSOCKET STREAM SERVING
# LIVE MODEL-INFERENCE RESULTS TO THOUSANDS OF CONCURRENT CLIENTS
# ============================================================================
#
# SETUP: a WebSocket service (L06) streams live inference results (e.g.
# live sentiment scores on a social feed) to thousands of connected
# clients; some clients have slow/unstable connections and can't consume
# messages as fast as the server produces them.
#
# ------------------------------------------------------------------------
# APPROACH A: Unbounded per-client send buffers -- queue every message
# for every client regardless of how far behind they are (L06)
# ------------------------------------------------------------------------
#   WHY VALID: guarantees no client ever misses a single message -- for
#   a use case where EVERY update genuinely matters and must eventually
#   be delivered (not just "the latest state"), this is the only one of
#   the three options that satisfies that guarantee at all.
#   COST: per L06's backpressure discussion, an unbounded buffer for a
#   permanently-slow client grows WITHOUT LIMIT -- a genuine, serious
#   memory-exhaustion risk on the server if even a small fraction of
#   thousands of clients are consistently slower than the production
#   rate, a real production-outage vector, not a theoretical concern.
#
# ------------------------------------------------------------------------
# APPROACH B: Bounded per-client buffers with drop-oldest (or drop-
# newest) policy once full (L06)
# ------------------------------------------------------------------------
#   WHY VALID: directly bounds the memory-exhaustion risk from A -- each
#   client's buffer has a hard cap, and once full, the server makes an
#   explicit, deliberate choice about what to drop rather than growing
#   unboundedly; appropriate specifically when clients care about
#   RECENCY (the latest sentiment score) more than completeness (every
#   single historical score).
#   COST: slow clients DO miss messages -- an explicit, accepted
#   tradeoff, but one that must be genuinely appropriate for the use
#   case; for a use case where missing even one update is unacceptable
#   (this case study doesn't specify that it is, but a different one
#   might), this approach is simply the wrong tool regardless of how
#   well-implemented the bounding/dropping logic is.
#
# ------------------------------------------------------------------------
# APPROACH C: Server-side sampling/coalescing -- rather than sending
# every individual update, periodically send only the LATEST state per
# client (e.g. at most once every 200ms), collapsing intermediate
# updates
# ------------------------------------------------------------------------
#   WHY VALID: reduces the ACTUAL message volume the backpressure
#   problem has to handle in the first place, rather than just managing
#   an unavoidably-large volume better (B) or accepting unbounded risk
#   (A) -- if clients genuinely only need the current/latest sentiment
#   score, not a full history of every intermediate value, this
#   sidesteps the problem at its root rather than mitigating symptoms.
#   COST: only valid when clients GENUINELY don't need every
#   intermediate update -- for any use case requiring a complete,
#   ordered history of every change (e.g. an audit log, or a use case
#   where intermediate values themselves carry meaning, not just the
#   final state), coalescing silently discards information the client
#   actually needed, a correctness bug disguised as a performance
#   optimization if applied to the wrong use case.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Memory-exhaustion risk | Message completeness | Fits "latest state only" clients | Fits "every update matters" clients |
#   |----------|------------------------------|----------------------------|------------------------------------------|-------------------------------------------|
#   | A: unbounded buffers | Severe | Complete | Wasteful (unneeded completeness) | Yes, but with real outage risk |
#   | B: bounded + drop policy | None | Incomplete for slow clients | Good | No (drops matter here) |
#   | C: server-side coalescing | None | Reduced by design | Best | No (loses intermediate values) |
#   For THIS case study's stated use case (live sentiment scores, where
#   clients almost certainly care about current state, not a complete
#   audit trail), C is the strongest fit; B is the right fallback when
#   coalescing isn't semantically appropriate but bounded memory still
#   is; A is essentially never the right production answer at this
#   client scale.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
