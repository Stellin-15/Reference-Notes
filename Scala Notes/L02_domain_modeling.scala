// ============================================================
// L02: Domain Modeling — Classes, Traits, Objects, Case
//      Classes, Enums & ADTs, OOP vs FP Modeling, Packages,
//      Imports, Export Clauses
// ============================================================
// WHAT: Scala 3 Book "Domain Modeling" (Tools, OOP Modeling, FP
//       Modeling) and "Packaging and Imports", plus reference
//       pages on enums, trait parameters, transparent/open
//       classes, creator applications, export clauses and
//       universal apply: classes & constructors, auxiliary
//       constructors, access modifiers, traits as interfaces and
//       mixins (linearization, trait parameters, self types),
//       singleton & companion objects, case classes (copy,
//       equality, unapply), case objects, enums (simple,
//       parameterized, ADTs, GADT-style), sealed hierarchies,
//       and the two modeling styles side by side.
// WHY:  Scala's superpower in business code is making illegal
//       states unrepresentable: enums/sealed traits for "one of",
//       case classes for "all of", opaque types (L04) for
//       validated primitives. The compiler then checks every
//       `match` is exhaustive.
// LEVEL: Foundation → Intermediate
// RUN:   scala-cli run L02_domain_modeling.scala
// SOURCE: docs.scala-lang.org/scala3/book/domain-modeling-*,
//         /scala3/book/packaging-imports, Scala 3 reference:
//         enums/*, other-new-features/trait-parameters, export, open-classes
// ============================================================
/*
CONCEPT OVERVIEW:
    class       — template for objects with state & behaviour.
    trait       — interface + reusable implementation; a class can
                  mix in many traits (`extends A, B, C` in Scala 3).
    object      — a singleton; a COMPANION object shares a class's
                  name and file and can access its private members
                  (factories, constants, implicit instances).
    case class  — immutable data: auto equals/hashCode/toString,
                  copy, pattern-matching extractor, no `new` needed.
    enum        — a closed set of cases; cases may carry data → an
                  algebraic data type (ADT).
    OOP modeling: data + behaviour together, dispatch via overriding.
    FP modeling: immutable data (ADTs) + functions that match on it.

PRODUCTION USE CASE:
    A payments domain: Money and Account as case classes, a
    PaymentMethod ADT, a PaymentEvent enum, an OOP-style
    notification hierarchy with mixins, and an FP-style state
    machine for payment lifecycle.

COMMON MISTAKES:
    1. Mutable fields (`var`) in case classes — breaks equality
       and hashing assumptions in Sets/Maps.
    2. Unsealed traits for closed sets → no exhaustiveness checks.
    3. Extending case classes (case-to-case inheritance is
       prohibited; regular-class inheritance from a case class is
       allowed but surprising — mark case classes `final`).
    4. Putting logic that needs validation in a public case-class
       constructor — use a smart constructor on the companion and
       a private constructor.
    5. Wildcard imports from large packages hiding name clashes.
*/

package payments                              // packages can also be nested blocks: `package a: ...`

import scala.collection.mutable               // import a package to refer to mutable.Map etc.
import java.time.{Instant, Duration as JDuration}   // selective import + rename with `as`
import scala.math.Ordering.Implicits.*        // `*` is the wildcard in Scala 3 (`_` is legacy)

// ============================================================
// SECTION 1: CLASSES, CONSTRUCTORS, ACCESS MODIFIERS
// ============================================================
class Account(val id: String, initial: BigDecimal):    // `val` param → public field; plain param → private
  private var balance: BigDecimal = initial            // private: this class + companion
  private[payments] var frozen = false                 // qualified private: visible in package `payments`

  def this(id: String) = this(id, BigDecimal(0))       // auxiliary constructor must call another first

  def deposit(amount: BigDecimal): Unit =
    require(amount > 0, s"deposit must be positive, got $amount")   // IllegalArgumentException
    balance += amount

  def withdraw(amount: BigDecimal): Either[String, BigDecimal] =
    if frozen then Left(s"$id is frozen")
    else if amount > balance then Left(s"insufficient funds in $id: ${balance} < $amount")
    else
      balance -= amount
      Right(balance)

  def currentBalance: BigDecimal = balance             // parameterless method (uniform access principle)
  override def toString = s"Account($id, $balance${if frozen then ", frozen" else ""})"

// Companion object: factories, constants; shares private access with the class.
object Account:
  private var created = 0
  def apply(id: String, initial: BigDecimal): Account = { created += 1; new Account(id, initial) }
  def count: Int = created
  def peek(a: Account): BigDecimal = a.balance        // can read the private field

// Universal apply (Scala 3): any class can be instantiated without `new`:
//   val sb = StringBuilder("x")   // calls new StringBuilder("x")
// …UNLESS its companion already defines an `apply` (then only that apply is used).

// ============================================================
// SECTION 2: TRAITS — interfaces, mixins, linearization, parameters
// ============================================================
trait Notifier:
  def channel: String                                   // abstract member
  def send(to: String, msg: String): String = s"[$channel] → $to: $msg"   // concrete, overridable

trait Retrying extends Notifier:
  abstract override def send(to: String, msg: String): String = s"retry(${super.send(to, msg)})"   // stackable modification

trait Logging extends Notifier:
  abstract override def send(to: String, msg: String): String = s"log(${super.send(to, msg)})"

class EmailNotifier extends Notifier:
  def channel = "email"

// Linearization: the RIGHTMOST trait's method runs first, calling super leftwards.
class ProdEmail extends EmailNotifier, Retrying, Logging

// Trait parameters (Scala 3): traits can take constructor arguments.
trait Branded(val brand: String):
  def signature = s"— the $brand team"
class Receipt(order: String) extends Branded("Acme Pay"):
  def body = s"Receipt for $order $signature"

// Self type: "anything mixing me in must also be a Clock" — a dependency, not inheritance.
trait Clock:
  def now: Instant
trait Expiring:
  this: Clock =>
  def expired(at: Instant): Boolean = now.isAfter(at)
class Session(val now: Instant) extends Clock, Expiring

// `open` classes (Scala 3): only classes marked `open` are intended for extension
// from other files (otherwise a feature warning). `transparent trait` hides
// helper traits from inferred types.
open class BaseFeeSchedule:
  def fee(amount: BigDecimal): BigDecimal = amount * BigDecimal("0.029") + BigDecimal("0.30")

// ============================================================
// SECTION 3: CASE CLASSES & CASE OBJECTS
// ============================================================
final case class Money(amount: BigDecimal, currency: String):
  require(currency.matches("[A-Z]{3}"), s"bad currency $currency")
  def +(other: Money): Money =
    require(other.currency == currency, "currency mismatch")
    copy(amount = amount + other.amount)
  override def toString = s"$currency ${amount.setScale(2, BigDecimal.RoundingMode.HALF_EVEN)}"

object Money:
  def usd(a: String): Money = Money(BigDecimal(a), "USD")
  given Ordering[Money] = Ordering.by(_.amount)          // a typeclass instance (L05)

// Smart constructor: private constructor + validating factory returning Either.
final case class Email private (value: String)
object Email:
  def parse(s: String): Either[String, Email] =
    val t = s.trim.toLowerCase
    if t.matches("""[^@\s]+@[^@\s]+\.[a-z]{2,}""") then Right(new Email(t)) else Left(s"invalid email: '$s'")

case object SystemUser                                   // singleton with case-class goodies (toString, pattern)

// ============================================================
// SECTION 4: ENUMS & ALGEBRAIC DATA TYPES
// ============================================================
// Simple enum
enum Currency:
  case USD, EUR, GBP

// Parameterized enum with members
enum CardNetwork(val prefixes: List[String]):
  case Visa extends CardNetwork(List("4"))
  case Mastercard extends CardNetwork(List("51", "52", "53", "54", "55", "2"))
  case Amex extends CardNetwork(List("34", "37"))
  def matches(pan: String): Boolean = prefixes.exists(pan.startsWith)

object CardNetwork:
  def detect(pan: String): Option[CardNetwork] = values.find(_.matches(pan))

// ADT: "one of" (sum) whose cases are "all of" (products).
enum PaymentMethod:
  case Card(pan: String, expMonth: Int, expYear: Int)
  case BankTransfer(iban: String)
  case Wallet(provider: String, token: String)
  case Cash

// The same ADT the "Scala 2 way" — sealed trait + case classes — still common,
// and needed when cases want their own extra methods or to extend other types.
sealed trait PaymentEvent:
  def paymentId: String
final case class Authorized(paymentId: String, amount: Money) extends PaymentEvent
final case class Captured(paymentId: String, amount: Money) extends PaymentEvent
final case class Refunded(paymentId: String, amount: Money, reason: String) extends PaymentEvent
final case class Failed(paymentId: String, code: String) extends PaymentEvent

// GADT-style enum: type parameter refined per case (typed expression trees).
enum Expr[A]:
  case Num(n: BigDecimal) extends Expr[BigDecimal]
  case Bool(b: Boolean) extends Expr[Boolean]
  case Gt(l: Expr[BigDecimal], r: Expr[BigDecimal]) extends Expr[Boolean]
  case If[T](c: Expr[Boolean], t: Expr[T], e: Expr[T]) extends Expr[T]

def eval[A](e: Expr[A]): A = e match            // the compiler knows A per case
  case Expr.Num(n)      => n
  case Expr.Bool(b)     => b
  case Expr.Gt(l, r)    => eval(l) > eval(r)
  case Expr.If(c, t, f) => if eval(c) then eval(t) else eval(f)

// ============================================================
// SECTION 5: FP MODELING — state machine as data + functions
// ============================================================
enum PaymentState:
  case Pending
  case AuthorizedState(amount: Money)
  case CapturedState(amount: Money, refunded: Money)
  case FailedState(code: String)

object PaymentLifecycle:
  import PaymentState.*
  // Pure transition function: (state, event) → new state or an error. No mutation.
  def transition(s: PaymentState, e: PaymentEvent): Either[String, PaymentState] = (s, e) match
    case (Pending, Authorized(_, amt))                       => Right(AuthorizedState(amt))
    case (Pending, Failed(_, code))                          => Right(FailedState(code))
    case (AuthorizedState(auth), Captured(_, amt)) if amt.amount <= auth.amount
                                                             => Right(CapturedState(amt, amt.copy(amount = 0)))
    case (CapturedState(cap, ref), Refunded(_, amt, _)) if (ref + amt).amount <= cap.amount
                                                             => Right(CapturedState(cap, ref + amt))
    case (state, event)                                      => Left(s"illegal: ${event.getClass.getSimpleName} in ${state}")

  def replay(events: List[PaymentEvent]): Either[String, PaymentState] =
    events.foldLeft[Either[String, PaymentState]](Right(Pending))((acc, e) => acc.flatMap(transition(_, e)))

// ============================================================
// SECTION 6: EXPORT CLAUSES — composition without boilerplate
// ============================================================
class Ledger:
  private val entries = mutable.ArrayBuffer.empty[(Instant, Money)]
  def record(m: Money): Unit = entries += (Instant.EPOCH -> m)
  def total(ccy: String): Money = entries.collect { case (_, m) if m.currency == ccy => m }.foldLeft(Money(0, ccy))(_ + _)
  def size: Int = entries.size

class Wallet2(val owner: String):
  private val ledger = Ledger()
  export ledger.{record, total}      // forwarders: Wallet2 now HAS record/total, delegating to ledger
                                     // (favour composition; `size` deliberately not exported)

// ============================================================
// SECTION 7: RUN
// ============================================================
@main def lesson02(): Unit =
  println("== classes & companions")
  val acc = Account("acc-1", BigDecimal(100))
  acc.deposit(50)
  println(s"   ${acc.withdraw(30)} ${acc.withdraw(500)} peek=${Account.peek(acc)} count=${Account.count} ${new Account("acc-2")}")
  // Account("acc-2") would NOT compile: once a companion defines its own `apply`,
  // Scala 3 stops generating universal-apply constructor proxies — use `new`.
  acc.frozen = true                                         // allowed: we're in package `payments`
  println(s"   ${acc.withdraw(1)} → $acc")
  try acc.deposit(-5) catch case e: IllegalArgumentException => println(s"   require: ${e.getMessage}")

  println("== traits")
  println(s"   linearization: ${ProdEmail().send("ada@x.io", "paid")}")
  println(s"   trait parameter: ${Receipt("ord-7").body}")
  println(s"   self type: expired=${Session(Instant.parse("2026-10-10T12:00:00Z")).expired(Instant.parse("2026-10-10T11:00:00Z"))}")

  println("== case classes")
  val a = Money.usd("19.99"); val b = a.copy(amount = BigDecimal("5.01"))
  println(s"   $a + $b = ${a + b}; equal by value: ${a == Money.usd("19.99")}; max=${List(a, b).max}; hash stable: ${a.hashCode == Money.usd("19.99").hashCode}")
  val Money(amt, ccy) = a                                    // deconstruction via unapply
  println(s"   unapply: $amt/$ccy  ${Email.parse(" Ada@Example.COM ")} ${Email.parse("nope")} $SystemUser")
  // new Email("x")  // error: constructor is private

  println("== enums & ADTs")
  println(s"   Currency.values=${Currency.values.toList} valueOf=${Currency.valueOf("EUR")} ordinal(GBP)=${Currency.GBP.ordinal}")
  println(s"   card detection: ${List("4242424242424242", "5555555555554444", "378282246310005", "6011").map(CardNetwork.detect)}")
  def describe(pm: PaymentMethod): String = pm match       // exhaustive: remove a case → compiler warning
    case PaymentMethod.Card(pan, m, y)      => s"card *${pan.takeRight(4)} exp $m/$y"
    case PaymentMethod.BankTransfer(iban)   => s"bank ${iban.take(4)}…"
    case PaymentMethod.Wallet(provider, _)  => s"wallet $provider"
    case PaymentMethod.Cash                 => "cash"
  println(s"   ${List(PaymentMethod.Card("4242424242424242", 12, 2030), PaymentMethod.Wallet("apple", "tok"), PaymentMethod.Cash).map(describe)}")
  import Expr.*
  println(s"   GADT eval: ${eval(If(Gt(Num(150), Num(100)), Num(BigDecimal("0.05")), Num(0)))} (discount rate)")

  println("== FP state machine")
  val ok = List(Authorized("p1", Money.usd("100")), Captured("p1", Money.usd("100")), Refunded("p1", Money.usd("30"), "damaged"))
  val bad = List(Authorized("p2", Money.usd("100")), Refunded("p2", Money.usd("10"), "too early"))
  println(s"   ${PaymentLifecycle.replay(ok)}")
  println(s"   ${PaymentLifecycle.replay(bad)}")

  println("== export clauses")
  val w = Wallet2("ada"); w.record(Money.usd("10")); w.record(Money.usd("2.50")); w.record(Money(BigDecimal(3), "EUR"))
  println(s"   exported total(USD)=${w.total("USD")} total(EUR)=${w.total("EUR")}")
  println(s"   java.time rename import: ${JDuration.ofMinutes(90)}")
