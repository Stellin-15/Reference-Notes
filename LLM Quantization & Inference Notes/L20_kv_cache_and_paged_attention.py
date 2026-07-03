# ============================================================
# L20: KV Cache and PagedAttention
# ============================================================
# WHAT: Why autoregressive generation caches Key/Value tensors, the exact
#       memory cost of that cache (and why it dominates inference memory
#       at long context), and PagedAttention (vLLM's technique for
#       managing that memory efficiently, borrowed directly from OS
#       virtual memory paging).
# WHY (SYSTEMS): The KV cache is THE dominant memory consumer for serving
#      real inference workloads (not the model weights, past a certain
#      context length/batch size) — you cannot design a serving system
#      without understanding this, and quantizing the KV cache itself is
#      an active, directly-relevant research area.
# LEVEL: Systems Core (Phase 6 of 8 — Inference Engine Internals)
# ============================================================

"""
CONCEPT OVERVIEW:
Recall attention (L03): computing token T's output requires the Key and
Value vectors of EVERY token up to and including T. Without caching,
generating token T+1 would require RECOMPUTING K/V for all T prior tokens
— wasteful, since those K/V vectors don't change once computed (they only
depend on earlier tokens, which are fixed by the time you're generating
token T+1). The KV CACHE stores every previously-computed K/V pair, so
generating each new token only computes ONE new K/V pair (for the new
token) and reuses everything else.

The memory cost is substantial: for each token, you store 2 (K and V) *
num_layers * num_kv_heads * d_head values. For a 32-layer, 8-KV-head (GQA),
128-d_head model in FP16, that's 2*32*8*128*2 bytes = 131KB PER TOKEN. At
a 32K context length, that's ~4.3GB — for A SINGLE sequence. This is why
serving many concurrent users at long context is fundamentally a MEMORY
problem, and why KV cache quantization (storing K/V in INT8 instead of
FP16) is a direct, high-value application of everything from Phase 3.

PagedAttention (vLLM's core contribution) addresses a DIFFERENT problem:
naive KV cache allocation reserves a CONTIGUOUS block of memory sized for
the MAXIMUM possible sequence length up front, for every request — this
wastes enormous memory on requests that finish early (a huge fraction of
allocated-but-unused memory, directly analogous to internal fragmentation
in OS memory management). PagedAttention borrows the OS's VIRTUAL MEMORY
PAGING solution directly: the KV cache is divided into small, fixed-size
"blocks" (pages), allocated ON DEMAND as a sequence grows, and a
"block table" per sequence maps logical token positions to physical
memory blocks (which need NOT be contiguous) — exactly like a page table
maps virtual addresses to physical memory pages.

PRODUCTION/RESEARCH USE CASE:
This is why vLLM can serve significantly higher THROUGHPUT (more
concurrent requests) than a naive implementation with the same GPU memory
— PagedAttention eliminates the wasted, over-allocated memory, letting
more actual KV cache data fit in the same VRAM, which directly translates
to serving more concurrent sequences.

COMMON MISTAKES:
- Forgetting that the KV cache SIZE depends on `num_kv_heads` (from GQA,
  L05), not `num_q_heads` — this is precisely WHY GQA was introduced: it
  directly and deliberately shrinks the KV cache, independent of any
  quantization technique.
- Assuming PagedAttention changes the ATTENTION MATH — it does not; it
  is purely a MEMORY MANAGEMENT technique. The attention computation
  itself is unchanged; only how the K/V tensors are physically laid out
  and addressed in memory changes.
- Quantizing the KV cache without accounting for its DIFFERENT
  distributional properties than weights — K/V tensors are activations
  (see L14's outlier discussion), not weights, and often need different
  quantization granularity/calibration than weight quantization schemes.
"""

from dataclasses import dataclass, field


# ------------------------------------------------------------------
# 1. Exact KV cache memory accounting
# ------------------------------------------------------------------
def kv_cache_bytes_per_token(num_layers: int, num_kv_heads: int,
                               d_head: int, dtype_bytes: int = 2) -> int:
    # 2 for K AND V, both stored per layer per KV head.
    return 2 * num_layers * num_kv_heads * d_head * dtype_bytes


def kv_cache_total_gb(num_layers: int, num_kv_heads: int, d_head: int,
                        seq_len: int, batch_size: int, dtype_bytes: int = 2) -> float:
    per_token = kv_cache_bytes_per_token(num_layers, num_kv_heads, d_head, dtype_bytes)
    return per_token * seq_len * batch_size / 1e9


def kv_cache_scaling_demo():
    # A LLaMA-2-7B-scale config: 32 layers, 32 heads (assume GQA with 8 KV heads), d_head=128.
    num_layers, num_kv_heads, d_head = 32, 8, 128

    print("KV cache size at various (seq_len, batch_size), FP16:")
    for seq_len in (2048, 8192, 32768):
        for batch_size in (1, 8, 32):
            gb = kv_cache_total_gb(num_layers, num_kv_heads, d_head, seq_len, batch_size, dtype_bytes=2)
            print(f"  seq_len={seq_len:6d}  batch={batch_size:3d}  ->  {gb:7.2f} GB")

    print("\nSame scenario with INT8 KV cache (half the bytes):")
    gb_int8 = kv_cache_total_gb(num_layers, num_kv_heads, d_head, 32768, 32, dtype_bytes=1)
    gb_fp16 = kv_cache_total_gb(num_layers, num_kv_heads, d_head, 32768, 32, dtype_bytes=2)
    print(f"  FP16: {gb_fp16:.2f} GB   INT8: {gb_int8:.2f} GB   "
          f"savings: {gb_fp16 - gb_int8:.2f} GB — often enough to fit "
          f"meaningfully more concurrent requests in the same VRAM budget.")


# ------------------------------------------------------------------
# 2. PagedAttention — block-based KV cache management
# ------------------------------------------------------------------
@dataclass
class KVCacheBlock:
    """One fixed-size physical block of KV cache memory (a 'page')."""
    block_id: int
    capacity_tokens: int
    tokens_used: int = 0

    @property
    def is_full(self) -> bool:
        return self.tokens_used >= self.capacity_tokens


@dataclass
class SequenceBlockTable:
    """
    The per-sequence 'page table' — maps LOGICAL token positions to
    PHYSICAL block IDs, exactly analogous to an OS virtual-memory page
    table mapping virtual addresses to physical page frames.
    """
    sequence_id: int
    block_ids: list[int] = field(default_factory=list)


class PagedKVCacheManager:
    """
    A simplified illustration of vLLM's block manager: allocates fixed-
    size blocks ON DEMAND as sequences grow, instead of reserving a
    worst-case-sized contiguous allocation per sequence up front.
    """

    def __init__(self, total_blocks: int, block_size_tokens: int):
        self.block_size_tokens = block_size_tokens
        self.free_blocks: list[int] = list(range(total_blocks))
        self.blocks: dict[int, KVCacheBlock] = {
            i: KVCacheBlock(block_id=i, capacity_tokens=block_size_tokens)
            for i in range(total_blocks)
        }
        self.sequence_tables: dict[int, SequenceBlockTable] = {}

    def allocate_for_new_sequence(self, sequence_id: int) -> bool:
        if not self.free_blocks:
            return False  # out of KV cache memory — caller must wait/evict
        block_id = self.free_blocks.pop()
        self.sequence_tables[sequence_id] = SequenceBlockTable(
            sequence_id=sequence_id, block_ids=[block_id]
        )
        return True

    def append_token(self, sequence_id: int) -> bool:
        """
        Called once per generated token. Only allocates a NEW block when
        the sequence's current last block is full — this is the exact
        mechanism that avoids over-provisioning memory for sequences that
        end up shorter than the maximum possible length.
        """
        table = self.sequence_tables[sequence_id]
        last_block = self.blocks[table.block_ids[-1]]

        if last_block.is_full:
            if not self.free_blocks:
                return False  # cache exhausted
            new_block_id = self.free_blocks.pop()
            table.block_ids.append(new_block_id)
            last_block = self.blocks[new_block_id]

        last_block.tokens_used += 1
        return True

    def free_sequence(self, sequence_id: int):
        """Returns all of a finished sequence's blocks to the free pool."""
        table = self.sequence_tables.pop(sequence_id)
        for block_id in table.block_ids:
            block = self.blocks[block_id]
            block.tokens_used = 0
            self.free_blocks.append(block_id)

    def memory_utilization(self) -> float:
        used_blocks = len(self.blocks) - len(self.free_blocks)
        return used_blocks / len(self.blocks)


def paged_attention_demo():
    manager = PagedKVCacheManager(total_blocks=20, block_size_tokens=16)

    # Simulate 3 concurrent sequences of DIFFERENT lengths — the exact
    # scenario where naive fixed-max-length allocation wastes memory.
    for seq_id, length in [(1, 10), (2, 50), (3, 5)]:
        manager.allocate_for_new_sequence(seq_id)
        for _ in range(length):
            success = manager.append_token(seq_id)
            if not success:
                print(f"  sequence {seq_id}: out of KV cache memory!")
                break

    for seq_id in (1, 2, 3):
        blocks_used = len(manager.sequence_tables[seq_id].block_ids)
        print(f"sequence {seq_id}: {blocks_used} physical blocks allocated "
              f"({blocks_used * manager.block_size_tokens} token capacity)")

    print(f"\noverall memory utilization: {manager.memory_utilization():.1%}")

    manager.free_sequence(1)
    print(f"after freeing sequence 1: {manager.memory_utilization():.1%} utilization, "
          f"{len(manager.free_blocks)} blocks now free for new requests")


if __name__ == "__main__":
    kv_cache_scaling_demo()
    print()
    paged_attention_demo()

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
A production inference server handling many concurrent users with wildly
different prompt/generation lengths is EXACTLY the scenario
PagedAttention was designed for — without it, a server provisioning KV
cache for a worst-case 32K context per request could serve far fewer
concurrent SHORT requests than the hardware's actual memory would allow,
because most of that reserved memory sits unused. Combining PagedAttention
(memory management) with KV cache quantization (from L09-L11, applied to
K/V tensors instead of weights) compounds both effects — this exact
combination is precisely where cutting-edge inference-serving research
currently lives.
"""
