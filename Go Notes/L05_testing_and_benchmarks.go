// ============================================================
// L05: Testing and Benchmarks
// ============================================================
// WHAT: Go's built-in testing ecosystem — unit tests, table-driven
//       tests, subtests, mocking via interfaces, HTTP testing,
//       benchmarks, fuzz testing, and coverage measurement.
// WHY:  Go ships a full testing toolkit in the standard library.
//       No framework needed for fundamentals. Proper tests catch
//       regressions, document intent, and let you refactor safely.
// LEVEL: Advanced
// ============================================================
/*
CONCEPT OVERVIEW:
  Go tests live in _test.go files alongside production code. The test
  binary is compiled separately by `go test`. Test functions must be
  named TestXxx and accept *testing.T. Benchmarks accept *testing.B.
  Fuzz functions accept *testing.F. The testing package provides
  structured failure reporting, subtests, and parallelism built-in.

PRODUCTION USE CASE:
  A user service with a repository interface mocked in tests, an HTTP
  handler verified with httptest, and the hot-path encoding function
  benchmarked. CI runs `go test ./... -race -cover` on every PR. The
  fuzz target guards the custom parser against malformed input.

COMMON MISTAKES:
  - Using t.Fatal in goroutines spawned inside tests (panics — use
    t.Error and coordinate via channels or WaitGroup instead).
  - Calling t.Parallel() after any mutating call on shared state.
  - Benchmarking inside a non-benchmark function (b.N not calibrated).
  - Mocking a concrete struct instead of an interface (couples tests
    to implementation and prevents swapping the real dep later).
  - Forgetting to call resp.Body.Close() in httptest-based tests,
    which leaks goroutines detected by the race detector.
*/

// NOTE: this is a documentation/teaching file.
// Build tag prevents it from being compiled into non-test binaries.
//go:build ignore

package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// ============================================================
// DOMAIN TYPES (minimal, to make the test examples self-contained)
// ============================================================

// User is the core domain object used across examples below.
type User struct {
	ID    int
	Name  string
	Email string
}

// ValidationError carries field-level context on bad input.
type ValidationError struct {
	Field   string
	Message string
}

func (e *ValidationError) Error() string {
	return fmt.Sprintf("validation error: field=%s msg=%s", e.Field, e.Message)
}

// ErrNotFound is the sentinel returned when a lookup finds nothing.
var ErrNotFound = errors.New("user not found")

// ============================================================
// REPOSITORY INTERFACE — the key to testable code
// ============================================================

// UserRepository is an interface, not a struct.
// Tests supply a fake implementation; production supplies Postgres.
// Rule: mock interfaces, never mock concrete structs.
type UserRepository interface {
	GetByID(id int) (*User, error)
	Create(u *User) error
	Update(u *User) error
	Delete(id int) error
}

// ============================================================
// SERVICE LAYER — depends on the interface, not a specific DB
// ============================================================

// UserService holds business logic.
// It receives UserRepository at construction time (dependency injection).
type UserService struct {
	repo UserRepository
}

// NewUserService wires a service to its repository.
func NewUserService(repo UserRepository) *UserService {
	return &UserService{repo: repo}
}

// GetUser fetches a user; wraps repo errors with context.
func (s *UserService) GetUser(id int) (*User, error) {
	if id <= 0 {
		// Validate before hitting the DB — cheap check saves a round-trip.
		return nil, &ValidationError{Field: "id", Message: "must be positive"}
	}
	u, err := s.repo.GetByID(id)
	if err != nil {
		// %w preserves the original error for errors.Is / errors.As unwrapping.
		return nil, fmt.Errorf("UserService.GetUser: %w", err)
	}
	return u, nil
}

// CreateUser validates then delegates to the repository.
func (s *UserService) CreateUser(name, email string) (*User, error) {
	if name == "" {
		return nil, &ValidationError{Field: "name", Message: "required"}
	}
	if !strings.Contains(email, "@") {
		return nil, &ValidationError{Field: "email", Message: "invalid format"}
	}
	u := &User{Name: name, Email: email}
	if err := s.repo.Create(u); err != nil {
		return nil, fmt.Errorf("UserService.CreateUser: %w", err)
	}
	return u, nil
}

// ============================================================
// MOCK REPOSITORY — test-only fake implementation
// ============================================================

// mockUserRepo is a hand-rolled mock that satisfies UserRepository.
// It stores users in-memory and records which methods were called.
// For larger projects, tools like mockery generate this automatically.
type mockUserRepo struct {
	users      map[int]*User
	createErr  error // inject an error to test sad paths
	nextID     int
	callCounts map[string]int // observability: did the right method get called?
}

func newMockRepo() *mockUserRepo {
	return &mockUserRepo{
		users:      make(map[int]*User),
		nextID:     1,
		callCounts: make(map[string]int),
	}
}

func (m *mockUserRepo) GetByID(id int) (*User, error) {
	m.callCounts["GetByID"]++
	u, ok := m.users[id]
	if !ok {
		return nil, ErrNotFound // return the sentinel, not a raw string
	}
	return u, nil
}

func (m *mockUserRepo) Create(u *User) error {
	m.callCounts["Create"]++
	if m.createErr != nil {
		return m.createErr // caller can inject failures
	}
	u.ID = m.nextID
	m.nextID++
	m.users[u.ID] = u
	return nil
}

func (m *mockUserRepo) Update(u *User) error {
	m.callCounts["Update"]++
	if _, ok := m.users[u.ID]; !ok {
		return ErrNotFound
	}
	m.users[u.ID] = u
	return nil
}

func (m *mockUserRepo) Delete(id int) error {
	m.callCounts["Delete"]++
	delete(m.users, id)
	return nil
}

// ============================================================
// UNIT TESTS — table-driven pattern
// ============================================================

// TestGetUser demonstrates the canonical table-driven test structure.
// Each row is a named scenario with its own inputs and expectations.
func TestGetUser(t *testing.T) {
	// Seed the mock with one existing user.
	repo := newMockRepo()
	repo.users[1] = &User{ID: 1, Name: "Alice", Email: "alice@example.com"}
	svc := NewUserService(repo)

	// testCases is a slice of anonymous structs — readable and exhaustive.
	testCases := []struct {
		name      string
		id        int
		wantUser  *User
		wantErr   error // nil means "expect no error"
		wantIsErr bool  // true when we only care about error type, not value
	}{
		{
			name:     "existing user returns correctly",
			id:       1,
			wantUser: &User{ID: 1, Name: "Alice", Email: "alice@example.com"},
			wantErr:  nil,
		},
		{
			name:        "missing user returns ErrNotFound",
			id:          999,
			wantUser:    nil,
			wantIsErr:   true, // wrapped by service, so check via errors.Is
		},
		{
			name:      "zero id returns ValidationError",
			id:        0,
			wantUser:  nil,
			wantIsErr: true,
		},
		{
			name:      "negative id returns ValidationError",
			id:        -5,
			wantUser:  nil,
			wantIsErr: true,
		},
	}

	for _, tc := range testCases {
		tc := tc // capture range variable — required before Go 1.22 loop-var fix
		t.Run(tc.name, func(t *testing.T) {
			// t.Parallel() here would let all subtests run concurrently.
			// Safe when subtests share only read-only state.
			// t.Parallel()

			got, err := svc.GetUser(tc.id)

			if tc.wantErr == nil && !tc.wantIsErr {
				// Happy path: no error expected.
				if err != nil {
					// t.Fatalf stops this subtest immediately — right for setup failures.
					t.Fatalf("GetUser(%d) unexpected error: %v", tc.id, err)
				}
				if got == nil || *got != *tc.wantUser {
					// t.Errorf continues the test — collects all failures.
					t.Errorf("GetUser(%d) = %+v, want %+v", tc.id, got, tc.wantUser)
				}
			} else {
				// Sad path: some error expected.
				if err == nil {
					t.Errorf("GetUser(%d) expected an error, got nil", tc.id)
				}
				// errors.Is walks the wrapping chain, so wrapped errors match.
				if tc.wantErr != nil && !errors.Is(err, tc.wantErr) {
					t.Errorf("GetUser(%d) error = %v, want %v", tc.id, err, tc.wantErr)
				}
			}
		})
	}
}

// TestCreateUser covers the creation happy path and validation failures.
func TestCreateUser(t *testing.T) {
	testCases := []struct {
		name    string
		uName   string
		email   string
		wantErr bool
		wantAs  interface{} // type to errors.As into
	}{
		{"valid input creates user", "Bob", "bob@example.com", false, nil},
		{"empty name rejected", "", "bob@example.com", true, &ValidationError{}},
		{"bad email rejected", "Bob", "not-an-email", true, &ValidationError{}},
	}

	for _, tc := range testCases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			repo := newMockRepo() // fresh repo per subtest avoids state leakage
			svc := NewUserService(repo)

			u, err := svc.CreateUser(tc.uName, tc.email)
			if tc.wantErr {
				if err == nil {
					t.Fatalf("expected error, got nil")
				}
				// errors.As checks if any error in the chain matches the target type.
				if tc.wantAs != nil {
					var ve *ValidationError
					if !errors.As(err, &ve) {
						t.Errorf("want ValidationError, got %T: %v", err, err)
					}
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if u.ID == 0 {
				t.Error("expected repo to assign an ID, got 0")
			}
			if repo.callCounts["Create"] != 1 {
				t.Errorf("expected Create called once, got %d", repo.callCounts["Create"])
			}
		})
	}
}

// ============================================================
// HTTP HANDLER + HTTPTEST
// ============================================================

// userHandler is the HTTP layer — thin wrapper around UserService.
type userHandler struct {
	svc *UserService
}

// ServeHTTP handles GET /users/{id} — simplified for illustration.
func (h *userHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// In real code you'd use r.PathValue("id") (Go 1.22+) or a router.
	idStr := r.URL.Query().Get("id")
	if idStr == "" {
		http.Error(w, "missing id", http.StatusBadRequest)
		return
	}
	var id int
	fmt.Sscan(idStr, &id) //nolint:errcheck // simplified for brevity

	u, err := h.svc.GetUser(id)
	if err != nil {
		if errors.Is(err, ErrNotFound) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		var ve *ValidationError
		if errors.As(err, &ve) {
			http.Error(w, ve.Error(), http.StatusBadRequest)
			return
		}
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(u) //nolint:errcheck
}

// TestUserHandler tests the HTTP layer with httptest — no real port opened.
func TestUserHandler(t *testing.T) {
	// Wire up a service backed by an in-memory mock.
	repo := newMockRepo()
	repo.users[1] = &User{ID: 1, Name: "Alice", Email: "alice@example.com"}
	svc := NewUserService(repo)
	handler := &userHandler{svc: svc}

	testCases := []struct {
		name       string
		queryID    string
		wantStatus int
	}{
		{"found", "1", http.StatusOK},
		{"not found", "999", http.StatusNotFound},
		{"invalid id", "0", http.StatusBadRequest},
		{"missing id param", "", http.StatusBadRequest},
	}

	for _, tc := range testCases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			// httptest.NewRequest builds a synthetic *http.Request.
			req := httptest.NewRequest(http.MethodGet, "/?id="+tc.queryID, nil)
			// httptest.NewRecorder captures response without a real TCP connection.
			rr := httptest.NewRecorder()

			handler.ServeHTTP(rr, req)

			if rr.Code != tc.wantStatus {
				t.Errorf("status = %d, want %d (body: %s)", rr.Code, tc.wantStatus, rr.Body.String())
			}
		})
	}
}

// TestUserHandler_RealServer shows httptest.NewServer: an actual HTTP server
// on a random local port. Useful when testing http.Client middleware chains.
func TestUserHandler_RealServer(t *testing.T) {
	repo := newMockRepo()
	repo.users[7] = &User{ID: 7, Name: "Carol", Email: "carol@example.com"}
	svc := NewUserService(repo)
	handler := &userHandler{svc: svc}

	// NewServer starts a real goroutine with a listener on a random port.
	ts := httptest.NewServer(handler)
	defer ts.Close() // always close to release the port

	resp, err := http.Get(ts.URL + "/?id=7")
	if err != nil {
		t.Fatalf("request failed: %v", err)
	}
	defer resp.Body.Close() // leak if forgotten — race detector will catch it

	if resp.StatusCode != http.StatusOK {
		t.Errorf("status = %d, want 200", resp.StatusCode)
	}
}

// ============================================================
// BENCHMARKS
// ============================================================

// encodeUsers is the function under benchmark — JSON encoding a user slice.
func encodeUsers(users []User) ([]byte, error) {
	return json.Marshal(users)
}

// BenchmarkEncodeUsers measures encoding throughput.
// Run with: go test -bench=BenchmarkEncodeUsers -benchmem -count=5
//
// b.N is auto-calibrated: the testing framework increases it until the
// benchmark runs long enough for stable timing (~1 second by default).
func BenchmarkEncodeUsers(b *testing.B) {
	users := make([]User, 100)
	for i := range users {
		users[i] = User{ID: i + 1, Name: "User", Email: "u@example.com"}
	}

	b.ReportAllocs()  // print allocs/op and bytes/op in the output
	b.ResetTimer()    // exclude setup time from the measurement

	for i := 0; i < b.N; i++ {
		_, err := encodeUsers(users)
		if err != nil {
			b.Fatal(err) // stop benchmark on unexpected error
		}
	}
}

// BenchmarkEncodeUsers_Preallocated compares pre-allocating the output buffer.
// Compare the two with: go test -bench=BenchmarkEncodeUsers -benchmem
func BenchmarkEncodeUsers_Preallocated(b *testing.B) {
	users := make([]User, 100)
	for i := range users {
		users[i] = User{ID: i + 1, Name: "User", Email: "u@example.com"}
	}

	var buf strings.Builder
	b.ReportAllocs()
	b.ResetTimer()

	for i := 0; i < b.N; i++ {
		buf.Reset() // reuse builder allocation
		enc := json.NewEncoder(&buf)
		if err := enc.Encode(users); err != nil {
			b.Fatal(err)
		}
	}
}

// ============================================================
// FUZZ TESTING
// ============================================================

// parseEmailDomain extracts the domain from an email — custom parser.
// Fuzz testing will find inputs that panic or return unexpected results.
func parseEmailDomain(email string) (string, error) {
	idx := strings.LastIndex(email, "@")
	if idx < 0 {
		return "", fmt.Errorf("no @ in email: %q", email)
	}
	domain := email[idx+1:]
	if domain == "" {
		return "", fmt.Errorf("empty domain in email: %q", email)
	}
	return domain, nil
}

// FuzzParseEmailDomain teaches the fuzzer with seed values, then lets it
// mutate inputs freely to find panics or crashes.
// Run with: go test -fuzz=FuzzParseEmailDomain -fuzztime=30s
func FuzzParseEmailDomain(f *testing.F) {
	// Seed corpus: known good and known bad inputs.
	f.Add("user@example.com")
	f.Add("no-at-sign")
	f.Add("@nodomain")
	f.Add("user@")
	f.Add("") // empty string edge case

	// The fuzzer will mutate these seeds and call the target repeatedly.
	// We only care that the function never panics — errors are fine.
	f.Fuzz(func(t *testing.T, input string) {
		// Any panic inside here is reported as a test failure with the input.
		domain, err := parseEmailDomain(input)
		if err != nil {
			return // expected for malformed inputs
		}
		// Invariant: if no error, domain must not be empty.
		if domain == "" {
			t.Errorf("parseEmailDomain(%q) returned empty domain without error", input)
		}
	})
}

// ============================================================
// PARALLEL SUBTESTS — run independent subtests concurrently
// ============================================================

// TestParallelSubtests demonstrates safe parallel subtest execution.
// Each subtest calls t.Parallel() to join the parallel group.
// The parent test waits for all parallel subtests to complete.
func TestParallelSubtests(t *testing.T) {
	ids := []int{1, 2, 3, 4, 5}

	for _, id := range ids {
		id := id // capture — essential before Go 1.22
		t.Run(fmt.Sprintf("user_%d", id), func(t *testing.T) {
			t.Parallel() // this subtest may run concurrently with siblings

			// Simulate work that benefits from parallelism (e.g. I/O waits).
			time.Sleep(10 * time.Millisecond)

			if id <= 0 {
				t.Errorf("invalid id: %d", id)
			}
		})
	}
	// All parallel subtests complete before t.Run returns here.
}

// ============================================================
// COVERAGE NOTE
// ============================================================
// Run coverage:
//   go test -cover ./...
//   go test -coverprofile=cover.out ./...
//   go tool cover -html=cover.out        (opens browser with line-level view)
//   go tool cover -func=cover.out        (prints per-function percentages)
//
// Target: aim for >80% coverage on business logic.
// Coverage alone does not prove correctness — assertions matter more.
// ============================================================

func main() {
	// Placeholder so the file compiles with go:build ignore removed.
	// Real test files end in _test.go and have no main().
	fmt.Println("Run with: go test ./... -v -race -cover")
	fmt.Println("Benchmark: go test -bench=. -benchmem")
	fmt.Println("Fuzz:      go test -fuzz=FuzzParseEmailDomain -fuzztime=30s")
}
