// ============================================================
// L08: Type Compatibility, Soundness & Type-Safe Architecture
// ============================================================
// WHAT: Reference page "Type Compatibility" (structural
//       assignability, function parameter bivariance, optional
//       and rest params, enums, classes, generics, any/unknown/
//       never subtype table), variance in depth, the known
//       soundness holes, the "What's New" timeline 4.0 → 7.0, and
//       the architect-level capstone: closing the compile-time /
//       runtime gap with a schema library — built from scratch
//       here (a mini-Zod) so every inference trick is visible.
// WHY:  TypeScript is deliberately UNSOUND in places to stay
//       compatible with real JavaScript. Senior engineers know
//       exactly where the holes are, so they put runtime
//       validation at trust boundaries and design APIs where the
//       holes can't bite.
// LEVEL: Architect
// SOURCE: typescriptlang.org/docs/handbook/type-compatibility.html,
//         .../release-notes/* (4.0 – 6.0), TS 7.0 announcement,
//         zod.dev (design of schema inference)
// ============================================================
/*
CONCEPT OVERVIEW:
    "S is assignable to T" — the core relation. Rules:
      - Object types: S must have AT LEAST T's required members,
        each assignable (width subtyping); extra members are fine
        (except fresh object literals — excess property check).
      - Functions: parameter types compared contravariantly under
        strictFunctionTypes for function-type properties, but
        BIVARIANTLY for method-syntax members; fewer parameters
        is fine; return types covariant.
      - Generics: compared by their structure after substitution;
        an unused type parameter makes Box<string> ≡ Box<number>.
      - any: assignable to/from everything (except never).
        unknown: everything → unknown; unknown → only any/unknown.
        never: assignable to everything; nothing (but never) → never.

PRODUCTION USE CASE:
    An API gateway handler: incoming JSON is validated by a schema
    that ALSO produces the TypeScript type, so the type can never
    disagree with what was actually checked at runtime.

COMMON MISTAKES:
    1. Trusting array covariance: `Dog[]` is assignable to
       `Animal[]`, so pushing a Cat through the Animal[] alias
       corrupts the Dog array — a soundness hole by design.
    2. Defining callbacks with method syntax in interfaces you own
       (`onEvent(e: Event): void`) — you lose strict parameter
       checking. Use property syntax `onEvent: (e: Event) => void`.
    3. Casting `JSON.parse(x) as User` — the single most common
       source of production type lies.
    4. Writing types and validators separately (interface User +
       a hand-written isUser) — they drift. Derive one from the other.
    5. Exporting huge inferred types from library entry points —
       slow editor performance; annotate public API types.
*/

// ============================================================
// SECTION 1: STRUCTURAL ASSIGNABILITY
// ============================================================
interface Pet { name: string }
class Dog { name = "rex"; bark() { return "woof"; } }
let pet: Pet = new Dog();      // OK — Dog has `name`
const notPet = { name: "x", owner: "y" };
pet = notPet;                  // OK — extra properties ignored for non-fresh objects
// pet = { name: "x", owner: "y" }; // error — FRESH literal, excess property check

// Weak types (all-optional properties) require at least one overlap:
interface Opts { verbose?: boolean; color?: string }
// const o: Opts = { colour: "red" }; // error: no properties in common (weak type detection)

// ============================================================
// SECTION 2: COMPARING FUNCTIONS
// ============================================================
let x2 = (a: number) => 0;
let y2 = (b: number, s: string) => 0;
y2 = x2;     // OK — fewer parameters is fine (JS ignores extra args)
// x2 = y2;  // error — y2 needs a second argument x2's callers won't supply

// Return types: source must return at least what target promises.
let r1 = () => ({ name: "Alice" });
let r2 = () => ({ name: "Alice", location: "Seattle" });
r1 = r2;     // OK
// r2 = r1;  // error — missing location

// PARAMETER BIVARIANCE — the method-syntax hole:
interface Animal { name: string }
interface Cat extends Animal { meow(): void }
interface HandlerMethod { handle(a: Animal): void }          // method syntax → bivariant
interface HandlerProp { handle: (a: Animal) => void }        // property syntax → contravariant
const catOnly = (c: Cat) => c.meow();
const viaMethod: HandlerMethod = { handle: catOnly };        // ALLOWED (unsound!)
// const viaProp: HandlerProp = { handle: catOnly };         // error under strictFunctionTypes
// viaMethod.handle({ name: "generic" }) would crash: meow is not a function.
// Why allowed: Array<T>'s methods (push(item: T)) must stay bivariant
// or Dog[] wouldn't be assignable to Animal[] at all.

// Optional and rest parameters are interchangeable when comparing —
// also unsound, also deliberate:
function invokeLater(args: unknown[], cb: (...args: unknown[]) => void) { cb(...args); }
invokeLater([1, 2], (a?, b?) => console.log(a, b));

// Overloads: each target overload must be matched by some source overload.

// ============================================================
// SECTION 3: ENUMS, CLASSES, GENERICS
// ============================================================
enum Status { Ready, Waiting }
enum Color { Red, Blue }
let st = Status.Ready;
// st = Color.Red;  // error — different enums are incompatible
const n: number = st; // numeric enum → number is fine

// Classes: only INSTANCE members compared; statics and constructors ignored.
class AnimalC { feet = 4; constructor(_name: string, _n: number) {} }
class SizeC { feet = 4; constructor(_n: number) {} }
let ac: AnimalC = new SizeC(1); // OK
// private/protected members must originate from the SAME declaration.

// Generics: compared after substitution.
interface Empty<T> {}
let e1: Empty<number> = {};
let e2: Empty<string> = e1;     // OK — T unused, structures identical
interface NotEmpty<T> { data: T }
// let ne: NotEmpty<string> = {} as NotEmpty<number>; // error — data types differ

// ============================================================
// SECTION 4: VARIANCE IN ONE TABLE
// ============================================================
//   Position of T                      Variance
//   readonly property / return type    covariant      (Dog[] → Animal[] allowed)
//   function-property parameter        contravariant  ((a:Animal)=>void → (d:Dog)=>void)
//   method parameter / array element   bivariant      (unsound, intentional)
//   both read and written (mutable)    invariant in theory; TS treats as covariant
// Explicit annotations (4.7): interface Getter<out T>, Setter<in T>, Ref<in out T>.

const dogs: Dog[] = [new Dog()];
const animals: { name: string }[] = dogs; // covariant arrays — allowed
animals.push({ name: "not-a-dog" });      // compiles!
// dogs[1].bark() would now throw at runtime. Defence: readonly arrays at
// API boundaries (ReadonlyArray has no push, so covariance is then sound).

// ============================================================
// SECTION 5: THE SOUNDNESS HOLES (know them by name)
// ============================================================
// 1. any                           — turns checking off, and spreads.
// 2. Type assertions (as, !)       — unchecked promises.
// 3. Method parameter bivariance   — §2.
// 4. Array covariance              — §4.
// 5. Index access w/o noUncheckedIndexedAccess — arr[99] typed as T.
// 6. Optional/rest parameter interchange — §2.
// 7. Type predicates that lie      — `x is T` is trusted blindly.
// 8. Narrowing invalidation        — a callback can mutate a narrowed
//                                     property; TS keeps the narrowing:
function holes(o: { v: string | number }, mutate: () => void) {
  if (typeof o.v === "string") {
    mutate();               // may set o.v = 42
    return o.v.toUpperCase(); // still typed string → potential runtime crash
  }
  return "";
}
// 9. Declaration files that lie    — @types out of sync with the library.
// 10. Object.keys returns string[] (not (keyof T)[]) BECAUSE of width
//     subtyping — an object may have more keys than its type says.

// ============================================================
// SECTION 6: WHAT'S NEW — 4.0 → 7.0 HIGHLIGHTS
// ============================================================
// 4.0  variadic tuple types, labelled tuple elements, `unknown` catch
//      variables option, short-circuit assignment (&&=, ||=, ??=)
// 4.1  template literal types, key remapping in mapped types (`as`),
//      recursive conditional types
// 4.2  leading/middle rest in tuples, abstract construct signatures
// 4.3  `override` keyword, separate getter/setter write types,
//      #private methods
// 4.4  control-flow analysis of aliased conditions, symbol/template
//      index signatures, `exactOptionalPropertyTypes`, static blocks
// 4.5  Awaited<T>, tail-recursive conditional types, `type` modifiers
//      on import names, node12 module (later node16)
// 4.6  CFA for destructured discriminated unions
// 4.7  ESM in Node (node16/nodenext), `infer X extends C`, variance
//      annotations, instantiation expressions, `moduleSuffixes`
// 4.8  improved `{}`/unknown narrowing, template literal inference
// 4.9  `satisfies`, `accessor` auto-accessors, `in` narrowing of
//      unlisted properties
// 5.0  standard decorators, `const` type parameters, enums as unions,
//      `moduleResolution: bundler`, `verbatimModuleSyntax`, extends arrays
// 5.1  unrelated getter/setter types, undefined-returning functions
// 5.2  `using` declarations, decorator metadata, named tuple copy
// 5.3  import attributes, switch(true) narrowing
// 5.4  NoInfer, preserved narrowing in closures after last assignment
// 5.5  inferred type predicates, isolatedDeclarations, regex syntax
//      checking, JSDoc @import, ${configDir}
// 5.6  disallowed always-truthy/nullish checks, iterator helper types,
//      --noUncheckedSideEffectImports, --noCheck
// 5.7  rewriteRelativeImportExtensions, never-initialized-variable checks,
//      es2024 target, faster startup via Node compile cache
// 5.8  erasableSyntaxOnly, --module node18, require(esm) support,
//      granular checks on conditional return expressions
// 5.9  minimal `tsc --init`, `import defer`, --module node20,
//      expandable hovers
// 6.0  last JS-based release: strict/esnext/es2025 defaults, types: [],
//      big deprecation wave, --stableTypeOrdering, Temporal types
// 7.0  native Go compiler, 8-12x faster builds, parallel checkers,
//      deprecations become errors, stable API deferred to 7.1

// ============================================================
// SECTION 7: CAPSTONE — A MINI SCHEMA LIBRARY (Zod-style)
// ============================================================
// One definition → runtime validator AND static type via `Infer<>`.

type Issue = { path: string; message: string };
type Result<T> = { ok: true; value: T } | { ok: false; issues: Issue[] };

abstract class Schema<T> {
  // Phantom field: carries T at the type level only; never read at runtime.
  declare readonly _type: T;
  abstract parseAt(input: unknown, path: string): Result<T>;

  safeParse(input: unknown): Result<T> { return this.parseAt(input, "$"); }
  parse(input: unknown): T {
    const r = this.safeParse(input);
    if (!r.ok) throw new Error(r.issues.map((i) => `${i.path}: ${i.message}`).join("; "));
    return r.value;
  }
  optional(): Schema<T | undefined> { return new OptionalSchema(this); }
  refine(check: (v: T) => boolean, message: string): Schema<T> { return new RefinedSchema(this, check, message); }
  transform<U>(fn: (v: T) => U): Schema<U> { return new TransformSchema(this, fn); }
}

type Infer<S extends Schema<unknown>> = S["_type"];

const fail = (path: string, message: string): Result<never> => ({ ok: false, issues: [{ path, message }] });

class StringSchema extends Schema<string> {
  parseAt(i: unknown, p: string): Result<string> { return typeof i === "string" ? { ok: true, value: i } : fail(p, `expected string, got ${typeof i}`); }
}
class NumberSchema extends Schema<number> {
  parseAt(i: unknown, p: string): Result<number> {
    return typeof i === "number" && Number.isFinite(i) ? { ok: true, value: i } : fail(p, `expected finite number`);
  }
}
class LiteralSchema<L extends string | number | boolean> extends Schema<L> {
  constructor(private readonly lit: L) { super(); }
  parseAt(i: unknown, p: string): Result<L> { return i === this.lit ? { ok: true, value: this.lit } : fail(p, `expected ${JSON.stringify(this.lit)}`); }
}
class OptionalSchema<T> extends Schema<T | undefined> {
  constructor(private readonly inner: Schema<T>) { super(); }
  parseAt(i: unknown, p: string): Result<T | undefined> { return i === undefined ? { ok: true, value: undefined } : this.inner.parseAt(i, p); }
}
class RefinedSchema<T> extends Schema<T> {
  constructor(private inner: Schema<T>, private check: (v: T) => boolean, private msg: string) { super(); }
  parseAt(i: unknown, p: string): Result<T> {
    const r = this.inner.parseAt(i, p);
    return r.ok && !this.check(r.value) ? fail(p, this.msg) : r;
  }
}
class TransformSchema<T, U> extends Schema<U> {
  constructor(private inner: Schema<T>, private fn: (v: T) => U) { super(); }
  parseAt(i: unknown, p: string): Result<U> {
    const r = this.inner.parseAt(i, p);
    return r.ok ? { ok: true, value: this.fn(r.value) } : r;
  }
}
class ArraySchema<T> extends Schema<T[]> {
  constructor(private item: Schema<T>) { super(); }
  parseAt(i: unknown, p: string): Result<T[]> {
    if (!Array.isArray(i)) return fail(p, "expected array");
    const out: T[] = []; const issues: Issue[] = [];
    i.forEach((el, idx) => { const r = this.item.parseAt(el, `${p}[${idx}]`); if (r.ok) out.push(r.value); else issues.push(...r.issues); });
    return issues.length ? { ok: false, issues } : { ok: true, value: out };
  }
}

// Object schema: the type-level heart. Keys whose schema accepts
// undefined become OPTIONAL properties in the inferred type.
type Shape = Record<string, Schema<unknown>>;
type OptionalKeys<S extends Shape> = { [K in keyof S]: undefined extends Infer<S[K]> ? K : never }[keyof S];
type ObjectType<S extends Shape> = { [K in Exclude<keyof S, OptionalKeys<S>>]: Infer<S[K]> } & { [K in OptionalKeys<S>]?: Infer<S[K]> };
type Flat<T> = { [K in keyof T]: T[K] } & {};

class ObjectSchema<S extends Shape> extends Schema<Flat<ObjectType<S>>> {
  constructor(private readonly shape: S) { super(); }
  parseAt(i: unknown, p: string): Result<Flat<ObjectType<S>>> {
    if (typeof i !== "object" || i === null || Array.isArray(i)) return fail(p, "expected object");
    const out: Record<string, unknown> = {}; const issues: Issue[] = [];
    for (const [key, schema] of Object.entries(this.shape)) {
      const r = schema.parseAt((i as Record<string, unknown>)[key], `${p}.${key}`);
      if (r.ok) { if (r.value !== undefined) out[key] = r.value; } else issues.push(...r.issues);
    }
    // Unknown keys are STRIPPED (like Zod's default) — no excess data leaks through.
    return issues.length ? { ok: false, issues } : { ok: true, value: out as Flat<ObjectType<S>> };
  }
}

class UnionSchema<Opts extends readonly Schema<unknown>[]> extends Schema<Infer<Opts[number]>> {
  constructor(private opts: Opts) { super(); }
  parseAt(i: unknown, p: string): Result<Infer<Opts[number]>> {
    const all: Issue[] = [];
    for (const o of this.opts) { const r = o.parseAt(i, p); if (r.ok) return r as Result<Infer<Opts[number]>>; all.push(...r.issues); }
    return { ok: false, issues: [{ path: p, message: `no union member matched (${all.length} issues)` }] };
  }
}

// The builder namespace — the public API.
const z = {
  string: () => new StringSchema(),
  number: () => new NumberSchema(),
  literal: <const L extends string | number | boolean>(l: L) => new LiteralSchema(l),
  array: <T>(item: Schema<T>) => new ArraySchema(item),
  object: <S extends Shape>(shape: S) => new ObjectSchema(shape),
  union: <const O extends readonly Schema<unknown>[]>(...opts: O) => new UnionSchema(opts),
};

// ============================================================
// SECTION 8: USING IT AT A TRUST BOUNDARY
// ============================================================
const CreateOrder = z.object({
  customerId: z.string().refine((s) => s.startsWith("cus_"), "must start with cus_"),
  items: z.array(z.object({
    sku: z.string(),
    quantity: z.number().refine((n) => Number.isInteger(n) && n > 0, "positive integer"),
  })).refine((a) => a.length > 0, "at least one item"),
  channel: z.union(z.literal("web"), z.literal("mobile")),
  note: z.string().optional(),
  // Refine BEFORE transform — `new Date("x")` doesn't throw, it yields Invalid Date.
  placedAt: z.string().refine((s) => !Number.isNaN(Date.parse(s)), "expected ISO date").transform((s) => new Date(s)),
});

// The type is DERIVED, not hand-written — it cannot drift from the validator.
type CreateOrder = Infer<typeof CreateOrder>;
// Hover shows:
// { customerId: string; items: { sku: string; quantity: number }[];
//   channel: "web" | "mobile"; placedAt: Date; note?: string | undefined }

function handleCreateOrder(body: string): string {
  let raw: unknown;
  try { raw = JSON.parse(body); } catch { return "400 invalid JSON"; }
  const r = CreateOrder.safeParse(raw);
  if (!r.ok) return `422 ${r.issues.map((i) => `${i.path}: ${i.message}`).join(", ")}`;
  const order: CreateOrder = r.value;               // fully typed from here inward
  const units = order.items.reduce((s, i) => s + i.quantity, 0);
  return `201 ${order.customerId} ${units} unit(s) via ${order.channel} at ${order.placedAt.toISOString()}`;
}

console.log(handleCreateOrder(JSON.stringify({
  customerId: "cus_42", channel: "web", placedAt: "2026-10-10T12:00:00Z",
  items: [{ sku: "A", quantity: 2 }, { sku: "B", quantity: 1 }], isAdmin: true, // isAdmin stripped
})));
console.log(handleCreateOrder(JSON.stringify({
  customerId: "42", channel: "fax", placedAt: "x", items: [{ sku: "A", quantity: 0 }],
})));
console.log(handleCreateOrder("{nope"));

// In production use Zod 4 / Valibot / ArkType / Effect Schema — same
// idea, plus Standard Schema interop, JSON Schema export, and error
// formatting. Architecture rule: validate at EVERY boundary —
// HTTP bodies, queue messages, env vars, localStorage, third-party
// API responses, DB rows from shared tables — and nowhere else.

console.log(pet.name, viaMethod.handle === catOnly, n, ac.feet, e2, holes({ v: "a" }, () => {}),
  r1().name, x2(1), y2(1, "s"), animals.length);
export type { Opts, HandlerProp, NotEmpty, Cat };
export { Color };
