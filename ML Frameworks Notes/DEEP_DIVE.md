# ML Frameworks — Principal Engineer Deep Dive

Companion to L01-L08. Narrative depth, then a comprehensive common-to-
uncommon reference on the practical framework ecosystem.


## PyTorch's Dynamic Graph, and Why It Won

**Beyond the lesson**: PyTorch's defining early advantage over TensorFlow
1.x was a DYNAMIC computation graph (define-by-run) — the graph is built
as your Python code actually executes, letting you use normal Python
control flow (`if`/`for` loops) directly in model logic, with immediate,
debuggable errors at the exact line something went wrong. TensorFlow 1.x's
STATIC graph (define-then-run — build the entire graph first, then feed
data through a session) made debugging genuinely harder (errors surfaced
during graph EXECUTION, often far from their root cause) but enabled
whole-graph optimization before any execution. TensorFlow 2.x's eager
mode adopted PyTorch's dynamic approach as the default, effectively
conceding this exact debuggability argument — worth knowing this
history precisely since "why did PyTorch win research/most new
production work" is a genuinely common ML-systems interview question with a real, specific technical answer.

**Worked example**: `torch.compile` (PyTorch 2.0+) reconciles both
worlds — write normal dynamic, eager PyTorch code, and `torch.compile`
traces/optimizes it into a static graph BEHIND THE SCENES for
production-speed execution, without giving up the dynamic-graph
development experience — a real, significant recent advance closing
PyTorch's historical performance gap versus statically-compiled alternatives.

**Interview Q&A**:
- *Q: Why would a production inference server still convert a PyTorch model to ONNX or TorchScript rather than serving raw PyTorch directly?* A: Removing the Python interpreter and PyTorch's dynamic-graph overhead from the serving hot path — ONNX/TorchScript produce a static, optimized graph representation that can run in lower-overhead runtimes (ONNX Runtime, TensorRT) without Python's GIL/interpreter overhead, a genuinely significant latency/throughput improvement for high-volume production inference.


## Distributed Training Strategy Selection

**Beyond the lesson**: DDP (DistributedDataParallel, see L05) replicates
the FULL model on every GPU and only synchronizes GRADIENTS — this works
great until the model itself doesn't fit on one GPU. At that point, the
choice isn't "DDP vs nothing" — it's a genuinely different family of
techniques (see GPU Computing deep dive for the full treatment): model/
tensor parallelism splits the model's LAYERS/WEIGHTS across GPUs; DeepSpeed
ZeRO partitions optimizer states/gradients/parameters across GPUs while
still doing data-parallel-style training — knowing WHICH constraint
(model too big vs data too big vs both) determines which strategy applies
is a real, practical distributed-training-engineering skill distinct from
just knowing each technique exists in isolation.

**Interview Q&A**:
- *Q: Training crashes with a CUDA out-of-memory error only during the OPTIMIZER STEP, not the forward/backward pass. What does that suggest?* A: Optimizer states (Adam keeps first and second moment estimates PER PARAMETER, doubling+ the memory needed beyond just the gradients themselves) are a real, often-underestimated memory cost — ZeRO stage 1 (partition optimizer states across GPUs) is the direct fix for exactly this failure mode, distinct from gradient checkpointing (which addresses ACTIVATION memory during the forward/backward pass instead).


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Framework ecosystem, precisely positioned
- **PyTorch** — dominant in research and increasingly production;
  Hugging Face's `transformers` library is built on it, cementing its
  dominance for anything LLM/NLP-adjacent.
- **TensorFlow/Keras** — still common in some large enterprises with
  legacy investment, and genuinely strong for production deployment
  tooling (TF Serving, TFLite for mobile/edge) that predates PyTorch's
  equivalent tooling maturity by years.
- **JAX** — functional, composable transformations (`grad`, `vmap`,
  `jit`) built around NumPy-like syntax — the choice for cutting-edge
  research wanting fine-grained control over automatic differentiation
  and genuinely excellent TPU support, used heavily inside Google/DeepMind's own research.
- **scikit-learn** — still the standard for classical ML (see Classical
  ML Theory deep dive) — its consistent `fit`/`predict`/`transform` API
  design pattern is genuinely influential, copied by many other libraries' APIs.

### Model serving & production deployment
- **TorchServe / TensorFlow Serving** — the framework-native production
  serving solutions, handling model versioning, batching, and REST/gRPC
  endpoints out of the box.
- **ONNX Runtime** — a framework-agnostic inference runtime; converting
  to ONNX format decouples your serving infrastructure from the training
  framework, a real, common production pattern (train in PyTorch, serve
  via ONNX Runtime for lower-overhead, more portable inference).
- **Triton Inference Server** (NVIDIA) — a production-grade, GPU-
  optimized serving platform supporting multiple frameworks/model formats
  simultaneously, with dynamic batching and model ensembling built in —
  the common choice for high-throughput, multi-model production inference at scale.
- **vLLM / TGI (Text Generation Inference)** — specifically for LLM
  serving (see LLM Quantization & Inference Notes and AI Agent & Automation
  Tooling Notes) — implement PagedAttention/continuous batching
  optimizations general-purpose serving frameworks don't provide out of the box.

### Experiment tracking & MLOps tooling
- **MLflow / Weights & Biases (W&B)** — experiment tracking, model
  registry, and hyperparameter sweep tooling — genuinely essential once a
  team runs more than a handful of training experiments, preventing
  "which config produced which result" chaos.
- **Optuna / Ray Tune** — hyperparameter optimization frameworks,
  implementing search strategies (Bayesian optimization, population-based
  training) genuinely more efficient than naive grid/random search.


## NICHE BUT REAL

- **Gradient checkpointing** — trades compute for memory: instead of
  storing every layer's activations for the backward pass, RECOMPUTE
  them during backprop as needed — a real, commonly-used technique for
  training models that otherwise wouldn't fit in GPU memory, at a real
  (usually 20-30%) training-time cost.
- **torch.fx / graph transformation tooling** — programmatically
  inspecting and transforming a PyTorch model's computation graph (used
  for quantization, pruning, custom optimization passes) — mostly
  library/tooling-author territory, but worth knowing exists for anyone
  building custom model-optimization pipelines.
- **Model soups / weight averaging** — literally averaging the WEIGHTS
  of multiple independently fine-tuned models (not their predictions)
  can sometimes outperform any single one — a genuinely surprising, real
  technique that's cheaper than traditional ensembling (only one model to
  serve at inference time) while capturing some of ensembling's benefit.
- **Framework interoperability gaps** — a model architecture using a
  custom CUDA kernel or framework-specific operation may not cleanly
  export to ONNX/another framework — a real, practical production
  constraint worth checking EARLY in a project if cross-framework
  portability (training in one, serving via another) is part of the
  planned architecture, rather than discovering the gap at deployment time.
