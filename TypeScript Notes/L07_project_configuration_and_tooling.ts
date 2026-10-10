// ============================================================
// L07: Project Configuration, Compiler Options & Tooling
// ============================================================
// WHAT: The Handbook's "Project Configuration" section — what a
//       tsconfig.json is, the TSConfig Reference (grouped by
//       category), tsc CLI options, Project References and
//       `tsc --build`, integrating with build tools, configuring
//       watch, nightly builds — plus the "Tooling in 5 minutes"
//       and "Migrating from JavaScript" tutorials, and the
//       TypeScript 6.0 → 7.0 transition (native Go compiler).
// WHY:  Two identical .ts files can be "fine" or "full of errors"
//       depending only on tsconfig. Joining a codebase, the first
//       thing to read is its tsconfig. Build speed in monorepos
//       comes almost entirely from project references,
//       incremental builds, and (now) TS 7's parallel checker.
// LEVEL: Intermediate → Architect
// SOURCE: typescriptlang.org/tsconfig, .../docs/handbook/tsconfig-json.html,
//         .../compiler-options.html, .../project-references.html,
//         .../integrating-with-build-tools.html, .../configuring-watch.html,
//         TS 6.0 release notes, TS 7.0 announcement (Jul 2026)
// ============================================================
/*
CONCEPT OVERVIEW:
    tsconfig.json marks a project root and holds:
      "compilerOptions"  — how to check and emit
      "include"/"exclude"/"files" — which files form the program
      "extends"          — inherit from a base config (or several, TS 5.0)
      "references"       — other projects this one depends on
    Running `tsc` with no input files uses the nearest tsconfig.
    Since TS 6.0, `tsc file.ts` while a tsconfig exists is an
    ERROR (use `--ignoreConfig`).

PRODUCTION USE CASE:
    This lesson's runnable part is a tsconfig AUDITOR: feed it a
    parsed tsconfig and it reports options removed in TS 7.0,
    defaults that changed in 6.0, and missing safety flags — the
    exact checklist for upgrading a legacy repo.

COMMON MISTAKES:
    1. Assuming `strict` covers everything. It doesn't include
       noUncheckedIndexedAccess, exactOptionalPropertyTypes,
       noImplicitOverride, noPropertyAccessFromIndexSignature.
    2. `exclude` doesn't stop a file from being compiled if
       something IMPORTS it — exclude only filters `include`.
    3. Using tsc as a bundler or minifier. tsc type-checks and
       transpiles; bundling is esbuild/Vite/Rollup/webpack's job
       (`outFile` is removed in TS 7.0).
    4. Letting Babel/esbuild/swc transpile WITHOUT ever running
       `tsc --noEmit` in CI. Those tools strip types and check
       nothing.
    5. `skipLibCheck: false` in a big app — slow, and you'll be
       debugging other people's .d.ts files.
    6. Upgrading straight from TS 5.x to 7.0. Go through 6.0
       first: it warns about everything 7.0 removes.
*/

// ============================================================
// SECTION 1: tsconfig ANATOMY
// ============================================================
// {
//   "extends": ["@tsconfig/strictest/tsconfig.json", "./tsconfig.paths.json"],
//   "compilerOptions": { ... },
//   "include": ["src/**/*"],          // globs: *, ?, **/
//   "exclude": ["**/*.test.ts"],       // default: node_modules, bower_components, outDir
//   "files": ["src/global.d.ts"],      // explicit list (no globs)
//   "references": [{ "path": "../shared" }]
// }
// `${configDir}` template (TS 5.5) — paths relative to the FINAL
// config, so shared bases can say "outDir": "${configDir}/dist".
// Community bases: @tsconfig/node22, @tsconfig/strictest, @tsconfig/vite-react.
// `tsc --showConfig` prints the fully-resolved config.
// `tsc --init` (5.9+) writes a short, modern default config.

// ============================================================
// SECTION 2: TSCONFIG REFERENCE — BY CATEGORY
// ============================================================
// --- Type Checking ---
// strict                       umbrella (default TRUE since 6.0) enabling:
//   alwaysStrict, strictNullChecks, strictFunctionTypes,
//   strictBindCallApply, strictPropertyInitialization, noImplicitAny,
//   noImplicitThis, useUnknownInCatchVariables, strictBuiltinIteratorReturn (5.6)
// noUncheckedIndexedAccess     arr[i] / dict[k] include `| undefined`  ← recommend
// exactOptionalPropertyTypes   `x?: T` forbids explicit undefined
// noImplicitOverride           require `override` on overridden members
// noImplicitReturns            every code path must return
// noFallthroughCasesInSwitch   non-empty case must break/return
// noPropertyAccessFromIndexSignature  force obj["key"] for index-signature props
// noUnusedLocals / noUnusedParameters  (often left to the linter)
// allowUnreachableCode / allowUnusedLabels
//
// --- Modules (L05) ---
// module, moduleResolution, paths, rootDirs, typeRoots, types,
// allowImportingTsExtensions, rewriteRelativeImportExtensions (5.7),
// resolveJsonModule, resolvePackageJsonExports/Imports,
// customConditions, allowArbitraryExtensions, moduleSuffixes,
// noResolve, noUncheckedSideEffectImports (default true since 6.0)
//
// --- Emit ---
// outDir, rootDir (defaults to tsconfig dir since 6.0), declaration,
// declarationDir, declarationMap, emitDeclarationOnly, sourceMap,
// inlineSourceMap, inlineSources, removeComments, noEmit,
// noEmitOnError, importHelpers (+ tslib), newLine,
// stripInternal (drop `/** @internal */` from .d.ts),
// preserveConstEnums, emitBOM, mapRoot, sourceRoot
//
// --- JavaScript Support ---
// allowJs, checkJs, maxNodeModuleJsDepth
//
// --- Interop Constraints ---
// isolatedModules        each file transpilable alone (needed by esbuild/swc/Babel)
// verbatimModuleSyntax   imports/exports emitted exactly as written; supersedes
//                        importsNotUsedAsValues & preserveValueImports (removed)
// erasableSyntaxOnly     (5.8) ban enums, namespaces with values, parameter
//                        properties, `import =` — for Node type stripping
// isolatedDeclarations   (5.5) exports need explicit types (fast .d.ts gen)
// esModuleInterop, allowSyntheticDefaultImports (both forced on in 6.0+),
// forceConsistentCasingInFileNames, preserveSymlinks
//
// --- Language and Environment ---
// target (default es2025 in 6.0; es5 removed in 7.0), lib,
// jsx, jsxFactory, jsxFragmentFactory, jsxImportSource,
// experimentalDecorators, emitDecoratorMetadata,
// useDefineForClassFields (true for target >= ES2022), noLib,
// libReplacement (default false since 6.0), moduleDetection
//
// --- Projects ---
// composite, incremental, tsBuildInfoFile,
// disableSourceOfProjectReferenceRedirect, disableSolutionSearching,
// disableReferencedProjectLoad
//
// --- Completeness / Output formatting / Diagnostics ---
// skipLibCheck, skipDefaultLibCheck, pretty, noErrorTruncation,
// extendedDiagnostics, generateTrace (perf trace for Chrome/Perfetto),
// explainFiles, listFiles, listEmittedFiles, traceResolution

// ============================================================
// SECTION 3: tsc CLI
// ============================================================
// tsc                         build using ./tsconfig.json
// tsc -p configs/prod.json    use a specific project file
// tsc --noEmit                type-check only (the CI step)
// tsc -w / --watch            incremental rebuild on change
// tsc -b / --build            project-references build orchestrator
// tsc --ignoreConfig a.ts     compile loose files despite a tsconfig (6.0)
// tsc --listFilesOnly         which files are in the program
// tsc --generateTrace ./trace slow-build investigation
// tsc --extendedDiagnostics   time per phase, memory, file counts
// TS 7.0: --checkers <n>      parallel type-checker workers
//         --builders <n>      parallel project builds in -b mode
//         --singleThreaded    disable parallelism (constrained CI)
// Any compilerOption can be passed on the CLI: --strict, --target es2022, ...

// ============================================================
// SECTION 4: PROJECT REFERENCES & tsc --build
// ============================================================
// Split a monorepo into projects; each builds to .d.ts that
// dependents consume instead of re-checking source.
//
// packages/shared/tsconfig.json
//   { "compilerOptions": { "composite": true, "declarationMap": true,
//       "outDir": "dist", "rootDir": "src" }, "include": ["src"] }
// packages/api/tsconfig.json
//   { "compilerOptions": { "composite": true, "outDir": "dist" },
//     "references": [{ "path": "../shared" }] }
// tsconfig.json (solution file — builds nothing itself)
//   { "files": [], "references": [{ "path": "packages/shared" }, { "path": "packages/api" }] }
//
// composite ⇒ declaration on, rootDir defaults to config dir, every
// file must be matched by include/files, writes .tsbuildinfo.
// tsc -b: builds out-of-date projects in dependency order; behaves as
// if noEmitOnError is on. Flags: --verbose, --dry, --clean, --force, --watch.
// Caveats: editors need the referenced .d.ts (or use source redirect);
// timestamps after git checkout may need --force.
// `prepend` (concatenate outFile outputs) was removed in TS 5.5.

// ============================================================
// SECTION 5: INCREMENTAL & WATCH
// ============================================================
// "incremental": true writes .tsbuildinfo so the next `tsc` only
// rechecks changed files and their dependents.
// "watchOptions": {
//   "watchFile": "useFsEvents",          // or fixedPollingInterval, dynamicPriorityPolling...
//   "watchDirectory": "useFsEvents",
//   "fallbackPolling": "dynamicPriority",
//   "synchronousWatchDirectory": true,
//   "excludeDirectories": ["**/node_modules", "dist"]
// }
// Env var TSC_WATCHFILE / TSC_WATCHDIRECTORY override for Docker/WSL
// mounts where fs events don't propagate.

// ============================================================
// SECTION 6: INTEGRATING WITH BUILD TOOLS
// ============================================================
// Two separate jobs: TRANSPILE (fast, per-file, no types) and
// TYPE-CHECK (whole program). Modern stacks split them:
//   Vite / esbuild / swc / Babel / Bun / Deno / Node strip-types → transpile
//   tsc --noEmit (or tsc -b) in CI and editor                → check
// Babel: @babel/preset-typescript (no const enums across files, no
//   namespaces with values unless configured).
// webpack: ts-loader (transpileOnly + fork-ts-checker-webpack-plugin)
//   — note: no TS 7 loader until the stable API lands in 7.1.
// Jest: ts-jest or babel-jest; Vitest uses esbuild natively.
// Linting: typescript-eslint (typed rules use the TS program —
//   pinned to the 6.x API via @typescript/typescript6 until 7.1).
// MSBuild/.NET: Microsoft.TypeScript.MSBuild package with
//   <TypeScriptTarget>, <TypeScriptStrict> properties.

// ============================================================
// SECTION 7: MIGRATING FROM JAVASCRIPT
// ============================================================
// 1. Add tsconfig with "allowJs": true, "checkJs": false, "outDir".
// 2. Turn on checkJs (or `// @ts-check` per file) and fix JSDoc types.
// 3. Rename files .js → .ts one module at a time, leaves first.
// 4. Start with `strict: false` + noImplicitAny if the error count is
//    unmanageable; ratchet strict flags on per directory (separate
//    tsconfigs or a tool like `typescript-strict-plugin`).
// 5. Replace `require` with `import`, add @types packages, write
//    local .d.ts for untyped deps (L06).
// 6. Ban new `any` with typescript-eslint `no-explicit-any` and
//    `no-unsafe-*` rules; track remaining `any` count as a metric.

// ============================================================
// SECTION 8: TS 6.0 → 7.0 UPGRADE CHECKLIST
// ============================================================
// 6.0 (2026) changed DEFAULTS:
//   strict: true · module: esnext · target: es2025 (current-year ES)
//   noUncheckedSideEffectImports: true · libReplacement: false
//   rootDir: tsconfig dir · types: []  (list global @types explicitly)
//   `dom` lib now includes dom.iterable and dom.asynciterable
// 6.0 DEPRECATED (error; silence with "ignoreDeprecations": "6.0"):
//   target es5, downlevelIteration, moduleResolution node/node10/classic,
//   module amd/umd/systemjs/none, baseUrl, esModuleInterop:false,
//   allowSyntheticDefaultImports:false, alwaysStrict:false, outFile,
//   `module Foo {}` syntax, import `asserts`, `/// <reference no-default-lib>`
// 6.0 ADDED: --stableTypeOrdering (match 7.0's deterministic type
//   order), target/lib es2025, Temporal types, Map.getOrInsert,
//   RegExp.escape, `#/` subpath imports, bundler resolution + commonjs.
// 7.0 (July 2026): native Go port; full builds ~8-12x faster
//   (VS Code: 125.7s → 10.6s); ~18% less memory; LSP-based multi-
//   threaded language service; every 6.0 deprecation is a hard error
//   with no ignoreDeprecations escape. No stable programmatic API
//   until 7.1 — tools needing the compiler API (typescript-eslint
//   typed rules, Vue/Svelte/Angular tooling, ts-loader) keep using
//   6.x via `@typescript/typescript6` (`tsc6` binary + 6.0 API).
// During preview the native compiler was `@typescript/native-preview`
// with a `tsgo` binary; in 7.0 it IS `tsc`.

// ============================================================
// SECTION 9: RUNNABLE — A TSCONFIG UPGRADE AUDITOR
// ============================================================
type Severity = "removed-in-7" | "default-changed-in-6" | "recommendation";
interface Finding { severity: Severity; option: string; message: string }

// Loose shape: tsconfig values come from JSON, so treat them as unknown.
interface TsConfig {
  extends?: string | string[];
  compilerOptions?: Record<string, unknown>;
  include?: string[];
  references?: { path: string }[];
}

const lower = (v: unknown) => (typeof v === "string" ? v.toLowerCase() : v);

// Each rule inspects compilerOptions and may produce a finding.
type Rule = (opts: Record<string, unknown>) => Finding | undefined;

const removedIn7: Rule[] = [
  (o) => lower(o.target) === "es5" || lower(o.target) === "es3"
    ? { severity: "removed-in-7", option: "target", message: "ES5/ES3 output removed; use es2015+ and an external downleveler if you must support old browsers" } : undefined,
  (o) => o.downlevelIteration !== undefined
    ? { severity: "removed-in-7", option: "downlevelIteration", message: "only affected ES5 emit; delete it" } : undefined,
  (o) => ["node", "node10", "classic"].includes(String(lower(o.moduleResolution)))
    ? { severity: "removed-in-7", option: "moduleResolution", message: `"${String(o.moduleResolution)}" removed; use "nodenext" (Node) or "bundler"` } : undefined,
  (o) => ["amd", "umd", "system", "systemjs", "none"].includes(String(lower(o.module)))
    ? { severity: "removed-in-7", option: "module", message: `"${String(o.module)}" removed; emit ESM/CJS and bundle` } : undefined,
  (o) => o.baseUrl !== undefined
    ? { severity: "removed-in-7", option: "baseUrl", message: "removed; prefix each `paths` entry instead (paths no longer need baseUrl)" } : undefined,
  (o) => o.outFile !== undefined || o.out !== undefined
    ? { severity: "removed-in-7", option: "outFile", message: "concatenated output removed; use a bundler" } : undefined,
  (o) => o.esModuleInterop === false || o.allowSyntheticDefaultImports === false
    ? { severity: "removed-in-7", option: "esModuleInterop", message: "interop can no longer be disabled; audit `import * as x` of CJS default exports" } : undefined,
  (o) => o.alwaysStrict === false
    ? { severity: "removed-in-7", option: "alwaysStrict", message: "sloppy-mode emit removed" } : undefined,
  (o) => o.importsNotUsedAsValues !== undefined || o.preserveValueImports !== undefined
    ? { severity: "removed-in-7", option: "importsNotUsedAsValues", message: "replaced by verbatimModuleSyntax (removed back in 5.5)" } : undefined,
];

const defaultsChanged: Rule[] = [
  (o) => o.strict === undefined
    ? { severity: "default-changed-in-6", option: "strict", message: "unset now means TRUE; expect new errors in a previously non-strict repo" } : undefined,
  (o) => o.types === undefined
    ? { severity: "default-changed-in-6", option: "types", message: "unset now means []; globals like `process`/`describe` vanish until listed, e.g. [\"node\", \"jest\"]" } : undefined,
  (o) => o.rootDir === undefined && o.outDir !== undefined
    ? { severity: "default-changed-in-6", option: "rootDir", message: "now defaults to the tsconfig dir — output may move from dist/x.js to dist/src/x.js; set rootDir: \"src\"" } : undefined,
  (o) => o.module === undefined
    ? { severity: "default-changed-in-6", option: "module", message: "default switched from commonjs to esnext" } : undefined,
];

const recommendations: Rule[] = [
  (o) => o.noUncheckedIndexedAccess !== true
    ? { severity: "recommendation", option: "noUncheckedIndexedAccess", message: "not in `strict`; catches arr[i]/dict[k] being undefined" } : undefined,
  (o) => o.verbatimModuleSyntax !== true
    ? { severity: "recommendation", option: "verbatimModuleSyntax", message: "makes emitted imports predictable for every transpiler" } : undefined,
  (o) => o.skipLibCheck !== true
    ? { severity: "recommendation", option: "skipLibCheck", message: "skip checking dependency .d.ts files (faster, fewer third-party errors)" } : undefined,
];

function audit(config: TsConfig): Finding[] {
  const opts = config.compilerOptions ?? {};
  return [...removedIn7, ...defaultsChanged, ...recommendations]
    .map((rule) => rule(opts))
    .filter((f): f is Finding => f !== undefined);
}

function report(name: string, config: TsConfig): void {
  const findings = audit(config);
  const order: Severity[] = ["removed-in-7", "default-changed-in-6", "recommendation"];
  console.log(`\n=== ${name}: ${findings.length} finding(s)`);
  for (const sev of order) {
    for (const f of findings.filter((x) => x.severity === sev)) {
      console.log(`[${sev}] ${f.option}: ${f.message}`);
    }
  }
}

// A typical 2019-era config…
report("legacy-app", {
  compilerOptions: {
    target: "es5", module: "commonjs", moduleResolution: "node", baseUrl: ".",
    paths: { "@/*": ["src/*"] }, downlevelIteration: true, outDir: "dist", esModuleInterop: true,
  },
  include: ["src"],
});
// …and a config already ready for 7.0.
report("modern-service", {
  compilerOptions: {
    module: "nodenext", strict: true, types: ["node"], rootDir: "src", outDir: "dist",
    noUncheckedIndexedAccess: true, verbatimModuleSyntax: true, skipLibCheck: true,
  },
});

export { audit };
export type { Finding, TsConfig };
