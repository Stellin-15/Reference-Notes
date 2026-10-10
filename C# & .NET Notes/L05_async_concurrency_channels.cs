// ============================================================
// L05: Async/Await, Tasks, Cancellation, Channels & Threading
// ============================================================
// WHAT: Microsoft Learn "Asynchronous programming with async and
//       await", "Task-based asynchronous pattern (TAP)",
//       "Cancellation in managed threads", "Channels", "Parallel
//       programming", "Threading" and "TimeProvider": how async
//       methods compile to state machines, Task vs ValueTask,
//       ConfigureAwait and SynchronizationContext, deadlocks from
//       .Result, cancellation tokens & linked timeouts, WhenAll/
//       WhenAny/WhenEach (.NET 9), IAsyncEnumerable, producer/
//       consumer with System.Threading.Channels, Parallel.ForEach
//       vs ForEachAsync, SemaphoreSlim throttling, the new Lock
//       type (.NET 9), Interlocked, and testable time.
// WHY:  Every ASP.NET Core request, EF Core query and HttpClient
//       call is async. Getting it wrong costs either throughput
//       (blocking threads → thread-pool starvation) or correctness
//       (fire-and-forget exceptions vanish, cancellations ignored).
// LEVEL: Intermediate → Advanced
// RUN:   dotnet run L05_async_concurrency_channels.cs
// SOURCE: learn.microsoft.com/dotnet/csharp/asynchronous-programming/*,
//         /standard/asynchronous-programming-patterns/*, /standard/threading/*,
//         /core/extensions/channels, /standard/datetime/timeprovider-overview;
//         .NET 11 "Runtime Async" preview notes
// ============================================================
/*
CONCEPT OVERVIEW:
    `async` turns a method into a state machine; each `await` on
    an incomplete task registers a continuation and RETURNS the
    thread to the pool. No thread is "waiting" during I/O.
    A Task represents a future result (or exception, or
    cancellation). CPU-bound work → Task.Run / Parallel;
    I/O-bound work → async all the way, never Task.Run around I/O.
    Cancellation is cooperative: pass CancellationToken down,
    check it, or hand it to APIs that honour it.
    .NET 11 (preview, Nov 2026 STS) moves async state machines into
    the runtime ("Runtime Async") — same C#, fewer allocations.

PRODUCTION USE CASE:
    An order-enrichment worker: reads orders from a bounded
    Channel, calls three downstream services concurrently with a
    per-request timeout and a global concurrency limit, streams
    results with IAsyncEnumerable, and shuts down gracefully.

COMMON MISTAKES:
    1. `.Result` / `.Wait()` on async code ("sync over async") →
       thread-pool starvation, or deadlock under a UI/legacy ASP.NET
       SynchronizationContext.
    2. `async void` (except event handlers) — exceptions crash the
       process; callers can't await it.
    3. Fire-and-forget tasks with no exception observation.
    4. Ignoring the CancellationToken parameter you accepted.
    5. Awaiting a ValueTask twice, or storing it.
    6. Unbounded parallelism: Task.WhenAll over 100k HTTP calls.
    7. `lock` around `await` — illegal (CS1996); use SemaphoreSlim.
*/

#:property Nullable=enable
#:property InvariantGlobalization=true

using System.Collections.Concurrent;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Threading.Channels;

Console.WriteLine("== async basics"); await AsyncBasics.Run();
Console.WriteLine("== composition"); await Composition.Run();
Console.WriteLine("== cancellation & timeouts"); await CancellationDemo.Run();
Console.WriteLine("== async streams"); await StreamsDemo.Run();
Console.WriteLine("== channels"); await ChannelsDemo.Run();
Console.WriteLine("== parallelism & synchronization"); await ParallelDemo.Run();
Console.WriteLine("== end-to-end: enrichment worker"); await EnrichmentWorker.Run();

// ============================================================
// SECTION 1: ASYNC BASICS, Task vs ValueTask, ConfigureAwait
// ============================================================
static class AsyncBasics
{
    static async Task<int> GetStockAsync(string sku)
    {
        await Task.Delay(20);                                   // simulated I/O: no thread blocked
        return sku.Length * 10;
    }

    // ValueTask: avoid a Task allocation when the result is often synchronous (cache hit).
    static readonly Dictionary<string, decimal> Cache = new() { ["A"] = 9.99m };
    static ValueTask<decimal> GetPriceAsync(string sku) =>
        Cache.TryGetValue(sku, out var p) ? ValueTask.FromResult(p) : new ValueTask<decimal>(LoadPriceAsync(sku));
    static async Task<decimal> LoadPriceAsync(string sku) { await Task.Delay(10); return Cache[sku] = 1.5m; }

    public static async Task Run()
    {
        int tid = Environment.CurrentManagedThreadId;
        int stock = await GetStockAsync("SKU-1");
        Console.WriteLine($"   stock={stock}; resumed on thread {(Environment.CurrentManagedThreadId == tid ? "same" : "a different pool")} thread (no SynchronizationContext in console/ASP.NET Core)");
        Console.WriteLine($"   ValueTask hit={await GetPriceAsync("A")} miss={await GetPriceAsync("B")}");

        // Exceptions are captured in the Task and rethrown at await.
        Task faulty = Task.Run(() => throw new InvalidOperationException("boom"));
        try { await faulty; } catch (InvalidOperationException e) { Console.WriteLine($"   awaited exception: {e.Message}, task status={faulty.Status}"); }

        // ConfigureAwait(false): don't resume on the captured context. Matters in
        // LIBRARIES (callers may be WPF/WinForms/MAUI/legacy ASP.NET). ASP.NET Core
        // has no SynchronizationContext, so app code usually doesn't need it.
        await Task.Delay(1).ConfigureAwait(false);
        // .NET 8: ConfigureAwait(ConfigureAwaitOptions.SuppressThrowing | ForceYielding).

        // Task.Run = queue CPU-bound work to the thread pool:
        long primes = await Task.Run(() => Enumerable.Range(2, 50_000).Count(IsPrime));
        Console.WriteLine($"   CPU-bound via Task.Run: {primes} primes < 50002");
        // State machine: the compiler rewrites the method into a struct implementing
        // IAsyncStateMachine with MoveNext(); locals become fields; each await is a state.
    }
    static bool IsPrime(int n) { for (int d = 2; d * d <= n; d++) if (n % d == 0) return false; return true; }
}

// ============================================================
// SECTION 2: COMPOSITION — WhenAll, WhenAny, WhenEach
// ============================================================
static class Composition
{
    static async Task<string> Call(string name, int ms, bool fail = false)
    {
        await Task.Delay(ms);
        return fail ? throw new HttpRequestException($"{name} 503") : $"{name}:{ms}ms";
    }

    public static async Task Run()
    {
        var sw = Stopwatch.StartNew();
        // Start all FIRST, then await — concurrency comes from not awaiting one by one.
        Task<string> inventory = Call("inventory", 60), pricing = Call("pricing", 40), fraud = Call("fraud", 50);
        string[] all = await Task.WhenAll(inventory, pricing, fraud);
        Console.WriteLine($"   WhenAll: [{string.Join(", ", all)}] in ~{Round(sw.ElapsedMilliseconds)}ms (max, not sum)");

        // WhenAll with failures: `await` throws the FIRST; inspect each task for the rest.
        var batch = new[] { Call("a", 10), Call("b", 10, fail: true), Call("c", 10, fail: true) };
        try { await Task.WhenAll(batch); }
        catch (HttpRequestException e) { Console.WriteLine($"   first error: {e.Message}; all errors: {string.Join(",", batch.Where(t => t.IsFaulted).Select(t => t.Exception!.InnerException!.Message))}"); }

        // WhenAny: hedged requests — first replica to answer wins.
        Task<string> winner = await Task.WhenAny(Call("replica-eu", 80), Call("replica-us", 30));
        Console.WriteLine($"   WhenAny winner: {await winner}");

        // WhenEach (.NET 9): process results in COMPLETION order.
        var order = new List<string>();
        await foreach (Task<string> done in Task.WhenEach(Call("slow", 50), Call("fast", 10), Call("mid", 30)))
            order.Add((await done).Split(':')[0]);
        Console.WriteLine($"   WhenEach completion order: {string.Join(" → ", order)}");
    }
    static long Round(long ms) => (ms + 5) / 10 * 10;
}

// ============================================================
// SECTION 3: CANCELLATION & TIMEOUTS
// ============================================================
static class CancellationDemo
{
    static async Task<int> SlowQueryAsync(CancellationToken ct)
    {
        for (int i = 0; i < 10; i++)
        {
            ct.ThrowIfCancellationRequested();                   // cooperative check for CPU loops
            await Task.Delay(50, ct);                            // pass the token to every async API
        }
        return 42;
    }

    public static async Task Run()
    {
        using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(120));   // auto-cancel timeout
        try { await SlowQueryAsync(cts.Token); }
        catch (OperationCanceledException) { Console.WriteLine("   query cancelled by 120ms timeout"); }

        // Linked tokens: cancel if EITHER the caller cancels OR our own deadline passes.
        using var shutdown = new CancellationTokenSource();
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(shutdown.Token);
        linked.CancelAfter(TimeSpan.FromSeconds(5));
        shutdown.CancelAfter(30);
        try { await SlowQueryAsync(linked.Token); }
        catch (OperationCanceledException) { Console.WriteLine($"   linked: cancelled because shutdown={shutdown.IsCancellationRequested}"); }

        // WaitAsync (.NET 6): put a timeout on a task that takes no token.
        try { await Task.Delay(1000).WaitAsync(TimeSpan.FromMilliseconds(20)); }
        catch (TimeoutException) { Console.WriteLine("   WaitAsync → TimeoutException (the underlying work keeps running!)"); }

        // Register callbacks (e.g., close a socket) when cancellation happens:
        using var cts2 = new CancellationTokenSource();
        using var reg = cts2.Token.Register(() => Console.WriteLine("   cancellation callback ran"));
        cts2.Cancel();
    }
}

// ============================================================
// SECTION 4: ASYNC STREAMS (IAsyncEnumerable)
// ============================================================
static class StreamsDemo
{
    // Producer: yields items as they arrive; [EnumeratorCancellation] wires
    // the token passed via WithCancellation().
    static async IAsyncEnumerable<int> PagesAsync([EnumeratorCancellation] CancellationToken ct = default)
    {
        for (int page = 1; page <= 5; page++)
        {
            await Task.Delay(10, ct);
            yield return page;
        }
    }

    public static async Task Run()
    {
        var got = new List<int>();
        using var cts = new CancellationTokenSource();
        await foreach (var p in PagesAsync().WithCancellation(cts.Token))
        {
            got.Add(p);
            if (p == 3) cts.Cancel();                           // stop early
            if (cts.IsCancellationRequested) break;
        }
        Console.WriteLine($"   pages consumed: {string.Join(",", got)}");
        // System.Linq.AsyncEnumerable (.NET 10 in-box): Where/Select/ToListAsync on async streams.
        var evens = await PagesAsync().Where(p => p % 2 == 0).ToListAsync();
        Console.WriteLine($"   AsyncEnumerable LINQ: {string.Join(",", evens)}");
        // EF Core: context.Orders.AsAsyncEnumerable(); ASP.NET Core can return
        // IAsyncEnumerable<T> from an endpoint and stream JSON.
    }
}

// ============================================================
// SECTION 5: CHANNELS — producer/consumer pipelines
// ============================================================
static class ChannelsDemo
{
    public static async Task Run()
    {
        // Bounded = backpressure: writers wait when consumers fall behind.
        var channel = Channel.CreateBounded<int>(new BoundedChannelOptions(capacity: 4)
        {
            FullMode = BoundedChannelFullMode.Wait,               // or DropOldest/DropNewest/DropWrite
            SingleReader = false, SingleWriter = true,
        });

        var producer = Task.Run(async () =>
        {
            for (int i = 1; i <= 20; i++) await channel.Writer.WriteAsync(i);
            channel.Writer.Complete();                            // signals "no more items"
        });

        var results = new ConcurrentBag<int>();
        var consumers = Enumerable.Range(0, 3).Select(_ => Task.Run(async () =>
        {
            await foreach (var item in channel.Reader.ReadAllAsync()) // ends when completed & drained
            {
                await Task.Delay(2);
                results.Add(item * item);
            }
        })).ToArray();

        await Task.WhenAll(consumers.Append(producer));
        Console.WriteLine($"   3 consumers processed {results.Count} items, sum of squares={results.Sum()}");
        // Channels vs BlockingCollection: channels are async-native and faster.
        // Hosted BackgroundService + Channel is the standard in-process queue in ASP.NET Core.
    }
}

// ============================================================
// SECTION 6: PARALLELISM & SYNCHRONIZATION PRIMITIVES
// ============================================================
static class ParallelDemo
{
    static readonly Lock Gate = new();                           // .NET 9 System.Threading.Lock (faster than lock(object))
    static long _locked, _interlocked;

    public static async Task Run()
    {
        // CPU-bound data parallelism:
        var counts = new int[4];
        Parallel.For(0, 1_000_000, new ParallelOptions { MaxDegreeOfParallelism = Environment.ProcessorCount },
            i => Interlocked.Increment(ref counts[i % 4]));
        Console.WriteLine($"   Parallel.For buckets: {string.Join(",", counts)}");

        // I/O-bound with a concurrency cap:
        int inFlight = 0, peak = 0;
        await Parallel.ForEachAsync(Enumerable.Range(0, 20), new ParallelOptions { MaxDegreeOfParallelism = 4 }, async (i, ct) =>
        {
            int now = Interlocked.Increment(ref inFlight);
            InterlockedMax(ref peak, now);
            await Task.Delay(10, ct);
            Interlocked.Decrement(ref inFlight);
        });
        Console.WriteLine($"   ForEachAsync peak concurrency={peak} (cap 4)");

        // lock vs Interlocked
        Parallel.For(0, 100_000, _ => { lock (Gate) { _locked++; } Interlocked.Increment(ref _interlocked); });
        Console.WriteLine($"   lock={_locked} interlocked={_interlocked}");

        // SemaphoreSlim: async-compatible mutual exclusion / throttling (can't `await` inside `lock`).
        var sem = new SemaphoreSlim(2);
        int maxSeen = 0, current = 0;
        await Task.WhenAll(Enumerable.Range(0, 8).Select(async _ =>
        {
            await sem.WaitAsync();
            try { InterlockedMax(ref maxSeen, Interlocked.Increment(ref current)); await Task.Delay(5); Interlocked.Decrement(ref current); }
            finally { sem.Release(); }
        }));
        Console.WriteLine($"   SemaphoreSlim max concurrent={maxSeen}");
        // Others: ReaderWriterLockSlim, Monitor.Wait/Pulse, ManualResetEventSlim,
        // CountdownEvent, Barrier, AsyncLocal<T> (flows with async context — used for
        // logging scopes/Activity), ThreadLocal<T>, volatile & Volatile.Read/Write.
    }
    static void InterlockedMax(ref int target, int value)
    {
        int seen;
        while ((seen = Volatile.Read(ref target)) < value && Interlocked.CompareExchange(ref target, value, seen) != seen) { }
    }
}

// ============================================================
// SECTION 7: END-TO-END — ENRICHMENT WORKER with TimeProvider
// ============================================================
static class EnrichmentWorker
{
    sealed record Order(int Id, string Sku);
    sealed record Enriched(int Id, int Stock, decimal Price, string Risk, double LatencyMs);

    // TimeProvider (.NET 8): inject time → tests use FakeTimeProvider
    // (Microsoft.Extensions.TimeProvider.Testing) to control timers & now.
    sealed class Services(TimeProvider time)
    {
        public async Task<int> Stock(string sku, CancellationToken ct) { await Task.Delay(TimeSpan.FromMilliseconds(15), time, ct); return sku.Length; }
        public async Task<decimal> Price(string sku, CancellationToken ct) { await Task.Delay(TimeSpan.FromMilliseconds(25), time, ct); return 10m + sku.Length; }
        public async Task<string> Risk(int id, CancellationToken ct)
        {
            // Order 7 hits a slow fraud service → must be cut off by the per-order timeout.
            await Task.Delay(TimeSpan.FromMilliseconds(id == 7 ? 500 : 20), time, ct);
            return id % 5 == 0 ? "review" : "low";
        }
    }

    public static async Task Run()
    {
        var time = TimeProvider.System;
        var svc = new Services(time);
        var input = Channel.CreateBounded<Order>(16);
        var output = Channel.CreateUnbounded<Enriched>();
        using var shutdown = new CancellationTokenSource();
        var throttle = new SemaphoreSlim(4);                     // global downstream concurrency limit

        var workers = Enumerable.Range(0, 4).Select(_ => Task.Run(async () =>
        {
            await foreach (var order in input.Reader.ReadAllAsync(shutdown.Token))
            {
                await throttle.WaitAsync(shutdown.Token);
                long start = time.GetTimestamp();
                try
                {
                    using var perOrder = CancellationTokenSource.CreateLinkedTokenSource(shutdown.Token);
                    perOrder.CancelAfter(TimeSpan.FromMilliseconds(150));   // per-request deadline
                    var stock = svc.Stock(order.Sku, perOrder.Token);
                    var price = svc.Price(order.Sku, perOrder.Token);
                    var risk = svc.Risk(order.Id, perOrder.Token);
                    await Task.WhenAll(stock, price, risk);
                    await output.Writer.WriteAsync(new Enriched(order.Id, stock.Result, price.Result, risk.Result,
                        time.GetElapsedTime(start).TotalMilliseconds), shutdown.Token);
                }
                catch (OperationCanceledException) when (!shutdown.IsCancellationRequested)
                {
                    await output.Writer.WriteAsync(new Enriched(order.Id, -1, 0, "timeout", time.GetElapsedTime(start).TotalMilliseconds));
                }
                finally { throttle.Release(); }
            }
        })).ToArray();

        for (int i = 1; i <= 10; i++) await input.Writer.WriteAsync(new Order(i, "SKU-" + new string('x', i % 3)));
        input.Writer.Complete();
        await Task.WhenAll(workers);
        output.Writer.Complete();

        var results = new List<Enriched>();
        await foreach (var e in output.Reader.ReadAllAsync()) results.Add(e);
        foreach (var e in results.OrderBy(r => r.Id))
            Console.WriteLine($"   order {e.Id,2}: stock={e.Stock,2} price={e.Price,5} risk={e.Risk,-7} {(e.LatencyMs < 100 ? "<100ms" : e.LatencyMs < 200 ? "~150ms (deadline)" : "slow")}");
        // In ASP.NET Core this is a BackgroundService; graceful shutdown comes from
        // IHostApplicationLifetime / the stoppingToken passed to ExecuteAsync.
        // Resilience: Microsoft.Extensions.Http.Resilience (Polly v8) adds retry,
        // circuit breaker, hedging and timeouts to HttpClient pipelines (L07).
    }
}
