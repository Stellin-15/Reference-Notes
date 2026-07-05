# ============================================================
# L12: Multi-Instance GPU (MIG) and GPU Sharing Strategies
# ============================================================
# WHAT: The mechanisms that let MULTIPLE workloads share ONE physical
#       GPU — MIG (Multi-Instance GPU, hardware-level partitioning on
#       NVIDIA A100/H100-class GPUs), time-slicing (software-level
#       sharing), and when each is appropriate — directly addressing
#       L11's "whole-GPU-only" Kubernetes scheduling limitation.
# WHY: L11 established that Kubernetes allocates GPUs as whole,
#      exclusive units by default — for INFERENCE workloads (often
#      needing much less than a full GPU's capacity per request) or
#      many small experimentation workloads, this wastes significant
#      GPU capacity. MIG and sharing strategies exist specifically to
#      recover that waste.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
MIG (Multi-Instance GPU), available on NVIDIA's A100/H100 and newer
data-center GPU generations, provides HARDWARE-LEVEL partitioning — a
single physical GPU is divided into up to 7 independent GPU INSTANCES,
each with its OWN dedicated memory, cache, and compute cores, fully
ISOLATED from the other instances at the hardware level (one instance's
workload cannot affect another's performance or see its memory — genuine
hardware fault/performance isolation, not just a software-level
convention). Each MIG instance appears to Kubernetes (via the device
plugin, L11) as its OWN separate, schedulable GPU resource — letting you
run, say, 7 SEPARATE inference workloads on ONE physical A100, each with
guaranteed, isolated resources, rather than one workload monopolizing
the entire GPU regardless of how little of its capacity that workload
actually uses.

TIME-SLICING is a SOFTWARE-level alternative (available on GPUs without
MIG hardware support, or when MIG's fixed partition sizes don't fit your
workload's needs): multiple workloads share ONE GPU by having the GPU
scheduler RAPIDLY SWITCH between them, giving each workload TIME-BASED
access to the FULL GPU in short bursts — unlike MIG's hardware
isolation, time-sliced workloads can experience PERFORMANCE INTERFERENCE
from each other (one workload consuming more of its time-slice than
expected affects others' effective throughput) and share memory access
patterns that MIG's dedicated-memory-per-instance design avoids entirely.

THE CHOICE between MIG, time-slicing, and simple whole-GPU allocation
(L11's default) depends on the workload: LARGE, memory/compute-hungry
TRAINING jobs generally want a WHOLE GPU (or several, for distributed
training, L04-L09) — partitioning would only hurt throughput for a
workload that can genuinely use the full GPU. SMALL, LATENCY-INSENSITIVE
INFERENCE workloads (many independent, small models, each needing only
a fraction of a GPU's capacity) are the classic MIG use case — hardware-
isolated partitions matching each workload's actual, smaller resource need.

PRODUCTION USE CASE:
A platform serving many small, independent inference endpoints (each a
different customer's fine-tuned model, individually low-traffic)
provisions each endpoint on its OWN MIG instance rather than a full
dedicated GPU per endpoint — dramatically improving GPU utilization
(one physical A100 serving 7 independent endpoints instead of 7
underutilized whole GPUs) while retaining the hardware-level isolation
guarantee that one customer's inference load spike cannot degrade
another customer's endpoint's latency.

COMMON MISTAKES:
- Applying MIG partitioning to a LARGE, genuinely GPU-hungry training
  job — this only reduces the available compute/memory per partition
  relative to the whole GPU, hurting throughput for a workload that
  could have used the FULL GPU productively; MIG is for workloads
  SMALLER than a full GPU's capacity, not a universal default.
- Using time-slicing when workloads have STRICT, mutually-independent
  latency/performance requirements — time-slicing's inherent
  performance interference between shared workloads can violate SLAs
  that MIG's true hardware isolation would have respected.
- Not accounting for MIG's FIXED PARTITION PROFILES (specific, pre-
  defined combinations of compute/memory fraction per instance, not
  arbitrary custom splits) — a workload needing a partition size that
  doesn't match any available MIG profile may need time-slicing or
  whole-GPU allocation instead.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Enabling and configuring MIG
# ------------------------------------------------------------------
MIG_SETUP_EXAMPLE = textwrap.dedent("""\
    # Enable MIG mode on a physical GPU (requires a reset)
    nvidia-smi -i 0 -mig 1

    # List available MIG PROFILES — fixed, pre-defined partition sizes
    # (e.g. "1g.5gb" = 1/7 of compute, 5GB of memory)
    nvidia-smi mig -lgip

    # Create MIG instances — e.g. splitting one A100 into 7 equal
    # "1g.5gb" instances, each independently schedulable:
    nvidia-smi mig -cgi 1g.5gb,1g.5gb,1g.5gb,1g.5gb,1g.5gb,1g.5gb,1g.5gb -C

    # Each instance now appears as its OWN device to the NVIDIA device
    # plugin (L11), schedulable in Kubernetes as an independent
    # nvidia.com/gpu resource — a pod requesting "1 GPU" actually
    # receives ONE MIG INSTANCE, not the whole physical card.
""")

# ------------------------------------------------------------------
# 2. MIG-aware Kubernetes device plugin configuration
# ------------------------------------------------------------------
MIG_K8S_CONFIG_EXAMPLE = textwrap.dedent("""\
    # The NVIDIA device plugin supports different MIG strategies:
    #   "none": MIG disabled, whole-GPU allocation only (L11's default)
    #   "single": all MIG instances on a node must be the SAME profile,
    #             exposed as a uniform nvidia.com/gpu resource count
    #   "mixed": DIFFERENT MIG profile sizes coexist, exposed as
    #             DISTINCT resource types (e.g. nvidia.com/mig-1g.5gb,
    #             nvidia.com/mig-2g.10gb) — pods request the SPECIFIC
    #             profile size they need.

    apiVersion: v1
    kind: Pod
    spec:
      containers:
        - name: inference-endpoint
          resources:
            limits:
              nvidia.com/mig-1g.5gb: 1   # requests exactly ONE small
                                           # MIG instance, not a full GPU
""")

# ------------------------------------------------------------------
# 3. Time-slicing configuration (the software-level alternative)
# ------------------------------------------------------------------
TIME_SLICING_CONFIG_EXAMPLE = textwrap.dedent("""\
    # NVIDIA device plugin ConfigMap enabling time-slicing — allows
    # MULTIPLE pods to share ONE physical GPU by time-based scheduling,
    # WITHOUT MIG's hardware partitioning (usable on GPUs lacking MIG
    # support, or when MIG's fixed profile sizes don't fit):
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: nvidia-device-plugin-config
    data:
      config.yaml: |
        version: v1
        sharing:
          timeSlicing:
            resources:
              - name: nvidia.com/gpu
                replicas: 4   # ONE physical GPU now appears as 4
                               # schedulable "replicas" — 4 pods can each
                               # request "1 GPU" and share the same
                               # physical hardware via time-based switching
""")

# ------------------------------------------------------------------
# 4. Decision framework — MIG vs time-slicing vs whole-GPU
# ------------------------------------------------------------------
SHARING_STRATEGY_DECISION = {
    "Whole GPU (L11 default)": "Large training jobs (L04-L09) or any "
        "workload that can productively use a FULL GPU's compute/memory.",
    "MIG": "Multiple SMALL, independent inference/experimentation "
        "workloads needing HARDWARE-LEVEL isolation (strict, mutual "
        "performance/fault independence) and available on MIG-capable "
        "hardware (A100/H100+).",
    "Time-slicing": "Multiple small workloads sharing older/non-MIG-"
        "capable hardware, OR workloads needing a partition size that "
        "doesn't match any available MIG profile — accepting some "
        "performance-interference risk in exchange for flexibility.",
}


if __name__ == "__main__":
    print(MIG_SETUP_EXAMPLE)
    print(MIG_K8S_CONFIG_EXAMPLE)
    print(TIME_SLICING_CONFIG_EXAMPLE)
    print("=== Sharing strategy decision framework ===")
    for strategy, guidance in SHARING_STRATEGY_DECISION.items():
        print(f"{strategy}: {guidance}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A platform serving dozens of small, independent customer-specific
fine-tuned model endpoints (each individually low-traffic, none needing
more than 1/7th of an A100's capacity) provisions them via MIG,
achieving roughly 7x better GPU utilization than one-endpoint-per-
whole-GPU would allow, while retaining hardware-level isolation
guaranteeing one customer's traffic spike cannot degrade another's
endpoint latency — a direct, measured cost reduction on the SAME
physical GPU fleet, purely from choosing the appropriate sharing
strategy for this specific, small-workload use case.
"""
