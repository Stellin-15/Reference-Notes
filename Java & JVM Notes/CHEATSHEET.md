# Java & JVM — In-Depth Reference

Still the most-hired-for enterprise language on the market. Covers core
Java, the JVM's actual mechanics, and the Spring ecosystem that dominates
enterprise backend hiring.


## 1. JVM INTERNALS — WHAT'S ACTUALLY HAPPENING UNDER "java -jar app.jar"

**Bytecode & the JIT compiler**: `javac` compiles Java source to platform-
independent BYTECODE (.class files), not machine code — the JVM's
Just-In-Time compiler then compiles HOT bytecode paths (methods called
frequently) to native machine code AT RUNTIME, which is why a long-running
JVM application often gets FASTER the longer it runs (as the JIT
progressively optimizes hot paths) — a genuinely different performance
profile than an ahead-of-time-compiled language, and the reason JVM
"warm-up" is a real production concern for latency-sensitive services (a freshly-started JVM is running less-optimized interpreted/tier-1 code initially).

**Garbage Collection, precisely** — the JVM manages memory automatically
via GC, and the CHOICE of collector is a real production tuning decision:
- **G1GC** (default since Java 9) — balances throughput and pause time,
  good general-purpose default for most applications.
- **ZGC / Shenandoah** — designed for extremely low pause times (sub-
  millisecond, even on huge heaps) at some throughput cost — chosen for
  latency-critical services where even G1's occasional longer pauses are unacceptable.
- **Parallel GC** — maximizes throughput, accepts longer pauses — chosen
  for batch/offline workloads where pause time genuinely doesn't matter.

```bash
# Common JVM tuning flags
java -Xms2g -Xmx2g -XX:+UseG1GC -XX:MaxGCPauseMillis=200 -jar app.jar
# -Xms/-Xmx: initial/max heap size (setting them EQUAL avoids resize pauses)
# Heap dump on OOM for post-mortem analysis:
java -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/tmp/heapdump.hprof -jar app.jar
```

**Memory generations**: Young generation (Eden + Survivor spaces, where
new objects are allocated and most die quickly — "most objects are
short-lived" is the generational GC hypothesis) and Old generation
(long-lived objects promoted after surviving several young-gen
collections) — a MINOR GC (young-gen only) is fast and frequent; a MAJOR/
FULL GC (whole heap) is slow and rare, and frequent full GCs are a real
red flag usually indicating a memory leak or an undersized heap.


## 2. MODERN JAVA — WHAT CHANGED (Java 8 through 21+)

- **Lambdas & Streams (Java 8)** — functional-style collection processing
  (`list.stream().filter(...).map(...).collect(...)`) — the single
  biggest paradigm shift in Java's history, still what most interview
  "refactor this loop" questions target.
- **Records (Java 14+)** — concise, immutable data classes
  (`record Point(int x, int y) {}`) auto-generating constructor,
  getters, equals/hashCode/toString — eliminates enormous boilerplate
  that plagued pre-records Java data classes.
- **Sealed classes / Pattern matching for switch (Java 17+/21)** — a real
  shift toward more expressive, exhaustively-checked type hierarchies —
  worth knowing Java has genuinely modernized well past its "verbose
  enterprise language" 2010s reputation.
- **Virtual Threads (Project Loom, Java 21)** — lightweight, JVM-managed
  threads (millions possible, unlike OS threads) specifically for
  I/O-bound concurrency — a genuinely significant, recent change directly
  comparable to Go's goroutines (see Go deep dive) — worth knowing as the
  JVM ecosystem's answer to the same scalability problem.

```java
// Virtual threads (Java 21+) — massive I/O-bound concurrency, no reactive complexity needed
try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
    for (int i = 0; i < 100_000; i++) {
        executor.submit(() -> callBlockingService());  // Cheap even at huge scale
    }
}
```


## 3. THE SPRING ECOSYSTEM — ENTERPRISE JAVA'S DOMINANT FRAMEWORK

- **Spring Boot** — convention-over-configuration, auto-configuration,
  embedded server (no separate app-server deployment needed) — the
  reason Spring became approachable versus classic, XML-configuration-
  heavy Spring of the 2000s.
- **Dependency Injection (`@Autowired`, constructor injection preferred)**
  — Spring's IoC container manages object lifecycles/wiring; constructor
  injection (over field injection) is the modern best practice
  specifically because it makes dependencies explicit and testable
  without needing Spring's context to instantiate a class in tests.
- **Spring Data JPA** — repository-pattern data access, generates queries
  from method names (`findByEmailAndStatus`) or JPQL/native SQL —
  dramatically reduces boilerplate versus hand-written JDBC.
- **Spring Security** — the standard auth/authorization framework —
  filter-chain-based, integrates directly with OAuth2/OIDC/SAML (see
  Identity & Access Management deep dive).

```java
@RestController
@RequiredArgsConstructor  // Lombok: generates constructor for final fields
public class OrderController {
    private final OrderService orderService;

    @GetMapping("/orders/{id}")
    public ResponseEntity<Order> getOrder(@PathVariable Long id) {
        return orderService.findById(id)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }
}
```


## 4. BUILD TOOLS & TESTING

- **Maven** — XML-based, convention-heavy, the long-standing enterprise
  default; **Gradle** — Groovy/Kotlin DSL, more flexible/faster
  (incremental builds, build caching) — increasingly the modern default
  for new projects, especially Android (which requires Gradle).
- **JUnit 5** — the standard testing framework; **Mockito** for mocking
  dependencies; **Testcontainers** (see Testing & QA Engineering Notes)
  heavily used in the Java ecosystem specifically for real-database
  integration tests via Docker.


## 5. NICHE BUT REAL

- **GraalVM Native Image** — compiles a JVM application AHEAD OF TIME to
  a native executable, eliminating JVM startup/warm-up time entirely
  (near-instant startup, lower memory) — a genuinely significant recent
  development making Java viable for serverless/CLI use cases where JVM
  cold-start was previously a dealbreaker (Spring Boot has first-class
  Native Image support now).
- **Project Panama / Project Valhalla** — ongoing JDK initiatives for
  better native-code interop (replacing JNI) and value types
  (reducing object-header overhead for primitive-like classes) — worth
  knowing the JVM platform itself is still under genuinely active,
  significant evolution, not a "finished" legacy platform.
- **ThreadLocal pitfalls with virtual threads** — `ThreadLocal` was
  designed around a small, fixed pool of platform threads; with millions
  of cheap virtual threads, naive `ThreadLocal` usage can balloon memory
  — `ScopedValue` (Java 21+) is the newer, virtual-thread-friendly
  alternative specifically designed to avoid this.
- **Class loading & the classpath** — a genuinely deep, occasionally
  production-relevant topic (custom class loaders, `NoClassDefFoundError`
  vs `ClassNotFoundException` distinctions, "JAR hell" from conflicting
  transitive dependency versions) — still bites real production systems, especially in large monorepo Java codebases with many shared internal libraries.
