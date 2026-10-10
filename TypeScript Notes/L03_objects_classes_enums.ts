// ============================================================
// L03: Object Types, Classes, Enums, Symbols, Iterators
// ============================================================
// WHAT: Handbook "Object Types" and "Classes" chapters plus the
//       Reference pages "Enums", "Symbols", and "Iterators and
//       Generators". Property modifiers, index signatures,
//       extending/intersecting, generic object types, readonly
//       arrays and tuples; class fields, constructors, accessors,
//       implements/extends, visibility (public/protected/private
//       vs #private), static members and blocks, parameter
//       properties, abstract classes, `this` types; numeric,
//       string and const enums; unique symbols; iterables,
//       generators, and async iteration.
// WHY:  Classes and object types are how most application code
//       models its domain. Enums and parameter properties are two
//       of the few TS features that EMIT runtime code — important
//       now that Node runs TS by stripping types (`erasableSyntaxOnly`).
// LEVEL: Intermediate
// SOURCE: typescriptlang.org/docs/handbook/2/objects.html,
//         .../2/classes.html, .../enums.html, .../symbols.html,
//         .../iterators-and-generators.html (TS 7.0, Oct 2026)
// ============================================================
/*
CONCEPT OVERVIEW:
    An object type lists properties with modifiers (optional `?`,
    `readonly`) and may carry index signatures. Classes are JS
    classes plus type annotations: TS adds visibility keywords,
    abstract members, `implements` checks, and parameter
    properties — but at runtime they are plain ES classes.
    Classes are still compared STRUCTURALLY: an object literal
    with the right shape is assignable to a class type unless the
    class has private/protected members.

PRODUCTION USE CASE:
    A repository layer for an inventory service: an abstract
    base repository, concrete in-memory implementation, typed
    events via a string enum alternative, and an async generator
    that pages through results.

COMMON MISTAKES:
    1. Believing `private` hides data at runtime. TS `private` is
       compile-time only — `obj["secret"]` works in JS. Use
       ECMAScript `#secret` for real privacy.
    2. Using `readonly` to mean "deeply immutable". It's shallow.
    3. Losing `this` when passing a method as a callback
       (`setTimeout(obj.method)`). Use arrow-function fields or bind.
    4. Numeric enums accepting any number in old TS (<5.0) — and
       reverse-mapping surprises. Prefer string enums or unions.
    5. `const enum` in libraries — breaks consumers using
       isolatedModules/Babel/esbuild. Avoid in published code.
    6. Index signature `[k: string]: number` then adding a
       `name: string` property — every property must match the
       index signature's type.
*/

// ============================================================
// SECTION 1: PROPERTY MODIFIERS
// ============================================================
interface PaintOptions {
  shape: { kind: "circle" | "square" };
  xPos?: number;            // optional
  readonly createdBy: string; // can't be written through this type
}

function paint({ shape, xPos = 0, createdBy }: PaintOptions) {
  // NOTE: you cannot annotate inside a destructuring pattern —
  // `{ shape: Shape }` would RENAME shape to a variable called Shape.
  return `${createdBy} paints ${shape.kind} at ${xPos}`;
}

// readonly is shallow, and readonly-ness is not enforced across aliases:
interface Person { name: string; age: number }
interface ReadonlyPerson { readonly name: string; readonly age: number }
const writable: Person = { name: "A", age: 1 };
const ro: ReadonlyPerson = writable; // allowed — structurally compatible
writable.age++;                      // ro.age changes too

// `exactOptionalPropertyTypes`: when on, `xPos?: number` means "absent
// or number" — explicitly writing `xPos: undefined` becomes an error.

// ============================================================
// SECTION 2: INDEX SIGNATURES
// ============================================================
interface StringArray { [index: number]: string }
interface Dictionary {
  [key: string]: number | string; // all named properties must fit
  length: number;                  // OK: number is in the union
  name: string;                    // OK
}
// Allowed index key types: string, number, symbol, template literal
// patterns, and unions of these.
interface Headers { [header: `x-${string}`]: string }
const h: Headers = { "x-request-id": "abc" };

// Record<K, V> is usually the cleaner way to write a dictionary.
const scores: Record<string, number> = {};
// With `noUncheckedIndexedAccess`, scores["bob"] is number | undefined —
// recommended for real codebases; dictionaries lie about presence.

// ============================================================
// SECTION 3: EXTENDING AND INTERSECTING
// ============================================================
interface BasicAddress { street: string; city: string; country: string }
interface AddressWithUnit extends BasicAddress { unit: string }
interface Colorful { color: string }
interface Circle { radius: number }
interface ColorfulCircle extends Colorful, Circle {}  // multiple extends
type ColorfulCircle2 = Colorful & Circle;             // equivalent intersection

// ============================================================
// SECTION 4: GENERIC OBJECT TYPES
// ============================================================
interface Box<T> { contents: T }
type OrNull<T> = T | null;
type OneOrMany<T> = T | T[];
function setContents<T>(box: Box<T>, value: T) { box.contents = value; }
const sbox: Box<string> = { contents: "hello" };
setContents(sbox, "bye");

// Built-in generic object types you use daily:
//   Array<T>, ReadonlyArray<T>, Map<K,V>, Set<T>, Promise<T>,
//   ReadonlyMap, ReadonlySet, WeakMap<K extends object, V>
function doStuff(values: ReadonlyArray<string>) {
  // values.push("x");  // error
  return values.slice();
}

// ============================================================
// SECTION 5: CLASS MEMBERS
// ============================================================
class Point {
  x = 0;                  // field with initializer — type inferred number
  y: number;              // must be assigned in constructor (strictPropertyInitialization)
  name!: string;          // definite assignment assertion — "trust me, set elsewhere"
  readonly origin = "0,0";

  constructor(x = 0, y = 0) {
    this.x = x;
    this.y = y;
  }

  // Constructor overloads are allowed (same rules as function overloads).
  scale(n: number): void {
    this.x *= n;
    this.y *= n;
  }
}

// Getters/setters. Since TS 5.1 the getter and setter types may be
// unrelated (setter accepts more types than the getter returns).
class Thermostat {
  #celsius = 20; // ECMAScript private field — truly private at runtime
  get celsius(): number { return this.#celsius; }
  set celsius(v: number | string) { this.#celsius = Number(v); }
}
const t = new Thermostat();
t.celsius = "23"; // setter accepts string
// Only a getter, no setter → property is automatically readonly.

// Index signatures in classes (rare, but allowed):
class MyClass {
  [s: string]: boolean | ((s: string) => boolean);
  check(s: string) { return this[s] as boolean; }
}

// ============================================================
// SECTION 6: implements AND extends
// ============================================================
interface Pingable { ping(): string }
class Sonar implements Pingable {
  ping() { return "ping!"; }
}
// `implements` is a CHECK only — it doesn't change the class's type
// or infer parameter types for methods. This is a common surprise:
interface Checkable { check(name: string): boolean }
class NameChecker implements Checkable {
  check(s: string) { return s.toLowerCase() === "ok"; } // must annotate s yourself
}

class Animal {
  move(distance = 0) { return `moved ${distance}m`; }
}
class Dog extends Animal {
  woof(times: number) { return "woof".repeat(times); }
  // override keyword (with `noImplicitOverride`) guards against base renames
  override move(distance = 5) { return super.move(distance) + " (dog)"; }
}
const d: Animal = new Dog(); // derived assignable to base
d.move();

// Initialization order: base fields → base ctor → derived fields → derived ctor.
// Consequence: a base constructor that reads a field the derived class
// re-declares sees the BASE value.

// Subclassing built-ins (Error, Array, Map) when targeting ES5 needed
// Object.setPrototypeOf hacks. ES5 targets are deprecated as of TS 6.0
// and removed in 7.0, so with ES2015+ output `class MyError extends Error`
// just works.
class NotFoundError extends Error {
  override name = "NotFoundError";
  constructor(public readonly resource: string) { super(`${resource} not found`); }
}

// ============================================================
// SECTION 7: MEMBER VISIBILITY
// ============================================================
class Account {
  public id: string;          // default — accessible anywhere
  protected balance = 0;      // this class and subclasses
  private auditLog: string[] = []; // this class only (compile-time)
  #pin: string;               // runtime-private (ES2022)

  constructor(id: string, pin: string) { this.id = id; this.#pin = pin; }

  deposit(n: number) { this.balance += n; this.auditLog.push(`+${n}`); }
  verify(pin: string) { return pin === this.#pin; }

  // Cross-instance private access IS allowed in TS (unlike some languages):
  sameLog(other: Account) { return other.auditLog.length === this.auditLog.length; }
}
class SavingsAccount extends Account {
  addInterest(rate: number) { this.balance *= 1 + rate; } // protected OK
  // A subclass may make a protected member public by redeclaring it.
}
// Escape hatch that shows `private` is soft: bracket access is allowed.
const acct = new Account("a1", "1234");
acct["auditLog"]; // compiles! — `#pin` would not be reachable at all

// ============================================================
// SECTION 8: STATIC MEMBERS AND STATIC BLOCKS
// ============================================================
class IdGenerator {
  static #next = 1;
  static prefix = "ID";
  static {
    // Static initialization block (ES2022): runs once, has access to privates.
    IdGenerator.#next = 1000;
  }
  static next() { return `${IdGenerator.prefix}-${IdGenerator.#next++}`; }
}
// Static names like `name`, `length`, `call` conflict with Function
// properties and are errors. Classes can't be generic over statics:
// `static default: T` is an error — statics exist once, not per T.

// ============================================================
// SECTION 9: PARAMETER PROPERTIES (emits code!)
// ============================================================
class Params {
  // Declares AND assigns fields from constructor params in one go.
  constructor(public readonly x: number, protected y: number, private z: number) {}
  sum() { return this.x + this.y + this.z; }
}
// Parameter properties generate `this.x = x` in the output. They're
// NOT erasable — Node's built-in type stripping rejects them, and TS
// 5.8's `erasableSyntaxOnly` flag reports them as errors. Codebases
// targeting `node file.ts` should use explicit fields instead.

// ============================================================
// SECTION 10: `this` AT RUNTIME, `this` TYPES, this-based guards
// ============================================================
class Counter {
  count = 0;
  // Arrow-function FIELD: `this` captured at construction; safe as a callback.
  // Cost: one function per instance, and subclasses can't call super.increment.
  increment = () => { this.count++; };
  // Method with `this` parameter: compile error if called unbound.
  reset(this: Counter) { this.count = 0; }
}
const c = new Counter();
const inc = c.increment; inc(); // fine
// const rst = c.reset; rst();  // error: 'this' context of type 'void' not assignable

// Polymorphic `this` type — fluent APIs that keep the subclass type.
class QueryBuilder {
  protected parts: string[] = [];
  where(cond: string): this { this.parts.push(`WHERE ${cond}`); return this; }
  build() { return this.parts.join(" "); }
}
class PagedQueryBuilder extends QueryBuilder {
  limit(n: number): this { this.parts.push(`LIMIT ${n}`); return this; }
}
new PagedQueryBuilder().where("a = 1").limit(10).build(); // limit still available after where

// `this is T` guards on methods
class FileSystemObject {
  isFile(): this is FileRep { return this instanceof FileRep; }
}
class FileRep extends FileSystemObject { constructor(public content: string) { super(); } }

// ============================================================
// SECTION 11: ABSTRACT CLASSES
// ============================================================
abstract class Shape {
  abstract area(): number;            // no implementation
  describe() { return `area=${this.area().toFixed(2)}`; } // concrete, uses abstract
}
class Sq extends Shape { constructor(private s: number) { super(); } area() { return this.s ** 2; } }
// new Shape();  // error: cannot create an instance of an abstract class

// Accepting "any concrete subclass constructor":
function build(ctor: new () => Shape) { return new ctor(); }
// abstract construct signature — accepts abstract classes too (for mixins, L06):
type AbstractCtor<T> = abstract new (...args: any[]) => T;
const shapeCtor: AbstractCtor<Shape> = Shape;

// ============================================================
// SECTION 12: CLASSES ARE STRUCTURAL
// ============================================================
class P1 { x = 0; y = 0 }
class P2 { x = 0; y = 0 }
const p: P1 = new P2(); // OK — identical shapes
class Empty {}
function fn(x: Empty) { return x; }
fn({ anything: true }); fn(42); // anything non-nullish fits an empty class!
// A private or protected member makes a class NOMINAL-ish: only
// instances from the same declaration are compatible.

// ============================================================
// SECTION 13: ENUMS
// ============================================================
// Numeric enum — auto-increments; generates a reverse mapping object.
enum Direction { Up = 1, Down, Left, Right } // Down=2, ...
Direction[2];        // "Down" — reverse mapping (numeric enums only)

// String enum — no reverse mapping; each member must be initialised.
enum LogLevel { Error = "ERROR", Warn = "WARN", Info = "INFO" }

// Computed and constant members:
enum FileAccess { None = 0, Read = 1 << 1, Write = 1 << 2, ReadWrite = Read | Write }

// Enums at compile time: `keyof typeof LogLevel` → "Error" | "Warn" | "Info"
type LevelKey = keyof typeof LogLevel;

// const enum — fully inlined, no runtime object. Fine inside an app
// compiled solely by tsc; hazardous for libraries and isolatedModules.
const enum Flags { A = 1, B = 2 }
const f = Flags.A | Flags.B; // compiled to `1 | 2`

// `declare enum` — ambient, describes an enum that exists elsewhere.

// THE MODERN ALTERNATIVE — erasable, tree-shakeable, plain JS at runtime:
const Status = { Active: "active", Suspended: "suspended" } as const;
type Status = (typeof Status)[keyof typeof Status];
function setStatus(s: Status) { return s; }
setStatus(Status.Active); setStatus("suspended"); // literals also accepted (enums reject them)
// Since TS 5.0 all enums are "union enums"; numeric enums now error on
// out-of-range literal assignment (`const d: Direction = 99` → error).

// ============================================================
// SECTION 14: SYMBOLS
// ============================================================
const sym1 = Symbol("key");
const sym2 = Symbol("key");
// sym1 === sym2;  // TS error 2367 "no overlap": each `const x = Symbol()`
//                 // gets its OWN unique symbol type — the checker knows they differ.
(sym1 as symbol) === sym2; // false at runtime — every Symbol() is unique

// `unique symbol` — a subtype of symbol tied to one declaration;
// only allowed on const declarations and readonly static properties.
const MetaKey: unique symbol = Symbol("meta");
interface Tagged { [MetaKey]: string }
const tagged: Tagged = { [MetaKey]: "v1" };

// Well-known symbols customise built-in behaviour:
//   Symbol.iterator, Symbol.asyncIterator, Symbol.hasInstance,
//   Symbol.toPrimitive, Symbol.toStringTag, Symbol.dispose (TS 5.2 `using`)
class Money {
  constructor(private cents: number) {}
  [Symbol.toPrimitive](hint: string) { return hint === "number" ? this.cents / 100 : `$${(this.cents / 100).toFixed(2)}`; }
  get [Symbol.toStringTag]() { return "Money"; }
}

// Explicit resource management (TS 5.2, `using` / `await using`):
class TempFile implements Disposable {
  constructor(public path: string) {}
  [Symbol.dispose]() { console.log(`deleted ${this.path}`); }
}
function useTemp() {
  using tmp = new TempFile("/tmp/x"); // disposed automatically at block exit, even on throw
  return tmp.path;
}

// ============================================================
// SECTION 15: ITERATORS AND GENERATORS
// ============================================================
// An object is ITERABLE if it has [Symbol.iterator]() returning an Iterator.
class Range implements Iterable<number> {
  constructor(private start: number, private end: number) {}
  *[Symbol.iterator](): Generator<number, void, undefined> {
    for (let i = this.start; i < this.end; i++) yield i;
  }
}
for (const n of new Range(0, 3)) console.log(n); // 0 1 2
const asArray = [...new Range(5, 8)];            // [5, 6, 7]

// Generator<Yield, Return, Next> — the three type parameters.
function* conversation(): Generator<string, number, string> {
  const name = yield "What's your name?"; // name: string (what .next(x) sends in)
  yield `Hello ${name}`;
  return 42;                              // Return type
}
const conv = conversation();
conv.next(); conv.next("Ada");

// TS 5.6: IteratorObject / BuiltinIteratorReturn and ES2025 iterator
// helpers (`.map`, `.filter`, `.take` directly on iterators; target es2025):
//   new Range(0, 100)[Symbol.iterator]().filter(n => n % 2 === 0).take(3).toArray()

// for..of vs for..in: for..of iterates VALUES via Symbol.iterator;
// for..in iterates enumerable KEYS (strings) — never use for..in on arrays.

// Async iteration: Symbol.asyncIterator + for await..of.
async function* paginate<T>(fetchPage: (cursor: number) => Promise<{ items: T[]; next?: number }>) {
  let cursor: number | undefined = 0;
  while (cursor !== undefined) {
    const page: { items: T[]; next?: number } = await fetchPage(cursor);
    yield* page.items;
    cursor = page.next;
  }
}

// ============================================================
// SECTION 16: END-TO-END — INVENTORY REPOSITORY
// ============================================================
interface Product { readonly sku: string; name: string; stock: number }

abstract class Repository<T, K extends keyof T> {
  protected readonly items = new Map<T[K], T>();
  constructor(protected readonly key: K) {}
  abstract validate(item: T): void;
  save(item: T): this {
    this.validate(item);
    this.items.set(item[this.key], item);
    return this;
  }
  get(id: T[K]): T {
    const found = this.items.get(id);
    if (!found) throw new NotFoundError(String(id));
    return found;
  }
  *[Symbol.iterator](): Generator<T> { yield* this.items.values(); }
}

class ProductRepo extends Repository<Product, "sku"> {
  constructor() { super("sku"); }
  validate(p: Product) { if (p.stock < 0) throw new RangeError(`negative stock for ${p.sku}`); }
  lowStock(threshold: number): Product[] { return [...this].filter((p) => p.stock < threshold); }
}

const repo = new ProductRepo()
  .save({ sku: "A1", name: "Widget", stock: 3 })
  .save({ sku: "B2", name: "Gadget", stock: 40 });

async function main() {
  const pages: Record<number, { items: string[]; next?: number }> = {
    0: { items: ["a", "b"], next: 1 },
    1: { items: ["c"] },
  };
  const all: string[] = [];
  for await (const item of paginate(async (c) => pages[c]!)) all.push(item);
  console.log(all); // ["a", "b", "c"]
}

console.log(repo.lowStock(10).map((p) => p.name)); // ["Widget"]
try { repo.get("ZZ"); } catch (e) { if (e instanceof NotFoundError) console.log(e.message, e.resource); }
console.log(paint({ shape: { kind: "circle" }, createdBy: "me" }), ro.age, h, scores, doStuff(["q"]),
  new Point(1, 2), t.celsius, new MyClass(), new Sonar().ping(), new NameChecker().check("OK"),
  new Dog().woof(2), acct.verify("1234"), IdGenerator.next(), new Params(1, 2, 3).sum(), c.count,
  new FileRep("x").isFile(), new Sq(2).describe(), shapeCtor.name, p, fn({}), Direction.Up,
  LogLevel.Warn, FileAccess.ReadWrite, f, setStatus("active"), tagged[MetaKey], `${new Money(150)}`,
  +new Money(150), useTemp(), asArray, new SavingsAccount("s", "0"), build);
void main();

export type { AddressWithUnit, ColorfulCircle, ColorfulCircle2, OrNull, OneOrMany, LevelKey, Pingable, StringArray, Dictionary };
