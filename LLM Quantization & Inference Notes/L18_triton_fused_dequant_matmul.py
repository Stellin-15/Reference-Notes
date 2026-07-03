# ============================================================
# L18: Writing a Fused Dequantize-Matmul Kernel in Triton
# ============================================================
# WHAT: A real, runnable Triton kernel that loads INT4-quantized weights,
#       dequantizes them ON THE FLY inside the kernel (never materializing
#       a full-precision weight tensor in HBM), and immediately uses them
#       in a matmul — the exact technique real quantized-inference
#       libraries (AutoGPTQ, AWQ's kernels, marlin) use.
# WHY (SYSTEMS): This is where quantization theory (Phase 4) becomes an
#      ACTUAL SPEEDUP, not just a smaller file on disk. Triton is the
#      practical entry point for writing custom GPU kernels without
#      hand-writing raw CUDA C++ — it's Python-like, compiles to
#      efficient GPU code, and is what most modern quantized-inference
#      kernels are either written in or inspired by.
# LEVEL: Systems Core (Phase 5 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
Triton is a Python-embedded DSL (domain-specific language) for writing
GPU kernels — you write functions decorated with `@triton.jit`, operating
on BLOCKS of data (not individual threads, unlike raw CUDA), and the
Triton compiler handles a lot of the low-level thread/memory scheduling
that you'd otherwise write by hand in CUDA C++.

The fused dequant-matmul pattern works like this:
  1. The kernel loads a TILE of packed low-bit weight data (e.g. INT4,
     two values packed per byte — see L15's nibble packing) from HBM
     into fast on-chip memory.
  2. It ALSO loads that tile's scale factor(s) — small, per-group values.
  3. INSIDE THE KERNEL, still in fast memory, it unpacks and dequantizes
     the weight tile to FP16 (a cheap bitwise/arithmetic operation, done
     on-chip, not requiring a separate HBM round-trip).
  4. It immediately uses the dequantized tile in the matmul's
     multiply-accumulate step.
  5. It NEVER writes the dequantized FP16 weights back to HBM — the
     full-precision version of the weights exists ONLY transiently,
     inside the kernel's fast memory, for exactly as long as it's needed.

This is precisely the "fusion" argument from L17: a naive two-kernel
approach (separate dequantize kernel, then separate matmul kernel) pays
the FULL FP16 HBM bandwidth cost for writing AND reading the intermediate
dequantized tensor. Fusing them into ONE kernel means HBM traffic is
dominated by the SMALL quantized weight bytes, not the large dequantized
FP16 bytes — this is the entire mechanism by which quantization actually
translates into measured wall-clock speedup, not just smaller file size.

PRODUCTION/RESEARCH USE CASE:
This exact pattern (fused dequant-matmul) is what libraries like AutoGPTQ,
AWQ's provided kernels, and Marlin (a highly-optimized INT4 kernel) all
implement — usually in raw CUDA C++ for maximum performance, but Triton
gets remarkably close to hand-tuned CUDA performance for this pattern
while being FAR more approachable to write and modify, making it the
right starting point for your own kernel work.

COMMON MISTAKES:
- Dequantizing OUTSIDE the kernel (as a separate PyTorch op) before
  calling a standard matmul — this defeats the entire point; it's
  functionally identical to just storing FP16 weights, since the
  dequantized tensor still gets written to and read from HBM.
- Getting BLOCK SIZE choices wrong — Triton kernels are tuned via
  `BLOCK_SIZE_M/N/K` constants; too small wastes parallelism, too large
  can exceed shared memory limits or hurt occupancy (see L17) — this is
  an empirical tuning problem, often solved via `triton.autotune`.
- Forgetting that Triton (like CUDA) requires explicit MASKING for tensor
  dimensions that don't evenly divide the block size — omitting a mask
  reads/writes out of bounds, a silent correctness bug that may not even
  crash, just produce subtly wrong results near tensor edges.
"""

# NOTE: Triton requires an NVIDIA GPU + the `triton` package to actually
# run. This file is written as REAL, correct Triton code (not pseudocode)
# so you can run it directly on your RTX-class GPU — but it's presented
# here as heavily-commented source for study even without a GPU handy.

try:
    import torch
    import triton
    import triton.language as tl
    TRITON_AVAILABLE = True
except ImportError:
    TRITON_AVAILABLE = False


if TRITON_AVAILABLE:
    @triton.jit
    def fused_dequant_matmul_kernel(
        # Pointers to the input tensors
        x_ptr, w_packed_ptr, scales_ptr, out_ptr,
        # Matrix dimensions
        M, N, K,
        # Strides (memory layout — see L01 for why these matter)
        stride_xm, stride_xk,
        stride_wk, stride_wn,      # w_packed is (K, N/2) — 2 values packed per byte
        stride_om, stride_on,
        GROUP_SIZE: tl.constexpr,   # quantization group size (see L11)
        BLOCK_M: tl.constexpr, BLOCK_N: tl.constexpr, BLOCK_K: tl.constexpr,
    ):
        """
        Computes out = x @ dequantize(w_packed, scales), fusing the
        dequantization directly into the matmul's inner loop — the
        dequantized weight tile exists ONLY in registers/shared memory
        for the duration of one block's computation, never touching HBM.
        """
        pid_m = tl.program_id(0)
        pid_n = tl.program_id(1)

        # Compute the row/col offsets this program instance is responsible for.
        offs_m = pid_m * BLOCK_M + tl.arange(0, BLOCK_M)
        offs_n = pid_n * BLOCK_N + tl.arange(0, BLOCK_N)
        offs_k = tl.arange(0, BLOCK_K)

        # Accumulator, kept in FP32 for numerical accuracy during
        # accumulation even though inputs are lower precision — this is
        # standard practice: accumulate high, store low.
        acc = tl.zeros((BLOCK_M, BLOCK_N), dtype=tl.float32)

        for k in range(0, K, BLOCK_K):
            # --- Load the activation tile (already FP16, no dequant needed) ---
            x_ptrs = x_ptr + offs_m[:, None] * stride_xm + (offs_k[None, :] + k) * stride_xk
            x_mask = (offs_m[:, None] < M) & (offs_k[None, :] + k < K)
            x_tile = tl.load(x_ptrs, mask=x_mask, other=0.0)

            # --- Load the PACKED (INT4, 2-per-byte) weight tile ---
            # Each byte holds two 4-bit values; dividing the K-offset by 2
            # gives the BYTE index, since packing halves the addressable
            # element count along that axis.
            w_byte_ptrs = (w_packed_ptr
                           + ((offs_k[:, None] + k) // 2) * stride_wk
                           + offs_n[None, :] * stride_wn)
            w_mask = (offs_k[:, None] + k < K) & (offs_n[None, :] < N)
            packed_bytes = tl.load(w_byte_ptrs, mask=w_mask, other=0)

            # Unpack: even K-offsets read the LOW nibble, odd read the HIGH.
            is_low_nibble = (offs_k[:, None] + k) % 2 == 0
            unpacked = tl.where(is_low_nibble, packed_bytes & 0x0F, (packed_bytes >> 4) & 0x0F)
            # Convert unsigned nibble [0,15] to signed [-8,7] range.
            signed_int4 = unpacked.to(tl.float32) - 8.0

            # --- Load the per-group scale and dequantize IN-KERNEL ---
            group_idx = (offs_k[:, None] + k) // GROUP_SIZE
            scale_ptrs = scales_ptr + group_idx * N + offs_n[None, :]
            scales = tl.load(scale_ptrs, mask=w_mask, other=1.0)
            w_dequantized = signed_int4 * scales   # THE fusion point: dequant
                                                     # happens here, in registers,
                                                     # immediately before use —
                                                     # never written back to HBM.

            # --- Multiply-accumulate ---
            acc += tl.dot(x_tile, w_dequantized)

        # Write the final FP32 accumulator out (optionally cast to FP16).
        out_ptrs = out_ptr + offs_m[:, None] * stride_om + offs_n[None, :] * stride_on
        out_mask = (offs_m[:, None] < M) & (offs_n[None, :] < N)
        tl.store(out_ptrs, acc, mask=out_mask)


    def fused_dequant_matmul(x: torch.Tensor, w_packed: torch.Tensor,
                               scales: torch.Tensor, group_size: int) -> torch.Tensor:
        """Python-side launcher: sets up the grid and calls the Triton kernel."""
        M, K = x.shape
        _, N = w_packed.shape  # w_packed's second dim is already N (unpacked count)
        out = torch.empty((M, N), device=x.device, dtype=torch.float32)

        BLOCK_M, BLOCK_N, BLOCK_K = 64, 64, 32
        grid = (triton.cdiv(M, BLOCK_M), triton.cdiv(N, BLOCK_N))

        fused_dequant_matmul_kernel[grid](
            x, w_packed, scales, out,
            M, N, K,
            x.stride(0), x.stride(1),
            w_packed.stride(0), w_packed.stride(1),
            out.stride(0), out.stride(1),
            GROUP_SIZE=group_size,
            BLOCK_M=BLOCK_M, BLOCK_N=BLOCK_N, BLOCK_K=BLOCK_K,
        )
        return out


# ------------------------------------------------------------------
# A pure-Python reference implementation, for correctness checking
# without requiring a GPU — verify your Triton kernel against this.
# ------------------------------------------------------------------
def reference_dequant_matmul(x, w_int4_signed, scales, group_size):
    """
    x: (M, K) float
    w_int4_signed: (K, N) int, values in [-8, 7]
    scales: (K // group_size, N) float
    """
    import numpy as np
    K, N = w_int4_signed.shape
    dequant_w = np.zeros((K, N))
    for k in range(K):
        group = k // group_size
        dequant_w[k] = w_int4_signed[k] * scales[group]
    return x @ dequant_w


if __name__ == "__main__":
    if TRITON_AVAILABLE and torch.cuda.is_available():
        torch.manual_seed(0)
        M, K, N, group_size = 64, 128, 64, 32
        x = torch.randn(M, K, device="cuda", dtype=torch.float32)

        w_int4 = torch.randint(-8, 8, (K, N), device="cuda", dtype=torch.int32)
        scales = torch.rand(K // group_size, N, device="cuda") * 0.1

        # Pack into bytes for the kernel (unsigned nibble representation)
        w_unsigned = (w_int4 + 8).to(torch.uint8)
        w_packed = (w_unsigned[0::2, :] | (w_unsigned[1::2, :] << 4))

        result = fused_dequant_matmul(x, w_packed, scales, group_size)
        print("Fused kernel output shape:", result.shape)
    else:
        print("Triton/CUDA not available in this environment — reference-only check:")
        import numpy as np
        np.random.seed(0)
        M, K, N, group_size = 8, 16, 8, 4
        x = np.random.randn(M, K)
        w_int4 = np.random.randint(-8, 8, (K, N))
        scales = np.random.rand(K // group_size, N) * 0.1
        out = reference_dequant_matmul(x, w_int4, scales, group_size)
        print("Reference (NumPy) output shape:", out.shape)

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
Benchmarking this kernel against (a) a naive "dequantize to a full FP16
tensor, then call torch.matmul" baseline and (b) PyTorch's native FP16
matmul on the FULL-PRECISION weight is the exact experiment that proves
(or disproves, on your specific hardware/shapes) the L17 roofline
argument empirically — this is genuinely useful, publishable-adjacent
systems work: characterizing where fused dequant-matmul actually wins,
and where its overhead (extra unpacking arithmetic per element) makes it
LOSE against simpler approaches, is real, valuable, currently-relevant
knowledge for anyone building inference tooling.
"""
