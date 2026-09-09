# TypeScript — In-Depth Reference

Distinct from Full-Stack & Frontend Essentials Notes — this file covers
TypeScript's TYPE SYSTEM in depth (structural typing, generics, advanced
types), applicable equally to frontend and Node.js backend code.


## 1. STRUCTURAL TYPING — THE FOUNDATIONAL DIFFERENCE FROM JAVA/C#

TypeScript's type system is STRUCTURAL, not nominal — a type is compatible
with another if it has the right SHAPE, regardless of explicit
declaration. This is a genuinely different mental model from Java/C#'s
nominal typing (where a class must explicitly `implements` an interface).

```typescript
interface Point { x: number; y: number; }

function printPoint(p: Point) { console.log(p.x, p.y); }

const obj = { x: 1, y: 2, z: 3 };  // Never declared as "Point"
printPoint(obj);  // Works! obj has AT LEAST the shape Point requires — "duck typing," statically checked
```

**Type inference** is genuinely strong — TypeScript infers types from
usage constantly, meaning idiomatic TS code has far fewer explicit type
annotations than beginners expect; over-annotating (`const x: number = 5`)
is often considered a style smell, not best practice, since `const x = 5`
infers the same type with less noise.


## 2. GENERICS & ADVANCED TYPES

```typescript
// Generic function — type-safe across any T, without duplicating logic per type
function firstElement<T>(arr: T[]): T | undefined {
  return arr[0];
}

// Conditional types — types that branch based on a condition, evaluated at compile time
type IsString<T> = T extends string ? true : false;

// Mapped types — transform every property of a type
type Partial<T> = { [K in keyof T]?: T[K] };   // Built into TS's standard lib, this is its actual definition
type Readonly<T> = { readonly [K in keyof T]: T[K] };

// Template literal types (TS 4.1+) — genuinely novel, string-pattern-aware types
type EventName = `on${Capitalize<string>}`;  // Matches "onClick", "onSubmit", etc. at the TYPE level
```

**Utility types worth knowing cold**: `Partial<T>`, `Required<T>`,
`Pick<T, K>`, `Omit<T, K>`, `Record<K, V>` — these are used constantly in
real production TypeScript and understanding them (not just using them)
is a genuine interview signal of real TS fluency versus surface familiarity.


## 3. TYPE NARROWING & DISCRIMINATED UNIONS

```typescript
// Discriminated unions — the idiomatic TS pattern for type-safe "one of several shapes" data
type Result =
  | { status: "success"; data: string }
  | { status: "error"; message: string };

function handle(result: Result) {
  if (result.status === "success") {
    console.log(result.data);      // TS KNOWS this branch has `data`, not `message`
  } else {
    console.log(result.message);   // And this branch is narrowed to the error shape
  }
}
```

This pattern (a shared literal "tag" field distinguishing union members)
is THE idiomatic way to model "one of several possible states" safely in
TypeScript — used constantly for API response shapes, Redux action types,
and state machines — genuinely more type-safe than an `any`-typed object
with optional fields checked ad-hoc.


## 4. THE `any` VS `unknown` DISTINCTION — A REAL, COMMON INTERVIEW QUESTION

`any` disables type checking entirely for that value — assigning it
anywhere, calling any method on it, all compile without error, silently
reintroducing exactly the runtime errors TypeScript exists to prevent.
`unknown` is type-safe by design: you can assign anything TO an
`unknown`-typed variable, but you CANNOT do anything with an `unknown`
value (no method calls, no property access) until you've NARROWED it via
a type guard/check — `unknown` is the "safe `any`," used when a value's
type is genuinely not known upfront (parsing JSON, function
parameters accepting arbitrary input) without giving up type safety.


## 5. NICHE BUT REAL

- **`satisfies` operator** (TS 4.9+) — validates a value MATCHES a type
  without WIDENING its inferred type the way an explicit type annotation
  would — lets you get both type-checking AND the most specific inferred
  literal type simultaneously, a subtle but real quality-of-life addition.
- **Type-level programming / recursive conditional types** — TypeScript's
  type system is technically Turing-complete; genuinely elaborate
  compile-time computations (parsing a string literal type character by
  character, implementing a type-level state machine) are possible and
  occasionally seen in advanced library type definitions (e.g. some
  routing libraries' type-safe path parameter extraction) — mostly
  library-author territory, not everyday application code.
- **Declaration files (`.d.ts`) & `DefinitelyTyped`** — how JavaScript
  libraries without native TypeScript support get typed (community-
  maintained `@types/` packages) — worth knowing this ecosystem exists
  and occasionally needs manual patching (`declare module` overrides) for
  a library with missing/incorrect community types.
- **`tsconfig.json` strictness flags** — `strict: true` bundles several
  individually-toggleable checks (`strictNullChecks`, `noImplicitAny`,
  `strictFunctionTypes`) — a codebase NOT running in strict mode is
  genuinely a different, much weaker type-safety experience than one
  that is, a real thing to check when joining/auditing an existing TS codebase.
- **Type-safe environment variables & runtime validation (Zod)** — since
  TypeScript's types are erased at compile time (zero runtime
  enforcement), validating EXTERNAL data (API responses, env vars, form
  input) still needs a runtime library like Zod/Yup that generates BOTH a
  runtime validator AND an inferred TS type from one schema definition —
  the standard modern pattern for closing TypeScript's fundamental
  "compile-time only" gap at actual runtime trust boundaries.
