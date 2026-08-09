#!/usr/bin/env bash
# WHAT: Four realistic containerization problems, each solved with THREE
#       genuinely different, individually defensible approaches drawn
#       from L01-L08 -- with an explicit comparison table and reasoning
#       for why each answer is valid under different constraints, in the
#       same spirit as this repo's theory-domain capstones.
# WHY:  "What's the right way to containerize X" is usually malformed
#       without knowing the actual constraint (image size, build time,
#       security posture, runtime environment) -- L01-L08 gave you the
#       primitives; this lesson is about choosing between them under
#       real pressure.
# LEVEL: Capstone -- read after L01-L08.
#
# This file is reference material -- not meant to be executed top-to-
# bottom. Before checking each comparison table, try reconstructing it
# yourself using only L01-L08's concepts.

: <<'CASE_STUDY_1'
============================================================================
CASE STUDY 1 -- SHIPPING A PYTHON ML INFERENCE SERVICE WITH LARGE MODEL
WEIGHTS (2GB+) AND HEAVY NATIVE DEPENDENCIES (CUDA, cuDNN)
============================================================================

SETUP: an inference service needs PyTorch + CUDA + a 2GB model checkpoint,
deployed to a GPU-enabled Kubernetes cluster, with both fast rolling
deployments and reasonable image-pull time as goals.

----------------------------------------------------------------------
APPROACH A: A single-stage image, `FROM nvidia/cuda:...` base, pip
install everything, COPY the model weights in directly (L02)
----------------------------------------------------------------------
  WHY VALID: simplest possible Dockerfile -- one stage, linear, easy for
  a new team member to read top to bottom and understand exactly what's
  in the final image, with no multi-stage COPY --from indirection to
  trace through.
  COST: the final image bundles build-time-only tooling (compilers, pip
  build dependencies for any package needing compilation) that's never
  needed at RUNTIME -- per L03's multi-stage discussion, this bloats the
  final image well beyond what's actually needed to run the service,
  directly increasing image-pull time on every node a pod schedules to,
  a real, recurring cost at deploy time.

----------------------------------------------------------------------
APPROACH B: Multi-stage build (L03) -- a builder stage installs/compiles
dependencies, a slim final stage copies only the installed Python
packages and model weights
----------------------------------------------------------------------
  WHY VALID: directly fixes A's bloat problem -- the final image
  contains only runtime-necessary files, meaningfully smaller and
  faster to pull, exactly the pattern L03 is built around.
  COST: the CUDA/cuDNN runtime libraries themselves are large and can't
  be trivially "slimmed away" the way build tooling can -- multi-stage
  builds help most with build-tool bloat, but a GPU-inference image's
  floor size is still dominated by CUDA runtime + model weights, which
  multi-staging alone doesn't shrink; the win here is real but bounded.

----------------------------------------------------------------------
APPROACH C: Multi-stage build for the CODE/dependencies, but keep the
2GB model weights OUT of the image entirely -- mount them via a
persistent volume (L05) or fetch them at container startup from object
storage
----------------------------------------------------------------------
  WHY VALID: decouples the (frequently-changing) application code image
  from the (large, less-frequently-changing) model weights -- a code-
  only deploy becomes fast (small image, quick pull) since it doesn't
  re-transfer 2GB of weights every rollout, and the SAME weights can be
  shared/cached across multiple pods via a shared volume rather than
  duplicated inside every pod's image layer.
  COST: adds a genuine startup-time dependency on an external fetch (or
  a volume being correctly mounted/populated) -- if that fetch is slow
  or fails, pod startup is slower or breaks in a way a fully self-
  contained image (A or B) wouldn't be exposed to, and correctly
  version-pinning "which model weights go with which code image" now
  needs explicit tracking rather than being implicit in one image tag.

COMPARISON TABLE (Case Study 1):
  | Approach | Image size | Deploy speed (code-only changes) | Startup reliability | Weight/code version coupling |
  |----------|----------------|----------------------------------------|---------------------------|------------------------------------|
  | A: single-stage | Largest | Slowest | Highest (self-contained) | Implicit (one image) |
  | B: multi-stage | Smaller | Faster | Highest (self-contained) | Implicit (one image) |
  | C: multi-stage + external weights | Smallest (image itself) | Fastest | Depends on fetch/mount reliability | Explicit (must be tracked) |
  B is close to a mandatory baseline regardless of scale; C is the
  right next step specifically once code deploys are frequent enough
  that re-shipping unchanged model weights on every rollout becomes a
  measured bottleneck.
CASE_STUDY_1

: <<'CASE_STUDY_2'
============================================================================
CASE STUDY 2 -- NETWORKING TOPOLOGY FOR A LOCAL MULTI-SERVICE DEV
ENVIRONMENT (API + WORKER + POSTGRES + REDIS)
============================================================================

SETUP: a local development setup (L06's Compose lesson) needs the API
service to reach Postgres/Redis, the worker to reach the same, and a
developer's host machine to be able to hit the API directly for testing.

----------------------------------------------------------------------
APPROACH A: One flat default Compose network -- every service on the
same bridge network (L04, L06)
----------------------------------------------------------------------
  WHY VALID: simplest possible topology -- every service can reach
  every other service by container name, zero network configuration
  beyond Compose's default behavior, minimal cognitive overhead for a
  small, trusted local dev setup.
  COST: no network-level isolation between services that arguably
  shouldn't need to talk to each other directly (e.g. does the worker
  really need direct network reachability to the API service, or only
  to Postgres/Redis?) -- fine for local dev, but a habit that, if
  carried unchanged into a security-conscious production Compose/
  Kubernetes setup, reflects poor practice (L04's network-isolation
  principles).

----------------------------------------------------------------------
APPROACH B: Multiple Compose networks -- a "backend" network (API,
worker, Postgres, Redis) and no host-exposed ports except the API's,
explicitly modeling which services should reach which (L04, L06)
----------------------------------------------------------------------
  WHY VALID: makes the INTENDED communication topology explicit and
  enforced at the network layer, not just "everything can technically
  reach everything, please don't" -- a genuinely useful habit-forming
  practice that mirrors production network-segmentation discipline
  (L04) even in a local dev environment.
  COST: more Compose YAML to write and maintain, and a genuine new-
  developer-onboarding question of "why can't my new service reach the
  database" if the network topology isn't clearly documented alongside
  the compose file -- friction that a flat network (A) simply doesn't
  have.

----------------------------------------------------------------------
APPROACH C: Run Postgres/Redis as separate, persistent, NAMED containers
outside the project's own Compose file entirely (started once, shared
across multiple projects' Compose setups via an external network, L04)
----------------------------------------------------------------------
  WHY VALID: avoids re-creating (and re-seeding, re-migrating) Postgres/
  Redis every time a project's Compose stack is torn down and rebuilt --
  a real time-saver for a developer working across MULTIPLE projects
  that all want a local Postgres/Redis, sharing one long-lived instance
  rather than each project running its own.
  COST: breaks Compose's normal "one `docker compose up` gives you a
  fully self-contained environment" convenience -- a new developer must
  ALSO know to start the shared external services first, a real, easy-
  to-forget setup step this approach introduces that A and B don't have,
  and cross-project data isolation (does project X's test data leak
  into project Y's local Postgres) becomes something to actively manage.

COMPARISON TABLE (Case Study 2):
  | Approach | Isolation clarity | Onboarding friction | Cross-project resource reuse |
  |----------|------------------------|---------------------------|------------------------------------|
  | A: flat network | None | Lowest | No |
  | B: segmented networks | Good | Medium | No |
  | C: shared external containers | N/A (different problem) | Highest (extra step) | Yes |
  A and B are both reasonable for a SINGLE project's local dev setup
  (B teaches better habits); C solves a genuinely different problem
  (resource reuse ACROSS projects) and is usually adopted later, once a
  developer feels the actual pain of repeatedly re-seeding databases
  across many projects' Compose stacks.
CASE_STUDY_2

: <<'CASE_STUDY_3'
============================================================================
CASE STUDY 3 -- HARDENING A CONTAINER IMAGE FOR A PUBLIC-FACING WEB
SERVICE (L07)
============================================================================

SETUP: a public-facing API container needs to minimize its attack
surface -- this case study is specifically about HOW FAR to take
hardening, since every additional restriction has a real operational
cost.

----------------------------------------------------------------------
APPROACH A: Run as a non-root user, drop unnecessary capabilities
(`--cap-drop ALL`), otherwise a normal, full-featured base image (L07)
----------------------------------------------------------------------
  WHY VALID: addresses the highest-leverage, lowest-friction hardening
  wins first -- per L07, running as root inside a container is a
  well-documented, high-impact risk (a container-escape vulnerability
  combined with root privileges is far more dangerous than the same
  vulnerability under a restricted user), and this is cheap to apply
  with minimal risk of breaking legitimate application behavior.
  COST: the base image still contains a full shell, package manager,
  and general-purpose OS tooling -- genuinely useful for `kubectl exec`-
  based debugging in production, but also USABLE BY AN ATTACKER who
  achieves code execution inside the container, a real remaining attack-
  surface cost this approach doesn't address.

----------------------------------------------------------------------
APPROACH B: A, PLUS `--read-only` root filesystem and a minimal
(distroless or Alpine-based) image with no shell at all (L07)
----------------------------------------------------------------------
  WHY VALID: meaningfully shrinks the attack surface further -- no shell
  means many common post-exploitation techniques (an attacker "just"
  getting a shell and pivoting from there) don't directly work, and a
  read-only root filesystem prevents an attacker from writing/persisting
  malicious files inside the running container at all.
  COST: directly breaks `kubectl exec -it <pod> -- /bin/sh`-style
  interactive debugging (there's no shell to exec into) -- teams
  choosing this approach need an alternative debugging strategy
  (ephemeral debug containers attached to the same pod, or comprehensive
  enough logging/tracing that live shell access is rarely needed), a
  real operational workflow change, not a purely additive security win.

----------------------------------------------------------------------
APPROACH C: B, PLUS a restrictive seccomp profile and running under a
gVisor/Kata-style sandboxed container runtime rather than standard runc
----------------------------------------------------------------------
  WHY VALID: seccomp profiles (L07) restrict which SYSCALLS the
  container can make at all (not just filesystem/capability
  restrictions), directly narrowing the kernel attack surface a
  container-escape exploit could target, and a sandboxed runtime adds
  an entire additional isolation layer between the container and the
  host kernel -- the strongest defense-in-depth of the three options,
  genuinely appropriate for a service handling untrusted input in a
  hostile-multi-tenant environment.
  COST: seccomp profiles are genuinely fragile to maintain -- an
  overly-restrictive profile can break legitimate application behavior
  in ways that only surface at RUNTIME (a syscall the app needs, blocked,
  causing a mysterious failure), requiring careful profiling/testing to
  get right; sandboxed runtimes also carry a real, measurable performance
  overhead versus standard runc, a cost that must be justified by the
  actual threat model, not applied reflexively to every service.

COMPARISON TABLE (Case Study 3):
  | Approach | Attack-surface reduction | Debuggability | Performance cost | Maintenance burden |
  |----------|-------------------------------|--------------------|------------------------|---------------------------|
  | A: non-root + dropped caps | Good, cheap | Full (shell available) | None | Low |
  | B: A + read-only + no-shell | Better | Reduced (needs new workflow) | None | Medium |
  | C: B + seccomp + sandboxed runtime | Best | Reduced | Real, measurable | Highest |
  A is close to a mandatory baseline for ANY public-facing service; B
  is well worth the debugging-workflow change for genuinely sensitive
  services; C is justified specifically by a hostile-multi-tenant or
  high-value-target threat model, not applied by default everywhere.
CASE_STUDY_3

: <<'CASE_STUDY_4'
============================================================================
CASE STUDY 4 -- MANAGING CONFIGURATION THAT DIFFERS ACROSS DEV/STAGING/
PRODUCTION ENVIRONMENTS
============================================================================

SETUP: the same application image needs different config (database URLs,
feature flags, log levels) depending on which environment it's deployed
to, and the team wants to avoid building separate images per environment.

----------------------------------------------------------------------
APPROACH A: Environment variables, injected at container run time
(`docker run -e` / Compose's `environment:` / Kubernetes env vars, L02,
L06, L08)
----------------------------------------------------------------------
  WHY VALID: the standard, most portable mechanism -- works identically
  across Docker, Compose, and Kubernetes, requires zero image rebuilds
  to change config, and is directly supported by essentially every
  application framework/library's configuration-loading conventions
  (L08's production-patterns discussion).
  COST: environment variables are FLAT strings -- genuinely awkward for
  deeply nested or structured configuration (a complex feature-flag
  hierarchy, multi-level settings), and there's no built-in mechanism
  distinguishing SENSITIVE values (a database password) from ordinary
  config (a log level) -- both just end up as env vars unless additional
  discipline (secrets-specific handling, L07/Kubernetes Notes) is
  layered on top deliberately.

----------------------------------------------------------------------
APPROACH B: Mounted config files, one per environment, selected via a
volume mount pointing at the right file (L05, L06)
----------------------------------------------------------------------
  WHY VALID: naturally supports STRUCTURED configuration (JSON/YAML/TOML
  files with real nesting) far more cleanly than flat env vars, and
  keeps a full, versionable, diffable config file per environment that's
  easy to review in a pull request the way a scattered set of env-var
  assignments across deploy scripts often isn't.
  COST: requires the volume-mount/file-selection mechanism itself to be
  correctly wired per environment (L05) -- a real, additional piece of
  deployment machinery beyond just setting env vars, and mistakenly
  mounting the WRONG environment's config file is a distinct, real
  failure mode (a mounting/wiring bug) that pure env-var injection
  doesn't have an equivalent of.

----------------------------------------------------------------------
APPROACH C: Bake environment-specific config INTO separate image tags
(one image build per environment, config compiled in at build time)
----------------------------------------------------------------------
  WHY VALID: config is validated at BUILD time (a malformed config
  fails the build, not a live deploy) and the exact configuration any
  given image contains is fully deterministic and auditable just by
  inspecting that image -- a genuine correctness/auditability advantage
  neither A nor B fully provides (both can be RUNTIME-overridden after
  the fact, which is a feature for flexibility but a liability for
  strict auditability).
  COST: directly contradicts this case study's stated goal ("avoid
  building separate images per environment") -- multiplies build/CI
  time and artifact count by the number of environments, and risks the
  team accidentally testing a DIFFERENT image in staging than the one
  that eventually reaches production (since they're now genuinely
  different artifacts, not the same image with different runtime
  config) -- a real "did we actually test what we're shipping" risk
  this specific case study's premise was trying to avoid.

COMPARISON TABLE (Case Study 4):
  | Approach | Structured config support | Build/deploy simplicity | Config-validation timing | Same-artifact guarantee |
  |----------|---------------------------------|-------------------------------|--------------------------------|-------------------------------|
  | A: env vars | Poor (flat only) | Simplest | Runtime (can fail late) | Yes (one image) |
  | B: mounted config files | Good | Medium (mount wiring) | Runtime (can fail late) | Yes (one image) |
  | C: baked-in per-environment images | Best | Worst (N builds) | Build time (fails early) | No (different images) |
  Given this case study's explicit constraint (avoid per-environment
  images), A or B are the right family of answers; A for simple flat
  config, B once configuration genuinely needs real structure/nesting
  that env vars represent awkwardly.
CASE_STUDY_4

echo "This file is reference material -- see the WHAT/WHY header and the"
echo "four case studies in the heredoc blocks above (not meant to be run)."
