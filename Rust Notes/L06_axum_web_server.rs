// ============================================================
// L06: Axum Web Server
// ============================================================
// WHAT: Type-safe async HTTP server framework built on Tokio,
//       hyper (HTTP/1.1 + HTTP/2), and Tower (middleware).
// WHY:  Axum enforces correct handler signatures at compile time —
//       wrong extractor types are errors, not 500s at runtime.
//       Tower integration gives you a rich ecosystem of battle-
//       tested middleware (tracing, CORS, compression, rate limiting).
// LEVEL: Advanced
// ============================================================
/*
CONCEPT OVERVIEW:
    Axum's core abstraction is the Handler trait. Any async function
    whose parameters are all extractors, and whose return type
    implements IntoResponse, is automatically a Handler. The router
    wires URL paths to handlers and enforces that all extractors are
    valid at compile time — missing state, wrong type, bad path
    params: all are compiler errors.

    Tower middleware wraps the entire service as layers. Each layer
    is applied from outermost to innermost; a request passes through
    each layer's before-logic, hits the handler, then unwinds through
    each layer's after-logic. This separation of concerns lets you
    add logging, auth, CORS, compression, and rate-limiting without
    touching handler code.

    Shared state flows through axum::extract::State<T>. Because State
    is cloned per request, T should be cheap to clone — wrap heavy
    resources (DB pool, HTTP client) in Arc.

PRODUCTION USE CASE:
    REST API with users CRUD, shared PostgreSQL connection pool via
    sqlx, structured JSON errors, CORS for browser clients, request
    tracing, and graceful shutdown on SIGTERM/Ctrl+C. This is the
    typical shape of a microservice or BFF (backend for frontend).

COMMON MISTAKES:
    1. Defining state as a bare struct in State<AppState> — AppState
       must be Clone; wrapping in Arc<AppState> is the idiomatic fix.
    2. Returning plain strings from handlers — you need to implement
       IntoResponse on your error type, otherwise the compiler will
       complain about a missing trait impl.
    3. Accessing body (Json extractor) and another body-consuming
       extractor at the same time — HTTP body can only be read once.
    4. Putting middleware in the wrong order — auth must come before
       business logic layers, not after.
    5. Forgetting to call .into_response() when building a custom
       response — just return (StatusCode, Json(body)) as a tuple;
       axum turns tuples into responses automatically.
*/

// ---------------------------------------------------------------------------
// Dependencies (Cargo.toml):
//   axum        = { version = "0.7", features = ["macros"] }
//   tokio       = { version = "1",   features = ["full"] }
//   tower       = "0.4"
//   tower-http  = { version = "0.5", features = ["cors","trace","compression-gzip"] }
//   serde       = { version = "1",   features = ["derive"] }
//   serde_json  = "1"
//   anyhow      = "1"
//   thiserror   = "1"
//   tracing     = "0.1"
//   tracing-subscriber = { version = "0.3", features = ["env-filter"] }
//   sqlx        = { version = "0.7", features = ["postgres","runtime-tokio","uuid"] }
//   uuid        = { version = "1",   features = ["v4","serde"] }
//   validator   = { version = "0.18", features = ["derive"] }
// ---------------------------------------------------------------------------

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{delete, get, post, put},
    Json, Router,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use thiserror::Error;
use tokio::net::TcpListener;
use tower_http::{
    compression::CompressionLayer,
    cors::{Any, CorsLayer},
    trace::TraceLayer,
};
use tracing::info;
use uuid::Uuid;

// ---------------------------------------------------------------------------
// SECTION 1: Domain types
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct User {
    pub id:    Uuid,
    pub name:  String,
    pub email: String,
}

// Request body for creating a user.
// Deserialize: axum's Json extractor will call serde on the HTTP body.
// Validate: the `validator` crate checks constraints at runtime.
#[derive(Debug, Deserialize)]
pub struct CreateUserRequest {
    // #[validate(length(min = 1, max = 100))]
    pub name: String,
    // #[validate(email)]
    pub email: String,
}

// Query-string parameters: GET /users?page=2&per_page=50
// All fields should be Option<T> with defaults — query params are optional.
#[derive(Debug, Deserialize)]
pub struct ListUsersQuery {
    #[serde(default = "default_page")]
    pub page: u32,
    #[serde(default = "default_per_page")]
    pub per_page: u32,
}

fn default_page()     -> u32 { 1 }
fn default_per_page() -> u32 { 20 }

// ---------------------------------------------------------------------------
// SECTION 2: Shared application state
// ---------------------------------------------------------------------------

// All handlers get a clone of this Arc — cheap (just increments ref count).
// Replace `Vec<User>` with `sqlx::PgPool` in production.
#[derive(Clone)]
pub struct AppState {
    // In-memory store for demo; swap for sqlx::PgPool.
    pub users: Arc<tokio::sync::Mutex<Vec<User>>>,
    pub config: Arc<AppConfig>,
}

#[derive(Debug)]
pub struct AppConfig {
    pub max_page_size: u32,
}

impl AppState {
    pub fn new() -> Self {
        AppState {
            users:  Arc::new(tokio::sync::Mutex::new(Vec::new())),
            config: Arc::new(AppConfig { max_page_size: 100 }),
        }
    }
}

// ---------------------------------------------------------------------------
// SECTION 3: Error type that implements IntoResponse
// ---------------------------------------------------------------------------

// thiserror::Error derives std::error::Error and Display automatically.
#[derive(Debug, Error)]
pub enum AppError {
    #[error("not found: {0}")]
    NotFound(String),

    #[error("bad request: {0}")]
    BadRequest(String),

    #[error("internal error")]
    Internal(#[from] anyhow::Error),
}

// Implementing IntoResponse lets handlers return Result<T, AppError>.
// Axum calls this when the Err variant is returned.
impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        // Structured JSON error body — clients can match on `error` field.
        #[derive(Serialize)]
        struct ErrorBody { error: String }

        let (status, message) = match &self {
            AppError::NotFound(msg)  => (StatusCode::NOT_FOUND, msg.clone()),
            AppError::BadRequest(msg) => (StatusCode::BAD_REQUEST, msg.clone()),
            AppError::Internal(_)    => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "internal server error".into(),
            ),
        };

        // Log internal errors with full detail; don't leak to client.
        if let AppError::Internal(ref e) = self {
            tracing::error!("internal error: {e:?}");
        }

        (status, Json(ErrorBody { error: message })).into_response()
    }
}

// ---------------------------------------------------------------------------
// SECTION 4: Handler functions
// ---------------------------------------------------------------------------

// GET /users?page=1&per_page=20
// Extractors in order: Query (query string), State (shared state).
// Return type: Result<Json<Vec<User>>, AppError> — axum handles both arms.
async fn list_users(
    Query(params): Query<ListUsersQuery>,
    State(state):  State<Arc<AppState>>,
) -> Result<Json<Vec<User>>, AppError> {
    // Clamp page size to configured maximum.
    let per_page = params.per_page.min(state.config.max_page_size) as usize;
    let page     = params.page.saturating_sub(1) as usize; // 0-indexed internally

    let users = state.users.lock().await;
    let page_data: Vec<User> = users
        .iter()
        .skip(page * per_page)
        .take(per_page)
        .cloned()
        .collect();

    // info! is structured: tracing records count as a field, not a string.
    info!(count = page_data.len(), page = params.page, "listed users");
    Ok(Json(page_data))
}

// POST /users   body: {"name":"Alice","email":"alice@example.com"}
// Json<CreateUserRequest>: parses + deserializes the request body.
// Returns 201 CREATED with the new user as JSON.
async fn create_user(
    State(state): State<Arc<AppState>>,
    Json(body):   Json<CreateUserRequest>,
) -> Result<(StatusCode, Json<User>), AppError> {
    // Validate inputs (in production, run validator::Validate::validate(&body)).
    if body.name.trim().is_empty() {
        return Err(AppError::BadRequest("name cannot be empty".into()));
    }
    if !body.email.contains('@') {
        return Err(AppError::BadRequest("invalid email address".into()));
    }

    let user = User {
        id:    Uuid::new_v4(),
        name:  body.name.trim().to_owned(),
        email: body.email.to_ascii_lowercase(),
    };

    let mut users = state.users.lock().await;
    users.push(user.clone());

    info!(user_id = %user.id, "created user");

    // Tuple (StatusCode, Json(body)) implements IntoResponse automatically.
    Ok((StatusCode::CREATED, Json(user)))
}

// GET /users/:id
// Path<Uuid>: extracts and parses the `:id` segment; returns 400 if invalid UUID.
async fn get_user(
    Path(id):     Path<Uuid>,
    State(state): State<Arc<AppState>>,
) -> Result<Json<User>, AppError> {
    let users = state.users.lock().await;
    let user  = users
        .iter()
        .find(|u| u.id == id)
        .cloned()
        .ok_or_else(|| AppError::NotFound(format!("user {id} not found")))?;

    Ok(Json(user))
}

// PUT /users/:id
async fn update_user(
    Path(id):     Path<Uuid>,
    State(state): State<Arc<AppState>>,
    Json(body):   Json<CreateUserRequest>,
) -> Result<Json<User>, AppError> {
    let mut users = state.users.lock().await;
    let user = users
        .iter_mut()
        .find(|u| u.id == id)
        .ok_or_else(|| AppError::NotFound(format!("user {id} not found")))?;

    user.name  = body.name.trim().to_owned();
    user.email = body.email.to_ascii_lowercase();

    info!(user_id = %id, "updated user");
    Ok(Json(user.clone()))
}

// DELETE /users/:id — returns 204 No Content (no body).
async fn delete_user(
    Path(id):     Path<Uuid>,
    State(state): State<Arc<AppState>>,
) -> Result<StatusCode, AppError> {
    let mut users = state.users.lock().await;
    let before    = users.len();
    users.retain(|u| u.id != id);

    if users.len() == before {
        return Err(AppError::NotFound(format!("user {id} not found")));
    }

    info!(user_id = %id, "deleted user");
    Ok(StatusCode::NO_CONTENT)
}

// GET /health — lightweight liveness probe for orchestrators (k8s, ECS).
async fn health() -> (StatusCode, Json<serde_json::Value>) {
    (StatusCode::OK, Json(serde_json::json!({ "status": "ok" })))
}

// ---------------------------------------------------------------------------
// SECTION 5: Router construction
// ---------------------------------------------------------------------------

pub fn build_router(state: Arc<AppState>) -> Router {
    // CORS: allow any origin for demo; restrict to specific origins in prod.
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    // TraceLayer: logs every request (method, URI, status, latency) via tracing.
    // CompressionLayer: gzip/deflate/brotli response compression automatically.
    Router::new()
        // Group user routes; could be split into sub-routers per domain.
        .route("/users",     get(list_users).post(create_user))
        .route("/users/:id", get(get_user).put(update_user).delete(delete_user))
        .route("/health",    get(health))
        // with_state makes AppState available to all handlers via State extractor.
        .with_state(state)
        // Layers wrap the entire router; order matters — outermost runs first.
        .layer(TraceLayer::new_for_http())   // request/response logging
        .layer(cors)                          // CORS headers
        .layer(CompressionLayer::new())       // response compression
}

// ---------------------------------------------------------------------------
// SECTION 6: Graceful shutdown
// ---------------------------------------------------------------------------

// Axum's serve() accepts a shutdown future. When it resolves, the server
// stops accepting new connections and drains in-flight requests.
async fn shutdown_signal() {
    // Wait for Ctrl+C (SIGINT) OR SIGTERM (from Docker/k8s).
    let ctrl_c = async {
        tokio::signal::ctrl_c()
            .await
            .expect("failed to install Ctrl+C handler");
    };

    #[cfg(unix)]
    let terminate = async {
        tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("failed to install SIGTERM handler")
            .recv()
            .await;
    };

    // On non-Unix platforms (Windows), only Ctrl+C is available.
    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c    => { info!("received Ctrl+C, shutting down") }
        _ = terminate => { info!("received SIGTERM, shutting down") }
    }
}

// ---------------------------------------------------------------------------
// SECTION 7: Main entrypoint
// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize structured logging. Use JSON subscriber in production.
    // RUST_LOG=info,axum=debug controls verbosity.
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let state  = Arc::new(AppState::new());
    let app    = build_router(state);

    let bind   = "0.0.0.0:3000";
    let listener = TcpListener::bind(bind).await?;
    info!("listening on http://{bind}");

    // with_graceful_shutdown: wait for shutdown signal before stopping.
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;

    info!("server shut down cleanly");
    Ok(())
}

// ---------------------------------------------------------------------------
// SECTION 8: Tests — use axum::Router directly, no real HTTP server needed
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use axum::{
        body::Body,
        http::{Method, Request},
    };
    use tower::ServiceExt; // .oneshot()

    fn test_state() -> Arc<AppState> {
        Arc::new(AppState::new())
    }

    // Helper: POST /users and return the created User.
    async fn do_create(app: Router, name: &str, email: &str) -> axum::response::Response {
        let body = serde_json::json!({ "name": name, "email": email });
        let req  = Request::builder()
            .method(Method::POST)
            .uri("/users")
            .header("content-type", "application/json")
            .body(Body::from(serde_json::to_vec(&body).unwrap()))
            .unwrap();

        // oneshot: send one request through the router without a real socket.
        app.oneshot(req).await.unwrap()
    }

    #[tokio::test]
    async fn health_returns_200() {
        let app = build_router(test_state());
        let req = Request::builder().uri("/health").body(Body::empty()).unwrap();
        let res = app.oneshot(req).await.unwrap();
        assert_eq!(res.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn create_and_get_user() {
        let state = test_state();
        let app   = build_router(Arc::clone(&state));

        let res = do_create(app, "Alice", "alice@example.com").await;
        assert_eq!(res.status(), StatusCode::CREATED);

        // Parse the response body.
        let bytes = axum::body::to_bytes(res.into_body(), usize::MAX).await.unwrap();
        let user: User = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(user.name, "Alice");
        assert_eq!(user.email, "alice@example.com");

        // Verify user appears in list.
        let users = state.users.lock().await;
        assert_eq!(users.len(), 1);
        assert_eq!(users[0].id, user.id);
    }

    #[tokio::test]
    async fn get_nonexistent_user_returns_404() {
        let app = build_router(test_state());
        let id  = Uuid::new_v4();
        let req = Request::builder()
            .uri(format!("/users/{id}"))
            .body(Body::empty())
            .unwrap();
        let res = app.oneshot(req).await.unwrap();
        assert_eq!(res.status(), StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn create_user_rejects_invalid_email() {
        let app  = build_router(test_state());
        let res  = do_create(app, "Bob", "not-an-email").await;
        assert_eq!(res.status(), StatusCode::BAD_REQUEST);
    }
}
