# ============================================================
# L01: GPU Computing Fundamentals — Architecture, SMs, Warps, Tensor Cores
# ============================================================
# WHAT: The GPU hardware architecture underlying ALL GPU computing —
#       Streaming Multiprocessors (SMs), warps and SIMT execution, the
#       memory hierarchy, and the distinction between general-purpose
#       CUDA cores and specialized Tensor Cores.
# WHY: This repo's LLM Quantization & Inference Notes L17-L19 covers GPU
#      memory hierarchy and CUDA/Triton specifically for LLM INFERENCE
#      kernels. This domain covers the BROADER GPU computing picture —
#      general-purpose GPU programming and, critically, MULTI-GPU
#      distributed TRAINING, which that narrower single-GPU inference
#      focus doesn't address at all.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
A GPU is organized into many STREAMING MULTIPROCESSORS (SMs) — each an
independent processing unit containing its own CUDA cores, registers,
and shared memory (this repo's LLM Quantization Notes L17 covers the
memory hierarchy in depth: HBM/VRAM, L2 cache, shared memory, registers
— that same hierarchy applies here, this lesson focuses on the
COMPUTE side rather than repeating the memory-hierarchy material).
Modern GPUs have dozens to well over a hundred SMs, each capable of
running MANY threads concurrently — this MASSIVE PARALLELISM (thousands
of threads active simultaneously across all SMs) is fundamentally what
makes GPUs so much faster than CPUs for the kind of highly-parallel,
identical-operation-across-many-data-elements workloads matrix
multiplication (the core operation of neural networks) represents.

A WARP is a group of 32 threads that execute in LOCKSTEP — SIMT (Single
Instruction, Multiple Threads) execution, meaning every thread in a warp
executes the SAME instruction at the same time (with different data).
This is why WARP DIVERGENCE (threads within a warp taking different
branches of an `if` statement) hurts performance: the hardware must
serialize the divergent paths, executing each branch with non-
participating threads masked off, effectively wasting those threads'
compute capacity during the branch they didn't take.

CUDA CORES are general-purpose parallel processing units, capable of
standard floating-point/integer arithmetic. TENSOR CORES are
SPECIALIZED hardware units (introduced with NVIDIA's Volta architecture
and refined since) designed SPECIFICALLY to accelerate the exact
operation deep learning depends on most: matrix multiply-accumulate
(specifically, computing D = A×B + C for entire small matrix tiles in a
single hardware operation, dramatically faster than doing the equivalent
work as a sequence of individual CUDA-core multiply-adds). Tensor Cores
are WHY mixed-precision training (L10) exists as a meaningful
optimization — Tensor Cores' peak throughput is dramatically higher for
FP16/BF16/lower-precision inputs than for FP32, directly incentivizing
lower-precision training specifically to exploit this specialized hardware.

PRODUCTION USE CASE:
Understanding that a specific neural network layer's matrix
multiplication can be executed on Tensor Cores (given correctly-shaped,
correctly-typed inputs) rather than falling back to general CUDA cores
is the exact reason mixed-precision training frameworks (PyTorch AMP,
L10) exist — enabling Tensor Cores isn't automatic; it requires using
compatible data types and often specific matrix dimension alignment
(dimensions that are multiples of 8, for many Tensor Core generations)
to actually engage the specialized hardware path.

COMMON MISTAKES:
- Writing GPU kernels with heavy branching based on `threadIdx` in a way
  that causes warp divergence (e.g. `if (threadIdx.x % 2 == 0)`) — this
  is covered in depth in LLM Quantization Notes L19, and the same
  general-purpose GPU programming principle applies to any custom CUDA
  kernel, not just LLM-specific ones.
- Assuming ANY matrix multiplication automatically uses Tensor Cores —
  it requires specific data types (FP16/BF16/TF32/INT8, not FP32) and
  often specific dimension alignment; a poorly-shaped or FP32 matmul
  silently falls back to slower general CUDA-core execution.
- Conflating "more CUDA cores" with "proportionally more performance"
  for deep learning workloads specifically — for matrix-multiply-heavy
  workloads, TENSOR CORE count/generation is frequently the more
  relevant spec than raw CUDA core count, a common point of confusion
  when comparing GPU models for ML purposes.
"""

import textwrap


# ------------------------------------------------------------------
# 1. The GPU hierarchy: SMs, warps, threads
# ------------------------------------------------------------------
GPU_HIERARCHY_NOTE = textwrap.dedent("""\
    GPU
     └── Streaming Multiprocessors (SMs) — dozens to 100+, each independent
          └── Warps — groups of 32 threads, executing in SIMT lockstep
               └── Threads — the smallest unit; each has its own registers

    A KERNEL LAUNCH specifies a GRID of THREAD BLOCKS, each thread block
    assigned to run on ONE SM (a block does NOT span multiple SMs). Each
    block's threads are further grouped into warps of 32 by the hardware
    scheduler — you don't explicitly manage warps yourself; understanding
    them explains WHY certain code patterns (branch divergence, memory
    access patterns) perform the way they do.
""")

# ------------------------------------------------------------------
# 2. Warp divergence, illustrated conceptually
# ------------------------------------------------------------------
WARP_DIVERGENCE_EXAMPLE = textwrap.dedent("""\
    __global__ void divergent_kernel(float* data, int n) {
        int idx = blockIdx.x * blockDim.x + threadIdx.x;
        if (idx < n) {
            if (threadIdx.x % 2 == 0) {
                data[idx] = expensive_computation_a(data[idx]);   // HALF the warp
            } else {
                data[idx] = expensive_computation_b(data[idx]);   // the OTHER half
            }
        }
    }
    // Within EVERY warp, half the threads take branch A while the other
    // half takes branch B — the hardware executes BOTH branches
    // SEQUENTIALLY for the whole warp (masking off non-participating
    // threads each time), meaning this warp's effective throughput is
    // roughly HALVED compared to a version where all 32 threads in a
    // warp took the SAME branch.

    // BETTER: restructure so branch decisions align with WARP boundaries
    // (e.g. process even/odd elements in SEPARATE kernel launches, or
    // reorganize data layout so a whole warp's threads share a branch
    // outcome) — eliminates the divergence penalty entirely.
""")

# ------------------------------------------------------------------
# 3. CUDA cores vs Tensor Cores
# ------------------------------------------------------------------
CORE_TYPE_COMPARISON = {
    "CUDA Cores": "General-purpose parallel ALUs — standard floating-"
        "point/integer arithmetic, one operation per core per cycle "
        "(roughly). Used for most non-matmul computation.",
    "Tensor Cores": "Specialized units computing a small matrix "
        "multiply-accumulate (D = A*B + C) in a single hardware "
        "operation — dramatically higher throughput for the matmul-"
        "heavy workload deep learning IS, but only when inputs use "
        "compatible precision (FP16/BF16/TF32/INT8) and often specific "
        "dimension alignment.",
}

TENSOR_CORE_ENABLEMENT_EXAMPLE = textwrap.dedent("""\
    import torch

    # FP32 matmul — does NOT engage Tensor Cores on many GPU generations
    # (though TF32 mode, enabled by default in recent PyTorch on Ampere+,
    # partially bridges this) — historically the slower default path.
    a_fp32 = torch.randn(1024, 1024, device="cuda", dtype=torch.float32)
    b_fp32 = torch.randn(1024, 1024, device="cuda", dtype=torch.float32)
    c = a_fp32 @ b_fp32

    # FP16/BF16 matmul — DIRECTLY engages Tensor Cores on compatible
    # hardware, often several times faster for the SAME logical matmul.
    a_fp16 = a_fp32.half()
    b_fp16 = b_fp32.half()
    c_fast = a_fp16 @ b_fp16

    # torch.cuda.amp (Automatic Mixed Precision, L10) automates choosing
    # WHICH operations run in FP16 (to engage Tensor Cores) vs which stay
    # in FP32 (for numerical stability), rather than manually converting
    # every tensor yourself as shown above.
""")


if __name__ == "__main__":
    print(GPU_HIERARCHY_NOTE)
    print(WARP_DIVERGENCE_EXAMPLE)
    print("=== CUDA Cores vs Tensor Cores ===")
    for core_type, note in CORE_TYPE_COMPARISON.items():
        print(f"{core_type}: {note}\n")
    print(TENSOR_CORE_ENABLEMENT_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A team training a large model observes a ~3x throughput improvement
simply from ensuring their model's linear layer dimensions are
Tensor-Core-friendly (multiples of 8, and later verified multiples of 64
for even better alignment on their specific GPU generation) combined
with genuinely using FP16/BF16 tensors rather than FP32 — a change with
ZERO impact on model architecture or accuracy, purely a matter of
engaging the specialized Tensor Core hardware path that a naive FP32
implementation with arbitrary dimensions was leaving completely unused.
"""
