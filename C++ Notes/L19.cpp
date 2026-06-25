// ============================================================
// L19: Virtual Functions, vtables, and CRTP
// ============================================================
// WHAT: How polymorphic dispatch works under the hood. The vtable
//       is a hidden lookup table the compiler builds to enable
//       runtime method selection. CRTP achieves the same effect
//       at compile time with zero runtime overhead.
// WHY (TRADING): Virtual function calls cost ~5-10ns due to a
//   pointer indirection through the vtable. On a path that runs
//   1 million times per second, that's 5-10ms wasted per second.
//   In HFT hot paths, virtual calls are avoided. CRTP (Curiously
//   Recurring Template Pattern) gives polymorphic behavior with
//   ZERO overhead — the compiler inlines everything at compile time.
//   Knowing this lets you make the right architectural choice.
// PHASE: OOP
// ============================================================

/*
  CONCEPT OVERVIEW:

  HOW VIRTUAL FUNCTIONS WORK:
    When a class has at least one virtual function, the compiler adds:
    1. A vptr (virtual pointer) as a HIDDEN FIELD in every object.
       This pointer adds sizeof(void*) = 8 bytes to every instance.
    2. A vtable (virtual dispatch table) per class — an array of
       function pointers, one per virtual method.

    Calling base->method() with virtual:
      1. Load vptr from object (memory access — possible cache miss)
      2. Index into vtable to find the right function pointer (another memory access)
      3. Call through that pointer (indirect jump — branch predictor struggles)
    Result: ~5-10ns overhead vs a direct call, plus prevents inlining.

    Calling obj.method() with no virtual (known static type):
      1. Direct call to the function — the compiler already knows which one
    Result: 0 overhead, can be fully inlined.

  VIRTUAL DESTRUCTOR RULE:
    If a class has ANY virtual methods, its destructor MUST be virtual.
    Without it: delete base_ptr calls ONLY base destructor, not derived.
    Result: derived class resources (memory, handles) are leaked.

  ABSTRACT CLASS:
    Has at least one pure virtual method (= 0).
    Cannot be instantiated directly — forces derived classes to implement it.
    Used as interfaces in trading: BaseStrategy, BaseGateway, BaseRiskModel.

  FINAL:
    class Foo final { ... }    — nobody can inherit from Foo
    void bar() final;          — nobody can override bar()
    PERFORMANCE: marking a class final allows the compiler to devirtualize
    calls — it knows there's no derived class, so it can call directly.

  CRTP — Curiously Recurring Template Pattern:
    template<typename Derived>
    class Base {
    public:
        void interface_method() {
            static_cast<Derived*>(this)->implementation();  // compile-time dispatch
        }
    };
    class Concrete : public Base<Concrete> {
    public:
        void implementation() { ... }   // called at compile time
    };
    BENEFIT: Polymorphism resolved at compile time — zero runtime overhead.
    COST: Each derived type generates new code (code size grows).
          Cannot switch strategies at runtime (must know type at compile time).
    IN HFT: CRTP is used for the hot path; regular virtual for the slow path.

  DEVIRTUALIZATION:
    If the compiler can prove which derived type an object is at a call site,
    it replaces the virtual call with a direct call automatically.
    Triggers when: the object is local (not via pointer), class is final,
    or with whole-program optimization.

  TRADING USE CASE:
    // Slow path (control, config, monitoring): virtual is fine
    class BaseGateway { virtual void send(const Order&) = 0; };

    // Hot path (tick processing, 1M ticks/sec): use CRTP
    template<typename Derived>
    class TickHandler {
        void on_tick(const Quote& q) {
            static_cast<Derived*>(this)->process(q);  // zero overhead
        }
    };

  COMMON MISTAKES:
    - Virtual calls in a tight loop — check if CRTP is appropriate
    - Missing virtual destructor — resource leaks when deleting via base pointer
    - Calling virtual methods from constructor — dispatches to BASE, not derived
    - Assuming devirtualization always happens — verify with profiler or compiler explorer
*/

#include <iostream>
#include <cstdint>
#include <chrono>
#include <memory>

// ============================================================
// PART 1: VIRTUAL DISPATCH — how it works
// ============================================================

class Animal {
public:
    virtual void speak() const {         // virtual: dispatched at runtime
        std::cout << "Animal speaks\n";
    }
    void breathe() const {               // non-virtual: always calls Animal::breathe
        std::cout << "Animal breathes\n";
    }
    virtual ~Animal() = default;         // virtual destructor: REQUIRED
};

class Dog : public Animal {
public:
    void speak() const override {        // override: replaces Animal::speak
        std::cout << "Dog: Woof!\n";
    }
};

class Cat : public Animal {
public:
    void speak() const override {
        std::cout << "Cat: Meow!\n";
    }
};

// ============================================================
// PART 2: VIRTUAL FUNCTIONS IN TRADING — slow path use
// ============================================================

struct Quote { double bid, ask; double mid() const { return (bid+ask)/2.0; } };
struct Fill  { double price; int qty; bool is_buy; };

// Base interface for all strategies — virtual, used on slow path
class IStrategy {
public:
    virtual void   on_quote(const Quote& q) = 0;   // pure virtual
    virtual void   on_fill(const Fill& f)   = 0;   // pure virtual
    virtual const char* name()        const = 0;   // pure virtual
    virtual ~IStrategy() = default;                 // mandatory virtual destructor
};

class SimpleStrategy : public IStrategy {
public:
    void on_quote(const Quote& q) override {
        last_mid_ = q.mid();
    }
    void on_fill(const Fill& f) override {
        pnl_ += (f.is_buy ? -1 : 1) * f.price * f.qty;
    }
    const char* name() const override { return "Simple"; }
    double pnl() const { return pnl_; }
private:
    double last_mid_ = 0.0;
    double pnl_      = 0.0;
};

// ============================================================
// PART 3: CRTP — compile-time polymorphism (zero overhead)
// ============================================================

// Base class is parameterized on the Derived type.
// The call to Derived::process() is resolved at COMPILE TIME.
// The compiler can inline the entire chain — no vtable, no vptr.
template<typename Derived>
class TickHandlerBase {
public:
    // This is the "interface" — called from outside
    void on_tick(const Quote& q) {
        // Downcast to Derived and call its implementation
        // This is resolved at COMPILE TIME — zero overhead
        static_cast<Derived*>(this)->process_tick(q);
    }

    // Common pre/post logic in the base (shared by all handlers)
    void handle(const Quote& q) {
        pre_process(q);
        on_tick(q);     // CRTP dispatch
        post_process(q);
    }

private:
    void pre_process(const Quote& q) {
        // Could do: sequence validation, timestamp check, etc.
        (void)q;
    }
    void post_process(const Quote& q) {
        // Could do: latency measurement, logging trigger
        (void)q;
    }
};

// Concrete momentum handler — inherits from Base<itself> (the CRTP pattern)
class MomentumHandler : public TickHandlerBase<MomentumHandler> {
public:
    // This method is called by the base class via static_cast — compile-time dispatch
    void process_tick(const Quote& q) {
        double mid = q.mid();
        if (prev_mid_ > 0) {
            double move_bps = (mid - prev_mid_) / prev_mid_ * 10000.0;
            if (move_bps > 5.0)  std::cout << "[CRTP Mom] BUY signal: " << move_bps << " bps\n";
            if (move_bps < -5.0) std::cout << "[CRTP Mom] SELL signal: " << move_bps << " bps\n";
        }
        prev_mid_ = mid;
    }
private:
    double prev_mid_ = 0.0;
};

// Another concrete handler — same base, different implementation
class VWAPHandler : public TickHandlerBase<VWAPHandler> {
public:
    void process_tick(const Quote& q) {
        double mid = q.mid();
        sum_  += mid;
        count_++;
        vwap_ = sum_ / count_;
        if (mid < vwap_ * 0.999) std::cout << "[CRTP VWAP] Price below VWAP — BUY\n";
        if (mid > vwap_ * 1.001) std::cout << "[CRTP VWAP] Price above VWAP — SELL\n";
    }
private:
    double sum_  = 0.0;
    int    count_ = 0;
    double vwap_  = 0.0;
};

// ============================================================
// PART 4: LATENCY COMPARISON — virtual vs direct
// ============================================================

// A tight benchmark loop comparing virtual call overhead
// (In a real system: use perf stat or Google Benchmark)
void benchmark() {
    constexpr int ITERATIONS = 10'000'000;
    Quote q{182.50, 182.55};

    // --- Virtual dispatch ---
    auto* strat = new SimpleStrategy();
    auto t1 = std::chrono::high_resolution_clock::now();
    for (int i = 0; i < ITERATIONS; ++i) {
        strat->on_quote(q);   // virtual call: vtable lookup each time
    }
    auto t2 = std::chrono::high_resolution_clock::now();
    long ns_virtual = std::chrono::duration_cast<std::chrono::nanoseconds>(t2 - t1).count();
    delete strat;

    // --- CRTP (direct, inlined) ---
    MomentumHandler handler;
    auto t3 = std::chrono::high_resolution_clock::now();
    for (int i = 0; i < ITERATIONS; ++i) {
        handler.on_tick(q);   // CRTP: statically resolved, can be inlined
    }
    auto t4 = std::chrono::high_resolution_clock::now();
    long ns_crtp = std::chrono::duration_cast<std::chrono::nanoseconds>(t4 - t3).count();

    std::cout << "=== Latency Benchmark (" << ITERATIONS << " calls) ===\n";
    std::cout << "Virtual call total:  " << ns_virtual << " ns"
              << "  (" << ns_virtual / ITERATIONS << " ns/call)\n";
    std::cout << "CRTP direct total:   " << ns_crtp    << " ns"
              << "  (" << ns_crtp    / ITERATIONS << " ns/call)\n";
    std::cout << "Speedup: ~" << (ns_virtual / std::max(1L, ns_crtp)) << "x\n";
}

// ============================================================
// MAIN
// ============================================================

int main() {

    // -------------------------------------------------------
    // VIRTUAL DISPATCH BASICS
    // -------------------------------------------------------

    std::cout << "--- Virtual dispatch demo ---\n";

    Animal* animals[] = { new Dog(), new Cat(), new Animal() };
    for (Animal* a : animals) {
        a->speak();       // virtual: calls the RIGHT derived speak()
        a->breathe();     // non-virtual: always calls Animal::breathe
    }
    for (Animal* a : animals) delete a;

    // -------------------------------------------------------
    // VIRTUAL IN TRADING: Strategy via interface
    // -------------------------------------------------------

    std::cout << "\n--- Virtual strategy interface ---\n";

    std::unique_ptr<IStrategy> s = std::make_unique<SimpleStrategy>();
    s->on_quote({182.50, 182.55});
    s->on_fill({182.55, 100, true});
    std::cout << "Strategy: " << s->name() << "\n";

    // -------------------------------------------------------
    // CRTP — zero overhead compile-time polymorphism
    // -------------------------------------------------------

    std::cout << "\n--- CRTP handlers ---\n";

    MomentumHandler mom;
    VWAPHandler     vwap;

    std::vector<Quote> ticks = {
        {182.40, 182.50},
        {182.55, 182.65},  // +10bps move
        {182.60, 182.70},
        {182.45, 182.55},  // -13bps reversal
    };

    for (const auto& q : ticks) {
        mom.handle(q);
        vwap.handle(q);
    }

    // -------------------------------------------------------
    // BENCHMARK
    // -------------------------------------------------------

    std::cout << "\n";
    benchmark();

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      The two-tier architecture used in real HFT systems:

        SLOW PATH (configuration, monitoring, startup):
          IStrategy* strat = load_strategy_from_config("momentum");
          // Virtual dispatch is fine here — runs once at startup

        HOT PATH (tick processing, 1M+ ticks/second):
          // CRTP: the compiler inlines the entire chain
          template<typename S>
          void tick_loop(S& strategy) {
              while (running) {
                  Quote q = receive_tick();
                  strategy.on_tick(q);  // statically known type, zero overhead
              }
          }
          // Called as:
          MomentumHandler m;
          tick_loop(m);   // compiler generates code specific to MomentumHandler

        This hybrid approach is used by most top-tier HFT firms:
        virtual for flexibility, CRTP for performance-critical paths.
    */
}
