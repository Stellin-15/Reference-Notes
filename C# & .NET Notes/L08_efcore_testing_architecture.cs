// ============================================================
// L08: EF Core 10, Testing, Architecture & Shipping .NET
// ============================================================
// WHAT: Microsoft Learn "Entity Framework Core" (DbContext,
//       modelling, relationships, migrations, querying & LINQ
//       translation, loading strategies, change tracking,
//       saving, transactions, concurrency, bulk ExecuteUpdate/
//       ExecuteDelete, complex types & JSON, interceptors,
//       performance), ".NET testing" (xUnit v3/MSTest/NUnit,
//       WebApplicationFactory, Testcontainers), architecture
//       guides (Clean Architecture, vertical slices, modular
//       monolith), .NET Aspire, container publishing, and the
//       road ahead (.NET 11 / C# 15 unions & closed hierarchies).
// WHY:  Data access is where .NET apps lose most of their
//       performance (N+1 queries, tracking overhead, client-side
//       evaluation) and correctness (lost updates without
//       concurrency tokens). Architecture and tests decide
//       whether the codebase survives its third year.
// LEVEL: Advanced → Architect
// RUN:   dotnet run L08_efcore_testing_architecture.cs
//        (restores Microsoft.EntityFrameworkCore.Sqlite from NuGet on first run)
// SOURCE: learn.microsoft.com/ef/core/* (What's new in EF Core 8-10),
//         /dotnet/core/testing/*, /aspnet/core/test/integration-tests,
//         /dotnet/architecture/modern-web-apps-azure/*, /dotnet/aspire/*,
//         /dotnet/core/containers/*, What's new in C# 15 (preview)
// ============================================================
/*
CONCEPT OVERVIEW:
    EF Core maps classes (entities) to tables. A DbContext is a
    unit of work + identity map: it TRACKS loaded entities, detects
    changes, and SaveChanges() writes them in one transaction.
    LINQ against DbSet<T> is an IQueryable: the provider translates
    the expression tree to SQL — nothing runs until enumeration.
    DbContext is NOT thread-safe and should be short-lived (one per
    request — AddDbContext registers it Scoped; AddDbContextPool reuses
    instances for throughput).

PRODUCTION USE CASE:
    A small order-management data layer on SQLite (swap the
    provider for SQL Server/PostgreSQL in production): customers,
    orders with line items and an owned Address, optimistic
    concurrency on stock, bulk price updates, projections for
    read endpoints, and the queries logged so you can see the SQL.

COMMON MISTAKES:
    1. N+1: lazy loading or querying inside a loop. Use Include,
       projections (Select), or split queries.
    2. Tracking queries for read-only endpoints. Use AsNoTracking()
       or project to DTOs (projections are never tracked).
    3. Calling ToList() too early → filtering in memory.
    4. One DbContext shared across threads or held as a singleton.
    5. No concurrency token → last writer silently wins.
    6. EnsureCreated() in production — use migrations
       (`dotnet ef migrations add`, `dotnet ef database update`,
       or migration bundles in CI/CD).
*/

#:package Microsoft.EntityFrameworkCore.Sqlite@10.0.*
#:property Nullable=enable
#:property InvariantGlobalization=true
#:property PublishAot=false

using System.ComponentModel.DataAnnotations;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.Logging;

// ============================================================
// SECTION 1: SETUP — in-memory SQLite kept alive by an open connection
// ============================================================
using var connection = new SqliteConnection("DataSource=:memory:");
connection.Open();
var sqlLog = new List<string>();
DbContextOptions<ShopContext> options = new DbContextOptionsBuilder<ShopContext>()
    .UseSqlite(connection)
    .LogTo(msg => sqlLog.Add(msg), [DbLoggerCategory.Database.Command.Name], LogLevel.Information)
    .AddInterceptors(new AuditInterceptor())
    .Options;

using (var db = new ShopContext(options))
{
    db.Database.EnsureCreated();                         // demo only — migrations in real apps
    Seed(db);
}
Console.WriteLine($"== schema created, seeded ({sqlLog.Count} SQL commands so far)");

// ============================================================
// SECTION 2: QUERYING — translation, projection, loading strategies
// ============================================================
using (var db = new ShopContext(options))
{
    // Inspect the SQL without running it:
    var q = db.Orders.Where(o => o.Total > 50).OrderByDescending(o => o.PlacedAt).Select(o => new { o.Id, o.Total, Customer = o.Customer.Name });
    Console.WriteLine("== ToQueryString():\n   " + q.ToQueryString().Replace("\n", "\n   "));
    Console.WriteLine($"   results: {string.Join(", ", q.ToList().Select(x => $"#{x.Id} {x.Customer} {x.Total}"))}");

    // N+1 vs Include vs projection — count the round-trips.
    sqlLog.Clear();
    foreach (var c in db.Customers.AsNoTracking().ToList())
        _ = db.Orders.Count(o => o.CustomerId == c.Id);  // one query PER customer
    int nPlusOne = sqlLog.Count;
    sqlLog.Clear();
    var withOrders = db.Customers.AsNoTracking().Include(c => c.Orders).ThenInclude(o => o.Lines).ToList();
    int include = sqlLog.Count;
    sqlLog.Clear();
    var summary = db.Customers.Select(c => new { c.Name, OrderCount = c.Orders.Count, Spent = c.Orders.Sum(o => o.Total) }).ToList();
    int projection = sqlLog.Count;
    Console.WriteLine($"== round-trips: N+1 loop={nPlusOne}, Include={include}, projection={projection}");
    Console.WriteLine($"   projection: {string.Join(", ", summary.Select(s => $"{s.Name}:{s.OrderCount}/{s.Spent}"))}");
    // AsSplitQuery() splits big Include graphs into one query per collection (avoids cartesian explosion).

    // Owned/complex types and filtering on them:
    var berliners = db.Customers.Where(c => c.ShippingAddress.City == "Berlin").Select(c => c.Name).ToList();
    Console.WriteLine($"   complex-type filter (city=Berlin): {string.Join(",", berliners)}");

    // Global query filter (soft delete) applied automatically; IgnoreQueryFilters() to bypass.
    Console.WriteLine($"   products visible={db.Products.Count()} including soft-deleted={db.Products.IgnoreQueryFilters().Count()}");

    // Raw SQL when you need it — parameterised via interpolation (safe):
    decimal min = 100;
    var expensive = db.Products.FromSql($"SELECT * FROM Products WHERE Price >= {min}").Select(p => p.Sku).ToList();
    Console.WriteLine($"   FromSql (parameterised): {string.Join(",", expensive)}");
    // NEVER FromSqlRaw("... " + userInput) — SQL injection.
}

// ============================================================
// SECTION 3: CHANGE TRACKING, SAVING, TRANSACTIONS
// ============================================================
using (var db = new ShopContext(options))
{
    var order = db.Orders.Include(o => o.Lines).First(o => o.Id == 1);
    order.Lines.Add(new OrderLine { Sku = "C-3", Quantity = 1, UnitPrice = 5m });
    order.Total = order.Lines.Sum(l => l.Quantity * l.UnitPrice);
    Console.WriteLine($"== change tracker before SaveChanges: {db.ChangeTracker.Entries().Count(e => e.State != EntityState.Unchanged)} modified/added entries "
        + $"(order={db.Entry(order).State})");
    db.SaveChanges();                                     // one transaction, batched commands
    Console.WriteLine($"   saved; order 1 total={order.Total}, audit stamp={order.UpdatedAt:HH:mm:ss} (set by interceptor)");

    // Explicit transaction across multiple SaveChanges:
    using var tx = db.Database.BeginTransaction();
    db.Customers.Add(new Customer { Name = "Temp", ShippingAddress = new Address("X", "Y", "00000") });
    db.SaveChanges();
    tx.Rollback();
    Console.WriteLine($"   explicit transaction rolled back → Temp exists: {new ShopContext(options).Customers.Any(c => c.Name == "Temp")}");
}

// ============================================================
// SECTION 4: OPTIMISTIC CONCURRENCY
// ============================================================
{
    using var userA = new ShopContext(options);
    using var userB = new ShopContext(options);
    var pa = userA.Products.Single(p => p.Sku == "A-1");
    var pb = userB.Products.Single(p => p.Sku == "A-1");
    pa.Stock -= 2; userA.SaveChanges();                    // A wins, version bumps
    pb.Stock -= 5;
    try { userB.SaveChanges(); }
    catch (DbUpdateConcurrencyException ex)
    {
        var entry = ex.Entries.Single();
        var dbValues = entry.GetDatabaseValues()!;
        Console.WriteLine($"== concurrency conflict detected: B saw stock={entry.OriginalValues[nameof(Product.Stock)]}, DB now={dbValues[nameof(Product.Stock)]}");
        // Resolve: reload + reapply the intent (here: subtract 5 from the CURRENT value), retry.
        entry.OriginalValues.SetValues(dbValues);
        pb.Stock = (int)dbValues[nameof(Product.Stock)]! - 5;
        userB.SaveChanges();
        Console.WriteLine($"   retried with fresh values → stock={pb.Stock} (both decrements applied: 50-2-5)");
    }
}

// ============================================================
// SECTION 5: BULK OPERATIONS & COMPILED QUERIES
// ============================================================
using (var db = new ShopContext(options))
{
    // ExecuteUpdate/ExecuteDelete (EF 7+): single SQL statement, no entity loading, bypasses tracking.
    int repriced = db.Products.Where(p => p.Sku.StartsWith("B")).ExecuteUpdate(s => s.SetProperty(p => p.Price, p => p.Price * 1.10m));
    int purged = db.Products.IgnoreQueryFilters().Where(p => p.IsDeleted).ExecuteDelete();
    Console.WriteLine($"== bulk: repriced {repriced} product(s), hard-deleted {purged} soft-deleted product(s)");
    var bySku = EF.CompileQuery((ShopContext ctx, string sku) => ctx.Products.AsNoTracking().FirstOrDefault(p => p.Sku == sku));
    Console.WriteLine($"   compiled query B-2 price={bySku(db, "B-2")?.Price}");
}
// Other EF Core 8-10 features worth knowing: complex types (value objects without keys),
// primitive collections (List<string> stored as JSON), JSON columns (OwnsOne(..., b => b.ToJson())),
// LeftJoin/RightJoin LINQ operators (EF 10), named query filters (EF 10), vector search
// (SQL Server 2025 / Azure SQL vector type, EF 10), HierarchyId, temporal tables (SQL Server),
// interceptors (auditing, soft delete, multi-tenancy), DbContext pooling, AOT-precompiled queries.

// ============================================================
// SECTION 6: TESTING (reference)
// ============================================================
// Frameworks: xUnit v3 (most common for new code), MSTest 3/4, NUnit 4, TUnit;
// all run on Microsoft.Testing.Platform as well as VSTest.
//   public class PricingTests
//   {
//       [Theory]
//       [InlineData(10, 0)] [InlineData(100, 10)]
//       public void Discount_applies_over_threshold(decimal amount, decimal expected)
//           => Assert.Equal(expected, new Pricing().Discount(amount));
//   }
// Mocks: NSubstitute / Moq / FakeItEasy for interfaces you own. Time: FakeTimeProvider.
// ASP.NET Core integration tests: WebApplicationFactory<Program> spins up the real
//   pipeline in-memory; override services with ConfigureTestServices.
// Data: Testcontainers.PostgreSql / MsSql for real databases (SQLite in-memory, as
//   here, is fast but differs in SQL dialect & behaviour; EF InMemory provider is
//   NOT a database — avoid it for query tests). Respawn resets DB state between tests.
// Snapshot tests: Verify. Architecture tests: NetArchTest/ArchUnitNET.
// Mutation testing: Stryker.NET. Benchmarks: BenchmarkDotNet. Coverage: coverlet.

// ============================================================
// SECTION 7: ARCHITECTURE & SHIPPING (reference)
// ============================================================
// Layering options:
//   CLEAN / ONION: Domain (entities, rules) ← Application (use cases, interfaces)
//     ← Infrastructure (EF Core, HTTP clients) ← Web (endpoints). Dependencies point inward.
//   VERTICAL SLICES: one folder per feature (endpoint + handler + validation + query),
//     minimal cross-feature abstraction; pairs well with minimal APIs.
//   MODULAR MONOLITH: modules with their own DbContext/schema and explicit contracts;
//     split into services only when a module needs independent scaling/deploys.
// .NET ASPIRE: code-first orchestration of an app + its dependencies for local dev
//   (AppHost: builder.AddPostgres("db"); builder.AddProject<Projects.Api>("api").WithReference(db)),
//   with a dashboard for logs/traces/metrics, service discovery, and deployment manifests.
// CONTAINERS without a Dockerfile:
//   dotnet publish -t:PublishContainer -p:ContainerRepository=orders-api
//   (chiseled Ubuntu base images: mcr.microsoft.com/dotnet/aspnet:10.0-noble-chiseled — non-root,
//   no shell; with Native AOT use runtime-deps:10.0-noble-chiseled).
// CI: dotnet build -warnaserror, dotnet test, dotnet format --verify-no-changes,
//   Central Package Management (Directory.Packages.props), NuGet audit (on by default),
//   SBOM via Microsoft.Sbom.Targets, reproducible builds with Deterministic=true.
// ROAD AHEAD: .NET 11 (STS, Nov 2026) — Runtime Async, Zstandard compression; C# 15 —
//   union types, `closed` class hierarchies (exhaustive switches over class hierarchies),
//   collection-expression arguments, extension indexers, labeled break/continue.
//   .NET 10 remains the LTS (supported to Nov 2028).

// ============================================================
// SECTION 8: MODEL
// ============================================================
static void Seed(ShopContext db)
{
    var acme = new Customer { Name = "Acme", ShippingAddress = new Address("1 Main St", "Austin", "73301") };
    var globex = new Customer { Name = "Globex", ShippingAddress = new Address("5 Unter den Linden", "Berlin", "10117") };
    var initech = new Customer { Name = "Initech", ShippingAddress = new Address("9 Office Park", "Austin", "73344") };
    db.Customers.AddRange(acme, globex, initech);
    db.Products.AddRange(
        new Product { Sku = "A-1", Price = 19.99m, Stock = 50 },
        new Product { Sku = "B-2", Price = 120m, Stock = 5 },
        new Product { Sku = "B-3", Price = 75m, Stock = 0, IsDeleted = true });
    db.Orders.AddRange(
        new Order { Customer = acme, PlacedAt = new DateTime(2026, 9, 1), Lines = [new() { Sku = "A-1", Quantity = 2, UnitPrice = 19.99m }], Total = 39.98m },
        new Order { Customer = acme, PlacedAt = new DateTime(2026, 9, 20), Lines = [new() { Sku = "B-2", Quantity = 1, UnitPrice = 120m }], Total = 120m },
        new Order { Customer = globex, PlacedAt = new DateTime(2026, 10, 2), Lines = [new() { Sku = "A-1", Quantity = 5, UnitPrice = 19.99m }], Total = 99.95m });
    db.SaveChanges();
}

public sealed class ShopContext(DbContextOptions<ShopContext> options) : DbContext(options)
{
    public DbSet<Customer> Customers => Set<Customer>();
    public DbSet<Order> Orders => Set<Order>();
    public DbSet<Product> Products => Set<Product>();

    protected override void OnModelCreating(ModelBuilder b)
    {
        // Fluent API (preferred over attributes for anything non-trivial).
        b.Entity<Customer>(e =>
        {
            e.Property(c => c.Name).HasMaxLength(100).IsRequired();
            e.HasIndex(c => c.Name).IsUnique();
            e.ComplexProperty(c => c.ShippingAddress);             // complex type: columns inline, no key (EF 8)
            e.HasMany(c => c.Orders).WithOne(o => o.Customer).HasForeignKey(o => o.CustomerId).OnDelete(DeleteBehavior.Cascade);
        });
        b.Entity<Order>(e =>
        {
            e.Property(o => o.Total).HasPrecision(18, 2);
            e.HasMany(o => o.Lines).WithOne().HasForeignKey(l => l.OrderId);
            e.HasIndex(o => new { o.CustomerId, o.PlacedAt });     // composite index for "orders by customer by date"
        });
        b.Entity<Product>(e =>
        {
            e.HasKey(p => p.Sku);                                  // natural key
            e.Property(p => p.Price).HasPrecision(18, 2);
            e.Property(p => p.Version).IsConcurrencyToken();       // optimistic concurrency (rowversion on SQL Server)
            e.HasQueryFilter(p => !p.IsDeleted);                   // global filter: soft delete
        });
        // SQLite stores decimal as TEXT and can't ORDER BY/compare it natively in all cases;
        // a converter to double keeps this demo's comparisons in SQL. (Not needed on SQL Server/Postgres.)
        foreach (var p in b.Model.GetEntityTypes().SelectMany(t => t.GetProperties()).Where(p => p.ClrType == typeof(decimal)))
            p.SetProviderClrType(typeof(double));
    }

    // Bump the concurrency version on every update.
    public override int SaveChanges(bool acceptAllChangesOnSuccess)
    {
        foreach (var e in ChangeTracker.Entries<Product>().Where(e => e.State == EntityState.Modified)) e.Entity.Version++;
        return base.SaveChanges(acceptAllChangesOnSuccess);
    }
}

public sealed class Customer
{
    public int Id { get; set; }
    public required string Name { get; set; }
    public required Address ShippingAddress { get; set; }
    public List<Order> Orders { get; set; } = [];
}
public sealed record Address(string Street, string City, string PostalCode);

public sealed class Order : IAudited
{
    public int Id { get; set; }
    public int CustomerId { get; set; }
    public Customer Customer { get; set; } = null!;
    public DateTime PlacedAt { get; set; }
    public decimal Total { get; set; }
    public List<OrderLine> Lines { get; set; } = [];
    public DateTime? UpdatedAt { get; set; }
}
public sealed class OrderLine
{
    public int Id { get; set; }
    public int OrderId { get; set; }
    [MaxLength(20)] public required string Sku { get; set; }
    public int Quantity { get; set; }
    public decimal UnitPrice { get; set; }
}
public sealed class Product
{
    public required string Sku { get; set; }
    public decimal Price { get; set; }
    public int Stock { get; set; }
    public bool IsDeleted { get; set; }
    public int Version { get; set; }
}

public interface IAudited { DateTime? UpdatedAt { get; set; } }

// Interceptor: cross-cutting behaviour on SaveChanges (auditing, soft delete, tenancy).
public sealed class AuditInterceptor : SaveChangesInterceptor
{
    public override InterceptionResult<int> SavingChanges(DbContextEventData eventData, InterceptionResult<int> result)
    {
        foreach (var e in eventData.Context!.ChangeTracker.Entries<IAudited>().Where(e => e.State == EntityState.Modified))
            e.Entity.UpdatedAt = DateTime.UtcNow;
        return result;
    }
}
