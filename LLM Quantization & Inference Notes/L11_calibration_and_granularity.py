# ============================================================
# L11: Calibration and Quantization Granularity
# ============================================================
# WHAT: How to choose quantization ranges using a small CALIBRATION
#       dataset (rather than guessing), and the granularity spectrum —
#       per-tensor, per-channel, per-group/block quantization — with
#       the actual memory/accuracy tradeoff math for each.
# WHY: This is the last fundamentals lesson before Phase 4's real papers.
#      GPTQ, AWQ, and GGUF all make a specific, deliberate GRANULARITY
#      choice (typically per-group, e.g. groups of 128 weights sharing one
#      scale) — you need this vocabulary and the tradeoff reasoning to
#      understand why they made that choice instead of per-tensor or
#      per-channel.
# LEVEL: Core (Phase 3 of 8 — final fundamentals lesson)
# ============================================================

"""
CONCEPT OVERVIEW:
Calibration answers: "what range of values will this tensor ACTUALLY take
during real use?" For WEIGHTS, this is trivial — the weight values are
fixed and known exactly. For ACTIVATIONS, the range depends on the INPUT
DATA, so you run a small representative dataset (the "calibration set,"
often just a few hundred sequences) through the model and RECORD the
actual min/max (or a percentile, to reduce outlier sensitivity) of each
activation tensor — this becomes the basis for the activation's scale
factor.

Granularity is the "how many values share one scale factor" question:
  - PER-TENSOR: one scale for the entire weight matrix. Cheapest (one
    float stored total), least accurate (forced to compromise across
    every row/column's different range).
  - PER-CHANNEL (per-row or per-column): one scale per output channel.
    A single weight matrix might have thousands of channels, each with
    a meaningfully different value range — per-channel captures this at
    the cost of storing one scale per channel (negligible memory
    overhead relative to the weights themselves).
  - PER-GROUP (a.k.a. per-block): splits EACH channel/row into small
    fixed-size groups (commonly 32, 64, or 128 consecutive weights),
    each with its OWN scale. This is FINER than per-channel — it can
    adapt to variation WITHIN a single output channel — at a real, if
    small, memory cost (many more scale factors stored).

The finer the granularity, the better the accuracy (more scales = more
freedom to fit local value ranges) but the WORSE the memory/compute
overhead (more scale factors to store and apply). This is a real,
quantifiable Pareto tradeoff, not a vague "it depends."

PRODUCTION/RESEARCH USE CASE:
GGUF's "K-quant" formats and GPTQ both default to group sizes around 128
— not an arbitrary number, but a deliberately-tuned point on this exact
Pareto curve, chosen empirically to recover most of per-channel's
accuracy while keeping the scale-factor storage overhead small relative
to the (already tiny) 3-4 bit weights.

COMMON MISTAKES:
- Calibrating on a dataset that doesn't represent REAL deployment
  distribution — e.g. calibrating a code-generation model's activation
  ranges using only natural-language text produces systematically wrong
  scale factors for code-heavy deployment traffic.
- Using min/max for calibration when a small percentage of extreme
  outliers dominates the range — a 99.9th-percentile-based calibration
  is often more robust than raw min/max, directly analogous to the
  clipping-vs-rounding tradeoff from L09.
- Choosing group size ARBITRARILY rather than empirically — smaller
  groups aren't always better once you account for the scale-factor
  storage overhead; there's a real crossover point worth measuring on
  your actual model and bit-width, not assuming smaller is always better.
"""

import torch


# ------------------------------------------------------------------
# 1. Activation calibration via a small representative dataset
# ------------------------------------------------------------------
class ActivationCalibrator:
    """
    Hooks into a model's forward pass, recording the observed range of
    an activation tensor across many calibration batches — this is
    exactly the mechanism real PTQ toolkits (e.g. Hugging Face's
    `optimum`, Intel Neural Compressor) use under the hood.
    """

    def __init__(self, percentile: float = 99.9):
        self.percentile = percentile
        self.observed_values: list[torch.Tensor] = []

    def observe(self, activation: torch.Tensor):
        # In a real hook, you'd store a running histogram instead of
        # every raw tensor (memory-prohibitive at scale) — this
        # simplified version keeps everything for clarity.
        self.observed_values.append(activation.detach().flatten())

    def compute_scale(self, num_bits: int = 8) -> float:
        all_values = torch.cat(self.observed_values)
        # Percentile-based range instead of raw min/max — robust to a
        # handful of extreme calibration-batch outliers that might not
        # represent the TYPICAL deployment distribution.
        k = int(len(all_values) * self.percentile / 100)
        abs_sorted = all_values.abs().sort().values
        clip_value = abs_sorted[min(k, len(abs_sorted) - 1)].item()

        qmax = 2 ** (num_bits - 1) - 1
        return clip_value / qmax


def calibration_demo():
    torch.manual_seed(0)
    calibrator = ActivationCalibrator(percentile=99.9)

    # Simulate running several calibration batches through a layer,
    # with occasional extreme activation spikes (realistic for LLM
    # activations, which have well-documented outlier channels).
    for _ in range(20):
        batch = torch.randn(32, 512) * 0.5
        if torch.rand(1).item() < 0.1:
            batch[0, 0] = 15.0  # rare extreme outlier activation
        calibrator.observe(batch)

    scale_p999 = calibrator.compute_scale(num_bits=8)

    calibrator_minmax = ActivationCalibrator(percentile=100.0)
    calibrator_minmax.observed_values = calibrator.observed_values
    scale_minmax = calibrator_minmax.compute_scale(num_bits=8)

    print(f"scale (99.9th percentile): {scale_p999:.6f}")
    print(f"scale (raw min/max):       {scale_minmax:.6f}")
    # The min/max scale is dragged much wider by the rare 15.0 spike —
    # every "normal" activation now gets coarser quantization because of
    # a handful of outlier calibration samples.


# ------------------------------------------------------------------
# 2. Granularity comparison — per-tensor, per-channel, per-group
# ------------------------------------------------------------------
def quantize_per_tensor(W: torch.Tensor, num_bits: int) -> tuple[torch.Tensor, torch.Tensor]:
    qmax = 2 ** (num_bits - 1) - 1
    scale = W.abs().max() / qmax
    W_int = (W / scale).round().clamp(-qmax, qmax)
    return W_int, scale.unsqueeze(0)  # a single scalar scale


def quantize_per_channel(W: torch.Tensor, num_bits: int) -> tuple[torch.Tensor, torch.Tensor]:
    qmax = 2 ** (num_bits - 1) - 1
    scale = W.abs().amax(dim=1, keepdim=True) / qmax   # one scale per row
    scale = scale.clamp(min=1e-8)
    W_int = (W / scale).round().clamp(-qmax, qmax)
    return W_int, scale


def quantize_per_group(W: torch.Tensor, num_bits: int, group_size: int) -> tuple[torch.Tensor, torch.Tensor]:
    """
    Reshapes each row into groups of `group_size` consecutive weights,
    each group getting its OWN scale — the finest-grained (and most
    storage-costly) granularity of the three shown here.
    """
    out_features, in_features = W.shape
    assert in_features % group_size == 0, "in_features must divide evenly into group_size"
    num_groups = in_features // group_size

    W_grouped = W.view(out_features, num_groups, group_size)
    qmax = 2 ** (num_bits - 1) - 1
    scale = W_grouped.abs().amax(dim=2, keepdim=True) / qmax
    scale = scale.clamp(min=1e-8)
    W_int = (W_grouped / scale).round().clamp(-qmax, qmax)
    return W_int.view(out_features, in_features), scale.view(out_features, num_groups)


def compare_granularities():
    torch.manual_seed(0)
    # A weight matrix with DELIBERATE per-row and per-group variance —
    # each row has a different overall scale, AND within each row, the
    # first half and second half have different scales too.
    W = torch.zeros(4, 256)
    for row in range(4):
        row_scale = 0.1 * (row + 1)
        W[row, :128] = torch.randn(128) * row_scale
        W[row, 128:] = torch.randn(128) * row_scale * 5   # 5x larger in second half

    num_bits = 4  # aggressive bit-width to make the differences visible

    for name, (W_int, scale) in [
        ("per-tensor", quantize_per_tensor(W, num_bits)),
        ("per-channel", quantize_per_channel(W, num_bits)),
        ("per-group (128)", quantize_per_group(W, num_bits, group_size=128)),
    ]:
        if name == "per-group (128)":
            out_features, num_groups = scale.shape
            scale_expanded = scale.repeat_interleave(W.shape[1] // num_groups, dim=1)
            W_dequant = W_int * scale_expanded
        else:
            W_dequant = W_int * scale
        mse = ((W - W_dequant) ** 2).mean().item()
        scale_params = scale.numel()
        print(f"{name:18s}  MSE={mse:.6f}   scale factors stored={scale_params}")
    # Expect: per-tensor has the WORST MSE (one scale can't fit both the
    # per-row AND per-half variance); per-group has the BEST MSE, at the
    # cost of storing far more scale factors than per-channel.


if __name__ == "__main__":
    calibration_demo()
    print()
    compare_granularities()

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
When you implement GPTQ in Phase 4, its default configuration quantizes
weights with `group_size=128` — exactly the granularity demonstrated in
`compare_granularities()`. The paper's authors empirically found this
group size recovers nearly all of per-channel's... no, actually BEATS
per-channel's accuracy (because within-channel variance is real in
trained LLM weights, as this lesson's synthetic example is built to
illustrate) while keeping the scale-factor storage overhead to roughly
0.1-0.4 additional bits per weight — small enough that a 4-bit
quantization scheme with group_size=128 is still meaningfully described
as "4-bit," not "4.4-bit."
"""
