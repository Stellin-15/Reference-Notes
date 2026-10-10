// ============================================================
// L05: Modules, Module Resolution, Namespaces & Declaration Merging
// ============================================================
// WHAT: Handbook "Modules" chapter, the Modules Reference
//       (Theory, Choosing Compiler Options, Reference, ESM/CJS
//       Interoperability appendix), and Reference pages
//       "Namespaces", "Namespaces and Modules", "Declaration
//       Merging", and "Triple-Slash Directives".
// WHY:  Module configuration is the #1 source of "works on my
//       machine" TypeScript breakage: wrong `module` setting,
//       missing `.js` extensions, default-import interop bugs,
//       dual-package hazards. Declaration merging is how you
//       augment third-party types (Express `Request.user`,
//       `Window` globals) safely.
// LEVEL: Intermediate → Advanced
// SOURCE: typescriptlang.org/docs/handbook/2/modules.html,
//         .../modules/theory.html, .../modules/guides/choosing-compiler-options.html,
//         .../modules/appendices/esm-cjs-interop.html,
//         .../declaration-merging.html, .../namespaces.html,
//         .../triple-slash-directives.html (TS 7.0, Oct 2026)
// ============================================================
/*
CONCEPT OVERVIEW:
    TypeScript does NOT run or bundle your code. Its module job is
    to (1) MODEL how the host (Node, a bundler, a browser) will
    resolve and load each import, so it can find the right types,
    and (2) EMIT the module format the host expects. The two key
    options mirror those jobs:
        "module"           → what host/format you're targeting
        "moduleResolution" → which resolution algorithm to model
    Since TS 5.x, "module" mostly implies the right resolution:
        nodenext / node18 / node20  → Node.js (file extensions required in ESM)
        esnext + "bundler"          → Vite, webpack, esbuild, tsx
        preserve                    → emit imports exactly as written

PRODUCTION USE CASE:
    Shipping an internal SDK used both by a Node service (ESM)
    and a legacy Node service (CommonJS), then augmenting Express
    and global types inside an app that consumes it.

COMMON MISTAKES:
    1. `import x from "./util"` in Node ESM — Node requires the
       extension: `./util.js` (yes, .js, even in a .ts file — TS
       maps it to util.ts). TS 5.7 `rewriteRelativeImportExtensions`
       lets you write `./util.ts` instead and rewrites on emit.
    2. Using `"moduleResolution": "bundler"` for a published
       library → output works in bundlers but breaks in Node.
    3. `import fs from "fs"` default-importing CommonJS without
       esModuleInterop (TS 6.0 makes interop always-on).
    4. Forgetting `import type` for type-only imports under
       `verbatimModuleSyntax` — the import survives into JS and
       may load a module (or crash) at runtime.
    5. Augmenting a module from a file that isn't itself a module
       — `declare module "express"` in a script file REPLACES the
       module's types instead of merging. Add `export {}`.
    6. Using namespaces to organise code in a module-based app.
       Modules already provide scoping; namespaces are legacy
       (except for type-only grouping and declaration files).
*/

// ============================================================
// SECTION 1: WHAT MAKES A FILE A MODULE
// ============================================================
// Any file with a top-level `import` or `export` is a MODULE: its
// declarations are file-scoped. A file without them is a SCRIPT:
// its declarations are GLOBAL (shared across every script in the
// program). `moduleDetection: "force"` treats every non-.d.ts file
// as a module regardless — the TS 5+ default for "auto" covers
// files under "type":"module" and .mts/.cts too.
// This file ends with exports, so it's a module.

// ============================================================
// SECTION 2: ES MODULE SYNTAX (what you should write)
// ============================================================
// --- math.ts ---
//   export const pi = 3.14;
//   export function absolute(n: number) { return n < 0 ? -n : n; }
//   export default class Calculator {}
//   export type Vec = [number, number];
//
// --- app.ts ---
//   import Calculator, { pi, absolute as abs } from "./math.js";
//   import * as math from "./math.js";            // namespace import
//   import type { Vec } from "./math.js";          // erased entirely
//   import { type Vec as V, pi as PI } from "./math.js"; // inline type modifier (TS 4.5)
//   import "./polyfills.js";                       // side-effect only
//   export * from "./math.js";                     // re-export
//   export * as utils from "./utils.js";           // namespaced re-export (TS 3.8)
//   export { default as Calc } from "./math.js";
//
// Import ATTRIBUTES (TS 5.3; `assert` form deprecated in 6.0):
//   import config from "./config.json" with { type: "json" };
//
// DEFERRED imports (TS 5.9, `--module esnext|preserve`):
//   import defer * as heavy from "./heavy.js";  // module runs on first property access
//
// Dynamic import — returns a Promise of the module namespace:
//   const { absolute } = await import("./math.js");
//
// Type-only imports with `import()` types — reference a type
// without an import statement:
//   let x: import("./math.js").Vec;

// ============================================================
// SECTION 3: COMMONJS SYNTAX IN TS
// ============================================================
// TS-specific "export =" / "import = require()" for CommonJS:
//   // legacy.cts
//   function legacy() {}
//   export = legacy;              // module.exports = legacy
//   // consumer.cts
//   import legacy = require("./legacy.cjs");
//
// In a .ts file compiled to CommonJS, ESM syntax is downlevelled:
//   export const a = 1  →  exports.a = 1
//   import { a } from "./x" → const x_1 = require("./x")
// TS 5.8 `--module nodenext` also allows `require()` of ESM from CJS,
// matching Node 22's require(esm) support.

// ============================================================
// SECTION 4: MODULE FORMAT DETECTION (Node semantics)
// ============================================================
// For the node16/node18/node20/nodenext modes, the output format of
// EACH FILE is decided like Node decides:
//   .mts  → always ESM          → emits .mjs
//   .cts  → always CommonJS     → emits .cjs
//   .ts   → nearest package.json "type": "module" → ESM, otherwise CJS
// Same file, different format, different rules: ESM files can't use
// `require`, CJS files can't use top-level await, and ESM imports of
// relative files need extensions.
//
// package.json "exports" (conditional exports) is respected:
//   "exports": {
//     ".": {
//       "import": { "types": "./dist/index.d.mts", "default": "./dist/index.mjs" },
//       "require": { "types": "./dist/index.d.cts", "default": "./dist/index.cjs" }
//     },
//     "./utils": "./dist/utils.js"
//   }
// "types" must come FIRST in each condition block — order matters.
// Subpath "imports" (#-prefixed, private aliases): "imports": { "#/*": "./src/*" }
// — `#/` prefix accepted since TS 6.0.

// ============================================================
// SECTION 5: CHOOSING COMPILER OPTIONS (official recommendations)
// ============================================================
// Node.js app (tsc emits, node runs output):
//   { "module": "nodenext", "verbatimModuleSyntax": true }
//   (implies moduleResolution nodenext, esModuleInterop, target esnext)
//
// Bundled app (Vite/webpack/esbuild) or tsx runner:
//   { "module": "esnext", "moduleResolution": "bundler", "noEmit": true,
//     "allowImportingTsExtensions": true, "allowArbitraryExtensions": true,
//     "customConditions": ["module"], "verbatimModuleSyntax": true }
//   — and do NOT set "type": "module" for bundler projects.
//
// Library published to npm:
//   { "module": "node18", "target": "es2020", "strict": true,
//     "verbatimModuleSyntax": true, "declaration": true,
//     "declarationMap": true, "sourceMap": true, "rootDir": "src", "outDir": "dist" }
//   Rationale: code that works in Node also works in bundlers; the
//   reverse isn't true ("infectiously bundler-only" code).
//
// Running .ts directly in Node (22.18+/23.6+ strip types by default):
//   { "module": "nodenext", "erasableSyntaxOnly": true,
//     "verbatimModuleSyntax": true, "rewriteRelativeImportExtensions": true,
//     "allowImportingTsExtensions": true, "noEmit": true }
//   — imports written as "./util.ts"; no enums/namespaces/parameter properties.
//
// Deprecated in 6.0 / removed in 7.0: moduleResolution "node" (node10)
// and "classic", module amd/umd/systemjs/none, baseUrl, outFile.

// ============================================================
// SECTION 6: MODULE RESOLUTION DETAILS
// ============================================================
// Relative imports ("./x", "../y") resolve against the importing file.
// Bare specifiers ("lodash") look in node_modules: package.json
// "exports" → "types"/"typings" → "main" → index.d.ts; then
// @types/lodash (DefinitelyTyped).
//
// "paths" maps specifiers (no longer needs baseUrl since TS 4.1):
//   "paths": { "@app/*": ["./src/*"] }
// paths affect TYPE resolution only — your runtime/bundler must
// apply the same mapping (Vite alias, Node subpath imports). Prefer
// package.json "imports" (#app/*) which Node understands natively.
//
// "types": [] — since TS 6.0, @types packages are NOT auto-included;
// list the globals you want: "types": ["node", "vitest/globals"].
//
// Debugging: `tsc --traceResolution` prints every lookup step;
// `tsc --explainFiles` says why each file is in the program.

// ============================================================
// SECTION 7: ESM ↔ CJS INTEROPERABILITY
// ============================================================
// A CommonJS module exports ONE value (module.exports). ESM has
// named exports + an optional default. Interop maps between them:
//   import fs from "fs"            — default import of CJS = module.exports
//   import * as fs from "fs"       — namespace import; under esModuleInterop
//                                    it's a wrapper object with `default` too
//   import { readFile } from "fs"  — named import of a CJS property
// Transpilers (Babel, old tsc) marked compiled ESM with
// `exports.__esModule = true` so a default import picks
// exports.default instead of the whole module.exports.
// Node's real ESM loader IGNORES __esModule: `import x from "cjs"`
// always gives module.exports. That's why the SAME library can give
// different default-import results under a bundler vs Node — the
// "default export confusion" this appendix describes.
// verbatimModuleSyntax + module nodenext makes TS model this
// precisely and forbids `export default` in CJS-format files.

// ============================================================
// SECTION 8: NAMESPACES (runnable — they emit code)
// ============================================================
// A namespace compiles to an IIFE that builds an object. Useful
// mostly in declaration files and for merging with classes/functions.
namespace Validation {
  export interface StringValidator { isAcceptable(s: string): boolean }
  const lettersRegexp = /^[A-Za-z]+$/;   // not exported → private to namespace
  const numberRegexp = /^[0-9]+$/;
  export class LettersOnlyValidator implements StringValidator {
    isAcceptable(s: string) { return lettersRegexp.test(s); }
  }
  export class ZipCodeValidator implements StringValidator {
    isAcceptable(s: string) { return s.length === 5 && numberRegexp.test(s); }
  }
}
// Namespaces can span blocks (and, in scripts, files with
// /// <reference path> — the pre-module era).
namespace Validation {
  export const version = "1.0";          // merged into the same object
}
// Nested namespace shorthand and aliases:
namespace Shapes.Polygons { export class Triangle { sides = 3 } }
import Polygons = Shapes.Polygons;        // alias — NOT a module import
const tri = new Polygons.Triangle();

// `module Foo {}` (the old spelling of namespace) is deprecated in 6.0.
// `declare module "x" {}` with a STRING name is unrelated and still
// correct — it declares an ambient module (L06).

// Namespaces vs modules — handbook guidance:
//   - Don't wrap a module's exports in a namespace ("needless namespacing").
//   - Don't use `/// <reference>` to link modules; use import.
//   - Namespaces can't be tree-shaken and aren't erasable syntax.

// ============================================================
// SECTION 9: DECLARATION MERGING
// ============================================================
// What each declaration creates:
//   Declaration   | Namespace | Type | Value
//   namespace     |     X     |      |   X
//   class         |           |  X   |   X
//   enum          |           |  X   |   X
//   interface     |           |  X   |
//   type alias    |           |  X   |
//   function      |           |      |   X
//   variable      |           |      |   X
// Things with the same name merge if their kinds allow.

// 9a. Interface + interface: members combine. For methods with the
// same name, LATER declarations' overloads come FIRST (except
// string-literal-parameter overloads, which bubble to the top).
interface BoxM { height: number; width: number }
interface BoxM { scale: number }
const bm: BoxM = { height: 5, width: 6, scale: 10 };
// Non-function members must be unique, or identical in type.

// 9b. Namespace + namespace: exported members combine; non-exported
// members are only visible inside their own block.

// 9c. Class + namespace: add static members / inner types.
class Album { label = new Album.AlbumLabel() }
namespace Album { export class AlbumLabel { name = "indie" } }

// 9d. Function + namespace: callable with properties (jQuery style).
function buildLabel(name: string): string { return buildLabel.prefix + name + buildLabel.suffix; }
namespace buildLabel { export const suffix = "!"; export const prefix = "Hello, "; }

// 9e. Enum + namespace: add methods to an enum.
enum Color { Red = 1, Green = 2, Blue = 4 }
namespace Color {
  export function mix(name: string): number {
    if (name === "yellow") return Color.Red + Color.Green;
    if (name === "white") return Color.Red + Color.Green + Color.Blue;
    return 0;
  }
}
// Disallowed: class + class (use mixins, L06).

// ============================================================
// SECTION 10: MODULE AUGMENTATION & GLOBAL AUGMENTATION
// ============================================================
// Patch types of an existing module — common for Express, Fastify,
// Vue, Pinia, and your own observable/plugin systems:
//
//   // types/express.d.ts
//   import "express";                  // makes this file a module
//   declare module "express-serve-static-core" {
//     interface Request { user?: { id: string; roles: string[] } }
//   }
//
// Rules: you can ADD declarations to existing ones (interfaces merge),
// but cannot add new TOP-LEVEL declarations to the module, and
// default exports can't be augmented.
//
// Global augmentation from inside a module:
declare global {
  interface Array<T> { toObservable?(): T[] }   // add to a built-in
  var __APP_VERSION__: string;                    // a build-time global (must be `var`)
}
globalThis.__APP_VERSION__ = "7.0.0";

// ============================================================
// SECTION 11: TRIPLE-SLASH DIRECTIVES
// ============================================================
// Single-line comments that act as compiler instructions; only valid
// at the TOP of a file (before any statements). Mostly for .d.ts files.
//   /// <reference path="./globals.d.ts" />  — include another file (scripts era)
//   /// <reference types="node" />            — depend on an @types package (in .d.ts)
//   /// <reference lib="es2022.array" />      — pull in a built-in lib file
//   /// <reference no-default-lib="true"/>    — deprecated in TS 6.0 (use --noLib)
//   /// <amd-module name="x" />               — AMD only; AMD removed in TS 7.0
// In application code, prefer tsconfig "types"/"lib" over these.
// TS 5.5+: `/// <reference types>` and `lib` directives found in your
// SOURCE files are no longer copied into emitted .d.ts files unless
// marked `preserve="true"`.

// ============================================================
// SECTION 12: END-TO-END — PLUGIN REGISTRY VIA AUGMENTATION
// ============================================================
// An extensible registry: plugins add their config type by
// augmenting an interface — the pattern Vue/Pinia/Fastify use.
// In a real repo the PluginConfigs interface lives in the SDK and
// each plugin package augments it with `declare module "sdk"`.
// Within one file we demonstrate the same merge on a local interface.
interface PluginConfigs {
  logger: { level: "debug" | "info" };
}
interface PluginConfigs {                // "plugin package" augmentation
  metrics: { endpoint: string; intervalMs: number };
}

class Registry {
  #configs: Partial<PluginConfigs> = {};
  register<K extends keyof PluginConfigs>(name: K, config: PluginConfigs[K]): this {
    this.#configs[name] = config;
    return this;
  }
  get<K extends keyof PluginConfigs>(name: K): PluginConfigs[K] | undefined {
    return this.#configs[name];
  }
}

const registry = new Registry()
  .register("logger", { level: "info" })
  .register("metrics", { endpoint: "https://m.test", intervalMs: 10_000 });
// registry.register("metrics", { endpoint: 1 }); // error: number isn't string

const validators: Record<string, Validation.StringValidator> = {
  zip: new Validation.ZipCodeValidator(),
  letters: new Validation.LettersOnlyValidator(),
};
for (const s of ["Hello", "98052", "101"]) {
  for (const [name, v] of Object.entries(validators)) {
    console.log(`"${s}" ${v.isAcceptable(s) ? "matches" : "does not match"} ${name}`);
  }
}
console.log(Validation.version, tri.sides, bm, new Album().label.name, buildLabel("Sam Smith"),
  Color.mix("white"), globalThis.__APP_VERSION__, registry.get("metrics")?.intervalMs);

export {};
