# ============================================================
# L09: Horovod and Distributed Training Framework Alternatives
# ============================================================
# WHAT: Horovod's ring-allreduce-based, framework-agnostic approach to
#       distributed training (originally built at Uber), and how it
#       compares to PyTorch's native DDP (L04) and DeepSpeed (L08) —
#       when each framework's specific design still matters today.
# WHY: L04 and L08 covered PyTorch-native distributed training tools.
#      Horovod represents a DIFFERENT design philosophy (framework-
#      agnostic, works across PyTorch/TensorFlow/MXNet with the SAME
#      API) worth understanding both for legacy systems still using it
#      and for the cross-framework consistency it offers.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
HOROVOD's core design goal was FRAMEWORK-AGNOSTICISM: the SAME Horovod
API wraps a training loop whether the underlying model is written in
TensorFlow, PyTorch, or MXNet — achieved by implementing the actual
distributed communication logic (built on the same ring-AllReduce
principles covered in L07, historically Horovod's own contribution that
popularized ring-AllReduce for deep learning specifically, predating
PyTorch's own DDP) as a SEPARATE library that INTERCEPTS gradient
computation regardless of which framework produced it.

This framework-agnostic design was HISTORICALLY significant: before
PyTorch's DistributedDataParallel matured into today's well-optimized,
NCCL-backed implementation, Horovod was often the MORE performant and
easier-to-use option, especially for teams running heterogeneous
model codebases across multiple frameworks who wanted ONE consistent
distributed training approach rather than learning each framework's own
native distributed API separately.

TODAY, for PURE PYTORCH codebases, PyTorch's own DDP (L04) has largely
closed the performance/ergonomics gap that originally motivated
Horovod's adoption, and DDP benefits from being maintained IN-TREE by
the same team developing PyTorch itself (tighter integration, faster
adoption of new PyTorch features). Horovod REMAINS relevant specifically
for: organizations with EXISTING Horovod-based infrastructure/expertise
(a real, common situation — migrating a large, working distributed
training codebase has real cost, independent of whether a "better"
option exists today), and organizations genuinely running MIXED
TensorFlow/PyTorch workloads wanting one consistent distributed training
approach across both.

PRODUCTION USE CASE:
An organization with a multi-year-old TensorFlow-based training
pipeline, already deeply integrated with Horovod, continues using it
rather than migrating to a PyTorch-native ecosystem purely because
"PyTorch is more popular now" — the actual migration cost (retraining
the team, rewriting substantial infrastructure, re-validating training
reproducibility) outweighs Horovod's now-narrower performance/ergonomics
gap versus modern PyTorch DDP for their SPECIFIC, working, TensorFlow-based system.

COMMON MISTAKES:
- Assuming Horovod is universally "outdated" and should always be
  migrated away from for new projects — for a PURE, NEW PyTorch project,
  DDP (L04) is generally the more natural default today, but this
  doesn't retroactively make Horovod a poor CHOICE for organizations
  with existing investment or genuine cross-framework needs.
- Migrating a working, well-understood Horovod-based training pipeline
  to a different framework purely based on general industry trend/
  popularity, without a concrete, measured performance or
  maintainability problem the migration would actually solve.
- Not recognizing that Horovod's CORE algorithmic contribution
  (popularizing ring-AllReduce for deep learning, L07) is now
  effectively STANDARD practice, implemented natively in NCCL/PyTorch
  DDP too — the underlying communication algorithm isn't a Horovod-
  exclusive advantage anymore, even where Horovod itself remains in use.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Horovod's framework-agnostic API
# ------------------------------------------------------------------
HOROVOD_PYTORCH_EXAMPLE = textwrap.dedent("""\
    import horovod.torch as hvd
    import torch

    hvd.init()
    torch.cuda.set_device(hvd.local_rank())

    model = MyModel().cuda()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-4 * hvd.size())  # linear
                                                                              # scaling, L04

    # Horovod's DistributedOptimizer wraps a STANDARD optimizer, adding
    # AllReduce-based gradient synchronization — conceptually similar to
    # what DDP does, but implemented as a Horovod-specific layer that
    # would work IDENTICALLY if the underlying model were TensorFlow instead.
    optimizer = hvd.DistributedOptimizer(optimizer, named_parameters=model.named_parameters())

    hvd.broadcast_parameters(model.state_dict(), root_rank=0)   # sync initial weights

    for batch in dataloader:
        optimizer.zero_grad()
        loss = compute_loss(model(batch))
        loss.backward()
        optimizer.step()   # AllReduce happens here, via Horovod's wrapper

    # Launch: horovodrun -np 8 -H localhost:8 python train.py
""")

HOROVOD_TENSORFLOW_EXAMPLE = textwrap.dedent("""\
    import horovod.tensorflow as hvd
    import tensorflow as tf

    hvd.init()

    # The SAME Horovod CONCEPTS (init, DistributedOptimizer-equivalent,
    # broadcast_parameters-equivalent) apply here, in TensorFlow — this
    # cross-framework API CONSISTENCY was Horovod's central value
    # proposition, letting an organization run BOTH TF and PyTorch
    # distributed training with one shared mental model and one shared
    # underlying communication library.
    optimizer = tf.keras.optimizers.Adam(1e-4 * hvd.size())
    optimizer = hvd.DistributedOptimizer(optimizer)
""")

# ------------------------------------------------------------------
# 2. Framework comparison — when each still makes sense
# ------------------------------------------------------------------
FRAMEWORK_COMPARISON = {
    "PyTorch DDP (L04)": "The natural default for NEW, pure-PyTorch "
        "projects — in-tree maintenance, tightest integration with new "
        "PyTorch features, generally matches or exceeds Horovod's "
        "performance today.",
    "Horovod": "Framework-agnostic (PyTorch/TensorFlow/MXNet, one "
        "consistent API) — remains the right choice for organizations "
        "with EXISTING Horovod investment or genuine cross-framework "
        "training needs, less compelling as a NEW default for pure-PyTorch work.",
    "DeepSpeed (L08)": "Adds ZeRO memory-sharding and pipeline/tensor "
        "parallelism integration ON TOP of PyTorch — the right choice "
        "when memory efficiency at very large model scale is the "
        "primary driving concern, beyond what plain DDP/Horovod address.",
}


if __name__ == "__main__":
    print(HOROVOD_PYTORCH_EXAMPLE)
    print(HOROVOD_TENSORFLOW_EXAMPLE)
    print("=== Framework comparison ===")
    for framework, note in FRAMEWORK_COMPARISON.items():
        print(f"{framework}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A research organization running BOTH a legacy TensorFlow-based
recommendation model pipeline and newer PyTorch-based vision models
standardizes on Horovod specifically to give their infrastructure team
ONE distributed-training operational model (one launcher, one set of
monitoring/debugging practices) across both frameworks, rather than
maintaining separate operational expertise for PyTorch DDP AND a
TensorFlow-native distributed strategy — a deliberate, still-valid
reason to choose Horovod today, distinct from simply defaulting to
whatever's currently most discussed for new, single-framework projects.
"""
