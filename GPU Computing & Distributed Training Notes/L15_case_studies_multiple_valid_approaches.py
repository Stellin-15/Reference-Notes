"""
WHAT: Four realistic large-scale training problems, each solved with
      THREE genuinely different, individually defensible approaches
      drawn from L01-L14 -- with an explicit comparison table and
      reasoning for why each answer is valid under different
      constraints.
WHY:  "Data parallel or model parallel," "DeepSpeed or plain DDP,"
      "how many GPUs" are all questions L01-L14 gave you real tools for,
      not one universal answer -- this lesson is about the decision
      process under real model-size and cluster constraints.
LEVEL: Capstone -- read after L01-L14.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L14's concepts.
"""

# ============================================================================
# CASE STUDY 1 — TRAINING A MODEL THAT DOESN'T FIT ON A SINGLE GPU'S
# MEMORY
# ============================================================================
#
# SETUP: a model's parameters, gradients, and optimizer states together
# exceed a single GPU's memory even at batch size 1 -- the team has 8
# GPUs available on one node.
#
# ------------------------------------------------------------------------
# APPROACH A: Tensor/model parallelism (L05) -- split individual layers'
# weight matrices across GPUs
# ------------------------------------------------------------------------
#   WHY VALID: per L05, this directly reduces the PER-GPU memory
#   footprint of the model's own parameters (each GPU holds only a
#   SLICE of each layer), the most direct fix for "the model itself
#   doesn't fit" specifically, and Megatron-style tensor parallelism is
#   well-established for exactly this scenario.
#   COST: per L05, tensor parallelism requires frequent, expensive
#   inter-GPU communication WITHIN a single forward/backward pass
#   (every layer needs its sliced outputs gathered/redistributed) --
#   this demands very high-bandwidth interconnect (NVLink, not just
#   PCIe) to avoid communication becoming the dominant bottleneck, a
#   real hardware-topology dependency, not just a software configuration
#   choice.
#
# ------------------------------------------------------------------------
# APPROACH B: DeepSpeed ZeRO Stage 3 (L08) -- partition parameters,
# gradients, AND optimizer states across GPUs, gathering full parameters
# only transiently when needed for computation
# ------------------------------------------------------------------------
#   WHY VALID: per L08, ZeRO-3 achieves memory reduction comparable to
#   (or exceeding) model parallelism's benefit while requiring FAR less
#   code restructuring -- it works with a largely standard model
#   definition (unlike tensor parallelism, which requires explicitly
#   splitting specific layers), making it a much lower-effort path to
#   fitting a too-large model across available GPUs.
#   COST: per L08, ZeRO-3's transient full-parameter gathering during
#   computation introduces its OWN communication overhead pattern
#   (different from tensor parallelism's, but real) -- and ZeRO-3
#   specifically (versus lighter ZeRO stages) can meaningfully increase
#   per-step wall-clock time relative to what data parallelism alone
#   would achieve if the model DID fit, a real throughput cost being
#   paid specifically to enable fitting at all.
#
# ------------------------------------------------------------------------
# APPROACH C: Pipeline parallelism (L06) -- split the model's LAYERS
# (not within-layer weights) across GPUs, each GPU owning a contiguous
# stage of the network, with micro-batches flowing through the pipeline
# ------------------------------------------------------------------------
#   WHY VALID: per L06, pipeline parallelism's communication pattern
#   (passing activations between adjacent pipeline stages) is
#   structurally LIGHTER-WEIGHT than tensor parallelism's per-layer
#   all-reduce pattern -- viable over LOWER-bandwidth interconnects
#   (even across multiple NODES, not just within one node) where tensor
#   parallelism would bottleneck badly.
#   COST: per L06, naive pipeline parallelism suffers from "bubble"
#   overhead -- GPUs sit idle waiting for their pipeline stage's turn,
#   especially with few micro-batches -- 1F1B scheduling (L06) mitigates
#   but doesn't eliminate this, and getting a good LAYER-TO-GPU split
#   (balancing compute time per stage) requires real tuning specific to
#   the model's architecture.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Interconnect requirement | Code restructuring effort | Communication overhead pattern |
#   |----------|--------------------------------|---------------------------------|---------------------------------------|
#   | A: tensor parallelism | High (needs NVLink-class) | High (explicit layer splitting) | Frequent, per-layer |
#   | B: DeepSpeed ZeRO-3 | Medium | Low (mostly automatic) | Transient full-parameter gathers |
#   | C: pipeline parallelism | Low (works across nodes) | Medium (stage partitioning) | Bubble overhead, inter-stage |
#   For a SINGLE node with strong NVLink (as stated: 8 GPUs, likely one
#   node), A or B are both reasonable; B is generally the lower-effort
#   starting point given far less code restructuring. C becomes the
#   right tool specifically once training needs to span MULTIPLE nodes
#   with weaker inter-node bandwidth than A's requirements assume.


# ============================================================================
# CASE STUDY 2 — DIAGNOSING POOR MULTI-GPU SCALING EFFICIENCY (4 GPUS
# GIVE ONLY ~2.2X SPEEDUP OVER 1 GPU, NOT CLOSE TO 4X)
# ============================================================================
#
# SETUP: a team scales DDP training from 1 to 4 GPUs and sees far less
# than linear speedup -- diagnosing the cause.
#
# ------------------------------------------------------------------------
# APPROACH A: Profile with Nsight Systems (L13) to find the actual
# bottleneck empirically before guessing
# ------------------------------------------------------------------------
#   WHY VALID: per L13, this is the methodologically correct FIRST step
#   -- poor scaling has multiple possible distinct causes (data loading
#   bottleneck, communication overhead, GPU underutilization from a
#   too-small per-GPU batch size), and profiling identifies WHICH one is
#   actually the culprit rather than guessing and potentially "fixing" a
#   problem that isn't the real bottleneck.
#   COST: profiling and correctly interpreting the results takes real
#   time and some genuine skill in reading a profiler's output -- a
#   team under time pressure may be tempted to skip straight to a guess-
#   based fix, and this approach alone doesn't fix anything, it just
#   diagnoses.
#
# ------------------------------------------------------------------------
# APPROACH B: Assume it's a data-loading bottleneck (a common, well-
# known cause) and increase DataLoader worker count / add prefetching,
# without profiling first
# ------------------------------------------------------------------------
#   WHY VALID: data-loading bottlenecks (the CPU-bound work of reading/
#   augmenting data not keeping up with the GPU's compute speed) ARE a
#   very common real-world cause of exactly this symptom, and this fix
#   is cheap and fast to try -- if it happens to be the actual cause,
#   this is the fastest path to a fix, no profiling overhead needed.
#   COST: if data loading ISN'T actually the bottleneck (e.g. the real
#   cause is NCCL communication overhead, L07, from a poor network
#   topology, or gradient synchronization overhead), this "fix" does
#   nothing, and the team has spent effort without diagnosing the ACTUAL
#   problem -- a classic case of treating a plausible-sounding guess as
#   if it were a confirmed diagnosis.
#
# ------------------------------------------------------------------------
# APPROACH C: Check the linear LR scaling rule (L04) was correctly
# applied, and verify NCCL is using the fastest available transport
# (NVLink/InfiniBand, not falling back to a slower path, L07)
# ------------------------------------------------------------------------
#   WHY VALID: per L04/L07, these are two SPECIFIC, well-known, easy-
#   to-silently-misconfigure causes -- a missed LR scaling adjustment
#   doesn't directly cause SLOW scaling per se, but a silent NCCL
#   fallback to a slower transport (e.g. falling back to Ethernet when
#   NVLink should be available, due to a misconfiguration) is a very
#   common, very real cause of exactly the described symptom, checkable
#   quickly via NCCL's own debug logging.
#   COST: this targets two SPECIFIC known failure modes -- if the actual
#   cause is something else entirely (e.g. a genuine data-loading
#   bottleneck, as in B), checking these two specific things won't find
#   it, the same "guessing among several plausible causes without a
#   general diagnostic process" limitation B has, just with different
#   specific guesses.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Diagnostic rigor | Speed to a (possibly wrong) fix | Risk of "fixing" the wrong thing |
#   |----------|------------------------|---------------------------------------|------------------------------------------|
#   | A: profile first | Highest | Slower (profiling overhead) | Lowest |
#   | B: assume data-loading bottleneck | None | Fastest, if correct | High, if wrong |
#   | C: check LR scaling + NCCL transport | Targeted, but still a guess | Fast, if correct | Medium (two specific guesses) |
#   A is the methodologically correct answer, and the profiling results
#   from A will typically POINT DIRECTLY at whether B or C's specific
#   hypothesis (or something else) is the actual cause -- B/C are
#   reasonable QUICK first guesses to try in parallel with kicking off
#   profiling, not substitutes for eventually confirming the real cause
#   via A if the quick guesses don't pan out.


# ============================================================================
# CASE STUDY 3 — CHOOSING A GPU-SHARING STRATEGY FOR A SHARED ML
# PLATFORM SERVING MANY SMALL TRAINING/INFERENCE JOBS
# ============================================================================
#
# SETUP: a shared internal ML platform runs many jobs that each only
# need a FRACTION of a modern GPU's compute/memory (small models,
# experimentation, inference) -- giving each job a full dedicated GPU
# wastes significant capacity.
#
# ------------------------------------------------------------------------
# APPROACH A: Multi-Instance GPU (MIG) partitioning (L12) -- hardware-
# level partitioning of a supported GPU into fixed-size, fully isolated
# instances
# ------------------------------------------------------------------------
#   WHY VALID: per L12, MIG provides HARD, hardware-enforced isolation
#   between jobs sharing the same physical GPU -- one job's workload
#   genuinely cannot affect another's performance or see its memory,
#   the strongest isolation guarantee of the options, valuable for a
#   genuinely multi-tenant platform with jobs from different teams/
#   trust levels.
#   COST: per L12, MIG partitions are FIXED-SIZE, decided at
#   partitioning time -- a job needing more than its allocated partition
#   size can't dynamically borrow idle capacity from another partition,
#   even if that partition is completely idle at that moment, a real
#   utilization inefficiency for bursty or highly variable workloads.
#
# ------------------------------------------------------------------------
# APPROACH B: Time-slicing GPU sharing (L12) -- multiple jobs share a
# GPU by taking turns, scheduled by the driver/Kubernetes device plugin
# ------------------------------------------------------------------------
#   WHY VALID: per L12, time-slicing allows jobs to use MORE than a
#   fixed partition's worth of compute when other jobs on the same GPU
#   are idle, generally achieving higher overall utilization for bursty,
#   variable workloads than MIG's fixed partitioning.
#   COST: per L12, time-slicing provides WEAKER isolation than MIG --
#   jobs share the SAME memory space (no hardware memory isolation), so
#   a memory-hungry job can genuinely affect co-scheduled jobs, and
#   performance can be less PREDICTABLE (a job's actual throughput
#   depends on what else happens to be scheduled on the same GPU at the
#   same time) -- a real concern for latency-sensitive inference
#   workloads sharing a GPU with unpredictable training jobs.
#
# ------------------------------------------------------------------------
# APPROACH C: No GPU sharing at all -- keep dedicated GPUs per job, but
# invest instead in better JOB SCHEDULING/BIN-PACKING (System Design
# Case Studies Notes L27) to more efficiently ASSIGN small jobs to
# appropriately-sized GPU allocations, minimizing idle capacity that way
# ------------------------------------------------------------------------
#   WHY VALID: sidesteps BOTH A's fixed-partition inflexibility and B's
#   isolation/predictability concerns entirely -- if the platform can
#   reliably PACK small jobs efficiently at the scheduling level (e.g.
#   running several small jobs' worth of aggregate work per physical
#   GPU-day via good queueing, rather than partitioning a single GPU at
#   a given moment), it gets good utilization without either sharing
#   mechanism's tradeoffs.
#   COST: doesn't help at all if MANY small jobs need to run
#   CONCURRENTLY (not just efficiently queued over time) — genuine
#   concurrent GPU-sharing needs (multiple jobs truly running
#   simultaneously on limited hardware, not just efficiently scheduled
#   one after another) aren't addressed by scheduling alone; this
#   approach solves a related but distinct problem (utilization over
#   TIME) than A/B (utilization at a given MOMENT via literal sharing).
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Isolation strength | Utilization for bursty workloads | Solves CONCURRENT small-job sharing |
#   |----------|-------------------------|-----------------------------------------|--------------------------------------------|
#   | A: MIG | Strongest | Lower (fixed partitions) | Yes |
#   | B: time-slicing | Weaker | Higher | Yes |
#   | C: scheduling/bin-packing, no sharing | N/A (dedicated GPUs) | Depends on queue depth | No (doesn't address true concurrency need) |
#   For a genuinely multi-tenant platform needing real isolation
#   (different teams, security boundaries), A; for a single team's
#   internal experimentation platform prioritizing raw utilization over
#   strict isolation, B; C is a complementary practice worth doing
#   regardless of A/B, since good scheduling helps utilization at any
#   sharing-strategy choice.


# ============================================================================
# CASE STUDY 4 — DECIDING WHETHER TO USE MIXED PRECISION TRAINING FOR A
# NEW MODEL
# ============================================================================
#
# SETUP: a team training a new model from scratch is deciding whether to
# use FP32 (standard full precision) or mixed precision (FP16/BF16 +
# FP32, L10) from the start.
#
# ------------------------------------------------------------------------
# APPROACH A: Standard FP32 training throughout, no mixed precision
# ------------------------------------------------------------------------
#   WHY VALID: the simplest, most numerically predictable option -- no
#   loss-scaling logic to configure/debug (L10), no risk of the
#   numerical instabilities mixed precision can occasionally introduce,
#   genuinely appropriate for a first working baseline before optimizing
#   for speed, or for a model architecture with known FP16-sensitivity
#   issues.
#   COST: per L10, this leaves REAL, substantial speed and memory
#   improvements unclaimed on any modern GPU with Tensor Core support --
#   for a large model or dataset, this can mean meaningfully longer
#   training time and higher memory usage (limiting achievable batch
#   size) for no offsetting benefit, once mixed precision has become
#   the well-established default for most architectures.
#
# ------------------------------------------------------------------------
# APPROACH B: Mixed precision with FP16 + dynamic loss scaling (L10)
# ------------------------------------------------------------------------
#   WHY VALID: per L10, this is the standard, well-established approach
#   for claiming Tensor Core speedups while dynamic loss scaling
#   specifically addresses FP16's narrow exponent range (the main
#   numerical risk), automatically adjusting the scale factor to avoid
#   gradient underflow/overflow -- broad framework support (PyTorch AMP)
#   makes this a low-effort, well-tested default for most architectures.
#   COST: per L10, FP16's narrow DYNAMIC RANGE (not just precision) can
#   still cause genuine numerical instability for SOME architectures/
#   loss functions even with loss scaling (certain attention patterns,
#   very large or very small intermediate activation magnitudes) --
#   requires actually monitoring for NaN/Inf losses during training and
#   potentially falling back to FP32 for specific problematic operations.
#
# ------------------------------------------------------------------------
# APPROACH C: Mixed precision with BF16 instead of FP16 (no loss scaling
# needed, L10)
# ------------------------------------------------------------------------
#   WHY VALID: per L10, BF16 has the SAME exponent range as FP32 (just
#   less mantissa precision) -- directly eliminates FP16's dynamic-range
#   instability risk and the NEED for loss-scaling logic entirely, a
#   simpler, more numerically robust mixed-precision option specifically
#   because of this range-matching property.
#   COST: per L10, BF16 requires GPU hardware support (available on
#   newer architectures, e.g. Ampere and later, but NOT on all GPUs a
#   team might be training on, particularly older hardware) -- and
#   BF16's REDUCED mantissa precision (versus FP16's) can occasionally
#   matter for specific numerically-sensitive computations where FP16's
#   extra precision (within its narrower range) would have been
#   adequate and BF16's coarser precision isn't.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Speed/memory benefit | Numerical stability risk | Hardware requirement |
#   |----------|---------------------------|---------------------------------|-----------------------------|
#   | A: FP32 only | None | Lowest | Any GPU |
#   | B: FP16 + loss scaling | High | Real (needs monitoring) | Tensor-Core-capable GPU |
#   | C: BF16 | High | Lower (no loss scaling needed) | Newer GPU architectures only |
#   C is the strongest default on hardware that supports it, specifically
#   because it captures most of B's benefit while removing FP16's
#   dynamic-range risk; B remains the necessary choice on older hardware
#   lacking BF16 support; A is reserved for an initial correctness-
#   focused baseline or architectures with confirmed severe mixed-
#   precision sensitivity.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
