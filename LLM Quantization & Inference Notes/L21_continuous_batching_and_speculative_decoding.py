# ============================================================
# L21: Continuous Batching and Speculative Decoding
# ============================================================
# WHAT: Continuous (in-flight) batching — the scheduling technique that
#       lets an inference server keep GPU utilization high despite
#       requests arriving and finishing at different times — and
#       speculative decoding, which uses a small "draft" model to
#       generate multiple tokens per large-model forward pass.
# WHY (SYSTEMS): Both techniques attack the SAME underlying problem from
#      different angles: LLM decode is memory-bandwidth-bound (L17), so
#      batch size 1 wastes most of the GPU's compute capability. These
#      are the two dominant real-world techniques for closing that gap
#      in production serving systems.
# LEVEL: Systems Core (Phase 6 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
STATIC BATCHING (the naive approach): collect a batch of N requests,
run them ALL through the model together until the SLOWEST one finishes,
then start a new batch. This wastes GPU time whenever requests in the
batch finish generating at different points — a request that needed 20
tokens sits idle (or its slot is wasted) while another in the same batch
needs 500 tokens.

CONTINUOUS BATCHING (a.k.a. in-flight batching, from the Orca paper,
used by vLLM/TGI/etc.): at EVERY decoding step, the scheduler checks
which sequences in the current batch have finished, REMOVES them, and
ADMITS new waiting requests to fill the freed slots — the batch
COMPOSITION changes every single step. This keeps the GPU consistently
busy with a full batch, dramatically improving throughput versus static
batching, at the cost of real scheduling complexity (deciding admission
order, handling the fact that different sequences are at different
points in their generation).

SPECULATIVE DECODING attacks the memory-bandwidth bottleneck differently:
instead of changing batching, it changes HOW MANY TOKENS one full-model
forward pass produces. A small, fast "draft" model generates K candidate
tokens autoregressively (cheap, since it's small). The LARGE target model
then does ONE forward pass over ALL K draft tokens SIMULTANEOUSLY
(scored in parallel, not autoregressively) and ACCEPTS the longest
prefix of draft tokens that match what the large model would have
generated itself (verified via a specific acceptance-probability rule
that guarantees the output distribution is IDENTICAL to always running
the large model alone — this exactness guarantee is the subtle,
important part of the technique). Rejected tokens are discarded and
replaced with a token sampled from the large model. Net effect: multiple
tokens are produced per EXPENSIVE large-model forward pass, exploiting
the fact that scoring K tokens in parallel costs barely more than scoring
1 (still memory-bound, same weight bytes moved) — this is the same
arithmetic-intensity argument from L02/L17, now applied at the sequence
level instead of the batch level.

PRODUCTION/RESEARCH USE CASE:
Continuous batching is table-stakes in every serious production LLM
serving system (vLLM, TGI, TensorRT-LLM) — running WITHOUT it leaves
significant throughput on the table for any workload with variable
generation lengths (which is essentially all real workloads). Speculative
decoding gives an ADDITIONAL, ORTHOGONAL speedup, particularly valuable
for latency-sensitive single-user/low-batch scenarios.

COMMON MISTAKES:
- Assuming speculative decoding changes OUTPUT QUALITY — correctly
  implemented, it produces a statistically IDENTICAL distribution to
  standard autoregressive decoding from the target model alone; it's a
  pure LATENCY optimization, not an approximation, when the
  acceptance/rejection sampling rule is implemented correctly.
- Choosing a draft model that's too SLOW relative to the target — if the
  draft model itself takes a meaningful fraction of the target model's
  forward-pass time, the technique's net speedup shrinks or disappears;
  the draft model needs to be MUCH cheaper (typically a smaller model
  from the same family, or a specially-trained tiny model).
- Implementing continuous batching without properly handling the KV
  cache implications (L20) — admitting a new sequence mid-batch requires
  KV cache allocation for it (PagedAttention makes this tractable), and
  removing a finished sequence requires freeing its blocks — the
  scheduling and memory management are tightly coupled, not independent.
"""

import random
from dataclasses import dataclass, field


# ------------------------------------------------------------------
# 1. Static batching vs continuous batching — a discrete-event simulation
# ------------------------------------------------------------------
@dataclass
class Request:
    request_id: int
    arrival_step: int
    total_tokens_needed: int
    tokens_generated: int = 0

    @property
    def is_finished(self) -> bool:
        return self.tokens_generated >= self.total_tokens_needed


def simulate_static_batching(requests: list[Request], batch_size: int) -> int:
    """
    Groups requests into FIXED batches; each batch runs until its
    SLOWEST member finishes, wasting GPU slots for members that finished
    earlier. Returns total simulated steps (a proxy for total GPU time).
    """
    total_steps = 0
    pending = sorted(requests, key=lambda r: r.arrival_step)

    while pending:
        batch = pending[:batch_size]
        pending = pending[batch_size:]
        max_needed = max(r.total_tokens_needed for r in batch)
        # The ENTIRE batch occupies the GPU for max_needed steps, even
        # though shorter requests finished long before that.
        total_steps += max_needed

    return total_steps


def simulate_continuous_batching(requests: list[Request], batch_size: int) -> int:
    """
    At every step, finished sequences are EVICTED and new arrivals are
    ADMITTED to fill the freed slots — the GPU stays busy with a full
    batch (as long as enough requests are available) at every step.
    """
    total_steps = 0
    waiting = sorted(requests, key=lambda r: r.arrival_step)
    active: list[Request] = []
    step = 0

    while waiting or active:
        step += 1
        # Admit new arrivals into any free slots.
        while len(active) < batch_size and waiting and waiting[0].arrival_step <= step:
            active.append(waiting.pop(0))

        if not active:
            # No requests ready yet — advance time without doing GPU work.
            if waiting:
                step = waiting[0].arrival_step - 1
            continue

        # One decode step for every ACTIVE request (a real batched
        # forward pass processes the whole active batch in ONE kernel
        # call, but the wall-clock cost is what we're counting here).
        for r in active:
            r.tokens_generated += 1
        total_steps += 1

        active = [r for r in active if not r.is_finished]

    return total_steps


def batching_comparison_demo():
    random.seed(0)
    requests_static = [
        Request(request_id=i, arrival_step=0, total_tokens_needed=random.randint(5, 200))
        for i in range(20)
    ]
    requests_continuous = [
        Request(request_id=r.request_id, arrival_step=r.arrival_step,
                total_tokens_needed=r.total_tokens_needed)
        for r in requests_static
    ]

    static_steps = simulate_static_batching(requests_static, batch_size=4)
    continuous_steps = simulate_continuous_batching(requests_continuous, batch_size=4)

    print(f"Static batching total GPU-steps:     {static_steps}")
    print(f"Continuous batching total GPU-steps: {continuous_steps}")
    print(f"Improvement: {(1 - continuous_steps / static_steps) * 100:.1f}% fewer GPU-steps "
          f"for the same set of requests")


# ------------------------------------------------------------------
# 2. Speculative decoding — draft-then-verify
# ------------------------------------------------------------------
def simulate_speculative_decoding(
    target_model_call_cost: float,   # relative cost of ONE target model forward pass
    draft_model_call_cost: float,     # relative cost of ONE draft model forward pass
    draft_acceptance_rate: float,     # probability EACH draft token is accepted
    num_speculative_tokens: int,
    total_tokens_to_generate: int,
) -> dict:
    """
    A simplified cost model: each "round" generates K draft tokens
    (K * draft_cost), then ONE target-model verification pass scores all
    K simultaneously (target_cost — crucially NOT K * target_cost, since
    verifying K tokens in parallel costs about the same as generating 1,
    per the memory-bandwidth argument from L17). The number of ACCEPTED
    tokens per round follows a geometric-like process based on
    draft_acceptance_rate.
    """
    tokens_generated = 0
    total_cost = 0.0
    rounds = 0

    while tokens_generated < total_tokens_to_generate:
        rounds += 1
        # Draft model generates K tokens autoregressively (K separate,
        # cheap forward passes).
        total_cost += num_speculative_tokens * draft_model_call_cost

        # Target model verifies all K in ONE parallel forward pass.
        total_cost += target_model_call_cost

        # Simulate how many of the K draft tokens get accepted.
        accepted = 0
        for _ in range(num_speculative_tokens):
            if random.random() < draft_acceptance_rate:
                accepted += 1
            else:
                break  # rejection stops the accepted run at this point
        # At least 1 token is always produced (either an accepted draft
        # token, or the target model's own correction token).
        tokens_generated += max(1, accepted)

    # Baseline: standard autoregressive decoding, ONE target-model call
    # per token, no draft model involved at all.
    baseline_cost = total_tokens_to_generate * target_model_call_cost

    return {
        "speculative_cost": total_cost,
        "baseline_cost": baseline_cost,
        "speedup": baseline_cost / total_cost,
        "rounds": rounds,
        "avg_tokens_per_round": total_tokens_to_generate / rounds,
    }


def speculative_decoding_demo():
    random.seed(0)
    result = simulate_speculative_decoding(
        target_model_call_cost=1.0,
        draft_model_call_cost=0.05,      # draft model ~20x cheaper per call
        draft_acceptance_rate=0.7,        # 70% of draft tokens get accepted
        num_speculative_tokens=4,
        total_tokens_to_generate=200,
    )
    for k, v in result.items():
        print(f"  {k}: {v:.3f}" if isinstance(v, float) else f"  {k}: {v}")

    print("\nSpeedup vs draft acceptance rate (holding other params fixed):")
    for acceptance_rate in (0.3, 0.5, 0.7, 0.9):
        random.seed(0)
        r = simulate_speculative_decoding(1.0, 0.05, acceptance_rate, 4, 200)
        print(f"  acceptance_rate={acceptance_rate:.1f}  ->  speedup={r['speedup']:.2f}x")
    # Higher acceptance rate (a BETTER-matched draft model) directly
    # produces higher speedup — this is why draft-model QUALITY (not just
    # speed) matters, and why some production systems use a distilled or
    # fine-tuned draft model specifically for higher acceptance rates.


if __name__ == "__main__":
    batching_comparison_demo()
    print()
    speculative_decoding_demo()

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
A quantized SMALL model makes an excellent speculative-decoding draft
model — this is a direct, natural intersection of Phase 4's quantization
work and this lesson's serving technique: a 4-bit-quantized 1B-parameter
draft model paired with a full-precision (or separately quantized) 70B
target model can achieve both the memory savings of quantization AND the
latency improvement of speculative decoding simultaneously, and
characterizing exactly how these two orthogonal techniques COMPOUND
(rather than assuming their benefits simply add) is itself a legitimate,
currently-relevant research question.
"""
