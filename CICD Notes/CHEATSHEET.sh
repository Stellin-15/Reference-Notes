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
# 8. TEKTON — KUBERNETES-NATIVE CI/CD
# =============================================================================

# Unlike GitHub Actions/Jenkins/CircleCI (which run on their own hosted or
# self-managed runners), Tekton pipelines run entirely as native Kubernetes
# resources — every step is a container in a Pod, scheduled by the K8s
# scheduler itself. This matters for shops standardizing everything on K8s:
# no separate CI infrastructure, uses the SAME RBAC/namespaces/quotas as the
# rest of the cluster, and is the plumbing underneath higher-level tools
# like OpenShift Pipelines and some parts of Argo Workflows.

cat <<'EOF'
apiVersion: tekton.dev/v1
kind: Task
metadata: { name: run-tests }
spec:
  steps:
    - name: test
      image: node:20-alpine
      script: |
        npm ci
        npm test
---
apiVersion: tekton.dev/v1
kind: Pipeline
metadata: { name: ci-pipeline }
spec:
  tasks:
    - name: test
      taskRef: { name: run-tests }
EOF

tkn pipeline start ci-pipeline               # Trigger a PipelineRun via the tkn CLI
tkn pipelinerun logs -f                         # Follow logs of the latest run
kubectl get taskruns,pipelineruns                 # Every run is just a K8s object — inspectable with kubectl too


# =============================================================================
# 9. FLUX — THE OTHER GITOPS OPERATOR (ARGOCD'S ALTERNATIVE)
# =============================================================================

# Flux (from Weaveworks, now a CNCF graduated project) does the same core job
# as ArgoCD — reconcile a live cluster to match a Git repo — but as a set of
# lightweight controllers with no separate UI by default (GitOps purists often
# prefer it for exactly that reason: less surface area, fully kubectl-native).

flux bootstrap github --owner=myorg --repository=myrepo --path=clusters/prod
  # ^ One command: installs Flux controllers AND commits their own manifests
  #   back into your Git repo — the control plane bootstraps itself via GitOps.

flux get sources git                          # List watched Git repositories
flux get kustomizations                          # List sync targets and their status
flux reconcile kustomization my-app                 # Force an immediate sync (like `argocd app sync`)
flux suspend kustomization my-app                      # Pause reconciliation (e.g. during an incident)

cat <<'EOF'
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata: { name: my-app }
spec:
  interval: 1m
  url: https://github.com/org/repo.git
  ref: { branch: main }
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata: { name: my-app }
spec:
  interval: 5m
  path: "./k8s/overlays/production"
  sourceRef: { kind: GitRepository, name: my-app }
  prune: true
EOF
# ArgoCD vs Flux, the real interview answer: ArgoCD ships a polished web UI
# and an app-centric mental model out of the box; Flux is more composable/
# unix-philosophy (separate controllers for sources, image updates, alerts)
# and integrates more naturally if you're already all-in on kubectl/CLI workflows.


# =============================================================================
# 10. SECRETS MANAGEMENT IN CI/CD: VAULT & SOPS
# =============================================================================

# --- HashiCorp Vault: centralized secrets, dynamic/short-lived credentials ---
vault login                                # Authenticate to Vault
vault kv put secret/myapp DB_PASSWORD=s3cret  # Store a static secret
vault kv get secret/myapp                        # Read it back
vault read database/creds/my-role                  # Request a DYNAMIC DB credential — generated on
                                                     # demand, auto-expires, never stored anywhere long-lived
vault policy write my-policy policy.hcl                # Define what a role/token is allowed to read

# CI integration pattern: the pipeline authenticates to Vault via short-lived
# OIDC/JWT (its CI provider identity token), NOT a long-lived Vault token
# checked into a secrets store — mirrors the OIDC-to-cloud pattern in section 1.

# --- SOPS (Secrets OPerationS): encrypt secrets so they're safe to commit to Git ---
sops -e -i secrets.enc.yaml                # Encrypt a file in place (keeps keys, encrypts values)
sops -d secrets.enc.yaml                      # Decrypt for viewing (needs the right KMS/PGP/age key)
sops --encrypt --kms arn:aws:kms:...:key/xxx secrets.yaml > secrets.enc.yaml  # Encrypt via AWS KMS
sops -d secrets.enc.yaml | kubectl apply -f -    # Decrypt at deploy time, straight into the cluster
# Key idea: SOPS lets you commit ENCRYPTED secrets alongside your GitOps
# manifests — Flux and ArgoCD both have native SOPS-decryption integrations,
# so "secrets live in Git, encrypted" and "GitOps is the source of truth" coexist.


# =============================================================================
# 11. IaC ALTERNATIVES TO TERRAFORM
# =============================================================================

# --- Pulumi: IaC using real programming languages (TypeScript/Python/Go/C#) ---
cat <<'EOF'
// index.ts
import * as aws from "@pulumi/aws";
const bucket = new aws.s3.Bucket("my-bucket");
export const bucketName = bucket.id;
EOF
pulumi up                              # Preview + apply (Terraform's plan+apply, one command)
pulumi preview                            # Dry run only
pulumi destroy                               # Tear down
pulumi stack select production                 # Switch environment (like tf workspace)
# Chosen over Terraform when a team wants real loops/functions/types/unit tests
# around infra code instead of HCL — same declarative-state model underneath.

# --- AWS CDK: similar idea, AWS-specific, synthesizes to CloudFormation ---
cat <<'EOF'
// AWS CDK (TypeScript)
const bucket = new s3.Bucket(this, 'MyBucket');
EOF
cdk synth                              # Render the CloudFormation template (no changes yet)
cdk diff                                  # Show what would change
cdk deploy                                   # Synth + deploy via CloudFormation under the hood

# --- Raw CloudFormation / Azure Bicep (native, no third-party state file) ---
aws cloudformation deploy --template-file template.yaml --stack-name my-stack
az deployment group create --resource-group my-rg --template-file main.bicep
# Tradeoff vs Terraform: no separate state file to manage/lock (the cloud
# provider IS the state), but locked to one cloud — Terraform's multi-provider
# model is exactly why it stayed dominant for anything multi-cloud/hybrid.


# =============================================================================
# 12. PACKER — IMMUTABLE IMAGE BUILDING
# =============================================================================

# Packer builds a machine image (AMI, Azure image, GCE image, or a Vagrant
# box) from a declarative template — the "bake the whole environment into an
# image" counterpart to Terraform's "provision infrastructure" and Ansible's
# "configure a running host." Common combo: Packer builds a golden AMI in CI,
# Terraform then deploys instances FROM that AMI.

cat <<'EOF'
# --- image.pkr.hcl ---
source "amazon-ebs" "app" {
  ami_name      = "myapp-{{timestamp}}"
  instance_type = "t3.micro"
  region        = "us-east-1"
  source_ami_filter {
    filters = { name = "ubuntu/images/*22.04*" }
    most_recent = true
    owners      = ["099720109477"]
  }
}
build {
  sources = ["source.amazon-ebs.app"]
  provisioner "shell" { script = "install.sh" }
}
EOF

packer init .                          # Download required plugins
packer validate image.pkr.hcl             # Check template syntax
packer build image.pkr.hcl                   # Build the image


# =============================================================================
# 13. DEPENDENCY & SUPPLY-CHAIN AUTOMATION: DEPENDABOT & RENOVATE
# =============================================================================

# Both auto-open PRs bumping outdated/vulnerable dependencies — the difference
# is scope and configurability.
#   Dependabot -> built into GitHub natively, zero external setup, simpler config
#   Renovate   -> far more configurable (grouping, scheduling, auto-merge rules,
#                   works across GitHub/GitLab/Bitbucket/Azure DevOps identically)

cat <<'EOF'
# --- .github/dependabot.yml ---
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/"
    schedule: { interval: "weekly" }
    open-pull-requests-limit: 10
EOF

cat <<'EOF'
// --- renovate.json ---
{
  "extends": ["config:recommended"],
  "packageRules": [
    { "matchUpdateTypes": ["minor", "patch"], "automerge": true }
  ],
  "schedule": ["before 6am on monday"]
}
EOF
# Both close the loop that A06 (Vulnerable & Outdated Components) in the OWASP
# Top 10 describes — see Ethical Hacking Fundamentals Notes section 6.


# =============================================================================
# 14. CODE QUALITY GATES: SONARQUBE
# =============================================================================

# SonarQube (or its cloud SaaS twin, SonarCloud) runs static analysis for
# bugs, vulnerabilities, code smells, duplication, and test coverage, then
# enforces a "Quality Gate" — a pipeline can be configured to FAIL the build
# if coverage drops below a threshold or new critical issues are introduced,
# turning code-quality policy into an actual CI blocker instead of a suggestion.

sonar-scanner \
  -Dsonar.projectKey=my-app \
  -Dsonar.sources=. \
  -Dsonar.host.url=https://sonarcloud.io \
  -Dsonar.login=$SONAR_TOKEN

# Typical CI step: run tests with coverage -> run sonar-scanner -> pipeline
# polls the Quality Gate result and fails the job if it doesn't pass.


# =============================================================================
# 15. MONOREPO BUILD SYSTEMS: NX, TURBOREPO & BAZEL
# =============================================================================

# As repos grow into monorepos (many apps/packages, one Git history), naive
# CI that rebuilds/retests EVERYTHING on every commit gets too slow. These
# tools solve that with dependency-graph-aware incremental builds and caching:

npx nx affected -t test                # Nx: only test projects actually affected by this diff
npx nx graph                              # Visualize the project dependency graph

turbo run build --filter=my-app        # Turborepo: build only one package + its dependencies
turbo run test --cache-dir=.turbo         # Local cache — reruns skip untouched packages entirely

bazel build //services/api:server      # Bazel: hermetic, reproducible builds at Google's original scale
bazel test //services/api:all             # Remote caching + remote execution scale this to huge monorepos
# Nx/Turborepo dominate JS/TS monorepos; Bazel is heavier to adopt but the
# standard answer for large polyglot monorepos (Google, Uber-style scale).


# =============================================================================
# 16. CROSS-TOOL CONCEPTS THAT SHOW UP IN EVERY INTERVIEW
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
