"""
WHAT: Scaled dot-product attention derived as a direct fix for RNNs'
      sequential-bottleneck and vanishing-gradient problems (L06), built
      up from a simple "soft lookup table" intuition to the full
      Query/Key/Value formulation, including WHY the scaling factor
      sqrt(d_k) is mathematically necessary, not a tuning nicety.
WHY:  "Attention lets the model focus on relevant parts of the input" is
      true but tells you nothing about the actual mechanism. This lesson
      derives attention as a weighted average over VALUES, where the
      weights come from a learned similarity between QUERIES and KEYS --
      and shows the mechanism solves L06's vanishing-gradient problem by
      construction, since every output position connects to every input
      position through exactly ONE matrix multiplication, not a T-step
      recurrent chain.
LEVEL: Foundational -- last lesson before this repo's LLM Core Theory
       Notes track, which builds the full Transformer directly on top of
       what's derived here.

PREREQUISITE: L06 (RNN vanishing gradients -- attention is presented here
explicitly as the direct architectural answer to that problem);
Classical ML Theory Notes L06 (softmax, referenced via its role in
attention weights).
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — ATTENTION AS A "SOFT" LOOKUP TABLE (the core intuition,
# before any Query/Key/Value terminology)
# ============================================================================
#
# A HARD lookup table maps a query to a value via exact key matching:
# find the key equal to the query, return its associated value. This is
# discrete and non-differentiable (can't backprop through "find the
# matching key" if match is exact equality).
#
# ATTENTION IS A DIFFERENTIABLE, SOFT VERSION: instead of finding the ONE
# exact-matching key, compute a SIMILARITY SCORE between the query and
# EVERY key, convert those scores into a probability distribution (via
# softmax -- Classical ML Theory Notes L06's multi-class generalization
# of sigmoid), and return a WEIGHTED AVERAGE of all the values, weighted
# by that similarity distribution. If one key is a much better match than
# the others, softmax naturally concentrates most of the weight there
# (approximating hard lookup); if several keys are similarly relevant,
# the output smoothly blends their values -- and because every step is
# built from differentiable operations (dot products, softmax, weighted
# sum), gradients flow through the ENTIRE mechanism cleanly, unlike a
# hard "argmax and select" lookup.

def soft_lookup_intuition(query, keys, values):
    """A minimal illustration of Concept #1: similarity via dot product,
    softmax to get weights, weighted average of values."""
    scores = keys @ query  # similarity of the query to each key
    weights = np.exp(scores - scores.max())
    weights /= weights.sum()  # softmax, done manually for transparency
    output = weights @ values
    return weights, output


# ============================================================================
# CONCEPT #2 — QUERY, KEY, VALUE: WHY THREE SEPARATE LEARNED PROJECTIONS,
# NOT ONE
# ============================================================================
#
# Full self-attention doesn't use the raw input vectors directly as
# queries/keys/values -- it LEARNS three separate linear projections of
# each input token embedding x_i:
#   q_i = x_i @ W_Q     (what this position is "looking for")
#   k_i = x_i @ W_K     (what this position "advertises" as its content,
#                         for OTHER positions to match against)
#   v_i = x_i @ W_V     (what this position actually CONTRIBUTES if
#                         attended to)
#
# WHY NOT JUST USE x_i DIRECTLY FOR ALL THREE ROLES: the query role
# ("what am I looking for") and the key role ("how do I advertise
# myself to be found") are conceptually DIFFERENT FUNCTIONS of the same
# token, and forcing them to be identical (x_i used as both query and
# key) would mean a token's similarity to itself (x_i . x_i) is always
# maximal by construction (self-dot-product is the largest possible
# value for a fixed norm, by Cauchy-Schwarz), heavily biasing every
# token to over-attend to itself regardless of whether that's actually
# useful for the task. Separate learned W_Q and W_K matrices let the
# model learn DIFFERENT representations for "what to seek" vs "what to
# offer," breaking this forced self-similarity bias, and the separate
# W_V lets the CONTENT actually retrieved differ from the content used
# for MATCHING -- e.g. a token's "matchability" (its key) might
# emphasize its part-of-speech/syntactic role, while its "contribution"
# (its value) might emphasize its full semantic content, two genuinely
# different pieces of information the same token carries.

def qkv_projections(X, W_Q, W_K, W_V):
    Q = X @ W_Q
    K = X @ W_K
    V = X @ W_V
    return Q, K, V


# ============================================================================
# CONCEPT #3 — SCALED DOT-PRODUCT ATTENTION, AND WHY THE sqrt(d_k) SCALING
# IS MATHEMATICALLY NECESSARY, NOT A TUNING CONVENIENCE
# ============================================================================
#
#   Attention(Q,K,V) = softmax( Q @ K^T / sqrt(d_k) ) @ V
#
# where d_k is the dimensionality of each query/key vector. WITHOUT the
# sqrt(d_k) division, here's the specific, derivable problem:
#
# Assume (a standard, reasonable assumption for the purposes of this
# derivation) each component of q and k is drawn independently with mean
# 0 and variance 1. The dot product q.k = sum_{i=1}^{d_k} q_i*k_i is a
# sum of d_k independent, zero-mean terms, EACH with variance
# Var(q_i*k_i) = Var(q_i)*Var(k_i) = 1 (for independent zero-mean q_i,k_i).
# By the same additivity-of-variance argument used in L03's initialization
# derivation:
#   Var(q.k) = sum_i Var(q_i*k_i) = d_k
#
# So the RAW dot product's variance GROWS LINEARLY with d_k -- for a
# typical transformer's d_k (commonly 64 per attention head), the raw
# dot products can have standard deviation ~8, meaning individual score
# values routinely land far into the tens. Feeding scores of this
# magnitude into softmax is specifically damaging: softmax's gradient
# is (for the i-th output) softmax_i*(1-softmax_i) at its peak, and this
# gradient VANISHES as the input scores become extreme (softmax
# saturates toward a near-one-hot distribution when its inputs are far
# apart in magnitude) -- exactly the same kind of vanishing-gradient
# mechanism identified for tanh/sigmoid in L03/L06, now afflicting the
# attention weights themselves. Dividing by sqrt(d_k) exactly
# counteracts the variance growth derived above:
#   Var(q.k / sqrt(d_k)) = Var(q.k) / d_k = d_k / d_k = 1
# restoring the scores to unit variance REGARDLESS of d_k, keeping
# softmax's inputs in a well-behaved range where its gradients don't
# saturate -- a precisely-derived fix for a precisely-derived problem,
# not an empirically-tuned constant.

def scaled_dot_product_attention(Q, K, V, mask=None):
    d_k = Q.shape[-1]
    scores = Q @ K.T / np.sqrt(d_k)
    if mask is not None:
        scores = np.where(mask, scores, -np.inf)  # see Concept #4
    scores_shifted = scores - scores.max(axis=-1, keepdims=True)  # numerical stability
    weights = np.exp(scores_shifted)
    weights /= weights.sum(axis=-1, keepdims=True)
    output = weights @ V
    return output, weights


def demonstrate_variance_growth_with_dk(seed=0):
    """Confirms Var(q.k) grows linearly with d_k, and that scaling by
    sqrt(d_k) restores unit variance regardless of d_k -- Concept #3's
    central claim, verified numerically."""
    rng = np.random.default_rng(seed)
    results = {}
    for d_k in [8, 32, 64, 128, 512]:
        q_samples = rng.normal(size=(5000, d_k))
        k_samples = rng.normal(size=(5000, d_k))
        raw_scores = np.sum(q_samples * k_samples, axis=1)
        scaled_scores = raw_scores / np.sqrt(d_k)
        results[d_k] = (raw_scores.var(), scaled_scores.var())
    return results


# ============================================================================
# CONCEPT #4 — WHY SELF-ATTENTION SOLVES L06'S VANISHING-GRADIENT PROBLEM
# BY CONSTRUCTION (a structural, not incidental, fix)
# ============================================================================
#
# Recall L06: in a vanilla RNN, the gradient connecting a distant early
# timestep to the final loss must pass through a PRODUCT of T
# Jacobians -- one multiplicative "hop" per intermediate timestep,
# geometrically shrinking (or exploding) with sequence length.
#
# In self-attention, the output at position i is DIRECTLY a weighted sum
# over ALL input positions' values: output_i = sum_j weights_ij * v_j.
# The gradient d(output_i)/d(v_j) is JUST weights_ij (a single
# multiplication, computed via ONE softmax + ONE matrix multiply) --
# REGARDLESS of how far apart positions i and j are in the sequence.
# There is NO T-step multiplicative chain connecting a distant position
# to another; every pair of positions is connected through exactly ONE
# hop (the attention weight matrix), independent of sequence length. This
# is precisely why Transformers (built from stacked self-attention
# layers, this repo's LLM Core Theory Notes) don't suffer the same
# vanishing-gradient-over-long-sequences problem RNNs do -- it's a
# structural, architecture-level consequence of replacing sequential
# recurrence with direct, all-pairs connectivity, not a training trick
# layered on top of an otherwise-recurrent design.
#
# THE TRADEOFF THIS BUYS AT A COST: all-pairs connectivity means
# computing attention costs O(T^2) in sequence length (every position
# attends to every other position), versus a vanilla RNN's O(T) per-
# timestep cost -- a real, well-known scaling tradeoff (quadratic
# compute/memory vs. sequence length) that motivates a significant
# amount of ongoing Transformer-efficiency research (sparse attention,
# linear attention, sliding-window attention) covered in this repo's LLM
# Core Theory Notes and LLM Quantization & Inference Notes tracks.
#
# CAUSAL MASKING: for autoregressive generation (predicting the next
# token, unable to "see" future tokens at inference time), a MASK is
# applied to the raw scores BEFORE softmax, setting scores for
# future/disallowed positions to -infinity (so exp(-infinity)=0,
# guaranteeing zero attention weight on masked positions after softmax
# normalization) -- implemented explicitly in
# scaled_dot_product_attention above via the mask parameter.

def demonstrate_uniform_gradient_path_length(seq_len, d_model=16, seed=0):
    """
    Confirms that d(output_i)/d(v_j) has the SAME structural form (a
    single attention weight, no chain of intermediate Jacobians)
    regardless of |i-j| -- contrasted with L06's vanilla-RNN result,
    where gradient magnitude explicitly depended on |i-j| via a product
    of that many Jacobians.
    """
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(seq_len, d_model))
    W_Q = rng.normal(0, 0.1, size=(d_model, d_model))
    W_K = rng.normal(0, 0.1, size=(d_model, d_model))
    W_V = rng.normal(0, 0.1, size=(d_model, d_model))
    Q, K, V = qkv_projections(X, W_Q, W_K, W_V)
    _, weights = scaled_dot_product_attention(Q, K, V)
    # d(output_0)/d(v_j) = weights[0, j] -- exactly one number, for EVERY
    # j, whether j is adjacent to position 0 or at the far end of the
    # sequence. No "distance penalty" built into the gradient PATH LENGTH
    # itself (though the LEARNED weight value can, of course, still be
    # small if position j is deemed irrelevant -- that's a content-based
    # choice, not a structural distance-decay).
    return weights[0]  # attention weights from position 0 to every position


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A team building a document-QA system compares a Transformer-based
# encoder against an LSTM-based encoder for extracting an answer from a
# 2,000-token document, and finds the Transformer noticeably better at
# questions requiring linking information from the very start and very
# end of the document, while the LSTM is competitive on questions
# answerable from local, nearby context alone. This is a direct,
# predictable consequence of Concept #4 -- LSTM's forget-gate mitigation
# (L06) reduces but does not eliminate the sequential-distance-dependent
# gradient/information decay across 2,000 steps, while self-attention's
# single-hop connectivity has no such distance dependence at all. The
# tradeoff the team must also weigh (not free per Concept #4's O(T^2)
# note): the Transformer's attention computation and memory cost scale
# quadratically with the 2,000-token document length, a real
# infrastructure cost the LSTM's linear-in-T cost doesn't carry --
# informing this repo's LLM Quantization & Inference Notes coverage of
# techniques (sparse/windowed attention, KV-cache management) built
# specifically to manage this tradeoff at longer context lengths.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Omitting the sqrt(d_k) scaling factor, treating it as a minor detail
#    safe to skip in a from-scratch implementation. Per Concept #3, this
#    specifically causes softmax saturation and vanishing GRADIENT
#    (not just an accuracy issue) for realistic d_k values -- a real,
#    diagnosable training-instability bug, not a cosmetic omission.
# 2. Using the SAME projection (or no projection at all -- raw token
#    embeddings) for queries and keys. Per Concept #2, this introduces a
#    structural self-similarity bias (Cauchy-Schwarz guarantees maximal
#    self-dot-product) that separate learned W_Q/W_K matrices are
#    specifically designed to avoid.
# 3. Applying the causal mask AFTER softmax (e.g. by zeroing out weights
#    post-hoc) instead of before, as -infinity added to the scores. Post-
#    hoc zeroing breaks the softmax normalization (the remaining weights
#    no longer sum to 1, and worse, masked positions' original nonzero
#    gradient contributions can leak through in a naive backward-pass
#    implementation) -- masking must happen on the SCORES, before softmax,
#    exactly as scaled_dot_product_attention implements it.
# 4. Believing self-attention has literally NO notion of position/order
#    (since, as Concept #4 shows, every pair of positions connects
#    identically via one hop, regardless of distance). This is true of
#    the raw attention mechanism itself, which is why Transformers
#    separately ADD explicit positional encoding to the input embeddings
#    before attention is applied at all (covered in depth in this repo's
#    LLM Core Theory Notes) -- without it, a Transformer literally cannot
#    distinguish "the cat sat on the mat" from "the mat sat on the cat"
#    from token identity and attention weights alone, since attention's
#    weighted-sum-over-values operation is itself permutation-invariant.


if __name__ == "__main__":
    print("=" * 70)
    print("CONCEPT #1: soft lookup -- attention weights concentrate on the")
    print("best-matching key, but blend smoothly when matches are close")
    print("=" * 70)
    rng = np.random.default_rng(0)
    keys = np.array([[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]])  # key 0 and key 2 are similar
    values = np.array([[10.0], [20.0], [15.0]])
    query_close_to_key0 = np.array([1.0, 0.0])
    weights, output = soft_lookup_intuition(query_close_to_key0, keys, values)
    print(f"Query closely matches key 0 and (less) key 2:")
    print(f"  Attention weights: {np.round(weights, 4)}  (should favor keys 0 and 2)")
    print(f"  Output (weighted avg of values): {output[0]:.4f}")

    print("\n" + "=" * 70)
    print("CONCEPT #3: dot-product variance grows with d_k; sqrt(d_k) fixes it")
    print("=" * 70)
    results = demonstrate_variance_growth_with_dk()
    print(f"{'d_k':>6} {'raw var':>10} {'scaled var':>12}")
    for d_k, (raw_var, scaled_var) in results.items():
        print(f"{d_k:>6} {raw_var:>10.2f} {scaled_var:>12.4f}")
    print("-> Raw variance should track d_k almost exactly (as derived);")
    print("   scaled variance should stay near 1.0 regardless of d_k.")

    print("\n" + "=" * 70)
    print("CONCEPT #4: attention weight from position 0 has no distance decay")
    print("=" * 70)
    weights_from_0 = demonstrate_uniform_gradient_path_length(seq_len=50)
    print(f"Attention weight, position 0 -> position 1 (adjacent):  {weights_from_0[1]:.5f}")
    print(f"Attention weight, position 0 -> position 25 (mid-seq):  {weights_from_0[25]:.5f}")
    print(f"Attention weight, position 0 -> position 49 (far end):  {weights_from_0[49]:.5f}")
    print("-> With random (untrained) projections, weights are roughly comparable")
    print("   regardless of distance -- there's no architectural distance-decay")
    print("   the way a vanilla RNN's T-step Jacobian product would impose (L06).")
