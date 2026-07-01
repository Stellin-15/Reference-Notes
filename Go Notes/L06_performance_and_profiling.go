// ============================================================
// L06: Performance, Profiling & Memory Optimisation in Go
// ============================================================
// WHAT: pprof profiler, escape analysis, sync.Pool, strings.Builder,
//       slice/map pre-allocation, GC tuning (GOGC/GOMEMLIMIT),
//       struct alignment, and sync.Map vs mutex-guarded map.
// WHY:  Every heap allocation is a future GC pause. Understanding where
//       allocations happen and how to eliminate them separates services
//       that handle 10k req/s from those that handle 100k req/s.
// LEVEL: Advanced
// ============================================================
/* CONCEPT OVERVIEW:
   pprof is Go's built-in profiler. Importing net/http/pprof registers
   /debug/pprof/* endpoints for CPU, heap, goroutine, and mutex profiles.
   Escape analysis (-gcflags="-m") shows at compile time which variables
   escape to the heap. sync.Pool recycles short-lived objects, eliminating
   repeated allocations of identical types. strings.Builder avoids O(n²)
   string concatenation. Struct field ordering eliminates compiler-added
   padding bytes, saving memory at millions of instances.

   PRODUCTION USE CASE:
   A JSON API processed 2,000 req/s. Heap profiling showed json.Marshal
   allocating a new []byte buffer per call. Replacing it with a sync.Pool
   and pre-allocating response slices raised throughput to 18,000 req/s
   and halved GC pause frequency. GOMEMLIMIT prevented OOM kills under burst.

   COMMON MISTAKES:
   1. Not using -http flag with pprof — missing the flamegraph view that
      makes hotspots obvious in seconds.
   2. Wrong type assertion on sync.Pool.Get() — always assert immediately.
   3. Assuming sync.Map beats map+RWMutex for all workloads — sync.Map
      wins only for high-read, low-write, disjoint-key access patterns.
   4. Forgetting b.ResetTimer() after expensive benchmark setup — inflates
      ns/op and misleads future readers of the benchmark output.
   5. Setting GOGC=off without GOMEMLIMIT — the process will eventually OOM.
*/

//go:build ignore

package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	_ "net/http/pprof" // registers /debug/pprof/* on http.DefaultServeMux
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"unsafe"
)

// ===========================================================================
// SECTION 1 — pprof: registering the debug endpoints
// ===========================================================================
// After importing _ "net/http/pprof" the following endpoints are live:
//   /debug/pprof/profile?seconds=30  — CPU profile (blocks for N seconds)
//   /debug/pprof/heap                — heap allocation snapshot
//   /debug/pprof/goroutine           — all goroutine stack traces (leak detection)
//   /debug/pprof/mutex               — mutex contention (enable below)
//   /debug/pprof/allocs              — allocation-focused heap view
//
// Usage:
//   go tool pprof -http=:8081 http://localhost:6060/debug/pprof/heap
//   go tool pprof http://localhost:6060/debug/pprof/profile?seconds=30
//
// NEVER expose pprof on the public port — it reveals heap contents.
// Bind to localhost or protect with VPN/mTLS.

func startProfilingServer() {
	runtime.SetMutexProfileFraction(5) // sample 1-in-5 mutex contentions
	runtime.SetBlockProfileRate(1000)  // sample 1-in-1000 blocking events
	go func() {
		log.Println("pprof on localhost:6060")
		log.Fatal(http.ListenAndServe("localhost:6060", nil))
	}()
}

// ===========================================================================
// SECTION 2 — Escape Analysis: stack vs heap
// ===========================================================================
// Run: go build -gcflags="-m" ./...
// Compiler output: "moved to heap: u" = heap allocation = GC pressure.
// Stack allocations are free: no GC involvement, no pointer bookkeeping.

// User is the domain struct used in all examples.
// Field ordering follows Section 7 (largest to smallest for alignment).
type User struct {
	ID    int64  // 8 bytes — largest field first
	Email string // 16 bytes (pointer + length)
	Name  string // 16 bytes
	Score int32  // 4 bytes
	_     [4]byte // explicit padding to 48; makes intention visible in diffs
}

// escapesToHeap — returning a pointer forces heap allocation because the
// value must outlive the current stack frame. Unavoidable when sharing
// across goroutines, but avoid it for hot-path internal values.
func escapesToHeap() *User {
	u := User{ID: 1} // compiler: "moved to heap: u"
	return &u
}

// staysOnStack — returns a value copy. Caller gets it on its own stack frame.
// No heap, no GC. Prefer this for small structs on hot paths.
func staysOnStack() User {
	return User{ID: 2}
}

// ===========================================================================
// SECTION 3 — sync.Pool: recycling allocations
// ===========================================================================

// bufferPool recycles *bytes.Buffer. The GC may clear a Pool between
// collection cycles — Pool is a cache hint, not a guarantee.
// Always Reset() before use; the returned object may be dirty.
var bufferPool = sync.Pool{
	New: func() interface{} { return &bytes.Buffer{} },
}

// encodeWithPool reuses a buffer instead of allocating one per call.
// At 10k req/s this eliminates 10k allocations/second.
func encodeWithPool(u User) ([]byte, error) {
	buf := bufferPool.Get().(*bytes.Buffer) // type-assert immediately
	buf.Reset()                             // CRITICAL: reset before use
	defer bufferPool.Put(buf)              // return on all exit paths

	if err := json.NewEncoder(buf).Encode(u); err != nil {
		return nil, fmt.Errorf("encode: %w", err)
	}
	// Copy before returning the buffer — next Get() would overwrite Bytes().
	out := make([]byte, buf.Len())
	copy(out, buf.Bytes())
	return out, nil
}

// encodeNaive allocates a new buffer each call — the baseline to beat.
func encodeNaive(u User) ([]byte, error) { return json.Marshal(u) }

// ===========================================================================
// SECTION 4 — strings.Builder: efficient string construction
// ===========================================================================

// buildNaive: O(n²) — each + copies all previous content into a new string.
// Never use string + in a loop. Even fmt.Sprintf in a loop is better.
func buildNaive(users []User) string {
	s := ""
	for _, u := range users {
		s += fmt.Sprintf("%d:%s\n", u.ID, u.Name) // allocation per iteration
	}
	return s
}

// buildFast: O(n) — single growing buffer. Grow() pre-sizes to avoid resizing.
func buildFast(users []User) string {
	var b strings.Builder
	b.Grow(len(users) * 32) // avoids internal resizing
	for _, u := range users {
		fmt.Fprintf(&b, "%d:%s\n", u.ID, u.Name)
	}
	return b.String() // single allocation
}

// bytes.Buffer alternative when the caller needs []byte (saves string→[]byte copy).
func buildBytes(users []User) []byte {
	var buf bytes.Buffer
	buf.Grow(len(users) * 32)
	for _, u := range users {
		fmt.Fprintf(&buf, "%d:%s\n", u.ID, u.Name)
	}
	return buf.Bytes()
}

// ===========================================================================
// SECTION 5 — Slice and Map pre-allocation
// ===========================================================================

// noPrealloc: starts with nil slice; append doubles capacity ~log₂(n) times,
// each triggering a full copy. For 1000 elements: ~10 reallocations.
func noPrealloc(users []User) []int64 {
	var ids []int64
	for _, u := range users {
		ids = append(ids, u.ID)
	}
	return ids
}

// prealloc: make([]T, 0, cap) — exact capacity, zero reallocations.
func prealloc(users []User) []int64 {
	ids := make([]int64, 0, len(users)) // length=0, capacity=n
	for _, u := range users {
		ids = append(ids, u.ID) // never reallocates
	}
	return ids
}

// Map pre-allocation: make(map[K]V, hint) — hints the runtime to allocate
// enough buckets up front. Eliminates rehash events during insertion.
func buildIndex(users []User) map[int64]User {
	m := make(map[int64]User, len(users)) // hint avoids rehash
	for _, u := range users {
		m[u.ID] = u
	}
	return m
}

// ===========================================================================
// SECTION 6 — GC Tuning: GOGC and GOMEMLIMIT
// ===========================================================================
// GOGC=100 (default): trigger GC when heap grows 100% above previous live heap.
//   If 50 MB live after last GC → trigger at 100 MB total.
// GOGC=200: trigger at 200% growth → half the GC frequency, ~2× memory.
// GOGC=off:  disable GC (only safe with a hard GOMEMLIMIT).
//
// GOMEMLIMIT (Go 1.19+): hard cap on total Go runtime memory.
//   The GC runs more aggressively as the process approaches the limit.
//   Set to ~80% of the container's memory limit to prevent OOM kills.
//
//   Kubernetes pod with 2 GiB limit:
//     GOGC=200          # halve GC cycles
//     GOMEMLIMIT=1536MiB # 1.5 GiB hard cap
//
// Programmatic (for tests or when env is not available):
//   import "runtime/debug"
//   debug.SetGCPercent(200)
//   debug.SetMemoryLimit(1536 * 1024 * 1024)
//   runtime.GC() // force a cycle (useful before benchmarks)

func printMemStats(label string) {
	var m runtime.MemStats
	runtime.ReadMemStats(&m)
	fmt.Printf("[%s] HeapAlloc=%d KB HeapObjects=%d NumGC=%d\n",
		label, m.HeapAlloc/1024, m.HeapObjects, m.NumGC)
}

// ===========================================================================
// SECTION 7 — Struct alignment: eliminate padding
// ===========================================================================
// The CPU requires fields to be aligned to their own size.
// A bool (1 byte) before an int64 (8 bytes) forces 7 bytes of padding.
// Ordering fields largest-first eliminates most padding automatically.
// Tool: go install golang.org/x/tools/go/analysis/passes/fieldalignment/cmd/fieldalignment@latest
// Run:  fieldalignment ./...

type unaligned struct {
	Active bool    // 1 byte + 7 padding
	Score  int64   // 8 bytes
	Flag   bool    // 1 byte + 3 padding
	Count  int32   // 4 bytes
	// sizeof = 24 bytes
}

type aligned struct {
	Score  int64 // 8 bytes — largest first
	Count  int32 // 4 bytes
	Active bool  // 1 byte
	Flag   bool  // 1 byte
	_      [2]byte
	// sizeof = 16 bytes — saves 8 bytes per instance
}

func logSizes() {
	fmt.Printf("unaligned: %d bytes\n", unsafe.Sizeof(unaligned{}))
	fmt.Printf("aligned:   %d bytes\n", unsafe.Sizeof(aligned{}))
}

// ===========================================================================
// SECTION 8 — sync.Map vs map+RWMutex
// ===========================================================================
// sync.Map: lock-free read path using an internal read-only copy.
//   Win: high-read, low-write, disjoint keys (config cache, routing table).
//   Loss: write-heavy workloads — the internal dirty promotion is expensive.
//
// map+RWMutex: explicit locking.
//   Win: balanced read/write, frequent key mutation, or when Range is needed.

type rwCache struct {
	mu   sync.RWMutex
	data map[string]string
}

func (c *rwCache) Get(k string) (string, bool) {
	c.mu.RLock(); defer c.mu.RUnlock()
	v, ok := c.data[k]; return v, ok
}
func (c *rwCache) Set(k, v string) {
	c.mu.Lock(); defer c.mu.Unlock()
	c.data[k] = v
}

type smCache struct{ m sync.Map }

func (c *smCache) Get(k string) (string, bool) {
	v, ok := c.m.Load(k)
	if !ok { return "", false }
	return v.(string), true
}
func (c *smCache) Set(k, v string) { c.m.Store(k, v) }

// AtomicCounter: ~10× faster than mutex for pure increment workloads.
type AtomicCounter struct{ n int64 }

func (c *AtomicCounter) Inc()       { atomic.AddInt64(&c.n, 1) }
func (c *AtomicCounter) Value() int64 { return atomic.LoadInt64(&c.n) }

// ===========================================================================
// SECTION 9 — Benchmarks: naive vs optimised
// ===========================================================================
// Run: go test -bench=. -benchmem -count=3 ./...
// Output columns: ns/op  B/op  allocs/op

func BenchmarkEncodeNaive(b *testing.B) {
	u := User{ID: 1, Name: "Alice", Email: "a@b.com", Score: 5}
	b.ReportAllocs(); b.ResetTimer()
	for range b.N { _, _ = encodeNaive(u) }
}

func BenchmarkEncodePool(b *testing.B) {
	u := User{ID: 1, Name: "Alice", Email: "a@b.com", Score: 5}
	b.ReportAllocs(); b.ResetTimer()
	for range b.N { _, _ = encodeWithPool(u) }
}

func BenchmarkBuildNaive(b *testing.B) {
	users := make([]User, 100)
	for i := range users { users[i] = User{ID: int64(i), Name: "u"} }
	b.ReportAllocs(); b.ResetTimer()
	for range b.N { _ = buildNaive(users) }
}

func BenchmarkBuildFast(b *testing.B) {
	users := make([]User, 100)
	for i := range users { users[i] = User{ID: int64(i), Name: "u"} }
	b.ReportAllocs(); b.ResetTimer()
	for range b.N { _ = buildFast(users) }
}

func BenchmarkNoPrealloc(b *testing.B) {
	users := make([]User, 1000)
	for i := range users { users[i] = User{ID: int64(i)} }
	b.ReportAllocs(); b.ResetTimer()
	for range b.N { _ = noPrealloc(users) }
}

func BenchmarkPrealloc(b *testing.B) {
	users := make([]User, 1000)
	for i := range users { users[i] = User{ID: int64(i)} }
	b.ReportAllocs(); b.ResetTimer()
	for range b.N { _ = prealloc(users) }
}

func main() {
	startProfilingServer()
	logSizes()
	printMemStats("startup")

	u := User{ID: 1, Name: "Alice", Email: "a@example.com", Score: 42}
	data, _ := encodeWithPool(u)
	fmt.Printf("encoded: %s\n", data)

	users := make([]User, 5)
	for i := range users { users[i] = User{ID: int64(i + 1), Name: fmt.Sprintf("u%d", i)} }
	fmt.Print(buildFast(users))

	http.Handle("/users", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		out, _ := encodeWithPool(u)
		w.Header().Set("Content-Type", "application/json")
		w.Write(out)
	}))
	log.Fatal(http.ListenAndServe(":8080", nil))
}
