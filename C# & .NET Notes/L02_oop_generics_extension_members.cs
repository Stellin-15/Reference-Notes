// ============================================================
// L02: Object-Oriented C#, Generics, Extension Members (C# 14)
// ============================================================
// WHAT: Microsoft Learn "Object-oriented programming", "Classes,
//       structs, and records", "Interfaces", "Generics" and
//       "Extension members": classes and constructors (incl.
//       primary constructors, C# 12), required/init members,
//       properties (auto, computed, C# 14 `field`-backed),
//       indexers, static members, inheritance (virtual/override/
//       new/sealed/abstract), interfaces (default and static
//       abstract members), operator overloading and C# 14
//       user-defined compound assignment, generics (constraints,
//       variance in/out, generic math via INumber<T>),
//       extension blocks (C# 14), partial types/members, events.
// WHY:  This is how real C# codebases are structured: DI-friendly
//       classes with primary constructors, immutable DTOs with
//       required/init, interfaces for seams, and extension
//       members to add fluent APIs to types you don't own.
// LEVEL: Foundation → Intermediate
// RUN:   dotnet run L02_oop_generics_extension_members.cs   (.NET 10 SDK)
// SOURCE: learn.microsoft.com/dotnet/csharp/fundamentals/object-oriented/*,
//         /fundamentals/types/generics, /programming-guide/classes-and-structs/*,
//         /language-reference/keywords/extension, What's new in C# 11-14
// ============================================================
/*
CONCEPT OVERVIEW:
    A class bundles state and behaviour; members default to
    `private`. Access modifiers: public, private, protected,
    internal (same assembly), protected internal, private protected,
    and `file` (C# 11, visible in one source file only).
    Methods are NON-virtual by default (unlike Java): you must
    mark `virtual` to allow overriding and `override` to do it.
    Generics are REIFIED in .NET (unlike Java's erasure):
    List<int> is a distinct runtime type with no boxing.

PRODUCTION USE CASE:
    A subscription-billing module: services with primary-
    constructor DI, an abstract pricing strategy hierarchy, an
    INumber<T>-generic statistics helper, and C# 14 extension
    properties/operators that make domain code read naturally.

COMMON MISTAKES:
    1. Hiding instead of overriding: a method with the same name
       but no `override` HIDES (warning CS0114); calls through the
       base type run the base version.
    2. Primary-constructor parameters are captured mutable state,
       not readonly fields — assign them to `readonly` fields if
       immutability matters.
    3. Exposing List<T> from a property — callers can mutate it.
       Expose IReadOnlyList<T> or an immutable collection.
    4. Events without unsubscription → memory leaks (the publisher
       holds subscribers alive).
    5. Overusing inheritance; prefer composition + interfaces.
    6. `new()` constraint + reflection-heavy factories when DI or
       a Func<T> would be clearer.
*/

#:property Nullable=enable
#:property InvariantGlobalization=true

using System.Numerics;

Console.WriteLine("== classes, constructors, properties");
ClassesDemo.Run();
Console.WriteLine("== inheritance & polymorphism");
InheritanceDemo.Run();
Console.WriteLine("== interfaces");
InterfacesDemo.Run();
Console.WriteLine("== operators");
OperatorsDemo.Run();
Console.WriteLine("== generics & generic math");
GenericsDemo.Run();
Console.WriteLine("== extension members (C# 14)");
ExtensionsDemo.Run();
Console.WriteLine("== events");
EventsDemo.Run();

// ============================================================
// SECTION 1: CLASSES, CONSTRUCTORS, PROPERTIES
// ============================================================
// PRIMARY CONSTRUCTOR (C# 12) on a class: parameters are in scope for
// the whole body — ideal for dependency injection.
public interface IClock { DateTimeOffset UtcNow { get; } }
public sealed class FixedClock(DateTimeOffset now) : IClock { public DateTimeOffset UtcNow => now; }

public sealed class InvoiceService(IClock clock, string prefix = "INV")
{
    private int _seq;                                        // ordinary field
    public string Next() => $"{prefix}-{clock.UtcNow:yyyyMMdd}-{++_seq:D4}";
}

public sealed class Subscription
{
    // `required` (C# 11): object initializer MUST set it. `init`: settable only during init.
    public required string CustomerId { get; init; }
    public required decimal MonthlyPrice { get; init; }
    public DateOnly Start { get; init; } = DateOnly.FromDateTime(DateTime.UnixEpoch);

    // C# 14 `field` keyword: validation without declaring a backing field.
    public string Plan
    {
        get;
        set => field = string.IsNullOrWhiteSpace(value) ? throw new ArgumentException("plan required") : value.Trim().ToLowerInvariant();
    } = "basic";

    // Computed (expression-bodied) property.
    public decimal AnnualPrice => MonthlyPrice * 12 * (Plan == "annual-discount" ? 0.85m : 1m);

    // Lazy init with `field`.
    public List<string> Notes => field ??= [];

    // Indexer.
    private readonly Dictionary<string, string> _meta = new();
    public string? this[string key] { get => _meta.GetValueOrDefault(key); set => _meta[key] = value ?? ""; }

    // Static members & static constructor (runs once before first use).
    public static int Created { get; private set; }
    static Subscription() { Created = 0; }
    public Subscription() => Created++;

    // Deconstruct method enables `var (id, price) = sub;`
    public void Deconstruct(out string id, out decimal price) => (id, price) = (CustomerId, MonthlyPrice);
}

static class ClassesDemo
{
    public static void Run()
    {
        var svc = new InvoiceService(new FixedClock(new DateTimeOffset(2026, 10, 10, 0, 0, 0, TimeSpan.Zero)));
        Console.WriteLine($"   invoice ids: {svc.Next()}, {svc.Next()}");
        var sub = new Subscription { CustomerId = "cus_1", MonthlyPrice = 20m, Plan = "  Annual-Discount " };
        sub.Notes.Add("migrated from v1");
        sub["region"] = "eu-west";
        var (id, price) = sub;
        Console.WriteLine($"   {id} {price} plan='{sub.Plan}' annual={sub.AnnualPrice} notes={sub.Notes.Count} region={sub["region"]} created={Subscription.Created}");
        try { sub.Plan = " "; } catch (ArgumentException e) { Console.WriteLine($"   field-backed setter rejected: {e.Message}"); }
        // var bad = new Subscription { CustomerId = "x" };  // error CS9035: required member 'MonthlyPrice' must be set
    }
}

// ============================================================
// SECTION 2: INHERITANCE & POLYMORPHISM
// ============================================================
public abstract class PricingStrategy
{
    public abstract string Name { get; }
    public abstract decimal PriceFor(int seats);                     // must override
    public virtual decimal Discount(int seats) => 0m;               // may override
    public decimal Quote(int seats) => Math.Max(0, PriceFor(seats) - Discount(seats)); // template method
    public override string ToString() => $"{Name}: 10 seats → {Quote(10)}";
}

public class PerSeat(decimal perSeat) : PricingStrategy
{
    public override string Name => "per-seat";
    public override decimal PriceFor(int seats) => seats * perSeat;
    public override decimal Discount(int seats) => seats >= 10 ? PriceFor(seats) * 0.1m : 0m;
}

public sealed class Tiered : PerSeat                                  // sealed: no further derivation
{
    public Tiered() : base(8m) { }                                    // base(...) chaining
    public override string Name => "tiered";
    public sealed override decimal Discount(int seats) => base.Discount(seats) + 5m;  // call base implementation
}

public class Animal { public string Speak() => "..."; public virtual string Move() => "moves"; }
public class Dog : Animal
{
    public new string Speak() => "woof";      // HIDES (no polymorphism) — `new` silences the warning
    public override string Move() => "runs";  // overrides (polymorphic)
}

static class InheritanceDemo
{
    public static void Run()
    {
        PricingStrategy[] strategies = [new PerSeat(10m), new Tiered()];
        foreach (var s in strategies) Console.WriteLine($"   {s}");
        Animal a = new Dog();
        Console.WriteLine($"   via base ref: Speak={a.Speak()} (hidden) Move={a.Move()} (overridden); via Dog: {((Dog)a).Speak()}");
        // Type checks: `is`, `as`, pattern matching; GetType() for exact type.
        Console.WriteLine($"   a is Dog: {a is Dog}, exact type: {a.GetType().Name}");
    }
}

// ============================================================
// SECTION 3: INTERFACES — default & static abstract members
// ============================================================
public interface INotifier
{
    string Channel { get; }
    Task SendAsync(string to, string msg);
    // Default interface method (C# 8): add members without breaking implementers.
    string Describe() => $"{Channel} notifier";
}

public interface IParsable2<TSelf> where TSelf : IParsable2<TSelf>
{
    // Static abstract member (C# 11): implementers supply a static factory —
    // the foundation of generic math and IParsable<T>.
    static abstract TSelf Parse(string s);
}

public sealed record Sku(string Code) : IParsable2<Sku>
{
    public static Sku Parse(string s) => s.StartsWith("SKU-", StringComparison.Ordinal) ? new(s) : throw new FormatException(s);
}

public sealed class EmailNotifier : INotifier
{
    public List<string> Sent { get; } = [];
    public string Channel => "email";
    public Task SendAsync(string to, string msg) { Sent.Add($"{to}: {msg}"); return Task.CompletedTask; }
}

// Explicit interface implementation: member only visible through the interface.
public sealed class Report : IDisposable, IFormattable
{
    public bool Disposed { get; private set; }
    void IDisposable.Dispose() => Disposed = true;
    public string ToString(string? format, IFormatProvider? provider) => format == "S" ? "report(short)" : "report(long form)";
}

static class InterfacesDemo
{
    static T ParseAll<T>(string s) where T : IParsable2<T> => T.Parse(s);   // calling a static via the type parameter

    public static void Run()
    {
        INotifier n = new EmailNotifier();
        n.SendAsync("ada@x.io", "invoice ready").Wait();
        Console.WriteLine($"   {n.Describe()} sent={((EmailNotifier)n).Sent.Count}  static abstract parse: {ParseAll<Sku>("SKU-9")}");
        var r = new Report();
        using (r as IDisposable) { }                                 // explicit impl reachable via the interface
        Console.WriteLine($"   explicit impl disposed={r.Disposed}  IFormattable: {r:S}");
    }
}

// ============================================================
// SECTION 4: OPERATOR OVERLOADING & C# 14 COMPOUND ASSIGNMENT
// ============================================================
public sealed class Meter
{
    public long Ticks { get; private set; }
    public Meter(long t) => Ticks = t;
    public static Meter operator +(Meter a, Meter b) => new(a.Ticks + b.Ticks);     // allocates a new object
    // C# 14: user-defined compound assignment — mutate IN PLACE, no allocation.
    public void operator +=(Meter other) => Ticks += other.Ticks;
    public void operator ++() => Ticks++;                                            // instance increment (C# 14)
    public static bool operator ==(Meter? a, Meter? b) => a?.Ticks == b?.Ticks;
    public static bool operator !=(Meter? a, Meter? b) => !(a == b);
    public override bool Equals(object? o) => o is Meter m && m.Ticks == Ticks;     // keep Equals/GetHashCode consistent
    public override int GetHashCode() => Ticks.GetHashCode();
    public static implicit operator long(Meter m) => m.Ticks;                       // conversion operators
    public static explicit operator Meter(long t) => new(t);
}

static class OperatorsDemo
{
    public static void Run()
    {
        var total = new Meter(10);
        var alias = total;
        total += new Meter(5);           // uses the instance operator += → same object mutated
        total++;
        long asLong = total;              // implicit conversion
        Console.WriteLine($"   ticks={total.Ticks} alias sees in-place change={alias.Ticks} same object={ReferenceEquals(alias, total)} long={asLong} ==: {total == (Meter)16L}");
    }
}

// ============================================================
// SECTION 5: GENERICS — constraints, variance, generic math
// ============================================================
// Constraints: where T : class | struct | notnull | unmanaged | new() |
//   BaseClass | IInterface | U (another type param) | allows ref struct (C# 13)
public sealed class Repository<TEntity, TKey> where TEntity : class where TKey : notnull
{
    private readonly Dictionary<TKey, TEntity> _items = new();
    private readonly Func<TEntity, TKey> _key;
    public Repository(Func<TEntity, TKey> key) => _key = key;
    public void Save(TEntity e) => _items[_key(e)] = e;
    public TEntity? Find(TKey id) => _items.GetValueOrDefault(id);
    public IReadOnlyCollection<TEntity> All => _items.Values;
}

// Variance on interfaces/delegates: out = covariant (producer), in = contravariant (consumer).
public interface ISource<out T> { T Next(); }
public interface ISink<in T> { void Put(T item); }
public sealed class StringSource : ISource<string> { public string Next() => "s"; }
public sealed class ObjectSink : ISink<object> { public int Count; public void Put(object item) => Count++; }

static class Stats
{
    // Generic math (.NET 7 / C# 11): one implementation for int, double, decimal...
    public static T Sum<T>(IEnumerable<T> xs) where T : INumber<T>
    {
        T total = T.Zero;
        foreach (var x in xs) total += x;
        return total;
    }
    public static T Mean<T>(IReadOnlyCollection<T> xs) where T : INumber<T> => Sum(xs) / T.CreateChecked(xs.Count);
}

static class GenericsDemo
{
    public static void Run()
    {
        var repo = new Repository<Subscription, string>(s => s.CustomerId);
        repo.Save(new Subscription { CustomerId = "c1", MonthlyPrice = 10m });
        repo.Save(new Subscription { CustomerId = "c2", MonthlyPrice = 30m });
        Console.WriteLine($"   repo find c2 → {repo.Find("c2")?.MonthlyPrice} missing → {repo.Find("zz")?.MonthlyPrice.ToString() ?? "null"}");

        ISource<object> covariant = new StringSource();      // ISource<string> → ISource<object>
        ISink<string> contravariant = new ObjectSink();      // ISink<object> → ISink<string>
        contravariant.Put(covariant.Next().ToString()!);
        Console.WriteLine($"   variance ok: sink count={((ObjectSink)contravariant).Count}");

        Console.WriteLine($"   generic math: Sum<int>={Stats.Sum([1, 2, 3])} Mean<double>={Stats.Mean<double>([1.5, 2.5])} Mean<decimal>={Stats.Mean<decimal>([10m, 20m, 40m]):F4}");
        // Reified generics: typeof(List<int>) != typeof(List<string>) at runtime.
        Console.WriteLine($"   reified: {typeof(List<int>) == typeof(List<string>)}  nameof(List<>)={nameof(List<>)} (C# 14 unbound nameof)");
    }
}

// ============================================================
// SECTION 6: EXTENSION MEMBERS (C# 14)
// ============================================================
// Extension BLOCKS group extension members for a receiver. New in 14:
// extension properties, static extension members, extension operators.
// Classic `this` extension methods still work and are binary-compatible.
public static class SubscriptionExtensions
{
    extension(Subscription s)                                     // instance receiver
    {
        public bool IsPremium => s.MonthlyPrice >= 25m;           // extension PROPERTY
        public decimal PriceForMonths(int months) => s.MonthlyPrice * months;
    }

    extension(IEnumerable<Subscription> subs)
    {
        public decimal Mrr => subs.Sum(x => x.MonthlyPrice);       // monthly recurring revenue
        public IEnumerable<Subscription> Premium => subs.Where(x => x.IsPremium);
    }

    extension(decimal)                                             // receiver TYPE only → static members
    {
        public static decimal FromCents(long cents) => cents / 100m;   // called as decimal.FromCents(...)
    }

    extension<T>(IEnumerable<T>)                                    // static extension operator
    {
        public static IEnumerable<T> operator +(IEnumerable<T> left, IEnumerable<T> right) => left.Concat(right);
    }

    // Classic syntax, still fine:
    public static string Masked(this string email) => email.Length < 3 ? "***" : email[0] + "***" + email[email.IndexOf('@')..];
}

static class ExtensionsDemo
{
    public static void Run()
    {
        List<Subscription> subs =
        [
            new() { CustomerId = "a", MonthlyPrice = 10m },
            new() { CustomerId = "b", MonthlyPrice = 49m },
            new() { CustomerId = "c", MonthlyPrice = 25m },
        ];
        Console.WriteLine($"   MRR={subs.Mrr} premium={string.Join(",", subs.Premium.Select(x => x.CustomerId))} b.IsPremium={subs[1].IsPremium} "
            + $"6 months of a={subs[0].PriceForMonths(6)}");
        IEnumerable<int> merged = new[] { 1, 2 }.AsEnumerable() + new[] { 3 };
        Console.WriteLine($"   static extension: decimal.FromCents(12345)={decimal.FromCents(12345)}  operator + → [{string.Join(",", merged)}]  masked={"ada@example.com".Masked()}");
    }
}

// ============================================================
// SECTION 7: EVENTS & DELEGATES (preview of L03)
// ============================================================
public sealed class PaymentProcessor
{
    // EventHandler<T> pattern: (object? sender, TEventArgs e)
    public event EventHandler<PaymentEventArgs>? PaymentSucceeded;
    public void Charge(string customer, decimal amount)
    {
        // ... charge ...
        PaymentSucceeded?.Invoke(this, new PaymentEventArgs(customer, amount));   // thread-safe null check
    }
}
public sealed record PaymentEventArgs(string Customer, decimal Amount);

static class EventsDemo
{
    public static void Run()
    {
        var p = new PaymentProcessor();
        var log = new List<string>();
        EventHandler<PaymentEventArgs> handler = (_, e) => log.Add($"receipt for {e.Customer}: {e.Amount}");
        p.PaymentSucceeded += handler;
        p.PaymentSucceeded += (_, e) => log.Add($"analytics {e.Amount}");
        p.Charge("cus_1", 49m);
        p.PaymentSucceeded -= handler;                  // unsubscribe (lambdas can't be removed unless stored)
        p.Charge("cus_2", 10m);
        Console.WriteLine($"   events: {string.Join(" | ", log)}");
        // Partial types/members: split a class across files (source generators
        // fill in `partial` methods/properties/constructors/events — C# 13/14).
    }
}
