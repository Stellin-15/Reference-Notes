#!/usr/bin/env bash
# =============================================================================
# CI/CD TOOLS CHEATSHEET — In-Depth Reference
# GitHub Actions, GitLab CI, Jenkins, CircleCI, ArgoCD, and Terraform —
# the CI/CD + IaC stack most in demand in current job postings.
# Read top-to-bottom; run individually.
# =============================================================================


# =============================================================================
# 1. GITHUB ACTIONS
# =============================================================================

cat <<'EOF'
# --- .github/workflows/ci.yml ---
name: CI
on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:            # Manual trigger button in the UI
  schedule:
    - cron: "0 3 * * *"            # Nightly at 03:00 UTC

permissions:
  contents: read
  id-token: write                  # Required for OIDC (keyless cloud auth)

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true            # Cancel superseded runs on the same branch

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node: [18, 20, 22]
      fail-fast: false
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node }}
          cache: "npm"
      - run: npm ci
      - run: npm test
      - name: Upload coverage
        uses: actions/upload-artifact@v4
        with:
          name: coverage-${{ matrix.node }}
          path: coverage/

  deploy:
    needs: test                      # Wait for the test job to succeed
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment: production           # Enables required-reviewer gates
    steps:
      - uses: actions/checkout@v4
      - name: Configure AWS creds via OIDC (no long-lived secrets)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::123456789012:role/gha-deploy
          aws-region: us-east-1
      - run: ./deploy.sh
EOF

# Secrets & variables:
#   Settings -> Secrets and variables -> Actions
#   Reference: ${{ secrets.MY_SECRET }}  /  ${{ vars.MY_VAR }}
#   Environment-scoped secrets require an `environment:` on the job and
#   support required reviewers / wait timers for protected deploys.

# Reusable workflows and composite actions:
#   uses: ./.github/workflows/reusable.yml with: { ... }   (workflow_call trigger)
#   uses: ./.github/actions/my-composite-action                (action.yml, composite runs steps)

# gh CLI companions for Actions (see Git & GitHub Notes/CHEATSHEET.sh for full gh reference):
#   gh workflow list / gh run list / gh run watch / gh run view <id> --log

# Local testing without pushing:
#   act -j test                     # Run the "test" job locally via `act` (Docker-based emulator)


# =============================================================================
# 2. GITLAB CI/CD
# =============================================================================

cat <<'EOF'
# --- .gitlab-ci.yml ---
stages:
  - build
  - test
  - deploy

variables:
  DOCKER_DRIVER: overlay2

default:
  image: node:20-alpine
  before_script:
    - npm ci

build:
  stage: build
  script:
    - npm run build
  artifacts:
    paths:
      - dist/
    expire_in: 1 week

test:
  stage: test
  script:
    - npm test
  coverage: '/Coverage: \d+\.\d+%/'
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == "main"'

deploy_prod:
  stage: deploy
  script:
    - ./deploy.sh
  environment:
    name: production
    url: https://example.com
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual                    # Requires a human click in the UI
EOF

# Runners:
gitlab-runner register                  # Register a self-hosted runner interactively
gitlab-runner run                          # Start the runner daemon
gitlab-runner exec docker test               # Run a job locally for debugging

# CI/CD variables: Settings -> CI/CD -> Variables (mask + protect for secrets)
# Predefined vars: $CI_COMMIT_SHA, $CI_PROJECT_DIR, $CI_PIPELINE_SOURCE, $CI_MERGE_REQUEST_IID
# Parent-child pipelines: `trigger: include: local: child.yml` — split large pipelines
# DAG-based ordering (skip strict stages): `needs: [job_name]` on any job


# =============================================================================
# 3. JENKINS
# =============================================================================

cat <<'EOF'
// --- Jenkinsfile (declarative pipeline) ---
pipeline {
    agent { label 'linux' }

    environment {
        NODE_ENV = 'production'
        AWS_CREDS = credentials('aws-deploy-creds')   // Injected from Jenkins Credentials store
    }

    options {
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
    }

    stages {
        stage('Checkout') {
            steps { checkout scm }
        }
        stage('Build') {
            steps { sh 'npm ci && npm run build' }
        }
        stage('Test') {
            steps { sh 'npm test' }
            post {
                always {
                    junit 'reports/**/*.xml'
                }
            }
        }
        stage('Deploy') {
            when { branch 'main' }
            steps { sh './deploy.sh' }
        }
    }

    post {
        failure {
            slackSend channel: '#builds', message: "Build ${env.BUILD_NUMBER} failed"
        }
    }
}
EOF

# CLI / operational commands:
#   java -jar jenkins-cli.jar -s http://localhost:8080/ build my-job    # Trigger a build
#   java -jar jenkins-cli.jar -s http://localhost:8080/ list-jobs          # List jobs
#   Blue Ocean UI            -> modern visual pipeline editor/viewer
#   Shared Libraries           -> vars/ + src/ Groovy code reused across many Jenkinsfiles
#   Agents/Nodes                 -> Manage Jenkins -> Nodes (static or dynamic via Kubernetes plugin)
#   Kubernetes plugin              -> spins ephemeral pod agents per build (`agent { kubernetes { ... } }`)

# Declarative vs Scripted pipeline:
#   Declarative -> structured, opinionated, easier to read/lint (recommended default)
#   Scripted    -> full Groovy control flow, used for complex/dynamic logic


# =============================================================================
# 4. CIRCLECI
# =============================================================================

cat <<'EOF'
# --- .circleci/config.yml ---
version: 2.1

orbs:
  node: circleci/node@5.2.0

jobs:
  build-and-test:
    docker:
      - image: cimg/node:20.11
    steps:
      - checkout
      - node/install-packages:
          cache-path: ~/project/node_modules
      - run: npm test
      - store_test_results:
          path: test-results
      - store_artifacts:
          path: coverage

  deploy:
    docker:
      - image: cimg/base:current
    steps:
      - checkout
      - run: ./deploy.sh

workflows:
  build-test-deploy:
    jobs:
      - build-and-test
      - deploy:
          requires: [build-and-test]
          filters:
            branches:
              only: main
EOF

circleci config validate                    # Lint config.yml locally
circleci local execute --job build-and-test   # Run a job locally (needs Docker)
circleci orb list                              # Browse reusable orbs

# Contexts (org-level secret groups) referenced via: context: [my-context]
# Parallelism: `parallelism: 4` + `circleci tests split` to shard a test suite


# =============================================================================
# 5. AZURE DEVOPS PIPELINES  (common in enterprise/.NET shops)
# =============================================================================

cat <<'EOF'
# --- azure-pipelines.yml ---
trigger:
  branches:
    include: [main]

pool:
  vmImage: 'ubuntu-latest'

stages:
  - stage: Build
    jobs:
      - job: BuildAndTest
        steps:
          - task: NodeTool@0
            inputs: { versionSpec: '20.x' }
          - script: npm ci && npm test
            displayName: 'Install and test'

  - stage: Deploy
    dependsOn: Build
    condition: succeeded()
    jobs:
      - deployment: ProdDeploy
        environment: production
        strategy:
          runOnce:
            deploy:
              steps:
                - script: ./deploy.sh
EOF


# =============================================================================
# 6. ARGOCD — GITOPS CONTINUOUS DELIVERY
# =============================================================================

argocd login argocd.example.com               # Authenticate CLI
argocd app create my-app \
  --repo https://github.com/org/repo.git \
  --path k8s/overlays/production \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace production \
  --sync-policy automated                        # Auto-sync on Git changes

argocd app list                                 # List managed apps
argocd app get my-app                             # Sync/health status
argocd app diff my-app                              # Live cluster state vs Git
argocd app sync my-app                                # Force a sync now
argocd app rollback my-app 5                            # Roll back to history ID 5
argocd app set my-app --sync-policy automated --self-heal --auto-prune

cat <<'EOF'
# --- Application manifest (declarative alternative to the CLI above) ---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/repo.git
    targetRevision: main
    path: k8s/overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: production
  syncPolicy:
    automated:
      prune: true          # Delete resources removed from Git
      selfHeal: true          # Revert manual cluster drift back to Git state
EOF

# Core GitOps principle: Git is the single source of truth. ArgoCD continuously
# reconciles live cluster state to match the target Git ref — deploys happen
# via a merged PR, not a `kubectl apply` from a laptop.
# ApplicationSets generate many Applications from one template (multi-cluster/multi-tenant fan-out).


# =============================================================================
# 7. TERRAFORM — INFRASTRUCTURE AS CODE (near-universal alongside CI/CD)
# =============================================================================

terraform init                          # Download providers + initialize backend
terraform fmt -recursive                   # Auto-format all .tf files
terraform validate                            # Check syntax/config validity (no API calls)
terraform plan                                   # Show proposed changes (dry run)
terraform plan -out=tfplan                          # Save the plan for a later apply
terraform apply                                        # Apply changes (prompts for confirmation)
terraform apply tfplan                                    # Apply a previously saved plan
terraform apply -auto-approve                                # Skip confirmation (use carefully, e.g. in CI)
terraform destroy                                              # Tear down all managed resources

terraform state list                        # List resources tracked in state
terraform state show aws_instance.web          # Show one resource's current attributes
terraform state rm aws_instance.web              # Remove a resource from state (doesn't destroy it)
terraform state mv aws_instance.a aws_instance.b   # Rename/move a resource in state
terraform import aws_instance.web i-0123456789     # Bring an existing resource under management

terraform workspace list                      # List workspaces (parallel state per env)
terraform workspace new staging                 # Create + switch to a new workspace
terraform workspace select production              # Switch workspace

terraform output                             # Show output values
terraform show                                 # Human-readable dump of current state
terraform graph | dot -Tpng > graph.png          # Visualize resource dependency graph

cat <<'EOF'
# --- main.tf ---
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  backend "s3" {
    bucket = "my-tf-state"
    key    = "prod/terraform.tfstate"
    region = "us-east-1"
    dynamodb_table = "tf-lock"      # State locking to prevent concurrent applies
  }
}

variable "instance_type" {
  type    = string
  default = "t3.micro"
}

resource "aws_instance" "web" {
  ami           = "ami-0123456789abcdef0"
  instance_type = var.instance_type
  tags = { Name = "web-server" }
}

output "instance_ip" {
  value = aws_instance.web.public_ip
}
EOF

# CI/CD + Terraform pattern: `terraform plan` on every PR (posted as a comment
# for review), `terraform apply` only on merge to main, remote state with
# locking so concurrent pipeline runs can't corrupt state.


# =============================================================================
# 8. CROSS-TOOL CONCEPTS THAT SHOW UP IN EVERY INTERVIEW
# =============================================================================

# - Pipeline as code: the pipeline definition lives in the repo, versioned with the app.
# - Caching: dependency caches (npm/pip/maven) cut build time; key caches on lockfile hash.
# - Matrix builds: run the same job across multiple versions/OSes in parallel.
# - Artifacts: pass build outputs between jobs/stages without rebuilding.
# - Secrets management: never in plaintext YAML — use the platform's secret store,
#   or short-lived OIDC federation to cloud providers instead of static keys.
# - Environments & approvals: gate production deploys behind manual approval / required reviewers.
# - Trunk-based development vs GitFlow: most modern CI/CD assumes short-lived branches,
#   frequent merges to main, and feature flags over long-lived release branches.
# - Deployment strategies: rolling, blue/green, canary — see CICD Notes L05 for the full breakdown.
# - GitOps vs push-based CD: ArgoCD/Flux (pull, cluster reconciles to Git) vs a
#   pipeline running `kubectl apply`/`helm upgrade` directly (push).
