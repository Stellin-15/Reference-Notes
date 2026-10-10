// ============================================================
// L02: Narrowing & Functions
// ============================================================
// WHAT: Handbook chapters "Narrowing" and "More on Functions".
//       Control-flow analysis, every narrowing construct
//       (typeof, truthiness, equality, in, instanceof,
//       assignment, type predicates, assertion functions,
//       discriminated unions, exhaustiveness with never), then
//       function types: call/construct signatures, generic
//       functions and constraints, optional params, overloads,
//       `this` typing, rest/spread, void semantics.
// WHY:  Narrowing is how TypeScript stays sound over unions —
//       it's the mechanism behind every `if` you write. Function
//       typing is where library APIs live; getting overloads
//       and generics right is the difference between a helpful
//       API and one that forces callers into `as` casts.
// LEVEL: Foundation → Intermediate
// SOURCE: typescriptlang.org/docs/handbook/2/narrowing.html,
//         .../2/functions.html (checked against TS 7.0, Oct 2026)
// ============================================================
/*
CONCEPT OVERVIEW:
    The checker walks your code like an interpreter, tracking the
    DECLARED type of each variable and its NARROWED type at each
    point (control-flow analysis). Every check — `typeof x ===
    "string"`, `"id" in x`, `x instanceof Date`, `x.kind ===
    "circle"` — refines the narrowed type for the branch where
    the check passed, and removes those members in the else.

PRODUCTION USE CASE:
    A payment webhook handler: an incoming event union is
    narrowed by its `type` tag, each branch handled with full
    type safety, and an exhaustiveness check guarantees that
    adding a new event type to the union breaks the build until
    it's handled.

COMMON MISTAKES:
    1. `typeof x === "object"` — null is also "object". Check
       `x !== null` too.
    2. Truthiness checks on numbers/strings: `if (count)` drops 0,
       `if (name)` drops "". Use `!== undefined` when 0/"" are valid.
    3. Narrowing a property, then calling a function: TS resets
       property narrowing after calls that could mutate it (it does
       keep narrowing of `const` locals).
    4. Writing a type predicate (`x is Foo`) that lies — TS trusts
       it blindly; a wrong predicate is as bad as `as`.
    5. Overloads whose implementation signature is visible — it
       isn't; callers only see the overload signatures.
    6. Using `Function` as a type — it's the untyped `any` of
       callables. Write the actual signature.
*/

// ============================================================
// SECTION 1: typeof GUARDS
// ============================================================
// typeof returns: "string" "number" "bigint" "boolean" "symbol"
//                 "undefined" "object" "function"
function padLeft(padding: number | string, input: string): string {
  if (typeof padding === "number") {
    return " ".repeat(padding) + input; // padding: number
  }
  return padding + input;               // padding: string
}

function printAll(strs: string | string[] | null) {
  if (typeof strs === "object") {
    // strs: string[] | null  ← null slipped through! typeof null === "object"
    if (strs !== null) {
      for (const s of strs) console.log(s);
    }
  } else if (typeof strs === "string") {
    console.log(strs);
  }
}

// ============================================================
// SECTION 2: TRUTHINESS AND EQUALITY NARROWING
// ============================================================
// Falsy values: 0, NaN, "", 0n, null, undefined, false.
function describe(n: number | undefined) {
  if (n) return `n=${n}`;          // n: number, but 0 lands in else!
  return "no number (or zero!)";
}

// Equality narrowing: === against a literal, or between two values.
function compare(x: string | number, y: string | boolean) {
  if (x === y) {
    // Only common type is string → both narrowed to string.
    return x.toUpperCase() + y.toLowerCase();
  }
  return null;
}

// `== null` catches both null and undefined (the one good use of ==).
function cleanup(value: string | null | undefined) {
  if (value != null) return value.trim(); // value: string
  return "";
}

// ============================================================
// SECTION 3: THE `in` OPERATOR
// ============================================================
type Fish = { swim: () => void; name: string };
type Bird = { fly: () => void; name: string };
type Human = { swim?: () => void; fly?: () => void; name: string };

function move(animal: Fish | Bird | Human) {
  if ("swim" in animal) {
    // Fish | Human — Human has optional swim, so it stays in both branches
    animal.swim?.();
  } else {
    // Bird | Human
    animal.fly?.();
  }
}

// ============================================================
// SECTION 4: instanceof AND ASSIGNMENT NARROWING
// ============================================================
function logValue(x: Date | string) {
  if (x instanceof Date) return x.toISOString(); // checks prototype chain
  return x.toUpperCase();
}

// Assignment: TS narrows to the assigned value's type, but the
// DECLARED type still bounds future assignments.
let id: string | number = Math.random() < 0.5 ? 1 : "a";
id = 42;           // narrowed: number
id.toFixed();      // OK
id = "abc";        // allowed — declared type is string | number
id.toUpperCase();  // narrowed: string

// ============================================================
// SECTION 5: CONTROL-FLOW ANALYSIS
// ============================================================
// Narrowing follows returns, throws, breaks, and reassignments.
function example() {
  let x: string | number | boolean;
  x = Math.random() < 0.5;   // boolean
  if (Math.random() < 0.5) {
    x = "hello";             // string
  } else {
    x = 100;                 // number
  }
  return x;                  // string | number (boolean was overwritten on both paths)
}

// Since TS 4.4, aliased conditions narrow too:
function aliased(input: unknown) {
  const isStr = typeof input === "string";
  if (isStr) return input.length; // input: string
  return 0;
}

// Since TS 5.4, narrowing is preserved in closures created AFTER
// the last assignment to a `let`:
function closures(url: string | URL) {
  if (typeof url === "string") url = new URL(url);
  // url: URL here, and the arrow function keeps that narrowing
  return ["a", "b"].map((p) => url.pathname + p);
}

// ============================================================
// SECTION 6: TYPE PREDICATES (user-defined type guards)
// ============================================================
function isFish(pet: Fish | Bird): pet is Fish {
  return (pet as Fish).swim !== undefined;
}
function getPet(): Fish | Bird {
  return { name: "nemo", swim() {} };
}
const pet = getPet();
if (isFish(pet)) pet.swim(); else pet.fly();

// Predicates power .filter() narrowing:
const zoo: (Fish | Bird)[] = [getPet(), getPet()];
const fishes: Fish[] = zoo.filter(isFish);

// TS 5.5+: INFERRED type predicates — simple arrow functions get a
// predicate automatically, so this narrows without annotation:
const mixedValues = [1, null, 2, undefined];
const nums = mixedValues.filter((v) => v !== undefined && v !== null); // number[]

// ============================================================
// SECTION 7: ASSERTION FUNCTIONS
// ============================================================
// `asserts cond` / `asserts x is T` — narrow by throwing on failure.
function assert(condition: unknown, msg?: string): asserts condition {
  if (!condition) throw new Error(msg ?? "assertion failed");
}
function assertIsString(val: unknown): asserts val is string {
  if (typeof val !== "string") throw new TypeError("not a string");
}
function shout(v: unknown) {
  assertIsString(v);
  return v.toUpperCase(); // v: string from here on
}
// Note: assertion functions must be called through an explicitly
// typed reference (a declared function, or a const with an
// annotated function type) — otherwise error TS2775.

// ============================================================
// SECTION 8: DISCRIMINATED UNIONS & EXHAUSTIVENESS
// ============================================================
// Each member shares a literal "tag" property. Checking the tag
// narrows to exactly one member.
type Shape =
  | { kind: "circle"; radius: number }
  | { kind: "square"; side: number }
  | { kind: "rect"; width: number; height: number };

function assertNever(x: never): never {
  // Reaching here at compile time = an unhandled union member.
  throw new Error(`Unhandled case: ${JSON.stringify(x)}`);
}

function area(s: Shape): number {
  switch (s.kind) {
    case "circle": return Math.PI * s.radius ** 2;
    case "square": return s.side ** 2;
    case "rect":   return s.width * s.height;
    default:       return assertNever(s); // s: never — add a member and this errors
  }
}

// Destructured discriminants narrow too (TS 4.6+):
type Action = { type: "add"; payload: number } | { type: "reset"; payload: undefined };
function reduce(state: number, { type, payload }: Action) {
  if (type === "add") return state + payload; // payload: number
  return 0;
}

// ============================================================
// SECTION 9: FUNCTION TYPE EXPRESSIONS & CALL SIGNATURES
// ============================================================
type Formatter = (value: number) => string; // parameter NAME is required
const usd: Formatter = (v) => `$${v.toFixed(2)}`;

// A call signature in an object type — for functions that also
// have properties.
type DescribableFn = {
  description: string;
  (arg: number): boolean; // note `:` not `=>`
};
function runIt(fn: DescribableFn) {
  return `${fn.description} returned ${fn(6)}`;
}
const isEven = Object.assign((n: number) => n % 2 === 0, { description: "isEven" });
runIt(isEven);

// Construct signatures: callable with `new`.
type Ctor<T> = new (...args: any[]) => T;
function create<T>(C: Ctor<T>): T { return new C(); }
create(Date);

// Both call and construct (like the Date global):
interface CallOrConstruct {
  (n?: number): string;
  new (s: string): Date;
}

// ============================================================
// SECTION 10: GENERIC FUNCTIONS
// ============================================================
// Relate input and output types.
function firstElement<T>(arr: readonly T[]): T | undefined {
  return arr[0];
}
const s1 = firstElement(["a", "b"]); // T inferred as string

function mapArray<In, Out>(arr: readonly In[], fn: (x: In) => Out): Out[] {
  return arr.map(fn);
}
const lengths = mapArray(["aa", "b"], (s) => s.length); // In=string, Out=number

// CONSTRAINTS limit what T may be.
function longest<T extends { length: number }>(a: T, b: T): T {
  return a.length >= b.length ? a : b;
}
longest([1, 2], [3]);     // T = number[]
longest("alice", "bob");  // T = "alice" | "bob" → string
// longest(10, 100);      // error: number has no length

// A classic mistake — returning a NEW object that only satisfies the constraint:
// function minLen<T extends { length: number }>(obj: T, min: number): T {
//   if (obj.length >= min) return obj;
//   return { length: min };   // error: { length } is not T (T may be string[]!)
// }

// Explicit type arguments when inference picks the wrong one:
function combine<T>(a: T[], b: T[]): T[] { return a.concat(b); }
const both = combine<string | number>([1, 2], ["x"]);

// `const` type parameters (TS 5.0) — infer literal types as if `as const`:
function routes<const T extends readonly string[]>(paths: T): T { return paths; }
const r = routes(["/home", "/about"]); // readonly ["/home", "/about"]

// HANDBOOK GUIDELINES for good generic functions:
//   1. Push type parameters down — constrain on T[], not on T extends any[].
//   2. Use fewer type parameters — if one doesn't relate two values, drop it.
//   3. A type parameter should appear at least twice; once = just use the constraint.

// ============================================================
// SECTION 11: OPTIONAL PARAMETERS & CALLBACKS
// ============================================================
function fixed(n: number, digits?: number) { return n.toFixed(digits); }
function withDefault(n: number, digits = 2) { return n.toFixed(digits); } // digits: number
fixed(1.234); withDefault(1.234, undefined); // explicit undefined → default applies

// Rule: NEVER mark callback parameters optional unless you'll
// call the callback without them. Callers can always pass a
// function with FEWER params — that's normal in JS.
function each<T>(arr: T[], cb: (item: T, index: number) => void) {
  arr.forEach((x, i) => cb(x, i));
}
each([1, 2], (x) => console.log(x)); // fine — ignoring index is allowed

// ============================================================
// SECTION 12: OVERLOADS
// ============================================================
// Overload signatures (visible to callers) + one implementation
// signature (not visible, must be compatible with all overloads).
function makeDate(timestamp: number): Date;
function makeDate(m: number, d: number, y: number): Date;
function makeDate(mOrTimestamp: number, d?: number, y?: number): Date {
  if (d !== undefined && y !== undefined) return new Date(y, mOrTimestamp, d);
  return new Date(mOrTimestamp);
}
makeDate(12345678);
makeDate(5, 5, 5);
// makeDate(1, 3);   // error: no overload expects 2 arguments

// Prefer UNION parameters over overloads when possible —
// overloads can't be called with a union argument:
function len(x: any[] | string) { return x.length; }
len(Math.random() > 0.5 ? "hello" : [0]); // works; overloaded version wouldn't

// ============================================================
// SECTION 13: `this` IN FUNCTIONS
// ============================================================
// Declare the expected `this` as a fake first parameter (erased in JS).
interface Db { filterUsers(filter: (this: User) => boolean): User[]; }
interface User { name: string; admin: boolean; }
const db: Db = {
  filterUsers(filter) {
    const all: User[] = [{ name: "a", admin: true }];
    return all.filter((u) => filter.call(u));
  },
};
// Must be a `function`, not an arrow — arrows capture outer `this`.
const admins = db.filterUsers(function (this: User) { return this.admin; });

// ============================================================
// SECTION 14: OTHER TYPES THAT MATTER WITH FUNCTIONS
// ============================================================
// void: a contextually-typed function returning void MAY return a
// value (it's ignored) — that's why this compiles:
const out: number[] = [];
[1, 2].forEach((v) => out.push(v)); // push returns number; forEach expects void
// But a function DECLARED `: void` may not return a value.

// object vs Object vs {} — see L01 §9.
// unknown for untyped callback results; never for functions that never return.
// Function (capital F) — has apply/call/bind but calling it returns any. Avoid.

// ============================================================
// SECTION 15: REST PARAMETERS, SPREAD, DESTRUCTURING
// ============================================================
function multiply(n: number, ...m: number[]) { return m.map((x) => n * x); }
multiply(10, 1, 2, 3);

// Spreading an array into a fixed-arity function needs a tuple:
const args = [8, 5] as const;
Math.atan2(...args); // OK — readonly [8, 5]
// const loose = [8, 5]; Math.atan2(...loose); // error: number[] may have any length

function sum({ a, b, c }: { a: number; b: number; c: number }) { return a + b + c; }

// Assignability of functions: parameters are checked BIVARIANTLY for
// method syntax and CONTRAVARIANTLY for function-property syntax
// under strictFunctionTypes — deep dive in L08.

// ============================================================
// SECTION 16: END-TO-END — TYPED WEBHOOK DISPATCH
// ============================================================
type PaymentEvent =
  | { type: "payment.succeeded"; id: string; amountCents: number }
  | { type: "payment.failed"; id: string; reason: string }
  | { type: "refund.created"; id: string; paymentId: string; amountCents: number };

// Map each event type to its handler, typed per member via
// Extract — a preview of L04's type manipulation.
type Handlers = {
  [K in PaymentEvent["type"]]: (e: Extract<PaymentEvent, { type: K }>) => string;
};

const handlers: Handlers = {
  "payment.succeeded": (e) => `credit ${e.amountCents}c for ${e.id}`,
  "payment.failed": (e) => `alert: ${e.id} failed (${e.reason})`,
  "refund.created": (e) => `debit ${e.amountCents}c, original ${e.paymentId}`,
};

function isPaymentEvent(x: unknown): x is PaymentEvent {
  // A real system validates every field (Zod, L08). Minimal check here.
  return typeof x === "object" && x !== null && "type" in x && typeof x.type === "string"
    && x.type in handlers && "id" in x;
}

function dispatch(e: PaymentEvent): string {
  switch (e.type) {
    case "payment.succeeded": return handlers[e.type](e);
    case "payment.failed":    return handlers[e.type](e);
    case "refund.created":    return handlers[e.type](e);
    default:                  return assertNever(e);
  }
}

function handleWebhook(body: string): string {
  const parsed: unknown = JSON.parse(body);
  assert(isPaymentEvent(parsed), "unrecognised webhook payload");
  return dispatch(parsed);
}

console.log(handleWebhook('{"type":"payment.failed","id":"pi_1","reason":"card_declined"}'));
console.log(padLeft(2, "x"), describe(0), compare("a", "a"), cleanup(" y "), logValue("z"),
  example(), aliased("abc"), closures("https://a.test/x"), fishes.length, nums, shout("hi"),
  area({ kind: "circle", radius: 1 }), reduce(1, { type: "add", payload: 2 }), usd(3),
  s1, lengths, both, r, admins, multiply(2, 3), sum({ a: 1, b: 2, c: 3 }), len("abc"));
printAll(["a"]); move({ name: "h" });

export type { CallOrConstruct };
export { create, longest, fixed, each, makeDate };
