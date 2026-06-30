#!/usr/bin/env bash
# ============================================================
# L01: CI/CD Foundations — Concepts, Philosophy, and Metrics
# ============================================================
# WHAT: CI/CD is an engineering practice and toolchain that
#       automates the journey from code commit to production.
#       CI = Continuous Integration: developers merge code
#       frequently (multiple times/day), triggering automated
#       build and test pipelines. CD = Continuous Delivery:
#       every merged commit is automatically verified and left
#       in a releasable state. Continuous Deployment goes one
#       step further — verified commits are deployed to
#       production automatically, without human approval.
#
# WHY:  Manual integration is painful. Long-lived branches
#       accumulate hidden conflicts. Large releases carry
#       large risk. CI/CD compresses the feedback loop:
#       a broken test fires in minutes, not after a two-week
#       integration sprint. Smaller, frequent releases mean
#       smaller blast radius when something goes wrong.
#
# LEVEL: Foundations
# ============================================================
# CONCEPT OVERVIEW:
#   - Continuous Integration (CI)
#   - Continuous Delivery vs Continuous Deployment
#   - Core pipeline stages
#   - Branching strategies (Trunk-based, GitFlow, GitHub Flow)
#   - Shift-Left testing
#   - DORA metrics
#
# PRODUCTION USE CASE:
#   A Python microservice team deploys 15 times per day.
#   Every PR triggers lint + unit + integration tests in < 5
#   minutes. Merging to main auto-deploys to staging; a human
#   clicks "Approve" for production. This is Continuous
#   Delivery. With full Continuous Deployment the approval
#   step is removed — tests ARE the gate.
#
# COMMON MISTAKES:
#   - Treating CI as "just running tests in the cloud"
#     (it's a cultural practice, not just a tool)
#   - Long-lived feature branches that defeat the purpose of CI
#   - Flaky tests that erode trust and get skipped
#   - Skipping the "verify after deploy" stage
#   - Storing secrets in the repository
# ============================================================

set -euo pipefail

echo "=== CI/CD Concepts Reference ==="
echo "This file is a runnable reference document."
echo "Each section prints explanations and examples."
echo ""

# ============================================================
# SECTION 1: THE THREE TERMS DEFINED
# ============================================================

explain_cicd_terms() {
    cat <<'EOF'

┌─────────────────────────────────────────────────────────────┐
│                   CI/CD SPECTRUM                            │
├──────────────────┬──────────────────┬───────────────────────┤
│  Continuous      │  Continuous      │  Continuous           │
│  Integration     │  Delivery        │  Deployment           │
├──────────────────┼──────────────────┼───────────────────────┤
│ Merge code often │ Always in a      │ Every merge goes to   │
│ Auto build+test  │ releasable state │ production auto       │
│ Human deploys    │ Human triggers   │ No human in the loop  │
│ when ready       │ production push  │ Tests ARE the gate    │
└──────────────────┴──────────────────┴───────────────────────┘

Continuous Integration does NOT mean "deploy continuously."
It means INTEGRATE (merge) continuously so conflicts surface fast.

EOF
}

# ============================================================
# SECTION 2: CORE PIPELINE STAGES
# ============================================================
# Every mature CI/CD pipeline covers these stages in order.
# Stages are sequential because each gates the next:
# there is no point scanning an image that fails to build.
# ============================================================

explain_pipeline_stages() {
    cat <<'EOF'

CORE PIPELINE STAGES
────────────────────
1. LINT / FORMAT CHECK
   Tool examples: flake8, ruff, black --check, eslint
   Goal: enforce code style before review. Fast (< 30s).
   Fail fast: a style error blocks all downstream stages.

2. STATIC ANALYSIS / TYPE CHECK
   Tool examples: mypy, pyright, pylint
   Goal: catch type errors without running the code.
   Runs in < 2 minutes on most Python projects.

3. UNIT TESTS
   Tool examples: pytest, jest, go test
   Goal: verify individual functions/classes in isolation.
   Should be < 5 minutes. Coverage threshold enforced (>80%).

4. INTEGRATION TESTS
   Tool examples: pytest with real DB, testcontainers
   Goal: verify components work together (service + DB).
   Slower (5–15 min). Uses Docker service containers.

5. BUILD
   Tool examples: docker build, go build, pip wheel
   Goal: produce the deployable artifact (image, binary, package).
   Layer caching reduces this to < 2 min for unchanged layers.

6. SECURITY SCAN
   Tool examples: trivy, snyk, bandit, semgrep
   Goal: block known CVEs and misconfigurations before push.
   Treat HIGH/CRITICAL findings as build failures.

7. PUSH TO REGISTRY
   Tool examples: docker push, ECR, GCR, GHCR
   Tag strategy: <sha>-<branch>, semver on tags, "latest" on main.

8. DEPLOY
   Tool examples: kubectl, helm upgrade, argocd sync
   Strategies: rolling, canary, blue/green (see L05).

9. VERIFY (SMOKE TESTS)
   Tool examples: curl health endpoint, k6, playwright
   Goal: confirm the deployed service responds correctly.
   Automatic rollback if verification fails.

EOF
}

# ============================================================
# SECTION 3: BRANCHING STRATEGIES
# ============================================================
# Your branching strategy determines how often developers
# integrate and how complex your pipeline needs to be.
# ============================================================

explain_branching_strategies() {
    cat <<'EOF'

BRANCHING STRATEGIES
────────────────────

TRUNK-BASED DEVELOPMENT (recommended for CI/CD)
  - Everyone commits to "main" (the trunk) daily or more
  - Short-lived feature branches: < 1-2 days
  - Feature flags hide incomplete work from users
  - Enables true Continuous Integration
  - Used by: Google, Facebook, Netflix

  main ─────────────────────────────────────────────►
          ↑    ↑    ↑    ↑    ↑
        feat feat feat feat feat (all < 2 days old)

GITHUB FLOW (pragmatic for most teams)
  - main is always deployable
  - Feature branches for new work
  - PR → review → merge → deploy
  - No release branches
  - Branches can live longer (but should be short)

  main ──────────────────────────────────────────────►
         \──feature/auth──/  \──feature/api──/

GITFLOW (avoid for CI/CD — creates integration debt)
  - Develop, feature, release, hotfix, main branches
  - Long release cycles accumulate risk
  - Merges become complex and error-prone
  - Use only if you have fixed release windows (e.g. app stores)

  main ────────────────────────────────────►
  develop ──────────────────────────────────►
           \──feature──/  \──feature──/
                     \──release──/

RECOMMENDATION: Trunk-based for teams with good test coverage.
GitHub Flow for teams building towards that.
Avoid GitFlow unless regulatory or release constraints force it.

EOF
}

# ============================================================
# SECTION 4: SHIFT-LEFT TESTING
# ============================================================
# "Shift left" means moving quality checks earlier in the
# development process — before code is even committed.
# The earlier you catch a bug, the cheaper it is to fix.
# ============================================================

explain_shift_left() {
    cat <<'EOF'

SHIFT-LEFT TESTING
──────────────────
Cost to fix a bug:
  Developer's machine:  $1
  CI pipeline:          $10
  Staging:              $100
  Production:           $1,000+

Layers of shift-left (earliest to latest):
  1. IDE linting (ruff, mypy in VSCode/PyCharm) — instant
  2. Pre-commit hooks (run lint + unit tests before git commit)
  3. CI on PR open (full pipeline before code is reviewed)
  4. CI on merge to main (gate for deployment)
  5. Staging verification (smoke + contract tests)
  6. Production monitoring (SLO alerts = shift-right safety net)

Pre-commit hook example (stored in .pre-commit-config.yaml):
  - Run ruff (linting)
  - Run mypy (type checking)
  - Run unit tests (pytest -x --fast)
  - Scan for secrets (gitleaks)
  Developers can't commit code that fails these checks locally.

EOF
}

# ============================================================
# SECTION 5: DORA METRICS
# ============================================================
# DORA (DevOps Research and Assessment) identified four key
# metrics that distinguish elite software delivery performers.
# Use these to measure your CI/CD program's health — not
# pipeline duration alone.
# ============================================================

explain_dora_metrics() {
    cat <<'EOF'

DORA METRICS (measure these to prove CI/CD value)
──────────────────────────────────────────────────

1. DEPLOYMENT FREQUENCY
   What: How often do you deploy to production?
   Elite: Multiple times per day
   High:  Once per day to once per week
   Med:   Once per week to once per month
   Low:   Once per month or less

2. LEAD TIME FOR CHANGES
   What: Time from code commit to running in production
   Elite: < 1 hour
   High:  1 day to 1 week
   Med:   1 week to 1 month
   Low:   > 1 month

3. MEAN TIME TO RESTORE (MTTR)
   What: How long to recover from a production incident?
   Elite: < 1 hour
   High:  < 1 day
   Med:   1 day to 1 week
   Low:   > 1 week

4. CHANGE FAILURE RATE
   What: % of deployments that cause a production incident
   Elite: 0–15%
   High:  16–30%
   Med:   16–30% (same range, worse outcomes)
   Low:   > 30%

How to measure in your pipeline:
  - Deployment frequency: count deploy job runs per day
  - Lead time: timestamp(commit) → timestamp(production deploy)
  - MTTR: incident start → deploy of fix
  - Change failure rate: (rollbacks + incidents) / total deploys

Instrument your pipeline to emit these as metrics to
Datadog / CloudWatch / Prometheus. Report them in team retros.

EOF
}

# ============================================================
# SECTION 6: PIPELINE AS CODE PRINCIPLES
# ============================================================

explain_pipeline_as_code() {
    cat <<'EOF'

PIPELINE AS CODE PRINCIPLES
────────────────────────────
1. Version-controlled: pipeline definitions live in the repo
   alongside the code they test. Changes are reviewed like code.

2. Reproducible: the same commit always produces the same result.
   Pin action versions (@v4, not @main). Pin Docker image digests.
   Pin tool versions (ruff==0.4.0, not ruff>=0.4.0).

3. Fast feedback: optimize for P95 pipeline duration < 10 min.
   Parallelise independent jobs. Cache aggressively.
   Fail fast: run cheapest checks first.

4. Idempotent: running the pipeline twice for the same commit
   should produce the same outcome. Avoid side effects in tests.

5. Secure by default: no secrets in code or logs. Use OIDC
   instead of long-lived credentials. Least privilege IAM roles.

6. Observable: every stage emits structured logs and metrics.
   Pipeline failures send alerts. Dashboards show trends.

7. Tested: your pipeline itself is tested. Use
   act (local GitHub Actions runner) to test workflows locally
   before pushing. Validate YAML with actionlint.

EOF
}

# ============================================================
# RUN ALL EXPLANATIONS
# ============================================================

explain_cicd_terms
explain_pipeline_stages
explain_branching_strategies
explain_shift_left
explain_dora_metrics
explain_pipeline_as_code

echo ""
echo "=== End of L01: CI/CD Concepts ==="
echo "Next: L02_github_actions.yaml — GitHub Actions deep dive"
