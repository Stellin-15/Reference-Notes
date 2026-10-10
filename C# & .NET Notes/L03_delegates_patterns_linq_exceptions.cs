// ============================================================
// L03: Delegates & Lambdas, Pattern Matching, LINQ, Exceptions
// ============================================================
// WHAT: Microsoft Learn "Functional techniques" (pattern
//       matching, discards, deconstruction), "Delegates and
//       events", "Lambda expressions", "LINQ" (query & method
//       syntax, deferred execution, standard query operators incl.
//       .NET 9-10 additions CountBy/AggregateBy/Index/LeftJoin),
//       and "Exceptions and exception handling": Func/Action/
//       Predicate, closures, local functions, static lambdas;
//       type/constant/relational/logical/property/positional/
//       list patterns and switch expressions; custom exceptions,
//       filters, finally, ExceptionDispatchInfo, guard helpers.
// WHY:  Patterns + LINQ make C# business logic declarative and
//       exhaustive. Deferred execution and closure capture are the
//       two LINQ bugs every team ships at least once. Exception
//       handling discipline is what makes logs useful.
// LEVEL: Intermediate
// RUN:   dotnet run L03_delegates_patterns_linq_exceptions.cs
// SOURCE: learn.microsoft.com/dotnet/csharp/fundamentals/functional/*,
//         /programming-guide/delegates/*, /linq/*, /fundamentals/exceptions/*,
//         /language-reference/operators/patterns, What's new in .NET 9/10 (LINQ)
// ============================================================
/*
CONCEPT OVERVIEW:
    A DELEGATE is a type-safe function pointer (Func<T,TResult>,
    Action<T>, Predicate<T>, or your own). Lambdas convert to
    delegates — or to EXPRESSION TREES (Expression<Func<...>>),
    which is how EF Core turns C# into SQL.
    LINQ = extension methods over IEnumerable<T> (in-memory, delegates)
    and IQueryable<T> (translated providers, expression trees).
    Most operators are DEFERRED: nothing runs until enumeration.
    PATTERNS test shape and extract values; switch EXPRESSIONS
    over patterns are checked for exhaustiveness (warning CS8509).

PRODUCTION USE CASE:
    Fraud-rule evaluation over card transactions: rules as
    patterns in a switch expression, analytics via LINQ grouping
    and joins, and an exception strategy that separates expected
    domain failures from bugs.

COMMON MISTAKES:
    1. Enumerating a deferred query twice (two DB round-trips, or
       results that changed in between). Materialise with ToList().
    2. Capturing a loop variable or mutable local in a lambda and
       running it later.
    3. `throw ex;` — resets the stack trace. Use `throw;`.
    4. Catching Exception to control flow. Use TryParse/TryGet
       patterns for expected failures; exceptions for exceptional.
    5. Count() > 0 instead of Any(); First() on possibly-empty
       sequences instead of FirstOrDefault().
    6. Missing a case in a switch expression — heed CS8509; at
       runtime it throws SwitchExpressionException.
*/

#:property Nullable=enable
#:property InvariantGlobalization=true

using System.Linq.Expressions;
using System.Runtime.ExceptionServices;

Console.WriteLine("== delegates & lambdas"); DelegatesDemo.Run();
Console.WriteLine("== pattern matching"); PatternsDemo.Run();
Console.WriteLine("== LINQ"); LinqDemo.Run();
Console.WriteLine("== exceptions"); ExceptionsDemo.Run();

// ============================================================
// SECTION 1: DELEGATES, LAMBDAS, CLOSURES, LOCAL FUNCTIONS
// ============================================================
public delegate decimal FeeCalculator(decimal amount);       // custom delegate type

static class DelegatesDemo
{
    static decimal FlatFee(decimal amount) => 0.30m;
    public static void Run()
    {
        FeeCalculator flat = FlatFee;                          // method group conversion
        FeeCalculator pct = amt => Math.Round(amt * 0.029m, 2);
        FeeCalculator combined = a => flat(a) + pct(a);
        Console.WriteLine($"   fee on 100: flat={flat(100)} pct={pct(100)} combined={combined(100)}");

        Func<int, int, int> add = (a, b) => a + b;
        Action<string> log = msg => Console.WriteLine($"   log: {msg}");
        Predicate<int> isEven = n => n % 2 == 0;
        var parse = (string s) => int.Parse(s);                // natural type (C# 10): Func<string,int>
        log($"add={add(2, 3)} isEven(4)={isEven(4)} parse={parse("7")}");

        // Multicast: += combines; invocation runs all (returns last result).
        Action pipeline = () => Console.Write("   step1 ");
        pipeline += () => Console.Write("step2 ");
        pipeline += () => Console.WriteLine("step3");
        pipeline();

        // CLOSURES capture VARIABLES, not values:
        var counters = new List<Func<int>>();
        int shared = 0;
        for (int i = 0; i < 3; i++) counters.Add(() => i * 10 + shared);   // ONE `i` shared by all iterations of a `for`
        shared = 1;
        Console.WriteLine($"   closure over for-loop variable: [{string.Join(",", counters.Select(f => f()))}] (all see final i=3 and shared=1)");
        var each = new List<Func<int>>();
        foreach (var v in new[] { 1, 2, 3 }) each.Add(() => v);            // foreach gets a fresh v per iteration (C# 5+)
        Console.WriteLine($"   closure over foreach variable: [{string.Join(",", each.Select(f => f()))}]");

        // Static lambdas (C# 9) can't capture — guarantees no hidden allocation.
        Func<int, int> square = static x => x * x;
        // Local functions: recursion, iterators, no delegate allocation when not captured.
        static long Fib(int n) => n < 2 ? n : Fib(n - 1) + Fib(n - 2);
        // C# 14: modifiers on untyped lambda parameters.
        TryParser<int> tryParse = (text, out result) => int.TryParse(text, out result);
        Console.WriteLine($"   static lambda={square(9)} local fn Fib(20)={Fib(20)} tryParse(\"12\")={tryParse("12", out var r12)}→{r12}");

        // Expression trees: code as data (EF Core translates these to SQL).
        Expression<Func<int, bool>> expr = x => x > 5 && x % 2 == 0;
        Console.WriteLine($"   expression tree: {expr.Body} → compiled(8)={expr.Compile()(8)}");
    }
}
public delegate bool TryParser<T>(string text, out T result);

// ============================================================
// SECTION 2: PATTERN MATCHING
// ============================================================
public enum Channel { Online, InStore, Phone }
public sealed record Card(string Bin, string Country, bool IsPrepaid);
public sealed record Txn(string Id, decimal Amount, string Currency, Channel Channel, Card Card, string IpCountry, int TxnsLastHour);

public abstract record Shape;
public sealed record Circle(double R) : Shape;
public sealed record Rect(double W, double H) : Shape;
public sealed record Triangle(double A, double B, double C) : Shape;

static class PatternsDemo
{
    // Rules engine as a switch expression — first match wins, top to bottom.
    static (string Decision, string Reason) Evaluate(Txn t) => t switch
    {
        { Amount: <= 0 }                                      => ("reject", "non-positive amount"),       // property + relational
        { Amount: > 10_000, Channel: Channel.Online }         => ("review", "large online amount"),
        { Card.IsPrepaid: true, Amount: > 500 }               => ("review", "large prepaid"),             // extended property pattern (C# 10)
        { TxnsLastHour: >= 10 }                               => ("reject", "velocity"),
        { Card.Country: var cc, IpCountry: var ip } when cc != ip && t.Channel is Channel.Online
                                                              => ("review", $"geo mismatch {cc}/{ip}"),
        { Currency: not ("USD" or "EUR" or "GBP") }           => ("review", $"unusual currency {t.Currency}"), // logical patterns
        _                                                     => ("approve", "ok"),
    };

    static double Area(Shape s) => s switch
    {
        Circle { R: var r }                     => Math.PI * r * r,
        Rect(var w, var h) when w == h          => w * w,                       // positional (deconstruction) pattern
        Rect(var w, var h)                      => w * h,
        Triangle(var a, var b, var c)           => Heron(a, b, c),
        _ => throw new ArgumentOutOfRangeException(nameof(s)),   // needed: Shape isn't closed (C# 15 adds `closed` hierarchies / unions)
    };
    static double Heron(double a, double b, double c) { var p = (a + b + c) / 2; return Math.Sqrt(p * (p - a) * (p - b) * (p - c)); }

    // List patterns (C# 11): match sequences by position, with slices `..`.
    static string Describe(int[] xs) => xs switch
    {
        []                    => "empty",
        [var only]            => $"one: {only}",
        [var first, .., var last] when first == last => $"bookended by {first}",
        [_, _, ..var rest]    => $"starts with two, then {rest.Length} more",
    };

    // Type patterns with `is`, `not`, null checks.
    static string Classify(object? o) => o switch
    {
        null                       => "null",
        int i and (< 0 or > 100)   => $"int out of range {i}",
        int i                      => $"int {i}",
        string { Length: 0 }       => "empty string",
        string s                   => $"string '{s}'",
        IEnumerable<int> seq       => $"ints x{seq.Count()}",
        _                          => o.GetType().Name,
    };

    public static void Run()
    {
        var card = new Card("424242", "US", IsPrepaid: false);
        Txn[] txns =
        [
            new("t1", 42m, "USD", Channel.InStore, card, "US", 1),
            new("t2", 25_000m, "USD", Channel.Online, card, "US", 1),
            new("t3", 900m, "USD", Channel.Online, card with { IsPrepaid = true }, "US", 1),
            new("t4", 30m, "USD", Channel.Online, card, "RO", 2),
            new("t5", 30m, "JPY", Channel.Phone, card, "US", 2),
            new("t6", 5m, "USD", Channel.Online, card, "US", 14),
        ];
        foreach (var t in txns) { var (d, why) = Evaluate(t); Console.WriteLine($"   {t.Id}: {d,-7} {why}"); }
        Console.WriteLine($"   areas: {string.Join(", ", new Shape[] { new Circle(1), new Rect(2, 2), new Rect(2, 3), new Triangle(3, 4, 5) }.Select(s => Area(s).ToString("F2")))}");
        Console.WriteLine($"   list patterns: {Describe([])} | {Describe([7])} | {Describe([1, 5, 1])} | {Describe([1, 2, 3, 4])}");
        Console.WriteLine($"   type patterns: {Classify(null)} | {Classify(150)} | {Classify(5)} | {Classify("")} | {Classify(new[] { 1, 2 })} | {Classify(3.0)}");
        if (txns[0] is { Card: { Country: "US" } c, Amount: var amt }) Console.WriteLine($"   `is` with nested capture: {c.Bin} {amt}");
        _ = int.TryParse("x", out _);    // discards: _ ignores values you don't need
    }
}

// ============================================================
// SECTION 3: LINQ
// ============================================================
public sealed record Customer(int Id, string Name, string Country);
public sealed record Order(int Id, int CustomerId, DateOnly Date, decimal Total, string Status);

static class LinqDemo
{
    static readonly Customer[] Customers = [new(1, "Acme", "US"), new(2, "Globex", "DE"), new(3, "Initech", "US"), new(4, "Umbrella", "UK")];
    static readonly Order[] Orders =
    [
        new(101, 1, new(2026, 9, 1), 120m, "paid"), new(102, 1, new(2026, 9, 15), 80m, "refunded"),
        new(103, 2, new(2026, 9, 3), 990m, "paid"), new(104, 3, new(2026, 10, 1), 45m, "paid"),
        new(105, 2, new(2026, 10, 2), 310m, "paid"), new(106, 1, new(2026, 10, 5), 60m, "paid"),
    ];

    public static void Run()
    {
        // Deferred execution — the query runs at enumeration, against CURRENT data.
        var list = new List<int> { 1, 2, 3 };
        var evens = list.Where(x => x % 2 == 0);
        list.Add(4);
        Console.WriteLine($"   deferred: evens=[{string.Join(",", evens)}] (sees the 4 added after the query was defined)");

        // Query syntax ≡ method syntax (compiler rewrites it).
        var q = from o in Orders
                where o.Status == "paid"
                join c in Customers on o.CustomerId equals c.Id
                group o by c.Name into g
                orderby g.Sum(o => o.Total) descending
                select new { Customer = g.Key, Revenue = g.Sum(o => o.Total), Count = g.Count() };
        Console.WriteLine($"   revenue (query syntax): {string.Join("; ", q.Select(x => $"{x.Customer}={x.Revenue}/{x.Count}"))}");

        var m = Orders.Where(o => o.Status == "paid")
                      .Join(Customers, o => o.CustomerId, c => c.Id, (o, c) => (c.Country, o.Total))
                      .GroupBy(x => x.Country)
                      .Select(g => (Country: g.Key, Total: g.Sum(x => x.Total)))
                      .OrderByDescending(x => x.Total);
        Console.WriteLine($"   revenue by country (method syntax): {string.Join(", ", m)}");

        // .NET 9: CountBy / AggregateBy / Index — no intermediate groupings.
        Console.WriteLine($"   CountBy status: {string.Join(", ", Orders.CountBy(o => o.Status))}");
        Console.WriteLine($"   AggregateBy max per customer: {string.Join(", ", Orders.AggregateBy(o => o.CustomerId, 0m, (max, o) => Math.Max(max, o.Total)))}");
        Console.WriteLine($"   Index(): {string.Join(", ", Customers.Take(2).Index().Select(t => $"{t.Index}:{t.Item.Name}"))}");
        // .NET 10: LeftJoin / RightJoin operators.
        var withOrders = Customers.LeftJoin(Orders, c => c.Id, o => o.CustomerId, (c, o) => (c.Name, OrderId: o?.Id))
                                  .Where(x => x.OrderId is null).Select(x => x.Name);
        Console.WriteLine($"   LeftJoin customers without orders: {string.Join(",", withOrders)}");

        // Sets, partitioning, element, quantifiers, aggregation
        Console.WriteLine($"   DistinctBy country: {string.Join(",", Customers.DistinctBy(c => c.Country).Select(c => c.Name))} | "
            + $"Chunk(4): {Orders.Chunk(4).Count()} chunks | MaxBy: {Orders.MaxBy(o => o.Total)!.Id} | "
            + $"Any refunded: {Orders.Any(o => o.Status == "refunded")} | All > 0: {Orders.All(o => o.Total > 0)}");
        Console.WriteLine($"   Zip: {string.Join(",", new[] { "a", "b" }.Zip([1, 2], (s, n) => s + n))} | SelectMany: {Customers.SelectMany(c => c.Name.Take(1)).Count()} | "
            + $"ToLookup US: {Customers.ToLookup(c => c.Country)["US"].Count()} | FirstOrDefault(none): {Orders.FirstOrDefault(o => o.Total > 5000)?.Id.ToString() ?? "null"}");
        // Running total via Aggregate with a seed + Scan-like Select with state:
        decimal running = 0;
        Console.WriteLine($"   running totals: {string.Join(",", Orders.OrderBy(o => o.Date).Select(o => running += o.Total))}");
        // IQueryable (EF Core) vs IEnumerable: AsEnumerable() switches from SQL to in-memory —
        // filters after that point run on the client. Watch where it happens.
    }
}

// ============================================================
// SECTION 4: EXCEPTIONS
// ============================================================
// Hierarchy: Exception → SystemException (NullReference, InvalidOperation,
// ArgumentException → ArgumentNull/OutOfRange, IO, Format...) and your own.
// All exceptions are unchecked in C# — document with <exception> XML docs.
public sealed class InsufficientFundsException(string accountId, decimal shortfall)
    : Exception($"Account {accountId} is short by {shortfall:F2}")
{
    public string AccountId { get; } = accountId;
    public decimal Shortfall { get; } = shortfall;
}

static class ExceptionsDemo
{
    static void Withdraw(string id, decimal balance, decimal amount)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(id);                 // guard helpers (.NET 6-8)
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(amount);
        if (amount > balance) throw new InsufficientFundsException(id, amount - balance);
    }

    static void Rethrow(bool preserve)
    {
        try { Withdraw("acc-1", 10, 50); }
        catch (InsufficientFundsException) when (preserve) { throw; }   // exception FILTER + rethrow keeps the stack
        catch (InsufficientFundsException ex) { throw new InvalidOperationException("withdrawal failed", ex); }  // wrap with inner
    }

    public static void Run()
    {
        try { Withdraw("acc-1", 100m, 250m); }
        catch (InsufficientFundsException ex) when (ex.Shortfall > 100)  // filters don't unwind the stack if false
        { Console.WriteLine($"   filtered catch: {ex.Message} (shortfall {ex.Shortfall})"); }

        try { Withdraw("acc-1", 100m, -5m); }
        catch (ArgumentOutOfRangeException ex) { Console.WriteLine($"   guard: {ex.ParamName} → {ex.Message.Split('.')[0]}"); }

        try { Rethrow(preserve: false); }
        catch (InvalidOperationException ex) { Console.WriteLine($"   wrapped: {ex.Message} ← inner: {ex.InnerException?.GetType().Name}"); }

        // finally + using: deterministic cleanup.
        var events = new List<string>();
        try
        {
            using var scope = new Scope(events);                          // using declaration (C# 8): disposed at end of block
            events.Add("work");
            throw new TimeoutException("upstream timed out");
        }
        catch (TimeoutException) { events.Add("caught"); }
        finally { events.Add("finally"); }
        Console.WriteLine($"   order: {string.Join(" → ", events)}");

        // Capture an exception on one thread and rethrow elsewhere with its original stack:
        ExceptionDispatchInfo? captured = null;
        try { throw new FormatException("bad csv row 17"); } catch (FormatException ex) { captured = ExceptionDispatchInfo.Capture(ex); }
        try { captured.Throw(); } catch (FormatException ex) { Console.WriteLine($"   EDI rethrow: {ex.Message}"); }

        // AggregateException from Task.WaitAll / Parallel; `await` unwraps the first.
        try { Task.WaitAll(Task.Run(() => throw new InvalidOperationException("a")), Task.Run(() => throw new ArgumentException("b"))); }
        catch (AggregateException ae) { Console.WriteLine($"   AggregateException with {ae.Flatten().InnerExceptions.Count} inner exceptions"); }
        // Guidelines: catch specific types; never swallow silently; log once at
        // the boundary; don't use exceptions for expected outcomes (use Try*/Result);
        // ASP.NET Core: IExceptionHandler + ProblemDetails (RFC 9457) at the edge (L07).
    }

    sealed class Scope(List<string> events) : IDisposable
    {
        public void Dispose() => events.Add("disposed");
    }
}
