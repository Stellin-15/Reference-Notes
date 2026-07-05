# ============================================================
# L25: Nginx vs Envoy vs HAProxy — Choosing a Real Load Balancer/Proxy
# ============================================================
# WHAT: A concrete comparison of the three most widely-used production
#       reverse-proxy/load-balancer implementations — their configuration
#       models, architectural strengths, and the actual scenarios each
#       is most commonly chosen for.
# WHY: L21-L24 covered load balancing/reverse-proxy CONCEPTS in the
#      abstract. This lesson grounds those concepts in the REAL tools
#      you'd actually deploy, and the genuine tradeoffs between them —
#      directly answering "which framework, and why" for this infra track.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
NGINX began as a high-performance WEB SERVER (serving static files) that
grew reverse-proxy and load-balancing capabilities over time — its
configuration is FILE-BASED and STATIC (a text config file, reloaded on
change), which is simple to reason about and extremely well-documented,
but changes typically require a config reload (a brief, usually
low-impact operation, but not truly dynamic runtime reconfiguration
without additional tooling). Nginx excels at general-purpose reverse
proxying, static content serving, and straightforward load balancing —
it's frequently the DEFAULT choice for a standard web application's
proxy/load-balancing needs specifically because of its maturity,
performance, and simplicity for the common case.

HAPROXY was built SPECIFICALLY as a dedicated load balancer from the
start (not a web server that grew the capability) — it's widely regarded
as offering the most SOPHISTICATED and battle-tested LOAD BALANCING
ALGORITHM options and extremely detailed connection-level statistics/
observability, making it a common choice specifically for high-traffic,
performance-critical load-balancing needs (including as the load
balancer underneath managed cloud load-balancer products at several
major providers) where load-balancing behavior itself is the primary requirement.

ENVOY was built at Lyft specifically for MODERN MICROSERVICES and SERVICE
MESH architectures (this repo's Platform Engineering Notes and
Kubernetes Notes touch on service mesh concepts) — its defining
characteristic is a DYNAMIC, API-DRIVEN configuration model (the "xDS"
APIs) that allows configuration to be pushed and updated at RUNTIME
without restarts or reloads, essential for environments where backend
instances are constantly changing (containers scaling up/down,
Kubernetes pods being rescheduled) — this dynamic model is precisely why
Envoy is the DEFAULT DATA PLANE for popular service mesh implementations
(Istio being the most prominent), which need to continuously
reconfigure routing as the underlying infrastructure changes far more
frequently than a traditional static-config reverse proxy was ever designed to handle.

CHOOSING BETWEEN THEM in practice: Nginx for straightforward web
app/API reverse proxying where configuration changes infrequently;
HAProxy when load-balancing sophistication/performance is the primary,
dominant requirement; Envoy specifically for Kubernetes/microservices/
service-mesh environments where DYNAMIC, frequently-changing backend
topology is the norm rather than the exception — this isn't a strict
hierarchy of "better/worse," but a genuine fit-for-purpose decision
based on the deployment environment's actual characteristics.

PRODUCTION USE CASE:
A company running a traditional monolithic web application with a
STABLE, rarely-changing set of backend servers uses Nginx for its
simplicity and maturity; that SAME company's newer microservices
platform, running on Kubernetes with pods scaling up/down constantly
and being rescheduled across nodes throughout the day, uses Envoy
(via Istio) specifically because its dynamic configuration model can
keep up with that CONSTANTLY changing backend topology without requiring
manual or scripted config reloads on every single pod change.

COMMON MISTAKES:
- Choosing Envoy/a full service mesh for a simple, small-scale
  application with a stable backend topology — this adds substantial
  operational complexity (learning curve, additional moving parts) that
  isn't justified unless the DYNAMIC reconfiguration capability is
  actually needed for genuinely fast-changing infrastructure.
- Choosing Nginx (static config) for a Kubernetes environment with
  frequently rescheduled pods without additional tooling to keep its
  configuration in sync — Nginx CAN be used with Kubernetes (via
  ingress controllers that regenerate config on change), but this is
  architecturally working AROUND Nginx's static-config design rather
  than a capability it was built for from the ground up, unlike Envoy's native dynamic model.
- Assuming ANY of these three is a strictly "better" default choice
  regardless of environment — each was built with a genuinely different
  primary use case in mind, and the right choice depends on the
  deployment's actual topology stability and configuration-change frequency.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Configuration model comparison
# ------------------------------------------------------------------
NGINX_CONFIG_EXAMPLE = textwrap.dedent("""\
    # Nginx: static, file-based configuration (reloaded on change)
    upstream backend_pool {
        server 10.0.1.10:8080 weight=2;
        server 10.0.1.11:8080 weight=1;
        server 10.0.1.12:8080 backup;   # only used if others are down
    }

    server {
        listen 443 ssl;
        location /api/ {
            proxy_pass http://backend_pool;
            proxy_set_header X-Forwarded-For $remote_addr;
        }
    }
    # Changing the backend pool requires editing this file and reloading
    # nginx (a fast, low-impact operation, but not a live API call).
""")

HAPROXY_CONFIG_EXAMPLE = textwrap.dedent("""\
    # HAProxy: also file-based, but with extremely granular
    # load-balancing algorithm and health-check tuning options
    backend backend_pool
        balance leastconn
        option httpchk GET /health
        server server1 10.0.1.10:8080 check weight 20
        server server2 10.0.1.11:8080 check weight 10
        server server3 10.0.1.12:8080 check backup
    # HAProxy's stats page and logging provide very detailed
    # per-backend connection/latency observability out of the box.
""")

ENVOY_CONFIG_EXAMPLE = textwrap.dedent("""\
    # Envoy: dynamic, API-driven configuration (xDS) — this snippet
    # shows the STATIC bootstrap form, but production Envoy deployments
    # typically fetch this configuration DYNAMICALLY from a control
    # plane (e.g. Istio's istiod) that pushes UPDATES in real time as
    # backends change, with NO restart or reload required.
    clusters:
      - name: backend_pool
        type: EDS   # Endpoint Discovery Service — backends discovered
                    # DYNAMICALLY at runtime, not hardcoded in a static file
        lb_policy: LEAST_REQUEST
        health_checks:
          - http_health_check:
              path: "/health"
    # As Kubernetes pods scale up/down or get rescheduled, the control
    # plane pushes updated endpoint lists to Envoy CONTINUOUSLY.
""")


# ------------------------------------------------------------------
# 2. Decision framework
# ------------------------------------------------------------------
def choose_reverse_proxy(environment: str) -> str:
    decision_map = {
        "traditional web app, stable backend servers": "Nginx",
        "high-performance dedicated load balancing, detailed stats needed": "HAProxy",
        "kubernetes microservices, frequently changing backend topology": "Envoy (often via Istio)",
    }
    return decision_map.get(environment, "Evaluate based on actual configuration-change frequency")


if __name__ == "__main__":
    print(NGINX_CONFIG_EXAMPLE)
    print(HAPROXY_CONFIG_EXAMPLE)
    print(ENVOY_CONFIG_EXAMPLE)

    print("Decision framework:")
    for env in [
        "traditional web app, stable backend servers",
        "high-performance dedicated load balancing, detailed stats needed",
        "kubernetes microservices, frequently changing backend topology",
    ]:
        print(f"  {env} -> {choose_reverse_proxy(env)}")

"""
PRODUCTION CONTEXT EXAMPLE:
A platform engineering team (this repo's Platform Engineering Notes)
running a Kubernetes-based internal developer platform adopts Istio
(built on Envoy) specifically because pods are rescheduled dozens of
times per day across their cluster's autoscaling nodes — Envoy's dynamic
xDS configuration model keeps routing correct continuously without any
manual intervention, a capability a static-config tool like Nginx or
HAProxy would require substantial additional automation tooling to
approximate, precisely because those tools were designed assuming a
comparatively stable backend topology as the common case.
"""
