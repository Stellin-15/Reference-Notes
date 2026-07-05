# ============================================================
# L14: ROCm and Hardware Alternatives — Capstone: Choosing a GPU Stack
# ============================================================
# WHAT: AMD's ROCm platform as an alternative to NVIDIA's CUDA ecosystem
#       (everything covered in L01-L13), portability considerations for
#       code written against CUDA, and a capstone decision framework for
#       choosing a GPU training/inference stack given real constraints.
# WHY: Every prior lesson in this domain assumed NVIDIA/CUDA — the
#      overwhelmingly dominant choice for ML today, but not the ONLY
#      one. Understanding ROCm and the portability question matters both
#      for organizations with AMD hardware and for writing code that
#      isn't unnecessarily locked to one vendor.
# LEVEL: Capstone
# ============================================================

"""
CONCEPT OVERVIEW:
ROCm (Radeon Open Compute) is AMD's answer to CUDA — an open-source GPU
computing platform including HIP (Heterogeneous-compute Interface for
Portability, a CUDA-like C++ API), and AMD's own equivalents to cuDNN/
cuBLAS (MIOpen, rocBLAS) and NCCL (RCCL) — every major concept from
L01-L13 (SMs/compute units, kernel launches, collective communication,
mixed precision) has a ROCm/AMD-hardware analog, even where the exact
terminology or specific hardware characteristics differ.

HIP'S PORTABILITY STORY: HIP is DELIBERATELY designed to be
SYNTACTICALLY VERY CLOSE to CUDA — AMD provides a conversion tool
(`hipify`) that translates much CUDA C++ code to HIP automatically,
and HIP code can often compile for BOTH AMD (via ROCm) and NVIDIA (via
CUDA, using HIP as a thin wrapper) targets from the SAME source — a
genuine attempt at avoiding vendor lock-in at the LOW-LEVEL kernel-code
level. In practice, though, the ECOSYSTEM MATURITY GAP is real and
significant: PyTorch and TensorFlow both support ROCm, but the DEPTH of
testing, the availability of pre-built optimized kernels for cutting-
edge model architectures, and community troubleshooting resources remain
considerably richer for CUDA — this is an ECOSYSTEM reality, not a
fundamental technical limitation of ROCm's design.

THE PRACTICAL DECISION for most teams today: CUDA/NVIDIA remains the
DEFAULT choice given its ecosystem maturity, UNLESS a specific,
concrete reason favors AMD/ROCm — cost (AMD GPUs can offer better
raw compute-per-dollar in some configurations), an organization's
EXISTING AMD hardware investment (e.g. some large-scale HPC/national
lab deployments are AMD-based), or a specific vendor
partnership/procurement constraint. Choosing ROCm today generally means
accepting SOME additional engineering friction (occasionally needing to
work around library gaps, potentially less mature debugging tooling)
in exchange for whatever the specific motivating benefit is — a real,
honest tradeoff, not a decision to make purely on principle.

PRODUCTION USE CASE:
A national laboratory's supercomputing cluster, procured with AMD MI-
series GPUs (a procurement decision made independently of ML-specific
considerations, driven by broader HPC cost/performance/contract
factors), runs PyTorch workloads via ROCm — the team accepts some extra
engineering effort porting a few custom CUDA kernels to HIP and
occasionally waiting longer for a brand-new model architecture's
optimized kernels to appear in ROCm-compatible form, a real, deliberate
tradeoff justified by the hardware they already have, not one they'd
necessarily choose if starting from a blank slate with unlimited hardware options.

COMMON MISTAKES:
- Assuming HIP's syntactic similarity to CUDA means a straightforward,
  zero-friction port for ANY existing CUDA codebase — `hipify` handles
  much boilerplate automatically, but performance-critical, hand-tuned
  CUDA kernels (especially anything using CUDA-specific intrinsics or
  Tensor-Core-specific instructions, L01) often need genuine manual
  rework, not just automated translation.
- Choosing AMD/ROCm purely to "avoid vendor lock-in" as an abstract
  principle, without a concrete, weighed cost/benefit specific to the
  actual project — the ecosystem maturity gap is real and has genuine
  practical engineering cost; this tradeoff should be made deliberately,
  not by default.
- Not periodically re-evaluating this choice as the ecosystem evolves —
  ROCm's maturity gap has been NARROWING over time; a decision made
  against ROCm several years ago may be worth revisiting rather than
  assumed to be permanently settled.
"""

import textwrap
from dataclasses import dataclass


# ------------------------------------------------------------------
# 1. HIP — CUDA-to-portable-C++ conversion
# ------------------------------------------------------------------
HIP_COMPARISON_EXAMPLE = textwrap.dedent("""\
    // CUDA
    __global__ void vector_add(const float* a, const float* b, float* out, int n) {
        int idx = blockIdx.x * blockDim.x + threadIdx.x;
        if (idx < n) out[idx] = a[idx] + b[idx];
    }
    vector_add<<<blocks, threads>>>(d_a, d_b, d_out, n);

    // HIP — DELIBERATELY near-identical syntax, mostly a search/replace
    // of API prefixes (cuda* -> hip*) for straightforward kernels:
    __global__ void vector_add(const float* a, const float* b, float* out, int n) {
        int idx = hipBlockIdx_x * hipBlockDim_x + hipThreadIdx_x;
        if (idx < n) out[idx] = a[idx] + b[idx];
    }
    hipLaunchKernelGGL(vector_add, blocks, threads, 0, 0, d_a, d_b, d_out, n);

    # The `hipify` tool automates this translation for many CUDA codebases:
    hipify-perl cuda_source.cu > hip_source.cpp
""")

# ------------------------------------------------------------------
# 2. PyTorch on ROCm — the same high-level API, different backend
# ------------------------------------------------------------------
PYTORCH_ROCM_NOTE = textwrap.dedent("""\
    import torch
    print(torch.cuda.is_available())   # returns True on ROCm too —
                                          # PyTorch's ROCm build presents
                                          # the SAME "cuda" device API,
                                          # for application-code compatibility

    model = MyModel().to("cuda")   # works IDENTICALLY whether the
                                     # underlying hardware is NVIDIA (via
                                     # CUDA) or AMD (via ROCm) — most
                                     # STANDARD PyTorch model code requires
                                     # ZERO changes to run on either.

    # The friction shows up specifically for:
    #   - Custom CUDA kernels (L02) written in raw CUDA C++, not
    #     PyTorch's standard ops — these need HIP porting
    #   - Cutting-edge model architectures whose optimized kernels
    #     (via cuDNN/custom Triton kernels) may lag in ROCm-compatible
    #     availability compared to day-one CUDA support
""")

# ------------------------------------------------------------------
# 3. Capstone decision framework — choosing a GPU stack
# ------------------------------------------------------------------
@dataclass
class StackDecisionFactor:
    factor: str
    favors_cuda_nvidia: str
    favors_rocm_amd: str


DECISION_FACTORS = [
    StackDecisionFactor(
        "Ecosystem maturity / library support",
        "Default choice — broadest, deepest, most battle-tested support "
        "across every framework/library covered in this domain",
        "Narrowing gap, but real friction remains for cutting-edge "
        "architectures or custom kernel work",
    ),
    StackDecisionFactor(
        "Existing hardware investment",
        "If you already own NVIDIA hardware, switching stacks has real cost",
        "If you already own AMD hardware (e.g. a specific HPC procurement), "
        "ROCm avoids re-purchasing hardware purely for CUDA compatibility",
    ),
    StackDecisionFactor(
        "Cost per unit of compute",
        "Often has an ecosystem-maturity premium reflected in pricing/availability",
        "Can offer more favorable compute-per-dollar in specific "
        "configurations — worth a concrete, current-market comparison, not assumption",
    ),
    StackDecisionFactor(
        "Custom kernel development needs (L02-L03)",
        "The most mature toolchain (Nsight, L13; cuDNN/cuBLAS, L03) for "
        "deep, hand-tuned kernel work",
        "HIP's portability is genuine, but expect more manual work for "
        "anything beyond straightforward, `hipify`-translatable kernels",
    ),
]


def print_decision_framework():
    for factor in DECISION_FACTORS:
        print(f"{factor.factor}:")
        print(f"  Favors CUDA/NVIDIA: {factor.favors_cuda_nvidia}")
        print(f"  Favors ROCm/AMD: {factor.favors_rocm_amd}\n")


# ------------------------------------------------------------------
# 4. Full domain recap
# ------------------------------------------------------------------
DOMAIN_RECAP = {
    "L01-L03: GPU fundamentals": "Architecture, raw CUDA programming, "
        "and WHY vendor libraries (cuDNN/cuBLAS) beat hand-written kernels for standard ops.",
    "L04-L06: Parallelism strategies": "Data parallelism (replicate the "
        "model), tensor/model parallelism (split it), pipeline "
        "parallelism (split it, keep every GPU busy via micro-batching).",
    "L07-L09: The communication layer": "NCCL's actual collective "
        "operations underlying every strategy above, and DeepSpeed/"
        "Horovod as the frameworks implementing these strategies for you.",
    "L10: Numerical precision at scale": "Mixed precision and loss "
        "scaling, and how they interact with distributed gradient synchronization.",
    "L11-L12: Cluster-level scheduling": "Kubernetes GPU scheduling, and "
        "MIG/time-slicing for sharing GPUs across smaller workloads.",
    "L13: Measurement": "Nsight Systems/Compute — verifying every "
        "theoretical optimization above with actual, measured behavior.",
    "L14 (this lesson): Hardware choice": "CUDA/NVIDIA as the ecosystem-"
        "mature default, ROCm/AMD as a real, deliberate alternative "
        "given the right constraints.",
}


if __name__ == "__main__":
    print(HIP_COMPARISON_EXAMPLE)
    print(PYTORCH_ROCM_NOTE)
    print("=== Capstone decision framework ===")
    print_decision_framework()

    print("=== Full domain recap ===")
    for phase, summary in DOMAIN_RECAP.items():
        print(f"{phase}: {summary}\n")

"""
FINAL CONTEXT:
The measure of having internalized this domain isn't being able to name
every tool (DeepSpeed, NCCL, ROCm) — it's being able to look at a real
distributed training performance problem, know WHICH layer to
investigate first (Nsight Systems' broad timeline before Nsight
Compute's kernel deep-dive, per L13), and understand WHY a specific
parallelism strategy (L04-L06) or GPU-sharing approach (L12) fits a
given workload's actual constraints — with the hardware-choice question
(this lesson) as the foundational, occasionally-revisited decision
everything else in the domain builds on top of.
"""
