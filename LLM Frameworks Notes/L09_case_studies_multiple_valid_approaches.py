"""
WHAT: Four realistic LLM-application-framework problems, each solved
      with THREE genuinely different, individually defensible approaches
      drawn from L01-L08 -- with an explicit comparison table and
      reasoning for why each answer is valid under different
      constraints.
WHY:  "LangChain or raw API calls," "which vector DB," "how to route
      across models" are all questions L01-L08 gave you real tools for,
      not one universal answer -- this lesson is about the decision
      process under real product and cost constraints.
LEVEL: Capstone -- read after L01-L08.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L08's concepts.
"""

# ============================================================================
# CASE STUDY 1 — BUILDING A SIMPLE, SINGLE-PURPOSE SUMMARIZATION FEATURE
# ============================================================================
#
# SETUP: a product needs one specific feature -- summarize a user-
# uploaded document -- with no multi-step reasoning, no tool use, no
# memory across requests.
#
# ------------------------------------------------------------------------
# APPROACH A: Raw OpenAI/Anthropic API calls directly (L01), no
# framework
# ------------------------------------------------------------------------
#   WHY VALID: per L01, for a task this SIMPLE (one prompt in, one
#   completion out), a framework like LangChain adds real abstraction
#   overhead (chains, prompt templates, output parsers) for
#   functionality a raw API call handles in a few lines -- fewer
#   dependencies, a smaller learning curve for the team, and full,
#   direct visibility into exactly what's being sent to the model with
#   no framework layer to understand or debug through.
#   COST: if the team LATER needs to add complexity (multi-step
#   reasoning, retries with fallback models, structured output parsing
#   with validation), they'll be re-building framework-provided
#   functionality by hand at that point -- a real, if deferred, cost if
#   this feature's scope is likely to grow.
#
# ------------------------------------------------------------------------
# APPROACH B: LangChain (L02) with a simple prompt template and output
# parser, even though the current need doesn't strictly require it
# ------------------------------------------------------------------------
#   WHY VALID: per L02, establishes a consistent pattern/abstraction the
#   team can extend later without a rewrite if this feature (or the
#   product generally) grows more complex -- worthwhile if the team
#   ALREADY uses LangChain elsewhere in the product, keeping a
#   consistent architecture rather than mixing raw-API and framework-
#   based code across different features.
#   COST: per L02, for a genuinely simple, standalone need, this is real
#   unnecessary complexity/overhead RIGHT NOW -- more moving parts,
#   more framework-specific concepts a new team member needs to learn,
#   for functionality that doesn't currently need any of it, a case of
#   premature abstraction if the team ISN'T already using LangChain
#   elsewhere.
#
# ------------------------------------------------------------------------
# APPROACH C: Raw API calls now (A), but write the prompt-construction
# and API-calling logic behind a SMALL, clean internal interface/
# function boundary, making a future migration to a framework (if
# actually needed) a contained, localized change rather than a
# scattered rewrite
# ------------------------------------------------------------------------
#   WHY VALID: gets A's current simplicity while directly addressing A's
#   stated cost (future migration pain) -- a well-designed internal
#   abstraction boundary means adopting LangChain LATER, if genuinely
#   warranted by growing complexity, touches one well-defined module
#   rather than every call site across the codebase.
#   COST: requires actually designing that clean boundary well upfront
#   -- a real, if modest, design investment, and if the interface is
#   designed around assumptions that don't hold up (e.g. it assumes
#   single-prompt-in/single-completion-out, and the REAL future need
#   turns out to require a fundamentally different shape, like streaming
#   or multi-turn state), the "clean boundary" doesn't actually save the
#   migration effort it was meant to.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Current complexity | Future extensibility | Consistency with existing codebase |
#   |----------|--------------------------|-----------------------------|-------------------------------------------|
#   | A: raw API calls | Lowest | Requires rework later | Only if codebase is already raw-API-based |
#   | B: LangChain now | Higher, possibly unneeded | Best (if growth actually happens) | Only if codebase already uses LangChain |
#   | C: raw calls behind a clean boundary | Low | Good (contained migration point) | Neutral, works either way |
#   For a GENUINELY simple, standalone feature with no existing
#   framework usage in the codebase, C is the strongest balance; B is
#   right specifically when the team already has LangChain
#   infrastructure and conventions in place elsewhere.


# ============================================================================
# CASE STUDY 2 — CHOOSING A VECTOR DATABASE FOR A RAG SYSTEM
# ============================================================================
#
# SETUP: building a RAG system (L03) over a growing internal knowledge
# base (currently ~50K documents, expected to grow), needs to support
# metadata filtering (e.g. "only search documents from department X").
#
# ------------------------------------------------------------------------
# APPROACH A: A managed, purpose-built vector database (e.g. Pinecone)
# ------------------------------------------------------------------------
#   WHY VALID: per L03, purpose-built vector databases are optimized
#   specifically for approximate nearest-neighbor search at scale, with
#   metadata filtering as a first-class, well-supported feature --
#   minimal operational burden (fully managed) and generally the best
#   out-of-the-box performance for pure vector-search workloads.
#   COST: real, ongoing service cost that scales with data volume/query
#   rate, and introduces a data store OUTSIDE whatever the team's
#   existing database infrastructure is -- a new system to operate
#   (even if managed) and a new vendor relationship/dependency.
#
# ------------------------------------------------------------------------
# APPROACH B: pgvector (a PostgreSQL extension) if the team already
# operates PostgreSQL for other application data (L03)
# ------------------------------------------------------------------------
#   WHY VALID: per L03, keeps vector search WITHIN existing relational
#   infrastructure -- metadata filtering is just ordinary SQL WHERE
#   clauses (leveraging Postgres's mature query planner and indexing,
#   SQL Notes), and the team avoids introducing an entirely new data
#   store/vendor for a feature that can be served by infrastructure they
#   already operate and understand well.
#   COST: per L03, pgvector's approximate-nearest-neighbor performance
#   at LARGE scale generally doesn't match purpose-built vector
#   databases' specialized indexing -- for 50K documents this is likely
#   a non-issue, but "expected to grow" (as stated) means this
#   performance gap could become real at some future scale the team
#   should proactively watch for, not just assume away.
#
# ------------------------------------------------------------------------
# APPROACH C: A self-hosted, open-source vector database (e.g. Qdrant,
# Chroma) rather than either a managed service or a relational extension
# ------------------------------------------------------------------------
#   WHY VALID: per L03, gets much of purpose-built vector search
#   performance (A's strength) while avoiding A's ongoing managed-
#   service cost and vendor dependency, appropriate for a team with the
#   operational capacity to self-host and comfortable NOT paying for a
#   fully-managed service.
#   COST: per L03, self-hosting means the TEAM now owns operational
#   responsibility for this new system (scaling, backups, upgrades,
#   monitoring) that a managed service (A) would have absorbed -- real,
#   ongoing operational burden that must be weighed against A's service
#   cost, not free just because it avoids a subscription fee.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Performance at large scale | Operational burden | Infrastructure consistency |
#   |----------|---------------------------------|--------------------------|-----------------------------------|
#   | A: managed vector DB | Best | Lowest | New, separate system |
#   | B: pgvector | Good at current scale, uncertain later | Lowest (reuses existing Postgres) | Best (if already on Postgres) |
#   | C: self-hosted open-source vector DB | Good | Highest (self-managed) | New, separate system |
#   For a team already running PostgreSQL and at THIS case study's
#   current scale (50K documents), B is the pragmatic starting point --
#   migrate to A or C specifically once growth is measured to actually
#   strain pgvector's performance, rather than preemptively adopting a
#   separate vector database before that need is confirmed.


# ============================================================================
# CASE STUDY 3 — DESIGNING AN AGENT'S TOOL-USE PERMISSIONS
# ============================================================================
#
# SETUP: an LLM agent (L04) needs to help users manage their cloud
# infrastructure via natural language -- including genuinely destructive
# actions (deleting resources), and the team needs to decide how much
# autonomy to grant.
#
# ------------------------------------------------------------------------
# APPROACH A: Grant the agent full tool access, including destructive
# actions, with no human confirmation step
# ------------------------------------------------------------------------
#   WHY VALID: the smoothest, fastest user experience -- a user can ask
#   "delete the unused staging environment" and have it happen
#   immediately, no interruption, genuinely valuable for trusted,
#   experienced users doing routine, low-risk cleanup tasks.
#   COST: per L04's security discussion, this directly exposes the FULL
#   consequence of any LLM error (a misunderstood request, a prompt-
#   injection-influenced action if any tool output includes untrusted
#   content, LLM Core Theory Notes L07) -- a single bad tool call can
#   cause real, irreversible infrastructure damage with zero human
#   checkpoint to catch it before it happens.
#
# ------------------------------------------------------------------------
# APPROACH B: Require explicit human confirmation before ANY destructive
# action executes (L04)
# ------------------------------------------------------------------------
#   WHY VALID: per L04, this is the standard, conservative safety
#   pattern -- a human reviews and approves the SPECIFIC action before
#   it executes, directly closing A's "no checkpoint" risk while still
#   letting the agent do the useful work of FORMULATING the right action
#   from natural language.
#   COST: per L04, adds real friction to every destructive action, even
#   ones a trusted, experienced user would have approved without a
#   second thought -- for a power user doing MANY routine cleanup
#   actions, requiring confirmation on every single one is a genuine,
#   repeated productivity cost.
#
# ------------------------------------------------------------------------
# APPROACH C: Tiered permissions -- non-destructive/reversible actions
# (listing resources, starting a stopped instance) execute autonomously;
# destructive/irreversible actions (deletion, terminating production
# resources) require confirmation; ADDITIONALLY, enforce hard permission
# SCOPING at the infrastructure/IAM level (Cloud Platforms Notes L06) so
# the agent's credentials themselves cannot touch production resources
# regardless of what any prompt or tool call claims
# ------------------------------------------------------------------------
#   WHY VALID: per L04 combined with LLM Core Theory Notes L07's
#   defense-in-depth point (no learned behavior alone is a structural
#   guarantee), this layers THREE distinct protections -- risk-
#   appropriate friction (only destructive actions need confirmation,
#   preserving B's safety without A's blanket inconvenience), PLUS a
#   hard, non-bypassable credential-scoping boundary that holds even if
#   the confirmation step is somehow subverted (a prompt injection
#   tricking a user into approving something they didn't understand,
#   for instance).
#   COST: the most implementation effort of the three -- requires
#   correctly classifying every tool/action by risk tier (an ongoing
#   maintenance task as new tools are added) AND setting up genuinely
#   scoped IAM credentials for the agent (real infrastructure work,
#   Cloud Platforms Notes L06), not just an application-layer permission
#   check that could itself have a bug.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | User friction | Protection if the LLM/confirmation step fails | Setup effort |
#   |----------|-------------------|------------------------------------------------------|-------------------|
#   | A: full autonomy | None | None | Lowest |
#   | B: confirm all destructive actions | Real, uniform | Depends entirely on the confirmation step holding | Low |
#   | C: tiered + hard IAM scoping | Proportional to actual risk | Real (structural backstop) | Highest |
#   For ANY agent with genuinely destructive capability over real
#   infrastructure, C is the responsible answer -- A is rarely
#   justifiable once real, irreversible actions are in scope, and B
#   alone, without C's structural IAM backstop, still depends entirely
#   on the confirmation UI/logic never being fooled or buggy, a single
#   point of failure C doesn't share.


# ============================================================================
# CASE STUDY 4 — MANAGING COST FOR A HIGH-VOLUME LLM-POWERED FEATURE
# ============================================================================
#
# SETUP: a customer-support chat feature's LLM API costs have grown
# substantially as usage scaled; the team needs to reduce cost without
# meaningfully degrading answer quality.
#
# ------------------------------------------------------------------------
# APPROACH A: Switch to a smaller, cheaper model across the board (L07,
# L08)
# ------------------------------------------------------------------------
#   WHY VALID: the single fastest, simplest cost lever -- per-token cost
#   drops immediately and uniformly, and for a genuinely large fraction
#   of support queries (simple, common questions), a smaller model may
#   perform just as well as a larger, more expensive one.
#   COST: per L07-L08, a uniform downgrade risks degrading quality on
#   the SUBSET of genuinely complex queries that actually benefited from
#   the larger model's capability -- a blunt, undifferentiated cut that
#   doesn't distinguish "this query didn't need the expensive model
#   anyway" from "this query genuinely needed it and now gets a worse
#   answer."
#
# ------------------------------------------------------------------------
# APPROACH B: Semantic caching (L08) -- cache responses for semantically
# similar (not just exact-duplicate) queries, serving cached responses
# for repeat/near-repeat questions instead of a fresh API call
# ------------------------------------------------------------------------
#   WHY VALID: per L08, customer support queries have real, high
#   redundancy (many users ask essentially the same common questions) --
#   semantic caching can eliminate a substantial fraction of API calls
#   entirely for genuinely repeated question patterns, without touching
#   model QUALITY at all for the queries that do still need a fresh call.
#   COST: per L08, semantic similarity matching isn't perfect -- a
#   cached response served for a query that's SIMILAR but not
#   IDENTICAL in a meaningful way can produce a subtly wrong or
#   irrelevant answer, and correctly tuning the similarity threshold
#   (too loose: wrong answers served; too strict: cache rarely hits,
#   little cost benefit) requires real, ongoing tuning and monitoring.
#
# ------------------------------------------------------------------------
# APPROACH C: Multi-model routing (L07) -- classify each incoming query
# by complexity, route simple/common queries to a cheap model, complex/
# novel queries to the expensive model, combined with B's semantic
# caching layered on top
# ------------------------------------------------------------------------
#   WHY VALID: per L07-L08, this directly addresses A's "uniform
#   downgrade hurts complex queries" problem by routing based on ACTUAL
#   query complexity rather than applying one blanket model choice, while
#   ALSO capturing B's cache-hit savings for genuinely repeated
#   questions -- combines both cost-reduction mechanisms rather than
#   choosing only one.
#   COST: per L07, the routing classifier itself is new infrastructure
#   requiring monitoring/evaluation (LLM Core Theory Notes L07's
#   evaluation-validity concerns apply directly to the router, not just
#   the downstream models) -- the most complex of the three options to
#   build and maintain correctly, combining B's tuning burden with an
#   additional routing-accuracy concern on top.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Cost reduction | Quality-preservation for complex queries | Implementation complexity |
#   |----------|--------------------|------------------------------------------------|----------------------------------|
#   | A: uniform model downgrade | High, immediate | Poor (blunt cut) | Lowest |
#   | B: semantic caching | Medium-high, for repeated queries | Good (doesn't touch model choice) | Medium |
#   | C: routing + caching combined | Highest | Best (complexity-aware) | Highest |
#   C is the strongest answer for a team with the engineering capacity
#   to build and maintain it; B alone is a strong, lower-effort first
#   step that captures real savings with minimal quality risk; A alone
#   is the fastest fix but carries the most real risk to answer quality
#   for exactly the queries where quality matters most.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
