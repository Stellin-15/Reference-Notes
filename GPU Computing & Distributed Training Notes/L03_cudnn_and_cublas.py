# ============================================================
# L03: cuDNN and cuBLAS — Vendor-Optimized GPU Libraries
# ============================================================
# WHAT: Why you should almost never hand-write CUDA kernels for standard
#       deep learning operations — cuDNN (convolutions, RNNs, pooling,
#       normalization) and cuBLAS (matrix multiplication and other
#       linear algebra) are NVIDIA's own, extensively hardware-tuned
#       implementations, and PyTorch/TensorFlow call them under the hood.
# WHY: L02 taught you to write raw CUDA kernels. This lesson is the
#      crucial caveat: for the OPERATIONS these libraries already cover
#      (which is most of what a standard neural network needs), a
#      hand-written kernel will almost always be SLOWER than the vendor
#      library's — knowing this boundary (write custom kernels only for
#      what these libraries DON'T cover) is a real engineering judgment call.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
cuBLAS implements BLAS (Basic Linear Algebra Subprograms) operations —
matrix multiplication (GEMM — General Matrix Multiply, the single most
important operation for deep learning), vector operations, and related
linear algebra — with EXTENSIVE, hardware-generation-specific tuning
(different code paths and tiling strategies optimized for each GPU
architecture's specific register file size, cache hierarchy, and Tensor
Core generation). Writing a hand-rolled matmul kernel that matches
cuBLAS's performance requires the kind of deep, hardware-specific tuning
expertise that NVIDIA's own engineering teams specialize in — this is
NOT a "just write it carefully" problem; it's genuinely one of the
hardest performance-engineering problems in GPU computing, which is
exactly why using the vendor library instead of reimplementing it is
almost always the right call.

cuDNN implements the specific operations DEEP LEARNING needs beyond raw
matmul: convolutions (with multiple different underlying ALGORITHMS —
direct convolution, FFT-based, Winograd — cuDNN automatically or
explicitly selects the best one for a given input shape/hardware),
pooling, normalization operations (batch norm, layer norm), and RNN/LSTM
cell computations — again, extensively hardware-tuned, with NEW
optimizations added by NVIDIA for each new GPU architecture generation.

PYTORCH AND TENSORFLOW BOTH CALL THESE LIBRARIES UNDER THE HOOD — when
you call `torch.nn.Conv2d` or `tensor_a @ tensor_b`, you are NOT
executing a PyTorch-authored kernel; you're calling into cuDNN/cuBLAS
(with PyTorch providing the Python API, autograd, and orchestration
layer on top). This is WHY these frameworks achieve near-optimal GPU
performance for standard operations without their own teams needing to
replicate NVIDIA's hardware-tuning expertise — they DELEGATE the
actual heavy-lifting kernel implementation to the vendor library.

THE JUDGMENT CALL this lesson sets up for the rest of the domain: write
CUSTOM CUDA/Triton kernels (L02, and the LLM Quantization Notes L18's
Triton coverage) ONLY for operations cuDNN/cuBLAS genuinely don't cover
— a novel fused operation combining several steps that would otherwise
require multiple separate library calls (with intermediate results
written to and read back from GPU memory between each), a completely
custom operation type, or a case where FUSING several standard
operations together (avoiding the memory traffic of materializing
intermediate results) provides a real, measurable win the standard
library calls, used separately, cannot achieve.

PRODUCTION USE CASE:
A team profiling their training pipeline finds that a sequence of
(convolution -> batch norm -> ReLU), each a separate cuDNN/PyTorch
call, spends measurable time simply reading and writing the
INTERMEDIATE results between these three operations to/from GPU memory
— writing a CUSTOM FUSED kernel combining all three into one (using
Triton, as covered in LLM Quantization Notes L18, or raw CUDA) that
never materializes the intermediate results provides a real speedup —
NOT because their custom convolution beats cuDNN's (it doesn't and
isn't trying to), but because FUSION eliminates memory traffic cuDNN's
separate, individually-optimal-but-not-jointly-optimal calls cannot avoid.

COMMON MISTAKES:
- Attempting to hand-write a custom convolution or matmul kernel
  "because it might be faster," without first profiling to confirm
  cuDNN/cuBLAS is ACTUALLY the bottleneck — for the vast majority of
  standard operations, the vendor library is already close to optimal,
  and the engineering effort is better spent elsewhere.
- Not being aware that cuDNN AUTO-SELECTS different convolution
  algorithms based on input shape — a benchmark/profiling run on ONE
  input shape doesn't necessarily generalize to a DIFFERENT shape,
  since cuDNN might choose a genuinely different algorithm for it.
- Missing genuine FUSION opportunities where combining several standard
  operations into one custom kernel WOULD provide a real win (per the
  production example above) — the "just use the library" default is
  correct MOST of the time, but not universally, and profiling-driven
  fusion is a real, valid optimization technique this domain's L02/L01
  (and LLM Quantization Notes L18) skills enable.
"""

import textwrap


# ------------------------------------------------------------------
# 1. cuBLAS — the GEMM operation underlying nearly all deep learning
# ------------------------------------------------------------------
CUBLAS_NOTE = textwrap.dedent("""\
    cuBLAS's core operation, GEMM (General Matrix Multiply), computes:
        C = alpha * (A @ B) + beta * C
    This single, extensively-tuned operation underlies:
      - Every fully-connected/linear layer's forward and backward pass
      - The Q@K^T and attention-weights@V steps in attention (L03 of
        LLM Quantization & Inference Notes covers the attention math itself)
      - Convolution, when implemented via the "im2col + GEMM" technique
        (one of several algorithms cuDNN can choose between)

    When PyTorch executes `a @ b` on CUDA tensors, it calls cuBLAS's
    GEMM implementation, selecting the specific variant (different
    precision, different transpose configurations) matching your tensors'
    dtype and layout — you never see this call directly, but understanding
    it explains WHY tensor shape/dtype choices (L01's Tensor Core
    discussion) affect performance so significantly.
""")

# ------------------------------------------------------------------
# 2. cuDNN — convolution algorithm selection
# ------------------------------------------------------------------
CUDNN_ALGORITHM_SELECTION_NOTE = textwrap.dedent("""\
    import torch

    torch.backends.cudnn.benchmark = True
    # This tells cuDNN to BENCHMARK several different convolution
    # algorithms (direct, FFT-based, Winograd) for your SPECIFIC input
    # shape on the FIRST forward pass, and cache whichever one is
    # actually fastest for that shape — subsequent passes with the SAME
    # shape reuse the winning algorithm. This is why the FIRST batch
    # through a newly-shaped model is often slower than the second — the
    # benchmarking overhead happens once, then pays off on every later
    # identically-shaped batch.

    # If your input shapes VARY frequently (e.g. variable-length
    # sequences without padding to a fixed size), this benchmarking
    # overhead can happen repeatedly, sometimes making
    # torch.backends.cudnn.benchmark = False (skip benchmarking, always
    # use a reasonable default algorithm) the better choice — a real,
    # measurable tradeoff depending on your actual workload's shape variability.
""")

# ------------------------------------------------------------------
# 3. Fusion — when a custom kernel legitimately beats separate library calls
# ------------------------------------------------------------------
FUSION_EXAMPLE = textwrap.dedent("""\
    # WITHOUT fusion: 3 separate operations, each reading/writing GPU
    # memory for its full input/output — cuDNN/cuBLAS optimizes EACH
    # operation individually, but the MEMORY TRAFFIC between them (writing
    # conv's output, reading it back for batch norm, writing THAT output,
    # reading it back for ReLU) is pure overhead none of the three
    # individually-optimal library calls can eliminate on their own.
    x = conv2d(input)        # cuDNN call — writes full output to GPU memory
    x = batch_norm(x)         # cuDNN call — reads that memory, writes new output
    x = relu(x)                # a simple elementwise op — reads, writes again

    # WITH fusion (a custom Triton/CUDA kernel, per L02/LLM Quantization
    # Notes L18): all three operations happen while data is STILL in
    # fast on-chip registers/shared memory, writing the FINAL result to
    # GPU memory only ONCE — genuinely faster, not because the custom
    # kernel's convolution math beats cuDNN's, but because it AVOIDS
    # the intermediate memory round-trips entirely.
    # (Frameworks increasingly do this automatically via JIT compilation
    # — PyTorch's torch.compile, covered as a related concept, can
    # automatically fuse eligible sequences of operations without
    # requiring you to hand-write the fused kernel yourself.)
""")

TORCH_COMPILE_NOTE = textwrap.dedent("""\
    import torch

    model = MyModel().cuda()
    compiled_model = torch.compile(model)
    # torch.compile analyzes the model's computation graph and
    # AUTOMATICALLY generates fused kernels for eligible operation
    # sequences (often via Triton under the hood) — capturing much of
    # the manual-fusion benefit shown above WITHOUT requiring you to
    # hand-write custom kernels yourself, for many common patterns.
""")


if __name__ == "__main__":
    print(CUBLAS_NOTE)
    print(CUDNN_ALGORITHM_SELECTION_NOTE)
    print(FUSION_EXAMPLE)
    print(TORCH_COMPILE_NOTE)

"""
PRODUCTION CONTEXT EXAMPLE:
A team profiling a custom vision model's training loop discovers the
conv->batchnorm->relu sequence's memory traffic between operations
accounts for a genuinely measurable fraction of total step time —
trying `torch.compile` first (the lowest-effort fix) recovers most of
the available fusion benefit automatically; only for a genuinely novel
operation pattern torch.compile can't fuse effectively does the team
invest in hand-writing a custom Triton kernel, following exactly the
judgment call this lesson describes: exhaust the "let the framework/
compiler handle it" options before hand-rolling anything cuDNN/cuBLAS/
torch.compile would already handle well.
"""
