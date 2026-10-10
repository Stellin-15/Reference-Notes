// ============================================================
// L02: Classes, Objects, Inheritance, Interfaces, Records,
//      Enums, Sealed Types, Nested Classes
// ============================================================
// WHAT: dev.java "Classes and Objects", "Inheritance",
//       "Interfaces", "Records", "Enums", "Sealed Classes",
//       "Nested Classes" tutorials and JLS ch. 8-9: fields,
//       constructors (incl. JDK 25 flexible constructor bodies),
//       initialization order, access control, static vs
//       instance, `this`/`super`, overriding rules, abstract
//       classes, default/static/private interface methods,
//       Object's contract (equals/hashCode/toString), records
//       with compact constructors, enums with behaviour,
//       sealed hierarchies, inner/local/anonymous classes.
// WHY:  Most Java bugs that survive code review are OO bugs:
//       broken equals/hashCode in HashMaps, mutable "value"
//       objects, overridable calls from constructors, leaking
//       `this`, inner classes pinning their outer instance in
//       memory. Records + sealed interfaces (Java 16/17) replaced
//       a lot of boilerplate and should be the default for data.
// LEVEL: Foundation → Intermediate
// RUN:   java L02_classes_objects_inheritance.java   (JDK 25)
// SOURCE: dev.java/learn/classes-objects, /inheritance,
//         /interfaces, /records, /enums, /sealed-classes,
//         JLS 25 ch. 8-9, JEP 395, 409, 513
// ============================================================
/*
CONCEPT OVERVIEW:
    A class declares state (fields) and behaviour (methods).
    Objects are created with `new`, live on the heap, and are
    reached through references. Java has single class
    inheritance (`extends`) and multiple interface inheritance
    (`implements`). Every class ultimately extends Object.
    Access levels: public > protected (package + subclasses) >
    package-private (no modifier) > private.

PRODUCTION USE CASE:
    A payments domain model: an immutable Money record, a
    sealed PaymentMethod hierarchy, an abstract Account base
    class with template-method behaviour, and an enum-based
    state machine for payment status.

COMMON MISTAKES:
    1. Overriding equals without hashCode (or vice versa) —
       objects "disappear" from HashSet/HashMap.
    2. Calling an overridable method from a constructor — the
       subclass override runs before the subclass's fields are
       initialised.
    3. Non-static inner classes capturing the outer instance
       (memory leaks, serialization surprises). Default to
       `static` nested classes.
    4. Exposing mutable internals from a getter (return a copy
       or an unmodifiable view; records don't copy for you).
    5. Field hiding: a subclass field with the same name doesn't
       override — fields are resolved by static type.
    6. Using `protected` as "a bit private" — it's also package-
       visible.
*/

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;

public class L02_classes_objects_inheritance {

    // ========================================================
    // SECTION 1: CLASS ANATOMY & INITIALIZATION ORDER
    // ========================================================
    static class InitOrder {
        static int staticCounter = log("1. static field initializer");
        static { log("2. static initializer block (once, at class init)"); }

        int a = log("3. instance field initializer");
        { log("4. instance initializer block"); }

        InitOrder() {
            // super() runs implicitly FIRST (before 3 and 4).
            log("5. constructor body");
        }
        static int log(String s) { IO.println("   " + s); return 0; }
    }
    // Class initialization is lazy: triggered by first `new`, static
    // method call, or non-constant static field access — and done once,
    // thread-safely, by the JVM (basis of the holder-idiom singleton).

    // ========================================================
    // SECTION 2: CONSTRUCTORS, `this`, CHAINING, FLEXIBLE BODIES
    // ========================================================
    static class Rectangle {
        private final double width;     // final fields must be assigned exactly once
        private final double height;

        Rectangle(double width, double height) {
            // JDK 25 (JEP 513, flexible constructor bodies): statements
            // may appear BEFORE this(...)/super(...) — e.g. validation —
            // as long as they don't use `this`.
            if (width <= 0 || height <= 0) throw new IllegalArgumentException("non-positive side");
            this.width = width;            // `this.` disambiguates field vs parameter
            this.height = height;
        }
        Rectangle(double side) {
            this(side, side);              // constructor chaining
        }
        double area() { return width * height; }
    }

    static class PositiveCounter extends ArrayList<Integer> {
        PositiveCounter(int initialCapacity) {
            // Before JDK 25 you'd need a static helper to validate before super().
            if (initialCapacity < 0) throw new IllegalArgumentException("capacity");
            super(initialCapacity);
        }
    }

    // ========================================================
    // SECTION 3: STATIC VS INSTANCE, ACCESS CONTROL
    // ========================================================
    static class IdGen {
        private static long next = 1;         // one per class (per class loader)
        private final long id;                // one per instance
        IdGen() { id = next++; }
        long id() { return id; }
        static long issued() { return next - 1; } // static methods can't use `this`
    }
    // Access summary:              class  package  subclass  world
    //   public                      ✓       ✓        ✓        ✓
    //   protected                   ✓       ✓        ✓        ✗
    //   (package-private)           ✓       ✓        ✗        ✗
    //   private                     ✓       ✗        ✗        ✗
    // Top-level classes: public or package-private only.
    // Modules (L07) add another layer: only EXPORTED packages are visible.

    // ========================================================
    // SECTION 4: INHERITANCE, OVERRIDING, POLYMORPHISM
    // ========================================================
    abstract static class Account {
        protected final String owner;
        private long balanceCents;

        Account(String owner) { this.owner = owner; }

        // TEMPLATE METHOD: final algorithm, overridable steps.
        public final void withdraw(long cents) {
            if (cents <= 0) throw new IllegalArgumentException("amount");
            long fee = fee(cents);                    // dynamic dispatch
            if (cents + fee > balanceCents + overdraftLimit()) throw new IllegalStateException("insufficient funds");
            balanceCents -= cents + fee;
        }
        public void deposit(long cents) { balanceCents += cents; }
        public long balance() { return balanceCents; }

        protected abstract long fee(long cents);      // must implement
        protected long overdraftLimit() { return 0; } // may override

        @Override
        public String toString() { return getClass().getSimpleName() + "[" + owner + ", " + balanceCents + "c]"; }
    }

    static class Checking extends Account {
        Checking(String owner) { super(owner); }      // super(...) must be explicit if no no-arg ctor
        @Override protected long fee(long cents) { return 25; }
        @Override protected long overdraftLimit() { return 10_000; }
    }

    static final class Savings extends Account {      // final: cannot be subclassed
        Savings(String owner) { super(owner); }
        @Override protected long fee(long cents) { return cents > 50_000 ? 100 : 0; }
        // Covariant return types are allowed when overriding:
        @Override public String toString() { return "Savings*" + super.toString(); }
    }
    // OVERRIDING RULES: same signature; return type same or subtype;
    // access can't be narrower; can't throw broader checked exceptions;
    // static methods are HIDDEN, not overridden; private methods aren't
    // inherited. @Override makes the compiler verify you really override.

    // Field hiding vs method overriding:
    static class Parent { String name = "parent"; String who() { return "parent"; } }
    static class Child extends Parent { String name = "child"; @Override String who() { return "child"; } }

    // The constructor trap:
    static class Base {
        Base() { IO.println("   Base ctor sees describe() = " + describe()); }
        String describe() { return "base"; }
    }
    static class Derived extends Base {
        private String label = "derived-label";
        @Override String describe() { return label; }  // runs BEFORE label is set → null
    }
    // Subtlety: had `label` been `final String label = "derived-label"`, it would
    // be a CONSTANT VARIABLE (final + constant initializer) — javac inlines the
    // literal at every use, so the trap would NOT show. Any non-constant
    // initializer (a method call, a non-final field) exposes the null.
    static class DerivedConst extends Base {
        private final String label = "inlined-constant";
        @Override String describe() { return label; }  // prints "inlined-constant"
    }

    // ========================================================
    // SECTION 5: INTERFACES
    // ========================================================
    interface Shape {
        double area();                                  // abstract (implicitly public)
        default String describe() {                     // default method (Java 8)
            return "%s with area %.2f".formatted(name(), area());
        }
        private String name() { return getClass().getSimpleName(); } // private helper (Java 9)
        static Shape unitSquare() { return new Square(1); }           // static factory (Java 8)
        double PI_ISH = 3.14;                           // constant: implicitly public static final
    }
    record Square(double side) implements Shape { public double area() { return side * side; } }
    record Circle(double r) implements Shape { public double area() { return Math.PI * r * r; } }

    // Diamond resolution for default methods: class wins; else the more
    // specific interface wins; else you MUST override and pick with X.super.m().
    interface Walker { default String move() { return "walk"; } }
    interface Swimmer { default String move() { return "swim"; } }
    static class Duck implements Walker, Swimmer {
        @Override public String move() { return Walker.super.move() + "+" + Swimmer.super.move(); }
    }

    // Functional interfaces (one abstract method) → lambdas (L03).
    // Marker interfaces (Serializable, Cloneable) carry no methods.

    // ========================================================
    // SECTION 6: Object'S CONTRACT — equals / hashCode / toString
    // ========================================================
    static final class Point {
        private final int x, y;
        Point(int x, int y) { this.x = x; this.y = y; }
        // equals: reflexive, symmetric, transitive, consistent, x.equals(null)==false
        @Override public boolean equals(Object o) {
            if (this == o) return true;
            return o instanceof Point p && x == p.x && y == p.y; // pattern matching instanceof
        }
        // Equal objects MUST have equal hash codes.
        @Override public int hashCode() { return Objects.hash(x, y); }
        @Override public String toString() { return "Point(" + x + "," + y + ")"; }
    }
    static final class BrokenPoint {
        final int x, y;
        BrokenPoint(int x, int y) { this.x = x; this.y = y; }
        @Override public boolean equals(Object o) { return o instanceof BrokenPoint p && p.x == x && p.y == y; }
        // no hashCode override → identity hash → HashSet can't find equal instances
    }
    // Using getClass() != o.getClass() vs instanceof in equals: getClass is
    // strict (subclasses never equal), instanceof allows subclass equality
    // but breaks symmetry if a subclass adds state. Final classes avoid the dilemma.

    // ========================================================
    // SECTION 7: RECORDS (Java 16, JEP 395)
    // ========================================================
    // Transparent, shallowly immutable data carriers. Auto-generated:
    // private final fields, canonical constructor, accessors x() (not
    // getX()), equals, hashCode, toString. Records are implicitly final
    // and can't extend classes (they extend java.lang.Record).
    record Money(long cents, String currency) {
        // Compact canonical constructor: validation/normalisation;
        // field assignment happens automatically after the body.
        Money {
            Objects.requireNonNull(currency, "currency");
            if (currency.length() != 3) throw new IllegalArgumentException("ISO-4217 code expected");
            currency = currency.toUpperCase();         // reassigning the PARAMETER
        }
        // Additional constructors must delegate to the canonical one.
        Money(long cents) { this(cents, "USD"); }
        static Money zero(String ccy) { return new Money(0, ccy); }  // static factories OK
        Money plus(Money o) {
            if (!currency.equals(o.currency)) throw new IllegalArgumentException("currency mismatch");
            return new Money(cents + o.cents, currency);          // "withers" return new instances
        }
        @Override public String toString() { return "%s %d.%02d".formatted(currency, cents / 100, Math.abs(cents % 100)); }
    }
    // Defensive copy for mutable components — records don't do it for you:
    record Team(String name, List<String> members) {
        Team { members = List.copyOf(members); }       // immutable copy, rejects nulls
    }
    // Records may implement interfaces, declare static fields, nested
    // types, and instance methods — but no instance fields beyond components.
    // Local records (declared inside a method) are great for intermediate results.

    // ========================================================
    // SECTION 8: ENUMS
    // ========================================================
    enum PaymentStatus {
        PENDING { @Override boolean canMoveTo(PaymentStatus s) { return s == AUTHORIZED || s == FAILED; } },
        AUTHORIZED { @Override boolean canMoveTo(PaymentStatus s) { return s == CAPTURED || s == VOIDED; } },
        CAPTURED { @Override boolean canMoveTo(PaymentStatus s) { return s == REFUNDED; } },
        REFUNDED, VOIDED, FAILED;                      // terminal: use default below

        boolean canMoveTo(PaymentStatus next) { return false; }
        boolean isTerminal() { return !(this == PENDING || this == AUTHORIZED || this == CAPTURED); }
    }
    enum Planet {
        MERCURY(3.303e+23, 2.4397e6), EARTH(5.976e+24, 6.37814e6);
        private final double mass, radius;              // enums can have fields and constructors
        Planet(double mass, double radius) { this.mass = mass; this.radius = radius; } // implicitly private
        double surfaceGravity() { return 6.67300E-11 * mass / (radius * radius); }
    }
    // Enums: singletons per constant, safe with ==, usable in switch,
    // values()/valueOf()/ordinal()/name(); EnumSet and EnumMap are the
    // fastest Set/Map for enum keys (bit vectors / arrays).
    // An enum with one constant is the recommended serialization-safe singleton.

    // ========================================================
    // SECTION 9: SEALED CLASSES AND INTERFACES (Java 17, JEP 409)
    // ========================================================
    // `sealed ... permits` restricts which classes may extend/implement.
    // Each permitted subclass must be final, sealed, or non-sealed.
    sealed interface PaymentMethod permits Card, BankTransfer, Wallet {}
    record Card(String last4, int expMonth, int expYear) implements PaymentMethod {}
    record BankTransfer(String iban) implements PaymentMethod {}
    non-sealed static class Wallet implements PaymentMethod {   // reopens the hierarchy below here
        final String provider;
        Wallet(String provider) { this.provider = provider; }
    }
    static final class ApplePay extends Wallet { ApplePay() { super("apple"); } }

    // The payoff: exhaustive switch without `default` (L05 goes deep).
    static String route(PaymentMethod m) {
        return switch (m) {
            case Card c -> "card network for *" + c.last4();
            case BankTransfer b -> "SEPA for " + b.iban().substring(0, 4) + "…";
            case Wallet w -> "wallet provider " + w.provider;
        };
    }

    // ========================================================
    // SECTION 10: NESTED, INNER, LOCAL, ANONYMOUS CLASSES
    // ========================================================
    static class Outer {
        private int secret = 42;
        static class StaticNested { int peek(Outer o) { return o.secret; } } // no implicit outer ref
        class Inner { int peek() { return secret; } }                        // holds Outer.this
        Runnable local() {
            int captured = secret * 2;                     // must be effectively final
            class LocalHelper implements Runnable {        // local class
                public void run() { IO.println("   local class sees " + captured); }
            }
            return new LocalHelper();
        }
        Runnable anonymous() {
            return new Runnable() {                        // anonymous class
                @Override public void run() { IO.println("   anonymous sees " + Outer.this.secret); }
            };
        }
    }
    // Rule of thumb: static nested by default; lambdas instead of
    // anonymous classes for functional interfaces; inner classes only
    // when each instance truly belongs to one outer instance (iterators).

    // ========================================================
    // SECTION 11: END-TO-END
    // ========================================================
    public static void main(String[] args) {
        IO.println("== init order");
        new InitOrder();

        IO.println("== constructors: area=" + new Rectangle(3).area() + ", capacity list empty=" + new PositiveCounter(5).isEmpty());
        try { new Rectangle(-1, 2); } catch (IllegalArgumentException e) { IO.println("   rejected: " + e.getMessage()); }

        new IdGen(); new IdGen();
        IO.println("== static: issued=" + IdGen.issued() + " third id=" + new IdGen().id());

        IO.println("== polymorphism");
        List<Account> accounts = List.of(new Checking("ada"), new Savings("bob"));
        for (Account a : accounts) {
            a.deposit(100_000);
            a.withdraw(60_000);
            IO.println("   " + a);
        }
        try { accounts.get(1).withdraw(1_000_000); } catch (IllegalStateException e) { IO.println("   " + e.getMessage()); }

        Parent p = new Child();
        IO.println("== hiding: field=" + p.name + " method=" + p.who());   // parent / child
        IO.println("== constructor trap:");
        new Derived();                                                       // prints null
        new DerivedConst();                                                  // prints the inlined constant

        IO.println("== interfaces: " + new Circle(1).describe() + " | " + Shape.unitSquare().describe() + " | " + new Duck().move());

        var set = new HashSet<Object>();
        set.add(new Point(1, 2));
        set.add(new BrokenPoint(1, 2));
        IO.println("== equals/hashCode: contains Point=" + set.contains(new Point(1, 2))
                + " contains BrokenPoint=" + set.contains(new BrokenPoint(1, 2)));

        Money m = new Money(1999, "usd").plus(new Money(1));
        IO.println("== records: " + m + " equals=" + m.equals(new Money(2000, "USD")) + " accessor=" + m.cents());
        var members = new ArrayList<>(List.of("ada"));
        Team team = new Team("core", members);
        members.add("mallory");
        IO.println("   defensive copy keeps team=" + team.members());

        IO.println("== enums: PENDING→CAPTURED allowed? " + PaymentStatus.PENDING.canMoveTo(PaymentStatus.CAPTURED)
                + ", AUTHORIZED→CAPTURED? " + PaymentStatus.AUTHORIZED.canMoveTo(PaymentStatus.CAPTURED)
                + ", REFUNDED terminal? " + PaymentStatus.REFUNDED.isTerminal()
                + String.format(", g(EARTH)=%.2f", Planet.EARTH.surfaceGravity()));

        IO.println("== sealed:");
        for (PaymentMethod pm : List.of(new Card("4242", 12, 2030), new BankTransfer("DE89370400440532013000"), new ApplePay()))
            IO.println("   " + route(pm));

        IO.println("== nested:");
        Outer o = new Outer();
        IO.println("   static nested=" + new Outer.StaticNested().peek(o) + " inner=" + o.new Inner().peek());
        o.local().run();
        o.anonymous().run();
    }
}
