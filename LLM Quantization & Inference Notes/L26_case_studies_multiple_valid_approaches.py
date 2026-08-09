"""
WHAT: Four realistic LLM-quantization/inference-engineering problems,
      each solved with THREE genuinely different, individually
      defensible approaches drawn from L01-L25 -- with an explicit
      comparison table and reasoning for why each answer is valid under
      different constraints.
WHY:  "GPTQ or AWQ," "continuous batching or static," "how aggressive to
      quantize" are all questions L01-L25 gave you real tools for, not
      one universal answer -- this lesson is about the decision process
      under real accuracy/throughput/memory constraints.
LEVEL: Capstone -- read after L01-L25 (this domain's own capstone, L25,
       covers a full design/roadmap; this lesson complements it with
       four additional, narrower decision-under-constraint scenarios).

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L25's concepts.
"""

# ============================================================================
# CASE STUDY 1 — CHOOSING A QUANTIZATION BIT-WIDTH FOR DEPLOYING A MODEL
# ON CONSUMER GPU HARDWARE (24GB VRAM)
# ============================================================================
#
# SETUP: deploying a model whose FP16 weights alone exceed 24GB VRAM,
# needing to fit on a single consumer GPU while preserving as much
# quality as possible.
#
# ------------------------------------------------------------------------
# APPROACH A: 8-bit quantization (INT8)
# ------------------------------------------------------------------------
#   WHY VALID: per this domain's early quantization lessons, 8-bit
#   quantization typically preserves model quality very close to FP16,
#   with a well-understood, mature accuracy/compression tradeoff -- the
#   conservative, safest choice when quality preservation is the
#   dominant concern.
#   COST: roughly halves memory versus FP16 -- if the FP16 model
#   significantly exceeds 24GB (not just slightly over), 8-bit alone
#   may still not be enough to fit, in which case this "safe" choice
#   simply doesn't solve the stated problem at all.
#
# ------------------------------------------------------------------------
# APPROACH B: 4-bit quantization (GPTQ or AWQ, per this domain's
# dedicated lessons on both)
# ------------------------------------------------------------------------
#   WHY VALID: roughly quarters memory versus FP16 -- for a model that
#   meaningfully exceeds 24GB in FP16, 4-bit quantization is often the
#   difference between "fits" and "doesn't fit" on this specific
#   hardware target, directly solving the stated constraint where A
#   might not.
#   COST: per this domain's accuracy-vs-compression discussion, 4-bit
#   quantization incurs a real, measurable (though often modest for
#   well-designed schemes like GPTQ/AWQ) quality degradation relative
#   to 8-bit or FP16 -- the specific degree of degradation is genuinely
#   model- and task-dependent, and must be validated empirically for
#   the SPECIFIC model and use case, not assumed acceptable by default.
#
# ------------------------------------------------------------------------
# APPROACH C: Mixed-precision quantization -- quantize MOST layers
# aggressively (4-bit) but keep specific, known-sensitive layers
# (e.g. certain attention components or the final output layer) at
# higher precision (8-bit or FP16), per this domain's sub-4-bit/open-
# questions discussion of non-uniform quantization strategies
# ------------------------------------------------------------------------
#   WHY VALID: directly targets B's accuracy-degradation concern --
#   quantization error isn't necessarily uniform across a model's
#   layers; some layers are empirically more sensitive to precision
#   loss than others, and selectively preserving precision specifically
#   where it matters most can recover much of B's lost quality while
#   keeping most of its memory savings.
#   COST: requires actually IDENTIFYING which layers are sensitive (via
#   empirical analysis/ablation, real additional investigative work
#   beyond just applying a uniform quantization scheme) and results in
#   a genuinely more complex deployment artifact (mixed precision across
#   layers) than B's uniform approach, with correspondingly more
#   implementation/tooling complexity to get right.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Memory reduction | Quality preservation | Implementation complexity |
#   |----------|------------------------|----------------------------|----------------------------------|
#   | A: 8-bit | Moderate (~2x) | Best | Lowest |
#   | B: 4-bit (GPTQ/AWQ) | Large (~4x) | Reduced, but often acceptable | Low (mature tooling) |
#   | C: mixed-precision | Large, slightly less than pure 4-bit | Best achievable at this memory budget | Highest |
#   Given the stated hard constraint (must fit in 24GB, FP16 doesn't),
#   B is the practical default answer for most cases; C is worth the
#   added complexity specifically when B's quality loss is measured to
#   be unacceptable for the actual use case, not applied preemptively
#   before confirming B's degradation is actually a real problem.


# ============================================================================
# CASE STUDY 2 — CHOOSING A BATCHING STRATEGY FOR A PRODUCTION INFERENCE
# SERVER
# ============================================================================
#
# SETUP: serving many concurrent user requests with varying prompt/
# generation lengths, needing to maximize GPU throughput.
#
# ------------------------------------------------------------------------
# APPROACH A: Static batching -- group a fixed number of requests
# together, process them as one batch, wait for ALL to finish (including
# the longest-generating request) before starting the next batch
# ------------------------------------------------------------------------
#   WHY VALID: simplest batching implementation -- straightforward to
#   reason about, and for a workload where request lengths are
#   genuinely UNIFORM (all requests generate roughly the same number of
#   tokens), this can be reasonably efficient with much less
#   implementation complexity than more sophisticated alternatives.
#   COST: per this domain's continuous-batching lesson, for VARYING
#   generation lengths (the realistic, common case), static batching
#   wastes significant GPU capacity -- shorter requests finish early but
#   their freed GPU capacity sits IDLE until the longest request in the
#   batch finally completes, a well-documented, substantial throughput
#   loss.
#
# ------------------------------------------------------------------------
# APPROACH B: Continuous batching (per this domain's dedicated lesson)
# -- as soon as any request in a batch finishes, immediately insert a
# new waiting request into that freed slot, without waiting for the
# whole batch to complete
# ------------------------------------------------------------------------
#   WHY VALID: directly eliminates A's idle-capacity waste -- GPU slots
#   are kept continuously busy as requests dynamically enter/exit the
#   batch, a substantial, well-documented throughput improvement over
#   static batching for realistic, varied-length workloads, the modern
#   standard for production LLM serving.
#   COST: genuinely more complex to implement correctly than static
#   batching -- requires careful management of the KV cache (per this
#   domain's paged-attention lesson) as requests dynamically enter and
#   exit, and the scheduling logic itself (deciding which waiting
#   request to insert next, and how) is real, additional engineering
#   complexity beyond A's simpler fixed-batch model.
#
# ------------------------------------------------------------------------
# APPROACH C: B, combined with speculative decoding (per this domain's
# dedicated lesson) for requests where a smaller, faster draft model can
# usefully predict likely continuations, verified by the larger model
# ------------------------------------------------------------------------
#   WHY VALID: per this domain's speculative-decoding lesson, this adds
#   a genuinely DIFFERENT throughput lever on top of B -- rather than
#   only improving GPU UTILIZATION (B's contribution), speculative
#   decoding can reduce the actual NUMBER of expensive large-model
#   forward passes needed per generated token, when the draft model's
#   predictions are frequently correct, a complementary, not
#   competing, optimization.
#   COST: requires maintaining and correctly integrating a SEPARATE
#   draft model into the serving pipeline, and speculative decoding's
#   benefit is highly dependent on the draft model's prediction
#   accuracy for the ACTUAL workload/domain -- for some workloads
#   (highly unpredictable, creative generation) the draft model's
#   predictions may be wrong often enough that the speculative
#   overhead isn't worth the benefit, a real, workload-dependent
#   tradeoff requiring empirical validation, not a guaranteed win.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | GPU utilization | Additional throughput lever beyond utilization | Implementation complexity |
#   |----------|---------------------|-------------------------------------------------------|----------------------------------|
#   | A: static batching | Poor, for varied lengths | None | Lowest |
#   | B: continuous batching | Best | None | Medium |
#   | C: B + speculative decoding | Best | Yes, if draft model is accurate for the workload | Highest |
#   B is close to a mandatory baseline for any serious production LLM
#   serving today; C is worth the added investment specifically once a
#   good draft model exists/can be trained for the actual workload and
#   its speedup is empirically confirmed to be genuinely worthwhile for
#   that specific traffic pattern.


# ============================================================================
# CASE STUDY 3 — DECIDING WHETHER TO WRITE A CUSTOM CUDA/TRITON KERNEL
# OR USE AN EXISTING LIBRARY IMPLEMENTATION
# ============================================================================
#
# SETUP: a specific operation in the inference pipeline (e.g. a fused
# dequantization+matmul step) is identified via profiling as a
# bottleneck.
#
# ------------------------------------------------------------------------
# APPROACH A: Use an existing, well-optimized library implementation
# (e.g. from a mature inference engine or a vendor-provided kernel
# library) if one exists for this exact operation
# ------------------------------------------------------------------------
#   WHY VALID: per this domain's CUDA/cuDNN-adjacent and inference-
#   engine-architecture lessons, mature library implementations are
#   typically extensively optimized and battle-tested across many real
#   workloads -- reusing one avoids both the significant engineering
#   time AND the correctness risk of writing custom low-level GPU code.
#   COST: only applies if a suitable existing implementation genuinely
#   exists for this EXACT operation/fusion pattern -- highly specific
#   or novel operations (a genuinely new fused operation not covered by
#   existing libraries) may have no ready-made option, disqualifying
#   this approach outright for those specific cases.
#
# ------------------------------------------------------------------------
# APPROACH B: Write a custom Triton kernel (per this domain's fused-
# dequant-matmul lesson)
# ------------------------------------------------------------------------
#   WHY VALID: per this domain's Triton lesson, Triton provides a
#   meaningfully more accessible, Python-embedded programming model
#   for writing custom GPU kernels than raw CUDA -- a genuinely
#   achievable path to a custom, fused kernel for THIS specific
#   bottleneck operation without needing deep raw-CUDA expertise, while
#   still achieving performance competitive with hand-written CUDA for
#   many kernel patterns.
#   COST: still requires real GPU-kernel-programming skill and careful
#   validation (both correctness AND performance) of the custom kernel
#   -- genuinely more engineering investment than A, justified
#   specifically when A's "no suitable existing implementation" gap is
#   confirmed, not assumed.
#
# ------------------------------------------------------------------------
# APPROACH C: Write a custom kernel in raw CUDA directly (per this
# domain's CUDA-fundamentals lesson) rather than Triton
# ------------------------------------------------------------------------
#   WHY VALID: per this domain's CUDA lesson, raw CUDA provides the
#   most direct, unrestricted control over GPU execution -- for a
#   genuinely unusual operation where Triton's abstraction model doesn't
#   map cleanly onto the needed computation pattern, or where squeezing
#   out the absolute maximum possible performance (beyond what Triton's
#   compiler produces) is worth the investment, raw CUDA remains the
#   ultimate-control option.
#   COST: per this domain's own framing, raw CUDA has a substantially
#   steeper learning curve and development time than Triton (B) for
#   comparable results in MOST cases -- the performance gap between a
#   well-written Triton kernel and equivalent hand-tuned CUDA is often
#   small enough that C's extra investment isn't justified unless B has
#   been tried and specifically found insufficient.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Development effort | Performance ceiling | Availability for this specific operation |
#   |----------|-------------------------|--------------------------|--------------------------------------------------|
#   | A: existing library | Lowest | Good, if a mature implementation exists | Only if one exists |
#   | B: custom Triton kernel | Medium | Very good, close to hand-tuned CUDA in most cases | Always achievable with effort |
#   | C: custom raw CUDA | Highest | Best, theoretical maximum | Always achievable with effort |
#   Check A first, always; B is the strong default for genuinely custom
#   kernel needs given its much lower development cost than C for
#   comparable results; C is justified only once B is confirmed
#   insufficient for the specific performance target, not chosen by
#   default for "maximum control."


# ============================================================================
# CASE STUDY 4 — DECIDING HOW TO VALIDATE A QUANTIZED MODEL BEFORE
# PRODUCTION DEPLOYMENT
# ============================================================================
#
# SETUP: a model has been quantized (per Case Study 1's decision); the
# team needs to decide how rigorously to validate it before deploying
# to replace the FP16 version in production.
#
# ------------------------------------------------------------------------
# APPROACH A: Compare perplexity on a standard held-out text corpus,
# quantized vs. FP16
# ------------------------------------------------------------------------
#   WHY VALID: per LLM Core Theory Notes L04's perplexity discussion,
#   this is a fast, cheap, well-understood sanity check -- a
#   substantially higher perplexity for the quantized model is a clear,
#   early red flag that something is meaningfully wrong with the
#   quantization.
#   COST: per LLM Core Theory Notes L07's perplexity-vs-task-accuracy
#   discussion (directly applicable here), perplexity is a PROXY metric
#   -- a quantized model can have only slightly higher perplexity while
#   still showing a real, meaningful degradation on the SPECIFIC
#   downstream tasks the model is actually used for in production,
#   which perplexity alone doesn't directly measure.
#
# ------------------------------------------------------------------------
# APPROACH B: Run the quantized model against the SAME task-specific
# evaluation benchmarks used to validate the original FP16 model (e.g.
# the specific accuracy/quality metrics the product actually cares about)
# ------------------------------------------------------------------------
#   WHY VALID: directly addresses A's proxy-metric gap -- measures the
#   thing that actually matters for the product, not an intermediate
#   signal, giving a much more directly actionable "is this quantized
#   model good enough to ship" answer.
#   COST: requires having well-established, reliable task-specific
#   benchmarks already in place (real, if usually already-existing,
#   infrastructure) and evaluating on these benchmarks is typically
#   slower/more expensive than a quick perplexity check -- not a
#   replacement for A's speed as an early, cheap first signal, but a
#   genuinely more rigorous second step.
#
# ------------------------------------------------------------------------
# APPROACH C: B, plus a SHADOW DEPLOYMENT (MLOps Notes L12's pattern,
# directly applicable here) -- run the quantized model in parallel with
# the live FP16 model on real production traffic, comparing outputs,
# before actually cutting over
# ------------------------------------------------------------------------
#   WHY VALID: per MLOps Notes L12, this catches issues that neither A
#   nor B's OFFLINE benchmark-based validation can -- real production
#   traffic often has a genuinely different distribution than curated
#   benchmark datasets (out-of-distribution inputs, edge cases,
#   adversarial or unusual real user queries), and shadow deployment
#   directly observes how the quantized model behaves on the ACTUAL
#   traffic it will eventually serve, with zero risk to real users
#   since its output isn't yet being used for real decisions.
#   COST: per MLOps Notes L12, requires real infrastructure to run both
#   models in parallel (meaning, temporarily, the compute cost of
#   BOTH the FP16 and quantized model simultaneously -- partially
#   undercutting the quantized model's resource-savings benefit during
#   this validation window) and a genuine comparison/analysis process
#   to interpret the shadow results meaningfully, not just collect them.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Speed/cost of validation | Confidence in production-readiness | Catches real-traffic distribution issues |
#   |----------|--------------------------------|-------------------------------------------|--------------------------------------------------|
#   | A: perplexity comparison | Fastest, cheapest | Weak (proxy metric only) | No |
#   | B: task-specific benchmark evaluation | Medium | Good | No (still offline, curated data) |
#   | C: B + shadow deployment on real traffic | Slowest, most resource-intensive | Best | Yes |
#   Use A as a fast, cheap early sanity check that can quickly reject an
#   obviously broken quantization attempt; B as the main go/no-go gate
#   before considering deployment; C specifically before a genuinely
#   HIGH-STAKES production cutover, where the extra cost/time is
#   justified by the confidence gained from observing real traffic
#   behavior before committing.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
