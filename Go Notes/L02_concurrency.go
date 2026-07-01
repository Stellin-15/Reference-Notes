// ============================================================
// L02: Go Concurrency
// ============================================================
// WHAT: Goroutines, channels, select, WaitGroup, Mutex, Once,
//       worker pools, context cancellation, atomic operations,
//       and the patterns that make concurrent Go code correct.
// WHY:  Go's concurrency model is the reason many teams choose
//       it over Python/Ruby for backend services. Goroutines are
//       cheaper than threads (~2KB vs ~2MB stack), scheduled by
//       the Go runtime (M:N threading), and communicate via
//       channels — not shared memory. "Don't communicate by
//       sharing memory; share memory by communicating." — Go proverb.
// LEVEL: Intermediate
// ============================================================
/*
CONCEPT OVERVIEW:
    Go's concurrency primitives map to real OS/hardware concepts:
      - Goroutine  → lightweight thread (managed by Go runtime)
      - Channel    → typed pipe between goroutines (CSP model)
      - Mutex      → OS mutex (protect shared memory)
      - WaitGroup  → counter-based join point
      - Context    → cancellation + timeout propagation tree
      - atomic     → lock-free CPU instructions (CAS, ADD)

    The Go scheduler uses GOMAXPROCS OS threads (default = CPU count)
    to multiplex goroutines. A blocking syscall parks the goroutine
    and the thread picks up another goroutine. This is why Go can
    handle 100k concurrent connections with a small thread pool.

PRODUCTION USE CASE:
    Worker pool for parallel URL fetching: a fixed number of goroutines
    (bounded concurrency) read from a jobs channel and write results
    to a results channel. Context provides timeout and cancellation.
    This pattern appears in: API gateways, batch processors, web scrapers,
    data pipeline stages.

COMMON MISTAKES:
    1. Goroutine leak: goroutine blocked on a channel nobody sends to.
       Always add a ctx.Done() case or a close(ch) to unblock.
    2. Data race: two goroutines access the same variable without sync.
       Detect with: go test -race ./... or go run -race main.go
    3. Closing a nil channel: panic. Always initialize: ch := make(chan T).
    4. Closing a channel twice: panic. Only one sender should close.
    5. Receiving from a closed channel: returns zero value + ok=false.
       For-range over closed channel drains it then exits. Fine.
    6. Forgetting defer wg.Done() — WaitGroup counter never reaches 0,
       wg.Wait() blocks forever.
    7. Not deferring cancel() from context.WithCancel/WithTimeout — leaks
       the goroutine that monitors the parent context.
*/

package main

import (
	"context"
	"fmt"
	"math/rand"
	"net/http"
	"sync"
	"sync/atomic"
	"time"
)

// ============================================================
// SECTION 1: GOROUTINES
// ============================================================

func sayHello(name string) {
	fmt.Printf("Hello from %s\n", name)
}

func demonstrateGoroutines() {
	// go keyword: launch a goroutine. Non-blocking — returns immediately.
	// The goroutine runs concurrently with the calling code.
	go sayHello("goroutine-1") // fire and forget (only OK if we don't care about result)
	go sayHello("goroutine-2")

	// Problem: if main() returns before goroutines finish, they are killed.
	// Solution: sync.WaitGroup, channels, or time.Sleep (only for demos).
	time.Sleep(10 * time.Millisecond) // demo only — use WaitGroup in production

	// Goroutine with closure: captures variables from outer scope.
	// WARNING: loop variable capture is a classic bug in Go < 1.22.
	// In Go 1.22+, loop variables are per-iteration. Before that, all
	// goroutines share the SAME loop variable (captures the address).
	for i := 0; i < 3; i++ {
		i := i // re-declare i to create a new variable per iteration (pre-1.22 fix)
		go func() {
			fmt.Println("goroutine loop:", i)
		}()
	}
	time.Sleep(10 * time.Millisecond)
}

// ============================================================
// SECTION 2: CHANNELS
// ============================================================

func demonstrateChannels() {
	// Unbuffered channel: make(chan T). Sender blocks until receiver is ready.
	// Guarantees synchronization: send and receive happen at the same instant.
	ch := make(chan int)

	go func() {
		// This goroutine sends 42. It will block until main() receives.
		ch <- 42
		fmt.Println("sent 42") // prints AFTER main receives
	}()

	val := <-ch // blocks until goroutine sends
	fmt.Println("received:", val)

	// Buffered channel: make(chan T, n). Sender blocks only when buffer is full.
	// Decouples producer and consumer. Useful when you know approximate throughput.
	buffered := make(chan string, 3)
	buffered <- "a" // does NOT block — buffer has space
	buffered <- "b"
	buffered <- "c"
	// buffered <- "d" // would block — buffer is full

	// Drain the buffer.
	fmt.Println(<-buffered) // "a"
	fmt.Println(<-buffered) // "b"
	fmt.Println(<-buffered) // "c"

	// Range over channel: blocks and receives until channel is closed.
	// ALWAYS close from the SENDER side. Closing twice panics.
	jobs := make(chan int, 5)
	for i := 0; i < 5; i++ {
		jobs <- i
	}
	close(jobs) // signal: no more values

	for job := range jobs { // exits when channel is closed and drained
		fmt.Println("processing job:", job)
	}

	// Check if channel is closed (two-return form):
	nums := make(chan int, 1)
	nums <- 7
	close(nums)
	v, ok := <-nums // ok=true, v=7 (drained value)
	fmt.Println(v, ok)
	v, ok = <-nums // ok=false, v=0 (channel closed and empty)
	fmt.Println(v, ok)
}

// ============================================================
// SECTION 3: SELECT
// ============================================================

func demonstrateSelect() {
	ch1 := make(chan string, 1)
	ch2 := make(chan string, 1)

	go func() {
		time.Sleep(1 * time.Millisecond)
		ch1 <- "one"
	}()
	go func() {
		time.Sleep(2 * time.Millisecond)
		ch2 <- "two"
	}()

	// select: like switch but for channel operations.
	// Blocks until at least one case is ready.
	// If multiple cases are ready simultaneously, one is chosen at random.
	for i := 0; i < 2; i++ {
		select {
		case msg1 := <-ch1:
			fmt.Println("from ch1:", msg1)
		case msg2 := <-ch2:
			fmt.Println("from ch2:", msg2)
		case <-time.After(5 * time.Second):
			// time.After returns a channel that receives after the duration.
			// Use for per-operation timeouts within a goroutine.
			fmt.Println("timeout!")
		}
	}

	// Non-blocking select with default:
	ready := make(chan bool, 1)
	select {
	case <-ready:
		fmt.Println("ready!")
	default:
		// Runs immediately if no channel is ready — no blocking.
		fmt.Println("not ready, continuing")
	}
}

// ============================================================
// SECTION 4: WAITGROUP
// ============================================================

func demonstrateWaitGroup() {
	var wg sync.WaitGroup // zero value is valid — no initialization needed

	results := make([]string, 5) // pre-allocate so index write is safe

	for i := 0; i < 5; i++ {
		wg.Add(1) // increment counter BEFORE launching goroutine
		go func(idx int) {
			// defer wg.Done() MUST be inside the goroutine.
			// If placed outside, Done() is called before the goroutine finishes.
			defer wg.Done()
			// Simulate work.
			time.Sleep(time.Duration(rand.Intn(10)) * time.Millisecond)
			results[idx] = fmt.Sprintf("result-%d", idx) // safe: each goroutine writes different index
		}(i) // pass i as argument — avoid loop variable capture
	}

	wg.Wait() // blocks until counter reaches 0
	fmt.Println("all done:", results)
}

// ============================================================
// SECTION 5: MUTEX AND RWMUTEX
// ============================================================

// SafeCounter: thread-safe counter using sync.Mutex.
// Without the mutex, concurrent increments would cause data races.
type SafeCounter struct {
	mu    sync.Mutex // protects count. mu is NOT a pointer — zero value is unlocked.
	count int
}

func (c *SafeCounter) Increment() {
	c.mu.Lock()         // acquire exclusive lock — blocks if another goroutine holds it
	defer c.mu.Unlock() // release when function returns. ALWAYS defer Unlock after Lock.
	c.count++           // this line is now exclusively protected
}

func (c *SafeCounter) Value() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.count
}

// SafeCache: demonstrates sync.RWMutex for a read-heavy workload.
// Multiple goroutines can read simultaneously. Writers get exclusive access.
type SafeCache struct {
	mu    sync.RWMutex // read-write mutex
	cache map[string]string
}

func NewSafeCache() *SafeCache {
	return &SafeCache{cache: make(map[string]string)}
}

func (c *SafeCache) Get(key string) (string, bool) {
	c.mu.RLock()         // read lock: multiple goroutines can hold this simultaneously
	defer c.mu.RUnlock() // release read lock
	val, ok := c.cache[key]
	return val, ok
}

func (c *SafeCache) Set(key, value string) {
	c.mu.Lock()         // write lock: exclusive — blocks all readers and writers
	defer c.mu.Unlock()
	c.cache[key] = value
}

// ============================================================
// SECTION 6: SYNC.ONCE
// ============================================================

// Simulated DB connection — expensive to create.
type DBConnection struct {
	dsn string
}

var (
	dbOnce       sync.Once
	dbConnection *DBConnection
)

// GetDB: singleton using sync.Once. Thread-safe lazy initialization.
// No matter how many goroutines call GetDB concurrently, the init
// function runs exactly ONCE. Subsequent calls return the cached value.
func GetDB() *DBConnection {
	dbOnce.Do(func() {
		// This runs once even if 1000 goroutines call GetDB simultaneously.
		fmt.Println("initializing DB connection...")
		dbConnection = &DBConnection{dsn: "postgres://localhost/mydb"}
	})
	return dbConnection
}

// ============================================================
// SECTION 7: CONTEXT
// ============================================================

// doWork simulates an operation that respects context cancellation.
// RULE: pass context as first parameter to every function that does IO.
// RULE: check ctx.Done() in loops or blocking operations.
func doWork(ctx context.Context, id int) error {
	select {
	case <-time.After(50 * time.Millisecond): // simulate work
		fmt.Printf("worker %d done\n", id)
		return nil
	case <-ctx.Done():
		// ctx.Done() is closed when: cancel() is called, timeout expires,
		// or deadline passes. ctx.Err() tells you which.
		return fmt.Errorf("worker %d cancelled: %w", id, ctx.Err())
	}
}

func demonstrateContext() {
	// context.Background(): root context. Never cancelled.
	// Always used as the starting point for a context tree.
	rootCtx := context.Background()

	// WithTimeout: automatically cancels after duration.
	// ALWAYS defer cancel() — failure to cancel leaks the monitoring goroutine.
	ctx, cancel := context.WithTimeout(rootCtx, 200*time.Millisecond)
	defer cancel() // even if timeout fires first, cancel is safe to call

	err := doWork(ctx, 1)
	if err != nil {
		fmt.Println("work error:", err)
	}

	// WithCancel: manual cancellation. Cancel when done or on error.
	ctx2, cancel2 := context.WithCancel(rootCtx)

	go func() {
		time.Sleep(30 * time.Millisecond)
		cancel2() // cancel all operations using ctx2
	}()

	err = doWork(ctx2, 2)
	fmt.Println("ctx2 result:", err)

	// context.WithValue: attach request-scoped data (request ID, user ID, trace ID).
	// Use typed keys (never strings) to avoid collisions between packages.
	type contextKey string
	const requestIDKey contextKey = "requestID"

	ctx3 := context.WithValue(rootCtx, requestIDKey, "req-abc-123")
	// Retrieve value — requires type assertion.
	if reqID, ok := ctx3.Value(requestIDKey).(string); ok {
		fmt.Println("request ID:", reqID)
	}
}

// ============================================================
// SECTION 8: ATOMIC OPERATIONS
// ============================================================

// AtomicCounter: lock-free counter using CPU atomic instructions.
// Faster than mutex for simple counters — no kernel involvement.
// atomic operations work on int32, int64, uint32, uint64, uintptr, Pointer.
type AtomicCounter struct {
	value int64 // must be 64-bit aligned for atomic ops on 32-bit systems
}

func (c *AtomicCounter) Increment() {
	// atomic.AddInt64: atomically adds delta and returns new value.
	// CPU-level instruction (LOCK XADD on x86) — no mutex needed.
	atomic.AddInt64(&c.value, 1)
}

func (c *AtomicCounter) Load() int64 {
	// atomic.LoadInt64: atomically reads the value.
	// Plain c.value read without Load would be a data race.
	return atomic.LoadInt64(&c.value)
}

func (c *AtomicCounter) CompareAndSwap(old, new int64) bool {
	// CAS: only updates if value == old. Returns true on success.
	// Foundation of lock-free algorithms (queues, stacks, etc.).
	return atomic.CompareAndSwapInt64(&c.value, old, new)
}

// ============================================================
// SECTION 9: WORKER POOL (FULL EXAMPLE)
// ============================================================

// FetchResult: result from fetching a URL.
type FetchResult struct {
	URL        string
	StatusCode int
	Error      error
	Duration   time.Duration
}

// fetchURL: simulates an HTTP GET request (real implementation below).
func fetchURL(ctx context.Context, url string) FetchResult {
	start := time.Now()

	// Create a request with context so HTTP client respects cancellation.
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return FetchResult{URL: url, Error: err, Duration: time.Since(start)}
	}

	// Use a client with explicit timeout (don't use http.DefaultClient in production).
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return FetchResult{URL: url, Error: err, Duration: time.Since(start)}
	}
	defer resp.Body.Close() // always close body to avoid connection leak

	return FetchResult{
		URL:        url,
		StatusCode: resp.StatusCode,
		Duration:   time.Since(start),
	}
}

// WorkerPool: launches numWorkers goroutines, each reading from jobs channel.
// Returns a results channel. Closes results when all workers are done.
// This is the canonical Go worker pool pattern.
func WorkerPool(
	ctx context.Context,
	numWorkers int,
	urls []string,
) <-chan FetchResult {
	// Buffered results channel — workers can write without blocking.
	// Buffer size = number of jobs so workers are never blocked writing results.
	results := make(chan FetchResult, len(urls))

	// jobs channel: unbuffered — each send blocks until a worker reads it.
	// This provides natural backpressure: producer only sends what workers can absorb.
	jobs := make(chan string)

	var wg sync.WaitGroup

	// Launch worker goroutines BEFORE sending jobs (avoid deadlock on unbuffered channel).
	for i := 0; i < numWorkers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			// Range over jobs: processes until channel is closed.
			for url := range jobs {
				select {
				case <-ctx.Done():
					// Context cancelled — stop processing new jobs.
					// Drain remaining jobs from channel to unblock sender.
					return
				default:
					// fetch is a blocking operation — it respects ctx internally.
					result := fetchURL(ctx, url)
					results <- result
				}
			}
		}()
	}

	// Sender goroutine: feeds jobs, then closes jobs channel.
	// Closing jobs causes all workers' range loops to exit.
	go func() {
		defer close(jobs) // MUST close to signal workers when done
		for _, url := range urls {
			select {
			case jobs <- url: // send job to any available worker
			case <-ctx.Done():
				return // context cancelled — stop sending jobs
			}
		}
	}()

	// Cleanup goroutine: waits for all workers, then closes results.
	// This is in its own goroutine so WorkerPool returns immediately.
	go func() {
		wg.Wait()      // blocks until all workers call wg.Done()
		close(results) // signal: no more results will be written
	}()

	return results // caller ranges over this channel
}

// ============================================================
// SECTION 10: MAIN — DEMO
// ============================================================

func main() {
	fmt.Println("=== goroutines ===")
	demonstrateGoroutines()

	fmt.Println("\n=== channels ===")
	demonstrateChannels()

	fmt.Println("\n=== select ===")
	demonstrateSelect()

	fmt.Println("\n=== waitgroup ===")
	demonstrateWaitGroup()

	fmt.Println("\n=== mutex ===")
	counter := &SafeCounter{}
	var wg sync.WaitGroup
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			counter.Increment()
		}()
	}
	wg.Wait()
	fmt.Println("final count:", counter.Value()) // always 100

	fmt.Println("\n=== sync.Once ===")
	for i := 0; i < 3; i++ {
		go func() { fmt.Println("DB:", GetDB().dsn) }()
	}
	time.Sleep(10 * time.Millisecond) // let goroutines print

	fmt.Println("\n=== context ===")
	demonstrateContext()

	fmt.Println("\n=== atomic ===")
	ac := &AtomicCounter{}
	var wg2 sync.WaitGroup
	for i := 0; i < 1000; i++ {
		wg2.Add(1)
		go func() {
			defer wg2.Done()
			ac.Increment()
		}()
	}
	wg2.Wait()
	fmt.Println("atomic counter:", ac.Load()) // always 1000

	fmt.Println("\n=== worker pool ===")
	// Use a short timeout so demo completes quickly.
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	// Sample URLs — in real code these would be real endpoints.
	urls := []string{
		"https://httpbin.org/status/200",
		"https://httpbin.org/status/404",
		"https://httpbin.org/delay/1",
	}

	// 3 workers processing 3 URLs with 3s timeout.
	results := WorkerPool(ctx, 3, urls)

	// Range over results channel — exits when results is closed.
	for r := range results {
		if r.Error != nil {
			fmt.Printf("FAIL %s: %v\n", r.URL, r.Error)
		} else {
			fmt.Printf("OK   %s → %d (%v)\n", r.URL, r.StatusCode, r.Duration.Round(time.Millisecond))
		}
	}
}
