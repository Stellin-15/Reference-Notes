"""
WHAT: Supervised fine-tuning (SFT) as continued MLE on a narrower
      distribution, RLHF derived as policy-gradient reinforcement
      learning against a learned reward model (with the KL penalty
      derived as the mechanism preventing reward over-optimization), and
      DPO derived as a mathematical reformulation that reaches an
      equivalent optimum WITHOUT training a separate reward model or
      running RL at all.
WHY:  "RLHF aligns the model to human preferences" and "DPO is a simpler
      alternative to RLHF" are usually stated as facts without the
      derivation connecting them -- this lesson derives WHY RLHF's KL
      penalty is mathematically necessary (not just "a good idea"), and
      walks through the actual algebra showing DPO's loss function is
      derived by substituting RLHF's OWN closed-form optimal policy back
      into the reward model, making the "simplification" a precise
      mathematical identity, not an approximation.
LEVEL: Foundational.

PREREQUISITE: L04 (pretraining objective -- fine-tuning starts from a
pretrained model and modifies the SAME MLE machinery); Classical ML
Theory Notes L02 (MLE/MAP derivation pattern, reused here for SFT).
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — SUPERVISED FINE-TUNING (SFT): THE SAME MLE OBJECTIVE FROM
# L04, ON A DIFFERENT (NARROWER, HIGHER-QUALITY) DISTRIBUTION
# ============================================================================
#
# SFT is NOT a conceptually new training objective -- it is EXACTLY L04's
# causal LM cross-entropy loss, applied to a much smaller, carefully
# curated dataset of high-quality (instruction, response) pairs, starting
# from the ALREADY-PRETRAINED model's weights rather than random
# initialization:
#   minimize  -sum_t log P_theta(response_t | instruction, response_<t)
# The ONLY things that change relative to pretraining are (a) the DATA
# distribution being fit (curated instruction-following examples instead
# of raw internet text) and (b) the STARTING POINT of optimization
# (pretrained weights, not random init).
#
# WHY THIS MATTERS CONCEPTUALLY: SFT is best understood as steering an
# ALREADY-capable model's OUTPUT DISTRIBUTION toward a narrower,
# more-desirable region of the space of things it could say -- the
# pretrained model already has broad world knowledge and language
# capability from L04's massive-scale training; SFT doesn't teach new
# facts so much as teach the model WHICH of its many possible completions
# (all of which it was, in some sense, already capable of generating) to
# actually prefer, given an instruction-following prompt format it may
# have seen only rarely during pretraining's raw-internet-text objective.

def sft_loss(logits, targets, loss_mask):
    """
    Identical mechanically to L04's causal_lm_loss, with one addition:
    loss_mask zeroes out the loss contribution from the INSTRUCTION/
    PROMPT tokens (you don't want to train the model to predict the
    human's own instruction text -- only to predict the DESIRED
    RESPONSE tokens, given that instruction as fixed context). This
    masking detail is a real, easy-to-get-wrong implementation point
    that materially changes what the SFT objective actually teaches if
    omitted.
    """
    seq_len, vocab_size = logits.shape
    max_logits = logits.max(axis=1, keepdims=True)
    log_probs = logits - max_logits - np.log(
        np.sum(np.exp(logits - max_logits), axis=1, keepdims=True))
    correct_log_probs = log_probs[np.arange(seq_len), targets]
    masked_log_probs = correct_log_probs * loss_mask
    return -masked_log_probs.sum() / loss_mask.sum()


# ============================================================================
# CONCEPT #2 — RLHF, PART 1: THE REWARD MODEL, TRAINED ON PAIRWISE
# PREFERENCE DATA
# ============================================================================
#
# SFT alone has a real limitation: it can only teach the model to imitate
# a FIXED set of written example responses. It cannot directly express
# "response A is BETTER than response B" (a comparative, preference-based
# signal), which is often easier for humans to reliably provide than
# writing a single "ideal" response from scratch, and captures nuanced
# QUALITY judgments SFT's imitation objective can't directly encode.
#
# RLHF's first stage trains a separate REWARD MODEL r_phi(x, y) (given a
# prompt x and response y, predict a scalar quality score) on human
# PAIRWISE PREFERENCE data -- humans shown two responses (y_w, the
# "winning"/preferred one, and y_l, the "losing" one) to the SAME prompt.
# The reward model is trained using the BRADLEY-TERRY MODEL of pairwise
# comparison, which assumes:
#   P(y_w preferred over y_l | x) = sigmoid(r_phi(x, y_w) - r_phi(x, y_l))
# This is trained via MLE -- EXACTLY the same logistic-regression-style
# MLE derivation from Classical ML Theory Notes L02, just with the
# "features" being a LEARNED reward difference rather than a fixed linear
# combination of hand-specified features:
#   loss = -log sigmoid(r_phi(x, y_w) - r_phi(x, y_l))
# Minimizing this over many (x, y_w, y_l) preference triples produces a
# reward model that assigns HIGHER scores to responses humans preferred
# -- turning subjective, pairwise human judgments into a differentiable,
# scalar function that can subsequently be used as a training SIGNAL.

def bradley_terry_reward_loss(reward_winner, reward_loser):
    """The reward model's training loss -- Classical ML Theory Notes L02's
    logistic-regression MLE derivation, applied to a LEARNED reward
    difference instead of a fixed linear feature combination."""
    diff = reward_winner - reward_loser
    # -log(sigmoid(diff)), computed in a numerically stable form
    # (softplus(-diff), avoiding direct exp() overflow for large negative diff).
    return np.logaddexp(0, -diff)


# ============================================================================
# CONCEPT #3 — RLHF, PART 2: WHY THE KL PENALTY IS MATHEMATICALLY
# NECESSARY, NOT AN OPTIONAL SAFETY ADD-ON
# ============================================================================
#
# Given the trained reward model, RLHF's second stage optimizes the
# LANGUAGE MODEL POLICY pi_theta to maximize expected reward, via
# reinforcement learning (typically PPO -- Proximal Policy Optimization).
# The NAIVE objective would be simply:
#   maximize  E_{y~pi_theta(.|x)} [ r_phi(x, y) ]
#
# WHY THIS NAIVE OBJECTIVE FAILS CATASTROPHICALLY IN PRACTICE --
# "REWARD HACKING": the reward model r_phi is an IMPERFECT, LEARNED
# APPROXIMATION of true human preference, trained on a finite sample of
# preference comparisons. Unconstrained optimization directly against
# r_phi will, given enough optimization pressure, discover and exploit
# whatever SYSTEMATIC ERRORS/BLIND SPOTS r_phi has -- e.g. if r_phi
# happens to have learned "longer responses tend to score higher"
# (plausible, since human raters may unconsciously favor longer, more
# thorough-SEEMING answers in the preference data), unconstrained RL will
# drive the policy toward producing extremely long, repetitive,
# genuinely LOW-QUALITY responses that nonetheless score artificially
# high under r_phi -- textbook Goodhart's Law ("when a measure becomes a
# target, it ceases to be a good measure").
#
# THE ACTUAL RLHF OBJECTIVE INCLUDES A KL-DIVERGENCE PENALTY, keeping
# the fine-tuned policy pi_theta close to the ORIGINAL SFT policy
# pi_SFT:
#   maximize  E_{y~pi_theta}[ r_phi(x,y) ]  -  beta * KL(pi_theta(.|x) || pi_SFT(.|x))
# THE KL TERM IS NOT AN OPTIONAL SAFETY MARGIN -- it's the mathematically
# necessary constraint preventing the optimization from drifting
# arbitrarily far from a policy the reward model was actually TRAINED to
# meaningfully evaluate. The reward model was trained on preference data
# comparing responses SIMILAR IN CHARACTER to pi_SFT's typical outputs --
# its reward estimates become increasingly UNRELIABLE (out-of-distribution
# for what it learned to judge) the further pi_theta drifts from that
# region, which is EXACTLY the region reward hacking exploits. beta is
# the tunable strength of this constraint -- too small, and reward
# hacking dominates; too large, and the policy barely moves from pi_SFT
# at all, forfeiting RLHF's benefit entirely. This is a direct structural
# parallel to Classical ML Theory Notes L02's regularization-as-implicit-
# capacity-constraint framing: the KL penalty restricts the EFFECTIVE
# space of policies being searched, for exactly the same reason L2
# regularization restricts the effective hypothesis class -- to prevent
# overfitting (here, to the IMPERFECT reward model) at the expense of
# some potential reward-maximization "accuracy."

def kl_divergence_categorical(p, q, eps=1e-10):
    """KL(P||Q) = sum_i P(i) * log(P(i)/Q(i)) -- the exact penalty term
    RLHF's objective subtracts, discouraging the policy from drifting
    too far from the reference (SFT) distribution."""
    p, q = p + eps, q + eps
    return np.sum(p * np.log(p / q))


def demonstrate_reward_hacking_without_kl_penalty(seed=0):
    """
    A toy illustration: an imperfect reward model that (plausibly,
    realistically) over-rewards a SPURIOUS feature (here, simulated as
    response "length") uncorrelated with genuine quality beyond a point.
    Confirms that UNCONSTRAINED reward maximization drifts toward
    exploiting this spurious signal, while a KL-constrained objective
    keeps the policy closer to a reference distribution not chosen
    purely to maximize the (imperfect) reward.
    """
    rng = np.random.default_rng(seed)
    # Simulate response "quality" (unobserved ground truth) vs. "length"
    # (an observed, reward-model-visible proxy the reward model has
    # LEARNED to over-weight, past a reasonable point).
    lengths = np.linspace(0, 10, 200)
    true_quality = -0.1 * (lengths - 4) ** 2 + 5       # peaks at moderate length=4
    learned_reward = 0.5 * lengths + rng.normal(0, 0.1, 200)  # reward model
                                                                 # mistakenly thinks
                                                                 # "longer is just better"

    # Unconstrained: policy would push toward whatever MAXIMIZES learned_reward.
    unconstrained_choice = lengths[np.argmax(learned_reward)]
    # True-quality-optimal choice (what we'd want, if we could observe it directly).
    true_optimal_choice = lengths[np.argmax(true_quality)]

    return unconstrained_choice, true_optimal_choice, true_quality[np.argmax(learned_reward)], true_quality.max()


# ============================================================================
# CONCEPT #4 — DPO: DERIVING AN EQUIVALENT OBJECTIVE WITHOUT A SEPARATE
# REWARD MODEL OR RL AT ALL
# ============================================================================
#
# DPO (Direct Preference Optimization, Rafailov et al. 2023)'s core
# insight is a piece of ALGEBRA, not a new heuristic: the KL-constrained
# RL objective from Concept #3 has a known CLOSED-FORM OPTIMAL SOLUTION
# (a standard result from the theory of KL-regularized RL / maximum-
# entropy RL):
#   pi*(y|x) = (1/Z(x)) * pi_SFT(y|x) * exp( r_phi(x,y) / beta )
# where Z(x) is a normalizing constant (summed/integrated over all
# possible y). REARRANGE this equation to solve for the reward r_phi
# in terms of the OPTIMAL policy pi* (algebra, not an approximation):
#   r_phi(x,y) = beta * log( pi*(y|x) / pi_SFT(y|x) )  +  beta*log(Z(x))
#
# SUBSTITUTE THIS EXPRESSION FOR THE REWARD directly back into the
# Bradley-Terry preference model from Concept #2:
#   P(y_w > y_l | x) = sigmoid( r_phi(x,y_w) - r_phi(x,y_l) )
# The beta*log(Z(x)) term is IDENTICAL for y_w and y_l (both are
# responses to the SAME prompt x, hence the SAME Z(x)) -- it CANCELS
# EXACTLY in the subtraction, leaving:
#   P(y_w > y_l | x) = sigmoid( beta*log(pi_theta(y_w|x)/pi_SFT(y_w|x))
#                              - beta*log(pi_theta(y_l|x)/pi_SFT(y_l|x)) )
# THIS IS DPO'S LOSS FUNCTION -- a preference-classification loss that
# depends ONLY on the POLICY pi_theta and the reference pi_SFT (both
# directly computable via ordinary forward passes, no separate reward
# model and no reinforcement learning loop needed at all), derived by
# ALGEBRAICALLY SUBSTITUTING the RL objective's OWN known optimal-policy
# form back into the SAME Bradley-Terry preference model Concept #2
# already used to train the reward model in the first place. DPO doesn't
# approximate RLHF's objective -- under the stated assumptions (the
# Bradley-Terry preference model, and the KL-regularized-RL closed-form
# solution both holding exactly), directly optimizing DPO's loss reaches
# the IDENTICAL optimal policy pi* that RLHF's full RL procedure was
# targeting all along, via a completely different (and dramatically
# simpler, more stable, no-RL-training-loop-required) optimization path.

def dpo_loss(log_pi_theta_winner, log_pi_ref_winner,
             log_pi_theta_loser, log_pi_ref_loser, beta=0.1):
    """
    log_pi_theta_*: log-probability the CURRENTLY-TRAINING policy
    assigns to the winning/losing response (sum of per-token log-probs,
    i.e. log P_theta(y|x) computed the same way L04's causal LM
    log-likelihood is computed).
    log_pi_ref_*: the SAME quantity under the FROZEN reference (SFT)
    policy -- never updated during DPO training.
    """
    winner_logratio = beta * (log_pi_theta_winner - log_pi_ref_winner)
    loser_logratio = beta * (log_pi_theta_loser - log_pi_ref_loser)
    # -log(sigmoid(diff)), the same numerically-stable form as Concept #2's
    # Bradley-Terry loss -- DPO's loss IS that same loss, with the reward
    # difference substituted for the log-ratio-of-policies difference.
    return np.logaddexp(0, -(winner_logratio - loser_logratio))


def verify_dpo_and_rlhf_objectives_share_the_same_optimum(seed=0):
    """
    A small numerical sanity check of the SUBSTITUTION argument: confirms
    that "reward expressed via the optimal-policy closed form" and "the
    ORIGINAL reward" produce the SAME Bradley-Terry preference
    probability, when the closed-form relationship actually holds exactly
    -- verifying the algebra in Concept #4's derivation is self-consistent,
    not asserting DPO/RLHF are equivalent in every practical respect
    (finite-sample optimization behavior genuinely differs between the two).
    """
    rng = np.random.default_rng(seed)
    beta = 0.5
    # Pick an arbitrary "true" reward function and reference policy.
    r_winner, r_loser = rng.normal(2.0, 0.5), rng.normal(0.5, 0.5)
    log_pi_ref_winner, log_pi_ref_loser = rng.normal(-3, 0.5), rng.normal(-3, 0.5)

    # Closed-form optimal policy (up to the SHARED Z(x), which cancels
    # in any preference comparison, so we can safely omit it here for
    # verification purposes since it never appears in the final DPO loss).
    log_pi_star_winner = log_pi_ref_winner + r_winner / beta
    log_pi_star_loser = log_pi_ref_loser + r_loser / beta

    # Original Bradley-Terry probability, using the RAW reward directly.
    p_via_reward = 1 / (1 + np.exp(-(r_winner - r_loser)))

    # DPO's reformulated probability, using ONLY policy log-ratios (no
    # explicit reward at all) -- should match EXACTLY, since it's the
    # identical quantity, algebraically rearranged.
    logratio_winner = beta * (log_pi_star_winner - log_pi_ref_winner)
    logratio_loser = beta * (log_pi_star_loser - log_pi_ref_loser)
    p_via_dpo = 1 / (1 + np.exp(-(logratio_winner - logratio_loser)))

    return p_via_reward, p_via_dpo


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A team fine-tuning an open-source LLM for a customer-support chatbot
# has to choose between full RLHF and DPO for their preference-alignment
# stage, given a modest infrastructure budget. Per Concept #4's
# derivation, DPO is often the pragmatically preferred choice for smaller
# teams specifically BECAUSE it eliminates two of RLHF's genuinely
# significant engineering costs: training and maintaining a SEPARATE
# reward model (its own training run, its own risk of overfitting/
# miscalibration per Concept #3), and running an RL training LOOP (PPO's
# notoriously finicky hyperparameter sensitivity and training instability,
# a widely-documented practical pain point). DPO's tradeoff, correctly
# understood from Concept #4's derivation rather than treated as strictly
# "simpler is worse" or "simpler is free": DPO's equivalence to RLHF's
# optimum holds under the STATED assumptions (Bradley-Terry preference
# model, exact closed-form policy solution) -- in practice, with finite
# data and imperfect optimization, the two methods' empirical behavior
# can genuinely differ, and DPO forfeits RLHF's ability to reuse the
# SEPARATE reward model for other purposes (e.g. best-of-N re-ranking at
# inference time, a real production pattern DPO's reward-model-free
# approach doesn't directly support without additional machinery).

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Forgetting to mask the instruction/prompt tokens out of the SFT loss
#    (Concept #1). Training the model to also predict/reconstruct the
#    human's own instruction text (rather than only the desired response)
#    dilutes and distorts the actual training signal, a real and easy-to-
#    introduce implementation bug.
# 2. Treating the RLHF KL penalty's beta as a minor hyperparameter to
#    leave at a framework's default value. Per Concept #3, beta directly
#    controls the tradeoff between reward-hacking risk (beta too small)
#    and forfeiting RLHF's benefit entirely (beta too large) -- a load-
#    bearing hyperparameter requiring real tuning, not a default to
#    ignore.
# 3. Believing DPO is "an approximation" of RLHF, when the derivation in
#    Concept #4 shows it's an algebraically EQUIVALENT reformulation
#    under the stated assumptions -- the actual, real-world differences
#    between the two arise from differing OPTIMIZATION dynamics and
#    finite-data/finite-compute practicalities, not from DPO solving a
#    fundamentally different or approximate objective on paper.
# 4. Assuming a reward model trained on pairwise preferences directly
#    produces well-calibrated ABSOLUTE quality scores. The Bradley-Terry
#    model (Concept #2) is trained to get RELATIVE comparisons right
#    (which of two responses is better) -- nothing in this training
#    objective guarantees the raw SCALE of r_phi(x,y) values is
#    meaningful in an absolute sense; only reward DIFFERENCES between
#    compared pairs are directly constrained by the training signal.


if __name__ == "__main__":
    print("=" * 70)
    print("CONCEPT #3: reward hacking -- unconstrained optimization exploits")
    print("an imperfect reward model's blind spot")
    print("=" * 70)
    unconstrained_choice, true_optimal_choice, quality_at_unconstrained, quality_at_optimal = \
        demonstrate_reward_hacking_without_kl_penalty()
    print(f"TRUE-quality-optimal response length: {true_optimal_choice:.2f} "
          f"(true quality there: {quality_at_optimal:.2f})")
    print(f"Reward-model-maximizing response length (unconstrained): "
          f"{unconstrained_choice:.2f} (TRUE quality there: {quality_at_unconstrained:.2f})")
    print(f"Quality gap from chasing the imperfect reward model unconstrained: "
          f"{quality_at_optimal - quality_at_unconstrained:.2f}")
    print("-> Unconstrained reward-maximization drifts to an extreme (max length)")
    print("   the reward model mistakenly favors, at real cost to TRUE quality --")
    print("   exactly what the KL penalty is designed to prevent by keeping the")
    print("   policy near pi_SFT, not near wherever the imperfect reward model peaks.")

    print("\n" + "=" * 70)
    print("CONCEPT #4: DPO's policy-log-ratio formulation matches the original")
    print("Bradley-Terry reward-based probability EXACTLY")
    print("=" * 70)
    p_via_reward, p_via_dpo = verify_dpo_and_rlhf_objectives_share_the_same_optimum()
    print(f"P(winner preferred), computed via the ORIGINAL reward difference: {p_via_reward:.6f}")
    print(f"P(winner preferred), computed via DPO's policy log-ratio difference: {p_via_dpo:.6f}")
    print(f"Exact match? {np.isclose(p_via_reward, p_via_dpo)}")
    print("-> Confirms the algebraic substitution in Concept #4: DPO's loss is")
    print("   the SAME Bradley-Terry objective, reparameterized in terms of the")
    print("   policy directly, not a distinct or approximate alternative to it.")
