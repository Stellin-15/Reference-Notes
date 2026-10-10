// ============================================================
// L04: Type Manipulation & Utility Types
// ============================================================
// WHAT: The Handbook's whole "Type Manipulation" section —
//       Creating Types from Types, Generics (generic types,
//       classes, constraints, defaults, variance annotations),
//       keyof, typeof, indexed access, conditional types (infer,
//       distributive behaviour), mapped types (modifiers, key
//       remapping with `as`), template literal types and the
//       intrinsic string types — then EVERY entry on the
//       Reference "Utility Types" page with its real definition.
// WHY:  This is the layer that lets you derive types instead of
//       duplicating them: one source of truth (a schema, a
//       config object, an API route table) and every dependent
//       type computed from it, so they can never drift apart.
// LEVEL: Intermediate → Advanced
// SOURCE: typescriptlang.org/docs/handbook/2/types-from-types.html
//         and sub-pages; .../utility-types.html (TS 7.0, Oct 2026)
// ============================================================
/*
CONCEPT OVERVIEW:
    The type system has its own expression language:
      keyof T           — union of T's keys
      typeof value      — the type of a value (type position only)
      T[K]              — indexed access (property type lookup)
      T extends U ? X : Y — conditional (if/else on types)
      infer R           — pattern-match and capture inside a conditional
      { [K in Keys]: … } — mapped type (loop over a union)
      `prefix${T}`      — template literal type (string building)
    Combine them and you can compute nearly any type from any other.

PRODUCTION USE CASE:
    A typed API client derived from ONE route table object:
    method names, path parameter types (parsed out of the path
    string at the type level), request and response types all
    come from the same `as const` definition.

COMMON MISTAKES:
    1. Unexpected distribution: `T extends any ? T[] : never`
       turns `string | number` into `string[] | number[]`.
       Wrap in brackets `[T] extends [any]` to stop it.
    2. `keyof` on a type with a string index signature returns
       `string | number` (numeric keys are strings in JS).
    3. Using `typeof` on a function call — `typeof f()` is a
       syntax error; use `ReturnType<typeof f>`.
    4. Over-engineering: a 40-line recursive conditional type
       nobody can debug. If plain interfaces work, use them.
    5. `Omit<T, "typo">` silently does nothing — Omit's key
       parameter is `keyof any`, not `keyof T`.
    6. Deep recursion hitting "Type instantiation is excessively
       deep" (limit ~50 for non-tail, ~1000 for tail-recursive
       conditional types).
*/

// ============================================================
// SECTION 1: GENERIC TYPES, CLASSES, CONSTRAINTS, DEFAULTS
// ============================================================
// A generic function's type can be written as a generic call signature:
function identity<T>(arg: T): T { return arg; }
const myIdentity: <U>(arg: U) => U = identity;
// …or moved into an interface (the type parameter on the INTERFACE
// fixes T for the whole object):
interface GenericIdentityFn<T> { (arg: T): T }
const numIdentity: GenericIdentityFn<number> = identity;

// Generic class — type parameters apply to instance side only.
class Stack<T> {
  #items: T[] = [];
  push(item: T): void { this.#items.push(item); }
  pop(): T | undefined { return this.#items.pop(); }
  get size() { return this.#items.length; }
}

// Constraint using another type parameter:
function getProperty<T, K extends keyof T>(obj: T, key: K): T[K] {
  return obj[key];
}
const cfg = { port: 8080, host: "0.0.0.0" };
const port = getProperty(cfg, "port"); // number
// getProperty(cfg, "hots");            // error: not a key

// Class types in generics — factory pattern:
function createInstance<A>(c: new () => A): A { return new c(); }

// Generic parameter DEFAULTS (like default function args):
interface ApiResponse<TData = unknown, TError = { message: string }> {
  data?: TData;
  error?: TError;
}
const resp: ApiResponse<string[]> = { data: ["a"] }; // TError defaulted

// VARIANCE ANNOTATIONS (TS 4.7): `in` = contravariant, `out` = covariant,
// `in out` = invariant. Normally inferred; annotate only for checker
// performance in huge recursive types, or to document intent.
interface Producer<out T> { make(): T }
interface Consumer<in T> { consume(arg: T): void }

// ============================================================
// SECTION 2: keyof
// ============================================================
type Pt = { x: number; y: number };
type PtKeys = keyof Pt;                       // "x" | "y"
type Arrayish = { [n: number]: unknown };
type A = keyof Arrayish;                      // number
type Mapish = { [k: string]: boolean };
type M = keyof Mapish;                        // string | number  (obj[0] === obj["0"])

// ============================================================
// SECTION 3: typeof (type-level)
// ============================================================
// Only legal on identifiers and their properties — not on calls.
const defaults = { retries: 3, timeoutMs: 5000, verbose: false };
type Defaults = typeof defaults;              // { retries: number; timeoutMs: number; verbose: boolean }
function makeUser() { return { id: "u1", roles: ["admin"] as string[] }; }
type MadeUser = ReturnType<typeof makeUser>;  // NOT `typeof makeUser()`

// ============================================================
// SECTION 4: INDEXED ACCESS TYPES
// ============================================================
type PersonT = { age: number; name: string; alive: boolean };
type Age = PersonT["age"];                    // number
type AgeOrName = PersonT["age" | "name"];     // number | string
type AnyProp = PersonT[keyof PersonT];        // number | string | boolean

// Element type of an array via [number]:
const People = [{ name: "Alice", age: 15 }, { name: "Bob", age: 23 }];
type PersonElem = (typeof People)[number];    // { name: string; age: number }
type PersonAge = (typeof People)[number]["age"]; // number
// Index with TYPES, not values: `const k = "age"; T[k]` is an error;
// use `type k = "age"` instead.

// ============================================================
// SECTION 5: CONDITIONAL TYPES
// ============================================================
interface IdLabel { id: number }
interface NameLabel { name: string }
// Replace overload explosions with one conditional return type:
type NameOrId<T extends number | string> = T extends number ? IdLabel : NameLabel;
function createLabel<T extends number | string>(idOrName: T): NameOrId<T> {
  // Implementation must cast: TS doesn't narrow generic return types
  // through runtime checks (TS 5.8 started narrowing some
  // conditional return types, but not this shape).
  return (typeof idOrName === "number" ? { id: idOrName } : { name: idOrName }) as NameOrId<T>;
}
const lbl = createLabel("typescript"); // NameLabel

// Conditional type CONSTRAINTS — narrow T inside the true branch:
type MessageOf<T> = T extends { message: unknown } ? T["message"] : never;
type EmailMsg = MessageOf<{ message: string }>; // string

// `infer` — capture part of a matched type:
type Flatten<T> = T extends Array<infer Item> ? Item : T;
type Str = Flatten<string[]>;   // string
type Num = Flatten<number>;     // number
type GetReturn<T> = T extends (...args: never[]) => infer R ? R : never;
type Awaited2<T> = T extends PromiseLike<infer V> ? Awaited2<V> : T; // recursive unwrapping

// `infer` with constraints (TS 4.7):
type FirstIfString<T> = T extends [infer S extends string, ...unknown[]] ? S : never;
type F1 = FirstIfString<["a", 1]>; // "a"

// Overloaded functions: `infer` matches the LAST signature only.

// DISTRIBUTIVE conditional types — naked type parameter + union input
// = applied to each member separately:
type ToArray<T> = T extends any ? T[] : never;
type Dist = ToArray<string | number>;           // string[] | number[]
type ToArrayNonDist<T> = [T] extends [any] ? T[] : never;
type NonDist = ToArrayNonDist<string | number>; // (string | number)[]
// `never` is the empty union — distributing over it yields never:
type IsNever<T> = [T] extends [never] ? true : false; // must use brackets

// ============================================================
// SECTION 6: MAPPED TYPES
// ============================================================
type OptionsFlags<T> = { [P in keyof T]: boolean };
type FeatureFlags = OptionsFlags<{ darkMode: () => void; newUI: () => void }>; // { darkMode: boolean; newUI: boolean }

// Modifiers: add (+) or remove (-) readonly and ?.
type Mutable<T> = { -readonly [P in keyof T]: T[P] };
type Concrete<T> = { [P in keyof T]-?: T[P] };

// KEY REMAPPING with `as` (TS 4.1):
type Getters<T> = {
  [K in keyof T as `get${Capitalize<string & K>}`]: () => T[K];
};
type PersonGetters = Getters<{ name: string; age: number }>; // { getName(): string; getAge(): number }

// Filtering keys by remapping to never:
type RemoveKind<T> = { [K in keyof T as Exclude<K, "kind">]: T[K] };
type KindlessCircle = RemoveKind<{ kind: "circle"; radius: number }>; // { radius: number }

// Mapping over an arbitrary union (not just keyof):
type EventConfig<E extends { kind: string }> = { [Ev in E as Ev["kind"]]: (e: Ev) => void };

// Filter properties by VALUE type:
type KeysOfType<T, V> = { [K in keyof T]-?: T[K] extends V ? K : never }[keyof T];
type StringKeys = KeysOfType<{ a: string; b: number; c?: string }, string | undefined>; // "a" | "c"

// Homomorphic mapped types (over `keyof T`) preserve optional/readonly
// modifiers, and map arrays/tuples to arrays/tuples.
type Boxed<T> = { [K in keyof T]: { value: T[K] } };
type BoxedTuple = Boxed<[string, number]>; // [{ value: string }, { value: number }]

// ============================================================
// SECTION 7: TEMPLATE LITERAL TYPES
// ============================================================
type World = "world";
type Greeting = `hello ${World}`;                 // "hello world"
type Lang = "en" | "ja"; type Section = "header" | "footer";
type LocaleId = `${Lang}_${Section}_id`;          // cross product: 4 members

// Typed event emitter: "on" + Capitalize<key>, payload typed by the key.
type PropEventSource<T> = {
  on<K extends string & keyof T>(eventName: `${K}Changed`, callback: (newValue: T[K]) => void): void;
};
function makeWatched<T extends object>(obj: T): T & PropEventSource<T> {
  const listeners = new Map<string, ((v: unknown) => void)[]>();
  return Object.assign(obj, {
    on(eventName: string, cb: (v: never) => void) {
      listeners.set(eventName, [...(listeners.get(eventName) ?? []), cb as (v: unknown) => void]);
    },
  }) as T & PropEventSource<T>;
}
const person = makeWatched({ firstName: "Saoirse", age: 26 });
person.on("ageChanged", (newAge) => newAge.toFixed()); // newAge: number
// person.on("firstNameChange", () => {});  // error: missing "d"

// INTRINSIC string manipulation types (compiler-implemented):
type U1 = Uppercase<"get">;      // "GET"
type L1 = Lowercase<"GET">;      // "get"
type C1 = Capitalize<"user">;    // "User"
type UC = Uncapitalize<"User">;  // "user"

// Parsing strings with infer in template positions:
type Trim<S extends string> = S extends ` ${infer R}` | `${infer R} ` ? Trim<R> : S;
type Trimmed = Trim<"  hi  ">;   // "hi"
type Split<S extends string, D extends string> =
  S extends `${infer Head}${D}${infer Tail}` ? [Head, ...Split<Tail, D>] : [S];
type Parts = Split<"a.b.c", ".">; // ["a", "b", "c"]

// ============================================================
// SECTION 8: EVERY BUILT-IN UTILITY TYPE (with definitions)
// ============================================================
interface Todo { title: string; description: string; completed: boolean; createdAt?: number }

// Awaited<T> (4.5) — recursively unwraps promises / thenables.
type AW = Awaited<Promise<Promise<number>>>;      // number

// Partial<T> = { [P in keyof T]?: T[P] }
function updateTodo(todo: Todo, patch: Partial<Todo>): Todo { return { ...todo, ...patch }; }

// Required<T> = { [P in keyof T]-?: T[P] }
type FullTodo = Required<Todo>;                   // createdAt now required

// Readonly<T> = { readonly [P in keyof T]: T[P] }
const frozenTodo: Readonly<Todo> = { title: "x", description: "", completed: false };
// frozenTodo.title = "y"; // error. (Object.freeze returns Readonly<T>.)

// Record<K extends keyof any, T> = { [P in K]: T }
type CatName = "miffy" | "boris";
const cats: Record<CatName, { age: number }> = { miffy: { age: 10 }, boris: { age: 5 } };

// Pick<T, K extends keyof T> = { [P in K]: T[P] }
type TodoPreview = Pick<Todo, "title" | "completed">;

// Omit<T, K extends keyof any> = Pick<T, Exclude<keyof T, K>>
type TodoInfo = Omit<Todo, "completed" | "createdAt">;
// Strict variant that rejects typos:
type StrictOmit<T, K extends keyof T> = Omit<T, K>;

// Exclude<T, U> = T extends U ? never : T      (filter a union)
type T0 = Exclude<"a" | "b" | "c", "a">;           // "b" | "c"
// Extract<T, U> = T extends U ? T : never      (keep matching members)
type T1 = Extract<string | number | (() => void), Function>; // () => void
// NonNullable<T> = T & {}
type T2 = NonNullable<string | null | undefined>;  // string

// Parameters<T> / ConstructorParameters<T> / ReturnType<T> / InstanceType<T>
declare function f1(arg: { a: number; b: string }): void;
type P1 = Parameters<typeof f1>;                   // [arg: { a: number; b: string }]
type CP = ConstructorParameters<typeof Error>;     // [message?: string, options?: ErrorOptions]
type R1 = ReturnType<() => { x: number }>;         // { x: number }
type I1 = InstanceType<typeof Stack<number>>;      // Stack<number> (instantiation expression, TS 4.7)

// NoInfer<T> (5.4) — block a position from contributing to inference.
function createStreetLight<C extends string>(colors: C[], defaultColor?: NoInfer<C>) { return defaultColor ?? colors[0]; }
createStreetLight(["red", "yellow", "green"], "red");
// createStreetLight(["red", "yellow", "green"], "blue"); // error — without NoInfer, C would widen to include "blue"

// ThisParameterType<T> / OmitThisParameter<T> / ThisType<T>
function toHex(this: number) { return this.toString(16); }
type TP = ThisParameterType<typeof toHex>;          // number
const fiveToHex: OmitThisParameter<typeof toHex> = toHex.bind(5);
// ThisType<T> — a marker (needs noImplicitThis) that sets `this` inside an object literal:
type ObjectDescriptor<D, Meth> = { data?: D; methods?: Meth & ThisType<D & Meth> };
function makeObject<D, Meth>(desc: ObjectDescriptor<D, Meth>): D & Meth {
  return { ...desc.data, ...desc.methods } as D & Meth;
}
const vec = makeObject({
  data: { x: 0, y: 0 },
  methods: { moveBy(dx: number, dy: number) { this.x += dx; this.y += dy; } }, // this: {x,y} & methods
});

// ============================================================
// SECTION 9: SELF-MADE UTILITIES WORTH KNOWING
// ============================================================
type DeepPartial<T> = T extends object ? { [K in keyof T]?: DeepPartial<T[K]> } : T;
type DeepReadonly<T> = T extends (...a: any[]) => any ? T : T extends object ? { readonly [K in keyof T]: DeepReadonly<T[K]> } : T;
// Prettify — flattens intersections for readable hovers:
type Prettify<T> = { [K in keyof T]: T[K] } & {};
// UnionToIntersection — classic contravariance trick:
type UnionToIntersection<U> = (U extends any ? (x: U) => void : never) extends (x: infer I) => void ? I : never;
type UI = UnionToIntersection<{ a: 1 } | { b: 2 }>; // { a: 1 } & { b: 2 }
// Branded (nominal) types — prevent mixing structurally identical primitives:
type Brand<T, B extends string> = T & { readonly __brand: B };
type UserId = Brand<string, "UserId">;
type OrderId = Brand<string, "OrderId">;
const asUserId = (s: string) => s as UserId;
function loadUser(id: UserId) { return id; }
loadUser(asUserId("u_1"));
// loadUser("u_1" as OrderId); // error — brands differ

// ============================================================
// SECTION 10: END-TO-END — CLIENT DERIVED FROM A ROUTE TABLE
// ============================================================
// Extract ":param" names from a path string at the type level.
type PathParams<P extends string> =
  P extends `${string}:${infer Param}/${infer Rest}` ? { [K in Param | keyof PathParams<Rest>]: string }
  : P extends `${string}:${infer Param}` ? { [K in Param]: string }
  : {};

const routes = {
  getUser:     { method: "GET",  path: "/users/:userId" },
  listOrders:  { method: "GET",  path: "/users/:userId/orders/:status" },
  createOrder: { method: "POST", path: "/orders" },
} as const;

// Response types keyed by route name.
interface Responses {
  getUser: { id: string; name: string };
  listOrders: { id: string; total: number }[];
  createOrder: { id: string };
}

type Routes = typeof routes;
type Client = {
  [Name in keyof Routes]: (
    params: Prettify<PathParams<Routes[Name]["path"]>>,
  ) => Promise<Name extends keyof Responses ? Responses[Name] : never>;
};

function buildClient(fetcher: (method: string, url: string) => Promise<unknown>): Client {
  const client = {} as Record<string, (p: Record<string, string>) => Promise<unknown>>;
  for (const [name, { method, path }] of Object.entries(routes)) {
    client[name] = (params) =>
      fetcher(method, path.replace(/:(\w+)/g, (_, k: string) => encodeURIComponent(params[k] ?? "")));
  }
  return client as unknown as Client; // the one unavoidable cast, at the boundary
}

const api = buildClient(async (method, url) => {
  console.log(method, url);
  return url.includes("orders") ? [{ id: "o1", total: 10 }] : { id: "u1", name: "Ada" };
});

async function demo() {
  const user = await api.getUser({ userId: "u1" });                  // { id; name }
  const orders = await api.listOrders({ userId: "u1", status: "open" }); // params must include both
  // await api.listOrders({ userId: "u1" });  // error: property 'status' is missing
  console.log(user.name, orders[0]?.total);
}

const s = new Stack<number>(); s.push(1);
console.log(myIdentity("a"), numIdentity(1), s.pop(), port, createInstance(Date) instanceof Date, resp,
  lbl, updateTodo({ title: "a", description: "", completed: false }, { completed: true }), frozenTodo.title,
  cats.boris.age, createStreetLight(["red", "green"]), fiveToHex(), (vec.moveBy(1, 2), vec.x), defaults.retries,
  makeUser().id, People.length, loadUser(asUserId("u2")));
void demo();

export type {
  Producer, Consumer, PtKeys, A, M, Defaults, MadeUser, Age, AgeOrName, AnyProp, PersonElem, PersonAge,
  EmailMsg, Str, Num, GetReturn, Awaited2, F1, Dist, NonDist, IsNever, FeatureFlags, Mutable, Concrete,
  PersonGetters, KindlessCircle, EventConfig, StringKeys, BoxedTuple, Greeting, LocaleId, U1, L1, C1, UC,
  Trimmed, Parts, AW, FullTodo, TodoPreview, TodoInfo, StrictOmit, T0, T1, T2, P1, CP, R1, I1, TP,
  DeepPartial, DeepReadonly, UI, OrderId,
};
