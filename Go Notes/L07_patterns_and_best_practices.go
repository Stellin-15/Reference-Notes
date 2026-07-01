// ============================================================
// L07: Patterns & Best Practices in Production Go
// ============================================================
// WHAT: Functional options for flexible constructors, error wrapping with
//       %w, sentinel errors, custom error types, the repository/service/
//       handler layered architecture, context propagation rules, and
//       graceful shutdown wired to SIGTERM.
// WHY:  Go does not enforce architecture. Without deliberate patterns,
//       services grow into untestable monoliths where HTTP handlers touch
//       the database directly. These patterns — used at Uber, Stripe, and
//       Cloudflare — keep code testable, extensible, and correctly shutdown
//       when Kubernetes sends SIGTERM during a rolling deployment.
// LEVEL: Advanced
// ============================================================
/* CONCEPT OVERVIEW:
   Functional options (type Option func(*T)) let a constructor accept zero
   or many optional settings without adding overloaded signatures. Error
   wrapping with fmt.Errorf("ctx: %w", err) preserves the original error
   so callers can use errors.Is (sentinel check) and errors.As (type check)
   without parsing strings. The repository pattern hides persistence behind
   an interface; the service layer never imports database/sql, so tests swap
   in an InMemoryRepository without touching real storage. Context carries
   cancellation and deadlines into every I/O call; context.Value holds only
   request-scoped data (trace IDs, auth user) — never config or DI.

   PRODUCTION USE CASE:
   A B2B SaaS API uses three distinct layers: handler (HTTP parsing only),
   service (business rules only), repository (SQL only). Functional options
   configure TLS, timeout, and rate-limiter at startup from env vars without
   changing the constructor's signature across releases. Graceful shutdown
   drains in-flight requests within 30 seconds then closes the DB pool,
   preventing transaction rollback storms during rolling deployments.

   COMMON MISTAKES:
   1. Business logic in HTTP handlers — untestable without a running server,
      impossible to reuse in background workers or gRPC handlers.
   2. Returning concrete structs instead of interfaces from constructors —
      locks callers to one implementation, prevents test fakes.
   3. Storing config/logger/DB pool in context.Value — values are untyped,
      invisible to static analysis, and lost after a context cancel.
   4. Not propagating ctx into every DB/HTTP/gRPC call — one slow query
      blocks all goroutines if cancellation never fires through.
   5. Calling os.Exit directly inside handlers — skips deferred cleanup
      and the graceful shutdown sequence entirely.
*/

//go:build ignore

package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"
)

// ===========================================================================
// SECTION 1 — Functional Options Pattern
// ===========================================================================

// ServerConfig holds all tuneable server parameters. Fields are unexported
// so callers are forced to use the options API — no ad hoc struct literals.
type ServerConfig struct {
	host            string
	port            int
	readTimeout     time.Duration
	writeTimeout    time.Duration
	shutdownTimeout time.Duration
	logger          *slog.Logger
}

// Option is a function that mutates a *ServerConfig.
// Named type — readable in godoc and IDE auto-complete.
type Option func(*ServerConfig)

// WithPort overrides the default listen port (8080).
func WithPort(port int) Option {
	return func(c *ServerConfig) { c.port = port }
}

// WithTimeouts sets read and write deadlines on the http.Server.
func WithTimeouts(read, write time.Duration) Option {
	return func(c *ServerConfig) {
		c.readTimeout = read
		c.writeTimeout = write
	}
}

// WithShutdownTimeout controls the graceful drain window.
func WithShutdownTimeout(d time.Duration) Option {
	return func(c *ServerConfig) { c.shutdownTimeout = d }
}

// WithLogger injects a structured logger. Default: slog.Default().
func WithLogger(l *slog.Logger) Option {
	return func(c *ServerConfig) { c.logger = l }
}

// AppServer is constructed via NewAppServer. Adding a new option later
// never changes the function signature — all existing callers keep compiling.
type AppServer struct {
	cfg     ServerConfig
	handler http.Handler
	httpSrv *http.Server
	health  *HealthChecker
}

// NewAppServer applies defaults, then each caller option in order.
// Example: NewAppServer(h, WithPort(9090), WithShutdownTimeout(10*time.Second))
func NewAppServer(handler http.Handler, opts ...Option) *AppServer {
	cfg := ServerConfig{ // sane defaults — service works out of the box
		host:            "0.0.0.0",
		port:            8080,
		readTimeout:     15 * time.Second,
		writeTimeout:    15 * time.Second,
		shutdownTimeout: 30 * time.Second,
		logger:          slog.Default(),
	}
	for _, opt := range opts { // later options override earlier ones
		opt(&cfg)
	}
	return &AppServer{cfg: cfg, handler: handler, health: &HealthChecker{ready: true}}
}

// ===========================================================================
// SECTION 2 — Error Wrapping, Sentinels, and Custom Error Types
// ===========================================================================

// Sentinel errors — package-level variables checked via errors.Is.
// %w wrapping preserves them through multiple wrapping layers.
var (
	ErrNotFound  = errors.New("not found")
	ErrForbidden = errors.New("forbidden")
	ErrConflict  = errors.New("conflict")
)

// AppError carries an HTTP status code alongside the message.
// Callers use errors.As to extract it and write the HTTP response.
type AppError struct {
	Code    int    // HTTP status code
	Message string // safe to return to clients
	Err     error  // wrapped underlying error
}

func (e *AppError) Error() string {
	if e.Err != nil {
		return fmt.Sprintf("%s: %v", e.Message, e.Err)
	}
	return e.Message
}

// Unwrap lets errors.Is and errors.As traverse through AppError.
func (e *AppError) Unwrap() error { return e.Err }

// respondError maps any error to an HTTP response.
// errors.As checks the full chain — works even when AppError is deeply wrapped.
func respondError(w http.ResponseWriter, err error) {
	var appErr *AppError
	if errors.As(err, &appErr) {
		http.Error(w, appErr.Message, appErr.Code)
		return
	}
	// Unknown errors: log the real message, return a generic 500.
	// Never leak stack traces or DB errors to clients.
	slog.Error("unhandled error", "error", err)
	http.Error(w, "internal server error", http.StatusInternalServerError)
}

// ===========================================================================
// SECTION 3 — Repository Pattern (interface + implementations)
// ===========================================================================

// User is the domain entity. Separate from any DB-row or JSON struct
// so persistence and transport concerns don't mix.
type User struct {
	ID        int64
	Name      string
	Email     string
	CreatedAt time.Time
}

// UserRepository defines persistence. The service layer imports this interface,
// never *sql.DB. This makes it trivial to:
//   - Unit test the service with InMemoryUserRepository
//   - Swap Postgres for MySQL without changing the service
//   - Add caching by wrapping the real repo (decorator pattern)
type UserRepository interface {
	GetByID(ctx context.Context, id int64) (*User, error)
	Create(ctx context.Context, u *User) error
	Update(ctx context.Context, u *User) error
	Delete(ctx context.Context, id int64) error
}

// InMemoryUserRepository — used in tests; satisfies UserRepository.
// No external dependencies, deterministic, fast.
type InMemoryUserRepository struct {
	mu     sync.RWMutex
	users  map[int64]*User
	nextID int64
}

func NewInMemoryRepo() *InMemoryUserRepository {
	return &InMemoryUserRepository{users: make(map[int64]*User), nextID: 1}
}

func (r *InMemoryUserRepository) GetByID(_ context.Context, id int64) (*User, error) {
	r.mu.RLock(); defer r.mu.RUnlock()
	u, ok := r.users[id]
	if !ok {
		return nil, fmt.Errorf("GetByID %d: %w", id, ErrNotFound)
	}
	clone := *u; return &clone, nil // return copy — prevent mutation of stored pointer
}

func (r *InMemoryUserRepository) Create(_ context.Context, u *User) error {
	r.mu.Lock(); defer r.mu.Unlock()
	u.ID = r.nextID; r.nextID++
	u.CreatedAt = time.Now()
	r.users[u.ID] = u; return nil
}

func (r *InMemoryUserRepository) Update(_ context.Context, u *User) error {
	r.mu.Lock(); defer r.mu.Unlock()
	if _, ok := r.users[u.ID]; !ok {
		return fmt.Errorf("Update %d: %w", u.ID, ErrNotFound)
	}
	r.users[u.ID] = u; return nil
}

func (r *InMemoryUserRepository) Delete(_ context.Context, id int64) error {
	r.mu.Lock(); defer r.mu.Unlock()
	delete(r.users, id); return nil
}

// ===========================================================================
// SECTION 4 — Service Layer (business logic only, no HTTP/SQL)
// ===========================================================================

// UserService holds business rules. Depends on the interface, not a concrete
// DB type. Never imports net/http or database/sql.
type UserService struct {
	repo   UserRepository
	logger *slog.Logger
}

func NewUserService(repo UserRepository, logger *slog.Logger) *UserService {
	return &UserService{repo: repo, logger: logger}
}

// CreateUser validates then delegates to the repository.
// Business rules live here, not in the handler and not in the repository.
func (s *UserService) CreateUser(ctx context.Context, name, email string) (*User, error) {
	if name == "" {
		return nil, &AppError{Code: http.StatusBadRequest, Message: "name is required"}
	}
	if email == "" {
		return nil, &AppError{Code: http.StatusBadRequest, Message: "email is required"}
	}
	u := &User{Name: name, Email: email}
	if err := s.repo.Create(ctx, u); err != nil {
		return nil, fmt.Errorf("UserService.CreateUser: %w", err) // %w preserves chain
	}
	s.logger.Info("user created", "id", u.ID)
	return u, nil
}

func (s *UserService) GetUser(ctx context.Context, id int64) (*User, error) {
	u, err := s.repo.GetByID(ctx, id)
	if err != nil {
		if errors.Is(err, ErrNotFound) { // works even through fmt.Errorf %w wrapping
			return nil, &AppError{Code: http.StatusNotFound,
				Message: fmt.Sprintf("user %d not found", id), Err: ErrNotFound}
		}
		return nil, fmt.Errorf("UserService.GetUser: %w", err)
	}
	return u, nil
}

// ===========================================================================
// SECTION 5 — HTTP Handler Layer (HTTP parsing only, calls service)
// ===========================================================================

// UserHandler translates HTTP ↔ service calls. Zero business logic here.
// If a rule moves to the handler it becomes untestable without a real server.
type UserHandler struct {
	svc *UserService
}

func NewUserHandler(svc *UserService) *UserHandler { return &UserHandler{svc: svc} }

func (h *UserHandler) Register(mux *http.ServeMux) {
	mux.HandleFunc("GET /users/{id}", h.getUser)
}

func (h *UserHandler) getUser(w http.ResponseWriter, r *http.Request) {
	var id int64
	fmt.Sscan(r.PathValue("id"), &id) // Go 1.22+ ServeMux path values
	u, err := h.svc.GetUser(r.Context(), id) // always pass request context
	if err != nil {
		respondError(w, err); return
	}
	w.Header().Set("Content-Type", "application/json")
	fmt.Fprintf(w, `{"id":%d,"name":%q}`, u.ID, u.Name)
}

// ===========================================================================
// SECTION 6 — Context Propagation
// ===========================================================================

// ctxKey is an unexported named type — prevents key collisions with
// other packages that also store values in context.
type ctxKey string

const (
	ctxKeyRequestID ctxKey = "request_id" // injected by middleware from X-Request-ID
	ctxKeyUserID    ctxKey = "user_id"    // injected by auth middleware from JWT
)

func RequestIDFromCtx(ctx context.Context) string {
	v, _ := ctx.Value(ctxKeyRequestID).(string); return v
}

// requestIDMiddleware shows the only valid use of context.Value:
// request-scoped data (trace ID, auth user) injected by middleware.
// config/logger/DB must be injected via struct fields — never via context.
func requestIDMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.Header.Get("X-Request-ID")
		if id == "" {
			id = fmt.Sprintf("req-%d", time.Now().UnixNano())
		}
		ctx := context.WithValue(r.Context(), ctxKeyRequestID, id)
		w.Header().Set("X-Request-ID", id)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// ===========================================================================
// SECTION 7 — Health Checker and Graceful Shutdown
// ===========================================================================

// HealthChecker controls readiness. Call SetReady(false) as the first step
// in shutdown so Kubernetes stops sending traffic before we begin draining.
type HealthChecker struct {
	mu    sync.RWMutex
	ready bool
}

func (h *HealthChecker) SetReady(v bool) { h.mu.Lock(); defer h.mu.Unlock(); h.ready = v }

func (h *HealthChecker) LiveHandler(w http.ResponseWriter, _ *http.Request) {
	w.WriteHeader(http.StatusOK) // simple: is the process alive?
}

func (h *HealthChecker) ReadyHandler(w http.ResponseWriter, _ *http.Request) {
	h.mu.RLock(); ready := h.ready; h.mu.RUnlock()
	if !ready {
		http.Error(w, "not ready", http.StatusServiceUnavailable); return
	}
	w.WriteHeader(http.StatusOK)
}

// Run starts the server and blocks until SIGTERM/SIGINT, then drains cleanly.
// Shutdown sequence:
//   1. SetReady(false)               — Kubernetes stops routing
//   2. server.Shutdown(drainCtx)     — waits for active handlers
//   3. wg.Wait()                     — waits for background goroutines
//   4. return nil                    — main() exits 0
func (s *AppServer) Run(ctx context.Context) error {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", s.health.LiveHandler)
	mux.HandleFunc("GET /ready",  s.health.ReadyHandler)
	mux.Handle("/", requestIDMiddleware(s.handler))

	s.httpSrv = &http.Server{
		Addr:         fmt.Sprintf("%s:%d", s.cfg.host, s.cfg.port),
		Handler:      mux,
		ReadTimeout:  s.cfg.readTimeout,
		WriteTimeout: s.cfg.writeTimeout,
	}

	sigCtx, stop := signal.NotifyContext(ctx, syscall.SIGTERM, os.Interrupt)
	defer stop()

	serverErr := make(chan error, 1)
	go func() {
		s.cfg.logger.Info("listening", "addr", s.httpSrv.Addr)
		if err := s.httpSrv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			serverErr <- err
		}
	}()

	select {
	case err := <-serverErr:
		return fmt.Errorf("server: %w", err)
	case <-sigCtx.Done():
		s.cfg.logger.Info("shutdown signal received")
	}

	s.health.SetReady(false) // step 1: stop receiving traffic
	s.cfg.logger.Info("draining requests")

	drainCtx, cancel := context.WithTimeout(context.Background(), s.cfg.shutdownTimeout)
	defer cancel()
	if err := s.httpSrv.Shutdown(drainCtx); err != nil {
		return fmt.Errorf("shutdown: %w", err)
	}
	s.cfg.logger.Info("server stopped cleanly")
	return nil
}

// ===========================================================================
// SECTION 8 — Wire everything in main (explicit, no magic DI framework)
// ===========================================================================

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil)).
		With("service", "user-api", "version", "1.0.0")

	repo := NewInMemoryRepo()              // swap for PostgresRepo in production
	svc := NewUserService(repo, logger)
	handler := NewUserHandler(svc)

	mux := http.NewServeMux()
	handler.Register(mux)

	srv := NewAppServer(mux,
		WithPort(8080),
		WithTimeouts(15*time.Second, 15*time.Second),
		WithShutdownTimeout(30*time.Second),
		WithLogger(logger),
	)

	if err := srv.Run(context.Background()); err != nil {
		logger.Error("fatal", "error", err)
		os.Exit(1) // only valid os.Exit call — outermost layer, after all cleanup
	}
}
