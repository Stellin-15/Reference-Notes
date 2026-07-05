# ============================================================
# L04: Data Parallelism — PyTorch DDP, Gradient Synchronization
# ============================================================
# WHAT: The simplest and most common distributed training strategy —
#       replicating the FULL model on every GPU, splitting the BATCH
#       across them, and synchronizing gradients after each backward
#       pass — implemented via PyTorch's DistributedDataParallel (DDP).
# WHY: This is the FIRST distributed-training strategy to reach for,
#      and the one that scales the most straightforwardly — L05-L06
#      cover model/tensor and pipeline parallelism specifically for the
#      case where a model is too LARGE to fit on one GPU at all, which
#      data parallelism alone cannot solve.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
DATA PARALLELISM works by giving EVERY GPU a COMPLETE COPY of the model,
and splitting each training BATCH into per-GPU MICRO-BATCHES — each GPU
independently computes a forward and backward pass on its own
micro-batch, producing its own LOCAL gradients. The key synchronization
step: before the optimizer updates any weights, ALL GPUs' local
gradients must be AVERAGED together (an ALL-REDUCE operation, covered
in full mechanical depth in L07's NCCL lesson) so every GPU ends up with
the IDENTICAL, averaged gradient — ensuring every GPU's model copy
stays IDENTICAL after the optimizer step, which is essential; if
gradients weren't synchronized, each GPU's model copy would drift
independently and stop being a valid "replica" of the same model at all.

PYTORCH'S DISTRIBUTEDDATAPARALLEL (DDP) is the standard, recommended
implementation of this pattern — it wraps your model, automatically
handles the gradient all-reduce (overlapping it with the backward pass's
computation for efficiency, rather than waiting for the ENTIRE backward
pass to finish before starting any communication), and requires each
GPU to run in its own PROCESS (not just a thread — this is a real,
deliberate design choice avoiding Python's GIL from limiting multi-GPU
throughput, unlike the older, now-discouraged `DataParallel`, DDP's
single-process, multi-thread predecessor).

EFFECTIVE BATCH SIZE SCALING is the direct, practical consequence of
data parallelism: training on 8 GPUs with a PER-GPU batch size of 32
gives you an EFFECTIVE (total) batch size of 256 — this typically
requires a corresponding LEARNING RATE adjustment (the well-known
"linear scaling rule": scaling the learning rate proportionally with
batch size, often combined with a warmup period, to maintain similar
training dynamics/convergence behavior to the smaller-batch, single-GPU
baseline) — simply adding more GPUs without adjusting the learning rate
can produce WORSE training outcomes despite more total compute being applied.

PRODUCTION USE CASE:
A team scales their training job from 1 GPU (batch size 32, learning
rate 1e-4) to 8 GPUs using DDP — naively keeping the SAME learning rate
with the new effective batch size of 256 produces measurably worse
final model accuracy than the single-GPU baseline; applying the linear
scaling rule (learning rate ~8e-4, with a brief warmup period) recovers
comparable (and, with the added compute, ultimately better, since more
data can be processed in less wall-clock time) training outcomes.

COMMON MISTAKES:
- Using the older `torch.nn.DataParallel` instead of
  `DistributedDataParallel` for new code — DataParallel is single-
  process, multi-thread, and suffers from Python GIL contention AND an
  unbalanced workload (one GPU does extra work gathering/scattering
  data) that DDP's multi-process design avoids entirely.
- Scaling up GPU count without correspondingly adjusting the learning
  rate (the linear scaling rule) — this is a genuine, well-documented
  training-dynamics pitfall, not just a minor tuning detail, and can
  produce meaningfully worse final model quality.
- Not accounting for data parallelism's fundamental limitation: EVERY
  GPU needs a FULL COPY of the model — for models too large to fit in a
  single GPU's memory at all, data parallelism alone cannot help; this
  is exactly the problem L05-L06's model/tensor/pipeline parallelism solve instead.
"""

import textwrap


# ------------------------------------------------------------------
# 1. DDP setup — the standard PyTorch multi-GPU training pattern
# ------------------------------------------------------------------
DDP_SETUP_EXAMPLE = textwrap.dedent("""\
    import torch
    import torch.distributed as dist
    from torch.nn.parallel import DistributedDataParallel as DDP
    from torch.utils.data.distributed import DistributedSampler

    def setup(rank, world_size):
        dist.init_process_group("nccl", rank=rank, world_size=world_size)
        torch.cuda.set_device(rank)

    def train(rank, world_size):
        setup(rank, world_size)

        model = MyModel().to(rank)
        # DDP wraps the model — it AUTOMATICALLY handles gradient
        # all-reduce after backward(), overlapping communication with
        # the backward pass's OWN computation for efficiency.
        ddp_model = DDP(model, device_ids=[rank])

        # DistributedSampler ensures each GPU (rank) sees a DIFFERENT
        # slice of the dataset each epoch — without this, every GPU
        # would train on the SAME data, defeating the purpose of
        # splitting the batch across GPUs at all.
        sampler = DistributedSampler(dataset, num_replicas=world_size, rank=rank)
        loader = torch.utils.data.DataLoader(dataset, batch_size=32, sampler=sampler)

        optimizer = torch.optim.Adam(ddp_model.parameters(), lr=1e-4)

        for epoch in range(num_epochs):
            sampler.set_epoch(epoch)   # reshuffle differently each epoch
            for batch in loader:
                optimizer.zero_grad()
                output = ddp_model(batch)
                loss = compute_loss(output)
                loss.backward()   # gradient all-reduce happens HERE,
                                    # automatically, overlapped with backward
                optimizer.step()   # every GPU now applies the IDENTICAL,
                                    # averaged gradient

    # Launch: torchrun --nproc_per_node=8 train.py
    # (torchrun handles spawning one PROCESS per GPU and setting rank/world_size)
""")

# ------------------------------------------------------------------
# 2. The linear scaling rule — learning rate vs effective batch size
# ------------------------------------------------------------------
def linear_scaling_rule(base_lr: float, base_batch_size: int, scaled_batch_size: int) -> float:
    """A simple, illustrative implementation of the well-documented
    linear scaling rule for learning rate vs batch size."""
    return base_lr * (scaled_batch_size / base_batch_size)


def scaling_demo():
    base_lr = 1e-4
    base_batch = 32
    num_gpus = 8
    per_gpu_batch = 32
    effective_batch = per_gpu_batch * num_gpus

    scaled_lr = linear_scaling_rule(base_lr, base_batch, effective_batch)
    print(f"Base config: batch={base_batch}, lr={base_lr}")
    print(f"Scaled config ({num_gpus} GPUs): effective_batch={effective_batch}, "
          f"scaled_lr={scaled_lr}")
    print("  -> Naively keeping lr=1e-4 at the LARGER effective batch size "
          "typically UNDER-TRAINS relative to this scaled learning rate, "
          "a real, measurable training-dynamics effect, not a minor detail.")

WARMUP_NOTE = textwrap.dedent("""\
    In practice, the scaled learning rate is usually reached GRADUALLY
    via a WARMUP period (the first few hundred/thousand steps ramp the
    LR up linearly from a small value to the full scaled LR) rather than
    used at full strength from step 1 — this combination (linear scaling
    + warmup) is the standard, well-validated recipe for large-batch
    distributed training, directly connecting to L06's cosine-with-
    warmup schedule concept from the LLM Quantization & Inference Notes
    domain, applied here specifically to the data-parallelism scaling context.
""")

# ------------------------------------------------------------------
# 3. DataParallel vs DistributedDataParallel — why DDP is preferred
# ------------------------------------------------------------------
DP_VS_DDP_COMPARISON = {
    "torch.nn.DataParallel (legacy, discouraged for new code)":
        "Single PROCESS, multiple THREADS — subject to Python's GIL "
        "limiting true parallelism; one GPU (the 'master') does extra "
        "work scattering inputs and gathering outputs, creating an "
        "unbalanced workload across GPUs.",
    "torch.nn.parallel.DistributedDataParallel (DDP, recommended)":
        "One INDEPENDENT PROCESS per GPU — no GIL contention between "
        "GPUs, balanced workload (each process handles its own full "
        "forward/backward/gradient-sync independently), and the "
        "standard, actively maintained approach for all new PyTorch "
        "multi-GPU training code.",
}


if __name__ == "__main__":
    print(DDP_SETUP_EXAMPLE)
    scaling_demo()
    print()
    print(WARMUP_NOTE)
    print("=== DataParallel vs DistributedDataParallel ===")
    for approach, note in DP_VS_DDP_COMPARISON.items():
        print(f"{approach}:\n  {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A research team scaling their training job from a single GPU to an
8-GPU node uses DDP with the linear scaling rule and a 500-step warmup —
their training loss curve, plotted against WALL-CLOCK TIME (not just
step count), shows the 8-GPU run reaching the same loss level roughly
7x faster than the single-GPU baseline (near-linear scaling, with the
small gap from perfect 8x explained by gradient all-reduce
communication overhead, L07) — a direct, measured validation that both
the parallelism strategy AND the learning-rate scaling recipe were
implemented correctly.
"""
