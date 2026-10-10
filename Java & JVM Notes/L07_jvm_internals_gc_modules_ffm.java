// ============================================================
// L07: JVM Internals — Class Loading, Bytecode, JIT, Memory &
//      Garbage Collection, Diagnostics, Modules (JPMS),
//      Reflection & MethodHandles, Foreign Function & Memory API
// ============================================================
// WHAT: The JVM Specification's architecture chapters and the
//       dev.java "JVM", "Modules", "Reflection" and "FFM"
//       material: class loading/linking/initialization, the
//       class-loader hierarchy, bytecode & `javap`, interpreter
//       → C1 → C2 tiered JIT, escape analysis, run-time data
//       areas, object layout (compact object headers, JDK 25),
//       G1 / ZGC / Shenandoah / Parallel / Serial / Epsilon,
//       JFR + jcmd + jstat, Project Leyden AOT cache (JDK 24-26),
//       JPMS modules, jlink/jpackage, reflection, MethodHandles,
//       and calling C from Java with the FFM API (final JDK 22).
// WHY:  Latency spikes, OOMs, slow startup, and "works in IDE,
//       fails in container" are JVM problems, not Java-language
//       problems. Senior Java engineers read GC logs, take heap
//       dumps, profile with JFR, and choose the right collector
//       and heap settings for containers.
// LEVEL: Advanced → Architect
// RUN:   java --enable-native-access=ALL-UNNAMED L07_jvm_internals_gc_modules_ffm.java
// SOURCE: JVMS 25, dev.java/learn/jvm, /modules, /reflection,
//         JEPs 439/474 (ZGC gen), 490, 483, 514, 515, 516, 519,
//         521, 523 (G1 default everywhere, JDK 27), 534, 454 (FFM)
// ============================================================
/*
CONCEPT OVERVIEW:
    .java → javac → .class (bytecode, constant pool, metadata)
          → ClassLoader loads → verify/prepare/resolve (linking)
          → <clinit> (initialization) → interpreter
          → hot methods compiled by C1 (fast, light opts) then
            C2 (aggressive, profile-guided) → deopt if assumptions break
    Run-time data areas:
      Heap (objects; GC-managed), Metaspace (class metadata, native
      memory), per-thread JVM stack (frames: locals + operand stack),
      PC register, native method stack, code cache (JIT output).
    GC is generational in practice: most objects die young.

PRODUCTION USE CASE:
    Sizing and diagnosing a containerised order service: pick a
    collector for the latency SLO, set heap as % of container
    memory, enable JFR continuously, use an AOT cache for fast
    startup, ship a jlink'd minimal runtime, and call a native
    hashing library through FFM instead of JNI.

COMMON MISTAKES:
    1. Setting -Xmx equal to the container limit — native memory
       (metaspace, thread stacks, direct buffers, code cache) pushes
       the process over → OOMKilled. Use -XX:MaxRAMPercentage=70-75.
    2. Calling System.gc() / tuning dozens of flags by cargo cult.
       Pick a collector, set heap + pause goal, measure.
    3. Ignoring Metaspace leaks from class loaders (hot redeploys,
       dynamic proxies) — "OutOfMemoryError: Metaspace".
    4. Benchmarking without warmup — you measure the interpreter.
       Use JMH.
    5. Reflection into JDK internals: strong encapsulation (JDK 16-17)
       blocks it; --add-opens is a smell, not a fix.
    6. Using sun.misc.Unsafe memory access — warned on since JDK 24
       (JEP 498); migrate to VarHandle / FFM MemorySegment.
*/

import java.lang.foreign.*;
import java.lang.invoke.MethodHandle;
import java.lang.invoke.MethodHandles;
import java.lang.invoke.MethodType;
import java.lang.invoke.VarHandle;
import java.lang.management.*;
import java.lang.reflect.*;
import java.util.*;

public class L07_jvm_internals_gc_modules_ffm {

    // ========================================================
    // SECTION 1: CLASS LOADING
    // ========================================================
    // Hierarchy (JDK 9+):
    //   Bootstrap (native; java.base etc.) ← Platform (java.sql, java.xml...)
    //     ← System/Application (classpath / module path) ← custom loaders
    // PARENT-DELEGATION: a loader asks its parent first, so core classes
    // can't be spoofed. A class's identity = (name, defining loader):
    // the same class loaded by two loaders = two distinct types
    // (ClassCastException "Foo cannot be cast to Foo").
    // Phases: Loading → Linking (verify bytecode, prepare statics,
    // resolve symbolic refs, lazily) → Initialization (<clinit>, once,
    // thread-safe, on first active use).
    static void classLoading() {
        IO.println("   String loader: " + String.class.getClassLoader() + " (null = bootstrap)");
        IO.println("   java.sql loader: " + loaderName(java.sql.Connection.class));
        IO.println("   this class loader: " + loaderName(L07_jvm_internals_gc_modules_ffm.class)
                + " (source-launcher in-memory loader) → parent " + loaderName(L07_jvm_internals_gc_modules_ffm.class.getClassLoader().getParent()));
        // Frameworks (Tomcat, OSGi, Spring Boot fat jars) use custom loaders for
        // isolation and hot reload; leaks occur when something outside holds a
        // reference to a class from a discarded loader (ThreadLocals, JDBC drivers).
    }
    static String loaderName(Object o) {
        ClassLoader cl = o instanceof Class<?> c ? c.getClassLoader() : (ClassLoader) o;
        return cl == null ? "bootstrap" : (cl.getName() == null ? "(unnamed)" : cl.getName()) + "/" + cl.getClass().getSimpleName();
    }

    // ========================================================
    // SECTION 2: BYTECODE & javap
    // ========================================================
    // `javap -c -v Foo.class` shows the bytecode. For:
    //   static int add(int a, int b) { return a + b; }
    // you get a stack-machine program:
    //   iload_0     // push a
    //   iload_1     // push b
    //   iadd        // pop 2, push sum
    //   ireturn
    // Invocation opcodes: invokestatic, invokevirtual (class dispatch),
    // invokeinterface, invokespecial (ctors/private/super), invokedynamic
    // (lambdas, string concatenation since 9, pattern-switch bootstraps).
    // The Class-File API (java.lang.classfile, final JDK 24, JEP 484)
    // replaces ASM for reading/writing class files inside the JDK.

    // ========================================================
    // SECTION 3: JIT COMPILATION
    // ========================================================
    // Tiered: level 0 interpreter (profiling) → 3 C1 with profiling →
    // 4 C2 optimized. Key optimizations: inlining (the "mother of all
    // optimizations"), escape analysis (scalar-replace objects that never
    // escape → no allocation), loop unrolling, intrinsics (System.arraycopy,
    // String.equals, crypto, vectorized ops), lock elision/coarsening,
    // speculative devirtualization with deoptimization fallback.
    // Observe: -XX:+PrintCompilation, JFR "jdk.Compilation" events, JITWatch.
    // Graal JIT (GraalVM) is an alternative top tier; GraalVM Native Image
    // compiles ahead of time to a native executable (closed-world, fast start,
    // reflection needs config).
    static long sumOfSquares(int n) { long s = 0; for (int i = 0; i < n; i++) s += (long) i * i; return s; }
    static void jitWarmup() {
        long cold = timeNs(() -> sumOfSquares(1_000_000));
        for (int i = 0; i < 2_000; i++) sumOfSquares(10_000);     // let C2 compile it
        long warm = timeNs(() -> sumOfSquares(1_000_000));
        IO.println("   1M-iteration loop: cold ≈ " + cold / 1_000 + "µs, after warmup ≈ " + warm / 1_000 + "µs (why JMH exists)");
    }
    static long timeNs(Runnable r) { long t = System.nanoTime(); r.run(); return System.nanoTime() - t; }

    // ========================================================
    // SECTION 4: MEMORY & OBJECT LAYOUT
    // ========================================================
    // Object = header (mark word: hash, lock state, GC age; class pointer)
    // + fields (reordered by size) + padding to 8 bytes.
    //   Classic header: 12 bytes (with compressed class pointers).
    //   Compact object headers (JEP 450 exp. JDK 24 → JEP 519 product
    //   JDK 25 via -XX:+UseCompactObjectHeaders → DEFAULT in JDK 27,
    //   JEP 534): 8 bytes — ~10-20% smaller heaps for object-heavy apps.
    // Compressed oops: 32-bit references for heaps < 32 GB — a 31 GB heap
    // can hold MORE than a 33 GB heap. Stay under ~31 GB or go well above.
    // Off-heap: direct ByteBuffers, MemorySegment (FFM), metaspace, thread stacks.
    static void memory() {
        MemoryMXBean mem = ManagementFactory.getMemoryMXBean();
        MemoryUsage heap = mem.getHeapMemoryUsage();
        IO.println("   heap used=" + mb(heap.getUsed()) + " committed=" + mb(heap.getCommitted()) + " max=" + mb(heap.getMax())
                + " | non-heap used=" + mb(mem.getNonHeapMemoryUsage().getUsed()));
        for (MemoryPoolMXBean pool : ManagementFactory.getMemoryPoolMXBeans())
            if (pool.getName().matches(".*(Eden|Old|Survivor|Metaspace|CodeHeap 'non-profiled).*"))
                IO.println("   pool " + pool.getName() + " [" + pool.getType() + "] used=" + mb(pool.getUsage().getUsed()));
        IO.println("   available processors=" + Runtime.getRuntime().availableProcessors() + " (container-aware since JDK 10)");
    }
    static String mb(long b) { return b < 0 ? "n/a" : (b / (1024 * 1024)) + "MB"; }

    // ========================================================
    // SECTION 5: GARBAGE COLLECTORS — CHOOSING ONE
    // ========================================================
    //  Collector    Flag                 Pauses           Best for
    //  G1 (default) -XX:+UseG1GC         ~10-200ms target  general purpose, 1-100s of GB
    //  ZGC          -XX:+UseZGC          < 1ms, ~heap-size independent  latency-critical, huge heaps
    //               (generational by default JDK 23; non-gen mode removed JDK 24, JEP 490)
    //  Shenandoah   -XX:+UseShenandoahGC < 10ms; generational mode product JDK 25 (JEP 521)
    //  Parallel     -XX:+UseParallelGC   long STW, max throughput   batch jobs
    //  Serial       -XX:+UseSerialGC     single-threaded STW        tiny heaps, CLIs
    //  Epsilon      -XX:+UseEpsilonGC    never collects             perf tests, short jobs
    // JDK 27 (JEP 523) makes G1 the default even on small machines where
    // the JVM previously picked Serial (< 2 CPUs or < 1792 MB).
    // G1 model: heap split into equal regions; young collections evacuate
    // eden/survivor regions; concurrent marking finds garbage-rich old
    // regions; mixed collections clean them ("garbage first").
    // Key flags: -Xms/-Xmx (or -XX:InitialRAMPercentage/MaxRAMPercentage),
    // -XX:MaxGCPauseMillis=200, -Xlog:gc*:file=gc.log:time,uptime,level,tags
    static void gcInfo() {
        for (GarbageCollectorMXBean gc : ManagementFactory.getGarbageCollectorMXBeans())
            IO.println("   collector " + gc.getName() + " collections=" + gc.getCollectionCount() + " time=" + gc.getCollectionTime() + "ms");
        // Allocate short-lived garbage and watch young collections happen:
        long before = totalCollections();
        List<byte[]> keep = new ArrayList<>();
        for (int i = 0; i < 20_000; i++) {
            byte[] chunk = new byte[16 * 1024];                 // 16 KB, mostly garbage
            if (i % 1000 == 0) keep.add(chunk);                 // a few survive
        }
        IO.println("   allocated ~312MB of short-lived arrays → +" + (totalCollections() - before) + " collections, kept " + keep.size());
        // Reference types: Strong > Soft (cleared under memory pressure; caches) >
        // Weak (cleared at next GC; WeakHashMap) > Phantom (post-mortem cleanup
        // via Cleaner — the replacement for deprecated finalize()).
    }
    static long totalCollections() {
        return ManagementFactory.getGarbageCollectorMXBeans().stream().mapToLong(GarbageCollectorMXBean::getCollectionCount).sum();
    }

    // ========================================================
    // SECTION 6: DIAGNOSTICS TOOLBOX
    // ========================================================
    //   jcmd <pid> help                       — the Swiss-army knife:
    //   jcmd <pid> VM.flags | VM.system_properties | VM.native_memory summary
    //   jcmd <pid> Thread.print               — thread dump (jstack)
    //   jcmd <pid> Thread.dump_to_file -format=json f.json  — incl. virtual threads
    //   jcmd <pid> GC.heap_dump /tmp/h.hprof  — analyse in Eclipse MAT / VisualVM
    //   jcmd <pid> GC.class_histogram         — top classes by instance count
    //   jcmd <pid> JFR.start duration=60s filename=rec.jfr settings=profile
    //   jstat -gcutil <pid> 1s                — live GC stats
    //   -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/dumps
    //   -XX:NativeMemoryTracking=summary      — then jcmd VM.native_memory
    // JFR (Flight Recorder): always-on low-overhead (<1-2%) profiling;
    // JDK 25 adds CPU-time profiling on Linux (JEP 509, experimental),
    // cooperative sampling (518), method timing & tracing (520); JDK 27
    // adds in-process data redaction (536). View with JDK Mission Control
    // or `jfr print --events jdk.GarbageCollection rec.jfr`.
    static void diagnostics() {
        RuntimeMXBean rt = ManagementFactory.getRuntimeMXBean();
        ThreadMXBean th = ManagementFactory.getThreadMXBean();
        IO.println("   VM=" + rt.getVmName() + " " + rt.getVmVersion() + " uptime=" + rt.getUptime() + "ms args=" + rt.getInputArguments());
        IO.println("   threads live=" + th.getThreadCount() + " peak=" + th.getPeakThreadCount() + " deadlocked=" + Arrays.toString(th.findDeadlockedThreads()));
    }

    // ========================================================
    // SECTION 7: STARTUP — CDS, AOT CACHE (Project Leyden)
    // ========================================================
    // CDS (class data sharing) maps pre-parsed JDK classes; on by default.
    // AOT cache (JDK 24, JEP 483): record a training run, then start with
    // classes already loaded+linked — 40%+ faster startup:
    //   JDK 25 one-step (JEP 514):  java -XX:AOTCacheOutput=app.aot -jar app.jar   (training run)
    //                               java -XX:AOTCache=app.aot -jar app.jar         (production)
    //   JDK 25 (JEP 515): the cache also stores method PROFILES → faster warmup.
    //   JDK 26 (JEP 516): AOT object caching works with ANY GC incl. ZGC.
    // Alternatives: CRaC (checkpoint/restore a warmed JVM — Azul, Spring),
    // GraalVM Native Image (no JIT warmup, smaller RSS, closed world).

    // ========================================================
    // SECTION 8: MODULES (JPMS, Java 9)
    // ========================================================
    // module-info.java at the source root:
    //   module com.acme.orders {
    //       requires java.net.http;                 // dependency
    //       requires transitive com.acme.money;     // consumers get it too
    //       requires static lombok;                 // compile-time only
    //       exports com.acme.orders.api;            // public API packages
    //       exports com.acme.orders.spi to com.acme.plugins;   // qualified
    //       opens com.acme.orders.model to com.fasterxml.jackson.databind; // deep reflection
    //       uses com.acme.orders.spi.PaymentProvider;           // ServiceLoader
    //       provides com.acme.orders.spi.PaymentProvider with com.acme.orders.StripeProvider;
    //   }
    // Strong encapsulation: non-exported packages are invisible even if
    // classes are public. Classpath code lives in the UNNAMED module (reads
    // everything); jars on the module path without module-info become
    // AUTOMATIC modules. `import module java.base;` (JEP 511, JDK 25)
    // imports every exported package of a module in source files.
    // jdeps --print-module-deps app.jar  → which JDK modules you need.
    // jlink --add-modules java.base,java.net.http,jdk.jfr --strip-debug
    //       --no-header-files --no-man-pages --compress=zip-9 --output rt
    //   → a 40-60 MB custom runtime for a slim container image.
    // jpackage → native installers (msi, dmg, deb, rpm) with a bundled runtime.
    static void modules() {
        Module m = String.class.getModule();
        IO.println("   String is in " + m.getName() + ", exports java.lang? " + m.isExported("java.lang")
                + ", exports jdk.internal.misc? " + m.isExported("jdk.internal.misc"));
        IO.println("   this class is in unnamed module: " + !L07_jvm_internals_gc_modules_ffm.class.getModule().isNamed()
                + " | boot layer modules=" + ModuleLayer.boot().modules().size());
    }

    // ========================================================
    // SECTION 9: REFLECTION, METHODHANDLES, VARHANDLES
    // ========================================================
    record Invoice(String id, long cents) { long withTax(double rate) { return Math.round(cents * (1 + rate)); } }

    static void reflection() throws Throwable {
        Class<?> c = Invoice.class;
        IO.println("   record components: " + Arrays.stream(c.getRecordComponents()).map(rc -> rc.getType().getSimpleName() + " " + rc.getName()).toList()
                + " isRecord=" + c.isRecord() + " final=" + Modifier.isFinal(c.getModifiers()));
        Method m = c.getDeclaredMethod("withTax", double.class);
        Object inv = c.getDeclaredConstructor(String.class, long.class).newInstance("inv-1", 10_000L);
        IO.println("   reflective call withTax(0.2)=" + m.invoke(inv, 0.2));

        // MethodHandles: typed, access-checked at lookup, JIT-inlinable — what
        // lambdas and modern frameworks use under the hood.
        MethodHandle mh = MethodHandles.lookup().findVirtual(Invoice.class, "withTax", MethodType.methodType(long.class, double.class));
        MethodHandle bound = mh.bindTo(new Invoice("inv-2", 5_000));
        IO.println("   MethodHandle invokeExact=" + (long) bound.invokeExact(0.1));

        // VarHandle: atomic/ordered access to fields and array elements (replaces Unsafe).
        VarHandle counterVH = MethodHandles.lookup().findStaticVarHandle(L07_jvm_internals_gc_modules_ffm.class, "counter", int.class);
        counterVH.getAndAdd(5);
        boolean swapped = counterVH.compareAndSet(5, 6);
        IO.println("   VarHandle CAS swapped=" + swapped + " counter=" + counter);

        // Dynamic proxies — how Spring AOP / Retrofit / mocking build interfaces at runtime.
        interface Greeter { String greet(String name); }
        Greeter proxy = (Greeter) Proxy.newProxyInstance(Greeter.class.getClassLoader(), new Class<?>[] {Greeter.class},
                (p, method, args) -> "[" + method.getName() + "] hello " + args[0]);
        IO.println("   proxy: " + proxy.greet("ada"));
        // Cost: reflection ~ 10-100x slower cold; JDK 18 (JEP 416) reimplemented
        // core reflection on MethodHandles. Prefer codegen at build time when hot.
    }
    static int counter = 0;

    // ========================================================
    // SECTION 10: FOREIGN FUNCTION & MEMORY API (final JDK 22, JEP 454)
    // ========================================================
    // Pure-Java replacement for JNI: no C glue code. Pieces:
    //   Arena          — lifetime of native memory (confined, shared, auto, global)
    //   MemorySegment  — bounds-checked, lifetime-checked pointer + size
    //   MemoryLayout   — describe C structs/arrays (padding, alignment)
    //   Linker         — downcalls (Java → C) and upcalls (C → Java callbacks)
    //   SymbolLookup   — find native symbols (libc, loaded libraries)
    // `jextract` generates bindings from C headers.
    // Native access is restricted (JEP 472): run with
    // --enable-native-access=ALL-UNNAMED (or a module name) to avoid warnings.
    static void ffm() throws Throwable {
        Linker linker = Linker.nativeLinker();
        MethodHandle strlen = linker.downcallHandle(
                linker.defaultLookup().find("strlen").orElseThrow(),
                FunctionDescriptor.of(ValueLayout.JAVA_LONG, ValueLayout.ADDRESS));
        try (Arena arena = Arena.ofConfined()) {                       // freed deterministically at close
            MemorySegment cString = arena.allocateFrom("Hello from the C runtime");
            IO.println("   strlen via FFM = " + (long) strlen.invokeExact(cString));

            // A C struct { int32_t id; double amount; } array of 3, off-heap:
            StructLayout txn = MemoryLayout.structLayout(
                    ValueLayout.JAVA_INT.withName("id"), MemoryLayout.paddingLayout(4), ValueLayout.JAVA_DOUBLE.withName("amount"));
            VarHandle idH = txn.arrayElementVarHandle(MemoryLayout.PathElement.groupElement("id"));
            VarHandle amtH = txn.arrayElementVarHandle(MemoryLayout.PathElement.groupElement("amount"));
            MemorySegment txns = arena.allocate(txn, 3);
            for (int i = 0; i < 3; i++) { idH.set(txns, 0L, (long) i, 100 + i); amtH.set(txns, 0L, (long) i, 9.99 * (i + 1)); }
            double total = 0; for (int i = 0; i < 3; i++) total += (double) amtH.get(txns, 0L, (long) i);
            IO.println("   off-heap struct array: size=" + txns.byteSize() + "B (layout " + txn.byteSize() + "B each) total=" + Math.round(total * 100) / 100.0
                    + " first id=" + (int) idH.get(txns, 0L, 0L));
            try { txns.getAtIndex(ValueLayout.JAVA_LONG, 100); } catch (IndexOutOfBoundsException e) { IO.println("   bounds-checked: out-of-range access rejected"); }
        }
    }

    public static void main(String[] args) throws Throwable {
        IO.println("== class loading"); classLoading();
        IO.println("== JIT"); jitWarmup();
        IO.println("== memory"); memory();
        IO.println("== GC"); gcInfo();
        IO.println("== diagnostics"); diagnostics();
        IO.println("== modules"); modules();
        IO.println("== reflection & handles"); reflection();
        IO.println("== FFM"); ffm();
    }
}
