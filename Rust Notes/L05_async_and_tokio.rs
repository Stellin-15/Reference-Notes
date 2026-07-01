// ============================================================
// L05: Async Rust and Tokio Runtime
// ============================================================
// WHAT: Asynchronous programming model using Rust's Future trait
//       and the Tokio runtime for concurrent IO-bound workloads.
// WHY:  A single OS thread can handle thousands of concurrent
//       connections without blocking — no thread-per-connection
//       overhead. Rust gives you Node.js-style concurrency with
//       compile-time safety and zero-cost abstractions.
// LEVEL: Advanced
// ============================================================
/*
CONCEPT OVERVIEW:
    Rust's async/await is built on a state-machine transformation.
    When you write `async fn`, the compiler rewrites it into a
    struct implementing the Future trait. Calling the function
    produces the struct but does NOT execute it. Execution only
    starts when you `.await` it — at which point the current
    task is suspended and the scheduler can run other tasks.

    Tokio is the async runtime: it provides the executor (thread
    pool), IO driver (epoll/kqueue/IOCP), and async-aware
    synchronisation primitives. Without a runtime, Futures are
    inert values that do nothing.

    Key mental model: tasks are green threads scheduled by Tokio.
    `tokio::spawn` creates a task (like a goroutine). Tasks are
    cooperatively scheduled — they yield at every `.await` point.
    Long CPU-bound work inside an async task blocks the executor;
    use `tokio::task::spawn_blocking` for that.

PRODUCTION USE CASE:
    HTTP scraper that fetches thousands of URLs concurrently,
    with per-request timeouts, rate limiting via Semaphore,
    and graceful shutdown via a broadcast channel. This pattern
    is used in data pipelines, link checkers, and API aggregators.

COMMON MISTAKES:
    1. Using std::sync::Mutex inside async code — it blocks the
       OS thread while held across an await, starving other tasks.
       Use tokio::sync::Mutex instead.
    2. Forgetting that async fn is lazy — you MUST .await it or
       spawn it; otherwise nothing runs and no error is emitted.
    3. Holding a MutexGuard across an .await point — this is a
       compile error with tokio::sync::Mutex but a runtime
       deadlock with std::sync::Mutex.
    4. Spawning too many tasks without backpressure — use a
       Semaphore to cap concurrency.
    5. Not reusing reqwest::Client — each new Client creates a
       new connection pool, destroying the performance benefit.
*/

// ---------------------------------------------------------------------------
// Dependencies (add to Cargo.toml):
//   tokio      = { version = "1", features = ["full"] }
//   reqwest    = { version = "0.12", features = ["json"] }
//   anyhow     = "1"
//   serde      = { version = "1", features = ["derive"] }
//   futures    = "0.3"
//   tokio-stream = "0.1"
// ---------------------------------------------------------------------------

use anyhow::{Context, Result};
use futures::StreamExt;           // .next() on streams
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{broadcast, mpsc, Semaphore};
use tokio::time::{sleep, timeout, Instant};

// ---------------------------------------------------------------------------
// SECTION 1: Basic async fn and .await
// ---------------------------------------------------------------------------

// `async fn` desugars to: fn fetch_url(...) -> impl Future<Output = Result<String>>
// The function body does not run until the caller .awaits the returned Future.
async fn fetch_url(client: &reqwest::Client, url: &str) -> Result<String> {
    // .await suspends THIS task here, allowing Tokio to run others.
    // When the response arrives (IO is ready), this task resumes.
    let response = client
        .get(url)
        .send()
        .await                             // suspend: wait for HTTP response headers
        .context("failed to send request")?;

    let body = response
        .text()
        .await                             // suspend: wait for full body download
        .context("failed to read body")?;

    Ok(body)
}

// ---------------------------------------------------------------------------
// SECTION 2: tokio::spawn — launching concurrent tasks
// ---------------------------------------------------------------------------

// spawn detaches the task onto the Tokio thread pool.
// Returns JoinHandle<T>; .await on the handle gets the task's return value.
// If you drop the handle, the task still runs (fire-and-forget).
async fn spawn_demo() -> Result<()> {
    // Each spawned task is independent — they run concurrently.
    let handle_a = tokio::spawn(async {
        sleep(Duration::from_millis(100)).await;
        "task A done"
    });

    let handle_b = tokio::spawn(async {
        sleep(Duration::from_millis(50)).await;
        "task B done"
    });

    // JoinHandle returns Result<T, JoinError>; JoinError if the task panicked.
    let result_a = handle_a.await?;   // waits for task A
    let result_b = handle_b.await?;   // waits for task B
    println!("{result_a}, {result_b}");
    Ok(())
}

// ---------------------------------------------------------------------------
// SECTION 3: tokio::time — sleep, timeout, interval
// ---------------------------------------------------------------------------

async fn time_demo() -> Result<()> {
    // sleep: yields this task for a duration, other tasks run meanwhile.
    sleep(Duration::from_millis(200)).await;

    // timeout: wrap any Future; returns Err(Elapsed) if it takes too long.
    // Pattern: give each network call its own deadline.
    let result = timeout(
        Duration::from_secs(5),
        fetch_url(&reqwest::Client::new(), "https://example.com"),
    )
    .await;

    match result {
        Ok(Ok(body)) => println!("got {} bytes", body.len()),
        Ok(Err(e))   => eprintln!("fetch error: {e}"),
        Err(_elapsed) => eprintln!("request timed out after 5 s"),
    }

    // interval: fires repeatedly; first tick is immediate.
    // Use for heartbeats, polling, metric flushes.
    let mut interval = tokio::time::interval(Duration::from_secs(1));
    for i in 0..3 {
        interval.tick().await;   // waits until next tick period
        println!("heartbeat {i}");
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// SECTION 4: tokio::sync channels
// ---------------------------------------------------------------------------

async fn channel_demo() -> Result<()> {
    // mpsc: multiple producers, single consumer. Work queue pattern.
    let (tx, mut rx) = mpsc::channel::<String>(32); // buffer = 32 items

    // Producer task: sends work items.
    let tx_clone = tx.clone();
    tokio::spawn(async move {
        for i in 0..5 {
            // send().await blocks if buffer is full (backpressure).
            tx_clone.send(format!("item {i}")).await.ok();
        }
        // Dropping tx closes the channel — receiver gets None.
    });
    drop(tx); // drop original tx so channel closes when spawn's tx is dropped

    // Consumer: drain the channel.
    while let Some(item) = rx.recv().await {
        println!("received: {item}");
    }

    // oneshot: single value, single use. Request/response pattern.
    let (resp_tx, resp_rx) = tokio::sync::oneshot::channel::<u64>();
    tokio::spawn(async move {
        let result = 42u64;
        resp_tx.send(result).ok(); // send consumes the sender
    });
    let value = resp_rx.await?;   // blocks until value arrives
    println!("oneshot value: {value}");

    // broadcast: one sender, many receivers. Shutdown signal pattern.
    let (bcast_tx, mut bcast_rx1) = broadcast::channel::<&str>(16);
    let mut bcast_rx2 = bcast_tx.subscribe(); // second subscriber
    bcast_tx.send("event").ok();
    println!("rx1: {}", bcast_rx1.recv().await?);
    println!("rx2: {}", bcast_rx2.recv().await?);

    Ok(())
}

// ---------------------------------------------------------------------------
// SECTION 5: tokio::select! — race multiple futures
// ---------------------------------------------------------------------------

async fn select_demo(mut shutdown: broadcast::Receiver<()>) -> Result<()> {
    let mut interval = tokio::time::interval(Duration::from_millis(500));

    loop {
        // select! polls all branches concurrently; runs the FIRST that's ready.
        // Remaining futures are dropped (cancelled) — they must be cancel-safe.
        tokio::select! {
            // Branch 1: periodic work
            _ = interval.tick() => {
                println!("doing periodic work");
            }
            // Branch 2: shutdown signal received
            _ = shutdown.recv() => {
                println!("shutting down");
                break;
            }
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// SECTION 6: tokio::sync::Semaphore — rate limiting / bounded concurrency
// ---------------------------------------------------------------------------

// Semaphore limits how many tasks run at once.
// Acquire a permit before doing work; drop permit when done.
async fn rate_limited_fetch(
    client: Arc<reqwest::Client>,
    urls: Vec<String>,
    max_concurrent: usize,
    request_timeout: Duration,
) -> Vec<Result<String>> {
    let semaphore = Arc::new(Semaphore::new(max_concurrent));
    let mut handles = Vec::with_capacity(urls.len());

    for url in urls {
        let client = Arc::clone(&client);
        let sem    = Arc::clone(&semaphore);

        let handle = tokio::spawn(async move {
            // acquire_owned: permit lives as long as the guard variable.
            // Dropping the guard returns the permit to the semaphore.
            let _permit = sem.acquire_owned().await?;

            // Each request gets its own timeout.
            timeout(request_timeout, fetch_url(&client, &url))
                .await
                .context("request timed out")?
        });

        handles.push(handle);
    }

    // Collect results in submission order.
    let mut results = Vec::with_capacity(handles.len());
    for handle in handles {
        results.push(handle.await.unwrap_or_else(|e| Err(e.into())));
    }
    results
}

// ---------------------------------------------------------------------------
// SECTION 7: Streams — async iteration
// ---------------------------------------------------------------------------

// Stream is the async equivalent of Iterator: yields values over time.
// futures::StreamExt adds combinator methods (.map, .filter, .for_each, etc.)
async fn stream_demo() -> Result<()> {
    use tokio_stream::wrappers::ReceiverStream;

    let (tx, rx) = mpsc::channel::<u32>(10);

    // Produce values asynchronously.
    tokio::spawn(async move {
        for i in 0u32..10 {
            tx.send(i).await.ok();
            sleep(Duration::from_millis(10)).await;
        }
    });

    // Wrap the receiver as a Stream, then process with combinators.
    let mut stream = ReceiverStream::new(rx);

    // .next() is the fundamental stream primitive — yields Option<T>.
    while let Some(value) = stream.next().await {
        println!("stream value: {value}");
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// SECTION 8: Full example — async HTTP scraper with graceful shutdown
// ---------------------------------------------------------------------------

#[derive(Debug)]
struct ScrapeResult {
    url:          String,
    byte_count:   usize,
    elapsed_ms:   u128,
    error:        Option<String>,
}

async fn scraper_main() -> Result<()> {
    // Reuse one Client across all requests — connection pool is shared.
    let client = Arc::new(
        reqwest::Client::builder()
            .user_agent("rust-scraper/1.0")
            .build()?,
    );

    let urls: Vec<String> = vec![
        "https://httpbin.org/get".into(),
        "https://httpbin.org/delay/1".into(),
        "https://httpbin.org/status/404".into(),
    ];

    // Broadcast channel: one signal fans out to all worker tasks.
    let (shutdown_tx, _) = broadcast::channel::<()>(1);
    let shutdown_tx = Arc::new(shutdown_tx);

    // Limit: at most 10 concurrent HTTP requests at any time.
    let semaphore = Arc::new(Semaphore::new(10));

    // Channel to collect results from worker tasks.
    let (result_tx, mut result_rx) = mpsc::channel::<ScrapeResult>(128);

    // Spawn a task per URL.
    for url in &urls {
        let client      = Arc::clone(&client);
        let sem         = Arc::clone(&semaphore);
        let result_tx   = result_tx.clone();
        let url         = url.clone();
        let mut shutdown_rx = shutdown_tx.subscribe();

        tokio::spawn(async move {
            // Acquire semaphore permit — blocks if at limit.
            let _permit = sem.acquire_owned().await.unwrap();
            let start   = Instant::now();

            // Race the fetch against the shutdown signal.
            let outcome = tokio::select! {
                res = timeout(Duration::from_secs(5), fetch_url(&client, &url)) => {
                    match res {
                        Ok(Ok(body))     => ScrapeResult {
                            url: url.clone(),
                            byte_count: body.len(),
                            elapsed_ms: start.elapsed().as_millis(),
                            error: None,
                        },
                        Ok(Err(e))       => ScrapeResult {
                            url: url.clone(),
                            byte_count: 0,
                            elapsed_ms: start.elapsed().as_millis(),
                            error: Some(e.to_string()),
                        },
                        Err(_elapsed)    => ScrapeResult {
                            url: url.clone(),
                            byte_count: 0,
                            elapsed_ms: 5_000,
                            error: Some("timeout".into()),
                        },
                    }
                }
                _ = shutdown_rx.recv() => {
                    // Graceful shutdown: abort this request.
                    ScrapeResult {
                        url: url.clone(),
                        byte_count: 0,
                        elapsed_ms: 0,
                        error: Some("cancelled by shutdown".into()),
                    }
                }
            };

            result_tx.send(outcome).await.ok();
        });
    }

    // Drop the extra sender so the channel closes when all workers finish.
    drop(result_tx);

    // Listen for Ctrl+C; send shutdown signal to all workers.
    let shutdown_tx_clone = Arc::clone(&shutdown_tx);
    tokio::spawn(async move {
        tokio::signal::ctrl_c().await.ok();
        println!("\nCtrl+C received — shutting down workers");
        shutdown_tx_clone.send(()).ok();
    });

    // Collect results as they arrive.
    let mut all_results = Vec::new();
    while let Some(result) = result_rx.recv().await {
        println!(
            "[{}] {} bytes in {}ms  error={:?}",
            result.url, result.byte_count, result.elapsed_ms, result.error
        );
        all_results.push(result);
    }

    println!("scraped {} URLs", all_results.len());
    Ok(())
}

// ---------------------------------------------------------------------------
// #[tokio::main]: macro expands to building a Tokio runtime and calling
// block_on(async_main()). For tests use #[tokio::test].
// ---------------------------------------------------------------------------
#[tokio::main]
async fn main() -> Result<()> {
    // Walk through each demo section.
    spawn_demo().await?;
    time_demo().await?;
    channel_demo().await?;
    stream_demo().await?;
    scraper_main().await?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Tests: use #[tokio::test] for async test functions.
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_semaphore_limits_concurrency() {
        let sem        = Arc::new(Semaphore::new(2));
        let counter    = Arc::new(tokio::sync::Mutex::new(0u32));
        let max_seen   = Arc::new(tokio::sync::Mutex::new(0u32));
        let mut handles = vec![];

        for _ in 0..8 {
            let sem      = Arc::clone(&sem);
            let counter  = Arc::clone(&counter);
            let max_seen = Arc::clone(&max_seen);

            handles.push(tokio::spawn(async move {
                let _permit = sem.acquire_owned().await.unwrap();
                // Increment active count, record peak, then decrement.
                let mut c = counter.lock().await;
                *c += 1;
                let current = *c;
                drop(c);

                let mut m = max_seen.lock().await;
                if current > *m { *m = current; }
                drop(m);

                sleep(Duration::from_millis(10)).await;

                let mut c = counter.lock().await;
                *c -= 1;
            }));
        }

        for h in handles { h.await.unwrap(); }

        // Peak concurrency must not exceed semaphore limit (2).
        let peak = *max_seen.lock().await;
        assert!(peak <= 2, "peak concurrency {peak} exceeded limit 2");
    }

    #[tokio::test]
    async fn test_timeout_fires() {
        // An operation that takes longer than its deadline.
        let result = timeout(
            Duration::from_millis(10),
            sleep(Duration::from_secs(10)),
        )
        .await;
        assert!(result.is_err(), "timeout should have fired");
    }
}
