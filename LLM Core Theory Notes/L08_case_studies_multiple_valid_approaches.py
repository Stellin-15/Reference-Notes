"""
WHAT: Four realistic LLM-system problems, each solved with THREE
      genuinely different, individually defensible approaches drawn from
      L01-L07 -- with an explicit comparison table and reasoning for why
      each answer is valid under different constraints, in the same
      spirit as Classical ML Theory Notes L09 and Deep Learning Theory
      Notes L08.
WHY:  Choosing between fine-tuning, RAG, prompt engineering, model size,
      and alignment technique is exactly as context-dependent as every
      other architecture choice in this repo -- these case studies force
      the same discipline: name the actual constraint, map it to a
      derived mechanism from L01-L07, name the cost of each defensible
      choice.
LEVEL: Capstone for the LLM Core Theory Notes track -- read after L01-L07.
"""

# ============================================================================
# CASE STUDY 1 — A CUSTOMER-SUPPORT LLM THAT MUST STAY CURRENT WITH A
# FAST-CHANGING PRODUCT CATALOG
# ============================================================================
#
# SETUP: an LLM-powered support assistant for an e-commerce platform
# whose product catalog, pricing, and policies change DAILY. The
# assistant must give accurate, up-to-date answers, ideally with minimal
# latency and infrastructure overhead.
#
# ------------------------------------------------------------------------
# APPROACH A: Fine-tune (SFT, L05) the model regularly on the latest
# catalog/policy data
# ------------------------------------------------------------------------
#   WHY VALID: per L05's Concept #1, SFT directly steers the model's
#   learned behavior/knowledge toward the target distribution -- for
#   information the model should ALWAYS have readily "in mind" (core
#   policies, common product categories), baking it into the weights
#   avoids any retrieval-latency overhead at inference time.
#   COST: daily-changing data makes this approach fundamentally mismatched
#   to the update cadence -- retraining (even lightweight fine-tuning)
#   on a daily basis is a real, recurring engineering/compute cost, and
#   there's an unavoidable STALENESS WINDOW between when data changes and
#   when the next fine-tuning run completes and deploys, during which the
#   model confidently gives OUTDATED answers with no signal to the user
#   that its knowledge might be stale.
#
# ------------------------------------------------------------------------
# APPROACH B: Retrieval-Augmented Generation (RAG) -- retrieve current
# catalog/policy documents at inference time, insert into the prompt
# context (this repo's Agentic AI & RAG Notes covers RAG mechanics in
# depth; this case study focuses on the tradeoff against L05's fine-
# tuning alternatives specifically)
# ------------------------------------------------------------------------
#   WHY VALID: directly solves Approach A's staleness problem -- updating
#   the underlying data store is instantaneous relative to any retraining
#   cycle, and the model's GENERATION capability (language fluency,
#   instruction-following from L05's SFT/RLHF) stays fixed while only the
#   FACTUAL CONTENT it's grounded in changes. This cleanly separates "how
#   to communicate" (a fine-tuning/alignment concern) from "what is
#   currently true" (a retrieval/data-freshness concern).
#   COST: retrieval adds LATENCY (an extra retrieval step before
#   generation can even begin) and INFRASTRUCTURE complexity (a vector
#   store or search index that itself needs to stay synced with the
#   catalog) -- and, per L07's Concept #3, inserting retrieved content
#   into the prompt context is EXACTLY the mechanism that makes RAG
#   systems structurally exposed to prompt injection if any retrieved
#   content can be influenced by an untrusted party (e.g. user-submitted
#   product reviews being retrieved as "context").
#
# ------------------------------------------------------------------------
# APPROACH C: A hybrid -- fine-tune for STABLE knowledge (company voice,
# general policies, common troubleshooting patterns) via SFT, RAG for
# VOLATILE knowledge (current prices, stock levels, today's promotions)
# ------------------------------------------------------------------------
#   WHY VALID: matches EACH type of knowledge to the mechanism best
#   suited to its actual UPDATE FREQUENCY -- stable knowledge gets the
#   latency/reliability benefit of being baked into weights (Approach A's
#   strength, without its staleness cost, since this knowledge genuinely
#   changes rarely); volatile knowledge gets the freshness guarantee of
#   retrieval (Approach B's strength) specifically where staleness would
#   actually cause visible errors.
#   COST: the most operationally complex of the three -- requires
#   correctly CLASSIFYING which knowledge belongs in which bucket (a
#   nontrivial, ongoing product/data-governance decision, not a one-time
#   setup task) and maintaining two separate update pipelines (a
#   fine-tuning cadence AND a retrieval-index sync process) rather than
#   just one.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Freshness | Latency | Injection surface | Ops complexity |
#   |----------|-----------|---------|---------------------|-------------------|
#   | A: SFT only | Poor (staleness window) | Best | None (no retrieved content) | Medium (retraining cadence) |
#   | B: RAG only | Best | Worse (retrieval step) | Real (per L07) | Medium (index sync) |
#   | C: Hybrid | Best (for volatile data) | Medium | Real, but scoped to volatile data only | Highest |
#   For genuinely daily-changing catalog data, B or C clearly beat A on
#   the CORE requirement (freshness) -- between B and C, the choice
#   depends on whether the team has bandwidth for C's added operational
#   complexity in exchange for lower per-query latency on stable-
#   knowledge questions.


# ============================================================================
# CASE STUDY 2 — CHOOSING A MODEL SIZE FOR A LATENCY-SENSITIVE, HIGH-
# VOLUME CLASSIFICATION TASK
# ============================================================================
#
# SETUP: classifying incoming support tickets into ~20 categories, at
# very high volume (millions/day), with a tight latency budget (<100ms
# per classification) -- NOT a generative, open-ended task.
#
# ------------------------------------------------------------------------
# APPROACH A: Prompt a large, general-purpose LLM (few-shot, no fine-
# tuning) to output the category
# ------------------------------------------------------------------------
#   WHY VALID: zero training cost, fastest to stand up, and leverages
#   the large pretrained model's broad world knowledge (L04) for
#   categories with subtle/ambiguous phrasing where a from-scratch
#   classifier might need substantial labeled data to learn similarly
#   nuanced distinctions.
#   COST: per L06's inference-cost discussion, a large general-purpose
#   model has substantially higher per-request latency and compute cost
#   than a much smaller, purpose-built model would -- at "millions/day"
#   volume with a tight latency SLA, this is very likely to be the
#   dominant, possibly disqualifying, cost of this approach.
#
# ------------------------------------------------------------------------
# APPROACH B: Fine-tune (SFT, L05) a SMALL, dedicated LLM specifically
# for this 20-category classification task
# ------------------------------------------------------------------------
#   WHY VALID: directly targets Approach A's cost/latency problem --
#   per L04's scaling-law framing, task-specific fine-tuning on a much
#   smaller model can reach strong accuracy on a NARROW, well-defined
#   task (20 fixed categories) without needing anywhere near the
#   capacity/cost of a large general-purpose model, since the task's
#   genuine complexity (a bounded classification problem) doesn't
#   require the large model's broad, general-purpose capability.
#   COST: requires an actual labeled training dataset (unlike Approach
#   A's zero-shot/few-shot setup) and a fine-tuning pipeline/cadence --
#   real, ongoing engineering investment Approach A avoids entirely, and
#   the smaller model is by construction LESS capable of gracefully
#   handling genuinely novel category-boundary edge cases the training
#   data didn't anticipate.
#
# ------------------------------------------------------------------------
# APPROACH C: A classical ML classifier (Classical ML Theory Notes L03's
# gradient boosting, on embeddings from a SMALL pretrained encoder) --
# explicitly choosing NOT to use a generative LLM at all for this step
# ------------------------------------------------------------------------
#   WHY VALID: this is a direct instance of Deep Learning Theory Notes
#   L08's Case Study 4 reasoning -- a BOUNDED, well-defined classification
#   task over a FIXED label set is not inherently a generative-LLM
#   problem just because LLMs are the current focus; a classical
#   classifier on top of embeddings can be dramatically CHEAPER and
#   FASTER at inference than even a small fine-tuned LLM, while matching
#   or exceeding accuracy on a task this bounded and well-specified.
#   COST: loses any ability to gracefully handle a genuinely novel input
#   that doesn't clearly map to a fixed embedding-space region near any
#   existing category (an LLM's broader language understanding can
#   sometimes reason through such edge cases more gracefully than a
#   pure classifier can), and requires its own separate embedding-model
#   maintenance/versioning discipline.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Latency | Setup cost | Accuracy ceiling | Edge-case robustness |
#   |----------|---------|--------------|----------------------|--------------------------|
#   | A: large LLM prompting | Worst | Lowest | High | Good |
#   | B: fine-tuned small LLM | Better | Medium | High (for this narrow task) | Medium |
#   | C: classical classifier | Best | Medium | Good (for well-separated categories) | Lower |
#   At "millions/day, <100ms" scale, A is very likely disqualified purely
#   on latency/cost economics -- the real decision is B vs. C, trading
#   B's somewhat better edge-case handling against C's superior raw
#   latency/cost efficiency, a decision that should be validated
#   empirically against the ACTUAL observed edge-case rate in this
#   specific ticket stream, not assumed from theory alone.


# ============================================================================
# CASE STUDY 3 — ALIGNING A MODEL FOR A HIGH-STAKES, NARROW DOMAIN
# (MEDICAL TRIAGE SUGGESTIONS)
# ============================================================================
#
# SETUP: an LLM assisting (NOT replacing) clinicians with triage
# suggestions, where the cost of a confidently-wrong suggestion is severe,
# and where the deployment needs strong, auditable safety guarantees.
#
# ------------------------------------------------------------------------
# APPROACH A: Full RLHF (L05) with a reward model specifically trained on
# clinician preference data for THIS domain
# ------------------------------------------------------------------------
#   WHY VALID: per L05's Concept #2-#3, RLHF's reward model can encode
#   nuanced, domain-specific preferences (e.g. "prefer clearly flagging
#   uncertainty over confident-sounding guesses" -- a subtle preference
#   pattern easier for expert clinicians to demonstrate PAIRWISE than to
#   specify as explicit written rules) directly into a differentiable
#   training signal, with the KL penalty (Concept #3) providing a
#   principled guard against the model drifting into reward-hacking
#   behaviors the reward model might not catch.
#   COST: requires substantial clinician time to generate quality
#   preference data (an expensive, slow, expert-bottlenecked process),
#   AND per L05's Concept #3, remains fundamentally VULNERABLE to reward-
#   model imperfection in a domain where an undetected blind spot could
#   have severe real-world consequences -- the exact reward-hacking
#   failure mode L05 derived is far more dangerous here than in a low-
#   stakes creative-writing setting.
#
# ------------------------------------------------------------------------
# APPROACH B: DPO (L05's Concept #4) on the same clinician preference
# data, skipping the separate reward model and RL loop entirely
# ------------------------------------------------------------------------
#   WHY VALID: per L05's derivation, DPO reaches an EQUIVALENT optimum to
#   RLHF (under the stated assumptions) with a simpler, more stable
#   training pipeline -- fewer moving parts to audit and validate is a
#   genuine SAFETY advantage in a high-stakes domain, since a simpler
#   pipeline is more tractable to thoroughly review and test before
#   deployment.
#   COST: per L05's Case Study/production-use discussion, DPO forfeits
#   the SEPARATE reward model's reusability for other safety-relevant
#   purposes (e.g. using the reward model at INFERENCE time to score and
#   filter/reject a generated suggestion before it ever reaches a
#   clinician, an extra safety layer DPO's approach doesn't directly
#   provide without additional separate machinery).
#
# ------------------------------------------------------------------------
# APPROACH C: Constrain the system architecturally -- use an aligned
# model (either A or B) ONLY to draft/suggest, with a HARD requirement
# that every suggestion is explicitly flagged as unverified and requires
# clinician sign-off, PLUS a separate, simpler, high-precision rule-based
# or classical-ML (Classical ML Theory Notes) triage-flagging system
# running IN PARALLEL as a sanity check
# ------------------------------------------------------------------------
#   WHY VALID: directly applies L07's Concept #3 lesson (no current
#   alignment technique provides a structural, provable safety guarantee)
#   -- rather than relying SOLELY on the LLM's learned alignment
#   behavior (however well-trained), this approach treats alignment
#   training as ONE layer of a defense-in-depth system, with a genuinely
#   INDEPENDENT (differently-failure-mode) system providing a cross-
#   check, and a hard human-sign-off requirement as the final,
#   non-bypassable safety boundary.
#   COST: the most operationally complex and slowest (human-in-the-loop
#   sign-off adds real latency to the workflow) of the three -- and
#   requires maintaining TWO separate systems (the LLM and the parallel
#   classical checker) rather than one, a genuine ongoing engineering cost.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Alignment quality | Pipeline simplicity/auditability | Structural safety guarantee | Cost |
#   |----------|----------------------|--------------------------------------|--------------------------------|------|
#   | A: full RLHF | Potentially highest (rich reward signal) | Lowest (most moving parts) | None beyond learned behavior | Highest (clinician time) |
#   | B: DPO | High, simpler pipeline | Higher | None beyond learned behavior | Medium |
#   | C: defense-in-depth wrapper | Depends on A or B underneath | Adds a layer, but each layer simpler | Real (human sign-off is a hard boundary) | Highest (multi-system) |
#   For a domain with THIS severity of stakes, C is very likely necessary
#   REGARDLESS of whether A or B is used underneath -- this case study's
#   explicit lesson is that "which alignment technique" (A vs. B) and
#   "whether to add structural safety layers on top" (C) are NOT
#   competing alternatives but answer different questions, and a mature
#   high-stakes deployment needs an answer to BOTH.


# ============================================================================
# CASE STUDY 4 — SERVING A CONVERSATIONAL ASSISTANT WITH LONG,
# MULTI-TURN CONTEXT AT SCALE
# ============================================================================
#
# SETUP: a consumer chat product where conversations can run to hundreds
# of turns, served to millions of concurrent users, with real
# infrastructure cost pressure (GPU-hours are the dominant cost driver).
#
# ------------------------------------------------------------------------
# APPROACH A: Send the FULL conversation history as context on every
# turn, relying on correctly-implemented KV caching (L06) for efficiency
# ------------------------------------------------------------------------
#   WHY VALID: preserves perfect fidelity to the full conversation --
#   the model genuinely has access to everything said, avoiding any risk
#   of losing relevant earlier context. Per L06's Concept #2, correctly-
#   implemented KV caching makes the PER-TURN incremental cost of
#   extending an existing conversation O(1) new tokens' worth of K/V
#   computation, not re-processing the whole history from scratch.
#   COST: even with KV caching eliminating the REDUNDANT computation,
#   the underlying attention mechanism's O(T^2) cost (Deep Learning
#   Theory Notes L07) in TOTAL conversation length still applies to
#   EVERY forward pass's attention computation itself -- a several-
#   hundred-turn conversation eventually hits real memory (the KV cache
#   itself, per L06's memory-cost note) and compute limits regardless of
#   caching efficiency, and per-user memory cost scales with THEIR
#   specific conversation length, complicating capacity planning at
#   "millions of concurrent users" scale.
#
# ------------------------------------------------------------------------
# APPROACH B: Periodically SUMMARIZE older conversation turns (using the
# LLM itself) into a compressed representation, replacing the full old
# turns with the summary in subsequent context
# ------------------------------------------------------------------------
#   WHY VALID: directly bounds the effective context length regardless
#   of how long the conversation actually runs, keeping both the
#   attention-computation cost AND the KV-cache memory cost bounded --
#   a genuine, scalable fix for Approach A's unbounded-growth problem.
#   COST: summarization is LOSSY by construction -- some genuinely
#   relevant detail from early in a long conversation may not survive
#   into the summary, and (per L07's evaluation-validity concerns) the
#   summarization step ITSELF is a place errors/hallucinations can be
#   introduced, silently corrupting the assistant's effective memory of
#   the conversation in a way that's hard for the user to detect or
#   correct.
#
# ------------------------------------------------------------------------
# APPROACH C: Use ALiBi or another length-extrapolation-friendly
# positional encoding (L03's Concept #4) combined with a windowed/sparse
# attention mechanism, explicitly trading full-history fidelity for
# bounded compute
# ------------------------------------------------------------------------
#   WHY VALID: addresses the SAME scaling problem as Approach B, but via
#   an ARCHITECTURAL choice made once (at model-design/training time)
#   rather than an additional per-conversation RUNTIME operation
#   (summarization) that itself consumes compute and introduces its own
#   failure mode -- per L03's Concept #4, ALiBi specifically is designed
#   to behave predictably and gracefully even for sequences longer than
#   anything seen in training, directly targeting long-conversation
#   robustness at the architecture level.
#   COST: per L03's Concept #4 and Case Study 1's cost discussion,
#   windowed/sparse attention explicitly SACRIFICES the ability to
#   attend to arbitrarily distant past turns with full fidelity -- a
#   genuinely different (architectural, not per-conversation-tunable)
#   tradeoff than Approach B's lossy-but-adaptive summarization, and
#   this choice must be baked in at TRAINING time, unlike B, which can
#   be added as a serving-layer technique on top of an already-trained
#   model without retraining.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Fidelity to full history | Compute/memory scaling | When the tradeoff is decided | Failure mode |
#   |----------|-----------------------------|----------------------------|----------------------------------|-------------------|
#   | A: full history + KV cache | Highest | Unbounded (grows with conversation) | N/A (no compression) | Eventually hits hard limits |
#   | B: periodic summarization | Lossy, adaptively | Bounded | Runtime, per conversation | Summarization errors/hallucination |
#   | C: architectural windowing | Lossy, structurally | Bounded | Training time (fixed) | Fixed, predictable attention range loss |
#   B and C both solve the scaling problem A cannot sustain indefinitely,
#   via genuinely different mechanisms (a runtime operation vs. a
#   training-time architectural choice) -- B is retrofittable onto an
#   existing deployed model; C requires the choice to have been made
#   before pretraining, making it a much earlier, harder-to-reverse
#   commitment, a real practical distinction beyond the pure fidelity/
#   compute tradeoff table above.
"""
As in the prior two domains' capstone lessons, this file has no runnable
code -- its content IS the comparative reasoning above. Before checking
the comparison tables, try reconstructing them yourself using only
L01-L07's derived mechanisms (KV-cache cost, attention's O(T^2) scaling,
RLHF/DPO's reward-hacking and equivalence properties, positional
encoding's extrapolation tradeoffs, evaluation-metric validity) -- the
goal is the reasoning pattern, not memorizing these four specific
verdicts.
"""
