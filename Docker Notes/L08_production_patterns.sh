#!/usr/bin/env bash

# ============================================================
# L08: Docker Production Patterns
# ============================================================
# WHAT: Operational patterns for running Docker in production —
#       graceful shutdown, health checks, logging, tagging,
#       layer caching, multi-platform builds, zero-downtime
#       deploys, and debugging live containers.
# WHY:  Getting an app into a container is easy. Running it
#       reliably in production — with proper shutdown, restart,
#       log collection, and observability — is where most teams
#       fail. These patterns are the difference between "works
#       in demo" and "runs for 18 months without incident."
# LEVEL: Advanced
# ============================================================
# CONCEPT OVERVIEW:
#   12-Factor App methodology (https://12factor.net) defines
#   the contract containers expect to fulfill:
#     - Stateless processes
#     - Logs as event streams (stdout/stderr)
#     - Config via environment variables
#     - Explicit port binding
#     - Fast startup, graceful shutdown
#   These patterns translate 12-Factor principles into Docker.
#
# PRODUCTION USE CASE:
#   A zero-downtime rolling deploy on a 3-replica API service:
#   health check gates traffic, old replicas drain requests,
#   new replicas pass health checks before old ones stop.
#   Without these patterns: dropped requests during every deploy.
#
# COMMON MISTAKES:
#   - Shell form CMD (loses SIGTERM, hangs for 10s on shutdown).
#   - Writing logs to files inside the container (lost on death).
#   - Using :latest image tag in production (non-deterministic).
#   - No health check: orchestrators can't detect a zombie app.
#   - Building for x86 on M1 Mac, deploying to ARM server.
# ============================================================


# ============================================================
# SECTION 1: GRACEFUL SHUTDOWN — SIGTERM AND PID 1
# ============================================================
# When Docker stops a container (`docker stop`), it sends
# SIGTERM to PID 1 (the first process). If PID 1 doesn't
# handle SIGTERM within --stop-timeout seconds (default 10),
# Docker sends SIGKILL — forceful, zero-grace-period kill.
#
# THE PID 1 PROBLEM:
#   SHELL FORM:   CMD "python app.py"
#     Docker starts: /bin/sh -c "python app.py"
#     PID 1 is /bin/sh, NOT python.
#     Shell does NOT forward SIGTERM to child processes.
#     Result: python gets SIGKILL after timeout. No graceful shutdown.
#
#   EXEC FORM:    CMD ["python", "app.py"]
#     Docker starts python directly as PID 1.
#     SIGTERM goes directly to python.
#     Python can catch it, flush connections, exit cleanly.
#
# IN DOCKERFILE:
#   WRONG:  CMD "uvicorn main:app --host 0.0.0.0 --port 8000"
#   RIGHT:  CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
#
# ENTRYPOINT INTERACTION:
#   ENTRYPOINT ["python"]
#   CMD ["app.py"]
#   → runs: python app.py (exec form — correct)

# Verify the PID of the main process in a container:
docker run -d --name test-app myapp:latest
docker exec test-app ps aux
# PID 1 should be your application, NOT sh/bash.

# Set a longer stop timeout for apps that need more drain time:
docker stop --time 30 myapp-container   # 30 second SIGTERM window


# ============================================================
# SECTION 2: TINI — PROPER PID 1 INIT PROCESS
# ============================================================
# Even with exec form, if your app spawns child processes,
# you need a real init to:
#   - Forward signals to the entire process tree.
#   - Reap zombie processes (wait() for dead children).
#
# Tini is a minimal init designed specifically for containers.
# It is included in Docker since 19.03 via --init flag.
#
# In Dockerfile:
#   RUN apt-get install -y tini
#   ENTRYPOINT ["/usr/bin/tini", "--"]
#   CMD ["python", "app.py"]
#
# Or at runtime:
docker run -d --init myapp:latest
# --init adds tini as PID 1 without modifying the Dockerfile.


# ============================================================
# SECTION 3: HEALTH CHECKS
# ============================================================
# A health check tells Docker (and orchestrators) whether the
# container is ACTUALLY ready to serve traffic — not just started.
#
# States:
#   starting  — within start_period, failures don't count
#   healthy   — last N checks passed
#   unhealthy — last N checks failed; orchestrator can restart
#
# DOCKERFILE HEALTHCHECK (baked into image):
#   HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
#     CMD curl -f http://localhost:8000/health || exit 1
#
# RUNTIME OVERRIDE (for images you don't control):
docker run -d \
  --health-cmd="curl -f http://localhost:8000/health || exit 1" \
  --health-interval=10s \
  --health-timeout=5s \
  --health-retries=3 \
  --health-start-period=30s \
  myapp:latest

# Check health status:
docker inspect --format='{{.State.Health.Status}}' myapp-container
docker ps    # STATUS column shows: Up 2 minutes (healthy)

# KUBERNETES MAPPING:
#   Liveness probe  → is the container alive? restart if not.
#   Readiness probe → is it ready for traffic? remove from LB if not.
#   Docker healthcheck roughly maps to liveness.
#   K8s readiness needs a separate endpoint that checks if the
#   app's dependencies (DB, cache) are accessible.


# ============================================================
# SECTION 4: LOGGING — STDOUT/STDERR (12-FACTOR)
# ============================================================
# Containers should write logs to stdout/stderr ONLY.
# NEVER write to log files inside the container:
#   - Files are lost when the container is removed.
#   - Files aren't accessible to Docker's log drivers.
#   - Disk fills up silently.
#
# Docker collects stdout/stderr via log drivers and routes
# them to whatever backend you configure.

# View logs from a running container:
docker logs myapp-container
docker logs -f myapp-container          # follow (tail -f)
docker logs --since=10m myapp-container # last 10 minutes
docker logs --tail=100 myapp-container  # last 100 lines

# Log driver: json-file (default) with rotation
# Set globally in /etc/docker/daemon.json:
# {
#   "log-driver": "json-file",
#   "log-opts": {
#     "max-size": "20m",
#     "max-file": "5"
#   }
# }
#
# Or per-container:
docker run -d \
  --log-driver json-file \
  --log-opt max-size=20m \
  --log-opt max-file=5 \
  myapp:latest

# CENTRALIZED LOGGING — fluentd / fluent-bit sidecar:
# Run fluent-bit as a container that reads Docker's json log files
# and ships them to Elasticsearch, Loki, Datadog, CloudWatch, etc.
docker run -d \
  --log-driver=fluentd \
  --log-opt fluentd-address=localhost:24224 \
  --log-opt tag="myapp.{{.Name}}" \
  myapp:latest


# ============================================================
# SECTION 5: IMAGE TAGGING STRATEGY
# ============================================================
# :latest is a lie. It means "whatever was last pushed with
# that tag." In production, this is catastrophic:
#   - `docker pull myapp:latest` can pull a DIFFERENT image
#     tomorrow than it pulled today.
#   - Rollback is impossible (what was :latest yesterday?).
#   - Container restarts may pull a different version.
#
# CORRECT TAGGING STRATEGY:
#   myapp:<semver>-<git-sha>
#   myapp:1.3.0-abc1234
#
# In CI (GitHub Actions example):
#   TAG="${VERSION}-$(git rev-parse --short HEAD)"
#   docker build -t myregistry/myapp:${TAG} .
#   docker push myregistry/myapp:${TAG}
#   # Also tag for semver convenience (these can lag behind SHA tags)
#   docker tag myregistry/myapp:${TAG} myregistry/myapp:${VERSION}
#   docker push myregistry/myapp:${VERSION}

VERSION="1.3.0"
GIT_SHA=$(git rev-parse --short HEAD)
IMAGE_TAG="${VERSION}-${GIT_SHA}"

docker build -t "myregistry/myapp:${IMAGE_TAG}" .
docker push "myregistry/myapp:${IMAGE_TAG}"


# ============================================================
# SECTION 6: LAYER CACHING IN CI/CD
# ============================================================
# Docker build cache dramatically speeds up CI pipelines.
# Without cache: full pip install on every build (2-5 minutes).
# With cache: unchanged layers are reused (10-20 seconds).
#
# BuildKit (enabled by default in Docker 23+) provides
# improved caching with --cache-from and inline cache manifests.

# Build with cache FROM a previously built image (registry cache):
DOCKER_BUILDKIT=1 docker build \
  --cache-from "myregistry/myapp:cache" \   # pull cache layers from here
  --build-arg BUILDKIT_INLINE_CACHE=1 \     # embed cache metadata in image
  -t "myregistry/myapp:${IMAGE_TAG}" \
  -t "myregistry/myapp:cache" \             # update cache tag for next build
  .

# GitHub Actions example (using actions/cache for layer caching):
# - uses: docker/setup-buildx-action@v3
# - uses: actions/cache@v4
#   with:
#     path: /tmp/.buildx-cache
#     key: ${{ runner.os }}-buildx-${{ hashFiles('**/Dockerfile') }}
# - uses: docker/build-push-action@v5
#   with:
#     cache-from: type=local,src=/tmp/.buildx-cache
#     cache-to: type=local,dest=/tmp/.buildx-cache-new,mode=max


# ============================================================
# SECTION 7: MULTI-PLATFORM BUILDS
# ============================================================
# Apple Silicon (M1/M2/M3) Macs use ARM64 architecture.
# Production servers typically run AMD64 (x86_64).
# Building on M1 without --platform produces an ARM image that
# CRASHES on AMD64 servers with "exec format error."
#
# docker buildx: Docker's build toolkit supporting multi-arch.
# Creates a manifest list: one image tag → multiple platform
# variants. Docker pulls the correct one automatically.

# One-time setup: create a buildx builder with multi-platform support:
docker buildx create --name multiarch --use
docker buildx inspect --bootstrap   # starts the builder

# Build for BOTH amd64 and arm64, push to registry:
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t "myregistry/myapp:${IMAGE_TAG}" \
  --push \    # buildx must push to registry (can't load multi-platform locally)
  .

# Build only for production target in CI:
docker buildx build \
  --platform linux/amd64 \
  -t "myregistry/myapp:${IMAGE_TAG}" \
  --load \    # load into local docker (single platform OK)
  .


# ============================================================
# SECTION 8: RESOURCE LIMITS
# ============================================================
# Without limits, a single misbehaving container can OOM the
# host, starving all other containers (noisy neighbor problem).
# Set limits on EVERY container in production.

docker run -d \
  --name api \
  --memory=512m \           # hard limit; OOM killer if exceeded
  --memory-swap=512m \      # disable swap (swap = memory means 0 swap)
  --memory-reservation=256m \  # soft limit for scheduling hints
  --cpus=1.0 \              # max 1 CPU core
  --cpu-shares=512 \        # relative weight (default 1024) for contention
  --pids-limit=200 \        # max PID count (prevents fork bombs)
  myapp:latest


# ============================================================
# SECTION 9: STARTUP ORDERING — WAIT FOR DEPENDENCIES
# ============================================================
# `depends_on: condition: service_healthy` (in compose) handles
# ordering at the compose level. But in standalone Docker or
# Swarm, containers start in parallel. Your app may crash before
# Postgres is accepting connections.
#
# Solutions:
#   1. wait-for-it.sh: bash script that polls TCP port until open.
#   2. dockerize: feature-rich wait tool (TCP, HTTP, file).
#   3. Application retry logic: exponential backoff on DB connect.
#      (PREFERRED — more resilient to runtime DB restarts too.)

# In entrypoint.sh using wait-for-it:
#   /wait-for-it.sh postgres:5432 --timeout=30 --strict -- uvicorn main:app
#
# In entrypoint.sh using dockerize:
#   dockerize -wait tcp://postgres:5432 -wait tcp://redis:6379 \
#             -timeout 60s uvicorn main:app


# ============================================================
# SECTION 10: ZERO-DOWNTIME DEPLOYMENT
# ============================================================
# Rolling deploy (Docker Swarm):
#   1. New containers start (health check must pass)
#   2. Load balancer routes traffic to new containers
#   3. Old containers get SIGTERM (drain in-flight requests)
#   4. Old containers stop after drain period
#
# Swarm rolling update config:
docker service update \
  --image myregistry/myapp:${IMAGE_TAG} \
  --update-parallelism 1 \      # update 1 replica at a time
  --update-delay 30s \          # wait 30s between each replica
  --update-failure-action rollback \   # auto-rollback on failure
  --health-cmd "curl -f http://localhost:8000/health" \
  myapp-service

# Rollback if something goes wrong:
docker service rollback myapp-service

# For Docker Compose (no Swarm), zero-downtime requires an
# external load balancer (nginx, Traefik) and manual traffic
# management. Traefik can auto-discover new containers.


# ============================================================
# SECTION 11: DEBUGGING PRODUCTION CONTAINERS
# ============================================================
# Rule: production containers should have minimal tooling
# (distroless has NO shell). How do you debug them?

# Option 1: exec into container (if shell exists)
docker exec -it myapp-container /bin/sh    # alpine
docker exec -it myapp-container /bin/bash  # debian/ubuntu

# Run a command without interactive shell:
docker exec myapp-container cat /proc/1/cmdline   # check PID 1 command
docker exec myapp-container ls /app               # list app files

# Option 2: docker cp — extract files without shell
docker cp myapp-container:/app/logs/error.log ./error.log
docker cp ./fixed-config.json myapp-container:/app/config.json

# Option 3: Ephemeral debug container (Docker 23+)
# Attach a debug container to the SAME namespace as the target.
# The debug container has tools; it SEES the target's filesystem.
docker debug myapp-container                     # Docker Desktop feature
# OR:
docker run -it --rm \
  --pid=container:myapp-container \              # share PID namespace
  --net=container:myapp-container \              # share network namespace
  --volumes-from myapp-container \              # share volumes
  nicolaka/netshoot \                            # debug toolkit image
  /bin/bash

# Option 4: docker commit — save container state for forensics
# If a container is crashing, commit its state to an image
# before it restarts, then inspect at leisure.
docker commit myapp-container myapp:forensics-$(date +%s)
docker run -it myapp:forensics-<timestamp> /bin/sh


# ============================================================
# SECTION 12: REAL-WORLD 3-TIER ARCHITECTURE EXAMPLE
# ============================================================
# Production setup combining all patterns above:
#
# NETWORK LAYOUT:
#   internet → nginx:443 → [frontend net] → api:8000 → [backend net] → postgres:5432
#                                                                     → redis:6379
#
# All services:
#   - Exec form CMD (SIGTERM propagation)
#   - tini as PID 1 (--init or ENTRYPOINT tini)
#   - Health checks (service_healthy dependencies)
#   - stdout/stderr logging with rotation
#   - Named image tags (never :latest)
#   - Resource limits (--memory, --cpus)
#   - Non-root user
#   - Read-only FS + targeted tmpfs
#
# Deploy process:
#   1. CI builds + scans + tags: myapp:1.4.0-abc1234
#   2. Push to registry
#   3. `docker service update --image myapp:1.4.0-abc1234`
#   4. Swarm rolls one replica at a time, checks health gates
#   5. Monitor with `docker service ps myapp-service`
#   6. If unhealthy: `docker service rollback myapp-service`

echo "Docker production patterns reference loaded."
