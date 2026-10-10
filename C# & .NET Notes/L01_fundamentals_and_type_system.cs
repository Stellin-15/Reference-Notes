// ============================================================
// L01: C# Fundamentals & the .NET Type System (C# 14 / .NET 10)
// ============================================================
// WHAT: Microsoft Learn "C# Fundamentals" — program structure
//       (file-based apps, top-level statements, namespaces),
//       the common type system (value vs reference types, the
//       built-in types, boxing), nullable value and reference
//       types, var/target-typed new, strings (interpolation, raw
//       literals, UTF-8 literals), tuples & deconstruction,
//       structs vs classes vs records, enums & flags, operators
//       (null-coalescing, null-conditional incl. C# 14
//       assignment), checked arithmetic, decimal for money,
//       arrays, ranges/indices, collection expressions.
// WHY:  C#'s type system decides performance and correctness:
//       struct copies, boxing allocations, nullable warnings you
//       silence instead of fix, and decimal-vs-double. Get this
//       layer right and LINQ, async and ASP.NET Core make sense.
// LEVEL: Foundation
// RUN:   dotnet run L01_fundamentals_and_type_system.cs   (.NET 10 SDK)
// SOURCE: learn.microsoft.com/dotnet/csharp/fundamentals/*,
//         /language-reference/builtin-types/*, What's new in C# 12-14
// ============================================================
/*
CONCEPT OVERVIEW:
    C# compiles (Roslyn) to IL in an assembly; the CLR JIT-compiles
    IL to machine code (or Native AOT compiles ahead of time).
    Every type derives from System.Object. VALUE types (struct,
    enum, the numeric primitives, bool, char, tuples) are copied
    on assignment and live inline (stack/fields/arrays). REFERENCE
    types (class, record, interface, delegate, string, arrays)
    live on the GC heap and are accessed via references.
    Since C# 8, "nullable reference types" (NRT) make `string`
    mean non-null and `string?` maybe-null — enforced by compiler
    warnings (enabled by default in new projects and file-based apps).

PRODUCTION USE CASE:
    A pricing engine's core types: a Money struct using decimal,
    a Currency enum, an immutable Quote record, and parsing of
    untrusted input with TryParse + nullable flow analysis.

COMMON MISTAKES:
    1. double/float for money. Use decimal (base-10, 28-29 digits).
    2. Mutable structs — modifying a copy (e.g. via a List indexer
       or a readonly field) silently changes nothing.
    3. Boxing in hot paths: value type → object/interface allocates.
    4. Silencing nullable warnings with `!` instead of handling null.
    5. `==` on strings is VALUE equality in C# (unlike Java), but
       culture-sensitive comparisons (ToUpper(), CompareTo) differ
       by machine locale — use StringComparison.Ordinal(IgnoreCase).
    6. Integer overflow wraps silently by default (unchecked).
*/

#:property Nullable=enable
#:property InvariantGlobalization=true

using System.Globalization;
using System.Text;

// ============================================================
// SECTION 1: PROGRAM STRUCTURE
// ============================================================
// FILE-BASED APPS (.NET 10): one .cs file, no .csproj, run with
// `dotnet run file.cs`. Directives at the top configure the build:
//   #:package Humanizer@2.14.1      — NuGet package reference
//   #:sdk Microsoft.NET.Sdk.Web     — choose SDK (web apps! see L07)
//   #:property LangVersion=preview  — any MSBuild property
// `dotnet project convert file.cs` turns it into a normal project.
// On Unix, a `#!/usr/bin/env dotnet` shebang makes the file executable.
//
// TOP-LEVEL STATEMENTS (C# 9): the statements below ARE Main. `args`
// is in scope; `return 1;` sets the exit code; `await` is allowed.
// Exactly one file per project may have top-level statements, and
// type declarations must come after them.

Section.Header("built-in types");
BuiltIns.Show();
Section.Header("value vs reference semantics");
Semantics.Show();
Section.Header("nullable types");
Nullability.Show(args);
Section.Header("strings");
Strings.Show();
Section.Header("tuples, records, structs");
DataTypes.Show();
Section.Header("operators & arithmetic");
Operators.Show();
Section.Header("arrays, ranges, collection expressions");
Collections.Show();
Section.Header("end-to-end: quote calculator");
QuoteDemo.Run();
return 0;

static class Section
{
    public static void Header(string title) => Console.WriteLine($"== {title}");
}

// ============================================================
// SECTION 2: BUILT-IN TYPES
// ============================================================
//  C# keyword  .NET type        size     notes
//  sbyte/byte  SByte/Byte       8 bit    byte is unsigned 0..255
//  short/ushort Int16/UInt16    16 bit
//  int/uint    Int32/UInt32     32 bit   default for integer literals
//  long/ulong  Int64/UInt64     64 bit   suffix L / UL
//  nint/nuint  IntPtr/UIntPtr   native   pointer-sized
//  Int128/UInt128               128 bit  (.NET 7)
//  float       Single           32 bit   suffix f, ~6-9 digits
//  double      Double           64 bit   ~15-17 digits
//  Half                         16 bit   ML/graphics storage
//  decimal     Decimal          128 bit  suffix m, base-10, ~28-29 digits — MONEY
//  bool        Boolean
//  char        Char             16 bit   UTF-16 code unit
//  string      String           ref      immutable UTF-16
//  object      Object           ref      root of everything
static class BuiltIns
{
    public static void Show()
    {
        int million = 1_000_000;
        long big = 9_223_372_036_854_775_807L;
        var hex = 0xFF; var bin = 0b_1010_1010;
        decimal price = 19.99m;
        double ratio = 0.1 + 0.2;
        Console.WriteLine($"   ints: {million} {big} {hex} {bin}  Int128.Max digits={Int128.MaxValue.ToString().Length}");
        Console.WriteLine($"   0.1+0.2 as double = {ratio:R}  vs decimal = {0.1m + 0.2m}  price*3 = {price * 3}");
        Console.WriteLine($"   default(int)={default(int)} default(bool)={default(bool)} default(string)={default(string) ?? "null"}");
        // Type keywords are aliases: int ≡ System.Int32, string ≡ System.String.
        Console.WriteLine($"   typeof(int)={typeof(int).FullName} sizeof(decimal)={sizeof(decimal)} char.IsLetter('é')={char.IsLetter('é')}");
        // Parsing: Parse throws on bad input; TryParse returns bool + out value.
        Console.WriteLine($"   TryParse(\"42x\") → {int.TryParse("42x", out var bad)} ({bad}); Parse invariant \"1,234.5\" → {double.Parse("1,234.5", CultureInfo.InvariantCulture)}");
    }
}

// ============================================================
// SECTION 3: VALUE VS REFERENCE SEMANTICS, BOXING
// ============================================================
struct PointS { public int X; }                        // value type
class PointC { public int X; }                         // reference type

static class Semantics
{
    static void Bump(PointS p) => p.X++;                 // gets a COPY
    static void Bump(PointC p) => p.X++;                 // gets a copy of the REFERENCE
    static void BumpRef(ref PointS p) => p.X++;          // ref: alias the caller's variable

    public static void Show()
    {
        var s1 = new PointS { X = 1 }; var s2 = s1; s2.X = 99;
        var c1 = new PointC { X = 1 }; var c2 = c1; c2.X = 99;
        Console.WriteLine($"   struct copy: s1.X={s1.X}  class alias: c1.X={c1.X}");
        Bump(s1); Bump(c1); BumpRef(ref s1);
        Console.WriteLine($"   after Bump: struct={s1.X} (only ref changed it), class={c1.X}");

        // Mutable struct trap: List<T> indexer returns a COPY.
        var list = new List<PointS> { new() { X = 1 } };
        // list[0].X = 5;   // compile error CS1612: cannot modify the return value (it's a copy)
        var tmp = list[0]; tmp.X = 5; list[0] = tmp;      // read-modify-write is required
        Console.WriteLine($"   list[0].X after write-back={list[0].X}");

        // Boxing: value → object allocates a heap copy.
        int n = 42;
        object boxed = n;                                  // box
        int unboxed = (int)boxed;                          // unbox (exact type required)
        n = 7;
        Console.WriteLine($"   boxed copy unaffected: {boxed}, unboxed={unboxed}; ReferenceEquals(boxed, boxed)={ReferenceEquals(boxed, boxed)}");
        // Generics (List<int>) avoid boxing; non-generic ArrayList and
        // interface calls on structs (IComparable) may box.
        // `in` (readonly ref) parameters pass large structs without copying;
        // `out` parameters must be assigned by the callee.
    }
}

// ============================================================
// SECTION 4: NULLABLE VALUE & REFERENCE TYPES
// ============================================================
static class Nullability
{
    static string? FindEmail(string user) => user == "ada" ? "ada@example.com" : null;

    public static void Show(string[] args)
    {
        int? maybe = null;                                 // Nullable<int>
        Console.WriteLine($"   int?: HasValue={maybe.HasValue} GetValueOrDefault={maybe.GetValueOrDefault()} ?? → {maybe ?? -1}");

        string? email = FindEmail("bob");
        // Console.WriteLine(email.Length);   // warning CS8602: possible null dereference
        Console.WriteLine($"   ?. and ??: {email?.Length ?? 0}");
        if (email is not null) Console.WriteLine(email.Length);   // flow analysis: non-null here
        email ??= "fallback@example.com";                  // assign if null
        Console.WriteLine($"   ??= → {email}");

        // C# 14 null-conditional ASSIGNMENT: RHS evaluated only if target non-null.
        Customer? c = args.Length > 99 ? new Customer() : null;
        c?.Tier = ComputeTier();                           // ComputeTier NOT called (c is null)
        Customer? real = new Customer();
        real?.Tier = ComputeTier();                        // target non-null → RHS runs
        Console.WriteLine($"   null-conditional assignment: real.Tier={real?.Tier}, calls={_calls}");

        // Null-forgiving `!` silences the warning — a promise, unchecked at runtime.
        // Attributes like [NotNullWhen(true)], [MaybeNull], [MemberNotNull] teach
        // the analyzer about your APIs (TryGet patterns).
        // ArgumentNullException.ThrowIfNull(x) / ArgumentException.ThrowIfNullOrEmpty(s) for guards.
    }
    static int _calls;
    static string ComputeTier() { _calls++; return "gold"; }
    sealed class Customer { public string Tier { get; set; } = "basic"; }
}

// ============================================================
// SECTION 5: STRINGS
// ============================================================
static class Strings
{
    public static void Show()
    {
        string a = "hello", b = string.Concat("hel", "lo");
        Console.WriteLine($"   == compares VALUE: {a == b}; ReferenceEquals: {ReferenceEquals(a, b)}");
        // Interpolation with alignment and format: {value,alignment:format}
        decimal amount = 1234.5m;
        Console.WriteLine($"   [{"left",-8}] [{amount,12:N2}] [{0.256,6:P1}] [{DateTime.UnixEpoch:yyyy-MM-dd}]");
        // Verbatim (@) and RAW string literals (C# 11) — no escaping, multi-line,
        // indentation trimmed to the closing quotes; $$ means {{x}} interpolates.
        string path = @"C:\data\orders.csv";
        string json = $$"""
            {
              "file": "{{path.Replace("\\", "/")}}",
              "amount": {{amount}}
            }
            """;
        Console.WriteLine(json);
        // UTF-8 string literals (C# 11): ReadOnlySpan<byte> with no runtime encoding cost.
        ReadOnlySpan<byte> utf8 = "Grüße"u8;
        Console.WriteLine($"   \"Grüße\"u8 bytes={utf8.Length}, string.Length={"Grüße".Length}");
        // StringBuilder for loops; string.Join/Create/Format for one-shots.
        var sb = new StringBuilder();
        for (int i = 0; i < 3; i++) sb.Append(i).Append(';');
        Console.WriteLine($"   builder={sb}  split={string.Join('|', "a,b,,c".Split(',', StringSplitOptions.RemoveEmptyEntries))}");
        // Culture & comparison: ALWAYS specify for identifiers.
        Console.WriteLine($"   Ordinal ignore-case equals: {string.Equals("FILE", "file", StringComparison.OrdinalIgnoreCase)}  "
            + $"StartsWith ordinal: {"Report.pdf".EndsWith(".PDF", StringComparison.OrdinalIgnoreCase)}");
        // The Turkish-I problem: "i".ToUpper(new CultureInfo("tr-TR")) == "İ" — why ToUpperInvariant exists.
    }
}

// ============================================================
// SECTION 6: TUPLES, RECORDS, STRUCTS, ENUMS
// ============================================================
// record (class) — reference type with value equality, ToString,
// `with` expressions, deconstruction. record struct (C# 10) — value type.
public record Person(string Name, int Age);
public readonly record struct Coordinate(double Lat, double Lon);

[Flags]
public enum Permissions { None = 0, Read = 1, Write = 2, Delete = 4, Admin = Read | Write | Delete }

static class DataTypes
{
    static (int Min, int Max, double Avg) Stats(IEnumerable<int> xs)   // named tuple return
    {
        var list = xs.ToList();
        return (list.Min(), list.Max(), list.Average());
    }

    public static void Show()
    {
        var (min, max, avg) = Stats([4, 8, 15, 16, 23, 42]);           // deconstruction
        var t = Stats([1, 2]);
        Console.WriteLine($"   tuple: min={min} max={max} avg={avg:F2}  t.Max={t.Max}  equality={(1, "a") == (1, "a")}");
        (min, max) = (max, min);                                       // swap via tuples
        Console.WriteLine($"   swapped: {min} {max}");

        var ada = new Person("Ada", 36);
        var older = ada with { Age = 37 };                             // non-destructive mutation
        Console.WriteLine($"   record: {ada}  equals copy? {ada == new Person("Ada", 36)}  with → {older}");
        var (name, age) = older;
        Console.WriteLine($"   deconstructed: {name}/{age}  record struct: {new Coordinate(51.5, -0.12)}");

        var perms = Permissions.Read | Permissions.Write;
        Console.WriteLine($"   flags: {perms}  HasFlag(Write)={perms.HasFlag(Permissions.Write)}  Admin={Permissions.Admin}  "
            + $"parse=\"{Enum.Parse<Permissions>("Delete")}\"  undefined cast={(Permissions)64} (enums aren't validated!)");
        // Choose: class (identity, mutable, inheritance), record (immutable data,
        // value equality), struct (small ≤16 bytes, short-lived, value semantics —
        // make it `readonly struct`), record struct (small value data).
    }
}

// ============================================================
// SECTION 7: OPERATORS & ARITHMETIC
// ============================================================
static class Operators
{
    public static void Show()
    {
        int max = int.MaxValue;
        Console.WriteLine($"   unchecked overflow: {unchecked(max + 1)}");
        try { _ = checked(max + 1); }
        catch (OverflowException) { Console.WriteLine("   checked(max + 1) → OverflowException"); }
        // <CheckForOverflowUnderflow>true</CheckForOverflowUnderflow> makes checked the project default.
        Console.WriteLine($"   int division 7/2={7 / 2}  7%-2={7 % -2}  7.0/2={7.0 / 2}  Math.DivRem={Math.DivRem(7, 2)}");
        Console.WriteLine($"   decimal rounding: {Math.Round(2.345m, 2)} (banker's)  {Math.Round(2.345m, 2, MidpointRounding.AwayFromZero)} (away)");
        // is / as / switch-expression preview (L03 goes deep on patterns):
        object o = 3.5;
        string kind = o switch { int i => $"int {i}", double d when d > 3 => $"big double {d}", _ => "other" };
        Console.WriteLine($"   pattern switch: {kind}   o as string → {(o as string) ?? "null"}");
        // Shifts: >>> unsigned right shift (C# 11).
        Console.WriteLine($"   -16 >> 2 = {-16 >> 2}, -16 >>> 28 = {-16 >>> 28}");
    }
}

// ============================================================
// SECTION 8: ARRAYS, INDICES, RANGES, COLLECTION EXPRESSIONS
// ============================================================
static class Collections
{
    public static void Show()
    {
        int[] nums = [5, 3, 9, 1, 7];                  // collection expression (C# 12)
        int[,] grid = { { 1, 2 }, { 3, 4 } };           // rectangular
        int[][] jagged = [[1], [2, 3]];                 // jagged
        Array.Sort(nums);
        Console.WriteLine($"   sorted=[{string.Join(",", nums)}] last={nums[^1]} slice={string.Join(",", nums[1..^1])} grid[1,0]={grid[1, 0]} jagged[1][1]={jagged[1][1]}");
        List<int> list = [.. nums, 100];                // spread
        HashSet<string> tags = ["a", "b", "a"];
        Dictionary<string, int> stock = new() { ["A"] = 3, ["B"] = 0 };  // index initializer
        Console.WriteLine($"   list={string.Join(",", list)} set count={tags.Count} stock[A]={stock["A"]} TryGetValue(Z)={stock.TryGetValue("Z", out _)}");
        // Span-based slicing doesn't copy (L04): nums.AsSpan(1, 3).
    }
}

// ============================================================
// SECTION 9: END-TO-END — QUOTE CALCULATOR
// ============================================================
public enum Currency { USD, EUR, GBP }

public readonly record struct Money(decimal Amount, Currency Currency)
{
    public static Money operator +(Money a, Money b) =>
        a.Currency == b.Currency ? new(a.Amount + b.Amount, a.Currency) : throw new InvalidOperationException("currency mismatch");
    public static Money operator *(Money a, decimal k) => new(Math.Round(a.Amount * k, 2, MidpointRounding.ToEven), a.Currency);
    public override string ToString() => $"{Amount:0.00} {Currency}";
}

public sealed record QuoteLine(string Sku, int Quantity, Money UnitPrice);

public sealed record Quote(IReadOnlyList<QuoteLine> Lines, decimal TaxRate)
{
    public Money Subtotal => Lines.Aggregate(new Money(0, Lines[0].UnitPrice.Currency), (acc, l) => acc + l.UnitPrice * l.Quantity);
    public Money Tax => Subtotal * TaxRate;
    public Money Total => Subtotal + Tax;
}

static class QuoteDemo
{
    // Parse "SKU,qty,price" rows from untrusted input; skip bad rows with a reason.
    static QuoteLine? ParseLine(string row, out string? error)
    {
        var parts = row.Split(',', StringSplitOptions.TrimEntries);
        error = null;
        if (parts is not [var sku, var q, var p]) { error = $"expected 3 fields: '{row}'"; return null; }   // list pattern
        if (!int.TryParse(q, out int qty) || qty <= 0) { error = $"bad quantity '{q}'"; return null; }
        if (!decimal.TryParse(p, NumberStyles.Number, CultureInfo.InvariantCulture, out decimal price)) { error = $"bad price '{p}'"; return null; }
        return new QuoteLine(sku, qty, new Money(price, Currency.USD));
    }

    public static void Run()
    {
        string[] rows = ["A-1, 3, 19.99", "B-2, 1, 249.00", "C-3, zero, 1", "D-4, 2", "E-5, 12, 0.35"];
        var lines = new List<QuoteLine>();
        foreach (var row in rows)
        {
            if (ParseLine(row, out var err) is { } line) lines.Add(line);   // property pattern null check
            else Console.WriteLine($"   skipped: {err}");
        }
        var quote = new Quote(lines, 0.0825m);
        Console.WriteLine($"   lines={quote.Lines.Count} subtotal={quote.Subtotal} tax={quote.Tax} total={quote.Total}");
    }
}
