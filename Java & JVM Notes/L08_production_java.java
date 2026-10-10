// ============================================================
// L08: Production Java — HTTP Server & Client, JDBC, Security
//      APIs, Logging, Builds, Testing, Spring Boot 4, Containers
// ============================================================
// WHAT: The JDK's production-facing APIs and the ecosystem
//       around them: java.net.http.HttpClient (HTTP/2; HTTP/3 in
//       JDK 26, JEP 517), the built-in jdk.httpserver, JDBC and
//       connection pooling, java.security / javax.crypto (KDF API
//       final JDK 25, ML-KEM/ML-DSA post-quantum JDK 24, hybrid
//       PQ TLS JDK 27), System.Logger + SLF4J, Maven & Gradle,
//       JUnit 6 + Mockito + Testcontainers, Spring Boot 4 (Nov
//       2025), container/JVM settings, and a capstone service.
// WHY:  L01-L07 teach the language and the VM; this lesson is
//       the checklist for shipping a JVM service that is fast to
//       start, safe, observable, and testable — and how the
//       moving parts map to what Spring Boot does for you.
// LEVEL: Architect
// RUN:   java L08_production_java.java   (JDK 25; uses no external libraries)
// SOURCE: JDK 25 Javadoc (java.net.http, jdk.httpserver, java.sql,
//         javax.crypto.KDF), JEPs 496, 497, 510, 517, 527;
//         docs.spring.io (Boot 4.0/4.1), junit.org (JUnit 6),
//         maven.apache.org, docs.gradle.org
// ============================================================
/*
CONCEPT OVERVIEW:
    A production service = request handling (HTTP server, thread
    model), outbound calls (HTTP client with timeouts/retries),
    persistence (JDBC + pool, transactions), security (TLS,
    crypto, secrets), observability (logs, metrics, traces, JFR),
    build & test pipeline, and runtime packaging (container image,
    JVM flags). Frameworks (Spring Boot, Quarkus, Micronaut,
    Helidon) wire these together; knowing the underlying JDK APIs
    is what lets you debug them.

PRODUCTION USE CASE:
    An orders microservice built with ZERO dependencies: JDK
    HttpServer on virtual threads, JSON-ish encoding, idempotency
    keys, HMAC-signed webhooks with HKDF-derived keys, structured
    logging, and an HttpClient-based smoke test.

COMMON MISTAKES:
    1. HttpClient without timeouts (connect AND per-request) —
       one slow dependency exhausts every thread.
    2. Creating a new HttpClient / DataSource per request. They're
       heavyweight and thread-safe: create once, share.
    3. JDBC string concatenation → SQL injection. Always
       PreparedStatement with parameters.
    4. Forgetting autoCommit semantics and transaction isolation;
       long transactions holding row locks.
    5. Comparing HMACs with equals() — timing attack. Use
       MessageDigest.isEqual.
    6. Logging secrets/PII; string-concatenating log messages
       that are disabled (use parameterised logging).
    7. Fat images: full JDK + build tools in the runtime image.
       Use multi-stage builds, a JRE/jlink runtime, non-root user.
*/

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import javax.crypto.KDF;
import javax.crypto.Mac;
import javax.crypto.SecretKey;
import javax.crypto.spec.HKDFParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.KeyPairGenerator;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicLong;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class L08_production_java {

    // ========================================================
    // SECTION 1: LOGGING
    // ========================================================
    // JDK: System.Logger (9) — a facade that routes to java.util.logging
    // by default or to any backend via LoggerFinder. Ecosystem: SLF4J 2
    // API + Logback or Log4j2 backend; JSON encoders (logstash-logback-
    // encoder, Log4j2 JsonTemplateLayout) for log aggregation.
    // Rules: parameterised messages, MDC/ScopedValue for request IDs,
    // levels mean something (ERROR = someone must act), never log secrets.
    static final System.Logger SYS_LOG = System.getLogger("orders");
    static void log(String level, String event, Map<String, Object> fields) {
        // Minimal structured (logfmt) logger for the capstone.
        var sb = new StringBuilder("ts=").append(Instant.now().toString(), 0, 19).append(" level=").append(level).append(" event=").append(event);
        fields.forEach((k, v) -> sb.append(' ').append(k).append('=').append(v));
        IO.println("   " + sb);
    }

    // ========================================================
    // SECTION 2: JDBC (shown, not run — needs a database)
    // ========================================================
    //   DataSource ds = new HikariDataSource(cfg);        // pool: create ONCE
    //   cfg.setJdbcUrl("jdbc:postgresql://db:5432/orders");
    //   cfg.setMaximumPoolSize(20);                       // ≈ DB cores × 2-4, NOT thread count
    //   try (Connection c = ds.getConnection()) {
    //       c.setAutoCommit(false);                       // explicit transaction
    //       try (PreparedStatement ps = c.prepareStatement(
    //               "INSERT INTO orders(id, customer_id, total_cents) VALUES (?, ?, ?)")) {
    //           ps.setString(1, id); ps.setString(2, customer); ps.setLong(3, cents);
    //           ps.executeUpdate();
    //       }
    //       try (PreparedStatement ps = c.prepareStatement("SELECT id, total_cents FROM orders WHERE customer_id = ?")) {
    //           ps.setString(1, customer);
    //           try (ResultSet rs = ps.executeQuery()) { while (rs.next()) { rs.getString("id"); rs.getLong(2); } }
    //       }
    //       c.commit();
    //   } // on exception: c.rollback() in catch; connection returns to pool on close
    // Batch inserts: ps.addBatch() + executeBatch(); fetchSize for streaming reads.
    // Isolation: READ_COMMITTED (Postgres default) vs REPEATABLE_READ vs SERIALIZABLE.
    // Virtual threads + JDBC: the POOL size is the real concurrency limit.
    // Higher level: JdbcClient / JdbcTemplate (Spring), jOOQ (typesafe SQL),
    // JPA/Hibernate (ORM — watch N+1 queries, use fetch joins / entity graphs).
    // Migrations: Flyway or Liquibase, run at deploy time, versioned SQL.

    // ========================================================
    // SECTION 3: SECURITY & CRYPTOGRAPHY APIs
    // ========================================================
    static void crypto() throws Exception {
        // HKDF via the KDF API (final in JDK 25, JEP 510): derive purpose-specific
        // keys from one master secret instead of reusing it everywhere.
        byte[] master = "master-secret-from-a-vault-not-source-code".getBytes(StandardCharsets.UTF_8);
        KDF hkdf = KDF.getInstance("HKDF-SHA256");
        SecretKey webhookKey = hkdf.deriveKey("HmacSHA256", HKDFParameterSpec.ofExtract()
                .addIKM(master).addSalt("orders-v1".getBytes(StandardCharsets.UTF_8))
                .thenExpand("webhook-signing".getBytes(StandardCharsets.UTF_8), 32));
        WEBHOOK_KEY = webhookKey;
        IO.println("   HKDF-derived HMAC key: " + webhookKey.getAlgorithm() + " " + webhookKey.getEncoded().length * 8 + " bits");

        // Post-quantum: ML-KEM (FIPS 203, JEP 496) and ML-DSA (FIPS 204, JEP 497), JDK 24.
        var kem = KeyPairGenerator.getInstance("ML-KEM-768").generateKeyPair();
        var dsa = KeyPairGenerator.getInstance("ML-DSA-65").generateKeyPair();
        IO.println("   ML-KEM-768 public key=" + kem.getPublic().getEncoded().length + "B, ML-DSA-65 public key=" + dsa.getPublic().getEncoded().length + "B");
        // JDK 27 (JEP 527): hybrid X25519MLKEM768 key exchange in TLS 1.3 by default.
        // Other essentials: SecureRandom (never java.util.Random for tokens),
        // AES/GCM/NoPadding with a unique 12-byte IV per message, PBKDF2/Argon2
        // (via libraries) for passwords, KeyStore (PKCS12) for keys/certs,
        // TLS config via SSLContext/SSLParameters. The SecurityManager is
        // permanently disabled since JDK 24 (JEP 486).
    }
    static SecretKey WEBHOOK_KEY;

    static String hmac(String payload) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(WEBHOOK_KEY);
        return HexFormat.of().formatHex(mac.doFinal(payload.getBytes(StandardCharsets.UTF_8)));   // HexFormat (17)
    }
    static boolean verify(String payload, String signatureHex) throws Exception {
        // Constant-time comparison: MessageDigest.isEqual, never String.equals.
        return MessageDigest.isEqual(hmac(payload).getBytes(StandardCharsets.US_ASCII), signatureHex.getBytes(StandardCharsets.US_ASCII));
    }

    // ========================================================
    // SECTION 4: BUILDS — MAVEN & GRADLE (reference)
    // ========================================================
    // Maven: convention over configuration, pom.xml, lifecycle
    //   validate → compile → test → package → verify → install → deploy
    //   ./mvnw -B verify          (wrapper pins the Maven version)
    //   <maven.compiler.release>25</maven.compiler.release>
    //   dependencyManagement / BOMs (spring-boot-dependencies, junit-bom)
    //   mvn dependency:tree, versions:display-dependency-updates
    // Gradle: build.gradle.kts, task graph, incremental + build cache,
    //   java { toolchain { languageVersion = JavaLanguageVersion.of(25) } }
    //   version catalogs (gradle/libs.versions.toml), configuration cache
    //   ./gradlew build --scan
    // Both: reproducible builds, dependency locking, SBOM generation
    // (CycloneDX plugin), OWASP dependency-check / Dependabot / Renovate.

    // ========================================================
    // SECTION 5: TESTING (reference)
    // ========================================================
    // JUnit 6 (Sept 2025, Java 17 baseline; Jupiter API unchanged from 5):
    //   @Test, @ParameterizedTest @CsvSource/@MethodSource, @Nested,
    //   @BeforeEach/@AfterEach, assertThrows, assertAll, @Timeout,
    //   @TempDir, extensions (@ExtendWith), parallel execution.
    // AssertJ for fluent assertions: assertThat(list).hasSize(2).contains("a").
    // Mockito: mock(), when(...).thenReturn(...), verify(...), ArgumentCaptor;
    //   mock only what you don't own via adapters you DO own.
    // Testcontainers: real Postgres/Kafka/Redis in Docker per test run;
    //   Spring Boot @ServiceConnection wires them automatically.
    // ArchUnit (architecture rules as tests), JMH (microbenchmarks),
    // PIT (mutation testing), WireMock (HTTP stubs), Awaitility (async).

    // ========================================================
    // SECTION 6: SPRING BOOT 4 IN ONE SCREEN (reference)
    // ========================================================
    // Spring Boot 4.0 (Nov 2025) on Spring Framework 7 + Jakarta EE 11;
    // Java 17 minimum, 21/25 recommended; Jackson 3; modularised auto-
    // configuration; JSpecify null-safety; API versioning; built-in
    // @Retryable/@ConcurrencyLimit resilience; Undertow and JUnit 4 dropped.
    // 4.1 (June 2026): gRPC support, security and observability updates.
    //   @SpringBootApplication
    //   class OrdersApp { static void main(String[] a) { SpringApplication.run(OrdersApp.class, a); } }
    //
    //   @RestController @RequestMapping(path = "/orders", version = "1")
    //   class OrderController {
    //     private final OrderService svc;                // constructor injection
    //     OrderController(OrderService svc) { this.svc = svc; }
    //     @PostMapping ResponseEntity<Order> create(@Valid @RequestBody CreateOrder req,
    //         @RequestHeader("Idempotency-Key") String key) { ... }
    //     @GetMapping("/{id}") Order get(@PathVariable String id) { ... }
    //   }
    //   @Service @Transactional class OrderService { ... }
    //   interface OrderRepo extends JpaRepository<OrderEntity, String> {}
    // application.yaml: spring.threads.virtual.enabled: true,
    //   management.endpoints.web.exposure.include: health,prometheus,
    //   spring.datasource.hikari.maximum-pool-size: 20
    // Observability: Micrometer metrics + tracing (OpenTelemetry bridge),
    //   Actuator /actuator/health/{liveness,readiness} for Kubernetes probes.
    // Native: ./mvnw -Pnative native:compile (GraalVM) or AOT cache (L07).
    // Alternatives: Quarkus (build-time DI, fast native), Micronaut
    // (compile-time DI), Helidon SE (virtual-thread-native), Javalin, Vert.x.

    // ========================================================
    // SECTION 7: CONTAINERS & JVM FLAGS (reference)
    // ========================================================
    //   FROM eclipse-temurin:25-jdk AS build
    //   RUN ./mvnw -B package -DskipTests && jdeps ... && jlink ... --output /rt
    //   FROM gcr.io/distroless/base-debian12 (or ubuntu:noble with a JRE)
    //   COPY --from=build /rt /opt/java ; COPY app.jar /app/app.jar
    //   USER 65532
    //   ENTRYPOINT ["/opt/java/bin/java",
    //     "-XX:MaxRAMPercentage=75", "-XX:+ExitOnOutOfMemoryError",
    //     "-XX:+HeapDumpOnOutOfMemoryError", "-XX:HeapDumpPath=/dumps",
    //     "-XX:AOTCache=/app/app.aot", "-Xlog:gc*:stdout:time,level,tags",
    //     "-XX:StartFlightRecording=disk=true,maxage=6h,dumponexit=true",
    //     "-jar", "/app/app.jar"]
    // Kubernetes: memory request = limit (avoid overcommit kills), CPU
    // limits affect availableProcessors() → GC/JIT thread counts; set
    // -XX:ActiveProcessorCount if you remove CPU limits. Graceful shutdown:
    // handle SIGTERM (Runtime.addShutdownHook / Spring server.shutdown=graceful).

    // ========================================================
    // SECTION 8: CAPSTONE — ORDERS SERVICE ON THE JDK ALONE
    // ========================================================
    record Order(String id, String customer, long cents, Instant createdAt) {
        String json() {
            return "{\"id\":\"%s\",\"customer\":\"%s\",\"cents\":%d,\"createdAt\":\"%s\"}".formatted(id, customer, cents, createdAt);
        }
    }
    static final Map<String, Order> ORDERS = new ConcurrentHashMap<>();
    static final Map<String, String> IDEMPOTENCY = new ConcurrentHashMap<>();    // key → order id
    static final AtomicLong SEQ = new AtomicLong(1000);
    static final Pattern FIELD = Pattern.compile("\"(\\w+)\"\\s*:\\s*(\"([^\"]*)\"|(-?\\d+))");

    // Tiny JSON field extractor — a real service uses Jackson/JSON-B.
    static Map<String, String> parseFlatJson(String body) {
        Map<String, String> out = new HashMap<>();
        Matcher m = FIELD.matcher(body);
        while (m.find()) out.put(m.group(1), m.group(3) != null ? m.group(3) : m.group(4));
        return out;
    }

    static void send(HttpExchange ex, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "application/json");
        ex.sendResponseHeaders(status, bytes.length == 0 ? -1 : bytes.length);   // -1 = no body (204/304)
        try (var os = ex.getResponseBody()) { os.write(bytes); }
    }

    static void handleOrders(HttpExchange ex) throws IOException {
        long start = System.nanoTime();
        String method = ex.getRequestMethod(), path = ex.getRequestURI().getPath();
        int status = 500;
        try {
            if (method.equals("POST") && path.equals("/orders")) {
                String key = ex.getRequestHeaders().getFirst("Idempotency-Key");
                if (key == null) { send(ex, status = 400, "{\"error\":\"Idempotency-Key header required\"}"); return; }
                String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                Map<String, String> f = parseFlatJson(body);
                if (f.get("customer") == null || f.get("cents") == null || Long.parseLong(f.get("cents")) <= 0) {
                    send(ex, status = 422, "{\"error\":\"customer and positive cents required\"}"); return;
                }
                // computeIfAbsent makes "check key, create order" atomic per key.
                String id = IDEMPOTENCY.computeIfAbsent(key, k -> {
                    var o = new Order("ord_" + SEQ.incrementAndGet(), f.get("customer"), Long.parseLong(f.get("cents")), Instant.now());
                    ORDERS.put(o.id(), o);
                    return o.id();
                });
                send(ex, status = 201, ORDERS.get(id).json());
            } else if (method.equals("GET") && path.startsWith("/orders/")) {
                Order o = ORDERS.get(path.substring("/orders/".length()));
                if (o == null) send(ex, status = 404, "{\"error\":\"not found\"}"); else send(ex, status = 200, o.json());
            } else if (method.equals("POST") && path.equals("/webhooks/payment")) {
                String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                String sig = Objects.requireNonNullElse(ex.getRequestHeaders().getFirst("X-Signature"), "");
                boolean ok = verify(body, sig);
                send(ex, status = ok ? 204 : 401, ok ? "" : "{\"error\":\"bad signature\"}");
            } else {
                send(ex, status = 405, "{\"error\":\"method not allowed\"}");
            }
        } catch (Exception e) {
            SYS_LOG.log(System.Logger.Level.ERROR, "unhandled error", e);
            send(ex, status = 500, "{\"error\":\"internal\"}");
        } finally {                                         // logs every exit path, incl. early returns
            var fields = new LinkedHashMap<String, Object>();   // insertion-ordered for readable logs
            fields.put("method", method); fields.put("path", path); fields.put("status", status);
            fields.put("duration_ms", (System.nanoTime() - start) / 1_000_000);
            fields.put("virtual", Thread.currentThread().isVirtual());
            log(status >= 500 ? "ERROR" : status >= 400 ? "WARN" : "INFO", "http_request", fields);
        }
    }

    public static void main(String[] args) throws Exception {
        IO.println("== crypto");
        crypto();

        IO.println("== service");
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);  // port 0 → ephemeral
        server.createContext("/", ex -> { try (ex) { handleOrders(ex); } });
        server.setExecutor(Executors.newVirtualThreadPerTaskExecutor());                  // thread per request, virtual
        server.start();
        String base = "http://127.0.0.1:" + server.getAddress().getPort();

        // One shared client, explicit timeouts; HTTP/2 preferred, falls back to 1.1.
        HttpClient client = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(2))
                .version(HttpClient.Version.HTTP_2)                 // HTTP_3 available since JDK 26 (JEP 517)
                .followRedirects(HttpClient.Redirect.NORMAL)
                .build();
        try {
            HttpRequest.Builder post = HttpRequest.newBuilder(URI.create(base + "/orders")).timeout(Duration.ofSeconds(3))
                    .header("Content-Type", "application/json").header("Idempotency-Key", "key-123");
            String body = "{\"customer\":\"cus_42\",\"cents\":12999}";
            var r1 = client.send(post.POST(HttpRequest.BodyPublishers.ofString(body)).build(), HttpResponse.BodyHandlers.ofString());
            var r2 = client.send(post.POST(HttpRequest.BodyPublishers.ofString(body)).build(), HttpResponse.BodyHandlers.ofString()); // retry
            IO.println("   POST x2 with same key → " + r1.statusCode() + " " + r1.body() + " | same order? " + r1.body().equals(r2.body()));

            String id = parseFlatJson(r1.body()).get("id");
            var get = client.sendAsync(HttpRequest.newBuilder(URI.create(base + "/orders/" + id)).build(), HttpResponse.BodyHandlers.ofString())
                    .thenApply(HttpResponse::statusCode).join();      // async API returns CompletableFuture
            var missing = client.send(HttpRequest.newBuilder(URI.create(base + "/orders/nope")).build(), HttpResponse.BodyHandlers.ofString());
            var invalid = client.send(HttpRequest.newBuilder(URI.create(base + "/orders")).header("Idempotency-Key", "k2")
                    .POST(HttpRequest.BodyPublishers.ofString("{\"customer\":\"x\",\"cents\":-5}")).build(), HttpResponse.BodyHandlers.ofString());
            IO.println("   GET existing=" + get + " GET missing=" + missing.statusCode() + " invalid POST=" + invalid.statusCode() + " " + invalid.body());

            String event = "{\"type\":\"payment.succeeded\",\"order\":\"" + id + "\"}";
            int good = client.send(HttpRequest.newBuilder(URI.create(base + "/webhooks/payment")).header("X-Signature", hmac(event))
                    .POST(HttpRequest.BodyPublishers.ofString(event)).build(), HttpResponse.BodyHandlers.discarding()).statusCode();
            int forged = client.send(HttpRequest.newBuilder(URI.create(base + "/webhooks/payment")).header("X-Signature", "00".repeat(32))
                    .POST(HttpRequest.BodyPublishers.ofString(event)).build(), HttpResponse.BodyHandlers.discarding()).statusCode();
            IO.println("   webhook signed=" + good + " forged=" + forged);
        } finally {
            server.stop(0);
            client.close();                                         // HttpClient is AutoCloseable since JDK 21
        }
    }
}
