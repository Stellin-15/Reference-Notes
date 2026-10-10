// ============================================================
// L06: The .NET Runtime — IL & JIT, Garbage Collection,
//      Disposal, Reflection & Attributes, Source Generators,
//      Native AOT & Trimming, Interop, Diagnostics
// ============================================================
// WHAT: Microsoft Learn ".NET runtime / CLR overview", "Managed
//       execution process", "Garbage collection" (fundamentals,
//       workstation vs server, background GC, LOH/POH, DATAS),
//       "Implement a Dispose method", "Reflection", "Attributes",
//       "Source generators", "Native AOT deployment", "Trimming",
//       "Native interoperability" (P/Invoke, LibraryImport),
//       "AssemblyLoadContext", and ".NET diagnostics tools".
// WHY:  When a .NET service leaks memory, pauses for GC, starts
//       slowly in a container, or breaks after enabling AOT,
//       the fix lives in this layer. Source generators replaced
//       most runtime reflection in modern .NET — it's how
//       System.Text.Json, logging and regex got AOT-safe and fast.
// LEVEL: Advanced → Architect
// RUN:   dotnet run L06_runtime_gc_reflection_interop.cs
// SOURCE: learn.microsoft.com/dotnet/standard/clr, /standard/garbage-collection/*,
//         /standard/managed-execution-process, /core/deploying/native-aot/*,
//         /standard/native-interop/*, /csharp/advanced-topics/reflection-and-attributes/*,
//         /core/diagnostics/*, .NET 9/10 performance blog posts
// ============================================================
/*
CONCEPT OVERVIEW:
    Build: C# → Roslyn → IL + metadata in an assembly (.dll).
    Run:   CLR loads assemblies → JIT compiles methods on first call.
      Tiered compilation: Tier0 (fast, unoptimised) → hot methods
      recompiled at Tier1 with Dynamic PGO (on by default since
      .NET 8) using real runtime profiles; OSR swaps long-running
      loops mid-execution. ReadyToRun (R2R) ships precompiled code;
      Native AOT compiles everything ahead of time (no JIT at all).
    GC: generational (Gen0 → Gen1 → Gen2), compacting, with a
      Large Object Heap (≥ 85,000 bytes, Gen2-collected, not
      compacted by default) and a Pinned Object Heap (.NET 5).

PRODUCTION USE CASE:
    A containerised API: tune GC mode for the CPU limit, find a
    leak with dotnet-counters + dotnet-gcdump, make startup fast
    with Native AOT, call a native library via LibraryImport, and
    replace reflection-based mapping with a source generator.

COMMON MISTAKES:
    1. Calling GC.Collect() to "fix" memory. Find the root holding
       the objects instead (event handlers, static caches, timers).
    2. Implementing a finalizer on a class that only holds managed
       resources — finalizers delay collection by a GC cycle.
    3. Forgetting Dispose on HttpResponseMessage, streams, DB
       connections, CancellationTokenSource with timers.
    4. Allocating big temporary arrays (≥ 85 KB) per request → LOH
       churn and Gen2 GCs. Pool them (ArrayPool, L04).
    5. Turning on Native AOT/trimming without fixing IL2026/IL3050
       warnings — reflection silently breaks at runtime.
    6. Server GC in a 1-CPU container with many replicas (memory
       bloat) — or Workstation GC on a 32-core box (throughput).
*/

#:property Nullable=enable
#:property InvariantGlobalization=true
#:property AllowUnsafeBlocks=true

using System.Diagnostics;
using System.Diagnostics.CodeAnalysis;
using System.Reflection;
using System.Runtime;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Runtime.Loader;

Console.WriteLine("== runtime & JIT"); RuntimeInfo.Run();
Console.WriteLine("== garbage collection"); GcDemo.Run();
Console.WriteLine("== disposal & finalization"); DisposalDemo.Run();
Console.WriteLine("== reflection & attributes"); ReflectionDemo.Run();
Console.WriteLine("== interop"); InteropDemo.Run();
Console.WriteLine("== assembly loading"); LoadingDemo.Run();

// ============================================================
// SECTION 1: RUNTIME INFO, TIERED JIT, DYNAMIC PGO
// ============================================================
static class RuntimeInfo
{
    [MethodImpl(MethodImplOptions.NoInlining)]
    static long Work(int n) { long s = 0; for (int i = 0; i < n; i++) s += i ^ (i >> 3); return s; }

    public static void Run()
    {
        Console.WriteLine($"   {RuntimeInformation.FrameworkDescription} on {RuntimeInformation.OSDescription.Split(' ')[0]} {RuntimeInformation.ProcessArchitecture}, "
            + $"dynamic code supported={RuntimeFeature.IsDynamicCodeSupported}");
        // NOTE: .NET 10 FILE-BASED APPS default to <PublishAot>true</PublishAot>, which also
        // turns on the trimming/AOT analyzers during `dotnet run` and reports dynamic code as
        // unsupported — so this file is checked as if it will be AOT-published.
        var sw = Stopwatch.StartNew(); Work(2_000_000); var cold = sw.Elapsed.TotalMicroseconds;
        for (int i = 0; i < 200; i++) Work(10_000);              // trigger tier-up (call count ≥ 30 + backedge counting)
        Thread.Sleep(150);                                        // tiering happens on a background thread
        sw.Restart(); Work(2_000_000); var warm = sw.Elapsed.TotalMicroseconds;
        Console.WriteLine($"   2M-iteration loop: first call ≈ {cold:F0}µs, after tier-up ≈ {warm:F0}µs "
            + "(often similar: OSR already optimised the hot loop DURING the first call)");
        // Knobs (csproj or env DOTNET_*): TieredCompilation, TieredPGO, ReadyToRun,
        // TieredCompilationQuickJitForLoops. Inspect JIT output: DOTNET_JitDisasm="Work".
        // [MethodImpl(AggressiveInlining)] / [SkipLocalsInit] for hot paths.
    }
}

// ============================================================
// SECTION 2: GARBAGE COLLECTION
// ============================================================
// Modes:
//   Workstation (default for console/desktop) — one heap, low footprint.
//   Server (default for ASP.NET Core) — one heap + GC thread per core; throughput.
//   Concurrent/Background GC — Gen2 marked concurrently with app threads.
//   DATAS (Dynamic Adaptation To Application Sizes) — default with Server GC
//     since .NET 9: grows/shrinks heap count to the actual load → container-friendly.
// Config: <ServerGarbageCollector>true</ServerGarbageCollector>,
//   <ConcurrentGarbageCollection>, DOTNET_GCHeapHardLimit / GCHeapHardLimitPercent,
//   DOTNET_GCgen0size, GCConserveMemory (0-9), GCSettings.LatencyMode.
static class GcDemo
{
    public static void Run()
    {
        Console.WriteLine($"   server GC={GCSettings.IsServerGC} latency mode={GCSettings.LatencyMode} max generation={GC.MaxGeneration}");
        var small = new object();
        var large = new byte[100_000];                           // ≥ 85,000 bytes → LOH
        Console.WriteLine($"   new small object gen={GC.GetGeneration(small)}, 100 KB array gen={GC.GetGeneration(large)} (LOH is logically Gen2)");
        GC.Collect(0); GC.Collect(0);
        Console.WriteLine($"   after two Gen0 GCs, survivor promoted to gen={GC.GetGeneration(small)}");

        int g0 = GC.CollectionCount(0), g2 = GC.CollectionCount(2);
        for (int i = 0; i < 200_000; i++) _ = new byte[256];       // short-lived garbage
        Console.WriteLine($"   50 MB of short-lived allocations → Gen0 GCs +{GC.CollectionCount(0) - g0}, Gen2 GCs +{GC.CollectionCount(2) - g2}");

        var info = GC.GetGCMemoryInfo();
        Console.WriteLine($"   heap={info.HeapSizeBytes / 1024 / 1024}MB committed={info.TotalCommittedBytes / 1024 / 1024}MB "
            + $"available={info.TotalAvailableMemoryBytes / 1024 / 1024 / 1024}GB pause%={info.PauseTimePercentage}");

        // WeakReference: lets the GC reclaim the target; use for caches of recomputable data.
        var weak = MakeWeak();
        GC.Collect(); GC.WaitForPendingFinalizers();
        Console.WriteLine($"   WeakReference alive after full GC: {weak.TryGetTarget(out _)}");
        // ConditionalWeakTable<TKey,TValue>: attach data to objects without keeping them alive.
        // GC.AllocateArray<T>(n, pinned: true) → Pinned Object Heap for buffers handed to native code.
    }
    [MethodImpl(MethodImplOptions.NoInlining)]
    static WeakReference<byte[]> MakeWeak() => new(new byte[1024]);
}

// ============================================================
// SECTION 3: DISPOSAL & FINALIZATION
// ============================================================
// IDisposable  — deterministic release (files, sockets, DB connections).
// IAsyncDisposable — async release (await using) for streams that flush.
// Finalizer (~T) — safety net for UNMANAGED handles only; prefer SafeHandle.
public sealed class Connection : IDisposable, IAsyncDisposable
{
    private readonly List<string> _log;
    private bool _disposed;
    public Connection(List<string> log) { _log = log; _log.Add("open"); }
    public void Query() { ObjectDisposedException.ThrowIf(_disposed, this); _log.Add("query"); }
    public void Dispose() { if (_disposed) return; _disposed = true; _log.Add("dispose"); }   // idempotent
    public ValueTask DisposeAsync() { Dispose(); _log.Add("(async)"); return ValueTask.CompletedTask; }
}

// The full pattern for a class that owns an UNMANAGED resource (rarely needed —
// wrap the handle in a SafeHandle subclass instead):
public class NativeBuffer : IDisposable
{
    private IntPtr _ptr = Marshal.AllocHGlobal(64);
    private bool _disposed;
    protected virtual void Dispose(bool disposing)
    {
        if (_disposed) return;
        if (disposing) { /* dispose managed members here */ }
        Marshal.FreeHGlobal(_ptr); _ptr = IntPtr.Zero;           // always free unmanaged
        _disposed = true;
    }
    public void Dispose() { Dispose(true); GC.SuppressFinalize(this); }
    ~NativeBuffer() => Dispose(false);                             // finalizer: unmanaged only
}

static class DisposalDemo
{
    public static void Run()
    {
        var log = new List<string>();
        using (var c = new Connection(log)) c.Query();
        try { var c2 = new Connection(log); c2.Dispose(); c2.Query(); }
        catch (ObjectDisposedException) { log.Add("ObjectDisposedException"); }
        RunAsync(log).GetAwaiter().GetResult();
        using (new NativeBuffer()) { }
        Console.WriteLine($"   {string.Join(" → ", log)}");
    }
    static async Task RunAsync(List<string> log) { await using var c = new Connection(log); c.Query(); }
}

// ============================================================
// SECTION 4: REFLECTION & ATTRIBUTES
// ============================================================
[AttributeUsage(AttributeTargets.Property)]
public sealed class MaskAttribute(int visible = 4) : Attribute { public int Visible { get; } = visible; }

[AttributeUsage(AttributeTargets.Class)]
public sealed class AuditedAttribute : Attribute { public string Category { get; init; } = "general"; }

[Audited(Category = "payments")]
public sealed class PaymentRecord
{
    public string Id { get; init; } = "";
    [Mask(4)] public string CardNumber { get; init; } = "";
    [Mask(0)] public string Cvv { get; init; } = "";
    public decimal Amount { get; init; }
    private string Secret { get; } = "internal";
}

static class Redactor
{
    // Reflection-based: flexible, but slow-ish and NOT trimming/AOT-safe without annotations.
    // [DynamicallyAccessedMembers] tells the trimmer which members reflection needs,
    // so they survive trimming/AOT. Using o.GetType() instead would raise IL2075.
    public static string Describe<[DynamicallyAccessedMembers(DynamicallyAccessedMemberTypes.PublicProperties)] T>(T o) where T : notnull
    {
        var type = typeof(T);
        var audited = type.GetCustomAttribute<AuditedAttribute>();
        var parts = type.GetProperties(BindingFlags.Public | BindingFlags.Instance).Select(p =>
        {
            var value = p.GetValue(o)?.ToString() ?? "";
            if (p.GetCustomAttribute<MaskAttribute>() is { } m)
                value = new string('*', Math.Max(0, value.Length - m.Visible)) + value[Math.Max(0, value.Length - m.Visible)..];
            return $"{p.Name}={value}";
        });
        return $"[{audited?.Category ?? "-"}] {type.Name}({string.Join(", ", parts)})";
    }
}

static class ReflectionDemo
{
    public static void Run()
    {
        var rec = new PaymentRecord { Id = "pay_1", CardNumber = "4242424242424242", Cvv = "123", Amount = 49.99m };
        Console.WriteLine($"   {Redactor.Describe(rec)}");
        var secret = typeof(PaymentRecord).GetProperty("Secret", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(rec);
        Console.WriteLine($"   reflection can read private members: Secret={secret} (why encapsulation is not security)");

        // Invoke a generic method via reflection:
        var mi = typeof(Enumerable).GetMethod(nameof(Enumerable.Repeat))!.MakeGenericMethod(typeof(string));
        var repeated = (IEnumerable<string>)mi.Invoke(null, ["ab", 3])!;
        Console.WriteLine($"   MakeGenericMethod + Invoke: {string.Concat(repeated)}");

        // UnsafeAccessor (.NET 8): compile-time-bound access to private members — fast and AOT-safe.
        Console.WriteLine($"   UnsafeAccessor read private: {GetSecret(rec)}");
        // SOURCE GENERATORS (Roslyn IIncrementalGenerator) generate code at build time:
        //   [JsonSerializable(typeof(Order))] partial class AppJsonContext : JsonSerializerContext {}
        //   [LoggerMessage(Level = LogLevel.Information, Message = "Order {Id} paid")] static partial void LogPaid(ILogger l, string id);
        //   [GeneratedRegex(@"^\d{4}-\d{2}$")] private static partial Regex Period();
        //   [LibraryImport("libc")] (below), ConfigurationBinder, Minimal API RequestDelegateGenerator
        // → no runtime reflection, trimming-safe, faster startup. Write your own for
        //   mappers/DTO boilerplate (or use Mapperly, which is a source generator).
    }
    [UnsafeAccessor(UnsafeAccessorKind.Method, Name = "get_Secret")]
    static extern string GetSecret(PaymentRecord r);
}

// ============================================================
// SECTION 5: NATIVE INTEROP — P/Invoke & LibraryImport
// ============================================================
// [DllImport] — runtime-generated marshalling stubs (classic).
// [LibraryImport] (.NET 7) — SOURCE-GENERATED marshalling: AOT-friendly,
//   requires `partial` and AllowUnsafeBlocks. Prefer it for new code.
// Blittable types (int, double, pointers, structs of them) cross for free;
// strings/arrays need marshalling (StringMarshalling.Utf16/Utf8).
static partial class Native
{
    [LibraryImport("kernel32.dll")]
    internal static partial uint GetCurrentProcessId();

    [LibraryImport("libc", EntryPoint = "getpid")]
    internal static partial int getpid();

    [LibraryImport("kernel32.dll", EntryPoint = "lstrlenW", StringMarshalling = StringMarshalling.Utf16)]
    internal static partial int StrLenW(string s);
}

static class InteropDemo
{
    public static unsafe void Run()
    {
        long pid = OperatingSystem.IsWindows() ? Native.GetCurrentProcessId() : Native.getpid();
        Console.WriteLine($"   native pid={pid} matches Environment.ProcessId: {pid == Environment.ProcessId}");
        if (OperatingSystem.IsWindows()) Console.WriteLine($"   lstrlenW(\"interop\")={Native.StrLenW("interop")}");

        // Unmanaged memory + pointers (unsafe): NativeMemory (.NET 6) is the modern malloc/free.
        int* buf = (int*)NativeMemory.Alloc(4, sizeof(int));
        try
        {
            var span = new Span<int>(buf, 4);                       // safe view over native memory
            span.Fill(7);
            Console.WriteLine($"   NativeMemory span sum={span[0] + span[1] + span[2] + span[3]}");
        }
        finally { NativeMemory.Free(buf); }
        // Callbacks: function pointers `delegate* unmanaged<int, void>` + [UnmanagedCallersOnly].
        // COM interop: ComWrappers + source-generated [GeneratedComInterface] (.NET 8).
    }
}

// ============================================================
// SECTION 6: ASSEMBLY LOADING, NATIVE AOT, TRIMMING, DIAGNOSTICS
// ============================================================
static class LoadingDemo
{
    public static void Run()
    {
        var alc = AssemblyLoadContext.GetLoadContext(typeof(LoadingDemo).Assembly)!;
        Console.WriteLine($"   this assembly's load context: {alc.Name}; loaded assemblies={AppDomain.CurrentDomain.GetAssemblies().Length}");
        // Plugins: new AssemblyLoadContext("plugin", isCollectible: true) + LoadFromAssemblyPath,
        // then Unload() — isolation and unloadability (replaces AppDomains from .NET Framework).
    }
}
// NATIVE AOT  (<PublishAot>true</PublishAot>, `dotnet publish -r linux-x64`):
//   single native executable, ~10-30 MB, starts in ~10-50 ms, lower RSS;
//   no JIT ⇒ no Reflection.Emit, no dynamic assembly loading, limited
//   MakeGenericType; requires trimming-compatible code. ASP.NET Core supports
//   it for minimal APIs + the "slim" builder (CreateSlimBuilder) — L07.
// TRIMMING (<PublishTrimmed>): removes unused IL; annotate reflection with
//   [DynamicallyAccessedMembers], [RequiresUnreferencedCode]; treat IL2xxx/IL3xxx
//   warnings as errors. ReadyToRun (<PublishReadyToRun>) = precompiled IL+native,
//   keeps the JIT for tiering — a middle ground.
// DIAGNOSTICS (dotnet tool install -g ...):
//   dotnet-counters monitor -p PID   — live GC/heap/thread-pool/exception rates
//   dotnet-trace collect -p PID      — EventPipe trace → PerfView / speedscope
//   dotnet-gcdump collect -p PID     — heap snapshot (leaks) → VS / PerfView
//   dotnet-dump collect/analyze      — full dump; `dumpheap -stat`, `gcroot <addr>`
//   dotnet-stack report -p PID       — managed stacks of all threads
//   System.Diagnostics.Metrics + ActivitySource → OpenTelemetry (L07).
//   EventCounters → Metrics: "System.Runtime" meter (.NET 9) exposes GC, JIT, thread pool.
