# ============================================================
# L04: Policy as Code — Open Policy Agent (OPA) and Rego
# ============================================================
# WHAT: Expressing authorization/compliance rules ("no pod may run as root",
#       "only approved images may deploy") as testable, version-controlled
#       code instead of tribal-knowledge PR review checklists.
# WHY (PRODUCTION): Manual review doesn't scale and is inconsistent. OPA lets
#       you enforce the same policy automatically at admission time (K8s),
#       in CI (Terraform/Dockerfile linting), and at the API layer
#       (authorization decisions) — one policy language, many enforcement
#       points.
# LEVEL: Senior backend / platform / security engineer
# ============================================================

"""
CONCEPT OVERVIEW:
OPA is a general-purpose policy engine. You give it two inputs — a `data`
document (context: who's asking, what resource, what environment) and a
`query` (the request under evaluation) — and it evaluates a Rego policy to
produce a decision (allow/deny, or a structured result).

Rego is a declarative, Datalog-derived language. Rules are NOT imperative
functions; they're logical statements that are true or false given the input.
OPA finds an assignment satisfying all rule bodies.

PRODUCTION USE CASE:
Gatekeeper (OPA running as a Kubernetes admission webhook) rejects any Pod
spec that doesn't set `resources.limits`, runs as root, or pulls from an
unapproved registry — BEFORE the pod is scheduled, not after it's already
causing a noisy-neighbor incident. The same Rego policy library also runs in
CI via Conftest against Terraform plans, catching a wide-open security group
before it's ever applied.

COMMON MISTAKES:
- Writing Rego like an imperative language (nested if/else) instead of
  independent rules that each evaluate to true/false — leads to confusing,
  unmaintainable policies.
- Deploying Gatekeeper in `deny` mode without a `dryrun`/audit period first —
  it will block legitimate deploys the first day if existing manifests
  violate a new policy.
- Not unit-testing Rego policies — a typo in a rule can silently allow
  everything (fail open) instead of denying everything.
"""

import textwrap

# ------------------------------------------------------------------
# 1. Rego fundamentals
# ------------------------------------------------------------------
REGO_BASICS = textwrap.dedent("""\
    package kubernetes.admission

    # `default` provides the fallback when no rule matches — ALWAYS set a
    # safe default (deny by default is the standard security posture).
    default allow = false

    # A rule is "true" if its body evaluates to true for some binding.
    # This is a "complete rule": allow is true if this exact condition holds.
    allow {
        input.request.kind.kind == "Pod"
        not runs_as_root
        has_resource_limits
    }

    # `runs_as_root` is itself a rule — Rego encourages small, composable,
    # independently testable predicates rather than one giant rule.
    runs_as_root {
        input.request.object.spec.securityContext.runAsNonRoot != true
    }

    has_resource_limits {
        container := input.request.object.spec.containers[_]  # iterate (the `[_]` idiom)
        container.resources.limits.cpu
        container.resources.limits.memory
    }

    # A `deny` set collects human-readable violation messages — this is the
    # pattern Gatekeeper ConstraintTemplates actually use, returning a set
    # of strings rather than a single boolean.
    deny[msg] {
        runs_as_root
        msg := "containers must not run as root (set securityContext.runAsNonRoot: true)"
    }

    deny[msg] {
        container := input.request.object.spec.containers[_]
        not container.resources.limits.cpu
        msg := sprintf("container '%v' is missing cpu limits", [container.name])
    }
""")

# ------------------------------------------------------------------
# 2. Iteration, comprehensions, built-ins
# ------------------------------------------------------------------
REGO_ITERATION = textwrap.dedent("""\
    package images

    # allowed registries — a set literal
    allowed_registries := {"registry.internal.myorg.com", "gcr.io/myorg-prod"}

    # array comprehension: collect all image refs used in the pod spec
    images_used[img] {
        img := input.request.object.spec.containers[_].image
    }

    # deny any image not from an allowed registry — string manipulation
    # built-ins (split, startswith) are core to real-world Rego policies
    deny[msg] {
        img := images_used[_]
        registry := split(img, "/")[0]
        not allowed_registries[registry]
        msg := sprintf("image '%v' is not from an approved registry", [img])
    }

    # `count` built-in — e.g. deny if more than 3 containers in one pod
    deny[msg] {
        count(input.request.object.spec.containers) > 3
        msg := "pods may not have more than 3 containers"
    }
""")

# ------------------------------------------------------------------
# 3. OPA as a Kubernetes admission webhook — Gatekeeper
# ------------------------------------------------------------------
# Gatekeeper wraps OPA in K8s CRDs: a ConstraintTemplate defines the Rego
# (parameterized), and a Constraint instantiates it with specific parameters.
GATEKEEPER_TEMPLATE = textwrap.dedent("""\
    apiVersion: templates.gatekeeper.sh/v1
    kind: ConstraintTemplate
    metadata:
      name: k8srequiredresources
    spec:
      crd:
        spec:
          names: { kind: K8sRequiredResources }
      targets:
        - target: admission.k8s.gatekeeper.sh
          rego: |
            package k8srequiredresources
            violation[{"msg": msg}] {
              container := input.review.object.spec.containers[_]
              not container.resources.limits.cpu
              msg := sprintf("container '%v' has no cpu limit", [container.name])
            }
    ---
    apiVersion: constraints.gatekeeper.sh/v1beta1
    kind: K8sRequiredResources
    metadata:
      name: require-resource-limits
    spec:
      enforcementAction: dryrun   # start in audit-only mode — logs violations
                                   # without blocking, so you can gauge blast
                                   # radius before flipping to "deny"
      match:
        kinds: [{ apiGroups: [""], kinds: ["Pod"] }]
        excludedNamespaces: ["kube-system"]
""")

# ------------------------------------------------------------------
# 4. Testing Rego policies
# ------------------------------------------------------------------
REGO_TESTS = textwrap.dedent("""\
    # kubernetes_admission_test.rego
    package kubernetes.admission

    test_denies_root_container {
        deny["containers must not run as root (set securityContext.runAsNonRoot: true)"] with input as {
            "request": {
                "kind": {"kind": "Pod"},
                "object": {"spec": {
                    "securityContext": {"runAsNonRoot": false},
                    "containers": [{"name": "app"}],
                }},
            }
        }
    }

    test_allows_compliant_pod {
        allow with input as {
            "request": {
                "kind": {"kind": "Pod"},
                "object": {"spec": {
                    "securityContext": {"runAsNonRoot": true},
                    "containers": [{
                        "name": "app",
                        "resources": {"limits": {"cpu": "500m", "memory": "256Mi"}},
                    }],
                }},
            }
        }
    }

    # Run with: opa test . -v
""")

# ------------------------------------------------------------------
# 5. Conftest — CI-time policy checks (not just admission-time)
# ------------------------------------------------------------------
CONFTEST_CI_USAGE = textwrap.dedent("""\
    # Same Rego policies, evaluated against Terraform PLAN JSON in CI —
    # catches violations before `terraform apply`, not just before K8s
    # admits a pod. This is "shift left" policy enforcement.

    terraform show -json tfplan > plan.json
    conftest test plan.json --policy policy/terraform/

    # policy/terraform/s3.rego
    package terraform.s3
    deny[msg] {
        resource := input.resource_changes[_]
        resource.type == "aws_s3_bucket"
        resource.change.after.acl == "public-read"
        msg := sprintf("S3 bucket '%v' must not be publicly readable", [resource.address])
    }
""")

# ------------------------------------------------------------------
# 6. Bundle distribution and decision logs
# ------------------------------------------------------------------
BUNDLES_AND_LOGS = textwrap.dedent("""\
    # OPA can pull policy bundles (a tarball of .rego + data.json files)
    # from a remote server on a poll interval, so policy updates roll out
    # without redeploying OPA itself:

    services:
      policy-registry:
        url: https://opa-bundles.internal.myorg.com
    bundles:
      authz:
        service: policy-registry
        resource: bundles/authz.tar.gz
        polling: { min_delay_seconds: 60, max_delay_seconds: 120 }

    # decision_logs stream every allow/deny decision (with input + result)
    # to an external sink — critical for security audits ("who was denied
    # access to what, when").
    decision_logs:
      console: true
""")

if __name__ == "__main__":
    print(REGO_BASICS[:300], "...")

"""
TRADING/PRODUCTION CONTEXT EXAMPLE:
A quant platform's Kubernetes cluster runs both research notebooks and
production trading services. A Gatekeeper policy denies any pod in the
`production-trading` namespace from being scheduled without a signed image
digest (not a mutable tag) and CPU/memory limits — preventing an
accidentally-unbounded backtest job from starving the live order-execution
pod on the same node. The same Rego library runs via Conftest in the
Terraform CI pipeline, blocking a security group change that would have
opened the market-data VPC to 0.0.0.0/0.
"""
