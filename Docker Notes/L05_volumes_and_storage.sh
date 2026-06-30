#!/usr/bin/env bash

# ============================================================
# L05: Docker Volumes and Storage
# ============================================================
# WHAT: Mechanisms for persisting and sharing data in/between
#       Docker containers — bind mounts, named volumes, tmpfs.
# WHY:  Containers are ephemeral by design. Their writable layer
#       dies with them. Any data you care about (DB files, logs,
#       user uploads) must live OUTSIDE the container layer.
# LEVEL: Advanced
# ============================================================
# CONCEPT OVERVIEW:
#   Docker has three distinct storage mount types:
#
#   1. BIND MOUNT  — maps a host filesystem path into the container.
#      The container sees and can modify real host files.
#      Host path must exist before the container starts.
#
#   2. NAMED VOLUME — Docker-managed directory under /var/lib/docker/volumes/.
#      Docker creates and owns the path. Containers reference it
#      by name, not by host path. Survives container removal.
#
#   3. TMPFS MOUNT — RAM-backed, never touches disk. Exists only
#      while the container is running. Perfect for secrets, caches,
#      and scratch space you must NOT persist.
#
# PRODUCTION USE CASE:
#   Postgres data directory uses a named volume so data survives
#   container image updates. App configs use bind mounts in dev
#   for live editing. Credential files use tmpfs so they are
#   never written to the copy-on-write (CoW) layer or disk.
#
# COMMON MISTAKES:
#   - Using bind mounts in production: ties image to a specific
#     host path layout. Breaks portability.
#   - Forgetting volume declarations in docker-compose: each
#     compose-up recreates a fresh anonymous volume, losing data.
#   - Storing secrets in Docker ENV / image layers (inspectable
#     with `docker history`). Use tmpfs or Docker secrets instead.
#   - Not backing up named volumes before destructive operations.
# ============================================================


# ============================================================
# SECTION 1: BIND MOUNTS
# ============================================================
# Syntax: -v /absolute/host/path:/container/path[:options]
# The host path is mounted directly. The container SEES the
# actual host files — changes on either side are immediate.
#
# GOOD FOR:
#   - Development: live-reload source code without rebuilding.
#   - Accessing host config files (e.g., /etc/ssl/certs).
#
# BAD FOR:
#   - Production deployments: locks you to one host's layout.
#   - Portability: path /home/alice/project doesn't exist on
#     the production server or in CI.

# Mount current directory into /app in the container.
# ':z' on SELinux hosts relabels the content so the container
# can access it. Without :z you get "Permission denied" on RHEL/Fedora.
docker run -d \
  --name dev-app \
  -v "$(pwd)":/app:z \        # read-write bind mount (default)
  -p 8000:8000 \
  myapp:dev

# READ-ONLY bind mount: container can READ the config but cannot
# corrupt it. Critical for prod config files you control via CM.
docker run -d \
  --name nginx \
  -v /etc/nginx/nginx.conf:/etc/nginx/nginx.conf:ro \
  nginx:alpine


# ============================================================
# SECTION 2: NAMED VOLUMES
# ============================================================
# Docker manages the actual storage location (~/ /var/lib/docker/volumes/).
# You reference volumes by a logical name, not a filesystem path.
# Named volumes are the RECOMMENDED approach for production data.
#
# WHY BETTER THAN BIND MOUNTS IN PRODUCTION:
#   - No host path dependency.
#   - Docker Desktop (Mac/Windows) runs inside a Linux VM.
#     Named volumes live INSIDE that VM → no file-system bridge
#     → dramatically better I/O performance than bind mounts.
#   - Volume drivers let you back volumes on EBS, NFS, GCS, etc.

# --- Create a named volume explicitly ---
docker volume create pgdata
# Docker creates /var/lib/docker/volumes/pgdata/_data on Linux.

# --- List all volumes ---
docker volume ls
# Shows: DRIVER  VOLUME NAME
#        local   pgdata

# --- Inspect a volume: see its real host path ---
docker volume inspect pgdata
# Returns JSON with Mountpoint, Driver, Labels, Scope.
# Mountpoint: "/var/lib/docker/volumes/pgdata/_data"

# --- Use a named volume in a container ---
# Postgres stores all its data in /var/lib/postgresql/data.
# We map pgdata → that path. Even if the container is deleted
# and recreated (e.g., during image upgrade), the data survives.
docker run -d \
  --name postgres \
  -e POSTGRES_PASSWORD=secret \
  -v pgdata:/var/lib/postgresql/data \  # named volume
  postgres:16

# --- Remove a specific volume (DESTRUCTIVE — data is gone) ---
docker volume rm pgdata

# --- Prune ALL unused volumes (not referenced by any container) ---
# Add -f to skip confirmation prompt.
docker volume prune -f
# WARNING: This is irreversible. Run `docker volume ls` first.


# ============================================================
# SECTION 3: SHARING VOLUMES BETWEEN CONTAINERS
# ============================================================
# Pattern 1: Named volume referenced by multiple containers.
# They share the same underlying data directory. Used for
# sidecars (log shippers reading app logs, init containers).
#
# CAUTION: Concurrent writes need application-level locking.
# Two Postgres instances on the same volume will corrupt data.

docker run -d --name writer -v shared-logs:/logs myapp:latest
docker run -d --name log-shipper -v shared-logs:/logs:ro fluent/fluent-bit

# Pattern 2: --volumes-from
# Inherits ALL volume mounts from another container.
# Legacy pattern — prefer named volumes in modern setups.
docker run -d --name data-container -v /data busybox
docker run -d --name app --volumes-from data-container myapp


# ============================================================
# SECTION 4: TMPFS MOUNTS (IN-MEMORY STORAGE)
# ============================================================
# tmpfs lives in host RAM. It is:
#   - Fast (memory speeds, no disk I/O)
#   - Ephemeral (gone when container stops or restarts)
#   - Invisible to docker commit / image layers
#
# PRODUCTION USE CASES:
#   - Secrets (tokens, private keys) that must NEVER be written
#     to disk or captured in container layers.
#   - High-speed temporary scratch space (ML inference, image
#     processing) where you don't want disk I/O bottleneck.
#   - Session tokens and nonces.

# Basic tmpfs mount (size defaults to half the host RAM)
docker run -d \
  --name secure-app \
  --tmpfs /app/temp \          # in-memory /app/temp
  myapp:latest

# Sized tmpfs: limit memory usage to avoid host RAM exhaustion
docker run -d \
  --name secure-app \
  --tmpfs /app/temp:size=64m,mode=1777 \   # 64 MB, world-writable sticky dir
  myapp:latest

# Secrets in tmpfs — the gold standard for runtime secrets.
# Mount secrets in /run/secrets. :ro prevents the app from
# writing back to the secret file.
docker run -d \
  --name api \
  --tmpfs /run/secrets:ro,size=1m \
  myapp:latest
# Then in entrypoint.sh: DB_PASS=$(cat /run/secrets/db_password)


# ============================================================
# SECTION 5: BACKUP AND RESTORE NAMED VOLUMES
# ============================================================
# Named volumes have no native "backup" command.
# The pattern: spin up a temporary alpine container that mounts
# BOTH the target volume and a host directory, then tar.

# --- BACKUP ---
# Mount pgdata at /data (read-only, don't corrupt it during backup),
# mount current host dir at /backup, then tar the volume out.
docker run --rm \
  -v pgdata:/data:ro \
  -v "$(pwd)":/backup \
  alpine \
  tar czf /backup/pgdata_backup_$(date +%Y%m%d).tar.gz -C /data .
# Result: pgdata_backup_20240615.tar.gz in current host directory.

# --- RESTORE ---
# Create a fresh empty volume, then extract the backup into it.
docker volume create pgdata_restored
docker run --rm \
  -v pgdata_restored:/data \
  -v "$(pwd)":/backup \
  alpine \
  tar xzf /backup/pgdata_backup_20240615.tar.gz -C /data
# Now pgdata_restored contains the backup. Point your container at it.


# ============================================================
# SECTION 6: READ-ONLY VOLUMES (SECURITY BEST PRACTICE)
# ============================================================
# Append :ro to any volume mount to make it read-only from
# the container's perspective. The host (or other containers
# with rw access) can still modify the files.
#
# WHY: Defence in depth. A compromised container process cannot
#      tamper with source configs, SSL certs, or scripts —
#      even if it achieves RCE inside the container.

docker run -d \
  --name api \
  -v /etc/ssl/certs:/etc/ssl/certs:ro \         # OS certs: read-only
  -v /opt/myapp/config:/app/config:ro \          # app config: read-only
  -v app-uploads:/app/uploads \                  # uploads: read-write OK
  myapp:latest

# Combine with --read-only on the whole container:
# Only tmpfs paths are writable, everything else is immutable.
docker run -d \
  --name hardened-api \
  --read-only \                          # entire container FS is read-only
  --tmpfs /tmp \                         # app needs a writable /tmp
  --tmpfs /var/run \                     # PID files go here
  -v /opt/myapp/config:/app/config:ro \
  myapp:latest


# ============================================================
# SECTION 7: STORAGE DRIVERS (UNION FILESYSTEMS)
# ============================================================
# Every Docker image is made of stacked read-only LAYERS.
# When a container runs, Docker adds a thin read-write layer
# on top using a UNION FILESYSTEM (Copy-on-Write).
#
# overlay2 (default, recommended):
#   - Uses kernel overlayfs. Upper dir (rw) overlays lower dirs (ro).
#   - When a container writes a file from the image, it is
#     COPIED UP to the upper (container) layer first.
#   - Very efficient for reads; writes trigger a one-time copy.
#   - Supported on ext4, xfs (with d_type=true), Btrfs.
#
# WHY THIS MATTERS:
#   - Containers that write a LOT to their own layer are slower
#     than containers that write to mounted volumes (no CoW).
#   - Big files written inside the container (not to a volume)
#     inflate the container's writable layer permanently until
#     the container is removed.
#
# Check which storage driver Docker is using:
docker info | grep "Storage Driver"
# Expected: Storage Driver: overlay2


# ============================================================
# SECTION 8: VOLUME DRIVERS (CLOUD-BACKED STORAGE)
# ============================================================
# The default "local" driver stores data on the host machine.
# Volume DRIVERS are plugins that back volumes on external
# storage: AWS EBS, GCE Persistent Disk, NFS, Ceph, etc.
#
# USE CASES:
#   - Multi-host clusters (Swarm): containers on different nodes
#     need to access the same data. Local volumes are per-node.
#   - Cloud-native storage with snapshotting and replication.
#
# Example drivers: rexray/ebs, rexray/gcepd, convoy, flocker.
# Note: In Kubernetes this role is filled by PersistentVolumes
# and StorageClasses. Volume drivers are primarily for Swarm.

# Create an EBS-backed volume (requires rexray/ebs plugin):
docker volume create \
  --driver rexray/ebs \
  --opt size=20 \           # 20 GB EBS volume
  --opt volumetype=gp3 \
  my-ebs-volume

docker run -d \
  --name db \
  -v my-ebs-volume:/var/lib/postgresql/data \
  postgres:16


# ============================================================
# SECTION 9: REAL-WORLD DOCKER COMPOSE VOLUME EXAMPLE
# ============================================================
# Illustrates how volumes are declared and used across multiple
# services in docker-compose.yml format (shown as comments here).

# In docker-compose.yaml:
#
# services:
#   postgres:
#     image: postgres:16
#     volumes:
#       - pgdata:/var/lib/postgresql/data   # named volume: persistent DB
#     environment:
#       POSTGRES_PASSWORD_FILE: /run/secrets/db_password
#
#   redis:
#     image: redis:7-alpine
#     volumes:
#       - redisdata:/data                   # named volume: persistent cache
#
#   api:
#     build: ./api
#     volumes:
#       - ./api:/app:z                      # bind mount: hot reload in dev
#       - /app/node_modules                 # anonymous vol: isolate deps
#     tmpfs:
#       - /tmp                              # in-memory temp
#       - /run/secrets                      # secrets never hit disk
#
# volumes:
#   pgdata:     # declares the named volume — Docker creates it on first run
#   redisdata:

echo "Docker volumes and storage reference loaded."
