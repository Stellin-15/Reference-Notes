# ============================================================
# L10: Real-Time Inference Serving vs Batch Scoring
# ============================================================
# WHAT: The architectural differences between serving ML/AI inference in
#       an event-driven, real-time context (a single prediction, bounded
#       latency budget, triggered by an event) versus batch scoring
#       (score a large dataset all at once, on a schedule) — and how to
#       design a latency budget for the real-time case.
# WHY: L01-L09 built the event-driven infrastructure (bus, durable
#      execution, trigger evaluation, LLM routing). This lesson covers
#      the specific concerns of putting ACTUAL MODEL INFERENCE (not just
#      business-rule evaluation) into that real-time path — inference
#      has its own latency/throughput characteristics distinct from a
#      simple trigger condition check.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
BATCH SCORING processes a LARGE dataset all at once, typically on a
schedule (this repo's Data Engineering/MLOps Notes cover this
extensively) — throughput-optimized, can leverage large-batch inference
efficiency (a GPU processing 1,000 examples at once is far more
efficient per-example than processing them one at a time), but
introduces latency BY DESIGN: a prediction computed in this morning's
batch run reflects data as of whenever the batch started, not the
current instant.

REAL-TIME/EVENT-DRIVEN INFERENCE serves ONE prediction request at a
time (or very small batches, opportunistically), triggered by an EVENT
(L01-L05) rather than a schedule — necessarily LATENCY-optimized rather
than throughput-optimized, since the whole point is responding to
something that just happened, quickly. This trades some of batch's raw
throughput efficiency for the ability to react to individual events
within a bounded, often sub-second-to-low-seconds latency budget.

A LATENCY BUDGET is the explicit allocation of an end-to-end time
constraint across every stage a real-time inference request passes
through: event bus delivery (L02, typically tens of milliseconds),
feature retrieval (Feature Stores & Modern Data Lake Notes L08's online
store, typically single-digit milliseconds), the model's OWN forward-
pass time (varies hugely by model size/complexity — this repo's LLM
Quantization & Inference Notes covers exactly this dimension for large
models), and response delivery back to whatever triggered the request.
Designing a real-time system means explicitly allocating a "budget" to
each stage and ensuring the SUM stays within the overall requirement —
if the end-to-end target is "under 5 seconds" and the model's own
forward pass alone takes 4 seconds, there's very little budget left for
everything else, and that's a genuine constraint on which MODEL can be
used at all in this real-time path (directly connecting back to model
size/quantization tradeoffs).

A common HYBRID pattern combines both: a FAST, LIGHTWEIGHT model handles
the real-time path (bounded by the tight latency budget), while a
SEPARATE, more expensive/accurate model runs on a BATCH schedule to
periodically refresh a cached prediction or flag cases needing deeper
review — the real-time path never waits on the expensive model directly.

PRODUCTION USE CASE:
A real-time fraud-check on a payment event must complete within a tight
latency budget (the payment can't be authorized until the check
completes) — the real-time path uses a SMALL, fast model making an
initial pass/fail/review decision within its latency budget, while a
SEPARATE, more thorough (and slower) model re-scores the SAME
transaction asynchronously afterward, flagging anything the fast model's
initial "pass" decision should be revisited on — the real-time path
never blocks the actual payment authorization on the slower, more
thorough model's result.

COMMON MISTAKES:
- Putting a large, slow model directly into a real-time, latency-bounded
  path without checking whether its own forward-pass time alone already
  consumes most or all of the available latency budget — this is a
  frequent, avoidable cause of a "real-time" feature that's actually too
  slow to meet its own stated latency requirement.
- Not accounting for FEATURE RETRIEVAL latency (Feature Stores & Modern
  Data Lake Notes L08) as part of the real-time latency budget — a fast
  model paired with a slow online-store lookup still produces a slow
  end-to-end response; the whole PATH's latency matters, not just the
  model's own inference time.
- Trying to force a single model to serve BOTH the real-time path AND
  batch scoring identically, when the two paths have genuinely different
  latency/throughput requirements that often justify DIFFERENT model
  choices (a lighter real-time model, a heavier batch model) rather than
  one model awkwardly serving both.
"""

from dataclasses import dataclass


# ------------------------------------------------------------------
# 1. Designing an explicit latency budget
# ------------------------------------------------------------------
@dataclass
class LatencyBudget:
    total_budget_ms: int
    event_delivery_ms: int
    feature_retrieval_ms: int
    model_inference_ms: int
    response_delivery_ms: int

    @property
    def total_allocated_ms(self) -> int:
        return (self.event_delivery_ms + self.feature_retrieval_ms
                + self.model_inference_ms + self.response_delivery_ms)

    @property
    def within_budget(self) -> bool:
        return self.total_allocated_ms <= self.total_budget_ms

    @property
    def remaining_margin_ms(self) -> int:
        return self.total_budget_ms - self.total_allocated_ms


def design_latency_budget_demo():
    # A realistic budget for "under 2 seconds end to end"
    budget = LatencyBudget(
        total_budget_ms=2000,
        event_delivery_ms=50,          # NATS/JetStream delivery, L02
        feature_retrieval_ms=15,        # Redis hot-tier lookup, Feature Stores Notes L08
        model_inference_ms=1200,        # the model's own forward pass
        response_delivery_ms=30,        # WebSocket/response delivery, L06
    )
    print(f"Total allocated: {budget.total_allocated_ms}ms / budget: {budget.total_budget_ms}ms")
    print(f"Within budget: {budget.within_budget}, margin: {budget.remaining_margin_ms}ms")

    # Now try a LARGER model that blows the budget
    oversized_budget = LatencyBudget(
        total_budget_ms=2000,
        event_delivery_ms=50, feature_retrieval_ms=15,
        model_inference_ms=2800,   # a much larger/slower model
        response_delivery_ms=30,
    )
    print(f"\nWith a larger model: total={oversized_budget.total_allocated_ms}ms, "
          f"within_budget={oversized_budget.within_budget}")
    print("  -> This model CANNOT be used in this real-time path as-is; "
          "options: a smaller/quantized model (LLM Quantization & "
          "Inference Notes), a faster serving stack (vLLM), or moving "
          "this specific check to an ASYNC path instead of the "
          "synchronous real-time budget.")


# ------------------------------------------------------------------
# 2. The hybrid pattern — fast real-time path + slower async re-check
# ------------------------------------------------------------------
@dataclass
class FraudCheckResult:
    decision: str   # "pass" | "fail" | "review"
    confidence: float


def fast_realtime_fraud_check(transaction: dict) -> FraudCheckResult:
    """A small, fast model — MUST complete within the payment
    authorization's tight latency budget."""
    risk_score = transaction.get("amount", 0) / 10000   # a toy heuristic stand-in
    if risk_score > 0.8:
        return FraudCheckResult("review", confidence=0.6)
    return FraudCheckResult("pass", confidence=0.9)


def slow_async_fraud_recheck(transaction: dict) -> FraudCheckResult:
    """A larger, more thorough model — runs ASYNCHRONOUSLY, never
    blocking the real-time payment authorization path."""
    # A real implementation might take seconds, using far more
    # sophisticated features/model architecture than the fast path allows.
    return FraudCheckResult("pass", confidence=0.97)


def process_payment_with_hybrid_fraud_check(transaction: dict) -> dict:
    fast_result = fast_realtime_fraud_check(transaction)

    if fast_result.decision == "pass":
        # Authorize the payment IMMEDIATELY — the real-time path never
        # waited on the slower model.
        authorize_payment(transaction)
        # Queue the async recheck for AFTER authorization, flagging for
        # follow-up review if it later disagrees.
        queue_async_recheck(transaction)
        return {"status": "authorized", "fast_check": fast_result.decision}

    return {"status": "held_for_review", "fast_check": fast_result.decision}


def authorize_payment(transaction: dict):
    print(f"  Payment authorized immediately (fast path): {transaction['id']}")


def queue_async_recheck(transaction: dict):
    print(f"  Queued async re-check (slow path, non-blocking): {transaction['id']}")


if __name__ == "__main__":
    design_latency_budget_demo()

    print("\n--- Hybrid real-time + async pattern ---")
    process_payment_with_hybrid_fraud_check({"id": "txn_1", "amount": 200})
    process_payment_with_hybrid_fraud_check({"id": "txn_2", "amount": 9500})

"""
PRODUCTION CONTEXT EXAMPLE:
A payments platform's fraud check uses a small, fast model in the
synchronous real-time path (bounded to a strict sub-500ms budget, since
the customer is actively waiting for payment confirmation), while a
much larger, more accurate model re-scores every transaction
asynchronously within a few minutes afterward — transactions the slow
model later flags as suspicious (despite the fast model's initial
"pass") are routed to a manual review queue rather than being silently
missed, giving the platform both fast customer-facing authorization AND
more thorough fraud detection, without forcing either concern to
compromise the other.
"""
