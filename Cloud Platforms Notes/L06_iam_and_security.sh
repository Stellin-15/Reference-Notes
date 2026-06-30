#!/usr/bin/env bash
# ============================================================
# L06: Cloud IAM and Security
# ============================================================
# WHAT: Identity and Access Management — who can do what to which
#       resources. Plus the key security services: encryption,
#       secrets, audit logging, and threat detection.
# WHY:  IAM misconfigurations are the #1 cause of cloud breaches.
#       Over-permissive roles, hardcoded credentials, and missing
#       audit logs are the most common failure patterns. Security
#       is designed in from the start, not bolted on later.
# LEVEL: Advanced
# ============================================================
# CONCEPT OVERVIEW:
#   AWS IAM uses a deny-by-default model: nothing is allowed
#   unless explicitly permitted by a policy. Policies are JSON
#   documents attached to identities (users, groups, roles) or
#   resources. Roles use temporary credentials via STS — no
#   long-lived passwords or access keys. At the org level,
#   SCPs add a hard ceiling that no IAM policy can override.
#
# PRODUCTION USE CASE:
#   A Lambda function reads from DynamoDB and writes to S3.
#   Instead of access keys in environment variables, the function
#   assumes an IAM role via instance profile. The role has a
#   customer-managed policy granting only the exact DynamoDB table
#   and S3 bucket needed — nothing else. CloudTrail records every
#   API call. GuardDuty alerts if the role is used from an
#   unexpected IP or performs unusual API calls.
#
# COMMON MISTAKES:
#   - Using root account for daily operations (use it only to
#     create the first admin user, then lock away root).
#   - Using IAM users with long-lived access keys in CI/CD.
#     Use OIDC federation with temporary credentials instead.
#   - Attaching AdministratorAccess to services. Always scope down.
#   - Not enabling MFA on privileged accounts.
#   - Storing secrets in environment variables or code.
#     Use Secrets Manager or Parameter Store.
#   - Not enabling CloudTrail — you lose your audit trail.
# ============================================================

set -euo pipefail

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="us-east-1"

# ============================================================
# SECTION 1: IAM Identity Types
# ============================================================
# WHAT: The three types of identities in AWS IAM.
#
# IAM USERS:
#   - Human or service identity with long-term credentials.
#   - Has username + password (console) and/or access key + secret.
#   - AVOID for services — access keys are static, can be leaked,
#     and don't rotate automatically.
#   - OK for: human admins (with MFA), emergency break-glass accounts.
#   - Should be in GROUPS, not have policies attached directly.
#
# IAM GROUPS:
#   - Collection of users. Attach policies to the group.
#   - Users inherit all permissions of their groups.
#   - Groups cannot have other groups as members.
#   - Use case: "developers" group with ReadOnly + CodeCommit access.
#
# IAM ROLES:
#   - Identity with temporary credentials. No password or long-term key.
#   - Assumed by: AWS services (EC2, Lambda), users (cross-account),
#     federated identities (SAML, OIDC/GitHub Actions).
#   - STS (Security Token Service) issues time-limited credentials
#     (default 1 hour, max 12 hours for most roles).
#   - Best practice: everything uses roles. No long-term credentials
#     for services, ever.
#
# GCP equivalent: Service Accounts (analogous to IAM roles).
# Azure: Service Principals, Managed Identities (analogous to roles —
#        system-assigned or user-assigned).
# ============================================================

# Create an IAM group for developers with managed read-only policy
aws iam create-group --group-name "Developers"

aws iam attach-group-policy \
  --group-name "Developers" \
  --policy-arn "arn:aws:iam::aws:policy/ReadOnlyAccess"

# Create a human IAM user for a developer (with MFA enforced via policy)
# In practice, prefer SSO (AWS IAM Identity Center) with your IdP
aws iam create-user --user-name "jdoe"

aws iam add-user-to-group --user-name "jdoe" --group-name "Developers"

# MFA enforcement policy — users without MFA can only manage their own MFA
# This pattern: no MFA → can only add MFA. With MFA → normal access.
cat > /tmp/mfa-enforce-policy.json << 'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowManageOwnMFA",
      "Effect": "Allow",
      "Action": [
        "iam:CreateVirtualMFADevice",
        "iam:EnableMFADevice",
        "iam:GetUser",
        "iam:ListMFADevices"
      ],
      "Resource": "arn:aws:iam::*:user/${aws:username}"
    },
    {
      "Sid": "DenyWithoutMFA",
      "Effect": "Deny",
      "NotAction": [
        "iam:CreateVirtualMFADevice",
        "iam:EnableMFADevice",
        "iam:GetUser",
        "iam:ListMFADevices",
        "sts:GetSessionToken"
      ],
      "Resource": "*",
      "Condition": {
        "BoolIfExists": {
          "aws:MultiFactorAuthPresent": "false"
        }
      }
    }
  ]
}
POLICY

aws iam create-policy \
  --policy-name "RequireMFA" \
  --policy-document file:///tmp/mfa-enforce-policy.json

aws iam attach-group-policy \
  --group-name "Developers" \
  --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/RequireMFA"

# ============================================================
# SECTION 2: IAM Policies — The Permission Engine
# ============================================================
# WHAT: JSON documents that define what actions are allowed or
#       denied on which resources and under what conditions.
#
# POLICY STRUCTURE — every statement has these elements:
#   Effect:    "Allow" or "Deny". Deny always wins.
#   Action:    AWS API actions. e.g., "s3:GetObject", "ec2:*",
#              ["dynamodb:GetItem", "dynamodb:PutItem"].
#   Resource:  ARN of the resource. "*" means all resources.
#              Scope down to specific ARN always.
#   Principal: WHO the policy applies to (only in resource policies
#              and trust policies, not identity policies).
#   Condition: Optional. Restrict by IP, region, MFA, time, tags, etc.
#
# POLICY EVALUATION ORDER:
#   1. Explicit DENY → deny immediately (no override).
#   2. Explicit ALLOW (from any policy) → allow.
#   3. Default DENY (nothing matched) → deny.
#
# POLICY TYPES:
#   AWS Managed: Written and maintained by AWS. Examples:
#     - AdministratorAccess  → full access to everything
#     - PowerUserAccess      → full access except IAM
#     - ReadOnlyAccess       → read all services, no write
#   Customer Managed: You write and control. Reusable.
#   Inline Policies: Embedded directly in user/role/group.
#     Deleted when the identity is deleted. Hard to audit.
#     Avoid unless you intentionally want 1-to-1 binding.
#
# GCP equivalent: IAM Roles (predefined and custom) with Bindings
#                 on resources. Conditions on bindings.
# Azure: Azure RBAC Roles and Role Assignments. Conditions (preview).
# ============================================================

# Customer managed policy — minimum permissions for a Lambda that
# reads DynamoDB and writes to S3 (the real example from the overview)
cat > /tmp/lambda-dynamodb-s3-policy.json << POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadFromOrdersTable",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:BatchGetItem"
      ],
      "Resource": [
        "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/orders",
        "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/orders/index/*"
      ]
    },
    {
      "Sid": "WriteToProcessedBucket",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:PutObjectAcl"
      ],
      "Resource": "arn:aws:s3:::my-processed-data-bucket/*"
    },
    {
      "Sid": "AllowLoggingToCloudWatch",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:/aws/lambda/order-processor:*"
    },
    {
      "Sid": "DenyInternetAccess",
      "Effect": "Deny",
      "Action": "*",
      "Resource": "*",
      "Condition": {
        "NotIpAddress": {
          "aws:SourceIp": [
            "10.0.0.0/8",
            "172.16.0.0/12"
          ]
        },
        "Bool": {
          "aws:ViaAWSService": "false"
        }
      }
    }
  ]
}
POLICY

POLICY_ARN=$(aws iam create-policy \
  --policy-name "LambdaOrderProcessorPolicy" \
  --policy-document file:///tmp/lambda-dynamodb-s3-policy.json \
  --query 'Policy.Arn' --output text)

echo "Created policy: $POLICY_ARN"

# ============================================================
# SECTION 3: IAM Roles and Service Roles
# ============================================================
# WHAT: Roles are the correct way for AWS services to get
#       permissions. A role has two parts:
#
#   TRUST POLICY (who can assume this role):
#     Defines which principal is allowed to call sts:AssumeRole.
#     Could be: an AWS service (lambda.amazonaws.com), an account,
#     a federated identity provider, or another role.
#
#   PERMISSION POLICY (what the role can do):
#     Standard IAM policy defining actions and resources.
#
# SERVICE ROLES — AWS services that assume roles:
#   EC2 Instance Profile: EC2 instances assume a role to get temp
#                          credentials. AWS SDK auto-refreshes them
#                          via the instance metadata service (IMDS).
#                          No credentials in code, ever.
#   Lambda Execution Role: Lambda function's identity. Attached at
#                          function creation. Can be changed later.
#   EKS Node Role: Worker nodes assume a role to pull ECR images,
#                  write CloudWatch logs, etc.
#   EKS Pod Role (IRSA): Individual pods get their own role via
#                         IAM Roles for Service Accounts. OIDC-based.
#                         Much more granular than node-level roles.
#
# GCP: Workload Identity — pods get a Google service account via
#      Kubernetes service account annotation. Similar to IRSA.
# Azure: Managed Identity — system-assigned (tied to resource
#        lifecycle) or user-assigned (independent lifecycle).
# ============================================================

# Trust policy for Lambda — only the Lambda service can assume this role
cat > /tmp/lambda-trust-policy.json << 'TRUST'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
TRUST

# Create the Lambda execution role
LAMBDA_ROLE_ARN=$(aws iam create-role \
  --role-name "OrderProcessorLambdaRole" \
  --assume-role-policy-document file:///tmp/lambda-trust-policy.json \
  --description "Execution role for order processor Lambda" \
  --query 'Role.Arn' --output text)

# Attach the minimum-permission policy we created earlier
aws iam attach-role-policy \
  --role-name "OrderProcessorLambdaRole" \
  --policy-arn "$POLICY_ARN"

# Also attach AWS managed policy for Lambda VPC access (if function is in VPC)
aws iam attach-role-policy \
  --role-name "OrderProcessorLambdaRole" \
  --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"

echo "Lambda role: $LAMBDA_ROLE_ARN"

# ============================================================
# SECTION 4: OIDC Federation — GitHub Actions Without Keys
# ============================================================
# WHAT: Allow external identity providers (GitHub, GitLab, Google)
#       to exchange their tokens for temporary AWS credentials.
#       No long-lived access keys in CI/CD. Ever.
#
# HOW GITHUB ACTIONS OIDC WORKS:
#   1. GitHub generates an OIDC token for the workflow run.
#      The token contains claims: repo, branch, workflow, actor.
#   2. GitHub Actions calls sts:AssumeRoleWithWebIdentity,
#      passing the OIDC token and the role ARN.
#   3. STS validates the token with GitHub's OIDC endpoint,
#      checks the trust policy conditions (must match repo/branch),
#      and returns short-lived credentials (1 hour).
#   4. The workflow uses those credentials to deploy to AWS.
#
# CONDITION examples in trust policy:
#   token.actions.githubusercontent.com:sub  →  the subject claim
#   "repo:myorg/myrepo:ref:refs/heads/main"  →  ONLY from main branch
#   "repo:myorg/myrepo:*"                    →  any branch (less secure)
#
# WHY THIS IS BETTER THAN ACCESS KEYS IN SECRETS:
#   - Keys can be accidentally committed to git, leaked in logs,
#     or stolen from secrets storage.
#   - OIDC tokens are short-lived (minutes), created per-run, and
#     can't be reused outside their GitHub Actions context.
#
# GCP: Workload Identity Federation — same OIDC concept.
# Azure: Federated identity credentials on App Registrations.
# ============================================================

# Register GitHub's OIDC provider with AWS once per account
aws iam create-open-id-connect-provider \
  --url "https://token.actions.githubusercontent.com" \
  --client-id-list "sts.amazonaws.com" \
  --thumbprint-list "6938fd4d98bab03faadb97b34396831e3780aea1"

# Trust policy that only allows GitHub Actions from your specific repo/branch
cat > /tmp/github-oidc-trust.json << TRUST
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:myorg/myrepo:ref:refs/heads/main"
        }
      }
    }
  ]
}
TRUST

# Create the deployment role
DEPLOY_ROLE=$(aws iam create-role \
  --role-name "GitHubActionsDeployRole" \
  --assume-role-policy-document file:///tmp/github-oidc-trust.json \
  --max-session-duration 3600 \
  --query 'Role.Arn' --output text)

# In GitHub Actions workflow (.github/workflows/deploy.yml):
# permissions:
#   id-token: write   # required for OIDC
#   contents: read
#
# - uses: aws-actions/configure-aws-credentials@v4
#   with:
#     role-to-assume: arn:aws:iam::ACCOUNT_ID:role/GitHubActionsDeployRole
#     aws-region: us-east-1

# ============================================================
# SECTION 5: Permission Boundaries and SCPs
# ============================================================
# WHAT: Two mechanisms for limiting the maximum permissions
#       an identity can ever have.
#
# PERMISSION BOUNDARIES:
#   - Attached to a specific role or user.
#   - Sets the MAXIMUM permissions that identity can have.
#   - Even if an identity has AdministratorAccess, a permission
#     boundary limiting to S3 means only S3 is accessible.
#   - Effective permissions = intersection of identity policy
#     AND permission boundary.
#   - Use case: "delegated admin" — let teams create roles but
#     prevent them from creating roles MORE powerful than a boundary.
#     Team can create roles for their apps but can't escalate to admin.
#
# SCPS (Service Control Policies):
#   - Applied at the AWS Organization / OU / Account level.
#   - Hard ceiling that NO IAM policy can override. Not even root.
#   - Applied BEFORE IAM evaluation.
#   - Example: deny all actions outside us-east-1 and eu-west-1.
#     Even if a user has AdministratorAccess, they can't create
#     resources in ap-southeast-1.
#   - Use case: org-wide guardrails, data residency compliance,
#     preventing accidental deployments to wrong regions.
#
# GCP equivalent: Org Policies — constraints on what can be done
#                 in a project/folder/org. e.g., restrict resource
#                 locations, require OS Login, disable service account keys.
# Azure: Azure Policy — compliance enforcement across subscriptions.
#        Management Groups for hierarchy like AWS Orgs.
# ============================================================

# Permission boundary — this role can ONLY interact with S3 and DynamoDB
# Even if you accidentally attach AdministratorAccess to this role,
# the boundary prevents anything beyond S3/DynamoDB
cat > /tmp/app-boundary.json << 'BOUNDARY'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:*",
        "dynamodb:*",
        "logs:*",
        "cloudwatch:*"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Deny",
      "Action": [
        "iam:*",
        "organizations:*",
        "account:*"
      ],
      "Resource": "*"
    }
  ]
}
BOUNDARY

BOUNDARY_ARN=$(aws iam create-policy \
  --policy-name "AppPermissionBoundary" \
  --policy-document file:///tmp/app-boundary.json \
  --query 'Policy.Arn' --output text)

# Apply boundary to the Lambda role
aws iam put-role-permissions-boundary \
  --role-name "OrderProcessorLambdaRole" \
  --permissions-boundary "$BOUNDARY_ARN"

# SCP example — deny all non-approved regions (org-level, not shown as CLI
# because it requires Organizations APIs and targets accounts/OUs)
# {
#   "Version": "2012-10-17",
#   "Statement": [
#     {
#       "Sid": "DenyNonApprovedRegions",
#       "Effect": "Deny",
#       "NotAction": [
#         "iam:*",
#         "organizations:*",
#         "route53:*",
#         "cloudfront:*",
#         "sts:*",
#         "support:*"
#       ],
#       "Resource": "*",
#       "Condition": {
#         "StringNotEquals": {
#           "aws:RequestedRegion": ["us-east-1", "eu-west-1"]
#         }
#       }
#     }
#   ]
# }

# ============================================================
# SECTION 6: KMS — Key Management Service
# ============================================================
# WHAT: Create and manage cryptographic keys for encrypting data
#       at rest (S3, EBS, RDS, DynamoDB, Secrets Manager).
#
# KEY TYPES:
#   AWS Managed Keys (aws/s3, aws/rds, etc.):
#     - Created automatically when you enable encryption.
#     - You don't manage them. Cannot customize key policy.
#     - Rotated annually. Cannot delete. No extra cost.
#
#   Customer Managed Keys (CMK):
#     - You create and control. Full key policy control.
#     - Enable automatic rotation (KMS generates new material yearly,
#       keeps old versions to decrypt existing data).
#     - Can be used cross-account by sharing key policy.
#     - Cost: $1/month per key + $0.03 per 10,000 API calls.
#     - Use when: compliance requires key ownership, cross-account
#       access, custom key rotation, key deletion control.
#
# ENVELOPE ENCRYPTION (how it actually works):
#   1. KMS generates a Data Encryption Key (DEK).
#   2. DEK encrypts your actual data.
#   3. KMS encrypts the DEK with your CMK (key-encrypting-key).
#   4. You store the encrypted data + encrypted DEK together.
#   5. To decrypt: call KMS to decrypt the DEK → use DEK to decrypt data.
#   This way KMS never sees your data — only the DEK.
#   Your data can be encrypted locally (fast) without sending to KMS each time.
#
# GCP: Cloud KMS — very similar concept. CMEK (customer-managed encryption keys).
# Azure: Azure Key Vault — keys, secrets, certificates in one service.
# ============================================================

# Create a Customer Managed Key for encrypting order data
CMK_ID=$(aws kms create-key \
  --description "CMK for encrypting order data in DynamoDB and S3" \
  --key-usage ENCRYPT_DECRYPT \
  --key-spec SYMMETRIC_DEFAULT \
  --query 'KeyMetadata.KeyId' --output text)

# Create a human-readable alias (CMK IDs are UUIDs)
aws kms create-alias \
  --alias-name "alias/order-data-key" \
  --target-key-id "$CMK_ID"

# Enable automatic key rotation (best practice)
# KMS rotates the key material annually.
# Old material is retained to decrypt existing ciphertext.
# New plaintext encryptions use the new material.
aws kms enable-key-rotation --key-id "$CMK_ID"

# Grant the Lambda role permission to use this key
aws kms create-grant \
  --key-id "$CMK_ID" \
  --grantee-principal "$LAMBDA_ROLE_ARN" \
  --operations Decrypt GenerateDataKey GenerateDataKeyWithoutPlaintext

echo "CMK: $CMK_ID (alias: order-data-key)"

# ============================================================
# SECTION 7: Secrets Manager and Parameter Store
# ============================================================
# WHAT: Secure storage for secrets (DB passwords, API keys, TLS certs).
#       Never put secrets in code, environment variables, or logs.
#
# SECRETS MANAGER:
#   - Stores secrets as key-value JSON, rotates them automatically.
#   - Built-in rotation support for RDS, Redshift, DocumentDB.
#     AWS provides a Lambda rotator — you just enable and schedule.
#   - Replicate secrets across regions for multi-region apps.
#   - Cost: $0.40/secret/month + $0.05 per 10,000 API calls.
#   - Use for: database passwords, OAuth tokens, API keys, anything
#     that rotates or requires audit log of every access.
#
# SSM PARAMETER STORE:
#   - Standard tier: free. 10,000 params, 4KB value, no rotation.
#   - Advanced tier: $0.05/param/month, 8KB, parameter policies (TTL).
#   - SecureString type: encrypted with KMS.
#   - Hierarchy: /prod/database/password, /prod/api/stripe-key.
#   - Use for: app configuration, feature flags, non-sensitive config
#     that benefits from central management without Secrets Manager cost.
#
# WHEN TO USE WHICH:
#   Secrets Manager: needs rotation, RDS integration, cross-region replication.
#   Parameter Store: config values, simple secrets, cost-conscious scenarios.
#
# GCP: Secret Manager — similar to AWS Secrets Manager.
# Azure: Azure Key Vault Secrets — combined key + secret + cert store.
# ============================================================

# Store the RDS password in Secrets Manager
aws secretsmanager create-secret \
  --name "prod/rds/orders-db-password" \
  --description "Master password for orders RDS cluster" \
  --kms-key-id "$CMK_ID" \
  --secret-string '{"username":"admin","password":"REPLACE_WITH_STRONG_PASSWORD"}' \
  --tags '[{"Key":"Environment","Value":"prod"},{"Key":"Service","Value":"orders"}]'

# Enable automatic rotation every 30 days (requires Lambda rotator for RDS)
# aws secretsmanager rotate-secret \
#   --secret-id "prod/rds/orders-db-password" \
#   --rotation-lambda-arn "arn:aws:lambda:us-east-1:ACCOUNT:function:SecretsManagerRotator" \
#   --rotation-rules '{"AutomaticallyAfterDays": 30}'

# SSM Parameter Store for non-secret configuration
aws ssm put-parameter \
  --name "/prod/app/max-concurrent-requests" \
  --value "1000" \
  --type String \
  --description "Max concurrent requests to the orders API"

# SecureString for a less-critical secret (no rotation needed)
aws ssm put-parameter \
  --name "/prod/api/stripe-webhook-secret" \
  --value "whsec_REPLACE_WITH_ACTUAL_SECRET" \
  --type SecureString \
  --key-id "$CMK_ID" \
  --description "Stripe webhook signing secret"

# Fetch a secret in code (Python example):
# import boto3, json
# client = boto3.client('secretsmanager', region_name='us-east-1')
# secret = json.loads(client.get_secret_value(SecretId='prod/rds/orders-db-password')['SecretString'])
# password = secret['password']  # no hardcoded credentials anywhere

# ============================================================
# SECTION 8: CloudTrail — Audit Logging
# ============================================================
# WHAT: Records every API call made in your AWS account.
#       WHO did WHAT to WHICH resource at WHAT TIME from WHERE.
#       This is your forensic record for security incidents.
#
# DEFAULT BEHAVIOR:
#   - Event history: last 90 days in console. No cost. No S3.
#   - To keep logs longer: create a Trail → stores in S3.
#   - Management events (control plane: IAM, EC2 create/delete):
#     logged by default by Trails.
#   - Data events (S3 PutObject, DynamoDB GetItem, Lambda invoke):
#     NOT logged by default — high volume, extra cost. Enable
#     selectively for sensitive buckets/tables.
#
# BEST PRACTICES:
#   - Create an org-level Trail to capture all accounts centrally.
#   - Store in a separate "log archive" account with no delete access.
#   - Enable log file integrity validation (SHA256 hashing).
#   - Enable CloudWatch Logs integration for real-time alerting.
#
# GCP: Cloud Audit Logs — Admin Activity (free, always on),
#      Data Access (need to enable per-service), System Events.
# Azure: Azure Activity Log (free, 90 days), Azure Monitor Logs
#        (longer retention), Microsoft Sentinel (SIEM).
# ============================================================

# Create a Trail for org-wide logging
TRAIL_BUCKET="my-cloudtrail-logs-${ACCOUNT_ID}"

# Create S3 bucket for CloudTrail (with encryption and versioning)
aws s3api create-bucket --bucket "$TRAIL_BUCKET" --region "$REGION"

aws s3api put-bucket-versioning \
  --bucket "$TRAIL_BUCKET" \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket "$TRAIL_BUCKET" \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "aws:kms",
        "KMSMasterKeyID": "'"$CMK_ID"'"
      }
    }]
  }'

# Block all public access to the log bucket — absolutely critical
aws s3api put-public-access-block \
  --bucket "$TRAIL_BUCKET" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

# Create the trail with log file validation enabled
aws cloudtrail create-trail \
  --name "prod-audit-trail" \
  --s3-bucket-name "$TRAIL_BUCKET" \
  --include-global-service-events \
  --is-multi-region-trail \
  --enable-log-file-validation \
  --kms-key-id "$CMK_ID"

aws cloudtrail start-logging --name "prod-audit-trail"

# ============================================================
# SECTION 9: GuardDuty and Security Hub
# ============================================================
# WHAT: Automated threat detection and security posture management.
#
# GUARDDUTY:
#   - Uses ML and threat intelligence to detect malicious activity.
#   - Analyzes: VPC Flow Logs, DNS logs, CloudTrail, EKS audit logs,
#     S3 data events, EBS volume scans, Lambda network activity.
#   - Findings: severity Low/Medium/High.
#   - Example detections:
#     * CryptoCurrency:EC2/BitcoinTool → cryptomining on EC2
#     * UnauthorizedAccess:IAMUser/MaliciousIPCaller → API calls from known bad IP
#     * Recon:EC2/PortProbeUnprotectedPort → port scanning your instances
#     * CredentialAccess:IAMUser/AnomalousBehavior → unusual API pattern
#   - Cost: based on volume of logs analyzed. Typical: $50-300/month.
#   - Enable in every account, every region. Use Org delegation.
#
# SECURITY HUB:
#   - Aggregates findings from: GuardDuty, Inspector (vuln scanning),
#     Macie (S3 data classification/PII detection), Config, Firewall Manager.
#   - Runs continuous compliance checks against:
#     * CIS AWS Foundations Benchmark (Level 1 & 2)
#     * AWS Foundational Security Best Practices
#     * PCI DSS
#     * SOC 2 (via third-party)
#   - Sends findings to EventBridge → Lambda → Jira/PagerDuty/Slack.
#
# GCP: Security Command Center (SCC) — similar aggregation of findings.
#      Chronicle SIEM, Event Threat Detection.
# Azure: Microsoft Defender for Cloud (was Security Center).
#        Microsoft Sentinel (cloud-native SIEM/SOAR).
# ============================================================

# Enable GuardDuty in the current region
DETECTOR_ID=$(aws guardduty create-detector \
  --enable \
  --finding-publishing-frequency FIFTEEN_MINUTES \
  --query 'DetectorId' --output text)

echo "GuardDuty detector: $DETECTOR_ID"

# Enable Security Hub with CIS benchmark enabled
aws securityhub enable-security-hub \
  --enable-default-standards  # enables CIS and AWS FSBP automatically

# Enable the PCI DSS standard additionally
# aws securityhub batch-enable-standards \
#   --standards-subscription-requests \
#     '[{"StandardsArn":"arn:aws:securityhub:us-east-1::standards/pci-dss/v/3.2.1"}]'

# EventBridge rule to route HIGH severity GuardDuty findings to SNS
# aws events put-rule \
#   --name "GuardDutyHighSeverityFindings" \
#   --event-pattern '{
#     "source": ["aws.guardduty"],
#     "detail-type": ["GuardDuty Finding"],
#     "detail": {
#       "severity": [{"numeric": [">=", 7.0]}]
#     }
#   }' \
#   --state ENABLED

# ============================================================
# SECTION 10: Summary — IAM Security Checklist
# ============================================================
# ✓ Root account: enable MFA, remove access keys, lock away.
# ✓ No IAM users for services — use roles everywhere.
# ✓ No long-lived access keys in CI/CD — use OIDC federation.
# ✓ All roles follow least privilege — scope to exact ARNs.
# ✓ Enable MFA on all human IAM users.
# ✓ SCPs in place: deny non-approved regions, deny root usage.
# ✓ All data encrypted at rest with CMKs in KMS.
# ✓ Secrets in Secrets Manager, rotated automatically.
# ✓ CloudTrail enabled in all regions with S3 retention.
# ✓ GuardDuty enabled in all regions.
# ✓ Security Hub enabled with CIS and FSBP standards.
# ✓ Permission boundaries on roles created by delegated admins.
# ============================================================

echo "IAM and security setup complete."
echo "Detector ID: $DETECTOR_ID"
echo "CMK ID: $CMK_ID"
