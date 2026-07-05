# ============================================================
# L04: Node.js and Express — Backend JavaScript
# ============================================================
# WHAT: Node.js's event-loop execution model, and Express — the
#       dominant minimal web framework for building REST APIs in
#       Node.js — routing, middleware, and error handling.
# WHY: This repo's backend coverage (FastAPI, Go, System Design Notes)
#      is entirely non-JavaScript. A genuinely full-stack developer
#      frequently needs a Node.js backend specifically to share language
#      (and sometimes code/types) with a JavaScript/TypeScript frontend
#      (L01-L03) — this lesson covers that backend option directly.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
NODE.JS runs JavaScript OUTSIDE the browser, on a SINGLE-THREADED EVENT
LOOP — rather than spawning a new OS thread per request (a traditional
multi-threaded server model), Node handles many concurrent connections
on ONE thread by NEVER BLOCKING on I/O: a database query, a file read,
or an HTTP call to another service is issued ASYNCHRONOUSLY, and the
event loop moves on to handle OTHER requests while waiting, resuming
this request's handler via a CALLBACK (or, in modern code, a resolved
`Promise`/`async`-`await`) once the I/O operation completes. This makes
Node.js genuinely well-suited to I/O-heavy workloads (many concurrent
requests, each spending most of its time waiting on a database/API call
rather than doing CPU-heavy computation) — but a CPU-INTENSIVE
operation (heavy computation, not I/O) BLOCKS the entire single event
loop, stalling EVERY other concurrent request, a real and important
limitation distinct from a multi-threaded server model.

EXPRESS is the dominant minimal web framework built on Node's HTTP
module — providing ROUTING (mapping HTTP method + path combinations to
handler functions) and a MIDDLEWARE pipeline (functions that run, in
order, BEFORE a route's actual handler — used for cross-cutting
concerns like authentication, logging, request body parsing, and error
handling, directly analogous to FastAPI's dependency injection/
middleware concepts, this repo's FastAPI Notes L02/L04, but with
Express's own distinct middleware-chaining API shape).

ASYNC/AWAIT is modern JavaScript's syntax for writing asynchronous code
that READS like synchronous code, while still being NON-BLOCKING under
the hood — `await` pauses execution of the CURRENT function (not the
entire event loop) until a Promise resolves, letting OTHER requests
continue being processed on the event loop in the meantime. ERROR
HANDLING with async/await in Express requires DELIBERATE care: an
error thrown inside an `async` route handler does NOT automatically
propagate to Express's error-handling middleware the way a SYNCHRONOUS
throw does — it must be explicitly CAUGHT and passed to `next(error)`,
or wrapped in a helper that does this automatically, or it becomes an
UNHANDLED PROMISE REJECTION that can crash the process.

PRODUCTION USE CASE:
An API gateway service (directly relevant to this repo's Auth &
Security Notes L13's multi-tenant gateway concepts) built in Express
handles many concurrent requests to various backend microservices — its
I/O-bound nature (mostly waiting on those backend calls, not doing heavy
local computation) is exactly the workload shape Node's event-loop model
handles efficiently, while a genuinely CPU-heavy operation (e.g. image
processing) is deliberately offloaded to a WORKER THREAD or a separate
service, specifically to avoid blocking the gateway's event loop for
every other concurrent request.

COMMON MISTAKES:
- Performing CPU-intensive synchronous work (a large synchronous loop,
  heavy computation) directly in a request handler — this blocks the
  ENTIRE event loop, stalling every other concurrent request for the
  duration, a fundamentally different failure mode than a slow database
  query (which is async and doesn't block other requests).
- Throwing an error inside an `async` Express route handler without
  catching it and passing it to `next(error)` — this becomes an
  unhandled promise rejection instead of triggering Express's error-
  handling middleware, a subtle and easy-to-miss correctness gap.
- Not ordering MIDDLEWARE correctly — Express middleware runs in the
  EXACT order it's registered; an authentication-check middleware
  registered AFTER a route handler that assumes the user is
  authenticated provides no actual protection.
"""

import textwrap


# ------------------------------------------------------------------
# 1. A minimal Express server — routing and middleware
# ------------------------------------------------------------------
EXPRESS_BASIC_EXAMPLE = textwrap.dedent("""\
    const express = require('express');
    const app = express();

    app.use(express.json());   // MIDDLEWARE: parses JSON request bodies
                                  // — runs on EVERY request, before route handlers

    // Custom middleware — logging, runs for every request
    app.use((req, res, next) => {
      console.log(`${req.method} ${req.path}`);
      next();   // MUST call next() to pass control to the next
                  // middleware/handler — omitting this HANGS the request
    });

    // Route: GET /api/agents/:id — :id is a URL PARAMETER
    app.get('/api/agents/:id', async (req, res, next) => {
      try {
        const agent = await db.findAgent(req.params.id);
        if (!agent) return res.status(404).json({ error: 'Not found' });
        res.json(agent);
      } catch (err) {
        next(err);   // REQUIRED — async errors don't auto-propagate;
                      // must be explicitly passed to Express's error handling
      }
    });

    app.listen(3000, () => console.log('Server running on port 3000'));
""")

# ------------------------------------------------------------------
# 2. Authentication middleware — ordering matters
# ------------------------------------------------------------------
AUTH_MIDDLEWARE_EXAMPLE = textwrap.dedent("""\
    function requireAuth(req, res, next) {
      const token = req.headers.authorization?.split(' ')[1];
      if (!token) return res.status(401).json({ error: 'Unauthorized' });

      try {
        req.user = verifyJwt(token);   // attach decoded user to the request
        next();                          // proceed to the ACTUAL route handler
      } catch {
        res.status(401).json({ error: 'Invalid token' });
      }
    }

    // CORRECT: auth middleware registered BEFORE the protected route
    app.get('/api/admin/dashboard', requireAuth, (req, res) => {
      res.json({ message: `Welcome, ${req.user.name}` });
    });

    // WRONG ordering — this middleware would need to run BEFORE this
    // route for the route to actually be protected; registering it
    // globally AFTER this route (app.use(requireAuth) placed later in
    // the file) would leave this specific route unprotected.
""")

# ------------------------------------------------------------------
# 3. Error-handling middleware — the special 4-argument signature
# ------------------------------------------------------------------
ERROR_HANDLING_EXAMPLE = textwrap.dedent("""\
    // Error-handling middleware is IDENTIFIED by Express via its FOUR
    // arguments (err, req, res, next) — must be registered LAST, after
    // all other routes/middleware.
    app.use((err, req, res, next) => {
        console.error(err.stack);
        res.status(err.statusCode || 500).json({
            error: err.message || 'Internal server error',
        });
    });

    // A helper to avoid repeating try/catch in every async route handler:
    function asyncHandler(fn) {
        return (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next);
    }

    // Usage — errors are now AUTOMATICALLY forwarded to error-handling
    // middleware, no manual try/catch needed in each route:
    app.get('/api/agents/:id', asyncHandler(async (req, res) => {
        const agent = await db.findAgent(req.params.id);   // if this
                                                              // throws, asyncHandler
                                                              // catches and forwards it
        res.json(agent);
    }));
""")

# ------------------------------------------------------------------
# 4. The event loop, illustrated conceptually
# ------------------------------------------------------------------
EVENT_LOOP_NOTE = textwrap.dedent("""\
    // GOOD: async I/O doesn't block the event loop — other requests
    // continue being processed WHILE this database query is in flight.
    app.get('/api/data', async (req, res) => {
        const data = await db.query('SELECT * FROM large_table');  // NON-BLOCKING
        res.json(data);
    });

    // BAD: synchronous, CPU-heavy work blocks the ENTIRE event loop —
    // EVERY other concurrent request (even unrelated ones) stalls until
    // this loop finishes, a fundamentally different problem than a slow
    // async I/O call.
    app.get('/api/compute-heavy', (req, res) => {
        let result = 0;
        for (let i = 0; i < 10_000_000_000; i++) { result += i; }  // BLOCKS everything
        res.json({ result });
    });

    // The FIX for genuine CPU-heavy work: offload to a Worker Thread or
    // a separate process/service, keeping the main event loop free to
    // handle other requests.
""")


if __name__ == "__main__":
    print(EXPRESS_BASIC_EXAMPLE)
    print(AUTH_MIDDLEWARE_EXAMPLE)
    print(ERROR_HANDLING_EXAMPLE)
    print(EVENT_LOOP_NOTE)

"""
PRODUCTION CONTEXT EXAMPLE:
An Express-based BFF (Backend for Frontend, this repo's API Design
Notes L05 covers the pattern generally) aggregating calls to several
backend microservices handles hundreds of concurrent requests
efficiently on a single Node process, since its workload is almost
entirely async I/O (waiting on those downstream service calls) — when a
new feature requiring genuine CPU-heavy image processing is added, the
team deliberately offloads it to a separate worker service rather than
processing it inline, specifically to avoid that heavy computation
blocking the event loop and degrading the BFF's otherwise-efficient
handling of every OTHER concurrent request.
"""
