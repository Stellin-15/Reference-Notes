// ============================================================
// L06: Functional Programming & Functional Error Handling
// ============================================================
// WHAT: Scala 3 Book "Functional Programming" (what is FP,
//       immutable values, pure functions, functions are values,
//       functional error handling) and related references:
//       referential transparency, Option/Either/Try and their
//       combinators, for-comprehension desugaring (and the
//       Scala 3.8 "better fors", SIP-62), error ACCUMULATION
//       (validated style), recursion & folds, immutability with
//       copy/lenses, `runtimeChecked` (SIP-57, Scala 3.8), effect
//       systems explained by building a tiny IO, and the
//       ecosystem map (Cats, Cats Effect, ZIO, Kyo, Ox).
// WHY:  FP in Scala isn't about academic purity — it's about
//       errors as values (no hidden exceptions), code you can
//       reason about locally, and effects you can retry, time
//       out and compose. That's what Typelevel/ZIO stacks sell.
// LEVEL: Intermediate → Advanced
// RUN:   scala-cli run L06_functional_programming_and_errors.scala
// SOURCE: docs.scala-lang.org/scala3/book/fp-*, Scala 3 reference:
//         changed-features/better-fors (3.8), other-new-features/runtimeChecked,
//         typelevel.org/cats, typelevel.org/cats-effect, zio.dev (overview pages)
// ============================================================
/*
CONCEPT OVERVIEW:
    PURE function: output depends only on input; no side effects.
    REFERENTIAL TRANSPARENCY: an expression can be replaced by its
    value without changing the program. This makes refactoring
    and testing trivial.
    Errors as values:
      Option[A]        — present or absent (no reason)
      Either[E, A]     — Right(success) or Left(error); right-biased
      Try[A]           — Success or Failure(Throwable); wraps exception-throwing code
    These are MONADS: they have map/flatMap, so they compose with
    for-comprehensions, which short-circuit on the first failure.
    For ACCUMULATING all errors (form validation) use an
    applicative style (Validated/ValidatedNec in Cats, or the
    hand-rolled version here).

PRODUCTION USE CASE:
    Customer onboarding: validate a sign-up form collecting ALL
    errors, then run a fail-fast pipeline (KYC lookup → account
    creation → welcome email) where each step can fail, written
    with Either and then with a minimal IO effect that supports
    retry and recovery.

COMMON MISTAKES:
    1. Calling .get on Option/Try — reintroduces the exception.
    2. Mixing exceptions and Either in the same layer.
    3. Using Try for business errors (it catches everything incl.
       bugs) — prefer Either with a domain error ADT.
    4. Fail-fast Either for form validation → users fix one error
       at a time. Accumulate instead.
    5. Side effects inside map/filter on strict collections passed
       around as "pure" values.
    6. Deep recursion without @tailrec → StackOverflowError.
*/

import scala.annotation.tailrec
import scala.util.{Failure, Success, Try}

@main def lesson06(): Unit =
  println("== purity & immutability"); Purity.run()
  println("== Option / Either / Try"); ErrorTypes.run()
  println("== for-comprehensions"); ForComprehensions.run()
  println("== error accumulation"); Validation.run()
  println("== recursion & folds"); Recursion.run()
  println("== a tiny IO effect"); TinyIO.run()

// ============================================================
// SECTION 1: PURITY & IMMUTABILITY
// ============================================================
object Purity:
  // Impure: depends on and mutates hidden state.
  var counter = 0
  def nextIdImpure(): Int = { counter += 1; counter }
  // Pure: state passed in, new state returned — trivially testable & thread-safe.
  def nextIdPure(state: Int): (Int, Int) = (state + 1, state + 1)

  final case class Address(city: String, zip: String)
  final case class Customer(name: String, address: Address, tags: List[String])

  def run(): Unit =
    val (id1, s1) = nextIdPure(0); val (id2, _) = nextIdPure(s1)
    println(s"   pure ids: $id1 $id2 (same input → same output, always)")
    val c = Customer("Ada", Address("London", "N1"), List("vip"))
    // Updating nested immutable data: copy chains (lens libraries like Monocle/Quicklens help at depth)
    val moved = c.copy(address = c.address.copy(city = "Berlin", zip = "10117"), tags = "relocated" :: c.tags)
    println(s"   original untouched: ${c.address.city}; updated: ${moved.address.city} ${moved.tags}")
    // Functions are values: store them, pass them, return them (L03)
    val pipeline: List[String => String] = List(_.trim, _.toLowerCase, _.replaceAll("\\s+", "-"))
    println(s"   composed pipeline: ${pipeline.reduce(_ andThen _)("  Hello Functional World ")}")

// ============================================================
// SECTION 2: OPTION, EITHER, TRY
// ============================================================
object ErrorTypes:
  val users = Map("u1" -> "ada@example.com", "u2" -> "")

  def emailOf(id: String): Option[String] = users.get(id).filter(_.nonEmpty)
  def domain(email: String): Option[String] = email.split("@").lift(1)

  enum SignupError:
    case InvalidAge(raw: String)
    case TooYoung(age: Int)
    case Banned(email: String)

  def parseAge(raw: String): Either[SignupError, Int] =
    raw.toIntOption.toRight(SignupError.InvalidAge(raw)).filterOrElse(_ >= 18, SignupError.TooYoung(raw.toIntOption.getOrElse(0)))

  def run(): Unit =
    // Option combinators
    println(s"   ${emailOf("u1").flatMap(domain)} ${emailOf("u2").flatMap(domain)} ${emailOf("zz").map(_.length).getOrElse(0)} "
      + s"${emailOf("u1").fold("none")(_.toUpperCase)} ${emailOf("u1").exists(_.endsWith(".com"))} ${emailOf("u2").orElse(Some("fallback@x.io"))}")
    // Either combinators — right-biased: map/flatMap act on Right
    println(s"   ${parseAge("30")} ${parseAge("abc")} ${parseAge("15")} ${parseAge("30").map(_ + 1)} ${parseAge("x").left.map(_.toString.toUpperCase)}")
    println(s"   swap=${parseAge("15").swap.isRight} toOption=${parseAge("15").toOption} getOrElse=${parseAge("x").getOrElse(-1)}")
    // Try: wrap exception-throwing (often Java) code at the boundary, convert to Either
    val t = Try("12a".toInt)
    println(s"   Try: $t recover=${t.recover { case _: NumberFormatException => 0 }} toEither=${t.toEither.left.map(_.getClass.getSimpleName)}")
    t match
      case Success(v) => println(s"   value $v")
      case Failure(e) => println(s"   failure handled by pattern: ${e.getMessage}")
    // Option ↔ Either ↔ Try conversions: toRight/toLeft, toOption, toTry, Try.toEither, Either.cond

// ============================================================
// SECTION 3: FOR-COMPREHENSIONS & DESUGARING
// ============================================================
object ForComprehensions:
  final case class User(id: String, accountId: String)
  final case class Account(id: String, balance: BigDecimal)
  val userDb = Map("u1" -> User("u1", "a1"), "u2" -> User("u2", "a9"))
  val accountDb = Map("a1" -> Account("a1", 120))

  def findUser(id: String): Either[String, User] = userDb.get(id).toRight(s"no user $id")
  def findAccount(id: String): Either[String, Account] = accountDb.get(id).toRight(s"no account $id")

  def balanceAfter(userId: String, spend: BigDecimal): Either[String, BigDecimal] =
    for
      user    <- findUser(userId)              // flatMap
      account <- findAccount(user.accountId)   // flatMap
      fee      = spend * BigDecimal("0.01")    // value binding (map with a tuple)
      _       <- Either.cond(account.balance >= spend + fee, (), s"insufficient: ${account.balance} < ${spend + fee}")
    yield account.balance - spend - fee        // map
  // Desugars to:
  //   findUser(userId).flatMap(user =>
  //     findAccount(user.accountId).map(account => (account, spend * 0.01)).flatMap { case (account, fee) =>
  //       Either.cond(...).map(_ => account.balance - spend - fee) })
  // Scala 3.8 "better fors" (SIP-62, now stable): an initial `=` binding is allowed
  // without a preceding generator, and a trailing `yield x` that just returns the
  // last bound value no longer generates a redundant `map`.

  def run(): Unit =
    println(s"   ${balanceAfter("u1", 50)} ${balanceAfter("u1", 200)} ${balanceAfter("u2", 1)} ${balanceAfter("u3", 1)}")
    // Same syntax over Option, List (all combinations), Future, IO...
    val combos = for
      size  <- List("S", "M")
      color <- List("red", "blue")
      if !(size == "S" && color == "blue")
    yield s"$size-$color"
    println(s"   over List: $combos")
    val startsWithBinding = for
      base = 10                               // 3.8+: binding first
      x <- Option(base * 2)
    yield x
    println(s"   better-fors leading binding: $startsWithBinding")

// ============================================================
// SECTION 4: ERROR ACCUMULATION (validated style)
// ============================================================
object Validation:
  // A minimal "Validated": Either whose Left holds ALL errors, combined applicatively.
  type V[A] = Either[List[String], A]
  def ok[A](a: A): V[A] = Right(a)
  def err[A](e: String): V[A] = Left(List(e))

  // zip-style combination that ACCUMULATES lefts instead of short-circuiting
  def map3[A, B, C, R](va: V[A], vb: V[B], vc: V[C])(f: (A, B, C) => R): V[R] =
    (va, vb, vc) match
      case (Right(a), Right(b), Right(c)) => Right(f(a, b, c))
      case _ => Left(List(va, vb, vc).collect { case Left(es) => es }.flatten)

  final case class SignUp(email: String, age: Int, password: String)

  def validEmail(s: String): V[String] = if s.matches("""[^@\s]+@[^@\s]+\.\w+""") then ok(s.toLowerCase) else err(s"email '$s' is invalid")
  def validAge(s: String): V[Int] = s.toIntOption match
    case Some(a) if a >= 18 => ok(a)
    case Some(a)            => err(s"must be 18+, got $a")
    case None               => err(s"age '$s' is not a number")
  def validPassword(s: String): V[String] =
    val problems = List(
      Option.when(s.length < 12)("password needs 12+ chars"),
      Option.when(!s.exists(_.isDigit))("password needs a digit"),
      Option.when(!s.exists(_.isUpper))("password needs an uppercase letter"),
    ).flatten
    if problems.isEmpty then ok(s) else Left(problems)

  def validate(email: String, age: String, pw: String): V[SignUp] =
    map3(validEmail(email), validAge(age), validPassword(pw))(SignUp.apply)

  def run(): Unit =
    println(s"   ${validate("ada@example.com", "36", "CorrectHorse9Battery")}")
    validate("not-an-email", "16", "short").left.foreach(es => es.foreach(e => println(s"   ✗ $e")))
    // Cats: (validEmail(e).toValidatedNec, validAge(a).toValidatedNec, ...).mapN(SignUp.apply)

// ============================================================
// SECTION 5: RECURSION, FOLDS, runtimeChecked
// ============================================================
object Recursion:
  // Structural recursion over an ADT
  enum Tree[+A]:
    case Leaf(value: A)
    case Node(left: Tree[A], right: Tree[A])
  import Tree.*
  def sum(t: Tree[Int]): Int = t match
    case Leaf(v)    => v
    case Node(l, r) => sum(l) + sum(r)
  def fold[A, B](t: Tree[A])(leaf: A => B)(node: (B, B) => B): B = t match   // a catamorphism
    case Leaf(v)    => leaf(v)
    case Node(l, r) => node(fold(l)(leaf)(node), fold(r)(leaf)(node))

  // Tail recursion with an accumulator → compiled to a loop
  @tailrec def factorial(n: Int, acc: BigInt = 1): BigInt = if n <= 1 then acc else factorial(n - 1, acc * n)

  def run(): Unit =
    val t = Node(Node(Leaf(1), Leaf(2)), Node(Leaf(3), Node(Leaf(4), Leaf(5))))
    println(s"   sum=${sum(t)} depth=${fold(t)(_ => 1)((l, r) => 1 + l.max(r))} leaves=${fold(t)(List(_))(_ ++ _)}")
    println(s"   factorial(30)=${factorial(30)}")
    // runtimeChecked (SIP-57, stable in 3.8): say "I know this match is partial, check at runtime"
    // instead of the old `(x: @unchecked) match` — silences the exhaustivity warning explicitly.
    val first :: rest = List(1, 2, 3).runtimeChecked
    println(s"   runtimeChecked destructuring: first=$first rest=$rest")

// ============================================================
// SECTION 6: A TINY IO — what Cats Effect / ZIO are built on
// ============================================================
// An effect is a DESCRIPTION of a computation; nothing happens until run().
// Because it's a value, you can retry it, time it, race it, compose it.
object TinyIO:
  final class IO[+A] private (val unsafeRun: () => A):
    def map[B](f: A => B): IO[B] = IO.delay(f(unsafeRun()))
    def flatMap[B](f: A => IO[B]): IO[B] = IO.delay(f(unsafeRun()).unsafeRun())
    def attempt: IO[Either[Throwable, A]] = IO.delay(Try(unsafeRun()).toEither)
    def handleErrorWith[B >: A](h: Throwable => IO[B]): IO[B] = attempt.flatMap(_.fold(h, IO.pure))
    def retry(times: Int): IO[A] = if times <= 0 then this else handleErrorWith(_ => retry(times - 1))
    def timed: IO[(A, Long)] = IO.delay { val t = System.nanoTime(); val a = unsafeRun(); (a, (System.nanoTime() - t) / 1_000_000) }
  object IO:
    def delay[A](a: => A): IO[A] = IO(() => a)
    def pure[A](a: A): IO[A] = IO(() => a)
    def raise(e: Throwable): IO[Nothing] = IO(() => throw e)

  // Effectful steps of the onboarding pipeline
  var kycCalls = 0
  def kycCheck(email: String): IO[Boolean] = IO.delay {
    kycCalls += 1
    if kycCalls < 3 then throw RuntimeException(s"KYC provider 503 (call $kycCalls)")
    !email.endsWith("@blocked.io")
  }
  def createAccount(email: String): IO[String] = IO.delay(s"acct_${email.hashCode.abs % 10000}")
  def sendWelcome(account: String, log: StringBuilder): IO[Unit] = IO.delay(log.append(s"welcome sent for $account; "))

  def onboard(email: String, log: StringBuilder): IO[Either[String, String]] =
    (for
      passed  <- kycCheck(email).retry(3)              // retried as a VALUE — impossible with eager calls
      account <- if passed then createAccount(email) else IO.raise(IllegalStateException("KYC rejected"))
      _       <- sendWelcome(account, log)
    yield account).attempt.map(_.left.map(_.getMessage))

  def run(): Unit =
    val log = StringBuilder()
    val program = onboard("ada@example.com", log)   // nothing has run yet
    println(s"   described program; KYC calls so far = $kycCalls")
    val (result, ms) = program.timed.unsafeRun()
    println(s"   ran: $result after $kycCalls KYC calls (2 failures retried) in ${ms}ms; log='$log'")
    kycCalls = 2
    println(s"   blocked user: ${onboard("eve@blocked.io", log).unsafeRun()}")
    // Real effect systems add: stack safety (trampolining — this toy isn't), async &
    // fibers, cancellation, resource safety (Resource/Scope), concurrency (parTraverse,
    // race), structured error channels (ZIO[R, E, A]), dependency injection (ZLayer).
    //   Cats Effect 3: IO, Resource, Ref, Deferred, Fiber; fs2 streams; http4s, doobie, skunk.
    //   ZIO 2: ZIO[R, E, A], ZLayer, ZStream, zio-http, zio-json; typed errors in the type.
    //   Ox (direct style on JDK 21+ virtual threads): par, race, supervised scopes, channels — L07.
    //   Kyo: algebraic-effects style "pending" types.
