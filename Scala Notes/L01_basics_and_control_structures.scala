// ============================================================
// L01: Scala 3 Basics — Syntax, Values & Types, Strings,
//      Control Structures, Methods, Main Methods
// ============================================================
// WHAT: Scala 3 Book chapters "A Taste of Scala", "A First Look
//       at Types", "String Interpolation", "Control Structures",
//       "Methods" and "Main Methods": the optional-braces
//       (indentation) syntax, val/var, the type hierarchy (Any,
//       AnyVal, AnyRef, Nothing, Null, Unit), literals, string
//       interpolators (s, f, raw, custom), if/match/for/while as
//       EXPRESSIONS, for-comprehensions with guards and yield,
//       try/catch/finally, default & named arguments, varargs,
//       multiple parameter lists, @main methods and top-level
//       definitions — on Scala 3.9 LTS (Sept 2026).
// WHY:  Scala's basics are expression-oriented: almost
//       everything returns a value. Internalising that (and
//       `match` as the central control structure) is what makes
//       the functional and type-level lessons later feel natural.
// LEVEL: Foundation
// RUN:   scala-cli run L01_basics_and_control_structures.scala
//        (or: scala run ... — scala-cli is the official `scala` command since 3.5)
// SOURCE: docs.scala-lang.org/scala3/book (taste-*, first-look-at-types,
//         string-interpolation, control-structures, methods-*),
//         Scala 3 reference: other-new-features/indentation, Scala 3.8/3.9 release notes
// ============================================================
/*
CONCEPT OVERVIEW:
    Scala compiles to JVM bytecode (also JavaScript via Scala.js
    and native code via Scala Native). It fuses object-oriented
    (every value is an object, classes/traits) and functional
    programming (functions are values, immutability by default,
    expressions everywhere) with a strong static type system and
    powerful inference.
    Scala 3 (2021) reworked the language: optional braces,
    enums, given/using, extension methods, union/intersection
    types, opaque types, a new macro system. Scala 3.9 is the
    current LTS (replacing 3.3 LTS); its standard library is now
    compiled by Scala 3 itself (since 3.8).

PRODUCTION USE CASE:
    A trade-blotter summariser: parses trade lines, classifies
    them with pattern matching, aggregates with for-comprehensions,
    and formats a report with interpolators — the kind of script
    Scala data/backend engineers write daily.

COMMON MISTAKES:
    1. Using `var` and mutable collections by habit. Default to
       `val` and immutable collections.
    2. Forgetting that the last expression is the result — writing
       `return` (discouraged; non-local return from lambdas is gone).
    3. Non-exhaustive `match` → MatchError at runtime. Heed the
       compiler's exhaustivity warnings (sealed types/enums).
    4. Mixing braces and indentation inconsistently in one file.
    5. `==` vs `eq`: `==` is value equality (calls equals, null-safe);
       `eq` is reference identity.
    6. Integer division and Int overflow behave exactly like Java.
*/

// ============================================================
// SECTION 1: MAIN METHODS & TOP-LEVEL DEFINITIONS
// ============================================================
// @main turns a method into a program entry point. Parameters are
// parsed from the command line (e.g. @main def run(n: Int, name: String)).
// Top-level defs/vals (no enclosing object) are allowed in Scala 3.
@main def lesson01(): Unit =
  section("values & types")(valuesAndTypes())
  section("strings")(strings())
  section("control structures")(controlStructures())
  section("methods")(methods())
  section("end-to-end: trade blotter")(Blotter.run())

def section(title: String)(body: => Unit): Unit =   // `=> Unit` is a BY-NAME parameter: evaluated lazily, inside
  println(s"== $title")
  body

// ============================================================
// SECTION 2: VALUES, VARIABLES, TYPES
// ============================================================
// Type hierarchy:
//   Any ─┬─ AnyVal: Int, Long, Double, Float, Short, Byte, Char, Boolean, Unit
//        └─ AnyRef (java.lang.Object): String, List, your classes...
//   Matchable (Scala 3) sits under Any: types you may pattern-match on.
//   Nothing: subtype of everything (type of `throw`, `???`).
//   Null: type of `null`; with -Yexplicit-nulls it's no longer a subtype of AnyRef.
def valuesAndTypes(): Unit =
  val immutable = 42                 // inferred Int; cannot be reassigned
  var counter = 0                    // mutable — use sparingly
  counter += 1
  val big: Long = 9_000_000_000L
  val ratio = 0.1 + 0.2              // Double
  val money = BigDecimal("0.1") + BigDecimal("0.2")
  val ch = 'A'
  val unit: Unit = ()                // Unit has exactly one value: ()
  println(s"   $immutable $counter $big $ratio $money ${ch + 1} ${(ch + 1).toChar} unit=$unit")

  // Everything is an object: methods on Int, operators are methods.
  println(s"   1.+(2) = ${1.+(2)}  5.max(3) = ${5.max(3)}  -7 % 2 = ${-7 % 2}  Math.floorMod(-7,2) = ${Math.floorMod(-7, 2)}")
  println(s"   Int.MaxValue + 1 = ${Int.MaxValue + 1} (wraps, like Java); Math.addExact throws")

  // Type ascription & conversions
  val n: Double = 3                  // Int literal widened
  val truncated = 3.99.toInt
  val parsed = "42".toIntOption      // Option[Int] — safe parse
  println(s"   widened=$n truncated=$truncated toIntOption=${parsed} bad=${"x".toIntOption}")

  // Lazy val: computed once, on first access (thread-safe).
  lazy val expensive = { println("   (computing expensive...)"); 99 }
  println(s"   before access"); println(s"   lazy=$expensive again=$expensive")

  // Equality: == is value equality (null-safe); eq is reference identity
  val a = "hello"; val b = new String("hello")
  println(s"   a == b: ${a == b}   a eq b: ${a eq b}")

// ============================================================
// SECTION 3: STRING INTERPOLATION & STRINGS
// ============================================================
// Custom interpolator: `money"..."` — any StringContext extension.
extension (sc: StringContext)
  def money(args: Any*): String =
    sc.s(args.map {
      case d: BigDecimal => f"$$${d.setScale(2, BigDecimal.RoundingMode.HALF_EVEN)}%s"
      case other => other
    }*)

def strings(): Unit =
  val name = "Ada"; val score = 97.456
  println(s"   s: Hello $name, next year ${2026 + 1}")
  println(f"   f: $name%-6s|$score%8.2f|${42}%05d")       // printf-style, type-checked at compile time
  println(raw"   raw: C:\new\table  (no escape processing)")
  println(money"   custom: total is ${BigDecimal("1234.5")} for $name")

  // Multi-line strings with stripMargin
  val sql =
    """SELECT id, total
      |FROM orders
      |WHERE total > 100""".stripMargin
  println(sql.linesIterator.map("   " + _).mkString("\n"))

  // Strings are java.lang.String + rich ops from StringOps
  val s = "  Scala 3.9 LTS  "
  println(s"   trim='${s.trim}' upper=${s.trim.toUpperCase} split=${"a,b,,c".split(",").toList} "
    + s"reverse=${"abc".reverse} capitalize=${"scala".capitalize} * = ${"ab" * 3} count(a)=${"banana".count(_ == 'a')}")

// ============================================================
// SECTION 4: CONTROL STRUCTURES — all are expressions
// ============================================================
enum Side:
  case Buy, Sell

def controlStructures(): Unit =
  // if/else is an expression (Scala has no ternary operator)
  val x = 7
  val parity = if x % 2 == 0 then "even" else "odd"
  println(s"   if-expression: $parity")

  // match: the central control structure
  def describe(v: Matchable): String = v match
    case 0                      => "zero"
    case i: Int if i < 0        => s"negative int $i"           // type pattern + guard
    case i: Int                 => s"int $i"
    case "buy" | "sell"         => "trade side keyword"          // alternatives
    case s: String              => s"string of ${s.length}"
    case (a, b)                 => s"tuple ($a, $b)"             // tuple pattern
    case List(1, rest*)         => s"list starting with 1, then ${rest.size} more"   // sequence pattern
    case Side.Buy               => "enum Buy"
    case _                      => "something else"
  List[Matchable](0, -3, 5, "buy", "hello", (1, "a"), List(1, 2, 3), Side.Buy, 3.14).foreach(v => println(s"   match ${v} → ${describe(v)}"))

  // for loops (side effects) vs for-COMPREHENSIONS (yield a value)
  for i <- 1 to 3 do print(s"   i=$i")
  println()
  val pairs =
    for
      i <- 1 to 3
      j <- 'a' to 'b'
      if i != 2                          // guard
      label = s"$i$j"                    // value definition inside the comprehension
    yield label
  println(s"   for/yield: $pairs")
  // A for-comprehension desugars to flatMap/map/withFilter — so it works on
  // Option, Either, Future, List... anything with those methods (L06).

  // while (rarely needed), do-while was removed in Scala 3: use while with a block condition
  var n = 3
  while n > 0 do n -= 1
  println(s"   while done, n=$n")

  // try/catch/finally is an expression; catch uses case patterns
  def safeDivide(a: Int, b: Int): Either[String, Int] =
    try Right(a / b)
    catch case e: ArithmeticException => Left(s"error: ${e.getMessage}")
    finally () // cleanup would go here
  println(s"   try as expression: ${safeDivide(10, 2)} ${safeDivide(1, 0)}")

  // Ranges
  println(s"   ranges: ${(1 to 10 by 3).toList} ${(10 until 0 by -4).toList} ${('a' to 'e').mkString}")

// ============================================================
// SECTION 5: METHODS
// ============================================================
def methods(): Unit =
  // Default and named arguments
  def connect(host: String = "localhost", port: Int = 5432, ssl: Boolean = false): String =
    s"${if ssl then "postgres+ssl" else "postgres"}://$host:$port"
  println(s"   ${connect()} | ${connect(port = 6543)} | ${connect(ssl = true, host = "db.prod")}")

  // Varargs and splatting a collection with *
  def sum(xs: Int*): Int = xs.sum
  val nums = List(1, 2, 3)
  println(s"   varargs: ${sum()} ${sum(4, 5)} ${sum(nums*)}")

  // Multiple parameter lists: curried, enable type inference & block syntax
  def retry[A](times: Int)(op: => A): A =
    var attempt = 1
    var result: Option[A] = None
    while result.isEmpty do
      try result = Some(op)
      catch case e: RuntimeException if attempt < times =>
        println(s"   attempt $attempt failed: ${e.getMessage}")
        attempt += 1
    result.get
  var calls = 0
  val v = retry(3) {
    calls += 1
    if calls < 3 then throw RuntimeException("flaky") else "ok on call 3"
  }
  println(s"   retry result: $v")

  // Methods are not functions, but convert automatically (eta-expansion):
  def square(i: Int) = i * i
  val f: Int => Int = square           // method → function value
  println(s"   eta-expansion: ${List(1, 2, 3).map(square)} ${f(9)}")

  // Recursion with @tailrec (compiler verifies it becomes a loop)
  @scala.annotation.tailrec
  def gcd(a: Long, b: Long): Long = if b == 0 then a else gcd(b, a % b)
  println(s"   tail-recursive gcd: ${gcd(1071, 462)}")

  // Return types: optional for private/local defs; annotate public API methods.
  // Procedures (Unit result) use `: Unit =` — the old `def f() { }` syntax is gone.

// ============================================================
// SECTION 6: END-TO-END — TRADE BLOTTER
// ============================================================
object Blotter:
  final case class Trade(id: String, symbol: String, side: Side, qty: Int, price: BigDecimal)

  private val raw = List(
    "T1,AAPL,BUY,100,231.50",
    "T2,AAPL,SELL,40,233.10",
    "T3,MSFT,BUY,50,512.25",
    "T4,NVDA,BUY,ten,180.00",      // bad qty
    "T5,MSFT,SELL,20,515.00",
    "T6,GOOG,HOLD,1,170.00",       // bad side
  )

  def parse(line: String): Either[String, Trade] =
    line.split(",").toList match
      case List(id, sym, side, qty, px) =>
        val parsedSide = side match
          case "BUY"  => Right(Side.Buy)
          case "SELL" => Right(Side.Sell)
          case other  => Left(s"$id: unknown side '$other'")
        for                                   // Either is right-biased: first Left short-circuits
          s <- parsedSide
          q <- qty.toIntOption.toRight(s"$id: bad quantity '$qty'")
          p <- scala.util.Try(BigDecimal(px)).toOption.toRight(s"$id: bad price '$px'")
        yield Trade(id, sym, s, q, p)
      case _ => Left(s"malformed line: $line")

  def run(): Unit =
    val (errors, trades) = raw.map(parse).partitionMap(identity)
    errors.foreach(e => println(s"   rejected → $e"))
    val positions =
      trades.groupMapReduce(_.symbol)(t => if t.side == Side.Buy then t.qty else -t.qty)(_ + _)
    val notional = trades.map(t => t.price * t.qty).sum
    println(f"   ${"SYMBOL"}%-6s ${"NET QTY"}%8s")
    for (sym, net) <- positions.toList.sortBy(_._1) do println(f"   $sym%-6s $net%8d")
    println(money"   gross notional ${notional}, ${trades.size} trades accepted")
