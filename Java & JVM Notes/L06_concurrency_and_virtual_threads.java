// ============================================================
// L06: Concurrency — Threads, the Memory Model, j.u.c.,
//      CompletableFuture, Virtual Threads, Scoped Values,
//      Structured Concurrency
// ============================================================
// WHAT: dev.java "Concurrency" tutorials, the Java Memory Model
//       (JLS ch. 17), and Project Loom: Thread lifecycle,
//       races and visibility, happens-before, synchronized and
//       volatile, locks (ReentrantLock, ReadWriteLock,
//       StampedLock), atomics and LongAdder, concurrent
//       collections, executors and thread pools, Future and
//       CompletableFuture composition, CountDownLatch/Semaphore/
//       CyclicBarrier/Phaser, virtual threads (JDK 21, JEP 444;
//       pinning fix JDK 24, JEP 491), ScopedValue (final JDK 25,
//       JEP 506), structured concurrency (preview, JEP 505 in 25).
// WHY:  Concurrency bugs are rare in tests and frequent in
//       production. Virtual threads changed the default answer
//       for I/O-bound services: thread-per-request is back, and
//       reactive frameworks are no longer required for scale.
// LEVEL: Advanced
// RUN:   java --enable-preview --source 25 L06_concurrency_and_virtual_threads.java
//        (preview flag needed only for StructuredTaskScope, §10)
// SOURCE: dev.java/learn/concurrency, JLS 25 ch. 17, JEP 444,
//         491, 505, 506; "Java Concurrency in Practice" (Goetz)
// ============================================================
/*
CONCEPT OVERVIEW:
    Three failure classes:
      ATOMICITY  — read-modify-write (count++) interleaves → lost updates
      VISIBILITY — one thread's write isn't seen by another (CPU caches,
                   compiler reordering) without a happens-before edge
      ORDERING   — operations appear reordered to other threads
    HAPPENS-BEFORE edges come from: unlock→later lock of the same
    monitor; volatile write→later read; Thread.start(); thread
    termination→join(); executor submit→task run; Future completion
    →get(); final fields after constructor (safe publication).
    PLATFORM threads are OS threads (~1 MB stack, thousands max).
    VIRTUAL threads are JVM-scheduled on a small carrier pool;
    millions are cheap; blocking unmounts them from the carrier.

PRODUCTION USE CASE:
    A checkout service that, per request, concurrently calls
    inventory, pricing, and fraud services with a deadline,
    cancels the siblings when one fails, propagates a request
    ID without ThreadLocal, and handles 10k concurrent requests
    on virtual threads.

COMMON MISTAKES:
    1. `volatile int count; count++` — volatile gives visibility,
       NOT atomicity. Use AtomicInteger/LongAdder or a lock.
    2. Checking then acting without a lock (`if (!map.containsKey(k))
       map.put(k, v)`) — use putIfAbsent/computeIfAbsent.
    3. Unbounded executors/queues (Executors.newCachedThreadPool,
       newFixedThreadPool's unbounded queue) under load → OOM.
    4. Swallowing InterruptedException — restore the flag:
       Thread.currentThread().interrupt().
    5. Pooling virtual threads or using them for CPU-bound work —
       create one per task; they help only when tasks block.
    6. CompletableFuture.supplyAsync without an executor uses the
       common ForkJoinPool — blocking I/O there starves everything.
    7. Lock ordering inconsistency → deadlock.
*/

import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.LongAdder;
import java.util.concurrent.locks.ReentrantLock;
import java.util.concurrent.locks.ReentrantReadWriteLock;
import java.util.concurrent.locks.StampedLock;
import java.util.stream.IntStream;

public class L06_concurrency_and_virtual_threads {

    // ========================================================
    // SECTION 1: THREADS & LIFECYCLE
    // ========================================================
    // States: NEW → RUNNABLE ⇄ (BLOCKED | WAITING | TIMED_WAITING) → TERMINATED
    static void threads() throws InterruptedException {
        Thread t = Thread.ofPlatform().name("worker-1").start(() ->       // builder API (21)
                IO.println("   running in " + Thread.currentThread().getName()));
        t.join();
        Thread sleeper = Thread.ofPlatform().unstarted(() -> {
            try { Thread.sleep(10_000); }
            catch (InterruptedException e) {
                IO.println("   interrupted → clean shutdown (flag cleared by the exception)");
                Thread.currentThread().interrupt();                          // restore for callers
            }
        });
        IO.println("   state before start: " + sleeper.getState());
        sleeper.start();
        Thread.sleep(50);
        IO.println("   state while sleeping: " + sleeper.getState());
        sleeper.interrupt();                                                 // cooperative cancellation
        sleeper.join();
        IO.println("   state after join: " + sleeper.getState());
        // Daemon threads don't keep the JVM alive. Thread.stop/suspend are
        // removed/unsupported — interruption is the only cancellation model.
    }

    // ========================================================
    // SECTION 2: RACES, synchronized, volatile, ATOMICS
    // ========================================================
    static int unsafeCount = 0;
    static int lockedCount = 0;
    static final Object LOCK = new Object();
    static final AtomicInteger atomicCount = new AtomicInteger();
    static final LongAdder adder = new LongAdder();     // striped counter: best under high contention

    static void races() throws InterruptedException {
        Runnable work = () -> {
            for (int i = 0; i < 100_000; i++) {
                unsafeCount++;                            // read, add, write — interleaves
                synchronized (LOCK) { lockedCount++; }    // mutual exclusion + visibility
                atomicCount.incrementAndGet();            // CAS loop
                adder.increment();
            }
        };
        var ts = IntStream.range(0, 4).mapToObj(i -> Thread.ofPlatform().start(work)).toList();
        for (Thread t : ts) t.join();
        IO.println("   expected 400000: unsafe=" + unsafeCount + " synchronized=" + lockedCount
                + " atomic=" + atomicCount.get() + " LongAdder=" + adder.sum());
        // CAS-based updates of arbitrary state:
        AtomicLong maxSeen = new AtomicLong();
        IntStream.of(5, 42, 17).parallel().forEach(v -> maxSeen.accumulateAndGet(v, Math::max));
        IO.println("   accumulateAndGet max=" + maxSeen.get());
    }

    // volatile: visibility + ordering for a single variable; perfect for flags.
    static volatile boolean running = true;
    static void visibility() throws InterruptedException {
        Thread spinner = Thread.ofPlatform().start(() -> {
            long spins = 0;
            while (running) spins++;                      // without volatile, JIT may hoist the read → infinite loop
            IO.println("   spinner saw running=false" + (spins > 0 ? "" : " immediately"));
        });
        Thread.sleep(20);
        running = false;
        spinner.join(2000);
    }
    // Safe publication of immutable objects: final fields are guaranteed
    // visible after the constructor — one reason records/immutables are
    // the easiest concurrent objects. Double-checked locking requires
    // `volatile` on the instance field (or use the holder-class idiom).

    // ========================================================
    // SECTION 3: EXPLICIT LOCKS
    // ========================================================
    static final class Inventory {
        private final Map<String, Integer> stock = new HashMap<>();
        private final ReentrantReadWriteLock rw = new ReentrantReadWriteLock();
        int get(String sku) {
            rw.readLock().lock();                         // many concurrent readers
            try { return stock.getOrDefault(sku, 0); } finally { rw.readLock().unlock(); }
        }
        void add(String sku, int qty) {
            rw.writeLock().lock();                        // exclusive
            try { stock.merge(sku, qty, Integer::sum); } finally { rw.writeLock().unlock(); }
        }
    }
    static final class Point {
        private double x, y;
        private final StampedLock sl = new StampedLock();
        double distanceFromOrigin() {
            long stamp = sl.tryOptimisticRead();          // no locking at all on the fast path
            double cx = x, cy = y;
            if (!sl.validate(stamp)) {                    // a write happened → fall back to a real read lock
                stamp = sl.readLock();
                try { cx = x; cy = y; } finally { sl.unlockRead(stamp); }
            }
            return Math.hypot(cx, cy);
        }
        void move(double dx, double dy) {
            long stamp = sl.writeLock();
            try { x += dx; y += dy; } finally { sl.unlockWrite(stamp); }
        }
    }
    static void locks() throws InterruptedException {
        var lock = new ReentrantLock(true);               // fair: FIFO acquisition (slower)
        if (lock.tryLock(100, TimeUnit.MILLISECONDS)) {   // timed / interruptible acquisition — synchronized can't
            try { IO.println("   tryLock acquired, holdCount=" + lock.getHoldCount()); } finally { lock.unlock(); }
        }
        var inv = new Inventory(); inv.add("A", 5); inv.add("A", 3);
        var p = new Point(); p.move(3, 4);
        IO.println("   rw-lock stock=" + inv.get("A") + " stamped distance=" + p.distanceFromOrigin());
        // Condition variables: lock.newCondition() → await()/signal(), like wait/notify
        // but multiple conditions per lock (e.g. notFull / notEmpty in a bounded buffer).
        // Deadlock avoidance: global lock ordering, tryLock with timeout, or one lock.
    }

    // ========================================================
    // SECTION 4: CONCURRENT COLLECTIONS
    // ========================================================
    //   ConcurrentHashMap       lock-striped/CAS; atomic compute/merge; never null keys/values
    //   CopyOnWriteArrayList    copy on every write; ideal for rarely-changing listener lists
    //   ConcurrentLinkedQueue   lock-free unbounded queue
    //   BlockingQueue           producer/consumer: ArrayBlockingQueue (bounded),
    //                           LinkedBlockingQueue, SynchronousQueue (hand-off),
    //                           PriorityBlockingQueue, DelayQueue
    //   ConcurrentSkipListMap   sorted, concurrent NavigableMap
    // Collections.synchronizedX wraps every method in one lock; iteration
    // still needs external synchronization — prefer the j.u.c. classes.
    static void producerConsumer() throws InterruptedException {
        BlockingQueue<String> queue = new ArrayBlockingQueue<>(2);    // bounded → backpressure
        var consumed = new CopyOnWriteArrayList<String>();
        Thread consumer = Thread.ofPlatform().start(() -> {
            try {
                while (true) {
                    String msg = queue.take();                        // blocks when empty
                    if (msg.equals("POISON")) break;                  // poison-pill shutdown
                    consumed.add(msg);
                }
            } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
        });
        for (int i = 1; i <= 5; i++) queue.put("event-" + i);         // blocks when full
        queue.put("POISON");
        consumer.join();
        IO.println("   consumed=" + consumed);
        var hits = new ConcurrentHashMap<String, LongAdder>();
        List.of("/a", "/b", "/a").parallelStream().forEach(path -> hits.computeIfAbsent(path, k -> new LongAdder()).increment());
        IO.println("   CHM hits /a=" + hits.get("/a").sum());
    }

    // ========================================================
    // SECTION 5: EXECUTORS
    // ========================================================
    // Production pool: bounded queue + named threads + rejection policy.
    static ExecutorService boundedPool() {
        return new ThreadPoolExecutor(
                4, 8,                                         // core, max
                30, TimeUnit.SECONDS,                         // idle timeout for non-core threads
                new ArrayBlockingQueue<>(100),                // BOUNDED work queue
                Thread.ofPlatform().name("checkout-", 0).factory(),
                new ThreadPoolExecutor.CallerRunsPolicy());   // backpressure: caller runs the task
    }
    // Sizing: CPU-bound ≈ #cores; I/O-bound ≈ cores × (1 + wait/compute)
    // — or just use virtual threads for I/O-bound work.
    // Executors.newFixedThreadPool(n) = unbounded queue; newCachedThreadPool =
    // unbounded threads. Fine in demos, risky under load.
    // ExecutorService is AutoCloseable since JDK 19: close() waits for tasks.

    static void executors() throws Exception {
        try (ExecutorService pool = boundedPool()) {
            Future<Integer> f = pool.submit(() -> 6 * 7);
            IO.println("   Future.get=" + f.get(1, TimeUnit.SECONDS));
            List<Callable<String>> tasks = List.of(() -> "a", () -> "b", () -> "c");
            IO.println("   invokeAll=" + pool.invokeAll(tasks).stream().map(L06_concurrency_and_virtual_threads::join).toList()
                    + " invokeAny=" + pool.invokeAny(tasks).length() + " char");
        }
        try (var sched = Executors.newSingleThreadScheduledExecutor()) {
            var ticks = new AtomicInteger();
            ScheduledFuture<?> h = sched.scheduleAtFixedRate(ticks::incrementAndGet, 0, 10, TimeUnit.MILLISECONDS);
            Thread.sleep(55);
            h.cancel(false);
            IO.println("   fixed-rate ticks in 55ms at 10ms period: " + ticks.get() + " (timing-dependent, ~6)");
        }
        // ForkJoinPool: work-stealing, for divide-and-conquer RecursiveTask;
        // backs parallel streams and default CompletableFuture async methods.
    }
    static <T> T join(Future<T> f) {
        try { return f.get(); } catch (Exception e) { throw new CompletionException(e); }
    }

    // ========================================================
    // SECTION 6: COMPLETABLEFUTURE
    // ========================================================
    static CompletableFuture<Integer> priceFor(String sku, Executor ex) {
        return CompletableFuture.supplyAsync(() -> { sleep(30); return sku.length() * 1000; }, ex);
    }
    static void completableFutures() {
        try (var ex = Executors.newVirtualThreadPerTaskExecutor()) {
            var price = priceFor("SKU-1", ex);
            var tax = CompletableFuture.supplyAsync(() -> { sleep(20); return 0.08; }, ex);
            var total = price.thenCombine(tax, (p, t) -> Math.round(p * (1 + t)))     // join two independent futures
                    .thenApply(c -> "total=" + c + "c")                              // transform
                    .orTimeout(1, TimeUnit.SECONDS)                                  // deadline (9)
                    .exceptionally(e -> "fallback price");                           // recover
            IO.println("   " + total.join());

            var failing = CompletableFuture.supplyAsync(() -> { throw new IllegalStateException("pricing down"); }, ex)
                    .handle((v, e) -> e == null ? "ok" : "handled: " + e.getCause().getMessage());
            IO.println("   " + failing.join());

            var all = CompletableFuture.allOf(priceFor("A", ex), priceFor("BB", ex));
            var first = CompletableFuture.anyOf(priceFor("CCC", ex), CompletableFuture.completedFuture(-1));
            all.join();
            IO.println("   allOf done, anyOf=" + first.join());
            // thenCompose = flatMap (chain a dependent async call);
            // thenApply vs thenApplyAsync: Async variants hop to an executor.
        }
    }

    // ========================================================
    // SECTION 7: SYNCHRONIZERS
    // ========================================================
    static void synchronizers() throws Exception {
        var ready = new CountDownLatch(3);                 // one-shot gate
        var permits = new Semaphore(2);                    // limit concurrency (e.g. DB connections)
        var maxConcurrent = new AtomicInteger(); var current = new AtomicInteger();
        try (var ex = Executors.newVirtualThreadPerTaskExecutor()) {
            for (int i = 0; i < 6; i++) {
                ex.submit(() -> {
                    permits.acquire();
                    try {
                        maxConcurrent.accumulateAndGet(current.incrementAndGet(), Math::max);
                        sleep(15);
                        current.decrementAndGet();
                    } finally { permits.release(); }
                    ready.countDown();
                    return null;
                });
            }
            ready.await(1, TimeUnit.SECONDS);
        }
        IO.println("   semaphore max concurrent=" + maxConcurrent.get() + " (limit 2), latch count=" + ready.getCount());
        // CyclicBarrier: N threads wait for each other, reusable per phase.
        // Phaser: dynamic party count, multi-phase. Exchanger: pairwise swap.
    }

    // ========================================================
    // SECTION 8: VIRTUAL THREADS (JDK 21)
    // ========================================================
    static void virtualThreads() throws InterruptedException {
        Thread vt = Thread.ofVirtual().name("vt-1").start(() -> {});
        vt.join();
        IO.println("   isVirtual=" + vt.isVirtual() + " daemon=" + vt.isDaemon());

        // 10,000 concurrent "requests", each blocking 100 ms.
        Instant start = Instant.now();
        try (var ex = Executors.newVirtualThreadPerTaskExecutor()) {
            IntStream.range(0, 10_000).forEach(i -> ex.submit(() -> { sleep(100); return i; }));
        }   // close() waits for all
        long ms = Duration.between(start, Instant.now()).toMillis();
        IO.println("   10k blocking tasks on virtual threads took ~" + (ms < 2000 ? "<2s" : ms + "ms")
                + " (platform pool of 200 would need ≥5s)");
        // Rules:
        //  - One virtual thread per task. Never pool them.
        //  - Limit access to scarce resources with a Semaphore, not pool size.
        //  - Pinning: before JDK 24, blocking inside `synchronized` pinned the
        //    carrier thread; JEP 491 (JDK 24) removed that. Native frames
        //    (JNI) still pin. Diagnose with JFR event jdk.VirtualThreadPinned.
        //  - ThreadLocals work but millions of copies are expensive → ScopedValue.
        //  - CPU-bound work gains nothing; parallel streams/FJP are still right there.
        //  - Spring Boot: spring.threads.virtual.enabled=true; Tomcat/Jetty/Helidon support them.
    }

    // ========================================================
    // SECTION 9: SCOPED VALUES (final in JDK 25, JEP 506)
    // ========================================================
    // Immutable, bounded-lifetime, inheritable-by-child-tasks context —
    // the replacement for ThreadLocal for request context.
    static final ScopedValue<String> REQUEST_ID = ScopedValue.newInstance();

    static String audit(String action) {
        return "[req=" + (REQUEST_ID.isBound() ? REQUEST_ID.get() : "none") + "] " + action;
    }
    static void scopedValues() throws Exception {
        String result = ScopedValue.where(REQUEST_ID, "r-7f3a").call(() -> {
            String inner = ScopedValue.where(REQUEST_ID, "r-nested").call(() -> audit("rebind in nested scope"));
            return audit("charge card") + " | " + inner + " | " + audit("back in outer");
        });
        IO.println("   " + result);
        IO.println("   outside scope: " + audit("background job"));
    }

    // ========================================================
    // SECTION 10: STRUCTURED CONCURRENCY (preview in JDK 25-27)
    // ========================================================
    // Treat a group of subtasks as one unit: they can't outlive the
    // scope; failure of one cancels the others; thread dumps show the
    // task tree. API (JEP 505): StructuredTaskScope.open(joiner).
    record Quote(int priceCents, boolean fraudOk, int stock) {}

    static Quote checkout(String sku, boolean fraudServiceFails) throws InterruptedException {
        try (var scope = StructuredTaskScope.open()) {              // default joiner: all must succeed, else throw
            var price = scope.fork(() -> { sleep(40); return sku.length() * 500; });
            var fraud = scope.fork(() -> {
                sleep(10);
                if (fraudServiceFails) throw new IllegalStateException("fraud service 503");
                return true;
            });
            var stock = scope.fork(() -> { sleep(30); return 12; });
            scope.join();                                           // waits; throws FailedException on first failure
            return new Quote(price.get(), fraud.get(), stock.get()); // ScopedValue bindings are inherited by forks
        }
    }
    static void structured() throws InterruptedException {
        IO.println("   " + ScopedValue.where(REQUEST_ID, "r-sc").call(() -> checkout("SKU-9", false)));
        try {
            checkout("SKU-9", true);
        } catch (StructuredTaskScope.FailedException e) {
            IO.println("   failed fast, siblings cancelled: " + e.getCause().getMessage());
        }
        // Other joiners: Joiner.anySuccessfulResultOrThrow() (race replicas,
        // first wins), Joiner.awaitAll(), allUntil(predicate); timeouts via
        // StructuredTaskScope.open(joiner, cfg -> cfg.withTimeout(Duration.ofSeconds(2))).
    }

    static void sleep(long ms) {
        try { Thread.sleep(ms); } catch (InterruptedException e) { Thread.currentThread().interrupt(); throw new CancellationException("interrupted"); }
    }

    public static void main(String[] args) throws Exception {
        IO.println("== threads"); threads();
        IO.println("== races"); races();
        IO.println("== volatile"); visibility();
        IO.println("== locks"); locks();
        IO.println("== concurrent collections"); producerConsumer();
        IO.println("== executors"); executors();
        IO.println("== CompletableFuture"); completableFutures();
        IO.println("== synchronizers"); synchronizers();
        IO.println("== virtual threads"); virtualThreads();
        IO.println("== scoped values"); scopedValues();
        IO.println("== structured concurrency"); structured();
    }
}
