# ============================================================
# L05: Platform Networking — Service Mesh with Istio
# ============================================================
# WHAT: A dedicated infrastructure layer (sidecar proxies) that handles
#       service-to-service traffic: mTLS, retries, timeouts, load balancing,
#       and observability — without any application code changes.
# WHY (PRODUCTION): Implementing retries/circuit-breaking/mTLS in every
#       service's code (in 6 different languages) is unmaintainable. A mesh
#       centralizes this in the network layer, configured declaratively.
# LEVEL: Senior backend / platform engineer
# ============================================================

"""
CONCEPT OVERVIEW:
Istio injects an Envoy proxy as a sidecar container into every pod. All
inbound/outbound traffic for that pod is transparently routed through its
Envoy sidecar via iptables rules. `istiod` is the control plane: it pushes
configuration (routing rules, TLS certs, service discovery) to every Envoy
in the mesh.

Because every request already flows through Envoy, the mesh can enforce
mTLS, collect uniform metrics, and apply traffic policies (canary splits,
circuit breakers) purely via configuration — no code changes in the
services themselves.

PRODUCTION USE CASE:
A 40-microservice platform enforces `PeerAuthentication: STRICT` mesh-wide —
every service-to-service call is automatically mutually authenticated and
encrypted, closing the "flat trusted internal network" attack surface. A
canary release of `checkout-service:v2` gets 5% of traffic via a
`VirtualService` weight split, with automatic rollback via outlier detection
if v2's error rate spikes.

COMMON MISTAKES:
- Enabling Istio without understanding the CPU/memory cost of a sidecar per
  pod (each Envoy proxy is a real, if usually small, tax).
- STRICT mTLS enabled before all services are in the mesh, breaking calls
  to non-meshed legacy services.
- Debugging "503 upstream connect error" without checking Envoy's own access
  logs (`istioctl proxy-config` / `kubectl logs <pod> -c istio-proxy`).
"""

import textwrap

# ------------------------------------------------------------------
# 1. mTLS — PeerAuthentication + DestinationRule
# ------------------------------------------------------------------
MTLS_CONFIG = textwrap.dedent("""\
    # Mesh-wide: require mTLS for every service in the mesh.
    apiVersion: security.istio.io/v1beta1
    kind: PeerAuthentication
    metadata:
      name: default
      namespace: istio-system
    spec:
      mtls:
        mode: STRICT   # PERMISSIVE allows plaintext during migration; STRICT
                        # is the production end-state — reject unencrypted traffic.
    ---
    # DestinationRule: tells CLIENT sidecars to use mTLS when calling this service.
    # (PeerAuthentication governs the SERVER side; DestinationRule governs the CLIENT.)
    apiVersion: networking.istio.io/v1beta1
    kind: DestinationRule
    metadata:
      name: billing-service
    spec:
      host: billing-service.payments.svc.cluster.local
      trafficPolicy:
        tls:
          mode: ISTIO_MUTUAL   # use the mesh's auto-rotated per-workload certs
""")

# ------------------------------------------------------------------
# 2. Traffic management — VirtualService + canary split
# ------------------------------------------------------------------
CANARY_TRAFFIC_SPLIT = textwrap.dedent("""\
    apiVersion: networking.istio.io/v1beta1
    kind: VirtualService
    metadata:
      name: checkout-service
    spec:
      hosts: [checkout-service]
      http:
        - route:
            - destination: { host: checkout-service, subset: v1 }
              weight: 90     # 90% of traffic to the stable version
            - destination: { host: checkout-service, subset: v2 }
              weight: 10     # 10% canary
          timeout: 3s
          retries:
            attempts: 2
            perTryTimeout: 1s
            retryOn: 5xx,reset,connect-failure
    ---
    apiVersion: networking.istio.io/v1beta1
    kind: DestinationRule
    metadata:
      name: checkout-service
    spec:
      host: checkout-service
      subsets:
        - name: v1
          labels: { version: v1 }   # matches pod label, selects the right pods
        - name: v2
          labels: { version: v2 }
""")

# ------------------------------------------------------------------
# 3. Circuit breaking — outlier detection
# ------------------------------------------------------------------
CIRCUIT_BREAKER_CONFIG = textwrap.dedent("""\
    apiVersion: networking.istio.io/v1beta1
    kind: DestinationRule
    metadata:
      name: inventory-service
    spec:
      host: inventory-service
      trafficPolicy:
        connectionPool:
          tcp:  { maxConnections: 100 }
          http: { http1MaxPendingRequests: 50, maxRequestsPerConnection: 10 }
        outlierDetection:
          # Eject a pod from the load-balancing pool after 5 consecutive
          # 5xx responses — this is the mesh doing circuit-breaking for you,
          # no client-side library needed.
          consecutive5xxErrors: 5
          interval: 10s
          baseEjectionTime: 30s
          maxEjectionPercent: 50   # never eject more than half the pool at once
""")

# ------------------------------------------------------------------
# 4. Gateway — ingress/egress traffic entry/exit points
# ------------------------------------------------------------------
GATEWAY_CONFIG = textwrap.dedent("""\
    apiVersion: networking.istio.io/v1beta1
    kind: Gateway
    metadata:
      name: public-gateway
    spec:
      selector: { istio: ingressgateway }
      servers:
        - port: { number: 443, name: https, protocol: HTTPS }
          tls: { mode: SIMPLE, credentialName: public-tls-cert }
          hosts: ["api.myorg.com"]
    ---
    apiVersion: networking.istio.io/v1beta1
    kind: VirtualService
    metadata:
      name: public-api-routes
    spec:
      hosts: ["api.myorg.com"]
      gateways: [public-gateway]
      http:
        - match: [{ uri: { prefix: "/v1/billing" } }]
          route: [{ destination: { host: billing-service } }]
""")

# ------------------------------------------------------------------
# 5. Envoy metrics and observability
# ------------------------------------------------------------------
ENVOY_METRICS = {
    "istio_requests_total": "counter, labeled by response_code/source/destination — the RED-method 'rate' and 'errors' signal.",
    "istio_request_duration_milliseconds": "histogram — the RED-method 'duration' signal, feeds p50/p99 dashboards.",
    "envoy_cluster_upstream_cx_active": "gauge of active upstream connections — useful for connection pool tuning.",
    "envoy_cluster_upstream_rq_pending_active": "gauge — requests queued waiting for a free connection (saturation signal).",
}

# ------------------------------------------------------------------
# 6. Kiali — mesh visualization
# ------------------------------------------------------------------
KIALI_NOTE = (
    "Kiali reads Istio's telemetry (via Prometheus) and renders a live "
    "topology graph: which services call which, at what error rate, with "
    "what latency. It's the fastest way to answer 'what does checkout-service "
    "actually talk to in production' without reading every deployment manifest."
)

# ------------------------------------------------------------------
# 7. Alternatives: Linkerd and Cilium service mesh
# ------------------------------------------------------------------
MESH_ALTERNATIVES = {
    "Linkerd": "Rust-based data plane (linkerd2-proxy), much lighter resource "
               "footprint than Envoy/Istio. Simpler feature set — often "
               "preferred when you mainly need mTLS + basic traffic splitting "
               "without Istio's full policy surface.",
    "Cilium Service Mesh": "eBPF-based — can implement L3/L4 policy and even "
                            "some L7 routing WITHOUT a sidecar proxy per pod, "
                            "using kernel-level enforcement instead. Lower "
                            "per-pod overhead, but less mature L7 feature "
                            "parity with Istio as of most current releases.",
}

if __name__ == "__main__":
    for metric, desc in ENVOY_METRICS.items():
        print(f"{metric}: {desc}")

"""
TRADING/PRODUCTION CONTEXT EXAMPLE:
A risk-check service must call 3 downstream services (position, pricing,
limits) before approving an order. Istio's outlier detection automatically
ejects a pricing-service pod that starts returning 5xx after a bad deploy,
routing traffic to healthy replicas within 10 seconds — without the
risk-check service's code containing a single line of retry/circuit-breaker
logic. Kiali's live graph is the first thing the on-call engineer opens
during an incident to see exactly which edge in the call graph is failing.
"""
