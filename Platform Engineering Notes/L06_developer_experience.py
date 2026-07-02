# ============================================================
# L06: Developer Experience (DevEx) Metrics and Tooling
# ============================================================
# WHAT: Measuring and improving how fast/frictionlessly engineers can go
#       from idea to running code in production.
# WHY (PRODUCTION): Platform investments are hard to justify without
#       numbers. DORA metrics turn "the pipeline feels slow" into "lead
#       time for changes is 4 hours, industry elite is under 1 hour" —
#       an actionable, trackable target.
# LEVEL: Senior backend / platform engineer, engineering manager
# ============================================================

"""
CONCEPT OVERVIEW:
DevEx tooling exists to remove toil between "I wrote code" and "it's running
correctly, observably, in production". This spans: local dev loop speed
(can I test a K8s change without a 10-minute image build?), ephemeral
environments (can reviewers click a live preview link instead of reading a
diff?), and standardized CI/CD (does every service reinvent its pipeline?).

DORA (DevOps Research and Assessment) metrics are the industry-standard way
to quantify delivery performance, validated across years of the State of
DevOps Report research.

PRODUCTION USE CASE:
A platform team notices lead-time-for-changes has crept from 2 hours to 18
hours over 6 months. Drilling into the DORA data shows the bottleneck is
CI queue time, not test duration — they add a second self-hosted runner
pool and reclaim 12 of those 18 hours, backed by before/after metrics in the
same dashboard that flagged the regression.

COMMON MISTAKES:
- Measuring deployment frequency per-repo instead of per-service, hiding a
  monorepo's actual release cadence.
- Standardizing CI templates so rigidly that teams can't add
  service-specific steps, causing shadow pipelines to reappear.
- Building an internal CLI that wraps kubectl/terraform but doesn't stay in
  sync with upstream flags, becoming a maintenance burden itself.
"""

import textwrap
from dataclasses import dataclass
from datetime import datetime, timedelta

# ------------------------------------------------------------------
# 1. DORA metrics — definitions and how to compute them
# ------------------------------------------------------------------
DORA_METRICS = {
    "deployment_frequency": "How often code is deployed to production. "
        "Elite: multiple times/day. Computed from CI/CD deploy events, "
        "not commits (a commit isn't a deploy).",
    "lead_time_for_changes": "Time from commit merged to main -> running in "
        "production. Elite: < 1 hour. Requires correlating a commit SHA "
        "across CI (build time) and CD (deploy time) events.",
    "mean_time_to_restore": "Time from an incident starting to it being "
        "resolved. Elite: < 1 hour. Requires incident start/end timestamps "
        "from your incident management tool (PagerDuty, Opsgenie).",
    "change_failure_rate": "% of deployments causing a production incident "
        "or requiring rollback. Elite: 0-15%. Needs deploys tagged with "
        "outcome (rolled back / caused incident / clean).",
}


@dataclass
class DeployEvent:
    service: str
    commit_sha: str
    committed_at: datetime
    deployed_at: datetime
    caused_incident: bool


def compute_lead_time(events: list[DeployEvent]) -> timedelta:
    """Median lead time — commit merge to production deploy."""
    deltas = sorted(e.deployed_at - e.committed_at for e in events)
    return deltas[len(deltas) // 2]  # median is robust to one slow outlier deploy


def compute_change_failure_rate(events: list[DeployEvent]) -> float:
    if not events:
        return 0.0
    failures = sum(1 for e in events if e.caused_incident)
    return failures / len(events)


# ------------------------------------------------------------------
# 2. Internal CLI — a Typer-based wrapper over platform primitives
# ------------------------------------------------------------------
# The point of an internal CLI is NOT to reimplement kubectl/terraform, but
# to encode multi-step workflows (provision env -> wait for ready -> print
# URL) that would otherwise be a wiki page full of copy-pasted commands.
INTERNAL_CLI_SKETCH = textwrap.dedent("""\
    # platform_cli/main.py  (conceptual, using Typer)
    import typer, subprocess

    app = typer.Typer()

    @app.command()
    def provision_env(service: str, ttl_hours: int = 24):
        '''Provision a short-lived preview environment for a service.'''
        # 1. Create an isolated namespace
        subprocess.run(["kubectl", "create", "namespace", f"preview-{service}"])
        # 2. Apply the service's Helm chart with preview-sized resource limits
        subprocess.run(["helm", "install", service, f"./charts/{service}",
                         "-n", f"preview-{service}", "--set", "resources.preview=true"])
        # 3. Register a TTL annotation a cleanup CronJob will later garbage-collect
        subprocess.run(["kubectl", "annotate", "namespace", f"preview-{service}",
                         f"ttl-hours={ttl_hours}"])
        typer.echo(f"Preview ready: https://{service}-preview.internal.myorg.com")

    @app.command()
    def get_secret(path: str):
        '''Fetch a Vault secret, wrapping the API so devs never touch raw curl.'''
        subprocess.run(["vault", "read", "-format=json", path])

    if __name__ == "__main__":
        app()
""")

# ------------------------------------------------------------------
# 3. Reusable CI/CD workflow templates (GitHub Actions)
# ------------------------------------------------------------------
REUSABLE_WORKFLOW = textwrap.dedent("""\
    # .github/workflows/standard-python-service.yml (shared, org-wide)
    on:
      workflow_call:
        inputs:
          service_name: { required: true, type: string }
    jobs:
      build-test-deploy:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4
          - run: pip install -r requirements.txt
          - run: pytest --cov
          - run: docker build -t ${{ inputs.service_name }} .
          - run: ./deploy.sh ${{ inputs.service_name }}

    # --- consumer repo, one line instead of 40 ---
    # .github/workflows/ci.yml
    jobs:
      call-standard:
        uses: myorg/.github/.github/workflows/standard-python-service.yml@v3
        with:
          service_name: billing-service
""")

# ------------------------------------------------------------------
# 4. Tilt — fast local Kubernetes development loop
# ------------------------------------------------------------------
TILTFILE_EXAMPLE = textwrap.dedent("""\
    # Tiltfile — watches source, rebuilds only what changed, live-syncs into
    # a running pod instead of a full image rebuild+redeploy cycle.
    docker_build(
        'billing-service',
        '.',
        live_update=[
            sync('./app', '/app'),               # rsync changed files into the container
            run('pip install -r requirements.txt', trigger=['./requirements.txt']),
        ],
    )
    k8s_yaml('k8s/billing-service.yaml')
    k8s_resource('billing-service', port_forwards=8000)
    # `tilt up` gives a live UI: edit a .py file, see it running in-cluster
    # in ~2 seconds instead of a 90-second image rebuild.
""")

# ------------------------------------------------------------------
# 5. Ephemeral / preview environments
# ------------------------------------------------------------------
PREVIEW_ENV_PATTERN = textwrap.dedent("""\
    # On PR open: CI creates a namespace `preview-pr-1234`, deploys the PR's
    # branch, comments the live URL on the PR. On PR close/merge: a CronJob
    # (or the same workflow's `on: pull_request: types: [closed]` step)
    # deletes the namespace.
    #
    # Key design point: preview envs share a DOWNSTREAM staging database
    # (read-only or namespaced schema) rather than provisioning a fresh DB
    # per PR — full DB provisioning per preview is usually too slow/costly
    # to be worth the isolation.
""")

# ------------------------------------------------------------------
# 6. devcontainer.json — standardized local dev environment
# ------------------------------------------------------------------
DEVCONTAINER_JSON = textwrap.dedent("""\
    {
      "name": "billing-service",
      "image": "mcr.microsoft.com/devcontainers/python:3.12",
      "features": {
        "ghcr.io/devcontainers/features/docker-in-docker:2": {}
      },
      "postCreateCommand": "pip install -r requirements-dev.txt && pre-commit install",
      "forwardPorts": [8000, 5432],
      "customizations": {
        "vscode": { "extensions": ["ms-python.python", "charliermarsh.ruff"] }
      }
    }
    // A new hire clones the repo, opens it in VS Code, clicks "Reopen in
    // Container" — and has the exact same environment as everyone else on
    // the team, with zero "works on my machine" debugging.
""")

if __name__ == "__main__":
    events = [
        DeployEvent("billing", "abc123", datetime(2026, 1, 1, 9),
                     datetime(2026, 1, 1, 11), caused_incident=False),
        DeployEvent("billing", "def456", datetime(2026, 1, 2, 9),
                     datetime(2026, 1, 2, 9, 30), caused_incident=True),
    ]
    print("Median lead time:", compute_lead_time(events))
    print("Change failure rate:", compute_change_failure_rate(events))

"""
TRADING/PRODUCTION CONTEXT EXAMPLE:
A quant research team's strategy backtests take 90 seconds to containerize
and redeploy to a K8s test cluster on every code change — too slow for an
iterative research loop. Switching to Tilt's live_update sync cuts that to
~2 seconds (no rebuild, just file sync + in-place restart), turning
"edit-run-observe" into a genuinely fast feedback loop instead of a
context-switch-inducing wait.
"""
