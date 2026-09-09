#!/usr/bin/env bash
# =============================================================================
# DOCKER CHEATSHEET — In-Depth Reference
# Images, containers, volumes, networks, Compose, BuildKit, registries,
# debugging, and production cleanup. Read top-to-bottom; run individually.
# =============================================================================


# =============================================================================
# 1. IMAGES
# =============================================================================

docker images                          # List local images
docker images -a                        # Include intermediate layers
docker image ls --filter "dangling=true" # Untagged/orphaned images

docker pull nginx:1.27-alpine             # Pull a specific tag
docker pull nginx@sha256:abc123...          # Pull by digest (immutable, reproducible)

docker build -t myapp:1.0 .                  # Build from Dockerfile in current dir
docker build -t myapp:1.0 -f Dockerfile.prod . # Build from a named Dockerfile
docker build --no-cache -t myapp:1.0 .          # Ignore layer cache
docker build --build-arg VERSION=1.2 -t myapp . # Pass a build-time variable
docker build --target builder -t myapp:build .    # Build a specific multi-stage target
docker build --platform linux/amd64,linux/arm64 . # Multi-arch build (needs buildx)

docker tag myapp:1.0 myrepo/myapp:1.0        # Add a tag / prep for push
docker push myrepo/myapp:1.0                   # Push to a registry
docker rmi myapp:1.0                             # Remove an image
docker image prune                                # Remove dangling images
docker image prune -a                              # Remove ALL unused images (not just dangling)

docker history myapp:1.0                             # Show layer history + sizes
docker inspect myapp:1.0                              # Full JSON metadata (env, cmd, layers, config)
docker save myapp:1.0 -o myapp.tar                     # Export image to a tarball
docker load -i myapp.tar                                 # Import an image from a tarball

docker scout cves myapp:1.0                               # Vulnerability scan (Docker Scout)
trivy image myapp:1.0                                       # Vulnerability scan (Trivy, more common in CI)


# =============================================================================
# 2. CONTAINERS — LIFECYCLE
# =============================================================================

docker run nginx                                # Run in foreground
docker run -d nginx                               # Run detached (background)
docker run -d --name web nginx                     # Assign a name
docker run -it ubuntu bash                           # Interactive TTY session
docker run --rm alpine echo hi                        # Auto-remove container on exit
docker run -p 8080:80 nginx                             # Map host:container port
docker run -p 127.0.0.1:8080:80 nginx                     # Bind only to localhost
docker run -e KEY=value nginx                               # Set an env var
docker run --env-file .env nginx                              # Load env vars from a file
docker run -v /host/path:/container/path nginx                  # Bind mount
docker run -v myvolume:/data nginx                                # Named volume mount
docker run --network mynet nginx                                   # Attach to a custom network
docker run --restart unless-stopped nginx                            # Restart policy
docker run --memory=512m --cpus=1.5 nginx                              # Resource limits
docker run --read-only nginx                                             # Read-only root filesystem
docker run --user 1000:1000 nginx                                          # Run as non-root UID:GID
docker run --cap-drop ALL --cap-add NET_BIND_SERVICE nginx                    # Minimal Linux capabilities
docker run --security-opt=no-new-privileges nginx                               # Block privilege escalation

docker ps                                # Running containers
docker ps -a                              # All containers, including stopped
docker ps -q                               # Only container IDs (useful for piping)
docker ps --filter "status=exited"           # Filter by status
docker ps --format "table {{.Names}}\t{{.Status}}" # Custom output format

docker start container_name                # Start a stopped container
docker stop container_name                    # Graceful stop (SIGTERM, then SIGKILL after timeout)
docker stop -t 30 container_name                # Custom grace period (seconds)
docker restart container_name                     # Stop + start
docker pause container_name                          # Freeze all processes in container
docker unpause container_name                          # Resume
docker kill container_name                                # Immediate SIGKILL
docker rm container_name                                    # Remove a stopped container
docker rm -f container_name                                   # Force remove (kills if running)
docker rm $(docker ps -aq)                                       # Remove all containers
docker container prune                                             # Remove all stopped containers


# =============================================================================
# 3. CONTAINERS — INTERACTION & DEBUGGING
# =============================================================================

docker exec -it container_name bash             # Shell into a running container
docker exec -it container_name sh                 # For minimal images without bash (alpine)
docker exec container_name env                      # Run a one-off command

docker logs container_name                             # Show logs
docker logs -f container_name                             # Follow logs live
docker logs --tail 100 container_name                        # Last 100 lines
docker logs --since 10m container_name                         # Logs from last 10 minutes
docker logs -t container_name                                    # Include timestamps

docker inspect container_name                              # Full JSON: network, mounts, env, state
docker inspect -f '{{.State.Status}}' container_name          # Extract a specific field
docker inspect -f '{{.NetworkSettings.IPAddress}}' container_name # Get container IP

docker top container_name                                    # Processes running inside container
docker stats                                                    # Live resource usage, all containers
docker stats container_name --no-stream                           # One-shot snapshot

docker diff container_name                                          # Filesystem changes vs image
docker cp container_name:/path/file.txt ./local.txt                    # Copy out of container
docker cp ./local.txt container_name:/path/file.txt                       # Copy into container

docker events                                                              # Stream real-time Docker events
docker port container_name                                                    # Show port mappings


# =============================================================================
# 4. VOLUMES & STORAGE
# =============================================================================

docker volume create myvolume                # Create a named volume
docker volume ls                               # List volumes
docker volume inspect myvolume                   # Show mount point + metadata
docker volume rm myvolume                          # Remove a volume
docker volume prune                                  # Remove all unused volumes

# Bind mount vs named volume vs tmpfs:
#   Bind mount  -> -v /host/path:/container/path   (tied to host filesystem, best for dev)
#   Named vol   -> -v myvolume:/container/path      (Docker-managed, best for persistent data)
#   tmpfs       -> --tmpfs /container/path            (in-memory, never persisted, for secrets/scratch)

docker run --tmpfs /app/tmp nginx                       # In-memory mount, gone on stop

# Backup and restore a named volume (via a throwaway helper container):
docker run --rm -v myvolume:/data -v $(pwd):/backup alpine \
  tar czf /backup/myvolume-backup.tar.gz -C /data .
docker run --rm -v myvolume:/data -v $(pwd):/backup alpine \
  tar xzf /backup/myvolume-backup.tar.gz -C /data


# =============================================================================
# 5. NETWORKING
# =============================================================================

docker network ls                                # List networks
docker network create mynet                        # Create a bridge network (default driver)
docker network create --driver overlay mynet          # Overlay network (Swarm/multi-host)
docker network create --subnet 172.20.0.0/16 mynet      # Custom subnet
docker network inspect mynet                               # Show connected containers + config
docker network connect mynet container_name                  # Attach a running container
docker network disconnect mynet container_name                  # Detach
docker network rm mynet                                           # Remove a network
docker network prune                                                # Remove all unused networks

# Network drivers:
#   bridge   -> default, isolated per-host network; containers reach each other by name
#   host     -> container shares the host's network namespace (no isolation, max performance)
#   none     -> no networking at all
#   overlay  -> spans multiple Docker hosts (Swarm mode)
#   macvlan  -> container gets its own MAC/IP on the physical network

# DNS: containers on the same user-defined bridge network resolve each other
# by container name automatically. On the default "bridge" network, they do not
# — always create a custom network for multi-container apps that need service discovery.


# =============================================================================
# 6. DOCKERFILE REFERENCE
# =============================================================================

# FROM node:20-alpine AS builder      # Base image + stage name (multi-stage build)
# WORKDIR /app                         # Set working directory (creates it if needed)
# COPY package*.json ./                 # Copy files in (layer-cached if unchanged)
# RUN npm ci --production                 # Execute a build-time command
# COPY . .                                  # Copy the rest of the source
# ENV NODE_ENV=production                     # Set a runtime env var (persists in image)
# ARG BUILD_VERSION                             # Build-time-only variable (--build-arg)
# EXPOSE 3000                                     # Document the port (does NOT publish it)
# USER node                                         # Drop root before CMD runs
# ENTRYPOINT ["node"]                                 # Fixed executable (not overridable by args)
# CMD ["server.js"]                                     # Default args (overridable at `docker run`)
# HEALTHCHECK --interval=30s CMD curl -f http://localhost:3000/health || exit 1
# VOLUME ["/data"]                                          # Declare a mount point
# LABEL maintainer="team@example.com"                          # Metadata

# CMD vs ENTRYPOINT:
#   ENTRYPOINT ["node"] + CMD ["server.js"]  -> `docker run img extra.js` runs `node extra.js`
#   CMD ["node", "server.js"] alone           -> `docker run img extra.js` runs just `extra.js` (whole CMD replaced)
#   Exec form ["cmd","arg"] runs directly (PID 1, receives signals properly)
#   Shell form  cmd arg                        runs via /bin/sh -c (extra shell process, signals not forwarded)

# .dockerignore — same syntax as .gitignore, exclude build context bloat:
#   node_modules
#   .git
#   *.log
#   .env


# =============================================================================
# 7. MULTI-STAGE BUILDS
# =============================================================================

cat <<'EOF'
# --- Example: Node.js multi-stage build ---
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine AS production
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
USER node
EXPOSE 3000
CMD ["node", "dist/server.js"]
# Result: final image excludes build tools, source maps, devDependencies —
# often 5-10x smaller than a single-stage build.
EOF


# =============================================================================
# 8. DOCKER COMPOSE
# =============================================================================

docker compose up                          # Start all services (foreground)
docker compose up -d                         # Start detached
docker compose up --build                      # Rebuild images before starting
docker compose up -d --scale worker=3            # Scale a service to 3 replicas
docker compose down                                # Stop and remove containers/networks
docker compose down -v                               # Also remove named volumes
docker compose ps                                      # List services in this project
docker compose logs -f                                    # Follow logs, all services
docker compose logs -f web                                  # Follow logs, one service
docker compose exec web bash                                  # Shell into a running service
docker compose run --rm web pytest                               # One-off command in a fresh container
docker compose restart web                                          # Restart one service
docker compose config                                                  # Validate + print resolved config
docker compose pull                                                      # Pull latest images for all services

cat <<'EOF'
# --- Example: compose.yaml ---
services:
  web:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgres://db:5432/app
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3

  db:
    image: postgres:16-alpine
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      - POSTGRES_PASSWORD=secret
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s

volumes:
  pgdata:
EOF


# =============================================================================
# 9. BUILDKIT & BUILDX
# =============================================================================

docker buildx create --use --name mybuilder      # Create + activate a builder instance
docker buildx build --platform linux/amd64,linux/arm64 -t myrepo/app:1.0 --push .
docker buildx ls                                    # List builders
docker buildx inspect --bootstrap                     # Show/init current builder

# BuildKit cache mount (speeds up repeated dependency installs):
cat <<'EOF'
RUN --mount=type=cache,target=/root/.npm \
    npm ci
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc \
    npm ci   # secret never persisted into a layer
EOF
# docker build --secret id=npmrc,src=$HOME/.npmrc -t myapp .


# =============================================================================
# 10. REGISTRIES & AUTH
# =============================================================================

docker login                                   # Login to Docker Hub
docker login myregistry.azurecr.io               # Login to a private/cloud registry
docker logout                                      # Log out
docker tag myapp:1.0 myregistry.azurecr.io/myapp:1.0
docker push myregistry.azurecr.io/myapp:1.0

# Common registries: Docker Hub, GitHub Container Registry (ghcr.io),
# AWS ECR, Azure ACR, Google Artifact Registry, self-hosted (Harbor).


# =============================================================================
# 11. SECURITY HARDENING
# =============================================================================

# - Run as non-root (USER directive or --user flag)
# - Use minimal base images (alpine, distroless) to shrink attack surface
# - --read-only + --tmpfs for writable dirs the app actually needs
# - --cap-drop ALL, add back only required capabilities
# - --security-opt=no-new-privileges:true
# - Pin base image by digest, not just tag, for supply-chain reproducibility
# - Scan images in CI: trivy image, docker scout, or Grype
# - Never bake secrets into image layers — use --secret (BuildKit) or runtime env/vault
# - Sign images: cosign sign myrepo/myapp:1.0 (verify with cosign verify)


# =============================================================================
# 12. PRODUCTION CLEANUP & MAINTENANCE
# =============================================================================

docker system df                          # Disk usage summary (images/containers/volumes/cache)
docker system prune                         # Remove stopped containers, dangling images, unused networks
docker system prune -a                        # Also remove all unused images (not just dangling)
docker system prune -a --volumes                # Also remove unused volumes (DESTRUCTIVE — check first)
docker builder prune                              # Clear the BuildKit build cache

# tini as PID 1 (handles zombie reaping + signal forwarding correctly):
#   ENTRYPOINT ["/sbin/tini", "--", "node", "server.js"]
# Graceful shutdown pattern: catch SIGTERM in-app, drain in-flight requests,
# exit before Docker's default 10s grace period expires (or extend with `docker stop -t`).


# =============================================================================
# 13. THE CONTAINER RUNTIME STACK — WHAT ACTUALLY RUNS UNDER "docker run"
# =============================================================================

# Docker is a UX layer on top of a standardized runtime stack. Understanding
# the layers matters because Kubernetes bypasses Docker entirely and talks
# to these lower layers directly (this is why "Docker support" was deprecated
# in Kubernetes 1.24 — kubelet never needed the Docker daemon, only the
# runtime underneath it):
#
#   docker CLI  ->  dockerd (daemon)  ->  containerd (high-level runtime,
#     manages image pulls, storage, container lifecycle)  ->  runc (low-level
#     OCI runtime, actually calls clone()/unshare()/pivot_root() to build the
#     namespaces+cgroups that BECOME the container) -> Linux kernel
#
# OCI (Open Container Initiative) defines two specs that make this pluggable:
#   - Image spec:   what a container image's layers/manifest/config must look like
#   - Runtime spec: what a "bundle" (rootfs + config.json) a runtime must accept
# Because of this, runc is swappable:
#   - gVisor (runsc)  -> intercepts syscalls in a userspace kernel (sandboxed,
#                          higher isolation, some syscall/perf compatibility cost)
#   - Kata Containers -> runs each container in a lightweight VM (hardware-level
#                          isolation — used for untrusted/multi-tenant workloads)
#   - crun            -> faster, lower-memory runc alternative written in C

ctr images ls                          # Interact with containerd directly (bypassing dockerd)
ctr run docker.io/library/alpine:latest test echo hi

crictl ps                              # CRI-level inspection (what kubelet actually sees)
crictl images                             # Images as containerd/CRI-O see them, not dockerd's view


# =============================================================================
# 14. PODMAN — THE DAEMONLESS, ROOTLESS ALTERNATIVE
# =============================================================================

# Podman is command-compatible with Docker for the vast majority of use cases
# (`alias docker=podman` works for most workflows) but with two structural
# differences that matter in enterprise/regulated environments:
#   1. No background daemon — each `podman run` forks a direct child process,
#      so there's no single root-owned daemon that, if compromised, owns every
#      container on the host (Docker's classic "root-equivalent socket" risk).
#   2. Rootless by default — containers run as your unprivileged user via user
#      namespaces, not root, even though processes inside the container still
#      see themselves as root (UID 0 is remapped to an unprivileged host UID).
# This is why RHEL/Fedora and many federal/regulated shops standardized on it.

podman run -d --name web -p 8080:80 nginx     # Same syntax as docker run, almost 1:1
podman ps                                        # List running containers
podman build -t myapp:1.0 .                        # Build (uses the same Dockerfile syntax)
podman pod create --name mypod -p 8080:80          # Podman's own concept: a "pod" = shared network
podman pod ps                                         # namespace for multiple containers (mirrors a K8s Pod)
podman generate kube mypod > pod.yaml                    # Export a Podman pod as a K8s manifest directly
podman play kube pod.yaml                                   # Run a K8s YAML file locally via Podman — no cluster needed
systemctl --user start podman.socket                          # Rootless Podman socket, per-user (no root daemon at all)


# =============================================================================
# 15. DOCKER SWARM — THE SIMPLE ALTERNATIVE TO KUBERNETES
# =============================================================================

# Still asked about in interviews as "when would you NOT reach for Kubernetes."
# Swarm is built into the Docker CLI/daemon — no separate control plane to
# install — and trades Kubernetes's flexibility for dramatically lower
# operational overhead. Reasonable fit for small teams/simple multi-host setups.

docker swarm init --advertise-addr 192.168.1.10   # Initialize a swarm on this node (becomes a manager)
docker swarm join-token worker                       # Get the token to join more nodes as workers
docker swarm join --token <token> 192.168.1.10:2377     # Run on a new node to join the swarm

docker node ls                                # List nodes in the swarm
docker service create --name web --replicas 3 -p 80:80 nginx  # Deploy a replicated service
docker service ls                                # List running services
docker service scale web=5                          # Scale a service
docker service update --image nginx:1.27 web           # Rolling update (built-in, no extra tooling)
docker stack deploy -c docker-compose.yml mystack          # Deploy a full Compose file as a Swarm stack
docker stack services mystack                                  # List services in a stack

docker secret create db_password ./password.txt   # Swarm-native secrets (encrypted at rest in the Raft log,
docker secret ls                                       # mounted as an in-memory tmpfs file inside the container —
                                                        # this is the Swarm equivalent of a K8s Secret)


# =============================================================================
# 16. MULTI-ARCHITECTURE IMAGES — MANIFEST LISTS
# =============================================================================

# A "multi-arch image" is really one tag pointing at a manifest LIST — a small
# index that maps each CPU architecture to its own separate image digest.
# `docker pull myapp:1.0` on an ARM Mac and an x86 CI runner silently pull
# different underlying images because the daemon reads the local platform
# and picks the matching entry automatically.

docker manifest inspect myrepo/myapp:1.0     # Show the manifest list (all platforms it covers)
docker buildx imagetools inspect myrepo/myapp:1.0  # Modern equivalent, works without a full pull

# Building and publishing one under buildx (see section 9 for buildx setup):
docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 \
  -t myrepo/myapp:1.0 --push .
# buildx assembles each platform's image separately (often via QEMU emulation
# unless building on native hardware for each arch) then pushes ONE manifest
# list tying them together under the single tag.


# =============================================================================
# 17. RESOURCE ISOLATION INTERNALS — WHAT --memory/--cpus ACTUALLY DO
# =============================================================================

# `docker run --memory/--cpus` are a thin wrapper over Linux cgroups (control
# groups) v2. Knowing the underlying files is the difference between guessing
# and actually debugging an OOM-killed or throttled container:

cat /sys/fs/cgroup/memory.max          # (inside a container's cgroup) the hard memory ceiling
cat /sys/fs/cgroup/memory.current         # Current usage right now
cat /sys/fs/cgroup/cpu.max                   # "<quota> <period>" — e.g. "50000 100000" = 0.5 CPU
docker inspect -f '{{.HostConfig.Memory}}' container_name  # Same value, read via Docker's API

# Namespaces are the OTHER half of "what is a container": PID, NET, MNT, UTS,
# IPC, and USER namespaces each isolate one kind of resource so the process
# inside believes it's alone on the machine. `docker run --pid=host` or
# `--network=host` deliberately punches a hole in one of these — useful for
# debugging tools (they need to see the real host's processes/network) but a
# real security boundary loss if left on in production.

nsenter -t $(docker inspect -f '{{.State.Pid}}' container_name) -n ip a
  # ^ Enter a running container's network namespace directly from the host,
  #   bypassing `docker exec` entirely — useful when a container has no shell.
