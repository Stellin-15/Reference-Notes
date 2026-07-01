// ============================================================
// L01: Go Fundamentals
// ============================================================
// WHAT: Core Go language concepts — types, variables, strings,
//       slices, maps, structs, pointers, functions, errors,
//       and interfaces. The building blocks used in every
//       Go program regardless of domain.
// WHY:  Go trades expressiveness for simplicity and reliability.
//       25 keywords (vs Java's 50+) means less to learn, less
//       to misuse. Compiled to native binary = fast startup,
//       great for containers. GC = no manual memory management.
//       Understanding these fundamentals is required before
//       touching concurrency, HTTP, or databases.
// LEVEL: Foundation
// ============================================================
/*
CONCEPT OVERVIEW:
    Go is an opinionated language: one way to do most things.
    Variables are declared explicitly. Errors are values, not
    exceptions. Interfaces are implicit. Concurrency is built in.
    The compiler enforces unused imports and unused variables —
    intentional friction that keeps codebases clean.

PRODUCTION USE CASE:
    User management service — User struct with CRUD operations,
    UserStore interface backed by an in-memory implementation.
    This exact pattern (interface + in-memory impl) is used for
    dependency injection and testing at every Go shop.

COMMON MISTAKES:
    1. Using += to concatenate strings in a loop — O(n^2). Use
       strings.Builder instead.
    2. Ignoring the second return value from map lookup — you get
       the zero value silently when the key is missing.
    3. Passing a large struct by value everywhere — copies the
       whole thing. Use a pointer for anything bigger than ~3 fields.
    4. Using panic() for expected error conditions. Panic is for
       programmer bugs (nil pointer, index out of range). Business
       logic errors must return error values.
    5. Shadowing err with := inside an if block, then checking the
       outer err which is still nil.
*/

// Every file must declare its package. Files in the same directory
// must share the same package name. "main" is special — it produces
// an executable. Any other name produces a library.
package main

import (
	// fmt: formatted I/O — Printf, Println, Sprintf, Errorf.
	"fmt"
	// strings: everything you need for string manipulation.
	"strings"
	// errors: errors.New, errors.Is, errors.As for error wrapping.
	"errors"
	// strconv: string ↔ numeric conversion (Atoi, Itoa, ParseFloat).
	"strconv"
)

// ============================================================
// SECTION 1: WHY GO
// ============================================================
// Go was created at Google in 2009 by Rob Pike, Ken Thompson,
// and Robert Griesemer to solve real pain points:
//   - C++ compile times were destroying developer productivity.
//   - Python was too slow for systems work.
//   - Java's complexity was causing bugs and cognitive overhead.
//
// Go's design goals:
//   COMPILED    → Native binary, no VM, fast startup (great for containers)
//   GC          → No malloc/free, no use-after-free, no buffer overflows
//   CONCURRENCY → Goroutines + channels are first-class language features
//   SIMPLICITY  → 25 keywords. One way to format code (gofmt).
//                 No generics debates until 1.18 (and even now, limited).
//   STD LIB     → HTTP server, JSON, crypto, SQL interfaces — batteries included
//
// Who uses Go in production:
//   Google        → internal services, YouTube, dl.google.com
//   Docker        → the entire container runtime
//   Kubernetes    → the entire orchestration platform
//   Uber          → routing, dispatch, 2000+ Go services
//   Cloudflare    → DNS resolver (1.1.1.1), Workers runtime
//   Dropbox       → migrated Python services to Go for 10-25x perf gains
//   Twitch        → video delivery pipeline
//   Stripe        → payment processing services

// ============================================================
// SECTION 2: TYPES
// ============================================================

// Go has no implicit type conversion. You must convert explicitly.
// This prevents entire classes of bugs (signed/unsigned confusion, etc.)
func demonstrateTypes() {
	// Integer types — pick the right size for your domain.
	var a int = 42          // platform-dependent (64-bit on 64-bit OS)
	var b int64 = 9_000_000 // explicit 64-bit; underscore is visual separator
	var c int32 = 100
	var d uint = 255 // unsigned — cannot be negative

	// Explicit conversion required — the compiler will NOT do this for you.
	// Without int64(c), this line would not compile: "cannot use c (int32) as int64"
	_ = b + int64(c)
	_ = a
	_ = d

	// Floating point
	var pi float64 = 3.14159265358979
	var approx float32 = 3.14 // less precision, less memory

	// bool: only true/false. No implicit int↔bool like in C.
	var isReady bool = true

	// string: immutable sequence of bytes, UTF-8 encoded.
	var greeting string = "Hello, 世界"

	// byte = uint8 (alias). Used for raw binary data.
	var b2 byte = 65 // ASCII 'A'

	// rune = int32 (alias). Represents a Unicode code point.
	// Use rune when you care about characters, not bytes.
	var r rune = '世' // Unicode code point U+4E16

	fmt.Println(pi, approx, isReady, greeting, b2, r)
}

// ============================================================
// SECTION 3: VARIABLES AND CONSTANTS
// ============================================================

// Package-level constants — evaluated at compile time.
const Pi = 3.14159265358979

// iota: auto-incrementing integer within a const block.
// Each const block resets iota to 0. Classic use: enums.
type Status int

const (
	StatusPending  Status = iota // 0
	StatusActive                 // 1 — iota increments automatically
	StatusInactive               // 2
	StatusDeleted                // 3
)

// String method on Status — satisfies the fmt.Stringer interface.
// Any type with a String() string method will print human-readable.
func (s Status) String() string {
	switch s {
	case StatusPending:
		return "PENDING"
	case StatusActive:
		return "ACTIVE"
	case StatusInactive:
		return "INACTIVE"
	case StatusDeleted:
		return "DELETED"
	default:
		return "UNKNOWN"
	}
}

func demonstrateVariables() {
	// var declaration: explicit, can be at package or function level.
	var x int = 5

	// Short declaration (:=): infers type, ONLY inside functions.
	// This is the most common form. x := 5 is identical to var x int = 5.
	y := 10

	// Multiple assignment — Go idiom for swap (no temp variable needed).
	x, y = y, x

	// Blank identifier (_): explicitly discard a value.
	// The compiler rejects unused variables, so use _ to opt out.
	_ = x
	_ = y

	// Zero values: every type has a zero value. No uninitialized memory.
	var i int     // 0
	var f float64 // 0.0
	var b bool    // false
	var s string  // "" (empty string)
	fmt.Println(i, f, b, s)
}

// ============================================================
// SECTION 4: STRINGS
// ============================================================

func demonstrateStrings() {
	s := "Hello, 世界"

	// len() returns byte count, NOT character (rune) count.
	// "世界" is 3 bytes each in UTF-8, so len = 7 + 6 = 13 total.
	fmt.Println("byte length:", len(s)) // 13, not 9

	// To count characters (runes), convert to []rune or use utf8 package.
	runes := []rune(s)
	fmt.Println("rune length:", len(runes)) // 9

	// Range over string iterates by RUNE, not byte.
	// i is byte offset, ch is rune value.
	for i, ch := range s {
		if i < 3 {
			fmt.Printf("index %d: %c (U+%04X)\n", i, ch, ch)
		}
	}

	// String concatenation with +=: DON'T use in loops.
	// Each += allocates a new string (strings are immutable).
	// For loops, use strings.Builder — single allocation, O(n) total.
	var builder strings.Builder
	words := []string{"Go", "is", "fast"}
	for i, w := range words {
		builder.WriteString(w)
		if i < len(words)-1 {
			builder.WriteByte(' ') // no allocation
		}
	}
	result := builder.String() // one allocation at the end
	fmt.Println(result)

	// strings package — the most commonly used functions.
	fmt.Println(strings.Contains(s, "世界"))           // true
	fmt.Println(strings.HasPrefix(s, "Hello"))        // true
	fmt.Println(strings.HasSuffix(s, "界"))            // true
	fmt.Println(strings.ToLower("HELLO"))              // "hello"
	fmt.Println(strings.TrimSpace("  hello  "))       // "hello"
	parts := strings.Split("a,b,c", ",")              // ["a","b","c"]
	fmt.Println(strings.Join(parts, " | "))            // "a | b | c"
	fmt.Println(strings.ReplaceAll("aabbcc", "b", "")) // "aacc"

	// strconv: converting between strings and numeric types.
	n, err := strconv.Atoi("42") // string → int
	if err != nil {
		fmt.Println("parse error:", err)
		return
	}
	fmt.Println(n + 1)              // 43
	fmt.Println(strconv.Itoa(n))    // "42"
}

// ============================================================
// SECTION 5: ARRAYS AND SLICES
// ============================================================

func demonstrateSlices() {
	// Array: fixed size, value type. Rarely used directly.
	// Copying an array copies ALL elements — expensive for large arrays.
	var arr [5]int   // [0 0 0 0 0]
	arr[0] = 1
	arr2 := arr      // COPY — modifying arr2 does NOT affect arr
	arr2[0] = 99
	fmt.Println(arr[0])  // still 1
	fmt.Println(arr2[0]) // 99

	// Slice: dynamic size, reference type. What you use 99% of the time.
	// A slice is a struct: {pointer, length, capacity}
	s := []int{10, 20, 30, 40, 50}

	// make([]T, len, cap): pre-allocate capacity to avoid re-allocation.
	// Use when you know the approximate final size.
	s2 := make([]int, 0, 100) // len=0, cap=100, no elements yet

	// append: adds element, returns new slice.
	// If len < cap: no allocation. If len == cap: doubles capacity (new backing array).
	s2 = append(s2, 1, 2, 3)

	// Spread operator (...) to append one slice to another.
	s2 = append(s2, s...)

	// Slicing: s[low:high] — shares the backing array.
	// Modifying the sub-slice modifies the original.
	sub := s[1:3] // [20, 30] — shares backing array with s
	sub[0] = 999
	fmt.Println(s[1]) // 999 — original was mutated!

	// copy: copies elements, does NOT share backing array.
	dst := make([]int, len(s))
	n := copy(dst, s) // returns number of elements copied
	dst[0] = 777
	fmt.Println(s[0], n) // s[0] unchanged; n = 5
}

// ============================================================
// SECTION 6: MAPS
// ============================================================

func demonstrateMaps() {
	// map[K]V: hash map. Keys must be comparable (not slices, maps, or funcs).
	// Always initialize with make — a nil map panics on write.
	scores := make(map[string]int)
	scores["Alice"] = 95
	scores["Bob"] = 87

	// Map literal: inline initialization.
	config := map[string]string{
		"host": "localhost",
		"port": "5432",
	}
	_ = config

	// Two-return lookup: ALWAYS use this form.
	// If key is missing, val=0 and ok=false.
	// Single-return form gives 0 silently — a common source of bugs.
	val, ok := scores["Charlie"]
	if !ok {
		fmt.Println("Charlie not found") // safe — we checked
	}
	fmt.Println(val) // 0 (zero value for int)

	// delete: remove a key. Safe to call even if key doesn't exist.
	delete(scores, "Bob")

	// Iterate: order is NOT guaranteed (randomized intentionally).
	for name, score := range scores {
		fmt.Printf("%s: %d\n", name, score)
	}

	// Maps are NOT safe for concurrent use.
	// Multiple goroutines reading is fine. Any writer = data race.
	// Solutions: sync.Mutex around map, or sync.Map for concurrent access.
}

// ============================================================
// SECTION 7: STRUCTS AND POINTERS
// ============================================================

// Struct: value type. Copied on assignment (each field is copied).
// Use pointers to avoid copying and to share/mutate state.
type User struct {
	ID    int64  // exported (capital letter) — visible outside package
	Name  string
	Email string
	Role  Status // embedded custom type
}

// Method with POINTER receiver: can modify the struct.
// If the method is on a value receiver, it gets a copy — changes are lost.
func (u *User) Activate() {
	u.Role = StatusActive // modifies the original User
}

// Method with VALUE receiver: reads but does not modify.
// Go will auto-dereference: if you have *User, you can call value methods.
func (u User) DisplayName() string {
	return fmt.Sprintf("%s <%s>", u.Name, u.Email)
}

func demonstrateStructs() {
	// Value literal — allocated on stack (usually).
	u1 := User{ID: 1, Name: "Alice", Email: "alice@example.com"}

	// Pointer literal — allocated on heap (usually).
	// &User{} is identical to new(User) followed by field assignment.
	u2 := &User{ID: 2, Name: "Bob", Email: "bob@example.com"}

	// Go auto-dereferences pointers for field access and method calls.
	// u2.Name and (*u2).Name are identical.
	fmt.Println(u2.Name)

	u1.Activate()    // pointer receiver — u1 is modified
	u2.Activate()    // u2 is already a pointer

	fmt.Println(u1.DisplayName())
	fmt.Println(u1.Role) // "ACTIVE"
}

// ============================================================
// SECTION 8: FUNCTIONS AND ERRORS
// ============================================================

// Sentinel error: a package-level var that callers can compare against.
// Convention: ErrXxx. Use errors.Is() for comparison (handles wrapping).
var ErrUserNotFound = errors.New("user not found")
var ErrInvalidInput = errors.New("invalid input")

// Multiple return values: Go's substitute for exceptions.
// The last return value is almost always error.
func parseUserID(s string) (int64, error) {
	if s == "" {
		// Wrap with context using %w. Callers can unwrap with errors.Is/As.
		return 0, fmt.Errorf("parseUserID: %w", ErrInvalidInput)
	}
	n, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		// Wrap the strconv error with our context.
		return 0, fmt.Errorf("parseUserID %q: %w", s, err)
	}
	return n, nil
}

// Named returns: names are used in godoc and can be returned with bare return.
// Useful mainly for clarity in short functions. Don't overuse — bare returns
// in long functions make it hard to see what's returned.
func divide(a, b float64) (result float64, err error) {
	if b == 0 {
		err = fmt.Errorf("divide: division by zero")
		return // bare return — returns named values (result=0, err=set)
	}
	result = a / b
	return // bare return — returns (a/b, nil)
}

// defer: runs at function exit, in LIFO order (last deferred runs first).
// Most common use: cleanup (close file, release lock, recover from panic).
func processWithDefer() {
	fmt.Println("start")
	defer fmt.Println("third")  // runs last
	defer fmt.Println("second") // runs second-to-last
	defer fmt.Println("first")  // runs first (LIFO)
	fmt.Println("end")
	// Output: start, end, first, second, third
}

// ============================================================
// SECTION 9: INTERFACES
// ============================================================

// Interface: a set of method signatures. Implemented IMPLICITLY.
// Any type with these methods satisfies the interface — no "implements".
// This enables loose coupling and easy testing (swap real impl for mock).
type UserStore interface {
	GetByID(id int64) (User, error)
	Create(user User) (User, error)
	Update(user User) (User, error)
	Delete(id int64) error
	List() ([]User, error)
}

// inMemoryStore: concrete implementation of UserStore.
// Unexported (lowercase) — callers use the interface, not this type.
type inMemoryStore struct {
	users  map[int64]User
	nextID int64
}

// NewInMemoryStore: constructor function. Returns the interface, not the
// concrete type. This hides implementation details and makes swapping easy.
func NewInMemoryStore() UserStore {
	return &inMemoryStore{
		users:  make(map[int64]User),
		nextID: 1,
	}
}

func (s *inMemoryStore) GetByID(id int64) (User, error) {
	u, ok := s.users[id]
	if !ok {
		// Wrap ErrUserNotFound so callers can use errors.Is().
		return User{}, fmt.Errorf("GetByID %d: %w", id, ErrUserNotFound)
	}
	return u, nil
}

func (s *inMemoryStore) Create(user User) (User, error) {
	if user.Name == "" || user.Email == "" {
		return User{}, fmt.Errorf("Create: %w", ErrInvalidInput)
	}
	user.ID = s.nextID
	s.nextID++
	user.Role = StatusActive
	s.users[user.ID] = user
	return user, nil
}

func (s *inMemoryStore) Update(user User) (User, error) {
	if _, ok := s.users[user.ID]; !ok {
		return User{}, fmt.Errorf("Update %d: %w", user.ID, ErrUserNotFound)
	}
	s.users[user.ID] = user
	return user, nil
}

func (s *inMemoryStore) Delete(id int64) error {
	if _, ok := s.users[id]; !ok {
		return fmt.Errorf("Delete %d: %w", id, ErrUserNotFound)
	}
	delete(s.users, id)
	return nil
}

func (s *inMemoryStore) List() ([]User, error) {
	result := make([]User, 0, len(s.users)) // pre-allocate exact capacity
	for _, u := range s.users {
		result = append(result, u)
	}
	return result, nil
}

// ============================================================
// SECTION 10: PUTTING IT TOGETHER
// ============================================================

func main() {
	demonstrateTypes()
	demonstrateVariables()
	demonstrateStrings()
	demonstrateSlices()
	demonstrateMaps()
	demonstrateStructs()

	// Error handling: check every error. errors.Is checks the chain.
	id, err := parseUserID("abc")
	if err != nil {
		fmt.Println("parse error:", err) // prints the full wrapped message
	}
	_ = id

	id2, err := parseUserID("42")
	if err != nil {
		fmt.Println("unexpected:", err)
	} else {
		fmt.Println("parsed ID:", id2)
	}

	// errors.Is: checks if ANY error in the wrap chain matches the target.
	_, err = parseUserID("")
	if errors.Is(err, ErrInvalidInput) {
		fmt.Println("got expected invalid input error")
	}

	// Interface usage — depends on UserStore, not inMemoryStore.
	store := NewInMemoryStore()

	alice, err := store.Create(User{Name: "Alice", Email: "alice@example.com"})
	if err != nil {
		fmt.Println("create error:", err)
		return
	}
	fmt.Println("created:", alice.DisplayName(), "status:", alice.Role)

	// Try to fetch a non-existent user.
	_, err = store.GetByID(999)
	if errors.Is(err, ErrUserNotFound) {
		fmt.Println("correctly got not-found error")
	}

	// List all users.
	users, _ := store.List()
	for _, u := range users {
		fmt.Println("-", u.DisplayName())
	}

	processWithDefer()
}
