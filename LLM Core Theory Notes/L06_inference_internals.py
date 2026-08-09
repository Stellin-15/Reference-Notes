"""
WHAT: KV caching derived from identifying the exact redundant computation
      naive autoregressive generation performs, and the major sampling
      strategies (greedy, temperature, top-k, top-p/nucleus) derived from
      the specific failure mode each one fixes in its predecessor.
WHY:  "LLMs cache keys and values for faster generation" and "temperature
      controls randomness" are usually stated without the mechanism. This
      lesson derives EXACTLY what computation KV caching eliminates (and
      quantifies the resulting speedup), and shows precisely why greedy
      decoding fails, why raw sampling also fails differently, and how
      each subsequent sampling strategy targets the specific gap its
      predecessor left open.
LEVEL: Foundational.

PREREQUISITE: L02 (Transformer architecture, Q/K/V, causal masking) --
this lesson is entirely about what happens differently at INFERENCE time
versus the training-time forward pass L02-L04 describe.
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — THE REDUNDANT COMPUTATION NAIVE AUTOREGRESSIVE GENERATION
# PERFORMS, IDENTIFIED PRECISELY
# ============================================================================
#
# Generating text autoregressively means: given a prompt, predict the
# next token, APPEND it to the sequence, then predict the NEXT next
# token given the now-longer sequence, repeating one token at a time.
#
# THE NAIVE APPROACH: at EVERY generation step, re-run the ENTIRE forward
# pass over the WHOLE sequence so far (prompt + all tokens generated up
# to this point) from scratch. This is enormously wasteful, and the exact
# source of waste is identifiable: recall from L02 that computing
# attention at position i requires Q_i (specific to position i) but K_j
# and V_j for EVERY position j <= i (via the causal mask). Crucially,
# K_j and V_j for any ALREADY-PROCESSED position j do NOT depend on any
# LATER token -- K_j = (token_j's embedding) @ W_K is a function purely
# of token j and the model's (fixed, already-trained) weights, computed
# identically regardless of what tokens come after position j.
#
# NAIVE GENERATION RE-COMPUTES K_j AND V_j FOR EVERY POSITION j, AT
# EVERY SINGLE GENERATION STEP, EVEN THOUGH THOSE VALUES NEVER CHANGE
# ONCE COMPUTED -- this is the precise, identifiable redundancy: for a
# sequence of length T generated one token at a time, computing K/V for
# position 1 happens T-1 UNNECESSARY EXTRA TIMES (once when position 1
# is first processed, correctly, and then needlessly AGAIN at every
# subsequent generation step, recomputing an identical value each time).

def naive_generation_step(x_tokens, W_K, W_V, W_Q):
    """Illustrates the WASTEFUL approach: recompute K, V for the ENTIRE
    sequence so far at every single step, even though most of it is
    identical to the previous step's computation."""
    K = x_tokens @ W_K  # recomputed for EVERY position, EVERY step
    V = x_tokens @ W_V  # same waste
    Q_new = x_tokens[-1:] @ W_Q  # only the newest token's query is actually new
    return Q_new, K, V


# ============================================================================
# CONCEPT #2 — THE KV CACHE: STORE, DON'T RECOMPUTE
# ============================================================================
#
# The fix follows directly from Concept #1's diagnosis: maintain a CACHE
# of every already-computed K_j, V_j pair. At each NEW generation step,
# compute K, V ONLY for the single NEW token just generated, APPEND these
# to the cache, and use the FULL cache (old + newly appended) for the
# attention computation -- Q is still only needed for the new token
# (since causal masking means earlier positions' outputs, and hence their
# queries, were already finalized in earlier steps and never need
# recomputing).
#
#   step t: K_cache = [K_1, ..., K_{t-1}]  (already computed, stored)
#           compute K_t, V_t for the NEW token only
#           K_cache <- K_cache + [K_t]     (append, not recompute)
#           attention uses Q_t against the FULL K_cache/V_cache
#
# COMPLEXITY IMPACT, QUANTIFIED: naive generation of T tokens does
# O(T) sequence-processing steps, each RE-processing an average of ~T/2
# tokens -- roughly O(T^2) total token-processing work just for the
# K/V computation across the whole generation (separate from, and
# additional to, the O(T^2) attention-score computation cost itself,
# which is unavoidable and shared by both approaches). WITH a KV cache,
# each step processes EXACTLY 1 new token for the K/V computation --
# O(T) total token-processing work across the whole generation, a
# genuine ASYMPTOTIC improvement (not just a constant-factor speedup)
# for the K/V-computation portion of the cost specifically.
#
# THE COST THIS BUYS: MEMORY. The cache must store K, V for EVERY
# position in the sequence generated so far, for EVERY layer and EVERY
# attention head -- for long contexts and large models, this KV cache
# memory footprint becomes a genuinely major production constraint
# (frequently the DOMINANT memory cost at inference time for long-
# context generation, motivating substantial engineering effort in
# techniques like multi-query/grouped-query attention and paged
# attention, covered in this repo's LLM Quantization & Inference Notes).

def kv_cache_generation_step(new_token_embedding, W_K, W_V, W_Q, K_cache, V_cache):
    """The efficient approach: compute K, V ONLY for the new token,
    append to the existing cache -- no recomputation of past positions."""
    K_new = new_token_embedding @ W_K   # just ONE new row, not the whole sequence
    V_new = new_token_embedding @ W_V
    Q_new = new_token_embedding @ W_Q
    K_cache = np.vstack([K_cache, K_new]) if K_cache is not None else K_new
    V_cache = np.vstack([V_cache, V_new]) if V_cache is not None else V_new
    return Q_new, K_cache, V_cache


def count_kv_computations(seq_len, use_cache):
    """Counts the TOTAL number of individual token positions that have
    K/V computed for them, summed across all `seq_len` generation steps
    -- directly quantifying Concept #2's asymptotic-improvement claim."""
    if use_cache:
        return seq_len  # exactly one NEW position computed per step
    else:
        return sum(range(1, seq_len + 1))  # step t re-processes t positions


# ============================================================================
# CONCEPT #3 — GREEDY DECODING'S FAILURE MODE: LOCALLY OPTIMAL, GLOBALLY
# OFTEN WRONG
# ============================================================================
#
# The simplest generation strategy: at every step, deterministically pick
# the SINGLE highest-probability next token (argmax over the model's
# output distribution). This is a GREEDY algorithm in exactly the sense
# Classical ML Theory Notes L03 used the term for tree-splitting --
# locally optimal at each individual step, with NO guarantee of producing
# the globally highest-probability FULL SEQUENCE.
#
# WHY GREEDY CAN BE GLOBALLY SUBOPTIMAL: consider a case where the single
# highest-probability FIRST token leads only to LOW-probability
# continuations (a "dead end" in probability-mass terms), while a
# slightly lower-probability first token opens up a path to a much
# higher-probability continuation overall. Greedy decoding, by
# construction, can NEVER discover this -- it commits irrevocably to the
# locally-best choice at each step, with no mechanism to reconsider based
# on how that choice affects FUTURE steps' probabilities. This is
# EXACTLY the same limitation greedy tree-splitting has (Classical ML
# Theory Notes L03): locally sound, not globally optimal, by
# construction, not by implementation flaw.
#
# BEAM SEARCH (maintaining the top-k highest-probability PARTIAL
# sequences at each step, rather than committing to just the single best
# one) partially mitigates this by exploring several candidate paths in
# parallel -- still not a GLOBAL guarantee (the true highest-probability
# sequence could still fall outside the beam if it requires several
# consecutive individually-unlikely-looking tokens), but a real,
# quantifiable improvement over pure greedy's single-path commitment.
#
# GREEDY'S OTHER, SEPARATE FAILURE MODE: even where it DOES find a
# high-probability sequence, greedy decoding is entirely DETERMINISTIC --
# the same prompt always produces the exact same output, and in practice
# greedy decoding is well-documented to produce noticeably repetitive,
# generic text (the model gets stuck in locally-high-probability loops,
# e.g. repeating the same phrase, since "repeat what was just said" is
# often a genuinely high-probability continuation the model has learned).
# This is a DIFFERENT problem from the local-vs-global-optimum issue
# above, and it's the specific problem SAMPLING-based strategies (Concept
# #4) are built to address, not beam search.

def greedy_decode_step(logits):
    return np.argmax(logits)


# ============================================================================
# CONCEPT #4 — TEMPERATURE, TOP-K, AND TOP-P: EACH FIXES A SPECIFIC GAP
# ITS PREDECESSOR LEAVES OPEN
# ============================================================================
#
# PURE SAMPLING (draw the next token randomly from the model's FULL
# predicted probability distribution, rather than taking the argmax):
# fixes greedy's repetitiveness problem (genuine randomness breaks
# deterministic loops), but introduces a NEW problem -- the model's
# predicted distribution over a large vocabulary typically has a very
# long, thin TAIL of extremely-low-but-nonzero-probability tokens.
# Sampling from the FULL distribution means occasionally drawing one of
# these tail tokens, producing a bizarre, incoherent completion that,
# while technically "possible" under the model's distribution, is
# usually a genuinely poor continuation nearly every human reader would
# judge as an error, not creative diversity.
#
# TEMPERATURE (T) rescales the logits BEFORE softmax:
#   P(token_i) = softmax(logit_i / T)
# T=1 recovers the original distribution unchanged. T<1 SHARPENS the
# distribution (high-probability tokens become relatively MORE likely,
# low-probability tokens relatively LESS likely) -- as T->0, this
# converges exactly to greedy decoding (the distribution concentrates
# entirely on the argmax). T>1 FLATTENS the distribution toward uniform,
# increasing randomness/diversity further. Temperature is a SMOOTH,
# CONTINUOUS knob interpolating between fully deterministic (greedy) and
# increasingly random -- but it does NOT solve the long-tail problem
# directly; it only rescales, it doesn't TRUNCATE the tail, so even a
# low temperature still assigns SOME nonzero probability to every token
# in the vocabulary, including the incoherent tail options, just with
# reduced (not eliminated) likelihood.
#
# TOP-K SAMPLING directly addresses the tail problem via TRUNCATION:
# restrict sampling to ONLY the K highest-probability tokens (renormalize
# their probabilities to sum to 1, sample from THAT restricted set).
# This guarantees genuinely low-probability tail tokens are NEVER
# selected, fixing pure sampling's incoherence problem directly rather
# than just reducing its likelihood. THE GAP TOP-K LEAVES OPEN: K is a
# FIXED number regardless of context -- but the model's predicted
# distribution's SHAPE varies enormously by context. For a very
# CONFIDENT prediction (one token has overwhelming probability, e.g.
# completing "The capital of France is ___"), a fixed K=50 might still
# include 49 essentially-irrelevant, low-quality options that shouldn't
# realistically be considered. For a very UNCERTAIN prediction (many
# tokens are all plausible, e.g. continuing an open-ended creative
# prompt), a fixed K=50 might be too RESTRICTIVE, excluding genuinely
# reasonable options just because the distribution happens to be
# spread more broadly across more than 50 tokens that step.
#
# TOP-P (NUCLEUS) SAMPLING fixes top-k's fixed-cutoff rigidity by
# truncating based on CUMULATIVE PROBABILITY MASS instead of a fixed
# COUNT: include the smallest set of highest-probability tokens whose
# probabilities SUM to at least P (e.g. P=0.9 -- include just enough of
# the highest-probability tokens to cover 90% of the total probability
# mass), renormalize, sample from that set. This ADAPTS automatically to
# the distribution's shape at each step: a confident prediction needs
# very FEW tokens to reach 90% cumulative mass (a small, tight nucleus);
# an uncertain prediction needs MANY tokens to reach 90% (a larger,
# broader nucleus) -- directly solving top-k's context-insensitivity
# problem by making the EFFECTIVE cutoff size a function of the actual
# distribution's shape at each specific step, rather than a single fixed
# number applied uniformly regardless of context.

def temperature_scale(logits, T):
    return logits / T


def top_k_filter(logits, k):
    """Sets all but the top-k logits to -infinity (so they get exactly
    zero probability after softmax) -- hard truncation, fixed count."""
    if k >= len(logits):
        return logits
    threshold = np.sort(logits)[-k]
    return np.where(logits >= threshold, logits, -np.inf)


def top_p_filter(logits, p):
    """Keeps the smallest set of highest-probability tokens whose
    cumulative probability reaches at least p -- adaptive cutoff SIZE,
    varying with how concentrated or spread the distribution is."""
    sorted_idx = np.argsort(logits)[::-1]
    sorted_logits = logits[sorted_idx]
    probs = np.exp(sorted_logits - sorted_logits.max())
    probs /= probs.sum()
    cumulative = np.cumsum(probs)
    cutoff = np.searchsorted(cumulative, p) + 1
    keep_idx = sorted_idx[:cutoff]
    filtered = np.full_like(logits, -np.inf)
    filtered[keep_idx] = logits[keep_idx]
    return filtered, cutoff  # cutoff: how many tokens were kept, for inspection


def demonstrate_top_p_adapts_to_distribution_shape(vocab_size=100, p=0.9, seed=0):
    """
    Confirms Concept #4's central claim: top-p's EFFECTIVE cutoff count
    varies with the distribution's confidence, while top-k's is fixed by
    definition -- verified by comparing the nucleus size on a CONFIDENT
    (peaked) distribution vs. an UNCERTAIN (flat) distribution.
    """
    rng = np.random.default_rng(seed)

    # Confident distribution: one token dominates.
    confident_logits = rng.normal(0, 0.5, vocab_size)
    confident_logits[0] = 10.0  # one massively dominant token
    _, confident_cutoff = top_p_filter(confident_logits, p)

    # Uncertain distribution: probabilities spread much more evenly.
    uncertain_logits = rng.normal(0, 0.3, vocab_size)  # no dominant token
    _, uncertain_cutoff = top_p_filter(uncertain_logits, p)

    return confident_cutoff, uncertain_cutoff


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A team serving an LLM-based coding assistant notices generation latency
# scales noticeably worse than expected as users' conversation history
# grows longer across a multi-turn session, despite the model itself
# being unchanged. Per Concept #1-#2, if their serving infrastructure
# ISN'T correctly reusing the KV cache ACROSS conversation turns (e.g. a
# naive implementation that re-runs the full forward pass over the ENTIRE
# accumulated conversation history from scratch at the start of every new
# turn, rather than extending a persisted cache from the previous turn),
# this is the EXACT O(T^2)-vs-O(T) gap Concept #2 quantifies, now
# manifesting across TURNS rather than just within a single generation
# call -- a diagnosable, architecture-level inefficiency with a specific,
# derivable fix (persist and correctly extend the KV cache across the
# full multi-turn session, not just within one generation call), rather
# than a vague "the model is slow with long context" complaint requiring
# open-ended profiling to root-cause.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Assuming higher temperature always means "better" or "more creative"
#    output without limit. Per Concept #4, temperature is a SMOOTH
#    interpolation knob with no built-in floor on coherence -- pushed too
#    high, it increasingly approaches uniform random token selection,
#    producing progressively less coherent (not more "creative" in any
#    useful sense) output; it does not, by itself, solve the long-tail
#    incoherence problem top-k/top-p directly address via truncation.
# 2. Using a fixed top-k value across wildly different tasks/contexts
#    without considering Concept #4's context-insensitivity critique.
#    A k tuned for open-ended creative writing may be far too permissive
#    (including implausible options) for a task wanting confident,
#    focused completions (e.g. code generation, factual QA) -- top-p is
#    frequently the more robust default specifically because it adapts
#    to per-step distribution shape automatically.
# 3. Believing KV caching changes WHAT the model computes/predicts in any
#    way. Per Concept #2, it is a PURE optimization -- the K, V values
#    stored and reused are mathematically IDENTICAL to what would be
#    recomputed from scratch; correctly implemented KV caching produces
#    bit-for-bit (up to floating-point summation order effects)
#    identical outputs to the naive approach, just far faster.
# 4. Conflating beam search with sampling-based methods (temperature/top-
#    k/top-p) as though they're solving the same problem. Per Concept #3
#    vs. #4, beam search addresses the LOCAL-vs-GLOBAL-optimum problem
#    (still fundamentally deterministic, still no randomness), while
#    sampling methods address the DETERMINISM/repetitiveness problem
#    (introducing controlled randomness) -- they're answers to two
#    genuinely different failure modes and are sometimes combined (e.g.
#    stochastic beam search variants) but are not interchangeable fixes
#    for the same issue.


if __name__ == "__main__":
    print("=" * 70)
    print("CONCEPT #2: KV cache eliminates O(T^2)-scaling redundant computation")
    print("=" * 70)
    for seq_len in [10, 100, 1000]:
        naive_count = count_kv_computations(seq_len, use_cache=False)
        cached_count = count_kv_computations(seq_len, use_cache=True)
        print(f"seq_len={seq_len:>5}: naive K/V computations = {naive_count:>7}, "
              f"cached = {cached_count:>5}  (speedup ~{naive_count/cached_count:.1f}x)")
    print("-> The speedup ratio should grow roughly LINEARLY with seq_len --")
    print("   confirming the O(T^2)-vs-O(T) asymptotic difference Concept #2 derives,")
    print("   not just a fixed constant-factor improvement.")

    print("\n" + "=" * 70)
    print("CONCEPT #4: top-p's cutoff SIZE adapts to distribution confidence,")
    print("unlike top-k's fixed count")
    print("=" * 70)
    confident_cutoff, uncertain_cutoff = demonstrate_top_p_adapts_to_distribution_shape()
    print(f"Top-p (p=0.9) nucleus size on a CONFIDENT (one dominant token) distribution: "
          f"{confident_cutoff} token(s)")
    print(f"Top-p (p=0.9) nucleus size on an UNCERTAIN (flat) distribution: "
          f"{uncertain_cutoff} token(s)")
    print("-> Nucleus size should be MUCH smaller for the confident distribution")
    print("   than the uncertain one -- a fixed top-k would apply the identical")
    print("   cutoff count to both cases regardless of this genuine difference")
    print("   in how spread out each distribution actually is.")
