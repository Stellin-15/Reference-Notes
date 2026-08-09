"""
WHAT: Four realistic deep-learning system problems, each solved with
      THREE genuinely different, individually defensible architectural
      approaches drawn from L01-L07 -- with an explicit comparison table
      and reasoning for why each answer is valid under different
      constraints, in the same spirit as Classical ML Theory Notes L09.
WHY:  "Which architecture is best" is exactly as malformed a question at
      the deep-learning level as it is at the classical-ML level (No Free
      Lunch, Classical ML Theory Notes L01) -- the real skill is mapping
      a problem's actual constraints (sequence length, latency budget,
      data volume, interpretability need, deployment target) to the
      architectural tradeoffs L01-L07 derived, and being able to
      articulate the COST of each defensible choice, not just its benefit.
LEVEL: Capstone for the Deep Learning Theory Notes track -- read after
       L01-L07.
"""

# ============================================================================
# CASE STUDY 1 — REAL-TIME SPEECH TRANSCRIPTION ON A MOBILE DEVICE
# ============================================================================
#
# SETUP: on-device (no cloud round-trip) transcription of streaming audio,
# strict latency budget (must emit partial transcripts within ~200ms of
# audio arriving), limited compute/memory (a phone, not a GPU server),
# and inherently SEQUENTIAL/streaming input (audio arrives incrementally,
# not as one complete sequence you can attend over all at once).
#
# ------------------------------------------------------------------------
# APPROACH A: A GRU-based streaming encoder (L06)
# ------------------------------------------------------------------------
#   WHY VALID: GRUs process input incrementally, ONE timestep at a time,
#   with O(1) additional compute per new audio frame and a small,
#   constant memory footprint (the hidden state) -- a natural match for
#   genuinely STREAMING input where you must emit output before the full
#   sequence exists (self-attention's L07 all-pairs mechanism assumes
#   you already HAVE the whole sequence to attend over). GRU's fewer
#   parameters than LSTM (Concept #4, L06) also directly help under a
#   mobile memory budget.
#   COST: even with gating mitigating (not eliminating) vanishing
#   gradients (L06), very long-range dependencies within a long
#   utterance are handled less robustly than an attention-based
#   alternative would manage.
#
# ------------------------------------------------------------------------
# APPROACH B: A windowed/streaming self-attention model (chunk-based
# Transformer, attending only within a limited recent window, L07)
# ------------------------------------------------------------------------
#   WHY VALID: gets most of self-attention's single-hop gradient-flow
#   benefit (L07's Concept #4) within each local window, while sidestepping
#   full self-attention's O(T^2) cost (L07) by never attending over the
#   ENTIRE audio stream -- only a fixed-size recent window, keeping
#   compute bounded regardless of total utterance length.
#   COST: genuinely long-range dependencies (a reference early in a long
#   sentence resolved much later) are structurally invisible outside the
#   window -- a real, deliberate accuracy tradeoff for the latency/compute
#   win, not a free improvement over Approach A in every respect.
#
# ------------------------------------------------------------------------
# APPROACH C: A hybrid -- a lightweight CNN (L05) for local acoustic
# feature extraction, feeding a small GRU (L06) for sequence modeling
# ------------------------------------------------------------------------
#   WHY VALID: uses CNN's parameter efficiency and translation-equivariant
#   inductive bias (L05's Concept #1) specifically where it's the RIGHT
#   bias -- raw audio/spectrogram features have strong local structure
#   (a phoneme's acoustic signature looks similar regardless of exactly
#   when it starts) -- before handing off to a GRU for the genuinely
#   sequential, order-dependent modeling a CNN alone can't capture. This
#   division of labor (CNN for local pattern extraction, RNN for
#   sequential structure) was the dominant pre-Transformer speech
#   architecture for exactly this reason.
#   COST: more architectural complexity (two distinct component types to
#   tune and maintain) than either single-architecture approach, and
#   still inherits GRU's sequential-processing latency characteristics
#   for the RNN half.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Streaming-native | Long-range accuracy | Compute/memory | Complexity |
#   |----------|-------------------|----------------------|------------------|------------|
#   | A: GRU only | Yes (natural) | Lower | Lowest | Low |
#   | B: windowed attention | Partial (chunked) | Medium (window-limited) | Medium | Medium |
#   | C: CNN+GRU hybrid | Yes | Medium | Medium | Highest |
#   The genuinely correct choice depends on the actual distribution of
#   utterance lengths and how much long-range context real transcription
#   accuracy needs for this specific product -- not resolvable from
#   architecture theory alone.


# ============================================================================
# CASE STUDY 2 — MEDICAL IMAGE CLASSIFICATION WITH A SMALL LABELED DATASET
# ============================================================================
#
# SETUP: 3,000 labeled chest X-rays (small by deep-learning standards),
# a rare-disease class is a small minority, and the deployed model's
# decisions need SOME degree of clinical auditability.
#
# ------------------------------------------------------------------------
# APPROACH A: Fine-tune a large pretrained CNN (e.g. a ResNet pretrained
# on ImageNet), freezing most early layers
# ------------------------------------------------------------------------
#   WHY VALID: per L05's Concept #1-#3, early CNN layers learn fairly
#   generic, low-level visual features (edges, textures, simple shapes)
#   that transfer well across very different image domains -- freezing
#   them and fine-tuning only the later, more task-specific layers
#   directly addresses the small-labeled-dataset problem by effectively
#   reusing millions of ImageNet images' worth of learned low-level
#   structure, needing far fewer NEW labeled examples than training from
#   scratch would (a direct application of Classical ML Theory Notes
#   L01's bias-variance framing: transfer learning trades some bias
#   toward "features useful for natural images in general" for a large
#   variance reduction given the tiny target dataset).
#   COST: ImageNet's natural-image statistics (learned edge/texture
#   detectors) may transfer imperfectly to X-ray-specific structure
#   (bone density gradients, tissue texture) that looks quite different
#   from natural photos -- some genuinely relevant fine-grained medical
#   texture information may not be well-captured by features originally
#   learned for cats and cars.
#
# ------------------------------------------------------------------------
# APPROACH B: Train a smaller, from-scratch CNN with heavy data
# augmentation and strong regularization (dropout, L04)
# ------------------------------------------------------------------------
#   WHY VALID: avoids Approach A's domain-mismatch risk entirely by
#   learning features directly suited to X-ray images from the start --
#   data augmentation (rotations, intensity shifts, crops -- exploiting
#   CNNs' translation equivariance, L05's Concept #4, directly) and
#   dropout's implicit-ensembling mechanism (L04's Concept #1) are both
#   targeted, principled countermeasures to the small-dataset overfitting
#   risk, not generic "throw in some regularization" moves.
#   COST: without transfer learning's head start, 3,000 images is still
#   a genuinely small dataset for learning good low-level visual features
#   FROM SCRATCH -- likely to underperform Approach A unless augmentation
#   is unusually effective at this specific data volume.
#
# ------------------------------------------------------------------------
# APPROACH C: A frozen pretrained CNN as a fixed FEATURE EXTRACTOR,
# feeding a simple linear/logistic classifier (Classical ML Theory Notes
# L02) on top
# ------------------------------------------------------------------------
#   WHY VALID: the MOST conservative response to the small-dataset/
#   auditability constraints simultaneously -- freezing the ENTIRE CNN
#   (not just early layers) means the only thing actually being fit to
#   the 3,000 X-rays is a low-capacity linear classifier, which per
#   Classical ML Theory Notes L01 has drastically lower variance than
#   fine-tuning even a subset of a deep network's layers, AND the linear
#   classifier's coefficients are directly, exactly interpretable
#   (Classical ML Theory Notes L02) in terms of the extracted CNN
#   features -- directly relevant to the clinical-auditability
#   requirement, in a way neither A nor B's fine-tuned deep layers are.
#   COST: leaves real accuracy on the table relative to Approach A --
#   the frozen features were never adapted AT ALL to X-ray-specific
#   patterns, only reused as-is, likely the weakest of the three purely
#   on raw predictive performance.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Expected accuracy | Small-data robustness | Auditability | Domain-mismatch risk |
#   |----------|---------------------|--------------------------|-----------------|-------------------------|
#   | A: fine-tune, freeze early layers | Highest | Medium | Low | Medium |
#   | B: from-scratch + augmentation | Lower (likely) | Lower | Low | None |
#   | C: frozen extractor + linear head | Lowest (likely) | Highest | Highest | Medium |
#   A clinical deployment with strict auditability requirements may
#   reasonably accept Approach C's lower accuracy for its interpretability;
#   a research/triage-assist tool optimizing pure diagnostic accuracy would
#   likely prefer Approach A -- genuinely different valid answers depending
#   on which constraint actually binds for this specific deployment.


# ============================================================================
# CASE STUDY 3 — MACHINE TRANSLATION FOR A LOW-RESOURCE LANGUAGE PAIR
# ============================================================================
#
# SETUP: translating between English and a language with only ~50,000
# parallel sentence pairs available (far less than the millions typical
# high-resource pairs have), sentences can be long (up to ~100 words),
# and there's a real need for the system to handle genuinely long-range
# grammatical dependencies (the target language has significantly
# different word order/agreement rules than English).
#
# ------------------------------------------------------------------------
# APPROACH A: A full Transformer encoder-decoder (self-attention, L07)
# trained from scratch on the 50,000 pairs
# ------------------------------------------------------------------------
#   WHY VALID: per L07's Concept #4, self-attention's single-hop
#   connectivity is exactly the right mechanism for capturing the
#   long-range word-order/agreement dependencies this language pair
#   requires, with no vanishing-gradient degradation over the up-to-100-
#   word sentences (which would meaningfully stress an RNN per L06).
#   COST: Transformers are well-documented to be relatively DATA-HUNGRY
#   -- their lack of RNN's/CNN's built-in sequential/local inductive
#   bias (Classical ML Theory Notes L01's No Free Lunch, again) means
#   they must LEARN positional/sequential structure from data rather
#   than having it built in, which 50,000 pairs may genuinely be too
#   little data for, risking a UNDER-TRAINED (high-bias) model despite
#   the architecture's theoretical suitability for the dependency
#   structure.
#
# ------------------------------------------------------------------------
# APPROACH B: An LSTM-based encoder-decoder with attention (a pre-
# Transformer but still attention-augmented architecture, combining L06
# and L07's mechanisms)
# ------------------------------------------------------------------------
#   WHY VALID: LSTM's recurrent structure imposes a built-in sequential
#   inductive bias that can partially compensate for limited training
#   data (less to learn from scratch than a from-scratch Transformer's
#   fully-learned positional structure), while STILL getting attention's
#   long-range-dependency benefit via an attention layer bridging
#   encoder and decoder (a well-established pre-Transformer NMT
#   architecture for exactly this reason).
#   COST: still inherits LSTM's OWN sequential-processing constraints
#   (L06) within the encoder/decoder recurrence itself, even with
#   attention bridging the two -- a genuinely weaker mechanism for very
#   long within-sequence dependencies than a full Transformer's
#   uniform all-pairs connectivity.
#
# ------------------------------------------------------------------------
# APPROACH C: Fine-tune a LARGE PRETRAINED multilingual Transformer
# (pretrained on many other language pairs/monolingual corpora) on the
# 50,000 pairs, rather than training a Transformer from scratch
# ------------------------------------------------------------------------
#   WHY VALID: directly addresses Approach A's data-hunger problem via
#   TRANSFER LEARNING (the same core idea as Case Study 2's Approach A,
#   applied to language instead of vision) -- a multilingual pretrained
#   model has already learned substantial general linguistic structure
#   (grammar, cross-lingual alignment patterns) from vastly more data
#   than 50,000 pairs, needing the low-resource pair's data only to
#   ADAPT that existing structure rather than learn language from zero.
#   COST: depends entirely on a suitable pretrained multilingual model
#   existing/being available for this specific language, and the quality
#   of transfer for a GENUINELY low-resource, possibly under-represented-
#   in-pretraining-data language can be inconsistent -- not guaranteed to
#   work as well as it does for higher-resource languages more heavily
#   represented in the pretraining corpus.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Data efficiency | Long-range dependency handling | Availability risk |
#   |----------|-------------------|------------------------------------|----------------------|
#   | A: Transformer from scratch | Lowest | Best (in principle) | None (self-contained) |
#   | B: LSTM+attention | Medium (built-in bias helps) | Good | None (self-contained) |
#   | C: fine-tune pretrained multilingual | Highest (if available) | Best | Depends on pretrained model existing |
#   For a GENUINELY low-resource pair, most practitioners would lean
#   toward C if a suitable pretrained model exists, falling back to B as
#   a more data-efficient self-contained alternative to A -- again a
#   reasoned lean, not a universal rule.


# ============================================================================
# CASE STUDY 4 — FRAUD DETECTION ON TABULAR TRANSACTION DATA (DEEP
# LEARNING VS. CLASSICAL ML, REVISITED FROM A DL-ARCHITECTURE ANGLE)
# ============================================================================
#
# SETUP: the same broad problem shape as Classical ML Theory Notes L09's
# Case Study 2 (real-time, imbalanced, latency-sensitive), but the
# specific question here is whether/how to apply DEEP LEARNING
# architecture choices to genuinely tabular (non-image, non-sequence,
# non-language) data.
#
# ------------------------------------------------------------------------
# APPROACH A: A plain MLP (fully-connected layers only, no CNN/RNN/
# attention structure, L01)
# ------------------------------------------------------------------------
#   WHY VALID: tabular features (transaction amount, merchant category,
#   time-since-last-transaction, etc.) have NO inherent spatial or
#   sequential structure the way images or language do -- per Classical
#   ML Theory Notes L01's No Free Lunch and this domain's L05 Concept #1
#   discussion, imposing a CNN's local-connectivity/weight-sharing bias
#   or an RNN's sequential bias on genuinely unordered tabular columns
#   would be imposing an inductive bias that doesn't MATCH the data's
#   actual structure -- a plain MLP with no such structural assumption is
#   the architecturally honest default here.
#   COST: gradient-boosted trees (Classical ML Theory Notes L03) are
#   extremely well-documented to consistently match or outperform MLPs
#   on tabular data in practice, need far less hyperparameter tuning,
#   and train faster -- meaning Approach A, while architecturally
#   defensible, is often NOT the empirically best choice for pure tabular
#   fraud data specifically (a direct instance of Classical ML Theory
#   Notes L09's Case Study 2 reasoning, now with the DL vs. classical-ML
#   choice made explicit).
#
# ------------------------------------------------------------------------
# APPROACH B: A Transformer-style self-attention layer over the
# transaction's INDIVIDUAL FEATURES (treating each feature as a "token,"
# an emerging tabular-deep-learning technique)
# ------------------------------------------------------------------------
#   WHY VALID: unlike Approach A's flat MLP, attention (L07) between
#   features can explicitly model FEATURE INTERACTIONS (which pairs/
#   groups of features jointly matter) directly, addressing the exact
#   filter-method blind spot Classical ML Theory Notes L08 identified
#   (XOR-style interactions) with a mechanism explicitly designed for
#   modeling pairwise relationships.
#   COST: this is a genuinely newer, less battle-tested approach for
#   tabular data than gradient boosting, with a real risk of adding
#   substantial architectural/training complexity without a
#   correspondingly reliable accuracy win over well-tuned gradient
#   boosting -- appropriate to test empirically, not to assume superior
#   by analogy to attention's well-established wins in vision/language.
#
# ------------------------------------------------------------------------
# APPROACH C: Gradient-boosted trees (Classical ML Theory Notes L03),
# explicitly choosing NOT to use a deep-learning architecture at all
# ------------------------------------------------------------------------
#   WHY VALID: this is the empirically strongest documented default for
#   tabular fraud-style data specifically, per extensive published
#   benchmarking -- and choosing it here is the correct application of
#   Classical ML Theory Notes L01's No Free Lunch theorem in the OTHER
#   direction from how this case study's setup might suggest: "we're
#   doing a deep-learning-focused case study" is not, by itself, a
#   reason to force a deep-learning architecture onto data where a
#   classical technique already excels for well-understood structural
#   reasons.
#   COST: forgoes any potential benefit of representation learning
#   (automatically learned feature embeddings/interactions) that a
#   sufficiently well-tuned deep architecture MIGHT eventually provide,
#   especially if the feature set grows to include less-structured data
#   (free text notes, images of receipts) that trees handle poorly and
#   deep architectures are specifically built for.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Matches data's inductive-bias needs | Empirical track record on tabular data | Complexity |
#   |----------|-----------------------------------------|--------------------------------------------|------------|
#   | A: plain MLP | Neutral (no bias imposed) | Weaker than trees, typically | Medium |
#   | B: feature-wise attention | Good (models interactions) | Emerging, less proven | High |
#   | C: gradient-boosted trees | N/A (not a DL architecture) | Strongest, well-documented | Lowest |
#   THE EXPLICIT LESSON OF THIS CASE STUDY: the existence of a deep
#   learning theory track does not mean every problem should route
#   through it -- recognizing when the classical-ML answer (C) is
#   simply the correct engineering choice, DESPITE working through a
#   deep-learning-focused lesson sequence, is itself the skill this
#   case study is testing.
"""
As in Classical ML Theory Notes L09, this lesson has no runnable code --
its content IS the comparative reasoning above. Before checking the
comparison tables, try reconstructing them yourself using only L01-L07's
derived mechanisms (variance propagation, gradient path length, inductive
bias matching, compute/data tradeoffs) -- the goal is the reasoning
pattern, not memorizing these four specific verdicts.
"""
