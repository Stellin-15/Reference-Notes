// ============================================================
// L04: Concurrency
// ============================================================
// WHAT: Rust's "fearless concurrency" — threads, shared state via
//       Arc<Mutex<T>>, message passing via channels, data parallelism
//       via rayon, and async I/O via Tokio — all with data-race
//       freedom enforced at compile time by the ownership system.
// WHY:  Concurrent bugs (data races, use-after-free across threads,
//       deadlocks from incorrect locking) are among the hardest bugs
//       to find and reproduce. Rust's Send/Sync traits and ownership
//       rules make an entire class of these bugs compile-time errors
//       rather than runtime surprises in production.
// LEVEL: Intermediate
// ============================================================
/*
CONCEPT OVERVIEW:
  Rust enforces two marker traits at compile time:
    • Send:  a type can be transferred to another thread.
    • Sync:  a type can be shared (via reference) between threads.
  The compiler automatically derives Send/Sync for most types. Types
  that are inherently thread-unsafe (e.g. Rc<T>, Cell<T>) are neither.
  This means you physically cannot accidentally send a non-thread-safe
  type to another thread — you get a compile error.

  Thread-based concurrency (std::thread):
    • spawn() + JoinHandle for parallelism within one process.
    • move closures to transfer ownership into the new thread.
    • Arc (Atomic Reference Count) for shared ownership.
    • Mutex<T> for mutual exclusion; RwLock<T> for reader-writer.

  Channel-based concurrency (std::sync::mpsc):
    • Multi-producer, single-consumer channels.
    • Decouples producers from consumers.
    • sync_channel(n) for bounded channels (backpressure).

  Data parallelism (rayon):
    • par_iter() mirrors Iterator API but runs in parallel.
    • Work-stealing thread pool — automatic load balancing.
    • Best for CPU-bound, embarrassingly parallel work.

  Async I/O (Tokio):
    • async fn / .await for non-blocking I/O.
    • Green threads (tasks) multiplexed over OS threads.
    • Best for I/O-bound work with many concurrent connections.
    • tokio::sync::Mutex (async-aware, not blocking).

PRODUCTION USE CASE:
  A concurrent file processor: multiple worker threads read and
  process files from a job queue, accumulate results in a shared
  HashMap (Arc<Mutex<…>>), send summaries through a channel to a
  reporter thread, and honour a shutdown signal. This pattern appears
  in log aggregators, batch ETL pipelines, and web crawlers.

COMMON MISTAKES:
  1. Using std::sync::Mutex inside async code. lock() blocks the OS
     thread, starving other async tasks on the same thread. Use
     tokio::sync::Mutex in async contexts.
  2. Holding a MutexGuard across an .await point — the guard is not
     Send, so the compiler will catch this, but the error message can
     be confusing.
  3. Cloning Arc unnecessarily instead of passing a reference. Arc
     clones are cheap (atomic increment) but still add up. Pass
     &arc when the callee doesn't need to store it.
  4. Deadlock: locking two mutexes in different orders in different
     threads. Always acquire locks in the same consistent order.
  5. Spawning threads for I/O-bound work instead of using async, or
     using async for CPU-bound work (which blocks the executor).
     Match the tool to the workload.
*/

use std::collections::HashMap;
use std::sync::{Arc, Mutex, RwLock};
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

// ---------------------------------------------------------------------------
// Section 1: Basic thread spawning
// ---------------------------------------------------------------------------

fn section_1_basic_threads() {
    // thread::spawn takes a closure and runs it on a new OS thread.
    // Returns a JoinHandle<T> where T is the closure's return type.
    let handle = thread::spawn(|| {
        for i in 0..5 {
            println!("  spawned thread: iteration {}", i);
            thread::sleep(Duration::from_millis(10)); // simulate work
        }
        42_i32 // the thread's return value, retrieved via join()
    });

    // Main thread continues concurrently with the spawned thread.
    for i in 0..3 {
        println!("  main thread: iteration {}", i);
        thread::sleep(Duration::from_millis(15));
    }

    // join() blocks until the thread finishes, then returns Result<T, _>.
    // The outer unwrap() handles the case where the thread panicked.
    let result = handle.join().unwrap();
    println!("  spawned thread returned: {}", result);
}

// ---------------------------------------------------------------------------
// Section 2: Move closures — transferring ownership to a thread
// ---------------------------------------------------------------------------

fn section_2_move_closures() {
    let data = vec![10, 20, 30, 40, 50];

    // Without `move`, the closure borrows `data`. But the borrow might
    // outlive the current function — the compiler rejects it.
    // With `move`, the closure takes ownership of `data`.
    // The original `data` is no longer accessible in the spawning thread.
    let handle = thread::spawn(move || {
        // `data` is now owned by this thread; no other thread can touch it.
        let sum: i32 = data.iter().sum();
        println!("  thread owns data, sum = {}", sum);
        sum
    });

    // `data` was moved — we cannot use it here anymore.
    // println!("{:?}", data); // ← compile error: value moved into closure

    let sum = handle.join().unwrap();
    println!("  retrieved sum from thread: {}", sum);
}

// ---------------------------------------------------------------------------
// Section 3: Arc — shared ownership across threads
// ---------------------------------------------------------------------------

fn section_3_arc() {
    // Arc<T> = Atomically Reference Counted pointer.
    // Like Rc<T> but the reference count update is atomic → thread-safe.
    // All clones of an Arc point to the same heap allocation.
    let shared_data: Arc<Vec<i32>> = Arc::new(vec![1, 2, 3, 4, 5]);

    let mut handles = Vec::new();

    for thread_id in 0..3 {
        // Clone the Arc: increments the atomic reference count.
        // Each thread gets its own Arc handle to the same underlying Vec.
        let data_clone = Arc::clone(&shared_data);

        let h = thread::spawn(move || {
            // data_clone is Send because Arc<Vec<i32>> is Send.
            // Multiple threads can READ concurrently — Vec is Sync.
            let local_sum: i32 = data_clone.iter().sum();
            println!("  thread {}: read shared data, sum={}", thread_id, local_sum);
        });
        handles.push(h);
    }

    for h in handles {
        h.join().unwrap(); // wait for all threads
    }

    // The original Arc is still valid — its count drops to 1 after the threads finish.
    println!("  main still holds Arc, len={}", shared_data.len());
}

// ---------------------------------------------------------------------------
// Section 4: Mutex<T> — mutual exclusion for mutable shared state
// ---------------------------------------------------------------------------

fn section_4_mutex() {
    // Arc<Mutex<T>> is the canonical pattern for shared mutable state.
    // Arc: shared ownership. Mutex: exclusive access to the inner T.
    let counter: Arc<Mutex<u64>> = Arc::new(Mutex::new(0));

    let mut handles = Vec::new();

    for _ in 0..8 {
        let counter_clone = Arc::clone(&counter);
        let h = thread::spawn(move || {
            for _ in 0..1_000 {
                // lock() blocks until no other thread holds the lock.
                // Returns a MutexGuard<u64> that auto-unlocks when dropped.
                let mut guard = counter_clone.lock().unwrap();
                // unwrap() here: if another thread panicked while holding
                // the lock, Mutex is "poisoned" and lock() returns Err.
                *guard += 1; // dereference the guard to access the inner u64
                // Guard drops at end of block → mutex unlocked immediately.
            }
        });
        handles.push(h);
    }

    for h in handles {
        h.join().unwrap();
    }

    let final_count = *counter.lock().unwrap();
    println!("  final counter: {} (expected 8000)", final_count);
}

// ---------------------------------------------------------------------------
// Section 5: RwLock — multiple readers OR one writer
// ---------------------------------------------------------------------------

fn section_5_rwlock() {
    // RwLock<T> is more efficient than Mutex when reads are frequent and
    // writes are rare. Multiple threads can hold read locks simultaneously;
    // a write lock is exclusive (blocks all readers and other writers).
    let cache: Arc<RwLock<HashMap<String, String>>> =
        Arc::new(RwLock::new(HashMap::new()));

    // Writer thread: inserts entries into the shared cache.
    {
        let cache_w = Arc::clone(&cache);
        let writer = thread::spawn(move || {
            let mut map = cache_w.write().unwrap(); // exclusive write lock
            map.insert("key1".to_string(), "value1".to_string());
            map.insert("key2".to_string(), "value2".to_string());
            println!("  writer inserted 2 entries");
        }); // write lock dropped when `map` goes out of scope
        writer.join().unwrap();
    }

    // Multiple reader threads: safe to run concurrently.
    let mut readers = Vec::new();
    for i in 0..3 {
        let cache_r = Arc::clone(&cache);
        let r = thread::spawn(move || {
            let map = cache_r.read().unwrap(); // shared read lock
            println!("  reader {}: key1={:?}", i, map.get("key1"));
        }); // read lock dropped here
        readers.push(r);
    }
    for r in readers {
        r.join().unwrap();
    }
}

// ---------------------------------------------------------------------------
// Section 6: Channels — message passing between threads
// ---------------------------------------------------------------------------

fn section_6_channels() {
    // mpsc = multi-producer, single-consumer.
    // tx (transmitter) can be cloned; rx (receiver) cannot.
    let (tx, rx) = mpsc::channel::<String>();

    // Spawn multiple producer threads, each with its own clone of tx.
    let mut producers = Vec::new();
    for producer_id in 0..4 {
        let tx_clone = tx.clone(); // clone increases producer count
        let h = thread::spawn(move || {
            for msg_id in 0..3 {
                let msg = format!("producer-{} msg-{}", producer_id, msg_id);
                // send() moves the value into the channel; fails only if rx is dropped.
                tx_clone.send(msg).expect("receiver hung up");
                thread::sleep(Duration::from_millis(5));
            }
        });
        producers.push(h);
    }

    // Drop the original tx so the channel closes when all clones are dropped.
    drop(tx);

    // Receiver iterates until the channel is empty AND all senders are dropped.
    let mut received = 0;
    for msg in rx {
        // rx acts like an iterator — blocks until a message arrives or channel closes.
        received += 1;
        // Print only a few to avoid flooding output.
        if received <= 3 {
            println!("  received: {}", msg);
        }
    }
    println!("  total messages received: {}", received); // should be 4*3 = 12

    for h in producers {
        h.join().unwrap();
    }
}

// ---------------------------------------------------------------------------
// Section 7: Bounded channel — backpressure with sync_channel
// ---------------------------------------------------------------------------

fn section_7_bounded_channel() {
    // sync_channel(n): channel with a bounded buffer of n items.
    // send() BLOCKS when the buffer is full — this is backpressure.
    // Use this to prevent producers from running ahead of the consumer.
    let (tx, rx) = mpsc::sync_channel::<u32>(4); // buffer size = 4

    let producer = thread::spawn(move || {
        for i in 0..10 {
            println!("  sending {}", i);
            tx.send(i).unwrap(); // blocks if buffer is full (consumer is slow)
        }
    });

    // Slow consumer — processes one item every 20ms.
    thread::sleep(Duration::from_millis(50)); // let producer fill buffer
    for val in rx {
        println!("  consumed {}", val);
        thread::sleep(Duration::from_millis(20));
    }

    producer.join().unwrap();
}

// ---------------------------------------------------------------------------
// Section 8: Data parallelism with rayon (conceptual)
// ---------------------------------------------------------------------------

// Rayon is an external crate (add `rayon = "1"` to Cargo.toml).
// Its API mirrors Iterator exactly, so the migration is often just
// changing .iter() to .par_iter().
//
// use rayon::prelude::*;
//
// fn parallel_sum(data: &[f64]) -> f64 {
//     data.par_iter().sum()   // automatically parallelised
// }
//
// fn parallel_map(data: &[i32]) -> Vec<i32> {
//     data.par_iter()
//         .map(|&x| heavy_compute(x))  // each item processed in parallel
//         .collect()
// }
//
// fn parallel_filter_map(data: &[i32]) -> Vec<i32> {
//     data.par_iter()
//         .filter(|&&x| x % 2 == 0)
//         .map(|&x| x * x)
//         .collect()
// }
//
// Rayon uses a work-stealing thread pool sized to the number of CPU cores.
// It shines for CPU-bound tasks (compression, image processing, matrix ops).
// Do NOT use rayon for I/O-bound tasks — use Tokio instead.

fn section_8_rayon_explanation() {
    // Simulate embarrassingly parallel work using std threads to show the idea.
    let data: Vec<i64> = (1..=1_000_000).collect();
    let chunk_size = data.len() / 4; // split into 4 chunks for 4 threads

    let mut handles = Vec::new();
    for chunk in data.chunks(chunk_size) {
        // chunk is a &[i64] into data — move a Vec copy to avoid lifetime issues.
        let chunk_owned: Vec<i64> = chunk.to_vec();
        let h = thread::spawn(move || {
            chunk_owned.iter().sum::<i64>() // compute partial sum
        });
        handles.push(h);
    }

    let total: i64 = handles.into_iter().map(|h| h.join().unwrap()).sum();
    println!("  parallel sum 1..1_000_000 = {}", total); // 500_000_500_000
    // With rayon this would simply be: data.par_iter().sum::<i64>()
}

// ---------------------------------------------------------------------------
// Section 9: Async with Tokio (conceptual — compiles without tokio dep)
// ---------------------------------------------------------------------------

// To use async Rust in production, add to Cargo.toml:
//   [dependencies]
//   tokio = { version = "1", features = ["full"] }
//
// #[tokio::main]
// async fn main() {
//     let result = fetch_data("https://example.com").await;
//     println!("{}", result);
// }
//
// async fn fetch_data(url: &str) -> String {
//     // .await suspends this task (not the OS thread!) until the future resolves.
//     let response = reqwest::get(url).await.unwrap();
//     response.text().await.unwrap()
// }
//
// tokio::spawn: lightweight green thread (task) within the Tokio runtime.
//   let handle = tokio::spawn(async move { heavy_async_work().await });
//   handle.await.unwrap();
//
// tokio::sync::Mutex (async-aware):
//   let mutex = Arc::new(tokio::sync::Mutex::new(HashMap::new()));
//   let mut guard = mutex.lock().await; // suspends task, not OS thread
//
// tokio::select!: race multiple futures, take the first to complete.
//   tokio::select! {
//       result = read_from_db() => handle_db(result),
//       _ = tokio::time::sleep(Duration::from_secs(5)) => handle_timeout(),
//   }
//
// tokio::sync::mpsc for async channels (bounded by default → backpressure):
//   let (tx, mut rx) = tokio::sync::mpsc::channel(32);
//   tokio::spawn(async move { tx.send("msg").await.unwrap(); });
//   while let Some(msg) = rx.recv().await { process(msg); }

fn section_9_async_explanation() {
    println!("  async/await requires the Tokio runtime (see comments in source).");
    println!("  Key rule: use tokio::sync::Mutex in async, std::sync::Mutex in sync.");
    println!("  tokio::spawn for async tasks; thread::spawn for CPU work.");
}

// ---------------------------------------------------------------------------
// Section 10: Real-world — concurrent file processor
// ---------------------------------------------------------------------------

// Job description: filename to process.
#[derive(Debug, Clone)]
struct Job {
    file_name: String,
    content: String, // In production: read from disk. Inlined here for simplicity.
}

// Result of processing one file.
#[derive(Debug)]
struct JobResult {
    file_name: String,
    word_count: usize,
    char_count: usize,
}

impl JobResult {
    fn process(job: &Job) -> Self {
        // Simulate processing delay proportional to content length.
        thread::sleep(Duration::from_millis(
            (job.content.len() as u64).min(50),
        ));
        JobResult {
            file_name: job.file_name.clone(),
            word_count: job.content.split_whitespace().count(),
            char_count: job.content.chars().count(),
        }
    }
}

fn section_10_file_processor() {
    // Shared state: a results map guarded by a Mutex.
    // Arc lets the map be owned by multiple threads simultaneously.
    let results: Arc<Mutex<HashMap<String, JobResult>>> =
        Arc::new(Mutex::new(HashMap::new()));

    // Channel for sending jobs to workers.
    // bounded(8): at most 8 jobs buffered — prevents producer running
    // unboundedly ahead of workers (backpressure).
    let (job_tx, job_rx) = mpsc::sync_channel::<Job>(8);

    // Channel for receiving completion notifications from workers.
    let (done_tx, done_rx) = mpsc::channel::<String>();

    // Wrap job_rx in Arc<Mutex> so multiple workers can receive from it.
    // (mpsc::Receiver is not Clone, so we guard it instead.)
    let job_rx = Arc::new(Mutex::new(job_rx));

    const NUM_WORKERS: usize = 3;
    let mut worker_handles = Vec::new();

    for worker_id in 0..NUM_WORKERS {
        let job_rx = Arc::clone(&job_rx);
        let results = Arc::clone(&results);
        let done_tx = done_tx.clone();

        let h = thread::spawn(move || {
            loop {
                // Try to receive a job — block until one is available or channel closes.
                let job = {
                    let rx_guard = job_rx.lock().unwrap(); // acquire receiver lock
                    rx_guard.recv() // blocks; returns Err when all senders are dropped
                };

                match job {
                    Ok(job) => {
                        println!("  worker-{} processing '{}'", worker_id, job.file_name);
                        let result = JobResult::process(&job); // CPU work outside lock
                        let fname = result.file_name.clone();

                        // Lock results only long enough to insert — release immediately.
                        {
                            let mut map = results.lock().unwrap();
                            map.insert(fname.clone(), result);
                        } // map guard dropped here → mutex released

                        done_tx.send(fname).expect("reporter hung up");
                    }
                    Err(_) => {
                        // Channel closed — no more jobs; worker exits cleanly.
                        println!("  worker-{} shutting down", worker_id);
                        break;
                    }
                }
            }
        });
        worker_handles.push(h);
    }

    // Drop original done_tx so reporter can detect when all workers finish.
    drop(done_tx);

    // Reporter thread: consumes done notifications and prints progress.
    let reporter_handle = thread::spawn(move || {
        let mut completed = 0;
        for fname in done_rx {
            // Receives file names as workers complete them.
            completed += 1;
            println!("  reporter: completed '{}' (total: {})", fname, completed);
        }
        println!("  reporter: all jobs complete, processed {} files", completed);
        completed
    });

    // Produce jobs — simulated file names and contents.
    let jobs = vec![
        Job { file_name: "alpha.txt".into(), content: "hello world rust concurrency".into() },
        Job { file_name: "beta.txt".into(), content: "fearless concurrency data races".into() },
        Job { file_name: "gamma.txt".into(), content: "Arc Mutex RwLock channels".into() },
        Job { file_name: "delta.txt".into(), content: "tokio async await spawn".into() },
        Job { file_name: "epsilon.txt".into(), content: "rayon par_iter parallel sum".into() },
    ];

    for job in jobs {
        job_tx.send(job).expect("workers all died");
    }
    drop(job_tx); // signal workers: no more jobs coming

    // Wait for all workers to finish.
    for h in worker_handles {
        h.join().unwrap();
    }

    // Wait for reporter to drain its channel.
    let total_processed = reporter_handle.join().unwrap();
    println!("  total files processed: {}", total_processed);

    // Print the final aggregated results.
    println!("\n  === Processing Report ===");
    let final_results = results.lock().unwrap();
    let mut sorted: Vec<_> = final_results.values().collect();
    // Sort by file name for deterministic output (HashMap order is random).
    sorted.sort_by_key(|r| &r.file_name);
    for r in sorted {
        println!(
            "  {:15} | words: {:3} | chars: {:3}",
            r.file_name, r.word_count, r.char_count
        );
    }
}

// ---------------------------------------------------------------------------
// Section 11: Send and Sync — the compile-time thread-safety guarantees
// ---------------------------------------------------------------------------

fn section_11_send_sync() {
    // Send: safe to move to another thread.
    // Sync: safe to share a reference across threads (&T is Send if T: Sync).
    //
    // Auto-implemented by the compiler for most types.
    // Explicitly NOT implemented for:
    //   Rc<T>   — use Arc<T> instead (Rc's reference count is not atomic)
    //   Cell<T> / RefCell<T> — use Mutex<T> instead (interior mutability without sync)
    //   *mut T  — raw pointers are opt-out of safety
    //
    // You cannot accidentally pass a Rc to another thread:
    //   let rc = std::rc::Rc::new(42);
    //   thread::spawn(move || println!("{}", rc)); // COMPILE ERROR
    //   // error: `Rc<i32>` cannot be sent between threads safely
    //   // help: use Arc instead
    //
    // This is the foundation of Rust's fearless concurrency claim.
    println!("  Send/Sync traits are compiler-enforced — see source comments.");
    println!("  Rc → Arc, RefCell → Mutex: the upgrades to thread-safety are explicit.");
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

fn main() {
    println!("=== L04: Concurrency ===\n");

    println!("--- 1. Basic Thread Spawning ---");
    section_1_basic_threads();

    println!("\n--- 2. Move Closures ---");
    section_2_move_closures();

    println!("\n--- 3. Arc (Shared Ownership) ---");
    section_3_arc();

    println!("\n--- 4. Mutex (Mutual Exclusion) ---");
    section_4_mutex();

    println!("\n--- 5. RwLock (Multiple Readers) ---");
    section_5_rwlock();

    println!("\n--- 6. Channels (Message Passing) ---");
    section_6_channels();

    println!("\n--- 7. Bounded Channel (Backpressure) ---");
    section_7_bounded_channel();

    println!("\n--- 8. Data Parallelism (Rayon pattern) ---");
    section_8_rayon_explanation();

    println!("\n--- 9. Async / Tokio (conceptual) ---");
    section_9_async_explanation();

    println!("\n--- 10. Concurrent File Processor ---");
    section_10_file_processor();

    println!("\n--- 11. Send and Sync ---");
    section_11_send_sync();

    println!("\n=== Done ===");
}
