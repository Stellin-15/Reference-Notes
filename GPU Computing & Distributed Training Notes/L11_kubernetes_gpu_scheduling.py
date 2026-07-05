# ============================================================
# L11: Kubernetes GPU Scheduling — Device Plugins, Requests, Affinity
# ============================================================
# WHAT: How Kubernetes (this repo's Kubernetes Notes covers general
#       cluster orchestration) schedules and allocates GPU resources
#       SPECIFICALLY — the NVIDIA device plugin, GPU resource requests/
#       limits, and node affinity/taints for GPU-specific scheduling needs.
# WHY: A distributed training job (L04-L09) needs to actually RUN on a
#      cluster somewhere — Kubernetes is the dominant orchestrator for
#      this, but GPUs are NOT a resource type Kubernetes understands
#      natively out of the box; a DEVICE PLUGIN is required to expose
#      GPUs to the scheduler at all.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
Kubernetes NATIVELY understands CPU and memory as schedulable resources
— GPUs are NOT a built-in resource type at all. The NVIDIA DEVICE
PLUGIN (a DaemonSet running on every GPU-equipped node) is what makes
GPUs SCHEDULABLE: it discovers the GPUs physically present on each node
and ADVERTISES them to the Kubernetes API as a custom resource type
(`nvidia.com/gpu`), which pods can then REQUEST exactly like they
request CPU/memory.

GPU RESOURCE REQUESTS in Kubernetes are WHOLE-NUMBER ONLY by default —
unlike CPU (which can be requested fractionally, e.g. `0.5` cores), a
pod requests `nvidia.com/gpu: 1` (or 2, 4, etc.) and gets EXCLUSIVE
access to that many WHOLE GPUs; there is no native way to request "half
a GPU" without additional tooling (L12's MIG and time-slicing cover the
mechanisms that DO enable GPU sharing, since whole-GPU-only allocation
can badly under-utilize hardware for workloads that don't need a full GPU).

NODE AFFINITY AND TAINTS/TOLERATIONS are how you ensure GPU-requesting
pods actually LAND on GPU-equipped nodes (and, just as importantly,
that NON-GPU workloads DON'T accidentally get scheduled onto expensive
GPU nodes, wasting that capacity) — a common pattern TAINTS every
GPU node (marking it as requiring a specific TOLERATION to be scheduled
there at all) and uses NODE AFFINITY rules on GPU-requesting pods to
prefer/require those tainted nodes specifically.

MULTI-GPU POD SCHEDULING for distributed training (a single training
JOB needing, say, 8 pods each with 1 GPU, or fewer pods each with
multiple GPUs) typically uses a specialized OPERATOR — the KUBEFLOW
TRAINING OPERATOR (supporting PyTorchJob, TFJob custom resources) or
similar — rather than raw Kubernetes Deployments/Jobs, because
coordinating DDP's rank/world-size environment variables (L04) across
many pods, handling pod failures/restarts correctly for a distributed
job, and managing the pod-to-pod networking DDP requires is genuinely
non-trivial to hand-roll correctly with bare Kubernetes primitives.

PRODUCTION USE CASE:
A platform team's GPU cluster taints every GPU node with
`nvidia.com/gpu=true:NoSchedule`, ensuring only pods with an explicit
toleration for that taint can be scheduled there — combined with a
ResourceQuota limiting how many GPUs each team's namespace can request
simultaneously, preventing one team's large training job from starving
another team's GPU access entirely, directly analogous to this repo's
Event-Driven & Real-Time AI Systems Notes L08's per-tenant quota concept,
applied here to cluster-level GPU capacity instead of LLM API calls.

COMMON MISTAKES:
- Not tainting GPU nodes, allowing NON-GPU workloads to be scheduled
  onto them by the default scheduler (since they otherwise look like
  any other node with spare CPU/memory) — this wastes expensive GPU
  node capacity on workloads that never actually use the GPU at all.
- Requesting MORE GPUs per pod than a job actually uses, "just in case"
  — since Kubernetes GPU allocation is whole-number and exclusive, an
  over-requested pod holds GPUs completely idle that could have served
  another workload, directly wasting capacity (this is exactly the kind
  of gap MIG/sharing, L12, addresses when genuine partial-GPU needs exist).
- Hand-rolling distributed training pod coordination (rank assignment,
  master-address discovery, restart handling) instead of using an
  established operator (Kubeflow Training Operator) that has already
  solved these genuinely tricky coordination problems correctly.
"""

import textwrap


# ------------------------------------------------------------------
# 1. NVIDIA device plugin — making GPUs schedulable at all
# ------------------------------------------------------------------
DEVICE_PLUGIN_NOTE = textwrap.dedent("""\
    # The NVIDIA device plugin runs as a DaemonSet on every node —
    # deployed once per cluster, not something application teams manage:
    kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/main/deployments/static/nvidia-device-plugin.yml

    # Once running, GPU-equipped nodes advertise a NEW schedulable
    # resource, visible via:
    kubectl describe node gpu-node-1
    # Capacity:
    #   nvidia.com/gpu: 8    <- now a resource pods can REQUEST, just
    #                            like cpu/memory
""")

# ------------------------------------------------------------------
# 2. Pod GPU resource requests
# ------------------------------------------------------------------
GPU_POD_SPEC_EXAMPLE = textwrap.dedent("""\
    apiVersion: v1
    kind: Pod
    metadata:
      name: training-job
    spec:
      containers:
        - name: trainer
          image: my-training-image:latest
          resources:
            limits:
              nvidia.com/gpu: 2   # whole-number, EXCLUSIVE — no native
                                    # fractional GPU requests without
                                    # additional tooling (L12)
      tolerations:
        - key: "nvidia.com/gpu"
          operator: "Exists"
          effect: "NoSchedule"    # required to be scheduled onto a
                                    # TAINTED GPU node (see below)
      nodeSelector:
        gpu-type: "a100"           # a common LABEL-based way to target
                                    # a SPECIFIC GPU model, since different
                                    # training jobs often need specific hardware
""")

# ------------------------------------------------------------------
# 3. Tainting GPU nodes — keeping non-GPU workloads OFF expensive hardware
# ------------------------------------------------------------------
TAINT_EXAMPLE = textwrap.dedent("""\
    # Taint every GPU node — by default, NOTHING can be scheduled here
    # without an explicit toleration (as shown in the pod spec above).
    kubectl taint nodes gpu-node-1 nvidia.com/gpu=true:NoSchedule

    # A ResourceQuota limiting a namespace's TOTAL GPU consumption —
    # preventing one team from monopolizing shared cluster GPU capacity:
    apiVersion: v1
    kind: ResourceQuota
    metadata:
      name: team-a-gpu-quota
      namespace: team-a
    spec:
      hard:
        requests.nvidia.com/gpu: "16"   # this namespace can request at
                                          # most 16 GPUs total, across ALL
                                          # its pods combined
""")

# ------------------------------------------------------------------
# 4. Kubeflow Training Operator — coordinating distributed training pods
# ------------------------------------------------------------------
PYTORCHJOB_EXAMPLE = textwrap.dedent("""\
    apiVersion: kubeflow.org/v1
    kind: PyTorchJob
    metadata:
      name: distributed-training-job
    spec:
      pytorchReplicaSpecs:
        Master:
          replicas: 1
          template:
            spec:
              containers:
                - name: pytorch
                  image: my-training-image:latest
                  resources: { limits: { nvidia.com/gpu: 1 } }
        Worker:
          replicas: 7   # 7 workers + 1 master = 8 total pods, matching
                          # an 8-GPU distributed training job (L04's DDP)
          template:
            spec:
              containers:
                - name: pytorch
                  image: my-training-image:latest
                  resources: { limits: { nvidia.com/gpu: 1 } }

    # The operator AUTOMATICALLY sets RANK, WORLD_SIZE, and
    # MASTER_ADDR/MASTER_PORT environment variables inside each pod —
    # exactly the values torch.distributed.init_process_group() (L04)
    # needs — and handles pod failure/restart coordination for the
    # whole distributed job, none of which you'd want to hand-roll
    # yourself with bare Kubernetes Jobs/Deployments.
""")


if __name__ == "__main__":
    print(DEVICE_PLUGIN_NOTE)
    print(GPU_POD_SPEC_EXAMPLE)
    print(TAINT_EXAMPLE)
    print(PYTORCHJOB_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A platform team runs a shared GPU cluster across multiple ML teams using
the Kubeflow Training Operator for all distributed training jobs (no
hand-rolled pod coordination), node taints ensuring only GPU-toleration-
bearing pods land on expensive GPU nodes, and per-namespace
ResourceQuotas capping each team's simultaneous GPU consumption — a
single team's large distributed training job cannot inadvertently starve
another team's smaller job of GPU access, and the operator handles a
worker pod's unexpected restart mid-training without a human needing to
manually reconstruct the distributed job's rank/coordination state.
"""
