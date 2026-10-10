// ============================================================
// L07: Concurrency — Futures & Promises, ExecutionContexts,
//      Virtual Threads, Direct-Style Concurrency with Ox,
//      and the Effect/Actor Ecosystem
// ============================================================
// WHAT: Scala 3 Book "Concurrency" (Futures), the "Futures and
//       Promises" overview guide (callbacks, combinators,
//       recover/fallbackTo, Promise completion, blocking,
//       ExecutionContext choice), JDK 21+ virtual threads from
//       Scala, the Ox library (SoftwareMill) for structured,
//       direct-style concurrency (par, race, supervised scopes,
//       timeouts, retries, channels), and an architecture map of
//       Cats Effect fibers, ZIO fibers and Pekko (Akka) actors.
// WHY:  Scala has three concurrency cultures: Futures (stdlib,
//       eager), effect systems (lazy IO with fibers), and actors.
//       Since JDK 21, virtual threads made a fourth — plain
//       blocking-style code that scales — and Ox is the Scala
//       library built on it. Knowing which a codebase uses (and
//       why) is the first question on any Scala backend team.
// LEVEL: Advanced
// RUN:   scala-cli run L07_concurrency.scala   (downloads Ox from Maven Central; JDK 21+)
// SOURCE: docs.scala-lang.org/scala3/book/concurrency,
//         docs.scala-lang.org/overviews/core/futures.html,
//         ox.softwaremill.com, typelevel.org/cats-effect/docs/concepts,
//         zio.dev/reference/fiber, pekko.apache.org/docs
// ============================================================
//> using dep com.softwaremill.ox::core:1.0.9
/*
CONCEPT OVERVIEW:
    Future[A]: a value that will be available later; EAGER (starts
    on creation), memoised, runs on an ExecutionContext (a thread
    pool). Composed with map/flatMap/for, failures propagate.
    Promise[A]: the writable side — complete it once; its .future
    is the readable side (bridges callback APIs).
    Virtual threads: JVM threads that cost ~1 KB; blocking unmounts
    them. Ox wraps them in STRUCTURED scopes: forks can't outlive
    their scope, an error cancels siblings — like Java's
    StructuredTaskScope (Java L06) with a Scala API.

PRODUCTION USE CASE:
    A quote aggregator: query three pricing providers in parallel,
    take the fastest healthy answer with a timeout, retry a flaky
    provider, and stream results through a channel — first with
    Futures, then in Ox direct style.

COMMON MISTAKES:
    1. Blocking inside a Future on the global EC without `blocking {}`
       → pool starvation (global EC has #cores threads).
    2. Await.result in the middle of code — only at the program edge
       (main, tests).
    3. Assuming a Future is lazy/re-runnable: `val f = Future(x)`
       already started; you can't "retry" a Future value.
    4. Fire-and-forget Futures whose failures nobody observes.
    5. Shared mutable state accessed from callbacks without
       synchronisation (use Atomic*, or confine state).
    6. Mixing effect systems (Cats Effect IO + ZIO + Futures) in one
       service — pick one runtime per service.
*/

import scala.concurrent.{Await, ExecutionContext, Future, Promise, blocking}
import scala.concurrent.duration.*
import scala.util.{Failure, Random, Success}
import java.util.concurrent.{Executors, atomic}

@main def lesson07(): Unit =
  println("== Futures"); FuturesDemo.run()
  println("== Promises & callbacks"); PromisesDemo.run()
  println("== ExecutionContexts & virtual threads"); ExecutionContexts.run()
  println("== Ox: direct-style structured concurrency"); OxDemo.run()

object Providers:
  // Simulated pricing providers with latency and failure behaviour.
  val calls = atomic.AtomicInteger(0)
  def quote(provider: String, latencyMs: Int, failTimes: Int = 0): BigDecimal =
    val n = calls.incrementAndGet()
    Thread.sleep(latencyMs)
    if failTimes > 0 && n <= failTimes then throw RuntimeException(s"$provider 503")
    BigDecimal(100) + provider.length

// ============================================================
// SECTION 1: FUTURES
// ============================================================
object FuturesDemo:
  given ExecutionContext = ExecutionContext.global      // fork-join pool sized to #cores

  def fetch(provider: String, latencyMs: Int): Future[BigDecimal] =
    Future(blocking(Providers.quote(provider, latencyMs)))   // `blocking` lets the global pool add threads

  def run(): Unit =
    val t0 = System.nanoTime()
    // Start all three BEFORE combining → they run concurrently.
    val fa = fetch("alpha", 120); val fb = fetch("beta", 80); val fc = fetch("gamma", 100)
    val best: Future[BigDecimal] = for a <- fa; b <- fb; c <- fc yield List(a, b, c).min
    println(s"   best quote ${Await.result(best, 2.seconds)} in ~${(System.nanoTime() - t0) / 1_000_000 / 10 * 10}ms (concurrent ≈ max latency)")
    // Anti-pattern: `for a <- fetch(...); b <- fetch(...)` starts b only after a finishes (sequential).

    // Combinators
    val all = Future.sequence(List(fetch("a", 10), fetch("bb", 10)))
    val traversed = Future.traverse(List("x", "yy", "zzz"))(p => fetch(p, 5))
    val fastest = Future.firstCompletedOf(List(fetch("slow", 200), fetch("fast", 20)))
    println(s"   sequence=${Await.result(all, 1.second)} traverse=${Await.result(traversed, 1.second)} firstCompletedOf=${Await.result(fastest, 1.second)}")

    // Failure handling
    val failing: Future[BigDecimal] = Future.failed(RuntimeException("provider down"))
    val recovered = failing.recover { case e: RuntimeException => BigDecimal(-1) }
    val fallback = failing.fallbackTo(Future.successful(BigDecimal(99)))
    val transformed = failing.transform {
      case Success(v) => Success(s"ok $v")
      case Failure(e) => Success(s"degraded: ${e.getMessage}")
    }
    println(s"   recover=${Await.result(recovered, 1.second)} fallbackTo=${Await.result(fallback, 1.second)} transform=${Await.result(transformed, 1.second)}")
    // Futures are eager & memoised: retry needs a FUNCTION that creates a new Future.
    def retry[A](times: Int)(mk: () => Future[A]): Future[A] = mk().recoverWith { case _ if times > 0 => retry(times - 1)(mk) }
    Providers.calls.set(0)
    val flaky = retry(3)(() => Future(Providers.quote("flaky", 5, failTimes = 2)))
    println(s"   retry with a thunk: ${Await.result(flaky, 1.second)} after ${Providers.calls.get} calls")

// ============================================================
// SECTION 2: PROMISES & CALLBACK BRIDGES
// ============================================================
object PromisesDemo:
  given ExecutionContext = ExecutionContext.global

  // A callback-style API (like many Java SDKs)
  def legacyFetch(id: String, onSuccess: String => Unit, onError: Throwable => Unit): Unit =
    val t = Thread(() => if id.nonEmpty then onSuccess(s"payload-$id") else onError(IllegalArgumentException("empty id")))
    t.start()

  def fetchF(id: String): Future[String] =
    val p = Promise[String]()
    legacyFetch(id, p.success, p.failure)            // complete exactly once
    p.future

  // Timeout as a race between the work and a promise completed by a scheduler.
  private val scheduler = Executors.newSingleThreadScheduledExecutor()
  def withTimeout[A](f: Future[A], d: FiniteDuration): Future[A] =
    val p = Promise[A]()
    scheduler.schedule((() => p.tryFailure(java.util.concurrent.TimeoutException(s"after $d"))): Runnable, d.toMillis, java.util.concurrent.TimeUnit.MILLISECONDS)
    f.onComplete(p.tryComplete)                      // whichever completes first wins
    p.future

  def run(): Unit =
    println(s"   bridged: ${Await.result(fetchF("42"), 1.second)} / ${Await.ready(fetchF(""), 1.second).value}")
    val slow = Future(blocking { Thread.sleep(300); "late" })
    println(s"   timeout race: ${Await.ready(withTimeout(slow, 50.millis), 1.second).value}")
    fetchF("cb").onComplete {                          // callbacks: run later on the EC; don't block in them
      case Success(v) => println(s"   onComplete callback got $v")
      case Failure(e) => println(s"   failed $e")
    }
    Thread.sleep(100)
    scheduler.shutdown()

// ============================================================
// SECTION 3: EXECUTION CONTEXTS & VIRTUAL THREADS
// ============================================================
object ExecutionContexts:
  def run(): Unit =
    // A virtual-thread-per-task ExecutionContext: blocking is cheap, no `blocking {}` needed.
    val vexec = Executors.newVirtualThreadPerTaskExecutor()
    given ExecutionContext = ExecutionContext.fromExecutorService(vexec)
    val t0 = System.nanoTime()
    val many = Future.traverse((1 to 10_000).toList)(i => Future { Thread.sleep(50); i })
    val total = Await.result(many, 10.seconds).sum
    println(s"   10k blocking Futures on virtual threads: sum=$total in ~${(System.nanoTime() - t0) / 1_000_000 / 100 * 100}ms")
    vexec.shutdown()
    // Choosing an EC: global (CPU-bound, short tasks); dedicated bounded pool for
    // blocking JDBC (size = connection pool); virtual threads for I/O fan-out (JDK 21+);
    // ExecutionContext.parasitic for trivial callbacks (runs on the completing thread).

// ============================================================
// SECTION 4: OX — DIRECT-STYLE, STRUCTURED CONCURRENCY
// ============================================================
object OxDemo:
  import ox.*
  import ox.channels.*
  import ox.resilience.*
  import ox.scheduling.*

  def run(): Unit =
    // par: run in parallel, wait for all; any failure cancels the rest and is rethrown.
    val t0 = System.nanoTime()
    val (a, b, c) = par(Providers.quote("alpha", 120), Providers.quote("beta", 80), Providers.quote("gamma", 100))
    println(s"   par: min=${List(a, b, c).min} in ~${(System.nanoTime() - t0) / 1_000_000 / 10 * 10}ms — plain blocking calls, no Future types")

    // race: first successful result wins, losers are interrupted.
    println(s"   race: ${raceSuccess(Providers.quote("slow-replica", 300), Providers.quote("fast-replica", 30))}")

    // timeout + retry policies on direct-style code
    // (also Schedule.fixedInterval(100.millis), Schedule.exponentialBackoff(100.millis).maxAttempts(5))
    Providers.calls.set(0)
    val retried = retry(Schedule.immediate.maxRetries(3))(Providers.quote("flaky", 5, failTimes = 2))
    println(s"   retry: $retried after ${Providers.calls.get} calls")
    val timedOut = timeoutOption(50.millis)(Providers.quote("hung", 500))
    println(s"   timeoutOption: $timedOut")

    // supervised scope: forks can't outlive it; an exception in any fork cancels siblings.
    val results = supervised {
      val f1 = fork(Providers.quote("p1", 40))
      val f2 = fork(Providers.quote("p22", 20))
      (f1.join(), f2.join())
    }
    println(s"   supervised forks: $results")
    try
      supervised {
        forkUser { Thread.sleep(500); println("   (never printed — cancelled)") }
        fork { Thread.sleep(20); throw IllegalStateException("provider p3 crashed") }.join()
      }
    catch case e: IllegalStateException => println(s"   supervised failure cancelled siblings: ${e.getMessage}")

    // Channels (Go-style) + structured producers/consumers
    val prices = supervised {
      val ch = Channel.buffered[BigDecimal](4)
      forkDiscard {
        for p <- List("a", "bb", "ccc", "dddd") do ch.send(Providers.quote(p, 5))
        ch.done()                                          // close the channel
      }
      Iterator.continually(ch.receiveOrClosed()).takeWhile(_ != ChannelClosed.Done).collect { case p: BigDecimal => p }.toList
    }
    println(s"   channel received: $prices")
    // Ox also offers Flows (reactive-streams-like, backpressured), rate limiters,
    // circuit breakers, and `either` blocks with `.ok()` for direct-style error handling.

// ============================================================
// SECTION 5: THE ECOSYSTEM MAP (reference)
// ============================================================
// CATS EFFECT 3 (Typelevel):
//   IO[A] lazy effect; fibers (green threads on a work-stealing runtime);
//   IO.parMapN / parTraverse, IO.race, .timeout, Resource for safe acquire/release,
//   Ref/Deferred/Queue/Semaphore; ecosystem: fs2 (streams), http4s, doobie/skunk (SQL),
//   circe (JSON), log4cats, otel4s.
//     val program: IO[BigDecimal] = (fetchA, fetchB).parMapN(_ min _).timeout(2.seconds)
// ZIO 2:
//   ZIO[R, E, A] — environment, typed error, result; fibers; ZLayer dependency
//   injection; ZStream; Schedule-based retries; zio-http, zio-json, Quill (SQL).
//     ZIO.foreachPar(providers)(fetch).withParallelism(4).timeoutFail(Timeout)(2.seconds)
// PEKKO (Apache fork of Akka 2.6, after Akka's 2022 license change):
//   actors (typed Behaviors), cluster sharding, persistence (event sourcing),
//   Pekko Streams (backpressured graphs), Pekko HTTP. Akka itself continues under BSL.
// Rule of thumb (2026): new services choose ONE of — Ox/direct style on virtual threads
// (simplest, Java-like), Cats Effect (Typelevel stack), or ZIO (batteries included);
// Futures remain for interop and libraries; actors for stateful distributed workloads.
