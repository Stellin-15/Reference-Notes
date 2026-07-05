# ============================================================
# L05: Model and Tensor Parallelism — When a Model Doesn't Fit on One GPU
# ============================================================
# WHAT: Splitting a SINGLE model's weights/computation ACROSS multiple
#       GPUs — model parallelism (different LAYERS on different GPUs)
#       and the more fine-grained tensor parallelism (splitting
#       INDIVIDUAL large matrix operations across GPUs, Megatron-style).
# WHY: L04's data parallelism requires a FULL model copy per GPU — for
#      models too large for a single GPU's memory (increasingly common
#      with modern LLM scale), this is simply impossible, regardless of
#      how many GPUs you have. Model/tensor parallelism solves a
#      DIFFERENT problem than data parallelism: fitting one model across
#      many GPUs, not replicating it.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
MODEL PARALLELISM (the simpler, coarser form) splits a model's LAYERS
across GPUs — e.g. GPU 0 holds layers 1-10, GPU 1 holds layers 11-20 —
with activations passed BETWEEN GPUs as data flows through the network.
This directly solves the "model doesn't fit on one GPU" problem, but
introduces a real inefficiency: GPU 1 sits IDLE while GPU 0 computes
layers 1-10 (nothing for GPU 1 to do until GPU 0's output arrives), and
vice versa during the backward pass — this idle time is called a
"bubble," and naive model parallelism can leave GPUs idle for a
significant fraction of total time (L06's pipeline parallelism is
specifically designed to reduce this bubble).

TENSOR PARALLELISM (the Megatron-LM approach, now a standard technique)
takes a MORE FINE-GRAINED approach: instead of splitting entire LAYERS
across GPUs, it splits INDIVIDUAL large matrix operations WITHIN a
layer — e.g. a large linear layer's weight matrix is split COLUMN-WISE
across GPUs, each GPU computes its slice of the output using its slice
of the weights, and the results are combined via an all-reduce/all-
gather (L07) — critically, ALL GPUs are ACTIVELY COMPUTING
SIMULTANEOUSLY on different slices of the SAME operation, rather than
one GPU idling while another computes a different LAYER entirely. This
generally achieves better GPU utilization than pure model parallelism,
at the cost of MORE FREQUENT communication (an all-reduce after every
split operation, rather than once per layer boundary) — meaning tensor
parallelism requires GENUINELY FAST interconnect (NVLink between GPUs
in the same node) to be worthwhile; over a slower network (multiple
nodes), the communication overhead can outweigh the benefit.

THE PRACTICAL RULE OF THUMB: tensor parallelism WITHIN a single node
(GPUs connected by fast NVLink), pipeline parallelism (L06) ACROSS nodes
(where the communication pattern is less frequent and more tolerant of
higher inter-node network latency) — this is exactly the "3D parallelism"
strategy modern large-model training frameworks (Megatron, DeepSpeed,
L08) implement, COMBINING data, tensor, AND pipeline parallelism
simultaneously, each applied at the scale where it makes the most sense.

PRODUCTION USE CASE:
Training a model too large to fit on a single GPU's memory even at
batch size 1 uses tensor parallelism across the 8 GPUs WITHIN one node
(connected via fast NVLink, making the frequent all-reduce communication
tensor parallelism requires cheap enough to be worthwhile), while
pipeline parallelism (L06) is used ACROSS multiple such nodes (where
the less-frequent, larger communication pattern tolerates the slower
inter-node network) — a combined strategy neither technique alone
could achieve as efficiently.

COMMON MISTAKES:
- Using tensor parallelism ACROSS multiple nodes (over a relatively slow
  network) instead of confining it WITHIN a single node's fast NVLink
  interconnect — the frequent, fine-grained communication tensor
  parallelism requires makes it a poor fit for slower inter-node links,
  a common and costly mismatch.
- Choosing model parallelism (simple layer-splitting) without
  understanding its "bubble" inefficiency, when tensor parallelism (or
  pipeline parallelism with proper micro-batching, L06) would achieve
  meaningfully better GPU utilization for the same hardware.
- Attempting to implement tensor parallelism from scratch rather than
  using an established framework (Megatron-LM, DeepSpeed, L08) that has
  already solved the substantial engineering complexity of correctly
  splitting attention/MLP layers and managing the required communication
  patterns — this is genuinely intricate to get right, not a
  straightforward engineering task to reimplement casually.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Model parallelism — splitting layers across GPUs
# ------------------------------------------------------------------
MODEL_PARALLELISM_EXAMPLE = textwrap.dedent("""\
    import torch.nn as nn

    class ModelParallelNetwork(nn.Module):
        def __init__(self):
            super().__init__()
            # Layers 1-10 live on GPU 0, layers 11-20 on GPU 1 — each
            # GPU holds only ITS PORTION of the total model's weights.
            self.first_half = nn.Sequential(*[nn.Linear(1024, 1024) for _ in range(10)]).to("cuda:0")
            self.second_half = nn.Sequential(*[nn.Linear(1024, 1024) for _ in range(10)]).to("cuda:1")

        def forward(self, x):
            x = x.to("cuda:0")
            x = self.first_half(x)     # GPU 0 computes; GPU 1 is IDLE during this
            x = x.to("cuda:1")          # activation transferred ACROSS GPUs
            x = self.second_half(x)     # GPU 1 computes; GPU 0 is now IDLE
            return x

    # The "bubble": GPU 1 does nothing while GPU 0 computes the first
    # half, and GPU 0 does nothing while GPU 1 computes the second half
    # — for a 2-GPU split, up to ~50% GPU-time is potentially idle in
    # the NAIVE version shown here (L06's pipeline parallelism reduces
    # this via micro-batching, keeping BOTH GPUs busier simultaneously).
""")

# ------------------------------------------------------------------
# 2. Tensor parallelism — splitting a matrix operation itself
# ------------------------------------------------------------------
TENSOR_PARALLELISM_CONCEPT = textwrap.dedent("""\
    # Conceptual illustration of column-parallel linear layer (Megatron-
    # style) — the WEIGHT MATRIX is split column-wise across GPUs:
    #
    #   Full weight matrix W: shape (d_in, d_out)
    #   GPU 0 holds W[:, :d_out/2]     GPU 1 holds W[:, d_out/2:]
    #
    #   Both GPUs receive the SAME input x (broadcast, or already
    #   locally available), and EACH computes its own slice of the
    #   output SIMULTANEOUSLY:
    #     GPU 0: y0 = x @ W[:, :d_out/2]
    #     GPU 1: y1 = x @ W[:, d_out/2:]
    #
    #   The full output is y = concat(y0, y1) — requiring an
    #   ALL-GATHER (L07) to assemble the full result if a subsequent
    #   operation needs it, or the split can be carried FORWARD into
    #   the next operation without gathering, depending on the specific
    #   parallelization scheme (Megatron alternates column-parallel and
    #   row-parallel layers specifically to minimize communication).
    #
    # CRITICALLY: unlike model parallelism's sequential bubble, BOTH
    # GPUs here are ACTIVELY COMPUTING at the same time — better
    # utilization, at the cost of needing a communication step (all-
    # gather/all-reduce) after EVERY such split operation, not just once
    # per layer boundary.

    from megatron.core.tensor_parallel import ColumnParallelLinear, RowParallelLinear

    # Real usage (Megatron-LM/NVIDIA's framework) — the library handles
    # the actual splitting and communication for you:
    layer = ColumnParallelLinear(input_size=4096, output_size=4096, gather_output=False)
""")

# ------------------------------------------------------------------
# 3. The 3D parallelism strategy — combining approaches by scope
# ------------------------------------------------------------------
PARALLELISM_SCOPE_GUIDANCE = {
    "Data parallelism (L04)": "Replicate the FULL model — use across as "
        "many GPUs/nodes as available, whenever the model FITS on one GPU.",
    "Tensor parallelism (this lesson)": "Split individual operations — "
        "use WITHIN a single node's fast NVLink-connected GPUs, where "
        "frequent communication is cheap.",
    "Pipeline parallelism (L06)": "Split layers into stages — use ACROSS "
        "nodes, where less-frequent, larger communication tolerates "
        "slower inter-node networking.",
}


if __name__ == "__main__":
    print(MODEL_PARALLELISM_EXAMPLE)
    print(TENSOR_PARALLELISM_CONCEPT)
    print("=== Parallelism strategy by scope ===")
    for strategy, guidance in PARALLELISM_SCOPE_GUIDANCE.items():
        print(f"{strategy}: {guidance}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
Training a very large language model uses ALL THREE strategies
simultaneously ("3D parallelism"): tensor parallelism splits each
transformer layer's attention/MLP matrices across the 8 GPUs within
each node (fast NVLink makes the frequent communication cheap), pipeline
parallelism splits the model's LAYERS across multiple such nodes
(tolerating the slower inter-node network with less-frequent
communication), and data parallelism replicates this entire tensor+
pipeline-parallel setup across multiple such multi-node groups to use
even more total hardware — exactly the strategy DeepSpeed and Megatron-
LM (L08) implement and manage the considerable engineering complexity of, automatically.
"""
