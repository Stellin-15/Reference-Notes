// WHAT: Four realistic HFT/systems-programming problems, each solved with
//       THREE genuinely different, individually defensible C++ approaches
//       drawn from L01-L65 -- with an explicit comparison table and
//       reasoning for why each answer is valid under different
//       constraints, in the same spirit as this repo's theory-domain
//       capstones (Classical ML Theory Notes L09, Deep Learning Theory
//       Notes L08, LLM Core Theory Notes L08).
// WHY:  "Which is the best way to do X in C++" is almost always a
//       malformed question in a latency-sensitive systems context --
//       every technique in this domain (lock-free vs. locked, allocator
//       strategy, kernel bypass vs. epoll) trades latency, throughput,
//       determinism, and engineering complexity against each other
//       differently. This lesson is deliberately built around
//       disagreement between defensible answers, since navigating that
//       disagreement under real constraints is the actual skill a senior
//       HFT engineer is hired for.
// LEVEL: Capstone -- read after L01-L65.
//
// This file, like the theory-domain capstones it mirrors, is NOT meant to
// compile and run as a program. It is reference material: read it, and
// before checking each comparison table, try reconstructing it yourself
// from memory using only L01-L65's techniques.

/*
============================================================================
CASE STUDY 1 -- THE HOT-PATH MARKET DATA QUEUE (PRODUCER: NETWORK THREAD,
CONSUMER: STRATEGY THREAD)
============================================================================

SETUP: a market-data feed handler (L58) must hand off parsed ticks to a
strategy thread (L61) with the lowest possible, most PREDICTABLE latency --
tail latency (p99.9) matters more than average latency, since a single
slow handoff can mean a stale price feeding a trading decision.

----------------------------------------------------------------------------
APPROACH A: A lock-free SPSC ring buffer (L38, L58)
----------------------------------------------------------------------------
  WHY VALID: single-producer/single-consumer is exactly the case a
  fixed-size ring buffer with atomic head/tail indices (L37, L38) handles
  optimally -- no locking, no dynamic allocation in the hot path (L44),
  and the access pattern (sequential, cache-friendly) plays well with
  prefetching and cache-line layout (L42, L43).
  COST: rigid to exactly one producer and one consumer -- if a second
  strategy thread later needs the same tick stream, this structure can't
  be safely shared without either a second independent queue (duplicating
  memory bandwidth) or a redesign to MPSC/MPMC, which is a materially
  harder lock-free problem (more complex CAS retry logic, more subtle
  memory-ordering requirements, L37).

----------------------------------------------------------------------------
APPROACH B: `std::condition_variable`-based producer-consumer with a
locked queue (L36, L39)
----------------------------------------------------------------------------
  WHY VALID: dramatically simpler to reason about correctness for
  (standard mutex + condvar semantics, well-understood, easy to code-
  review), and if the strategy thread's OWN processing time per tick
  already dominates the latency budget, the mutex/condvar overhead may be
  genuinely negligible relative to that processing cost -- optimizing the
  handoff further would be solving the wrong bottleneck.
  COST: `condition_variable::notify_one()` risks OS-scheduler-mediated
  wake-up latency (potentially microseconds, and NOT tightly bounded --
  the OS scheduler makes no hard real-time latency guarantee) -- for a
  strategy where price staleness of even a few microseconds is
  competitively meaningful, this variance in wake-up latency, not just
  its average, is a real, possibly disqualifying cost.

----------------------------------------------------------------------------
APPROACH C: SPSC ring buffer PLUS a busy-spin consumer using `_mm_pause()`
(L38, L41) instead of blocking
----------------------------------------------------------------------------
  WHY VALID: eliminates approach B's OS-scheduler wake-up latency
  entirely -- the consumer thread never sleeps, so there's no wake-up
  cost to pay at all, and `_mm_pause()` (L41) specifically reduces power
  draw and avoids the memory-order violation penalty a naive tight spin
  loop can trigger on some architectures, versus a naive `while(true){}`.
  COST: burns an entire CPU core continuously, 100% utilization,
  regardless of actual message rate -- a real, ongoing infrastructure
  cost (that core is unavailable for anything else) that's only justified
  when the latency improvement over B is competitively meaningful enough
  to pay for a dedicated, pinned core (L40) per hot queue.

COMPARISON TABLE (Case Study 1):
  | Approach | p99.9 latency | Code complexity | CPU cost | Multi-consumer? |
  |----------|----------------|--------------------|--------------|--------------------|
  | A: SPSC ring buffer, blocking-free | Low, but consumer must poll | Medium | Low (idle when empty, if polled cooperatively) | No |
  | B: locked queue + condvar | Higher, OS-scheduler-dependent | Low | Low | Yes (easily extends to MPMC) |
  | C: SPSC ring buffer + busy-spin | Lowest, most predictable | Medium | Highest (100% of one core) | No |
  For genuinely latency-critical hot paths, C is the standard HFT choice
  DESPITE its CPU cost -- that cost is usually an accepted, budgeted
  tradeoff, not an oversight, in this specific domain.


============================================================================
CASE STUDY 2 -- MEMORY MANAGEMENT FOR PER-ORDER OBJECTS IN THE MATCHING
ENGINE
============================================================================

SETUP: the matching engine (L55) creates and destroys millions of Order
objects (L53) per trading session, and heap allocation/deallocation
latency variance is a direct source of tail-latency risk (L44's "no-malloc
hot path" concern).

----------------------------------------------------------------------------
APPROACH A: A fixed-size, pre-allocated object pool (`OrderPool<T>`, L22,
L44)
----------------------------------------------------------------------------
  WHY VALID: allocates ALL memory upfront (at startup, off the hot path),
  and "allocation" during trading reduces to popping a free-list index --
  O(1), no syscall, no heap-metadata-lock contention, and fully
  deterministic latency, exactly the guarantee L44 is built around.
  COST: requires knowing (or conservatively over-provisioning) the
  MAXIMUM number of simultaneously-live orders upfront -- a genuine
  capacity-planning exercise, and if that upper bound is exceeded (an
  unusual but not impossible burst), the system needs an explicit,
  tested fallback behavior (reject new orders? reuse the pool
  destructively? both require deliberate design, not an afterthought).

----------------------------------------------------------------------------
APPROACH B: `std::unique_ptr` with the DEFAULT allocator (L14, L23), no
custom pooling
----------------------------------------------------------------------------
  WHY VALID: simplest to implement correctly, gets automatic RAII
  cleanup (L15, L23) with zero custom memory-management code to audit
  for bugs -- for a research/backtesting build (L64) where wall-clock
  performance doesn't need to match live-trading requirements, the
  engineering-simplicity win is real and the allocator-latency cost is
  irrelevant to the actual use case.
  COST: the default allocator's latency is NOT deterministic (varies
  with heap fragmentation state, can occasionally take a slow path,
  e.g. requesting new pages from the OS) -- categorically unacceptable
  for the LIVE trading hot path this case study's setup describes,
  which is exactly why this approach is valid ONLY for the backtesting/
  research context, not live trading.

----------------------------------------------------------------------------
APPROACH C: A slab/arena allocator (L44) sized per trading session, reset
(not individually freed) at session boundaries
----------------------------------------------------------------------------
  WHY VALID: if orders' lifetimes are naturally bounded by the TRADING
  SESSION (or some other natural batch boundary) rather than needing
  individual, unpredictable-timing destruction, an arena that's simply
  reset (bulk-deallocated) at the boundary avoids BOTH approach A's
  upfront-capacity-planning rigidity (arenas can grow, at some cost) and
  approach B's per-allocation latency variance.
  COST: individual objects can't be freed early and their memory
  reclaimed mid-session without a more complex arena design (e.g. a
  generational/segmented arena) -- if orders' lifetimes are actually
  highly variable and NOT well-approximated by "lives until session end,"
  this wastes memory holding dead orders' slots until the whole arena
  resets, a real cost this approach's simplicity trades away.

COMPARISON TABLE (Case Study 2):
  | Approach | Allocation determinism | Capacity planning burden | Fits variable-lifetime orders? |
  |----------|---------------------------|------------------------------|-------------------------------------|
  | A: fixed object pool | Highest | High (must size upfront) | Yes, if pool sized correctly |
  | B: default allocator | Lowest | None | Yes, but with latency-variance cost |
  | C: session-scoped arena | High | Medium (arena growth policy) | Only if lifetimes track session boundaries |
  Live trading systems overwhelmingly use A; B is legitimate ONLY outside
  the live hot path (backtesting, tooling); C is a genuine third option
  when the lifetime-pattern assumption actually holds.


============================================================================
CASE STUDY 3 -- CHOOSING A CONCURRENCY MODEL FOR THE RISK-CHECK LAYER
============================================================================

SETUP: pre-trade risk checks (L59) must validate every outgoing order
against position limits and kill-switch state BEFORE it reaches the
exchange gateway -- correctness (never letting a limit-violating order
through) is non-negotiable, and latency is important but secondary to
correctness here, unlike Case Study 1's pure-speed hot path.

----------------------------------------------------------------------------
APPROACH A: A single-threaded risk engine, all order flow serialized
through it
----------------------------------------------------------------------------
  WHY VALID: eliminates an entire class of concurrency bugs by
  construction -- there is no shared mutable risk-state race condition to
  reason about AT ALL if only one thread ever touches it, a strong,
  provable correctness property that's genuinely hard to achieve with
  any concurrent design without extremely careful auditing.
  COST: becomes a hard throughput ceiling and a single point of latency
  contention if order volume is high enough that a single core's risk-
  check throughput is the binding constraint -- a real scaling limit
  with no incremental fix short of a fundamentally different design.

----------------------------------------------------------------------------
APPROACH B: Sharded risk engines, one per instrument/symbol group, each
single-threaded internally (combining L35's threading model with L17's
encapsulation)
----------------------------------------------------------------------------
  WHY VALID: preserves approach A's "no shared mutable state within a
  shard" correctness property WHILE scaling throughput horizontally
  across shards (different symbols' orders can be risk-checked fully in
  parallel, since they don't share state) -- often the natural sweet
  spot when risk limits are genuinely PER-SYMBOL or per-symbol-group
  rather than cross-symbol.
  COST: any risk check that's inherently CROSS-SYMBOL (e.g. an aggregate
  portfolio-wide position limit spanning many symbols) breaks the
  sharding assumption and needs a separate, explicitly cross-shard
  mechanism (a shared atomic counter, L37, or a periodic reconciliation
  pass) -- not something the sharded design provides "for free."

----------------------------------------------------------------------------
APPROACH C: A single shared risk-state structure protected by fine-
grained locks or atomics (L36, L37) per position/limit entry
----------------------------------------------------------------------------
  WHY VALID: handles BOTH per-symbol and cross-symbol risk checks against
  the SAME unified state without approach B's shard-boundary complication,
  and fine-grained (per-entry, not one global mutex) locking limits
  contention to genuinely conflicting accesses rather than serializing
  everything.
  COST: by far the hardest of the three to get provably correct --
  fine-grained locking introduces real deadlock risk (L36's ordering
  discipline becomes load-bearing) and subtle lost-update bugs are far
  easier to introduce and far harder to catch in code review than in
  either single-threaded approach, a genuine, elevated engineering-risk
  cost for a component where correctness is explicitly non-negotiable.

COMPARISON TABLE (Case Study 3):
  | Approach | Correctness risk | Throughput ceiling | Handles cross-symbol limits? |
  |----------|----------------------|--------------------------|------------------------------------|
  | A: single-threaded | Lowest | Hard ceiling, one core | Yes, trivially (all state local) |
  | B: sharded by symbol | Low (within a shard) | Scales with shard count | Only with extra cross-shard mechanism |
  | C: fine-grained locked shared state | Highest (real bug risk) | Scales with contention level | Yes, natively |
  Given correctness is stated as non-negotiable here, many teams would
  start with A or B and only reach for C if a genuine, unavoidable
  cross-symbol requirement AND a throughput ceiling both bind
  simultaneously -- C's correctness risk should be a deliberate, reviewed
  tradeoff, not a default.


============================================================================
CASE STUDY 4 -- SERIALIZING/PARSING INCOMING MARKET DATA (FIX VS. BINARY
PROTOCOLS, L56, L57)
============================================================================

SETUP: a feed handler needs to parse an incoming exchange protocol as
fast as possible, and the exchange offers BOTH a FIX-based feed and a
raw binary (ITCH-style) feed for the same underlying data.

----------------------------------------------------------------------------
APPROACH A: Parse the FIX feed with a zero-copy, tag-value scanner (L56)
----------------------------------------------------------------------------
  WHY VALID: FIX is text-based and self-describing (tag=value pairs) --
  genuinely easier to debug in production (a captured packet is human-
  readable without a separate decoder tool) and more forgiving of minor
  exchange-side protocol version drift (an unexpected new tag can often
  be safely skipped rather than corrupting the whole parse).
  COST: even a well-optimized zero-copy FIX parser (L56) does
  meaningfully more per-byte work than a binary parser -- text parsing
  (tag/delimiter scanning, ASCII-to-numeric conversion) is intrinsically
  more expensive than reading a fixed-offset binary field directly.

----------------------------------------------------------------------------
APPROACH B: Parse the binary ITCH-style feed via `reinterpret_cast` onto
a packed struct (L57)
----------------------------------------------------------------------------
  WHY VALID: the fastest possible parse -- for a well-defined fixed
  binary layout, "parsing" reduces to a pointer cast and struct-field
  reads, with none of FIX's tag-scanning/ASCII-conversion overhead --
  the clear latency-optimal choice when the exchange's binary feed
  layout is stable and well-documented.
  COST: fragile to ANY layout mismatch (a misaligned struct, an
  unexpected padding byte, an exchange-side protocol version bump) --
  errors here are silent data CORRUPTION (reading the wrong bytes as the
  wrong field), not a parse exception, which is a categorically more
  dangerous failure mode than FIX's more gracefully-degrading text
  format, and demands correspondingly more rigorous testing/validation
  discipline (checksums, sequence-number gap detection, L58) to catch.

----------------------------------------------------------------------------
APPROACH C: Support BOTH feeds, using FIX as a redundant/backup path and
binary as the primary hot path
----------------------------------------------------------------------------
  WHY VALID: gets binary's latency advantage for the primary trading
  path WHILE retaining FIX's easier debuggability and (if the exchange's
  binary and FIX feeds are independently delivered) genuine redundancy
  against a feed-specific outage or gap -- a real operational resilience
  benefit neither single-feed approach provides alone.
  COST: doubles the feed-handling code path to build, test, and
  maintain, and requires an explicit reconciliation/failover policy
  (when do you trust FIX over binary, or vice versa, if they disagree?)
  -- a nontrivial design and operational burden most smaller trading
  operations wouldn't take on unless the redundancy is specifically
  justified by the strategy's risk tolerance for a feed outage.

COMPARISON TABLE (Case Study 4):
  | Approach | Parse latency | Debuggability | Failure mode if corrupted | Redundancy |
  |----------|-------------------|-------------------|--------------------------------|----------------|
  | A: FIX, zero-copy | Higher | Best (human-readable) | Graceful (parse error) | None |
  | B: binary, reinterpret_cast | Lowest | Worst (needs tooling) | Dangerous (silent corruption) | None |
  | C: both, binary primary | Lowest (primary path) | Good (FIX for debugging) | Mitigated (failover) | Yes |
  Pure-speed HFT strategies default to B; anything valuing operational
  resilience over the last few nanoseconds should seriously weigh C
  despite its added engineering cost.
*/

int main() {
    // This file is reference material, not a runnable program -- see the
    // WHAT/WHY header and the four case studies above. Nothing to execute.
    return 0;
}
