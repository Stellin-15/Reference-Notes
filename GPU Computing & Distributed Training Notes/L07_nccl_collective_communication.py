# ============================================================
# L07: NCCL and Collective Communication Primitives
# ============================================================
# WHAT: The actual communication operations underlying EVERY distributed
#       training strategy covered so far — AllReduce, AllGather,
#       Broadcast, ReduceScatter — implemented by NVIDIA's NCCL
#       (NVIDIA Collective Communications Library), and how these
#       primitives map onto GPU interconnect topology (NVLink vs network).
# WHY: L04-L06 each referenced "gradient synchronization" or "all-
#      reduce" without explaining the actual mechanism — this lesson is
#      where those references become concrete. Every distributed
#      training framework (DDP, DeepSpeed, Megatron) uses NCCL
#      underneath for the actual cross-GPU data movement.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
A COLLECTIVE COMMUNICATION operation involves ALL participating
GPUs/processes together (as opposed to point-to-point send/receive
between just two) — NCCL implements these operations with topology-
aware algorithms specifically optimized for GPU interconnects (NVLink
within a node, InfiniBand/Ethernet between nodes), choosing different
underlying algorithms (ring-based, tree-based) depending on the number
of participants and the actual network topology, to minimize total
communication time.

ALLREDUCE is the operation underlying L04's gradient synchronization:
every GPU contributes a value (its local gradient), and EVERY GPU ends
up with the SAME reduced result (typically summed or averaged) — this
is implemented efficiently as a RING ALLREDUCE for many topologies: GPUs
are logically arranged in a ring, and data is passed around the ring in
a specific pattern (a "reduce-scatter" phase followed by an "all-gather"
phase) such that the TOTAL data transferred per GPU is roughly constant
regardless of how many GPUs participate — a genuinely clever algorithmic
property that makes AllReduce scale well to many GPUs, rather than
communication cost growing linearly (or worse) with participant count.

ALLGATHER collects a DIFFERENT piece of data from EVERY GPU and gives
EVERY GPU the FULL, COMBINED result — this is what L05's tensor
parallelism uses to assemble a full output tensor from each GPU's
column-parallel slice. BROADCAST sends data from ONE source GPU to ALL
others (e.g. broadcasting initial model weights to every GPU at the
start of training, ensuring all replicas start identical). REDUCESCATTER
combines a reduce (like AllReduce's summing) with a scatter (each GPU
ends up with only ITS OWN SLICE of the reduced result, not the full
thing) — this is actually the FIRST HALF of how ring-AllReduce is
implemented internally (ReduceScatter followed by AllGather equals
AllReduce), and it's also directly useful on its own for specific
sharded-optimizer patterns (L08's DeepSpeed ZeRO uses ReduceScatter directly).

INTERCONNECT TOPOLOGY matters enormously for actual achieved
performance: NVLINK (GPU-to-GPU direct connections WITHIN a single
node) offers dramatically higher bandwidth and lower latency than
going through the network to a DIFFERENT node — this is exactly WHY
L05 recommended confining tensor parallelism's frequent communication
to within-node NVLink-connected GPUs, and why pipeline/data
parallelism's less-frequent communication tolerates the slower
inter-node network better.

PRODUCTION USE CASE:
A training job's profiling reveals gradient AllReduce time scales
sub-linearly with GPU count up to 8 GPUs (all within one node, NVLink-
connected) but jumps significantly when scaling to a second node —
directly attributable to the interconnect topology difference (NVLink
vs inter-node networking), informing the team's decision to prioritize
tensor parallelism within each node and a communication-lighter strategy
(data or pipeline parallelism) across nodes, exactly matching L05's guidance.

COMMON MISTAKES:
- Assuming AllReduce communication cost scales LINEARLY with GPU count
  — ring-AllReduce's actual scaling property (roughly constant per-GPU
  communication volume) is a specific, non-obvious algorithmic result
  worth understanding rather than assuming naive linear scaling.
- Not considering INTERCONNECT TOPOLOGY when deciding which parallelism
  strategy to apply where (L05's guidance) — treating all "cross-GPU
  communication" as equally costly regardless of whether it crosses
  NVLink or a network boundary is a common, costly oversight.
- Manually implementing custom collective communication logic instead
  of using NCCL (via PyTorch's `torch.distributed` API, which uses NCCL
  as its backend for CUDA tensors) — NCCL's topology-aware algorithm
  selection is genuinely difficult to replicate correctly by hand.
"""

import textwrap


# ------------------------------------------------------------------
# 1. The four core collective operations, illustrated
# ------------------------------------------------------------------
COLLECTIVE_OPERATIONS_ILLUSTRATION = textwrap.dedent("""\
    AllReduce (used for gradient synchronization, L04):
      GPU 0: [1, 2, 3]  \\
      GPU 1: [4, 5, 6]   } -> EVERY GPU ends up with [5, 7, 9] (summed)
      GPU 2: [0, 0, 0]  /

    AllGather (used to assemble tensor-parallel outputs, L05):
      GPU 0: [A]  \\
      GPU 1: [B]   } -> EVERY GPU ends up with [A, B, C] (concatenated)
      GPU 2: [C]  /

    Broadcast (used to sync initial weights across all replicas):
      GPU 0 (source): [W1, W2, W3]
      GPU 1: receives [W1, W2, W3]
      GPU 2: receives [W1, W2, W3]

    ReduceScatter (the first half of ring-AllReduce internally; also
    used directly by ZeRO-style sharded optimizers, L08):
      GPU 0: [1, 2, 3]  \\
      GPU 1: [4, 5, 6]   } -> GPU 0 gets [5]  (its slice of the sum)
      GPU 2: [0, 0, 0]  /     GPU 1 gets [7]  (a DIFFERENT slice)
                               GPU 2 gets [9]  (a DIFFERENT slice)
""")

# ------------------------------------------------------------------
# 2. Ring-AllReduce — why communication cost doesn't scale linearly
# ------------------------------------------------------------------
def ring_allreduce_bandwidth_per_gpu(data_size: float, num_gpus: int) -> float:
    """
    A simplified model of ring-AllReduce's key property: total data
    TRANSFERRED PER GPU is approximately 2 * data_size * (N-1)/N —
    which APPROACHES 2 * data_size as N grows, NOT N * data_size as a
    naive "everyone sends to everyone" approach would require. This is
    THE algorithmic property that makes AllReduce scale well.
    """
    return 2 * data_size * (num_gpus - 1) / num_gpus


def scaling_demo():
    data_size_gb = 1.0   # e.g. 1GB of gradients
    print("Per-GPU communication volume for ring-AllReduce, vs naive approach:")
    for n in [2, 4, 8, 16, 64]:
        ring_cost = ring_allreduce_bandwidth_per_gpu(data_size_gb, n)
        naive_cost = data_size_gb * (n - 1)   # naive: send to every other GPU directly
        print(f"  {n:3d} GPUs: ring-AllReduce ~{ring_cost:.2f} GB/GPU, "
              f"naive all-to-all ~{naive_cost:.2f} GB/GPU")
    print("  -> ring-AllReduce's per-GPU cost APPROACHES a CONSTANT "
          "(~2GB here) as GPU count grows, while naive all-to-all "
          "grows LINEARLY with GPU count — this is why AllReduce scales "
          "to large GPU counts far better than a naive communication pattern would.")


# ------------------------------------------------------------------
# 3. Using NCCL via PyTorch's distributed API
# ------------------------------------------------------------------
NCCL_USAGE_EXAMPLE = textwrap.dedent("""\
    import torch.distributed as dist

    # "nccl" backend uses NCCL for all collective operations on CUDA
    # tensors — this is what DDP (L04) uses internally for gradient
    # AllReduce, and what tensor-parallel frameworks (L05) use for
    # their AllGather/ReduceScatter operations.
    dist.init_process_group(backend="nccl")

    tensor = torch.ones(1000, device="cuda")

    # Direct AllReduce call — this is EXACTLY what happens internally
    # (automatically) during DDP's loss.backward() call for gradients.
    dist.all_reduce(tensor, op=dist.ReduceOp.SUM)

    # Direct AllGather
    gathered = [torch.zeros(1000, device="cuda") for _ in range(dist.get_world_size())]
    dist.all_gather(gathered, tensor)

    # Broadcast (e.g. syncing initial model weights from rank 0)
    dist.broadcast(tensor, src=0)
""")

# ------------------------------------------------------------------
# 4. Interconnect topology — NVLink vs network
# ------------------------------------------------------------------
INTERCONNECT_COMPARISON = {
    "NVLink (within a node)": "Very high bandwidth, very low latency — "
        "direct GPU-to-GPU connections. Makes frequent, fine-grained "
        "communication (tensor parallelism, L05) practically worthwhile.",
    "InfiniBand/high-speed Ethernet (between nodes)": "Lower bandwidth, "
        "higher latency than NVLink, though still far faster than "
        "commodity networking — tolerates LESS FREQUENT, larger "
        "communication patterns (pipeline/data parallelism) better than "
        "tensor parallelism's frequent, small communication pattern.",
}


if __name__ == "__main__":
    print(COLLECTIVE_OPERATIONS_ILLUSTRATION)
    scaling_demo()
    print()
    print(NCCL_USAGE_EXAMPLE)
    print("=== Interconnect topology ===")
    for interconnect, note in INTERCONNECT_COMPARISON.items():
        print(f"{interconnect}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A team debugging unexpectedly slow multi-node training uses NCCL's own
debug logging (`NCCL_DEBUG=INFO`) to discover NCCL selected a
SUBOPTIMAL communication algorithm for their specific network topology
— explicitly configuring NCCL's topology awareness (via
`NCCL_TOPO_FILE` describing their actual InfiniBand fabric layout)
resolves the issue, recovering expected AllReduce throughput — a
concrete debugging path only accessible once you understand that NCCL
is making TOPOLOGY-DEPENDENT algorithm choices under the hood, not
applying one universal communication strategy regardless of hardware layout.
"""
