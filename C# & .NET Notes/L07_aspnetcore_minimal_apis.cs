// ============================================================
// L07: ASP.NET Core 10 — Hosting, DI, Configuration, Logging,
//      Middleware, Minimal APIs, Validation, Errors, Security,
//      Rate Limiting, Caching, Health, Background Services
// ============================================================
// WHAT: The ASP.NET Core fundamentals docs end to end: the
//       generic host & WebApplication builder, dependency
//       injection (lifetimes, keyed services, scope validation),
//       configuration providers and the Options pattern, logging
//       (ILogger, scopes, source-generated LoggerMessage), the
//       middleware pipeline and ordering, routing, minimal APIs
//       (route groups, TypedResults, parameter binding, endpoint
//       filters), .NET 10 built-in validation, ProblemDetails &
//       IExceptionHandler, authentication/authorization overview,
//       rate limiting, output caching, health checks, OpenAPI,
//       IHttpClientFactory + resilience, BackgroundService,
//       OpenTelemetry, and the AOT-friendly slim builder.
// WHY:  This is where most C# developers spend their working day.
//       Knowing the pipeline order, DI lifetimes and options
//       binding is the difference between "it works locally" and
//       a service that is secure, observable and scalable.
// LEVEL: Intermediate → Architect
// RUN:   dotnet run L07_aspnetcore_minimal_apis.cs
//        (starts the API on a random port, exercises it with
//        HttpClient, prints results, shuts down)
// SOURCE: learn.microsoft.com/aspnet/core/fundamentals/* (host, DI,
//         configuration, options, logging, middleware, routing,
//         minimal-apis, error-handling, rate-limit, health-checks),
//         /performance/caching/output, /fundamentals/openapi,
//         /fundamentals/native-aot, What's new in ASP.NET Core 10
// ============================================================
/*
CONCEPT OVERVIEW:
    WebApplication.CreateBuilder(args) sets up the HOST: config
    (appsettings.json → appsettings.{Env}.json → user secrets →
    env vars → command line; later wins), logging, DI container,
    Kestrel. builder.Build() freezes DI; app.UseX(...) / app.MapX(...) define the
    request PIPELINE — middleware run in registration order on the
    way in and reverse order on the way out.
    DI LIFETIMES: Singleton (one per app), Scoped (one per
    request), Transient (new every resolve). A singleton must never
    capture a scoped service (captive dependency) — ValidateScopes
    catches this in Development.

PRODUCTION USE CASE:
    An Orders API: CRUD with validation, idempotent POST,
    ProblemDetails errors, per-client rate limiting, cached
    catalog reads, health/readiness probes, a background
    outbox dispatcher, and structured logs with correlation.

COMMON MISTAKES:
    1. Wrong middleware order: UseAuthentication after
       MapControllers, CORS after auth, exception handler not first.
    2. Injecting a scoped DbContext into a singleton (captive
       dependency) → cross-request data leaks, threading bugs.
    3. `new HttpClient()` per request → socket exhaustion; use
       IHttpClientFactory / typed clients.
    4. Reading config with IConfiguration["A:B"] strings everywhere
       instead of validated, typed IOptions<T>.
    5. Returning exception messages/stack traces to clients.
    6. Blocking calls (.Result) in endpoints → thread-pool starvation.
*/

#:sdk Microsoft.NET.Sdk.Web
#:property Nullable=enable
#:property InvariantGlobalization=true
#:property PublishAot=false

using System.Collections.Concurrent;
using System.ComponentModel.DataAnnotations;
using System.Diagnostics;
using System.Net.Http.Json;
using System.Threading.RateLimiting;
using Microsoft.AspNetCore.Diagnostics;
using Microsoft.AspNetCore.Http.HttpResults;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Options;

// ============================================================
// SECTION 1: BUILDER — CONFIGURATION, OPTIONS, LOGGING, DI
// ============================================================
var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls("http://127.0.0.1:0");                     // port 0 → OS picks a free port

// In-memory config here; normally appsettings.json + env vars (Orders__MaxItemsPerOrder=50).
builder.Configuration.AddInMemoryCollection(new Dictionary<string, string?>
{
    ["Orders:MaxItemsPerOrder"] = "20",
    ["Orders:Currency"] = "USD",
    ["Logging:LogLevel:Default"] = "Warning",
    ["Logging:LogLevel:Orders"] = "Information",
    ["Logging:LogLevel:OutboxDispatcher"] = "Information",
});

// OPTIONS PATTERN: typed, validated, fail-fast at startup.
builder.Services.AddOptions<OrdersOptions>()
    .Bind(builder.Configuration.GetSection(OrdersOptions.Section))
    .ValidateDataAnnotations()
    .ValidateOnStart();
// IOptions<T> (singleton snapshot) | IOptionsSnapshot<T> (per request, reloads) |
// IOptionsMonitor<T> (singleton + change notifications).

builder.Logging.ClearProviders().AddSimpleConsole(o => { o.SingleLine = true; o.TimestampFormat = "HH:mm:ss "; o.IncludeScopes = false; });

// DEPENDENCY INJECTION
builder.Services.AddSingleton(TimeProvider.System);
builder.Services.AddSingleton<IOrderStore, InMemoryOrderStore>();      // app-lifetime state
builder.Services.AddScoped<OrderService>();                            // per request
builder.Services.AddTransient<IIdGenerator, UlidLikeIdGenerator>();
builder.Services.AddKeyedSingleton<IPricing, StandardPricing>("standard");   // keyed services (.NET 8)
builder.Services.AddKeyedSingleton<IPricing, VipPricing>("vip");
builder.Services.AddHostedService<OutboxDispatcher>();                 // background worker

// .NET 10 built-in minimal-API validation (DataAnnotations on parameters/records).
builder.Services.AddValidation();

// Errors → RFC 9457 ProblemDetails everywhere.
builder.Services.AddProblemDetails(o => o.CustomizeProblemDetails = ctx =>
    ctx.ProblemDetails.Extensions["traceId"] = Activity.Current?.Id ?? ctx.HttpContext.TraceIdentifier);
builder.Services.AddExceptionHandler<DomainExceptionHandler>();

// Rate limiting: fixed window per client key.
builder.Services.AddRateLimiter(o =>
{
    o.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
    o.AddPolicy("per-client", ctx => RateLimitPartition.GetFixedWindowLimiter(
        partitionKey: ctx.Request.Headers["X-Client-Id"].FirstOrDefault() ?? "anonymous",
        factory: _ => new FixedWindowRateLimiterOptions { PermitLimit = 10, Window = TimeSpan.FromSeconds(10), QueueLimit = 0 }));
});

builder.Services.AddOutputCache(o => o.AddPolicy("catalog", p => p.Expire(TimeSpan.FromSeconds(30)).Tag("catalog")));
builder.Services.AddHealthChecks()
    .AddCheck("self", () => HealthCheckResult.Healthy())
    .AddCheck<StoreHealthCheck>("store", tags: ["ready"]);
// Typed HttpClient via IHttpClientFactory (pooled handlers, DNS refresh):
//   builder.Services.AddHttpClient<FxRatesClient>(c => c.BaseAddress = new("https://fx.example"))
//          .AddStandardResilienceHandler();      // Microsoft.Extensions.Http.Resilience: retry, CB, timeout, hedging
// OpenAPI (.NET 9+): builder.Services.AddOpenApi(); app.MapOpenApi();  → /openapi/v1.json
// AuthN/AuthZ: builder.Services.AddAuthentication().AddJwtBearer(); AddAuthorization(o => o.AddPolicy(...))
// OpenTelemetry: builder.Services.AddOpenTelemetry().WithTracing(t => t.AddAspNetCoreInstrumentation().AddOtlpExporter())
//                .WithMetrics(m => m.AddAspNetCoreInstrumentation().AddRuntimeInstrumentation());

builder.Host.UseDefaultServiceProvider(o => { o.ValidateScopes = true; o.ValidateOnBuild = true; });

var app = builder.Build();

// ============================================================
// SECTION 2: MIDDLEWARE PIPELINE (order matters)
// ============================================================
// Recommended order: ExceptionHandler → HSTS → HttpsRedirection → Static files →
// Routing → CORS → Authentication → Authorization → RateLimiter → OutputCache →
// custom → Endpoints.
app.UseExceptionHandler();                                 // first: catches everything below
app.UseStatusCodePages();                                  // bare 404/405 → ProblemDetails
app.Use(async (ctx, next) =>                               // inline middleware: correlation + timing
{
    var correlationId = ctx.Request.Headers["X-Correlation-Id"].FirstOrDefault() ?? Guid.NewGuid().ToString("N")[..8];
    ctx.Response.Headers["X-Correlation-Id"] = correlationId;
    var logger = ctx.RequestServices.GetRequiredService<ILoggerFactory>().CreateLogger("Orders");
    // BeginScope attaches CorrelationId to EVERY log written during this request
    // (visible with IncludeScopes or a JSON/OpenTelemetry exporter).
    using (logger.BeginScope(new Dictionary<string, object> { ["CorrelationId"] = correlationId }))
    {
        var sw = Stopwatch.StartNew();
        var failed = false;
        try { await next(ctx); }                            // ← call the rest of the pipeline
        catch { failed = true; throw; }                     // exceptions bubble OUT through this middleware…
        finally                                             // …so log in finally, or failed requests go unlogged
        {
            // On failure the status isn't set yet — UseExceptionHandler (outermost) sets it afterwards.
            Log.RequestCompleted(logger, correlationId, ctx.Request.Method, ctx.Request.Path,
                failed ? "threw (handler sets status)" : ctx.Response.StatusCode.ToString(), sw.ElapsedMilliseconds);
        }
    }
});
app.UseRateLimiter();
app.UseOutputCache();

// ============================================================
// SECTION 3: MINIMAL API ENDPOINTS
// ============================================================
app.MapHealthChecks("/health/live", new() { Predicate = _ => false });       // liveness: process is up
app.MapHealthChecks("/health/ready", new() { Predicate = c => c.Tags.Contains("ready") });

var orders = app.MapGroup("/orders")
    .WithTags("Orders")
    .RequireRateLimiting("per-client")
    .AddEndpointFilter(async (ctx, next) =>                 // endpoint filter: runs around handlers in the group
    {
        if (!ctx.HttpContext.Request.Headers.ContainsKey("X-Client-Id"))
            return TypedResults.Problem("X-Client-Id header required", statusCode: 400);
        return await next(ctx);
    });

// Parameter binding: route ({id}), query, header ([FromHeader]), body (JSON),
// services (DI), special types (HttpContext, CancellationToken, ClaimsPrincipal).
orders.MapPost("/", async Task<Results<Created<OrderDto>, Ok<OrderDto>, ProblemHttpResult>> (
        CreateOrderRequest req,
        [FromHeader(Name = "Idempotency-Key")] string? idempotencyKey,
        OrderService svc, CancellationToken ct) =>
    {
        if (string.IsNullOrWhiteSpace(idempotencyKey))
            return TypedResults.Problem("Idempotency-Key header required", statusCode: 400);
        var (order, created) = await svc.CreateAsync(req, idempotencyKey, ct);
        return created ? TypedResults.Created($"/orders/{order.Id}", order) : TypedResults.Ok(order);
    });

orders.MapGet("/{id}", Results<Ok<OrderDto>, NotFound> (string id, IOrderStore store) =>
    store.Get(id) is { } o ? TypedResults.Ok(o) : TypedResults.NotFound());

orders.MapGet("/", (IOrderStore store, int page = 1, int pageSize = 10) =>
    TypedResults.Ok(store.All().OrderBy(o => o.Id).Skip((page - 1) * pageSize).Take(pageSize)));

orders.MapPost("/{id}/cancel", async (string id, OrderService svc) =>
{
    await svc.CancelAsync(id);                               // may throw a domain exception → handled globally
    return TypedResults.NoContent();
});

app.MapGet("/catalog", (TimeProvider time) => new { Generated = time.GetUtcNow().ToString("HH:mm:ss.fff"), Items = new[] { "A", "B" } })
   .CacheOutput("catalog");

app.MapGet("/quote/{tier}", (string tier, decimal amount, IServiceProvider sp) =>
    sp.GetKeyedService<IPricing>(tier) is { } p ? Results.Ok(new { tier, total = p.Price(amount) }) : Results.NotFound());

// ============================================================
// SECTION 4: RUN + SELF-TEST WITH HttpClient
// ============================================================
await app.StartAsync();
var baseUrl = app.Urls.First();
using var http = new HttpClient { BaseAddress = new Uri(baseUrl) };
http.DefaultRequestHeaders.Add("X-Client-Id", "client-a");

async Task Show(string label, HttpResponseMessage r) =>
    Console.WriteLine($"   {label,-34} → {(int)r.StatusCode} {Trim(await r.Content.ReadAsStringAsync())}");
static string Trim(string s) => s.Length > 110 ? s[..110] + "…" : s;

Console.WriteLine($"== API listening on {baseUrl}");
var valid = new { customerId = "cus_42", items = new[] { new { sku = "A-1", quantity = 2, unitPrice = 19.99m } } };
var post = (object body, string key) => { var m = new HttpRequestMessage(HttpMethod.Post, "/orders") { Content = JsonContent.Create(body) }; m.Headers.Add("Idempotency-Key", key); return http.SendAsync(m); };

var r1 = await post(valid, "k-1");
var created = await r1.Content.ReadFromJsonAsync<OrderDto>();
await Show("POST /orders (new)", r1);
await Show("POST /orders (same key, retried)", await post(valid, "k-1"));
await Show("POST /orders (invalid body)", await post(new { customerId = "", items = Array.Empty<object>() }, "k-2"));
await Show("GET /orders/{id}", await http.GetAsync($"/orders/{created!.Id}"));
await Show("GET /orders/missing", await http.GetAsync("/orders/missing"));
await Show("POST /orders/{id}/cancel twice (2nd)", await http.PostAsync($"/orders/{created.Id}/cancel", null).ContinueWith(_ => http.PostAsync($"/orders/{created.Id}/cancel", null)).Unwrap());
await Show("GET /orders?page=1", await http.GetAsync("/orders?page=1"));
using (var noClient = new HttpClient { BaseAddress = new Uri(baseUrl) }) await Show("GET /orders without X-Client-Id", await noClient.GetAsync("/orders"));
var c1 = await http.GetStringAsync("/catalog"); await Task.Delay(20); var c2 = await http.GetStringAsync("/catalog");
Console.WriteLine($"   output cache: second /catalog served from cache = {c1 == c2}");
await Show("GET /quote/vip?amount=100", await http.GetAsync("/quote/vip?amount=100"));
await Show("GET /health/ready", await http.GetAsync("/health/ready"));
await Show("GET /nope (status code pages)", await http.GetAsync("/nope"));
using (var burst = new HttpClient { BaseAddress = new Uri(baseUrl) })
{
    burst.DefaultRequestHeaders.Add("X-Client-Id", "client-b");                 // separate rate-limit partition
    var codes = await Task.WhenAll(Enumerable.Range(0, 14).Select(_ => burst.GetAsync("/orders")));
    Console.WriteLine($"   burst of 14 from client-b: {codes.Count(c => (int)c.StatusCode == 200)}×200, {codes.Count(c => (int)c.StatusCode == 429)}×429 (limit 10 per 10s)");
}
await Task.Delay(1200);                                       // let the outbox worker tick
await app.StopAsync();                                        // graceful shutdown: stops hosted services

// ============================================================
// SECTION 5: TYPES — options, DTOs, services, handlers, workers
// ============================================================
public sealed class OrdersOptions
{
    public const string Section = "Orders";
    [Range(1, 100)] public int MaxItemsPerOrder { get; set; }
    [Required, RegularExpression("^[A-Z]{3}$")] public string Currency { get; set; } = "";
}

public sealed record LineItem([Required, StringLength(20)] string Sku, [Range(1, 1000)] int Quantity, [Range(0.01, 1_000_000)] decimal UnitPrice);
public sealed record CreateOrderRequest([Required, MinLength(1)] string CustomerId, [Required, MinLength(1)] List<LineItem> Items);
public sealed record OrderDto(string Id, string CustomerId, decimal Total, string Currency, string Status);

public interface IIdGenerator { string Next(); }
public sealed class UlidLikeIdGenerator(TimeProvider time) : IIdGenerator
{
    private static int _seq;
    public string Next() => $"ord_{time.GetUtcNow():yyMMddHHmmss}{Interlocked.Increment(ref _seq):D3}";
}

public interface IOrderStore
{
    OrderDto? Get(string id);
    IEnumerable<OrderDto> All();
    OrderDto GetOrAdd(string idempotencyKey, Func<OrderDto> create, out bool created);
    void Update(OrderDto o);
    ConcurrentQueue<string> Outbox { get; }
}
public sealed class InMemoryOrderStore : IOrderStore
{
    private readonly ConcurrentDictionary<string, OrderDto> _byId = new();
    private readonly ConcurrentDictionary<string, string> _byKey = new();
    public ConcurrentQueue<string> Outbox { get; } = new();
    public OrderDto? Get(string id) => _byId.GetValueOrDefault(id);
    public IEnumerable<OrderDto> All() => _byId.Values;
    public OrderDto GetOrAdd(string key, Func<OrderDto> create, out bool created)
    {
        var isNew = false;
        var id = _byKey.GetOrAdd(key, _ => { var o = create(); _byId[o.Id] = o; isNew = true; Outbox.Enqueue($"OrderCreated:{o.Id}"); return o.Id; });
        created = isNew;
        return _byId[id];
    }
    public void Update(OrderDto o) => _byId[o.Id] = o;
}

public sealed class OrderService(IOrderStore store, IIdGenerator ids, IOptionsSnapshot<OrdersOptions> options, ILogger<OrderService> log)
{
    public Task<(OrderDto Order, bool Created)> CreateAsync(CreateOrderRequest req, string key, CancellationToken ct)
    {
        var opts = options.Value;
        if (req.Items.Count > opts.MaxItemsPerOrder) throw new DomainException("too_many_items", $"max {opts.MaxItemsPerOrder} items");
        var order = store.GetOrAdd(key, () => new OrderDto(ids.Next(), req.CustomerId, req.Items.Sum(i => i.Quantity * i.UnitPrice), opts.Currency, "pending"), out var created);
        if (created) Log.OrderCreated(log, order.Id, order.Total);
        return Task.FromResult((order, created));
    }
    public Task CancelAsync(string id)
    {
        var o = store.Get(id) ?? throw new DomainException("not_found", $"order {id} not found", 404);
        if (o.Status == "cancelled") throw new DomainException("invalid_state", "order already cancelled", 409);
        store.Update(o with { Status = "cancelled" });
        return Task.CompletedTask;
    }
}

public interface IPricing { decimal Price(decimal amount); }
public sealed class StandardPricing : IPricing { public decimal Price(decimal a) => a; }
public sealed class VipPricing : IPricing { public decimal Price(decimal a) => Math.Round(a * 0.9m, 2); }

// Domain exceptions → ProblemDetails with the right status; everything else → generic 500.
public sealed class DomainException(string code, string message, int status = 422) : Exception(message)
{
    public string Code { get; } = code;
    public int Status { get; } = status;
}
public sealed class DomainExceptionHandler(IProblemDetailsService problems) : IExceptionHandler
{
    public async ValueTask<bool> TryHandleAsync(HttpContext ctx, Exception ex, CancellationToken ct)
    {
        if (ex is not DomainException d) return false;          // let the default handler produce a safe 500
        ctx.Response.StatusCode = d.Status;
        return await problems.TryWriteAsync(new()
        {
            HttpContext = ctx,
            ProblemDetails = { Status = d.Status, Title = d.Code, Detail = d.Message, Type = $"https://errors.example/{d.Code}" },
        });
    }
}

public sealed class StoreHealthCheck(IOrderStore store) : IHealthCheck
{
    public Task<HealthCheckResult> CheckHealthAsync(HealthCheckContext context, CancellationToken ct = default) =>
        Task.FromResult(store.Outbox.Count < 1000 ? HealthCheckResult.Healthy($"outbox={store.Outbox.Count}") : HealthCheckResult.Degraded("outbox backlog"));
}

// BackgroundService: long-running work tied to the host lifetime (graceful stop via stoppingToken).
public sealed class OutboxDispatcher(IOrderStore store, ILogger<OutboxDispatcher> log, TimeProvider time) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromMilliseconds(500), time);
        try
        {
            while (await timer.WaitForNextTickAsync(stoppingToken))
                while (store.Outbox.TryDequeue(out var evt)) Log.Published(log, evt);   // publish to Kafka/Service Bus in real life
        }
        catch (OperationCanceledException) { /* host is stopping — normal shutdown */ }
    }
}

// Source-generated, allocation-free logging (no boxing, no parsing of templates at runtime).
static partial class Log
{
    [LoggerMessage(Level = LogLevel.Information, Message = "[{CorrelationId}] {Method} {Path} → {Status} in {ElapsedMs}ms")]
    public static partial void RequestCompleted(ILogger logger, string correlationId, string method, string path, string status, long elapsedMs);
    [LoggerMessage(Level = LogLevel.Information, Message = "Order {OrderId} created, total {Total}")]
    public static partial void OrderCreated(ILogger logger, string orderId, decimal total);
    [LoggerMessage(Level = LogLevel.Information, Message = "Outbox published {Event}")]
    public static partial void Published(ILogger logger, string @event);
}
// NATIVE AOT for APIs: WebApplication.CreateSlimBuilder(args) + a JsonSerializerContext
// ([JsonSerializable(typeof(OrderDto))]) registered via ConfigureHttpJsonOptions, and
// `#:property PublishAot=true` → ~20 MB self-contained binary, ~20 ms startup.
// MVC controllers ([ApiController]) remain fully supported; minimal APIs are the
// default for new microservices. Blazor (server/WASM/auto render modes) and
// SignalR (real-time hubs) are the other major ASP.NET Core frameworks.
