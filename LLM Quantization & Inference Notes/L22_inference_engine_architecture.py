# ============================================================
# L22: Reading Real Inference Engines — vLLM and llama.cpp Architecture
# ============================================================
# WHAT: A guided tour of how vLLM and llama.cpp are ACTUALLY structured
#       internally — mapping every concept from L17-L21 (memory
#       hierarchy, fused kernels, KV cache paging, continuous batching)
#       onto the real components of two production-grade, widely-used
#       inference engines.
# WHY (SYSTEMS): The goal of this whole curriculum's systems track is to
#      build tooling that "makes AI easier to run on hardware" — you are
#      not going to invent inference serving from nothing; you're going
#      to extend, contribute to, or build something INSPIRED BY these
#      real systems. Knowing their actual architecture is the direct
#      prerequisite for that.
# LEVEL: Systems Core (Phase 6 of 8 — final lesson, ties everything together)
# ============================================================

"""
CONCEPT OVERVIEW:
vLLM's architecture, mapped to what you've learned:

  - LLMEngine: the top-level orchestrator. Owns the scheduler and the
    model executor. Roughly corresponds to the "continuous batching
    scheduler" from L21 — deciding which requests are active each step.
  - Scheduler: implements continuous batching's admission/eviction logic
    (L21) — decides, every step, which waiting requests to admit and
    which finished ones to evict, subject to available KV cache memory.
  - BlockManager: implements PagedAttention (L20) — the block
    allocator/free-list and per-sequence block tables live here.
  - Worker / ModelRunner: owns the actual model weights (potentially
    GPTQ/AWQ-quantized, per Phase 4) and runs the forward pass, calling
    into custom CUDA/Triton kernels (like L18's fused dequant-matmul, or
    vLLM's own PagedAttention CUDA kernel that reads the block table
    directly during attention computation).
  - The PagedAttention CUDA kernel itself is the piece that ties L03's
    attention math, L17's memory hierarchy reasoning, and L20's block
    management together — it computes attention scores while reading K/V
    values from NON-CONTIGUOUS physical blocks, using the block table as
    an indirection layer INSIDE the kernel (not as a separate
    gather/copy step beforehand, which would reintroduce the exact
    memory-traffic waste L18's fusion argument warns against).

llama.cpp's architecture, mapped the same way:

  - GGUF loader: reads the format from L15 — parses the header, tensor
    metadata, and memory-maps (or loads) the quantized weight blocks.
  - ggml (the underlying tensor library): implements the actual
    computation graph and CPU/GPU kernels, including hand-written
    K-quant dequantization kernels for many different CPU instruction
    sets (AVX2, AVX-512, ARM NEON) — this is where llama.cpp's famous
    CPU inference speed comes from: highly-tuned, architecture-specific
    kernels for exactly the block/superblock format from L15.
  - Backend abstraction: ggml supports multiple compute backends (CPU,
    CUDA, Metal, Vulkan) behind a common interface — the SAME GGUF file
    can run on very different hardware because the FORMAT (L15) is
    decoupled from the KERNEL implementation for any particular backend.
  - llama.cpp's batching/serving story is comparatively simpler than
    vLLM's (it's originally designed for single-user local inference,
    not high-throughput multi-tenant serving) — though `llama-server`
    has grown continuous-batching-like capabilities over time as its use
    case has expanded toward serving.

PRODUCTION/RESEARCH USE CASE:
If your goal is "make AI easier on hardware," a genuinely valuable and
achievable contribution path is: pick ONE of these two systems, find a
specific gap (a missing quantization format, an unsupported hardware
backend, a kernel that could be fused better), and contribute a real,
reviewed, merged improvement — this is simultaneously a way to build
expertise, build a portfolio, and directly serve your stated goal, without
needing to build an entirely new inference engine from scratch first.

COMMON MISTAKES:
- Assuming vLLM and llama.cpp are competing for the SAME use case — vLLM
  is optimized for high-throughput MULTI-TENANT SERVING (many concurrent
  users, datacenter GPUs); llama.cpp is optimized for SINGLE-USER LOCAL
  inference (CPU or consumer GPU, minimal dependencies, easy deployment).
  Choosing between them (or their underlying techniques) should be driven
  by which use case you're actually solving for.
- Trying to read either codebase top-down without first having the
  vocabulary from L17-L21 — the code will look like arbitrary complexity
  without the conceptual map this lesson (and the rest of Phase 6)
  provides.
- Underestimating how much of llama.cpp's practical performance comes
  from architecture-SPECIFIC kernel tuning (different code paths for
  AVX2 vs AVX-512 vs ARM NEON) rather than the quantization format alone
  — the format (L15) makes efficient computation POSSIBLE, but realizing
  it requires real per-architecture kernel engineering, directly
  connecting back to L19's CUDA-vs-Triton tradeoff discussion (here,
  CPU-SIMD-vs-portable-C is the analogous tradeoff).
"""

import textwrap

# ------------------------------------------------------------------
# 1. vLLM's request lifecycle, traced end to end
# ------------------------------------------------------------------
VLLM_REQUEST_LIFECYCLE = textwrap.dedent("""\
    1. Client sends a generation request -> LLMEngine.add_request()
    2. Scheduler places it in a WAITING queue.
    3. Every engine step (LLMEngine.step()):
         a. Scheduler decides which waiting requests to ADMIT (subject to
            KV cache block availability via BlockManager — L20) and which
            running requests to EVICT/PREEMPT if memory is tight.
         b. ModelRunner executes ONE forward pass for the current batch
            of active sequences (continuous batching — L21), calling the
            PagedAttention kernel (which reads K/V through each
            sequence's block table, not a contiguous buffer — L20).
         c. Sampled tokens are appended to each active sequence; the
            BlockManager allocates a new physical block whenever a
            sequence's current block fills up.
         d. Finished sequences are removed; their blocks are freed back
            to the pool.
         e. Results for finished/streaming sequences are returned to
            the client.
    4. Repeat step 3 until all requests are complete.
""")

# ------------------------------------------------------------------
# 2. llama.cpp's model-loading and inference path
# ------------------------------------------------------------------
LLAMA_CPP_LOAD_AND_INFER_PATH = textwrap.dedent("""\
    1. GGUF file opened, header + tensor metadata parsed (tensor names,
       shapes, quantization TYPE per tensor — e.g. Q4_K_M for most
       weights, often F16 or F32 for norms/embeddings — L15).
    2. Tensor data is either fully loaded into RAM or memory-mapped
       (mmap) directly from disk — mmap lets the OS page in weight data
       LAZILY, which matters for models larger than available RAM, and
       lets multiple processes share the same read-only weight pages.
    3. The ggml computation graph is built for one forward pass — nodes
       correspond to operations (matmul, RMSNorm, RoPE application, etc.
       — everything from L05's transformer block), each backed by an
       architecture-specific kernel implementation.
    4. On CPU: for each K-quant tensor, ggml calls a DEQUANTIZE-FUSED
       matmul kernel specifically hand-written for the host's SIMD
       instruction set (AVX2/AVX-512/NEON) — conceptually identical to
       L18's fused Triton kernel, but hand-tuned per CPU architecture
       instead of compiled generically.
    5. On GPU (CUDA/Metal/Vulkan backend): similar fused dequant-matmul
       kernels exist per-backend, letting the same GGUF file run
       efficiently across very different hardware without reformatting.
""")

# ------------------------------------------------------------------
# 3. A concrete diagnostic exercise: profiling one real inference call
# ------------------------------------------------------------------
PROFILING_EXERCISE_NOTE = textwrap.dedent("""\
    A genuinely useful exercise to internalize this entire phase: clone
    vLLM, run a small quantized model, and use `torch.profiler` (or
    `nsight systems` for a GPU-level trace) on a single generation
    request. In the trace, try to identify:
      - The PagedAttention CUDA kernel call (L20) — how much of total
        time does it consume relative to the linear-layer matmuls?
      - Whether the linear layers are using a fused quantized kernel
        (L18) or falling back to a separate dequantize-then-matmul path
        — the profiler's kernel list will show you EXACTLY how many
        distinct kernel launches happen per layer, which tells you
        definitively whether fusion is actually happening in this
        specific code path.
      - How the scheduler's step boundaries (L21) show up as gaps or
        batching-size changes in the trace over a multi-request run.

    This exercise turns everything from L17 onward from "read about it"
    into "verified with my own eyes, on real hardware, in a real system"
    — which is exactly the standard your eventual research/systems work
    should be held to.
""")


if __name__ == "__main__":
    print("=== vLLM request lifecycle ===")
    print(VLLM_REQUEST_LIFECYCLE)
    print("=== llama.cpp load-and-infer path ===")
    print(LLAMA_CPP_LOAD_AND_INFER_PATH)
    print("=== Suggested profiling exercise ===")
    print(PROFILING_EXERCISE_NOTE)

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
This lesson is the deliberate hinge between Phase 6 (understanding
existing systems) and Phase 7-8 (research methodology and your own
capstone project). A concrete, well-scoped capstone idea directly
enabled by everything through this lesson: implement KV-cache
quantization (INT8 or NF4-style, from Phase 3-4) as an ACTUAL PATCH to
either vLLM or llama.cpp, benchmark the real throughput/memory tradeoff
on your own consumer GPU, and write up the results — this single project
touches nearly every phase of this curriculum and produces something
concretely useful whether or not it becomes a published paper.
"""
