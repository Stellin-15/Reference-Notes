# LLM Quantization & Inference — Principal Engineer Deep Dive

Companion to the existing 26-lesson track. Narrative depth, then a
comprehensive common-to-uncommon reference.


## Quantization — What's Actually Being Traded Away

**Beyond the lesson**: Quantization reduces numerical precision (FP32 →
FP16/BF16 → INT8 → INT4) to shrink memory footprint and increase
throughput — but the interesting engineering question is WHERE precision
loss hurts least. Weights tend to tolerate aggressive quantization better
than activations, because weights are STATIC (learned once, quantization
error is a fixed, analyzable perturbation) while activations vary
per-input and can have outlier values that a naive uniform quantization
scheme clips badly — this is exactly why techniques like GPTQ and AWQ
exist: they specifically calibrate quantization scales using REAL
representative data to minimize the ACTUAL error on typical inputs,
rather than a naive uniform min-max quantization that treats every value equally.

**Worked example**: GGUF (llama.cpp's format) and its K-quant variants
(Q4_K_M, Q5_K_M, etc.) apply DIFFERENT quantization precision to
different parts of a model — some layers/matrices are quantized more
aggressively, others kept at higher precision, based on empirically-
measured sensitivity — this mixed-precision-per-layer approach is why
Q4_K_M consistently outperforms a naive uniform 4-bit quantization at
the same average bit-width, a real, practical engineering refinement
beyond "just use fewer bits everywhere."

**Interview Q&A**:
- *Q: Why does INT8 quantization sometimes cause a much bigger accuracy drop on one model architecture than another at the same bit-width?* A: Models vary in how much their weight/activation distributions have OUTLIERS (a few values far larger than the typical range) — architectures/layers with heavy-tailed distributions lose more information under uniform quantization's fixed range, which is exactly the problem techniques like SmoothQuant address by redistributing quantization difficulty between weights and activations rather than accepting the naive split.


## Continuous Batching & PagedAttention — The Throughput Unlock

**Beyond the lesson**: Naive batched LLM serving (static batching) waits
for an entire batch to finish generating before starting a new batch —
but requests in a batch finish at DIFFERENT times (different output
lengths), wasting GPU capacity on already-finished sequences sitting idle
until the slowest one completes. Continuous batching (vLLM's core
innovation, alongside PagedAttention) dynamically ADDS new requests into
a batch as soon as any slot frees up, keeping GPU utilization consistently
high — this single serving-infrastructure change is responsible for a huge
fraction of the real-world throughput improvement modern LLM serving
stacks achieve over naive implementations, genuinely more impactful for
production cost than most model-level optimizations alone.

**Interview Q&A**:
- *Q: Why does PagedAttention specifically solve a memory FRAGMENTATION problem, not just a memory SIZE problem?* A: Without it, each sequence's KV-cache is allocated as one contiguous block sized for its MAXIMUM possible length upfront — as sequences of varying actual lengths complete and new ones start, this creates fragmented, unusable gaps (like classic OS memory fragmentation); PagedAttention allocates KV-cache in fixed-size PAGES (borrowing directly from OS virtual memory paging) that can be non-contiguous and reused flexibly, eliminating that fragmentation waste.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Serving frameworks, precisely differentiated
- **vLLM** — the dominant open-source high-throughput serving engine;
  PagedAttention + continuous batching, the current de facto standard for
  self-hosted LLM serving at scale.
- **TGI (Text Generation Inference, Hugging Face)** — a similar-purpose
  alternative, tightly integrated with the Hugging Face ecosystem.
- **llama.cpp** — CPU-first (with GPU acceleration support), C++,
  extremely portable — the dominant choice for local/edge/consumer-
  hardware inference (powers Ollama and many local-LLM apps under the hood).
- **TensorRT-LLM** (NVIDIA) — maximally optimized for NVIDIA GPUs
  specifically, squeezing out the most raw performance at the cost of
  being tied to NVIDIA's own toolchain/hardware.
- **SGLang** — a newer serving framework emphasizing efficient handling
  of structured generation and complex multi-call agent workflows,
  gaining real production traction as agentic use cases (many
  interdependent LLM calls per task) grow.

### Model compression techniques beyond quantization
- **Pruning** — removing weights/neurons/attention heads that contribute
  little to the model's output — structured pruning (removing whole
  channels/heads, hardware-friendly) vs unstructured pruning (individual
  weights, higher theoretical compression but needs specialized sparse
  hardware/kernels to actually realize speed gains).
- **Knowledge distillation** — training a smaller STUDENT model to
  mimic a larger TEACHER model's output distribution (not just hard
  labels) — DistilBERT and many small, deployable models are produced this way.
- **Speculative decoding** (see LLM Core Theory deep dive) — an
  INFERENCE-time technique, not a compression technique, but frequently
  deployed alongside quantization for compounding latency improvements.

### Hardware-aware inference considerations
- **Memory bandwidth vs compute-bound inference** — LLM inference
  (especially with small batch sizes / single-user latency-focused
  serving) is frequently MEMORY-BANDWIDTH-bound, not compute-bound — the
  bottleneck is moving weights from GPU memory to compute units fast
  enough, not the matrix multiplication FLOPs themselves — this is why
  quantization (reducing bytes moved) often speeds up inference more
  than the raw FLOP reduction alone would predict.
- **Batch size's effect on the compute/memory-bound crossover** — at
  larger batch sizes, the SAME weights get reused across more sequences
  per memory load, shifting the bottleneck toward compute-bound — this is
  the same "amortize weight loading" principle from the ML Frameworks deep dive's batching discussion, specific to inference economics.


## NICHE BUT REAL

- **Activation-aware quantization (AWQ)** — identifies which WEIGHT
  channels are most sensitive based on their corresponding ACTIVATION
  magnitudes (not just the weight values themselves) and preserves
  precision specifically for those, a genuinely more targeted approach
  than uniform or purely weight-magnitude-based quantization schemes.
- **Ternary/binary quantization research** (1-bit LLMs, BitNet) — an
  active, cutting-edge research direction pushing quantization to its
  logical extreme (weights restricted to {-1, 0, 1}) — still mostly
  research-stage but worth knowing as the frontier beyond mainstream
  4-bit/8-bit production quantization.
- **Flash Attention** — an exact (not approximate) attention
  implementation that reduces memory reads/writes by never materializing
  the full attention matrix in slow GPU memory, keeping computation in
  fast on-chip SRAM instead — a genuinely significant systems-level
  (not algorithmic) optimization, distinct from quantization, that most
  modern training AND inference stacks use by default now.
- **Speculative decoding tree/multi-draft variants** — more advanced
  variants of speculative decoding propose MULTIPLE candidate continuation
  paths (a tree, not a single linear draft) verified in parallel,
  squeezing out further latency improvement over the basic single-draft
  approach — an active area of continued serving-infrastructure research.
