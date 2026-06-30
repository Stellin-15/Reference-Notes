# ============================================================
# L05: Concurrency
# ============================================================
# WHAT: threading, multiprocessing (Pool, Queue, shared memory),
#       asyncio (event loop, coroutines, tasks, gather, Queue,
#       semaphores), concurrent.futures, and when to use each.
# WHY:  Modern services are I/O-bound (network, DB, disk).
#       Concurrency is mandatory at scale. Choosing the wrong
#       model leads to deadlocks, race conditions, or GIL-limited
#       performance. This lesson prevents those mistakes.
# LEVEL: Advanced → Architecture
# ============================================================

"""
CONCEPT OVERVIEW:
    Python has three concurrency models:
    1. threading    — shared memory, GIL limits CPU parallelism
    2. multiprocessing — separate processes, true CPU parallelism
    3. asyncio      — cooperative multitasking, no OS threads

    Decision matrix:
    ┌─────────────────────────────┬─────────────────────────────┐
    │ Workload                    │ Use                         │
    ├─────────────────────────────┼─────────────────────────────┤
    │ I/O-bound, moderate scale   │ threading or asyncio        │
    │ I/O-bound, high scale       │ asyncio (10k+ connections)  │
    │ CPU-bound                   │ multiprocessing             │
    │ Mixed (I/O + CPU)           │ asyncio + ProcessPoolExec.  │
    │ Simple parallelism          │ concurrent.futures          │
    └─────────────────────────────┴─────────────────────────────┘

PRODUCTION USE CASE:
    - Web scraper: asyncio with semaphore for 1000 concurrent requests
    - Image processor: multiprocessing.Pool for CPU-bound resize
    - Background job queue: threading.Thread + queue.Queue
    - Microservice: asyncio (FastAPI/aiohttp) + ProcessPoolExecutor

COMMON MISTAKES:
    - Sharing mutable state between threads without locks
    - Using threads for CPU-bound work (GIL prevents speedup)
    - Blocking the asyncio event loop with time.sleep or requests
    - Not cancelling asyncio tasks — they linger and leak resources
    - Using multiprocessing with unpicklable objects
"""

import time
import queue
import asyncio
import threading
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from typing import List, Any, Callable

# ============================================================
# SECTION 1: threading — I/O-Bound Work
# ============================================================
# WHAT: OS threads sharing memory space. The GIL is released
#       during I/O (network, disk), so threads genuinely
#       speed up I/O-bound work.
# WHY:  Threads are simpler than asyncio for small-scale I/O
#       parallelism. Downside: shared state needs explicit locking.
# COMMON MISTAKE: No lock around shared state → race condition.

print("=== threading: I/O-Bound ===")

def simulate_api_call(url: str, results: list, lock: threading.Lock) -> None:
    """Simulate an HTTP GET — GIL released during actual I/O."""
    time.sleep(0.05)     # simulates network latency
    with lock:           # lock protects shared `results` list
        results.append(f"response from {url}")

urls = [f"https://api.example.com/item/{i}" for i in range(10)]
results = []
lock = threading.Lock()

start = time.perf_counter()
threads = [threading.Thread(target=simulate_api_call, args=(url, results, lock))
           for url in urls]
for t in threads: t.start()
for t in threads: t.join()
elapsed = time.perf_counter() - start

print(f"  {len(results)} responses in {elapsed*1000:.0f}ms (serial would be ~500ms)")

# ============================================================
# SECTION 2: threading.Event, Condition, Semaphore
# ============================================================
# WHAT: Synchronization primitives for coordinating threads.
# WHY:  Without these, concurrent access to shared state causes
#       data corruption, missed signals, and deadlocks.

print("\n=== Thread Synchronization ===")

# threading.Event: signal between threads (producer/consumer)
ready_event = threading.Event()
result_holder = []

def producer():
    time.sleep(0.02)
    result_holder.append(42)
    ready_event.set()     # signal consumers

def consumer():
    ready_event.wait()    # block until event is set
    print(f"  consumer received: {result_holder[0]}")

p = threading.Thread(target=producer)
c = threading.Thread(target=consumer)
c.start(); p.start()
p.join(); c.join()

# threading.Semaphore: limit concurrent access
# Production use: connection pool limiting, rate limiting
semaphore = threading.Semaphore(3)   # max 3 concurrent workers

def rate_limited_worker(worker_id: int):
    with semaphore:      # acquires slot, releases on exit
        time.sleep(0.01)
        # At most 3 workers execute simultaneously

workers = [threading.Thread(target=rate_limited_worker, args=(i,))
           for i in range(10)]
for w in workers: w.start()
for w in workers: w.join()
print("  Semaphore-limited workers completed")

# ============================================================
# SECTION 3: queue.Queue — Thread-Safe Producer/Consumer
# ============================================================
# WHAT: queue.Queue is a thread-safe FIFO queue. It handles
#       its own locking internally.
# WHY:  The classic pattern for distributing work to a thread pool.
#       Background job systems (Celery workers, etc.) use this model.

print("\n=== queue.Queue: Producer/Consumer ===")

def worker_thread(q: queue.Queue, worker_id: int, output: list):
    while True:
        item = q.get()
        if item is None:   # sentinel value signals shutdown
            q.task_done()
            break
        output.append(f"worker-{worker_id} processed {item}")
        q.task_done()

work_queue = queue.Queue(maxsize=50)   # bounded: prevents runaway memory
processed  = []
n_workers  = 4

pool = [threading.Thread(target=worker_thread, args=(work_queue, i, processed))
        for i in range(n_workers)]
for t in pool: t.start()

for i in range(20):
    work_queue.put(i)

for _ in range(n_workers):
    work_queue.put(None)    # one sentinel per worker

work_queue.join()           # wait for all items to be processed
for t in pool: t.join()

print(f"  Processed {len(processed)} items via thread pool")

# ============================================================
# SECTION 4: multiprocessing — CPU-Bound Work
# ============================================================
# WHAT: Spawns separate Python interpreter processes with separate
#       memory spaces and GILs. True CPU parallelism.
# WHY:  The ONLY way to achieve CPU parallelism in CPython.
#       NumPy releases the GIL for some ops, but general Python
#       code needs multiprocessing.
# COMMON MISTAKE: On Windows, multiprocessing code must be inside
#   `if __name__ == '__main__':` to prevent recursive spawning.

print("\n=== multiprocessing: CPU-Bound ===")

def cpu_task(n: int) -> int:
    """CPU-bound: sum of squares."""
    return sum(i * i for i in range(n))

# Use Pool.map for simple parallelism
inputs = [500_000] * 4   # 4 tasks

# Single-process baseline
start = time.perf_counter()
serial_results = [cpu_task(n) for n in inputs]
serial_time = time.perf_counter() - start
print(f"  Serial     (4 tasks): {serial_time*1000:.0f}ms")

# Multiprocessing pool
# NOTE: On Windows, Pool must be guarded by if __name__ == '__main__'
#       This demo calls it directly — works in module context.
try:
    with mp.Pool(processes=min(4, mp.cpu_count())) as pool:
        start = time.perf_counter()
        parallel_results = pool.map(cpu_task, inputs)
        parallel_time = time.perf_counter() - start
    print(f"  Parallel   (4 tasks): {parallel_time*1000:.0f}ms")
    print(f"  Speedup: {serial_time/parallel_time:.1f}x  (on {mp.cpu_count()} cores)")
except Exception as e:
    print(f"  Pool demo skipped in interactive mode: {e}")

# Pool.imap_unordered: streaming results (lower memory for large inputs)
def process_chunk(chunk: list) -> list:
    return [x * 2 for x in chunk]

# multiprocessing.Queue for inter-process communication
def producer_proc(q: mp.Queue):
    for i in range(5):
        q.put(i)
    q.put(None)  # sentinel

def consumer_proc(q: mp.Queue, results: mp.Queue):
    while True:
        item = q.get()
        if item is None:
            break
        results.put(item * item)

# ============================================================
# SECTION 5: asyncio — Event Loop and Coroutines
# ============================================================
# WHAT: asyncio uses a single-threaded event loop with cooperative
#       multitasking. `await` suspends a coroutine and yields
#       control back to the event loop.
# WHY:  Can handle 10,000+ concurrent connections in a single thread.
#       No OS thread overhead, no GIL contention, no race conditions
#       on most operations (single-threaded).
# CRITICAL: NEVER call blocking code (time.sleep, requests.get,
#       file I/O without aiofiles) in async functions.
#       Use `await asyncio.sleep()` and `aiohttp` instead.

print("\n=== asyncio: Event Loop ===")

async def fetch_data(url: str, semaphore: asyncio.Semaphore) -> dict:
    """Simulate async HTTP fetch with concurrency limit."""
    async with semaphore:             # limit to N concurrent requests
        await asyncio.sleep(0.05)     # simulate network I/O (non-blocking)
        return {"url": url, "status": 200}

async def fetch_all(urls: List[str], max_concurrent: int = 10) -> List[dict]:
    """Fetch all URLs concurrently, max N at a time."""
    semaphore = asyncio.Semaphore(max_concurrent)
    tasks = [asyncio.create_task(fetch_data(url, semaphore)) for url in urls]
    # asyncio.gather preserves order; asyncio.as_completed gives results as ready
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if not isinstance(r, Exception)]

async def main_async():
    urls = [f"https://api.example.com/item/{i}" for i in range(20)]

    start = time.perf_counter()
    results = await fetch_all(urls, max_concurrent=10)
    elapsed = time.perf_counter() - start

    print(f"  Fetched {len(results)} URLs in {elapsed*1000:.0f}ms")
    print(f"  Serial would take ~{len(urls) * 50}ms")

asyncio.run(main_async())

# ============================================================
# SECTION 6: asyncio.Queue — Async Producer/Consumer
# ============================================================

async def async_producer(q: asyncio.Queue, n: int):
    for i in range(n):
        await q.put(i)
        await asyncio.sleep(0)   # yield to event loop

async def async_consumer(q: asyncio.Queue, results: list, worker_id: int):
    while True:
        try:
            item = await asyncio.wait_for(q.get(), timeout=0.5)
            results.append(f"w{worker_id}:{item}")
            q.task_done()
        except asyncio.TimeoutError:
            break

async def async_pipeline():
    q = asyncio.Queue(maxsize=10)
    results = []
    producer = asyncio.create_task(async_producer(q, 10))
    consumers = [asyncio.create_task(async_consumer(q, results, i))
                 for i in range(3)]
    await asyncio.gather(producer, *consumers)
    return results

pipeline_results = asyncio.run(async_pipeline())
print(f"\n  Async pipeline processed {len(pipeline_results)} items")

# ============================================================
# SECTION 7: asyncio Task Management
# ============================================================

async def cancellable_task(name: str, duration: float):
    try:
        print(f"  [{name}] starting (will run {duration}s)")
        await asyncio.sleep(duration)
        return f"{name} completed"
    except asyncio.CancelledError:
        print(f"  [{name}] was cancelled — cleaning up")
        raise    # ALWAYS re-raise CancelledError

async def task_management_demo():
    # Create tasks explicitly for fine-grained control
    t1 = asyncio.create_task(cancellable_task("fast", 0.01))
    t2 = asyncio.create_task(cancellable_task("slow", 10.0))

    await asyncio.sleep(0.05)  # let fast task finish

    # Cancel the slow task — important for shutdown/timeout
    t2.cancel()

    results = await asyncio.gather(t1, t2, return_exceptions=True)
    for r in results:
        if isinstance(r, asyncio.CancelledError):
            print("  gathered: task was cancelled")
        else:
            print(f"  gathered: {r}")

print("\n=== asyncio Task Cancellation ===")
asyncio.run(task_management_demo())

# ============================================================
# SECTION 8: concurrent.futures — Unified Interface
# ============================================================
# WHAT: High-level interface over both thread and process pools.
#       ThreadPoolExecutor: I/O-bound
#       ProcessPoolExecutor: CPU-bound
# WHY:  Simpler API than raw threading/multiprocessing.
#       submit() returns a Future; as_completed() for streaming results.

print("\n=== concurrent.futures ===")

def io_task(n: int) -> str:
    time.sleep(0.02)
    return f"result-{n}"

# ThreadPoolExecutor: I/O-bound
with ThreadPoolExecutor(max_workers=5) as executor:
    start = time.perf_counter()
    futures = {executor.submit(io_task, i): i for i in range(10)}
    results = []
    for future in as_completed(futures):
        try:
            results.append(future.result())
        except Exception as e:
            results.append(f"error: {e}")
    elapsed = time.perf_counter() - start

print(f"  ThreadPoolExecutor: {len(results)} tasks in {elapsed*1000:.0f}ms")

# executor.map: simpler but blocks until all done
with ThreadPoolExecutor(max_workers=5) as executor:
    mapped = list(executor.map(io_task, range(5), timeout=10))
print(f"  executor.map: {len(mapped)} results")

# ============================================================
# SECTION 9: asyncio + ProcessPoolExecutor for Mixed Workloads
# ============================================================
# WHAT: Run CPU-bound code in a process pool from an async context.
# WHY:  Web servers (FastAPI) are async but sometimes need CPU work
#       (image resize, ML inference). This pattern bridges both.

def cpu_intensive(n: int) -> int:
    """Pure CPU work — runs in subprocess."""
    return sum(i * i for i in range(n))

async def mixed_workload():
    loop = asyncio.get_event_loop()
    # Run_in_executor bridges sync code into the event loop
    with ProcessPoolExecutor(max_workers=2) as pool:
        # Non-blocking: event loop can handle other I/O while CPU works
        result = await loop.run_in_executor(pool, cpu_intensive, 100_000)
    return result

print("\n=== asyncio + ProcessPoolExecutor ===")
result = asyncio.run(mixed_workload())
print(f"  CPU task result (in subprocess): {result}")

# ============================================================
# SECTION 10: Decision Summary
# ============================================================
print("\n=== Concurrency Decision Guide ===")
print("""
  Situation                          → Solution
  ──────────────────────────────────────────────────────────────
  Many network/DB calls, moderate    → ThreadPoolExecutor
  Many network/DB calls, high scale  → asyncio + aiohttp/asyncpg
  CPU-bound (image proc, ML, crypto) → ProcessPoolExecutor
  Background jobs, simple queue      → threading.Thread + queue.Queue
  CPU + I/O in same service          → asyncio + run_in_executor(ProcessPool)
  Shared state between workers       → multiprocessing.Manager / Queue
  Limit concurrency (rate limit)     → asyncio.Semaphore / threading.Semaphore
  One-shot parallel map              → Pool.map or executor.map
  Streaming results as ready         → as_completed() or imap_unordered
  ──────────────────────────────────────────────────────────────
  GOLDEN RULE: asyncio for I/O, multiprocessing for CPU.
  Never block the event loop. Never use threads for CPU work.
""")
