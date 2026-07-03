# ============================================================
# L01: Tensors and Autograd — Backpropagation From Scratch
# ============================================================
# WHAT: What a tensor actually is (strided memory + shape), and how
#       automatic differentiation (autograd) computes gradients by
#       building a computation graph and running the chain rule backward.
# WHY (RESEARCH + SYSTEMS): Every quantization method you'll study later
#       is fundamentally "how do we approximate this tensor/operation with
#       fewer bits while keeping gradients/outputs close enough." You
#       cannot reason about that without understanding what's actually
#       happening at the tensor/autograd level — not just calling
#       `loss.backward()` and trusting it.
# LEVEL: Foundation (Phase 1 of 8 — Deep Learning Foundations for LLMs)
# ============================================================

"""
CONCEPT OVERVIEW:
A tensor is NOT a magic multi-dimensional array — it's a flat, contiguous
(or strided) block of memory plus metadata (shape, strides, dtype) that
tells you how to interpret that memory as an N-dimensional grid. This
matters immensely for later lessons: quantization repacks this exact
memory layout into fewer bits, and understanding strides is what lets you
understand why some quantization schemes are "free" (just reinterpret
bytes) and others require actual repacking work.

Autograd works by building a DAG (directed acyclic graph) at runtime as
you perform operations. Each node remembers: (1) which operation created
it, (2) references to its input tensors. Calling `.backward()` walks this
graph in reverse topological order, applying the chain rule at each node:
if y = f(x), then dL/dx = dL/dy * dy/dx. Every "layer" you'll ever write
is just a function with a known local derivative; autograd chains these
together for you.

PRODUCTION/RESEARCH USE CASE:
When you later implement GPTQ or AWQ (Phase 4), you'll be computing
Hessians and analyzing per-weight sensitivity to quantization error — this
requires you to understand EXACTLY what gradient/second-derivative
information autograd is giving you, not just call `.backward()` and hope.
When you write a fused dequantize-matmul Triton kernel (Phase 5), you need
to understand tensor memory layout well enough to know when a layout
change would silently break correctness.

COMMON MISTAKES:
- Treating `.backward()` as opaque magic — you cannot debug NaN gradients,
  vanishing gradients, or quantization-induced training instability without
  a mental model of what's actually being computed.
- Confusing a tensor's LOGICAL shape with its MEMORY layout — a
  transpose() in PyTorch doesn't move any memory, it just changes strides;
  this trips people up constantly when writing custom kernels later.
- Forgetting that autograd graphs are built PER FORWARD PASS and freed
  after backward (unless retain_graph=True) — a common source of "trying
  to backward twice" errors.
"""

import math
from typing import Callable, Optional


# ------------------------------------------------------------------
# 1. A minimal scalar autograd engine — this IS what PyTorch does,
#    just without the tensor/GPU/broadcasting machinery.
#    (Inspired by the structure of micrograd — this is the clearest way
#    to internalize the mechanism before trusting a real framework.)
# ------------------------------------------------------------------
class Value:
    """
    A single scalar node in a computation graph. Wraps a float, remembers
    how it was produced (`_prev`, `_op`), and knows how to propagate a
    gradient backward through the operation that created it (`_backward`).
    """

    def __init__(self, data: float, _children: tuple = (), _op: str = ""):
        self.data = data
        self.grad = 0.0                 # dL/d(self) — accumulated during backward()
        self._backward: Callable[[], None] = lambda: None  # local backward rule
        self._prev = set(_children)     # which Values produced this one
        self._op = _op                  # for debugging/visualization only

    def __add__(self, other):
        other = other if isinstance(other, Value) else Value(other)
        out = Value(self.data + other.data, (self, other), "+")

        def _backward():
            # d(out)/d(self) = 1, d(out)/d(other) = 1 — addition just
            # PASSES the upstream gradient through unchanged to both inputs.
            self.grad += 1.0 * out.grad
            other.grad += 1.0 * out.grad

        out._backward = _backward
        return out

    def __mul__(self, other):
        other = other if isinstance(other, Value) else Value(other)
        out = Value(self.data * other.data, (self, other), "*")

        def _backward():
            # Product rule: d(out)/d(self) = other.data, and vice versa.
            # This is the exact mechanism behind every weight update in
            # a neural net — a multiplication's local gradient is simply
            # "the other operand's current value."
            self.grad += other.data * out.grad
            other.grad += self.data * out.grad

        out._backward = _backward
        return out

    def __pow__(self, power: float):
        out = Value(self.data ** power, (self,), f"**{power}")

        def _backward():
            # d(x^p)/dx = p * x^(p-1) — standard power rule.
            self.grad += (power * self.data ** (power - 1)) * out.grad

        out._backward = _backward
        return out

    def relu(self):
        out = Value(max(0.0, self.data), (self,), "relu")

        def _backward():
            # ReLU's local derivative is 1 where input > 0, else 0 — this
            # is exactly why dead ReLUs stop learning: grad is hard-zeroed.
            self.grad += (out.data > 0) * out.grad

        out._backward = _backward
        return out

    def tanh(self):
        t = math.tanh(self.data)
        out = Value(t, (self,), "tanh")

        def _backward():
            # d(tanh(x))/dx = 1 - tanh(x)^2
            self.grad += (1 - t ** 2) * out.grad

        out._backward = _backward
        return out

    def backward(self):
        """
        The core autograd algorithm:
          1. Topologically sort the graph (every node before the nodes
             that depend on it).
          2. Seed the OUTPUT node's gradient to 1.0 (dL/dL = 1).
          3. Walk the topological order IN REVERSE, calling each node's
             local `_backward()`, which accumulates gradient into its
             parents. By the time we reach a node, every node that
             consumes it has already contributed its share — this is
             exactly the chain rule applied node by node.
        """
        topo: list[Value] = []
        visited: set[Value] = set()

        def build_topo(v: "Value"):
            if v not in visited:
                visited.add(v)
                for child in v._prev:
                    build_topo(child)
                topo.append(v)

        build_topo(self)

        self.grad = 1.0  # seed: gradient of the loss w.r.t. itself is 1
        for node in reversed(topo):
            node._backward()

    def __repr__(self):
        return f"Value(data={self.data:.4f}, grad={self.grad:.4f})"

    # Convenience operators so `Value` behaves like a normal number
    def __neg__(self): return self * -1
    def __radd__(self, other): return self + other
    def __sub__(self, other): return self + (-other)
    def __rsub__(self, other): return other + (-self)
    def __rmul__(self, other): return self * other
    def __truediv__(self, other): return self * other ** -1


# ------------------------------------------------------------------
# 2. Worked example: a tiny 2-input, 1-neuron "network" trained by hand
# ------------------------------------------------------------------
def worked_example():
    # y = tanh(w1*x1 + w2*x2 + b) — a single neuron with tanh activation.
    x1, x2 = Value(2.0), Value(0.0)
    w1, w2 = Value(-3.0), Value(1.0)
    b = Value(6.8813735870195432)

    n = x1 * w1 + x2 * w2 + b   # pre-activation
    out = n.tanh()               # activation

    out.backward()  # populates .grad on every node in the graph

    print(f"output = {out.data:.4f}")
    print(f"dL/dw1 = {w1.grad:.4f}  (how much output changes per unit w1)")
    print(f"dL/dw2 = {w2.grad:.4f}")
    print(f"dL/db  = {b.grad:.4f}")
    # These gradients are EXACTLY what an optimizer (see L02) uses to
    # update w1, w2, b — nothing more mysterious happens inside PyTorch.


# ------------------------------------------------------------------
# 3. What a tensor actually is: shape + strides over flat memory
# ------------------------------------------------------------------
class TinyTensor:
    """
    A minimal illustration of PyTorch's actual internal model: a flat
    Python list (standing in for a contiguous memory buffer) plus a shape
    and strides tuple that tells you how to map a multi-dim index into a
    flat offset. This is NOT a full tensor implementation — it exists
    purely to make strides concrete before you hit real PyTorch tensors.
    """

    def __init__(self, data: list, shape: tuple[int, ...]):
        self.data = data          # the actual flat memory
        self.shape = shape
        self.strides = self._compute_strides(shape)

    @staticmethod
    def _compute_strides(shape: tuple[int, ...]) -> tuple[int, ...]:
        # Row-major (C-contiguous) strides: strides[-1] = 1, each earlier
        # stride is the product of all dimension sizes after it. This is
        # exactly how NumPy/PyTorch lay out a default (non-transposed)
        # tensor in memory.
        strides = [1] * len(shape)
        for i in range(len(shape) - 2, -1, -1):
            strides[i] = strides[i + 1] * shape[i + 1]
        return tuple(strides)

    def get(self, *indices: int) -> float:
        # This is the ENTIRE mechanism behind tensor indexing: multiply
        # each index by its stride, sum, look up the flat offset.
        offset = sum(idx * stride for idx, stride in zip(indices, self.strides))
        return self.data[offset]

    def transpose_2d(self) -> "TinyTensor":
        """
        A transpose does NOT copy or move any memory — it just swaps the
        shape and strides. This is why `.transpose()` in PyTorch is O(1),
        but why a transposed tensor is no longer "contiguous" (you often
        need `.contiguous()` before certain kernel calls that assume
        row-major layout — a very common bug source when writing custom
        Triton/CUDA kernels in Phase 5).
        """
        new_shape = (self.shape[1], self.shape[0])
        new_strides = (self.strides[1], self.strides[0])
        t = TinyTensor.__new__(TinyTensor)
        t.data = self.data           # SAME underlying memory, no copy
        t.shape = new_shape
        t.strides = new_strides
        return t


if __name__ == "__main__":
    worked_example()

    # 2x3 matrix stored row-major: [[1,2,3],[4,5,6]]
    t = TinyTensor([1, 2, 3, 4, 5, 6], shape=(2, 3))
    print("t[1,2] =", t.get(1, 2))   # -> 6, the element at row 1, col 2

    tt = t.transpose_2d()
    print("transposed shape:", tt.shape, "strides:", tt.strides)
    # Same memory, reinterpreted — get(2,1) on the transposed view should
    # equal get(1,2) on the original.
    print("tt[2,1] =", tt.get(2, 1))  # -> 6, same value, zero copy

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
When GPTQ (Phase 4) computes a layer-wise Hessian to decide which weights
tolerate quantization error best, it's doing repeated matrix operations
over the SAME memory layout concepts shown here — and when you later write
a custom Triton kernel that reads quantized INT4 weights and dequantizes
them on-the-fly during a matmul, you'll be manually computing offsets from
strides exactly like `TinyTensor.get()` does, except now correctness bugs
show up as silent numerical corruption instead of a Python exception —
which is exactly why this mental model has to be solid before Phase 5.
"""
