# ============================================================
# L08: Production Deployment for FastAPI
# ============================================================
# WHAT: Dockerisation, pydantic-settings config, health probes,
#       Kubernetes manifests, graceful shutdown, secrets
#       management, structured logging, Prometheus metrics,
#       and zero-downtime rolling deploys.
# WHY:  A FastAPI app that works locally breaks in prod because
#       of missing health endpoints, hard-coded config, missing
#       SIGTERM handling, and no observability. This file covers
#       every layer you need before going live.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    Production deployment is a stack of concerns, each of which
    can independently cause downtime or security incidents:

    Config: pydantic-settings reads env vars with type validation.
    One class, one source of truth; @lru_cache means it's read
    once per process, not on every request.

    Health: Kubernetes needs two distinct endpoints. /health
    (liveness) tells K8s whether to restart the pod. /ready
    (readiness) tells K8s whether to send traffic. They are NOT
    the same. A pod can be alive but not yet ready (DB still
    connecting). A pod can fail readiness without being restarted
    if liveness passes — traffic is drained until it recovers.

    Migrations: Alembic runs as a K8s init container before the
    main app containers start. This prevents the race condition
    where pod-1 runs migrations while pod-2 starts with the old
    schema.

    Graceful shutdown: SIGTERM → Uvicorn stops accepting new
    connections, drains in-flight requests (up to --graceful-
    timeout seconds), then exits. Without this, rolling deploys
    drop ~1-5% of requests as pods are killed mid-flight.

    Observability: JSON logging so log aggregators (Datadog,
    Splunk, Loki) can parse fields without regex. Prometheus
    metrics auto-instrumented by prometheus-fastapi-instrumentator.
    OpenTelemetry traces for distributed tracing.

PRODUCTION USE CASE:
    SaaS API: 3 pods, rolling deploy every day. HPA scales to
    10 pods on CPU > 70%. PodDisruptionBudget guarantees ≥ 2
    pods stay up during node drain. Init container runs
    migrations atomically. Vault Agent injects DB credentials
    as env vars at pod startup — no secrets in git or .env.

COMMON MISTAKES:
    1. Running as root in Docker — any container escape gives
       root access to the host. Always add USER nonroot.
    2. Putting secrets in .env files committed to git — rotate
       them immediately, then switch to K8s External Secrets or
       Vault. GitGuardian scans public repos continuously.
    3. Having only one health endpoint for both liveness and
       readiness — K8s will restart a pod that's merely waiting
       for the DB to accept connections on startup.
    4. No PodDisruptionBudget — a node drain can evict ALL pods
       simultaneously, causing a complete outage. PDB limits
       concurrent voluntary disruptions.
    5. Offset-reading settings on every request — use
       @lru_cache on get_settings() so it reads env vars once.
"""

import logging
import os
import signal
import time
from functools import lru_cache
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Optional observability imports — guarded so the file is importable without
# all prod deps installed in a dev environment.
# ---------------------------------------------------------------------------
try:
    from prometheus_fastapi_instrumentator import Instrumentator

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

try:
    from pythonjsonlogger import jsonlogger

    _JSON_LOGGING_AVAILABLE = True
except ImportError:
    _JSON_LOGGING_AVAILABLE = False


# ===========================================================================
# STRUCTURED JSON LOGGING
# Log aggregators (Datadog, Loki) parse JSON fields natively.
# Structured logs let you filter by log_level, request_id, user_id
# without writing fragile regex parsers.
# ===========================================================================
def configure_logging() -> None:
    """Set up JSON logging. Call once at process start."""
    handler = logging.StreamHandler()
    if _JSON_LOGGING_AVAILABLE:
        # Fields: timestamp, level, logger name, message, plus any extra
        formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
        handler.setFormatter(formatter)
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        handlers=[handler],
    )


configure_logging()
logger = logging.getLogger(__name__)


# ===========================================================================
# PYDANTIC-SETTINGS — type-validated configuration from env vars
#
# pydantic-settings reads from:
#   1. Environment variables (highest priority)
#   2. .env file (if present, for local dev only — never commit)
#   3. Field defaults
#
# Type validation catches "DATABASE_URL=postgrs://..." (typo) at startup,
# not at the first DB query 2 hours into production.
# ===========================================================================
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",           # read from .env if it exists (dev only)
        env_file_encoding="utf-8",
        case_sensitive=False,      # DATABASE_URL == database_url
    )

    # Application
    app_name: str = "my-api"
    environment: str = Field(default="production", pattern="^(dev|staging|production)$")
    debug: bool = False

    # Database — pydantic validates the URL scheme (postgresql+asyncpg://)
    database_url: PostgresDsn

    # Redis
    redis_url: RedisDsn = "redis://localhost:6379"  # type: ignore[assignment]

    # Secret key for JWT signing — must come from env / secrets manager
    secret_key: str = Field(min_length=32)

    # Observability
    sentry_dsn: Optional[str] = None
    otel_endpoint: Optional[str] = None  # OpenTelemetry collector URL

    # Worker tuning
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_pool_overflow: int = 5


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Singleton settings object. @lru_cache means env vars are read
    ONCE per process, not on every request. Call get_settings()
    everywhere — do not instantiate Settings() directly.
    """
    return Settings()  # type: ignore[call-arg]


# ===========================================================================
# APPLICATION FACTORY + LIFESPAN
# ===========================================================================
_db_pool = None       # asyncpg / SQLAlchemy pool
_redis_client = None  # redis.asyncio client
_ready = False        # flipped to True once all connections are live


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        # Disable docs in production — no need to expose the schema publicly
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None if settings.environment == "production" else "/redoc",
    )

    # -----------------------------------------------------------------------
    # Prometheus metrics — auto-instruments every route with request_count
    # and request_latency histograms. Exposes /metrics for Prometheus scrape.
    # -----------------------------------------------------------------------
    if _PROMETHEUS_AVAILABLE:
        Instrumentator().instrument(app).expose(app, endpoint="/metrics")

    _register_startup_shutdown(app)
    _register_health_endpoints(app)
    _register_graceful_shutdown()
    return app


def _register_startup_shutdown(app: FastAPI) -> None:
    global _db_pool, _redis_client, _ready

    @app.on_event("startup")
    async def startup() -> None:
        global _db_pool, _redis_client, _ready
        settings = get_settings()
        logger.info("Starting up", extra={"environment": settings.environment})

        # Import here so tests can mock before app creation
        import redis.asyncio as aioredis

        # Connect to Redis — raises immediately if unreachable
        _redis_client = aioredis.from_url(str(settings.redis_url))
        await _redis_client.ping()  # verify connection before accepting traffic

        # Connect to DB (asyncpg / SQLAlchemy async engine)
        # _db_pool = await asyncpg.create_pool(str(settings.database_url), ...)
        # await _db_pool.fetchval("SELECT 1")

        _ready = True  # /ready will now return 200
        logger.info("Startup complete — accepting traffic")

    @app.on_event("shutdown")
    async def shutdown() -> None:
        global _ready
        _ready = False  # stop readiness immediately
        logger.info("Shutdown initiated")
        if _redis_client:
            await _redis_client.aclose()
        if _db_pool:
            await _db_pool.close()
        logger.info("Connections closed cleanly")


# ===========================================================================
# HEALTH ENDPOINTS
#
# /health  (liveness):  "Is the process alive?"
#           Kubernetes restarts the pod if this returns non-2xx.
#           Keep it CHEAP — no DB calls. Just return 200 if the
#           event loop is running.
#
# /ready   (readiness): "Is the pod ready to serve traffic?"
#           Kubernetes removes the pod from the Service endpoints
#           if this returns non-2xx. DB must be connected.
#           Use this to hold traffic off during startup.
#
# /startup (startup probe): replaces readiness during initial
#           boot — allows longer timeout without triggering
#           unnecessary restarts on slow first-startup.
# ===========================================================================
def _register_health_endpoints(app: FastAPI) -> None:
    @app.get("/health", tags=["ops"])
    async def liveness():
        """
        Liveness probe. Returns 200 as long as the process is alive.
        If this is broken, the process is stuck — K8s should restart it.
        """
        return {"status": "alive"}

    @app.get("/ready", tags=["ops"])
    async def readiness():
        """
        Readiness probe. Returns 200 only when all dependencies are up.
        K8s will not send traffic until this returns 200.
        Blocks during startup migrations and initial connection setup.
        """
        if not _ready:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Not ready — dependencies still initialising",
            )
        # Optionally do a lightweight DB ping to confirm the pool is alive
        # try:
        #     await _db_pool.fetchval("SELECT 1")
        # except Exception:
        #     raise HTTPException(503, detail="DB unreachable")
        return {"status": "ready"}

    @app.get("/info", tags=["ops"])
    async def build_info(settings: Settings = Depends(get_settings)):
        """Returns non-sensitive runtime info. Useful for confirming deploys."""
        return {
            "app": settings.app_name,
            "env": settings.environment,
            # Inject GIT_SHA at build time via Docker ARG → ENV
            "sha": os.getenv("GIT_SHA", "unknown"),
        }


# ===========================================================================
# GRACEFUL SHUTDOWN — SIGTERM HANDLER
#
# Kubernetes sends SIGTERM before killing the pod. Default Python
# behaviour: exit immediately, dropping in-flight requests.
# Correct behaviour: stop accepting, finish current requests, then exit.
# Uvicorn's --graceful-timeout handles this for HTTP; we add cleanup here
# for any additional resources (DB pools, message consumers).
# ===========================================================================
def _register_graceful_shutdown() -> None:
    def _handle_sigterm(signum, frame) -> None:
        """
        SIGTERM received from Kubernetes (pod termination).
        Log it; Uvicorn handles draining HTTP — we just need to
        ensure our background tasks and DB pools close cleanly.
        The shutdown event handler (above) does the actual cleanup.
        """
        logger.info("SIGTERM received — initiating graceful shutdown")
        # Do NOT call sys.exit() here — let Uvicorn's graceful-timeout
        # drain in-flight requests first (configured with --graceful-timeout 30)

    signal.signal(signal.SIGTERM, _handle_sigterm)


app = create_app()


# ===========================================================================
# REQUEST ID MIDDLEWARE
# Attach a unique ID to every request for distributed tracing correlation.
# Log the ID on every log line in the request scope.
# ===========================================================================
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    import uuid

    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    # Attach to request state so any handler can read it
    request.state.request_id = request_id
    response = await call_next(request)
    # Echo back so the client can correlate their request with server logs
    response.headers["X-Request-ID"] = request_id
    return response


# ===========================================================================
# KUBERNETES MANIFEST REFERENCE (embedded as comments)
# These are the key K8s objects for a production FastAPI deployment.
# In a real repo these live in k8s/ directory as YAML files.
# ===========================================================================

# --- Deployment (k8s/deployment.yaml) ---
# apiVersion: apps/v1
# kind: Deployment
# spec:
#   replicas: 3
#   strategy:
#     type: RollingUpdate
#     rollingUpdate:
#       maxUnavailable: 0     # never reduce capacity during deploy
#       maxSurge: 1           # add 1 extra pod, wait for ready, then remove old
#   template:
#     spec:
#       terminationGracePeriodSeconds: 60   # must be > --graceful-timeout
#       initContainers:
#         - name: migrations
#           image: my-api:latest
#           command: ["alembic", "upgrade", "head"]
#           # Runs once before app containers start. Prevents migration race.
#       containers:
#         - name: api
#           image: my-api:latest
#           command:
#             - gunicorn
#             - -w 4                           # 4 uvicorn workers (2*CPU+1)
#             - -k uvicorn.workers.UvicornWorker
#             - --graceful-timeout 30          # drain in-flight for 30 s
#             - --bind 0.0.0.0:8000
#             - app.main:app
#           resources:
#             requests: {cpu: "250m", memory: "256Mi"}
#             limits:   {cpu: "1000m", memory: "512Mi"}
#           livenessProbe:
#             httpGet: {path: /health, port: 8000}
#             initialDelaySeconds: 5
#             periodSeconds: 10
#           readinessProbe:
#             httpGet: {path: /ready, port: 8000}
#             initialDelaySeconds: 5
#             periodSeconds: 5
#           startupProbe:
#             httpGet: {path: /ready, port: 8000}
#             failureThreshold: 30   # 30 * 10 s = 5 min for slow first start
#             periodSeconds: 10

# --- PodDisruptionBudget (k8s/pdb.yaml) ---
# apiVersion: policy/v1
# kind: PodDisruptionBudget
# spec:
#   minAvailable: 2    # at least 2 pods must be up during voluntary disruptions
#   selector:
#     matchLabels:
#       app: my-api

# --- HorizontalPodAutoscaler (k8s/hpa.yaml) ---
# apiVersion: autoscaling/v2
# kind: HorizontalPodAutoscaler
# spec:
#   minReplicas: 3
#   maxReplicas: 10
#   metrics:
#     - type: Resource
#       resource:
#         name: cpu
#         target: {type: Utilization, averageUtilization: 70}


# ===========================================================================
# DOCKERFILE REFERENCE (embedded as comments)
# Multi-stage build: builder installs deps; final image is minimal.
# ===========================================================================

# FROM python:3.12-slim AS builder
# WORKDIR /build
# # --- Copy dependency files FIRST for layer caching ---
# # Docker re-uses this layer if pyproject.toml is unchanged,
# # even if source code changed. Saves 30-60 s per build.
# COPY pyproject.toml poetry.lock ./
# RUN pip install poetry && poetry export -f requirements.txt -o requirements.txt
# RUN pip install --prefix=/install -r requirements.txt
#
# FROM python:3.12-slim AS final
# WORKDIR /app
# # --- Non-root user: security best practice ---
# RUN groupadd -r appgroup && useradd -r -g appgroup appuser
# COPY --from=builder /install /usr/local
# COPY src/ ./src/
# USER appuser   # switch before CMD so the process never runs as root
# HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
#     CMD curl -f http://localhost:8000/health || exit 1
# CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker",
#      "--graceful-timeout", "30", "--bind", "0.0.0.0:8000", "src.main:app"]


# ===========================================================================
# SECRETS MANAGEMENT PATTERNS (never in git)
#
# Option A — Kubernetes External Secrets (AWS Secrets Manager / GCP SM):
#   ExternalSecret syncs secrets from the cloud provider into K8s secrets.
#   Pod mounts the K8s secret as env vars. Rotations trigger a sync.
#
# Option B — Vault Agent Injector:
#   Vault Agent sidecar injects secrets as env vars or files at pod start.
#   Supports dynamic secrets (short-lived DB credentials that auto-rotate).
#
# Both options mean zero secrets in .env files, Helm values, or Docker images.
# ===========================================================================

# Quick demo: reading a required secret from env at startup
def _get_required_secret(name: str) -> str:
    """
    Read a secret from an environment variable.
    Raise at startup if missing — fail fast rather than serving
    requests with a broken auth key.
    """
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Required secret '{name}' not found in environment. "
            "Ensure the secret is mounted by Vault Agent or K8s External Secrets."
        )
    return val
