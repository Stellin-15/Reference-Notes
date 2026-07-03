# ============================================================
# L15: GGUF and K-Quants — llama.cpp's Quantization Format
# ============================================================
# WHAT: The block-wise quantization scheme (K-quants) behind GGUF, the
#       file format llama.cpp (and most CPU/consumer-GPU-friendly
#       inference tools) uses — implemented from scratch, including the
#       "superblock" hierarchical scaling structure.
# WHY (SYSTEMS): This is the format you'll actually SHIP if your goal is
#      "make AI easier to run on real (often non-datacenter) hardware."
#      Understanding its exact bit-packing is a direct prerequisite for
#      Phase 5's kernel work, where you'll write code that reads this
#      exact memory layout.
# LEVEL: Advanced (Phase 4 of 8 — final research-methods lesson before kernels)
# ============================================================

"""
CONCEPT OVERVIEW:
GGUF ("GPT-Generated Unified Format") is a FILE FORMAT (metadata + tensor
data layout), distinct from the quantization SCHEME it typically carries —
K-quants. K-quants use a two-level HIERARCHICAL block structure:

  - Each tensor is split into "superblocks" of 256 consecutive values.
  - Each superblock is further split into smaller sub-blocks (e.g. 16
    values each, 16 sub-blocks per superblock).
  - Each SUB-BLOCK gets its own quantized scale factor.
  - Each SUPERBLOCK gets ONE overall scale that the sub-block scales are
    themselves expressed RELATIVE to (the sub-block scales are stored as
    SMALL quantized values too, not full floats) — this is the key
    efficiency trick: rather than storing a full FP16 scale (16 bits) per
    small sub-block, K-quants store a coarser, cheaper representation of
    each sub-block scale relative to its superblock's single float scale.

This is a deliberate point on the granularity-vs-overhead Pareto curve
from L11: per-sub-block granularity (fine, accurate) WITHOUT paying the
full memory cost of a full-precision scale per sub-block (because
sub-block scales are themselves compressed, relative to their superblock).

Naming: `Q4_K_M` means "4-bit K-quant, Medium variant" — the letter suffix
(S/M/L for Small/Medium/Large) indicates which LAYERS get quantized more
vs less aggressively within the same nominal bit-width (K-quants often mix
precision ACROSS layers too — e.g. attention output projections might get
slightly higher effective precision than MLP layers, since empirically
they're more sensitive).

PRODUCTION/RESEARCH USE CASE:
GGUF/K-quants are the dominant format for CPU inference and for running
models on consumer GPUs via llama.cpp — if your "make AI easier on
hardware" project targets people running models locally without a
datacenter GPU, this exact format (or something directly inspired by it)
is very likely what you'll be reading, writing, or extending.

COMMON MISTAKES:
- Assuming "Q4" always means the SAME thing across different quant
  schemes — GPTQ's "4-bit," AWQ's "4-bit," and GGUF's "Q4_K_M" all pack
  bits differently and have different accuracy/speed tradeoffs; the bit
  count alone is not a complete specification.
- Miscounting the ACTUAL average bits-per-weight — K-quants' hierarchical
  scale overhead means "4-bit" K-quants are actually closer to 4.5-5.5
  bits per weight once superblock/sub-block scale storage is counted;
  this matters when comparing memory footprint against other schemes.
- Getting the superblock/sub-block indexing wrong when implementing a
  reader/writer for the format — an off-by-one in block boundaries
  silently corrupts every weight after the first mistake, since the
  format is a tightly packed byte stream with no delimiters.
"""

import struct
import torch


# ------------------------------------------------------------------
# 1. A simplified two-level block quantization scheme (K-quant style)
# ------------------------------------------------------------------
SUPERBLOCK_SIZE = 256
SUBBLOCK_SIZE = 16
NUM_SUBBLOCKS = SUPERBLOCK_SIZE // SUBBLOCK_SIZE  # 16


def kquant_encode_superblock(values: torch.Tensor, num_bits: int = 4) -> dict:
    """
    Encodes ONE superblock (256 values) using the hierarchical scheme:
      1. Split into 16 sub-blocks of 16 values each.
      2. Compute a full-precision scale PER SUB-BLOCK.
      3. Find the MAX sub-block scale — this becomes the superblock's
         single FP16 "master scale."
      4. Re-express each sub-block's scale as a SMALL QUANTIZED fraction
         of the master scale (e.g. a 6-bit value, 0-63), rather than
         storing each sub-block scale at full FP16 precision.
      5. Quantize each value using its sub-block's (now-quantized)
         effective scale.
    """
    assert values.numel() == SUPERBLOCK_SIZE
    qmax = 2 ** (num_bits - 1) - 1

    subblocks = values.view(NUM_SUBBLOCKS, SUBBLOCK_SIZE)
    subblock_scales_fp = subblocks.abs().amax(dim=1) / qmax        # (16,) full precision
    subblock_scales_fp = subblock_scales_fp.clamp(min=1e-8)

    master_scale = subblock_scales_fp.max()                         # ONE float for the whole superblock

    # Quantize each sub-block scale to a small integer (6 bits: 0-63)
    # RELATIVE to the master scale — this is the actual memory-saving
    # trick: instead of 16 x FP16 (16 x 16 = 256 bits) for sub-block
    # scales, we store 16 x 6-bit values (96 bits) plus one FP16 master
    # scale (16 bits) = 112 bits total, a real, quantifiable savings.
    scale_qmax = 2 ** 6 - 1
    quantized_subblock_scales = (subblock_scales_fp / master_scale * scale_qmax).round().clamp(0, scale_qmax)
    reconstructed_subblock_scales = quantized_subblock_scales / scale_qmax * master_scale

    quantized_values = torch.zeros_like(subblocks, dtype=torch.int8)
    for i in range(NUM_SUBBLOCKS):
        scale = reconstructed_subblock_scales[i]
        quantized_values[i] = (subblocks[i] / scale).round().clamp(-qmax, qmax).to(torch.int8)

    return {
        "master_scale": master_scale.item(),
        "quantized_subblock_scales": quantized_subblock_scales.to(torch.uint8),
        "quantized_values": quantized_values,
        "num_bits": num_bits,
    }


def kquant_decode_superblock(encoded: dict) -> torch.Tensor:
    scale_qmax = 2 ** 6 - 1
    subblock_scales = (
        encoded["quantized_subblock_scales"].float() / scale_qmax * encoded["master_scale"]
    )
    values = torch.zeros(NUM_SUBBLOCKS, SUBBLOCK_SIZE)
    for i in range(NUM_SUBBLOCKS):
        values[i] = encoded["quantized_values"][i].float() * subblock_scales[i]
    return values.flatten()


# ------------------------------------------------------------------
# 2. Computing the ACTUAL average bits-per-weight (accounting for overhead)
# ------------------------------------------------------------------
def compute_effective_bits_per_weight(num_bits: int) -> float:
    """
    For a single superblock (256 values):
      - 256 * num_bits bits for the quantized values themselves
      - 16 * 6 bits for the quantized sub-block scales
      - 16 bits (one FP16) for the master scale
    Divide the TOTAL by 256 to get the true effective bits/weight —
    this is the number that should be compared against GPTQ/AWQ's
    group_size overhead (L11), not the nominal "4-bit" label alone.
    """
    value_bits = SUPERBLOCK_SIZE * num_bits
    subblock_scale_bits = NUM_SUBBLOCKS * 6
    master_scale_bits = 16
    total_bits = value_bits + subblock_scale_bits + master_scale_bits
    return total_bits / SUPERBLOCK_SIZE


# ------------------------------------------------------------------
# 3. Reading/writing the format at the byte level (a minimal illustration)
# ------------------------------------------------------------------
def pack_int4_pairs(values: torch.Tensor) -> bytes:
    """
    4-bit values can't be individually addressed at the byte level —
    real GGUF packs TWO 4-bit values into each byte (nibble packing).
    This is the exact kind of bit-level packing you'll need to replicate
    correctly when writing a custom kernel that reads GGUF files
    directly in Phase 5.
    """
    assert values.numel() % 2 == 0
    packed = bytearray()
    flat = values.flatten().tolist()
    for i in range(0, len(flat), 2):
        # Values are stored as UNSIGNED 4-bit (0-15) with a bias, not
        # signed — real K-quants store an offset-encoded unsigned nibble;
        # here we assume values are already offset into [0, 15].
        low = flat[i] & 0x0F
        high = flat[i + 1] & 0x0F
        packed.append(low | (high << 4))
    return bytes(packed)


def unpack_int4_pairs(packed: bytes) -> list[int]:
    values = []
    for byte in packed:
        values.append(byte & 0x0F)          # low nibble
        values.append((byte >> 4) & 0x0F)   # high nibble
    return values


if __name__ == "__main__":
    torch.manual_seed(0)
    superblock = torch.randn(SUPERBLOCK_SIZE) * 0.05
    # Inject a bit of within-superblock variance to make the hierarchical
    # scheme's benefit visible (constant-scale superblocks wouldn't show
    # any advantage over a single flat scale).
    superblock[:64] *= 3

    encoded = kquant_encode_superblock(superblock, num_bits=4)
    decoded = kquant_decode_superblock(encoded)
    mse = (superblock - decoded).pow(2).mean().item()
    print(f"K-quant (hierarchical) MSE: {mse:.6f}")

    # Compare against a FLAT single-scale quantization of the same data
    flat_scale = superblock.abs().max() / 7  # 4-bit symmetric qmax=7
    flat_quantized = (superblock / flat_scale).round().clamp(-7, 7) * flat_scale
    flat_mse = (superblock - flat_quantized).pow(2).mean().item()
    print(f"Flat single-scale MSE:      {flat_mse:.6f}")

    print(f"\nEffective bits/weight for nominal 4-bit K-quant: "
          f"{compute_effective_bits_per_weight(4):.3f}")

    print("\nInt4 nibble packing round-trip:")
    test_values = torch.tensor([1, 15, 0, 8, 3, 12])
    packed = pack_int4_pairs(test_values)
    print("  packed bytes:", packed.hex())
    print("  unpacked:", unpack_int4_pairs(packed))

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
When you write a custom Triton kernel in Phase 5 that reads GGUF-format
Q4_K weights directly (dequantizing on-the-fly during a matmul, never
materializing the full FP16 weight in memory), you will be implementing
EXACTLY the hierarchical decode shown in `kquant_decode_superblock()`,
except inside a GPU kernel operating on thousands of superblocks in
parallel — getting the sub-block/superblock indexing arithmetic right
here, in slow readable Python first, is what makes debugging the much
less forgiving GPU kernel version tractable later.
"""
