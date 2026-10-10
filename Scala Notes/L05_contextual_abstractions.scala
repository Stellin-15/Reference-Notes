// ============================================================
// L05: Contextual Abstractions — given/using, Type Classes,
//      Extension Methods, Context Bounds, Derivation, Given
//      Imports, Multiversal Equality, Implicit Conversions
// ============================================================
// WHAT: Scala 3 Book "Contextual Abstractions" (extension
//       methods, context parameters, context bounds, given
//       imports, type classes, multiversal equality, implicit
//       conversions) and the reference on given instances,
//       using clauses, context functions, by-name context
//       parameters, type class derivation (`derives`), and the
//       Scala 3.6+ syntax for named/aggregate context bounds
//       and deferred givens.
// WHY:  Scala 2's `implicit` did five unrelated jobs and was the
//       language's most-criticised feature. Scala 3 split it into
//       explicit, purpose-specific constructs. Type classes are
//       how Scala libraries (Cats, Circe, ZIO JSON, Doobie, Tapir)
//       achieve ad-hoc polymorphism without inheritance.
// LEVEL: Advanced
// RUN:   scala-cli run L05_contextual_abstractions.scala
// SOURCE: docs.scala-lang.org/scala3/book/ca-*, Scala 3 reference:
//         contextual/* (givens, using-clauses, context-bounds,
//         extension-methods, type-classes, derivation, conversions,
//         multiversal-equality, context-functions, deferred-givens)
// ============================================================
/*
CONCEPT OVERVIEW:
    given      — DEFINE a canonical value for a type (an instance).
    using      — DECLARE a parameter the compiler fills in from
                 givens in scope (context parameter).
    summon[T]  — fetch the given T in scope.
    A TYPE CLASS is a trait with a type parameter (Show[A],
    Encoder[A], Monoid[A]) plus given instances per type; functions
    require it via `using` or a context bound `[A: Show]`.
    Resolution: the compiler searches lexical scope, explicit
    `given` imports, then the IMPLICIT SCOPE of the involved types
    (their companion objects) — which is where instances belong.

PRODUCTION USE CASE:
    A mini JSON encoder library with type-class derivation for
    case classes and enums, a request-context passed implicitly
    through service calls, and a Monoid-based metrics aggregator.

COMMON MISTAKES:
    1. Putting given instances in random objects so callers must
       import them; put them in the companion of the type or of
       the type class (found automatically).
    2. Ambiguous givens (two instances of the same type in scope).
    3. Overusing implicit conversions — they hide behaviour;
       Scala 3 requires `import scala.language.implicitConversions`
       at the use site for a reason.
    4. Context parameters for things that aren't context (pass
       ordinary arguments when it's actual data).
    5. Forgetting `import x.given` — `import x.*` does NOT import givens.
*/

import scala.deriving.Mirror
import scala.compiletime.{erasedValue, summonFrom, constValueTuple}

@main def lesson05(): Unit =
  println("== extension methods"); Extensions.run()
  println("== given / using / summon"); GivensDemo.run()
  println("== type classes & context bounds"); TypeClasses.run()
  println("== derivation"); Derivation.run()
  println("== equality, conversions, context functions"); Misc.run()

// ============================================================
// SECTION 1: EXTENSION METHODS
// ============================================================
object Extensions:
  extension (s: String)
    def toSnakeCase: String = s.replaceAll("([a-z0-9])([A-Z])", "$1_$2").toLowerCase
    def masked(visible: Int = 4): String = "*" * (s.length - visible) + s.takeRight(visible)

  // Generic extensions, and extensions with their own using clauses
  extension [A](xs: List[A])
    def second: Option[A] = xs.drop(1).headOption
    def sumBy[B](f: A => B)(using n: Numeric[B]): B = xs.map(f).sum

  // Operators as extensions
  final case class Vec(x: Double, y: Double)
  extension (a: Vec)
    def +(b: Vec): Vec = Vec(a.x + b.x, a.y + b.y)
    infix def dot(b: Vec): Double = a.x * b.x + a.y * b.y     // `infix` allows `a dot b`

  def run(): Unit =
    println(s"   ${"orderCreatedAt".toSnakeCase} ${"4242424242424242".masked()} ${List(1, 2, 3).second} ${List("ab", "cde").sumBy(_.length)}")
    println(s"   ${Vec(1, 2) + Vec(3, 4)} dot=${Vec(1, 2) dot Vec(3, 4)}")

// ============================================================
// SECTION 2: GIVEN / USING / SUMMON
// ============================================================
object GivensDemo:
  final case class RequestContext(requestId: String, user: String, locale: String)
  final case class Config(currency: String, taxRate: BigDecimal)

  // Context parameters thread "ambient" values through a call chain without
  // cluttering every signature with explicit arguments.
  def price(amount: BigDecimal)(using cfg: Config): BigDecimal = amount * (1 + cfg.taxRate)
  def audit(msg: String)(using ctx: RequestContext): String = s"[${ctx.requestId} ${ctx.user}] $msg"
  def checkout(amount: BigDecimal)(using RequestContext, Config): String =   // anonymous using params
    val total = price(amount)                                                 // Config passed along implicitly
    audit(s"charged ${summon[Config].currency} $total")                     // summon to access an anonymous one

  def run(): Unit =
    given Config = Config("EUR", BigDecimal("0.20"))                          // anonymous given
    given ctx: RequestContext = RequestContext("req-7f", "ada", "de-DE")      // named given
    println(s"   ${checkout(100)}")
    // Explicitly pass a using argument when you need to override:
    println(s"   ${checkout(100)(using ctx, Config("USD", 0))}")

// ============================================================
// SECTION 3: TYPE CLASSES & CONTEXT BOUNDS
// ============================================================
trait Show[A]:
  extension (a: A) def show: String

object Show:
  // Instances in the TYPE CLASS companion are found automatically (implicit scope).
  given Show[Int] with
    extension (a: Int) def show = s"Int($a)"
  given Show[String] with
    extension (a: String) def show = s"\"$a\""
  given [A: Show]: Show[List[A]] with                             // conditional instance: List[A] if A has one
    extension (as: List[A]) def show = as.map(_.show).mkString("[", ", ", "]")
  given [A: Show, B: Show]: Show[(A, B)] with
    extension (p: (A, B)) def show = s"(${p._1.show}, ${p._2.show})"

trait Monoid[A]:
  def empty: A
  def combine(x: A, y: A): A

object Monoid:
  def apply[A](using m: Monoid[A]): Monoid[A] = m                 // "summoner" convention: Monoid[Int].empty
  given Monoid[Int] with { def empty = 0; def combine(x: Int, y: Int) = x + y }
  given Monoid[String] with { def empty = ""; def combine(x: String, y: String) = x + y }
  given [K, V: Monoid]: Monoid[Map[K, V]] with
    def empty = Map.empty
    def combine(x: Map[K, V], y: Map[K, V]) =
      y.foldLeft(x) { case (acc, (k, v)) => acc.updated(k, acc.get(k).fold(v)(Monoid[V].combine(_, v))) }

object TypeClasses:
  // Context bound `A: Show` ≡ (using Show[A])
  def describe[A: Show](a: A): String = s"value ${a.show}"
  def combineAll[A: Monoid](xs: List[A]): A = xs.foldLeft(Monoid[A].empty)(Monoid[A].combine)

  // Scala 3.6+ (SIP-64): NAMED context bounds with `as`…
  def total[A: Monoid as m](xs: List[A]): A = xs.foldLeft(m.empty)(m.combine)
  // …and AGGREGATE bounds in braces (names go inside: {Monoid as m, Show}).
  def report[A: {Show, Monoid as m}](xs: List[A]): String =
    s"${xs.size} items, total ${total(xs).show}, identity ${m.empty.show}"

  // Local instance overrides (lexical scope wins over implicit scope)
  def run(): Unit =
    println(s"   ${describe(42)} ${describe(List("a", "b"))} ${describe(List((1, "x")))}")
    val perHost = List(Map("api" -> 3, "web" -> 1), Map("api" -> 2, "db" -> 7))
    println(s"   Monoid[Map] merge: ${combineAll(perHost)}  Monoid[String]: ${combineAll(List("a", "b", "c"))}")
    println(s"   aggregate bound: ${report(List(1, 2, 3))}")
    locally:
      given Monoid[Int] with { def empty = 1; def combine(x: Int, y: Int) = x * y }   // product instead of sum
      println(s"   local given shadows companion: product=${combineAll(List(2, 3, 4))}")

// ============================================================
// SECTION 4: TYPE CLASS DERIVATION (`derives`) with Mirrors
// ============================================================
// A tiny JSON encoder that can be DERIVED for any case class or enum.
trait Encoder[A]:
  def encode(a: A): String

object Encoder:
  given Encoder[Int] = _.toString
  given Encoder[Long] = _.toString
  given Encoder[Double] = _.toString
  given Encoder[Boolean] = _.toString
  given Encoder[String] = s => "\"" + s.replace("\"", "\\\"") + "\""
  given Encoder[BigDecimal] = _.toString
  given [A: Encoder]: Encoder[List[A]] = xs => xs.map(summon[Encoder[A]].encode).mkString("[", ",", "]")
  given [A: Encoder]: Encoder[Option[A]] = _.fold("null")(summon[Encoder[A]].encode)

  // Use an existing given if there is one; otherwise derive one recursively
  // (needed for enum cases, which don't carry their own `derives` clause).
  inline def summonOrDerive[T]: Encoder[T] = summonFrom {
    case e: Encoder[T]   => e
    case m: Mirror.Of[T] => derived[T](using m)
  }

  // Summon an encoder for each element type of a tuple of types (compile-time loop).
  inline def summonAll[T <: Tuple]: List[Encoder[?]] = inline erasedValue[T] match
    case _: EmptyTuple => Nil
    case _: (t *: ts)  => summonOrDerive[t] :: summonAll[ts]

  // `derived` is what `derives Encoder` calls. Mirror describes the type's shape.
  inline def derived[A](using m: Mirror.Of[A]): Encoder[A] =
    val elemEncoders = summonAll[m.MirroredElemTypes]
    val labels = constValueTuple[m.MirroredElemLabels].toList.map(_.toString)
    inline m match
      case p: Mirror.ProductOf[A] => (a: A) =>
        val fields = a.asInstanceOf[Product].productIterator.toList
        labels.zip(fields).zip(elemEncoders).map { case ((l, v), enc) => s"\"$l\":${enc.asInstanceOf[Encoder[Any]].encode(v)}" }.mkString("{", ",", "}")
      case s: Mirror.SumOf[A] => (a: A) =>
        val idx = s.ordinal(a)
        s"{\"type\":\"${labels(idx)}\",\"value\":${elemEncoders(idx).asInstanceOf[Encoder[Any]].encode(a)}}"

extension [A](a: A)(using enc: Encoder[A]) def toJson: String = enc.encode(a)

object Derivation:
  final case class LineItem(sku: String, qty: Int, price: BigDecimal) derives Encoder
  final case class Order(id: String, items: List[LineItem], note: Option[String], paid: Boolean) derives Encoder
  enum Payment derives Encoder:
    case Card(last4: String)
    case Bank(iban: String)

  def run(): Unit =
    val order = Order("o-1", List(LineItem("A", 2, BigDecimal("9.99")), LineItem("B", 1, BigDecimal(25))), None, paid = true)
    println(s"   ${order.toJson}")
    println(s"   ${(Payment.Card("4242"): Payment).toJson}")
    // Built-in derivable type classes: CanEqual; libraries provide derivation for
    // Circe/ZIO JSON codecs, Cats Eq/Show/Order, Tapir schemas, Doobie Read/Write.

// ============================================================
// SECTION 5: EQUALITY, CONVERSIONS, CONTEXT FUNCTIONS, GIVEN IMPORTS
// ============================================================
object Misc:
  // Multiversal equality: opt in to forbid comparing unrelated types.
  final case class UserId(v: String) derives CanEqual
  final case class OrderId(v: String) derives CanEqual
  def strictCompare(): String =
    import scala.language.strictEquality
    val u = UserId("1")
    // u == OrderId("1")   // error under strictEquality: Values of types UserId and OrderId cannot be compared
    s"strict: ${u == UserId("1")}"

  // Implicit conversions: defined as a given Conversion; use sites need the language import.
  final case class Cents(value: Long)
  given Conversion[Int, Cents] = i => Cents(i.toLong * 100)
  def charge(c: Cents): String = s"charging ${c.value}c"

  // Context functions: a function type whose parameter is a CONTEXT parameter.
  // Great for builder DSLs and transactional scopes.
  final class Transaction(val id: Int) { val log = scala.collection.mutable.ListBuffer.empty[String] }
  type Transactional[A] = Transaction ?=> A
  def inTransaction[A](body: Transactional[A]): (A, List[String]) =
    given tx: Transaction = Transaction(1)
    val r = body                                        // body receives the given Transaction implicitly
    (r, tx.log.toList)
  def write(row: String): Transactional[Unit] = summon[Transaction].log += s"INSERT $row"

  // Given imports: `import x.*` brings members, `import x.given` brings givens.
  object Instances:
    given Ordering[Cents] = Ordering.by(_.value)
    val helper = "plain member"

  def run(): Unit =
    println(s"   ${strictCompare()}")
    import scala.language.implicitConversions
    println(s"   conversion: ${charge(5)}")
    val (result, log) = inTransaction { write("a"); write("b"); "committed" }
    println(s"   context function: $result $log")
    import Instances.given                               // only the givens
    import Instances.helper
    println(s"   given import: ${List(Cents(300), Cents(100)).sorted} $helper")
