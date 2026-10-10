// ============================================================
// L04: Collections, Span<T>/Memory<T>, and High-Performance C#
// ============================================================
// WHAT: Microsoft Learn ".NET collections", "Memory and spans",
//       "Memory<T> and Span<T> usage guidelines", "Frozen
//       collections", "High-performance C#" and the runtime
//       performance blog topics: List/Dictionary/HashSet/Queue/
//       Stack/PriorityQueue/Sorted*/LinkedList and their costs,
//       capacity & growth, comparers, immutable vs frozen vs
//       read-only collections, CollectionsMarshal; Span<T>,
//       ReadOnlySpan<T>, Memory<T>, stackalloc, ref structs,
//       `scoped`, ArrayPool/MemoryPool, string.Create, SearchValues,
//       allocation-free parsing, and measuring with BenchmarkDotNet.
// WHY:  Allocation is the hidden tax of managed code: every
//       short-lived object is GC work. The span family lets C#
//       write parsers and protocol code with zero allocations and
//       bounds-checked safety — it's how Kestrel, System.Text.Json
//       and gRPC got fast.
// LEVEL: Intermediate → Advanced
// RUN:   dotnet run L04_collections_spans_performance.cs
// SOURCE: learn.microsoft.com/dotnet/standard/collections/*,
//         /standard/memory-and-spans/*, /csharp/advanced-topics/performance/*,
//         System.Collections.Frozen, System.Buffers.SearchValues API docs
// ============================================================
/*
CONCEPT OVERVIEW:
    Span<T> is a ref struct: a (pointer, length) view over
    contiguous memory — an array, a stackalloc buffer, native
    memory, or a string (ReadOnlySpan<char>). Slicing is O(1) and
    allocation-free. Because it may point at the stack, it can
    NEVER go to the heap: no fields in classes, no boxing, no
    capture in lambdas, no use across `await`. Memory<T> is its
    heap-storable sibling; call .Span when you need to work.

PRODUCTION USE CASE:
    A market-data feed handler parsing millions of
    "SYMBOL,PRICE,QTY" lines per second without allocating per
    line, aggregating into a pre-sized Dictionary, with a frozen
    symbol whitelist and pooled buffers.

COMMON MISTAKES:
    1. Not pre-sizing List/Dictionary when the count is known —
       repeated grow-and-copy.
    2. Using LINQ in a per-message hot path (enumerator +
       delegate allocations). Fine elsewhere.
    3. Returning a rented ArrayPool array twice, or using it after
       return; forgetting rented arrays can be LONGER than requested.
    4. string.Substring / Split in parsers → one allocation per
       piece. Slice spans instead.
    5. Dictionary<string,...> with culture-sensitive or case-
       insensitive needs but default comparer — pass
       StringComparer.Ordinal(IgnoreCase).
    6. Optimising without measuring. Use BenchmarkDotNet with
       [MemoryDiagnoser]; Stopwatch micro-timings lie.
*/

#:property Nullable=enable
#:property InvariantGlobalization=true

using System.Buffers;
using System.Collections.Concurrent;
using System.Collections.Frozen;
using System.Collections.Immutable;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;

Console.WriteLine("== core collections"); CollectionsDemo.Run();
Console.WriteLine("== immutable, frozen, read-only, concurrent"); SpecialCollectionsDemo.Run();
Console.WriteLine("== spans & memory"); SpanDemo.Run();
Console.WriteLine("== pooling & strings"); PoolingDemo.Run();
Console.WriteLine("== end-to-end: zero-allocation feed parser"); FeedParser.Run();

// ============================================================
// SECTION 1: CORE COLLECTIONS & THEIR COSTS
// ============================================================
//  Type                        Lookup       Add          Notes
//  List<T>                     O(1) index   O(1) amort.  contiguous array; Insert/RemoveAt(0) O(n)
//  Dictionary<K,V>             O(1)         O(1) amort.  hash table; insertion order NOT guaranteed
//  HashSet<T>                  O(1)         O(1)         set algebra: UnionWith, IntersectWith...
//  Queue<T> / Stack<T>         O(1) ends    O(1)         circular buffer / array
//  PriorityQueue<TE,TP> (.NET 6) O(1) peek  O(log n)     min-heap by priority; not stable
//  SortedDictionary<K,V>       O(log n)     O(log n)     red-black tree
//  SortedList<K,V>             O(log n)     O(n)         two arrays; compact, slow inserts
//  SortedSet<T>                O(log n)     O(log n)     GetViewBetween for ranges
//  LinkedList<T>               O(n)         O(1) at node rarely the right answer
//  OrderedDictionary<K,V> (.NET 9) O(1) key / index     insertion-ordered generic dictionary
static class CollectionsDemo
{
    public static void Run()
    {
        var list = new List<int>(capacity: 4);
        var caps = new List<int>();
        for (int i = 0; i < 20; i++) { list.Add(i); if (!caps.Contains(list.Capacity)) caps.Add(list.Capacity); }
        Console.WriteLine($"   List growth (doubling): capacities seen {string.Join("→", caps)}; TrimExcess shrinks");

        var prices = new Dictionary<string, decimal>(StringComparer.OrdinalIgnoreCase) { ["AAPL"] = 231.5m };
        prices.TryAdd("aapl", 1m);                                     // false — case-insensitive comparer
        // CollectionsMarshal: get a ref to the value slot — update in place, one hash lookup.
        ref decimal slot = ref CollectionsMarshal.GetValueRefOrAddDefault(prices, "MSFT", out bool existed);
        slot = 512.25m;
        Console.WriteLine($"   Dictionary: count={prices.Count} MSFT existed={existed} value={prices["msft"]}");

        var pq = new PriorityQueue<string, int>();
        pq.EnqueueRange([("low", 5), ("urgent", 0), ("normal", 2)]);
        var drained = new List<string>(); while (pq.TryDequeue(out var item, out _)) drained.Add(item);
        Console.WriteLine($"   PriorityQueue (min-heap): {string.Join(",", drained)}");

        var sorted = new SortedSet<int>([50, 10, 40, 20, 30]);
        Console.WriteLine($"   SortedSet view [15..40]: {string.Join(",", sorted.GetViewBetween(15, 40))}  min={sorted.Min} max={sorted.Max}");

        var ordered = new OrderedDictionary<string, int> { ["first"] = 1, ["second"] = 2 };
        ordered.Insert(0, "zero", 0);
        Console.WriteLine($"   OrderedDictionary: {string.Join(",", ordered.Keys)} index 1 → {ordered.GetAt(1).Key}");

        var a = new HashSet<string> { "x", "y", "z" };
        a.IntersectWith(["y", "z", "w"]);
        Console.WriteLine($"   HashSet ∩: {string.Join(",", a.Order())}");
        // Equality: HashSet/Dictionary use IEqualityComparer<T> (GetHashCode + Equals).
        // Records & tuples have structural equality; classes default to reference equality.
    }
}

// ============================================================
// SECTION 2: IMMUTABLE, FROZEN, READ-ONLY, CONCURRENT
// ============================================================
// ReadOnlyCollection / IReadOnlyList — a VIEW; the owner can still mutate.
// ImmutableList/Dictionary — persistent trees; every "change" returns a
//   new instance sharing structure; great for snapshots/undo, slower reads.
// FrozenDictionary/FrozenSet (.NET 8) — build once (slow), read fastest;
//   for configuration, lookup tables, routing tables.
// Concurrent* — thread-safe without external locks (see L05).
static class SpecialCollectionsDemo
{
    public static void Run()
    {
        var backing = new List<string> { "a" };
        IReadOnlyList<string> view = backing.AsReadOnly();
        backing.Add("b");
        Console.WriteLine($"   read-only view sees owner's change: {view.Count}");

        var v1 = ImmutableList.Create(1, 2, 3);
        var v2 = v1.Add(4);
        var builder = v2.ToBuilder(); builder.RemoveAt(0); var v3 = builder.ToImmutable();   // batch edits efficiently
        Console.WriteLine($"   immutable: v1={string.Join(",", v1)} v2={string.Join(",", v2)} v3={string.Join(",", v3)}");

        FrozenSet<string> allowedSymbols = new[] { "AAPL", "MSFT", "NVDA", "GOOG" }.ToFrozenSet(StringComparer.Ordinal);
        FrozenDictionary<string, int> lotSizes = new Dictionary<string, int> { ["AAPL"] = 100, ["NVDA"] = 50 }.ToFrozenDictionary();
        // .NET 9+: alternate lookup — query a string-keyed set with a ReadOnlySpan<char>, zero allocation.
        var spanLookup = allowedSymbols.GetAlternateLookup<ReadOnlySpan<char>>();
        ReadOnlySpan<char> line = "NVDA,123.45,10";
        Console.WriteLine($"   frozen: contains NVDA (span, no alloc)={spanLookup.Contains(line[..4])} lot={lotSizes["NVDA"]}");

        var cache = new ConcurrentDictionary<string, int>();
        Parallel.For(0, 1000, i => cache.AddOrUpdate(i % 2 == 0 ? "even" : "odd", 1, (_, n) => n + 1));
        Console.WriteLine($"   ConcurrentDictionary counts: even={cache["even"]} odd={cache["odd"]}");
        // GetOrAdd(key, factory) may run the factory more than once under a race —
        // wrap values in Lazy<T> when creation is expensive or must be single.
    }
}

// ============================================================
// SECTION 3: SPAN<T>, READONLYSPAN<T>, MEMORY<T>, STACKALLOC
// ============================================================
static class SpanDemo
{
    // ref struct: may contain spans; stack-only like Span itself.
    ref struct Tokenizer(ReadOnlySpan<char> input, char sep)
    {
        private ReadOnlySpan<char> _rest = input;
        public bool Next(out ReadOnlySpan<char> token)
        {
            if (_rest.IsEmpty) { token = default; return false; }
            int i = _rest.IndexOf(sep);
            token = i < 0 ? _rest : _rest[..i];
            _rest = i < 0 ? ReadOnlySpan<char>.Empty : _rest[(i + 1)..];
            return true;
        }
    }

    static int SumDigits(scoped ReadOnlySpan<char> s)   // `scoped`: promise the span won't escape this method
    {
        int sum = 0;
        foreach (char c in s) if (char.IsAsciiDigit(c)) sum += c - '0';
        return sum;
    }

    public static void Run()
    {
        int[] array = [1, 2, 3, 4, 5, 6];
        Span<int> middle = array.AsSpan(2, 3);         // view, no copy
        middle[0] = 99;                                // writes through to the array
        Console.WriteLine($"   span over array: array[2]={array[2]} slice len={middle.Length}");

        Span<byte> buffer = stackalloc byte[16];       // stack memory: no GC, freed at method exit
        buffer.Fill(0xAB);
        Console.WriteLine($"   stackalloc: {Convert.ToHexString(buffer[..4])}  (keep stackalloc small: < ~1 KB)");

        ReadOnlySpan<char> csv = "AAPL,231.50,100";
        var tok = new Tokenizer(csv, ',');
        var parts = new List<string>();
        while (tok.Next(out var t)) parts.Add(t.ToString());   // ToString only for display
        Console.WriteLine($"   tokenizer: [{string.Join("|", parts)}]  SumDigits={SumDigits("a1b2c3")}");

        // Parsing straight from spans — no Substring:
        var priceSpan = csv[5..11];
        decimal price = decimal.Parse(priceSpan, CultureInfo.InvariantCulture);
        Console.WriteLine($"   decimal.Parse(span)={price}");

        // C# 14 first-class span conversions: arrays convert implicitly to (ReadOnly)Span
        // in more places, incl. extension method receivers and generic inference.
        Console.WriteLine($"   span extension on array: {array.AsSpan().ContainsAny(98, 99)}");

        // Memory<T>: storable on the heap, usable across await; get .Span to work.
        Memory<int> mem = array.AsMemory(0, 2);
        var holder = new { Chunk = mem };              // allowed (Span<T> here would not compile)
        Console.WriteLine($"   Memory<T> in a heap object: {string.Join(",", holder.Chunk.Span.ToArray())}");
        // Rules: Span<T> for synchronous hot paths; Memory<T> to store/pass across
        // async boundaries; never hold a Span over an `await`.
        // MemoryMarshal.Cast<byte,int>(bytes) reinterprets without copying;
        // BinaryPrimitives.ReadInt32LittleEndian(span) for protocols.
    }
}

// ============================================================
// SECTION 4: POOLING, string.Create, SearchValues
// ============================================================
static class PoolingDemo
{
    static readonly SearchValues<char> Delimiters = SearchValues.Create(",;|\t");   // vectorized multi-char search (.NET 8)

    public static void Run()
    {
        byte[] rented = ArrayPool<byte>.Shared.Rent(1000);
        try
        {
            Console.WriteLine($"   ArrayPool: asked 1000, got {rented.Length} (may be larger — track your own length)");
            Encoding.UTF8.TryGetBytes("hello pool", rented, out int written);
            Console.WriteLine($"   wrote {written} bytes into rented buffer");
        }
        finally { ArrayPool<byte>.Shared.Return(rented, clearArray: true); }   // clear if it held secrets

        // string.Create: build a string by writing directly into its buffer — one allocation.
        string id = string.Create(12, 4242L, static (span, n) =>
        {
            "ORD-".AsSpan().CopyTo(span);
            n.TryFormat(span[4..], out int w, "D8");
        });
        Console.WriteLine($"   string.Create → {id}");

        ReadOnlySpan<char> line = "symbol;price|qty";
        Console.WriteLine($"   SearchValues first delimiter at {line.IndexOfAny(Delimiters)} ('{line[line.IndexOfAny(Delimiters)]}')");

        // Interpolated string handlers: logging libs & StringBuilder.Append($"...")
        // format directly into buffers; DefaultInterpolatedStringHandler avoids boxing.
        var sb = new StringBuilder();
        sb.Append($"px={231.5m} qty={100}");
        Console.WriteLine($"   StringBuilder interpolation handler: {sb}");
        // Other tools: ObjectPool<T> (Microsoft.Extensions.ObjectPool), RecyclableMemoryStream,
        // ValueTask (L05), struct enumerators (foreach over List<T> doesn't allocate),
        // [SkipLocalsInit], Vector<T>/Vector128-512 SIMD (System.Runtime.Intrinsics).
    }
}

// ============================================================
// SECTION 5: END-TO-END — ZERO-ALLOCATION FEED PARSER
// ============================================================
static class FeedParser
{
    readonly record struct Tick(decimal Price, int Qty);

    sealed class Book
    {
        public decimal Notional; public long Volume; public int Count;
    }

    static bool TryParseLine(ReadOnlySpan<char> line, out ReadOnlySpan<char> symbol, out Tick tick)
    {
        symbol = default; tick = default;
        int c1 = line.IndexOf(',');
        if (c1 <= 0) return false;
        var rest = line[(c1 + 1)..];
        int c2 = rest.IndexOf(',');
        if (c2 <= 0) return false;
        if (!decimal.TryParse(rest[..c2], NumberStyles.Number, CultureInfo.InvariantCulture, out var px)) return false;
        if (!int.TryParse(rest[(c2 + 1)..], NumberStyles.Integer, CultureInfo.InvariantCulture, out var qty)) return false;
        symbol = line[..c1]; tick = new Tick(px, qty);
        return true;
    }

    public static void Run()
    {
        string[] symbols = ["AAPL", "MSFT", "NVDA", "GOOG"];
        var feed = new StringBuilder();
        var rng = new Random(7);
        for (int i = 0; i < 200_000; i++)
            feed.Append(symbols[i % 4]).Append(',').Append((100 + rng.Next(0, 10000) / 100m).ToString(CultureInfo.InvariantCulture)).Append(',').Append(rng.Next(1, 500)).Append('\n');
        feed.Append("BAD LINE\n");
        string text = feed.ToString();

        // Pre-sized dictionary keyed by string; span lookups via the alternate comparer (.NET 9).
        var books = new Dictionary<string, Book>(capacity: 8, StringComparer.Ordinal);
        foreach (var s in symbols) books[s] = new Book();
        var lookup = books.GetAlternateLookup<ReadOnlySpan<char>>();

        long before = GC.GetAllocatedBytesForCurrentThread();
        var sw = Stopwatch.StartNew();
        int bad = 0;
        ReadOnlySpan<char> remaining = text;
        foreach (var range in remaining.Split('\n'))                       // span Split (.NET 9): enumerates Ranges, no strings
        {
            var line = remaining[range];
            if (line.IsEmpty) continue;
            if (!TryParseLine(line, out var sym, out var tick) || !lookup.TryGetValue(sym, out var book)) { bad++; continue; }
            book.Notional += tick.Price * tick.Qty; book.Volume += tick.Qty; book.Count++;
        }
        sw.Stop();
        long allocated = GC.GetAllocatedBytesForCurrentThread() - before;

        foreach (var (sym, b) in books)
            Console.WriteLine($"   {sym}: ticks={b.Count,6} volume={b.Volume,9} VWAP={b.Notional / b.Volume:F4}");
        Console.WriteLine($"   bad lines={bad}; parsed 200k lines, allocated ≈ {allocated} bytes in the loop (≈0 → no per-line garbage)");
        // Benchmark properly with BenchmarkDotNet:
        //   #:package BenchmarkDotNet@0.15.*
        //   [MemoryDiagnoser] public class ParserBench { [Benchmark] public void Parse() {...} }
        //   BenchmarkRunner.Run<ParserBench>();   (Release build, no debugger)
    }
}
