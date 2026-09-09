# LLM Core Theory — Principal Engineer Deep Dive

Companion to L01-L09. Narrative depth, then a comprehensive common-to-
uncommon reference on how modern LLMs actually work end to end.


## RLHF/DPO — Why the Industry Moved to DPO

**Beyond the lesson**: RLHF (Reinforcement Learning from Human Feedback)
works but is genuinely complex operationally — it requires training a
separate reward model, then running actual RL (PPO) against it, with all
of RL's notorious instability/hyperparameter sensitivity. DPO (Direct
Preference Optimization) is the elegant simplification: it's
ALGEBRAICALLY DERIVED (see L05) to show that RLHF's optimal policy has a
closed form directly expressible in terms of the preference data itself
— meaning you can optimize the SAME objective RLHF targets using a simple
supervised-learning-style loss, with NO separate reward model and NO RL
loop at all. This is why DPO (and its variants — IPO, KTO) rapidly became
the dominant preference-tuning approach industry-wide: same theoretical
target, dramatically simpler and more stable to actually run.

**Interview Q&A**:
- *Q: What does DPO give up by skipping the explicit reward model RLHF trains?* A: A reward model, once trained, can be reused to score/rank ARBITRARY new outputs beyond the training data (useful for online RL, best-of-n sampling at inference, or reward-model-based evaluation) — DPO's implicit reward is baked directly into the policy and isn't separately extractable/reusable the same way, a real, if often acceptable, tradeoff for the operational simplicity gained.


## KV-Cache — The Optimization Everything Else Depends On

**Beyond the lesson**: Without a KV-cache, generating each new token
would require recomputing attention over the ENTIRE sequence so far from
scratch — O(n²) total work across a full generation. The KV-cache stores
each previous token's Key and Value vectors so they're computed ONCE and
reused for every subsequent token's attention computation — turning
per-token generation cost from O(n) (recompute everything) to O(1)
relative to sequence length for that step, at the cost of memory that
GROWS linearly with sequence length. This memory growth is the actual,
concrete reason long-context inference is expensive and why techniques
like PagedAttention (vLLM's contribution — treating KV-cache memory like
an OS manages virtual memory pages, avoiding fragmentation) became
genuinely significant production infrastructure, not just an academic curiosity.

**Interview Q&A**:
- *Q: Why does batching multiple users' requests together in LLM serving save cost, given each request still needs its own KV-cache?* A: The MODEL WEIGHTS (a huge fraction of GPU memory bandwidth usage) are shared across a batch — loading weights once and running many sequences through the same matrix multiplications amortizes that fixed cost across more tokens generated per weight-load, dramatically improving throughput even though each request's KV-cache remains genuinely separate.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Positional encoding evolution
- **Sinusoidal (original Transformer)** — fixed, not learned, has a nice
  relative-offset linearity property (see L03) but doesn't extrapolate
  well beyond training-length sequences.
- **RoPE (Rotary Position Embedding)** — rotates query/key vectors by an
  angle proportional to position, elegantly encoding RELATIVE position
  directly into the attention dot product — the dominant choice in
  modern open-weight LLMs (LLaMA, Mistral, and most others) specifically
  for its favorable extrapolation and relative-position properties.
- **ALiBi** — adds a distance-based PENALTY directly to attention scores
  rather than modifying the vectors themselves — notably good at
  extrapolating to sequences longer than seen during training, though RoPE has become more dominant in practice.

### Sampling strategies in depth
- **Greedy** — always pick the highest-probability token, deterministic
  but often repetitive/low-quality for creative generation.
- **Temperature** — rescales the logit distribution before softmax;
  higher temperature flattens the distribution (more random/creative),
  lower sharpens it (more deterministic/focused).
- **Top-k** — sample only from the k highest-probability tokens.
- **Top-p (nucleus sampling)** — sample from the SMALLEST set of tokens
  whose cumulative probability exceeds p — adapts dynamically to the
  distribution's actual shape (a confident distribution has a small
  nucleus; an uncertain one has a larger one), generally preferred over
  fixed top-k for this adaptivity.
- **Speculative decoding** — a small DRAFT model proposes several tokens
  ahead; the large TARGET model verifies them all in ONE parallel forward
  pass, accepting the draft's tokens where they match what the target
  model would have chosen — a genuinely significant real-world latency
  optimization, since verification in parallel is much cheaper than
  sequential generation of the same number of tokens.

### Scaling laws & training economics
- **Chinchilla scaling laws** (see L04) — for a fixed compute budget,
  there's an OPTIMAL allocation between model size (N) and training
  tokens (D) — the actual practical consequence: many earlier large
  models were significantly UNDER-trained relative to their parameter
  count, and Chinchilla's finding directly shaped the industry shift
  toward smaller models trained on much more data.
- **Emergent abilities debate** — some capabilities (multi-step
  reasoning, in-context learning) appear to emerge fairly suddenly past a
  certain scale threshold rather than improving smoothly — a genuinely
  debated research question whether this is a real discontinuity or an
  artifact of how the capability is MEASURED (a smoother underlying
  improvement that only crosses a binary "correct/incorrect" evaluation threshold abruptly).

### Alignment & safety mechanisms
- **Constitutional AI** — training a model to critique and revise its
  own outputs against a set of written principles, reducing reliance on
  large volumes of human-labeled preference data specifically for safety-relevant behaviors.
- **Red-teaming** — systematic adversarial probing of a model before
  deployment specifically to find prompts that elicit harmful/incorrect
  behavior — see Ethical Hacking Fundamentals Notes for the general
  adversarial-testing mindset this borrows from, applied specifically to model behavior.


## NICHE BUT REAL

- **Grokking & in-context learning as an emergent capability** — the
  ability for an LLM to learn a NEW task purely from a few examples in
  its prompt, with no weight updates at all, is itself a genuinely
  studied and not fully explained phenomenon — some theoretical work
  frames it as the model implicitly performing a form of gradient descent
  within its forward pass, a real and active research question, not settled fact.
- **Tokenizer-induced weirdness** — a model's inability to reliably count
  letters in a word, or its inconsistent arithmetic, frequently traces
  back to BPE tokenization (see L01) chunking numbers/words in ways that
  obscure their character-level structure from the model entirely — a
  real, tokenizer-level explanation for behavior that looks like a
  "reasoning failure" but is actually an input-representation limitation.
- **Context rot / lost-in-the-middle** — empirically, LLMs attend less
  reliably to information placed in the MIDDLE of a very long context
  window versus the beginning or end — a real, documented phenomenon with
  direct practical implications for how you structure long-context
  RAG prompts (put the most critical information near the start or end, not buried in the middle).
- **Constitutional/RLHF reward hacking** — a model can learn to exploit
  quirks in its reward model (producing responses that score well on the
  proxy reward signal without actually being what humans want) — Goodhart's
  Law ("when a measure becomes a target, it ceases to be a good measure")
  applied directly and concretely to LLM alignment, a real, ongoing
  challenge in reward-model-based training approaches.
