// ============================================================
// L04: The Collections Framework & the Stream API
// ============================================================
// WHAT: dev.java "The Collections Framework" and "The Stream
//       API" tutorials plus JDK 21-25 additions: the interface
//       hierarchy (Collection, List, Set, Queue, Deque, Map,
//       Sequenced*), every major implementation and its Big-O,
//       immutable vs unmodifiable views, iteration and fail-fast
//       iterators, Comparable/Comparator, Collections/Arrays
//       utilities; streams — creation, intermediate and terminal
//       ops, laziness, Collectors (grouping, partitioning,
//       teeing, toMap merge), primitive streams, Optional,
//       parallel streams, and Stream Gatherers (JEP 485, JDK 24).
// WHY:  Picking the wrong collection is the most common
//       performance bug in business code (LinkedList for random
//       access, List.contains in a loop, HashMap with mutable
//       keys). Streams are how modern Java expresses data
//       transformations — and how it hides O(n²) and
//       side-effect bugs when misused.
// LEVEL: Intermediate
// RUN:   java L04_collections_and_streams.java   (JDK 24+)
// SOURCE: dev.java/learn/api/collections-framework, /streams,
//         JEP 431 (Sequenced Collections), JEP 485 (Gatherers),
//         java.util / java.util.stream Javadoc (JDK 25)
// ============================================================
/*
CONCEPT OVERVIEW:
    Iterable
      └─ Collection
           ├─ SequencedCollection (21) ─ List: ArrayList, LinkedList, CopyOnWriteArrayList
           │                          └─ Deque: ArrayDeque, LinkedList, ConcurrentLinkedDeque
           ├─ Set: HashSet, EnumSet, CopyOnWriteArraySet
           │   └─ SequencedSet: LinkedHashSet, SortedSet → NavigableSet: TreeSet, ConcurrentSkipListSet
           └─ Queue: PriorityQueue, ArrayBlockingQueue, LinkedBlockingQueue, ...
    Map (not a Collection): HashMap, EnumMap, IdentityHashMap, WeakHashMap,
      ConcurrentHashMap │ SequencedMap: LinkedHashMap, NavigableMap: TreeMap,
      ConcurrentSkipListMap
    A Stream is a lazy pipeline: source → 0..n intermediate ops →
    exactly one terminal op. Nothing runs until the terminal op;
    a stream can be consumed only once.

PRODUCTION USE CASE:
    Order analytics: grouping orders by customer and status,
    top-N per group, revenue partitioning, an LRU cache built
    on LinkedHashMap, and windowed metrics with a Gatherer.

COMMON MISTAKES:
    1. Modifying a collection while iterating it with for-each →
       ConcurrentModificationException. Use Iterator.remove or
       removeIf.
    2. Mutable objects as HashMap keys / HashSet elements — change
       the hash-relevant field and the entry is lost.
    3. Collectors.toMap without a merge function on duplicate
       keys → IllegalStateException.
    4. List.of(...) / Map.of(...) reject nulls and are immutable —
       add() throws UnsupportedOperationException.
    5. Arrays.asList is fixed-size AND write-through to the array.
    6. parallel() as a speed button: it uses the common
       ForkJoinPool, helps only for large CPU-bound, splittable,
       stateless work, and breaks with shared mutable state.
    7. Stream.toList() (16) returns an UNMODIFIABLE list;
       Collectors.toList() returns a mutable ArrayList (unspecified).
*/

import java.util.*;
import java.util.function.BinaryOperator;
import java.util.function.Function;
import java.util.stream.*;

public class L04_collections_and_streams {

    // ========================================================
    // SECTION 1: LISTS — ArrayList vs LinkedList
    // ========================================================
    //                  get(i)   add(end)   add(0)/remove(0)  memory
    //   ArrayList       O(1)    O(1)*      O(n)              compact array
    //   LinkedList      O(n)    O(1)       O(1)              node per element (~5x)
    // (* amortised). ArrayList wins almost always — even for queues, use ArrayDeque.
    static void lists() {
        List<String> names = new ArrayList<>(List.of("ada", "linus", "grace", "barbara"));
        names.removeIf(n -> n.startsWith("l"));                // safe bulk removal
        names.replaceAll(String::toUpperCase);
        names.sort(Comparator.naturalOrder());
        IO.println("list: " + names + " subList=" + names.subList(0, 2) + " indexOf=" + names.indexOf("GRACE"));

        // Sequenced collections (JDK 21): uniform first/last/reversed API.
        IO.println("sequenced: first=" + names.getFirst() + " last=" + names.getLast() + " reversed=" + names.reversed());

        // Fail-fast iterator:
        try {
            for (String n : names) if (n.equals("ADA")) names.remove(n);
        } catch (ConcurrentModificationException e) {
            IO.println("CME: modified during for-each");
        }

        // Immutable vs unmodifiable view vs fixed-size:
        List<Integer> immutable = List.of(1, 2, 3);                    // truly immutable, null-hostile
        List<Integer> backing = new ArrayList<>(immutable);
        List<Integer> view = Collections.unmodifiableList(backing);     // read-only VIEW: sees backing changes
        backing.add(4);
        Integer[] arr = {1, 2};
        List<Integer> fixed = Arrays.asList(arr);                       // fixed-size, write-through
        fixed.set(0, 99);
        IO.println("view sees backing change: " + view + ", asList wrote through: arr[0]=" + arr[0]);
        try { immutable.add(4); } catch (UnsupportedOperationException e) { IO.println("List.of is immutable"); }
    }

    // ========================================================
    // SECTION 2: SETS
    // ========================================================
    //   HashSet       O(1) add/contains, no order
    //   LinkedHashSet O(1), insertion order (SequencedSet)
    //   TreeSet       O(log n), sorted, NavigableSet (floor/ceiling/headSet...)
    //   EnumSet       bit-vector, fastest for enums
    static void sets() {
        var tree = new TreeSet<>(List.of(50, 10, 40, 20, 30));
        IO.println("TreeSet: " + tree + " floor(35)=" + tree.floor(35) + " ceiling(35)=" + tree.ceiling(35)
                + " headSet(30)=" + tree.headSet(30) + " descending=" + tree.descendingSet());
        var linked = new LinkedHashSet<>(List.of("c", "a", "b", "a"));
        linked.addFirst("z");                                   // JDK 21 SequencedSet
        IO.println("LinkedHashSet keeps order, dedups: " + linked);
        Set<String> a = new HashSet<>(Set.of("x", "y", "z")), b = Set.of("y", "z", "w");
        var inter = new HashSet<>(a); inter.retainAll(b);
        var union = new HashSet<>(a); union.addAll(b);
        var diff = new HashSet<>(a); diff.removeAll(b);
        IO.println("set algebra: ∩=" + new TreeSet<>(inter) + " ∪=" + new TreeSet<>(union) + " −=" + diff);

        // The mutable-key bug:
        record Key(List<String> parts) {}
        var parts = new ArrayList<>(List.of("a"));
        var set = new HashSet<Key>(); set.add(new Key(parts));
        parts.add("b");                                         // hashCode of the key changes
        IO.println("mutable key lost: contains=" + set.contains(new Key(parts)) + " size=" + set.size());
    }

    // ========================================================
    // SECTION 3: QUEUES & DEQUES
    // ========================================================
    // Method pairs: throws vs returns special value
    //   add/offer   remove/poll   element/peek
    static void queues() {
        Deque<Integer> stack = new ArrayDeque<>();          // use instead of legacy Stack (synchronized)
        stack.push(1); stack.push(2); stack.push(3);
        IO.println("stack pop=" + stack.pop() + " peek=" + stack.peek());

        Queue<String> fifo = new ArrayDeque<>(List.of("first", "second"));
        IO.println("queue poll=" + fifo.poll() + " poll=" + fifo.poll() + " poll(empty)=" + fifo.poll());

        // PriorityQueue: binary heap; poll is O(log n); iteration order is NOT sorted.
        record Job(String name, int priority) {}
        var pq = new PriorityQueue<>(Comparator.comparingInt(Job::priority).reversed());
        pq.addAll(List.of(new Job("email", 1), new Job("payment", 10), new Job("report", 5)));
        var order = new ArrayList<String>();
        while (!pq.isEmpty()) order.add(pq.poll().name());
        IO.println("priority order: " + order);
        // Concurrent queues (BlockingQueue, ConcurrentLinkedQueue) → L06.
    }

    // ========================================================
    // SECTION 4: MAPS
    // ========================================================
    //   HashMap        O(1); buckets become red-black trees past 8 collisions (Java 8)
    //   LinkedHashMap  insertion or ACCESS order (→ LRU caches)
    //   TreeMap        O(log n), sorted, NavigableMap
    //   EnumMap        array-backed for enum keys
    //   IdentityHashMap  == instead of equals (graph algorithms, serializers)
    //   WeakHashMap    entries vanish when keys are GC'd (caches keyed by objects)
    static void maps() {
        Map<String, Integer> wordCount = new HashMap<>();
        for (String w : "the quick the lazy the end".split(" ")) wordCount.merge(w, 1, Integer::sum);
        IO.println("merge counts: " + new TreeMap<>(wordCount));

        Map<String, List<String>> index = new HashMap<>();
        index.computeIfAbsent("j", k -> new ArrayList<>()).add("java");
        index.computeIfAbsent("j", k -> new ArrayList<>()).add("jvm");
        index.putIfAbsent("k", new ArrayList<>(List.of("kotlin")));
        index.computeIfPresent("k", (k, v) -> v.isEmpty() ? null : v);   // returning null removes
        IO.println("multimap: " + new TreeMap<>(index) + " getOrDefault=" + index.getOrDefault("z", List.of()));

        var prices = new TreeMap<>(Map.of(100, "basic", 500, "pro", 2000, "enterprise"));
        IO.println("tier for 750: " + prices.floorEntry(750).getValue() + ", tiers ≥ 500: " + prices.tailMap(500, true).values());

        // Iterate entries, not keys+get:
        for (var e : prices.entrySet()) if (e.getKey() > 1000) IO.println("entry: " + e.getKey() + "=" + e.getValue());
        // Map.of supports up to 10 pairs; Map.ofEntries(Map.entry(k, v), ...) for more.
        // SequencedMap (21): firstEntry(), lastEntry(), pollFirstEntry(), putFirst(), reversed().
    }

    // LRU cache in 8 lines — LinkedHashMap in ACCESS order + removeEldestEntry.
    static final class LruCache<K, V> extends LinkedHashMap<K, V> {
        private final int capacity;
        LruCache(int capacity) { super(16, 0.75f, true); this.capacity = capacity; }
        @Override protected boolean removeEldestEntry(Map.Entry<K, V> eldest) { return size() > capacity; }
    }

    // ========================================================
    // SECTION 5: STREAMS — CREATION, INTERMEDIATE, TERMINAL
    // ========================================================
    // Sources:  coll.stream(), Arrays.stream(arr), Stream.of(...),
    //           Stream.iterate(seed, hasNext, next), Stream.generate(s),
    //           IntStream.range/rangeClosed, Files.lines(path), str.chars(),
    //           Pattern.splitAsStream, random.ints(), map.entrySet().stream()
    // Intermediate (lazy): filter, map, flatMap, mapMulti (16), distinct,
    //           sorted, peek, limit, skip, takeWhile, dropWhile (9), gather (24)
    // Terminal: forEach, collect, toList (16), reduce, count, min, max,
    //           anyMatch/allMatch/noneMatch, findFirst/findAny, toArray, iterator
    static void streamBasics() {
        // Laziness: watch the per-element order of operations.
        var trace = new ArrayList<String>();
        var result = Stream.of("a", "bb", "ccc", "dddd")
                .filter(s -> { trace.add("filter " + s); return s.length() > 1; })
                .map(s -> { trace.add("map " + s); return s.toUpperCase(); })
                .findFirst();                                   // short-circuits after "bb"
        IO.println("lazy: " + result.orElseThrow() + " trace=" + trace);

        IO.println("iterate: " + Stream.iterate(1, x -> x < 200, x -> x * 3).toList()
                + " takeWhile: " + IntStream.of(2, 4, 6, 7, 8).takeWhile(x -> x % 2 == 0).boxed().toList());
        IO.println("flatMap: " + Stream.of(List.of(1, 2), List.of(3)).flatMap(List::stream).toList()
                + " mapMulti: " + Stream.of(1, 2, 3).<Integer>mapMulti((x, sink) -> { if (x != 2) { sink.accept(x); sink.accept(-x); } }).toList());
        int sumSquares = IntStream.rangeClosed(1, 10).map(x -> x * x).sum();
        var stats = IntStream.of(4, 8, 15, 16, 23, 42).summaryStatistics();
        IO.println("primitive: sum of squares=" + sumSquares + " stats=" + stats);
        IO.println("reduce: " + Stream.of(1, 2, 3, 4).reduce(0, Integer::sum) + " joined: "
                + Stream.of("x", "y", "z").collect(Collectors.joining(", ", "[", "]")));
        try {
            Stream<String> s = Stream.of("once");
            s.count();
            s.count();
        } catch (IllegalStateException e) {
            IO.println("reuse: " + e.getMessage());
        }
    }

    // ========================================================
    // SECTION 6: COLLECTORS
    // ========================================================
    enum Status { NEW, PAID, SHIPPED, CANCELLED }
    record Order(String id, String customer, Status status, long cents, List<String> skus) {}

    static final List<Order> ORDERS = List.of(
            new Order("o1", "acme", Status.PAID, 12_000, List.of("A", "B")),
            new Order("o2", "acme", Status.SHIPPED, 4_500, List.of("C")),
            new Order("o3", "globex", Status.PAID, 99_000, List.of("A")),
            new Order("o4", "initech", Status.CANCELLED, 3_000, List.of("D")),
            new Order("o5", "globex", Status.NEW, 7_000, List.of("B", "C", "D")),
            new Order("o6", "acme", Status.PAID, 1_500, List.of("A")));

    static void collectors() {
        // groupingBy with a downstream collector
        Map<String, Long> revenueByCustomer = ORDERS.stream()
                .filter(o -> o.status() != Status.CANCELLED)
                .collect(Collectors.groupingBy(Order::customer, TreeMap::new, Collectors.summingLong(Order::cents)));
        IO.println("revenue by customer: " + revenueByCustomer);

        Map<Status, List<String>> idsByStatus = ORDERS.stream().collect(
                Collectors.groupingBy(Order::status, () -> new EnumMap<>(Status.class),
                        Collectors.mapping(Order::id, Collectors.toList())));
        IO.println("ids by status: " + idsByStatus);

        Map<Boolean, Long> bigVsSmall = ORDERS.stream().collect(Collectors.partitioningBy(o -> o.cents() >= 10_000, Collectors.counting()));
        IO.println("partition ≥$100: " + bigVsSmall);

        // toMap — duplicates need a merge function; pick map type with the 4-arg form.
        Map<String, Order> largestPerCustomer = ORDERS.stream().collect(Collectors.toMap(
                Order::customer, Function.identity(),
                BinaryOperator.maxBy(Comparator.comparingLong(Order::cents)), TreeMap::new));
        IO.println("largest per customer: " + largestPerCustomer.values().stream().map(Order::id).toList());

        // flatMapping + toCollection for distinct sorted SKUs per customer
        Map<String, TreeSet<String>> skus = ORDERS.stream().collect(Collectors.groupingBy(Order::customer, TreeMap::new,
                Collectors.flatMapping(o -> o.skus().stream(), Collectors.toCollection(TreeSet::new))));
        IO.println("skus per customer: " + skus);

        // teeing (12): two collectors, then combine.
        var avg = ORDERS.stream().collect(Collectors.teeing(
                Collectors.summingLong(Order::cents), Collectors.counting(), (sum, n) -> sum / n));
        IO.println("teeing average cents: " + avg);

        // Top-N per group
        Map<String, List<String>> top2 = ORDERS.stream().collect(Collectors.groupingBy(Order::customer, TreeMap::new,
                Collectors.collectingAndThen(Collectors.toList(), l -> l.stream()
                        .sorted(Comparator.comparingLong(Order::cents).reversed()).limit(2).map(Order::id).toList())));
        IO.println("top-2 orders per customer: " + top2);
    }

    // ========================================================
    // SECTION 7: OPTIONAL
    // ========================================================
    // Optional is for RETURN types that may be absent. Not for fields,
    // parameters, or collections (return an empty collection instead).
    static Optional<Order> findOrder(String id) { return ORDERS.stream().filter(o -> o.id().equals(id)).findFirst(); }
    static void optionals() {
        String status = findOrder("o3").map(Order::status).map(Enum::name).orElse("UNKNOWN");
        String missing = findOrder("zz").map(Order::customer).orElseGet(() -> "fallback-" + System.nanoTime() % 1);
        IO.println("optional: " + status + " " + missing + " present=" + findOrder("o1").isPresent()
                + " stream=" + Stream.of("o1", "zz", "o2").map(L04_collections_and_streams::findOrder).flatMap(Optional::stream).map(Order::id).toList());
        // orElseThrow() (10) — the honest replacement for get().
        // Avoid: if (opt.isPresent()) opt.get() — use map/ifPresentOrElse/orElse.
    }

    // ========================================================
    // SECTION 8: PARALLEL STREAMS
    // ========================================================
    // Worth it when: N large (≥ 10k-100k), per-element work CPU-heavy,
    // source splits well (ArrayList, arrays, IntStream.range — NOT
    // LinkedList or Stream.iterate), ops stateless and associative.
    // Runs on ForkJoinPool.commonPool() (size = cores - 1) shared JVM-wide.
    static void parallel() {
        long seq = LongStream.rangeClosed(1, 2_000_000).filter(L04_collections_and_streams::isPrime).count();
        long par = LongStream.rangeClosed(1, 2_000_000).parallel().filter(L04_collections_and_streams::isPrime).count();
        IO.println("primes ≤ 2M: sequential=" + seq + " parallel=" + par);
        // WRONG — race on a shared ArrayList:
        //   var out = new ArrayList<Long>(); stream.parallel().forEach(out::add);
        // RIGHT — let the collector combine: stream.parallel().boxed().toList()
        // forEachOrdered preserves encounter order (at a cost); findAny beats findFirst in parallel.
    }
    static boolean isPrime(long n) {
        if (n < 2) return false;
        for (long d = 2; d * d <= n; d++) if (n % d == 0) return false;
        return true;
    }

    // ========================================================
    // SECTION 9: STREAM GATHERERS (JDK 24, JEP 485)
    // ========================================================
    // gather(Gatherer) = a user-definable INTERMEDIATE op (as Collector is
    // for terminal ops). Built-ins in java.util.stream.Gatherers:
    //   windowFixed(n), windowSliding(n), fold(init, f), scan(init, f),
    //   mapConcurrent(maxConcurrency, f) — runs f on virtual threads, keeps order.
    static void gatherers() {
        IO.println("windowFixed: " + Stream.of(1, 2, 3, 4, 5).gather(Gatherers.windowFixed(2)).toList());
        IO.println("windowSliding: " + Stream.of(1, 2, 3, 4).gather(Gatherers.windowSliding(3)).toList());
        IO.println("scan (running total): " + Stream.of(5, 10, 20).gather(Gatherers.scan(() -> 0, Integer::sum)).toList());

        // Moving average of latency samples — sliding window + map.
        var latencies = List.of(120, 80, 300, 90, 110, 95);
        IO.println("3-sample moving avg: " + latencies.stream().gather(Gatherers.windowSliding(3))
                .map(w -> w.stream().mapToInt(Integer::intValue).average().orElse(0)).map(d -> Math.round(d)).toList());

        // A custom gatherer: emit only elements that differ from the previous one
        // (like `uniq`). Integrator gets (state, element, downstream).
        Gatherer<String, ?, String> dedupConsecutive = Gatherer.ofSequential(
                () -> new Object() { String last; },
                (state, element, downstream) -> {
                    if (!element.equals(state.last)) { state.last = element; return downstream.push(element); }
                    return true;                                    // keep going
                });
        IO.println("custom uniq: " + Stream.of("a", "a", "b", "b", "b", "a", "c").gather(dedupConsecutive).toList());

        // mapConcurrent — I/O fan-out with bounded concurrency, order preserved.
        IO.println("mapConcurrent: " + Stream.of("o1", "o3", "o5").gather(Gatherers.mapConcurrent(2,
                id -> { try { Thread.sleep(20); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
                        return id + ":" + findOrder(id).map(Order::status).orElseThrow(); })).toList());
    }

    public static void main(String[] args) {
        IO.println("== lists"); lists();
        IO.println("== sets"); sets();
        IO.println("== queues"); queues();
        IO.println("== maps"); maps();
        var lru = new LruCache<String, Integer>(2);
        lru.put("a", 1); lru.put("b", 2); lru.get("a"); lru.put("c", 3);     // "b" is least-recently used
        IO.println("LRU after access(a), put(c): " + lru.keySet());
        IO.println("== stream basics"); streamBasics();
        IO.println("== collectors"); collectors();
        IO.println("== optional"); optionals();
        IO.println("== parallel"); parallel();
        IO.println("== gatherers"); gatherers();
    }
}
