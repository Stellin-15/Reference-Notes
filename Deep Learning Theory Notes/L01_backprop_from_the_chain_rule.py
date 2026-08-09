"""
WHAT: Backpropagation derived as a direct, mechanical application of the
      multivariate chain rule to a computation graph -- not "the algorithm
      neural nets use," but the specific, inevitable consequence of
      wanting dL/d(every parameter) in a layered function composition.
WHY:  "Backprop computes gradients efficiently via the chain rule" is true
      but empty until you've actually propagated a gradient backward
      through a graph by hand and seen WHY it's dramatically cheaper than
      the naive alternative (numerical/symbolic differentiation of the
      whole composed function). This lesson builds a tiny autograd engine
      from scratch so every subsequent Deep Learning Theory lesson can
      say "the gradient flows through here" and mean something concrete.
LEVEL: Foundational (read first in this domain).

PREREQUISITE: Classical ML Theory Notes L01-L02 (gradient descent,
MLE-derived losses); Data Science Fundamentals Notes L04 (gradient
descent mechanics).
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — WHY THE CHAIN RULE, AND WHY NOT JUST DIFFERENTIATE THE WHOLE
# COMPOSED FUNCTION DIRECTLY
# ============================================================================
#
# A neural network is a composition of functions: given input x,
#   z1 = W1*x + b1;      a1 = f(z1)
#   z2 = W2*a1 + b2;      a2 = f(z2)
#   ...
#   L  = loss(a_final, y)
#
# You need dL/dW1, dL/db1, dL/dW2, ... for EVERY parameter, to run
# gradient descent. In principle you could write L as one giant nested
# expression in terms of every W_i, b_i and differentiate it directly --
# but that expression, for a real network, has millions of parameters
# appearing through many layers of nested function calls. Two facts make
# the naive approach (differentiate the whole nested expression, or
# recompute the whole forward pass 2*p times for numerical finite-
# difference gradients on p parameters) intractable:
#
#   1. NUMERICAL DIFFERENTIATION cost: estimating dL/dtheta_i by finite
#      differences (perturb theta_i by epsilon, recompute L, subtract,
#      divide by epsilon) costs one full forward pass PER PARAMETER. For
#      a model with a million parameters, that's a million forward
#      passes to get ONE gradient step -- computationally absurd, and it
#      still only APPROXIMATES the true gradient (finite-difference
#      error).
#   2. SYMBOLIC DIFFERENTIATION of the fully-expanded expression suffers
#      "expression swell" -- repeatedly applying the chain rule
#      symbolically to a deeply composed function can produce an
#      expression whose SIZE grows exponentially in the depth of
#      composition, because shared sub-expressions get needlessly
#      re-expanded/re-derived independently at each occurrence.
#
# THE CHAIN RULE, APPLIED IN A SPECIFIC ORDER (backward, reusing
# intermediate results), avoids BOTH problems. For y=f(g(x)):
#   dy/dx = dy/dg * dg/dx
# Backprop applies this repeatedly, layer by layer, from the OUTPUT
# backward to the INPUT, and -- critically -- REUSES each layer's
# gradient-so-far (dL/da_i, called the "upstream gradient" or "adjoint")
# rather than re-deriving it from scratch for every downstream parameter
# that depends on it. This reuse is exactly what makes backprop's cost
# O(1) forward-pass-equivalents (roughly 2x-3x one forward pass) to get
# ALL parameter gradients simultaneously, regardless of how many
# parameters there are -- a qualitatively different cost profile than
# either alternative above.

# ============================================================================
# CONCEPT #2 — A COMPUTATION GRAPH AND REVERSE-MODE AUTODIFF, BUILT FROM
# SCRATCH
# ============================================================================
#
# Every operation (add, multiply, matmul, an activation function) is a
# NODE in a directed acyclic graph. Reverse-mode autodiff (what "backprop"
# specifically refers to) does two passes:
#   FORWARD PASS: compute the actual output value of each node, in
#                 topological (input-to-output) order, caching each
#                 node's output (needed later for the backward pass's
#                 local-derivative computations).
#   BACKWARD PASS: starting from dL/dL=1 at the final loss node, visit
#                 nodes in REVERSE topological order. At each node,
#                 given the UPSTREAM gradient (dL/d(this node's output)),
#                 compute dL/d(each of this node's inputs) via the local
#                 derivative rule for that specific operation, multiplied
#                 by the upstream gradient (exactly the chain rule) --
#                 and ACCUMULATE (sum) gradients at any node that has
#                 multiple downstream consumers (the multivariate chain
#                 rule's sum-over-paths rule, Concept #3 below).
#
# This tiny "Value" class implements exactly that -- a minimal, from-
# scratch reverse-mode autodiff engine (the same core idea underlying
# PyTorch's autograd, at a fraction of the engineering, with none of the
# performance optimization).

class Value:
    """A scalar that remembers how it was computed, so gradients can be
    propagated backward through the exact sequence of operations that
    produced it."""

    def __init__(self, data, _children=(), _op=""):
        self.data = data
        self.grad = 0.0
        self._backward = lambda: None  # how to propagate gradient TO children
        self._prev = set(_children)
        self._op = _op

    def __add__(self, other):
        other = other if isinstance(other, Value) else Value(other)
        out = Value(self.data + other.data, (self, other), "+")

        def _backward():
            # d(out)/d(self) = 1, d(out)/d(other) = 1 -- local derivative
            # of addition is just 1 for each input. Chain rule: multiply
            # by the upstream gradient (out.grad) and ACCUMULATE (+=, not
            # =) because a Value can be used in multiple places (Concept #3).
            self.grad += 1.0 * out.grad
            other.grad += 1.0 * out.grad
        out._backward = _backward
        return out

    def __mul__(self, other):
        other = other if isinstance(other, Value) else Value(other)
        out = Value(self.data * other.data, (self, other), "*")

        def _backward():
            # d(out)/d(self) = other.data, d(out)/d(other) = self.data --
            # the product rule's local derivatives.
            self.grad += other.data * out.grad
            other.grad += self.data * out.grad
        out._backward = _backward
        return out

    def __pow__(self, power):
        out = Value(self.data ** power, (self,), f"**{power}")

        def _backward():
            # d(x^n)/dx = n*x^(n-1) -- the power rule.
            self.grad += (power * self.data ** (power - 1)) * out.grad
        out._backward = _backward
        return out

    def relu(self):
        out = Value(max(0.0, self.data), (self,), "ReLU")

        def _backward():
            # d(ReLU(x))/dx = 1 if x>0 else 0 -- a hard gate on the
            # gradient, the exact mechanism behind Deep Learning Theory
            # Notes L03/L04's "dead ReLU" discussion.
            self.grad += (1.0 if self.data > 0 else 0.0) * out.grad
        out._backward = _backward
        return out

    def tanh(self):
        t = np.tanh(self.data)
        out = Value(t, (self,), "tanh")

        def _backward():
            # d(tanh(x))/dx = 1 - tanh(x)^2 -- derived from tanh's
            # definition via the quotient rule; this exact term is the
            # source of vanishing gradients discussed in this domain's
            # RNN lesson (it's always <=1, and often << 1 away from x=0).
            self.grad += (1 - t ** 2) * out.grad
        out._backward = _backward
        return out

    def backward(self):
        """Topologically sort the graph, then walk it in reverse,
        calling each node's local _backward() -- this IS backpropagation,
        end to end, in nine lines."""
        topo = []
        visited = set()

        def build_topo(v):
            if v not in visited:
                visited.add(v)
                for child in v._prev:
                    build_topo(child)
                topo.append(v)
        build_topo(self)

        self.grad = 1.0  # dL/dL = 1, the base case of the chain rule
        for v in reversed(topo):
            v._backward()

    def __repr__(self):
        return f"Value(data={self.data:.4f}, grad={self.grad:.4f})"

    def __neg__(self):
        return self * -1

    def __sub__(self, other):
        return self + (-other if isinstance(other, Value) else Value(-other))

    def __rsub__(self, other):
        return Value(other) + (-self)

    def __truediv__(self, other):
        other = other if isinstance(other, Value) else Value(other)
        return self * other ** -1

    __radd__ = __add__
    __rmul__ = __mul__


# ============================================================================
# CONCEPT #3 — THE MULTIVARIATE CHAIN RULE'S "SUM OVER PATHS" RULE (why
# gradients ACCUMULATE, not overwrite, at shared nodes)
# ============================================================================
#
# If a value x feeds into TWO different downstream computations that both
# eventually affect L (e.g. a shared hidden activation used by two
# different output heads, or -- most commonly -- a WEIGHT reused at every
# timestep of an RNN, this domain's L06), the multivariate chain rule
# says:
#   dL/dx = sum over every path from x to L of (product of local
#           derivatives along that path)
# This is NOT a special case needing special handling -- it's why the
# Value class above uses += (accumulate) rather than = (overwrite) in
# every _backward function. If x is used twice, build_topo visits it
# once, but BOTH usages call their own _backward(), each contributing
# ANOTHER additive term to x.grad. Get this wrong (use = instead of +=)
# and you silently compute the WRONG gradient for any parameter reused
# more than once -- which, in a real network, is essentially every weight
# matrix (used once per example in the batch, and in RNNs, once per
# timestep) -- making this a real, easy-to-introduce bug in a hand-rolled
# autodiff engine, not a theoretical footnote.

def demonstrate_gradient_accumulation():
    """x used TWICE in computing L=(x+x)*x = 2x^2+0... let's use x in two
    genuinely different branches: L = x*x + x -- dL/dx should be 2x+1 by
    ordinary single-variable calculus. Confirm the autodiff engine gets
    this right ONLY because of gradient accumulation at x."""
    x = Value(3.0)
    L = x * x + x  # x is a child of BOTH the multiplication and the addition
    L.backward()
    analytical = 2 * x.data + 1  # d(x^2+x)/dx = 2x+1, ordinary calculus
    return x.grad, analytical


# ============================================================================
# CONCEPT #4 — A TWO-LAYER NEURAL NET, TRAINED END TO END WITH THIS
# FROM-SCRATCH ENGINE
# ============================================================================
#
# Confirms the whole chain (forward pass -> loss -> backward() -> gradient
# descent update) actually trains something, using nothing but the Value
# class above -- no autograd library, so every gradient that flows is one
# you could, in principle, hand-trace back to the chain-rule applications
# in Concepts #2-#3.

class Neuron:
    def __init__(self, n_inputs, rng):
        self.w = [Value(rng.uniform(-1, 1)) for _ in range(n_inputs)]
        self.b = Value(0.0)

    def __call__(self, x):
        act = sum((wi * xi for wi, xi in zip(self.w, x)), self.b)
        return act.relu()

    def parameters(self):
        return self.w + [self.b]


class Layer:
    def __init__(self, n_inputs, n_outputs, rng):
        self.neurons = [Neuron(n_inputs, rng) for _ in range(n_outputs)]

    def __call__(self, x):
        outs = [n(x) for n in self.neurons]
        return outs

    def parameters(self):
        return [p for n in self.neurons for p in n.parameters()]


class MLP:
    def __init__(self, n_inputs, layer_sizes, rng):
        sizes = [n_inputs] + layer_sizes
        self.layers = [Layer(sizes[i], sizes[i + 1], rng) for i in range(len(layer_sizes))]

    def __call__(self, x):
        for layer in self.layers:
            x = layer(x)
        return x

    def parameters(self):
        return [p for layer in self.layers for p in layer.parameters()]


def train_tiny_mlp():
    rng = np.random.default_rng(0)
    model = MLP(n_inputs=2, layer_sizes=[4, 1], rng=rng)

    # A tiny, genuinely nonlinear dataset (XOR) -- the canonical proof
    # that a network needs a HIDDEN layer + nonlinearity to solve, tying
    # directly back to Classical ML Theory Notes L08's XOR discussion.
    X = [[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]]
    Y = [0.0, 1.0, 1.0, 0.0]

    lr = 0.1
    losses = []
    for step in range(300):
        # ---- forward pass ----
        preds = [model([Value(xi) for xi in x])[0] for x in X]
        loss = sum((p - Value(y)) ** 2 for p, y in zip(preds, Y)) * (1.0 / len(Y))

        # ---- backward pass ----
        for p in model.parameters():
            p.grad = 0.0  # MUST zero gradients before each backward() call,
                           # or Concept #3's accumulation adds this step's
                           # gradient on top of the PREVIOUS step's --
                           # exactly the real "forgot optimizer.zero_grad()"
                           # bug production PyTorch code is equally prone to.
        loss.backward()

        # ---- gradient descent update ----
        for p in model.parameters():
            p.data -= lr * p.grad

        losses.append(loss.data)

    return losses, model, X, Y


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A team debugging a training run that silently diverges after adding a
# custom loss term (a hand-written regularization penalty) traces the bug
# to exactly Concept #3: the custom penalty term reused an intermediate
# activation tensor that was ALSO consumed by the main loss, and a custom
# autograd Function they'd written manually assigned (=) rather than
# accumulated (+=) the incoming gradient at that shared tensor -- silently
# discarding the main loss's gradient contribution whenever the backward
# pass visited the penalty branch after the main branch. This is precisely
# the bug demonstrate_gradient_accumulation() is built to catch: any
# custom autodiff code (a custom CUDA kernel's backward pass, a custom
# `torch.autograd.Function`) that doesn't accumulate gradients at reused
# nodes will silently corrupt gradients for exactly the class of models
# (anything with parameter sharing: RNNs, Siamese networks, weight-tied
# embeddings) where reuse is common, not rare.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Forgetting to zero gradients before calling backward() again. Per
#    Concept #3's accumulation rule, gradients ADD onto whatever is
#    already in .grad -- if you don't reset to zero before each new
#    backward pass, step 2's gradient silently includes step 1's leftover
#    gradient, corrupting every subsequent update. This is real production
#    PyTorch code's single most common beginner bug (`optimizer.zero_grad()`
#    exists specifically to prevent it), not just a hand-rolled-engine risk.
# 2. Assuming symbolic/numerical differentiation and backprop compute
#    DIFFERENT gradients. They compute the mathematically IDENTICAL
#    gradient (up to numerical precision) -- backprop's advantage is
#    purely computational efficiency (Concept #1), not a different or
#    approximate answer.
# 3. Believing backprop requires the loss function or activations to be
#    "backprop-specific" in some way. Any function built from
#    differentiable (or subgradient-defined, like ReLU at 0) primitive
#    operations automatically supports backprop -- there's no separate
#    "backprop-compatible" design constraint beyond differentiability of
#    the pieces.
# 4. Confusing "backpropagation" (the specific reverse-mode chain-rule
#    algorithm) with "gradient descent" (the optimization algorithm that
#    USES the gradients backprop computes). They're different, composable
#    concepts -- backprop answers "what is dL/dtheta," gradient descent
#    (and its variants, this domain's L02) answers "given dL/dtheta, how
#    do I update theta."


if __name__ == "__main__":
    print("=" * 70)
    print("CONCEPT #3: gradient accumulation at a reused node")
    print("=" * 70)
    autodiff_grad, analytical_grad = demonstrate_gradient_accumulation()
    print(f"Autodiff-computed dL/dx:  {autodiff_grad:.6f}")
    print(f"Hand-derived dL/dx=2x+1:  {analytical_grad:.6f}")
    print(f"Match? {np.isclose(autodiff_grad, analytical_grad)}")
    print("-> Correct ONLY because the engine accumulates (+=) gradients")
    print("   at x, which is used in both the '*' and '+' operations.")

    print("\n" + "=" * 70)
    print("CONCEPT #4: training a tiny from-scratch MLP on XOR")
    print("=" * 70)
    losses, model, X, Y = train_tiny_mlp()
    print(f"Loss at step 0:   {losses[0]:.4f}")
    print(f"Loss at step 299: {losses[-1]:.4f}")
    preds = [model([Value(xi) for xi in x])[0].data for x in X]
    for x, y, p in zip(X, Y, preds):
        print(f"  input={x}  target={y}  predicted={p:.4f}")
    print("-> Loss should have dropped substantially and predictions should")
    print("   be close to their XOR targets -- confirming this from-scratch")
    print("   chain-rule engine actually trains a genuinely nonlinear function,")
    print("   using nothing but Concepts #1-#3.")
