// ============================================================
// L03: Go HTTP Servers
// ============================================================
// WHAT: Building production HTTP servers in Go — standard library
//       net/http, the Chi router, middleware chains, JSON handling,
//       request context, graceful shutdown, timeouts, and structured
//       logging with log/slog.
// WHY:  Go's net/http package is fast enough for most workloads
//       without a framework. The standard library HTTP server is
//       concurrent by default (each request in its own goroutine),
//       handles keep-alive, TLS, and HTTP/2. Chi adds a clean
//       routing DSL and composable middleware with zero magic.
//       Understanding this stack means you can build, debug, and
//       tune HTTP services without framework lock-in.
// LEVEL: Intermediate
// ============================================================
/*
CONCEPT OVERVIEW:
    Go's HTTP model:
      Request → ServeMux (router) → Middleware chain → Handler
      Handler writes to ResponseWriter (streams the response)

    Handler signature: func(w http.ResponseWriter, r *http.Request)
    Everything — middleware, handlers, route groups — is this type.

    Chi router adds:
      - URL parameters: /users/{id}
      - Method-specific routing: r.Get, r.Post, r.Put, r.Delete
      - Middleware via r.Use() (global) or r.With() (per-route)
      - Sub-routers for grouping: r.Route("/api/v1", func(r chi.Router) {...})

    Middleware: wraps a handler. Executes code before/after.
    Runs in order: Logger → Auth → RateLimit → Handler → (reverse)

PRODUCTION USE CASE:
    REST API for user management: CRUD endpoints, request ID middleware,
    structured JSON logging, JWT auth middleware, graceful shutdown on
    SIGTERM. This pattern is used at every Go shop as the starting
    point for microservices.

COMMON MISTAKES:
    1. Writing to ResponseWriter after WriteHeader — headers already sent.
       Always set headers BEFORE calling WriteHeader or Write.
    2. Not reading/closing r.Body — connection stays open (resource leak).
       json.Decoder reads Body; you must still drain+close on error.
    3. Using http.DefaultClient — no timeout. A slow upstream hangs your
       goroutine forever. Always configure Timeout on http.Client.
    4. Calling log.Fatal in a handler — kills the whole process.
       Return an error JSON response instead.
    5. Storing mutable state in package-level vars without synchronization
       — each request runs in its own goroutine. Use a struct with mutex.
    6. Not setting Content-Type before writing — clients may misparse response.
*/

package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"
)

// ============================================================
// SECTION 1: DOMAIN TYPES
// ============================================================

// HTTPUser: the JSON representation of a user in API responses.
// Tags control JSON serialization: field name, omitempty (omit if zero).
type HTTPUser struct {
	ID        int64     `json:"id"`
	Name      string    `json:"name"`
	Email     string    `json:"email"`
	CreatedAt time.Time `json:"created_at"`
}

// CreateUserRequest: payload for POST /users. Validated after decode.
type CreateUserRequest struct {
	Name  string `json:"name"`
	Email string `json:"email"`
}

// Validate: simple field validation. In production use go-playground/validator
// which handles struct tags like validate:"required,email,min=2,max=100".
func (r CreateUserRequest) Validate() error {
	if r.Name == "" {
		return fmt.Errorf("name is required")
	}
	if len(r.Name) > 100 {
		return fmt.Errorf("name must be 100 characters or fewer")
	}
	if r.Email == "" {
		return fmt.Errorf("email is required")
	}
	return nil
}

// UpdateUserRequest: payload for PATCH /users/{id}. All fields optional.
// Using pointers: nil means "not provided", so we don't overwrite with zero.
type UpdateUserRequest struct {
	Name  *string `json:"name,omitempty"`
	Email *string `json:"email,omitempty"`
}

// AppError: structured error type that maps to HTTP responses.
// Carrying the HTTP status code here keeps handler code clean — handlers
// just return an AppError and the error-writing middleware handles status.
type AppError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
	// Err is the underlying cause — not serialized to JSON (no tag).
	Err error `json:"-"`
}

func (e *AppError) Error() string {
	if e.Err != nil {
		return fmt.Sprintf("HTTP %d: %s: %v", e.Code, e.Message, e.Err)
	}
	return fmt.Sprintf("HTTP %d: %s", e.Code, e.Message)
}

// Unwrap: lets errors.Is/As traverse the chain through AppError.
func (e *AppError) Unwrap() error { return e.Err }

// Common error constructors — readable at call sites.
func errNotFound(msg string) *AppError {
	return &AppError{Code: http.StatusNotFound, Message: msg}
}
func errBadRequest(msg string) *AppError {
	return &AppError{Code: http.StatusBadRequest, Message: msg}
}
func errInternal(err error) *AppError {
	return &AppError{Code: http.StatusInternalServerError, Message: "internal server error", Err: err}
}
func errUnauthorized() *AppError {
	return &AppError{Code: http.StatusUnauthorized, Message: "unauthorized"}
}

// ============================================================
// SECTION 2: IN-MEMORY USER STORE (re-using patterns from L01)
// ============================================================

// userStore: thread-safe in-memory store. Each request runs in its own
// goroutine, so all shared state must be protected by a mutex.
type userStore struct {
	mu     sync.RWMutex // protects users map; RWMutex allows parallel reads
	users  map[int64]HTTPUser
	nextID int64
}

// Include sync for the userStore
var (
	_ = sync.RWMutex{} // ensure sync is imported — will be used in userStore
)

// newUserStore: constructor. Seeds with one user for demo purposes.
func newUserStore() *userStore {
	s := &userStore{
		users:  make(map[int64]HTTPUser),
		nextID: 1,
	}
	// Seed data.
	s.users[1] = HTTPUser{ID: 1, Name: "Alice", Email: "alice@example.com", CreatedAt: time.Now()}
	s.nextID = 2
	return s
}

func (s *userStore) GetByID(id int64) (HTTPUser, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	u, ok := s.users[id]
	return u, ok
}

func (s *userStore) Create(req CreateUserRequest) HTTPUser {
	s.mu.Lock()
	defer s.mu.Unlock()
	u := HTTPUser{ID: s.nextID, Name: req.Name, Email: req.Email, CreatedAt: time.Now()}
	s.users[s.nextID] = u
	s.nextID++
	return u
}

func (s *userStore) Update(id int64, req UpdateUserRequest) (HTTPUser, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	u, ok := s.users[id]
	if !ok {
		return HTTPUser{}, false
	}
	if req.Name != nil {
		u.Name = *req.Name
	}
	if req.Email != nil {
		u.Email = *req.Email
	}
	s.users[id] = u
	return u, true
}

func (s *userStore) Delete(id int64) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	_, ok := s.users[id]
	if !ok {
		return false
	}
	delete(s.users, id)
	return true
}

func (s *userStore) List() []HTTPUser {
	s.mu.RLock()
	defer s.mu.RUnlock()
	result := make([]HTTPUser, 0, len(s.users))
	for _, u := range s.users {
		result = append(result, u)
	}
	return result
}

// ============================================================
// SECTION 3: RESPONSE HELPERS
// ============================================================

// writeJSON: marshals v to JSON and writes it to w with given status code.
// Always set Content-Type BEFORE WriteHeader — headers are sent with status.
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status) // sends status line + headers; after this, headers are immutable
	if err := json.NewEncoder(w).Encode(v); err != nil {
		// At this point we can't change the status — it's already sent.
		// Log only.
		slog.Error("writeJSON encode failed", "error", err)
	}
}

// writeError: writes an AppError as a JSON response.
// Extracts the HTTP code from the AppError.
func writeError(w http.ResponseWriter, err error) {
	var appErr *AppError
	if errors.As(err, &appErr) {
		// Log internal errors with full detail; client only sees the message.
		if appErr.Code == http.StatusInternalServerError && appErr.Err != nil {
			slog.Error("internal error", "error", appErr.Err)
		}
		writeJSON(w, appErr.Code, map[string]string{"error": appErr.Message})
		return
	}
	// Fallback for unexpected error types.
	slog.Error("unhandled error type", "error", err)
	writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal server error"})
}

// ============================================================
// SECTION 4: CONTEXT KEYS AND HELPERS
// ============================================================

// Typed context keys: prevents collisions between packages.
// Never use plain strings as context keys — two packages could use "userID".
type contextKey string

const (
	requestIDKey contextKey = "requestID"
	userIDKey    contextKey = "userID" // set by auth middleware
)

// requestIDFromCtx: safely retrieves request ID from context.
func requestIDFromCtx(ctx context.Context) string {
	if id, ok := ctx.Value(requestIDKey).(string); ok {
		return id
	}
	return "unknown"
}

// ============================================================
// SECTION 5: MIDDLEWARE
// ============================================================

// Middleware signature: func(next http.Handler) http.Handler
// This is the standard Go middleware type. Chi, gorilla/mux, net/http all use it.

// RequestIDMiddleware: generates a unique ID for each request.
// Adds it to context (for downstream use) and response header (for clients/logs).
func RequestIDMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Generate a simple request ID. Production: use UUID or ULID.
		reqID := fmt.Sprintf("%d", time.Now().UnixNano())

		// Attach to context so handlers can retrieve it.
		ctx := context.WithValue(r.Context(), requestIDKey, reqID)

		// Add to response header so clients can correlate logs.
		w.Header().Set("X-Request-ID", reqID)

		// Call next handler with updated request (new context attached).
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// responseWriter: wraps http.ResponseWriter to capture the status code.
// net/http doesn't expose the status code after it's written — we must wrap.
type responseWriter struct {
	http.ResponseWriter
	status int
}

func (rw *responseWriter) WriteHeader(status int) {
	rw.status = status                  // capture before forwarding
	rw.ResponseWriter.WriteHeader(status) // forward to underlying writer
}

// LoggingMiddleware: logs method, path, status, and duration for every request.
// Uses log/slog (Go 1.21+) for structured, machine-parseable output.
func LoggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()

		// Wrap ResponseWriter to capture status code.
		wrapped := &responseWriter{ResponseWriter: w, status: http.StatusOK}

		// Call the next handler. After this returns, the response is complete.
		next.ServeHTTP(wrapped, r)

		// Log after handler returns — we now have status and duration.
		slog.Info("request",
			"method", r.Method,
			"path", r.URL.Path,
			"status", wrapped.status,
			"duration_ms", time.Since(start).Milliseconds(),
			"request_id", requestIDFromCtx(r.Context()),
			"remote_addr", r.RemoteAddr,
		)
	})
}

// AuthMiddleware: validates a simple Bearer token.
// Production: validate JWT (use github.com/golang-jwt/jwt),
// check expiry, extract claims, attach user ID to context.
func AuthMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		token := r.Header.Get("Authorization")
		// In production: parse "Bearer <token>", validate JWT signature and expiry.
		if token != "Bearer super-secret-token" {
			writeError(w, errUnauthorized())
			return // stop middleware chain — do NOT call next
		}

		// Attach user ID to context so downstream handlers can use it.
		// In production: extract user ID from JWT claims.
		ctx := context.WithValue(r.Context(), userIDKey, int64(1))
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// RecoveryMiddleware: catches panics in handlers and returns 500.
// Without this, a panic kills the goroutine handling the request
// but the server keeps running (Go recovers panics per-goroutine).
// However, the client gets a broken connection. Better to recover + 500.
func RecoveryMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rec := recover(); rec != nil {
				slog.Error("panic recovered",
					"panic", rec,
					"path", r.URL.Path,
					"request_id", requestIDFromCtx(r.Context()),
				)
				writeJSON(w, http.StatusInternalServerError,
					map[string]string{"error": "internal server error"})
			}
		}()
		next.ServeHTTP(w, r)
	})
}

// ============================================================
// SECTION 6: HANDLERS
// ============================================================

// UserHandler: holds dependencies. Handlers are methods on this struct.
// This is the standard Go pattern for dependency injection into handlers —
// no global state, easy to test (pass a mock store).
type UserHandler struct {
	store *userStore
}

// getIDParam: parses the {id} URL parameter using standard library.
// In Go 1.22+ ServeMux, use r.PathValue("id").
// For compatibility with chi: use chi.URLParam(r, "id").
// Here we show the stdlib 1.22 approach.
func getIDParam(r *http.Request) (int64, error) {
	idStr := r.PathValue("id") // Go 1.22+ — extracts {id} from pattern
	if idStr == "" {
		return 0, fmt.Errorf("missing id parameter")
	}
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		return 0, fmt.Errorf("id must be an integer, got %q", idStr)
	}
	if id <= 0 {
		return 0, fmt.Errorf("id must be positive, got %d", id)
	}
	return id, nil
}

// ListUsers: GET /users
func (h *UserHandler) ListUsers(w http.ResponseWriter, r *http.Request) {
	users := h.store.List()
	// Return empty array, not null, if no users — clients prefer [].
	if users == nil {
		users = []HTTPUser{}
	}
	writeJSON(w, http.StatusOK, users)
}

// GetUser: GET /users/{id}
func (h *UserHandler) GetUser(w http.ResponseWriter, r *http.Request) {
	id, err := getIDParam(r)
	if err != nil {
		writeError(w, errBadRequest(err.Error()))
		return
	}

	user, ok := h.store.GetByID(id)
	if !ok {
		writeError(w, errNotFound(fmt.Sprintf("user %d not found", id)))
		return
	}

	writeJSON(w, http.StatusOK, user)
}

// CreateUser: POST /users
func (h *UserHandler) CreateUser(w http.ResponseWriter, r *http.Request) {
	// Limit body size to prevent memory exhaustion attacks.
	// http.MaxBytesReader wraps Body so reads past the limit return an error.
	r.Body = http.MaxBytesReader(w, r.Body, 1<<20) // 1 MB limit

	var req CreateUserRequest
	// json.NewDecoder streams the body — no need to ReadAll first.
	// DisallowUnknownFields makes the decoder strict — rejects unknown JSON keys.
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()

	if err := decoder.Decode(&req); err != nil {
		writeError(w, errBadRequest(fmt.Sprintf("invalid JSON: %v", err)))
		return
	}

	// Validate after decoding — decoder only checks JSON syntax, not business rules.
	if err := req.Validate(); err != nil {
		writeError(w, errBadRequest(err.Error()))
		return
	}

	user := h.store.Create(req)
	// 201 Created — not 200 OK — for successful resource creation.
	writeJSON(w, http.StatusCreated, user)
}

// UpdateUser: PATCH /users/{id}
func (h *UserHandler) UpdateUser(w http.ResponseWriter, r *http.Request) {
	id, err := getIDParam(r)
	if err != nil {
		writeError(w, errBadRequest(err.Error()))
		return
	}

	r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
	var req UpdateUserRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, errBadRequest(fmt.Sprintf("invalid JSON: %v", err)))
		return
	}

	user, ok := h.store.Update(id, req)
	if !ok {
		writeError(w, errNotFound(fmt.Sprintf("user %d not found", id)))
		return
	}

	writeJSON(w, http.StatusOK, user)
}

// DeleteUser: DELETE /users/{id}
func (h *UserHandler) DeleteUser(w http.ResponseWriter, r *http.Request) {
	id, err := getIDParam(r)
	if err != nil {
		writeError(w, errBadRequest(err.Error()))
		return
	}

	if !h.store.Delete(id) {
		writeError(w, errNotFound(fmt.Sprintf("user %d not found", id)))
		return
	}

	// 204 No Content: success with no body. Don't call Encode after this.
	w.WriteHeader(http.StatusNoContent)
}

// HealthCheck: GET /health — liveness probe for Kubernetes/load balancers.
func HealthCheck(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{
		"status": "ok",
		"time":   time.Now().UTC().Format(time.RFC3339),
	})
}

// ============================================================
// SECTION 7: ROUTER SETUP (STDLIB NET/HTTP 1.22)
// ============================================================

// newRouter: builds and returns the ServeMux with all routes registered.
// Go 1.22 ServeMux supports method+path patterns: "GET /users/{id}"
// For a third-party router, replace with chi.NewRouter() and r.Get/Post etc.
func newRouter(h *UserHandler) *http.ServeMux {
	mux := http.NewServeMux()

	// Health check — no auth required.
	mux.HandleFunc("GET /health", HealthCheck)

	// User routes.
	mux.HandleFunc("GET /users", h.ListUsers)
	mux.HandleFunc("POST /users", h.CreateUser)
	mux.HandleFunc("GET /users/{id}", h.GetUser)
	mux.HandleFunc("PATCH /users/{id}", h.UpdateUser)
	mux.HandleFunc("DELETE /users/{id}", h.DeleteUser)

	return mux
}

// chainMiddleware: applies middleware in order (first = outermost = runs first).
// Equivalent to chi.Chain(m1, m2, m3).Handler(mux).
func chainMiddleware(h http.Handler, middlewares ...func(http.Handler) http.Handler) http.Handler {
	// Apply in reverse so the first middleware in the slice runs first.
	for i := len(middlewares) - 1; i >= 0; i-- {
		h = middlewares[i](h)
	}
	return h
}

// ============================================================
// SECTION 8: GRACEFUL SHUTDOWN
// ============================================================

// runServer: starts the HTTP server and handles graceful shutdown.
// Graceful shutdown: stop accepting new connections, wait for in-flight
// requests to complete (up to timeout), then exit.
// Without this: a SIGTERM during a request causes the client to see a broken connection.
func runServer(addr string, handler http.Handler) error {
	// Configure the server with explicit timeouts.
	// ReadTimeout: time to read the full request (headers + body).
	// WriteTimeout: time to write the full response.
	// IdleTimeout: time to keep idle keep-alive connections open.
	// Without timeouts, slow clients can hold connections indefinitely.
	srv := &http.Server{
		Addr:         addr,
		Handler:      handler,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  120 * time.Second,
		// BaseContext: sets context for all connections — useful to inject app context.
		// BaseContext: func(net.Listener) context.Context { return appCtx },
	}

	// Listen on the address first so we can report the actual port.
	listener, err := net.Listen("tcp", addr)
	if err != nil {
		return fmt.Errorf("listen %s: %w", addr, err)
	}

	slog.Info("server started", "addr", listener.Addr().String())

	// Signal handling: wait for SIGTERM (Kubernetes) or SIGINT (Ctrl+C).
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGTERM, syscall.SIGINT)

	// serverErr: receives error from Serve() (non-nil unless ErrServerClosed).
	serverErr := make(chan error, 1)
	go func() {
		// Serve blocks until Shutdown() is called. Returns ErrServerClosed on shutdown.
		if err := srv.Serve(listener); !errors.Is(err, http.ErrServerClosed) {
			serverErr <- err
		}
	}()

	// Block until signal or server error.
	select {
	case err := <-serverErr:
		return fmt.Errorf("server error: %w", err)
	case sig := <-quit:
		slog.Info("shutting down", "signal", sig)
	}

	// Graceful shutdown: give in-flight requests 30 seconds to complete.
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer shutdownCancel()

	if err := srv.Shutdown(shutdownCtx); err != nil {
		return fmt.Errorf("shutdown error: %w", err)
	}

	slog.Info("server stopped cleanly")
	return nil
}

// ============================================================
// SECTION 9: MAIN
// ============================================================

func main() {
	// Configure slog with JSON handler for structured, parseable logs.
	// JSON is preferred in production (Datadog, Splunk, CloudWatch parse it).
	// For local development, use slog.NewTextHandler for human-readable output.
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo, // filter out Debug logs in production
	}))
	slog.SetDefault(logger) // make this the package-level default logger

	// Build dependencies.
	store := newUserStore()
	handler := &UserHandler{store: store}
	router := newRouter(handler)

	// Wrap router with middleware. Order: Recovery → RequestID → Logging → Auth → router.
	// Recovery is outermost so it catches panics from all other middleware.
	// Auth wraps the router directly — applies to all routes.
	// For per-route auth, apply AuthMiddleware at the route level instead.
	wrappedHandler := chainMiddleware(
		router,
		RecoveryMiddleware,
		RequestIDMiddleware,
		LoggingMiddleware,
		AuthMiddleware,
	)

	// Run server. This blocks until shutdown.
	if err := runServer(":8080", wrappedHandler); err != nil {
		slog.Error("server failed", "error", err)
		os.Exit(1)
	}
}

// ============================================================
// SECTION 10: CHI ROUTER REFERENCE (commented — requires go get)
// ============================================================
/*
import "github.com/go-chi/chi/v5"
import "github.com/go-chi/chi/v5/middleware"

func newChiRouter(h *UserHandler) http.Handler {
    r := chi.NewRouter()

    // Built-in middleware from chi/middleware package.
    r.Use(middleware.RequestID)       // adds X-Request-Id header
    r.Use(middleware.RealIP)         // reads X-Forwarded-For
    r.Use(middleware.Logger)         // logs every request
    r.Use(middleware.Recoverer)      // catches panics

    // Route group with version prefix.
    r.Route("/api/v1", func(r chi.Router) {
        // Apply auth to everything in this group.
        r.Use(AuthMiddleware)

        r.Get("/users", h.ListUsers)
        r.Post("/users", h.CreateUser)

        // Nested route with URL parameter.
        r.Route("/users/{id}", func(r chi.Router) {
            r.Get("/", h.GetUser)
            r.Patch("/", h.UpdateUser)
            r.Delete("/", h.DeleteUser)
        })
    })

    // Health check outside auth group.
    r.Get("/health", HealthCheck)

    return r
}

// With chi, use chi.URLParam instead of r.PathValue:
// idStr := chi.URLParam(r, "id")
*/
