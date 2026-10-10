// ============================================================
// L05: Pattern Matching & Data-Oriented Programming, I/O & NIO.2,
//      the Date-Time API
// ============================================================
// WHAT: dev.java "Pattern Matching", "Java I/O" (java.io and
//       java.nio.file), "Date Time" tutorials, and the JEPs
//       behind modern Java's data features: type patterns for
//       instanceof (16), switch patterns with guards and null
//       handling (21), record patterns and nested deconstruction
//       (21), unnamed patterns `_` (22); Files/Path API, reading
//       and writing text and bytes, directory walking, file
//       attributes, temp files, buffered streams and charsets,
//       WatchService; java.time — Instant, LocalDate/Time,
//       ZonedDateTime, Duration vs Period, formatting/parsing,
//       time zones and DST, Clock for testability.
// WHY:  Pattern matching + records + sealed types (L02) turn Java
//       into a language for modelling data as algebraic types —
//       the compiler checks that every case is handled. File I/O
//       and time handling are where production incidents come
//       from: wrong charset, unclosed streams, DST gaps, and
//       `new Date()` in business logic.
// LEVEL: Intermediate → Advanced
// RUN:   java L05_pattern_matching_io_datetime.java   (JDK 25)
// SOURCE: dev.java/learn/pattern-matching, /java-io, /date-time;
//         JEP 394, 440, 441, 456; JDK 25 Javadoc for java.nio.file,
//         java.time. Preview (not used here): JEP 530/532 primitive
//         types in patterns (4th/5th preview in JDK 26/27).
// ============================================================
/*
CONCEPT OVERVIEW:
    A PATTERN tests a value's shape and binds variables on success:
      o instanceof String s                 type pattern
      case Point(var x, var y)              record pattern
      case Circle c when c.r() > 10         guarded pattern
      case Shape(_, Color c)                unnamed pattern
    switch over a SEALED type is checked for EXHAUSTIVENESS: add a
    new permitted subtype and every non-exhaustive switch breaks
    at compile time — the "data-oriented programming" payoff.

    I/O: java.io = streams of bytes/chars (InputStream/Reader).
    java.nio.file (Java 7) = Path + Files: the API to use for
    files. Always specify the charset (UTF-8 is default since
    JDK 18, JEP 400, but be explicit in libraries).

    TIME: Instant = a point on the UTC timeline (machine time).
    LocalDate/LocalDateTime = no zone (a calendar/wall value).
    ZonedDateTime = local + zone rules. Store Instants, display
    in the user's zone.

PRODUCTION USE CASE:
    An expression evaluator for a pricing-rules engine (sealed
    AST + exhaustive switch), a log-file ingester using NIO.2,
    and a billing-period calculator correct across DST and
    month-ends.

COMMON MISTAKES:
    1. `switch` with `default` over a sealed type — it hides the
       compile error you WANT when a new subtype is added.
    2. Dominated patterns: `case Object o` before `case String s`
       is a compile error; order specific → general.
    3. Files.lines / Files.list / Files.walk return streams that
       hold OS handles — use try-with-resources.
    4. Files.readAllLines on a multi-GB file → OOM. Stream it.
    5. Using LocalDateTime for timestamps of events — it has no
       zone, so it can't identify an instant. Use Instant/OffsetDateTime.
    6. `plusDays(1)` vs `plus(Duration.ofHours(24))` across DST —
       not the same; Period is calendar-based, Duration exact.
    7. Pattern "YYYY" (week-based year) instead of "yyyy" (or "uuuu").
*/

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.time.temporal.TemporalAdjusters;
import java.util.*;
import java.util.stream.Collectors;
import java.util.stream.Stream;

public class L05_pattern_matching_io_datetime {

    // ========================================================
    // SECTION 1: TYPE PATTERNS WITH instanceof (Java 16)
    // ========================================================
    static String describe(Object o) {
        // Before: if (o instanceof String) { String s = (String) o; ... }
        if (o instanceof String s && !s.isBlank()) return "non-blank string of length " + s.length();
        if (!(o instanceof Number n)) return "not a number: " + o;
        return "number with double value " + n.doubleValue();   // n in scope: flow-sensitive
    }

    // ========================================================
    // SECTION 2: SWITCH PATTERNS (Java 21, JEP 441)
    // ========================================================
    static String classify(Object o) {
        return switch (o) {
            case null -> "null (switch handles it explicitly; otherwise NPE)";
            case Integer i when i < 0 -> "negative int";            // guard with `when`
            case Integer i -> "int " + i;
            case Long l -> "long " + l;
            case String s when s.length() > 5 -> "long string";
            case String s -> "short string '" + s + "'";
            case int[] arr -> "int array of " + arr.length;
            case List<?> list when list.isEmpty() -> "empty list";
            case List<?> list -> "list of " + list.size();
            default -> "other: " + o.getClass().getSimpleName();    // Object isn't sealed → default needed
        };
    }
    // Enum constants can be qualified in case labels (21): case Color.RED -> ...
    // and mixed with patterns when switching over a sealed interface they implement.

    // ========================================================
    // SECTION 3: RECORD PATTERNS & EXHAUSTIVENESS (Java 21, JEP 440)
    // ========================================================
    // A pricing-rules expression language as an algebraic data type.
    sealed interface Expr permits Num, Var, Add, Mul, Neg, IfGt {}
    record Num(double value) implements Expr {}
    record Var(String name) implements Expr {}
    record Add(Expr left, Expr right) implements Expr {}
    record Mul(Expr left, Expr right) implements Expr {}
    record Neg(Expr inner) implements Expr {}
    record IfGt(Expr a, Expr b, Expr then, Expr otherwise) implements Expr {}

    static double eval(Expr e, Map<String, Double> env) {
        return switch (e) {                                          // no default: compiler proves exhaustive
            case Num(var v) -> v;
            case Var(var name) -> Optional.ofNullable(env.get(name))
                    .orElseThrow(() -> new NoSuchElementException("unbound variable " + name));
            case Add(var l, var r) -> eval(l, env) + eval(r, env);
            case Mul(var l, var r) -> eval(l, env) * eval(r, env);
            case Neg(var inner) -> -eval(inner, env);
            case IfGt(var a, var b, var t, var f) -> eval(a, env) > eval(b, env) ? eval(t, env) : eval(f, env);
        };
    }

    // Nested patterns make algebraic simplification read like the math.
    static Expr simplify(Expr e) {
        return switch (e) {
            case Add(Num(var a), Num(var b)) -> new Num(a + b);       // constant folding
            case Mul(Num(var a), Num(var b)) -> new Num(a * b);
            case Add(var x, Num(var z)) when z == 0 -> simplify(x);   // x + 0 = x
            case Mul(var x, Num(var one)) when one == 1 -> simplify(x);
            case Mul(_, Num(var z)) when z == 0 -> new Num(0);        // unnamed pattern `_` (22)
            case Neg(Neg(var x)) -> simplify(x);                       // --x = x
            case Add(var l, var r) -> rebuildIfChanged(e, new Add(simplify(l), simplify(r)));
            case Mul(var l, var r) -> rebuildIfChanged(e, new Mul(simplify(l), simplify(r)));
            case Neg(var x) -> new Neg(simplify(x));
            case Num n -> n;
            case Var v -> v;
            case IfGt(var a, var b, var t, var f) -> new IfGt(simplify(a), simplify(b), simplify(t), simplify(f));
        };
    }
    static Expr rebuildIfChanged(Expr original, Expr rebuilt) {
        return rebuilt.equals(original) ? original : simplify(rebuilt);  // records give structural equals for free
    }

    static String show(Expr e) {
        return switch (e) {
            case Num(var v) -> v == Math.rint(v) ? String.valueOf((long) v) : String.valueOf(v);
            case Var(var n) -> n;
            case Add(var l, var r) -> "(" + show(l) + " + " + show(r) + ")";
            case Mul(var l, var r) -> show(l) + "·" + show(r);
            case Neg(var x) -> "-" + show(x);
            case IfGt(var a, var b, var t, var f) -> "if(" + show(a) + ">" + show(b) + ", " + show(t) + ", " + show(f) + ")";
        };
    }
    // Generic record patterns infer type args: case Box<String>(var s) or case Box(var s).
    // Record patterns also work in instanceof: if (o instanceof Point(int x, int y)) ...
    // Data-oriented programming principles (Brian Goetz): model data as
    // immutable records, make illegal states unrepresentable with sealed
    // types, validate at construction, keep behaviour in switch-based functions.

    // ========================================================
    // SECTION 4: NIO.2 — Path & Files
    // ========================================================
    static void files(Path dir) throws IOException {
        Path log = dir.resolve("app.log");                        // Path ops are pure (no I/O)
        IO.println("path ops: name=" + log.getFileName() + " parent=" + log.getParent().getFileName()
                + " normalize=" + Path.of("a/./b/../c").normalize() + " relativize=" + Path.of("/x/y").relativize(Path.of("/x/z/w")));

        // Write — small files in one call; options control create/append/truncate.
        Files.writeString(log, """
                2026-10-10T08:00:01Z INFO  order=o1 latency_ms=120
                2026-10-10T08:00:02Z ERROR order=o2 latency_ms=3400 msg="gateway timeout"
                2026-10-10T08:00:03Z INFO  order=o3 latency_ms=95
                """, StandardCharsets.UTF_8);
        Files.writeString(log, "2026-10-10T08:00:04Z WARN  order=o4 latency_ms=900\n",
                StandardCharsets.UTF_8, StandardOpenOption.APPEND);

        // Stream lines lazily; the stream holds a file handle → try-with-resources.
        try (Stream<String> lines = Files.lines(log, StandardCharsets.UTF_8)) {
            Map<String, Long> byLevel = lines.map(l -> l.split("\\s+")[1])
                    .collect(Collectors.groupingBy(lvl -> lvl, TreeMap::new, Collectors.counting()));
            IO.println("levels: " + byLevel);
        }

        // BufferedReader/Writer for line-oriented processing with control.
        Path errors = dir.resolve("errors.log");
        try (BufferedReader in = Files.newBufferedReader(log);
             BufferedWriter out = Files.newBufferedWriter(errors)) {
            String line;
            while ((line = in.readLine()) != null) {
                if (line.contains("ERROR") || line.contains("WARN")) { out.write(line); out.newLine(); }
            }
        }
        IO.println("errors.log lines=" + Files.readAllLines(errors).size() + " size=" + Files.size(errors) + "B");

        // Directories, copy/move, attributes, walking.
        Path archive = Files.createDirectories(dir.resolve("archive/2026/10"));
        Files.copy(errors, archive.resolve("errors-1.log"), StandardCopyOption.REPLACE_EXISTING);
        Files.move(errors, archive.resolve("errors-2.log"), StandardCopyOption.ATOMIC_MOVE);
        BasicFileAttributes attrs = Files.readAttributes(log, BasicFileAttributes.class);
        IO.println("attrs: regular=" + attrs.isRegularFile() + " size=" + attrs.size() + " exists(errors)=" + Files.exists(errors));
        try (Stream<Path> walk = Files.walk(dir)) {
            IO.println("walk: " + walk.filter(Files::isRegularFile).map(p -> dir.relativize(p).toString().replace('\\', '/')).sorted().toList());
        }
        try (DirectoryStream<Path> ds = Files.newDirectoryStream(archive, "*.log")) {   // glob filter
            int n = 0; for (Path ignored : ds) n++;
            IO.println("glob *.log in archive: " + n);
        }
        // Files.find(start, depth, (path, attrs) -> ...), Files.walkFileTree(visitor)
        // for delete-recursive; Files.mismatch (12) compares contents;
        // WatchService (FileSystems.getDefault().newWatchService()) gets
        // ENTRY_CREATE/MODIFY/DELETE events for config hot-reload.
    }

    // ========================================================
    // SECTION 5: java.io BYTE & CHAR STREAMS (decorator pattern)
    // ========================================================
    // InputStream/OutputStream = bytes; Reader/Writer = chars.
    // Decorators stack: new BufferedInputStream(new FileInputStream(f)),
    // DataInputStream (primitives), ObjectInputStream (serialization —
    // a known RCE vector: never deserialize untrusted data; use JSON/protobuf,
    // and ObjectInputFilter (9) if you must).
    static void ioStreams() throws IOException {
        var bytes = new ByteArrayOutputStream();
        try (var out = new DataOutputStream(new BufferedOutputStream(bytes))) {
            out.writeInt(0xCAFEBABE);       // the class-file magic number
            out.writeUTF("héllo");          // modified UTF-8 with length prefix
            out.writeDouble(Math.PI);
        }
        try (var in = new DataInputStream(new ByteArrayInputStream(bytes.toByteArray()))) {
            IO.println("data stream: " + Integer.toHexString(in.readInt()) + " " + in.readUTF() + " " + in.readDouble()
                    + " (" + bytes.size() + " bytes)");
        }
        // Charset matters: same text, different byte counts.
        String s = "Grüße 👋";
        IO.println("UTF-8 bytes=" + s.getBytes(StandardCharsets.UTF_8).length + " UTF-16 bytes=" + s.getBytes(StandardCharsets.UTF_16).length
                + " ISO-8859-1 lossy=" + new String(s.getBytes(StandardCharsets.ISO_8859_1), StandardCharsets.ISO_8859_1));
        // InputStream.transferTo(out) (9), readAllBytes (9), readNBytes — no more manual copy loops.
    }

    // ========================================================
    // SECTION 6: THE DATE-TIME API (java.time, JSR-310)
    // ========================================================
    static void dateTime() {
        // A fixed Clock makes "now" deterministic — inject Clock in production code too.
        Clock clock = Clock.fixed(Instant.parse("2026-03-07T15:30:00Z"), ZoneOffset.UTC);
        Instant now = Instant.now(clock);
        ZoneId ny = ZoneId.of("America/New_York");
        ZonedDateTime nyNow = now.atZone(ny);
        IO.println("instant=" + now + " in NY=" + nyNow + " epochMillis=" + now.toEpochMilli());

        // DST: US clocks spring forward 2026-03-08 02:00 → 03:00.
        ZonedDateTime beforeDst = ZonedDateTime.of(2026, 3, 7, 12, 0, 0, 0, ny);
        IO.println("plusDays(1)=" + beforeDst.plusDays(1).toLocalTime() + " vs plus(24h)=" + beforeDst.plus(Duration.ofHours(24)).toLocalTime());
        LocalDateTime gap = LocalDateTime.of(2026, 3, 8, 2, 30);   // doesn't exist in NY
        IO.println("gap time 02:30 resolves to " + gap.atZone(ny).toLocalTime() + " (shifted forward)");

        // Period (calendar: y/m/d) vs Duration (exact seconds/nanos).
        LocalDate start = LocalDate.of(2026, 1, 31);
        IO.println("Jan 31 + 1 month = " + start.plusMonths(1) + " (clamped)  Period between="
                + Period.between(start, LocalDate.of(2026, 10, 10)) + " days=" + ChronoUnit.DAYS.between(start, LocalDate.of(2026, 10, 10)));

        // Adjusters for business rules
        LocalDate today = LocalDate.now(clock);
        IO.println("end of month=" + today.with(TemporalAdjusters.lastDayOfMonth())
                + " next Monday=" + today.with(TemporalAdjusters.next(DayOfWeek.MONDAY))
                + " first Friday next month=" + today.plusMonths(1).with(TemporalAdjusters.firstInMonth(DayOfWeek.FRIDAY)));

        // Formatting/parsing — formatters are immutable & thread-safe (unlike SimpleDateFormat).
        var fmt = DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm zzz", Locale.ROOT);
        IO.println("formatted=" + nyNow.format(fmt) + " ISO=" + DateTimeFormatter.ISO_OFFSET_DATE_TIME.format(nyNow.toOffsetDateTime())
                + " parsed=" + LocalDate.parse("2026-12-25").getDayOfWeek());
        // "YYYY" bug: week-based year. 2026-12-28 is in week 1 of 2027:
        IO.println("YYYY trap: " + LocalDate.of(2026, 12, 28).format(DateTimeFormatter.ofPattern("YYYY-MM-dd", Locale.ROOT)));
        // Legacy interop: Date.from(instant), date.toInstant(), TimeZone.toZoneId().
    }

    // Billing periods: monthly anniversary billing that stays correct at month-ends.
    static List<LocalDate> billingDates(LocalDate anchor, int periods) {
        var out = new ArrayList<LocalDate>();
        for (int i = 0; i < periods; i++) out.add(anchor.plusMonths(i));   // always from the ANCHOR, never chained
        return out;
    }

    public static void main(String[] args) throws IOException {
        IO.println("== instanceof patterns: " + describe("hi") + " | " + describe(42) + " | " + describe(List.of()));
        IO.println("== switch patterns:");
        for (Object o : Arrays.asList(null, -5, 7, 9L, "hello world", "hey", new int[3], List.of(), List.of(1, 2), 3.0))
            IO.println("   " + classify(o));

        IO.println("== record patterns / ADT:");
        // price = base * qty + (if qty > 10 then -discount else 0) + 0
        Expr price = new Add(new Add(new Mul(new Var("base"), new Var("qty")),
                new IfGt(new Var("qty"), new Num(10), new Neg(new Var("discount")), new Num(0))), new Num(0));
        var env = Map.of("base", 19.99, "qty", 12.0, "discount", 25.0);
        IO.println("   expr     = " + show(price));
        IO.println("   simplify = " + show(simplify(price)));
        IO.println("   eval     = " + Math.round(eval(price, env) * 100) / 100.0);
        IO.println("   fold     = " + show(simplify(new Mul(new Add(new Num(2), new Num(3)), new Neg(new Neg(new Var("x")))))));
        try { eval(new Var("tax"), env); } catch (NoSuchElementException e) { IO.println("   " + e.getMessage()); }

        IO.println("== NIO.2 files:");
        Path tmp = Files.createTempDirectory("l05-");
        try {
            files(tmp);
        } finally {
            try (Stream<Path> walk = Files.walk(tmp)) {                  // recursive delete: deepest first
                walk.sorted(Comparator.reverseOrder()).forEach(p -> p.toFile().delete());
            }
        }
        IO.println("== java.io:"); ioStreams();
        IO.println("== java.time:"); dateTime();
        IO.println("   billing from Jan 31: " + billingDates(LocalDate.of(2026, 1, 31), 4));
    }
}
