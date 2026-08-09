"""
WHAT: Sinusoidal absolute positional encoding derived from the specific
      properties it needs to satisfy, then Rotary Position Embeddings
      (RoPE) and ALiBi derived as answers to absolute encoding's real
      limitations -- extrapolation to longer sequences than seen in
      training, and directly encoding RELATIVE (not just absolute)
      position.
WHY:  "Transformers add positional encoding because attention is
      permutation-invariant" (Deep Learning Theory Notes L07) explains
      WHY positional encoding must exist, but not why the sinusoidal
      formula looks the way it does, or why virtually every modern LLM
      has moved to RoPE instead. This lesson derives the actual math
      behind all three, and the specific problem each later scheme fixes
      in its predecessor.
LEVEL: Foundational.

PREREQUISITE: L02 (Transformer architecture); Deep Learning Theory Notes
L07 (attention's permutation-invariance, Concept #4's masking, and the
sqrt(d_k) variance derivation -- the same kind of derivation style
recurs here).
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — WHAT POSITIONAL ENCODING MUST PROVIDE, DERIVED FROM
# ATTENTION'S PERMUTATION-INVARIANCE GAP
# ============================================================================
#
# Deep Learning Theory Notes L07 established that self-attention's
# weighted-sum-over-values operation is PERMUTATION-INVARIANT: shuffling
# the input sequence's order produces the same set of outputs, just
# reordered identically -- there is NOTHING in raw attention that lets
# the model distinguish "the cat sat" from "sat the cat" using token
# identity and attention weights alone.
#
# Positional encoding must inject INTO each token's embedding some signal
# that lets the model recover (or at least usefully exploit) ordering
# information. This constrains the DESIGN requirements for any valid
# scheme:
#   1. Each position needs a UNIQUE encoding (so the model CAN
#      distinguish position 5 from position 50).
#   2. The encoding should let the model easily learn RELATIVE
#      relationships (e.g. "position j is 3 tokens after position i")
#      via some SIMPLE, learnable function of the two positions'
#      encodings -- not require the model to somehow infer relative
#      distance from two arbitrary, unrelated absolute-position vectors.
#   3. Ideally, the scheme should generalize to sequence lengths LONGER
#      than any seen during training (a real, practical requirement --
#      you can't retrain a model every time a user submits a longer
#      prompt than any training example had).

# ============================================================================
# CONCEPT #2 — SINUSOIDAL ABSOLUTE POSITIONAL ENCODING: DERIVED FROM
# WANTING A CONSTANT LINEAR TRANSFORMATION TO EXPRESS RELATIVE OFFSETS
# ============================================================================
#
# The original Transformer paper's encoding, added directly to each
# token's embedding before the first layer:
#   PE(pos, 2i)   = sin(pos / 10000^(2i/d_model))
#   PE(pos, 2i+1) = cos(pos / 10000^(2i/d_model))
# for position `pos` and dimension index `i` (alternating sin/cos across
# the d_model dimensions).
#
# WHY SINE AND COSINE SPECIFICALLY (not, say, just using `pos` directly,
# or a learned embedding per position): the key trigonometric identity
# this design exploits is the ANGLE-ADDITION FORMULA:
#   sin(a+b) = sin(a)cos(b) + cos(a)sin(b)
#   cos(a+b) = cos(a)cos(b) - sin(a)sin(b)
# This means PE(pos+k) -- the encoding at a position OFFSET by k from
# pos -- can be expressed as a LINEAR FUNCTION (a fixed rotation matrix,
# not a complicated new formula) of PE(pos), for ANY fixed offset k. This
# directly satisfies Concept #1's requirement #2: relative position (an
# offset k) is expressible as a SIMPLE LINEAR TRANSFORMATION, something a
# neural network's linear layers can learn to exploit far more easily
# than an arbitrary, unstructured relationship between two absolute-
# position vectors would allow.
#
# WHY THE GEOMETRICALLY-SPACED FREQUENCIES (the 10000^(2i/d_model)
# denominator, varying across dimensions i): each dimension pair (2i,
# 2i+1) uses a DIFFERENT frequency, spanning from very high frequency
# (i=0, wavelength ~2*pi, distinguishes ADJACENT positions sharply) to
# very low frequency (i=d_model/2, wavelength ~10000*2*pi, distinguishes
# only very DISTANT positions, changing slowly across nearby ones) --
# together, this range of frequencies lets the encoding represent BOTH
# fine-grained local position differences AND coarse long-range position
# differences simultaneously, across the model's full embedding
# dimensionality, similar in spirit to how a Fourier series represents a
# complex signal as a sum of components at many different frequencies.

def sinusoidal_positional_encoding(seq_len, d_model):
    positions = np.arange(seq_len)[:, None]
    dims = np.arange(d_model)[None, :]
    angle_rates = 1.0 / (10000 ** (2 * (dims // 2) / d_model))
    angles = positions * angle_rates
    pe = np.zeros((seq_len, d_model))
    pe[:, 0::2] = np.sin(angles[:, 0::2])
    pe[:, 1::2] = np.cos(angles[:, 1::2])
    return pe


def verify_relative_offset_is_linear(seq_len=50, d_model=16, offset=5):
    """
    Confirms Concept #2's central claim: PE(pos+offset) is EXACTLY a
    fixed linear transformation of PE(pos), for a CONSTANT offset,
    regardless of which pos you start from -- verified by fitting one
    linear map from many (PE(pos), PE(pos+offset)) pairs and checking it
    generalizes to held-out positions.
    """
    pe = sinusoidal_positional_encoding(seq_len, d_model)
    train_end = seq_len - offset - 5  # leave the last 5+offset positions held out
    X = pe[:train_end]                        # PE(pos) for pos = 0..train_end-1
    Y = pe[offset:train_end + offset]          # PE(pos+offset) for the SAME positions
    # Fit the linear map M such that Y ≈ X @ M (least squares).
    M, *_ = np.linalg.lstsq(X, Y, rcond=None)

    # Test on a HELD-OUT position range never used to fit M.
    X_test = pe[train_end:seq_len - offset]
    Y_test = pe[train_end + offset:seq_len]
    Y_pred = X_test @ M
    return np.max(np.abs(Y_pred - Y_test))


# ============================================================================
# CONCEPT #3 — WHY MODERN LLMS MOVED TO ROTARY POSITION EMBEDDINGS (RoPE)
# ============================================================================
#
# Sinusoidal encoding ADDS a position vector to the token embedding once,
# before the first layer -- position information then has to survive and
# remain USABLE through every subsequent layer's transformations, mixed
# together with content information in the same vector, with no
# guarantee any specific later layer can still cleanly recover relative-
# position information from it.
#
# RoPE takes a fundamentally different approach: instead of ADDING a
# position signal to the embedding, it ROTATES the query and key vectors
# (Deep Learning Theory Notes L07's Q, K) by an angle PROPORTIONAL TO
# THEIR POSITION, applied FRESH at EVERY attention layer (not just once
# at the input):
#   q_rotated(pos) = R(pos*theta) @ q          (a rotation matrix, applied
#                                                 per 2D subspace pair of
#                                                 dimensions, at an angle
#                                                 that grows with pos)
#
# THE KEY PROPERTY THIS BUYS (the actual reason RoPE is preferred, not
# merely "a different but equally valid way to add position"): the dot
# product between a rotated query at position m and a rotated key at
# position n depends ONLY on their RELATIVE offset (m-n), not on their
# absolute positions individually:
#   (R(m*theta)@q) . (R(n*theta)@k) = q . R((n-m)*theta) @ k
#   (a direct consequence of rotation matrices' composition property:
#   R(a)^T @ R(b) = R(b-a))
# This means the ATTENTION SCORE ITSELF -- computed directly inside every
# layer, not just the input embedding -- automatically and exactly
# encodes RELATIVE position, with NO dependence on absolute position at
# all. This is a stronger, more directly USEFUL property than sinusoidal
# encoding's "relative offset is expressible as SOME linear map" (Concept
# #2) -- RoPE makes relative position the ONLY thing the dot product can
# depend on, baked directly into every attention computation at every
# layer, rather than a recoverable-in-principle signal added once at the
# start that must survive many layers of transformation intact.

def rope_rotation_matrix_2d(pos, theta):
    """A single 2D rotation, one of the (d_model/2) rotation subspaces
    RoPE applies -- real RoPE applies a DIFFERENT theta per dimension
    pair (analogous to sinusoidal encoding's varying frequencies,
    Concept #2), rotating each 2D pair of dimensions by pos*theta_i."""
    angle = pos * theta
    return np.array([[np.cos(angle), -np.sin(angle)],
                      [np.sin(angle), np.cos(angle)]])


def verify_rope_dot_product_depends_only_on_relative_offset(theta=0.1, d=2):
    """
    Confirms Concept #3's central claim: the dot product of two
    RoPE-rotated vectors depends ONLY on (n-m), the relative offset --
    verified by checking that DIFFERENT absolute position PAIRS with the
    SAME relative offset produce IDENTICAL dot products.
    """
    rng = np.random.default_rng(0)
    q, k = rng.normal(size=d), rng.normal(size=d)

    def rotated_dot(m, n):
        q_rot = rope_rotation_matrix_2d(m, theta) @ q
        k_rot = rope_rotation_matrix_2d(n, theta) @ k
        return q_rot @ k_rot

    # Three different (m, n) pairs, all sharing the SAME relative offset (n-m=7).
    pairs = [(0, 7), (10, 17), (100, 107)]
    dot_products = [rotated_dot(m, n) for m, n in pairs]
    return pairs, dot_products


# ============================================================================
# CONCEPT #4 — ALiBi: AN EVEN SIMPLER APPROACH, TRADING EXPRESSIVITY FOR
# EXTRAPOLATION ROBUSTNESS
# ============================================================================
#
# Both sinusoidal encoding and RoPE encode position via a signal
# eventually multiplied into Q/K representations. ALiBi (Attention with
# Linear Biases) takes a much more direct approach: don't touch Q/K at
# all -- instead, SUBTRACT a PENALTY directly from the raw attention
# SCORES, proportional to the distance between the two positions:
#   score(i,j) = (q_i . k_j) - m * |i - j|
# where m is a fixed (not learned), head-specific slope. Nearby positions
# get a SMALL penalty (barely discouraged from attending to each other);
# distant positions get a LARGE penalty (softmax will assign them a much
# smaller weight, all else equal) -- directly, explicitly building in a
# "prefer local attention, allow long-range attention only when content
# strongly justifies overcoming the distance penalty" bias.
#
# WHY THIS SPECIFICALLY IMPROVES EXTRAPOLATION TO LONGER SEQUENCES THAN
# SEEN IN TRAINING (a genuine, documented weakness of both sinusoidal
# encoding and, to a lesser but real extent, RoPE): sinusoidal encoding's
# fixed frequency range is calibrated (implicitly, through training) to
# the sequence lengths actually seen during training -- extrapolating to
# much longer sequences means evaluating the sin/cos functions at
# positions/angles the model's learned weights never had reason to
# handle well, and RoPE's rotation-based scores, while more relative-
# position-native than sinusoidal encoding, still show measurable
# degradation well beyond training-length sequences in practice. ALiBi's
# penalty term is a SIMPLE, MONOTONIC, UNLEARNED function of |i-j| that
# behaves predictably and continues to make sense (very distant positions
# get heavily penalized, nearby ones lightly) for ANY sequence length,
# including lengths far beyond anything seen in training, without relying
# on any learned parameter needing to generalize outside its training
# distribution.

def alibi_bias(seq_len, slope):
    positions = np.arange(seq_len)
    distance = np.abs(positions[:, None] - positions[None, :])
    return -slope * distance  # subtracted directly from raw attention scores


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A team deploying a document-summarization LLM finds that summarization
# quality degrades noticeably on documents 3-4x longer than the model's
# training context length, despite the model's architecture supporting
# arbitrarily long input in principle (no hard sequence-length limit
# baked into the attention mechanism itself). Per Concept #3-#4, this is
# a well-documented, EXPECTED consequence of the model's positional
# encoding scheme not being explicitly designed/trained for robust
# extrapolation -- diagnosing WHICH encoding scheme the model uses
# (checking whether it's sinusoidal, RoPE, or ALiBi) directly predicts
# how severely this degradation should be expected: sinusoidal encoding
# typically shows the sharpest degradation beyond training length, RoPE
# (especially with certain scaling/interpolation techniques applied at
# inference time, an active area of ongoing research) shows more moderate
# degradation, and ALiBi is specifically documented to extrapolate most
# robustly among the three. The correctly-targeted response, given a
# fixed pretrained model, is applying a position-interpolation technique
# matched to that model's SPECIFIC encoding scheme (different techniques
# exist for RoPE vs. sinusoidal) -- not assuming a generic "just increase
# context window" fix works identically regardless of which positional
# encoding the model actually uses internally.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Assuming positional encoding is a minor implementation detail that
#    "just tells the model where each token is," with no further
#    consequence. Per Concept #4's use case, the SPECIFIC scheme chosen
#    has large, measurable, real-world effects on long-context behavior
#    -- a genuinely consequential architectural decision, not an
#    interchangeable convention.
# 2. Believing RoPE (or any scheme) "solves" length extrapolation
#    entirely. Per Concept #4, RoPE improves on sinusoidal encoding's
#    relative-position handling but still shows real degradation well
#    beyond training length in practice -- ALiBi's simpler, unlearned
#    penalty function is specifically documented to extrapolate further,
#    a genuine, still-debated tradeoff among the three approaches, not a
#    settled hierarchy where one scheme dominates in every respect.
# 3. Conflating "positional encoding provides absolute position" with
#    "positional encoding provides relative position" as though they were
#    the same guarantee. Per Concept #2 vs. #3, sinusoidal encoding
#    provides absolute position directly, with relative-position
#    information only recoverable via a learnable linear transformation
#    (a weaker, indirect guarantee); RoPE bakes RELATIVE position directly
#    into the attention score computation itself, a structurally stronger
#    and more direct property.
# 4. Assuming ALiBi's fixed, unlearned distance penalty means the model
#    literally cannot attend to distant tokens when it matters. The
#    penalty SHIFTS the softmax distribution toward local attention by
#    default, but strong CONTENT-based similarity (a large q.k dot
#    product) can still outweigh a substantial distance penalty when the
#    content genuinely warrants long-range attention -- it's a learned-
#    content-vs-fixed-distance tradeoff in the softmax, not an absolute
#    hard cutoff on attention range.


if __name__ == "__main__":
    print("=" * 70)
    print("CONCEPT #2: relative offset IS expressible as a fixed linear map")
    print("of sinusoidal encoding, generalizing to held-out positions")
    print("=" * 70)
    max_error = verify_relative_offset_is_linear(seq_len=50, d_model=16, offset=5)
    print(f"Max error, applying a linear map (fit on positions 0-39) to predict")
    print(f"PE(pos+5) from PE(pos) on HELD-OUT positions 45-49: {max_error:.6f}")
    print("-> Should be extremely small (near machine precision), confirming a")
    print("   SINGLE fixed linear transformation captures offset-by-5 for ANY")
    print("   starting position, not just the ones used to fit it.")

    print("\n" + "=" * 70)
    print("CONCEPT #3: RoPE's rotated dot product depends only on relative offset")
    print("=" * 70)
    pairs, dot_products = verify_rope_dot_product_depends_only_on_relative_offset()
    for (m, n), dp in zip(pairs, dot_products):
        print(f"  positions (m={m:>3}, n={n:>3}), offset={n-m}: dot product = {dp:.6f}")
    print(f"All three (very different absolute positions, same offset=7) match? "
          f"{np.allclose(dot_products, dot_products[0])}")

    print("\n" + "=" * 70)
    print("CONCEPT #4: ALiBi's penalty grows linearly, unlearned, with distance")
    print("=" * 70)
    bias = alibi_bias(seq_len=8, slope=0.5)
    print("ALiBi bias matrix (row=query position, col=key position):")
    print(np.round(bias, 2))
    print("-> Diagonal is 0 (no penalty attending to self); penalty grows")
    print("   linearly and symmetrically with |i-j|, by construction, for")
    print("   ANY sequence length -- no learned parameter needs to generalize")
    print("   beyond its training distribution the way sinusoidal/RoPE's")
    print("   position-dependent computations implicitly do.")
