# ============================================================
# L02: Infrastructure as Code — Terraform Deep Dive
# ============================================================
# WHAT: Declaring cloud infrastructure (VPCs, databases, IAM, Kubernetes
#       clusters) as version-controlled code instead of manual console clicks.
# WHY (PRODUCTION): Manual infra changes are unauditable and unreproducible.
#       Terraform gives you a diff (`plan`) before every change, a single
#       source of truth, and the ability to recreate an entire environment
#       from git history.
# LEVEL: Mid-to-senior backend / platform engineer
# ============================================================

"""
CONCEPT OVERVIEW:
Terraform (HashiCorp) is a declarative IaC tool. You describe the desired
end state in HCL (HashiCorp Configuration Language); Terraform computes a
diff against the last known state and an execution plan to reconcile reality
with your code.

Core building blocks:
  - provider: which API to talk to (aws, google, kubernetes, vault...)
  - resource: a thing to create/manage (aws_instance, aws_db_instance...)
  - data source: read-only lookup of existing infra (data "aws_ami" ...)
  - variable / output: parameterization and cross-module wiring
  - module: a reusable, versioned bundle of resources

PRODUCTION USE CASE:
A platform team maintains a `terraform-modules` repo with a versioned
`rds-postgres` module. Every team consuming a Postgres DB pins a module
version (`source = "git::.../rds-postgres?ref=v2.3.0"`), gets consistent
tagging/backup/encryption defaults, and upgrades on their own schedule by
bumping the ref.

COMMON MISTAKES:
- Storing state locally (or in git) — it contains secrets in plaintext and
  causes conflicts when two people run `apply` simultaneously.
- Never using `-target` as a permanent workaround; it hides drift.
- Not pinning provider/module versions — a `terraform init` six months later
  silently pulls breaking changes.
- Running `apply` by hand in prod instead of via CI (Atlantis/CI pipeline).
"""

import textwrap

# ------------------------------------------------------------------
# 1. HCL fundamentals
# ------------------------------------------------------------------
HCL_BASICS = textwrap.dedent("""\
    # provider: configures the AWS provider, pinned to a major version
    terraform {
      required_version = ">= 1.7.0"
      required_providers {
        aws = {
          source  = "hashicorp/aws"
          version = "~> 5.0"          # allow 5.x, block 6.x (breaking changes)
        }
      }
    }

    provider "aws" {
      region = var.aws_region
    }

    # variable: an input parameter, with a type constraint and default
    variable "aws_region" {
      type    = string
      default = "us-east-1"
    }

    # data source: read-only lookup — does NOT create anything
    data "aws_ami" "amazon_linux" {
      most_recent = true
      owners      = ["amazon"]
      filter {
        name   = "name"
        values = ["al2023-ami-*-x86_64"]
      }
    }

    # resource: the thing Terraform actually creates/manages
    resource "aws_instance" "web" {
      ami           = data.aws_ami.amazon_linux.id
      instance_type = "t3.micro"
      tags = {
        Name        = "web-server"
        Environment = var.environment   # references another variable
        ManagedBy   = "terraform"       # tagging convention — see L07 FinOps
      }
    }

    # local: a computed value, scoped to this module, not settable from outside
    locals {
      name_prefix = "${var.environment}-${var.aws_region}"
    }

    # output: exposes a value to the caller (root module or parent module)
    output "instance_public_ip" {
      value = aws_instance.web.public_ip
    }
""")

# ------------------------------------------------------------------
# 2. Remote state with locking — the #1 production requirement
# ------------------------------------------------------------------
# Local state (terraform.tfstate on disk) breaks the moment a second engineer
# runs terraform. Remote state in S3 + a DynamoDB lock table solves both
# "single source of truth" and "no concurrent apply corrupts state".
REMOTE_STATE_CONFIG = textwrap.dedent("""\
    terraform {
      backend "s3" {
        bucket         = "myorg-terraform-state"
        key            = "billing-service/prod/terraform.tfstate"
        region         = "us-east-1"
        dynamodb_table = "terraform-locks"   # DynamoDB item = advisory lock
        encrypt        = true                # SSE-KMS on the state file itself
      }
    }

    # The DynamoDB table needs exactly one attribute: LockID (string, hash key).
    # Terraform writes a lock item before `apply`/`plan` mutations and deletes
    # it on completion. A crashed process can leave a stale lock — use
    # `terraform force-unlock <LOCK_ID>` only after confirming no other apply
    # is actually running.
""")

# ------------------------------------------------------------------
# 3. Modules — reusable, versioned infrastructure
# ------------------------------------------------------------------
MODULE_EXAMPLE = textwrap.dedent("""\
    # modules/rds-postgres/main.tf  (the reusable module)
    variable "identifier"   { type = string }
    variable "instance_class" { type = string, default = "db.t3.medium" }
    variable "allocated_storage" { type = number, default = 20 }

    resource "aws_db_instance" "this" {
      identifier           = var.identifier
      engine               = "postgres"
      engine_version       = "15.4"
      instance_class       = var.instance_class
      allocated_storage    = var.allocated_storage
      storage_encrypted    = true                 # org-wide default baked into module
      backup_retention_period = 7
      deletion_protection  = true
    }

    output "endpoint" { value = aws_db_instance.this.endpoint }

    # --- consumer usage, pinned to a tagged release ---
    module "billing_db" {
      source  = "git::https://github.com/myorg/terraform-modules.git//rds-postgres?ref=v2.3.0"
      identifier = "billing-prod"
      instance_class = "db.r6g.large"
    }
""")

# ------------------------------------------------------------------
# 4. Workspaces — environment separation within one config
# ------------------------------------------------------------------
WORKSPACE_COMMANDS = textwrap.dedent("""\
    terraform workspace new staging
    terraform workspace new prod
    terraform workspace select staging
    terraform apply    # applies against the 'staging' state file, isolated
                        # from 'prod' — same .tf code, different state.

    # In code, reference the active workspace to vary sizing:
    # instance_class = terraform.workspace == "prod" ? "db.r6g.large" : "db.t3.micro"
    #
    # CAVEAT: workspaces share the same backend config and variable
    # definitions. For meaningfully different environments (different
    # accounts, different VPCs), most teams prefer separate root modules
    # per environment over workspaces, reserving workspaces for
    # short-lived preview/ephemeral environments.
""")

# ------------------------------------------------------------------
# 5. Core workflow + meta-arguments
# ------------------------------------------------------------------
CORE_WORKFLOW = textwrap.dedent("""\
    terraform init      # download providers/modules, configure backend
    terraform validate  # syntax + internal consistency check
    terraform plan -out=tfplan   # compute diff, save it (apply exactly this plan)
    terraform apply tfplan       # apply the SAVED plan — avoids TOCTOU races
    terraform destroy            # tear down everything this state manages

    # Importing infra that was created out-of-band (console click, old script):
    terraform import aws_instance.web i-0123456789abcdef0
""")

META_ARGUMENTS = textwrap.dedent("""\
    # count: create N near-identical copies (indexed 0..N-1)
    resource "aws_instance" "worker" {
      count         = 3
      ami           = data.aws_ami.amazon_linux.id
      instance_type = "t3.micro"
      tags          = { Name = "worker-${count.index}" }
    }

    # for_each: create one resource per map/set entry — PREFERRED over count
    # because adding/removing a middle entry doesn't shift every subsequent
    # resource's index (count causes destroy/recreate cascades on reorder).
    resource "aws_iam_user" "team" {
      for_each = toset(["alice", "bob", "carol"])
      name     = each.value
    }

    # lifecycle block: control replacement/deletion behavior
    resource "aws_db_instance" "prod" {
      # ...
      lifecycle {
        prevent_destroy       = true   # `terraform destroy` errors out — safety net
        create_before_destroy = true   # for zero-downtime replacement (e.g. ASG launch configs)
      }
    }

    # dynamic block: generate repeated nested blocks from a list/map
    resource "aws_security_group" "web" {
      name = "web-sg"
      dynamic "ingress" {
        for_each = [80, 443]
        content {
          from_port   = ingress.value
          to_port     = ingress.value
          protocol    = "tcp"
          cidr_blocks = ["0.0.0.0/0"]
        }
      }
    }
""")

# ------------------------------------------------------------------
# 6. Atlantis — GitOps for Terraform
# ------------------------------------------------------------------
# Atlantis runs as a webhook receiver on your VCS. On PR open, it comments
# `terraform plan` output automatically. On a magic comment (`atlantis apply`)
# after approval, it runs `apply`. This makes Terraform changes go through
# the exact same review gate as application code — no more "someone ran
# apply from their laptop with stale local state".
ATLANTIS_CONFIG = textwrap.dedent("""\
    # atlantis.yaml at repo root
    version: 3
    projects:
      - name: billing-prod
        dir: envs/prod
        workspace: default
        autoplan:
          when_modified: ["*.tf", "../modules/**/*.tf"]
        apply_requirements: [approved, mergeable]   # blocks apply until PR approved
""")

# ------------------------------------------------------------------
# 7. Drift detection
# ------------------------------------------------------------------
# Someone clicking around in the AWS console changes real infra without
# updating Terraform's state — this is "drift". Detect it by running
# `terraform plan` on a schedule (e.g. nightly CI cron) and alerting if the
# plan is non-empty when it should be (no pending code changes).
DRIFT_DETECTION_CI = textwrap.dedent("""\
    # nightly-drift-check.yml (GitHub Actions, conceptual)
    - run: terraform plan -detailed-exitcode
      # exit code 0 = no changes, 1 = error, 2 = changes present (drift!)
      continue-on-error: true
      id: plan
    - if: steps.plan.outputs.exitcode == '2'
      run: slack-notify "Drift detected in billing-prod — investigate before next apply"
""")

if __name__ == "__main__":
    print(HCL_BASICS[:200], "...")

"""
TRADING/PRODUCTION CONTEXT EXAMPLE:
A trading firm's market-data ingestion cluster runs on 40 EC2 instances
across 3 availability zones, defined entirely in Terraform modules. When a
new exchange feed is added, an engineer bumps a `feed_count` variable and
runs `terraform plan` — the diff shows exactly 3 new instances (one per AZ)
with zero risk of accidentally modifying the other 37. State lives in S3
with DynamoDB locking so the on-call engineer and the platform team never
clobber each other's concurrent `apply` during an incident.
"""
