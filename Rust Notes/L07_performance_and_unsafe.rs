// ============================================================
// L07: Performance Optimization and Unsafe Rust
// ============================================================
// WHAT: Techniques for squeezing maximum performance from Rust:
//       zero-cost abstractions, allocation avoidance, SIMD
//       vectorization, and controlled use of unsafe code for
//       low-level operations that the borrow checker cannot verify.
// WHY:  Rust competes with C/C++ for systems-level performance.
//       Understanding where costs come from — heap allocation,
//       cache misses, branch mispredictions, virtual dispatch —
//       lets you write code that is both safe and fast. Unsafe
//       is the escape hatch when the compiler's guarantees are
//       too conservative for a provably correct algorithm.
// LEVEL: Advanced
// ============================================================
/*
CONCEPT OVERVIEW:
    Zero-cost abstractions: Rust's iterators, closures, and generics
    compile to the same machine code as equivalent hand-written loops.
    There is no virtual dispatch unless you explicitly opt into it
    with dyn Trait. Monomorphization generates a specialised copy of
    generic code for each concrete type — no boxing, no indirection.

    Allocation avoidance is the single highest-leverage performance
    technique. Every heap allocation is a potential cache miss and a
    synchronised bump of the allocator's bookkeeping. Use stack arrays
    ([T; N]), slices (&[T]), and string slices (&str) whenever the
    data doesn't need to outlive its scope.

    SIMD (Single Instruction Multiple Data): modern CPUs process 4–16
    values in one instruction. Auto-vectorization handles simple loops;
    for control over which instruction set is used, write explicit
    SIMD with std::arch intrinsics or the `wide` crate.

    unsafe Rust: a block that tells the compiler "I have checked the
    invariants you cannot verify." The programmer takes responsibility
    for: valid pointer alignment and lifetime, no data races on raw
    pointers, correct FFI ABI, and invariant preservation for unsafe
    traits. Always wrap unsafe in a safe public API — the goal is to
    contain unsafety, not to spread it.

PRODUCTION USE CASE:
    High-performance binary protocol parser (e.g. network packet,
    FIX financial protocol, Protobuf decoder). Uses SIMD to scan
    for delimiter bytes, unsafe buffer slicing for zero-copy field
    extraction, and Criterion benchmarks to validate each change.

COMMON MISTAKES:
    1. Using format!() in hot paths — it allocates a new String every
       call. Use write!() into a pre-allocated buffer instead.
    2. Passing Vec<T> to functions — copies the fat pointer AND
       prevents the function from accepting slices. Use &[T].
    3. Dereferencing a raw pointer outside an unsafe block (compile
       error) or with wrong lifetime assumptions (UB).
    4. Calling mem::transmute to cast between types of different size
       — always use mem::size_of assertions as guards.
    5. Forgetting #[repr(C)] on structs passed through FFI — Rust's
       default layout is unspecified and can reorder fields.
*/

#![allow(dead_code)]

use std::hint::black_box; // Prevents the compiler from optimising away benchmark work.
use std::mem;

// ---------------------------------------------------------------------------
// SECTION 1: Zero-cost abstractions — iterators vs loops
// ---------------------------------------------------------------------------

// This iterator chain compiles to EXACTLY the same assembly as a hand-written loop.
// No heap allocations, no virtual calls — pure stack operations.
fn sum_squares_iter(data: &[f64]) -> f64 {
    data.iter()
        .filter(|&&x| x > 0.0)   // predicate inlined
        .map(|&x| x * x)          // transformation inlined
        .sum()                     // single-pass accumulation
}

// The hand-written equivalent — same generated code:
fn sum_squares_loop(data: &[f64]) -> f64 {
    let mut total = 0.0f64;
    for &x in data {
        if x > 0.0 {
            total += x * x;
        }
    }
    total
}

// ---------------------------------------------------------------------------
// SECTION 2: Avoiding allocations
// ---------------------------------------------------------------------------

// BAD: allocates a new String on every call.
fn format_bad(prefix: &str, value: u64) -> String {
    format!("{prefix}:{value}")        // heap allocation
}

// GOOD: caller provides the buffer; no allocation occurs.
fn format_good(buf: &mut String, prefix: &str, value: u64) {
    use std::fmt::Write;
    buf.clear();
    write!(buf, "{prefix}:{value}").unwrap(); // writes into existing allocation
}

// Stack-allocated buffer for small strings — stays entirely on the stack.
fn format_stack() {
    let mut buf = [0u8; 64];              // stack array — zero cost
    let msg     = format_into(&mut buf, b"evt:", 42u64);
    println!("{}", std::str::from_utf8(msg).unwrap());
}

// Write into a stack byte array; return the filled slice.
fn format_into<'a>(buf: &'a mut [u8], prefix: &[u8], value: u64) -> &'a [u8] {
    let plen = prefix.len().min(buf.len());
    buf[..plen].copy_from_slice(&prefix[..plen]);
    // Simple u64 → ASCII decimal into remaining bytes.
    let mut n    = value;
    let mut end  = plen;
    if n == 0 {
        buf[end] = b'0';
        end += 1;
    } else {
        let start = end;
        while n > 0 && end < buf.len() {
            buf[end] = b'0' + (n % 10) as u8;
            n /= 10;
            end += 1;
        }
        buf[start..end].reverse(); // digits were written backwards
    }
    &buf[..end]
}

// &str vs String: prefer &str in function signatures — works with both
// String and &str without allocating.
fn count_chars(s: &str) -> usize { s.chars().count() }
// DO NOT write: fn count_chars(s: String) — forces a move, prevents &str.

// &[T] vs Vec<T>: same principle. Accept the slice, caller owns the Vec.
fn max_value(data: &[i32]) -> Option<i32> { data.iter().copied().max() }

// ---------------------------------------------------------------------------
// SECTION 3: String pre-allocation
// ---------------------------------------------------------------------------

fn build_csv_row(fields: &[&str]) -> String {
    // Estimate capacity upfront to avoid repeated reallocation.
    let capacity: usize = fields.iter().map(|f| f.len() + 1).sum();
    let mut s = String::with_capacity(capacity);
    for (i, field) in fields.iter().enumerate() {
        if i > 0 { s.push(','); }
        s.push_str(field);
    }
    s
}

// ---------------------------------------------------------------------------
// SECTION 4: SIMD — explicit vectorisation
// ---------------------------------------------------------------------------

// Count bytes equal to a target using x86_64 AVX2 (32-byte vectors).
// Falls back to scalar on other platforms.
fn count_byte_scalar(haystack: &[u8], needle: u8) -> usize {
    // Auto-vectorised by LLVM with -C target-cpu=native; explicit for clarity.
    haystack.iter().filter(|&&b| b == needle).count()
}

// Using portable SIMD (nightly / std::simd preview).
// On stable, use the `wide` crate for the same effect.
#[cfg(target_arch = "x86_64")]
unsafe fn count_byte_avx2(haystack: &[u8], needle: u8) -> usize {
    use std::arch::x86_64::*;

    // Load needle into all 32 lanes of a 256-bit register.
    let needle_vec = _mm256_set1_epi8(needle as i8);
    let mut count  = 0usize;
    let mut i      = 0usize;

    // Process 32 bytes per iteration.
    while i + 32 <= haystack.len() {
        let chunk = _mm256_loadu_si256(
            haystack[i..].as_ptr() as *const __m256i
        );
        // Compare each byte; matching lanes get 0xFF, others 0x00.
        let cmp   = _mm256_cmpeq_epi8(chunk, needle_vec);
        // Extract a 32-bit bitmask; popcount counts the matches.
        let mask  = _mm256_movemask_epi8(cmp) as u32;
        count    += mask.count_ones() as usize;
        i        += 32;
    }

    // Scalar tail for the remaining < 32 bytes.
    count += haystack[i..].iter().filter(|&&b| b == needle).count();
    count
}

// Safe wrapper: dispatch to SIMD if available, scalar otherwise.
pub fn count_byte(haystack: &[u8], needle: u8) -> usize {
    #[cfg(target_arch = "x86_64")]
    if is_x86_feature_detected!("avx2") {
        // Safety: we checked the feature flag; haystack is a valid slice.
        return unsafe { count_byte_avx2(haystack, needle) };
    }
    count_byte_scalar(haystack, needle)
}

// ---------------------------------------------------------------------------
// SECTION 5: unsafe Rust — raw pointers and manual memory
// ---------------------------------------------------------------------------

// Raw pointer types: *const T (immutable), *mut T (mutable).
// They have NO lifetime, NO borrow-checker tracking, NO null safety.
// Dereferencing them is UB if the pointer is invalid, unaligned, or dangling.

fn raw_pointer_demo() {
    let mut value: u32 = 42;

    // Taking raw pointer from a reference is always safe.
    let ptr: *mut u32 = &mut value as *mut u32;

    // Dereferencing is unsafe — the programmer guarantees ptr is valid.
    unsafe {
        *ptr += 1;                     // write through raw pointer
        println!("value via ptr: {}", *ptr);
    }

    // ptr::read / ptr::write: copy semantics without borrow rules.
    let mut dst: u32 = 0;
    unsafe {
        std::ptr::write(&mut dst, std::ptr::read(ptr));
    }
    assert_eq!(dst, 43);
}

// ---------------------------------------------------------------------------
// SECTION 6: Safe public API wrapping unsafe internals (Vec pattern)
// ---------------------------------------------------------------------------

// A fixed-capacity byte buffer backed by a stack array.
// The public API is entirely safe; unsafe is contained inside.
pub struct StackBuffer<const N: usize> {
    data: [u8; N],
    len:  usize,
}

impl<const N: usize> StackBuffer<N> {
    pub fn new() -> Self {
        // Safety: [u8; N] is valid for any byte pattern, so uninit is fine
        // BUT we use zeroed for simplicity and to avoid MaybeUninit complexity.
        StackBuffer { data: [0u8; N], len: 0 }
    }

    pub fn push_slice(&mut self, src: &[u8]) -> bool {
        let new_len = self.len + src.len();
        if new_len > N { return false; } // would overflow — reject

        // Safety: dst is within bounds (checked above); src is a valid slice;
        // regions do not overlap (src is external, dst is self.data).
        unsafe {
            std::ptr::copy_nonoverlapping(
                src.as_ptr(),
                self.data.as_mut_ptr().add(self.len),
                src.len(),
            );
        }
        self.len = new_len;
        true
    }

    // Returns a slice of the filled portion — no copy, zero allocation.
    pub fn as_slice(&self) -> &[u8] {
        // Safety: self.len <= N, data is valid, slice is immutably borrowed.
        unsafe { std::slice::from_raw_parts(self.data.as_ptr(), self.len) }
    }

    pub fn len(&self) -> usize { self.len }
    pub fn is_empty(&self) -> bool { self.len == 0 }
}

// ---------------------------------------------------------------------------
// SECTION 7: Memory layout — repr(C), repr(transparent)
// ---------------------------------------------------------------------------

// repr(C): fields laid out in declaration order with C-compatible padding.
// Required for structs passed to/from C via FFI.
#[repr(C)]
pub struct PacketHeader {
    pub magic:   u32,   // offset 0
    pub version: u8,    // offset 4
    // 3 bytes padding inserted by compiler to align next field
    pub length:  u32,   // offset 8
}

// repr(transparent): single-field newtype; identical layout to the inner type.
// Allows safe transmutation between the newtype and its inner type in FFI.
#[repr(transparent)]
pub struct UserId(pub u64);

// repr(packed): remove padding — saves bytes but may cause unaligned accesses.
// Use only when the wire format demands it; unaligned access is UB on some archs.
#[repr(C, packed)]
pub struct PackedRecord {
    pub tag:   u8,
    pub value: u32,  // unaligned — access only via ptr::read_unaligned
}

// Safe read of an unaligned field.
pub fn read_packed_value(r: &PackedRecord) -> u32 {
    // Direct field access on packed struct is UB on non-x86 CPUs.
    // ptr::read_unaligned handles any alignment safely.
    unsafe { std::ptr::read_unaligned(&r.value as *const u32) }
}

// ---------------------------------------------------------------------------
// SECTION 8: FFI — calling C from Rust
// ---------------------------------------------------------------------------

// Declare C functions: extern "C" uses the C calling convention.
// These are link-time symbols; the linker finds them in libc or a native lib.
extern "C" {
    fn strlen(s: *const std::ffi::c_char) -> usize;
    fn memcpy(dst: *mut std::ffi::c_void, src: *const std::ffi::c_void, n: usize)
        -> *mut std::ffi::c_void;
}

// Rust function exported to C: #[no_mangle] keeps the symbol name exact.
// extern "C" uses the C calling convention.
#[no_mangle]
pub extern "C" fn rust_add(a: i32, b: i32) -> i32 {
    a + b  // safe Rust in the body
}

// Safe wrapper around the unsafe C strlen call.
pub fn c_strlen(s: &std::ffi::CStr) -> usize {
    // Safety: CStr guarantees null-terminated UTF-8(?)-ish bytes.
    unsafe { strlen(s.as_ptr()) }
}

// ---------------------------------------------------------------------------
// SECTION 9: High-performance binary parser (production example)
// ---------------------------------------------------------------------------

// Parse a sequence of length-prefixed frames: [u32 len][len bytes payload]
// Uses unsafe slice operations for zero-copy field extraction.
#[derive(Debug, PartialEq)]
pub struct Frame<'a> {
    pub payload: &'a [u8],
}

pub struct FrameParser<'a> {
    buf: &'a [u8],
    pos: usize,
}

impl<'a> FrameParser<'a> {
    pub fn new(buf: &'a [u8]) -> Self { FrameParser { buf, pos: 0 } }

    pub fn next_frame(&mut self) -> Option<Frame<'a>> {
        // Need at least 4 bytes for the length prefix.
        if self.pos + 4 > self.buf.len() { return None; }

        // Read u32 length from potentially unaligned position.
        // Safety: pos + 4 <= buf.len() checked above; buf is valid memory.
        let len = unsafe {
            std::ptr::read_unaligned(
                self.buf.as_ptr().add(self.pos) as *const u32
            )
        } as usize;

        self.pos += 4;

        if self.pos + len > self.buf.len() { return None; }

        // Zero-copy: return a slice of the original buffer, no allocation.
        // Safety: pos + len <= buf.len(); lifetime is tied to 'a (the buffer).
        let payload = unsafe {
            std::slice::from_raw_parts(self.buf.as_ptr().add(self.pos), len)
        };

        self.pos += len;
        Some(Frame { payload })
    }
}

// ---------------------------------------------------------------------------
// SECTION 10: Criterion benchmark structure
// ---------------------------------------------------------------------------

// In benches/parser_bench.rs (separate file, not inline here):
//
//   use criterion::{black_box, criterion_group, criterion_main, Criterion};
//
//   fn bench_count_byte(c: &mut Criterion) {
//       let data: Vec<u8> = (0..=255u8).cycle().take(65_536).collect();
//       c.bench_function("count_byte_scalar", |b| {
//           b.iter(|| count_byte_scalar(black_box(&data), black_box(b'\n')))
//       });
//       c.bench_function("count_byte_simd", |b| {
//           b.iter(|| count_byte(black_box(&data), black_box(b'\n')))
//       });
//   }
//
//   criterion_group!(benches, bench_count_byte);
//   criterion_main!(benches);
//
// Run: cargo criterion
// Output: HTML flame chart in target/criterion/

fn benchmark_usage_demo() {
    // black_box prevents the compiler from constant-folding away the work.
    // Use it around inputs AND outputs in micro-benchmarks.
    let data = vec![1u8; 1024];
    let _result = black_box(count_byte(black_box(&data), black_box(1u8)));
}

// ---------------------------------------------------------------------------
// SECTION 11: Profiling workflow
// ---------------------------------------------------------------------------

// 1. Build with debug symbols in release: add to Cargo.toml [profile.release]
//       debug = true
// 2. cargo install flamegraph
// 3. cargo flamegraph --bin mybin -- args
//    → produces flamegraph.svg; open in browser
//    → wide towers = hot functions; look for unexpected allocations

// To check allocations without a profiler:
//   RUSTFLAGS="-C target-cpu=native" cargo build --release
//   valgrind --tool=massif ./target/release/mybin
//   ms_print massif.out.* | head -50

// ---------------------------------------------------------------------------
// Main & tests
// ---------------------------------------------------------------------------

fn main() {
    // Demonstrate zero-cost iterators.
    let data: Vec<f64> = (-5..=5).map(|x| x as f64).collect();
    assert_eq!(sum_squares_iter(&data), sum_squares_loop(&data));

    // Stack buffer: no heap allocation.
    let mut buf = StackBuffer::<128>::new();
    assert!(buf.push_slice(b"hello, world"));
    println!("StackBuffer: {:?}", std::str::from_utf8(buf.as_slice()));

    // Frame parser.
    let mut wire = Vec::new();
    let payload  = b"HELLO";
    wire.extend_from_slice(&(payload.len() as u32).to_ne_bytes());
    wire.extend_from_slice(payload);
    let mut parser = FrameParser::new(&wire);
    let frame = parser.next_frame().unwrap();
    assert_eq!(frame.payload, b"HELLO");
    println!("Parsed frame: {:?}", frame);

    raw_pointer_demo();
    benchmark_usage_demo();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn iter_equals_loop() {
        let data: Vec<f64> = (-10..=10).map(|x| x as f64).collect();
        let eps = 1e-10;
        assert!((sum_squares_iter(&data) - sum_squares_loop(&data)).abs() < eps);
    }

    #[test]
    fn stack_buffer_overflow_returns_false() {
        let mut buf = StackBuffer::<4>::new();
        assert!(buf.push_slice(b"abcd"));
        assert!(!buf.push_slice(b"e")); // would overflow
        assert_eq!(buf.as_slice(), b"abcd");
    }

    #[test]
    fn frame_parser_roundtrip() {
        let payloads: &[&[u8]] = &[b"frame1", b"frame2", b"x"];
        let mut wire = Vec::new();
        for p in payloads {
            wire.extend_from_slice(&(p.len() as u32).to_ne_bytes());
            wire.extend_from_slice(p);
        }
        let mut parser = FrameParser::new(&wire);
        for expected in payloads {
            let frame = parser.next_frame().unwrap();
            assert_eq!(frame.payload, *expected);
        }
        assert!(parser.next_frame().is_none());
    }

    #[test]
    fn count_byte_matches_scalar() {
        let data: Vec<u8> = (0..=255u8).cycle().take(10_000).collect();
        let scalar = count_byte_scalar(&data, b'A');
        let simd   = count_byte(&data, b'A');
        assert_eq!(scalar, simd);
    }

    #[test]
    fn packed_record_read() {
        let r = PackedRecord { tag: 7, value: 0xDEAD_BEEF };
        assert_eq!(read_packed_value(&r), 0xDEAD_BEEF);
    }

    #[test]
    fn mem_size_sanity() {
        // repr(transparent): UserId must be the same size as u64.
        assert_eq!(mem::size_of::<UserId>(), mem::size_of::<u64>());
    }
}
