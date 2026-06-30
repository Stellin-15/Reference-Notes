#!/usr/bin/env bash

# ============================================================
# L07: Docker Security Best Practices
# ============================================================
# WHAT: Hardening techniques for Docker containers and images —
#       from non-root users and capability dropping to image
#       scanning and rootless Docker daemon.
# WHY:  A container is NOT a VM. The kernel is shared with the
#       host. A misconfigured container can be an easy path to
#       full host compromise. Security is not optional in prod.
# LEVEL: Advanced
# ============================================================
# CONCEPT OVERVIEW:
#   Container security is layered (defence in depth). No single
#   control is sufficient. Apply all layers:
#     1. Non-root USER in image
#     2. Read-only root filesystem
#     3. Drop Linux capabilities (principle of least privilege)
#     4. Block privilege escalation (no-new-privileges)
#     5. Seccomp: restrict allowed syscalls
#     6. AppArmor/SELinux: MAC (mandatory access control)
#     7. Minimal base image (distroless / alpine)
#     8. Image vulnerability scanning (Trivy, Snyk)
#     9. Runtime resource limits
#    10. Network isolation
#
# PRODUCTION USE CASE:
#   PCI-DSS, SOC2, and HIPAA all require demonstrable container
#   hardening. CIS Docker Benchmark is the industry standard
#   checklist. Running containers as root with full capabilities
#   is an automatic finding in any security audit.
#
# COMMON MISTAKES:
#   - Running as root (default if USER not set in Dockerfile).
#   - Mounting the Docker socket into a container — that container
#     becomes root on the host.
#   - Using :latest image tags (no reproducibility, may pull
#     vulnerable images silently).
#   - Storing secrets in ENV instructions (visible in history).
#   - Using --privileged for convenience — disables ALL security.
# ============================================================


# ============================================================
# SECTION 1: NON-ROOT USER
# ============================================================
# By default, Docker containers run as root (UID 0) inside
# the container. If that container also has a volume mounted
# from the host, the process is root on the host files.
# If --privileged is set (or the socket is mounted), root in
# container == root on host. Full compromise.
#
# Set USER in Dockerfile (shown as comments):
#
#   FROM python:3.12-slim
#   RUN groupadd --gid 1001 appuser && \
#       useradd --uid 1001 --gid appuser --no-create-home appuser
#   WORKDIR /app
#   COPY --chown=appuser:appuser . .
#   USER appuser          # <-- all subsequent RUN/CMD/ENTRYPOINT as this user
#   CMD ["uvicorn", "main:app"]
#
# Verify at runtime:
docker run --rm myapp:latest whoami    # should print: appuser, NOT root

# Override user at runtime if needed for debugging:
docker run --rm -u 0 myapp:latest whoami    # temporarily run as root


# ============================================================
# SECTION 2: READ-ONLY ROOT FILESYSTEM
# ============================================================
# --read-only makes the container's entire filesystem read-only.
# A process that achieves RCE cannot write malware, cannot modify
# binaries, cannot create new SUID binaries.
#
# The downside: many apps need SOME writable paths (/tmp, /var/run,
# socket files). Solve this with targeted tmpfs mounts.

docker run -d \
  --name hardened-api \
  --read-only \                    # immutable FS
  --tmpfs /tmp:size=32m \          # app's temp dir (in RAM)
  --tmpfs /var/run:size=8m \       # PID files, Unix sockets
  --tmpfs /var/log/nginx:size=16m \# nginx needs writable log dir
  -v /opt/config:/app/config:ro \
  myapp:latest

# Test that the filesystem is actually read-only:
docker run --rm --read-only myapp:latest \
  sh -c 'echo test > /test.txt' 2>&1
# Expected: /bin/sh: can't create /test.txt: Read-only file system


# ============================================================
# SECTION 3: DROP LINUX CAPABILITIES
# ============================================================
# Linux capabilities split root power into ~40 distinct privileges.
# Docker grants containers ~14 capabilities by default — far more
# than most apps need.
#
# PRINCIPLE OF LEAST PRIVILEGE: drop ALL, then add back ONLY what
# the app actually requires.
#
# Common capabilities:
#   NET_BIND_SERVICE — bind to ports < 1024 (e.g., port 80)
#   NET_ADMIN        — configure network interfaces
#   SYS_PTRACE       — attach to processes with ptrace (debuggers)
#   CHOWN            — change file ownership
#   DAC_OVERRIDE     — bypass file read/write/exec permission checks
#   SETUID           — change UID (sudo-like)
#   SYS_ADMIN        — huge catch-all; almost never needed; never grant
#
# Most web apps need ZERO capabilities (they run on high ports,
# don't touch kernel networking, don't change UIDs).

docker run -d \
  --name api \
  --cap-drop ALL \                      # drop every capability
  --cap-add NET_BIND_SERVICE \          # only add back what's needed
  --security-opt no-new-privileges:true \
  myapp:latest

# nginx on port 80 needs NET_BIND_SERVICE:
docker run -d \
  --name nginx \
  --cap-drop ALL \
  --cap-add NET_BIND_SERVICE \
  --cap-add CHOWN \                     # nginx needs to chown its workers
  --cap-add SETGID \                    # drop privileges from master to worker
  --cap-add SETUID \
  --security-opt no-new-privileges:true \
  nginx:alpine


# ============================================================
# SECTION 4: NO NEW PRIVILEGES
# ============================================================
# --security-opt no-new-privileges:true prevents any process
# inside the container from gaining MORE privileges than it
# started with — even via SETUID binaries (like su, sudo).
#
# Without this: a process running as appuser could exec /bin/su
# (SETUID root) and become root.
# With this:    the setuid bit is ignored. su fails immediately.
#
# This is a low-cost, high-value setting. ALWAYS enable it.

docker run -d \
  --security-opt no-new-privileges:true \
  myapp:latest


# ============================================================
# SECTION 5: SECCOMP (SYSCALL FILTERING)
# ============================================================
# Seccomp (Secure Computing Mode) restricts which Linux syscalls
# a process can make. The Docker default profile blocks ~44 of
# the ~435 syscalls — dangerous ones like: ptrace, mount,
# create_module, kexec_load, pivot_root.
#
# Custom profiles allow even tighter restrictions. Generate a
# profile with syscall tracing (strace/falco), then whitelist
# only what your app calls.
#
# Docker's default seccomp profile is already applied unless
# you explicitly disable it. Don't disable it unless you must.

# Apply default seccomp (already on by default — shown for clarity):
docker run --security-opt seccomp=/etc/docker/seccomp/default.json myapp:latest

# Apply a CUSTOM seccomp profile (whitelist only needed syscalls):
docker run \
  --security-opt seccomp=/opt/seccomp/myapp-profile.json \
  myapp:latest

# Disable seccomp (DANGEROUS — only for debugging):
docker run --security-opt seccomp=unconfined myapp:latest


# ============================================================
# SECTION 6: APPARMOR
# ============================================================
# AppArmor (Linux kernel security module) restricts what files,
# networks, and capabilities a process can access — at the MAC
# (mandatory access control) level, bypassing DAC entirely.
# Available on Ubuntu/Debian. SELinux is the RHEL/Fedora equiv.

# Docker applies docker-default AppArmor profile by default.
# To apply a custom profile (loaded via apparmor_parser first):
docker run \
  --security-opt apparmor=my-custom-profile \
  myapp:latest

# Disable AppArmor (debugging only):
docker run --security-opt apparmor=unconfined myapp:latest


# ============================================================
# SECTION 7: IMAGE SCANNING
# ============================================================
# Image scanners check:
#   - OS packages (apt, apk, rpm) for CVEs
#   - Language dependencies (pip, npm, Maven) for CVEs
#   - Dockerfile misconfigurations (running as root, COPY .)
#   - Secrets accidentally baked in (API keys in layers)
#
# Trivy (open-source, by Aqua Security) — recommended:
trivy image myapp:latest
# Or in CI, fail the pipeline if HIGH/CRITICAL CVEs found:
trivy image --exit-code 1 --severity HIGH,CRITICAL myapp:latest

# Scan a Dockerfile for misconfigs before building:
trivy config ./Dockerfile

# Snyk (SaaS, better IDE integration):
snyk container test myapp:latest

# Docker Scout (Docker's built-in scanner, requires login):
docker scout cves myapp:latest
docker scout recommendations myapp:latest   # suggest base image upgrades


# ============================================================
# SECTION 8: DISTROLESS AND MINIMAL IMAGES
# ============================================================
# Distroless images (Google's gcr.io/distroless/*) contain
# ONLY the app runtime — no shell, no package manager, no
# coreutils, no curl. Attack surface reduced to near zero.
#
# If there's no shell, an attacker who achieves RCE inside the
# container cannot run `apt install`, cannot `curl` a C2 server
# (no curl), cannot read /etc/passwd (no cat).
#
# Multi-stage build pattern:
#
#   # Stage 1: BUILD (fat image with build tools)
#   FROM python:3.12 AS builder
#   WORKDIR /app
#   COPY requirements.txt .
#   RUN pip install --prefix=/install -r requirements.txt
#
#   # Stage 2: PRODUCTION (distroless — no shell)
#   FROM gcr.io/distroless/python3-debian12
#   COPY --from=builder /install /usr/local
#   COPY --from=builder /app /app
#   WORKDIR /app
#   USER nonroot          # distroless provides nonroot (uid 65532)
#   CMD ["main.py"]       # no shell form possible — exec form only
#
# Result: final image is ~50MB instead of ~1GB. Zero CVEs from
# build toolchain. No interactive shell for attackers.

# Verify no shell in distroless image:
docker run --rm gcr.io/distroless/python3 /bin/sh 2>&1
# Expected: exec /bin/sh: no such file or directory


# ============================================================
# SECTION 9: SECRETS MANAGEMENT
# ============================================================
# DANGER RANKING (most to least dangerous):
#
#   1. ENV in Dockerfile      — baked into image, visible in
#                               `docker history`, stays in ALL
#                               image layers forever.
#   2. --env / -e at runtime  — visible in `docker inspect`,
#                               in /proc/1/environ on the host.
#   3. Bind-mounted secret file — host controls the file, but
#                               file path may be predictable.
#   4. Environment via env_file — same as #2 but easier to
#                               manage. Don't commit the file.
#   5. tmpfs mount            — in RAM only, never on disk,
#                               not in image layers.
#   6. Docker secrets (Swarm)  — encrypted in Raft log,
#                               mounted as tmpfs at runtime.
#                               BEST for Swarm.
#   7. HashiCorp Vault / AWS   — external secret store with
#      Secrets Manager           audit trail. BEST for K8s/cloud.

# WRONG: never do this in a Dockerfile
#   ENV DATABASE_PASSWORD=supersecret123
#   ARG SECRET_KEY=abc123       # visible in: docker history myimage

# RIGHT: Docker secret at runtime
#   echo "supersecret123" | docker secret create db_password -
#   docker service create --secret db_password myapp:latest
#   # Secret available at: /run/secrets/db_password (tmpfs)


# ============================================================
# SECTION 10: DOCKER CONTENT TRUST (IMAGE SIGNING)
# ============================================================
# DOCKER_CONTENT_TRUST=1 enables Notary-based image signing.
# Docker will REFUSE to pull unsigned images.
# Protects against supply chain attacks and registry tampering.

export DOCKER_CONTENT_TRUST=1
docker pull nginx:alpine      # will fail if image is not signed
docker push myregistry/myapp:1.0.0   # will sign on push

# In CI, set this globally. In prod, enforce via Docker daemon config.
# /etc/docker/daemon.json:
# { "content-trust": { "mode": "enforced" } }


# ============================================================
# SECTION 11: ROOTLESS DOCKER
# ============================================================
# The Docker DAEMON itself runs as root by default. The daemon
# process can do anything on the host. If it's compromised
# (via API exposure or socket access), the attacker owns the host.
#
# Rootless Docker: the daemon runs as the current user.
# A compromised daemon can only do what that user can do.
#
# Setup (Linux, Docker 20.10+):
dockerd-rootless-setuptool.sh install   # one-time setup per user
# Then start the daemon:
systemctl --user start docker
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
# All docker commands now talk to the rootless daemon.
#
# Limitations: some features unavailable (port binding < 1024
# requires kernel capability, limited storage drivers).


# ============================================================
# SECTION 12: NETWORK ISOLATION
# ============================================================
# --network host: container shares the host's network namespace.
# The container sees ALL host network interfaces. A compromised
# container can port-scan and attack the host's localhost services
# (Kubernetes API server, cloud metadata endpoint 169.254.169.254).

# NEVER use --network host unless absolutely required.
# (Performance-critical UDP workloads sometimes need it.)

# Default bridge: containers get their own network, can reach
# internet via NAT, isolated from each other (unless on same
# user-defined network).
docker run --network bridge myapp:latest   # default, fine

# Custom bridge: better than default bridge because containers
# can address each other by name (DNS resolution).
docker network create myapp-net
docker run --network myapp-net --name api myapp:latest
docker run --network myapp-net --name worker myapp:latest
# worker can reach api at http://api:8000


# ============================================================
# SECTION 13: RESOURCE LIMITS (DoS PREVENTION)
# ============================================================
# A compromised or buggy container can consume all host CPU/RAM,
# crashing other containers (denial of service).
# Hard limits prevent this.

docker run -d \
  --memory=512m \          # hard RAM limit; OOM killer if exceeded
  --memory-swap=512m \     # = memory: disables swap (swap = 0)
  --cpus=0.5 \             # max 0.5 CPU cores (50% of one core)
  --pids-limit=100 \       # max 100 processes (prevents fork bombs)
  --ulimit nofile=1024:2048 \   # file descriptor limits
  myapp:latest


# ============================================================
# SECURITY HARDENING CHECKLIST (10 Points)
# ============================================================
# 1. [ ] USER non-root in Dockerfile
# 2. [ ] --read-only + targeted --tmpfs for writable paths
# 3. [ ] --cap-drop ALL --cap-add <only-needed>
# 4. [ ] --security-opt no-new-privileges:true
# 5. [ ] Seccomp profile applied (default or custom)
# 6. [ ] No secrets in ENV/ARG in Dockerfile or compose file
# 7. [ ] Minimal base image (distroless or alpine)
# 8. [ ] Image scanned by Trivy/Snyk before deploy
# 9. [ ] Resource limits (--memory, --cpus, --pids-limit)
#10. [ ] No public port exposure for DB/cache services
#        BONUS: Rootless Docker daemon in production
#        BONUS: DOCKER_CONTENT_TRUST=1 in CI

echo "Docker security reference loaded."
