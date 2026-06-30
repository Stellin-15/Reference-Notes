# ============================================================
# L05: Model Serving Architectures
# ============================================================
# WHAT: Model serving is the process of exposing a trained model as a
#       service that accepts requests and returns predictions in production.
#       Architectures range from a simple FastAPI wrapper to purpose-built
#       inference servers (TorchServe, Triton) handling thousands of
#       requests per second across GPU fleets.
# WHY:  Training is a one-time batch job. Serving is an always-on system
#       that must be fast, reliable, and maintainable. A great model with
#       poor serving is worthless in production — latency kills UX, and
#       downtime costs revenue.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    Model serving has two fundamental concerns: latency and throughput.
    Latency is how fast a single request is answered (P99 matters more
    than mean). Throughput is how many requests per second the system can
    handle. These trade off against each other — batching improves
    throughput but increases latency. The serving architecture you choose
    must be tuned to your SLA and traffic pattern.

PRODUCTION USE CASE:
    An e-commerce recommendation system serves 5,000 predictions/second
    with P99 < 80ms. Architecture: NGINX → FastAPI gateway (validates
    request, fetches user features from Redis) → gRPC call to Triton
    inference server running ONNX model on A10G GPU with dynamic batching
    (batch up to 64, max delay 5ms). Prometheus scrapes Triton metrics;
    Grafana alerts fire if P99 exceeds 100ms.

COMMON MISTAKES:
    1. Loading the model INSIDE the request handler — does this once per
       request, not once at startup. A 2-second model load on every call
       equals a 2-second minimum latency.
    2. No health/readiness separation — K8s treats a starting pod as ready
       and sends traffic before the model is loaded.
    3. No batching on GPU — serving one sample at a time wastes 90%+ of
       GPU compute. Dynamic batching gives 10-50x throughput improvement.
    4. Ignoring the feature retrieval budget — if your model inference is
       20ms but feature lookup is 150ms, the model speed is irrelevant.
    5. Single model version in production — makes A/B testing and rollback
       impossible. Always support routing to multiple versions.
"""

import asyncio
import time
import threading
import queue
import logging
from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np

logger = logging.getLogger(__name__)

# ============================================================
# SECTION 1: SERVING REQUIREMENTS (WHAT YOU MUST HIT IN PROD)
# ============================================================
#
# LATENCY    — P99 < 100ms for most consumer-facing models.
#              P50 < 30ms for real-time features (ad ranking, fraud).
#              "Mean latency" is not enough — tail latency kills UX.
#
# THROUGHPUT — 1,000+ requests/second for large-scale applications.
#              Must be tested with realistic traffic patterns (burst).
#
# AVAILABILITY — 99.9% uptime = 8.7 hours downtime/year.
#                99.99% = 52 minutes/year. Rolling deploys, blue/green,
#                health probes all contribute to this.
#
# MODEL VERSIONING — Must be able to run v1 and v2 simultaneously.
#                    Needed for A/B testing, shadow mode, rollback.
#
# MONITORING — Every request logged: latency, input features (sample),
#              prediction value, model version. Out-of-range inputs alerted.
#
# GRACEFUL DEGRADATION — If model fails (OOM, timeout), return a cached
#                        or default prediction rather than an error.

# ============================================================
# SECTION 2: FASTAPI MODEL SERVER — CORRECT PATTERN
# ============================================================
# FastAPI is the standard choice for Python model serving when you don't
# need the scale of TorchServe/Triton. Key: load the model ONCE at startup,
# share it across all requests via app state or a module-level variable.

# WRONG pattern (model reloaded on every request — never do this):
# @app.post("/predict")
# def predict(request: PredictRequest):
#     model = joblib.load("model.pkl")   # <-- 1-5 seconds, every request!
#     return model.predict(request.features)

# CORRECT pattern (model loaded once at startup):
#
# from contextlib import asynccontextmanager
# from fastapi import FastAPI
# import joblib, numpy as np
#
# model_store = {}   # module-level dict holds model reference
#
# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # STARTUP: runs once when the server starts
#     # This is where slow initialization happens: load model, warm up, etc.
#     model_store["model"] = joblib.load("model.pkl")
#     model_store["ready"] = True
#     logger.info("Model loaded and ready")
#     yield
#     # SHUTDOWN: cleanup (close connections, flush buffers)
#     model_store.clear()
#
# app = FastAPI(lifespan=lifespan)
#
# @app.get("/health")
# def health():
#     """Liveness probe — is the server process alive?"""
#     return {"status": "ok"}
#
# @app.get("/ready")
# def ready():
#     """Readiness probe — is the model loaded and ready to serve?
#     K8s will not route traffic until this returns 200."""
#     if not model_store.get("ready"):
#         raise HTTPException(status_code=503, detail="Model not loaded")
#     return {"status": "ready"}
#
# @app.post("/predict")
# def predict(request: PredictRequest):
#     model = model_store["model"]   # already loaded — microseconds, not seconds
#     features = np.array(request.features).reshape(1, -1)
#     prediction = model.predict_proba(features)[0, 1]
#     return {"score": float(prediction)}

# ============================================================
# SECTION 3: DYNAMIC BATCHING IN FASTAPI
# ============================================================
# On GPU, batching 32 inputs is nearly the same compute cost as batching 1.
# Dynamic batching: accumulate requests for up to MAX_DELAY_MS milliseconds
# OR until MAX_BATCH_SIZE requests arrive, whichever comes first.
# Then process the batch together and return results to each caller.
# Result: 10-50x throughput improvement on GPU, small latency increase.

MAX_BATCH_SIZE = 32
MAX_DELAY_MS = 20  # max time to wait before processing a partial batch


@dataclass
class BatchRequest:
    """One item waiting in the batch queue."""
    features: np.ndarray
    future: asyncio.Future  # result will be set on this future when batch runs


class DynamicBatcher:
    """
    Collects incoming predict() calls into batches, runs inference once
    per batch, and returns results to each individual caller.

    Architecture:
        Client A → put (features_A, future_A) in queue ──┐
        Client B → put (features_B, future_B) in queue ──┤→ background worker
        Client C → put (features_C, future_C) in queue ──┘   runs batch inference
                                                              sets future_A, B, C
    Each client awaits its future → gets result when batch completes.
    """

    def __init__(self, model, max_batch_size: int = MAX_BATCH_SIZE,
                 max_delay_ms: float = MAX_DELAY_MS):
        self.model = model
        self.max_batch_size = max_batch_size
        self.max_delay_s = max_delay_ms / 1000.0
        self._queue: queue.Queue = queue.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._worker_thread = threading.Thread(
            target=self._batch_worker, daemon=True
        )
        self._worker_thread.start()

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """Called at server startup so the worker thread can set futures."""
        self._loop = loop

    async def predict(self, features: np.ndarray) -> float:
        """
        Submit one request. Returns when the batch containing this request
        has been processed. Caller awaits this — no busy-waiting.
        """
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._queue.put(BatchRequest(features=features, future=future))
        return await future  # suspends until batch worker sets result

    def _batch_worker(self):
        """
        Runs in a background thread. Collects requests, runs inference,
        resolves futures. Separate thread because model.predict() may
        release the GIL (NumPy, ONNX) but we still isolate it.
        """
        while True:
            batch: List[BatchRequest] = []

            # Block until the first request arrives
            try:
                first = self._queue.get(timeout=1.0)
                batch.append(first)
            except queue.Empty:
                continue

            # Accumulate more requests up to MAX_DELAY_MS or MAX_BATCH_SIZE
            deadline = time.monotonic() + self.max_delay_s
            while len(batch) < self.max_batch_size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    item = self._queue.get(timeout=remaining)
                    batch.append(item)
                except queue.Empty:
                    break

            # Run inference on the full batch at once
            try:
                features_batch = np.vstack([r.features for r in batch])
                scores = self.model.predict_proba(features_batch)[:, 1]
                # Return results to each waiting coroutine
                for req, score in zip(batch, scores):
                    if self._loop:
                        self._loop.call_soon_threadsafe(
                            req.future.set_result, float(score)
                        )
            except Exception as exc:
                for req in batch:
                    if self._loop:
                        self._loop.call_soon_threadsafe(
                            req.future.set_exception, exc
                        )

# ============================================================
# SECTION 4: ONNX RUNTIME INFERENCE
# ============================================================
# ONNX (Open Neural Network Exchange) is a universal model format.
# Export from PyTorch/TensorFlow → run with ONNX Runtime.
# ORT is typically 2-4x faster than native PyTorch on CPU.
# Supports hardware acceleration: CUDA, TensorRT, OpenVINO, CoreML.

# import onnxruntime as ort
# import numpy as np
#
# ONNX SESSION OPTIONS — set once at startup
# opts = ort.SessionOptions()
# opts.intra_op_num_threads = 4      # threads for within-op parallelism
# opts.inter_op_num_threads = 1      # threads between ops (usually 1)
# opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
#
# Create session — loads model into memory, compiles graph
# Provider priority: try CUDA first, fall back to CPU
# sess = ort.InferenceSession(
#     "model.onnx",
#     sess_options=opts,
#     providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
# )
#
# Get input/output names (needed for sess.run())
# input_name  = sess.get_inputs()[0].name    # e.g. "input"
# output_name = sess.get_outputs()[0].name   # e.g. "output"
#
# Inference — input must be numpy array matching model's expected dtype/shape
# input_array = np.array(features, dtype=np.float32)
# result = sess.run([output_name], {input_name: input_array})
# scores = result[0]   # numpy array of predictions
#
# EXPORT from PyTorch:
# torch.onnx.export(
#     model,
#     dummy_input,
#     "model.onnx",
#     opset_version=17,
#     input_names=["input"],
#     output_names=["output"],
#     dynamic_axes={"input": {0: "batch_size"}, "output": {0: "batch_size"}},
# )

# ============================================================
# SECTION 5: TORCHSERVE
# ============================================================
# TorchServe is PyTorch's official production model server.
# Packages models into .mar archives (Model ARchive).
# Three APIs:
#   Inference API (8080): POST /predictions/{model_name}
#   Management API (8081): register/deregister/scale models
#   Metrics API (8082): Prometheus-format metrics

# CREATE MAR FILE:
# torch-model-archiver \
#   --model-name fraud_detector \
#   --version 1.0 \
#   --model-file model.py \
#   --serialized-file model.pth \
#   --handler fraud_handler.py \
#   --extra-files vocab.json \
#   --export-path model_store/

# START SERVER:
# torchserve --start \
#   --model-store model_store/ \
#   --models fraud_detector=fraud_detector.mar \
#   --ts-config config.properties

# config.properties (key settings):
#   inference_address=http://0.0.0.0:8080
#   management_address=http://0.0.0.0:8081
#   metrics_address=http://0.0.0.0:8082
#   number_of_netty_threads=4
#   job_queue_size=1000
#   batch_size=16            # dynamic batching
#   max_batch_delay=20       # ms — wait up to 20ms before running batch

# CUSTOM HANDLER — controls preprocess/inference/postprocess:
# from ts.torch_handler.base_handler import BaseHandler
#
# class FraudHandler(BaseHandler):
#     def preprocess(self, data):
#         """Convert raw request bytes/JSON → torch.Tensor."""
#         import json, torch
#         rows = [json.loads(d["body"]) for d in data]
#         features = [[r["amount"], r["hour"], r["freq_7d"]] for r in rows]
#         return torch.FloatTensor(features)
#
#     def inference(self, data):
#         """Run model forward pass. data is batched tensor."""
#         with torch.no_grad():
#             return self.model(data)
#
#     def postprocess(self, data):
#         """Convert tensor → JSON-serializable list."""
#         return data.numpy().tolist()

# MANAGEMENT API calls (curl):
#   Register:   POST /models?url=fraud_detector.mar&model_name=fraud_detector
#   Scale:      PUT  /models/fraud_detector?min_worker=2&max_worker=8
#   Status:     GET  /models/fraud_detector
#   Deregister: DELETE /models/fraud_detector

# ============================================================
# SECTION 6: TRITON INFERENCE SERVER (NVIDIA)
# ============================================================
# Triton is NVIDIA's production inference server. Supports:
# TensorRT, ONNX Runtime, PyTorch (TorchScript), TensorFlow, Python backend.
# Key features: concurrent model execution, dynamic batching, model ensembles,
# GPU instance groups, built-in Prometheus metrics.

# MODEL REPOSITORY structure:
# model_repository/
#   fraud_detector/
#     config.pbtxt        ← model configuration
#     1/                  ← version 1
#       model.onnx        ← or model.plan (TensorRT), model.pt, etc.
#     2/                  ← version 2 (older versions kept for rollback)
#       model.onnx

# config.pbtxt example:
# name: "fraud_detector"
# backend: "onnxruntime"
# max_batch_size: 64
#
# input [{
#   name: "input"
#   data_type: TYPE_FP32
#   dims: [3]              # 3 features per sample; batch dim is implicit
# }]
# output [{
#   name: "output"
#   data_type: TYPE_FP32
#   dims: [1]
# }]
#
# dynamic_batching {
#   preferred_batch_size: [8, 16, 32]
#   max_queue_delay_microseconds: 5000   # 5ms max wait
# }
#
# instance_group [{
#   kind: KIND_GPU
#   count: 2               # 2 model instances on GPU (parallelism)
#   gpus: [0]
# }]

# START TRITON:
# docker run --gpus all -p 8000:8000 -p 8001:8001 -p 8002:8002 \
#   -v /path/to/model_repository:/models \
#   nvcr.io/nvidia/tritonserver:24.01-py3 \
#   tritonserver --model-repository=/models

# gRPC INFERENCE (lower latency than REST):
# import tritonclient.grpc as grpcclient
# import numpy as np
#
# client = grpcclient.InferenceServerClient("localhost:8001")
# input_tensor = grpcclient.InferInput("input", [1, 3], "FP32")
# input_tensor.set_data_from_numpy(np.array([[200.0, 14, 5]], dtype=np.float32))
# result = client.infer("fraud_detector", [input_tensor])
# score = result.as_numpy("output")[0, 0]

# ENSEMBLE MODEL — combine preprocessing + model + postprocessing
# in a single request (avoids multiple round trips):
# preprocessing → fraud_detector → thresholding
# All three run server-side; client sends raw input, gets final label.

# ============================================================
# SECTION 7: gRPC vs REST FOR MODEL SERVING
# ============================================================
# REST:   JSON over HTTP/1.1. Human-readable. Easy to debug. Larger payload.
#         Good for: management APIs, dashboards, low-traffic endpoints.
#
# gRPC:   Protocol Buffers over HTTP/2. Binary format (~7x smaller payload).
#         10-30% lower latency than equivalent JSON REST. Streaming support.
#         Good for: high-throughput inference, inter-service communication.
#
# For model serving: use gRPC for the inference path.
#                    use REST for health, management, monitoring.
#
# Latency comparison (same model, same hardware):
#   REST  (JSON): ~45ms P99
#   gRPC  (proto): ~32ms P99
#   Improvement: ~29% latency reduction

# ============================================================
# SECTION 8: LATENCY BUDGET AND FEATURE RETRIEVAL
# ============================================================
# Total request latency = sum of all components in the serving path.
# You must budget each component explicitly:
#
# Example for a recommendation system (SLA: P99 < 100ms):
#
#   Network (client → gateway):          5ms
#   Request validation + auth:           2ms
#   Feature retrieval (Redis lookup):    8ms   ← often the bottleneck
#   Model inference (ONNX/Triton):      25ms
#   Postprocessing + ranking:            5ms
#   Response serialization:              2ms
#   Network (gateway → client):          5ms
#   ─────────────────────────────────────────
#   Total P50:                          52ms   ✓ within budget
#   Total P99 (with queue/retry):       85ms   ✓ within budget
#
# FEATURE RETRIEVAL STRATEGIES:
#   1. Online Feature Store (Feast/Tecton → Redis/DynamoDB)
#      - Pre-computed features served at <10ms
#      - Must be kept fresh (updated by streaming job)
#   2. Request-time features: computed from the raw request (cheap)
#   3. Cached features: LRU cache for frequent users/items
#   4. Never: compute heavy features (aggregations over raw events) at serve time

# ============================================================
# SECTION 9: HEALTH, READINESS, AND CIRCUIT BREAKER
# ============================================================

class CircuitBreaker:
    """
    Prevents cascading failures when the model is misbehaving.
    If error rate exceeds threshold in the observation window,
    open the circuit — return default prediction instead of calling model.
    Automatically closes after RECOVERY_SECONDS if errors stop.

    States:
        CLOSED  — normal operation, requests go to model
        OPEN    — circuit tripped, return default prediction
        HALF_OPEN — trial: let one request through, close if it succeeds
    """

    def __init__(self, error_threshold: float = 0.05,
                 window_seconds: int = 30,
                 recovery_seconds: int = 60,
                 default_prediction: float = 0.5):
        self.error_threshold = error_threshold  # 5% error rate triggers open
        self.window_seconds = window_seconds
        self.recovery_seconds = recovery_seconds
        self.default_prediction = default_prediction

        self._requests = 0
        self._errors = 0
        self._window_start = time.monotonic()
        self._open_since: Optional[float] = None
        self._state = "CLOSED"  # CLOSED | OPEN | HALF_OPEN

    @property
    def is_open(self) -> bool:
        return self._state == "OPEN"

    def record_success(self):
        self._requests += 1
        if self._state == "HALF_OPEN":
            self._state = "CLOSED"
            self._reset_counters()

    def record_failure(self):
        self._requests += 1
        self._errors += 1
        self._check_threshold()

    def _check_threshold(self):
        now = time.monotonic()
        if now - self._window_start > self.window_seconds:
            self._reset_counters()
            return

        if self._requests >= 10:  # need minimum sample size
            error_rate = self._errors / self._requests
            if error_rate > self.error_threshold and self._state == "CLOSED":
                self._state = "OPEN"
                self._open_since = now
                logger.warning(
                    f"Circuit OPEN: error_rate={error_rate:.2%} "
                    f"over {self._requests} requests"
                )

    def _reset_counters(self):
        self._requests = 0
        self._errors = 0
        self._window_start = time.monotonic()
        # After recovery period, try half-open
        if (self._state == "OPEN" and self._open_since and
                time.monotonic() - self._open_since > self.recovery_seconds):
            self._state = "HALF_OPEN"
            logger.info("Circuit HALF_OPEN: trying one request")


# ============================================================
# SECTION 10: CANARY DEPLOYMENT
# ============================================================
# Run two model versions simultaneously. Route a small percentage
# of traffic to the new (challenger) model. Compare metrics before
# making the full switch. Zero-downtime upgrade with rollback safety.

import random


class CanaryRouter:
    """
    Routes requests between champion and challenger model.
    Start with 5% to challenger, gradually increase as confidence grows.
    """

    def __init__(self, champion_model, challenger_model,
                 challenger_fraction: float = 0.1):
        self.champion = champion_model
        self.challenger = challenger_model
        self.challenger_fraction = challenger_fraction  # 10% to challenger
        self._champion_latencies: List[float] = []
        self._challenger_latencies: List[float] = []

    def predict(self, features: np.ndarray) -> dict:
        use_challenger = random.random() < self.challenger_fraction
        model = self.challenger if use_challenger else self.champion
        version = "challenger" if use_challenger else "champion"

        start = time.monotonic()
        score = float(model.predict_proba(features)[0, 1])
        latency = time.monotonic() - start

        # Track latencies per version for comparison
        if use_challenger:
            self._challenger_latencies.append(latency)
        else:
            self._champion_latencies.append(latency)

        return {
            "score": score,
            "model_version": version,
            "latency_ms": latency * 1000,
        }

    def promote_challenger(self):
        """After analysis shows challenger is better, promote it."""
        self.champion = self.challenger
        self.challenger_fraction = 0.0
        logger.info("Challenger promoted to champion. Canary complete.")


# ============================================================
# DEMONSTRATION
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    # Simulate a model with a predict_proba method
    class DummyModel:
        def predict_proba(self, X):
            rng = np.random.default_rng(seed=0)
            n = len(X)
            probs = rng.uniform(0, 1, size=(n, 2))
            probs = probs / probs.sum(axis=1, keepdims=True)
            return probs

    model = DummyModel()

    # Demo circuit breaker
    cb = CircuitBreaker(error_threshold=0.05, default_prediction=0.5)
    for _ in range(5):
        cb.record_success()
    print(f"Circuit state after 5 successes: {cb._state}")  # CLOSED

    # Demo canary router
    champion = DummyModel()
    challenger = DummyModel()
    router = CanaryRouter(champion, challenger, challenger_fraction=0.2)
    features = np.array([[200.0, 14, 5]])
    result = router.predict(features)
    print(f"Canary prediction: {result}")

# ============================================================
# KEY TAKEAWAYS
# ============================================================
# - Load model at startup (lifespan/startup event), never per-request.
# - Dynamic batching is essential on GPU — 10-50x throughput gain.
# - ONNX Runtime is the fastest option for CPU inference in Python.
# - Triton handles multi-framework, high-scale GPU serving with built-in
#   dynamic batching, metrics, and concurrent model execution.
# - Budget every millisecond in the serving path — feature retrieval
#   often dominates, not model inference.
# - Always have /health (liveness) and /ready (readiness) — K8s needs both.
# - Circuit breakers and canary deployments are production necessities,
#   not optional polish.
