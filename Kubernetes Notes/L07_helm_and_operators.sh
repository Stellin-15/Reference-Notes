#!/usr/bin/env bash
# ============================================================
# L07: Helm and Kubernetes Operators
# ============================================================
# WHAT: Helm is the package manager for Kubernetes — it bundles
#       K8s manifests into versioned, configurable Charts.
#       Operators extend K8s with custom controllers that manage
#       complex stateful apps (Postgres, Kafka, Prometheus) with
#       domain-specific operational knowledge baked in.
# WHY:  Raw kubectl apply for complex apps (50+ YAML files with
#       environment-specific overrides) is unmanageable. Helm gives
#       you versioning, rollback, and templating. Operators give you
#       automated Day-2 operations: failover, backup, scaling upgrades.
# LEVEL: Advanced
# ============================================================
# CONCEPT OVERVIEW:
#   Helm Chart anatomy:
#     mychart/
#     ├── Chart.yaml           # metadata: name, version, appVersion, dependencies
#     ├── values.yaml          # default config values (overridden per environment)
#     ├── templates/           # Go-templated YAML files
#     │   ├── deployment.yaml
#     │   ├── service.yaml
#     │   ├── _helpers.tpl     # reusable template snippets (named templates)
#     │   └── NOTES.txt        # printed to user after helm install
#     ├── charts/              # sub-charts (dependencies packaged inline)
#     └── .helmignore          # like .gitignore for chart packaging
#
#   Release: an instance of a chart installed in a cluster.
#   One chart can be installed multiple times with different names:
#     helm install mydb ./postgres-chart --values prod-values.yaml
#     helm install staging-db ./postgres-chart --values staging-values.yaml
#
#   Operator pattern:
#     CRD (Custom Resource Definition) → defines a new K8s API resource
#     Controller → watches for that resource, reconciles actual vs desired
#     The controller has domain knowledge: it knows HOW to safely restart
#     Postgres, promote a replica, take a backup, handle split-brain.
#
# PRODUCTION USE CASE:
#   CloudNativePG Operator vs raw StatefulSet for PostgreSQL:
#   - StatefulSet: you get a Postgres pod. That's it. YOU must:
#     * Write the Patroni config for HA
#     * Wire up pg_basebackup for replication
#     * Create a VIP/DNS for primary failover
#     * Write backup cron jobs
#     * Handle replica promotion during primary failure
#   - CloudNativePG: apply a Cluster CR → operator handles all of above.
#     Failover in ~30 seconds, automated backups to S3, PITR, TLS.
#
# COMMON MISTAKES:
#   - helm upgrade --install without --atomic — a partial upgrade can
#     leave the release in a broken state with no auto-rollback.
#   - Storing secrets in values.yaml in git (plaintext passwords) —
#     use helm-secrets + sops or External Secrets Operator instead.
#   - Not pinning chart versions — helm repo update + helm upgrade
#     can pull a new chart version with breaking changes.
#   - Building an Operator for a simple app — Operators add complexity.
#     Use Helm for stateless apps and simple stateful ones.
#     Only use Operators for apps with complex operational logic.
#   - Not setting --cleanup-on-fail on hooks — failed migration jobs
#     block all future upgrades (Job names collide).
# ============================================================


# ===========================================================
# SECTION 1: Helm Installation and Repository Management
# ===========================================================

# Install Helm (macOS/Linux)
# macOS:
brew install helm

# Linux:
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Add commonly used Helm repositories
helm repo add stable https://charts.helm.sh/stable
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add cert-manager https://charts.jetstack.io
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo add kedacore https://kedacore.github.io/charts
helm repo add cnpg https://cloudnative-pg.github.io/charts

# Update all repo indexes (fetch latest chart versions)
helm repo update

# Search for charts in added repos
helm search repo postgres
helm search repo kafka --versions        # list all available versions

# Search in Artifact Hub (public registry)
helm search hub postgres --max-col-width=80


# ===========================================================
# SECTION 2: Chart.yaml — Chart Metadata
# ===========================================================
# Chart.yaml lives at the root of every Helm chart.
# It defines:
#   apiVersion:  v2 for Helm 3 (v1 is Helm 2 only)
#   name:        chart name (used in Release naming)
#   version:     chart version (SemVer — increment on any chart change)
#   appVersion:  version of the APP being packaged (informational)
#   description: shown in helm search results
#   dependencies: sub-charts pulled from repos (like npm dependencies)
#
# version vs appVersion:
#   version:    tracks the chart itself (template changes, new values)
#   appVersion: tracks the application (Docker image tag)
#   You can update the chart (values, templates) without changing appVersion.
#
# Example Chart.yaml (cannot run as shell commands — shown for reference):
# ---
# apiVersion: v2
# name: api-server
# version: 1.4.2
# appVersion: "2.1.0"
# description: REST API server for the platform
# type: application
# dependencies:
#   - name: postgresql
#     version: "13.x.x"
#     repository: https://charts.bitnami.com/bitnami
#     condition: postgresql.enabled    # only deploy if values.postgresql.enabled=true
#   - name: redis
#     version: "18.x.x"
#     repository: https://charts.bitnami.com/bitnami

# After adding/changing dependencies, run:
helm dependency update ./api-server-chart
# This downloads dependent charts into charts/ directory


# ===========================================================
# SECTION 3: Go Templating in Helm Charts
# ===========================================================
# Helm templates use Go's text/template with Sprig functions.
# The template is rendered at install/upgrade time with values
# from values.yaml merged with any --values files or --set flags.
#
# Template variables:
#   .Values.*        → from values.yaml and --values / --set
#   .Release.Name    → name given at helm install time
#   .Release.Namespace → namespace of the release
#   .Chart.Name      → chart name from Chart.yaml
#   .Chart.Version   → chart version
#   .Chart.AppVersion → appVersion from Chart.yaml
#
# Example template snippet (deployment.yaml):
#   image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
#   replicas: {{ .Values.replicaCount }}
#   name: {{ .Release.Name }}-api
#   namespace: {{ .Release.Namespace }}
#
# Control structures:
#   {{- if .Values.ingress.enabled }}   # conditional block (- trims whitespace)
#   {{- range .Values.ingress.hosts }}  # loop over a list
#     host: {{ .host }}
#   {{- end }}
#
# Named templates (_helpers.tpl):
#   {{- define "myapp.labels" -}}
#   app: {{ .Chart.Name }}
#   release: {{ .Release.Name }}
#   {{- end }}
#   # Used in other templates:
#   labels:
#     {{- include "myapp.labels" . | nindent 4 }}
#
# required: fails helm install if value is missing
#   image: {{ required "image.tag is required" .Values.image.tag }}
#
# Render templates locally for debugging (no cluster needed):
helm template my-release ./api-server-chart \
  --values values.yaml \
  --values prod-values.yaml \
  --set image.tag=v2.1.0 \
  --debug                          # show computed values and template source


# ===========================================================
# SECTION 4: Installing and Managing Releases
# ===========================================================

# Basic install
helm install my-api ./api-server-chart
#   my-api         = release name (must be unique per namespace)
#   ./api-server-chart = path to chart dir OR chart name from repo

# Install from repo with specific version
helm install my-api bitnami/nginx --version 15.3.2

# Install with values overrides
helm install my-api ./api-server-chart \
  --namespace production \
  --create-namespace \
    # Create the namespace if it doesn't exist
  --values ./environments/prod/values.yaml \
    # Override defaults with prod-specific values
  --set image.tag=v2.1.0 \
    # Single value override (for CI/CD pipelines — inject image tag)
  --set-string replicaCount=5 \
    # Force value to be a string (prevents YAML type coercion)
  --atomic \
    # If the install fails (pods not Ready within --timeout), auto-rollback
    # CRITICAL for production upgrades — never leave a cluster in half-state
  --timeout 5m \
  --wait
    # Wait until all pods, services, PVCs are Ready before returning

# Idempotent install-or-upgrade (MOST COMMON in CI/CD)
helm upgrade --install my-api ./api-server-chart \
  --namespace production \
  --values ./environments/prod/values.yaml \
  --set image.tag="${IMAGE_TAG}" \
  --atomic \
  --timeout 5m
  # If release doesn't exist: install it
  # If release exists: upgrade it
  # This is the standard CI/CD deployment command

# Dry-run: simulate install/upgrade without touching the cluster
helm upgrade --install my-api ./api-server-chart \
  --values prod-values.yaml \
  --dry-run \
  --debug
  # Prints rendered YAML + computed values. Use to validate before deploying.

# List all releases
helm list --all-namespaces          # all namespaces
helm list --namespace production    # specific namespace
helm list --all                     # include failed/deleted releases

# Inspect a release
helm status my-api --namespace production
helm get values my-api --namespace production     # values used for this release
helm get values my-api --namespace production --all  # including defaults
helm get manifest my-api --namespace production   # rendered K8s manifests

# View release history
helm history my-api --namespace production
#   REVISION  STATUS      CHART               DESCRIPTION
#   1         superseded  api-server-1.3.0    Install complete
#   2         deployed    api-server-1.4.2    Upgrade complete

# Rollback to a previous revision
helm rollback my-api 1 --namespace production
  # Rolls back to revision 1. Creates a new revision entry (revision 3).
  # For atomic rollback: helm rollback --wait --timeout 5m

# Uninstall (delete release and all K8s resources it created)
helm uninstall my-api --namespace production
  # WARNING: this deletes Deployments, Services, ConfigMaps, etc.
  # It does NOT delete PVCs (data safety — you must delete those manually).
  # Add --keep-history to preserve release history for audit trail.


# ===========================================================
# SECTION 5: Helm Secrets — Encrypting Sensitive Values
# ===========================================================
# NEVER commit plaintext passwords to git in values files.
# Solution: helm-secrets plugin + sops (Mozilla Secrets OPerationS)
#
# sops encrypts YAML values using AWS KMS, GCP KMS, or age keys.
# Only the values (not keys) are encrypted, making diffs readable.
#
# Setup:
pip install sops                          # or: brew install sops
helm plugin install https://github.com/jkroepke/helm-secrets

# Create a secrets file (unencrypted, add to .gitignore):
# secrets.yaml:
#   db_password: "supersecret"
#   api_key: "sk-12345"

# Encrypt with AWS KMS:
sops --encrypt \
  --kms arn:aws:kms:us-east-1:123456789:key/abc-def \
  secrets.yaml > secrets.enc.yaml
  # Commit secrets.enc.yaml to git. The values are encrypted.
  # sops knows how to decrypt using the KMS key (via IAM role).

# Install with encrypted secrets:
helm secrets upgrade --install my-api ./api-server-chart \
  --values prod-values.yaml \
  --values secrets.enc.yaml
  # helm-secrets decrypts the file in memory, passes to helm, never writes to disk


# ===========================================================
# SECTION 6: Helm Hooks
# ===========================================================
# Hooks run Kubernetes Jobs at specific points in the release lifecycle.
# They use the annotation: "helm.sh/hook": pre-install
#
# Available hooks:
#   pre-install:   before any K8s resources are created (DB migration)
#   post-install:  after all resources are Running (smoke test, notification)
#   pre-upgrade:   before upgrade (schema migration, backup)
#   post-upgrade:  after upgrade (cache warmup, test)
#   pre-rollback:  before rollback
#   post-rollback: after rollback
#   pre-delete:    before uninstall (graceful shutdown, data export)
#   test:          run when `helm test` is called (integration test)
#
# Hook Job template annotation example:
#   annotations:
#     "helm.sh/hook": pre-upgrade
#     "helm.sh/hook-weight": "0"          # order multiple hooks (lower = first)
#     "helm.sh/hook-delete-policy": before-hook-creation
#       # Delete old hook Job before creating new one.
#       # Without this: Jobs collide on upgrade (same name already exists).
#       # Options: before-hook-creation, hook-succeeded, hook-failed
#
# Run tests after install:
helm test my-api --namespace production
  # Runs all pods/jobs annotated with "helm.sh/hook": test
  # Each test pod must exit 0 to pass


# ===========================================================
# SECTION 7: Kustomize vs Helm
# ===========================================================
# Both tools solve the "environment-specific K8s config" problem
# but with different philosophies:
#
# HELM:
#   + Packaging, versioning, sharing (Artifact Hub)
#   + Powerful templating (conditionals, loops, functions)
#   + Release management (install, upgrade, rollback, history)
#   - Templates can become complex and hard to read
#   - Go templating is NOT YAML during development (no validation)
#   USE FOR: publishing charts for others to use, complex apps with
#             many configuration knobs, apps with optional components
#
# KUSTOMIZE:
#   + Pure YAML — no templating, always valid K8s manifests
#   + Strategic merge patches and JSON patches
#   + Built into kubectl (kubectl apply -k ./overlays/prod)
#   + Clear diff: base vs overlay shows exactly what changes per env
#   - No release history or rollback mechanism
#   - Cannot conditionally include/exclude resources (no if/else)
#   USE FOR: environment-specific patches (resource sizes, replicas,
#             image tags), patching third-party Helm charts
#
# BEST PRACTICE — Use Both:
#   1. helm pull bitnami/postgres --untar    # download chart as YAML
#   2. Use kustomize overlay to patch the downloaded chart
#   OR
#   1. Use helm template to render chart → raw YAML
#   2. Apply kustomize overlays on top of rendered YAML
#
# Kustomize example directory structure:
#   k8s/
#   ├── base/                 # shared config (all environments)
#   │   ├── kustomization.yaml
#   │   ├── deployment.yaml
#   │   └── service.yaml
#   └── overlays/
#       ├── staging/
#       │   ├── kustomization.yaml   # references base, applies patches
#       │   └── patch-replicas.yaml  # replicas: 2
#       └── production/
#           ├── kustomization.yaml
#           └── patch-replicas.yaml  # replicas: 10

kubectl apply -k ./k8s/overlays/production
  # kubectl has kustomize built in since 1.14
  # No separate tool installation needed


# ===========================================================
# SECTION 8: Kubernetes Operators
# ===========================================================
# Operators implement the "Operator Pattern":
#   1. Define a Custom Resource Definition (CRD)
#      → extends the K8s API with a new resource type (e.g., PostgresCluster)
#   2. Deploy a controller (a Pod watching the CRD)
#      → controller's reconcile loop: watch → compare → act
#   3. Users create instances of the CRD
#      → controller creates and manages the actual K8s resources
#
# Why Operators beat raw StatefulSets for complex apps:
#   StatefulSet gives you: pods, volumes, ordered restart
#   Operator gives you:    all of above PLUS operational intelligence
#
# PostgreSQL Operator (CloudNativePG) example:
#   Without operator: StatefulSet + Patroni DaemonSet + HAProxy + CronJob for backups
#     = 300+ lines of YAML + operational runbooks + 3AM oncall rotations
#   With CNPG operator: 30 lines of YAML → operator manages everything
#
# Popular Operators and their use cases:
#
#   cert-manager:        TLS certificate lifecycle (Let's Encrypt, Vault, AWS ACM)
#                        CRDs: Certificate, ClusterIssuer, CertificateRequest
#
#   Prometheus Operator: Prometheus + Alertmanager lifecycle
#                        CRDs: ServiceMonitor, PrometheusRule, Prometheus, Alertmanager
#                        ServiceMonitor replaces manual scrape_configs
#
#   Strimzi:             Apache Kafka on K8s
#                        CRDs: Kafka, KafkaTopic, KafkaUser, KafkaConnect
#                        Handles: rolling upgrades, config changes, topic management
#
#   CloudNativePG:       PostgreSQL HA clusters
#                        CRDs: Cluster, Backup, ScheduledBackup, Pooler (PgBouncer)
#                        Handles: replication, failover, backups, PITR, scaling
#
#   Redis Operator:      Redis Sentinel or Redis Cluster
#                        (several operators available: Spotahome, OpsTree)
#
#   Argo CD:             GitOps continuous delivery
#                        CRDs: Application, AppProject, ApplicationSet

# Install cert-manager operator:
helm install cert-manager cert-manager/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.13.0 \
  --set installCRDs=true
    # installCRDs=true: let Helm install the CRDs
    # Alternative: kubectl apply -f https://github.com/.../cert-manager.crds.yaml
    # Production tip: manage CRDs separately from the operator chart
    # so CRD upgrades don't accidentally wipe custom resources

# Install CloudNativePG operator:
helm install cnpg cnpg/cloudnative-pg \
  --namespace cnpg-system \
  --create-namespace \
  --version 0.18.0

# Install Strimzi Kafka operator:
helm install strimzi-operator oci://quay.io/strimzi-helm-charts/strimzi-kafka-operator \
  --namespace strimzi-system \
  --create-namespace


# ===========================================================
# SECTION 9: CloudNativePG — Operator vs StatefulSet Comparison
# ===========================================================
# This section shows WHY an operator beats a raw StatefulSet
# for PostgreSQL specifically.
#
# RAW STATEFULSET APPROACH — what you'd have to manage yourself:
#   - Write StatefulSet with postgres:15 container
#   - Configure Patroni (DCS: etcd or consul required)
#   - Write a HAProxy or Pgpool config for read routing
#   - Create a CronJob for pg_basebackup to S3
#   - Write a script to handle PITR restore from S3
#   - Write liveness/readiness probes that check Patroni status
#   - Handle TLS certificate rotation manually
#   - Write runbook for manual failover if Patroni fails
#   Total: 500+ lines YAML, external etcd dependency, custom scripts
#
# CNPG OPERATOR APPROACH — apply this Cluster CR:
# (Shown as comment since it's a K8s resource not a shell command)
#
# apiVersion: postgresql.cnpg.io/v1
# kind: Cluster
# metadata:
#   name: postgres-prod
#   namespace: production
# spec:
#   instances: 3
#   primaryUpdateStrategy: unsupervised   # automatic failover
#   storage:
#     size: 100Gi
#     storageClass: ssd
#   backup:
#     target: prefer-standby              # backup from replica, not primary
#     retentionPolicy: 30d
#     barmanObjectStore:
#       destinationPath: s3://my-backups/postgres/
#       s3Credentials:
#         accessKeyId:
#           name: s3-creds
#           key: ACCESS_KEY_ID
#         secretAccessKey:
#           name: s3-creds
#           key: SECRET_ACCESS_KEY
#   monitoring:
#     enablePodMonitor: true              # auto-creates Prometheus ServiceMonitor
#
# The operator handles: replica setup, WAL archiving to S3, automatic
# failover on primary failure (< 30 seconds), TLS between nodes, PgBouncer
# connection pooling, PITR recovery, backup scheduling, Prometheus metrics.
#
# Apply it:
kubectl apply -f postgres-cluster.yaml

# Check cluster status:
kubectl get cluster postgres-prod -n production
kubectl describe cluster postgres-prod -n production

# Trigger a manual failover (promote a specific replica):
kubectl cnpg promote postgres-prod postgres-prod-2 -n production

# Take an on-demand backup:
kubectl cnpg backup postgres-prod -n production

# List backups:
kubectl get backup -n production


# ===========================================================
# SECTION 10: Operator SDK — Building Your Own Operator
# ===========================================================
# Use Operator SDK to scaffold an operator in Go or Ansible.
# Only build custom operators for genuinely novel operational logic.
# Before building: check operatorhub.io — someone may have already done it.
#
# Reconcile loop (the heart of every operator):
#   func (r *MyReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
#     // 1. Fetch the custom resource
#     cr := &myv1.MyResource{}
#     r.Get(ctx, req.NamespacedName, cr)
#
#     // 2. Compare desired state (cr.Spec) vs actual state (cluster)
#     actual := &appsv1.Deployment{}
#     r.Get(ctx, namespacedName, actual)
#
#     // 3. Reconcile: create/update/delete to match desired state
#     if !reflect.DeepEqual(actual.Spec, desired.Spec) {
#       r.Update(ctx, desired)
#     }
#
#     // 4. Return: Requeue after X duration or on next watch event
#     return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
#   }
#
# Scaffold a new operator:
operator-sdk init --domain=company.io --repo=github.com/company/my-operator
operator-sdk create api --group=apps --version=v1 --kind=MyApp --resource --controller

# The SDK generates:
#   api/v1/myapp_types.go      → Go struct for your CRD spec/status
#   controllers/myapp_controller.go → reconcile loop skeleton
#   config/crd/                → generated CRD YAML
#   config/rbac/               → RBAC for your controller

# Build and push operator image:
make docker-build docker-push IMG="mycompany/my-operator:v0.1.0"

# Deploy operator to cluster:
make deploy IMG="mycompany/my-operator:v0.1.0"

# Generate CRD YAML (for distribution):
make manifests
