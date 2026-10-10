// ============================================================
// L04: The Scala 3 Type System
// ============================================================
// WHAT: Scala 3 Book "Types and the Type System" (inferred types,
//       generics, intersection types, union types, ADTs, variance,
//       opaque types, structural types, dependent function types,
//       other types) plus the Scala 3 reference on match types,
//       type lambdas, polymorphic function types, singleton and
//       literal types, kind polymorphism, explicit nulls and
//       CanEqual: upper/lower bounds, covariance/contravariance
//       with the position rules, existentials via wildcards,
//       path-dependent types, tuple types as HLists.
// WHY:  Scala's types let you encode business rules the compiler
//       enforces — validated IDs that can't be mixed up (opaque
//       types), error channels as unions, APIs that compute their
//       result type from the input (match types). Variance is the
//       thing every library author must get right.
// LEVEL: Advanced
// RUN:   scala-cli run L04_type_system.scala
// SOURCE: docs.scala-lang.org/scala3/book/types-*, Scala 3 reference:
//         new-types/* (intersection, union, type-lambdas, match-types,
//         dependent-function-types, polymorphic-function-types),
//         other-new-features/opaques, explicit-nulls, contextual/multiversal-equality
// ============================================================
/*
CONCEPT OVERVIEW:
    Scala infers local types, but method signatures (especially
    public ones) should be explicit. Generic types have VARIANCE:
      List[+A]   covariant:   List[Cat] <: List[Animal]
      Sink[-A]   contravariant: Sink[Animal] <: Sink[Cat]
      Array[A]   invariant
    Scala 3 adds first-class union (A | B) and intersection
    (A & B) types, opaque type aliases (zero-cost newtypes),
    match types (type-level pattern matching), and type lambdas
    ([X] =>> F[X]).

PRODUCTION USE CASE:
    A typed money/identity layer for a payments service: opaque
    UserId/OrderId/Cents types, a union-typed error channel,
    variance-correct event handlers, and a match-type-driven
    API returning precise result types.

COMMON MISTAKES:
    1. Declaring a mutable/consumer type covariant — the compiler
       stops you ("covariant type A occurs in contravariant
       position"); fix with a lower bound [B >: A].
    2. Using type aliases (`type UserId = String`) for safety —
       aliases are transparent; use opaque types.
    3. Letting unions widen to their LUB by accident — union
       types are inferred only when you ascribe them.
    4. Structural types (reflection-based on JVM) in hot paths.
    5. Overusing match types/type-level code where an ADT would do.
*/

import scala.compiletime.ops.int.*
import scala.reflect.Selectable.reflectiveSelectable

@main def lesson04(): Unit =
  println("== generics & bounds"); Generics.run()
  println("== variance"); Variance.run()
  println("== union & intersection"); UnionIntersection.run()
  println("== opaque types"); OpaqueDemo.run()
  println("== structural & dependent types"); Structural.run()
  println("== match types, type lambdas, singleton types"); TypeLevel.run()

// ============================================================
// SECTION 1: GENERICS & BOUNDS
// ============================================================
object Generics:
  final case class Box[A](value: A):
    def map[B](f: A => B): Box[B] = Box(f(value))

  // Upper bound: A must be a subtype of Comparable-like Ordered
  def maxOf[A <: Ordered[A]](xs: List[A]): A = xs.reduce((a, b) => if a > b then a else b)
  final case class Version(major: Int, minor: Int) extends Ordered[Version]:
    def compare(that: Version) = summon[Ordering[(Int, Int)]].compare((major, minor), (that.major, that.minor))

  // Context bound (preferred over upper bounds for typeclasses — L05)
  def largest[A: Ordering](xs: List[A]): A = xs.max

  // Lower bound: "B is a supertype of A" — used for covariant containers
  sealed trait Animal { def name: String }
  final case class Cat(name: String) extends Animal
  final case class Dog(name: String) extends Animal
  def prepend[A, B >: A](elem: B, xs: List[A]): List[B] = elem :: xs

  def run(): Unit =
    println(s"   ${Box(21).map(_ * 2)} maxOf=${maxOf(List(Version(1, 9), Version(2, 0), Version(1, 10)))} largest=${largest(List("pear", "apple"))}")
    val cats: List[Cat] = List(Cat("tom"))
    val animals = prepend(Dog("rex"), cats)          // inferred List[Animal] (well: List[Cat | Dog] widened to Animal)
    println(s"   lower bound result: $animals : List[Animal]")
    // Wildcards (existential-ish): List[?] = a list of some unknown element type
    def size(xs: List[?]): Int = xs.size
    println(s"   wildcard size(List[?])=${size(List("a", 1, true))}")

// ============================================================
// SECTION 2: VARIANCE
// ============================================================
object Variance:
  import Generics.{Animal, Cat, Dog}

  // Covariant producer: only RETURNS A
  trait Source[+A]:
    def next(): A
  // Contravariant consumer: only ACCEPTS A
  trait Handler[-A]:
    def handle(a: A): String
  // Invariant: both reads and writes A
  final class Cell[A](var value: A)

  // Covariant immutable stack: to add an element we need a lower bound,
  // because A would otherwise appear in a contravariant (parameter) position.
  sealed trait Stack[+A]:
    def push[B >: A](b: B): Stack[B] = NonEmpty(b, this)
    def toList: List[A]
  case object Empty extends Stack[Nothing] { def toList = Nil }
  final case class NonEmpty[+A](top: A, rest: Stack[A]) extends Stack[A] { def toList = top :: rest.toList }

  def run(): Unit =
    val catSource: Source[Cat] = () => Cat("felix")
    val animalSource: Source[Animal] = catSource                 // OK: covariant
    val animalHandler: Handler[Animal] = a => s"handled ${a.name}"
    val catHandler: Handler[Cat] = animalHandler                 // OK: contravariant
    println(s"   ${animalSource.next()} ${catHandler.handle(Cat("tom"))}")
    // val c: Cell[Animal] = Cell[Cat](Cat("x"))  // error: Cell is invariant (would allow writing a Dog into a Cat cell)
    val s: Stack[Cat] = Empty.push(Cat("a"))
    val widened: Stack[Animal] = s.push(Dog("b"))                // push widens to the LUB
    println(s"   covariant stack: ${widened.toList}")
    // Functions: Function1[-A, +B] — accept more, return less.
    val f: Animal => Cat = a => Cat(a.name)
    val g: Cat => Animal = f                                     // OK by variance of Function1
    println(s"   Function1 variance: ${g(Cat("z"))}")

// ============================================================
// SECTION 3: UNION & INTERSECTION TYPES
// ============================================================
object UnionIntersection:
  // Union as a lightweight error channel (no wrapper hierarchy needed)
  final case class NotFound(id: String)
  final case class Forbidden(reason: String)
  final case class RateLimited(retryAfterSec: Int)
  type ApiError = NotFound | Forbidden | RateLimited

  def fetchOrder(id: String, user: String): Either[ApiError, String] =
    if user == "guest" then Left(Forbidden("guests can't view orders"))
    else if id.startsWith("x") then Left(NotFound(id))
    else if id == "hot" then Left(RateLimited(30))
    else Right(s"order $id")

  def status(e: ApiError): Int = e match                      // exhaustive over the union
    case NotFound(_)    => 404
    case Forbidden(_)   => 403
    case RateLimited(_) => 429

  // Unions of unrelated types / literals
  def show(x: Int | String | Boolean): String = x match
    case i: Int     => s"int $i"
    case s: String  => s"str $s"
    case b: Boolean => s"bool $b"
  type HttpMethod = "GET" | "POST" | "DELETE"                  // union of LITERAL types
  def call(m: HttpMethod) = s"$m /orders"

  // Intersection: a value that is BOTH (has all members)
  trait Resettable { def reset(): String = "reset" }
  trait Growable { def grow(n: Int): String = s"grow $n" }
  def maintain(x: Resettable & Growable): String = s"${x.reset()}, ${x.grow(2)}"
  class Buffer extends Resettable, Growable

  def run(): Unit =
    for (id, u) <- List(("1", "ada"), ("x9", "ada"), ("1", "guest"), ("hot", "ada")) do
      println(s"   fetch($id,$u) → ${fetchOrder(id, u).left.map(e => s"${status(e)} $e")}")
    println(s"   ${show(1)} ${show("a")} ${show(true)} | ${call("POST")} | ${maintain(Buffer())}")
    // call("PATCH")  // error: "PATCH" is not a HttpMethod
    // Inference note: `if c then 1 else "a"` infers Matchable (the join), not Int | String,
    // unless the expected type is a union: val v: Int | String = if c then 1 else "a"

// ============================================================
// SECTION 4: OPAQUE TYPES — zero-cost newtypes
// ============================================================
object Ids:
  opaque type UserId = String                  // inside Ids: UserId == String; outside: distinct type
  object UserId:
    def apply(s: String): Either[String, UserId] =
      Either.cond(s.matches("u_[a-z0-9]{3,}"), s, s"bad user id '$s'")
    extension (id: UserId) def value: String = id

  opaque type OrderId = String
  object OrderId:
    def unsafe(s: String): OrderId = s
    extension (id: OrderId) def value: String = id

  opaque type Cents = Long
  object Cents:
    def apply(l: Long): Cents = l
    def fromDollars(d: BigDecimal): Cents = (d * 100).setScale(0, BigDecimal.RoundingMode.HALF_EVEN).toLong
    extension (c: Cents)
      def +(o: Cents): Cents = c + o
      def *(k: Int): Cents = c * k
      def show: String = f"$$${c / 100}%d.${math.abs(c % 100)}%02d"
      def toLong: Long = c

object OpaqueDemo:
  import Ids.*
  def lookup(user: UserId, order: OrderId): String = s"${user.value} → ${order.value}"

  def run(): Unit =
    val u = UserId("u_ada1")
    val bad = UserId("ADA")
    val o = OrderId.unsafe("ord_9")
    println(s"   $u $bad ${u.map(lookup(_, o))}")
    // lookup(o, u)        // error: arguments swapped — OrderId is not UserId (aliases would compile!)
    // val s: String = o   // error: OrderId is not a String outside its scope
    val total = Cents.fromDollars(BigDecimal("19.99")) * 3 + Cents(150)
    println(s"   Cents: ${total.show} (runtime representation is a plain Long: ${total.toLong})")

// ============================================================
// SECTION 5: STRUCTURAL & DEPENDENT TYPES
// ============================================================
object Structural:
  // Structural type: "anything with a close(): Unit" (uses reflection on the JVM)
  type Closeable = { def close(): Unit }
  def using[R <: Closeable, A](r: R)(f: R => A): A = try f(r) finally r.close()
  class Conn { var open = true; def close(): Unit = open = false; def query = "rows" }

  // Path-dependent types: each Registry instance has its OWN Key type
  class Registry:
    final case class Key(name: String)
    private val store = scala.collection.mutable.Map.empty[Key, String]
    def key(n: String): Key = Key(n)
    def put(k: Key, v: String): Unit = store(k) = v
    def get(k: Key): Option[String] = store.get(k)

  // Dependent function type: result type depends on the argument VALUE's member type
  trait Entry { type Value; def value: Value }
  val extract: (e: Entry) => e.Value = e => e.value

  // Polymorphic function type: a function VALUE with its own type parameter
  val firstOrNone: [A] => List[A] => Option[A] = [A] => (xs: List[A]) => xs.headOption

  def run(): Unit =
    val c = Conn()
    println(s"   structural: ${using(c)(_.query)} open after=${c.open}")
    val r1 = Registry(); val r2 = Registry()
    val k1 = r1.key("config")
    r1.put(k1, "v1")
    // r2.put(k1, "v2")   // error: found r1.Key, required r2.Key — keys can't cross registries
    println(s"   path-dependent: ${r1.get(k1)}")
    val intEntry = new Entry { type Value = Int; def value = 42 }
    val n: Int = extract(intEntry)                          // precise type Int, not Any
    println(s"   dependent function: $n  polymorphic function: ${firstOrNone(List("a", "b"))} ${firstOrNone(List.empty[Int])}")

// ============================================================
// SECTION 6: MATCH TYPES, TYPE LAMBDAS, SINGLETON/LITERAL TYPES
// ============================================================
object TypeLevel:
  // Match type: compute a type from a type
  type Elem[X] = X match
    case String      => Char
    case Array[t]    => t
    case Iterable[t] => t
    case Option[t]   => t

  def firstElem[X](x: X): Elem[X] = x match
    case s: String      => s.charAt(0)
    case a: Array[t]    => a(0)
    case i: Iterable[t] => i.head
    case o: Option[t]   => o.get

  // Type lambda: partially apply a two-parameter type constructor
  type EitherErr = [A] =>> Either[String, A]
  def pureE[A](a: A): EitherErr[A] = Right(a)

  // Singleton & literal types + compile-time arithmetic (scala.compiletime.ops)
  val three: 3 = 3
  type Five = 2 + 3                                        // computed by the compiler
  val five: Five = 5
  // val wrong: Five = 6   // error: Found 6, Required 5

  // Tuples are HLists in Scala 3: typed head/tail/concat/map on types
  val tup = (1, "a", true)
  type T = Tuple.Concat[(Int, String), Tuple1[Boolean]]   // (Int, String, Boolean)
  val same: T = tup

  // valueOf / constValue: lift a literal type to a value
  inline def sizeOf[N <: Int]: Int = scala.compiletime.constValue[N]

  def run(): Unit =
    val c: Char = firstElem("scala")
    val i: Int = firstElem(List(7, 8))
    val d: Double = firstElem(Array(1.5))
    println(s"   match types: $c $i $d ${firstElem(Some("x"))}")
    println(s"   type lambda: ${pureE(1)}  literal types: $three $five  constValue[Five]=${sizeOf[Five]}")
    println(s"   tuple ops: head=${tup.head} tail=${tup.tail} ${tup ++ (2.0, 'z')} size=${tup.size} same=$same")
    // Explicit nulls (-Yexplicit-nulls): String no longer includes null; Java APIs return String | Null.
    // Multiversal equality (`import scala.language.strictEquality`): `1 == "1"` becomes a compile error
    // unless a CanEqual instance exists (case classes can `derives CanEqual`).
