#!/usr/bin/env bash
# =============================================================================
# KUBERNETES CHEATSHEET — In-Depth Reference
# kubectl, contexts/namespaces, workloads, debugging, Helm, Kustomize.
# Read top-to-bottom; run individually.
# =============================================================================


# =============================================================================
# 1. CONTEXTS, CLUSTERS & NAMESPACES
# =============================================================================

kubectl config get-contexts               # List available contexts
kubectl config current-context              # Show active context
kubectl config use-context my-cluster         # Switch context
kubectl config set-context --current --namespace=my-ns  # Default namespace for current context
kubectl config view                              # Show merged kubeconfig
kubectl cluster-info                               # Show control plane / service endpoints
kubectl version                                      # Client + server version

kubectl get namespaces                       # List namespaces
kubectl create namespace my-ns                 # Create a namespace
kubectl delete namespace my-ns                   # Delete a namespace (and everything in it)
kubectl get pods -n my-ns                          # Scope any command with -n / --namespace
kubectl get pods --all-namespaces                    # Across all namespaces (-A shorthand)


# =============================================================================
# 2. GET, DESCRIBE, EXPLAIN — THE CORE LOOP
# =============================================================================

kubectl get pods                          # List pods in current namespace
kubectl get pods -o wide                    # Include node, IP, etc.
kubectl get pods -w                           # Watch for live changes
kubectl get pods --show-labels                  # Include labels column
kubectl get pods -l app=web                       # Filter by label selector
kubectl get pods --field-selector=status.phase=Running

kubectl get all                              # Pods, services, deployments, etc. at once
kubectl get deploy,svc,ing                     # Multiple resource types in one call
kubectl get pod my-pod -o yaml                   # Full resource manifest as-applied
kubectl get pod my-pod -o json | jq '.status'      # Pipe to jq for scripting

kubectl describe pod my-pod                  # Human-readable detail + recent Events
kubectl describe node my-node                  # Node capacity, conditions, allocated resources
kubectl explain pod.spec.containers              # Inline API field documentation
kubectl explain deployment.spec --recursive        # Full field tree for a resource kind

kubectl api-resources                         # List all resource types the cluster supports
kubectl api-versions                            # List all supported API versions


# =============================================================================
# 3. CREATING & APPLYING RESOURCES
# =============================================================================

kubectl apply -f deployment.yaml            # Create or update (declarative — preferred)
kubectl apply -f ./manifests/                  # Apply every file in a directory
kubectl apply -f https://example.com/app.yaml    # Apply directly from a URL
kubectl apply -f deployment.yaml --dry-run=client -o yaml  # Preview without applying
kubectl diff -f deployment.yaml                    # Show what apply WOULD change

kubectl create deployment nginx --image=nginx  # Imperative — quick one-liners, not for prod
kubectl create -f pod.yaml                        # Create only (errors if it already exists)
kubectl replace -f pod.yaml                          # Replace entire object (full overwrite)

kubectl delete -f deployment.yaml           # Delete by manifest
kubectl delete pod my-pod                     # Delete a specific pod
kubectl delete pod my-pod --grace-period=0 --force  # Force delete (use sparingly — can leak resources)
kubectl delete pods -l app=web                    # Delete by label selector
kubectl delete all --all -n my-ns                    # Wipe every resource in a namespace

kubectl label pod my-pod env=prod            # Add/update a label
kubectl label pod my-pod env-                  # Remove a label
kubectl annotate pod my-pod note="reviewed"      # Add/update an annotation


# =============================================================================
# 4. WORKLOADS: DEPLOYMENTS, REPLICASETS, DAEMONSETS, JOBS
# =============================================================================

kubectl get deployments                       # List deployments
kubectl rollout status deployment/my-app         # Watch a rollout to completion
kubectl rollout history deployment/my-app          # List revision history
kubectl rollout history deployment/my-app --revision=3  # Detail of one revision
kubectl rollout undo deployment/my-app               # Roll back to the previous revision
kubectl rollout undo deployment/my-app --to-revision=2 # Roll back to a specific revision
kubectl rollout restart deployment/my-app              # Force new pods (e.g. to pick up a Secret change)
kubectl rollout pause deployment/my-app                  # Pause mid-rollout
kubectl rollout resume deployment/my-app                   # Resume

kubectl scale deployment/my-app --replicas=5      # Manual scale
kubectl autoscale deployment/my-app --min=2 --max=10 --cpu-percent=70  # Quick HPA

kubectl set image deployment/my-app app=myrepo/app:2.0  # Update image (triggers rolling update)
kubectl edit deployment my-app                              # Open live resource in $EDITOR

kubectl get replicasets                        # ReplicaSets (usually managed via Deployments, not directly)
kubectl get daemonsets                            # One pod per node (log agents, CNI, monitoring)
kubectl get statefulsets                            # Stable identity + storage (databases, queues)

kubectl create job my-job --image=busybox -- echo hi  # One-off Job
kubectl get jobs                                          # List Jobs
kubectl create cronjob my-cron --image=busybox --schedule="*/5 * * * *" -- echo hi
kubectl get cronjobs                                          # List CronJobs


# =============================================================================
# 5. SERVICES & NETWORKING
# =============================================================================

kubectl get services                        # List services (svc)
kubectl expose deployment my-app --port=80 --target-port=8080 --type=ClusterIP
kubectl expose deployment my-app --type=LoadBalancer --port=80

# Service types:
#   ClusterIP    -> internal-only, default
#   NodePort     -> exposes a static port on every node (30000-32767)
#   LoadBalancer -> provisions a cloud LB (AWS ELB / Azure LB / GCP LB)
#   ExternalName -> DNS CNAME alias to an external service, no proxying

kubectl get ingress                          # List Ingress resources
kubectl describe ingress my-ingress             # Rules, backends, TLS config

kubectl get endpoints                          # Show which pod IPs back a Service
kubectl get networkpolicies                       # List NetworkPolicies (pod-to-pod firewall rules)

kubectl port-forward pod/my-pod 8080:80        # Forward localhost:8080 -> pod:80
kubectl port-forward svc/my-svc 8080:80          # Same, but targeting a Service
kubectl port-forward deployment/my-app 8080:80     # Same, targeting a Deployment (picks one pod)


# =============================================================================
# 6. CONFIGURATION: CONFIGMAPS & SECRETS
# =============================================================================

kubectl create configmap my-config --from-literal=KEY=value
kubectl create configmap my-config --from-file=app.properties
kubectl create configmap my-config --from-env-file=.env
kubectl get configmaps
kubectl describe configmap my-config

kubectl create secret generic my-secret --from-literal=PASSWORD=s3cr3t
kubectl create secret docker-registry my-registry-secret \
  --docker-server=myregistry.io --docker-username=user --docker-password=pass
kubectl create secret tls my-tls-secret --cert=tls.crt --key=tls.key
kubectl get secrets
kubectl get secret my-secret -o jsonpath='{.data.PASSWORD}' | base64 -d  # Decode a value

# Secrets are base64-encoded, NOT encrypted at rest by default — enable etcd
# encryption at rest, or use Sealed Secrets / External Secrets Operator / Vault
# for anything sensitive in a real cluster.


# =============================================================================
# 7. STORAGE: PV, PVC, STORAGECLASS
# =============================================================================

kubectl get pv                              # PersistentVolumes (cluster-wide storage)
kubectl get pvc                               # PersistentVolumeClaims (namespace-scoped requests)
kubectl describe pvc my-claim                    # Bound status, capacity, access modes
kubectl get storageclass                            # Available dynamic-provisioning classes
kubectl delete pvc my-claim                            # Delete a claim (may leave PV depending on reclaim policy)

# Access modes: ReadWriteOnce (single node), ReadOnlyMany, ReadWriteMany (needs
# a networked backend like NFS/EFS/Azure Files), ReadWriteOncePod (K8s 1.22+).


# =============================================================================
# 8. DEBUGGING & TROUBLESHOOTING
# =============================================================================

kubectl logs my-pod                          # Pod logs
kubectl logs -f my-pod                          # Follow live
kubectl logs my-pod -c container-name              # Specific container in a multi-container pod
kubectl logs my-pod --previous                        # Logs from the PREVIOUS crashed instance
kubectl logs -l app=web --all-containers --tail=50       # Aggregate across matching pods

kubectl exec -it my-pod -- bash              # Shell into a pod
kubectl exec -it my-pod -c container-name -- sh  # Target a specific container
kubectl exec my-pod -- env                      # One-off command

kubectl debug my-pod -it --image=busybox --target=my-container  # Ephemeral debug container (no restart needed)
kubectl debug node/my-node -it --image=busybox    # Debug a node via a privileged pod

kubectl get events                            # Cluster-wide recent events
kubectl get events --sort-by=.lastTimestamp     # Chronological
kubectl get events --field-selector involvedObject.name=my-pod

kubectl top pods                              # CPU/memory usage per pod (needs metrics-server)
kubectl top nodes                                # CPU/memory usage per node

# Common pod states and what to check:
#   Pending          -> kubectl describe pod (unschedulable: resources, taints, PVC not bound)
#   ImagePullBackOff -> wrong image name/tag, missing registry credentials (imagePullSecrets)
#   CrashLoopBackOff -> kubectl logs --previous; app is exiting, check startup/liveness probe
#   OOMKilled        -> check `kubectl describe pod` Last State reason; raise memory limits or fix a leak
#   Evicted          -> node ran out of resources; check node conditions and pod QoS class


# =============================================================================
# 9. RESOURCE MANAGEMENT: REQUESTS, LIMITS, QOS
# =============================================================================

cat <<'EOF'
resources:
  requests:
    cpu: "250m"        # 0.25 vCPU — used for scheduling decisions
    memory: "256Mi"
  limits:
    cpu: "500m"          # Hard cap; CPU throttles, doesn't kill
    memory: "512Mi"       # Hard cap; memory over-limit -> OOMKilled
EOF

# QoS classes (derived automatically, not set directly):
#   Guaranteed -> requests == limits for every resource, every container
#   Burstable  -> requests set, but requests != limits
#   BestEffort -> no requests/limits set at all (first to be evicted under pressure)

kubectl describe node my-node | grep -A5 "Allocated resources"  # See scheduling pressure


# =============================================================================
# 10. PROBES: LIVENESS, READINESS, STARTUP
# =============================================================================

cat <<'EOF'
livenessProbe:                        # Restarts the container if it fails
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 10
readinessProbe:                        # Removes pod from Service endpoints if it fails
  httpGet:
    path: /ready
    port: 8080
  periodSeconds: 5
startupProbe:                            # Delays liveness checks until slow-starting apps are ready
  httpGet:
    path: /healthz
    port: 8080
  failureThreshold: 30
  periodSeconds: 5
EOF


# =============================================================================
# 11. AUTOSCALING & DISRUPTION BUDGETS
# =============================================================================

kubectl get hpa                              # HorizontalPodAutoscalers
kubectl describe hpa my-app-hpa                 # Current/target metrics, scaling events
kubectl get vpa                                   # VerticalPodAutoscaler (needs VPA installed)
kubectl get pdb                                      # PodDisruptionBudgets

# Cluster Autoscaler adjusts NODE count based on unschedulable pods.
# HPA adjusts POD replica count based on CPU/memory/custom metrics.
# VPA adjusts POD resource requests/limits in place (or via recreation).
# KEDA extends HPA to scale on external event sources (queue depth, Kafka lag, etc).

cat <<'EOF'
# --- PodDisruptionBudget example ---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app-pdb
spec:
  minAvailable: 2          # or maxUnavailable: 1
  selector:
    matchLabels:
      app: my-app
EOF


# =============================================================================
# 12. RBAC, SERVICE ACCOUNTS & SECURITY CONTEXT
# =============================================================================

kubectl get serviceaccounts                  # List ServiceAccounts
kubectl get roles,rolebindings -n my-ns          # Namespace-scoped RBAC
kubectl get clusterroles,clusterrolebindings        # Cluster-wide RBAC
kubectl auth can-i create pods --namespace=my-ns       # Check current user's permission
kubectl auth can-i create pods --as=system:serviceaccount:my-ns:my-sa  # Check as another identity

cat <<'EOF'
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
EOF


# =============================================================================
# 13. HELM
# =============================================================================

helm repo add bitnami https://charts.bitnami.com/bitnami   # Add a chart repo
helm repo update                                              # Refresh repo indexes
helm search repo nginx                                          # Search available charts

helm install my-release bitnami/nginx                # Install a chart
helm install my-release ./my-chart -f values.yaml       # Install a local chart with custom values
helm upgrade my-release ./my-chart                         # Upgrade an existing release
helm upgrade --install my-release ./my-chart                 # Install if absent, upgrade if present
helm rollback my-release 1                                      # Roll back to revision 1
helm uninstall my-release                                          # Remove a release

helm list                              # List releases in current namespace
helm list -A                             # Across all namespaces
helm status my-release                     # Current state + notes
helm history my-release                      # Revision history
helm get values my-release                     # Show values currently in use
helm get manifest my-release                      # Show rendered K8s manifests

helm template ./my-chart                       # Render manifests locally, no install (great for review)
helm lint ./my-chart                             # Validate chart structure/syntax
helm create my-chart                               # Scaffold a new chart

# Chart anatomy: Chart.yaml (metadata), values.yaml (defaults),
# templates/ (Go-templated manifests), charts/ (subchart dependencies).


# =============================================================================
# 14. KUSTOMIZE
# =============================================================================

kubectl apply -k ./overlays/production      # Apply a kustomization directory
kustomize build ./overlays/production          # Render final manifests without applying

cat <<'EOF'
# --- base/kustomization.yaml ---
resources:
  - deployment.yaml
  - service.yaml

# --- overlays/production/kustomization.yaml ---
resources:
  - ../../base
patches:
  - path: replica-patch.yaml
images:
  - name: myapp
    newTag: 1.4.0
EOF
# Kustomize composes plain YAML via overlays/patches — no templating language,
# often preferred over Helm for pure environment-diffing (dev/staging/prod).


# =============================================================================
# 15. GITOPS: ARGOCD BASICS (kubectl-adjacent CLI)
# =============================================================================

argocd app list                             # List managed applications
argocd app get my-app                          # Show sync/health status
argocd app sync my-app                            # Trigger a manual sync
argocd app diff my-app                              # Diff live state vs Git
argocd app rollback my-app 3                          # Roll back to a specific history ID
argocd app set my-app --sync-policy automated             # Enable auto-sync


# =============================================================================
# 16. PRODUCTION PATTERNS & CHEAT NOTES
# =============================================================================

# - Anti-affinity for HA: force replicas across nodes/zones
cat <<'EOF'
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchLabels:
            app: my-app
        topologyKey: kubernetes.io/hostname
EOF

# - Topology spread (softer, more flexible than strict anti-affinity):
cat <<'EOF'
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        app: my-app
EOF

# - Rolling update tuning:
cat <<'EOF'
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1          # Extra pods allowed during rollout
    maxUnavailable: 0      # Zero downtime — never drop below desired replica count
EOF

# - kubectl get pods -o custom-columns for fast triage:
kubectl get pods -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,NODE:.spec.nodeName

# - kubectl neat / stern / k9s are common third-party CLI companions:
#   stern my-app          -> tail logs across multiple pods with color-coded prefixes
#   k9s                   -> full-screen terminal UI for cluster navigation
