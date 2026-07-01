// ============================================================
// L02: Structs, Enums, and Traits
// ============================================================
// WHAT: Rust's core data-modelling tools — structs bundle named
//       fields into a record type, enums model "one of several
//       possible shapes" (including data payloads), and traits
//       define shared behaviour across unrelated types.
// WHY:  Together they replace classes, interfaces, and null-safe
//       wrappers from OO languages — without inheritance — giving
//       you expressive, zero-cost abstractions and exhaustive
//       pattern matching that the compiler verifies completely.
// LEVEL: Foundation
// ============================================================
/*
CONCEPT OVERVIEW:
  Structs in Rust are plain data records. You add behaviour through
  impl blocks (methods) rather than putting code inside the type
  definition. This separation keeps data and logic distinct.

  Enums are algebraic data types: each variant can carry different
  data. They are far more powerful than C enums. The two most
  important built-in enums are Option<T> (value or nothing) and
  Result<T, E> (success or failure) — they eliminate null pointer
  crashes and unhandled exceptions by making every case explicit.

  Traits are like interfaces: they declare a set of methods a type
  must implement. They enable polymorphism without inheritance and
  are the foundation of Rust's standard library (Iterator, Display,
  Clone, From, Into, Default, ...).

  Generics let structs, enums, and functions work over many types
  while the compiler generates specialised, monomorphised code for
  each concrete type used — zero runtime overhead.

PRODUCTION USE CASE:
  An order management system (OMS) used in financial trading
  infrastructure. Orders pass through multiple states (Pending →
  Filled → Cancelled), each state holding different data. Traits
  let the reporting layer call display/debug on any order type
  without knowing its concrete variant. Result<T, E> makes every
  failure path explicit and compiler-enforced — critical when
  incorrect order handling can cause financial loss.

COMMON MISTAKES:
  1. Trying to use self after moving it out of a method. Use &self
     for reading and &mut self for mutation; take self only when you
     intentionally consume the struct (builder pattern, etc.).
  2. Forgetting to make a field pub when it needs to be visible
     outside the module. Rust fields are private by default.
  3. Using unwrap() on Option/Result in library code — prefer
     returning the Option/Result to the caller so they can decide.
  4. Implementing Display and Debug manually when #[derive(Debug)]
     suffices for debugging, and using {:?} everywhere instead of
     implementing a clean Display for user-facing output.
  5. Writing trait bounds with concrete types in impl blocks instead
     of using generics, which leads to code duplication.
*/

use std::fmt;

// ---------------------------------------------------------------------------
// Section 1: Basic struct — User record
// ---------------------------------------------------------------------------

// #[derive] asks the compiler to automatically generate trait implementations.
// Debug:     enables {:?} and {:#?} printing.
// Clone:     enables .clone() for deep copies.
// PartialEq: enables == and != comparisons.
#[derive(Debug, Clone, PartialEq)]
struct User {
    id: u64,           // unique identifier
    name: String,      // owned, heap-allocated — user owns their name
    email: String,     // owned — avoids lifetime complexity in stored data
    active: bool,      // account status flag
    login_count: u32,  // tracks how many times user has authenticated
}

impl User {
    // Associated function (no `self`) — acts like a constructor.
    // Returns Self so the type name is not repeated; easier to refactor.
    fn new(id: u64, name: String, email: String) -> Self {
        User {
            id,                // field init shorthand: field: field
            name,
            email,
            active: true,      // new users start active
            login_count: 0,    // no logins yet
        }
    }

    // Immutable method — borrows self read-only; multiple callers can call concurrently.
    fn display_name(&self) -> &str {
        &self.name // return a borrow into self; lifetime tied to self
    }

    // Mutable method — requires exclusive access to self.
    fn deactivate(&mut self) {
        self.active = false; // mutate through the exclusive borrow
        println!("User '{}' has been deactivated.", self.name);
    }

    // Mutable method with a return value — records a login and returns the new count.
    fn record_login(&mut self) -> u32 {
        self.login_count += 1;
        self.login_count
    }

    // Consumes self (ownership transferred in) — used for builder-style finalisation.
    // After calling this, the original `user` variable is invalid.
    fn into_summary(self) -> String {
        format!(
            "User#{} | {} <{}> | active={} | logins={}",
            self.id, self.name, self.email, self.active, self.login_count
        )
    }
}

// Custom Display implementation — controls what appears with {}.
// Different from Debug ({:?}) which is for developers; Display is for end users.
impl fmt::Display for User {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "[User#{}: {}]", self.id, self.name)
    }
}

// ---------------------------------------------------------------------------
// Section 2: Tuple structs and unit structs
// ---------------------------------------------------------------------------

// Tuple struct: fields accessed by position (.0, .1, .2). Useful for
// newtype wrappers that add type-safety without renaming fields.
#[derive(Debug, Clone, Copy, PartialEq)]
struct Color(u8, u8, u8); // RGB components — all Copy, so the struct is Copy

#[derive(Debug, Clone, Copy, PartialEq)]
struct Meters(f64); // newtype wrapper — prevents accidentally mixing units

#[derive(Debug, Clone, Copy, PartialEq)]
struct Kilograms(f64);

// Unit struct: no data. Useful as a zero-sized marker to implement traits on.
struct Marker; // occupies 0 bytes at runtime

fn section_2_tuple_and_unit() {
    let red = Color(255, 0, 0);
    let green = Color(0, 255, 0);
    println!("red: {:?}, green: {:?}", red, green);
    println!("red R component: {}", red.0); // field access by index

    let distance = Meters(1.5);
    let weight = Kilograms(70.0);
    // The type system prevents: let _ = distance.0 + weight.0 — they are different types.
    println!("distance: {:?}, weight: {:?}", distance, weight);

    let _m = Marker; // zero-sized; compiler may optimise it away entirely
}

// ---------------------------------------------------------------------------
// Section 3: Enums — algebraic data types with payloads
// ---------------------------------------------------------------------------

// Each variant can hold completely different data — not possible in C enums.
#[derive(Debug, Clone, PartialEq)]
enum Shape {
    Circle(f64),                         // holds the radius
    Rectangle(f64, f64),                 // holds width and height
    Triangle(f64, f64, f64),             // holds the three sides
    Point,                               // no data — unit variant
}

impl Shape {
    // Pattern matching is exhaustive — the compiler forces you to handle every variant.
    fn area(&self) -> f64 {
        match self {
            Shape::Circle(r) => std::f64::consts::PI * r * r, // πr²
            Shape::Rectangle(w, h) => w * h,                   // base × height
            Shape::Triangle(a, b, c) => {
                // Heron's formula: area = √(s(s-a)(s-b)(s-c)) where s = half-perimeter
                let s = (a + b + c) / 2.0;
                (s * (s - a) * (s - b) * (s - c)).sqrt()
            }
            Shape::Point => 0.0, // a point has no area
        }
    }

    fn perimeter(&self) -> f64 {
        match self {
            Shape::Circle(r) => 2.0 * std::f64::consts::PI * r, // 2πr
            Shape::Rectangle(w, h) => 2.0 * (w + h),
            Shape::Triangle(a, b, c) => a + b + c,
            Shape::Point => 0.0,
        }
    }
}

impl fmt::Display for Shape {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Shape::Circle(r) => write!(f, "Circle(r={})", r),
            Shape::Rectangle(w, h) => write!(f, "Rectangle({}x{})", w, h),
            Shape::Triangle(a, b, c) => write!(f, "Triangle({},{},{})", a, b, c),
            Shape::Point => write!(f, "Point"),
        }
    }
}

// ---------------------------------------------------------------------------
// Section 4: Option<T> — Rust's null-free nullable value
// ---------------------------------------------------------------------------

// Option<T> = Some(T) | None. There is no `null` in safe Rust.
// Every function that might not return a value says so in its type signature.

fn find_user_by_id(users: &[User], id: u64) -> Option<&User> {
    // iter().find returns Option<&User> — either Some(ref to found user) or None.
    users.iter().find(|u| u.id == id)
}

fn section_4_option() {
    let users = vec![
        User::new(1, "Alice".into(), "alice@example.com".into()),
        User::new(2, "Bob".into(), "bob@example.com".into()),
    ];

    // match on Option — explicit handling of both cases.
    match find_user_by_id(&users, 1) {
        Some(user) => println!("Found: {}", user),
        None => println!("User not found"),
    }

    // if let — concise when you only care about the Some case.
    if let Some(user) = find_user_by_id(&users, 99) {
        println!("Found: {}", user);
    } else {
        println!("ID 99 not found (expected)");
    }

    // Combinators — transform Option without unpacking manually.
    let name: Option<String> = find_user_by_id(&users, 2)
        .map(|u| u.name.clone()); // Some("Bob") or None
    println!("mapped name: {:?}", name);

    let display: String = find_user_by_id(&users, 2)
        .map(|u| u.name.clone())
        .unwrap_or_else(|| "anonymous".to_string()); // fallback if None
    println!("display: {}", display);

    // Chaining with and_then (flatMap) — avoids nested Some(Some(...)).
    let login_count: Option<u32> = find_user_by_id(&users, 1)
        .and_then(|u| if u.active { Some(u.login_count) } else { None });
    println!("active user login count: {:?}", login_count);
}

// ---------------------------------------------------------------------------
// Section 5: Result<T, E> — explicit, compiler-enforced error handling
// ---------------------------------------------------------------------------

#[derive(Debug)]
enum OrderError {
    InvalidQuantity(u32),
    InvalidPrice(f64),
    UserNotActive(u64),
}

impl fmt::Display for OrderError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            OrderError::InvalidQuantity(q) => write!(f, "invalid quantity: {}", q),
            OrderError::InvalidPrice(p) => write!(f, "invalid price: {}", p),
            OrderError::UserNotActive(id) => write!(f, "user {} is not active", id),
        }
    }
}

// Result<T, E> = Ok(T) | Err(E). Must handle both cases — the compiler reminds you.
fn validate_order(user: &User, quantity: u32, price: f64) -> Result<String, OrderError> {
    if !user.active {
        return Err(OrderError::UserNotActive(user.id));
    }
    if quantity == 0 {
        return Err(OrderError::InvalidQuantity(quantity));
    }
    if price <= 0.0 {
        return Err(OrderError::InvalidPrice(price));
    }
    // All checks passed — return the success value.
    Ok(format!(
        "Order for {} x {} @ ${:.2} validated",
        user.name, quantity, price
    ))
}

fn section_5_result() {
    let user = User::new(10, "Carol".into(), "carol@example.com".into());

    match validate_order(&user, 100, 42.50) {
        Ok(msg) => println!("Success: {}", msg),
        Err(e) => println!("Error: {}", e),
    }

    match validate_order(&user, 0, 42.50) {
        Ok(msg) => println!("Success: {}", msg),
        Err(e) => println!("Error: {}", e), // prints "invalid quantity: 0"
    }

    // ? operator: in a function returning Result, ? unwraps Ok or early-returns Err.
    fn process(user: &User) -> Result<(), OrderError> {
        let confirmation = validate_order(user, 50, 99.0)?; // propagate on Err
        println!("Processed: {}", confirmation);
        Ok(())
    }
    process(&user).unwrap(); // safe here: user is valid
}

// ---------------------------------------------------------------------------
// Section 6: Traits — shared behaviour across types
// ---------------------------------------------------------------------------

// A trait declares method signatures (and optional default implementations).
trait Priceable {
    // Required method — every implementor must define this.
    fn unit_price(&self) -> f64;

    // Default method — implementors may override, but don't have to.
    fn total_value(&self, quantity: u32) -> f64 {
        self.unit_price() * quantity as f64 // default: price × quantity
    }

    fn is_expensive(&self) -> bool {
        self.unit_price() > 1_000.0 // default threshold
    }
}

#[derive(Debug)]
struct Stock {
    ticker: String,
    price: f64,
}

#[derive(Debug)]
struct Bond {
    issuer: String,
    face_value: f64,
    coupon_rate: f64, // annual interest rate as a decimal (e.g. 0.05 = 5%)
}

impl Priceable for Stock {
    fn unit_price(&self) -> f64 {
        self.price // stock price IS the unit price
    }
}

impl Priceable for Bond {
    fn unit_price(&self) -> f64 {
        self.face_value // bond trades at or near face value
    }

    // Override the default total_value to account for accumulated coupon.
    fn total_value(&self, quantity: u32) -> f64 {
        self.face_value * quantity as f64 * (1.0 + self.coupon_rate)
    }
}

// Trait bound: accepts any type T that implements Priceable.
// Monomorphised at compile time — no virtual dispatch overhead.
fn print_valuation<T: Priceable + fmt::Debug>(instrument: &T, qty: u32) {
    println!(
        "{:?} — unit: ${:.2}, total({} units): ${:.2}, expensive: {}",
        instrument,
        instrument.unit_price(),
        qty,
        instrument.total_value(qty),
        instrument.is_expensive()
    );
}

// Dynamic dispatch variant: accepts any Priceable via trait object.
// Useful when you need to store mixed types in a collection.
fn print_valuation_dyn(instrument: &dyn Priceable, qty: u32) {
    println!(
        "dyn — unit: ${:.2}, total: ${:.2}",
        instrument.unit_price(),
        instrument.total_value(qty)
    );
}

// ---------------------------------------------------------------------------
// Section 7: Generics — zero-cost abstraction over types
// ---------------------------------------------------------------------------

// Generic stack that works for any type T.
// The compiler generates a separate version for each concrete T used.
#[derive(Debug)]
struct Stack<T> {
    items: Vec<T>, // Vec<T> grows on the heap; T can be anything
}

impl<T> Stack<T> {
    fn new() -> Self {
        Stack { items: Vec::new() }
    }

    fn push(&mut self, item: T) {
        self.items.push(item); // moves item onto the stack
    }

    fn pop(&mut self) -> Option<T> {
        self.items.pop() // returns Some(item) or None if empty
    }

    fn peek(&self) -> Option<&T> {
        self.items.last() // borrow the top without removing it
    }

    fn is_empty(&self) -> bool {
        self.items.is_empty()
    }

    fn size(&self) -> usize {
        self.items.len()
    }
}

// Constrained generic: T must implement Display so we can print items.
impl<T: fmt::Display> Stack<T> {
    fn print_top(&self) {
        match self.peek() {
            Some(top) => println!("Top of stack: {}", top), // T: Display required here
            None => println!("Stack is empty"),
        }
    }
}

// ---------------------------------------------------------------------------
// Section 8: Real-world — Order Management System
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
enum OrderSide {
    Buy,
    Sell,
}

impl fmt::Display for OrderSide {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            OrderSide::Buy => write!(f, "BUY"),
            OrderSide::Sell => write!(f, "SELL"),
        }
    }
}

// OrderStatus models the lifecycle of a trade order.
// Each variant carries the data relevant to that state — no unnecessary fields.
#[derive(Debug, Clone, PartialEq)]
enum OrderStatus {
    Pending,                                    // submitted, not yet acted on
    PartiallyFilled { filled_qty: u32 },        // some shares filled, rest pending
    Filled { avg_price: f64 },                  // fully executed at average price
    Cancelled { reason: String },               // rejected or cancelled
}

impl fmt::Display for OrderStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            OrderStatus::Pending => write!(f, "PENDING"),
            OrderStatus::PartiallyFilled { filled_qty } => {
                write!(f, "PARTIALLY_FILLED({})", filled_qty)
            }
            OrderStatus::Filled { avg_price } => write!(f, "FILLED(avg=${:.2})", avg_price),
            OrderStatus::Cancelled { reason } => write!(f, "CANCELLED({})", reason),
        }
    }
}

#[derive(Debug, Clone)]
struct Order {
    id: u64,
    user_id: u64,
    ticker: String,
    side: OrderSide,
    quantity: u32,
    limit_price: f64,
    status: OrderStatus,
}

impl Order {
    fn new(id: u64, user_id: u64, ticker: &str, side: OrderSide, qty: u32, price: f64) -> Self {
        Order {
            id,
            user_id,
            ticker: ticker.to_string(), // &str → owned String
            side,
            quantity: qty,
            limit_price: price,
            status: OrderStatus::Pending, // all orders start pending
        }
    }

    fn fill(&mut self, avg_price: f64) {
        // Transition from any state to Filled — in a real OMS you would
        // validate that only Pending/PartiallyFilled can transition to Filled.
        self.status = OrderStatus::Filled { avg_price };
    }

    fn partially_fill(&mut self, qty: u32) {
        self.status = OrderStatus::PartiallyFilled { filled_qty: qty };
    }

    fn cancel(&mut self, reason: &str) {
        self.status = OrderStatus::Cancelled { reason: reason.to_string() };
    }

    fn is_terminal(&self) -> bool {
        // Matches on two variants using the | (or) pattern.
        matches!(
            self.status,
            OrderStatus::Filled { .. } | OrderStatus::Cancelled { .. }
        )
    }
}

impl fmt::Display for Order {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "Order#{} [{}] {} {} {} @ ${:.2} — {}",
            self.id,
            self.user_id,
            self.side,
            self.quantity,
            self.ticker,
            self.limit_price,
            self.status
        )
    }
}

// Generic Result wrapper — wraps any value with an audit message.
#[derive(Debug)]
struct AuditedResult<T> {
    value: T,
    audit_trail: Vec<String>, // log of actions taken
}

impl<T: fmt::Display> AuditedResult<T> {
    fn new(value: T) -> Self {
        AuditedResult { value, audit_trail: Vec::new() }
    }

    fn log(&mut self, msg: &str) {
        self.audit_trail.push(msg.to_string());
    }

    fn print_trail(&self) {
        println!("Audit trail for {}:", self.value);
        for (i, entry) in self.audit_trail.iter().enumerate() {
            println!("  {}. {}", i + 1, entry);
        }
    }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

fn main() {
    println!("=== L02: Structs, Enums, and Traits ===\n");

    // --- 1. User struct ---
    println!("--- 1. Structs ---");
    let mut u = User::new(1, "Alice".into(), "alice@example.com".into());
    println!("Display: {}", u);
    println!("Debug:   {:?}", u);
    let count = u.record_login();
    println!("Login count: {}", count);
    let summary = u.into_summary(); // consumes u
    println!("Summary: {}", summary);

    // --- 2. Tuple and unit structs ---
    println!("\n--- 2. Tuple & Unit Structs ---");
    section_2_tuple_and_unit();

    // --- 3. Enums and pattern matching ---
    println!("\n--- 3. Enums ---");
    let shapes: Vec<Shape> = vec![
        Shape::Circle(5.0),
        Shape::Rectangle(4.0, 6.0),
        Shape::Triangle(3.0, 4.0, 5.0),
        Shape::Point,
    ];
    for shape in &shapes {
        println!("{} — area={:.2}, perimeter={:.2}", shape, shape.area(), shape.perimeter());
    }

    // --- 4. Option ---
    println!("\n--- 4. Option<T> ---");
    section_4_option();

    // --- 5. Result ---
    println!("\n--- 5. Result<T, E> ---");
    section_5_result();

    // --- 6. Traits ---
    println!("\n--- 6. Traits ---");
    let stock = Stock { ticker: "AAPL".into(), price: 185.50 };
    let bond = Bond { issuer: "US Treasury".into(), face_value: 1_000.0, coupon_rate: 0.045 };
    print_valuation(&stock, 10);
    print_valuation(&bond, 5);
    // Dynamic dispatch — both types behind &dyn Priceable.
    let instruments: Vec<&dyn Priceable> = vec![&stock, &bond];
    for inst in &instruments {
        print_valuation_dyn(*inst, 2);
    }

    // --- 7. Generics ---
    println!("\n--- 7. Generics ---");
    let mut int_stack: Stack<i32> = Stack::new();
    int_stack.push(10);
    int_stack.push(20);
    int_stack.push(30);
    int_stack.print_top(); // "Top of stack: 30"
    println!("popped: {:?}", int_stack.pop()); // Some(30)
    println!("size: {}", int_stack.size());     // 2

    // --- 8. Order Management System ---
    println!("\n--- 8. Order Management System ---");
    let mut order = Order::new(101, 1, "AAPL", OrderSide::Buy, 100, 180.00);
    let mut audited: AuditedResult<Order> = AuditedResult::new(order.clone());
    audited.log("Order created");

    order.partially_fill(40);
    audited.log("Partially filled 40 shares");
    println!("{}", order);

    order.fill(179.95);
    audited.log("Fully filled at avg $179.95");
    println!("{}", order);
    println!("Is terminal: {}", order.is_terminal()); // true

    let mut cancel_order = Order::new(102, 2, "TSLA", OrderSide::Sell, 50, 250.00);
    cancel_order.cancel("Price limit not met during session");
    println!("{}", cancel_order);

    audited.print_trail();

    println!("\n=== Done ===");
}
