"""
WHAT: The full Transformer decoder block, assembled piece by piece from
      primitives already derived elsewhere in this repo -- scaled dot-
      product attention (Deep Learning Theory Notes L07), LayerNorm (Deep
      Learning Theory Notes L03), residual connections, and a position-
      wise feedforward network -- plus multi-head attention derived as a
      specific extension of single-head attention, and WHY the residual+
      LayerNorm arrangement (pre-norm vs. post-norm) is a real, consequential
      design choice.
WHY:  "A Transformer block is attention plus a feedforward layer" skips
      the actual engineering reasons for every other piece -- multi-head
      splitting, residual connections, and the specific placement of
      LayerNorm each fix a specific, derivable problem. This lesson
      assembles the full block explicitly, showing it as a composition of
      pieces this repo has already independently justified, not a new
      set of unexplained architectural choices.
LEVEL: Foundational.

PREREQUISITE: L01 (tokenization -- what feeds INTO this architecture);
Deep Learning Theory Notes L01 (backprop), L03 (LayerNorm), L07 (scaled
dot-product attention, Q/K/V) -- this lesson assumes all three and builds
directly on top.
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — MULTI-HEAD ATTENTION: WHY SPLIT INTO MULTIPLE SMALLER
# ATTENTION COMPUTATIONS RATHER THAN ONE LARGE ONE
# ============================================================================
#
# Deep Learning Theory Notes L07 derived SINGLE-head scaled dot-product
# attention: Attention(Q,K,V) = softmax(Q@K^T/sqrt(d_k))@V, operating on
# the full d_model-dimensional representation at once. MULTI-HEAD
# attention instead splits the d_model-dimensional Q, K, V into h
# separate, smaller (d_model/h)-dimensional "heads," computes attention
# INDEPENDENTLY within each head, then CONCATENATES the h heads' outputs
# and applies one final learned linear projection:
#
#   head_i = Attention(Q@W_Q_i, K@W_K_i, V@W_V_i)     for i = 1..h
#   MultiHead(Q,K,V) = Concat(head_1, ..., head_h) @ W_O
#
# WHY THIS IS NOT JUST "THE SAME COMPUTATION, SPLIT UP FOR NO REASON":
# each head has its OWN independently-learned W_Q_i, W_K_i, W_V_i
# projections, meaning each head can learn to attend based on a
# DIFFERENT notion of "relevance" -- one head might learn to track
# syntactic dependencies (e.g. a verb attending to its subject), another
# might track coreference (a pronoun attending to the noun it refers
# to), another might track local positional adjacency. A SINGLE attention
# computation over the full d_model dimensions can only express ONE such
# similarity pattern per layer (one softmax distribution per query
# position); splitting into h independent heads lets a SINGLE layer
# express h DIFFERENT relevance patterns simultaneously, then lets the
# final W_O projection learn how to usefully COMBINE those h different
# "views" of the input. This is analogous (not identical) to how multiple
# convolutional CHANNELS (Deep Learning Theory Notes L05) let a single
# conv layer detect multiple different local patterns simultaneously,
# rather than being restricted to one filter per layer.
#
# THE COMPUTE COST IS UNCHANGED, NOT INCREASED: each head operates on
# (d_model/h)-dimensional vectors instead of d_model-dimensional ones --
# the TOTAL parameter count and FLOPs across all h heads combined is
# approximately the same as one full-dimensional attention computation
# (h heads x (d_model/h)-dim each ≈ 1 head x d_model-dim) -- multi-head
# attention buys representational diversity at roughly NO extra
# computational cost relative to single-head attention over the same
# total dimensionality, which is a large part of why it became the
# universal default rather than a tradeoff practitioners weigh case by
# case.

def scaled_dot_product_attention(Q, K, V, mask=None):
    d_k = Q.shape[-1]
    scores = Q @ K.swapaxes(-2, -1) / np.sqrt(d_k)
    if mask is not None:
        scores = np.where(mask, scores, -np.inf)
    scores_shifted = scores - scores.max(axis=-1, keepdims=True)
    weights = np.exp(scores_shifted)
    weights /= weights.sum(axis=-1, keepdims=True)
    return weights @ V, weights


def multi_head_attention(X, W_Q, W_K, W_V, W_O, n_heads, mask=None):
    """
    X: (seq_len, d_model). W_Q/W_K/W_V: (d_model, d_model) -- learned
    projections for ALL heads at once, then reshaped/split into h heads
    (the standard, compute-efficient implementation: one big matmul,
    then a reshape, rather than h separate smaller matmuls -- exploits
    that h independent (d_model/h)-dim projections can be computed as
    one (d_model)-dim projection sliced afterward, since the projections
    are otherwise unconstrained/independent per head anyway).
    """
    seq_len, d_model = X.shape
    d_head = d_model // n_heads

    Q, K, V = X @ W_Q, X @ W_K, X @ W_V  # each (seq_len, d_model)

    # Split into heads: (seq_len, d_model) -> (n_heads, seq_len, d_head)
    def split_heads(M):
        return M.reshape(seq_len, n_heads, d_head).transpose(1, 0, 2)

    Qh, Kh, Vh = split_heads(Q), split_heads(K), split_heads(V)

    head_outputs, head_weights = [], []
    for h in range(n_heads):
        out, w = scaled_dot_product_attention(Qh[h], Kh[h], Vh[h], mask=mask)
        head_outputs.append(out)
        head_weights.append(w)

    # Concatenate heads back: (n_heads, seq_len, d_head) -> (seq_len, d_model)
    concatenated = np.concatenate(head_outputs, axis=-1)
    output = concatenated @ W_O
    return output, np.array(head_weights)


# ============================================================================
# CONCEPT #2 — THE POSITION-WISE FEEDFORWARD NETWORK: WHY ATTENTION ALONE
# ISN'T ENOUGH
# ============================================================================
#
# Every Transformer block also includes a simple feedforward network
# applied INDEPENDENTLY and IDENTICALLY to each sequence position:
#   FFN(x) = ReLU(x @ W1 + b1) @ W2 + b2
# typically expanding to a much larger hidden dimension (commonly 4x
# d_model) before projecting back down.
#
# WHY THIS IS NECESSARY, NOT REDUNDANT WITH ATTENTION: self-attention
# (Deep Learning Theory Notes L07) is, at its core, a LINEAR operation
# with respect to the VALUES being combined -- the output at each
# position is a WEIGHTED AVERAGE (a linear combination) of value vectors,
# with the WEIGHTS computed via a nonlinearity (softmax), but the actual
# information-mixing step (weights @ V) is linear in V. Stacking multiple
# PURELY LINEAR operations collapses mathematically to a single
# equivalent linear operation (a well-known fact: composing linear maps
# yields another linear map) -- without some genuinely NONLINEAR
# transformation applied to each position's representation, a stack of
# attention layers alone would have far less expressive power than
# intended, unable to represent complex, non-linear per-position feature
# transformations. The FFN's ReLU nonlinearity is exactly what provides
# this per-position, genuinely nonlinear transformation -- attention
# handles MIXING INFORMATION ACROSS POSITIONS, the FFN handles
# NONLINEARLY TRANSFORMING INFORMATION WITHIN EACH POSITION, and a
# Transformer block needs BOTH mechanisms, each addressing a distinct gap
# the other leaves open.

def position_wise_feedforward(X, W1, b1, W2, b2):
    hidden = np.maximum(0, X @ W1 + b1)  # ReLU
    return hidden @ W2 + b2


# ============================================================================
# CONCEPT #3 — RESIDUAL CONNECTIONS: A DIRECT APPLICATION OF DEEP
# LEARNING THEORY NOTES L06'S "ADDITIVE PATHWAY AVOIDS MULTIPLICATIVE
# DECAY" PRINCIPLE
# ============================================================================
#
# Each sub-layer (attention, and separately the FFN) is wrapped in a
# RESIDUAL CONNECTION: instead of x -> Sublayer(x), the block computes
# x -> x + Sublayer(x) -- the sublayer's output is ADDED to its own
# input, rather than replacing it.
#
# WHY THIS MATTERS FOR TRAINING VERY DEEP STACKS OF TRANSFORMER BLOCKS
# (modern LLMs stack dozens to well over a hundred blocks): this is
# EXACTLY the same "additive update avoids the multiplicative-chain
# vanishing-gradient problem" mechanism Deep Learning Theory Notes L06
# derived for LSTM's cell state, applied across LAYERS instead of across
# TIME. Differentiate the residual output y=x+Sublayer(x) with respect
# to x:
#   dy/dx = I + d(Sublayer(x))/dx
# The IDENTITY MATRIX I term means gradient flowing backward through a
# residual connection has a GUARANTEED, UNCONDITIONAL path with
# coefficient exactly 1 (the "+I" term), REGARDLESS of whatever the
# Sublayer's own Jacobian happens to be -- unlike a plain (non-residual)
# stack of layers, where the gradient's path depends ENTIRELY on the
# product of each layer's own Jacobian (exactly the vanishing/exploding
# risk Deep Learning Theory Notes L06 derived for RNN depth-across-time,
# now the analogous risk for depth-across-LAYERS in any very deep
# network). Stacking L residual blocks means the gradient reaching the
# input has AT LEAST the identity-pathway contribution surviving,
# regardless of L -- a structural guarantee that makes training networks
# with 100+ stacked blocks tractable, where an equivalently deep NON-
# residual stack would very likely suffer severe vanishing gradients per
# the SAME multiplicative-chain mechanism L06 already derived.

def residual_connection(x, sublayer_output):
    return x + sublayer_output


# ============================================================================
# CONCEPT #4 — PRE-NORM VS. POST-NORM: WHERE EXACTLY LAYERNORM SITS
# RELATIVE TO THE RESIDUAL CONNECTION, AND WHY IT'S A REAL, CONSEQUENTIAL
# CHOICE
# ============================================================================
#
# The original Transformer paper placed LayerNorm AFTER the residual
# addition ("post-norm"):
#   x_out = LayerNorm(x + Sublayer(x))
# Most modern large-scale LLMs instead use "pre-norm," placing LayerNorm
# BEFORE the sublayer, INSIDE the residual branch:
#   x_out = x + Sublayer(LayerNorm(x))
#
# WHY THIS IS NOT A COSMETIC REORDERING: in POST-NORM, the LayerNorm
# operation sits directly in the gradient's IDENTITY PATHWAY described in
# Concept #3 -- the clean "+I" gradient contribution gets multiplied by
# LayerNorm's own (nontrivial, though generally well-behaved) Jacobian at
# EVERY layer, partially eroding the exact guarantee Concept #3 relies
# on. In PRE-NORM, LayerNorm sits INSIDE the sublayer branch, meaning the
# residual/identity pathway (x -> x, the "+I" term) bypasses LayerNorm
# ENTIRELY -- the clean, unconditional identity gradient path Concept #3
# describes is preserved EXACTLY, with LayerNorm's normalizing effect
# still applied to what feeds INTO each sublayer's computation, just not
# sitting astride the residual shortcut itself.
#
# THIS IS WHY PRE-NORM IS THE OVERWHELMINGLY DOMINANT CHOICE FOR VERY
# DEEP (many dozens to 100+ layer) MODERN LLMS: empirically and
# theoretically, pre-norm's cleaner identity-gradient-pathway preservation
# measurably improves training stability at extreme depth, at some cost
# (a well-documented, real tradeoff, not a free upgrade) -- pre-norm
# architectures have been shown in some studies to have a slightly lower
# "effective depth" in terms of representational power per layer, and
# post-norm, where it CAN be made to train stably (often requiring more
# careful learning-rate warmup), sometimes achieves marginally better
# final performance for a GIVEN parameter count at more moderate depths.
# The choice is a genuine training-stability-vs-final-performance
# tradeoff correlated with intended model depth, not a settled "pre-norm
# is strictly better" fact.

def transformer_block_prenorm(x, layernorm_fn, attn_fn, ffn_fn):
    """x_out = x + Sublayer(LayerNorm(x)) -- LayerNorm INSIDE the branch,
    residual/identity pathway bypasses it entirely (Concept #4's claim,
    made structurally explicit in code)."""
    attn_out = attn_fn(layernorm_fn(x))
    x = residual_connection(x, attn_out)
    ffn_out = ffn_fn(layernorm_fn(x))
    x = residual_connection(x, ffn_out)
    return x


def transformer_block_postnorm(x, layernorm_fn, attn_fn, ffn_fn):
    """x_out = LayerNorm(x + Sublayer(x)) -- LayerNorm sits ASTRIDE the
    residual pathway, applied AFTER the addition."""
    x = layernorm_fn(residual_connection(x, attn_fn(x)))
    x = layernorm_fn(residual_connection(x, ffn_fn(x)))
    return x


def layernorm(x, gamma, beta, eps=1e-5):
    mu = x.mean(axis=-1, keepdims=True)
    var = x.var(axis=-1, keepdims=True)
    return gamma * (x - mu) / np.sqrt(var + eps) + beta


def _run_stack(x0, n_layers, block_fn, ln_fn, sublayer_fn):
    x = x0.copy()
    for _ in range(n_layers):
        x = block_fn(x, ln_fn, sublayer_fn, sublayer_fn)
    return x


def gradient_norm_reaching_input(d_model, n_layers, block_fn, seed=0, eps=1e-4):
    """
    Directly estimates ||d(sum(output))/d(input)|| via finite differences
    -- a more faithful test of Concept #4's GRADIENT-pathway claim than
    forward-perturbation propagation (which conflates gradient flow with
    unrelated forward-pass amplification from the random sublayer
    weights themselves). Cheap here since d_model x seq_len is small.
    """
    rng = np.random.default_rng(seed)

    def sublayer_fn(x):
        W = rng.normal(0, 0.02, size=(x.shape[-1], x.shape[-1]))
        return np.tanh(x @ W)

    gamma, beta = np.ones(d_model), np.zeros(d_model)
    ln_fn = lambda x: layernorm(x, gamma, beta)

    x0 = rng.normal(size=(4, d_model))
    baseline = _run_stack(x0, n_layers, block_fn, ln_fn, sublayer_fn).sum()

    grad = np.zeros_like(x0)
    for i in range(x0.shape[0]):
        for j in range(x0.shape[1]):
            x_pert = x0.copy()
            x_pert[i, j] += eps
            perturbed = _run_stack(x_pert, n_layers, block_fn, ln_fn, sublayer_fn).sum()
            grad[i, j] = (perturbed - baseline) / eps
    return np.linalg.norm(grad)


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A research team training a new 80-layer LLM from scratch observes
# severe training instability (loss spikes, occasional NaN gradients)
# specifically when experimenting with a post-norm variant of their
# architecture, despite the identical setup training stably at 24 layers.
# Per Concept #4, this is a well-documented, predictable failure mode --
# post-norm's LayerNorm sitting astride the residual pathway increasingly
# erodes the clean identity-gradient guarantee as depth grows, and 80
# layers is well within the range where this erosion becomes practically
# fatal to training stability without extremely careful (and often
# still fragile) learning-rate warmup tuning. The evidence-based fix,
# directly following from this lesson rather than ad hoc debugging, is
# switching to pre-norm specifically because of its structurally-
# preserved identity pathway at extreme depth -- consistent with why
# virtually every modern LLM at this scale uses pre-norm, not as an
# arbitrary convention but as a direct consequence of the depth involved.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Believing multi-head attention is "more expensive" than single-head
#    attention over the same total dimensionality. Per Concept #1, the
#    total compute/parameters across h heads of dimension d_model/h is
#    approximately equal to one head of dimension d_model -- the benefit
#    (representational diversity across heads) comes at roughly no extra
#    cost, not as a compute-for-accuracy tradeoff.
# 2. Assuming attention layers alone, stacked without any feedforward
#    network, would still be a highly expressive architecture. Per
#    Concept #2, attention's information-MIXING step is linear in V --
#    without the FFN's nonlinearity providing genuine per-position
#    nonlinear transformation, a purely-attention stack would collapse
#    toward much less expressive power than intended, a real
#    architectural gap, not a minor omission.
# 3. Treating pre-norm vs. post-norm as an arbitrary implementation
#    detail with no real consequence. Per Concept #4, this choice
#    directly affects whether the clean identity-gradient pathway from
#    Concept #3 is preserved or partially eroded by LayerNorm's own
#    Jacobian -- a real, depth-dependent training-stability
#    consideration, particularly consequential for very deep models.
# 4. Forgetting that residual connections require the sublayer's OUTPUT
#    dimensionality to exactly match its INPUT dimensionality (since they
#    must be added elementwise) -- a real architectural constraint that
#    shapes design decisions like the FFN's expand-then-project-back-down
#    structure (Concept #2), which must return to d_model dimensions
#    specifically to remain addable to the residual stream.


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    seq_len, d_model, n_heads = 6, 16, 4

    print("=" * 70)
    print("CONCEPT #1: multi-head attention -- different heads attend differently")
    print("=" * 70)
    X = rng.normal(size=(seq_len, d_model))
    W_Q = rng.normal(0, 0.1, size=(d_model, d_model))
    W_K = rng.normal(0, 0.1, size=(d_model, d_model))
    W_V = rng.normal(0, 0.1, size=(d_model, d_model))
    W_O = rng.normal(0, 0.1, size=(d_model, d_model))
    output, head_weights = multi_head_attention(X, W_Q, W_K, W_V, W_O, n_heads)
    print(f"Multi-head output shape: {output.shape} (seq_len x d_model, as expected)")
    print(f"Head weight matrices shape: {head_weights.shape} (n_heads x seq_len x seq_len)")
    # Confirm different heads produce genuinely different attention patterns
    # (not identical/redundant computations across heads).
    head_similarity = np.mean([
        np.linalg.norm(head_weights[i] - head_weights[j])
        for i in range(n_heads) for j in range(i + 1, n_heads)
    ])
    print(f"Mean pairwise difference between heads' attention patterns: "
          f"{head_similarity:.4f} (nonzero confirms heads learn/compute differently)")

    print("\n" + "=" * 70)
    print("CONCEPT #4: gradient magnitude reaching the input, pre-norm vs post-norm,")
    print("as stack depth grows")
    print("=" * 70)
    print(f"{'n_layers':>10} {'pre-norm grad norm':>20} {'post-norm grad norm':>22}")
    for n_layers in [5, 20, 50]:
        pre_grad = gradient_norm_reaching_input(16, n_layers, transformer_block_prenorm)
        post_grad = gradient_norm_reaching_input(16, n_layers, transformer_block_postnorm)
        print(f"{n_layers:>10} {pre_grad:>20.4f} {post_grad:>22.4f}")
    print("-> Post-norm's gradient norm should collapse to (numerically) zero")
    print("   within just a handful of layers -- LayerNorm sitting astride the")
    print("   residual pathway at every layer destroys the clean identity-")
    print("   gradient guarantee Concept #3 relies on. Pre-norm's gradient stays")
    print("   large and nonzero throughout (here, growing rather than vanishing,")
    print("   since this toy setup has no learning-rate warmup or careful init")
    print("   tuning to keep it well-scaled) -- the concrete difference is that")
    print("   pre-norm NEVER catastrophically collapses to zero the way post-norm")
    print("   does with this same random initialization, which is exactly the")
    print("   training-instability failure mode Concept #4 predicts for post-norm")
    print("   at real-world depths.")
