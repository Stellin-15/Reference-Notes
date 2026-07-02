# ============================================================
# L06: Cilium — eBPF-Powered Kubernetes Networking
# ============================================================
# WHAT: A CNI (Container Network Interface) plugin that replaces
#       iptables-based kube-proxy and traditional overlay networking with
#       an eBPF datapath.
# WHY (PRODUCTION): iptables rule evaluation is O(n) in the number of
#       services — at thousands of services, packet processing latency
#       degrades measurably. Cilium's eBPF datapath uses hash-map lookups
#       (O(1)) for service routing, and adds L7-aware network policy and
#       deep flow observability (Hubble) that iptables can't express.
# LEVEL: Senior / Staff platform engineer
# ============================================================

"""
CONCEPT OVERVIEW:
Cilium replaces two things simultaneously: kube-proxy (Service -> Pod IP
translation, normally done via iptables/IPVS rules) and the CNI's basic pod
networking (normally an overlay like VXLAN via Flannel/Calico). Both are
reimplemented as eBPF programs attached at various points (TC hooks, XDP,
socket-level hooks for even faster same-node routing).

Hubble is Cilium's observability component — since every packet already
flows through Cilium's eBPF datapath, Hubble can export flow-level
visibility (who talked to whom, on what port, allowed or denied) essentially
for free, without a separate packet-capture agent.

PRODUCTION USE CASE:
A 500-node Kubernetes cluster migrates from Calico (iptables-based) to
Cilium's eBPF datapath as kube-proxy replacement. Service-to-service p99
latency for east-west traffic drops measurably, because Service VIP
translation is now a single BPF map lookup instead of traversing hundreds
of iptables chains. CiliumNetworkPolicy enforces L7-aware rules (e.g.
"payments-service may only call GET /health and POST /charge on
billing-service", not just "may connect on port 443 at all").

COMMON MISTAKES:
- Migrating to Cilium's kube-proxy replacement without validating kernel
  version compatibility first — full functionality needs a reasonably
  modern kernel (5.x+) with BTF support; older nodes may only get partial
  feature support.
- Writing CiliumNetworkPolicies that are L3/L4 only when L7 policy was the
  actual requirement — verify the policy is actually inspecting HTTP
  methods/paths, not just allowing all traffic on the port.
- Enabling WireGuard transparent encryption without checking the CPU
  overhead on the busiest nodes — encryption isn't free, and undersized
  nodes can see meaningful CPU pressure increase.
"""

import textwrap

# ------------------------------------------------------------------
# 1. Cilium as kube-proxy replacement
# ------------------------------------------------------------------
KUBEPROXY_REPLACEMENT_NOTES = (
    "Standard Kubernetes Services are implemented via kube-proxy writing "
    "iptables (or IPVS) rules that DNAT a Service's ClusterIP to a "
    "backend Pod IP. Cilium instead maintains a BPF hash map of "
    "Service -> backend Pod IPs, and does the translation via a BPF "
    "program attached at the socket layer (for same-node traffic, "
    "avoiding even the TC/networking-stack traversal) or at TC hooks "
    "(for cross-node traffic) — an O(1) map lookup instead of O(n) "
    "iptables chain traversal, which matters increasingly as service "
    "count grows into the thousands."
)

CILIUM_INSTALL = textwrap.dedent("""\
    # Cilium CLI handles version compatibility checks and applies the
    # Helm chart with kube-proxy replacement enabled.
    cilium install --set kubeProxyReplacement=true

    # Verify the install and datapath mode
    cilium status --wait
    cilium status | grep KubeProxyReplacement
    # -> KubeProxyReplacement: True   [eth0 10.0.1.5 (Direct Routing)]
""")

# ------------------------------------------------------------------
# 2. CiliumNetworkPolicy — L3/L4/L7-aware policy
# ------------------------------------------------------------------
CILIUM_NETWORK_POLICY = textwrap.dedent("""\
    apiVersion: cilium.io/v2
    kind: CiliumNetworkPolicy
    metadata:
      name: payments-to-billing-l7
      namespace: payments
    spec:
      endpointSelector:
        matchLabels: { app: billing-service }
      ingress:
        - fromEndpoints:
            - matchLabels: { app: payments-service }
          toPorts:
            - ports: [{ port: "8080", protocol: TCP }]
              rules:
                http:
                  # L7-AWARE — a plain Kubernetes NetworkPolicy (or a raw
                  # iptables rule) can only express "allow port 8080",
                  # NOT "allow only these specific HTTP methods/paths".
                  # This closes off lateral movement even between two
                  # services that ARE allowed to talk to each other.
                  - method: "GET"
                    path: "/health"
                  - method: "POST"
                    path: "/charge"
""")

# ------------------------------------------------------------------
# 3. Hubble — network observability
# ------------------------------------------------------------------
HUBBLE_CLI_USAGE = textwrap.dedent("""\
    # Every flow already passes through Cilium's eBPF datapath — Hubble
    # exports flow metadata (source/dest identity, verdict, L7 details)
    # without needing a separate packet-capture sidecar.

    hubble observe --namespace payments --verdict DROPPED
    # TIMESTAMP        SOURCE                  DESTINATION            VERDICT
    # 12:03:14.221     payments-service        billing-service:8080   DROPPED (policy denied)

    hubble observe --http-method POST --http-path '/charge'
    # shows exactly which pods called this specific endpoint and when —
    # invaluable for both debugging AND security incident investigation

    # Hubble UI renders this as a live, filterable service dependency graph
""")

# ------------------------------------------------------------------
# 4. WireGuard transparent encryption
# ------------------------------------------------------------------
WIREGUARD_ENCRYPTION_NOTE = (
    "Cilium can transparently encrypt all pod-to-pod traffic between "
    "nodes using WireGuard, configured with a single Helm flag "
    "(`encryption.type=wireguard`) — no application code changes, no "
    "service mesh sidecar needed. This is a lighter-weight alternative "
    "to Istio's mTLS for teams who only need encryption-in-transit "
    "between nodes, not the full L7 traffic-management feature set of a "
    "service mesh (see Platform Engineering L05)."
)

# ------------------------------------------------------------------
# 5. ClusterMesh — multi-cluster networking
# ------------------------------------------------------------------
CLUSTERMESH_NOTE = (
    "ClusterMesh connects multiple Kubernetes clusters' Cilium datapaths "
    "so pods in cluster A can reach Services in cluster B using normal "
    "Kubernetes Service DNS names, with the same eBPF-level policy "
    "enforcement — used for multi-region active-active deployments or "
    "gradual cluster migrations where workloads temporarily need to span "
    "two clusters during a cutover."
)

# ------------------------------------------------------------------
# 6. Bandwidth manager — EDT-based egress rate limiting
# ------------------------------------------------------------------
BANDWIDTH_MANAGER_NOTE = (
    "Cilium's bandwidth manager uses EDT (Earliest Departure Time) "
    "queuing implemented in eBPF to rate-limit a pod's egress bandwidth "
    "per its `kubernetes.io/egress-bandwidth` annotation — enforced at "
    "the eBPF datapath level rather than a userspace traffic shaper, "
    "avoiding an extra hop's worth of latency for the enforcement itself."
)

# ------------------------------------------------------------------
# 7. Cilium service mesh — sidecar-free L7
# ------------------------------------------------------------------
SIDECAR_FREE_MESH_NOTE = (
    "Cilium can implement a meaningful subset of service-mesh L7 "
    "features (HTTP-aware policy, some traffic management) WITHOUT "
    "injecting an Envoy sidecar into every pod — using per-node shared "
    "eBPF programs and, for advanced L7 cases, a per-node (not per-pod) "
    "Envoy proxy instance. This trades some of Istio's fine-grained L7 "
    "feature parity for meaningfully lower per-pod resource overhead — "
    "worth evaluating when sidecar CPU/memory tax is the dominant cost "
    "concern in a large cluster."
)

# ------------------------------------------------------------------
# 8. Comparison: Cilium vs Calico vs Flannel vs AWS VPC CNI
# ------------------------------------------------------------------
CNI_COMPARISON = {
    "Cilium": "eBPF datapath, L7-aware NetworkPolicy, built-in "
        "observability (Hubble), can replace kube-proxy entirely. "
        "Highest feature ceiling, steepest learning curve.",
    "Calico": "iptables OR eBPF datapath (has its own eBPF mode too), "
        "strong NetworkPolicy support (L3/L4), mature and widely deployed. "
        "L7 policy support is less mature than Cilium's.",
    "Flannel": "Simplest possible overlay networking (VXLAN), NO network "
        "policy enforcement of its own — often paired with Calico's "
        "policy engine on top for that reason.",
    "AWS VPC CNI": "Assigns pods REAL VPC IP addresses (no overlay "
        "encapsulation) — best raw throughput on AWS, but consumes ENI/IP "
        "capacity per node, a real scaling constraint on IP-dense clusters.",
}

if __name__ == "__main__":
    for cni, desc in CNI_COMPARISON.items():
        print(f"{cni}: {desc}")

"""
TRADING/PRODUCTION CONTEXT EXAMPLE:
A market-data platform's Kubernetes cluster runs Cilium with L7
CiliumNetworkPolicy restricting the risk-engine pod to only accept POST
requests on /evaluate from the order-gateway service — even if an
attacker compromises another pod in the same namespace with valid L3/L4
network access, Hubble immediately shows the DROPPED verdict on any
unauthorized request path, and the eBPF-enforced policy blocks it before
it ever reaches the risk engine's application code.
"""
