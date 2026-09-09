# Deep Learning Theory — Principal Engineer Deep Dive

Companion to L01-L09. Narrative depth, then a comprehensive common-to-
uncommon reference.


## Why Adam Won, and Where It Still Loses

**Beyond the lesson**: Adam combines momentum (accumulating a moving
average of past gradients, smoothing out noisy updates) with RMSProp's
per-parameter adaptive learning rate (dividing by a moving average of
squared gradients, so parameters with historically large gradients get
smaller effective steps, and vice versa) — this combination is WHY Adam
converges fast and robustly across a huge range of problems without much
learning-rate tuning, which is exactly why it became the default. The
production nuance most tutorials skip: Adam's adaptive per-parameter
scaling can lead to WORSE generalization than plain SGD with momentum on
some problems (a genuinely observed, studied phenomenon) — which is why
many state-of-the-art vision models still train with SGD+momentum+
carefully-tuned learning-rate schedules despite Adam's convenience, and
why AdamW (decoupling weight decay from the adaptive gradient scaling —
see L04) specifically exists to fix a real, separate bug in how vanilla
Adam interacted with L2 regularization.

**Interview Q&A**:
- *Q: Why does AdamW usually outperform Adam with L2 regularization for the exact same nominal weight-decay coefficient?* A: In vanilla Adam, L2 regularization gets folded into the gradient BEFORE the adaptive per-parameter scaling divides it — so parameters with large historical gradients get LESS effective weight decay, not a uniform decay rate as intended. AdamW applies weight decay directly to the weights, decoupled from the adaptive gradient scaling, restoring the uniform decay behavior that was the actual intent all along.


## Attention as the Solution to a Specific, Named Problem

**Beyond the lesson**: Self-attention isn't an arbitrary architectural
choice — it's the direct engineering answer to the vanishing-gradient
problem RNNs/LSTMs suffer over long sequences (see L06). An RNN must
propagate information through EVERY intermediate timestep sequentially,
and gradients shrink (or explode) multiplicatively at each step; an
attention mechanism lets ANY token attend DIRECTLY to any other token in
ONE step, regardless of their distance in the sequence — the gradient
path length between any two positions is O(1), not O(sequence length).
This single architectural insight is WHY Transformers displaced RNNs for
long-range dependency modeling, not because attention is inherently
"smarter" in some vague sense.

**Interview Q&A**:
- *Q: Why is attention scaled by 1/sqrt(d_k) before the softmax?* A: As the dimension of the query/key vectors grows, their dot products grow in magnitude proportionally, pushing softmax inputs into a regime where its GRADIENT becomes vanishingly small (softmax saturates) — dividing by sqrt(d_k) keeps the dot-product variance roughly constant regardless of dimension, keeping the softmax in a well-behaved gradient regime — a mathematically necessary normalization, not an arbitrary hyperparameter.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Normalization techniques beyond BatchNorm/LayerNorm
- **RMSNorm** — a simplification of LayerNorm that skips re-centering
  (subtracting the mean), only rescaling by the root-mean-square —
  computationally cheaper, and used in many modern LLM architectures
  (LLaMA and others) as a genuinely effective simplification, not just an optimization shortcut.
- **GroupNorm** — normalizes over GROUPS of channels rather than the full
  batch (BatchNorm) or full layer (LayerNorm) — chosen for small-batch-size
  training regimes (common in object detection/segmentation) where
  BatchNorm's batch-statistics estimate becomes unreliable with few samples per batch.

### Regularization beyond dropout/weight decay
- **Label smoothing** — instead of training against a hard one-hot
  target (100% confidence in the correct class), soften it slightly
  (e.g. 90% correct class, 10% spread across others) — prevents the
  model from becoming overconfident and improves calibration, a real,
  widely-used technique in production classification models.
- **Mixup / CutMix** — data augmentation techniques that blend two
  training examples (and their labels proportionally) — a genuinely
  effective regularizer for vision models, forcing the model to learn
  more robust, less memorization-prone features.
- **Gradient clipping** — capping gradient norm during training,
  specifically to prevent exploding gradients from a single bad batch
  destabilizing an otherwise well-behaved training run — a standard,
  near-universal production training safeguard, especially for RNNs/Transformers.

### Architecture families beyond CNN/RNN/Transformer
- **Graph Neural Networks (GNNs)** — extend the "learn from neighbors"
  idea to genuinely graph-structured data (social networks, molecules,
  recommendation systems) — message passing between connected nodes is
  the core mechanism, a real, distinct architecture family from the
  grid-structured assumptions CNNs make or the sequential assumptions RNNs make.
- **Diffusion models** — the dominant modern architecture for image
  generation (Stable Diffusion, DALL-E) — trained to progressively
  DENOISE random noise back into a coherent image, a genuinely different
  generative paradigm from GANs' adversarial min-max training.
- **Mixture of Experts (MoE)** — routes each input through only a SUBSET
  of a model's total parameters (a learned "router" selects which expert
  sub-networks activate) — lets a model have a huge total parameter count
  while keeping the ACTUAL compute per forward pass much smaller — the
  architecture underneath several of the largest modern LLMs' efficiency claims.

### Training infrastructure concepts
- **Mixed precision training** (see GPU Computing deep dive) — training
  in FP16/BF16 instead of FP32 for most operations, with careful loss
  scaling to avoid gradient underflow — a near-universal production
  technique for training speed/memory at negligible accuracy cost when done correctly.
- **Learning rate warmup + decay schedules** — starting training with a
  small, gradually INCREASING learning rate before the main decay
  schedule — genuinely necessary for Transformer training stability
  specifically, preventing early, large, destabilizing updates before the
  optimizer's adaptive statistics have accumulated meaningful history.


## NICHE BUT REAL

- **The lottery ticket hypothesis** — the finding that within a large,
  randomly-initialized network, there exist much SMALLER subnetworks
  ("winning tickets") that, if trained in isolation from that same
  initialization, achieve comparable accuracy — a real, influential
  research finding underlying much of modern pruning/sparsity research.
- **Double descent** — a genuinely counterintuitive, empirically observed
  phenomenon where test error can DECREASE, then INCREASE (classic
  overfitting), then DECREASE AGAIN as model capacity/training time
  continues to grow past the classical "overfitting" regime — challenges
  the simple bias-variance tradeoff narrative and is an actively studied,
  real deep-learning-theory research area.
- **Neural Tangent Kernel (NTK) theory** — a theoretical framework showing
  that infinitely-wide neural networks trained with gradient descent
  behave equivalently to a specific kernel method — a genuinely deep
  theoretical bridge between classical kernel methods (see Classical ML
  Theory deep dive) and modern deep learning, worth knowing exists even
  without the full derivation at hand.
- **Grokking** — a real, observed phenomenon where a model trained past
  the point of apparent overfitting SUDDENLY generalizes dramatically
  better after extended training — an active, genuinely surprising area
  of interpretability/training-dynamics research with no fully settled explanation yet.
