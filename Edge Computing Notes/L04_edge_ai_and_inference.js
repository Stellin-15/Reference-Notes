// ============================================================
// L04: Edge AI and Inference
// ============================================================
// WHAT: Running ML model inference at the edge (close to the user) instead
//       of a centralized inference server, under tight size/latency budgets.
// WHY:  A round trip to a centralized GPU inference server can cost
//       50-200ms. For latency-sensitive use cases (real-time content
//       moderation, personalization, bot detection) that's often too slow —
//       edge inference targets single-digit-millisecond budgets.
// LEVEL: Advanced
// ============================================================

/*
CONCEPT OVERVIEW:
Edge inference operates under constraints centralized inference doesn't:
no GPU (CPU/WASM SIMD only), tight model size limits (a few MB, not
gigabytes — edge platforms bill/limit by bundle size), and a hard latency
budget (edge compute pricing models assume millisecond-scale execution,
not seconds).

This forces model OPTIMIZATION before deployment: quantization (storing
weights as INT8 instead of FP32 — 4x smaller, faster integer math),
pruning (removing near-zero-weight connections), and knowledge distillation
(training a small "student" model to mimic a large "teacher" model's
outputs).

PRODUCTION USE CASE:
Cloudflare Workers AI hosts pre-optimized, quantized models (text
classification, embeddings, small LLMs) that run on Cloudflare's own edge
GPU fleet, invoked from a Worker with a simple binding — no model file
shipped in your Worker bundle. For custom models under the Worker's own
size budget, teams convert a trained PyTorch model to ONNX, quantize it to
INT8, and run it via ONNX Runtime Web (WASM backend) directly in the
Worker's isolate.

COMMON MISTAKES:
  - Deploying an un-quantized FP32 model to the edge — it blows the
    Worker's bundle size limit (typically 1-10MB) before you even
    consider whether it's fast enough.
  - Doing every inference at the edge when embedding-generation-only can
    be edge-side with the expensive similarity SEARCH done centrally
    against a proper vector index — trying to run a full vector DB inside
    an edge isolate doesn't scale past a tiny embedded dataset.
  - Ignoring cold-start cost of loading model weights into a fresh
    isolate — if the isolate is evicted between requests, "fast inference"
    can be dominated by weight-loading time, not the forward pass itself.
*/

// ------------------------------------------------------------------
// 1. Model optimization for edge constraints
// ------------------------------------------------------------------
const OPTIMIZATION_TECHNIQUES = {
  quantization: "FP32 -> INT8 (or FP16). ~4x smaller model, faster integer "
    + "ops on CPU, usually < 1-2% accuracy loss for classification tasks. "
    + "The default first lever to pull for edge deployment.",
  pruning: "Remove weights near zero (below a magnitude threshold) and "
    + "the connections associated with them, shrinking the model — most "
    + "effective combined with a fine-tuning pass after pruning to recover "
    + "accuracy lost from the removed connections.",
  distillation: "Train a small 'student' network to match a large "
    + "'teacher' model's output distribution (not just the hard labels) — "
    + "produces a genuinely smaller architecture, not just a compressed "
    + "version of the same one.",
};

// ------------------------------------------------------------------
// 2. Cloudflare Workers AI — hosted edge inference
// ------------------------------------------------------------------
const WORKERS_AI_EXAMPLE = `
// wrangler.toml
// [ai]
// binding = "AI"

export default {
  async fetch(request, env) {
    const { text } = await request.json();

    // No model file ships in YOUR Worker bundle — Cloudflare hosts the
    // model on its own edge GPU fleet; this call is a fast RPC to the
    // nearest inference node, not a cold model load in your isolate.
    const embedding = await env.AI.run("@cf/baai/bge-base-en-v1.5", {
      text: [text],
    });

    const classification = await env.AI.run(
      "@cf/huggingface/distilbert-sst-2-int8",  // pre-quantized, edge-sized
      { text }
    );

    return Response.json({ embedding, classification });
  },
};
`;

// ------------------------------------------------------------------
// 3. Custom ONNX model in-isolate via WASM
// ------------------------------------------------------------------
const ONNX_RUNTIME_WEB_EXAMPLE = `
// A small custom classifier (e.g. bot-detection scoring), converted from
// PyTorch to ONNX and quantized to fit the Worker's bundle size budget.

// python: torch -> onnx export + quantization (build-time, not runtime)
//   torch.onnx.export(model, dummy_input, "model.onnx")
//   from onnxruntime.quantization import quantize_dynamic
//   quantize_dynamic("model.onnx", "model_int8.onnx")

import * as ort from "onnxruntime-web/wasm";
import modelBytes from "./model_int8.onnx";  // bundled as a binary asset

let session; // module-level — reused across requests IF the isolate survives
async function getSession() {
  if (!session) {
    session = await ort.InferenceSession.create(modelBytes, {
      executionProviders: ["wasm"],  // no GPU in an edge isolate
    });
  }
  return session;
}

export default {
  async fetch(request) {
    const session = await getSession();
    const features = new Float32Array([/* extracted request features */]);
    const feeds = { input: new ort.Tensor("float32", features, [1, features.length]) };
    const results = await session.run(feeds);
    const score = results.output.data[0];
    return Response.json({ bot_score: score });
  },
};
`;

// ------------------------------------------------------------------
// 4. On-device AI (mobile edge) — a related but distinct model
// ------------------------------------------------------------------
const ON_DEVICE_AI = {
  CoreML: "Apple's on-device inference framework (iOS/macOS) — models "
    + "converted via coremltools, runs on the Neural Engine/GPU/CPU with "
    + "automatic hardware selection.",
  TFLite: "TensorFlow Lite — Android's dominant on-device inference "
    + "runtime, with its own quantization/conversion pipeline (TFLite "
    + "Converter) analogous to ONNX's.",
};

// ------------------------------------------------------------------
// 5. Edge embedding + centralized vector search (hybrid pattern)
// ------------------------------------------------------------------
const HYBRID_SEARCH_PATTERN = `
// The realistic production split: EMBEDDING GENERATION happens at the
// edge (fast, small model, low-latency, close to the user's raw text),
// but the actual ANN (approximate nearest neighbor) SEARCH against
// millions of vectors happens in a centralized vector DB (Pinecone,
// pgvector) — running HNSW/IVF search over a large index inside an edge
// isolate does not scale, but calling out to a fast vector DB with an
// already-computed embedding is a single, cheap round trip.

export default {
  async fetch(request, env) {
    const { query } = await request.json();
    const { data } = await env.AI.run("@cf/baai/bge-base-en-v1.5", { text: [query] });
    const embedding = data[0];

    // one HTTP call to a centralized vector DB, not a local index scan
    const results = await fetch("https://vectordb.internal/search", {
      method: "POST",
      body: JSON.stringify({ vector: embedding, top_k: 10 }),
    });
    return results;
  },
};
`;

// ------------------------------------------------------------------
// 6. Federated learning and privacy-preserving inference (concept)
// ------------------------------------------------------------------
const PRIVACY_PRESERVING_NOTES = `
Federated learning trains a shared model across many edge devices WITHOUT
centralizing raw user data — each device computes a local gradient update
on its own data, only the (much smaller, less sensitive) gradient is sent
back to be aggregated into the global model. This is a training-time
pattern, distinct from edge INFERENCE (which is what most of this lesson
covers) — but both share the motivation of keeping raw sensitive data from
ever leaving the edge/device.
`;

module.exports = {
  OPTIMIZATION_TECHNIQUES,
  WORKERS_AI_EXAMPLE,
  ONNX_RUNTIME_WEB_EXAMPLE,
  ON_DEVICE_AI,
  HYBRID_SEARCH_PATTERN,
  PRIVACY_PRESERVING_NOTES,
};

/*
TRADING/PRODUCTION CONTEXT EXAMPLE:
A trading platform's fraud-detection layer runs a quantized INT8
classifier at the edge to score account-takeover risk on every login
request, before it ever reaches the origin auth service — adding ~3ms
instead of the ~80ms a centralized model-serving call would cost. Only
requests scoring above a risk threshold get routed to a heavier,
centralized model for a second-pass, higher-confidence check — the edge
model's job is fast triage, not final judgment.
*/
