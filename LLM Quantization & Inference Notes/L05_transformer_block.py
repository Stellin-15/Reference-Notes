# ============================================================
# L05: The Transformer Block — A Modern (LLaMA-style) Implementation
# ============================================================
# WHAT: A full, working transformer decoder block in PyTorch: RMSNorm,
#       RoPE (rotary positional embeddings), grouped-query attention,
#       and a SwiGLU MLP — the actual architecture used by LLaMA,
#       Mistral, and most current open-weight LLMs (not the original
#       2017 "Attention Is All You Need" block).
# WHY: This is the architecture you'll be quantizing in Phase 3-4. You
#      need to know EXACTLY which tensors exist (Q/K/V/O projections,
#      gate/up/down MLP projections, norm weights) because quantization
#      methods treat different tensor types very differently (norm
#      weights are almost never quantized; MLP weights usually are).
# LEVEL: Foundation (Phase 2 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
Modern LLM blocks differ from the original Transformer paper in three
consistent ways that matter for later phases:

1. RMSNorm instead of LayerNorm — RMSNorm normalizes by root-mean-square
   only (no mean-subtraction, no learned bias), which is cheaper to
   compute and empirically works as well for LLMs. Norm weights are
   small (a single vector per layer) and are almost universally kept at
   full precision even in aggressively quantized models — quantizing
   them saves negligible memory but risks measurable quality loss.

2. RoPE (Rotary Position Embedding) instead of additive sinusoidal
   encoding — instead of ADDING a positional vector to the token
   embedding, RoPE ROTATES the Query and Key vectors by an angle
   proportional to their position, applied INSIDE the attention
   computation. This has a subtle but important property: the dot
   product of two rotated vectors depends only on their RELATIVE
   position, not their absolute position — this is why RoPE-based models
   generalize better to sequence lengths beyond what they were trained on.

3. Grouped-Query Attention (GQA) instead of full multi-head attention —
   multiple Query heads SHARE a smaller number of Key/Value heads. This
   directly shrinks the KV cache (the thing that dominates inference
   memory at long context — see Phase 6), at a small quality cost versus
   full multi-head attention.

4. SwiGLU MLP instead of a plain ReLU MLP — a gated linear unit variant
   that empirically improves quality per parameter, at the cost of a
   THIRD weight matrix (gate, up, down) instead of two (up, down).

PRODUCTION/RESEARCH USE CASE:
When you implement GPTQ/AWQ in Phase 4, you'll quantize `gate_proj`,
`up_proj`, `down_proj`, and the attention `q/k/v/o_proj` matrices — but
NOT the RMSNorm weights or (usually) the embedding/output head at the
same aggressiveness. Knowing the actual tensor names and shapes here is
what lets you read a real HuggingFace model's `state_dict()` and know
exactly what you're looking at.

COMMON MISTAKES:
- Applying RoPE to the WHOLE Q/K vector when a model spec says "partial
  rotary" (rotate only a fraction of dimensions) — a common bug when
  porting between model families that changes numerical outputs subtly.
- Forgetting that GQA's KV heads are REPEATED (not summed or projected)
  across the query heads that share them — an incorrect repeat/reshape
  here silently produces wrong attention patterns without crashing.
- Using LayerNorm's mean-subtraction reasoning when reasoning about
  RMSNorm — RMSNorm has NO mean-centering step, so intuition from
  BatchNorm/LayerNorm papers doesn't transfer directly.
"""

import math
import torch
import torch.nn as nn
import torch.nn.functional as F


# ------------------------------------------------------------------
# 1. RMSNorm
# ------------------------------------------------------------------
class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))  # the ONLY learned param

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # RMS = sqrt(mean(x^2)) — no mean-subtraction, unlike LayerNorm.
        # Normalizing by RMS keeps the SCALE of activations controlled
        # without needing to also re-center them, which turns out to be
        # unnecessary for transformer activations in practice.
        rms = x.pow(2).mean(dim=-1, keepdim=True).add(self.eps).sqrt()
        return (x / rms) * self.weight


# ------------------------------------------------------------------
# 2. RoPE — rotary positional embeddings
# ------------------------------------------------------------------
def precompute_rope_freqs(dim: int, max_seq_len: int, base: float = 10000.0):
    """
    Computes the rotation angle for each (position, dimension-pair). Each
    pair of dimensions rotates at a DIFFERENT frequency — low dimensions
    rotate fast (encode fine-grained relative position), high dimensions
    rotate slow (encode coarse-grained relative position), directly
    analogous to the different sinusoid frequencies in L03's additive
    positional encoding — but here the position information is injected
    via ROTATION, not addition.
    """
    # inv_freq[i] = 1 / base^(2i/dim), one frequency per dimension pair
    inv_freq = 1.0 / (base ** (torch.arange(0, dim, 2).float() / dim))
    positions = torch.arange(max_seq_len).float()
    # Outer product: angle for every (position, frequency) combination
    freqs = torch.outer(positions, inv_freq)              # (seq_len, dim/2)
    return torch.cos(freqs), torch.sin(freqs)              # each (seq_len, dim/2)


def apply_rope(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    """
    Applies the rotation to Q or K. Splits the last dimension into pairs
    and rotates each pair by its precomputed angle — mathematically this
    is a 2D rotation matrix applied per pair:
        [x1']   [cos -sin] [x1]
        [x2'] = [sin  cos] [x2]
    """
    x1, x2 = x[..., 0::2], x[..., 1::2]   # even/odd dimension interleave
    rotated = torch.stack([
        x1 * cos - x2 * sin,
        x1 * sin + x2 * cos,
    ], dim=-1)
    return rotated.flatten(-2)


# ------------------------------------------------------------------
# 3. Grouped-Query Attention
# ------------------------------------------------------------------
class GroupedQueryAttention(nn.Module):
    def __init__(self, d_model: int, num_q_heads: int, num_kv_heads: int, max_seq_len: int):
        super().__init__()
        assert num_q_heads % num_kv_heads == 0, "Q heads must divide evenly into KV heads"
        self.num_q_heads = num_q_heads
        self.num_kv_heads = num_kv_heads
        self.group_size = num_q_heads // num_kv_heads   # how many Q heads share 1 KV head
        self.d_head = d_model // num_q_heads

        # Note the ASYMMETRIC output sizes: Q projects to the full
        # num_q_heads, but K/V project to the SMALLER num_kv_heads — this
        # asymmetry is exactly what shrinks the KV cache in Phase 6.
        self.q_proj = nn.Linear(d_model, num_q_heads * self.d_head, bias=False)
        self.k_proj = nn.Linear(d_model, num_kv_heads * self.d_head, bias=False)
        self.v_proj = nn.Linear(d_model, num_kv_heads * self.d_head, bias=False)
        self.o_proj = nn.Linear(num_q_heads * self.d_head, d_model, bias=False)

        cos, sin = precompute_rope_freqs(self.d_head, max_seq_len)
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch, seq_len, _ = x.shape

        q = self.q_proj(x).view(batch, seq_len, self.num_q_heads, self.d_head)
        k = self.k_proj(x).view(batch, seq_len, self.num_kv_heads, self.d_head)
        v = self.v_proj(x).view(batch, seq_len, self.num_kv_heads, self.d_head)

        cos = self.rope_cos[:seq_len].unsqueeze(0).unsqueeze(2)  # broadcast over batch/heads
        sin = self.rope_sin[:seq_len].unsqueeze(0).unsqueeze(2)
        q = apply_rope(q, cos, sin)
        k = apply_rope(k, cos, sin)

        # REPEAT (not project) each KV head to match its group of Q heads
        # — this is the exact mechanism that makes GQA "grouped": the K/V
        # computation happens once per KV head, but is reused (via a
        # cheap repeat, not recomputation) across `group_size` Q heads.
        k = k.repeat_interleave(self.group_size, dim=2)
        v = v.repeat_interleave(self.group_size, dim=2)

        q, k, v = (t.transpose(1, 2) for t in (q, k, v))  # (batch, heads, seq, d_head)

        out = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        out = out.transpose(1, 2).reshape(batch, seq_len, -1)
        return self.o_proj(out)


# ------------------------------------------------------------------
# 4. SwiGLU MLP
# ------------------------------------------------------------------
class SwiGLU(nn.Module):
    def __init__(self, d_model: int, d_ff: int):
        super().__init__()
        # THREE weight matrices, not two — this is the specific parameter
        # cost of SwiGLU vs a plain ReLU MLP, and it's why d_ff is
        # usually scaled down (e.g. to 8/3 * d_model) to keep total
        # parameter count comparable to a standard 4x-expansion ReLU MLP.
        self.gate_proj = nn.Linear(d_model, d_ff, bias=False)
        self.up_proj = nn.Linear(d_model, d_ff, bias=False)
        self.down_proj = nn.Linear(d_ff, d_model, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # SiLU(gate(x)) * up(x) — the gate branch acts as a learned,
        # per-element multiplicative "how much of up(x) to let through."
        return self.down_proj(F.silu(self.gate_proj(x)) * self.up_proj(x))


# ------------------------------------------------------------------
# 5. Full transformer block
# ------------------------------------------------------------------
class TransformerBlock(nn.Module):
    def __init__(self, d_model: int, num_q_heads: int, num_kv_heads: int,
                 d_ff: int, max_seq_len: int):
        super().__init__()
        self.attn_norm = RMSNorm(d_model)
        self.attn = GroupedQueryAttention(d_model, num_q_heads, num_kv_heads, max_seq_len)
        self.mlp_norm = RMSNorm(d_model)
        self.mlp = SwiGLU(d_model, d_ff)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Pre-norm residual structure: normalize BEFORE the sublayer, add
        # the sublayer's output as a residual. Pre-norm (vs the original
        # Transformer's post-norm) is what makes deep transformers
        # trainable without extremely careful learning-rate warmup.
        x = x + self.attn(self.attn_norm(x))
        x = x + self.mlp(self.mlp_norm(x))
        return x


if __name__ == "__main__":
    torch.manual_seed(0)
    d_model, num_q_heads, num_kv_heads, d_ff, max_seq_len = 512, 8, 2, 1408, 2048
    block = TransformerBlock(d_model, num_q_heads, num_kv_heads, d_ff, max_seq_len)

    x = torch.randn(2, 16, d_model)   # (batch=2, seq_len=16, d_model=512)
    out = block(x)
    print("output shape:", out.shape)   # -> torch.Size([2, 16, 512])

    total_params = sum(p.numel() for p in block.parameters())
    print(f"parameters in one block: {total_params:,}")
    for name, p in block.named_parameters():
        print(f"  {name:30s} {tuple(p.shape)}")

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
When you load a real LLaMA-family model's state_dict in Phase 4 to run
GPTQ on it, the tensor names you'll see (`q_proj.weight`, `k_proj.weight`,
`gate_proj.weight`, `up_proj.weight`, `down_proj.weight`, plus
`input_layernorm.weight`) map EXACTLY onto the modules built here — this
lesson exists so that when a quantization paper says "we quantize all
linear layers except norms," you know precisely which tensors that means
and can write code that correctly targets them.
"""
