# ============================================================
# L13: Profiling GPU Workloads with Nsight Systems and Nsight Compute
# ============================================================
# WHAT: NVIDIA's two complementary profiling tools — Nsight Systems
#       (system-wide TIMELINE profiling: CPU/GPU overlap, data transfer,
#       multi-GPU communication) and Nsight Compute (KERNEL-LEVEL deep
#       profiling: occupancy, memory throughput, instruction-level detail
#       for ONE specific kernel) — and how to use them together to find
#       actual bottlenecks in a distributed training job.
# WHY: L01-L12 covered many optimization techniques (parallelism
#      strategies, mixed precision, GPU sharing) — this lesson covers
#      how to actually MEASURE whether they're working, and identify
#      WHICH specific bottleneck to address next, rather than optimizing
#      blindly based on theory alone.
# LEVEL: Advanced (final systems lesson before the capstone)
# ============================================================

"""
CONCEPT OVERVIEW:
NSIGHT SYSTEMS provides a SYSTEM-WIDE TIMELINE view: CPU activity, GPU
kernel execution, memory transfers (host-to-device, device-to-host),
and — critically for distributed training — NCCL communication
operations (L07's AllReduce/AllGather/etc.), all correlated on ONE
shared timeline. This is the RIGHT TOOL for answering high-level
questions: "is my GPU actually busy the whole time, or are there gaps
where it's waiting on something (CPU preprocessing, data loading,
inter-GPU communication)?" — exactly the "bubble" question from L06's
pipeline parallelism, now answerable with an ACTUAL measured timeline
instead of theoretical estimation.

NSIGHT COMPUTE provides DEEP, KERNEL-LEVEL profiling for ONE SPECIFIC
kernel at a time — occupancy (what fraction of the GPU's theoretical
maximum concurrent threads is actually achieved), memory throughput
(actual achieved bandwidth vs the GPU's theoretical peak), and detailed
instruction-level metrics (register usage per thread, shared memory
usage, warp execution efficiency — directly relevant to L01's warp
divergence discussion, now measurable rather than theoretical). This is
the RIGHT TOOL once Nsight Systems has identified a SPECIFIC kernel as a
bottleneck, and you need to understand WHY that kernel isn't performing
well and what to change.

THE TYPICAL PROFILING WORKFLOW: start with Nsight Systems for the
BROAD, system-level view — identify whether the bottleneck is GPU
compute (kernels are running but taking a long time), GPU idle time
(gaps in the timeline — data loading, CPU preprocessing, or
communication overhead), or specifically COMMUNICATION time (NCCL
operations dominating the timeline, suggesting a parallelism-strategy
mismatch per L05's topology guidance). ONLY THEN, if the bottleneck is
identified as a SPECIFIC slow kernel, drill into Nsight Compute for
that kernel's detailed occupancy/memory-throughput/instruction metrics
to understand the ROOT CAUSE and what change (different block size,
different memory access pattern, engaging Tensor Cores per L01) would
actually help.

PRODUCTION USE CASE:
A distributed training job's throughput is lower than expected — Nsight
Systems' timeline reveals significant GPU IDLE TIME correlated with data
loading operations, not with the training kernels themselves or NCCL
communication — redirecting investigation entirely away from "optimize
the model's kernels" (which weren't the actual bottleneck at all) toward
the data loading pipeline (adding more DataLoader worker processes,
or prefetching), a diagnosis Nsight Compute's kernel-level view alone
could never have surfaced, since the problem wasn't in any KERNEL at all.

COMMON MISTAKES:
- Jumping straight to Nsight Compute's deep kernel-level profiling
  without first using Nsight Systems to confirm WHICH kernel (if any) is
  actually the bottleneck — this can waste significant time deeply
  optimizing a kernel that was never the actual limiting factor in the
  first place.
- Optimizing based on THEORETICAL expectations (L06's bubble formula,
  L07's ring-AllReduce scaling) without ever actually MEASURING the
  real, achieved behavior — theory predicts what SHOULD happen under
  idealized assumptions; profiling reveals what's ACTUALLY happening,
  including real-world factors theory doesn't capture (network
  congestion, uneven workload distribution, driver overhead).
- Profiling a SHORT, unrepresentative slice of training (e.g. just the
  first few steps) instead of a representative STEADY-STATE window —
  early steps often include one-time setup/warmup costs (cuDNN algorithm
  benchmarking, L03; initial data loading) that don't reflect steady-
  state throughput.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Nsight Systems — capturing a system-wide timeline
# ------------------------------------------------------------------
NSIGHT_SYSTEMS_USAGE = textwrap.dedent("""\
    # Profile a training script, capturing CPU, GPU, and NCCL activity
    nsys profile -o training_profile --trace=cuda,nvtx,osrt,cudnn,cublas,nccl \\
        python train.py

    # Opens as a VISUAL timeline in the Nsight Systems GUI, or can be
    # queried programmatically:
    nsys stats training_profile.nsys-rep

    # Key things to look for in the timeline:
    #   - GPU utilization: is the GPU row mostly SOLID (busy) or full of
    #     GAPS (idle, waiting on something)?
    #   - NCCL operations: do AllReduce/AllGather calls take a
    #     significant, correlated fraction of total step time?
    #   - CPU<->GPU memory transfers: are they OVERLAPPED with compute
    #     (L02's streams concept, visible directly in the timeline) or
    #     serialized (compute waits for transfer to finish first)?
""")

NVTX_ANNOTATION_EXAMPLE = textwrap.dedent("""\
    import torch.cuda.nvtx as nvtx

    for batch in dataloader:
        with nvtx.range("data_loading"):
            batch = prepare_batch(batch)

        with nvtx.range("forward_pass"):
            output = model(batch)

        with nvtx.range("backward_pass"):
            loss.backward()

        with nvtx.range("optimizer_step"):
            optimizer.step()

    # NVTX ranges appear as LABELED SECTIONS in the Nsight Systems
    # timeline — turning an otherwise-opaque sequence of CUDA calls into
    # a readable breakdown of "how much time did EACH LOGICAL PHASE of
    # my training step actually take," which is often far more
    # immediately actionable than raw kernel names alone.
""")

# ------------------------------------------------------------------
# 2. Nsight Compute — deep, single-kernel profiling
# ------------------------------------------------------------------
NSIGHT_COMPUTE_USAGE = textwrap.dedent("""\
    # Profile ALL kernel launches in detail (verbose, slow — usually
    # narrow this to a SPECIFIC kernel once Nsight Systems has identified one)
    ncu --set full -o kernel_profile python train.py

    # Profile only a SPECIFIC, already-identified kernel by name pattern:
    ncu --set full -k "my_custom_kernel" -o kernel_profile python train.py

    # Key metrics Nsight Compute reports per kernel:
    #   - Achieved Occupancy: actual concurrent-thread utilization vs
    #     the GPU's theoretical maximum for this kernel's configuration
    #   - Memory Throughput: achieved GB/s vs the GPU's theoretical peak
    #     bandwidth — directly relevant to L01/LLM Quantization Notes
    #     L17's memory-bound vs compute-bound distinction, now MEASURED
    #     rather than theoretically estimated
    #   - Warp Execution Efficiency: what fraction of a warp's 32 lanes
    #     were actually active on average — a LOW value here is direct,
    #     measured evidence of warp divergence (L01)
""")

# ------------------------------------------------------------------
# 3. The profiling workflow, as a decision tree
# ------------------------------------------------------------------
PROFILING_WORKFLOW = textwrap.dedent("""\
    1. Run Nsight Systems on a REPRESENTATIVE, steady-state training window
       (not the first few warmup steps).

    2. Look at the timeline's OVERALL shape:
       - GPU mostly IDLE, correlated with data loading gaps?
         -> Investigate the DATA PIPELINE (more DataLoader workers,
            prefetching), not GPU kernels at all.
       - GPU mostly IDLE, correlated with NCCL operations?
         -> Investigate PARALLELISM STRATEGY / interconnect topology
            (L05/L07) — likely a tensor-parallelism-over-slow-network
            mismatch, or insufficient overlap of communication with computation.
       - GPU mostly BUSY, but specific kernels take longer than expected?
         -> Proceed to Nsight Compute on THOSE specific kernels.

    3. In Nsight Compute, for the identified slow kernel:
       - Low occupancy? -> Consider adjusting block size/register usage.
       - Low memory throughput relative to peak, on a MEMORY-BOUND
         kernel? -> Consider L01's Tensor Core engagement (dtype/shape),
         or reducing unnecessary memory traffic (L03's fusion discussion).
       - Low warp execution efficiency? -> Investigate warp divergence
         (L01) in that kernel's branching logic.
""")


if __name__ == "__main__":
    print(NSIGHT_SYSTEMS_USAGE)
    print(NVTX_ANNOTATION_EXAMPLE)
    print(NSIGHT_COMPUTE_USAGE)
    print(PROFILING_WORKFLOW)

"""
PRODUCTION CONTEXT EXAMPLE:
A team's multi-node training throughput is well below their theoretical
projection (per L06/L07's formulas) — Nsight Systems' timeline reveals
NCCL AllReduce operations consuming a much larger fraction of step time
than expected, and further investigation (checking NCCL's own debug
output, L07) reveals the cluster's inter-node network wasn't using the
expected high-speed InfiniBand fabric due to a misconfiguration, silently
falling back to slower Ethernet — a root cause that pure theoretical
analysis would never have surfaced, found specifically because the team
measured the ACTUAL system behavior with Nsight Systems rather than
assuming the theoretical model held.
"""
