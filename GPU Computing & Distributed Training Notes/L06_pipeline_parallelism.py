# ============================================================
# L06: Pipeline Parallelism — Micro-Batching to Fill the Bubble
# ============================================================
# WHAT: Splitting a model into sequential STAGES across GPUs (like L05's
#       model parallelism), but processing MANY small micro-batches in
#       an overlapping, assembly-line fashion to keep every GPU busy
#       simultaneously — directly addressing the "bubble" inefficiency
#       L05 identified in naive model parallelism.
# WHY: L05's model parallelism has a real, measurable inefficiency:
#      GPUs idle while waiting for data from the previous stage.
#      Pipeline parallelism is the specific technique that fixes this,
#      and it's the strategy used ACROSS NODES in the 3D-parallelism
#      combination L05 introduced.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
Naive model parallelism (L05) processes ONE batch at a time through the
full pipeline of stages — GPU 1 is completely idle until GPU 0 finishes
its stage for that ENTIRE batch. PIPELINE PARALLELISM instead splits
each batch into many small MICRO-BATCHES, and feeds them through the
pipeline in an OVERLAPPING, ASSEMBLY-LINE fashion: while GPU 0 processes
micro-batch 2, GPU 1 is SIMULTANEOUSLY processing micro-batch 1 (which
GPU 0 already finished) — much like a factory assembly line where
multiple items are at different stages of production simultaneously,
rather than one item passing through the entire line before the next starts.

This dramatically reduces (though does not entirely eliminate) the
BUBBLE — there's still an unavoidable "fill" period at the START (GPU 1
has nothing to do until GPU 0 produces the first micro-batch's output)
and a "drain" period at the END (GPU 0 has nothing left to do once it's
processed all micro-batches, while GPU 1 finishes the last ones) — but
with ENOUGH micro-batches, this fill/drain overhead becomes a small
fraction of TOTAL processing time, since the STEADY STATE in the middle
keeps every GPU continuously busy.

THE GPIPE AND PIPEDREAM SCHEDULING STRATEGIES represent two different
approaches to managing this pipeline: GPipe uses a simpler "fill, then
drain" schedule (all micro-batches' forward passes complete before any
backward passes begin), trading some memory overhead (activations for
ALL micro-batches must be kept until their backward pass) for
simplicity. PipeDream-style "1F1B" (one-forward-one-backward)
scheduling interleaves forward and backward passes more tightly, using
LESS peak memory (fewer micro-batches' activations need to be held
simultaneously) at the cost of more complex scheduling logic — this
memory/complexity tradeoff is a real, practical decision modern
frameworks (DeepSpeed, L08) make on your behalf, exposed as a
configuration choice rather than something you typically implement by hand.

PRODUCTION USE CASE:
A model too large for tensor parallelism alone (or needing to scale
ACROSS multiple nodes where tensor parallelism's frequent communication
would be too costly, per L05) uses pipeline parallelism with a
sufficiently large number of micro-batches (a common guideline: at
least 4x the number of pipeline stages) to keep the bubble overhead
below roughly 10-20% of total training step time — validated by directly
measuring GPU utilization/idle time during actual training, not assumed
from theory alone.

COMMON MISTAKES:
- Using too FEW micro-batches relative to the number of pipeline
  stages — this makes the fill/drain bubble a LARGE fraction of total
  time (in the extreme, one micro-batch per stage is equivalent to naive
  model parallelism's full bubble problem), defeating the purpose of
  pipelining at all.
- Not accounting for pipeline parallelism's ADDITIONAL memory
  requirement — because multiple micro-batches are "in flight"
  simultaneously across different stages, MORE activation memory must
  be held at once than in a naive, single-micro-batch-at-a-time
  approach, a real memory/throughput tradeoff to balance.
- Implementing custom pipeline scheduling logic from scratch instead of
  using an established framework's (DeepSpeed, L08; PyTorch's own
  `torch.distributed.pipelining`) already-solved, carefully-tuned
  scheduling implementation — correctly handling the forward/backward
  interleaving and gradient accumulation across micro-batches is
  genuinely intricate to get right.
"""

import textwrap


# ------------------------------------------------------------------
# 1. The bubble problem, quantified
# ------------------------------------------------------------------
def bubble_overhead_fraction(num_stages: int, num_micro_batches: int) -> float:
    """
    A standard formula for the FRACTION of total pipeline time spent in
    the fill/drain bubble (not doing useful, overlapped work) — larger
    num_micro_batches relative to num_stages shrinks this fraction.
    """
    return (num_stages - 1) / (num_stages - 1 + num_micro_batches)


def bubble_demo():
    num_stages = 8   # e.g. 8 pipeline stages across 8 GPUs
    for micro_batches in [1, 4, 8, 32, 128]:
        overhead = bubble_overhead_fraction(num_stages, micro_batches)
        print(f"  {micro_batches:4d} micro-batches: {overhead:.1%} bubble overhead")
    print("  -> with only 1 micro-batch, this IS naive model parallelism "
          "(L05) — the bubble dominates. With 128 micro-batches, the "
          "bubble shrinks to a small fraction of total time.")


# ------------------------------------------------------------------
# 2. GPipe-style scheduling — conceptual timeline
# ------------------------------------------------------------------
GPIPE_SCHEDULE_ILLUSTRATION = textwrap.dedent("""\
    Time ->
    GPU 0: F1 F2 F3 F4          B4 B3 B2 B1
    GPU 1:    F1 F2 F3 F4          B4 B3 B2 B1
    GPU 2:       F1 F2 F3 F4          B4 B3 B2 B1
    GPU 3:          F1 F2 F3 F4          B4 B3 B2 B1

    (F = forward pass for a micro-batch, B = backward pass)

    GPipe's schedule: ALL forward passes for ALL micro-batches complete
    FIRST (across the whole pipeline), THEN all backward passes run —
    simple to reason about, but requires holding EVERY micro-batch's
    activations in memory until ITS backward pass eventually runs,
    since none of the backward passes start until the LAST forward pass
    (F4 on GPU 3) has completed.
""")

# ------------------------------------------------------------------
# 3. 1F1B (PipeDream-style) scheduling — lower memory footprint
# ------------------------------------------------------------------
ONE_F_ONE_B_ILLUSTRATION = textwrap.dedent("""\
    Time ->
    GPU 0: F1 F2 F3 B1 F4 B2 B3 B4
    GPU 1:    F1 F2 B1 F3 B2 F4 B3 B4
    GPU 2:       F1 B1 F2 B2 F3 B3 F4 B4
    GPU 3:          F1 B1 F2 B2 F3 B3 F4 B4

    1F1B interleaves forward and backward passes MUCH more tightly —
    each stage does roughly one forward, then one backward, alternating
    — meaning a micro-batch's activations are needed for a SHORTER
    period before being consumed by its backward pass, reducing PEAK
    memory usage compared to GPipe's "all forwards, then all backwards"
    approach, at the cost of more complex scheduling logic (handled by
    the framework, not something you typically implement by hand).
""")

# ------------------------------------------------------------------
# 4. Real framework usage — PyTorch's pipelining API
# ------------------------------------------------------------------
PYTORCH_PIPELINING_EXAMPLE = textwrap.dedent("""\
    from torch.distributed.pipelining import pipeline, SplitPoint

    # Define WHERE to split the model into pipeline stages
    split_spec = {
        "layers.10": SplitPoint.BEGINNING,   # stage boundary before layer 10
        "layers.20": SplitPoint.BEGINNING,   # another boundary before layer 20
    }
    pipe = pipeline(model, mb_args=(example_input,), split_spec=split_spec)

    # The framework handles micro-batch splitting, forward/backward
    # scheduling (1F1B or similar), and cross-stage activation
    # communication — you specify WHERE to split, not HOW to schedule
    # the resulting pipeline.
""")


if __name__ == "__main__":
    bubble_demo()
    print()
    print(GPIPE_SCHEDULE_ILLUSTRATION)
    print(ONE_F_ONE_B_ILLUSTRATION)
    print(PYTORCH_PIPELINING_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A team training a large model across 4 nodes (pipeline parallelism
across nodes, tensor parallelism within each node, per L05's 3D-
parallelism guidance) measures actual GPU utilization during training
and finds their initial configuration (8 micro-batches across 4 pipeline
stages) leaves a measurable ~30% bubble — increasing to 32 micro-batches
(within their memory budget, verified not to cause OOM given 1F1B
scheduling's lower memory footprint vs GPipe) reduces the bubble to
under 10%, a direct, measured throughput improvement from applying
exactly the formula and scheduling tradeoff this lesson covers.
"""
