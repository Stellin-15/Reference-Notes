// ============================================================
// L01: Java Language Basics (JDK 25 LTS)
// ============================================================
// WHAT: The dev.java "Getting Started" and "Language Basics"
//       tutorials plus the JLS fundamentals: running code
//       (compact source files, the source launcher, jshell),
//       primitive and reference types, literals, `var`,
//       operators and promotion rules, control flow (incl.
//       switch expressions), arrays, strings, text blocks,
//       StringBuilder, string formatting, and the wrapper
//       classes with autoboxing pitfalls.
// WHY:  Java's basics hide real traps: integer overflow is
//       silent, `==` on Integer works below 128 and breaks above
//       it, `char` arithmetic yields int, and floating point
//       money is wrong. Every later lesson assumes this layer.
// LEVEL: Foundation
// RUN:   java L01_language_basics.java   (JDK 11+ source launcher;
//        this file uses JDK 25 features — compact source files
//        are final in JDK 25 via JEP 512)
// SOURCE: dev.java/learn (Getting Started, Language Basics,
//         Numbers & Strings), JLS 25 ch. 3-5, 14-15, JEP 512
// ============================================================
/*
CONCEPT OVERVIEW:
    Java source compiles to bytecode (.class) that runs on the JVM.
    Every value is either a PRIMITIVE (8 kinds, stored by value)
    or a REFERENCE (pointer to an object on the heap, or null).
    Java is statically and strongly typed; since Java 10, `var`
    infers LOCAL variable types — still static typing.
    Since JDK 25 (JEP 512) a file can be a "compact source file":
    top-level methods and fields with an implicitly declared class
    and an instance `void main()` — no `public static void
    main(String[] args)` ceremony. `IO.println` (java.lang.IO) is
    available without imports.

PRODUCTION USE CASE:
    A small invoice calculator: parses quantities, computes
    totals with BigDecimal (never double for money), formats a
    text-block report, and guards against int overflow.

COMMON MISTAKES:
    1. Comparing Strings or boxed Integers with `==` — compares
       references. Use .equals() / Objects.equals().
    2. Money in double: 0.1 + 0.2 != 0.3. Use BigDecimal (with
       String constructor) or long minor units (cents).
    3. Silent int overflow: Integer.MAX_VALUE + 1 is negative.
       Use Math.addExact / multiplyExact or long.
    4. String concatenation in loops — use StringBuilder (the
       compiler only optimises a single expression).
    5. Integer division: 5 / 2 == 2. Cast first: 5 / 2.0.
    6. Unboxing null: `int x = map.get(k);` throws NPE when the
       key is absent.
*/

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Arrays;
import java.util.Locale;

// ============================================================
// SECTION 1: RUNNING JAVA — THE FOUR WAYS
// ============================================================
// 1. Classic:   javac Hello.java && java Hello
// 2. Source launcher (JDK 11, JEP 330): java Hello.java — compiles in memory.
//    JDK 22 (JEP 458) lets it run multi-file programs: other .java files in
//    the same directory tree are compiled on demand.
// 3. jshell (JDK 9): interactive REPL — /vars, /methods, /save, /open.
// 4. Packaged: java -jar app.jar (manifest Main-Class) or jlink/jpackage
//    custom runtimes (L07).
//
// This file is a regular class so it can host nested examples. The
// compact form (JEP 512, final in 25) looks like this — a complete program:
//     void main() {
//         IO.println("Hello, World!");
//     }
// Implicit classes automatically import every exported package of
// java.base (module import, JEP 511) — so List, Map, etc. need no imports.

public class L01_language_basics {

    // ========================================================
    // SECTION 2: PRIMITIVE TYPES
    // ========================================================
    //  type     bits  range / notes                         default
    //  byte       8   -128 .. 127                            0
    //  short     16   -32768 .. 32767                        0
    //  int       32   -2^31 .. 2^31-1  (~±2.1 billion)       0
    //  long      64   -2^63 .. 2^63-1  (suffix L)            0L
    //  float     32   IEEE-754, ~7 digits (suffix f)         0.0f
    //  double    64   IEEE-754, ~15-16 digits                0.0d
    //  char      16   UTF-16 code UNIT '\u0000'..'￿'    '\u0000'
    //  boolean    -   true / false (not numbers!)            false
    // Defaults apply to FIELDS and array elements only. Local variables
    // must be definitely assigned before use (compile error otherwise).
    static void primitives() {
        int decimal = 1_000_000;          // underscores for readability (Java 7)
        int hex = 0xFF, octal = 017, binary = 0b1010;
        long big = 9_223_372_036_854_775_807L;
        float f = 3.14f;                  // without f it's a double literal → error
        double d = 1.5e-3;
        char c = 'A';
        char unicode = 'Ω';          // Ω
        boolean flag = decimal > 0;

        IO.println("literals: " + decimal + " " + hex + " " + octal + " " + binary + " " + big
                + " " + f + " " + d + " " + c + " " + unicode + " " + flag);

        // char arithmetic promotes to int:
        IO.println("'A' + 1 = " + (c + 1) + ", (char)('A' + 1) = " + (char) (c + 1)); // 66 and B

        // Silent overflow wraps around (two's complement):
        int max = Integer.MAX_VALUE;
        IO.println("MAX_VALUE + 1 = " + (max + 1));            // -2147483648
        try {
            Math.addExact(max, 1);                              // throws instead
        } catch (ArithmeticException e) {
            IO.println("addExact: " + e.getMessage());          // "integer overflow"
        }

        // Narrowing casts truncate bits; widening is implicit.
        long widened = max;                // int → long, implicit
        byte truncated = (byte) 200;       // 200 - 256 = -56
        int fromDouble = (int) 3.99;       // truncates toward zero → 3
        IO.println("casts: " + widened + " " + truncated + " " + fromDouble);

        // Floating point is binary — 0.1 has no exact representation:
        IO.println("0.1 + 0.2 = " + (0.1 + 0.2));               // 0.30000000000000004
        IO.println("1.0 / 0 = " + (1.0 / 0) + ", 0.0/0 = " + (0.0 / 0)); // Infinity, NaN
        IO.println("NaN == NaN? " + (Double.NaN == Double.NaN)); // false! use Double.isNaN
        // Integer division by zero, by contrast, throws ArithmeticException.
    }

    // ========================================================
    // SECTION 3: VARIABLES, `var`, `final`, SCOPE
    // ========================================================
    static void variables() {
        var count = 10;                    // inferred int (local variables only)
        var names = new java.util.ArrayList<String>(); // ArrayList<String>
        // var x;            // error: cannot infer without initializer
        // var n = null;     // error: null has no type to infer
        final int limit = 3;               // can't be reassigned
        // limit = 4;        // error
        for (var i = 0; i < limit; i++) names.add("n" + i);
        IO.println("var: " + count + " " + names);
        // Unnamed variables `_` (JDK 22, JEP 456) for values you must declare but ignore:
        int total = 0;
        for (var _ : names) total++;
        IO.println("counted with unnamed var: " + total);
        // Naming conventions: camelCase variables/methods, PascalCase types,
        // UPPER_SNAKE constants (static final), lowercase.dotted packages.
    }

    // ========================================================
    // SECTION 4: OPERATORS & PRECEDENCE
    // ========================================================
    // Precedence (high → low): postfix x++ ; unary ++x -x !x ~x ; cast ;
    // * / % ; + - ; << >> >>> ; < > <= >= instanceof ; == != ; & ; ^ ; | ;
    // && ; || ; ?: ; assignment = += -= ...
    static void operators() {
        int a = 7, b = 2;
        IO.println("arith: " + (a / b) + " " + (a % b) + " " + (a / (double) b) + " " + (-7 % 2)); // 3 1 3.5 -1
        IO.println("floorMod(-7, 2) = " + Math.floorMod(-7, 2)); // 1 — use for wrap-around indices

        int i = 5;
        int post = i++;  // post = 5, i = 6
        int pre = ++i;   // i = 7, pre = 7
        IO.println("inc: " + post + " " + pre);

        // Compound assignment includes an implicit cast:
        byte by = 10;
        by += 5;          // OK: by = (byte)(by + 5)
        // by = by + 5;   // error: int → byte needs explicit cast

        // Bitwise & shifts: >> keeps sign, >>> fills with zeros
        IO.println("bits: " + (6 & 3) + " " + (6 | 3) + " " + (6 ^ 3) + " " + (~6) + " "
                + (-16 >> 2) + " " + (-16 >>> 28));

        // Short-circuit: && and || skip the right side; & and | don't.
        String s = null;
        boolean safe = s != null && s.length() > 3;   // no NPE
        IO.println("short-circuit: " + safe);

        // String concatenation is left-to-right:
        IO.println(1 + 2 + "3" + 4 + 5);              // "3345"
    }

    // ========================================================
    // SECTION 5: CONTROL FLOW
    // ========================================================
    enum Day { MON, TUE, WED, THU, FRI, SAT, SUN }

    static void controlFlow() {
        // Labeled break/continue for nested loops:
        outer:
        for (int r = 0; r < 3; r++) {
            for (int c = 0; c < 3; c++) {
                if (c == 2) continue outer;
                if (r == 2) break outer;
                IO.print("(" + r + "," + c + ") ");
            }
        }
        IO.println();

        int n = 0;
        do { n++; } while (n < 3);   // body runs at least once
        IO.println("do-while ran to " + n);

        // Switch EXPRESSION (Java 14): arrow labels, no fall-through,
        // yields a value, must be exhaustive.
        for (Day day : new Day[] {Day.MON, Day.SAT}) {
            int letters = switch (day) {
                case MON, FRI, SUN -> 6;
                case TUE -> 7;
                case THU, SAT -> 8;
                case WED -> {
                    int len = day.toString().length();
                    yield len + 6;    // `yield` returns from a block arm
                }
            };
            String kind = switch (day) {
                case SAT, SUN -> "weekend";
                default -> "weekday";
            };
            IO.println(day + " -> " + letters + " " + kind);
        }
        // Old-style switch statements with `case X:` still fall through
        // without `break` — a classic bug. Prefer arrows.
        // Pattern matching in switch (type patterns, guards, records) → L05.
    }

    // ========================================================
    // SECTION 6: ARRAYS
    // ========================================================
    static void arrays() {
        int[] nums = {5, 3, 9, 1};
        int[] zeros = new int[4];                 // default 0s
        String[] words = new String[2];           // default nulls
        int[][] grid = {{1, 2}, {3, 4, 5}};       // jagged: rows may differ
        Arrays.sort(nums);
        IO.println("sorted " + Arrays.toString(nums) + ", binarySearch(9)=" + Arrays.binarySearch(nums, 9));
        IO.println("deep " + Arrays.deepToString(grid) + " zeros " + Arrays.toString(zeros) + " words " + Arrays.toString(words));
        int[] copy = Arrays.copyOf(nums, 6);      // pads with 0
        IO.println("copyOf " + Arrays.toString(copy) + " equals? " + Arrays.equals(nums, Arrays.copyOf(copy, 4)));
        // Arrays are COVARIANT and checked at runtime:
        Object[] objs = new String[1];
        try { objs[0] = 42; } catch (ArrayStoreException e) { IO.println("ArrayStoreException: " + e.getMessage()); }
        // Arrays have fixed length (.length field, not method). Use List for growable.
    }

    // ========================================================
    // SECTION 7: STRINGS, TEXT BLOCKS, FORMATTING
    // ========================================================
    static void strings() {
        String a = "hello";
        String b = "hel" + "lo";                    // compile-time constant → interned, same object
        String c = new String("hello");             // new object
        IO.println("== : " + (a == b) + " " + (a == c) + " ; equals: " + a.equals(c));

        // Strings are immutable; every "modification" returns a new String.
        String s = "  Java Streams  ";
        IO.println("[" + s.strip() + "] [" + s.trim().toUpperCase() + "] blank? " + "   ".isBlank());
        IO.println("repeat/chars: " + "ab".repeat(3) + " " + "a,b,,c".split(",").length + " "
                + String.join("|", "x", "y") + " " + "hello".chars().filter(ch -> ch == 'l').count());
        IO.println("indexOf/substring: " + a.indexOf('l') + " " + a.substring(1, 3) + " " + a.contains("ell"));

        // Text blocks (Java 15): multi-line literals; incidental indentation stripped.
        String json = """
                {
                  "name": "Ada",
                  "langs": ["Java", "Rust"]
                }
                """;
        IO.print(json);
        // Escapes inside text blocks: \<newline> joins lines, \s keeps a trailing space.

        // Formatting
        IO.println(String.format(Locale.ROOT, "%-8s|%6.2f|%05d|%,d|%x", "pad", 3.14159, 42, 1234567, 255));
        IO.println("%s has %d items".formatted("cart", 3));   // Java 15 instance method

        // StringBuilder for loops (not thread-safe; StringBuffer is synchronized, legacy).
        var sb = new StringBuilder();
        for (int i = 0; i < 5; i++) sb.append(i).append(',');
        sb.setLength(sb.length() - 1);
        IO.println("builder: " + sb.reverse());

        // Unicode: length() counts UTF-16 units, not characters.
        String emoji = "😀";
        IO.println("emoji length=" + emoji.length() + " codePoints=" + emoji.codePointCount(0, emoji.length()));
    }

    // ========================================================
    // SECTION 8: WRAPPERS, AUTOBOXING, NUMBERS
    // ========================================================
    static void wrappers() {
        Integer x = 127, y = 127;
        Integer p = 128, q = 128;
        IO.println("Integer cache: " + (x == y) + " " + (p == q) + " equals: " + p.equals(q)); // true false true
        // Integer.valueOf caches -128..127 — so == "works" in tests, fails in prod.

        java.util.Map<String, Integer> stock = new java.util.HashMap<>();
        try {
            int qty = stock.get("missing");           // unboxing null → NPE
            IO.println(qty);
        } catch (NullPointerException e) {
            IO.println("NPE unboxing null (helpful message): " + e.getMessage());
        }
        int qty = stock.getOrDefault("missing", 0);   // safe
        IO.println("getOrDefault: " + qty + ", parse: " + Integer.parseInt("42") + " " + Integer.toBinaryString(10)
                + " " + Long.MAX_VALUE + " " + Integer.compare(3, 7));

        // BigDecimal for money — ALWAYS construct from String.
        IO.println("BigDecimal(0.1)=" + new BigDecimal(0.1));          // the true binary value, ugly
        IO.println("BigDecimal(\"0.1\")+\"0.2\"=" + new BigDecimal("0.1").add(new BigDecimal("0.2")));
        // equals() compares scale too: 2.0 vs 2.00 not equal; use compareTo.
        IO.println("2.0 equals 2.00? " + new BigDecimal("2.0").equals(new BigDecimal("2.00"))
                + ", compareTo==0? " + (new BigDecimal("2.0").compareTo(new BigDecimal("2.00")) == 0));
    }

    // ========================================================
    // SECTION 9: METHODS
    // ========================================================
    // Java is pass-by-VALUE always. For references, the reference value
    // is copied: you can mutate the object, not rebind the caller's variable.
    static void mutate(int[] arr, int n) { arr[0] = 99; n = 99; }
    // Varargs: syntactic sugar for an array parameter (must be last).
    static int sum(int... values) { int t = 0; for (int v : values) t += v; return t; }
    // Overloading: same name, different parameter lists; resolved at COMPILE time.
    static String describe(int i) { return "int " + i; }
    static String describe(long l) { return "long " + l; }
    static String describe(Integer i) { return "Integer " + i; }
    static String describe(Object o) { return "Object " + o; }

    static void methods() {
        int[] arr = {1};
        int n = 1;
        mutate(arr, n);
        IO.println("pass-by-value: arr[0]=" + arr[0] + " n=" + n);   // 99, 1
        IO.println("varargs: " + sum() + " " + sum(1, 2, 3));
        // Overload resolution phases: exact/widening first, then boxing, then varargs.
        IO.println(describe(5) + " | " + describe(5L) + " | " + describe((short) 5) + " | " + describe("s"));
        // describe((short)5) → int (widening beats boxing)
    }

    // ========================================================
    // SECTION 10: END-TO-END — INVOICE CALCULATOR
    // ========================================================
    record Line(String sku, int qty, BigDecimal unitPrice) {}

    static String invoice(Line... lines) {
        BigDecimal subtotal = BigDecimal.ZERO;
        var body = new StringBuilder();
        for (Line l : lines) {
            if (l.qty() <= 0) throw new IllegalArgumentException("qty must be positive: " + l);
            BigDecimal lineTotal = l.unitPrice().multiply(BigDecimal.valueOf(l.qty()));
            subtotal = subtotal.add(lineTotal);
            body.append("%-6s x%3d  %10s%n".formatted(l.sku(), l.qty(), lineTotal.setScale(2, RoundingMode.HALF_EVEN)));
        }
        BigDecimal tax = subtotal.multiply(new BigDecimal("0.0825")).setScale(2, RoundingMode.HALF_EVEN); // banker's rounding
        BigDecimal total = subtotal.add(tax).setScale(2, RoundingMode.HALF_EVEN);
        return """
                INVOICE
                -----------------------
                %s-----------------------
                subtotal      %9s
                tax 8.25%%     %9s
                TOTAL         %9s
                """.formatted(body, subtotal.setScale(2, RoundingMode.HALF_EVEN), tax, total);
    }

    public static void main(String[] args) {
        primitives();
        variables();
        operators();
        controlFlow();
        arrays();
        strings();
        wrappers();
        methods();
        IO.print(invoice(
                new Line("A-100", 3, new BigDecimal("19.99")),
                new Line("B-200", 1, new BigDecimal("249.00")),
                new Line("C-300", 12, new BigDecimal("0.35"))));
    }
}
