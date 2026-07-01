// ============================================================
// L08: Production Deployment — Build, Docker, Logging, Metrics, Shutdown
// ============================================================
// WHAT: Single-binary Go builds, multi-stage distroless Docker images,
//       environment-driven config with fail-fast validation, structured
//       slog logging, Prometheus metrics, /health + /ready endpoints,
//       graceful shutdown on SIGTERM, and a CI Makefile.
// WHY:  A service that works on localhost but OOMs in Kubernetes, loses
//       in-flight requests during deploys, or produces unqueryable logs
//       is not production-ready. These patterns are the baseline every Go
//       service must hit before its first deployment.
// LEVEL: Advanced
// ============================================================
/* CONCEPT OVERVIEW:
   `go build` produces a single self-contained binary. CGO_ENABLED=0 makes
   it purely static (no libc). -ldflags="-s -w" strips symbol/DWARF, cutting
   binary size ~30%. Multi-stage Docker builds compile in a full Go image and
   copy only the binary into gcr.io/distroless/static — no shell, no package
   manager, minimal attack surface. log/slog (Go 1.21+) is the standard
   structured logger: JSON output, level filtering, per-request field
   injection with zero third-party dependencies. Prometheus histograms
   instrument request duration; /metrics is scraped by Prometheus, graphed
   in Grafana. Health and readiness probes let Kubernetes distinguish
   "alive" from "ready for traffic". Graceful shutdown marks readiness false,
   waits for the load balancer to drain, then calls server.Shutdown().

   PRODUCTION USE CASE:
   A Kubernetes API receives 50k req/s. Every request records a
   request_duration_seconds histogram (P50/P95/P99 in Grafana dashboards).
   On rolling deploy, Kubernetes sends SIGTERM; the handler immediately
   fails /ready, a 5-second pause lets the LB drain, then Shutdown() waits
   for active handlers, closes the DB pool, and exits 0 — zero errors during
   deployment. The distroless image means CVE scanners find no OS-level
   vulnerabilities (no bash, no openssl, no apt).

   COMMON MISTAKES:
   1. Using log.Println — unstructured text cannot be queried in Loki or
      CloudWatch; parsing it at scale costs 10× more than indexed JSON.
   2. Not setting GOMEMLIMIT — the process OOMs with no heap dump to analyse.
      Always set to ~80% of the container memory limit.
   3. Missing a separate /ready endpoint — if /health handles both, a slow
      DB reconnect during startup causes live traffic to hit an unready pod.
   4. Registering Prometheus metrics inside a handler — each request
      re-registers the same metric and panics with "duplicate metric".
      Always declare metrics at package level with var declarations.
   5. Exposing /debug/pprof on the public port — pprof reveals heap contents
      including secrets. Always bind the debug mux to localhost only.
*/

//go:build ignore

package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"runtime"
	"strconv"
	"sync"
	"syscall"
	"time"
)

// ===========================================================================
// SECTION 1 — Build flags reference (comment block)
// ===========================================================================
// Single-binary build:
//   CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
//   go build \
//     -ldflags="-s -w -X main.version=${GIT_SHA} -X main.buildTime=$(date -u +%FT%TZ)" \
//     -o bin/server \
//     ./cmd/server
//
//   -s  strips the symbol table  (removes symbol names)
//   -w  strips DWARF debug info   (no debugger attachment)
//   Together: ~30% smaller binary, identical runtime behaviour.
//   CGO_ENABLED=0: pure static binary — no libc, runs in distroless/scratch.
//
// Version variables injected at link time so the running binary can report
// exactly which commit it was built from:

var (
	version   = "dev"             // overwritten by -X main.version=${GIT_SHA}
	buildTime = "unknown"         // overwritten by -X main.buildTime=...
)

func goVersion() string { return runtime.Version() }

// ===========================================================================
// SECTION 2 — Environment-driven configuration with fail-fast validation
// ===========================================================================

// Config holds all runtime parameters. Optional fields have defaults;
// required fields cause an immediate panic if absent — fail fast, never
// start in a broken state. The panic appears in pod logs before any traffic.
type Config struct {
	HTTPPort        int           // PORT (default 8080)
	MetricsPort     int           // METRICS_PORT (default 9090)
	DatabaseURL     string        // DATABASE_URL — REQUIRED
	ReadTimeout     time.Duration // READ_TIMEOUT_SEC (default 15)
	WriteTimeout    time.Duration // WRITE_TIMEOUT_SEC (default 15)
	ShutdownTimeout time.Duration // SHUTDOWN_TIMEOUT_SEC (default 30)
	LogLevel        slog.Level    // LOG_LEVEL: debug|info|warn|error (default info)
	Environment     string        // ENVIRONMENT: production|staging|development
	ServiceName     string        // SERVICE_NAME (default "api")
}

func LoadConfig() Config {
	return Config{
		HTTPPort:        envInt("PORT", 8080),
		MetricsPort:     envInt("METRICS_PORT", 9090),
		DatabaseURL:     envRequired("DATABASE_URL"), // panics with clear message if unset
		ReadTimeout:     envSeconds("READ_TIMEOUT_SEC", 15),
		WriteTimeout:    envSeconds("WRITE_TIMEOUT_SEC", 15),
		ShutdownTimeout: envSeconds("SHUTDOWN_TIMEOUT_SEC", 30),
		LogLevel:        envLogLevel("LOG_LEVEL", slog.LevelInfo),
		Environment:     envStr("ENVIRONMENT", "development"),
		ServiceName:     envStr("SERVICE_NAME", "api"),
	}
}

func envRequired(key string) string {
	v := os.Getenv(key)
	if v == "" {
		panic(fmt.Sprintf("required env var %q is not set — cannot start", key))
	}
	return v
}
func envStr(key, def string) string {
	if v := os.Getenv(key); v != "" { return v }; return def
}
func envInt(key string, def int) int {
	s := os.Getenv(key); if s == "" { return def }
	n, err := strconv.Atoi(s)
	if err != nil { panic(fmt.Sprintf("env %s=%q: not an integer", key, s)) }
	return n
}
func envSeconds(key string, def int) time.Duration {
	return time.Duration(envInt(key, def)) * time.Second
}
func envLogLevel(key string, def slog.Level) slog.Level {
	s := os.Getenv(key); if s == "" { return def }
	var l slog.Level
	if err := l.UnmarshalText([]byte(s)); err != nil {
		panic(fmt.Sprintf("env %s=%q: not a valid log level", key, s))
	}
	return l
}

// ===========================================================================
// SECTION 3 — Structured logging with log/slog (Go 1.21+)
// ===========================================================================

// buildLogger creates the application logger. JSON in production (queryable
// in Loki, CloudWatch, Datadog). Text in development (human-readable).
func buildLogger(cfg Config) *slog.Logger {
	opts := &slog.HandlerOptions{
		Level:     cfg.LogLevel,
		AddSource: cfg.Environment == "development", // file:line in dev only
	}
	var h slog.Handler
	if cfg.Environment == "development" {
		h = slog.NewTextHandler(os.Stdout, opts)
	} else {
		h = slog.NewJSONHandler(os.Stdout, opts) // index-able structured JSON
	}
	// With() adds fields to every log line — service name, version, env.
	// These fields appear in every Loki stream selector and CloudWatch filter.
	logger := slog.New(h).With(
		"service", cfg.ServiceName,
		"version", version,
		"env",     cfg.Environment,
	)
	slog.SetDefault(logger) // packages that call slog.Info() use our handler
	return logger
}

// responseWriter captures the status code written by handlers for logging.
type responseWriter struct {
	http.ResponseWriter
	status int
	size   int
}

func (rw *responseWriter) WriteHeader(s int) { rw.status = s; rw.ResponseWriter.WriteHeader(s) }
func (rw *responseWriter) Write(b []byte) (int, error) {
	n, err := rw.ResponseWriter.Write(b); rw.size += n; return n, err
}

// accessLogMiddleware logs every request with method, path, status, duration.
func accessLogMiddleware(logger *slog.Logger, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rw := &responseWriter{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rw, r)
		logger.Info("request",
			"method", r.Method, "path", r.URL.Path,
			"status", rw.status, "bytes", rw.size,
			"duration_ms", time.Since(start).Milliseconds(),
		)
	})
}

// ===========================================================================
// SECTION 4 — Prometheus Metrics (pattern without import)
// ===========================================================================
// In production, replace stub types with:
//   import "github.com/prometheus/client_golang/prometheus"
//   import "github.com/prometheus/client_golang/prometheus/promauto"
//   import "github.com/prometheus/client_golang/prometheus/promhttp"
//
// Always declare metrics at package level — handler-level registration panics.
//
// Example (real code):
//   var requestDuration = promauto.NewHistogramVec(prometheus.HistogramOpts{
//       Namespace: "api",
//       Subsystem: "http",
//       Name:      "request_duration_seconds",
//       Help:      "HTTP request latency distribution.",
//       Buckets:   prometheus.DefBuckets, // .005 .01 .025 .05 .1 .25 .5 1 2.5 5 10
//   }, []string{"method", "status", "path"})
//
//   // In metrics middleware:
//   requestDuration.WithLabelValues(method, status, path).Observe(duration)
//
//   // Expose on the internal metrics port:
//   metricsMux.Handle("/metrics", promhttp.Handler())

// Stub types so this file compiles without the prometheus import.
type histogram struct{}
type counter struct{}
type gauge struct{}

func (h *histogram) Observe(_ float64)              {}
func (h *histogram) WithLabels(...string) *histogram { return h }
func (c *counter) Inc()                              {}
func (c *counter) WithLabels(...string) *counter     { return c }
func (g *gauge) Inc()                                {}
func (g *gauge) Dec()                                {}

var (
	requestDuration = &histogram{} // api_http_request_duration_seconds{method,status,path}
	requestTotal    = &counter{}   // api_http_requests_total{method,status}
	activeRequests  = &gauge{}     // api_http_requests_in_flight
)

// metricsMiddleware instruments every HTTP request.
func metricsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		activeRequests.Inc()
		defer activeRequests.Dec()
		rw := &responseWriter{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rw, r)
		dur := time.Since(start).Seconds()
		status := strconv.Itoa(rw.status)
		requestDuration.Observe(dur)   // P50/P95/P99 visible in Grafana
		requestTotal.Inc()             // alert on error rate = 5xx / total
		_ = status
	})
}

// ===========================================================================
// SECTION 5 — Health and Readiness Probes
// ===========================================================================

// HealthChecker — SetReady(false) is the first step in the shutdown sequence.
// Kubernetes stops sending traffic once /ready returns non-200.
type HealthChecker struct {
	mu    sync.RWMutex
	ready bool
}

func (h *HealthChecker) SetReady(v bool) { h.mu.Lock(); defer h.mu.Unlock(); h.ready = v }

// LiveHandler: GET /health — is the process alive?
// Kubernetes restarts the pod if this returns non-200.
// NEVER check external dependencies here — keep it O(1) and infallible.
func (h *HealthChecker) LiveHandler(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "version": version})
}

// ReadyHandler: GET /ready — is the pod ready to serve traffic?
// Return 503 during startup (migrations), during shutdown (draining),
// or when a required dependency is unhealthy (DB unreachable).
func (h *HealthChecker) ReadyHandler(w http.ResponseWriter, r *http.Request) {
	h.mu.RLock(); ready := h.ready; h.mu.RUnlock()
	if !ready {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"status": "not ready"})
		return
	}
	// Probe the DB with a short deadline — never block a Kubernetes probe > 2s.
	// ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	// defer cancel()
	// if err := db.PingContext(ctx); err != nil { ... 503 ... }
	_ = r
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "db": "ok"})
}

func writeJSON(w http.ResponseWriter, status int, body interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(body) //nolint:errcheck
}

// ===========================================================================
// SECTION 6 — Application wiring and graceful shutdown
// ===========================================================================

type App struct {
	cfg    Config
	logger *slog.Logger
	health *HealthChecker
}

// Run starts the API and metrics servers and blocks until SIGTERM/SIGINT.
// Shutdown sequence:
//   1. health.SetReady(false)            — Kubernetes sees 503 on /ready
//   2. time.Sleep(5s)                    — LB drains connections (k8s propagation delay)
//   3. apiServer.Shutdown(drainCtx)      — waits for active handlers to complete
//   4. metricsServer.Shutdown(drainCtx)  — shuts down metrics endpoint
//   5. db.Close()                        — no new queries after all handlers done
//   6. return nil → main() exits 0       — clean exit, no goroutine leaks
func (a *App) Run(ctx context.Context) error {
	apiMux := http.NewServeMux()
	apiMux.HandleFunc("GET /health", a.health.LiveHandler)
	apiMux.HandleFunc("GET /ready",  a.health.ReadyHandler)
	apiMux.HandleFunc("GET /users",  func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"users": "[]"})
	})
	apiChain := accessLogMiddleware(a.logger, metricsMiddleware(apiMux))

	apiSrv := &http.Server{
		Addr:         fmt.Sprintf(":%d", a.cfg.HTTPPort),
		Handler:      apiChain,
		ReadTimeout:  a.cfg.ReadTimeout,
		WriteTimeout: a.cfg.WriteTimeout,
	}
	// Metrics server on a separate port — never expose to the internet.
	metricsMux := http.NewServeMux()
	metricsMux.HandleFunc("/metrics", func(w http.ResponseWriter, _ *http.Request) {
		fmt.Fprintln(w, "# Prometheus metrics (stub)")
		// In production: promhttp.Handler().ServeHTTP(w, r)
	})
	metricsSrv := &http.Server{Addr: fmt.Sprintf(":%d", a.cfg.MetricsPort), Handler: metricsMux}

	sigCtx, stop := signal.NotifyContext(ctx, syscall.SIGTERM, os.Interrupt)
	defer stop()

	errc := make(chan error, 2)
	go func() {
		a.logger.Info("API listening", "addr", apiSrv.Addr)
		if err := apiSrv.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
			errc <- fmt.Errorf("api: %w", err)
		}
	}()
	go func() {
		a.logger.Info("metrics listening", "addr", metricsSrv.Addr)
		if err := metricsSrv.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
			errc <- fmt.Errorf("metrics: %w", err)
		}
	}()

	select {
	case err := <-errc:
		return err
	case <-sigCtx.Done():
		a.logger.Info("shutdown signal received")
	}

	a.health.SetReady(false) // step 1 — Kubernetes stops sending traffic
	a.logger.Info("readiness probe failing; waiting for LB drain")
	time.Sleep(5 * time.Second) // step 2 — k8s needs ~2–5s to observe the probe change

	drainCtx, cancel := context.WithTimeout(context.Background(), a.cfg.ShutdownTimeout)
	defer cancel()

	var wg sync.WaitGroup
	wg.Add(2)
	go func() { defer wg.Done(); apiSrv.Shutdown(drainCtx) }()     //nolint:errcheck
	go func() { defer wg.Done(); metricsSrv.Shutdown(drainCtx) }() //nolint:errcheck
	wg.Wait()

	a.logger.Info("shutdown complete") // step 6 — caller exits 0
	return nil
}

// ===========================================================================
// SECTION 7 — Dockerfile (multi-stage distroless) — reference comment
// ===========================================================================
/*
# syntax=docker/dockerfile:1

# ---- Stage 1: compile ----
FROM golang:1.22-alpine AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download                    # cache module layer separately
COPY . .
ARG GIT_SHA=dev
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build \
      -ldflags="-s -w -X main.version=${GIT_SHA}" \
      -o /out/server ./cmd/server

# ---- Stage 2: run ----
# distroless/static: CA certs + timezone data only.
# No shell, no package manager — minimal CVE surface.
FROM gcr.io/distroless/static-debian12:nonroot
WORKDIR /app
COPY --from=builder /out/server .
USER nonroot:nonroot              # never run as root
EXPOSE 8080 9090
ENTRYPOINT ["/app/server"]        # exec form: signals go directly to PID 1
*/

// ===========================================================================
// SECTION 8 — Makefile and CI reference (comment block)
// ===========================================================================
/*
GIT_SHA := $(shell git rev-parse --short HEAD)
IMAGE    := myrepo/api:$(GIT_SHA)

.PHONY: build test lint docker-build run

build:
    CGO_ENABLED=0 go build \
        -ldflags="-s -w -X main.version=$(GIT_SHA)" \
        -o bin/server ./cmd/server

test:
    go test -race -cover -coverprofile=coverage.out ./...
    go tool cover -func=coverage.out | tail -1        # print total %

lint:
    go vet ./...
    staticcheck ./...      # honnef.co/go/tools/cmd/staticcheck
    golangci-lint run      # aggregates 50+ linters

docker-build:
    docker build --build-arg GIT_SHA=$(GIT_SHA) -t $(IMAGE) .

run:                       # local dev with all required env vars
    DATABASE_URL=postgres://user:pass@localhost:5432/app \
    PORT=8080 ENVIRONMENT=development LOG_LEVEL=debug \
    go run ./cmd/server

# CI (GitHub Actions excerpt):
#   - run: go test -race -coverprofile=coverage.out ./...
#   - run: go vet ./...
#   - run: staticcheck ./...
#   - run: docker build --build-arg GIT_SHA=${{ github.sha }} -t $IMAGE .
*/

// ===========================================================================
// SECTION 9 — Key environment variables quick-reference
// ===========================================================================
// Variable              Default     Notes
// ─────────────────────────────────────────────────────────────────────
// PORT                  8080        Public API port
// METRICS_PORT          9090        Internal Prometheus scrape port
// DATABASE_URL          (required)  postgres://user:pass@host:5432/db
// LOG_LEVEL             info        debug|info|warn|error
// ENVIRONMENT           development production|staging|development
// SERVICE_NAME          api         Injected on every log line + metric
// READ_TIMEOUT_SEC      15          http.Server.ReadTimeout
// WRITE_TIMEOUT_SEC     15          http.Server.WriteTimeout
// SHUTDOWN_TIMEOUT_SEC  30          Graceful drain window
// GOGC                  100         200 = half GC frequency, 2× memory
// GOMEMLIMIT            (unset)     e.g. 1536MiB — prevents OOM kills
// GOMAXPROCS            NumCPU      Use uber-go/automaxprocs in containers

func main() {
	cfg := LoadConfig() // panics on missing required env vars
	logger := buildLogger(cfg)

	logger.Info("starting",
		"version",    version,
		"build_time", buildTime,
		"go_version", goVersion(),
		"port",       cfg.HTTPPort,
		"metrics",    cfg.MetricsPort,
	)

	app := &App{cfg: cfg, logger: logger, health: &HealthChecker{ready: true}}

	if err := app.Run(context.Background()); err != nil {
		logger.Error("fatal", "error", err)
		os.Exit(1) // only valid os.Exit — outermost caller, after all cleanup
	}
}
