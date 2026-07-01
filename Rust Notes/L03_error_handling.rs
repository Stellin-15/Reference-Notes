// ============================================================
// L03: Error Handling
// ============================================================
// WHAT: Rust's system for dealing with failures — custom error
//       types, the ? operator, error propagation, and ecosystem
//       crates (thiserror / anyhow) that make the boilerplate
//       manageable in production code.
// WHY:  Rust has no exceptions. Every failure is a value in the
//       return type (Result<T, E>). This forces every error path
//       to be explicitly considered, making code more robust and
//       making failure modes visible in function signatures.
// LEVEL: Foundation → Intermediate
// ============================================================
/*
CONCEPT OVERVIEW:
  Rust distinguishes two kinds of failures:
    • Unrecoverable — panic!(). The thread unwinds (or aborts). Used
      only for programmer errors: index out of bounds, unwrap() on None
      in code that "should never" reach that path, assertion failures.
      A panic in one thread does NOT crash other threads.
    • Recoverable — Result<T, E>. Used for everything the caller might
      reasonably handle: file not found, bad network packet, invalid
      user input, database timeout.

  Custom error types let you give the caller structured information
  about what went wrong rather than just a string. The standard library
  traits `std::error::Error` and `std::fmt::Display` are what the
  ecosystem expects; implement them on your error type.

  The `thiserror` crate eliminates the boilerplate of implementing
  Display and Error manually for library/crate error types. The
  `anyhow` crate provides a single opaque error type for application
  code where you care more about context chains than matching variants.

  The ? operator is syntax sugar for: "if this is Err(e), convert e
  with From::from and return it; otherwise unwrap the Ok value." This
  makes propagation chains read almost like synchronous happy-path code.

PRODUCTION USE CASE:
  A file-processing microservice that reads configuration, opens and
  parses CSV files, and writes results — all of which can fail in
  different ways. Library functions expose typed errors (thiserror).
  The main entry point uses anyhow to attach human-readable context at
  each layer, so the final error message reads like a stack trace in
  English: "failed to run pipeline: failed to open data file: No such
  file or directory (os error 2)".

COMMON MISTAKES:
  1. Calling .unwrap() everywhere. It panics on None/Err — fine in
     tests or quick scripts, dangerous in production. Replace with ?
     or explicit match/if-let.
  2. Using Box<dyn std::error::Error> in library code. It erases the
     type so callers cannot match on variants. Use a concrete enum
     (with thiserror) for library crates.
  3. Using anyhow in a library crate. anyhow is for applications;
     libraries should expose typed errors so their callers can handle
     specific cases programmatically.
  4. Logging AND returning an error. Pick one: either log where you
     handle the error (at the top of the call stack), or return it for
     the caller to log. Doing both causes duplicate log lines.
  5. Forgetting to implement From<OtherError> when chaining error types.
     Without From, ? cannot auto-convert, and you'll get compile errors.
*/

use std::fmt;
use std::num::ParseIntError;

// ---------------------------------------------------------------------------
// Section 1: panic! — for programmer errors, not user errors
// ---------------------------------------------------------------------------

fn section_1_panic_demo() {
    // Safe: index access panics if out of bounds — programmer error.
    let v = vec![1, 2, 3];
    // v[99]; // ← would panic: "index out of bounds: the len is 3 but the index is 99"

    // Explicit panic for invariant violations.
    fn divide(a: f64, b: f64) -> f64 {
        if b == 0.0 {
            // Division by zero is a programmer error in this context.
            panic!("divide called with zero denominator — fix the caller");
        }
        a / b
    }

    println!("10 / 2 = {}", divide(10.0, 2.0));
    // divide(1.0, 0.0); // ← panics at runtime with the message above

    // assert! and assert_eq! use panic! internally — for invariant checks.
    let result = 2 + 2;
    assert_eq!(result, 4, "math is broken: 2+2={}", result); // would panic if false

    println!("panic demo completed (no panic triggered)");
}

// ---------------------------------------------------------------------------
// Section 2: Basic Result usage
// ---------------------------------------------------------------------------

// parse::<T>() returns Result<T, ParseIntError>.
fn parse_port(s: &str) -> Result<u16, ParseIntError> {
    // The ? operator: if parse fails, return Err immediately.
    // If it succeeds, bind the Ok value to `n`.
    let n: u32 = s.trim().parse()?;
    // After parsing, validate the range.
    if n > 65535 {
        // We cannot use ? here because range errors are a different type.
        // We'll handle range validation in a custom error type later.
        panic!("port {} out of range", n); // simplified for now
    }
    Ok(n as u16)
}

fn section_2_basic_result() {
    match parse_port("8080") {
        Ok(port) => println!("Parsed port: {}", port),
        Err(e) => println!("Parse error: {}", e),
    }

    match parse_port("not_a_number") {
        Ok(port) => println!("Port: {}", port),
        Err(e) => println!("Expected error: {}", e), // "invalid digit found in string"
    }

    // map_err: transform the error type without changing the Ok value.
    let result: Result<u16, String> = parse_port("443")
        .map_err(|e| format!("invalid port string: {}", e));
    println!("map_err result: {:?}", result);

    // and_then: chain a second Result-returning operation.
    let doubled: Result<u16, String> = parse_port("100")
        .map_err(|e| e.to_string())
        .and_then(|p| {
            p.checked_mul(2) // returns Option<u16>
                .ok_or_else(|| "overflow on doubling port".to_string())
        });
    println!("doubled port: {:?}", doubled);
}

// ---------------------------------------------------------------------------
// Section 3: Custom error enum — typed, matchable errors
// ---------------------------------------------------------------------------

// Without thiserror (manual implementation — shows what thiserror generates).
#[derive(Debug)]
enum ConfigError {
    MissingField(String),                          // a required key was absent
    InvalidValue { field: String, message: String }, // key present but value bad
    IoError(std::io::Error),                        // underlying I/O failure
    ParseError(String),                             // numeric/format parse failure
}

// Display is what humans see; match the verbosity to the audience.
impl fmt::Display for ConfigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ConfigError::MissingField(field) => {
                write!(f, "required configuration field '{}' is missing", field)
            }
            ConfigError::InvalidValue { field, message } => {
                write!(f, "field '{}' has invalid value: {}", field, message)
            }
            ConfigError::IoError(e) => write!(f, "I/O error: {}", e),
            ConfigError::ParseError(msg) => write!(f, "parse error: {}", msg),
        }
    }
}

// std::error::Error is the trait the ecosystem uses to work with errors generically.
// The default implementation is empty — just the marker impl is needed.
impl std::error::Error for ConfigError {
    // source() returns the underlying error, enabling error chains.
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            ConfigError::IoError(e) => Some(e), // chain: ConfigError → io::Error
            _ => None,
        }
    }
}

// From<io::Error> lets ? automatically convert io::Error into ConfigError.
impl From<std::io::Error> for ConfigError {
    fn from(e: std::io::Error) -> Self {
        ConfigError::IoError(e) // wrap the io::Error in our variant
    }
}

impl From<ParseIntError> for ConfigError {
    fn from(e: ParseIntError) -> Self {
        ConfigError::ParseError(e.to_string())
    }
}

// ---------------------------------------------------------------------------
// Section 4: Using ? with custom errors — propagation chains
// ---------------------------------------------------------------------------

use std::collections::HashMap;

// Simulates reading a config file from a string of "key=value" lines.
fn parse_config(content: &str) -> Result<HashMap<String, String>, ConfigError> {
    let mut map = HashMap::new();
    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue; // skip blank lines and comments
        }
        let mut parts = line.splitn(2, '='); // split on first '=' only
        let key = parts
            .next()
            .ok_or_else(|| ConfigError::MissingField("(key)".into()))?
            .trim()
            .to_string();
        let value = parts
            .next()
            .ok_or_else(|| ConfigError::MissingField(key.clone()))?
            .trim()
            .to_string();
        map.insert(key, value);
    }
    Ok(map)
}

fn get_required<'a>(map: &'a HashMap<String, String>, key: &str) -> Result<&'a str, ConfigError> {
    // ok_or_else: converts Option<&String> to Result<&String, ConfigError>.
    map.get(key)
        .map(String::as_str) // &String → &str
        .ok_or_else(|| ConfigError::MissingField(key.to_string()))
}

fn get_port_from_config(map: &HashMap<String, String>) -> Result<u16, ConfigError> {
    let raw = get_required(map, "port")?;         // ? propagates MissingField
    let n: u32 = raw.parse::<u32>()              // parse returns ParseIntError
        .map_err(|e| ConfigError::InvalidValue {
            field: "port".to_string(),
            message: e.to_string(),
        })?;                                      // ? propagates InvalidValue
    if n > 65535 {
        return Err(ConfigError::InvalidValue {
            field: "port".to_string(),
            message: format!("{} exceeds max port 65535", n),
        });
    }
    Ok(n as u16)
}

fn section_4_propagation() {
    let good_config = "# server settings\nhost=localhost\nport=9000\nworkers=4";
    let bad_config = "host=localhost\nport=not_a_number\nworkers=4";
    let missing_config = "host=localhost\nworkers=4";

    for (label, cfg) in [("good", good_config), ("bad", bad_config), ("missing", missing_config)] {
        let result = parse_config(cfg).and_then(|map| get_port_from_config(&map));
        match result {
            Ok(port) => println!("[{}] port = {}", label, port),
            Err(e) => println!("[{}] error: {}", label, e),
        }
    }
}

// ---------------------------------------------------------------------------
// Section 5: Simulating thiserror — what the macro generates
// ---------------------------------------------------------------------------

// In real code you would write:
//   #[derive(thiserror::Error, Debug)]
//   enum AppError {
//       #[error("record {0} not found")]
//       NotFound(u64),
//       #[error("database error: {0}")]
//       Database(#[from] sqlx::Error),
//   }
//
// The macro generates the Display impl and the From impl for you.
// Here we show the equivalent hand-written version so you understand
// what thiserror does under the hood.

#[derive(Debug)]
enum AppError {
    NotFound(u64),
    DatabaseTimeout { query: String, elapsed_ms: u64 },
    Serialization(String),
    Config(ConfigError), // wraps our ConfigError from above
}

impl fmt::Display for AppError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            AppError::NotFound(id) => write!(f, "record {} not found", id),
            AppError::DatabaseTimeout { query, elapsed_ms } => {
                write!(f, "query timed out after {}ms: {}", elapsed_ms, query)
            }
            AppError::Serialization(msg) => write!(f, "serialization failed: {}", msg),
            AppError::Config(e) => write!(f, "configuration error: {}", e),
        }
    }
}

impl std::error::Error for AppError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            AppError::Config(e) => Some(e), // chain: AppError → ConfigError
            _ => None,
        }
    }
}

impl From<ConfigError> for AppError {
    fn from(e: ConfigError) -> Self {
        AppError::Config(e) // ? on a ConfigError in an AppError context auto-wraps
    }
}

fn load_app_config(content: &str) -> Result<u16, AppError> {
    // ? here converts ConfigError → AppError via From automatically.
    let map = parse_config(content)?;
    let port = get_port_from_config(&map)?;
    Ok(port)
}

fn fetch_record(id: u64) -> Result<String, AppError> {
    if id == 0 {
        return Err(AppError::NotFound(id));
    }
    if id > 9999 {
        return Err(AppError::DatabaseTimeout {
            query: format!("SELECT * FROM records WHERE id={}", id),
            elapsed_ms: 5000,
        });
    }
    Ok(format!("Record#{} data payload", id))
}

fn section_5_app_errors() {
    let config_str = "host=localhost\nport=8080";
    match load_app_config(config_str) {
        Ok(port) => println!("App port: {}", port),
        Err(e) => println!("Config failed: {}", e),
    }

    for id in [42_u64, 0, 10_000] {
        match fetch_record(id) {
            Ok(data) => println!("Got: {}", data),
            Err(e) => println!("Error: {}", e),
        }
    }
}

// ---------------------------------------------------------------------------
// Section 6: anyhow — context chains for application code
// ---------------------------------------------------------------------------

// In real code, import anyhow::{Result, Context, bail, anyhow};
// We simulate anyhow's behaviour here with a simple wrapper so this file
// compiles without external dependencies.

// Real anyhow usage looks like:
//
//   use anyhow::{Context, Result, bail};
//
//   fn read_config(path: &str) -> Result<u16> {
//       let content = std::fs::read_to_string(path)
//           .with_context(|| format!("failed to read config file '{}'", path))?;
//       let map = parse_config(&content)
//           .context("failed to parse configuration")?;
//       get_port_from_config(&map)
//           .context("failed to extract port from config")
//           .map_err(Into::into)
//   }
//
//   fn main() -> Result<()> {
//       let port = read_config("/etc/myapp/config.ini")
//           .context("failed to initialise application")?;
//       println!("Listening on port {}", port);
//       Ok(())
//   }
//
// If the file doesn't exist, the error chain prints as:
//   Error: failed to initialise application
//   Caused by:
//     0: failed to read config file '/etc/myapp/config.ini'
//     1: No such file or directory (os error 2)

fn section_6_anyhow_explanation() {
    println!("anyhow example (conceptual — no external crate needed to read this):");
    println!("  anyhow::Result<T> = Result<T, anyhow::Error>");
    println!("  .context(\"msg\")? wraps any error with a human-readable description");
    println!("  bail!(\"reason\") is shorthand for return Err(anyhow!(\"reason\"))");
    println!("  Use anyhow in APPLICATIONS; use typed enums in LIBRARIES");
}

// ---------------------------------------------------------------------------
// Section 7: Error handling patterns — collect, map_err, unwrap_or_else
// ---------------------------------------------------------------------------

fn section_7_combinators() {
    // Collect Results: Vec of Results → Result<Vec, E>
    // If ANY element fails, the whole collect returns the first Err.
    let strings = vec!["1", "2", "3", "four", "5"];
    let parsed: Result<Vec<i32>, _> = strings.iter().map(|s| s.parse::<i32>()).collect();
    match parsed {
        Ok(nums) => println!("all parsed: {:?}", nums),
        Err(e) => println!("parse failed (expected): {}", e), // stops at "four"
    }

    // Filter successful parses only (ignore failures).
    let good_only: Vec<i32> = strings
        .iter()
        .filter_map(|s| s.parse::<i32>().ok()) // .ok() converts Result → Option
        .collect();
    println!("good only: {:?}", good_only); // [1, 2, 3, 5]

    // unwrap_or_else: provide a fallback computation on error.
    let port: u16 = "xyz".parse::<u16>().unwrap_or_else(|_| 8080); // default to 8080
    println!("port with fallback: {}", port);

    // or_else: try an alternative Result-returning function on failure.
    fn try_parse_env() -> Result<u16, String> {
        Err("env var not set".to_string()) // simulated failure
    }
    let port: u16 = try_parse_env()
        .or_else(|_| "9090".parse::<u16>().map_err(|e| e.to_string()))
        .unwrap_or(8080); // final fallback
    println!("port from or_else chain: {}", port);
}

// ---------------------------------------------------------------------------
// Section 8: Real-world — file processing service with full error context
// ---------------------------------------------------------------------------

#[derive(Debug)]
enum ProcessingError {
    Io(std::io::Error),
    Parse { line: usize, content: String, reason: String },
    Validation { row: usize, field: String, message: String },
    Empty,
}

impl fmt::Display for ProcessingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ProcessingError::Io(e) => write!(f, "I/O error: {}", e),
            ProcessingError::Parse { line, content, reason } => {
                write!(f, "line {}: parse error on '{}': {}", line, content, reason)
            }
            ProcessingError::Validation { row, field, message } => {
                write!(f, "row {}: validation failed on '{}': {}", row, field, message)
            }
            ProcessingError::Empty => write!(f, "input file is empty"),
        }
    }
}

impl std::error::Error for ProcessingError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        if let ProcessingError::Io(e) = self {
            Some(e)
        } else {
            None
        }
    }
}

impl From<std::io::Error> for ProcessingError {
    fn from(e: std::io::Error) -> Self {
        ProcessingError::Io(e)
    }
}

// Parses a CSV-like string of "name,amount" records.
fn parse_csv_records(content: &str) -> Result<Vec<(String, f64)>, ProcessingError> {
    if content.trim().is_empty() {
        return Err(ProcessingError::Empty);
    }

    let mut records = Vec::new();

    for (idx, line) in content.lines().enumerate() {
        let line_num = idx + 1; // 1-based for human error messages
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue; // skip blank lines and comments
        }

        let mut cols = line.splitn(2, ',');
        let name = cols
            .next()
            .ok_or_else(|| ProcessingError::Parse {
                line: line_num,
                content: line.to_string(),
                reason: "missing name column".to_string(),
            })?
            .trim()
            .to_string();

        let amount_str = cols
            .next()
            .ok_or_else(|| ProcessingError::Parse {
                line: line_num,
                content: line.to_string(),
                reason: "missing amount column".to_string(),
            })?
            .trim();

        let amount: f64 = amount_str.parse().map_err(|_| ProcessingError::Parse {
            line: line_num,
            content: line.to_string(),
            reason: format!("'{}' is not a valid number", amount_str),
        })?;

        // Business rule validation: amounts must be positive.
        if amount <= 0.0 {
            return Err(ProcessingError::Validation {
                row: line_num,
                field: "amount".to_string(),
                message: format!("must be positive, got {}", amount),
            });
        }

        records.push((name, amount));
    }

    Ok(records)
}

fn compute_report(records: &[(String, f64)]) -> String {
    let total: f64 = records.iter().map(|(_, amt)| amt).sum();
    let max = records.iter().map(|(_, amt)| amt).cloned().fold(f64::NEG_INFINITY, f64::max);
    format!(
        "Processed {} records | Total: {:.2} | Max: {:.2}",
        records.len(),
        total,
        max
    )
}

fn section_8_file_processor() {
    let good_input = "# Transaction records\nAlice,150.00\nBob,300.50\nCarol,75.25";
    let bad_amount = "Alice,150.00\nBob,abc\nCarol,75.25";
    let negative = "Alice,150.00\nBob,-50.00";
    let empty = "";

    for (label, input) in [
        ("good", good_input),
        ("bad_amount", bad_amount),
        ("negative", negative),
        ("empty", empty),
    ] {
        match parse_csv_records(input) {
            Ok(records) => println!("[{}] {}", label, compute_report(&records)),
            Err(e) => {
                // Log the full error chain: error + its source.
                println!("[{}] Error: {}", label, e);
                if let Some(src) = std::error::Error::source(&e) {
                    println!("  Caused by: {}", src);
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

fn main() {
    println!("=== L03: Error Handling ===\n");

    println!("--- 1. panic! ---");
    section_1_panic_demo();

    println!("\n--- 2. Basic Result ---");
    section_2_basic_result();

    println!("\n--- 3 & 4. Custom Errors & Propagation ---");
    section_4_propagation();

    println!("\n--- 5. App-level Errors ---");
    section_5_app_errors();

    println!("\n--- 6. anyhow (conceptual) ---");
    section_6_anyhow_explanation();

    println!("\n--- 7. Result Combinators ---");
    section_7_combinators();

    println!("\n--- 8. File Processing Service ---");
    section_8_file_processor();

    println!("\n=== Done ===");
}
