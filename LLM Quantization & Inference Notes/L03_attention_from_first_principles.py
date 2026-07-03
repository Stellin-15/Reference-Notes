# ============================================================
# L03: Attention Mechanism — Derived From First Principles
# ============================================================
# WHAT: How scaled dot-product attention and multi-head attention actually
#       work, derived step by step (not just the formula), plus positional
#       encoding — the mechanism that makes a transformer a transformer.
# WHY: You are about to build a full transformer from scratch in Phase 2.
#      You cannot design a quantization-aware or hardware-aware attention
#      kernel later (Phase 5/6) without understanding exactly which
#      tensors flow through attention, in what shapes, and why the
#      softmax step in particular is numerically delicate.
# LEVEL: Foundation (Phase 1 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
Attention answers the question: "for this token, how much should I weigh
information from every other token?" Mechanically:
  1. Project each token into a Query (Q), Key (K), and Value (V) vector.
  2. Compute similarity between a token's Query and every token's Key
     (a dot product) — this gives raw "attention scores."
  3. Scale the scores by 1/sqrt(d_k) — without this, scores grow with
     dimension size and push softmax into a near-one-hot, near-zero-
     gradient regime (this scaling constant is not arbitrary; it's the
     variance-stabilizing factor for a dot product of d_k iid terms).
  4. Softmax the scores into a probability distribution (they sum to 1).
  5. Use these probabilities as weights over the Value vectors — the
     output is a weighted average of every token's Value, weighted by
     how relevant that token's Key was to this token's Query.

Multi-head attention runs this whole process H times in parallel with
SMALLER Q/K/V dimensions each (d_model/H), then concatenates the results.
This lets different heads specialize in different types of relationships
(e.g. one head tracks syntactic dependency, another tracks coreference)
rather than forcing one attention pattern to capture everything.

Positional encoding exists because attention itself is permutation-
invariant — swap two tokens' positions and, without positional info, the
attention computation gives identical results. Positional encodings
(sinusoidal, or learned, or rotary/RoPE) inject order information.

PRODUCTION/RESEARCH USE CASE:
FlashAttention (which you'll study in Phase 6) is fundamentally a
memory-access reordering of EXACTLY this computation — it doesn't change
the math at all, it changes the order operations happen in and what's
kept in fast GPU SRAM vs slow HBM, specifically to avoid materializing
the full (seq_len x seq_len) attention score matrix. You cannot appreciate
what FlashAttention actually saves you without having the naive
implementation's memory profile in your head first.

COMMON MISTAKES:
- Forgetting the 1/sqrt(d_k) scaling — training becomes unstable as
  d_k grows, a mistake that's easy to make when hand-rolling attention.
- Confusing "attention weights" (the softmax output, meant to be
  interpreted, sum to 1) with "attention logits" (the raw scaled dot
  products, unbounded) — this distinction matters when debugging or
  when implementing attention masking (masking must happen on LOGITS,
  before softmax, using -inf, not on the post-softmax weights).
- Implementing causal masking incorrectly (e.g. masking after softmax
  instead of before) — this leaks future-token information into past
  tokens' attention distributions, a subtle bug that still "trains" but
  produces a broken autoregressive model.
"""

import math


# ------------------------------------------------------------------
# 1. Minimal pure-Python scaled dot-product attention (single head)
#    — no PyTorch, so every step is visible.
# ------------------------------------------------------------------
def matmul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    rows_a, cols_a = len(a), len(a[0])
    rows_b, cols_b = len(b), len(b[0])
    assert cols_a == rows_b, "inner dimensions must match"
    result = [[0.0] * cols_b for _ in range(rows_a)]
    for i in range(rows_a):
        for j in range(cols_b):
            result[i][j] = sum(a[i][k] * b[k][j] for k in range(cols_a))
    return result


def transpose(m: list[list[float]]) -> list[list[float]]:
    return [list(row) for row in zip(*m)]


def softmax_row(row: list[float]) -> list[float]:
    # Subtracting the max before exponentiating is NOT optional in real
    # code — it's the standard numerically-stable softmax. exp(large
    # number) overflows a float; exp(number - max) never exceeds exp(0)=1.
    m = max(row)
    exps = [math.exp(x - m) for x in row]
    total = sum(exps)
    return [e / total for e in exps]


def scaled_dot_product_attention(
    Q: list[list[float]],   # (seq_len, d_k)
    K: list[list[float]],   # (seq_len, d_k)
    V: list[list[float]],   # (seq_len, d_v)
    causal: bool = False,
) -> list[list[float]]:
    d_k = len(Q[0])
    scale = 1.0 / math.sqrt(d_k)

    # Step 1: raw similarity scores — Q @ K^T, shape (seq_len, seq_len).
    # This is THE quadratic-in-sequence-length tensor that FlashAttention
    # (Phase 6) is specifically designed to avoid ever fully materializing.
    scores = matmul(Q, transpose(K))
    scores = [[s * scale for s in row] for row in scores]

    # Step 2: causal masking — a token may only attend to itself and
    # earlier tokens. Masking happens HERE, on logits, using -infinity,
    # so that after softmax the masked positions become exactly 0.
    if causal:
        seq_len = len(scores)
        for i in range(seq_len):
            for j in range(i + 1, seq_len):
                scores[i][j] = float("-inf")

    # Step 3: softmax each row independently — each token's distribution
    # over "how much to attend to every other token" sums to 1.
    weights = [softmax_row(row) for row in scores]

    # Step 4: weighted sum of Values — the actual attention OUTPUT.
    output = matmul(weights, V)
    return output


# ------------------------------------------------------------------
# 2. Multi-head attention — split, attend per-head, concatenate
# ------------------------------------------------------------------
def split_heads(x: list[list[float]], num_heads: int) -> list[list[list[float]]]:
    """Splits the last dimension into num_heads equal chunks per token."""
    d_model = len(x[0])
    d_head = d_model // num_heads
    heads = []
    for h in range(num_heads):
        head = [row[h * d_head:(h + 1) * d_head] for row in x]
        heads.append(head)
    return heads


def concat_heads(heads: list[list[list[float]]]) -> list[list[float]]:
    seq_len = len(heads[0])
    return [
        [val for head in heads for val in head[t]]
        for t in range(seq_len)
    ]


def multi_head_attention(
    Q: list[list[float]], K: list[list[float]], V: list[list[float]],
    num_heads: int, causal: bool = False,
) -> list[list[float]]:
    # In a real implementation, Q/K/V would each first pass through their
    # OWN learned linear projection (W_q, W_k, W_v) before splitting into
    # heads — omitted here to keep the attention mechanism itself the
    # focus; L04 builds the full transformer block including projections.
    q_heads = split_heads(Q, num_heads)
    k_heads = split_heads(K, num_heads)
    v_heads = split_heads(V, num_heads)

    # Each head attends INDEPENDENTLY — this is what lets different heads
    # specialize; there is no cross-head interaction until concatenation.
    outputs = [
        scaled_dot_product_attention(q, k, v, causal=causal)
        for q, k, v in zip(q_heads, k_heads, v_heads)
    ]
    return concat_heads(outputs)


# ------------------------------------------------------------------
# 3. Positional encoding — sinusoidal (the original Transformer's choice)
# ------------------------------------------------------------------
def sinusoidal_positional_encoding(seq_len: int, d_model: int) -> list[list[float]]:
    """
    PE(pos, 2i)   = sin(pos / 10000^(2i/d_model))
    PE(pos, 2i+1) = cos(pos / 10000^(2i/d_model))

    Different frequency sinusoids per dimension pair let the model learn
    to attend by RELATIVE position too — sin/cos of a sum can be expressed
    as a linear combination of sin/cos of the parts, so relative offsets
    are, in principle, linearly recoverable from these encodings. Modern
    LLMs mostly use RoPE (Rotary Position Embedding) instead, which
    applies a position-dependent ROTATION to Q/K vectors rather than
    adding a fixed vector — covered when building the real transformer
    in Phase 2, since RoPE is what you'll actually implement there.
    """
    pe = [[0.0] * d_model for _ in range(seq_len)]
    for pos in range(seq_len):
        for i in range(0, d_model, 2):
            angle = pos / (10000 ** (i / d_model))
            pe[pos][i] = math.sin(angle)
            if i + 1 < d_model:
                pe[pos][i + 1] = math.cos(angle)
    return pe


if __name__ == "__main__":
    # A toy 4-token sequence, d_model=8, 2 heads (d_head=4)
    seq_len, d_model, num_heads = 4, 8, 2
    Q = [[float((i + j) % 3) / 3 for j in range(d_model)] for i in range(seq_len)]
    K = [[float((i * j) % 4) / 4 for j in range(d_model)] for i in range(seq_len)]
    V = [[float((i - j) % 5) / 5 for j in range(d_model)] for i in range(seq_len)]

    out = multi_head_attention(Q, K, V, num_heads=num_heads, causal=True)
    for i, row in enumerate(out):
        print(f"token {i} output: {[round(v, 3) for v in row]}")

    pe = sinusoidal_positional_encoding(seq_len, d_model)
    print("\nPositional encoding for token 0:", [round(v, 3) for v in pe[0]])
    print("Positional encoding for token 1:", [round(v, 3) for v in pe[1]])

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
When you profile a real transformer's inference in Phase 6, you'll see
that the `scores = Q @ K^T` step above materializes an O(seq_len^2)
tensor — for a 32K-context model, that's a genuinely large intermediate
tensor written to and read back from GPU HBM. FlashAttention's entire
contribution is computing the mathematically IDENTICAL output shown here
while never writing that full matrix to slow memory, instead processing
it in small tiles that fit in fast on-chip SRAM — a systems optimization
with zero change to the actual attention formula you just implemented.
"""
