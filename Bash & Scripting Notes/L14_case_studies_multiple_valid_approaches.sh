#!/usr/bin/env bash
# WHAT: Four realistic shell-scripting/automation problems, each solved
#       with THREE genuinely different, individually defensible
#       approaches drawn from L01-L13 -- with an explicit comparison
#       table and reasoning for why each answer is valid under different
#       constraints.
# WHY:  "Bash or a real programming language," "how defensive should
#       error handling be," "cron or a scheduler" are all questions
#       L01-L13 gave you real tools for, not one universal answer -- this
#       lesson is about the decision process under real script-
#       criticality and team-maintainability constraints.
# LEVEL: Capstone -- read after L01-L13.
#
# This file is reference material -- not meant to be executed top-to-
# bottom. Before checking each comparison table, try reconstructing it
# yourself using only L01-L13's concepts.

: <<'CASE_STUDY_1'
============================================================================
CASE STUDY 1 -- CHOOSING BASH VS. A "REAL" PROGRAMMING LANGUAGE FOR A NEW
AUTOMATION TASK (A DAILY LOG-ROTATION AND ARCHIVAL SCRIPT)
============================================================================

SETUP: a new script needs to find, compress, and archive old log files
across several directories, with some conditional logic based on file
age and disk space -- the team is deciding whether Bash is the right
tool at all.

----------------------------------------------------------------------
APPROACH A: Write it in Bash (L08, L13)
----------------------------------------------------------------------
  WHY VALID: per L08/L13, this task is FUNDAMENTALLY a sequence of file-
  system operations and external command invocations (find, gzip, mv,
  df) -- exactly Bash's strongest natural fit, since it composes
  external Unix tools with minimal ceremony, and the script runs
  anywhere a shell is available with no additional runtime/interpreter
  dependency to install.
  COST: per L07's error-handling discussion, Bash's error handling is
  genuinely more primitive than a general-purpose language's exception
  system -- a subtly wrong `[[ ]]` condition or an unquoted variable
  with a space in a filename (a classic, well-documented Bash pitfall)
  can cause silent, hard-to-notice bugs in exactly the kind of file-
  deletion/archival logic where a silent bug is genuinely costly.

----------------------------------------------------------------------
APPROACH B: Write it in Python instead
----------------------------------------------------------------------
  WHY VALID: Python's standard library (pathlib, shutil, os) handles
  file operations with much stronger error handling (real exceptions,
  not just exit codes to remember to check) and more readable,
  maintainable conditional logic than equivalent Bash -- for logic with
  genuine complexity (multiple conditions, edge cases around disk
  space thresholds), Python code is generally easier for a team to
  read, test, and modify safely over time.
  COST: adds a Python runtime dependency to whatever environment this
  script runs in (relevant if this needs to run on minimal/embedded
  systems where Bash is guaranteed present but Python might not be),
  and for a task this fundamentally shell-command-centric, Python code
  often ends up calling `subprocess` for some operations anyway,
  arguably losing some of Bash's natural fit for orchestrating external
  tools.

----------------------------------------------------------------------
APPROACH C: Bash (A), but written with L07's full defensive-scripting
discipline applied rigorously -- `set -euo pipefail`, careful quoting
of every variable, explicit error traps, and clear logging of every
action taken (L07, L12)
----------------------------------------------------------------------
  WHY VALID: per L07/L12, this directly addresses A's stated weakness
  (fragile, silent-failure-prone error handling) without giving up A's
  genuine fit for the underlying file-operation-heavy task -- `set
  -euo pipefail` alone eliminates a large class of "script continues
  after a command silently failed" bugs, and disciplined quoting
  eliminates the word-splitting/filename-with-spaces pitfall.
  COST: requires the team to actually KNOW and consistently APPLY this
  defensive discipline -- unlike B, where some of these protections
  (real exceptions, no implicit word-splitting) are the LANGUAGE's
  default behavior, Bash's safety here is opt-in and easy to forget on
  any GIVEN line of a growing script, a real, ongoing discipline
  requirement rather than a structural guarantee.

COMPARISON TABLE (Case Study 1):
  | Approach | Fit for shell-command-heavy logic | Error-handling robustness | Requires ongoing discipline |
  |----------|------------------------------------------|---------------------------------|------------------------------------|
  | A: plain Bash | Best | Weakest | High (easy to get wrong) |
  | B: Python | Good (via subprocess) | Best (language default) | Low (safety is structural) |
  | C: Bash + rigorous defensive discipline | Best | Good, if discipline holds | High |
  For a task this centered on orchestrating file-system commands, C is
  the strongest answer specifically IF the team has and maintains the
  discipline L07 teaches; B is the safer default for a team that can't
  fully guarantee that ongoing discipline, or for logic complex enough
  that Python's readability/testability advantage outweighs Bash's
  natural command-orchestration fit.
CASE_STUDY_1

: <<'CASE_STUDY_2'
============================================================================
CASE STUDY 2 -- SCHEDULING A RECURRING SCRIPT (CRON VS. ALTERNATIVES)
============================================================================

SETUP: the log-rotation script from Case Study 1 needs to run daily;
deciding how to schedule it.

----------------------------------------------------------------------
APPROACH A: A plain cron job (L10-adjacent process-management
discussion, L13)
----------------------------------------------------------------------
  WHY VALID: the simplest, most universally-available scheduling
  mechanism on any Unix-like system -- zero additional infrastructure,
  and for a genuinely simple, single-machine, non-critical scheduled
  task, cron's basic guarantees (run at this time, on this machine) are
  entirely sufficient.
  COST: cron provides NO built-in retry logic, no alerting if the job
  fails silently, and no visibility beyond whatever logging the script
  itself produces -- if the script fails (or the machine is down at the
  scheduled time), nothing NOTICES unless someone is actively watching
  logs, a real, common source of "we didn't realize this had been
  silently failing for two weeks" incidents.

----------------------------------------------------------------------
APPROACH B: A systemd timer (an alternative to cron on systemd-based
Linux systems) with `OnFailure=` configured to trigger an alert
----------------------------------------------------------------------
  WHY VALID: per L04's systemd-adjacent process-management concepts,
  systemd timers provide meaningfully better observability than plain
  cron -- built-in logging via journald, explicit failure-handling
  hooks, and dependency management (e.g. "only run if this other
  service is active") that cron lacks entirely.
  COST: systemd-specific -- doesn't work identically across all Unix-
  like systems (a real portability constraint if this script needs to
  run on non-systemd systems, containers without systemd, or macOS),
  and has a genuinely steeper configuration syntax/learning curve than
  cron's simple crontab line for a team unfamiliar with systemd units.

----------------------------------------------------------------------
APPROACH C: A workflow orchestrator (Airflow, or Data Engineering
Notes' broader orchestration tooling) even for this single, simple
script
----------------------------------------------------------------------
  WHY VALID: if the ORGANIZATION already runs a workflow orchestrator
  for other scheduled jobs, adding this script as one more scheduled
  task reuses EXISTING monitoring, alerting, and retry infrastructure
  the team already operates and trusts -- avoids building yet another,
  separate scheduling/alerting mechanism (cron+custom alerting, or
  systemd timers) just for this one script.
  COST: standing up a full workflow orchestrator PURELY for one simple
  daily log-rotation script (if none already exists) would be
  significant, unjustified overkill -- real infrastructure and
  operational complexity vastly disproportionate to this task's actual
  needs, appropriate only as a "reuse what already exists" answer, not
  as a reason to adopt orchestration tooling from scratch.

COMPARISON TABLE (Case Study 2):
  | Approach | Failure visibility | Portability | Fits "we already have this infra" |
  |----------|-------------------------|-----------------|-------------------------------------------|
  | A: plain cron | Poor (silent failures) | Best | N/A |
  | B: systemd timer + OnFailure | Good | Limited to systemd systems | N/A |
  | C: existing workflow orchestrator | Best | N/A (reuses existing tooling) | Only if it already exists |
  For a genuinely simple, standalone script on a systemd-based Linux
  system, B is the strongest standalone answer (meaningfully better
  observability than A for modest added complexity); C is right ONLY
  when the organization already operates orchestration tooling this
  script can piggyback on, never as a reason to adopt it fresh for one
  task this size.
CASE_STUDY_2

: <<'CASE_STUDY_3'
============================================================================
CASE STUDY 3 -- PROCESSING A LARGE LOG FILE TO EXTRACT AND SUMMARIZE
ERROR PATTERNS
============================================================================

SETUP: a multi-gigabyte application log file needs to be searched for
error patterns, counted by type, and summarized -- a one-off
investigative task, not a recurring pipeline.

----------------------------------------------------------------------
APPROACH A: A chain of Unix text-processing tools -- grep, awk, sort,
uniq -c (L09)
----------------------------------------------------------------------
  WHY VALID: per L09, this is EXACTLY the kind of task Unix text tools
  excel at -- a single pipeline (`grep ERROR file.log | awk '{print
  $5}' | sort | uniq -c | sort -rn`) can extract, categorize, and count
  patterns from a multi-gigabyte file in one pass, streaming through the
  data without loading it all into memory, genuinely fast and
  appropriate for this exact task shape.
  COST: per L09, complex, multi-field extraction/transformation logic
  can become a genuinely hard-to-read, hard-to-modify pipeline of
  chained tools with cryptic awk/sed syntax -- for anything beyond
  fairly simple field extraction and counting, this readability cost
  becomes real, especially for a team member less fluent in awk/sed
  specifically.
  --
APPROACH B: Load the log file into Python with pandas for analysis
----------------------------------------------------------------------
  WHY VALID: pandas provides much richer, more readable analysis
  capabilities (grouping, complex conditional filtering, easy
  visualization if needed) than a chained shell pipeline -- genuinely
  better suited if the investigation needs iterative, exploratory
  analysis (try one grouping, then another, based on what the data
  shows) rather than one fixed extraction pipeline decided upfront.
  COST: loading a multi-gigabyte file entirely into a pandas DataFrame
  can be genuinely memory-intensive (per Python Notes L06's
  memory/performance discussion) -- depending on the actual file size
  and available memory, this can be slow or even infeasible without
  chunked reading, a real practical constraint the streaming shell-
  pipeline approach (A) doesn't share.
  --
APPROACH C: Use `awk` alone for the extraction/counting (leveraging
its native ability to do grouping/counting internally in one pass,
L09), reserving Python only for any FINAL visualization/reporting step
on the much-smaller, already-summarized output
----------------------------------------------------------------------
  WHY VALID: per L09, awk can do grouping/counting NATIVELY within a
  single pass (associative arrays), often more efficiently than
  chaining multiple separate tools (A) AND without B's full-file-in-
  memory cost -- reserves the richer, more readable tooling (Python)
  for the step that actually benefits from it (formatting/visualizing
  a summary that's now small enough to trivially load), rather than
  using Python for something a streaming tool handles more efficiently.
  COST: still requires genuine awk proficiency to write the grouping/
  counting logic correctly and readably -- a real skill/team-
  familiarity dependency, and for someone unfamiliar with awk's
  associative-array patterns, this can be harder to write correctly on
  a first attempt than equivalent (if less efficient) pandas code.

COMPARISON TABLE (Case Study 3):
  | Approach | Memory efficiency on a multi-GB file | Readability for complex logic | Fits exploratory, iterative analysis |
  |----------|--------------------------------------------|--------------------------------------|---------------------------------------------|
  | A: chained Unix tools | Best (streaming) | Poor, for complex logic | Poor (fixed pipeline per attempt) |
  | B: pandas, full file in memory | Worst | Best | Best |
  | C: awk for extraction + Python for summary reporting | Best | Good (for the reporting step) | Medium |
  For a genuinely one-off investigation with straightforward pattern
  counting, A or C are both strong, efficient answers; B is the right
  choice specifically once the investigation becomes genuinely
  exploratory/iterative in a way that benefits from pandas's richer,
  more interactive analysis capabilities, and the file size is
  manageable (or chunked reading is used).
CASE_STUDY_3

: <<'CASE_STUDY_4'
============================================================================
CASE STUDY 4 -- HANDLING SECRETS (API KEYS) NEEDED BY A DEPLOYMENT SCRIPT
============================================================================

SETUP: a Bash deployment script needs an API key to authenticate against
a third-party service during deployment.

----------------------------------------------------------------------
APPROACH A: Hardcode the key directly in the script
----------------------------------------------------------------------
  WHY VALID: essentially never actually valid in a real production
  context -- included here only to name it explicitly as the baseline
  to avoid; the ONLY marginal scenario where this is even defensible is
  a genuinely throwaway, single-use local script never committed to
  version control or shared with anyone.
  COST: per L12's configuration-loading discussion and basic security
  hygiene, hardcoded secrets are a severe, well-documented risk -- if
  this script is ever committed to version control (even briefly,
  even in a private repo), the secret is now in git history
  permanently unless the history itself is rewritten, and anyone with
  read access to the script has the credential.

----------------------------------------------------------------------
APPROACH B: Load the key from an environment variable, set outside the
script (`.env` file loaded via L12's pattern, or set by the CI/CD
platform's own secret management, CICD Notes L07)
----------------------------------------------------------------------
  WHY VALID: per L12, this is the standard, straightforward fix --
  the secret never appears in the script's own source code at all,
  and if the script runs in CI/CD, it can draw on that platform's own
  secret-management/masking features (CICD Notes L07) to avoid the
  secret appearing in logs.
  COST: the secret still needs to exist SOMEWHERE as a static value
  (in a `.env` file, in CI/CD platform secret storage) -- per CICD
  Notes L07's OIDC discussion, a static secret (however well it's kept
  out of the script itself) remains a long-lived credential that, if
  THAT storage location is compromised, is usable until manually
  rotated.

----------------------------------------------------------------------
APPROACH C: Use OIDC-based keyless authentication (CICD Notes L02, L07)
if the deployment target supports it, eliminating any static API key
entirely -- the script exchanges a short-lived platform-issued token
for temporary credentials at run time
----------------------------------------------------------------------
  WHY VALID: per CICD Notes L07, this is the strongest answer available
  -- there's no static secret to leak, hardcode, or need to rotate at
  all, directly eliminating the entire risk category B still carries
  (a leaked long-lived-if-unrotated static secret).
  COST: only available if the target service/deployment platform
  actually SUPPORTS OIDC federation -- a real prerequisite not every
  third-party service offers, and requires genuine one-time setup
  effort to configure the trust relationship correctly; for a service
  that only supports traditional API keys, this option simply isn't
  available and B remains the practical answer.

COMPARISON TABLE (Case Study 4):
  | Approach | Secret exposure risk | Setup effort | Availability |
  |----------|---------------------------|-------------------|-------------------|
  | A: hardcoded in script | Severe | None | Always "available," never advisable |
  | B: environment variable / CI secret store | Real, but contained | Low | Always available |
  | C: OIDC keyless auth | Minimal (no static secret) | Medium (trust config) | Only if the target service supports it |
  C is the strongest answer wherever available; B is the correct,
  reasonable fallback wherever OIDC isn't supported by the target
  service; A should be treated as essentially never acceptable outside
  a genuinely disposable, never-shared local script.
CASE_STUDY_4

echo "This file is reference material -- see the WHAT/WHY header and the"
echo "four case studies in the heredoc blocks above (not meant to be run)."
