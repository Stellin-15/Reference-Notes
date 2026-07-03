# ============================================================
# L17: GPU Memory Hierarchy and Why Inference Is Bandwidth-Bound
# ============================================================
# WHAT: The actual physical memory hierarchy of a consumer GPU (HBM/VRAM,
#       L2 cache, shared memory/L1, registers), their real bandwidth and
#       latency numbers, and the roofline model for reasoning about
#       whether a kernel is compute-bound or memory-bound.
# WHY (SYSTEMS): Every kernel you write in L18-19 is an attempt to
#      manage THIS hierarchy well. Without a concrete mental model of
#      "how many bytes/sec can actually move where," you cannot judge
#      whether a kernel you write is close to hardware limits or leaving
#      performance on the table.
# LEVEL: Systems Core (Phase 5 of 8 — CUDA/Triton for a Consumer GPU)
# ============================================================

"""
CONCEPT OVERVIEW:
A GPU has several distinct memory levels, each roughly 1-2 orders of
magnitude different in size and bandwidth from its neighbor:

  - HBM/VRAM (e.g. 24GB on an RTX 4090): the "main" GPU memory. Large,
    but SLOW relative to on-chip memory — roughly 1000 GB/s on a
    high-end consumer card. Every tensor you load starts here.
  - L2 cache (a few MB, shared across the whole chip): much faster than
    HBM, automatically managed (you don't explicitly control what's in
    it, though you can influence it through access patterns).
  - Shared memory / L1 (per streaming multiprocessor, ~100-200KB):
    EXPLICITLY programmer-managed fast memory, shared by all threads in
    a thread block — this is the memory tier kernel authors actively
    design around, since it's ~10-20x faster than HBM and small enough
    that using it well requires deliberate tiling strategies.
  - Registers (per-thread, tiny): the fastest tier, but extremely limited
    — using too many registers per thread REDUCES how many threads can
    run concurrently (occupancy), a real tradeoff kernel authors tune.

THE ROOFLINE MODEL: for any computation, plot its "arithmetic intensity"
(FLOPs per byte moved — introduced in L02) against the hardware's peak
achievable performance. Below a certain arithmetic-intensity threshold
(the "ridge point," where memory bandwidth becomes the limiting factor
rather than compute throughput), a kernel's speed is capped by BANDWIDTH,
no matter how fast the compute units are — improving compute throughput
further does NOTHING for a memory-bound kernel. LLM decode-step matmuls
(established in L02 as having very low arithmetic intensity at batch
size 1) sit firmly in this memory-bound regime — which is the entire
reason quantization (fewer bytes to move) helps decode speed so directly.

PRODUCTION/RESEARCH USE CASE:
When you profile a real inference kernel (e.g. with `nsight compute` or
PyTorch's profiler) and see it's only achieving 20% of the GPU's
advertised peak FLOPs, the roofline model tells you WHETHER that's
actually a problem — if the kernel's arithmetic intensity puts it below
the ridge point, 20% of peak COMPUTE might already be 90%+ of peak
achievable BANDWIDTH-bound performance, meaning the kernel is actually
close to optimal and further "compute optimization" would be wasted
effort; the fix would have to be reducing bytes moved (quantization,
kernel fusion), not making the arithmetic faster.

COMMON MISTAKES:
- Trying to "optimize" a memory-bound kernel by making its arithmetic
  faster (e.g. using a faster matmul algorithm) — this does nothing if
  the kernel is bandwidth-bound; the actual lever is REDUCING BYTES
  MOVED (smaller dtype, kernel fusion to avoid intermediate writes/reads).
- Not accounting for the COST OF MOVING DATA TO HBM in the first place —
  loading a model's weights from disk/CPU RAM to GPU HBM (a one-time cost
  at startup) is a completely different bottleneck from the PER-TOKEN
  HBM-to-compute-unit bandwidth cost that dominates steady-state inference.
- Assuming "more shared memory usage = always faster" — over-using
  shared memory per thread block can REDUCE the number of thread blocks
  that fit concurrently on a streaming multiprocessor (occupancy), which
  can hurt performance despite each individual block running "faster."
"""

from dataclasses import dataclass


# ------------------------------------------------------------------
# 1. Representative consumer GPU specs (RTX 4090-class, illustrative)
# ------------------------------------------------------------------
@dataclass
class GPUSpec:
    name: str
    hbm_bandwidth_gbps: float     # HBM/VRAM bandwidth, GB/s
    fp16_tflops: float             # peak FP16 tensor-core throughput
    int8_tops: float                # peak INT8 tensor-core throughput
    vram_gb: float
    l2_cache_mb: float
    sm_shared_memory_kb: float     # per streaming-multiprocessor shared memory


RTX_4090 = GPUSpec(
    name="RTX 4090",
    hbm_bandwidth_gbps=1008,
    fp16_tflops=165,     # dense tensor-core FP16, approximate
    int8_tops=330,        # roughly 2x FP16, typical for INT8 tensor cores
    vram_gb=24,
    l2_cache_mb=72,
    sm_shared_memory_kb=128,
)


def ridge_point_flops_per_byte(gpu: GPUSpec, dtype: str = "fp16") -> float:
    """
    The roofline model's RIDGE POINT: the arithmetic intensity at which
    a kernel transitions from memory-bound to compute-bound. Below this
    value (FLOPs/byte), you're bandwidth-limited; above it, compute-limited.
    """
    peak_flops = gpu.fp16_tflops * 1e12 if dtype == "fp16" else gpu.int8_tops * 1e12
    peak_bandwidth = gpu.hbm_bandwidth_gbps * 1e9
    return peak_flops / peak_bandwidth


def roofline_achievable_performance(gpu: GPUSpec, arithmetic_intensity: float,
                                      dtype: str = "fp16") -> float:
    """
    Returns the MAXIMUM achievable FLOPs/sec for a kernel with the given
    arithmetic intensity — the roofline model's central prediction:
        achievable = min(peak_compute, arithmetic_intensity * peak_bandwidth)
    """
    peak_flops = gpu.fp16_tflops * 1e12 if dtype == "fp16" else gpu.int8_tops * 1e12
    peak_bandwidth = gpu.hbm_bandwidth_gbps * 1e9
    return min(peak_flops, arithmetic_intensity * peak_bandwidth)


# ------------------------------------------------------------------
# 2. Applying the roofline model to LLM decode vs prefill (from L02)
# ------------------------------------------------------------------
def analyze_llm_workload(gpu: GPUSpec):
    ridge = ridge_point_flops_per_byte(gpu, dtype="fp16")
    print(f"{gpu.name} ridge point (FP16): {ridge:.1f} FLOPs/byte")
    print(f"  Below this AI: memory-bound. Above: compute-bound.\n")

    # Reuse the exact matmul cost model from L02.
    def matmul_ai(m, k, n, dtype_bytes):
        flops = 2 * m * k * n
        bytes_moved = dtype_bytes * (m * k + k * n + m * n)
        return flops / bytes_moved

    workloads = {
        "Decode (batch=1, d=4096)":  matmul_ai(1, 4096, 4096, 2),
        "Decode (batch=8, d=4096)":  matmul_ai(8, 4096, 4096, 2),
        "Prefill (seq=512, d=4096)": matmul_ai(512, 4096, 4096, 2),
        "Prefill (seq=4096, d=4096)": matmul_ai(4096, 4096, 4096, 2),
    }

    for name, ai in workloads.items():
        achievable = roofline_achievable_performance(gpu, ai, dtype="fp16")
        pct_of_peak = 100 * achievable / (gpu.fp16_tflops * 1e12)
        regime = "MEMORY-BOUND" if ai < ridge else "compute-bound"
        print(f"  {name:32s}  AI={ai:7.2f}  {regime:14s}  "
              f"achievable={achievable/1e12:7.1f} TFLOPs ({pct_of_peak:5.1f}% of peak)")


# ------------------------------------------------------------------
# 3. Concrete effect of quantization on the roofline picture
# ------------------------------------------------------------------
def quantization_roofline_effect(gpu: GPUSpec):
    """
    Quantizing weights doesn't move the ridge point (that's a hardware
    property) — it moves the WORKLOAD's arithmetic intensity, by
    reducing bytes_moved for the SAME flop count. This is the precise
    mechanism (not just "smaller file, therefore faster") behind
    quantization's inference speedup for memory-bound workloads.
    """
    def matmul_ai(m, k, n, dtype_bytes):
        flops = 2 * m * k * n
        bytes_moved = dtype_bytes * (m * k + k * n + m * n)
        return flops / bytes_moved

    print("Decode-step (batch=1, d=4096) arithmetic intensity by weight dtype:")
    for dtype_name, dtype_bytes in [("FP16", 2), ("INT8", 1), ("INT4", 0.5)]:
        ai = matmul_ai(1, 4096, 4096, dtype_bytes)
        achievable = roofline_achievable_performance(gpu, ai, dtype="fp16")
        print(f"  {dtype_name:5s}  AI={ai:6.2f} FLOPs/byte   "
              f"achievable={achievable/1e9:8.1f} GFLOPs")
    # Each halving of dtype_bytes roughly DOUBLES arithmetic intensity
    # for a fixed FLOP count — and since we established this workload is
    # deep in the memory-bound regime, doubling AI roughly DOUBLES
    # achievable throughput too. This is the actual mechanism, made
    # numerically concrete, behind "quantization speeds up decode."


if __name__ == "__main__":
    analyze_llm_workload(RTX_4090)
    print()
    quantization_roofline_effect(RTX_4090)

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
When you write the fused dequantize-matmul Triton kernel in L18, its
entire performance argument rests on this lesson: a naive approach
(dequantize the full weight tensor to FP16 in one kernel, THEN run a
separate FP16 matmul kernel) pays the FULL FP16 bandwidth cost anyway,
because the dequantized FP16 tensor gets written to and then read back
from HBM between the two kernels. FUSING dequantization directly into
the matmul kernel (load compact INT4 bytes, dequantize IN REGISTERS/
SHARED MEMORY, immediately multiply) is what actually realizes the
bandwidth savings this lesson predicts — and this fusion argument is
incomprehensible without the memory-hierarchy model built here.
"""
