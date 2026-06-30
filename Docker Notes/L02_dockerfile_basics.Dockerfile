# ============================================================
# L02: Dockerfile Basics — Writing Production-Quality Images
# ============================================================
# WHAT: Every instruction in a Dockerfile, what it does, why it
#       matters, and how it affects layer caching, image size,
#       and security.
# WHY:  A badly written Dockerfile produces slow builds, huge
#       images, security vulnerabilities, and hard-to-debug
#       runtime failures. A well-written one is a competitive
#       advantage: faster CI, smaller attack surface, cheaper
#       image transfers.
# LEVEL: Foundations
# ============================================================
# CONCEPT OVERVIEW:
#   Docker reads a Dockerfile top-to-bottom. Each instruction
#   creates a new LAYER. Layers are cached: if the instruction
#   and all previous layers are unchanged, Docker reuses the
#   cached layer (no re-execution). The caching rules are:
#
#   - FROM:        Cache busted if the base image digest changes.
#   - RUN:         Cache busted if the instruction string changes.
#   - COPY/ADD:    Cache busted if the SOURCE FILES change (Docker
#                  checksums the file content, not the timestamp).
#   - ENV/ARG:     Cache busted if the value changes (affects all
#                  subsequent layers).
#
#   GOLDEN RULE OF LAYER CACHING:
#   Put things that change LEAST at the top.
#   Put things that change MOST at the bottom.
#   This maximises cache hits in CI and local development.
#
# PRODUCTION USE CASE:
#   A Python web service at a startup. The team deploys dozens
#   of times per day. Every second saved in the build pipeline
#   compounds. Correct layer ordering means only the last 2-3
#   layers ever rebuild on a normal code push.
#
# COMMON MISTAKES:
#   - RUN apt-get update on its own line (cache poison: update
#     can be skipped while install uses stale package lists)
#   - COPY . . before installing dependencies (invalidates the
#     dependency layer on EVERY code change)
#   - Running as root (security risk in production)
#   - Using ADD when COPY is sufficient (ADD has hidden behavior)
#   - Shell form ENTRYPOINT — cannot receive signals properly
#   - Not pinning base image versions (non-reproducible builds)
# ============================================================


# ============================================================
# INSTRUCTION 1: FROM — Choose your base image
# ============================================================
# FROM <image>[:<tag>] [AS <name>]
#
# The base image is the foundation every subsequent layer builds
# on. Choosing it well means:
#   - Smaller images (less to download, less attack surface)
#   - Faster builds (fewer dependencies to install)
#   - Fewer CVEs (smaller OS = fewer vulnerable packages)
#
# COMMON BASE IMAGE FAMILIES:
#
#   ubuntu:22.04      Full Ubuntu. Easy to use, large (~80MB).
#                     Good for development; avoid in production.
#
#   debian:bookworm-slim  Debian without docs, man pages, etc.
#                         Good balance: ~75MB, wide package support.
#
#   python:3.12-slim  Official Python on debian-slim. ~150MB.
#                     Good default for Python production images.
#
#   python:3.12-alpine  Python on Alpine Linux. ~50MB.
#                       WARNING: Alpine uses musl libc instead of
#                       glibc. Many Python C extensions (numpy,
#                       pandas, cryptography) must be compiled from
#                       source. Build times are much longer.
#                       Use slim unless image size is critical.
#
#   alpine:3.19       Bare Alpine. ~7MB. Maximum control.
#                     You install exactly what you need.
#
#   scratch           Empty image. Only for statically compiled
#                     binaries (Go, Rust). See L03.
#
#   gcr.io/distroless/python3-debian12
#                     Google's distroless: no shell, no package
#                     manager, no unnecessary OS tools. Minimum
#                     attack surface. Harder to debug but very secure.
#
# PINNING STRATEGY:
#   BAD:  FROM python:3          # Could be 3.9, 3.10, 3.12 — unknown
#   BAD:  FROM python:latest     # Changes whenever Python releases
#   OK:   FROM python:3.12-slim  # Pinned to minor version
#   BEST: FROM python:3.12.3-slim  # Pinned to patch version
#   PROD: FROM python:3.12.3-slim@sha256:<digest>  # Immutable

FROM python:3.12.3-slim AS base
# We use "AS base" to name this stage for multi-stage builds (L03).
# Even in single-stage Dockerfiles, naming stages is a good habit.


# ============================================================
# INSTRUCTION 2: LABEL — Image metadata
# ============================================================
# LABEL key="value" key2="value2"
#
# Metadata attached to the image. Not part of the filesystem.
# Searchable with: docker images --filter "label=maintainer=..."
# Useful for:
#   - Tracking which CI build produced this image
#   - Linking to source code (org.opencontainers.image.source)
#   - Specifying maintainer for automated security tooling

LABEL maintainer="platform-team@company.com" \
      org.opencontainers.image.title="myapp" \
      org.opencontainers.image.description="Production web API" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.source="https://github.com/company/myapp"
# The opencontainers.image.* labels follow OCI standard conventions.
# GitHub Container Registry (ghcr.io) uses these to auto-populate
# the package page with description, source link, and version.


# ============================================================
# INSTRUCTION 3: ENV — Environment variables (baked in)
# ============================================================
# ENV KEY=VALUE
#
# Sets environment variables that persist into the running container
# AND into subsequent Dockerfile build steps.
#
# USE FOR:
#   - Runtime configuration that doesn't change per deployment
#   - Python path setup, locale settings, etc.
#   - Telling apps they're running in a container
#
# DO NOT USE FOR:
#   - Secrets (they appear in "docker inspect" and image history)
#   - Values that differ between environments (pass those at runtime
#     with -e or --env-file)

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

# PYTHONDONTWRITEBYTECODE=1  → Don't write .pyc files. Keeps the
#   container filesystem cleaner; saves a tiny amount of space.
#
# PYTHONUNBUFFERED=1  → Python won't buffer stdout/stderr.
#   CRITICAL: Without this, logs written with print() or logging
#   may never appear in "docker logs" because Python buffers output
#   when it detects non-TTY stdout. Always set this.
#
# PYTHONHASHSEED=random  → Randomize hash seeds for security.
#   Prevents hash-collision DoS attacks against dict/set operations.
#
# PIP_NO_CACHE_DIR=1  → pip won't cache downloaded wheels inside
#   the container filesystem. Reduces image size slightly.
#
# PORT=8000  → Convention: document the port the app listens on.
#   The app should read this variable: server.listen(os.environ["PORT"])


# ============================================================
# INSTRUCTION 4: ARG — Build-time variables (not in final image)
# ============================================================
# ARG NAME[=default]
#
# Unlike ENV, ARG values are only available during the BUILD.
# They do NOT persist into the running container (unless you
# explicitly copy them into an ENV).
#
# Override with: docker build --build-arg APP_VERSION=2.0.0 .
#
# USE FOR:
#   - CI pipeline metadata (build number, git SHA)
#   - Switching between dev/prod dependencies at build time
#   - Parameterizing the base image version

ARG APP_VERSION=dev
ARG BUILD_DATE="unknown"
ARG GIT_SHA="unknown"

# These ARG values can be baked into LABEL at build time:
LABEL org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${GIT_SHA}"

# IMPORTANT: ARG before FROM is accessible in FROM only.
#   ARG after FROM is accessible in RUN/COPY/etc.
# SECURITY WARNING: Build args appear in `docker history` output.
#   Do NOT pass secrets as ARG values.


# ============================================================
# INSTRUCTION 5: WORKDIR — Set the working directory
# ============================================================
# WORKDIR /path/to/dir
#
# Sets the working directory for all subsequent RUN, COPY, ADD,
# ENTRYPOINT, and CMD instructions. Also sets the default
# directory for "docker exec" sessions.
#
# If the directory doesn't exist, WORKDIR creates it.
#
# NEVER use: RUN cd /app && ...
# That only affects the current RUN step. WORKDIR persists.
#
# Convention for web apps: /app
# Convention for scripts:  /scripts or /opt/app

WORKDIR /app


# ============================================================
# INSTRUCTION 6: RUN — Execute commands during build
# ============================================================
# RUN <command>  (shell form — runs via /bin/sh -c "...")
# RUN ["executable", "arg1", "arg2"]  (exec form)
#
# CRITICAL LAYER CACHING PATTERN:
# Each RUN creates ONE layer. Chain all related commands with &&
# to keep them in the same layer. This prevents stale package
# list caching and keeps layer count low.
#
# ALWAYS: apt-get update && apt-get install in the SAME RUN command.
# NEVER:  separate "RUN apt-get update" and "RUN apt-get install"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        # List each package on its own line for readability/diffs
        curl \
        gcc \
        libpq-dev \
    # Clean up apt cache in the SAME layer to avoid bloating
    # the image. apt's cache lives in /var/lib/apt/lists/ and
    # /var/cache/apt/archives/ — remove both.
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /var/cache/apt/archives/*
# --no-install-recommends: Don't install "recommended" packages.
#   apt marks many packages as "recommended" that are rarely needed
#   in containers. This flag can cut 30-50% off the install size.

# ============================================================
# LAYER CACHING STRATEGY: Copy requirements FIRST, code SECOND
# ============================================================
# This is the most impactful optimization in Python Dockerfiles.
#
# Problem: If you COPY . . first, any change to ANY file (even a
# README.md) invalidates the COPY layer, which forces pip install
# to re-run on every build. That's 2-5 minutes wasted.
#
# Solution: Copy ONLY the dependency manifest first, run the
# install, THEN copy the rest of the code. pip install is cached
# as long as requirements.txt doesn't change.

COPY requirements.txt .
# This COPY only gets cache-busted when requirements.txt changes.
# On a normal feature branch push, this file rarely changes.
# pip install below will be served from cache 90%+ of the time.

RUN pip install --no-cache-dir -r requirements.txt
# --no-cache-dir: Don't store the pip download cache in the layer.
#   pip's cache is useful on developer laptops (re-use downloaded
#   wheels), but inside a Dockerfile RUN it only bloats the layer.
#   The result of pip install (site-packages) IS kept; just not the
#   raw wheel files.

# NOW copy the application code.
# This layer rebuilds on every code change — but that's fine,
# because it's cheap (just copying files, no compilation).
COPY src/ ./src/
COPY config/ ./config/


# ============================================================
# INSTRUCTION 7: COPY vs ADD — Know the difference
# ============================================================
# Both copy files from the build context into the image.
#
# COPY <src> <dest>
#   - Simple and explicit. Does exactly what it says.
#   - Preferred for everything.
#
# ADD <src> <dest>
#   - Has two magical behaviors on top of COPY:
#     1. If <src> is a URL, it downloads the file (use curl instead
#        — you get better control over error handling and caching).
#     2. If <src> is a .tar.gz/.tar.bz2/.tar.xz, it auto-extracts.
#   - This magic makes ADD surprising and harder to audit.
#
# RULE: Use COPY unless you specifically need ADD's tar extraction.
#       Even then, consider: RUN curl ... | tar xz instead.

# COPY with --chown: set file ownership in one step
COPY --chown=appuser:appgroup scripts/ /app/scripts/
# Without --chown, COPY'd files are owned by root.
# --chown avoids a separate RUN chown ... step (extra layer).
# Note: --chown creates the user in the image layer cache key.


# ============================================================
# INSTRUCTION 8: USER — Run as non-root
# ============================================================
# USER <user>[:<group>]
# USER <UID>[:<GID>]
#
# By default, containers run as UID 0 (root). If an attacker
# escapes the container (container breakout vulnerability), they
# have root access to the host. Running as non-root limits the
# blast radius.
#
# Some orchestrators (Kubernetes with PodSecurityPolicy/PSA,
# OpenShift) REFUSE to run containers as root by default.
#
# PATTERN: Create the user and group, then switch to it.

RUN groupadd --system --gid 1001 appgroup \
    && useradd --system --uid 1001 --gid appgroup \
               --no-create-home --shell /sbin/nologin \
               appuser
# --system: Creates a system user/group (UID/GID in low range).
# --no-create-home: Don't create /home/appuser (saves space, no
#   risk of home dir being writable).
# --shell /sbin/nologin: Prevents interactive login to this user
#   (belt-and-suspenders security).

# Set ownership of the app directory before switching user
RUN chown -R appuser:appgroup /app

USER appuser
# All subsequent RUN, CMD, ENTRYPOINT instructions run as appuser.
# docker exec will also default to appuser (override with -u root).


# ============================================================
# INSTRUCTION 9: EXPOSE — Document the port (NOT publish it)
# ============================================================
# EXPOSE <port>[/<protocol>]
#
# EXPOSE is DOCUMENTATION. It tells developers and tools which
# port the application listens on. It does NOT open any port
# on the host. Port publishing requires -p at docker run time.
#
# EXPOSE does enable container-to-container communication within
# the same Docker network (without -p), because containers on
# the same network can reach each other on any port regardless.
# EXPOSE just serves as a hint.

EXPOSE 8000/tcp
# Documents that the app listens on TCP port 8000.
# Match this with the PORT environment variable above.


# ============================================================
# INSTRUCTION 10: ENTRYPOINT vs CMD — The critical difference
# ============================================================
#
# BOTH specify what runs when the container starts.
# The key difference is how they interact and how overridable
# they are.
#
#
# CMD ["executable", "arg1"] — Exec form (PREFERRED)
# CMD executable arg1        — Shell form (runs via /bin/sh -c)
# CMD ["arg1", "arg2"]       — Default arguments for ENTRYPOINT
#
# ENTRYPOINT ["executable", "arg1"]  — Exec form (PREFERRED)
# ENTRYPOINT executable arg1         — Shell form
#
#
# EXEC FORM vs SHELL FORM — the most critical distinction:
#
#   Exec form:   ["uvicorn", "src.main:app"]
#   Shell form:  uvicorn src.main:app
#
#   Shell form wraps the command in: /bin/sh -c "uvicorn ..."
#   This means /bin/sh is PID 1, NOT your app. When Docker
#   sends SIGTERM on "docker stop", /bin/sh receives it but
#   typically does NOT forward it to your app. Your app never
#   gets a chance to shut down gracefully. It gets SIGKILL
#   after the timeout.
#
#   Exec form runs your command DIRECTLY as PID 1. SIGTERM
#   goes straight to your app. Graceful shutdown works.
#
#   ALWAYS use exec form for ENTRYPOINT and CMD in production.
#
#
# HOW THEY COMBINE:
#
#   +------------------+------------------+---------------------------+
#   | ENTRYPOINT       | CMD              | Result                    |
#   +------------------+------------------+---------------------------+
#   | not set          | ["uvicorn","app"]| uvicorn app               |
#   | ["uvicorn"]      | ["app","--port"] | uvicorn app --port        |
#   | ["uvicorn"]      | not set          | uvicorn                   |
#   | not set          | not set          | Error                     |
#   +------------------+------------------+---------------------------+
#
#   docker run myimage --workers=4
#   If ENTRYPOINT=["uvicorn","app"], the "--workers=4" APPENDS to
#   entrypoint: "uvicorn app --workers=4".
#   CMD is REPLACED by the docker run argument.
#
# PATTERN: Use ENTRYPOINT for the executable, CMD for default args.
# This makes it easy to override args without losing the executable.

ENTRYPOINT ["uvicorn"]
CMD ["src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

# Override at runtime:
#   docker run myapp src.main:app --port 9000 --reload
#
# Override entrypoint for debugging:
#   docker run --entrypoint sh myapp
#   docker run --entrypoint python myapp -c "import sys; print(sys.version)"


# ============================================================
# FULL PICTURE: Layer order recap for this Dockerfile
# ============================================================
# Layer 1: FROM python:3.12.3-slim      (pulled from registry)
# Layer 2: LABEL ...                    (metadata, no disk impact)
# Layer 3: ENV ...                      (rarely changes)
# Layer 4: RUN apt-get install ...      (rarely changes)
# Layer 5: COPY requirements.txt        (changes when deps change)
# Layer 6: RUN pip install              (changes when deps change)
# Layer 7: COPY src/ config/            (changes on every commit)
# Layer 8: RUN groupadd / useradd       (rarely changes)
# Layer 9: USER appuser                 (rarely changes)
# Layer 10: EXPOSE / ENTRYPOINT / CMD   (rarely changes)
#
# On a normal code push, only Layer 7 rebuilds. Layers 1-6 and
# 8-10 are served from cache. Total rebuild time: ~2 seconds.


# ============================================================
# .dockerignore — What NOT to send to the build context
# ============================================================
# The build context is everything in the directory sent to the
# Docker daemon. Large contexts slow down every build.
# Create a .dockerignore file alongside your Dockerfile:
#
#   .git/              # Version control history (can be huge)
#   .gitignore
#   .env               # Never bake secrets into images
#   .env.*
#   __pycache__/       # Python bytecode
#   *.pyc
#   *.pyo
#   .pytest_cache/
#   .mypy_cache/
#   .coverage
#   htmlcov/
#   dist/
#   build/
#   *.egg-info/
#   node_modules/      # If mixed project
#   .venv/             # Virtual environment
#   venv/
#   Dockerfile         # No need to include this itself
#   docker-compose*.yml
#   README.md
#   docs/
#   tests/             # Optional: exclude tests from prod image
#
# Check context size: docker build . 2>&1 | head -5
# "Sending build context to Docker daemon  2.048kB"  ← good
# "Sending build context to Docker daemon  450.5MB"  ← bad
