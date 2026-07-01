// ============================================================
// L01: Ownership and Borrowing
// ============================================================
// WHAT: Rust's compile-time memory management system — ownership,
//       borrowing, lifetimes, and slices — replacing the need for
//       a garbage collector or manual free().
// WHY:  Enables memory safety (no dangling pointers, no double-free,
//       no use-after-free) and thread safety (no data races) with
//       zero runtime overhead. The compiler enforces all rules.
// LEVEL: Foundation
// ============================================================
/*
CONCEPT OVERVIEW:
  Every value in Rust has exactly one owner. When the owner goes out of
  scope, the value is dropped (memory freed). Ownership can be moved to
  a new variable, at which point the old variable is invalid. For cheap
  stack types (integers, bool, char), Rust copies instead of moves.

  Borrowing lets you use a value without taking ownership: &T gives a
  shared (read-only) reference, &mut T gives an exclusive mutable one.
  The compiler enforces: at any point in time you may have EITHER any
  number of shared references OR exactly one mutable reference — never
  both. This rule, enforced at compile time, eliminates entire classes
  of bugs including iterator invalidation and data races.

  Lifetimes are the compiler's way of tracking how long a reference is
  valid. Most lifetimes are inferred; explicit annotations are required
  when the compiler cannot figure out the relationship on its own.

PRODUCTION USE CASE:
  Rust is used by AWS (Firecracker VMM), Meta (Mercurial rewrite, Hack
  type checker), Microsoft (Windows kernel components), Cloudflare
  (their proxy stack), and is now accepted in the Linux kernel. Common
  production uses: high-performance backend services (Axum framework),
  CLI tools (ripgrep searches 10x faster than grep), WebAssembly
  modules, and game engines (Bevy). All of these benefit from
  predictable latency — no GC pauses — and memory safety without paying
  a runtime cost.

COMMON MISTAKES:
  1. Trying to use a value after moving it — compiler error: "value used
     here after move". Solution: clone if you need both copies, or
     restructure to use borrows.
  2. Holding a &mut reference and then trying to read elsewhere in the
     same scope. Solution: end the mutable borrow first (let it go out
     of scope or use a block).
  3. Returning a reference to a local variable — compiler error: "returns
     a reference to data owned by the current function". Solution: return
     the owned value instead.
  4. Confusing &String with &str. Prefer &str in function parameters: it
     accepts both &String and &str (the former auto-derefs to the latter).
  5. Overusing clone() to silence borrow checker errors. This is correct
     sometimes, but is often a sign that ownership structure needs rework.
*/

// ---------------------------------------------------------------------------
// Section 1: Why Rust — no GC, no manual free, no crashes
// ---------------------------------------------------------------------------

fn section_1_why_rust() {
    // In C you would malloc/free manually — forget free() → memory leak,
    // free() twice → undefined behaviour, use after free → security hole.
    // In Java/Go a GC collects garbage but introduces unpredictable pauses.
    // Rust does neither: the compiler inserts the equivalent of free() at
    // the exact closing brace where the owner goes out of scope.

    {
        // `s` is a heap-allocated, growable String owned by this block.
        let s = String::from("hello, world");
        println!("inside block: {}", s);
        // At this brace Rust calls drop(s) — equivalent to free(). No GC needed.
    }
    // `s` is no longer accessible here; the compiler would error if you tried.
    println!("block ended — s has been freed automatically");
}

// ---------------------------------------------------------------------------
// Section 2: Move semantics — one owner at a time
// ---------------------------------------------------------------------------

fn section_2_move_semantics() {
    let s1 = String::from("ownership");

    // This is a MOVE, not a copy. s1 no longer owns the data.
    // Rust invalidates s1 so the same heap memory cannot be freed twice.
    let s2 = s1; // s1 → moved into s2

    // println!("{}", s1); // ← compile error: "value borrowed here after move"
    println!("s2 now owns the string: {}", s2);

    // To keep both variables alive you must explicitly clone (deep copy).
    let s3 = String::from("clone me");
    let s4 = s3.clone(); // heap data is duplicated — intentional and visible
    println!("s3: {}, s4: {} — both valid after clone", s3, s4);
}

// ---------------------------------------------------------------------------
// Section 3: Copy types — stack values are always copied, never moved
// ---------------------------------------------------------------------------

fn section_3_copy_types() {
    // Types that implement the Copy trait are bitwise-copied on assignment.
    // This is safe because they live entirely on the stack (fixed size,
    // no heap allocation to double-free).
    let x: i32 = 42;
    let y = x; // copy — x is still valid
    println!("x={}, y={} — both valid (Copy type)", x, y);

    // Types that implement Copy: i8..i128, u8..u128, f32, f64, bool, char,
    // tuples of Copy types, arrays of Copy types.
    let flag = true;
    let also_flag = flag; // copy
    println!("flag={}, also_flag={}", flag, also_flag);

    // String does NOT implement Copy — it is heap-allocated and moving it
    // is intentionally visible so you know ownership has transferred.
}

// ---------------------------------------------------------------------------
// Section 4: Borrowing — shared (&T) and mutable (&mut T) references
// ---------------------------------------------------------------------------

fn section_4_borrowing() {
    let mut data = vec![1, 2, 3, 4, 5];

    // Shared borrow: multiple readers allowed simultaneously.
    let r1 = &data;
    let r2 = &data; // fine — two shared refs coexist
    println!("shared: r1={:?}, r2={:?}", r1, r2);
    // r1 and r2 are no longer used after this point, so they are dropped here
    // (Non-Lexical Lifetimes: borrow ends at last use, not at closing brace).

    // Mutable borrow: exclusive — no other reference can exist at the same time.
    let r3 = &mut data;
    r3.push(6); // only r3 can touch data while this borrow is live
    println!("after push: {:?}", r3);
    // r3's borrow ends here (last use), so we can read data again below.

    println!("original data mutated in place: {:?}", data);
}

// ---------------------------------------------------------------------------
// Section 5: Borrow checker in action — preventing data races at compile time
// ---------------------------------------------------------------------------

fn section_5_borrow_rules_demo() {
    let mut v = vec![10, 20, 30];

    // The following would be a compile error — uncomment to see:
    // let shared = &v;
    // let exclusive = &mut v; // ERROR: cannot borrow `v` as mutable because
    //                         // it is also borrowed as immutable
    // println!("{:?}", shared);

    // The correct pattern: finish the shared borrow before taking a mutable one.
    {
        let shared = &v;
        println!("reading: {:?}", shared);
    } // shared borrow ends here

    {
        let exclusive = &mut v;
        exclusive.push(40); // safe — no other borrow is alive
    } // mutable borrow ends here

    println!("v after mutation: {:?}", v);
    // This compile-time guarantee means data races are impossible in safe Rust.
}

// ---------------------------------------------------------------------------
// Section 6: Functions and ownership — borrow vs move vs return
// ---------------------------------------------------------------------------

// Takes ownership — caller loses `s` after this call.
fn takes_ownership(s: String) {
    println!("took ownership of: {}", s);
} // s is dropped here

// Borrows immutably — caller keeps its data.
fn borrows_ref(s: &str) -> usize {
    // &str is a string slice — a read-only view into any string data.
    // Prefer &str over &String in parameters: works with both.
    s.len() // returns length; caller still owns the original string
}

// Borrows mutably — caller's data is modified in place.
fn append_exclamation(s: &mut String) {
    s.push_str("!"); // modifies through the exclusive mutable reference
}

fn section_6_functions() {
    let owned = String::from("hello");
    takes_ownership(owned); // `owned` moved into function, no longer valid here

    let greeting = String::from("world");
    let len = borrows_ref(&greeting); // pass a shared borrow — greeting lives on
    println!("'{}' has {} chars", greeting, len); // greeting still valid

    let mut message = String::from("Rust");
    append_exclamation(&mut message); // exclusive borrow for mutation
    println!("mutated: {}", message); // message still owned here
}

// ---------------------------------------------------------------------------
// Section 7: Lifetimes — references must not outlive the data they point to
// ---------------------------------------------------------------------------

// Without a lifetime annotation the compiler cannot tell whether the returned
// reference comes from `x` or `y`, and therefore cannot verify safety.
// The annotation `'a` says: "the returned reference lives at least as long as
// the shorter of x and y's lifetimes."
fn longest<'a>(x: &'a str, y: &'a str) -> &'a str {
    // 'a is a lifetime parameter — it is erased at compile time (zero cost).
    if x.len() >= y.len() {
        x // returning a borrow of x, which lives for 'a
    } else {
        y // returning a borrow of y, which also lives for 'a
    }
}

fn section_7_lifetimes() {
    let s1 = String::from("long string is long");
    let result;
    {
        let s2 = String::from("xyz");
        result = longest(s1.as_str(), s2.as_str());
        // result is valid here because both s1 and s2 are alive.
        println!("longest: {}", result);
    }
    // result cannot be used here — s2 has been dropped, and result might
    // have pointed to it. The compiler rejects any attempt to use result
    // outside this block. Uncomment to see the error:
    // println!("{}", result); // ERROR: `s2` does not live long enough
}

// Struct holding a reference needs a lifetime parameter to tell the compiler
// "this struct cannot outlive the string slice it borrows."
struct ImportantExcerpt<'a> {
    part: &'a str, // 'a ties the struct's lifetime to the borrowed str
}

impl<'a> ImportantExcerpt<'a> {
    // Lifetime elision rules let us omit annotations here:
    // the output reference borrows from &self, so its lifetime matches self.
    fn announce(&self, announcement: &str) -> &str {
        println!("Attention: {}", announcement);
        self.part // returning a borrow of self.part — lives as long as self
    }
}

// ---------------------------------------------------------------------------
// Section 8: Slices — references into contiguous data
// ---------------------------------------------------------------------------

fn section_8_slices() {
    // &str is a string slice — a fat pointer (ptr + length) into UTF-8 data.
    let sentence = String::from("hello world");
    let hello: &str = &sentence[0..5]; // borrow bytes 0..5
    let world: &str = &sentence[6..11]; // borrow bytes 6..11
    println!("{} {}", hello, world);
    // sentence is still valid — we only borrowed parts of it.

    // Array slices work the same way.
    let numbers = [1, 2, 3, 4, 5];
    let middle: &[i32] = &numbers[1..4]; // borrow elements 1, 2, 3
    println!("middle slice: {:?}", middle);

    // Slice in a function: accepts any contiguous integer sequence.
    fn sum_slice(s: &[i32]) -> i32 {
        s.iter().sum() // iterate without taking ownership
    }
    println!("sum of middle: {}", sum_slice(middle));
    println!("sum of all:    {}", sum_slice(&numbers));
}

// ---------------------------------------------------------------------------
// Section 9: String vs &str — the most common confusion in Rust
// ---------------------------------------------------------------------------

fn section_9_string_vs_str() {
    // String: owned, heap-allocated, growable. You can push, append, modify.
    let mut owned: String = String::from("Hello");
    owned.push_str(", Rust");
    println!("owned String: {}", owned);

    // &str: borrowed string slice. Lightweight — just a pointer and length.
    // String literals are &'static str — stored in the binary's read-only data.
    let literal: &str = "I am a string literal"; // lives for the entire program
    println!("str literal: {}", literal);

    // Coercion: &String automatically derefs to &str via Deref trait.
    fn print_message(msg: &str) {
        // Accepts both &str and &String (the latter coerces automatically).
        println!("message: {}", msg);
    }
    print_message(literal);        // &str directly
    print_message(&owned);         // &String coerces to &str
    print_message(&owned[0..5]);   // string slice of owned

    // Rule of thumb:
    //   Parameter type  → &str    (most flexible, accepts both)
    //   Return new data → String  (caller can own and modify it)
    //   Storing in struct with lifetime → &'a str (if borrowing) or String (if owning)
}

// ---------------------------------------------------------------------------
// Section 10: Real-world pattern — text processor with ownership and borrowing
// ---------------------------------------------------------------------------

/// Counts word frequency in a text document.
/// Takes a shared borrow — does not need to own the text.
fn count_words(text: &str) -> std::collections::HashMap<&str, usize> {
    // HashMap maps borrowed string slices (pointing into `text`) to counts.
    // The lifetime of the keys is tied to the lifetime of `text`.
    let mut counts = std::collections::HashMap::new();
    for word in text.split_whitespace() {
        // entry API: insert 0 if absent, then add 1.
        *counts.entry(word).or_insert(0) += 1;
    }
    counts
}

/// Normalises text by trimming and lower-casing, returning a new owned String.
/// Takes a borrow; returns an owned value because it creates new data.
fn normalise(text: &str) -> String {
    text.trim().to_lowercase() // trim borrows, to_lowercase allocates new String
}

/// Extracts the N most frequent words, borrowing from the counts map.
fn top_n_words<'a>(
    counts: &'a std::collections::HashMap<&str, usize>,
    n: usize,
) -> Vec<(&'a str, usize)> {
    // 'a ties the returned slices to the counts map's lifetime.
    let mut pairs: Vec<(&str, usize)> = counts.iter().map(|(&w, &c)| (w, c)).collect();
    pairs.sort_by(|a, b| b.1.cmp(&a.1)); // sort descending by count
    pairs.into_iter().take(n).collect()   // take first n items
}

fn section_10_real_world() {
    let raw_text = "  Rust is fast. Rust is safe. Rust is productive. Safe and fast!  ";

    // normalise takes a borrow, produces a new owned String.
    let clean: String = normalise(raw_text);

    // count_words borrows clean; counts keys are slices pointing into clean.
    let counts = count_words(&clean);

    // top_n_words borrows counts; returned slices point into counts' keys.
    let top = top_n_words(&counts, 3);

    println!("Top 3 words:");
    for (word, count) in &top {
        println!("  {:>10} : {}", word, count);
    }
    // clean, counts, and top all drop here in order (top first, then counts,
    // then clean) — the compiler ensures references are always valid.
}

// ---------------------------------------------------------------------------
// Section 11: Demonstrating the drop order and RAII
// ---------------------------------------------------------------------------

struct Resource {
    name: String,
}

impl Drop for Resource {
    // Drop is called automatically when the value goes out of scope.
    // This is how Rust implements RAII (Resource Acquisition Is Initialisation).
    fn drop(&mut self) {
        println!("Dropping resource: {}", self.name);
    }
}

fn section_11_drop_order() {
    // Variables are dropped in reverse order of declaration (stack discipline).
    let _a = Resource { name: String::from("A") };
    let _b = Resource { name: String::from("B") };
    let _c = Resource { name: String::from("C") };
    println!("Resources created: A, B, C");
    // Output order: "Dropping C", "Dropping B", "Dropping A"
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

fn main() {
    println!("=== L01: Ownership and Borrowing ===\n");

    println!("--- 1. Why Rust ---");
    section_1_why_rust();

    println!("\n--- 2. Move Semantics ---");
    section_2_move_semantics();

    println!("\n--- 3. Copy Types ---");
    section_3_copy_types();

    println!("\n--- 4. Borrowing ---");
    section_4_borrowing();

    println!("\n--- 5. Borrow Rules Demo ---");
    section_5_borrow_rules_demo();

    println!("\n--- 6. Functions and Ownership ---");
    section_6_functions();

    println!("\n--- 7. Lifetimes ---");
    section_7_lifetimes();

    let novel = String::from("Call me Ishmael. Some years ago...");
    let first_sentence = novel.split('.').next().expect("Could not find a '.'");
    let excerpt = ImportantExcerpt { part: first_sentence };
    excerpt.announce("new book arrived");

    println!("\n--- 8. Slices ---");
    section_8_slices();

    println!("\n--- 9. String vs &str ---");
    section_9_string_vs_str();

    println!("\n--- 10. Real-World Text Processor ---");
    section_10_real_world();

    println!("\n--- 11. Drop Order (RAII) ---");
    section_11_drop_order();

    println!("\n=== Done ===");
}
