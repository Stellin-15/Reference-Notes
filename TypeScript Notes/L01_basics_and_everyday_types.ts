// ============================================================
// L01: TypeScript Basics & Everyday Types
// ============================================================
// WHAT: The foundation of the TypeScript Handbook — "The Basics",
//       "Everyday Types", "Variable Declaration" and "Type
//       Inference" chapters. Primitives, arrays, tuples, objects,
//       unions, aliases vs interfaces, literal types, null and
//       undefined, any/unknown/never/void, inference rules, and
//       how a .ts file becomes .js.
// WHY:  Every later lesson (generics, conditional types, .d.ts
//       authoring) is built from these pieces. Most real-world
//       TypeScript bugs come from misunderstanding THIS layer:
//       widening, optional vs undefined, `any` leaking, and the
//       fact that types are erased at runtime.
// LEVEL: Foundation
// SOURCE: typescriptlang.org/docs/handbook — The Basics,
//         Everyday Types, Variable Declaration, Type Inference
//         (checked against TypeScript 7.0, Oct 2026)
// ============================================================
/*
CONCEPT OVERVIEW:
    TypeScript = JavaScript + a static type checker. The checker
    runs at compile time and then ERASES every type annotation:
    the emitted JavaScript contains no types at all. So:
      - Types never change runtime behaviour (with a few
        exceptions that emit code: enums, namespaces, parameter
        properties, decorators — see L03/L05/L06).
      - You cannot ask "is x a User?" at runtime using the type
        `User`. You check the VALUE's shape (L02 narrowing) or
        validate with a runtime schema library (L08).
    The type system is STRUCTURAL: compatibility is decided by
    shape, not by name.

PRODUCTION USE CASE:
    Modelling an order-management domain: typed order records,
    tuples for CSV rows, literal-union status fields, and an
    inferred config object. This is how a typical Node backend
    or React app declares its core data.

COMMON MISTAKES:
    1. Annotating everything (`const n: number = 5`). Let
       inference work; annotate function parameters, public API
       return types, and empty containers.
    2. Using `any` to silence an error. It spreads: anything
       touched by `any` becomes `any`. Use `unknown` and narrow.
    3. Using the boxed types `String`, `Number`, `Boolean`,
       `Object`. Always use lowercase `string`, `number`,
       `boolean`, `object`.
    4. Forgetting that `let x = "a"` has type `string` but
       `const x = "a"` has type `"a"` (widening), then being
       surprised when a literal-union parameter rejects it.
    5. Treating optional (`x?: T`) and `x: T | undefined` as the
       same thing. With `exactOptionalPropertyTypes` they differ.
    6. Assuming a type assertion (`as User`) validates data. It
       does not — it is a promise to the compiler, unchecked.
*/

// ============================================================
// SECTION 1: THE BASICS — STATIC CHECKING
// ============================================================
// JavaScript reports `undefined is not a function` only when the
// line RUNS. TypeScript reports it when you WRITE it.
//
//   const message = "hello";
//   message();          // error TS2349: This expression is not callable.
//
// It also catches non-exception bugs that plain JS silently allows:
//
//   const user = { name: "Ada", age: 36 };
//   user.location;      // error TS2339: Property 'location' does not exist
//   Math.random < 0.5   // error: Operator '<' cannot be applied (forgot to call it)
//
// `tsc` (the compiler) both type-checks and emits JS. With errors,
// tsc STILL emits by default (`noEmitOnError: false`), because the
// type system is a linter-like layer over JS — set
// `noEmitOnError: true` in CI builds where broken output must not ship.

// Explicit annotation on a function parameter — the main place
// annotations are required, because parameters can't be inferred
// from nowhere.
function greet(person: string, date: Date): string {
  // Template literal; `date.toDateString()` is known to exist on Date.
  return `Hello ${person}, today is ${date.toDateString()}!`;
}

// greet("Ada", Date());   // error: Date() returns a string, not a Date
greet("Ada", new Date()); // OK

// ============================================================
// SECTION 2: PRIMITIVE TYPES
// ============================================================
// JavaScript has 7 primitives; TypeScript gives each a type.
const count: number = 42;            // all numbers are IEEE-754 doubles; no int/float split
const big: bigint = 9_007_199_254_740_993n; // arbitrary precision integers (target ES2020+)
const label: string = "order";       // UTF-16 strings
const isPaid: boolean = true;
const nothing: null = null;
const missing: undefined = undefined;
const tag: symbol = Symbol("tag");   // unique identity; see L03 for `unique symbol`

// In real code you'd drop every annotation above — inference
// gives the same (or narrower) types. They're written out here
// only to show the names.

// ============================================================
// SECTION 3: ARRAYS AND TUPLES
// ============================================================
const ids: number[] = [1, 2, 3];          // shorthand
const names: Array<string> = ["a", "b"];  // generic form — identical meaning
const frozen: readonly number[] = [1, 2]; // no push/pop/assignment
// frozen.push(3);  // error: Property 'push' does not exist on type 'readonly number[]'

// A tuple is an array with a fixed length and per-position types.
type CsvRow = [orderId: string, quantity: number, price: number]; // labelled elements (TS 4.0+)
const row: CsvRow = ["ORD-1", 3, 19.99];
const [orderId, qty] = row; // destructuring keeps per-position types

// Optional and rest elements in tuples.
type Point = [x: number, y: number, z?: number];
type LogLine = [level: "info" | "error", ...parts: string[]];
const line: LogLine = ["info", "server", "started"];

// `as const` turns an array literal into a readonly tuple of literals.
const directions = ["north", "south"] as const; // readonly ["north", "south"]
type Direction = (typeof directions)[number];    // "north" | "south" — index with `number`

// ============================================================
// SECTION 4: OBJECT TYPES
// ============================================================
// Inline object type. Separate members with `,` or `;`.
function printCoord(pt: { x: number; y: number; label?: string }) {
  // `label` is optional: its type inside is `string | undefined`.
  console.log(pt.x, pt.y, pt.label?.toUpperCase()); // optional chaining required
}
printCoord({ x: 3, y: 7 });

// EXCESS PROPERTY CHECKING: a FRESH object literal passed directly
// is checked for extra keys — a typo guard.
// printCoord({ x: 1, y: 2, lable: "a" }); // error: 'lable' does not exist
// But a variable with extra properties is allowed (structural typing):
const withExtra = { x: 1, y: 2, color: "red" };
printCoord(withExtra); // OK — has at least x and y

// ============================================================
// SECTION 5: UNION TYPES
// ============================================================
// A union `A | B` is a value that is EITHER type. You may only use
// operations valid for EVERY member until you narrow (L02).
function formatId(id: number | string): string {
  // id.toUpperCase();  // error: not on number
  if (typeof id === "string") {
    return id.toUpperCase(); // narrowed to string
  }
  return id.toFixed(0);       // narrowed to number
}

// Methods common to all members are allowed without narrowing.
function firstThree(x: number[] | string) {
  return x.slice(0, 3); // both arrays and strings have slice
}

// ============================================================
// SECTION 6: TYPE ALIASES VS INTERFACES
// ============================================================
// A type alias names ANY type: unions, tuples, primitives, objects.
type OrderStatus = "pending" | "paid" | "shipped" | "cancelled";
type Money = { amount: number; currency: "USD" | "EUR" | "GBP" };

// An interface names an OBJECT shape only.
interface Order {
  readonly id: string;       // can't be reassigned after creation
  status: OrderStatus;
  total: Money;
  notes?: string;            // optional
}

// Extending: interfaces use `extends`, aliases use intersection `&`.
interface ExpressOrder extends Order {
  deliverBy: Date;
}
type GiftOrder = Order & { giftMessage: string };

// KEY DIFFERENCES (handbook guidance):
//   - Interfaces can be RE-OPENED (declaration merging, L05).
//     Two `interface Window {}` blocks merge. Aliases cannot.
//   - Aliases can name unions, tuples, mapped & conditional types.
//   - Interface `extends` reports conflicts as errors; `&` silently
//     produces `never` for conflicting property types.
//   - Error messages and hover show interface names consistently,
//     and the checker caches interface relationships — for big
//     object hierarchies interfaces are slightly cheaper to check.
// Handbook rule of thumb: use `interface` until you need a
// feature only `type` has.

// ============================================================
// SECTION 7: LITERAL TYPES AND WIDENING
// ============================================================
let mutableKind = "card";      // type: string  (let can change → widened)
const fixedKind = "card";      // type: "card"  (const can't change → literal)

function charge(method: "card" | "bank") { return method; }
charge(fixedKind);   // OK
// charge(mutableKind); // error: string not assignable to "card" | "bank"

// The classic object-literal trap: properties are mutable, so they widen.
const req = { url: "https://x.test", method: "GET" }; // method: string
function send(url: string, method: "GET" | "POST") { return [url, method]; }
// send(req.url, req.method);  // error: string is not "GET" | "POST"
// Fix 1: assert at the use site
send(req.url, req.method as "GET");
// Fix 2: `as const` on the object — all properties become readonly literals
const req2 = { url: "https://x.test", method: "GET" } as const;
send(req2.url, req2.method);
// Fix 3: annotate the object with a type that has the literal union.

// Numeric and boolean literals work the same way.
type DiceRoll = 1 | 2 | 3 | 4 | 5 | 6;
type Truthy = true; // `boolean` is literally the union `true | false`

// ============================================================
// SECTION 8: NULL, UNDEFINED, AND strictNullChecks
// ============================================================
// With `strictNullChecks` (part of `strict`, which is ON by default
// since TS 6.0) null/undefined are NOT members of every type.
function lookup(map: Map<string, number>, key: string): number | undefined {
  return map.get(key);
}
const found = lookup(new Map([["a", 1]]), "a");
// found.toFixed();       // error: 'found' is possibly 'undefined'
found?.toFixed();         // optional chaining → undefined if missing
const safe = found ?? 0;  // nullish coalescing — only null/undefined fall back (not 0 or "")

// Non-null assertion `!` — tells the compiler "trust me, not null".
// Unchecked at runtime; use only when you KNOW (e.g. right after a check
// the compiler can't follow).
const el = (globalThis as any).document?.getElementById("app");
// el!.textContent = "x";

// ============================================================
// SECTION 9: any, unknown, never, void, object
// ============================================================
// any      — opts out of checking. Everything goes; nothing is caught.
// unknown  — top type. Anything can be assigned TO it; you can do
//            nothing WITH it until you narrow.
// never    — bottom type. No value has it: functions that throw or
//            loop forever, impossible union branches (exhaustiveness).
// void     — a function's "no meaningful return" marker.
// object   — any non-primitive (not string/number/...). Distinct from
//            `Object` (anything with Object's methods — nearly everything)
//            and `{}` (any non-null/undefined value).

function parseJson(text: string): unknown {
  return JSON.parse(text); // JSON.parse returns any; widen to unknown at the boundary
}
const parsed = parseJson('{"id": 1}');
// parsed.id;  // error: 'parsed' is of type 'unknown'
if (typeof parsed === "object" && parsed !== null && "id" in parsed) {
  console.log(parsed.id); // narrowed: object & Record<"id", unknown>
}

function fail(msg: string): never {
  throw new Error(msg); // never returns normally
}

// `noImplicitAny` (in strict) errors when TS would silently infer any,
// e.g. an unannotated parameter: function f(x) {} → error TS7006.

// ============================================================
// SECTION 10: TYPE ASSERTIONS
// ============================================================
// `expr as T` — allowed only if T is "sufficiently related" (one
// assignable to the other). Prevents absurd casts like string→number.
const raw: unknown = { id: "u1" };
const asObj = raw as { id: string };
// const nonsense = "hello" as number;  // error: neither type sufficiently overlaps
// Escape hatch (rarely justified): "hello" as unknown as number
// Angle-bracket form `<T>expr` is equivalent but invalid in .tsx files.

// ============================================================
// SECTION 11: VARIABLE DECLARATION (let / const / var)
// ============================================================
// Handbook "Variable Declaration" chapter — JS semantics, TS-checked.
//   var   — function-scoped, hoisted, re-declarable. Avoid.
//   let   — block-scoped, temporal dead zone before declaration.
//   const — block-scoped, binding can't be reassigned (object
//           contents CAN still change — use readonly/as const for that).
// The classic closure bug `var` causes:
//   for (var i = 0; i < 3; i++) setTimeout(() => console.log(i)); // 3,3,3
//   for (let i = 0; i < 3; i++) setTimeout(() => console.log(i)); // 0,1,2
// Destructuring with defaults and types:
function connect({ host = "localhost", port = 5432 }: { host?: string; port?: number } = {}) {
  return `${host}:${port}`;
}
connect({ port: 6543 });

// ============================================================
// SECTION 12: TYPE INFERENCE
// ============================================================
// Handbook "Type Inference" chapter.
// 1. Basic: initializers, default params, return statements.
let retries = 3;                  // number
function double(n: number) { return n * 2; } // return type inferred as number

// 2. BEST COMMON TYPE: for array literals TS picks a union of candidates.
const mixed = [0, 1, null];        // (number | null)[]
const animals = [new Map(), new Set()]; // (Map<any, any> | Set<any>)[]

// 3. CONTEXTUAL TYPING: the expected type flows INTO an expression.
//    The callback parameter types come from the array element type.
const prices = [10, 20, 30];
const withTax = prices.map((p) => p * 1.2); // p: number, no annotation needed
// Event handler example: window.onmousedown = (e) => e.button  — e is MouseEvent

// 4. Empty containers need annotations (otherwise never[] / any[]).
const queue: string[] = [];

// When to annotate return types explicitly:
//   - Exported/public functions (stable API, faster checking in big
//     projects, required for `isolatedDeclarations`, L07).
//   - Recursive functions (inference can't see the end).
//   - When you want the compiler to verify every path matches.

// ============================================================
// SECTION 13: ENUM PREVIEW AND LESS COMMON PRIMITIVES
// ============================================================
// Enums emit runtime code and are covered in L03. Most modern code
// prefers a literal union + `as const` object (zero runtime cost
// beyond the object itself, works with `erasableSyntaxOnly`).
const Currency = { USD: "USD", EUR: "EUR" } as const;
type Currency = (typeof Currency)[keyof typeof Currency]; // "USD" | "EUR"

// ============================================================
// SECTION 14: END-TO-END EXAMPLE — ORDER INTAKE
// ============================================================
interface LineItem {
  sku: string;
  quantity: number;
  unitPrice: number;
}

interface NewOrder {
  readonly id: string;
  status: OrderStatus;
  items: readonly LineItem[];
  currency: Currency;
  couponCode?: string;
}

// Parse a CSV row (untrusted input) into a typed LineItem.
function parseLineItem(cols: readonly string[]): LineItem {
  const [sku, q, p] = cols;
  if (sku === undefined || q === undefined || p === undefined) {
    // `noUncheckedIndexedAccess` would make destructured cols string | undefined;
    // checking keeps this correct under every strictness setting.
    return fail(`bad row: ${cols.join(",")}`);
  }
  const quantity = Number(q);
  const unitPrice = Number(p);
  if (!Number.isFinite(quantity) || !Number.isFinite(unitPrice)) {
    return fail(`non-numeric row: ${cols.join(",")}`);
  }
  return { sku, quantity, unitPrice };
}

function orderTotal(order: NewOrder): Money {
  // reduce with an explicit initial value: accumulator type = number
  const amount = order.items.reduce((sum, item) => sum + item.quantity * item.unitPrice, 0);
  const discounted = order.couponCode === "SAVE10" ? amount * 0.9 : amount;
  // Round to cents — floating point (see SECTION 2): money should be
  // integer minor units in real systems; shown simply here.
  return { amount: Math.round(discounted * 100) / 100, currency: order.currency };
}

const order: NewOrder = {
  id: "ORD-42",
  status: "pending",
  currency: Currency.USD,
  items: [
    parseLineItem(["SKU-1", "2", "9.99"]),
    parseLineItem(["SKU-2", "1", "24.50"]),
  ],
  couponCode: "SAVE10",
};

console.log(greet("Ada", new Date()), formatId(7), firstThree("abcdef"));
console.log(orderTotal(order)); // { amount: 40.03, currency: "USD" }
console.log(connect(), double(retries), withTax, mixed, animals.length, queue, line, row, orderId, qty);
console.log(count, big, label, isPaid, nothing, missing, tag.description, ids, names, frozen, safe, asObj, el);

// Unused declarations kept for illustration; reference them so the
// file compiles cleanly under noUnusedLocals.
export type { Point, Direction, ExpressOrder, GiftOrder, DiceRoll, Truthy, Order };
export { lookup, mutableKind, charge };
