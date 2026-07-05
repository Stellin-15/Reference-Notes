# ============================================================
# L08: DeepSpeed — ZeRO Optimizer Sharding and Offload
# ============================================================
# WHAT: Microsoft's DeepSpeed framework, and specifically its flagship
#       contribution ZeRO (Zero Redundancy Optimizer) — a technique that
#       eliminates the MEMORY REDUNDANCY inherent in standard data
#       parallelism (L04), where every GPU wastefully holds a full copy
#       of optimizer state that could instead be SHARDED across GPUs.
# WHY: L04's data parallelism replicates not just the MODEL but also the
#      OPTIMIZER STATE (momentum, variance for Adam) on every GPU — for
#      large models, this optimizer state is often LARGER than the
#      model weights themselves (this repo's LLM Quantization & Inference
#      Notes L08 covers the exact memory math). ZeRO eliminates this
#      redundancy, letting you train much larger models on the same
#      hardware.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
Standard data-parallel training (L04) has EVERY GPU hold: (1) the full
model weights, (2) the full gradients, and (3) the full OPTIMIZER STATE
(for Adam: a first and second moment estimate PER PARAMETER, at FP32
precision — this repo's LLM Quantization & Inference Notes L08
established this is often 2x the model's own parameter memory). This is
REDUNDANT: since gradients are averaged (all-reduced) to be IDENTICAL
across all GPUs anyway, and the optimizer applies the SAME update
formula everywhere, there's no fundamental need for every GPU to
independently STORE a full copy of this state.

ZeRO addresses this redundancy in THREE PROGRESSIVE STAGES, each sharding
more state across GPUs:
  - ZeRO STAGE 1: shards OPTIMIZER STATE across GPUs — each GPU holds
    only 1/N of the total optimizer state (momentum/variance), reducing
    memory by roughly the fraction optimizer state represents of total
    memory (often the LARGEST single contributor for Adam).
  - ZeRO STAGE 2: additionally shards GRADIENTS — each GPU only needs
    to hold the gradients for the PARAMETERS whose optimizer state it
    owns, further reducing memory.
  - ZeRO STAGE 3: additionally shards the MODEL PARAMETERS themselves —
    each GPU holds only 1/N of the actual model weights, gathering the
    full parameters ONLY momentarily (via AllGather, L07) when needed
    for a specific layer's forward/backward computation, then
    discarding them again — this is the most memory-efficient stage,
    approaching a MODEL-PARALLELISM-LIKE memory profile while retaining
    DATA PARALLELISM's simpler programming model (you don't manually
    restructure your model's code the way L05's tensor parallelism requires).

CPU/NVME OFFLOAD extends ZeRO further: optimizer state (or even model
parameters, in ZeRO-Infinity) can be offloaded to CPU RAM or even NVMe
SSD storage when GPU memory alone isn't sufficient — trading some
throughput (moving data between GPU and CPU/disk is slower than keeping
everything in GPU memory) for the ability to train MUCH larger models
than would otherwise fit, even on modest hardware.

PRODUCTION USE CASE:
A team training a model that doesn't fit in GPU memory with standard
DDP (L04) enables DeepSpeed's ZeRO Stage 2 — with ZERO CHANGES to their
model's actual architecture code (unlike L05's tensor parallelism, which
requires restructuring specific layers), simply wrapping their existing
training loop with DeepSpeed's configuration — and the SAME model now
fits comfortably, because optimizer state and gradients are sharded
across their 8 GPUs instead of each holding a full redundant copy.

COMMON MISTAKES:
- Reaching for ZeRO Stage 3 (or full CPU/NVMe offload) by default when
  a model already fits comfortably under Stage 1 or 2 — each additional
  stage/offload level trades away some throughput for memory savings;
  applying more aggressive sharding than actually needed leaves
  performance on the table for no memory benefit.
- Assuming ZeRO Stage 3's parameter sharding is equivalent to L05's
  tensor parallelism — they solve OVERLAPPING but distinct problems;
  ZeRO-3 shards parameters for MEMORY efficiency while still computing
  each layer's FULL operation (gathering full parameters temporarily),
  whereas tensor parallelism genuinely SPLITS the computation itself
  across GPUs permanently — the two can also be COMBINED, which is
  common in practice for the largest-scale training.
- Enabling CPU/NVMe offload without understanding the real throughput
  cost — offload trades memory capacity for speed; verifying the actual
  measured throughput impact (not assuming it based on theoretical
  bandwidth alone) is important before committing to an offload configuration.
"""

import textwrap


# ------------------------------------------------------------------
# 1. ZeRO stages — what's sharded at each level
# ------------------------------------------------------------------
ZERO_STAGES = {
    "ZeRO Stage 1": "Shards OPTIMIZER STATE only (momentum/variance for "
        "Adam) — often the single largest memory consumer, so this "
        "stage alone provides substantial savings with minimal added complexity.",
    "ZeRO Stage 2": "Additionally shards GRADIENTS — each GPU holds "
        "gradients only for the parameters whose optimizer state it owns.",
    "ZeRO Stage 3": "Additionally shards MODEL PARAMETERS themselves — "
        "the most memory-efficient, gathering full parameters "
        "MOMENTARILY (via AllGather, L07) only when a specific layer "
        "actually needs them for computation.",
}

# ------------------------------------------------------------------
# 2. Memory savings, quantified
# ------------------------------------------------------------------
def estimate_per_gpu_memory_gb(num_params_billions: float, num_gpus: int, zero_stage: int) -> dict:
    """
    A simplified illustration of ZeRO's memory savings — reusing the
    same memory-cost model established in LLM Quantization & Inference
    Notes L08 for full fine-tuning (weights + gradients + optimizer state).
    """
    params_bytes = num_params_billions * 1e9
    weights_gb = params_bytes * 2 / 1e9    # FP16 weights
    gradients_gb = params_bytes * 2 / 1e9   # FP16 gradients
    optimizer_gb = params_bytes * 4 * 2 / 1e9  # FP32 Adam moments (m and v)

    if zero_stage == 0:   # standard DDP — no sharding at all
        return {"weights": weights_gb, "gradients": gradients_gb, "optimizer": optimizer_gb,
                "total_per_gpu": weights_gb + gradients_gb + optimizer_gb}
    elif zero_stage == 1:
        return {"weights": weights_gb, "gradients": gradients_gb, "optimizer": optimizer_gb / num_gpus,
                "total_per_gpu": weights_gb + gradients_gb + optimizer_gb / num_gpus}
    elif zero_stage == 2:
        return {"weights": weights_gb, "gradients": gradients_gb / num_gpus, "optimizer": optimizer_gb / num_gpus,
                "total_per_gpu": weights_gb + gradients_gb / num_gpus + optimizer_gb / num_gpus}
    else:  # stage 3
        return {"weights": weights_gb / num_gpus, "gradients": gradients_gb / num_gpus,
                "optimizer": optimizer_gb / num_gpus,
                "total_per_gpu": (weights_gb + gradients_gb + optimizer_gb) / num_gpus}


def memory_savings_demo():
    num_params = 7   # a 7B parameter model
    num_gpus = 8
    for stage in [0, 1, 2, 3]:
        result = estimate_per_gpu_memory_gb(num_params, num_gpus, stage)
        label = "Standard DDP (no sharding)" if stage == 0 else f"ZeRO Stage {stage}"
        print(f"  {label}: {result['total_per_gpu']:.1f} GB per GPU")


# ------------------------------------------------------------------
# 3. Real DeepSpeed configuration and usage
# ------------------------------------------------------------------
DEEPSPEED_CONFIG_EXAMPLE = textwrap.dedent("""\
    // ds_config.json
    {
      "train_batch_size": 256,
      "fp16": { "enabled": true },
      "zero_optimization": {
        "stage": 2,
        "offload_optimizer": {
          "device": "cpu",       // offload optimizer state to CPU RAM
          "pin_memory": true       // pinned memory for faster CPU<->GPU transfer
        }
      },
      "optimizer": {
        "type": "AdamW",
        "params": { "lr": 1e-4 }
      }
    }
""")

DEEPSPEED_TRAINING_LOOP_EXAMPLE = textwrap.dedent("""\
    import deepspeed

    model = MyLargeModel()
    model_engine, optimizer, _, _ = deepspeed.initialize(
        model=model, config="ds_config.json",
    )

    for batch in dataloader:
        outputs = model_engine(batch)
        loss = compute_loss(outputs)
        model_engine.backward(loss)   # DeepSpeed handles the sharded
                                        # gradient computation/communication
                                        # internally, per the configured ZeRO stage
        model_engine.step()            # DeepSpeed handles the sharded
                                        # optimizer update internally

    # Notice: NO manual restructuring of the model's architecture code
    # was needed (unlike L05's tensor parallelism) — DeepSpeed's sharding
    # happens BENEATH the standard PyTorch model definition.
""")


if __name__ == "__main__":
    print("=== ZeRO stages ===")
    for stage, note in ZERO_STAGES.items():
        print(f"{stage}: {note}\n")

    print("=== Memory savings for a 7B model across 8 GPUs ===")
    memory_savings_demo()

    print()
    print(DEEPSPEED_CONFIG_EXAMPLE)
    print(DEEPSPEED_TRAINING_LOOP_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A team's 7B-parameter model training job fails with an out-of-memory
error under standard DDP on their 8x consumer-GPU node — enabling
DeepSpeed ZeRO Stage 2 (sharding gradients and optimizer state across
the 8 GPUs) reduces per-GPU memory from roughly 98GB (impossible on
their hardware) to about 30GB, fitting comfortably, with ZERO changes
to their actual model architecture code — purely a training-loop/
configuration change, exactly the kind of "unlock more scale on the
same hardware, without redesigning the model" result ZeRO is built to provide.
"""
