"""
WHAT: The causal language modeling objective derived as autoregressive
      maximum likelihood (a direct extension of Classical ML Theory
      Notes L02's MLE-derivation pattern to sequences), why it's the
      dominant choice over masked language modeling for generative LLMs,
      and the Chinchilla scaling laws derived as an optimization problem
      over a fixed compute budget.
WHY:  "LLMs are trained to predict the next token" is true but skips WHY
      that specific objective, framed as MLE, explains loss curves,
      perplexity, and the entire pretraining process as one continuous
      application of ideas this repo already built (MLE in Classical ML
      Theory Notes L02, generalized here from independent examples to a
      sequential, autoregressive factorization). Scaling laws are usually
      cited as an empirical curve fit -- this lesson shows the actual
      optimization problem (allocate a fixed compute budget between model
      size and data) that produces the famous "roughly equal scaling"
      result.
LEVEL: Foundational.

PREREQUISITE: L01-L03 (tokenization, architecture, positional encoding
-- this lesson explains what OBJECTIVE all of that machinery is trained
against); Classical ML Theory Notes L02 (MLE derivation pattern, directly
reused and extended here).
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — CAUSAL LANGUAGE MODELING AS AUTOREGRESSIVE MLE (extending
# Classical ML Theory Notes L02's MLE pattern from independent examples
# to a SEQUENCE)
# ============================================================================
#
# Classical ML Theory Notes L02 derived logistic regression's cross-
# entropy loss from Bernoulli MLE over INDEPENDENT examples:
#   L(beta) = prod_i P(y_i | x_i; beta)
# A sequence of tokens is NOT a set of independent examples -- token 5
# depends on tokens 1-4. The CHAIN RULE OF PROBABILITY lets you factor
# the joint probability of an ENTIRE sequence w = (w_1, ..., w_T) into a
# product of CONDITIONAL probabilities, with NO independence assumption
# required (this factorization is an identity, always exactly true):
#   P(w_1, ..., w_T) = prod_{t=1}^{T} P(w_t | w_1, ..., w_{t-1})
#
# CAUSAL (AUTOREGRESSIVE) LANGUAGE MODELING trains a single neural
# network to approximate EVERY ONE of these conditional distributions
# simultaneously, using the SAME shared parameters theta:
#   P_theta(w_t | w_1, ..., w_{t-1})
# and the training objective is exactly MLE applied to this factorized
# joint probability, across the entire training corpus of sequences:
#   maximize  sum over training sequences  sum_{t=1}^{T} log P_theta(w_t | w_<t)
# Taking the negative and dividing by the number of predicted tokens
# gives the CROSS-ENTROPY LOSS every LLM pretraining run actually
# minimizes -- IDENTICAL in form (negative log-likelihood of the correct
# class under a softmax) to Classical ML Theory Notes L02's multi-class
# logistic regression loss, just applied T times per sequence (once per
# token position, each time conditioning on all PRECEDING tokens) rather
# than once per independent example. This is why "LLM pretraining" is
# not a conceptually new kind of machine learning -- it's the same MLE-
# under-a-categorical-distribution framework from Classical ML Theory
# Notes L02, applied to a sequential factorization instead of independent
# rows.
#
# WHY "CAUSAL" (the model can only condition on PRECEDING tokens, never
# future ones) is enforced via EXACTLY the causal mask Deep Learning
# Theory Notes L07 derived (setting attention scores for future positions
# to -infinity before softmax) -- without this mask, a model attending
# to a token's own future context during training would trivially "cheat"
# (predicting w_t by literally looking at w_t, or tokens after it,
# rather than genuinely learning to predict from context alone), making
# training loss meaningless and the resulting model useless for actual
# left-to-right generation at inference time, where future tokens
# genuinely don't exist yet.

def causal_lm_loss(logits, targets):
    """
    logits: (seq_len, vocab_size) -- the model's PREDICTED distribution
    (before softmax) over the next token, at EVERY position simultaneously
    (this is what a single forward pass produces, thanks to the causal
    mask -- one forward pass yields T separate next-token predictions,
    not just one).
    targets: (seq_len,) -- the ACTUAL next token at each position (i.e.
    targets[t] = the token that truly follows position t, typically just
    the input sequence shifted left by one).
    Returns the average cross-entropy loss -- the direct MLE objective
    from Concept #1, computed exactly as multi-class logistic regression's
    loss (Classical ML Theory Notes L02) would be, applied per position.
    """
    seq_len, vocab_size = logits.shape
    # Numerically stable log-softmax (identical technique to Classical ML
    # Theory Notes L07's log-sum-exp trick).
    max_logits = logits.max(axis=1, keepdims=True)
    log_probs = logits - max_logits - np.log(
        np.sum(np.exp(logits - max_logits), axis=1, keepdims=True))
    correct_log_probs = log_probs[np.arange(seq_len), targets]
    return -correct_log_probs.mean()


def perplexity(loss):
    """Perplexity = exp(average negative log-likelihood per token) -- a
    direct, monotonic transform of the SAME cross-entropy loss, with an
    intuitive interpretation: perplexity P means the model is, on
    average, as 'confused' as if it had to choose uniformly among P
    equally-likely options at each token position. Lower is better;
    perplexity 1 means perfect, fully-confident correct prediction."""
    return np.exp(loss)


# ============================================================================
# CONCEPT #2 — WHY CAUSAL (LEFT-TO-RIGHT) LM DOMINATES OVER MASKED
# LANGUAGE MODELING FOR GENERATIVE LLMS, DESPITE BERT-STYLE MASKED LM'S
# EARLIER SUCCESS
# ============================================================================
#
# MASKED LANGUAGE MODELING (MLM, as in BERT): randomly mask ~15% of
# tokens in a sequence, train the model to predict the masked tokens
# using BIDIRECTIONAL context (both preceding AND following tokens are
# visible, since the model isn't doing left-to-right generation). This
# gives MLM a genuine advantage for representation-learning/understanding
# tasks -- a masked token can be predicted using richer, bidirectional
# context than causal LM allows.
#
# WHY THIS BIDIRECTIONAL ADVANTAGE DOESN'T TRANSFER TO GENERATIVE USE:
# MLM's training objective NEVER teaches the model to produce text
# LEFT-TO-RIGHT, one token at a time, conditioning only on what's been
# generated so far -- exactly the operation actually needed at INFERENCE
# time for open-ended text generation (chat, completion, code generation).
# A model trained purely with MLM has no natural mechanism for
# autoregressive generation at all; adapting an MLM-trained model to
# generate text requires additional architecture/training changes that
# largely reduce to re-deriving something closer to causal LM anyway.
# CAUSAL LM, by contrast, trains the model on EXACTLY the task it will
# perform at inference (predict the next token given only preceding
# context) -- a direct train/inference match that MLM structurally lacks
# for generative use cases, which is precisely why virtually every modern
# large-scale GENERATIVE LLM (GPT-family and its many descendants) uses
# causal LM as its core pretraining objective, while MLM-style models
# (BERT-family) remain more common for pure understanding/embedding/
# classification tasks where bidirectional context is a pure win with no
# generation requirement to trade off against.

def demonstrate_bidirectional_vs_causal_context(seq_len=8):
    """Illustrates, structurally, the exact context each objective's
    mask makes available at each position -- causal (lower-triangular:
    can see only past+self) vs. bidirectional/MLM-style (full visibility,
    except the masked position itself, which real MLM implementations
    handle by simply excluding it as its own target while allowing full
    context elsewhere)."""
    causal_mask = np.tril(np.ones((seq_len, seq_len), dtype=bool))
    bidirectional_mask = np.ones((seq_len, seq_len), dtype=bool)
    return causal_mask, bidirectional_mask


# ============================================================================
# CONCEPT #3 — CHINCHILLA SCALING LAWS: OPTIMAL COMPUTE ALLOCATION
# BETWEEN MODEL SIZE AND DATA, DERIVED AS A CONSTRAINED OPTIMIZATION
# PROBLEM
# ============================================================================
#
# Empirically (Hoffmann et al. 2022, "Chinchilla"), final pretraining
# loss L, as a function of model parameter count N and training tokens D,
# follows an approximately additive power-law form:
#   L(N, D) ≈ E + A/N^alpha + B/D^beta
# where E is an irreducible-error-like floor (a direct echo of Classical
# ML Theory Notes L01's sigma^2 term -- a loss floor no amount of
# capacity or data eliminates), A/N^alpha captures loss reduction from
# more model CAPACITY (echoing L01's BIAS term -- larger N reduces the
# error from the model class being too restrictive), and B/D^beta
# captures loss reduction from more DATA (echoing L01's VARIANCE term --
# more data tightens the estimate of the true underlying distribution).
# This empirical form is directly interpretable through the SAME bias-
# variance-plus-irreducible-error decomposition Classical ML Theory
# Notes L01 derived for classical models, now fit to observed large-
# scale training-run data rather than derived analytically.
#
# THE SCALING-LAW QUESTION: given a FIXED compute budget C (roughly
# proportional to N*D -- more parameters AND more training tokens each
# cost proportionally more compute, and their PRODUCT approximates total
# training FLOPs), how should you ALLOCATE that budget between N (bigger
# model) and D (more data) to MINIMIZE L(N,D)?
#
# This is a constrained optimization problem: minimize L(N,D) subject to
# N*D = C (a fixed compute budget). Using a Lagrange multiplier (the same
# technique Classical ML Theory Notes L04 used to derive the SVM dual,
# and this domain's L02 used for PCA):
#   Lagrangian: A/N^alpha + B/D^beta - lambda*(N*D - C)
#   Setting partial derivatives w.r.t. N and D to zero and solving
#   yields, given empirically-observed alpha ≈ beta (Chinchilla's key
#   empirical finding, not a mathematical necessity of the derivation
#   itself, but the specific empirical values found), that COMPUTE-
#   OPTIMAL TRAINING ALLOCATES ROUGHLY EQUAL SCALING to N and D: for a
#   10x increase in compute budget, optimal N and optimal D should each
#   increase by ROUGHLY THE SAME factor (documented as close to N∝C^0.5,
#   D∝C^0.5, i.e. both scale with the square root of compute) -- NOT the
#   earlier (pre-Chinchilla, GPT-3-era) convention of scaling model size
#   MUCH faster than data, which the Chinchilla paper showed was
#   compute-SUBOPTIMAL (many earlier large models were significantly
#   UNDER-TRAINED on data relative to their parameter count, for the
#   compute they'd spent).

def chinchilla_loss(N, D, E=1.5, A=400.0, alpha=0.35, B=400.0, beta=0.35):
    """A simplified Chinchilla-style loss surface -- illustrative
    constants (not literal paper-reported values), chosen to demonstrate
    the SHAPE of the tradeoff, not to reproduce exact published numbers."""
    return E + A / (N ** alpha) + B / (D ** beta)


def find_compute_optimal_allocation(compute_budget, E=1.5, A=400.0, alpha=0.35,
                                     B=400.0, beta=0.35, n_grid=500):
    """
    Grid-searches N (with D = compute_budget / N, enforcing the fixed-
    compute constraint N*D=C directly) to find the loss-minimizing
    allocation -- a direct numerical solution to the constrained
    optimization problem Concept #3 describes, avoiding the need to
    algebraically solve the Lagrangian conditions by hand.
    """
    N_values = np.geomspace(1e6, compute_budget / 1e6, n_grid)
    D_values = compute_budget / N_values
    losses = chinchilla_loss(N_values, D_values, E, A, alpha, B, beta)
    best_idx = np.argmin(losses)
    return N_values[best_idx], D_values[best_idx], losses[best_idx]


def demonstrate_roughly_equal_scaling(compute_budgets, **kwargs):
    """
    Confirms Concept #3's central empirical claim: as compute budget
    grows by some factor, the compute-OPTIMAL N and D each grow by
    ROUGHLY THE SAME factor (when alpha≈beta, as Chinchilla found
    empirically) -- verified here on the simplified model above.
    """
    results = []
    for C in compute_budgets:
        N_opt, D_opt, loss_opt = find_compute_optimal_allocation(C, **kwargs)
        results.append((C, N_opt, D_opt, loss_opt))
    return results


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A research team with a fixed training compute budget is deciding
# between training a 70B-parameter model on 1 trillion tokens versus a
# 30B-parameter model on 2.3 trillion tokens (roughly comparable total
# compute, since compute scales with N*D). Per Concept #3, this is
# EXACTLY the constrained-optimization question Chinchilla's scaling laws
# directly address -- rather than guessing or defaulting to "bigger model
# is always better" (the pre-Chinchilla convention the paper's findings
# specifically corrected), the team should consult (or, if training a
# genuinely novel architecture/domain, empirically fit) their own
# scaling-law curve at smaller scale, then extrapolate the compute-
# optimal (N, D) allocation for their actual target compute budget --
# treating this as a data-informed optimization question with a derivable
# answer, not a matter of institutional convention or intuition about
# "bigger is better."

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Believing "more parameters always means a better model" without
#    reference to the DATA available to train on. Per Concept #3, a
#    large model trained on too little data for its size (undertrained
#    relative to N) can be systematically OUTPERFORMED, for the SAME
#    total compute cost, by a smaller model trained on proportionally
#    more data -- this was the specific, empirically-demonstrated
#    Chinchilla finding that corrected widespread earlier practice.
# 2. Conflating perplexity with accuracy or treating it as directly
#    comparable ACROSS different tokenizers/vocabularies. Per Concept #1,
#    perplexity is defined relative to a SPECIFIC per-token cross-entropy
#    loss, which itself depends on how text was tokenized (L01) -- two
#    models using DIFFERENT tokenizers can have perplexity numbers that
#    aren't directly comparable, since they're measuring "confusion per
#    token" using differently-defined tokens.
# 3. Assuming masked language modeling (MLM) is strictly obsolete because
#    generative LLMs use causal LM. Per Concept #2, MLM's bidirectional-
#    context advantage remains genuinely superior for pure understanding/
#    embedding/classification tasks with no generation requirement --
#    "causal LM is better" is only true SPECIFICALLY for the generative
#    use case, not a universal ranking of the two objectives.
# 4. Treating the Chinchilla scaling law constants (E, A, alpha, B, beta)
#    as universal, architecture-independent physical constants. They are
#    EMPIRICALLY FIT to a specific family of models/data/training setup
#    -- a different architecture, data distribution, or training recipe
#    can genuinely shift these constants, meaning scaling-law-informed
#    decisions should ideally be grounded in curves fit to YOUR specific
#    setup at smaller scale, not blindly imported from a different paper's
#    published constants.


if __name__ == "__main__":
    print("=" * 70)
    print("CONCEPT #1: causal LM loss and perplexity, on a toy example")
    print("=" * 70)
    rng = np.random.default_rng(0)
    seq_len, vocab_size = 5, 20

    # A model outputting exactly UNIFORM logits (all zeros) is maximally
    # "confused" with no confident-but-wrong bets -- its perplexity should
    # equal exactly vocab_size, the textbook reference point.
    uniform_logits = np.zeros((seq_len, vocab_size))
    targets = rng.integers(0, vocab_size, size=seq_len)
    uniform_loss = causal_lm_loss(uniform_logits, targets)
    print(f"Uniform (maximally uncertain) logits -- loss: {uniform_loss:.4f}, "
          f"perplexity: {perplexity(uniform_loss):.2f} (should equal vocab_size={vocab_size} exactly)")

    # RANDOM (non-uniform) logits, by contrast, can be CONFIDENTLY WRONG on
    # some positions -- and confidently-wrong predictions are penalized far
    # more heavily by cross-entropy than uniform uncertainty is, so this can
    # push perplexity ABOVE vocab_size, not toward it.
    random_logits = rng.normal(size=(seq_len, vocab_size)) * 3  # exaggerated confidence
    random_loss = causal_lm_loss(random_logits, targets)
    print(f"Random, confidently-wrong logits -- loss: {random_loss:.4f}, "
          f"perplexity: {perplexity(random_loss):.2f} (can exceed vocab_size --")
    print(f"   confidently wrong is worse than uniformly uncertain, unlike a")
    print(f"   genuinely undertrained-but-calibrated model, which stays near vocab_size)")

    print("\n" + "=" * 70)
    print("CONCEPT #2: causal vs bidirectional attention masks -- what context")
    print("each position can see")
    print("=" * 70)
    causal_mask, bidirectional_mask = demonstrate_bidirectional_vs_causal_context(seq_len=6)
    print("Causal mask (row=query pos, True=can attend):")
    print(causal_mask.astype(int))
    print(f"Causal: position 0 can see {causal_mask[0].sum()} position(s) "
          f"(itself only); position 5 can see {causal_mask[5].sum()} positions (all so far).")
    print(f"Bidirectional: every position can see all {bidirectional_mask[0].sum()} positions.")

    print("\n" + "=" * 70)
    print("CONCEPT #3: compute-optimal N and D scale together as compute grows")
    print("=" * 70)
    budgets = [1e18, 1e19, 1e20, 1e21]
    results = demonstrate_roughly_equal_scaling(budgets)
    print(f"{'compute':>12} {'optimal N':>14} {'optimal D':>14} {'loss':>8}")
    for C, N_opt, D_opt, loss_opt in results:
        print(f"{C:>12.0e} {N_opt:>14.3e} {D_opt:>14.3e} {loss_opt:>8.4f}")
    ratios_N = [results[i+1][1] / results[i][1] for i in range(len(results) - 1)]
    ratios_D = [results[i+1][2] / results[i][2] for i in range(len(results) - 1)]
    print(f"\nPer-10x-compute-step growth factor for N: {np.round(ratios_N, 2)}")
    print(f"Per-10x-compute-step growth factor for D: {np.round(ratios_D, 2)}")
    print("-> With alpha approx. beta, these two growth-factor sequences should be")
    print("   close to each other at every step -- the 'roughly equal scaling'")
    print("   result, reproduced here as a direct numerical optimization,")
    print("   not asserted from the paper's reported conclusion.")
