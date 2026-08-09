"""
WHAT: The vanishing/exploding gradient problem derived quantitatively for
      vanilla RNNs (as a product of many Jacobians through time), and
      LSTM/GRU gating mechanisms derived as a direct, targeted fix for
      that specific derived problem.
WHY:  "RNNs suffer from vanishing gradients over long sequences, LSTMs
      fix this with gates" is usually stated without showing WHY the
      gradient vanishes (it's a product of T Jacobian terms, each <1)
      or WHY a gate specifically breaks that multiplicative chain. This
      lesson derives both, using the SAME reverse-mode-autodiff machinery
      from L01, just applied to a network with a loop.
LEVEL: Foundational.

PREREQUISITE: L01 (backprop -- this lesson is "backprop through time" as
a specific instance of the general algorithm, with parameter reuse from
L01's Concept #3, gradient accumulation, as the central mechanism).
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — BACKPROPAGATION THROUGH TIME (BPTT) IS ORDINARY BACKPROP
# ON AN "UNROLLED" GRAPH, WITH THE SAME WEIGHTS REUSED AT EVERY STEP
# ============================================================================
#
# A vanilla RNN computes a sequence of hidden states:
#   h_t = tanh(W_hh * h_{t-1} + W_xh * x_t + b)
# for t = 1..T, using the SAME W_hh, W_xh, b at EVERY timestep -- this is
# EXACTLY L01's Concept #3 (parameter reuse / gradient accumulation)
# applied across time instead of across a batch. "Unroll" the recurrence
# into a T-layer feedforward-looking computation graph (h_0 -> h_1 -> ...
# -> h_T), and ordinary backprop applies UNCHANGED -- the only thing
# distinguishing "BPTT" from plain backprop is that W_hh appears as an
# input to EVERY one of the T layers, so its gradient (per Concept #3's
# accumulation rule) is a SUM over T separate contributions, one per
# timestep:
#   dL/dW_hh = sum_{t=1}^{T} dL_t/dW_hh   (roughly; the precise
#              derivation also has each h_t's loss contribution flowing
#              backward through ALL subsequent timesteps' hidden-state
#              dependencies, not just its own timestep)
#
# This reframing (BPTT = backprop on an unrolled graph, nothing new) is
# the right way to hold this algorithm in your head -- it removes any
# mystery about why RNN training needs a "special" algorithm; it needs
# the SAME algorithm, applied to a graph shaped like a chain instead of
# a stack.

# ============================================================================
# CONCEPT #2 — THE VANISHING/EXPLODING GRADIENT PROBLEM, DERIVED
# QUANTITATIVELY AS A PRODUCT OF T JACOBIANS
# ============================================================================
#
# To compute dL/dh_1 (how the loss depends on the FIRST hidden state,
# needed to update W_xh/W_hh's contribution from early timesteps), the
# chain rule must pass the gradient backward through EVERY intermediate
# hidden state:
#   dL/dh_1 = dL/dh_T * dh_T/dh_{T-1} * dh_{T-1}/dh_{T-2} * ... * dh_2/dh_1
#
# Each factor dh_t/dh_{t-1} is the JACOBIAN of one recurrence step:
#   dh_t/dh_{t-1} = diag(1 - tanh(z_t)^2) * W_hh
#   (tanh's derivative, per L01's Value.tanh backward rule, times W_hh
#   itself -- the chain rule applied to h_t = tanh(W_hh*h_{t-1}+...))
#
# THE GRADIENT FLOWING BACK TO EARLY TIMESTEPS IS THE PRODUCT OF T-1
# SUCH JACOBIANS. Two things make this product pathological for even
# moderately large T:
#   1. tanh'(z) = 1-tanh(z)^2 is ALWAYS <= 1 (equal to 1 only exactly at
#      z=0, and rapidly approaching 0 as |z| grows) -- so EVERY factor in
#      the product is already capped at <=1 purely from the activation
#      function, before even considering W_hh.
#   2. If the largest eigenvalue (spectral radius) of W_hh is < 1, the
#      product of T such matrices shrinks GEOMETRICALLY (like
#      lambda_max^T) toward the zero matrix as T grows -- VANISHING
#      gradients, meaning early timesteps effectively stop receiving any
#      training signal at all for long sequences (the RNN can't learn to
#      use information from far in the past).
#   3. If the spectral radius is > 1, the SAME product GROWS
#      geometrically -- EXPLODING gradients, causing numerically huge,
#      destabilizing parameter updates.
# There is no "sweet spot" spectral radius that avoids both failure modes
# simultaneously across ARBITRARY sequence lengths -- exactly 1 is an
# unstable equilibrium, not a robustly maintainable operating point
# during training (W_hh keeps changing every gradient step).

def vanilla_rnn_forward_and_grad_norm(W_hh, x_seq, h0, seed=0):
    """
    Runs a vanilla RNN forward, computes a toy loss depending on the
    FINAL hidden state, and returns ||dL/dh_t|| for every t -- making the
    geometric decay (or growth) predicted by Concept #2 directly
    observable rather than asserted.
    """
    T = len(x_seq)
    hidden_dim = W_hh.shape[0]
    rng = np.random.default_rng(seed)
    W_xh = rng.normal(0, 0.5, size=(hidden_dim, 1))

    h = [h0]
    z_list = []
    for t in range(T):
        z = W_hh @ h[-1] + W_xh.flatten() * x_seq[t]
        z_list.append(z)
        h.append(np.tanh(z))

    # Toy loss: squared error between final hidden state and a target.
    target = np.ones(hidden_dim) * 0.5
    dL_dhT = 2 * (h[-1] - target)  # dL/dh_T

    # Backpropagate dL/dh_t through EVERY timestep, exactly the chain-rule
    # product from Concept #2, tracking the gradient norm at each step.
    grad = dL_dhT
    grad_norms = [np.linalg.norm(grad)]
    for t in reversed(range(T)):
        tanh_deriv = 1 - np.tanh(z_list[t]) ** 2  # diag(1-tanh(z)^2), as a vector
        # dh_t/dh_{t-1} = diag(tanh_deriv) @ W_hh -- apply this Jacobian
        # (transposed, since we're propagating a gradient/row-vector backward).
        grad = (tanh_deriv * grad) @ W_hh
        grad_norms.append(np.linalg.norm(grad))

    return list(reversed(grad_norms))  # index 0 = earliest timestep


# ============================================================================
# CONCEPT #3 — LSTM'S GATES DERIVED AS A DIRECT FIX: REPLACE THE
# MULTIPLICATIVE tanh-CHAIN WITH AN ADDITIVE, GATED PATHWAY
# ============================================================================
#
# The vanilla RNN's core problem (Concept #2) is that information MUST
# pass through a tanh nonlinearity and a multiplication by W_hh at EVERY
# single timestep to survive to a distant future step -- there's no way
# to "skip" this repeated shrinking operation. LSTM's central innovation
# is the CELL STATE c_t, which is updated ADDITIVELY (not purely
# multiplicatively) and can, in principle, carry information across many
# timesteps with much less forced decay:
#   f_t = sigmoid(W_f * [h_{t-1}, x_t] + b_f)     <- FORGET gate
#   i_t = sigmoid(W_i * [h_{t-1}, x_t] + b_i)     <- INPUT gate
#   c_tilde_t = tanh(W_c * [h_{t-1}, x_t] + b_c)  <- candidate new content
#   c_t = f_t * c_{t-1}  +  i_t * c_tilde_t        <- KEY: ADDITIVE update
#   o_t = sigmoid(W_o * [h_{t-1}, x_t] + b_o)     <- OUTPUT gate
#   h_t = o_t * tanh(c_t)
#
# WHY THE ADDITIVE c_t UPDATE SPECIFICALLY FIXES THE GRADIENT PROBLEM:
# differentiate c_t = f_t*c_{t-1} + i_t*c_tilde_t with respect to c_{t-1}:
#   dc_t/dc_{t-1} = f_t + [terms involving how f_t,i_t,c_tilde_t THEMSELVES
#                           depend on c_{t-1} through h_{t-1}]
# The DOMINANT term is simply f_t (the forget gate's value) -- if the
# network LEARNS to set f_t close to 1 (a gate value, bounded in [0,1] by
# the sigmoid, that the network controls based on the CURRENT input/
# context), the gradient dc_t/dc_{t-1} stays close to 1, and the product
# of T such terms does NOT geometrically vanish the way the vanilla RNN's
# tanh'(z)*W_hh product does -- because f_t is not FORCED to be <1 by the
# architecture (unlike tanh'(z), which mathematically cannot exceed 1),
# the network has an explicit, LEARNABLE mechanism for choosing to
# preserve gradient flow when the task calls for it (long-range
# dependencies) and to actively forget when it doesn't. This is a direct,
# derivable fix targeted exactly at the mechanism Concept #2 identified
# as the cause, not a generic "add more parameters and hope."

class LSTMCell:
    def __init__(self, input_dim, hidden_dim, rng):
        concat_dim = input_dim + hidden_dim
        scale = np.sqrt(1.0 / concat_dim)
        self.W_f = rng.normal(0, scale, (hidden_dim, concat_dim))
        self.W_i = rng.normal(0, scale, (hidden_dim, concat_dim))
        self.W_c = rng.normal(0, scale, (hidden_dim, concat_dim))
        self.W_o = rng.normal(0, scale, (hidden_dim, concat_dim))
        self.hidden_dim = hidden_dim

    @staticmethod
    def sigmoid(z):
        return 1.0 / (1.0 + np.exp(-z))

    def step(self, x_t, h_prev, c_prev):
        concat = np.concatenate([h_prev, x_t])
        f_t = self.sigmoid(self.W_f @ concat)
        i_t = self.sigmoid(self.W_i @ concat)
        c_tilde = np.tanh(self.W_c @ concat)
        c_t = f_t * c_prev + i_t * c_tilde     # the additive update, Concept #3
        o_t = self.sigmoid(self.W_o @ concat)
        h_t = o_t * np.tanh(c_t)
        return h_t, c_t, f_t


def lstm_cell_state_gradient_survival(lstm, x_seq, forget_bias_shift=0.0):
    """
    Runs an LSTM forward and measures how much dc_T/dc_1 survives (i.e.
    the product of forget gates across the whole sequence) -- the direct
    LSTM analogue of Concept #2's vanilla-RNN gradient-norm measurement,
    showing the SAME kind of quantity but through the additive cell-state
    pathway instead of the multiplicative hidden-state pathway.
    forget_bias_shift lets us simulate "the network learned to keep the
    forget gate open" (a large positive bias pushes sigmoid(z) near 1).
    """
    T = len(x_seq)
    h = np.zeros(lstm.hidden_dim)
    c = np.zeros(lstm.hidden_dim)
    forget_gate_values = []
    for t in range(T):
        concat = np.concatenate([h, x_seq[t]])
        f_t = lstm.sigmoid(lstm.W_f @ concat + forget_bias_shift)
        i_t = lstm.sigmoid(lstm.W_i @ concat)
        c_tilde = np.tanh(lstm.W_c @ concat)
        c = f_t * c + i_t * c_tilde
        o_t = lstm.sigmoid(lstm.W_o @ concat)
        h = o_t * np.tanh(c)
        forget_gate_values.append(f_t.mean())
    # The product of forget-gate values approximates how much of dc_1's
    # gradient survives (via the DOMINANT f_t term) all the way to c_T.
    cumulative_survival = np.prod(forget_gate_values)
    return forget_gate_values, cumulative_survival


# ============================================================================
# CONCEPT #4 — GRU: A SIMPLER GATING SCHEME, AND THE GENUINE TRADEOFF
# VERSUS LSTM
# ============================================================================
#
# GRU (Gated Recurrent Unit) merges LSTM's forget/input gates into a
# single UPDATE gate and removes the separate cell state (using only the
# hidden state h_t directly as the carried-forward memory):
#   z_t = sigmoid(W_z * [h_{t-1}, x_t])            <- UPDATE gate
#   r_t = sigmoid(W_r * [h_{t-1}, x_t])            <- RESET gate
#   h_tilde_t = tanh(W_h * [r_t * h_{t-1}, x_t])
#   h_t = (1 - z_t) * h_{t-1}  +  z_t * h_tilde_t   <- ADDITIVE update,
#                                                        same core mechanism
#                                                        as LSTM's c_t
#
# THE SAME ADDITIVE-UPDATE MECHANISM FROM CONCEPT #3 IS PRESENT (h_t is a
# convex combination of h_{t-1} and a new candidate, gated by a LEARNABLE
# z_t) -- GRU fixes the SAME vanishing-gradient problem via essentially
# the SAME mechanism, just with fewer distinct gates (2 vs LSTM's 3) and
# no separate cell state. GRU has fewer parameters (roughly 3/4 of an
# equivalently-sized LSTM, since it has 3 weight matrices per layer
# instead of 4) and is correspondingly somewhat faster to train.
#
# THE GENUINE, CONTESTED TRADEOFF: empirical comparisons across many
# tasks show NEITHER LSTM nor GRU consistently dominates the other --
# GRU often matches LSTM's accuracy with fewer parameters on many tasks,
# but LSTM's extra gate (the separate input/forget distinction, and the
# separate cell state c_t decoupled from the OUTPUT-facing h_t) gives it
# strictly more representational flexibility in principle, which some
# tasks with particularly long or complex dependency structure benefit
# from measurably. There is no universally correct choice -- this is a
# genuine instance of Classical ML Theory Notes L01's No Free Lunch
# theorem playing out concretely between two closely related
# architectures, not a settled "GRU is the modern replacement for LSTM"
# claim (a common oversimplification).


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A team training a vanilla RNN on customer-session sequences (predicting
# churn from up to 500 sequential events) observes the model performs
# well on customers who churn within the first ~20 events but fails to
# capture patterns building up over longer sessions. Per Concept #2, this
# is the textbook symptom of vanishing gradients over long sequences --
# confirming it doesn't require guesswork: instrumenting the training run
# to log gradient norms at early vs. late timesteps (exactly what
# vanilla_rnn_forward_and_grad_norm demonstrates) would show near-zero
# gradient magnitude reaching the early portions of long sequences,
# directly diagnosing the mechanism rather than just observing the
# downstream symptom. The fix that directly targets this diagnosed cause
# is switching to an LSTM/GRU (or, per this repo's LLM Core Theory Notes,
# an attention-based architecture that avoids sequential gradient
# propagation through time entirely) -- not, e.g., more training data or
# a deeper stack of vanilla RNN layers, neither of which addresses the
# actual mechanism identified.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Believing LSTMs/GRUs are "immune" to vanishing gradients entirely.
#    Per Concept #3, they substantially MITIGATE it (the forget gate
#    CAN learn to stay near 1), but there's no mathematical guarantee it
#    always does -- a poorly-initialized or poorly-trained LSTM can still
#    learn forget-gate values that decay, and very long sequences (many
#    thousands of steps) can still pose real difficulty even with gating.
# 2. Initializing the LSTM forget-gate bias to zero (a common default)
#    without considering the consequence. sigmoid(0)=0.5 means EVERY
#    memory cell starts by default forgetting roughly half its content
#    every timestep -- many practitioners deliberately initialize the
#    forget-gate bias to a positive value (commonly 1.0-2.0) specifically
#    to bias the network toward "remember by default," easing early
#    training on tasks with genuine long-range dependencies.
# 3. Assuming "GRU is just a simplified/strictly worse LSTM" or "GRU is
#    the modern default that replaced LSTM." Per Concept #4, empirical
#    performance is genuinely task-dependent -- treat the choice as a
#    hyperparameter to validate empirically on your specific task, not a
#    settled architectural upgrade path in either direction.
# 4. Conflating BPTT's need to "unroll" a sequence with an architectural
#    limitation of RNNs specifically. Per Concept #1, this is just
#    ordinary backprop on a longer graph -- the actual scaling problem is
#    MEMORY (storing every intermediate h_t/c_t for the backward pass
#    costs memory proportional to sequence length T), which is why
#    "truncated BPTT" (splitting long sequences into shorter chunks,
#    accepting some loss of true long-range gradient signal) is a real,
#    common production tradeoff, not a design flaw unique to recurrent
#    architectures.


if __name__ == "__main__":
    print("=" * 70)
    print("CONCEPT #2: vanilla RNN gradient norm vanishes across timesteps")
    print("=" * 70)
    rng = np.random.default_rng(0)
    hidden_dim = 8
    T = 30
    x_seq = rng.normal(size=T)
    h0 = rng.normal(0, 0.3, size=hidden_dim)
    # A W_hh with spectral radius < 1 -- deliberately shrinks each recurrence step.
    W_hh_raw = rng.normal(0, 1, size=(hidden_dim, hidden_dim))
    W_hh = W_hh_raw / (np.max(np.abs(np.linalg.eigvals(W_hh_raw))) * 1.1)  # spectral radius ~0.91
    grad_norms = vanilla_rnn_forward_and_grad_norm(W_hh, x_seq, h0)
    print(f"Gradient norm reaching timestep  1: {grad_norms[0]:.8f}")
    print(f"Gradient norm reaching timestep 15: {grad_norms[14]:.8f}")
    print(f"Gradient norm reaching timestep 30: {grad_norms[29]:.8f}")
    print("-> Gradient norm should shrink by orders of magnitude from t=30 to")
    print("   t=1, confirming geometric vanishing across just 30 timesteps.")

    print("\n" + "=" * 70)
    print("CONCEPT #3: LSTM forget gate lets gradient signal survive far longer")
    print("=" * 70)
    lstm = LSTMCell(input_dim=1, hidden_dim=8, rng=rng)
    x_seq_2 = [rng.normal(size=1) for _ in range(T)]
    # forget_bias_shift=2.0 simulates a network that LEARNED to keep the
    # forget gate open (biased toward "remember"), per common mistake #2 below.
    fg_values_open, survival_open = lstm_cell_state_gradient_survival(
        lstm, x_seq_2, forget_bias_shift=2.0)
    fg_values_default, survival_default = lstm_cell_state_gradient_survival(
        lstm, x_seq_2, forget_bias_shift=0.0)
    print(f"Mean forget-gate value with bias=+2.0 (learned to remember): "
          f"{np.mean(fg_values_open):.4f}")
    print(f"Mean forget-gate value with bias=0.0 (default init):         "
          f"{np.mean(fg_values_default):.4f}")
    print(f"Cumulative gradient survival over {T} steps -- bias=+2.0: {survival_open:.6f}")
    print(f"Cumulative gradient survival over {T} steps -- bias=0.0:  {survival_default:.10f}")
    print("-> A forget-gate bias favoring 'remember' preserves vastly more")
    print("   gradient signal across the same 30 timesteps than the default,")
    print("   confirming Concept #3's mechanism directly and motivating")
    print("   Common Mistake #2's positive forget-gate-bias initialization advice.")
