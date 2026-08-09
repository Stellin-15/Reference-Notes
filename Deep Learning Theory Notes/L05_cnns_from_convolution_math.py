"""
WHAT: Convolution derived as a specific, deliberately-constrained linear
      operation (a fully-connected layer with weight-sharing and local
      connectivity imposed), and receptive field growth derived
      quantitatively across stacked layers.
WHY:  "CNNs use convolution to detect local patterns like edges" is true
      but skips the mechanism: convolution IS a fully-connected layer,
      just one where you've forced most weights to be permanently zero
      (local connectivity) and forced the remaining weights to be
      IDENTICAL across every spatial position (weight sharing). Seeing
      convolution as a constrained special case of the fully-connected
      layer from L01 explains exactly WHY it has vastly fewer parameters
      and WHY that specific constraint is the right inductive bias for
      images (tying directly to Classical ML Theory Notes L01's No Free
      Lunch argument).
LEVEL: Foundational -- first of this domain's architecture-specific
       lessons.

PREREQUISITE: L01 (backprop, fully-connected layers); Classical ML Theory
Notes L01 (No Free Lunch -- CNNs' inductive bias is a direct application).
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — CONVOLUTION AS A CONSTRAINED FULLY-CONNECTED LAYER (the
# central reframing this lesson is built around)
# ============================================================================
#
# A fully-connected layer mapping a flattened n-pixel image to an
# n-pixel output has an n x n weight matrix -- EVERY output pixel is a
# learned linear combination of EVERY input pixel, with its OWN
# independent set of n weights. For a modest 256x256 image (65,536
# pixels), that's 65,536^2 ≈ 4.3 BILLION weights for ONE layer -- both
# computationally infeasible and, more importantly, a terrible INDUCTIVE
# BIAS (Classical ML Theory Notes L01's No Free Lunch framing): nothing
# in this formulation encodes the fact that nearby pixels are far more
# likely to be related than distant ones, or that "detecting an edge"
# should mean the same computation regardless of WHERE in the image that
# edge appears.
#
# CONVOLUTION IS THE SAME FULLY-CONNECTED LINEAR OPERATION, WITH TWO
# ADDITIONAL CONSTRAINTS IMPOSED ON THE WEIGHT MATRIX:
#
#   1. LOCAL CONNECTIVITY: each output position is connected to only a
#      small NxN neighborhood of input positions (the "kernel size"),
#      not the entire image -- every weight connecting an output pixel
#      to an input pixel FARTHER than the kernel radius is fixed at
#      exactly zero, permanently, not learned.
#   2. WEIGHT SHARING: the SAME small set of weights (the kernel/filter)
#      is used at EVERY spatial position -- the weights connecting output
#      pixel (5,5) to its local neighborhood are IDENTICAL to the weights
#      connecting output pixel (100,100) to ITS local neighborhood.
#
# Both constraints are DELIBERATE INDUCTIVE BIAS, not incidental
# efficiency hacks: local connectivity encodes "nearby pixels are more
# related than distant ones" (true for natural images); weight sharing
# encodes "a useful local pattern -- an edge, a texture -- should be
# detected identically regardless of where it appears" (TRANSLATION
# EQUIVARIANCE). Removing either constraint (a fully-connected layer, or
# a "locally connected" layer with UNSHARED weights per position) gives
# up exactly the assumption that constraint encodes, at the direct cost
# of needing vastly more parameters/data to relearn what the constraint
# would have provided for free.

def convolution_as_matrix_multiply(x, kernel):
    """
    Builds the EXPLICIT (n_out x n_in) weight matrix that a 1D
    convolution with the given kernel is mathematically equivalent to,
    then confirms matrix-multiplying by it gives the identical result to
    a direct convolution -- making Concept #1's "convolution IS a
    constrained fully-connected layer" claim fully explicit rather than
    asserted. (1D for clarity; the exact same argument generalizes to 2D
    images with a 2D kernel and a much larger, more sparse matrix.)
    """
    n = len(x)
    k = len(kernel)
    n_out = n - k + 1  # "valid" convolution, no padding

    # Build the equivalent fully-connected weight matrix EXPLICITLY.
    W = np.zeros((n_out, n))
    for i in range(n_out):
        W[i, i:i + k] = kernel  # SAME kernel weights at every row -- weight
                                 # sharing, made explicit as identical rows
                                 # (shifted), and every entry outside the
                                 # k-wide window is hard-zero -- local
                                 # connectivity, made explicit as sparsity.
    matmul_result = W @ x

    # Direct convolution (the "normal" way to compute it, and what a
    # framework's Conv1d actually executes for speed -- the matrix-multiply
    # formulation is never used in practice due to its huge sparse-matrix
    # memory footprint, but is mathematically identical).
    direct_result = np.array([np.dot(x[i:i + k], kernel) for i in range(n_out)])

    return W, matmul_result, direct_result


# ============================================================================
# CONCEPT #2 — PARAMETER COUNT: THE DIRECT, QUANTIFIABLE PAYOFF OF THE
# TWO CONSTRAINTS
# ============================================================================
#
# Fully-connected layer, n_in -> n_out: n_in * n_out parameters (plus bias).
# Convolutional layer, kernel size k, n_out_channels output feature maps:
# k * k * n_in_channels * n_out_channels parameters (plus bias per output
# channel) -- COMPLETELY INDEPENDENT of the image's spatial dimensions
# (height, width). A 3x3 kernel with 64 input and 64 output channels has
# 3*3*64*64 = 36,864 weights, REGARDLESS of whether the image is 32x32 or
# 4096x4096 -- while a fully-connected layer's parameter count scales
# with the SQUARE of spatial resolution. This isn't a minor efficiency
# gain; it's the difference between "trainable on a laptop" and
# "physically impossible to fit in any GPU's memory" once resolution
# gets even moderately large.

def parameter_count_comparison(image_hw, kernel_size, in_channels, out_channels):
    n_pixels_per_channel = image_hw * image_hw
    fc_params = (n_pixels_per_channel * in_channels) * (n_pixels_per_channel * out_channels)
    conv_params = kernel_size * kernel_size * in_channels * out_channels
    return fc_params, conv_params


# ============================================================================
# CONCEPT #3 — RECEPTIVE FIELD: WHY STACKING CONVOLUTIONS LETS DEEP
# LAYERS "SEE" LARGE REGIONS DESPITE EACH LAYER'S SMALL KERNEL
# ============================================================================
#
# A single conv layer with kernel size k gives each output unit a
# RECEPTIVE FIELD (the region of the ORIGINAL input it depends on) of
# exactly k x k. This seems like a real limitation -- how can a network
# built entirely from small (e.g. 3x3) kernels ever "see" large-scale
# structure (a whole face, a whole object)?
#
# THE ANSWER IS RECEPTIVE FIELD GROWS WITH DEPTH, and the growth formula
# is derivable directly by induction. Let RF_l be the receptive field
# (in original-input pixels) of a unit at layer l, kernel size k_l,
# stride s_l (for pooling/strided-conv layers that downsample):
#   RF_l = RF_{l-1} + (k_l - 1) * prod_{i<l} s_i
#
# Intuition for the induction: a unit at layer l depends on a k_l x k_l
# window of layer (l-1)'s units; EACH of those layer-(l-1) units, in
# turn, already has its own RF_{l-1}-sized receptive field into the
# original input, and adjacent layer-(l-1) units' receptive fields
# OVERLAP and are OFFSET by however many original-input pixels one
# stride-1 step in layer (l-1)'s space corresponds to (the cumulative
# stride product up to that layer). Stacking L layers of 3x3 kernels
# (stride 1) grows the receptive field LINEARLY in L (RF ≈ 1 + 2L for
# stride-1 3x3 kernels stacked L times) -- so even without any pooling/
# downsampling, ~20-30 stacked 3x3 layers already reach receptive fields
# covering most of a typical input image, while using far fewer
# parameters (per Concept #2) than a single giant kernel of the
# equivalent size would.
#
# WHY STACKED SMALL KERNELS ARE PREFERRED OVER ONE LARGE KERNEL EVEN
# WHEN THE RECEPTIVE FIELD ENDS UP THE SAME SIZE: two stacked 3x3 conv
# layers have the SAME receptive field as one 5x5 layer (RF=1+2+2=5), but
# 2*(3*3*C^2)=18C^2 parameters vs 5*5*C^2=25C^2 for the single 5x5 layer
# (C = channel count) -- FEWER parameters for the identical receptive
# field, AND an extra nonlinearity (activation function) between the two
# 3x3 layers, giving the network more representational flexibility per
# parameter. This is the direct, derivable justification for the "stack
# many small kernels" design that essentially all modern CNN
# architectures (VGG onward) converged on.

def receptive_field_growth(kernel_sizes, strides):
    rf = 1
    cumulative_stride = 1
    history = [rf]
    for k, s in zip(kernel_sizes, strides):
        rf = rf + (k - 1) * cumulative_stride
        cumulative_stride *= s
        history.append(rf)
    return history


# ============================================================================
# CONCEPT #4 — TRANSLATION EQUIVARIANCE, PRECISELY DEFINED, AND WHY
# POOLING ADDS (APPROXIMATE) TRANSLATION INVARIANCE ON TOP OF IT
# ============================================================================
#
# CONVOLUTION IS TRANSLATION EQUIVARIANT, not translation invariant --
# a precise, frequently-conflated distinction:
#   EQUIVARIANT: if you shift the input by some amount, the OUTPUT shifts
#   by the SAME amount (shift-then-convolve = convolve-then-shift). This
#   follows DIRECTLY from weight sharing (Concept #1): the same kernel
#   applied to a shifted input produces the identically-shaped feature
#   detection, just at a shifted output location.
#   INVARIANT: the output does NOT change at all when the input is
#   shifted -- a fundamentally stronger and different property.
#
# Convolution alone gives you equivariance, which is exactly the right
# property for FEATURE DETECTION (an edge detector's output should track
# WHERE the edge moved to, not disappear/change identity). But for
# CLASSIFICATION (e.g. "is there a cat anywhere in this image," where you
# want the FINAL prediction to not care about the cat's exact pixel
# position), you additionally want some INVARIANCE. POOLING (max-pooling
# or average-pooling, which discards exact spatial position within each
# pooling window, keeping only a summary statistic) is what converts
# equivariance into approximate invariance -- small shifts within a
# pooling window produce an IDENTICAL pooled output (for max-pooling,
# as long as the maximal activation stays within the same window), while
# larger architectural depth (many pooling layers) builds up
# progressively stronger, though never perfect, invariance to larger
# shifts.

def demonstrate_translation_equivariance(x, kernel, shift):
    """Confirms: convolve(shift(x)) == shift(convolve(x)) -- equivariance,
    verified numerically rather than asserted."""
    def convolve_valid(signal, k):
        n_out = len(signal) - len(k) + 1
        return np.array([np.dot(signal[i:i + len(k)], k) for i in range(n_out)])

    x_shifted = np.roll(x, shift)
    conv_of_shifted = convolve_valid(x_shifted, kernel)
    conv_of_original = convolve_valid(x, kernel)
    shifted_conv_of_original = np.roll(conv_of_original, shift)
    return conv_of_shifted, shifted_conv_of_original


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A team building a manufacturing defect-detection CNN observes the model
# performs excellently on defects appearing in the CENTER of each captured
# frame but noticeably worse near the frame's EDGES, despite training data
# covering defects at all positions roughly equally. Per Concept #1's
# equivariance claim, this SHOULDN'T happen from convolution itself
# (weight sharing means the kernel treats every position identically) --
# tracing the actual cause typically reveals it's PADDING behavior: many
# "same" padding schemes zero-pad the input near the border, meaning
# edge-region output units receive a receptive field partially filled
# with artificial zeros rather than real image content, breaking true
# translation equivariance specifically near edges -- a genuine,
# identifiable architectural artifact ("boundary effects"), not a
# training-data or capacity problem, and the fix (more careful padding
# strategy, or explicitly ensuring training crops include proportionally
# more edge-region examples) is targeted at that specific, correctly-
# diagnosed mechanism rather than blindly adding more data or capacity.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Believing a bigger single kernel is strictly more powerful than
#    several stacked smaller kernels with the same total receptive field.
#    Per Concept #3, stacked small kernels typically use FEWER parameters
#    for the same receptive field AND add extra nonlinearities between
#    them -- a strictly better parameter-efficiency tradeoff in most
#    cases, which is why large single kernels (e.g. 11x11, as in early
#    AlexNet-style architectures) were largely abandoned in favor of
#    stacked 3x3s in subsequent architecture designs.
# 2. Confusing translation EQUIVARIANCE (what raw convolution provides)
#    with translation INVARIANCE (what pooling/architectural depth
#    approximately provides on top). These are different properties with
#    different implications -- a common imprecision that leads to
#    incorrect claims like "CNNs are invariant to translation," which
#    is only approximately true, and only once pooling/downsampling is
#    part of the architecture.
# 3. Assuming convolution's parameter savings come "for free" with no
#    tradeoff. The local-connectivity and weight-sharing constraints are
#    a genuine INDUCTIVE BIAS (Classical ML Theory Notes L01's No Free
#    Lunch framing) -- they're excellent for image-like data with local,
#    translation-relevant structure, but actively wrong for data with no
#    such spatial structure (e.g. arbitrarily-ordered tabular features,
#    where "nearby columns are more related" is usually false) -- using
#    convolution there imposes a harmful, not helpful, bias.
# 4. Forgetting that receptive field is computed relative to the ORIGINAL
#    input resolution, not the current layer's (possibly downsampled)
#    feature-map resolution -- a common off-by-scale error when manually
#    computing receptive field for an architecture with strided/pooling
#    layers, since the cumulative stride term (Concept #3) is easy to
#    omit or miscompute.


if __name__ == "__main__":
    print("=" * 70)
    print("CONCEPT #1: convolution IS a fully-connected layer with weights")
    print("constrained to be local and shared")
    print("=" * 70)
    rng = np.random.default_rng(0)
    x = rng.normal(size=10)
    kernel = np.array([0.5, -1.0, 0.5])  # a simple edge-detector-like kernel
    W, matmul_result, direct_result = convolution_as_matrix_multiply(x, kernel)
    print(f"Explicit weight matrix shape: {W.shape} (n_out x n_in, mostly zero)")
    print(f"Fraction of W that is exactly zero: {(W == 0).mean():.2%}")
    print(f"Result via explicit matmul:    {np.round(matmul_result, 4)}")
    print(f"Result via direct convolution: {np.round(direct_result, 4)}")
    print(f"Identical? {np.allclose(matmul_result, direct_result)}")

    print("\n" + "=" * 70)
    print("CONCEPT #2: parameter count, fully-connected vs convolutional")
    print("=" * 70)
    for hw in [32, 256, 1024]:
        fc, conv = parameter_count_comparison(hw, kernel_size=3, in_channels=64, out_channels=64)
        print(f"  {hw}x{hw} image: fully-connected = {fc:,} params, "
              f"conv (3x3, 64->64 channels) = {conv:,} params")
    print("-> Conv params stay CONSTANT across resolution; FC params explode")
    print("   quadratically with resolution -- the direct payoff of Concept #1's")
    print("   local-connectivity + weight-sharing constraints.")

    print("\n" + "=" * 70)
    print("CONCEPT #3: receptive field growth, stacked 3x3 vs one big kernel")
    print("=" * 70)
    rf_history = receptive_field_growth(kernel_sizes=[3] * 5, strides=[1] * 5)
    print(f"Receptive field after each of 5 stacked 3x3 (stride-1) layers: {rf_history}")
    two_3x3_params = 2 * (3 * 3 * 64 * 64)
    one_5x5_params = 5 * 5 * 64 * 64
    print(f"Two stacked 3x3 layers: RF={rf_history[2]}, params={two_3x3_params:,}")
    print(f"One 5x5 layer:          RF=5, params={one_5x5_params:,}")
    print(f"Same receptive field, fewer params in the stacked version? "
          f"{two_3x3_params < one_5x5_params}")

    print("\n" + "=" * 70)
    print("CONCEPT #4: translation equivariance, verified numerically")
    print("=" * 70)
    x2 = rng.normal(size=12)
    conv_of_shifted, shifted_conv_of_original = demonstrate_translation_equivariance(
        x2, kernel, shift=2)
    print(f"convolve(shift(x)):   {np.round(conv_of_shifted, 4)}")
    print(f"shift(convolve(x)):   {np.round(shifted_conv_of_original, 4)}")
    # Interior region should match exactly; only the wrap-around edge from
    # np.roll differs, which is a boundary artifact of this toy demo, not
    # a violation of equivariance itself.
    print("-> These match away from the wrap-around boundary, confirming")
    print("   equivariance: shifting the input shifts the output identically.")
