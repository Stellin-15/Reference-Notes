# Bash & Scripting — Principal Engineer Deep Dive

Companion to L01-L14. Narrative depth, then a comprehensive common-to-
uncommon reference.


## Quoting, Word Splitting & the Bugs They Cause

**Beyond the lesson**: The single most common source of real production
bash bugs is UNQUOTED variable expansion — `rm $file` where `$file`
contains a space or glob character undergoes word splitting AND
pathname expansion, potentially deleting far more than intended (or
erroring confusingly). `rm "$file"` prevents both. This isn't pedantry —
`shellcheck` (see below) exists largely BECAUSE this class of bug is so
common and so dangerous specifically in scripts that touch the
filesystem/run destructive commands.

**Worked example**: `set -euo pipefail` at the top of a production script
is the standard defensive header, and each flag matters for a different
failure mode: `-e` (exit immediately on any command's non-zero exit,
instead of silently continuing past a failure), `-u` (error on an
undefined variable reference instead of silently expanding to an empty
string — catches typos like `$FILE_PTH`), `-o pipefail` (a pipeline's
exit status reflects the FIRST failing command, not just the last one —
without this, `cmd_that_fails | grep something` reports success because
`grep`'s exit code is all that's checked by default).

**Interview Q&A**:
- *Q: A script with `set -e` still continued after a command failed. Why?* A: `-e` doesn't trigger inside conditionals (`if failing_cmd; then`), inside a pipeline except the LAST command (without `pipefail`), inside `&&`/`||` chains, or inside a function called as part of a condition — these are real, commonly-hit exceptions to `-e`'s behavior that trip up even experienced script authors.


## Process Substitution & Advanced Redirection

**Beyond the lesson**: Process substitution (`<(command)`) lets you use a
command's OUTPUT as if it were a FILE, without an explicit temp file —
`diff <(sort file1) <(sort file2)` compares two sorted streams without
ever writing an intermediate sorted file to disk. This works because bash
creates a named pipe (or `/dev/fd/N` on systems supporting it) behind the
scenes — genuinely useful in production scripts that need to avoid
temp-file cleanup complexity/race conditions.

**Interview Q&A**:
- *Q: Why does `cmd | while read line; do var=$line; done; echo $var` print nothing, even though the loop clearly sets `var`?* A: The pipeline runs the `while` loop in a SUBSHELL (each pipeline stage gets its own process) — variables set inside a subshell don't propagate back to the parent shell; the fix is either restructuring to avoid the pipe (`while read line; do ...; done < <(cmd)` using process substitution instead) or using `shopt -s lastpipe` (bash-specific, runs the last pipeline stage in the current shell).


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Static analysis & testing
- **ShellCheck** — the near-universal bash linter, catches quoting bugs,
  unused variables, and dozens of other real footguns — should be a
  standard CI step for any repo with production bash scripts, genuinely
  catches bugs before they become incidents.
- **bats (Bash Automated Testing System)** — a real unit-testing framework
  for bash scripts, letting you write `@test` blocks with assertions —
  used when a script is complex/critical enough to warrant actual test coverage rather than manual verification.

### Text processing power tools beyond grep/sed/awk
- **jq** — the standard tool for JSON manipulation in shell scripts/CI
  pipelines — genuinely essential once scripts start consuming API
  responses or structured config.
- **yq** — the YAML equivalent of jq, common in Kubernetes/CI-config-manipulating scripts.
- **xargs** — builds and executes commands from stdin, the standard way
  to parallelize/batch operations (`find . -name "*.log" | xargs -P4 gzip`
  runs gzip on 4 files in parallel) — a real, common performance technique
  for shell-based batch processing.
- **parallel (GNU parallel)** — a more feature-rich alternative to xargs
  for genuinely complex parallel command execution with progress
  tracking/job control.

### Scripting language alternatives, and when to actually switch
- **When bash stops being the right tool** — once a script needs real
  data structures beyond arrays/associative arrays, proper error handling
  beyond exit codes, or meaningful test coverage, the honest answer is
  usually "rewrite this in Python" — a genuinely important engineering
  judgment call, since bash's error-proneness scales badly with script
  complexity in a way Python/Go doesn't.
- **Make** — still genuinely common as a lightweight task-runner/build
  orchestrator even outside its original C-compilation use case (a
  `Makefile` with phony targets as a project's "here are the common
  commands" entry point) — worth knowing as a real, still-relevant tool
  beyond its historical niche.

### Debugging techniques
- **`bash -x` / `set -x`** — trace every command as it executes, the
  standard first debugging step for a script doing something unexpected.
- **`trap` for cleanup** — `trap 'cleanup_function' EXIT` guarantees a
  cleanup function runs whether the script exits normally, errors out, or
  is interrupted (Ctrl+C) — the correct way to ensure temp files/locks are
  always released, rather than relying on the script reaching its normal end unmodified.


## NICHE BUT REAL

- **Here-docs vs here-strings** — `<<EOF...EOF` (multi-line input) vs
  `<<<"string"` (single value as stdin) — the here-string form is a real,
  underused convenience for feeding a single variable to a command
  expecting stdin without a subshell/pipe.
- **Parameter expansion tricks** — `${var:-default}` (use default if
  unset/empty), `${var:?error message}` (error out with a message if
  unset), `${var%pattern}`/`${var#pattern}` (strip a suffix/prefix without
  calling out to `sed`/`basename`) — genuinely useful, often-unknown
  built-in string manipulation that avoids spawning extra processes.
- **Exit code conventions** — 0 (success), 1 (general error), 2 (misuse
  of shell builtins), 126 (command found but not executable), 127
  (command not found), 128+N (terminated by signal N) — worth knowing
  these aren't arbitrary; scripts checking `$?` against specific values
  should know what each actually signals.
- **POSIX sh vs bash-specific features** — arrays, `[[ ]]` (vs POSIX
  `[ ]`), and `local` are bash extensions NOT guaranteed present in a
  minimal `/bin/sh` (dash on Debian/Ubuntu, for instance) — a script with
  a `#!/bin/sh` shebang using bash-only syntax will fail or misbehave on
  systems where `/bin/sh` isn't actually bash, a real, recurring
  cross-distro portability bug.
