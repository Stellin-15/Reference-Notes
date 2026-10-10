// ============================================================
// L03: Functions & the Collections Library
// ============================================================
// WHAT: Scala 3 Book "Functions" (anonymous functions, function
//       variables, eta-expansion, higher-order functions, writing
//       map/filter yourself, functions returning functions,
//       partial functions) and "Scala Collections" (collection
//       types, collection methods), plus the Collections Overview
//       guide: the immutable/mutable hierarchy (Seq/IndexedSeq/
//       LinearSeq, Set, Map), List vs Vector vs ArrayBuffer vs
//       Array performance, LazyList, views, iterators, builders,
//       and the ~100 operations grouped by purpose (transform,
//       filter, fold, group, sort, zip, slide, partition...).
// WHY:  Idiomatic Scala is pipelines of collection operations
//       over immutable data. Choosing List where you need
//       indexing, or materialising huge intermediate collections,
//       is the common performance mistake; partial functions and
//       collect are the common readability win.
// LEVEL: Intermediate
// RUN:   scala-cli run L03_functions_and_collections.scala
// SOURCE: docs.scala-lang.org/scala3/book/fun-*, /scala3/book/collections-*,
//         docs.scala-lang.org/overviews/collections-2.13/* (performance
//         characteristics, views, arrays, strings, equality)
// ============================================================
/*
CONCEPT OVERVIEW:
    A function value has a type like `Int => Int` (sugar for
    Function1[Int, Int]). Methods (def) convert to functions
    automatically (eta-expansion). Higher-order functions take or
    return functions.
    Collections: scala.collection.immutable is the default (List,
    Vector, Map, Set are imported automatically); mutable versions
    live in scala.collection.mutable. Strict collections compute
    eagerly; LazyList and views compute on demand.

PRODUCTION USE CASE:
    Clickstream analytics: sessionising events per user,
    computing funnels and top-N pages, sliding-window rates,
    and building lookup indexes — all with immutable pipelines.

COMMON MISTAKES:
    1. list(i) or list.length in a loop — List is a linked list
       (O(n) indexing). Use Vector or IndexedSeq.
    2. `list :+ x` repeatedly (O(n) append) — prepend with :: and
       reverse, or use a builder/ArrayBuffer/Vector.
    3. Long chains over huge data creating intermediate collections
       — use .view (or .iterator) then materialise once.
    4. mapValues/filterKeys returning lazy views (2.13+): results
       recomputed on every access — call .toMap when needed.
    5. groupBy then mapValues(_.size) instead of groupMapReduce.
    6. Comparing Array with == (reference equality). Use sameElements
       or convert to Seq.
*/

import scala.collection.mutable
import scala.collection.immutable.{SortedMap, TreeSet}

@main def lesson03(): Unit =
  println("== functions"); functions()
  println("== collection types"); collectionTypes()
  println("== operations"); operations()
  println("== laziness: views, LazyList, iterators"); laziness()
  println("== end-to-end: clickstream analytics"); Clickstream.run()

// ============================================================
// SECTION 1: FUNCTIONS
// ============================================================
def functions(): Unit =
  val double = (i: Int) => i * 2                       // anonymous function
  val add: (Int, Int) => Int = _ + _                   // placeholder syntax: each _ is the next param
  val greet: String => String = name => s"hi $name"
  println(s"   ${double(21)} ${add(2, 3)} ${greet("ada")} ${List(1, 2, 3).map(_ * 10)}")

  // Higher-order functions: functions as parameters...
  def applyTwice(f: Int => Int, x: Int): Int = f(f(x))
  // ...and as results (closures capture surrounding values)
  def multiplier(k: Int): Int => Int = x => x * k
  val triple = multiplier(3)
  println(s"   applyTwice(double, 5)=${applyTwice(double, 5)} triple(7)=${triple(7)}")

  // Composition
  val inc: Int => Int = _ + 1
  println(s"   (inc andThen double)(3)=${(inc andThen double)(3)} (inc compose double)(3)=${(inc compose double)(3)}")

  // Currying & partial application
  def fee(rate: BigDecimal)(fixed: BigDecimal)(amount: BigDecimal) = amount * rate + fixed
  val stripeLike = fee(BigDecimal("0.029"))(BigDecimal("0.30"))
  println(s"   curried fee on 100 = ${stripeLike(100)}")
  val curriedAdd = add.curried
  println(s"   add.curried(1)(2)=${curriedAdd(1)(2)} tupled=${add.tupled((4, 5))}")

  // Writing your own map/filter — what the library does conceptually
  def myMap[A, B](xs: List[A])(f: A => B): List[B] = xs match
    case Nil => Nil
    case h :: t => f(h) :: myMap(t)(f)
  def myFilter[A](xs: List[A])(p: A => Boolean): List[A] =
    xs.foldRight(List.empty[A])((x, acc) => if p(x) then x :: acc else acc)
  println(s"   myMap=${myMap(List(1, 2, 3))(_ + 1)} myFilter=${myFilter((1 to 10).toList)(_ % 3 == 0)}")

  // Partial functions: defined only for some inputs; `collect` = filter + map in one
  val parseCents: PartialFunction[String, Long] =
    case s if s.matches("""\d+\.\d{2}""") => s.replace(".", "").toLong
  val raw = List("12.50", "abc", "3.00", "7")
  println(s"   collect with PF: ${raw.collect(parseCents)} isDefinedAt(abc)=${parseCents.isDefinedAt("abc")} "
    + s"lift=${raw.map(parseCents.lift)}")
  val orElse = parseCents.orElse { case s if s.forall(_.isDigit) => s.toLong * 100 }
  println(s"   orElse chain: ${raw.collect(orElse)}")

  // By-name parameters (=> A): evaluated each time they're used (lazy, repeatable)
  def logIf(enabled: Boolean)(msg: => String): Unit = if enabled then println(s"   log: $msg")
  logIf(false)({ println("   (never computed)"); "x" })
  logIf(true)("computed only when enabled")

// ============================================================
// SECTION 2: COLLECTION TYPES & PERFORMANCE
// ============================================================
//              head  tail  apply(i)  update  prepend  append  insert
// List         C     C     L         L       C        L       -
// Vector       eC    eC    eC        eC      eC       eC      -
// ArraySeq     C     L     C         L       L        L       -     (immutable wrapper over Array)
// ArrayBuffer  C     L     C         C       L        aC      L     (mutable)
// ListBuffer   C     L     L         L       C        C       L     (mutable)
// Array        C     L     C         C       -        -       -     (JVM array, mutable, fixed size)
// C=constant, eC=effectively constant (log32 n), aC=amortised constant, L=linear
// HashMap/HashSet: eC lookup/add/remove; TreeMap/TreeSet: log n, sorted.
def collectionTypes(): Unit =
  val list = List(3, 1, 2)                              // immutable singly-linked list
  val consed = 0 :: list                                // O(1) prepend
  val vec = Vector(1, 2, 3) :+ 4                        // efficient append/update
  val updated = vec.updated(0, 99)                      // returns a NEW vector; vec unchanged
  println(s"   list=$list 0::list=$consed vec=$vec updated=$updated original=$vec")

  val set = Set("b", "a", "b")
  val sortedSet = TreeSet(5, 1, 3)
  val map = Map("AAPL" -> 231.5, "MSFT" -> 512.25)
  val sortedMap = SortedMap("b" -> 2, "a" -> 1)
  println(s"   set=$set treeSet=$sortedSet map(AAPL)=${map("AAPL")} get(X)=${map.get("X")} getOrElse=${map.getOrElse("X", 0.0)} sortedMap=$sortedMap")
  println(s"   map + (NVDA -> 180) = ${map + ("NVDA" -> 180.0)}   map - MSFT = ${map - "MSFT"}")

  // Mutable collections — keep them local, expose immutable results
  val buf = mutable.ArrayBuffer(1, 2)
  buf += 3; buf ++= List(4, 5); buf.remove(0)
  val counts = mutable.Map.empty[String, Int].withDefaultValue(0)
  for w <- "to be or not to be".split(" ") do counts(w) += 1
  println(s"   ArrayBuffer=$buf counts=${counts.toList.sortBy(_._1)} → immutable=${buf.toVector}")

  // Arrays: JVM arrays, mutable, == is reference equality
  val arr = Array(1, 2, 3)
  println(s"   Array == Array: ${arr == Array(1, 2, 3)}, sameElements: ${arr.sameElements(Array(1, 2, 3))}, toSeq ==: ${arr.toSeq == Seq(1, 2, 3)}")

  // Tuples (Scala 3: tuples of any arity, with generic operations)
  val t = ("AAPL", 100, 231.5)
  println(s"   tuple _1=${t._1} size=${t.size} toList=${t.toList} t(1)=${t(1)} ++ ${t ++ ("USD", true)}")

  // Ranges and strings are collections too
  println(s"   range sum=${(1 to 100).sum}  string ops: ${"scala".map(_.toUpper)} ${"hello world".filter(_ != 'o')} ${"abc".zipWithIndex}")

// ============================================================
// SECTION 3: OPERATIONS BY PURPOSE
// ============================================================
def operations(): Unit =
  val xs = List(5, 3, 8, 1, 9, 2, 7)
  // transform
  println(s"   map=${xs.map(_ * 2)} flatMap=${List("a b", "c").flatMap(_.split(" "))} collect=${xs.collect { case x if x > 5 => x * 100 }}")
  // filter & search
  println(s"   filter=${xs.filter(_ % 2 == 1)} filterNot=${xs.filterNot(_ > 4)} find=${xs.find(_ > 6)} exists=${xs.exists(_ > 8)} forall=${xs.forall(_ > 0)} count=${xs.count(_ > 4)}")
  // take/drop/slice/span
  println(s"   take=${xs.take(3)} drop=${xs.drop(5)} takeWhile=${xs.takeWhile(_ > 2)} span=${xs.span(_ > 2)} splitAt=${xs.splitAt(2)} slice=${xs.slice(1, 4)}")
  // fold & reduce
  println(s"   sum=${xs.sum} product=${xs.product} max=${xs.max} foldLeft(-)=${xs.foldLeft(0)(_ - _)} foldRight(-)=${xs.foldRight(0)(_ - _)} reduce=${xs.reduce(_ max _)} scanLeft=${xs.scanLeft(0)(_ + _)}")
  // sorting
  case class P(name: String, age: Int)
  val people = List(P("Cy", 30), P("Al", 25), P("Bo", 30))
  println(s"   sorted=${xs.sorted} sortWith(>)=${xs.sortWith(_ > _)} sortBy(age,name)=${people.sortBy(p => (p.age, p.name)).map(_.name)} maxBy=${people.maxBy(_.age).name}")
  // grouping
  println(s"   groupBy=${people.groupBy(_.age).view.mapValues(_.map(_.name)).toMap} partition=${xs.partition(_ > 4)}")
  println(s"   groupMapReduce(word→count)=${"a b a c b a".split(" ").toList.groupMapReduce(identity)(_ => 1)(_ + _)}")
  // zipping, sliding, grouped
  println(s"   zip=${List("a", "b").zip(List(1, 2, 3))} zipWithIndex=${List("x", "y").zipWithIndex} unzip=${List(("a", 1), ("b", 2)).unzip}")
  println(s"   sliding(3)=${xs.sliding(3).toList.take(3)} grouped(3)=${xs.grouped(3).toList}")
  // set-like & misc
  println(s"   distinct=${List(1, 1, 2).distinct} distinctBy=${people.distinctBy(_.age).map(_.name)} diff=${xs.diff(List(1, 2))} intersect=${xs.intersect(List(1, 2, 99))} mkString=${xs.mkString("[", "|", "]")}")
  // Converting
  println(s"   toSet=${xs.toSet.size} toMap=${List("a" -> 1).toMap} toVector=${xs.toVector.getClass.getSimpleName} to(TreeSet)=${xs.to(TreeSet)}")

// ============================================================
// SECTION 4: LAZINESS — views, LazyList, iterators
// ============================================================
def laziness(): Unit =
  var evaluated = 0
  val firstBig = (1 to 1_000_000).view.map { x => evaluated += 1; x * x }.filter(_ > 50).head
  println(s"   view: first square > 50 = $firstBig after evaluating only $evaluated elements")

  // LazyList: lazily evaluated, memoised, possibly infinite
  // A LOCAL self-referential definition must be a `lazy val` (a plain local val
  // can't reference itself: "forward reference extends over the definition").
  lazy val fibs: LazyList[BigInt] = BigInt(0) #:: BigInt(1) #:: fibs.zip(fibs.tail).map(_ + _)
  println(s"   LazyList fibs.take(12)=${fibs.take(12).toList} fibs(90)=${fibs(90)}")
  val primes = LazyList.from(2).filter(n => (2 to math.sqrt(n).toInt).forall(n % _ != 0))
  println(s"   first 10 primes=${primes.take(10).toList}")

  // Iterators: single-pass, constant memory (e.g. reading a file line by line)
  val it = Iterator.iterate(1)(_ * 2).takeWhile(_ < 1000)
  println(s"   Iterator.iterate powers of 2 < 1000: ${it.toList}")
  // Iterator.unfold — generate from state:
  val countdown = Iterator.unfold(5)(n => if n == 0 then None else Some((n, n - 1)))
  println(s"   unfold: ${countdown.mkString(",")}")

// ============================================================
// SECTION 5: END-TO-END — CLICKSTREAM ANALYTICS
// ============================================================
object Clickstream:
  final case class Event(user: String, ts: Long, page: String)

  val events: Vector[Event] = Vector(
    Event("u1", 0, "/home"), Event("u1", 30, "/product/1"), Event("u1", 70, "/cart"), Event("u1", 90, "/checkout"),
    Event("u1", 4000, "/home"),                                   // new session (gap > 30 min)
    Event("u2", 10, "/home"), Event("u2", 50, "/product/2"), Event("u2", 2000, "/product/1"),
    Event("u3", 5, "/product/1"), Event("u3", 20, "/cart"),
  )

  val SessionGap = 1800L   // seconds

  // Sessionise: per user, split the time-ordered events whenever the gap exceeds 30 min.
  def sessions(es: Seq[Event]): Map[String, List[List[Event]]] =
    es.groupBy(_.user).view.mapValues { userEvents =>
      userEvents.sortBy(_.ts).foldLeft(List.empty[List[Event]]) {
        case (current :: done, e) if e.ts - current.head.ts <= SessionGap => (e :: current) :: done
        case (acc, e)                                                    => List(e) :: acc
      }.map(_.reverse).reverse
    }.toMap

  val Funnel = List("/home", "/product", "/cart", "/checkout")

  // How far down the funnel did each session get? (steps must occur in order)
  def funnelDepth(session: List[Event]): Int =
    Funnel.foldLeft((0, session.map(_.page))) { case ((depth, remaining), step) =>
      remaining.dropWhile(!_.startsWith(step)) match
        case _ :: rest if depth == Funnel.indexOf(step) => (depth + 1, rest)
        case _                                          => (depth, remaining)
    }._1

  def run(): Unit =
    val bySession = sessions(events)
    val allSessions = bySession.values.flatten.toList
    println(s"   sessions per user: ${bySession.view.mapValues(_.size).toList.sorted}")
    val depthCounts = allSessions.map(funnelDepth).groupMapReduce(identity)(_ => 1)(_ + _)
    Funnel.indices.foreach { i =>
      val reached = depthCounts.collect { case (d, n) if d > i => n }.sum
      println(f"   funnel ${Funnel(i)}%-10s reached by $reached%d / ${allSessions.size}%d sessions")
    }
    val topPages = events.groupMapReduce(_.page)(_ => 1)(_ + _).toList.sortBy((p, n) => (-n, p)).take(3)
    println(s"   top pages: $topPages")
    // Average time-on-page: diff between consecutive events within a session
    val dwell = allSessions.flatMap(s => s.zip(s.drop(1)).map((a, b) => a.page -> (b.ts - a.ts)))
    val avgDwell = dwell.groupMap(_._1)(_._2).view.mapValues(ts => ts.sum.toDouble / ts.size).toList.sortBy(_._1)
    println(s"   avg dwell (s): ${avgDwell.map((p, d) => f"$p=$d%.0f").mkString(", ")}")
