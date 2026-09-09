# GPU Computing & Distributed Training — Principal Engineer Deep Dive

Companion to L01-L14. Narrative depth, then a comprehensive common-to-
uncommon reference.


## Why GPUs Suit Deep Learning — The Actual Architectural Reason

**Beyond the lesson**: A CPU core is optimized for low-LATENCY execution
of a single instruction stream (deep pipelines, branch prediction,
large caches) — a GPU trades all of that away for massive THROUGHPUT via
thousands of simpler cores executing the SAME instruction across many
data elements simultaneously (SIMT — Single Instruction, Multiple
Threads). Matrix multiplication (the core operation of every neural
network layer) is embarrassingly parallel in exactly this way — each
output element is an independent dot product — which is why GPUs achieve
orders-of-magnitude higher throughput for this specific workload despite
each individual GPU core being far weaker than a CPU core. Tensor Cores
(specialized hardware units on modern NVIDIA GPUs) push this further,
performing an entire small matrix-multiply-accumulate operation in
hardware in one step, specifically because that exact operation pattern dominates deep learning workloads.

**Worked example**: Warp divergence — a GPU executes threads in groups
called WARPS (32 threads on NVIDIA hardware) that must execute the SAME
instruction in lockstep; if a conditional branch inside a kernel causes
different threads within a warp to take DIFFERENT paths, the warp must
execute BOTH paths sequentially (masking off the threads that don't
apply to each path) — a real, significant performance cliff for
GPU code with heavily data-dependent branching, and a genuine reason
GPU-friendly algorithms are often restructured to minimize per-thread
conditional divergence even at the cost of some redundant computation.

**Interview Q&A**:
- *Q: Why does batch size affect GPU utilization so dramatically for the SAME model?* A: Small batches don't provide enough parallel work to fill all of a GPU's compute units and hide memory-access latency — the GPU sits partially idle waiting on memory transfers between compute bursts; larger batches provide more independent work to overlap with memory latency, better saturating the hardware — this is the same underlying "memory-bound vs compute-bound" tradeoff discussed in the LLM Quantization & Inference deep dive, applicable to training as well as inference.


## NCCL & the AllReduce Operation — What Actually Synchronizes Gradients

**Beyond the lesson**: In data-parallel distributed training (DDP, see
ML Frameworks deep dive), every GPU computes gradients on its own data
shard, and these gradients must be AVERAGED across all GPUs before the
optimizer step — this is an ALLREDUCE operation (every participant ends
up with the same, combined result). NCCL implements this using a
RING-ALLREDUCE algorithm specifically because its communication cost
scales with the DATA SIZE, not the NUMBER OF GPUs — each GPU only
communicates with its two ring neighbors, passing partial sums around the
ring, achieving near-optimal bandwidth utilization regardless of how many
GPUs participate — a genuinely elegant algorithmic property that's WHY
distributed training scales as well as it does across many GPUs, not just an implementation detail.

**Interview Q&A**:
- *Q: Why does distributed training throughput sometimes scale sub-linearly (8 GPUs giving less than 8x speedup) even with a well-implemented AllReduce?* A: Communication overhead doesn't fully disappear — network bandwidth between nodes (versus the much faster NVLink/interconnect WITHIN a single node) becomes a real bottleneck at multi-node scale, and this is exactly why techniques like gradient compression, larger per-GPU batch sizes (amortizing communication cost over more compute), and gradient accumulation exist — to keep the communication-to-computation ratio favorable as GPU count grows.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### GPU hardware landscape
- **NVIDIA H100/A100/consumer RTX series** — the dominant training/
  inference hardware; H100's Transformer Engine specifically accelerates
  the exact matrix-multiply patterns Transformer architectures use.
- **AMD MI300 series (ROCm)** — the primary alternative ecosystem (see
  GPU Computing L14) — genuinely improving but still has real software-
  ecosystem-maturity gaps versus CUDA's years of accumulated tooling/library support.
- **Google TPUs** — purpose-built ASICs (not general-purpose GPUs) for
  exactly the matrix-multiply-heavy workload deep learning needs — only
  accessible via Google Cloud, tightly integrated with JAX/TensorFlow (see ML Frameworks deep dive).
- **Cloud GPU rental economics** — spot/preemptible GPU instances (see
  Cloud Platforms deep dive's spot-instance coverage) are a genuinely
  significant cost lever for training workloads that can checkpoint and resume, given GPU instance pricing's steep premium over general compute.

### Parallelism strategies, precisely distinguished
- **Data parallelism (DDP)** — same model, different data shards per GPU
  — the simplest, most common strategy when the model fits on one GPU.
- **Tensor parallelism** — splits INDIVIDUAL layers' weight matrices
  across GPUs (Megatron-style) — needed when a single layer's weights
  don't fit on one GPU, requires fast interconnect (NVLink) between
  participating GPUs due to the FREQUENT communication needed within each layer's forward/backward pass.
- **Pipeline parallelism** — splits the model's LAYERS across GPUs (GPU 1
  has layers 1-10, GPU 2 has layers 11-20) — introduces "bubble" overhead
  (idle time while later-stage GPUs wait for earlier stages) that
  1F1B (one-forward-one-backward) scheduling specifically minimizes versus naive sequential scheduling.
- **3D parallelism** — combining data + tensor + pipeline parallelism
  simultaneously — the actual strategy behind training the largest
  modern models, since no single parallelism strategy alone scales to
  models with hundreds of billions of parameters across thousands of GPUs.

### Memory optimization at scale
- **DeepSpeed ZeRO stages** — Stage 1 partitions optimizer states across
  GPUs; Stage 2 additionally partitions gradients; Stage 3 additionally
  partitions the MODEL PARAMETERS themselves — each stage trades more
  communication overhead for more memory savings, letting progressively
  larger models train on the same GPU memory budget.
- **CPU/NVMe offloading** — ZeRO-Infinity and similar techniques offload
  optimizer states/parameters to CPU RAM or even NVMe storage when GPU
  memory is fully exhausted — dramatically slower per-access but enables
  training models that simply wouldn't fit in aggregate GPU memory otherwise.


## NICHE BUT REAL

- **Kubernetes GPU scheduling nuances** (see also Kubernetes Notes) —
  device plugins expose GPUs as a schedulable resource, but naive
  whole-GPU allocation wastes capacity for workloads not needing a full
  GPU — **MIG (Multi-Instance GPU)** hardware-partitions a single
  physical GPU into several fully-isolated smaller GPUs; **time-slicing**
  software-shares one GPU across multiple pods without hardware
  isolation — genuinely different isolation/performance tradeoffs worth distinguishing precisely.
- **Nsight Systems/Compute profiling** — NVIDIA's profiling tools reveal
  exactly where GPU time goes (kernel execution, memory transfer,
  idle/stall time) — the standard diagnostic tool for answering "why
  isn't my training loop actually GPU-bound" precisely, rather than guessing.
- **Gradient accumulation as a memory/batch-size lever** — accumulating
  gradients across several smaller forward/backward passes before a
  single optimizer step SIMULATES a larger effective batch size without
  needing the memory a true larger batch would require — a real, common
  technique when the desired batch size doesn't fit in available GPU memory at once.
- **Checkpoint sharding for huge models** — saving/loading a model
  checkpoint that's sharded across many GPUs (ZeRO Stage 3, tensor-
  parallel splits) requires genuinely careful orchestration to
  reconstruct or re-shard correctly, especially when RESUMING training
  on a different number of GPUs than the checkpoint was originally saved
  with — a real, non-trivial distributed-training-infrastructure engineering challenge.
