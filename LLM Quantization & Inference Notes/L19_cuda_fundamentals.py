# ============================================================
# L19: CUDA Fundamentals — Reading and Modifying Real Kernels
# ============================================================
# WHAT: The CUDA programming model (threads, blocks, grids, warps), the
#       execution model that Triton (L18) abstracts over, and enough real
#       CUDA C++ to read and modify actual inference-library kernel code
#       (llama.cpp, ExLlama, Marlin) when Triton alone isn't enough.
# WHY (SYSTEMS): Triton is the right STARTING point, but the fastest,
#      most specialized quantized-inference kernels in the wild are often
#      hand-written CUDA C++ — you need to be able to READ that code
#      (even if you write most of your own work in Triton) to understand
#      state-of-the-art techniques and eventually contribute to or extend
#      real inference engines.
# LEVEL: Systems Core (Phase 5 of 8 — final systems-fundamentals lesson)
# ============================================================

"""
CONCEPT OVERVIEW:
CUDA's execution model, bottom to top:

  - THREAD: the smallest unit of execution, runs one instance of your
    kernel function. Has its own registers and program counter.
  - WARP: a group of 32 threads that execute in LOCKSTEP on real NVIDIA
    hardware — all 32 threads in a warp execute the SAME instruction at
    the same time (SIMT — Single Instruction, Multiple Threads). This is
    why "warp divergence" (threads in a warp taking different branches of
    an `if`) is expensive: the hardware serializes the divergent paths,
    executing each path with the non-participating threads masked off.
  - THREAD BLOCK: a group of threads (up to 1024) that can cooperate via
    SHARED MEMORY (the fast, on-chip memory tier from L17) and
    synchronize via `__syncthreads()`. All threads in a block run on the
    SAME streaming multiprocessor (SM).
  - GRID: the full collection of thread blocks launched for one kernel
    call — blocks in a grid CANNOT directly communicate with each other
    (no block-to-block synchronization primitive within a single kernel
    launch), which is why kernels are often decomposed into multiple
    launches when cross-block coordination is needed.

Triton's `@triton.jit` functions correspond to a SINGLE THREAD BLOCK's
worth of work — Triton's compiler handles the mapping down to individual
threads/warps for you; raw CUDA requires you to reason about that mapping
explicitly, which is both the extra burden and the extra control CUDA
offers over Triton.

PRODUCTION/RESEARCH USE CASE:
Marlin (a widely-used, extremely fast INT4 matmul kernel) achieves its
speed through techniques below what Triton currently exposes cleanly:
precise register allocation, warp-level primitives (`__shfl_sync` for
exchanging data between threads in a warp without going through shared
memory), and careful instruction scheduling. Reading Marlin's source is
a genuinely useful exercise once this lesson's vocabulary is solid.

COMMON MISTAKES:
- Writing a CUDA kernel with heavy branching based on `threadIdx` in a way
  that causes WARP DIVERGENCE — e.g. `if (threadIdx.x % 2 == 0) {...}
  else {...}` splits every warp's 32 threads into two serialized groups
  of 16, roughly halving that warp's effective throughput for that code.
- Forgetting `__syncthreads()` after writing to shared memory and before
  a DIFFERENT thread in the same block reads it — without this barrier,
  there's no guarantee the write has completed before another thread's
  read, a classic race condition.
- Launching a grid with too FEW blocks to saturate the GPU's streaming
  multiprocessors (leaving SMs idle), or too many threads per block
  (exceeding register/shared-memory limits, which silently REDUCES the
  number of blocks that can run concurrently per SM — an occupancy
  problem introduced in L17, now with the specific CUDA-level cause).
"""

import textwrap


# ------------------------------------------------------------------
# 1. A minimal, complete, real CUDA kernel — vector addition
#    (the "hello world" of CUDA, annotated for exactly what maps to
#    what in Triton's abstraction)
# ------------------------------------------------------------------
VECTOR_ADD_CUDA = textwrap.dedent("""\
    __global__ void vector_add(const float* a, const float* b, float* out, int n) {
        // Each THREAD computes its own GLOBAL index from its block and
        // thread indices — this single line is what Triton's
        // `pid = tl.program_id(0)` plus `tl.arange(...)` abstracts away
        // for an entire BLOCK of elements at once, rather than one
        // thread at a time.
        int idx = blockIdx.x * blockDim.x + threadIdx.x;

        // Bounds check — REQUIRED because the grid size is often rounded
        // UP to a multiple of the block size, so some threads at the end
        // would read/write out of bounds without this guard. This is the
        // raw-CUDA equivalent of Triton's `mask=` argument to tl.load/store.
        if (idx < n) {
            out[idx] = a[idx] + b[idx];
        }
    }

    // Host-side launch (conceptual):
    //   int threads_per_block = 256;
    //   int num_blocks = (n + threads_per_block - 1) / threads_per_block;
    //   vector_add<<<num_blocks, threads_per_block>>>(a_dev, b_dev, out_dev, n);
""")

# ------------------------------------------------------------------
# 2. Shared memory tiling — the pattern behind every fast matmul kernel
# ------------------------------------------------------------------
TILED_MATMUL_CUDA_SKETCH = textwrap.dedent("""\
    #define TILE_SIZE 16

    __global__ void tiled_matmul(const float* A, const float* B, float* C,
                                  int M, int K, int N) {
        // SHARED memory tiles — explicitly declared, explicitly managed.
        // This is what Triton's `tl.load` into a block-shaped tensor
        // handles implicitly; here the programmer manages it by hand.
        __shared__ float tile_A[TILE_SIZE][TILE_SIZE];
        __shared__ float tile_B[TILE_SIZE][TILE_SIZE];

        int row = blockIdx.y * TILE_SIZE + threadIdx.y;
        int col = blockIdx.x * TILE_SIZE + threadIdx.x;
        float acc = 0.0f;

        for (int t = 0; t < (K + TILE_SIZE - 1) / TILE_SIZE; t++) {
            // Each thread loads ONE element into shared memory —
            // collectively, the whole thread block loads one full tile.
            if (row < M && t * TILE_SIZE + threadIdx.x < K)
                tile_A[threadIdx.y][threadIdx.x] = A[row * K + t * TILE_SIZE + threadIdx.x];
            else
                tile_A[threadIdx.y][threadIdx.x] = 0.0f;

            if (col < N && t * TILE_SIZE + threadIdx.y < K)
                tile_B[threadIdx.y][threadIdx.x] = B[(t * TILE_SIZE + threadIdx.y) * N + col];
            else
                tile_B[threadIdx.y][threadIdx.x] = 0.0f;

            // CRITICAL: every thread in the block must finish WRITING
            // its element to shared memory before ANY thread starts
            // READING from it in the loop below — without this barrier,
            // a fast thread could read a not-yet-written (garbage) value.
            __syncthreads();

            for (int k = 0; k < TILE_SIZE; k++)
                acc += tile_A[threadIdx.y][k] * tile_B[k][threadIdx.x];

            // Also required BEFORE the next iteration overwrites the
            // shared tiles — otherwise a slow thread might still be
            // READING the current tile while a fast thread starts
            // WRITING the next one.
            __syncthreads();
        }

        if (row < M && col < N)
            C[row * N + col] = acc;
    }

    // This EXACT tiling strategy (load a tile into shared memory once,
    // reuse it for many multiply-accumulates before moving to the next
    // tile) is the core idea that makes matmul kernels fast: each byte
    // loaded from HBM into shared memory is REUSED TILE_SIZE times
    // instead of being re-fetched from slow HBM on every use — directly
    // improving the effective arithmetic intensity discussed in L17.
""")

# ------------------------------------------------------------------
# 3. Warp-level primitives — the mechanism behind Marlin-class speed
# ------------------------------------------------------------------
WARP_SHUFFLE_NOTE = textwrap.dedent("""\
    __shfl_sync(mask, value, src_lane) lets threads WITHIN THE SAME WARP
    exchange register values DIRECTLY, without going through shared
    memory at all — this is faster than a shared-memory round trip
    because it stays entirely within the SM's register file, the fastest
    tier in the memory hierarchy (L17). Highly-optimized quantized-matmul
    kernels (Marlin, and the AWQ/GPTQ CUDA kernels) use warp shuffles
    extensively for tasks like broadcasting a shared scale factor to
    every thread in a warp, or performing a fast reduction (summing
    partial results across a warp) without ANY shared-memory traffic.

    A minimal example — broadcasting lane 0's value to every thread in
    the warp:
        float scale = ...;  // only lane 0 has the "real" value
        scale = __shfl_sync(0xFFFFFFFF, scale, 0);  // now EVERY lane has it
""")

# ------------------------------------------------------------------
# 4. When to drop to raw CUDA instead of staying in Triton
# ------------------------------------------------------------------
WHEN_TO_USE_RAW_CUDA = {
    "Triton is usually enough for": "standard fused elementwise/matmul "
        "patterns (like L18's dequant-matmul), rapid iteration, and "
        "getting within a reasonable margin of hand-tuned performance "
        "with far less code and far faster development time.",
    "Raw CUDA becomes worth it for": "kernels needing warp-level "
        "primitives Triton doesn't expose cleanly, extremely fine-"
        "grained register/occupancy tuning for a SPECIFIC GPU "
        "architecture, or squeezing out the last 10-20% of performance "
        "for a kernel that will run billions of times in production "
        "(where that last margin genuinely matters at scale).",
}


if __name__ == "__main__":
    print("=== Vector Add (CUDA) ===")
    print(VECTOR_ADD_CUDA)
    print("=== Tiled Matmul (CUDA, shared-memory tiling) ===")
    print(TILED_MATMUL_CUDA_SKETCH[:600], "...\n")
    for context, advice in WHEN_TO_USE_RAW_CUDA.items():
        print(f"{context}: {advice}\n")

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
When your own fused dequant-matmul kernel from L18 hits a performance
ceiling in Triton, the diagnostic path is: profile with `nsight compute`,
identify whether you're bandwidth-bound (matches L17's prediction, and
if so, further CUDA-level micro-optimization won't help — you need a
DIFFERENT algorithmic approach, like a smaller dtype or better fusion) or
whether you're leaving REGISTER/OCCUPANCY performance on the table (in
which case dropping to raw CUDA to hand-tune block/warp behavior, using
exactly the primitives introduced in this lesson, is the justified next
step) — this diagnostic judgment call is itself a real systems-engineering
skill, not something with a single universal answer.
"""
