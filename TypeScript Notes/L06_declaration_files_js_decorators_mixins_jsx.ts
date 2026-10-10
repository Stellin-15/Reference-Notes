// ============================================================
// L06: Declaration Files, JS Projects, Decorators, Mixins, JSX
// ============================================================
// WHAT: The Handbook's "Declaration Files" section (Introduction,
//       Declaration Reference, Library Structures, .d.ts
//       Templates, Do's and Don'ts, Deep Dive, Publishing,
//       Consumption), the "JavaScript" section (type-checking JS,
//       JSDoc Reference, generating .d.ts from .js), and the
//       Reference pages "Decorators", "Mixins", and "JSX".
// WHY:  Every npm package you consume is typed by a .d.ts file —
//       either bundled or from DefinitelyTyped. When types are
//       missing or wrong you must write or patch them. JSDoc
//       typing lets JS-only codebases (and build scripts) get
//       checking with zero compile step. Decorators are now a
//       standard ECMAScript feature (TS 5.0) used by Angular,
//       NestJS, Lit, MobX, TypeORM.
// LEVEL: Advanced
// SOURCE: typescriptlang.org/docs/handbook/declaration-files/*,
//         .../intro-to-js-ts.html, .../jsdoc-supported-types.html,
//         .../decorators.html, .../mixins.html, .../jsx.html (TS 7.0)
// ============================================================
/*
CONCEPT OVERVIEW:
    A declaration file (.d.ts) contains ONLY types — `declare`
    statements describing values that exist at runtime somewhere
    else. tsc reads them; it never emits JS for them.
    Sources of declarations, in resolution order:
      1. The package's own "types"/"exports"."types" entry
      2. @types/<pkg> from DefinitelyTyped
      3. Your own `declare module "pkg"` in a local .d.ts
    `skipLibCheck: true` skips type-checking .d.ts files (faster,
    and avoids errors in dependencies' types) — near-universal.

PRODUCTION USE CASE:
    Typing an untyped internal JS analytics library, publishing a
    typed package with correct "exports", and building a NestJS-
    style decorator-based validation layer on standard decorators.

COMMON MISTAKES:
    1. Writing `declare module "lib"` in a file with top-level
       import/export — it becomes an AUGMENTATION, not a
       declaration. Ambient module declarations go in script files.
    2. Shipping .d.ts that reference @types packages you only have
       as devDependencies — consumers get errors. Put type deps
       your public API exposes in "dependencies".
    3. Mixing `experimentalDecorators` (legacy, TS-specific) with
       code written for standard decorators — different signatures.
    4. Publishing `"types"` that point at .ts sources — consumers
       then type-check your source with THEIR settings.
    5. Using `allowJs` without `checkJs` and assuming the JS is
       type-checked. allowJs only includes JS; checkJs checks it.
*/

// ============================================================
// SECTION 1: DECLARATION REFERENCE — `declare` FORMS
// ============================================================
// Typical .d.ts contents (here as ambient declarations; at runtime
// nothing below exists — only used in type positions):
declare const APP_BUILD: string;                       // global variable
declare function track(event: string, props?: Record<string, unknown>): void; // global function
declare namespace analytics {                           // object with properties
  function identify(userId: string): void;
  let sampleRate: number;
  interface Event { name: string; ts: number }         // types nested inside
}
declare class Widget {                                  // a class from a script tag
  constructor(el: string);
  render(): void;
  static version: string;
}
// Overloaded functions declare multiple signatures; no body:
declare function getWidget(n: number): Widget;
declare function getWidget(s: string): Widget[];

// ============================================================
// SECTION 2: LIBRARY STRUCTURES & .d.ts TEMPLATES
// ============================================================
// Identify the library's shape, then pick the template:
//
// (a) MODULE library (import/require) — template "module.d.ts":
//     // index.d.ts
//     export function parse(input: string, opts?: ParseOptions): Ast;
//     export interface ParseOptions { strict?: boolean }
//     export interface Ast { type: string; children: Ast[] }
//
// (b) Module exporting a CLASS (CommonJS `module.exports = Cls`)
//     — template "module-class.d.ts":
//     declare class Greeter { constructor(name: string); greet(): string }
//     declare namespace Greeter { interface Options { loud: boolean } }
//     export = Greeter;
//
// (c) Module exporting a FUNCTION (`module.exports = fn`) with props
//     — template "module-function.d.ts":
//     declare function slugify(s: string): string;
//     declare namespace slugify { const version: string }
//     export = slugify;
//
// (d) Module PLUGIN (adds methods to another module, e.g. moment plugins)
//     — template "module-plugin.d.ts": `import "moment"; declare module "moment" { interface Moment { fromNowShort(): string } }`
//
// (e) GLOBAL library (script tag, defines window.X) — "global.d.ts":
//     declare function myLib(a: string): string;
//     declare namespace myLib { let timeout: number }
//
// (f) GLOBAL-MODIFYING module (imported for side effects, patches
//     String.prototype etc.) — "global-modifying-module.d.ts":
//     export {};
//     declare global { interface String { fancyFormat(): string } }
//
// UMD libraries (usable both ways) add: `export as namespace myLib;`

// ============================================================
// SECTION 3: DO'S AND DON'TS (official list, condensed)
// ============================================================
//  ✗ Number/String/Boolean/Symbol/Object  ✓ number/string/boolean/symbol/object
//  ✗ generic type parameters that are never used (break inference)
//  ✗ any (except while migrating)          ✓ unknown for pass-through values
//  ✗ callback return type any when ignored ✓ void
//  ✗ optional parameters in callbacks      ✓ required (callers may pass fewer)
//  ✗ overloads differing only in callback arity ✓ one overload, max arity
//  ✗ general overloads before specific     ✓ specific first (first match wins)
//  ✗ overloads differing only in trailing params ✓ optional parameters
//  ✗ overloads differing in one argument's type  ✓ a union type

// ============================================================
// SECTION 4: DEEP DIVE — HOW DECLARATIONS COMBINE
// ============================================================
// A name can simultaneously be a VALUE, a TYPE, and a NAMESPACE
// (L05 §9). .d.ts authors exploit this to model JS shapes:
//   export declare const Status: { readonly Ok: 200; readonly NotFound: 404 };
//   export type Status = (typeof Status)[keyof typeof Status];
// One import `import { Status }` then gives both the object and the type.
// "Advanced combinations" — adding a namespace to a class to model
// static nested types, interfaces merging with classes to add instance
// members to a class declared elsewhere.

// ============================================================
// SECTION 5: PUBLISHING & CONSUMPTION
// ============================================================
// package.json for a typed package (bundled types — preferred):
//   {
//     "name": "@acme/sdk",
//     "type": "module",
//     "exports": { ".": { "types": "./dist/index.d.ts", "default": "./dist/index.js" } },
//     "types": "./dist/index.d.ts",           // fallback for old resolvers
//     "files": ["dist"],
//     "dependencies": { "@types/node": "^24" } // only if PUBLIC API exposes Node types
//   }
// "typesVersions" maps different .d.ts per consumer TS version:
//   "typesVersions": { "<5.0": { "*": ["ts4/*"] } }
// Not your package? Contribute to DefinitelyTyped (types/<pkg>/
// index.d.ts + tests); published automatically as @types/<pkg>.
// Validate packages with `@arethetypeswrong/cli` (attw) — checks
// ESM/CJS type resolution under every moduleResolution mode.
// Consumption: `npm i -D @types/lodash` — and since TS 6.0 list
// GLOBAL @types (node, jest) in tsconfig "types"; module @types like
// lodash are found by import resolution regardless.
//
// `isolatedDeclarations` (TS 5.5): requires explicit annotations on
// exports so .d.ts can be generated per-file by fast tools
// (oxc, swc) without running the type checker.

// ============================================================
// SECTION 6: TYPE-CHECKING JAVASCRIPT & JSDOC
// ============================================================
// tsconfig: "allowJs": true, "checkJs": true   (or `// @ts-check` per file)
// Per-line suppressions also work in .ts:
//   // @ts-ignore          — suppress next line's error (always)
//   // @ts-expect-error    — suppress, but ERROR if there's no error (prefer this)
//   // @ts-nocheck         — disable checking for the file
//
// JSDoc that TypeScript understands, in a .js file:
//   /** @type {string} */                let s;
//   /** @param {number} a @param {number} [b=1] @returns {number} */
//   function add(a, b = 1) { return a + b; }
//   /** @typedef {{ id: string, tags?: string[] }} Post */
//   /** @typedef {import("./types.js").User} User */   — import a TS type
//   /** @import { User } from "./types.js" */          — TS 5.5 import tag
//   /** @template T @param {T[]} xs @returns {T | undefined} */
//   function first(xs) { return xs[0]; }
//   /** @callback Predicate @param {string} s @returns {boolean} */
//   /** @satisfies {Config} */                           — TS 5.0
//   /** @overload @param {string} x @returns {string} */ — TS 5.0
//   /** @extends {Base<string>} */ class A extends Base {}
//   /** @implements {Printable} */ class B {}
//   /** @public @private @protected @readonly @override */
//   /** @deprecated use foo() */                         — strikethrough in editors
//   /** @enum {number} */ const Dir = { Up: 1, Down: 2 };
//   /** @this {HTMLElement} */
//   /** @throws {RangeError} */  (documentation only)
//   /** @see {@link foo} */      (links in hovers)
// Casts: /** @type {HTMLInputElement} */ (el)  — parentheses required.
//
// Generate .d.ts from JS: `tsc --allowJs --declaration --emitDeclarationOnly`.
// JS inference specifics: properties assigned in the constructor or
// methods are inferred as class members; CommonJS `module.exports`
// and `exports.x` patterns are recognised; object literals are
// "open-ended" (you can add properties later) in .js files.

// ============================================================
// SECTION 7: DECORATORS — STANDARD (TS 5.0+, TC39 stage 3)
// ============================================================
// A decorator is a function called with (value, context) where
// context.kind ∈ "class" | "method" | "getter" | "setter" |
// "field" | "accessor". It may return a replacement.
// Works WITHOUT any flag. `experimentalDecorators` selects the
// older TS-only proposal (different signature, plus parameter
// decorators and `emitDecoratorMetadata` — still used by NestJS,
// TypeORM, Angular <=19-era code).

// Method decorator: log calls. Generic over this/args/return.
function logged<This, Args extends unknown[], Ret>(
  target: (this: This, ...args: Args) => Ret,
  context: ClassMethodDecoratorContext<This, (this: This, ...args: Args) => Ret>,
) {
  const name = String(context.name);
  return function (this: This, ...args: Args): Ret {
    console.log(`→ ${name}(${args.join(", ")})`);
    const result = target.call(this, ...args);
    console.log(`← ${name} = ${String(result)}`);
    return result;
  };
}

// addInitializer: run code per instance (e.g. auto-bind methods).
function bound<This, T extends (this: This, ...a: any[]) => any>(_t: T, context: ClassMethodDecoratorContext<This, T>) {
  const name = context.name;
  context.addInitializer(function (this: This) {
    const self = this as Record<string | symbol, unknown>;
    self[name] = (self[name] as T).bind(this);
  });
}

// Decorator FACTORY — returns a decorator; takes configuration.
function range(min: number, max: number) {
  // Field decorator: return an initializer transform.
  return function <This>(_v: undefined, context: ClassFieldDecoratorContext<This, number>) {
    return function (this: This, initial: number) {
      if (initial < min || initial > max) {
        throw new RangeError(`${String(context.name)}=${initial} outside [${min}, ${max}]`);
      }
      return initial;
    };
  };
}

// `accessor` keyword (auto-accessor) + decorator: intercept get/set.
function clamp(min: number, max: number) {
  return function <This>(
    target: ClassAccessorDecoratorTarget<This, number>,
    _ctx: ClassAccessorDecoratorContext<This, number>,
  ): ClassAccessorDecoratorResult<This, number> {
    return {
      set(v) { target.set.call(this, Math.min(max, Math.max(min, v))); },
      get() { return target.get.call(this); },
    };
  };
}

// Class decorator: register class in a registry.
const registry = new Map<string, Function>();
function register(name: string) {
  return function <T extends abstract new (...a: any[]) => object>(cls: T, ctx: ClassDecoratorContext<T>) {
    ctx.addInitializer(() => { registry.set(name, cls); });
  };
}

@register("thermostat")
class Thermostat {
  @range(-40, 60) setpoint = 20;
  @clamp(0, 100) accessor humidity = 50;
  constructor(public readonly room: string) {}

  @logged
  adjust(delta: number) { this.setpoint += delta; return this.setpoint; }

  @bound
  describe() { return `${this.room}: ${this.setpoint}°C, ${this.humidity}%`; }
}
// Evaluation order: decorator expressions evaluate top-to-bottom;
// multiple decorators on one member APPLY bottom-to-top (like f(g(x))).
// Decorator METADATA (TS 5.2): context.metadata object, readable via
// Class[Symbol.metadata] — needs a Symbol.metadata polyfill on older runtimes.

// ============================================================
// SECTION 8: MIXINS
// ============================================================
// A mixin is a function: base class in, extended class out.
type Constructor<T = {}> = new (...args: any[]) => T;

function Timestamped<TBase extends Constructor>(Base: TBase) {
  return class extends Base { createdAt = new Date(0); };
}
function Activatable<TBase extends Constructor>(Base: TBase) {
  return class extends Base {
    isActive = false;
    activate() { this.isActive = true; return this; }
  };
}
// Constrained mixin — requires the base to have certain members:
type Named = Constructor<{ name: string }>;
function Greetable<TBase extends Named>(Base: TBase) {
  return class extends Base { greet() { return `hi ${this.name}`; } };
}

class UserBase { constructor(public name: string) {} }
const SmartUser = Greetable(Activatable(Timestamped(UserBase)));
const su = new SmartUser("ada").activate();

// Limitations: decorators can't add members visible to the type
// system (use mixins); static property types can't be generic per mixin
// application; class + interface merging is the "alternative pattern":
//   class Sprite {} ; interface Sprite extends Jumpable, Duckable {}
//   applyMixins(Sprite, [Jumpable, Duckable]); // copies prototype members

// ============================================================
// SECTION 9: JSX
// ============================================================
// Only in .tsx files. Options: "jsx": "react-jsx" (React 17+ automatic
// runtime, imports from "react/jsx-runtime"), "react-jsxdev",
// "preserve" (leave JSX for another tool), "react" (classic
// React.createElement), "react-native". `jsxImportSource` switches
// libraries: "preact", "solid-js", "@emotion/react", "hono/jsx".
//
//   type ButtonProps = { label: string; onClick?: () => void } & React.ComponentProps<"button">;
//   function Button({ label, ...rest }: ButtonProps) { return <button {...rest}>{label}</button>; }
//   <Button label="Save" disabled />            // props type-checked
//   const el = <div /> as HTMLElement;          // `as` only — <T>x is JSX syntax in .tsx
//   function Generic<T>(p: { items: T[]; render: (t: T) => JSX.Element }) {...}
//   <Generic<string> items={["a"]} render={(s) => <b>{s}</b>} />  // explicit type arg
//   const id = <T,>(x: T) => x;  // generic arrow in .tsx needs the trailing comma
//
// Type checking rules:
//   - Lowercase tag = INTRINSIC element; looked up on JSX.IntrinsicElements.
//   - Capitalised = VALUE-BASED element (function or class component).
//   - JSX.ElementAttributesProperty / ElementChildrenAttribute pick the
//     props/children property names; JSX.LibraryManagedAttributes
//     applies defaultProps/propTypes.
//   - The result type of any JSX expression is JSX.Element by default;
//     TS 5.1 allows components returning any JSX.ElementType (async
//     server components returning Promise<ReactNode>).

// ============================================================
// SECTION 10: END-TO-END — RUN THE DECORATED CLASS AND MIXIN
// ============================================================
const t = new Thermostat("lab");
t.adjust(3);
t.humidity = 150;                         // clamped by accessor decorator
const describe = t.describe;              // unbound reference — still works thanks to @bound
console.log(describe());                  // "lab: 23°C, 100%"
// @range validates the INITIAL value only — later assignments bypass it
// (use `accessor` + a decorator, like @clamp, to guard every write).
class Oven { @range(0, 300) temp = 500 }
try { new Oven(); } catch (e) { console.log((e as Error).message); } // "temp=500 outside [0, 300]"
console.log(registry.has("thermostat"), su.greet(), su.isActive, su.createdAt.toISOString());

// Ambient declarations above are type-only; reference them in types so
// noUnusedLocals stays quiet without touching runtime.
export type AmbientDemo = [typeof APP_BUILD, typeof track, analytics.Event, typeof analytics.sampleRate, Widget, typeof getWidget];
