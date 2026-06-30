#!/usr/bin/env bash
# ============================================================
# L01: Kubernetes Core Concepts — From Zero to Understanding
# ============================================================
# WHAT: Kubernetes (K8s) is a container orchestration platform.
#       It automates deployment, scaling, healing, and networking
#       of containerized workloads across a cluster of machines.
# WHY:  Without orchestration, running 1000 containers across
#       50 servers manually is impossible. K8s handles scheduling,
#       restarts, load balancing, and rollouts automatically.
# LEVEL: Foundations
# ============================================================
# CONCEPT OVERVIEW:
#   Before Kubernetes, teams ran VMs, SSHed into boxes, and
#   managed deployments with bash scripts. Containers (Docker)
#   solved the "works on my machine" problem, but you still
#   needed something to run them at scale. That is Kubernetes.
#
#   Think of Kubernetes like an operating system for your
#   datacenter: the cluster is the computer, nodes are the CPU
#   cores, and pods are the processes.
#
# PRODUCTION USE CASE:
#   Spotify, Airbnb, and GitHub run millions of pods on K8s.
#   A single K8s cluster can manage tens of thousands of nodes
#   and run workloads handling millions of requests per second.
#
# COMMON MISTAKES:
#   - Treating K8s like a VM manager (it is not)
#   - Ignoring namespaces and running everything in "default"
#   - Not understanding the control plane vs data plane split
# ============================================================


# ============================================================
# SECTION 1: THE CLUSTER — THE FUNDAMENTAL UNIT
# ============================================================
# A Kubernetes CLUSTER is made of two kinds of machines:
#
#   CONTROL PLANE (the brain):
#     - Decides WHAT runs WHERE
#     - Stores all cluster state
#     - Exposes the API
#     - You never run your app workloads here
#
#   WORKER NODES (the muscle):
#     - Actually run your containers (pods)
#     - Report status back to the control plane
#     - Managed by kubelet
#
# In production: control plane is usually 3 nodes for HA
# (High Availability). If one control plane node dies,
# the cluster keeps working. With 1 control plane node,
# a crash means no scheduling, no scaling, no deploys.
# ============================================================


# ============================================================
# SECTION 2: CONTROL PLANE COMPONENTS
# ============================================================

# --- API SERVER (kube-apiserver) ---
# The front door to Kubernetes. Every single operation —
# kubectl commands, controllers, schedulers — goes through
# the API server. It validates and persists to etcd.
# REST API. Stateless. Horizontally scalable.
# If the API server is down, nothing new can happen.
# Existing pods keep running, but you cannot change anything.

# --- etcd ---
# The distributed key-value store where ALL cluster state lives.
# This is the source of truth. Every object (pod, service,
# deployment, configmap) is stored here as JSON.
#
# etcd uses the Raft consensus algorithm — it needs a quorum
# (majority) of nodes to be up to accept writes.
# 3 etcd nodes: can lose 1    (needs 2/3 = quorum)
# 5 etcd nodes: can lose 2    (needs 3/5 = quorum)
#
# CRITICAL: Back up etcd regularly. Losing etcd means losing
# the entire cluster state. AWS EKS manages this for you.

# --- SCHEDULER (kube-scheduler) ---
# Watches for unscheduled pods and assigns them to nodes.
# It considers: node resources (CPU/memory available),
# node selectors, affinity rules, taints/tolerations,
# pod topology spread constraints.
#
# Scheduling is a PROPOSAL: the scheduler writes the node
# name onto the pod spec. The kubelet on that node then
# actually starts the container.

# --- CONTROLLER MANAGER (kube-controller-manager) ---
# Runs a loop of controllers, each watching cluster state
# and reconciling it toward the desired state.
#
# Examples:
#   ReplicaSet controller: "You want 3 pods? I see 2. Adding 1."
#   Node controller:       "Node X hasn't responded in 5 min. Mark NotReady."
#   Job controller:        "This job is done. Clean up."
#
# This reconciliation loop is the core Kubernetes pattern.
# It is idempotent and self-healing by design.


# ============================================================
# SECTION 3: WORKER NODE COMPONENTS
# ============================================================

# --- kubelet ---
# The agent on every worker node. It:
#   1. Registers the node with the API server
#   2. Watches for pods assigned to this node
#   3. Tells the container runtime (containerd) to start them
#   4. Reports pod health back to the API server
#   5. Runs liveness/readiness probes
#
# If a container crashes, kubelet restarts it (based on restartPolicy).

# --- kube-proxy ---
# Runs on every node. Manages network rules (iptables or ipvs)
# so that Service IPs route to the correct pods.
# When you hit a ClusterIP service, kube-proxy's rules
# load balance that to one of the backing pods.

# --- Container Runtime ---
# containerd (the standard) or CRI-O. This is what actually
# pulls images and runs containers. Docker is no longer used
# as a K8s runtime (deprecated since K8s 1.20).


# ============================================================
# SECTION 4: CORE KUBERNETES OBJECTS
# ============================================================

# --- POD ---
# The smallest deployable unit in Kubernetes.
# A pod wraps one or more containers that share:
#   - Network namespace (same IP, can talk via localhost)
#   - Storage volumes
#   - Lifecycle (scheduled, started, stopped together)
#
# WHY: The pod abstraction lets you co-locate a main app
# container with helper sidecars (logging, proxies) while
# keeping them tightly coupled but separately defined.
#
# NEVER run bare pods in production. If the node dies,
# the pod is gone. Use Deployments which create ReplicaSets
# which create and manage pods.

# --- REPLICASET ---
# Ensures N replicas of a pod template are running.
# If a pod dies, the ReplicaSet controller creates a new one.
# You rarely create ReplicaSets directly — Deployments do it.

# --- DEPLOYMENT ---
# Manages ReplicaSets to provide rolling updates and rollbacks.
# "I want version 2 of my app running with 5 replicas."
# The Deployment creates a new ReplicaSet for v2, scales it up
# while scaling down the old v1 ReplicaSet. Zero downtime.

# --- SERVICE ---
# A stable network endpoint for a set of pods.
# Pods come and go (IPs change). Services give you a fixed
# DNS name and IP that load balances to healthy pods.
# Types: ClusterIP, NodePort, LoadBalancer, ExternalName.
# (Deep dive in L03)

# --- INGRESS ---
# Layer 7 (HTTP/HTTPS) routing into the cluster.
# "Route /api to service A, /web to service B, on host foo.com"
# Requires an Ingress Controller (nginx, traefik, etc).

# --- NAMESPACE ---
# Virtual cluster within a cluster. Used to isolate:
#   - Teams (team-a, team-b)
#   - Environments (dev, staging) — though separate clusters
#     are better for prod isolation
#   - System workloads (kube-system, monitoring)
#
# RBAC, NetworkPolicies, and ResourceQuotas are namespace-scoped.
# Do NOT use the default namespace in production.

# --- CONFIGMAP ---
# Non-sensitive configuration data as key-value pairs.
# Decouples config from the container image.
# (Deep dive in L04)

# --- SECRET ---
# Like ConfigMap but for sensitive data.
# Base64 encoded. NOT encrypted by default. Use Sealed Secrets
# or External Secrets Operator for real security. (L04)


# ============================================================
# SECTION 5: CLUSTER SETUP OPTIONS
# ============================================================

# --- LOCAL DEVELOPMENT ---

# minikube: Single-node cluster in a VM or Docker container.
# Best for beginners. Includes addons (ingress, metrics-server).
minikube start --cpus=4 --memory=8192 --kubernetes-version=v1.30.0

# kind (Kubernetes IN Docker): Multi-node cluster using Docker.
# Faster than minikube. Great for CI/CD pipelines and
# testing multi-node scenarios locally.
# kind create cluster --config kind-config.yaml

# k3d: k3s (lightweight K8s) running in Docker. Very fast.
# Great for local testing of production-like configs.

# --- MANAGED CLOUD (PRODUCTION CHOICE) ---

# EKS (AWS): Managed control plane. You manage worker nodes
#            (EC2 or Fargate). Deep AWS integration.
# GKE (GCP): Gold standard. Autopilot mode manages nodes too.
#            Best autoscaling, cheapest control plane.
# AKS (Azure): Best for Microsoft/Windows shops.
#              Good Active Directory integration.

# For millions of users: USE MANAGED KUBERNETES.
# Managing the control plane yourself is a full-time job.
# EKS/GKE/AKS handle etcd backups, control plane HA,
# K8s version upgrades (with proper tooling).


# ============================================================
# SECTION 6: KUBECTL — YOUR PRIMARY TOOL
# ============================================================
# kubectl talks to the API server. It reads ~/.kube/config
# which has cluster credentials and contexts.
# A CONTEXT = cluster + user + namespace.

# --- CONTEXT MANAGEMENT ---
kubectl config get-contexts                    # List all contexts (clusters)
kubectl config current-context                 # Which cluster am I talking to?
kubectl config use-context my-production-cluster  # Switch cluster
# WARNING: Always confirm your context before running
# destructive commands. Deleting in prod is bad.

# --- GETTING INFORMATION ---
kubectl get pods                               # List pods in current namespace
kubectl get pods -n kube-system               # List pods in kube-system namespace
kubectl get pods --all-namespaces             # All pods in all namespaces
kubectl get pods -o wide                       # Include node, IP info
kubectl get pods -o yaml                       # Full YAML output
kubectl get pods --watch                       # Stream updates in real time

kubectl get all                                # Pods, services, deployments, etc
kubectl get nodes                              # List cluster nodes + status
kubectl get nodes -o wide                      # Node IPs, OS, container runtime

# --- INSPECTING RESOURCES ---
kubectl describe pod my-pod                    # Full details: events, conditions
kubectl describe node my-node                  # Node capacity, allocated resources
# 'describe' is your best friend for debugging.
# The Events section at the bottom shows WHAT went wrong.
# "ImagePullBackOff" → wrong image name or registry creds.
# "OOMKilled" → container exceeded memory limit.
# "Pending" → can't schedule: no nodes with enough resources.

# --- APPLYING AND DELETING ---
kubectl apply -f deployment.yaml               # Create or update resource
kubectl apply -f ./manifests/                  # Apply all YAMLs in directory
kubectl apply -k ./kustomize/                  # Apply kustomization

kubectl delete -f deployment.yaml             # Delete resource from file
kubectl delete pod my-pod                      # Delete specific pod
kubectl delete pod my-pod --grace-period=0    # Force delete (last resort)
# NOTE: 'apply' is declarative (desired state).
#       'create' is imperative (one-time creation).
#       Always use 'apply' in production workflows.

# --- DEBUGGING ---
kubectl logs my-pod                            # Stdout logs of the pod
kubectl logs my-pod -c my-container           # Logs of specific container in pod
kubectl logs my-pod --previous                 # Logs from the previous crashed container
kubectl logs my-pod -f                         # Stream (follow) logs
kubectl logs -l app=my-app --tail=100         # Logs from all pods matching label

kubectl exec -it my-pod -- /bin/sh            # Interactive shell in container
kubectl exec my-pod -- curl localhost:8080    # Run command without interactive shell
# WARNING: 'exec' into prod pods only for emergencies.
# It can change running state. Prefer logging/tracing.

kubectl port-forward pod/my-pod 8080:80       # Forward local:8080 → pod:80
kubectl port-forward svc/my-service 8080:80   # Forward to service
# port-forward is for LOCAL debugging only.
# Never expose this to other users.

# --- EDITING LIVE RESOURCES (CAREFUL) ---
kubectl edit deployment my-deployment         # Opens in $EDITOR. Saves on close.
kubectl patch deployment my-deployment \
  -p '{"spec":{"replicas":5}}'               # Patch specific field
# For production changes, ALWAYS update your manifest
# files and use 'kubectl apply'. Editing live is fine
# for emergencies but creates drift from git state.

# --- RESOURCE SHORTCUTS ---
# po = pods, svc = services, deploy = deployments
# cm = configmaps, pv = persistentvolumes, pvc = persistentvolumeclaims
# ns = namespaces, no = nodes, sa = serviceaccounts
kubectl get po,svc,deploy -n production        # Multiple resource types at once


# ============================================================
# SECTION 7: THE KUBERNETES WAY — DECLARATIVE PHILOSOPHY
# ============================================================
# Kubernetes is DECLARATIVE: you describe the desired state,
# K8s figures out how to get there.
#
# You do NOT say: "Start container A on node 3, then start
# container B on node 7, then create a route."
#
# You say: "I want 3 replicas of app A and 2 replicas of app B,
# accessible on this DNS name, with these resource limits."
#
# K8s continuously reconciles actual state → desired state.
# This is why K8s is self-healing: if a pod dies, the
# controller sees divergence and creates a new pod.
#
# IMPLICATION: Store all your K8s manifests in Git.
# This is Infrastructure as Code. GitOps (ArgoCD/Flux)
# takes this further: Git becomes the source of truth,
# and K8s automatically syncs to whatever is in git.
# ============================================================

echo "L01 Complete: You now understand what Kubernetes is and how it works."
echo "Next: L02 — Pods and Deployments (the workload layer)"
