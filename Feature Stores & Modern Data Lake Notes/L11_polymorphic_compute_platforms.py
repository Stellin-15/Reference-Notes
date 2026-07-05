# ============================================================
# L11: Polymorphic Compute Platforms — The Kernels-as-a-Service Pattern
# ============================================================
# WHAT: The architectural pattern behind "run my Jupyter notebook against
#       whichever compute backend makes sense" — abstracting YARN,
#       Kubernetes, cloud ML platforms (Vertex AI), and Ray behind ONE
#       notebook interface, using a ProcessProxy abstraction and a
#       Jupyter Kernel Gateway, with auth tokens propagated through
#       long-lived kernel sessions.
# WHY: A feature/data platform (L01-L10) needs data scientists to
#      actually RUN CODE against the platform's data — often at wildly
#      different scales (a quick exploratory query vs a multi-hour
#      distributed training job) and across heterogeneous infrastructure
#      (on-prem Hadoop clusters, cloud GPU pools, lightweight Ray
#      clusters). This lesson covers the pattern that makes "just pick
#      compute size/type from a dropdown" possible from ONE notebook UI.
# LEVEL: Advanced (final lesson before the capstone)
# ============================================================

"""
CONCEPT OVERVIEW:
A JUPYTER NOTEBOOK's execution model separates the NOTEBOOK UI/DOCUMENT
(what the user sees and edits) from the KERNEL (the actual running
process executing code cells) — these can be, and in a platform context
ARE, on entirely different machines. The KERNEL GATEWAY is the component
that lets a notebook UI connect to a kernel running on REMOTE
infrastructure over the network, rather than the traditional model of a
kernel running as a local subprocess on the same machine as the notebook UI.

A PROCESS PROXY is the abstraction that decides HOW and WHERE to actually
launch that remote kernel process — instead of Jupyter's default
"spawn a local subprocess," a custom ProcessProxy implementation can
submit a kernel launch request to YARN (as an application), to Kubernetes
(as a pod), to a cloud ML platform's managed notebook/training
infrastructure (Vertex AI), or to a Ray cluster (as a Ray actor) — the
SAME notebook UI, the SAME user-facing experience, with the ProcessProxy
layer translating "start a kernel" into whatever that specific
backend's actual launch mechanism requires. This is the POLYMORPHIC
COMPUTE idea: one interface, many possible backend implementations,
selected per-session (often via a UI dropdown: "Small/CPU," "Large/GPU,"
"Distributed/Ray") rather than requiring the data scientist to know
each backend's own API/CLI/submission mechanism.

AUTH TOKEN PROPAGATION is the specific, often-overlooked hard problem
this pattern introduces: a user authenticates ONCE (e.g. via OAuth2 to
the platform's web UI), but their kernel — potentially running for HOURS
on a remote YARN/K8s node — needs to make AUTHENTICATED requests back to
platform services (the feature store, L01-L10; a model registry) on the
user's behalf, for the ENTIRE lifetime of that long-running kernel
session, not just at initial launch. This requires propagating an access
token THROUGH the launch chain (from the user's browser session, through
the Kernel Gateway, into the ProcessProxy's launch request, into the
kernel's own runtime environment) AND handling TOKEN EXPIRY during a
long-running session — a token issued at kernel launch that expires
after an hour is not sufficient for an 8-hour training job; a
TOKEN REFRESHER mechanism running alongside the long-lived kernel must
proactively renew the token before it expires, transparently to the
user's running code.

PRODUCTION USE CASE:
A data scientist opens one notebook interface and, via a compute-
selection dropdown, launches a lightweight exploratory kernel on a small
shared Kubernetes pool for quick data exploration, then later launches a
SEPARATE, large distributed kernel on the organization's on-prem YARN
cluster for an overnight feature-engineering job over petabytes of
historical data — both experiences happen through the SAME notebook UI
and the SAME authenticated session, with the platform's ProcessProxy
layer handling the entirely different underlying launch mechanisms
transparently, and the overnight job's auth token being silently
refreshed multiple times without the data scientist's code needing any
awareness of token lifecycle at all.

COMMON MISTAKES:
- Building separate, backend-specific UIs/workflows for each compute
  type (a YARN launcher, a separate K8s launcher, a separate cloud
  notebook flow) instead of one unified interface with a ProcessProxy
  abstraction underneath — this multiplies the data scientist's cognitive
  load and the platform team's UI maintenance burden for no benefit.
- Issuing a SHORT-LIVED auth token at kernel launch with no refresh
  mechanism for long-running sessions — this either forces artificially
  short kernel lifetimes (disrupting genuinely long-running work) or,
  worse, tempts implementers into issuing an overly long-lived token
  upfront as a workaround, which is a real security risk (a long-lived,
  broadly-scoped credential sitting in a remote kernel's memory for hours).
- Not isolating DIFFERENT backends' resource pools from each other —
  a runaway exploratory-tier kernel consuming resources meant for the
  production-tier distributed compute pool (or vice versa) undermines
  the whole point of offering differentiated compute tiers in the first place.
"""

import textwrap
from dataclasses import dataclass
from datetime import datetime, timedelta


# ------------------------------------------------------------------
# 1. The ProcessProxy abstraction — one interface, multiple backends
# ------------------------------------------------------------------
class ProcessProxy:
    """The abstract interface every backend-specific launcher implements
    — the Kernel Gateway calls THIS interface, never a backend-specific
    API directly."""

    def launch_kernel(self, user_id: str, auth_token: str, resource_profile: str) -> str:
        raise NotImplementedError

    def terminate_kernel(self, kernel_id: str):
        raise NotImplementedError


class YarnProcessProxy(ProcessProxy):
    def launch_kernel(self, user_id: str, auth_token: str, resource_profile: str) -> str:
        # A real implementation submits a YARN application via the YARN
        # REST API, passing the auth_token through as an environment
        # variable/config the launched container can read.
        print(f"  [YARN] submitting application for {user_id}, profile={resource_profile}")
        return f"yarn-app-{user_id}-{datetime.now().timestamp():.0f}"


class KubernetesProcessProxy(ProcessProxy):
    def launch_kernel(self, user_id: str, auth_token: str, resource_profile: str) -> str:
        # A real implementation creates a Kubernetes Pod via the K8s API,
        # mounting the auth_token as a Secret the pod's container reads.
        print(f"  [K8s] creating pod for {user_id}, profile={resource_profile}")
        return f"k8s-pod-{user_id}-{datetime.now().timestamp():.0f}"


class VertexAIProcessProxy(ProcessProxy):
    def launch_kernel(self, user_id: str, auth_token: str, resource_profile: str) -> str:
        # A real implementation calls the Vertex AI Workbench/custom
        # training job API to provision managed notebook compute.
        print(f"  [Vertex AI] provisioning managed notebook for {user_id}, profile={resource_profile}")
        return f"vertex-notebook-{user_id}-{datetime.now().timestamp():.0f}"


class RayProcessProxy(ProcessProxy):
    def launch_kernel(self, user_id: str, auth_token: str, resource_profile: str) -> str:
        # A real implementation submits a Ray job/actor to an existing
        # Ray cluster for distributed, in-cluster kernel execution.
        print(f"  [Ray] submitting kernel actor for {user_id}, profile={resource_profile}")
        return f"ray-actor-{user_id}-{datetime.now().timestamp():.0f}"


# ------------------------------------------------------------------
# 2. The Kernel Gateway — routes to the right ProcessProxy per request
# ------------------------------------------------------------------
class KernelGateway:
    def __init__(self):
        self.backends: dict[str, ProcessProxy] = {
            "yarn-large": YarnProcessProxy(),
            "k8s-small": KubernetesProcessProxy(),
            "vertex-gpu": VertexAIProcessProxy(),
            "ray-distributed": RayProcessProxy(),
        }

    def start_session(self, user_id: str, auth_token: str, backend_choice: str) -> str:
        """
        The data scientist picks a BACKEND CHOICE (e.g. from a UI
        dropdown) — the Kernel Gateway routes to the corresponding
        ProcessProxy, without the notebook UI itself needing to know
        anything about YARN/K8s/Vertex/Ray-specific launch mechanics.
        """
        proxy = self.backends.get(backend_choice)
        if proxy is None:
            raise ValueError(f"Unknown backend: {backend_choice}")
        return proxy.launch_kernel(user_id, auth_token, backend_choice)


# ------------------------------------------------------------------
# 3. Token propagation and refresh for long-lived kernel sessions
# ------------------------------------------------------------------
@dataclass
class AuthToken:
    value: str
    issued_at: datetime
    ttl: timedelta

    @property
    def expires_at(self) -> datetime:
        return self.issued_at + self.ttl

    def is_near_expiry(self, now: datetime, buffer: timedelta = timedelta(minutes=5)) -> bool:
        return now >= (self.expires_at - buffer)


class TokenRefresher:
    """
    Runs ALONGSIDE a long-lived kernel session, proactively renewing the
    auth token BEFORE it expires — an 8-hour training job launched with
    a 1-hour token would fail partway through without this mechanism.
    """

    def __init__(self, initial_token: AuthToken, refresh_fn):
        self.current_token = initial_token
        self.refresh_fn = refresh_fn   # calls the real OAuth2 refresh endpoint

    def get_valid_token(self, now: datetime) -> AuthToken:
        if self.current_token.is_near_expiry(now):
            print(f"  [TokenRefresher] token nearing expiry at {now} — refreshing")
            new_value = self.refresh_fn(self.current_token.value)
            self.current_token = AuthToken(new_value, now, self.current_token.ttl)
        return self.current_token


def fake_refresh_endpoint(old_token: str) -> str:
    return f"refreshed-{old_token}"


if __name__ == "__main__":
    gateway = KernelGateway()

    print("Launching a quick exploratory kernel on Kubernetes:")
    gateway.start_session("data_scientist_1", "auth-token-abc", "k8s-small")

    print("\nLaunching a large overnight job on YARN:")
    kernel_id = gateway.start_session("data_scientist_1", "auth-token-abc", "yarn-large")
    print(f"  kernel_id: {kernel_id}")

    print("\n--- Token refresh over a long-running session ---")
    token = AuthToken("auth-token-abc", issued_at=datetime(2026, 1, 1, 0, 0), ttl=timedelta(hours=1))
    refresher = TokenRefresher(token, fake_refresh_endpoint)

    for hours_elapsed in [0, 0.5, 0.95, 1.9, 2.95]:
        now = datetime(2026, 1, 1, 0, 0) + timedelta(hours=hours_elapsed)
        valid_token = refresher.get_valid_token(now)
        print(f"  t+{hours_elapsed}h: using token '{valid_token.value}'")

"""
PRODUCTION CONTEXT EXAMPLE:
A platform serving 1,500+ monthly active data scientists exposes exactly
this pattern: one notebook UI, a resource-profile dropdown mapping to
YARN/Kubernetes/Vertex/Ray ProcessProxies under the hood, and a
TokenRefresher keeping each session's platform-API access valid for the
full duration of whatever job the data scientist launches — from a
30-second exploratory query to a 10-hour distributed feature-engineering
run — without the data scientist ever needing to think about which
specific infrastructure API they're actually talking to, or worry about
their session's authentication silently expiring partway through a long job.
"""
