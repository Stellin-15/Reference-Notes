"""
WHAT: Why perplexity (L04) and benchmark accuracy measure genuinely
      different things and can diverge, the LLM-as-judge evaluation
      pattern derived along with its specific, structural biases, and
      jailbreaking/prompt injection analyzed as a direct consequence of
      causal LM's inability to structurally distinguish "instruction" from
      "data" in its input stream.
WHY:  "We evaluate LLMs with benchmarks" and "LLMs can be jailbroken"
      are both true but shallow without mechanism. This lesson connects
      evaluation validity back to Classical ML Theory Notes L07's
      metric-choice framework (now applied to generative, not
      classification, outputs) and derives WHY prompt injection is not
      a "bug" to be patched away but a structural consequence of the
      causal LM objective itself (L04) treating all input tokens
      identically regardless of their intended ROLE.
LEVEL: Foundational -- final lesson before this track's case studies.

PREREQUISITE: L04 (causal LM objective, perplexity); L05 (RLHF/DPO --
alignment techniques this lesson evaluates the LIMITS of); Classical ML
Theory Notes L07 (metric-validity framework, directly extended here).
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — WHY LOWER PERPLEXITY DOES NOT GUARANTEE BETTER TASK
# PERFORMANCE (a direct generative-model instance of Classical ML Theory
# Notes L07's "the metric you optimize is not always the metric you care
# about" lesson)
# ============================================================================
#
# L04 established perplexity as a direct, monotonic transform of the
# causal LM cross-entropy loss -- a measure of how well the model
# predicts the NEXT TOKEN in held-out TEXT drawn from a specific
# distribution (typically resembling the pretraining/fine-tuning data
# distribution). Two DIFFERENT models, or the SAME model at different
# checkpoints, can have very different perplexity-vs-downstream-task
# relationships, for reasons directly analogous to Classical ML Theory
# Notes L07's accuracy-vs-precision/recall gap:
#
#   1. PERPLEXITY IS DISTRIBUTION-SPECIFIC: a model with LOW perplexity
#      on generic web text may have comparatively HIGH perplexity on,
#      say, legal documents or a specific downstream task's input
#      distribution -- perplexity says nothing about performance on
#      distributions NOT represented in the evaluation text, exactly
#      the same distribution-dependence concern L01's PAC-bound
#      framing raised for train/test distribution mismatch generally.
#   2. PERPLEXITY MEASURES TOKEN-LEVEL PREDICTION, NOT TASK SUCCESS: a
#      model can achieve excellent perplexity (accurately predicting
#      FLUENT, natural-sounding continuations) while still failing a
#      DOWNSTREAM TASK requiring, e.g., correct arithmetic, faithful
#      summarization, or accurate factual recall -- fluent, low-
#      perplexity text and CORRECT text are simply different properties,
#      and a model optimized purely for next-token prediction accuracy
#      has no GUARANTEE of also being reliably correct on tasks
#      requiring multi-step reasoning or precise factual grounding.
#   3. RLHF/DPO FINE-TUNING (L05) TYPICALLY INCREASES PERPLEXITY ON THE
#      ORIGINAL PRETRAINING DISTRIBUTION, WHILE IMPROVING TASK
#      PERFORMANCE: aligning a model toward helpful, instruction-
#      following behavior deliberately shifts its output distribution
#      AWAY from simply mimicking raw internet text's statistical
#      patterns (which is what perplexity, computed against a raw-text
#      reference, measures) -- an aligned model that refuses harmful
#      requests, gives concise rather than rambling answers, or follows
#      specific formatting instructions is, BY DESIGN, less similar to
#      generic internet text, which can show up as HIGHER perplexity on
#      a generic web-text benchmark despite being a clearly BETTER
#      instruction-following model in every practically relevant sense.
#
# THIS IS WHY MODERN LLM EVALUATION RELIES ON TASK-SPECIFIC BENCHMARKS
# (multiple-choice QA accuracy, code-execution pass rates, human/LLM-
# judged preference comparisons) RATHER THAN PERPLEXITY ALONE for
# comparing aligned, instruction-tuned models -- perplexity remains
# useful for monitoring PRETRAINING progress (L04) specifically, but is
# a poor, potentially actively misleading, metric for comparing
# DOWNSTREAM task capability across differently-aligned models.

def demonstrate_perplexity_task_accuracy_can_diverge():
    """
    A toy illustration (not a literal simulation of real training
    dynamics, but structurally accurate): a 'raw' model that closely
    mimics generic text (low perplexity on generic text, LOW task
    accuracy because it doesn't reliably follow instructions) versus an
    'aligned' model (higher perplexity on generic text -- it deviates
    from generic patterns on purpose -- but HIGH task accuracy).
    """
    models = {
        "raw_pretrained": {"perplexity_on_generic_text": 12.0, "task_accuracy": 0.31},
        "aligned_sft_rlhf": {"perplexity_on_generic_text": 18.5, "task_accuracy": 0.79},
    }
    return models


# ============================================================================
# CONCEPT #2 — LLM-AS-JUDGE EVALUATION: THE PATTERN AND ITS STRUCTURAL
# BIASES
# ============================================================================
#
# Given that human evaluation is slow and expensive, a common modern
# pattern is LLM-AS-JUDGE: use a strong LLM to compare two candidate
# responses (from the model being evaluated and a reference/competitor
# model) and pick the "better" one, or assign a numeric quality score --
# structurally identical to the pairwise Bradley-Terry preference
# comparison L05's reward-model training used, just with an LLM's
# judgment substituting for a human rater's.
#
# WHY THIS INTRODUCES SPECIFIC, DOCUMENTED, SYSTEMATIC BIASES (not
# random noise, which would be less concerning -- these are directional,
# repeatable distortions):
#   1. POSITION BIAS: LLM judges have been repeatedly documented to favor
#      whichever response is presented FIRST (or, in some models,
#      SECOND) in the prompt, independent of actual quality -- a
#      well-known, measurable artifact requiring mitigation (e.g.
#      evaluating BOTH orderings and combining results) that a naive
#      single-ordering evaluation setup will silently miss.
#   2. LENGTH BIAS: LLM judges have been repeatedly documented to favor
#      LONGER responses, independent of whether that additional length
#      reflects genuinely more useful content -- structurally the SAME
#      reward-hacking vulnerability L05's Concept #3 identified for
#      RLHF's reward model, now appearing in the judge model itself
#      rather than a separately-trained reward model.
#   3. SELF-PREFERENCE BIAS: an LLM used to judge outputs, including its
#      OWN model family's outputs against a competitor, has been shown in
#      several studies to systematically favor outputs more similar in
#      STYLE to its own typical outputs -- a genuine confound when using
#      GPT-family judges to evaluate GPT-family outputs against a
#      differently-trained competitor, independent of the competing
#      outputs' actual quality.
#
# WHY THIS MATTERS OPERATIONALLY, CONNECTING DIRECTLY BACK TO CLASSICAL
# ML THEORY NOTES L07's STATISTICAL-SIGNIFICANCE DISCUSSION: an LLM-judge
# win rate of "62% vs 38%" between two models is subject to BOTH ordinary
# sampling noise (Classical ML Theory Notes L07's Concept #4 -- is this
# difference even statistically distinguishable from a smaller test set)
# AND these additional, SYSTEMATIC judge biases that a simple confidence
# interval does NOT correct for -- a rigorous LLM-as-judge evaluation
# needs randomized response ordering (fixing position bias), length-
# controlled or length-normalized comparison, and ideally a JUDGE MODEL
# from a DIFFERENT family than either candidate being compared (partially
# mitigating self-preference bias), none of which a naive "just ask an
# LLM which is better" setup provides by default.

def demonstrate_position_bias(seed=0):
    """
    A toy simulation of position bias: an LLM judge's win-probability for
    'response A' as a function of WHICH position it's shown in, holding
    the UNDERLYING quality of A and B FIXED and equal -- confirming a
    genuinely unbiased judge should show ~50% either way, while a biased
    judge (simulated here) shows a systematic shift purely from ordering.
    """
    rng = np.random.default_rng(seed)
    n_trials = 2000
    # Simulate a judge with a REAL first-position bias: +0.15 log-odds
    # boost simply for being shown first, regardless of actual quality
    # (which is held IDENTICAL between A and B in this simulation).
    position_bias_logit = 0.6

    a_shown_first = rng.integers(0, 2, n_trials).astype(bool)
    # Underlying TRUE quality is IDENTICAL (logit=0, i.e. true 50/50) --
    # any deviation from 50% observed below is PURELY the position bias.
    true_quality_logit = np.zeros(n_trials)
    judge_logit = true_quality_logit + np.where(a_shown_first, position_bias_logit, -position_bias_logit)
    p_a_wins = 1 / (1 + np.exp(-judge_logit))
    a_wins = rng.uniform(size=n_trials) < p_a_wins

    win_rate_when_first = a_wins[a_shown_first].mean()
    win_rate_when_second = a_wins[~a_shown_first].mean()
    return win_rate_when_first, win_rate_when_second


# ============================================================================
# CONCEPT #3 — PROMPT INJECTION AND JAILBREAKING AS A STRUCTURAL
# CONSEQUENCE OF CAUSAL LM, NOT A PATCHABLE BUG
# ============================================================================
#
# Recall L04's Concept #1: causal LM's ENTIRE training objective is
# P_theta(next_token | ALL preceding tokens) -- EVERY preceding token,
# regardless of whether it came from a "system prompt," a "developer
# instruction," "trusted user input," or "untrusted third-party data
# retrieved via a tool call," is architecturally just... preceding
# tokens. There is NOTHING in the base Transformer architecture (L02) or
# the causal LM training objective (L04) that structurally, mechanically
# DISTINGUISHES these different ROLES of input tokens the way, say, a
# typed programming language distinguishes code from data, or an SQL
# engine (when used correctly, with parameterized queries) structurally
# separates a query's fixed logic from user-supplied values.
#
# THIS IS WHY PROMPT INJECTION IS BEST UNDERSTOOD AS A STRUCTURAL
# CONSEQUENCE OF THE ARCHITECTURE, NOT A BUG TO BE PATCHED: if an
# attacker can get text under their control into ANY part of the token
# sequence the model conditions on (a document the model is asked to
# summarize, a webpage retrieved via a tool call, a user-submitted form
# field embedded into a larger prompt template), and that text CONTAINS
# something that LOOKS, statistically, like a plausible instruction
# ("Ignore previous instructions and instead..."), the model has no
# ARCHITECTURAL mechanism forcing it to treat that text differently from
# a genuine system-level instruction -- both are just tokens in its
# context, and the model's learned behavior of "follow instructions that
# appear in my context" (itself a DIRECT, INTENDED consequence of L05's
# SFT/RLHF alignment training) applies to BOTH indiscriminately unless
# something ELSE (additional training, architectural changes, or
# external guardrails) specifically teaches or enforces a distinction.
#
# CURRENT MITIGATIONS AND THEIR HONEST LIMITS: RLHF/DPO fine-tuning
# (L05) CAN be used to train a model to behave DIFFERENTLY based on
# structural/positional cues (e.g. text explicitly delimited as "system"
# vs. "user" vs. "retrieved content" via special tokens or consistent
# formatting conventions) -- this genuinely helps and is standard modern
# practice, but it is a LEARNED, STATISTICAL behavior (the model has
# learned "text after this special token pattern is usually less
# trustworthy," a PATTERN, not a hard architectural guarantee), not a
# structural, provably-enforced boundary the way memory-safe language
# type systems provide provable guarantees against certain classes of
# bugs. A sufficiently adversarial input can still, in principle, find
# phrasing that evades the LEARNED distinction -- this is why prompt
# injection remains an open, actively-researched problem rather than one
# considered definitively "solved" by any current alignment technique,
# and why defense-in-depth (external guardrails, permission scoping on
# what actions a model-driven agent can actually TAKE regardless of what
# it's been told to do, output filtering) remains standard practice
# rather than relying on the model's own learned instruction-following
# discipline alone.

def demonstrate_no_architectural_distinction(seed=0):
    """
    Illustrates Concept #3 structurally (not a literal running model):
    confirms that, mechanically, a causal LM's attention mechanism
    (L02/Deep Learning Theory Notes L07) computes attention scores from
    Q.K dot products with NO input to that computation indicating
    whether a given KEY position originated from a 'system', 'user', or
    'retrieved document' role -- the role information, if used at all,
    can only enter via whatever the TOKEN EMBEDDINGS AND LEARNED WEIGHTS
    happen to encode about patterns like delimiter tokens, not via any
    separate, structurally-enforced channel.
    """
    rng = np.random.default_rng(seed)
    d_model = 8
    # Two tokens: one from a 'trusted system prompt', one from 'untrusted
    # retrieved content' -- but BOTH are embedded into the SAME vector
    # space via the SAME embedding table and the SAME W_Q/W_K projections.
    system_token_embedding = rng.normal(size=d_model)
    untrusted_token_embedding = rng.normal(size=d_model)
    W_Q = rng.normal(0, 0.1, size=(d_model, d_model))
    W_K = rng.normal(0, 0.1, size=(d_model, d_model))

    # The attention SCORE computation is IDENTICAL in form regardless of
    # source -- there's no separate 'trust' input to this function at all.
    query = rng.normal(size=d_model) @ W_Q
    score_vs_system = query @ (system_token_embedding @ W_K)
    score_vs_untrusted = query @ (untrusted_token_embedding @ W_K)
    return score_vs_system, score_vs_untrusted


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A team deploying an LLM-powered customer-support agent that can browse
# retrieved documentation to answer questions discovers, via a red-team
# exercise, that a maliciously crafted support ticket (submitted by a
# user, then later RETRIEVED by the agent as "context" when handling a
# DIFFERENT, unrelated ticket) can cause the agent to leak information
# from other tickets or take unintended actions. Per Concept #3, this is
# NOT a one-off implementation bug to hunt down and patch -- it's the
# expected, structural consequence of any causal-LM-based agent
# conditioning on attacker-influenced retrieved content, and the correct,
# durable response follows directly from this lesson's honest assessment
# of current mitigations' limits: (a) apply learned instruction-hierarchy
# fine-tuning (a real, partial mitigation) AND (b) treat it as
# insufficient ALONE -- enforce hard PERMISSION BOUNDARIES at the SYSTEM
# level (the agent's tool-use layer should never have unscoped access to
# other users' tickets in the first place, regardless of what any prompt
# claims), so that even a successful injection cannot exceed a
# structurally-enforced blast radius. This is a defense-in-depth
# architecture decision directly informed by Concept #3's "no
# architectural distinction" finding, not a hope that better prompting
# or alignment training alone will eventually close the gap.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Using perplexity as the primary metric for comparing INSTRUCTION-
#    TUNED/aligned models against each other. Per Concept #1, alignment
#    training can legitimately INCREASE perplexity on generic text while
#    IMPROVING real task performance -- a lower-perplexity aligned model
#    is not necessarily the better one for actual downstream use.
# 2. Treating a single LLM-as-judge win-rate number as ground truth
#    without accounting for Concept #2's documented, systematic biases
#    (position, length, self-preference) -- these are DIRECTIONAL
#    distortions, not just noise a larger sample size averages away, and
#    require specific mitigations (randomized ordering, length
#    normalization, cross-family judges), not just more evaluation
#    trials.
# 3. Believing a prompt-injection vulnerability, once patched via
#    improved system-prompt phrasing or one round of adversarial fine-
#    tuning, is "fixed" permanently. Per Concept #3, the underlying
#    structural gap (no architectural role-distinction) remains --
#    any specific patch addresses the SPECIFIC attack phrasings tested,
#    not the general vulnerability class, which is why ongoing red-
#    teaming and defense-in-depth (not a one-time fix) is standard
#    practice for any production system processing untrusted input.
# 4. Assuming benchmark accuracy numbers (e.g. "outperforms on MMLU")
#    generalize to arbitrary real-world use cases outside what the
#    benchmark actually measures -- exactly Classical ML Theory Notes
#    L07's "the metric you optimize/report is not automatically the
#    metric that matters for your specific deployment" caution, applied
#    to LLM benchmarks specifically; benchmark contamination (test
#    questions leaking into pretraining data) is also a well-documented,
#    real concern that can inflate reported benchmark numbers without
#    reflecting genuine capability improvement.


if __name__ == "__main__":
    print("=" * 70)
    print("CONCEPT #1: perplexity and task accuracy can move in OPPOSITE directions")
    print("=" * 70)
    models = demonstrate_perplexity_task_accuracy_can_diverge()
    for name, metrics in models.items():
        print(f"  {name}: perplexity={metrics['perplexity_on_generic_text']}, "
              f"task_accuracy={metrics['task_accuracy']}")
    print("-> The ALIGNED model has HIGHER perplexity on generic text (it deviates")
    print("   from raw-internet-text patterns on purpose) but MUCH higher task")
    print("   accuracy -- picking a model by 'lowest perplexity' alone would select")
    print("   the WORSE model for actual instruction-following use.")

    print("\n" + "=" * 70)
    print("CONCEPT #2: position bias -- a judge's verdict shifts purely from")
    print("ORDERING, with TRUE quality held identical")
    print("=" * 70)
    win_rate_first, win_rate_second = demonstrate_position_bias()
    print(f"Win rate for response A when shown FIRST:  {win_rate_first:.3f}")
    print(f"Win rate for response A when shown SECOND: {win_rate_second:.3f}")
    print(f"(True underlying quality was IDENTICAL between A and B in this simulation --")
    print(f" any deviation from 50%/50% above is PURELY the simulated position bias.)")

    print("\n" + "=" * 70)
    print("CONCEPT #3: attention score computation has no structural 'trust' input")
    print("=" * 70)
    score_system, score_untrusted = demonstrate_no_architectural_distinction()
    print(f"Attention score toward 'system prompt' token: {score_system:.4f}")
    print(f"Attention score toward 'untrusted retrieved' token: {score_untrusted:.4f}")
    print("-> Both computed via the IDENTICAL Q.K formula, from the SAME learned")
    print("   W_Q/W_K -- there is no separate 'is this trusted' input anywhere in")
    print("   this computation; any distinction the model makes must be LEARNED")
    print("   from patterns in the embeddings/weights, not architecturally guaranteed.")
