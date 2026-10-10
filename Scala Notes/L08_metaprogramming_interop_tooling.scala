// ============================================================
// L08: Metaprogramming, Java Interop, Tooling, Testing,
//      Cross-Platform & Migration
// ============================================================
// WHAT: Scala 3 reference "Metaprogramming" (inline, compile-time
//       operations, macros with quotes & splices, TASTy
//       reflection, staging), Scala 3 Book "Interacting with
//       Java" and "Scala Tools" (sbt, scala-cli, worksheets),
//       plus Mill, testing with MUnit/ScalaTest/ScalaCheck,
//       Scala.js & Scala Native, Spark/Flink usage, and the
//       Scala 2 → 3 migration guide.
// WHY:  Inline and macros are how Scala libraries give zero-cost
//       abstractions and compile-time validation (JSON codecs,
//       SQL checking in Quill/Magnum, refined types). Interop is
//       how Scala services use the entire Java ecosystem. The
//       build tool and test stack are the first thing you touch
//       on any team.
// LEVEL: Architect
// RUN:   scala-cli run L08_metaprogramming_interop_tooling.scala
// SOURCE: docs.scala-lang.org/scala3/reference/metaprogramming/*,
//         /scala3/book/interacting-with-java, /scala3/book/scala-tools,
//         scala-cli.virtuslab.org, scala-sbt.org, mill-build.org,
//         scalameta.org/munit, docs.scala-lang.org/scala3/guides/migration/*
// ============================================================
/*
CONCEPT OVERVIEW:
    METAPROGRAMMING LEVELS (least → most powerful):
      inline def / inline val / inline if / inline match — guaranteed
        inlining & compile-time branch selection
      scala.compiletime: constValue, erasedValue, error, summonInline,
        summonFrom, codeOf — type-level computation at expansion time
      Mirrors (scala.deriving) — generic derivation (L05)
      Macros: '{ quotes } and ${ splices } produce typed ASTs (Expr[T]),
        with reflection over TASTy (quotes.reflect) when needed
      Multi-stage programming (scala.quoted.staging) — generate &
        compile code at RUNTIME
    TASTy: Scala 3's typed AST format stored in .tasty files —
    enables macros, IDE tooling, and Scala 2.13 ↔ 3 interop.

PRODUCTION USE CASE:
    Compile-time validated configuration (bad literals fail the
    build), a zero-overhead debug-logging facility, Java SDK
    interop (CompletableFuture, java.time, Optional, functional
    interfaces), and the build/test setup for a service.

COMMON MISTAKES:
    1. Reaching for macros when inline + compiletime suffices.
    2. Defining a macro and calling it in the same compilation unit
       ("cannot call macro defined in the same source file").
    3. Leaking Java nulls into Scala code — wrap with Option(...)
       at the boundary (or enable explicit nulls).
    4. Forgetting `.asScala` / `.asJava` converters, or converting
       repeatedly in hot loops.
    5. Mixing Scala binary versions (_2.13 vs _3 artifacts) — use
       `::` in dependency syntax so the build picks the right one.
*/

import scala.compiletime.{constValue, error, codeOf}
import scala.jdk.CollectionConverters.*
import scala.jdk.FutureConverters.*
import scala.jdk.OptionConverters.*
import scala.concurrent.Await
import scala.concurrent.duration.*

@main def lesson08(): Unit =
  println("== inline & compile-time operations"); InlineDemo.run()
  println("== Java interop"); JavaInterop.run()
  println("== tooling, testing, platforms, migration — see reference sections below")

// ============================================================
// SECTION 1: INLINE & COMPILE-TIME OPERATIONS
// ============================================================
object InlineDemo:
  // inline val: a constant folded into every use site
  inline val DebugEnabled = false

  // inline def + inline if: when DebugEnabled is false, the call AND its message
  // construction disappear from the bytecode entirely (zero-cost logging).
  inline def debug(inline msg: String): Unit =
    inline if DebugEnabled then println(s"[debug] $msg")

  // Compile-time validation: a bad LITERAL fails compilation with a custom message.
  inline def port(inline p: Int): Int =
    inline if p < 1 || p > 65535 then error("port must be in 1..65535") else p
  // val bad = port(70000)     // compile error: port must be in 1..65535

  // transparent inline: the result type is refined to the inlined expression's type.
  transparent inline def defaultFor(inline kind: String): Any =
    inline kind match
      case "int"    => 0
      case "string" => ""
      case "list"   => List.empty[Int]
  val zero: Int = defaultFor("int")             // typed as Int, not Any
  val empty: String = defaultFor("string")

  // inline match on types + constValue: compute from literal types
  inline def bitsOf[T]: Int = inline compiletime.erasedValue[T] match
    case _: Byte   => 8
    case _: Short  => 16
    case _: Int    => 32
    case _: Long   => 64
    case _         => error("unsupported type")

  inline def nameOf[N <: String & Singleton]: String = constValue[N]

  // Inline parameters vs by-name: `inline x` is substituted textually (evaluated at
  // each use, like by-name, but with no closure allocation).
  inline def twice(inline x: Int): Int = x + x

  def run(): Unit =
    debug(s"expensive ${(1 to 1_000_000).sum}")   // compiled away (DebugEnabled = false)
    println(s"   port(8080)=${port(8080)} defaultFor: zero=$zero empty='${empty}' list=${defaultFor("list")}")
    println(s"   bitsOf[Long]=${bitsOf[Long]} bitsOf[Short]=${bitsOf[Short]} nameOf[\"orders\"]=${nameOf["orders"]}")
    var calls = 0
    def next(): Int = { calls += 1; calls }
    println(s"   inline param re-evaluates: twice(next())=${twice(next())} (calls=$calls)")
    println(s"   codeOf: ${codeOf(1 + 2 * 3)}")

// ============================================================
// SECTION 2: MACROS (quotes & splices) — reference
// ============================================================
// Macros must live in a different file/compilation unit than their callers.
//
//   // Macros.scala
//   import scala.quoted.*
//   object Macros:
//     // Public entry point: an inline def that splices in the macro implementation.
//     inline def assertPositive(inline x: Int): Int = ${ assertPositiveImpl('x) }
//
//     def assertPositiveImpl(x: Expr[Int])(using Quotes): Expr[Int] =
//       x.value match                                  // known at compile time?
//         case Some(v) if v <= 0 =>
//           quotes.reflect.report.errorAndAbort(s"expected positive literal, got $v", x)
//         case Some(_) => x                            // literal OK: no runtime check
//         case None    => '{ val v = $x; require(v > 0, s"expected positive, got $$v"); v }   // runtime check
//
//     // Expression introspection — print the source of an expression with its value:
//     inline def debugExpr[T](inline e: T): T = ${ debugExprImpl('e) }
//     def debugExprImpl[T: Type](e: Expr[T])(using Quotes): Expr[T] =
//       '{ val r = $e; println(${ Expr(e.show) } + " = " + r); r }
//
// quotes.reflect gives full access to typed trees (TASTy reflection): inspect case
// class fields, generate pattern matches, read annotations. Real uses: circe/jsoniter
// codecs, Quill/Magnum compile-time SQL, Chimney transformations, refined/iron types,
// sourcecode-style implicit metadata, test frameworks' assertion messages (MUnit).
// Staging (scala.quoted.staging.run): build and JIT-compile specialised code at runtime.

// ============================================================
// SECTION 3: JAVA INTEROP
// ============================================================
object JavaInterop:
  def run(): Unit =
    // Collections: explicit converters, no implicit magic.
    // asJava on an IMMUTABLE Scala List gives a read-only view — mutation throws.
    val javaView: java.util.List[String] = List("a", "b").asJava
    val viewMutation =
      try { javaView.add("c"); "added" }
      catch case _: UnsupportedOperationException => "UnsupportedOperationException (read-only view)"
    val javaCopy = new java.util.ArrayList[String](javaView)     // copy when Java code needs to mutate
    javaCopy.add("c")
    println(s"   asJava view add → $viewMutation; ArrayList copy → $javaCopy")
    val jmap = new java.util.HashMap[String, Int]()
    jmap.put("x", 1)
    println(s"   java → scala: ${jmap.asScala.toMap} ; scala → java: ${Map("k" -> 2).asJava.getClass.getSimpleName}")

    // Optional ↔ Option, java.time works directly
    val jopt: java.util.Optional[String] = java.util.Optional.of("v")
    println(s"   Optional.toScala=${jopt.toScala} Option.toJava=${Some(5).toJava} java.time=${java.time.LocalDate.of(2026, 10, 10).plusMonths(1)}")

    // Null from Java APIs → wrap in Option at the boundary
    val maybeEnv = Option(System.getenv("DEFINITELY_NOT_SET_12345"))
    println(s"   Option(null) from Java = $maybeEnv")

    // SAM conversion: Scala lambdas implement Java functional interfaces directly
    val r: Runnable = () => ()
    val cmp: java.util.Comparator[String] = (a, b) => a.length - b.length
    val sorted = new java.util.ArrayList[String](java.util.List.of("ccc", "a", "bb"))
    sorted.sort(cmp)
    val jfn: java.util.function.Function[Int, Int] = x => x * 10    // plain SAM conversion
    // scala.jdk.FunctionConverters' `.asJava` picks the MOST SPECIALISED Java type
    // (Int => Int becomes IntUnaryOperator, not Function) — and wildcard-importing it makes
    // `someMap.asJava` ambiguous, because a Scala Map is also a Function. Import it narrowly.
    println(s"   SAM: sorted=$sorted Function.apply=${jfn.apply(4)} runnable=${r.getClass.getSimpleName.nonEmpty}")

    // CompletableFuture ↔ Future
    val cf = java.util.concurrent.CompletableFuture.supplyAsync(() => "from Java")
    println(s"   CompletableFuture.asScala → ${Await.result(cf.asScala, 1.second)}")

    // Calling Scala from Java: @main/objects compile to static forwarders;
    // @varargs generates a Java-friendly varargs overload; @throws declares checked
    // exceptions for Java callers; @BeanProperty generates getX/setX; @static (3.x)
    // emits a real static member in a companion.
    println(s"   Scala object from Java's view: ${Interop.total(1, 2, 3)} via @varargs")

object Interop:
  @scala.annotation.varargs def total(xs: Int*): Int = xs.sum   // Java sees: int total(int... xs)
  @throws[java.io.IOException] def readConfig(path: String): String = s"config at $path"

// ============================================================
// SECTION 4: BUILD TOOLS (reference)
// ============================================================
// SCALA-CLI (the official `scala` command since 3.5): scripts, single modules,
//   prototyping, CI one-offs. Directives in source:
//     //> using scala 3.9.0
//     //> using dep com.softwaremill.ox::core:1.0.9      (:: picks the _3 artifact)
//     //> using test.dep org.scalameta::munit:1.1.1
//     //> using jvm 25
//     //> using options -deprecation -feature -Wunused:all
//   scala-cli run . | test . | package . --assembly | package --native-image | --js
//   scala-cli export --sbt / --mill  → graduate to a full build.
// SBT (most widely used for multi-module projects):
//   ThisBuild / scalaVersion := "3.9.0"
//   lazy val core = project.settings(libraryDependencies += "org.typelevel" %% "cats-core" % "2.13.0")
//   lazy val api  = project.dependsOn(core).enablePlugins(JavaAppPackaging)
//   sbt ~compile, sbt test, sbt "api/run", sbt-assembly, sbt-native-packager, sbt-scalafmt,
//   sbt-scalafix, sbt-tpolecat (strict compiler flags), sbt-revolver (hot reload)
// MILL: build.mill in Scala, fast & cacheable; growing adoption (Mill 1.x).
// Tooling: Metals (LSP for VS Code/Neovim), IntelliJ Scala plugin, scalafmt (formatter),
//   scalafix (linter/rewrites, incl. Scala 3 migration rules), Bloop (build server).

// ============================================================
// SECTION 5: TESTING (reference)
// ============================================================
// MUnit (lightweight, great diffs):
//   class PricingSuite extends munit.FunSuite:
//     test("discount over threshold"):
//       assertEquals(Pricing.discount(BigDecimal(150)), BigDecimal(15))
// ScalaTest (many styles: AnyFunSuite, AnyFlatSpec, AnyWordSpec) with matchers:
//   result should contain theSameElementsAs List(1, 2)
// ScalaCheck property-based testing:
//   property("reverse twice is identity") = forAll((xs: List[Int]) => xs.reverse.reverse == xs)
// Effect testing: munit-cats-effect, weaver-test (CE), zio-test (ZIO).
// Integration: testcontainers-scala; HTTP: sttp stubs / http4s client mocks.

// ============================================================
// SECTION 6: PLATFORMS & DATA ENGINEERING (reference)
// ============================================================
// Scala.js — compile to JavaScript (frontends with Laminar/Tyrian, shared models
//   between server and browser). Scala Native — LLVM-compiled binaries, fast startup,
//   C interop. GraalVM native-image works for JVM Scala apps too.
// Apache Spark 4.x supports Scala 2.13 (Scala 3 users call Spark via 2.13 artifacts
//   with `.cross(CrossVersion.for3Use2_13)` or use the Spark Connect client).
//   Flink dropped its Scala API (use Java API from Scala, or flink-scala-api community lib).
//   Kafka Streams has a Scala wrapper; fs2-kafka / zio-kafka for effect stacks.

// ============================================================
// SECTION 7: SCALA 2 → 3 MIGRATION (reference)
// ============================================================
// - Scala 3 consumes Scala 2.13 libraries (and vice versa via TASTy reader), so you can
//   migrate module by module.
// - Syntax: `implicit` → given/using/extension (old syntax still compiles under -source 3.x
//   with warnings); `_` wildcard imports → `*`; `=> A` stays; procedure syntax removed;
//   symbol literals removed; `do-while` removed.
// - Macros: Scala 2 macros (scala-reflect) don't run in Scala 3 — libraries rewrite them;
//   cross-building macro libraries requires two implementations.
// - Tools: `-source 3.0-migration -rewrite`, scalafix migration rules, the Scala 3
//   migration guide's incompatibility table.
// - LTS strategy: Scala 3.3 LTS → Scala 3.9 LTS (Sept 2026); libraries publish against
//   the LTS for maximum compatibility, applications can track the latest Next release.
