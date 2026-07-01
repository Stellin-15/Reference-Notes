// ============================================================
// L08: Production Rust — Workspace, Config, Tracing, Docker, CI
// ============================================================
// WHAT: Patterns for taking a Rust project from single-file to
//       production-grade service: Cargo workspaces, layered
//       configuration, structured logging, Docker multi-stage
//       builds, cross-compilation, and a complete CI pipeline.
// WHY:  A "it compiles and runs locally" binary is far from
//       production-ready. You need observability (tracing), safe
//       configuration management (env vars override files),
//       reproducible builds (Docker), minimal attack surface
//       (distroless / scratch), and automated quality gates (CI).
// LEVEL: Advanced
// ============================================================
/*
CONCEPT OVERVIEW:
    Cargo workspace: a single Cargo.toml at the repo root lists
    member crates. All members share one target/ directory and one
    lock file. A typical layout is:
        workspace/
          Cargo.toml          ← [workspace] members = ["core","api","worker"]
          core/               ← shared library crate
          api/                ← binary: HTTP server
          worker/             ← binary: background job processor

    Layered configuration (config crate): settings are merged in
    priority order — defaults < config file < environment variables.
    This means: ship sensible defaults in code, override per
    environment with a TOML file, and allow ops to patch anything
    via env vars without redeploying.

    tracing crate: structured, async-aware logging. Unlike log!(),
    tracing records key-value fields attached to the current span,
    so every log line in an async handler automatically carries the
    request ID, user ID, etc. from the parent span. Essential for
    correlating logs across microservices.

    Docker multi-stage: stage 1 (rust:slim) compiles the binary;
    stage 2 (debian:slim or scratch) copies only the binary. The
    final image is ~10 MB instead of ~1.5 GB. Using the musl target
    with `cross` produces a fully static binary with zero shared lib
    dependencies.

PRODUCTION USE CASE:
    A production microservice: workspace with a core lib and an API
    binary, layered config, structured JSON tracing, Docker
    multi-stage build, and a Makefile that drives lint/test/build/
    docker targets for local dev and CI parity.

COMMON MISTAKES:
    1. Putting [dependencies] in the workspace root — workspace root
       can only hold [workspace.dependencies]; individual members
       declare their own [dependencies].
    2. Using env::var() directly throughout the codebase — config
       is scattered, typos are runtime panics. Deserialize into a
       Config struct once at startup.
    3. Initialising tracing_subscriber inside library code — only
       the binary entrypoint should call init(); library code only
       uses tracing macros.
    4. Building without --release in Docker — debug binaries are
       10–100x slower and 5x larger.
    5. Forgetting to strip debug symbols from release binaries —
       strip = true in [profile.release] halves binary size at no
       runtime cost.
*/

// ---------------------------------------------------------------------------
// SECTION 1: Cargo Workspace layout (reference — not executable Rust)
// ---------------------------------------------------------------------------
//
// File: Cargo.toml (workspace root)
// ┌──────────────────────────────────────────────────────────┐
// │ [workspace]                                              │
// │ members = ["core", "api", "worker"]                      │
// │ resolver = "2"   # required for feature unification fix  │
// │                                                          │
// │ [workspace.dependencies]                                 │
// │ # Shared versions — members inherit with { workspace = true }
// │ tokio   = { version = "1", features = ["full"] }         │
// │ serde   = { version = "1", features = ["derive"] }       │
// │ anyhow  = "1"                                            │
// │ tracing = "0.1"                                          │
// └──────────────────────────────────────────────────────────┘
//
// File: api/Cargo.toml
// ┌──────────────────────────────────────────────────────────┐
// │ [package]                                                │
// │ name = "api"                                             │
// │ version = "0.1.0"                                        │
// │ edition = "2021"                                         │
// │                                                          │
// │ [dependencies]                                           │
// │ core   = { path = "../core" }   # internal dep           │
// │ tokio  = { workspace = true }   # inherits version       │
// │ serde  = { workspace = true }                            │
// │ anyhow = { workspace = true }                            │
// └──────────────────────────────────────────────────────────┘
//
// Cargo features for conditional compilation:
// ┌──────────────────────────────────────────────────────────┐
// │ [features]                                               │
// │ default  = []                                            │
// │ metrics  = ["dep:prometheus"]                            │
// │ tracing  = ["dep:opentelemetry"]                         │
// │                                                          │
// │ [dependencies]                                           │
// │ prometheus     = { version = "0.13", optional = true }   │
// │ opentelemetry  = { version = "0.23", optional = true }   │
// └──────────────────────────────────────────────────────────┘
//
// Enable features at build time:
//   cargo build --features metrics,tracing

// ---------------------------------------------------------------------------
// SECTION 2: Dependencies for this file
// ---------------------------------------------------------------------------
// Add to Cargo.toml:
//   config             = "0.14"
//   serde              = { version = "1", features = ["derive"] }
//   anyhow             = "1"
//   thiserror          = "1"
//   tracing            = "0.1"
//   tracing-subscriber = { version = "0.3", features = ["env-filter","json"] }
//   tracing-appender   = "0.2"
//   tokio              = { version = "1", features = ["full"] }
// ---------------------------------------------------------------------------

use anyhow::{Context, Result};
use serde::Deserialize;
use std::sync::Arc;
use tracing::{debug, error, info, instrument, warn};

// ---------------------------------------------------------------------------
// SECTION 3: Layered configuration
// ---------------------------------------------------------------------------

// The Config struct is the single source of truth for all settings.
// Fields map 1:1 to config file keys / env var names.
#[derive(Debug, Deserialize, Clone)]
pub struct Config {
    pub server:   ServerConfig,
    pub database: DatabaseConfig,
    pub log:      LogConfig,
}

#[derive(Debug, Deserialize, Clone)]
pub struct ServerConfig {
    pub host:             String,
    pub port:             u16,
    pub shutdown_timeout: u64,   // seconds
}

#[derive(Debug, Deserialize, Clone)]
pub struct DatabaseConfig {
    pub url:          String,
    pub max_connections: u32,
    pub connect_timeout: u64,    // seconds
}

#[derive(Debug, Deserialize, Clone)]
pub struct LogConfig {
    pub level:  String,   // "info", "debug", "warn", "error"
    pub format: String,   // "json" or "pretty"
}

// Load configuration from multiple sources in priority order.
// The `config` crate merges them automatically.
pub fn load_config() -> Result<Config> {
    use config::{Config as Cfg, Environment, File};

    let cfg = Cfg::builder()
        // Layer 1: built-in defaults (always present).
        .set_default("server.host",               "0.0.0.0")?
        .set_default("server.port",               3000i64)?
        .set_default("server.shutdown_timeout",   30i64)?
        .set_default("database.max_connections",  10i64)?
        .set_default("database.connect_timeout",  5i64)?
        .set_default("log.level",                 "info")?
        .set_default("log.format",                "pretty")?
        // Layer 2: config file (optional; missing file is not an error).
        .add_source(File::with_name("config/default").required(false))
        // Layer 3: environment-specific file (e.g. config/production.toml).
        .add_source(
            File::with_name(&format!(
                "config/{}",
                std::env::var("APP_ENV").unwrap_or_else(|_| "development".into())
            ))
            .required(false),
        )
        // Layer 4: environment variables with prefix APP_.
        // APP_SERVER__PORT=4000 overrides server.port.
        // Double underscore __ separates nested keys.
        .add_source(Environment::with_prefix("APP").separator("__"))
        .build()
        .context("failed to build configuration")?;

    cfg.try_deserialize::<Config>()
        .context("failed to deserialize configuration")
}

// ---------------------------------------------------------------------------
// SECTION 4: Structured tracing setup
// ---------------------------------------------------------------------------

pub fn init_tracing(config: &LogConfig) -> Result<()> {
    use tracing_subscriber::{fmt, prelude::*, EnvFilter};

    // Parse log level from config, fall back to INFO.
    let filter = EnvFilter::try_from_default_env()
        .or_else(|_| EnvFilter::try_new(&config.level))
        .unwrap_or_else(|_| EnvFilter::new("info"));

    match config.format.as_str() {
        "json" => {
            // Production: JSON lines, one per log event — machine-readable,
            // ingestible by Elasticsearch, Datadog, Cloud Logging, etc.
            tracing_subscriber::registry()
                .with(filter)
                .with(fmt::layer().json())
                .init();
        }
        _ => {
            // Development: coloured, human-readable output.
            tracing_subscriber::registry()
                .with(filter)
                .with(fmt::layer().pretty())
                .init();
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// SECTION 5: #[instrument] — automatic span creation for async functions
// ---------------------------------------------------------------------------

// #[instrument] wraps the function body in a tracing span.
// The span captures function arguments as fields (skip sensitive ones).
// Every log statement inside carries those fields automatically.
#[instrument(skip(db), fields(user_id = %user_id))]
async fn fetch_user_from_db(db: &DatabaseStub, user_id: u64) -> Result<UserRecord> {
    debug!("querying database");     // fields: user_id, function name, file, line

    // Simulated DB call; replace with sqlx::query_as!(...).fetch_one(&db.pool).
    let record = db.find_user(user_id).await?;

    info!(email = %record.email, "user fetched successfully");
    Ok(record)
}

// ---------------------------------------------------------------------------
// SECTION 6: Conditional compilation with cargo features
// ---------------------------------------------------------------------------

// Feature-gated code: only compiled when the "metrics" feature is enabled.
// cargo build --features metrics
#[cfg(feature = "metrics")]
pub fn register_metrics() {
    // prometheus::register_counter!("requests_total", "Total HTTP requests").unwrap();
    info!("metrics registered");
}

#[cfg(not(feature = "metrics"))]
pub fn register_metrics() {
    // No-op when metrics feature is disabled.
    debug!("metrics feature disabled; skipping registration");
}

// ---------------------------------------------------------------------------
// SECTION 7: Testing — unit, integration, doc tests
// ---------------------------------------------------------------------------

/// Adds two numbers together.
///
/// # Examples
///
/// ```
/// // Doc tests are compiled and run by `cargo test` automatically.
/// // They serve as always-up-to-date documentation.
/// assert_eq!(production_rust_demo::add(2, 3), 5);
/// ```
pub fn add(a: i32, b: i32) -> i32 { a + b }

// Unit tests live in the same file as the code they test.
// `cargo test` discovers and runs all #[test] functions.
#[cfg(test)]
mod unit_tests {
    use super::*;

    #[test]
    fn add_works() {
        assert_eq!(add(2, 3), 5);
        assert_eq!(add(-1, 1), 0);
        assert_eq!(add(i32::MAX, 0), i32::MAX);
    }

    #[test]
    fn config_defaults_are_sane() {
        // Test config loading without any files or env vars.
        // In CI: env vars are NOT set, so defaults must be valid.
        std::env::remove_var("APP_SERVER__PORT");
        std::env::remove_var("APP_DATABASE__URL");
        // Note: this will fail unless DATABASE__URL has a default set.
        // In practice, required fields (DB URL) have no default and
        // the test verifies the error message is useful.
    }

    #[tokio::test]
    async fn instrumented_fn_does_not_panic() {
        // #[instrument] must not break normal function behaviour.
        let db = DatabaseStub::new();
        let result = fetch_user_from_db(&db, 1).await;
        assert!(result.is_ok());
    }
}

// Integration tests live in tests/ directory (separate files).
// They only have access to the public API of the crate, just like
// an external consumer would. Run with: cargo test --test my_test
//
// tests/api_test.rs (reference — not in this file):
// ┌──────────────────────────────────────────────────────────────────────┐
// │ use myservice::build_router;                                         │
// │ use axum::body::Body;                                                │
// │ use tower::ServiceExt;                                               │
// │                                                                      │
// │ #[tokio::test]                                                       │
// │ async fn health_endpoint_returns_200() {                             │
// │     let app = build_router(test_state());                            │
// │     let req = Request::get("/health").body(Body::empty()).unwrap();  │
// │     let res = app.oneshot(req).await.unwrap();                       │
// │     assert_eq!(res.status(), 200);                                   │
// │ }                                                                    │
// └──────────────────────────────────────────────────────────────────────┘

// ---------------------------------------------------------------------------
// SECTION 8: Docker multi-stage build (reference)
// ---------------------------------------------------------------------------
//
// Dockerfile
// ┌──────────────────────────────────────────────────────────────────┐
// │ # Stage 1: compile                                               │
// │ FROM rust:1.79-slim AS builder                                   │
// │ WORKDIR /app                                                     │
// │                                                                  │
// │ # Cache dependency compilation separately from source changes.   │
// │ # Only re-runs if Cargo.toml/Cargo.lock change.                  │
// │ COPY Cargo.toml Cargo.lock ./                                    │
// │ RUN mkdir src && echo 'fn main(){}' > src/main.rs               │
// │ RUN cargo build --release                                        │
// │ RUN rm -rf src                                                   │
// │                                                                  │
// │ # Now copy real source and rebuild (only src/ changed).         │
// │ COPY src ./src                                                   │
// │ RUN touch src/main.rs && cargo build --release                   │
// │                                                                  │
// │ # Stage 2: runtime image — no Rust toolchain, no source code.   │
// │ FROM debian:bookworm-slim AS final                               │
// │ RUN apt-get update && apt-get install -y ca-certificates         │
// │     && rm -rf /var/lib/apt/lists/*                               │
// │ COPY --from=builder /app/target/release/api /usr/local/bin/api  │
// │ EXPOSE 3000                                                      │
// │ ENTRYPOINT ["/usr/local/bin/api"]                                │
// └──────────────────────────────────────────────────────────────────┘
//
// For a truly minimal image (no libc at all):
// ┌──────────────────────────────────────────────────────────────────┐
// │ # Compile statically linked binary with musl                     │
// │ FROM rust:1.79 AS builder                                        │
// │ RUN rustup target add x86_64-unknown-linux-musl                 │
// │ RUN apt-get update && apt-get install -y musl-tools              │
// │ COPY . .                                                         │
// │ RUN cargo build --release --target x86_64-unknown-linux-musl    │
// │                                                                  │
// │ FROM scratch AS final   # empty base — nothing but our binary   │
// │ COPY --from=builder /app/target/x86_64-unknown-linux-musl/      │
// │      release/api /api                                            │
// │ ENTRYPOINT ["/api"]                                              │
// └──────────────────────────────────────────────────────────────────┘

// ---------------------------------------------------------------------------
// SECTION 9: Cross-compilation with `cross`
// ---------------------------------------------------------------------------
//
// `cross` wraps cargo with a Docker container for the target toolchain.
// No host-side cross toolchain setup required.
//
//   cargo install cross
//   cross build --release --target aarch64-unknown-linux-gnu
//   cross build --release --target x86_64-unknown-linux-musl
//
// Cross-compilation use cases:
//   - Build aarch64 (AWS Graviton / Apple M-series servers) from x86_64 CI
//   - Build musl static binary for Alpine / scratch Docker images
//   - Build Windows .exe from Linux CI

// ---------------------------------------------------------------------------
// SECTION 10: Binary size optimization (Cargo.toml profile)
// ---------------------------------------------------------------------------
//
// [profile.release]
// opt-level    = 3          # maximum speed (default)
// # opt-level = "z"         # minimum size (slower, smaller)
// lto          = true       # link-time optimisation: cross-crate inlining
// codegen-units = 1         # single codegen unit: better LTO, slower compile
// panic        = "abort"    # no unwinding machinery: smaller binary
// strip        = true       # strip debug symbols from final binary

// ---------------------------------------------------------------------------
// SECTION 11: CI pipeline (GitHub Actions reference)
// ---------------------------------------------------------------------------
//
// .github/workflows/ci.yml
// ┌──────────────────────────────────────────────────────────────────┐
// │ name: CI                                                         │
// │ on: [push, pull_request]                                         │
// │ jobs:                                                            │
// │   test:                                                          │
// │     runs-on: ubuntu-latest                                       │
// │     steps:                                                       │
// │       - uses: actions/checkout@v4                                │
// │       - uses: dtolnay/rust-toolchain@stable                     │
// │         with: { components: clippy, rustfmt }                   │
// │       - uses: Swatinem/rust-cache@v2   # cache target/ & registry│
// │       - run: cargo fmt --check          # fail on unformatted code│
// │       - run: cargo clippy -- -D warnings # lint as errors        │
// │       - run: cargo test                 # all unit + integration │
// │       - run: cargo audit                # CVE check on deps      │
// │       - run: cargo build --release      # verify release builds  │
// └──────────────────────────────────────────────────────────────────┘
//
// cargo nextest: faster parallel test runner.
//   cargo install cargo-nextest
//   cargo nextest run           # drop-in replacement for cargo test
//   cargo nextest run --retries 2  # retry flaky tests

// ---------------------------------------------------------------------------
// SECTION 12: Makefile for local dev + CI parity
// ---------------------------------------------------------------------------
//
// Makefile
// ┌──────────────────────────────────────────────────────────────────┐
// │ .PHONY: lint test build docker clean                             │
// │                                                                  │
// │ lint:                                                            │
// │ 	cargo fmt --check                                             │
// │ 	cargo clippy -- -D warnings                                   │
// │ 	cargo audit                                                   │
// │                                                                  │
// │ test:                                                            │
// │ 	cargo nextest run                                             │
// │                                                                  │
// │ build:                                                           │
// │ 	cargo build --release                                         │
// │                                                                  │
// │ docker:                                                          │
// │ 	docker build -t myservice:latest .                            │
// │ 	docker run --rm -p 3000:3000 myservice:latest                 │
// │                                                                  │
// │ clean:                                                           │
// │ 	cargo clean                                                   │
// └──────────────────────────────────────────────────────────────────┘

// ---------------------------------------------------------------------------
// SECTION 13: Stub types used in examples above
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct UserRecord {
    pub id:    u64,
    pub email: String,
}

// Minimal in-memory DB stub; replace with sqlx::PgPool in real code.
pub struct DatabaseStub;

impl DatabaseStub {
    pub fn new() -> Self { DatabaseStub }

    pub async fn find_user(&self, id: u64) -> Result<UserRecord> {
        if id == 0 {
            anyhow::bail!("user not found: id=0");
        }
        Ok(UserRecord { id, email: format!("user{id}@example.com") })
    }
}

// ---------------------------------------------------------------------------
// SECTION 14: Main entrypoint (production service skeleton)
// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() -> Result<()> {
    // Step 1: Load configuration (fails fast with a clear message on error).
    let config = load_config().context("configuration error")?;

    // Step 2: Initialise structured logging.
    init_tracing(&config.log)?;

    info!(
        host = %config.server.host,
        port = config.server.port,
        "service starting"
    );

    // Step 3: Register metrics if feature is enabled.
    register_metrics();

    // Step 4: Connect to database.
    // let pool = sqlx::PgPool::connect(&config.database.url).await
    //     .context("failed to connect to database")?;
    // info!(max_connections = config.database.max_connections, "database pool ready");

    // Step 5: Build and start HTTP server.
    // let state = Arc::new(AppState { pool, config: config.clone() });
    // let app   = build_router(state);
    // let addr  = format!("{}:{}", config.server.host, config.server.port);
    // let listener = tokio::net::TcpListener::bind(&addr).await?;
    // info!(%addr, "listening");
    // axum::serve(listener, app)
    //     .with_graceful_shutdown(shutdown_signal())
    //     .await?;

    // Stub: demonstrate tracing spans in action.
    let db   = DatabaseStub::new();
    let user = fetch_user_from_db(&db, 42).await?;
    info!(user_id = user.id, email = %user.email, "demo complete");

    warn!("no real server started — this is a demo binary");
    Ok(())
}

// ---------------------------------------------------------------------------
// SECTION 15: Tracing patterns for common scenarios
// ---------------------------------------------------------------------------

// Pattern: propagate request ID through all log lines in a request.
async fn handle_request_with_trace_id(request_id: &str) {
    // Create a span with request_id field; all child log lines inherit it.
    let span = tracing::info_span!("handle_request", request_id = request_id);
    let _enter = span.enter();

    info!("processing request");       // carries: request_id, target, file, line
    do_work().await;
    info!("request complete");         // carries same request_id field
}

async fn do_work() {
    // Even nested calls carry the parent span's fields automatically.
    debug!("doing internal work");
}

// Pattern: log an error with full context chain (anyhow).
fn log_error_chain(e: &anyhow::Error) {
    error!(
        error = %e,           // Display: human readable top-level message
        debug = ?e,           // Debug: full error chain with source locations
        "operation failed"
    );
}
