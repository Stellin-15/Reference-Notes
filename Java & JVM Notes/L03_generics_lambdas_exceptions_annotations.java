// ============================================================
// L03: Generics, Lambdas & Functional Interfaces, Exceptions,
//      Annotations
// ============================================================
// WHAT: dev.java "Generics", "Lambda Expressions", "Exceptions",
//       "Annotations" tutorials and the java.util.function
//       package: generic classes/methods, bounded types,
//       wildcards and PECS, type erasure and its consequences,
//       lambdas, method references, the 43 standard functional
//       interfaces (the families that matter), composition;
//       the exception hierarchy, checked vs unchecked,
//       try-with-resources, suppressed exceptions, chaining,
//       custom exceptions; annotations — built-ins, meta-
//       annotations, retention, writing and reading your own.
// WHY:  Generics and lambdas are the vocabulary of every modern
//       Java API (Streams, CompletableFuture, Spring, JUnit).
//       Exception design decides whether failures are diagnosable
//       at 3 a.m. Annotations drive frameworks (Spring, JPA,
//       Jackson, JUnit) — you need to know what they actually do.
// LEVEL: Intermediate
// RUN:   java L03_generics_lambdas_exceptions_annotations.java
// SOURCE: dev.java/learn/generics, /lambdas, /exceptions,
//         /annotations; JLS 25 ch. 4.5-4.8, 9.6-9.7, 11, 15.27;
//         Effective Java 3e items 26-33, 42-44, 69-77
// ============================================================
/*
CONCEPT OVERVIEW:
    GENERICS give compile-time type safety for containers and
    algorithms; at runtime the type arguments are ERASED
    (List<String> and List<Integer> are the same class).
    LAMBDAS are concise implementations of FUNCTIONAL INTERFACES
    (interfaces with exactly one abstract method). They're
    compiled with invokedynamic, not anonymous classes.
    EXCEPTIONS: Throwable → Error (don't catch) | Exception →
    RuntimeException (unchecked) | everything else (checked —
    the compiler forces handling or declaration).
    ANNOTATIONS are metadata; they do nothing unless a compiler
    plugin, annotation processor, or reflection reads them.

PRODUCTION USE CASE:
    A typed retry/validation toolkit: a generic Result type,
    a retry helper parameterised by functional interfaces, a
    custom checked/unchecked exception strategy, and a tiny
    annotation-driven validator (the idea behind Jakarta Bean
    Validation's @NotNull / @Size).

COMMON MISTAKES:
    1. Raw types (`List list = new ArrayList()`) — silently turn
       off generic checking. Always parameterise.
    2. `List<Object>` param when you meant `List<?>` — List<String>
       is NOT a List<Object> (generics are invariant).
    3. Catching Exception/Throwable broadly and swallowing it —
       log with context and rethrow, or handle specifically.
    4. Losing the cause: `throw new MyEx(e.getMessage())` drops the
       stack trace. Pass `e` as the cause.
    5. Checked exceptions inside lambdas — standard functional
       interfaces can't throw them; wrap deliberately.
    6. Mutating captured state from lambdas (only effectively-final
       locals can be captured; mutating a shared collection from a
       parallel stream is a race).
*/

import java.io.Closeable;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import java.lang.reflect.Field;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.Callable;
import java.util.function.BiFunction;
import java.util.function.BinaryOperator;
import java.util.function.Consumer;
import java.util.function.Function;
import java.util.function.IntBinaryOperator;
import java.util.function.Predicate;
import java.util.function.Supplier;
import java.util.function.UnaryOperator;

public class L03_generics_lambdas_exceptions_annotations {

    // ========================================================
    // SECTION 1: GENERIC TYPES AND METHODS
    // ========================================================
    // Type parameter naming: E element, K key, V value, T/U/S types, R result, N number.
    static final class Box<T> {
        private T value;
        Box(T value) { this.value = value; }
        T get() { return value; }
        void set(T v) { value = v; }
        <R> Box<R> map(Function<? super T, ? extends R> f) { return new Box<>(f.apply(value)); }
    }

    // Generic METHOD: type parameter before return type; usually inferred.
    static <K, V> Map<V, K> invert(Map<K, V> m) {
        var out = new java.util.HashMap<V, K>();
        m.forEach((k, v) -> out.put(v, k));
        return out;
    }

    // BOUNDED type parameters: T must be Comparable to itself (or a supertype).
    static <T extends Comparable<? super T>> T max(Collection<? extends T> items) {
        T best = null;
        for (T t : items) if (best == null || t.compareTo(best) > 0) best = t;
        return best;
    }
    // Multiple bounds: <T extends Number & Comparable<T>> — class first, then interfaces.

    // ========================================================
    // SECTION 2: WILDCARDS AND PECS
    // ========================================================
    // Generics are INVARIANT: List<Integer> is not a List<Number>.
    // Wildcards restore flexibility:
    //   ? extends T  — PRODUCER: you read T out (can't add, except null)
    //   ? super T    — CONSUMER: you put T in (read back only Object)
    //   ?            — unknown: read as Object, can't add
    // PECS: "Producer Extends, Consumer Super" (Effective Java item 31).
    static double sum(List<? extends Number> nums) {            // accepts List<Integer>, List<Double>
        double s = 0;
        for (Number n : nums) s += n.doubleValue();
        return s;
    }
    static void fillWithInts(List<? super Integer> sink, int n) { // accepts List<Integer>, List<Number>, List<Object>
        for (int i = 0; i < n; i++) sink.add(i);
    }
    // Collections.copy uses both: copy(List<? super T> dest, List<? extends T> src)

    // ========================================================
    // SECTION 3: TYPE ERASURE AND ITS CONSEQUENCES
    // ========================================================
    // At runtime: List<String> → List, T → its bound (Object or the first bound).
    // Consequences — you can't:
    //   new T()             (no type at runtime — pass a Supplier<T> or Class<T>)
    //   new T[n] / new List<String>[n]  (generic array creation)
    //   x instanceof List<String>       (only List<?> is checkable)
    //   overload f(List<String>) and f(List<Integer>) (same erasure → clash)
    //   static T field      (statics are shared across all parameterisations)
    //   catch (T e) or generic exception classes
    // Bridge methods: the compiler generates synthetic methods so overriding
    // still works after erasure (visible in stack traces and reflection).
    static <T> T create(Supplier<T> factory) { return factory.get(); }       // the workaround for new T()
    static <T> List<T> typedList(Class<T> type, Object... raw) {            // "type token" pattern
        var out = new ArrayList<T>();
        for (Object o : raw) out.add(type.cast(o));                          // checked cast at runtime
        return out;
    }
    // Heap pollution with generic varargs: annotate safe ones with @SafeVarargs.
    @SafeVarargs
    static <T> List<T> listOf(T... items) { return List.of(items); }

    // ========================================================
    // SECTION 4: LAMBDAS AND METHOD REFERENCES
    // ========================================================
    // Syntax: (params) -> expression  |  (params) -> { statements; }
    // Target typing: a lambda has no type on its own; it takes the type of
    // the functional interface expected at that position.
    // Method references — four kinds:
    //   Static:              Integer::parseInt          s -> Integer.parseInt(s)
    //   Bound instance:      "abc"::startsWith          p -> "abc".startsWith(p)
    //   Unbound instance:    String::toUpperCase        s -> s.toUpperCase()
    //   Constructor:         ArrayList::new             () -> new ArrayList<>()
    static void lambdas() {
        Function<String, Integer> parse = Integer::parseInt;
        Predicate<String> isEmpty = String::isEmpty;
        Supplier<List<String>> newList = ArrayList::new;
        BiFunction<String, Integer, Character> charAt = String::charAt;
        IO.println("method refs: " + parse.apply("42") + " " + isEmpty.test("") + " " + newList.get() + " " + charAt.apply("java", 1));

        // Composition — the standard interfaces have combinators:
        Function<Integer, Integer> plus2 = x -> x + 2, times3 = x -> x * 3;
        IO.println("andThen=" + plus2.andThen(times3).apply(1) + " compose=" + plus2.compose(times3).apply(1)); // 9, 5
        Predicate<String> longWord = s -> s.length() > 4;
        Predicate<String> startsJ = s -> s.startsWith("J");
        IO.println("predicates: " + longWord.and(startsJ).test("Javelin") + " " + longWord.negate().or(startsJ).test("Go")
                + " " + Predicate.not(String::isBlank).test(" "));
        Comparator<String> byLenThenAlpha = Comparator.comparingInt(String::length).thenComparing(Comparator.naturalOrder());
        var langs = new ArrayList<>(List.of("Rust", "Go", "Java", "C", "Kotlin"));
        langs.sort(byLenThenAlpha.reversed());
        IO.println("comparator: " + langs);

        // Capture rule: locals must be effectively final.
        int base = 10;
        UnaryOperator<Integer> addBase = x -> x + base;
        // base++;  // would make the lambda above a compile error
        // `this` in a lambda is the enclosing instance (unlike anonymous classes).
        IO.println("capture: " + addBase.apply(5));

        // Primitive specialisations avoid boxing: IntBinaryOperator, ToIntFunction, IntStream...
        IntBinaryOperator gcd = new IntBinaryOperator() {        // anonymous class — needed for recursion via `this`
            public int applyAsInt(int a, int b) { return b == 0 ? a : this.applyAsInt(b, a % b); }
        };
        IO.println("gcd: " + gcd.applyAsInt(84, 36));
    }
    // FAMILIES in java.util.function (43 interfaces, all variations of):
    //   Supplier<T>        () -> T            BooleanSupplier, IntSupplier...
    //   Consumer<T>        T -> void          BiConsumer, IntConsumer, ObjIntConsumer...
    //   Predicate<T>       T -> boolean       BiPredicate, IntPredicate...
    //   Function<T,R>      T -> R             BiFunction, IntFunction, ToIntFunction, IntToLongFunction...
    //   UnaryOperator<T>   T -> T             IntUnaryOperator...
    //   BinaryOperator<T>  (T,T) -> T         IntBinaryOperator...
    // Write your own @FunctionalInterface only when none fits or a name
    // clarifies intent (e.g. a lambda that may throw a checked exception).

    @FunctionalInterface
    interface ThrowingSupplier<T, E extends Exception> { T get() throws E; }

    // ========================================================
    // SECTION 5: EXCEPTIONS
    // ========================================================
    //                 Throwable
    //               /           \
    //           Error            Exception
    //  (OOM, StackOverflow:      /          \
    //    don't catch)   RuntimeException   IOException, SQLException,
    //                  (unchecked: NPE,    InterruptedException ...
    //                   IAE, ISE, IOOBE)   (checked)
    // Guideline: CHECKED for recoverable conditions the caller can act on;
    // UNCHECKED for programming errors and unrecoverable states. Most modern
    // frameworks (Spring, JPA) wrap checked into unchecked.
    static class PaymentDeclinedException extends Exception {        // checked: caller must decide
        private final String code;
        PaymentDeclinedException(String code, String msg) { super(msg); this.code = code; }
        String code() { return code; }
    }
    static class GatewayUnavailableException extends RuntimeException { // unchecked: retry layer handles
        GatewayUnavailableException(String msg, Throwable cause) { super(msg, cause); } // keep the cause!
    }

    // try-with-resources: any AutoCloseable; closed in REVERSE order,
    // even on exception; close() failures become SUPPRESSED exceptions.
    static final class Resource implements Closeable {
        private final String name;
        private final boolean failOnClose;
        Resource(String name, boolean failOnClose) { this.name = name; this.failOnClose = failOnClose; IO.println("   open " + name); }
        @Override public void close() {
            IO.println("   close " + name);
            if (failOnClose) throw new IllegalStateException("close failed: " + name);
        }
    }

    static void exceptions() {
        try (var a = new Resource("db", false); var b = new Resource("file", true)) {
            throw new IllegalArgumentException("body failed");
        } catch (IllegalArgumentException e) {
            IO.println("   primary: " + e.getMessage() + ", suppressed: " + e.getSuppressed()[0].getMessage());
        }

        // Multi-catch (types must be unrelated) and finally:
        try {
            Object o = List.of(1).get(3);
            IO.println(o);
        } catch (IndexOutOfBoundsException | ClassCastException e) {
            IO.println("   multi-catch: " + e.getClass().getSimpleName());
        } finally {
            IO.println("   finally always runs (unless the JVM exits)");
        }
        // NEVER return from finally — it silently discards any exception in flight.

        // Chaining preserves the root cause:
        try {
            try {
                throw new java.net.SocketTimeoutException("read timed out after 2000ms");
            } catch (java.io.IOException io) {
                throw new GatewayUnavailableException("stripe call failed", io);
            }
        } catch (GatewayUnavailableException e) {
            IO.println("   wrapped: " + e.getMessage() + " <- cause: " + e.getCause().getMessage());
        }
        // Helpful NullPointerExceptions (JDK 14+, default on): the message names
        // exactly which reference was null — e.g. "because "user.address" is null".
    }

    // ========================================================
    // SECTION 6: ANNOTATIONS
    // ========================================================
    // Built-ins: @Override, @Deprecated(since, forRemoval), @SuppressWarnings,
    //            @FunctionalInterface, @SafeVarargs.
    // Meta-annotations: @Retention(SOURCE|CLASS|RUNTIME), @Target(...),
    //            @Documented, @Inherited, @Repeatable.
    //   SOURCE  — discarded by javac (Lombok, @Override)
    //   CLASS   — in .class file, not visible via reflection (default)
    //   RUNTIME — readable via reflection (Spring, JPA, JUnit, Jackson)
    // Element types: TYPE, FIELD, METHOD, PARAMETER, CONSTRUCTOR,
    //   LOCAL_VARIABLE, ANNOTATION_TYPE, PACKAGE, TYPE_PARAMETER,
    //   TYPE_USE (Java 8: @NonNull String), MODULE, RECORD_COMPONENT (16).
    // Annotation PROCESSORS (javax.annotation.processing) run inside javac
    // and generate code at compile time — MapStruct, Dagger, Micronaut,
    // Immutables, AutoValue — no reflection cost at runtime.
    @Retention(RetentionPolicy.RUNTIME)
    @Target({ElementType.FIELD, ElementType.RECORD_COMPONENT})
    @interface NotBlank {}

    @Retention(RetentionPolicy.RUNTIME)
    @Target({ElementType.FIELD, ElementType.RECORD_COMPONENT})
    @interface Range { long min() default 0; long max() default Long.MAX_VALUE; String message() default "out of range"; }

    record ChargeRequest(@NotBlank String customerId, @Range(min = 50, max = 1_000_000, message = "amount must be 50..1000000 cents") long amountCents,
                         @NotBlank String currency) {}

    // A reflection-based validator — the core of Bean Validation, in 20 lines.
    static List<String> validate(Object target) {
        var errors = new ArrayList<String>();
        for (Field f : target.getClass().getDeclaredFields()) {
            f.setAccessible(true);
            try {
                Object v = f.get(target);
                if (f.isAnnotationPresent(NotBlank.class) && (v == null || v.toString().isBlank()))
                    errors.add(f.getName() + " must not be blank");
                Range r = f.getAnnotation(Range.class);
                if (r != null && v instanceof Number n && (n.longValue() < r.min() || n.longValue() > r.max()))
                    errors.add(f.getName() + ": " + r.message());
            } catch (IllegalAccessException e) {
                throw new IllegalStateException(e);
            }
        }
        return errors;
    }
    // Annotations on record components propagate to the generated field,
    // accessor, and constructor parameter according to their @Target.

    // ========================================================
    // SECTION 7: END-TO-END — GENERIC RETRY WITH TYPED RESULTS
    // ========================================================
    sealed interface Result<T> {
        record Ok<T>(T value) implements Result<T> {}
        record Err<T>(Exception error, int attempts) implements Result<T> {}
        default <R> Result<R> map(Function<? super T, ? extends R> f) {
            return switch (this) {
                case Ok<T> ok -> new Ok<>(f.apply(ok.value()));
                case Err<T> err -> new Err<>(err.error(), err.attempts());
            };
        }
    }

    static <T> Result<T> retry(Callable<T> op, int maxAttempts, Duration backoff,
                               Predicate<? super Exception> retryable, Consumer<String> log) {
        Exception last = null;
        for (int attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                return new Result.Ok<>(op.call());
            } catch (Exception e) {
                last = e;
                if (!retryable.test(e) || attempt == maxAttempts) return new Result.Err<>(e, attempt);
                long sleep = backoff.toMillis() * (1L << (attempt - 1));        // exponential
                log.accept("attempt %d failed (%s), retrying in %dms".formatted(attempt, e.getMessage(), sleep));
                try { Thread.sleep(sleep); } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();                         // restore the flag!
                    return new Result.Err<>(ie, attempt);
                }
            }
        }
        return new Result.Err<>(last, maxAttempts);
    }

    public static void main(String[] args) throws Exception {
        IO.println("== generics");
        Box<String> box = new Box<>("generics");
        IO.println("   " + box.map(String::length).get() + " " + invert(Map.of("a", 1)) + " " + max(List.of(3, 9, 4))
                + " " + sum(List.of(1, 2.5, 3L)));
        List<Number> sink = new ArrayList<>();
        fillWithInts(sink, 3);
        IO.println("   PECS sink=" + sink + " create=" + create(StringBuilder::new).append("ok")
                + " typed=" + typedList(String.class, "a", "b") + " listOf=" + listOf(1, 2));
        try { typedList(Integer.class, "x"); } catch (ClassCastException e) { IO.println("   type token caught: " + e.getMessage()); }

        IO.println("== lambdas");
        lambdas();

        IO.println("== exceptions");
        exceptions();

        IO.println("== annotations");
        IO.println("   valid:   " + validate(new ChargeRequest("cus_1", 5000, "USD")));
        IO.println("   invalid: " + validate(new ChargeRequest(" ", 10, "")));

        IO.println("== retry");
        int[] calls = {0};
        Result<String> r = retry(() -> {
            if (++calls[0] < 3) throw new GatewayUnavailableException("503 from gateway", null);
            return "ch_123";
        }, 5, Duration.ofMillis(10), e -> e instanceof GatewayUnavailableException, s -> IO.println("   " + s));
        IO.println("   " + r.map(id -> "charged " + id));

        ThrowingSupplier<String, PaymentDeclinedException> charge = () -> { throw new PaymentDeclinedException("card_declined", "insufficient funds"); };
        Result<String> declined = retry(charge::get, 5, Duration.ofMillis(10), e -> e instanceof GatewayUnavailableException, IO::println);
        if (declined instanceof Result.Err<String>(PaymentDeclinedException p, int attempts))  // record pattern (L05)
            IO.println("   not retried: code=" + p.code() + " attempts=" + attempts);

        BinaryOperator<Integer> pick = BinaryOperator.minBy(Comparator.naturalOrder());
        IO.println("   minBy=" + pick.apply(4, 2) + " optional=" + Optional.of("x").map(String::toUpperCase).orElse("none"));
    }
}
