# ============================================================
# L03: Multi-Stage Builds — Tiny Production Images
# ============================================================
# WHAT: Multi-stage builds allow you to use multiple FROM
#       instructions in a single Dockerfile. Each FROM starts
#       a new stage with its own filesystem. You COPY artifacts
#       from earlier stages into later ones — leaving behind
#       all the build tooling.
# WHY:  Build dependencies (compilers, dev headers, test tools,
#       pip, npm, cargo) are needed to BUILD the app but not to
#       RUN it. Multi-stage builds keep them out of the final
#       image, achieving:
#       - Dramatically smaller images (10x-50x smaller is common)
#       - Smaller attack surface (fewer tools = fewer CVEs)
#       - Faster image pulls in production
#       - Cleaner separation of build and runtime concerns
# LEVEL: Advanced
# ============================================================
# CONCEPT OVERVIEW:
#   Traditional single-stage:
#     FROM python:3.12 (900MB)
#     RUN pip install build tools, compile C extensions...
#     COPY app code
#     → Final image: 1.2GB with everything including gcc, pip, etc.
#
#   Multi-stage:
#     Stage 1 (builder): FROM python:3.12 — install everything
#     Stage 2 (final):   FROM python:3.12-slim — COPY only the
#                        compiled result from stage 1
#     → Final image: 150MB with only runtime requirements
#
# PRODUCTION USE CASE:
#   - Python: compile C extensions in full image, copy .so files
#   - Node.js: build React/Next.js, serve static output with nginx
#   - Go: compile binary in golang image, run in scratch
#   - Java: maven build in JDK image, run in JRE image
#
# COMMON MISTAKES:
#   - COPY --from with wrong stage name/index (off-by-one errors)
#   - Forgetting to copy ALL needed runtime files (missing .so libs)
#   - Building unnecessarily large builder stages (install only
#     what the build actually needs)
#   - Not naming stages (numeric --from=0 is fragile)
# ============================================================


# ============================================================
# EXAMPLE 1: Python — Build C extensions, run in slim
# ============================================================
# Scenario: FastAPI app with numpy, pandas, psycopg2.
# These packages have C extensions that require gcc, headers.
# We compile them in the full image, then copy only the
# resulting .so files and pure Python to the slim runtime.


# --- STAGE 1: Builder ---
# Full python image has build tools (gcc, make, pip, etc.)
# "builder" is the stage name — referenced in COPY --from below.

FROM python:3.12.3 AS python-builder
# NOT slim/alpine. We want the full image with gcc, libpq-dev, etc.
# This image will be large (~1GB) but it's NEVER shipped to prod.
# It exists only during the build on CI.

WORKDIR /build

# Install system-level build dependencies.
# libpq-dev: needed to compile psycopg2 (PostgreSQL client)
# libffi-dev: needed for cffi (Python cryptography, etc.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# We install into a custom prefix so we can COPY just that dir
# into the final image cleanly. This avoids polluting system Python.
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
# --prefix=/install  → Installs packages into /install/lib/python3.12/
#   site-packages/ instead of the system Python path.
#   This isolated directory is easy to COPY wholesale to the final image.


# --- STAGE 2: Final runtime image ---
# Switch to the slim base — much smaller, no build tools.

FROM python:3.12.3-slim AS python-final

# SIZE COMPARISON (approximate):
#   python:3.12.3         → ~1.0 GB (full)
#   python:3.12.3-slim    → ~150 MB (no build tools, no docs)
#   Our final image       → ~180 MB (slim + installed packages)
#   VS single-stage full  → ~1.3 GB (everything, including gcc)
#   SAVINGS: ~1.1 GB, or ~85% smaller

WORKDIR /app

# Install only RUNTIME system libraries (not -dev headers, not gcc)
# libpq5: runtime PostgreSQL client library (psycopg2 needs this)
# libffi8: runtime FFI library
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        libffi8 \
    && rm -rf /var/lib/apt/lists/*

# COPY compiled packages from the builder stage.
# COPY --from=<stage_name> <src_in_stage> <dest_in_current_stage>
COPY --from=python-builder /install /usr/local
# /install was our --prefix. Copying it to /usr/local merges it
# with the system Python's site-packages. Python will find
# all the compiled packages automatically.

# COPY app code from the build context (local files)
COPY src/ ./src/
COPY config/ ./config/

# Create non-root user for security (see L02)
RUN groupadd --system --gid 1001 appgroup \
    && useradd --system --uid 1001 --gid appgroup \
               --no-create-home --shell /sbin/nologin appuser \
    && chown -R appuser:appgroup /app

USER appuser
EXPOSE 8000

ENTRYPOINT ["uvicorn"]
CMD ["src.main:app", "--host", "0.0.0.0", "--port", "8000"]


# ============================================================
# EXAMPLE 2: Node.js + React → Nginx
# ============================================================
# Scenario: React frontend built with npm, served by nginx.
# The node_modules directory is typically 200-500MB.
# We build the static files, then throw away node_modules entirely.


FROM node:20.12-alpine AS node-builder
# Alpine keeps the builder stage smaller too.
# node:20.12-alpine ≈ 130MB vs node:20.12 ≈ 1.1GB

WORKDIR /app

# Layer cache strategy: copy package files first, install, then code.
# node_modules rebuild only when package.json/lock changes.
COPY package.json package-lock.json ./
RUN npm ci --only=production=false
# npm ci (clean install): faster than npm install, uses lock file
# exactly, deletes node_modules before install (reproducible).
# --only=production=false: include devDependencies (needed for build).

COPY . .
RUN npm run build
# Produces /app/dist/ (or /app/build/ depending on your config)
# with optimized static HTML/CSS/JS bundles.

# Check what we built:
# RUN ls -la /app/dist/  # Uncomment to debug build output path


FROM nginx:1.25.3-alpine AS node-final
# nginx:1.25.3-alpine ≈ 45MB
# We need NOTHING from Node, npm, or node_modules.

# Copy only the static build output — typically 1-10MB
COPY --from=node-builder /app/dist /usr/share/nginx/html
# /usr/share/nginx/html is nginx's default document root.

# Custom nginx config for SPA routing (React Router, Vue Router)
# Without this, direct URL access (e.g., /about) returns 404.
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Example nginx.conf for SPA:
#   server {
#     listen 80;
#     root /usr/share/nginx/html;
#     try_files $uri $uri/ /index.html;  # fallback to index.html
#   }

EXPOSE 80
# nginx base image already sets CMD ["nginx", "-g", "daemon off;"]
# "daemon off" is critical — it keeps nginx in the foreground
# so it stays as PID 1 and Docker can track it.

# FINAL SIZES:
#   node-builder stage:  ~1.3GB (alpine node + node_modules + source)
#   node-final image:    ~50MB  (nginx + static files)
#   SAVINGS: ~1.25 GB sent to production registry / pulled per pod


# ============================================================
# EXAMPLE 3: Go — Compile to binary, run in scratch
# ============================================================
# Go compiles to a single statically linked binary.
# The binary needs NO runtime libraries, NO interpreter, NO OS tools.
# We can run it in "scratch" — a completely empty image.


FROM golang:1.22.2-alpine AS go-builder
# golang:1.22.2-alpine ≈ 250MB — includes Go compiler, stdlib.
# Alpine version avoids glibc, which matters for static compilation.

WORKDIR /build

# Download dependencies first (layer cache strategy)
COPY go.mod go.sum ./
RUN go mod download
# go.mod and go.sum define dependencies like requirements.txt.
# They rarely change between commits, so this layer is usually cached.

COPY . .

# Build the binary with important flags for minimal/static output:
RUN CGO_ENABLED=0 \
    GOOS=linux \
    GOARCH=amd64 \
    go build \
    -ldflags="-w -s" \
    -o /app/server \
    ./cmd/server/
#
# CGO_ENABLED=0   → Disable C Go interface. Forces pure Go stdlib
#   implementations instead of linking to system C libraries.
#   Result: fully statically linked binary. No external .so needed.
#
# GOOS=linux      → Cross-compile target OS. If building on macOS,
#   this ensures a Linux binary. In CI (Linux), same as default.
#
# GOARCH=amd64    → Target architecture. For ARM64 (Apple M1,
#   AWS Graviton), use arm64. See L08 for multi-platform builds.
#
# -ldflags="-w -s" → Linker flags:
#   -w: Omit DWARF debug information (~30% smaller binary)
#   -s: Omit symbol table (~10% smaller binary)
#   Result: binary cannot be debugged with dlv, but that's fine
#   for production. Keep an unstripped binary in your build
#   artifacts for post-mortem analysis if needed.


FROM scratch AS go-final
# "scratch" is a special Docker keyword — an empty image.
# No OS, no shell, no filesystem at all. Just our binary.
# Image size: only the size of the compiled binary (typically 10-30MB)
# VS golang:1.22 base: 800MB
# SAVINGS: 770MB+. Every pod pull is 30x faster.

# SCRATCH LIMITATIONS:
#   - No shell (cannot "docker exec -it container sh")
#   - No CA certificates (HTTPS calls will fail unless you add them)
#   - No /tmp directory
#   - No /etc/passwd (non-root UID must be specified numerically)
#
# SOLUTION: Copy what you need from the builder.

# Copy CA certificates for HTTPS support
COPY --from=go-builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
# Without this, any HTTPS outbound call gets: "x509: certificate
# signed by unknown authority". Alpine's ca-certificates package
# provides this file.

# Copy timezone data if your app uses time.LoadLocation()
COPY --from=go-builder /usr/share/zoneinfo /usr/share/zoneinfo

# Copy the compiled binary
COPY --from=go-builder /app/server /server

# Run as a non-root UID (no /etc/passwd in scratch, use numeric UID)
# This requires your app to not need any /home or /etc/passwd lookups.
USER 1001:1001

EXPOSE 8080

# Exec form is mandatory — scratch has no shell to use shell form.
ENTRYPOINT ["/server"]


# ============================================================
# BUILD COMMANDS AND THE --target FLAG
# ============================================================

# Build the default (final) stage:
#   docker build -t myapp:1.0 .

# Build only up to a specific stage (for testing/debugging):
#   docker build --target python-builder -t myapp:builder .
#   docker run --rm -it myapp:builder bash
#   # Now you're inside the builder with all tools — debug build issues

# Build a specific named stage as the final output:
#   docker build --target go-builder -t myapp:build-debug .

# Named stages prevent brittle --from=0, --from=1 numbering.
# If you insert a stage, numeric indexes all shift. Names don't.


# ============================================================
# ARCHITECTURE SUMMARY
# ============================================================
# Multi-stage build flow:
#
#   [Source Code]
#       │
#       ▼
#   ┌─────────────────────────────┐
#   │  Stage 1: builder           │  ← Large image, build tools
#   │  - Full base image          │  ← Runs on CI worker ONLY
#   │  - Compilers, dev headers   │  ← Never pushed to registry
#   │  - Produces: artifacts      │
#   └──────────────┬──────────────┘
#                  │  COPY --from=builder
#                  ▼
#   ┌─────────────────────────────┐
#   │  Stage 2: final             │  ← Tiny image, no build tools
#   │  - Minimal base image       │  ← Pushed to registry
#   │  - Runtime libs only        │  ← Pulled by every pod in prod
#   │  - Just the artifacts       │
#   └─────────────────────────────┘
#
# The builder stage is a throwaway — it never leaves the CI machine.
# Only the tiny final stage becomes the production image.
