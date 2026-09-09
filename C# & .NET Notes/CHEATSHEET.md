# C# & .NET — In-Depth Reference

The dominant stack in enterprise/finance shops standardized on Microsoft
technology. Modern .NET (Core/.NET 5+) is genuinely cross-platform,
open-source, and a real competitor to Java/Go/Node in performance.


## 1. .NET's EVOLUTION — WHY "CORE" MATTERED

**.NET Framework** (Windows-only, the original, now legacy) vs
**.NET Core → .NET 5+** (cross-platform, open-source, the unified modern
platform) — this rebrand/unification (.NET Framework, .NET Core, and
Xamarin/Mono all merged into one ".NET" going forward from .NET 5) is
worth knowing precisely because job postings and legacy codebases still
reference "framework" vs "core," and they are genuinely different
runtimes with real compatibility gaps, not just version numbers.

**The CLR (Common Language Runtime)** is .NET's equivalent of the JVM —
compiles C#/F#/VB.NET source to IL (Intermediate Language), then JIT-
compiles to native code at runtime, with its own generational garbage
collector conceptually similar to the JVM's (see Java & JVM deep dive for
the shared generational-GC mental model, applicable here too).


## 2. MODERN C# LANGUAGE FEATURES

```csharp
// Records (C# 9+) — immutable data types with value-based equality, like Java's records
public record Point(int X, int Y);

// Pattern matching — genuinely powerful, beyond simple switch
var description = shape switch
{
    Circle { Radius: > 10 } => "big circle",
    Circle => "circle",
    Rectangle { Width: var w, Height: var h } when w == h => "square",
    _ => "unknown"
};

// Nullable reference types (C# 8+) — compile-time null-safety warnings
string? maybeNull = GetValue();     // The ? makes intent explicit
string definitelyNotNull = "value";  // Compiler warns if this could actually be null

// async/await — first-class, mature async support
public async Task<Order> GetOrderAsync(int id)
{
    var order = await _repository.FindByIdAsync(id);
    return order ?? throw new NotFoundException();
}
```

**LINQ (Language Integrated Query)** — SQL-like query syntax integrated
directly into C#, operating over in-memory collections OR translated to
actual SQL when querying a database via Entity Framework — a genuinely
distinctive language feature most other mainstream languages don't have
built-in at this level of integration.

```csharp
var topCustomers = orders
    .Where(o => o.Total > 100)
    .GroupBy(o => o.CustomerId)
    .Select(g => new { CustomerId = g.Key, Total = g.Sum(o => o.Total) })
    .OrderByDescending(x => x.Total)
    .Take(10);
```


## 3. ASP.NET CORE — THE WEB FRAMEWORK

- **Minimal APIs** (newer, .NET 6+) — lightweight endpoint definitions
  without full MVC controller boilerplate, similar philosophy to
  FastAPI/Express for simpler APIs.
- **MVC / Web API controllers** — the traditional, still-dominant pattern
  for larger enterprise APIs, with attribute-based routing
  (`[HttpGet("orders/{id}")]`) and built-in model binding/validation.
- **Dependency Injection** — built INTO the framework natively (unlike
  Java/Spring needing a separate DI framework bolted on) — every ASP.NET
  Core app registers services in a container at startup by default.
- **Middleware pipeline** — request/response processing as an explicit,
  ordered chain (`app.UseAuthentication(); app.UseAuthorization();
  app.UseEndpoints(...)`) — genuinely clear, explicit control over
  cross-cutting request handling.

```csharp
// Program.cs (modern minimal hosting model, .NET 6+)
var builder = WebApplication.CreateBuilder(args);
builder.Services.AddScoped<IOrderService, OrderService>();
builder.Services.AddDbContext<AppDbContext>(opt => opt.UseSqlServer(connectionString));

var app = builder.Build();
app.MapGet("/orders/{id}", async (int id, IOrderService svc) => await svc.GetByIdAsync(id));
app.Run();
```


## 4. ENTITY FRAMEWORK CORE (ORM)

The dominant .NET ORM — Code-First migrations (define models in C#,
generate/apply schema migrations) or Database-First (scaffold models from
an existing schema). LINQ queries against `DbSet<T>` translate to SQL at
query-execution time — a common real gotcha: `.Where()` clauses execute
IN THE DATABASE (translated to SQL), but calling a C#-only method inside
a LINQ query that EF can't translate throws a runtime error, not a
compile error — a genuinely common "why did this query that looks fine suddenly fail" production surprise.


## 5. NICHE BUT REAL

- **Blazor** — building interactive web UIs in C# instead of JavaScript,
  running either server-side (SignalR-based real-time updates) or
  client-side (compiled to WebAssembly, running actually IN the browser)
  — a genuinely distinctive .NET-ecosystem answer to "full-stack in one language."
- **gRPC in .NET** — first-class, well-integrated support, common in
  enterprise microservices architectures already standardized on .NET.
- **NuGet** — .NET's package manager, the direct equivalent of npm/pip —
  worth knowing by name for the ecosystem-fluency signal.
- **Span<T> / Memory<T>** — low-allocation, high-performance memory
  access primitives (avoiding array copies/heap allocations in
  performance-critical code) — a real, meaningful performance tool in
  .NET's evolution toward being genuinely competitive with lower-level
  languages for high-throughput services.
- **Source generators** — compile-time code generation (similar spirit to
  Rust macros or Java annotation processors) increasingly used by
  System.Text.Json and other modern .NET libraries to generate
  serialization code at COMPILE time instead of relying on slower runtime reflection.
