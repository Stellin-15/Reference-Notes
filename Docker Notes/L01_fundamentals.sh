#!/bin/bash

# ============================================================
# L01: Docker Fundamentals — Containers, the Kernel, and Core CLI
# ============================================================
# WHAT: Understand what Docker is, how it works at the OS level,
#       and master the essential CLI commands used daily.
# WHY:  Without understanding the kernel primitives underneath
#       containers, you will debug blindly and make poor
#       architectural decisions. This is the mental model
#       every senior engineer carries at all times.
# LEVEL: Foundations
# ============================================================
# CONCEPT OVERVIEW:
#   A container is NOT a VM. It is a process (or process tree)
#   on the HOST kernel that has been isolated using three Linux
#   kernel features:
#
#   1. NAMESPACES  — limit what a process can SEE
#   2. CGROUPS     — limit what a process can USE
#   3. UNION FS    — give the process its own layered filesystem
#
# PRODUCTION USE CASE:
#   Every microservice at companies like Netflix, Uber, and
#   Shopify runs inside containers. Containers make deployments
#   reproducible: if it runs on your laptop, it runs in prod.
#
# COMMON MISTAKES:
#   - Confusing containers with VMs (containers share the kernel)
#   - Running containers as root in production
#   - Storing state inside the container (it's ephemeral!)
#   - Not understanding that "docker stop" sends SIGTERM, not SIGKILL
# ============================================================


# ============================================================
# PART 1: CONTAINERS vs VIRTUAL MACHINES
# ============================================================
#
# VIRTUAL MACHINE stack:
#   [ Your App        ]
#   [ Guest OS        ]  <-- full OS kernel copied per VM
#   [ Hypervisor      ]  <-- VMware, VirtualBox, KVM
#   [ Host OS Kernel  ]
#   [ Hardware        ]
#
# CONTAINER stack:
#   [ Your App        ]
#   [ Container (namespace + cgroup) ]
#   [ Docker Daemon (containerd)     ]
#   [ Host OS Kernel  ]  <-- SHARED. One kernel for all containers.
#   [ Hardware        ]
#
# KEY DIFFERENCES:
#   Property        | VM                  | Container
#   --------------- | ------------------- | --------------------
#   Startup time    | 30-60 seconds       | Milliseconds
#   Memory overhead | 256MB-2GB per guest | ~1MB per container
#   Isolation level | Full OS boundary    | Process boundary
#   Portability     | Heavy (GB images)   | Light (MB images)
#   Kernel          | Own kernel per VM   | Shared host kernel
#
# IMPLICATION: Because containers share the host kernel, a Linux
# container CANNOT run on a Windows host natively. Docker Desktop
# on Mac/Windows runs a tiny Linux VM, then runs containers inside
# that. In production (Linux servers), there's no VM layer.


# ============================================================
# PART 2: KERNEL NAMESPACES — Isolation by "what you can see"
# ============================================================
#
# Linux namespaces partition global kernel resources so that
# each container has its own view of the system.
#
# NAMESPACE TYPE  | WHAT IT ISOLATES
# --------------- | ------------------------------------------------
# pid             | Process IDs. Container sees its own PID 1.
#                 | Host can still see container PIDs, but container
#                 | cannot see host PIDs.
# net             | Network interfaces, IP addresses, routing tables,
#                 | firewall rules. Each container gets its own eth0.
# mnt             | Mount points / filesystem. Container has its own
#                 | /proc, /sys, /tmp view.
# uts             | Hostname and domain name. Container can have its
#                 | own hostname (e.g., "web-server-1").
# ipc             | Inter-process communication (shared memory,
#                 | semaphores). Prevents cross-container IPC.
# user            | User and group IDs. UID 0 inside container can
#                 | map to an unprivileged UID on the host (rootless).
# cgroup          | A container's own view of its cgroup hierarchy.
#
# HOW TO INSPECT: On a Linux host, you can see namespace IDs:
#   ls -la /proc/<pid>/ns/
# Each file is a symlink to the namespace. Two processes in the
# same namespace share the same symlink target.


# ============================================================
# PART 3: CGROUPS — Resource limits ("what you can USE")
# ============================================================
#
# Control Groups (cgroups) enforce resource quotas. Without them,
# a single container could starve all others.
#
# CGROUP SUBSYSTEM | WHAT IT CONTROLS
# ---------------- | ------------------------------------------------
# cpu              | CPU time allocation (shares, quota, period)
# cpuset           | Which CPU cores the container can use
# memory           | RAM limit + swap limit + OOM killer behavior
# blkio            | Disk I/O rate limits (read/write IOPS, MB/s)
# net_cls          | Network packet classification for QoS
# pids             | Maximum number of processes/threads
#
# Example: limit a container to 512MB RAM and 0.5 CPUs:
#   docker run --memory=512m --cpus=0.5 nginx
#
# If the container exceeds --memory, the OOM killer terminates it.
# In production, always set memory limits. Without them, a
# runaway container can crash the entire host.
#
# Inspect cgroup limits for a running container:
#   cat /sys/fs/cgroup/memory/docker/<container_id>/memory.limit_in_bytes


# ============================================================
# PART 4: UNION FILESYSTEMS — Layered images (OverlayFS)
# ============================================================
#
# Docker images are built from READ-ONLY LAYERS stacked on top
# of each other. OverlayFS (the default storage driver) merges
# these layers into a single coherent filesystem view.
#
# Example for an Nginx image:
#   Layer 4 (R/W): Container write layer (ephemeral)
#   Layer 3 (R):   COPY nginx.conf /etc/nginx/    <- your layer
#   Layer 2 (R):   RUN apt-get install nginx       <- install layer
#   Layer 1 (R):   debian:bullseye-slim base       <- base OS layer
#
# OverlayFS terms:
#   lowerdir  = read-only image layers (stacked)
#   upperdir  = read-write container layer
#   workdir   = OverlayFS internal scratch space
#   merged    = the unified view the container process sees
#
# COPY-ON-WRITE (CoW): When a container modifies a file that
# lives in a read-only layer, OverlayFS copies it up to the
# upperdir first, then modifies it. The original layer is
# untouched. Multiple containers share the same lowerdir layers,
# saving disk space dramatically.
#
# WHY THIS MATTERS ARCHITECTURALLY:
#   - Layer caching makes rebuilds fast (only changed layers rebuild)
#   - Multiple containers from the same image share layers on disk
#   - Writing large files inside containers is slow (CoW overhead)
#     — put database data on volumes, not inside containers


# ============================================================
# PART 5: ESSENTIAL CLI COMMANDS
# ============================================================

# --- PULLING IMAGES ---
# docker pull <image>[:<tag>]
# Downloads image layers from the registry (Docker Hub by default).
# If no tag is specified, Docker pulls "latest" — AVOID in production.
# In prod, always pin to a specific version tag or SHA digest.

docker pull nginx:1.25.3
# Pulls nginx version 1.25.3. Each layer is downloaded separately
# and cached locally in /var/lib/docker/overlay2/.

docker pull nginx@sha256:abc123...
# Pull by digest (SHA256 of the manifest). Immutable — guarantees
# you always get the exact same image bytes. Use this in prod.

# --- RUNNING CONTAINERS ---
# docker run [OPTIONS] IMAGE [COMMAND] [ARG...]
# Creates a new container from an image and starts it.

docker run nginx
# Runs nginx in the FOREGROUND. Your terminal is attached to its
# stdout/stderr. Press Ctrl+C to stop (sends SIGINT).

docker run -d nginx
# -d (--detach): Run in the background. Returns the container ID.
# You get your terminal back immediately. This is typical in prod.

docker run -d --name my-nginx nginx
# --name: Give the container a human-readable name.
# Without --name, Docker assigns a random name (e.g., "hopeful_turing").
# Named containers are easier to reference in scripts.

# --- PORT MAPPING ---
# -p HOST_PORT:CONTAINER_PORT
# Without -p, the container's port is not reachable from outside.
# The EXPOSE instruction in a Dockerfile is documentation only.
# Only -p actually binds to the host.

docker run -d -p 8080:80 --name web nginx
# Host port 8080 → Container port 80.
# curl http://localhost:8080 will hit nginx inside the container.
# The host's firewall rules still apply to port 8080.

docker run -d -p 127.0.0.1:8080:80 nginx
# Bind to loopback only. Prevents external access to port 8080.
# Use this for internal services that should not be internet-facing.

docker run -d -p 80 nginx
# Publish container port 80 to a RANDOM available host port.
# Useful when running many instances and you don't care which port.
# Find the assigned port with: docker port <container_name>

# --- ENVIRONMENT VARIABLES ---
# -e VAR=VALUE or --env VAR=VALUE
# The primary way to configure containerized apps (12-factor app style).

docker run -d \
  -e POSTGRES_USER=myapp \
  -e POSTGRES_PASSWORD=supersecret \
  -e POSTGRES_DB=myappdb \
  -p 5432:5432 \
  postgres:16

# --env-file: Load variables from a file (one VAR=VALUE per line).
# NEVER commit .env files to git if they contain secrets.
docker run -d --env-file .env.production myapp:1.0.0

# --- VOLUME MOUNTS ---
# -v HOST_PATH:CONTAINER_PATH[:OPTIONS]
# Two main forms: bind mounts and named volumes (see L05).

docker run -d \
  -v /data/nginx/html:/usr/share/nginx/html:ro \
  nginx
# HOST_PATH: /data/nginx/html (must exist on host)
# CONTAINER_PATH: /usr/share/nginx/html
# :ro = read-only mount. Container cannot modify these files.
# Use :ro for config files and static assets.

docker run -d \
  -v pgdata:/var/lib/postgresql/data \
  postgres:16
# "pgdata" is a NAMED VOLUME managed by Docker.
# Data persists when the container is removed and restarts.
# Find it in /var/lib/docker/volumes/pgdata/

# --- EXEC INTO A RUNNING CONTAINER ---
docker exec -it my-nginx bash
# -i (--interactive): Keep STDIN open
# -t (--tty): Allocate a pseudo-TTY (terminal emulator)
# Combined: gives you an interactive shell inside the container.
# The container's PID 1 keeps running; exec spawns an additional process.

docker exec my-nginx nginx -t
# Run a single command inside a container without opening a shell.
# Useful for running scripts, checking config, etc.

docker exec -it my-nginx sh
# Use sh instead of bash if bash is not installed (e.g., Alpine images).

# --- VIEWING RUNNING CONTAINERS ---
docker ps
# Lists only RUNNING containers.
# Columns: CONTAINER ID, IMAGE, COMMAND, CREATED, STATUS, PORTS, NAMES

docker ps -a
# -a (--all): Lists ALL containers including stopped ones.
# Stopped containers still occupy disk space until removed.

docker ps -q
# -q (--quiet): Print only container IDs. Useful in scripts:
#   docker stop $(docker ps -q)  # stop all running containers

docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
# Custom output format using Go templates. Useful in scripts and CI.

# --- STOPPING AND REMOVING CONTAINERS ---
docker stop my-nginx
# Sends SIGTERM to PID 1 of the container, waits 10 seconds (grace
# period), then sends SIGKILL if the process hasn't exited.
# Well-written apps catch SIGTERM and shut down gracefully
# (finish in-flight requests, close DB connections, etc.).

docker stop --time=30 my-nginx
# --time: Override the grace period (seconds) before SIGKILL.
# For slow-shutting services (e.g., databases flushing writes),
# increase this value.

docker kill my-nginx
# Immediately sends SIGKILL. No grace period. Data loss risk.
# Only use when a container is hung and won't respond to SIGTERM.

docker rm my-nginx
# Removes a STOPPED container. Frees its writable layer disk space.
# Does NOT remove the image or named volumes.

docker rm -f my-nginx
# -f (--force): Stop (SIGKILL) and remove in one step.
# Dangerous — use only in scripts or cleanup scenarios.

docker run -d --rm nginx
# --rm: Automatically remove the container when it exits.
# Perfect for one-shot tasks (migrations, scripts, tests).
# The container cleans itself up — no orphaned stopped containers.

# --- VIEWING LOGS ---
docker logs my-nginx
# Prints all stdout and stderr output from the container.
# Docker captures everything written to stdout/stderr by PID 1
# and its children (via the log driver, default: json-file).

docker logs -f my-nginx
# -f (--follow): Stream logs in real time. Like "tail -f".
# Ctrl+C detaches the log stream without stopping the container.

docker logs --tail=100 my-nginx
# Show only the last 100 lines. Useful for large log outputs.

docker logs --since=1h my-nginx
# Show logs from the last hour. Accepts: 10s, 5m, 2h, 2013-01-02.

docker logs --timestamps my-nginx
# Prefix each line with the UTC timestamp Docker received it.

# --- INSPECTING CONTAINERS AND IMAGES ---
docker inspect my-nginx
# Returns a massive JSON document with EVERYTHING about the container:
# - NetworkSettings.IPAddress: container's internal IP
# - Mounts: volume mount details
# - Config.Env: environment variables
# - State.Status: running/stopped/exited + exit code
# - HostConfig.Memory: memory limit in bytes (0 = unlimited)

docker inspect --format '{{.NetworkSettings.IPAddress}}' my-nginx
# Extract a single field using Go template syntax.
# Indispensable in shell scripts.

docker inspect --format '{{.State.ExitCode}}' my-nginx
# Check why a container stopped. ExitCode 0 = clean exit.
# ExitCode 137 = killed by OOM killer (out of memory).
# ExitCode 1   = app crashed.

docker image inspect nginx:1.25.3
# Inspect an IMAGE (not a running container).
# Shows layers, architecture, entrypoint, exposed ports, etc.

# --- IMAGE MANAGEMENT ---
docker images
# List all locally cached images.
# Columns: REPOSITORY, TAG, IMAGE ID, CREATED, SIZE

docker rmi nginx:1.25.3
# Remove a local image. Cannot remove if a container (even stopped)
# is using it. Remove the container first.

docker image prune
# Remove all DANGLING images (untagged layers from old builds).
# Run this regularly in CI environments to reclaim disk space.

docker system prune -a
# Nuclear option: remove ALL unused images, containers, networks,
# and build cache. Frees maximum disk space but next build starts cold.
# DO NOT run on a production host that is serving traffic.

# --- CONTAINER LIFECYCLE DIAGRAM ---
#
#   docker pull → [IMAGE]
#                    |
#               docker run → [CREATED] → [RUNNING]
#                                             |
#                                    docker stop/kill
#                                             |
#                                         [EXITED]
#                                             |
#                                        docker rm
#                                             |
#                                         (gone)
#
# A container can also go from RUNNING → PAUSED (docker pause)
# and back (docker unpause). PAUSED sends SIGSTOP to the cgroup.

# --- QUICK REFERENCE ---
# docker pull IMAGE:TAG           # Download image
# docker run -d -p H:C IMAGE      # Start detached with port map
# docker ps / ps -a               # List running / all containers
# docker logs -f NAME             # Stream logs
# docker exec -it NAME sh         # Open shell in container
# docker stop NAME                # Graceful shutdown (SIGTERM)
# docker rm NAME                  # Delete stopped container
# docker images                   # List local images
# docker rmi IMAGE:TAG            # Delete local image
# docker inspect NAME             # Full JSON metadata
# docker stats                    # Live CPU/memory/net usage

echo "L01 complete. You now understand the kernel foundations of Docker."
