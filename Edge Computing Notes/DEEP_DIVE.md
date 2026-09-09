# Edge Computing — Principal Engineer Deep Dive

Companion to the existing lessons. Narrative depth, then a comprehensive
common-to-uncommon tool reference.


## Why Edge Computing Exists

**Beyond the lesson**: Edge computing isn't "cloud, but smaller" — it's a
direct response to two physical constraints centralized cloud can't solve:
speed-of-light latency (a round trip to a distant region is bounded by
physics, not engineering effort — roughly 100ms+ for a real transcontinental
round trip no amount of optimization removes) and bandwidth cost/availability
(a factory floor with thousands of sensors can't economically stream all
raw data to a distant region continuously). Edge pushes compute physically
closer to where data is generated or consumed specifically to sidestep both constraints.

**Worked example**: A video-analytics pipeline for retail stores running
inference AT the store (edge) rather than streaming raw video to a cloud
region — the edge device runs a lightweight model (see LLM Quantization &
Inference Notes for the model-shrinking side of this) to detect events
locally, and only sends the SMALL, meaningful result (an alert, a metadata
event) to the cloud — cutting bandwidth needs by orders of magnitude versus
shipping raw video, and keeping detection latency low enough to be actionable in real time.

**Interview Q&A**:
- *Q: When does edge computing NOT make sense?* A: When latency isn't user-facing/real-time-critical and data volume is modest — the operational complexity of managing distributed edge infrastructure (patching, monitoring, connectivity-loss handling across many physical sites) is real overhead that centralized cloud avoids; edge is a deliberate tradeoff, not a default upgrade.


## CDN Edge vs Compute Edge

**Beyond the lesson**: "Edge" means different things at different layers,
and conflating them causes real confusion in interviews and architecture
discussions. CDN edge (Cloudflare, Fastly, Akamai's original model) caches
STATIC content close to users — no general-purpose compute involved beyond
cache rules. Edge FUNCTIONS (Cloudflare Workers, Fastly Compute, Lambda@Edge)
run actual application logic at those same edge locations — a genuinely
different capability (personalization, A/B testing, auth checks) that
happens BEFORE a request ever reaches the origin. IoT/industrial edge
(the L01-style "edge computing" most people picture) is a third, physically
distinct thing — compute on real physical devices/gateways at a factory,
vehicle, or retail location, with intermittent/unreliable connectivity as
the defining constraint CDN edge never has to consider.

**Interview Q&A**:
- *Q: How is a Cloudflare Worker different from a Lambda function?* A: Workers run in V8 isolates (not full containers/VMs) distributed across hundreds of global edge locations, start in single-digit milliseconds with no cold-start penalty comparable to Lambda's, and are deployed by default to EVERY location simultaneously — optimized specifically for low-latency, globally-distributed request handling rather than Lambda's more general-purpose, single-region-by-default compute model.


## COMPREHENSIVE TOOL REFERENCE — COMMON TO UNCOMMON

### Edge compute/serverless platforms
- **Cloudflare Workers** — V8-isolate-based, the fastest-starting edge
  compute option, runs at 300+ global locations by default.
- **Fastly Compute@Edge** — WASM-based edge compute, similar niche to Workers.
- **AWS Lambda@Edge / CloudFront Functions** — AWS's edge compute tiers;
  CloudFront Functions are lighter/faster but far more limited (no network
  calls); Lambda@Edge is fuller-featured but slower to cold-start.
- **Vercel Edge Functions / Netlify Edge Functions** — frontend-platform-
  native edge compute, mostly used for personalization/redirects/A-B
  testing at the CDN layer in modern JAMstack-style deployments.

### IoT/industrial edge platforms
- **AWS IoT Greengrass / Azure IoT Edge / Google Distributed Cloud Edge** —
  the major clouds' own "run cloud-managed workloads on edge hardware" offerings,
  giving centralized fleet management/deployment for distributed physical devices.
- **K3s / MicroK8s / KubeEdge** — lightweight Kubernetes distributions
  purpose-built to run on resource-constrained edge hardware, letting edge
  fleets be managed with the same K8s tooling/mental model as cloud clusters.
- **MQTT** — the dominant lightweight pub/sub protocol for IoT device
  communication specifically because it's designed for unreliable,
  low-bandwidth, high-latency links (unlike HTTP, which assumes a
  reasonably reliable connection) — QoS levels 0/1/2 trade delivery
  guarantees against overhead explicitly for this environment.

### Content delivery & edge caching
- **Cloudflare / Akamai / Fastly / AWS CloudFront** — the major CDN
  providers; differentiate on edge-compute capability, cache-purge speed,
  and network footprint size more than raw caching mechanics, which are similar across all four.
- **Cache invalidation strategies**: TTL-based (simplest, has propagation
  delay), tag-based purge (invalidate everything tagged "product-123"
  instantly across the whole network), and stale-while-revalidate (serve
  the stale cached version immediately while fetching a fresh one in the
  background) — each solves a different freshness-vs-latency tradeoff.

### Edge AI/ML inference
- **NVIDIA Jetson** — the dominant edge-AI hardware platform for real
  camera/sensor-based inference (robotics, retail analytics, autonomous
  systems) — GPU-accelerated but power/thermal-constrained versus datacenter GPUs.
- **TensorFlow Lite / ONNX Runtime / Core ML** — the model-serving runtimes
  purpose-built for constrained edge devices, pairing directly with the
  quantization techniques covered in LLM Quantization & Inference Notes.


## NICHE BUT REAL

- **Fog computing** — an intermediate tier between edge devices and the
  cloud (a local gateway/mini-datacenter serving a factory or campus) — a
  distinct architectural layer from both "edge device" and "cloud region,"
  useful when a single edge device is too constrained but the full cloud
  round-trip is still too slow/expensive.
- **Edge-to-cloud sync conflict resolution** — edge devices that operate
  offline and later reconnect need CRDT-style (Conflict-free Replicated
  Data Type) or explicit last-write-wins/merge logic to reconcile changes
  made during the disconnected period — a real distributed-systems problem
  edge architectures can't avoid.
- **Digital twins** — a live, continuously-updated virtual model of a
  physical system (a factory line, a fleet of vehicles) fed by edge
  telemetry — increasingly used for simulation/predictive-maintenance,
  worth knowing as a named pattern in industrial-edge contexts.
- **5G MEC (Multi-access Edge Computing)** — telecom-operator-hosted edge
  compute integrated directly into 5G network infrastructure, aimed at
  ultra-low-latency use cases (AR/VR, autonomous vehicles) that even a
  nearby cloud region's latency can't satisfy.
