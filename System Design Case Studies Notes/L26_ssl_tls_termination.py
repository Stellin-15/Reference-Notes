# ============================================================
# L26: SSL/TLS Termination — Where Encryption Actually Ends
# ============================================================
# WHAT: What "TLS termination" means concretely, WHERE it happens in a
#       typical infrastructure stack, and the genuine security tradeoff
#       between terminating at the edge (re-encrypting internally or
#       not) vs passing encrypted traffic all the way to the backend.
# WHY: L24-L25 mentioned TLS termination as one of a reverse proxy's
#       responsibilities. This lesson covers it in the depth it deserves
#       — it's a security-critical decision with real, non-obvious tradeoffs.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
TLS TERMINATION means DECRYPTING incoming HTTPS traffic at some point in
the infrastructure stack — once terminated, the CLEARTEXT (unencrypted)
request continues onward from that point. The most common location for
this is the load balancer/reverse proxy (L24) — the CLIENT-to-proxy leg
of the connection is encrypted (protecting data as it crosses the
public internet), while what happens AFTER the proxy is a genuine architectural decision.

TERMINATE-AND-FORWARD-CLEARTEXT: after the proxy decrypts incoming
traffic, it forwards the request to backends as PLAIN, unencrypted
HTTP — this is simpler (backends never need to manage TLS certificates
at all) and slightly faster (no additional encryption/decryption
overhead internally), and is a REASONABLE choice when the internal
network between proxy and backends is genuinely trusted and isolated
(e.g. a private VPC subnet with no external access) — but it means ANY
compromise of that internal network (a misconfigured security group, an
attacker who's gained a foothold inside the network) exposes ALL
internal traffic in cleartext, which is a real and non-trivial security
exposure for any environment where "trusted internal network" isn't
airtight in practice.

TERMINATE-AND-RE-ENCRYPT (TLS RE-ENCRYPTION, sometimes called "TLS
bridging"): the proxy decrypts the client's TLS connection, then
establishes a SEPARATE, NEW TLS connection to the backend — this
provides DEFENSE IN DEPTH (encryption in transit for BOTH legs of the
journey, not just the public-facing one), at the cost of backends now
needing to manage their own TLS certificates and the additional
CPU overhead of a second encryption/decryption step. This is
increasingly the DEFAULT-RECOMMENDED approach in zero-trust security
models (this repo's Auth & Security Notes covers zero-trust
principles), which explicitly assume internal network compromise is a
realistic possibility that shouldn't automatically grant an attacker
cleartext access to all internal traffic.

TLS PASSTHROUGH is a THIRD option: the load balancer doesn't decrypt
traffic AT ALL — it operates purely at L4 (L21), forwarding encrypted
TCP packets straight to the backend, which performs its OWN TLS
termination directly. This means the load balancer has ZERO VISIBILITY
into the actual HTTP content (no L7 content-based routing possible,
since the traffic is never decrypted at this layer at all) but provides
TRUE end-to-end encryption with no intermediate decryption point
whatsoever — appropriate when regulatory/compliance requirements
mandate that literally no intermediate system ever sees decrypted
traffic, even briefly.

MUTUAL TLS (mTLS) extends normal TLS (which only verifies the SERVER's
identity to the client) to ALSO verify the CLIENT's identity to the
server via a client certificate — commonly used for SERVICE-TO-SERVICE
authentication within a service mesh (L25's Envoy/Istio commonly
implement mTLS automatically between mesh-internal services), ensuring
that even INTERNAL, re-encrypted traffic between backend services is
cryptographically authenticated in both directions, not just encrypted.

PRODUCTION USE CASE:
A financial services company operating under strict compliance
requirements uses TLS re-encryption (not cleartext-forward) between its
edge load balancer and every internal backend service, AND layers mTLS
on top for service-to-service authentication within its internal
service mesh — ensuring that even an attacker who somehow gains network
access to the internal VPC cannot passively observe cleartext traffic
OR impersonate a legitimate internal service without a valid client certificate.

COMMON MISTAKES:
- Terminating TLS at the edge and forwarding CLEARTEXT internally,
  without considering that "trusted internal network" is an assumption
  that can fail (misconfiguration, insider threat, a compromised
  adjacent service) — modern zero-trust security models explicitly
  reject this assumption, favoring re-encryption or mTLS instead.
- Choosing TLS PASSTHROUGH by default without needing its specific
  property (true end-to-end encryption with zero intermediate
  decryption) — this sacrifices ALL L7 content-based routing capability
  (L21) at the load balancer layer, a significant loss of routing
  flexibility that should be a deliberate tradeoff, not a default.
- Implementing re-encryption for CLIENT-facing security but never adding
  mTLS for SERVICE-to-service authentication internally — this encrypts
  internal traffic but still allows any process that gains internal
  network access to IMPERSONATE a legitimate backend service, since
  encryption alone doesn't verify identity in both directions.
"""

import textwrap


# ------------------------------------------------------------------
# 1. The three TLS termination models, illustrated
# ------------------------------------------------------------------
TERMINATION_MODELS = textwrap.dedent("""\
    MODEL 1 — Terminate and forward cleartext:

        [Client] --TLS--> [Load Balancer] --PLAIN HTTP--> [Backend]

        Simple, fast, but internal traffic is UNENCRYPTED — relies
        entirely on network-level trust/isolation for security.

    MODEL 2 — Terminate and re-encrypt (TLS bridging):

        [Client] --TLS--> [Load Balancer] --NEW TLS connection--> [Backend]

        Defense in depth: BOTH legs encrypted, but backends need their
        own certificates, and there's additional CPU cost for the
        second encrypt/decrypt cycle.

    MODEL 3 — TLS passthrough:

        [Client] --TLS (never decrypted by LB)--> [Backend decrypts directly]

        True end-to-end encryption, but the load balancer has ZERO
        visibility into HTTP content — no L7 routing possible at this layer.
""")

# ------------------------------------------------------------------
# 2. Deciding which model fits a given requirement
# ------------------------------------------------------------------
def choose_tls_model(requirements: dict) -> str:
    if requirements.get("needs_l7_routing") and requirements.get("zero_trust_internal"):
        return "Terminate and re-encrypt (Model 2) — get both L7 routing AND internal encryption"
    elif requirements.get("regulatory_no_intermediate_decryption"):
        return "TLS passthrough (Model 3) — compliance mandates zero intermediate visibility"
    elif requirements.get("trusted_isolated_network") and not requirements.get("zero_trust_internal"):
        return "Terminate and forward cleartext (Model 1) — acceptable given genuine network isolation"
    else:
        return "Default to Model 2 (re-encrypt) — the safest default for most modern environments"


def decision_demo():
    scenarios = [
        {"name": "Standard SaaS API needing path-based routing, zero-trust posture",
         "requirements": {"needs_l7_routing": True, "zero_trust_internal": True}},
        {"name": "Regulated finance system, compliance mandates no intermediate decryption",
         "requirements": {"regulatory_no_intermediate_decryption": True}},
    ]
    for scenario in scenarios:
        decision = choose_tls_model(scenario["requirements"])
        print(f"{scenario['name']}:")
        print(f"  -> {decision}\n")


if __name__ == "__main__":
    print(TERMINATION_MODELS)
    decision_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A healthcare platform subject to HIPAA compliance requirements uses TLS
re-encryption between its edge load balancer and internal microservices
(gaining L7 path-based routing for its API gateway) AND deploys mTLS via
a service mesh for service-to-service traffic within its Kubernetes
cluster — a deliberate, layered decision recognizing that "internal
network" and "trusted network" are not the same guarantee, especially
for a system handling regulated health data where a network-level
compromise having access to cleartext patient data would constitute a
severe, reportable incident.
"""
