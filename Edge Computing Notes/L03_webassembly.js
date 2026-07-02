// ============================================================
// L03: WebAssembly (WASM) at the Edge
// ============================================================
// WHAT: A binary instruction format for a stack-based virtual machine —
//       near-native execution speed, language-agnostic, sandboxed by design.
// WHY:  Edge runtimes (V8 isolates) run JS fast, but CPU-heavy work
//       (image resizing, crypto, ML inference) is much faster compiled to
//       WASM from Rust/C/Go than written in JS. WASM's sandboxing model
//       also matches the edge's "run untrusted-ish code cheaply" requirement.
// LEVEL: Intermediate
// ============================================================

/*
CONCEPT OVERVIEW:
WASM modules are a stack machine: instructions push/pop values on an
operand stack (no general-purpose registers exposed at the bytecode level).
Memory is a single contiguous, sandboxed "linear memory" — a resizable
ArrayBuffer the module reads/writes via explicit load/store instructions.
Nothing in a WASM module can touch memory outside its own linear memory or
call arbitrary host functions — only functions explicitly imported are
callable, and only functions explicitly exported are callable from outside.
This is what makes running third-party or user-submitted WASM at the edge
safe in a way that arbitrary native code never could be.

WASI (WebAssembly System Interface) standardizes OS-like capabilities
(file access, clocks, random) as a set of importable functions, using a
CAPABILITY model: a WASM module can only open files/sockets it was
explicitly granted a handle to at instantiation time, not anything on the
host filesystem by path.

PRODUCTION USE CASE:
Cloudflare Workers can bundle a WASM module compiled from Rust for
CPU-intensive work (e.g. image transformation, a fast regex/parsing engine)
alongside the JS "glue" code that handles routing and I/O. The JS layer
stays for what it's good at (fast startup, ergonomic async I/O); the WASM
layer handles the hot loop where JS's dynamic typing overhead would matter.

COMMON MISTAKES:
  - Assuming WASM is always faster than JS — for I/O-bound or
    small/one-shot computations, the JS<->WASM boundary crossing overhead
    (copying data into linear memory) can dominate and make WASM SLOWER.
  - Passing complex JS objects directly to WASM — you can only pass
    numbers across the boundary natively; strings/objects need manual
    serialization into linear memory (or a helper like wasm-bindgen).
  - Not accounting for WASM's fixed/growable-but-bounded memory model when
    processing large payloads — a naive image-processing WASM module can
    hit its memory ceiling on a large enough input.
*/

// ------------------------------------------------------------------
// 1. Writing WASM in Rust — the dominant edge-WASM toolchain
// ------------------------------------------------------------------
const RUST_WASM_SOURCE = `
// src/lib.rs — compiled with wasm-pack to a .wasm + JS glue module
use wasm_bindgen::prelude::*;

// #[wasm_bindgen] generates the marshalling code so this function is
// callable from JS with normal-looking arguments (wasm-pack handles the
// string encoding into/out of linear memory for you).
#[wasm_bindgen]
pub fn resize_image_luma(pixels: &[u8], width: u32, height: u32, factor: u32) -> Vec<u8> {
    // A hot loop like this is exactly the case WASM wins: tight,
    // predictable-shape numeric work with no GC pauses, no dynamic
    // dispatch overhead — Rust compiles this to near-native machine code.
    let new_w = width / factor;
    let new_h = height / factor;
    let mut out = Vec::with_capacity((new_w * new_h) as usize);
    for y in 0..new_h {
        for x in 0..new_w {
            let src_idx = (y * factor * width + x * factor) as usize;
            out.push(pixels[src_idx]); // simple nearest-neighbor downsample
        }
    }
    out
}
`;

const WASM_PACK_BUILD = `
# Compiles Rust -> WASM binary + JS bindings, targeting a bundler/worker runtime.
wasm-pack build --target bundler --release
# Output: pkg/my_module_bg.wasm, pkg/my_module.js (the glue code)
`;

// ------------------------------------------------------------------
// 2. Instantiating and calling WASM from a Cloudflare Worker
// ------------------------------------------------------------------
const WORKER_WASM_USAGE = `
// index.js — Cloudflare Workers can import a .wasm module directly via
// a build-time binding (wrangler.toml [[wasm_modules]] or module rules).
import wasmModule from "./pkg/my_module_bg.wasm";
import { resize_image_luma } from "./pkg/my_module.js";

export default {
  async fetch(request) {
    const imageBytes = new Uint8Array(await request.arrayBuffer());

    // Crossing the JS -> WASM boundary: the Uint8Array is copied into
    // the WASM module's linear memory by the generated glue code.
    const resized = resize_image_luma(imageBytes, 800, 600, 4);

    return new Response(resized, {
      headers: { "content-type": "application/octet-stream" },
    });
  },
};
`;

// ------------------------------------------------------------------
// 3. Manual instantiation without a bundler (raw WebAssembly API)
// ------------------------------------------------------------------
const RAW_WASM_INSTANTIATION = `
// Shows what wasm-bindgen's glue code does under the hood — useful to
// understand for debugging or for languages without wasm-bindgen tooling.
const wasmResponse = await fetch("module.wasm");
const { instance } = await WebAssembly.instantiateStreaming(wasmResponse, {
  env: {
    // "imports" — host functions the WASM module is allowed to call.
    // A module compiled with NO imports literally cannot do I/O at all —
    // this is the sandboxing property in action.
    log: (ptr, len) => {
      const bytes = new Uint8Array(instance.exports.memory.buffer, ptr, len);
      console.log(new TextDecoder().decode(bytes));
    },
  },
});

// Writing input into the module's linear memory manually:
const inputPtr = instance.exports.alloc(1024);          // ask WASM to allocate
const mem = new Uint8Array(instance.exports.memory.buffer);
mem.set(new TextEncoder().encode("hello"), inputPtr);    // copy bytes in
const resultPtr = instance.exports.process(inputPtr, 5); // call exported fn
`;

// ------------------------------------------------------------------
// 4. WASI — system interface for non-browser WASM (server/edge runtimes)
// ------------------------------------------------------------------
const WASI_NOTES = `
WASI gives a WASM module POSIX-like capabilities (open a file, read a
clock, get random bytes) WITHOUT giving it ambient authority over the host.
A WASI runtime (Wasmtime, WasmEdge) grants access by explicitly "preopening"
specific directories/handles at instantiation — the module can only see
what it was handed, never the full host filesystem by path traversal.

  wasmtime run --dir=/data::/sandboxed-data my_module.wasm
  # Inside the module, opening "/sandboxed-data/file.txt" works.
  # Opening "/etc/passwd" or any path outside the preopened dir fails —
  # there is no syscall path that reaches it.

This capability model is why edge platforms (e.g. Fastly Compute@Edge) use
WASI/WASM as their sandboxing primitive instead of full containers: strong
isolation with near-zero cold-start cost.
`;

// ------------------------------------------------------------------
// 5. Other language toolchains
// ------------------------------------------------------------------
const OTHER_TOOLCHAINS = {
  C_CPP: "Emscripten compiles C/C++ to WASM + JS glue, historically the "
    + "original WASM toolchain (used for porting existing native codebases "
    + "like image/video codecs, physics engines).",
  Go: "TinyGo (not the standard Go compiler — its WASM output is too large "
    + "for edge use) produces small WASM binaries suited to edge size limits.",
  AssemblyScript: "A TypeScript-like syntax that compiles directly to WASM "
    + "— popular for teams who want WASM's performance without learning "
    + "Rust/C, at the cost of less mature tooling/ecosystem.",
};

// ------------------------------------------------------------------
// 6. The Component Model — where WASM is heading
// ------------------------------------------------------------------
const COMPONENT_MODEL_NOTE = `
The WASM Component Model standardizes HIGH-LEVEL types (strings, records,
lists, variants) crossing module boundaries, instead of everything being
"pass numbers through linear memory and manually serialize." It also
enables COMPOSING WASM modules written in different languages together as
"components" with typed interfaces (WIT - WASM Interface Types) — e.g. a
Rust image-processing component and a Go routing component linked
together, each unaware the other is written in a different language.
`;

module.exports = {
  RUST_WASM_SOURCE,
  WASM_PACK_BUILD,
  WORKER_WASM_USAGE,
  RAW_WASM_INSTANTIATION,
  WASI_NOTES,
  OTHER_TOOLCHAINS,
  COMPONENT_MODEL_NOTE,
};

/*
TRADING/PRODUCTION CONTEXT EXAMPLE:
A market-data edge gateway needs to decompress and validate incoming
FIX/ITCH-style binary messages before routing them, at every one of 100+
edge PoPs. Doing the bit-level parsing in JS is measurably slower than a
Rust-compiled WASM parser due to JS's dynamic typing overhead on
byte-level operations; the WASM module handles decode+validate in a tight
loop, while the surrounding JS handles routing, auth, and async I/O — each
layer doing what it's actually good at.
*/
